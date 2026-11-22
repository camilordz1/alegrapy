import mimetypes
import os
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

    def upload_logo(self, file_path: Union[str, os.PathLike]) -> Any:
        """Upload the company logo (``POST /company/attachment``).

        Reads the entire image file into memory (no persistent file handle is kept) and
        sends it as ``multipart/form-data`` with ``type="logo"``. Multipart uploads are
        not retried by ``RetryPolicy``.

        Args:
            file_path (str or os.PathLike): Path to an existing image file (``image/*``).

        Returns:
            Any: Parsed JSON response from the server (e.g. ``{"file": ..., "type": "logo"}``).

        Raises:
            FileNotFoundError: If ``file_path`` does not exist.
            ValueError: If ``file_path`` is not a regular file or its MIME type is not ``image/*``.
        """
        path = os.fspath(file_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        if not os.path.isfile(path):
            raise ValueError(f"Path is not a regular file: {path}")
        content_type, _ = mimetypes.guess_type(path)
        if not content_type or not content_type.startswith("image/"):
            raise ValueError(f"Logo file must be an image (got {content_type!r})")

        with open(path, "rb") as f:
            payload_bytes = f.read()

        endpoint = f"{self._client.url}{self.endpoint}/attachment"
        files = {
            "file": (os.path.basename(path), payload_bytes, content_type),
            "type": (None, "logo"),
        }
        return self._client.query('post', endpoint, files=files)
