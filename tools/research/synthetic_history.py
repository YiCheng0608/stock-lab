"""A synthetic long-history database for timing the research tools (Issue #752).

The exploration tools (``explore_research``, ``trade_research``) read up to
twenty years of the research database, which may only be run once per
hypothesis (docs/spec/evidence.md 第 2 步的工具).  To measure their time and
memory without touching the research volume, this builds a database of the
same shape from a read-only copy of the production database (individual
stocks from 2024-09-30):

- **Calendar**: every weekday from ``--start`` (default 2004-02-11) to
  2024-09-27 is a synthetic session (no real historical calendar is read; a
  year has about 261 weekdays against about 245 sessions, an upper bound).
  The copy's own rows from 2024-09-30 on are kept as they are.
- **Tiles**: the copy's stock sessions from 2024-09-30 are one block, laid
  backwards from 2024-09-27 until ``--start`` (the synthetic session ``j``
  places before 2024-09-30 gets the block's session ``j`` places before its
  end, modulo its length).  Bars (every instrument type), chips, margin lists
  and corporate actions follow that date map; monthly revenues move by whole
  blocks of months, quarterly statements by whole years; the MOPS material
  information (``events``) by blocks of calendar days.  Prices jump at every
  seam, so the returns mean nothing: the database is for timing only.
- **Delisted**: ``--delisted`` clones of existing stocks (new ids, symbols
  ``X0001``…, every 33rd ``transferred``, the rest ``delisted``), each with a
  two- to eight-year slice of its source's synthetic rows ending by
  2024-09-27.
- Tables the research tools do not read (``EMPTY``) are created empty.

Next to ``stock.db`` it writes ``synthetic-db.json`` (``purpose`` is
``synthetic_scale``), never the research marker ``research-db.json``, so the
validation gate of the research tools refuses it.  It refuses a source that is
the production database (``evidence_lib.production_problem``: inside
``stock-lab-data`` or ``STOCK_DATA_DIR``, or the same file as production), an
output directory that (or any directory above it) holds ``research-db.json``,
one that already holds a ``stock.db``,
or one inside the production data directory.

Usage (docs/ops/RESEARCH_DB.md 研究工具的耗時與記憶體)::

    python tools/research/synthetic_history.py --src /src/stock.db --out /synth/full \
        [--start 2004-02-11] [--delisted 1000]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "research"))
import evidence_lib as lib  # noqa: E402

PURPOSE = "synthetic_scale"
MARKER_NAME = "synthetic-db.json"
RESEARCH_MARKER = "research-db.json"
DB_NAME = "stock.db"
COPY_FROM = date(2024, 9, 30)  # the production copy's first stock session
LAST = date(2024, 9, 27)  # the last synthetic session (the validation's end)
DEFAULT_START = date(2004, 2, 11)
DEFAULT_DELISTED = 1000
MIN_SPAN, MAX_SPAN = 500, 2000  # sessions of a delisted clone (two to eight years)
TRANSFERRED_EVERY = 33
MOPS = ("mops_material_information", "material_information")
# Not read by the research tools: created empty.
EMPTY = (
    "technical_features",
    "technical_indicators",
    "signals",
    "signal_evaluations",
    "signal_settlements",
    "data_quality",
    "ingestion_runs",
    "raw_payloads",
    "news_items",
    "news_llm_results",
    "news_projection_state",
    "group_daily_scores",
    "group_daily_score_archive",
    "candidate_runs",
    "daily_candidates",
    "candidate_llm_notes",
    "schedule_runs",
    "schedule_run_steps",
    "tracking_plans",
    "tracking_plan_sessions",
    "market_summaries",
    "strategy_levels",
    "action_tier_snapshots",
    "portfolio_positions",
)
# Dated tables: copied from COPY_FROM on, then tiled.
DATED = {
    "market_bars": "trading_date",
    "chip_snapshots": "trading_date",
    "margin_lists": "trading_date",
    "corporate_actions": "action_date",
    "monthly_revenues": "announcement_date",
    "fundamental_snapshots": "period_end",
    "events": "event_date",
}


def refusals(src: Path, out: Path, environ: dict[str, str]) -> list[str]:
    problems = []
    problem = lib.production_problem(src, environ)
    if problem:
        problems.append(f"source: {problem}")
    elif not src.is_file():
        problems.append(f"{src} does not exist")
    # The directory or any above it: /research/synth would write into the research volume.
    for folder in (out, *out.resolve().parents):
        if (folder / RESEARCH_MARKER).exists():
            problems.append(f"{folder} holds {RESEARCH_MARKER}: a research database")
            break
    if (out / DB_NAME).exists():
        problems.append(f"{out / DB_NAME} already exists")
    problem = lib.production_problem(out / DB_NAME, environ)
    if problem:
        problems.append(f"output: {problem}")
    return problems


def weekdays(first: date, last: date) -> list[date]:
    out, day = [], first
    while day <= last:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def date_map(block: list[date], calendar: list[date]) -> list[tuple[str, str]]:
    """(source, synthetic) for every synthetic session: counted back from the
    end of both, the block repeating."""

    n = len(block)
    return [
        (
            block[n - 1 - (j % n)].isoformat(),
            calendar[len(calendar) - 1 - j].isoformat(),
        )
        for j in range(len(calendar))
    ]


def _months(first: date, last: date) -> int:
    return (last.year - first.year) * 12 + last.month - first.month + 1


def _unit(seed: str) -> float:
    digest = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def clones(
    sources: list[int], count: int, calendar: list[date], first_id: int
) -> list[tuple[int, int, str, str]]:
    """(new id, source id, first day, last day): a deterministic slice each."""

    out = []
    if not sources or len(calendar) < MIN_SPAN:
        return out
    for k in range(count):
        span = MIN_SPAN + int(_unit(f"span:{k}") * (MAX_SPAN - MIN_SPAN))
        span = min(span, len(calendar))
        end = span - 1 + int(_unit(f"end:{k}") * (len(calendar) - span + 1))
        end = min(end, len(calendar) - 1)
        out.append(
            (
                first_id + k,
                sources[k % len(sources)],
                calendar[end - span + 1].isoformat(),
                calendar[end].isoformat(),
            )
        )
    return out


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f'pragma main.table_info("{table}")')]


def _copy(
    con: sqlite3.Connection,
    table: str,
    select: dict[str, str],
    tail: str,
    params: tuple = (),
    source: str = "src",
) -> int:
    """Insert into ``table`` every column but ``id``; ``select`` overrides a column's
    expression (``t`` is the source row)."""

    columns = [c for c in _columns(con, table) if c != "id"]
    exprs = [select.get(c, f't."{c}"') for c in columns]
    names = ", ".join(f'"{c}"' for c in columns)
    cursor = con.execute(
        f'insert into main."{table}" ({names}) select {", ".join(exprs)} '
        f'from {source}."{table}" t {tail}',
        params,
    )
    return cursor.rowcount


def build(
    src: Path,
    out: Path,
    start: date = DEFAULT_START,
    delisted: int = DEFAULT_DELISTED,
    progress=lambda text: None,
) -> dict[str, Any]:
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    partial = out / (DB_NAME + ".partial")
    if partial.exists():
        partial.unlink()
    con = sqlite3.connect(f"file:{partial.resolve()}", uri=True, isolation_level=None)
    con.execute("pragma journal_mode = off")
    con.execute("pragma synchronous = off")
    con.execute("pragma foreign_keys = off")
    con.execute("attach database ? as src", (f"file:{src.resolve()}?mode=ro",))
    if not _read_only(con):
        raise SystemExit("the source did not open read-only")
    schema = con.execute(
        "select type, name, tbl_name, sql from src.sqlite_master "
        "where sql is not null and name not like 'sqlite_%'"
    ).fetchall()
    analyzed = bool(
        con.execute(
            "select 1 from src.sqlite_master where name = 'sqlite_stat1'"
        ).fetchone()
    )
    con.execute("begin")
    for kind, _name, _table, sql in schema:
        if kind == "table":
            con.execute(sql)
    counts: dict[str, int] = {}
    for kind, table, _t, _s in schema:
        if kind != "table" or table in EMPTY:
            continue
        column = DATED.get(table)
        where, params = "", ()
        if column is not None:
            # Revenues by their month: a late filing for 2024-08 would clash
            # with the tile that lands on 2024-08.
            key = "revenue_month" if table == "monthly_revenues" else column
            first = COPY_FROM.replace(day=1) if key == "revenue_month" else COPY_FROM
            where, params = f' where "{key}" >= ?', (first.isoformat(),)
        counts[table] = con.execute(
            f'insert into main."{table}" select * from src."{table}"{where}', params
        ).rowcount
    progress(f"copied {counts}")

    block = [
        date.fromisoformat(day)
        for (day,) in con.execute(
            "select distinct mb.trading_date from src.market_bars mb "
            "join src.instruments i on i.id = mb.instrument_id "
            "where i.instrument_type = 'stock' and mb.trading_date >= ? order by 1",
            (COPY_FROM.isoformat(),),
        )
    ]
    calendar = weekdays(start, LAST)
    if not block or not calendar:
        raise SystemExit(
            "no stock session from 2024-09-30 in the source, or no calendar"
        )
    # One source day to several synthetic days: the key is (src, syn).
    con.execute("create temp table dmap (src text, syn text, primary key (src, syn))")
    con.executemany("insert into temp.dmap values (?, ?)", date_map(block, calendar))
    tiled: dict[str, int] = {}
    for table in ("market_bars", "chip_snapshots", "margin_lists", "corporate_actions"):
        column = DATED[table]
        tiled[table] = _copy(
            con,
            table,
            {column: "m.syn"},
            f'join temp.dmap m on m.src = t."{column}"',
        )
        progress(f"tiled {table}: {tiled[table]}")
    # Monthly revenues: whole blocks of the copy's months from 2024-09.
    months = con.execute(
        "select min(revenue_month), max(revenue_month) from src.monthly_revenues "
        "where revenue_month >= ?",
        (COPY_FROM.replace(day=1).isoformat(),),
    ).fetchone()
    tiled["monthly_revenues"] = 0
    tiled["fundamental_snapshots"] = 0
    if months[0]:
        width = _months(date.fromisoformat(months[0]), date.fromisoformat(months[1]))
        tiled["monthly_revenues"] = _tile_months(
            con,
            "monthly_revenues",
            width,
            ("revenue_month", "announcement_date"),
            start,
        )
    quarters = con.execute(
        "select min(period_end), max(period_end) from src.fundamental_snapshots "
        "where period_end >= ?",
        (COPY_FROM.isoformat(),),
    ).fetchone()
    if quarters[0]:
        width = _months(
            date.fromisoformat(quarters[0]), date.fromisoformat(quarters[1])
        )
        width = -(-width // 12) * 12  # whole years: the quarter of the year stays
        tiled["fundamental_snapshots"] = _tile_months(
            con,
            "fundamental_snapshots",
            width,
            ("period_end", "announcement_date"),
            start,
        )
    tiled["events"] = _tile_events(con, start)
    progress(f"tiled {tiled}")
    for kind, _name, _table, sql in schema:
        if kind == "index":
            con.execute(sql)
    progress("indexes")
    made = _delisted(con, calendar, delisted)
    progress(f"delisted clones {made}")
    con.execute("commit")
    if analyzed:  # the planner sees what it sees on the copy
        con.execute("analyze")
    con.execute("detach database src")
    facts = {
        table: con.execute(f'select count(*) from main."{table}"').fetchone()[0]
        for table in DATED
    }
    per_day = con.execute(
        "select count(*) * 1.0 / count(distinct mb.trading_date) from market_bars mb "
        "join instruments i on i.id = mb.instrument_id "
        "where i.instrument_type in ('stock', 'ipo')"
    ).fetchone()[0]
    con.close()
    final = out / DB_NAME
    os.replace(partial, final)
    marker = {
        "purpose": PURPOSE,
        "issue": 752,
        "start": start.isoformat(),
        "last_synthetic": LAST.isoformat(),
        "block_sessions": len(block),
        "synthetic_sessions": len(calendar),
        "delisted_clones": made,
        "rows": facts,
        "stock_bars_per_day": round(per_day or 0.0, 1),
    }
    (out / MARKER_NAME).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        **marker,
        "db": str(final),
        "bytes": final.stat().st_size,
        "seconds": round(time.monotonic() - started, 1),
    }


def _read_only(con: sqlite3.Connection) -> bool:
    try:
        con.execute("create table src._probe (x)")
    except sqlite3.OperationalError:
        return True
    con.execute("drop table src._probe")
    return False


def _tile_months(
    con: sqlite3.Connection,
    table: str,
    width: int,
    columns: tuple[str, ...],
    start: date,
) -> int:
    """Copies of the rows from 2024-09 moved back by ``k × width`` months until
    the first is before ``start`` (only rows whose first column is ≥ ``start``
    and < 2024-09-30)."""

    total, k = 0, 1
    floor = COPY_FROM.replace(day=1).isoformat()
    first = con.execute(
        f'select min("{columns[0]}") from src."{table}" where "{columns[0]}" >= ?',
        (floor,),
    ).fetchone()[0]
    while True:
        shift = f"-{k * width} months"
        moved = {c: f"date(t.\"{c}\", '{shift}')" for c in columns}
        key = moved[columns[0]]
        total += _copy(
            con,
            table,
            moved,
            f'where t."{columns[0]}" >= ? and {key} >= ? and {key} < ? '
            "and t.announcement_date is not null",
            (first, start.isoformat(), floor),
        )
        if minus_months(date.fromisoformat(first), k * width) <= start:
            break
        k += 1
    return total


def minus_months(day: date, months: int) -> date:
    """The first of the month ``months`` before ``day``'s month (a lower bound
    of SQLite's ``date(day, '-N months')``)."""

    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def _tile_events(con: sqlite3.Connection, start: date) -> int:
    """The MOPS list's calendar days as one block, laid back from 2024-09-29."""

    first, last = con.execute(
        "select min(event_date), max(event_date) from src.events "
        "where source = ? and event_type = ? and instrument_id is not null",
        MOPS,
    ).fetchone()
    if not first:
        return 0
    width = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    end = COPY_FROM - timedelta(days=1)
    total, k = 0, 1
    while True:
        # Synthetic day = source day − (last − end) − (k − 1) × width.
        offset = (date.fromisoformat(last) - end).days + (k - 1) * width
        shifted = f"date(t.event_date, '-{offset} days')"
        total += _copy(
            con,
            "events",
            {"event_date": shifted},
            f"where t.source = ? and t.event_type = ? and t.instrument_id is not null "
            f"and {shifted} >= ?",
            (*MOPS, start.isoformat()),
        )
        if date.fromisoformat(first) - timedelta(days=offset) <= start:
            break
        k += 1
    return total


