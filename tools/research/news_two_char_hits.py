"""Two-character-name news relations without a code, by name, for reading by hand (#461).

The news rule counts a listed stock's two-character name on its own (NEWS_SPEC §2
規則關聯 第 4 點).  Those matches are where the rule goes wrong (泰山 the district,
南港, 中華民國), so this lists, for the active feed items of a period, every
relation the rule makes only through a two-character name: the stock is matched,
and it would not be without rule 4 (no code with context, no longer name).

Reads a stock.db copy through a ``mode=ro`` connection with ``query_only`` on;
nothing is written to the database.  The period is in Taipei dates of the
source time (``published_at``, else ``collected_at``).  Writes one JSON file:
per name, the stock, how many items it matched, where (title start, title
segment, summary segment) and up to ``--examples`` titles with the text around
the match; and the item ids, so a reader can go back to the rows.  The matcher
is the one in this checkout (``worker.news_batch.RelationMatcher.from_db``);
news_relation_diff.py compares two checkouts' rules on the same news.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from worker.news_batch import RELATION_METHOD, RelationMatcher  # noqa: E402

TAIPEI = ZoneInfo("Asia/Taipei")
SCHEMA_VERSION = "news-two-char-hits/v1"
# Characters kept on each side of a match in an example.
CONTEXT_CHARS = 12


def _utc_bounds(since: date, until: date) -> tuple[str, str]:
    """Naive UTC instants (as stored) of Taipei ``since`` 00:00 and ``until`` + 1 day."""

    def utc(day: date) -> str:
        local = datetime.combine(day, time(), TAIPEI)
        return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat(" ")

    return utc(since), utc(until + timedelta(days=1))


def _where(field: str, start: int) -> str:
    if field == "summary":
        return "summary_segment"
    return "title_start" if start == 0 else "title_segment"


def _snippet(text: str, start: int, name: str) -> str:
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), start + len(name) + CONTEXT_CHARS)
    return (
        ("…" if left else "")
        + text[left:start]
        + f"【{name}】"
        + text[start + len(name) : right]
        + ("…" if right < len(text) else "")
    )


def measure(
    db: Path,
    since: date,
    until: date,
    categories: tuple[str, ...] = ("domestic",),
    examples: int = 3,
) -> dict[str, Any]:
    uri = f"{db.resolve().as_uri()}?mode=ro"

    def connect() -> sqlite3.Connection:
        con = sqlite3.connect(uri, uri=True)
        con.execute("PRAGMA query_only=1")
        return con

    engine = create_engine("sqlite://", creator=connect)
    try:
        with Session(engine) as session:
            matcher = RelationMatcher.from_db(session)
            names = {
                f"{exchange}:{symbol}": name
                for exchange, symbol, name in session.connection()
                .exec_driver_sql("SELECT exchange, symbol, name FROM instruments")
                .all()
            }
            low, high = _utc_bounds(since, until)
            marks = ",".join("?" for _ in categories)
            rows = (
                session.connection()
                .exec_driver_sql(
                    "SELECT id, title, summary FROM news_items "
                    f"WHERE status = 'active' AND category IN ({marks}) "
                    "AND COALESCE(published_at, collected_at) >= ? "
                    "AND COALESCE(published_at, collected_at) < ? ORDER BY id",
                    (*categories, low, high),
                )
                .all()
            )
    finally:
        engine.dispose()

    by_name: dict[tuple[str, str], dict[str, Any]] = {}
    with_hit = 0
    for item_id, title, summary in rows:
        title, summary = title or "", summary or ""
        without = set(matcher.symbols(title, summary, two_char=False))
        seen: set[str] = set()
        for key, name, field, start in matcher.two_char_hits(title, summary):
            if key in without or key in seen:
                continue
            seen.add(key)
            text = title if field == "title" else summary
            entry = by_name.setdefault(
                (name, key),
                {
                    "name": name,
                    "symbol": key,
                    "instrument_name": names.get(key),
                    "items": 0,
                    "where": {},
                    "examples": [],
                    "news_item_ids": [],
                },
            )
            entry["items"] += 1
            where = _where(field, start)
            entry["where"][where] = entry["where"].get(where, 0) + 1
            entry["news_item_ids"].append(item_id)
            if len(entry["examples"]) < examples:
                entry["examples"].append(
                    {
                        "news_item_id": item_id,
                        "title": title,
                        "field": field,
                        "context": _snippet(text, start, name),
                    }
                )
        with_hit += bool(seen)
    names_out = sorted(
        by_name.values(), key=lambda entry: (-entry["items"], entry["name"])
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "method": RELATION_METHOD,
        "period": {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "basis": "Asia/Taipei date of COALESCE(published_at, collected_at)",
        },
        "categories": list(categories),
        "items": len(rows),
        "items_with_hit": with_hit,
        "hits": sum(entry["items"] for entry in names_out),
        "names": names_out,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, type=Path, help="stock.db copy")
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--category",
        action="append",
        help="news_items.category (repeatable; default domestic)",
    )
    parser.add_argument("--examples", type=int, default=3)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.until < args.since:
        parser.error("--until is before --since")
    if not args.db.is_file():
        parser.error(f"{args.db} is not a file")
    data = measure(
        args.db,
        args.since,
        args.until,
        tuple(args.category or ("domestic",)),
        args.examples,
    )
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                key: data[key]
                for key in ("method", "period", "items", "items_with_hit", "hits")
            }
            | {"names": len(data["names"])},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
