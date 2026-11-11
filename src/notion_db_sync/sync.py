"""Incremental synchronization of a Notion database into Markdown files."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import NotionSyncError
from .ports import NotionPort
from .transform import (
    _page_to_record_with_skipped,
    file_name_for_page,
    render_markdown,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


@dataclass(frozen=True)
class SyncReport:
    """Summary of one sync run."""

    created: int
    updated: int
    unchanged: int
    deleted: int
    conflicts: tuple[str, ...]
    skipped_properties: tuple[str, ...] = ()


EventCallback = Callable[[dict[str, object]], None]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Write JSON atomically via a temporary file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".notion-sync-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(data), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise


def _load_state(directory: Path, database_id: str) -> tuple[dict[str, Any], Path]:
    """Load and validate state; returns (state_dict, state_path)."""
    state_path = directory / ".notion-sync.json"
    if not state_path.exists():
        return {"version": 1, "database_id": database_id, "pages": {}}, state_path

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise NotionSyncError("invalid_state") from None

    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or data.get("database_id") != database_id
    ):
        raise NotionSyncError("invalid_state")

    pages = data.get("pages", {})
    if not isinstance(pages, dict):
        raise NotionSyncError("invalid_state")
    return data, state_path


def _save_state(state_path: Path, state: Mapping[str, Any]) -> None:
    _atomic_write_json(state_path, state)


def _validate_path_inside(directory: Path, file_path: Path) -> None:
    """Ensure file_path stays inside directory to prevent traversal."""
    try:
        relative = file_path.relative_to(directory)
    except ValueError:
        raise NotionSyncError("invalid_state") from None
    if relative.is_absolute() or ".." in relative.parts:
        raise NotionSyncError("invalid_state")
    # Reject Windows-style separators/drive prefixes even on POSIX systems.
    if any("\\" in part for part in relative.parts):
        raise NotionSyncError("invalid_state")
    try:
        directory_resolved = directory.resolve()
        file_resolved = file_path.resolve()
        common = os.path.commonpath([str(directory_resolved), str(file_resolved)])
        if common != str(directory_resolved):
            raise NotionSyncError("invalid_state")
    except ValueError:
        raise NotionSyncError("invalid_state") from None


def _handle_deletion(
    page_id: str,
    state_entry: Mapping[str, Any],
    state: dict[str, Any],
    directory: Path,
    report: dict[str, Any],
    on_event: EventCallback | None,
) -> None:
    """Process a page that should be deleted (missing or trashed)."""
    filename = state_entry.get("file")
    if not isinstance(filename, str):
        # Malformed state entry: ignore and remove.
        state["pages"].pop(page_id, None)
        return

    file_path = directory / filename
    _validate_path_inside(directory, file_path)
    expected_sha = state_entry.get("sha256")

    if file_path.exists():
        actual_sha = _sha256_bytes(file_path.read_bytes())
        if expected_sha == actual_sha:
            file_path.unlink()
            report["deleted"] += 1
            if on_event:
                on_event({"event": "deleted", "page_id": page_id, "file": filename})
            state["pages"].pop(page_id, None)
        else:
            report["conflicts"].append(filename)
            if on_event:
                on_event({"event": "conflict", "page_id": page_id, "file": filename})
            # Keep state entry so the conflict is reported again next run.
    else:
        state["pages"].pop(page_id, None)


def _process_page(
    page: Mapping[str, Any],
    directory: Path,
    title_property: str,
    body_property: str | None,
    state: dict[str, Any],
    report: dict[str, Any],
    on_event: EventCallback | None,
) -> None:
    """Handle one page from the query results."""
    page_id = str(page.get("id", ""))
    if not page_id:
        raise NotionSyncError("invalid_response")

    # Check for trashed/archived deletion
    in_trash = bool(page.get("in_trash", False))
    archived = bool(page.get("archived", False))
    if in_trash or archived:
        state_entry = state["pages"].get(page_id)
        if state_entry:
            _handle_deletion(page_id, state_entry, state, directory, report, on_event)
        return

    _record, skipped = _page_to_record_with_skipped(page)
    for prop in skipped:
        report["skipped_properties"].add(prop)

    filename = file_name_for_page(page, title_property)
    _validate_path_inside(directory, directory / filename)
    last_edited_time = str(page.get("last_edited_time", ""))

    state_entry = state["pages"].get(page_id)

    if state_entry is None:
        # No previous record -> create
        content = render_markdown(page, title_property=title_property, body_property=body_property)
        file_path = directory / filename
        with open(file_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        sha = _sha256_bytes(content.encode("utf-8"))
        state["pages"][page_id] = {
            "file": filename,
            "last_edited_time": last_edited_time,
            "sha256": sha,
        }
        report["created"] += 1
        if on_event:
            on_event({"event": "created", "page_id": page_id, "file": filename})
        return

    # Existing state entry
    old_file = state_entry.get("file")
    old_last_edited = state_entry.get("last_edited_time")
    old_sha = state_entry.get("sha256")
    if (
        not isinstance(old_file, str)
        or not isinstance(old_last_edited, str)
        or not isinstance(old_sha, str)
    ):
        raise NotionSyncError("invalid_state")

    local_path = directory / old_file
    _validate_path_inside(directory, local_path)

    remote_changed = old_last_edited != last_edited_time
    local_exists = local_path.exists()
    local_sha = _sha256_bytes(local_path.read_bytes()) if local_exists else None
    local_matches = (local_sha == old_sha) if local_exists else False

    if local_matches and not remote_changed:
        # Unchanged
        report["unchanged"] += 1
        return

    if local_matches and remote_changed:
        # Remote changed, local untouched -> update (may rename)
        new_content = render_markdown(
            page, title_property=title_property, body_property=body_property
        )
        new_sha = _sha256_bytes(new_content.encode("utf-8"))
        new_file = filename

        if new_file != old_file and local_exists:
            local_path.unlink()

        new_path = directory / new_file
        with open(new_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)

        state["pages"][page_id] = {
            "file": new_file,
            "last_edited_time": last_edited_time,
            "sha256": new_sha,
        }
        report["updated"] += 1
        if on_event:
            on_event({"event": "updated", "page_id": page_id, "file": new_file})
        return

    # Local file differs from state (edited or missing)
    if remote_changed:
        # Conflict
        report["conflicts"].append(old_file)
        if on_event:
            on_event({"event": "conflict", "page_id": page_id, "file": old_file})
    else:
        # Remote unchanged, local edit is unrelated -> leave as is, count unchanged
        report["unchanged"] += 1


def sync(
    port: NotionPort,
    database_id: str,
    directory: Path,
    *,
    title_property: str,
    body_property: str | None = None,
    max_pages: int = 1000,
    max_records: int = 10_000,
    on_event: EventCallback | None = None,
) -> SyncReport:
    """Synchronize a Notion database into local Markdown files.

    Args:
        port: Object implementing ``query_database``.
        database_id: Notion database ID.
        directory: Local directory to write files and state into (created if needed).
        title_property: Name of the property used as the page title.
        body_property: Optional name of the property whose text becomes the Markdown body.
        max_pages: Maximum number of API queries (default 1000).
        max_records: Maximum number of pages across all queries (default 10_000).
        on_event: Optional callback receiving ``{'event', 'page_id', 'file'}``.

    Returns:
        SyncReport with counts of actions and conflict filenames.

    Raises:
        NotionSyncError: with codes 'too_many_pages', 'too_many_records',
            'invalid_state', 'invalid_response', etc.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    state, state_path = _load_state(directory, database_id)

    report: dict[str, Any] = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
        "conflicts": [],
        "skipped_properties": set(),
    }

    query_count = 0
    accumulated_pages: list[Mapping[str, Any]] = []
    start_cursor: str | None = None

    while True:
        query_count += 1
        if query_count > max_pages:
            raise NotionSyncError("too_many_pages")

        resp = port.query_database(database_id, start_cursor)
        if not isinstance(resp, Mapping):
            raise NotionSyncError("invalid_response")

        results = resp.get("results")
        has_more = resp.get("has_more")
        next_cursor = resp.get("next_cursor")
        if not isinstance(results, list) or not isinstance(has_more, bool):
            raise NotionSyncError("invalid_response")

        accumulated_pages.extend(results)
        if len(accumulated_pages) > max_records:
            raise NotionSyncError("too_many_records")

        if has_more and isinstance(next_cursor, str):
            start_cursor = next_cursor
        elif has_more:
            raise NotionSyncError("invalid_response")
        else:
            break

    seen_ids: set[str] = set()
    for page in accumulated_pages:
        if not isinstance(page, Mapping):
            raise NotionSyncError("invalid_response")
        page_id = str(page.get("id", ""))
        if page_id:
            seen_ids.add(page_id)
            _process_page(page, directory, title_property, body_property, state, report, on_event)

    # Handle deletions for pages not present in the latest query results
    for page_id in list(state["pages"].keys()):
        if page_id not in seen_ids:
            state_entry = state["pages"][page_id]
            _handle_deletion(page_id, state_entry, state, directory, report, on_event)

    _save_state(state_path, state)

    skipped_tuple = tuple(sorted(report["skipped_properties"]))
    return SyncReport(
        created=report["created"],
        updated=report["updated"],
        unchanged=report["unchanged"],
        deleted=report["deleted"],
        conflicts=tuple(report["conflicts"]),
        skipped_properties=skipped_tuple,
    )
