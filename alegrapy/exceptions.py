"""Exceptions raised by the Alegra client.

Every exception in this module subclasses :class:`AlegraAPIError`, so existing
``except AlegraAPIError`` handlers keep catching HTTP and transport failures.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import copy
import math
from typing import Any, Dict, Mapping, Optional

import requests
import urllib3

from alegrapy.dedup import _json_safe


class AlegraAPIError(Exception):
    """Exception raised for errors in the Alegra API response.

    Attributes:
        message (str): Explanation of the error.
        status_code (int, optional): HTTP status code returned by the API.
        response_body (str, optional): Raw response body text from the server.
        retry_after (float, optional): Seconds to wait before retrying, taken from the
            ``Retry-After`` response header. ``None`` when the header is missing or
            cannot be parsed.
    """
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None,
                 retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.retry_after = retry_after

    @property
    def request_not_sent(self) -> bool:
        """Whether the request provably never reached Alegra.

        ``True`` only for a connect timeout or a refused/unresolvable connection.
        ``False`` when the request may have been processed, including every HTTP error
        response. Use it before re-creating non-idempotent records (invoices, payments).
        """
        return _was_not_sent(self.__cause__)


class AlegraAuthError(AlegraAPIError):
    """Authentication or authorization failed (HTTP 401 or 403)."""


class AlegraNotFoundError(AlegraAPIError):
    """The requested resource does not exist (HTTP 404)."""


class AlegraValidationError(AlegraAPIError):
    """The request payload was rejected by Alegra (HTTP 400 or 422)."""


class AlegraRateLimitError(AlegraAPIError):
    """The account hit an API rate limit (HTTP 429).

    Inspect ``retry_after`` for the server's suggested wait, when supplied.
    """


class AlegraServerError(AlegraAPIError):
    """Alegra failed while processing the request (any HTTP 5xx)."""


class AlegraConnectionError(AlegraAPIError):
    """The connection failed or broke before a complete response was received.

    This is ambiguous: the request MAY have reached Alegra and been processed, unless
    ``request_not_sent`` is ``True`` (connect timeout, connection refused or an
    unresolvable host). Do not re-create invoices or payments based on this class alone;
    check ``request_not_sent`` first.
    """


class AlegraTimeoutError(AlegraAPIError):
    """Alegra did not answer in time (read or other timeout).

    The request may have reached the server and been processed, so non-idempotent
    requests (invoice or payment creation) must not be retried blindly.
    """


class AlegraStampTimeoutError(AlegraTimeoutError):
    """Electronic stamping did not reach a final state within the polling window.

    Attributes:
        last_status (StampStatus, optional): Most recent status observed before timing out.
    """
    def __init__(self, message: str, *, last_status: Any = None) -> None:
        super().__init__(message)
        self.last_status = last_status


class AlegraFileNotAvailableError(AlegraAPIError):
    """The invoice has no downloadable file.

    Alegra does not generate a PDF for draft invoices; the XML is only available once
    the invoice is stamped.
    """


class AlegraStampError(AlegraAPIError):
    """The credit note was created but its electronic stamping failed.

    Alegra returns HTTP 400 with the created document; it is available as
    ``document`` so the caller can retry stamping instead of creating another note.
    """
    def __init__(self, message: str, *, document: Dict[str, Any],
                 status_code: Optional[int] = None, response_body: Optional[str] = None,
                 retry_after: Optional[float] = None) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body,
                         retry_after=retry_after)
        self.document = copy.deepcopy(document)


class AlegraAlreadyAnnulledError(AlegraAPIError):
    """The invoice is already fully cancelled by an annulment note.

    Attributes:
        invoice_id (int or str): Invoice that is already annulled.
    """
    def __init__(self, message: str, *, invoice_id: Any) -> None:
        super().__init__(message)
        self.invoice_id = invoice_id


class AlegraLookupIncompleteError(AlegraAPIError):
    """A dedup lookup stopped at ``max_pages`` without exhausting the target day."""

    def __init__(self, message: str, *, resource: str, dedup_key: str,
                 date: str, pages_scanned: int) -> None:
        super().__init__(message)
        self.resource = resource
        self.dedup_key = dedup_key
        self.date = date
        self.pages_scanned = pages_scanned


class AlegraUnverifiedCreateError(AlegraAPIError):
    """A create failed ambiguously and Alegra could not confirm whether it happened.

    The request may have created the record. Store the result of :meth:`to_dict` in a
    quarantine table/queue and reconcile it later; do not create the record again
    blindly.

    Attributes:
        dedup_key (str): Caller-supplied key used for the lookup.
        client_id (int or str): Client id used to scope the lookup.
        resource (str): Resource that was being created.
        payload (dict): Copy of the payload that was sent (marker included).
        attempts (int): Number of POSTs made.
        status_code (int, optional): Status of the last error, if any.
        response_body (str, optional): Body of the last error, if any.
    """
    def __init__(self, message: str, *, dedup_key: str, client_id: Any, resource: str = "invoices",
                 payload: Optional[dict] = None, attempts: int = 0,
                 status_code: Optional[int] = None, response_body: Optional[str] = None,
                 retry_after: Optional[float] = None) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body,
                         retry_after=retry_after)
        self.dedup_key = dedup_key
        self.client_id = client_id
        self.resource = resource
        self.payload = copy.deepcopy(payload) if payload is not None else {}
        self.attempts = attempts

    def to_dict(self) -> dict:
        """Return a JSON-serializable summary suitable for a quarantine table.

        Contains no credentials, headers or connection details.
        """
        return {
            "dedup_key": self.dedup_key,
            "client_id": self.client_id,
            "resource": self.resource,
            "payload": _json_safe(self.payload),
            "attempts": self.attempts,
            "status_code": self.status_code,
            "response_body": self.response_body,
        }


# Any other HTTP status (405, 409, ...) is reported with the base class.
_STATUS_ERRORS = {
    400: AlegraValidationError,
    401: AlegraAuthError,
    403: AlegraAuthError,
    404: AlegraNotFoundError,
    422: AlegraValidationError,
    429: AlegraRateLimitError,
}


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header without ever raising.

    Args:
        value (str, optional): Header value, either delta-seconds or an HTTP-date.

    Returns:
        float, optional: Seconds to wait (never negative), or ``None`` when the header
            is missing or unparseable.
    """
    if not value:
        return None

    text = value.strip()
    try:
        seconds = float(text)
    except (TypeError, ValueError):
        pass
    else:
        if not math.isfinite(seconds):
            return None
        return max(0.0, seconds)

    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


