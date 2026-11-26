"""The pre-market AI reading as 08:45 and the today page show it (#1042).

``app.premarket_ai.view`` (the champion of the current prompt version only),
``GET /api/premarket-ai``, and the AI part of the Telegram text and card
(``worker.notify``, ``worker.notify_card``) in the four cases of a day: done,
failed, rejected and no reading yet (not run or still running). The session
is MONDAY (2026-09-07), its list date T (2026-09-04).
"""

from __future__ import annotations

import dataclasses
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api as api_module
import app.main as main_module
from app import premarket_ai
from app.db import Base, enable_sqlite_foreign_keys
from app.main import app
from app.models import Instrument, PremarketAiReading, PremarketAiStock
from test_candidates import T
from test_notify import MONDAY, _list_of_t
from test_notify_card import _blank, _pixels
from worker import notify, notify_card, pipeline
from worker.premarket_reading import PROMPT_VERSION, directive_words

MODEL = "claude-sonnet-5-5"
LEVELS = {
    "rank": 1,
    "strategy": "breakout_v3",
    "entry_type": "breakout",
    "entry": 101.0,
    "entry_zone": {"low": 101.0, "high": 101.0},
    "invalid_price": 98.0,
    "target_1": 103.2,
    "target_2": None,
    "risk_reward": 0.7333,
    "earliest_execution_date": "2026-09-07",
}
LISTED_REASON = (
    "根據費半上漲 2.1%（us:SOX）與外資連三日買超，推論開盤可能跳空，價位依開盤價重算"
)
OTHER_REASON = "根據台指期夜盤缺資料，推論族群方向不明，暫緩判讀"
MARKET_REASON = "根據美股四大指數收高，推論台股開盤偏多"
SECTOR_REASON = "根據隔夜新聞（news:777），推論半導體族群可能正向"
REPRICE = {"max_gap_pct": 0.05, "max_gap_down_pct": 0.03, "min_risk_reward": 1.5}


@pytest.fixture
def db():
    """test_notify's database: in memory, with the strategies."""

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


def _payload():
    return {
        "session_date": MONDAY.isoformat(),
        "list_date": T.isoformat(),
        "taiex": {"date": T.isoformat(), "close": 20000.0},
        "us_indices": {
            "SPX": {"close": 1.0, "freshness": "latest"},
            "IXIC": {"close": 1.0, "freshness": "latest"},
            "DJI": {"close": 1.0, "freshness": "latest"},
            "SOX": {"close": 1.0, "freshness": "stale"},
        },
        "tx_futures": {"day": {"close": 1.0}, "night": {"status": "missing"}},
        "overnight_news_stats": {"total": 4, "not_judged_by_cutoff": 1},
        "market_news": [
            {"id": 777, "title": "美股收高 費半大漲", "source": "鉅亨網", "time": "x"}
        ],
        "candidates": [
            {
                "symbol": "1101",
                "exchange": "TWSE",
                "name": "台泥",
                "on_today_list": True,
                "price": {"close": 100.0},
                "chips": {"status": "missing"},
                "news": [{"id": 501, "title": "台泥擴產", "source": "中央社"}],
                "strategy_levels": LEVELS,
            },
            {
                "symbol": "2330",
                "exchange": "TWSE",
                "name": "台積電",
                "on_today_list": False,
                "price": {"status": "missing"},
                "chips": {"net": 1},
                "news": [],
            },
        ],
    }


def _output(listed_reason=LISTED_REASON):
    return {
        "market": {
            "stance": "bullish",
            "confidence": "medium",
            "reasons": [{"text": MARKET_REASON, "refs": ["us:SPX", "tx:night"]}],
        },
        "sectors": [
            {
                "group_id": "industry:24",
                "name": "半導體",
                "direction": "positive",
                "reasons": [{"text": SECTOR_REASON, "refs": ["news:777"]}],
            }
        ],
        "candidates": [],
        "data_gaps": ["台指期夜盤沒有資料，大盤判讀信心降低"],
    }


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


