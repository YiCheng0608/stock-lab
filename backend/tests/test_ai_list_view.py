"""The AI list as the today page and 08:45 show it (#1146).

``app.ai_list.view``, ``GET /api/ai-list`` and the Telegram text and card
(``worker.notify``, ``worker.notify_card``): a done list, a day without one (the
list before it with the reason, #1142 1/4 Q1-5 A), a pick whose levels failed a
check, one past its validity, one with a corporate action after the list date,
and the cut of a text past 4096 characters (3/4). The session is MONDAY
(2026-09-07), its list date T (2026-09-04).
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api as api_module
import app.main as main_module
from app import ai_list
from app.db import Base, enable_sqlite_foreign_keys
from app.main import app
from app.models import AiListPick, AiListReading, Instrument
from worker import notify, notify_card, pipeline
from worker.ai_list_reading import PROMPT_VERSION
from worker.premarket_reading import directive_words

MONDAY = date(2026, 9, 7)
FRIDAY = date(2026, 9, 4)
TUESDAY = date(2026, 9, 8)
THURSDAY = date(2026, 9, 3)
MODEL = "claude-sonnet-5-5"
MARKET_REASON = "根據台指期夜盤與結算價持平，推論開盤缺乏方向訊號"
PICK_REASON = "根據收盤 233 創 20 日新高、量比 1.39，推論突破格局成形"
DISPLAY = {
    "entry": {"type": "breakout", "low": 233.0, "high": 236.5},
    "stop": 226.0,
    "target_1": 243.5,
    "target_2": 254.5,
    "risk_reward": 1.5,
    "valid_sessions": 3,
    "valid_until": "2026-09-09",
}
PULLBACK = {
    "entry": {"type": "pullback", "low": 44.4, "high": 46.05},
    "stop": 42.0,
    "target_1": 48.95,
    "target_2": None,
    "risk_reward": 1.2,
    "valid_sessions": 4,
    "valid_until": "2026-09-10",
}
LEVELS_ANSWER = {
    "entry": {
        "type": "breakout",
        "low": {"price": 233.0, "refs": ["stock:1477:high_20"], "atr_multiple": 0},
        "high": {"price": 236.5, "refs": ["stock:1477:high_20"], "atr_multiple": 0.5},
        "condition": "若站上 20 日高點",
    },
    "stop": {"price": 226.0, "refs": ["stock:1477:ma10"], "atr_multiple": 0},
    "target_1": {"price": 243.5, "refs": ["stock:1477:high_60"], "atr_multiple": 0},
    "target_2": None,
    "exit_conditions": [{"text": "若外資轉為連續賣超", "refs": []}],
    "valid_sessions": 3,
}
CHECK = {
    "status": "pass",
    "prices": {
        "entry.low": {"ref": "stock:1477:high_20", "atr_multiple": 0, "price": 233.0},
        "entry.high": {
            "ref": "stock:1477:high_20",
            "atr_multiple": 0.5,
            "price": 236.5,
        },
        "stop": {"ref": "stock:1477:ma10", "atr_multiple": 0, "price": 226.0},
    },
}


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.info["strategies"] = pipeline._ensure_strategies(session)
        session.commit()
        yield session
    engine.dispose()


def _instrument(db, symbol, name):
    row = db.query(Instrument).filter_by(symbol=symbol).one_or_none()
    if row is None:
        row = Instrument(
            exchange="TWSE",
            symbol=symbol,
            name=name,
            instrument_type="stock",
            status="active",
        )
        db.add(row)
        db.flush()
    return row


def _payload(corporate=False):
    facts = {
        "close": 233.0,
        "high_20": {"price": 233.0, "date": "2026-09-03"},
        "ma10": 226.1,
        "corporate_action_in_window": False,
        "corporate_action_on_session": corporate,
    }
    return {
        "candidates": [
            {
                "symbol": "1477",
                "exchange": "TWSE",
                "name": "聚陽",
                "level_facts": facts,
            },
            {"symbol": "2618", "exchange": "TWSE", "name": "長榮航", "level_facts": {}},
            {"symbol": "9999", "exchange": "TWSE", "name": "範例", "level_facts": {}},
        ],
        "market_news": [],
    }


def _output(picks=True, empty_reason=None):
    return {
        "market": {
            "stance": "neutral",
            "confidence": "low",
            "method": {"basis": ["tx_night", "taiex", "news", "us"]},
            "reasons": [
                {"text": MARKET_REASON, "refs": ["tx:night"]},
                {"text": "根據美股休市，推論隔夜消息有限", "refs": []},
            ],
        },
        "sectors": [
            {
                "group_id": "industry:28",
                "name": "PCB",
                "direction": "positive",
                "reasons": [{"text": "根據……，推論……", "refs": []}],
            }
        ],
        "picks": [] if not picks else [{"symbol": "1477"}],
        "empty_reason": empty_reason,
        "data_gaps": [{"text": "台指期日盤沒有資料", "refs": []}],
    }


def _reading(
    db,
    day=MONDAY,
    status="done",
    *,
    reason=None,
    sequence=1,
    list_date=FRIDAY,
    picks=None,
    corporate=False,
    empty_reason=None,
    version=PROMPT_VERSION,
):
    at = datetime(day.year, day.month, day.day, 0, 22)
    reading = AiListReading(
        session_date=day,
        list_date=list_date,
        role="champion",
        sequence=sequence,
        trigger="scheduler",
        prompt_version=version,
        prompt_sha256="0" * 64,
        schema_sha256="0" * 64,
        model_alias="sonnet",
        llm_model=MODEL if status == "done" else None,
        pool_phase="morning",
        cutoff_at=at,
        input_hash="0" * 64,
        input_json=_payload(corporate),
        status=status,
        reason=reason,
        output_json=_output(picks != [], empty_reason) if status == "done" else None,
        market_method_json=["tx_night", "taiex", "news", "us"]
        if status == "done"
        else None,
        checks_json={},
        attempts=1,
        attempts_json=[],
        duration_ms=40000,
        usage_json={},
        started_at=at,
        finished_at=at,
    )
    db.add(reading)
    db.flush()
    if status == "done":
        for pick in _picks() if picks is None else picks:
            db.add(_pick_row(db, reading, **pick))
        db.flush()
    db.commit()
    return reading


def _picks():
    return [
        {"rank": 1, "symbol": "1477", "name": "聚陽", "display": DISPLAY},
        {
            "rank": 2,
            "symbol": "2618",
            "name": "長榮航",
            "display": PULLBACK,
            "setup": "pullback_support",
            "confidence": "medium",
        },
        {"rank": 3, "symbol": "9999", "name": "範例", "display": None},
    ]


def _pick_row(
    db,
    reading,
    *,
    rank,
    symbol,
    name,
    display,
    setup="breakout",
    confidence="medium",
    reason=PICK_REASON,
):
    instrument = _instrument(db, symbol, name)
    until = date.fromisoformat(display["valid_until"]) if display else date(2026, 9, 9)
    return AiListPick(
        reading_id=reading.id,
        session_date=reading.session_date,
        prompt_version=reading.prompt_version,
        role="champion",
        rank=rank,
        instrument_id=instrument.id,
        symbol=symbol,
        pool_item_id=None,
        pool_sources_json=["rule_signal"],
        on_rule_list=rank == 1,
        setup=setup,
        basis_json=["technical", "chips"],
        basis_primary="technical",
        confidence=confidence,
        levels_json=LEVELS_ANSWER,
        levels_check_json=CHECK if display else {"status": "fail"},
        display_levels_json=display,
        risk_reward=display["risk_reward"] if display else None,
        valid_sessions=display["valid_sessions"] if display else 3,
        valid_until=until,
        exit_conditions_json=LEVELS_ANSWER["exit_conditions"],
        reasons_json=[{"text": reason, "refs": ["stock:1477:price"]}],
        rule_levels_json=None,
    )


US = [
    {
        "symbol": "SPX",
        "name": "SPX",
        "status": "available",
        "trading_date": "2026-09-04",
        "freshness": "latest",
        "close": 7561.67,
        "change_pct": -0.004,
        "source": {"label": "FinMind USStockPrice ^GSPC"},
    }
]
RULES = {"status": "success", "candidate_count": 3, "items": []}


def _well_formed(text):
    """Telegram's HTML parser takes it: the only tags are <b> and </b>, paired."""

    assert text.count("<b>") == text.count("</b>")
    assert "<" not in re.sub(r"</?b>", "", text)


