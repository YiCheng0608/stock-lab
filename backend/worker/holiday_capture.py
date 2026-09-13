"""Local, unsigned holidaySchedule capture normalization; no network or DB access.

Use load_holiday_capture, then TwseAdapter(holiday_capture=capture).
An existing successful collect run may skip its adapter: callers must explicitly
use collect(..., force=True). Other adapter endpoints remain legacy requests.
Capture time is observation time, never publication or first availability.
Only multi-day fetch_bars consumes this calendar. Missing dates do not establish
open sessions, annual completeness, or historical point-in-time availability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
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

SOURCE_ID = "twse_holiday_schedule"
ENDPOINT = ENDPOINTS[SOURCE_ID]
MAX_RECEIPT_BYTES = 256 * 1024
MAX_ZIP_BYTES = MAX_BODY_BYTES + MAX_RECEIPT_BYTES + 65536


class HolidayCaptureError(ValueError):
    pass


def _require(ok, reason):
    if not ok:
        raise HolidayCaptureError(reason)


def _same(actual, expected):
    """JSON equality without bool/int aliasing in condition receipts."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(_same(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_same(a, b) for a, b in zip(actual, expected))
    if type(expected) in (int, float):
        return type(actual) in (int, float, Decimal) and actual == expected
    return type(actual) is type(expected) and actual == expected


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
                          parse_constant=lambda _: (_ for _ in ()).throw(HolidayCaptureError("nonfinite_json")))
    except (ValueError, UnicodeError) as exc:
        raise HolidayCaptureError("invalid_json:" + str(exc)) from exc


def _day(value):
    _require(isinstance(value, str), "invalid_market_date")
    text = value.strip()
    if re.fullmatch(r"\d{7,8}", text):
        year, month, day = int(text[:-4]), int(text[-4:-2]), int(text[-2:])
    elif re.fullmatch(r"\d{3,4}[/\-]\d{1,2}[/\-]\d{1,2}", text):
        year, month, day = map(int, re.split(r"[/\-]", text))
    else:
        raise HolidayCaptureError("invalid_market_date")
    try:
        return date(year + 1911 if year < 1000 else year, month, day)
    except ValueError as exc:
        raise HolidayCaptureError("invalid_market_date") from exc


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        _require(parsed.utcoffset() is not None, "naive_timestamp")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise HolidayCaptureError("invalid_timestamp") from exc


WEEKDAYS = "一二三四五六日"
# Deliberately finite names and complete sentences observed in the annual feed.
# Unknown wording remains unknown; this is not a natural-language interpreter.
HOLIDAY_NAMES = {
    "中華民國開國紀念日", "和平紀念日", "兒童節及民族掃墓節", "勞動節",
    "端午節", "中秋節", "孔子誕辰紀念日/教師節", "國慶日",
    "臺灣光復暨金門古寧頭大捷紀念日", "行憲紀念日", "農曆除夕及春節",
}
REPLACEMENT_NAMES = {
    "和平紀念日": "和平紀念日", "兒童節": "兒童節及民族掃墓節",
    "民族掃墓節": "兒童節及民族掃墓節", "國慶日": "國慶日",
    "臺灣光復暨金門古寧頭大捷紀念日": "臺灣光復暨金門古寧頭大捷紀念日",
}


def _clean(value):
    # Only explicit br tags and whitespace. Other markup remains unrecognized.
    return re.sub(r"\s+", "", re.sub(r"<\s*br\s*/?\s*>", "", value))


def _rows(body, year):
    _require(type(year) is int and 1 <= year <= 9999, "invalid_schedule_year")
    rows = _json(body)
    _require(isinstance(rows, list) and bool(rows), "nonempty_row_list_required")
    days = set()
    for row in rows:
        _require(isinstance(row, dict), "row_object_required")
        _require(all(isinstance(row.get(k), str) for k in ("Name", "Description", "Weekday")), "row_text_required")
        day = _day(row.get("Date"))
        _require(day.year == year, "schedule_year_mismatch")
        _require(day not in days, "duplicate_date")
        _require(row["Weekday"].strip() == WEEKDAYS[day.weekday()], "weekday_mismatch")
        days.add(day)
    return rows


def _closed_reason(row):
    day = _day(row["Date"])
    name, description = _clean(row["Name"]), _clean(row["Description"])
    if name == "市場無交易，僅辦理結算交割作業" and description == "":
        return None
    if name not in HOLIDAY_NAMES:
        return "unrecognized_or_nonclosing_name"
    if description == "依規定放假1日。":
        return None
    replacement = re.fullmatch(
        r"(.+)為(\d{1,2})月(\d{1,2})日適逢星期([六日])，於(\d{1,2})月(\d{1,2})日（星期([一二三四五六日])）補假。",
        description,
    )
    lunar = re.fullmatch(
        r"依規定於(\d{1,2})月(\d{1,2})日至(\d{1,2})月(\d{1,2})日放假(\d+)日。"
        r"(\d{1,2})月(\d{1,2})日適逢星期([六日])，於(\d{1,2})月(\d{1,2})日（星期([一二三四五六日])）補假。",
        description,
    )
    try:
        if replacement:
            label, m, d, weekday, rm, rd, replacement_weekday = replacement.groups()
            if REPLACEMENT_NAMES.get(label) != name:
                return "replacement_name_mismatch"
            original, substitute = date(day.year, int(m), int(d)), date(day.year, int(rm), int(rd))
            if WEEKDAYS[original.weekday()] != weekday or WEEKDAYS[substitute.weekday()] != replacement_weekday:
                return "description_weekday_mismatch"
            return None if day == substitute else "outside_explicit_replacement_date"
        if lunar and name == "農曆除夕及春節":
            m, d, em, ed, count, om, od, weekday, rm, rd, replacement_weekday = lunar.groups()
            first, last = date(day.year, int(m), int(d)), date(day.year, int(em), int(ed))
            original, substitute = date(day.year, int(om), int(od)), date(day.year, int(rm), int(rd))
            if (last - first).days + 1 != int(count) or not first <= original <= last or first <= substitute <= last:
                return "description_range_mismatch"
            if WEEKDAYS[original.weekday()] != weekday or WEEKDAYS[substitute.weekday()] != replacement_weekday:
                return "description_weekday_mismatch"
            return None if first <= day <= last or day == substitute else "outside_explicit_holiday_dates"
    except ValueError:
        return "invalid_description_date"
    return "unrecognized_or_nonclosing_description"


