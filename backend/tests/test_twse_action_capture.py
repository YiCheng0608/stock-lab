"""Memory-only verification: run with --noconftest and no cache/plugin writes.

Fixtures are reconstructable in memory; MockTransport is not live evidence.
Disk capture regression uses a mock sink and does not verify ZIP publication.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from worker import source_registry as registry
from worker import source_runtime as runtime
from worker import twse_action_capture as actions

PINS = {"manifest": registry.REGISTRY_PATH, "profile": "free_public_local",
        "expected_registry_version": "r1-a1-c009-2026-09-12.1",
        "expected_digest": "sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b"}
ROWS = [{"Code": "6834", "Name": "公司甲", "Date": "1151002", "Exdividend": "權", "Reference": "1.2500"},
        {"Code": "2614", "Name": "公司乙", "Date": "1151006", "Exdividend": "權息"},
        {"Code": "1463", "Name": "公司丙", "Date": "1151015", "Exdividend": "息"},
        {"Code": "6834", "Name": "公司甲", "Date": "1151102", "Exdividend": "息"}]


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def transport(body, *, status=200, headers=None):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers=headers or {}, stream=httpx.ByteStream(body))
    return httpx.MockTransport(handler), calls


def captured(body=None, *, monkeypatch=None):
    body = encoded(ROWS) if body is None else body
    adapter, calls = transport(body)
    if monkeypatch:
        moments = iter(["2026-10-03T00:00:00+00:00", "2026-10-03T00:00:01+00:00"])
        monkeypatch.setattr(runtime, "_utc", lambda: next(moments))
    raw, receipt = runtime.capture_memory(**PINS, source_id=actions.SOURCE_ID, transport=adapter)
    assert raw == body and len(calls) == 1
    return raw, receipt, calls


def summary(body, receipt, **overrides):
    return actions.summarize_memory_capture(body, receipt, **{**PINS, "symbols": ["6834", "2614", "1463"], **overrides})


def memory_manifest(monkeypatch, edit):
    manifest = registry.load_manifest(registry.REGISTRY_PATH)
    edit(next(s for s in manifest["sources"] if s["source_id"] == actions.SOURCE_ID))
    manifest["content_digest"] = registry.manifest_digest(manifest)
    # Keep the real validator/pin/policy path; replace only filesystem reading.
    monkeypatch.setattr(registry, "_read_manifest", lambda _: deepcopy(manifest))
    return {**PINS, "expected_digest": manifest["content_digest"]}


def test_selected_multi_event_future_dates_raw_strings_and_distinct_clocks(monkeypatch):
    body, receipt, calls = captured(monkeypatch=monkeypatch)
    result = summary(body, receipt)
    assert result["selected_count"] == result["candidate_count"] == 4
    assert [r["row_ordinal"] for r in result["rows"]] == [1, 4, 2, 3]
    assert result["rows"][0]["source_row"]["Reference"] == "1.2500"
    assert result["rows"][1]["event_date"] == "2026-11-02"
    assert [r["kind"] for r in result["rows"]] == ["ex_right", "ex_dividend", "ex_right_and_dividend", "ex_dividend"]
    assert all(r["event_date_role"] == "effective_date" and r["event_date_precision"] == "date" for r in result["rows"])
    assert all(r["published_at"] is r["first_available_at"] is r["revision_available_at"] is None for r in result["rows"])
    assert result["provenance"]["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert result["provenance"]["receipt_sha256"] == hashlib.sha256(receipt).hexdigest()
    assert result["provenance"]["captured_at"] == "2026-10-03T00:00:01+00:00"
    assert result["historical_pit"] == "unsupported" and result["durable_capture"] is False
    parsed = json.loads(receipt)
    assert parsed["schema_version"] == "source-memory-capture/v1" and parsed["storage"] == "memory_only"
    assert "artifact" not in parsed
    assert parsed["condition_receipts"]["preserve_source_integrity"]["artifact"] == "memory:body"
    assert str(calls[0].url) == actions.ENDPOINT and calls[0].method == "GET"
    assert calls[0].headers["Accept-Encoding"] == "identity" and "authorization" not in calls[0].headers


@pytest.mark.parametrize("override", [{"symbols": []}, {"symbols": "6834"}, {"symbols": ["6834", "6834"]},
                                      {"symbols": [6834]}, {"symbols": [" 6834"]},
                                      {"expected_digest": "sha256:wrong"}, {"expected_registry_version": "wrong"},
                                      {"profile": "wrong"}, {"manifest": None}])
def test_live_preflight_rejection_has_zero_requests(override):
    adapter, calls = transport(encoded(ROWS))
    with pytest.raises((actions.ActionCaptureError, registry.RegistryError)):
        actions.live_summarize(**{**PINS, "symbols": ["6834"], **override}, transport=adapter)
    assert calls == []


@pytest.mark.parametrize("purpose", ["local_fetch", "raw_store", "summarize"])
def test_policy_denied_precedes_live_get(monkeypatch, purpose):
    pins = memory_manifest(monkeypatch, lambda s: s["purposes"][purpose].update(status="denied"))
    adapter, calls = transport(encoded(ROWS))
    with pytest.raises(actions.ActionCaptureError, match="purpose_not_admitted"):
        actions.live_summarize(**pins, symbols=["6834"], transport=adapter)
    assert calls == []


@pytest.mark.parametrize("change", [lambda s: s.update(exact_url="https://example.invalid/"),
                                    lambda s: s.update(method="POST"),
                                    lambda s: s["purposes"]["local_fetch"]["conditions"].append("unimplemented"),
                                    lambda s: s["access"].update(rate_limit={"status": "known", "value": "1/minute"})])
def test_memory_runtime_preflight_rejects_bad_contract_with_zero_requests(monkeypatch, change):
    pins = memory_manifest(monkeypatch, change)
    adapter, calls = transport(encoded(ROWS))
    body, receipt = runtime.capture_memory(**pins, source_id=actions.SOURCE_ID, transport=adapter)
    assert body is None and calls == []
    assert json.loads(receipt)["status"] == "rejected" and json.loads(receipt)["request_count"] == 0


@pytest.mark.parametrize("source_id", ["unknown", "tpex_3insti_daily_trading", "twse_stock_day_all",
                                      "twse_holiday_schedule", "tpex_spendi_history"])
def test_runtime_wrong_or_unadmitted_source_has_zero_requests(source_id):
    adapter, calls = transport(b"[]")
    body, receipt = runtime.capture_memory(**PINS, source_id=source_id, transport=adapter)
    assert body is None and calls == [] and json.loads(receipt)["status"] == "rejected"
    assert json.loads(receipt)["error_reason"] == "memory_source_not_supported"


@pytest.mark.parametrize("change,reason", [
    (lambda r: r.update(schema_version="source-capture/v1"), "schema_version"),
    (lambda r: r.update(storage="disk"), "storage"),
    (lambda r: r.update(artifact="capture.zip"), "has_artifact"),
    (lambda r: r.update(source_id="twse_stock_day_all"), "source_id"),
    (lambda r: r.update(body_sha256="0" * 64), "body_sha256"),
    (lambda r: r.update(body_bytes=True), "body_bytes"),
    (lambda r: r.update(http_status=True), "invalid_http_status"),
    (lambda r: r.update(request_count=True), "request_count"),
    (lambda r: r.update(captured_at="2026-10-03T00:00:01"), "must_be_utc"),
    (lambda r: r.update(captured_at="2026-10-03T08:00:01+08:00"), "must_be_utc"),
    (lambda r: r.update(captured_at="2026-10-02T00:00:00+00:00"), "nonmonotonic"),
    (lambda r: r["condition_receipts"]["bounded_requests"].update(max_requests=True), "condition_receipts"),
    (lambda r: r["condition_receipts"]["preserve_source_integrity"].update(artifact="body.bin"), "condition_receipts"),
    (lambda r: r["attribution"].update(terms={}), "attribution"),
    (lambda r: r.update(executed_purposes=["local_fetch"]), "executed_purposes"),
])
def test_receipt_tampering_rejected(monkeypatch, change, reason):
    body, receipt, _ = captured(monkeypatch=monkeypatch)
    parsed = json.loads(receipt)
    change(parsed)
    with pytest.raises(actions.ActionCaptureError, match=reason):
        summary(body, encoded(parsed))


@pytest.mark.parametrize("rows,reason", [
    ([], "nonempty_row_list"), ({}, "nonempty_row_list"), ([True], "row_object"),
    ([{**ROWS[0], "Code": 6834}], "invalid_security_code"),
    ([{k: v for k, v in ROWS[0].items() if k != "Code"}], "invalid_security_code"),
    ([{**ROWS[0], "Date": "2026-10-02"}], "invalid_effective_date"),
    ([{**ROWS[0], "Date": "1150230"}], "invalid_effective_date"),
    ([{**ROWS[0], "Date": 1151002}], "invalid_effective_date"),
    ([{**ROWS[0], "Name": None}], "selected_name_missing"),
    ([{**ROWS[0], "Exdividend": "息權"}], "selected_event_class_unknown"),
    ([{**ROWS[0], "Exdividend": 1}], "selected_event_class_unknown"),
    ([ROWS[0], ROWS[0]], "selected_event_duplicate"),
    ([ROWS[1]], "selected_symbol_missing"),
    ([ROWS[0], {**ROWS[1], "Date": "1150230"}], "invalid_effective_date"),
])
def test_bad_payload_or_selection_rejected(rows, reason):
    body, receipt, _ = captured(encoded(rows))
    with pytest.raises(actions.ActionCaptureError, match=reason):
        summary(body, receipt, symbols=["6834"])


@pytest.mark.parametrize("body,reason", [(b'[{"Code":"6834","Code":"2614"}]', "duplicate_json_key"),
                                         (b'[{"v":1e9999}]', "nonfinite_json")])
def test_duplicate_key_and_overflow_rejected(body, reason):
    raw, receipt, _ = captured(body)
    with pytest.raises(actions.ActionCaptureError, match=reason):
        summary(raw, receipt)


def test_exact_fields_authoritative_and_unselected_class_not_upgraded():
    rows = [{**ROWS[0], "代號": "9999", "除權息": "unknown"}, {**ROWS[1], "Exdividend": "unknown", "Name": None}]
    raw, receipt, _ = captured(encoded(rows))
    result = summary(raw, receipt, symbols=["6834"])
    assert result["selected_count"] == 1 and result["candidate_count"] == 2
    assert result["rows"][0]["source_row"]["代號"] == "9999"
    assert result["rows"][0]["symbol"] == "6834"


@pytest.mark.parametrize("status", [301, 307, 429, 503])
def test_http_failure_one_attempt_memory_receipt_and_no_body(status):
    adapter, calls = transport(b"[]", status=status, headers={"Retry-After": "60", "Location": "https://example.invalid/"})
    result = actions.live_summarize(**PINS, symbols=["6834"], transport=adapter)
    assert result["status"] == "unavailable" and len(calls) == 1
    receipt = result["capture_receipt"]
    assert receipt["http_status"] == status and receipt["retry_after"] == "60"
    assert receipt["status"] == "capture_failed" and receipt["executed_purposes"] == []
    assert "artifact" not in receipt


@pytest.mark.parametrize("body,headers,reason", [(b"not json", {}, "invalid_json"), (b"NaN", {}, "invalid_json"),
                                                 (b"[]", {"Content-Encoding": "gzip"}, "unsupported_content_encoding"),
                                                 (b"[123456789]", {}, "body_limit_exceeded")])
def test_runtime_body_encoding_and_size_failure(monkeypatch, body, headers, reason):
    monkeypatch.setattr(runtime, "MAX_BODY_BYTES", 10)
    adapter, calls = transport(body, headers=headers)
    raw, receipt = runtime.capture_memory(**PINS, source_id=actions.SOURCE_ID, transport=adapter)
    assert raw is None and len(calls) == 1 and json.loads(receipt)["error_reason"] == reason


def test_cooperative_deadline_and_timeout_fail_without_retry(monkeypatch):
    moments = iter([0.0, 31.0])
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(moments))
    adapter, calls = transport(b"[]")
    body, receipt = runtime.capture_memory(**PINS, source_id=actions.SOURCE_ID, transport=adapter)
    assert body is None and len(calls) == 1 and json.loads(receipt)["error_reason"] == "request_deadline_exceeded"
    monkeypatch.undo()
    calls = []
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("fixture", request=request)
    body, receipt = runtime.capture_memory(**PINS, source_id=actions.SOURCE_ID, transport=httpx.MockTransport(timeout))
    assert body is None and len(calls) == 1 and json.loads(receipt)["error_reason"] == "ReadTimeout"


@pytest.mark.parametrize("source_id", ["twse_stock_day_all", "twse_holiday_schedule", "twse_twt48u_all", "tpex_spendi_history"])
def test_original_disk_receipt_contract_with_mock_sink_only(monkeypatch, source_id):
    sink = []
    target = Path("mock-output")
    monkeypatch.setattr(runtime, "_output_path", lambda _: target)
    monkeypatch.setattr(runtime, "_publish", lambda p, b, r: sink.append((p, b, deepcopy(r))))
    adapter, calls = transport(b'[ { "v": 1.00 } ]\n')
    receipt = runtime.capture(**PINS, source_id=source_id, output_dir=target, transport=adapter)
    assert receipt["schema_version"] == "source-capture/v1" and "storage" not in receipt
    assert receipt["artifact"] == str(target / "capture.zip") and receipt["status"] == "capture_complete"
    assert receipt["condition_receipts"]["attribute_source"]["artifact"] == "receipt.json:attribution"
    assert receipt["condition_receipts"]["preserve_source_integrity"]["artifact"] == "body.bin"
    assert sink == [(target, b'[ { "v": 1.00 } ]\n', receipt)] and len(calls) == 1


def test_original_disk_sink_failure_semantics_with_no_files(monkeypatch):
    monkeypatch.setattr(runtime, "_output_path", lambda _: Path("mock-output"))
    def fail(*_):
        raise OSError("mock sink refused")
    monkeypatch.setattr(runtime, "_publish", fail)
    adapter, calls = transport(b"[]")
    receipt = runtime.capture(**PINS, source_id=actions.SOURCE_ID, output_dir="mock-output", transport=adapter)
    assert receipt["status"] == "capture_failed" and receipt["executed_purposes"] == []
    assert receipt["error_reason"] == "OSError" and "artifact" not in receipt and len(calls) == 1


def test_cli_success_emits_selected_rows_not_whole_body_and_failure_exit(monkeypatch, capsys):
    adapter, calls = transport(encoded(ROWS))
    original = actions.capture_memory
    monkeypatch.setattr(actions, "capture_memory", lambda **kwargs: original(**{**kwargs, "transport": adapter}))
    argv = ["live-summarize", "--manifest", str(PINS["manifest"]), "--profile", PINS["profile"],
            "--source", actions.SOURCE_ID, "--expected-registry-version", PINS["expected_registry_version"],
            "--expected-digest", PINS["expected_digest"], "--symbol", "6834"]
    assert actions._cli(argv) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["selected_count"] == 2 and all(r["symbol"] == "6834" for r in output["rows"])
    assert "body" not in output and "body.bin" not in output and len(calls) == 1
    argv[-1] = "bad symbol"
    assert actions._cli(argv) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable" and len(calls) == 1
