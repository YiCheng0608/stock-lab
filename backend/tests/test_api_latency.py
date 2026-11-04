"""Bounded reads behind the #462 API latency work.

On the production copy these reads hydrated whole histories to keep a few rows:
every bar and chip of the coverage window, every group score, every chip and
data-quality row of an action page, and every run's metadata. Each test pins a
read to the rows it keeps (counted with the ORM ``load`` event or the SQL it
sends) and to the values those rows give, so a regression to the whole-history
read fails here. The responses themselves were compared on the production copy
before and after (PR of #462).
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, create_engine, desc, event, select, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app import decision, decision_market_reads, migrations
from app.db import Base, enable_sqlite_foreign_keys
from app.decision_market_reads import (
    _project,
    load_decision_market_reads,
    read_market_date,
)
from app.main import app
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    DataQuality,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    ThemeGroup,
)
from worker import backfill

D0 = date(2026, 10, 1)


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'latency.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with make() as session:
        yield session


@pytest.fixture
def client(engine, monkeypatch):
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with make() as session:
            yield session

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client
    app.dependency_overrides.pop(api_module.get_db, None)


@contextmanager
def orm_loads():
    """Count ORM rows hydrated per model class while the block runs."""

    counts: Counter[str] = Counter()

    def on_load(target, _context):
        counts[type(target).__name__] += 1

    event.listen(Base, "load", on_load, propagate=True)
    try:
        yield counts
    finally:
        event.remove(Base, "load", on_load)


@contextmanager
def statements(engine):
    sent: list[str] = []

    def before(_conn, _cursor, statement, _params, _context, _many):
        sent.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield sent
    finally:
        event.remove(engine, "before_cursor_execute", before)


def instrument(db, symbol, *, kind="stock", exchange="TWSE", status="active"):
    row = Instrument(
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def bar(db, item, day, *, source="twse_fixture"):
    db.add(
        MarketBar(
            instrument_id=item.id,
            trading_date=day,
            open=10,
            high=10,
            low=10,
            close=10,
            adj_close=10,
            source=source,
        )
    )


def chip(db, item, day):
    db.add(ChipSnapshot(instrument_id=item.id, trading_date=day, foreign_buy=1.0))


def plan(db, compiled_sql):
    return " | ".join(
        str(row[-1])
        for row in db.connection().exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled_sql}")
    )


# ---- group scores: one row per group ----


def test_latest_scores_load_only_each_groups_newest_row(db):
    for group_id in ("G1", "G2"):
        db.add(ThemeGroup(id=group_id, name=group_id))
    db.flush()
    days = [D0 + timedelta(days=offset) for offset in range(3)]
    for day in days:
        db.add(GroupDailyScore(group_id="G1", trading_date=day, score=day.day))
    for day in days[:2]:
        db.add(GroupDailyScore(group_id="G2", trading_date=day, score=day.day))
    db.commit()
    db.expunge_all()

    with orm_loads() as loads:
        latest = api_module.latest_scores(db)
    assert {key: row.trading_date for key, row in latest.items()} == {
        "G1": days[2],
        "G2": days[1],
    }
    # The dict keeps the former order: trading_date desc, then id desc.
    assert list(latest) == ["G1", "G2"]
    assert loads["GroupDailyScore"] == 2

    db.expunge_all()
    with orm_loads() as loads:
        scoped = api_module.scores_as_of(db, days[1])
    assert {key: row.trading_date for key, row in scoped.items()} == {
        "G1": days[1],
        "G2": days[1],
    }
    # Same date: the higher id (G2's row, written later) first.
    assert list(scoped) == ["G2", "G1"]
    assert loads["GroupDailyScore"] == 2
    assert api_module.scores_as_of(db, None) == {}


# ---- decision context: newest 120 chips, newest quality row ----


def test_decision_context_loads_the_newest_chips_and_quality_row_only(db):
    item = instrument(db, "1101")
    other = instrument(db, "1102")
    days = [D0 + timedelta(days=offset) for offset in range(130)]
    for day in days:
        chip(db, item, day)
    chip(db, other, days[0])
    key = f"{item.exchange}:{item.symbol}"
    for day in (days[10], days[50], days[129]):
        db.add(DataQuality(entity_type="instrument", entity_key=key, as_of_date=day))
    db.add(DataQuality(entity_type="market", entity_key=key, as_of_date=days[60]))
    db.add(ThemeGroup(id="G1", name="G1"))
    db.flush()
    db.add(GroupMembership(group_id="G1", instrument_id=item.id, valid_from=days[0]))
    for day in (days[100], days[127], days[129]):
        db.add(GroupDailyScore(group_id="G1", trading_date=day, score=day.day))
    db.commit()
    db.expunge_all()
    as_of = days[128]

    with orm_loads() as loads:
        context = decision._prepare_decision_context(db, as_of, [item.id, other.id])

    # The group's newest score on or before the cutoff, and only that one.
    [(group, score, membership)] = context["groups_by_instrument"][item.id]
    assert (group.id, score.trading_date, membership.instrument_id) == (
        "G1",
        days[127],
        item.id,
    )
    assert loads["GroupDailyScore"] == 1

    chips = context["chips_by_instrument"][item.id]
    assert [row.trading_date for row in chips] == list(reversed(days[9:129]))
    assert [row.trading_date for row in context["chips_by_instrument"][other.id]] == [
        days[0]
    ]
    assert context["quality_by_key"][key].as_of_date == days[50]
    assert loads["ChipSnapshot"] == 120 + 1
    assert loads["DataQuality"] == 1


# ---- decision market reads: the same rows as the Python window ----


def reference_reads(db, instrument_ids, as_of, *, limit=120):
    """load_decision_market_reads before #462: every bar, windowed in Python."""

    ids = set(instrument_ids)
    query = text(
        "SELECT id, instrument_id, trading_date, close, adj_close, source, "
        "is_suspended, raw_payload_id FROM market_bars WHERE instrument_id IN :ids "
        "ORDER BY instrument_id, trading_date DESC, id DESC"
    ).bindparams(bindparam("ids", expanding=True))
    candidates = {item_id: [] for item_id in ids}
    unlocated = {}
    for row in db.execute(query, {"ids": sorted(ids)}).mappings():
        trading_date = read_market_date(row["trading_date"])
        if trading_date is None:
            unlocated.setdefault(row["instrument_id"], _project(row))
        elif as_of is not None and trading_date > as_of:
            continue
        rows = candidates[row["instrument_id"]]
        if len(rows) < limit:
            rows.append(row)
    return {
        item_id: [_project(row) for row in rows] for item_id, rows in candidates.items()
    }, unlocated


