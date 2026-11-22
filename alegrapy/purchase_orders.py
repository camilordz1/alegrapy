import json
from typing import Any, Dict, List, Optional, Union
from alegrapy.actions import Actions
from alegrapy.exceptions import AlegraAPIError, AlegraNotFoundError

_DOCUMENT_NOT_FOUND_CODE = 37009


def _error_code(body: Dict[str, Any]) -> Optional[int]:
    """Return the Alegra error code of ``body`` when it is an int or a digit string."""
    code = body.get("code")
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        return code
    if isinstance(code, str) and code.isascii() and code.isdigit():
        return int(code)
    return None


def _raise_for_error_body(result: Any) -> None:
    """Raise when a successful (2xx) response carries an Alegra error body.

    A body counts as an error when it is a dict without ``id`` that has a ``message``
    and a numeric ``code`` outside 200..299. Anything else is left alone.
    ``status_code`` is ``None`` because ``AlegraClient.query()`` does not expose the
    HTTP status of successful responses.
    """
    if not isinstance(result, dict) or "id" in result or "message" not in result:
        return
    code = _error_code(result)
    if code is None or 200 <= code <= 299:
        return
    message = str(result["message"])
    body = json.dumps(result, ensure_ascii=False)
    if code == _DOCUMENT_NOT_FOUND_CODE:
        raise AlegraNotFoundError(message, status_code=None, response_body=body)
    raise AlegraAPIError(message, status_code=None, response_body=body)


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

        .. note::
            This endpoint is not documented by Alegra; its existence was verified on
            2026-11-21. It may change without notice.

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
        endpoint = self._resource_url(id, "email")
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
        endpoint = self._resource_url(id, "void")
        return self.client.query('post', endpoint)

    def add_comment(self, id: Union[int, str], comment_text: str) -> Any:
        """Add comments to a purchase order.

        .. note::
            This endpoint is not documented by Alegra; its existence was verified on
            2026-11-21. It may change without notice.
            Alegra was observed answering a missing purchase order with HTTP 200 and
            an error body (``{"code": 37009, ...}``); that case is raised as an error
            (see ``Raises``). Its ``status_code`` is ``None`` because the 2xx status is
            not exposed by the client.

        Args:
            id (int or str): Purchase order ID.
            comment_text (str): The text comment to add.

        Returns:
            Any: Parsed JSON response from the server.

        Raises:
            ValueError: If the ID is not a valid resource identifier.
            AlegraNotFoundError: If Alegra answers 2xx with an error body whose code is
                37009 (the purchase order does not exist).
            AlegraAPIError: If Alegra answers 2xx with any other error body.
        """
        endpoint = self._resource_url(id, "comments")
        data = {"comments": comment_text}
        result = self.client.query('post', endpoint, data=data)
        _raise_for_error_body(result)
        return result


# For backward compatibility
purchase_orders = PurchaseOrders

