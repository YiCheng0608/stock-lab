"""Today's TPEx notices identify announcements, not suspended OHLC bars."""

import hashlib
import json
import socket
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Event, IngestionRun, Instrument, MarketBar, RawPayload, Signal, SignalEvaluation
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher


DAY = date(2026, 9, 4)
WARNING = "announcements do not establish bar suspension status"


class NoticeFetcher(FixtureFetcher):
    def __init__(self, today, history=None):
        super().__init__()
        self.today = today
        self.history = history or []

    def __call__(self, url, **kwargs):
        if url == sources.TPEX_SUSPEND_ENDPOINT:
            self.calls.append(url)
            if isinstance(self.today, Exception):
                raise self.today
            return self.today
        if url == sources.TPEX_SUSPEND_HISTORY_ENDPOINT:
            self.calls.append(url)
            return self.history
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            # collect requires source taxonomy codes; the older adapter-only
            # fixture uses display labels that are deliberately rejected.
            return [dict(row, Industry="01" if row["Code"] == "1101" else "24") for row in payload]
        return payload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in TPEx notice regressions")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.mark.parametrize("captured_day", [DAY, date(2026, 9, 13)], ids=["same-day", "backfill"])
@pytest.mark.parametrize("today", [
    [{"Date": "1150904", "SecuritiesCompanyCode": "7001", "恢復交易": "115/09/04 09:00", "暫停交易": ""}],
    [{"Date": "1150904", "SecuritiesCompanyCode": "7001", "暫停交易": "115/09/07 09:00", "恢復交易": ""}],
    [{"SecuritiesCompanyCode": "7001"}],
    [{"SecuritiesCompanyCode": "700019"}],
    [{}],
    [None, "malformed row"],
], ids=["resumption", "future-suspension", "code-only", "out-of-scope", "missing-code", "malformed"])
def test_notice_does_not_override_date_scoped_bars(today, captured_day, monkeypatch):
    class CaptureClock(datetime):
        @classmethod
        def utcnow(cls):
            return cls(captured_day.year, captured_day.month, captured_day.day, 10)

    monkeypatch.setattr(sources, "datetime", CaptureClock)
    fetcher = NoticeFetcher(today)
    batch = sources.TpexAdapter(fetcher).fetch(DAY, DAY)
    assert {(bar.symbol, bar.trading_date) for bar in batch.bars} == {("7001", DAY), ("00679B", DAY)}
    assert all(not bar.is_suspended and bar.volume > 0 for bar in batch.bars)
    assert any(WARNING in warning for warning in batch.warnings)
    raw = next(item for item in batch.payloads if item.endpoint == sources.TPEX_SUSPEND_ENDPOINT)
    assert raw.collected_at.date() == captured_day
    assert json.loads(raw.payload_path.read_text(encoding="utf-8")) == today
    assert hashlib.sha256(raw.payload_path.read_bytes()).hexdigest() == raw.sha256
    assert not any(event.event_type in {"suspension", "resumption"} for event in batch.events)


def test_empty_notice_is_not_open_session_evidence():
    batch = sources.TpexAdapter(NoticeFetcher([])).fetch(DAY, DAY)
    assert not any(WARNING in warning for warning in batch.warnings)
    assert batch.no_data_dates == []
    assert batch.event_coverage["status"] == "unsupported"
    assert batch.event_coverage["empty_dates"] == []
    assert any(raw.endpoint == sources.TPEX_SUSPEND_ENDPOINT and raw.payload == [] for raw in batch.payloads)


def test_independent_flags_and_multiple_dates_are_preserved(monkeypatch):
    adapter = sources.TpexAdapter(NoticeFetcher([{"SecuritiesCompanyCode": "7001"}]))
    real_fetch_bars = adapter.fetch_bars

    def supplied_bars(symbols, start, end):
        bars, payloads = real_fetch_bars(symbols, DAY, DAY)
        # Represents a separately supported bar flag, not notice inference.
        return [replace(bar, is_suspended=bar.symbol == "00679B") for bar in bars] + [
            replace(bars[0], trading_date=date(2026, 9, 3), is_suspended=True)
        ], payloads

    monkeypatch.setattr(adapter, "fetch_bars", supplied_bars)
    monkeypatch.setattr(adapter, "fetch_chips", lambda *args: ([], [], []))
    batch = adapter.fetch(date(2026, 9, 3), DAY)
    assert {(b.symbol, b.trading_date): b.is_suspended for b in batch.bars} == {
        ("7001", DAY): False, ("00679B", DAY): True, ("7001", date(2026, 9, 3)): True,
    }


def test_history_dates_and_future_details_remain_unchanged():
    row = {"SecuritiesCompanyCode": "7001", "DateOfSuspendedTrading": "2026/09/02", "DateOfResumedTrading": "2026/09/10"}
    batch = sources.TpexAdapter(NoticeFetcher([{"SecuritiesCompanyCode": "7001"}], [row])).fetch(DAY, DAY)
    events = [event for event in batch.events if event.source == "tpex_suspension_history"]
    assert len(events) == 1
    assert events[0].event_type == "suspension" and events[0].event_date == date(2026, 9, 2)
    assert events[0].details == {
        "suspended_date": "2026-09-02", "resumed_date": "2026-09-10", "interval_end": "2026-09-10",
        "source_row": row, "data_as_of": DAY.isoformat(),
    }
    raw = next(item for item in batch.payloads if item.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT)
    assert events[0].payload_sha256 == raw.sha256


