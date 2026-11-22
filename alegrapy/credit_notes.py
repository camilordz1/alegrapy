import enum
from typing import Any, Dict, Optional, Union

from alegrapy._create_once import (contains_marker, marker_for, validate_dedup_key,
                                 validate_lookup_date, validate_lookup_pages)
from alegrapy.actions import Actions, validate_id


class CreditNoteType(str, enum.Enum):
    """Credit-note types accepted by the Colombian catalog.

    ``PARTIALL_DEVOLUTION`` keeps the API's spelling; do not "fix" it.
    """
    PARTIALL_DEVOLUTION = "PARTIALL_DEVOLUTION"
    VOID_ELECTRONIC_INVOICE = "VOID_ELECTRONIC_INVOICE"
    REDUCTION_DISCOUNT_PARTIAL_TOTAL = "REDUCTION_DISCOUNT_PARTIAL_TOTAL"
    PRICE_ADJUSTMENT = "PRICE_ADJUSTMENT"
    OTHER = "OTHER"


class CreditNoteOperationType(str, enum.Enum):
    """Colombian credit-note operation types."""
    REFERENCE_TO_ELECTRONIC_INVOICE = "REFERENCE_TO_ELECTRONIC_INVOICE"
    NO_REFERENCE_TO_ELECTRONIC_INVOICE = "NO_REFERENCE_TO_ELECTRONIC_INVOICE"


def _record_client_id(record: Any) -> Optional[str]:
    """Return the record's client id as a comparable string, when present."""
    if not isinstance(record, dict):
        return None
    client = record.get("client")
    raw = client.get("id") if isinstance(client, dict) else client
    if raw is None:
        return None
    try:
        return str(validate_id(raw))
    except ValueError:
        return None


class CreditNotes(Actions):
    """Operations related to credit notes (notas crédito) endpoint."""
    endpoint: str = "credit-notes"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def reconcile(self, dedup_key: str, client_id: Union[int, str, None] = None,
                  lookup_pages: int = 2, *, date: Any = None) -> Optional[Dict[str, Any]]:
        """Return the newest credit note carrying ``dedup_key``, or ``None``.

        ``GET /credit-notes`` (reviewed 2026-11-22) documents ``client_id`` and exact
        ``date`` (``YYYY-MM-DD``) filters. When ``client_id`` is given, it is sent as a
        server filter and also re-checked client-side. When ``date`` is given, the
        lookup first scans up to ``lookup_pages * 30`` notes for that day, and falls
        back to an unfiltered-by-date scan of ``lookup_pages * 30`` notes if not found.

        Args:
            dedup_key (str): Key used in the note's ``observations`` marker.
            client_id (int or str, optional): Restrict matches to this client.
            lookup_pages (int): Number of 30-record pages to scan per pass (default 2).
            date (datetime.date or str, optional): Credit-note date (``YYYY-MM-DD``) to
                narrow the first lookup pass via the server ``date`` filter.

        Returns:
            dict, optional: The matching credit note, or ``None``.

        Raises:
            ValueError: If the key, client id, ``lookup_pages`` or ``date`` are invalid.
        """
        key = validate_dedup_key(dedup_key)
        pages = validate_lookup_pages(lookup_pages)
        lookup_date = validate_lookup_date(date)
        marker = marker_for(key)
        valid_client_id = validate_id(client_id) if client_id is not None else None
        expected_client = str(valid_client_id) if valid_client_id is not None else None

        base_filters: Dict[str, Any] = {"order_field": "id", "order_direction": "DESC"}
        if valid_client_id is not None:
            base_filters["client_id"] = valid_client_id

        def _scan(extra_filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            for note in self.iter_all(max_items=pages * 30, **extra_filters):
                if not contains_marker(note, marker):
                    continue
                record_client = _record_client_id(note)
                if (expected_client is not None and record_client is not None
                        and record_client != expected_client):
                    continue
                return note
            return None

        if lookup_date is not None:
            found = _scan({**base_filters, "date": lookup_date})
            if found is not None:
                return found

        return _scan(base_filters)


# For backward compatibility
credit_notes = CreditNotes
