"""Behavior tests for the public API of notion_db_sync."""

from __future__ import annotations

import pytest

import notion_db_sync


def test_normalize_trims_and_lowercases() -> None:
    assert notion_db_sync.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        notion_db_sync.normalize(value)


def test_version_is_semver() -> None:
    parts = notion_db_sync.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
