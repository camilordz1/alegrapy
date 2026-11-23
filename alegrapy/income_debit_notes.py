import numbers
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from alegrapy._create_once import (
    client_id_from,
    contains_marker,
    marker_for,
    payload_with_marker,
    record_client_id,
    run_create_once,
    validate_dedup_key,
    validate_lookup_date,
    validate_lookup_pages,
    validate_verify_window,
)
from alegrapy._listing import build_list_params
from alegrapy.actions import Actions, validate_id
from alegrapy.exceptions import AlegraAPIError, AlegraLookupIncompleteError

INCOME_DEBIT_NOTE_STATUSES = frozenset({"open", "closed", "draft", "void"})
INCOME_DEBIT_NOTE_EMISSION_STATUSES = frozenset({
    "PENDING",
    "STAMPED_AND_ACCEPTED",
    "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS",
    "STAMPED_AND_REJECTED",
    "STAMPED_AND_WAITING_RESPONSE",
})
_DEBIT_NOTE_ENUMS = {
    "status": INCOME_DEBIT_NOTE_STATUSES,
    "emission_status": INCOME_DEBIT_NOTE_EMISSION_STATUSES,
}
_DEBIT_NOTE_DATE_KEYS = ("date", "dueDate")


def _id_sort_key(record: Dict[str, Any]) -> Tuple[int, int, str]:
    raw_id = record.get("id")
    if isinstance(raw_id, numbers.Integral) and not isinstance(raw_id, bool):
        return (1, int(raw_id), str(raw_id))
    if isinstance(raw_id, str):
        text = raw_id.strip()
        if text.isascii() and text.isdigit():
            return (1, int(text), text)
        return (0, 0, text)
    return (0, 0, "")


class IncomeDebitNotes(Actions):
    """Operations related to customer debit notes (notas débito de venta) endpoint."""
    endpoint: str = "income-debit-notes"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List customer debit notes.

        ``start`` and ``limit`` follow the Alegra-wide pagination convention (not
        explicitly documented for ``/income-debit-notes``). Ordering is not documented,
        so passing ``order_field`` or ``order_direction`` raises ``ValueError``.
        """
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=frozenset(),
            enums=_DEBIT_NOTE_ENUMS,
            date_keys=_DEBIT_NOTE_DATE_KEYS,
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over customer debit notes, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=frozenset(),
            enums=_DEBIT_NOTE_ENUMS,
            date_keys=_DEBIT_NOTE_DATE_KEYS,
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)

    def reconcile(self, dedup_key: str, *, date: Any,
                  client_id: Union[int, str, None] = None,
                  max_pages: int = 10) -> Optional[Dict[str, Any]]:
        """Return the matching debit note carrying ``dedup_key`` on ``date``, or ``None``.

        ``GET /income-debit-notes`` returns records in ascending ``id`` order and does
        not support ``order_field`` or ``client_id``, so this scans pages of 30 records
        filtered by ``date`` until a short page ends the day. When ``client_id`` is
        given, records without a matching ``client.id`` are skipped. If several notes
        match, the one with the highest ``id`` is returned.

        Raises:
            ValueError: If ``dedup_key``, ``date``, ``client_id``, or ``max_pages`` are invalid.
            AlegraLookupIncompleteError: If ``max_pages`` full pages were scanned without
                reaching the end of the day.
        """
        key = validate_dedup_key(dedup_key)
        lookup_date = validate_lookup_date(date)
        if lookup_date is None:
            raise ValueError("date is required for debit-note reconciliation")
        pages = validate_lookup_pages(max_pages)
        expected_client = str(validate_id(client_id)) if client_id is not None else None
        marker = marker_for(key)

        best_match: Optional[Dict[str, Any]] = None
        start = 0
        for _ in range(pages):
            page = self.list(start=start, limit=30, date=lookup_date)
            if not isinstance(page, list):
                raise AlegraAPIError(f"Unexpected response shape while listing {self.endpoint}")
            for note in page:
                if not contains_marker(note, marker):
                    continue
                if expected_client is not None and record_client_id(note) != expected_client:
                    continue
                if best_match is None or _id_sort_key(note) > _id_sort_key(best_match):
                    best_match = note
            if len(page) < 30:
                return best_match
            start += len(page)

        raise AlegraLookupIncompleteError(
            f"Debit-note lookup for {key!r} on {lookup_date} stopped after {pages} full pages",
            resource=self.endpoint,
            dedup_key=key,
            date=lookup_date,
            pages_scanned=pages,
        )

    def create_once(self, params: Dict[str, Any], dedup_key: str, *,
                    on_unverified: str = "retry", verify_window: float = 30.0,
                    max_pages: int = 10, precheck: bool = True) -> Any:
        """Create a customer debit note at most once per ``dedup_key``.

        Flow:

        1. With ``precheck``, look for the marker on ``params["date"]``; return the note
           if found. If the day exceeds ``max_pages * 30`` notes,
           :class:`AlegraLookupIncompleteError` propagates and nothing is posted.
        2. POST the payload. A non-ambiguous failure is raised unchanged.
        3. On an ambiguous failure (timeout, 5xx, dropped connection), verify during
           ``verify_window`` seconds.
        4. If not found and ``on_unverified="retry"``, POST once more and verify again;
           otherwise raise :class:`AlegraUnverifiedCreateError`. Never more than 2 POSTs.

        Limitations:
            The lookup only covers ``params["date"]``: a note created on another day
            (for example a retry after midnight with a new date) is not found. Alegra
            may reuse ids after deleting drafts (identity is the marker, never the id).
            Stamping via ``stamp.generateStamp`` follows ``AlegraStampError`` handling
            (unverified live).
        """
        key = validate_dedup_key(dedup_key)
        if on_unverified not in ("retry", "raise"):
            raise ValueError("on_unverified must be 'retry' or 'raise'")
        validate_verify_window(verify_window)
        pages = validate_lookup_pages(max_pages)
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        lookup_date = validate_lookup_date(params.get("date"))
        if lookup_date is None:
            raise ValueError("params['date'] is required for duplicate-safe debit-note creation")
        client_id = client_id_from(params, required=True)
        payload = payload_with_marker(params, key)
        payload["date"] = lookup_date

        return run_create_once(
            post=self.create,
            lookup=lambda: self.reconcile(
                key, date=lookup_date, client_id=client_id, max_pages=pages
            ),
            payload=payload,
            dedup_key=key,
            client_id=client_id,
            resource=self.endpoint,
            on_unverified=on_unverified,
            verify_window=verify_window,
            lookup_pages=pages,
            precheck=precheck,
            log_path=f"/{self.endpoint}",
        )

    def void(self, id: Union[int, str]) -> Any:
        """Void a customer debit note by ID (``POST /income-debit-notes/{id}/void``)."""
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)
