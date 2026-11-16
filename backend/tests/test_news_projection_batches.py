"""A full news projection queries its IN lists in batches (Issue #791).

``sync_news_from_events`` used to bind every instrument id and every
canonical key of a full projection in one ``IN``.  The research database has
about 690,000 Events, more than SQLite's 32766 bound variables, and its full
projection failed with ``too many SQL variables``.  Here the connection limit
is lowered to 999 (SQLite before 3.32) and the fixture has more instruments
and Events than that, so the single-query version fails and the batched one
must write what the single query wrote.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app.news as news
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Event, GroupMembership, Instrument, NewsItem, ThemeGroup
from app.taxonomy import canonical_group_id

INSTRUMENTS = 1100
MARKET_EVENTS = 60
DAY = date(2026, 11, 2)
COLLECTED = datetime(2026, 11, 2, 18, 0)
CEMENT = canonical_group_id("industry", "Cement")


def _factory(path, variable_limit=None):
    engine = create_engine(f"sqlite:///{path}")
    enable_sqlite_foreign_keys(engine)
    if variable_limit is not None:

        @event.listens_for(engine, "connect")
        def _limit(dbapi_connection, _record):
            dbapi_connection.setlimit(
                sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, variable_limit
            )

    upgrade_database(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed(db):
    """Instruments in a verified industry, their Events, part already projected.

    Every company Event has its own instrument, so the instrument and
    membership queries also exceed 999 ids.  The first 300 Events are
    projected before the full projection; of those, every tenth then gets a
    new description and every fiftieth item was marked duplicate by an
    operator, so the full projection inserts, updates, keeps and does not
    reactivate.
    """

    db.add_all(
        [
            ThemeGroup(
                id=CEMENT,
                name="Industry · Cement",
                group_type="official_industry",
                active=True,
                display_name_zh="水泥",
                name_status="official",
            ),
            ThemeGroup(
                id="inactive-group",
                name="old",
                group_type="official_industry",
                active=False,
                display_name_zh="舊",
                name_status="official",
            ),
        ]
    )
    instruments = [
        Instrument(
            market="TW",
            exchange="TWSE",
            symbol=str(1000 + index),
            name=f"I{index}",
            instrument_type="stock",
            industry="01",
            status="active",
        )
        for index in range(INSTRUMENTS)
    ]
    db.add_all(instruments)
    db.flush()
    for index, instrument in enumerate(instruments):
        db.add(
            GroupMembership(
                group_id=CEMENT,
                instrument_id=instrument.id,
                valid_from=date(2020, 1, 1),
                # A membership that ended before the Event: no theme.
                valid_to=date(2026, 1, 1) if index % 7 == 0 else None,
                source="official_industry exchange=TWSE",
            )
        )
        db.add(
            GroupMembership(
                group_id="inactive-group",
                instrument_id=instrument.id,
                valid_from=date(2020, 1, 1),
                source="official_industry exchange=TWSE",
            )
        )
    events = [
        Event(
            instrument_id=instrument.id,
            event_date=DAY - timedelta(days=index % 30),
            event_type="material",
            title=f"company {index}",
            description=f"text {index}",
            source="mops_material_information",
            collected_at=COLLECTED,
        )
        for index, instrument in enumerate(instruments)
    ] + [
        Event(
            instrument_id=None,
            event_date=DAY,
            event_type="suspension",
            title=f"market {index}",
            description=None,
            source="twse_suspension",
            collected_at=COLLECTED,
        )
        for index in range(MARKET_EVENTS)
    ]
    db.add_all(events)
    db.flush()
    news.sync_news_from_events(db, events[:300])
    for index, item in enumerate(
        db.scalars(select(NewsItem).order_by(NewsItem.event_id)).all()
    ):
        if index % 50 == 0:
            item.status = "duplicate"
    for index, row in enumerate(events[:300]):
        if index % 10 == 0:
            row.description = f"corrected {index}"
    db.commit()


def _items(factory):
    with factory() as db:
        return [
            tuple(row)
            for row in db.execute(text("SELECT * FROM news_items ORDER BY id"))
        ]


def _full_projection(factory):
    with factory() as db:
        changed = news.project_news(db)
        db.commit()
    return changed


@pytest.fixture
def limited(tmp_path):
    engine, factory = _factory(tmp_path / "limited.db", variable_limit=999)
    with factory() as db:
        _seed(db)
    yield factory
    engine.dispose()


@pytest.fixture
def single_query(tmp_path, monkeypatch):
    """The same database projected as before #791: one query per IN list."""

    engine, factory = _factory(tmp_path / "single.db")
    with factory() as db:
        _seed(db)
    with monkeypatch.context() as patch:
        # raising=False: the code before #791 has no batch size to patch.
        patch.setattr(news, "_IN_BATCH_SIZE", 10**9, raising=False)
        changed = _full_projection(factory)
    yield changed, _items(factory)
    engine.dispose()


def test_the_fixture_exceeds_the_lowered_variable_limit(limited):
    keys = list(range(1000))
    with limited() as db:
        with pytest.raises(OperationalError, match="too many SQL variables"):
            db.scalars(select(Instrument).where(Instrument.id.in_(keys))).all()


def test_a_full_projection_over_the_limit_writes_what_one_query_wrote(
    limited, single_query
):
    expected_changed, expected_items = single_query

    changed = _full_projection(limited)

    assert changed == expected_changed
    # Inserted: the 1100 + 60 - 300 unprojected Events; updated: the 30
    # corrected ones.
    assert changed == INSTRUMENTS + MARKET_EVENTS - 300 + 30
    assert _items(limited) == expected_items
    with limited() as db:
        items = db.scalars(select(NewsItem)).all()
        assert len(items) == INSTRUMENTS + MARKET_EVENTS
        assert sum(item.status == "duplicate" for item in items) == 6
        assert sum(item.theme_ids_json == [CEMENT] for item in items) == sum(
            index % 7 != 0 for index in range(INSTRUMENTS)
        )


def test_a_second_full_projection_over_the_limit_changes_nothing(limited):
    _full_projection(limited)
    before = _items(limited)

    assert _full_projection(limited) == 0
    assert _items(limited) == before


def test_small_batches_project_what_one_query_projected(
    tmp_path, monkeypatch, single_query
):
    """Batch edges anywhere (7 does not divide the counts) change nothing."""

    expected_changed, expected_items = single_query
    engine, factory = _factory(tmp_path / "small.db")
    with factory() as db:
        _seed(db)
    monkeypatch.setattr(news, "_IN_BATCH_SIZE", 7, raising=False)

    assert _full_projection(factory) == expected_changed
    assert _items(factory) == expected_items
    engine.dispose()
