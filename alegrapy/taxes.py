from typing import Optional
from alegrapy.actions import Actions


class Taxes(Actions):
    """Operations related to taxes (impuestos) endpoint."""
    endpoint: str = "taxes"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)


# For backward compatibility
taxes = Taxes

