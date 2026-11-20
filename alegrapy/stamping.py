"""Electronic stamping (DIAN emission) types, mapping, and response helpers."""

import enum
import json
import math
import numbers
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from alegrapy.actions import validate_id

from alegrapy.exceptions import AlegraAPIError

_MAX_STAMP_IDS = 10


class StampState(str, enum.Enum):
    """Normalized electronic-stamping state."""

    DRAFT = "DRAFT"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_OBSERVATIONS = "ACCEPTED_WITH_OBSERVATIONS"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


_RAW_STATE_MAP: Dict[str, StampState] = {
    "PENDING": StampState.PENDING,
    "STAMPED_AND_WAITING_RESPONSE": StampState.PENDING,
    "ACCEPTED": StampState.ACCEPTED,
    "STAMPED_AND_ACCEPTED": StampState.ACCEPTED,
    "STAMPED_AND_ACCEPTED_WITH_OBSERVATIONS": StampState.ACCEPTED_WITH_OBSERVATIONS,
    "REJECTED": StampState.REJECTED,
    "STAMPED_AND_REJECTED": StampState.REJECTED,
}

_EMITTED_STATES = frozenset({
    StampState.ACCEPTED,
    StampState.ACCEPTED_WITH_OBSERVATIONS,
})

_FINAL_STATES = frozenset({
    StampState.ACCEPTED,
    StampState.ACCEPTED_WITH_OBSERVATIONS,
    StampState.REJECTED,
})


def map_stamp_state(
    raw_value: Optional[str],
    *,
    invoice_status: Optional[str] = None,
) -> StampState:
    """Map an Alegra ``legalStatus`` or ``emissionStatus`` string to ``StampState``.

    Unknown values always map to ``StampState.UNKNOWN`` and are never inferred as
    emitted. When ``raw_value`` is ``None`` or blank, a ``draft`` invoice maps to
    ``StampState.DRAFT`` while any other invoice status maps to ``StampState.UNKNOWN``.
    """
    if isinstance(raw_value, str):
        normalized = raw_value.strip().upper()
        if normalized:
            return _RAW_STATE_MAP.get(normalized, StampState.UNKNOWN)

    if isinstance(invoice_status, str) and invoice_status.strip().lower() == "draft":
        return StampState.DRAFT
    return StampState.UNKNOWN


