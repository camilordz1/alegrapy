"""Exceptions raised by the Alegra client.

Every exception in this module subclasses :class:`AlegraAPIError`, so existing
``except AlegraAPIError`` handlers keep catching HTTP and transport failures.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Optional

import requests


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
    """The request never reached Alegra (connection or connect-timeout error).

    ``requests.ConnectTimeout`` is reported here rather than as a timeout because it
    means the connection could not be established, so the request was provably not
    sent. Retries and other recovery logic may treat it as safe for non-idempotent
    requests, unlike :class:`AlegraTimeoutError`.
    """


class AlegraTimeoutError(AlegraAPIError):
    """Alegra did not answer in time (read or other timeout).

    The request may have reached the server and been processed, so non-idempotent
    requests (invoice or payment creation) must not be retried blindly.
    """


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
        return max(0.0, float(text))
    except (TypeError, ValueError):
        pass

    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


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
