"""Maintainer script to measure Alegra invoice list latency (NOT shipped in wheel/sdist).

Creates ONE draft invoice carrying a dedup marker, polls ``reconcile`` every 0.5 s
up to 60 s, and prints the elapsed seconds and invoice ID.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
import uuid
from typing import Optional, Sequence

from alegrapy import AlegraClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes-call-live-api",
        action="store_true",
        help="Required confirmation before creating a draft invoice on the live Alegra API.",
    )
    parser.add_argument("--client-id", required=True, help="Client ID for the draft invoice.")
    parser.add_argument("--item-id", required=True, help="Item ID for the draft invoice line.")
    parser.add_argument("--delete", action="store_true", help="Delete the draft invoice after measuring.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.yes_call_live_api:
        print("Refusing to call live Alegra API without --yes-call-live-api.", file=sys.stderr)
        sys.exit(2)

    user = os.environ.get("ALEGRA_USER", "").strip()
    token = os.environ.get("ALEGRA_TOKEN", "").strip()
    if not user or not token:
        print("ALEGRA_USER and ALEGRA_TOKEN must be set in the environment.", file=sys.stderr)
        sys.exit(2)

    today = dt.date.today().isoformat()
    dedup_key = f"latency-{uuid.uuid4().hex[:12]}"
    payload = {
        "date": today,
        "dueDate": today,
        "status": "draft",
        "client": {"id": args.client_id},
        "items": [{"id": args.item_id, "quantity": 1, "price": 1000}],
    }

    with AlegraClient(user=user, token=token) as client:
        created = client.invoices.create_once(payload, dedup_key=dedup_key, precheck=False)
        invoice_id = created["id"]
        start = time.monotonic()
        found = None
        while time.monotonic() - start <= 60.0:
            found = client.invoices.reconcile(dedup_key, args.client_id, date=today)
            if found is not None:
                break
            time.sleep(0.5)
        elapsed = time.monotonic() - start
        if found is not None:
            print(f"Visible in GET /invoices after {elapsed:.2f}s (invoice id={invoice_id})")
        else:
            print(f"Not visible within 60s (invoice id={invoice_id})")
        if args.delete:
            client.invoices.delete(invoice_id)
            print(f"Deleted draft invoice id={invoice_id}")
    return 0 if found is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
