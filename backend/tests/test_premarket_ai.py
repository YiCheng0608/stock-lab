"""The pre-market AI reading (#1041): input snapshot, checks, retries and stored rows.

Day D is Tuesday 2026-11-24, its list date Monday 2026-11-23; the cutoff is D 08:15
Taipei. No test calls the real CLI: ``FakeCli`` answers with made-up envelopes. The
job runs take fcntl locks: Linux only, like worker.job.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import socket
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE_READ_VERSIONS, US_INDEX_EXCHANGE, US_INDEXES
from app.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidateRun,
    ChipSnapshot,
    DailyCandidate,
    FuturesNightBar,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    NewsLlmResult,
    PremarketAiReading,
    PremarketAiStock,
    RawPayload,
    Signal,
    ThemeGroup,
)
from worker import premarket_ai, premarket_input, premarket_reading, sources
from worker.news_llm import CliResult

ON_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(not ON_LINUX, reason="fcntl lock: Linux only (#333)")

D = date(2026, 11, 24)
L = date(2026, 11, 23)
TPE = timedelta(hours=8)
MODEL = "claude-sonnet-5-5"


def tpe(day: date, hour: int, minute: int, second: int = 0) -> datetime:
    """The UTC-naive instant of a Taipei time (as stored)."""

    return datetime(day.year, day.month, day.day, hour, minute, second) - TPE


def weekdays(end: date, count: int) -> list[date]:
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


DAYS = weekdays(L, 25)


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in premarket AI tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session
    engine.dispose()


# --- fixture data ---------------------------------------------------------------------


def instrument(db, symbol, *, exchange="TWSE", kind="stock", watch=False, name=None):
    row = Instrument(
        exchange=exchange,
        symbol=symbol,
        name=name or f"名{symbol}",
        instrument_type=kind,
        status="active",
        is_watchlisted=watch,
    )
    db.add(row)
    db.flush()
    return row


def bars(db, row, closes, days=DAYS, collected=None, **extra):
    for day, close in zip(days, closes):
        db.add(
            MarketBar(
                instrument_id=row.id,
                trading_date=day,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                adj_close=close,
                volume=2_000_000,
                turnover=close * 2_000_000,
                source="fixture-bars",
                collected_at=collected or tpe(day, 15, 0),
                **extra,
            )
        )
    db.flush()


def stock(db, symbol, **kwargs):
    row = instrument(db, symbol, **kwargs)
    bars(db, row, [100.0 + index for index in range(len(DAYS))])
    for day in DAYS[-5:]:
        db.add(
            ChipSnapshot(
                instrument_id=row.id,
                trading_date=day,
                foreign_buy=10_000,
                trust_buy=2_000,
                dealer_buy=0,
                margin_change=5,
                source="fixture-chips",
            )
        )
    db.flush()
    return row


def news(db, symbols, published, *, collected=None, ai=None, title=None, key=None):
    item = NewsItem(
        canonical_key=key or f"k-{len(symbols)}-{published.isoformat()}-{title}",
        source_name="fixture-media",
        source_kind="media",
        title=title or f"新聞 {','.join(symbols)}",
        time_precision="datetime",
        time_basis="published",
        display_time=published,
        published_at=published,
        collected_at=collected or published + timedelta(minutes=2),
        symbols_json=list(symbols),
    )
    db.add(item)
    db.flush()
    if ai is not None:
        scope, direction, run_at = ai
        db.add(
            NewsLlmResult(
                news_item_id=item.id,
                prompt_version="news_v4",
                llm_model=MODEL,
                llm_input_hash="x" * 64,
                llm_run_at=run_at,
                llm_status="done",
                ai_summary=f"摘要 {item.title}",
                ai_impact_direction=direction,
                ai_impact_scope=scope,
                ai_unsupported=False,
            )
        )
        db.flush()
    return item


def raw(db):
    row = RawPayload(source="fixture", endpoint="fixture")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def world(db):
    """The DB of D: a two-stock today list, a rule signal, H2-less, a watchlist stock,
    a busy news stock, the indexes and the night."""

    taiex = instrument(db, "TAIEX", kind="index", name="加權指數")
    bars(db, taiex, [27000.0 + index * 10 for index in range(len(DAYS))])
    tx = instrument(db, "TX", exchange="TAIFEX", kind="futures", name="台指期")
    bars(
        db,
        tx,
        [27010.0 + index * 10 for index in range(len(DAYS))],
        contract_month="202612",
    )
    us_days = weekdays(L, 3)
    for series in US_INDEXES:
        index = instrument(db, series.symbol, exchange=US_INDEX_EXCHANGE, kind="index")
        # The US session of 11-23 is collected at 07:31 on D, before the cutoff ...
        bars(db, index, [5000.0, 5010.0, 5050.0], days=us_days, collected=tpe(L, 7, 31))
        db.get(MarketBar, db.scalar(select(func.max(MarketBar.id)))).collected_at = tpe(
            D, 7, 31
        )
    # ... but SOX's 11-23 close only at 08:31, after it: the snapshot has its 11-20.
    sox = db.scalar(select(Instrument).where(Instrument.symbol == "SOX"))
    db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == sox.id, MarketBar.trading_date == L
        )
    ).collected_at = tpe(D, 8, 31)
    db.add(
        FuturesNightBar(
            symbol="TX",
            trading_date=D,
            contract_month="202612",
            open=27200.0,
            high=27400.0,
            low=27150.0,
            close=27350.0,
            change=100.0,
            volume=45678,
            source="taifex_futdatadown",
            data_as_of=datetime(2026, 11, 24),
            # The 08:15 night job writes it seconds after the cutoff.
            collected_at=tpe(D, 8, 15, 20),
            raw_payload_id=raw(db).id,
        )
    )
    listed = [stock(db, "2330"), stock(db, "2412")]
    signalled = stock(db, "1101")
    watched = stock(db, "2603", watch=True)
    busy = stock(db, "3711")
    group = ThemeGroup(id="theme:cowos", name="CoWoS", group_type="theme", active=True)
    db.add(group)
    db.flush()
    db.add(
        GroupMembership(
            group_id=group.id,
            instrument_id=listed[0].id,
            role="member",
            valid_from=DAYS[0],
        )
    )
    run = CandidateRun(
        trading_date=L,
        score_version=CANDIDATE_SCORE_READ_VERSIONS[0],
        computed_at=tpe(L, 21, 40),
        candidate_count=2,
    )
    db.add(run)
    db.flush()
    for rank, row in enumerate(listed, start=1):
        signal = Signal(
            signal_key=f"analysis-{row.symbol}-{L}",
            signal_date=L,
            instrument_id=row.id,
            status="active",
            entry_type="breakout",
            breakout_price=125.0,
            invalid_price=118.0,
            target_1=135.0,
            target_2=140.0,
            earliest_execution_date=D,
        )
        db.add(signal)
        db.flush()
        db.add(
            DailyCandidate(
                candidate_run_id=run.id,
                trading_date=L,
                instrument_id=row.id,
                signal_id=signal.id,
                strategy="breakout_v3",
                score_version=run.score_version,
                total_score=80.0 - rank,
                weight_coverage=1.0,
                rank=rank,
                data_as_of=L,
            )
        )
    db.add(
        Signal(
            signal_key=f"analysis-1101-{L}",
            signal_date=L,
            instrument_id=signalled.id,
            status="conditional",
            entry_type="pullback",
            pullback_low=110.0,
            pullback_high=115.0,
            invalid_price=108.0,
        )
    )
    items = {
        # Overnight, linked to 2330, judged by the cutoff.
        "listed": news(
            db, ["2330"], tpe(L, 20, 0), ai=("instrument", "positive", tpe(L, 20, 10))
        ),
        # A market item judged by the cutoff.
        "market": news(
            db, [], tpe(D, 7, 0), ai=("market", "negative", tpe(D, 7, 5)), title="美股"
        ),
        # Judged only after the cutoff: in, but not judged.
        "late_ai": news(
            db, ["2412"], tpe(D, 7, 10), ai=("market", "positive", tpe(D, 8, 17))
        ),
        # Published after the cutoff; collected after it; before the window.
        "after": news(db, ["2330"], tpe(D, 8, 20), title="盤前"),
        "late_collect": news(
            db, ["2330"], tpe(D, 8, 0), collected=tpe(D, 8, 16), title="晚收"
        ),
        "before_window": news(db, ["2330"], tpe(L, 12, 0), title="盤中"),
        # Two items of 3711: it enters as a busy news stock.
        "busy_1": news(db, ["3711"], tpe(L, 22, 0), title="日月光一"),
        "busy_2": news(db, ["TWSE:3711"], tpe(D, 6, 0), title="日月光二"),
    }
    db.commit()
    return argparse.Namespace(
        listed=listed,
        signalled=signalled,
        watched=watched,
        busy=busy,
        items=items,
        run=run,
    )


def snapshot(db, assembled=None):
    return premarket_input.build(db, D, L, assembled or tpe(D, 8, 21))


# --- fake CLI answers -----------------------------------------------------------------


def answer(payload, *, actions=None, **change):
    """A valid answer to PAYLOAD: keep for every stock, a market reason citing news."""

    news_id = payload["market_news"][0]["id"] if payload["market_news"] else None
    out = {
        "market": {
            "stance": "neutral",
            "confidence": "medium",
            "reasons": [
                {
                    "text": "根據美股與夜盤，推論大盤開盤持平。",
                    "refs": [f"news:{news_id}", "tx:night"]
                    if news_id
                    else ["tx:night"],
                }
            ],
        },
        "sectors": [],
        "candidates": [
            {
                "symbol": item["symbol"],
                "action": (actions or {}).get(item["symbol"], "keep"),
                "reprice_rule": None,
                "reasons": [{"text": "根據籌碼，推論維持。", "refs": []}],
            }
            for item in payload["candidates"]
        ],
        "data_gaps": [],
    }
    for item in out["candidates"]:
        if item["action"] == "reprice":
            item["reprice_rule"] = {
                "max_gap_pct": 0.05,
                "max_gap_down_pct": 0.03,
                "min_risk_reward": 1.2,
            }
    out.update(change)
    return out


def envelope(output) -> CliResult:
    return CliResult(
        0,
        json.dumps(
            {
                "type": "result",
                "is_error": False,
                "result": "",
                "structured_output": output,
                "modelUsage": {
                    MODEL: {
                        "inputTokens": 100,
                        "outputTokens": 50,
                        "cacheReadInputTokens": 1000,
                        "cacheCreationInputTokens": 10,
                    }
                },
            }
        ),
        "",
    )


TIMEOUT = CliResult(None, "", "", timed_out=True)
BROKEN = CliResult(0, "not json", "")
RATE_LIMITED = CliResult(
    1, json.dumps({"is_error": True, "result": "Claude AI usage limit reached"}), ""
)
NOT_LOGGED_IN = CliResult(
    1, json.dumps({"is_error": True, "result": "Not logged in · Please run /login"}), ""
)


class FakeCli:
    """Answers in turn: a CliResult, or a callable of the input payload."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.argv: list[list[str]] = []

    def __call__(self, prompt, argv):
        self.prompts.append(prompt)
        self.argv.append(list(argv))
        payload = json.loads(prompt.split("<input>\n", 1)[1].rsplit("\n</input>", 1)[0])
        reply = self.answers.pop(0)
        return reply(payload) if callable(reply) else reply


