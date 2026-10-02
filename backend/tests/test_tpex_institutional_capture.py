from __future__ import annotations

import copy
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import httpx
import pytest

from worker import source_registry as registry
from worker import source_runtime as runtime
from worker import tpex_institutional_capture as consumer

DAY = date(2026, 10, 2)
FOREIGN_BUY = "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy"
FOREIGN_SELL = " Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell"
FOREIGN_NET = "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"


def row(symbol="3105"):
    # Independent, hand-calculated example: 750 - 30 - 40 = 680 shares.
    return {"Date": "1151002", "SecuritiesCompanyCode": symbol, "CompanyName": "範例公司",
            FOREIGN_BUY: "1000", FOREIGN_SELL: "250", FOREIGN_NET: "750",
            "SecuritiesInvestmentTrustCompanies-TotalBuy": "20",
            "SecuritiesInvestmentTrustCompanies-TotalSell": "50",
            "SecuritiesInvestmentTrustCompanies-Difference": "-30",
            "Dealers-TotalBuy": "0", "Dealers-TotalSell": "40", "Dealers-Difference": "-40",
            "TotalDifference": "680", "ForeignDealer-Difference": "9999999"}


def encode_zip(body, receipt, *, compression=zipfile.ZIP_STORED, names=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as archive:
        for name, value in names or [("body.bin", body), ("receipt.json", json.dumps(receipt, ensure_ascii=False).encode())]:
            archive.writestr(name, value)
    return stream.getvalue()


@pytest.fixture
def evidence(monkeypatch):
    manifest = registry.load_manifest(consumer.REGISTRY_PATH)
    args = dict(manifest=consumer.REGISTRY_PATH, profile="free_public_local",
                expected_registry_version=manifest["registry_version"], expected_digest=manifest["content_digest"],
                expected_date=DAY, symbols=["3105"])
    saved = []
    monkeypatch.setattr(runtime, "_output_path", lambda _: Path("memory-capture"))
    monkeypatch.setattr(runtime, "_publish", lambda output, body, receipt: saved.append((body, receipt.copy())))
    body = json.dumps([row()], ensure_ascii=False).encode()
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, stream=httpx.ByteStream(body))
    result = runtime.capture(manifest=args["manifest"], profile=args["profile"],
                             source_id=consumer.SOURCE_ID, expected_registry_version=args["expected_registry_version"],
                             expected_digest=args["expected_digest"], output_dir="memory-capture", transport=httpx.MockTransport(handler))
    assert result["status"] == "capture_complete" and len(saved) == len(calls) == 1
    return body, result, args


def summarize(evidence, *, body=None, receipt=None, **overrides):
    original_body, original_receipt, args = evidence
    selected_body = original_body if body is None else body
    selected_receipt = copy.deepcopy(original_receipt) if receipt is None else receipt
    selected_receipt["body_sha256"] = hashlib.sha256(selected_body).hexdigest()
    selected_receipt["body_bytes"] = len(selected_body)
    return consumer.summarize_capture_bytes(encode_zip(selected_body, selected_receipt), **(args | overrides))


def test_snapshot_and_default_four_source_pins_are_independent():
    original = registry.load_manifest(expected_registry_version="r1-a1-c009-2026-09-12.1",
        expected_digest="sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b")
    assert len(original["sources"]) == 4
    new = registry.load_manifest(consumer.REGISTRY_PATH)
    assert len(new["sources"]) == 1
    assert registry.decide_policy(original, consumer.SOURCE_ID, "local_fetch", profile="free_public_local").allowed is False
    for purpose in ("local_fetch", "raw_store", "summarize"):
        assert registry.decide_policy(new, consumer.SOURCE_ID, purpose, profile="free_public_local").allowed
    assert registry.decide_policy(new, consumer.SOURCE_ID, "historical_pit", profile="free_public_local").decision == "unsupported"