@dataclass(frozen=True)
class HolidayCapture:
    """Validated local evidence, not a cryptographic proof of origin or PIT."""
    body: bytes
    receipt_bytes: bytes
    schedule_year: int
    captured_at: datetime
    sha256: str
    body_path: Path

    def select(self, start, end):
        from .sources import FetchedPayload

        _require(type(start) is date and type(end) is date and start <= end, "invalid_date_range")
        receipt = _json(self.receipt_bytes)
        _require(isinstance(receipt, dict), "receipt_object_required")
        _require(self.captured_at.utcoffset() is not None and self.captured_at == _timestamp(receipt.get("captured_at")), "capture_timestamp_changed")
        _require(_timestamp(receipt.get("request_started_at")) <= self.captured_at, "nonmonotonic_timestamps")
        _require(receipt.get("body_sha256") == self.sha256 and receipt.get("body_bytes") == len(self.body), "capture_metadata_changed")
        _require(receipt.get("source_id") == SOURCE_ID and receipt.get("endpoint") == ENDPOINT, "capture_source_changed")
        _require(hashlib.sha256(self.body).hexdigest() == self.sha256, "capture_body_changed")
        _require(self.body_path.read_bytes() == self.body, "materialized_body_changed")
        _require(self.body_path.with_name("receipt.json").read_bytes() == self.receipt_bytes, "materialized_receipt_changed")
        rows = _rows(self.body, self.schedule_year)
        closed, unknown = set(), []
        for row in rows:
            day = _day(row["Date"])
            if not start <= day <= end:
                continue
            reason = _closed_reason(row)
            if reason is None:
                closed.add(day)
            else:
                unknown.append({"date": day.isoformat(), "name": row["Name"], "reason": reason})
        # Calendar year denotes the payload's domain, never a verified session.
        raw = FetchedPayload("twse", ENDPOINT, rows, str(self.schedule_year), self.captured_at, self.body_path, self.sha256)
        return closed, raw, unknown


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
        lock = output / ".holiday.lock"
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


def load_holiday_capture(capture_zip, *, manifest, profile, expected_registry_version,
                          expected_digest, expected_schedule_year, output_dir):
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
        raise HolidayCaptureError("invalid_zip") from exc
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
        _require(type(receipt.get(key)) is type(value) and _same(receipt.get(key), value), "receipt_mismatch:" + key)
    _require(type(receipt.get("http_status")) is int and 200 <= receipt["http_status"] < 300, "invalid_http_status")
    attribution = {"owner": source["owner"], "dataset_id": source["dataset_id"], "source_id": SOURCE_ID,
                   "source_url": ENDPOINT, "terms": source["access"]["documented_terms"], "evidence": source["evidence"],
                   "purpose_evidence": {p: source["purposes"][p]["evidence"] for p in decisions}}
    _require(_same(receipt.get("attribution"), attribution), "attribution_mismatch")
    conditions = receipt.get("condition_receipts")
    _require(isinstance(conditions, dict) and set(conditions) == MIN_CONDITIONS["local_fetch"] | MIN_CONDITIONS["raw_store"], "condition_receipts_missing")
    _require(all(isinstance(v, dict) for v in conditions.values()), "condition_receipts_invalid")
    _require(conditions.get("attribute_source") == {"artifact": "receipt.json:attribution"}, "attribution_receipt")
    _require(conditions.get("preserve_source_integrity") == {"artifact": "body.bin", "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding"}, "integrity_receipt")
    _require(_same(conditions.get("bounded_requests"), {"max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS,
        "cooperative_deadline_seconds": DEADLINE_SECONDS, "deadline_scope": "checked between streamed chunks; not a hard total deadline", "max_body_bytes": MAX_BODY_BYTES}), "bounds_receipt")
    limits = conditions.get("respect_endpoint_limits", {})
    _require(_same(limits, {"strategy": "single_get_stop_on_response", "retries": 0, "redirects": 0,
                           "warmup_requests": 0, "numeric_quota_verified": False}), "limits_receipt")
    _require(source["access"]["rate_limit"]["status"] == "unknown"
             and receipt.get("rate_limit_evidence") == source["access"]["rate_limit"]
             and receipt.get("documented_numeric_rate_limit") == "unknown"
             and receipt.get("rate_limit_verified") is False
             and limits.get("numeric_quota_verified") is False, "rate_limit_receipt")
    started, captured = _timestamp(receipt.get("request_started_at")), _timestamp(receipt.get("captured_at"))
    _require(started <= captured, "nonmonotonic_timestamps")
    _rows(body, expected_schedule_year)
    path = _publish(output_dir, body, receipt_bytes)
    return HolidayCapture(body, receipt_bytes, expected_schedule_year, captured, expected["body_sha256"], path)
