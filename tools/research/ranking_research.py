"""Chip-ranking research on one research backtest run (#598), read only.

For every score date of run ``--run-id`` (a ``backtest_research.py
--aggressive`` run on the copy ``--db``), builds the candidate pool
``candidate_score_v7`` would score from that run's baseline signals
(``breakout_v3``, ``pullback_v4``; namespace ``backtest-<run>``), scores it
with ``worker.candidates``' own steps (``_liquid_pool``, ``_score_pool``)
and orders it by each ranking of ``app.strategies.chip_ranking`` (v7, K1,
K2, K3).  Then, for each ranking's first ``--top`` per date, per segment,
the whole range and each quarter: the tracking statuses and T+5／T+20
returns of those signals (``regime_report.summarize``), the slots that
differ from v7's top, the daily overlap with v7's top, and the segment
judgement of ``chip_ranking.judge_exploration``／``judge_validation``.

The pool's filters (actionable on T, active strategy row, stock／ipo,
active instrument, legal levels, the entry type of the strategy, a bar on T
that is not suspended) are ``compute_daily_candidates``'s, copied here
because that function also writes its rows; a test pins this copy's v7
order to the rows it writes.  Each date also checks that ``rank("v7")``
gives the order ``_score_pool`` returns (``v7_mismatch_dates`` lists any
date where it does not).

The database is opened ``mode=ro`` with ``query_only`` on: no
``candidate_runs``／``daily_candidates`` row, and no row of any kind, is
written.  Writes ``rankings.csv`` (every ranked slot), ``tables.json`` and
``summary.md`` to ``--out``.  Refuses the production database as
``backtest_research.py`` does.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from datetime import date
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
quarter = regime_report.quarter
summarize = regime_report.summarize
pct = regime_report.pct
share = regime_report.share
VERDICT_ZH = {
    "selected": "選出",
    "not_selected": "未選出",
    "not_reversed": "沒有反轉",
    "reversed": "反轉",
    "insufficient": "無法判定",
}


def _backend():
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ranking_research.py", description=__doc__)
    parser.add_argument("--db", required=True, help="the copy the research run wrote")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--top", type=int, default=None, help="default chip_ranking.TOP_N"
    )
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    return parser


def read_only_session_factory(db: Path):
    """SQLAlchemy sessions on ``db`` opened ``mode=ro`` with ``query_only`` on."""

    _backend()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    uri = f"{db.resolve().as_uri()}?mode=ro"

    def connect():
        connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        connection.execute("PRAGMA query_only=1")
        return connection

    engine = create_engine("sqlite://", creator=connect)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def build_pool(db, trading_date: date, namespace: str, config: Mapping[str, Any]):
    """``compute_daily_candidates``' pool of ``namespace``'s signals on ``trading_date``.

    Returns ``(pool, summary, exclusions, evaluated)``; the pool is before
    the liquidity floor.
    """

    _backend()
    from sqlalchemy import select

    from app.domain import validate_signal_levels
    from app.models import Instrument, MarketBar, Signal, StrategyVersion
    from app.strategies.aggressive import BASES
    from worker import candidates

    pool_config = config["pool"]
    rows = db.execute(
        select(Signal, StrategyVersion, Instrument)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Signal.signal_date == trading_date,
            Signal.signal_key.like(f"{namespace}-%"),
            StrategyVersion.name.in_(pool_config["strategies"]),
        )
        .order_by(Signal.id)
    ).all()
    status_counts: dict[str, int] = defaultdict(int)
    exclusions: dict[str, int] = defaultdict(int)
    pool = []
    actionable = 0
    for signal, strategy, instrument in rows:
        status_counts[signal.status] += 1
        if not candidates._actionable_on_signal_date(signal, pool_config):
            continue
        actionable += 1
        if not strategy.active:
            exclusions["inactive_strategy_formula"] += 1
            continue
        if instrument.instrument_type not in pool_config["instrument_types"]:
            exclusions[f"instrument_type_excluded:{instrument.instrument_type}"] += 1
            continue
        if instrument.status != "active":
            exclusions["instrument_inactive"] += 1
            continue
        validation = validate_signal_levels(
            entry_type=signal.entry_type,
            reference_entry=signal.reference_entry,
            breakout_price=signal.breakout_price,
            invalid_price=signal.invalid_price,
            target_1=signal.target_1,
            target_2=signal.target_2,
        )
        if signal.entry_type != BASES[strategy.name].entry_type or not validation.valid:
            exclusions["invalid_levels"] += 1
            continue
        bar = db.scalar(
            select(MarketBar).where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date == trading_date,
            )
        )
        if bar is None or bar.is_suspended:
            exclusions["signal_day_suspended_or_missing"] += 1
            continue
        pool.append(
            candidates._PoolEntry(
                signal=signal,
                instrument=instrument,
                strategy=strategy.name,
                technical=candidates._technical_inputs(signal, strategy.name, bar),
            )
        )
    summary = {
        "signal_status_counts": dict(sorted(status_counts.items())),
        "actionable_signals": actionable,
    }
    return pool, summary, exclusions, len(rows)


def positive_flow_sessions(db, instrument_id: int, trading_date: date) -> int | None:
    """Of the last five non-suspended sessions through T, those with a positive net buy.

    The sessions and the fail-closed rule are ``candidates._chip_inputs``'
    five-session flow: T itself must be the newest session, and every one of
    the five needs foreign, trust and dealer values.
    """

    _backend()
    from sqlalchemy import desc, select

    from app.models import ChipSnapshot, MarketBar
    from worker import candidates

    dates = [
        row.trading_date
        for row in db.execute(
            select(MarketBar.trading_date)
            .where(
                MarketBar.instrument_id == instrument_id,
                MarketBar.trading_date <= trading_date,
                (MarketBar.is_suspended.is_(False) | MarketBar.is_suspended.is_(None)),
            )
            .order_by(desc(MarketBar.trading_date))
            .limit(5)
        )
    ]
    if len(dates) != 5 or dates[0] != trading_date:
        return None
    chips = {
        chip.trading_date: chip
        for chip in db.scalars(
            select(ChipSnapshot).where(
                ChipSnapshot.instrument_id == instrument_id,
                ChipSnapshot.trading_date.in_(dates),
            )
        )
    }
    positive = 0
    for day in dates:
        chip = chips.get(day)
        if chip is None:
            return None
        parts = [
            candidates._finite(chip.foreign_buy),
            candidates._finite(chip.trust_buy),
            candidates._finite(chip.dealer_buy),
        ]
        if any(part is None for part in parts):
            return None
        positive += sum(parts) > 0
    return positive


def day_entries(db, trading_date: date, namespace: str):
    """The scored pool of one date as ``chip_ranking.Entry`` and ``_score_pool``'s own order."""

    _backend()
    from app.strategies import chip_ranking as cr
    from worker import candidates

    config = json.loads(json.dumps(cr.SCORE_CONFIG))
    pool, summary, exclusions, evaluated = build_pool(
        db, trading_date, namespace, config
    )
    if pool and "liquidity" in config["pool"]:
        pool = candidates._liquid_pool(
            db, trading_date, pool, config["pool"], summary, exclusions
        )
    selected = []
    if pool:
        selected = candidates._score_pool(
            db, trading_date, pool, config, summary, exclusions
        )
    entries = []
    for item in pool:
        chips = item.components["chips"]["items"]
        entries.append(
            cr.Entry(
                signal_id=item.signal.id,
                instrument_id=item.instrument.id,
                exchange=item.instrument.exchange,
                symbol=item.instrument.symbol,
                strategy=item.strategy,
                scores={key: item.components[key]["score"] for key in cr.COMPONENTS},
                institutional_flow_5d=chips["institutional_flow_5d"]["value"],
                margin_change_5d=chips["margin_change_5d"]["value"],
                positive_flow_sessions_5d=positive_flow_sessions(
                    db, item.instrument.id, trading_date
                ),
            )
        )
    info = {
        "evaluated_signals": evaluated,
        "actionable_signals": summary["actionable_signals"],
        "pool": len(pool),
        "exclusions": dict(sorted(exclusions.items())),
    }
    return entries, [item.signal.id for item in selected], info


