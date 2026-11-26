"""How did the candidate pool's stocks do afterwards, source by source (#1069)?

docs/spec/candidate_pool.md 對答案: every stock ``candidate_pool_v1`` selected
on a day T (the evening run and the morning one) is held from the open of D,
the first Taiwan session after T (the pre-market AI reading's day), to the
close of T+N (``app.premarket_score.open_hold``: +5 bps in, −5 bps out, 30 bps
off, the prices put back on T's basis), and compared with the same
population the AI's scores use (``worker.premarket_score.population``: every
stock／ipo with a D bar not suspended, equal weight, no liquidity floor).  The
pool and the AI are scored on one yardstick, not recomputed in a second way.

The groups are the pool's sixteen sources, a stock counted once in each of
its sources, and beside them the whole pool, each tier, the number of
sources, the stocks the caps turned away (``selected=false``) and the pool
stocks the champion AI reading kept or re-priced.  A group's day is the mean
of its comparable stocks less the day's population mean; a day the group has
no comparable stock is no day of it.  ``t`` is ``evidence_lib.t_stat`` with
``overlap=N``; the verdict is ``portfolio_research.forward_judge`` once
``MIN_DAYS`` days are in, cumulative from the pool's first day.

Read only (``mode=ro`` + ``query_only``), refused as ``exit_research`` refuses
(the production database, Taipei 21:30～23:30, too little free memory).
``--end`` cuts the pool days T; the returns read the copy to its last
session, so a T whose T+N is not stored yet is pending.  ``tables.json`` holds
no clock: the same copy gives the same file, alone or under monthly_review.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import portfolio_research as pr  # noqa: E402

VERSION = 1
DESIGN = "1069"
HORIZONS = {"5": 5, "20": 20}
MIN_DAYS = 60  # monthly_review.SCORECARD_MIN_DAYS
COMPARABLE = "comparable"
KEEP_REPRICE = ("keep", "reprice")

# The groups beside the sources, in the report's order.
POOL = "pool"
REJECTED = "rejected"
AI_KEPT = "ai_keep_reprice"
TIERS = (1, 2, 3, 4, 5)
SOURCE_COUNTS = ("1", "2", "3+")
LABELS = {
    POOL: "全池（入選）",
    REJECTED: "被上限擋掉（selected=false）",
    AI_KEPT: "AI 判 keep／reprice（champion）",
}


def source_key(source: str) -> str:
    return f"source:{source}"


def tier_key(tier: int) -> str:
    return f"tier:{tier}"


def count_key(count: int) -> str:
    return f"sources:{count if count < 3 else '3+'}"


def group_keys(sources: list[str]) -> list[str]:
    """Every group in the report's order: the sources, then the rest."""

    return [
        *(source_key(source) for source in sources),
        POOL,
        *(tier_key(tier) for tier in TIERS),
        *(f"sources:{count}" for count in SOURCE_COUNTS),
        REJECTED,
        AI_KEPT,
    ]


def label(key: str) -> str:
    if key in LABELS:
        return LABELS[key]
    kind, _sep, value = key.partition(":")
    if kind == "source":
        return f"`{value}`"
    if kind == "tier":
        return f"層級 {value}"
    return f"來源數 {value}"


def groups_of(item: dict[str, Any], action: str | None) -> list[str]:
    """The groups one pool row of a day counts in at one horizon."""

    if not item["selected"]:
        return [REJECTED]
    keys = [source_key(source) for source in item["sources"]]
    keys += [POOL, tier_key(item["tier"]), count_key(item["source_count"])]
    if action in KEEP_REPRICE:
        keys.append(AI_KEPT)
    return keys


# --- reading the copy ---------------------------------------------------------------


