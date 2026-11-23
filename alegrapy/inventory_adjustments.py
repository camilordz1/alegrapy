import copy
import math
import numbers
from typing import Any, Dict, Iterator, List, Optional, Union

from alegrapy._create_once import (
    contains_marker,
    marker_for,
    payload_with_marker,
    run_create_once,
    validate_dedup_key,
    validate_lookup_date,
    validate_lookup_pages,
    validate_verify_window,
)
from alegrapy._listing import build_list_params
from alegrapy.actions import Actions, validate_id
from alegrapy.exceptions import AlegraAPIError, AlegraLookupIncompleteError

_ADJ_ORDER_FIELDS = frozenset({"id", "number", "date", "observations", "warehouse_name"})
_ADJ_DATE_KEYS = ("date",)
_ITEM_TYPES = frozenset({"in", "out"})


def _is_finite_real(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, numbers.Real)
        and math.isfinite(value)
    )


def _validate_adjustment_payload(params: Any, *, require_all: bool) -> Dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be a dict")
    cleaned = copy.deepcopy(params)

    if "date" in cleaned or require_all:
        norm_date = validate_lookup_date(cleaned.get("date"))
        if norm_date is None:
            raise ValueError("date is required")
        cleaned["date"] = norm_date

    if "items" in cleaned or require_all:
        items = cleaned.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("items must be a non-empty list")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("each item must be a dict")
            if "id" not in item:
                raise ValueError("each item must include 'id'")
            validate_id(item["id"])
            itype = item.get("type")
            if not isinstance(itype, str) or itype not in _ITEM_TYPES:
                raise ValueError("each item 'type' must be 'in' or 'out'")
            qty = item.get("quantity")
            if not _is_finite_real(qty) or qty <= 0:
                raise ValueError("each item 'quantity' must be a finite number > 0")
            cost = item.get("unitCost")
            if not _is_finite_real(cost) or cost < 0:
                raise ValueError("each item 'unitCost' must be a finite number >= 0")
    return cleaned


def _warehouse_id_from(raw_wh: Any) -> Optional[str]:
    if raw_wh is None:
        return None
    val = raw_wh.get("id") if isinstance(raw_wh, dict) else raw_wh
    if val is None:
        return None
    return str(validate_id(val))


