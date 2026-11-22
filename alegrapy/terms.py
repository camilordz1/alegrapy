from typing import Any, Iterator, List, Optional

from alegrapy._listing import build_list_params
from alegrapy.actions import Actions
from alegrapy.exceptions import AlegraAPIError

_TERM_ENUMS = {"fields": frozenset({"deletable"})}


class Terms(Actions):
    """Operations related to payment terms (términos de pago) endpoint.

    Note:
        ``GET /terms`` documents no pagination or ordering (default 30 terms);
        :meth:`iter_all` yields from a single :meth:`list` call.
    """
    endpoint: str = "terms"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, *, fields: Optional[str] = None, **kwargs: Any) -> List[Any]:
        """List payment terms without ``start``, ``limit``, or ordering parameters."""
        extra = dict(kwargs)
        if fields is not None:
            extra["fields"] = fields
        start = extra.pop("start", None)
        limit = extra.pop("limit", None)
        params = build_list_params(
            start,
            limit,
            extra,
            order_fields=frozenset(),
            enums=_TERM_ENUMS,
            date_keys=(),
            paginate=False,
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Yield payment terms from a single ``GET /terms`` call (max 30 documented)."""
        self._validate_iter_all(max_items, page_size, filters)
        build_list_params(
            None,
            None,
            filters,
            order_fields=frozenset(),
            enums=_TERM_ENUMS,
            date_keys=(),
            paginate=False,
        )

        def _single_page() -> Iterator[Any]:
            if max_items == 0:
                return
            records = self.list(**filters)
            if not isinstance(records, list):
                raise AlegraAPIError(f"Unexpected response shape while listing {self.endpoint}")
            for idx, record in enumerate(records):
                if max_items is not None and idx >= max_items:
                    return
                yield record

        return _single_page()
