"""The monthly report of the pre-market AI scores (Issue #1043).

``worker.cli premarket-score-report --month YYYY-MM [--out PATH]``: markdown,
read only.  The cumulative numbers of every prompt version and role from the
first reading through the month's last day, one section each, as
``premarket_score`` wrote them; fewer than ``REPORT_MIN_DAYS`` scored trading
days is ``insufficient_sample``.  With a shadow version, the two switch
conditions (docs/spec/premarket_ai.md 對答案) on the days both versions were
scored.  The coordinator posts it to #1 on the first trading day of the
next month; this module posts nothing.
"""

from __future__ import annotations

import calendar
import re
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import premarket_score as score
from app.models import PremarketAiReading, PremarketAiScore
from app.premarket_ai import CHAMPION, DONE, SHADOW
from worker import pipeline

STANCES = ("bullish", "neutral", "bearish")
REALIZED = ("up", "flat", "down")


def month_bounds(month: str) -> tuple[date, date]:
    year, number = (int(part) for part in month.split("-", 1))
    return date(year, number, 1), date(
        year, number, calendar.monthrange(year, number)[1]
    )


def _mean(values: Iterable[float | None]) -> float | None:
    numbers = [value for value in values if value is not None]
    return statistics.fmean(numbers) if numbers else None


def _median(values: Iterable[float | None]) -> float | None:
    numbers = [value for value in values if value is not None]
    return statistics.median(numbers) if numbers else None


def _pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def collect(db: Session, end: date) -> dict[tuple[str, str], dict[str, Any]]:
    """Per (prompt_version, role): the day statuses and the score rows through ``end``."""

    out: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"days": {}, "scores": []}
    )
    for reading in db.scalars(
        select(PremarketAiReading)
        .where(PremarketAiReading.session_date <= end)
        .order_by(PremarketAiReading.session_date, PremarketAiReading.sequence)
    ):
        days = out[(reading.prompt_version, reading.role)]["days"]
        # The day's reading: its done row, else its latest row.
        if days.get(reading.session_date) != DONE:
            days[reading.session_date] = reading.status
    for row in db.scalars(
        select(PremarketAiScore).where(
            PremarketAiScore.session_date <= end,
            PremarketAiScore.score_version == score.SCORE_VERSION,
        )
    ):
        out[(row.prompt_version, row.role)]["scores"].append(row)
    return dict(out)


def market_part(rows: list[PremarketAiScore], horizon: str) -> dict[str, Any]:
    scored = [
        row.outcome_json
        for row in rows
        if row.scope == score.MARKET
        and row.horizon == horizon
        and row.outcome_json.get("status") == "scored"
    ]
    table: Counter[tuple[str, str]] = Counter(
        (item["stance"], item["realized"]) for item in scored
    )
    by_stance = {
        stance: _mean(item["return"] for item in scored if item["stance"] == stance)
        for stance in STANCES
    }
    hits = sum(1 for item in scored if item["hit"])
    no_data = sum(
        1
        for row in rows
        if row.scope == score.MARKET
        and row.horizon == horizon
        and row.outcome_json.get("status") != "scored"
    )
    return {
        "days": len(scored),
        "no_data": no_data,
        "hit_rate": hits / len(scored) if scored else None,
        "table": table,
        "by_stance": by_stance,
    }


def overall_part(rows: list[PremarketAiScore], horizon: str) -> dict[str, Any]:
    items = [
        row.outcome_json
        for row in rows
        if row.scope == score.OVERALL
        and row.horizon == horizon
        and "ai_version" in row.outcome_json
    ]
    rule_days = [
        item["rule_version"]
        for item in items
        if item["rule_version"]["status"] != score.NO_LIST
    ]
    return {
        "days": len(items),
        "ai_excess": _mean(item["ai_version"]["excess"] for item in items),
        "rule_days": len(rule_days),
        "no_list_days": len(items) - len(rule_days),
        "rule_excess": _mean(item["excess"] for item in rule_days),
        "value_open_hold": _mean(item["value_open_hold"]["value"] for item in items),
        "value_days": sum(
            1 for item in items if item["value_open_hold"]["value"] is not None
        ),
        "value_levels": _mean(item["levels"]["value"] for item in items),
        "value_levels_days": sum(
            1 for item in items if item["levels"]["value"] is not None
        ),
    }