MALFORMED = [
    "2026-02-30",
    "2026/01/05",
    "0000-01-01",
    "",
    "2026-13-01",
    "9999-99-99",
    "2026-04-31",
]


@pytest.fixture
def bars(db):
    item = instrument(db, "2330")
    late = instrument(db, "2317")
    for offset in range(200):
        bar(db, item, D0 - timedelta(days=offset))
    for offset in range(5):
        bar(db, late, D0 - timedelta(days=offset))
    db.commit()
    ids = db.scalars(
        select(MarketBar.id)
        .where(MarketBar.instrument_id == item.id)
        .order_by(MarketBar.trading_date)
    ).all()
    # Malformed stored dates, spread so that some sort inside and some outside
    # the window; one numeric (not text) value as well.
    for row_id, value in zip(ids[::30], MALFORMED):
        db.execute(
            text("UPDATE market_bars SET trading_date = :value WHERE id = :id"),
            {"value": value, "id": row_id},
        )
    db.execute(
        text("UPDATE market_bars SET trading_date = 20260101 WHERE id = :id"),
        {"id": ids[1]},
    )
    db.commit()
    return item, late


@pytest.mark.parametrize("as_of", [None, D0 - timedelta(days=50), D0, date(1999, 1, 1)])
@pytest.mark.parametrize("limit", [0, 1, 20, 120, 500])
def test_market_reads_keep_the_rows_of_the_python_window(db, bars, as_of, limit):
    ids = [item.id for item in bars] + [999]
    assert load_decision_market_reads(db, ids, as_of, limit=limit) == reference_reads(
        db, ids, as_of, limit=limit
    )


def test_market_reads_do_not_walk_every_bar(db, bars, monkeypatch):
    seen = []
    original = decision_market_reads.read_market_date

    def counting(value):
        seen.append(value)
        return original(value)

    monkeypatch.setattr(decision_market_reads, "read_market_date", counting)
    item, _late = bars
    rows, unlocated = load_decision_market_reads(db, [item.id], D0, limit=20)
    assert len(rows[item.id]) == 20
    assert item.id in unlocated
    # The loop and the projection read each kept row once, plus the malformed
    # rows outside the window; the old loop read all 200 rows first.
    assert len(seen) <= 2 * (20 + len(MALFORMED) + 1) < 200