def rank_day(entries, selected: list[int], top: int) -> dict[str, Any]:
    """Every ranking's order of one date's entries, and the v7 check against ``selected``."""

    _backend()
    from app.strategies import chip_ranking as cr

    orders = {code: cr.rank(entries, code) for code in cr.RANKINGS}
    maximum = int(cr.SCORE_CONFIG["list_size"]["maximum"])
    v7 = [item.entry.signal_id for item in orders["v7"]]
    k3_out = [entry for entry in entries if not cr.passes_flow_and_margin(entry)]
    return {
        "orders": orders,
        "tops": {
            code: [item.entry.signal_id for item in order[:top]]
            for code, order in orders.items()
        },
        "v7_matches_score_pool": v7[:maximum] == selected,
        "k3_filtered": len(k3_out),
        "k3_filtered_without_margin": sum(e.margin_change_5d is None for e in k3_out),
        "k3_filtered_without_flow": sum(
            e.institutional_flow_5d is None for e in k3_out
        ),
        "k2_chips_null": sum(
            cr.k2_chips(e.positive_flow_sessions_5d, e.margin_change_5d) is None
            for e in entries
        ),
    }


def score_dates(con: sqlite3.Connection, run_id: int) -> list[date]:
    return [
        date.fromisoformat(day)
        for (day,) in con.execute(
            "select distinct signal_date from signals where signal_key like ? "
            "order by signal_date",
            (f"backtest-{run_id}-%",),
        )
    ]


