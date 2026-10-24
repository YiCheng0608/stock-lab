"""Build the verify-stock-lab fixture database (Issue #241).

    python tools/verify/fixture_db.py --dest <empty directory>

Writes ``<dest>/stock.db``: migrates an empty file to the Alembic head through
``app.db.init_db`` (the path ``python -m worker.cli init-db`` takes), inserts
the rows of ``tools/verify/fixture_data.py`` and prints one JSON object with
``alembic_version``, the row count of every table and a content hash.  The
elapsed time goes to stderr so two builds print identical JSON.

``STOCK_DATA_DIR``/``STOCK_DB_PATH``/``STOCK_RAW_DIR`` are pointed at ``dest``
before anything from ``app`` is imported; ``app.config`` creates
``<dest>/raw`` (left empty).  Nothing reads the production data directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DB_NAME = "stock.db"


def summarize(db_path: Path) -> dict:
    """Row counts and one SHA-256 over every table's rows in primary-key order."""

    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        digest = hashlib.sha256()
        counts = {}
        for table in tables:
            columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            keys = [
                column[1] for column in sorted(columns, key=lambda c: c[5]) if column[5]
            ]
            order = ", ".join(f'"{key}"' for key in keys) or "rowid"
            rows = connection.execute(
                f'SELECT * FROM "{table}" ORDER BY {order}'
            ).fetchall()
            counts[table] = len(rows)
            digest.update(f"{table}\n".encode())
            for row in rows:
                digest.update(json.dumps(row, ensure_ascii=False).encode() + b"\n")
        (version,) = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    finally:
        connection.close()
    return {
        "alembic_version": version,
        "tables": counts,
        "content_sha256": digest.hexdigest(),
    }


def build(dest: Path, skip: tuple[str, ...] = ()) -> dict:
    """Build ``dest/stock.db``; ``skip`` names fixture tables left without rows."""

    db_path = dest / DB_NAME
    if db_path.exists():
        raise SystemExit(f"{db_path} already exists; use an empty directory")
    dest.mkdir(parents=True, exist_ok=True)
    os.environ["STOCK_DATA_DIR"] = str(dest)
    os.environ["STOCK_DB_PATH"] = str(db_path)
    os.environ["STOCK_RAW_DIR"] = str(dest / "raw")
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import alembic.command  # noqa: F401
    except ImportError:
        # upgrade_database would fall back to create_all, a different schema path.
        raise SystemExit("alembic is not installed; install backend/requirements.txt")

    from sqlalchemy import MetaData

    from app.db import engine, init_db
    from app.migration_revisions import REVISIONS
    import fixture_data

    init_db()
    metadata = MetaData()
    metadata.reflect(bind=engine)
    with engine.begin() as connection:
        for name, rows in fixture_data.TABLES.items():
            if rows and name not in skip:
                connection.execute(metadata.tables[name].insert(), rows)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    engine.dispose()

    summary = summarize(db_path)
    if summary["alembic_version"] != REVISIONS[-1]:
        raise SystemExit(
            f"alembic_version {summary['alembic_version']} != head {REVISIONS[-1]}"
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", required=True, type=Path, help="empty directory")
    args = parser.parse_args()
    started = time.perf_counter()
    summary = build(args.dest.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"elapsed_seconds={time.perf_counter() - started:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()
