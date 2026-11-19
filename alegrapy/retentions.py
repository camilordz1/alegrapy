from typing import Optional
from alegrapy.actions import Actions


class Retentions(Actions):
    """Operations related to retentions (retenciones) endpoint."""
    endpoint: str = "retentions"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)


# For backward compatibility
retentions = Retentions

