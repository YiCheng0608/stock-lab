"""The AI list as the today page and 08:45 show it (Issue #1146, docs/spec/ai_list.md).

``worker.ai_list`` stores each run of a trading day as an ``ai_list_readings`` row
(``sequence`` 1, 2, ...) and the picks of a ``done`` one as ``ai_list_picks`` rows;
none is ever changed.  ``view`` is the one reading of the list both the page
(``GET /api/ai-list``) and the Telegram message (``worker.notify``) read:

- the day: SESSION_DATE when given, else the latest session with a row;
- its ``done`` row when it has one;
- else (the day failed, was rejected, or has no row) the latest ``done`` row before
  it, with ``failure`` saying why the day has none (#1142 1/4 Q1-5 A: the list
  before stays up, marked with its own date);
- ``status=missing`` when there is no ``done`` row at all.

A pick whose levels failed a check has no levels (``display_levels_json`` is null):
its rank, method and reasons stay, and its levels read 「價位未通過核對，未顯示」
(2/4 Q2-5 A).  A pick past ``valid_until`` reads 「價位已過有效期」 and has no
levels shown either.  A pick with a corporate action between the list date and the
session (``level_facts.corporate_action_on_session``) keeps its levels, with a note
that they are on the list date's basis.

The words below are the one wording of the page and the message
(docs/UI_COPY_SPEC.md §10 AI 名單).  Only the champion of the current prompt
version is shown.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .clock import utcnow
from .models import AiListPick, AiListReading, Instrument
from .premarket_ai import (
    CONFIDENCE_TEXT,
    DIRECTION_TEXT,
    STANCE_TEXT,
    _news_index,
    _reasons,
    input_gaps,
)
from .premarket_ai import REASON_TEXT as PREMARKET_REASON_TEXT

CHAMPION = "champion"
DONE = "done"
MISSING = "missing"
TAIPEI = timezone(timedelta(hours=8))
WEEKDAYS = "一二三四五六日"

TITLE = "AI 名單"
MARK = "AI 推論，未經驗證"
LEVELS_FAILED_TEXT = "價位未通過核對，未顯示"
EMPTY_TEXT = "今天 AI 沒有列股票："
MISSING_TEXT = "尚無 AI 名單（每個交易日 08:21 開盤前產出）"
SETUP_TEXT = {
    "breakout": "突破",
    "pullback_support": "回檔到支撐",
    "oversold_rebound": "跌深反彈",
    "theme_momentum": "題材發酵",
    "news_catalyst": "消息催化",
    "chip_accumulation": "籌碼集中",
}
BASIS_TEXT = {
    "news": "消息",
    "chips": "籌碼",
    "technical": "技術面",
    "sector": "族群",
    "market": "大盤",
}
MARKET_BASIS_TEXT = {
    "us": "美股",
    "tx_night": "台指期夜盤",
    "tx_day": "台指期日盤",
    "news": "隔夜消息",
    "taiex": "加權指數",
}
BASIS_JOIN = "＞"
ENTRY_TYPE_TEXT = {"breakout": "突破", "pullback": "拉回"}
# reason -> the short sentence after 「…的 AI 名單沒有產出：」: the call's failures as
# premarket_v1 has them, the list checks of ai_list_v1 (docs/spec/ai_list.md 核對),
# and a day without any row.
REASON_TEXT = {
    **{
        key: value
        for key, value in PREMARKET_REASON_TEXT.items()
        if key
        not in ("additions_present", "coverage", "reprice_without_levels", "schema")
    },
    "schema": "名單格式不符",
    "not_in_pool": "名單含候選池以外的股票",
    "duplicate_pick": "名單有重複的股票",
    "rank_not_contiguous": "名次不連號",
    "empty_without_reason": "空名單沒有寫原因",
    "unknown_news_ref": "名單引用了不在輸入裡的新聞",
    "directive_words": "名單含交易指示用語",
    MISSING: "沒有產出紀錄",
}
OTHER_REASON = "其他原因"
# The level fields a price may stand on (ai_list_reading.PRICE_FIELDS and
# FACT_PRICE_FIELDS), as the page names them.
FIELD_TEXT = {
    "open": "名單日開盤",
    "high": "名單日最高",
    "low": "名單日最低",
    "close": "名單日收盤",
    "ma5": "5 日均線",
    "ma10": "10 日均線",
    "ma20": "20 日均線",
    "ma60": "60 日均線",
    "high_20": "20 日高點",
    "low_20": "20 日低點",
    "high_60": "60 日高點",
    "low_60": "60 日低點",
    "volume_node_60.low": "60 日量密集區下緣",
    "volume_node_60.high": "60 日量密集區上緣",
    "limit_up": "漲停",
    "limit_down": "跌停",
}
LEVEL_TEXT = {
    "entry.low": "進場下緣",
    "entry.high": "進場上緣",
    "stop": "停損",
    "target_1": "目標一",
    "target_2": "目標二",
}


def taipei_today(now: datetime | None = None) -> date:
    """Today in Taipei from naive UTC NOW (default the clock)."""

    moment = (now or utcnow()).replace(tzinfo=timezone.utc)
    return moment.astimezone(TAIPEI).date()


def reason_text(reason: str | None) -> str:
    return REASON_TEXT.get(reason or "", OTHER_REASON)


def short_day(day: date) -> str:
    return f"{day:%m/%d}"


def day_text(day: date) -> str:
    """「2026/11/27（五）」."""

    return f"{day:%Y/%m/%d}（{WEEKDAYS[day.weekday()]}）"


def _champion_version() -> str:
    from worker.ai_list_reading import PROMPT_VERSION

    return PROMPT_VERSION


def _utc(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _rows(db: Session, version: str):
    return select(AiListReading).where(
        AiListReading.prompt_version == version, AiListReading.role == CHAMPION
    )


def latest_session(db: Session, version: str | None = None) -> date | None:
    version = version or _champion_version()
    return db.scalar(
        select(func.max(AiListReading.session_date)).where(
            AiListReading.prompt_version == version, AiListReading.role == CHAMPION
        )
    )


def day_reading(
    db: Session, session_date: date, version: str | None = None
) -> AiListReading | None:
    """The day's reading: its done row, else its latest row, else None."""

    version = version or _champion_version()
    rows = _rows(db, version).where(AiListReading.session_date == session_date)
    done = db.scalar(
        rows.where(AiListReading.status == DONE)
        .order_by(AiListReading.sequence)
        .limit(1)
    )
    if done is not None:
        return done
    return db.scalar(rows.order_by(desc(AiListReading.sequence)).limit(1))


