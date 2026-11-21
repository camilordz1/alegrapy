from typing import Any, Dict, List, Optional, Union
from alegrapy._deprecation import warn_legacy
from alegrapy.actions import Actions


class Estimates(Actions):
    """Operations related to estimates (cotizaciones) endpoint."""
    endpoint: str = "estimates"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource.

        Args:
            client (AlegraClient, optional): The AlegraClient instance.
        """
        super().__init__(client)

    def send_email(self, id: Union[int, str], emails: Union[List[str], str], send_copy_to_user: bool = False,
                   subject: Optional[str] = None, message: Optional[str] = None) -> Any:
        """Send estimate by email.

        Args:
            id (int or str): Estimate ID.
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
        """Void / Annul an estimate by ID.

        .. deprecated:: 0.3.0
            ``POST /estimates/{id}/void`` is not documented by Alegra; this method
            will be removed in 1.0.

        Args:
            id (int or str): Estimate ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        warn_legacy(
            "estimates.void",
            "Estimates.void() calls POST /estimates/{id}/void, which is not documented "
            "by Alegra and will be removed in 1.0.",
        )
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)

    def open(self, id: Union[int, str]) -> Any:
        """Open / Reopen an estimate by ID.

        .. deprecated:: 0.3.0
            ``POST /estimates/{id}/open`` is not documented by Alegra; this method
            will be removed in 1.0.

        Args:
            id (int or str): Estimate ID.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
        """
        warn_legacy(
            "estimates.open",
            "Estimates.open() calls POST /estimates/{id}/open, which is not documented "
            "by Alegra and will be removed in 1.0.",
        )
        endpoint = self._resource_url(id, "open")
        return self.client.query('post', endpoint)


# For backward compatibility
estimates = Estimates

