from typing import Any, Iterator, List, Optional

from alegrapy._listing import build_list_params
from alegrapy.actions import Actions

_DEBIT_NOTE_ORDER_FIELDS: frozenset[str] = frozenset()
_DEBIT_NOTE_DATE_KEYS = ("date",)


class DebitNotes(Actions):
    """Operations related to supplier debit notes (``/debit-notes``).

    For customer debit notes, use ``client.income_debit_notes`` instead.
    """
    endpoint: str = "debit-notes"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List supplier debit notes.

        ``/debit-notes`` does not document ordering; passing ``order_field`` or
        ``order_direction`` raises ``ValueError``. Note that deleting a debit note
        fails on Alegra when a linked bill is reconciled.
        """
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=_DEBIT_NOTE_ORDER_FIELDS,
            enums={},
            date_keys=_DEBIT_NOTE_DATE_KEYS,
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over supplier debit notes, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=_DEBIT_NOTE_ORDER_FIELDS,
            enums={},
            date_keys=_DEBIT_NOTE_DATE_KEYS,
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)
