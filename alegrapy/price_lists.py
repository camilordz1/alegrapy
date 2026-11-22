import numbers
from typing import Any, Dict, Iterator, List, Optional, Union

from alegrapy._listing import build_list_params
from alegrapy.actions import Actions

_PRICE_LIST_ORDER_FIELDS = frozenset({"name", "id"})
_PRICE_LIST_ENUMS = {"fields": frozenset({"editable", "deletable"})}
_PRICE_LIST_TYPES = frozenset({"amount", "percentage"})


def _validate_price_list_payload(params: Any) -> None:
    if not isinstance(params, dict):
        raise ValueError("params must be a dict")
    if "name" in params:
        name = params["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 90:
            raise ValueError("name must be a non-empty string of at most 90 characters")
    if "type" in params:
        ptype = params["type"]
        if not isinstance(ptype, str) or ptype not in _PRICE_LIST_TYPES:
            raise ValueError("type must be 'amount' or 'percentage'")
        if ptype == "percentage":
            pct = params.get("percentage")
            if isinstance(pct, bool) or not isinstance(pct, numbers.Real):
                raise ValueError("percentage must be a number when type is 'percentage'")


class PriceLists(Actions):
    """Operations related to price lists (listas de precios) endpoint."""
    endpoint: str = "price-lists"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List price lists."""
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=_PRICE_LIST_ORDER_FIELDS,
            enums=_PRICE_LIST_ENUMS,
            date_keys=(),
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over price lists, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=_PRICE_LIST_ORDER_FIELDS,
            enums=_PRICE_LIST_ENUMS,
            date_keys=(),
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)

    def create(self, params: Dict[str, Any], **kwargs: Any) -> Any:
        """Create a price list after validating ``name``, ``type``, and ``percentage``."""
        _validate_price_list_payload(params)
        return super().create(params, **kwargs)

    def update(self, id: Union[int, str], params: Dict[str, Any], **kwargs: Any) -> Any:
        """Update a price list after validating ``name``, ``type``, and ``percentage``."""
        _validate_price_list_payload(params)
        return super().update(id, params, **kwargs)
