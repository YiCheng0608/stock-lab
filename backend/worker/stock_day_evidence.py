"""Detached, read-only STOCK_DAY_ALL evidence for one sealed selected bar.

The verdict is local consistency of named files and a pinned local registry.
It does not authenticate TWSE, the receipt at capture time, availability, PIT,
or any v3 prior-volume row. It does not modify capture/bridge status fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from .source_registry import MIN_CONDITIONS, decide_policy, validation_report
from .stock_day_capture import (
    ENDPOINT, MAX_RECEIPT_BYTES, SOURCE_ID, StockDayCaptureError,
    _json, _numeric, _rows, _timestamp,
)
from .source_runtime import DEADLINE_SECONDS, MAX_BODY_BYTES, PROJECT_ROOT, TIMEOUT_SECONDS


SCHEMA_VERSION = "stock-day-selected-bar-evidence/v1"
MAX_MANIFEST_BYTES = 1024 * 1024
_HEX = re.compile(r"[0-9a-fA-F]{64}\Z")
_REGISTRY_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class StockDayEvidenceError(ValueError):
    """A complete verdict was refused; ``code`` is a stable reason code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise StockDayEvidenceError(code)


def _digest_pin(value, code: str) -> str:
    _require(type(value) is str and _HEX.fullmatch(value) is not None, code)
    return value.lower()


def _same_json(left, right) -> bool:
    """Compare decoded JSON without Python's bool/int equality coercion."""
    if type(left) is Decimal and type(right) is float:
        return left == Decimal(str(right))
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(
            _same_json(left[key], right[key]) for key in right
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _same_json(a, b) for a, b in zip(left, right)
        )
    return left == right


