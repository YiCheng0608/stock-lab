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
from app.models import ChipSnapshot, IngestionRun, Instrument, MarketBar, ScheduleRun, ScheduleRunStep
import worker.backfill as backfill
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
import worker.sources as sources
from test_sources import FixtureFetcher


DAY = date(2026, 9, 4)


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
            "analyze": {"status": "success", "signals_upserted": 3},
            "evaluate": {"status": "success", "evaluations_written": 4, "settlements_written": 1},
            "candidates": {"status": "success", "records": 2},
            "indicators": {"status": "not_configured", "reason": "fixture"},
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
        monkeypatch.setattr(pipeline, "analyze", make("analyze"))
        monkeypatch.setattr(pipeline, "evaluate", make("evaluate"))
        monkeypatch.setattr(schedule_runs, "_candidate_step", make("candidates"))
        monkeypatch.setattr(schedule_runs, "_indicator_step", make("indicators"))


def runs(factory):
    with factory() as db:
        rows = db.scalars(select(ScheduleRun).order_by(ScheduleRun.id)).all()
        steps = {
            row.id: {
                step.step: step
                for step in db.scalars(select(ScheduleRunStep).where(ScheduleRunStep.schedule_run_id == row.id)).all()
            }
            for row in rows
        }
        return rows, steps


def test_daily_logs_every_step_and_a_rerun_is_recorded_without_running_again(database, monkeypatch):
    steps = Steps(monkeypatch)
    first = pipeline.run_daily(DAY, trigger="scheduler")
    assert first["status"] == "success"
    assert steps.calls == ["collect", "analyze", "evaluate", "candidates", "indicators"]
    rows, by_run = runs(database)
    assert [(row.status, row.trigger, row.target_date, row.records) for row in rows] == [("success", "scheduler", DAY, 12)]
    logged = by_run[rows[0].id]
    assert {name: (step.status, step.records) for name, step in logged.items()} == {
        "collect": ("success", 12),
        "analyze": ("success", 3),
        "evaluate": ("success", 5),
        "candidates": ("success", 2),
        "indicators": ("not_configured", None),
    }
    assert all(step.started_at and step.finished_at for step in logged.values())
    assert rows[0].finished_at >= rows[0].started_at

    again = pipeline.run_daily(DAY, trigger="scheduler")
    assert again["status"] == "skipped" and again["reason"] == "already_complete"
    assert again["related_run_id"] == rows[0].id
    assert steps.calls == ["collect", "analyze", "evaluate", "candidates", "indicators"]
    rows, by_run = runs(database)
    assert [row.status for row in rows] == ["success", "skipped"]
    assert by_run[rows[1].id] == {}

    forced = pipeline.run_daily(DAY, force=True)
    assert forced["status"] == "success"
    assert steps.calls.count("collect") == 2


def test_partial_collect_stops_later_steps_and_keeps_the_warning(database, monkeypatch):
    steps = Steps(monkeypatch, collect={"status": "partial", "records": 9, "warnings": ["TWSE margin chips unavailable"]})
    result = pipeline.run_daily(DAY)
    assert result["status"] == "partial"
    assert steps.calls == ["collect"]
    rows, by_run = runs(database)
    assert rows[0].status == "partial" and "TWSE margin chips unavailable" in rows[0].error
    assert {name: step.status for name, step in by_run[rows[0].id].items()} == {
        "collect": "partial",
        "analyze": "skipped",
        "evaluate": "skipped",
        "candidates": "skipped",
        "indicators": "skipped",
    }
    # A partial day is retried by the next trigger instead of being reused.
    steps.results["collect"] = {"status": "success", "records": 10}
    assert pipeline.run_daily(DAY)["status"] == "success"
    assert steps.calls == ["collect", "collect", "analyze", "evaluate", "candidates", "indicators"]


