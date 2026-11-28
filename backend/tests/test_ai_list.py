"""The AI list (#1145): level facts, checks of the answer and of each pick's levels,
the rows (only added) and the job.

The DB is test_premarket_ai's ``world`` of D = Tuesday 2026-11-24 (list date L =
Monday 2026-11-23): every pool stock has 25 bars, closes 100..124, high close + 1,
low close − 1, so on L: close 124, ma5 122, ma20 114.5, high_20 125 (L), low_20
104, atr14 2 (every true range is 2), tick 0.5, D's limits 112..136.  No test calls
the real CLI.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session
from test_premarket_ai import (
    BROKEN,
    D,
    DAYS,
    L,
    MODEL,
    RATE_LIMITED,
    TIMEOUT,
    FakeCli,
    bars,
    envelope,
    instrument,
    linux_only,
    tpe,
    valid,
)

# test_premarket_ai's fixtures, imported under other names and given back their own
# below (a test parameter named like an import would shadow it).
from test_premarket_ai import db as premarket_db  # noqa: F401
from test_premarket_ai import no_network as premarket_no_network  # noqa: F401
from test_premarket_ai import world as premarket_world  # noqa: F401

from app.db import enable_sqlite_foreign_keys
from app.models import (
    AiListPick,
    AiListReading,
    CorporateAction,
    IngestionRun,
    Instrument,
    MarketBar,
    PremarketAiReading,
    PremarketAiScore,
    PremarketAiStock,
    RawPayload,
)
from worker import ai_list, ai_list_input, ai_list_reading, premarket_ai
from worker.news_llm import LlmBatchError
from worker.premarket_score import score_readings


@pytest.fixture(autouse=True)
def no_network(request):
    return request.getfixturevalue("premarket_no_network")


@pytest.fixture
def db(request):
    return request.getfixturevalue("premarket_db")


@pytest.fixture
def world(request):
    return request.getfixturevalue("premarket_world")


def snapshot(db):
    return ai_list_input.build(db, D, L, tpe(D, 8, 21))


def _price(price, field, multiple=0, symbol="2330"):
    return {
        "price": price,
        "refs": [f"stock:{symbol}:{field}"],
        "atr_multiple": multiple,
    }


def good_pick(symbol="2330", rank=1, **levels):
    """A breakout on high_20 125 (ATR 2): entry 125～126, stop 120 (ma5 − 1 ATR),
    target 131 (high_20 + 3 ATR); RR (131 − 125) ÷ (125 − 120) = 1.2."""

    out = {
        "symbol": symbol,
        "rank": rank,
        "method": {
            "setup": "breakout",
            "basis": ["technical", "chips"],
            "confidence": "medium",
        },
        "reasons": [
            {
                "text": "根據收盤貼近 20 日高點，推論站上前高可能續強。",
                "refs": [f"stock:{symbol}:high_20"],
            }
        ],
        "levels": {
            "entry": {
                "type": "breakout",
                "low": _price(125, "high_20", symbol=symbol),
                "high": _price(126, "high_20", 0.5, symbol=symbol),
                "condition": "若股價站上 20 日高點，才視為突破成立。",
            },
            "stop": _price(120, "ma5", -1, symbol=symbol),
            "target_1": _price(131, "high_20", 3, symbol=symbol),
            "target_2": None,
            "exit_conditions": [
                {
                    "text": "觀察外資是否轉為連續賣超。",
                    "refs": [f"stock:{symbol}:foreign_net_lots_5d"],
                }
            ],
            "valid_sessions": 3,
        },
    }
    out["levels"].update(levels)
    return out


def answer(payload, picks=None, **change):
    news_id = payload["market_news"][0]["id"]
    out = {
        "market": {
            "stance": "neutral",
            "confidence": "medium",
            "method": {"basis": ["us", "news"]},
            "reasons": [
                {
                    "text": "根據美股與隔夜消息，推論大盤開盤持平。",
                    "refs": [f"news:{news_id}", "us:SPX"],
                },
                {"text": "根據台指期夜盤，推論開盤波動有限。", "refs": ["tx:night"]},
            ],
        },
        "sectors": [],
        "picks": [good_pick()] if picks is None else picks,
        "empty_reason": None,
        "data_gaps": [],
    }
    out.update(change)
    return out


def replying(build):
    """A FakeCli answer: BUILD(payload) -> output."""

    return lambda payload: envelope(build(payload))


def ok(payload):
    return envelope(answer(payload))


def read(db, cli, **kwargs):
    shot = snapshot(db)
    return shot, ai_list_reading.read(shot, ["claude"], cli, **kwargs)


# --- the input: level facts -----------------------------------------------------------


def test_level_facts_by_hand(db, world):
    shot = snapshot(db)
    item = next(item for item in shot.payload["candidates"] if item["symbol"] == "2330")
    facts = item["level_facts"]
    assert facts["version"] == "ai_list_facts_v1" and facts["basis"] == "list_date_raw"
    assert facts["close"] == 124.0 and facts["as_of"] == L.isoformat()
    assert (facts["ma5"], facts["ma10"], facts["ma20"]) == (122.0, 119.5, 114.5)
    # 25 bars: no 60-session facts.
    assert facts["ma60"] is None and facts["high_60"] is None
    assert facts["volume_node_60"] is None
    assert facts["high_20"] == {"price": 125.0, "date": L.isoformat()}
    assert facts["low_20"] == {"price": 104.0, "date": DAYS[5].isoformat()}
    assert facts["atr14"] == 2.0 and facts["tick"] == 0.5
    # 124 × 0.9 = 111.6 up to 112; 124 × 1.1 = 136.4 down to 136.
    assert (facts["limit_down"], facts["limit_up"]) == (112.0, 136.0)
    assert facts["corporate_action_in_window"] is False
    assert shot.payload["level_facts_version"] == "ai_list_facts_v1"
    # The rest of the snapshot is premarket_v1's.
    assert "strategy_levels" in item and "price" in item and "chips" in item


def test_the_window_is_put_on_the_list_dates_basis(db):
    """A 5 cash dividend on L at reference 100: the bars before are × 0.95."""

    row = instrument(db, "9999")
    days = DAYS[-21:]
    bars(db, row, [100.0] * 20 + [95.0], days=days)
    db.add(
        CorporateAction(
            instrument_id=row.id,
            action_date=L,
            action_type="dividend",
            cash_dividend=5.0,
            reference_price=100.0,
        )
    )
    db.flush()
    facts = ai_list_input.level_facts(db, row, L, D)
    assert facts["corporate_action_in_window"] is True
    # Raw: (4 × 100 + 95) / 5 = 99; on L's basis every close is 95.
    assert facts["ma5"] == 95.0 and facts["ma20"] == 95.0
    # high 100 + 1 before the action → 101 × 0.95 = 95.95; L's own high is 96.
    assert facts["high_20"] == {"price": 96.0, "date": L.isoformat()}
    # 13 true ranges of 101 × 0.95 − 99 × 0.95 = 1.9 and L's 96 − 94 = 2:
    # (13 × 1.9 + 2) ÷ 14 = 1.907.  Raw, L's range would be |94 − 100| = 6.
    assert facts["atr14"] == 1.907


def test_a_stock_without_the_list_dates_bar_has_no_facts(db):
    row = instrument(db, "9998")
    bars(db, row, [50.0] * 5, days=DAYS[-6:-1])
    assert ai_list_input.level_facts(db, row, L, D) == {"status": "missing"}


# --- the levels of one pick (#1142 2/4) ----------------------------------------------


@pytest.fixture
def item(db, world):
    shot = snapshot(db)
    return copy.deepcopy(
        next(item for item in shot.payload["candidates"] if item["symbol"] == "2330")
    )


def problems(result):
    return [problem["check"] for problem in result["problems"]]


def test_a_good_pick_passes_with_the_rr_the_program_computes(item):
    result = ai_list_reading.check_levels(good_pick(), item, D)
    assert result["status"] == "pass" and result["problems"] == []
    assert result["risk_reward"] == 1.2 and result["reference_entry"] == 125.0
    assert result["rounded"] == []
    assert result["display"] == {
        "entry": {"type": "breakout", "low": 125.0, "high": 126.0},
        "stop": 120.0,
        "target_1": 131.0,
        "target_2": None,
        "risk_reward": 1.2,
        "valid_sessions": 3,
    }
    assert result["prices"]["stop"]["expected"] == 120.0


def test_prices_are_rounded_to_the_tick_and_rr_is_on_the_rounded_prices(item):
    """Tick 0.5: entry low 125.3 down to 125, stop 120.2 up to 120.5, entry high
    125.8 up to 126, target 130.9 down to 130.5; RR (130.5 − 125) ÷ (125 − 120.5)
    = 5.5 ÷ 4.5 = 1.22."""

    pick = good_pick(
        stop=_price(120.2, "ma5", -1),
        target_1=_price(130.9, "high_20", 3),
    )
    pick["levels"]["entry"]["low"] = _price(125.3, "high_20")
    pick["levels"]["entry"]["high"] = _price(125.8, "high_20", 0.5)
    result = ai_list_reading.check_levels(pick, item, D)
    assert result["status"] == "pass"
    assert sorted(result["rounded"]) == ["entry.high", "entry.low", "stop", "target_1"]
    assert result["display"]["entry"] == {
        "type": "breakout",
        "low": 125.0,
        "high": 126.0,
    }
    assert (result["display"]["stop"], result["display"]["target_1"]) == (120.5, 130.5)
    assert result["risk_reward"] == 1.22


def test_a_pullback_measures_rr_from_the_middle_of_its_zone(item):
    """Entry 121～122 (ma5 − 0.5 ATR, ma5), stop 118 (ma5 − 2 ATR), target 126
    (high_20 + 0.5 ATR): RR (126 − 121.5) ÷ (121.5 − 118) = 4.5 ÷ 3.5 = 1.29."""

    pick = good_pick(stop=_price(118, "ma5", -2), target_1=_price(126, "high_20", 0.5))
    pick["levels"]["entry"] = {
        "type": "pullback",
        "low": _price(121, "ma5", -0.5),
        "high": _price(122, "ma5"),
        "condition": "若股價回到 5 日均線附近，才視為進場區成立。",
    }
    result = ai_list_reading.check_levels(pick, item, D)
    assert result["status"] == "pass"
    assert result["reference_entry"] == 121.5 and result["risk_reward"] == 1.29


def test_rr_and_rounding_by_hand():
    assert ai_list_reading.risk_reward("breakout", 10, 11, 8, 13) == 1.5
    assert ai_list_reading.risk_reward("pullback", 10, 11, 8, 13) == pytest.approx(
        2.5 / 2.5
    )
    assert ai_list_reading.risk_reward("breakout", 10, 11, 10, 13) is None
    # 2027-07-05 on: a TWSE stock at 1000 and above moves by 1, not 5.
    assert ai_list_reading.rounded("stop", 1002.2, "stock", "TWSE", D) == 1005.0
    assert (
        ai_list_reading.rounded("stop", 1002.2, "stock", "TWSE", date(2027, 7, 5))
        == 1003.0
    )
    assert ai_list_reading.rounded("target_1", 21.86, "stock", "TWSE", D) == 21.85
    assert ai_list_reading.rounded("entry.high", 21.86, "stock", "TWSE", D) == 21.9


def _with(pick, name, level):
    if name.startswith("entry."):
        pick["levels"]["entry"][name.split(".")[1]] = level
    else:
        pick["levels"][name] = level
    return pick


@pytest.mark.parametrize(
    "change, check",
    [
        # refs[0] is a ratio, another stock's field, or nothing of the input.
        (lambda p: _with(p, "stop", _price(120, "ret_5d")), "ref_not_price_field"),
        (
            lambda p: _with(p, "stop", _price(120, "ma5", -1, symbol="2412")),
            "ref_not_price_field",
        ),
        (
            lambda p: _with(
                p, "stop", {"price": 120, "refs": ["taiex"], "atr_multiple": 0}
            ),
            "ref_not_price_field",
        ),
        # A multiple off the table (the sample's 0.04).
        (
            lambda p: _with(p, "entry.low", _price(125.08, "high_20", 0.04)),
            "atr_multiple_not_allowed",
        ),
        # 128 is not high_20 125 within max(2 ticks, 0.5%) = 1.
        (
            lambda p: _with(p, "target_1", _price(133, "high_20", 3) | {"price": 128}),
            "ref_mismatch",
        ),
        # 137 = limit_up 136 + 0.5 ATR, past D's limit up.
        (
            lambda p: _with(p, "target_2", _price(137, "limit_up", 0.5)),
            "outside_limits",
        ),
        # The stop above the entry.
        (lambda p: _with(p, "stop", _price(126, "high_20", 0.5)), "order"),
        # Target 1 126.5 (high_20 + 0.5 ATR within 1): RR (126.5 − 125) ÷ 5 = 0.3.
        (
            lambda p: _with(
                p, "target_1", _price(126.5, "high_20", 0.5) | {"price": 126.5}
            ),
            "risk_reward_below_min",
        ),
    ],
)
def test_each_failing_level_check(item, change, check):
    result = ai_list_reading.check_levels(change(good_pick()), item, D)
    assert result["status"] == "fail" and result["display"] is None
    assert check in problems(result)


def _cheap_item(stop, target):
    """A TWSE stock at 9 (tick 0.01 below 10, 0.05 from 10) without limits: a breakout
    at high_20 9.00, stop low_20 STOP, target high_60 TARGET (each on its base)."""

    return {
        "symbol": "2330",
        "exchange": "TWSE",
        "price": {"close": 9.0},
        "level_facts": {
            "instrument_type": "stock",
            "close": 9.0,
            "tick": 0.01,
            "atr14": 0.1,
            "high_20": {"price": 9.0, "date": L.isoformat()},
            "low_20": {"price": stop, "date": L.isoformat()},
            "high_60": {"price": target, "date": L.isoformat()},
            "limit_up": None,
            "limit_down": None,
        },
    }


@pytest.mark.parametrize(
    "stop, target, stored, passed",
    [
        # (11.00 − 9.00) ÷ (9.00 − 6.99) = 0.99502: stored 1.0, and so it passes.
        (6.99, 11.0, 1.0, True),
        # (11.00 − 9.00) ÷ (9.00 − 6.98) = 0.99010: stored 0.99, below 1.0.
        (6.98, 11.0, 0.99, False),
        # (11.05 − 9.00) ÷ (9.00 − 6.95) = 1.0 exactly.
        (6.95, 11.05, 1.0, True),
    ],
)
def test_the_rr_judged_is_the_rr_stored(stop, target, stored, passed):
    """PR #1151 review, 2: no row stores risk_reward=1.0 with risk_reward_below_min."""

    pick = good_pick(
        stop=_price(stop, "low_20"),
        target_1=_price(target, "high_60"),
    )
    pick["levels"]["entry"]["low"] = _price(9.0, "high_20")
    pick["levels"]["entry"]["high"] = _price(9.05, "high_20", 0.5)
    result = ai_list_reading.check_levels(pick, _cheap_item(stop, target), D)
    assert result["risk_reward"] == stored
    assert ("risk_reward_below_min" not in problems(result)) is passed
    assert (result["status"] == "pass") is passed


