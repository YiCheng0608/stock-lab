"""Daily candidate list (candidate_score_v1) on an in-memory SQLite database."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import get_db, router
from app.db import Base, enable_sqlite_foreign_keys
from app.domain import (
    CANDIDATE_SCORE,
    CANDIDATE_SCORE_V1,
    CANDIDATE_SCORE_V2,
    CANDIDATE_SCORE_VERSION,
    weighted_available_mean,
)
from app.models import (
    CandidateRun,
    ChipSnapshot,
    DailyCandidate,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    NewsLlmResult,
    Signal,
    ThemeGroup,
)
from worker import news_llm, pipeline
from worker.candidates import _chip_inputs, compute_daily_candidates


def _weekdays(end: date, count: int) -> list[date]:
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


T = date(2026, 9, 4)
DAYS = _weekdays(T, 25)
CLOSE = 100.0
NEWS_PROMPT_VERSION = CANDIDATE_SCORE["components"]["news_sentiment"][
    "llm_prompt_version"
]


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


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client


def stock(
    db,
    symbol,
    *,
    exchange="TWSE",
    instrument_type="stock",
    volume=1000,
    flow=(10.0, 10.0, 0.0),
    margin=(1000.0, 1000.0),
    chips=True,
):
    instrument = Instrument(
        exchange=exchange,
        symbol=symbol,
        name=f"名{symbol}",
        instrument_type=instrument_type,
        status="active",
    )
    db.add(instrument)
    db.flush()
    for day in DAYS:
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=CLOSE,
                high=CLOSE + 1,
                low=CLOSE - 1,
                close=CLOSE,
                adj_close=CLOSE,
                volume=volume,
                turnover=CLOSE * volume,
                source="fixture-bars",
            )
        )
        if chips:
            db.add(
                ChipSnapshot(
                    instrument_id=instrument.id,
                    trading_date=day,
                    foreign_buy=flow[0],
                    trust_buy=flow[1],
                    dealer_buy=flow[2],
                    margin_balance=margin[1] if day == T else margin[0],
                    source="fixture-chips",
                )
            )
    db.flush()
    return instrument


def signal(
    db,
    instrument,
    strategy="breakout_v1",
    *,
    status="conditional",
    volume_ratio=1.5,
    distance=0.01,
    invalid=98.0,
    target_1=103.2,
    day=T,
    evidence=True,
    actionable_flag=True,
):
    breakout = strategy == "breakout_v1"
    prior_volume = 1000 / volume_ratio
    inputs = (
        {
            "prior_20_volumes": [prior_volume] * 20,
            "prior_20_highs": [CLOSE / (1 + distance)] * 20,
            "ma20": CLOSE / (1 + distance),
        }
        if evidence
        else {}
    )
    version = db.info["strategies"][strategy]
    row = Signal(
        signal_key=f"analysis-{instrument.exchange}-{instrument.symbol}-{day.isoformat()}-{strategy}-{version.version}",
        signal_date=day,
        instrument_id=instrument.id,
        strategy_version_id=version.id,
        status=status,
        entry_type="breakout" if breakout else "pullback",
        breakout_price=CLOSE if breakout else None,
        reference_entry=None if breakout else CLOSE,
        pullback_low=None if breakout else 99.0,
        pullback_high=None if breakout else 101.0,
        invalid_price=invalid,
        target_1=target_1,
        target_2=106.0,
        source_report="fixture-bars",
        # analyze sets the flag on T; evaluate later moves only the status.
        rule_evidence_json={"inputs": inputs, "actionable": status == "conditional"}
        if actionable_flag
        else {"inputs": inputs},
    )
    db.add(row)
    db.flush()
    return row


def group(
    db, group_id, members, *, rank, board="industry", quality="complete", eligible=3
):
    group_type = "official_industry" if board == "industry" else "theme"
    db.add(
        ThemeGroup(
            id=group_id,
            name=group_id,
            display_name_zh=f"群{group_id}",
            group_type=group_type,
        )
    )
    db.flush()
    for instrument in members:
        db.add(
            GroupMembership(
                group_id=group_id, instrument_id=instrument.id, valid_from=DAYS[0]
            )
        )
    db.add(
        GroupDailyScore(
            group_id=group_id,
            trading_date=T,
            score=80.0 - rank,
            rank=rank,
            data_quality=quality,
            eligible_members=eligible,
            details_json={
                "benchmark": "TAIEX",
                "leaderboard": "equity",
                "board": board,
            },
        )
    )
    db.flush()


def news_run(db, day=T, status="success"):
    db.add(
        IngestionRun(
            run_type="news", source="fixture-news", run_date=day, status=status
        )
    )
    db.flush()


def news(db, symbols, direction, *, published=None, event_date=None, key=None):
    published = published or datetime(2026, 9, 4, 2, 0)  # 10:00 Taipei on T
    item = NewsItem(
        canonical_key=key or f"news-{len(db.scalars(select(NewsItem)).all())}",
        source_name="fixture",
        title="標題",
        published_at=None if event_date else published,
        event_date=event_date,
        display_time=datetime.combine(event_date, datetime.min.time())
        if event_date
        else published,
        time_basis="event_date" if event_date else "published",
        time_precision="date" if event_date else "datetime",
        time_consistency="verified",
        symbols_json=symbols,
    )
    db.add(item)
    db.flush()
    if direction is not None:
        db.add(
            NewsLlmResult(
                news_item_id=item.id,
                prompt_version=NEWS_PROMPT_VERSION,
                llm_input_hash="x" * 64,
                llm_status="done",
                ai_impact_direction=direction,
            )
        )
        db.flush()
    return item


def rows(db):
    return db.scalars(select(DailyCandidate).order_by(DailyCandidate.rank)).all()


def _snapshot_sha256(config):
    snapshot = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()


def test_config_snapshot_is_pinned_and_weights_sum_to_one():
    """Changing candidate_score_v1 without a new version must fail here."""

    assert _snapshot_sha256(CANDIDATE_SCORE_V1) == (
        "bf477ab5a61bb4aa8c1d6962ebe19d21b4c608083fe3593b718dbbc429a262c8"
    )
    assert CANDIDATE_SCORE_V1["name"] == "candidate_score_v1"
    assert sum(CANDIDATE_SCORE_V1["weights"].values()) == pytest.approx(1.0)
    assert CANDIDATE_SCORE_V1["weights"] == {
        "technical": 0.35,
        "chips": 0.30,
        "group": 0.20,
        "news_sentiment": 0.15,
    }
    for name in ("technical", "chips"):
        items = CANDIDATE_SCORE_V1["components"][name]["items"]
        assert sum(item["weight"] for item in items.values()) == pytest.approx(1.0)
    assert (
        CANDIDATE_SCORE_V1["components"]["technical"]["items"]["risk_reward"]["weight"]
        == 0.0
    )


def test_v2_differs_from_v1_only_in_its_name_and_news_prompt():
    """Changing candidate_score_v2 without a new version must fail here (#262)."""

    assert _snapshot_sha256(CANDIDATE_SCORE_V2) == (
        "461c472b405da8aa2609ec7c850fa3890faa89f838a8a08a2d99ff8fc3f964d3"
    )
    assert CANDIDATE_SCORE is CANDIDATE_SCORE_V2
    assert CANDIDATE_SCORE["name"] == CANDIDATE_SCORE_VERSION == "candidate_score_v2"
    expected = copy.deepcopy(CANDIDATE_SCORE_V1)
    expected["name"] = "candidate_score_v2"
    expected["components"]["news_sentiment"]["llm_prompt_version"] = "news_v2"
    assert CANDIDATE_SCORE_V2 == expected


def test_score_reads_the_news_prompt_version_the_news_llm_writes():
    """A news prompt upgrade without a score version would leave news unscored."""

    assert (
        CANDIDATE_SCORE["components"]["news_sentiment"]["llm_prompt_version"]
        == news_llm.PROMPT_VERSION
    )


def test_weighted_mean_renormalizes_without_filling_zero():
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}
    assert weighted_available_mean({"a": 1.0, "b": None, "c": 0.0}, weights) == (
        pytest.approx(0.5 / 0.7),
        pytest.approx(0.7),
    )
    assert weighted_available_mean({"a": None, "b": None, "c": None}, weights) == (
        None,
        0.0,
    )
    # A zero-weight item never contributes or counts as coverage.
    assert weighted_available_mean({"a": 0.2, "z": 1.0}, {"a": 1.0, "z": 0.0}) == (
        0.2,
        1.0,
    )