def valid(payload):
    return envelope(answer(payload))


def read(db, cli, **kwargs):
    shot = snapshot(db)
    return shot, premarket_reading.read(
        shot, premarket_reading.PROMPT_VERSION, "champion", ["claude"], cli, **kwargs
    )


# --- AC-1: the input snapshot ---------------------------------------------------------


def test_the_snapshot_has_only_what_was_there_by_0815(db, world):
    payload = snapshot(db).payload
    assert payload["cutoff_taipei"] == "2026-11-24 08:15"
    assert (
        payload["session_date"] == "2026-11-24" and payload["list_date"] == "2026-11-23"
    )
    ids = premarket_reading.payload_news_ids(payload)
    items = world.items
    assert {items["listed"].id, items["market"].id, items["late_ai"].id} <= ids
    assert (
        not {
            items["after"].id,
            items["late_collect"].id,
            items["before_window"].id,
        }
        & ids
    )
    # An item judged after the cutoff is in, without the later reading.
    late = next(
        entry
        for stock_item in payload["candidates"]
        for entry in stock_item["news"]
        if entry["id"] == items["late_ai"].id
    )
    assert late["ai"] == "not_judged_by_cutoff" and "ai_direction" not in late
    assert [entry["id"] for entry in payload["market_news"]] == [items["market"].id]
    assert payload["overnight_news_stats"]["total"] == 5
    assert payload["overnight_news_stats"]["not_judged_by_cutoff"] == 3
    # The index values: SOX's 11-23 close came at 08:31, so 11-20's is read.
    us = payload["us_indices"]
    assert us["expected_date"] == "2026-11-23"
    assert us["SPX"]["trading_date"] == "2026-11-23" and us["SPX"]["close"] == 5050.0
    assert (
        us["SOX"]["trading_date"] == "2026-11-20" and us["SOX"]["freshness"] == "stale"
    )
    assert payload["taiex"]["date"] == "2026-11-23"
    assert payload["taiex"]["close"] == 27000.0 + 10 * (len(DAYS) - 1)
    night = payload["tx_futures"]["night"]
    assert night["date"] == "2026-11-24" and night["close"] == 27350.0
    assert night["change_pct"] == round(27350.0 / 27250.0 - 1, 4)
    assert payload["tx_futures"]["day"]["contract_month"] == "202612"


