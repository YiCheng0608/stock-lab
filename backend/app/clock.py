"""The current time as naive UTC, the form every DateTime column stores (#374).

``datetime.utcnow()`` is deprecated and warned on every call (about 170,000 warnings
per backend pytest run); ``utcnow()`` returns the same value and type. Imports nothing
from the app, so models, the API and the worker can all use it.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC now, as ``datetime.utcnow()`` returned it."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