def test_verified_non_trading_day_is_complete(database, monkeypatch):
    steps = Steps(monkeypatch, collect={"status": "skipped", "records": 0, "no_data_dates": [DAY.isoformat()]})
    assert pipeline.run_daily(DAY)["status"] == "non_trading_day"
    assert pipeline.run_daily(DAY)["reason"] == "already_complete"
    assert steps.calls == ["collect"]
    rows, _ = runs(database)
    assert [row.status for row in rows] == ["non_trading_day", "skipped"]
    assert rows[0].error is None


def test_step_exception_is_recorded_and_dependent_steps_are_skipped(database, monkeypatch):
    steps = Steps(monkeypatch, analyze=RuntimeError("fixture analyze crash"))
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    # Indicators depend only on the collected bars, so they still run.
    assert steps.calls == ["collect", "analyze", "indicators"]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert rows[0].status == "failed" and "fixture analyze crash" in rows[0].error
    assert logged["analyze"].status == "failed" and "RuntimeError: fixture analyze crash" in logged["analyze"].error
    assert logged["evaluate"].status == "skipped" and logged["evaluate"].error == "analyze_not_successful"
    assert logged["candidates"].status == "skipped" and logged["candidates"].error == "analyze_not_successful"
    assert logged["indicators"].status == "not_configured"


def test_failed_evaluate_still_runs_candidates_and_indicators(database, monkeypatch):
    steps = Steps(monkeypatch, evaluate={"status": "failed", "error": "fixture evaluate failure"})
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    # candidates read the trading date's signals, which analyze already stored.
    assert steps.calls == ["collect", "analyze", "evaluate", "candidates", "indicators"]
    rows, by_run = runs(database)
    assert rows[0].error == "evaluate: fixture evaluate failure"
    assert by_run[rows[0].id]["candidates"].status == "success"


def test_failed_candidates_fail_the_run_without_blocking_indicators(database, monkeypatch):
    steps = Steps(monkeypatch, candidates=RuntimeError("fixture candidate crash"))
    result = pipeline.run_daily(DAY)
    assert result["status"] == "failed"
    assert steps.calls == ["collect", "analyze", "evaluate", "candidates", "indicators"]
    rows, by_run = runs(database)
    logged = by_run[rows[0].id]
    assert "fixture candidate crash" in rows[0].error
    assert logged["candidates"].status == "failed"
    assert logged["evaluate"].status == "success" and logged["indicators"].status == "not_configured"


def test_candidate_step_without_signals_is_an_acceptable_no_data_step(database, monkeypatch):
    Steps(monkeypatch, candidates={"status": "no_data", "reason": "no_signals_for_date", "records": 0})
    assert pipeline.run_daily(DAY)["status"] == "success"


def test_failed_indicator_batch_fails_the_run(database, monkeypatch):
    Steps(monkeypatch, indicators={"status": "failed", "error": "fixture indicator failure"})
    assert pipeline.run_daily(DAY)["status"] == "failed"
    rows, _ = runs(database)
    assert rows[0].error == "indicators: fixture indicator failure"


def test_running_rows_block_until_stale_then_are_marked_abandoned(database, monkeypatch):
    steps = Steps(monkeypatch)
    now = datetime.utcnow()
    with database() as db:
        db.add(ScheduleRun(job="daily", target_date=DAY, trigger="scheduler", status="running", started_at=now))
        db.commit()
    blocked = pipeline.run_daily(DAY)
    assert blocked["status"] == "skipped" and blocked["reason"] == "already_running"
    assert steps.calls == []
    with database() as db:
        db.execute(update(ScheduleRun).where(ScheduleRun.status == "running").values(started_at=now - timedelta(hours=4)))
        db.commit()
    assert pipeline.run_daily(DAY)["status"] == "success"
    rows, _ = runs(database)
    assert rows[0].status == "failed" and rows[0].error.startswith("abandoned")


def test_indicator_step_is_not_configured_without_the_batch_module(monkeypatch):
    monkeypatch.setattr(schedule_runs, "INDICATOR_MODULE", "worker.missing_indicator_batch_fixture")
    assert schedule_runs._indicator_step(DAY)["status"] == "not_configured"