def test_components_percentiles_nulls_and_total(db):
    a = stock(db, "1101", flow=(30.0, 20.0, 0.0), margin=(1000.0, 900.0))
    b = stock(db, "1102", flow=(5.0, -1.0, 0.0), margin=(1000.0, 1100.0))
    c = stock(db, "1103", flow=(-5.0, 0.0, 0.0), margin=(1000.0, 1000.0))
    stock(db, "1104", chips=False)  # in the market population with null chips
    signal(db, a, volume_ratio=2.0, distance=0.01)
    signal(db, b, volume_ratio=1.5, distance=0.03)
    signal(db, c, volume_ratio=1.2, distance=0.02)
    group(db, "ind-1", [a], rank=1)
    group(db, "ind-2", [b], rank=2)
    group(db, "ind-3", [], rank=3)
    news_run(db)
    news(db, ["TWSE:1101"], "positive")
    news(db, ["1101"], "positive", event_date=T - timedelta(days=2))
    news(db, ["1102"], "negative")
    news(db, ["1102"], "unknown")
    news(db, ["1103"], None)  # not yet judged by the LLM
    news(
        db, ["1101"], "positive", published=datetime(2026, 9, 1, 15, 0)
    )  # 23:00 Taipei on T-3: outside
    db.commit()

    result = compute_daily_candidates(db, T)
    assert result["status"] == "success" and result["candidate_count"] == 3
    first, second, third = rows(db)
    assert [first.instrument_id, second.instrument_id, third.instrument_id] == [
        a.id,
        b.id,
        c.id,
    ]

    tech = first.components_json["technical"]
    assert (
        tech["items"]["volume_ratio"]["percentile"] == 1.0
    )  # highest of three breakouts
    assert (
        tech["items"]["distance"]["percentile"] == 1.0
    )  # closest above the prior high
    assert tech["items"]["risk_reward"]["value"] == pytest.approx(1.6)
    assert (
        tech["score"] == 1.0 and tech["inference"] is False and tech["population"] == 3
    )

    chips = first.components_json["chips"]
    assert chips["items"]["institutional_flow_5d"]["value"] == pytest.approx(
        5 * 50 / 1000
    )
    assert chips["items"]["institutional_flow_20d"]["value"] == pytest.approx(
        20 * 50 / 1000
    )
    assert chips["items"]["margin_change_5d"]["value"] == pytest.approx(-0.1)
    assert chips["items"]["institutional_flow_5d"]["percentile"] == 1.0
    assert (
        chips["population"]["institutional_flow_5d"] == 3
    )  # 1104 has no chips: null, not zero
    assert chips["score"] == 1.0

    sentiment = first.components_json["news_sentiment"]
    assert sentiment["inference"] is True
    assert sentiment["items"]["net_direction"]["value"] == 2.0
    assert sentiment["counts"] == {
        "linked": 2,
        "positive": 2,
        "negative": 0,
        "mixed": 0,
        "unscored": 0,
    }
    assert sentiment["instruments_with_news"] == 3
    second_news = second.components_json["news_sentiment"]
    assert (
        second_news["counts"]["negative"] == 1
        and second_news["counts"]["unscored"] == 1
    )
    assert second_news["items"]["net_direction"]["value"] == -1.0
    # No linked news is a valid zero once collection succeeded; mid-rank for ties.
    assert (
        third.components_json["news_sentiment"]["items"]["net_direction"]["value"]
        == 0.0
    )

    assert first.components_json["group"]["score"] == 1.0
    assert first.components_json["group"]["source"] == {
        "group_id": "ind-1",
        "name": "群ind-1",
        "board": "industry",
        "rank": 1,
        "board_size": 3,
    }
    assert second.components_json["group"]["score"] == 0.5
    assert third.components_json["group"]["score"] is None
    assert third.components_json["group"]["null_reason"] == "no_qualified_group"
    # group is null for the third, so its total renormalizes over 0.80.
    assert third.weight_coverage == pytest.approx(0.80)
    expected = (
        sum(
            third.components_json[key]["score"] * CANDIDATE_SCORE_V1["weights"][key]
            for key in ("technical", "chips", "news_sentiment")
        )
        / 0.80
    )
    assert third.total_score == pytest.approx(expected, abs=1e-6)
    assert first.weight_coverage == 1.0 and first.total_score == pytest.approx(
        (0.35 * 1 + 0.30 * 1 + 0.20 * 1 + 0.15 * 1.0), abs=1e-6
    )

    texts = [reason["text"] for reason in first.reasons_json]
    assert texts[:2] == ["突破 20 日高點，量比 2.0", "外資＋投信 5 日淨買超"]
    assert "所屬產業「群ind-1」熱度第 1" in texts
    assert len(first.reasons_json) == CANDIDATE_SCORE_V1["max_reasons"]
    news_reason = [
        reason for reason in first.reasons_json if reason["code"] == "news_positive_3d"
    ]
    assert all(reason["inference"] for reason in news_reason)
    assert not [
        reason for reason in second.reasons_json if reason["code"] == "news_positive_3d"
    ]
    # Trust sold, so only the three-institution total qualifies; ratios read as multiples.
    assert "三大法人 5 日淨買超，約 20 日均量的 0.02 倍" in [
        reason["text"] for reason in second.reasons_json
    ]


