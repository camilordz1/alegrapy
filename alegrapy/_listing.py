"""Shared list query parameter validation for Alegra resources."""

import numbers
from typing import AbstractSet, Any, Dict, Iterable, Tuple

from alegrapy._create_once import validate_lookup_date

ORDER_DIRECTIONS = frozenset({"ASC", "DESC"})


def validate_pagination(start: Any, limit: Any) -> Tuple[int, int]:
    """Validate ``start >= 0`` and ``1 <= limit <= 30`` (rejecting booleans)."""
    if isinstance(start, bool) or not isinstance(start, numbers.Integral) or start < 0:
        raise ValueError("start must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, numbers.Integral) or not 1 <= limit <= 30:
        raise ValueError("limit must be an integer between 1 and 30")
    return int(start), int(limit)


def validate_choice(name: str, value: Any, allowed: AbstractSet[str]) -> str:
    """Validate that ``value`` is a string in ``allowed``."""
    if not isinstance(value, str) or value not in allowed:
        if not allowed:
            raise ValueError(f"{name} is not supported on this endpoint")
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value


def validate_date_filters(filters: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    """Validate and normalize ISO ``YYYY-MM-DD`` / ``datetime.date`` filter keys."""
    validated = dict(filters)
    for key in keys:
        if key in validated:
            normalized = validate_lookup_date(validated[key])
            if normalized is None:
                raise ValueError(f"{key} must not be None")
            validated[key] = normalized
    return validated


def build_list_params(
    start: Any,
    limit: Any,
    filters: Dict[str, Any],
    *,
    order_fields: AbstractSet[str],
    enums: Dict[str, AbstractSet[str]],
    date_keys: Iterable[str],
    paginate: bool = True,
) -> Dict[str, Any]:
    """Validate pagination, ordering, enum filters, and date filters for ``list``."""
    params: Dict[str, Any] = {}
    if paginate:
        valid_start, valid_limit = validate_pagination(start, limit)
        params["start"] = valid_start
        params["limit"] = valid_limit
    elif start is not None or limit is not None:
        raise ValueError("pagination parameters are not supported on this endpoint")

    validated = validate_date_filters(filters, date_keys)

    if "order_field" in validated:
        validated["order_field"] = validate_choice(
            "order_field", validated["order_field"], order_fields
        )
    if "order_direction" in validated:
        if not order_fields:
            raise ValueError("order_direction is not supported on this endpoint")
        validated["order_direction"] = validate_choice(
            "order_direction", validated["order_direction"], ORDER_DIRECTIONS
        )

    for key, allowed in enums.items():
        if key in validated:
            validated[key] = validate_choice(key, validated[key], allowed)

    params.update(validated)
    return params