def test_no_atr_with_a_multiple_fails(item):
    item["level_facts"]["atr14"] = None
    result = ai_list_reading.check_levels(good_pick(), item, D)
    assert "no_atr" in problems(result)


def test_a_pick_without_level_facts_fails(item):
    item["level_facts"] = {"status": "missing"}
    result = ai_list_reading.check_levels(good_pick(), item, D)
    assert problems(result) == ["no_level_facts"]


def test_an_etf_has_no_limits_to_check(item):
    item["level_facts"].update(limit_up=None, limit_down=None, instrument_type="etf")
    pick = _with(good_pick(), "target_2", _price(137, "high_20", 6) | {"price": 137})
    # 6 is no allowed multiple either way: only the limit check is left out.
    result = ai_list_reading.check_levels(pick, item, D)
    assert "outside_limits" not in problems(result)


# --- the checks of an answer -----------------------------------------------------------


def _payload(db):
    return snapshot(db).payload


@pytest.mark.parametrize(
    "build, reason",
    [
        (lambda p: answer(p, [good_pick(), good_pick("9999", 2)]), "not_in_pool"),
        (lambda p: answer(p, [good_pick(), good_pick(rank=2)]), "duplicate_pick"),
        (lambda p: answer(p, [good_pick(rank=2)]), "rank_not_contiguous"),
        (
            lambda p: answer(p, [good_pick(), good_pick("2412", 3)]),
            "rank_not_contiguous",
        ),
        (lambda p: answer(p, []), "empty_without_reason"),
        (lambda p: answer(p, [], empty_reason="  "), "empty_without_reason"),
    ],
)
def test_a_wrong_list_is_rejected_without_a_retry(db, world, build, reason):
    cli = FakeCli(replying(build), ok)
    _shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("rejected", reason)
    assert len(cli.prompts) == 1


