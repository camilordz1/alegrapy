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
- [ ] T2 — Validate resource ids before building URLs (route: delegated writer; trigger: 2+ non-trivial files)
- [ ] T3 — Enforce HTTPS base URL (route: delegated writer; trigger: preparation + tests)
- [ ] T4 — Pairwise credential resolution and per-request headers (route: delegated writer; trigger: preparation + tests)
- [ ] T5 — Stop logging response bodies / exception text (route: delegated writer; trigger: preparation + tests)
- [ ] T6 — Document the new security behavior in README (route: inline or with T5)

## Acceptance criteria
- Each task has a RED test observed before the fix, then GREEN.
- Full suite green: `env/bin/python -m unittest discover -s tests`.
- Legacy `session.user/token` usage still works.

## Progress / evidence
| Task | Commit | Tests | Review tier / outcome |
|------|--------|-------|------------------------|
| T1 | 41de750 | RED: 3 errors (no `timeout` kwarg/param); GREEN: 16 tests OK | pending assessment |

## Next step
T2.
