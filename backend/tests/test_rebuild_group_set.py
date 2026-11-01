"""#409: a corporate-actions rebuild rescores only the groups a session already has.

``rebuild_after_sync`` rescores old sessions with corrected prices and factors.
It must not add a group that had no score on that session (that would backfill
history with today's group definitions), and the ranks are computed among the
groups the session already had.  Daily still scores every active group.
"""

from __future__ import annotations

import warnings
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.corporate_action_sync as sync
import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    CorporateAction,
    GroupDailyScore,
    GroupDailyScoreArchive,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    ThemeGroup,
)
from app.theme_table import THEME_GROUP_TYPE
from worker.industry_repair import rescore_dates
from worker.sources import TWSE_CHIP_ENDPOINT

DATES = pipeline.business_days(date(2026, 9, 4), 26)
OLD, NEW = DATES[-2], DATES[-1]
EX_DATE = DATES[20]
# Daily growth of each group's members: G3 (added after OLD was scored) leads,
# G2 beats G1 until G1's ex-dividend drop is restored.
GROWTH = {"G1": 0.003, "G2": 0.002, "G3": 0.006}
DROP = 0.9


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'groups.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _bar(instrument, day, close, volume):
    return MarketBar(
        instrument_id=instrument.id,
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


def _seed(db):
    """TAIEX and three members for each of G1, G2, G3; only G1 and G2 exist yet."""

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
    for group in GROWTH:
        for number in (1, 2, 3):
            symbol = f"{group}{number}"
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
    for index, day in enumerate(DATES):
        level = 100 + index * 0.1
        db.add(_bar(benchmark, day, level, 0))
        raw = RawPayload(
            source="twse",
            endpoint=f"{TWSE_CHIP_ENDPOINT}?date={day:%Y%m%d}&selectType=ALL&response=json",
            sha256=f"t86-{day.isoformat()}",
            data_as_of=day.isoformat(),
        )
        db.add(raw)
        db.flush()
        for symbol, stock in stocks.items():
            number = int(symbol[-1])
            close = 50 * (1 + GROWTH[symbol[:2]] + 0.0002 * number) ** index
            if symbol == "G11" and day >= EX_DATE:
                # G11 goes ex-dividend on EX_DATE; its raw close drops by 10%.
                close *= DROP
            db.add(_bar(stock, day, close, 1000 + 100 * number))
            db.add(
                ChipSnapshot(
                    instrument_id=stock.id,
                    trading_date=day,
                    foreign_buy=10 * number,
                    trust_buy=5,
                    dealer_buy=1,
                    margin_balance=1000,
                    margin_change=0,
                    source="twse_t86+twse_margin",
                    raw_payload_id=raw.id,
                )
            )
    db.flush()
    for group in ("G1", "G2"):
        _group(db, group, stocks)
    for stock in stocks.values():
        pipeline._calculate_features(db, stock)
    db.flush()
    return stocks


def _group(db, group_id, stocks, members=None, group_type="official_industry"):
    """An active group of the three ``members`` stocks (default: G1 -> G11..G13)."""

    db.add(ThemeGroup(id=group_id, name=group_id, group_type=group_type, active=True))
    db.flush()
    for number in (1, 2, 3):
        db.add(
            GroupMembership(
                group_id=group_id,
                instrument_id=stocks[f"{members or group_id}{number}"].id,
                valid_from=DATES[0],
                source="fixture",
            )
        )
    db.flush()


def _rows(db):
    return {
        (row.trading_date, row.group_id): row
        for row in db.scalars(select(GroupDailyScore))
    }


def _ranks(db, day):
    return {key[1]: row.rank for key, row in _rows(db).items() if key[0] == day}


def _ex_dividend(db, stocks):
    """The sync's correction: G11's dividend, recorded after the sessions were scored."""

    db.add(
        CorporateAction(
            instrument_id=stocks["G11"].id,
            action_date=EX_DATE,
            action_type="corporate_action",
            cash_dividend=1.0,
            details_json={"price_factor": DROP},
            source="fixture",
        )
    )
    run = IngestionRun(
        run_type=sync.REPRICE_RUN_TYPE,
        source="fixture",
        run_date=NEW,
        status="success",
        metadata_json={"affected": {str(stocks["G11"].id): EX_DATE.isoformat()}},
    )
    db.add(run)
    db.flush()
    return run


def _scored_history(db, *, themes=False):
    """OLD scored by daily before G3 existed; NEW scored by daily with G3.

    ``themes`` adds two theme groups before OLD: T1 holds G3's members, T2 G2's.
    """

    stocks = _seed(db)
    if themes:
        _group(db, "T1", stocks, "G3", THEME_GROUP_TYPE)
        _group(db, "T2", stocks, "G2", THEME_GROUP_TYPE)
    pipeline._calculate_group_scores(db, OLD)
    db.flush()
    _group(db, "G3", stocks)
    pipeline._calculate_group_scores(db, NEW)
    db.flush()
    return stocks


def test_daily_scores_a_new_group_on_its_day(factory):
    with factory() as db:
        _scored_history(db)
        # The daily path scores every active group: G3 is scored on NEW and
        # leads the board, while OLD (scored before G3 existed) has no G3 row.
        assert _ranks(db, NEW) == {"G3": 1, "G2": 2, "G1": 3}
        assert _ranks(db, OLD) == {"G2": 1, "G1": 2}
        assert _rows(db)[(NEW, "G3")].score is not None


def test_a_rebuild_keeps_the_groups_of_each_session_and_ranks_among_them(factory):
    with factory() as db:
        stocks = _scored_history(db)
        before = {key: row.score for key, row in _rows(db).items()}
        run = _ex_dividend(db, stocks)
        db.commit()

        result = sync.rebuild_after_sync(db, run.id)
        db.commit()

        assert result["group_score_dates"]["count"] == 2
        after = _rows(db)
        # AC-1: no (date, group) is added; G3 is not backfilled onto OLD.
        assert (
            set(after)
            == set(before)
            == {
                (OLD, "G1"),
                (OLD, "G2"),
                (NEW, "G1"),
                (NEW, "G2"),
                (NEW, "G3"),
            }
        )
        # AC-2: the restored dividend lifts G1 on both sessions; on OLD it is
        # ranked against G2 alone, on NEW against the groups NEW already had.
        assert after[(OLD, "G1")].score != before[(OLD, "G1")]
        assert after[(NEW, "G1")].score != before[(NEW, "G1")]
        assert _ranks(db, OLD) == {"G1": 1, "G2": 2}
        assert _ranks(db, NEW) == {"G3": 1, "G1": 2, "G2": 3}
        assert after[(OLD, "G1")].details_json["hot_group_version"]


def test_rescore_dates_without_the_option_scores_every_active_group(factory):
    # rescore_recent (industry / instrument repair) keeps scoring every
    # active group of its recent sessions.
    with factory() as db:
        _scored_history(db)
        rescore_dates(db, [OLD])
        db.flush()
        assert _ranks(db, OLD) == {"G3": 1, "G2": 2, "G1": 3}


def test_a_session_without_scores_gets_no_row(factory):
    # A rebuild only picks sessions that have scores, but rescore_dates on a
    # session with none adds nothing (and an empty IN list does not warn).
    empty = DATES[-3]
    with factory() as db:
        _scored_history(db)
        before = set(_rows(db))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            rescore_dates(db, [empty], existing_groups_only=True)
            db.flush()
        assert set(_rows(db)) == before
        assert _ranks(db, empty) == {}


def test_theme_and_industry_boards_are_ranked_apart(factory):
    with factory() as db:
        stocks = _scored_history(db, themes=True)
        before = set(_rows(db))
        run = _ex_dividend(db, stocks)
        db.commit()
        sync.rebuild_after_sync(db, run.id)
        db.commit()
        assert set(_rows(db)) == before
        # Each board ranks its own groups from 1: the themes do not push the
        # industries down, and G3 (industry only from NEW) stays off OLD.
        assert _ranks(db, OLD) == {"G1": 1, "G2": 2, "T1": 1, "T2": 2}
        assert _ranks(db, NEW) == {"G3": 1, "G1": 2, "G2": 3, "T1": 1, "T2": 2}
        assert {
            group: row.details_json["board"]
            for (day, group), row in _rows(db).items()
            if day == OLD
        } == {"G1": "industry", "G2": "industry", "T1": "theme", "T2": "theme"}


def test_a_group_deactivated_before_the_rebuild_keeps_its_score_without_a_rank(
    factory,
):
    with factory() as db:
        stocks = _scored_history(db)
        db.get(ThemeGroup, "G2").active = False
        before = {key: row.score for key, row in _rows(db).items()}
        run = _ex_dividend(db, stocks)
        db.commit()
        sync.rebuild_after_sync(db, run.id)
        db.commit()
        after = _rows(db)
        assert set(after) == set(before)
        # G2 is not rescored: its score stays, its rank is cleared and the
        # ranked row is archived; G1 and G3 are ranked without it.
        for day in (OLD, NEW):
            assert after[(day, "G2")].score == before[(day, "G2")]
            assert after[(day, "G2")].rank is None
        assert _ranks(db, OLD) == {"G1": 1, "G2": None}
        assert _ranks(db, NEW) == {"G3": 1, "G1": 2, "G2": None}
        assert sorted(
            (row.trading_date, row.group_id)
            for row in db.scalars(
                select(GroupDailyScoreArchive).where(
                    GroupDailyScoreArchive.archive_reason
                    == "rank_cleared_inactive_group"
                )
            )
        ) == [(OLD, "G2"), (NEW, "G2")]
