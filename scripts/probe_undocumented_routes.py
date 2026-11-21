"""Maintainer probe for undocumented Alegra endpoints (NOT shipped in wheel/sdist).

Posts to a non-existent ID and compares the response against a documented sibling
GET route, printing status, verdict, and body excerpts for manual audit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional, Sequence

import requests

BASE_URL = "https://api.alegra.com/api/v1"
NON_EXISTENT_ID = "999999999"

TARGETS = (
    ("POST /estimates/{id}/void", f"/estimates/{NON_EXISTENT_ID}/void", None, f"/estimates/{NON_EXISTENT_ID}"),
    ("POST /estimates/{id}/open", f"/estimates/{NON_EXISTENT_ID}/open", None, f"/estimates/{NON_EXISTENT_ID}"),
    ("POST /purchase-orders/{id}/email", f"/purchase-orders/{NON_EXISTENT_ID}/email", {"emails": []}, f"/purchase-orders/{NON_EXISTENT_ID}"),
    ("POST /purchase-orders/{id}/comments", f"/purchase-orders/{NON_EXISTENT_ID}/comments", {"comments": "probe"}, f"/purchase-orders/{NON_EXISTENT_ID}"),
)


def _excerpt(text: str, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit]


def _has_json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except (ValueError, TypeError):
        return False


def _classify(post_resp: requests.Response, sibling_resp: requests.Response) -> str:
    if post_resp.status_code in (400, 422):
        return "route exists"
    if post_resp.status_code in (405, 501):
        return "route missing"
    if post_resp.status_code == 404:
        if sibling_resp.status_code == 404 and post_resp.text == sibling_resp.text:
            return "route exists"
        if not _has_json_object(post_resp.text):
            return "route missing"
        return "inconclusive"
    return "inconclusive"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes-call-live-api",
        action="store_true",
        help="Required confirmation before sending requests to the live Alegra API.",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="Request timeout in seconds.")
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

    session = requests.Session()
    session.auth = (user, token)
    session.headers["Accept"] = "application/json"

    siblings: dict[str, requests.Response] = {}
    print(f"{'Route':<38} {'Status':<8} {'Verdict':<15} {'POST body':<30} Sibling GET body")
    print("-" * 110)
    for label, post_path, body, sibling_path in TARGETS:
        if sibling_path not in siblings:
            siblings[sibling_path] = session.get(f"{BASE_URL}{sibling_path}", timeout=args.timeout)
        sibling_resp = siblings[sibling_path]
        post_resp = session.post(f"{BASE_URL}{post_path}", json=body, timeout=args.timeout)
        verdict = _classify(post_resp, sibling_resp)
        print(
            f"{label:<38} {post_resp.status_code:<8} {verdict:<15} "
            f"{_excerpt(post_resp.text)} | {_excerpt(sibling_resp.text)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
