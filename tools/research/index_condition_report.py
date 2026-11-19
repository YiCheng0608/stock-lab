"""Tables of one index-condition research backtest run (#567), read only.

Reads the database ``--db`` (the copy the ``backtest_research.py
--index-condition`` run wrote) through a ``mode=ro`` connection with
``query_only`` on, and writes to ``--out``:

- ``summary.md``: the tables of the #567 report;
- ``tables.json``: the same numbers, with the run id and request key;
- ``segments.csv``: every run of consecutive score dates with one condition
  state (C2／C7 once per market).

The sample split is ``app.strategies.index_conditions``' ``EXPLORATION``／
``VALIDATION``, fixed before any result was read; every table is given for
both segments (and the whole range and each calendar quarter of the signal
date).  For each registered strategy of the run (the baseline) and each of
its index-condition strategies, as ``regime_report.py`` does for #546:

- rows, ``data_incomplete`` rows and actionable signals (status not
  ``observation``／``data_incomplete``／``invalid_levels``);
- the tracking status of the actionable signals (口徑: the run's
  ``tracking_version``);
- the T+5／T+20 comparable settlement returns, less the ones still
  ``not_triggered`` at T+N;
- the baseline's actionable signals split by the condition's state on their
  signal date for their own market (kept, condition failed, index data
  incomplete): what each condition removes, and how many of those were later
  ``invalidated``;
- a check that each condition version's actionable signals are the
  baseline's where its condition holds, with the same status and settlements;
- the segment judgement of ``judge_exploration``／``judge_validation``.

Then the market: each series over each segment (first and last close, largest
drawdown), TAIEX by quarter, each condition's days and runs, every TX roll
(the basis on the contract's last day and the next one's first), and which US
date each score date read.

An overnight condition (#855) is judged by ``judge_improved``／``judge_edge``
instead: each signal's T+20 return (a) and its excess (b) over the signal
date's population (``evidence_lib.universe``／``forward_return``, read from
the same copy), the removed signals split by fill day (E, later, never), and
which US row each score date read (``overnight.csv``).

Refuses the production database as ``backtest_research.py`` does.  Never
writes the database.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import importlib.util
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ALL = "all"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


regime_report = _load("regime_report")
STATUSES = regime_report.STATUSES
STATES = regime_report.STATES
STATE_ZH = regime_report.STATE_ZH
NOT_ACTIONABLE = regime_report.NOT_ACTIONABLE
quarter = regime_report.quarter
summarize = regime_report.summarize
pct = regime_report.pct
share = regime_report.share
MARKETS = ("TWSE", "TPEx")
MARKET_ZH = {"TWSE": "上市", "TPEx": "上櫃"}


def _evidence_lib():
    """``evidence_lib`` as the evidence tools import it (its dataclasses need a module entry)."""

    if str(ROOT / "tools" / "research") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools" / "research"))
    import evidence_lib

    return evidence_lib


def _conditions_module():
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))
    from app.strategies import index_conditions

    return index_conditions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="index_condition_report.py", description=__doc__
    )
    parser.add_argument("--db", required=True, help="the copy the research run wrote")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--out", required=True)
    return parser


def strategy_versions(con: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    result = {}
    for strategy_id, name, version, kind, config in con.execute(
        "select id, name, version, kind, config_json from strategy_versions"
    ):
        config = json.loads(config) if isinstance(config, str) else (config or {})
        condition = config.get("index_condition") or {}
        result[strategy_id] = {
            "name": name,
            "version": version,
            "kind": kind,
            "base": condition.get("base_strategy") or name,
            "condition": condition.get("condition"),
        }
    return result


def scopes_of(day: date, segment_of) -> tuple[str, ...]:
    segment = segment_of(day)
    return (ALL, quarter(day)) + ((segment,) if segment else ())


def scan(
    con: sqlite3.Connection, prefix: str, versions: Mapping[int, dict], segment_of
):
    """One pass over the run's signals, without ``rule_evidence_json``.

    ``counts[(name, scope)]`` is [rows, data_incomplete, actionable];
    ``actionable[name]`` maps (instrument, signal date) to (signal id, status).
    """

    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    actionable: dict[str, dict[tuple[int, date], tuple[int, str]]] = defaultdict(dict)
    days: dict[str, date] = {}
    for signal_id, strategy_id, day, instrument_id, status in con.execute(
        "select id, strategy_version_id, signal_date, instrument_id, status "
        "from signals where signal_key like ? order by id",
        (prefix,),
    ):
        name = versions[strategy_id]["name"]
        day = days.setdefault(day, date.fromisoformat(day))
        is_actionable = status not in NOT_ACTIONABLE
        for scope in scopes_of(day, segment_of):
            item = counts[(name, scope)]
            item[0] += 1
            item[1] += status == "data_incomplete"
            item[2] += is_actionable
        if is_actionable:
            actionable[name][(instrument_id, day)] = (signal_id, status)
    return {
        "counts": dict(counts),
        "actionable": dict(actionable),
        "days": sorted(days.values()),
    }


def series_rows(con: sqlite3.Connection, series: Mapping[str, tuple[str, str, str]]):
    rows: dict[str, dict[date, tuple[float | None, str | None]]] = {}
    for key, (exchange, symbol, instrument_type) in series.items():
        found = con.execute(
            "select mb.trading_date, mb.close, mb.contract_month from market_bars mb "
            "join instruments i on i.id = mb.instrument_id "
            "where i.exchange = ? and i.symbol = ? and i.instrument_type = ?",
            (exchange, symbol, instrument_type),
        ).fetchall()
        if found:
            rows[key] = {
                date.fromisoformat(d): (close, month) for d, close, month in found
            }
    return rows


def exchanges(con: sqlite3.Connection, ids: Iterable[int]) -> dict[int, str]:
    wanted = set(ids)
    return {
        instrument_id: exchange
        for instrument_id, exchange in con.execute(
            "select id, exchange from instruments"
        )
        if instrument_id in wanted
    }


def taiwan_sessions(db: Path) -> list[date]:
    """``worker.pipeline.taiwan_bar_dates`` of the copy, read only (E of the overnight conditions)."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from worker.pipeline import taiwan_bar_dates

    engine = create_engine(
        "sqlite://", creator=lambda: regime_report.connect_read_only(db)
    )
    try:
        with Session(engine) as session:
            return list(taiwan_bar_dates(session))
    finally:
        engine.dispose()


