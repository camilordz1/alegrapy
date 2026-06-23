from typing import Any, Dict, List, Optional, Union

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
        from alegra.session import default_client
        return default_client

    @client.setter
    def client(self, value: Optional['AlegraClient']) -> None:
        """Set the client instance for this resource."""
        self._client = value

    def read(self, id: Union[int, str], **kwargs: Any) -> Any:
        """Search and retrieve a single resource by its ID.

        Args:
            id (int or str): The unique identifier of the resource.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response representing the resource.
        """
        endpoint = f"{self.client.url}{self.endpoint}/{id}"
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
        endpoint = f"{self.client.url}{self.endpoint}"
        params = {
            'start': start,
            'limit': limit,
            'order_direction': 'ASC',
            'order_field': 'id'
        }
        params.update(kwargs)
        return self.client.query('get', endpoint, params=params)

    def create(self, params: Dict[str, Any], **kwargs: Any) -> Any:
        """Send information to create a new resource in Alegra.

        Args:
            params (dict): The fields and values to create the resource with.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response from the server.
        """
        endpoint = f"{self.client.url}{self.endpoint}"
        return self.client.query('post', endpoint, data=params, params=kwargs)

    def update(self, id: Union[int, str], params: Dict[str, Any], **kwargs: Any) -> Any:
        """Update an existing record in Alegra by its ID.

        Args:
            id (int or str): The unique identifier of the resource to update.
            params (dict): The fields and values to update.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response from the server.
        """
        endpoint = f"{self.client.url}{self.endpoint}/{id}"
        return self.client.query('put', endpoint, data=params, params=kwargs)

    def delete(self, id: Union[int, str], **kwargs: Any) -> Any:
        """Delete an existing resource by its ID.

        Args:
            id (int or str): The unique identifier of the resource to delete.
            **kwargs: Additional query parameters.

        Returns:
            Any: The parsed JSON response from the server.
        """
        endpoint = f"{self.client.url}{self.endpoint}/{id}"
        return self.client.query('delete', endpoint, params=kwargs)

    def _upload_file(self, endpoint: str, file_path: str, field_name: str = 'file') -> Any:
        """Upload a file using multipart/form-data.

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
        with open(file_path, 'rb') as f:
            files = {field_name: (os.path.basename(file_path), f.read())}
            return self.client.query('post', endpoint, files=files)

    def add_attachment(self, id: Union[int, str], file_path: str, field_name: str = 'file') -> Any:
        """Upload an attachment to this resource by its ID.

        Args:
            id (int or str): The unique identifier of the resource.
            file_path (str): Path to the local file to upload.
            field_name (str): Name of the form field expected by the server (default 'file').

        Returns:
            Any: The parsed JSON response from the server.
        """
        endpoint = f"{self.client.url}{self.endpoint}/{id}/attachment"
        return self._upload_file(endpoint, file_path, field_name)


# For backward compatibility
actions = Actions