# --- the view -------------------------------------------------------------------------


def test_a_done_list_has_its_date_mark_method_levels_and_reasons(db):
    _reading(db)
    view = ai_list.view(db, today=MONDAY)
    assert view["status"] == "done" and view["failure"] is None
    assert (view["session_date"], view["list_date"]) == ("2026-09-07", "2026-09-04")
    assert view["is_today"] is True and view["mark"] == "AI 推論，未經驗證"
    assert view["llm_model"] == MODEL and view["prompt_version"] == PROMPT_VERSION
    assert view["market"]["basis_text"] == "台指期夜盤＞加權指數＞隔夜消息＞美股"
    assert view["market"]["stance_text"] == "中性"
    first, second, third = view["picks"]
    assert [p["rank"] for p in view["picks"]] == [1, 2, 3]
    assert (first["symbol"], first["name"], first["exchange"]) == (
        "1477",
        "聚陽",
        "TWSE",
    )
    assert first["method_text"] == "突破 · 技術面＞籌碼 · 把握中"
    assert first["levels"] == DISPLAY and first["levels_text"] is None
    assert first["risk_reward"] == 1.5 and first["expired"] is False
    assert first["entry_condition"] == "若站上 20 日高點"
    assert first["exit_conditions"][0]["text"] == "若外資轉為連續賣超"
    assert first["reasons"][0]["text"] == PICK_REASON
    assert first["level_refs"] == [
        "進場下緣 233.00＝20 日高點（09/03）",
        "進場上緣 236.50＝20 日高點（09/03） ＋0.5 倍 ATR",
        "停損 226.00＝10 日均線",
    ]
    assert first["corporate_action_on_session"] is False
    assert first["corporate_action_text"] is None
    assert second["setup_text"] == "回檔到支撐"
    assert view["data_gaps"] == ["台指期日盤沒有資料"]


