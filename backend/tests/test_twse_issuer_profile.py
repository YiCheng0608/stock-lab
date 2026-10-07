"""Reconstructable RAM-only issuer boundaries and actual-router launch helper.

Install test_official_events.install_zero_disk_guard before importing this file
or pytest. Use --noconftest, no cache/logging plugins and -B. The helper requires
external issuer pins; it never grants them, fetches sources or adds debug routes.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from app import official_events as events
from app import twse_issuer_profile as issuer
from worker import twse_issuer_capture as consumer
from test_official_events import encoded, memory_app, source as event_source

DAY = date(2026, 10, 8)
ENABLED = {issuer.CAPTURE_ENV: "1", issuer.REGISTRY_VERSION_ENV: consumer.REGISTRY_VERSION,
           issuer.REGISTRY_DIGEST_ENV: consumer.REGISTRY_DIGEST, issuer.PROFILE_VERSION_ENV: issuer.VERSION,
           issuer.PROFILE_DIGEST_ENV: issuer.POLICY_DIGEST, events.CAPTURE_ENV: "1"}
NAMES = {"1449": "佳和", "1463": "強盛新", "2614": "東森"}
EVENT_ROWS = [{"Code": code, "Name": name, "Date": raw, "Exdividend": kind}
              for code, name, raw, kind in [("1449", "佳和", "1151012", "權"),
                                             ("1463", "強盛新", "1151015", "息"),
                                             ("2614", "東森", "1151006", "權息"),
                                             ("0056", "元大高股息", "1151022", "息")]]


def issuer_rows():
    rows = []
    for code, name in NAMES.items():
        row = dict.fromkeys(consumer.FIELDS, "")
        row.update({"出表日期": "1151008", "公司代號": code, "公司名稱": name + "股份有限公司",
                    "公司簡稱": name, "上市日期": "19900102", "產業別": "91" if code == "2614" else "04",
                    "實收資本額": "UNVALIDATED", "已發行普通股數或TDR原股發行股數": "UNVALIDATED"})
        rows.append(row)
    return rows


@contextmanager
def issuer_memory_app(*, issuer_store=None, event_store=None, environment=None):
    """ROOT may serve the real router and inspect originals via app.state.

    The four catalogue rows only route requests. With environment=None this
    preserves the launcher's external pins. It does not supply pins or preload.
    ROOT can call app.state.issuer_originals() from its own held stdin inspector;
    the returned byte pairs are the store's original objects, not API exports.
    """
    issuer_store = issuer_store if issuer_store is not None else issuer.IssuerMemory()
    event_store = event_store if event_store is not None else events.OfficialEventMemory()
    event_generation = getattr(event_store, "generation_id", None) or str(uuid4())
    event_store.generation_id = event_generation
    catalogue = (("0056", "合成ETF路由", "etf"), *(tuple((code, "合成路由" + code, "stock")) for code in consumer.SYMBOLS))
    with patch.dict(os.environ, environment or {}), patch.object(issuer, "MEMORY_ISSUERS", issuer_store):
        with memory_app(store=event_store, catalogue=catalogue, enabled=os.environ.get(events.CAPTURE_ENV, "")) as app:
            # The reusable event test helper adds a cross-market fixture; this
            # launch contract exposes only its four explicitly admitted routes.
            from app.api import get_db
            from app.models import Instrument
            session_iterator = app.dependency_overrides[get_db]()
            try:
                session = next(session_iterator)
                session.query(Instrument).filter(Instrument.exchange != "TWSE").delete()
                session.commit()
            finally:
                session_iterator.close()
            app.state.issuer_memory = issuer_store
            app.state.event_memory = event_store
            def originals():
                return {"issuer_generation": issuer_store.generation_id, "event_generation": event_generation,
                        "issuer_snapshot": issuer_store.snapshot, "event_snapshot": event_store.snapshot,
                        "issuer_failure_receipt": issuer_store.failure_receipt,
                        "issuer_failure_original": issuer_store.failure_original,
                        "issuer_attempted": issuer_store.attempted, "event_attempted": event_store.attempted,
                        "issuer_snapshot_id": id(issuer_store.snapshot), "event_snapshot_id": id(event_store.snapshot)}
            app.state.issuer_originals = originals
            yield app


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(issuer, "_today_taipei", lambda: DAY)
    monkeypatch.setattr(events, "_today_taipei", lambda: DAY)
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 7, 22, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(consumer, "datetime", FixedDatetime)


def transport(rows=None, *, status=200, encoding="identity", handler=None):
    body = encoded(issuer_rows() if rows is None else rows)
    calls = []
    def request(request):
        calls.append(request)
        assert str(request.url) == consumer.ENDPOINT and request.method == "GET"
        if handler:
            return handler(request, body)
        return httpx.Response(status, headers={"Content-Encoding": encoding}, stream=httpx.ByteStream(body))
    return body, calls, httpx.MockTransport(request)


def selected_events(symbol="1449", *, name=None, cutoff=DAY):
    return {"status": "available", "as_of": cutoff.isoformat(),
            "rows": [{"exchange": "TWSE", "symbol": symbol, "company_name": name or NAMES[symbol]}]}


def acquire(rows=None, *, symbol="1449", name=None, **kwargs):
    body, calls, adapter = transport(rows, **kwargs)
    store = issuer.IssuerMemory(transport=adapter)
    result = issuer.capture_issuer_profile("TWSE", symbol, DAY, events=selected_events(symbol, name=name),
                                          environment=ENABLED, store=store)
    return body, calls, store, result


def test_complete_schema_and_selected_raw_mapping_no_classification():
    body, calls, store, data = acquire()
    assert data["status"] == "available" and len(calls) == 1
    assert data["row"]["full_name"] == "佳和股份有限公司"
    assert data["row"]["source_row"] == issuer_rows()[0]
    assert data["row"]["report_date"] == "2026-10-08" and data["row"]["listing_date"] == "1990-01-02"
    assert data["provenance"]["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert data["provenance"]["receipt_sha256"] == hashlib.sha256(store.snapshot[1]).hexdigest()
    assert data["classification"] == data["historical_pit"] == "unsupported"
    assert store.snapshot[0] is body or store.snapshot[0] == body
    for symbol in consumer.SYMBOLS:
        read = issuer.capture_issuer_profile("TWSE", symbol, DAY, events=selected_events(symbol), environment=ENABLED, store=store)
        assert read["status"] == "available" and read["capture_action"] == "cached"
    assert len(calls) == 1


@pytest.mark.parametrize("raw,expected", [("19900102", "1990-01-02"), ("0790102", "1990-01-02"), ("1151008", "2026-10-08")])
def test_listing_exact_date_grammars(raw, expected):
    assert consumer.source_date(raw) == expected


@pytest.mark.parametrize("raw,report", [("19900102", True), ("1150230", True), ("0001008", True), ("1151008 ", True),
                                          ("19900230", False), ("00000102", False), ("", False), ("１１５１００８", False)])
def test_invalid_dates(raw, report):
    with pytest.raises(consumer.IssuerCaptureError):
        consumer.source_date(raw, report=report)


@pytest.mark.parametrize("mutation", ["field_missing", "extra_field", "wrong_type", "duplicate", "outside_scope_wrong_type",
                                        "report", "listing", "name", "industry"])
def test_all_feed_validation_and_failure_seal(mutation):
    rows = issuer_rows()
    if mutation == "field_missing": del rows[0]["網址"]
    elif mutation == "extra_field": rows[0]["Unknown"] = ""
    elif mutation == "wrong_type": rows[0]["住址"] = None
    elif mutation == "duplicate": rows.append(dict(rows[0]))
    elif mutation == "outside_scope_wrong_type":
        extra = dict(rows[0], **{"公司代號": "9999", "住址": 0})
        rows.append(extra)
    elif mutation == "report": rows[0]["出表日期"] = "1150230"
    elif mutation == "listing": rows[0]["上市日期"] = ""
    elif mutation == "name": rows[0]["公司名稱"] = ""
    elif mutation == "industry": rows[0]["產業別"] = ""
    body, calls, store, result = acquire(rows)
    assert result["status"] == "unavailable" and store.attempted and store.snapshot is None
    assert store.failure_receipt is not None
    assert store.failure_original[0] == body and store.failure_original[1] is store.failure_receipt
    receipt = consumer.strict_json(store.failure_receipt)
    assert receipt["body_sha256"] == hashlib.sha256(body).hexdigest() and receipt["body_bytes"] == len(body)
    for symbol in consumer.SYMBOLS:
        assert issuer.capture_issuer_profile("TWSE", symbol, DAY, events=selected_events(symbol),
                                              environment=ENABLED, store=store)["capture_action"] == "failed"
    assert len(calls) == 1


@pytest.mark.parametrize("rows", [[], {}, ["row"], [dict(issuer_rows()[0], **{"公司代號": " 1449"})]])
def test_array_shape_and_company_code_required(rows):
    assert acquire(rows)[3]["status"] == "unavailable"


@pytest.mark.parametrize("status,encoding", [(503, "identity"), (302, "identity"), (200, "gzip")])
def test_transport_failure_spent(status, encoding):
    _, calls, store, result = acquire(status=status, encoding=encoding)
    assert result["capture_action"] == "failed" and store.attempted and store.snapshot is None
    issuer.capture_issuer_profile("TWSE", "1463", DAY, events=selected_events("1463"), environment=ENABLED, store=store)
    assert len(calls) == 1


def test_missing_selected_absent_and_name_conflict_preserve_originals():
    body, calls, store, missing = acquire(issuer_rows()[1:])
    assert missing["status"] == "unavailable" and missing["feed_status"] == "available"
    assert missing["profile_present"] is False and missing["row"] is missing["provenance"] is None
    assert store.snapshot[0] == body and len(calls) == 1
    body, calls, store, conflict = acquire(name="不同來源名稱")
    assert conflict["reasons"] == ["issuer_event_name_conflict"] and conflict["row"] is None
    assert store.snapshot[0] == body and store.snapshot is not None
    summary = consumer.summarize_memory(*store.snapshot, expected_registry_version=consumer.REGISTRY_VERSION,
                                        expected_digest=consumer.REGISTRY_DIGEST, generation_id=store.generation_id)
    assert summary["selected"]["1449"]["short_name"] == "佳和"
    assert issuer.build_issuer_profile("TWSE", "1449", DAY, events=selected_events(name="佳和股份有限公司"),
                                      environment=ENABLED, store=store)["status"] == "available"
    assert len(calls) == 1


@pytest.mark.parametrize("key", [issuer.REGISTRY_VERSION_ENV, issuer.REGISTRY_DIGEST_ENV, issuer.PROFILE_VERSION_ENV,
                                  issuer.PROFILE_DIGEST_ENV, issuer.CAPTURE_ENV])
def test_required_external_pins_precede_attempt(key):
    _, calls, adapter = transport()
    store = issuer.IssuerMemory(transport=adapter)
    env = {name: value for name, value in ENABLED.items() if name != key}
    result = issuer.capture_issuer_profile("TWSE", "1449", DAY, events=selected_events(), environment=env, store=store)
    assert result["status"] == "unavailable" and calls == [] and not store.attempted


@pytest.mark.parametrize("change", ["digest", "generation", "request_count", "extra", "time", "http", "canonical"])
def test_receipt_consistency_is_strict(change):
    _, _, store, _ = acquire()
    body, original = store.snapshot
    receipt = consumer.strict_json(original)
    if change == "digest": receipt["body_sha256"] = "0" * 64
    elif change == "generation": receipt["generation_id"] = str(uuid4())
    elif change == "request_count": receipt["request_count"] = True
    elif change == "extra": receipt["artifact"] = "forbidden"
    elif change == "time": receipt["captured_at"] = "2026-10-07T22:00:00"
    elif change == "http": receipt["http_status"] = 503
    changed = json.dumps(receipt).encode() if change == "canonical" else consumer.canonical(receipt)
    with pytest.raises(consumer.IssuerCaptureError):
        consumer.summarize_memory(body, changed, expected_registry_version=consumer.REGISTRY_VERSION,
                                  expected_digest=consumer.REGISTRY_DIGEST, generation_id=store.generation_id)


def test_cutoff_and_unsupported_never_fallback():
    _, calls, store, _ = acquire()
    for cutoff in (None, date(2026, 10, 7)):
        result = issuer.build_issuer_profile("TWSE", "1449", cutoff, events=selected_events(), environment=ENABLED, store=store)
        assert result["status"] == "unavailable" and result["row"] is result["provenance"] is None
    unsupported = issuer.build_issuer_profile("TWSE", "0056", DAY, events=selected_events(), environment=ENABLED, store=store)
    assert unsupported["reasons"] == ["issuer_symbol_not_supported"]
    assert issuer.build_issuer_profile("TWSE", "1449", DAY, events=selected_events(), environment=ENABLED, store=store)["status"] == "available"
    assert len(calls) == 1


def test_inflight_single_attempt_and_failed_read_clear():
    entered, release = Event(), Event()
    def wait(_, body):
        entered.set()
        assert release.wait(3)
        return httpx.Response(200, stream=httpx.ByteStream(body))
    _, calls, adapter = transport(handler=wait)
    store = issuer.IssuerMemory(transport=adapter)
    results = []
    thread = Thread(target=lambda: results.append(issuer.capture_issuer_profile("TWSE", "1449", DAY,
                    events=selected_events(), environment=ENABLED, store=store)))
    thread.start()
    assert entered.wait(3)
    assert issuer.capture_issuer_profile("TWSE", "1463", DAY, events=selected_events("1463"), environment=ENABLED, store=store)["busy"]
    release.set(); thread.join(3)
    assert results[0]["status"] == "available" and len(calls) == 1
    body, receipt = store.snapshot
    store.snapshot = (body, receipt + b" ")
    bad = issuer.build_issuer_profile("TWSE", "1449", DAY, events=selected_events(), environment=ENABLED, store=store)
    assert bad["status"] == "unavailable" and bad["row"] is bad["provenance"] is None


def test_router_initial_zero_network_invalid_before_db_and_same_cutoff(monkeypatch):
    from fastapi.testclient import TestClient
    _, event_calls = event_source(monkeypatch, EVENT_ROWS, captured_at="2026-10-07T22:00:00+00:00")
    _, issuer_calls, adapter = transport()
    issuer_store, event_store = issuer.IssuerMemory(transport=adapter), events.OfficialEventMemory()
    with issuer_memory_app(issuer_store=issuer_store, event_store=event_store, environment=ENABLED) as app:
        from app import api
        with TestClient(app) as client:
            before = client.get("/api/stocks/TWSE/1449?as_of=2026-10-08").json()
            assert before["overview"]["issuer_profile"]["status"] == "unavailable"
            assert event_calls == issuer_calls == []
            provider = app.dependency_overrides[api.get_db]
            def forbidden():
                raise AssertionError("invalid request reached database")
                yield
            app.dependency_overrides[api.get_db] = forbidden
            for query, body in [("", {}), ("?as_of=2026-10-08&as_of=2026-10-08", {}),
                                ("?as_of=2026-02-30", {}), ("?as_of=2026-10-08&next=x", {}),
                                ("?as_of=2026-10-08", {"x": 1})]:
                assert client.post("/api/stocks/TWSE/1449/issuer-profile/capture" + query, json=body).status_code == 422
            app.dependency_overrides[api.get_db] = provider
            assert event_calls == issuer_calls == []
            assert client.post("/api/focus/official-events/capture?as_of=2026-10-08&from=2026-10-01&to=2026-12-31&event_kind=ex_right&q=1449", json={}).json()["status"] == "available"
            result = client.post("/api/stocks/TWSE/1449/issuer-profile/capture?as_of=2026-10-08", json={}).json()
            assert result["status"] == "available" and len(issuer_calls) == len(event_calls) == 1
            for symbol in consumer.SYMBOLS:
                detail = client.get(f"/api/stocks/TWSE/{symbol}?as_of=2026-10-08").json()
                assert detail["instrument"]["name"].startswith("合成路由")
                assert detail["overview"]["issuer_profile"]["row"]["short_name"] == NAMES[symbol]
                assert detail["overview"]["events"]["as_of"] == detail["overview"]["issuer_profile"]["as_of"]
                assert client.post(f"/api/stocks/TWSE/{symbol}/issuer-profile/capture?as_of=2026-10-08", json={}).json()["capture_action"] == "cached"
            earlier = client.get("/api/stocks/TWSE/1449?as_of=2026-10-07").json()["overview"]
            assert earlier["issuer_profile"]["row"] is None and earlier["events"]["rows"] == []
            assert client.get("/api/stocks/TWSE/0056?as_of=2026-10-08").json()["overview"]["issuer_profile"]["reasons"] == ["issuer_symbol_not_supported"]
            originals = app.state.issuer_originals()
            assert originals["issuer_snapshot"] is issuer_store.snapshot and originals["event_snapshot"] is event_store.snapshot
            assert originals["issuer_generation"] != originals["event_generation"]
            assert len(issuer_calls) == len(event_calls) == 1
