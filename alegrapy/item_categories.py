from typing import Any, Iterator, List, Optional, Union

from alegrapy._listing import build_list_params
from alegrapy.actions import Actions, validate_id

_CATEGORY_ORDER_FIELDS = frozenset({"name"})
_CATEGORY_ENUMS = {"status": frozenset({"active", "inactive"})}


class ItemCategories(Actions):
    """Operations related to item categories (categorías de ítems) endpoint.

    Note:
        Uploaded attachments on item categories are limited to 2 MB by Alegra.
    """
    endpoint: str = "item-categories"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List item categories (only ``order_field='name'`` is supported)."""
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=_CATEGORY_ORDER_FIELDS,
            enums=_CATEGORY_ENUMS,
            date_keys=(),
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over item categories, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=_CATEGORY_ORDER_FIELDS,
            enums=_CATEGORY_ENUMS,
            date_keys=(),
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)

    def delete_attachment(self, attachment_id: Union[int, str]) -> Any:
        """Delete an item category attachment (``DELETE /item-categories/attachment/{id}``)."""
        valid_id = validate_id(attachment_id)
        endpoint = f"{self.client.url}{self.endpoint}/attachment/{valid_id}"
        return self.client.query('delete', endpoint)
