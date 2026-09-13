"""TPEx history row numbers must never select a security or hide its code."""

import hashlib
import json
import socket
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Event, Instrument, MarketBar, RawPayload, Signal, SignalEvaluation
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher


DAY = date(2026, 9, 4)
DATES = {"DateOfSuspendedTrading": "115/09/02", "DateOfResumedTrading": "115/09/03"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in TPEx identity regressions")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def parse(row, allowed=None):
    return sources.parse_tpex_suspension_history_rows(
        [row], allowed_symbols=allowed if allowed is not None else {"7001", "00679B", "0050"},
        endpoint=sources.TPEX_SUSPEND_HISTORY_ENDPOINT, data_as_of=DAY.isoformat(),
        payload_sha256="fixture-sha",
    )


@pytest.mark.parametrize("identity,expected", [
    ({"Serial": "7001"}, None),
    ({"Serial": "7001", "SecuritiesCompanyCode": ""}, None),
    ({"Serial": "7001", "SecuritiesCompanyCode": "  "}, None),
    ({"Serial": "7001", "SecuritiesCompanyCode": None}, None),
    ({}, None),
    ({"Serial": "1", "Code": "7001"}, "7001"),
    ({"Serial": "00679B", "Code": "7001"}, "7001"),
    ({"Serial": "7001", "Code": "00679B"}, "00679B"),
    ({"Serial": "1", "證券代號": "7001"}, "7001"),
    ({"Serial": "1", "代號": "7001"}, "7001"),
    ({"Serial": "7001", "Code": "0050"}, "0050"),
    ({"Serial": "7001", "Code": "50"}, None),
    ({"Serial": "7001", "Code": "679B"}, None),
    ({"Serial": "7001", "SecuritiesCompanyCode": "", "Code": "00679B"}, "00679B"),
    ({"Serial": "00679B", "SecuritiesCompanyCode": "7001", "Code": "00679B"}, "7001"),
    ({"SecuritiesCompanyCode": "9999", "Serial": "7001", "Code": "7001"}, None),
    ({"Code": "9999", "證券代號": "7001", "Serial": "7001"}, None),
    ({"Code": "", "證券代號": "00679B", "代號": "7001"}, "00679B"),
    ({"證券代號": "", "代號": "7001", "Serial": "00679B"}, "7001"),
    ({"SecuritiesCompanyCode": " 7001 ", "Serial": "00679B"}, "7001"),
], ids=[
    "serial-only", "blank-primary", "whitespace-primary", "null-primary", "no-identity",
    "code-shadow", "serial-collision", "alphanumeric", "chinese-code", "short-chinese",
    "leading-zero", "no-zero-padding", "no-alphanumeric-padding", "blank-primary-alias",
    "canonical-precedence", "unknown-primary-does-not-fallback", "unknown-code-no-fallback",
    "first-nonblank-chinese", "last-alias", "trim-primary",
])
def test_history_identity_and_audit_metadata(identity, expected):
    row = {**DATES, **identity, "CompanyName": "fixture name"}
    events = parse(row)
    if expected is None:
        assert events == []
        return
    assert [(event.symbol, event.event_type, event.event_date) for event in events] == [
        (expected, "suspension", date(2026, 9, 2)), (expected, "resumption", date(2026, 9, 3)),
    ]
    for event in events:
        assert event.details == {
            "suspended_date": "2026-09-02", "resumed_date": "2026-09-03",
            "interval_end": "2026-09-03", "source_row": row, "data_as_of": DAY.isoformat(),
        }
        assert event.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT
        assert event.payload_sha256 == "fixture-sha"
        assert event.exchange == "TPEx" and event.source == "tpex_suspension_history"
    assert parse(row, allowed=set()) == []


class HistoryFetcher(FixtureFetcher):
    def __init__(self, history):
        super().__init__()
        self.history = history

    def __call__(self, url, **kwargs):
        if url == sources.TPEX_SUSPEND_ENDPOINT:
            self.calls.append(url)
            return []
        if url == sources.TPEX_SUSPEND_HISTORY_ENDPOINT:
            self.calls.append(url)
            return self.history
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            return [dict(row, Industry="01" if row["Code"] == "1101" else "24") for row in payload]
        return payload


def official(fetcher):
    return sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher))


@pytest.mark.parametrize("both_markets", [False, True], ids=["tpex", "official-both"])
@pytest.mark.parametrize("identity,expected", [
    ({"Serial": "7001"}, set()),
    ({"Serial": "1", "Code": "7001"}, {"7001"}),
    ({"Serial": "7001", "Code": "00679B"}, {"00679B"}),
    ({"Serial": "7001", "SecuritiesCompanyCode": "9999", "Code": "7001"}, set()),
])
def test_adapters_keep_history_raw_and_select_only_security_codes(identity, expected, both_markets):
    row = {**DATES, **identity}
    fetcher = HistoryFetcher([row])
    adapter = official(fetcher) if both_markets else sources.TpexAdapter(fetcher)
    batch = adapter.fetch(DAY, DAY)
    events = [e for e in batch.events if e.source == "tpex_suspension_history"]
    assert {e.symbol for e in events} == expected
    assert len(events) == 2 * len(expected)
    raw = next(p for p in batch.payloads if p.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT)
    assert json.loads(raw.payload_path.read_text(encoding="utf-8")) == [row]
    assert hashlib.sha256(raw.payload_path.read_bytes()).hexdigest() == raw.sha256
    assert all(e.details["source_row"] == row and e.payload_sha256 == raw.sha256 for e in events)
    assert fetcher.calls.count(sources.TPEX_SUSPEND_HISTORY_ENDPOINT) == 1
    assert all(not b.is_suspended for b in batch.bars)
    assert not batch.no_data_dates  # Identity rejection is not open-session evidence.
    if both_markets:
        assert {b.exchange for b in batch.bars} == {"TWSE", "TPEx"}


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'identity.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield factory
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def evaluate(db, instrument, key):
    signal = Signal(
        signal_key=key, instrument_id=instrument.id, signal_date=date(2026, 9, 1),
        status="conditional", entry_type="breakout", breakout_price=1,
        invalid_price=0.1, target_1=1000, data_quality="complete",
    )
    db.add(signal)
    db.flush()
    gap = pipeline._suspension_gap_between(db, instrument.id, signal.signal_date, DAY)
    assert pipeline._evaluate_signal_tracking(db, signal) == (1, 2)
    db.flush()
    evaluation = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id))
    observed = (gap, evaluation.status, evaluation.breakout_price_trigger, evaluation.comparable)
    db.commit()
    return observed


