"""Explicit TWT48U acquisition and read-only, process-memory event projection.

Import and overview reads never fetch. One successful explicit capture publishes
one immutable bytes pair for this process; changing the observation requires a
restart. The cutoff gates observation in Taipei, never the effective date or
historical availability. No DB, filesystem mutation or financial inference.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
from threading import Lock
from typing import Mapping

from worker import twse_action_capture as consumer
from worker.source_runtime import capture_memory

VERSION = "official-events/p3b-v1"
FOCUS_VERSION = "official-event-focus/p3-v1"
FOCUS_LIMIT = 100
CAPTURE_ENV = "STOCK_TWSE_EVENTS_MEMORY_CAPTURE"
PINS = {
    "manifest": Path(__file__).resolve().parents[1] / "worker" / "source_registry.json",
    "profile": "free_public_local",
    "expected_registry_version": "r1-a1-c009-2026-09-12.1",
    "expected_digest": "sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b",
}


class OfficialEventMemory:
    """A bounded single feed, published atomically after its consumer validation."""
    def __init__(self):
        self.snapshot: tuple[bytes, bytes] | None = None
        self.capture_lock = Lock()
        self.attempted = False
        self.failure_reason: str | None = None


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


def canonical_event_date(value: str) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("event_date_not_canonical")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("event_date_not_canonical")
    return parsed


def effective_range(from_date: str | None, to_date: str | None) -> tuple[str | None, str | None]:
    for value in (from_date, to_date):
        if value is not None:
            canonical_event_date(value)
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("event_effective_range_reversed")
    return from_date, to_date


def _missing(result: dict, memory: OfficialEventMemory) -> dict:
    result.update(reasons=[memory.failure_reason or "event_memory_capture_missing"],
                  can_capture=result["can_capture"] and not memory.attempted)
    if memory.failure_reason:
        result["capture_action"] = "failed"
    return result


def _failed(result: dict, memory: OfficialEventMemory, reason: str) -> dict:
    if memory.attempted and memory.snapshot is None:
        memory.failure_reason = reason
    result.update(capture_action="failed", reasons=[reason], can_capture=False)
    return result


def _http_failure(receipt_bytes: bytes) -> str:
    reason = consumer._json(receipt_bytes).get("error_reason")
    return reason if isinstance(reason, str) and re.fullmatch(r"(?:http_status:[0-9]{3}|[a-z_]+)", reason) else "event_capture_failed"


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
    memory = MEMORY_EVENTS if store is None else store
    snapshot = memory.snapshot
    if snapshot is None:
        return _missing(result, memory)
    result["capture_action"] = "cached"
    try:
        return _project(result, _summary(snapshot, symbol), as_of)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        result.update(cache_present=True, can_capture=False, reasons=[_safe_failure(exc)])
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
        result.update(can_capture=False, reasons=["event_capture_in_progress"])
        return result
    try:
        if memory.snapshot is not None:
            return build_official_events(exchange, symbol, as_of, environment=environment, store=memory)
        if memory.attempted:
            return _missing(result, memory)
        # The summarize purpose is checked before the one allowed GET as in P3a.
        consumer._symbols([symbol])
        consumer._admission(**PINS)
        memory.attempted = True
        body, receipt_bytes = capture_memory(**PINS, source_id=consumer.SOURCE_ID)
        if body is None:
            return _failed(result, memory, _http_failure(receipt_bytes))
        snapshot = (body, receipt_bytes)
        consumer.summarize_memory_feed(*snapshot, **PINS)
        summary = _summary(snapshot, symbol)
        # No assignment on a failed/missing selection, and no prior success fallback.
        memory.snapshot = snapshot
        result["capture_action"] = "acquired"
        return _project(result, summary, as_of)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        return _failed(result, memory, _safe_failure(exc))
    finally:
        memory.capture_lock.release()


def _today_taipei() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def _focus_result(as_of: date | None) -> dict:
    result = _result(as_of)
    result.update(version=FOCUS_VERSION, items=[], total=0, matched=0, search_query="", displayed=0,
                  truncated=False, limit=FOCUS_LIMIT, order="symbol_lexicographic",
                  coverage="observed_feed_only", research_conditions="unknown",
                  candidate_count=0, selected_count=0, effective_from=None, effective_to=None,
                  range_event_count=0, range_matched=0)
    result.pop("rows")
    result["limitations"] = ["observed_feed_only" if value == "selected_events_only" else value
                             for value in result["limitations"]] + ["not_a_ranking", "research_conditions_unknown"]
    return result


def _focus_gate(result: dict, as_of: date | None, q: str, environment: Mapping[str, str] | None,
                from_date: str | None = None, to_date: str | None = None) -> bool:
    if not isinstance(q, str) or len(q) > 100:
        result.update(can_capture=False, reasons=["event_search_query_invalid"])
        return False
    result["search_query"] = q.strip()
    try:
        result["effective_from"], result["effective_to"] = effective_range(from_date, to_date)
    except (ValueError, TypeError):
        result.update(can_capture=False, reasons=["event_effective_range_invalid"])
        return False
    if not _gate(result, "TWSE", "0000", environment):
        return False
    if type(as_of) is not date:
        result.update(can_capture=False, reasons=["event_shared_cutoff_missing"])
        return False
    return True


def _focus_project(result: dict, summary: dict, as_of: date) -> dict:
    _project(result, summary, as_of)
    rows = result.pop("rows", [])
    # A valid held feed is reused even when observation is excluded by cutoff.
    result["can_capture"] = result["status"] == "available"
    if result["status"] != "available":
        return result
    grouped: dict[tuple[str, str], dict] = {}
    total = len({(row["exchange"], row["symbol"]) for row in rows})
    retained = [row for row in rows
                if (result["effective_from"] is None or row["event_date"] >= result["effective_from"])
                and (result["effective_to"] is None or row["event_date"] <= result["effective_to"])]
    for row in retained:
        key = (row["exchange"], row["symbol"])
        if key not in grouped:
            grouped[key] = {"exchange": row["exchange"], "symbol": row["symbol"],
                            "company_name": row["company_name"], "events": [],
                            "stock_page_available": False, "detail_url": None,
                            "research_conditions": "unknown"}
        grouped[key]["events"].append(row)
    query = result["search_query"].casefold()
    matched = {key: item for key, item in grouped.items()
               if not query or query in item["symbol"].casefold()
               or any(query in event["company_name"].casefold() for event in item["events"])}
    items = [matched[key] for key in sorted(matched, key=lambda key: (key[1], key[0]))]
    result.update(total=total, range_event_count=len(retained), range_matched=len(grouped),
                  matched=len(items), displayed=min(len(items), FOCUS_LIMIT),
                  truncated=len(items) > FOCUS_LIMIT, items=items[:FOCUS_LIMIT])
    # Rows live inside each displayed card; the uncapped raw feed is not another
    # list consumers might mistake for the bounded focus list.
    return result


def build_official_event_focus(as_of: date | None, *, q: str = "", from_date: str | None = None,
                               to_date: str | None = None,
                               environment: Mapping[str, str] | None = None,
                               store: OfficialEventMemory | None = None) -> dict:
    """Read the shared original feed without fetching or touching a database."""
    result = _focus_result(as_of)
    if not _focus_gate(result, as_of, q, environment, from_date, to_date):
        return result
    memory = MEMORY_EVENTS if store is None else store
    snapshot = memory.snapshot
    if snapshot is None:
        result["can_capture"] = as_of >= _today_taipei()
        return _missing(result, memory)
    result["capture_action"] = "cached"
    try:
        return _focus_project(result, consumer.summarize_memory_feed(*snapshot, **PINS), as_of)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        result.update(cache_present=True, can_capture=False, reasons=[_safe_failure(exc)])
        return result


def capture_official_event_focus(as_of: date | None, *, q: str = "", from_date: str | None = None,
                                 to_date: str | None = None,
                                 environment: Mapping[str, str] | None = None,
                                 store: OfficialEventMemory | None = None) -> dict:
    """Explicit first acquisition; validate the entire feed before publication."""
    result = _focus_result(as_of)
    if not _focus_gate(result, as_of, q, environment, from_date, to_date):
        return result
    memory = MEMORY_EVENTS if store is None else store
    if not memory.capture_lock.acquire(blocking=False):
        result.update(can_capture=False, reasons=["event_capture_in_progress"])
        return result
    try:
        if memory.snapshot is not None:
            return build_official_event_focus(as_of, q=q, from_date=from_date, to_date=to_date, environment=environment, store=memory)
        if memory.attempted:
            return _missing(result, memory)
        if as_of < _today_taipei():
            result.update(can_capture=False, reasons=["event_cutoff_before_current_observation"])
            return result
        consumer._admission(**PINS)
        memory.attempted = True
        body, receipt_bytes = capture_memory(**PINS, source_id=consumer.SOURCE_ID)
        if body is None:
            return _failed(result, memory, _http_failure(receipt_bytes))
        snapshot = (body, receipt_bytes)
        summary = consumer.summarize_memory_feed(*snapshot, **PINS)
        memory.snapshot = snapshot
        result["capture_action"] = "acquired"
        return _focus_project(result, summary, as_of)
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        return _failed(result, memory, _safe_failure(exc))
    finally:
        memory.capture_lock.release()
