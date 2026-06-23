from typing import Optional
from alegra.actions import Actions


class Contacts(Actions):
    """Operations related to contacts (clientes/proveedores) endpoint."""
    endpoint: str = "contacts"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)


# For backward compatibility
contacts = Contacts