def test_the_night_is_missing_when_it_was_not_collected_by_the_snapshot(db, world):
    payload = snapshot(db, assembled=tpe(D, 8, 15, 10)).payload
    assert payload["tx_futures"]["night"] == {
        "status": "missing",
        "expected_date": "2026-11-24",
    }


def test_only_today_list_stocks_carry_rule_levels(db, world):
    shot = snapshot(db)
    by_symbol = {item["symbol"]: item for item in shot.payload["candidates"]}
    assert list(by_symbol) == ["2330", "2412", "1101", "2603", "3711"]
    for symbol in ("2330", "2412"):
        levels = by_symbol[symbol]["strategy_levels"]
        assert by_symbol[symbol]["on_today_list"] is True
        assert levels["entry"] == 125.0 and levels["invalid_price"] == 118.0
        assert levels["target_1"] == 135.0 and levels["risk_reward"] == round(10 / 7, 4)
    for symbol in ("1101", "2603", "3711"):
        assert by_symbol[symbol]["on_today_list"] is False
        assert "strategy_levels" not in by_symbol[symbol]
        assert set(by_symbol[symbol]) == {
            "symbol",
            "exchange",
            "name",
            "pool_sources",
            "on_today_list",
            "price",
            "chips",
            "groups",
            "news",
        }
    # A today-list stock is also among the rule signals: both sources, the list first.
    assert by_symbol["2330"]["pool_sources"] == [
        "today_list#1",
        "rule_signal:breakout:active",
    ]
    assert by_symbol["1101"]["pool_sources"] == ["rule_signal:pullback:conditional"]
    assert by_symbol["2603"]["pool_sources"] == ["watchlist"]
    assert by_symbol["3711"]["pool_sources"] == ["overnight_news:2"]
    assert by_symbol["2330"]["groups"] == [
        {"group_id": "theme:cowos", "name": "CoWoS", "type": "theme"}
    ]
    assert shot.payload["groups"] == {"theme:cowos": "CoWoS"}
    assert "extra_universe" not in shot.payload
    meta = {item.symbol: item for item in shot.stocks}
    assert meta["2330"].levels["entry"] == 125.0 and meta["1101"].levels is None
    # Prices and volume are for every stock: only the rule levels are left out.
    assert by_symbol["2603"]["price"]["date"] == "2026-11-23"
    assert by_symbol["2603"]["chips"]["foreign_net_lots_5d"] == 50


def test_the_interim_pool_is_capped_and_named(db, world, monkeypatch):
    monkeypatch.setattr(premarket_input, "POOL_CAP", 3)
    shot = snapshot(db)
    assert [item["symbol"] for item in shot.payload["candidates"]] == [
        "2330",
        "2412",
        "1101",
    ]
    assert shot.pool_phase == "interim" and shot.payload["pool"]["phase"] == "interim"
    assert shot.payload["pool"]["today_list_count"] == 2


def pool_run(db, phase, items, *, computed, base=None):
    """A candidate_pool_v1 run of L: ITEMS are (instrument, selected, sources)."""

    run = CandidatePoolRun(
        trading_date=L,
        version="candidate_pool_v1",
        phase=phase,
        status="computed",
        cap=40 if phase == "evening" else 10,
        computed_at=computed,
        base_run_id=base.id if base is not None else None,
    )
    db.add(run)
    db.flush()
    rank = 0
    for row, selected, names in items:
        rank += selected
        db.add(
            CandidatePoolItem(
                run_id=run.id,
                trading_date=L,
                version=run.version,
                phase=phase,
                instrument_id=row.id,
                rank=rank if selected else None,
                tier=2,
                selected=selected,
                reject_reason=None if selected else "cap",
                source_count=len(names),
                sources_json=[
                    {
                        "source": source,
                        "value": {"n": 1},
                        "data_date": str(L),
                        "source_ids": ["x:1"],
                    }
                    for source in names
                ],
            )
        )
    db.commit()
    return run


