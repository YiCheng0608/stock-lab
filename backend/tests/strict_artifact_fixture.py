from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from app.atr import calculate_atr14


UTC = timezone.utc
INSTRUMENT = {"exchange": "TWSE", "symbol": "2330", "legacy_reference": "legacy:technical:2330"}
START = date(2026, 1, 2)
DATES = tuple(START + timedelta(days=index) for index in range(16))
MARKET_DATE = DATES[-1]
SNAPSHOT_ID = "bars-snapshot-1"


def fixture_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


SNAPSHOT_HASH = fixture_hash("bars-snapshot-1")
DECISION_A = datetime(2026, 1, 31, 8, tzinfo=UTC)
DECISION_B = datetime(2026, 2, 1, 8, tzinfo=UTC)
WINDOW = {
    "start_date": DATES[0].isoformat(),
    "end_date": DATES[-1].isoformat(),
    "terminal_market_date": MARKET_DATE.isoformat(),
}


def make_artifact(*, decision_at: datetime = DECISION_A, snapshot_id: str = SNAPSHOT_ID):
    bars = [
        {
            "trading_date": trading_date,
            "open": 100 + index,
            "high": 105 + index,
            "low": 100 + index,
            "close": 102 + index,
            "price_basis": "raw_v1",
            "data_available_at": datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC),
        }
        for index, trading_date in enumerate(DATES)
    ]
    return calculate_atr14(
        bars,
        price_basis="raw_v1",
        input_snapshot_ref=snapshot_id,
        expected_sessions=DATES,
        decision_at=decision_at,
        true_sequence_start=True,
        corporate_action_coverage="complete",
        corporate_action_source_ref="fixture://actions/v1",
        corporate_action_available_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _snapshot(identifier: str, digest: str, source_ref: str) -> dict[str, str]:
    return {
        "id": identifier,
        "hash": digest,
        "hash_algorithm": "sha256",
        "source_ref": source_ref,
    }


def _available(at: datetime) -> dict[str, str]:
    return {"status": "available", "available_at": at.isoformat()}


def _config(artifact) -> dict[str, object]:
    return {
        "algorithm": artifact.algorithm,
        "period": artifact.period,
        "smoothing": "wilder",
        "seed": "simple_mean",
        "precision": "float64",
    }


def _basis_digest() -> str:
    payload = {
        "price_basis": "raw_v1",
        "version": "price-basis/raw-v1",
        "source_ref": "fixture://basis/raw-v1",
        "evidence_ref": "fixture://basis-evidence/1",
        "scope": WINDOW,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_provenance(artifact=None, *, source_id: str = SNAPSHOT_ID, source_hash: str = SNAPSHOT_HASH):
    artifact = artifact or make_artifact()
    source_snapshot = _snapshot(source_id, source_hash, "fixture://bars/snapshot")
    instrument_snapshot = _snapshot("instrument-snapshot-1", fixture_hash("instrument-snapshot-1"), "fixture://instrument")
    calendar_snapshot = _snapshot("calendar-snapshot-1", fixture_hash("calendar-snapshot-1"), "fixture://calendar")
    halt_snapshot = _snapshot("halt-snapshot-1", fixture_hash("halt-snapshot-1"), "fixture://halts")
    action_snapshot = _snapshot("action-snapshot-1", fixture_hash("action-snapshot-1"), "fixture://actions")
    config = _config(artifact)
    config_digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source_rows = [
        {
            "sequence_position": index,
            "row_ref": f"fixture://bars/{index + 1}",
            "market_date": trading_date.isoformat(),
            "market_session": f"TWSE-{trading_date.isoformat()}",
            "snapshot_id": source_id,
            "price_basis": artifact.price_basis,
            "row_status": "bar",
            "availability": _available(datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC)),
        }
        for index, trading_date in enumerate(DATES)
    ]
    sessions = [
        {
            "sequence_position": index,
            "session_date": trading_date.isoformat(),
            "session_ref": f"fixture://calendar/session/{trading_date.isoformat()}",
            "snapshot_id": calendar_snapshot["id"],
            "source_ref": "fixture://calendar",
            "status": "open",
            "availability": _available(datetime(2026, 1, 1, tzinfo=UTC)),
        }
        for index, trading_date in enumerate(DATES)
    ]
    halt_statuses = [
        {
            "sequence_position": index,
            "session_date": trading_date.isoformat(),
            "session_ref": f"fixture://halts/session/{trading_date.isoformat()}",
            "snapshot_id": halt_snapshot["id"],
            "source_ref": "fixture://halts",
            "status": "no_halt",
            "availability": _available(datetime(2026, 1, 1, tzinfo=UTC)),
        }
        for index, trading_date in enumerate(DATES)
    ]
    manifest_digest = hashlib.sha256(b"[]").hexdigest()
    return {
        "contract": {
            "name": "atr-provenance",
            "version": 2,
            "id": "atr-provenance/v2",
            "mode": "caller_provided_only",
        },
        "feature": {"name": "atr14", "version": artifact.feature_version},
        "instrument": {
            "exchange": INSTRUMENT["exchange"],
            "symbol": INSTRUMENT["symbol"],
            "legacy_reference": INSTRUMENT["legacy_reference"],
            "validation_status": "caller_supplied_only",
            "source_identity": {"type": "fixture_instrument_id", "value": "instrument-2330"},
            "source": {
                "source_ref": "fixture://instrument",
                "snapshot": instrument_snapshot,
            },
        },
        "source": {
            "source_ref": "fixture://bars",
            "version": "bars/v1",
            "snapshot": source_snapshot,
            "coverage_window": WINDOW,
            "ordered_source_rows": source_rows,
            "availability": _available(datetime(2026, 1, 30, 8, tzinfo=UTC)),
        },
        "algorithm": {
            "name": artifact.algorithm,
            "version": "wilder/v1",
            "period": artifact.period,
            "smoothing": "wilder",
            "seed": "simple_mean",
            "precision": "float64",
            "config": config,
            "config_digest": config_digest,
            "implementation": {
                "name": "taiwan-stock-research.atr",
                "version": "atr-v2",
                "digest": fixture_hash("atr-implementation-v1"),
                "digest_algorithm": "sha256",
                "source_ref": "fixture://implementation/atr.py",
            },
        },
        "basis": {
            "price_basis": artifact.price_basis,
            "version": "price-basis/raw-v1",
            "source_ref": "fixture://basis/raw-v1",
            "evidence_ref": "fixture://basis-evidence/1",
            "scope": WINDOW,
            "digest": _basis_digest(),
            "availability": _available(datetime(2026, 1, 1, tzinfo=UTC)),
        },
        "calendar": {
            "version": "twse-calendar/v1",
            "calendar_ref": "twse-calendar/v1",
            "source_ref": "fixture://calendar",
            "snapshot": calendar_snapshot,
            "coverage_window": WINDOW,
            "availability": _available(datetime(2026, 1, 1, tzinfo=UTC)),
        },
        "sessions": {
            "version": "twse-sessions/v1",
            "session_ref": "twse-sessions/v1",
            "source_ref": "fixture://calendar",
            "snapshot": calendar_snapshot,
            "coverage_window": WINDOW,
            "ordered_sessions": sessions,
            "availability": _available(datetime(2026, 1, 1, tzinfo=UTC)),
        },
        "halts": {
            "version": "twse-halts/v1",
            "halt_ref": "twse-halts/v1",
            "source_ref": "fixture://halts",
            "snapshot": halt_snapshot,
            "coverage_window": WINDOW,
            "session_statuses": halt_statuses,
            "availability": _available(datetime(2026, 1, 1, tzinfo=UTC)),
        },
        "previous_close": {
            "selection_status": "not_used",
            "reason": "true_sequence_start_proven_by_caller",
            "candidates": [],
        },
        "company_actions": {
            "manifest": [],
            "digest": manifest_digest,
            "coverage": "complete",
            "coverage_proof": "complete_none",
            "no_actions_reason": "caller_complete_none_for_fixture_window",
            "missing_or_unknown": [],
            "coverage_window": WINDOW,
            "source": {
                "source_ref": "fixture://actions",
                "version": "actions/v1",
                "snapshot": action_snapshot,
            },
            "availability": _available(datetime(2026, 1, 1, tzinfo=UTC)),
        },
    }