def test_an_empty_list_with_its_reason_is_done(db, world):
    _shot, outcome = read(
        db,
        FakeCli(
            replying(
                lambda p: answer(p, [], empty_reason="大盤偏空，推論今日不宜列股。")
            )
        ),
    )
    assert outcome.status == "done" and outcome.checks["picks"] == {}


def test_an_unknown_news_ref_is_rejected(db, world):
    def build(payload):
        out = answer(payload)
        out["picks"][0]["reasons"][0]["refs"].append("news:999999")
        return out

    _shot, outcome = read(db, FakeCli(replying(build)))
    assert (outcome.status, outcome.reason) == ("rejected", "unknown_news_ref")


@pytest.mark.parametrize(
    "where",
    ["reason", "condition", "exit", "empty_reason"],
)
def test_order_wording_anywhere_is_rejected(db, world, where):
    def build(payload):
        out = answer(payload)
        pick = out["picks"][0]
        if where == "reason":
            pick["reasons"][0]["text"] = "根據前高，推論建議買進。"
        elif where == "condition":
            pick["levels"]["entry"]["condition"] = "開盤進場，站上 125 才算。"
        elif where == "exit":
            pick["levels"]["exit_conditions"][0]["text"] = "跌破就立即出場。"
        else:
            out["picks"] = []
            out["empty_reason"] = "今天不要買進。"
        return out

    _shot, outcome = read(db, FakeCli(replying(build)))
    assert (outcome.status, outcome.reason) == ("rejected", "directive_words")


