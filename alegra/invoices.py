from typing import Any, Dict, List, Optional, Union
from alegra.actions import Actions


class Invoices(Actions):
    """Operations related to invoices (facturas de venta) endpoint."""
    endpoint: str = "invoices"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def send_email(self, id: Union[int, str], emails: Union[List[str], str], send_copy_to_user: bool = False,
                   subject: Optional[str] = None, message: Optional[str] = None) -> Any:
        """Send invoice by email.

        Args:
            id (int or str): Invoice ID.
            emails (list or str): Email address or list of email addresses to send to.
            send_copy_to_user (bool): Send a copy of the email to the user (default False).
            subject (str, optional): Custom email subject.
            message (str, optional): Custom email body message.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "email")
        data: Dict[str, Any] = {
            "emails": emails if isinstance(emails, list) else [emails],
            "sendCopyToUser": send_copy_to_user
        }
        if subject or message:
            data["emailTemplate"] = {"subject": subject or "", "message": message or ""}
        return self.client.query('post', endpoint, data=data)

    def void(self, id: Union[int, str]) -> Any:
        """Void / Annul an invoice by ID.

        Args:
            id (int or str): Invoice ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)

    def open(self, id: Union[int, str]) -> Any:
        """Open / Reopen a void invoice by ID.

        Args:
            id (int or str): Invoice ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        endpoint = self._resource_url(id, "open")
        return self.client.query('post', endpoint)


# For backward compatibility
invoices = Invoices


