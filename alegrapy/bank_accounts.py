from typing import Any, Dict, Optional, Union
from alegrapy.actions import Actions


class BankAccounts(Actions):
    """Operations related to bank accounts endpoint."""
    endpoint: str = "bank-accounts"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def transfer(self, from_id: Union[int, str], to_id: Union[int, str], amount: float, date: str, description: Optional[str] = None) -> Any:
        """Transfer funds between bank accounts.

        Args:
            from_id (int or str): Source bank account ID.
            to_id (int or str): Destination bank account ID.
            amount (float): Amount to transfer.
            date (str): Date of transfer (YYYY-MM-DD).
            description (str, optional): Description of the transfer.

        Returns:
            Any: Parsed JSON response from the server.
        """
        endpoint = f"{self.client.url}{self.endpoint}/transfer"
        data = {
            "from": from_id,
            "to": to_id,
            "amount": amount,
            "date": date
        }
        if description:
            data["description"] = description
        return self.client.query('post', endpoint, data=data)


# For backward compatibility
bank_accounts = BankAccounts