# ---- coverage report: two columns of bars and chips, two metadata values ----


def test_coverage_report_counts_without_hydrating_bars_chips_or_metadata(db):
    stock = instrument(db, "1101")
    gone = instrument(db, "1102", status="delisted")
    otc = instrument(db, "6488", exchange="TPEx")
    taiex = instrument(db, "TAIEX", kind="index")
    days = [D0 + timedelta(days=offset) for offset in range(6)]  # Thu..Tue
    weekdays = [day for day in days if day.weekday() < 5]
    for day in weekdays[:3]:
        bar(db, taiex, day)
        bar(db, stock, day)
        chip(db, stock, day)
    bar(db, gone, weekdays[0])
    bar(db, otc, weekdays[1])
    db.add(
        IngestionRun(
            run_type="collect",
            source="official",
            run_date=weekdays[0],
            status="success",
            data_as_of=weekdays[0].isoformat(),
            metadata_json={
                "event_coverage": {"verified_dates": [weekdays[0].isoformat()]},
                "unrelated": "x" * 10_000,
            },
        )
    )
    db.add(
        IngestionRun(
            run_type="backfill",
            source="official",
            run_date=weekdays[1],
            status="success",
            metadata_json={
                "coverage_manifest": {
                    weekdays[1].isoformat(): {
                        "event_coverage": {"empty_dates": [weekdays[1].isoformat()]}
                    }
                },
                "event_coverage": {"verified_dates": [weekdays[2].isoformat()]},
            },
        )
    )
    db.commit()
    db.expunge_all()

    with orm_loads() as loads:
        report = backfill.coverage_report(db, days[0], days[-1])

    assert not {"MarketBar", "ChipSnapshot", "IngestionRun"} & set(loads)
    by_day = {item["date"]: item for item in report["date_coverage"]}
    first, second, third, fourth = (by_day[day.isoformat()] for day in weekdays)
    assert first["bars"] == {"TWSE": 2} and first["chips"] == {"TWSE": 1}
    assert first["taiex_rows"] == 1 and first["status"] == "success"
    assert second["bars"] == {"TPEx": 1, "TWSE": 2}
    assert fourth["status"] == "stale" and fourth["received"] is False
    # Collect metadata covers its data date; a backfill's own event_coverage
    # is not read, only its per-day manifest.
    assert first["event_coverage_status"] == "success"
    assert second["event_coverage_status"] == "verified_empty"
    assert third["event_coverage_status"] == "unqueried"
    assert report["session_count"] == 3
    stock_row = next(
        row for row in report["instrument_coverage"] if row["symbol"] == "1101"
    )
    assert stock_row["bars_total"] == 3 and stock_row["chips_total"] == 3
    assert {row["symbol"] for row in report["instrument_coverage"]} == {
        "1101",
        "6488",
    }


@pytest.mark.parametrize("path", ["sqlite", "forced_fallback"])
def test_coverage_reads_event_coverage_from_metadata_with_nan(db, monkeypatch, path):
    """json.dumps writes NaN; SQLite without JSON5 (< 3.42) rejects it as malformed.

    Either SQLite extracts the value or the whole-row Python read takes over,
    with the same report, and a caller's uncommitted write survives the
    failed SELECT (the backfill worker calls coverage_report mid-transaction).
    """

    taiex = instrument(db, "TAIEX", kind="index")
    bar(db, taiex, D0)
    db.add(
        IngestionRun(
            run_type="collect",
            source="official",
            run_date=D0,
            status="success",
            data_as_of=D0.isoformat(),
            metadata_json={
                "ratio": float("nan"),
                "event_coverage": {"verified_dates": [D0.isoformat()]},
            },
        )
    )
    db.commit()
    stored = db.execute(text("SELECT metadata_json FROM ingestion_runs")).scalar()
    assert "NaN" in stored
    if path == "forced_fallback":
        # Any SQLite version: a SELECT that fails the way malformed JSON does.
        monkeypatch.setattr(
            backfill, "_event_manifest_query", lambda: text("SELECT json('{')")
        )
    pending = instrument(db, "9999")

    report = backfill.coverage_report(db, D0, D0)

    assert report["date_coverage"][0]["event_coverage_status"] == "success"
    db.commit()
    db.expunge_all()
    assert db.get(Instrument, pending.id).symbol == "9999"


