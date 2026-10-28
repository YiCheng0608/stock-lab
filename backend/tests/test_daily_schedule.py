"""Daily schedule run log, re-run idempotency and historical backfill fetch plan."""

import os
import socket
import subprocess
import sys
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    DataQuality,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    ScheduleRun,
    ScheduleRunStep,
)
import worker.backfill as backfill
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
import worker.sources as sources
from test_sources import FixtureFetcher


DAY = date(2026, 9, 4)
# Captured before Steps replaces it with a no-op.
REAL_CATCHUP_STEP = schedule_runs._catchup_step
REAL_PLAN_TRACKING_STEP = schedule_runs._plan_tracking_step
REAL_STRATEGY_LEVELS_STEP = schedule_runs._strategy_levels_step
REAL_TRADING_CALENDAR_STEP = schedule_runs._trading_calendar_step


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in daily schedule regressions")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'schedule.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


class Steps:
    """Fake pipeline steps that record calls and return scripted results."""

    def __init__(self, monkeypatch, **results):
        self.calls: list[str] = []
        self.results = {
            "collect": {"status": "success", "records": 12, "run_id": None},
            "trading_calendar": {"status": "success", "records": 0},
            "analyze": {"status": "success", "signals_upserted": 3},
            "evaluate": {
                "status": "success",
                "evaluations_written": 4,
                "settlements_written": 1,
            },
            "candidates": {"status": "success", "records": 2},
            "indicators": {"status": "not_configured", "reason": "fixture"},
            "theme_suggestions": {"status": "success", "records": 4},
            "plan_tracking": {"status": "success", "records": 0},
            "strategy_levels": {"status": "success", "records": 6},
            "candidate_notes": {"status": "success", "records": 3},
        }
        self.results.update(results)

        def make(name):
            def step(*_args, **_kwargs):
                self.calls.append(name)
                result = self.results[name]
                if isinstance(result, Exception):
                    raise result
                return dict(result)

            return step

        monkeypatch.setattr(pipeline, "collect", make("collect"))
        monkeypatch.setattr(
            schedule_runs, "_trading_calendar_step", make("trading_calendar")
        )
        monkeypatch.setattr(pipeline, "analyze", make("analyze"))
        monkeypatch.setattr(pipeline, "evaluate", make("evaluate"))
        monkeypatch.setattr(schedule_runs, "_candidate_step", make("candidates"))
        monkeypatch.setattr(schedule_runs, "_indicator_step", make("indicators"))
        monkeypatch.setattr(
            schedule_runs, "_theme_suggestion_step", make("theme_suggestions")
        )
        monkeypatch.setattr(schedule_runs, "_plan_tracking_step", make("plan_tracking"))
        monkeypatch.setattr(
            schedule_runs, "_strategy_levels_step", make("strategy_levels")
        )
        monkeypatch.setattr(
            schedule_runs, "_candidate_note_step", make("candidate_notes")
        )
        # Catch-up has its own tests; here no earlier session is missing.
        monkeypatch.setattr(
            schedule_runs,
            "_catchup_step",
            lambda *_args: {"status": "success", "records": 0},
        )


def runs(factory):
    with factory() as db:
        rows = db.scalars(select(ScheduleRun).order_by(ScheduleRun.id)).all()
        steps = {
            row.id: {
                step.step: step
                for step in db.scalars(
                    select(ScheduleRunStep).where(
                        ScheduleRunStep.schedule_run_id == row.id
                    )
                ).all()
            }
            for row in rows
        }
        return rows, steps


def test_daily_logs_every_step_and_a_rerun_is_recorded_without_running_again(
    database, monkeypatch
):
    steps = Steps(monkeypatch)
    first = pipeline.run_daily(DAY, trigger="scheduler")
    assert first["status"] == "success"
    assert steps.calls == [
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]
    rows, by_run = runs(database)
    assert [
        (row.status, row.trigger, row.target_date, row.records) for row in rows
    ] == [("success", "scheduler", DAY, 12)]
    logged = by_run[rows[0].id]
    assert {name: (step.status, step.records) for name, step in logged.items()} == {
        "catchup": ("success", 0),
        "collect": ("success", 12),
        "trading_calendar": ("success", 0),
        "analyze": ("success", 3),
        "evaluate": ("success", 5),
        "candidates": ("success", 2),
        "indicators": ("not_configured", None),
        "theme_suggestions": ("success", 4),
        "plan_tracking": ("success", 0),
        "strategy_levels": ("success", 6),
        "candidate_notes": ("success", 3),
    }
    assert all(step.started_at and step.finished_at for step in logged.values())
    assert rows[0].finished_at >= rows[0].started_at

    again = pipeline.run_daily(DAY, trigger="scheduler")
    assert again["status"] == "skipped" and again["reason"] == "already_complete"
    assert again["related_run_id"] == rows[0].id
    assert steps.calls == [
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]
    rows, by_run = runs(database)
    assert [row.status for row in rows] == ["success", "skipped"]
    assert by_run[rows[1].id] == {}

    forced = pipeline.run_daily(DAY, force=True)
    assert forced["status"] == "success"
    assert steps.calls.count("collect") == 2


def test_partial_collect_stops_later_steps_and_keeps_the_warning(database, monkeypatch):
    steps = Steps(
        monkeypatch,
        collect={
            "status": "partial",
            "records": 9,
            "warnings": ["TWSE margin chips unavailable"],
        },
    )
    result = pipeline.run_daily(DAY)
    assert result["status"] == "partial"
    assert steps.calls == ["collect"]
    rows, by_run = runs(database)
    assert (
        rows[0].status == "partial" and "TWSE margin chips unavailable" in rows[0].error
    )
    assert {name: step.status for name, step in by_run[rows[0].id].items()} == {
        "catchup": "success",
        "collect": "partial",
        "trading_calendar": "skipped",
        "analyze": "skipped",
        "evaluate": "skipped",
        "candidates": "skipped",
        "indicators": "skipped",
        "theme_suggestions": "skipped",
        "plan_tracking": "skipped",
        "strategy_levels": "skipped",
        "candidate_notes": "skipped",
    }
    # A partial day is retried by the next trigger instead of being reused.
    steps.results["collect"] = {"status": "success", "records": 10}
    assert pipeline.run_daily(DAY)["status"] == "success"
    assert steps.calls == [
        "collect",
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]


def test_verified_non_trading_day_is_complete(database, monkeypatch):
    steps = Steps(
        monkeypatch,
        collect={"status": "skipped", "records": 0, "no_data_dates": [DAY.isoformat()]},
    )
    assert pipeline.run_daily(DAY)["status"] == "non_trading_day"
    assert pipeline.run_daily(DAY)["reason"] == "already_complete"
    assert steps.calls == ["collect"]
    rows, _ = runs(database)
    assert [row.status for row in rows] == ["non_trading_day", "skipped"]
    assert rows[0].error is None


def test_step_exception_is_recorded_and_dependent_steps_are_skipped(
    database, monkeypatch
):
    steps = Steps(monkeypatch, analyze=RuntimeError("fixture analyze crash"))
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    # Indicators depend only on the collected bars, theme suggestions only on
    # stored news results and plan tracking only on the bars and the plans'
    # own levels, so they still run.
    assert steps.calls == [
        "collect",
        "trading_calendar",
        "analyze",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
    ]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert rows[0].status == "failed" and "fixture analyze crash" in rows[0].error
    assert (
        logged["analyze"].status == "failed"
        and "RuntimeError: fixture analyze crash" in logged["analyze"].error
    )
    assert (
        logged["evaluate"].status == "skipped"
        and logged["evaluate"].error == "analyze_not_successful"
    )
    assert (
        logged["candidates"].status == "skipped"
        and logged["candidates"].error == "analyze_not_successful"
    )
    assert logged["indicators"].status == "not_configured"
    assert logged["theme_suggestions"].status == "success"
    assert (
        logged["strategy_levels"].status == "skipped"
        and logged["strategy_levels"].error == "analyze_not_successful"
    )
    assert (
        logged["candidate_notes"].status == "skipped"
        and logged["candidate_notes"].error == "candidates_not_successful"
    )