class InventoryAdjustmentNumerations(Actions):
    """Operations for inventory adjustment numerations (``/inventory-adjustments/numerations``)."""
    endpoint: str = "inventory-adjustments/numerations"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the numerations sub-resource."""
        super().__init__(client)

    def list(self, start: int = 0, limit: int = 20, **kwargs: Any) -> List[Any]:
        """List inventory adjustment numerations (``limit`` defaults to 20, max 30)."""
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=frozenset(),
            enums={},
            date_keys=(),
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 20,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over inventory adjustment numerations."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=frozenset(),
            enums={},
            date_keys=(),
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)

    def create(self, params: Dict[str, Any], **kwargs: Any) -> Any:
        """Create a numeration (requires ``name`` and ``autoIncrement``)."""
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name is required")
        if params.get("autoIncrement") is None:
            raise ValueError("autoIncrement is required")
        return super().create(params, **kwargs)


class InventoryAdjustments(Actions):
    """Operations related to inventory adjustments (``/inventory-adjustments``)."""
    endpoint: str = "inventory-adjustments"

    def __init__(self, client: Optional['AlegraClient'] = None) -> None:
        """Initialize the resource."""
        super().__init__(client)

    @property
    def numerations(self) -> InventoryAdjustmentNumerations:
        """Access inventory adjustment numerations sub-resource."""
        if not hasattr(self, '_numerations'):
            self._numerations = InventoryAdjustmentNumerations(self.client)
        return self._numerations

    def list(self, start: int = 0, limit: int = 30, **kwargs: Any) -> List[Any]:
        """List inventory adjustments with optional ordering and filters."""
        params = build_list_params(
            start,
            limit,
            kwargs,
            order_fields=_ADJ_ORDER_FIELDS,
            enums={},
            date_keys=_ADJ_DATE_KEYS,
        )
        return self.client.query('get', self._collection_url(), params=params)

    def iter_all(self, max_items: Optional[int] = None, page_size: int = 30,
                 **filters: Any) -> Iterator[Any]:
        """Iterate lazily over inventory adjustments, validating filters eagerly."""
        build_list_params(
            0,
            page_size,
            filters,
            order_fields=_ADJ_ORDER_FIELDS,
            enums={},
            date_keys=_ADJ_DATE_KEYS,
        )
        return super().iter_all(max_items=max_items, page_size=page_size, **filters)

    def create(self, params: Dict[str, Any], **kwargs: Any) -> Any:
        """Create an inventory adjustment after validating ``date`` and ``items``."""
        payload = _validate_adjustment_payload(params, require_all=True)
        return super().create(payload, **kwargs)

    def update(self, id: Union[int, str], params: Dict[str, Any], **kwargs: Any) -> Any:
        """Update an inventory adjustment after validating provided ``date``/``items``."""
        payload = _validate_adjustment_payload(params, require_all=False)
        return super().update(id, payload, **kwargs)

    def reconcile(self, dedup_key: str, *, date: Any,
                  warehouse_id: Union[int, str, None] = None,
                  max_pages: int = 10) -> Optional[Dict[str, Any]]:
        """Return the newest adjustment carrying ``dedup_key`` on ``date``, or ``None``.

        Scans ``date`` in descending ``id`` order (newest first) up to ``max_pages``
        pages of 30 records. When ``warehouse_id`` is given, it is sent as a server
        filter and re-checked client-side. Raises :class:`AlegraLookupIncompleteError`
        only if ``max_pages`` full pages were scanned without finding a match.
        """
        key = validate_dedup_key(dedup_key)
        lookup_date = validate_lookup_date(date)
        if lookup_date is None:
            raise ValueError("date is required for inventory-adjustment reconciliation")
        pages = validate_lookup_pages(max_pages)
        valid_wh = validate_id(warehouse_id) if warehouse_id is not None else None
        expected_wh = str(valid_wh) if valid_wh is not None else None
        marker = marker_for(key)

        extra: Dict[str, Any] = {}
        if valid_wh is not None:
            extra["warehouse_id"] = valid_wh

        start = 0
        for _ in range(pages):
            page = self.list(
                start=start,
                limit=30,
                date=lookup_date,
                order_field="id",
                order_direction="DESC",
                **extra,
            )
            if not isinstance(page, list):
                raise AlegraAPIError(f"Unexpected response shape while listing {self.endpoint}")
            for adj in page:
                if not contains_marker(adj, marker):
                    continue
                if expected_wh is not None:
                    rec_wh = _warehouse_id_from(adj.get("warehouse") if isinstance(adj, dict) else None)
                    if rec_wh != expected_wh:
                        continue
                return adj
            if len(page) < 30:
                return None
            start += len(page)

        raise AlegraLookupIncompleteError(
            f"Inventory-adjustment lookup for {key!r} on {lookup_date} stopped after {pages} full pages",
            resource=self.endpoint,
            dedup_key=key,
            date=lookup_date,
            pages_scanned=pages,
        )

    def create_once(self, params: Dict[str, Any], dedup_key: str, *,
                    on_unverified: str = "retry", verify_window: float = 30.0,
                    max_pages: int = 10, precheck: bool = True) -> Any:
        """Create an inventory adjustment at most once per ``dedup_key``.

        Flow:

        1. With ``precheck``, look for the marker on ``params["date"]``; return the
           adjustment if found. If the day exceeds ``max_pages * 30`` adjustments,
           :class:`AlegraLookupIncompleteError` propagates and nothing is posted.
        2. POST the payload. A non-ambiguous failure is raised unchanged.
        3. On an ambiguous failure, verify during ``verify_window`` seconds.
        4. If not found and ``on_unverified="retry"``, POST once more and verify again;
           otherwise raise :class:`AlegraUnverifiedCreateError`.

        Limitations:
            The lookup covers only ``params["date"]``. Because an adjustment moves
            real stock, prefer ``on_unverified="raise"`` and quarantine
            :class:`AlegraUnverifiedCreateError` instead of retrying blindly. Ids may be
            reused after deletes.
        """
        key = validate_dedup_key(dedup_key)
        if on_unverified not in ("retry", "raise"):
            raise ValueError("on_unverified must be 'retry' or 'raise'")
        validate_verify_window(verify_window)
        pages = validate_lookup_pages(max_pages)
        validated = _validate_adjustment_payload(params, require_all=True)
        wh_id = _warehouse_id_from(validated.get("warehouse"))
        payload = payload_with_marker(validated, key)
        lookup_date = payload["date"]

        return run_create_once(
            post=self.create,
            lookup=lambda: self.reconcile(
                key, date=lookup_date, warehouse_id=wh_id, max_pages=pages
            ),
            payload=payload,
            dedup_key=key,
            client_id=wh_id,
            resource=self.endpoint,
            on_unverified=on_unverified,
            verify_window=verify_window,
            lookup_pages=pages,
            precheck=precheck,
            log_path=f"/{self.endpoint}",
        )