@pytest.fixture
def evening(db, world):
    return pool_run(
        db,
        "evening",
        [
            (world.listed[1], True, ["rule_signal"]),
            (world.listed[0], True, ["rule_signal", "hot_theme"]),
            (world.watched, False, ["watchlist"]),
        ],
        computed=tpe(L, 21, 50),
    )


def test_the_pool_is_evening_and_morning_once_the_morning_round_is_written(
    db, world, evening
):
    morning = pool_run(
        db,
        "morning",
        [(world.busy, True, ["morning_news"])],
        computed=tpe(D, 8, 20, 30),
        base=evening,
    )
    shot = snapshot(db)
    assert shot.pool_phase == "morning"
    assert [item["symbol"] for item in shot.payload["candidates"]] == [
        "2412",
        "2330",
        "3711",
    ]
    pool = shot.payload["pool"]
    assert pool["phase"] == "morning" and "fallback" not in pool
    assert (pool["evening_run_id"], pool["morning_run_id"]) == (evening.id, morning.id)
    assert shot.payload["candidates"][1]["pool_sources"] == [
        {"source": "rule_signal", "value": {"n": 1}, "data_date": "2026-11-23"},
        {"source": "hot_theme", "value": {"n": 1}, "data_date": "2026-11-23"},
    ]
    item_ids = {
        row.instrument_id: row.id for row in db.scalars(select(CandidatePoolItem))
    }
    meta = {item.symbol: item for item in shot.stocks}
    assert meta["3711"].pool_item_id == item_ids[world.busy.id]
    # The rule levels are still the today list's only.
    assert "strategy_levels" in shot.payload["candidates"][0]
    assert "strategy_levels" not in shot.payload["candidates"][2]
    reading = premarket_reading.store(
        db,
        shot,
        premarket_reading.read(
            shot, "premarket_v1", "champion", ["claude"], FakeCli(valid)
        ),
        trigger="manual",
        ingestion_run_id=None,
    )
    assert reading.pool_phase == "morning"
    stored = {row.symbol: row for row in db.scalars(select(PremarketAiStock))}
    assert stored["3711"].pool_item_id == item_ids[world.busy.id]
    assert stored["3711"].pool_sources_json[0]["source"] == "morning_news"


@pytest.mark.parametrize("morning_at", [None, tpe(D, 8, 22)])
def test_without_the_morning_round_by_then_the_pool_is_the_evening_round(
    db, world, evening, morning_at
):
    """08:20's preopen may still be waiting for news at 08:21: no wait, the evening."""

    if morning_at is not None:
        pool_run(
            db,
            "morning",
            [(world.busy, True, ["morning_news"])],
            computed=morning_at,
            base=evening,
        )
    shot = snapshot(db)
    assert (
        shot.pool_phase == "evening" and shot.payload["pool"]["morning_run_id"] is None
    )
    assert [item["symbol"] for item in shot.payload["candidates"]] == ["2412", "2330"]


def test_without_an_evening_round_the_stand_in_pool_is_read_and_marked(db, world):
    # An evening round computed only after the snapshot does not count either.
    pool_run(
        db, "evening", [(world.listed[0], True, ["rule_signal"])], computed=tpe(D, 9, 0)
    )
    shot = snapshot(db)
    assert shot.pool_phase == "interim"
    assert shot.payload["pool"]["fallback"] == "no_candidate_pool_evening"
    assert [item["symbol"] for item in shot.payload["candidates"]] == [
        "2330",
        "2412",
        "1101",
        "2603",
        "3711",
    ]
    assert all(item.pool_item_id is None for item in shot.stocks)


def test_a_done_reading_records_version_hash_model_and_duration(db, world):
    cli = FakeCli(valid)
    shot, outcome = read(db, cli)
    assert outcome.status == "done" and outcome.reason is None
    reading = premarket_reading.store(
        db, shot, outcome, trigger="scheduler", ingestion_run_id=None
    )
    db.commit()
    assert reading.prompt_version == "premarket_v1"
    assert reading.prompt_sha256 == premarket_reading.PROMPTS["premarket_v1"]
    assert reading.schema_sha256 == premarket_reading.SCHEMA_SHA256
    assert reading.model_alias == "sonnet" and reading.llm_model == MODEL
    assert reading.duration_ms >= 0 and reading.attempts == 1
    assert reading.usage_json["output_tokens"] == 50
    assert reading.pool_phase == "interim"
    assert reading.cutoff_at == tpe(D, 8, 15)
    assert reading.input_hash == shot.hash and reading.input_json == shot.payload
    assert (
        "--model" in cli.argv[0]
        and cli.argv[0][cli.argv[0].index("--model") + 1] == "sonnet"
    )
    rows = db.scalars(
        select(PremarketAiStock).order_by(PremarketAiStock.position)
    ).all()
    assert [row.symbol for row in rows] == ["2330", "2412", "1101", "2603", "3711"]
    assert rows[0].on_today_list and rows[0].levels_json["entry"] == 125.0
    assert rows[0].daily_candidate_id is not None
    assert rows[2].levels_json is None and rows[2].daily_candidate_id is None
    assert {row.action for row in rows} == {"keep"}


