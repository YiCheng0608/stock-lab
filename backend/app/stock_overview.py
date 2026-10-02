"""Read-only, date-cutoff research overview for the first M1 delivery.

Prices require a selected STOCK_DAY_ALL row and matching local capture evidence.
This proves local consistency, not origin authentication or historical availability.
No request, normalization write, strategy evaluation, or calendar inference occurs.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
import os
from pathlib import Path
import stat
from typing import Any

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from worker.source_registry import MIN_CONDITIONS, decide_policy, load_manifest
from worker.source_runtime import DEADLINE_SECONDS, MAX_BODY_BYTES, TIMEOUT_SECONDS
from worker.stock_day_capture import (
    ENDPOINT, MAX_RECEIPT_BYTES, SOURCE_ID, _json, _rows,
    _select_validated_rows, _timestamp,
)
from worker.stock_day_evidence import _assert_binding, _checked_path, _identity, _same_json

from .models import (ChipSnapshot, CorporateAction, Event, FundamentalSnapshot, IngestionRun,
                     Instrument, MarketBar, NewsItem, RawPayload, Signal, StrategyVersion, TechnicalFeature)
from .institutional_daily import build_institutional_daily
from .official_events import build_official_events

OVERVIEW_VERSION = "stock-overview/p3b-v1"
REGISTRY_VERSION = "r1-a1-c009-2026-09-12.1"
REGISTRY_DIGEST = "sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "worker" / "source_registry.json"
PROFILE = "free_public_local"


class OverviewEvidenceError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise OverviewEvidenceError(reason)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def resolve_stock_cutoff(db: Session, instrument: Instrument, requested: date | None) -> date | None:
    """Default to the latest stored data date; an explicit date is never advanced."""
    if requested is not None:
        return requested
    latest_bar = db.scalar(select(func.max(MarketBar.trading_date)).where(MarketBar.instrument_id == instrument.id))
    if latest_bar is not None:
        return latest_bar
    # A stock with no prices may still have independent research records.
    # Their stored dates supply a common date cutoff without upgrading their source status.
    observed_dates = [db.scalar(select(func.max(field)).where(model.instrument_id == instrument.id))
                      for model, field in ((ChipSnapshot, ChipSnapshot.trading_date),
                                           (TechnicalFeature, TechnicalFeature.trading_date),
                                           (Signal, Signal.signal_date), (Event, Event.event_date),
                                           (CorporateAction, CorporateAction.action_date),
                                           (FundamentalSnapshot, func.coalesce(FundamentalSnapshot.announcement_date, FundamentalSnapshot.period_end))) ]
    related_news = (select(NewsItem).outerjoin(Event, NewsItem.event_id == Event.id)
                    .where(NewsItem.status == "active", NewsItem.time_consistency == "verified",
                           or_(Event.instrument_id == instrument.id,
                               and_(NewsItem.event_id.is_(None), NewsItem.symbols_json.contains([instrument.symbol])))))
    # Publication takes precedence over a future announced event date. UTC-naive
    # storage is the existing app.news writer contract, not inferred availability.
    for item in db.scalars(related_news).all():
        instant = item.published_at or item.event_at
        if instant is not None:
            observed_dates.append((_utc_from_persisted(instant) + timedelta(hours=8)).date())
        else:
            event = db.get(Event, item.event_id) if item.event_id else None
            observed_dates.append(item.event_date or (event.event_date if event else None))
    return max((day for day in observed_dates if day is not None), default=None)


def _utc_from_persisted(value: datetime | None) -> datetime | None:
    # The existing ingestion writer persists capture UTC without tzinfo.
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _stable_read(bound, limit: int) -> bytes:
    """Bounded double read with path and handle identity checked separately.

    Windows stat/fstat can expose different legacy ctime meanings. Compare their
    shared file identity fields, while requiring each API's full identity to stay
    unchanged throughout the read. No filesystem mutation or cross-request cache.
    """
    _assert_binding(bound)
    before = bound.path.stat()
    _require(before.st_size <= limit, bound.kind + "_size_limit")
    with bound.path.open("rb") as source:
        opened = os.fstat(source.fileno())
        _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1, bound.kind + "_path_alias")
        def shared(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)
        _require(shared(before) == shared(opened), bound.kind + "_changed")
        first = source.read(limit + 1)
        source.seek(0)
        second = source.read(limit + 1)
        closed = os.fstat(source.fileno())
    after = bound.path.stat()
    _require(_identity(before) == _identity(after) == bound.identity
             and _identity(opened) == _identity(closed) and shared(closed) == shared(after)
             and len(first) == before.st_size and len(first) <= limit and first == second, bound.kind + "_changed")
    _assert_binding(bound)
    return first


def _capture_evidence(raw: RawPayload, run: IngestionRun | None, manifest: dict) -> dict:
    _require(raw.source == "twse" and raw.endpoint == ENDPOINT, "price_source_not_admitted")
    _require(run is not None and run.source == "official" and run.run_type in {"collect", "backfill"}
             and run.status in {"success", "partial", "skipped"}, "price_ingestion_provenance_missing")
    _require(bool(raw.payload_path) and bool(raw.sha256), "price_raw_evidence_missing")
    body_bound = _checked_path(raw.payload_path, "body", name="body.bin", external=True)
    receipt_bound = _checked_path(body_bound.path.with_name("receipt.json"), "receipt", name="receipt.json", external=True)
    body = _stable_read(body_bound, MAX_BODY_BYTES)
    receipt_bytes = _stable_read(receipt_bound, MAX_RECEIPT_BYTES)
    digest = hashlib.sha256(body).hexdigest()
    _require(raw.sha256 == digest, "price_body_hash_mismatch")
    receipt = _json(receipt_bytes)
    _require(type(receipt) is dict, "price_receipt_invalid")
    source = next(item for item in manifest["sources"] if item["source_id"] == SOURCE_ID)
    decisions = {}
    for purpose in ("local_fetch", "raw_store", "summarize"):
        decision = decide_policy(manifest, SOURCE_ID, purpose, profile=PROFILE, endpoint=ENDPOINT, method="GET")
        _require(decision.allowed and set(decision.conditions) == MIN_CONDITIONS[purpose], "price_purpose_not_admitted")
        decisions[purpose] = decision.to_dict()
    expected = {
        "schema_version": "source-capture/v1", "status": "capture_complete", "source_id": SOURCE_ID,
        "endpoint": ENDPOINT, "method": "GET", "source_version": source["source_version"],
        "profile": PROFILE, "registry_version": REGISTRY_VERSION, "manifest_digest": REGISTRY_DIGEST,
        "body_sha256": digest, "body_bytes": len(body), "executed_purposes": ["local_fetch", "raw_store"],
        "policy_decisions": {key: decisions[key] for key in ("local_fetch", "raw_store")},
        "historical_pit": "unsupported", "request_count": 1, "error_reason": None,
        "rate_limit_verified": False, "documented_numeric_rate_limit": "unknown",
        "rate_limit_scope": "one invocation; no cross-process enforcement", "rate_limit_evidence": source["access"]["rate_limit"],
    }
    _require(all(_same_json(receipt.get(key), value) for key, value in expected.items()), "price_receipt_mismatch")
    _require(type(receipt.get("http_status")) is int and 200 <= receipt["http_status"] < 300, "price_receipt_http_invalid")
    attribution = {
        "owner": source["owner"], "dataset_id": source["dataset_id"], "source_id": SOURCE_ID,
        "source_url": ENDPOINT, "terms": source["access"]["documented_terms"], "evidence": source["evidence"],
        "purpose_evidence": {key: source["purposes"][key]["evidence"] for key in ("local_fetch", "raw_store")},
    }
    _require(_same_json(receipt.get("attribution"), attribution), "price_attribution_mismatch")
    conditions = {
        "attribute_source": {"artifact": "receipt.json:attribution"},
        "preserve_source_integrity": {"artifact": "body.bin", "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding"},
        "bounded_requests": {"max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS,
                             "cooperative_deadline_seconds": DEADLINE_SECONDS,
                             "deadline_scope": "checked between streamed chunks; not a hard total deadline", "max_body_bytes": MAX_BODY_BYTES},
        "respect_endpoint_limits": {"strategy": "single_get_stop_on_response", "retries": 0, "redirects": 0,
                                    "warmup_requests": 0, "numeric_quota_verified": False},
    }
    _require(_same_json(receipt.get("condition_receipts"), conditions), "price_conditions_mismatch")
    started, captured = _timestamp(receipt.get("request_started_at")), _timestamp(receipt.get("captured_at"))
    _require(started <= captured and _utc_from_persisted(raw.collected_at) == captured, "price_capture_time_mismatch")
    rows, day = _rows(body)
    _require(raw.data_as_of == day.isoformat(), "price_raw_date_mismatch")
    # Recheck both bindings after parsing; never persist an evidence cache across requests.
    _require(_stable_read(body_bound, MAX_BODY_BYTES) == body
             and _stable_read(receipt_bound, MAX_RECEIPT_BYTES) == receipt_bytes, "price_evidence_changed")
    return {"rows": rows, "date": day, "receipt": receipt,
            "provenance": {"raw_payload_id": raw.id, "ingestion_run_id": raw.ingestion_run_id,
                           "source_id": SOURCE_ID, "source_version": source["source_version"], "endpoint": ENDPOINT,
                           "body_sha256": digest, "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                           "registry_version": REGISTRY_VERSION, "manifest_digest": REGISTRY_DIGEST,
                           "captured_at": receipt["captured_at"], "raw_collected_at": raw.collected_at.isoformat(),
                           "license": source["retention"]["raw_store"], "summarize_decision": decisions["summarize"],
                           "verification": "local_evidence_consistent"}}


def _qualified_price(row: MarketBar, instrument: Instrument, evidence: dict) -> dict:
    _require(instrument.exchange == "TWSE" and row.source == "twse", "price_source_not_admitted")
    _require(row.trading_date == evidence["date"] and row.instrument_id == instrument.id, "price_identity_date_mismatch")
    _require(not row.is_suspended, "price_suspended")
    prices = [row.open, row.high, row.low, row.close]
    _require(all(_finite(value) and value > 0 for value in prices)
             and row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high, "price_invalid_ohlc")
    _require(type(row.volume) is int and 0 <= row.volume <= 9223372036854775807, "price_invalid_volume")
    records, unavailable = _select_validated_rows(evidence["rows"], evidence["date"], [instrument.symbol], evidence["provenance"]["body_sha256"])
    _require(bool(records) and not unavailable, "price_selected_row_invalid")
    selected = records[0]
    _require(all(getattr(row, key) == getattr(selected, key) for key in ("open", "high", "low", "close", "volume")), "price_selected_value_mismatch")
    _require(row.turnover_status == selected.turnover_status and row.turnover_reason == selected.turnover_reason
             and _finite(row.turnover) and row.turnover == selected.turnover, "price_turnover_state_mismatch")
    _require(row.data_as_of is not None and row.data_as_of.date() == row.trading_date, "price_data_date_mismatch")
    return {"date": row.trading_date.isoformat(), "open": row.open, "high": row.high, "low": row.low,
            "close": row.close, "volume": row.volume,
            "turnover": row.turnover if row.turnover_status == "available" else None,
            "turnover_status": row.turnover_status, "turnover_reason": row.turnover_reason,
            "source": row.source, "data_as_of": row.data_as_of.isoformat(),
            "collected_at": row.collected_at.isoformat() if row.collected_at else None,
            "provenance": evidence["provenance"]}


def build_stock_overview(db: Session, instrument: Instrument, as_of: date | None = None) -> dict:
    cutoff = resolve_stock_cutoff(db, instrument, as_of)
    query = select(MarketBar).where(MarketBar.instrument_id == instrument.id)
    query = query.where(MarketBar.trading_date <= cutoff) if cutoff else query.where(False)
    rows = list(db.scalars(query.order_by(desc(MarketBar.trading_date), desc(MarketBar.id)).limit(120)).all())
    duplicate_dates = {day for day, count in Counter(row.trading_date for row in rows).items() if count > 1}
    qualified, rejected, evidence_cache = [], [], {}
    try:
        manifest = load_manifest(MANIFEST_PATH, expected_registry_version=REGISTRY_VERSION, expected_digest=REGISTRY_DIGEST)
    except (ValueError, OSError, TypeError):
        manifest = None
    for row in reversed(rows):
        try:
            _require(row.trading_date not in duplicate_dates, "price_duplicate_date")
            _require(manifest is not None, "price_registry_pin_mismatch")
            _require(instrument.exchange == "TWSE" and row.source == "twse", "price_source_not_admitted")
            _require(row.raw_payload_id is not None, "price_raw_evidence_missing")
            if row.raw_payload_id not in evidence_cache:
                try:
                    raw = db.get(RawPayload, row.raw_payload_id)
                    _require(raw is not None, "price_raw_evidence_missing")
                    evidence_cache[row.raw_payload_id] = _capture_evidence(raw, db.get(IngestionRun, raw.ingestion_run_id) if raw.ingestion_run_id else None, manifest)
                except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
                    evidence_cache[row.raw_payload_id] = exc
            evidence = evidence_cache[row.raw_payload_id]
            if isinstance(evidence, Exception):
                raise evidence
            qualified.append(_qualified_price(row, instrument, evidence))
        except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            reason = getattr(exc, "code", None) or (str(exc) if isinstance(exc, OverviewEvidenceError) else "price_evidence_invalid")
            rejected.append({"date": row.trading_date.isoformat(), "reason": reason})
    price_reasons = list(dict.fromkeys(item["reason"] for item in rejected))
    if not rows:
        price_reasons.append("price_no_rows_before_cutoff")
    latest = qualified[-1] if qualified else None
    if latest and cutoff and latest["date"] != cutoff.isoformat():
        price_reasons.append("price_latest_before_cutoff")
    strategy_query = (select(Signal, StrategyVersion).join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
                      .where(Signal.instrument_id == instrument.id, StrategyVersion.name.in_({"breakout_v1", "pullback_v1"})))
    strategy_query = strategy_query.where(Signal.signal_date <= cutoff) if cutoff else strategy_query.where(False)
    latest_strategies = {}
    for signal, version in db.execute(strategy_query.order_by(desc(Signal.signal_date), desc(Signal.id))).all():
        latest_strategies.setdefault(version.name, (signal, version))
    conditions = []
    for name, label in (("breakout_v1", "突破條件"), ("pullback_v1", "回踩條件")):
        pair = latest_strategies.get(name)
        reasons = ["strategy_input_sources_not_admitted", "strategy_time_evidence_not_verified", "industry_membership_not_verified"]
        if pair is None:
            reasons.append("strategy_result_missing")
        elif pair[0].signal_date != cutoff:
            reasons.append("strategy_result_before_cutoff")
        conditions.append({"strategy": name, "label": label, "version": pair[1].version if pair else None,
                           "signal_date": pair[0].signal_date.isoformat() if pair else None,
                           "status": "data_insufficient", "reasons": reasons})
    daily = build_institutional_daily(instrument.exchange, instrument.symbol, cutoff)
    return {
        "version": OVERVIEW_VERSION, "as_of": cutoff.isoformat() if cutoff else None,
        "cutoff_basis": "data_date_inclusive", "historical_pit": "unsupported",
        "scope": "M1-P3b: cutoff, traceable price, TPEx single-day institutional and memory-observed TWSE event evidence",
        "price": {"status": "available" if qualified else "unavailable", "basis": "original_api_ohlcv",
                  "window_limit": 120, "candidate_count": len(rows), "valid_count": len(qualified),
                  "from": qualified[0]["date"] if qualified else None, "to": latest["date"] if latest else None,
                  "latest": latest, "bars": qualified, "rejected": rejected, "reasons": price_reasons},
        "institutional": {"status": "unavailable", "horizons": [5, 20],
                          "investors": ["foreign", "trust", "dealer"], "values": None,
                          "reasons": (["multi_session_institutional_evidence_missing", "trading_session_source_not_admitted"]
                                      if daily["status"] == "available" else
                                      ["institutional_sources_not_admitted", "trading_session_source_not_admitted"])},
        "institutional_daily": daily,
        "conditions": conditions,
        "events": build_official_events(instrument.exchange, instrument.symbol, cutoff),
        "limitations": ["local_evidence_consistency_only", "adjustment_chain_not_provided", "complete_m1_not_delivered"],
    }
