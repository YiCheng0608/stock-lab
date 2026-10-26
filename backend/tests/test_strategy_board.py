"""Stock strategy board (``strategy_board`` of the stock detail API, #274)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_candidates import T, signal, stock

from app.api import get_db, router
from app.db import Base, enable_sqlite_foreign_keys
from app.domain import STRATEGY_LEVELS_VERSION, RuleEvaluation
from app.models import (
    CandidateLlmNote,
    DailyCandidate,
    Instrument,
    MarketBar,
    Signal,
    StrategyLevel,
)
from app.strategies import REGISTRY, ObservationLevels, StrategyInputs
from app.strategies import levels
from worker import pipeline
from worker.candidates import compute_daily_candidates

BREAKOUT, PULLBACK = REGISTRY["breakout_v1"], REGISTRY["pullback_v1"]


@pytest.fixture
def db():
    # Same database as test_candidates (whose stock/signal helpers build the rows).
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


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client


def stored_conditions(strategy, state="rejected", reasons=()):
    """A compact conditions_json as the levels step writes it."""

    evaluation = RuleEvaluation(state == "passed", state, tuple(reasons))
    inputs = StrategyInputs(
        bar_count=60,
        close=100.0,
        volume=1000,
        ma20=99.0,
        ma60=95.0,
        atr14=2.0,
        prior_highs=[101.0] * 20,
        prior_volumes=[800] * 20,
        group_excess_return_20d=0.01,
        institutional_flow_ratio_5d=0.0,
        margin_change_ratio_5d=0.0,
    )
    conditions = [
        *levels.common_conditions(
            instrument_type="stock",
            etf_category=None,
            bar_count=60,
            is_suspended=False,
            evaluation=evaluation,
        ),
        *strategy.conditions(inputs, evaluation, ObservationLevels("levels")),
    ]
    return levels.compact_conditions(strategy, conditions), [
        item.as_json() for item in conditions
    ]


def level_row(db, signal_row, strategy, **values):
    compact, full = stored_conditions(strategy, **values.pop("evaluation", {}))
    db.add(
        StrategyLevel(
            signal_id=signal_row.id,
            levels_version=STRATEGY_LEVELS_VERSION,
            next_session_date=date(2026, 9, 7),
            conditions_json=compact,
            missing_inputs_json=values.pop("missing_inputs_json", []),
            price_basis="score_date_raw_basis",
            **values,
        )
    )
    db.flush()
    return full


def board(client, symbol, **params):
    response = client.get(f"/api/stocks/TWSE/{symbol}", params=params)
    assert response.status_code == 200
    return response.json()


def rows(body):
    return {row["strategy"]: row for row in body["strategy_board"]["strategies"]}


def test_a_candidate_reads_signal_levels_and_its_observation_reads_the_table(
    db, client
):
    alpha = stock(db, "1101")
    breakout = signal(db, alpha)
    pullback = signal(db, alpha, "pullback_v1", status="observation")
    for row in (breakout, pullback):
        row.pullback_low = row.pullback_high = row.reference_entry = None
    pullback.breakout_price = pullback.invalid_price = None
    pullback.target_1 = pullback.target_2 = None
    # The conditional signal's own levels row holds other numbers: never shown.
    level_row(
        db,
        breakout,
        BREAKOUT,
        availability="levels",
        trigger_price=555.0,
        invalid_price=500.0,
        evaluation={"state": "passed"},
    )
    full = level_row(
        db,
        pullback,
        PULLBACK,
        availability="levels",
        zone_low=99.1,
        zone_high=100.9,
        min_volume=480,
        max_volume=960,
        reference_entry=100.0,
        entry_low=98.5,
        entry_high=100.5,
        invalid_price=98.0,
        target_1=103.2,
        target_2=106.0,
        risk_reward=1.6,
        reachable_next_session=True,
        evaluation={
            "reasons": [
                "close_outside_ma20_support_zone",
                "pullback_volume_ratio_outside_range",
            ]
        },
    )
    db.commit()
    compute_daily_candidates(db, T)
    run_row = db.scalar(select(DailyCandidate))
    db.add(
        CandidateLlmNote(
            daily_candidate_id=run_row.id,
            candidate_run_id=run_row.candidate_run_id,
            trading_date=T,
            llm_input_hash="0" * 64,
            prompt_version="candidate_notes_v1",
            llm_status="done",
            ai_selection="入選",
            ai_levels="價位",
            ai_risks="風險",
            llm_model="sonnet",
        )
    )
    db.commit()

    body = board(client, "1101")
    payload = body["strategy_board"]
    assert payload["as_of"] == T.isoformat()
    assert payload["levels_version"] == "strategy_levels_v1"
    assert payload["candidate"]["rank"] == 1
    assert payload["candidate"]["strategy"] == "breakout_v1"
    assert payload["candidate"]["total_score"] == body["candidate"]["total_score"]
    assert payload["candidate"]["llm_note"]["status"] == "done"
    assert payload["candidate"]["llm_note"]["inference"] is True
    assert [row["strategy"] for row in payload["strategies"]] == list(REGISTRY)

    by_key = rows(body)
    actionable = by_key["breakout_v1"]
    assert actionable["status"] == "conditional"
    assert actionable["label"] == "突破條件"
    assert actionable["signal_date"] == T.isoformat()
    assert actionable["levels"] == {
        "kind": "actionable",
        "entry_type": "breakout",
        "trigger_price": 100.0,
        "reference_entry": None,
        "entry_low": None,
        "entry_high": None,
        "invalid_price": 98.0,
        "target_1": 103.2,
        "target_2": 106.0,
        "risk_reward": 1.6,
    }
    assert [item["code"] for item in actionable["conditions"]][:3] == [
        "eligibility",
        "required_inputs",
        "breakout_price",
    ]

    observation = by_key["pullback_v1"]
    assert observation["status"] == "observation"
    assert observation["levels"]["kind"] == "observation"
    assert observation["levels"]["display_label"] == "條件未成立・觀察價位"
    assert observation["levels"]["availability"] == "levels"
    assert (
        observation["levels"]["zone_low"],
        observation["levels"]["zone_high"],
        observation["levels"]["min_volume"],
        observation["levels"]["max_volume"],
    ) == (99.1, 100.9, 480, 960)
    assert observation["levels"]["next_session_date"] == "2026-09-07"
    assert observation["levels_missing"] is False
    assert observation["unmet"] == ["pullback_support_zone", "pullback_volume"]
    # The compact stored list reads back as the full condition list.
    assert observation["conditions"] == full


def test_trend_unreachable_has_no_price_levels(db, client):
    beta = stock(db, "1102")
    pullback = signal(db, beta, "pullback_v1", status="observation")
    level_row(
        db,
        pullback,
        PULLBACK,
        availability="trend_unreachable",
        missing_inputs_json=["trend_cannot_pass_within_support_zone"],
        evaluation={"reasons": ["ma20_not_above_ma60"]},
    )
    db.commit()
    row = rows(board(client, "1102"))["pullback_v1"]
    assert row["status"] == "observation"
    levels_ = row["levels"]
    assert levels_["availability"] == "trend_unreachable"
    assert levels_["missing_inputs"] == ["trend_cannot_pass_within_support_zone"]
    price_fields = (
        "trigger_price",
        "zone_low",
        "zone_high",
        "reference_entry",
        "invalid_price",
        "target_1",
        "target_2",
        "risk_reward",
    )
    assert all(levels_[key] is None for key in price_fields)
    assert row["unmet"] == ["pullback_trend"]
    # The breakout signal of the day is missing: its row says so, with no levels.
    missing = rows(board(client, "1102"))["breakout_v1"]
    assert missing["status"] == "data_incomplete"
    assert missing["missing"] == ["signal_not_computed"]
    assert missing["levels"] is None and missing["conditions"] == []


def test_incomplete_data_lists_what_is_missing(db, client):
    gamma = stock(db, "1103")
    for key in REGISTRY:
        row = signal(db, gamma, key, status="data_incomplete")
        row.rationale = (
            "breakout=rejected:; pullback=data_incomplete:history_under_60_bars; "
            "group=missing; missing=history_under_60_bars,"
            "effective_group_score_missing_or_under_minimum_members"
        )
        row.breakout_price = row.invalid_price = row.target_1 = None
    db.commit()
    row = rows(board(client, "1103"))["pullback_v1"]
    assert row["status"] == "data_incomplete"
    assert row["missing"] == [
        "history_under_60_bars",
        "effective_group_score_missing_or_under_minimum_members",
    ]
    assert row["missing_labels"] == [
        "近 60 個交易日行情不足",
        "族群成員或相對大盤資料不足，無法取得有效群組脈絡",
    ]
    assert row["levels"] is None and row["levels_missing"] is False


def test_an_excluded_etf_category_is_not_applicable(db, client):
    etf = stock(db, "00679B", instrument_type="etf")
    etf.etf_category = "bond"
    for key in REGISTRY:
        row = signal(db, etf, key, status="data_incomplete")
        row.rationale = "missing=etf_category_excluded_from_actionable_signals:bond"
    db.commit()
    body = board(client, "00679B")
    for row in body["strategy_board"]["strategies"]:
        assert row["status"] == "not_applicable"
        assert row["missing"] == ["etf_category_excluded_from_actionable_signals:bond"]
        assert row["missing_labels"] == [
            "債券、槓桿或反向 ETF 不適用一般突破／回踩研究條件"
        ]
        assert row["levels"] is None
    assert body["strategy_board"]["candidate"] is None


def test_an_observation_without_a_levels_row_is_left_empty(db, client):
    # An older date (before the table) or a failed levels step: nothing is filled.
    delta = stock(db, "1104")
    for key in REGISTRY:
        signal(db, delta, key, status="observation")
    db.commit()
    for row in board(client, "1104")["strategy_board"]["strategies"]:
        assert row["status"] == "observation"
        assert row["levels"] is None
        assert row["levels_missing"] is True
        assert row["conditions"] == [] and row["unmet"] == []


def test_a_later_status_is_still_the_conditional_of_its_date(db, client):
    # evaluate moved the status; the actionable flag of T keeps the row 成立.
    epsilon = stock(db, "1105")
    moved = signal(db, epsilon, status="conditional")
    moved.status = "target_1_hit"
    db.commit()
    row = rows(board(client, "1105"))["breakout_v1"]
    assert row["status"] == "conditional"
    assert row["levels"]["kind"] == "actionable"


def test_only_the_as_of_day_candidate_is_on_the_board(db, client):
    zeta = stock(db, "1106")
    signal(db, zeta)
    db.commit()
    compute_daily_candidates(db, T)
    later = date(2026, 9, 7)
    db.add(
        MarketBar(
            instrument_id=zeta.id,
            trading_date=later,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            adj_close=100.0,
            volume=1000,
            turnover=100000.0,
            source="fixture-bars",
        )
    )
    signal(db, zeta, status="observation", day=later)
    db.commit()
    body = board(client, "1106")
    # The existing field keeps the latest run on or before the cutoff.
    assert body["candidate"]["trading_date"] == T.isoformat()
    assert body["strategy_board"]["as_of"] == later.isoformat()
    assert body["strategy_board"]["candidate"] is None
    assert (
        board(client, "1106", as_of=T.isoformat())["strategy_board"]["candidate"][
            "rank"
        ]
        == 1
    )


def test_the_board_changes_no_other_field_or_page(db, client):
    eta = stock(db, "1107")
    breakout = signal(db, eta)
    pullback = signal(db, eta, "pullback_v1", status="observation")
    db.commit()
    compute_daily_candidates(db, T)
    before = {
        "stock": board(client, "1107"),
        "candidates": client.get("/api/candidates").json(),
        "actions": client.get("/api/actions").json(),
    }
    for row, strategy in ((breakout, BREAKOUT), (pullback, PULLBACK)):
        level_row(db, row, strategy, availability="levels", trigger_price=1.0)
    db.commit()
    after = {
        "stock": board(client, "1107"),
        "candidates": client.get("/api/candidates").json(),
        "actions": client.get("/api/actions").json(),
    }
    clock = ("response_generated_at", "generated_at", "computed_at")

    def without(value):
        if isinstance(value, dict):
            return {
                k: without(v)
                for k, v in value.items()
                if k not in clock and k != "strategy_board"
            }
        if isinstance(value, list):
            return [without(item) for item in value]
        return value

    assert without(after) == without(before)
    assert after["stock"]["strategy_board"] != before["stock"]["strategy_board"]


def test_a_stock_without_signals_has_one_empty_row_per_strategy(db, client):
    db.add(
        Instrument(
            exchange="TWSE",
            symbol="1108",
            name="無訊號",
            instrument_type="stock",
            status="active",
        )
    )
    db.commit()
    payload = board(client, "1108")["strategy_board"]
    assert payload["as_of"] is None and payload["candidate"] is None
    assert [row["missing"] for row in payload["strategies"]] == [
        ["signal_not_computed"]
    ] * len(REGISTRY)


def test_the_board_reads_only_current_strategy_versions(db, client):
    theta = stock(db, "1109")
    old = signal(db, theta, status="observation")
    old.strategy_version_id = None
    db.commit()
    assert db.scalar(select(Signal).where(Signal.id == old.id)) is not None
    row = rows(board(client, "1109"))["breakout_v1"]
    assert row["missing"] == ["signal_not_computed"]
