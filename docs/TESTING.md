# Testing

The test module is `tests/test_notion_db_sync.py`. It uses `pytest` and a local `FakePort` plus `make_pager` helper; no network or real Notion account is required.

It contains acceptance tests:

- `test_page_to_record_acceptance`: `page_to_record` on the Launch plan page returns sorted keys and values.
- `test_render_markdown_acceptance`: `render_markdown(..., title_property="Name", body_property="Notes")` returns the exact front matter and body string.
- `test_file_name_slug_acceptance`: `file_name_for_page` returns `launch-plan-1a2b3c4d.md`.
- `test_first_and_second_sync`: first sync creates two files and `.notion-sync.json`; an immediate second sync returns `unchanged=2`.

The same module also exercises remote updates, conflicts when the local file changed, deletion for missing, trashed, or archived pages, pagination cursors and `max_pages`/`max_records` errors, and `HttpNotionPort` request shape and error codes (`unauthorized`, `rate_limited`, `response_too_large`). It asserts that no error or event contains the token `secret_x`.

Run:

```bash
pytest
```
