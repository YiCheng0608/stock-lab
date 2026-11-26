"""The month's pre-market AI readings that turned out wrong (#1069).

docs/spec/premarket_ai.md 判錯清單與改版提案: from the champion's ``done``
readings, the cases the rules frozen here call wrong, each with what the
reading saw (its stock's ``input_json.candidates`` entry and the market part
of the input), what it said (action, re-price rule, reasons) and what
happened (the ``premarket_score_v1`` rows already written: nothing is
recomputed).  Beside them as many cases it got right, sorted the same way, so
a proposal does not learn from the misses alone (#1004 第 4 點).

``cases.json`` is what ``prompt_proposal.py`` reads; ``cases.md`` is for the
coordinator.  Read only (``mode=ro`` + ``query_only``), refused as
``exit_research`` refuses.  Only the columns used are selected: a reading row
carries its whole input and output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402

VERSION = 1
DESIGN = "1069"
CASES = "cases.json"
REPORT = "cases.md"


def _session(db: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://", creator=lambda: lib.connect_read_only(db))
    return engine, Session(engine)


def month_bounds(month: str) -> tuple[date, date]:
    from worker.premarket_score_report import month_bounds as bounds

    return bounds(month)


# --- reading the copy ---------------------------------------------------------------


def day_statuses(session, version: str, end: date) -> dict[date, str]:
    """The champion's day status through ``end``: its done row, else its
    latest (``premarket_score_report.collect``'s rule)."""

    from sqlalchemy import select

    from app.models import PremarketAiReading as Reading
    from app.premarket_ai import CHAMPION, DONE

    days: dict[date, str] = {}
    for session_date, status in session.execute(
        select(Reading.session_date, Reading.status)
        .where(
            Reading.role == CHAMPION,
            Reading.prompt_version == version,
            Reading.session_date <= end,
        )
        .order_by(Reading.session_date, Reading.sequence)
    ):
        if days.get(session_date) != DONE:
            days[session_date] = status
    return days


def done_readings(session, version: str, end: date) -> dict[int, dict[str, Any]]:
    """Reading id → the champion's done readings through ``end`` (no input)."""

    from sqlalchemy import select

    from app.models import PremarketAiReading as Reading
    from app.premarket_ai import CHAMPION, DONE

    out = {}
    for row in session.execute(
        select(
            Reading.id,
            Reading.session_date,
            Reading.list_date,
            Reading.pool_phase,
            Reading.llm_model,
            Reading.output_json,
        ).where(
            Reading.role == CHAMPION,
            Reading.prompt_version == version,
            Reading.status == DONE,
            Reading.session_date <= end,
        )
    ):
        out[row.id] = {
            "id": row.id,
            "session_date": row.session_date,
            "list_date": row.list_date,
            "pool_phase": row.pool_phase,
            "llm_model": row.llm_model,
            "market": (row.output_json or {}).get("market") or {},
            "data_gaps": (row.output_json or {}).get("data_gaps") or [],
        }
    return out


def reading_inputs(session, ids: list[int]) -> dict[int, dict[str, Any]]:
    """Reading id → its ``input_json``, for the readings that have a case only."""

    from sqlalchemy import select

    from app.models import PremarketAiReading as Reading

    if not ids:
        return {}
    return {
        reading_id: payload or {}
        for reading_id, payload in session.execute(
            select(Reading.id, Reading.input_json).where(Reading.id.in_(ids))
        )
    }


def stocks(session, reading_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Stock row id → the AI's call on one pool stock."""

    from sqlalchemy import select

    from app.models import PremarketAiStock as Stock

    out = {}
    if not reading_ids:
        return out
    for row in session.execute(
        select(
            Stock.id,
            Stock.reading_id,
            Stock.symbol,
            Stock.position,
            Stock.on_today_list,
            Stock.pool_sources_json,
            Stock.levels_json,
            Stock.action,
            Stock.reprice_rule_json,
            Stock.reasons_json,
        ).where(Stock.reading_id.in_(reading_ids))
    ):
        out[row.id] = {
            "id": row.id,
            "reading_id": row.reading_id,
            "symbol": row.symbol,
            "position": row.position,
            "on_today_list": bool(row.on_today_list),
            "pool_sources": row.pool_sources_json or [],
            "levels": row.levels_json,
            "action": row.action,
            "reprice_rule": row.reprice_rule_json,
            "reasons": row.reasons_json or [],
        }
    return out


def scores(session, reading_ids: list[int]) -> dict[tuple[int, str, str, str], dict]:
    """(reading id, scope, subject, horizon) → the written outcome."""

    from sqlalchemy import select

    from app import premarket_score as score
    from app.models import PremarketAiScore as Score

    out = {}
    if not reading_ids:
        return out
    for row in session.execute(
        select(
            Score.reading_id,
            Score.stock_id,
            Score.scope,
            Score.subject,
            Score.horizon,
            Score.outcome_json,
        ).where(
            Score.reading_id.in_(reading_ids),
            Score.score_version == score.SCORE_VERSION,
        )
    ):
        out[(row.reading_id, row.scope, row.subject, row.horizon)] = {
            "stock_id": row.stock_id,
            **(row.outcome_json or {}),
        }
    return out


def market_input(payload: dict[str, Any], cited: set[str]) -> dict[str, Any]:
    """The market part of a reading's input: the index, US, TX and news counts,
    and the market news its reasons cited."""

    news = [
        item
        for item in payload.get("market_news") or []
        if f"news:{item.get('id')}" in cited
    ]
    return {
        "session_date": payload.get("session_date"),
        "list_date": payload.get("list_date"),
        "taiex": payload.get("taiex"),
        "us_indices": payload.get("us_indices"),
        "tx_futures": payload.get("tx_futures"),
        "overnight_news_stats": payload.get("overnight_news_stats"),
        "cited_market_news": news,
    }


def candidate_input(payload: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    for item in payload.get("candidates") or []:
        if item.get("symbol") == symbol:
            return item
    return None


# --- the rules (docs/spec/premarket_ai.md 判錯清單與改版提案) ------------------------
#
# Frozen before the first real run (#1069 決定 7203530697); a change is a new VERSION.

ERROR, CONTROL = "error", "control"
MARKET = "market"
DEFER = "defer"  # 有效動作 defer，之後卻漲
LEVELS = "levels_stop"  # 有規則價位的 keep／reprice，觸停損
NO_LEVELS = "no_levels_keep"  # 沒有規則價位的 keep，之後卻跌
CATEGORIES = (MARKET, DEFER, LEVELS, NO_LEVELS)
CATEGORY_TEXT = {
    MARKET: "大盤當日判錯",
    DEFER: "defer 卻漲",
    LEVELS: "keep／reprice 卻觸停損",
    NO_LEVELS: "沒有規則價位的 keep 卻跌",
}
ERROR_EXCESS = 0.03
STOP_TRIGGER = "invalidated"
TARGET_TRIGGER = "target_1_hit"
MAX_CASES = 30
MIN_MARKET_DAYS = 15
MIN_ERRORS = 10
OK = "ok"
INSUFFICIENT = "insufficient_sample"
SHADOW_EXISTS = "shadow_exists"
GATE_TEXT = {
    OK: "達到提案門檻，跑 prompt_proposal.py",
    INSUFFICIENT: "樣本不足，不提案",
    SHADOW_EXISTS: "已有 shadow，不提案",
}
PENDING = "pending"  # the row is not written yet: its result is in a later month
INCOMPARABLE = "incomparable"


def _excess(hold: dict[str, Any] | None, population: float | None) -> float | None:
    if not hold or hold.get("status") != "comparable" or population is None:
        return None
    value = hold.get("return")
    return None if value is None else value - population


def _month(day: str | None) -> str | None:
    return day[:7] if day else None


def judge_market(row: dict[str, Any] | None) -> dict[str, Any]:
    """The reading's market call at ``d0``: wrong, right, or not judged."""

    if row is None:
        return {"verdict": PENDING}
    if row.get("status") != "scored":
        return {"verdict": INCOMPARABLE, "reason": row.get("reason")}
    return {
        "verdict": CONTROL if row.get("hit") else ERROR,
        "category": MARKET,
        "result_date": row.get("close_date"),
        "key": abs(row.get("return") or 0.0),
        "outcome": {
            key: row.get(key)
            for key in ("stance", "confidence", "return", "realized", "band", "hit")
        },
    }


def judge_stock(
    stock: dict[str, Any],
    rows: dict[str, dict[str, Any] | None],
    populations: dict[str, float | None],
) -> dict[str, Any]:
    """One stock of one reading: at most one case (Q7).  ``rows`` and
    ``populations`` by horizon (``t5``, ``t20``)."""

    from app import premarket_score as score

    t5, t20 = rows.get("t5"), rows.get("t20")
    first = t5 or t20
    if first is None:
        return {"verdict": PENDING}
    action = first.get("effective_action")
    levelled = score.has_levels(stock["levels"]) and action in (score.KEEP, score.REPRICE)
    if levelled:
        if t20 is None:
            return {"verdict": PENDING}
        part = t20.get("levels") or {}
        result = (
            part.get("original") if action == score.KEEP else part.get("repriced_result")
        ) or {}
        excess = _excess(t20.get("open_hold"), populations.get("t20"))
        outcome = {
            "horizon": "t20",
            "first_trigger": result.get("first_trigger"),
            "levels_status": result.get("status"),
            "levels_return": result.get("return"),
            "open_hold_return": (t20.get("open_hold") or {}).get("return"),
            "population_mean": populations.get("t20"),
            "excess": excess,
        }
        trigger = result.get("first_trigger")
        if trigger == STOP_TRIGGER:
            verdict = ERROR
        elif trigger == TARGET_TRIGGER:
            verdict = CONTROL
        elif result.get("status") != "comparable" and trigger is None:
            return {"verdict": INCOMPARABLE, "reason": result.get("reason")}
        else:
            return {"verdict": None}
        return {
            "verdict": verdict,
            "category": LEVELS,
            "result_date": (t20.get("open_hold") or {}).get("exit_date"),
            "key": abs(excess or 0.0),
            "outcome": outcome,
        }
    if t5 is None:
        return {"verdict": PENDING}
    excess = _excess(t5.get("open_hold"), populations.get("t5"))
    if excess is None:
        return {
            "verdict": INCOMPARABLE,
            "reason": (t5.get("open_hold") or {}).get("reason") or "no_population",
        }
    category = DEFER if action == score.DEFER else NO_LEVELS
    if category == DEFER:
        verdict = (
            ERROR
            if excess >= ERROR_EXCESS
            else CONTROL
            if excess <= -ERROR_EXCESS
            else None
        )
    else:
        verdict = (
            ERROR
            if excess <= -ERROR_EXCESS
            else CONTROL
            if excess >= ERROR_EXCESS
            else None
        )
    if verdict is None:
        return {"verdict": None}
    return {
        "verdict": verdict,
        "category": category,
        "result_date": t5["open_hold"].get("exit_date"),
        "key": abs(excess),
        "reprice_deferred": stock["action"] == score.REPRICE and action == score.DEFER,
        "outcome": {
            "horizon": "t5",
            "open_hold_return": t5["open_hold"].get("return"),
            "population_mean": populations.get("t5"),
            "excess": excess,
        },
    }


def _order(case: dict[str, Any]) -> tuple:
    return (-case["key"], case["session_date"], case.get("symbol") or "")


def pick(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most ``MAX_CASES`` errors, every market one first, the stocks by
    ``|excess|``; then as many right ones per category, sorted the same."""

    errors = [case for case in found if case["kind"] == ERROR]
    market = sorted(
        (case for case in errors if case["category"] == MARKET),
        key=lambda case: case["session_date"],
    )
    stocks = sorted((case for case in errors if case["category"] != MARKET), key=_order)
    chosen = (market + stocks)[:MAX_CASES]
    controls = []
    for category in CATEGORIES:
        wanted = sum(1 for case in chosen if case["category"] == category)
        right = sorted(
            (
                case
                for case in found
                if case["kind"] == CONTROL and case["category"] == category
            ),
            key=_order,
        )
        controls += right[:wanted]
    return chosen + controls


def ref_kind(ref: str) -> str:
    """A reason's citation as the table lists it (Q10)."""

    if ref.startswith("news:"):
        return "news"
    if ref.startswith("stock:"):
        parts = ref.split(":", 2)
        return f"stock:{parts[2]}" if len(parts) == 3 else "stock"
    if ref.startswith("us:") or ref in ("tx:night", "tx:day", "taiex"):
        return ref
    return "other"


def ref_table(calls: list[tuple[list[dict[str, Any]], bool | None]]) -> list[dict]:
    """Per citation kind: the reasons citing it and the share of those calls
    that were right (Q10: the sign of the T+5 excess, the market's ``hit``)."""

    cited: dict[str, list[bool | None]] = defaultdict(list)
    for reasons, right in calls:
        for reason in reasons or []:
            for kind in sorted({ref_kind(str(ref)) for ref in reason.get("refs") or []}):
                cited[kind].append(right)
    rows = []
    for kind, outcomes in cited.items():
        known = [value for value in outcomes if value is not None]
        rows.append(
            {
                "ref": kind,
                "reasons": len(outcomes),
                "judged": len(known),
                "right_rate": sum(known) / len(known) if known else None,
            }
        )
    return sorted(rows, key=lambda row: (-row["reasons"], row["ref"]))


def sign_right(action: str | None, excess: float | None) -> bool | None:
    if excess is None or action is None:
        return None
    return excess > 0 if action in ("keep", "reprice") else excess < 0


# --- building the month -----------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def build(db: Path, month: str) -> dict[str, Any]:
    from app import premarket_score as score
    from worker import premarket_reading

    version = premarket_reading.PROMPT_VERSION
    shadow = premarket_reading.SHADOW_PROMPT_VERSION
    first, last = month_bounds(month)
    engine, session = _session(db)
    try:
        statuses = day_statuses(session, version, last)
        other = other_versions(session, version, first, last)
        readings = done_readings(session, version, last)
        ids = sorted(readings)
        calls = stocks(session, ids)
        written = scores(session, ids)
        found: list[dict[str, Any]] = []
        counts: dict[str, int] = defaultdict(int)
        refs: list[tuple[list[dict[str, Any]], bool | None]] = []
        market_days, market_hits = 0, 0
        by_action: dict[str, list[float]] = defaultdict(list)
        for reading_id in ids:
            reading = readings[reading_id]
            in_month = first <= reading["session_date"] <= last
            market = judge_market(written.get((reading_id, score.MARKET, score.MARKET, "d0")))
            if in_month:
                if market["verdict"] in (ERROR, CONTROL):
                    market_days += 1
                    market_hits += market["verdict"] == CONTROL
                refs.append(
                    (
                        reading["market"].get("reasons"),
                        None
                        if market["verdict"] not in (ERROR, CONTROL)
                        else market["verdict"] == CONTROL,
                    )
                )
            _keep(found, counts, market, reading, None, month)
            populations = {
                horizon: (
                    (written.get((reading_id, score.OVERALL, score.OVERALL, horizon)) or {})
                    .get("population")
                    or {}
                ).get("mean")
                for horizon in score.STOCK_HORIZONS
            }
            for stock in sorted(
                (row for row in calls.values() if row["reading_id"] == reading_id),
                key=lambda row: row["position"],
            ):
                rows = {
                    horizon: written.get((reading_id, score.STOCK, stock["symbol"], horizon))
                    for horizon in score.STOCK_HORIZONS
                }
                if in_month and rows["t5"] is not None:
                    action = rows["t5"].get("effective_action")
                    excess = _excess(rows["t5"].get("open_hold"), populations["t5"])
                    refs.append((stock["reasons"], sign_right(action, excess)))
                    hold = (rows["t5"].get("open_hold") or {})
                    if hold.get("status") == "comparable":
                        by_action[action].append(hold["return"])
                case = judge_stock(stock, rows, populations)
                _keep(found, counts, case, reading, stock, month)
        chosen = pick(found)
        wanted = sorted({case["reading_id"] for case in chosen})
        inputs = reading_inputs(session, wanted)
    finally:
        session.close()
        engine.dispose()
    errors = sum(1 for case in found if case["kind"] == ERROR)
    sessions = {}
    for reading_id in wanted:
        reading = readings[reading_id]
        payload = inputs.get(reading_id) or {}
        cited = {
            str(ref)
            for reason in reading["market"].get("reasons") or []
            for ref in reason.get("refs") or []
        }
        sessions[reading["session_date"].isoformat()] = {
            "reading_id": reading_id,
            "list_date": reading["list_date"].isoformat(),
            "pool_phase": reading["pool_phase"],
            "llm_model": reading["llm_model"],
            "market_input": market_input(payload, cited),
            "market_output": reading["market"],
        }
    for case in chosen:
        payload = inputs.get(case["reading_id"]) or {}
        if case["symbol"]:
            case["input"] = candidate_input(payload, case["symbol"])
    month_days = {day: status for day, status in statuses.items() if first <= day <= last}
    gate = proposal_gate(market_days, errors, shadow)
    return {
        "version": VERSION,
        "design": DESIGN,
        "month": month,
        "prompt_version": version,
        "shadow_prompt_version": shadow,
        "score_version": score.SCORE_VERSION,
        "synthetic": False,
        "days": {
            "done": sum(1 for value in month_days.values() if value == "done"),
            "failed": sum(1 for value in month_days.values() if value == "failed"),
            "rejected": sum(1 for value in month_days.values() if value == "rejected"),
        },
        "other_versions": other,
        "found": {
            "errors": errors,
            "controls": sum(1 for case in found if case["kind"] == CONTROL),
            "by_category": {
                category: sum(
                    1
                    for case in found
                    if case["kind"] == ERROR and case["category"] == category
                )
                for category in CATEGORIES
            },
            "incomparable": counts[INCOMPARABLE],
            "pending": counts[PENDING],
        },
        "month_stats": {
            "market_d0_days": market_days,
            "market_d0_hit_rate": market_hits / market_days if market_days else None,
            "open_hold_t5_by_effective_action": {
                action: {"n": len(values), "mean": _mean(values)}
                for action, values in sorted(by_action.items())
            },
        },
        "proposal_gate": gate,
        "sessions": dict(sorted(sessions.items())),
        "cases": chosen,
        "refs": ref_table(refs),
    }


def _keep(found, counts, judged, reading, stock, month) -> None:
    verdict = judged["verdict"]
    if verdict in (PENDING, INCOMPARABLE):
        if first_month(reading, month):
            counts[verdict] += 1
        return
    if verdict is None:
        return
    if _month(judged["result_date"]) != month:
        return
    day = reading["session_date"].isoformat()
    subject = stock["symbol"] if stock else MARKET
    case = {
        "case_id": f"{day}:{subject}:{judged['category']}",
        "kind": verdict,
        "category": judged["category"],
        "session_date": day,
        "list_date": reading["list_date"].isoformat(),
        "result_date": judged["result_date"],
        "reading_id": reading["id"],
        "symbol": stock["symbol"] if stock else None,
        "key": judged["key"],
        "outcome": judged["outcome"],
    }
    if stock:
        case.update(
            on_today_list=stock["on_today_list"],
            pool_sources=stock["pool_sources"],
            action=stock["action"],
            reprice_rule=stock["reprice_rule"],
            reprice_deferred=judged.get("reprice_deferred", False),
            levels=stock["levels"],
            reasons=stock["reasons"],
        )
    else:
        case["reasons"] = reading["market"].get("reasons") or []
    found.append(case)


def first_month(reading: dict[str, Any], month: str) -> bool:
    """A pending or incomparable call is counted in its reading's month only."""

    return reading["session_date"].isoformat()[:7] == month


def proposal_gate(market_days: int, errors: int, shadow: str | None) -> dict[str, Any]:
    if shadow:
        status = SHADOW_EXISTS
        why = f"`SHADOW_PROMPT_VERSION` 是 `{shadow}`：同時最多一個 shadow"
    elif market_days < MIN_MARKET_DAYS or errors < MIN_ERRORS:
        status = INSUFFICIENT
        why = (
            f"大盤 d0 已對答案 {market_days} 天（至少 {MIN_MARKET_DAYS}），判錯 {errors} 筆"
            f"（至少 {MIN_ERRORS}）"
        )
    else:
        status = OK
        why = f"大盤 d0 已對答案 {market_days} 天，判錯 {errors} 筆"
    return {
        "status": status,
        "text": GATE_TEXT[status],
        "why": why,
        "market_d0_days": market_days,
        "errors": errors,
        "min_market_days": MIN_MARKET_DAYS,
        "min_errors": MIN_ERRORS,
    }


def other_versions(session, version: str, first: date, last: date) -> list[dict]:
    """Champion readings of the month under another prompt version: their
    days and version only (Q6), never their cases."""

    from sqlalchemy import func, select

    from app.models import PremarketAiReading as Reading
    from app.premarket_ai import CHAMPION

    rows = session.execute(
        select(
            Reading.prompt_version,
            func.count(func.distinct(Reading.session_date)),
        )
        .where(
            Reading.role == CHAMPION,
            Reading.prompt_version != version,
            Reading.session_date >= first,
            Reading.session_date <= last,
        )
        .group_by(Reading.prompt_version)
        .order_by(Reading.prompt_version)
    )
    return [{"prompt_version": name, "days": days} for name, days in rows]


# --- the report ---------------------------------------------------------------------


def markdown(result: dict[str, Any], command: str) -> str:
    found = result["found"]
    gate = result["proposal_gate"]
    days = result["days"]
    stats = result["month_stats"]
    lines = [
        f"# 早盤 AI 判錯清單 {result['month']}（premarket_errors 第 {result['version']} 版，"
        f"#{result['design']}）",
        "",
        f"- 判讀：champion、`{result['prompt_version']}`；{result['month']} 的判讀日 "
        f"done {days['done']}、failed {days['failed']}、rejected {days['rejected']} 天"
        "（failed／rejected 只列天數）",
        "- 其他提示版本的 champion（只列，不收）："
        + (
            "、".join(
                f"`{row['prompt_version']}` {row['days']} 天"
                for row in result["other_versions"]
            )
            or "沒有"
        ),
        f"- 案例歸結果出來的那個月（大盤是 D，個股是期間的最後一個交易日）：本月判錯 "
        f"{found['errors']} 筆（"
        + "、".join(
            f"{CATEGORY_TEXT[key]} {value}" for key, value in found["by_category"].items()
        )
        + f"），判對 {found['controls']} 筆；不能比 {found['incomparable']}、"
        f"尚未對答案 {found['pending']}（本月的判讀，結果在之後的月份）",
        f"- 大盤 d0 判對率：{lib.pct(stats['market_d0_hit_rate'], 1)}"
        f"（{stats['market_d0_days']} 天）",
        f"- 收進 `cases.json`：判錯最多 {MAX_CASES} 筆（大盤全收，個股依超額絕對值）、"
        "每類同樣筆數的判對當對照",
        f"- 提案：**{gate['text']}**（{gate['why']}）",
        f"- 重現：`{command}`",
        "",
        "## 案例",
        "",
    ]
    if not result["cases"]:
        lines += ["（沒有）", ""]
    else:
        lines += [
            "| case_id | 類 | 判錯／判對 | 動作 | 結果 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for case in result["cases"]:
            outcome = case["outcome"]
            if case["category"] == MARKET:
                what = (
                    f"{outcome['stance']}，實際 {outcome['realized']}"
                    f"（{lib.pct(outcome['return'])}）"
                )
                action = outcome["stance"]
            else:
                what = f"對母體超額 {lib.pct(outcome.get('excess'))}"
                if case["category"] == LEVELS:
                    what = f"先觸 `{outcome['first_trigger']}`，" + what
                action = case["action"] + ("（重算後暫緩）" if case["reprice_deferred"] else "")
            kind = "判錯" if case["kind"] == ERROR else "判對"
            lines.append(
                f"| `{case['case_id']}` | {CATEGORY_TEXT[case['category']]} | {kind} "
                f"| {action} | {what} |"
            )
        lines.append("")
    lines += [
        "## 理由引用的種類與判對率（只列出，不進清單）",
        "",
        "- 判對：大盤看 `hit`；每檔看 T+5 對母體超額的正負（keep／reprice 為正、defer 為負）。"
        f"這和判錯的 ±{ERROR_EXCESS * 100:.0f} 個百分點門檻不是同一個口徑",
        "",
    ]
    if not result["refs"]:
        lines += ["（沒有）", ""]
    else:
        lines += ["| 引用 | 理由數 | 有結果 | 判對率 |", "| --- | ---: | ---: | ---: |"]
        for row in result["refs"]:
            lines.append(
                f"| `{row['ref']}` | {row['reasons']} | {row['judged']} "
                f"| {lib.pct(row['right_rate'], 1)} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="premarket_errors.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a copy_db.py copy of stock.db")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
        parser.error("--month 要是 YYYY-MM")
    db = Path(args.db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    started = time.monotonic()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = build(db, args.month)
    command = "python tools/research/premarket_errors.py " + " ".join(argv)
    result["command"] = command
    (out / CASES).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / REPORT).write_text(markdown(result, command), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out.resolve()),
                "errors": result["found"]["errors"],
                "gate": result["proposal_gate"]["status"],
                "elapsed_seconds": round(time.monotonic() - started, 1),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
