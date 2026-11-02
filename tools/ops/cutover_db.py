"""The database checks of tools/ops/cutover.sh (#342), on the host and in a container.

cutover.sh pipes this file to ``python -`` in a container, so the image needs no copy of it.
Standard library only.

  counts <db>                 one JSON object: integrity_check, journal_mode and every table's
                              row count, read-only (mode=ro, query_only)
  compare <a.json> <b.json>   exit 0 when both are integrity ok with the same row counts;
                              else the differences, exit 1
  rewrite-paths <db> <raw>    rollback: the payload_path of each capture the container wrote
                              (/data/raw/...) becomes the same file under RAW, the host's raw
                              directory, with Windows separators when RAW is a Windows path;
                              prints the number of rows changed. Only for a copy that is not
                              in use (cutover.sh runs it on its own snapshot).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

CONTAINER_RAW = "/data/raw/"


def counts(db: str) -> dict:
    uri = Path(db).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables = {
            name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for name in names
        }
    return {
        "integrity_check": integrity[0] if integrity == ["ok"] else integrity[:20],
        "journal_mode": journal,
        "tables": tables,
    }


def compare(a: dict, b: dict) -> list[str]:
    problems = [
        f"{side}: integrity_check {value['integrity_check']}"
        for side, value in (("a", a), ("b", b))
        if value["integrity_check"] != "ok"
    ]
    for name in sorted(set(a["tables"]) | set(b["tables"])):
        left, right = a["tables"].get(name), b["tables"].get(name)
        if left != right:
            problems.append(f"{name}: {left} != {right}")
    return problems


def host_path(raw: str, relative: str) -> str:
    windows = len(raw) > 1 and raw[1] == ":"
    sep = "\\" if windows else "/"
    base = raw.replace("/", "\\") if windows else raw
    return base.rstrip(sep) + sep + relative.replace("/", sep)


def rewrite_paths(db: str, raw: str) -> int:
    with closing(sqlite3.connect(db)) as conn:
        rows = conn.execute(
            "SELECT id, payload_path FROM raw_payloads WHERE payload_path LIKE ?",
            (CONTAINER_RAW + "%",),
        ).fetchall()
        with conn:
            conn.executemany(
                "UPDATE raw_payloads SET payload_path = ? WHERE id = ?",
                [
                    (host_path(raw, path[len(CONTAINER_RAW) :]), row_id)
                    for row_id, path in rows
                ],
            )
    return len(rows)


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "counts":
        print(json.dumps(counts(argv[1]), sort_keys=True))
        return 0
    if len(argv) == 3 and argv[0] == "compare":
        a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in argv[1:])
        problems = compare(a, b)
        for line in problems:
            print(line)
        return 1 if problems else 0
    if len(argv) == 3 and argv[0] == "rewrite-paths":
        print(rewrite_paths(argv[1], argv[2]))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
