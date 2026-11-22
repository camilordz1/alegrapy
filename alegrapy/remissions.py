from typing import Any, Iterator, List, Optional, Union

from alegrapy._listing import build_list_params
from alegrapy.actions import Actions, validate_id

_REMISSION_ORDER_FIELDS = frozenset({"id", "name", "date", "dueDate"})
_REMISSION_ENUMS = {"status": frozenset({"open", "void", "closed"})}
_REMISSION_DATE_KEYS = ("date", "dueDate")


class Remissions(Actions):
    """Operations related to remissions (remisiones) endpoint."""
    endpoint: str = "remissions"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List remissions with validated pagination, ordering, status, and dates."""
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=_REMISSION_ORDER_FIELDS,
            enums=_REMISSION_ENUMS,
            date_keys=_REMISSION_DATE_KEYS,
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over remissions, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=_REMISSION_ORDER_FIELDS,
            enums=_REMISSION_ENUMS,
            date_keys=_REMISSION_DATE_KEYS,
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)

    def open(self, id: Union[int, str]) -> Any:
        """Open / Reopen a remission by ID (``POST /remissions/{id}/open``)."""
        return self.client.query('post', self._resource_url(id, "open"))

    def void(self, id: Union[int, str]) -> Any:
        """Void / Annul a remission by ID (``POST /remissions/{id}/void``)."""
        return self.client.query('post', self._resource_url(id, "void"))

    def delete_attachment(self, attachment_id: Union[int, str]) -> Any:
        """Delete a remission attachment (``DELETE /remissions/attachment/{id}``)."""
        valid_id = validate_id(attachment_id)
        endpoint = f"{self.client.url}{self.endpoint}/attachment/{valid_id}"
        return self.client.query('delete', endpoint)