def _code(payload, path, value):
    out = answer(payload)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


@pytest.mark.parametrize(
    "path, value",
    [
        # Codes off the table (Q2-6 A): the schema stops them.
        (("picks", 0, "method", "setup"), "gap_follow"),
        (("picks", 0, "method", "basis"), ["fundamental"]),
        (("market", "method", "basis"), ["chips"]),
        # The order is the rank: a repeated code has none.
        (("picks", 0, "method", "basis"), ["chips", "chips"]),
        (("market", "method", "basis"), ["us", "us"]),
        (("picks", 0, "levels", "valid_sessions"), 6),
        (("picks", 0, "levels", "entry", "type"), "gap"),
        # Reason counts (PR #1151 review suggestion 1): a pick 1 to 3, the market 2 to 4.
        (("picks", 0, "reasons"), []),
        (("picks", 0, "reasons"), [{"text": "根據籌碼，推論偏多。", "refs": []}] * 4),
        (("market", "reasons"), [{"text": "根據美股，推論持平。", "refs": ["us:SPX"]}]),
    ],
)
def test_a_code_off_the_table_is_retried_once_then_rejected(db, world, path, value):
    cli = FakeCli(
        replying(lambda p: _code(p, path, value)),
        replying(lambda p: _code(p, path, value)),
    )
    _shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("rejected", "schema")
    assert len(cli.prompts) == 2