def test_a_pick_whose_levels_failed_has_no_levels_and_says_so(db):
    """AC-2 (2/4 Q2-5 A): the rank, method and reasons stay; no level at all."""

    _reading(db)
    third = ai_list.view(db, today=MONDAY)["picks"][2]
    assert third["levels_status"] == "fail"
    assert third["levels"] is None and third["risk_reward"] is None
    assert third["levels_text"] == "價位未通過核對，未顯示"
    assert third["entry_condition"] is None and third["level_refs"] == []
    assert third["method_text"] == "突破 · 技術面＞籌碼 · 把握中"
    assert third["reasons"][0]["text"] == PICK_REASON


def test_a_list_of_another_day_is_not_today(db):
    _reading(db)
    view = ai_list.view(db, today=TUESDAY)
    assert view["session_date"] == "2026-09-07" and view["is_today"] is False
    assert view["failure"] is None  # the latest session is Monday's: no failed day


def test_a_pick_past_its_validity_says_so_without_levels(db):
    _reading(db)
    # Monday's first pick holds to 09/09: on 09/10 it is past.
    first, second, _ = ai_list.view(db, today=date(2026, 9, 10))["picks"]
    assert first["expired"] is True and first["levels"] is None
    assert first["expired_text"] == "價位已過有效期（3 個交易日，至 09/09）"
    assert second["expired"] is False and second["levels"] == PULLBACK