def test_chip_inputs_match_the_strategy_functions(db):
    instrument = stock(db, "2330", flow=(12.0, -3.0, 4.0), margin=(800.0, 840.0))
    db.commit()
    raw = _chip_inputs(db, instrument.id, T)
    assert raw["institutional_flow_5d"] == pytest.approx(
        pipeline._strategy_institutional_flow_to_average_volume_ratio(
            db, instrument.id, T
        )
    )
    assert raw["margin_change_5d"] == pytest.approx(
        pipeline._margin_change_ratio(db, instrument.id, T)
    )
    # An older session never stands in for the trading date.
    assert (
        _chip_inputs(db, instrument.id, T + timedelta(days=3))["institutional_flow_5d"]
        is None
    )


def test_news_component_is_null_without_a_news_collection_run(db):
    a = stock(db, "1101")
    signal(db, a)
    group(db, "ind-1", [a], rank=1)
    news(db, ["1101"], "positive")
    db.commit()
    compute_daily_candidates(db, T)
    (row,) = rows(db)
    sentiment = row.components_json["news_sentiment"]
    assert (
        sentiment["score"] is None
        and sentiment["null_reason"] == "news_collection_missing"
    )
    assert row.weight_coverage == pytest.approx(0.85)
    run = db.scalar(select(CandidateRun))
    assert run.summary_json["news"]["null_reason"] == "news_collection_missing"


