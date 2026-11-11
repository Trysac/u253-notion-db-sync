# Project record

## Objective

Pull a Notion database into local Markdown files with front matter: incremental by last edit time, deletions mirrored and local edits detected as conflicts, never overwritten.

## Scope

In scope: the public API `NotionPort`, `HttpNotionPort`, `page_to_record`, `render_markdown`, `sync`, `SyncReport`, and `NotionSyncError`; incremental mirroring of a Notion database into one Markdown file per page; state tracking in `.notion-sync.json`; conflict detection; deletion mirroring for missing, trashed, or archived pages; pagination limits; typed errors. The implementation uses only the Python standard library and has no runtime dependencies.

Out of scope: pushing local edits to Notion, page block content, attachments, and retries. A caller retries on `rate_limited`.

## Timeline

No dated milestones are recorded in the specification.

## Effort metrics

The specification records no measured effort values.

| Metric | Value |
|---|---|
| Tokens (input / output) | 1428555 / 87438 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.1212 |

## Factory run u253 (measured from API usage)

| Date (UTC) | Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| 2026-11-11 | generation | deepseek-v4-pro | yes | 5604 | 26604 | 0 | 0 | 0.0564 |
| 2026-11-11 | fix-1 | deepseek-flash | no | 22165 | 22637 | 0 | 522496 | 0.0185 |
| 2026-11-11 | audit | deepseek-flash | no | 39792 | 21852 | 0 | 582272 | 0.0208 |
| 2026-11-11 | fix-2 | deepseek-flash | no | 15516 | 6114 | 0 | 154240 | 0.0065 |
| 2026-11-11 | docs | deepseek-flash | no | 86214 | 10231 | 0 | 256 | 0.0191 |

Total: $0.1212. Prices: deepseek line, as measured by its adapter. Providers serve the current version of each model id, so the date tells which version answered; versions, launch stages and price sources per line are in the factory's model register (docs/MODELS.md).