def test_a_corporate_action_after_the_list_date_keeps_the_levels_with_a_note(db):
    """Decision 7238366814 (A): the levels stay, with the warning."""

    _reading(db, corporate=True)
    first = ai_list.view(db, today=MONDAY)["picks"][0]
    assert first["corporate_action_on_session"] is True
    assert first["levels"] == DISPLAY
    assert first["corporate_action_text"] == (
        "名單日後有除權息，價位以 09/04 收盤為基準，今天的漲跌停與參考價可能不同"
    )


@pytest.mark.parametrize(
    ("status", "reason", "text"),
    [
        ("failed", "timeout", "今天的 AI 名單沒有產出：呼叫逾時"),
        ("rejected", "not_in_pool", "今天的 AI 名單沒有產出：名單含候選池以外的股票"),
        ("rejected", "directive_words", "今天的 AI 名單沒有產出：名單含交易指示用語"),
    ],
)
def test_a_failed_day_shows_the_list_before_with_its_reason(db, status, reason, text):
    """AC-2 (1/4 Q1-5 A)."""

    _reading(db, day=FRIDAY, list_date=THURSDAY)
    _reading(db, status=status, reason=reason)
    view = ai_list.view(db, today=MONDAY)
    assert view["status"] == "done"
    assert view["session_date"] == "2026-09-04" and view["is_today"] is False
    assert view["failure"] == {
        "session_date": "2026-09-07",
        "status": status,
        "reason": reason,
        "reason_text": text.split("：", 1)[1],
        "text": text,
    }
    assert [p["rank"] for p in view["picks"]] == [1, 2, 3]


def test_a_failed_then_done_day_shows_its_done_list(db):
    _reading(db, day=FRIDAY, list_date=THURSDAY)
    _reading(db, status="failed", reason="timeout")
    _reading(db, sequence=2)
    view = ai_list.view(db, today=MONDAY)
    assert view["session_date"] == "2026-09-07" and view["failure"] is None


def test_a_day_without_any_row_asked_for_shows_the_list_before(db):
    _reading(db)
    view = ai_list.view(db, session_date=TUESDAY, today=TUESDAY)
    assert view["session_date"] == "2026-09-07"
    assert view["failure"]["text"] == "今天的 AI 名單沒有產出：沒有產出紀錄"


def test_no_done_list_at_all_is_missing(db):
    assert ai_list.view(db, today=MONDAY)["status"] == "missing"
    _reading(db, status="failed", reason="rate_limited")
    view = ai_list.view(db, today=MONDAY)
    assert view["status"] == "missing" and view["picks"] == []
    assert view["failure"]["text"] == "今天的 AI 名單沒有產出：訂閱用量已達上限"


def test_an_empty_list_has_its_reason(db):
    _reading(db, picks=[], empty_reason="大盤偏空、信心不低")
    view = ai_list.view(db, today=MONDAY)
    assert view["picks"] == []
    assert view["empty_text"] == "今天 AI 沒有列股票：大盤偏空、信心不低"


def test_only_the_current_version_is_shown(db):
    _reading(db, version="ai_list_v0")
    assert ai_list.view(db, today=MONDAY)["status"] == "missing"


def test_the_texts_have_no_order_wording():
    texts = [
        *ai_list.REASON_TEXT.values(),
        *ai_list.SETUP_TEXT.values(),
        ai_list.LEVELS_FAILED_TEXT,
        ai_list.EMPTY_TEXT,
        ai_list.MISSING_TEXT,
        ai_list.MARK,
        ai_list.expired_text(3, MONDAY),
        ai_list.corporate_action_text(FRIDAY),
    ]
    assert [text for text in texts if directive_words(text)] == []


# --- the API -------------------------------------------------------------------------