@dataclass(frozen=True)
class StampStatus:
    """Typed electronic-stamping status for a single invoice."""

    invoice_id: str
    state: StampState
    is_emitted: bool
    is_final: bool
    observations: List[str]
    cufe: Optional[str]
    stamped_at: Optional[str]
    legal_status_raw: Optional[str]
    invoice_status: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of this status."""
        return {
            "invoice_id": self.invoice_id,
            "state": self.state.value,
            "is_emitted": self.is_emitted,
            "is_final": self.is_final,
            "observations": list(self.observations),
            "cufe": self.cufe,
            "stamped_at": self.stamped_at,
            "legal_status_raw": self.legal_status_raw,
            "invoice_status": self.invoice_status,
        }


@dataclass(frozen=True)
class StampResult:
    """Per-invoice result returned by ``Invoices.stamp()``."""

    invoice_id: str
    success: bool
    message: str
    code: Optional[int]
    emission_status_raw: Optional[str]
    state: StampState


def validate_stamp_ids(ids: Iterable[Union[int, str]]) -> List[str]:
    """Validate 1..10 unique invoice IDs for ``POST /invoices/stamp``."""
    if isinstance(ids, (str, bytes)):
        raise ValueError("ids must be a sequence of invoice IDs, not a string")
    raw_list = list(ids)
    if not raw_list:
        raise ValueError("ids must contain at least 1 invoice ID")
    if len(raw_list) > _MAX_STAMP_IDS:
        raise ValueError(f"ids may contain at most {_MAX_STAMP_IDS} invoice IDs")

    normalized: List[str] = []
    seen = set()
    for item in raw_list:
        clean = str(validate_id(item))
        if clean in seen:
            raise ValueError(f"Duplicate invoice ID in ids: {clean}")
        seen.add(clean)
        normalized.append(clean)
    return normalized


def validate_poll_timing(timeout: Any, interval: Any) -> Tuple[float, float]:
    """Validate positive finite ``timeout`` and ``interval`` values in seconds."""
    parsed: List[float] = []
    for name, value in (("timeout", timeout), ("interval", interval)):
        if (isinstance(value, bool) or not isinstance(value, numbers.Real)
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be a positive finite number")
        parsed.append(float(value))
    return parsed[0], parsed[1]


def _collect_observations(stamp: Dict[str, Any]) -> List[str]:
    observations: List[str] = []
    for field in ("warnings", "errors"):
        raw = stamp.get(field)
        if isinstance(raw, list):
            for item in raw:
                text = item if isinstance(item, str) else (None if item is None else str(item))
                if text is not None and text.strip():
                    observations.append(text)
        elif isinstance(raw, str) and raw.strip():
            observations.append(raw)
    return observations


def stamp_status_from_invoice(
    invoice: Dict[str, Any],
    fallback_id: Optional[Union[int, str]] = None,
) -> StampStatus:
    """Build a ``StampStatus`` from a ``GET /invoices/{id}`` payload."""
    raw_id = invoice.get("id", fallback_id)
    invoice_id = str(raw_id) if raw_id is not None else ""
    invoice_status = invoice.get("status")
    if invoice_status is not None and not isinstance(invoice_status, str):
        invoice_status = str(invoice_status)

    stamp = invoice.get("stamp")
    if isinstance(stamp, dict):
        legal_status_raw = stamp.get("legalStatus")
        cufe = stamp.get("cufe")
        stamped_at = stamp.get("date")
        observations = _collect_observations(stamp)
    else:
        legal_status_raw = None
        cufe = None
        stamped_at = None
        observations = []

    state = map_stamp_state(legal_status_raw, invoice_status=invoice_status)
    return StampStatus(
        invoice_id=invoice_id,
        state=state,
        is_emitted=state in _EMITTED_STATES,
        is_final=state in _FINAL_STATES,
        observations=observations,
        cufe=cufe,
        stamped_at=stamped_at,
        legal_status_raw=legal_status_raw,
        invoice_status=invoice_status,
    )


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    # ASCII digits only: str.isdigit() also accepts characters such as "\u00b2" that int()
    # rejects, which would raise after the stamp POST was already accepted
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def parse_stamp_response(
    payload: Any,
    requested_ids: Sequence[str],
) -> List[StampResult]:
    """Parse a 200 ``POST /invoices/stamp`` response into per-ID ``StampResult`` items."""
    entries: Any = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        # The POST was accepted (HTTP 200), so this is NOT a local input error: the
        # invoices may have been emitted. Callers must check stamp_status() before retrying.
        raise AlegraAPIError(
            "Unexpected stamp response shape (no 'data' list); the invoices may have been "
            "emitted: check stamp_status() before stamping again"
        )

    parsed: List[StampResult] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        inv_id = str(entry["id"])
        emission_raw = entry.get("emissionStatus")
        state = map_stamp_state(emission_raw)
        result = StampResult(
            invoice_id=inv_id,
            # Only a real JSON true counts: "false", 1 or missing are never a success
            success=entry.get("success") is True,
            message=str(entry.get("message") or ""),
            code=_optional_int(entry.get("code")),
            emission_status_raw=emission_raw if isinstance(emission_raw, str) else None,
            state=state,
        )
        parsed.append(result)

    return _reconcile(parsed, requested_ids)


def _reconcile(results: List[StampResult], requested_ids: Sequence[str]) -> List[StampResult]:
    """Order results by the request and add a failed entry for every requested id the
    server did not answer; results for unrequested ids are appended at the end."""
    by_id: Dict[str, StampResult] = {}
    extra: List[StampResult] = []
    for result in results:
        if result.invoice_id in requested_ids and result.invoice_id not in by_id:
            by_id[result.invoice_id] = result
        else:
            extra.append(result)
    ordered: List[StampResult] = []
    for req_id in requested_ids:
        ordered.append(by_id.get(req_id) or StampResult(
            invoice_id=req_id,
            success=False,
            message="No result returned for this invoice",
            code=None,
            emission_status_raw=None,
            state=StampState.UNKNOWN,
        ))
    return ordered + extra


def parse_stamp_error_400(response_body: Optional[str],
                          requested_ids: Sequence[str] = ()) -> Optional[List[StampResult]]:
    """Return per-ID ``StampResult`` items for a 400 with ``data: [{id, ...}]``, else ``None``."""
    if not response_body:
        return None
    try:
        payload = json.loads(response_body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get("data")
    if not isinstance(entries, list) or not entries:
        return None

    results: List[StampResult] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") is None:
            return None
        emission_raw = entry.get("emissionStatus")
        results.append(
            StampResult(
                invoice_id=str(entry["id"]),
                success=False,
                message=str(entry.get("message") or ""),
                code=_optional_int(entry.get("code")),
                emission_status_raw=emission_raw if isinstance(emission_raw, str) else None,
                state=map_stamp_state(emission_raw),
            )
        )
    if not requested_ids:
        return results
    return _reconcile(results, requested_ids)
