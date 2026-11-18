import base64
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit
import requests

from alegra.exceptions import (AlegraAPIError, _error_for_exception, _error_for_status)

# Create a dedicated logger for the library, allowing applications to configure it
logger = logging.getLogger("alegra")

# Hosts allowed to use plain HTTP, for local testing only
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validate_base_url(url: str) -> str:
    """Ensure the base API URL cannot expose credentials in transit.

    Args:
        url (str): Base API URL to validate.

    Returns:
        str: The same URL, unchanged, when valid.

    Raises:
        ValueError: If the scheme is not https (http is allowed only for loopback hosts),
            the URL has no host, or it embeds credentials (userinfo). Error messages never
            include the raw URL, since it may carry secrets.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise ValueError("Invalid base URL: missing host")
    if "@" in parts.netloc:
        raise ValueError("Invalid base URL: credentials in the URL are not allowed")
    if parts.scheme == "https":
        return url
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return url
    raise ValueError(
        f"Insecure base URL (scheme {parts.scheme!r}, host {host!r}): https is required "
        f"(http is allowed only for {', '.join(sorted(_LOOPBACK_HOSTS))})"
    )


class AlegraClient:
    """The main client interface for interacting with the Alegra API.

    Allows managing multiple API sessions with different credentials.
    """
    def __init__(self, user: Optional[str] = None, token: Optional[str] = None, url: Optional[str] = None,
                 timeout: Optional[float] = None) -> None:
        """Initialize the client.

        Args:
            user (str, optional): Alegra username (email).
            token (str, optional): Alegra API token.
            url (str, optional): Custom base API URL. Must use https (http only for loopback hosts).
                Defaults to 'https://api.alegra.com/api/v1/'.
            timeout (float, optional): Request timeout in seconds. Defaults to the global session timeout (30).

        Raises:
            ValueError: If url is given and is not a valid https (or loopback http) URL.
        """
        self._user = user
        self._token = token
        self._url = None
        self.url = url  # validated by the setter
        self._timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })

    @property
    def contacts(self) -> 'Contacts':
        """Access Contacts resource operations."""
        if not hasattr(self, '_contacts'):
            from alegra.contacts import Contacts
            self._contacts = Contacts(self)
        return self._contacts

    @property
    def invoices(self) -> 'Invoices':
        """Access Invoices resource operations."""
        if not hasattr(self, '_invoices'):
            from alegra.invoices import Invoices
            self._invoices = Invoices(self)
        return self._invoices

    @property
    def payments(self) -> 'Payments':
        """Access Payments resource operations."""
        if not hasattr(self, '_payments'):
            from alegra.payments import Payments
            self._payments = Payments(self)
        return self._payments

    @property
    def items(self) -> 'Items':
        """Access Items resource operations."""
        if not hasattr(self, '_items'):
            from alegra.items import Items
            self._items = Items(self)
        return self._items

    @property
    def estimates(self) -> 'Estimates':
        """Access Estimates resource operations."""
        if not hasattr(self, '_estimates'):
            from alegra.estimates import Estimates
            self._estimates = Estimates(self)
        return self._estimates

    @property
    def purchase_orders(self) -> 'PurchaseOrders':
        """Access Purchase Orders resource operations."""
        if not hasattr(self, '_purchase_orders'):
            from alegra.purchase_orders import PurchaseOrders
            self._purchase_orders = PurchaseOrders(self)
        return self._purchase_orders

    @property
    def bank_accounts(self) -> 'BankAccounts':
        """Access Bank Accounts resource operations."""
        if not hasattr(self, '_bank_accounts'):
            from alegra.bank_accounts import BankAccounts
            self._bank_accounts = BankAccounts(self)
        return self._bank_accounts

    @property
    def taxes(self) -> 'Taxes':
        """Access Taxes resource operations."""
        if not hasattr(self, '_taxes'):
            from alegra.taxes import Taxes
            self._taxes = Taxes(self)
        return self._taxes

    @property
    def currencies(self) -> 'Currencies':
        """Access Currencies resource operations."""
        if not hasattr(self, '_currencies'):
            from alegra.currencies import Currencies
            self._currencies = Currencies(self)
        return self._currencies

    @property
    def retentions(self) -> 'Retentions':
        """Access Retentions resource operations."""
        if not hasattr(self, '_retentions'):
            from alegra.retentions import Retentions
            self._retentions = Retentions(self)
        return self._retentions

    @property
    def users(self) -> 'Users':
        """Access Users resource operations."""
        if not hasattr(self, '_users'):
            from alegra.users import Users
            self._users = Users(self)
        return self._users

    def _credentials(self) -> Tuple[Optional[str], Optional[str]]:
        """Resolve the (user, token) pair used to authenticate requests.

        Credentials are resolved as a pair: if the client has its own user or its own token,
        only the client's pair is used (a missing half is never filled from the global session).
        The global ``session`` credentials are used only when the client has neither.

        Returns:
            Tuple[Optional[str], Optional[str]]: The effective (user, token) pair.
        """
        if self._user is not None or self._token is not None:
            return self._user, self._token
        return session.user, session.token

    @property
    def user(self) -> Optional[str]:
        """Get the effective username/email (the client's own pair, else the global session's)."""
        return self._credentials()[0]

    @user.setter
    def user(self, value: Optional[str]) -> None:
        """Set the authenticated username/email."""
        self._user = value

    @property
    def token(self) -> Optional[str]:
        """Get the effective API token (the client's own pair, else the global session's)."""
        return self._credentials()[1]

    @token.setter
    def token(self, value: Optional[str]) -> None:
        """Set the API token."""
        self._token = value

    @property
    def url(self) -> str:
        """Get the base API URL."""
        if self._url is not None:
            return self._url
        return session.url or "https://api.alegra.com/api/v1/"

    @url.setter
    def url(self, value: Optional[str]) -> None:
        """Set the base API URL.

        Args:
            value (str, optional): Base API URL, or None to use the global default.

        Raises:
            ValueError: If value is not None and is not a valid https (or loopback http) URL.
        """
        self._url = _validate_base_url(value) if value is not None else None

    @property
    def timeout(self) -> float:
        """Get the request timeout in seconds."""
        return self._timeout if self._timeout is not None else session.timeout

    @timeout.setter
    def timeout(self, value: Optional[float]) -> None:
        """Set the request timeout in seconds."""
        self._timeout = value

    def get_auth_header(self) -> str:
        """Generate the Basic Authorization header string from credentials.

        Returns:
            str: Basic authorization header, or empty string if credentials are missing.
        """
        user, token = self._credentials()
        if not user or not token:
            return ""
        api_key = base64.b64encode(f"{user}:{token}".encode()).decode()
        return f"Basic {api_key}"

    def _log_path(self, url: str) -> str:
        """Reduce a request URL to its path relative to the base URL, for logging.

        The host, query string and fragment are dropped because they may carry sensitive data.

        Args:
            url (str): Full endpoint URL.

        Returns:
            str: Path without the base path or query string.
        """
        path = urlsplit(url).path
        base_path = urlsplit(self.url).path.rstrip("/")
        if base_path and path.startswith(base_path):
            path = path[len(base_path):]
        return path

    def query(self, method: str, url: str, data: Optional[Dict[str, Any]] = None,
              params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Any:
        """Perform an HTTP request to the Alegra API and handle errors.

        Args:
            method (str): HTTP method (get, post, put, delete)
            url (str): Full endpoint URL
            data (dict, optional): Request body payload. Defaults to None.
            params (dict, optional): Query parameters. Defaults to None.
            files (dict, optional): Files for multipart uploads. Defaults to None.

        Returns:
            Any: Parsed JSON response from server (dict, list, or empty dict/value).

        Raises:
            AlegraAPIError: If the server returns a non-2xx status code or a request error occurs
                (transport errors chain the original exception as ``__cause__``). Typed subclasses
                are raised for known HTTP statuses and transport failures.
            ValueError: If the resolved base URL is not https (or loopback http); nothing is sent.
        """
        # Also covers the legacy global session.url, which is a plain class attribute
        _validate_base_url(self.url)

        # Build headers per request: the shared requests.Session must never carry credentials,
        # otherwise concurrent requests with different credentials could mix them up
        headers = {k: v for k, v in self.session.headers.items() if k.lower() != 'authorization'}
        auth_header = self.get_auth_header()
        if auth_header:
            headers['Authorization'] = auth_header
        if files:
            # Let requests determine the Content-Type with boundary for multipart/form-data
            headers.pop('Content-Type', None)

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                headers=headers,
                files=files,
                timeout=self.timeout
            )
        except Exception as e:
            # Exception text may include the URL and query params, so log only the class name
            logger.error(f"{method.upper()} - {self._log_path(url)} - request failed ({type(e).__name__})")
            raise _error_for_exception(e) from e

        short_url = self._log_path(url)

        if 200 <= response.status_code < 300:
            logger.info(f"{method.upper()} - {short_url} - Successful! (Status: {response.status_code})")
            if response.status_code == 204 or not response.text.strip():
                return {}
            try:
                return response.json()
            except ValueError:
                return {"response_text": response.text}

        # Handle errors
        error_msg = f"API error (Status {response.status_code})"
        try:
            res_json = response.json()
            if isinstance(res_json, dict) and 'message' in res_json:
                error_msg = res_json['message']
        except ValueError:
            res_json = None
            if response.text:
                error_msg = response.text

        # The API message may contain user data: it stays in the exception, never in the logs
        logger.warning(f"{method.upper()} - {short_url} - Failed! (Status: {response.status_code})")
        raise _error_for_status(error_msg, response.status_code, response.text, response.headers)


class session:
    """Legacy compatibility class representing global session configurations."""
    user: Optional[str] = None
    token: Optional[str] = None
    url: str = "https://api.alegra.com/api/v1/"
    timeout: float = 30
    headers: Dict[str, str] = {'Accept': 'application/json', 'Content-type': 'application/json'}

    @classmethod
    def create_auth(cls) -> None:
        """Compatibility method to populate headers dictionary"""
        if cls.user and cls.token:
            api_key = base64.b64encode(f"{cls.user}:{cls.token}".encode()).decode()
            cls.headers['Authorization'] = f"Basic {api_key}"

    @classmethod
    def query(cls, method: str, url: str, data: Optional[Dict[str, Any]] = None,
              params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Any:
        """Perform a query using the legacy global credentials.

        Delegates to the global default_client.
        """
        cls.create_auth()
        # Delegate to global default client
        return default_client.query(method, url, data=data, params=params, files=files)


# Instantiate the default global client for legacy import compatibility
default_client = AlegraClient()


