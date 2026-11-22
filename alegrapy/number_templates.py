import numbers
from typing import Any, Dict, Iterator, List, Optional

from alegrapy.actions import Actions

DOCUMENT_TYPES = frozenset({
    "invoice",
    "estimate",
    "transactionIn",
    "transactionOut",
    "creditNote",
    "debitNote",
    "incomeDebitNote",
})


def _validate_document_type(document_type: Any) -> str:
    if not isinstance(document_type, str) or document_type not in DOCUMENT_TYPES:
        allowed = ", ".join(sorted(DOCUMENT_TYPES))
        raise ValueError(f"document_type must be one of: {allowed}")
    return document_type


def _validate_pagination(start: Any, limit: Any) -> tuple[int, int]:
    if isinstance(start, bool) or not isinstance(start, numbers.Integral) or start < 0:
        raise ValueError("start must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, numbers.Integral) or not 1 <= limit <= 30:
        raise ValueError("limit must be an integer between 1 and 30")
    return int(start), int(limit)


class NumberTemplates(Actions):
    """Operations related to number templates (numeraciones) endpoint."""
    endpoint: str = "number-templates"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 30, *,
             document_type: str, **kwargs: Any) -> List[Any]:
        """List number templates for a required ``document_type``.

        Unlike :meth:`Actions.list`, ``GET /number-templates`` does not document
        ``order_field`` or ``order_direction`` and requires ``documentType``, so only
        ``start``, ``limit``, ``documentType``, and caller ``kwargs`` are sent.

        Args:
            start (int): Initial position index for pagination (default 0).
            limit (int): Maximum number of results to return, 1..30 (default 30).
            document_type (str): Document type enum (e.g. ``"invoice"``,
                ``"creditNote"``).
            **kwargs: Additional query parameters.

        Returns:
            List[Any]: Matching number templates.

        Raises:
            ValueError: If ``document_type``, ``start``, or ``limit`` are invalid.
        """
        valid_type = _validate_document_type(document_type)
        valid_start, valid_limit = _validate_pagination(start, limit)
        endpoint = self._collection_url()
        params: Dict[str, Any] = {
            "start": valid_start,
            "limit": valid_limit,
            "documentType": valid_type,
        }
        params.update(kwargs)
        return self.client.query('get', endpoint, params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30, *,
                 document_type: str, **filters: Any) -> Iterator[Any]:
        """Iterate lazily over all number templates for ``document_type``.

        Args:
            max_items (int, optional): Maximum records to yield.
            page_size (int): Records per request, between 1 and 30 (default 30).
            document_type (str): Document type enum (required).
            **filters: Extra query parameters forwarded to :meth:`list`.

        Yields:
            Any: Each number template record.

        Raises:
            ValueError: If ``document_type``, ``page_size``, ``max_items``, or filters
                are invalid; no request is sent.
        """
        valid_type = _validate_document_type(document_type)
        return super().iter_all(
            max_items=max_items,
            page_size=page_size,
            document_type=valid_type,
            **filters,
        )

    def default(self, document_type: str = "invoice") -> Optional[Dict[str, Any]]:
        """Return the active default number template for ``document_type``, or ``None``.

        Note:
            Reflects Alegra's preferred numbering (``isDefault`` true and ``status``
            ``"active"``), not DIAN resolution validity (such as ``endDate`` or range).

        Args:
            document_type (str): Document type enum (default ``"invoice"``).

        Returns:
            dict, optional: The matching number template, or ``None`` if none exists.
        """
        for template in self.iter_all(document_type=document_type):
            if (isinstance(template, dict)
                    and template.get("isDefault") is True
                    and template.get("status") == "active"):
                return template
        return None