def executions(con: sqlite3.Connection, prefix: str) -> dict[int, date | None]:
    """``signal id -> execution_date`` of the run (None: never filled)."""

    return {
        signal_id: date.fromisoformat(day) if day else None
        for signal_id, day in con.execute(
            "select id, execution_date from signals where signal_key like ? "
            "and execution_date is not null",
            (prefix,),
        )
    }


def population_means(db: Path, days: list[date], raw_dir: Path) -> dict[date, float]:
    """Each score date's population mean T+20 return less tracking's 30 bps (evidence.md 共同口徑)."""

    ic = _conditions_module()
    lib = _evidence_lib()
    # load_panel (research_report.load_actions) points STOCK_DB_PATH,
    # STOCK_DATA_DIR and STOCK_RAW_DIR at the copy; put them back after it.
    names = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")
    saved = {name: os.environ.get(name) for name in names}
    try:
        panel = lib.load_panel(db, days[0] - timedelta(days=60), raw_dir)
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    result = {}
    for day in days:
        values = [
            value
            for item, at in lib.universe(panel, day, lib.DEFAULT_MIN_LOTS)
            if (value := lib.forward_return(item, at, 20)) is not None
        ]
        if values:
            result[day] = sum(values) / len(values) - ic.TRACKING_COST
    return result


def overnight_metrics(
    keys: Iterable[tuple[int, date]],
    signals: Mapping[tuple[int, date], tuple[int, str]],
    settled: Mapping[int, Mapping[int, tuple]],
    population: Mapping[date, float],
) -> dict[str, Any]:
    """(a) and (b) of #855 over ``keys`` (``index_conditions.OvernightComparison``)."""

    lib = _evidence_lib()
    nets: list[float] = []
    excess: list[float] = []
    by_day: dict[date, list[float]] = defaultdict(list)
    for key in keys:
        value = regime_report.usable_return(settled.get(signals[key][0], {}).get(20))
        if value is None:
            continue
        nets.append(value)
        base = population.get(key[1])
        if base is not None:
            excess.append(value - base)
            by_day[key[1]].append(value - base)
    daily = [sum(values) / len(values) for _, values in sorted(by_day.items())]
    return {
        "t20_n": len(nets),
        "net_mean": sum(nets) / len(nets) if nets else None,
        "net_median": regime_report.quantile(nets, 0.5) if nets else None,
        "excess_n": len(excess),
        "excess_mean": sum(excess) / len(excess) if excess else None,
        "excess_days": len(daily),
        "excess_daily_mean": sum(daily) / len(daily) if daily else None,
        "excess_daily_t": lib.t_stat(daily, overlap=20),
    }


FILLS = ("entry_day", "later", "not_filled")
FILL_ZH = {"entry_day": "E 當天成交", "later": "E 之後才成交", "not_filled": "沒成交"}


def _next_session(history, day: date) -> date | None:
    try:
        return history.next_session(day)
    except Exception:  # next_session_unknown after the last session
        return None


