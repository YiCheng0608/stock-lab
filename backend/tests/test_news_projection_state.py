"""The news GETs project the official events only when their inputs changed (#476).

The worker projects before committing what it writes (collect, the MOPS event
backfill, the theme table, the industry repair, ``news-project``) and stores
the fingerprint it ran against; ``/api/dashboard``, ``/api/news`` and
``/api/news/{id}`` compare it with the database and project only on a
difference: a new event, an event corrected in place (through the ORM, or by
Core or raw SQL without ``updated_at``), a membership change, or a bump of
``NEWS_PROJECTION_VERSION``.

``app.news`` is reached through ``news()`` so that, on code without the
fingerprint, every test fails on its own.
"""

import importlib
import socket
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
import worker.industry_repair as industry_repair
import worker.instrument_repair as instrument_repair
import worker.mops_events as mops_events
import worker.pipeline as pipeline
import worker.sources as sources
import worker.themes as themes
from app.main import app
from app.models import Event, GroupMembership, Instrument, NewsItem, ThemeGroup
from test_mops_event_list import (
    DAY,
    NOW,
    CollectFetcher,
    ListFetcher,
    _combined,
    _instruments,
    row,
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """As test_mops_event_list: no network, raw under tmp, a fixed MOPS clock."""

    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in news projection tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(mops_events, "utcnow", lambda: NOW.replace(tzinfo=None))


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield factory
    engine.dispose()


GETS = ["/api/dashboard", "/api/news"]


def news():
    return importlib.import_module("app.news")


@pytest.fixture
def client(database, monkeypatch):
    def override_get_db():
        with database() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(api_module.get_db, None)


@pytest.fixture
def projections(monkeypatch):
    """Count the full projections, wherever they are called from."""

    module = news()
    calls: list[int] = []
    real = module.sync_news_from_events

    def counted(db, events=None):
        calls.append(1)
        return real(db, events)

    monkeypatch.setattr(module, "sync_news_from_events", counted)
    return calls


def _event(db, title="first", description="text", day=DAY):
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == "1101"))
    event = Event(
        instrument_id=instrument.id,
        event_date=day,
        event_type="material",
        title=title,
        description=description,
        source="mops_material_information",
    )
    db.add(event)
    db.flush()
    return event


def _seeded(database):
    with database() as db:
        _instruments(db)
        _event(db)
        news().project_news(db)
        db.commit()


def _summaries(database):
    with database() as db:
        return {item.title: item.summary for item in db.scalars(select(NewsItem))}


@pytest.mark.parametrize("path", GETS)
def test_an_unchanged_database_is_not_projected_again(
    database, client, projections, path
):
    _seeded(database)
    projections.clear()
    for _ in range(3):
        assert client.get(path).status_code == 200
    assert projections == []
    with database() as db:
        item = db.scalar(select(NewsItem))
    assert client.get(f"/api/news/{item.id}").status_code == 200
    assert projections == []


def test_without_a_stored_fingerprint_the_first_get_projects_once(
    database, client, projections
):
    with database() as db:
        _instruments(db)
        _event(db)
        db.commit()
    for path in GETS:
        assert client.get(path).status_code == 200
    assert projections == [1]
    assert _summaries(database) == {"first": "text"}


def test_a_new_event_is_projected_by_the_next_get(database, client, projections):
    _seeded(database)
    with database() as db:
        _event(db, title="second", description="more")
        db.commit()
    projections.clear()
    assert client.get("/api/dashboard").status_code == 200
    assert projections == [1]
    assert _summaries(database) == {"first": "text", "second": "more"}
    client.get("/api/news")
    assert projections == [1]


def test_an_orm_correction_with_the_same_collected_at_is_projected(
    database, client, projections, ticking_utcnow
):
    _seeded(database)
    with database() as db:
        event = db.scalar(select(Event))
        collected_at = event.collected_at
        # The same length, the same collected_at: only updated_at moves.
        event.description = "TEXT"
        db.commit()
        assert db.scalar(select(Event)).collected_at == collected_at
    projections.clear()
    client.get("/api/news")
    assert projections == [1]
    assert _summaries(database) == {"first": "TEXT"}


@pytest.mark.parametrize(
    "statement",
    [
        # Core, without updated_at: the content totals change.
        lambda: update(Event).values(description="a longer corrected text"),
        lambda: update(Event).values(details_json={"published_at": "2026-09-04"}),
        # Raw SQL keeping the length, but setting updated_at as a writer must.
        lambda: text(
            "UPDATE events SET description = 'TEXT', "
            "updated_at = '2026-09-05 00:00:00.000000'"
        ),
    ],
    ids=["core_description", "core_details", "raw_sql_with_updated_at"],
)
def test_a_non_orm_correction_is_projected(database, client, projections, statement):
    _seeded(database)
    with database() as db:
        db.execute(statement())
        db.commit()
    projections.clear()
    client.get("/api/dashboard")
    assert projections == [1]
    with database() as db:
        event = db.scalar(select(Event))
        item = db.scalar(select(NewsItem))
        assert item.summary == event.description


def test_a_membership_change_is_projected(database, client, projections):
    _seeded(database)
    with database() as db:
        db.add(ThemeGroup(id="g", name="g", active=True))
        db.flush()
        db.add(
            GroupMembership(
                group_id="g",
                instrument_id=db.scalar(
                    select(Instrument.id).where(Instrument.symbol == "1101")
                ),
                valid_from=date(2020, 1, 1),
                source="official exchange=TWSE",
            )
        )
        db.commit()
    projections.clear()
    client.get("/api/news")
    assert projections == [1]
    with database() as db:
        membership = db.scalar(select(GroupMembership))
        membership.valid_to = DAY - timedelta(days=1)
        db.commit()
    client.get("/api/news")
    assert projections == [1, 1]


