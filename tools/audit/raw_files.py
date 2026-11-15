"""List the raw captures the database cites whose file is damaged (Issue #772).

A ``raw_payloads`` row is damaged when its file is missing, is 0 bytes, cannot be read,
or (unless ``--quick``) its sha256 is not the one recorded.  For each such row the output names
the raw id, the stored path and the file read, the endpoint, ``collected_at`` and how
many rows of which table cite it: every column whose foreign key is
``raw_payloads.id`` (``PRAGMA foreign_key_list``), so a new table is covered without
editing this file.  References kept inside JSON metadata are not counted.

Only reads: the database through ``mode=ro`` + ``query_only`` (audit_lib.connect),
the files with ``open(path, "rb")``; only the columns it needs are selected.  Use a
copy of the production database (tools/ops/copy_db.py); the raw directory may be
the data volume mounted read-only.  Where a file is follows ``app.raw_paths``:
``--raw-dir`` is where an old Windows path is looked for, as in audit.py.
``--fallback-raw-dir`` is a second raw directory: a missing file that is whole there,
under the same path relative to its raw directory, is counted in
``whole_in_fallback`` and not listed (the research DB's rows copied from production
have their files only in the production volume, #772 decision 6893166947).

Refuses (exit 2) between 21:30 and 23:30 Taipei time: hashing every file competes
with the daily job for the disk.  Prints one JSON object; exit 0 when nothing is
damaged, 1 otherwise.

    python tools/audit/raw_files.py --db /copy/stock.db [--raw-dir /data/raw] [--quick]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools" / "research"))

from audit_lib import RawFiles, connect, tables  # noqa: E402
from backtest_research import daily_window_problem  # noqa: E402

from app.raw_paths import legacy_relative  # noqa: E402
from app.raw_paths import raw_dir as stored_raw_dir  # noqa: E402

MISSING, EMPTY, SHA_MISMATCH, UNREADABLE = (
    "missing",
    "empty",
    "sha_mismatch",
    "unreadable",
)
CHUNK = 1 << 20
# SQLite's default limit on host parameters is 999 before 3.32.
ID_BATCH = 500


def file_state(path: Path, sha256: str | None, quick: bool) -> str | None:
    """MISSING, EMPTY, SHA_MISMATCH or UNREADABLE for a damaged file; None when whole."""

    try:
        handle = open(path, "rb")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return MISSING
    except OSError:
        return UNREADABLE
    with handle:
        try:
            chunk = handle.read(CHUNK)
            if not chunk:
                return EMPTY
            if quick or not sha256:
                return None
            digest = hashlib.sha256()
            while chunk:
                digest.update(chunk)
                chunk = handle.read(CHUNK)
        except OSError:
            return UNREADABLE
    return None if digest.hexdigest() == sha256 else SHA_MISMATCH


def referencing_columns(con: sqlite3.Connection) -> list[tuple[str, str]]:
    """(table, column) of every foreign key to ``raw_payloads.id``."""

    found = []
    for table in sorted(tables(con)):
        for row in con.execute(f'PRAGMA foreign_key_list("{table}")'):
            # id, seq, table, from, to, on_update, on_delete, match
            if row[2] == "raw_payloads" and row[4] in (None, "id"):
                found.append((table, row[3]))
    return found


def references(
    con: sqlite3.Connection, raw_ids: list[int]
) -> dict[int, dict[str, int]]:
    """For each of RAW_IDS, ``{"table.column": rows}`` of the rows citing it."""

    cited: dict[int, dict[str, int]] = defaultdict(dict)
    for table, column in referencing_columns(con):
        for start in range(0, len(raw_ids), ID_BATCH):
            batch = raw_ids[start : start + ID_BATCH]
            marks = ",".join("?" * len(batch))
            query = (
                f'SELECT "{column}", count(*) FROM "{table}" '
                f'WHERE "{column}" IN ({marks}) GROUP BY "{column}"'
            )
            for raw_id, count in con.execute(query, batch):
                cited[int(raw_id)][f"{table}.{column}"] = int(count)
    return cited


def relative_to_raw(payload_path: str, path: Path) -> PurePosixPath | None:
    """PATH (the file read for PAYLOAD_PATH) relative to its raw directory."""

    legacy = legacy_relative(payload_path)
    if legacy is not None:
        return legacy
    try:
        return PurePosixPath(path.relative_to(stored_raw_dir()).as_posix())
    except ValueError:
        return None


def scan(
    db: Path, raw_dir: Path | None, quick: bool, fallback_raw_dir: Path | None = None
) -> dict[str, Any]:
    con = connect(db)
    files = RawFiles(raw_dir)
    damaged: list[dict[str, Any]] = []
    states: Counter[str] = Counter()
    checked = 0
    in_fallback = 0
    rows = con.execute(
        "SELECT id, endpoint, payload_path, sha256, collected_at "
        "FROM raw_payloads ORDER BY id"
    )
    for raw_id, endpoint, payload_path, sha256, collected_at in rows:
        checked += 1
        path = files.path(payload_path) if payload_path else None
        state = MISSING if path is None else file_state(path, sha256, quick)
        if state == MISSING and path is not None and fallback_raw_dir is not None:
            relative = relative_to_raw(payload_path, path)
            if relative is not None and (
                file_state(fallback_raw_dir.joinpath(*relative.parts), sha256, quick)
                is None
            ):
                in_fallback += 1
                continue
        if state is None:
            continue
        states[state] += 1
        damaged.append(
            {
                "raw_id": int(raw_id),
                "state": state,
                "payload_path": payload_path,
                "file": None if path is None else str(path),
                "endpoint": endpoint,
                "collected_at": collected_at,
                "sha256": sha256,
            }
        )
    cited = references(con, [item["raw_id"] for item in damaged])
    con.close()
    for item in damaged:
        item["referenced_by"] = cited.get(item["raw_id"], {})
    return {
        "db": str(db),
        "quick": quick,
        "raw_payloads": checked,
        "fallback_raw_dir": None if fallback_raw_dir is None else str(fallback_raw_dir),
        "whole_in_fallback": in_fallback,
        "damaged": len(damaged),
        "by_state": dict(sorted(states.items())),
        "referenced_damaged": sum(1 for item in damaged if item["referenced_by"]),
        "files": damaged,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--db", required=True, help="a stock.db (a copy for production)"
    )
    parser.add_argument(
        "--raw-dir", help="raw directory an old Windows payload_path is looked for in"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="only missing and 0-byte files; no sha256 is computed",
    )
    parser.add_argument(
        "--fallback-raw-dir",
        help="another raw directory (read-only) where a missing file is looked for "
        "under the same relative path, e.g. the production volume's for the "
        "research DB's rows copied from production",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    problem = daily_window_problem(datetime.now(timezone.utc))
    if problem:
        print(json.dumps({"refused": [problem]}, ensure_ascii=False))
        return 2
    db = Path(args.db)
    if not db.is_file():
        print(json.dumps({"refused": [f"{db} is not a file"]}, ensure_ascii=False))
        return 2
    result = scan(
        db,
        Path(args.raw_dir) if args.raw_dir else None,
        args.quick,
        Path(args.fallback_raw_dir) if args.fallback_raw_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 1 if result["damaged"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