def test_list_schedule_runs_reports_steps(database, monkeypatch):
    Steps(monkeypatch)
    pipeline.run_daily(DAY)
    listed = schedule_runs.list_schedule_runs(5, DAY)
    assert listed[0]["status"] == "success"
    assert [step["step"] for step in listed[0]["steps"]] == ["collect", "analyze", "evaluate", "candidates", "indicators"]


# --- collect never rewrites stored official values ----------------------


def combined(fetcher):
    return sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher))


def _bar(db, symbol):
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    return db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument.id, MarketBar.trading_date == DAY))


def test_rerun_fills_missing_values_but_keeps_stored_ones(database):
    class Fetcher(FixtureFetcher):
        def __call__(self, url, **kwargs):
            payload = super().__call__(url, **kwargs)
            if url == sources.TWSE_LISTED_ENDPOINT:
                return [dict(row, Industry="01" if row["Code"] == "1101" else "24") for row in payload]
            return payload

    fetcher = Fetcher()
    first = pipeline.collect(DAY, adapter=combined(fetcher))
    assert first["status"] == "success", first
    with database() as db:
        bar = _bar(db, "1101")
        original = (bar.open, bar.close, bar.volume)
        bar.close = original[1] + 1.5  # stands in for a value stored by an earlier run
        chip = db.scalar(select(ChipSnapshot).where(ChipSnapshot.instrument_id == bar.instrument_id))
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
        chip = db.scalar(select(ChipSnapshot).where(ChipSnapshot.instrument_id == bar.instrument_id))
        assert chip.margin_balance == margin
        assert len(db.scalars(select(ChipSnapshot)).all()) == chip_count
        assert len(db.scalars(select(MarketBar)).all()) == len({(b.instrument_id, b.trading_date) for b in db.scalars(select(MarketBar)).all()})
        run = db.get(IngestionRun, second["run_id"])
        assert any(item["field"] == "close" for item in run.metadata_json["value_conflict_samples"])
        untouched = _bar(db, "0050")
        untouched_state = (untouched.close, untouched.raw_payload_id, untouched.collected_at)

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
        {"SecuritiesCompanyCode": "6264", "發言日期": "1151016", "發言時間": "194240", "主旨": title, "說明": "B unit"},
        {"SecuritiesCompanyCode": "6264", "發言日期": "1151016", "發言時間": "194110", "主旨": title, "說明": "A unit"},
        {"SecuritiesCompanyCode": "6264", "發言日期": "1151016", "發言時間": "194110", "主旨": title, "說明": "A unit"},
        {"SecuritiesCompanyCode": "6264", "發言日期": "1151016", "發言時間": "194341", "主旨": title, "說明": "C unit"},
        {"SecuritiesCompanyCode": "6265", "發言日期": "1151016", "發言時間": "100000", "主旨": title, "說明": "other issuer"},
    ]
    events = sources.parse_mops_event_rows(rows, exchange="TPEx", endpoint="fixture")
    titles = {(event.symbol, event.description): event.title for event in events}
    assert len(events) == 4
    assert titles[("6264", "A unit")] == title
    assert titles[("6264", "B unit")] == f"{title}（發言時間 19:42:40）"
    assert titles[("6264", "C unit")] == f"{title}（發言時間 19:43:41）"
    assert titles[("6265", "other issuer")] == title
    # An earlier fetch that only saw the first announcement stored the same title.
    first_only = sources.parse_mops_event_rows(rows[1:2], exchange="TPEx", endpoint="fixture")
    assert first_only[0].title == title


# --- historical fetch plan ----------------------------------------------


