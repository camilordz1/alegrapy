import copy
import logging
import math
import numbers
import re
import time
from typing import Any, Dict, List, Optional, Union

from alegra.actions import Actions, validate_id
from alegra.exceptions import AlegraAPIError, AlegraUnverifiedCreateError
from alegra.retry import _may_have_been_processed

logger = logging.getLogger("alegra")

_DEDUP_KEY_PATTERN = re.compile(r'[A-Za-z0-9_.:-]+')
_MARKER_PREFIX = "alegrapy:dedup:"
_MAX_OBSERVATIONS = 500
_VERIFY_INITIAL_INTERVAL = 1.0
_VERIFY_MAX_INTERVAL = 8.0


def _validate_dedup_key(dedup_key: Any) -> str:
    """Validate and strip a dedup key."""
    if not isinstance(dedup_key, str):
        raise ValueError("dedup_key must be a string")
    key = dedup_key.strip()
    if not 1 <= len(key) <= 64 or not _DEDUP_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "dedup_key must be 1..64 characters using letters, digits, '_', '.', ':' or '-'"
        )
    return key


def _marker_for(key: str) -> str:
    return f"{_MARKER_PREFIX}{key}"


def _validate_lookup_pages(lookup_pages: Any) -> int:
    if (isinstance(lookup_pages, bool) or not isinstance(lookup_pages, numbers.Integral)
            or lookup_pages < 1):
        raise ValueError("lookup_pages must be a positive integer")
    return int(lookup_pages)


def _validate_verify_window(verify_window: Any) -> float:
    if (isinstance(verify_window, bool) or not isinstance(verify_window, numbers.Real)
            or not math.isfinite(verify_window) or verify_window < 0):
        raise ValueError("verify_window must be a finite, non-negative number")
    return float(verify_window)


def _contains_marker(invoice: Any, marker: str) -> bool:
    if not isinstance(invoice, dict):
        return False
    observations = invoice.get("observations")
    if not isinstance(observations, str):
        return False
    return any(line.strip() == marker for line in observations.splitlines())