def _reading(
    db,
    status="done",
    *,
    reason=None,
    sequence=1,
    role="champion",
    version=PROMPT_VERSION,
    listed_reason=LISTED_REASON,
    stocks=True,
):
    at = datetime(2026, 9, 7, 0, 25)
    reading = PremarketAiReading(
        session_date=MONDAY,
        list_date=T,
        role=role,
        sequence=sequence,
        trigger="scheduler",
        prompt_version=version,
        prompt_sha256="0" * 64,
        schema_sha256="0" * 64,
        model_alias="sonnet",
        llm_model=MODEL if status != "failed" else None,
        pool_phase="morning",
        cutoff_at=datetime(2026, 9, 7, 0, 15),
        input_hash="0" * 64,
        input_json=_payload(),
        status=status,
        reason=reason,
        output_json=_output(listed_reason) if status == "done" else None,
        checks_json={},
        attempts=1,
        attempts_json=[],
        duration_ms=1000,
        usage_json={},
        started_at=at,
        finished_at=at,
    )
    db.add(reading)
    db.flush()
    if status == "done" and stocks:
        # The pool order puts the other stock first: the view lists the today list first.
        other = _instrument(db, "2330", "台積電")
        listed = _instrument(db, "1101", "台泥")
        rows = [
            (other, 2, False, None, "defer", None, OTHER_REASON, ["tx:night"]),
            (
                listed,
                1,
                True,
                LEVELS,
                "reprice",
                REPRICE,
                listed_reason,
                ["us:SOX", "news:501", "stock:1101:chips.foreign_5d", "weird"],
            ),
        ]
        for instrument, position, on_list, levels, action, rule, text, refs in rows:
            db.add(
                PremarketAiStock(
                    reading_id=reading.id,
                    session_date=MONDAY,
                    prompt_version=version,
                    role=role,
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    position=position,
                    on_today_list=on_list,
                    levels_json=levels,
                    action=action,
                    reprice_rule_json=rule,
                    reasons_json=[{"text": text, "refs": refs}],
                )
            )
    db.commit()
    return reading


# --- the view ------------------------------------------------------------------------


def test_a_done_reading_lists_the_today_list_first_and_only_it_has_prices(db):
    _reading(db)
    view = premarket_ai.view(db, session_date=MONDAY)
    assert view["status"] == "done"
    assert (view["llm_model"], view["prompt_version"]) == (MODEL, PROMPT_VERSION)
    assert [stock["symbol"] for stock in view["stocks"]] == ["1101", "2330"]
    listed, other = view["stocks"]
    # 3a: the rule's levels on the today-list stock, no price key at all on the other.
    assert listed["levels"] == LEVELS and listed["rank"] == 1
    assert "levels" not in other and "rank" not in other
    assert set(other) == {
        "symbol",
        "exchange",
        "name",
        "on_today_list",
        "action",
        "action_text",
        "reprice_rule",
        "reprice_text",
        "reasons",
    }
    assert listed["action_text"] == "依開盤價重算"
    assert (
        listed["reprice_text"]
        == "開盤漲幅逾 5.0%、跌幅逾 3.0%或重算後 RR 低於 1.5 倍即暫緩"
    )
    assert other["action_text"] == "暫緩" and other["reprice_text"] is None
    assert view["market"]["stance_text"] == "偏多"
    assert view["market"]["confidence_text"] == "把握中"
    assert view["sectors"][0]["direction_text"] == "可能正向"


def test_cited_news_carry_their_id_and_title_and_other_refs_a_label(db):
    _reading(db)
    view = premarket_ai.view(db, session_date=MONDAY)
    refs = view["stocks"][0]["reasons"][0]["refs"]
    assert refs == [
        {"ref": "us:SOX", "kind": "us", "label": "美股 費半"},
        {"ref": "news:501", "kind": "news", "news_id": 501, "label": "台泥擴產"},
        {"ref": "stock:1101:chips.foreign_5d", "kind": "stock", "label": "1101 籌碼"},
        {"ref": "weird", "kind": "other", "label": None},
    ]
    sector_ref = view["sectors"][0]["reasons"][0]["refs"][0]
    assert sector_ref["news_id"] == 777 and sector_ref["label"] == "美股收高 費半大漲"