def test_a_schema_failure_then_a_good_answer_is_done(db, world):
    cli = FakeCli(
        replying(lambda p: _code(p, ("picks", 0, "method", "setup"), "x")), ok
    )
    _shot, outcome = read(db, cli)
    assert outcome.status == "done" and len(outcome.attempts) == 2


def test_more_than_ten_picks_is_a_schema_failure(db, world):
    picks = [good_pick(rank=rank) for rank in range(1, 12)]
    with pytest.raises(LlmBatchError, match="11 items"):
        ai_list_reading.validate_schema(answer(_payload(db), picks))


def test_an_edited_prompt_without_a_new_version_is_not_called(db, world, monkeypatch):
    monkeypatch.setitem(ai_list_reading.PROMPTS, "ai_list_v1", "0" * 64)
    cli = FakeCli(ok)
    _shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("failed", "prompt_hash_mismatch")
    assert cli.prompts == [] and outcome.attempts == []


@pytest.mark.parametrize("first", [TIMEOUT, BROKEN])
def test_a_timeout_or_a_broken_answer_is_retried_once(db, world, first):
    _shot, outcome = read(db, FakeCli(first, ok))
    assert outcome.status == "done" and len(outcome.attempts) == 2


def test_rate_limited_is_not_retried(db, world):
    cli = FakeCli(RATE_LIMITED, ok)
    _shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("failed", "rate_limited")
    assert len(cli.prompts) == 1


def test_a_failed_level_check_keeps_the_reading_done(db, world):
    def build(payload):
        bad = good_pick(
            "2412", 2, target_1=_price(126.5, "high_20", 0.5, symbol="2412")
        )
        return answer(payload, [good_pick(), bad])

    _shot, outcome = read(db, FakeCli(replying(build)))
    assert outcome.status == "done"
    assert outcome.checks["picks"]["2330"]["status"] == "pass"
    assert outcome.checks["picks"]["2412"]["status"] == "fail"
    assert outcome.checks["picks_passed"] == 1


def test_recorded_only_prices_long_reasons_and_unknown_groups(db, world):
    def build(payload):
        out = answer(payload)
        out["picks"][0]["reasons"][0]["text"] = (
            "根據消息，推論股價可望挑戰 2300 元。" + "字" * 120
        )
        out["sectors"] = [
            {
                "group_id": "theme:none",
                "name": "無",
                "direction": "mixed",
                "reasons": [],
            }
        ]
        return out

    _shot, outcome = read(db, FakeCli(replying(build)))
    assert outcome.status == "done"
    assert outcome.checks["price_mentions"] == [
        {"symbol": "2330", "where": "reasons[0]", "price": "2300 元"}
    ]
    assert outcome.checks["long_reasons"] == 1
    assert outcome.checks["unknown_group_ids"] == ["theme:none"]


def test_a_price_of_the_input_is_no_unknown_price(db, world):
    def build(payload):
        out = answer(payload)
        out["picks"][0]["reasons"][0]["text"] = (
            "根據收盤 124 元貼近 20 日高點 125.00，推論可能續強。"
        )
        return out

    _shot, outcome = read(db, FakeCli(replying(build)))
    assert outcome.checks["price_mentions"] == []


def test_the_prompt_and_schema_are_pinned():
    text = ai_list_reading.prompt_text("ai_list_v1")
    assert ai_list_reading._sha256(text) == ai_list_reading.PROMPTS["ai_list_v1"]
    # Changing the schema needs a new version too.
    assert ai_list_reading.SCHEMA_SHA256 == (
        "5cbc238882cbdab744e21c55c27706b2e6901ce0ec169d661457955cf522a494"
    )
    assert "最多 10 檔" in text and "1.0" in text


def test_the_prompt_is_sent_with_the_schema_and_no_previous_list(db, world):
    cli = FakeCli(ok)
    shot, outcome = read(db, cli)
    argv = cli.argv[0]
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["properties"]["picks"]["maxItems"] == 10
    assert "--model" in argv and argv[argv.index("--model") + 1] == "sonnet"
    payload = json.loads(
        cli.prompts[0].split("<input>\n", 1)[1].rsplit("\n</input>", 1)[0]
    )
    assert "level_facts" in payload["candidates"][0]
    assert not any("ai_list" in key for key in payload if key != "level_facts_version")
    assert outcome.prompt_sha256 == ai_list_reading.PROMPTS["ai_list_v1"]


# --- the job and its rows ----------------------------------------------------------------


@pytest.fixture
def run_env(tmp_path, monkeypatch, db, world):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("STOCK_DATA_DIR", str(data))
    cli_path = tmp_path / "claude"
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("STOCK_CLAUDE_CLI", str(cli_path))
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    @contextlib.contextmanager
    def session():
        yield db

    monkeypatch.setattr(ai_list, "_session", session)
    monkeypatch.setattr(premarket_ai, "_session", session)
    return argparse.Namespace(data=data, logs=data / "logs", db=db, world=world)


def _args(module, *argv):
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    return parser.parse_args(list(argv))


