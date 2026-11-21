"""Shared duplicate-safe create flow used by invoices, credit notes, and payments.

Private module: callers use ``Invoices.create_once``, ``Invoices.annul``, or
``Payments.create_once``.
"""
import copy
import datetime
import logging
import math
import numbers
import re
import time
from typing import Any, Callable, Dict, Optional, Union

from alegrapy.actions import validate_id
from alegrapy.exceptions import (AlegraAlreadyAnnulledError, AlegraAPIError, AlegraStampError,
                               AlegraUnverifiedCreateError)
from alegrapy.retry import _may_have_been_processed

logger = logging.getLogger("alegra")

_DEDUP_KEY_PATTERN = re.compile(r'[A-Za-z0-9_.:-]+')
_LOOKUP_DATE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}')
_MARKER_PREFIX = "alegrapy:dedup:"
_MAX_OBSERVATIONS = 500
_VERIFY_INITIAL_INTERVAL = 1.0
_VERIFY_MAX_INTERVAL = 8.0


def validate_dedup_key(dedup_key: Any) -> str:
    """Validate and strip a dedup key."""
    if not isinstance(dedup_key, str):
        raise ValueError("dedup_key must be a string")
    key = dedup_key.strip()
    if not 1 <= len(key) <= 64 or not _DEDUP_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "dedup_key must be 1..64 characters using letters, digits, '_', '.', ':' or '-'"
        )
    return key


def marker_for(key: str) -> str:
    """Return the observations marker for a dedup key."""
    return f"{_MARKER_PREFIX}{key}"


def contains_marker(record: Any, marker: str) -> bool:
    """Whether a record's ``observations`` contains the marker as a whole line."""
    if not isinstance(record, dict):
        return False
    observations = record.get("observations")
    if not isinstance(observations, str):
        return False
    return any(line.strip() == marker for line in observations.splitlines())


def validate_lookup_pages(lookup_pages: Any) -> int:
    if (isinstance(lookup_pages, bool) or not isinstance(lookup_pages, numbers.Integral)
            or lookup_pages < 1):
        raise ValueError("lookup_pages must be a positive integer")
    return int(lookup_pages)


def validate_verify_window(verify_window: Any) -> float:
    if (isinstance(verify_window, bool) or not isinstance(verify_window, numbers.Real)
            or not math.isfinite(verify_window) or verify_window < 0):
        raise ValueError("verify_window must be a finite, non-negative number")
    return float(verify_window)


def validate_lookup_date(value: Any) -> Optional[str]:
    """Validate an optional lookup date (strict ``YYYY-MM-DD`` or ``datetime.date``)."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        raise ValueError("date must be a datetime.date or 'YYYY-MM-DD' string, not datetime")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, str) and _LOOKUP_DATE_PATTERN.fullmatch(value):
        try:
            return datetime.date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise ValueError("date must be a datetime.date or strict 'YYYY-MM-DD' string")


def client_id_from(params: Dict[str, Any], *,
                   required: bool = True) -> Union[int, str, None]:
    """Read and validate the client id from ``params['client']``.

    Accepts ``{"id": x}`` or a bare id. When ``required`` is True, a missing
    client raises ``ValueError``; when False, it returns ``None``.
    """
    client = params.get("client")
    raw = client.get("id") if isinstance(client, dict) else client
    if raw is None:
        if required:
            raise ValueError(
                "params['client'] must provide the client id used for the dedup lookup"
            )
        return None
    return validate_id(raw)


def record_client_id(record: Any) -> Optional[str]:
    """Return a record's client id as a comparable string, when present and valid."""
    if not isinstance(record, dict):
        return None
    client = record.get("client")
    raw = client.get("id") if isinstance(client, dict) else client
    if raw is None:
        return None
    try:
        return str(validate_id(raw))
    except ValueError:
        return None


