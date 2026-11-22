"""Maintainer probe for debit-note ``observations`` marker & pagination (NOT shipped)."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import uuid
from typing import Any, Dict, Optional, Sequence

from alegrapy import AlegraClient, AlegraNotFoundError


def build_probe_payload(*, client_id: str, item_id: str, invoice_id: str,
                        note_type: str, payment_form: str, marker: str) -> Dict[str, Any]:
    today = dt.date.today().isoformat()
    return {
        "date": today,
        "dueDate": today,
        "status": "draft",
        "type": note_type,
        "paymentMethod": payment_form,
        "paymentType": payment_form,
        "client": {"id": client_id},
        "invoice": {"id": invoice_id},
        "items": [{"id": item_id, "quantity": 1, "price": 1000}],
        "observations": marker,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes-call-live-api", action="store_true",
                        help="Required confirmation before creating a draft debit note.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--invoice-id", required=True)
    parser.add_argument("--type", dest="note_type", default="VALUE_CHANGE")
    parser.add_argument("--payment-form", default="CASH")
    parser.add_argument("--delete", action="store_true", help="Delete the draft afterwards.")
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

    marker = f"alegrapy:dedup:probe-{uuid.uuid4().hex[:12]}"
    payload = build_probe_payload(
        client_id=args.client_id, item_id=args.item_id, invoice_id=args.invoice_id,
        note_type=args.note_type, payment_form=args.payment_form, marker=marker,
    )
    with AlegraClient(user=user, token=token) as client:
        created = client.income_debit_notes.create(payload)
        note_id = created["id"]
        print(f"Created draft income debit note id={note_id}")
        fetched = client.income_debit_notes.read(note_id)
        obs = fetched.get("observations") if isinstance(fetched, dict) else None
        print(f"(a) GET by id observations persists marker: {isinstance(obs, str) and marker in obs}")
        p0 = client.income_debit_notes.list(start=0, limit=1)
        p1 = client.income_debit_notes.list(start=1, limit=1)
        id0 = p0[0].get("id") if p0 else None
        id1 = p1[0].get("id") if p1 else None
        print(f"(b) Pagination honored (len<=1 and start=1 differs): {len(p0) <= 1 and id0 != id1}")
        found = any(
            isinstance(n, dict) and n.get("id") == note_id
            for n in client.income_debit_notes.iter_all(max_items=60)
        )
        print(f"(c) Found in list scan: {found}")
        if args.delete:
            client.income_debit_notes.delete(note_id)
            try:
                client.income_debit_notes.read(note_id)
                print(f"Delete check: note id={note_id} still readable")
            except AlegraNotFoundError:
                print(f"Delete check: note id={note_id} deleted (404 confirmed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