def job(env, cli, *extra, at="08:21", trigger="scheduler", module=ai_list):
    args = _args(
        module,
        "--now",
        f"{D.isoformat()}T{at}",
        "--trigger",
        trigger,
        "--log-dir",
        str(env.logs),
        "--min-free-memory-gb",
        "0",
        *extra,
    )
    out = io.StringIO()
    code = module._Run(args, runner=cli, out=out).run()
    return code, out.getvalue()


def _log(env) -> str:
    return (env.logs / "ai-list-20261124.log").read_text(encoding="utf-8")


def _rows(db, model=AiListReading):
    return db.scalars(select(model).order_by(model.id)).all()


def _frozen(row):
    return {
        column.key: getattr(row, column.key)
        for column in inspect(type(row)).mapper.column_attrs
    }


def _two_picks(payload):
    bad = good_pick("2412", 2, target_1=_price(126.5, "high_20", 0.5, symbol="2412"))
    return envelope(answer(payload, [good_pick(), bad]))


@linux_only
def test_the_scheduled_run_stores_the_reading_and_its_picks(run_env):
    code, _out = job(run_env, FakeCli(_two_picks))
    assert code == 0
    log = _log(run_env)
    assert "start job=ai-list trigger=scheduler" in log
    assert "--- input session_date=2026-11-24 list_date=2026-11-23" in log
    assert "--- result status=done session_date=2026-11-24" in log
    assert "prompt_version=ai_list_v1 model=claude-sonnet-5-5 attempts=1" in log
    assert "picks=2 levels_passed=1" in log
    assert "--- pick rank=2 symbol=2412 setup=breakout" in log
    assert "levels=fail risk_reward=0.3 problems=risk_reward_below_min" in log
    (reading,) = _rows(run_env.db)
    assert (reading.status, reading.sequence, reading.role) == ("done", 1, "champion")
    assert reading.market_method_json == ["us", "news"]
    assert reading.model_alias == "sonnet" and reading.llm_model == MODEL
    assert reading.schema_sha256 == ai_list_reading.SCHEMA_SHA256
    assert reading.input_json["level_facts_version"] == "ai_list_facts_v1"
    run = run_env.db.get(IngestionRun, reading.ingestion_run_id)
    assert run.run_type == "ai_list" and run.status == "success"
    raw_id = reading.attempts_json[0]["raw_payload_id"]
    assert run_env.db.get(RawPayload, raw_id).source == "ai_list"
    first, second = _rows(run_env.db, AiListPick)
    assert (first.rank, first.symbol, second.rank, second.symbol) == (
        1,
        "2330",
        2,
        "2412",
    )
    assert first.on_rule_list is True and first.rule_levels_json["rank"] == 1
    assert first.setup == "breakout" and first.basis_primary == "technical"
    assert first.basis_json == ["technical", "chips"]
    assert first.risk_reward == 1.2 and first.valid_sessions == 3
    # D (Tue) is the first session: Tue, Wed, Thu.
    assert first.valid_until == D + timedelta(days=2)
    assert first.display_levels_json["valid_until"] == "2026-11-26"
    assert first.display_levels_json["stop"] == 120.0
    # A failed check keeps the rank and reasons, no display levels (Q2-5 A).
    assert second.display_levels_json is None and second.reasons_json
    assert second.levels_check_json["status"] == "fail"
    assert ai_list.day_done(run_env.logs, D)


def test_valid_until_skips_a_closed_day(db):
    from app.models import TradingCalendarDay

    raw = RawPayload(source="fixture", endpoint="fixture")
    db.add(raw)
    db.flush()
    db.add(
        TradingCalendarDay(
            exchange="TWSE",
            calendar_date=D + timedelta(days=1),
            year=D.year,
            kind="closed",
            name="休市",
            source="fixture",
            collected_at=tpe(D, 0, 0),
            raw_payload_id=raw.id,
        )
    )
    db.flush()
    # Tue, (Wed closed), Thu, Fri.
    assert ai_list_reading.valid_until(db, D, 3) == D + timedelta(days=3)
    # Fri + 2 sessions: Mon.
    assert ai_list_reading.valid_until(db, D + timedelta(days=3), 2) == D + timedelta(
        days=6
    )


@linux_only
def test_a_rerun_after_done_is_already_done_and_changes_nothing(run_env):
    job(run_env, FakeCli(ok))
    (first,) = _rows(run_env.db)
    before = _frozen(first)
    picks = [_frozen(row) for row in _rows(run_env.db, AiListPick)]
    cli = FakeCli(ok)
    code, _ = job(run_env, cli, trigger="manual")
    assert code == 0 and cli.prompts == []
    assert "--- result status=skipped reason=already_done" in _log(run_env)
    (again,) = _rows(run_env.db)
    run_env.db.refresh(again)
    assert _frozen(again) == before
    assert [_frozen(row) for row in _rows(run_env.db, AiListPick)] == picks