class Invoices(Actions):
    """Operations related to invoices (facturas de venta) endpoint."""
    endpoint: str = "invoices"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def reconcile(self, dedup_key: str, client_id: Union[int, str],
                  lookup_pages: int = 2) -> Optional[Dict[str, Any]]:
        """Return the newest invoice carrying ``dedup_key``, or ``None``.

        Scans the newest ``lookup_pages * 30`` invoices of the client (no ``status``
        filter, so drafts and open invoices are both considered). The marker is matched
        against the invoice's ``observations`` as a whole stripped line.

        Args:
            dedup_key (str): Key used when the invoice was created with ``create_once``.
            client_id (int or str): Client whose invoices are scanned.
            lookup_pages (int): Number of 30-record pages to scan (default 2).

        Returns:
            dict, optional: The matching invoice, or ``None`` when not found.

        Raises:
            ValueError: If the key, client id or ``lookup_pages`` are invalid.
        """
        key = _validate_dedup_key(dedup_key)
        pages = _validate_lookup_pages(lookup_pages)
        marker = _marker_for(key)
        valid_client_id = validate_id(client_id)

        for invoice in self.iter_all(max_items=pages * 30, client_id=valid_client_id,
                                     order_field="id", order_direction="DESC"):
            if _contains_marker(invoice, marker):
                return invoice
        return None

    def create_once(self, params: Dict[str, Any], dedup_key: str, *,
                    on_unverified: str = "retry", verify_window: float = 30.0,
                    lookup_pages: int = 2, precheck: bool = True) -> Any:
        """Create an invoice at most once per ``dedup_key``.

        A unique marker (``alegrapy:dedup:<key>``) is appended to ``observations`` and
        the invoice is looked up by that marker so re-runs return the existing record
        instead of creating a duplicate.

        Flow:

        1. With ``precheck``, look for the marker first; return the invoice if found.
        2. POST the payload. A non-ambiguous failure is raised unchanged.
        3. On an ambiguous failure (timeout, 5xx, dropped connection), look for the
           marker during ``verify_window`` seconds.
        4. If not found and ``on_unverified="retry"``, POST once more with the same
           payload, verify again, and otherwise raise
           :class:`AlegraUnverifiedCreateError`. Never more than 2 POSTs.
        5. With ``on_unverified="raise"``, raise the error right after the window.

        Limitations:
            ``"retry"`` reduces but does not eliminate duplicates: if Alegra shows the
            invoice later than ``verify_window``, a second invoice can be created. Use
            ``"raise"`` plus a quarantine queue for zero-duplicate flows. Two processes
            using the same key concurrently can both miss the precheck; serialize per
            key. The lookup only covers the newest ``lookup_pages * 30`` invoices of the
            client, and whether ``observations`` reaches the DIAN XML is unverified.
            ``query()`` itself may repeat a POST only when it provably was not sent
            (429 or ``request_not_sent``), which cannot create an extra invoice.

        Args:
            params (dict): Payload for ``create``; ``params["client"]`` (or
                ``params["client"]["id"]``) is required.
            dedup_key (str): Stable key for this logical creation, 1..64 chars of
                letters, digits, ``_``, ``.``, ``:`` or ``-``.
            on_unverified (str): ``"retry"`` (default) or ``"raise"``.
            verify_window (float): Seconds to look for the invoice after an ambiguous
                failure (default 30).
            lookup_pages (int): Pages of 30 invoices scanned on each lookup (default 2).
            precheck (bool): Look for the marker before posting (default True).

        Returns:
            Any: The created (or previously existing) invoice.

        Raises:
            ValueError: If the key, client id, options or observations length are
                invalid; nothing is sent.
            AlegraAPIError: The original error for a non-ambiguous failure.
            AlegraUnverifiedCreateError: When an ambiguous create cannot be verified.
        """
        key = _validate_dedup_key(dedup_key)
        if on_unverified not in ("retry", "raise"):
            raise ValueError("on_unverified must be 'retry' or 'raise'")
        window = _validate_verify_window(verify_window)
        pages = _validate_lookup_pages(lookup_pages)
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        payload = self._payload_with_marker(params, key)
        client_id = self._client_id_from(params)

        if precheck:
            existing = self.reconcile(key, client_id, lookup_pages=pages)
            if existing is not None:
                return existing

        attempts = 1
        try:
            return self.create(payload)
        except AlegraAPIError as error:
            if not _may_have_been_processed(error):
                raise
            last_error = error

        found = self._verified_lookup(key, client_id, pages, window, payload, attempts, last_error)
        if found is not None:
            return found
        if on_unverified == "raise":
            raise self._unverified_error(key, client_id, payload, attempts, last_error) from last_error

        logger.warning(
            f"POST - /{self.endpoint} - dedup key {key!r} unverified; "
            f"retrying create (attempt 2)"
        )
        attempts = 2
        try:
            return self.create(payload)
        except AlegraAPIError as error:
            if not _may_have_been_processed(error):
                # The first attempt may still have created the invoice, so quarantine it
                raise self._unverified_error(key, client_id, payload, attempts, error) from error
            last_error = error

        found = self._verified_lookup(key, client_id, pages, window, payload, attempts, last_error)
        if found is not None:
            return found
        raise self._unverified_error(key, client_id, payload, attempts, last_error) from last_error

    def _verified_lookup(self, key: str, client_id: Union[int, str], lookup_pages: int,
                         verify_window: float, payload: Dict[str, Any], attempts: int,
                         cause: AlegraAPIError) -> Optional[Dict[str, Any]]:
        """Run the verification window; wrap lookup failures as unverified creates."""
        try:
            return self._verify_until_found(key, client_id, lookup_pages, verify_window)
        except AlegraAPIError as lookup_error:
            raise self._unverified_error(key, client_id, payload, attempts, lookup_error,
                                         details_source=cause) from lookup_error

    def _verify_until_found(self, key: str, client_id: Union[int, str], lookup_pages: int,
                            verify_window: float) -> Optional[Dict[str, Any]]:
        """Look for the marker at increasing intervals until the window elapses."""
        deadline = time.monotonic() + verify_window
        interval = _VERIFY_INITIAL_INTERVAL
        lookup = 0

        while True:
            lookup += 1
            logger.warning(
                f"POST - /{self.endpoint} - verifying dedup key {key!r} (lookup {lookup})"
            )
            found = self.reconcile(key, client_id, lookup_pages=lookup_pages)
            if found is not None:
                return found

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, _VERIFY_MAX_INTERVAL)

    @staticmethod
    def _payload_with_marker(params: Dict[str, Any], key: str) -> Dict[str, Any]:
        """Build a copy of ``params`` with the dedup marker on its own line.

        Re-submitting a stored payload is safe: an existing identical marker is kept
        as-is instead of appended again, and a payload carrying a different dedup key is
        rejected.
        """
        payload = copy.deepcopy(params)
        existing = payload.get("observations")
        marker = _marker_for(key)

        if existing:
            lines = [line.strip() for line in str(existing).splitlines()]
            if marker in lines:
                return payload
            if any(line.startswith(_MARKER_PREFIX) for line in lines):
                raise ValueError("observations already contains a different dedup marker")
            observations = f"{existing}\n{marker}"
        else:
            observations = marker

        if len(observations) > _MAX_OBSERVATIONS:
            raise ValueError(
                f"observations would exceed {_MAX_OBSERVATIONS} characters with the dedup marker"
            )
        payload["observations"] = observations
        return payload

    @staticmethod
    def _client_id_from(params: Dict[str, Any]) -> Union[int, str]:
        """Read and validate the client id required for the dedup lookup."""
        client = params.get("client")
        raw = client.get("id") if isinstance(client, dict) else client
        if raw is None:
            raise ValueError(
                "params['client'] must provide the client id used for the dedup lookup"
            )
        return validate_id(raw)

    def _unverified_error(self, key: str, client_id: Union[int, str], payload: Dict[str, Any],
                          attempts: int, cause: AlegraAPIError,
                          details_source: Optional[AlegraAPIError] = None) -> AlegraUnverifiedCreateError:
        """Build the quarantine error carrying the last ambiguous error's HTTP details."""
        details = details_source if details_source is not None else cause
        return AlegraUnverifiedCreateError(
            f"Invoice creation unverified for dedup key {key!r}",
            dedup_key=key,
            client_id=client_id,
            resource=self.endpoint,
            payload=payload,
            attempts=attempts,
            status_code=details.status_code,
            response_body=details.response_body,
            retry_after=details.retry_after,
        )

    def send_email(self, id: Union[int, str], emails: Union[List[str], str], send_copy_to_user: bool = False,
                   subject: Optional[str] = None, message: Optional[str] = None) -> Any:
        """Send invoice by email.

        Args:
            id (int or str): Invoice ID.
            emails (list or str): Email address or list of email addresses to send to.
            send_copy_to_user (bool): Send a copy of the email to the user (default False).
            subject (str, optional): Custom email subject.
            message (str, optional): Custom email body message.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "email")
        data: Dict[str, Any] = {
            "emails": emails if isinstance(emails, list) else [emails],
            "sendCopyToUser": send_copy_to_user
        }
        if subject or message:
            data["emailTemplate"] = {"subject": subject or "", "message": message or ""}
        return self.client.query('post', endpoint, data=data)

    def void(self, id: Union[int, str]) -> Any:
        """Void / Annul an invoice by ID.

        Args:
            id (int or str): Invoice ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)

    def open(self, id: Union[int, str]) -> Any:
        """Open / Reopen a void invoice by ID.

        Args:
            id (int or str): Invoice ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "open")
        return self.client.query('post', endpoint)


# For backward compatibility
invoices = Invoices


