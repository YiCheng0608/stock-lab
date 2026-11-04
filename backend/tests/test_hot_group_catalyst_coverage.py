"""hot_group_v1 catalyst follows the dated MOPS coverage (docs/spec/hot_group.md, #453).

A 20-session window whose every date is a dated answer (verified or empty)
gives a catalyst value: the capped event count, or a valid 0 without events.
Any partial or unqueried date in the window makes the catalyst null and the
group partial, with or without events.  Candidates qualify only complete
groups, so a fully covered day no longer drops ranked groups from them.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.candidates as candidates
import worker.mops_events as mops_events
import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.domain import HOT_GROUP_VERSION
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    Event,
    GroupDailyScore,
    GroupDailyScoreArchive,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    TechnicalFeature,
    ThemeGroup,
)

SCORE_DATE = date(2026, 9, 4)
GROWTH = {"S1": 0.001, "S2": 0.002, "S3": 0.003, "S4": 0.004, "S5": 0.005, "S6": 0.006}


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalyst.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _market(db):
    """TAIEX and six stocks over 25 sessions; two industry groups of three."""

    dates = pipeline.business_days(SCORE_DATE, 25)
    benchmark = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="TAIEX",
        name="TAIEX",
        instrument_type="index",
        status="active",
    )
    db.add(benchmark)
    stocks = {}
    for symbol in GROWTH:
        stocks[symbol] = Instrument(
            market="TW",
            exchange="TWSE",
            symbol=symbol,
            name=symbol,
            instrument_type="stock",
            status="active",
        )
        db.add(stocks[symbol])
    db.flush()
    for index, day in enumerate(dates):
        level = 100 + index * 0.1
        db.add(
            MarketBar(
                instrument_id=benchmark.id,
                trading_date=day,
                open=level,
                high=level,
                low=level,
                close=level,
                adj_close=level,
                volume=0,
                turnover=0,
                source="fixture",
            )
        )
        for symbol, rate in GROWTH.items():
            close = 50 * (1 + rate) ** index
            volume = 1000 + 10 * index * int(symbol[-1])
            db.add(
                MarketBar(
                    instrument_id=stocks[symbol].id,
                    trading_date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adj_close=close,
                    volume=volume,
                    turnover=close * volume,
                    turnover_status="available",
                    source="fixture",
                )
            )
            db.add(
                ChipSnapshot(
                    instrument_id=stocks[symbol].id,
                    trading_date=day,
                    foreign_buy=10 * int(symbol[-1]),
                    trust_buy=5,
                    dealer_buy=1,
                    margin_balance=1000,
                    margin_change=0,
                    source="fixture",
                )
            )
    for row in stocks.values():
        for day in dates[-3:]:
            db.add(
                TechnicalFeature(
                    instrument_id=row.id,
                    trading_date=day,
                    features_json={},
                    source="fixture",
                )
            )
    for group_id, symbols in (
        ("ind-a", ("S1", "S2", "S3")),
        ("ind-b", ("S4", "S5", "S6")),
    ):
        db.add(
            ThemeGroup(
                id=group_id, name=group_id, group_type="official_industry", active=True
            )
        )
        db.flush()
        for symbol in symbols:
            db.add(
                GroupMembership(
                    group_id=group_id,
                    instrument_id=stocks[symbol].id,
                    valid_from=dates[0],
                    source="fixture",
                )
            )
    db.flush()
    window = pipeline._effective_trading_dates(db, benchmark.id, SCORE_DATE, 20)
    return stocks, window


def _event(db, instrument, day, title="重大訊息"):
    db.add(
        Event(
            instrument_id=instrument.id,
            event_date=day,
            event_type="material_information",
            title=title,
            source=mops_events.EVENT_SOURCE,
            endpoint=mops_events.MOPS_EVENT_LIST_ENDPOINT,
        )
    )
    db.flush()


def _coverage(db, days, *, partial=(), observed=()):
    """One event_backfill run answering ``days``; ``partial`` dates failed."""

    manifest = {}
    for day in days:
        if day in partial:
            coverage = mops_events.date_coverage(day, None, error="fixture failure")
        else:
            coverage = mops_events.date_coverage(day, None)
            if day in observed:
                coverage = {
                    **coverage,
                    "status": "complete",
                    "verified_dates": [day.isoformat()],
                    "empty_dates": [],
                    "observed_event_dates": [day.isoformat()],
                }
        manifest[day.isoformat()] = {"event_coverage": coverage}
    db.add(
        IngestionRun(
            run_type=mops_events.RUN_TYPE,
            source="official",
            run_date=SCORE_DATE,
            status="success",
            metadata_json={"coverage_manifest": manifest},
        )
    )
    db.flush()


def _scores(db):
    return {
        row.group_id: row
        for row in db.scalars(
            select(GroupDailyScore).where(GroupDailyScore.trading_date == SCORE_DATE)
        )
    }


# AC-2: with events, without events and full coverage, without events and gaps


def test_events_with_full_coverage_give_a_catalyst_and_complete_group(factory):
    with factory() as db:
        stocks, window = _market(db)
        _event(db, stocks["S1"], window[-1])
        _coverage(db, window, observed={window[-1]})
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        row = _scores(db)["ind-a"]
        # One event on the score date: (0.5 + 0.3 + 0.2) / 3.
        assert row.catalyst == pytest.approx(1 / 3)
        assert row.data_quality == "complete"
        assert row.rank is not None


def test_no_events_with_full_coverage_is_a_valid_zero(factory):
    with factory() as db:
        _stocks, window = _market(db)
        _coverage(db, window)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        for row in _scores(db).values():
            assert row.catalyst == 0.0
            assert row.details_json["normalized_values"]["catalyst"] == 0.0
            assert row.data_quality == "complete"
            assert row.rank is not None


@pytest.mark.parametrize("gap", ["unqueried", "partial"])
@pytest.mark.parametrize("with_event", [False, True])
def test_any_unanswered_window_date_makes_the_catalyst_null(factory, gap, with_event):
    with factory() as db:
        stocks, window = _market(db)
        if with_event:
            # An event does not stand in for the missing coverage.
            _event(db, stocks["S1"], window[-1])
        answered = [day for day in window if gap == "partial" or day != window[3]]
        _coverage(
            db,
            answered,
            partial={window[3]} if gap == "partial" else (),
            observed={window[-1]} if with_event else (),
        )
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        row = _scores(db)["ind-a"]
        assert row.catalyst is None
        assert row.data_quality == "partial"
        # The four other components still score and rank (weight 0.90).
        assert row.score is not None and row.rank is not None
        coverage = row.details_json["catalyst_coverage"]
        assert coverage["complete"] is False
        assert coverage["unanswered_dates"] == [window[3].isoformat()]


def test_snapshot_only_window_is_unqueried(factory):
    with factory() as db:
        stocks, window = _market(db)
        _event(db, stocks["S1"], window[-1])
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        row = _scores(db)["ind-a"]
        assert row.catalyst is None and row.data_quality == "partial"
        assert row.details_json["catalyst_coverage"]["states"] == {"unqueried": 20}


def test_coverage_is_read_once_per_score_date(factory, monkeypatch):
    calls = []
    original = mops_events.event_coverage_states

    def spy(db, days):
        days = list(days)
        calls.append(days)
        return original(db, days)

    monkeypatch.setattr(mops_events, "event_coverage_states", spy)
    with factory() as db:
        _stocks, window = _market(db)
        _coverage(db, window)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
    assert calls == [window]


def test_coverage_details_and_version(factory):
    with factory() as db:
        _stocks, window = _market(db)
        _coverage(db, window)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        row = _scores(db)["ind-a"]
        assert row.details_json["hot_group_version"] == HOT_GROUP_VERSION == "1.2.0"
        assert row.details_json["catalyst_coverage"] == {
            "window": [window[0].isoformat(), window[-1].isoformat()],
            "sessions": 20,
            "states": {"empty": 20},
            "complete": True,
            "unanswered_dates": [],
        }


def test_rows_of_the_previous_version_are_archived_before_overwrite(factory):
    with factory() as db:
        _stocks, window = _market(db)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        row = _scores(db)["ind-a"]
        row.details_json = {**row.details_json, "hot_group_version": "1.1.0"}
        db.flush()
        _coverage(db, window)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        archived = db.scalars(select(GroupDailyScoreArchive)).all()
        assert [
            (item.group_id, item.hot_group_version, item.archive_reason)
            for item in archived
        ] == [("ind-a", "1.1.0", "superseded_by_1.2.0")]
        assert archived[0].catalyst is None and archived[0].data_quality == "partial"


# AC-2: candidates qualify the complete group of a fully covered day


def test_candidates_qualify_groups_of_a_fully_covered_day(factory):
    with factory() as db:
        stocks, window = _market(db)
        _coverage(db, window)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        groups, _summary = candidates._group_inputs(db, SCORE_DATE)
        first = groups[stocks["S1"].id][0]
        assert first["qualified"] is True
        assert first["rank"] is not None and first["data_quality"] == "complete"


def test_candidates_keep_partial_groups_unqualified_with_their_quality(factory):
    with factory() as db:
        stocks, window = _market(db)
        _coverage(db, window[1:])
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        groups, _summary = candidates._group_inputs(db, SCORE_DATE)
        first = groups[stocks["S1"].id][0]
        assert first["qualified"] is False and first["rank"] is None
        # The candidate row keeps why the group was not used.
        assert first["data_quality"] == "partial"
