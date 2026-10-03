"""M2-P1 reconstructable memory checks; no live or catalogue market evidence.

Run under the checked-in P3b zero-disk audit guard before importing pytest,
with --noconftest, plugin autoload disabled and cache/logging plugins disabled.
The API fixture uses the existing repo directories as no-op config paths and
only :memory: SQLite. No application lifespan or persistent captures are used.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from threading import Event, Thread
from unittest.mock import patch

import pytest

from app import official_events as events
from worker import twse_action_capture as consumer
from test_official_events import DAY, ENABLED, ROWS, encoded, memory_api, memory_app, source


@pytest.fixture(autouse=True)
def fixed_observation_day(monkeypatch):
    monkeypatch.setattr(events, "_today_taipei", lambda: DAY)


def acquire(monkeypatch, rows=None, **kwargs):
    body, calls = source(monkeypatch, rows, **kwargs)
    store = events.OfficialEventMemory()
    result = events.capture_official_event_focus(DAY, environment=ENABLED, store=store)
    return store, body, calls, result


def test_all_observed_symbols_grouped_multiple_events_and_dual_hash(monkeypatch):
    store, body, calls, value = acquire(monkeypatch)
    assert value["version"] == "official-event-focus/p1-v1" and value["status"] == "available"
    assert value["total"] == value["displayed"] == 3 and not value["truncated"]
    assert [item["symbol"] for item in value["items"]] == ["0056", "1449", "1463"]
    assert [row["row_ordinal"] for row in value["items"][0]["events"]] == [1, 4]
    assert [row["event_date"] for row in value["items"][0]["events"]] == ["2026-10-22", "2026-11-22"]
    assert value["provenance"]["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert value["provenance"]["receipt_sha256"] == hashlib.sha256(store.snapshot[1]).hexdigest()
    assert value["candidate_count"] == value["selected_count"] == 4
    assert "UNVALIDATED" not in json.dumps(value) and "source_row" not in json.dumps(value)
    assert all(item["research_conditions"] == "unknown" for item in value["items"])
    assert len(calls) == 1


def test_empty_feed_receipt_available_but_selected_still_missing(monkeypatch):
    store, body, calls, value = acquire(monkeypatch, [])
    assert body == b"[]" and value["status"] == "available" and value["items"] == []
    assert value["candidate_count"] == value["total"] == value["displayed"] == 0
    assert value["provenance"] and value["attribution"] and value["summary_condition_receipts"]
    assert value["coverage"] == "observed_feed_only" and len(calls) == 1
    selected = events.build_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    assert selected["status"] == "unavailable" and selected["reasons"] == ["nonempty_row_list_required"]


def test_fixed_reading_order_cap_counts_and_whole_body_validation(monkeypatch):
    rows = [{"Code": f"{code:04}", "Name": "fixture", "Date": "1151022", "Exdividend": "息"}
            for code in reversed(range(1000, 1102))]
    store, _, calls, value = acquire(monkeypatch, rows)
    assert value["total"] == 102 and value["displayed"] == value["limit"] == 100 and value["truncated"]
    assert [item["symbol"] for item in value["items"]] == [str(code) for code in range(1000, 1100)]
    assert value["items"][0]["events"][0]["row_ordinal"] == 102
    assert value["candidate_count"] == value["selected_count"] == 102 and len(calls) == 1
    rows[0]["Exdividend"] = "unknown"
    store, _, calls, value = acquire(monkeypatch, rows)
    assert value["reasons"] == ["selected_event_class_unknown"] and store.snapshot is None


@pytest.mark.parametrize("rows,reason", [
    ([ROWS[0], ROWS[0]], "selected_event_duplicate"),
    ([{**ROWS[0], "Name": " "}], "selected_name_missing"),
    ([{**ROWS[0], "Code": "bad!"}], "invalid_security_code"),
    ([{**ROWS[0], "Date": "1150230"}], "invalid_effective_date"),
    ([ROWS[0], {**ROWS[1], "Exdividend": "unknown"}], "selected_event_class_unknown"),
    ([None], "row_object_required"), ({"data": ROWS}, "row_list_required")])
def test_rejected_feed_not_published(monkeypatch, rows, reason):
    store, _, calls, value = acquire(monkeypatch, rows)
    assert value["status"] == "unavailable" and value["items"] == []
    assert value["reasons"] == [reason] and value["capture_action"] == "failed"
    assert store.snapshot is None and value["provenance"] is None and len(calls) == 1


@pytest.mark.parametrize("value", [None, "", "0", "true", " 1", "1 "])
def test_disabled_configuration_zero_fetch(monkeypatch, value):
    _, calls = source(monkeypatch)
    environment = {} if value is None else {events.CAPTURE_ENV: value}
    for operation in (events.build_official_event_focus, events.capture_official_event_focus):
        result = operation(DAY, environment=environment, store=events.OfficialEventMemory())
        assert result["status"] == "unavailable" and not result["can_capture"]
    assert not calls


@pytest.mark.parametrize("cutoff", [None, "2026-10-03", date(2026, 10, 2)])
def test_missing_invalid_and_past_cutoff_zero_fetch(monkeypatch, cutoff):
    _, calls = source(monkeypatch)
    store = events.OfficialEventMemory()
    value = events.capture_official_event_focus(cutoff, environment=ENABLED, store=store)
    reason = "event_cutoff_before_current_observation" if type(cutoff) is date else "event_shared_cutoff_missing"
    assert value["reasons"] == [reason] and not value["can_capture"]
    assert store.snapshot is None and calls == []


@pytest.mark.parametrize("captured_at,observed", [("2026-10-02T15:59:59+00:00", "2026-10-02"),
                                                ("2026-10-02T16:00:00+00:00", "2026-10-03")])
def test_taipei_observation_cutoff_inclusive_cache_and_future_effective(monkeypatch, captured_at, observed):
    store, _, calls, _ = acquire(monkeypatch, captured_at=captured_at)
    for cutoff in (date(2026, 10, 2), DAY, date(2026, 10, 4)):
        value = events.capture_official_event_focus(cutoff, environment=ENABLED, store=store)
        assert "rows" not in value
        assert value["capture_action"] == "cached" and value["observed_date"] == observed
        available = cutoff.isoformat() >= observed
        assert value["status"] == ("available" if available else "unavailable")
        if available:
            assert value["items"][0]["events"][1]["event_date"] == "2026-11-22"
        else:
            assert value["items"] == [] and value["reasons"] == ["event_observation_after_cutoff"]
    assert len(calls) == 1


def test_shared_selected_cache_read_only_feed_validation_and_missing_selection(monkeypatch):
    body, calls = source(monkeypatch)
    store = events.OfficialEventMemory()
    selected = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    original = store.snapshot
    focus = events.capture_official_event_focus(DAY, environment=ENABLED, store=store)
    assert focus["capture_action"] == "cached" and focus["provenance"] == selected["provenance"]
    focus["items"][0]["events"][0]["company_name"] = "client change"
    assert events.build_official_event_focus(DAY, environment=ENABLED, store=store)["items"][0]["company_name"] == "元大高股息"
    missing = events.build_official_events("TWSE", "2330", DAY, environment=ENABLED, store=store)
    assert missing["reasons"] == ["selected_symbol_missing:2330"]
    assert store.snapshot is original and store.snapshot[0] == body and len(calls) == 1


def test_selected_unselected_class_contract_preserved_but_focus_rejects(monkeypatch):
    rows = [ROWS[0], {**ROWS[1], "Exdividend": "unknown"}]
    _, calls = source(monkeypatch, rows)
    store = events.OfficialEventMemory()
    assert events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)["status"] == "available"
    value = events.build_official_event_focus(DAY, environment=ENABLED, store=store)
    assert value["reasons"] == ["selected_event_class_unknown"] and not value["can_capture"]
    assert len(calls) == 1


@pytest.mark.parametrize("part", ["body", "receipt", "pins"])
def test_revalidation_and_no_refresh(monkeypatch, part):
    store, _, calls, _ = acquire(monkeypatch)
    body, receipt = store.snapshot
    if part == "body":
        store.snapshot = (body + b" ", receipt)
    elif part == "receipt":
        value = json.loads(receipt); value["source_version"] = "bad"
        store.snapshot = (body, encoded(value))
    else:
        monkeypatch.setitem(events.PINS, "expected_digest", "sha256:" + "0" * 64)
    for operation in (events.build_official_event_focus, events.capture_official_event_focus):
        value = operation(DAY, environment=ENABLED, store=store)
        assert value["status"] == "unavailable" and value["items"] == [] and value["provenance"] is None
    assert len(calls) == 1


def test_http_and_admission_failure_no_cache_and_sanitized(monkeypatch):
    store, _, calls, value = acquire(monkeypatch, status=503)
    assert value["reasons"] == ["http_status:503"] and len(calls) == 1 and store.snapshot is None
    def denied(**_):
        raise consumer.ActionCaptureError("purpose_not_admitted:summarize")
    monkeypatch.setattr(consumer, "_admission", denied)
    value = events.capture_official_event_focus(DAY, environment=ENABLED, store=store)
    assert value["reasons"] == ["purpose_not_admitted:summarize"] and len(calls) == 1


def test_lock_shared_with_selected_and_get_does_not_wait_or_fetch(monkeypatch):
    _, calls = source(monkeypatch)
    actual, entered, release = events.capture_memory, Event(), Event()
    def waiting(**kwargs):
        entered.set(); assert release.wait(10)
        return actual(**kwargs)
    monkeypatch.setattr(events, "capture_memory", waiting)
    store, output = events.OfficialEventMemory(), []
    thread = Thread(target=lambda: output.append(events.capture_official_event_focus(DAY, environment=ENABLED, store=store)))
    thread.start()
    try:
        assert entered.wait(10)
        assert events.capture_official_event_focus(DAY, environment=ENABLED, store=store)["reasons"] == ["event_capture_in_progress"]
        assert events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)["reasons"] == ["event_capture_in_progress"]
        assert events.build_official_event_focus(DAY, environment=ENABLED, store=store)["reasons"] == ["event_memory_capture_missing"]
        assert calls == []
    finally:
        release.set(); thread.join(10)
    assert not thread.is_alive() and output[0]["status"] == "available" and len(calls) == 1


def test_actual_router_required_cutoff_get_import_zero_network(monkeypatch):
    _, calls = source(monkeypatch)
    with memory_api() as client:
        assert calls == []
        for method in (client.get, client.post):
            path = "/api/focus/official-events" + ("/capture" if method == client.post else "")
            assert method(path).status_code == 422
            assert method(path + "?as_of=bad").status_code == 422
        result = client.get("/api/focus/official-events?as_of=2026-10-03").json()
        assert result["reasons"] == ["event_memory_capture_missing"] and calls == []
        result = client.post("/api/focus/official-events/capture?as_of=2026-10-02").json()
        assert result["reasons"] == ["event_cutoff_before_current_observation"] and calls == []


def test_actual_api_catalogue_read_only_unknown_and_same_cutoff_m1(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import event as sql_event
    from sqlalchemy.orm import Session
    extra = {"Code": "9999", "Name": "原件未知公司", "Date": "1151023", "Exdividend": "息"}
    _, calls = source(monkeypatch, [*ROWS, extra])
    store = events.OfficialEventMemory()
    with memory_app(store=store) as app:
        from app.api import get_db
        from app.db import Base
        provider = app.dependency_overrides[get_db]()
        db = next(provider)
        engine = db.get_bind()
        def snapshot():
            with engine.connect() as connection:
                return {table.name: [dict(row) for row in connection.execute(table.select()).mappings()]
                        for table in Base.metadata.sorted_tables}
        before = snapshot()
        def only_read(_conn, _cursor, statement, *_):
            assert statement.lstrip().upper().startswith("SELECT"), "unexpected SQL mutation: " + statement
        sql_event.listen(engine, "before_cursor_execute", only_read)
        def forbidden(*_, **__):
            raise AssertionError("unexpected DB commit/flush")
        try:
            with TestClient(app) as client:
                with patch.object(Session, "commit", forbidden), patch.object(Session, "flush", forbidden):
                    acquired = client.post("/api/focus/official-events/capture?as_of=2026-10-03").json()
                    cached = client.get("/api/focus/official-events?as_of=2026-10-03").json()
                    assert client.post("/api/focus/official-events/capture?as_of=2026-10-03").json()["capture_action"] == "cached"
                    assert client.get("/api/focus/official-events?as_of=2026-10-02").json()["items"] == []
                    assert snapshot() == before
                assert acquired["status"] == cached["status"] == "available"
                known, unknown = cached["items"][0], cached["items"][-1]
                assert known["detail_url"] == "/stocks/TWSE/0056?as_of=2026-10-03" and known["stock_page_available"]
                assert unknown["symbol"] == "9999" and unknown["company_name"] == "原件未知公司"
                assert not unknown["stock_page_available"] and unknown["detail_url"] is None
                # The catalogue-only focus route did not manufacture a new row.
                sql_event.remove(engine, "before_cursor_execute", only_read)
                detail = client.get("/api" + known["detail_url"]).json()
                selected = detail["overview"]["events"]
                assert detail["overview"]["as_of"] == cached["as_of"] == "2026-10-03"
                assert selected["status"] == "available" and selected["provenance"] == cached["provenance"]
                assert selected["rows"] == known["events"]
                assert len(calls) == 1 and snapshot() == before
        finally:
            if sql_event.contains(engine, "before_cursor_execute", only_read):
                sql_event.remove(engine, "before_cursor_execute", only_read)
            provider.close()


def test_catalogue_query_cannot_autoflush_pending_row(monkeypatch):
    with memory_app() as app:
        from app import api
        from app.models import Instrument
        from sqlalchemy.orm import Session
        provider = app.dependency_overrides[api.get_db]()
        db = next(provider)
        try:
            db.add(Instrument(exchange="TWSE", symbol="9999", name="pending fixture"))
            with patch.object(Session, "flush", side_effect=AssertionError("autoflush forbidden")):
                result = api._focus_catalogue(db, {"items": [{"symbol": "0056"}, {"symbol": "9999"}], "as_of": "2026-10-03"})
            assert result["items"][0]["stock_page_available"]
            assert "stock_page_available" not in result["items"][1]
        finally:
            provider.close()
