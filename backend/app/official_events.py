"""Explicit TWT48U acquisition and read-only, process-memory event projection.

Import and overview reads never fetch. One successful selected capture publishes
one immutable bytes pair for this process; changing the observation requires a
restart. The cutoff gates observation in Taipei, never the effective date or
historical availability. No DB, filesystem mutation or financial inference.
"""
from __future__ import annotations

from datetime import date, timedelta
import os
from pathlib import Path
import re
from threading import Lock
from typing import Mapping

from worker import twse_action_capture as consumer
from worker.source_runtime import capture_memory

VERSION = "official-events/p3b-v1"
CAPTURE_ENV = "STOCK_TWSE_EVENTS_MEMORY_CAPTURE"
PINS = {
    "manifest": Path(__file__).resolve().parents[1] / "worker" / "source_registry.json",
    "profile": "free_public_local",
    "expected_registry_version": "r1-a1-c009-2026-09-12.1",
    "expected_digest": "sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b",
}


class OfficialEventMemory:
    """A bounded single feed, published atomically only after selected validation."""
    def __init__(self):
        self.snapshot: tuple[bytes, bytes] | None = None
        self.capture_lock = Lock()


MEMORY_EVENTS = OfficialEventMemory()


def _result(as_of: date | None) -> dict:
    return {
        "version": VERSION, "status": "unavailable", "reasons": [],
        "as_of": as_of.isoformat() if type(as_of) is date else None,
        "cutoff_basis": "observed_taipei_date_inclusive", "observed_date": None,
        "capture_enabled": False, "can_capture": False, "capture_action": "not_attempted",
        "cache_present": False, "storage": "memory_only", "durable_capture": False,
        "historical_pit": "unsupported", "source_url_kind": "feed",
        "published_time": "unknown", "first_availability": "unknown", "revision_history": "unknown",
        "rows": [], "provenance": None, "attribution": None,
        "limitations": ["local_evidence_consistency_only", "selected_events_only", "not_complete_history",
                        "future_effective_dates_retained", "not_historical_as_of", "not_latest_feed",
                        "financial_values_not_validated", "no_price_impact_inference"],
    }


def _gate(result: dict, exchange: str, symbol: str, environment: Mapping[str, str] | None) -> bool:
    config = os.environ if environment is None else environment
    enabled = config.get(CAPTURE_ENV)
    if enabled != "1":
        result["reasons"] = ["event_capture_not_enabled" if enabled is None or enabled == "" else "event_capture_configuration_invalid"]
        return False
    result["capture_enabled"] = True
    if exchange != "TWSE":
        result["reasons"] = ["event_exchange_not_supported"]
        return False
    if not isinstance(symbol, str) or re.fullmatch(r"[0-9A-Z]{4,6}", symbol) is None:
        result["reasons"] = ["event_invalid_symbol"]
        return False
    result["can_capture"] = True
    return True


def _safe_failure(exc: Exception) -> str:
    # Consumer reasons contain only defined tokens, a purpose or validated code.
    # Registry/OS messages may contain internal paths; never expose those.
    reason = str(exc) if isinstance(exc, consumer.ActionCaptureError) else "event_evidence_invalid"
    return reason if re.fullmatch(r"[a-z_]+(?::(?:[a-z_]+|[0-9A-Z]{4,6}))?", reason) else "event_evidence_invalid"


def _summary(snapshot: tuple[bytes, bytes], symbol: str) -> dict:
    return consumer.summarize_memory_capture(*snapshot, **PINS, symbols=[symbol])


def _project(result: dict, summary: dict, as_of: date | None) -> dict:
    observed = (consumer._timestamp(summary["provenance"]["captured_at"]) + timedelta(hours=8)).date()
    result.update(observed_date=observed.isoformat(), cache_present=True)
    if type(as_of) is not date:
        result["reasons"] = ["event_shared_cutoff_missing"]
        return result
    if observed > as_of:
        result["reasons"] = ["event_observation_after_cutoff"]
        return result
    # Only identity, effective-date classification and traceability are exposed.
    # Unvalidated dividend/allotment/reference-price strings stay in raw bytes.
    fields = ("exchange", "symbol", "company_name", "event_date", "source_date", "event_date_role",
              "event_date_precision", "kind", "label", "row_ordinal", "published_at", "first_available_at",
              "revision_available_at", "availability")
    result.update(status="available", rows=[{**{key: row[key] for key in fields},
                                            "source_classification": row["source_row"]["Exdividend"]}
                                           for row in summary["rows"]],
                  provenance=summary["provenance"], attribution=summary["attribution"],
                  candidate_count=summary["candidate_count"], selected_count=summary["selected_count"],
                  validation_scope=summary["validation_scope"], summarize_decision=summary["summarize_decision"],
                  runtime_condition_receipts=summary["runtime_condition_receipts"],
                  summary_condition_receipts=summary["summary_condition_receipts"])
    return result


def build_official_events(exchange: str, symbol: str, as_of: date | None, *,
                          environment: Mapping[str, str] | None = None,
                          store: OfficialEventMemory | None = None) -> dict:
    """Revalidate the held original bytes, with zero fetches or persistent cache."""
    result = _result(as_of)
    if not _gate(result, exchange, symbol, environment):
        return result
    snapshot = (MEMORY_EVENTS if store is None else store).snapshot
    if snapshot is None:
        result["reasons"] = ["event_memory_capture_missing"]
        return result
    result["capture_action"] = "cached"
    try:
        return _project(result, _summary(snapshot, symbol), as_of)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        result.update(cache_present=True, reasons=[_safe_failure(exc)])
        return result


def capture_official_events(exchange: str, symbol: str, as_of: date | None, *,
                            environment: Mapping[str, str] | None = None,
                            store: OfficialEventMemory | None = None) -> dict:
    """Only the explicit POST invokes this; a held feed is never refreshed."""
    result = _result(as_of)
    if not _gate(result, exchange, symbol, environment):
        return result
    memory = MEMORY_EVENTS if store is None else store
    if not memory.capture_lock.acquire(blocking=False):
        result["reasons"] = ["event_capture_in_progress"]
        return result
    try:
        if memory.snapshot is not None:
            return build_official_events(exchange, symbol, as_of, environment=environment, store=memory)
        # The summarize purpose is checked before the one allowed GET as in P3a.
        consumer._symbols([symbol])
        consumer._admission(**PINS)
        body, receipt_bytes = capture_memory(**PINS, source_id=consumer.SOURCE_ID)
        if body is None:
            receipt = consumer._json(receipt_bytes)
            reason = receipt.get("error_reason")
            safe = reason if isinstance(reason, str) and re.fullmatch(r"(?:http_status:[0-9]{3}|[a-z_]+)", reason) else "event_capture_failed"
            result.update(capture_action="failed", reasons=[safe])
            return result
        snapshot = (body, receipt_bytes)
        summary = _summary(snapshot, symbol)
        # No assignment on a failed/missing selection, and no prior success fallback.
        memory.snapshot = snapshot
        result["capture_action"] = "acquired"
        return _project(result, summary, as_of)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        result.update(capture_action="failed", reasons=[_safe_failure(exc)])
        return result
    finally:
        memory.capture_lock.release()
