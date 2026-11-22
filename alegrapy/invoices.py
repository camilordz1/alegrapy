import copy
import enum
import json
import logging
import math
import numbers
import os
import tempfile
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast
from urllib.parse import urljoin, urlsplit

import requests

from alegrapy._create_once import (client_id_from, contains_marker, marker_for,
                                 payload_with_marker, run_create_once,
                                 validate_dedup_key, validate_lookup_date, validate_lookup_pages,
                                 validate_verify_window)
from alegrapy.actions import Actions, validate_id
from alegrapy.credit_notes import CreditNoteOperationType, CreditNoteType
from alegrapy.dedup import make_dedup_key
from alegrapy.exceptions import (AlegraAPIError, AlegraAlreadyAnnulledError,
                               AlegraFileNotAvailableError, AlegraStampError,
                               AlegraStampTimeoutError, AlegraTimeoutError,
                               AlegraValidationError, _error_for_exception,
                               _error_for_status)
from alegrapy.stamping import (StampResult, StampStatus, parse_stamp_error_400,
                               parse_stamp_response, stamp_status_from_invoice,
                               validate_poll_timing, validate_stamp_ids)

logger = logging.getLogger("alegra")

_DEFAULT_MAX_BYTES = 25 * 1024 * 1024
_XML_BOM = b"\xef\xbb\xbf"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5


def _validate_max_bytes(max_bytes: Any) -> int:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return max_bytes


def _resolve_deadline(deadline: Any, client_timeout: float) -> float:
    if deadline is None:
        return max(60.0, 4 * float(client_timeout))
    if (isinstance(deadline, bool) or not isinstance(deadline, numbers.Real)
            or not math.isfinite(deadline) or deadline <= 0):
        raise ValueError("deadline must be a positive finite number")
    return float(deadline)


def _file_url_host(url: str) -> str:
    """Validate a file URL and return its host, never echoing the URL."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        raise AlegraAPIError(
            "Invalid file URL: https, a host and no embedded credentials are required"
        )
    return parts.hostname


def _enum_value(value: Any) -> Any:
    """Accept enum members or raw strings."""
    return value.value if isinstance(value, enum.Enum) else value


def _today_iso() -> str:
    """Today's date as ``YYYY-MM-DD`` (module-level ``date`` so tests can patch it)."""
    return date.today().isoformat()


