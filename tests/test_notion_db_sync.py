"""Tests for the notion_db_sync package."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from notion_db_sync import (
    HttpNotionPort,
    NotionSyncError,
    SyncReport,
    page_to_record,
    render_markdown,
    sync,
)


def make_page(
    page_id: str,
    title: str,
    last_edited: str,
    *,
    body: str = "",
    extra_props: dict[str, Any] | None = None,
    in_trash: bool = False,
    archived: bool = False,
) -> dict[str, Any]:
    props = {
        "Name": {"type": "title", "title": [{"plain_text": title}]},
        "Notes": {"type": "rich_text", "rich_text": [{"plain_text": body}]},
    }
    if extra_props:
        props.update(extra_props)
    page: dict[str, Any] = {
        "id": page_id,
        "last_edited_time": last_edited,
        "properties": props,
    }
    if in_trash:
        page["in_trash"] = True
    if archived:
        page["archived"] = True
    return page


class FakePort:
    def __init__(self, pages: list[dict[str, Any]], *, cursor: str | None = None):
        self.pages = pages
        self.cursor = cursor
        self.queries: list[tuple[str, str | None]] = []

    def query_database(self, database_id: str, start_cursor: str | None):
        self.queries.append((database_id, start_cursor))
        if not self.pages:
            return {"results": [], "has_more": False, "next_cursor": None}
        batch = self.pages[:1]
        self.pages = self.pages[1:]
        has_more = bool(self.pages)
        next_cursor = (self.cursor or "cursor-1") if has_more else None
        return {"results": batch, "has_more": has_more, "next_cursor": next_cursor}


def test_page_to_record_acceptance():
    page = {
        "id": "1a2b3c4d-0000-0000-0000-000000000001",
        "last_edited_time": "2026-11-01T10:00:00.000Z",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Launch plan"}]},
            "Done": {"type": "checkbox", "checkbox": True},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "q4"}, {"name": "web"}]},
            "Notes": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "Ship by "}, {"plain_text": "Friday."}],
            },
        },
    }
    expected = {
        "Done": True,
        "Name": "Launch plan",
        "Notes": "Ship by Friday.",
        "Tags": ["q4", "web"],
    }
    assert page_to_record(page) == expected


def test_render_markdown_acceptance():
    page = make_page(
        "1a2b3c4d-0000-0000-0000-000000000001",
        "Launch plan",
        "2026-11-01T10:00:00.000Z",
        body="Ship by Friday.",
        extra_props={
            "Done": {"type": "checkbox", "checkbox": True},
            "Tags": {
                "type": "multi_select",
                "multi_select": [{"name": "q4"}, {"name": "web"}],
            },
        },
    )
    output = render_markdown(page, title_property="Name", body_property="Notes")
    expected = (
        "---\n"
        'id: "1a2b3c4d-0000-0000-0000-000000000001"\n'
        'last_edited_time: "2026-11-01T10:00:00.000Z"\n'
        "Done: true\n"
        'Name: "Launch plan"\n'
        'Tags: ["q4", "web"]\n'
        "---\n"
        "Ship by Friday.\n"
    )
    assert output == expected


def test_file_name_slug_acceptance():
    page = make_page(
        "1a2b3c4d-0000-0000-0000-000000000001", "Launch plan", "2026-11-01T10:00:00.000Z"
    )
    # file_name_for_page is internal; test via sync or compute manually
    from notion_db_sync.transform import file_name_for_page

    assert file_name_for_page(page, "Name") == "launch-plan-1a2b3c4d.md"


def test_first_and_second_sync(tmp_path: Path):
    pages = [
        make_page("id1", "Page One", "2026-11-01T00:00:00.000Z", body="Content 1"),
        make_page("id2", "Page Two", "2026-11-01T00:00:00.000Z", body="Content 2"),
    ]
    port = FakePort(pages[:])
    report = sync(port, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report == SyncReport(
        created=2, updated=0, unchanged=0, deleted=0, conflicts=(), skipped_properties=()
    )
    assert (tmp_path / ".notion-sync.json").exists()

    # second sync same data -> unchanged=2
    port2 = FakePort(pages[:])
    report2 = sync(port2, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report2 == SyncReport(
        created=0, updated=0, unchanged=2, deleted=0, conflicts=(), skipped_properties=()
    )


def test_update_remote_changed(tmp_path: Path):
    initial = [make_page("id1", "Title", "2026-11-01T00:00:00.000Z", body="old")]
    port1 = FakePort(initial[:])
    sync(port1, "db1", tmp_path, title_property="Name", body_property="Notes")

    updated_page = make_page("id1", "Title", "2026-11-02T00:00:00.000Z", body="new")
    port2 = FakePort([updated_page])
    report = sync(port2, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report.updated == 1
    assert report.unchanged == 0
    file = tmp_path / "title-id1.md"  # id1 no dashes? id1 is okay
    assert file.exists()
    content = file.read_text(encoding="utf-8")
    assert "old" not in content
    assert "new" in content


def test_conflict_local_edited(tmp_path: Path):
    initial = [make_page("id1", "Title", "2026-11-01T00:00:00.000Z", body="orig")]
    port1 = FakePort(initial[:])
    sync(port1, "db1", tmp_path, title_property="Name", body_property="Notes")

    # Edit local file
    file = tmp_path / "title-id1.md"
    original_content = file.read_text(encoding="utf-8")
    file.write_text(original_content + "\nlocal edit", encoding="utf-8")

    # Remote changes too
    updated_page = make_page("id1", "Title", "2026-11-02T00:00:00.000Z", body="remote change")
    port2 = FakePort([updated_page])
    report = sync(port2, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report.conflicts == ("title-id1.md",)
    assert file.read_text(encoding="utf-8") == original_content + "\nlocal edit"
    # state unchanged
    state = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert state["pages"]["id1"]["last_edited_time"] == "2026-11-01T00:00:00.000Z"
    assert state["pages"]["id1"]["sha256"] == hashlib.sha256(original_content.encode()).hexdigest()

    # The conflict must be reported again on the next run, local bytes kept.
    port3 = FakePort([updated_page])
    report3 = sync(port3, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report3.conflicts == ("title-id1.md",)
    assert file.read_text(encoding="utf-8") == original_content + "\nlocal edit"
    state3 = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert state3["pages"]["id1"]["last_edited_time"] == "2026-11-01T00:00:00.000Z"
    assert state3["pages"]["id1"]["sha256"] == hashlib.sha256(original_content.encode()).hexdigest()


def test_conflict_rereported_spec_page_literal(tmp_path: Path):
    page_id = "1a2b3c4d-0000-0000-0000-000000000001"
    first = [make_page(page_id, "Launch plan", "2026-11-01T10:00:00.000Z", body="Ship by Friday.")]
    sync(FakePort(first[:]), "db1", tmp_path, title_property="Name", body_property="Notes")

    file = tmp_path / "launch-plan-1a2b3c4d.md"
    original_content = file.read_text(encoding="utf-8")
    file.write_text(original_content + "\nlocal edit", encoding="utf-8")

    updated = [make_page(page_id, "Launch plan", "2026-11-02T10:00:00.000Z", body="remote change")]
    report = sync(
        FakePort(updated[:]), "db1", tmp_path, title_property="Name", body_property="Notes"
    )
    assert report.conflicts == ("launch-plan-1a2b3c4d.md",)
    assert file.read_text(encoding="utf-8") == original_content + "\nlocal edit"

    report2 = sync(
        FakePort(updated[:]), "db1", tmp_path, title_property="Name", body_property="Notes"
    )
    assert report2.conflicts == ("launch-plan-1a2b3c4d.md",)
    assert file.read_text(encoding="utf-8") == original_content + "\nlocal edit"


def test_deletion_trashed(tmp_path: Path):
    pages = [make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content")]
    port = FakePort(pages[:])
    sync(port, "db1", tmp_path, title_property="Name", body_property="Notes")

    # Now come back trashed
    trashed = make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content", in_trash=True)
    port2 = FakePort([trashed])
    report = sync(port2, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report.deleted == 1
    assert not (tmp_path / "page-id1.md").exists()
    state = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert "id1" not in state["pages"]


def test_deletion_edited_conflict(tmp_path: Path):
    pages = [make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content")]
    port = FakePort(pages[:])
    sync(port, "db1", tmp_path, title_property="Name", body_property="Notes")

    # edit local
    file = tmp_path / "page-id1.md"
    file.write_text(file.read_text(encoding="utf-8") + "\nedit", encoding="utf-8")

    trashed = make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content", in_trash=True)
    port2 = FakePort([trashed])
    report = sync(port2, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report.deleted == 0
    assert report.conflicts == ("page-id1.md",)
    assert file.exists()
    state = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert "id1" in state["pages"]


def test_deletion_archived(tmp_path: Path):
    pages = [make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content")]
    sync(FakePort(pages[:]), "db1", tmp_path, title_property="Name", body_property="Notes")

    archived = make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content", archived=True)
    report = sync(
        FakePort([archived]), "db1", tmp_path, title_property="Name", body_property="Notes"
    )
    assert report.deleted == 1
    assert not (tmp_path / "page-id1.md").exists()
    state = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert "id1" not in state["pages"]


def test_deletion_archived_edited_conflict(tmp_path: Path):
    pages = [make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content")]
    sync(FakePort(pages[:]), "db1", tmp_path, title_property="Name", body_property="Notes")

    file = tmp_path / "page-id1.md"
    file.write_text(file.read_text(encoding="utf-8") + "\nedit", encoding="utf-8")

    archived = make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content", archived=True)
    report = sync(
        FakePort([archived]), "db1", tmp_path, title_property="Name", body_property="Notes"
    )
    assert report.deleted == 0
    assert report.conflicts == ("page-id1.md",)
    assert file.exists()
    state = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert "id1" in state["pages"]


def test_pagination_cursor(tmp_path: Path):
    pages = [
        make_page("a", "A", "2026-11-01T00:00:00.000Z"),
        make_page("b", "B", "2026-11-01T00:00:00.000Z"),
    ]
    port = FakePort(pages[:], cursor="c2")
    port.pages = pages[:]  # two pages to simulate two batches
    report = sync(port, "db1", tmp_path, title_property="Name", max_pages=10)
    assert report.created == 2
    assert port.queries[0] == ("db1", None)
    assert port.queries[1] == ("db1", "c2")


def test_max_pages_exceeded(tmp_path: Path):
    port = FakePort([make_page("x", "X", "2026-11-01T00:00:00.000Z")], cursor="c")
    port.pages = [make_page("x", "X", "2026-11-01T00:00:00.000Z")] * 3  # has_more always true
    with pytest.raises(NotionSyncError) as exc:
        sync(port, "db1", tmp_path, title_property="Name", max_pages=2)
    assert exc.value.code == "too_many_pages"


def test_max_records_exceeded(tmp_path: Path):
    pages = [make_page(f"id{i}", f"T{i}", "2026-11-01T00:00:00.000Z") for i in range(3)]
    port = FakePort(pages[:])
    with pytest.raises(NotionSyncError) as exc:
        sync(port, "db1", tmp_path, title_property="Name", max_records=2)
    assert exc.value.code == "too_many_records"


def test_http_port_headers_and_body():
    captured: dict[str, Any] = {}

    def fake_send(url, method, headers, body):
        captured["url"] = url
        captured["method"] = method
        captured["headers"] = dict(headers)
        captured["body"] = body
        return 200, b'{"results": []}'

    port = HttpNotionPort("secret_x", send=fake_send)
    port.query_database("db1", None)
    assert captured["url"] == "https://api.notion.com/v1/databases/db1/query"
    assert captured["method"] == "POST"
    assert captured["headers"]["Notion-Version"] == "2022-06-28"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["headers"]["Authorization"] == "Bearer secret_x"
    assert captured["body"] == b'{"page_size": 100}'

    # with start_cursor
    port.query_database("db1", "cursor1")
    assert b"cursor1" in captured["body"]


def test_http_port_unauthorized():
    def fake_send(url, method, headers, body):
        return 401, b'{"message": "unauthorized"}'

    port = HttpNotionPort("secret", send=fake_send)
    with pytest.raises(NotionSyncError) as exc:
        port.query_database("db1", None)
    assert exc.value.code == "unauthorized"
    assert "secret" not in str(exc.value)


def test_http_port_rate_limited():
    def fake_send(url, method, headers, body):
        return 429, b'{"message": "rate limited"}'

    port = HttpNotionPort("secret", send=fake_send)
    with pytest.raises(NotionSyncError) as exc:
        port.query_database("db1", None)
    assert exc.value.code == "rate_limited"


def test_http_port_response_too_large():
    def fake_send(url, method, headers, body):
        return 200, b"x" * (10_485_760 + 1)

    port = HttpNotionPort("secret", send=fake_send)
    with pytest.raises(NotionSyncError) as exc:
        port.query_database("db1", None)
    assert exc.value.code == "response_too_large"


def test_http_port_http_error():
    def fake_send(url, method, headers, body):
        return 500, b"server error"

    port = HttpNotionPort("secret", send=fake_send)
    with pytest.raises(NotionSyncError) as exc:
        port.query_database("db1", None)
    assert exc.value.code == "http_error"


def test_http_port_invalid_json():
    def fake_send(url, method, headers, body):
        return 200, b"not json"

    port = HttpNotionPort("secret", send=fake_send)
    with pytest.raises(NotionSyncError) as exc:
        port.query_database("db1", None)
    assert exc.value.code == "invalid_response"


def test_state_invalid_database_id(tmp_path: Path):
    (tmp_path / ".notion-sync.json").write_text(
        json.dumps({"version": 1, "database_id": "other", "pages": {}}), encoding="utf-8"
    )
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([]), "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_state"


def test_state_invalid_version(tmp_path: Path):
    (tmp_path / ".notion-sync.json").write_text(
        json.dumps({"version": 2, "database_id": "db1", "pages": {}}), encoding="utf-8"
    )
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([]), "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_state"


def test_skipped_properties(tmp_path: Path):
    page = make_page(
        "id1",
        "Title",
        "2026-11-01T00:00:00.000Z",
        extra_props={"Formula": {"type": "formula", "formula": {"type": "string", "string": "x"}}},
    )
    port = FakePort([page])
    report = sync(port, "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report.skipped_properties == ("Formula",)


def test_two_pages_same_slug_distinct_ids(tmp_path: Path):
    pages = [
        make_page("id-aaa", "Same Title", "2026-11-01T00:00:00.000Z"),
        make_page("id-bbb", "Same Title", "2026-11-01T00:00:00.000Z"),
    ]
    port = FakePort(pages[:])
    sync(port, "db1", tmp_path, title_property="Name")
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 2
    names = {f.name for f in files}
    assert "same-title-idaaa.md" in names
    assert "same-title-idbbb.md" in names


def test_empty_title_slug_untitled(tmp_path: Path):
    page = make_page("id-123", "", "2026-11-01T00:00:00.000Z")
    port = FakePort([page])
    sync(port, "db1", tmp_path, title_property="Name")
    assert (tmp_path / "untitled-id123.md").exists()


def test_title_sanitization_cut_60(tmp_path: Path):
    long_title = "A" * 100
    page = make_page("id-abc", long_title, "2026-11-01T00:00:00.000Z")
    port = FakePort([page])
    sync(port, "db1", tmp_path, title_property="Name")
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert len(files[0].stem) <= 60 + 1 + 8  # slug + '-' + 8 hex


def test_render_markdown_no_body():
    page = make_page("id1", "Title", "2026-11-01T00:00:00.000Z")
    output = render_markdown(page, title_property="Name", body_property=None)
    expected = (
        "---\n"
        'id: "id1"\n'
        'last_edited_time: "2026-11-01T00:00:00.000Z"\n'
        'Name: "Title"\n'
        'Notes: ""\n'
        "---"
    )
    assert output == expected


def test_secret_not_in_error_or_event(tmp_path: Path):
    events: list[dict[str, object]] = []

    def on_event(event):
        events.append(event)

    pages = [make_page("id1", "Title", "2026-11-01T00:00:00.000Z", body="content")]
    port = FakePort(pages[:])
    sync(port, "db1", tmp_path, title_property="Name", body_property="Notes", on_event=on_event)
    assert all("secret" not in str(e) for e in events)

    # HttpNotionPort error should not contain token
    def fake_send(url, method, headers, body):
        assert "secret_x" not in url
        assert "secret_x" not in method
        assert "secret_x" not in body.decode()
        return 401, b"unauthorized"

    port = HttpNotionPort("secret_x", send=fake_send)
    with pytest.raises(NotionSyncError):
        port.query_database("db1", None)


class StaticPort:
    """Port returning a fixed query response."""

    def __init__(self, response: Any):
        self.response = response

    def query_database(self, database_id: str, start_cursor: str | None):
        return self.response


def test_property_type_mapping():
    page = {
        "properties": {
            "Num": {"type": "number", "number": 3},
            "Sel": {"type": "select", "select": {"name": "x"}},
            "SelNone": {"type": "select", "select": None},
            "Stat": {"type": "status", "status": {"name": "Done"}},
            "Ms": {"type": "multi_select", "multi_select": [{"name": "a"}]},
            "MsBad": {"type": "multi_select", "multi_select": None},
            "DateStart": {"type": "date", "date": {"start": "2026-01-01"}},
            "DateRange": {
                "type": "date",
                "date": {"start": "2026-01-01", "end": "2026-01-05"},
            },
            "DateNone": {"type": "date", "date": None},
            "Url": {"type": "url", "url": "https://example.com"},
            "Email": {"type": "email", "email": None},
            "Phone": {"type": "phone_number", "phone_number": "1"},
            "TitleBad": {"type": "title", "title": None},
        }
    }
    assert page_to_record(page) == {
        "DateNone": None,
        "DateRange": "2026-01-01/2026-01-05",
        "DateStart": "2026-01-01",
        "Email": None,
        "Ms": ["a"],
        "MsBad": [],
        "Num": 3,
        "Phone": "1",
        "Sel": "x",
        "SelNone": None,
        "Stat": "Done",
        "TitleBad": "",
        "Url": "https://example.com",
    }


def test_page_to_record_malformed_property():
    page = {"properties": {"Good": {"type": "checkbox", "checkbox": False}, "Bad": "nope"}}
    assert page_to_record(page) == {"Good": False}


def test_page_to_record_invalid_properties():
    with pytest.raises(ValueError):
        page_to_record({"properties": []})


def test_file_name_non_string_title():
    from notion_db_sync.transform import file_name_for_page

    page = {
        "id": "id1",
        "properties": {"Name": {"type": "checkbox", "checkbox": True}},
    }
    assert file_name_for_page(page, "Name") == "untitled-id1.md"


def test_render_markdown_non_string_body():
    page = make_page(
        "id1",
        "Title",
        "2026-11-01T00:00:00.000Z",
        extra_props={"Count": {"type": "number", "number": 5}},
    )
    output = render_markdown(page, title_property="Name", body_property="Count")
    assert output.endswith("---\n5\n")


def test_http_port_non_mapping_body():
    def fake_send(url, method, headers, body):
        return 200, b"[]"

    port = HttpNotionPort("secret", send=fake_send)
    with pytest.raises(NotionSyncError) as exc:
        port.query_database("db1", None)
    assert exc.value.code == "invalid_response"


def test_state_unreadable_json(tmp_path: Path):
    (tmp_path / ".notion-sync.json").write_text("not json", encoding="utf-8")
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([]), "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_state"


def test_state_pages_not_mapping(tmp_path: Path):
    (tmp_path / ".notion-sync.json").write_text(
        json.dumps({"version": 1, "database_id": "db1", "pages": []}), encoding="utf-8"
    )
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([]), "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_state"


def test_state_entry_malformed_for_existing_page(tmp_path: Path):
    page = make_page("id1", "Title", "2026-11-01T00:00:00.000Z")
    state = {"version": 1, "database_id": "db1", "pages": {"id1": {"file": 1}}}
    (tmp_path / ".notion-sync.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([page]), "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_state"


def test_state_malformed_deletion_entry_removed(tmp_path: Path):
    state = {"version": 1, "database_id": "db1", "pages": {"gone": {"file": 1}}}
    (tmp_path / ".notion-sync.json").write_text(json.dumps(state), encoding="utf-8")
    report = sync(FakePort([]), "db1", tmp_path, title_property="Name")
    assert report.deleted == 0
    saved = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert "gone" not in saved["pages"]


def test_state_path_traversal_rejected(tmp_path: Path):
    state = {
        "version": 1,
        "database_id": "db1",
        "pages": {"gone": {"file": "../escape.md", "sha256": "x"}},
    }
    (tmp_path / ".notion-sync.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([]), "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_state"


def test_state_path_traversal_rejected_existing_page(tmp_path: Path):
    outside = tmp_path.parent / "outside-target.md"
    outside.write_text("do not touch\n", encoding="utf-8")
    state = {
        "version": 1,
        "database_id": "db1",
        "pages": {
            "id1": {
                "file": "../outside-target.md",
                "last_edited_time": "2026-11-01T00:00:00.000Z",
                "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            }
        },
    }
    (tmp_path / ".notion-sync.json").write_text(json.dumps(state), encoding="utf-8")

    changed = make_page("id1", "Title", "2026-11-02T00:00:00.000Z", body="new")
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([changed]), "db1", tmp_path, title_property="Name", body_property="Notes")
    assert exc.value.code == "invalid_state"
    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "do not touch\n"


def test_state_absolute_path_rejected_existing_page(tmp_path: Path):
    state = {
        "version": 1,
        "database_id": "db1",
        "pages": {
            "id1": {
                "file": "C:\\Users\\someone\\notes.md",
                "last_edited_time": "2026-11-01T00:00:00.000Z",
                "sha256": "x",
            }
        },
    }
    (tmp_path / ".notion-sync.json").write_text(json.dumps(state), encoding="utf-8")
    changed = make_page("id1", "Title", "2026-11-02T00:00:00.000Z", body="new")
    with pytest.raises(NotionSyncError) as exc:
        sync(FakePort([changed]), "db1", tmp_path, title_property="Name", body_property="Notes")
    assert exc.value.code == "invalid_state"


def test_missing_page_without_local_file(tmp_path: Path):
    state = {
        "version": 1,
        "database_id": "db1",
        "pages": {"gone": {"file": "gone.md", "last_edited_time": "x", "sha256": "x"}},
    }
    (tmp_path / ".notion-sync.json").write_text(json.dumps(state), encoding="utf-8")
    report = sync(FakePort([]), "db1", tmp_path, title_property="Name")
    assert report.deleted == 0
    saved = json.loads((tmp_path / ".notion-sync.json").read_text(encoding="utf-8"))
    assert "gone" not in saved["pages"]


def test_invalid_response_not_mapping(tmp_path: Path):
    port = StaticPort([1, 2])
    with pytest.raises(NotionSyncError) as exc:
        sync(port, "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_response"


def test_invalid_response_missing_cursor(tmp_path: Path):
    port = StaticPort({"results": [], "has_more": True, "next_cursor": None})
    with pytest.raises(NotionSyncError) as exc:
        sync(port, "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_response"


def test_invalid_response_result_not_mapping(tmp_path: Path):
    port = StaticPort({"results": ["nope"], "has_more": False, "next_cursor": None})
    with pytest.raises(NotionSyncError) as exc:
        sync(port, "db1", tmp_path, title_property="Name")
    assert exc.value.code == "invalid_response"


def test_page_without_id_is_ignored(tmp_path: Path):
    port = StaticPort({"results": [{"properties": {}}], "has_more": False, "next_cursor": None})
    report = sync(port, "db1", tmp_path, title_property="Name")
    assert report == SyncReport(
        created=0, updated=0, unchanged=0, deleted=0, conflicts=(), skipped_properties=()
    )
    assert not list(tmp_path.glob("*.md"))


def test_page_removed_from_results_deletes_file(tmp_path: Path):
    pages = [
        make_page("id1", "One", "2026-11-01T00:00:00.000Z"),
        make_page("id2", "Two", "2026-11-01T00:00:00.000Z"),
    ]
    sync(FakePort(pages[:]), "db1", tmp_path, title_property="Name")
    report = sync(FakePort([pages[0]]), "db1", tmp_path, title_property="Name")
    assert report.deleted == 1
    assert not (tmp_path / "two-id2.md").exists()


def test_trashed_page_without_state_is_ignored(tmp_path: Path):
    trashed = make_page("id1", "Page", "2026-11-01T00:00:00.000Z", in_trash=True)
    report = sync(FakePort([trashed]), "db1", tmp_path, title_property="Name")
    assert report.deleted == 0
    assert report.conflicts == ()


def test_local_edit_remote_unchanged(tmp_path: Path):
    page = make_page("id1", "Title", "2026-11-01T00:00:00.000Z", body="orig")
    sync(FakePort([page]), "db1", tmp_path, title_property="Name", body_property="Notes")
    file = tmp_path / "title-id1.md"
    file.write_text(file.read_text(encoding="utf-8") + "\nedit", encoding="utf-8")

    report = sync(FakePort([page]), "db1", tmp_path, title_property="Name", body_property="Notes")
    assert report.unchanged == 1
    assert report.conflicts == ()
    assert file.read_text(encoding="utf-8").endswith("\nedit")


def test_events_and_rename(tmp_path: Path):
    events: list[dict[str, object]] = []
    first = [make_page("id1", "Title", "2026-11-01T00:00:00.000Z", body="one")]
    sync(
        FakePort(first[:]),
        "db1",
        tmp_path,
        title_property="Name",
        body_property="Notes",
        on_event=events.append,
    )
    assert events == [{"event": "created", "page_id": "id1", "file": "title-id1.md"}]

    second = [make_page("id1", "Renamed", "2026-11-02T00:00:00.000Z", body="two")]
    report = sync(
        FakePort(second[:]),
        "db1",
        tmp_path,
        title_property="Name",
        body_property="Notes",
        on_event=events.append,
    )
    assert report.updated == 1
    assert (tmp_path / "renamed-id1.md").exists()
    assert not (tmp_path / "title-id1.md").exists()
    assert events[-1] == {"event": "updated", "page_id": "id1", "file": "renamed-id1.md"}

    report = sync(
        FakePort([]),
        "db1",
        tmp_path,
        title_property="Name",
        body_property="Notes",
        on_event=events.append,
    )
    assert report.deleted == 1
    assert events[-1] == {"event": "deleted", "page_id": "id1", "file": "renamed-id1.md"}


def test_conflict_event_payload(tmp_path: Path):
    events: list[dict[str, object]] = []
    first = [make_page("id1", "Title", "2026-11-01T00:00:00.000Z", body="orig")]
    sync(
        FakePort(first[:]),
        "db1",
        tmp_path,
        title_property="Name",
        body_property="Notes",
        on_event=events.append,
    )
    file = tmp_path / "title-id1.md"
    file.write_text(file.read_text(encoding="utf-8") + "\nedit", encoding="utf-8")

    changed = [make_page("id1", "Title", "2026-11-02T00:00:00.000Z", body="remote")]
    report = sync(
        FakePort(changed[:]),
        "db1",
        tmp_path,
        title_property="Name",
        body_property="Notes",
        on_event=events.append,
    )
    assert report.conflicts == ("title-id1.md",)
    assert events[-1] == {"event": "conflict", "page_id": "id1", "file": "title-id1.md"}


def test_deletion_conflict_event_payload(tmp_path: Path):
    events: list[dict[str, object]] = []
    page = make_page("id1", "Page", "2026-11-01T00:00:00.000Z", body="content")
    sync(
        FakePort([page]),
        "db1",
        tmp_path,
        title_property="Name",
        body_property="Notes",
        on_event=events.append,
    )
    file = tmp_path / "page-id1.md"
    file.write_text(file.read_text(encoding="utf-8") + "\nedit", encoding="utf-8")

    trashed = make_page("id1", "Page", "2026-11-01T00:00:00.000Z", in_trash=True)
    report = sync(
        FakePort([trashed]),
        "db1",
        tmp_path,
        title_property="Name",
        body_property="Notes",
        on_event=events.append,
    )
    assert report.conflicts == ("page-id1.md",)
    assert events[-1] == {"event": "conflict", "page_id": "id1", "file": "page-id1.md"}


def test_atomic_write_failure_propagates(tmp_path: Path, monkeypatch):
    module = importlib.import_module("notion_db_sync.sync")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(module.os, "replace", boom)
    with pytest.raises(OSError):
        sync(FakePort([]), "db1", tmp_path, title_property="Name")
