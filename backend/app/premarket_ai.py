"""Reading the stored pre-market AI readings (Issue #1041, docs/spec/premarket_ai.md).

``premarket_ai_readings`` keeps every run of a trading day, prompt version and
role as its own row (``sequence`` 1, 2, ...); a row is never changed.  The
day's reading of a version and role is its ``done`` row when there is one,
else the latest row.  ``view`` is the champion's reading as the 08:45 message
(``worker.notify``) and ``GET /api/premarket-ai`` give it (#1042).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .models import PremarketAiReading, PremarketAiStock

CHAMPION = "champion"
SHADOW = "shadow"
ROLES = (CHAMPION, SHADOW)
DONE = "done"
FAILED = "failed"
REJECTED = "rejected"
STATUSES = (DONE, FAILED, REJECTED)
# pool_phase: candidate_pool_v1's morning round (evening plus morning items),
# its evening round alone (no morning round yet at 08:21), or the stand-in pool.
POOL_PHASES = ("morning", "evening", "interim")


def readings(
    db: Session, session_date: date, prompt_version: str, role: str
) -> list[PremarketAiReading]:
    """The rows of one day, version and role, oldest first."""

    return list(
        db.scalars(
            select(PremarketAiReading)
            .where(
                PremarketAiReading.session_date == session_date,
                PremarketAiReading.prompt_version == prompt_version,
                PremarketAiReading.role == role,
            )
            .order_by(PremarketAiReading.sequence)
        )
    )


def done_reading(
    db: Session, session_date: date, prompt_version: str, role: str
) -> PremarketAiReading | None:
    return db.scalar(
        select(PremarketAiReading)
        .where(
            PremarketAiReading.session_date == session_date,
            PremarketAiReading.prompt_version == prompt_version,
            PremarketAiReading.role == role,
            PremarketAiReading.status == DONE,
        )
        .order_by(PremarketAiReading.sequence)
        .limit(1)
    )


def day_reading(
    db: Session, session_date: date, prompt_version: str, role: str = CHAMPION
) -> PremarketAiReading | None:
    """The day's reading: its done row, else its latest row, else None."""

    done = done_reading(db, session_date, prompt_version, role)
    if done is not None:
        return done
    return db.scalar(
        select(PremarketAiReading)
        .where(
            PremarketAiReading.session_date == session_date,
            PremarketAiReading.prompt_version == prompt_version,
            PremarketAiReading.role == role,
        )
        .order_by(desc(PremarketAiReading.sequence))
        .limit(1)
    )


def next_sequence(
    db: Session, session_date: date, prompt_version: str, role: str
) -> int:
    latest = db.scalar(
        select(func.max(PremarketAiReading.sequence)).where(
            PremarketAiReading.session_date == session_date,
            PremarketAiReading.prompt_version == prompt_version,
            PremarketAiReading.role == role,
        )
    )
    return (latest or 0) + 1


def stocks(db: Session, reading_id: int) -> list[PremarketAiStock]:
    return list(
        db.scalars(
            select(PremarketAiStock)
            .where(PremarketAiStock.reading_id == reading_id)
            .order_by(PremarketAiStock.position)
        )
    )


# --- the view of a day (#1042): 08:45 Telegram and the today page ------------
#
# Only the champion of the current prompt version is shown; a shadow never is.
# The words below are the one wording of the message and the page
# (docs/UI_COPY_SPEC.md §10 早盤 AI 判讀).