def stock_part(rows: list[PremarketAiScore], horizon: str) -> dict[str, dict[str, Any]]:
    """Per effective action: the pooled D-open holds and tracking_v2 results."""

    out: dict[str, dict[str, Any]] = {}
    stocks = [
        row.outcome_json
        for row in rows
        if row.scope == score.STOCK and row.horizon == horizon
    ]
    for action in score.ACTIONS:
        mine = [item for item in stocks if item["effective_action"] == action]
        holds = [
            item["open_hold"]["return"]
            for item in mine
            if item["open_hold"]["status"] == "comparable"
        ]
        levels = []
        for item in mine:
            part = item.get("levels")
            if part is None:
                continue
            result = (
                part["repriced_result"] if action == score.REPRICE else part["original"]
            )
            if result and result.get("status") == "comparable":
                levels.append(result["return"])
        out[action] = {
            "n": len(mine),
            "hold_n": len(holds),
            "hold_mean": _mean(holds),
            "hold_median": _median(holds),
            "levels_n": len(levels),
            "levels_mean": _mean(levels),
        }
    return out


def _sample(days: int, minimum: int) -> str:
    return score.INSUFFICIENT_SAMPLE if days < minimum else "sufficient"


def section(version: str, role: str, data: dict[str, Any]) -> list[str]:
    days = data["days"]
    statuses = Counter(days.values())
    rows = data["scores"]
    d0 = market_part(rows, "d0")
    lines = [
        f"## `{version}`／`{role}`",
        "",
        f"- 判讀日 {len(days)} 天：`done` {statuses.get(DONE, 0)}、`failed` "
        f"{statuses.get('failed', 0)}、`rejected` {statuses.get('rejected', 0)}"
        + (f"（{min(days).isoformat()}～{max(days).isoformat()}）" if days else ""),
        f"- 大盤當日已對答案 {d0['days']} 天：**{_sample(d0['days'], score.REPORT_MIN_DAYS)}**"
        f"（滿 {score.REPORT_MIN_DAYS} 個交易日才下結論）",
        "",
        "| 大盤 | 天數 | 判對率 | 無資料 | 看多平均 | 中性平均 | 看空平均 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon, label in (("d0", "當日"), ("t5", "T+5")):
        part = market_part(rows, horizon)
        lines.append(
            f"| {label} | {part['days']} | {_pct(part['hit_rate'], 1)} | {part['no_data']} | "
            + " | ".join(_pct(part["by_stance"][stance]) for stance in STANCES)
            + " |"
        )
    lines += [
        "",
        "當日的判讀×實際（天數）：",
        "",
        "| 判讀＼實際 | 漲 | 平 | 跌 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for stance in STANCES:
        lines.append(
            f"| `{stance}` | "
            + " | ".join(str(d0["table"].get((stance, real), 0)) for real in REALIZED)
            + " |"
        )
    lines += [
        "",
        "| 整體 | 天數 | AI 版本超額 | 規則版本超額（有名單天數） | AI 判讀的價值 open_hold（天數） | AI 判讀的價值 levels（天數，參考） |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in score.STOCK_HORIZONS:
        part = overall_part(rows, horizon)
        lines.append(
            f"| {horizon.upper()} | {part['days']} | {_pct(part['ai_excess'])} | "
            f"{_pct(part['rule_excess'])}（{part['rule_days']}） | "
            f"{_pct(part['value_open_hold'])}（{part['value_days']}） | "
            f"{_pct(part['value_levels'])}（{part['value_levels_days']}） |"
        )
    lines += [
        "",
        "| 每檔（有效動作） | 期間 | 筆數 | open_hold 可比 | 平均 | 中位數 | levels 可比 | levels 平均 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in score.STOCK_HORIZONS:
        for action, part in stock_part(rows, horizon).items():
            lines.append(
                f"| `{action}` | {horizon.upper()} | {part['n']} | {part['hold_n']} | "
                f"{_pct(part['hold_mean'])} | {_pct(part['hold_median'])} | "
                f"{part['levels_n']} | {_pct(part['levels_mean'])} |"
            )
    lines.append("")
    return lines


def _by_day(rows: list[PremarketAiScore], scope: str, horizon: str) -> dict[date, dict]:
    return {
        row.session_date: row.outcome_json
        for row in rows
        if row.scope == scope and row.horizon == horizon
    }


def switch_section(
    champion: tuple[str, dict[str, Any]], shadow: tuple[str, dict[str, Any]]
) -> list[str]:
    """The two switch conditions on the days both versions were scored."""

    old_market = _by_day(champion[1]["scores"], score.MARKET, "d0")
    new_market = _by_day(shadow[1]["scores"], score.MARKET, "d0")
    old_value = _by_day(champion[1]["scores"], score.OVERALL, "t5")
    new_value = _by_day(shadow[1]["scores"], score.OVERALL, "t5")
    market_days = sorted(
        day
        for day in set(old_market) & set(new_market)
        if old_market[day].get("status") == "scored"
        and new_market[day].get("status") == "scored"
    )

    def value(item):
        return (item.get("value_open_hold") or {}).get("value")

    value_days = sorted(
        day
        for day in set(old_value) & set(new_value)
        if value(old_value[day]) is not None and value(new_value[day]) is not None
    )

    def rate(market, days):
        return (
            sum(1 for day in days if market[day]["hit"]) / len(days) if days else None
        )

    old_rate, new_rate = rate(old_market, market_days), rate(new_market, market_days)
    old_mean = _mean(value(old_value[day]) for day in value_days)
    new_mean = _mean(value(new_value[day]) for day in value_days)
    first = old_rate is not None and new_rate is not None and new_rate >= old_rate
    second = old_mean is not None and new_mean is not None and new_mean > old_mean
    days = min(len(market_days), len(value_days))
    return [
        f"## 換版條件：`{shadow[0]}`（shadow）對 `{champion[0]}`（champion）",
        "",
        f"- 同一批交易日：大盤 {len(market_days)} 天、價值 {len(value_days)} 天："
        f"**{_sample(days, score.SHADOW_MIN_DAYS)}**（至少 {score.SHADOW_MIN_DAYS} 個交易日）",
        "",
        "| 條件 | champion | shadow | 過 |",
        "| --- | ---: | ---: | --- |",
        f"| 大盤當日判對率不低於 | {_pct(old_rate, 1)} | {_pct(new_rate, 1)} | {'是' if first else '否'} |",
        f"| AI 判讀的價值 open_hold T+5 高於 | {_pct(old_mean)} | {_pct(new_mean)} | {'是' if second else '否'} |",
        "",
    ]


def render(db: Session, month: str) -> str:
    _start, end = month_bounds(month)
    data = collect(db, end)
    lines = [
        f"# 早盤 AI 判讀對答案月報 {month}（累積到 {end.isoformat()}）",
        "",
        f"口徑 `{score.SCORE_VERSION}`（docs/spec/premarket_ai.md「對答案」）。數字是每天 "
        "`premarket_score` 寫的對答案列；超額與價值是每日值的平均，報酬已扣 30 bps 與滑價。"
        "早盤 AI 判讀不能回測，以上線後的逐日紀錄判定。",
        "",
    ]
    if not data:
        lines += ["尚無判讀紀錄。", ""]
        return "\n".join(lines)
    ordered = sorted(data.items(), key=lambda item: (item[0][1] != CHAMPION, item[0]))
    for (version, role), part in ordered:
        lines += section(version, role, part)
    champions = [(key[0], part) for key, part in ordered if key[1] == CHAMPION]
    shadows = [(key[0], part) for key, part in ordered if key[1] == SHADOW]
    if champions and shadows:
        for shadow in shadows:
            lines += switch_section(champions[-1], shadow)
    return "\n".join(lines)


def month_problem(month: str) -> str | None:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        return "--month 要是 YYYY-MM"
    return None


def run(month: str, out: str | None = None) -> str:
    """The month's report; also written to ``out`` when given."""

    # pipeline.SessionLocal, like the daily steps (and their test patches).
    with pipeline.SessionLocal() as db:
        text = render(db, month)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    return text
