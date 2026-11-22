from typing import Any, Iterator, List, Optional

from alegrapy._listing import build_list_params
from alegrapy.actions import Actions

_WAREHOUSE_ORDER_FIELDS = frozenset({"name", "id"})
_WAREHOUSE_ENUMS = {
    "status": frozenset({"active", "inactive"}),
    "fields": frozenset({"editable", "deletable"}),
}


class Warehouses(Actions):
    """Operations related to warehouses (bodegas) endpoint."""
    endpoint: str = "warehouses"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List warehouses."""
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=_WAREHOUSE_ORDER_FIELDS,
            enums=_WAREHOUSE_ENUMS,
            date_keys=(),
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over warehouses, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=_WAREHOUSE_ORDER_FIELDS,
            enums=_WAREHOUSE_ENUMS,
            date_keys=(),
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)