def test_the_prompt_and_schema_are_pinned():
    text = premarket_reading.prompt_text("premarket_v1")
    assert (
        hashlib.sha256(text.encode("utf-8")).hexdigest()
        == (premarket_reading.PROMPTS["premarket_v1"])
    )
    # Changing the output schema needs a new prompt version too.
    assert premarket_reading.SCHEMA_SHA256 == (
        "4d694082ef7deda8da4b09bdef316bb674e444c7a769310f6824687faf00811d"
    )
    assert "additions" not in premarket_reading.OUTPUT_SCHEMA["properties"]
    assert set(premarket_reading.REPRICE_KEYS) == {
        "max_gap_pct",
        "max_gap_down_pct",
        "min_risk_reward",
    }


def test_an_edited_prompt_without_a_new_version_is_not_called(db, world, monkeypatch):
    monkeypatch.setitem(premarket_reading.PROMPTS, "premarket_v1", "0" * 64)
    cli = FakeCli(valid)
    _shot, outcome = read(db, cli)
    assert outcome.status == "failed" and outcome.reason == "prompt_hash_mismatch"
    assert cli.prompts == []


# --- AC-2: checks and retries ---------------------------------------------------------


def _drop_first(payload):
    output = answer(payload)
    output["candidates"] = output["candidates"][1:]
    return envelope(output)


def _extra(payload):
    output = answer(payload)
    output["candidates"].append(
        {
            "symbol": "9999",
            "action": "keep",
            "reprice_rule": None,
            "reasons": [{"text": "x", "refs": []}],
        }
    )
    return envelope(output)


def _duplicate(payload):
    output = answer(payload)
    output["candidates"].append(dict(output["candidates"][0]))
    return envelope(output)


def _unknown_news(payload):
    output = answer(payload)
    output["candidates"][0]["reasons"][0]["refs"] = ["news:999999"]
    return envelope(output)


def _order_words(payload):
    output = answer(payload)
    output["candidates"][0]["reasons"][0]["text"] = (
        "根據突破，推論今日可進場（條件：開盤 ≥125）。"
    )
    return envelope(output)


def _additions(payload):
    output = answer(payload)
    output["additions"] = [{"symbol": "6274", "reasons": []}]
    return envelope(output)


def _reprice_off_list(payload):
    return envelope(answer(payload, actions={"1101": "reprice"}))


def _bad_schema(payload):
    output = answer(payload)
    output["market"]["stance"] = "very_bullish"
    return envelope(output)


@pytest.mark.parametrize(
    "reply, reason, detail",
    [
        (_drop_first, "coverage", '"missing": ["2330"]'),
        (_extra, "coverage", '"extra": ["9999"]'),
        (_duplicate, "coverage", '"duplicate": ["2330"]'),
        (_unknown_news, "unknown_news_ref", "news:999999"),
        (_order_words, "directive_words", "可進場"),
        (_additions, "additions_present", "additions"),
        (_reprice_off_list, "reprice_without_levels", "1101"),
    ],
)
def test_a_failed_content_check_is_rejected_without_a_retry(
    db, world, reply, reason, detail
):
    cli = FakeCli(reply, valid)
    shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("rejected", reason)
    assert detail in outcome.error
    assert len(cli.prompts) == 1 and len(outcome.attempts) == 1
    reading = premarket_reading.store(
        db, shot, outcome, trigger="manual", ingestion_run_id=None
    )
    db.commit()
    assert reading.status == "rejected" and reading.reason == reason
    assert reading.output_json is not None
    # A rejected reading has no stock rows.
    assert db.scalar(select(func.count(PremarketAiStock.id))) == 0


def _reprice_without_rule(payload):
    output = answer(payload, actions={"2330": "reprice"})
    output["candidates"][0]["reprice_rule"] = None
    return envelope(output)


def _keep_with_rule(payload):
    output = answer(payload)
    output["candidates"][0]["reprice_rule"] = {
        "max_gap_pct": 0.05,
        "max_gap_down_pct": 0.03,
        "min_risk_reward": 1.2,
    }
    return envelope(output)


def _rule_left_out(payload):
    output = answer(payload, actions={"2330": "reprice"})
    del output["candidates"][0]["reprice_rule"]
    return envelope(output)


@pytest.mark.parametrize(
    "reply, detail",
    [
        (_reprice_without_rule, "reprice_rule must be an object for reprice"),
        (_keep_with_rule, "reprice_rule must be an object for reprice"),
        # The AC-4 run's answer: every reprice without the (then optional) rule.
        (_rule_left_out, "missing ['reprice_rule']"),
    ],
)
def test_reprice_rule_is_an_object_for_reprice_and_null_otherwise(
    db, world, reply, detail
):
    cli = FakeCli(reply, reply)
    _shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("rejected", "schema")
    assert detail in outcome.error and len(cli.prompts) == 2


def test_a_reprice_rule_is_stored_on_its_stock_row(db, world):
    cli = FakeCli(
        lambda payload: envelope(answer(payload, actions={"2330": "reprice"}))
    )
    shot, outcome = read(db, cli)
    assert outcome.status == "done"
    premarket_reading.store(db, shot, outcome, trigger="manual", ingestion_run_id=None)
    rows = {row.symbol: row for row in db.scalars(select(PremarketAiStock))}
    assert rows["2330"].action == "reprice"
    assert rows["2330"].reprice_rule_json == {
        "max_gap_pct": 0.05,
        "max_gap_down_pct": 0.03,
        "min_risk_reward": 1.2,
    }
    assert rows["2412"].reprice_rule_json is None


@pytest.mark.parametrize("ref", ["news: 123", "news:1,2", "news:abc"])
def test_a_malformed_news_ref_is_rejected(db, world, ref):
    def reply(payload):
        output = answer(payload)
        output["candidates"][0]["reasons"][0]["refs"] = [ref]
        return envelope(output)

    _shot, outcome = read(db, FakeCli(reply))
    assert (outcome.status, outcome.reason) == ("rejected", "unknown_news_ref")
    assert ref in outcome.error