def _parse_reset_seconds(value: Optional[str]) -> Optional[float]:
    """Parse an ``X-Rate-Limit-Reset`` value (seconds left in the window).

    Negative or unparseable values yield ``None`` so the caller can fall back to backoff.

    Args:
        value (str, optional): Header value.

    Returns:
        float, optional: Non-negative seconds, or ``None``.
    """
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _was_not_sent(exc: Optional[BaseException]) -> bool:
    """Tell whether a transport error proves the request never reached Alegra.

    Only two cases are safe:

    - ``requests.ConnectTimeout``: the connection could not be established.
    - A ``requests.ConnectionError`` wrapping a ``urllib3.MaxRetryError`` whose reason is
      a ``urllib3.NewConnectionError`` (DNS failure, connection refused): the connection
      was never opened.

    Other connection errors (for example one wrapping ``ProtocolError`` or
    ``RemoteDisconnected``) can happen after the request was sent, so they are not safe
    for non-idempotent methods.

    Args:
        exc (BaseException, optional): Original exception raised by ``requests``.

    Returns:
        bool: ``True`` only when the request provably was not sent.
    """
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return True
    if not isinstance(exc, requests.exceptions.ConnectionError):
        return False

    cause = exc.args[0] if exc.args else None
    if not isinstance(cause, urllib3.exceptions.MaxRetryError):
        return False
    # NewConnectionError subclasses ConnectTimeoutError (urllib3 1.26 and 2.x). A plain
    # ConnectTimeoutError is not a NewConnectionError, and requests raises ConnectTimeout
    # for it, which the first check already handled.
    return isinstance(cause.reason, urllib3.exceptions.NewConnectionError)


def _error_for_status(message: str, status_code: int, response_body: Optional[str],
                      headers: Optional[Mapping[str, Any]] = None) -> AlegraAPIError:
    """Build the most specific error for an HTTP error response.

    Args:
        message (str): Error message extracted from the response.
        status_code (int): HTTP status code returned by the API.
        response_body (str, optional): Raw response body text.
        headers (Mapping, optional): Response headers, used for ``Retry-After``.

    Returns:
        AlegraAPIError: A typed error for known statuses, or the base class otherwise.
    """
    if 500 <= status_code <= 599:
        error_class = AlegraServerError
    else:
        error_class = _STATUS_ERRORS.get(status_code, AlegraAPIError)

    retry_after = _parse_retry_after(headers.get('Retry-After') if headers else None)
    if retry_after is None and status_code == 429:
        # Alegra documents X-Rate-Limit-Reset (seconds left), not Retry-After
        retry_after = _parse_reset_seconds(headers.get('X-Rate-Limit-Reset') if headers else None)
    return error_class(message, status_code=status_code, response_body=response_body,
                       retry_after=retry_after)


def _error_for_exception(exc: Exception) -> AlegraAPIError:
    """Map an exception raised by ``requests`` to a typed Alegra error.

    ``requests.ConnectTimeout`` is checked first because it subclasses both
    ``ConnectionError`` and ``Timeout``; it means the request was not sent.

    Args:
        exc (Exception): Original exception raised while sending the request.

    Returns:
        AlegraAPIError: The typed error that should replace ``exc``.
    """
    message = f"HTTP request failed ({type(exc).__name__})"
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return AlegraConnectionError(message)
    if isinstance(exc, requests.exceptions.Timeout):
        return AlegraTimeoutError(message)
    if isinstance(exc, requests.exceptions.ConnectionError):
        return AlegraConnectionError(message)
    return AlegraAPIError(message)
