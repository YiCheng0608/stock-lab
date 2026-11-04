"""Compare the news rule relations of two checkouts on the same news (#461).

Relates the active feed items of a period with the ``RelationMatcher`` of this
checkout and with that of ``--base-root`` (another checkout, for example
``git archive <commit>`` of the previous rule), each in its own Python process
so the two ``worker`` packages never mix, and lists the "news item × stock"
pairs only one of them makes: ``added`` (this checkout only) and ``removed``
(the base only), with the title and summary to read them by.

``--sample N --seed S`` draws, once, N pairs from ``added`` (sorted by item id
and key) with ``random.Random(S).sample``; when ``added`` has fewer than N, all
of it is the sample and the rest is drawn, with the same generator, from this
checkout's two-character-name-only pairs of the period
(``news_two_char_hits.py``) that are not in ``added``.  The period, the
categories and the read-only connection are those of news_two_char_hits.py.
Nothing is written to the database.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "news-relation-diff/v1"

# Run in a fresh interpreter with a checkout's backend/ first on sys.path; it
# only uses what every rule version has: RelationMatcher.from_db and symbols().
_DUMP = r"""
import json, sqlite3, sys
backend, db, low, high, categories = sys.argv[1:6]
sys.path.insert(0, backend)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from worker.news_batch import RELATION_METHOD, RelationMatcher
from pathlib import Path
uri = Path(db).resolve().as_uri() + "?mode=ro"
def connect():
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only=1")
    return con
engine = create_engine("sqlite://", creator=connect)
cats = json.loads(categories)
with Session(engine) as session:
    matcher = RelationMatcher.from_db(session)
    rows = session.connection().exec_driver_sql(
        "SELECT id, title, summary FROM news_items WHERE status = 'active' "
        "AND category IN (" + ",".join("?" for _ in cats) + ") "
        "AND COALESCE(published_at, collected_at) >= ? "
        "AND COALESCE(published_at, collected_at) < ? ORDER BY id",
        (*cats, low, high),
    ).all()
    out = {str(i): matcher.symbols(t or "", s or "") for i, t, s in rows}
engine.dispose()
print(json.dumps({"method": RELATION_METHOD, "symbols": out}))
"""


def _hits_tool():
    spec = importlib.util.spec_from_file_location(
        "news_two_char_hits", ROOT / "tools" / "research" / "news_two_char_hits.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def relations(
    root: Path, db: Path, since: date, until: date, categories: tuple[str, ...]
) -> dict[str, Any]:
    """{"method", "symbols": {item id: [keys]}} of the checkout at ROOT."""

    low, high = _hits_tool()._utc_bounds(since, until)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            _DUMP,
            str(root / "backend"),
            str(db),
            low,
            high,
            json.dumps(list(categories)),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        cwd=root,
    )
    return json.loads(result.stdout)


def _pairs(symbols: dict[str, list[str]]) -> set[tuple[int, str]]:
    return {(int(item), key) for item, keys in symbols.items() for key in keys}


def _texts(db: Path, ids: set[int]) -> dict[int, tuple[str, str]]:
    if not ids:
        return {}
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")
    try:
        marks = ",".join("?" for _ in ids)
        return {
            row[0]: (row[1] or "", row[2] or "")
            for row in con.execute(
                f"SELECT id, title, summary FROM news_items WHERE id IN ({marks})",
                sorted(ids),
            )
        }
    finally:
        con.close()


def diff(
    db: Path,
    since: date,
    until: date,
    base_root: Path,
    categories: tuple[str, ...] = ("domestic",),
    sample: int = 0,
    seed: int | None = None,
) -> dict[str, Any]:
    base = relations(base_root, db, since, until, categories)
    head = relations(ROOT, db, since, until, categories)
    base_pairs, head_pairs = _pairs(base["symbols"]), _pairs(head["symbols"])
    added, removed = sorted(head_pairs - base_pairs), sorted(base_pairs - head_pairs)
    drawn: list[dict[str, Any]] = []
    if sample:
        rng = random.Random(seed)
        if len(added) >= sample:
            drawn = [
                {"news_item_id": i, "symbol": k, "from": "added"}
                for i, k in rng.sample(added, sample)
            ]
        else:
            hits = _hits_tool().measure(db, since, until, categories, examples=0)
            two_char = sorted(
                {
                    (item, row["symbol"])
                    for row in hits["names"]
                    for item in row["news_item_ids"]
                }
                - set(added)
            )
            drawn = [
                {"news_item_id": i, "symbol": k, "from": "added"} for i, k in added
            ] + [
                {"news_item_id": i, "symbol": k, "from": "two_char_only"}
                for i, k in rng.sample(
                    two_char, min(sample - len(added), len(two_char))
                )
            ]
        drawn.sort(key=lambda row: (row["news_item_id"], row["symbol"]))
    texts = _texts(
        db,
        {i for i, _ in added}
        | {i for i, _ in removed}
        | {d["news_item_id"] for d in drawn},
    )

    def rows(pairs):
        return [
            {
                "news_item_id": item,
                "symbol": key,
                "title": texts[item][0],
                "summary": texts[item][1],
            }
            for item, key in pairs
        ]

    for row in drawn:
        row["title"], row["summary"] = texts[row["news_item_id"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "period": {"since": since.isoformat(), "until": until.isoformat()},
        "categories": list(categories),
        "base_method": base["method"],
        "method": head["method"],
        "items": len(head["symbols"]),
        "items_with_symbols": {
            "base": sum(bool(keys) for keys in base["symbols"].values()),
            "head": sum(bool(keys) for keys in head["symbols"].values()),
        },
        "pairs": {"base": len(base_pairs), "head": len(head_pairs)},
        "added": rows(added),
        "removed": rows(removed),
        "sample": {"seed": seed, "size": sample, "drawn": drawn},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, type=Path, help="stock.db copy")
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", required=True, type=date.fromisoformat)
    parser.add_argument("--base-root", required=True, type=Path)
    parser.add_argument("--category", action="append")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.until < args.since:
        parser.error("--until is before --since")
    if args.sample and args.seed is None:
        parser.error("--sample needs --seed")
    data = diff(
        args.db,
        args.since,
        args.until,
        args.base_root,
        tuple(args.category or ("domestic",)),
        args.sample,
        args.seed,
    )
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "base_method": data["base_method"],
                "method": data["method"],
                "items": data["items"],
                "items_with_symbols": data["items_with_symbols"],
                "added": len(data["added"]),
                "removed": len(data["removed"]),
                "drawn": len(data["sample"]["drawn"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