def test_a_today_list_stock_without_levels_cannot_be_repriced(db, world):
    shot = snapshot(db)
    payload = json.loads(json.dumps(shot.payload))
    payload["candidates"][0]["strategy_levels"] = {"status": "no_levels"}
    output = answer(payload, actions={"2330": "reprice"})
    checked = premarket_reading.check(output, payload)
    assert checked.reason == "reprice_without_levels" and checked.detail == "2330"


def test_a_schema_mismatch_is_retried_once_then_rejected(db, world):
    cli = FakeCli(_bad_schema, _bad_schema, valid)
    _shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("rejected", "schema")
    assert "market.stance" in outcome.error
    assert [attempt["reason"] for attempt in outcome.attempts] == ["schema", "schema"]


@pytest.mark.parametrize("first", [TIMEOUT, BROKEN])
def test_a_timeout_or_a_broken_answer_is_retried_once(db, world, first):
    cli = FakeCli(first, valid)
    _shot, outcome = read(db, cli)
    assert outcome.status == "done" and len(outcome.attempts) == 2
    assert outcome.attempts[0]["reason"] in ("timeout", "invalid_json")
    assert outcome.attempts[1]["reason"] is None
    assert outcome.usage["output_tokens"] == 50


def test_two_broken_answers_fail(db, world):
    cli = FakeCli(BROKEN, TIMEOUT, valid)
    _shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("failed", "timeout")
    assert len(cli.prompts) == 2


@pytest.mark.parametrize(
    "reply, reason", [(RATE_LIMITED, "rate_limited"), (NOT_LOGGED_IN, "not_logged_in")]
)
def test_rate_limited_and_not_logged_in_are_not_retried(db, world, reply, reason):
    cli = FakeCli(reply, valid)
    shot, outcome = read(db, cli)
    assert (outcome.status, outcome.reason) == ("failed", reason)
    assert len(cli.prompts) == 1
    reading = premarket_reading.store(
        db, shot, outcome, trigger="manual", ingestion_run_id=None
    )
    assert (
        reading.status == "failed"
        and reading.llm_model is None
        and reading.attempts == 1
    )


def test_no_retry_starts_without_the_time_for_it(db, world):
    now = [0.0]

    def clock():
        return now[0]

    def slow_timeout(_payload):
        now[0] += 400.0
        return TIMEOUT

    cli = FakeCli(slow_timeout, valid)
    _shot, outcome = read(db, cli, deadline=600.0, clock=clock)
    assert (outcome.status, outcome.reason) == ("failed", "timeout")
    assert outcome.checks["retry_skipped"] == "no_time" and len(cli.prompts) == 1


@pytest.mark.parametrize(
    "text",
    [
        "根據瑞銀初評買進，推論市場關注度上升。",
        "根據券商調升至買進評等，推論偏正。",
        "根據收盤低於進場區，推論暫緩。",
        "根據外資賣出 3,000 張，推論籌碼轉弱。",
        "根據法人連三日買進，推論籌碼偏多。",
        "規則價位以開盤價重算後，報酬風險比低於 1.2 時暫緩。",
        # One-character prefixes that end a word (#1051 review 7194545794, 3).
        "根據外資率先買進記憶體股的新聞，推論族群偏多。",
        "根據法人首先賣出權值股，推論賣壓集中。",
        "根據資金搶先買進題材股，推論短線過熱。",
        "根據投信優先買進高殖利率股，推論防禦偏好。",
        "根據外資與投信分別買進與賣出，推論籌碼分歧。",
        "根據市場反應賣出壓力，推論開盤偏弱。",
        "根據業者因應賣出潮調整報價，推論影響有限。",
    ],
)
def test_rating_quotes_nouns_and_flows_are_not_orders(text):
    assert premarket_reading.directive_words([text]) == []


@pytest.mark.parametrize(
    "text",
    [
        "推論今日可進場。",
        "建議買進。",
        "今日暫不進場，觀察開盤。",
        "持有者可出場。",
        "可於開盤掛單。",
        "推論宜逢低買進。",
    ],
)
def test_order_wordings_are_found(text):
    assert premarket_reading.directive_words([text])


# --- AC-3: append only, reruns and the shadow -----------------------------------------


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

    monkeypatch.setattr(premarket_ai, "_session", session)
    return argparse.Namespace(data=data, logs=data / "logs", db=db, world=world)


def _args(*argv):
    parser = argparse.ArgumentParser()
    premarket_ai.add_arguments(parser)
    return parser.parse_args(list(argv))


