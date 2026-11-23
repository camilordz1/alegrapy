import logging
import mimetypes
import numbers
import re
from typing import Any, Dict, Iterator, List, Optional, Union

from alegrapy._deprecation import warn_legacy
from alegrapy.exceptions import AlegraAPIError

_ID_PATTERN = re.compile(r'[A-Za-z0-9_-]+')

# Built at import: mimetypes otherwise loads its tables lazily on the first upload, reading
# system files with whatever ``open`` is in effect at that moment
_MIME_TYPES = mimetypes.MimeTypes()

logger = logging.getLogger("alegra")


def validate_id(id: Union[int, str]) -> Union[int, str]:
    """Validate a resource ID before it is placed in a URL path.

    Args:
        id (int or str): A non-negative integral number (bool excluded), or a string of
            letters, digits, '_' or '-'.

    Returns:
        int or str: The ID; integral numbers are normalized to a plain ``int``.

    Raises:
        ValueError: If the ID could alter the URL path or query (e.g. contains '/', '.', '?').
    """
    if isinstance(id, numbers.Integral) and not isinstance(id, bool) and id >= 0:
        return int(id)
    if isinstance(id, str) and _ID_PATTERN.fullmatch(id):
        return id
    raise ValueError(
        f"Invalid resource id {id!r}: expected a non-negative integer or a string "
        "containing only letters, digits, '_' and '-'."
    )