def _manifest_json(raw: bytes) -> dict:
    """Use the registry's ordinary JSON number types for its canonical digest."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate manifest key")
            result[key] = value
        return result

    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("nonfinite manifest number")
        return value

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=finite_float,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise StockDayEvidenceError("manifest_invalid") from exc
    _require(type(value) is dict, "manifest_invalid")
    return value


@dataclass(frozen=True)
class _BoundFile:
    path: Path
    kind: str
    resolved: Path
    identity: tuple[int, int, int, int, int, int]
    external: bool


def _identity(info) -> tuple[int, int, int, int, int, int]:
    _require(type(info.st_ino) is int and info.st_ino != 0,
             "file_identity_unavailable")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def _inspect_path(path: Path, kind: str, external: bool):
    """Observed path identity; this is not a defense against arbitrary races."""
    try:
        if os.name == "nt" and not hasattr(Path, "is_junction"):
            raise StockDayEvidenceError(kind + "_alias_check_unsupported")
        for part in (path, *path.parents):
            if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                raise StockDayEvidenceError(kind + "_path_alias")
        resolved = path.resolve(strict=True)
        _require(os.path.normcase(str(path)) == os.path.normcase(str(resolved)),
                 kind + "_path_alias")
        if external:
            _require(not resolved.is_relative_to(PROJECT_ROOT), kind + "_path_protected")
        info = path.stat()
        _require(stat.S_ISREG(info.st_mode), kind + "_not_regular")
        _require(info.st_nlink == 1, kind + "_path_alias")
        identity = _identity(info)
    except StockDayEvidenceError:
        raise
    except (OSError, RuntimeError) as exc:
        raise StockDayEvidenceError(kind + "_unreadable") from exc
    return resolved, identity


def _checked_path(value, kind: str, *, name: str | None = None,
                  external: bool = False) -> _BoundFile:
    _require(isinstance(value, (str, Path)), kind + "_path_invalid")
    path = Path(value)
    _require(path.is_absolute() and not str(value).casefold().startswith("file:")
             and ":memory:" not in str(value) and ".." not in path.parts,
             kind + "_path_invalid")
    if name is not None:
        _require(path.name == name, kind + "_path_invalid")
    resolved, identity = _inspect_path(path, kind, external)
    return _BoundFile(path, kind, resolved, identity, external)


def _assert_binding(bound: _BoundFile) -> None:
    resolved, identity = _inspect_path(bound.path, bound.kind, bound.external)
    _require(resolved == bound.resolved and identity == bound.identity,
             bound.kind + "_changed")


def _stable_read(bound: _BoundFile, limit: int) -> bytes:
    """Bounded double read against the identity bound for this entire call."""
    kind = bound.kind
    _assert_binding(bound)
    try:
        before = bound.path.stat()
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                 kind + "_path_alias")
        _require(before.st_size <= limit, kind + "_size_limit")
        with bound.path.open("rb") as source:
            opened = os.fstat(source.fileno())
            _require(stat.S_ISREG(opened.st_mode), kind + "_not_regular")
            _require(opened.st_nlink == 1, kind + "_path_alias")
            _require(opened.st_size <= limit, kind + "_size_limit")
            _require(_identity(opened) == bound.identity, kind + "_changed")
            first = source.read(limit + 1)
            source.seek(0)
            second = source.read(limit + 1)
            closed = os.fstat(source.fileno())
        after = bound.path.stat()
    except StockDayEvidenceError:
        raise
    except OSError as exc:
        raise StockDayEvidenceError(kind + "_unreadable") from exc
    _require(len(first) <= limit and len(second) <= limit, kind + "_size_limit")
    _require(_identity(before) == _identity(opened) == _identity(closed)
             == _identity(after) == bound.identity
             and len(first) == before.st_size and first == second, kind + "_changed")
    _assert_binding(bound)
    return first


def _verify_payload(*, call: dict, capture_kind: str, body: bytes,
                    receipt_bytes: bytes, manifest: dict,
                    expected_receipt_sha256: str, expected_registry_version: str,
                    expected_manifest_digest: str, expected_profile: str) -> dict:
    """Pure parse/match boundary; callers pass only already read bytes and data."""
    from .analysis_capture import (
        AnalysisCaptureError, KIND_V2, KIND_V3, _exact, _selected_bar_float,
        _validate_selected_bar_provenance,
    )

    _require(capture_kind in (KIND_V2, KIND_V3), "unsupported_capture_kind")
    _require(type(body) is bytes and type(receipt_bytes) is bytes
             and len(body) <= MAX_BODY_BYTES and len(receipt_bytes) <= MAX_RECEIPT_BYTES,
             "evidence_size_limit")
    _require(hashlib.sha256(receipt_bytes).hexdigest() ==
             _digest_pin(expected_receipt_sha256, "expected_receipt_sha256_required"),
             "receipt_hash_mismatch")
    _require(type(expected_registry_version) is str and bool(expected_registry_version)
             and type(expected_profile) is str and bool(expected_profile)
             and type(expected_manifest_digest) is str
             and _REGISTRY_DIGEST.fullmatch(expected_manifest_digest) is not None,
             "registry_pins_required")
    report = validation_report(manifest, expected_registry_version=expected_registry_version,
                               expected_digest=expected_manifest_digest)
    _require(report["valid"] and report["verification"] == "pinned", "registry_pin_mismatch")
    sources = [item for item in manifest["sources"] if item["source_id"] == SOURCE_ID]
    _require(len(sources) == 1 and sources[0]["exact_url"] == ENDPOINT
             and sources[0]["method"] == "GET", "registry_source_mismatch")
    source = sources[0]
    decisions = {}
    for purpose in ("local_fetch", "raw_store"):
        decision = decide_policy(manifest, SOURCE_ID, purpose, profile=expected_profile,
                                 endpoint=ENDPOINT, method="GET")
        _require(decision.allowed and set(decision.conditions) == MIN_CONDITIONS[purpose],
                 "registry_policy_rejected")
        decisions[purpose] = decision.to_dict()
    _require(source["access"]["rate_limit"]["status"] == "unknown",
             "registry_policy_rejected")

    try:
        receipt = _json(receipt_bytes)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise StockDayEvidenceError("receipt_invalid") from exc
    _require(type(receipt) is dict, "receipt_invalid")
    body_sha = hashlib.sha256(body).hexdigest()
    expected = {
        "schema_version": "source-capture/v1", "status": "capture_complete",
        "source_id": SOURCE_ID, "endpoint": ENDPOINT, "method": "GET",
        "source_version": source["source_version"], "profile": expected_profile,
        "registry_version": expected_registry_version,
        "manifest_digest": expected_manifest_digest,
        "body_sha256": body_sha, "body_bytes": len(body),
        "executed_purposes": ["local_fetch", "raw_store"],
        "policy_decisions": decisions, "historical_pit": "unsupported",
        "request_count": 1, "error_reason": None,
        "rate_limit_verified": False, "rate_limit_scope": "one invocation; no cross-process enforcement",
        "documented_numeric_rate_limit": "unknown",
        "rate_limit_evidence": source["access"]["rate_limit"],
    }
    for key, value in expected.items():
        _require(_same_json(receipt.get(key), value),
                 "receipt_pin_mismatch")
    _require(type(receipt.get("http_status")) is int
             and 200 <= receipt["http_status"] < 300, "receipt_http_status_invalid")
    attribution = {
        "owner": source["owner"], "dataset_id": source["dataset_id"],
        "source_id": SOURCE_ID, "source_url": ENDPOINT,
        "terms": source["access"]["documented_terms"],
        "evidence": source["evidence"],
        "purpose_evidence": {purpose: source["purposes"][purpose]["evidence"]
                             for purpose in decisions},
    }
    _require(_same_json(receipt.get("attribution"), attribution),
             "receipt_attribution_mismatch")
    conditions = receipt.get("condition_receipts")
    _require(type(conditions) is dict
             and set(conditions) == MIN_CONDITIONS["local_fetch"] | MIN_CONDITIONS["raw_store"],
             "receipt_conditions_mismatch")
    _require(_same_json(conditions["attribute_source"], {"artifact": "receipt.json:attribution"})
             and _same_json(conditions["preserve_source_integrity"], {
                 "artifact": "body.bin",
                 "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding",
             }) and _same_json(conditions["bounded_requests"], {
                 "max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS,
                 "cooperative_deadline_seconds": DEADLINE_SECONDS,
                 "deadline_scope": "checked between streamed chunks; not a hard total deadline",
                 "max_body_bytes": MAX_BODY_BYTES,
             }) and _same_json(conditions["respect_endpoint_limits"], {
                 "strategy": "single_get_stop_on_response", "retries": 0,
                 "redirects": 0, "warmup_requests": 0,
                 "numeric_quota_verified": False,
             }), "receipt_conditions_mismatch")
    try:
        started = _timestamp(receipt.get("request_started_at"))
        captured = _timestamp(receipt.get("captured_at"))
    except StockDayCaptureError as exc:
        raise StockDayEvidenceError("receipt_timestamp_invalid") from exc
    _require(started <= captured, "receipt_timestamp_invalid")

    _require(type(call) is dict and type(call.get("selected_strategy")) is dict
             and call.get("evaluator") == call["selected_strategy"].get("name"),
             "evaluator_not_selected_strategy")
    provenance = call.get("input_provenance")
    if capture_kind == KIND_V3:
        _require(type(provenance) is dict and set(provenance) == {"selected_bar", "prior_volumes"},
                 "selected_bar_provenance_invalid")
        provenance = provenance["selected_bar"]
    subject = call.get("subject")
    _require(type(subject) is dict and subject.get("exchange") == "TWSE"
             and type(subject.get("symbol")) is str
             and subject["symbol"] == subject["symbol"].strip().upper(),
             "source_identity_mismatch")
    try:
        _validate_selected_bar_provenance(
            provenance, call["arguments"], subject=subject,
            market_date=call["observed_market_date"],
        )
    except (AnalysisCaptureError, KeyError, TypeError, ValueError) as exc:
        raise StockDayEvidenceError("selected_bar_provenance_invalid") from exc
    bar, raw = provenance["bar"], provenance["raw_payload"]
    _require(bar["raw_payload_id"] is not None and raw is not None,
             "raw_fk_missing")
    _require(bar["source"] == raw["source"] == "twse"
             and raw["endpoint"] == ENDPOINT, "source_identity_mismatch")
    _require(type(raw["sha256"]) is str and _HEX.fullmatch(raw["sha256"]) is not None,
             "raw_digest_missing")
    _require(raw["sha256"].lower() == body_sha, "body_hash_mismatch")
    try:
        rows, market_day = _rows(body)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise StockDayEvidenceError("body_invalid") from exc
    _require(market_day.isoformat() == call["observed_market_date"]
             and bar["trading_date"] == call["observed_market_date"],
             "market_date_mismatch")
    matches = [row for row in rows if row["Code"].strip() == subject["symbol"]]
    _require(len(matches) == 1, "selected_symbol_missing")
    row = matches[0]
    values = {}
    for field in ("OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice",
                  "TradeVolume", "TradeValue"):
        try:
            values[field] = _numeric(row.get(field), integer=field == "TradeVolume",
                                     positive=field.endswith("Price"))
        except (ValueError, OverflowError) as exc:
            raise StockDayEvidenceError("selected_row_invalid") from exc
    opening, high, low, close = (values[key] for key in
                                 ("OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice"))
    _require(low <= opening <= high and low <= close <= high, "selected_row_invalid")
    volume = values["TradeVolume"]
    _require(_exact(close, _selected_bar_float(bar["close"]))
             and type(bar["volume"]) is int and volume == bar["volume"],
             "selected_bar_value_mismatch")
    _require(_exact(call["arguments"]["close"], close)
             and _exact(call["arguments"]["volume"], _selected_bar_float(volume)),
             "evaluator_projection_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": "local_evidence_consistent",
        "scope": "selected_bar_only",
        "capture_kind": capture_kind,
        "raw_payload_id": raw["id"],
        "source_id": SOURCE_ID,
        "source_version": source["source_version"],
        "registry_version": expected_registry_version,
        "manifest_digest": expected_manifest_digest,
        "body_sha256": body_sha,
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "symbol": subject["symbol"],
        "market_date": market_day.isoformat(),
        "close": close,
        "volume": volume,
    }


def verify_selected_bar_evidence(
    *, research_snapshot_path, expected_snapshot_sha256, attempt_id, ordinal,
    manifest_path, expected_registry_version, expected_manifest_digest,
    expected_profile, expected_receipt_sha256,
) -> dict:
    """Verify one exact v2/v3 selected call and return a detached local verdict.

    Every path is explicit. No candidate, DB row, cache, or sidecar is written.
    The caller must provide the current research SHA and external receipt and
    registry pins; this function does not discover a file by digest or recency.
    """
    from app.signal_artifact_store import ReadonlySnapshotError, readonly_snapshot
    from .analysis_capture import KIND_V2, KIND_V3, _read_analysis_attempt

    snapshot_sha = _digest_pin(expected_snapshot_sha256, "expected_snapshot_sha256_required")
    _digest_pin(expected_receipt_sha256, "expected_receipt_sha256_required")
    _require(type(attempt_id) is str and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", attempt_id) is not None,
        "invalid_attempt_id")
    _require(type(ordinal) is int and ordinal >= 0, "invalid_ordinal")
    try:
        with readonly_snapshot(research_snapshot_path,
                               expected_database_sha256=snapshot_sha) as (connection, fingerprint):
            try:
                verified = _read_analysis_attempt(
                    research_database_path=research_snapshot_path,
                    attempt_id=attempt_id, _connection=connection,
                )
            except Exception as exc:
                raise StockDayEvidenceError("capture_invalid") from exc
            _require(ordinal < len(verified["captures"]), "ordinal_not_found")
            kind = verified["receipt"]["kind"]
            _require(kind in (KIND_V2, KIND_V3), "unsupported_capture_kind")
            call = verified["captures"][ordinal]
            _require(call["evaluator"] == call["selected_strategy"]["name"],
                     "evaluator_not_selected_strategy")
            provenance = (call["input_provenance"]["selected_bar"] if kind == KIND_V3
                          else call["input_provenance"])
            raw = provenance["raw_payload"]
            _require(provenance["bar"]["raw_payload_id"] is not None and raw is not None,
                     "raw_fk_missing")
            _require(provenance["bar"]["raw_payload_id"] == raw["id"]
                     and provenance["bar"]["source"] == raw["source"] == "twse"
                     and call["subject"]["exchange"] == "TWSE"
                     and raw["endpoint"] == ENDPOINT, "source_identity_mismatch")
            body_path = _checked_path(raw["payload_path"], "body", name="body.bin",
                                      external=True)
            receipt_path = _checked_path(body_path.path.with_name("receipt.json"), "receipt",
                                         name="receipt.json", external=True)
            selected_manifest = _checked_path(manifest_path, "manifest")
            body = _stable_read(body_path, MAX_BODY_BYTES)
            receipt_bytes = _stable_read(receipt_path, MAX_RECEIPT_BYTES)
            manifest_bytes = _stable_read(selected_manifest, MAX_MANIFEST_BYTES)
            manifest = _manifest_json(manifest_bytes)
            result = _verify_payload(
                call=call, capture_kind=kind, body=body, receipt_bytes=receipt_bytes,
                manifest=manifest, expected_receipt_sha256=expected_receipt_sha256,
                expected_registry_version=expected_registry_version,
                expected_manifest_digest=expected_manifest_digest,
                expected_profile=expected_profile,
            )
            final_body = _stable_read(body_path, MAX_BODY_BYTES)
            final_receipt = _stable_read(receipt_path, MAX_RECEIPT_BYTES)
            final_manifest = _stable_read(selected_manifest, MAX_MANIFEST_BYTES)
            _require(final_body == body and final_receipt == receipt_bytes
                     and final_manifest == manifest_bytes,
                     "evidence_changed")
            return {**result, "research_snapshot_sha256": fingerprint["sha256"],
                    "attempt_id": attempt_id, "ordinal": ordinal}
    except ReadonlySnapshotError as exc:
        raise StockDayEvidenceError("snapshot_invalid") from exc


__all__ = ["StockDayEvidenceError", "verify_selected_bar_evidence"]
