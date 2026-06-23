from typing import Optional
from alegra.actions import Actions


class Currencies(Actions):
    """Operations related to currencies (monedas/divisas) endpoint."""
    endpoint: str = "currencies"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)


# For backward compatibility
currencies = Currencies