def _delisted(con: sqlite3.Connection, calendar: list[date], count: int) -> int:
    sources = [
        row[0]
        for row in con.execute(
            "select id from main.instruments where instrument_type = 'stock' "
            "and status = 'active' order by id"
        )
    ]
    first_id = con.execute("select max(id) from main.instruments").fetchone()[0] + 1
    plan = clones(sources, count, calendar, first_id)
    if not plan:
        return 0
    con.execute(
        "create temp table clones (new_id integer primary key, src_id integer, "
        "first text, last text)"
    )
    con.executemany("insert into temp.clones values (?, ?, ?, ?)", plan)
    columns = [c for c in _columns(con, "instruments") if c != "id"]
    exprs = {
        "symbol": "printf('X%04d', c.new_id - ?)",
        "name": "'合成下市' || printf('%04d', c.new_id - ?)",
        "status": (
            f"case when (c.new_id - ?) % {TRANSFERRED_EVERY} = 0 "
            "then 'transferred' else 'delisted' end"
        ),
        "is_watchlisted": "0",
    }
    select = ", ".join(exprs.get(c, f't."{c}"') for c in columns)
    offset = first_id - 1
    con.execute(
        f"insert into main.instruments (id, {', '.join(chr(34) + c + chr(34) for c in columns)}) "
        f"select c.new_id, {select} from temp.clones c "
        "join main.instruments t on t.id = c.src_id",
        tuple(offset for c in columns if c in ("symbol", "name", "status")),
    )
    for table, column in (
        ("market_bars", "trading_date"),
        ("chip_snapshots", "trading_date"),
        ("corporate_actions", "action_date"),
        ("monthly_revenues", "announcement_date"),
        ("fundamental_snapshots", "announcement_date"),
        ("events", "event_date"),
    ):
        _copy(
            con,
            table,
            {"instrument_id": "c.new_id"},
            f"join temp.clones c on c.src_id = t.instrument_id "
            f'and t."{column}" between c.first and c.last',
            source="main",
        )
    return len(plan)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--src", required=True, help="a read-only copy of production")
    parser.add_argument("--out", required=True, help="a new directory (task volume)")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--delisted", type=int, default=DEFAULT_DELISTED)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    src, out = Path(args.src), Path(args.out)
    problems = refusals(src, out, dict(os.environ))
    if not problems and not date(1990, 1, 1) <= args.start < COPY_FROM:
        problems.append(f"--start {args.start} is not before {COPY_FROM}")
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    line = build(src, out, args.start, args.delisted, progress)
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
