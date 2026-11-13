"""How did the candidates the product actually listed do afterwards?

Read only (``mode=ro`` + ``query_only``); refuses the production database as
``backtest_research.py`` does.  Reads a ``tools/ops/copy_db.py`` copy and writes
``summary.md`` and ``tables.json`` to ``--out``.

The candidates are the rows ``daily`` saved (``daily_candidates`` of a
``success`` run): what 今日可買 showed that evening, never recomputed.  A day
with runs of more than one score version counts the highest version only, the
one the pages read.  Each candidate is bought at the open of T+1 and valued at
the close of T+5／T+20 (``evidence_lib.forward_return``): a plain hold, not the
tracking's target and stop, so the number says whether the list picks stocks,
apart from how they are then traded.

Per horizon it reports the candidates' return before and after costs
(``--cost-bps``), their excess over the mean of the same day's tradable
universe (``evidence_lib.universe``) and over TAIEX, and the share of
candidates above the universe's mean; then the same by rank, strategy, score
version and month.  ``ranking`` asks whether a higher score did better among
the candidates of one day: the mean daily rank correlation of the forward
return with the total score and with each component's score (days with at
least ``MIN_RANKED`` comparable candidates).

``t`` counts the days as ``days / horizon`` (``evidence_lib.t_stat``).  A
candidate whose T+N is after the last session is ``pending``, not missing.
These are a few weeks to months of one market: a record to keep adding to,
not a win rate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_lib as lib  # noqa: E402

RAW_DIR_NAME = ".raw-unused"
MIN_RANKED = 5
RANK_BUCKETS = ((1, 5, "第 1～5 名"), (6, 10, "第 6～10 名"), (11, 20, "第 11～20 名"))
COMPONENTS = ("technical", "chips", "group", "news_sentiment")
COMPONENT_LABELS = {
    "total": "總分",
    "technical": "技術",
    "chips": "籌碼",
    "group": "族群",
    "news_sentiment": "新聞情緒",
}
# Calendar days of bars read before the first candidate day: the universe's
# floor needs 20 sessions.
PANEL_LEAD_DAYS = 60


def version_number(score_version: str) -> int:
    match = re.search(r"(\d+)$", score_version)
    return int(match.group(1)) if match else -1


def read_candidates(con, start: date | None, end: date | None) -> list[dict[str, Any]]:
    """The saved candidates, one score version per day (the highest)."""

    rows = con.execute(
        "select c.trading_date, c.instrument_id, c.rank, c.strategy, c.score_version, "
        "c.total_score, c.components_json from daily_candidates c "
        "join candidate_runs r on r.id = c.candidate_run_id "
        "where r.status = 'success' order by c.trading_date, c.rank"
    ).fetchall()
    version: dict[str, str] = {}
    for day, *_rest, score_version, _total, _components in rows:
        if day not in version or version_number(score_version) > version_number(
            version[day]
        ):
            version[day] = score_version
    out = []
    for day, instrument_id, rank, strategy, score_version, total, components in rows:
        trading_date = date.fromisoformat(day)
        if score_version != version[day]:
            continue
        if (start and trading_date < start) or (end and trading_date > end):
            continue
        parsed = json.loads(components) if isinstance(components, str) else components
        scores = {"total": total}
        for name in COMPONENTS:
            scores[name] = ((parsed or {}).get(name) or {}).get("score")
        out.append(
            {
                "day": trading_date,
                "instrument_id": instrument_id,
                "rank": rank,
                "strategy": strategy,
                "score_version": score_version,
                "scores": scores,
            }
        )
    return out


def measure(
    panel: lib.Panel, candidates: list[dict[str, Any]], horizon: int, min_lots: float
) -> list[dict[str, Any]]:
    """Each candidate with its forward return and the day's two baselines."""

    baselines: dict[date, float | None] = {}
    rows = []
    for candidate in candidates:
        day = candidate["day"]
        if day not in baselines:
            known = [
                value
                for item, at in lib.universe(panel, day, min_lots)
                if (value := lib.forward_return(item, at, horizon)) is not None
            ]
            baselines[day] = statistics.fmean(known) if known else None
        item = panel.series.get(candidate["instrument_id"])
        at = item.position.get(day) if item else None
        forward = lib.forward_return(item, at, horizon) if at is not None else None
        rows.append(
            {
                **candidate,
                "return": forward,
                "pending": forward is None and lib.is_pending(panel, day, horizon),
                "universe": baselines[day],
                "index": lib.index_return(panel, day, horizon),
            }
        )
    return rows