@pytest.mark.parametrize("identity,expected", [
    ({"Serial": "7001"}, set()),
    ({"Serial": "1", "Code": "7001"}, {"7001"}),
    ({"Serial": "7001", "Code": "00679B"}, {"00679B"}),
])
def test_collect_commits_history_linkage_and_real_tracking(database, identity, expected):
    row = {**DATES, **identity}
    fetcher = HistoryFetcher([row])
    result = pipeline.collect(DAY, adapter=official(fetcher))
    assert result["status"] == "success", result
    with database() as db:
        events = db.scalars(select(Event).where(Event.source == "tpex_suspension_history")).all()
        assert {db.get(Instrument, e.instrument_id).symbol for e in events} == expected
        assert len(events) == 2 * len(expected)
        raw = db.scalar(select(RawPayload).where(
            RawPayload.ingestion_run_id == result["run_id"],
            RawPayload.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT,
        ))
        assert raw and json.loads(Path(raw.payload_path).read_text(encoding="utf-8")) == [row]
        assert hashlib.sha256(Path(raw.payload_path).read_bytes()).hexdigest() == raw.sha256
        for event in events:
            assert event.raw_payload_id == raw.id and event.details_json["source_row"] == row
            assert event.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT
            assert event.data_as_of == event.event_date.isoformat()
        for symbol in ("7001", "00679B"):
            instrument = db.scalar(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol == symbol))
            bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument.id))
            assert bar.is_suspended is False and bar.volume > 0
            assert evaluate(db, instrument, "fresh-" + symbol) == (
                (True, "suspended", False, False) if symbol in expected
                else (False, "active", True, True)
            )


@pytest.mark.parametrize("replacement", [
    [], [{**DATES, "Serial": "7001"}], [{**DATES, "Serial": "7001", "Code": "00679B"}],
], ids=["empty-history", "rejected-serial-only", "corrected-other-security"])
def test_reuse_and_force_refetch_do_not_delete_legacy_wrong_events(database, replacement):
    legacy_row = {**DATES, "Serial": "7001"}
    fetcher = HistoryFetcher([legacy_row])
    adapter = official(fetcher)
    first = pipeline.collect(DAY, adapter=adapter)
    assert first["status"] == "success", first
    with database() as db:
        instrument = db.scalar(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol == "7001"))
        raw = db.scalar(select(RawPayload).where(
            RawPayload.ingestion_run_id == first["run_id"],
            RawPayload.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT,
        ))
        assert db.scalar(select(Event).where(Event.source == "tpex_suspension_history")) is None
        # Simulate a persisted pre-fix record, explicitly retaining its invalid identity row.
        template = parse({**DATES, "SecuritiesCompanyCode": "7001"})[0]
        legacy = replace(template, details={**template.details, "source_row": legacy_row})
        pipeline._upsert_event(db, legacy, {("TPEx", "7001"): instrument}, raw.id)
        db.commit()
        wrong = db.scalar(select(Event).where(Event.source == "tpex_suspension_history"))
        wrong_id, raw_id = wrong.id, raw.id
        assert evaluate(db, instrument, "legacy-before") == (True, "suspended", False, False)

    fetcher.history = replacement
    call_count = len(fetcher.calls)
    reused = pipeline.collect(DAY, adapter=adapter, force=False)
    assert reused["idempotent_reuse"] is True and len(fetcher.calls) == call_count
    refetched = pipeline.collect(DAY, adapter=adapter, force=True)
    assert refetched["status"] == "success" and not refetched.get("idempotent_reuse"), refetched
    assert len(fetcher.calls) > call_count
    with database() as db:
        wrong = db.get(Event, wrong_id)
        assert wrong and wrong.raw_payload_id == raw_id and wrong.details_json["source_row"] == legacy_row
        instrument = db.get(Instrument, wrong.instrument_id)
        assert instrument.symbol == "7001"
        assert evaluate(db, instrument, "legacy-after") == (True, "suspended", False, False)
        old_signal = db.scalar(select(Signal).where(Signal.signal_key == "legacy-before"))
        assert db.scalar(select(SignalEvaluation.status).where(
            SignalEvaluation.signal_id == old_signal.id,
        )) == "suspended"
        events = db.scalars(select(Event).where(Event.source == "tpex_suspension_history")).all()
        assert len(events) == (3 if replacement and "Code" in replacement[0] else 1)
        if len(events) == 3:
            correct = [e for e in events if e.id != wrong_id]
            assert {db.get(Instrument, e.instrument_id).symbol for e in correct} == {"00679B"}
            assert all(e.details_json["source_row"] == replacement[0] for e in correct)
        history_raws = db.scalars(select(RawPayload).where(
            RawPayload.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT,
        )).all()
        assert any(json.loads(Path(r.payload_path).read_text(encoding="utf-8")) == replacement for r in history_raws)
