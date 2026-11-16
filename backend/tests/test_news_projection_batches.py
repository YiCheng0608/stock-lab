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

import gc
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


def _seed(db, duplicate_key=False):
    """Instruments in a verified industry, their Events, part already projected.

    Every company Event has its own instrument, so the instrument and
    membership queries also exceed 999 ids.  The first 300 Events are
    projected before the full projection; of those, every tenth then gets a
    new description and every fiftieth item was marked duplicate by an
    operator, so the full projection inserts, updates, keeps and does not
    reactivate.  ``duplicate_key`` adds two market Events, far apart in id,
    that share a canonical key (a NULL instrument_id is not unique), so one
    NewsItem is written by two segments.
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
    if duplicate_key:
        shared = dict(
            instrument_id=None,
            event_date=DAY,
            event_type="suspension",
            title="shared",
            source="twse_suspension",
            collected_at=COLLECTED,
        )
        events.insert(310, Event(description="first", **shared))
        events.append(Event(description="last", **shared))
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


def _as_before_791(patch):
    """One query per IN list and every Event at once, as before #791.

    raising=False: the code before #791 has neither size to patch.
    """

    patch.setattr(news, "_IN_BATCH_SIZE", 10**9, raising=False)
    patch.setattr(news, "_EVENT_SEGMENT_SIZE", 10**9, raising=False)


def _small_segments(patch):
    """Batch and segment edges anywhere: 7 divides none of the counts."""

    patch.setattr(news, "_IN_BATCH_SIZE", 7, raising=False)
    patch.setattr(news, "_EVENT_SEGMENT_SIZE", 7, raising=False)


def _projected(path, monkeypatch, sizes, duplicate_key=False):
    engine, factory = _factory(path)
    with factory() as db:
        _seed(db, duplicate_key)
    with monkeypatch.context() as patch:
        sizes(patch)
        changed = _full_projection(factory)
    items = _items(factory)
    engine.dispose()
    return changed, items


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

    return _projected(tmp_path / "single.db", monkeypatch, _as_before_791)


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


def test_small_batches_and_segments_project_what_one_query_projected(
    tmp_path, monkeypatch, single_query
):
    assert (
        _projected(tmp_path / "small.db", monkeypatch, _small_segments) == single_query
    )


def test_a_canonical_key_shared_across_segments_projects_as_one_pass(
    tmp_path, monkeypatch
):
    expected = _projected(
        tmp_path / "single.db", monkeypatch, _as_before_791, duplicate_key=True
    )

    segmented = _projected(
        tmp_path / "small.db", monkeypatch, _small_segments, duplicate_key=True
    )

    assert segmented == expected
    changed, items = segmented
    # The second Event of the shared key rewrites the item the first inserted.
    assert changed == INSTRUMENTS + MARKET_EVENTS + 2 - 300 + 30
    assert len(items) == INSTRUMENTS + MARKET_EVENTS + 1


def test_a_full_projection_holds_one_segment_of_events_at_a_time(tmp_path, monkeypatch):
    """The memory bound: earlier segments are released, not kept loaded.

    The session's identity map holds clean rows weakly, so what it still has
    when a segment starts is what the projection keeps referencing.
    """

    engine, factory = _factory(tmp_path / "held.db")
    with factory() as db:
        _seed(db)
    monkeypatch.setattr(news, "_EVENT_SEGMENT_SIZE", 100)
    held: list[tuple[int, int]] = []
    real = news._project_events

    def counted(db, events):
        gc.collect()
        kinds = [type(obj) for obj in db.identity_map.values()]
        held.append((kinds.count(Event), kinds.count(NewsItem)))
        return real(db, events)

    monkeypatch.setattr(news, "_project_events", counted)
    with factory() as db:
        news.project_news(db)
    engine.dispose()

    assert len(held) == 12  # 1160 Events in segments of 100
    assert max(events for events, _ in held) <= 100
    assert max(items for _, items in held) == 0
