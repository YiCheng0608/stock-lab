"""Unique TPEx split rows close date intervals without inventing event cycles."""

import copy
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
# Exact two rows from https://www.tpex.org.tw/openapi/v1/tpex_spendi_history
# observed 2026-09-13; whole response SHA256:
# 4e3747a4a27c1e45542ce476ff7ccd0384e5c420e9f2d5bbfd9257b9cc48e6a2.
# Only history rows are live-derived; all other feeds/prices below are fixtures.
START = {
    "Date": "115", "Serial": "1", "SecuritiesCompanyCode": "1788", "CompanyName": "杏昌",
    "DateOfSuspendedTrading": "1150618", "TimeOfSuspendedTrading": "080000",
    "DateOfResumedTrading": "", "TimeOfResumedTrading": "",
}
RESUME = {
    "Date": "115", "Serial": "2", "SecuritiesCompanyCode": "1788", "CompanyName": "杏昌",
    "DateOfSuspendedTrading": "", "TimeOfSuspendedTrading": "",
    "DateOfResumedTrading": "1150622", "TimeOfResumedTrading": "080000",
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in suspension interval tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def parse(rows, allowed=None):
    return sources.parse_tpex_suspension_history_rows(
        rows, allowed_symbols={"1788", "1799"} if allowed is None else allowed,
        endpoint=sources.TPEX_SUSPEND_HISTORY_ENDPOINT,
        data_as_of=DAY.isoformat(), payload_sha256="fixture-sha",
    )


@pytest.mark.parametrize("rows", [
    [START, RESUME], [RESUME, START],
    [dict(START, Serial="1788"), dict(RESUME, Serial="1788")],
], ids=["saved-live-shape", "reverse-order", "serial-irrelevant"])
def test_unique_pair_preserves_audit_events_order_and_raw(rows):
    before = copy.deepcopy(rows)
    unlinked = [event for row in rows for event in parse([row])]
    events = parse(rows)
    assert rows == before
    assert len(events) == 2
    for old, new in zip(unlinked, events, strict=True):
        if old.event_type == "resumption":
            assert new == old
        else:
            assert new == replace(old, details={
                **old.details, "resumed_date": "2026-06-22", "interval_end": "2026-06-22",
                "resumption_source_row": next(row for row in rows if row["DateOfResumedTrading"]),
            })
    # Pairing has no state across payloads/calls.
    assert parse([START])[0].details["resumed_date"] is None
    assert parse([RESUME])[0].details["suspended_date"] is None
    assert parse([]) == []


def test_interleaved_symbols_pair_independently_without_reordering():
    other_start = dict(START, SecuritiesCompanyCode="1799", DateOfSuspendedTrading="1150312")
    other_resume = dict(RESUME, SecuritiesCompanyCode="1799", DateOfResumedTrading="1150313")
    rows = [RESUME, other_start, START, other_resume]
    events = parse(rows)
    assert [(e.symbol, e.event_type) for e in events] == [
        ("1788", "resumption"), ("1799", "suspension"),
        ("1788", "suspension"), ("1799", "resumption"),
    ]
    assert events[1].details["resumption_source_row"] == other_resume
    assert events[2].details["resumption_source_row"] == RESUME


@pytest.mark.parametrize("identity", [
    {"SecuritiesCompanyCode": "", "Code": "1788"},
    {"SecuritiesCompanyCode": None, "證券代號": "1788"},
    {"SecuritiesCompanyCode": " ", "代號": "1788"},
    {"SecuritiesCompanyCode": " 1788 ", "Code": "1799"},
    {"SecuritiesCompanyCode": 1788},
])
def test_existing_identity_alias_priority_and_coercion(identity):
    events = parse([dict(START, **identity), dict(RESUME, **identity)])
    assert len(events) == 2 and events[0].symbol == "1788"
    assert events[0].details["resumed_date"] == "2026-06-22"


def test_unknown_canonical_does_not_retry_alias_or_join_other_identity():
    unknown_resume = dict(RESUME, SecuritiesCompanyCode="9999", Code="1788")
    events = parse([START, unknown_resume])
    assert len(events) == 1 and events[0].details["resumed_date"] is None
    assert parse([START, RESUME], allowed=set()) == []
    # A row selected as another identity cannot count toward this identity's pair.
    events = parse([START, RESUME, unknown_resume])
    assert len(events) == 2 and events[0].details["resumed_date"] == "2026-06-22"


@pytest.mark.parametrize("rows", [
    [START], [RESUME],
    [START, START, RESUME], [START, RESUME, RESUME],
    [START, RESUME, {"SecuritiesCompanyCode": "1788"}],
    [START, RESUME, dict(START, DateOfSuspendedTrading="bad")],
    [START, RESUME, dict(START, DateOfResumedTrading="1150622")],
    [START, dict(RESUME, DateOfResumedTrading="1150618")],
    [START, dict(RESUME, DateOfResumedTrading="1150617")],
    [START, dict(RESUME, DateOfResumedTrading="bad")],
    [START, dict(RESUME, DateOfResumedTrading="2026/02/30")],
    [dict(START, DateOfResumedTrading="bad"), RESUME],
    [START, dict(RESUME, DateOfSuspendedTrading="bad")],
    [dict(START, DateOfResumedTrading="1150622"), RESUME],
    [dict(START, DateOfResumedTrading="1150622")],
    [START, dict(RESUME, SecuritiesCompanyCode="1799")],
    [START, dict(RESUME, DateOfResumedTrading="bad", ResumedTradingDate="1150622")],
    [dict(START, DateOfSuspendedTrading="bad", SuspendedTradingDate="1150618"), RESUME],
], ids=[
    "start-only", "resume-only", "duplicate-start", "duplicate-resume", "empty-extra",
    "invalid-extra", "full-interval-extra", "same-day", "reversed-date", "invalid-resume",
    "impossible-resume", "invalid-opposite-resume", "invalid-opposite-start",
    "combined-plus-resume", "combined-only", "different-identity",
    "invalid-canonical-resume-no-retry", "invalid-canonical-start-no-retry",
])
def test_ambiguous_or_ineligible_payload_retains_individual_row_behavior(rows):
    assert parse(rows) == [event for row in rows for event in parse([row])]


@pytest.mark.parametrize("start_value,resume_value", [
    ("115/06/18", "115/06/22"), ("2026-06-18", "2026-06-22"),
    ("20260618", "20260622"), (date(2026, 6, 18), date(2026, 6, 22)),
])
def test_existing_date_formats_are_unchanged(start_value, resume_value):
    events = parse([dict(START, DateOfSuspendedTrading=start_value),
                    dict(RESUME, DateOfResumedTrading=resume_value)])
    assert events[0].details["interval_end"] == "2026-06-22"


def test_date_aliases_and_blank_opposite_fields_keep_existing_selection():
    start = dict(START, DateOfSuspendedTrading=" ", SuspendedTradingDate="1150618",
                 DateOfResumedTrading=None, ResumedTradingDate=" ")
    resume = dict(RESUME, DateOfResumedTrading=" ", 復牌日期="1150622",
                  DateOfSuspendedTrading=None, SuspendedTradingDate=" ")
    events = parse([start, resume])
    assert events[0].details["interval_end"] == "2026-06-22"
    assert events[0].details["source_row"] == start
    assert events[0].details["resumption_source_row"] == resume


@pytest.mark.parametrize("time_value", [None, "", "080000", "130000", "not-a-time"])
def test_time_fields_remain_raw_only_for_strictly_ordered_dates(time_value):
    start = dict(START, TimeOfSuspendedTrading=time_value)
    resume = dict(RESUME, TimeOfResumedTrading=time_value)
    events = parse([start, resume])
    assert events[0].details["interval_end"] == "2026-06-22"
    assert events[0].details["source_row"]["TimeOfSuspendedTrading"] == time_value
    assert events[0].details["resumption_source_row"]["TimeOfResumedTrading"] == time_value


def test_datetime_text_is_not_promoted_to_new_date_format():
    rows = [dict(START, DateOfSuspendedTrading="2026/06/18 08:00:00"), RESUME]
    assert parse(rows) == parse([rows[0]]) + parse([RESUME])


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
            payload = [dict(row, Industry="01" if row["Code"] == "1101" else "24") for row in payload]

        def remap(value):
            if isinstance(value, dict):
                return {key: remap(item) for key, item in value.items()}
            if isinstance(value, list):
                return [remap(item) for item in value]
            return "1788" if value == "7001" else value
        return remap(payload)


def official(fetcher):
    return sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher))