def job(env, cli, *extra, at="08:21", trigger="scheduler"):
    args = _args(
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
    code = premarket_ai._Run(args, runner=cli, out=out).run()
    return code, out.getvalue()


def _log(env) -> str:
    return (env.logs / "premarket-ai-20261124.log").read_text(encoding="utf-8")


def _rows(db):
    return db.scalars(select(PremarketAiReading).order_by(PremarketAiReading.id)).all()


def _frozen(row):
    return {
        column.key: getattr(row, column.key)
        for column in inspect(PremarketAiReading).mapper.column_attrs
    }


@linux_only
def test_the_scheduled_run_stores_one_reading_and_logs_it(run_env):
    code, out = job(run_env, FakeCli(valid))
    assert code == 0
    log = _log(run_env)
    assert "start job=premarket-ai trigger=scheduler" in log
    assert (
        "--- input session_date=2026-11-24 list_date=2026-11-23 pool_phase=interim"
        in log
    )
    assert "--- result status=done session_date=2026-11-24" in log
    assert "prompt_version=premarket_v1 model=claude-sonnet-5-5 attempts=1" in log
    assert "output_tokens=50" in log and "actions=keep:5,reprice:0,defer:0" in log
    assert log.rstrip().splitlines()[-1].startswith("===== ") and "end exit=0" in log
    (reading,) = _rows(run_env.db)
    assert reading.status == "done" and reading.sequence == 1
    assert reading.trigger == "scheduler" and reading.role == "champion"
    run = run_env.db.get(IngestionRun, reading.ingestion_run_id)
    assert run.run_type == "premarket_ai" and run.status == "success"
    raw_id = reading.attempts_json[0]["raw_payload_id"]
    assert run_env.db.get(RawPayload, raw_id).source == "premarket_ai"
    assert premarket_ai.day_done(run_env.logs, D)


@linux_only
def test_a_running_reading_is_among_the_running_jobs(tmp_path):
    """Maintenance (MaintenanceHold, status, a deploy) sees a reading in progress."""

    from worker import job as worker_job

    lock = worker_job.FileLock(worker_job.lock_path(tmp_path, premarket_ai.LOCK))
    assert lock.acquire()
    try:
        assert worker_job.running_jobs(tmp_path) == ["premarket_ai"]
    finally:
        lock.release()
    assert worker_job.running_jobs(tmp_path) == []


def _no_pending_write(db) -> bool:
    return not db.connection().connection.dbapi_connection.in_transaction


@linux_only
def test_no_write_is_open_during_the_calls(run_env, monkeypatch, tmp_path):
    """A retry or a shadow call never holds SQLite's write lock (review 7194545794, 2)."""

    prompts = tmp_path / "prompts"
    prompts.mkdir()
    text = premarket_reading.prompt_text("premarket_v1")
    (prompts / "premarket_v1.md").write_text(text, encoding="utf-8")
    (prompts / "premarket_v1_test.md").write_text(text + "\n", encoding="utf-8")
    monkeypatch.setattr(premarket_reading, "PROMPT_DIR", prompts)
    monkeypatch.setitem(
        premarket_reading.PROMPTS,
        "premarket_v1_test",
        hashlib.sha256((text + "\n").encode("utf-8")).hexdigest(),
    )
    monkeypatch.setattr(premarket_reading, "SHADOW_PROMPT_VERSION", "premarket_v1_test")
    seen = []

    def watching(reply):
        def call(payload):
            seen.append(_no_pending_write(run_env.db))
            return reply(payload) if callable(reply) else reply

        return call

    code, _ = job(run_env, FakeCli(watching(BROKEN), watching(valid), watching(valid)))
    assert code == 0 and seen == [True, True, True]
    champion, shadow = _rows(run_env.db)
    assert champion.attempts == 2 and shadow.status == "done"
    # The raw rows came with the readings, one per call.
    ids = [a["raw_payload_id"] for a in champion.attempts_json + shadow.attempts_json]
    assert len(set(ids)) == 3
    assert all(run_env.db.get(RawPayload, raw_id) is not None for raw_id in ids)
    assert run_env.db.get(IngestionRun, champion.ingestion_run_id).status == "success"


@linux_only
def test_maintenance_started_during_the_calls_writes_nothing(run_env):
    from worker import job as worker_job

    counts = lambda: [  # noqa: E731
        run_env.db.scalar(select(func.count(model.id)))
        for model in (PremarketAiReading, PremarketAiStock, IngestionRun, RawPayload)
    ]
    before = counts()

    def deploy_starts(payload):
        worker_job.maintenance_on(run_env.data, "deploy")
        return valid(payload)

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
def test_a_rerun_after_done_calls_nothing_and_changes_nothing(run_env):
    job(run_env, FakeCli(valid))
    (first,) = _rows(run_env.db)
    before = _frozen(first)
    stocks = run_env.db.scalar(select(func.count(PremarketAiStock.id)))
    # New news after the reading: a rerun still does not read again.
    news(run_env.db, ["2330"], tpe(D, 7, 30), title="新")
    run_env.db.commit()
    cli = FakeCli(valid)
    code, _ = job(run_env, cli, trigger="manual")
    assert code == 0 and cli.prompts == []
    assert "--- result status=skipped reason=already_done" in _log(run_env)
    (again,) = _rows(run_env.db)
    run_env.db.refresh(again)
    assert _frozen(again) == before
    assert run_env.db.scalar(select(func.count(PremarketAiStock.id))) == stocks


@linux_only
def test_a_rerun_after_a_failure_adds_the_next_row(run_env):
    code, _ = job(run_env, FakeCli(RATE_LIMITED))
    assert code == 1
    (failed,) = _rows(run_env.db)
    before = _frozen(failed)
    assert failed.status == "failed" and failed.reason == "rate_limited"
    assert "--- result status=failed reason=rate_limited" in _log(run_env)
    code, _ = job(run_env, FakeCli(valid), at="08:35")
    assert code == 0
    first, second = _rows(run_env.db)
    run_env.db.refresh(first)
    assert _frozen(first) == before
    assert (second.sequence, second.status) == (2, "done")


@linux_only
def test_the_shadow_reads_the_same_input_into_its_own_row(
    run_env, monkeypatch, tmp_path
):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    text = premarket_reading.prompt_text("premarket_v1")
    (prompts / "premarket_v1.md").write_text(text, encoding="utf-8")
    shadow_text = text + "\n9. 測試用的 shadow 版本。\n"
    (prompts / "premarket_v1_test.md").write_text(shadow_text, encoding="utf-8")
    monkeypatch.setattr(premarket_reading, "PROMPT_DIR", prompts)
    monkeypatch.setitem(
        premarket_reading.PROMPTS,
        "premarket_v1_test",
        hashlib.sha256(shadow_text.encode("utf-8")).hexdigest(),
    )
    monkeypatch.setattr(premarket_reading, "SHADOW_PROMPT_VERSION", "premarket_v1_test")
    cli = FakeCli(valid, valid)
    code, _ = job(run_env, cli)
    assert code == 0 and len(cli.prompts) == 2
    champion, shadow = _rows(run_env.db)
    assert (champion.role, shadow.role) == ("champion", "shadow")
    assert shadow.prompt_version == "premarket_v1_test"
    assert shadow.input_hash == champion.input_hash
    assert shadow.input_json == champion.input_json
    assert "shadow status=done" in _log(run_env)


@linux_only
def test_a_later_shadow_reads_the_champions_stored_input(
    run_env, monkeypatch, tmp_path
):
    job(run_env, FakeCli(valid))
    (champion,) = _rows(run_env.db)
    # Something the fresh input would have now: news collected after the reading.
    news(run_env.db, ["2330"], tpe(D, 7, 40), collected=tpe(D, 7, 41), title="遲到")
    run_env.db.commit()
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    text = premarket_reading.prompt_text("premarket_v1")
    (prompts / "premarket_v1.md").write_text(text, encoding="utf-8")
    (prompts / "premarket_v1_test.md").write_text(text + "\n", encoding="utf-8")
    monkeypatch.setattr(premarket_reading, "PROMPT_DIR", prompts)
    monkeypatch.setitem(
        premarket_reading.PROMPTS,
        "premarket_v1_test",
        hashlib.sha256((text + "\n").encode("utf-8")).hexdigest(),
    )
    monkeypatch.setattr(premarket_reading, "SHADOW_PROMPT_VERSION", "premarket_v1_test")
    assert snapshot(run_env.db).hash != champion.input_hash
    cli = FakeCli(valid)
    job(run_env, cli, at="08:30")
    assert len(cli.prompts) == 1
    _champion, shadow = _rows(run_env.db)
    assert shadow.role == "shadow" and shadow.input_hash == champion.input_hash
    assert (
        f"--- stored_input reading_id={champion.id} input_hash={champion.input_hash}"
        in _log(run_env)
    )


@linux_only
@pytest.mark.parametrize(
    "at, trigger, expected",
    [
        ("08:46", "scheduler", "status=skipped reason=too_late at=08:46"),
        ("08:20", "scheduler", "status=skipped reason=too_late at=08:20"),
    ],
)
def test_a_scheduled_run_outside_0821_to_0845_is_too_late(
    run_env, at, trigger, expected
):
    cli = FakeCli(valid)
    code, _ = job(run_env, cli, at=at, trigger=trigger)
    assert code == 0 and cli.prompts == []
    assert f"--- result {expected}" in _log(run_env)
    assert _rows(run_env.db) == []


@linux_only
def test_a_dry_run_calls_once_and_writes_nothing(run_env, tmp_path):
    dump = tmp_path / "dump"
    cli = FakeCli(valid)
    code, out = job(run_env, cli, "--dry-run", "--dump", str(dump), trigger="manual")
    assert code == 0 and len(cli.prompts) == 1
    assert "--- result status=done" in out
    assert not run_env.logs.exists()
    assert _rows(run_env.db) == []
    assert run_env.db.scalar(select(func.count(IngestionRun.id))) == 0
    assert json.loads((dump / "input.json").read_text(encoding="utf-8"))[
        "list_date"
    ] == ("2026-11-23")
    assert (
        json.loads((dump / "champion-premarket_v1.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "done"
    )


@linux_only
def test_a_closed_day_and_maintenance_are_skipped(run_env):
    from worker import job as worker_job

    worker_job.maintenance_on(run_env.data, "test")
    try:
        code, _ = job(run_env, FakeCli(valid))
    finally:
        worker_job.maintenance_off(run_env.data, "test")
    assert code == 0 and "--- result status=skipped reason=maintenance" in _log(run_env)
    args = _args(
        "--now",
        "2026-11-28T08:21",
        "--trigger",
        "scheduler",
        "--log-dir",
        str(run_env.logs),
    )
    out = io.StringIO()
    premarket_ai._Run(args, runner=FakeCli(valid), out=out).run()
    assert "status=skipped reason=non_trading_day" in out.getvalue()
    assert _rows(run_env.db) == []


# --- the migration --------------------------------------------------------------------


TABLES = {"premarket_ai_readings", "premarket_ai_stocks", "premarket_ai_scores"}
INDEXES = {
    "ix_premarket_ai_readings_session_date",
    "ix_premarket_ai_stocks_reading_id",
    "ix_premarket_ai_stocks_session_date",
    "ix_premarket_ai_stocks_instrument_id",
    "ix_premarket_ai_scores_reading_id",
    "ix_premarket_ai_scores_session_date",
}


def _alembic_config(engine):
    from alembic.config import Config

    from app import migrations

    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    return config


def _schema(engine):
    names = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        indexes = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        version = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        fk = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    return names, indexes, version, fk


def test_the_migration_goes_down_and_up_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command

    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith("_premarket_ai"))
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
            reading = PremarketAiReading(
                session_date=D,
                list_date=L,
                role="champion",
                sequence=1,
                trigger="manual",
                prompt_version="premarket_v1",
                prompt_sha256="a" * 64,
                schema_sha256="b" * 64,
                model_alias="sonnet",
                llm_model=MODEL,
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
                PremarketAiStock(
                    reading_id=reading.id,
                    session_date=D,
                    prompt_version="premarket_v1",
                    role="champion",
                    instrument_id=row.id,
                    symbol="2330",
                    position=1,
                    on_today_list=False,
                    pool_sources_json=["watchlist"],
                    action="keep",
                    reasons_json=[],
                )
            )
            session.commit()
        names, indexes, version, _fk = _schema(engine)
        assert TABLES <= names and INDEXES <= indexes
        assert version == [(revision,)]

        command.downgrade(config, previous)
        names, indexes, version, fk = _schema(engine)
        assert not TABLES & names and not INDEXES & indexes
        assert version == [(previous,)] and fk == []

        command.upgrade(config, revision)
        names, indexes, version, fk = _schema(engine)
        assert TABLES <= names and INDEXES <= indexes
        assert version == [(revision,)] and fk == []
    finally:
        engine.dispose()
