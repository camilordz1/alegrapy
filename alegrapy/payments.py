from typing import Any, Optional, Union
from alegrapy.actions import Actions


class Payments(Actions):
    """Operations related to payments (pagos/ingresos) endpoint."""
    endpoint: str = "payments"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def void(self, id: Union[int, str]) -> Any:
        """Void / Annul a payment by ID.

        Args:
            id (int or str): Payment ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)

    def open(self, id: Union[int, str]) -> Any:
        """Open / Reopen a void payment by ID.

        Args:
            id (int or str): Payment ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "open")
        return self.client.query('post', endpoint)


# For backward compatibility
payments = Payments