@pytest.mark.parametrize("both_markets", [False, True], ids=["tpex", "both-markets"])
@pytest.mark.parametrize("future", [False, True], ids=["past-resume", "future-resume"])
def test_actual_adapters_keep_raw_and_future_details_before_event_cutoff(both_markets, future):
    resume = dict(RESUME, DateOfResumedTrading="1150907") if future else RESUME
    rows = [START, resume]
    fetcher = HistoryFetcher(rows)
    adapter = official(fetcher) if both_markets else sources.TpexAdapter(fetcher)
    batch = adapter.fetch(DAY, DAY)
    events = [e for e in batch.events if e.source == "tpex_suspension_history"]
    assert [e.event_type for e in events] == (["suspension"] if future else ["suspension", "resumption"])
    # Existing adapter cutoff filters Event dates, not future end dates in details.
    # This does not assert historical availability/PIT or full-day market openness.
    assert events[0].details["resumed_date"] == ("2026-09-07" if future else "2026-06-22")
    assert events[0].details["resumption_source_row"] == resume
    raw = next(p for p in batch.payloads if p.endpoint == sources.TPEX_SUSPEND_HISTORY_ENDPOINT)
    assert json.loads(raw.payload_path.read_text(encoding="utf-8")) == rows
    assert hashlib.sha256(raw.payload_path.read_bytes()).hexdigest() == raw.sha256
    assert all(e.payload_sha256 == raw.sha256 for e in events)
    assert not batch.no_data_dates and batch.event_coverage["status"] == "unsupported"
    assert all(not bar.is_suspended for bar in batch.bars)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'intervals.db'}")
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
    signal = Signal(signal_key=key, instrument_id=instrument.id, signal_date=date(2026, 9, 3),
                    status="conditional", entry_type="breakout", breakout_price=1,
                    invalid_price=0.1, target_1=1000, data_quality="complete")
    db.add(signal)
    db.commit()
    gap = pipeline._suspension_gap_between(db, instrument.id, signal.signal_date, DAY)
    assert pipeline._evaluate_signal_tracking(db, signal) == (1, 2)
    db.commit()
    ev = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id))
    return ev.id, (gap, ev.status, ev.breakout_price_trigger, ev.comparable)