@linux_only
@pytest.mark.parametrize(
    "first, status",
    [
        (RATE_LIMITED, "failed"),
        (replying(lambda p: answer(p, [good_pick(rank=2)])), "rejected"),
    ],
)
def test_a_rerun_after_failed_or_rejected_adds_the_next_sequence(
    run_env, first, status
):
    code, _ = job(run_env, FakeCli(first))
    assert code == 1
    (failed,) = _rows(run_env.db)
    before = _frozen(failed)
    assert failed.status == status and failed.market_method_json is None
    assert _rows(run_env.db, AiListPick) == []
    assert f"--- result status={status}" in _log(run_env)
    code, _ = job(run_env, FakeCli(ok), at="08:35")
    assert code == 0
    first_row, second = _rows(run_env.db)
    run_env.db.refresh(first_row)
    assert _frozen(first_row) == before
    assert (second.sequence, second.status) == (2, "done")
    assert [pick.reading_id for pick in _rows(run_env.db, AiListPick)] == [second.id]


def _premarket_tables(db):
    return [
        [_frozen(row) for row in _rows(db, model)]
        for model in (PremarketAiReading, PremarketAiStock, PremarketAiScore)
    ]


def _session_bars(db):
    """D's bars of the TAIEX and every stock, so premarket_score has a d0 to score."""

    for row in db.scalars(
        select(Instrument).where(Instrument.instrument_type.in_(("stock", "index")))
    ):
        last = db.scalar(
            select(MarketBar)
            .where(MarketBar.instrument_id == row.id)
            .order_by(MarketBar.trading_date.desc())
            .limit(1)
        )
        if last is None or last.trading_date != L:
            continue
        bars(db, row, [last.close + 1], days=[D], collected=tpe(D, 15, 0))
    db.commit()


@linux_only
def test_premarket_ai_rows_and_its_scores_are_unchanged_by_the_ai_list(run_env):
    """AC-3: premarket-ai's three tables and premarket_score's output, row by row."""

    code, _ = job(run_env, FakeCli(valid), module=premarket_ai)
    assert code == 0
    _session_bars(run_env.db)
    before = _premarket_tables(run_env.db)
    scores = [
        (row.scope, row.subject, row.horizon, row.outcome_json)
        for row in score_readings(run_env.db, D, now=tpe(D, 22, 0))
    ]
    assert scores  # the d0 of the market at least
    run_env.db.rollback()
    code, _ = job(run_env, FakeCli(_two_picks))
    assert code == 0 and len(_rows(run_env.db)) == 1
    assert _premarket_tables(run_env.db) == before
    after = [
        (row.scope, row.subject, row.horizon, row.outcome_json)
        for row in score_readings(run_env.db, D, now=tpe(D, 22, 0))
    ]
    assert after == scores
    run_env.db.rollback()


@linux_only
def test_the_two_jobs_have_their_own_locks_and_logs(run_env):
    from worker import job as worker_job

    lock = worker_job.FileLock(worker_job.lock_path(run_env.data, premarket_ai.LOCK))
    assert lock.acquire()
    try:
        # premarket-ai holding its lock does not hold the AI list back.
        code, _ = job(run_env, FakeCli(ok))
        assert code == 0 and "--- result status=done" in _log(run_env)
        assert worker_job.running_jobs(run_env.data) == ["premarket_ai"]
    finally:
        lock.release()
    own = worker_job.FileLock(worker_job.lock_path(run_env.data, ai_list.LOCK))
    assert own.acquire()
    try:
        assert worker_job.running_jobs(run_env.data) == ["ai_list"]
        code, _ = job(run_env, FakeCli(ok), trigger="manual")
        assert "--- result status=skipped reason=already_running" in _log(run_env)
    finally:
        own.release()
    assert not (run_env.logs / "premarket-ai-20261124.log").exists()


def _no_pending_write(db) -> bool:
    return not db.connection().connection.dbapi_connection.in_transaction


@linux_only
def test_no_write_is_open_during_the_calls(run_env):
    """A retry never holds SQLite's write lock (as premarket-ai, review 7194545794, 2)."""

    seen = []

    def watching(reply):
        def call(payload):
            seen.append(_no_pending_write(run_env.db))
            return reply(payload) if callable(reply) else reply

        return call

    code, _ = job(run_env, FakeCli(watching(BROKEN), watching(ok)))
    assert code == 0 and seen == [True, True]
    (reading,) = _rows(run_env.db)
    assert reading.attempts == 2 and reading.status == "done"
    # The raw rows came with the reading, one per call.
    ids = [attempt["raw_payload_id"] for attempt in reading.attempts_json]
    assert len(set(ids)) == 2
    assert all(run_env.db.get(RawPayload, raw_id) is not None for raw_id in ids)


@linux_only
def test_maintenance_started_during_the_call_writes_nothing(run_env):
    from worker import job as worker_job

    counts = lambda: [  # noqa: E731
        run_env.db.scalar(select(func.count(model.id)))
        for model in (AiListReading, AiListPick, IngestionRun, RawPayload)
    ]
    before = counts()

    def deploy_starts(payload):
        worker_job.maintenance_on(run_env.data, "deploy")
        return ok(payload)

    try:
        code, _ = job(run_env, FakeCli(deploy_starts))
    finally:
        worker_job.maintenance_off(run_env.data, "deploy")
    assert code == 0
    assert "--- result status=skipped reason=maintenance after_calls=yes" in _log(
        run_env
    )
    run_env.db.rollback()
    assert counts() == before


