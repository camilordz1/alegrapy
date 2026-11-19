import copy
import logging
import math
import numbers
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlsplit

import requests

from alegra.actions import Actions, validate_id
from alegra.exceptions import (AlegraAPIError, AlegraFileNotAvailableError,
                               AlegraUnverifiedCreateError, _error_for_exception,
                               _error_for_status)
from alegra.retry import _may_have_been_processed

logger = logging.getLogger("alegra")

_DEDUP_KEY_PATTERN = re.compile(r'[A-Za-z0-9_.:-]+')
_MARKER_PREFIX = "alegrapy:dedup:"
_MAX_OBSERVATIONS = 500
_VERIFY_INITIAL_INTERVAL = 1.0
_VERIFY_MAX_INTERVAL = 8.0
_DEFAULT_MAX_BYTES = 25 * 1024 * 1024
_XML_BOM = b"\xef\xbb\xbf"


def _validate_max_bytes(max_bytes: Any) -> int:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return max_bytes


def _file_url_host(url: str) -> str:
    """Validate a file URL and return its host, never echoing the URL."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        raise AlegraAPIError(
            "Invalid file URL: https, a host and no embedded credentials are required"
        )
    return parts.hostname


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

    def get_pdf(self, id: Union[int, str], max_bytes: int = _DEFAULT_MAX_BYTES) -> bytes:
        """Download the PDF of an invoice and return its bytes.

        The file URL comes from the authenticated ``GET /invoices/{id}?fields=pdf`` call;
        the download itself is anonymous: no API credentials, client headers or cookies
        are sent to the file host. Signed URLs expire, so store the file, not the URL.

        Args:
            id (int or str): Invoice ID.
            max_bytes (int): Maximum accepted file size (default 25 MB).

        Returns:
            bytes: PDF content, starting with ``%PDF-``.

        Raises:
            AlegraFileNotAvailableError: If the invoice has no PDF (drafts never do).
            AlegraAPIError: If the URL, download or content is invalid.
            ValueError: If the ID or ``max_bytes`` is invalid.
        """
        return self._fetch_file(id, "pdf", _validate_max_bytes(max_bytes))

    def get_xml(self, id: Union[int, str], max_bytes: int = _DEFAULT_MAX_BYTES) -> bytes:
        """Download the stamped XML of an invoice and return its bytes.

        Uses the same anonymous download and safety rules as :meth:`get_pdf`.

        Args:
            id (int or str): Invoice ID.
            max_bytes (int): Maximum accepted file size (default 25 MB).

        Returns:
            bytes: XML content (a UTF-8 BOM is allowed before ``<?xml``).

        Raises:
            AlegraFileNotAvailableError: If the invoice has no stamped XML.
            AlegraAPIError: If the URL, download or content is invalid.
            ValueError: If the ID or ``max_bytes`` is invalid.
        """
        return self._fetch_file(id, "xml", _validate_max_bytes(max_bytes))

    def download_pdf(self, id: Union[int, str], path: Union[str, os.PathLike],
                     overwrite: bool = False,
                     max_bytes: int = _DEFAULT_MAX_BYTES) -> Path:
        """Download an invoice PDF to ``path`` atomically.

        Args:
            id (int or str): Invoice ID.
            path (str or PathLike): Destination file; its parent must exist.
            overwrite (bool): Replace an existing file (default False).
            max_bytes (int): Maximum accepted file size (default 25 MB).

        Returns:
            pathlib.Path: The final path.

        Raises:
            FileExistsError: If the file exists and ``overwrite`` is False (before any
                request is made).
            FileNotFoundError: If the parent directory does not exist.
            AlegraFileNotAvailableError: If the invoice has no PDF.
            AlegraAPIError: If the URL, download or content is invalid.
        """
        return self._download_to_path(id, "pdf", path, overwrite, max_bytes)

    def download_xml(self, id: Union[int, str], path: Union[str, os.PathLike],
                     overwrite: bool = False,
                     max_bytes: int = _DEFAULT_MAX_BYTES) -> Path:
        """Download an invoice XML to ``path`` atomically.

        Args:
            id (int or str): Invoice ID.
            path (str or PathLike): Destination file; its parent must exist.
            overwrite (bool): Replace an existing file (default False).
            max_bytes (int): Maximum accepted file size (default 25 MB).

        Returns:
            pathlib.Path: The final path.

        Raises:
            FileExistsError: If the file exists and ``overwrite`` is False (before any
                request is made).
            FileNotFoundError: If the parent directory does not exist.
            AlegraFileNotAvailableError: If the invoice has no stamped XML.
            AlegraAPIError: If the URL, download or content is invalid.
        """
        return self._download_to_path(id, "xml", path, overwrite, max_bytes)

    def _fetch_file(self, id: Union[int, str], field: str, max_bytes: int) -> bytes:
        """Fetch an invoice file, refreshing an expired URL once."""
        record = self.read(id, fields=field)
        url = self._file_field_url(record, field)
        prefix = b"%PDF-" if field == "pdf" else b"<?xml"

        try:
            return self._download_file(id, field, url, prefix, max_bytes)
        except AlegraAPIError as error:
            if error.status_code not in (403, 404):
                raise

        # The signature expired (or the object moved): ask Alegra for a fresh URL once.
        record = self.read(id, fields=field)
        url = self._file_field_url(record, field)
        return self._download_file(id, field, url, prefix, max_bytes)

    @staticmethod
    def _file_field_url(record: Any, field: str) -> str:
        value = record.get(field) if isinstance(record, dict) else None
        if not isinstance(value, str) or not value.strip():
            label = field.upper()
            raise AlegraFileNotAvailableError(
                f"No {label} available for this invoice; draft invoices have none"
            )
        return value

    def _download_file(self, id: Union[int, str], field: str, url: str,
                       expected_prefix: bytes, max_bytes: int) -> bytes:
        """Download one file anonymously, with size and content checks."""
        host = _file_url_host(url)
        api_path = urlsplit(self._resource_url(id)).path
        logger.info(f"GET - {api_path} - downloading {field.upper()} from {host}")

        try:
            response = requests.get(url, timeout=self.client.timeout, stream=True,
                                    allow_redirects=True)
        except requests.RequestException as error:
            raise _error_for_exception(error) from error

        try:
            final_url = getattr(response, "url", None)
            if isinstance(final_url, str):
                _file_url_host(final_url)

            if not 200 <= response.status_code < 300:
                raise _error_for_status(
                    f"File download failed (Status {response.status_code})",
                    response.status_code, None, getattr(response, "headers", None)
                )

            try:
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise AlegraAPIError("File exceeds the maximum allowed size")
                    chunks.append(chunk)
            except requests.RequestException as error:
                raise _error_for_exception(error) from error
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        content = b"".join(chunks)
        check = content[len(_XML_BOM):] if content.startswith(_XML_BOM) else content
        if not check.startswith(expected_prefix):
            raise AlegraAPIError("unexpected file content")
        return content

    def _download_to_path(self, id: Union[int, str], field: str,
                          path: Union[str, os.PathLike], overwrite: bool,
                          max_bytes: int) -> Path:
        target = Path(path)
        size_limit = _validate_max_bytes(max_bytes)
        self._check_target(target, overwrite)
        return self._atomic_write(target, self._fetch_file(id, field, size_limit))

    @staticmethod
    def _check_target(target: Path, overwrite: bool) -> None:
        if not target.parent.is_dir():
            raise FileNotFoundError(f"Parent directory does not exist: {target.parent}")
        if not overwrite and target.exists():
            raise FileExistsError(f"File already exists: {target}")

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> Path:
        """Write bytes to a temp file in the target directory, fsync and replace."""
        descriptor, temp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        except BaseException:
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise
        return target

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