def test_ranking_ties_use_the_fixed_key(db):
    instruments = [
        stock(db, symbol, exchange=exchange)
        for exchange, symbol in (("TPEx", "6488"), ("TWSE", "2454"), ("TWSE", "1101"))
    ]
    for instrument in instruments:
        signal(db, instrument)
    db.commit()
    compute_daily_candidates(db, T)
    ordered = [
        (
            db.get(Instrument, row.instrument_id).exchange,
            db.get(Instrument, row.instrument_id).symbol,
        )
        for row in rows(db)
    ]
    assert ordered == [("TPEx", "6488"), ("TWSE", "1101"), ("TWSE", "2454")]
    assert len({row.total_score for row in rows(db)}) == 1


def test_etf_invalid_levels_and_status_are_excluded(db):
    good = stock(db, "1101")
    etf = stock(db, "0050", instrument_type="etf")
    bad = stock(db, "1102")
    rr_low = stock(db, "1103")
    observation = stock(db, "1104")
    signal(db, good)
    signal(db, etf)
    signal(db, bad, invalid=101.0)  # invalid above entry
    signal(db, rr_low, target_1=101.0)  # RR 0.5 < 1.5
    signal(db, observation, status="observation")
    db.commit()
    result = compute_daily_candidates(db, T)
    assert [row.instrument_id for row in rows(db)] == [good.id]
    assert result["exclusions"] == {
        "instrument_type_excluded:etf": 1,
        "invalid_levels": 2,
    }
    run = db.scalar(select(CandidateRun))
    assert run.evaluated_signals == 5 and run.pool_count == 1
    assert run.summary_json["signal_status_counts"] == {
        "conditional": 4,
        "observation": 1,
    }


