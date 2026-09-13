"""Local, unsigned STOCK_DAY_ALL capture normalization; no network or DB access.

Use load_stock_day_capture, then TwseAdapter(stock_day_capture=capture).
An existing successful collect run may skip its adapter: callers must explicitly
use collect(..., force=True). Other adapter endpoints remain legacy requests.
Capture time is observation time, never publication or first availability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import zipfile

from .source_registry import MIN_CONDITIONS, decide_policy, load_manifest
from .source_runtime import ENDPOINTS, MAX_BODY_BYTES, PROJECT_ROOT, TIMEOUT_SECONDS, DEADLINE_SECONDS

SOURCE_ID = "twse_stock_day_all"
ENDPOINT = ENDPOINTS[SOURCE_ID]
MAX_RECEIPT_BYTES = 256 * 1024
MAX_ZIP_BYTES = MAX_BODY_BYTES + MAX_RECEIPT_BYTES + 65536


class StockDayCaptureError(ValueError):
    pass


def _require(ok, reason):
    if not ok:
        raise StockDayCaptureError(reason)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def number(value):
        parsed = Decimal(value)
        _require(parsed.is_finite() and math.isfinite(float(parsed)), "nonfinite_json")
        return parsed
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=number,
                          parse_constant=lambda _: (_ for _ in ()).throw(StockDayCaptureError("nonfinite_json")))
    except (ValueError, UnicodeError) as exc:
        raise StockDayCaptureError("invalid_json:" + str(exc)) from exc


def _day(value):
    _require(isinstance(value, str), "invalid_market_date")
    text = value.strip()
    if re.fullmatch(r"\d{7,8}", text):
        year, month, day = int(text[:-4]), int(text[-4:-2]), int(text[-2:])
    elif re.fullmatch(r"\d{3,4}[/\-]\d{1,2}[/\-]\d{1,2}", text):
        year, month, day = map(int, re.split(r"[/\-]", text))
    else:
        raise StockDayCaptureError("invalid_market_date")
    try:
        return date(year + 1911 if year < 1000 else year, month, day)
    except ValueError as exc:
        raise StockDayCaptureError("invalid_market_date") from exc


def _rows(body):
    rows = _json(body)
    _require(isinstance(rows, list) and bool(rows), "nonempty_row_list_required")
    codes, days = set(), set()
    for row in rows:
        _require(isinstance(row, dict), "row_object_required")
        code = row.get("Code")
        _require(isinstance(code, str) and bool(code.strip()), "invalid_code")
        code = code.strip()
        _require(code not in codes, "duplicate_code")
        codes.add(code)
        days.add(_day(row.get("Date")))
    _require(len(days) == 1, "mixed_market_dates")
    return rows, days.pop()


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        _require(parsed.utcoffset() is not None, "naive_timestamp")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise StockDayCaptureError("invalid_timestamp") from exc


def _numeric(value, *, integer=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("missing_or_invalid")
    # A Python float has already lost its JSON lexical precision. The loader
    # supplies Decimal for JSON fractions; do not guess integer volume here.
    if integer and isinstance(value, float):
        raise ValueError("inexact_float_volume")
    text = str(value).strip()
    if not isinstance(value, Decimal) and not re.fullmatch(r"[+]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text):
        raise ValueError("missing_or_invalid")
    try:
        number = Decimal(text.replace(",", ""))
        if not number.is_finite() or number < 0 or (positive and number <= 0):
            raise ValueError("out_of_range")
        if integer:
            if number != number.to_integral_value() or number > 9223372036854775807:
                raise ValueError("noninteger_or_overflow")
            return int(number)
        converted = float(number)
        if not math.isfinite(converted) or (positive and converted <= 0):
            raise ValueError("out_of_range")
        return converted
    except InvalidOperation as exc:
        raise ValueError("invalid_number") from exc


@dataclass(frozen=True)
class StockDayCapture:
    """Validated local metadata, not a cryptographic proof of origin."""
    body: bytes
    receipt_bytes: bytes
    market_date: date
    captured_at: datetime
    sha256: str
    body_path: Path

    def select(self, symbols, end):
        from .sources import BarRecord, FetchedPayload

        _require(end == self.market_date, "capture_date_mismatch")
        receipt = _json(self.receipt_bytes)
        _require(isinstance(receipt, dict), "receipt_object_required")
        _require(self.captured_at.utcoffset() is not None and self.captured_at == _timestamp(receipt.get("captured_at")), "capture_timestamp_changed")
        _require(receipt.get("body_sha256") == self.sha256 and receipt.get("body_bytes") == len(self.body), "capture_metadata_changed")
        _require(hashlib.sha256(self.body).hexdigest() == self.sha256, "capture_body_changed")
        _require(self.body_path.read_bytes() == self.body, "materialized_body_changed")
        _require(self.body_path.with_name("receipt.json").read_bytes() == self.receipt_bytes, "materialized_receipt_changed")
        rows, day = _rows(self.body)
        _require(day == self.market_date, "capture_date_mismatch")
        by_code = {row["Code"].strip(): row for row in rows}
        bars, unavailable = [], []
        for symbol in dict.fromkeys(symbols):
            row = by_code.get(symbol)
            if row is None:
                unavailable.append({"symbol": symbol, "reason": "missing_symbol"})
                continue
            values = {}
            for field in ("OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"):
                try:
                    values[field] = _numeric(row.get(field), integer=field == "TradeVolume",
                                             positive=field.endswith("Price"))
                except ValueError:
                    unavailable.append({"symbol": symbol, "reason": "invalid_or_missing_" + field})
                    break
            else:
                o, h, l, c = (values[k] for k in ("OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice"))
                if not (l <= o <= h and l <= c <= h):
                    unavailable.append({"symbol": symbol, "reason": "inconsistent_ohlc_range"})
                    continue
                bars.append(BarRecord(symbol=symbol, trading_date=day, open=o, high=h, low=l, close=c,
                                      volume=values["TradeVolume"], turnover=values["TradeValue"],
                                      exchange="TWSE", source="twse", data_as_of=day.isoformat(),
                                      payload_sha256=self.sha256))
        raw = FetchedPayload("twse", ENDPOINT, rows, day.isoformat(), self.captured_at, self.body_path, self.sha256)
        return bars, raw, unavailable


def _publish(output, body, receipt):
    output = Path(output).expanduser().resolve()
    _require(output != PROJECT_ROOT and not output.is_relative_to(PROJECT_ROOT), "output_inside_project")
    _require(output.parent.is_dir(), "output_parent_missing")
    _require(not output.exists() or (output.is_dir() and not any(output.iterdir())), "output_not_empty")
    made_dir, owned = False, []
    try:
        if not output.exists():
            output.mkdir()
            made_dir = True
        lock = output / ".stock-day.lock"
        with lock.open("xb"):
            pass
        owned.append(lock)
        _require(set(output.iterdir()) == {lock}, "output_conflict")
        for name, value in (("body.bin", body), ("receipt.json", receipt)):
            path = output / name
            with path.open("xb") as handle:
                owned.append(path)
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
        lock.unlink()
        return output / "body.bin"
    except Exception:
        for path in reversed(owned):
            path.unlink(missing_ok=True)
        if made_dir:
            try:
                output.rmdir()
            except OSError:
                pass
        raise


def load_stock_day_capture(capture_zip, *, manifest, profile, expected_registry_version,
                          expected_digest, expected_market_date, output_dir):
    """Validate completely before exclusively materializing plain raw evidence.

    Only local_fetch/raw_store eligibility is rechecked. This performs no
    summarize or historical_pit execution. Invalid input creates no output.
    """
    _require(bool(manifest) and bool(profile) and bool(expected_registry_version) and bool(expected_digest), "explicit_pins_required")
    selected = load_manifest(manifest, expected_registry_version=expected_registry_version, expected_digest=expected_digest)
    source = next((s for s in selected["sources"] if s["source_id"] == SOURCE_ID), None)
    _require(source is not None and source["exact_url"] == ENDPOINT and source["method"] == "GET", "source_mismatch")
    decisions = {}
    for purpose in ("local_fetch", "raw_store"):
        decision = decide_policy(selected, SOURCE_ID, purpose, profile=profile, endpoint=ENDPOINT, method="GET")
        _require(decision.allowed and set(decision.conditions) == MIN_CONDITIONS[purpose], "policy_rejected:" + purpose)
        decisions[purpose] = decision.to_dict()
    with Path(capture_zip).open("rb") as handle:
        encoded = handle.read(MAX_ZIP_BYTES + 1)
    _require(len(encoded) <= MAX_ZIP_BYTES, "zip_size_limit")
    try:
        with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
            members = archive.infolist()
            _require(len(members) == 2 and {m.filename for m in members} == {"body.bin", "receipt.json"}, "zip_members")
            contents = {}
            for member in members:
                limit = MAX_BODY_BYTES if member.filename == "body.bin" else MAX_RECEIPT_BYTES
                _require(not member.flag_bits & 1 and member.compress_type == zipfile.ZIP_STORED, "zip_encoding")
                _require(member.file_size <= limit and member.compress_size == member.file_size, "zip_member_size")
                with archive.open(member) as stream:
                    contents[member.filename] = stream.read(limit + 1)
                _require(len(contents[member.filename]) == member.file_size, "zip_member_size")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise StockDayCaptureError("invalid_zip") from exc
    body, receipt_bytes = contents["body.bin"], contents["receipt.json"]
    receipt = _json(receipt_bytes)
    _require(isinstance(receipt, dict), "receipt_object_required")
    expected = {"schema_version": "source-capture/v1", "status": "capture_complete", "source_id": SOURCE_ID,
                "endpoint": ENDPOINT, "method": "GET", "source_version": source["source_version"],
                "profile": profile, "registry_version": selected["registry_version"], "manifest_digest": selected["content_digest"],
                "body_sha256": hashlib.sha256(body).hexdigest(), "body_bytes": len(body),
                "executed_purposes": ["local_fetch", "raw_store"], "policy_decisions": decisions,
                "historical_pit": "unsupported", "request_count": 1, "error_reason": None}
    for key, value in expected.items():
        _require(type(receipt.get(key)) is type(value) and receipt.get(key) == value, "receipt_mismatch:" + key)
    _require(type(receipt.get("http_status")) is int and 200 <= receipt["http_status"] < 300, "invalid_http_status")
    attribution = {"owner": source["owner"], "dataset_id": source["dataset_id"], "source_id": SOURCE_ID,
                   "source_url": ENDPOINT, "terms": source["access"]["documented_terms"], "evidence": source["evidence"],
                   "purpose_evidence": {p: source["purposes"][p]["evidence"] for p in decisions}}
    _require(receipt.get("attribution") == attribution, "attribution_mismatch")
    conditions = receipt.get("condition_receipts")
    _require(isinstance(conditions, dict) and set(conditions) == MIN_CONDITIONS["local_fetch"] | MIN_CONDITIONS["raw_store"], "condition_receipts_missing")
    _require(all(isinstance(v, dict) for v in conditions.values()), "condition_receipts_invalid")
    _require(conditions.get("attribute_source") == {"artifact": "receipt.json:attribution"}, "attribution_receipt")
    _require(conditions.get("preserve_source_integrity") == {"artifact": "body.bin", "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding"}, "integrity_receipt")
    _require(conditions.get("bounded_requests") == {"max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS,
        "cooperative_deadline_seconds": DEADLINE_SECONDS, "deadline_scope": "checked between streamed chunks; not a hard total deadline", "max_body_bytes": MAX_BODY_BYTES}, "bounds_receipt")
    limits = conditions.get("respect_endpoint_limits", {})
    _require(limits.get("strategy") == "single_get_stop_on_response" and all(limits.get(k) == 0 for k in ("retries", "redirects", "warmup_requests")), "limits_receipt")
    _require(source["access"]["rate_limit"]["status"] == "unknown"
             and receipt.get("rate_limit_evidence") == source["access"]["rate_limit"]
             and receipt.get("documented_numeric_rate_limit") == "unknown"
             and receipt.get("rate_limit_verified") is False
             and limits.get("numeric_quota_verified") is False, "rate_limit_receipt")
    started, captured = _timestamp(receipt.get("request_started_at")), _timestamp(receipt.get("captured_at"))
    _require(started <= captured, "nonmonotonic_timestamps")
    _, day = _rows(body)
    _require(type(expected_market_date) is date and day == expected_market_date, "capture_date_mismatch")
    path = _publish(output_dir, body, receipt_bytes)
    return StockDayCapture(body, receipt_bytes, day, captured, expected["body_sha256"], path)
