"""Read-time product time semantics.

This module is deliberately separate from ``time_evidence`` and its store.
It describes what the existing product rows can safely show without
inventing a timezone, availability fact, historical decision time, or
generation time.  It never reads arbitrary JSON evidence markers and never
writes back to a model.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping


UTC = timezone.utc
PRODUCT_TIME_VERSION = "product-time/v1"
PRODUCT_TIME_ROLES = (
    "market_date",
    "event_date",
    "event_at",
    "published_at",
    "first_available_at",
    "collected_at",
    "revision_available_at",
    "decision_at",
    "generated_at",
    "earliest_execution_at",
    "earliest_execution_date",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _legacy_value(value: Any) -> Any:
    """Detach a legacy value while retaining naive timestamp text verbatim."""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _legacy_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_legacy_value(item) for item in value]
    return copy.deepcopy(value)


def _unknown(
    role: str,
    reason: str,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    return {
        "role": role,
        "status": "unknown",
        "precision": "none",
        "value": None,
        "utc": None,
        "date": None,
        "source": source,
        "evidence": None,
        "ref": None,
        "reason": reason,
        "timezone_policy": "not_applicable",
    }


def _known(
    role: str,
    value: str,
    precision: str,
    *,
    source: str,
) -> dict[str, Any]:
    is_date = precision == "date"
    return {
        "role": role,
        "status": "known",
        "precision": precision,
        "value": value,
        "utc": None if is_date else value,
        "date": value if is_date else None,
        "source": source,
        "evidence": None,
        "ref": None,
        "reason": None,
        "timezone_policy": (
            "calendar_date_no_timezone_conversion"
            if is_date
            else "source_offset_normalized_to_UTC"
        ),
    }


def _parse_aware(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None, "empty"
        if _DATE_RE.fullmatch(text):
            return None, "date_only"
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None, "invalid"
    else:
        return None, "invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "naive"
    return parsed.astimezone(UTC).isoformat(), None


def _parse_date(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, datetime):
        return None, "datetime_not_date"
    if isinstance(value, date):
        return value.isoformat(), None
    if isinstance(value, str) and _DATE_RE.fullmatch(value.strip()):
        try:
            return date.fromisoformat(value.strip()).isoformat(), None
        except ValueError:
            return None, "invalid"
    return None, "invalid"


def _role_from_value(
    role: str,
    value: Any,
    *,
    source: str,
    missing_reason: str,
    date_role: bool = False,
    conflict: bool = False,
) -> dict[str, Any]:
    if conflict:
        return _unknown(role, "time_consistency_conflict", source=source)
    if value is None:
        return _unknown(role, missing_reason, source=source)
    if date_role:
        normalized, error = _parse_date(value)
        if normalized is not None:
            return _known(role, normalized, "date", source=source)
        reason = {
            "datetime_not_date": f"{role}_datetime_not_date",
            "invalid": f"{role}_invalid",
        }.get(error or "invalid", f"{role}_invalid")
        return _unknown(role, reason, source=source)
    normalized, error = _parse_aware(value)
    if normalized is not None:
        return _known(role, normalized, "instant", source=source)
    reason = {
        "date_only": f"{role}_date_only_not_instant",
        "naive": f"{role}_naive_timezone_missing",
        "empty": f"{role}_empty",
        "invalid": f"{role}_invalid",
    }.get(error or "invalid", f"{role}_invalid")
    return _unknown(role, reason, source=source)


def _date_precision_role(
    role: str,
    value: Any,
    *,
    source: str,
    missing_reason: str,
    conflict: bool = False,
) -> dict[str, Any]:
    """Keep a source-declared date precision without manufacturing an instant."""

    if conflict:
        return _unknown(role, "time_consistency_conflict", source=source)
    if value is None:
        return _unknown(role, missing_reason, source=source)
    if isinstance(value, datetime):
        normalized = value.date().isoformat()
    elif isinstance(value, date):
        normalized = value.isoformat()
    elif isinstance(value, str):
        normalized = value.strip()[:10]
    else:
        return _unknown(role, f"{role}_invalid", source=source)
    parsed, error = _parse_date(normalized)
    if parsed is None:
        return _unknown(role, f"{role}_{error or 'invalid'}", source=source)
    return _known(role, parsed, "date", source=source)


def _response_time(value: str | datetime | None) -> str:
    """Return an aware UTC response timestamp, never a legacy naive value."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is not None and parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed.astimezone(UTC).isoformat()
    return datetime.now(UTC).isoformat()