# ---- ingestion runs: metadata only on request; the latest run without it ----


def add_run(db, *, day, metadata, run_type="collect", status="success"):
    run = IngestionRun(
        run_type=run_type,
        source="official",
        run_date=day,
        status=status,
        data_as_of=day.isoformat(),
        metadata_json=metadata,
        started_at=datetime(2026, 10, 1, 10),
        finished_at=datetime(2026, 10, 1, 11),
        updated_at=datetime(2026, 10, day.day, 12),
    )
    db.add(run)
    db.commit()
    return run


def test_the_run_list_leaves_metadata_out_unless_asked(db, engine, client):
    add_run(db, day=D0, metadata={"big": "x" * 5000})
    add_run(db, day=D0 + timedelta(days=1), metadata={"n": 1})

    with statements(engine) as sent:
        listed = client.get("/api/ingestion-runs").json()["items"]
    assert [item["run_date"] for item in listed] == ["2026-10-02", "2026-10-01"]
    assert all("metadata" not in item for item in listed)
    # The page's row query does not read the column (the count query's
    # subquery names it, but count(*) reads no column).
    page_queries = [sql for sql in sent if "LIMIT" in sql]
    assert page_queries and not [sql for sql in page_queries if "metadata_json" in sql]

    full = client.get("/api/ingestion-runs?include_metadata=true").json()["items"]
    assert [item["metadata"] for item in full] == [{"n": 1}, {"big": "x" * 5000}]
    # The key keeps its former position.
    assert list(full[0]) == [
        "id",
        "run_type",
        "source",
        "run_date",
        "status",
        "records",
        "error",
        "request_key",
        "data_as_of",
        "metadata",
        "started_at",
        "finished_at",
        "updated_at",
    ]


def test_the_latest_official_run_is_read_without_its_metadata(db):
    add_run(db, day=D0, metadata={"old": True})
    newest = add_run(db, day=D0 + timedelta(days=1), metadata={"big": "x" * 5000})
    add_run(db, day=D0 + timedelta(days=2), metadata={}, status="failed")
    db.expunge_all()

    run = decision.latest_official_run(db)
    assert run.id == newest.id
    assert "metadata_json" not in run.__dict__
    # Still readable when a caller asks for it.
    assert run.metadata_json == {"big": "x" * 5000}


# ---- migration 0024: the two ingestion_runs indexes and their use ----


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_the_upgrade_adds_the_ingestion_run_indexes(tmp_path, monkeypatch, entry):
    if entry == "alembic":
        pytest.importorskip("alembic")
    path = tmp_path / f"{entry}.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    if entry == "fallback":
        monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    try:
        upgrade_database(engine)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as connection:
        columns = {
            name: [row[2] for row in connection.execute(f"PRAGMA index_info('{name}')")]
            for name in ("ix_ingestion_runs_latest", "ix_ingestion_runs_updated_at")
        }
        version = (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if entry == "alembic"
            else connection.execute(
                "SELECT version FROM schema_migrations WHERE version = "
                "'0024_ingestion_run_indexes'"
            ).fetchall()
        )
    assert columns == {
        "ix_ingestion_runs_latest": ["run_type", "source", "status", "updated_at"],
        "ix_ingestion_runs_updated_at": ["updated_at"],
    }
    assert version == [("0024_ingestion_run_indexes",)]


def test_run_orderings_use_the_indexes_not_a_sort_of_whole_rows(db):
    latest = (
        select(IngestionRun.id)
        .where(
            IngestionRun.run_type == "collect",
            IngestionRun.source == "official",
            IngestionRun.status == "success",
            IngestionRun.data_as_of.is_not(None),
        )
        .order_by(desc(IngestionRun.updated_at), desc(IngestionRun.id))
        .limit(1)
    )
    listed = (
        select(IngestionRun.id)
        .order_by(desc(IngestionRun.updated_at), desc(IngestionRun.id))
        .limit(20)
    )
    for query, index in (
        (latest, "ix_ingestion_runs_latest"),
        (listed, "ix_ingestion_runs_updated_at"),
    ):
        compiled = query.compile(
            dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
        )
        found = plan(db, compiled)
        assert index in found and "TEMP B-TREE" not in found, found
