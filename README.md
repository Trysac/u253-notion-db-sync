# trysac-notion-db-sync

Pull a Notion database into local Markdown files with front matter.

`notion_db_sync` mirrors a Notion database into one Markdown file per page. It is incremental: a page is rewritten only when its `last_edited_time` changes and the local file still matches the SHA-256 recorded in `.notion-sync.json`. Local edits are not overwritten; when a remote change and a local edit collide, `sync` reports a conflict. Pages removed from query results or returned with `in_trash`/`archived` delete their untouched local files. File names and front matter are deterministic.

## Features

- Pure Python standard library; no runtime dependencies.
- Calls Notion API version `2022-06-28` against `POST /v1/databases/{id}/query`.
- Pagination with `max_pages` (default 1000) and `max_records` (default 10_000).
- State file `.notion-sync.json`: `{"version": 1, "database_id": ..., "pages": {id: {"file", "last_edited_time", "sha256"}}}`, written atomically.
- Typed errors via `NotionSyncError.code`.
- Supports `title`, `rich_text`, `number`, `select`, `status`, `multi_select`, `date`, `checkbox`, `url`, `email`, `phone_number`; other property types are skipped and reported once in `SyncReport.skipped_properties`.
- File name: slugified title (lowercase, non-`[a-z0-9]` runs to `-`, trimmed, 60 characters, `untitled` if empty) + `-` + first 8 hex characters of the page ID without dashes + `.md`; names never contain path separators, and every write is checked to stay inside the target directory.
- Front matter: `---`, `id`, `last_edited_time`, remaining supported properties sorted by name (body property excluded) as `key: json.dumps(value, ensure_ascii=False)`, `---`, then body text plus `\n` when `body_property` is set.

## Installation

```bash
pip install trysac-notion-db-sync
```

## Usage

```python
from pathlib import Path
from urllib.request import Request, urlopen
from notion_db_sync import HttpNotionPort, sync


def send(url, method, headers, body):
    with urlopen(Request(url, data=body, headers=headers, method=method)) as r:
        return r.status, r.read()


port = HttpNotionPort("secret_token", send=send)
report = sync(port, "database_id", Path("pages"), title_property="Name", body_property="Notes")
```

The `on_event` callback receives `{"event": "created" | "updated" | "deleted" | "conflict", "page_id": ..., "file": ...}`; it never receives property values or the token.

## Public API

- `NotionPort` Protocol: `query_database(database_id: str, start_cursor: str | None) -> Mapping[str, object]`, returning the raw JSON object from `POST /v1/databases/{id}/query` with keys `results`, `has_more`, `next_cursor`.
- `HttpNotionPort(token: str, *, send: Callable[[str, str, Mapping[str, str], bytes], tuple[int, bytes]], notion_version: str = "2022-06-28", max_response_bytes: int = 10_485_760)`. Sends `Authorization: Bearer <token>`, `Notion-Version`, and `Content-Type: application/json`; the body is `json.dumps({"page_size": 100})` plus `start_cursor` when given. Raises `unauthorized` on 401, `rate_limited` on 429, `http_error` on `status >= 400`, `response_too_large` when the body exceeds `max_response_bytes`, and `invalid_response` for invalid JSON or a non-mapping response.
- `page_to_record(page) -> dict[str, object]`: keys sorted alphabetically; unsupported property types are omitted; raises `ValueError` if `properties` is not a mapping.
- `render_markdown(page, *, title_property: str, body_property: str | None = None) -> str`.
- `sync(port, database_id, directory, *, title_property, body_property=None, max_pages=1000, max_records=10_000, on_event=None) -> SyncReport`.
- `SyncReport(created, updated, unchanged, deleted, conflicts, skipped_properties=())` frozen dataclass.
- `NotionSyncError(code, message="")` with codes `'unauthorized'`, `'rate_limited'`, `'http_error'`, `'response_too_large'`, `'invalid_response'`, `'too_many_pages'`, `'too_many_records'`, `'invalid_state'`.

Limits: `sync` raises `too_many_pages` when more than `max_pages` queries are needed and `too_many_records` when more than `max_records` pages are returned. On API version `2022-06-28`, a database with a second data source fails as `http_error`.

## Why not official export

The Notion export is manual and full. This library is incremental, scriptable, conflict-safe, and Git friendly: it updates only changed pages and reports local edits instead of overwriting them.

## Documentation

- Security threat model: [`docs/SECURITY.md`](docs/SECURITY.md)
- Project record: [`docs/PROJECT.md`](docs/PROJECT.md)
- Testing: [`docs/TESTING.md`](docs/TESTING.md)
