"""Pure in-memory verifier cases; no pytest fixtures, DB, files, or network."""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from worker.analysis_capture import KIND_V2, KIND_V3
from worker.source_registry import MIN_CONDITIONS, MIN_REQUIRED_EVIDENCE, decide_policy, manifest_digest
from worker.source_runtime import DEADLINE_SECONDS, MAX_BODY_BYTES, TIMEOUT_SECONDS
from worker.stock_day_capture import ENDPOINT, SOURCE_ID
from worker.stock_day_evidence import (
    StockDayEvidenceError, _assert_binding, _checked_path, _stable_read, _verify_payload,
)


PROFILE = "free_public_local"
VERSION = "registry-test-v1"
SOURCE_VERSION = "stock-day-test-v1"
DAY = "2026-09-04"
VOLUME = 9007199254740993  # Binary64 rounds this, but the row volume must not.


def _file_stat(inode):
    return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1,
                           st_dev=9, st_ino=inode, st_size=4,
                           st_mtime_ns=100, st_ctime_ns=100)


class _MemoryFile(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.read_calls = 0

    def fileno(self):
        return 99

    def read(self, size=-1):
        self.read_calls += 1
        return super().read(size)


def _manifest():
    citation = {"url": "https://example.test/policy", "checked_at": "2026-09-01",
                "claim": "Synthetic policy evidence for an in-memory contract test."}
    known = lambda value: {"status": "known", "value": value}
    unknown = {"status": "unknown", "reason": "Not established by this fixture."}
    purposes = {}
    for purpose in ("local_fetch", "raw_store", "summarize", "historical_pit"):
        purposes[purpose] = {
            "status": "admitted" if purpose in ("local_fetch", "raw_store") else "unknown",
            "reason": "Synthetic fixture only.",
            "evidence": [citation] if purpose in ("local_fetch", "raw_store") else [],
            "required_evidence": sorted(MIN_REQUIRED_EVIDENCE[purpose]),
            "conditions": sorted(MIN_CONDITIONS[purpose]),
        }
    source = {
        "schema_version": "source-registry/v1", "registry_version": VERSION,
        "source_id": SOURCE_ID, "dataset_id": "test-dataset",
        "source_version": SOURCE_VERSION, "method": "GET", "exact_url": ENDPOINT,
        "owner": {"name": "Synthetic TWSE", "type": "official_exchange"},
        "source_type": "official_open_api", "evidence": [citation],
        "access": {
            "free_public": known(True), "auth": known(False),
            "documented_terms": known("synthetic local fixture"),
            "rate_limit": copy.deepcopy(unknown), "latency": copy.deepcopy(unknown),
        },
        "temporal": {key: copy.deepcopy(unknown) for key in (
            "update_cadence", "publication", "first_availability",
            "historical_coverage", "revision_policy",
        )},
        "retention": {"raw_store": known(True), "summarize": known(True)},
        "deprecation": {"status": "active"}, "enabled": known(True),
        "versioning": copy.deepcopy(unknown), "purposes": purposes,
    }
    manifest = {
        "schema_version": "source-registry/v1", "policy_version": "source-policy/v1",
        "registry_version": VERSION,
        "profiles": {PROFILE: {"version": "1", "policy_version": "source-policy/v1",
                              "source_versions": {SOURCE_ID: SOURCE_VERSION}}},
        "sources": [source],
    }
    manifest["content_digest"] = manifest_digest(manifest)
    return manifest


def _fixture():
    manifest = _manifest()
    row = {
        "Code": "1101", "Date": "1150904",
        "OpeningPrice": "200", "HighestPrice": "205", "LowestPrice": "198",
        "ClosingPrice": "203", "TradeVolume": "9,007,199,254,740,993",
        "TradeValue": "250,000",
    }
    rows = [row]
    body = json.dumps(rows, separators=(",", ":")).encode("utf-8")
    body_sha = hashlib.sha256(body).hexdigest()
    source = manifest["sources"][0]
    decisions = {purpose: decide_policy(
        manifest, SOURCE_ID, purpose, profile=PROFILE, endpoint=ENDPOINT, method="GET",
    ).to_dict() for purpose in ("local_fetch", "raw_store")}
    receipt = {
        "schema_version": "source-capture/v1", "status": "capture_complete",
        "source_id": SOURCE_ID, "endpoint": ENDPOINT, "method": "GET",
        "source_version": SOURCE_VERSION, "profile": PROFILE,
        "registry_version": VERSION, "manifest_digest": manifest["content_digest"],
        "body_sha256": body_sha, "body_bytes": len(body),
        "executed_purposes": ["local_fetch", "raw_store"],
        "policy_decisions": decisions, "historical_pit": "unsupported",
        "request_count": 1, "error_reason": None, "http_status": 200,
        "rate_limit_verified": False,
        "rate_limit_scope": "one invocation; no cross-process enforcement",
        "documented_numeric_rate_limit": "unknown",
        "rate_limit_evidence": source["access"]["rate_limit"],
        "request_started_at": "2026-09-05T00:00:00+00:00",
        "captured_at": "2026-09-05T00:00:01+00:00",
        "attribution": {
            "owner": source["owner"], "dataset_id": source["dataset_id"],
            "source_id": SOURCE_ID, "source_url": ENDPOINT,
            "terms": source["access"]["documented_terms"],
            "evidence": source["evidence"],
            "purpose_evidence": {p: source["purposes"][p]["evidence"] for p in decisions},
        },
        "condition_receipts": {
            "bounded_requests": {
                "max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS,
                "cooperative_deadline_seconds": DEADLINE_SECONDS,
                "deadline_scope": "checked between streamed chunks; not a hard total deadline",
                "max_body_bytes": MAX_BODY_BYTES,
            },
            "respect_endpoint_limits": {
                "strategy": "single_get_stop_on_response", "retries": 0,
                "redirects": 0, "warmup_requests": 0,
                "numeric_quota_verified": False,
            },
            "attribute_source": {"artifact": "receipt.json:attribution"},
            "preserve_source_integrity": {
                "artifact": "body.bin",
                "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding",
            },
        },
    }
    selected = {
        "schema": "worker-selected-bar-provenance/v1",
        "coverage": ["close", "volume"],
        "bar": {
            "id": 10, "instrument_id": 7, "trading_date": DAY,
            "close": 203.0, "volume": VOLUME, "source": "twse",
            "raw_payload_id": 20, "data_as_of": None, "collected_at": None,
        },
        "raw_payload": {
            "id": 20, "source": "twse", "endpoint": ENDPOINT,
            "payload_path": "C:/named-evidence/body.bin", "sha256": body_sha,
            "ingestion_run_id": 30, "data_as_of": None, "collected_at": None,
        },
        "raw_status": "linked_metadata", "raw_reason": None,
        "raw_bytes_verification": "bytes_unverified",
    }
    call = {
        "evaluator": "breakout_v1", "selected_strategy": {"name": "breakout_v1"},
        "subject": {"instrument_id": 7, "market": "TW", "exchange": "TWSE", "symbol": "1101"},
        "observed_market_date": DAY,
        "arguments": {"close": 203.0, "volume": float(VOLUME)},
        "input_provenance": selected,
    }
    return {"manifest": manifest, "rows": rows, "body": body,
            "receipt": receipt, "call": call, "kind": KIND_V2}


def _refresh(fixture, *, body=False, receipt=True, raw=True):
    if body:
        fixture["body"] = json.dumps(fixture["rows"], separators=(",", ":")).encode("utf-8")
        body_sha = hashlib.sha256(fixture["body"]).hexdigest()
        fixture["receipt"]["body_sha256"] = body_sha
        fixture["receipt"]["body_bytes"] = len(fixture["body"])
        if raw:
            selected = fixture["call"]["input_provenance"]
            if fixture["kind"] == KIND_V3:
                selected = selected["selected_bar"]
            selected["raw_payload"]["sha256"] = body_sha
    if receipt:
        fixture["receipt_bytes"] = json.dumps(
            fixture["receipt"], sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        fixture["receipt_pin"] = hashlib.sha256(fixture["receipt_bytes"]).hexdigest()


def _verify(fixture, **changes):
    if "receipt_bytes" not in fixture:
        _refresh(fixture)
    arguments = {
        "call": fixture["call"], "capture_kind": fixture["kind"],
        "body": fixture["body"], "receipt_bytes": fixture["receipt_bytes"],
        "manifest": fixture["manifest"],
        "expected_receipt_sha256": fixture["receipt_pin"],
        "expected_registry_version": VERSION,
        "expected_manifest_digest": fixture["manifest"]["content_digest"],
        "expected_profile": PROFILE,
    }
    arguments.update(changes)
    return _verify_payload(**arguments)


class SelectedBarEvidenceMemoryTests(unittest.TestCase):
    def assert_reason(self, fixture, code, **changes):
        with self.assertRaises(StockDayEvidenceError) as failure:
            _verify(fixture, **changes)
        self.assertEqual(failure.exception.code, code)

    def test_v2_exact_integer_and_detached_local_verdict(self):
        fixture = _fixture()
        before = copy.deepcopy(fixture["call"])
        result = _verify(fixture)
        self.assertEqual(result["verdict"], "local_evidence_consistent")
        self.assertEqual(result["schema_version"], "stock-day-selected-bar-evidence/v1")
        self.assertEqual(result["volume"], VOLUME)
        self.assertEqual(result["close"], 203.0)
        self.assertNotIn("prior_volumes", result)
        self.assertNotIn("raw_bytes_verification", result)
        self.assertEqual(fixture["call"], before)
        self.assertEqual(fixture["call"]["input_provenance"]["raw_bytes_verification"],
                         "bytes_unverified")

    def test_v3_checks_only_selected_bar(self):
        fixture = _fixture()
        fixture["kind"] = KIND_V3
        fixture["call"]["input_provenance"] = {
            "selected_bar": fixture["call"]["input_provenance"],
            "prior_volumes": {"outside_this_verdict": True},
        }
        result = _verify(fixture)
        self.assertEqual(result["capture_kind"], KIND_V3)
        self.assertEqual(result["scope"], "selected_bar_only")
        self.assertNotIn("prior_volumes", result)

    def test_receipt_digest_and_pins(self):
        fixture = _fixture()
        _refresh(fixture)
        self.assert_reason(fixture, "receipt_hash_mismatch",
                           expected_receipt_sha256="0" * 64)
        fixture["receipt"]["source_version"] = "another-version"
        _refresh(fixture)
        self.assert_reason(fixture, "receipt_pin_mismatch")
        fixture = _fixture()
        fixture["receipt"]["policy_decisions"]["local_fetch"]["allowed"] = 1
        self.assert_reason(fixture, "receipt_pin_mismatch")
        fixture = _fixture()
        fixture["receipt"]["condition_receipts"]["respect_endpoint_limits"]["retries"] = False
        self.assert_reason(fixture, "receipt_conditions_mismatch")

    def test_registry_external_pins_and_source_identity(self):
        fixture = _fixture()
        self.assert_reason(fixture, "registry_pins_required",
                           expected_manifest_digest="")
        self.assert_reason(fixture, "registry_pin_mismatch",
                           expected_registry_version="another-version")
        fixture["manifest"]["sources"][0]["source_version"] = "another-version"
        self.assert_reason(fixture, "registry_pin_mismatch")
        fixture = _fixture()
        fixture["call"]["input_provenance"]["raw_payload"]["endpoint"] = "other-endpoint"
        self.assert_reason(fixture, "source_identity_mismatch")

    def test_raw_fk_and_declared_body_digest_required(self):
        fixture = _fixture()
        selected = fixture["call"]["input_provenance"]
        selected["bar"]["raw_payload_id"] = None
        selected["raw_payload"] = None
        selected["raw_status"] = "unknown"
        selected["raw_reason"] = "raw_payload_id_missing"
        self.assert_reason(fixture, "raw_fk_missing")
        fixture = _fixture()
        fixture["call"]["input_provenance"]["raw_payload"]["sha256"] = None
        self.assert_reason(fixture, "raw_digest_missing")
        fixture = _fixture()
        fixture["rows"][0]["TradeValue"] = "251,000"
        _refresh(fixture, body=True, raw=False)
        self.assert_reason(fixture, "body_hash_mismatch")

    def test_full_row_uniqueness_date_and_selected_only_numeric(self):
        fixture = _fixture()
        fixture["rows"].append(copy.deepcopy(fixture["rows"][0]))
        _refresh(fixture, body=True)
        self.assert_reason(fixture, "body_invalid")
        fixture = _fixture()
        fixture["rows"][0]["Date"] = "1150905"
        _refresh(fixture, body=True)
        self.assert_reason(fixture, "market_date_mismatch")
        fixture = _fixture()
        fixture["rows"][0]["TradeVolume"] = "1.5"
        _refresh(fixture, body=True)
        self.assert_reason(fixture, "selected_row_invalid")
        fixture = _fixture()
        other = copy.deepcopy(fixture["rows"][0])
        other["Code"] = "BAD"
        other["ClosingPrice"] = ""
        fixture["rows"].append(other)
        _refresh(fixture, body=True)
        self.assertEqual(_verify(fixture)["volume"], VOLUME)

    def test_exact_volume_survives_binary64_collision(self):
        fixture = _fixture()
        fixture["rows"][0]["TradeVolume"] = str(VOLUME - 1)
        self.assertEqual(float(VOLUME), float(VOLUME - 1))
        _refresh(fixture, body=True)
        self.assert_reason(fixture, "selected_bar_value_mismatch")
        fixture = _fixture()
        fixture["rows"][0]["ClosingPrice"] = "204"
        _refresh(fixture, body=True)
        self.assert_reason(fixture, "selected_bar_value_mismatch")

    def test_unsupported_kind_and_unselected_evaluator(self):
        fixture = _fixture()
        self.assert_reason(fixture, "unsupported_capture_kind", capture_kind="worker-analysis-capture/v1")
        fixture["call"]["evaluator"] = "pullback_v1"
        self.assert_reason(fixture, "evaluator_not_selected_strategy")

    def test_concrete_path_and_original_identity_are_kept(self):
        path = (Path("C:/named-evidence/body.bin") if os.name == "nt"
                else Path("/named-evidence/body.bin"))
        old, replacement = _file_stat(41), _file_stat(42)
        state = {"stat": old}
        with (patch.object(Path, "is_symlink", lambda self: False),
              patch.object(Path, "is_junction", lambda self: False, create=True),
              patch.object(Path, "resolve", lambda self, strict=False: self),
              patch.object(Path, "stat", lambda self: state["stat"]),
              patch.object(Path, "open", lambda self, mode: _MemoryFile(b"same")),
              patch("worker.stock_day_evidence.os.fstat", return_value=old)):
            bound = _checked_path(path, "body", name="body.bin")
            self.assertEqual(bound.path, path)
            self.assertEqual(_stable_read(bound, 10), b"same")
            state["stat"] = replacement  # Same content and metadata, different inode.
            with self.assertRaises(StockDayEvidenceError) as failure:
                _stable_read(bound, 10)
            self.assertEqual(failure.exception.code, "body_changed")

    def test_alias_replacement_is_rejected_with_original_binding(self):
        path = (Path("C:/named-evidence/body.bin") if os.name == "nt"
                else Path("/named-evidence/body.bin"))
        old = _file_stat(41)
        with (patch.object(Path, "is_symlink", lambda self: False),
              patch.object(Path, "is_junction", lambda self: False, create=True),
              patch.object(Path, "resolve", lambda self, strict=False: self),
              patch.object(Path, "stat", return_value=old)):
            bound = _checked_path(path, "body", name="body.bin")
            with patch.object(Path, "is_symlink", lambda self: self == path):
                with self.assertRaises(StockDayEvidenceError) as failure:
                    _assert_binding(bound)
                self.assertEqual(failure.exception.code, "body_path_alias")
            with patch.object(Path, "is_junction", lambda self: self == path, create=True):
                with self.assertRaises(StockDayEvidenceError) as failure:
                    _assert_binding(bound)
                self.assertEqual(failure.exception.code, "body_path_alias")

    def test_replaced_open_handle_is_rejected_before_read(self):
        path = (Path("C:/named-evidence/body.bin") if os.name == "nt"
                else Path("/named-evidence/body.bin"))
        original, replacement = _file_stat(41), _file_stat(42)
        handle = _MemoryFile(b"same")
        with (patch.object(Path, "is_symlink", lambda self: False),
              patch.object(Path, "is_junction", lambda self: False, create=True),
              patch.object(Path, "resolve", lambda self, strict=False: self),
              patch.object(Path, "stat", return_value=original),
              patch.object(Path, "open", return_value=handle),
              patch("worker.stock_day_evidence.os.fstat", return_value=replacement)):
            bound = _checked_path(path, "body", name="body.bin")
            with self.assertRaises(StockDayEvidenceError) as failure:
                _stable_read(bound, 10)
            self.assertEqual(failure.exception.code, "body_changed")
            self.assertEqual(handle.read_calls, 0)

    def test_deep_receipt_and_body_json_have_stable_reasons(self):
        deep = b"[" * 1500 + b"0" + b"]" * 1500
        fixture = _fixture()
        fixture["receipt_bytes"] = deep
        fixture["receipt_pin"] = hashlib.sha256(deep).hexdigest()
        self.assert_reason(fixture, "receipt_invalid")
        fixture = _fixture()
        fixture["body"] = deep
        body_sha = hashlib.sha256(deep).hexdigest()
        fixture["receipt"]["body_sha256"] = body_sha
        fixture["receipt"]["body_bytes"] = len(deep)
        fixture["call"]["input_provenance"]["raw_payload"]["sha256"] = body_sha
        self.assert_reason(fixture, "body_invalid")


if __name__ == "__main__":
    unittest.main()
