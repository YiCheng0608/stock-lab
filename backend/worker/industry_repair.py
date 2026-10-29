"""Move pre-baseline official industry memberships into their canonical groups.

The production DB carries memberships imported before the reviewed baseline
with a wrong code -> label table (e.g. code 17 in ``Communications``) and
``valid_from`` copied from the listing date.  This repair replays the company
basic-data captures already stored in ``raw_payloads``: D0 is the Asia/Taipei
date an instrument first appears in a capture, i.e. the observation the
collector skipped.  Wrong rows are closed at ``D0 - 1`` and the canonical group
is opened from D0; nothing is deleted and no ``valid_from`` is changed.  Groups
whose label is not a current canonical label are deactivated.

Dry-run is the default.  ``apply`` validates everything before the first write,
records a receipt in ``ingestion_runs`` and is idempotent: a second run finds
nothing to change and writes nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    ThemeGroup,
)
from app.taxonomy import (
    INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE,
    INDUSTRY_DISPLAY_ZH,
    canonical_group_id,
    canonical_industry_label,
)
from worker.pipeline import (
    OFFICIAL_INDUSTRY_SOURCE,
    _benchmark_instrument,
    _calculate_group_scores,
    _effective_trading_dates,
    archive_group_score,
    ensure_official_industry_group,
)
from worker.sources import TPEX_LISTED_ENDPOINT, TWSE_LISTED_ENDPOINT, _rows, _text

REPAIR_VERSION = "industry-repair-v1"
RUN_TYPE = "industry_repair"
TAIPEI = timezone(timedelta(hours=8))
LISTED_ENDPOINTS = {"TWSE": TWSE_LISTED_ENDPOINT, "TPEx": TPEX_LISTED_ENDPOINT}
OFFICIAL_SOURCES = {OFFICIAL_INDUSTRY_SOURCE} | {
    f"{OFFICIAL_INDUSTRY_SOURCE}; exchange={exchange}" for exchange in LISTED_ENDPOINTS
}
CANONICAL_LABELS = frozenset(
    label
    for codes in INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE.values()
    for label in codes.values()
)


class IndustryRepairError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:20]))
        self.errors = errors


def _captures(db: Session) -> list[dict[str, Any]]:
    """Earliest stored row of every distinct company basic-data capture."""

    exchanges = {endpoint: exchange for exchange, endpoint in LISTED_ENDPOINTS.items()}
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    captures = []
    for raw in db.scalars(
        select(RawPayload)
        .where(RawPayload.endpoint.in_(list(exchanges)))
        .order_by(RawPayload.collected_at, RawPayload.id)
    ):
        key = (raw.endpoint, raw.sha256 or "")
        captured = (
            raw.collected_at.replace(tzinfo=timezone.utc)
            if raw.collected_at.tzinfo is None
            else raw.collected_at
        )
        if key in seen:
            # Identical content captured again: D0 stays the first date.
            seen[key]["last_observed_date"] = captured.astimezone(TAIPEI).date()
            continue
        if not raw.payload_path or not raw.sha256:
            raise IndustryRepairError(
                [f"raw_payloads({raw.id}): missing payload path or sha256"]
            )
        encoded = Path(raw.payload_path).read_bytes()
        if hashlib.sha256(encoded).hexdigest() != raw.sha256:
            raise IndustryRepairError(
                [f"raw_payloads({raw.id}): file content does not match sha256"]
            )
        exchange = exchanges[raw.endpoint]
        codes = {}
        for row in _rows(json.loads(encoded)):
            if exchange == "TWSE":
                symbol, code = (
                    _text(row, "公司代號", "Code", "證券代號"),
                    _text(row, "產業別", "Industry"),
                )
            else:
                symbol = _text(row, "SecuritiesCompanyCode", "Code", "證券代號", "代號")
                code = _text(row, "SecuritiesIndustryCode", "Industry", "產業別")
            if symbol:
                codes[symbol] = code
        captures.append(
            {
                "raw_payload_id": raw.id,
                "exchange": exchange,
                "endpoint": raw.endpoint,
                "sha256": raw.sha256,
                "captured_at_utc": captured.astimezone(timezone.utc).isoformat(),
                "observed_date": captured.astimezone(TAIPEI).date(),
                "last_observed_date": captured.astimezone(TAIPEI).date(),
                "codes": codes,
            }
        )
        seen[key] = captures[-1]
    return captures


def _official_rows(
    db: Session, instrument_id: int
) -> list[tuple[GroupMembership, ThemeGroup]]:
    rows = db.execute(
        select(GroupMembership, ThemeGroup)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(GroupMembership.instrument_id == instrument_id)
        .order_by(GroupMembership.valid_from, GroupMembership.id)
    ).all()
    return [
        (membership, group)
        for membership, group in rows
        if (
            group.group_type == "official_industry"
            or group.id.startswith("official-industry-")
        )
        and membership.source in OFFICIAL_SOURCES
    ]


def _group_label(group: ThemeGroup) -> str | None:
    prefix = "Industry · "
    label = group.name[len(prefix) :] if group.name.startswith(prefix) else None
    if label in CANONICAL_LABELS and group.id == canonical_group_id("industry", label):
        return label
    return None


def plan_repair(db: Session) -> dict[str, Any]:
    """Validate every instrument and group, returning the changes without writing."""

    captures = _captures(db)
    if not {capture["exchange"] for capture in captures} >= set(LISTED_ENDPOINTS):
        raise IndustryRepairError(
            ["no stored company basic-data capture for both TWSE and TPEx"]
        )
    observations: dict[tuple[str, str], list[tuple[date, str, int]]] = {}
    for capture in captures:
        for symbol, code in capture["codes"].items():
            observations.setdefault((capture["exchange"], symbol), []).append(
                (capture["observed_date"], code, capture["raw_payload_id"])
            )
    errors: list[str] = []
    changes: list[dict[str, Any]] = []
    labels_needed: set[str] = set()
    no_evidence: list[str] = []
    instruments = db.scalars(
        select(Instrument)
        .where(
            Instrument.instrument_type.in_(("stock", "ipo")),
            Instrument.exchange.in_(list(LISTED_ENDPOINTS)),
        )
        .order_by(Instrument.exchange, Instrument.symbol)
    ).all()
    for instrument in instruments:
        name = f"{instrument.exchange}:{instrument.symbol}"
        rows = _official_rows(db, instrument.id)
        seen = observations.get((instrument.exchange, instrument.symbol))
        if not seen:
            if any(membership.valid_to is None for membership, _group in rows):
                no_evidence.append(name)
            continue
        codes = {code for _day, code, _raw in seen}
        code = seen[0][1]
        if len(codes) != 1:
            errors.append(
                f"{name}: industry code changed between captures {sorted(codes)}"
            )
            continue
        if not (code.isascii() and code.isdigit()):
            errors.append(f"{name}: nonnumeric industry code {code!r} in capture")
            continue
        if str(instrument.industry or "").strip() != code:
            errors.append(
                f"{name}: instruments.industry {instrument.industry!r} differs from capture {code!r}"
            )
            continue
        start, evidence_raw_id = seen[0][0], seen[0][2]
        label = canonical_industry_label(instrument.exchange, code)
        target = canonical_group_id("industry", label) if label else None
        expected_source = f"{OFFICIAL_INDUSTRY_SOURCE}; exchange={instrument.exchange}"
        closes = []
        for membership, _group in rows:
            if membership.source not in {OFFICIAL_INDUSTRY_SOURCE, expected_source}:
                errors.append(
                    f"{name}: membership {membership.id} has another exchange's source"
                )
            elif membership.group_id != target and (
                membership.valid_to is None or membership.valid_to >= start
            ):
                if membership.valid_from >= start:
                    errors.append(
                        f"{name}: wrong-group membership {membership.id} starts on/after D0 {start}"
                    )
                else:
                    closes.append(membership)
        opened = None
        if target:
            labels_needed.add(label)
            own = [
                membership
                for membership, _group in rows
                if membership.group_id == target
            ]
            covered = any(
                m.valid_from <= start and (m.valid_to is None or m.valid_to >= start)
                for m in own
            )
            later = [m.valid_from for m in own if m.valid_from > start]
            if not covered:
                opened = {
                    "group_id": target,
                    "valid_from": start,
                    "valid_to": min(later) - timedelta(days=1) if later else None,
                    "source": expected_source,
                }
        if closes or opened:
            changes.append(
                {
                    "instrument_id": instrument.id,
                    "exchange": instrument.exchange,
                    "symbol": instrument.symbol,
                    "code": code,
                    "label": label,
                    "d0": start,
                    "evidence_raw_payload_id": evidence_raw_id,
                    "closes": closes,
                    "opened": opened,
                }
            )
    groups_to_create = []
    for label in sorted(labels_needed):
        group = db.get(ThemeGroup, canonical_group_id("industry", label))
        if group is None:
            groups_to_create.append(label)
        elif (
            group.name != f"Industry · {label}"
            or group.group_type != "official_industry"
            or group.definition_version != "official-v1"
            or group.source != OFFICIAL_INDUSTRY_SOURCE
        ):
            errors.append(
                f"theme_groups({group.id}): canonical industry group identity conflict"
            )
    display_updates, deactivations = [], []
    for group in db.scalars(
        select(ThemeGroup)
        .where(ThemeGroup.id.like("official-industry-%"))
        .order_by(ThemeGroup.name)
    ):
        label = _group_label(group)
        if label is None:
            if group.active:
                deactivations.append(group)
        elif group.display_name_zh != INDUSTRY_DISPLAY_ZH[label]:
            display_updates.append((group, label))
        if label in labels_needed and not group.active:
            errors.append(
                f"theme_groups({group.id}): canonical industry group is inactive"
            )
    if errors:
        raise IndustryRepairError(errors)
    return {
        "captures": captures,
        "changes": changes,
        "groups_to_create": groups_to_create,
        "display_updates": display_updates,
        "deactivations": deactivations,
        "no_evidence": no_evidence,
    }


def _summary(plan: dict[str, Any]) -> dict[str, Any]:
    changes = plan["changes"]
    return {
        "memberships_closed": sum(len(item["closes"]) for item in changes),
        "memberships_opened": sum(item["opened"] is not None for item in changes),
        "instruments_changed": len(changes),
        "instruments_changed_by_exchange": dict(
            Counter(item["exchange"] for item in changes)
        ),
        "groups_created": plan["groups_to_create"],
        "groups_deactivated": [
            f"{group.id} {group.name}" for group in plan["deactivations"]
        ],
        "display_names_updated": [
            f"{group.id} {group.display_name_zh} -> {INDUSTRY_DISPLAY_ZH[label]}"
            for group, label in plan["display_updates"]
        ],
        "open_memberships_without_capture": len(plan["no_evidence"]),
        "evidence": [
            {
                key: value.isoformat() if isinstance(value, date) else value
                for key, value in capture.items()
                if key != "codes"
            }
            for capture in plan["captures"]
        ],
    }


def _receipt(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": REPAIR_VERSION,
        "time_semantics": "d0_is_first_stored_capture_date_not_classification_effective_date",
        **_summary(plan),
        "open_memberships_without_capture_instruments": plan["no_evidence"],
        "changes": [
            {
                **{
                    key: item[key]
                    for key in (
                        "instrument_id",
                        "exchange",
                        "symbol",
                        "code",
                        "label",
                        "evidence_raw_payload_id",
                    )
                },
                "d0": item["d0"].isoformat(),
                "closed": [
                    {
                        "membership_id": m.id,
                        "group_id": m.group_id,
                        "valid_from": m.valid_from.isoformat(),
                        "old_valid_to": m.valid_to.isoformat() if m.valid_to else None,
                        "new_valid_to": (item["d0"] - timedelta(days=1)).isoformat(),
                    }
                    for m in item["closes"]
                ],
                "opened": item["opened"]
                and {
                    **item["opened"],
                    "valid_from": item["opened"]["valid_from"].isoformat(),
                    "valid_to": item["opened"]["valid_to"].isoformat()
                    if item["opened"]["valid_to"]
                    else None,
                },
            }
            for item in plan["changes"]
        ],
    }


def rescore_recent(db: Session, days: int) -> list[str]:
    """Recompute ``hot_group_v1`` for the latest ``days`` TAIEX trading dates.

    A row written by an older hot_group version is archived before it is
    overwritten or its rank is cleared (``pipeline.archive_group_score``).
    """

    benchmark = _benchmark_instrument(db)
    if benchmark is None or days < 1:
        return []
    latest = db.scalar(
        select(MarketBar.trading_date)
        .where(MarketBar.instrument_id == benchmark.id)
        .order_by(MarketBar.trading_date.desc())
        .limit(1)
    )
    dates = _effective_trading_dates(db, benchmark.id, latest, days) if latest else []
    for day in dates:
        _calculate_group_scores(db, day)
        # Inactive groups are not rescored; their old rank would collide with
        # the recomputed ranks of the same board.
        for score in db.scalars(
            select(GroupDailyScore)
            .join(ThemeGroup, ThemeGroup.id == GroupDailyScore.group_id)
            .where(
                GroupDailyScore.trading_date == day,
                ThemeGroup.active.is_(False),
                GroupDailyScore.rank.is_not(None),
            )
        ).all():
            archive_group_score(db, score, "rank_cleared_inactive_group")
            score.rank = None
        db.flush()
    return [day.isoformat() for day in dates]


def repair_industry_memberships(
    db: Session, *, apply: bool = False, today: date | None = None
) -> dict[str, Any]:
    """Plan, and with ``apply`` write, the repair in the caller's transaction (no commit)."""

    plan = plan_repair(db)
    summary = _summary(plan)
    pending = (
        plan["changes"]
        or plan["groups_to_create"]
        or plan["display_updates"]
        or plan["deactivations"]
    )
    if not apply:
        return {"status": "dry_run", "version": REPAIR_VERSION, **summary}
    if not pending:
        return {"status": "no_change", "version": REPAIR_VERSION, **summary}
    receipt = _receipt(plan)
    for label in plan["groups_to_create"]:
        ensure_official_industry_group(db, label)
    for _group, label in plan["display_updates"]:
        ensure_official_industry_group(db, label)
    for group in plan["deactivations"]:
        group.active = False
    for item in plan["changes"]:
        for membership in item["closes"]:
            membership.valid_to = item["d0"] - timedelta(days=1)
        if item["opened"]:
            db.add(
                GroupMembership(
                    group_id=item["opened"]["group_id"],
                    instrument_id=item["instrument_id"],
                    valid_from=item["opened"]["valid_from"],
                    valid_to=item["opened"]["valid_to"],
                    role="member",
                    confidence=1.0,
                    source=item["opened"]["source"],
                )
            )
    db.flush()
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=today or now.replace(tzinfo=timezone.utc).astimezone(TAIPEI).date(),
        status="success",
        records=len(plan["changes"]),
        data_as_of=max(
            capture["last_observed_date"] for capture in plan["captures"]
        ).isoformat(),
        metadata_json=receipt,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    return {
        "status": "applied",
        "version": REPAIR_VERSION,
        "ingestion_run_id": run.id,
        **summary,
    }


def run_industry_repair(
    *, apply: bool = False, rescore_days: int = 0
) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            result = repair_industry_memberships(db, apply=apply)
        except IndustryRepairError as exc:
            db.rollback()
            return {"status": "failed", "version": REPAIR_VERSION, "errors": exc.errors}
        if apply and rescore_days:
            result["rescored_dates"] = rescore_recent(db, rescore_days)
        if apply:
            db.commit()
        return result
