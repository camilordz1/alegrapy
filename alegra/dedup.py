"""Helpers for duplicate-safe creation (dedup keys and JSON-safe serialization)."""
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _json_safe(value: Any) -> Any:
    """Return a JSON-serializable copy of ``value``.

    ``Decimal`` becomes its plain decimal string (no exponent), dates and datetimes use
    ISO 8601, sets are sorted by string and tuples become lists. Unknown objects fall
    back to ``str``. The input is never mutated.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(item) for item in value), key=str)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