def test_failed_evaluate_still_runs_candidates_and_indicators(database, monkeypatch):
    steps = Steps(
        monkeypatch, evaluate={"status": "failed", "error": "fixture evaluate failure"}
    )
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    # candidates read the trading date's signals, which analyze already stored.
    assert steps.calls == [
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]
    rows, by_run = runs(database)
    assert rows[0].error == "evaluate: fixture evaluate failure"
    assert by_run[rows[0].id]["candidates"].status == "success"


def test_failed_candidates_fail_the_run_without_blocking_indicators(
    database, monkeypatch
):
    steps = Steps(monkeypatch, candidates=RuntimeError("fixture candidate crash"))
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    assert steps.calls == [
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
    ]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert "fixture candidate crash" in rows[0].error
    assert logged["candidates"].status == "failed"
    assert (
        logged["evaluate"].status == "success"
        and logged["indicators"].status == "not_configured"
    )
    assert (
        logged["candidate_notes"].status == "skipped"
        and logged["candidate_notes"].error == "candidates_not_successful"
    )


def test_candidate_step_without_signals_is_an_acceptable_no_data_step(
    database, monkeypatch
):
    Steps(
        monkeypatch,
        candidates={"status": "no_data", "reason": "no_signals_for_date", "records": 0},
    )
    assert pipeline.run_daily(DAY)["status"] == "success"


@pytest.mark.parametrize(
    "outcome",
    [
        {"status": "failed", "reason": "cli_not_found: claude"},
        {
            "status": "partial",
            "error": "batch 1: timeout: no result within 300s",
            "records": 5,
        },
        RuntimeError("fixture note crash"),
    ],
)
def test_candidate_note_failures_stay_on_the_step_and_the_run_succeeds(
    database, monkeypatch, outcome
):
    steps = Steps(monkeypatch, candidate_notes=outcome)
    result = pipeline.run_daily(DAY)
    assert result["status"] == "success"
    assert steps.calls[-1] == "candidate_notes"
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]["candidate_notes"]
    assert rows[0].status == "success" and rows[0].error is None
    assert logged.status in {"failed", "partial"} and logged.error
    assert rows[0].summary_json["steps"]["candidate_notes"] == logged.status


def test_candidate_note_step_runs_the_target_date(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "worker.candidate_notes.run_candidate_notes_batch",
        lambda day: seen.append(day) or {"status": "success"},
    )
    assert schedule_runs._candidate_note_step(DAY)["status"] == "success"
    assert seen == [DAY]


def test_failed_indicator_batch_fails_the_run(database, monkeypatch):
    Steps(
        monkeypatch,
        indicators={"status": "failed", "error": "fixture indicator failure"},
    )
    assert pipeline.run_daily(DAY)["status"] == "failed"
    rows, _ = runs(database)
    assert rows[0].error == "indicators: fixture indicator failure"


