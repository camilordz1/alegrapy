"""Helpers for duplicate-safe creation (dedup keys and JSON-safe serialization)."""
import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

_READABLE_PART = re.compile(r"[A-Za-z0-9_.-]+")
_NAMESPACE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,20}")


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


def _number_text(value: Any) -> str:
    """Render a number by value, without exponent or trailing zeros."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    if number == 0:
        number = Decimal("0")
    return format(number.normalize(), "f")


def _canonical_json(value: Any) -> str:
    """Stable JSON used for hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _key_part_text(value: Any, role: str) -> str:
    """Validate and normalize one ``make_dedup_key`` part."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{role} must not be blank")
        return text
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError(f"{role} must be a string, an int or a Decimal")
    return _number_text(value)


def make_dedup_key(*parts: Any, namespace: Any = None) -> str:
    """Build a deterministic dedup key from business identifiers.

    Parts are strings, non-bool ints or ``Decimal`` values (numbers are compared by
    value). The readable form is ``":".join(parts)`` when every part uses only letters,
    digits, ``_``, ``.`` or ``-`` and the result fits 64 characters; otherwise a hash is
    returned. The colon is reserved as the separator, so ``("a:b", "c")`` and
    ``("a", "b:c")`` cannot collide.

    Args:
        *parts: One or more business identifiers (order id, payment operation id, ...).
        namespace (str, optional): Prefix prepended as the first part, to avoid clashes
            between independent integrations.

    Returns:
        str: A key valid for ``Invoices.create_once``.

    Raises:
        ValueError: If a part is blank, a bool, a float or another unsupported type, or
            no parts are given.
    """
    texts = []
    if namespace is not None:
        texts.append(_key_part_text(namespace, "namespace"))
    if not parts:
        raise ValueError("make_dedup_key requires at least one part")
    texts.extend(_key_part_text(part, "part") for part in parts)

    readable = ":".join(texts)
    if len(readable) <= 64 and all(_READABLE_PART.fullmatch(text) for text in texts):
        return readable
    digest = hashlib.sha256(_canonical_json(texts).encode("utf-8")).hexdigest()[:40]
    return f"h:{digest}"


def make_dedup_key_from(payload: Mapping, fields: Sequence, namespace: Any = None) -> str:
    """Build a dedup key from selected fields of a payload.

    Use this only when there is no business id. You must choose the fields: there is no
    default set. Dotted paths select nested values; a segment ending in ``[]`` projects
    into every element of a list (``"items[].id"``).

    Canonicalization before hashing: dict keys are sorted, strings are stripped, numbers
    are compared by value, projected lists are sorted (their original order does not
    matter), other lists keep their order, dates and datetimes use ISO 8601, and ``None``
    stays null. Selecting a date or timestamp usually defeats deduplication because every
    payload differs.

    Args:
        payload (Mapping): Payload used for the invoice.
        fields (list[str]): Non-empty, unique dotted paths.
        namespace (str, optional): 1..20 chars of letters, digits, ``_``, ``.`` or
            ``-``; included in the hash and prefixed when it fits.

    Returns:
        str: A key valid for ``Invoices.create_once``.

    Raises:
        ValueError: If the payload is not a mapping, ``fields`` is empty/duplicated or
            contains an invalid or missing path, or the namespace is invalid.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    if (isinstance(fields, (str, bytes)) or not isinstance(fields, Sequence) or not fields):
        raise ValueError("fields must be a non-empty list of dotted paths")

    paths = []
    seen = set()
    for field in fields:
        if not isinstance(field, str):
            raise ValueError("field paths must be strings")
        path = field.strip()
        if not path:
            raise ValueError("field paths must not be blank")
        if path in seen:
            raise ValueError(f"duplicate field path: {path!r}")
        seen.add(path)
        paths.append(path)

    if namespace is not None:
        if not isinstance(namespace, str):
            raise ValueError("namespace must be a string")
        namespace = namespace.strip()
        if not _NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError(
                "namespace must be 1..20 characters of letters, digits, '_', '.' or '-'"
            )

    values = {}
    for path in paths:
        value, projected = _extract_path(payload, path)
        values[path] = _canonical_projected(value, projected)

    document = {"fields": sorted(paths), "values": values}
    if namespace is not None:
        document["namespace"] = namespace

    digest = hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()[:40]
    key = f"h:{digest}"
    if namespace is not None and len(namespace) + 1 + len(key) <= 64:
        return f"{namespace}:{key}"
    return key


def _extract_path(payload: Any, path: str) -> Any:
    """Extract a dotted path, projecting lists for segments ending in ``[]``."""
    values = [payload]
    projected = False

    for segment in path.split("."):
        project = segment.endswith("[]")
        key = segment[:-2] if project else segment
        if not key or "[]" in key:
            raise ValueError(f"Field path not found: {path!r}")

        next_values = []
        for value in values:
            if not isinstance(value, Mapping) or key not in value:
                raise ValueError(f"Field path not found: {path!r}")
            item = value[key]
            if project:
                if not isinstance(item, (list, tuple)):
                    raise ValueError(f"Field path not found: {path!r}")
                next_values.extend(item)
                projected = True
            else:
                next_values.append(item)
        values = next_values

    if projected:
        return values, True
    if len(values) != 1:
        raise ValueError(f"Field path not found: {path!r}")
    return values[0], False


def _canonical_projected(value: Any, projected: bool) -> Any:
    """Canonicalize an extracted value; projected lists are sorted."""
    if projected:
        items = [_canonical_value(item) for item in value]
        items.sort(key=_canonical_json)
        return items
    return _canonical_value(value)


def _canonical_value(value: Any) -> Any:
    """Canonical JSON value used by ``make_dedup_key_from``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, Decimal)):
        return _number_text(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical_value(item) for item in value), key=_canonical_json)
    return str(value)
