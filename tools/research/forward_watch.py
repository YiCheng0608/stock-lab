"""The frozen forward entries of the forward-watch objects (#868).

docs/spec/evidence.md 前瞻監測與下架: every object (a hypothesis whose
validation was ``前瞻觀察``, or a strategy in the product) is followed from its
registration day on the data no one used to choose it, each month in the same
report as H1 (#699).  The first object is X4 (#867's validation, comment
7033243199); the second H2, explore_research's X2, which passed its
validation (#864 comment 7043710015, kind ``通過驗證`` until the user decides
on the product, #875); the third H2 again, in the product from 2026-11-21
(key ``H2-product``, kind ``已進產品``, #902; the old row stays and runs on,
and the reports name both H2); the fourth round 10's F2
(round10_research 第 1 版, #944 validation 7072993427, kind ``前瞻觀察`` from
2026-11-22, #949); the fifth round 15's P2 (round15_research 第 1 版, #986
validation 7097870215, kind ``前瞻觀察`` from 2026-11-23, #990); the sixth
round 17's A1 (round17_research 第 1 版, #1011 validation 7113410582, kind
``前瞻觀察`` from 2026-11-24, #1013).  Nothing here is a command-line option:
``WATCHES`` holds each object's frozen entry, its definition is the one its own tool ran (imported,
not copied, and refused when that tool's ``definitions_sha256`` is not the
frozen one), and the golden test of its output fails on any change.

The engine, the costs and the excess are those of 前瞻驗證 H1's ``--window
forward``: signal dates T from the first session on or after ``since`` to the
session before the cutoff, T+1's open to the K-th session's close
(``portfolio_research.simulate``), the benchmark the same engine over the
day's whole population (``evidence_lib.universe``), TAIEX only listed.  The
bars before ``since`` are read for the features only, as far back as the
source tool reads a later segment: ``WARMUP_CALENDAR_DAYS`` for
explore_research, the copy from ``LOAD_FROM`` for round10_research (F2's
``vol_720`` needs 721 bars), round15_research and round17_research.

P2 and A1 trade on event days (``round14_research.quarter_events``, the four
statutory deadlines) on X7's one account (``explore_research.simulate_events``,
held to the next event day), not on every session: its signal dates are the
event days from the first session on or after ``since`` to the session before
the cutoff (an event day before ``since`` is not bought, its list is not put
in front), the equity starts the session after the first of them, and until
there is one the report says ``樣本不足（起日後還沒有事件日）`` and the next
statutory deadline.  Their reference populations (P2 第 7 點, A1 第 8 點)
are listed, not judged.  The verdict is
``portfolio_research.forward_judge`` on every session to the cutoff with
``min_days`` 60: before 60 sessions it is ``樣本不足`` and the numbers are no
verdict.  What follows a verdict is the kind's (``KIND_NOTES``): only a
strategy in the product is proposed for delisting on ``輸給基準``.

A next object registers its entry in ``WATCHES`` (its source tool, code,
definition hash, since and kind), adds an engine to ``ENGINES`` if its tool's
rule is not one of them, and gets a golden test; the command and the report
stay the same.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import explore_research as er  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round10_research as r10  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402
import round17_research as r17  # noqa: E402

VERSION = 1
DESIGN = "868"
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
RAW_DIR_NAME = "raw"
MIN_DAYS = (
    60  # 前瞻監測與下架: judged from 60 sessions on (the same M as H1 historical)
)
WARMUP_CALENDAR_DAYS = er.WARMUP_CALENDAR_DAYS
WATCH = "前瞻觀察"
PRODUCT = "已進產品"
PASSED = "通過驗證"  # #875 決定 7044311598: passed, the user not yet decided
KIND_NOTES = {
    WATCH: "前瞻觀察的對象：只當紀錄，不判下架，判到「輸給基準」也只記錄；"
    "之後的數字再好也不改成「通過」、不進產品",
    PRODUCT: "已進產品的策略：滿 60 日起每月判一次，判到「輸給基準」由統籌在 #1 提案下架；"
    "其餘判定只列出",
    PASSED: "通過驗證、待使用者決定進不進產品的策略：只當紀錄，不判下架；判到「輸給基準」時由統籌"
    "在 #1 的進產品提案補一則（是事實，不是下架提案），其餘判定只記錄",
}

# The frozen entries (#868).  ``definitions_sha256`` is the source tool's at the
# reports that put the object here; ``since`` its registration day.
WATCHES: dict[str, dict[str, Any]] = {
    "X4": {
        "kind": WATCH,
        "source": "explore_research",
        "source_version": 2,
        "code": "X4",
        "definitions_sha256": (
            "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"
        ),
        "since": date(2026, 11, 20),
        "min_days": MIN_DAYS,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7033243199"
        ),
    },
    # X2 passed both segments (#864 7041131687, 7043710015) and is H2 (#875):
    # the same frozen definition, followed from the day its validation was
    # written to the ledger.  The user's product decision adds a row, never
    # edits this one (#875 決定 7044311598).
    "H2": {
        "kind": PASSED,
        "source": "explore_research",
        "source_version": 2,
        "code": "X2",
        "definitions_sha256": (
            "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"
        ),
        "since": date(2026, 11, 20),
        "min_days": MIN_DAYS,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/864#issuecomment-7043710015"
        ),
    },
    # The user put H2 in the product (#1 7044998169); its list went live on
    # 2026-11-21 (v1.2.74, #1 7050216934, #882 7050234452).  The same frozen X2, followed from
    # that day as a product strategy (#902); the key differs from the row above
    # (a dict key is unique), the code in the reports is still H2 (``display``).
    "H2-product": {
        "kind": PRODUCT,
        "source": "explore_research",
        "source_version": 2,
        "code": "X2",
        "definitions_sha256": (
            "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"
        ),
        "since": date(2026, 11, 21),
        "min_days": MIN_DAYS,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7050216934"
        ),
    },
    # Round 10's F2 was judged 前瞻觀察 on its validation (#944 7072993427,
    # 決定 7073015041): round10_research 第 1 版's definition, followed from
    # the day the validation was written to the ledger (finished_at
    # 2026-11-22T02:33:50Z, #949).
    "F2": {
        "kind": WATCH,
        "source": "round10_research",
        "source_version": 1,
        "code": "F2",
        "definitions_sha256": (
            "453f65124f86b5643ef1ce79dd079530a603e9434ed719a5f942090eeaf85dd9"
        ),
        "since": date(2026, 11, 22),
        "min_days": MIN_DAYS,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/944#issuecomment-7072993427"
        ),
    },
    # Round 15's P2 was judged 前瞻觀察 on its validation (#986 7097870215,
    # 決定 7097039382): round15_research 第 1 版's definition, followed from
    # the day the validation was written to the ledger (finished_at
    # 2026-11-23T10:21:58Z, #990).  Its first event day from then on is
    # 2027-03-31 (2026Q4's deadline); 2026-11-16's (2026Q3) is before the start.
    "P2": {
        "kind": WATCH,
        "source": "round15_research",
        "source_version": 1,
        "code": "P2",
        "definitions_sha256": (
            "dbbeb3e2626bbd4642c7b8732da3f376c9905e50575bee8f2dbed60273ea824e"
        ),
        "since": date(2026, 11, 23),
        "min_days": MIN_DAYS,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/986#issuecomment-7097870215"
        ),
    },
    # Round 17's A1 was judged 前瞻觀察 on its validation (#1011 7113410582):
    # round17_research 第 1 版's definition, followed from the day the
    # validation was written to the ledger: finished_at 2026-11-23T20:39:54Z,
    # 2026-11-24 04:39 in Taipei, the sessions' calendar (#1013).  Its first
    # event day from then on is 2027-03-31 (2026Q4's deadline); 2026-11-16's
    # (2026Q3) is before the start.
    "A1": {
        "kind": WATCH,
        "source": "round17_research",
        "source_version": 1,
        "code": "A1",
        "definitions_sha256": (
            "505666ec2537fdb6b77086ce6b633bd6b58b4a61de8b7aa5f6213ef18d4c95df"
        ),
        "since": date(2026, 11, 24),
        "min_days": MIN_DAYS,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/1011#issuecomment-7113410582"
        ),
    },
}
SOURCES = {
    "explore_research": er,
    "round10_research": r10,
    "round15_research": r15,
    "round17_research": r17,
}
# The lists an event-day object's list is overlapped with (P2 第 6 點, A1 第 7
# 點), listed only: the keys of its source's ``OVERLAP_NOTE``
EVENT_OVERLAPS = {"P2": ("P2_K2", "P2_X4"), "A1": ("A1_X8",)}


def display(name: str) -> str:
    """The object's code in its reports: the ``WATCHES`` key up to its first
    ``-`` (``H2-product`` is H2, #875 決定 7044311598 第 3 點)."""

    return name.split("-", 1)[0]


def definition(name: str) -> dict[str, Any]:
    """The object's definition as its source tool holds it."""

    entry = WATCHES[name]
    return SOURCES[entry["source"]].HYPOTHESES[entry["code"]]


def source_problems(name: str) -> list[str]:
    """Refuse when the source tool is no longer the one that judged the object."""

    entry = WATCHES[name]
    source = SOURCES[entry["source"]]
    problems = []
    if source.VERSION != entry["source_version"]:
        problems.append(
            f"{entry['source']} is version {source.VERSION}, "
            f"{name} was judged by version {entry['source_version']}"
        )
    if source.definitions_sha256() != entry["definitions_sha256"]:
        problems.append(
            f"{entry['source']}'s definitions_sha256 is not the one {name} was judged by"
        )
    return problems


# --- the engines ---------------------------------------------------------------


def _signal_window(
    sessions: list[date], since: date, cutoff: date | None
) -> tuple[int, list[int]]:
    """The last session valued and the signal dates' indexes: from the first
    session on or after ``since`` to the session before the last."""

    position = {day: index for index, day in enumerate(sessions)}
    if cutoff is not None and cutoff not in position:
        raise SystemExit(f"cutoff {cutoff} is not a market session")
    last = position[cutoff] if cutoff is not None else len(sessions) - 1
    return last, [at for at in range(last) if sessions[at] >= since]


def _empty_run(panel: lib.Panel, last: int, signals: list[int]) -> dict[str, Any]:
    sessions = panel.sessions
    return {
        "panel": panel,
        "cutoff": sessions[last].isoformat() if sessions else None,
        "signal_days": len(signals),
        "dates": [],
        "rows": [],
        "positions": [],
        "equity": ([], []),
        "returns": ([], []),
        "taiex": [],
        "invested": ([], []),
        "turnover": ([], []),
        "counts": {},
        "coverage": {},
    }


def _simulated(
    run: dict[str, Any],
    code: str,
    spec: dict[str, Any],
    planned: Any,
    quote: Callable,
    first: int,
    last: int,
) -> dict[str, Any]:
    """``simulate`` for the picks and the population from ``first`` to
    ``last`` (both engines: the H1 ``--window forward`` rule)."""

    panel = run["panel"]
    mine = pr.simulate(planned.picks, quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(planned.population, quote, first, last, spec["hold"], None)
    run.update(
        {
            "dates": panel.sessions[first : last + 1],
            "rows": planned.rows,
            "positions": mine.positions,
            "equity": (mine.equity, population.equity),
            "returns": (
                pr.daily_returns(mine.equity),
                pr.daily_returns(population.equity),
            ),
            "taiex": er._taiex(panel, first, last),
            "invested": (mine.invested, population.invested),
            "turnover": (er._turnover(mine), er._turnover(population)),
            "counts": {code: dict(mine.counts), POPULATION: dict(population.counts)},
            "coverage": planned.coverage,
            "win": er.win_rate(mine),
        }
    )
    return run


def explore_daily(
    db: Path, entry: dict[str, Any], since: date, cutoff: date | None, out: Path
) -> dict[str, Any]:
    """An explore_research ``daily`` hypothesis forward: its ``plan`` (the
    filters, subset and keys of the registration) on the signal dates from
    ``since``, ``simulate`` for it and the population."""

    spec = SOURCES[entry["source"]].HYPOTHESES[entry["code"]]
    if spec["rule"] != "daily":
        raise SystemExit(f"{entry['code']} is not a daily hypothesis")
    latest = pr.copy_facts(db)["latest"]
    end = cutoff or (date.fromisoformat(latest) if latest else since)
    ctx = er.load_context(
        db, since - timedelta(days=WARMUP_CALENDAR_DAYS), end, out / RAW_DIR_NAME
    )
    panel = ctx.market.panel
    last, signals = _signal_window(panel.sessions, since, cutoff)
    run = _empty_run(panel, last, signals)
    if not signals:
        return run
    first = signals[0] + 1
    planned = er.plan(ctx, spec, first, last)
    return _simulated(run, entry["code"], spec, planned, ctx.quote, first, last)


def round10_portfolio(
    db: Path, entry: dict[str, Any], since: date, cutoff: date | None, out: Path
) -> dict[str, Any]:
    """A round10_research portfolio hypothesis (F2) forward: the copy read
    from ``LOAD_FROM`` (its own rule: F2's ``vol_720`` needs 721 bars, more
    than ``WARMUP_CALENDAR_DAYS``), its ``plan`` (the half, the two ranks, the
    mean rank, and the overlap with X2's list) on the signal dates from
    ``since``, ``simulate`` for it and the population."""

    code = entry["code"]
    spec = r10.HYPOTHESES[code]
    if spec["engine"] != r10.PORTFOLIO or spec["rule"] != "daily":
        raise SystemExit(f"{code} is not a daily portfolio hypothesis")
    latest = pr.copy_facts(db)["latest"]
    end = cutoff or (date.fromisoformat(latest) if latest else since)
    ctx = r10.load(db, r10.LOAD_FROM, end, out / RAW_DIR_NAME)
    panel = ctx.panel
    last, signals = _signal_window(panel.sessions, since, cutoff)
    run = _empty_run(panel, last, signals)
    run["overlap"] = r10.overlap_summary({})
    if not signals:
        return run
    first = signals[0] + 1
    planned = r10.plan(ctx, spec, code, first, last)
    run["overlap"] = r10.overlap_summary(planned.overlap)
    return _simulated(run, code, spec, planned, ctx.quote, first, last)


def round15_context(db: Path, end: date, raw_dir: Path) -> r15.Context:
    """``round15_research.load`` without the member table: the same panel
    from ``LOAD_FROM`` (``explore_research.load_context``), P2's statements and
    the instruments' status.  The table (#779) is only P1's industries, and it
    lies beside the research DB, not the copy (#990)."""

    base = er.load_context(db, r15.LOAD_FROM, end, raw_dir)
    return r15.Context(
        base,
        r15.load_statements(db, base.market.panel.series, end),
        r15.load_statuses(db),
    )


def next_deadline(sessions: list[date], since: date, last: int) -> date:
    """The first statutory deadline (``round14_research.DEADLINES``) on or
    after ``since`` and after the last session that can be a signal date
    (``last − 1``): the next event day is the first Monday～Friday session on
    or after it."""

    after = sessions[last - 1] if last >= 1 else None
    year = since.year
    while True:
        for month, day, _end_month, _offset in r14.DEADLINES:
            deadline = date(year, month, day)
            if deadline >= since and (after is None or deadline > after):
                return deadline
        year += 1


def _events(
    source: Any, ctx: Any, code: str, since: date, cutoff: date | None
) -> dict[str, Any]:
    """An event-day hypothesis forward on ``ctx`` (its source's own load): the
    event days of ``round14_research.quarter_events`` from ``since`` on, the
    source's ``planner`` and ``engines``: X7's one account for it, the
    population and the reference, each held to the next event day."""

    spec = source.HYPOTHESES[code]
    if spec["engine"] != source.EVENTS or spec["rule"] != "quarterly":
        raise SystemExit(f"{code} is not a quarterly event-day hypothesis")
    panel = ctx.panel
    sessions = panel.sessions
    last, _signals = _signal_window(sessions, since, cutoff)
    events = [
        at
        for at, _quarter in r14.quarter_events(sessions)
        if at < last and sessions[at] >= since
    ]
    run = _empty_run(panel, last, events)
    run["next_deadline"] = next_deadline(sessions, since, last)
    run["reference_returns"] = []
    run["overlaps"] = {key: r10.overlap_summary({}) for key in EVENT_OVERLAPS[code]}
    run["rebalances"] = []
    if not events:
        return run
    first = events[0] + 1
    planned = source.planner(code)(ctx, spec, first, last)
    mine, population, reference = source.engines(ctx, code, planned, first, last)
    for event in planned.rebalances:
        s = sessions.index(date.fromisoformat(event["signal_date"])) + 1
        event["invested"] = mine.invested[s - first] if s <= last else None
    run.update(
        {
            "dates": sessions[first : last + 1],
            "rows": planned.rows,
            "positions": mine.positions,
            "equity": (mine.equity, population.equity),
            "returns": (
                pr.daily_returns(mine.equity),
                pr.daily_returns(population.equity),
            ),
            "reference_returns": pr.daily_returns(reference.equity),
            "taiex": er._taiex(panel, first, last),
            "invested": (mine.invested, population.invested),
            "turnover": (er._turnover(mine), er._turnover(population)),
            "counts": {code: dict(mine.counts), POPULATION: dict(population.counts)},
            "coverage": planned.coverage,
            "win": er.win_rate(mine),
            "overlaps": {
                key: r10.overlap_summary(by_year)
                for key, by_year in planned.overlap.items()
            },
            "rebalances": planned.rebalances,
        }
    )
    return run


def _end(db: Path, since: date, cutoff: date | None) -> date:
    latest = pr.copy_facts(db)["latest"]
    return cutoff or (date.fromisoformat(latest) if latest else since)


def round15_events(
    db: Path, entry: dict[str, Any], since: date, cutoff: date | None, out: Path
) -> dict[str, Any]:
    """A round15_research event-day hypothesis (P2) forward: the copy read
    from ``LOAD_FROM`` (``round15_context``), ``plan_p2`` (``margins_up``, 20
    by the hash) and ``round15_research.engines`` (``_events``)."""

    ctx = round15_context(db, _end(db, since, cutoff), out / RAW_DIR_NAME)
    return _events(r15, ctx, entry["code"], since, cutoff)


def round17_events(
    db: Path, entry: dict[str, Any], since: date, cutoff: date | None, out: Path
) -> dict[str, Any]:
    """A round17_research event-day hypothesis (A1) forward: the copy read by
    ``round17_research.load`` from its ``LOAD_FROM`` (the panel, A1's
    statements and stock dividends, the statuses; no member table),
    ``plan_a1`` (``net_issue`` small first, 20, X8's overlap) and
    ``round17_research.engines`` (``_events``)."""

    ctx = r17.load(db, r17.LOAD_FROM, _end(db, since, cutoff), out / RAW_DIR_NAME)
    return _events(r17, ctx, entry["code"], since, cutoff)


ENGINES: dict[str, Callable[..., dict[str, Any]]] = {
    "explore_research": explore_daily,
    "round10_research": round10_portfolio,
    "round15_research": round15_events,
    "round17_research": round17_events,
}
# The source's columns of picks.csv and lines of 資料覆蓋 (each its own tool's)
PICK_FIELDS: dict[str, Callable[[str, dict[str, Any]], tuple[str, ...]]] = {
    "explore_research": lambda code, spec: er.used_features(spec),
    "round10_research": lambda code, spec: r10.PICK_FIELDS[code],
    "round15_research": lambda code, spec: r15.PICK_FIELDS[code],
    "round17_research": lambda code, spec: r17.PICK_FIELDS[code],
}
COVERAGE_LINES: dict[str, Callable[[str, dict[str, Any]], list[str]]] = {
    "explore_research": er.coverage_lines,
    "round10_research": r10.portfolio_coverage_lines,
    "round15_research": r15.coverage_lines,
    "round17_research": r17.coverage_lines,
}


REFERENCE = "reference"


# --- the run ---------------------------------------------------------------------


def study(run: dict[str, Any], name: str, min_days: int) -> dict[str, Any]:
    mine, others = run["returns"]
    taiex = run["taiex"]
    excess = {
        TAIEX: pr.excess_metrics([a - b for a, b in zip(mine, taiex) if b is not None]),
        POPULATION: pr.excess_metrics([a - b for a, b in zip(mine, others)]),
    }
    if "reference_returns" in run:  # P2 第 7 點, A1 第 8 點: listed, not judged
        excess[REFERENCE] = pr.excess_metrics(
            [a - b for a, b in zip(mine, run["reference_returns"])]
        )
    curves = {
        TAIEX: pr.curve_metrics([v for v in taiex if v is not None], [1.0], [0.0]),
        name: pr.curve_metrics(mine, run["invested"][0], run["turnover"][0]),
        POPULATION: pr.curve_metrics(others, run["invested"][1], run["turnover"][1]),
    }
    return {
        "days": len(run["dates"]),
        "min_days": min_days,
        "verdict": pr.forward_judge(excess[POPULATION], min_days),
        "excess": excess,
        "absolute": {
            "days": len(mine),
            "mean": statistics.fmean(mine) if mine else None,
        },
        "curves": curves,
        "win": run.get("win"),
        "counts": run["counts"],
        "coverage": run["coverage"],
    }


def run_watch(
    db: Path,
    name: str,
    out: Path,
    cutoff: date | None = None,
    since: date | None = None,
    command: str = "",
) -> dict[str, Any]:
    """Run object ``name`` forward and write ``out``.

    ``since`` replaces the frozen start for the tests only; the command line
    has no way to set it.
    """

    started = time.monotonic()
    entry = WATCHES[name]
    start = since or entry["since"]
    out.mkdir(parents=True, exist_ok=True)
    run = ENGINES[entry["source"]](db, entry, start, cutoff, out)
    code = display(name)
    # the engine counts under the source's code (X2); the report under the
    # object's (H2, also for H2-product: ``display``), as its curve and its
    # equity column
    run["counts"] = {
        (code if key == entry["code"] else key): value
        for key, value in run["counts"].items()
    }
    dates = run["dates"]
    spec = definition(name)
    result = {
        "version": VERSION,
        "design": DESIGN,
        "watch": name,
        "kind": entry["kind"],
        "note": KIND_NOTES[entry["kind"]],
        "entry": entry,
        "definition": spec,
        "command": command,
        "tool_commit": er.tool_commit(),
        "copy": pr.copy_facts(db),
        "rule": {
            "slippage_bps": pr.SLIPPAGE * 10_000,
            "fee": pr.FEE,
            "tax": pr.TAX,
            "min_t": pr.MIN_T,
        },
        "since": start.isoformat(),
        "cutoff": run["cutoff"],
        "first_signal": run["rows"][0]["signal_date"] if run["rows"] else None,
        "first_session": dates[0].isoformat() if dates else None,
        "last_session": dates[-1].isoformat() if dates else None,
        "signal_days": run["signal_days"],
        **study(run, code, entry["min_days"]),
    }
    if "overlap" in run:  # F2 第 6 點: its list's overlap with H2's, listed only
        result["overlap"] = run["overlap"]
    if "next_deadline" in run:  # the event-day engine (P2, A1)
        result["next_deadline"] = run["next_deadline"].isoformat()
        # P2 第 6 點 (K2's and X4's), A1 第 7 點 (X8's): listed only
        result["overlaps"] = run["overlaps"]
        result["rebalances"] = run["rebalances"]
    result["elapsed_seconds"] = time.monotonic() - started
    result["peak_memory_gb"] = lib._load("backtest_research").peak_memory_gb()
    write_outputs(out, result, run)
    return {
        "out": str(out.resolve()),
        "watch": name,
        "days": result["days"],
        "min_days": result["min_days"],
        "verdict": result["verdict"],
        "elapsed_seconds": round(result["elapsed_seconds"], 1),
    }


# --- the report ------------------------------------------------------------------

VOLATILE_KEYS = ("command", "tool_commit", "elapsed_seconds", "peak_memory_gb")


def _pct(value: float | None, digits: int = 2) -> str:
    return lib.pct(value, digits)


def _t(value: float | None) -> str:
    return lib.num(value, 2)


def markdown(result: dict[str, Any]) -> str:
    name, entry, spec = display(result["watch"]), result["entry"], result["definition"]
    days, threshold = result["days"], result["min_days"]
    e, a = result["excess"], result["absolute"]
    events = "next_deadline" in result  # the event-day engine (P2, A1)
    if events and not result["signal_days"]:
        verdict = (
            f"**樣本不足（起日後還沒有事件日）**：累積 {days}／{threshold} 日，下一個事件日 "
            f"{result['next_deadline']}（法定期限；當天或之後的第一個週一～週五交易日），"
            f"數字不是判定，滿 {threshold} 日才判定"
        )
    elif result["verdict"] == "樣本不足":
        verdict = (
            f"**樣本不足（累積 {days}／{threshold} 日）**：數字不是判定，滿 {threshold} 日"
            "才判定"
        )
    else:
        verdict = f"**{result['verdict']}**（累積 {days} 日，`forward_judge`）"
    if events:
        hold = ""  # the label says it: 持有到下一個事件日
        trading = (
            "- 進出與成本：事件日 T 收盤後選名單，T+1 開盤買（+5 bps、手續費 0.1425%），"
            "下一個事件日收盤賣（−5 bps、手續費、證交稅 0.3%），一個帳戶（X7，"
            "`explore_research.simulate_events`）；基準是同一帳戶規則、同一組事件日的全部母體"
        )
        window = (
            f"- 窗口：前瞻起日 {result['since']}（之前的資料只當暖機，起日以前的事件日不買），"
            f"第一個事件日 {result['first_signal'] or '—'}（事件日 {result['signal_days']} 個），"
            f"下一個法定期限 {result['next_deadline']}；有淨值的交易日 "
            f"{result['first_session'] or '—'}～{result['last_session'] or '—'}，"
            f"cutoff {result['cutoff'] or '—'}"
        )
    else:
        hold = f"、K＝{spec['hold']}"
        trading = (
            "- 進出與成本同「前瞻驗證 H1」：T+1 開盤買（+5 bps、手續費 0.1425%），成交那根算第 1 根、"
            f"第 {spec['hold']} 根收盤賣（−5 bps、手續費、證交稅 0.3%），{spec['hold']} 份子帳戶輪替；"
            "基準是同一引擎的每日全部母體"
        )
        window = (
            f"- 窗口：前瞻起日 {result['since']}（之前的資料只當暖機），第一個訊號日 "
            f"{result['first_signal'] or '—'}；有淨值的交易日 {result['first_session'] or '—'}"
            f"～{result['last_session'] or '—'}，cutoff {result['cutoff'] or '—'}"
        )
    lines = [
        f"# {name} {entry['kind']}的前瞻紀錄（forward_watch 第 {result['version']} 版，"
        f"#{result['design']}）",
        "",
        # the TAIEX excess first, then the population's (前瞻監測與下架「每月」)
        f"- 對加權指數超額（只列出）：日均 {_pct(e[TAIEX]['mean'], 3)}，t {_t(e[TAIEX]['t'])}，"
        f"{e[TAIEX]['days']} 日",
        f"- 對母體超額：日均 {_pct(e[POPULATION]['mean'], 3)}，t {_t(e[POPULATION]['t'])}，"
        f"累積 {days} 日",
        f"- 判定：{verdict}；{result['note']}",
        f"- 定義：{entry['source']} 第 {entry['source_version']} 版的 {entry['code']}"
        f"（{spec['label']}；N＝{spec['top']}{hold}），定義雜湊 "
        f"`{entry['definitions_sha256']}`；登記 {entry['registered']}",
        window,
        f"- 副本：最新交易日 {result['copy']['latest']}，alembic `{result['copy']['alembic']}`，"
        f"檔案時間 {result['copy']['mtime']}",
        trading,
        f"- 判定表（由上往下）：樣本不足（< {threshold} 日）→ 通過（超額日均 > 0 且 t ≥ 2）"
        "→ 輸給基準（< 0 且 t ≤ −2）→ 方向一致但不顯著（> 0）→ 沒有優勢",
        f"- 耗時 {result.get('elapsed_seconds', 0):.0f} 秒，峰值記憶體 "
        f"{lib.num(result.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{result['command']}`",
        "",
        "## 數字（至今）",
        "",
        "| 量 | 日數 | 日均 | 年化 | t |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| 超額（對加權指數，只列出） | {e[TAIEX]['days']} | {_pct(e[TAIEX]['mean'], 3)} "
        f"| {_pct(e[TAIEX]['annual'])} | {_t(e[TAIEX]['t'])} |",
        f"| 超額（對母體） | {e[POPULATION]['days']} | {_pct(e[POPULATION]['mean'], 3)} "
        f"| {_pct(e[POPULATION]['annual'])} | {_t(e[POPULATION]['t'])} |",
        *(
            [
                f"| 超額（對對照基準，只列出） | {e[REFERENCE]['days']} "
                f"| {_pct(e[REFERENCE]['mean'], 3)} | {_pct(e[REFERENCE]['annual'])} "
                f"| {_t(e[REFERENCE]['t'])} |"
            ]
            if REFERENCE in e
            else []
        ),
        f"| 絕對報酬（扣成本，只列出） | {a['days']} | {_pct(a['mean'], 3)} "
        f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
        "",
        "## 資金曲線（只列出）",
        "",
        "| 組合 | 日數 | 年化報酬 | 年化波動 | 最大回撤 | 平均投入 | 年化換手 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = {TAIEX: "加權指數（價格指數）", name: name, POPULATION: "母體（基準）"}
    for key in (TAIEX, name, POPULATION):
        c = result["curves"][key]
        held = (
            "| — | — |"
            if key == TAIEX
            else f"| {_pct(c.get('invested'), 1)} | {lib.num(c.get('turnover'), 1)} |"
        )
        lines.append(
            f"| {labels[key]} | {c['days']} | {_pct(c.get('annual'))} "
            f"| {_pct(c.get('volatility'))} | {_pct(c.get('max_drawdown'))} " + held
        )
    counts = result["counts"].get(name, {})
    win = result.get("win") or {"rate": None, "won": 0, "bought": 0, "unsold": 0}
    lines += [
        "",
        f"勝率（買進的每一筆，期末未賣以最後收盤計）：{_pct(win['rate'], 1)}"
        f"（{win['won']:,}／{win['bought']:,}，期末未賣 {win['unsold']:,}）。",
        f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
        f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
        f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
        f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
        "",
    ]
    if "overlap" in result:
        o = result["overlap"]
        lines += [
            "## 和 H2 的重疊（只列出）",
            "",
            r10.OVERLAP_NOTE + "。",
            "",
            f"前瞻起日至今平均：{_pct(o['mean'], 1)}（{o['days']:,} 個訊號日）。",
            "",
        ]
    if events:
        notes = SOURCES[entry["source"]].OVERLAP_NOTE
        lines += [
            f"{notes[entry['code'] + '_reference']}。",
            "",
            "## 名單的重疊（只列出）",
            "",
        ]
        for key in EVENT_OVERLAPS[entry["code"]]:
            o = result["overlaps"][key]
            lines += [
                f"- {notes[key]}。前瞻起日至今平均：{_pct(o['mean'], 1)}"
                f"（{o['days']:,} 個事件日）。",
            ]
        lines.append("")
    if result["coverage"]:
        coverage = COVERAGE_LINES[entry["source"]](entry["code"], result["coverage"])
        lines += ["## 資料覆蓋", "", *coverage, ""]
    return "\n".join(lines)


def write_outputs(out: Path, result: dict[str, Any], run: dict[str, Any]) -> None:
    name = display(result["watch"])
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(markdown(result), encoding="utf-8")
    panel = run["panel"]
    mine, population = run["equity"]
    with (out / "equity.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", name, POPULATION, "taiex_close"])
        for at, day in enumerate(run["dates"]):
            writer.writerow(
                [
                    day.isoformat(),
                    f"{mine[at]:.8f}",
                    f"{population[at]:.8f}",
                    panel.index_close.get(day),
                ]
            )
    fields = [
        "signal_date",
        "rank",
        "exchange",
        "symbol",
        *PICK_FIELDS[result["entry"]["source"]](
            result["entry"]["code"], result["definition"]
        ),
        "tie",
    ]
    with (out / "picks.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(run["rows"])
    sessions = panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "account",
                "exchange",
                "symbol",
                "bought",
                "due",
                "sold",
                "how",
                "cost",
                "proceeds",
            ]
        )
        for p in run["positions"]:
            exchange, symbol, _ = panel.symbols.get(p.instrument_id, ("", "", ""))
            writer.writerow(
                [
                    p.account,
                    exchange,
                    symbol,
                    sessions[p.bought].isoformat(),
                    sessions[p.due].isoformat() if p.due < len(sessions) else "",
                    sessions[p.sold].isoformat() if p.sold is not None else "",
                    p.how,
                    f"{p.cost:.10f}",
                    "" if p.proceeds is None else f"{p.proceeds:.10f}",
                ]
            )


# --- the command -----------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forward_watch.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a copy_db.py copy of stock.db")
    parser.add_argument("--watch", required=True, choices=list(WATCHES))
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=None,
        help="last session valued (default: the copy's latest session)",
    )
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    problems += source_problems(args.watch)
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    line = run_watch(
        db,
        args.watch,
        Path(args.out),
        cutoff=args.cutoff,
        command="python tools/research/forward_watch.py " + " ".join(argv),
    )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
