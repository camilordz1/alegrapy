from typing import Any, Iterator, List, Optional, Union

from alegrapy._listing import build_list_params
from alegrapy.actions import Actions

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


class IncomeDebitNotes(Actions):
    """Operations related to customer debit notes (notas débito de venta) endpoint."""
    endpoint: str = "income-debit-notes"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List customer debit notes.

        ``start`` and ``limit`` follow the Alegra-wide pagination convention (not
        explicitly documented for ``/income-debit-notes``). Ordering is not documented,
        so passing ``order_field`` or ``order_direction`` raises ``ValueError``.

        Args:
            start (int): Initial position index for pagination (default 0).
            limit (int): Maximum number of results to return, 1..30 (default 30).
            **kwargs: Optional filters (``status``, ``emission_status``, ``date``,
                ``dueDate``, ``client_name``, ``client_identification``, ``prefix``,
                ``number``).

        Returns:
            List[Any]: Matching customer debit notes.

        Raises:
            ValueError: If pagination, ordering, or filter values are invalid; no
                request is sent.
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

    def void(self, id: Union[int, str]) -> Any:
        """Void a customer debit note by ID (``POST /income-debit-notes/{id}/void``).

        Args:
            id (int or str): Debit note ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)
