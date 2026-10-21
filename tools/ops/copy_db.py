"""Copy a stock.db for verification without writing to the source (Issue #227).

The source is opened with ``mode=ro`` and ``query_only``; the SQLite backup
API copies one consistent snapshot, WAL frames included, so the source needs
no checkpoint (a read-only connection cannot run one anyway). The copy is
written to ``<dest>/stock.db.partial``, switched to a rollback journal so it is
a single self-contained file, and only then renamed to ``<dest>/stock.db``.

The destination must not be the source's directory or inside it, so the
production data directory is never written. An existing ``<dest>/stock.db`` is
replaced only with ``--force``, so a mistyped destination (another worktree's
copy, say) is refused before anything there is touched. Prints one JSON object:
the copy path, the source path, the source's latest ``market_bars.trading_date``
and the copied Alembic revision.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

COPY_NAME = "stock.db"
# Left next to an older copy by an API process; stale ones must not meet a new copy.
SIDE_FILES = ("-wal", "-shm", "-journal")


class CopyError(Exception):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copy_db.py",
        description=(
            "Copy a SQLite stock.db read-only with the backup API into "
            f"<dest>/{COPY_NAME}; print the copy path and the source's latest "
            "trading_date as JSON."
        ),
    )
    parser.add_argument("--src", required=True, help="source stock.db (read only)")
    parser.add_argument(
        "--dest",
        required=True,
        help=f"directory for the copy ({COPY_NAME}); created when missing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"replace an existing <dest>/{COPY_NAME} and its -wal/-shm files",
    )
    return parser


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _scalar(conn: sqlite3.Connection, table: str, sql: str) -> object:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return conn.execute(sql).fetchone()[0] if exists else None


def copy_db(src: Path, dest: Path, force: bool = False) -> dict[str, object]:
    src = src.resolve()
    dest = dest.resolve()
    if not src.is_file():
        raise CopyError(f"source is not a file: {src}")
    if _inside(dest, src.parent):
        raise CopyError(
            f"destination {dest} is inside the source directory {src.parent}; "
            "choose a directory outside it"
        )
    target = dest / COPY_NAME
    if target.exists() and not force:
        raise CopyError(f"{target} already exists; pass --force to replace it")
    dest.mkdir(parents=True, exist_ok=True)
    partial = dest / (COPY_NAME + ".partial")
    for name in [partial.name] + [partial.name + s for s in SIDE_FILES]:
        (dest / name).unlink(missing_ok=True)

    started = time.monotonic()
    with closing(sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)) as source:
        source.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(partial)) as copy:
            # pages=-1: one step, one read transaction, one snapshot.
            source.backup(copy, pages=-1)
            copy.execute("PRAGMA journal_mode=DELETE")
            trading_date = _scalar(
                copy, "market_bars", "SELECT max(trading_date) FROM market_bars"
            )
            alembic = _scalar(
                copy, "alembic_version", "SELECT version_num FROM alembic_version"
            )

    try:
        for suffix in SIDE_FILES:
            Path(str(target) + suffix).unlink(missing_ok=True)
        os.replace(partial, target)
    except PermissionError as error:
        raise CopyError(
            f"{target} is in use (stop the API that opened it first): {error}"
        ) from error
    return {
        "copy": target.as_posix(),
        "source": src.as_posix(),
        "source_latest_trading_date": trading_date,
        "alembic_version": alembic,
        "bytes": target.stat().st_size,
        "seconds": round(time.monotonic() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = copy_db(Path(args.src), Path(args.dest), force=args.force)
    except (CopyError, sqlite3.Error) as error:
        print(f"copy_db: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
