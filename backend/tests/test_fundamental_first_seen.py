"""The snapshot feeds keep a quarter's first release date (#529).

``t187ap14_L``／``mopsfin_t187ap14_O`` restamp 出表日期 every time they are
published again; overwriting it hid 2330 115Q2 until 2026-10-30, months after
it was announced.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, enable_sqlite_foreign_keys
from app.models import FundamentalSnapshot, Instrument
from worker import pipeline, sources


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add(
            Instrument(
                market="TW",
                exchange="TWSE",
                symbol="2330",
                name="台積電",
                instrument_type="stock",
                status="active",
            )
        )
        session.flush()
        yield session
    engine.dispose()


def snapshot(released: date | None, eps: float, **details) -> sources.FundamentalRecord:
    return sources.FundamentalRecord(
        symbol="2330",
        period_end=date(2026, 6, 30),
        fiscal_period="Q2",
        announcement_date=released,
        revenue=2_404_483_690.0,
        eps=eps,
        details={"出表日期": f"115{released:%m%d}" if released else "", **details},
    )


def collect(db, record):
    instruments = {(i.exchange, i.symbol): i for i in db.scalars(select(Instrument))}
    pipeline._upsert_fundamental(db, record, instruments, None)
    db.flush()
    (row,) = db.scalars(select(FundamentalSnapshot)).all()
    return row


def test_a_later_snapshot_keeps_the_first_release_date_and_takes_new_values(db):
    collect(db, snapshot(date(2026, 9, 8), 49.3))
    row = collect(db, snapshot(date(2026, 10, 30), 49.33))
    assert (row.announcement_date, row.eps) == (date(2026, 9, 8), 49.33)
    assert row.data_json == {"出表日期": "1151030"}


def test_an_earlier_date_or_a_first_date_replaces_the_stored_one(db):
    assert collect(db, snapshot(None, 49.0)).announcement_date is None
    assert collect(db, snapshot(date(2026, 10, 30), 49.3)).announcement_date == date(
        2026, 10, 30
    )
    assert collect(db, snapshot(date(2026, 9, 8), 49.33)).announcement_date == date(
        2026, 9, 8
    )
    # A missing date never clears a stored one.
    assert collect(db, snapshot(None, 49.33)).announcement_date == date(2026, 9, 8)


def test_the_kept_date_keeps_its_basis(db):
    collect(
        db,
        snapshot(
            date(2026, 8, 14),
            49.33,
            announcement_basis="statutory_deadline",
            statutory_deadline="2026-08-14",
        ),
    )
    row = collect(db, snapshot(date(2026, 11, 5), 49.33))
    assert row.announcement_date == date(2026, 8, 14)
    assert row.data_json == {
        "出表日期": "1151105",
        "announcement_basis": "statutory_deadline",
        "statutory_deadline": "2026-08-14",
    }
