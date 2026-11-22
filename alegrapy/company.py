from typing import Any, Dict, Iterable, Optional, Union

COMPANY_FIELDS = frozenset({
    "origin",
    "interfaceSettings",
    "certificate",
    "invoiceText",
    "stampReceptionEmail",
    "sector",
    "uuid",
    "country",
    "mandateSignatureUrl",
    "swornDeclarationUrl",
    "manifestSignature",
    "simple",
    "status",
    "lastActivityDate",
    "sectorKey",
})


def _validate_fields(fields: Optional[Union[str, Iterable[str]]]) -> Optional[str]:
    if fields is None:
        return None
    if isinstance(fields, str):
        items = [fields]
    elif isinstance(fields, Iterable) and not isinstance(fields, (bytes, bytearray)):
        items = list(fields)
        if not items:
            raise ValueError("fields iterable must not be empty")
    else:
        raise ValueError("fields must be None, a string, or an iterable of strings")

    for item in items:
        if not isinstance(item, str) or item not in COMPANY_FIELDS:
            allowed = ", ".join(sorted(COMPANY_FIELDS))
            raise ValueError(f"Invalid company field {item!r}; allowed: {allowed}")
    return ",".join(items)


class Company:
    """Operations related to the company singleton endpoint (``/company``)."""
    endpoint: str = "company"

    def __init__(self, client: 'AlegraClient') -> None:
        """Initialize the singleton resource with an explicit ``AlegraClient``."""
        self._client = client

    def get(self, fields: Optional[Union[str, Iterable[str]]] = None) -> Any:
        """Retrieve company information.

        Note:
            When multiple ``fields`` are passed, they are joined with ``","``; Alegra's
            documentation lists the enum values but does not state how multiple values
            are combined.

        Args:
            fields (str or Iterable[str], optional): Optional field(s) to request.

        Returns:
            Any: Parsed JSON response for the company.

        Raises:
            ValueError: If ``fields`` contains an unsupported value.
        """
        valid_fields = _validate_fields(fields)
        endpoint = f"{self._client.url}{self.endpoint}"
        params = {"fields": valid_fields} if valid_fields is not None else None
        return self._client.query('get', endpoint, params=params)

    def update(self, params: Dict[str, Any]) -> Any:
        """Update company information (``PUT /company``).

        Args:
            params (dict): Fields to update.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If ``params`` is not a dict.
        """
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        endpoint = f"{self._client.url}{self.endpoint}"
        return self._client.query('put', endpoint, data=params)