def statuses(con: sqlite3.Connection, run_id: int) -> dict[int, str]:
    return dict(
        con.execute(
            "select id, status from signals where signal_key like ? "
            "and status not in ('observation','data_incomplete','invalid_levels')",
            (f"backtest-{run_id}-%",),
        ).fetchall()
    )


def build(
    db: Path,
    run_id: int,
    *,
    top: int | None = None,
    start: date | None = None,
    end: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], list[list[Any]]]:
    _backend()
    from app.strategies import chip_ranking as cr

    top = top or cr.TOP_N
    con = regime_report.connect_read_only(db)
    run = con.execute(
        "select id, status, request_key, metadata_json from ingestion_runs "
        "where id = ? and run_type = 'backtest'",
        (run_id,),
    ).fetchone()
    if not run:
        raise SystemExit(f"no backtest run {run_id} in {db}")
    metadata = json.loads(run[3]) if isinstance(run[3], str) else (run[3] or {})
    days = [
        day
        for day in score_dates(con, run_id)
        if (start is None or day >= start) and (end is None or day <= end)
    ]
    status_of = statuses(con, run_id)
    settled = regime_report.settlements(con, f"backtest-{run_id}-%")
    con.close()

    engine, factory = read_only_session_factory(db)
    namespace = f"backtest-{run_id}"
    per_day: dict[date, dict[str, Any]] = {}
    csv_rows: list[list[Any]] = []
    mismatches: list[str] = []
    started = time.perf_counter()
    try:
        for number, day in enumerate(days, start=1):
            with factory() as session:
                entries, selected, info = day_entries(session, day, namespace)
                ranked = rank_day(entries, selected, top)
                session.rollback()
            if not ranked["v7_matches_score_pool"]:
                mismatches.append(day.isoformat())
            for code, order in ranked["orders"].items():
                for position, item in enumerate(order, start=1):
                    entry = item.entry
                    csv_rows.append(
                        [
                            day.isoformat(),
                            code,
                            position,
                            entry.signal_id,
                            entry.exchange,
                            entry.symbol,
                            entry.strategy,
                            round(item.total, 6),
                            round(item.coverage, 6),
                            status_of.get(entry.signal_id),
                        ]
                    )
            per_day[day] = {
                **info,
                "tops": ranked["tops"],
                "eligible": {
                    code: len(order) for code, order in ranked["orders"].items()
                },
                "k3_filtered": ranked["k3_filtered"],
                "k3_filtered_without_margin": ranked["k3_filtered_without_margin"],
                "k3_filtered_without_flow": ranked["k3_filtered_without_flow"],
                "k2_chips_null": ranked["k2_chips_null"],
            }
            if progress and (number % 10 == 0 or number == len(days)):
                elapsed = time.perf_counter() - started
                progress(
                    f"{number}/{len(days)} {day} elapsed {elapsed:.0f}s "
                    f"eta {elapsed / number * (len(days) - number):.0f}s"
                )
    finally:
        engine.dispose()

    quarters = sorted({quarter(day) for day in days})
    segment_codes = [item.code for item in cr.SEGMENTS]
    scopes = (ALL, *segment_codes, *quarters)

    def in_scope(day: date, scope: str) -> bool:
        segment = cr.segment_of(day)
        return scope in (ALL, quarter(day)) + ((segment,) if segment else ())

    rankings: dict[str, Any] = {}
    for code in cr.RANKINGS:
        item: dict[str, Any] = {"label_zh": cr.RANKINGS[code].label_zh, "scopes": {}}
        for scope in scopes:
            chosen = [day for day in days if in_scope(day, scope)]
            signals = [
                # A pool signal is actionable on T; any other status is 「其他」.
                (signal_id, status_of.get(signal_id, "not_actionable"))
                for day in chosen
                for signal_id in per_day[day]["tops"][code]
            ]
            compared = [day for day in chosen if per_day[day]["tops"]["v7"]]
            overlaps = [
                cr.overlap(per_day[day]["tops"][code], per_day[day]["tops"]["v7"], top)
                for day in compared
            ]
            # 交集檔數／該日 v7 前 N 檔的檔數（不足 N 檔的日子照實記）。
            shared = Counter(
                (
                    len(
                        set(per_day[day]["tops"][code])
                        & set(per_day[day]["tops"]["v7"])
                    ),
                    len(per_day[day]["tops"]["v7"]),
                )
                for day in compared
            )
            replaced = sum(
                len(set(per_day[day]["tops"][code]) - set(per_day[day]["tops"]["v7"]))
                for day in chosen
            )
            sizes = Counter(len(per_day[day]["tops"][code]) for day in chosen)
            item["scopes"][scope] = {
                "dates": len(chosen),
                "slots": len(signals),
                "dates_under_top": sum(
                    count for size, count in sizes.items() if size < top
                ),
                "top_size_days": {str(k): v for k, v in sorted(sizes.items())},
                "replaced": replaced,
                "overlap": {
                    "days": len(overlaps),
                    "mean": statistics.fmean(overlaps) if overlaps else None,
                    "histogram": {
                        f"{inter}/{size}": v
                        for (inter, size), v in sorted(shared.items())
                    },
                },
                **summarize(signals, settled),
            }
        rankings[code] = item

    judgement: dict[str, Any] = {}
    for code in [code for code in cr.RANKINGS if code != "v7"]:
        judged: dict[str, Any] = {}
        for segment in segment_codes:
            mine = rankings[code]["scopes"][segment]
            theirs = rankings["v7"]["scopes"][segment]
            comparison = cr.Comparison(
                replaced=mine["replaced"],
                t20_n=mine["returns"]["t20"]["n"],
                t20_median=mine["returns"]["t20"].get("p50"),
                baseline_t20_median=theirs["returns"]["t20"].get("p50"),
                invalidated_share=mine["invalidated_share"],
                baseline_invalidated_share=theirs["invalidated_share"],
            )
            verdict = (
                cr.judge_exploration(comparison)
                if segment == cr.EXPLORATION.code
                else cr.judge_validation(comparison)
            )
            judged[segment] = {
                **comparison.__dict__,
                "judgeable": comparison.judgeable,
                "verdict": verdict,
            }
        judged["proposable"] = (
            judged[cr.EXPLORATION.code]["verdict"] == "selected"
            and judged[cr.VALIDATION.code]["verdict"] == "not_reversed"
        )
        judgement[code] = judged

    totals = {
        key: sum(per_day[day][key] for day in days)
        for key in (
            "evaluated_signals",
            "actionable_signals",
            "pool",
            "k3_filtered",
            "k3_filtered_without_margin",
            "k3_filtered_without_flow",
            "k2_chips_null",
        )
    }
    exclusions: Counter = Counter()
    for day in days:
        exclusions.update(per_day[day]["exclusions"])
    result = {
        "run": {
            "id": run[0],
            "status": run[1],
            "request_key": run[2],
            "start": metadata.get("start_date"),
            "end": metadata.get("end_date"),
            "tracking_version": metadata.get("tracking_version"),
            "score_session_count": metadata.get("score_session_count"),
        },
        "ranked_dates": {
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "count": len(days),
        },
        "top": top,
        "score_config": cr.SCORE_CONFIG["name"],
        "weights": {code: dict(item.weights) for code, item in cr.RANKINGS.items()},
        "split": {
            item.code: {
                "label_zh": item.label_zh,
                "start": item.start,
                "end": item.end or (days[-1] if days else None),
                "dates": sum(cr.segment_of(day) == item.code for day in days),
            }
            for item in cr.SEGMENTS
        },
        "selection_rule": {
            "text_zh": cr.SELECTION_RULE_ZH,
            "min_replaced": cr.MIN_REPLACED,
            "min_t20": cr.MIN_T20,
        },
        "v7_mismatch_dates": mismatches,
        "totals": totals,
        "exclusions": dict(sorted(exclusions.items())),
        "quarters": quarters,
        "rankings": rankings,
        "judgement": judgement,
        "seconds": round(time.perf_counter() - started, 1),
    }
    return result, csv_rows


