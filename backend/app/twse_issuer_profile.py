"""Selected issuer profile from independent RAM originals and same-cutoff events."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
import re
from threading import Lock
from typing import Mapping
from uuid import uuid4

from worker import twse_issuer_capture as consumer

VERSION = "twse-issuer-event-profile/m1-v1"
POLICY_DIGEST = "sha256:02bf2422129c46490516557bccd188f7d550d2516c4b5e49e9acc2faf5338244"
_POLICY = json.loads(r'''{"classification":"unsupported","cutoff":"observed_taipei_date_inclusive","historical_pit":"unsupported","listing_date":["Gregorian8date","ROC7date"],"max_attempts":1,"max_body_bytes":5242880,"max_rows":2000,"name_relation":"exact_event_name_equals_issuer_full_or_short","profile":"twse_issuer_free_public_local","registry_digest":"sha256:7488da20a3bdf94aaa548c896d19077628bf93529208226d49b2a02896972f89","registry_version":"twse-issuer-r1-2026-10-08.1","report_date":"ROC7date","schema":"exact33stringfields_uniquecompanycodes","source_id":"twse_t187ap03_l","source_version":"twse-t187ap03-l-d18419-2026-10-08","storage":"memory_only","symbols":["1449","1463","2614"],"version":"twse-issuer-event-profile/m1-v1"}''')
CAPTURE_ENV = "STOCK_TWSE_ISSUER_MEMORY_CAPTURE"
REGISTRY_VERSION_ENV = "STOCK_TWSE_ISSUER_REGISTRY_VERSION"
REGISTRY_DIGEST_ENV = "STOCK_TWSE_ISSUER_REGISTRY_DIGEST"
PROFILE_VERSION_ENV = "STOCK_TWSE_ISSUER_PROFILE_VERSION"
PROFILE_DIGEST_ENV = "STOCK_TWSE_ISSUER_PROFILE_DIGEST"


class IssuerMemory:
    def __init__(self, *, transport=None):
        self.generation_id = str(uuid4())
        self.snapshot: tuple[bytes, bytes] | None = None
        self.capture_lock = Lock()
        self.attempted = False
        self.failure_reason: str | None = None
        self.failure_receipt: bytes | None = None
        self.failure_original: tuple[bytes, bytes] | None = None
        self.transport = transport


MEMORY_ISSUERS = IssuerMemory()


def profile_policy() -> dict:
    return json.loads(json.dumps(_POLICY))


def _today_taipei() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def _safe_failure(exc: Exception) -> str:
    reason = str(exc) if isinstance(exc, consumer.IssuerCaptureError) else "issuer_evidence_invalid"
    return reason if re.fullmatch(r"[a-z_]+(?::[a-z_0-9]+)?", reason) else "issuer_evidence_invalid"


def _result(exchange: str, symbol: str, as_of: date | None, memory: IssuerMemory) -> dict:
    return {"version": VERSION, "status": "unavailable", "reasons": [], "exchange": exchange, "symbol": symbol,
            "as_of": as_of.isoformat() if type(as_of) is date else None,
            "cutoff_basis": "observed_taipei_date_inclusive", "observed_date": None,
            "capture_enabled": False, "can_capture": False,
            "capture_action": "failed" if memory.failure_reason else "not_attempted",
            "attempted": memory.attempted, "busy": memory.capture_lock.locked(), "cache_present": memory.snapshot is not None,
            "storage": "memory_only", "durable_capture": False, "historical_pit": "unsupported",
            "published_time": "unknown", "first_availability": "unknown", "revision_history": "unknown",
            "classification": "unsupported", "feed_status": "unavailable", "profile_present": None,
            "candidate_count": None, "row": None, "provenance": None, "attribution": None,
            "policy": {"version": VERSION, "digest": POLICY_DIGEST, "profile": consumer.PROFILE},
            "limitations": ["selected_issuer_identity_only", "not_ordinary_or_etf_classification", "raw_industry_not_sector_mapping",
                            "observed_date_not_publication", "not_historical_pit", "no_price_or_financial_inference"]}


def _gate(result: dict, environment: Mapping[str, str] | None) -> bool:
    config = os.environ if environment is None else environment
    if config.get(CAPTURE_ENV) != "1":
        result["reasons"] = ["issuer_capture_not_enabled"]
        return False
    result["capture_enabled"] = True
    if result["exchange"] != "TWSE" or result["symbol"] not in consumer.SYMBOLS:
        result["reasons"] = ["issuer_symbol_not_supported"]
        return False
    if result["as_of"] is None:
        result["reasons"] = ["issuer_shared_cutoff_missing"]
        return False
    expected = ((REGISTRY_VERSION_ENV, consumer.REGISTRY_VERSION), (REGISTRY_DIGEST_ENV, consumer.REGISTRY_DIGEST),
                (PROFILE_VERSION_ENV, VERSION), (PROFILE_DIGEST_ENV, POLICY_DIGEST))
    policy_digest = "sha256:" + hashlib.sha256(json.dumps(_POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if policy_digest != POLICY_DIGEST or any(config.get(key) != value for key, value in expected):
        result["reasons"] = ["issuer_external_policy_pins_mismatch"]
        return False
    return True


def _summary(memory: IssuerMemory, environment: Mapping[str, str] | None) -> dict:
    config = os.environ if environment is None else environment
    return consumer.summarize_memory(*memory.snapshot, expected_registry_version=config[REGISTRY_VERSION_ENV],
                                     expected_digest=config[REGISTRY_DIGEST_ENV], generation_id=memory.generation_id)


def _event_gate(events: dict | None, symbol: str, as_of: str) -> bool:
    return (type(events) is dict and events.get("status") == "available" and events.get("as_of") == as_of
            and any(row.get("exchange") == "TWSE" and row.get("symbol") == symbol for row in events.get("rows", [])))


def _project(result: dict, summary: dict, events: dict | None) -> dict:
    provenance = summary["provenance"]
    observed = (consumer.timestamp(provenance["captured_at"]) + timedelta(hours=8)).date().isoformat()
    result.update(observed_date=observed, feed_status="available", candidate_count=summary["candidate_count"])
    if observed > result["as_of"]:
        result.update(feed_status="unavailable", candidate_count=None, reasons=["issuer_observation_after_cutoff"])
        return result
    row = summary["selected"].get(result["symbol"])
    result["profile_present"] = row is not None
    if row is None:
        result["reasons"] = ["issuer_symbol_absent_from_valid_feed"]
        return result
    if not _event_gate(events, result["symbol"], result["as_of"]):
        result["reasons"] = ["issuer_same_cutoff_event_unavailable"]
        return result
    names = [event["company_name"] for event in events["rows"] if event["symbol"] == result["symbol"]]
    if any(name not in (row["full_name"], row["short_name"]) for name in names):
        # Retain both original sources in their stores; do not publish a joined identity.
        result["reasons"] = ["issuer_event_name_conflict"]
        return result
    result.update(status="available", row={**row, "event_names": names,
                                           "body_sha256": provenance["body_sha256"], "receipt_sha256": provenance["receipt_sha256"]},
                  provenance=provenance, attribution=summary["attribution"], can_capture=True)
    return result


def build_issuer_profile(exchange: str, symbol: str, as_of: date | None, *, events: dict | None,
                         environment: Mapping[str, str] | None = None, store: IssuerMemory | None = None) -> dict:
    memory = MEMORY_ISSUERS if store is None else store
    result = _result(exchange, symbol, as_of, memory)
    if not _gate(result, environment):
        return result
    if memory.snapshot is None:
        result.update(reasons=[memory.failure_reason or "issuer_memory_capture_missing"],
                      can_capture=not memory.attempted and as_of >= _today_taipei()
                      and _event_gate(events, symbol, result["as_of"]))
        return result
    result["capture_action"] = "cached"
    try:
        return _project(result, _summary(memory, environment), events)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        result["reasons"] = [_safe_failure(exc)]
        return result


def capture_issuer_profile(exchange: str, symbol: str, as_of: date | None, *, events: dict | None,
                           environment: Mapping[str, str] | None = None, store: IssuerMemory | None = None) -> dict:
    memory = MEMORY_ISSUERS if store is None else store
    result = _result(exchange, symbol, as_of, memory)
    if not _gate(result, environment):
        return result
    if not memory.capture_lock.acquire(blocking=False):
        result.update(busy=True, reasons=["issuer_capture_in_progress"])
        return result
    try:
        if memory.snapshot is not None:
            return build_issuer_profile(exchange, symbol, as_of, events=events, environment=environment, store=memory)
        if memory.attempted:
            result.update(capture_action="failed", reasons=[memory.failure_reason or "issuer_capture_failed"])
            return result
        if as_of < _today_taipei() or not _event_gate(events, symbol, result["as_of"]):
            result["reasons"] = ["issuer_current_cutoff_event_required"]
            return result
        memory.attempted = True
        result["attempted"] = True
        config = os.environ if environment is None else environment
        def hold_failed_original(body: bytes, receipt: bytes) -> None:
            memory.failure_original = (body, receipt)
        body, receipt = consumer.capture_memory(expected_registry_version=config[REGISTRY_VERSION_ENV],
                                                expected_digest=config[REGISTRY_DIGEST_ENV],
                                                generation_id=memory.generation_id, transport=memory.transport,
                                                failure_original_sink=hold_failed_original)
        if body is None:
            memory.failure_receipt = receipt
            memory.failure_reason = _safe_failure(consumer.IssuerCaptureError(consumer.strict_json(receipt).get("error_reason") or "issuer_capture_failed"))
            result.update(capture_action="failed", reasons=[memory.failure_reason])
            return result
        summary = consumer.summarize_memory(body, receipt, expected_registry_version=config[REGISTRY_VERSION_ENV],
                                            expected_digest=config[REGISTRY_DIGEST_ENV], generation_id=memory.generation_id)
        memory.snapshot = (body, receipt)
        result.update(cache_present=True, capture_action="acquired")
        return _project(result, summary, events)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        memory.failure_reason = _safe_failure(exc)
        result.update(capture_action="failed", reasons=[memory.failure_reason])
        return result
    finally:
        memory.capture_lock.release()