MISSING = "missing"
# 3a (#1058): a reason or data gap of a stock without usable rule levels that wrote
# a price (premarket_reading.prices_without_levels in checks_json) shows as this.
PRICE_HIDDEN_TEXT = "理由含價位，未顯示"
ACTION_TEXT = {"keep": "維持", "reprice": "依開盤價重算", "defer": "暫緩"}
STANCE_TEXT = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}
CONFIDENCE_TEXT = {"high": "把握高", "medium": "把握中", "low": "把握低"}
DIRECTION_TEXT = {"positive": "可能正向", "negative": "可能負向", "mixed": "正負互見"}
# reason -> the short sentence after 「AI 判讀失敗：」 (failed and rejected rows).
REASON_TEXT = {
    # failed: the call
    "timeout": "呼叫逾時",
    "invalid_json": "回應格式無法解析",
    "cli_error": "呼叫出錯",
    "rate_limited": "訂閱用量已達上限",
    "not_logged_in": "Claude Code 未登入",
    "cli_not_started": "Claude Code 無法啟動",
    "cli_not_found": "找不到 Claude Code",
    "cli_config_invalid": "Claude Code 設定有誤",
    "api_key_env_refused": "環境設了 API 金鑰，拒絕呼叫",
    "prompt_hash_mismatch": "提示詞與版本不符，未呼叫",
    "no_time": "判讀時間不足，未呼叫",
    # rejected: the checks
    "additions_present": "判讀加了候選池以外的股票",
    "schema": "判讀格式不符",
    "coverage": "判讀漏了或多了股票",
    "reprice_without_levels": "沒有規則價位的股票被判依開盤價重算",
    "unknown_news_ref": "判讀引用了不在輸入裡的新聞",
    "directive_words": "判讀含交易指示用語",
}
OTHER_REASON = "其他原因"
US_SHORT = {"SPX": "S&P 500", "IXIC": "NASDAQ", "DJI": "道瓊", "SOX": "費半"}
REF_TEXT = {"tx:night": "台指期夜盤", "tx:day": "台指期日盤", "taiex": "加權指數"}
STOCK_FIELD_TEXT = {
    "price": "價量",
    "chips": "籌碼",
    "groups": "族群",
    "news": "新聞",
    "strategy_levels": "規則價位",
    "pool_sources": "入池來源",
}
_NEWS_REF = re.compile(r"^news:(\d+)$")


def reason_text(reason: str | None) -> str:
    return REASON_TEXT.get(reason or "", OTHER_REASON)