@linux_only
@pytest.mark.parametrize(
    "at, expected",
    [
        ("08:45", "status=skipped reason=too_late at=08:45"),
        ("08:20", "status=skipped reason=too_late at=08:20"),
    ],
)
def test_a_scheduled_run_outside_0821_to_0845_is_too_late(run_env, at, expected):
    cli = FakeCli(ok)
    code, _ = job(run_env, cli, at=at)
    assert code == 0 and cli.prompts == []
    assert f"--- result {expected}" in _log(run_env)
    assert _rows(run_env.db) == []


@linux_only
def test_a_dry_run_calls_once_and_writes_nothing(run_env, tmp_path):
    dump = tmp_path / "dump"
    cli = FakeCli(ok)
    code, out = job(run_env, cli, "--dry-run", "--dump", str(dump), trigger="manual")
    assert code == 0 and len(cli.prompts) == 1
    assert "--- result status=done" in out and "--- pick rank=1 symbol=2330" in out
    assert not run_env.logs.exists()
    assert _rows(run_env.db) == []
    assert run_env.db.scalar(select(func.count(IngestionRun.id))) == 0
    stored = json.loads((dump / "champion-ai_list_v1.json").read_text(encoding="utf-8"))
    assert stored["status"] == "done" and stored["checks"]["picks_passed"] == 1


@linux_only
def test_a_closed_day_is_skipped(run_env):
    args = _args(
        ai_list,
        "--now",
        "2026-11-28T08:21",
        "--trigger",
        "scheduler",
        "--log-dir",
        str(run_env.logs),
    )
    out = io.StringIO()
    ai_list._Run(args, runner=FakeCli(ok), out=out).run()
    assert "status=skipped reason=non_trading_day" in out.getvalue()
    assert _rows(run_env.db) == []


def test_day_done_reads_the_ai_list_log(tmp_path):
    path = ai_list.log_path(tmp_path, D)
    path.write_text("--- result status=failed reason=timeout\n", encoding="utf-8")
    assert not ai_list.day_done(tmp_path, D)
    with open(path, "a", encoding="utf-8") as log:
        log.write("--- result status=skipped reason=already_done session_date=x\n")
    assert ai_list.day_done(tmp_path, D)


# --- the migration ----------------------------------------------------------------------

TABLES = {"ai_list_readings", "ai_list_picks"}
INDEXES = {
    "ix_ai_list_readings_session_date",
    "ix_ai_list_picks_reading_id",
    "ix_ai_list_picks_session_date",
    "ix_ai_list_picks_instrument_id",
}


def test_the_migration_adds_only_the_two_tables_and_goes_down_and_up(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from sqlalchemy import create_engine
    from test_premarket_ai import _alembic_config, _schema

    from app.migration_revisions import REVISIONS

    revision = "0051_ai_list"
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'down.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = _alembic_config(engine)
    try:
        command.upgrade(config, revision)
        with Session(engine) as session:
            row = Instrument(exchange="TWSE", symbol="2330", name="台積電")
            session.add(row)
            session.flush()
            reading = AiListReading(
                session_date=D,
                list_date=L,
                role="champion",
                sequence=1,
                trigger="manual",
                prompt_version="ai_list_v1",
                prompt_sha256="a" * 64,
                schema_sha256="b" * 64,
                model_alias="sonnet",
                pool_phase="interim",
                cutoff_at=tpe(D, 8, 15),
                input_hash="c" * 64,
                input_json={"candidates": []},
                status="done",
                checks_json={},
                attempts=1,
                attempts_json=[],
                duration_ms=1000,
                usage_json={},
                started_at=tpe(D, 8, 21),
                finished_at=tpe(D, 8, 22),
            )
            session.add(reading)
            session.flush()
            session.add(
                AiListPick(
                    reading_id=reading.id,
                    session_date=D,
                    prompt_version="ai_list_v1",
                    role="champion",
                    rank=1,
                    instrument_id=row.id,
                    symbol="2330",
                    pool_sources_json=["watchlist"],
                    on_rule_list=False,
                    setup="breakout",
                    basis_json=["technical"],
                    basis_primary="technical",
                    confidence="low",
                    levels_json={},
                    levels_check_json={},
                    valid_sessions=1,
                    exit_conditions_json=[],
                    reasons_json=[],
                )
            )
            session.commit()
        names, indexes, version, fk = _schema(engine)
        assert TABLES <= names and INDEXES <= indexes
        assert version == [(revision,)] and fk == []

        command.downgrade(config, previous)
        down, down_indexes, version, fk = _schema(engine)
        assert not TABLES & down and not INDEXES & down_indexes
        assert version == [(previous,)] and fk == []

        # Up again: the two tables and their indexes, nothing else.
        command.upgrade(config, revision)
        names, indexes, version, fk = _schema(engine)
        named = {
            name for name in indexes - down_indexes if not name.startswith("sqlite_")
        }
        assert names - down == TABLES and named == INDEXES
        assert down <= names and version == [(revision,)] and fk == []
    finally:
        engine.dispose()
