"""Maintainer probe for debit-note ``observations`` marker & pagination (NOT shipped)."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


def pagination_verdict(p0: List[Any], p1: List[Any]) -> str:
    if len(p0) < 1 or len(p1) < 1:
        return "INCONCLUSIVE"
    if len(p0) == 1 and len(p1) == 1:
        id0 = p0[0].get("id") if isinstance(p0[0], dict) else None
        id1 = p1[0].get("id") if isinstance(p1[0], dict) else None
        if id0 is not None and id1 is not None and id0 != id1:
            return "PASS"
    return "FAIL"


def _count_type(raw: str) -> int:
    value = int(raw)
    if not 1 <= value <= 5:
        raise argparse.ArgumentTypeError("count must be between 1 and 5")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes-call-live-api", action="store_true",
                        help="Required confirmation before creating draft debit notes.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--invoice-id", required=True)
    parser.add_argument("--count", type=_count_type, default=2, help="Number of drafts (1..5).")
    parser.add_argument("--type", dest="note_type", default="VALUE_CHANGE")
    parser.add_argument("--payment-form", default="CASH")
    parser.add_argument("--delete", action="store_true", help="Delete created drafts afterwards.")
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

    created_notes: List[Tuple[Any, str]] = []
    verdicts: Dict[str, str] = {}
    with AlegraClient(user=user, token=token) as client:
        try:
            for _ in range(args.count):
                marker = f"alegrapy:dedup:probe-{uuid.uuid4().hex[:12]}"
                payload = build_probe_payload(
                    client_id=args.client_id, item_id=args.item_id, invoice_id=args.invoice_id,
                    note_type=args.note_type, payment_form=args.payment_form, marker=marker,
                )
                created = client.income_debit_notes.create(payload)
                note_id = created["id"]
                created_notes.append((note_id, marker))
                print(f"Created draft income debit note id={note_id}")

            persisted = True
            for note_id, marker in created_notes:
                fetched = client.income_debit_notes.read(note_id)
                obs = fetched.get("observations") if isinstance(fetched, dict) else None
                if not (isinstance(obs, str) and marker in obs):
                    persisted = False
            verdicts["a"] = "PASS" if persisted else "FAIL"
            print(f"(a) GET by id observations persists marker: {verdicts['a']}")

            p0 = client.income_debit_notes.list(start=0, limit=1)
            p1 = client.income_debit_notes.list(start=1, limit=1)
            verdicts["b"] = pagination_verdict(p0, p1)
            print(f"(b) Pagination honored (start=0/1 limit=1): {verdicts['b']}")

            p2 = client.income_debit_notes.list(start=0, limit=2)
            verdicts["c"] = "PASS" if len(p2) <= 2 else "FAIL"
            print(f"(c) Limit=2 honored (got {len(p2)}): {verdicts['c']}")

            scanned_ids = {
                n.get("id") for n in client.income_debit_notes.iter_all(max_items=60)
                if isinstance(n, dict)
            }
            all_found = all(note_id in scanned_ids for note_id, _ in created_notes)
            verdicts["d"] = "PASS" if all_found else "FAIL"
            print(f"(d) All created notes found in iter_all(60): {verdicts['d']}")
        finally:
            if args.delete:
                for note_id, _ in created_notes:
                    try:
                        client.income_debit_notes.delete(note_id)
                        client.income_debit_notes.read(note_id)
                        print(f"Delete check: note id={note_id} still readable")
                    except AlegraNotFoundError:
                        print(f"Delete check: note id={note_id} deleted (404 confirmed)")
                    except Exception as exc:
                        print(f"Delete check: note id={note_id} cleanup error ({type(exc).__name__})")

    return 0 if all(v == "PASS" for v in verdicts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
