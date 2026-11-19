"""Retry policy and helpers for transient Alegra failures.

Retries are deliberately implemented here instead of through ``urllib3.Retry`` /
``HTTPAdapter``: non-idempotent requests are only retried when the request provably
never reached Alegra, which requires inspecting the original exception.
"""
import numbers
import random
import time
from dataclasses import dataclass
from typing import Any, FrozenSet, Optional

import requests
import urllib3

from alegra.exceptions import (AlegraAPIError, AlegraConnectionError, AlegraRateLimitError,
                               AlegraTimeoutError)

# Methods whose repetition cannot create a second record on Alegra's side.
IDEMPOTENT_METHODS: FrozenSet[str] = frozenset({"GET", "PUT", "DELETE", "HEAD", "OPTIONS"})

DEFAULT_RETRY_STATUSES: FrozenSet[int] = frozenset({429, 502, 503, 504})

# Local failures that a retry cannot fix (TLS, proxy configuration, malformed URL).
# SSLError and ProxyError subclass requests.ConnectionError, so they need an explicit check.
_NON_RETRYABLE_CAUSES = (requests.exceptions.SSLError, requests.exceptions.ProxyError,
                         requests.exceptions.InvalidURL)


@dataclass(frozen=True)
class RetryPolicy:
    """How many times and how long to wait before retrying a failed request.

    Attributes:
        max_retries (int): Extra attempts after the first one; ``0`` disables retries.
        backoff_factor (float): Base delay in seconds for exponential backoff.
        backoff_max (float): Upper bound for a computed backoff delay, in seconds.
        retry_statuses (frozenset[int]): HTTP statuses retried for idempotent methods.
            500 is not included by default because on Alegra it usually means the payload
            was rejected.
        max_retry_after (float): Longest ``Retry-After`` / ``X-Rate-Limit-Reset`` we will
            honor. A longer delay stops retrying immediately.
    """
    max_retries: int = 2
    backoff_factor: float = 0.5
    backoff_max: float = 30.0
    retry_statuses: FrozenSet[int] = DEFAULT_RETRY_STATUSES
    max_retry_after: float = 60.0

    def __post_init__(self) -> None:
        """Validate the policy values.

        Raises:
            ValueError: If a value is negative (or ``max_retries`` is not an integer) or
                ``retry_statuses`` contains something that is not an HTTP status code.
        """
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int):
            raise ValueError("max_retries must be an integer")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        for name in ("backoff_factor", "backoff_max", "max_retry_after"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ValueError(f"{name} must be a number")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

        try:
            statuses = list(self.retry_statuses)
        except TypeError:
            raise ValueError("retry_statuses must be an iterable of HTTP status codes") from None
        for status in statuses:
            if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
                raise ValueError(f"retry_statuses contains an invalid status code: {status!r}")


def _was_not_sent(exc: BaseException) -> bool:
    """Tell whether a transport error proves the request never reached Alegra.

    Only two cases are safe:

    - ``requests.ConnectTimeout``: the connection could not be established.
    - A ``requests.ConnectionError`` wrapping a ``urllib3.MaxRetryError`` whose reason is
      a ``urllib3.NewConnectionError`` (DNS failure, connection refused): the connection
      was never opened.

    Other connection errors (for example one wrapping ``ProtocolError`` or
    ``RemoteDisconnected``) can happen after the request was sent, so they are not safe
    to retry for non-idempotent methods.

    Args:
        exc (BaseException): Original exception raised by ``requests``.

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
    # urllib3 2.x ConnectTimeoutError subclasses NewConnectionError, so both versions match
    return isinstance(cause.reason, urllib3.exceptions.NewConnectionError)


def _should_retry(policy: RetryPolicy, method: str, files: Any, error: AlegraAPIError) -> bool:
    """Decide whether a failed attempt may be repeated.

    Args:
        policy (RetryPolicy): Active retry policy.
        method (str): HTTP method used for the request.
        files (Any): Multipart files passed to the request, if any.
        error (AlegraAPIError): Typed error raised by the attempt.

    Returns:
        bool: ``True`` when the request can be retried safely.
    """
    if files:
        # File streams are consumed by the first attempt.
        return False

    if isinstance(error.__cause__, _NON_RETRYABLE_CAUSES):
        return False

    if method.upper() in IDEMPOTENT_METHODS:
        if isinstance(error, (AlegraConnectionError, AlegraTimeoutError)):
            return True
        return error.status_code in policy.retry_statuses

    # Non-idempotent (POST, PATCH, unknown): a retry may create a duplicate invoice.
    if isinstance(error, AlegraRateLimitError):
        return True
    cause = error.__cause__
    return cause is not None and _was_not_sent(cause)


def _retry_delay(policy: RetryPolicy, error: AlegraAPIError, attempt: int) -> Optional[float]:
    """Compute the delay before the next attempt.

    ``Retry-After`` / ``X-Rate-Limit-Reset`` wins over exponential backoff. Otherwise the
    delay is full-jitter exponential backoff.

    Args:
        policy (RetryPolicy): Active retry policy.
        error (AlegraAPIError): Error raised by the attempt.
        attempt (int): Zero-based retry attempt number.

    Returns:
        float, optional: Seconds to wait, or ``None`` when the server asks for a delay
            longer than ``max_retry_after`` and retrying should stop.
    """
    if error.retry_after is not None:
        if error.retry_after > policy.max_retry_after:
            return None
        return float(error.retry_after)

    cap = min(policy.backoff_max, policy.backoff_factor * 2 ** attempt)
    return random.uniform(0, cap)


def _sleep(delay: float) -> None:
    """Sleep between attempts (indirection so tests can patch ``alegra.retry.time``)."""
    time.sleep(delay)