def test_unavailable_today_keeps_other_captures_and_history():
    row = {"SecuritiesCompanyCode": "7001", "DateOfSuspendedTrading": "2026/09/02", "DateOfResumedTrading": "2026/09/03"}
    batch = sources.TpexAdapter(NoticeFetcher(sources.OfficialDataError("fixture unavailable"), [row])).fetch(DAY, DAY)
    assert any(warning.startswith("TPEx suspension feed unavailable:") and "fixture unavailable" in warning for warning in batch.warnings)
    assert not any(raw.endpoint == sources.TPEX_SUSPEND_ENDPOINT for raw in batch.payloads)
    assert any(raw.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT for raw in batch.payloads)
    assert {event.event_type for event in batch.events} >= {"suspension", "resumption"}
    assert all(not bar.is_suspended for bar in batch.bars)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'notice.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield factory
    engine.dispose()


def combined(fetcher, tpex=None):
    return sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher), tpex or sources.TpexAdapter(fetcher))


def test_collect_partial_raw_reuse_and_existing_rows_require_refetch(database):
    fetcher = NoticeFetcher([])
    adapter = combined(fetcher)
    first = pipeline.collect(DAY, adapter=adapter)
    assert first["status"] == "success", first
    with database() as db:
        instrument = db.scalar(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol == "7001"))
        instrument_id = instrument.id
        bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument_id, MarketBar.trading_date == DAY))
        assert bar.is_suspended is False
        bar.is_suspended = True  # Simulate an existing row from the old collector.
        untouched = MarketBar(instrument_id=instrument_id, trading_date=date(2026, 9, 2), open=50, high=52, low=49,
                              close=51, adj_close=51, volume=2000, turnover=102000, is_suspended=True, source="fixture")
        db.add(untouched)
        db.commit()

    fetcher.today = [{"SecuritiesCompanyCode": "7001", "恢復交易": "115/09/04 09:00"}]
    calls = len(fetcher.calls)
    reuse = pipeline.collect(DAY, adapter=adapter)
    assert reuse["idempotent_reuse"] is True and len(fetcher.calls) == calls

    def evaluate(key):
        with database() as db:
            signal = Signal(signal_key=key, signal_date=date(2026, 9, 3), instrument_id=instrument_id,
                            status="conditional", entry_type="breakout", breakout_price=51, invalid_price=45,
                            target_1=60, data_quality="complete")
            db.add(signal)
            db.flush()
            pipeline._evaluate_signal_tracking(db, signal)
            db.flush()
            evaluation = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id))
            observed = (evaluation.status, evaluation.breakout_price_trigger, evaluation.suspended, evaluation.comparable)
            db.commit()
            return observed

    assert evaluate("legacy-notice") == ("suspended", False, True, False)
    fixed = pipeline.collect(DAY, adapter=adapter, force=True)
    assert fixed["status"] == "partial" and any(WARNING in warning for warning in fixed["warnings"])
    assert fixed["records"] == first["records"] and fixed["no_data_dates"] == []
    assert evaluate("corrected-notice") == ("active", True, False, True)
    with database() as db:
        assert db.scalar(select(MarketBar.is_suspended).where(MarketBar.instrument_id == instrument_id, MarketBar.trading_date == date(2026, 9, 2))) is True
        # Recollecting OHLC never rewrites old signal evaluations automatically.
        old_id = db.scalar(select(Signal.id).where(Signal.signal_key == "legacy-notice"))
        assert db.scalar(select(SignalEvaluation.status).where(SignalEvaluation.signal_id == old_id)) == "suspended"
        run = db.get(IngestionRun, fixed["run_id"])
        assert any(WARNING in warning for warning in run.metadata_json["warnings"])
        raws = db.scalars(select(RawPayload).where(RawPayload.ingestion_run_id == run.id, RawPayload.endpoint == sources.TPEX_SUSPEND_ENDPOINT)).all()
        assert len(raws) == 2  # Empty and nonempty responses are both auditable.
        assert any(json.loads(Path(raw.payload_path).read_text(encoding="utf-8")) == fetcher.today for raw in raws)
        for raw in raws:
            assert hashlib.sha256(Path(raw.payload_path).read_bytes()).hexdigest() == raw.sha256
        bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument_id, MarketBar.trading_date == DAY))
        assert db.get(RawPayload, bar.raw_payload_id).endpoint == sources.TPEX_HISTORY_API
        assert db.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    calls = len(fetcher.calls)
    retried = pipeline.collect(DAY, adapter=adapter)
    assert retried["status"] == "partial" and not retried.get("idempotent_reuse")
    assert len(fetcher.calls) > calls  # Partial runs are not successful-run reuse.


def test_later_collection_failure_retains_today_raw(database):
    fetcher = NoticeFetcher([{"SecuritiesCompanyCode": "7001"}])

    class LaterFailure(sources.TpexAdapter):
        def fetch(self, start, end):
            super().fetch(start, end)
            raise sources.OfficialDataError("fixture failure after notice capture")

    result = pipeline.collect(DAY, adapter=combined(fetcher, LaterFailure(fetcher)))
    assert result["status"] == "failed" and result["records"] == 0
    with database() as db:
        raw = db.scalar(select(RawPayload).where(RawPayload.ingestion_run_id == result["run_id"], RawPayload.endpoint == sources.TPEX_SUSPEND_ENDPOINT))
        assert raw and json.loads(Path(raw.payload_path).read_text(encoding="utf-8")) == fetcher.today
        assert db.scalar(select(MarketBar)) is None
        assert db.scalar(select(Event)) is None