class Actions:
    """Base class for all resource endpoints in the Alegra API.

    Provides common CRUD operations and attachment uploads.
    """
    endpoint: str = ""

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance to use. If None, the global default_client is used.
        """
        self._client = client

    @property
    def client(self) -> 'AlegraClient':
        """Get the client instance for this resource."""
        if self._client is not None:
            return self._client
        from alegrapy.session import _default_client
        warn_legacy(
            "actions.default_client",
            f"{type(self).__name__}() without an explicit AlegraClient uses the deprecated "
            "global default client; pass client=AlegraClient(...) or use client.<resource>. "
            "The global session will be removed in 1.0.",
        )
        return _default_client

    @client.setter
    def client(self, value: Optional['AlegraClient']) -> None:
        """Set the client instance for this resource."""
        self._client = value

    def _collection_url(self) -> str:
        """Build the collection URL for this resource (base URL plus endpoint)."""
        return f"{self.client.url}{self.endpoint}"

    def _resource_url(self, id: Union[int, str], *suffix: str) -> str:
        """Build the URL of a single resource, validating its ID first.

        Args:
            id (int or str): Resource ID; validated before use.
            *suffix (str): Fixed path segments appended after the ID (e.g. 'void').

        Returns:
            str: The collection URL, ID and suffix segments joined with '/'.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        return "/".join((self._collection_url(), str(validate_id(id)), *suffix))

    def read(self, id: Union[int, str], **kwargs: Any) -> Any:
        """Search and retrieve a single resource by its ID.

        Args:
            id (int or str): The unique identifier of the resource.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response representing the resource.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id)
        return self.client.query('get', endpoint, params=kwargs)

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """Search multiple results and return a list of resources.

        Args:
            start (int): Initial position index for pagination (default 0).
            limit (int): Maximum number of results to return (max 30, default 30).
            **kwargs: Additional query parameters.

        Returns:
            List[Any]: A list of matching resources.
        """
        endpoint = self._collection_url()
        params = {
            'start': start,
            'limit': limit,
            'order_direction': 'ASC',
            'order_field': 'id'
        }
        params.update(kwargs)
        return self.client.query('get', endpoint, params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate over every matching resource, fetching one page at a time.

        Pages are requested lazily with ``start``/``limit`` through :meth:`list`, so the
        full result is never held in memory. The iteration stops on an empty or short
        page, when ``max_items`` records have been yielded, or if the API ignores
        ``start`` (detected when a full page repeats the previous page's first id).

        Offset pagination over a collection that changes while you walk it can skip or
        repeat records. Ascending ``id`` (the default ordering) is the most stable order
        for "process everything" jobs.

        Args:
            max_items (int, optional): Maximum records to yield. ``0`` yields nothing and
                sends no request.
            page_size (int): Records per request, between 1 and 30 (default 30).
            **filters: Query parameters forwarded to :meth:`list`. ``start``, ``limit``
                and ``metadata`` are rejected because the iterator owns pagination.

        Yields:
            Any: Each resource, in the order returned by the API.

        Raises:
            ValueError: If ``page_size``, ``max_items`` or the filters are invalid; no
                request is sent.
            AlegraAPIError: If a page does not have the expected list shape, or if any
                request fails (the original typed error propagates unchanged).
        """
        self._validate_iter_all(max_items, page_size, filters)
        return self._iterate_pages(
            None if max_items is None else int(max_items),
            int(page_size),
            filters,
        )

    @staticmethod
    def _validate_iter_all(max_items: Optional[int], page_size: int,
                           filters: Dict[str, Any]) -> None:
        """Validate ``iter_all`` arguments before any request is made."""
        if (isinstance(page_size, bool) or not isinstance(page_size, numbers.Integral)
                or not 1 <= page_size <= 30):
            raise ValueError("page_size must be an integer between 1 and 30")
        if max_items is not None and (isinstance(max_items, bool)
                                      or not isinstance(max_items, numbers.Integral)
                                      or max_items < 0):
            raise ValueError("max_items must be None or a non-negative integer")

        forbidden = {'start', 'limit', 'metadata'} & set(filters)
        if forbidden:
            raise ValueError(
                "iter_all owns pagination and the response shape; remove: "
                + ", ".join(sorted(forbidden))
            )

    def _iterate_pages(self, max_items: Optional[int], page_size: int,
                       filters: Dict[str, Any]) -> Iterator[Any]:
        """Yield records page by page; state lives only in this generator."""
        start = 0
        yielded = 0
        previous_first_id = None
        has_previous_page = False

        while True:
            remaining = page_size if max_items is None else min(page_size, max_items - yielded)
            if remaining <= 0:
                return

            page = self.list(start=start, limit=remaining, **filters)
            if not isinstance(page, list):
                raise AlegraAPIError(
                    f"Unexpected response shape while paginating {self.endpoint}"
                )
            if not page:
                return

            first_id = page[0].get('id') if isinstance(page[0], dict) else None
            if (has_previous_page and first_id is not None
                    and first_id == previous_first_id and len(page) == remaining):
                logger.warning(
                    f"GET - /{self.endpoint} - pagination did not advance at start {start}; stopping"
                )
                return

            previous_first_id = first_id
            has_previous_page = True

            for record in page:
                yield record
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return

            if len(page) < remaining:
                return
            start += len(page)

    def create(self, params: Dict[str, Any], **kwargs: Any) -> Any:
        """Send information to create a new resource in Alegra.

        Args:
            params (dict): The fields and values to create the resource with.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response from the server.
        """
        endpoint = self._collection_url()
        return self.client.query('post', endpoint, data=params, params=kwargs)

    def update(self, id: Union[int, str], params: Dict[str, Any], **kwargs: Any) -> Any:
        """Update an existing record in Alegra by its ID.

        Args:
            id (int or str): The unique identifier of the resource to update.
            params (dict): The fields and values to update.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id)
        return self.client.query('put', endpoint, data=params, params=kwargs)

    def delete(self, id: Union[int, str], **kwargs: Any) -> Any:
        """Delete an existing resource by its ID.

        Args:
            id (int or str): The unique identifier of the resource to delete.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id)
        return self.client.query('delete', endpoint, params=kwargs)

    def _upload_file(self, endpoint: str, file_path: str, field_name: str = 'file') -> Any:
        """Upload a file using multipart/form-data.

        The file part carries its MIME type, guessed from the file name
        (``application/octet-stream`` when unknown): Alegra rejects a part without one
        (HTTP 400 "El archivo adjunto es un campo obligatorio").

        Args:
            endpoint (str): Complete API endpoint URL.
            file_path (str): Path to the local file.
            field_name (str): Name of the form field expected by the server.

        Returns:
            Any: The parsed JSON response from the server.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        import os
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        content_type = _MIME_TYPES.guess_type(file_path)[0] or 'application/octet-stream'
        with open(file_path, 'rb') as f:
            files = {field_name: (os.path.basename(file_path), f.read(), content_type)}
            return self.client.query('post', endpoint, files=files)

    def add_attachment(self, id: Union[int, str], file_path: str, field_name: str = 'file') -> Any:
        """Upload an attachment to this resource by its ID.

        Args:
            id (int or str): The unique identifier of the resource.
            file_path (str): Path to the local file to upload.
            field_name (str): Name of the form field expected by the server (default 'file').

        Returns:
            Any: The parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "attachment")
        return self._upload_file(endpoint, file_path, field_name)


# For backward compatibility
actions = Actions


