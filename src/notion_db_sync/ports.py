"""Transport layer for querying the Notion API."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Protocol

from .errors import NotionSyncError


class NotionPort(Protocol):
    """Protocol for anything that can query a Notion database."""

    def query_database(self, database_id: str, start_cursor: str | None) -> Mapping[str, object]:
        """Return the raw JSON object from POST /v1/databases/{id}/query."""
        ...


Send = Callable[[str, str, Mapping[str, str], bytes], tuple[int, bytes]]


class HttpNotionPort:
    """Concrete port that calls the Notion HTTP API.

    Args:
        token: Notion integration token. Never logged or exposed in errors.
        send: Callable taking (url, method, headers, body_bytes) and returning
            (status_code, response_body_bytes). Allows injection for testing.
        notion_version: API version string (default '2022-06-28').
        max_response_bytes: Maximum allowed size of a response body. Exceeding
            this raises ``NotionSyncError('response_too_large')``.
    """

    def __init__(
        self,
        token: str,
        *,
        send: Send,
        notion_version: str = "2022-06-28",
        max_response_bytes: int = 10_485_760,
    ):
        self._token = token
        self._send = send
        self._notion_version = notion_version
        self._max_response_bytes = max_response_bytes

    def query_database(self, database_id: str, start_cursor: str | None) -> Mapping[str, object]:
        """Query the given database, optionally continuing from a cursor."""
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": self._notion_version,
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {"page_size": 100}
        if start_cursor is not None:
            payload["start_cursor"] = start_cursor
        body = json.dumps(payload).encode()

        status, response_body = self._send(url, "POST", headers, body)

        if len(response_body) > self._max_response_bytes:
            raise NotionSyncError("response_too_large")

        if status == 401:
            raise NotionSyncError("unauthorized")
        if status == 429:
            raise NotionSyncError("rate_limited")
        if status >= 400:
            raise NotionSyncError("http_error")

        try:
            data = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise NotionSyncError("invalid_response") from None

        if not isinstance(data, Mapping):
            raise NotionSyncError("invalid_response")

        return data
