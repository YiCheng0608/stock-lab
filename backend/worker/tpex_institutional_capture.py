"""Read-only selected-day TPEx institutional summary, independent of the DB.

Run ``python -m worker.tpex_institutional_capture summarize --help``.
The capture ZIP is consumed in memory and is never extracted or rewritten.
Only the selected rows' quantities are validated. Date consistency is checked
across the payload; this does not establish market-wide data quality, trading
sessions, a five/twenty-session window, origin authentication, or historical PIT.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, DecimalException
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Sequence
import zipfile

from .source_registry import MIN_CONDITIONS, RegistryError, decide_policy, load_manifest
from .source_runtime import DEADLINE_SECONDS, ENDPOINTS, MAX_BODY_BYTES, TIMEOUT_SECONDS

SOURCE_ID = "tpex_3insti_daily_trading"
ENDPOINT = ENDPOINTS[SOURCE_ID]
REGISTRY_PATH = Path(__file__).with_name("tpex_institutional_registry.json")
SUMMARY_VERSION = "tpex-institutional-selected/v1"
MAX_RECEIPT_BYTES = 256 * 1024
MAX_ZIP_BYTES = MAX_BODY_BYTES + MAX_RECEIPT_BYTES + 65536
MAX_SHARES = 9223372036854775807
DATA_CONTRACT = {"unit": "shares", "date_encoding": "ROC_YYYMMDD", "selection": "exact_security_code"}
# The leading space in the foreign total-sell key is part of the official schema.
FIELDS = {
    "foreign": (
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy",
        " Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell",
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
    ),
    "trust": (
        "SecuritiesInvestmentTrustCompanies-TotalBuy",
        "SecuritiesInvestmentTrustCompanies-TotalSell",
        "SecuritiesInvestmentTrustCompanies-Difference",
    ),
    "dealer": ("Dealers-TotalBuy", "Dealers-TotalSell", "Dealers-Difference"),
}
LABELS = {"foreign": "外資及陸資（不含外資自營商）", "trust": "投信", "dealer": "自營商"}


class InstitutionalCaptureError(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise InstitutionalCaptureError(reason)


def _json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def nonfinite(_):
        raise InstitutionalCaptureError("nonfinite_json")
    def floating(value):
        # No float field is consumed as a share quantity. Still reject overflow
        # everywhere rather than letting an unselected row hide infinity.
        parsed = Decimal(value)
        _require(parsed.is_finite() and math.isfinite(float(parsed)), "nonfinite_json")
        return parsed
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=floating, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError, DecimalException, OverflowError) as exc:
        if isinstance(exc, InstitutionalCaptureError):
            raise
        raise InstitutionalCaptureError("invalid_json") from exc


def _same(actual: Any, expected: Any) -> bool:
    """Receipt equality is type-sensitive; booleans cannot stand in for numbers."""
    if type(expected) is float:
        return type(actual) is Decimal and actual.is_finite() and actual == Decimal(str(expected))
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_same(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_same(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _timestamp(value: Any) -> datetime:
    try:
        _require(isinstance(value, str), "invalid_timestamp")
        instant = datetime.fromisoformat(value)
        _require(instant.utcoffset() is not None, "naive_timestamp")
        return instant.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, InstitutionalCaptureError):
            raise
        raise InstitutionalCaptureError("invalid_timestamp") from exc


def _day(value: Any) -> date:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9]{7}", value) is not None, "invalid_market_date")
    try:
        _require(int(value[:3]) > 0, "invalid_market_date")
        return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:]))
    except ValueError as exc:
        raise InstitutionalCaptureError("invalid_market_date") from exc


def _shares(value: Any, *, gross: bool) -> int:
    # Only canonical signed integer strings from the exact Swagger contract.
    # Commas, units, whitespace, leading zeroes, exponents and decimals fail closed.
    _require(isinstance(value, str) and len(value) <= 20
             and re.fullmatch(r"(?:0|-?[1-9][0-9]*)", value) is not None, "invalid_share_quantity")
    value = int(value)
    _require(-MAX_SHARES <= value <= MAX_SHARES, "invalid_share_quantity")
    _require(not gross or value >= 0, "negative_gross_quantity")
    return value


def _selected_rows(body: bytes, symbols: Sequence[str], expected_date: date) -> tuple[list[dict], int]:
    _require(type(expected_date) is date, "explicit_expected_date_required")
    _require(not isinstance(symbols, (str, bytes)) and bool(symbols), "selected_symbols_required")
    _require(all(isinstance(s, str) and re.fullmatch(r"[0-9A-Z]{4,6}", s) is not None for s in symbols), "invalid_selected_symbol")
    _require(len(set(symbols)) == len(symbols), "duplicate_selected_symbol")
    rows = _json(body)
    _require(type(rows) is list and bool(rows), "nonempty_row_list_required")
    matches = {symbol: [] for symbol in symbols}
    for ordinal, row in enumerate(rows, 1):
        _require(type(row) is dict, "row_object_required")
        _require(_day(row.get("Date")) == expected_date, "payload_date_mismatch")
        code = row.get("SecuritiesCompanyCode")
        _require(isinstance(code, str) and bool(code) and code == code.strip(), "invalid_security_code")
        if code in matches:
            matches[code].append((ordinal, row))
    selected = []
    for symbol in symbols:
        _require(len(matches[symbol]) == 1, "selected_row_missing" if not matches[symbol] else "selected_row_duplicate")
        ordinal, row = matches[symbol][0]
        _require(isinstance(row.get("CompanyName"), str) and bool(row["CompanyName"].strip()), "selected_company_name_missing")
        investors = {}
        for investor, keys in FIELDS.items():
            buy, sell = (_shares(row.get(key), gross=True) for key in keys[:2])
            net = _shares(row.get(keys[2]), gross=False)
            _require(net == buy - sell, "selected_net_mismatch:" + investor)
            investors[investor] = {"label": LABELS[investor], "buy": buy, "sell": sell, "net": net,
                                   "source_fields": {"buy": keys[0], "sell": keys[1], "net": keys[2]}}
        total = _shares(row.get("TotalDifference"), gross=False)
        _require(total == sum(v["net"] for v in investors.values()), "selected_total_difference_mismatch")
        selected.append({"symbol": symbol, "company_name": row["CompanyName"], "date": expected_date.isoformat(),
                         "source_date": row["Date"], "exchange": "TPEx", "unit": "shares",
                         "row_ordinal": ordinal, "investors": investors, "total_net": total})
    return selected, len(rows)


def _zip_contents(encoded: bytes) -> tuple[bytes, bytes]:
    _require(type(encoded) is bytes and len(encoded) <= MAX_ZIP_BYTES, "zip_size_limit")
    try:
        with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
            members = archive.infolist()
            _require(len(members) == 2 and {m.filename for m in members} == {"body.bin", "receipt.json"}, "zip_members")
            contents = {}
            for member in members:
                limit = MAX_BODY_BYTES if member.filename == "body.bin" else MAX_RECEIPT_BYTES
                _require(not member.flag_bits & 1 and member.compress_type == zipfile.ZIP_STORED, "zip_encoding")
                _require(member.file_size <= limit and member.compress_size == member.file_size, "zip_member_size")
                with archive.open(member) as handle:
                    contents[member.filename] = handle.read(limit + 1)
                _require(len(contents[member.filename]) == member.file_size, "zip_member_size")
        return contents["body.bin"], contents["receipt.json"]
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError) as exc:
        raise InstitutionalCaptureError("invalid_zip") from exc


def summarize_capture_bytes(encoded: bytes, *, manifest: str | Path, profile: str,
                            expected_registry_version: str, expected_digest: str,
                            expected_date: date, symbols: Sequence[str]) -> dict:
    """Verify one explicitly pinned capture and return selected quantities only."""
    _require(bool(manifest) and bool(profile) and bool(expected_registry_version) and bool(expected_digest), "explicit_pins_and_profile_required")
    selected_manifest = load_manifest(manifest, expected_registry_version=expected_registry_version, expected_digest=expected_digest)
    source = next((s for s in selected_manifest["sources"] if s["source_id"] == SOURCE_ID), None)
    _require(source is not None and source["exact_url"] == ENDPOINT and source["method"] == "GET", "source_mismatch")
    _require(_same(source.get("data_contract"), DATA_CONTRACT), "source_unit_or_schema_mismatch")
    decisions = {}
    for purpose in ("local_fetch", "raw_store", "summarize"):
        decision = decide_policy(selected_manifest, SOURCE_ID, purpose, profile=profile, endpoint=ENDPOINT, method="GET")
        _require(decision.allowed and set(decision.conditions) == MIN_CONDITIONS[purpose], "purpose_not_admitted:" + purpose)
        decisions[purpose] = decision.to_dict()
    body, receipt_bytes = _zip_contents(encoded)
    receipt = _json(receipt_bytes)
    _require(type(receipt) is dict, "receipt_object_required")
    digest = hashlib.sha256(body).hexdigest()
    expected = {
        "schema_version": "source-capture/v1", "status": "capture_complete", "source_id": SOURCE_ID,
        "endpoint": ENDPOINT, "method": "GET", "source_version": source["source_version"],
        "profile": profile, "registry_version": expected_registry_version, "manifest_digest": expected_digest,
        "body_sha256": digest, "body_bytes": len(body), "executed_purposes": ["local_fetch", "raw_store"],
        "policy_decisions": {p: decisions[p] for p in ("local_fetch", "raw_store")},
        "historical_pit": "unsupported", "request_count": 1, "error_reason": None,
        "rate_limit_verified": False, "documented_numeric_rate_limit": "unknown",
        "rate_limit_scope": "one invocation; no cross-process enforcement", "rate_limit_evidence": source["access"]["rate_limit"],
    }
    for key, value in expected.items():
        _require(_same(receipt.get(key), value), "receipt_mismatch:" + key)
    _require(source["access"]["rate_limit"]["status"] == "unknown", "rate_limit_not_supported")
    _require(type(receipt.get("http_status")) is int and 200 <= receipt["http_status"] < 300, "invalid_http_status")
    attribution = {
        "owner": source["owner"], "dataset_id": source["dataset_id"], "source_id": SOURCE_ID,
        "source_url": ENDPOINT, "terms": source["access"]["documented_terms"], "evidence": source["evidence"],
        "purpose_evidence": {p: source["purposes"][p]["evidence"] for p in ("local_fetch", "raw_store")},
    }
    _require(_same(receipt.get("attribution"), attribution), "attribution_mismatch")
    conditions = {
        "attribute_source": {"artifact": "receipt.json:attribution"},
        "preserve_source_integrity": {"artifact": "body.bin", "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding"},
        "bounded_requests": {"max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS,
                             "cooperative_deadline_seconds": DEADLINE_SECONDS,
                             "deadline_scope": "checked between streamed chunks; not a hard total deadline", "max_body_bytes": MAX_BODY_BYTES},
        "respect_endpoint_limits": {"strategy": "single_get_stop_on_response", "retries": 0, "redirects": 0,
                                    "warmup_requests": 0, "numeric_quota_verified": False},
    }
    _require(_same(receipt.get("condition_receipts"), conditions), "condition_receipts_mismatch")
    _require(_timestamp(receipt.get("request_started_at")) <= _timestamp(receipt.get("captured_at")), "nonmonotonic_timestamps")
    rows, candidate_count = _selected_rows(body, symbols, expected_date)
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    provenance = {"source_id": SOURCE_ID, "source_version": source["source_version"], "endpoint": ENDPOINT,
                  "registry_version": expected_registry_version, "manifest_digest": expected_digest,
                  "body_sha256": digest, "receipt_sha256": receipt_digest, "captured_at": receipt["captured_at"],
                  "verification": "local_evidence_consistent"}
    return {
        "version": SUMMARY_VERSION, "status": "available", "as_of": expected_date.isoformat(),
        "scope": "M1-P2a: selected single-day TPEx institutional quantities", "unit": "shares",
        "validation_scope": "payload_dates_and_selected_row_quantities", "candidate_count": candidate_count,
        "selected_count": len(rows), "rows": rows, "provenance": provenance, "attribution": attribution,
        "runtime_condition_receipts": conditions,
        "summarize_decision": decisions["summarize"],
        "summary_condition_receipts": {
            "attribute_source": {"artifact": "summary:attribution", "purpose_evidence": source["purposes"]["summarize"]["evidence"]},
            "preserve_source_integrity": {"artifact": "capture.zip:body.bin", "body_sha256": digest},
            "retain_traceability": {"artifact": "summary:provenance_and_rows", "receipt_sha256": receipt_digest,
                                    "row_ordinals": [row["row_ordinal"] for row in rows]},
        },
        "historical_pit": "unsupported", "session_windows": {"status": "unavailable", "horizons": [5, 20],
            "reasons": ["trading_session_source_not_admitted", "multi_session_institutional_evidence_missing"]},
        "limitations": ["local_evidence_consistency_only", "selected_quantities_only", "complete_m1_not_delivered"],
    }


def _stable_zip_read(path: str | Path) -> bytes:
    target = Path(path).expanduser()
    _require(not target.is_symlink(), "capture_path_alias")
    before = target.stat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "capture_path_alias")
    _require(before.st_size <= MAX_ZIP_BYTES, "zip_size_limit")
    def identity(info):
        # Windows stat/fstat legacy ctime meanings can differ; these fields
        # identify the handle and keep its body/size/mtime stable separately.
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)
    with target.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        _require(identity(before) == identity(opened), "capture_changed")
        first = handle.read(MAX_ZIP_BYTES + 1)
        handle.seek(0)
        second = handle.read(MAX_ZIP_BYTES + 1)
        closed = os.fstat(handle.fileno())
    after = target.stat()
    _require(identity(before) == identity(closed) == identity(after) and first == second
             and len(first) == before.st_size and not target.is_symlink(), "capture_changed")
    return first


def summarize_capture(capture_zip: str | Path, **kwargs) -> dict:
    encoded = _stable_zip_read(capture_zip)
    summary = summarize_capture_bytes(encoded, **kwargs)
    _require(_stable_zip_read(capture_zip) == encoded, "capture_changed")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    child = sub.add_parser("summarize")
    child.add_argument("--capture-zip", required=True)
    child.add_argument("--manifest", required=True)
    child.add_argument("--profile", required=True)
    child.add_argument("--expected-registry-version", required=True)
    child.add_argument("--expected-digest", required=True)
    child.add_argument("--expected-date", required=True, help="Exact Gregorian YYYY-MM-DD; no latest-date inference")
    child.add_argument("--symbol", dest="symbols", action="append", required=True)
    args = vars(parser.parse_args(argv))
    args.pop("command")
    try:
        _require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", args["expected_date"]) is not None, "invalid_expected_date")
        args["expected_date"] = date.fromisoformat(args["expected_date"])
        result = summarize_capture(**args)
    except (ValueError, RegistryError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        reason = str(exc) if isinstance(exc, (InstitutionalCaptureError, RegistryError)) else "capture_evidence_invalid"
        result = {"version": SUMMARY_VERSION, "status": "unavailable", "reason": reason, "historical_pit": "unsupported"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "available" else 2


if __name__ == "__main__":
    sys.exit(_cli())