def table(rows: list[dict[str, Any]], horizon: int, cost: float) -> dict[str, Any]:
    """Counts and averages of one group of measured candidates."""

    known = [row for row in rows if row["return"] is not None]
    out: dict[str, Any] = {
        "candidates": len(rows),
        "pending": sum(1 for row in rows if row["pending"]),
        "comparable": len(known),
        "days": len({row["day"] for row in known}),
    }
    if not known:
        return out
    gross = [row["return"] for row in known]
    out["gross"] = lib.summary(gross)
    out["net"] = lib.summary([value - cost for value in gross])
    versus = [row for row in known if row["universe"] is not None]
    excess = [row["return"] - row["universe"] for row in versus]
    out["excess_universe"] = lib.summary(excess)
    by_day: dict[date, list[float]] = defaultdict(list)
    for row, value in zip(versus, excess):
        by_day[row["day"]].append(value)
    daily = [statistics.fmean(by_day[day]) for day in sorted(by_day)]
    out["daily_excess"] = {
        "days": len(daily),
        "mean": statistics.fmean(daily) if daily else None,
        "positive": (sum(1 for value in daily if value > 0) / len(daily))
        if daily
        else None,
        "t": lib.t_stat(daily, horizon),
        "t_naive": lib.t_stat(daily),
    }
    indexed = [
        row["return"] - row["index"] for row in known if row["index"] is not None
    ]
    out["excess_index"] = lib.summary(indexed)
    return out