def test_hand_calculated_quantities_trace_raw_rows_and_receipts(evidence):
    body, receipt, args = evidence
    result = consumer.summarize_capture_bytes(encode_zip(body, receipt), **args)
    selected = result["rows"][0]
    assert selected["date"] == "2026-10-02" and selected["source_date"] == "1151002"
    assert selected["row_ordinal"] == 1 and selected["unit"] == "shares"
    assert [(v["buy"], v["sell"], v["net"]) for v in selected["investors"].values()] == [(1000, 250, 750), (20, 50, -30), (0, 40, -40)]
    assert selected["total_net"] == 680
    assert selected["investors"]["foreign"]["label"] == "外資及陸資（不含外資自營商）"
    assert selected["investors"]["foreign"]["source_fields"]["sell"].startswith(" Foreign")
    assert result["provenance"]["body_sha256"] == hashlib.sha256(body).hexdigest()
    receipt_bytes = json.dumps(receipt, ensure_ascii=False).encode()
    assert result["provenance"]["receipt_sha256"] == hashlib.sha256(receipt_bytes).hexdigest()
    assert result["provenance"]["captured_at"] == receipt["captured_at"]
    assert result["attribution"]["owner"]["data_provider"] == "金融監督管理委員會證券期貨局"
    assert result["attribution"]["owner"]["dataset_name"] == "上櫃股票三大法人買賣明細資訊"
    assert result["attribution"]["owner"]["license_url"] == "https://data.gov.tw/license"
    assert result["attribution"]["owner"]["attribution_year"] == 2026
    assert result["summarize_decision"]["allowed"] is True
    assert set(result["summary_condition_receipts"]) == {"attribute_source", "preserve_source_integrity", "retain_traceability"}
    assert result["runtime_condition_receipts"]["bounded_requests"]["per_operation_timeout_seconds"] == 15.0
    assert result["runtime_condition_receipts"]["bounded_requests"]["cooperative_deadline_seconds"] == 30.0
    assert result["historical_pit"] == "unsupported" and result["session_windows"]["status"] == "unavailable"
    json.dumps(result)  # stdout remains standard JSON, including decimal receipt parsing.


def test_only_selected_quantities_are_validated_and_order_is_preserved(evidence):
    other = row("6488")
    other[FOREIGN_BUY] = "unvalidated"
    result = summarize(evidence, body=json.dumps([other, row()]).encode())
    assert result["candidate_count"] == 2 and result["rows"][0]["row_ordinal"] == 2
    assert result["validation_scope"] == "payload_dates_and_selected_row_quantities"
    result = summarize(evidence, body=json.dumps([row(), row("6488")]).encode(), symbols=["6488", "3105"])
    assert [(r["symbol"], r["row_ordinal"]) for r in result["rows"]] == [("6488", 2), ("3105", 1)]


@pytest.mark.parametrize("value", [None, "", " ", "1.0", "1e3", "1,000", " 1", "1 ", "+1", "01", "-0", "1股", True, 1, 1.0, "9223372036854775808"])
def test_noncanonical_selected_share_values_rejected(evidence, value):
    bad = row()
    bad[FOREIGN_BUY] = value
    with pytest.raises(consumer.InstitutionalCaptureError, match="share_quantity"):
        summarize(evidence, body=json.dumps([bad]).encode())


@pytest.mark.parametrize("key,value,reason", [(FOREIGN_BUY, "-1", "negative_gross"),
    (FOREIGN_NET, "751", "selected_net_mismatch:foreign"),
    ("SecuritiesInvestmentTrustCompanies-Difference", "0", "selected_net_mismatch:trust"),
    ("Dealers-Difference", "0", "selected_net_mismatch:dealer"),
    ("TotalDifference", "681", "selected_total_difference_mismatch"),
    ("CompanyName", "", "selected_company_name_missing")])
def test_selected_arithmetic_and_name_are_required(evidence, key, value, reason):
    bad = row()
    bad[key] = value
    with pytest.raises(consumer.InstitutionalCaptureError, match=reason):
        summarize(evidence, body=json.dumps([bad]).encode())


def test_missing_exact_foreign_sell_key_and_zero_are_distinct(evidence):
    bad = row()
    bad[FOREIGN_SELL.lstrip()] = bad.pop(FOREIGN_SELL)
    with pytest.raises(consumer.InstitutionalCaptureError):
        summarize(evidence, body=json.dumps([bad]).encode())
    zeros = row()
    for key in [FOREIGN_BUY, FOREIGN_SELL, FOREIGN_NET, "SecuritiesInvestmentTrustCompanies-TotalBuy",
                "SecuritiesInvestmentTrustCompanies-TotalSell", "SecuritiesInvestmentTrustCompanies-Difference",
                "Dealers-TotalBuy", "Dealers-TotalSell", "Dealers-Difference", "TotalDifference"]:
        zeros[key] = "0"
    assert summarize(evidence, body=json.dumps([zeros]).encode())["rows"][0]["total_net"] == 0


