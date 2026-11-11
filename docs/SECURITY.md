# Security

## Threat Model

`notion_db_sync` processes page metadata and property values from the Notion API and writes Markdown files and a state file into a local directory. The defense boundary is the target directory; the threat model assumes the caller supplies a trusted `send` callable and token.

### Defended

- Path traversal: every page-file write and deletion path goes through `_validate_path_inside(directory, file_path)`; it rejects `relative_to` failure, absolute relative paths, `..`, backslash in any relative part, and a resolved common path outside the directory, raising `NotionSyncError("invalid_state")`.
- Token exposure: the token is only used in `Authorization: Bearer <token>`; it is not stored in state, included in library error messages, or passed to `on_event` payloads. `on_event` fields are `event`, `page_id`, and `file`.
- Oversized responses: `HttpNotionPort` checks `len(response_body) > max_response_bytes` (default 10_485_760) before JSON parsing and raises `NotionSyncError("response_too_large")`.
- HTTP failures: 401 raises `unauthorized`, 429 raises `rate_limited`, `status >= 400` raises `http_error`; invalid JSON or a non-mapping response raises `invalid_response`.
- Pagination bounds: `sync` raises `too_many_pages` before querying more than `max_pages` (default 1000) and `too_many_records` when accumulated pages exceed `max_records` (default 10_000).
- State validation: `.notion-sync.json` must be a dict with `version == 1`, a matching `database_id`, and `pages` as a dict; otherwise `invalid_state` is raised. Malformed per-page entries raise `invalid_state` during processing.
- Atomic state writes: the state file is written through `tempfile.mkstemp` in the target directory, JSON-dumped with UTF-8 and fsync, then `os.replace`; the temporary file is removed on exception.

### Not defended

- No retry or backoff: HTTP 429 is surfaced as `rate_limited`; the caller must retry.
- No transport implementation: `HttpNotionPort` requires an injected `send`; TLS, redirects, and network timeouts are the caller's responsibility.
- No encryption at rest and no file locking; local users with write access to the directory can read or modify Markdown files and `.notion-sync.json`.
- Page files are written with `open(..., "w")` after path validation, not via atomic replace; a concurrent local process or symlink race is not prevented.
- Markdown body and front matter values are rendered as data and are not sanitised for downstream Markdown or HTML consumers.
- The library does not push local edits, does not fetch page block content, and does not handle attachments.

## Mitigations

The controls listed under Defended are implemented in `src/notion_db_sync/ports.py`, `src/notion_db_sync/sync.py`, and `src/notion_db_sync/errors.py`.

## Reporting a Vulnerability

Please report security issues privately to the repository maintainers.