def _session(db: Path):
    """A SQLAlchemy Session on the copy, read only (monthly_review.premarket_text's)."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://", creator=lambda: lib.connect_read_only(db))
    return engine, Session(engine)


def read_items(session, end: date | None) -> list[dict[str, Any]]:
    """Every ``candidate_pool_v1`` row through ``end``, only the columns used."""

    from sqlalchemy import select

    from app.candidate_pool import CANDIDATE_POOL_VERSION
    from app.models import CandidatePoolItem as Item

    query = select(
        Item.id,
        Item.trading_date,
        Item.phase,
        Item.instrument_id,
        Item.tier,
        Item.selected,
        Item.reject_reason,
        Item.source_count,
        Item.sources_json,
    ).where(Item.version == CANDIDATE_POOL_VERSION)
    if end is not None:
        query = query.where(Item.trading_date <= end)
    rows = []
    for row in session.execute(query.order_by(Item.trading_date, Item.id)):
        rows.append(
            {
                "id": row.id,
                "trading_date": row.trading_date,
                "phase": row.phase,
                "instrument_id": row.instrument_id,
                "tier": row.tier,
                "selected": bool(row.selected),
                "reject_reason": row.reject_reason,
                "source_count": row.source_count,
                "sources": [part["source"] for part in row.sources_json or []],
            }
        )
    return rows


def ai_actions(session) -> dict[tuple[int, str], str]:
    """(pool item id, horizon) → the effective action of the champion's done
    reading (``role=champion``, the running ``PROMPT_VERSION``), from its
    written ``premarket_score_v1`` stock rows."""

    from sqlalchemy import select

    from app import premarket_score as score
    from app.models import PremarketAiReading as Reading
    from app.models import PremarketAiScore as Score
    from app.models import PremarketAiStock as Stock
    from app.premarket_ai import CHAMPION, DONE
    from worker.premarket_reading import PROMPT_VERSION

    query = (
        select(Stock.pool_item_id, Score.horizon, Score.outcome_json)
        .join(Reading, Reading.id == Stock.reading_id)
        .join(Score, Score.stock_id == Stock.id)
        .where(
            Reading.role == CHAMPION,
            Reading.prompt_version == PROMPT_VERSION,
            Reading.status == DONE,
            Score.scope == score.STOCK,
            Score.score_version == score.SCORE_VERSION,
            Stock.pool_item_id.is_not(None),
        )
    )
    out: dict[tuple[int, str], str] = {}
    for item_id, horizon, outcome in session.execute(query):
        out[(item_id, horizon.removeprefix("t"))] = (outcome or {}).get(
            "effective_action"
        )
    return out


def ai_overall(session) -> dict[tuple[date, str], float | None]:
    """(list date T, horizon) → the champion's ``overall`` ``ai_version.excess``:
    the AI group's day must equal it (docs/spec/candidate_pool.md 對答案)."""

    from sqlalchemy import select

    from app import premarket_score as score
    from app.models import PremarketAiReading as Reading
    from app.models import PremarketAiScore as Score
    from app.premarket_ai import CHAMPION, DONE
    from worker.premarket_reading import PROMPT_VERSION

    query = (
        select(Reading.list_date, Score.horizon, Score.outcome_json)
        .join(Score, Score.reading_id == Reading.id)
        .where(
            Reading.role == CHAMPION,
            Reading.prompt_version == PROMPT_VERSION,
            Reading.status == DONE,
            Score.scope == score.OVERALL,
            Score.score_version == score.SCORE_VERSION,
        )
    )
    out: dict[tuple[date, str], float | None] = {}
    for list_date, horizon, outcome in session.execute(query):
        version = (outcome or {}).get("ai_version") or {}
        if "excess" in version:
            out[(list_date, horizon.removeprefix("t"))] = version["excess"]
    return out


def liquid_config(session, day: date) -> dict[str, Any] | None:
    """The evening run's ``config_json`` of ``day`` (None: no evening run)."""

    from sqlalchemy import select

    from app.candidate_pool import CANDIDATE_POOL_VERSION, EVENING
    from app.models import CandidatePoolRun as Run

    return session.scalar(
        select(Run.config_json).where(
            Run.trading_date == day,
            Run.version == CANDIDATE_POOL_VERSION,
            Run.phase == EVENING,
        )
    )