def test_historical_adapter_skips_current_feeds_and_reuses_the_universe(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = FixtureFetcher()
    adapter = sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher, snapshot_feeds=False),
        sources.TpexAdapter(fetcher, snapshot_feeds=False),
    )
    first = adapter.fetch(DAY, DAY)
    second = adapter.fetch(DAY, DAY)
    current_only = {
        sources.TWSE_DAILY_ENDPOINT, sources.TWSE_INDEX_ENDPOINT, sources.TWSE_ACTION_ENDPOINT,
        sources.TWSE_EVENT_ENDPOINT, sources.TWSE_FUNDAMENTAL_ENDPOINT, sources.TPEX_ACTION_ENDPOINT,
        sources.TPEX_SUSPEND_ENDPOINT, sources.TPEX_SUSPEND_HISTORY_ENDPOINT, sources.TPEX_EVENT_ENDPOINT,
        sources.TPEX_FUNDAMENTAL_ENDPOINT,
    }
    assert not current_only.intersection(fetcher.calls)
    for endpoint in (sources.TWSE_LISTED_ENDPOINT, sources.TPEX_LISTED_ENDPOINT):
        assert fetcher.calls.count(endpoint) == 1
    for batch in (first, second):
        assert batch.snapshot_feeds is False
        assert any(bar.symbol == "TAIEX" and bar.trading_date == DAY for bar in batch.bars)
        assert {bar.symbol for bar in batch.bars} >= {"1101", "7001"}
        assert batch.chips and not batch.events and not batch.actions
        assert batch.event_coverage["status"] == "unsupported"
        # The reused universe payloads stay attached to every batch for provenance.
        assert any(p.endpoint == sources.TWSE_LISTED_ENDPOINT for p in batch.payloads)


def test_snapshot_collect_uses_the_dated_report_taiex_before_the_current_index(tmp_path, monkeypatch):
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
    assert all((end - start).days <= pipeline.OFFICIAL_MAX_BACKFILL_DAYS for start, end in windows)
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
        return {"id": len(calls), "status": "partial" if len(calls) == 1 else "success", "metadata": metadata}

    monkeypatch.setattr(backfill, "targeted_backfill", fake)
    result = backfill.chunked_backfill(date(2024, 10, 14), date(2025, 3, 1), adapter=object())
    assert len(calls) == 2 and calls[0][2] is calls[1][2]
    assert result["status"] == "partial"
    assert result["partial_dates"] == [calls[0][1].isoformat()]
    assert result["skipped_non_trading_dates"] == ["2024-12-25"]
    assert [window["run_id"] for window in result["windows"]] == [1, 2]


def test_official_host_requests_are_spaced(monkeypatch):
    clock = {"now": 100.0}
    sleeps = []
    monkeypatch.setattr(sources.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: sleeps.append(seconds) or clock.__setitem__("now", clock["now"] + seconds))
    monkeypatch.setattr(sources, "_host_last_request", {})
    sources._throttle_official_host("https://www.twse.com.tw/rwd/zh/fund/T86?date=20260904")
    clock["now"] += 0.5
    sources._throttle_official_host("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20260904")
    sources._throttle_official_host("https://fixture.example/unthrottled")
    assert sleeps == [pytest.approx(sources.OFFICIAL_HOST_MIN_INTERVAL_SECONDS["www.twse.com.tw"] - 0.5)]


def test_analyze_uses_the_pinned_collect_run_even_when_another_is_newer(database):
    with database() as db:
        pinned = IngestionRun(run_type="collect", source="official", run_date=date(2026, 9, 3), status="success",
                              records=1, data_as_of="2026-09-03", updated_at=datetime(2026, 9, 3, 8))
        failed = IngestionRun(run_type="collect", source="official", run_date=date(2026, 9, 2), status="partial",
                              records=1, data_as_of="2026-09-02", updated_at=datetime(2026, 9, 2, 8))
        newer = IngestionRun(run_type="collect", source="official", run_date=DAY, status="success",
                             records=1, data_as_of=DAY.isoformat(), updated_at=datetime(2026, 9, 5, 8))
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
        db.execute(text("UPDATE alembic_version SET version_num = :value"), {"value": REVISIONS[-2]})
        db.commit()
    assert schedule_runs._ensure_schema() == "upgraded" and calls == ["init_db"]