def payload_with_marker(params: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Build a copy of ``params`` with the dedup marker on its own line.

    Re-submitting a stored payload is safe: an existing identical marker is kept as-is
    instead of appended again, and a payload carrying a different dedup key is rejected.
    """
    payload = copy.deepcopy(params)
    existing = payload.get("observations")
    marker = marker_for(key)

    if existing:
        lines = [line.strip() for line in str(existing).splitlines()]
        if marker in lines:
            return payload
        if any(line.startswith(_MARKER_PREFIX) for line in lines):
            raise ValueError("observations already contains a different dedup marker")
        observations = f"{existing}\n{marker}"
    else:
        observations = marker

    if len(observations) > _MAX_OBSERVATIONS:
        raise ValueError(
            f"observations would exceed {_MAX_OBSERVATIONS} characters with the dedup marker"
        )
    payload["observations"] = observations
    return payload


def run_create_once(*, post: Callable[[Dict[str, Any]], Any],
                    lookup: Callable[[], Optional[Dict[str, Any]]],
                    payload: Dict[str, Any], dedup_key: str,
                    client_id: Any, resource: str,
                    on_unverified: str = "retry", verify_window: float = 30.0,
                    lookup_pages: int = 2, precheck: bool = True,
                    before_post: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
                    log_path: str) -> Any:
    """POST once (twice at most), verifying ambiguous failures by dedup marker.

    ``before_post`` runs before every POST attempt. If it returns a document, that
    document is returned instead of posting; it may also raise to abort the create.
    """
    if on_unverified not in ("retry", "raise"):
        raise ValueError("on_unverified must be 'retry' or 'raise'")
    window = validate_verify_window(verify_window)
    pages = validate_lookup_pages(lookup_pages)

    if precheck:
        existing = lookup()
        if existing is not None:
            return existing

    existing = before_post() if before_post is not None else None
    if existing is not None:
        return existing

    attempts = 1
    try:
        return post(payload)
    except AlegraStampError:
        raise
    except AlegraAPIError as error:
        if not _may_have_been_processed(error):
            raise
        last_error = error

    found = _verified_lookup(lookup, window, payload, dedup_key, client_id,
                             resource, attempts, last_error, log_path)
    if found is not None:
        return found
    if on_unverified == "raise":
        raise _unverified_error(dedup_key, client_id, resource, payload,
                                attempts, last_error) from last_error

    # The first POST may have created the document, so a failing guard here must not
    # surface raw: quarantine it, unless the guard reached a definitive outcome
    # "Already annulled" here most likely means this call's own first POST succeeded, so it
    # is quarantined too (with the dedup data) instead of surfacing only the invoice id
    try:
        existing = before_post() if before_post is not None else None
    except AlegraStampError:
        raise
    except (AlegraAlreadyAnnulledError, AlegraAPIError, ValueError) as guard_error:
        raise _unverified_error(dedup_key, client_id, resource, payload,
                                attempts, last_error) from guard_error
    if existing is not None:
        return existing

    logger.warning(
        f"POST - {log_path} - dedup key {dedup_key!r} unverified; "
        f"retrying create (attempt 2)"
    )
    attempts = 2
    try:
        return post(payload)
    except AlegraStampError:
        # Definitive "created but not stamped" outcome: never wrap or retry it
        raise
    except AlegraAPIError as error:
        if not _may_have_been_processed(error):
            # The first attempt may still have created the document: quarantine it
            raise _unverified_error(dedup_key, client_id, resource, payload,
                                    attempts, error) from error
        last_error = error

    found = _verified_lookup(lookup, window, payload, dedup_key, client_id,
                             resource, attempts, last_error, log_path)
    if found is not None:
        return found
    raise _unverified_error(dedup_key, client_id, resource, payload,
                            attempts, last_error) from last_error


def _verified_lookup(lookup: Callable[[], Optional[Dict[str, Any]]], verify_window: float,
                     payload: Dict[str, Any], dedup_key: str, client_id: Any,
                     resource: str, attempts: int, cause: AlegraAPIError,
                     log_path: str) -> Optional[Dict[str, Any]]:
    """Run the verification window; wrap lookup failures as unverified creates."""
    try:
        return _verify_until_found(lookup, verify_window, dedup_key, log_path)
    except AlegraStampError:
        # The lookup found the document but it was not stamped: a definitive outcome
        raise
    except AlegraAPIError as lookup_error:
        raise _unverified_error(dedup_key, client_id, resource, payload, attempts,
                                lookup_error, details_source=cause) from lookup_error


def _verify_until_found(lookup: Callable[[], Optional[Dict[str, Any]]],
                        verify_window: float, dedup_key: str,
                        log_path: str) -> Optional[Dict[str, Any]]:
    """Look for the marker at increasing intervals until the window elapses."""
    deadline = time.monotonic() + verify_window
    interval = _VERIFY_INITIAL_INTERVAL
    lookup_number = 0

    while True:
        lookup_number += 1
        logger.warning(
            f"POST - {log_path} - verifying dedup key {dedup_key!r} "
            f"(lookup {lookup_number})"
        )
        found = lookup()
        if found is not None:
            return found

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(interval, remaining))
        interval = min(interval * 2, _VERIFY_MAX_INTERVAL)


def _unverified_error(dedup_key: str, client_id: Any, resource: str,
                      payload: Dict[str, Any], attempts: int, cause: AlegraAPIError,
                      details_source: Optional[AlegraAPIError] = None) -> AlegraUnverifiedCreateError:
    """Build the quarantine error carrying the last ambiguous error's HTTP details."""
    details = details_source if details_source is not None else cause
    return AlegraUnverifiedCreateError(
        f"{resource} creation unverified for dedup key {dedup_key!r}",
        dedup_key=dedup_key,
        client_id=client_id,
        resource=resource,
        payload=payload,
        attempts=attempts,
        status_code=details.status_code,
        response_body=details.response_body,
        retry_after=details.retry_after,
    )
