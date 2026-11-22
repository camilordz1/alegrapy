from typing import Any, Dict, Iterator, List, Optional, Union

from alegrapy._create_once import validate_lookup_date
from alegrapy._listing import build_list_params
from alegrapy.actions import Actions, validate_id

_BILL_ORDER_FIELDS = frozenset({"date", "name", "dueDate"})
_BILL_ENUMS = {
    "status": frozenset({"open", "closed", "void"}),
    "type": frozenset({"bill", "supportDocument", "all"}),
}
_BILL_DATE_KEYS = ("date", "dueDate")


class Bills(Actions):
    """Operations related to supplier bills (facturas de proveedor) endpoint."""
    endpoint: str = "bills"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List supplier bills.

        ``order_field`` (``date``, ``name``, ``dueDate``) and ``order_direction``
        (``ASC``, ``DESC``) are sent only when passed by the caller.
        """
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=_BILL_ORDER_FIELDS,
            enums=_BILL_ENUMS,
            date_keys=_BILL_DATE_KEYS,
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over supplier bills, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=_BILL_ORDER_FIELDS,
            enums=_BILL_ENUMS,
            date_keys=_BILL_DATE_KEYS,
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)

    def close(self, id: Union[int, str], date: Any, category: Union[int, str, Dict[str, Any]],
              observations: Optional[str] = None) -> Any:
        """Close a supplier bill by writing off its pending balance (``POST /bills/{id}/close``).

        Note:
            Alegra requires ``date`` to be later than the bill's creation date.
        """
        endpoint = self._resource_url(id, "close")
        close_date = validate_lookup_date(date)
        if close_date is None:
            raise ValueError("date is required")

        raw_cat = category.get("id") if isinstance(category, dict) else category
        if raw_cat is None:
            raise ValueError("category id is required")
        cat_id = validate_id(raw_cat)

        body: Dict[str, Any] = {"date": close_date, "category": {"id": cat_id}}
        if observations is not None:
            if not isinstance(observations, str) or len(observations) > 500:
                raise ValueError("observations must be a string of at most 500 characters")
            body["observations"] = observations
        return self.client.query('post', endpoint, data=body)

    def add_comment(self, id: Union[int, str], comments: Union[str, List[str]]) -> Any:
        """Add comment(s) to a supplier bill (``POST /bills/{id}/comments``).

        Returns Alegra's response unchanged (typically ``{"code": 201, "message": <bill>}``
        inside an HTTP 200).
        """
        endpoint = self._resource_url(id, "comments")
        if isinstance(comments, str):
            if not comments.strip():
                raise ValueError("comments must not be empty")
            payload_comments: Union[str, List[str]] = comments
        elif isinstance(comments, list) and comments and all(
            isinstance(c, str) and c.strip() for c in comments
        ):
            payload_comments = comments
        else:
            raise ValueError("comments must be a non-empty string or non-empty list of strings")
        return self.client.query('post', endpoint, data={"comments": payload_comments})

    def delete_attachment(self, attachment_id: Union[int, str]) -> Any:
        """Delete a bill attachment by attachment ID (``DELETE /bills/attachment/{id}``)."""
        valid_id = validate_id(attachment_id)
        endpoint = f"{self.client.url}{self.endpoint}/attachment/{valid_id}"
        return self.client.query('delete', endpoint)
