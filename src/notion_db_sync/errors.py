"""Exception types for notion-db-sync."""

from typing import Literal

SyncErrorCode = Literal[
    "unauthorized",
    "rate_limited",
    "http_error",
    "response_too_large",
    "invalid_response",
    "too_many_pages",
    "too_many_records",
    "invalid_state",
]


class NotionSyncError(Exception):
    """Base error for all notion-db-sync failures.

    Attributes:
        code: Stable machine-readable error code.
        message: Human-readable description (never contains secrets or more
            than 200 characters of input).
    """

    def __init__(self, code: SyncErrorCode, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)