def test_preflight_skip_is_logged_without_running_steps_and_does_not_complete_the_day(database, monkeypatch):
    steps = Steps(monkeypatch)
    skipped = schedule_runs.record_preflight_skip(DAY, reason="low_memory")
    assert skipped["status"] == "skipped" and skipped["reason"] == "low_memory"
    assert steps.calls == []
    # A declined start is not completion: the next trigger still runs the day.
    assert pipeline.run_daily(DAY)["status"] == "success"
    rows, _ = runs(database)
    assert [(row.status, row.summary_json.get("reason")) for row in rows] == [("skipped", "low_memory"), ("success", None)]
    with pytest.raises(ValueError):
        schedule_runs.record_preflight_skip(DAY, reason="unknown")


def test_running_row_whose_process_is_gone_is_abandoned_at_once(database, monkeypatch):
    steps = Steps(monkeypatch)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    now = datetime.utcnow()
    with database() as db:
        db.add(ScheduleRun(job="daily", target_date=DAY, trigger="scheduler", status="running",
                           started_at=now, host=socket.gethostname(), pid=os.getpid()))
        db.commit()
    # A live owner on this host still blocks a second trigger.
    assert pipeline.run_daily(DAY)["reason"] == "already_running"
    with database() as db:
        db.execute(update(ScheduleRun).where(ScheduleRun.status == "running").values(pid=dead.pid))
        db.commit()
    # The 18:30 process was killed: the 21:30 trigger reruns well before the time limit.
    assert pipeline.run_daily(DAY)["status"] == "success"
    assert steps.calls == ["collect", "analyze", "evaluate", "candidates", "indicators"]
    rows, _ = runs(database)
    assert rows[0].status == "failed" and f"process {dead.pid}" in rows[0].error
    assert rows[-1].host == socket.gethostname() and rows[-1].pid == os.getpid()


def test_running_row_from_another_host_waits_for_the_time_limit(database, monkeypatch):
    Steps(monkeypatch)
    with database() as db:
        db.add(ScheduleRun(job="daily", target_date=DAY, trigger="scheduler", status="running",
                           started_at=datetime.utcnow() - timedelta(hours=2), host="other-host", pid=1))
        db.commit()
    assert pipeline.run_daily(DAY)["reason"] == "already_running"


def test_cli_schedule_runs_and_daily_exit_codes(monkeypatch, capsys):
    import json as json_module

    import worker.cli as cli

    monkeypatch.setattr(cli, "list_schedule_runs", lambda limit, target: [])
    monkeypatch.setattr(sys, "argv", ["worker.cli", "schedule-runs"])
    cli.main()  # must not raise on a list result
    assert json_module.loads(capsys.readouterr().out) == []
    for status, code in (("success", 0), ("partial", 2), ("failed", 1), ("non_trading_day", 0)):
        monkeypatch.setattr(cli, "run_daily", lambda *args, _status=status, **kwargs: {"status": _status})
        monkeypatch.setattr(sys, "argv", ["worker.cli", "daily", "--date", DAY.isoformat()])
        with pytest.raises(SystemExit) as exited:
            cli.main()
        assert exited.value.code == code



def _bar_record(**overrides):
    values = dict(symbol="1101", trading_date=DAY, open=10.0, high=11.0, low=9.5, close=10.5, volume=1000,
                  turnover=0.0, turnover_status="unavailable", turnover_reason="missing")
    values.update(overrides)
    return sources.BarRecord(**values)


