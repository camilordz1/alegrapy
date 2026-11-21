from typing import Any, Dict, Optional, Union

from alegrapy._create_once import (client_id_from, contains_marker, marker_for,
                                 payload_with_marker, record_client_id,
                                 run_create_once, validate_dedup_key,
                                 validate_lookup_pages, validate_verify_window)
from alegrapy.actions import Actions, validate_id

_VALID_PAYMENT_TYPES = ("in", "out")


def _validate_payment_type(payment_type: Any) -> Optional[str]:
    if payment_type is None:
        return None
    if not isinstance(payment_type, str) or payment_type not in _VALID_PAYMENT_TYPES:
        raise ValueError("type must be 'in' or 'out'")
    return payment_type


class Payments(Actions):
    """Operations related to payments (pagos/ingresos) endpoint."""
    endpoint: str = "payments"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def reconcile(self, dedup_key: str, client_id: Union[int, str, None] = None,
                  *, type: Optional[str] = None,
                  lookup_pages: int = 2) -> Optional[Dict[str, Any]]:
        """Return the newest payment carrying ``dedup_key``, or ``None``.

        Scans the newest ``lookup_pages * 30`` payments (no ``status`` filter, so
        voided payments carrying the marker are also considered; callers should
        check ``status``). ``client_id`` and ``type`` are sent as server filters
        when given and re-checked client-side: when ``client_id`` is given, a
        record whose ``client`` is ``null`` or a different id does not match; a
        record with a different ``type`` does not match. A record that omits the
        ``client`` or ``type`` key still matches, so an existing payment is not missed.

        Args:
            dedup_key (str): Key used when the payment was created with ``create_once``.
            client_id (int or str, optional): Restrict matches to this client.
            type (str, optional): Restrict matches to ``"in"`` or ``"out"``.
            lookup_pages (int): Number of 30-record pages to scan (default 2).

        Returns:
            dict, optional: The matching payment, or ``None`` when not found.

        Raises:
            ValueError: If the key, client id, ``type`` or ``lookup_pages`` are invalid.
        """
        key = validate_dedup_key(dedup_key)
        pages = validate_lookup_pages(lookup_pages)
        valid_client_id = validate_id(client_id) if client_id is not None else None
        expected_client = str(valid_client_id) if valid_client_id is not None else None
        valid_type = _validate_payment_type(type)
        marker = marker_for(key)

        filters: Dict[str, Any] = {
            "order_field": "id",
            "order_direction": "DESC",
        }
        if valid_client_id is not None:
            filters["client_id"] = valid_client_id
        if valid_type is not None:
            filters["type"] = valid_type

        for payment in self.iter_all(max_items=pages * 30, **filters):
            if not contains_marker(payment, marker):
                continue
            # A record that omits ``client`` or ``type`` still matches: the server already
            # filtered by them, and skipping it would miss an existing payment and let
            # "retry" re-post. An explicit ``client: null`` is a client-less payment.
            client_known = isinstance(payment, dict) and "client" in payment
            if (expected_client is not None and client_known
                    and record_client_id(payment) != expected_client):
                continue
            record_type = payment.get("type") if isinstance(payment, dict) else None
            if valid_type is not None and record_type is not None and record_type != valid_type:
                continue
            return payment
        return None

    def create_once(self, params: Dict[str, Any], dedup_key: str, *,
                    on_unverified: str = "retry", verify_window: float = 30.0,
                    lookup_pages: int = 2, precheck: bool = True) -> Any:
        """Create a payment at most once per ``dedup_key``.

        A unique marker (``alegrapy:dedup:<key>``) is appended to ``observations``
        (which Alegra does not print on the document) and the payment is looked up
        by that marker so re-runs return the existing record instead of creating
        a duplicate.

        Flow:

        1. With ``precheck``, look for the marker first; return the payment if found.
        2. POST the payload. A non-ambiguous failure is raised unchanged.
        3. On an ambiguous failure (timeout, 5xx, dropped connection), look for the
           marker during ``verify_window`` seconds.
        4. If not found and ``on_unverified="retry"``, POST once more with the same
           payload, verify again, and otherwise raise
           :class:`AlegraUnverifiedCreateError`. Never more than 2 POSTs.
        5. With ``on_unverified="raise"``, raise the error right after the window.

        Limitations:
            ``"retry"`` reduces but does not eliminate duplicates: if Alegra shows the
            payment later than ``verify_window``, a second payment can be created. Use
            ``"raise"`` plus a quarantine queue for zero-duplicate flows. Two processes
            using the same key concurrently can both miss the precheck; serialize per
            key. ``client`` is optional on payments: without a client, the lookup
            window covers only the newest ``lookup_pages * 30`` payments of the
            company (filtered by ``type`` when given), so high-volume accounts
            should pass a client or raise ``lookup_pages``.
            ``query()`` itself may repeat a POST only when it provably was not sent
            (429 or ``request_not_sent``), which cannot create an extra payment.

        Args:
            params (dict): Payload for ``create``. ``params["client"]`` (``{"id": x}``
                or bare id) and ``params["type"]`` (``"in"`` or ``"out"``) are optional
                and narrow the lookup when provided.
            dedup_key (str): Stable key for this logical creation, 1..64 chars of
                letters, digits, ``_``, ``.``, ``:`` or ``-``.
            on_unverified (str): ``"retry"`` (default) or ``"raise"``.
            verify_window (float): Seconds to look for the payment after an ambiguous
                failure (default 30).
            lookup_pages (int): Pages of 30 payments scanned on each lookup (default 2).
            precheck (bool): Look for the marker before posting (default True).

        Returns:
            Any: The created (or previously existing) payment.

        Raises:
            ValueError: If the key, client id, ``type``, options or observations
                length are invalid; nothing is sent.
            AlegraAPIError: The original error for a non-ambiguous failure.
            AlegraUnverifiedCreateError: When an ambiguous create cannot be verified.
        """
        key = validate_dedup_key(dedup_key)
        if on_unverified not in ("retry", "raise"):
            raise ValueError("on_unverified must be 'retry' or 'raise'")
        validate_verify_window(verify_window)
        validate_lookup_pages(lookup_pages)
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        payload = payload_with_marker(params, key)
        client_id = client_id_from(params, required=False)
        payment_type = _validate_payment_type(params.get("type"))

        return run_create_once(
            post=self.create,
            lookup=lambda: self.reconcile(
                key, client_id, type=payment_type, lookup_pages=lookup_pages
            ),
            payload=payload,
            dedup_key=key,
            client_id=client_id,
            resource=self.endpoint,
            on_unverified=on_unverified,
            verify_window=verify_window,
            lookup_pages=lookup_pages,
            precheck=precheck,
            log_path=f"/{self.endpoint}",
        )

    def void(self, id: Union[int, str]) -> Any:
        """Void / Annul a payment by ID.

        Args:
            id (int or str): Payment ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)

    def open(self, id: Union[int, str]) -> Any:
        """Open / Reopen a void payment by ID.

        Args:
            id (int or str): Payment ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "open")
        return self.client.query('post', endpoint)


# For backward compatibility
payments = Payments