def test_the_data_gaps_are_shown_as_the_input_and_the_ai_have_them(db):
    _reading(db)
    view = premarket_ai.view(db, session_date=MONDAY)
    assert view["input_gaps"] == [
        "美股 費半 非最新",
        "台指期夜盤無資料",
        "隔夜新聞 1 則截止前尚未判讀",
        "1101 台泥 無籌碼資料",
        "2330 台積電 名單日無日線",
    ]
    assert view["data_gaps"] == ["台指期夜盤沒有資料，大盤判讀信心降低"]


def test_only_the_champion_of_the_current_version_is_shown(db):
    _reading(db, role="shadow", listed_reason="影子版本的理由")
    _reading(db, version="premarket_v0", listed_reason="舊版本的理由")
    assert premarket_ai.view(db, session_date=MONDAY)["status"] == "missing"
    _reading(db, "failed", reason="timeout")
    view = premarket_ai.view(db, session_date=MONDAY)
    assert (view["status"], view["reason_text"]) == ("failed", "呼叫逾時")
    _reading(db, sequence=2, stocks=False)
    assert premarket_ai.view(db, session_date=MONDAY)["status"] == "done"


@pytest.mark.parametrize(
    ("status", "reason", "text"),
    [
        ("failed", "rate_limited", "訂閱用量已達上限"),
        ("rejected", "directive_words", "判讀含交易指示用語"),
        ("rejected", "something_new", "其他原因"),
    ],
)
def test_a_reading_that_is_not_done_has_its_reason_and_nothing_else(
    db, status, reason, text
):
    _reading(db, status, reason=reason)
    view = premarket_ai.view(db, session_date=MONDAY)
    assert (view["status"], view["reason"], view["reason_text"]) == (
        status,
        reason,
        text,
    )
    assert view["market"] is None and view["stocks"] == [] and view["sectors"] == []


@pytest.fixture
def client(db, monkeypatch):
    def override_get_db():
        yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(api_module.get_db, None)


def test_the_api_reads_the_reading_of_a_list_date_or_says_missing(client, db):
    empty = client.get("/api/premarket-ai", params={"list_date": T.isoformat()})
    assert empty.status_code == 200
    assert empty.json()["status"] == "missing"
    assert empty.json()["list_date"] == T.isoformat()
    _reading(db)
    for params in ({"list_date": T.isoformat()}, {"date": MONDAY.isoformat()}, {}):
        body = client.get("/api/premarket-ai", params=params).json()
        assert body["status"] == "done", params
        assert body["session_date"] == MONDAY.isoformat()
        assert "levels" not in body["stocks"][1]
    other = client.get("/api/premarket-ai", params={"list_date": "2026-09-07"})
    assert other.json()["status"] == "missing"


# --- 08:45: the text and the card ------------------------------------------------------


def _content(db, **reading):
    _list_of_t(db)
    if reading.get("status") != "none":
        _reading(db, **reading)
    return notify.read(db, MONDAY)


def _ai_part(message: str) -> str:
    """The text from the AI section's title on."""

    at = message.find(notify.AI_TITLE)
    return message[at:] if at >= 0 else ""


def test_a_done_reading_is_sent_in_its_own_section_after_the_list(db):
    card = _content(db)
    message = notify.text(card)
    assert card.ai_line is None
    assert "AI 判讀失敗" not in message and notify.AI_PENDING not in message
    ai = _ai_part(message)
    lines = ai.splitlines()
    assert lines[0] == "早盤 AI 判讀</b>（AI 推論）"
    assert lines[1] == f"模型 {MODEL}・提示 {PROMPT_VERSION}"
    assert lines[2] == "<b>大盤</b> 偏多（把握中）"
    assert f"　{MARKET_REASON}" in lines
    assert f"　半導體 可能正向：{SECTOR_REASON}" in lines
    # The today list first, then the pool's others; no price in the section (3a).
    assert lines.index("<b>今日名單的股票</b>") < lines.index("<b>候選池其他股票</b>")
    assert (
        "<b>1101 台泥</b>　依開盤價重算（開盤漲幅逾 5.0%、跌幅逾 3.0%或重算後 RR 低於 1.5 倍即暫緩）"
        in lines
    )
    assert "<b>2330 台積電</b>　暫緩" in lines
    assert not re.search(r"進場|停損|目標|\d+\.\d{2}(?!%)", ai)
    # The section comes after the list and the US block.
    assert message.index("隔夜美股") < message.index(notify.AI_TITLE)
    html = notify_card.card_html(card)
    assert (
        '<section class="ai"><h2>早盤 AI 判讀<span class="badge">AI 推論</span></h2>'
        in html
    )
    assert f"模型 {MODEL}・提示 {PROMPT_VERSION}" in html
    assert "2330 台積電" in html and '<div class="ai-line' not in html
    assert notify_card.ai_height(card) > 0