def _assemble(
    roles: Mapping[str, dict[str, Any]],
    *,
    legacy: Mapping[str, Any],
    response_generated_at: str | datetime | None,
    limitations: Iterable[str],
    scope: str,
) -> dict[str, Any]:
    response_time = _response_time(response_generated_at)
    role_copy = {role: copy.deepcopy(roles[role]) for role in PRODUCT_TIME_ROLES}
    return {
        "version": PRODUCT_TIME_VERSION,
        "scope": scope,
        "availability_truth": "not_asserted",
        "timezone_policy": {
            "display_timezone": "Asia/Taipei",
            "known_instant": "UTC_normalized_then_displayed_in_Asia_Taipei",
            "date_only": "calendar_date_without_timezone_conversion",
            "naive_or_missing": "unknown_with_reason",
        },
        "roles": role_copy,
        "response_generated_at": response_time,
        "legacy": _legacy_value(dict(legacy)),
        "limitations": list(dict.fromkeys(str(item) for item in limitations if item)),
    }


def build_news_product_time(
    item: Any,
    *,
    event: Any | None = None,
    response_generated_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Project a NewsItem without promoting display fallbacks to instants."""

    conflict = str(getattr(item, "time_consistency", "") or "").casefold() == "conflict"
    item_event_date = getattr(item, "event_date", None)
    event_date = item_event_date if item_event_date is not None else getattr(event, "event_date", None)
    time_basis = str(getattr(item, "time_basis", "") or "").casefold()
    time_precision = str(getattr(item, "time_precision", "") or "").casefold()
    roles = {
        "market_date": _unknown("market_date", "news_market_date_not_persisted", source="news_item"),
        "event_date": _role_from_value(
            "event_date",
            event_date,
            source="news_item.event_date" if item_event_date is not None else "event.event_date",
            missing_reason="news_event_date_not_persisted",
            date_role=True,
            conflict=conflict,
        ),
        "event_at": _unknown("event_at", "news_event_at_not_display_basis", source="news_item.event_at"),
        "published_at": _unknown("published_at", "news_published_at_not_display_basis", source="news_item.published_at"),
        "first_available_at": _unknown("first_available_at", "news_first_available_at_not_persisted", source="news_item"),
        "collected_at": _unknown("collected_at", "news_collected_at_not_persisted", source="news_item.collected_at"),
        "revision_available_at": _unknown("revision_available_at", "news_revision_available_at_not_persisted", source="news_item"),
        "decision_at": _unknown("decision_at", "news_decision_at_not_persisted", source="news_item"),
        "generated_at": _unknown("generated_at", "news_generated_at_not_persisted", source="news_item"),
        "earliest_execution_at": _unknown(
            "earliest_execution_at",
            "news_earliest_execution_at_not_applicable",
            source="news_item",
        ),
        "earliest_execution_date": _unknown(
            "earliest_execution_date",
            "news_earliest_execution_date_not_applicable",
            source="news_item",
        ),
    }
    if conflict:
        roles["market_date"] = _unknown("market_date", "time_consistency_conflict", source="news_item")
    elif time_basis in {"published", "event", "collected"} and time_precision in {"datetime", "date"}:
        role = f"{time_basis}_at"
        if time_basis == "published":
            source = "news_item.published_at"
            value = getattr(item, "published_at", None)
            roles[role] = (
                _date_precision_role(
                    "published_at",
                    value,
                    source=source,
                    missing_reason="news_published_at_not_persisted",
                )
                if time_precision == "date"
                else _role_from_value(
                    "published_at",
                    value,
                    source=source,
                    missing_reason="news_published_at_not_persisted",
                )
            )
        elif time_basis == "event":
            source = "news_item.event_at"
            value = getattr(item, "event_at", None)
            roles[role] = (
                _date_precision_role(
                    "event_at",
                    value,
                    source=source,
                    missing_reason="news_event_at_not_persisted",
                )
                if time_precision == "date"
                else _role_from_value(
                    "event_at",
                    value,
                    source=source,
                    missing_reason="news_event_at_not_persisted",
                )
            )
        else:
            roles[role] = (
                _date_precision_role(
                    "collected_at",
                    getattr(item, "collected_at", None),
                    source="news_item.collected_at",
                    missing_reason="news_collected_at_not_persisted",
                )
                if time_precision == "date"
                else _role_from_value(
                    "collected_at",
                    getattr(item, "collected_at", None),
                    source="news_item.collected_at",
                    missing_reason="news_collected_at_not_persisted",
                )
            )
    if not conflict and time_basis != "collected":
        # collected_at is an independent system-record timestamp.  Its
        # presence does not make published_at/event_at known, and its own
        # offset still has to be explicit.
        roles["collected_at"] = _role_from_value(
            "collected_at",
            getattr(item, "collected_at", None),
            source="news_item.collected_at",
            missing_reason="news_collected_at_not_persisted",
        )
    legacy = {
        "published_at": getattr(item, "published_at", None),
        "event_at": getattr(item, "event_at", None),
        "event_date": event_date,
        "display_time": getattr(item, "display_time", None),
        "time_basis": getattr(item, "time_basis", None),
        "time_precision": getattr(item, "time_precision", None),
        "time_consistency": getattr(item, "time_consistency", None),
        "collected_at": getattr(item, "collected_at", None),
    }
    limitations = [
        "This is a read-time product projection; it does not assert source availability truth.",
        "News display_time and date-only event_date remain legacy-compatible values and are not promoted to an instant.",
        "A collection timestamp does not prove when the source first became available.",
        "Historical decision and generation times are not persisted by the NewsItem projection.",
    ]
    if time_basis not in {"published", "event", "event_date", "collected", "unverified"} or time_precision not in {"datetime", "date", "none"}:
        limitations.append("Invalid or missing News time_basis/time_precision does not establish a known instant.")
    elif time_basis == "unverified" or time_precision == "none":
        limitations.append("Unverified or none time quality does not promote stored aware timestamps to known product instants.")
    if conflict:
        limitations.append("Conflicting event chronology is fail-closed; legacy values are retained only for review.")
    return _assemble(
        roles,
        legacy=legacy,
        response_generated_at=response_generated_at,
        limitations=limitations,
        scope="news_item",
    )


def build_signal_product_time(
    signal: Any,
    *,
    response_generated_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Project a persisted Signal while keeping legacy date fields explicit."""

    roles = {
        "market_date": _role_from_value(
            "market_date",
            getattr(signal, "signal_date", None),
            source="signal.signal_date",
            missing_reason="signal_market_date_not_persisted",
            date_role=True,
        ),
        "event_date": _unknown("event_date", "signal_event_date_not_persisted", source="signal"),
        "event_at": _unknown("event_at", "signal_event_at_not_persisted", source="signal"),
        "published_at": _unknown("published_at", "signal_published_at_not_persisted", source="signal"),
        "first_available_at": _unknown("first_available_at", "signal_first_available_at_not_persisted", source="signal"),
        "collected_at": _unknown("collected_at", "signal_collected_at_not_persisted", source="signal"),
        "revision_available_at": _unknown("revision_available_at", "signal_revision_available_at_not_persisted", source="signal"),
        "decision_at": _unknown("decision_at", "legacy_decision_at_not_persisted", source="signal"),
        "generated_at": _unknown("generated_at", "legacy_generated_at_not_persisted_with_timezone", source="signal"),
        "earliest_execution_at": _role_from_value(
            "earliest_execution_at",
            None,
            source="signal.earliest_execution_date",
            missing_reason=(
                "legacy_earliest_execution_date_is_date_only"
                if getattr(signal, "earliest_execution_date", None) is not None
                else "signal_earliest_execution_at_not_persisted"
            ),
        ),
        "earliest_execution_date": _role_from_value(
            "earliest_execution_date",
            getattr(signal, "earliest_execution_date", None),
            source="signal.earliest_execution_date",
            missing_reason="signal_earliest_execution_date_not_persisted",
            date_role=True,
        ),
    }
    legacy = {
        "signal_date": getattr(signal, "signal_date", None),
        "data_cutoff": getattr(signal, "data_cutoff", None),
        "earliest_execution_date": getattr(signal, "earliest_execution_date", None),
        "execution_date": getattr(signal, "execution_date", None),
        "created_at": getattr(signal, "created_at", None),
    }
    return _assemble(
        roles,
        legacy=legacy,
        response_generated_at=response_generated_at,
        limitations=[
            "This is a read-time product projection; it does not assert source availability truth.",
            "signal_date and earliest_execution_date are calendar dates only; neither is an instant.",
            "earliest_execution_at remains unknown until an actual timezone-aware execution instant is persisted.",
            "Legacy data_cutoff and naive created_at are preserved but cannot establish historical decision or generation time.",
            "Arbitrary rule_evidence markers are not accepted as time evidence.",
        ],
        scope="signal",
    )


def build_action_product_time(
    *,
    as_of: Any = None,
    price_as_of: Any = None,
    earliest_execution_date: Any = None,
    related_events: Iterable[Any] | None = None,
    collected_at: Any = None,
    response_generated_at: str | datetime | None = None,
    legacy_generated_at: Any = None,
) -> dict[str, Any]:
    """Project action/stock timing from the already-batched decision context."""

    events = list(related_events or [])
    unique_event = events[0] if len(events) == 1 else None
    event_reason = (
        "action_event_date_not_unique"
        if len(events) > 1
        else "action_event_date_not_persisted"
    )
    market_value = price_as_of if price_as_of is not None else as_of
    market_source = "market_bar.trading_date" if price_as_of is not None else "decision.as_of"
    roles = {
        "market_date": _role_from_value(
            "market_date",
            market_value,
            source=market_source,
            missing_reason="action_market_date_not_persisted",
            date_role=True,
        ),
        "event_date": _role_from_value(
            "event_date",
            getattr(unique_event, "event_date", None),
            source="event.event_date" if unique_event is not None else "decision.events",
            missing_reason=event_reason,
            date_role=True,
        ),
        "event_at": _unknown("event_at", "action_event_at_not_persisted", source="decision"),
        "published_at": _unknown("published_at", "action_published_at_not_persisted", source="decision"),
        "first_available_at": _unknown("first_available_at", "action_first_available_at_not_persisted", source="decision"),
        "collected_at": _unknown(
            "collected_at",
            "action_collected_at_not_persisted",
            source="decision",
        ),
        "revision_available_at": _unknown("revision_available_at", "action_revision_available_at_not_persisted", source="decision"),
        "decision_at": _unknown("decision_at", "legacy_decision_at_not_persisted", source="decision"),
        "generated_at": _unknown("generated_at", "legacy_generated_at_not_persisted_with_timezone", source="decision"),
        "earliest_execution_at": _role_from_value(
            "earliest_execution_at",
            None,
            source="signal.earliest_execution_date",
            missing_reason=(
                "legacy_earliest_execution_date_is_date_only"
                if earliest_execution_date is not None
                else "action_earliest_execution_at_not_persisted"
            ),
        ),
        "earliest_execution_date": _role_from_value(
            "earliest_execution_date",
            earliest_execution_date,
            source="signal.earliest_execution_date",
            missing_reason="action_earliest_execution_date_not_persisted",
            date_role=True,
        ),
    }
    legacy = {
        "as_of": as_of,
        "data_cutoff": as_of,
        "price_as_of": price_as_of,
        "earliest_execution_date": earliest_execution_date,
        "generated_at": legacy_generated_at,
        "generated_at_role": "legacy_response_assembly_time",
        "run_finished_at": collected_at,
    }
    return _assemble(
        roles,
        legacy=legacy,
        response_generated_at=response_generated_at,
        limitations=[
            "This is a read-time product projection; it does not assert source availability truth.",
            "Decision data_cutoff/as_of and earliest_execution_date are calendar dates; they do not establish an instant.",
            "earliest_execution_at remains unknown until an actual timezone-aware execution instant is persisted.",
            "A unique related event is required before an action can expose an event date; multiple events fail closed.",
            "An ingestion run finished_at is retained as a legacy run timestamp and is not promoted to collected_at for an action.",
            "Historical decision and generation times are not persisted by the legacy action projection.",
            "The legacy generated_at field is retained as a response-assembly compatibility value; response_generated_at is not historical generated_at.",
        ],
        scope="action_summary",
    )


__all__ = [
    "PRODUCT_TIME_ROLES",
    "PRODUCT_TIME_VERSION",
    "build_action_product_time",
    "build_news_product_time",
    "build_signal_product_time",
]