def overnight_judgement(
    ic,
    own: Mapping[tuple[int, date], tuple[int, str]],
    baseline: Mapping[tuple[int, date], tuple[int, str]],
    parts: Mapping[str, list[tuple[int, date]]],
    settled: Mapping[int, Mapping[int, tuple]],
    population: Mapping[date, float],
    executed: Mapping[int, date | None],
    history,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """#855's two judgements of one condition version, and its removed signals by fill day."""

    judged: dict[str, Any] = {}
    fills: dict[str, Any] = {}
    comparisons = {}
    for segment in (item.code for item in ic.SEGMENTS):

        def chosen(keys, segment=segment):
            return [key for key in keys if ic.segment_of(key[1]) == segment]

        mine = overnight_metrics(chosen(own), own, settled, population)
        theirs = overnight_metrics(chosen(baseline), baseline, settled, population)
        removed = chosen(parts["rejected"])
        comparison = ic.OvernightComparison(
            removed=len(removed),
            removed_days=len({key[1] for key in removed}),
            t20_n=mine["t20_n"],
            net_mean=mine["net_mean"],
            baseline_net_mean=theirs["net_mean"],
            excess_mean=mine["excess_mean"],
            baseline_excess_mean=theirs["excess_mean"],
        )
        comparisons[segment] = comparison
        judged[segment] = {
            **comparison.__dict__,
            "common_net_mean": comparison.common_net_mean,
            "judgeable": comparison.judgeable,
            "improved": ic.judge_improved(comparison),
            "edge": ic.judge_edge(comparison),
            "version": mine,
            "baseline": theirs,
            "removed_group": overnight_metrics(removed, baseline, settled, population),
            "data_incomplete": len(chosen(parts["data_incomplete"])),
        }
        groups: dict[str, list[tuple[int, date]]] = {fill: [] for fill in FILLS}
        for key in removed:
            filled = executed.get(baseline[key][0])
            entry = _next_session(history, key[1])
            if filled is None:
                groups["not_filled"].append(key)
            elif entry is not None and filled == entry:
                groups["entry_day"].append(key)
            else:
                groups["later"].append(key)
        fills[segment] = {
            fill: {
                "signals": len(keys),
                **overnight_metrics(keys, baseline, settled, population),
            }
            for fill, keys in groups.items()
        }
    judged["verdict"] = ic.overnight_verdict(
        comparisons[ic.EXPLORATION.code], comparisons[ic.VALIDATION.code]
    )
    return judged, fills


def overnight_alignment(
    ic, history, codes: list[str], days: list[date]
) -> tuple[dict[str, Any], list[tuple]]:
    """Which US row each score date's overnight conditions read, by series and segment."""

    summary: dict[str, Any] = {}
    rows: list[tuple] = []
    for key in sorted({k for code in codes for k in ic.ALL_CONDITIONS[code].series}):
        read = history.overnight_rows(key, days)
        entry: dict[str, Any] = {}
        for scope in (ALL, *(item.code for item in ic.SEGMENTS)):
            chosen = {
                day: item
                for day, item in read.items()
                if scope == ALL or ic.segment_of(day) == scope
            }
            kinds: Counter = Counter()
            for item in chosen.values():
                if "missing" in item:
                    kinds[item["missing"]] += 1
                elif item["rows"] == 0:
                    kinds["us_market_closed"] += 1
                elif item["rows"] > 1:
                    kinds["several_us_rows"] += 1
                else:
                    kinds["one_us_row"] += 1
            entry[scope] = dict(kinds)
        entry["read_on_or_after_entry"] = sum(
            1
            for item in read.values()
            if item.get("date") is not None and item["date"] >= item["entry"]
        )
        entry["read_before_score_date"] = sum(
            1
            for day, item in read.items()
            if item.get("date") is not None and item["date"] < day
        )
        entry["us_market_closed_dates"] = [
            day for day, item in read.items() if item.get("rows") == 0
        ]
        entry["several_us_rows_dates"] = [
            day for day, item in read.items() if (item.get("rows") or 0) > 1
        ]
        entry["missing_dates"] = {
            str(day): item["missing"] for day, item in read.items() if "missing" in item
        }
        summary[key] = entry
        for day, item in read.items():
            rows.append(
                (
                    key,
                    day,
                    item.get("entry"),
                    item.get("date"),
                    item.get("previous_date"),
                    item.get("return"),
                    item.get("rows"),
                    item.get("missing"),
                )
            )
    return summary, rows


def _span(points: list[tuple[date, float]]) -> dict[str, Any] | None:
    if not points:
        return None
    return {
        "sessions": len(points),
        "first": points[0],
        "last": points[-1],
        "return": points[-1][1] / points[0][1] - 1.0,
        "max_drawdown": regime_report.max_drawdown(points),
    }


def build(db: Path, run_id: int, raw_dir: Path | None = None) -> dict[str, Any]:
    ic = _conditions_module()
    from worker.futures_bars import near_month

    con = regime_report.connect_read_only(db)
    run = con.execute(
        "select id, status, request_key, metadata_json from ingestion_runs "
        "where id = ? and run_type = 'backtest'",
        (run_id,),
    ).fetchone()
    if not run:
        raise SystemExit(f"no backtest run {run_id} in {db}")
    metadata = json.loads(run[3]) if isinstance(run[3], str) else (run[3] or {})
    prefix = f"backtest-{run_id}-%"
    versions = strategy_versions(con)
    scanned = scan(con, prefix, versions, ic.segment_of)
    settled = regime_report.settlements(con, prefix)
    history = ic.IndexHistory(series_rows(con, ic.SERIES), taiwan_sessions(db))
    markets_of = exchanges(
        con,
        {key[0] for signals in scanned["actionable"].values() for key in signals},
    )
    executed = executions(con, prefix)
    con.close()

    days = scanned["days"]
    names = metadata.get("research_registry") or sorted(
        {name for name, _scope in scanned["counts"]}
    )
    by_name = {item["name"]: item for item in versions.values()}
    codes = [
        code
        for code in ic.ALL_CONDITIONS
        if any(by_name[name]["condition"] == code for name in names)
    ]
    overnight = [code for code in codes if code in ic.OVERNIGHT_CONDITIONS]
    per_market = {code for code in codes if ic.ALL_CONDITIONS[code].per_market}
    population = (
        population_means(
            db, scanned["days"], raw_dir or Path(db).resolve().parent / "raw"
        )
        if overnight and scanned["days"]
        else {}
    )
    states: dict[str, dict[str | None, dict[date, str]]] = {}
    for code in codes:
        markets = MARKETS if code in per_market else (None,)
        states[code] = {
            market: {
                day: item.state
                for day, item in history.states(code, days, market).items()
            }
            for market in markets
        }

    def state_of(code: str, key: tuple[int, date]) -> str:
        by_market = states[code]
        market = markets_of.get(key[0]) if code in per_market else None
        if market not in by_market:  # an exchange with no market index
            return "data_incomplete"
        return by_market[market][key[1]]

    quarters = sorted({quarter(day) for day in days})
    segment_codes = [item.code for item in ic.SEGMENTS]
    scopes = (ALL, *segment_codes, *quarters)

    def in_scope(day: date, scope: str) -> bool:
        return scope in scopes_of(day, ic.segment_of)

    def table(name: str, keys: Iterable[tuple[int, date]] | None = None) -> dict:
        signals = scanned["actionable"].get(name, {})
        chosen = signals.values() if keys is None else (signals[k] for k in keys)
        return summarize(chosen, settled)

    strategies: dict[str, Any] = {}
    for base in [name for name in names if by_name[name]["condition"] is None]:
        versions_of = [base] + [
            name for name in names if by_name[name]["base"] == base and name != base
        ]
        result: dict[str, Any] = {
            "versions": {},
            "removed": {},
            "consistency": {},
            "judgement": {},
            "overnight": {},
            "fills": {},
        }
        for name in versions_of:
            item = {"condition": by_name[name]["condition"], "scopes": {}}
            for scope in scopes:
                rows, incomplete, actionable = scanned["counts"].get(
                    (name, scope), [0, 0, 0]
                )
                keys = None
                if scope != ALL:
                    keys = [
                        key
                        for key in scanned["actionable"].get(name, {})
                        if in_scope(key[1], scope)
                    ]
                summary = table(name, keys)
                assert summary["actionable"] == actionable
                item["scopes"][scope] = {
                    "rows": rows,
                    "data_incomplete": incomplete,
                    **summary,
                }
            result["versions"][name] = item
        baseline = scanned["actionable"].get(base, {})
        for name in versions_of[1:]:
            code = by_name[name]["condition"]
            parts = {state: [] for state in STATES}
            for key in baseline:
                parts[state_of(code, key)].append(key)
            result["removed"][name] = {
                state: {
                    scope: table(base, [k for k in keys if in_scope(k[1], scope)])
                    for scope in scopes
                }
                for state, keys in parts.items()
            }
            own = scanned["actionable"].get(name, {})
            kept = set(parts["passed"])
            mismatched = [
                key
                for key in kept & set(own)
                if baseline[key][1] != own[key][1]
                or settled.get(baseline[key][0]) != settled.get(own[key][0])
            ]
            result["consistency"][name] = {
                "baseline_on_passed_dates": len(kept),
                "condition_actionable": len(own),
                "only_in_baseline": len(kept - set(own)),
                "only_in_condition": len(set(own) - kept),
                "status_or_settlement_differs": len(mismatched),
            }
            if code in ic.OVERNIGHT_CONDITIONS:
                result["overnight"][name], result["fills"][name] = overnight_judgement(
                    ic, own, baseline, parts, settled, population, executed, history
                )
                continue
            judged = {}
            for segment in segment_codes:
                mine = result["versions"][name]["scopes"][segment]
                theirs = result["versions"][base]["scopes"][segment]
                comparison = ic.Comparison(
                    removed=result["removed"][name]["rejected"][segment]["actionable"],
                    t20_n=mine["returns"]["t20"]["n"],
                    t20_median=mine["returns"]["t20"].get("p50"),
                    baseline_t20_median=theirs["returns"]["t20"].get("p50"),
                    invalidated_share=mine["invalidated_share"],
                    baseline_invalidated_share=theirs["invalidated_share"],
                )
                verdict = (
                    ic.judge_exploration(comparison)
                    if segment == ic.EXPLORATION.code
                    else ic.judge_validation(comparison)
                )
                judged[segment] = {
                    **comparison.__dict__,
                    "judgeable": comparison.judgeable,
                    "verdict": verdict,
                }
            judged["proposable"] = (
                judged[ic.EXPLORATION.code]["verdict"] == "selected"
                and judged[ic.VALIDATION.code]["verdict"] == "not_reversed"
            )
            judged["validation_independent"] = ic.ALL_CONDITIONS[
                code
            ].validation_independent
            result["judgement"][name] = judged
        strategies[base] = result

    # ---- market ----
    points = {
        key: [
            (day, close)
            for day, close in zip(*history.series(key)[:2])
            if close is not None and close > 0
        ]
        for key in ic.SERIES
    }
    first_day, last_day = (days[0], days[-1]) if days else (None, None)
    spans: dict[str, dict[str, Any]] = {}
    for key, series in points.items():
        spans[key] = {
            "stored": {
                "rows": len(history.series(key)[0]),
                "first": history.series(key)[0][0] if history.series(key)[0] else None,
                "last": history.series(key)[0][-1] if history.series(key)[0] else None,
            }
        }
        for scope in (ALL, *segment_codes):
            chosen = [
                (day, close)
                for day, close in series
                if first_day
                and first_day <= day <= last_day
                and (scope == ALL or ic.segment_of(day) == scope)
            ]
            spans[key][scope] = _span(chosen)
    taiex = dict(points["TAIEX"])
    condition_days: dict[str, dict[str, Any]] = {}
    segment_rows = []
    for code in codes:
        for market, by_day in states[code].items():
            label = code if market is None else f"{code}:{market}"
            entry = {}
            for scope in (ALL, *segment_codes):
                chosen = {
                    day: state
                    for day, state in by_day.items()
                    if scope == ALL or ic.segment_of(day) == scope
                }
                counted = Counter(chosen.values())
                runs = regime_report.segments(chosen)
                entry[scope] = {
                    "days": {state: counted.get(state, 0) for state in STATES},
                    "passed_segments": [
                        run for run in runs if run["state"] == "passed"
                    ],
                }
            condition_days[label] = entry
            segment_rows += [
                (label, run["state"], run["start"], run["end"], run["sessions"])
                for run in regime_report.segments(by_day)
            ]
    rolls = [
        item
        for item in history.rolls()
        if first_day and first_day <= item["first_day"] <= last_day
    ]
    tx_dates, _tx_closes, tx_months = history.series("TX")
    off_month = [
        (day, month)
        for day, month in zip(tx_dates, tx_months)
        if first_day and first_day <= day <= last_day and month != near_month(day)
    ]
    us_alignment = {}
    for key in sorted(ic.US_SERIES):
        us_dates = history.series(key)[0]
        gaps: Counter = Counter()
        same_day = 0
        for day in days:
            at = bisect.bisect_left(us_dates, day)
            if at < len(us_dates) and us_dates[at] == day:
                same_day += 1
            gaps["none" if not at else (day - us_dates[at - 1]).days] += 1
        us_alignment[key] = {
            "gap_days": {str(k): v for k, v in sorted(gaps.items(), key=str)},
            "score_dates_with_a_same_date_us_row_not_read": same_day,
        }

    overnight_summary, overnight_csv = overnight_alignment(ic, history, overnight, days)

    return {
        "run": {
            "id": run[0],
            "status": run[1],
            "request_key": run[2],
            "start": metadata.get("start_date"),
            "end": metadata.get("end_date"),
            "tracking_version": metadata.get("tracking_version"),
            "score_session_count": metadata.get("score_session_count"),
            "registry": names,
        },
        "split": {
            item.code: {
                "label_zh": item.label_zh,
                "start": item.start,
                "end": item.end or last_day,
                "score_sessions": sum(ic.segment_of(day) == item.code for day in days),
            }
            for item in ic.SEGMENTS
        },
        "selection_rule": {
            "text_zh": ic.SELECTION_RULE_ZH,
            "min_removed": ic.MIN_REMOVED,
            "min_t20": ic.MIN_T20,
        },
        "overnight_rule": {
            "text_zh": ic.OVERNIGHT_RULE_ZH,
            "min_removed": ic.OVERNIGHT_MIN_REMOVED,
            "min_removed_days": ic.OVERNIGHT_MIN_REMOVED_DAYS,
            "min_t20": ic.OVERNIGHT_MIN_T20,
            "tracking_cost": ic.TRACKING_COST,
            "common_cost": ic.COMMON_COST,
            "groups": sum(len(data["overnight"]) for data in strategies.values()),
        },
        "overnight_codes": overnight,
        "conditions": {
            code: {
                "definition": ic.ALL_CONDITIONS[code].definition,
                "label_zh": ic.ALL_CONDITIONS[code].label_zh,
                "reads": ic.ALL_CONDITIONS[code].reads,
                "validation_independent": ic.ALL_CONDITIONS[
                    code
                ].validation_independent,
                "note_zh": ic.ALL_CONDITIONS[code].note_zh,
                "per_market": code in per_market,
            }
            for code in codes
        },
        "market": {
            "series": spans,
            "taiex_quarters": regime_report.market(taiex, days, {})["quarters"],
            "condition_days": condition_days,
            "tx_rolls": rolls,
            "tx_rows_not_near_month": off_month,
            "us_alignment": us_alignment,
            "overnight_rows": overnight_summary,
        },
        "segment_rows": segment_rows,
        "overnight_rows": overnight_csv,
        "quarters": quarters,
        "strategies": strategies,
    }


# --- markdown -------------------------------------------------------------

VERDICT_ZH = {
    "selected": "選出",
    "not_selected": "未選出",
    "not_reversed": "沒有反轉",
    "reversed": "反轉",
    "insufficient": "無法判定",
}


def _label(name: str, conditions: Mapping[str, Any], code: str | None) -> str:
    if code is None:
        return f"`{name}`（baseline）"
    return f"`{name}`（{code.upper()}：{conditions[code]['label_zh']}）"


def _cond_label(label: str, conditions: Mapping[str, Any]) -> str:
    code, _, market = label.partition(":")
    text = f"{code.upper()}｜{conditions[code]['label_zh']}"
    return f"{text}（{MARKET_ZH[market]}）" if market else text


def _close(point) -> str:
    return "—" if not point else f"{point[0]} {point[1]:,.2f}"


def _pp(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f} pp"


IMPROVED_ZH = {"improved": "改善", "not_improved": "未改善", "insufficient": "無法判定"}
EDGE_ZH = {"edge": "有優勢", "no_edge": "沒有優勢", "insufficient": "無法判定"}
OVERNIGHT_KIND_ZH = {
    "one_us_row": "一列",
    "several_us_rows": "多列（台股休市，取最新）",
    "us_market_closed": "美股休市（不濾）",
}


def _diff(mine: float | None, theirs: float | None) -> float | None:
    return None if mine is None or theirs is None else mine - theirs


def _t(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}"


def overnight_alignment_lines(result: dict[str, Any], tag: str) -> list[str]:
    split = result["split"]
    lines = [
        "",
        f"### 隔夜美股讀哪一列（#855，{tag}）",
        "",
        "- T 是訊號日，E 是 T 之後第一個台股交易日（`worker.pipeline.taiwan_bar_dates`）。"
        "讀日期在 [T, E) 的最新一列，r＝它的收盤 ÷ 前一筆已存收盤 − 1；日期 ≥ E 的列不讀。",
        "",
        "| 序列 | 段 | 一列 | 多列（台股休市，取最新） | 美股休市（不濾） | 資料不足 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for key, entry in result["market"]["overnight_rows"].items():
        for scope in ("all", *split):
            kinds = entry[scope]
            missing = "、".join(
                f"`{reason}` {count}"
                for reason, count in sorted(kinds.items())
                if reason not in OVERNIGHT_KIND_ZH
            )
            name = "全範圍" if scope == "all" else split[scope]["label_zh"]
            lines.append(
                f"| {key} | {name} | {kinds.get('one_us_row', 0):,} | "
                f"{kinds.get('several_us_rows', 0):,} | {kinds.get('us_market_closed', 0):,} | "
                f"{missing or '0'} |"
            )
    for key, entry in result["market"]["overnight_rows"].items():
        lines += [
            "",
            f"- {key}：讀到日期 ≥ E 的列 {entry['read_on_or_after_entry']} 日、"
            f"日期 < T 的列 {entry['read_before_score_date']} 日（兩者都應為 0）。",
            f"  - 美股休市（不濾）的 T：{', '.join(map(str, entry['us_market_closed_dates'])) or '無'}",
            f"  - [T, E) 有多列的 T：{', '.join(map(str, entry['several_us_rows_dates'])) or '無'}",
            "  - 資料不足的 T："
            + (
                "、".join(
                    f"{day}（`{why}`）" for day, why in entry["missing_dates"].items()
                )
                or "無"
            ),
        ]
    return lines


def overnight_lines(
    result: dict[str, Any], base: str, data: dict[str, Any], tag: str
) -> list[str]:
    split = result["split"]
    conditions = result["conditions"]
    segs = list(split)
    lines = [
        "",
        f"### {base}：隔夜條件判定（#855，{tag}）",
        "",
        "(a)＝扣成本 T+20 模擬報酬（tracking_v2，來回 30 bps）的逐筆平均；"
        "(a′)＝同一數字改扣共同口徑 58.5 bps；(b)＝(a) 減同一訊號日母體等權平均（母體同扣 30 bps）的逐筆平均；"
        "t＝(b) 先依訊號日平均，再以日數 ÷ 20 算的 t（只列、不判定）。",
        "",
        "| 條件 | 段 | 濾掉（訊號日） | 資料不足 | 研究版 T+20 n | (a) 研究版 | (a) baseline | (a) 差 | "
        "(a′) 研究版 | (b) 研究版 | (b) baseline | (b) 差 | (b) t | 改善 | 有優勢 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for version, judged in data["overnight"].items():
        code = data["versions"][version]["condition"]
        for scope in segs:
            item = judged[scope]
            lines.append(
                f"| {code.upper()} | {split[scope]['label_zh']} | "
                f"{item['removed']:,}（{item['removed_days']}） | {item['data_incomplete']:,} | "
                f"{item['t20_n']:,} | {pct(item['net_mean'])} | {pct(item['baseline_net_mean'])} | "
                f"{_pp(_diff(item['net_mean'], item['baseline_net_mean']))} | "
                f"{pct(item['common_net_mean'])} | {pct(item['excess_mean'])} | "
                f"{pct(item['baseline_excess_mean'])} | "
                f"{_pp(_diff(item['excess_mean'], item['baseline_excess_mean']))} | "
                f"{_t(item['version']['excess_daily_t'])} | "
                f"{IMPROVED_ZH[item['improved']]} | {EDGE_ZH[item['edge']]} |"
            )
    lines += [
        "",
        "| 條件 | 定義 | 改善（兩段都過） | 有優勢（兩段都過） |",
        "| --- | --- | --- | --- |",
    ]
    for version, judged in data["overnight"].items():
        code = data["versions"][version]["condition"]
        verdict = judged["verdict"]
        lines.append(
            f"| {code.upper()} | {conditions[code]['label_zh']} | "
            f"{'是' if verdict['improved'] else '否'} | {'是' if verdict['edge'] else '否'} |"
        )
    lines += [
        "",
        f"#### {base}：濾掉的那組（baseline 的可行動訊號，條件不成立，{tag}）",
        "",
        "| 條件 | 段 | T+20 n | (a) 平均 | (a) 中位 | (b) 平均 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for version, judged in data["overnight"].items():
        code = data["versions"][version]["condition"]
        for scope in segs:
            group = judged[scope]["removed_group"]
            lines.append(
                f"| {code.upper()} | {split[scope]['label_zh']} | {group['t20_n']:,} | "
                f"{pct(group['net_mean'])} | {pct(group['net_median'])} | "
                f"{pct(group['excess_mean'])} |"
            )
    lines += [
        "",
        f"#### {base}：濾掉的訊號依成交日（E＝T+1 台股交易日，{tag}）",
        "",
        "| 條件 | 段 | 成交 | 筆數 | T+20 n | (a) 平均 | (b) 平均 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for version, fills in data["fills"].items():
        code = data["versions"][version]["condition"]
        for scope in segs:
            for fill in FILLS:
                cell = fills[scope][fill]
                lines.append(
                    f"| {code.upper()} | {split[scope]['label_zh']} | {FILL_ZH[fill]} | "
                    f"{cell['signals']:,} | {cell['t20_n']:,} | {pct(cell['net_mean'])} | "
                    f"{pct(cell['excess_mean'])} |"
                )
    return lines


def overnight_counts(result: dict[str, Any]) -> dict[str, int]:
    verdicts = [
        judged["verdict"]
        for data in result["strategies"].values()
        for judged in data["overnight"].values()
    ]
    return {
        "groups": len(verdicts),
        "improved": sum(item["improved"] for item in verdicts),
        "edge": sum(item["edge"] for item in verdicts),
    }


def markdown(result: dict[str, Any], command: str) -> str:
    run = result["run"]
    conditions = result["conditions"]
    split = result["split"]
    tag = f"run {run['id']}"
    segs = list(split)
    overnight = result.get("overnight_codes") or []
    only_overnight = bool(overnight) and set(overnight) == set(conditions)
    title = "# 隔夜美股條件研究（#855）" if only_overnight else "# 指數條件研究（#567）"
    rule_lines = []
    if not only_overnight:
        rule_lines.append(
            "- 判定規則（同模組 `judge_exploration`／`judge_validation`）："
            + result["selection_rule"]["text_zh"]
        )
    if overnight:
        rule_lines.append(
            "- 隔夜條件的判定（同模組 `judge_improved`／`judge_edge`，#855 決定 7018301183）："
            + result["overnight_rule"]["text_zh"]
        )
        counts = overnight_counts(result)
        rule_lines.append(
            f"- 比較次數：隔夜條件 {counts['groups']} 組（策略 × 條件）× 2 段；"
            f"兩段都過：改善 {counts['improved']} 組、有優勢 {counts['edge']} 組。"
            "同一檔指數的三個門檻是巢狀的，各組不獨立。"
        )
    lines = [
        title,
        "",
        f"- run id：`{run['id']}`（{run['status']}）",
        f"- request key：`{run['request_key']}`",
        f"- 範圍：{run['start']}～{run['end']}，{run['score_session_count']} 個交易日；"
        f"追蹤口徑 `{run['tracking_version']}`",
        f"- 重現：`{command}`",
        "- 事先切分（`app.strategies.index_conditions` 的 `EXPLORATION`／`VALIDATION`）："
        + "；".join(
            f"{item['label_zh']} {item['start']}～{item['end']}（{item['score_sessions']} 個交易日）"
            for item in split.values()
        ),
        *rule_lines,
        "",
        f"## 指數市況（{tag}）",
        "",
        "| 序列 | 段 | 起 | 迄 | 報酬 | 最大回檔 | 已存列數（起～迄） |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for key, item in result["market"]["series"].items():
        stored = item["stored"]
        stored_text = (
            f"{stored['rows']}（{stored['first']}～{stored['last']}）"
            if stored["rows"]
            else "0"
        )
        for scope in ("all", *segs):
            span = item[scope]
            name = "全範圍" if scope == "all" else split[scope]["label_zh"]
            if not span:
                lines.append(f"| {key} | {name} | — | — | — | — | {stored_text} |")
                continue
            dd = span["max_drawdown"]
            lines.append(
                f"| {key} | {name} | {_close(span['first'])} | {_close(span['last'])} | "
                f"{pct(span['return'])} | {dd['peak']}→{dd['trough']}（{pct(dd['return'])}） | "
                f"{stored_text} |"
            )
    lines += [
        "",
        "| 季 | 交易日 | TAIEX 季末收盤 | 季報酬 | 季內最大回檔 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, item in result["market"]["taiex_quarters"].items():
        lines.append(
            f"| {key} | {item['sessions']} | {item['last_close']:,.2f} | "
            f"{pct(item['return'])} | {pct(item['max_drawdown']['return'])} |"
        )
    lines += [
        "",
        f"### 各條件為真的天數（{tag}）",
        "",
        "| 條件 | 段 | 成立日 | 不成立日 | 資料不足日 | 成立區段數 | 最長成立區段 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for label, entry in result["market"]["condition_days"].items():
        for scope in ("all", *segs):
            item = entry[scope]
            runs = item["passed_segments"]
            longest = max(runs, key=lambda run: run["sessions"], default=None)
            name = "全範圍" if scope == "all" else split[scope]["label_zh"]
            lines.append(
                f"| {_cond_label(label, conditions)} | {name} | {item['days']['passed']} | "
                f"{item['days']['rejected']} | {item['days']['data_incomplete']} | {len(runs)} | "
                + (
                    f"{longest['start']}～{longest['end']}（{longest['sessions']} 日）"
                    if longest
                    else "—"
                )
                + " |"
            )
    for label, entry in result["market"]["condition_days"].items():
        runs = entry["all"]["passed_segments"]
        lines += [
            "",
            f"<details><summary>{_cond_label(label, conditions)} 成立區段（{len(runs)} 段）</summary>",
            "",
            ", ".join(f"{r['start']}～{r['end']}（{r['sessions']}）" for r in runs)
            or "無",
            "",
            "</details>",
        ]
    rolls_start = len(lines)
    rolls = result["market"]["tx_rolls"]
    jumps = [item["basis_jump"] for item in rolls if "basis_jump" in item]
    lines += [
        "",
        f"### 台指期換月（{tag}）",
        "",
        f"- 範圍內換月 {len(rolls)} 次；近月判定與 `worker.futures_bars.near_month` 不符的列："
        f"{len(result['market']['tx_rows_not_near_month'])}。",
        "- C3 價差用當日近月：換月日用新合約。C3 的 MA20 用已存近月收盤，不跨月調整；"
        "下表的「價差跳動」是新合約首日價差減舊合約末日價差，等於 MA20 窗口裡混到的合約差。",
    ]
    if jumps:
        lines.append(
            f"- 價差跳動：中位 {regime_report.quantile(jumps, 0.5):+,.1f} 點，"
            f"最小 {min(jumps):+,.1f}，最大 {max(jumps):+,.1f}。"
        )
    lines += [
        "",
        "<details><summary>每次換月</summary>",
        "",
        "| 舊合約末日 | 舊合約 | 舊價差 | 新合約首日 | 新合約 | 新價差 | 價差跳動 |",
        "| --- | --- | ---: | --- | --- | ---: | ---: |",
    ]
    for item in rolls:
        lines.append(
            f"| {item['last_day']} | {item['last_month']} | {item.get('last_basis', 0):+,.1f} | "
            f"{item['first_day']} | {item['first_month']} | {item.get('first_basis', 0):+,.1f} | "
            f"{item.get('basis_jump', 0):+,.1f} |"
        )
    lines += ["", "</details>"]
    if only_overnight:
        del lines[rolls_start:]
    if overnight:
        lines += overnight_alignment_lines(result, tag)
    c4_start = len(lines)
    lines += ["", f"### 美股日期對齊（#567 的 C4，{tag}）", ""]
    for key, item in result["market"]["us_alignment"].items():
        gaps = "、".join(
            f"{gap} 天 {count} 日" if gap != "none" else f"沒有前一列 {count} 日"
            for gap, count in item["gap_days"].items()
        )
        lines.append(
            f"- {key}：訊號日與所讀美股列相差 {gaps}；訊號日當天也有美股列（不讀）"
            f" {item['score_dates_with_a_same_date_us_row_not_read']} 日。"
        )
    if only_overnight:  # #567 only: the TX rolls and C4's US dates
        del lines[c4_start:]

    head = (
        "| 版本 | 列數 | data_incomplete | 可行動 | "
        + " | ".join(STATUSES)
        + " | 其他 | T+5 | T+20 |"
    )
    rule = "| --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in STATUSES)
    rule += " | ---: | --- | --- |"
    for base, data in result["strategies"].items():
        for scope in (*segs, "all"):
            name = "全範圍" if scope == "all" else split[scope]["label_zh"]
            lines += ["", f"## {base}：{name}（{tag}）", "", head, rule]
            for version, item in data["versions"].items():
                cell = item["scopes"][scope]
                lines.append(
                    f"| {_label(version, conditions, item['condition'])} | {cell['rows']:,} | "
                    f"{cell['data_incomplete']:,} | {cell['actionable']:,} | "
                    + " | ".join(regime_report._status_cells(cell))
                    + f" | {regime_report._returns(cell['returns']['t5'])} | "
                    f"{regime_report._returns(cell['returns']['t20'])} |"
                )
        if data["judgement"]:
            lines += [
                "",
                f"### {base}：段別判定（{tag}）",
                "",
                "| 條件 | 段 | 濾掉的可行動 | 研究版 T+20 n | T+20 中位差 | invalidated 差 | 判定 |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
            for version, judged in data["judgement"].items():
                code = data["versions"][version]["condition"]
                for scope in segs:
                    item = judged[scope]
                    median_diff = (
                        None
                        if item["t20_median"] is None
                        or item["baseline_t20_median"] is None
                        else item["t20_median"] - item["baseline_t20_median"]
                    )
                    inv_diff = (
                        None
                        if item["invalidated_share"] is None
                        or item["baseline_invalidated_share"] is None
                        else item["invalidated_share"]
                        - item["baseline_invalidated_share"]
                    )
                    lines.append(
                        f"| {code.upper()} | {split[scope]['label_zh']} | {item['removed']:,} | "
                        f"{item['t20_n']:,} | {_pp(median_diff)} | {_pp(inv_diff)} | "
                        f"{VERDICT_ZH[item['verdict']]} |"
                    )
            lines += [
                "",
                "| 條件 | 兩段都過 | 驗證段獨立 | 說明 |",
                "| --- | --- | --- | --- |",
            ]
            for version, judged in data["judgement"].items():
                code = data["versions"][version]["condition"]
                lines.append(
                    f"| {code.upper()} | {'是' if judged['proposable'] else '否'} | "
                    f"{'是' if judged['validation_independent'] else '否'} | "
                    f"{conditions[code]['note_zh'] or '—'} |"
                )
        if data["overnight"]:
            lines += overnight_lines(result, base, data, tag)
        lines += [
            "",
            f"### {base}：逐季（{tag}）",
            "",
            "| 季 | 版本 | 可行動 | invalidated | T+5 中位（n） | T+20 中位（n） |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for scope in result["quarters"]:
            for version, item in data["versions"].items():
                cell = item["scopes"][scope]
                t5, t20 = cell["returns"]["t5"], cell["returns"]["t20"]
                lines.append(
                    f"| {scope} | {(item['condition'] or 'baseline').upper()} | "
                    f"{cell['actionable']:,} | "
                    f"{share(cell['statuses'].get('invalidated', 0), cell['actionable'])}"
                    f" | {pct(t5.get('p50'))}（{t5['n']:,}） | "
                    f"{pct(t20.get('p50'))}（{t20['n']:,}） |"
                )
        lines += [
            "",
            f"### {base}：條件濾掉了什麼（baseline 的可行動訊號依訊號日、所屬市場的條件狀態分組，{tag}）",
            "",
            "| 條件 | 段 | 訊號日條件 | 可行動 | invalidated | target_1_hit＋target_2_hit | T+5 | T+20 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
        for version, parts in data["removed"].items():
            code = data["versions"][version]["condition"]
            for scope in segs:  # the whole range is in tables.json
                name = "全範圍" if scope == "all" else split[scope]["label_zh"]
                for state in STATES:
                    cell = parts[state][scope]
                    hits = cell["statuses"].get("target_1_hit", 0) + cell[
                        "statuses"
                    ].get("target_2_hit", 0)
                    lines.append(
                        f"| {code.upper()} | {name} | {STATE_ZH[state]} | {cell['actionable']:,} | "
                        f"{share(cell['statuses'].get('invalidated', 0), cell['actionable'])}"
                        f" | {share(hits, cell['actionable'])} | "
                        f"{regime_report._returns(cell['returns']['t5'])} | "
                        f"{regime_report._returns(cell['returns']['t20'])} |"
                    )
        lines += [
            "",
            f"### {base}：條件為真時與 baseline 一致的核對（{tag}）",
            "",
            "| 版本 | baseline 在成立日的可行動 | 研究版本可行動 | 只在 baseline | 只在研究版本 | 狀態或結算不同 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for version, item in data["consistency"].items():
            lines.append(
                f"| `{version}` | {item['baseline_on_passed_dates']:,} | "
                f"{item['condition_actionable']:,} | {item['only_in_baseline']:,} | "
                f"{item['only_in_condition']:,} | {item['status_or_settlement_differs']:,} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problem = _load("backtest_research").production_problem(db, dict(os.environ))
    if problem or not db.is_file():
        print(json.dumps({"refused": [problem or f"{db} does not exist"]}))
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = build(db, args.run_id, raw_dir=out / "raw")
    command = "python tools/research/index_condition_report.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    with (out / "segments.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["condition", "state", "start", "end", "sessions"])
        writer.writerows(result["segment_rows"])
    if result["overnight_rows"]:
        with (out / "overnight.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "series",
                    "score_date",
                    "entry_session",
                    "us_date",
                    "previous_us_date",
                    "overnight_return",
                    "us_rows_in_window",
                    "missing",
                ]
            )
            writer.writerows(result["overnight_rows"])
    print(
        json.dumps(
            {"out": str(out.resolve()), "run": result["run"]}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
