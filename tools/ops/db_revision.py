"""The database's Alembic revision against the head of the code that would run it (#456).

tools/ops/deploy.sh pipes this file to ``python - /data/stock.db`` in a throwaway container of
the backend image it has just built, with the project's data volume mounted read-only and no
network, before any container is replaced. The head is that image's ``app.migration_revisions``
(the tag's own chain, which the new api's readiness accepts as the only revision); the revision
is the volume's DB. Prints one line, ``revision <state> <db> <head>``:

  same      the DB is at the head;
  behind    the DB is at an earlier revision of the chain: back it up, then init-db with the
            new image (docs/RELEASE.md, 含 migration 的版本);
  ahead     the DB's revision is not in the chain: a later tag's (deploying an older tag back),
            or not this project's (docs/RELEASE.md, 版本回退);
  missing   there is no database file (db is ``-``);
  unmarked  no alembic_version table, or not exactly one row in it (db is ``-``, or the rows
            joined with ``,``).

Exit 2 when the database cannot be read. Never writes: ``mode=ro`` and ``query_only``. On the
read-only volume a WAL database without its -shm file (no connection open) cannot be opened
``mode=ro``; when there is no -wal file either, the main file alone is the whole database and
it is opened ``immutable=1``. A -wal without -shm, or a hot -journal, is not read (immutable
would skip the WAL, or read pages a rollback has yet to undo).

Stricter than the api's readiness on purpose: readiness also accepts a DB with no
alembic_version whose schema_migrations lists every revision (the fallback when Alembic
cannot load); here that DB is ``unmarked`` and the deploy is refused. Every image carries
Alembic and the production DB has always had alembic_version, so a DB without it is a DB
to look at before deploying, not one to deploy onto.
Imports nothing but the standard library and app.migration_revisions, which does no I/O.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from app.migration_revisions import REVISIONS


# Kept identical in tools/ops/db_revision.py and tools/ops/copy_db.py (#486; a test compares
# the two). Neither can import the other: copy_db.py is mounted alone into whichever image is
# running, db_revision.py is piped on stdin.
def open_read_only(path: Path) -> tuple[sqlite3.Connection, bool]:
    """(connection, immutable): ``mode=ro``; ``immutable=1`` only when that cannot open the
    file and nothing is next to it (no -wal, -shm or hot -journal), so it is the whole DB."""
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.OperationalError:
            connection.close()
            raise
        return connection, False
    except sqlite3.OperationalError:
        sides = ("-wal", "-shm", "-journal")
        if any(Path(f"{path}{side}").exists() for side in sides):
            raise
    return sqlite3.connect(uri + "&immutable=1", uri=True), True


def revision(path: Path) -> tuple[str, str]:
    """(state, db revision) of the database at path; see the module docstring."""
    if not path.is_file():
        return "missing", "-"
    with closing(open_read_only(path)[0]) as connection:
        connection.execute("PRAGMA query_only=ON")
        has_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        rows = (
            [
                row[0]
                for row in connection.execute(
                    "SELECT version_num FROM alembic_version LIMIT 2"
                )
            ]
            if has_table
            else []
        )
    if len(rows) != 1 or type(rows[0]) is not str or not rows[0].strip():
        return "unmarked", ",".join(str(row) for row in rows) or "-"
    db = rows[0]
    if db == REVISIONS[-1]:
        return "same", db
    if db in REVISIONS:
        return "behind", db
    return "ahead", db


def main(argv: list[str]) -> int:
    path = Path(argv[0] if argv else "/data/stock.db")
    try:
        state, db = revision(path)
    except sqlite3.Error as error:
        print(f"讀不到 {path}：{error}", file=sys.stderr)
        return 2
    # One token each: a revision with blanks would split the line.
    print("revision", state, "_".join(db.split()) or "-", REVISIONS[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
