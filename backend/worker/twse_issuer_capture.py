"""Independent, pinned TWSE issuer acquisition; original bytes stay in RAM.

Import has no application, database, filesystem-write or HTTP side effects.
The exact 33-string schema is checked before any selected projection. This is
issuer identity evidence, never an ordinary-stock/ETF/PIT classification.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from uuid import UUID

from .source_registry import MIN_CONDITIONS, decide_policy, load_manifest

SOURCE_ID = "twse_t187ap03_l"
SOURCE_VERSION = "twse-t187ap03-l-d18419-2026-10-08"
ENDPOINT = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
PROFILE = "twse_issuer_free_public_local"
REGISTRY_VERSION = "twse-issuer-r1-2026-10-08.1"
REGISTRY_DIGEST = "sha256:7488da20a3bdf94aaa548c896d19077628bf93529208226d49b2a02896972f89"
MANIFEST = Path(__file__).with_name("twse_issuer_registry.json")
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
MAX_ROWS = 2000
TIMEOUT_SECONDS = 15.0
DEADLINE_SECONDS = 30.0
SYMBOLS = ("1449", "1463", "2614")
FIELDS = ("出表日期", "公司代號", "公司名稱", "公司簡稱", "外國企業註冊地國", "產業別", "住址",
          "營利事業統一編號", "董事長", "總經理", "發言人", "發言人職稱", "代理發言人", "總機電話",
          "成立日期", "上市日期", "普通股每股面額", "實收資本額", "私募股數", "特別股", "編制財務報表類型",
          "股票過戶機構", "過戶電話", "過戶地址", "簽證會計師事務所", "簽證會計師1", "簽證會計師2",
          "英文簡稱", "英文通訊地址", "傳真機號碼", "電子郵件信箱", "網址", "已發行普通股數或TDR原股發行股數")


class IssuerCaptureError(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise IssuerCaptureError(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")


def strict_json(raw: bytes) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "issuer_duplicate_json_key")
            result[key] = value
        return result
    def invalid(_):
        raise IssuerCaptureError("issuer_nonfinite_json")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, IssuerCaptureError):
            raise
        raise IssuerCaptureError("issuer_invalid_json") from exc


def source_date(raw: str, *, report: bool = False) -> str:
    require(type(raw) is str and re.fullmatch(r"[0-9]{7}" if report else r"(?:[0-9]{7}|[0-9]{8})", raw) is not None,
            "issuer_report_date_invalid" if report else "issuer_listing_date_invalid")
    try:
        year = int(raw[:-4]) + (1911 if len(raw) == 7 else 0)
        require(int(raw[:-4]) > 0, "issuer_source_date_invalid")
        return date(year, int(raw[-4:-2]), int(raw[-2:])).isoformat()
    except (ValueError, OverflowError) as exc:
        if isinstance(exc, IssuerCaptureError):
            raise
        raise IssuerCaptureError("issuer_source_date_invalid") from exc


def timestamp(raw: Any) -> datetime:
    require(type(raw) is str, "issuer_capture_time_invalid")
    try:
        parsed = datetime.fromisoformat(raw)
        require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
                "issuer_capture_time_invalid")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise IssuerCaptureError("issuer_capture_time_invalid") from exc


def admission(*, expected_registry_version: str, expected_digest: str,
              manifest: str | Path = MANIFEST, profile: str = PROFILE) -> tuple[dict, dict]:
    require(expected_registry_version == REGISTRY_VERSION and expected_digest == REGISTRY_DIGEST
            and profile == PROFILE, "issuer_external_registry_pins_mismatch")
    registry = load_manifest(manifest, expected_registry_version=expected_registry_version,
                             expected_digest=expected_digest)
    require(len(registry["sources"]) == 1, "issuer_registry_scope_invalid")
    source = registry["sources"][0]
    require(source["source_id"] == SOURCE_ID and source["source_version"] == SOURCE_VERSION
            and source["exact_url"] == ENDPOINT and source["method"] == "GET", "issuer_source_pins_mismatch")
    decisions = {}
    for purpose in ("local_fetch", "raw_store", "summarize"):
        decision = decide_policy(registry, SOURCE_ID, purpose, profile=profile, endpoint=ENDPOINT, method="GET")
        require(decision.allowed and set(decision.conditions) == MIN_CONDITIONS[purpose],
                "issuer_purpose_not_admitted")
        decisions[purpose] = decision.to_dict()
    require(source["access"]["rate_limit"]["status"] == "unknown", "issuer_rate_limit_not_supported")
    return source, decisions


def attribution(source: dict, decisions: dict) -> dict:
    return {"owner": source["owner"], "dataset_id": source["dataset_id"], "source_id": SOURCE_ID,
            "source_url": ENDPOINT, "terms": source["access"]["documented_terms"], "evidence": source["evidence"],
            "purpose_evidence": {key: source["purposes"][key]["evidence"] for key in decisions}}


def conditions() -> dict:
    return {"bounded_requests": {"max_requests": 1, "max_body_bytes": MAX_BODY_BYTES,
                                  "per_operation_timeout_seconds": TIMEOUT_SECONDS,
                                  "cooperative_deadline_seconds": DEADLINE_SECONDS,
                                  "deadline_scope": "checked between chunks; not a hard total deadline"},
            "respect_endpoint_limits": {"retries": 0, "redirects": 0, "warmup_requests": 0,
                                         "numeric_quota_verified": False},
            "attribute_source": {"artifact": "memory:receipt.attribution"},
            "preserve_source_integrity": {"artifact": "memory:body", "encoding": "identity HTTP entity bytes; no re-encoding"}}


def validate_feed(body: bytes) -> tuple[int, dict[str, dict]]:
    require(type(body) is bytes and len(body) <= MAX_BODY_BYTES, "issuer_body_limit")
    payload = strict_json(body)
    require(type(payload) is list and 0 < len(payload) <= MAX_ROWS, "issuer_row_list_invalid")
    codes = set()
    selected = {}
    for ordinal, row in enumerate(payload, 1):
        require(type(row) is dict and set(row) == set(FIELDS)
                and all(type(value) is str for value in row.values()), "issuer_row_schema_invalid")
        code = row["公司代號"]
        require(re.fullmatch(r"[0-9A-Z]{4,6}", code) is not None, "issuer_company_code_invalid")
        require(code not in codes, "issuer_duplicate_company_code")
        codes.add(code)
        if code not in SYMBOLS:
            continue
        require(bool(row["公司名稱"].strip()) and bool(row["公司簡稱"].strip())
                and bool(row["產業別"].strip()), "issuer_selected_identity_missing")
        selected[code] = {"exchange": "TWSE", "symbol": code, "full_name": row["公司名稱"],
                          "short_name": row["公司簡稱"], "report_date_raw": row["出表日期"],
                          "report_date": source_date(row["出表日期"], report=True), "report_date_role": "issuer_report_date",
                          "listing_date_raw": row["上市日期"], "listing_date": source_date(row["上市日期"]),
                          "listing_date_role": "listing_date", "industry_code_raw": row["產業別"],
                          "row_ordinal": ordinal, "source_row": row}
    return len(payload), selected


def capture_memory(*, expected_registry_version: str, expected_digest: str, generation_id: str,
                   transport: Any = None, failure_original_sink: Any = None) -> tuple[bytes | None, bytes]:
    """One exact GET, no retries or redirects and no disk delivery path."""
    body = None
    original_body = None
    receipt = {"schema_version": "twse-issuer-memory-capture/v1", "status": "rejected",
               "storage": "memory_only", "generation_id": generation_id, "source_id": SOURCE_ID,
               "source_version": SOURCE_VERSION, "endpoint": ENDPOINT, "method": "GET", "profile": PROFILE,
               "registry_version": expected_registry_version, "manifest_digest": expected_digest,
               "request_count": 0, "http_status": None, "request_started_at": None, "captured_at": None,
               "body_bytes": 0, "body_sha256": None, "error_reason": None, "executed_purposes": [],
               "historical_pit": "unsupported", "rate_limit_verified": False}
    try:
        require(str(UUID(generation_id)) == generation_id, "issuer_generation_invalid")
        source, decisions = admission(expected_registry_version=expected_registry_version, expected_digest=expected_digest)
        receipt.update(attribution=attribution(source, decisions), policy_decisions=decisions,
                       condition_receipts=conditions(), documented_numeric_rate_limit="unknown")
        import httpx
        started = time.monotonic()
        receipt.update(status="capture_failed", request_count=1, request_started_at=datetime.now(timezone.utc).isoformat())
        chunks = bytearray()
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
            with client.stream("GET", ENDPOINT, headers={"Accept-Encoding": "identity", "User-Agent": "taiwan-stock-research/issuer-memory-v1"}) as response:
                receipt["http_status"] = response.status_code
                require(200 <= response.status_code < 300, "issuer_http_status:" + str(response.status_code))
                require(response.headers.get("Content-Encoding", "identity").strip().lower() in {"", "identity"},
                        "issuer_content_encoding_invalid")
                for chunk in response.iter_raw():
                    require(time.monotonic() - started <= DEADLINE_SECONDS, "issuer_cooperative_deadline")
                    require(len(chunks) + len(chunk) <= MAX_BODY_BYTES, "issuer_body_limit")
                    chunks.extend(chunk)
                require(time.monotonic() - started <= DEADLINE_SECONDS, "issuer_cooperative_deadline")
        body = bytes(chunks)
        original_body = body
        receipt.update(body_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest())
        validate_feed(body)
        receipt.update(status="capture_complete", captured_at=datetime.now(timezone.utc).isoformat(),
                       body_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest(),
                       executed_purposes=["local_fetch", "raw_store"])
    except Exception as exc:
        receipt["error_reason"] = str(exc) if isinstance(exc, IssuerCaptureError) else "issuer_capture_failed"
        receipt["status"] = "capture_failed" if receipt["request_count"] else "rejected"
        body = None
    original_receipt = canonical(receipt)
    if body is None and original_body is not None and failure_original_sink is not None:
        # A complete but invalid entity remains unpublished, inspectable RAM evidence.
        failure_original_sink(original_body, original_receipt)
    return body, original_receipt


def summarize_memory(body: bytes, receipt_bytes: bytes, *, expected_registry_version: str,
                     expected_digest: str, generation_id: str) -> dict:
    source, decisions = admission(expected_registry_version=expected_registry_version, expected_digest=expected_digest)
    require(type(receipt_bytes) is bytes and len(receipt_bytes) <= MAX_RECEIPT_BYTES, "issuer_receipt_limit")
    receipt = strict_json(receipt_bytes)
    require(type(receipt) is dict and canonical(receipt) == receipt_bytes, "issuer_receipt_not_original_canonical")
    count, selected = validate_feed(body)
    expected = {"schema_version": "twse-issuer-memory-capture/v1", "status": "capture_complete",
                "storage": "memory_only", "generation_id": generation_id, "source_id": SOURCE_ID,
                "source_version": SOURCE_VERSION, "endpoint": ENDPOINT, "method": "GET", "profile": PROFILE,
                "registry_version": expected_registry_version, "manifest_digest": expected_digest,
                "request_count": 1, "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                "error_reason": None, "executed_purposes": ["local_fetch", "raw_store"],
                "historical_pit": "unsupported", "rate_limit_verified": False,
                "attribution": attribution(source, decisions), "policy_decisions": decisions,
                "condition_receipts": conditions(), "documented_numeric_rate_limit": "unknown"}
    require(set(receipt) == set(expected) | {"http_status", "request_started_at", "captured_at"}, "issuer_receipt_schema_invalid")
    for key, value in expected.items():
        require(canonical(receipt.get(key)) == canonical(value), "issuer_receipt_mismatch:" + key)
    require(type(receipt["http_status"]) is int and 200 <= receipt["http_status"] < 300, "issuer_http_status_invalid")
    require(timestamp(receipt["request_started_at"]) <= timestamp(receipt["captured_at"]), "issuer_capture_time_invalid")
    return {"candidate_count": count, "selected": selected, "attribution": receipt["attribution"],
            "provenance": {key: receipt[key] for key in ("source_id", "source_version", "endpoint", "profile",
                                                        "registry_version", "manifest_digest", "generation_id",
                                                        "request_started_at", "captured_at", "body_sha256", "body_bytes")}
            | {"receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(), "storage": "memory_only",
               "verification": "local_evidence_consistent", "validation_scope": "all_33_string_fields_unique_company_codes"}}
