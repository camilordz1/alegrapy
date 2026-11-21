import base64
import logging
from http.cookiejar import DefaultCookiePolicy
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit, urlunsplit
import requests

from alegrapy._deprecation import warn_legacy
from alegrapy.exceptions import (AlegraAPIError, AlegraNotFoundError, _error_for_exception,
                               _error_for_status)
from alegrapy.retry import (RetryPolicy, _may_have_been_processed, _retry_delay, _should_retry,
                          _sleep)

DEFAULT_BASE_URL = "https://api.alegra.com/api/v1/"
DEFAULT_TIMEOUT = 30

# Create a dedicated logger for the library, allowing applications to configure it
# The logger keeps the pre-rename name "alegra" on purpose, so existing logging
# configuration keeps working through 0.1.x; a rename is planned for 1.0
logger = logging.getLogger("alegra")

# Hosts allowed to use plain HTTP, for local testing only
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _normalize_base_url(url: str) -> str:
    """Ensure the base URL path ends with exactly one slash.

    Resource URLs are built by simple concatenation, so a base URL without the trailing
    slash would produce ``.../api/v1contacts``. Only the path is touched; the query
    string and fragment are preserved.

    Args:
        url (str): Base API URL.

    Returns:
        str: The URL with a single trailing slash in its path.
    """
    parts = urlsplit(url)
    path = parts.path.rstrip("/") + "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _validate_base_url(url: str) -> str:
    """Ensure the base API URL cannot expose credentials in transit.

    Args:
        url (str): Base API URL to validate.

    Returns:
        str: The URL with exactly one trailing slash in its path when valid.

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
        return _normalize_base_url(url)
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return _normalize_base_url(url)
    raise ValueError(
        f"Insecure base URL (scheme {parts.scheme!r}, host {host!r}): https is required "
        f"(http is allowed only for {', '.join(sorted(_LOOPBACK_HOSTS))})"
    )


class AlegraClient:
    """The main client interface for interacting with the Alegra API.

    Allows managing multiple API sessions with different credentials.

    Thread safety:
        Safe: any number of threads may send requests through the same client, and
        several clients with different credentials may be used at the same time. Every
        request builds its own ``Authorization`` header from the client it was sent
        through, and the shared connection pool never stores credentials or cookies.

        Not safe: changing a client's configuration (``user``, ``token``, ``url``,
        ``timeout``, ``retry``) while other threads are using it. Configure the client
        first, then share it.

        Resource attributes (``client.contacts``, ``client.invoices``, ...) may be
        accessed for the first time from any thread. A concurrent first access can build
        two equivalent, stateless resource objects bound to the same client; this is
        benign.

        Not safe for multiple tenants: the legacy global ``session`` and the module-level
        resources keep process-wide credentials. Multi-tenant applications must create
        one ``AlegraClient`` per tenant.
    """
    def __init__(self, user: Optional[str] = None, token: Optional[str] = None, url: Optional[str] = None,
                 timeout: Optional[float] = None, retry: Optional[RetryPolicy] = None) -> None:
        """Initialize the client.

        Args:
            user (str, optional): Alegra username (email).
            token (str, optional): Alegra API token.
            url (str, optional): Custom base API URL. Must use https (http only for loopback hosts).
                Defaults to ``DEFAULT_BASE_URL`` (``'https://api.alegra.com/api/v1/'``).
            timeout (float, optional): Request timeout in seconds. Defaults to the global session timeout (30).
            retry (RetryPolicy, optional): Retry policy. Defaults to the global session policy
                (``RetryPolicy()`` when unset).

        Raises:
            ValueError: If url is given and is not a valid https (or loopback http) URL.
        """
        self._user = user
        self._token = token
        self._url = None
        self.url = url  # validated by the setter
        self._timeout = timeout
        self._retry = retry
        self.session = requests.Session()
        # The API authenticates every request with a header and needs no cookies.
        # Rejecting them removes the cookie jar, the only shared mutable state left in
        # the pooled session, so one client can serve many threads safely.
        self.session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })

    @property
    def contacts(self) -> 'Contacts':
        """Access Contacts resource operations."""
        if not hasattr(self, '_contacts'):
            from alegrapy.contacts import Contacts
            self._contacts = Contacts(self)
        return self._contacts

    @property
    def invoices(self) -> 'Invoices':
        """Access Invoices resource operations."""
        if not hasattr(self, '_invoices'):
            from alegrapy.invoices import Invoices
            self._invoices = Invoices(self)
        return self._invoices

    @property
    def credit_notes(self) -> 'CreditNotes':
        """Access Credit Notes resource operations."""
        if not hasattr(self, '_credit_notes'):
            from alegrapy.credit_notes import CreditNotes
            self._credit_notes = CreditNotes(self)
        return self._credit_notes

    @property
    def payments(self) -> 'Payments':
        """Access Payments resource operations."""
        if not hasattr(self, '_payments'):
            from alegrapy.payments import Payments
            self._payments = Payments(self)
        return self._payments

    @property
    def items(self) -> 'Items':
        """Access Items resource operations."""
        if not hasattr(self, '_items'):
            from alegrapy.items import Items
            self._items = Items(self)
        return self._items

    @property
    def estimates(self) -> 'Estimates':
        """Access Estimates resource operations."""
        if not hasattr(self, '_estimates'):
            from alegrapy.estimates import Estimates
            self._estimates = Estimates(self)
        return self._estimates

    @property
    def purchase_orders(self) -> 'PurchaseOrders':
        """Access Purchase Orders resource operations."""
        if not hasattr(self, '_purchase_orders'):
            from alegrapy.purchase_orders import PurchaseOrders
            self._purchase_orders = PurchaseOrders(self)
        return self._purchase_orders

    @property
    def bank_accounts(self) -> 'BankAccounts':
        """Access Bank Accounts resource operations."""
        if not hasattr(self, '_bank_accounts'):
            from alegrapy.bank_accounts import BankAccounts
            self._bank_accounts = BankAccounts(self)
        return self._bank_accounts

    @property
    def taxes(self) -> 'Taxes':
        """Access Taxes resource operations."""
        if not hasattr(self, '_taxes'):
            from alegrapy.taxes import Taxes
            self._taxes = Taxes(self)
        return self._taxes

    @property
    def currencies(self) -> 'Currencies':
        """Access Currencies resource operations."""
        if not hasattr(self, '_currencies'):
            from alegrapy.currencies import Currencies
            self._currencies = Currencies(self)
        return self._currencies

    @property
    def retentions(self) -> 'Retentions':
        """Access Retentions resource operations."""
        if not hasattr(self, '_retentions'):
            from alegrapy.retentions import Retentions
            self._retentions = Retentions(self)
        return self._retentions

    @property
    def users(self) -> 'Users':
        """Access Users resource operations."""
        if not hasattr(self, '_users'):
            from alegrapy.users import Users
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
        """Get the base API URL (always with exactly one trailing slash)."""
        if self._url is not None:
            return self._url
        # The legacy class attribute bypasses the setter; normalize it here too
        return _normalize_base_url(session.url or DEFAULT_BASE_URL)

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

    @property
    def retry(self) -> RetryPolicy:
        """Get the retry policy (the client's own, else the global session's)."""
        if self._retry is not None:
            return self._retry
        if session.retry is not None:
            return session.retry
        return RetryPolicy()

    @retry.setter
    def retry(self, value: Optional[RetryPolicy]) -> None:
        """Set the retry policy (``None`` falls back to the global session's)."""
        self._retry = value

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

    def _warn_global_fallbacks(self) -> None:
        """Emit one-time warnings when a request actually falls back to ``session``."""
        if (self._user is None and self._token is None
                and (session.user is not None or session.token is not None)):
            warn_legacy(
                "client.fallback.credentials",
                "AlegraClient is falling back to the deprecated global "
                "session.user/session.token; pass user= and token= to AlegraClient(...). "
                "The global session will be removed in 1.0.",
                stacklevel=3,
            )
        if (self._url is None
                and _normalize_base_url(session.url or DEFAULT_BASE_URL) != DEFAULT_BASE_URL):
            warn_legacy(
                "client.fallback.url",
                "AlegraClient is falling back to the deprecated global session.url; "
                "pass url= to AlegraClient(...). The global session will be removed in 1.0.",
                stacklevel=3,
            )
        if self._timeout is None and session.timeout != DEFAULT_TIMEOUT:
            warn_legacy(
                "client.fallback.timeout",
                "AlegraClient is falling back to the deprecated global session.timeout; "
                "pass timeout= to AlegraClient(...). The global session will be removed in 1.0.",
                stacklevel=3,
            )
        if self._retry is None and session.retry is not None:
            warn_legacy(
                "client.fallback.retry",
                "AlegraClient is falling back to the deprecated global session.retry; "
                "pass retry= to AlegraClient(...). The global session will be removed in 1.0.",
                stacklevel=3,
            )

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

        A ``DELETE`` that returns 404 on a retry is treated as success and returns ``{}``
        only when any earlier attempt may have been processed (a timeout, an ambiguous
        connection error or a 5xx). After only 429s or provably unsent requests, the 404
        is a genuine not-found and raises ``AlegraNotFoundError``.

        Raises:
            AlegraAPIError: If the server returns a non-2xx status code or a request error occurs
                (transport errors chain the original exception as ``__cause__``). Typed subclasses
                are raised for known HTTP statuses and transport failures. Only
                ``requests.RequestException`` failures are wrapped: other exceptions, such as a
                payload that cannot be JSON-serialized, propagate unchanged. When retries are
                enabled, the error raised is the one from the last attempt.
            ValueError: If the resolved base URL is not https (or loopback http); nothing is sent.
        """
        # Also covers the legacy global session.url, which is a plain class attribute
        _validate_base_url(self.url)
        self._warn_global_fallbacks()

        headers = self._request_headers(files)
        policy = self.retry
        attempt = 0
        may_have_been_processed = False

        while True:
            try:
                return self._request_once(method, url, data, params, files, headers)
            except AlegraAPIError as error:
                if (method.upper() == "DELETE" and attempt > 0
                        and isinstance(error, AlegraNotFoundError)
                        and may_have_been_processed):
                    # Any earlier attempt may have deleted the record before failing
                    logger.warning(
                        f"{method.upper()} - {self._log_path(url)} - DELETE returned 404 on retry; "
                        f"treating as already deleted"
                    )
                    return {}
                may_have_been_processed = (may_have_been_processed
                                           or _may_have_been_processed(error))
                if attempt >= policy.max_retries or not _should_retry(policy, method, files, error):
                    raise
                delay = _retry_delay(policy, error, attempt)
                if delay is None:
                    raise

                detail = type(error).__name__
                if error.status_code is not None:
                    detail = f"{detail} (status {error.status_code})"
                logger.warning(
                    f"{method.upper()} - {self._log_path(url)} - retrying in {delay:.2f}s "
                    f"(attempt {attempt + 1}/{policy.max_retries}, {detail})"
                )
                _sleep(delay)
                attempt += 1

    def _request_headers(self, files: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Build the headers for one request.

        The shared ``requests.Session`` must never carry credentials, otherwise concurrent
        requests with different credentials could mix them up.

        Args:
            files (dict, optional): Files for multipart uploads, if any.

        Returns:
            dict: Headers to send with the request.
        """
        headers = {k: v for k, v in self.session.headers.items() if k.lower() != 'authorization'}
        auth_header = self.get_auth_header()
        if auth_header:
            headers['Authorization'] = auth_header
        if files:
            # Let requests determine the Content-Type with boundary for multipart/form-data
            headers.pop('Content-Type', None)
        return headers

    def _request_once(self, method: str, url: str, data: Optional[Dict[str, Any]],
                      params: Optional[Dict[str, Any]], files: Optional[Dict[str, Any]],
                      headers: Dict[str, str]) -> Any:
        """Send one attempt and translate the response or transport failure.

        Args:
            method (str): HTTP method.
            url (str): Full endpoint URL.
            data (dict, optional): Request body payload.
            params (dict, optional): Query parameters.
            files (dict, optional): Files for multipart uploads.
            headers (dict): Headers built for this request.

        Returns:
            Any: Parsed JSON response.

        Raises:
            AlegraAPIError: Typed error for the response status or transport failure.
        """
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
        except requests.RequestException as e:
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


    def close(self) -> None:
        """Close the underlying HTTP session and release pooled connections.

        Safe to call more than once. The client must not be reused after closing it;
        ``requests`` may silently reopen pools, which is unsupported behavior.
        """
        self.session.close()

    def __enter__(self) -> 'AlegraClient':
        """Return the client so it can be used in a ``with`` block."""
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close the client when leaving a ``with`` block; never swallow exceptions."""
        self.close()


class _LegacySessionMeta(type):
    """Metaclass that emits a one-time FutureWarning on ``session.<attr> = ...``."""

    def __setattr__(cls, name: str, value: Any) -> None:
        warn_legacy(
            f"session.{name}",
            f"session.{name} is deprecated; pass configuration to AlegraClient(...) "
            "instead. The global session will be removed in 1.0.",
            stacklevel=2,
        )
        super().__setattr__(name, value)


class session(metaclass=_LegacySessionMeta):
    """Legacy compatibility class representing global session configurations."""
    user: Optional[str] = None
    token: Optional[str] = None
    url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    retry: Optional[RetryPolicy] = None
    headers: Dict[str, str] = {'Accept': 'application/json', 'Content-type': 'application/json'}

    @classmethod
    def create_auth(cls) -> None:
        """Deprecated no-op retained for compatibility; never stores credentials."""
        cls.headers.pop('Authorization', None)
        warn_legacy(
            "session.create_auth",
            "session.create_auth() is deprecated and is now a no-op; pass user= and "
            "token= to AlegraClient(...). The global session will be removed in 1.0.",
            stacklevel=2,
        )

    @classmethod
    def query(cls, method: str, url: str, data: Optional[Dict[str, Any]] = None,
              params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Any:
        """Perform a query using the legacy global credentials.

        Delegates to the global default client.
        """
        warn_legacy(
            "session.query",
            "session.query() is deprecated; use AlegraClient(...).query() or resource "
            "methods on AlegraClient. The global session will be removed in 1.0.",
            stacklevel=2,
        )
        return _default_client.query(method, url, data=data, params=params, files=files)


# Internal default global client for legacy import compatibility
_default_client = AlegraClient()


def __getattr__(name: str) -> Any:
    if name == "default_client":
        warn_legacy(
            "session.default_client",
            "alegrapy.session.default_client is deprecated; instantiate AlegraClient(...) "
            "instead. The global default client will be removed in 1.0.",
            stacklevel=2,
        )
        return _default_client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