def test_failed_theme_suggestions_fail_the_run_after_every_other_step(
    database, monkeypatch
):
    steps = Steps(
        monkeypatch, theme_suggestions=RuntimeError("fixture suggestion crash")
    )
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    assert steps.calls == [
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert "fixture suggestion crash" in rows[0].error
    assert logged["theme_suggestions"].status == "failed"
    assert logged["candidates"].status == "success"


def test_failed_plan_tracking_fails_the_run_but_the_notes_still_run(
    database, monkeypatch
):
    steps = Steps(monkeypatch, plan_tracking=RuntimeError("fixture plan crash"))
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    assert steps.calls[-3:] == ["plan_tracking", "strategy_levels", "candidate_notes"]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert "plan_tracking" in rows[0].error and "fixture plan crash" in rows[0].error
    assert logged["plan_tracking"].status == "failed"
    assert logged["candidate_notes"].status == "success"
    # Rows are found by step name; the sequence only orders them.
    assert [
        logged[name].sequence
        for name in ("plan_tracking", "strategy_levels", "candidate_notes")
    ] == [8, 9, 10]


@pytest.mark.parametrize(
    "outcome",
    [
        {"status": "failed", "error": "fixture levels failure"},
        {"status": "partial", "error": "fixture partial levels", "records": 2},
        RuntimeError("fixture levels crash"),
    ],
)
def test_strategy_level_failures_stay_on_the_step_and_the_run_succeeds(
    database, monkeypatch, outcome
):
    # The run's success definition does not depend on strategy_levels (#273).
    steps = Steps(monkeypatch, strategy_levels=outcome)
    result = pipeline.run_daily(DAY)
    assert result["status"] == "success"
    assert steps.calls[-2:] == ["strategy_levels", "candidate_notes"]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert rows[0].status == "success" and rows[0].error is None
    step = logged["strategy_levels"]
    assert step.status in {"failed", "partial"}
    assert "fixture" in step.error and "levels" in step.error
    assert rows[0].summary_json["steps"]["strategy_levels"] == step.status
    assert logged["candidate_notes"].status == "success"


def test_the_real_strategy_level_step_records_the_signals_it_processed(
    database, monkeypatch
):
    from test_strategy_levels import T, seed

    Steps(monkeypatch)
    monkeypatch.setattr(
        schedule_runs, "_strategy_levels_step", REAL_STRATEGY_LEVELS_STEP
    )
    with database() as db:
        seed(db)
        db.commit()
    assert pipeline.run_daily(T)["status"] == "success"
    rows, by_run = runs(database)
    step = by_run[rows[0].id]["strategy_levels"]
    assert (step.status, step.records, step.error) == ("success", 2, None)
    assert step.details_json["rows_written"] == 2
    assert step.details_json["date"] == T.isoformat()
    assert (
        sum(
            sum(counts.values())
            for counts in step.details_json["availability"].values()
        )
        == 2
    )
    # An analyze that wrote no signals for the date leaves an acceptable empty step.
    assert pipeline.run_daily(date(2026, 10, 23))["status"] == "success"
    rows, by_run = runs(database)
    empty = by_run[rows[-1].id]["strategy_levels"]
    assert (empty.status, empty.records) == ("no_data", 0)


@pytest.mark.parametrize(
    "outcome",
    [
        {"status": "failed", "error": "fixture calendar failure"},
        {"status": "partial", "error": "fixture partial calendar", "records": 0},
        RuntimeError("fixture calendar crash"),
    ],
)
def test_a_trading_calendar_failure_stays_on_the_step_and_analyze_runs(
    database, monkeypatch, outcome
):
    # #294: analyze then reads the calendar already stored.
    steps = Steps(monkeypatch, trading_calendar=outcome)
    result = pipeline.run_daily(DAY)
    assert result["status"] == "success"
    assert steps.calls[1:3] == ["trading_calendar", "analyze"]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert rows[0].status == "success" and rows[0].error is None
    step = logged["trading_calendar"]
    assert step.status in {"failed", "partial"}
    assert "fixture" in step.error and "calendar" in step.error
    assert rows[0].summary_json["steps"]["trading_calendar"] == step.status
    assert (logged["trading_calendar"].sequence, logged["analyze"].sequence) == (2, 3)
    assert logged["analyze"].status == "success"


def test_the_real_trading_calendar_step_stores_the_target_year_and_the_next(
    database, monkeypatch
):
    import worker.trading_calendar as trading_calendar
    from test_trading_calendar import Fetcher, schedule

    Steps(monkeypatch)
    monkeypatch.setattr(
        schedule_runs, "_trading_calendar_step", REAL_TRADING_CALENDAR_STEP
    )
    fetcher = Fetcher({2026: schedule(2026), 2027: schedule(2027)})
    real = trading_calendar.run_trading_calendar
    monkeypatch.setattr(
        trading_calendar,
        "run_trading_calendar",
        lambda target: real(target, fetcher=fetcher),
    )
    assert pipeline.run_daily(DAY)["status"] == "success"
    rows, by_run = runs(database)
    step = by_run[rows[0].id]["trading_calendar"]
    assert (step.status, step.records, step.error) == ("success", 27, None)
    assert step.details_json["years"]["2026"]["status"] == "inserted"
    assert step.details_json["years"]["2027"]["status"] == "unpublished"
    assert fetcher.urls == [
        trading_calendar.year_endpoint(2026),
        trading_calendar.year_endpoint(2027),
    ]


def test_a_real_trading_calendar_failure_keeps_its_reason_on_the_step(
    database, monkeypatch
):
    # #294 review L1: the reason shows in schedule-runs, not only in details.
    import worker.trading_calendar as trading_calendar
    from test_trading_calendar import Fetcher

    Steps(monkeypatch)
    monkeypatch.setattr(
        schedule_runs, "_trading_calendar_step", REAL_TRADING_CALENDAR_STEP
    )
    down = sources.OfficialDataError("fixture schedule endpoint down")
    fetcher = Fetcher({2026: down, 2027: down})
    real = trading_calendar.run_trading_calendar
    monkeypatch.setattr(
        trading_calendar,
        "run_trading_calendar",
        lambda target: real(target, fetcher=fetcher),
    )
    assert pipeline.run_daily(DAY)["status"] == "success"
    rows, by_run = runs(database)
    step = by_run[rows[0].id]["trading_calendar"]
    assert step.status == "failed"
    assert step.error == "; ".join(
        f"holiday schedule {year} unavailable: official endpoint failed:"
        f" {trading_calendar.year_endpoint(year)}: fixture schedule endpoint down"
        for year in (2026, 2027)
    )
    assert by_run[rows[0].id]["analyze"].status == "success"


def test_plan_tracking_without_any_plan_is_a_successful_empty_step(
    database, monkeypatch
):
    # The real step on an empty plan table: G7 counts this run as a success.
    Steps(monkeypatch)
    monkeypatch.setattr(schedule_runs, "_plan_tracking_step", REAL_PLAN_TRACKING_STEP)
    assert pipeline.run_daily(DAY)["status"] == "success"
    rows, by_run = runs(database)
    step = by_run[rows[0].id]["plan_tracking"]
    assert (step.status, step.records, step.error) == ("success", 0, None)
    assert step.details_json["plans_checked"] == 0
    assert step.details_json["date"] == DAY.isoformat()


def test_theme_suggestion_step_refreshes_with_the_daily_session(database, monkeypatch):
    seen = []
    monkeypatch.setattr(
        schedule_runs.theme_suggestions,
        "run_theme_suggestions",
        lambda factory=None: seen.append(factory)
        or {"status": "success", "records": 0},
    )
    assert schedule_runs._theme_suggestion_step()["status"] == "success"
    assert seen == [database]


def test_running_rows_block_until_stale_then_are_marked_abandoned(
    database, monkeypatch
):
    steps = Steps(monkeypatch)
    now = datetime.utcnow()
    with database() as db:
        db.add(
            ScheduleRun(
                job="daily",
                target_date=DAY,
                trigger="scheduler",
                status="running",
                started_at=now,
            )
        )
        db.commit()
    blocked = pipeline.run_daily(DAY)
    assert blocked["status"] == "skipped" and blocked["reason"] == "already_running"
    assert steps.calls == []
    with database() as db:
        db.execute(
            update(ScheduleRun)
            .where(ScheduleRun.status == "running")
            .values(started_at=now - timedelta(hours=4))
        )
        db.commit()
    assert pipeline.run_daily(DAY)["status"] == "success"
    rows, _ = runs(database)
    assert rows[0].status == "failed" and rows[0].error.startswith("abandoned")


def test_indicator_step_is_not_configured_without_the_batch_module(monkeypatch):
    monkeypatch.setattr(
        schedule_runs, "INDICATOR_MODULE", "worker.missing_indicator_batch_fixture"
    )
    assert schedule_runs._indicator_step(DAY)["status"] == "not_configured"


def test_list_schedule_runs_reports_steps(database, monkeypatch):
    Steps(monkeypatch)
    pipeline.run_daily(DAY)
    listed = schedule_runs.list_schedule_runs(5, DAY)
    assert listed[0]["status"] == "success"
    assert [step["step"] for step in listed[0]["steps"]] == [
        "catchup",
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]


# --- collect never rewrites stored official values ----------------------


def combined(fetcher):
    return sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher)
    )


def _bar(db, symbol):
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    return db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id, MarketBar.trading_date == DAY
        )
    )


def test_rerun_fills_missing_values_but_keeps_stored_ones(database):
    class Fetcher(FixtureFetcher):
        def __call__(self, url, **kwargs):
            payload = super().__call__(url, **kwargs)
            if url == sources.TWSE_LISTED_ENDPOINT:
                return [
                    dict(row, Industry="01" if row["Code"] == "1101" else "24")
                    for row in payload
                ]
            return payload

    fetcher = Fetcher()
    first = pipeline.collect(DAY, adapter=combined(fetcher))
    assert first["status"] == "success", first
    with database() as db:
        bar = _bar(db, "1101")
        original = (bar.open, bar.close, bar.volume)
        bar.close = original[1] + 1.5  # stands in for a value stored by an earlier run
        chip = db.scalar(
            select(ChipSnapshot).where(ChipSnapshot.instrument_id == bar.instrument_id)
        )
        margin = chip.margin_balance
        assert margin is not None
        chip.margin_balance = None  # e.g. margin data published after an earlier run
        chip_count = len(db.scalars(select(ChipSnapshot)).all())
        db.execute(update(IngestionRun).values(status="partial"))
        db.commit()

    second = pipeline.collect(DAY, adapter=combined(fetcher))
    assert second["status"] == "success" and not second.get("idempotent_reuse")
    assert second["value_conflicts"] >= 1
    with database() as db:
        bar = _bar(db, "1101")
        assert bar.close == original[1] + 1.5
        assert bar.volume == original[2]
        chip = db.scalar(
            select(ChipSnapshot).where(ChipSnapshot.instrument_id == bar.instrument_id)
        )
        assert chip.margin_balance == margin
        assert len(db.scalars(select(ChipSnapshot)).all()) == chip_count
        assert len(db.scalars(select(MarketBar)).all()) == len(
            {
                (b.instrument_id, b.trading_date)
                for b in db.scalars(select(MarketBar)).all()
            }
        )
        run = db.get(IngestionRun, second["run_id"])
        assert any(
            item["field"] == "close"
            for item in run.metadata_json["value_conflict_samples"]
        )
        untouched = _bar(db, "0050")
        untouched_state = (
            untouched.close,
            untouched.raw_payload_id,
            untouched.collected_at,
        )

    third = pipeline.collect(DAY, adapter=combined(fetcher), force=True)
    assert third["status"] == "success" and third["value_conflicts"] == 0
    with database() as db:
        assert _bar(db, "1101").close == original[1]
        untouched = _bar(db, "0050")
        # force restores replace semantics, so provenance moves to the new capture.
        assert untouched.close == untouched_state[0]


