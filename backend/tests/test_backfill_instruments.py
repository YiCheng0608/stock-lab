"""A collect of an old session keeps the stored instrument types and statuses (#838).

The official lists (issuer masters, ETF lists, TWSE ``company/newlisting``) are
always today's.  A backfill or a re-run of an old date used to classify them
against the old session and write the result over every stored instrument:
#702 batch 5 turned 8 delisted ``ipo`` instruments back to ``active`` and
flipped 23 others between ``stock`` and ``ipo``.  Now only a new instrument
takes those values; the daily collect of today's session is unchanged.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Instrument, MarketBar

TODAY = date(2026, 11, 17)  # a Tuesday
OLD_SESSION = date(2011, 3, 1)


@pytest.fixture
def pipeline_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(pipeline, "taipei_today", lambda: TODAY)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


class FakeAdapter:
    def __init__(self, batch):
        self.batch = batch

    def fetch(self, start, end):
        return self.batch


def _batch(day: date) -> sources.OfficialBatch:
    """Today's lists as a collect of ``day`` sees them, and that day's quotes."""

    capture = sources.capture_payload(
        "twse",
        sources.TWSE_LISTED_ENDPOINT,
        {"fixture": day.isoformat()},
        day.isoformat(),
        collected_at=datetime(2026, 11, 17, 10, 0),
    )

    def record(symbol, instrument_type, exchange="TWSE"):
        return sources.InstrumentRecord(
            symbol,
            f"{symbol} official",
            exchange=exchange,
            instrument_type=instrument_type,
            industry="24",
            payload_sha256=capture.sha256,
        )

    def bar(symbol, exchange="TWSE"):
        return sources.BarRecord(
            symbol=symbol,
            trading_date=day,
            open=10,
            high=11,
            low=9,
            close=10.5,
            volume=1000,
            turnover=10500,
            exchange=exchange,
            source="twse_index" if symbol == "TAIEX" else exchange.lower(),
            data_as_of=day.isoformat(),
            payload_sha256=capture.sha256,
            turnover_status="available",
        )

    return sources.OfficialBatch(
        instruments=[
            sources.InstrumentRecord(
                "TAIEX", "TAIEX", exchange="TWSE", instrument_type="index"
            ),
            # newlisting row of a company that has left the master
            record("8427", "ipo"),
            # listed in 2011, so "recent" against an old session
            record("6505", "ipo"),
            record("1339", "stock"),
            record("1589", "stock"),
            record("8047", "ipo", exchange="TPEx"),
            # not stored yet: a new instrument
            record("9999", "ipo"),
        ],
        bars=[bar("TAIEX"), bar("6505"), bar("9999")],
        payloads=[capture],
        data_as_of=day.isoformat(),
        snapshot_feeds=False,
    )


STORED = {
    ("TWSE", "8427"): ("ipo", "delisted"),
    ("TWSE", "6505"): ("stock", "active"),
    ("TWSE", "1339"): ("ipo", "active"),
    ("TWSE", "1589"): ("ipo", "dormant"),
    ("TPEx", "8047"): ("stock", "transferred"),
}


def _seed(factory) -> None:
    with factory() as db:
        for (exchange, symbol), (instrument_type, status) in STORED.items():
            db.add(
                Instrument(
                    market="TW",
                    exchange=exchange,
                    symbol=symbol,
                    name=f"{symbol} stored",
                    instrument_type=instrument_type,
                    status=status,
                )
            )
        db.commit()


def _state(factory) -> dict[tuple[str, str], tuple[str, str]]:
    with factory() as db:
        return {
            (item.exchange, item.symbol): (item.instrument_type, item.status)
            for item in db.scalars(select(Instrument)).all()
            if item.symbol != "TAIEX"
        }


def test_old_session_keeps_stored_types_and_statuses_and_creates_new_ones(
    pipeline_env,
):
    _seed(pipeline_env)

    result = pipeline.collect(OLD_SESSION, adapter=FakeAdapter(_batch(OLD_SESSION)))

    assert result["status"] == "success"
    assert _state(pipeline_env) == {
        **STORED,
        # a new instrument still takes the record's values
        ("TWSE", "9999"): ("ipo", "active"),
    }
    with pipeline_env() as db:
        # the session's quotes are written as before
        assert set(
            db.scalars(
                select(Instrument.symbol)
                .join(MarketBar, MarketBar.instrument_id == Instrument.id)
                .where(MarketBar.trading_date == OLD_SESSION)
            )
        ) == {"TAIEX", "6505", "9999"}
        # the other official fields are still refreshed
        assert (
            db.scalar(select(Instrument).where(Instrument.symbol == "6505")).name
            == "6505 official"
        )


def test_todays_session_rewrites_types_and_statuses_as_before(pipeline_env):
    _seed(pipeline_env)

    result = pipeline.collect(TODAY, adapter=FakeAdapter(_batch(TODAY)))

    assert result["status"] == "success"
    assert _state(pipeline_env) == {
        ("TWSE", "8427"): ("ipo", "active"),
        ("TWSE", "6505"): ("ipo", "active"),
        ("TWSE", "1339"): ("stock", "active"),
        # dormant ends only when a quote row returns
        ("TWSE", "1589"): ("stock", "dormant"),
        ("TPEx", "8047"): ("ipo", "active"),
        ("TWSE", "9999"): ("ipo", "active"),
    }


@pytest.mark.parametrize(
    ("score_date", "current"),
    [
        (date(2026, 11, 17), True),  # today
        (date(2026, 11, 16), False),  # yesterday: a catch-up or re-run
        (date(2004, 2, 11), False),
    ],
)
def test_lists_are_current_only_for_todays_session(pipeline_env, score_date, current):
    assert pipeline.lists_are_current(score_date) is current


def test_on_a_weekend_the_last_weekday_is_current(monkeypatch):
    monkeypatch.setattr(pipeline, "taipei_today", lambda: date(2026, 11, 22))  # Sun
    assert pipeline.lists_are_current(date(2026, 11, 20))  # Friday
    assert pipeline.lists_are_current(date(2026, 11, 21))  # a weekend session
    assert not pipeline.lists_are_current(date(2026, 11, 19))
