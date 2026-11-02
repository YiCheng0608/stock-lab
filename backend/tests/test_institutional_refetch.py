"""The 21:30 daily refetches a completed day's institutional files (Issue #396).

The exchanges revise the institutional (三大法人) files after 18:30.  When the
18:30 daily already finished as ``success``, the 21:30 one used to record only
``already_complete``; now it requests the TWSE T86 and TPEx daily-trade files
once more (two requests) and applies them with #387's later-capture rule,
without requesting OHLCV, margin or events.  The fixture numbers are those of
``test_institutional_revisions``: 1101's investment-trust flow -162,968 at
18:30 and 1,133,032 at 21:30.
"""

import socket

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import ChipSnapshot, IngestionRun, MarketBar, ScheduleRun
import worker.institutional_refetch as institutional_refetch
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
import worker.sources as sources
from test_daily_schedule import runs
from test_institutional_revisions import (
    DAY,
    FIRST,
    INITIAL,
    LATER,
    LATEST,
    REVISED,
    Fetcher,
    chip,
    t86_capture,
)

# The requests a refetch may send: one per exchange.
INSTITUTIONAL_FILES = (sources.TWSE_CHIP_ENDPOINT, sources.TPEX_CHIP_HISTORY_ENDPOINT)
LATER_STEPS = (
    "trading_calendar",
    "analyze",
    "evaluate",
    "candidates",
    "indicators",
    "theme_suggestions",
    "plan_tracking",
    "strategy_levels",
    "candidate_notes",
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in institutional refetch tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'refetch.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


class Daily:
    """The daily job with the real collect and refetch on fixture feeds.

    Steps after collect are no-ops, so a run's requests are collect's and the
    refetch's only; ``collects`` counts the collect calls.
    """

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.fetcher = Fetcher(INITIAL)
        self.collects = 0
        real_collect = pipeline.collect

        def adapter():
            return sources.OfficialMarketDataAdapter(
                sources.TwseAdapter(self.fetcher), sources.TpexAdapter(self.fetcher)
            )

        def collect(*args, **kwargs):
            self.collects += 1
            return real_collect(*args, **kwargs)

        monkeypatch.setattr(pipeline, "OfficialMarketDataAdapter", adapter)
        monkeypatch.setattr(institutional_refetch, "OfficialMarketDataAdapter", adapter)
        monkeypatch.setattr(pipeline, "collect", collect)
        done = {"status": "success", "records": 0}
        monkeypatch.setattr(schedule_runs, "_catchup_step", lambda *_args: done)
        monkeypatch.setattr(schedule_runs, "_trading_calendar_step", lambda *_: done)
        monkeypatch.setattr(pipeline, "analyze", lambda **_: done)
        monkeypatch.setattr(pipeline, "evaluate", lambda **_: done)
        for name in (
            "_candidate_step",
            "_indicator_step",
            "_plan_tracking_step",
            "_strategy_levels_step",
            "_candidate_note_step",
        ):
            monkeypatch.setattr(schedule_runs, name, lambda *_: done)
        monkeypatch.setattr(schedule_runs, "_theme_suggestion_step", lambda: done)

    def run(self, when, t86=INITIAL, **fetcher):
        self.fetcher = Fetcher(t86, **fetcher)
        self.monkeypatch.setattr(sources, "utcnow", lambda: when)
        return pipeline.run_daily(DAY, trigger="scheduler")


def institutional(row):
    return (row.foreign_buy, row.trust_buy, row.dealer_buy)


def test_the_2130_run_refetches_the_institutional_file_and_revises_the_row(
    database, monkeypatch
):
    daily = Daily(monkeypatch)
    first = daily.run(FIRST, INITIAL)
    assert first["status"] == "success", first
    with database() as db:
        row = chip(db)
        assert institutional(row) == (-1733324, -162968, 307854)
        stored_raw, margin = row.raw_payload_id, row.margin_balance
        margin_group = (row.margin_source, row.margin_raw_payload_id)
        assert margin_group[1] is not None and margin_group[1] != stored_raw
        tpex_before = db.scalar(
            select(ChipSnapshot).where(ChipSnapshot.source.like("tpex_3insti%"))
        )
        tpex_values = (institutional(tpex_before), tpex_before.raw_payload_id)
        bars = db.scalar(select(MarketBar.id).order_by(MarketBar.id.desc()))

    second = daily.run(LATER, REVISED)
    # The day stays complete: no second collect, nothing but the two files.
    assert (second["status"], second["reason"]) == ("skipped", "already_complete")
    assert daily.collects == 1
    assert [url.split("?", 1)[0] for url in daily.fetcher.calls] == list(
        INSTITUTIONAL_FILES
    )
    refetch = second["institutional_refetch"]
    assert refetch["status"] == "success" and refetch["requests"] == 2
    assert refetch["revised_rows"] == 1
    with database() as db:
        row = chip(db)
        revised_raw = t86_capture(db, LATER)
        assert institutional(row) == (-1733324, 1133032, 307854)
        assert row.raw_payload_id == revised_raw != stored_raw
        # Margin is not requested and keeps its value and source part.
        assert row.margin_balance == margin
        assert row.source == "twse_t86+twse_margin"
        # Only the institutional group moves to the refetched capture (#395).
        assert row.institutional_raw_payload_id == revised_raw
        assert (row.margin_source, row.margin_raw_payload_id) == margin_group
        # The TPEx file did not change: its row keeps its values and capture.
        tpex_after = db.get(ChipSnapshot, tpex_before.id)
        assert (institutional(tpex_after), tpex_after.raw_payload_id) == tpex_values
        assert db.scalar(select(MarketBar.id).order_by(MarketBar.id.desc())) == bars

        run = db.get(IngestionRun, refetch["run_id"])
        assert (run.run_type, run.status, run.records) == (
            "institutional_refetch",
            "success",
            1,
        )
        assert run.metadata_json["requests"] == 2
        assert run.metadata_json["unchanged_rows"] == 1
        assert run.metadata_json["value_revision_rows"] == [
            {
                "table": "chip_snapshots",
                "exchange": "TWSE",
                "symbol": "1101",
                "trading_date": DAY.isoformat(),
                "fields": {"trust_buy": {"stored": -162968.0, "incoming": 1133032.0}},
                "stored_raw_payload_id": stored_raw,
                "raw_payload_id": revised_raw,
            }
        ]
    rows, by_run = runs(database)
    assert [row.status for row in rows] == ["success", "skipped"]
    assert rows[1].summary_json["reason"] == "already_complete"
    assert rows[1].summary_json["related_run_id"] == rows[0].id
    assert rows[1].summary_json["institutional_refetch"] == {
        "status": "success",
        "run_id": run.id,
        "idempotent_reuse": False,
        "requests": 2,
        "revised_rows": 1,
        "unchanged_rows": 1,
        "value_fills": 0,
    }
    assert rows[1].records == 1
    step = by_run[rows[1].id]
    assert list(step) == ["institutional_refetch"]
    assert (
        step["institutional_refetch"].status,
        step["institutional_refetch"].records,
    ) == (
        "success",
        1,
    )
    assert step["institutional_refetch"].ingestion_run_id == run.id


def test_a_refetch_without_a_correction_changes_nothing(database, monkeypatch):
    daily = Daily(monkeypatch)
    assert daily.run(FIRST, INITIAL)["status"] == "success"
    with database() as db:
        kept = {
            row.id: (
                institutional(row),
                row.raw_payload_id,
                row.collected_at,
                row.source,
            )
            for row in db.scalars(select(ChipSnapshot))
        }

    second = daily.run(LATER, INITIAL)
    refetch = second["institutional_refetch"]
    assert (refetch["status"], refetch["requests"], refetch["revised_rows"]) == (
        "success",
        2,
        0,
    )
    assert refetch["unchanged_rows"] == len(kept) == 2
    assert daily.collects == 1
    assert [url.split("?", 1)[0] for url in daily.fetcher.calls] == list(
        INSTITUTIONAL_FILES
    )
    with database() as db:
        # The capture is kept, but no row points at it or changes.
        assert t86_capture(db, LATER) is not None
        assert {
            row.id: (
                institutional(row),
                row.raw_payload_id,
                row.collected_at,
                row.source,
            )
            for row in db.scalars(select(ChipSnapshot))
        } == kept
        run = db.get(IngestionRun, refetch["run_id"])
        assert run.metadata_json["value_revision_rows"] == []


def test_the_files_are_refetched_once_per_day(database, monkeypatch):
    daily = Daily(monkeypatch)
    daily.run(FIRST, INITIAL)
    first_refetch = daily.run(LATER, REVISED)["institutional_refetch"]

    # A third invocation (a manual rerun) sends no request at all.
    third = daily.run(LATEST, INITIAL, extra=[["2330", "1", "2", "3"]])
    assert third["reason"] == "already_complete"
    assert daily.fetcher.calls == []
    assert third["institutional_refetch"] == {
        "status": "success",
        "run_id": first_refetch["run_id"],
        "idempotent_reuse": True,
        "requests": 0,
        "revised_rows": 1,
        "unchanged_rows": 1,
        "value_fills": 0,
    }
    with database() as db:
        assert chip(db).trust_buy == 1133032
    assert daily.collects == 1


def test_a_partial_collect_is_completed_by_21_30_without_a_refetch(
    database, monkeypatch
):
    daily = Daily(monkeypatch)
    daily.run(FIRST, INITIAL)
    with database() as db:
        db.query(ScheduleRun).update({"status": "partial"})
        db.query(IngestionRun).update({"status": "partial"})
        db.commit()

    second = daily.run(LATER, REVISED)
    # The 21:30 collect fetches every feed itself and takes the revision.
    assert second["status"] == "success" and "institutional_refetch" not in second
    assert daily.collects == 2
    assert len(daily.fetcher.calls) > len(INSTITUTIONAL_FILES)
    with database() as db:
        assert chip(db).trust_buy == 1133032
        assert (
            db.scalar(
                select(IngestionRun).where(
                    IngestionRun.run_type == institutional_refetch.RUN_TYPE
                )
            )
            is None
        )


def test_a_non_trading_day_is_not_refetched(database, monkeypatch):
    daily = Daily(monkeypatch)
    with database() as db:
        db.add(
            ScheduleRun(
                job="daily",
                target_date=DAY,
                trigger="scheduler",
                status="non_trading_day",
                started_at=FIRST,
                finished_at=FIRST,
            )
        )
        db.commit()
    result = daily.run(LATER, REVISED)
    assert result["reason"] == "already_complete"
    assert "institutional_refetch" not in result
    assert daily.fetcher.calls == [] and daily.collects == 0
    rows, by_run = runs(database)
    assert by_run[rows[1].id] == {}


def test_one_failed_file_is_partial_and_the_next_run_tries_again(database, monkeypatch):
    daily = Daily(monkeypatch)
    daily.run(FIRST, INITIAL)

    class TpexDown(Fetcher):
        def __call__(self, url, **kwargs):
            if url == sources.TPEX_CHIP_HISTORY_ENDPOINT:
                self.calls.append(url)
                raise sources.OfficialDataError("TPEx unavailable")
            return super().__call__(url, **kwargs)

    monkeypatch.setattr(sources, "utcnow", lambda: LATER)
    daily.fetcher = TpexDown(REVISED)
    second = pipeline.run_daily(DAY, trigger="scheduler")
    refetch = second["institutional_refetch"]
    assert (refetch["status"], refetch["requests"], refetch["revised_rows"]) == (
        "partial",
        2,
        1,
    )
    assert refetch["error"].startswith("TPEx: ")
    assert refetch["error"].endswith("TPEx unavailable")
    with database() as db:
        assert chip(db).trust_buy == 1133032
        run = db.get(IngestionRun, refetch["run_id"])
        exchanges = run.metadata_json["exchanges"]
        assert exchanges["TWSE"]["status"] == "success"
        assert exchanges["TPEx"]["status"] == "failed"
        assert exchanges["TPEx"]["error"].endswith("TPEx unavailable")
    rows, by_run = runs(database)
    assert rows[1].status == "skipped"
    assert by_run[rows[1].id]["institutional_refetch"].status == "partial"

    # Not a success, so the next invocation requests both files again.
    third = daily.run(LATEST, REVISED)
    assert third["institutional_refetch"]["status"] == "success"
    assert third["institutional_refetch"]["run_id"] == refetch["run_id"]
    assert [url.split("?", 1)[0] for url in daily.fetcher.calls] == list(
        INSTITUTIONAL_FILES
    )


def test_a_refetch_error_is_recorded_and_the_run_stays_skipped(database, monkeypatch):
    daily = Daily(monkeypatch)
    daily.run(FIRST, INITIAL)

    def broken(*_args, **_kwargs):
        raise RuntimeError("upsert broke")

    monkeypatch.setattr(pipeline, "_upsert_official_chip", broken)
    second = daily.run(LATER, REVISED)
    assert second["status"] == "skipped"
    refetch = second["institutional_refetch"]
    assert refetch["status"] == "failed"
    assert "RuntimeError: upsert broke" in refetch["error"]
    with database() as db:
        assert chip(db).trust_buy == -162968
        run = db.get(IngestionRun, refetch["run_id"])
        assert run.status == "failed" and run.finished_at is not None


# The guards that keep a bad or foreign file out of the stored rows (#399 review).


class T86Override(Fetcher):
    """The fixture feeds with the T86 payload's keys replaced."""

    def __init__(self, t86=INITIAL, **override):
        super().__init__(t86)
        self.override = override

    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url.startswith(sources.TWSE_CHIP_ENDPOINT):
            return dict(payload, **self.override)
        return payload


def refetch_with(monkeypatch, daily, fetcher):
    monkeypatch.setattr(sources, "utcnow", lambda: LATER)
    daily.fetcher = fetcher
    return pipeline.run_daily(DAY, trigger="scheduler")


def test_a_refetch_creates_no_chip_row(database, monkeypatch):
    daily = Daily(monkeypatch)
    daily.run(FIRST, INITIAL)
    with database() as db:
        db.delete(chip(db))
        db.commit()
        count = db.query(ChipSnapshot).count()

    refetch = daily.run(LATER, REVISED)["institutional_refetch"]
    # 1101 is in the file, but the 18:30 collect left it without a row.
    assert (refetch["status"], refetch["requests"], refetch["revised_rows"]) == (
        "success",
        2,
        0,
    )
    with database() as db:
        assert chip(db) is None
        assert db.query(ChipSnapshot).count() == count


def test_a_file_reported_for_another_date_is_not_applied(database, monkeypatch):
    daily = Daily(monkeypatch)
    daily.run(FIRST, INITIAL)

    # The T86 answer is the day before's file, with other values.
    second = refetch_with(monkeypatch, daily, T86Override(REVISED, date="20260903"))
    assert second["status"] == "skipped"
    refetch = second["institutional_refetch"]
    assert (refetch["status"], refetch["revised_rows"]) == ("partial", 0)
    with database() as db:
        assert chip(db).trust_buy == -162968
        exchanges = db.get(IngestionRun, refetch["run_id"]).metadata_json["exchanges"]
        assert exchanges["TWSE"]["status"] == "failed"
        assert "2026-09-04" in exchanges["TWSE"]["error"]
        assert exchanges["TPEx"]["status"] == "success"


def test_a_file_without_rows_is_a_failed_exchange(database, monkeypatch):
    daily = Daily(monkeypatch)
    daily.run(FIRST, INITIAL)

    refetch = refetch_with(monkeypatch, daily, T86Override(REVISED, data=[]))[
        "institutional_refetch"
    ]
    assert (refetch["status"], refetch["revised_rows"]) == ("partial", 0)
    assert refetch["error"] == "TWSE: the file returned no rows"
    with database() as db:
        assert chip(db).trust_buy == -162968
