"""Transforms Notion page objects into records and Markdown."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

# Property types that map to a scalar/list value. Unsupported types are skipped
# and recorded in ``skipped_properties``.
_SUPPORTED_TYPES = {
    "title",
    "rich_text",
    "number",
    "select",
    "status",
    "multi_select",
    "date",
    "checkbox",
    "url",
    "email",
    "phone_number",
}


def _extract_property_value(prop: Mapping[str, Any]) -> Any:
    """Extract the Python value for a single Notion property object."""
    ptype = prop.get("type")

    if ptype in {"title", "rich_text"}:
        items = prop.get(ptype, [])
        if isinstance(items, list):
            return "".join(
                item.get("plain_text", "") for item in items if isinstance(item, Mapping)
            )
        return ""

    if ptype == "number":
        return prop.get("number")

    if ptype in {"select", "status"}:
        inner = prop.get(ptype)
        if isinstance(inner, Mapping):
            return inner.get("name")
        return None

    if ptype == "multi_select":
        items = prop.get("multi_select", [])
        if isinstance(items, list):
            return [item["name"] for item in items if isinstance(item, Mapping) and "name" in item]
        return []

    if ptype == "date":
        date_obj = prop.get("date")
        if not isinstance(date_obj, Mapping):
            return None
        start = date_obj.get("start")
        end = date_obj.get("end")
        if end is not None:
            return f"{start}/{end}"
        return start

    if ptype == "checkbox":
        return bool(prop.get("checkbox", False))

    if ptype in {"url", "email", "phone_number"}:
        return prop.get(ptype)

    # Unsupported types (formula, relation, people, files, etc.) return None.
    return None


def _page_to_record_with_skipped(page: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Build (record, skipped_names) from a page object."""
    props = page.get("properties", {})
    record: dict[str, Any] = {}
    skipped: list[str] = []

    if not isinstance(props, Mapping):
        raise ValueError("page must contain a 'properties' mapping")

    for prop_name, prop in props.items():
        if not isinstance(prop, Mapping):
            skipped.append(prop_name)
            continue
        ptype = prop.get("type")
        if ptype in _SUPPORTED_TYPES:
            record[prop_name] = _extract_property_value(prop)
        else:
            skipped.append(prop_name)

    # Return a new dict with sorted keys to keep deterministic output.
    sorted_record = {key: record[key] for key in sorted(record)}
    return sorted_record, sorted(skipped)


def page_to_record(page: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a Notion page object to a flat dictionary of property values.

    Keys are sorted alphabetically. Unsupported property types are omitted.

    Args:
        page: Mapping with at least 'id', 'last_edited_time', and 'properties'.

    Returns:
        dict mapping property names to extracted values.

    Raises:
        ValueError: if 'properties' is not a mapping.
    """
    record, _ = _page_to_record_with_skipped(page)
    return record


def slugify_title(title: str) -> str:
    """Slugify a title for safe file naming.

    Lowercase, replace runs of characters outside [a-z0-9] with '-', trim '-',
    truncate to 60 characters, and use 'untitled' if empty.
    """
    lowered = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not slug:
        slug = "untitled"
    return slug[:60]


def file_name_for_page(page: Mapping[str, Any], title_property: str) -> str:
    """Return the Markdown filename for a page."""
    record = page_to_record(page)
    title = record.get(title_property, "")
    if not isinstance(title, str):
        title = ""
    slug = slugify_title(title)
    page_id = str(page.get("id", ""))
    id_suffix = page_id.replace("-", "")[:8]
    return f"{slug}-{id_suffix}.md"


def render_markdown(
    page: Mapping[str, Any],
    *,
    title_property: str,
    body_property: str | None = None,
) -> str:
    """Render a Notion page as a Markdown string with YAML front matter.

    Front matter contains 'id', 'last_edited_time', and all extracted properties
    sorted by name, excluding the body property. The body text (if body_property
    is set and present) is appended after the closing '---' and a newline.

    Args:
        page: Page mapping.
        title_property: Name of the property used as the page title.
        body_property: Optional name of a property whose text becomes the body.

    Returns:
        Rendered Markdown string.
    """
    record, _ = _page_to_record_with_skipped(page)
    page_id = str(page.get("id", ""))
    last_edited = str(page.get("last_edited_time", ""))

    front_matter: dict[str, Any] = {"id": page_id, "last_edited_time": last_edited}
    for key in sorted(record.keys()):
        if key == body_property:
            continue
        front_matter[key] = record[key]

    lines = ["---"]
    for key, value in front_matter.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")

    if body_property is not None:
        body_text = record.get(body_property, "")
        if not isinstance(body_text, str):
            body_text = str(body_text)
        lines.append(body_text)
        return "\n".join(lines) + "\n"
    return "\n".join(lines)
