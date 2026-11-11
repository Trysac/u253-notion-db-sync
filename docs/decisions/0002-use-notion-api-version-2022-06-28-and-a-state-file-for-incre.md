# Use Notion API version 2022-06-28 and a state file for incremental sync

Status: accepted (generated, pending human review)

## Context

The Notion API's default database query endpoint changed in later API versions; version 2025-09-03 deprecated POST /v1/databases/{id}/query in favour of data source queries, and the newest version also replaced archived with in_trash. Notion states it has no current plans to stop supporting older versions, but database calls fail on 2022-06-28 once a database has a second data source, which surfaces as an HTTP error. The library needs a stable endpoint for the requested functionality and a way to track remote changes without overwriting local edits.

## Decision

Pin the Notion-Version header to '2022-06-28' by default and use POST /v1/databases/{database_id}/query. Maintain a local state file (`.notion-sync.json`) that records the last seen `last_edited_time` and SHA-256 hash of each page's rendered Markdown file. On each sync, compare remote metadata with the state to decide between create, update, unchanged, conflict, or delete. The state file is written atomically and validated for version and database ID.

## Consequences

The library remains compatible with older API versions and avoids the deprecation issues of newer releases. It provides conflict detection for locally edited files and supports incremental updates. If a database gains a second data source, the library will raise an 'http_error' as documented; users may override `notion_version` to a newer API version, though the query endpoint would then change and the current code would need adaptation.
