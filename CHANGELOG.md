# Changelog

All notable changes to **AlegraPy** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning

- **While on `0.y.z`**: a `MINOR` bump (`0.1` -> `0.2`) **may** include breaking changes (always listed under **Breaking changes**); a `PATCH` bump (`0.1.0` -> `0.1.1`) contains fixes only.
- **From `1.0.0` onward**: breaking changes appear only in `MAJOR` releases; deprecations are announced at least one `MINOR` release before removal with a warning.
- **Planned for `1.0.0`**: remove the `alegra` compatibility shim and the legacy global `session`, and rename the `"alegra"` logger.
- **Pinning recommendation**: pin `AlegraPy>=0.2,<0.3` until `1.0.0`.

## [Unreleased]

## [0.2.0] - 2026-11-21

Compared against `0.1.0`.

### Breaking changes

- **Legacy global API emits `FutureWarning`**: code that still uses the global `session`, `default_client`, or resources without an explicit `AlegraClient` now warns once per feature. Test suites that run with `-W error` (or `filterwarnings = error`) will fail until they migrate to `AlegraClient` or filter the warnings (see the legacy migration guide).
- **`session.create_auth()` is a no-op**: it no longer writes an `Authorization` header into `session.headers`. Requests were already authenticated per request, so only code that read `session.headers["Authorization"]` directly is affected.

### Added

- **Duplicate-safe payment creation**: `payments.create_once()` and `payments.reconcile()` reusing the `observations` dedup-marker flow (with optional `client` and `type` filtering).
- **Electronic stamping (DIAN emission) API**: `invoices.stamp(ids)`, `invoices.stamp_status(id)`, and `invoices.wait_until_stamped(id, timeout=60.0, interval=2.0)`, along with typed `StampState`, `StampStatus`, `StampResult`, and `AlegraStampTimeoutError`.

### Deprecated

- **Legacy global `session` and `default_client`** (emits a once-per-process `FutureWarning`, planned for removal in `1.0.0`):
  - Assigning attributes on `session` (`session.user = ...`, `session.token = ...`, `session.url = ...`, `session.timeout = ...`, `session.retry = ...`, etc.).
  - Calling `session.query()` or `session.create_auth()`.
  - Accessing `alegrapy.session.default_client`.
  - Instantiating resources without an explicit `AlegraClient` (e.g. `invoices()`, `Contacts()`).
  - Sending requests with an `AlegraClient` that falls back to `session.user`/`session.token` or non-default `session.url`/`session.timeout`/`session.retry`.

### Security

- `session.create_auth()` no longer encodes or stores an `Authorization` header in the global `session.headers` dictionary (and removes any stale `Authorization` key defensively).

## [0.1.0] - 2026-11-20

Compared against the previous PyPI release (`0.0.4`).

### Breaking changes

Read this section first when upgrading from `0.0.4`:

- **Import name changed to `alegrapy`**: replace `import alegra` with `import alegrapy`. The old `alegra` package name remains as a compatibility shim that emits a `FutureWarning` and will be removed in `1.0.0`.
- **Python 3.10+ required**: `requires-python` is now `>=3.10` (dropped Python `<3.10`).
- **Updated runtime dependency**: requires `requests>=2.32,<3` (older `requests` versions have known CVEs).
- **Errors now raise typed exceptions**: non-2xx responses and transport failures raise typed `AlegraAPIError` subclasses instead of logging and returning `None` from the legacy `session.query`. Catch `AlegraAPIError` (or a specific subclass) instead of checking for `None`.
- **Legacy `actions.delete` sends a real `DELETE`**: previously `actions.delete` sent a `GET` request (no effect); it now sends an HTTP `DELETE`. Audit any existing calls to `delete()` before upgrading.
- **No automatic `alegra.log` file**: the library no longer calls `logging.basicConfig` or writes `alegra.log`. It logs to the named logger `"alegra"` with no handler attached; configure logging in your application. The logger name remains `"alegra"` through `0.1.x`.
- **Retries enabled by default**: `AlegraClient` defaults to `RetryPolicy()` (`max_retries=2` for transient failures). Disable retries with `RetryPolicy(max_retries=0)`. `POST` requests are retried only when `request_not_sent` is `True` (or on `429` when included in `retry_statuses`).
- **HTTPS and input validation enforced**: base URLs must use `https` (`http` is allowed only for loopback hosts `localhost`, `127.0.0.1`, `::1`); resource IDs are validated before building URLs; explicit `AlegraClient` credentials are never mixed with the global `session`.
- **`invoices.void(id, cause=None)`**: gains an optional `cause` parameter. For electronic invoices, use `invoices.annul()` instead.

### Added

- **Per-tenant `AlegraClient`**: thread-safe client for multi-tenant applications with a documented thread-safety contract, `close()`, and context-manager support (`with AlegraClient(...) as client:`).
- **Typed exception hierarchy**: `AlegraAuthError`, `AlegraNotFoundError`, `AlegraValidationError`, `AlegraRateLimitError`, `AlegraServerError`, `AlegraConnectionError`, `AlegraTimeoutError`, `AlegraFileNotAvailableError`, `AlegraStampError`, `AlegraAlreadyAnnulledError`, and `AlegraUnverifiedCreateError` (all subclassing `AlegraAPIError`), plus `AlegraAPIError.request_not_sent` and `AlegraUnverifiedCreateError.to_dict()`.
- **Configurable retries**: `RetryPolicy` with exponential backoff, jitter, and `Retry-After` / `X-Rate-Limit-Reset` header handling.
- **Lazy pagination**: `iter_all(max_items=None, page_size=30, **filters)` across resources.
- **Exact search helpers**: `contacts.find_by_identification()` and `items.find_by_reference()`.
- **Duplicate-safe invoice creation**: `invoices.create_once()`, `invoices.reconcile()`, `make_dedup_key()`, and `make_dedup_key_from()`.
- **Invoice PDF and XML downloads**: `invoices.get_pdf()`, `invoices.get_xml()`, `invoices.download_pdf()`, and `invoices.download_xml()`.
- **Credit notes and electronic invoice annulment**: `client.credit_notes` (`CreditNotes`, `reconcile()`), `CreditNoteType`, `CreditNoteOperationType`, and `invoices.annul()`.
- **Packaging and documentation**: PEP 561 `py.typed` marker and MkDocs documentation site.

### Security

- Enforce HTTPS-only base URLs (allowing plain `http` only for loopback hosts) and reject URLs containing embedded credentials.
- Validate resource IDs before constructing request URLs to prevent path traversal and injection.
- Never log request/response bodies, `Authorization` headers, tokens, or signed URL query parameters.
- Never send Alegra credentials to CDN or S3 file hosts when downloading invoice PDFs/XMLs; validate every redirect hop manually (`https` required) and write downloads without clobbering existing files when `overwrite=False`.
- Reject all cookies on each client's HTTP session (`DefaultCookiePolicy`), so no server-set state is shared between requests or threads using the same client (each `AlegraClient` already has its own session).
