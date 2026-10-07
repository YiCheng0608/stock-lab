"""Memory-only P3b checks and reusable minimal-catalog API review helper.

Run -B, --noconftest, -s, -p no:cacheprovider -p no:logging with plugin
autoload disabled. Install the audit guard BEFORE importing pytest or the API.
The helper is a test catalog, not real market DB evidence or a production server.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import Event, Thread
from unittest.mock import patch

import httpx
import pytest

from app import official_events as events
from worker import source_runtime as runtime
from worker import twse_action_capture as consumer

REPO = Path(__file__).resolve().parents[2]
DAY = date(2026, 10, 3)
ENABLED = {events.CAPTURE_ENV: "1"}
ROWS = [{"Code": "0056", "Name": "元大高股息", "Date": "1151022", "Exdividend": "息", "CashDividend": "UNVALIDATED"},
        {"Code": "1449", "Name": "佳和", "Date": "1151012", "Exdividend": "權"},
        {"Code": "1463", "Name": "強盛新", "Date": "1151015", "Exdividend": "息"},
        {"Code": "0056", "Name": "元大高股息", "Date": "1151122", "Exdividend": "權息"}]


def install_zero_disk_guard() -> None:
    """Install before any API import; reject writes, real network and disk DB."""
    def audit(event, args):
        if event == "open":
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                raise AssertionError("unexpected_disk_write:" + str(args[0]))
        if event == "socket.connect":
            caller = sys._getframe(1)
            if (caller.f_code.co_name == "_fallback_socketpair"
                    and Path(caller.f_code.co_filename) == Path(__import__("socket").__file__)
                    and isinstance(args[1], tuple) and args[1][0] in {"127.0.0.1", "::1"}):
                return
            raise AssertionError("unexpected_external_connection")
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink",
                     "tempfile.mkstemp", "tempfile.mkdtemp", "subprocess.Popen"}:
            raise AssertionError("unexpected_filesystem_mutation_or_subprocess:" + event)
        if event == "sqlite3.connect" and args[0] != ":memory:":
            raise AssertionError("unexpected_disk_database")
    sys.addaudithook(audit)


@contextmanager
def memory_app(*, enabled: str = "1", store: events.OfficialEventMemory | None = None):
    """Actual router, :memory: SQLite and fixed three-instrument test catalog.

    No app.main lifespan/readiness, capture mock or network configuration. A
    reviewer can serve this yielded app, with separately authorized network
    guards, to exercise the real explicit POST. The bytes cache is process-only.
    """
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    def existing_directory_only(target, *args, **kwargs):
        assert target == REPO and target.is_dir(), "unexpected config mkdir"

    environment = {"STOCK_DATA_DIR": str(REPO), "STOCK_RAW_DIR": str(REPO), "STOCK_DB_PATH": ":memory:",
                   events.CAPTURE_ENV: enabled, "STOCK_TPEX_INSTITUTIONAL_CAPTURE_ZIP": "",
                   "STOCK_TPEX_INSTITUTIONAL_CAPTURE_DATE": ""}
    with patch.dict(os.environ, environment), patch.object(Path, "mkdir", existing_directory_only), \
            patch.object(events, "MEMORY_EVENTS", store if store is not None else events.OfficialEventMemory()):
        from app.api import configure_cors, get_db, router
        from app.db import Base, enable_sqlite_foreign_keys
        from app.models import Instrument
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        enable_sqlite_foreign_keys(engine)
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        with sessions() as db:
            db.add_all([Instrument(exchange="TWSE", symbol=symbol, name=name, instrument_type=kind)
                        for symbol, name, kind in [("0056", "元大高股息", "etf"), ("1449", "佳和", "stock"),
                                                   ("1463", "強盛新", "stock")]])
            db.add(Instrument(exchange="TPEx", symbol="0056", name="同代號市場測試"))
            db.commit()
        def memory_db():
            with sessions() as db:
                yield db
        app = FastAPI()
        configure_cors(app)
        app.include_router(router)
        app.dependency_overrides[get_db] = memory_db
        try:
            yield app
        finally:
            app.dependency_overrides.clear()
            engine.dispose()


@contextmanager
def memory_api(**kwargs):
    from fastapi.testclient import TestClient
    with memory_app(**kwargs) as app:
        with TestClient(app) as client:
            yield client


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def source(monkeypatch, rows=None, *, status=200, captured_at="2026-10-02T16:00:01+00:00"):
    body = encoded(ROWS if rows is None else rows)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body))
    adapter = httpx.MockTransport(handler)
    monkeypatch.setattr(runtime, "_utc", lambda: captured_at)
    real = runtime.capture_memory
    monkeypatch.setattr(events, "capture_memory", lambda **kwargs: real(**kwargs, transport=adapter))
    return body, calls


def acquired(monkeypatch):
    body, calls = source(monkeypatch)
    store = events.OfficialEventMemory()
    result = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    assert result["status"] == "available" and len(calls) == 1
    return store, body, calls, result


@pytest.mark.parametrize("value", [None, "", "0", "true", " 1", "1 ", "2"])
def test_disabled_invalid_configuration_zero_requests(monkeypatch, value):
    store, _, calls, _ = acquired(monkeypatch)
    config = {} if value is None else {events.CAPTURE_ENV: value}
    for operation in (events.build_official_events, events.capture_official_events):
        result = operation("TWSE", "0056", DAY, environment=config, store=store)
        assert result["status"] == "unavailable" and result["rows"] == []
        assert result["provenance"] is None and not result["cache_present"]
        assert not result["can_capture"]
    assert len(calls) == 1


@pytest.mark.parametrize("exchange,symbol", [("TPEx", "0056"), ("TWSE", "../bad"), ("TWSE", "0056 ")])
def test_identity_gate_before_source(monkeypatch, exchange, symbol):
    _, calls = source(monkeypatch)
    value = events.capture_official_events(exchange, symbol, DAY, environment=ENABLED, store=events.OfficialEventMemory())
    assert value["status"] == "unavailable" and calls == []


def test_normal_read_without_original_never_fetches(monkeypatch):
    _, calls = source(monkeypatch)
    for _ in range(3):
        value = events.build_official_events("TWSE", "0056", DAY, environment=ENABLED, store=events.OfficialEventMemory())
        assert value["reasons"] == ["event_memory_capture_missing"]
    assert calls == []


@pytest.mark.parametrize("cutoff,available,reason", [(DAY, True, None), (date(2026, 10, 4), True, None),
                         (date(2026, 10, 2), False, "event_observation_after_cutoff"),
                         (None, False, "event_shared_cutoff_missing")])
def test_taipei_midnight_inclusive_observation_and_future_events(monkeypatch, cutoff, available, reason):
    store, body, calls, _ = acquired(monkeypatch)
    value = events.build_official_events("TWSE", "0056", cutoff, environment=ENABLED, store=store)
    assert value["observed_date"] == "2026-10-03"
    assert value["as_of"] == (cutoff.isoformat() if cutoff else None)
    assert value["status"] == ("available" if available else "unavailable")
    if available:
        assert [row["event_date"] for row in value["rows"]] == ["2026-10-22", "2026-11-22"]
        assert [row["label"] for row in value["rows"]] == ["除息", "除權息"]
        assert [row["source_classification"] for row in value["rows"]] == ["息", "權息"]
        assert [row["row_ordinal"] for row in value["rows"]] == [1, 4]
        assert all(row["published_at"] is None and row["first_available_at"] is None
                   and row["revision_available_at"] is None for row in value["rows"])
        assert "UNVALIDATED" not in json.dumps(value) and all("source_row" not in row for row in value["rows"])
        assert value["provenance"]["body_sha256"] == hashlib.sha256(body).hexdigest()
        assert value["provenance"]["receipt_sha256"] == hashlib.sha256(store.snapshot[1]).hexdigest()
    else:
        assert value["reasons"] == [reason] and value["rows"] == [] and value["provenance"] is None
    assert len(calls) == 1


def test_capture_no_cutoff_publishes_bytes_without_advancing_cutoff(monkeypatch):
    _, calls = source(monkeypatch)
    store = events.OfficialEventMemory()
    value = events.capture_official_events("TWSE", "0056", None, environment=ENABLED, store=store)
    assert value["capture_action"] == "acquired" and value["as_of"] is None
    assert value["reasons"] == ["event_shared_cutoff_missing"] and value["observed_date"] == "2026-10-03"
    assert store.snapshot is not None and len(calls) == 1


def test_one_original_reused_all_symbols_no_refresh_and_returned_values_not_trusted(monkeypatch):
    store, _, calls, value = acquired(monkeypatch)
    original = store.snapshot
    value["rows"][0]["company_name"] = "client modified"
    value["provenance"]["body_sha256"] = "wrong"
    for symbol, name in [("0056", "元大高股息"), ("1449", "佳和"), ("1463", "強盛新")]:
        for operation in (events.build_official_events, events.capture_official_events):
            value = operation("TWSE", symbol, DAY, environment=ENABLED, store=store)
            assert value["status"] == "available" and value["rows"][0]["company_name"] == name
            assert value["capture_action"] == "cached"
    assert store.snapshot is original and len(calls) == 1


@pytest.mark.parametrize("rows,reason", [([ROWS[1]], "selected_symbol_missing:0056"),
    ([{**ROWS[0], "Exdividend": "unknown"}], "selected_event_class_unknown"),
    ([ROWS[0], ROWS[0]], "selected_event_duplicate")])
def test_invalid_or_missing_selected_capture_never_published(monkeypatch, rows, reason):
    _, calls = source(monkeypatch, rows)
    store = events.OfficialEventMemory()
    value = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    assert value["reasons"] == [reason] and value["capture_action"] == "failed"
    assert value["rows"] == [] and value["provenance"] is None and store.snapshot is None and len(calls) == 1


def test_missing_in_existing_feed_closed_without_fetch_or_prior_success(monkeypatch):
    store, _, calls, _ = acquired(monkeypatch)
    value = events.capture_official_events("TWSE", "2330", DAY, environment=ENABLED, store=store)
    assert value["status"] == "unavailable" and value["reasons"] == ["selected_symbol_missing:2330"]
    assert value["rows"] == [] and value["provenance"] is None and len(calls) == 1


@pytest.mark.parametrize("part", ["body", "receipt", "pins"])
def test_read_time_revalidation_rejects_tamper_without_refresh(monkeypatch, part):
    store, _, calls, _ = acquired(monkeypatch)
    body, receipt = store.snapshot
    if part == "body":
        store.snapshot = (body + b" ", receipt)
    elif part == "receipt":
        parsed = json.loads(receipt)
        parsed["source_version"] = "wrong"
        store.snapshot = (body, encoded(parsed))
    else:
        monkeypatch.setitem(events.PINS, "expected_digest", "sha256:" + "0" * 64)
    for operation in (events.build_official_events, events.capture_official_events):
        value = operation("TWSE", "0056", DAY, environment=ENABLED, store=store)
        assert value["status"] == "unavailable" and not value["rows"] and value["provenance"] is None
    assert len(calls) == 1


def test_summary_preflight_blocks_get_and_sanitizes_paths(monkeypatch):
    _, calls = source(monkeypatch)
    def denied(**kwargs):
        raise events.consumer.ActionCaptureError("purpose_not_admitted:summarize")
    monkeypatch.setattr(events.consumer, "_admission", denied)
    value = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=events.OfficialEventMemory())
    assert value["reasons"] == ["purpose_not_admitted:summarize"] and not calls
    def broken(**kwargs):
        raise OSError("C:/private/internal/manifest.json")
    monkeypatch.setattr(events.consumer, "_admission", broken)
    value = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=events.OfficialEventMemory())
    assert value["reasons"] == ["event_evidence_invalid"] and "private" not in json.dumps(value)


def test_http_failure_has_one_request_and_no_cache(monkeypatch):
    _, calls = source(monkeypatch, status=503)
    store = events.OfficialEventMemory()
    value = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    assert value["reasons"] == ["http_status:503"] and value["capture_action"] == "failed"
    assert len(calls) == 1 and store.snapshot is None


def test_concurrent_capture_single_get_and_normal_read_does_not_wait_or_fetch(monkeypatch):
    body, calls = source(monkeypatch)
    actual_capture = events.capture_memory
    entered, release = Event(), Event()
    def wait_capture(**kwargs):
        entered.set()
        assert release.wait(10)
        return actual_capture(**kwargs)
    monkeypatch.setattr(events, "capture_memory", wait_capture)
    store, output = events.OfficialEventMemory(), []
    def first():
        output.append(events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store))
    thread = Thread(target=first)
    thread.start()
    try:
        assert entered.wait(10)
        second = events.capture_official_events("TWSE", "1449", DAY, environment=ENABLED, store=store)
        assert second["reasons"] == ["event_capture_in_progress"] and not calls
        assert events.build_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)["reasons"] == ["event_memory_capture_missing"]
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and output[0]["status"] == "available" and len(calls) == 1
    assert store.snapshot[0] == body


def test_actual_router_get_import_zero_network_post_capture_and_dual_overview(monkeypatch):
    _, calls = source(monkeypatch)
    store = events.OfficialEventMemory()
    with memory_api(store=store) as client:
        assert calls == []
        prefix = "/api/stocks/TWSE/0056"
        before = client.get(prefix + "/overview?as_of=2026-10-03")
        assert before.status_code == 200 and before.json()["events"]["reasons"] == ["event_memory_capture_missing"]
        assert not calls
        assert client.post("/api/stocks/TWSE/2330/official-events/capture").status_code == 404
        assert client.post(prefix + "/official-events/capture?as_of=bad").status_code == 422
        assert client.post("/api/stocks/TPEx/0056/official-events/capture?as_of=2026-10-03").json()["reasons"] == ["event_exchange_not_supported"]
        assert not calls
        value = client.post(prefix + "/official-events/capture?as_of=2026-10-03").json()
        assert value["status"] == "available" and value["capture_action"] == "acquired" and len(calls) == 1
        for symbol in ("0056", "1449", "1463"):
            path = "/api/stocks/TWSE/" + symbol
            detail = client.get(path + "?as_of=2026-10-03")
            overview = client.get(path + "/overview?as_of=2026-10-03")
            assert detail.status_code == overview.status_code == 200
            assert detail.json()["overview"] == overview.json()
            assert overview.json()["events"]["status"] == "available"
        assert client.get(prefix + "/overview?as_of=2026-10-02").json()["events"]["rows"] == []
        missing = client.get(prefix + "/overview").json()
        assert missing["as_of"] is None and missing["events"]["observed_date"] == "2026-10-03"
        assert missing["events"]["reasons"] == ["event_shared_cutoff_missing"]
        assert client.post(prefix + "/official-events/capture?as_of=2026-10-03").json()["capture_action"] == "cached"
        assert len(calls) == 1


def test_router_disabled_after_success_hides_original(monkeypatch):
    _, calls = source(monkeypatch)
    with memory_api() as client:
        path = "/api/stocks/TWSE/0056"
        assert client.post(path + "/official-events/capture?as_of=2026-10-03").json()["status"] == "available"
        monkeypatch.setenv(events.CAPTURE_ENV, "0")
        for method, tail in [(client.get, "/overview"), (client.post, "/official-events/capture")]:
            value = method(path + tail + "?as_of=2026-10-03").json()
            projected = value if method == client.post else value["events"]
            assert projected["status"] == "unavailable"
            assert projected["rows"] == [] and projected["provenance"] is None and not projected["cache_present"]
        assert len(calls) == 1


def test_router_post_failure_keeps_selected_reason_and_publishes_no_original(monkeypatch):
    _, calls = source(monkeypatch, [ROWS[1]])
    with memory_api() as client:
        path = "/api/stocks/TWSE/0056"
        value = client.post(path + "/official-events/capture?as_of=2026-10-03").json()
        assert value["status"] == "unavailable" and value["capture_action"] == "failed"
        assert value["reasons"] == ["selected_symbol_missing:0056"] and len(calls) == 1
        assert events.MEMORY_EVENTS.snapshot is None
        held_failure = client.get(path + "/overview?as_of=2026-10-03").json()["events"]
        assert held_failure["reasons"] == ["selected_symbol_missing:0056"] and not held_failure["can_capture"]
        assert len(calls) == 1


@pytest.mark.parametrize("first", ["focus", "selected"])
@pytest.mark.parametrize("failure", ["http", "receipt", "full_feed"])
def test_first_failed_attempt_seals_focus_and_selected_across_conditions(monkeypatch, first, failure):
    monkeypatch.setattr(events, "_today_taipei", lambda: DAY)
    rows = [*ROWS, {**ROWS[0], "Code": "9999", "Date": "1150101", "Exdividend": "unknown"}] if failure == "full_feed" else ROWS
    _, calls = source(monkeypatch, rows, status=503 if failure == "http" else 200)
    if failure == "receipt":
        real = events.capture_memory
        def invalid_receipt(**kwargs):
            body, receipt = real(**kwargs)
            value = json.loads(receipt)
            value["body_sha256"] = "0" * 64
            return body, encoded(value)
        monkeypatch.setattr(events, "capture_memory", invalid_receipt)
    store = events.OfficialEventMemory()
    value = events.capture_official_event_focus(DAY, from_date="2026-10-22", to_date="2026-10-22", environment=ENABLED, store=store) if first == "focus" else events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    assert value["status"] == "unavailable" and value["capture_action"] == "failed"
    assert store.attempted and store.snapshot is None and not value["can_capture"] and len(calls) == 1
    reason = value["reasons"]
    for operation in (events.build_official_event_focus, events.capture_official_event_focus):
        held = operation(DAY, q="1449", from_date="2026-01-01", to_date="2026-12-31", environment=ENABLED, store=store)
        assert held["reasons"] == reason and held["items"] == [] and not held["can_capture"]
        assert all(held[key] == 0 for key in ("total", "matched", "displayed", "range_event_count", "range_matched", "candidate_count", "selected_count"))
    for symbol in ("0056", "1449"):
        for operation in (events.build_official_events, events.capture_official_events):
            held = operation("TWSE", symbol, DAY, environment=ENABLED, store=store)
            assert held["reasons"] == reason and held["rows"] == [] and held["provenance"] is None and not held["can_capture"]
    assert len(calls) == 1 and store.snapshot is None


def test_selected_missing_failure_cannot_retry_another_symbol_or_focus(monkeypatch):
    monkeypatch.setattr(events, "_today_taipei", lambda: DAY)
    _, calls = source(monkeypatch, [ROWS[1]])
    store = events.OfficialEventMemory()
    failed = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    assert failed["reasons"] == ["selected_symbol_missing:0056"] and not failed["can_capture"]
    assert events.capture_official_events("TWSE", "1449", DAY, environment=ENABLED, store=store)["reasons"] == failed["reasons"]
    assert events.capture_official_event_focus(DAY, environment=ENABLED, store=store)["reasons"] == failed["reasons"]
    assert store.snapshot is None and len(calls) == 1


def test_preflight_admission_failure_does_not_spend_capture_attempt(monkeypatch):
    _, calls = source(monkeypatch)
    store = events.OfficialEventMemory()
    admission = consumer._admission
    def refused(**kwargs):
        raise consumer.ActionCaptureError("source_not_admitted")
    monkeypatch.setattr(consumer, "_admission", refused)
    value = events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)
    assert value["status"] == "unavailable" and not store.attempted and calls == []
    monkeypatch.setattr(consumer, "_admission", admission)
    assert events.capture_official_events("TWSE", "0056", DAY, environment=ENABLED, store=store)["status"] == "available"
    assert len(calls) == 1
