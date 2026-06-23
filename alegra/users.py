from typing import Any, Optional
from alegra.actions import Actions


class Users(Actions):
    """Operations related to users endpoint."""
    endpoint: str = "users"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def self_info(self) -> Any:
        """Retrieve the details of the currently authenticated user.

        Returns:
            Any: Parsed JSON response representing the authenticated user.
        """
        endpoint = f"{self.client.url}{self.endpoint}/self"
        return self.client.query('get', endpoint)


# For backward compatibility
users = Users

