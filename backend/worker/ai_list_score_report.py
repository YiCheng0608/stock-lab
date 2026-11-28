"""The monthly report of the AI list scores (Issue #1147).

``worker.cli ai-list-score-report --month YYYY-MM [--out PATH]``: markdown,
read only.  One section per prompt version and role: the reading days, the
list against the population, AI levels against the rule levels, AI picks
against the rule list, the not-applicable and failed-levels counts, and the
method groups (``app.ai_list_score.grouped``), cumulative through the month's
last day and the month alone.  A group with fewer than
``MIN_GROUP_COMPARABLE`` comparable results is 樣本不足.  The coordinator
reads it in the monthly review (``tools/research/monthly_review.py``); this
module posts nothing.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_list_score as score
from app.models import AiListReading, AiListScore
from app.premarket_ai import CHAMPION, DONE
from worker import pipeline
from worker.premarket_score_report import month_bounds, month_problem  # noqa: F401

GROUP_LABELS = {
    "setup": "型態 `setup`",
    "basis_primary": "主要依據 `basis_primary`",
    "basis": "依據含 `basis`（可重複計）",
    "confidence": "把握 `confidence`",
    "setup_confidence": "型態×把握",
    "state": "狀態（價位核對不過／今日不適用／可進場）",
}


def _mean(values: Iterable[float | None]) -> float | None:
    numbers = [value for value in values if value is not None]
    return statistics.fmean(numbers) if numbers else None


def _pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _count(value: int | None) -> str:
    return "—" if value is None else str(value)


def collect(db: Session, end: date) -> dict[tuple[str, str], dict[str, Any]]:
    """Per (prompt_version, role): the day statuses and the score rows through ``end``."""

    out: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"days": {}, "scores": []}
    )
    for session_date, version, role, status in db.execute(
        select(
            AiListReading.session_date,
            AiListReading.prompt_version,
            AiListReading.role,
            AiListReading.status,
        )
        .where(AiListReading.session_date <= end)
        .order_by(AiListReading.session_date, AiListReading.sequence)
    ):
        days = out[(version, role)]["days"]
        if days.get(session_date) != DONE:
            days[session_date] = status
    for row in db.scalars(
        select(AiListScore).where(
            AiListScore.session_date <= end,
            AiListScore.score_version == score.SCORE_VERSION,
        )
    ):
        out[(row.prompt_version, row.role)]["scores"].append(row)
    return dict(out)


def overall_part(rows: list[AiListScore], horizon: str) -> dict[str, Any]:
    items = [
        row.outcome_json
        for row in rows
        if row.scope == score.OVERALL
        and row.horizon == horizon
        and "ai_list" in row.outcome_json
    ]
    rule_days = [item for item in items if item["rule_list"]["status"] != score.NO_LIST]

    def values(key: str) -> list[float]:
        return [item[key]["value"] for item in items if item[key]["value"] is not None]

    levels, picks = values("ai_vs_rule_levels"), values("ai_vs_rule_picks")
    counts: Counter[str] = Counter()
    for item in items:
        counts.update(item["counts"])
    return {
        "days": len(items),
        "ai_excess": _mean(item["ai_list"]["open_hold"]["excess"] for item in items),
        "rule_days": len(rule_days),
        "rule_excess": _mean(
            item["rule_list"]["open_hold"]["excess"] for item in rule_days
        ),
        "levels_value": _mean(levels),
        "levels_days": len(levels),
        "levels_pairs": sum(item["ai_vs_rule_levels"]["pairs"] for item in items),
        "picks_value": _mean(picks),
        "picks_days": len(picks),
        "counts": counts,
    }


def pick_rows(rows: list[AiListScore]) -> list[dict[str, dict[str, Any] | None]]:
    """``{horizon: outcome}`` per pick (``pick_id``), in date and rank order."""

    picks: dict[int, dict[str, Any]] = {}
    order: dict[int, tuple] = {}
    for row in rows:
        if row.scope != score.STOCK or row.pick_id is None:
            continue
        picks.setdefault(row.pick_id, {})[row.horizon] = row.outcome_json
        order[row.pick_id] = (row.session_date, row.outcome_json.get("rank") or 0)
    return [picks[key] for key in sorted(picks, key=lambda key: order[key])]


def group_table(groups: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "| 組 | 筆數 | 樣本 | 有價位 | 成交 | 成交率 | 可比 | 勝率 | 平均 | 中位數 "
        "| 先碰目標一 | 先碰停損 | 都沒碰 | open_hold T+5 超額（可比） "
        "| open_hold T+20 超額（可比） | 不能比 |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for key, part in groups.items():
        triggers = part["first_trigger"]
        sample = "樣本不足" if part["status"] == score.INSUFFICIENT_SAMPLE else "足"
        reasons = "、".join(f"`{k}` {v}" for k, v in part["incomparable"].items())
        lines.append(
            f"| `{key}` | {part['n']} | {sample} | {part['levels_n']} | {part['filled']} | "
            f"{_pct(part['fill_rate'], 1)} | {part['comparable']} | "
            f"{_pct(part['win_rate'], 1)} | {_pct(part['mean'])} | {_pct(part['median'])} | "
            f"{_count(triggers[score.TARGET_HIT])} | {_count(triggers[score.STOP_HIT])} | "
            f"{_count(triggers['None'])} | "
            f"{_pct(part['open_hold_t5_excess'])}（{part['open_hold_t5_n']}） | "
            f"{_pct(part['open_hold_t20_excess'])}（{part['open_hold_t20_n']}） | "
            f"{reasons or '—'} |"
        )
    return lines


def market_table(rows: list[AiListScore]) -> list[str]:
    outcomes = [
        {"horizon": row.horizon, **row.outcome_json}
        for row in rows
        if row.scope == score.MARKET
    ]
    lines = [
        "| 大盤主要依據 | 當日天數 | 當日判對率 | T+5 天數 | T+5 判對率 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, part in score.market_groups(outcomes).items():
        d0, t5 = part["d0"], part["t5"]
        lines.append(
            f"| `{key}` | {d0['days']} | "
            + ("樣本不足" if d0["hit_rate"] is None else _pct(d0["hit_rate"], 1))
            + f" | {t5['days']} | "
            + ("樣本不足" if t5["hit_rate"] is None else _pct(t5["hit_rate"], 1))
            + " |"
        )
    return lines


def groups_block(rows: list[AiListScore], title: str) -> list[str]:
    picks = pick_rows(rows)
    lines = [f"### 依判讀方式分組：{title}", ""]
    if not picks:
        return lines + ["尚無已對答案的每檔列。", ""]
    lines.append(
        f"每檔 {len(picks)} 筆；`ai_levels` 看 T+20，可比 < {score.MIN_GROUP_COMPARABLE} 的組"
        "標樣本不足，只列筆數；open_hold 超額的可比也要滿同一門檻才列。"
    )
    lines.append("")
    for name, groups in score.grouped(picks).items():
        lines += [f"**{GROUP_LABELS[name]}**", "", *group_table(groups), ""]
    lines += ["**大盤**", "", *market_table(rows), ""]
    return lines


def section(version: str, role: str, data: dict[str, Any], start: date) -> list[str]:
    days = data["days"]
    statuses = Counter(days.values())
    month_statuses = Counter(status for day, status in days.items() if day >= start)
    rows = data["scores"]
    lines = [
        f"## `{version}`／`{role}`",
        "",
        f"- 判讀日 {len(days)} 天：`done` {statuses.get(DONE, 0)}、`failed` "
        f"{statuses.get('failed', 0)}、`rejected` {statuses.get('rejected', 0)}"
        + (f"（{min(days).isoformat()}～{max(days).isoformat()}）" if days else ""),
        f"- 當月：`done` {month_statuses.get(DONE, 0)}、`failed` "
        f"{month_statuses.get('failed', 0)}、`rejected` {month_statuses.get('rejected', 0)}",
        "",
        "| 整體 | 天數 | AI 名單 open_hold 超額 | 規則名單超額（有名單天數） "
        "| AI 價位對規則價位（天數，配對檔數） | AI 選股對規則選股（天數） |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    parts = {horizon: overall_part(rows, horizon) for horizon in score.STOCK_HORIZONS}
    for horizon, part in parts.items():
        lines.append(
            f"| {horizon.upper()} | {part['days']} | {_pct(part['ai_excess'])} | "
            f"{_pct(part['rule_excess'])}（{part['rule_days']}） | "
            f"{_pct(part['levels_value'])}（{part['levels_days']}，{part['levels_pairs']}） | "
            f"{_pct(part['picks_value'])}（{part['picks_days']}） |"
        )
    counts = parts[score.LEVELS_HORIZON]["counts"]
    lines += [
        "",
        f"- T+20 已對答案的每檔 {counts.get('picks', 0)} 筆：價位核對不過 "
        f"{counts.get('levels_check_failed', 0)}、今日不適用 {counts.get('not_applicable', 0)}、"
        f"沒有規則價位 {counts.get('no_rule_levels', 0)}、名單日到 D 有除權息 "
        f"{counts.get('corporate_action_on_session', 0)}",
        "",
    ]
    lines += groups_block(rows, "累積")
    lines += groups_block([row for row in rows if row.session_date >= start], "當月")
    return lines


def render(db: Session, month: str) -> str:
    start, end = month_bounds(month)
    data = collect(db, end)
    lines = [
        f"# AI 名單對答案月報 {month}（累積到 {end.isoformat()}）",
        "",
        f"口徑 `{score.SCORE_VERSION}`（docs/spec/ai_list.md「對答案」）。數字是每天 "
        "`ai_list_score` 寫的對答案列；超額與差是每日值的平均，報酬已扣 30 bps 與滑價。"
        "規則名單是對答案的基準：只記錄，不提案。AI 名單不能回測，以上線後的逐日紀錄判定。",
        "",
    ]
    if not data:
        lines += ["尚無判讀紀錄。", ""]
        return "\n".join(lines)
    ordered = sorted(data.items(), key=lambda item: (item[0][1] != CHAMPION, item[0]))
    for (version, role), part in ordered:
        lines += section(version, role, part, start)
    return "\n".join(lines)


def run(month: str, out: str | None = None) -> str:
    """The month's report; also written to ``out`` when given."""

    with pipeline.SessionLocal() as db:
        text = render(db, month)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    return text