@pytest.mark.parametrize("status", ["delisted", "transferred"])
def test_delisted_and_transferred_instruments_are_not_candidates(db, status):
    # Issue #212: the collector's status sync marks instruments that left the
    # official lists; their stored signals never enter the pool.
    good = stock(db, "1101")
    gone = stock(db, "8908", exchange="TPEx")
    signal(db, good)
    signal(db, gone)
    gone.status = status
    db.commit()
    result = compute_daily_candidates(db, T)
    assert [row.instrument_id for row in rows(db)] == [good.id]
    assert result["exclusions"] == {"instrument_inactive": 1}


def test_missing_technical_inputs_fail_the_coverage_floor(db):
    a = stock(db, "1101")
    b = stock(db, "1102")
    signal(db, a)
    signal(db, b, evidence=False)
    db.commit()
    result = compute_daily_candidates(db, T)
    assert [row.instrument_id for row in rows(db)] == [a.id]
    assert result["exclusions"] == {"insufficient_score_coverage": 1}


def test_one_row_per_stock_keeps_the_higher_scored_strategy(db):
    a = stock(db, "1101")
    b = stock(db, "1102")
    signal(db, a, "breakout_v1", volume_ratio=1.3, distance=0.05)
    signal(db, b, "breakout_v1", volume_ratio=2.0, distance=0.01)
    pullback = signal(db, a, "pullback_v1", volume_ratio=0.8, distance=0.01)
    db.commit()
    result = compute_daily_candidates(db, T)
    by_instrument = {row.instrument_id: row for row in rows(db)}
    assert len(by_instrument) == 2 and result["exclusions"] == {
        "same_instrument_lower_scored_strategy": 1
    }
    kept = by_instrument[a.id]
    assert kept.strategy == "pullback_v1" and kept.signal_id == pullback.id
    assert [item["strategy"] for item in kept.components_json["alternatives"]] == [
        "breakout_v1"
    ]
    assert kept.reasons_json[0]["text"] == "回測 20 日均線，距均線 1.0%，量比 0.8"


def test_list_is_capped_at_twenty(db):
    for index in range(22):
        signal(db, stock(db, f"{1200 + index}"), volume_ratio=1.2 + index * 0.05)
    db.commit()
    result = compute_daily_candidates(db, T)
    assert result["candidate_count"] == 20 and result["pool_count"] == 22
    assert result["exclusions"] == {"below_list_cutoff": 2}
    assert [row.rank for row in rows(db)] == list(range(1, 21))


def test_zero_candidates_are_stored_with_a_reason(db):
    observation = stock(db, "1101")
    signal(db, observation, status="observation")
    db.commit()
    result = compute_daily_candidates(db, T)
    assert (
        result["candidate_count"] == 0
        and result["zero_reason"] == "no_actionable_signals"
    )
    assert db.scalar(select(CandidateRun)).zero_reason == "no_actionable_signals"


def test_zero_candidates_when_every_conditional_is_excluded(db):
    signal(db, stock(db, "0050", instrument_type="etf"))
    db.commit()
    result = compute_daily_candidates(db, T)
    assert result["zero_reason"] == "all_excluded" and rows(db) == []


def test_a_date_without_signals_is_no_data_and_not_stored(db):
    db.commit()
    result = compute_daily_candidates(db, T)
    assert result == {
        "status": "no_data",
        "reason": "no_signals_for_date",
        "trading_date": T.isoformat(),
        "score_version": CANDIDATE_SCORE_VERSION,
        "records": 0,
    }
    assert db.scalar(select(func.count(CandidateRun.id))) == 0


