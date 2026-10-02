"""Selected TWT48U events observed now, independent of application/DB imports.

``python -m worker.twse_action_capture live-summarize --help`` performs one
explicitly admitted GET, retains the original bytes only in memory and prints
selected events. Date is the effective date, never publication/availability.
There is no historical as-of filter, price adjustment or impact inference.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Sequence

from .source_registry import MIN_CONDITIONS, RegistryError, decide_policy, load_manifest
from .source_runtime import (DEADLINE_SECONDS, ENDPOINTS, MAX_BODY_BYTES,
                             TIMEOUT_SECONDS, capture_memory)

SOURCE_ID = "twse_twt48u_all"
ENDPOINT = ENDPOINTS[SOURCE_ID]
SUMMARY_VERSION = "twse-action-selected/v1"
MAX_RECEIPT_BYTES = 256 * 1024
KINDS = {"息": ("ex_dividend", "除息"), "權": ("ex_right", "除權"),
         "權息": ("ex_right_and_dividend", "除權息")}


class ActionCaptureError(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ActionCaptureError(reason)


def _json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def floating(value):
        parsed = float(value)
        _require(math.isfinite(parsed), "nonfinite_json")
        return parsed
    def nonfinite(_):
        raise ActionCaptureError("nonfinite_json")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=floating,
                          parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, ActionCaptureError):
            raise
        raise ActionCaptureError("invalid_json") from exc


def _same(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_same(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_same(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _timestamp(value: Any) -> datetime:
    try:
        _require(isinstance(value, str), "invalid_capture_timestamp")
        instant = datetime.fromisoformat(value)
        _require(instant.utcoffset() is not None and instant.utcoffset().total_seconds() == 0,
                 "capture_timestamp_must_be_utc")
        return instant.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ActionCaptureError):
            raise
        raise ActionCaptureError("invalid_capture_timestamp") from exc


def _day(value: Any) -> date:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9]{7}", value) is not None,
             "invalid_effective_date")
    try:
        _require(int(value[:3]) > 0, "invalid_effective_date")
        return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:]))
    except ValueError as exc:
        raise ActionCaptureError("invalid_effective_date") from exc


def _symbols(symbols: Sequence[str]) -> list[str]:
    _require(not isinstance(symbols, (str, bytes)) and isinstance(symbols, Sequence)
             and bool(symbols), "selected_symbols_required")
    _require(all(isinstance(s, str) and re.fullmatch(r"[0-9A-Z]{4,6}", s) is not None for s in symbols),
             "invalid_selected_symbol")
    _require(len(set(symbols)) == len(symbols), "duplicate_selected_symbol")
    return list(symbols)


def _admission(*, manifest: str | Path, profile: str, expected_registry_version: str,
               expected_digest: str) -> tuple[dict, dict]:
    _require(bool(manifest) and bool(profile) and bool(expected_registry_version)
             and bool(expected_digest), "explicit_pins_and_profile_required")
    selected = load_manifest(manifest, expected_registry_version=expected_registry_version,
                             expected_digest=expected_digest)
    source = next((s for s in selected["sources"] if s["source_id"] == SOURCE_ID), None)
    _require(source is not None, "source_missing")
    _require(source["exact_url"] == ENDPOINT and source["method"] == "GET", "endpoint_or_method_mismatch")
    decisions = {}
    for purpose in ("local_fetch", "raw_store", "summarize"):
        decision = decide_policy(selected, SOURCE_ID, purpose, profile=profile,
                                 endpoint=ENDPOINT, method="GET")
        _require(decision.allowed and set(decision.conditions) == MIN_CONDITIONS[purpose],
                 "purpose_not_admitted:" + purpose)
        decisions[purpose] = decision.to_dict()
    _require(source["access"]["rate_limit"]["status"] == "unknown", "rate_limit_not_supported")
    return source, decisions


def summarize_memory_capture(body: bytes, receipt_bytes: bytes, *, manifest: str | Path,
                             profile: str, expected_registry_version: str,
                             expected_digest: str, symbols: Sequence[str]) -> dict:
    """Verify the memory receipt and exact selected effective-date events.

    Unsigned receipt/hash consistency is not origin authentication. All payload
    codes/dates are validated; classifications are validated only for selections.
    Missing selections fail closed and never mean a verified absence of events.
    """
    requested = _symbols(symbols)
    source, decisions = _admission(manifest=manifest, profile=profile,
                                   expected_registry_version=expected_registry_version,
                                   expected_digest=expected_digest)
    _require(type(body) is bytes and len(body) <= MAX_BODY_BYTES, "body_size_limit")
    _require(type(receipt_bytes) is bytes and len(receipt_bytes) <= MAX_RECEIPT_BYTES,
             "receipt_size_limit")
    receipt = _json(receipt_bytes)
    _require(type(receipt) is dict, "receipt_object_required")
    _require("artifact" not in receipt, "memory_receipt_has_artifact")
    digest = hashlib.sha256(body).hexdigest()
    expected = {
        "schema_version": "source-memory-capture/v1", "storage": "memory_only",
        "status": "capture_complete", "source_id": SOURCE_ID, "endpoint": ENDPOINT,
        "method": "GET", "source_version": source["source_version"], "profile": profile,
        "registry_version": expected_registry_version, "manifest_digest": expected_digest,
        "body_sha256": digest, "body_bytes": len(body), "executed_purposes": ["local_fetch", "raw_store"],
        "policy_decisions": {p: decisions[p] for p in ("local_fetch", "raw_store")},
        "historical_pit": "unsupported", "request_count": 1, "error_reason": None,
        "rate_limit_verified": False, "documented_numeric_rate_limit": "unknown",
        "rate_limit_scope": "one invocation; no cross-process enforcement",
        "rate_limit_evidence": source["access"]["rate_limit"],
    }
    for key, value in expected.items():
        _require(_same(receipt.get(key), value), "receipt_mismatch:" + key)
    _require(type(receipt.get("http_status")) is int and 200 <= receipt["http_status"] < 300,
             "invalid_http_status")
    attribution = {"owner": source["owner"], "dataset_id": source["dataset_id"],
                   "source_id": SOURCE_ID, "source_url": ENDPOINT,
                   "terms": source["access"]["documented_terms"], "evidence": source["evidence"],
                   "purpose_evidence": {p: source["purposes"][p]["evidence"] for p in ("local_fetch", "raw_store")}}
    _require(_same(receipt.get("attribution"), attribution), "attribution_mismatch")
    conditions = {
        "attribute_source": {"artifact": "memory:receipt.attribution"},
        "preserve_source_integrity": {"artifact": "memory:body", "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding"},
        "bounded_requests": {"max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS,
                             "cooperative_deadline_seconds": DEADLINE_SECONDS,
                             "deadline_scope": "checked between streamed chunks; not a hard total deadline",
                             "max_body_bytes": MAX_BODY_BYTES},
        "respect_endpoint_limits": {"strategy": "single_get_stop_on_response", "retries": 0,
                                    "redirects": 0, "warmup_requests": 0, "numeric_quota_verified": False},
    }
    _require(_same(receipt.get("condition_receipts"), conditions), "condition_receipts_mismatch")
    _require(_timestamp(receipt.get("request_started_at")) <= _timestamp(receipt.get("captured_at")),
             "nonmonotonic_capture_timestamps")
    payload = _json(body)
    _require(type(payload) is list and bool(payload), "nonempty_row_list_required")
    matches = {symbol: [] for symbol in requested}
    identities = set()
    for ordinal, row in enumerate(payload, 1):
        _require(type(row) is dict, "row_object_required")
        code = row.get("Code")
        _require(isinstance(code, str) and re.fullmatch(r"[0-9A-Z]{4,6}", code) is not None,
                 "invalid_security_code")
        effective = _day(row.get("Date"))
        if code not in matches:
            continue
        _require(isinstance(row.get("Name"), str) and bool(row["Name"].strip()), "selected_name_missing")
        value = row.get("Exdividend")
        _require(isinstance(value, str) and value in KINDS, "selected_event_class_unknown")
        identity = (code, row["Date"], value)
        _require(identity not in identities, "selected_event_duplicate")
        identities.add(identity)
        kind, label = KINDS[value]
        matches[code].append({"exchange": "TWSE", "symbol": code, "company_name": row["Name"],
                              "event_date": effective.isoformat(), "source_date": row["Date"],
                              "event_date_role": "effective_date", "event_date_precision": "date",
                              "kind": kind, "label": label, "row_ordinal": ordinal, "source_row": row,
                              "published_at": None, "first_available_at": None,
                              "revision_available_at": None, "availability": "unknown"})
    for symbol, rows in matches.items():
        _require(bool(rows), "selected_symbol_missing:" + symbol)
    rows = [row for symbol in requested for row in matches[symbol]]
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    provenance = {"source_id": SOURCE_ID, "source_version": source["source_version"], "endpoint": ENDPOINT,
                  "registry_version": expected_registry_version, "manifest_digest": expected_digest,
                  "body_sha256": digest, "receipt_sha256": receipt_digest,
                  "captured_at": receipt["captured_at"], "request_started_at": receipt["request_started_at"],
                  "storage": "memory_only", "verification": "local_evidence_consistent"}
    return {"version": SUMMARY_VERSION, "status": "available", "scope": "M1-P3a: selected observed TWT48U effective-date events",
            "validation_scope": "payload_codes_dates_and_selected_identity_classification", "source_url_kind": "feed",
            "candidate_count": len(payload), "selected_count": len(rows), "selected_symbols": requested,
            "rows": rows, "provenance": provenance, "attribution": attribution,
            "runtime_condition_receipts": conditions, "summarize_decision": decisions["summarize"],
            "summary_condition_receipts": {
                "attribute_source": {"artifact": "summary:attribution", "purpose_evidence": source["purposes"]["summarize"]["evidence"]},
                "preserve_source_integrity": {"artifact": "memory:body", "body_sha256": digest},
                "retain_traceability": {"artifact": "summary:provenance_and_rows", "receipt_sha256": receipt_digest,
                                        "row_ordinals": [row["row_ordinal"] for row in rows]}},
            "historical_pit": "unsupported", "published_time": "unknown", "first_availability": "unknown",
            "revision_history": "unknown", "durable_capture": False,
            "limitations": ["local_evidence_consistency_only", "selected_events_only", "not_complete_history",
                            "future_effective_dates_retained", "not_historical_as_of", "product_wiring_pending"]}


def live_summarize(*, manifest: str | Path, profile: str, expected_registry_version: str,
                   expected_digest: str, symbols: Sequence[str], transport: Any = None) -> dict:
    """Validate selection and summary eligibility before one bounded GET."""
    _symbols(symbols)
    selectors = dict(manifest=manifest, profile=profile, expected_registry_version=expected_registry_version,
                     expected_digest=expected_digest)
    _admission(**selectors)
    body, receipt_bytes = capture_memory(**selectors, source_id=SOURCE_ID, transport=transport)
    receipt = _json(receipt_bytes)
    if body is None:
        return {"version": SUMMARY_VERSION, "status": "unavailable", "reason": receipt["error_reason"],
                "capture_receipt": receipt, "historical_pit": "unsupported"}
    return summarize_memory_capture(body, receipt_bytes, **selectors, symbols=symbols)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    child = sub.add_parser("live-summarize", help="one GET; memory only; selected rows to stdout")
    child.add_argument("--manifest", required=True)
    child.add_argument("--profile", required=True)
    child.add_argument("--source", required=True, choices=[SOURCE_ID])
    child.add_argument("--expected-registry-version", required=True)
    child.add_argument("--expected-digest", required=True)
    child.add_argument("--symbol", dest="symbols", action="append", required=True)
    args = vars(parser.parse_args(argv))
    args.pop("command")
    args.pop("source")
    try:
        result = live_summarize(**args)
    except (ValueError, RegistryError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        result = {"version": SUMMARY_VERSION, "status": "unavailable", "historical_pit": "unsupported",
                  "reason": str(exc) if isinstance(exc, (ActionCaptureError, RegistryError)) else "capture_evidence_invalid"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "available" else 2


if __name__ == "__main__":
    sys.exit(_cli())