# --- MOPS same-subject announcements ------------------------------------


def test_same_subject_announcements_keep_distinct_titles():
    title = "公告本公司處分不動產予關係人案"
    rows = [
        {
            "SecuritiesCompanyCode": "6264",
            "發言日期": "1151016",
            "發言時間": "194240",
            "主旨": title,
            "說明": "B unit",
        },
        {
            "SecuritiesCompanyCode": "6264",
            "發言日期": "1151016",
            "發言時間": "194110",
            "主旨": title,
            "說明": "A unit",
        },
        {
            "SecuritiesCompanyCode": "6264",
            "發言日期": "1151016",
            "發言時間": "194110",
            "主旨": title,
            "說明": "A unit",
        },
        {
            "SecuritiesCompanyCode": "6264",
            "發言日期": "1151016",
            "發言時間": "194341",
            "主旨": title,
            "說明": "C unit",
        },
        {
            "SecuritiesCompanyCode": "6265",
            "發言日期": "1151016",
            "發言時間": "100000",
            "主旨": title,
            "說明": "other issuer",
        },
    ]
    events = sources.parse_mops_event_rows(rows, exchange="TPEx", endpoint="fixture")
    titles = {(event.symbol, event.description): event.title for event in events}
    assert len(events) == 4
    assert titles[("6264", "A unit")] == title
    assert titles[("6264", "B unit")] == f"{title}（發言時間 19:42:40）"
    assert titles[("6264", "C unit")] == f"{title}（發言時間 19:43:41）"
    assert titles[("6265", "other issuer")] == title
    # An earlier fetch that only saw the first announcement stored the same title.
    first_only = sources.parse_mops_event_rows(
        rows[1:2], exchange="TPEx", endpoint="fixture"
    )
    assert first_only[0].title == title


# --- historical fetch plan ----------------------------------------------


def test_historical_adapter_skips_current_feeds_and_reuses_the_universe(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = FixtureFetcher()
    adapter = sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher, snapshot_feeds=False),
        sources.TpexAdapter(fetcher, snapshot_feeds=False),
    )
    first = adapter.fetch(DAY, DAY)
    second = adapter.fetch(DAY, DAY)
    current_only = {
        sources.TWSE_DAILY_ENDPOINT,
        sources.TWSE_INDEX_ENDPOINT,
        sources.TWSE_ACTION_ENDPOINT,
        sources.TWSE_EVENT_ENDPOINT,
        sources.TWSE_FUNDAMENTAL_ENDPOINT,
        sources.TPEX_ACTION_ENDPOINT,
        sources.TPEX_SUSPEND_ENDPOINT,
        sources.TPEX_SUSPEND_HISTORY_ENDPOINT,
        sources.TPEX_EVENT_ENDPOINT,
        sources.TPEX_FUNDAMENTAL_ENDPOINT,
    }
    assert not current_only.intersection(fetcher.calls)
    for endpoint in (sources.TWSE_LISTED_ENDPOINT, sources.TPEX_LISTED_ENDPOINT):
        assert fetcher.calls.count(endpoint) == 1
    for batch in (first, second):
        assert batch.snapshot_feeds is False
        assert any(
            bar.symbol == "TAIEX" and bar.trading_date == DAY for bar in batch.bars
        )
        assert {bar.symbol for bar in batch.bars} >= {"1101", "7001"}
        assert batch.chips and not batch.events and not batch.actions
        assert batch.event_coverage["status"] == "unsupported"
        # The reused universe payloads stay attached to every batch for provenance.
        assert any(p.endpoint == sources.TWSE_LISTED_ENDPOINT for p in batch.payloads)