def test_rerun_is_idempotent_and_a_new_version_keeps_old_rows(db):
    a = stock(db, "1101")
    b = stock(db, "1102")
    signal(db, a, volume_ratio=2.0)
    signal(db, b)
    db.commit()
    first = compute_daily_candidates(db, T)
    before = [
        (row.id, row.total_score, row.rank, row.components_json, row.reasons_json)
        for row in rows(db)
    ]

    # New inputs after the first run must not rewrite the stored list.
    news_run(db)
    news(db, ["1102"], "positive")
    db.commit()
    again = compute_daily_candidates(db, T)
    db.expire_all()
    assert (
        again["already_complete"] is True
        and again["candidate_run_id"] == first["candidate_run_id"]
    )
    assert [
        (row.id, row.total_score, row.rank, row.components_json, row.reasons_json)
        for row in rows(db)
    ] == before
    assert db.scalar(select(func.count(CandidateRun.id))) == 1

    upgraded = copy.deepcopy(CANDIDATE_SCORE_V1)
    upgraded["name"] = "candidate_score_v2_fixture"
    upgraded["weights"] = {
        "technical": 0.25,
        "chips": 0.25,
        "group": 0.25,
        "news_sentiment": 0.25,
    }
    second = compute_daily_candidates(db, T, config=upgraded)
    db.expire_all()
    assert second["candidate_run_id"] != first["candidate_run_id"]
    assert db.scalar(select(func.count(CandidateRun.id))) == 2
    old = db.scalars(
        select(DailyCandidate).where(
            DailyCandidate.score_version == CANDIDATE_SCORE_VERSION
        )
    ).all()
    assert [
        (row.id, row.total_score, row.rank, row.components_json, row.reasons_json)
        for row in old
    ] == before
    assert db.scalar(select(func.count(DailyCandidate.id))) == 4


def test_api_returns_ranked_fields_inference_and_null_explanations(db, client):
    a = stock(db, "1101", flow=(30.0, 20.0, 0.0))
    b = stock(db, "1102")
    signal(db, a, volume_ratio=2.0)
    signal(db, b, "pullback_v1", volume_ratio=0.8)
    group(db, "ind-1", [a], rank=1)
    db.commit()
    compute_daily_candidates(db, T)

    body = client.get("/api/candidates").json()
    assert (
        body["trading_date"] == T.isoformat()
        and body["score_version"] == CANDIDATE_SCORE_VERSION
    )
    assert body["candidate_count"] == 2 and body["zero_reason"] is None
    assert (
        body["methodology"]["purpose"]
        == "評分只用於排序，不代表勝率或預期報酬，不改變策略判定"
    )
    assert body["methodology"]["components"]["news_sentiment"]["inference"] is True
    assert body["methodology"]["components"]["technical"]["inference"] is False
    top = body["items"][0]
    assert (
        top["rank"] == 1
        and top["instrument"]["symbol"] == "1101"
        and top["strategy"] == "breakout_v1"
    )
    assert top["levels"] == {
        "entry_type": "breakout",
        "entry": 100.0,
        "entry_zone": {"low": 100.0, "high": 100.0},
        "invalid_price": 98.0,
        "target_1": 103.2,
        "target_2": 106.0,
        "risk_reward": 1.6,
        "earliest_execution_date": None,
    }
    assert set(top["components"]) == {"technical", "chips", "group", "news_sentiment"}
    assert top["components"]["news_sentiment"]["inference"] is True
    assert top["components"]["news_sentiment"]["score"] is None
    assert (
        top["components"]["news_sentiment"]["null_explanation"]
        == "近 3 日沒有成功的新聞收集，新聞分項無資料"
    )
    assert (
        top["weight_coverage"] == pytest.approx(0.85)
        and top["partial_components"] is True
    )
    assert top["data_as_of"] == T.isoformat()
    assert (
        top["sources"]["market_bar"] == "fixture-bars"
        and top["sources"]["chips"] == "fixture-chips"
    )
    assert top["groups"][0]["group_id"] == "ind-1" and top["groups"][0]["rank"] == 1
    assert {reason["code"] for reason in top["reasons"]} >= {
        "breakout_20d_high",
        "hot_group_rank",
    }
    pullback = body["items"][1]
    assert pullback["levels"]["entry_zone"] == {"low": 99.0, "high": 101.0}
    assert (
        pullback["components"]["group"]["null_explanation"]
        == "當日沒有已排名且資料完整的所屬產業或題材"
    )

    assert len(client.get("/api/candidates", params={"limit": 1}).json()["items"]) == 1
    assert client.get("/api/candidates", params={"limit": 21}).status_code == 422
    missing = client.get("/api/candidates", params={"date": "2026-09-03"}).json()
    assert missing["status"] == "not_computed" and missing["items"] == []

    detail = client.get("/api/stocks/TWSE/1101").json()
    assert (
        detail["candidate"]["rank"] == 1
        and detail["candidate"]["trading_date"] == T.isoformat()
    )
    other = stock(db, "9999")
    db.commit()
    assert client.get(f"/api/stocks/TWSE/{other.symbol}").json()["candidate"] is None