def _credit_note_date(value: Any) -> Optional[str]:
    """Validate an explicit credit-note date; ``None`` means "today" (resolved later).

    Accepts a ``date``/``datetime`` or an ISO ``YYYY-MM-DD`` string and returns the ISO
    text. Anything else raises ``ValueError`` before any request is made.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:  # fromisoformat accepts other shapes on newer Pythons
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                pass
    raise ValueError("date must be a date or an ISO 'YYYY-MM-DD' string")


def _note_is_stamped(note: Dict[str, Any]) -> bool:
    """Whether a credit note was stamped and accepted (with or without observations)."""
    stamp_data = note.get("stamp")
    legal_status = stamp_data.get("legalStatus") if isinstance(stamp_data, dict) else None
    return isinstance(legal_status, str) and legal_status.startswith("STAMPED_AND_ACCEPTED")


def _invoice_is_annulled(invoice: Dict[str, Any]) -> bool:
    """An invoice fully cancelled by an annulment note: closed, zero balance and paid."""
    return (invoice.get("status") == "closed"
            and _is_zero(invoice.get("balance"))
            and _is_zero(invoice.get("totalPaid")))


def _is_zero(value: Any) -> bool:
    """Compare an amount numerically, tolerating decimal strings."""
    if value is None:
        return False
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def _stamp_failure_document(error: AlegraAPIError,
                             invoice_id: Union[int, str]) -> Optional[Dict[str, Any]]:
    """Extract the created credit note for this invoice from a stamp-failure 400."""
    if error.status_code != 400 or not error.response_body:
        return None
    try:
        body = json.loads(error.response_body)
    except (TypeError, ValueError):
        return None
    return _find_created_document(body, invoice_id)


def _find_created_document(value: Any,
                           invoice_id: Union[int, str]) -> Optional[Dict[str, Any]]:
    """Find a credit-note-looking object that references ``invoice_id``."""
    if isinstance(value, dict):
        if _is_created_note(value, invoice_id):
            return value
        for child in value.values():
            found = _find_created_document(child, invoice_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_created_document(child, invoice_id)
            if found is not None:
                return found
    return None


def _is_created_note(value: Dict[str, Any], invoice_id: Union[int, str]) -> bool:
    """A candidate must look like a credit note for this specific invoice."""
    if "id" not in value:
        return False
    note_type = value.get("type")
    has_note_marker = bool(value.get("creditNoteOperationType")) or note_type in {
        member.value for member in CreditNoteType
    }
    if not has_note_marker:
        return False
    invoices = value.get("invoices")
    if not isinstance(invoices, list):
        return False
    return any(isinstance(entry, dict) and str(entry.get("id")) == str(invoice_id)
               for entry in invoices)


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
                  lookup_pages: int = 2, *, date: Any = None) -> Optional[Dict[str, Any]]:
        """Return the newest invoice carrying ``dedup_key``, or ``None``.

        When ``date`` is given, first scans up to ``lookup_pages * 30`` invoices of the
        client with the server ``date`` filter, and falls back to the newest
        ``lookup_pages * 30`` unfiltered invoices of the client if not found (no
        ``status`` filter, so drafts and open invoices are both considered). The marker
        is matched against the invoice's ``observations`` as a whole stripped line.

        Limitations:
            Coverage is the whole ``date`` day when given (up to ``lookup_pages * 30``
            invoices on that day) plus the newest ``lookup_pages * 30`` invoices of
            the client.

        Args:
            dedup_key (str): Key used when the invoice was created with ``create_once``.
            client_id (int or str): Client whose invoices are scanned.
            lookup_pages (int): Number of 30-record pages to scan per pass (default 2).
            date (datetime.date or str, optional): Invoice date (``YYYY-MM-DD``) to
                narrow the first lookup pass via the server ``date`` filter.

        Returns:
            dict, optional: The matching invoice, or ``None`` when not found.

        Raises:
            ValueError: If the key, client id, ``lookup_pages`` or ``date`` are invalid.
        """
        key = validate_dedup_key(dedup_key)
        pages = validate_lookup_pages(lookup_pages)
        lookup_date = validate_lookup_date(date)
        marker = marker_for(key)
        valid_client_id = validate_id(client_id)

        if lookup_date is not None:
            for invoice in self.iter_all(max_items=pages * 30, client_id=valid_client_id,
                                         order_field="id", order_direction="DESC",
                                         date=lookup_date):
                if contains_marker(invoice, marker):
                    return invoice

        for invoice in self.iter_all(max_items=pages * 30, client_id=valid_client_id,
                                     order_field="id", order_direction="DESC"):
            if contains_marker(invoice, marker):
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
            key. When ``params["date"]`` is present, lookups cover up to
            ``lookup_pages * 30`` invoices on that day plus the newest
            ``lookup_pages * 30`` invoices of the client; otherwise only the newest
            window is scanned. Whether ``observations`` reaches the DIAN XML is
            unverified. ``query()`` itself may repeat a POST only when it provably was
            not sent (429 or ``request_not_sent``), which cannot create an extra invoice.

        Args:
            params (dict): Payload for ``create``; ``params["client"]`` (or
                ``params["client"]["id"]``) is required. If ``params["date"]`` is
                present, it must be a ``datetime.date`` or strict ``YYYY-MM-DD``
                string and is used to narrow lookups.
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
        key = validate_dedup_key(dedup_key)
        if on_unverified not in ("retry", "raise"):
            raise ValueError("on_unverified must be 'retry' or 'raise'")
        validate_verify_window(verify_window)
        validate_lookup_pages(lookup_pages)
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        lookup_date = validate_lookup_date(params.get("date"))
        payload = payload_with_marker(params, key)
        if lookup_date is not None:
            payload["date"] = lookup_date
        client_id = self._client_id_from(params)

        return run_create_once(
            post=self.create,
            lookup=lambda: self.reconcile(
                key, client_id, lookup_pages=lookup_pages, date=lookup_date
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

    @staticmethod
    def _payload_with_marker(params: Dict[str, Any], key: str) -> Dict[str, Any]:
        """Build a copy of ``params`` with the dedup marker on its own line."""
        return payload_with_marker(params, key)

    @staticmethod
    def _client_id_from(params: Dict[str, Any]) -> Union[int, str]:
        """Read and validate the client id required for the dedup lookup."""
        # required=True raises instead of returning None
        return cast(Union[int, str], client_id_from(params, required=True))

    def annul(self, id: Union[int, str], cause: str, *, dedup_key: Optional[str] = None,
              operation_type: Any = None, number_template_id: Any = None,
              stamp: bool = True, on_unverified: str = "retry",
              verify_window: float = 30.0, lookup_pages: int = 2,
              date: Any = None) -> Dict[str, Any]:
        """Annul a stamped electronic invoice with a credit note.

        Builds and posts a ``VOID_ELECTRONIC_INVOICE`` credit note referencing the
        invoice, with double-creation protection (same invoice -> same note). Only
        invoices with status ``open`` and an accepted stamp can be annulled; use
        :meth:`void` for non-electronic documents.

        The invoice is re-read before every POST. If it is now ``closed`` with zero
        ``balance`` and ``totalPaid`` (an annulment already happened), no note is
        created: the existing note is returned through the marker lookup, or
        :class:`AlegraAlreadyAnnulledError` is raised.

        Args:
            id (int or str): Invoice ID.
            cause (str): Reason for the annulment; must not be blank.
            dedup_key (str, optional): Override the default ``annul:<id>`` key.
            operation_type (CreditNoteOperationType or str, optional): Defaults to
                ``REFERENCE_TO_ELECTRONIC_INVOICE``. Use
                ``NO_REFERENCE_TO_ELECTRONIC_INVOICE`` when the customer already
                accepted the invoice.
            number_template_id (int or str, optional): Number template for the note.
            stamp (bool): Request electronic stamping (default True).
            on_unverified (str): ``"retry"`` (default) or ``"raise"``.
            verify_window (float): Seconds to look for the note after an ambiguous
                failure (default 30).
            lookup_pages (int): Pages of 30 credit notes scanned per lookup (default 2).
            date (date or str, optional): Credit-note date (``date`` or ISO
                ``YYYY-MM-DD``). Defaults to the host's local date; pass it explicitly
                when the host clock or timezone may differ from the business date.

        Returns:
            dict: The created (or previously existing) credit note.

        Raises:
            ValueError: If the cause is blank, the invoice is not open or not stamped,
                the invoice has no client id, or the options are invalid.
            AlegraAlreadyAnnulledError: The invoice is already annulled and its note
                was not found in the scanned pages.
            AlegraStampError: The note was created but stamping failed (400 with the
                created document, available as ``.document``).
            AlegraAPIError: Any other API failure.
            AlegraUnverifiedCreateError: When the create cannot be verified.
        """
        if not isinstance(cause, str) or not cause.strip():
            raise ValueError("cause must not be blank")
        note_date = _credit_note_date(date)

        invoice = self.read(id)
        if not isinstance(invoice, dict):
            raise ValueError("Unexpected invoice response")

        client = invoice.get("client")
        raw_client_id = client.get("id") if isinstance(client, dict) else client
        if raw_client_id is None:
            raise ValueError("Invoice has no client id")
        client_id = validate_id(raw_client_id)
        invoice_id = validate_id(invoice.get("id") or id)

        if dedup_key is None:
            key = make_dedup_key("annul", invoice_id)
        else:
            key = validate_dedup_key(dedup_key)

        credit_notes = self.client.credit_notes
        # Resolve "today" once so the payload and every lookup use the same date
        note_date = note_date or _today_iso()

        def lookup() -> Optional[Dict[str, Any]]:
            note = credit_notes.reconcile(
                key, client_id, lookup_pages=lookup_pages, date=note_date
            )
            if note is not None and stamp and not _note_is_stamped(note):
                # A previous attempt created the note but stamping failed: the
                # annulment is not complete, so report it instead of returning it
                raise AlegraStampError(
                    "An annulment credit note exists but it is not stamped",
                    document=note,
                )
            return note

        def guard() -> Optional[Dict[str, Any]]:
            """Re-read the invoice; never POST when it is already annulled."""
            current = self.read(id)
            if not isinstance(current, dict):
                raise ValueError("Unexpected invoice response")
            if _invoice_is_annulled(current):
                note = lookup()
                if note is not None:
                    return note
                raise AlegraAlreadyAnnulledError(
                    f"Invoice {invoice_id} is already annulled", invoice_id=invoice_id)
            if current.get("status") != "open":
                raise ValueError("Only open invoices can be annulled")
            return None

        if _invoice_is_annulled(invoice):
            note = lookup()
            if note is not None:
                return note
            raise AlegraAlreadyAnnulledError(
                f"Invoice {invoice_id} is already annulled", invoice_id=invoice_id)
        if invoice.get("status") != "open":
            raise ValueError("Only open invoices can be annulled")

        stamp_data = invoice.get("stamp")
        legal_status = stamp_data.get("legalStatus") if isinstance(stamp_data, dict) else None
        if not isinstance(legal_status, str) or not legal_status.startswith("STAMPED_AND_ACCEPTED"):
            raise ValueError(
                "Only stamped and accepted electronic invoices can be annulled; "
                "use void() for non-electronic documents"
            )

        payload = payload_with_marker(
            self._annulment_payload(invoice, invoice_id, client_id, cause,
                                    operation_type, number_template_id, stamp,
                                    note_date),
            key,
        )

        def post(data: Dict[str, Any]) -> Any:
            try:
                return credit_notes.create(data)
            except AlegraAPIError as error:
                document = _stamp_failure_document(error, invoice_id)
                if document is not None:
                    raise AlegraStampError(
                        "Credit note created but electronic stamping failed",
                        document=document,
                        status_code=error.status_code,
                        response_body=error.response_body,
                        retry_after=error.retry_after,
                    ) from error
                raise

        return run_create_once(
            post=post,
            lookup=lookup,
            payload=payload,
            dedup_key=key,
            client_id=client_id,
            resource="credit-notes",
            on_unverified=on_unverified,
            verify_window=verify_window,
            lookup_pages=lookup_pages,
            precheck=True,
            before_post=guard,
            log_path="/credit-notes",
        )

    def get_pdf(self, id: Union[int, str], max_bytes: int = _DEFAULT_MAX_BYTES,
                deadline: Optional[float] = None) -> bytes:
        """Download the PDF of an invoice and return its bytes.

        The file URL comes from the authenticated ``GET /invoices/{id}?fields=pdf`` call;
        the download itself is anonymous: no API credentials, client headers or cookies
        are sent to the file host. Signed URLs expire, so store the file, not the URL.

        Two limits apply: ``max_bytes`` caps the file size, and ``deadline`` caps the
        total elapsed time of the download (including redirects), because
        ``client.timeout`` only bounds connect and each individual read.

        Args:
            id (int or str): Invoice ID.
            max_bytes (int): Maximum accepted file size (default 25 MB).
            deadline (float, optional): Maximum seconds for the whole download;
                defaults to ``max(60, 4 * client.timeout)``.

        Returns:
            bytes: PDF content, starting with ``%PDF-``.

        Raises:
            AlegraFileNotAvailableError: If the invoice has no PDF (drafts never do).
            AlegraAPIError: If the URL, download or content is invalid.
            AlegraTimeoutError: If the total download deadline is exceeded.
            ValueError: If the ID, ``max_bytes`` or ``deadline`` is invalid.
        """
        return self._fetch_file(id, "pdf", _validate_max_bytes(max_bytes),
                                _resolve_deadline(deadline, self.client.timeout))

    def get_xml(self, id: Union[int, str], max_bytes: int = _DEFAULT_MAX_BYTES,
                deadline: Optional[float] = None) -> bytes:
        """Download the stamped XML of an invoice and return its bytes.

        Uses the same anonymous download and safety rules as :meth:`get_pdf`.

        Args:
            id (int or str): Invoice ID.
            max_bytes (int): Maximum accepted file size (default 25 MB).
            deadline (float, optional): Maximum seconds for the whole download;
                defaults to ``max(60, 4 * client.timeout)``.

        Returns:
            bytes: XML content (a UTF-8 BOM is allowed before ``<?xml``).

        Raises:
            AlegraFileNotAvailableError: If the invoice has no stamped XML.
            AlegraAPIError: If the URL, download or content is invalid.
            AlegraTimeoutError: If the total download deadline is exceeded.
            ValueError: If the ID, ``max_bytes`` or ``deadline`` is invalid.
        """
        return self._fetch_file(id, "xml", _validate_max_bytes(max_bytes),
                                _resolve_deadline(deadline, self.client.timeout))

    def download_pdf(self, id: Union[int, str], path: Union[str, os.PathLike],
                     overwrite: bool = False,
                     max_bytes: int = _DEFAULT_MAX_BYTES,
                     deadline: Optional[float] = None) -> Path:
        """Download an invoice PDF to ``path`` atomically.

        Args:
            id (int or str): Invoice ID.
            path (str or PathLike): Destination file; its parent must exist.
            overwrite (bool): Replace an existing file (default False).
            max_bytes (int): Maximum accepted file size (default 25 MB).
            deadline (float, optional): Maximum seconds for the whole download;
                defaults to ``max(60, 4 * client.timeout)``.

        Returns:
            pathlib.Path: The final path.

        Raises:
            FileExistsError: If the file exists and ``overwrite`` is False (before any
                request is made, and again atomically at the final step).
            FileNotFoundError: If the parent directory does not exist.
            AlegraFileNotAvailableError: If the invoice has no PDF.
            AlegraAPIError: If the URL, download or content is invalid.
            AlegraTimeoutError: If the total download deadline is exceeded.
        """
        return self._download_to_path(id, "pdf", path, overwrite, max_bytes, deadline)

    def download_xml(self, id: Union[int, str], path: Union[str, os.PathLike],
                     overwrite: bool = False,
                     max_bytes: int = _DEFAULT_MAX_BYTES,
                     deadline: Optional[float] = None) -> Path:
        """Download an invoice XML to ``path`` atomically.

        Args:
            id (int or str): Invoice ID.
            path (str or PathLike): Destination file; its parent must exist.
            overwrite (bool): Replace an existing file (default False).
            max_bytes (int): Maximum accepted file size (default 25 MB).
            deadline (float, optional): Maximum seconds for the whole download;
                defaults to ``max(60, 4 * client.timeout)``.

        Returns:
            pathlib.Path: The final path.

        Raises:
            FileExistsError: If the file exists and ``overwrite`` is False (before any
                request is made, and again atomically at the final step).
            FileNotFoundError: If the parent directory does not exist.
            AlegraFileNotAvailableError: If the invoice has no stamped XML.
            AlegraAPIError: If the URL, download or content is invalid.
            AlegraTimeoutError: If the total download deadline is exceeded.
        """
        return self._download_to_path(id, "xml", path, overwrite, max_bytes, deadline)

    def _fetch_file(self, id: Union[int, str], field: str, max_bytes: int,
                    deadline: float) -> bytes:
        """Fetch an invoice file, refreshing an expired URL once."""
        record = self.read(id, fields=field)
        url = self._file_field_url(record, field)
        prefix = b"%PDF-" if field == "pdf" else b"<?xml"

        try:
            return self._download_file(id, field, url, prefix, max_bytes, deadline)
        except AlegraAPIError as error:
            if error.status_code not in (403, 404):
                raise

        # The signature expired (or the object moved): ask Alegra for a fresh URL once.
        record = self.read(id, fields=field)
        url = self._file_field_url(record, field)
        return self._download_file(id, field, url, prefix, max_bytes, deadline)

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
                       expected_prefix: bytes, max_bytes: int, deadline: float) -> bytes:
        """Download one file anonymously, following redirects safely."""
        end = time.monotonic() + deadline
        api_path = urlsplit(self._resource_url(id)).path
        current_url = url
        hops = 0

        while True:
            self._check_deadline(end)
            host = _file_url_host(current_url)
            logger.info(f"GET - {api_path} - downloading {field.upper()} from {host}")

            try:
                response = requests.get(current_url, timeout=self.client.timeout,
                                        stream=True, allow_redirects=False)
            except requests.RequestException as error:
                raise _error_for_exception(error) from error

            try:
                if response.status_code in _REDIRECT_STATUSES:
                    headers = getattr(response, "headers", None)
                    location = headers.get('Location') if headers is not None else None
                    if not isinstance(location, str) or not location:
                        raise AlegraAPIError("Redirect response without a Location header")
                    hops += 1
                    if hops > _MAX_REDIRECTS:
                        raise AlegraAPIError("too many redirects")
                    # Resolved and validated at the top of the loop, before it is requested
                    current_url = urljoin(current_url, location)
                    continue

                if not 200 <= response.status_code < 300:
                    raise _error_for_status(
                        f"File download failed (Status {response.status_code})",
                        response.status_code, None, getattr(response, "headers", None)
                    )

                try:
                    chunks = []
                    total = 0
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        self._check_deadline(end)
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

    @staticmethod
    def _check_deadline(end: float) -> None:
        if time.monotonic() >= end:
            raise AlegraTimeoutError("File download deadline exceeded")

    def _download_to_path(self, id: Union[int, str], field: str,
                          path: Union[str, os.PathLike], overwrite: bool,
                          max_bytes: int, deadline: Optional[float]) -> Path:
        target = Path(path)
        size_limit = _validate_max_bytes(max_bytes)
        time_limit = _resolve_deadline(deadline, self.client.timeout)
        self._check_target(target, overwrite)
        data = self._fetch_file(id, field, size_limit, time_limit)
        return self._atomic_write(target, data, overwrite)

    @staticmethod
    def _check_target(target: Path, overwrite: bool) -> None:
        if not target.parent.is_dir():
            raise FileNotFoundError(f"Parent directory does not exist: {target.parent}")
        if not overwrite and target.exists():
            raise FileExistsError(f"File already exists: {target}")

    @staticmethod
    def _atomic_write(target: Path, data: bytes, overwrite: bool) -> Path:
        """Write bytes atomically; with ``overwrite=False`` never clobber a new file."""
        descriptor, temp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())

            if overwrite:
                os.replace(temp_path, target)
            else:
                try:
                    os.link(temp_path, target)
                except FileExistsError:
                    raise
                except (OSError, AttributeError):
                    # Filesystem without hardlinks: exclusive create at the final step
                    with open(target, "xb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
        return target

    @staticmethod
    def _annulment_payload(invoice: Dict[str, Any], invoice_id: Union[int, str],
                           client_id: Union[int, str], cause: str,
                           operation_type: Any, number_template_id: Any,
                           stamp: bool, note_date: Optional[str] = None) -> Dict[str, Any]:
        """Build the credit-note payload from the invoice record."""
        items = []
        for item in invoice.get("items") or []:
            entry = {
                "id": validate_id(item.get("id")),
                "price": item.get("price"),
                "quantity": item.get("quantity"),
            }
            if item.get("tax") is not None:
                tax = item["tax"]
                if isinstance(tax, (list, tuple)):
                    entry["tax"] = [
                        validate_id(element.get("id") if isinstance(element, dict) else element)
                        for element in tax
                    ]
                else:
                    entry["tax"] = [
                        validate_id(tax.get("id") if isinstance(tax, dict) else tax)
                    ]
            for field in ("reference", "description"):
                if field in item:
                    entry[field] = item[field]
            items.append(entry)

        payload: Dict[str, Any] = {
            "date": note_date or date.today().isoformat(),
            "client": {"id": client_id},
            "items": items,
            "type": CreditNoteType.VOID_ELECTRONIC_INVOICE.value,
            "creditNoteOperationType": _enum_value(
                operation_type if operation_type is not None
                else CreditNoteOperationType.REFERENCE_TO_ELECTRONIC_INVOICE
            ),
            "cause": cause.strip(),
            "invoices": [{"id": invoice_id, "amount": invoice.get("total")}],
        }
        for field in ("warehouse", "costCenter"):
            if invoice.get(field) is not None:
                payload[field] = copy.deepcopy(invoice[field])
        if number_template_id is not None:
            payload["numberTemplate"] = {"id": validate_id(number_template_id)}
        if stamp:
            payload["stamp"] = {"generateStamp": True}
        return payload

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

    def void(self, id: Union[int, str], cause: Optional[str] = None) -> Any:
        """Void a non-electronic invoice by ID.

        For Colombian electronic invoices use :meth:`annul`: they are cancelled with a
        credit note, not voided. ``cause`` is optional and sent only when provided.

        Args:
            id (int or str): Invoice ID.
            cause (str, optional): Reason for voiding.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "void")
        if cause is None:
            return self.client.query('post', endpoint)
        return self.client.query('post', endpoint, data={"cause": cause})

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

    def stamp(self, ids: List[Union[int, str]]) -> List[StampResult]:
        """Emit 1 to 10 electronic invoices to the tax authority via ``POST /invoices/stamp``.

        Never re-POSTs on ambiguous failures (timeouts, connection errors after send,
        or 5xx): callers must check :meth:`stamp_status` before stamping again.

        Args:
            ids (Sequence[int or str]): 1 to 10 unique invoice IDs.

        Returns:
            list[StampResult]: Per-invoice results, even when HTTP 200 mixes successes
                and failures or HTTP 400 carries a per-ID ``data`` list.

        Raises:
            ValueError: If ``ids`` is empty, exceeds 10 items, contains duplicates, or
                has an invalid ID.
            AlegraAPIError: On ambiguous failures or non-per-ID 4xx/5xx responses.
        """
        normalized_ids = validate_stamp_ids(ids)
        endpoint = f"{self._collection_url()}/stamp"
        logger.info("Stamping %d invoice(s) via %s", len(normalized_ids), endpoint)
        try:
            payload = self.client.query('post', endpoint, data={"ids": normalized_ids})
        except AlegraValidationError as exc:
            parsed = parse_stamp_error_400(exc.response_body, normalized_ids)
            if parsed is not None:
                return parsed
            raise
        return parse_stamp_response(payload, normalized_ids)

    def stamp_status(self, id: Union[int, str]) -> StampStatus:
        """Read an invoice and return its typed electronic-stamping status.

        Args:
            id (int or str): Invoice ID.

        Returns:
            StampStatus: Normalized state, emission/final flags, observations, and CUFE.

        Raises:
            ValueError: If the ID is invalid or the server response is not a dict.
            AlegraAPIError: On API or transport failures.
        """
        clean_id = validate_id(id)
        invoice = self.read(clean_id)
        if not isinstance(invoice, dict):
            raise ValueError("Unexpected invoice response")
        return stamp_status_from_invoice(invoice, fallback_id=clean_id)

    def wait_until_stamped(self, id: Union[int, str], timeout: float = 60.0,
                           interval: float = 2.0) -> StampStatus:
        """Poll :meth:`stamp_status` until a final state is reached.

        ``ACCEPTED``, ``ACCEPTED_WITH_OBSERVATIONS``, and ``REJECTED`` are final and
        returned directly (``REJECTED`` is not raised). ``DRAFT``, ``PENDING``, and
        ``UNKNOWN`` continue polling until ``timeout`` expires.

        Args:
            id (int or str): Invoice ID.
            timeout (float): Maximum seconds to wait (must be positive and finite).
            interval (float): Seconds between polls (must be positive and finite).

        Returns:
            StampStatus: The final stamping status.

        Raises:
            ValueError: If ``id``, ``timeout``, or ``interval`` is invalid.
            AlegraStampTimeoutError: If ``timeout`` expires before a final state,
                carrying ``.last_status``.
            AlegraAPIError: On API or transport failures during polling.
        """
        clean_id = validate_id(id)
        max_wait, step = validate_poll_timing(timeout, interval)
        deadline = time.monotonic() + max_wait

        while True:
            status = self.stamp_status(clean_id)
            if status.is_final:
                logger.info("Invoice %s reached final stamp state %s",
                            status.invoice_id, status.state.value)
                return status
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AlegraStampTimeoutError(
                    f"Invoice {clean_id} did not reach a final stamp state within {max_wait}s",
                    last_status=status,
                )
            time.sleep(min(step, remaining))


# For backward compatibility
invoices = Invoices


