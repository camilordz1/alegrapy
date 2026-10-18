from typing import Any, Dict, List, Optional, Union
from alegra.actions import Actions, validate_id


class PurchaseOrders(Actions):
    """Operations related to purchase orders (órdenes de compra) endpoint."""
    endpoint: str = "purchase-orders"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def send_email(self, id: Union[int, str], emails: Union[List[str], str], send_copy_to_user: bool = False,
                   subject: Optional[str] = None, message: Optional[str] = None) -> Any:
        """Send purchase order by email.

        Args:
            id (int or str): Purchase order ID.
            emails (list or str): Email address or list of email addresses to send to.
            send_copy_to_user (bool): Send a copy of the email to the user (default False).
            subject (str, optional): Custom email subject.
            message (str, optional): Custom email body message.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = f"{self.client.url}{self.endpoint}/{validate_id(id)}/email"
        data: Dict[str, Any] = {
            "emails": emails if isinstance(emails, list) else [emails],
            "sendCopyToUser": send_copy_to_user
        }
        if subject or message:
            data["emailTemplate"] = {"subject": subject or "", "message": message or ""}
        return self.client.query('post', endpoint, data=data)

    def void(self, id: Union[int, str]) -> Any:
        """Void / Annul a purchase order by ID.

        Args:
            id (int or str): Purchase order ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = f"{self.client.url}{self.endpoint}/{validate_id(id)}/void"
        return self.client.query('post', endpoint)

    def add_comment(self, id: Union[int, str], comment_text: str) -> Any:
        """Add comments to a purchase order.

        Args:
            id (int or str): Purchase order ID.
            comment_text (str): The text comment to add.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = f"{self.client.url}{self.endpoint}/{validate_id(id)}/comments"
        data = {"comments": comment_text}
        return self.client.query('post', endpoint, data=data)


# For backward compatibility
purchase_orders = PurchaseOrders

