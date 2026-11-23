"""Maintainer probe for live inventory adjustments (NOT shipped in wheel/sdist)."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import uuid
from typing import Any, Dict, Optional, Sequence, Tuple

from alegrapy import AlegraClient, AlegraNotFoundError


def build_adjustment_payload(*, item_id: str, quantity: float, unit_cost: float,
                             warehouse_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "date": dt.date.today().isoformat(),
        "items": [{"id": item_id, "type": "in", "quantity": quantity, "unitCost": unit_cost}],
    }
    if warehouse_id is not None:
        payload["warehouse"] = {"id": warehouse_id}
    return payload


def _extract_stock(item: Dict[str, Any], warehouse_id: Optional[str]) -> float:
    inv = item.get("inventory") or {}
    if warehouse_id is not None:
        for wh in inv.get("warehouses") or []:
            if isinstance(wh, dict) and str(wh.get("id")) == str(warehouse_id):
                return float(wh["availableQuantity"])
        # Never fall back to the item total: the comparison would use the wrong number
        raise ValueError(f"Warehouse {warehouse_id} not found in the item's inventory")
    return float(inv["availableQuantity"])


def compensation_hint(*, initial: float, current: float) -> Optional[Tuple[str, float]]:
    """Return the ``(type, quantity)`` adjustment that restores ``initial``, or ``None``."""
    delta = current - initial
    if delta > 0:
        return ("out", delta)
    if delta < 0:
        return ("in", -delta)
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes-call-live-api", action="store_true",
                        help="Required confirmation before calling the live Alegra API.")
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--warehouse-id", default=None)
    parser.add_argument("--quantity", type=float, default=1.0)
    parser.add_argument("--delete", action="store_true",
                        help="Required safety flag: delete the probe adjustment afterwards.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.yes_call_live_api or not args.delete:
        print("Refusing to run without both --yes-call-live-api and --delete.", file=sys.stderr)
        sys.exit(2)
    user = os.environ.get("ALEGRA_USER", "").strip()
    token = os.environ.get("ALEGRA_TOKEN", "").strip()
    if not user or not token:
        print("ALEGRA_USER and ALEGRA_TOKEN must be set in the environment.", file=sys.stderr)
        sys.exit(2)

    dedup_key = f"probe-adj-{uuid.uuid4().hex[:12]}"
    verdicts: Dict[str, str] = {}
    adj_id: Optional[str] = None
    with AlegraClient(user=user, token=token) as client:
        item = client.items.read(args.item_id)
        inv = item.get("inventory") if isinstance(item, dict) else None
        if not isinstance(inv, dict):
            print(f"Item {args.item_id} has no 'inventory' object.", file=sys.stderr)
            return 2
        try:
            initial_stock = _extract_stock(item, args.warehouse_id)
        except ValueError as exc:
            print(f"{exc}; nothing was created.", file=sys.stderr)
            return 2
        unit_cost = float(inv.get("unitCost", 0))
        payload = build_adjustment_payload(
            item_id=args.item_id, quantity=args.quantity, unit_cost=unit_cost,
            warehouse_id=args.warehouse_id,
        )
        created = client.inventory_adjustments.create_once(payload, dedup_key=dedup_key)
        adj_id = created["id"]
        print(f"Created inventory adjustment id={adj_id}")
        try:
            fetched = client.inventory_adjustments.read(adj_id)
            obs = fetched.get("observations") if isinstance(fetched, dict) else None
            verdicts["a"] = "PASS" if isinstance(obs, str) and dedup_key in obs else "FAIL"
            print(f"(a) Marker persists on GET: {verdicts['a']}")

            rec = client.inventory_adjustments.reconcile(
                dedup_key, date=payload["date"], warehouse_id=args.warehouse_id
            )
            verdicts["b"] = "PASS" if isinstance(rec, dict) and rec.get("id") == adj_id else "FAIL"
            print(f"(b) reconcile finds adjustment: {verdicts['b']}")

            posts = 0
            orig_create = client.inventory_adjustments.create

            def counted_create(data, **kw):
                nonlocal posts
                posts += 1
                return orig_create(data, **kw)

            client.inventory_adjustments.create = counted_create  # type: ignore[method-assign]
            try:
                second = client.inventory_adjustments.create_once(payload, dedup_key=dedup_key)
            finally:
                client.inventory_adjustments.create = orig_create  # type: ignore[method-assign]
            verdicts["c"] = "PASS" if posts == 0 and second.get("id") == adj_id else "FAIL"
            print(f"(c) Second create_once idempotent (posts={posts}): {verdicts['c']}")

            after_item = client.items.read(args.item_id)
            after_stock = _extract_stock(after_item, args.warehouse_id)
            verdicts["d"] = "PASS" if after_stock == initial_stock + args.quantity else "FAIL"
            print(f"(d) Stock rose by {args.quantity} ({initial_stock} -> {after_stock}): {verdicts['d']}")
        finally:
            if adj_id is not None:
                try:
                    client.inventory_adjustments.delete(adj_id)
                    try:
                        client.inventory_adjustments.read(adj_id)
                        print(f"Delete check: id={adj_id} still readable")
                    except AlegraNotFoundError:
                        print(f"Delete check: id={adj_id} deleted (404 confirmed)")
                except Exception as exc:
                    print(f"Cleanup error deleting {adj_id}: {type(exc).__name__}", file=sys.stderr)
                reverted_item = client.items.read(args.item_id)
                reverted_stock = _extract_stock(reverted_item, args.warehouse_id)
                if reverted_stock == initial_stock:
                    verdicts["e"] = "PASS"
                    print(f"(e) Stock reverted to {initial_stock}: PASS")
                else:
                    verdicts["e"] = "FAIL"
                    hint = compensation_hint(initial=initial_stock, current=reverted_stock)
                    kind, qty = hint if hint is not None else ("none", 0.0)
                    print(
                        f"WARNING: Stock did NOT revert ({initial_stock} -> {reverted_stock}). "
                        f"To restore it, apply a '{kind}' adjustment for item {args.item_id}, "
                        f"quantity={qty}, unitCost={unit_cost} (the difference may include "
                        f"concurrent sales: check before applying).",
                        file=sys.stderr,
                    )
    return 0 if all(v == "PASS" for v in verdicts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