@pytest.fixture
def client(db, monkeypatch):
    def override_get_db():
        yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(api_module.get_db, None)


def test_the_api_gives_the_latest_or_a_dates_list(client, db):
    assert client.get("/api/ai-list").json()["status"] == "missing"
    _reading(db, day=FRIDAY, list_date=THURSDAY)
    _reading(db, status="failed", reason="timeout")
    latest = client.get("/api/ai-list").json()
    assert latest["session_date"] == "2026-09-04"
    assert latest["failure"]["session_date"] == "2026-09-07"
    friday = client.get("/api/ai-list", params={"date": "2026-09-04"}).json()
    assert friday["session_date"] == "2026-09-04" and friday["failure"] is None
    assert friday["picks"][2]["levels_text"] == "價位未通過核對，未顯示"


# --- the Telegram text and card --------------------------------------------------------


def _card(db, today=MONDAY, rules=RULES):
    return notify.content(
        today, ai_list.view(db, session_date=today, today=today), US, rules
    )


def test_the_text_is_the_ai_list_with_its_date_and_mark(db):
    """AC-1."""

    _reading(db, corporate=True)
    message = notify.text(_card(db))
    _well_formed(message)
    lines = message.splitlines()
    assert lines[:10] == [
        "📋 <b>AI 名單 2026/09/07（一）開盤前</b> · AI 推論，未經驗證",
        f"模型 {MODEL}・提示 {PROMPT_VERSION}",
        f"<b>大盤</b> 中性（把握低）：{MARKET_REASON}",
        "<b>族群</b>：PCB 可能正向",
        "<b>1. 1477 聚陽</b>｜突破｜把握中",
        "　進場 站上 233.00（不追 236.50）｜停損 226.00｜目標 243.50／254.50｜RR 1.50"
        "（除權息，價位以 09/04 為基準）",
        f"　{PICK_REASON}",
        "<b>2. 2618 長榮航</b>｜回檔到支撐｜把握中",
        "　進場區 44.40～46.05｜停損 42.00｜目標 48.95｜RR 1.20",
        f"　{PICK_REASON}",
    ]
    assert lines[10:13] == [
        "<b>3. 9999 範例</b>｜突破｜把握中",
        "　價位未通過核對，未顯示",
        f"　{PICK_REASON}",
    ]
    assert "（規則名單 3 檔見今日名單頁）" in lines
    assert "🌎 <b>隔夜美股</b>（09/04 收盤）" in lines
    assert not directive_words(message)


def test_a_failed_day_sends_the_list_before_with_its_first_line(db):
    """AC-2 (1/4 Q1-5 A): the first line says why, the title the list's date."""

    _reading(db, day=FRIDAY, list_date=THURSDAY)
    _reading(db, status="failed", reason="timeout")
    card = _card(db)
    lines = notify.text(card).splitlines()
    assert lines[:2] == [
        "今天的 AI 名單沒有產出（呼叫逾時）；以下是 09/04 的名單",
        "📋 <b>AI 名單 2026/09/04（五）開盤前</b> · AI 推論，未經驗證",
    ]
    assert notify.caption(card) == (
        "<b>AI 名單 09/04（五）</b>・09/04 的名單・3 檔・AI 推論，未經驗證"
    )
    html = notify_card.card_html(card)
    assert '<span class="stale">09/04 的名單</span>' in html
    assert "今天的 AI 名單沒有產出（呼叫逾時）；以下是 09/04 的名單" in html


def test_no_list_at_all_sends_one_line_and_the_us_block(db):
    _reading(db, status="failed", reason="timeout")
    card = _card(db, rules={"status": "not_computed"})
    lines = notify.text(card).splitlines()
    assert lines[0] == "今天的 AI 名單沒有產出（呼叫逾時）"
    assert (
        "（規則名單：無資料）" in lines and "🌎 <b>隔夜美股</b>（09/04 收盤）" in lines
    )
    assert notify_card.card_height(card) > 0 and "隔夜美股" in notify_card.card_html(
        card
    )


