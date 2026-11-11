# Architecture

## Overview

`notion_db_sync` is a small Python library that incrementally mirrors a Notion
database into local Markdown files. It uses the Notion API version `2022-06-28`
because that version supports the stable `POST /v1/databases/{id}/query`
endpoint, which is deprecated in later versions. The library maintains a local
state file (`.notion-sync.json`) to track remote changes and to detect local
edits that would otherwise be overwritten.

## Components

- `src/notion_db_sync/errors.py`: Defines `NotionSyncError` with a typed
  machine-readable code.
- `src/notion_db_sync/ports.py`: Defines `NotionPort` protocol and the
  `HttpNotionPort` implementation. The HTTP port takes an injectable `send`
  callable for testability and enforces response size limits.
- `src/notion_db_sync/transform.py`: Converts Notion page objects into plain
  Python records and renders Markdown with YAML front matter. It also
  provides filename slugification.
- `src/notion_db_sync/sync.py`: Orchestrates the sync process, pagination,
  state management, conflict detection, deletion mirroring, and event
  callbacks.

## Data Flow

1. `sync` loads or initialises the state file, validating version and database
   ID.
2. It paginates through `port.query_database`, enforcing `max_pages` and
   `max_records`.
3. For each page, `sync` extracts a record and skipped property names, computes
   the target filename, and compares remote `last_edited_time` with the state
   entry and the local file's SHA-256 hash.
4. Based on the decision algorithm, it creates, updates, reports a conflict, or
   leaves the file unchanged. Pages marked `in_trash` or `archived` are treated
   as deletions. Pages missing from the query results are also deleted, but only
   if their local file matches the state hash.
5. The state file is written atomically at the end.

## Security Considerations

- The Notion token is never logged, stored in state, or included in error
  messages or events.
- File writes are constrained to the target directory via path validation.
- Response bodies are capped by `max_response_bytes`.
- The state file is written atomically to avoid corruption.

## Design Decisions

- **Pin Notion API version 2022-06-28**: Keeps the stable database query
  endpoint. Newer versions deprecated it in favour of data source queries, and
  the newest version also changed `archived` to `in_trash`.
- **State file as single source of truth**: Stores `last_edited_time` and file
  SHA-256 to distinguish untouched, locally edited, and remotely changed files.
- **No runtime dependencies**: All functionality uses the Python standard
  library to keep the package lightweight and easy to vendor.
