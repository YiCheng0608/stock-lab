"""Where the file of a stored raw capture is (``raw_payloads.payload_path``, #342).

A capture's path is written where the collector ran. Until the Docker cutover that was the
Windows data directory (``C:\\Users\\YiCheng\\stock-lab-data\\raw\\...``); the scheduler
container writes ``/data/raw/...``. The cutover copies ``raw/`` into the volume and leaves the
database as it was (decision 1 of #342, comment 6588843632), so a rollback to Windows still
finds every old path. Each reader of ``payload_path`` goes through ``payload_file``: a path
that exists is used as it is; a path that does not, under the old Windows ``raw`` directory,
is the same relative path under ``STOCK_RAW_DIR``; anything else is returned unchanged, so the
reader fails as it did before.

``STOCK_STORED_RAW_DIR``, when set, is the ``raw`` directory to map to instead of
``app.config.RAW_DIR``: tools/ops/data_check.py points ``STOCK_RAW_DIR`` at a scratch directory
so nothing it fetches lands in the watchdog's data directory, yet the captures it reads are the
real ones.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from app import config

# The data directory's raw/ before the cutover (docs/OPERATIONS.md §6, user decision 2026-10-17).
LEGACY_RAW_DIRS = (r"C:\Users\YiCheng\stock-lab-data\raw",)
STORED_RAW_DIR_ENV = "STOCK_STORED_RAW_DIR"


def _key(text: str) -> str:
    # Windows paths: either separator, any case.
    return text.replace("\\", "/").rstrip("/").casefold()


def raw_dir() -> Path:
    """The raw directory an old Windows path is mapped to."""

    stored = os.environ.get(STORED_RAW_DIR_ENV)
    return Path(stored) if stored else Path(config.RAW_DIR)


def legacy_relative(payload_path: str) -> PurePosixPath | None:
    """PAYLOAD_PATH relative to the old Windows raw directory, or None when not under it."""

    text = payload_path.replace("\\", "/")
    for prefix in LEGACY_RAW_DIRS:
        key = _key(prefix) + "/"
        if text.casefold().startswith(key):
            parts = [part for part in text[len(key) :].split("/") if part]
            if not parts or any(part in (".", "..") for part in parts):
                return None
            return PurePosixPath(*parts)
    return None


def payload_file(payload_path: str | os.PathLike[str] | None) -> Path:
    """The file to read for PAYLOAD_PATH in this environment (see the module docstring).

    An empty or missing value is ``Path("")``, which every reader already failed on.
    """

    text = os.fspath(payload_path) if payload_path else ""
    path = Path(text)
    if not text or path.exists():
        return path
    relative = legacy_relative(text)
    if relative is None:
        return path
    return raw_dir().joinpath(*relative.parts)