@pytest.mark.parametrize(
    ("case", "line"),
    [
        ({"status": "failed", "reason": "timeout"}, "今日 AI 判讀失敗：呼叫逾時"),
        (
            {"status": "rejected", "reason": "coverage"},
            "今日 AI 判讀失敗：判讀漏了或多了股票",
        ),
        ({"status": "none"}, "今日 AI 判讀尚未完成"),
    ],
    ids=["failed", "rejected", "not_yet"],
)
def test_a_reading_not_done_sends_the_list_only_with_one_line(db, case, line):
    card = _content(db, **case)
    message = notify.text(card)
    assert card.ai_line == line
    lines = message.splitlines()
    # Under the head (and the pre-open line), before the list's rows.
    assert line in lines[2:4] and lines.index(line) < lines.index(
        "🚀 <b>突破（1 檔）</b>"
    )
    assert notify.AI_TITLE not in message and "AI 推論" not in message
    html = notify_card.card_html(card)
    assert f'<div class="ai-line line">{line}</div>' in html
    assert 'class="ai"' not in html and notify_card.ai_height(card) == 0
    # The line is one more head line of the card, nothing else.
    without = dataclasses.replace(card, ai=None)
    assert (
        notify_card.card_height(card)
        == notify_card.card_height(without) + notify_card.HEAD_LINE_H
    )


def test_the_texts_have_no_order_wording(db):
    """AC-3: the message (text, card) and every fixed wording of the AI part pass the
    job's own check (``directive_words``)."""

    card = _content(db)
    page = re.sub(r"<[^>]+>", "\n", notify_card.card_html(card))
    assert directive_words([notify.text(card), page]) == []
    fixed = [
        *premarket_ai.ACTION_TEXT.values(),
        *premarket_ai.REASON_TEXT.values(),
        *premarket_ai.STANCE_TEXT.values(),
        *premarket_ai.DIRECTION_TEXT.values(),
        premarket_ai.reprice_text(REPRICE),
        notify.AI_FAILED,
        notify.AI_PENDING,
        notify.AI_LISTED,
        notify.AI_OTHERS,
    ]
    assert directive_words(fixed) == []
    # The check would catch one (the test is not empty).
    assert directive_words(["今日買進"]) != []


def test_a_long_reading_cuts_its_stocks_before_the_lists_rows(db, monkeypatch):
    card = _content(db, listed_reason="根據" + "外資買超" * 1100 + "，推論維持")
    message = notify.text(card)
    assert notify.length(message) <= notify.MAX_CHARS
    assert "另 2 檔的 AI 判讀見今日名單頁" in message
    # The list's own row is still there.
    assert "　進場 " in message


BROWSER = notify_card.find_browser()


@pytest.fixture
def card_temp(monkeypatch):
    """Its own system temp directory, as test_notify_card's private_temp (a short path:
    Chromium's profile socket)."""

    temp = Path(tempfile.mkdtemp(prefix="nc-"))
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.mark.skipif(
    BROWSER is None, reason="no Chromium (the image has it: docker job)"
)
def test_the_images_chromium_draws_the_ai_section_in_its_height(
    db,
    card_temp,
    monkeypatch,
):
    card = _content(db)
    height = notify_card.card_height(card)
    extra = 40
    monkeypatch.setattr(notify_card, "card_height", lambda _card: height + extra)
    drawn = notify_card.render(card, timeout=120.0)
    assert drawn.reason is None, drawn.reason
    scale = notify_card.SCALE
    _width, channels, rows = _pixels(drawn.png)
    assert all(_blank(row, channels) for row in rows[height * scale :])
    edge = (height - notify_card.PAD) * scale
    assert not all(_blank(row, channels) for row in rows[edge - 4 : edge])
    assert all(_blank(row, channels) for row in rows[edge + 2 : height * scale])
    assert os.listdir(card_temp) == []
