from typing import Optional
from alegra.actions import Actions


class Items(Actions):
    """Operations related to items (productos/servicios) endpoint."""
    endpoint: str = "items"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)


# For backward compatibility
items = Items