def test_snapshot_collect_uses_the_dated_report_taiex_before_the_current_index(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = FixtureFetcher()
    batch = sources.TwseAdapter(fetcher).fetch(DAY, DAY)
    assert sources.TWSE_INDEX_ENDPOINT not in fetcher.calls
    assert [bar.trading_date for bar in batch.bars if bar.symbol == "TAIEX"] == [DAY]


def test_no_session_day_does_not_request_the_current_index(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")

    class Holiday(FixtureFetcher):
        def __call__(self, url, **kwargs):
            if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
                self.calls.append(url)
                return {"stat": "很抱歉，沒有符合條件的資料!"}
            return super().__call__(url, **kwargs)

    fetcher = Holiday()
    holiday = date(2026, 9, 7)
    batch = sources.TwseAdapter(fetcher).fetch(holiday, holiday)
    assert batch.no_data_dates == [holiday]
    assert sources.TWSE_INDEX_ENDPOINT not in fetcher.calls


def test_backfill_windows_cover_the_range_within_the_cap():
    windows = backfill.backfill_windows(date(2024, 10, 14), date(2026, 10, 16))
    assert windows[0][0] == date(2024, 10, 14) and windows[-1][1] == date(2026, 10, 16)
    for (start, end), (next_start, _next_end) in zip(windows, windows[1:]):
        assert next_start == end + timedelta(days=1)
    assert all(
        (end - start).days <= pipeline.OFFICIAL_MAX_BACKFILL_DAYS
        for start, end in windows
    )
    with pytest.raises(ValueError):
        backfill.backfill_windows(date(2026, 1, 2), date(2026, 1, 1))


def test_chunked_backfill_merges_window_results(monkeypatch):
    calls = []

    def fake(start, end, *, scope, adapter, force):
        calls.append((start, end, adapter))
        metadata = {
            "completed_dates": [start.isoformat()],
            "partial_dates": [end.isoformat()] if len(calls) == 1 else [],
            "failed_dates": [],
            "skipped_non_trading_dates": ["2024-12-25"] if len(calls) == 1 else [],
        }
        return {
            "id": len(calls),
            "status": "partial" if len(calls) == 1 else "success",
            "metadata": metadata,
        }

    monkeypatch.setattr(backfill, "targeted_backfill", fake)
    result = backfill.chunked_backfill(
        date(2024, 10, 14), date(2025, 3, 1), adapter=object()
    )
    assert len(calls) == 2 and calls[0][2] is calls[1][2]
    assert result["status"] == "partial"
    assert result["partial_dates"] == [calls[0][1].isoformat()]
    assert result["skipped_non_trading_dates"] == ["2024-12-25"]
    assert [window["run_id"] for window in result["windows"]] == [1, 2]


def test_official_host_requests_are_spaced(monkeypatch):
    clock = {"now": 100.0}
    sleeps = []
    monkeypatch.setattr(sources.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        sources.time,
        "sleep",
        lambda seconds: sleeps.append(seconds)
        or clock.__setitem__("now", clock["now"] + seconds),
    )
    monkeypatch.setattr(sources, "_host_last_request", {})
    sources._throttle_official_host(
        "https://www.twse.com.tw/rwd/zh/fund/T86?date=20260904"
    )
    clock["now"] += 0.5
    sources._throttle_official_host(
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20260904"
    )
    sources._throttle_official_host("https://fixture.example/unthrottled")
    assert sleeps == [
        pytest.approx(
            sources.OFFICIAL_HOST_MIN_INTERVAL_SECONDS["www.twse.com.tw"] - 0.5
        )
    ]


def test_analyze_uses_the_pinned_collect_run_even_when_another_is_newer(database):
    with database() as db:
        pinned = IngestionRun(
            run_type="collect",
            source="official",
            run_date=date(2026, 9, 3),
            status="success",
            records=1,
            data_as_of="2026-09-03",
            updated_at=datetime(2026, 9, 3, 8),
        )
        failed = IngestionRun(
            run_type="collect",
            source="official",
            run_date=date(2026, 9, 2),
            status="partial",
            records=1,
            data_as_of="2026-09-02",
            updated_at=datetime(2026, 9, 2, 8),
        )
        newer = IngestionRun(
            run_type="collect",
            source="official",
            run_date=DAY,
            status="success",
            records=1,
            data_as_of=DAY.isoformat(),
            updated_at=datetime(2026, 9, 5, 8),
        )
        db.add_all([pinned, failed, newer])
        db.commit()
        ids = (pinned.id, failed.id)
    assert pipeline.analyze(collect_run_id=ids[0])["date"] == "2026-09-03"
    assert pipeline.analyze(collect_run_id=ids[1])["status"] == "skipped"
    assert pipeline.analyze()["date"] == DAY.isoformat()


def test_schema_check_skips_init_db_only_at_the_code_head(database, monkeypatch):
    from sqlalchemy import text

    from app.migration_revisions import REVISIONS

    calls = []
    monkeypatch.setattr(pipeline, "init_db", lambda: calls.append("init_db"))
    assert schedule_runs._ensure_schema() == "current" and calls == []
    with database() as db:
        db.execute(
            text("UPDATE alembic_version SET version_num = :value"),
            {"value": REVISIONS[-2]},
        )
        db.commit()
    assert schedule_runs._ensure_schema() == "upgraded" and calls == ["init_db"]


def test_preflight_skip_is_logged_without_running_steps_and_does_not_complete_the_day(
    database, monkeypatch
):
    steps = Steps(monkeypatch)
    skipped = schedule_runs.record_preflight_skip(DAY, reason="low_memory")
    assert skipped["status"] == "skipped" and skipped["reason"] == "low_memory"
    assert steps.calls == []
    # A declined start is not completion: the next trigger still runs the day.
    assert pipeline.run_daily(DAY)["status"] == "success"
    rows, _ = runs(database)
    assert [(row.status, row.summary_json.get("reason")) for row in rows] == [
        ("skipped", "low_memory"),
        ("success", None),
    ]
    with pytest.raises(ValueError):
        schedule_runs.record_preflight_skip(DAY, reason="unknown")


def test_a_lock_skip_points_at_the_running_row(database, monkeypatch):
    with database() as db:
        running = ScheduleRun(
            job="daily",
            target_date=DAY,
            trigger="scheduler",
            status="running",
            started_at=datetime.utcnow(),
            host=socket.gethostname(),
            pid=os.getpid(),
        )
        db.add(running)
        db.commit()
        running_id = running.id
    skipped = schedule_runs.record_preflight_skip(DAY, reason="already_running")
    assert skipped["status"] == "skipped" and skipped["reason"] == "already_running"
    assert skipped["related_run_id"] == running_id
    rows, _ = runs(database)
    assert [(row.status, row.summary_json) for row in rows][-1] == (
        "skipped",
        {"reason": "already_running", "related_run_id": running_id},
    )


def test_a_lock_skip_writes_nothing_while_the_database_awaits_migration(
    database, monkeypatch
):
    # #313 AC-7: the daily holding the job lock may be migrating this database.
    # The migration reads inside one transaction for minutes before it writes; a
    # row committed meanwhile (or a second migration) made its write fail.
    from sqlalchemy import text

    from app.migration_revisions import REVISIONS

    def migrate():
        raise AssertionError("the lock skip ran init_db")

    monkeypatch.setattr(pipeline, "init_db", migrate)
    with database() as db:
        db.execute(
            text("UPDATE alembic_version SET version_num = :value"),
            {"value": REVISIONS[-2]},
        )
        db.commit()
    skipped = schedule_runs.record_preflight_skip(DAY, reason="already_running")
    assert skipped["status"] == "skipped" and skipped["schedule_run_id"] is None
    assert skipped["error"].startswith(
        f"skip row not written: database at ['{REVISIONS[-2]}']"
    )
    assert runs(database)[0] == []


def test_a_lock_skip_that_cannot_write_its_row_reports_it(database, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def locked():
        raise OperationalError("INSERT", {}, Exception("database is locked"))

    monkeypatch.setattr(pipeline, "SessionLocal", locked)
    skipped = schedule_runs.record_preflight_skip(DAY, reason="already_running")
    assert skipped["status"] == "skipped" and skipped["schedule_run_id"] is None
    assert "database is locked" in skipped["error"]
    # Any other skip reason still raises: its row is the only trace in the DB.
    with pytest.raises(OperationalError):
        schedule_runs.record_preflight_skip(DAY, reason="low_memory")


def test_running_row_whose_process_is_gone_is_abandoned_at_once(database, monkeypatch):
    steps = Steps(monkeypatch)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    now = datetime.utcnow()
    with database() as db:
        db.add(
            ScheduleRun(
                job="daily",
                target_date=DAY,
                trigger="scheduler",
                status="running",
                started_at=now,
                host=socket.gethostname(),
                pid=os.getpid(),
            )
        )
        db.commit()
    # A live owner on this host still blocks a second trigger.
    assert pipeline.run_daily(DAY)["reason"] == "already_running"
    with database() as db:
        db.execute(
            update(ScheduleRun)
            .where(ScheduleRun.status == "running")
            .values(pid=dead.pid)
        )
        db.commit()
    # The 18:30 process was killed: the 21:30 trigger reruns well before the time limit.
    assert pipeline.run_daily(DAY)["status"] == "success"
    assert steps.calls == [
        "collect",
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]
    rows, _ = runs(database)
    assert rows[0].status == "failed" and f"process {dead.pid}" in rows[0].error
    assert rows[-1].host == socket.gethostname() and rows[-1].pid == os.getpid()


def test_running_row_from_another_host_waits_for_the_time_limit(database, monkeypatch):
    Steps(monkeypatch)
    with database() as db:
        db.add(
            ScheduleRun(
                job="daily",
                target_date=DAY,
                trigger="scheduler",
                status="running",
                started_at=datetime.utcnow() - timedelta(hours=2),
                host="other-host",
                pid=1,
            )
        )
        db.commit()
    assert pipeline.run_daily(DAY)["reason"] == "already_running"


def test_cli_schedule_runs_and_daily_exit_codes(monkeypatch, capsys):
    import json as json_module

    import worker.cli as cli

    monkeypatch.setattr(cli, "list_schedule_runs", lambda limit, target: [])
    monkeypatch.setattr(sys, "argv", ["worker.cli", "schedule-runs"])
    cli.main()  # must not raise on a list result
    assert json_module.loads(capsys.readouterr().out) == []
    for status, code in (
        ("success", 0),
        ("partial", 2),
        ("failed", 1),
        ("non_trading_day", 0),
        ("non_trading_unconfirmed", 0),
    ):
        monkeypatch.setattr(
            cli,
            "run_daily",
            lambda *args, _status=status, **kwargs: {"status": _status},
        )
        monkeypatch.setattr(
            sys, "argv", ["worker.cli", "daily", "--date", DAY.isoformat()]
        )
        with pytest.raises(SystemExit) as exited:
            cli.main()
        assert exited.value.code == code


def _bar_record(**overrides):
    values = dict(
        symbol="1101",
        trading_date=DAY,
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        volume=1000,
        turnover=0.0,
        turnover_status="unavailable",
        turnover_reason="missing",
    )
    values.update(overrides)
    return sources.BarRecord(**values)


def test_turnover_amount_status_and_reason_change_together(database):
    with database() as db:
        instrument = Instrument(
            symbol="1101", name="fixture", exchange="TWSE", instrument_type="stock"
        )
        db.add(instrument)
        db.flush()

        def upsert(record, *, overwrite=False):
            conflicts = []
            bar = pipeline._upsert_official_bar(
                db, instrument, record, None, overwrite=overwrite, conflicts=conflicts
            )
            db.flush()
            return (bar.turnover, bar.turnover_status, bar.turnover_reason), conflicts

        assert upsert(_bar_record())[0] == (0.0, "unavailable", "missing")
        # An available amount fills the empty group as a whole.
        available = _bar_record(
            turnover=10500.0, turnover_status="available", turnover_reason=None
        )
        assert upsert(available)[0] == (10500.0, "available", None)
        # An unavailable re-fetch never downgrades it, with or without force.
        assert upsert(_bar_record())[0] == (10500.0, "available", None)
        assert upsert(_bar_record(), overwrite=True)[0] == (10500.0, "available", None)
        # A different available amount is a conflict unless forced.
        revised = _bar_record(
            turnover=11000.0, turnover_status="available", turnover_reason=None
        )
        state, conflicts = upsert(revised)
        assert state == (10500.0, "available", None) and [
            item["field"] for item in conflicts
        ] == ["turnover"]
        assert upsert(revised, overwrite=True)[0] == (11000.0, "available", None)


def test_forced_refetch_keeps_values_the_source_left_empty(database):
    with database() as db:
        instrument = Instrument(
            symbol="1101", name="fixture", exchange="TWSE", instrument_type="stock"
        )
        db.add(instrument)
        db.flush()
        instruments = {("TWSE", "1101"): instrument}
        full = sources.ChipRecord(
            symbol="1101",
            trading_date=DAY,
            foreign_buy=10,
            trust_buy=2,
            dealer_buy=1,
            margin_balance=500,
            margin_change=5,
        )
        pipeline._upsert_official_chip(db, full, instruments, None, overwrite=True)
        db.flush()
        partial = sources.ChipRecord(
            symbol="1101", trading_date=DAY, foreign_buy=12, trust_buy=2, dealer_buy=1
        )
        pipeline._upsert_official_chip(db, partial, instruments, None, overwrite=True)
        db.flush()
        chip = db.scalar(
            select(ChipSnapshot).where(ChipSnapshot.instrument_id == instrument.id)
        )
        assert (chip.foreign_buy, chip.margin_balance, chip.margin_change) == (
            12,
            500,
            5,
        )


def test_chunked_backfill_is_not_success_when_a_window_failed(monkeypatch):
    results = iter(
        [
            {
                "id": 1,
                "status": "partial",
                "error": None,
                "metadata": {
                    "completed_dates": ["2024-10-14"],
                    "skipped_non_trading_dates": ["2024-10-31"],
                },
            },
            {
                "id": 2,
                "status": "failed",
                "error": "scope resolved to no active instruments",
                "metadata": {},
            },
        ]
    )
    monkeypatch.setattr(
        backfill, "targeted_backfill", lambda *args, **kwargs: next(results)
    )
    result = backfill.chunked_backfill(
        date(2024, 10, 14), date(2025, 3, 1), adapter=object()
    )
    assert result["partial_dates"] == [] and result["failed_dates"] == []
    assert result["status"] == "partial"
    # A window that is partial only because of non-trading dates counts as complete.
    results = iter(
        [
            {
                "id": 3,
                "status": "partial",
                "error": None,
                "metadata": {
                    "completed_dates": ["2024-10-14"],
                    "skipped_non_trading_dates": ["2024-10-31"],
                },
            },
        ]
    )
    assert (
        backfill.chunked_backfill(
            date(2024, 10, 14), date(2024, 11, 1), adapter=object()
        )["status"]
        == "success"
    )


def test_0011_migration_matches_the_mapped_schedule_tables(database):
    from sqlalchemy import text as sql_text
    from sqlalchemy.pool import StaticPool

    from app.db import Base

    def shape(connection):
        result = {}
        for table in ("schedule_runs", "schedule_run_steps"):
            columns = [
                tuple(row[1:6])
                for row in connection.execute(sql_text(f"PRAGMA table_info({table})"))
            ]
            indexes = {}
            for row in connection.execute(sql_text(f"PRAGMA index_list({table})")):
                cols = [
                    info[2]
                    for info in connection.execute(
                        sql_text(f"PRAGMA index_info('{row[1]}')")
                    )
                ]
                indexes[tuple(cols)] = bool(row[2])
            fks = sorted(
                tuple(row[2:5])
                for row in connection.execute(
                    sql_text(f"PRAGMA foreign_key_list({table})")
                )
            )
            result[table] = (columns, indexes, fks)
        return result

    with database() as db:
        migrated = shape(db.connection())
    mapped_engine = create_engine("sqlite://", poolclass=StaticPool)
    try:
        Base.metadata.create_all(mapped_engine)
        with mapped_engine.connect() as connection:
            mapped = shape(connection)
    finally:
        mapped_engine.dispose()
    assert migrated == mapped


# --- catch-up of missed sessions (Issue #185 AC-2) --------------------------

MONDAY = date(2026, 10, 19)


def _collect_run(factory, day, status="success", taiex=1, finished_at=None):
    # By default the answer was obtained the day after, like a backfill.
    finished = finished_at or datetime(day.year, day.month, day.day) + timedelta(
        days=1, hours=2
    )
    with factory() as db:
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=day,
                status=status,
                records=10,
                request_key=f"official-ohlcv:{day}:{day}",
                started_at=finished - timedelta(minutes=5),
                finished_at=finished,
                metadata_json={"taiex_records": taiex},
            )
        )
        db.commit()


class CollectLog:
    """pipeline.collect fake: records (date, path) and writes a collect run like the real one."""

    def __init__(self, monkeypatch, factory, failing=()):
        self.calls: list[tuple[date, str]] = []

        def collect(day, *, adapter=None, months_back=0, init_schema=True, force=False):
            path = "historical" if adapter == "historical-adapter" else "snapshot"
            self.calls.append((day, path))
            if day in failing:
                return {"status": "failed", "records": 0, "error": "fixture outage"}
            _collect_run(factory, day)
            return {"status": "success", "records": 10, "run_id": None}

        monkeypatch.setattr(pipeline, "collect", collect)
        monkeypatch.setattr(
            schedule_runs, "_catchup_adapter", lambda: "historical-adapter"
        )
        monkeypatch.setattr(schedule_runs, "_catchup_step", REAL_CATCHUP_STEP)


def _week_before_monday(factory):
    # Fri 10-16 and Thu 10-15 were missed; Tue 10-13 was a holiday.
    for day in (date(2026, 10, 14), date(2026, 10, 12), date(2026, 10, 9)):
        _collect_run(factory, day)
    _collect_run(factory, date(2026, 10, 13), status="skipped", taiex=0)


def test_daily_collects_missed_sessions_oldest_first_then_the_target(
    database, monkeypatch
):
    steps = Steps(monkeypatch)
    log = CollectLog(monkeypatch, database)
    _week_before_monday(database)
    result = pipeline.run_daily(MONDAY, trigger="scheduler")
    assert result["status"] == "success"
    assert log.calls == [
        (date(2026, 10, 15), "historical"),
        (date(2026, 10, 16), "historical"),
        (MONDAY, "snapshot"),
    ]
    assert steps.calls == [
        "trading_calendar",
        "analyze",
        "evaluate",
        "candidates",
        "indicators",
        "theme_suggestions",
        "plan_tracking",
        "strategy_levels",
        "candidate_notes",
    ]
    caught = result["catchup"]
    # The holiday does not count toward the five sessions.
    assert caught["checked_dates"] == [
        "2026-10-09",
        "2026-10-12",
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
    ]
    assert caught["missing_dates"] == ["2026-10-15", "2026-10-16"]
    assert (caught["status"], caught["records"]) == ("success", 20)
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert (
        logged["catchup"].status,
        logged["catchup"].sequence,
        logged["catchup"].records,
    ) == ("success", 0, 20)
    assert rows[0].summary_json["steps"]["catchup"] == "success"

    # Idempotent: a later run finds nothing missing and fetches only its target.
    assert pipeline.run_daily(MONDAY)["reason"] == "already_complete"
    forced = pipeline.run_daily(MONDAY, force=True)
    assert forced["catchup"]["missing_dates"] == []
    assert log.calls[3:] == [(MONDAY, "snapshot")]


def test_incomplete_catchup_is_recorded_without_blocking_the_target(
    database, monkeypatch
):
    Steps(monkeypatch)
    log = CollectLog(monkeypatch, database, failing={date(2026, 10, 15)})
    _week_before_monday(database)
    result = pipeline.run_daily(MONDAY)
    assert result["status"] == "success"
    assert [day for day, _path in log.calls] == [
        date(2026, 10, 15),
        date(2026, 10, 16),
        MONDAY,
    ]
    assert result["catchup"]["status"] == "partial"
    assert result["catchup"]["incomplete_dates"] == ["2026-10-15"]
    rows, by_run = runs(database)
    assert rows[0].summary_json["steps"]["catchup"] == "partial"
    assert (
        by_run[rows[0].id]["catchup"].error == "catch-up incomplete: 2026-10-15 failed"
    )
    # The next day's run tries the missed date again.
    log.calls.clear()
    pipeline.run_daily(date(2026, 10, 20))
    assert log.calls[0] == (date(2026, 10, 15), "historical")


def test_catchup_can_be_turned_off(database, monkeypatch):
    Steps(monkeypatch)
    log = CollectLog(monkeypatch, database)
    result = pipeline.run_daily(MONDAY, catchup_sessions=0)
    assert result["status"] == "success" and "catchup" not in result
    assert log.calls == [(MONDAY, "snapshot")]


def test_catchup_collects_a_missed_session_through_the_backfill_path(
    database, monkeypatch
):
    fetcher = FixtureFetcher()
    monkeypatch.setattr(
        schedule_runs,
        "_catchup_adapter",
        lambda: sources.OfficialMarketDataAdapter(
            sources.TwseAdapter(fetcher, snapshot_feeds=False),
            sources.TpexAdapter(fetcher, snapshot_feeds=False),
        ),
    )
    for day in (
        date(2026, 9, 3),
        date(2026, 9, 2),
        date(2026, 9, 1),
        date(2026, 8, 31),
    ):
        _collect_run(database, day)
    result = schedule_runs._catchup_step(date(2026, 9, 7), 5)
    assert result["missing_dates"] == [DAY.isoformat()]
    assert result["status"] == "success", result
    with database() as db:
        run = db.scalar(
            select(IngestionRun).where(
                IngestionRun.request_key == f"official-ohlcv:{DAY}:{DAY}"
            )
        )
        assert run.status == "success" and run.metadata_json["taiex_records"] > 0
        assert (
            db.scalar(select(MarketBar).where(MarketBar.trading_date == DAY))
            is not None
        )
    calls = len(fetcher.calls)
    again = schedule_runs._catchup_step(date(2026, 9, 7), 5)
    assert again["missing_dates"] == [] and len(fetcher.calls) == calls


# --- a first no-session answer waits for the 21:30 trigger (Issue #185 item 6)


def test_first_no_session_answer_for_today_is_confirmed_by_the_next_trigger(
    database, monkeypatch
):
    steps = Steps(
        monkeypatch,
        collect={"status": "skipped", "records": 0, "no_data_dates": [DAY.isoformat()]},
    )
    monkeypatch.setattr(schedule_runs, "_today", lambda: DAY)
    first = pipeline.run_daily(DAY)
    assert first["status"] == "non_trading_unconfirmed"
    assert pipeline.run_daily(DAY)["status"] == "non_trading_day"
    assert pipeline.run_daily(DAY)["reason"] == "already_complete"
    assert steps.calls == ["collect", "collect"]
    rows, by_run = runs(database)
    assert [row.status for row in rows] == [
        "non_trading_unconfirmed",
        "non_trading_day",
        "skipped",
    ]
    assert (
        rows[0].error is None
        and rows[0].summary_json["reason"] == "official_no_session_unconfirmed"
    )
    assert by_run[rows[0].id]["analyze"].status == "skipped"


def test_trading_data_at_the_second_trigger_replaces_an_unconfirmed_no_session(
    database, monkeypatch
):
    steps = Steps(monkeypatch, collect={"status": "skipped", "records": 0})
    monkeypatch.setattr(schedule_runs, "_today", lambda: DAY)
    assert pipeline.run_daily(DAY)["status"] == "non_trading_unconfirmed"
    steps.results["collect"] = {"status": "success", "records": 10}
    assert pipeline.run_daily(DAY)["status"] == "success"


# --- non-core source warnings (Issue #185 item 5) -------------------------


class CodedFetcher(FixtureFetcher):
    """FixtureFetcher with numeric industry codes, which collect requires."""

    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            return [
                dict(row, Industry="01" if row["Code"] == "1101" else "24")
                for row in payload
            ]
        return payload


class OutageFetcher(CodedFetcher):
    def __init__(self, failing):
        super().__init__()
        self.failing = failing

    def __call__(self, url, **kwargs):
        if any(url.startswith(prefix) for prefix in self.failing):
            self.calls.append(url)
            raise sources.OfficialDataError(f"fixture outage {url}")
        return super().__call__(url, **kwargs)


def test_noncore_source_warnings_keep_the_collect_successful(database):
    failing = (
        sources.TWSE_EVENT_ENDPOINT,
        sources.TWSE_FUNDAMENTAL_ENDPOINT,
        sources.TPEX_EVENT_ENDPOINT,
        sources.TPEX_FUNDAMENTAL_ENDPOINT,
        sources.TPEX_SUSPEND_ENDPOINT,
        sources.TPEX_SUSPEND_HISTORY_ENDPOINT,
        # The display-only market summary (Issue #275).
        sources.TPEX_HIGHLIGHT_ENDPOINT,
    )
    result = pipeline.collect(DAY, adapter=combined(OutageFetcher(failing)))
    assert result["status"] == "success", result
    assert result["core_warnings"] == [] and len(result["noncore_warnings"]) == 7
    assert result["warnings"] == result["noncore_warnings"]
    with database() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert (
            run.status == "success" and len(run.metadata_json["noncore_warnings"]) == 7
        )


def test_core_source_warning_keeps_the_collect_partial(database):
    failing = (sources.TWSE_MARGIN_HISTORY_ENDPOINT, sources.TWSE_EVENT_ENDPOINT)
    result = pipeline.collect(DAY, adapter=combined(OutageFetcher(failing)))
    assert result["status"] == "partial"
    assert [w.split(" ")[:3] for w in result["core_warnings"]] == [
        ["TWSE", "margin", "chips"]
    ]
    assert [w.split(" ")[:3] for w in result["noncore_warnings"]] == [
        ["TWSE", "MOPS", "events"]
    ]


def test_split_collect_warnings_treats_unknown_warnings_as_core():
    core, noncore = pipeline.split_collect_warnings(
        [
            "TPEx MOPS fundamentals unavailable: x",
            "TWSE MI_INDEX unavailable for 2026-10-16 endpoint=...: x",
            "holiday_capture_unknown:{}",
            "something new",
        ]
    )
    assert noncore == ["TPEx MOPS fundamentals unavailable: x"]
    assert len(core) == 3


def test_daily_runs_analyze_after_a_collect_with_only_noncore_warnings(
    database, monkeypatch
):
    warning = "TWSE MOPS events unavailable: fixture"
    steps = Steps(
        monkeypatch,
        collect={
            "status": "success",
            "records": 9,
            "warnings": [warning],
            "core_warnings": [],
            "noncore_warnings": [warning],
        },
    )
    assert pipeline.run_daily(DAY)["status"] == "success"
    assert "analyze" in steps.calls
    rows, _ = runs(database)
    assert rows[0].summary_json["noncore_warnings"] == [warning]
    # A partial run names only the warnings that made it partial.
    core = "TPEx margin feed returned no rows for 2026-09-07"
    steps.results["collect"] = {
        "status": "partial",
        "records": 9,
        "warnings": [warning, core],
        "core_warnings": [core],
        "noncore_warnings": [warning],
    }
    assert pipeline.run_daily(DAY + timedelta(days=3))["status"] == "partial"
    rows, _ = runs(database)
    assert rows[-1].error == "collect partial: " + core


# --- a fill keeps the row's raw pointer (Issue #185 item 4) -----------------


def test_filling_empty_values_keeps_provenance_and_records_the_fill(database):
    fetcher = CodedFetcher()
    first = pipeline.collect(DAY, adapter=combined(fetcher))
    assert first["status"] == "success"
    with database() as db:
        universe_raw = db.scalar(
            select(RawPayload.id).where(
                RawPayload.endpoint == sources.TWSE_LISTED_ENDPOINT
            )
        )
        bar = _bar(db, "1101")
        bar_raw, turnover = bar.raw_payload_id, (bar.turnover, bar.turnover_status)
        assert turnover[1] == "available"
        # Stands in for an earlier capture whose turnover was unavailable.
        bar.turnover, bar.turnover_status, bar.turnover_reason = (
            0.0,
            "unavailable",
            "missing",
        )
        bar.raw_payload_id = universe_raw
        stamp = bar.collected_at
        chip = db.scalar(
            select(ChipSnapshot).where(ChipSnapshot.instrument_id == bar.instrument_id)
        )
        chip_raw, margin = chip.raw_payload_id, chip.margin_balance
        chip.margin_balance = None
        chip.raw_payload_id = universe_raw
        db.execute(update(IngestionRun).values(status="partial"))
        db.commit()

    second = pipeline.collect(DAY, adapter=combined(fetcher))
    assert second["status"] == "success" and second["value_fills"] == 2
    with database() as db:
        bar = _bar(db, "1101")
        assert (
            (bar.turnover, bar.turnover_status),
            bar.raw_payload_id,
            bar.collected_at,
        ) == (turnover, universe_raw, stamp)
        chip = db.scalar(
            select(ChipSnapshot).where(ChipSnapshot.instrument_id == bar.instrument_id)
        )
        assert (chip.margin_balance, chip.raw_payload_id) == (margin, universe_raw)
        groups = db.get(IngestionRun, second["run_id"]).metadata_json[
            "value_fill_groups"
        ]
    assert {
        (g["table"], tuple(g["fields"]), g["raw_payload_id"], tuple(g["symbols"]))
        for g in groups
    } == {
        ("market_bars", ("turnover",), bar_raw, ("1101",)),
        ("chip_snapshots", ("margin_balance",), chip_raw, ("1101",)),
    }
    assert all(
        g["exchange"] == "TWSE" and g["trading_date"] == DAY.isoformat() for g in groups
    )

    # force overwrites a differing stored value, so the pointer moves to the capture.
    with database() as db:
        _bar(db, "1101").close += 1
        db.commit()
    pipeline.collect(DAY, adapter=combined(fetcher), force=True)
    with database() as db:
        assert _bar(db, "1101").raw_payload_id == bar_raw


# --- PR #218 review: unconfirmed closures and snapshot coverage -------------


def test_unconfirmed_no_session_is_fetched_again_by_catchup(database):
    for day in (
        date(2026, 10, 15),
        date(2026, 10, 14),
        date(2026, 10, 13),
        date(2026, 10, 12),
    ):
        _collect_run(database, day)
    friday = date(2026, 10, 16)
    # 18:30 Taipei on Friday: both markets said no session, 21:30 never asked again.
    _collect_run(
        database,
        friday,
        status="skipped",
        taiex=0,
        finished_at=datetime(2026, 10, 16, 10, 35),
    )
    with database() as db:
        db.add(
            ScheduleRun(
                job="daily",
                target_date=friday,
                trigger="scheduler",
                status="non_trading_unconfirmed",
                started_at=datetime(2026, 10, 16, 10, 30),
            )
        )
        db.commit()
    assert schedule_runs.catchup_dates(MONDAY)[1] == [friday]
    # A no-data answer obtained after Friday ended (a later catch-up) is final.
    with database() as db:
        db.execute(
            update(IngestionRun)
            .where(IngestionRun.run_date == friday)
            .values(finished_at=datetime(2026, 10, 18, 10, 35))
        )
        db.commit()
    assert friday not in schedule_runs.catchup_dates(MONDAY)[0]
    # So is a daily run that confirmed it at 21:30.
    with database() as db:
        db.execute(
            update(IngestionRun)
            .where(IngestionRun.run_date == friday)
            .values(finished_at=datetime(2026, 10, 16, 10, 35))
        )
        db.add(
            ScheduleRun(
                job="daily",
                target_date=friday,
                trigger="scheduler",
                status="non_trading_day",
                started_at=datetime(2026, 10, 16, 13, 30),
            )
        )
        db.commit()
    checked, missing = schedule_runs.catchup_dates(MONDAY)
    assert friday not in checked and missing == [date(2026, 10, 9)]


def test_historical_refetch_keeps_the_snapshot_event_coverage(database):
    fetcher = CodedFetcher()
    snapshot = pipeline.collect(DAY, adapter=combined(fetcher))
    assert snapshot["status"] == "success"
    with database() as db:
        run = db.get(IngestionRun, snapshot["run_id"])
        coverage = dict(run.metadata_json["event_coverage"])
        quality = {
            (row.entity_type, row.entity_key): (row.status, row.checks_json)
            for row in db.scalars(
                select(DataQuality).where(
                    DataQuality.entity_type.in_(("mops_events", "mops_fundamentals")),
                    DataQuality.as_of_date == DAY,
                )
            )
        }
        db.execute(update(IngestionRun).values(status="partial"))
        db.commit()
    # The historical default would be an empty observed_event_dates list.
    assert DAY.isoformat() in coverage["observed_event_dates"] and len(quality) == 4

    historical = sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher, snapshot_feeds=False),
        sources.TpexAdapter(fetcher, snapshot_feeds=False),
    )
    refetched = pipeline.collect(DAY, adapter=historical)
    assert (
        refetched["status"] == "success" and refetched["run_id"] == snapshot["run_id"]
    )
    assert refetched["event_coverage"] == coverage
    with database() as db:
        assert (
            db.get(IngestionRun, snapshot["run_id"]).metadata_json["event_coverage"]
            == coverage
        )
        assert {
            (row.entity_type, row.entity_key): (row.status, row.checks_json)
            for row in db.scalars(
                select(DataQuality).where(
                    DataQuality.entity_type.in_(("mops_events", "mops_fundamentals")),
                    DataQuality.as_of_date == DAY,
                )
            )
        } == quality
