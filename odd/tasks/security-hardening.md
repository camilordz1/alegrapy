# Security hardening

## Objective
Make the AlegraPy client secure by default: no hanging requests, no path injection,
no credentials over plain HTTP, no silent credential mixing, no response bodies in logs.

## Problem
A read-only audit (2026-10-17) found no leaked secrets in git history or `dist/`, but
found runtime risks in `alegra/session.py` and `alegra/actions.py`.

## Why
This is a library consumed by other applications; callers may pass end-user input
(ids, config) straight through, so the library must validate at its boundary.

## Scope
- In: `alegra/session.py`, `alegra/actions.py`, resource modules using `/{id}` URLs,
  `tests/test_alegra.py`, `README.md`.
- Out: version bump in `setup.py` (pre-existing uncommitted change, not part of this work),
  `.atl/`, publishing to PyPI.

## Constraints
- Keep the legacy `session` API working (backwards compatibility).
- TDD: strict, enabled (source: session/orchestrator config). Runner:
  `env/bin/python -m unittest discover -s tests`.
- RDD: on (decided by global). Review boundary starts at branch point `b0d6eec`.
- Delivery strategy: `ask-on-risk`. Forecast ~300 authored changed lines (single PR expected).

## Decisions (defaults chosen)
- Timeout: default 30s, configurable via `AlegraClient(timeout=...)` and `session.timeout`.
- Ids: accept non-bool `int` or `str` matching `^[A-Za-z0-9_-]+$`; otherwise `ValueError`.
- Base URL: must be `https://`; `http://` allowed only for loopback hosts (local testing).
- Credentials: resolved as a pair; the client falls back to global `session` credentials
  only when it has neither `user` nor `token` of its own.
- Headers: built per request; the shared `requests.Session` headers are never mutated.
- Logging: log method, path and status code only; never response bodies or exception text
  that may carry query data. `AlegraAPIError.response_body` is still kept for callers.

## Tasks
- [x] T1 — Default request timeout (route: delegated writer; trigger: preparation + tests)
- [x] T2 — Validate resource ids before building URLs (route: delegated writer; trigger: 2+ non-trivial files)
- [x] T2b — Accept `numbers.Integral` ids and centralize URL building (reopened from T2 review: R3/R4 WARNING int-like regression, R2 WARNING duplicated builder; route: delegated writer with T3)
- [x] T3 — Enforce HTTPS base URL (route: delegated writer; trigger: preparation + tests)
- [x] T4 — Pairwise credential resolution and per-request headers (route: delegated writer; trigger: preparation + tests)
- [x] T5 — Stop logging response bodies / exception text (route: delegated writer; trigger: preparation + tests)
- [x] T6 — Document the new security behavior in README (route: inline or with T5)

## Acceptance criteria
- Each task has a RED test observed before the fix, then GREEN.
- Full suite green: `env/bin/python -m unittest discover -s tests`.
- Legacy `session.user/token` usage still works.

## Progress / evidence
| Task | Commit | Tests | Review tier / outcome |
|------|--------|-------|------------------------|
| T1 | 8fd5165 | RED: 3 errors (no `timeout` kwarg/param); GREEN: 16 tests OK | high; granted; approved + acknowledged (lineage review-3bb45dcdd52fe328) |
| T2 | f818ae0 | RED: 21 ran, 1 failure + 18 errors (invalid ids reached the mocked request); GREEN: 21 tests OK | high; granted; approved + acknowledged (lineage review-f888d8c17b28c6f1); range 8fd5165..52c21d3 |
| T2b | 2b1331f | RED: 23 ran, 1 error (`test_int_like_ids_are_accepted` against committed source); GREEN: 23 tests OK | high; granted; approved + acknowledged (lineage review-82b9d2aa52a06b2a) |
| T3 | 0b398c7 | RED: 28 ran, 11 failures (insecure/malformed urls accepted by constructor, setter and legacy query); GREEN: 28 tests OK | high; granted; approved + acknowledged (lineage review-7523605932838e4e) |
| T4 | 32312f4 | RED: 36 ran, 3 failures (own user used with global token, own token with global user, Authorization stored on shared session headers); GREEN: 36 tests OK | high; granted; approved + acknowledged as one slice 0b398c7..5d5b583 (lineage review-c52fc725d50363d6) |
| T5 | dbd3a85 | RED: 43 ran, 8 failures (API message/body and exception text logged, query string logged, userinfo accepted, URL echoed in errors, constructor bypassed url setter); GREEN: 43 tests OK | high; granted; approved + acknowledged as one slice 0b398c7..5d5b583 (lineage review-c52fc725d50363d6) |
| T6 | 5d5b583 | docs only; GREEN: 43 tests OK | high; granted; approved + acknowledged as one slice 0b398c7..5d5b583 (lineage review-c52fc725d50363d6) |

### Follow-ups from T1 review (non-blocking)
- R4 WARNING: a timeout on non-idempotent POSTs (invoices, payments) is ambiguous; the record may
  be created server-side while the client raises. Document "do not blindly retry POSTs" in README (T6).
- R3/R2 suggestions: validate `timeout` (positive number), clarify that `timeout=None` means
  "use global default", and test the `timeout` setter.

### Follow-ups from T2 review (non-blocking, accepted into T2b)
- R3/R4 WARNING: `validate_id` rejects int-like types (`numpy.int64`, etc.) that worked before; accept `numbers.Integral` (non-bool, >= 0).
- R2 WARNING: 14 copies of the URL f-string; add one helper that validates and builds the resource URL.
- R2/R3 SUGGESTION: `test_valid_ids_are_accepted` must assert every URL, including id `0` and `"123"`.

### T2b interruption note
- The delegated writer was interrupted when the app closed; it left `_resource_url` calling itself
  (unbounded recursion that exhausted memory and killed the test process, exit 137).
- Parent finished T2b inline: split `_collection_url()` (list/create) from `_resource_url(id, *suffix)`
  (always validates), so `read(None)` is still rejected instead of hitting the collection URL.

### Follow-ups from T2b review (non-blocking)
- R2/R3 SUGGESTION: `_IntLike` is registered on `numbers.Integral` at import (process-wide); consider a real `numbers.Integral` subclass.

### Follow-ups from T3 review (accepted into T5 where noted)
- R1/R2 WARNING (-> T5): `_validate_base_url` errors echo the full URL; a URL with `user:password@` userinfo
  would leak secrets into exceptions/logs. Reject userinfo in base URLs and never echo the raw URL.
- R2 SUGGESTION (-> T5): build the loopback-host message from `_LOOPBACK_HOSTS`; constructor should assign via
  the `url` setter instead of duplicating its logic.
- R3 SUGGESTION: loopback test should also send a request; ensure tests never leak a bad `session.url`.

### Follow-ups from T4-T6 review (non-blocking)
- R1 SUGGESTION: `requests` merges `session.headers` back in `prepare_request`, so dropping `Authorization`
  from the per-request dict does not remove a caller-set session-level `Authorization`; set it to `None`
  in the per-request headers when there are no credentials.
- R2/R3 SUGGESTION: `_log_path` strips the base with a bare `startswith` (no path-segment boundary).
- R2/R3 SUGGESTION: `test_constructor_validates_through_url_setter` uses `unittest.mock.PropertyMock` via
  attribute chain and tests implementation rather than behavior.

Reviewed boundary: `5d5b583`.

## Next step
All tasks done and reviewed. Push / PR are the user's decision. Optional: address non-blocking follow-ups.