def _pp(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f} pp"


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def markdown(result: dict[str, Any], command: str) -> str:
    run = result["run"]
    split = result["split"]
    top = result["top"]
    tag = f"run {run['id']}"
    segs = list(split)
    totals = result["totals"]
    lines = [
        "# 籌碼型排序研究（#598）",
        "",
        f"- 訊號來源：run `{run['id']}`（{run['status']}），request key `{run['request_key']}`",
        f"- 排序日期：{result['ranked_dates']['first']}～{result['ranked_dates']['last']}，"
        f"{result['ranked_dates']['count']} 日；每日取前 {top} 檔；基準 `{result['score_config']}`（在同一批研究訊號上重算）",
        f"- 重現：`{command}`",
        "- 事先切分（同 #567）："
        + "；".join(
            f"{item['label_zh']} {item['start']}～{item['end']}（{item['dates']} 日）"
            for item in split.values()
        ),
        f"- 判定規則（`app.strategies.chip_ranking`）：{result['selection_rule']['text_zh']}",
        f"- v7 排序與 `_score_pool` 不一致的日期：{len(result['v7_mismatch_dates'])}"
        + (
            f"（{', '.join(result['v7_mismatch_dates'][:20])}）"
            if result["v7_mismatch_dates"]
            else ""
        ),
        f"- 候選池：可行動 {totals['actionable_signals']:,}、進池（流動性前）{totals['pool']:,}；"
        f"排除 {', '.join(f'{k} {v:,}' for k, v in result['exclusions'].items()) or '無'}",
        f"- K3 篩掉的池內訊號 {totals['k3_filtered']:,}，其中沒有融資 5 日變化 {totals['k3_filtered_without_margin']:,}、"
        f"沒有法人 5 日流向 {totals['k3_filtered_without_flow']:,}；K2 籌碼分項為 null {totals['k2_chips_null']:,}",
        "",
        "| 排序 | 技術 | 籌碼 | 族群 | 新聞 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for code, weights in result["weights"].items():
        lines.append(
            f"| {code.upper()} | "
            + " | ".join(
                f"{weights[key]:.6f}"
                for key in ("technical", "chips", "group", "news_sentiment")
            )
            + " |"
        )
    head = (
        "| 排序 | 日數 | 名額 | 不足 "
        + str(top)
        + " 檔的日數 | 與 v7 不同的名額 | 與 v7 平均重疊率 | "
        + " | ".join(STATUSES)
        + " | 其他 | T+5 | T+20 |"
    )
    rule = "| --- | ---: | ---: | ---: | ---: | ---: | " + " | ".join(
        "---:" for _ in STATUSES
    )
    rule += " | ---: | --- | --- |"
    for scope in (*segs, ALL):
        name = "全範圍" if scope == ALL else split[scope]["label_zh"]
        lines += ["", f"## 每日前 {top} 檔：{name}（{tag}）", "", head, rule]
        for code, item in result["rankings"].items():
            cell = item["scopes"][scope]
            mean = cell["overlap"]["mean"]
            lines.append(
                f"| {code.upper()}（{item['label_zh']}） | {cell['dates']:,} | {cell['slots']:,} | "
                f"{cell['dates_under_top']:,} | {cell['replaced']:,} | "
                f"{'—' if mean is None else f'{mean * 100:.1f}%'} | "
                + " | ".join(regime_report._status_cells(cell))
                + f" | {regime_report._returns(cell['returns']['t5'])} | "
                f"{regime_report._returns(cell['returns']['t20'])} |"
            )
    lines += [
        "",
        f"### 重疊率分佈（每日與 v7 前 {top} 檔的交集檔數／v7 當日檔數：日數；平均重疊率的分母取兩邊前 {top} 檔較多的一邊，{tag}）",
        "",
        "| 排序 | 段 | 分佈（交集／v7 檔數：日數） |",
        "| --- | --- | --- |",
    ]
    for code, item in result["rankings"].items():
        if code == "v7":
            continue
        for scope in (*segs, ALL):
            name = "全範圍" if scope == ALL else split[scope]["label_zh"]
            hist = item["scopes"][scope]["overlap"]["histogram"]
            lines.append(
                f"| {code.upper()} | {name} | "
                + ("、".join(f"{k}：{v}" for k, v in hist.items()) or "—")
                + " |"
            )
    lines += [
        "",
        f"### 段別判定（{tag}）",
        "",
        "| 排序 | 段 | 與 v7 不同的名額 | 前 10 檔 T+20 n | T+20 中位差 | invalidated 差 | 判定 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for code, judged in result["judgement"].items():
        for scope in segs:
            item = judged[scope]
            lines.append(
                f"| {code.upper()} | {split[scope]['label_zh']} | {item['replaced']:,} | "
                f"{item['t20_n']:,} | {_pp(_diff(item['t20_median'], item['baseline_t20_median']))} | "
                f"{_pp(_diff(item['invalidated_share'], item['baseline_invalidated_share']))} | "
                f"{VERDICT_ZH[item['verdict']]} |"
            )
    lines += ["", "| 排序 | 兩段都過 |", "| --- | --- |"]
    for code, judged in result["judgement"].items():
        lines.append(f"| {code.upper()} | {'是' if judged['proposable'] else '否'} |")
    lines += [
        "",
        f"### 逐季（{tag}）",
        "",
        "| 季 | 排序 | 名額 | 與 v7 平均重疊率 | invalidated | T+5 中位（n） | T+20 中位（n） |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for scope in result["quarters"]:
        for code, item in result["rankings"].items():
            cell = item["scopes"][scope]
            t5, t20 = cell["returns"]["t5"], cell["returns"]["t20"]
            mean = cell["overlap"]["mean"]
            lines.append(
                f"| {scope} | {code.upper()} | {cell['slots']:,} | "
                f"{'—' if mean is None else f'{mean * 100:.1f}%'} | "
                f"{share(cell['statuses'].get('invalidated', 0), cell['slots'])} | "
                f"{pct(t5.get('p50'))}（{t5['n']:,}） | {pct(t20.get('p50'))}（{t20['n']:,}） |"
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

    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    result, rows = build(
        db,
        args.run_id,
        top=args.top,
        start=args.start,
        end=args.end,
        progress=progress,
    )
    command = "python tools/research/ranking_research.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    with (out / "rankings.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "trading_date",
                "ranking",
                "rank",
                "signal_id",
                "exchange",
                "symbol",
                "strategy",
                "total",
                "coverage",
                "status",
            ]
        )
        writer.writerows(rows)
    print(
        json.dumps(
            {
                "out": str(out.resolve()),
                "run": result["run"],
                "dates": result["ranked_dates"]["count"],
                "v7_mismatch_dates": len(result["v7_mismatch_dates"]),
                "seconds": result["seconds"],
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