def test_turnover_amount_status_and_reason_change_together(database):
    with database() as db:
        instrument = Instrument(symbol="1101", name="fixture", exchange="TWSE", instrument_type="stock")
        db.add(instrument)
        db.flush()

        def upsert(record, *, overwrite=False):
            conflicts = []
            bar = pipeline._upsert_official_bar(db, instrument, record, None, overwrite=overwrite, conflicts=conflicts)
            db.flush()
            return (bar.turnover, bar.turnover_status, bar.turnover_reason), conflicts

        assert upsert(_bar_record())[0] == (0.0, "unavailable", "missing")
        # An available amount fills the empty group as a whole.
        available = _bar_record(turnover=10500.0, turnover_status="available", turnover_reason=None)
        assert upsert(available)[0] == (10500.0, "available", None)
        # An unavailable re-fetch never downgrades it, with or without force.
        assert upsert(_bar_record())[0] == (10500.0, "available", None)
        assert upsert(_bar_record(), overwrite=True)[0] == (10500.0, "available", None)
        # A different available amount is a conflict unless forced.
        revised = _bar_record(turnover=11000.0, turnover_status="available", turnover_reason=None)
        state, conflicts = upsert(revised)
        assert state == (10500.0, "available", None) and [item["field"] for item in conflicts] == ["turnover"]
        assert upsert(revised, overwrite=True)[0] == (11000.0, "available", None)


def test_forced_refetch_keeps_values_the_source_left_empty(database):
    with database() as db:
        instrument = Instrument(symbol="1101", name="fixture", exchange="TWSE", instrument_type="stock")
        db.add(instrument)
        db.flush()
        instruments = {("TWSE", "1101"): instrument}
        full = sources.ChipRecord(symbol="1101", trading_date=DAY, foreign_buy=10, trust_buy=2, dealer_buy=1,
                                  margin_balance=500, margin_change=5)
        pipeline._upsert_official_chip(db, full, instruments, None, overwrite=True)
        db.flush()
        partial = sources.ChipRecord(symbol="1101", trading_date=DAY, foreign_buy=12, trust_buy=2, dealer_buy=1)
        pipeline._upsert_official_chip(db, partial, instruments, None, overwrite=True)
        db.flush()
        chip = db.scalar(select(ChipSnapshot).where(ChipSnapshot.instrument_id == instrument.id))
        assert (chip.foreign_buy, chip.margin_balance, chip.margin_change) == (12, 500, 5)


def test_chunked_backfill_is_not_success_when_a_window_failed(monkeypatch):
    results = iter([
        {"id": 1, "status": "partial", "error": None,
         "metadata": {"completed_dates": ["2024-10-14"], "skipped_non_trading_dates": ["2024-10-31"]}},
        {"id": 2, "status": "failed", "error": "scope resolved to no active instruments", "metadata": {}},
    ])
    monkeypatch.setattr(backfill, "targeted_backfill", lambda *args, **kwargs: next(results))
    result = backfill.chunked_backfill(date(2024, 10, 14), date(2025, 3, 1), adapter=object())
    assert result["partial_dates"] == [] and result["failed_dates"] == []
    assert result["status"] == "partial"
    # A window that is partial only because of non-trading dates counts as complete.
    results = iter([
        {"id": 3, "status": "partial", "error": None,
         "metadata": {"completed_dates": ["2024-10-14"], "skipped_non_trading_dates": ["2024-10-31"]}},
    ])
    assert backfill.chunked_backfill(date(2024, 10, 14), date(2024, 11, 1), adapter=object())["status"] == "success"


def test_0011_migration_matches_the_mapped_schedule_tables(database):
    from sqlalchemy import text as sql_text
    from sqlalchemy.pool import StaticPool

    from app.db import Base

    def shape(connection):
        result = {}
        for table in ("schedule_runs", "schedule_run_steps"):
            columns = [tuple(row[1:6]) for row in connection.execute(sql_text(f"PRAGMA table_info({table})"))]
            indexes = {}
            for row in connection.execute(sql_text(f"PRAGMA index_list({table})")):
                cols = [info[2] for info in connection.execute(sql_text(f"PRAGMA index_info('{row[1]}')"))]
                indexes[tuple(cols)] = bool(row[2])
            fks = sorted(tuple(row[2:5]) for row in connection.execute(sql_text(f"PRAGMA foreign_key_list({table})")))
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