def test_api_reports_the_zero_reason(db, client):
    signal(db, stock(db, "1101"), status="observation")
    db.commit()
    compute_daily_candidates(db, T)
    body = client.get("/api/candidates").json()
    assert body["candidate_count"] == 0 and body["items"] == []
    assert body["zero_reason"] == "no_actionable_signals"
    assert body["zero_reason_text"] == "當日沒有成立（條件成立）的策略訊號"


# ---- item market: latest close and its change (#276) ----

ITEM_KEYS = {
    "rank",
    "trading_date",
    "score_version",
    "instrument",
    "strategy",
    "signal_id",
    "signal_status",
    "levels",
    "total_score",
    "weight_coverage",
    "partial_components",
    "components",
    "alternatives",
    "reasons",
    "groups",
    "data_as_of",
    "llm_note",
    "sources",
    # User tracking plans (#253).
    "candidate_id",
    "open_plan_id",
}


def taiex(db, days=DAYS):
    """TAIEX sessions; a ``fixture`` source counts as a verified session."""

    index = Instrument(
        exchange="TWSE",
        symbol="TAIEX",
        name="加權指數",
        instrument_type="index",
        status="active",
    )
    db.add(index)
    db.flush()
    for day in days:
        db.add(
            MarketBar(
                instrument_id=index.id,
                trading_date=day,
                open=20000.0,
                high=20000.0,
                low=20000.0,
                close=20000.0,
                adj_close=20000.0,
                source="twse_fixture",
            )
        )
    db.flush()


def bar(db, instrument, day):
    return db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id, MarketBar.trading_date == day
        )
    )


def listed_market(db, client, change=None):
    """Compute the list on T, apply ``change`` to the stored bars, read the API."""

    a = stock(db, "1101")
    signal(db, a)
    taiex(db)
    db.commit()
    compute_daily_candidates(db, T)
    if change:
        change(a)
    db.commit()
    return client.get("/api/candidates").json()["items"][0]["market"]


def test_candidate_market_has_the_close_and_its_change(db, client):
    def rise(a):
        current = bar(db, a, T)
        current.close = current.adj_close = 102.0

    assert listed_market(db, client, rise) == {
        "trading_date": T.isoformat(),
        "close": 102.0,
        "change": 2.0,
        "change_pct": pytest.approx(0.02),
        "change_status": "known",
        "source": "fixture-bars",
    }


def test_candidate_market_change_needs_the_same_source_previous_session(db, client):
    def other_source(a):
        bar(db, a, DAYS[-2]).source = "tpex"

    market = listed_market(db, client, other_source)
    assert market["close"] == CLOSE and market["source"] == "fixture-bars"
    assert market["change"] is None and market["change_pct"] is None
    assert market["change_status"] == "unverified"


def test_candidate_market_change_needs_the_adjacent_session(db, client):
    # No bar on the previous TAIEX session: the bar before it is two sessions
    # back, so its close is not the previous close.
    def gap(a):
        db.delete(bar(db, a, DAYS[-2]))

    market = listed_market(db, client, gap)
    assert market["close"] == CLOSE
    assert market["change"] is None and market["change_status"] == "unverified"


def test_candidate_market_without_a_bar_on_the_day(db, client):
    def missing(a):
        db.delete(bar(db, a, T))

    assert listed_market(db, client, missing) == {
        "trading_date": T.isoformat(),
        "close": None,
        "change": None,
        "change_pct": None,
        "change_status": "missing",
        "source": None,
    }


