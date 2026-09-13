"""Official-event to product-news projection.

This module is intentionally conservative: it only projects rows that already
exist in the official Event table.  It never turns an endpoint into an
article, and it never infers a positive or negative market impact from an
event type alone.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Event, GroupMembership, Instrument, NewsItem, ThemeGroup
from .taxonomy import INDUSTRY_DISPLAY_ZH, canonical_group_id, canonical_industry_label


_SOURCE_NAMES = {
    "mops_material_information": "MOPS",
    "tpex_suspension_history": "TPEx 停復牌資料",
    "tpex_suspension": "TPEx 停牌資料",
    "twse_suspension": "TWSE 停牌資料",
}


def is_verified_theme(group: ThemeGroup | None) -> bool:
    """Return whether a theme is safe to expose in product news.

    Legacy groups can still exist for audit, but a pending/unknown display
    name must never turn an internal industry code or English fallback into a
    user-facing relationship.
    """

    return bool(
        group
        and group.active
        and (group.display_name_zh or "").strip()
        and group.name_status in {"official", "verified", "approved"}
    )


def _membership_has_exchange_source(membership: GroupMembership, exchange: str) -> bool:
    """Require the exchange provenance written by the official collector."""

    source = str(membership.source or "").casefold()
    exchange_token = f"exchange={exchange}".casefold()
    return exchange_token in source


def _is_verified_theme_for_instrument(
    group: ThemeGroup | None,
    membership: GroupMembership,
    instrument: Instrument | None,
) -> bool:
    """Validate a group against the instrument's source taxonomy.

    ``name_status=official`` alone is not sufficient: a legacy exchange code
    can have been attached to the wrong market-wide group while still carrying
    an apparently official display name.  Unknown mappings fail closed.
    """

    if not instrument or not is_verified_theme(group):
        return False
    if not _membership_has_exchange_source(membership, instrument.exchange):
        return False
    assert group is not None
    if group.group_type == "official_industry":
        label = canonical_industry_label(instrument.exchange, instrument.industry)
        if not label:
            return False
        if group.id != canonical_group_id("industry", label):
            return False
        expected_name = f"Industry · {label}"
        return (
            group.name == expected_name
            and group.display_name_zh == INDUSTRY_DISPLAY_ZH.get(label)
        )
    if group.group_type == "etf":
        category = str(instrument.etf_category or "").strip().casefold()
        if instrument.instrument_type != "etf" or not category:
            return False
        if group.id != canonical_group_id("etf", category):
            return False
        return group.name == f"ETF · {category}"
    if group.group_type == "daily_hot_group":
        return group.id == canonical_group_id("new-listings", "new-listings")
    return False


def _is_official_event(event: Event) -> bool:
    source = (event.source or "").casefold()
    return source == "official" or source.startswith(("mops", "twse", "tpex"))


def _source_name(event: Event) -> str:
    if event.source in _SOURCE_NAMES:
        return _SOURCE_NAMES[event.source]
    source = event.source or ""
    if source.startswith("mops"):
        return "MOPS"
    if source.startswith("tpex"):
        return "TPEx"
    if source.startswith("twse"):
        return "TWSE"
    return source or "官方資料來源"


def _source_url(event: Event) -> tuple[str | None, str]:
    # An Event endpoint is a feed/report endpoint, not an item-level article
    # URL.  Only expose absolute HTTP(S) values as clickable links.
    endpoint = (event.endpoint or "").strip()
    if endpoint.startswith("https://") or endpoint.startswith("http://"):
        return endpoint, "feed"
    return None, "none"


def _source_item_id(event: Event) -> str | None:
    details = event.details_json or {}
    for key in ("source_item_id", "item_id", "Serial", "serial", "id"):
        value = details.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    # Database DateTime values are naive UTC values in this project.  Keep the
    # projection deterministic when a source gives an offset-aware value.
    return parsed.replace(tzinfo=None)


def _parse_embedded_date(value: object) -> list[date]:
    """Find explicit dates in structured MOPS evidence or its description.

    This is only a consistency check.  It never promotes a text date to a
    publication/event timestamp, which is important for avoiding look-ahead
    or false chronology.
    """

    text = str(value or "")
    result: list[date] = []
    for year_text, month_text, day_text in re.findall(
        r"(?<!\d)(20\d{2})[\-/年](\d{1,2})[\-/月](\d{1,2})日?", text
    ):
        try:
            result.append(date(int(year_text), int(month_text), int(day_text)))
        except ValueError:
            continue
    for year_text, month_text, day_text in re.findall(
        r"(?<!\d)(1\d{2})[\-/年](\d{1,2})[\-/月](\d{1,2})日?", text
    ):
        try:
            result.append(date(int(year_text) + 1911, int(month_text), int(day_text)))
        except ValueError:
            continue
    return list(dict.fromkeys(result))


def _mops_time_consistency(event: Event) -> str:
    """Classify source/date conflicts without guessing a replacement time."""

    if not (event.source or "").casefold().startswith("mops"):
        return "verified"
    details = event.details_json or {}
    explicit = str(details.get("time_consistency") or "").strip().casefold()
    if explicit in {"conflict", "inconsistent", "quarantine"}:
        return "conflict"
    for key in ("mentioned_date", "content_date", "fact_date", "event_date_in_text"):
        values = _parse_embedded_date(details.get(key))
        if values and any(value != event.event_date for value in values):
            return "conflict"
    values = _parse_embedded_date(event.description)
    if any(value != event.event_date for value in values):
        return "conflict"
    return "verified"


def _event_published_at(event: Event) -> datetime | None:
    details = event.details_json or {}
    for key in ("published_at", "PublishedAt", "publication_time", "publish_time"):
        parsed = _parse_datetime(details.get(key))
        if parsed is not None:
            return parsed
    return None


def _event_at_from_evidence(event: Event) -> datetime | None:
    details = event.details_json or {}
    for key in ("event_at", "event_time", "EventTime"):
        parsed = _parse_datetime(details.get(key))
        if parsed is not None:
            return parsed
    return None


def _temporal_fields(event: Event) -> dict[str, object]:
    published_at = _event_published_at(event)
    event_at = _event_at_from_evidence(event)
    consistency = _mops_time_consistency(event)
    if published_at is not None:
        return {
            "published_at": published_at,
            "event_at": event_at,
            "event_date": event.event_date,
            "display_time": published_at,
            "time_basis": "published",
            "time_precision": "datetime",
            "time_consistency": consistency,
        }
    if event_at is not None:
        return {
            "published_at": None,
            "event_at": event_at,
            "event_date": event.event_date,
            "display_time": event_at,
            "time_basis": "event",
            "time_precision": "datetime",
            "time_consistency": consistency,
        }
    return {
        "published_at": None,
        "event_at": None,
        "event_date": event.event_date,
        "display_time": datetime.combine(event.event_date, time.min),
        "time_basis": "event_date",
        "time_precision": "date",
        "time_consistency": consistency,
    }


def _theme_ids_for_event(db: Session, event: Event) -> list[str]:
    if not event.instrument_id:
        return []
    instrument = db.get(Instrument, event.instrument_id)
    if not instrument:
        return []
    rows = db.execute(
        select(GroupMembership, ThemeGroup)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(
            GroupMembership.instrument_id == event.instrument_id,
            GroupMembership.valid_from <= event.event_date,
            (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= event.event_date)),
            ThemeGroup.active.is_(True),
        )
        .order_by(GroupMembership.group_id)
    ).all()
    return _verified_theme_ids_from_rows(event, instrument, rows)


def _verified_theme_ids_from_rows(
    event: Event,
    instrument: Instrument | None,
    rows: Iterable[tuple[GroupMembership, ThemeGroup]],
) -> list[str]:
    """Resolve event themes from already-loaded membership rows.

    The news projector handles many events per request.  Keeping the strict
    exchange-aware validation in this helper lets the projector batch-load
    instruments, memberships, and groups instead of issuing one query per
    event.
    """

    if not instrument:
        return []
    return list(
        dict.fromkeys(
            group.id
            for membership, group in rows
            if membership.valid_from <= event.event_date
            and (membership.valid_to is None or membership.valid_to >= event.event_date)
            if _is_verified_theme_for_instrument(group, membership, instrument)
        )
    )


def _canonical_key(event: Event) -> str:
    # Event already has a database identity constraint.  Reusing its semantic
    # fields keeps this projection stable if its integer id changes between a
    # fixture database and an official database.
    instrument_key = str(event.instrument_id or "market")
    raw = "|".join(
        (
            event.source or "",
            instrument_key,
            event.event_date.isoformat(),
            event.event_type or "",
            event.title or "",
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"official-event:{digest}"


def _content_hash(event: Event, instrument: Instrument | None, theme_ids: list[str]) -> str:
    payload = {
        "source": event.source,
        "event_date": event.event_date.isoformat(),
        "event_type": event.event_type,
        "title": event.title,
        "description": event.description,
        "instrument": f"{instrument.exchange}:{instrument.symbol}" if instrument else None,
        "theme_ids": theme_ids,
        "details": event.details_json or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _event_at(event: Event) -> datetime:
    return datetime.combine(event.event_date, time.min)


def sync_news_from_events(db: Session, events: Iterable[Event] | None = None) -> int:
    """Upsert NewsItem rows for official Events and return changed row count.

    The operation is safe to call after every official collect and is also
    useful as a one-time projection for an existing official database.  It
    does not delete historical NewsItem rows, including rows later marked
    duplicate/retracted by an operator.
    """

    event_rows = list(events) if events is not None else db.scalars(select(Event).order_by(Event.id)).all()
    event_rows = [event for event in event_rows if _is_official_event(event)]
    # Projection is called by the dashboard and news feed.  Batch-load the
    # small relational context once so a market-sized event set cannot turn
    # into an N+1 query storm.
    instrument_ids = {int(event.instrument_id) for event in event_rows if event.instrument_id}
    instruments_by_id = {
        instrument.id: instrument
        for instrument in (
            db.scalars(select(Instrument).where(Instrument.id.in_(instrument_ids))).all()
            if instrument_ids
            else []
        )
    }
    memberships_by_instrument: dict[int, list[tuple[GroupMembership, ThemeGroup]]] = {}
    if instrument_ids:
        for membership, group in db.execute(
            select(GroupMembership, ThemeGroup)
            .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
            .where(
                GroupMembership.instrument_id.in_(instrument_ids),
                ThemeGroup.active.is_(True),
            )
            .order_by(GroupMembership.instrument_id, GroupMembership.group_id)
        ).all():
            memberships_by_instrument.setdefault(membership.instrument_id, []).append((membership, group))
    canonical_keys = {_canonical_key(event) for event in event_rows}
    items_by_key = {
        item.canonical_key: item
        for item in (
            db.scalars(select(NewsItem).where(NewsItem.canonical_key.in_(canonical_keys))).all()
            if canonical_keys
            else []
        )
    }

    changed = 0
    for event in event_rows:
        instrument = instruments_by_id.get(event.instrument_id) if event.instrument_id else None
        theme_ids = _verified_theme_ids_from_rows(
            event,
            instrument,
            memberships_by_instrument.get(event.instrument_id, []),
        )
        canonical_key = _canonical_key(event)
        item = items_by_key.get(canonical_key)
        is_new = item is None
        if item is None:
            item = NewsItem(canonical_key=canonical_key)
            db.add(item)
            items_by_key[canonical_key] = item

        tracked_fields = (
            "dedupe_cluster_id",
            "category",
            "source_kind",
            "source_name",
            "source_url",
            "source_url_kind",
            "source_item_id",
            "title",
            "summary",
            "language",
            "published_at",
            "event_at",
            "event_date",
            "time_basis",
            "time_precision",
            "time_consistency",
            "display_time",
            "collected_at",
            "symbols_json",
            "theme_ids_json",
            "impact_scope",
            "impact_direction",
            "impact_rationale",
            "impact_method",
            "confidence",
            "raw_payload_id",
            "event_id",
            "content_hash",
            "status",
        )
        before = {field: getattr(item, field, None) for field in tracked_fields}

        source_url, source_url_kind = _source_url(event)
        temporal = _temporal_fields(event)
        time_conflict = temporal["time_consistency"] == "conflict"
        values = {
            "dedupe_cluster_id": canonical_key,
            "category": "company" if instrument else "taiwan",
            "source_kind": "official_disclosure",
            "source_name": _source_name(event),
            "source_url": source_url,
            "source_url_kind": source_url_kind,
            "source_item_id": _source_item_id(event),
            "title": event.title,
        }
        for key, value in values.items():
            setattr(item, key, value)
        # Do not reactivate an item that an operator or a later reconciliation
        # explicitly marked duplicate/retracted/superseded.
        item_status = item.status
        if is_new or item_status in {None, "active", "quarantined"}:
            item.status = "quarantined" if time_conflict else "active"
        # A missing official description remains missing.  No summary is
        # synthesized from a title or event type.
        item.summary = event.description
        item.language = "zh-Hant"
        for key, value in temporal.items():
            setattr(item, key, value)
        item.collected_at = event.collected_at
        # A time-conflicted MOPS row remains available by id for audit, but it
        # must not create a product association, theme context, or action
        # priority until an operator verifies the chronology.
        item.symbols_json = [] if time_conflict else ([instrument.symbol] if instrument else [])
        item.theme_ids_json = [] if time_conflict else theme_ids
        item.impact_scope = "market" if time_conflict else ("instrument" if instrument else "market")
        item.impact_direction = "unknown"
        item.impact_rationale = None
        item.impact_method = "time_consistency_conflict" if time_conflict else "default_unknown"
        item.confidence = "unknown" if time_conflict else ("high" if instrument else "unknown")
        item.raw_payload_id = event.raw_payload_id
        item.event_id = event.id
        item.content_hash = _content_hash(event, instrument, theme_ids)
        after = {field: getattr(item, field, None) for field in tracked_fields}
        changed += int(is_new or before != after)
    db.flush()
    return changed