@pytest.mark.parametrize("body,reason", [(b"[]", "nonempty_row_list"), (b"{}", "nonempty_row_list"),
    (b"[null]", "row_object"), (json.dumps([row(), row()]).encode(), "selected_row_duplicate"),
    (json.dumps([row("6488")]).encode(), "selected_row_missing"),
    (json.dumps([row(), row("6488") | {"Date": "1151001"}]).encode(), "payload_date_mismatch"),
    (json.dumps([row() | {"Date": "20261002"}]).encode(), "invalid_market_date"),
    (json.dumps([row() | {"Date": "1150230"}]).encode(), "invalid_market_date"),
    (json.dumps([row() | {"Date": "1151003"}]).encode(), "payload_date_mismatch")])
def test_global_dates_and_selected_uniqueness_fail_closed(evidence, body, reason):
    with pytest.raises(consumer.InstitutionalCaptureError, match=reason):
        summarize(evidence, body=body)


@pytest.mark.parametrize("body", [b'[{"Date":"1151002","Date":"1151002"}]', b"[NaN]", b"[Infinity]", b"[1e999]", b"[1e999999999999999999999999999999999999]"])
def test_duplicate_keys_nonfinite_and_decimal_errors_are_controlled(evidence, body):
    with pytest.raises(consumer.InstitutionalCaptureError):
        summarize(evidence, body=body)


@pytest.mark.parametrize("key,value", [("source_id", "twse_t86"), ("endpoint", "https://example.com"), ("method", "POST"),
    ("source_version", "different"), ("registry_version", "different"), ("manifest_digest", "sha256:different"),
    ("profile", "different"), ("body_sha256", "bad"), ("body_bytes", True), ("request_count", True),
    ("status", "capture_failed"), ("http_status", True), ("http_status", 500), ("error_reason", "error"),
    ("rate_limit_verified", 0), ("historical_pit", "supported"), ("executed_purposes", ["local_fetch"]),
    ("captured_at", "2026-10-02T01:00:00"), ("captured_at", "2020-01-01T00:00:00+00:00")])
def test_receipt_pins_hashes_types_times_and_execution_are_rechecked(evidence, key, value):
    body, receipt, args = evidence
    bad = copy.deepcopy(receipt)
    bad[key] = value
    with pytest.raises(consumer.InstitutionalCaptureError):
        consumer.summarize_capture_bytes(encode_zip(body, bad), **args)


@pytest.mark.parametrize("section,key,value", [("bounded_requests", "max_requests", True),
    ("bounded_requests", "per_operation_timeout_seconds", 15), ("bounded_requests", "cooperative_deadline_seconds", True),
    ("respect_endpoint_limits", "retries", False), ("respect_endpoint_limits", "numeric_quota_verified", 0)])
def test_nested_conditions_reject_boolean_number_aliases(evidence, section, key, value):
    body, receipt, args = evidence
    bad = copy.deepcopy(receipt)
    bad["condition_receipts"][section][key] = value
    with pytest.raises(consumer.InstitutionalCaptureError, match="condition_receipts"):
        consumer.summarize_capture_bytes(encode_zip(body, bad), **args)


def test_attribution_and_policy_receipts_are_bound_to_manifest(evidence):
    body, receipt, args = evidence
    for part in ("attribution", "policy_decisions"):
        bad = copy.deepcopy(receipt)
        bad[part] = {}
        with pytest.raises(consumer.InstitutionalCaptureError):
            consumer.summarize_capture_bytes(encode_zip(body, bad), **args)
    for override in ({"expected_digest": "bad"}, {"expected_registry_version": "bad"}, {"profile": "bad"},
                     {"expected_date": None}, {"symbols": []}, {"symbols": ["3105", "3105"]}):
        with pytest.raises(ValueError):
            consumer.summarize_capture_bytes(encode_zip(body, receipt), **(args | override))