def liquid_members(session, day: date) -> set[int] | None:
    """T's liquid stocks by the evening run's own floor (both phases read it);
    None when T has no evening run or no TAIEX bar: no value, no default."""

    from app import candidate_pool as cp

    config = liquid_config(session, day) or {}
    if config.get("liquidity_days") is None or config.get("min_average_lots") is None:
        return None
    floor = cp.PoolConfig(
        liquidity_days=int(config["liquidity_days"]),
        min_average_lots=float(config["min_average_lots"]),
    )
    try:
        sessions = [
            when
            for when, _close in cp.index_sessions(session, day, floor.liquidity_days)
        ]
    except cp.CandidatePoolDataError:
        return None
    if len(sessions) < floor.liquidity_days:
        return None
    return set(cp.liquid_ids(session, sessions, floor))


# --- the returns ----------------------------------------------------------------------


def day_results(
    session, day: date, items: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Horizon → the population and each row's ``open_hold`` for pool day T."""

    from app import premarket_score as score
    from worker import pipeline
    from worker import premarket_score as scoring

    longest = max(HORIZONS.values())
    sessions = pipeline.taiwan_bar_dates(session, after=day, limit=longest)
    out: dict[str, dict[str, Any]] = {}
    if len(sessions) < min(HORIZONS.values()):
        return {h: {"pending": True} for h in HORIZONS}

    def tracked_of(instrument_id: int):
        return pipeline._tracking_inputs(
            session, instrument_id, day, evaluation_cutoff=sessions[-1]
        )[1]

    tracked = {
        item["instrument_id"]: tracked_of(item["instrument_id"]) for item in items
    }
    liquid = liquid_members(session, day)
    liquid_tracked = None
    if liquid is not None:
        liquid_tracked = {
            instrument_id: tracked.get(instrument_id) or tracked_of(instrument_id)
            for instrument_id in sorted(liquid)
        }
    for horizon, length in HORIZONS.items():
        if len(sessions) < length:
            out[horizon] = {"pending": True}
            continue
        out[horizon] = {
            "pending": False,
            "d": sessions[0].isoformat(),
            "exit": sessions[length - 1].isoformat(),
            "population": scoring.population(session, day, sessions, length),
            "liquid": None
            if liquid_tracked is None
            else liquid_population(liquid_tracked, sessions, length),
            "holds": {
                item["id"]: score.open_hold(
                    tracked[item["instrument_id"]], sessions, length
                )
                for item in items
            },
        }
    return out


def liquid_population(
    tracked: dict[int, list], sessions: list[date], length: int
) -> dict[str, Any]:
    """The liquid stocks' D-open hold, kept as ``population`` keeps its members
    (a D bar, not suspended on D): a reference, never judged."""

    from app import premarket_score as score

    results = [
        score.open_hold(bars, sessions, length)
        for bars in tracked.values()
        if bars and bars[0].trading_date == sessions[0] and not score.suspended(bars[0])
    ]
    out = score.summary(results)
    out["members"] = out.pop("n")
    return out


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def collect(
    items: list[dict[str, Any]],
    results: dict[date, dict[str, dict[str, Any]]],
    actions: dict[tuple[int, str], str],
    sources: list[str],
    overall: dict[tuple[date, str], float | None] | None = None,
) -> dict[str, Any]:
    """Per horizon and group: the daily excess series and the stock counts."""

    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_day[item["trading_date"]].append(item)
    horizons: dict[str, Any] = {}
    for horizon, length in HORIZONS.items():
        series: dict[str, list[dict[str, Any]]] = {
            key: [] for key in group_keys(sources)
        }
        pending_days = 0
        population_days = []
        for day in sorted(by_day):
            part = results[day][horizon]
            if part["pending"]:
                pending_days += 1
                continue
            mean = part["population"]["mean"]
            liquid = part.get("liquid")
            liquid_mean = None if liquid is None else liquid["mean"]
            population_days.append(
                {
                    "t": day.isoformat(),
                    "d": part["d"],
                    **part["population"],
                    "liquid": liquid,
                }
            )
            if mean is None:
                continue
            values: dict[str, list[float]] = defaultdict(list)
            for item in by_day[day]:
                hold = part["holds"][item["id"]]
                if hold["status"] != COMPARABLE:
                    continue
                for key in groups_of(item, actions.get((item["id"], horizon))):
                    values[key].append(hold["return"])
            for key, returns in values.items():
                average = _mean(returns)
                series[key].append(
                    {
                        "t": day.isoformat(),
                        "stocks": len(returns),
                        "mean": average,
                        "excess": average - mean,
                        "liquid_excess": None
                        if liquid_mean is None
                        else average - liquid_mean,
                    }
                )
        groups = {}
        for key, days in series.items():
            excess = [row["excess"] for row in days]
            liquid_excess = [
                row["liquid_excess"] for row in days if row["liquid_excess"] is not None
            ]
            summary = {
                "days": len(excess),
                "mean": _mean(excess),
                "t": lib.t_stat(excess, overlap=length),
            }
            groups[key] = {
                **summary,
                "stocks": sum(row["stocks"] for row in days),
                "verdict": verdict(summary),
                "liquid_reference": {
                    "days": len(liquid_excess),
                    "mean": _mean(liquid_excess),
                },
                "daily": days,
            }
        horizons[horizon] = {
            "pending_days": pending_days,
            "population": population_days,
            "groups": groups,
            "ai_check": ai_check(groups[AI_KEPT]["daily"], overall or {}, horizon),
        }
    return horizons


AI_TOLERANCE = 1e-7  # the score rows round to 8 places


def ai_check(
    days: list[dict[str, Any]],
    overall: dict[tuple[date, str], float | None],
    horizon: str,
) -> dict[str, Any]:
    """The AI group's days against the champion's ``ai_version.excess`` of the
    same T: compared, and the ones that differ (listed, never adjusted)."""

    compared, differ = 0, []
    for row in days:
        expected = overall.get((date.fromisoformat(row["t"]), horizon))
        if expected is None:
            continue
        compared += 1
        if abs(row["excess"] - expected) > AI_TOLERANCE:
            differ.append({"t": row["t"], "group": row["excess"], "overall": expected})
    return {"compared": compared, "differ": differ}


def verdict(summary: dict[str, Any]) -> str:
    if summary["mean"] is None:
        return "樣本不足"
    return pr.forward_judge(summary, MIN_DAYS)


def only_source(items: list[dict[str, Any]]) -> dict[str, int]:
    """Source → selected rows whose only source it is (listed, not judged)."""

    out: dict[str, int] = defaultdict(int)
    for item in items:
        if item["selected"] and len(item["sources"]) == 1:
            out[item["sources"][0]] += 1
    return dict(out)


def build(db: Path, end: date | None) -> dict[str, Any]:
    from app.candidate_pool import SOURCES

    sources = list(SOURCES)
    engine, session = _session(db)
    try:
        items = read_items(session, end)
        by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            by_day[item["trading_date"]].append(item)
        results = {day: day_results(session, day, rows) for day, rows in by_day.items()}
        actions = ai_actions(session)
        overall = ai_overall(session)
    finally:
        session.close()
        engine.dispose()
    days = sorted(by_day)
    rejected = defaultdict(int)
    for item in items:
        if not item["selected"]:
            rejected[item["reject_reason"] or "unknown"] += 1
    return {
        "version": VERSION,
        "design": DESIGN,
        "min_days": MIN_DAYS,
        "range": [days[0].isoformat(), days[-1].isoformat()] if days else None,
        "end": end.isoformat() if end else None,
        "pool_days": len(days),
        "rows": len(items),
        "selected": sum(1 for item in items if item["selected"]),
        "rejected": dict(sorted(rejected.items())),
        "only_source": only_source(items),
        "sources": sources,
        "comparisons": len(group_keys(sources)) * len(HORIZONS),
        "horizons": collect(items, results, actions, sources, overall),
    }


# --- the report ---------------------------------------------------------------------


CHANCE_NOTE = (
    "`MIN_T` 2.0 約是單邊 2.5%：{n} 組裡大約會有 1 組純屬偶然達到「通過」或"
    "「輸給基準」（研究規則第 4 條），單一組達標要連同組數一起看"
)
LIQUID_NOTE = (
    "「對流動母體」只列出、不判定、不算進比較組數：流動母體是 T 晚上那輪 "
    "`config_json` 的流動門檻（早上那輪也用它）下 D 有日 K、沒停牌的股票；"
    "那天沒有晚上那輪寫「無資料」，不改用預設值"
)


def markdown(result: dict[str, Any], command: str) -> str:
    lines = [
        f"# 候選池的對答案（candidate_pool_score 第 {result['version']} 版，"
        f"#{result['design']}）",
        "",
    ]
    if not result["range"]:
        return "\n".join(lines + ["- 副本沒有 candidate_pool_v1 的池", ""]) + "\n"
    rejected = "、".join(f"`{k}` {v}" for k, v in result["rejected"].items()) or "0"
    lines += [
        f"- 池的交易日 T：{result['range'][0]}～{result['range'][1]}，"
        f"{result['pool_days']} 天；入選 {result['selected']} 檔次，被上限擋掉 "
        f"{rejected}",
        "- 判定：每日超額（組內可比股票的 open_hold 平均 − 同日母體平均，母體同 "
        f"`premarket_score_v1`），`forward_judge`，滿 {result['min_days']} 日才判；比較 "
        f"{result['comparisons']} 組（{len(result['sources'])} 個來源與另列的 "
        f"{result['comparisons'] // len(HORIZONS) - len(result['sources'])} 組 × "
        f"{len(HORIZONS)} 個期間）",
        "- " + CHANCE_NOTE.format(n=result["comparisons"]),
        "- 進清單的只有 16 個來源；另列的組只放在本表",
        "- " + LIQUID_NOTE,
        f"- 重現：`{command}`",
        "",
    ]
    for horizon, part in result["horizons"].items():
        check = part["ai_check"]
        lines += [
            f"## T+{horizon}",
            "",
            f"- 未到期的池日：{part['pending_days']} 天",
            f"- AI 組對 `overall` 的 `ai_version.excess`：比對 {check['compared']} 天，"
            f"不同 {len(check['differ'])} 天",
            "",
            "| 組 | 日數 | 檔次 | 只有這個來源 | 每日超額日均 | t | 判定 | 對流動母體（參考） |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
        ]
        for key, group in part["groups"].items():
            only = ""
            if key.startswith("source:"):
                only = str(result["only_source"].get(key.split(":", 1)[1], 0))
            reference = group["liquid_reference"]
            liquid = (
                "無資料"
                if group["days"] and not reference["days"]
                else lib.pct(reference["mean"], 3)
            )
            lines.append(
                f"| {label(key)} | {group['days']} | {group['stocks']} | {only} "
                f"| {lib.pct(group['mean'], 3)} | {lib.num(group['t'], 2)} "
                f"| {group['verdict']} | {liquid} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="candidate_pool_score.py", description=__doc__
    )
    parser.add_argument("--db", required=True, help="a copy_db.py copy of stock.db")
    parser.add_argument("--out", required=True)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    started = time.monotonic()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = build(db, args.end)
    command = "python tools/research/candidate_pool_score.py " + " ".join(argv)
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out.resolve()),
                "pool_days": result["pool_days"],
                "elapsed_seconds": round(time.monotonic() - started, 1),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
