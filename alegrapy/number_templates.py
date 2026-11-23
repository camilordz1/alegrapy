from typing import Any, Dict, Iterator, List, Optional

from alegrapy._listing import build_list_params, validate_choice
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
        ``order_field`` or ``order_direction`` (passing them raises ``ValueError``)
        and requires ``documentType``, so only ``start``, ``limit``, ``documentType``,
        and caller ``kwargs`` are sent.

        Args:
            start (int): Initial position index for pagination (default 0).
            limit (int): Maximum number of results to return, 1..30 (default 30).
            document_type (str): Document type enum (e.g. ``"invoice"``,
                ``"creditNote"``).
            **kwargs: Additional query parameters.

        Returns:
            List[Any]: Matching number templates.

        Raises:
            ValueError: If ``document_type``, ``start``, ``limit``, or ordering
                parameters are invalid.
        """
        if "documentType" in kwargs:
            raise ValueError("pass the document type as document_type, not documentType")
        valid_type = validate_choice("document_type", document_type, DOCUMENT_TYPES)
        params = build_list_params(
            start,
            limit,
            {"documentType": valid_type, **kwargs},
            order_fields=frozenset(),
            enums={},
            date_keys=(),
        )
        return self.client.query('get', self._collection_url(), params=params)

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
        valid_type = validate_choice("document_type", document_type, DOCUMENT_TYPES)
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=frozenset(),
            enums={},
            date_keys=(),
        )
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