def ranking(rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    """Mean daily rank correlation of the forward return with each score."""

    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["return"] is not None:
            by_day[row["day"]].append(row)
    out = {}
    for name in ("total", *COMPONENTS):
        daily = []
        for day in sorted(by_day):
            pairs = [
                (row["scores"][name], row["return"])
                for row in by_day[day]
                if row["scores"].get(name) is not None
            ]
            if len(pairs) < MIN_RANKED:
                continue
            ic = lib.spearman([pair[0] for pair in pairs], [pair[1] for pair in pairs])
            if ic is not None:
                daily.append(ic)
        out[name] = {
            "days": len(daily),
            "ic": statistics.fmean(daily) if daily else None,
            "positive": (sum(1 for value in daily if value > 0) / len(daily))
            if daily
            else None,
            "t": lib.t_stat(daily, horizon),
        }
    return out


def _groups(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    groups: dict[str, dict[str, list]] = {
        "rank": {},
        "strategy": defaultdict(list),
        "score_version": defaultdict(list),
        "month": defaultdict(list),
    }
    for low, high, label in RANK_BUCKETS:
        groups["rank"][label] = [row for row in rows if low <= row["rank"] <= high]
    for row in rows:
        groups["strategy"][row["strategy"]].append(row)
        groups["score_version"][row["score_version"]].append(row)
        groups["month"][row["day"].strftime("%Y-%m")].append(row)
    return groups


def build(
    db: Path,
    start: date | None,
    end: date | None,
    min_lots: float,
    cost_bps: float,
    raw_dir: Path,
) -> dict[str, Any]:
    con = lib.connect_read_only(db)
    try:
        candidates = read_candidates(con, start, end)
    finally:
        con.close()
    result: dict[str, Any] = {
        "candidates": len(candidates),
        "days": len({candidate["day"] for candidate in candidates}),
        "range": [
            candidates[0]["day"].isoformat() if candidates else None,
            candidates[-1]["day"].isoformat() if candidates else None,
        ],
        "min_lots": min_lots,
        "cost_bps": cost_bps,
        "horizons": {},
    }
    if not candidates:
        return result
    panel_start = date.fromordinal(candidates[0]["day"].toordinal() - PANEL_LEAD_DAYS)
    panel = lib.load_panel(db, panel_start, raw_dir)
    result["last_session"] = panel.sessions[-1].isoformat() if panel.sessions else None
    cost = cost_bps / 10_000.0
    for horizon in lib.HORIZONS:
        rows = measure(panel, candidates, horizon, min_lots)
        result["horizons"][str(horizon)] = {
            "all": table(rows, horizon, cost),
            "ranking": ranking(rows, horizon),
            **{
                name: {key: table(group, horizon, cost) for key, group in parts.items()}
                for name, parts in _groups(rows).items()
            },
        }
    return result


# --- the report --------------------------------------------------------------

HEAD = (
    "| 分組 | 候選 | 未到期 | 可比較 | 平均（扣成本） | 中位數（扣成本） | 正報酬 "
    "| 對母體超額 | 贏過母體平均 | 對加權超額 | 每日超額 t |\n"
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
)


def _line(label: str, part: dict[str, Any]) -> str:
    if not part.get("comparable"):
        cells = ["—"] * 7
    else:
        cells = [
            lib.pct(part["net"]["mean"]),
            lib.pct(part["net"]["median"]),
            lib.pct(part["net"]["positive"], 1),
            lib.pct(part["excess_universe"].get("mean")),
            lib.pct(part["excess_universe"].get("positive"), 1),
            lib.pct(part["excess_index"].get("mean")),
            lib.num(part["daily_excess"]["t"], 2),
        ]
    counts = f"{part['candidates']} | {part['pending']} | {part['comparable']}"
    return f"| {label} | {counts} | {' | '.join(cells)} |"


def markdown(result: dict[str, Any], command: str) -> str:
    lines = [
        "# 候選成績單（candidate_scorecard）",
        "",
        f"- 候選：{result['range'][0]}～{result['range'][1]}，{result['days']} 個交易日、"
        f"{result['candidates']} 檔次（`daily` 當晚存下的名單，不重算）",
        f"- 行情到 {result.get('last_session')}；T+N 還沒到的記「未到期」",
        "- 報酬：T+1 開盤買（含 5 bps 滑價）、T+N 收盤計價，單純持有，不套用停損與目標",
        f"- 成本：來回 {result['cost_bps']:g} bps（兩次手續費 0.1425% 加證交稅 0.3%，未折讓）",
        f"- 母體：同一天有成交、20 日均量 ≥ {result['min_lots']:g} 張的股票與 IPO 的平均；"
        "超額報酬與成本無關",
        "- t 值把天數以「日數 ÷ N」計，是保守的下限",
        f"- 重現：`{command}`",
        "",
    ]
    for horizon, tables in result["horizons"].items():
        lines += [f"## T+{horizon}", "", HEAD, _line("全部", tables["all"])]
        for name, title in (
            ("rank", "名次"),
            ("strategy", "策略"),
            ("score_version", "評分版本"),
            ("month", "月份"),
        ):
            for key in tables[name] if name == "rank" else sorted(tables[name]):
                lines.append(_line(f"{title}：{key}", tables[name][key]))
        lines += [
            "",
            f"### T+{horizon}：分數高的有沒有比較好",
            "",
            f"同一天的候選裡，分數與之後報酬的排序相關（至少 {MIN_RANKED} 檔可比較的日子）。",
            "",
            "| 分數 | 日數 | 平均 IC | IC 為正的日數比例 | t |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for name, part in tables["ranking"].items():
            lines.append(
                f"| {COMPONENT_LABELS[name]} | {part['days']} | {lib.num(part['ic'])} "
                f"| {lib.pct(part['positive'], 1)} | {lib.num(part['t'], 2)} |"
            )
        lines.append("")
    lines += [
        "## 樣本限制",
        "",
        "- 只有上線以來的名單，期間短、市況單一；這是持續累積的紀錄，不是勝率。",
        "- 同一檔連續幾天入選各算一筆，報酬期間重疊。",
        "- 不含部位大小、漲跌停買不到與成交量限制。",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candidate_scorecard.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a tools/ops/copy_db.py copy")
    parser.add_argument("--out", required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--min-lots", type=float, default=lib.DEFAULT_MIN_LOTS)
    parser.add_argument("--cost-bps", type=float, default=lib.DEFAULT_COST_BPS)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problem = lib.production_problem(db, dict(os.environ))
    if problem or not db.is_file():
        print(json.dumps({"refused": [problem or f"{db} does not exist"]}))
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = build(
        db, args.start, args.end, args.min_lots, args.cost_bps, out / RAW_DIR_NAME
    )
    command = "python tools/research/candidate_scorecard.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    print(json.dumps({"out": str(out.resolve()), "candidates": result["candidates"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