def test_collect_migration_sqlite_raw_fk_and_same_symbol_exchange_isolation(database):
    result = pipeline.collect(DAY, adapter=official(HistoryFetcher([START, RESUME])))
    assert result["status"] == "success", result
    with database() as db:
        inst = db.scalar(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol == "1788"))
        events = db.scalars(select(Event).where(Event.instrument_id == inst.id, Event.source == "tpex_suspension_history")).all()
        assert len(events) == 2
        raw = db.get(RawPayload, events[0].raw_payload_id)
        assert raw and all(event.raw_payload_id == raw.id for event in events)
        assert json.loads(Path(raw.payload_path).read_text(encoding="utf-8")) == [START, RESUME]
        assert hashlib.sha256(Path(raw.payload_path).read_bytes()).hexdigest() == raw.sha256
        assert evaluate(db, inst, "finite")[1] == (False, "active", True, True)
        # Independent TWSE suspension with identical symbol must not receive the TPEx end.
        other = Instrument(market="TW", exchange="TWSE", symbol="1788", name="fixture", instrument_type="stock", status="active")
        db.add(other)
        db.flush()
        db.add(MarketBar(instrument_id=other.id, trading_date=DAY, open=50, high=52, low=49,
                         close=51, adj_close=51, volume=2000, source="fixture"))
        old = replace(parse([START])[0], exchange="TWSE")
        pipeline._upsert_event(db, old, {("TWSE", "1788"): other}, None)
        db.commit()
        assert evaluate(db, other, "other-exchange")[1] == (True, "suspended", False, False)
        assert evaluate(db, inst, "finite-again")[1] == (False, "active", True, True)


def test_collect_reuse_and_force_update_same_event_keep_old_evaluation(database, monkeypatch):
    current = sources.parse_tpex_suspension_history_rows

    def legacy_split_rows(payload, **kwargs):
        # Prior normalization, retaining both raw audit events but no cross-row link.
        return [event for row in sources._rows(payload) for event in current([row], **kwargs)]

    fetcher = HistoryFetcher([START, RESUME])
    adapter = official(fetcher)
    with monkeypatch.context() as context:
        context.setattr(sources, "parse_tpex_suspension_history_rows", legacy_split_rows)
        first = pipeline.collect(DAY, adapter=adapter)
    assert first["status"] == "success", first
    with database() as db:
        inst = db.scalar(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol == "1788"))
        old = db.scalar(select(Event).where(Event.instrument_id == inst.id, Event.event_type == "suspension"))
        event_id, raw_id = old.id, old.raw_payload_id
        assert old.details_json["resumed_date"] is None
        old_evaluation_id, observed = evaluate(db, inst, "legacy")
        assert observed == (True, "suspended", False, False)

    count = len(fetcher.calls)
    reused = pipeline.collect(DAY, adapter=adapter, force=False)
    assert reused["idempotent_reuse"] and len(fetcher.calls) == count
    with database() as db:
        assert db.get(Event, event_id).details_json["resumed_date"] is None
        inst = db.get(Instrument, inst.id)
        assert evaluate(db, inst, "reused")[1] == (True, "suspended", False, False)
    refetched = pipeline.collect(DAY, adapter=adapter, force=True)
    assert refetched["status"] == "success" and not refetched.get("idempotent_reuse"), refetched
    assert len(fetcher.calls) > count
    with database() as db:
        corrected = db.get(Event, event_id)
        assert corrected.details_json["resumed_date"] == corrected.details_json["interval_end"] == "2026-06-22"
        assert corrected.details_json["source_row"] == START
        assert corrected.details_json["resumption_source_row"] == RESUME
        assert corrected.raw_payload_id == raw_id  # Same captured content is deduplicated.
        assert db.get(SignalEvaluation, old_evaluation_id).status == "suspended"
        inst = db.get(Instrument, corrected.instrument_id)
        assert evaluate(db, inst, "corrected")[1] == (False, "active", True, True)
        events = db.scalars(select(Event).where(Event.instrument_id == inst.id, Event.source == "tpex_suspension_history")).all()
        assert len(events) == 2
        resumption = next(e for e in events if e.event_type == "resumption")
        assert resumption.details_json == parse([RESUME])[0].details