def test_summarize_is_separate_and_source_unit_is_checked(evidence, monkeypatch):
    body, receipt, args = evidence
    original = registry.load_manifest(consumer.REGISTRY_PATH)
    for mode in ("summarize", "unit"):
        changed = copy.deepcopy(original)
        if mode == "summarize":
            changed["sources"][0]["purposes"]["summarize"].update(status="unknown", reason="not documented")
        else:
            changed["sources"][0]["data_contract"]["unit"] = "lots"
        changed["content_digest"] = registry.manifest_digest(changed)
        monkeypatch.setattr(consumer, "load_manifest", lambda *a, **k: changed)
        with pytest.raises(consumer.InstitutionalCaptureError, match="purpose_not_admitted:summarize|source_unit_or_schema"):
            consumer.summarize_capture_bytes(encode_zip(body, receipt), **args)


def test_zip_members_encoding_bounds_and_receipt_json_are_checked(evidence, monkeypatch):
    body, receipt, args = evidence
    for encoded in (b"not zip", encode_zip(body, receipt, compression=zipfile.ZIP_DEFLATED),
                    encode_zip(body, receipt, names=[("../body.bin", body), ("receipt.json", b"{}")]),
                    encode_zip(body, receipt, names=[("body.bin", body), ("receipt.json", b'{"status":1,"status":1}')])):
        with pytest.raises(consumer.InstitutionalCaptureError):
            consumer.summarize_capture_bytes(encoded, **args)
    monkeypatch.setattr(consumer, "MAX_BODY_BYTES", 5)
    with pytest.raises(consumer.InstitutionalCaptureError, match="zip_member_size"):
        consumer.summarize_capture_bytes(encode_zip(body, receipt), **args)


def test_file_cli_and_import_are_read_only_and_app_independent(evidence, tmp_path):
    body, receipt, args = evidence
    existing_entries = set(tmp_path.iterdir())
    path = tmp_path / "capture.zip"
    path.write_bytes(encode_zip(body, receipt))  # File/CLI read and hash acceptance contract.
    before = path.read_bytes()
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", STOCK_DATA_DIR=str(tmp_path / "unexpected-data"),
               STOCK_DB_PATH=str(tmp_path / "unexpected.db"), STOCK_RAW_DIR=str(tmp_path / "unexpected-raw"))
    imported = subprocess.run([sys.executable, "-c", "import sys; import worker.tpex_institutional_capture; assert not any(x == 'app' or x.startswith('app.') or x in ('worker.sources','worker.pipeline','httpx') for x in sys.modules)"], env=env, capture_output=True, text=True)
    assert imported.returncode == 0, imported.stderr
    command = [sys.executable, "-m", "worker.tpex_institutional_capture", "summarize", "--capture-zip", str(path),
               "--manifest", str(args["manifest"]), "--profile", args["profile"],
               "--expected-registry-version", args["expected_registry_version"], "--expected-digest", args["expected_digest"],
               "--expected-date", "2026-10-02", "--symbol", "3105"]
    completed = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["rows"][0]["total_net"] == 680
    bad = command.copy()
    bad[bad.index("--expected-date") + 1] = "2026-10-01"
    rejected = subprocess.run(bad, env=env, capture_output=True, text=True, encoding="utf-8")
    assert rejected.returncode == 2 and json.loads(rejected.stdout)["status"] == "unavailable"
    missing_date = command.copy()
    index = missing_date.index("--expected-date")
    del missing_date[index:index + 2]
    rejected = subprocess.run(missing_date, env=env, capture_output=True, text=True)
    assert rejected.returncode == 2
    assert set(tmp_path.iterdir()) == existing_entries | {path} and path.read_bytes() == before
    assert not any((tmp_path / name).exists() for name in ("unexpected-data", "unexpected.db", "unexpected-raw"))


def test_file_change_during_summary_is_rejected(evidence, monkeypatch):
    body, receipt, args = evidence
    encoded = encode_zip(body, receipt)
    reads = iter([encoded, encoded + b"changed"])
    monkeypatch.setattr(consumer, "_stable_zip_read", lambda _: next(reads))
    with pytest.raises(consumer.InstitutionalCaptureError, match="capture_changed"):
        consumer.summarize_capture("unused.zip", **args)