def test_a_rule_version_bump_is_projected_once(
    database, client, projections, monkeypatch
):
    _seeded(database)
    monkeypatch.setattr(
        news(), "NEWS_PROJECTION_VERSION", news().NEWS_PROJECTION_VERSION + "-next"
    )
    projections.clear()
    client.get("/api/dashboard")
    client.get("/api/news")
    assert projections == [1]


def test_watchlist_and_name_changes_do_not_project(database, client, projections):
    _seeded(database)
    with database() as db:
        db.execute(update(Instrument).values(is_watchlisted=True, name="Renamed"))
        db.commit()
    projections.clear()
    client.get("/api/news")
    assert projections == []


def _current(database):
    """The stored fingerprint matches the database: no GET would project."""

    with database() as db:
        return news().ensure_news_projection(db) is False


@pytest.mark.parametrize("snapshot_feeds", [True, False])
def test_collect_projects_before_its_commit(database, snapshot_feeds):
    mops = ListFetcher({DAY: [row(DAY, "09:00:00", "1101", "listed news")]})
    result = pipeline.collect(
        DAY, adapter=_combined(CollectFetcher(mops), snapshot_feeds=snapshot_feeds)
    )
    assert result["status"] == "success", result
    with database() as db:
        titles = {item.title for item in db.scalars(select(NewsItem))}
    # A historical batch (catch-up, backfill) projects as well (#476).
    assert "listed news" in titles
    assert _current(database)


def test_the_event_backfill_projects_each_date_and_records_the_fingerprint(database):
    monday, tuesday = date(2026, 9, 7), date(2026, 9, 8)
    fetcher = ListFetcher(
        {
            monday: [row(monday, "09:00:00", "1101", "monday news")],
            tuesday: [row(tuesday, "09:00:00", "7001", "tuesday news", market="otc")],
        }
    )
    with database() as db:
        _instruments(db)
        db.commit()
        result = mops_events.backfill_events(
            db, start=monday, end=tuesday, fetcher=fetcher, sleep=lambda _: None
        )
        db.commit()
    assert result["events_written"] == 2
    with database() as db:
        assert {item.title for item in db.scalars(select(NewsItem))} == {
            "monday news",
            "tuesday news",
        }
    assert _current(database)


def test_an_interrupted_backfill_keeps_the_projected_dates(database, monkeypatch):
    monday, tuesday = date(2026, 9, 7), date(2026, 9, 8)
    fetcher = ListFetcher({monday: [row(monday, "09:00:00", "1101", "monday news")]})
    real = mops_events.fetch_date

    def crash_on_tuesday(day, fetch):
        if day == tuesday:
            raise RuntimeError("fixture crash")
        return real(day, fetch)

    monkeypatch.setattr(mops_events, "fetch_date", crash_on_tuesday)
    with database() as db:
        _instruments(db)
        db.commit()
        with pytest.raises(RuntimeError):
            mops_events.backfill_events(
                db, start=monday, end=tuesday, fetcher=fetcher, sleep=lambda _: None
            )
    with database() as db:
        assert [item.title for item in db.scalars(select(NewsItem))] == ["monday news"]


@pytest.mark.parametrize("command", ["themes", "industry_repair", "instrument_repair"])
def test_membership_commands_project_before_their_commit(
    database, monkeypatch, command
):
    order: list[str] = []
    with database() as db:
        _instruments(db)
        db.commit()

    class Session:
        def __init__(self):
            self.db = database()

        def __enter__(self):
            self.db.__enter__()
            real_commit = self.db.commit

            def commit():
                order.append("commit")
                real_commit()

            self.db.commit = commit
            return self.db

        def __exit__(self, *args):
            return self.db.__exit__(*args)

    def project(db):
        order.append("project")
        return news().project_news(db)

    if command == "themes":
        monkeypatch.setattr(themes, "SessionLocal", Session)
        monkeypatch.setattr(themes, "load_theme_table", lambda path: {})
        monkeypatch.setattr(themes, "apply_theme_table", lambda db, t, path: {})
        monkeypatch.setattr(themes, "project_news", project)
        themes.sync_themes("fixture.json")
    elif command == "industry_repair":
        monkeypatch.setattr(industry_repair, "SessionLocal", Session)
        monkeypatch.setattr(
            industry_repair, "repair_industry_memberships", lambda db, apply: {}
        )
        monkeypatch.setattr(industry_repair, "project_news", project)
        industry_repair.run_industry_repair(apply=True)
    else:
        # Its status sync ends memberships (pipeline.apply_instrument_status).
        monkeypatch.setattr(instrument_repair, "SessionLocal", Session)
        monkeypatch.setattr(
            instrument_repair,
            "repair_instruments",
            lambda db, **kwargs: {"status": "applied"},
        )
        monkeypatch.setattr(instrument_repair, "project_news", project)
        instrument_repair.run_instrument_repair(apply=True)
    assert order == ["project", "commit"]
    assert _current(database)


def test_news_project_records_the_fingerprint(database, projections):
    with database() as db:
        _instruments(db)
        _event(db)
        db.commit()
    worker = importlib.import_module("worker.news_projection")
    result = worker.run_news_project()
    assert result["status"] == "success" and result["changed"] == 1
    assert result["version"] == news().NEWS_PROJECTION_VERSION
    assert _current(database)
    assert projections == [1]


def test_a_database_without_events_stays_unwritten_by_the_gets(
    database, client, projections
):
    with database() as db:
        _instruments(db)
        db.commit()
    for path in GETS:
        assert client.get(path).status_code == 200
    assert projections == []
    models = importlib.import_module("app.models")
    with database() as db:
        assert db.scalars(select(models.NewsProjectionState)).all() == []
