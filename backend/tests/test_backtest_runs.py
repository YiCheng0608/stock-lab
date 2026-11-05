"""Technical backtest runs left ``running`` by a dead process (#484).

A canonical backtest runs only through ``worker.cli backtest``, which holds maintenance
mode (``worker.job.MaintenanceHold``): one backfill or backtest at a time. So when a
canonical backtest starts, any other canonical backtest run still ``running`` has no
process left (run 2286 was killed by the OOM killer) and is closed as abandoned:
``failed`` with an ``abandoned:`` error, as schedule_runs, candidate_notes and news_llm
close theirs.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Instrument, IngestionRun, MarketBar

SCORE_DATE = date(2026, 9, 4)
DAY = SCORE_DATE.isoformat()


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'backtest.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", session_factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    with session_factory() as db:
        instrument = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="STALE",
            name="Stale",
            instrument_type="stock",
            status="active",
        )
        db.add(instrument)
        db.flush()
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=SCORE_DATE,
                open=100,
                high=101,
                low=99,
                close=100,
                adj_close=100,
                volume=1000,
                turnover=100000,
                source="fixture",
            )
        )
        db.commit()
    yield session_factory
    engine.dispose()


def _run(db, request_key: str, status: str, **extra) -> int:
    row = IngestionRun(
        run_type="backtest",
        source="technical_backtest",
        run_date=date(2026, 11, 3),
        status=status,
        request_key=request_key,
        started_at=datetime(2026, 11, 4, 13, 54),
        **extra,
    )
    db.add(row)
    db.commit()
    return row.id


def test_a_canonical_backtest_closes_a_canonical_run_left_running(
    factory, frozen_utcnow
):
    with factory() as db:
        killed = _run(db, "technical-backtest:v2:2025-11-04:2026-11-03", "running")
    result = pipeline.backtest(SCORE_DATE, SCORE_DATE)
    assert result["run"]["status"] == "success"
    assert result["abandoned_runs"] == [killed]
    with factory() as db:
        row = db.get(IngestionRun, killed)
        assert row.status == "failed"
        assert row.error.startswith("abandoned: ")
        assert row.finished_at == frozen_utcnow.at
        assert row.records == 0


def test_finished_runs_and_research_runs_are_left_alone(factory):
    with factory() as db:
        done = _run(db, "technical-backtest:v2:2026-06-01:2026-08-31", "success")
        failed = _run(
            db, "technical-backtest:v2:2026-03-01:2026-05-31", "failed", error="boom"
        )
        # A research run belongs to tools/research on a copy, not to the CLI's hold.
        research = _run(
            db,
            "technical-backtest:v2:2026-01-01:2026-02-27:research:breakout_v3",
            "running",
        )
        # Other run types are closed by their own jobs.
        other = IngestionRun(
            run_type="collect",
            source="twse",
            run_date=SCORE_DATE,
            status="running",
            request_key="collect:2026-09-04",
            started_at=datetime(2026, 11, 4, 13, 54),
        )
        db.add(other)
        db.commit()
        other_id = other.id
    result = pipeline.backtest(SCORE_DATE, SCORE_DATE)
    assert result["run"]["status"] == "success"
    assert result["abandoned_runs"] == []
    with factory() as db:
        assert db.get(IngestionRun, done).status == "success"
        assert db.get(IngestionRun, failed).error == "boom"
        assert db.get(IngestionRun, research).status == "running"
        assert db.get(IngestionRun, other_id).status == "running"


def test_a_rerun_of_the_killed_range_reuses_its_row_and_reports_it(factory):
    key = f"technical-backtest:v2:{DAY}:{DAY}"
    with factory() as db:
        killed = _run(db, key, "running")
    result = pipeline.backtest(SCORE_DATE, SCORE_DATE)
    assert result["run"]["id"] == killed and result["run"]["status"] == "success"
    assert result["abandoned_runs"] == [killed]
    with factory() as db:
        rows = db.scalars(
            select(IngestionRun).where(IngestionRun.request_key == key)
        ).all()
        assert [row.status for row in rows] == ["success"]


def test_an_idempotent_reuse_still_closes_the_abandoned_run(factory):
    assert pipeline.backtest(SCORE_DATE, SCORE_DATE)["run"]["status"] == "success"
    with factory() as db:
        killed = _run(db, "technical-backtest:v2:2025-11-04:2026-11-03", "running")
    again = pipeline.backtest(SCORE_DATE, SCORE_DATE)
    assert again["idempotent_reuse"] is True
    assert again["abandoned_runs"] == [killed]
    with factory() as db:
        assert db.get(IngestionRun, killed).status == "failed"
