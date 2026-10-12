"""Failures of the test-database entry.

Every failure names a stable ``code``, the absolute ``path`` it concerns, the
``size_bytes`` involved (when a file or tree is concerned) and a human-readable
``reason``, so a caller or reviewer can locate the problem without rerunning.
"""

from __future__ import annotations

from typing import Any


class DbEntryError(Exception):
    def __init__(
        self,
        code: str,
        reason: str,
        *,
        path: Any = None,
        size_bytes: int | None = None,
        **details: Any,
    ) -> None:
        self.code = code
        self.reason = reason
        self.path = str(path) if path is not None else None
        self.size_bytes = size_bytes
        self.details = details
        super().__init__(f"[{code}] {reason} (path={self.path}, size_bytes={size_bytes})")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "details": self.details,
        }


class QuotaExceededError(DbEntryError):
    """The tool root would exceed its authorized total size."""

    def __init__(self, reason: str, *, path: Any, size_bytes: int, **details: Any) -> None:
        super().__init__("quota_exceeded", reason, path=path, size_bytes=size_bytes, **details)


class CleanupError(DbEntryError):
    """Removal left something behind; ``failures`` lists every item with path, size and reason."""

    def __init__(self, root: Any, failures: list[dict[str, Any]], remaining_bytes: int) -> None:
        first = failures[0]
        reason = f"{len(failures)} item(s) could not be removed; first: {first['reason']}"
        super().__init__(
            "cleanup_failed",
            reason,
            path=first["path"],
            size_bytes=first["size_bytes"],
            root=str(root),
            failures=failures,
            remaining_bytes=remaining_bytes,
        )
        self.failures = failures