def done_before(
    db: Session, session_date: date, version: str | None = None
) -> AiListReading | None:
    """The latest done reading of a session before SESSION_DATE."""

    version = version or _champion_version()
    return db.scalar(
        _rows(db, version)
        .where(
            AiListReading.session_date < session_date,
            AiListReading.status == DONE,
        )
        .order_by(desc(AiListReading.session_date), AiListReading.sequence)
        .limit(1)
    )


def failure_text(failed_day: date, today: date, reason: str | None) -> str:
    """「今天的 AI 名單沒有產出：呼叫逾時」 (another day: 「11/27 的 AI 名單…」)."""

    who = "今天" if failed_day == today else short_day(failed_day)
    return f"{who}的 AI 名單沒有產出：{reason_text(reason)}"


def method_text(setup: str, basis: list[str], confidence: str) -> str:
    """「突破 · 技術面＞籌碼 · 把握中」: the codes in words only (DESIGN_SYSTEM)."""

    return " · ".join(
        [
            SETUP_TEXT.get(setup, "其他"),
            BASIS_JOIN.join(BASIS_TEXT.get(code, code) for code in basis),
            CONFIDENCE_TEXT.get(confidence, ""),
        ]
    )


def _input_item(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    return next(
        (s for s in payload.get("candidates") or [] if s.get("symbol") == symbol), {}
    )


def _price(value: Any) -> str:
    return f"{float(value):,.2f}"


def _multiple(value: float) -> str:
    if value == 0:
        return ""
    sign = "＋" if value > 0 else "−"
    return f" {sign}{abs(value):g} 倍 ATR"


def level_refs(check: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    """Each level's base as words: 「進場下緣 233.00＝20 日高點（11/26）」."""

    out = []
    prices = check.get("prices") if isinstance(check, dict) else None
    for name in ("entry.low", "entry.high", "stop", "target_1", "target_2"):
        record = (prices or {}).get(name)
        if not isinstance(record, dict) or "price" not in record:
            continue
        field = str(record.get("ref") or "").split(":", 2)[-1]
        label = FIELD_TEXT.get(field)
        if label is None:
            continue
        fact: Any = facts
        for key in field.split("."):
            fact = fact.get(key) if isinstance(fact, dict) else None
        when = ""
        if isinstance(fact, dict) and fact.get("date"):
            when = f"（{short_day(date.fromisoformat(fact['date']))}）"
        multiple = float(record.get("atr_multiple") or 0)
        out.append(
            f"{LEVEL_TEXT[name]} {_price(record['price'])}＝{label}{when}{_multiple(multiple)}"
        )
    return out


def expired_text(sessions: int, until: date) -> str:
    return f"價位已過有效期（{sessions} 個交易日，至 {short_day(until)}）"


def corporate_action_text(list_date: date) -> str:
    return (
        f"名單日後有除權息，價位以 {short_day(list_date)} 收盤為基準，"
        "今天的漲跌停與參考價可能不同"
    )


def _pick(
    pick: AiListPick,
    instrument: Instrument | None,
    payload: dict[str, Any],
    news: dict[int, dict[str, Any]],
    list_date: date,
    today: date,
) -> dict[str, Any]:
    item = _input_item(payload, pick.symbol)
    facts = item.get("level_facts") or {}
    display = pick.display_levels_json
    until = pick.valid_until
    expired = until is not None and until < today
    corporate = bool(facts.get("corporate_action_on_session"))
    levels_status = "pass" if display else "fail"
    entry = (pick.levels_json or {}).get("entry") or {}
    return {
        "rank": pick.rank,
        "symbol": pick.symbol,
        "exchange": instrument.exchange if instrument else item.get("exchange"),
        "name": instrument.name if instrument else item.get("name"),
        "instrument_type": instrument.instrument_type if instrument else None,
        "on_rule_list": pick.on_rule_list,
        "setup": pick.setup,
        "setup_text": SETUP_TEXT.get(pick.setup, "其他"),
        "basis": list(pick.basis_json or []),
        "basis_text": BASIS_JOIN.join(
            BASIS_TEXT.get(code, code) for code in pick.basis_json or []
        ),
        "confidence": pick.confidence,
        "confidence_text": CONFIDENCE_TEXT.get(pick.confidence, ""),
        "method_text": method_text(
            pick.setup, list(pick.basis_json or []), pick.confidence
        ),
        "levels_status": levels_status,
        # Only levels that passed every check, and not past their validity.
        "levels": display if display and not expired else None,
        "levels_text": None if display else LEVELS_FAILED_TEXT,
        "risk_reward": pick.risk_reward if display else None,
        "valid_sessions": pick.valid_sessions,
        "valid_until": until.isoformat() if until else None,
        "expired": bool(display) and expired,
        "expired_text": expired_text(pick.valid_sessions, until)
        if display and expired and until
        else None,
        "corporate_action_on_session": corporate,
        "corporate_action_text": corporate_action_text(list_date)
        if corporate and display and not expired
        else None,
        "entry_condition": entry.get("condition") if display else None,
        "exit_conditions": _reasons(pick.exit_conditions_json, news),
        "reasons": _reasons(pick.reasons_json, news),
        "level_refs": level_refs(pick.levels_check_json or {}, facts)
        if display and not expired
        else [],
    }


def _empty(version: str, today: date, failure: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "status": MISSING,
        "title": TITLE,
        "mark": MARK,
        "today": today.isoformat(),
        "session_date": None,
        "list_date": None,
        "is_today": False,
        "prompt_version": version,
        "llm_model": None,
        "finished_at": None,
        "failure": failure,
        "missing_text": MISSING_TEXT,
        "market": None,
        "sectors": [],
        "picks": [],
        "empty_reason": None,
        "empty_text": None,
        "data_gaps": [],
        "input_gaps": [],
    }


def view(
    db: Session, session_date: date | None = None, today: date | None = None
) -> dict[str, Any]:
    """The AI list of SESSION_DATE (default the latest session with a row), or the
    latest done one before it with ``failure`` (Q1-5 A); ``status=missing`` without
    any done list."""

    version = _champion_version()
    today = today or taipei_today()
    day = session_date or latest_session(db, version)
    if day is None:
        return _empty(version, today, None)
    reading = day_reading(db, day, version)
    failure = None
    if reading is None or reading.status != DONE:
        reason = reading.reason if reading is not None else MISSING
        failure = {
            "session_date": day.isoformat(),
            "status": reading.status if reading is not None else MISSING,
            "reason": reason,
            "reason_text": reason_text(reason),
            "text": failure_text(day, today, reason),
        }
        reading = done_before(db, day, version)
        if reading is None:
            return _empty(version, today, failure)
    payload = reading.input_json or {}
    output = reading.output_json or {}
    news = _news_index(payload)
    market = output.get("market") or {}
    picks = list(
        db.scalars(
            select(AiListPick)
            .where(AiListPick.reading_id == reading.id)
            .order_by(AiListPick.rank)
        )
    )
    instruments = {
        row.id: row
        for row in db.scalars(
            select(Instrument).where(
                Instrument.id.in_([pick.instrument_id for pick in picks])
            )
        )
    }
    basis = list(
        reading.market_method_json or market.get("method", {}).get("basis") or []
    )
    return {
        "status": DONE,
        "title": TITLE,
        "mark": MARK,
        "today": today.isoformat(),
        "session_date": reading.session_date.isoformat(),
        "list_date": reading.list_date.isoformat(),
        "is_today": reading.session_date == today,
        "prompt_version": reading.prompt_version,
        "llm_model": reading.llm_model,
        "model_alias": reading.model_alias,
        "pool_phase": reading.pool_phase,
        "cutoff_at": _utc(reading.cutoff_at),
        "finished_at": _utc(reading.finished_at),
        "failure": failure,
        "missing_text": None,
        "market": {
            "stance": market.get("stance"),
            "stance_text": STANCE_TEXT.get(market.get("stance"), ""),
            "confidence": market.get("confidence"),
            "confidence_text": CONFIDENCE_TEXT.get(market.get("confidence"), ""),
            "basis": basis,
            "basis_text": BASIS_JOIN.join(
                MARKET_BASIS_TEXT.get(code, code) for code in basis
            ),
            "reasons": _reasons(market.get("reasons"), news),
        }
        if market
        else None,
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
        "picks": [
            _pick(
                pick,
                instruments.get(pick.instrument_id),
                payload,
                news,
                reading.list_date,
                today,
            )
            for pick in picks
        ],
        "empty_reason": output.get("empty_reason") if not picks else None,
        "empty_text": f"{EMPTY_TEXT}{output.get('empty_reason') or OTHER_REASON}"
        if not picks
        else None,
        "data_gaps": [
            (gap.get("text") or "").strip()
            for gap in output.get("data_gaps") or []
            if isinstance(gap, dict) and (gap.get("text") or "").strip()
        ],
        "input_gaps": input_gaps(payload),
    }
