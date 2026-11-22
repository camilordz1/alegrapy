import numbers
from typing import Any, Dict, Iterator, List, Optional, Union

from alegrapy._create_once import validate_lookup_date
from alegrapy.actions import Actions

INCOME_DEBIT_NOTE_STATUSES = frozenset({"open", "closed", "draft", "void"})
INCOME_DEBIT_NOTE_EMISSION_STATUSES = frozenset({
    "PENDING",
    "STAMPED_AND_ACCEPTED",
    "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS",
    "STAMPED_AND_REJECTED",
    "STAMPED_AND_WAITING_RESPONSE",
})


def _validate_pagination(start: Any, limit: Any) -> tuple[int, int]:
    if isinstance(start, bool) or not isinstance(start, numbers.Integral) or start < 0:
        raise ValueError("start must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, numbers.Integral) or not 1 <= limit <= 30:
        raise ValueError("limit must be an integer between 1 and 30")
    return int(start), int(limit)


def _validate_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    validated = dict(filters)
    if "status" in validated:
        status = validated["status"]
        if not isinstance(status, str) or status not in INCOME_DEBIT_NOTE_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(INCOME_DEBIT_NOTE_STATUSES))}")
    if "emission_status" in validated:
        emission = validated["emission_status"]
        if not isinstance(emission, str) or emission not in INCOME_DEBIT_NOTE_EMISSION_STATUSES:
            raise ValueError(
                "emission_status must be one of: "
                + ", ".join(sorted(INCOME_DEBIT_NOTE_EMISSION_STATUSES))
            )
    for date_key in ("date", "dueDate"):
        if date_key in validated:
            validated[date_key] = validate_lookup_date(validated[date_key])
    return validated


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
        explicitly documented for ``/income-debit-notes``); ``order_field`` and
        ``order_direction`` are not sent.

        Args:
            start (int): Initial position index for pagination (default 0).
            limit (int): Maximum number of results to return, 1..30 (default 30).
            **kwargs: Optional filters (``status``, ``emission_status``, ``date``,
                ``dueDate``, ``client_name``, ``client_identification``, ``prefix``,
                ``number``).

        Returns:
            List[Any]: Matching customer debit notes.

        Raises:
            ValueError: If pagination or filter values are invalid; no request is sent.
        """
        valid_start, valid_limit = _validate_pagination(start, limit)
        valid_filters = _validate_filters(kwargs)
        endpoint = self._collection_url()
        params: Dict[str, Any] = {"start": valid_start, "limit": valid_limit}
        params.update(valid_filters)
        return self.client.query('get', endpoint, params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over customer debit notes, validating filters eagerly."""
        valid_filters = _validate_filters(filters)
        return super().iter_all(max_items=max_items, page_size=page_size, **valid_filters)

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