def _utc(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _champion_version() -> str:
    from worker.premarket_reading import PROMPT_VERSION

    return PROMPT_VERSION


def _session_of(db: Session, version: str, list_date: date | None) -> date | None:
    query = select(func.max(PremarketAiReading.session_date)).where(
        PremarketAiReading.prompt_version == version,
        PremarketAiReading.role == CHAMPION,
    )
    if list_date is not None:
        query = query.where(PremarketAiReading.list_date == list_date)
    return db.scalar(query)


def _news_index(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Every news item of the input by id: the ones a reason may cite."""

    out: dict[int, dict[str, Any]] = {}
    items = list(payload.get("market_news") or [])
    for stock in payload.get("candidates") or []:
        items += stock.get("news") or []
    for item in items:
        if isinstance(item.get("id"), int) and item["id"] not in out:
            out[item["id"]] = {
                "id": item["id"],
                "title": item.get("title"),
                "source": item.get("source"),
                "time": item.get("time"),
            }
    return out


def _ref(ref: str, news: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """One cited input: news links to the news page; the others are a label; an
    unknown one is ``other`` without a label (the page leaves it out)."""

    match = _NEWS_REF.match(ref)
    if match:
        item = news.get(int(match.group(1)))
        return {
            "ref": ref,
            "kind": "news",
            "news_id": int(match.group(1)),
            "label": (item or {}).get("title") or f"新聞 {match.group(1)}",
        }
    if ref in REF_TEXT:
        return {"ref": ref, "kind": ref.split(":")[0], "label": REF_TEXT[ref]}
    if ref.startswith("us:") and ref[3:] in US_SHORT:
        return {"ref": ref, "kind": "us", "label": f"美股 {US_SHORT[ref[3:]]}"}
    if ref.startswith("stock:"):
        _, _, rest = ref.partition(":")
        symbol, _, field = rest.partition(":")
        label = STOCK_FIELD_TEXT.get(field.split(".")[0])
        if symbol:
            return {
                "ref": ref,
                "kind": "stock",
                "label": f"{symbol} {label}" if label else symbol,
            }
    return {"ref": ref, "kind": "other", "label": None}


def _reasons(
    value: Any, news: dict[int, dict[str, Any]], hidden: frozenset[int] = frozenset()
) -> list[dict[str, Any]]:
    out = []
    for index, reason in enumerate(value or []):
        if index in hidden:
            out.append({"text": PRICE_HIDDEN_TEXT, "refs": []})
            continue
        refs = [_ref(ref, news) for ref in reason.get("refs") or []]
        out.append({"text": reason.get("text") or "", "refs": refs})
    return out


_HIDDEN_WHERE = re.compile(r"^(reasons|data_gaps)\[(\d+)\]$")


def hidden_prices(checks: Any) -> tuple[dict[str, frozenset[int]], frozenset[int]]:
    """From ``checks_json.prices_without_levels``: each stock's reason indexes and
    the data gap indexes to show as PRICE_HIDDEN_TEXT (#1058).  A row stored before
    the check has none."""

    reasons: dict[str, set[int]] = {}
    gaps: set[int] = set()
    items = checks.get("prices_without_levels") if isinstance(checks, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        match = _HIDDEN_WHERE.match(str(item.get("where") or ""))
        if match is None:
            continue
        if match.group(1) == "data_gaps":
            gaps.add(int(match.group(2)))
        else:
            reasons.setdefault(str(item.get("symbol")), set()).add(int(match.group(2)))
    return {key: frozenset(value) for key, value in reasons.items()}, frozenset(gaps)


def _pct(value: Any) -> str:
    return f"{value * 100:.1f}%"


def reprice_text(rule: dict[str, Any] | None) -> str | None:
    """The reprice rule as one clause: what makes it 暫緩 after the open."""

    if not rule:
        return None
    parts = []
    if isinstance(rule.get("max_gap_pct"), (int, float)):
        parts.append(f"開盤漲幅逾 {_pct(rule['max_gap_pct'])}")
    if isinstance(rule.get("max_gap_down_pct"), (int, float)):
        parts.append(f"跌幅逾 {_pct(rule['max_gap_down_pct'])}")
    if isinstance(rule.get("min_risk_reward"), (int, float)):
        parts.append(f"重算後 RR 低於 {rule['min_risk_reward']:g} 倍")
    if not parts:
        return None
    return (
        "、".join(parts[:-1]) + ("或" if len(parts) > 1 else "") + parts[-1] + "即暫緩"
    )


def input_gaps(payload: dict[str, Any]) -> list[str]:
    """What the input marked missing or stale, as facts (not the AI's data_gaps)."""

    gaps = []
    if (payload.get("taiex") or {}).get("status") == "missing":
        gaps.append("加權指數名單日無資料")
    us = payload.get("us_indices") or {}
    for code, label in US_SHORT.items():
        value = us.get(code) or {}
        if value.get("status") == "missing":
            gaps.append(f"美股 {label} 未取得")
        elif value.get("freshness") == "stale":
            gaps.append(f"美股 {label} 非最新")
    futures = payload.get("tx_futures") or {}
    if (futures.get("day") or {}).get("status") == "missing":
        gaps.append("台指期日盤無資料")
    if (futures.get("night") or {}).get("status") == "missing":
        gaps.append("台指期夜盤無資料")
    late = (payload.get("overnight_news_stats") or {}).get("not_judged_by_cutoff")
    if late:
        gaps.append(f"隔夜新聞 {late} 則截止前尚未判讀")
    for stock in payload.get("candidates") or []:
        who = f"{stock.get('symbol', '')} {stock.get('name', '')}".strip()
        if (stock.get("price") or {}).get("status") == "missing":
            gaps.append(f"{who} 名單日無日線")
        if (stock.get("chips") or {}).get("status") == "missing":
            gaps.append(f"{who} 無籌碼資料")
        if (stock.get("strategy_levels") or {}).get("status") == "no_levels":
            gaps.append(f"{who} 規則價位不完整")
    return gaps


def _stock(
    row: PremarketAiStock,
    payload: dict[str, Any],
    news,
    hidden: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    inputs = payload.get("candidates") or []
    source = inputs[row.position - 1] if 0 < row.position <= len(inputs) else {}
    if source.get("symbol") != row.symbol:
        source = next((s for s in inputs if s.get("symbol") == row.symbol), {})
    out: dict[str, Any] = {
        "symbol": row.symbol,
        "exchange": source.get("exchange"),
        "name": source.get("name"),
        "on_today_list": row.on_today_list,
        "action": row.action,
        "action_text": ACTION_TEXT.get(row.action, row.action),
        "reprice_rule": row.reprice_rule_json,
        "reprice_text": reprice_text(row.reprice_rule_json),
        "reasons": _reasons(row.reasons_json, news, hidden),
    }
    if row.on_today_list:
        # 3a: only a today-list stock has prices, the rule's levels as the input had
        # them; any other stock has no levels key at all.
        levels = row.levels_json or None
        out["rank"] = (levels or {}).get("rank")
        out["levels"] = levels
    return out


def view(
    db: Session, session_date: date | None = None, list_date: date | None = None
) -> dict[str, Any]:
    """The champion reading of SESSION_DATE (or of the latest session of LIST_DATE,
    or the latest one) for the message and the page; ``status=missing`` without one
    (not run yet, still running, or no run that day)."""

    version = _champion_version()
    if session_date is None:
        session_date = _session_of(db, version, list_date)
    reading = day_reading(db, session_date, version, CHAMPION) if session_date else None
    if reading is None:
        return {
            "status": MISSING,
            "session_date": session_date.isoformat() if session_date else None,
            "list_date": list_date.isoformat() if list_date else None,
            "prompt_version": version,
            "llm_model": None,
            "reason": None,
            "reason_text": None,
            "market": None,
            "sectors": [],
            "stocks": [],
            "data_gaps": [],
            "input_gaps": [],
        }
    payload = reading.input_json or {}
    done = reading.status == DONE
    output = (reading.output_json or {}) if done else {}
    news = _news_index(payload)
    market = output.get("market") if done else None
    hidden, hidden_gaps = (
        hidden_prices(reading.checks_json) if done else ({}, frozenset())
    )
    stocks_out = []
    if done:
        rows = [
            _stock(row, payload, news, hidden.get(row.symbol, frozenset()))
            for row in stocks(db, reading.id)
        ]
        listed = sorted(
            (row for row in rows if row["on_today_list"]),
            key=lambda row: (row.get("rank") is None, row.get("rank") or 0),
        )
        stocks_out = listed + [row for row in rows if not row["on_today_list"]]
    return {
        "status": reading.status,
        "session_date": reading.session_date.isoformat(),
        "list_date": reading.list_date.isoformat(),
        "prompt_version": reading.prompt_version,
        "llm_model": reading.llm_model,
        "model_alias": reading.model_alias,
        "pool_phase": reading.pool_phase,
        "cutoff_at": _utc(reading.cutoff_at),
        "finished_at": _utc(reading.finished_at),
        "reason": None if done else reading.reason,
        "reason_text": None if done else reason_text(reading.reason),
        "market": None
        if market is None
        else {
            "stance": market.get("stance"),
            "stance_text": STANCE_TEXT.get(market.get("stance"), ""),
            "confidence": market.get("confidence"),
            "confidence_text": CONFIDENCE_TEXT.get(market.get("confidence"), ""),
            "reasons": _reasons(market.get("reasons"), news),
        },
        "sectors": [
            {
                "group_id": sector.get("group_id"),
                "name": sector.get("name"),
                "direction": sector.get("direction"),
                "direction_text": DIRECTION_TEXT.get(sector.get("direction"), ""),
                "reasons": _reasons(sector.get("reasons"), news),
            }
            for sector in output.get("sectors") or []
        ],
        "stocks": stocks_out,
        "data_gaps": [
            PRICE_HIDDEN_TEXT if index in hidden_gaps else gap
            for index, gap in enumerate(output.get("data_gaps") or [])
            if gap
        ],
        "input_gaps": input_gaps(payload),
    }