def test_candidate_market_keeps_every_existing_field(db, client):
    a = stock(db, "1101")
    signal(db, a)
    db.commit()
    compute_daily_candidates(db, T)
    item = client.get("/api/candidates").json()["items"][0]
    assert set(item) == ITEM_KEYS | {"market"}
    # Without verified TAIEX sessions the change cannot be checked.
    assert item["market"]["close"] == CLOSE
    assert item["market"]["change_status"] == "unverified"
    detail = client.get("/api/stocks/TWSE/1101").json()["candidate"]
    assert set(detail) == ITEM_KEYS | {"market"}


def _snapshot(db):
    db.expire_all()
    return [
        (
            row.instrument_id,
            row.signal_id,
            row.rank,
            row.total_score,
            row.weight_coverage,
            row.components_json,
            row.reasons_json,
            row.groups_json,
        )
        for row in rows(db)
    ]


def test_recomputing_a_tracked_date_sees_the_same_pool(db):
    """evaluate moves T's conditional signals on; a recompute of T must not lose them."""

    a = stock(db, "1101", flow=(30.0, 20.0, 0.0))
    b = stock(db, "1102")
    c = stock(db, "1103")
    first = signal(db, a, volume_ratio=2.0)
    second = signal(db, b, "pullback_v1", volume_ratio=0.8)
    third = signal(db, c)
    db.commit()
    on_the_day = compute_daily_candidates(db, T)
    expected = _snapshot(db)
    assert on_the_day["candidate_count"] == 3

    first.status, second.status, third.status = "active", "target_1_hit", "invalidated"
    db.execute(delete(DailyCandidate))
    db.execute(delete(CandidateRun))
    db.commit()
    again = compute_daily_candidates(db, T)
    assert again["already_complete"] is False and again["candidate_count"] == 3
    assert _snapshot(db) == expected
    run = db.scalar(select(CandidateRun))
    assert run.summary_json["actionable_signals"] == 3
    assert run.summary_json["signal_status_counts"] == {
        "active": 1,
        "invalidated": 1,
        "target_1_hit": 1,
    }


def test_rows_without_the_flag_fall_back_to_post_conditional_statuses(db):
    legacy = stock(db, "1101")
    expired = stock(db, "1102")
    unflagged_observation = stock(db, "1103")
    signal(db, legacy, status="active", actionable_flag=False)
    signal(
        db, expired, status="expired", actionable_flag=False
    )  # reachable from observation too
    signal(db, unflagged_observation, status="observation", actionable_flag=False)
    flagged_off = signal(db, stock(db, "1104"), status="active")
    assert (
        flagged_off.rule_evidence_json["actionable"] is False
    )  # the flag wins over the status
    db.commit()
    compute_daily_candidates(db, T)
    assert [row.instrument_id for row in rows(db)] == [legacy.id]


def test_equal_totals_for_both_strategies_keep_breakout(db):
    a = stock(db, "1101")
    breakout = signal(db, a, "breakout_v1")
    pullback = signal(db, a, "pullback_v1")
    db.commit()
    result = compute_daily_candidates(db, T)
    (row,) = rows(db)
    alternative = row.components_json["alternatives"][0]
    # Each strategy pool has one signal, so every percentile is 0.5 and the totals tie.
    assert alternative["total_score"] == row.total_score
    assert row.strategy == "breakout_v1" and row.signal_id == breakout.id
    assert (
        alternative["strategy"] == "pullback_v1"
        and alternative["signal_id"] == pullback.id
    )
    assert result["exclusions"] == {"same_instrument_lower_scored_strategy": 1}


# Timestamps written below (#376). `frozen_utcnow` (conftest) makes app.clock answer one
# instant to every caller, so a stamp taken from local time or the real clock stores a
# value other than the one asserted here.


def test_a_candidate_run_is_computed_at_the_clock(db, frozen_utcnow):
    signal(db, stock(db, "0050", instrument_type="etf"))
    db.commit()
    compute_daily_candidates(db, T)
    assert db.scalar(select(CandidateRun.computed_at)) == frozen_utcnow.at