def test_a_reading_that_cannot_be_read_still_sends_the_us_block(db, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("output_json of another shape")

    monkeypatch.setattr(ai_list, "view", broken)
    card = notify.read(db, MONDAY)
    assert card.ai.status == notify.AI_ERROR and card.ai.error == "KeyError"
    message = notify.text(card)
    assert notify.AI_UNREADABLE in message.splitlines() and "隔夜美股" in message
    assert notify.AI_UNREADABLE in notify_card.card_html(card)


def test_a_long_text_cuts_the_reasons_from_the_last_pick_then_the_picks(db):
    """AC-3 (3/4): reasons from the last pick up first, then the picks from the last."""

    long = "根據" + "長" * 600 + "，推論可能續強"
    picks = [
        {"rank": n, "symbol": f"{1000 + n}", "name": f"名{n}", "display": DISPLAY}
        for n in range(1, 11)
    ]
    reading = _reading(db, picks=[])
    for pick in picks:
        db.add(_pick_row(db, reading, reason=long, **pick))
    db.commit()
    card = _card(db)
    full = notify.ai_list_lines(card.ai, 10, 10)
    assert notify.length("\n".join(full)) > notify.MAX_CHARS
    message = notify.text(card)
    _well_formed(message)
    assert notify.length(message) <= notify.MAX_CHARS
    # Every pick is still there with its levels; only the first ones keep a reason.
    assert all(
        f"<b>{n}. {1000 + n} 名{n}</b>｜突破｜把握中" in message for n in range(1, 11)
    )
    kept = message.count(long)
    assert 0 < kept < 10
    lines = message.splitlines()
    heads = [
        i for i, line in enumerate(lines) if line.startswith("<b>") and ". " in line
    ]
    with_reason = [i for i in heads if lines[i + 2] == f"　{long}"]
    assert with_reason == heads[:kept]
    assert "（規則名單 3 檔見今日名單頁）" in lines


def test_a_text_still_too_long_without_reasons_cuts_the_last_picks(db, monkeypatch):
    _reading(db)
    card = _card(db)
    no_reasons = "\n".join(
        [
            *notify.ai_list_lines(card.ai, 3, 0),
            card.rule_line,
            "",
            *notify.us_lines(card.us),
        ]
    )
    # Room for the text without reasons less one line: the last pick goes.
    monkeypatch.setattr(notify, "MAX_CHARS", notify.length(no_reasons) - 5)
    message = notify.text(card)
    assert PICK_REASON not in message
    assert "<b>3. 9999 範例</b>" not in message and "<b>2. 2618 長榮航</b>" in message
    assert "另 1 檔見今日名單頁" in message.splitlines()


def test_the_card_has_the_picks_levels_and_the_rule_line(db):
    _reading(db, corporate=True)
    card = _card(db)
    html = notify_card.card_html(card)
    assert '<span class="badge">AI 推論，未經驗證</span>' in html
    assert '<span class="name line">1. 1477 聚陽</span>' in html
    assert (
        "進場 站上 233.00（不追 236.50）｜停損 226.00｜目標 243.50／254.50｜RR 1.50"
        in html
    )
    assert '<div class="corp line">（除權息，價位以 09/04 為基準）</div>' in html
    assert '<div class="levels line hidden muted">價位未通過核對，未顯示</div>' in html
    assert "（規則名單 3 檔見今日名單頁）" in html
    assert 'class="stale"' not in html  # today's list
    assert notify.caption(card) == (
        "<b>AI 名單 09/07（一）</b>・3 檔・AI 推論，未經驗證"
    )
    # Three picks, one with the note: the height adds each fixed part.
    base = notify_card.card_height(
        notify.Content(MONDAY, notify.AiList("missing", line="x"), card.us, 3)
    )
    assert notify_card.card_height(card) > base
