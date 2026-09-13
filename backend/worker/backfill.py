from __future__ import annotations

"""Auditable, resumable official-data backfill orchestration.

The low-level official adapters remain responsible for endpoint validation and
raw capture.  This module adds a date-level retry boundary around the existing
collector so a failed historical session can be retried without re-running a
successful session or inventing a bar/chip row.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import OFFICIAL_MAX_BACKFILL_DAYS
from app.coverage import (
    has_backfill_manifest,
    official_snapshot_status,
    verified_taiex_sessions,
)
from app.models import (
    ChipSnapshot,
    CorporateAction,
    Event,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    PortfolioPosition,
    RawPayload,
    Signal,
    ThemeGroup,
)
from worker import pipeline
from worker.sources import (
    OfficialBatch,
    OfficialDataError,
    OfficialMarketDataAdapter,
)


BACKFILL_SCOPES = frozenset({
    "market",
    "portfolio",
    "watchlist",
    "events",
    "candidates",
    "priority",
    "all",
})

# Phase 3 collection bounds.  The existing official adapters are deliberately
# called with one date at a time by the first implementation, which is a
# stricter bound than five sessions.  The plan is still expressed in five-day
# chunks so the audit contract remains stable if an adapter later batches
# requests without changing the public request key.
MAX_BATCH_TRADING_DATES = 5
IMMEDIATE_RETRY_ATTEMPTS = 3
TARGETED_RETRY_ATTEMPTS = 2
TARGET_OHLCV_TAIEX_SESSIONS = 65
TARGET_CHIP_EVENT_SESSIONS = 20
BACKFILL_DOMAINS = (
    "ohlcv",
    "taiex",
    "chips",
    "events",
    "corporate_actions",
    "fundamentals",
    "membership",
)
BACKFILL_EXCHANGES = ("TWSE", "TPEx")


def _validate_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValueError("backfill start_date must be on or before end_date")
    if (end_date - start_date).days > OFFICIAL_MAX_BACKFILL_DAYS:
        raise ValueError("official backfill exceeds the three-month limit")


def calendar_weekday_dates(start_date: date, end_date: date) -> list[date]:
    """Return requested weekdays; official feeds decide which are sessions.

    Weekends are never sent to a source.  Public-holiday handling remains
    source-driven because a weekday without a verified official response must
    not be silently converted into a fabricated market session.
    """

    _validate_range(start_date, end_date)
    values: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor += timedelta(days=1)
    return values


def _extension_candidate_dates(start_date: date, end_date: date) -> list[date]:
    """Return bounded weekdays immediately before ``start_date``.

    The original request range is immutable for request-key compatibility.  A
    full 65-session run may activate these candidates when an official
    holiday/no-data response means the original weekdays contain fewer than 65
    verified TAIEX sessions.  The three-month cap is the hard stop.
    """

    lower_bound = end_date - timedelta(days=OFFICIAL_MAX_BACKFILL_DAYS)
    cursor = start_date - timedelta(days=1)
    values: list[date] = []
    while cursor >= lower_bound:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor -= timedelta(days=1)
    return values


def _target_session_count(requested_dates: list[date]) -> int:
    # Short fixture/targeted runs should remain bounded to their explicit
    # range; the full Phase 3 window has 65 weekday candidates.
    return min(TARGET_OHLCV_TAIEX_SESSIONS, len(requested_dates))


def _merge_batch_plan(
    metadata: dict[str, Any],
    scope: str,
    start_date: date,
    end_date: date,
    candidate_dates: list[date],
) -> None:
    """Extend the audit plan without changing existing item state."""

    old = {
        item.get("request_key"): item
        for item in metadata.get("batch_plan", [])
        if isinstance(item, dict) and item.get("request_key")
    }
    rebuilt = _build_batch_plan(scope, start_date, end_date, candidate_dates)
    for item in rebuilt:
        previous = old.get(item["request_key"])
        if previous:
            item.update(previous)
    metadata["batch_plan"] = rebuilt


def _active_instruments(db: Session) -> list[Instrument]:
    return db.scalars(
        select(Instrument)
        .where(
            Instrument.status == "active",
            Instrument.instrument_type.in_({"stock", "etf", "ipo"}),
        )
        .order_by(Instrument.exchange, Instrument.symbol)
    ).all()


def _keys(rows: Iterable[Instrument]) -> set[tuple[str, str]]:
    return {(row.exchange, row.symbol) for row in rows}


def _date_chunks(values: list[date], size: int = MAX_BATCH_TRADING_DATES) -> list[list[date]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    return [values[index:index + size] for index in range(0, len(values), size)]


def _build_batch_plan(
    scope: str,
    start_date: date,
    end_date: date,
    requested_dates: list[date],
) -> list[dict[str, Any]]:
    """Build an auditable exchange/domain/date plan before any network call.

    The current adapters fetch all domains for a date together, so a plan item
    may point to the same collect run as its sibling domains.  Keeping the
    domain rows explicit prevents a successful OHLCV response from hiding a
    missing chips or events response, and gives a future adapter a safe place
    to split requests without changing audit semantics.
    """

    plan: list[dict[str, Any]] = []
    chunks = _date_chunks(requested_dates)
    for exchange in BACKFILL_EXCHANGES:
        for domain in BACKFILL_DOMAINS:
            # TAIEX is a TWSE benchmark, not a TPEx instrument feed.
            if domain == "taiex" and exchange != "TWSE":
                continue
            for batch_index, chunk in enumerate(chunks, start=1):
                first = chunk[0].isoformat()
                last = chunk[-1].isoformat()
                request_key = (
                    f"official-backfill:v1:{scope}:{exchange}:{domain}:"
                    f"{first}:{last}"
                )
                plan.append(
                    {
                        "request_key": request_key,
                        "scope": scope,
                        "exchange": exchange,
                        "domain": domain,
                        "batch_index": batch_index,
                        "batch_size": len(chunk),
                        "start_date": first,
                        "end_date": last,
                        "requested_dates": [item.isoformat() for item in chunk],
                        "received_dates": [],
                        "missing_dates": [],
                        "status": "planned",
                        "attempts": 0,
                        "immediate_attempts": 0,
                        "targeted_attempts": 0,
                        "raw_payload_ids": [],
                        "error_refs": [],
                    }
                )
    return plan


def _candidate_instrument_keys(db: Session, start_date: date, end_date: date) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    signal_rows = db.execute(
        select(Instrument)
        .join(Signal, Signal.instrument_id == Instrument.id)
        .where(
            Signal.signal_date >= start_date,
            Signal.signal_date <= end_date,
            Instrument.status == "active",
        )
    ).scalars()
    result.update(_keys(signal_rows))

    # Group candidates are stored in the score evidence because the score is
    # the as-of source of the candidate list.  Resolve by symbol only when the
    # historical evidence lacks exchange provenance, retaining all matching
    # active exchange rows rather than guessing one.
    scores = db.scalars(
        select(GroupDailyScore).where(
            GroupDailyScore.trading_date >= start_date,
            GroupDailyScore.trading_date <= end_date,
        )
    ).all()
    symbols: set[str] = set()
    for score in scores:
        details = score.details_json or {}
        values = details.get("candidate_symbols", [])
        if isinstance(values, list):
            symbols.update(str(value).strip() for value in values if str(value).strip())
    if symbols:
        result.update(
            _keys(
                db.scalars(
                    select(Instrument).where(
                        Instrument.symbol.in_(symbols),
                        Instrument.status == "active",
                    )
                ).all()
            )
        )
    return result


def resolve_backfill_scope(
    db: Session,
    scope: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Resolve a stable target snapshot for a backfill request."""

    _validate_range(start_date, end_date)
    normalized = scope.strip().lower()
    if normalized not in BACKFILL_SCOPES:
        raise ValueError(f"unsupported backfill scope: {scope}")

    all_rows = _active_instruments(db)
    all_keys = _keys(all_rows)
    if normalized in {"market", "all"}:
        target_keys = all_keys
        filter_keys: set[tuple[str, str]] | None = None
    elif normalized == "portfolio":
        target_keys = _keys(
            db.scalars(
                select(Instrument)
                .join(PortfolioPosition, PortfolioPosition.instrument_id == Instrument.id)
                .where(Instrument.status == "active")
            ).all()
        )
        filter_keys = target_keys
    elif normalized == "watchlist":
        target_keys = _keys(
            db.scalars(
                select(Instrument).where(
                    Instrument.status == "active",
                    Instrument.is_watchlisted.is_(True),
                )
            ).all()
        )
        filter_keys = target_keys
    elif normalized == "events":
        target_keys = _keys(
            db.execute(
                select(Instrument)
                .join(Event, Event.instrument_id == Instrument.id)
                .where(
                    Event.event_date >= start_date,
                    Event.event_date <= end_date,
                    Instrument.status == "active",
                )
            ).scalars()
        )
        filter_keys = target_keys
    elif normalized == "candidates":
        target_keys = _candidate_instrument_keys(db, start_date, end_date)
        filter_keys = target_keys
    else:  # priority: held/watchlisted/event/candidate union
        portfolio_keys = _keys(
            db.scalars(
                select(Instrument)
                .join(PortfolioPosition, PortfolioPosition.instrument_id == Instrument.id)
                .where(Instrument.status == "active")
            ).all()
        )
        watchlist_keys = _keys(
            db.scalars(
                select(Instrument).where(
                    Instrument.status == "active",
                    Instrument.is_watchlisted.is_(True),
                )
            ).all()
        )
        event_keys = _keys(
            db.execute(
                select(Instrument)
                .join(Event, Event.instrument_id == Instrument.id)
                .where(
                    Event.event_date >= start_date,
                    Event.event_date <= end_date,
                    Instrument.status == "active",
                )
            ).scalars()
        )
        target_keys = portfolio_keys | watchlist_keys | event_keys | _candidate_instrument_keys(db, start_date, end_date)
        filter_keys = target_keys

    ordered = sorted(target_keys)
    target_rows = [
        row for row in all_rows if (row.exchange, row.symbol) in target_keys
    ]
    target_type_counts = dict(Counter(row.instrument_type for row in target_rows))
    target_etf_categories = sorted(
        {
            row.etf_category
            for row in target_rows
            if row.instrument_type == "etf" and row.etf_category
        }
    )
    return {
        "scope": normalized,
        "target_keys": ordered,
        "target_instruments": [f"{exchange}:{symbol}" for exchange, symbol in ordered],
        "target_count": len(ordered),
        "target_type_counts": target_type_counts,
        "target_etf_categories": target_etf_categories,
        "filter_keys": filter_keys,
        "all_market_count": len(all_keys),
    }


class _ScopedOfficialAdapter:
    """Filter a normalized official batch without changing raw provenance."""

    def __init__(self, delegate: Any, filter_keys: set[tuple[str, str]] | None) -> None:
        self.delegate = delegate
        self.filter_keys = filter_keys

    @property
    def captured_payloads(self) -> list[Any]:
        return list(getattr(self.delegate, "captured_payloads", []))

    def fetch(self, start: date, end: date) -> OfficialBatch:
        batch = self.delegate.fetch(start, end)
        if self.filter_keys is None:
            return batch
        allowed = set(self.filter_keys)
        # TAIEX is a market-base observation needed for score-date coverage and
        # group relative-return calculations even for a priority scope.
        allowed.add(("TWSE", "TAIEX"))

        def keep(record: Any) -> bool:
            return (getattr(record, "exchange", ""), getattr(record, "symbol", "")) in allowed

        return OfficialBatch(
            instruments=[record for record in batch.instruments if keep(record)],
            bars=[record for record in batch.bars if keep(record)],
            chips=[record for record in batch.chips if keep(record)],
            actions=[record for record in batch.actions if keep(record)],
            fundamentals=[record for record in batch.fundamentals if keep(record)],
            events=[record for record in batch.events if keep(record)],
            payloads=list(batch.payloads),
            warnings=list(batch.warnings),
            data_as_of=batch.data_as_of,
            no_data_dates=list(batch.no_data_dates),
            event_coverage=dict(batch.event_coverage or {}),
        )


def _coverage_summary(report: dict[str, Any]) -> dict[str, Any]:
    instruments = report.get("instrument_coverage", [])
    reasons: Counter[str] = Counter()
    for item in instruments:
        reasons.update(item.get("coverage_reasons", []))
    return {
        "session_basis": report.get("session_basis"),
        "session_count": report.get("session_count", 0),
        "date_count": len(report.get("date_coverage", [])),
        "instrument_count": len(instruments),
        "bar_rows": sum(item.get("bars_total", 0) for item in instruments),
        "chip_rows": sum(item.get("chips_total", 0) for item in instruments),
        "incomplete_to_20": sum(
            1 for item in instruments if item.get("missing_bars_to_20", 0) > 0
        ),
        "incomplete_to_60": sum(
            1 for item in instruments if item.get("missing_bars_to_60", 0) > 0
        ),
        "incomplete_chips_to_20": sum(
            1 for item in instruments if item.get("missing_chips_to_20", 0) > 0
        ),
        "incomplete_chips_to_60": sum(
            1 for item in instruments if item.get("missing_chips_to_60", 0) > 0
        ),
        "coverage_reason_counts": dict(sorted(reasons.items())),
        "event_coverage": report.get("event_coverage", {}),
        "date_coverage": report.get("date_coverage", []),
    }


def coverage_report(
    db: Session,
    start_date: date,
    end_date: date,
    *,
    target_keys: set[tuple[str, str]] | None = None,
    known_no_data_dates: Iterable[date] | None = None,
    target_ohlcv_sessions: int | None = None,
    target_chip_event_sessions: int | None = None,
    event_coverage_by_date: dict[str, dict[str, Any]] | None = None,
    require_provenance: bool = False,
    include_calendar_dates: bool = True,
) -> dict[str, Any]:
    """Aggregate date/exchange/instrument coverage without mutating the DB."""

    _validate_range(start_date, end_date)
    known_no_data = {
        item for item in (known_no_data_dates or [])
        if start_date <= item <= end_date
    }
    all_active_rows = db.scalars(
        select(Instrument).where(Instrument.status == "active")
    ).all()
    active = [
        item
        for item in all_active_rows
        if item.instrument_type in {"stock", "etf", "ipo"}
    ]
    if target_keys is not None:
        active = [item for item in active if (item.exchange, item.symbol) in target_keys]
    active_by_key = {(item.exchange, item.symbol): item for item in active}

    all_bars = db.scalars(
        select(MarketBar).where(
            MarketBar.trading_date >= start_date,
            MarketBar.trading_date <= end_date,
        )
    ).all()
    all_chips = db.scalars(
        select(ChipSnapshot).where(
            ChipSnapshot.trading_date >= start_date,
            ChipSnapshot.trading_date <= end_date,
        )
    ).all()
    event_rows = db.scalars(
        select(Event).where(
            Event.event_date >= start_date,
            Event.event_date <= end_date,
        )
    ).all()
    action_rows = db.scalars(
        select(CorporateAction).where(
            CorporateAction.action_date >= start_date,
            CorporateAction.action_date <= end_date,
        )
    ).all()
    memberships = db.execute(
        select(GroupMembership.instrument_id, GroupMembership.valid_from, GroupMembership.valid_to)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(ThemeGroup.active.is_(True))
    ).all()

    instrument_by_id = {item.id: item for item in all_active_rows}
    market_dates = {row.trading_date for row in all_bars}
    taiex_dates = set(
        verified_taiex_sessions(
            db,
            start_date,
            end_date,
            require_provenance=require_provenance,
        )
    )
    requested_weekdays = set(calendar_weekday_dates(start_date, end_date))
    # ``sessions`` is deliberately only the intersection of verified TAIEX
    # observations.  Requested weekdays and explicit no-data dates remain in
    # the date manifest, but can never inflate a 20/60-day eligibility count.
    sessions = sorted(taiex_dates)
    if require_provenance and not sessions and target_keys is None:
        # Do not classify every active instrument as "short" when the market
        # session denominator itself is unknown.  A caller asking for one
        # explicit instrument may still receive a targeted unknown row.
        active = []
        active_by_key = {}
    has_manifest = has_backfill_manifest(db)
    baseline = official_snapshot_status(db, sessions, has_manifest=has_manifest)
    if sessions:
        session_basis = "official_snapshot" if require_provenance and not has_manifest else "taiex_observed"
    else:
        session_basis = "unknown"
    if include_calendar_dates:
        expected_dates = sorted(requested_weekdays | market_dates | known_no_data)
    elif sessions:
        # Without a bounded run, observed dates are a snapshot, not a
        # generated audit calendar.
        expected_dates = sorted(set(sessions) | market_dates | known_no_data)
    else:
        expected_dates = []
    latest_reference_date = max(taiex_dates, default=None)

    bars_by_date_exchange: dict[date, Counter[str]] = defaultdict(Counter)
    chips_by_date_exchange: dict[date, Counter[str]] = defaultdict(Counter)
    bars_by_key: dict[tuple[str, str], set[date]] = defaultdict(set)
    chips_by_key: dict[tuple[str, str], set[date]] = defaultdict(set)
    for row in all_bars:
        instrument = instrument_by_id.get(row.instrument_id)
        if not instrument:
            continue
        key = (instrument.exchange, instrument.symbol)
        bars_by_date_exchange[row.trading_date][instrument.exchange] += 1
        if key in active_by_key:
            bars_by_key[key].add(row.trading_date)
    for row in all_chips:
        instrument = instrument_by_id.get(row.instrument_id)
        if not instrument:
            continue
        key = (instrument.exchange, instrument.symbol)
        chips_by_date_exchange[row.trading_date][instrument.exchange] += 1
        if key in active_by_key:
            chips_by_key[key].add(row.trading_date)

    events_by_date = Counter(row.event_date for row in event_rows)
    actions_by_date = Counter(row.action_date for row in action_rows)
    event_manifest: dict[str, dict[str, Any]] = dict(event_coverage_by_date or {})
    if not event_manifest:
        # Read persisted coverage evidence from collect/backfill metadata.  An
        # Event row alone is observational evidence, not proof that the
        # source answered an empty query for that session.
        runs = db.scalars(
            select(IngestionRun).where(
                IngestionRun.source == "official",
                IngestionRun.run_type.in_({"collect", "backfill"}),
            )
        ).all()
        for run in runs:
            metadata = run.metadata_json or {}
            if run.run_type == "backfill":
                manifests = metadata.get("coverage_manifest") or {}
                for day, item in manifests.items():
                    coverage = item.get("event_coverage") if isinstance(item, dict) else None
                    if coverage:
                        event_manifest[str(day)] = dict(coverage)
            else:
                day = run.data_as_of or run.run_date
                coverage = metadata.get("event_coverage")
                if day and coverage:
                    event_manifest[str(day)[:10]] = dict(coverage)

    def event_state(day: date) -> str:
        item = event_manifest.get(day.isoformat()) or {}
        if not item:
            return "unqueried"
        verified = set(str(value)[:10] for value in item.get("verified_dates", []))
        empty = set(str(value)[:10] for value in item.get("empty_dates", []))
        unsupported = set(str(value)[:10] for value in item.get("unsupported_dates", []))
        partial = set(str(value)[:10] for value in item.get("partial_dates", []))
        if day.isoformat() in verified or day.isoformat() in empty:
            return "verified_empty" if day.isoformat() in empty else "success"
        if day.isoformat() in unsupported:
            return "unsupported"
        if day.isoformat() in partial:
            return "partial"
        status = str(item.get("status") or "unsupported")
        return status if status in {"complete", "verified_empty", "partial", "unsupported", "missing"} else "unsupported"

    event_verified_dates = {
        day for day in expected_dates if event_state(day) in {"success", "verified_empty"}
    }
    event_empty_dates = {
        day for day in expected_dates if event_state(day) == "verified_empty"
    }
    event_unsupported_dates = {
        day for day in expected_dates if event_state(day) == "unsupported"
    }
    event_partial_dates = {
        day for day in expected_dates if event_state(day) == "partial"
    }
    event_unqueried_dates = {
        day for day in expected_dates if event_state(day) == "unqueried"
    }
    observed_event_dates = {row.event_date for row in event_rows}
    if event_verified_dates:
        event_status = "complete" if not (event_unsupported_dates or event_partial_dates) else "partial"
    elif event_partial_dates:
        event_status = "partial"
    elif event_manifest or observed_event_dates:
        event_status = "unsupported"
    else:
        event_status = "unsupported"
    event_summary = {
        "status": event_status,
        "denominator": "verified_event_query_sessions",
        "target_sessions": target_chip_event_sessions if target_chip_event_sessions is not None else min(TARGET_CHIP_EVENT_SESSIONS, len(requested_weekdays)),
        "verified_sessions": len(event_verified_dates),
        "verified_empty_sessions": len(event_empty_dates),
        "partial_sessions": len(event_partial_dates),
        "unsupported_sessions": len(event_unsupported_dates),
        "unqueried_sessions": len(event_unqueried_dates),
        "observed_event_dates": len(observed_event_dates),
        "observed_event_rows": len(event_rows),
        "verified_dates": sorted(day.isoformat() for day in event_verified_dates),
        "unsupported_dates": sorted(day.isoformat() for day in event_unsupported_dates),
        "reason": "event rows/dates are not used as the denominator; only date-scoped verified or verified-empty responses count",
    }
    events_by_key: dict[tuple[str, str], list[date]] = defaultdict(list)
    event_types_by_key: dict[tuple[str, str], list[tuple[date, str]]] = defaultdict(list)
    actions_by_key: dict[tuple[str, str], list[date]] = defaultdict(list)
    for row in event_rows:
        instrument = instrument_by_id.get(row.instrument_id) if row.instrument_id else None
        if instrument:
            key = (instrument.exchange, instrument.symbol)
            if key in active_by_key:
                events_by_key[key].append(row.event_date)
                event_types_by_key[key].append((row.event_date, row.event_type or ""))
    for row in action_rows:
        instrument = instrument_by_id.get(row.instrument_id)
        if instrument:
            key = (instrument.exchange, instrument.symbol)
            if key in active_by_key:
                actions_by_key[key].append(row.action_date)
    membership_by_date: Counter[date] = Counter()
    membership_by_key: dict[tuple[str, str], set[date]] = defaultdict(set)
    for trading_date in sessions:
        seen: set[int] = set()
        for instrument_id, valid_from, valid_to in memberships:
            if valid_from <= trading_date and (valid_to is None or valid_to >= trading_date):
                seen.add(instrument_id)
                instrument = instrument_by_id.get(instrument_id)
                if instrument:
                    key = (instrument.exchange, instrument.symbol)
                    if key in active_by_key:
                        membership_by_key[key].add(trading_date)
        membership_by_date[trading_date] = len(seen)

    date_coverage = []
    for trading_date in expected_dates:
        bar_count = sum(
            1 for row in all_bars if row.trading_date == trading_date
        )
        non_index_bar_count = sum(
            1
            for row in all_bars
            if row.trading_date == trading_date
            and instrument_by_id.get(row.instrument_id)
            and instrument_by_id[row.instrument_id].instrument_type != "index"
        )
        taiex_count = sum(
            1
            for row in all_bars
            if row.trading_date == trading_date
            and instrument_by_id.get(row.instrument_id)
            and instrument_by_id[row.instrument_id].instrument_type == "index"
            and instrument_by_id[row.instrument_id].symbol in {"TAIEX", "TWII"}
        )
        chip_count = sum(1 for row in all_chips if row.trading_date == trading_date)
        if trading_date in known_no_data and bar_count == 0:
            coverage_status = "skipped_non_trading"
        elif (taiex_count or trading_date in taiex_dates) and non_index_bar_count:
            coverage_status = "success"
        elif bar_count or chip_count or events_by_date[trading_date]:
            coverage_status = "partial"
        elif latest_reference_date and trading_date > latest_reference_date:
            # No observation after the latest verified benchmark session is a
            # freshness problem, not the same thing as a hole inside an
            # otherwise observed range.
            coverage_status = "stale"
        else:
            coverage_status = "missing"
        date_coverage.append(
            {
                "date": trading_date.isoformat(),
                "status": coverage_status,
                "requested": trading_date in requested_weekdays,
                "received": bar_count > 0,
                "bars": dict(sorted(bars_by_date_exchange[trading_date].items())),
                "chips": dict(sorted(chips_by_date_exchange[trading_date].items())),
                # A date-validated raw MI_INDEX payload is a TAIEX
                # observation even when an older collect failed to
                # normalize its index row into market_bars.
                "taiex_rows": taiex_count or int(trading_date in taiex_dates),
                "membership_instruments": membership_by_date.get(trading_date, 0),
                "event_rows": events_by_date[trading_date],
                "event_coverage_status": event_state(trading_date),
                "event_coverage_verified": event_state(trading_date) in {"success", "verified_empty"},
                "corporate_action_rows": actions_by_date[trading_date],
            }
        )

    instrument_coverage = []
    for key, instrument in sorted(active_by_key.items()):
        raw_bar_dates = bars_by_key.get(key, set())
        raw_chip_dates = chips_by_key.get(key, set())
        eligible_sessions = [
            day
            for day in sessions
            if instrument.listing_date is None or day >= instrument.listing_date
        ]
        bar_dates = raw_bar_dates.intersection(eligible_sessions)
        chip_dates = raw_chip_dates.intersection(eligible_sessions)
        suspension_dates = {
            day
            for day, event_type in event_types_by_key.get(key, [])
            if any(token in event_type.casefold() for token in ("suspension", "停牌"))
        }
        coverage_reasons: list[str] = []
        windows: dict[str, dict[str, int]] = {}
        for horizon in (20, 60):
            window = eligible_sessions[-horizon:]
            bar_days = len(bar_dates.intersection(window))
            chip_days = len(chip_dates.intersection(window))
            missing_bar_dates = sorted(set(window) - bar_dates)
            missing_chip_dates = sorted(set(window) - chip_dates)
            missing_bars = (
                max(0, horizon - len(bar_dates))
                if len(eligible_sessions) < horizon
                else len(missing_bar_dates)
            )
            missing_chips = (
                max(0, horizon - len(chip_dates))
                if len(eligible_sessions) < horizon
                else len(missing_chip_dates)
            )
            windows[str(horizon)] = {
                "expected_sessions": len(window),
                "eligible_sessions": len(eligible_sessions),
                "bar_days": bar_days,
                "chip_days": chip_days,
                "missing_bars": missing_bars,
                "missing_chips": missing_chips,
                "missing_bar_dates": [day.isoformat() for day in missing_bar_dates],
                "missing_chip_dates": [day.isoformat() for day in missing_chip_dates],
            }
            if missing_bars:
                if len(eligible_sessions) < horizon and instrument.instrument_type == "ipo":
                    coverage_reasons.append("listed_under_threshold")
                elif any(day in suspension_dates for day in missing_bar_dates):
                    coverage_reasons.append("suspended_or_no_trade")
                else:
                    coverage_reasons.append("missing_bar_dates")
            if missing_chips:
                coverage_reasons.append("missing_chips")
        if not sessions:
            coverage_reasons.append("missing_taiex")
        if instrument.instrument_type == "etf" and instrument.etf_category in {"bond", "leveraged", "inverse"}:
            coverage_reasons.append("etf_not_general_action_eligible")
        coverage_reasons = list(dict.fromkeys(coverage_reasons))
        ipo_stage = None
        if instrument.instrument_type == "ipo":
            if len(bar_dates) < 20:
                ipo_stage = "not_observable"
            elif len(bar_dates) < 60:
                ipo_stage = "observation_only"
            else:
                ipo_stage = "actionable_eligible"
        instrument_coverage.append(
            {
                "exchange": instrument.exchange,
                "symbol": instrument.symbol,
                "instrument_type": instrument.instrument_type,
                "etf_category": instrument.etf_category,
                "listing_date": instrument.listing_date.isoformat() if instrument.listing_date else None,
                "bars_total": len(bar_dates),
                "chips_total": len(chip_dates),
                "effective_bar_sessions": len(bar_dates),
                "effective_chip_sessions": len(chip_dates),
                "eligible_sessions": len(eligible_sessions),
                "latest_bar": max(bar_dates).isoformat() if bar_dates else None,
                "latest_chip": max(chip_dates).isoformat() if chip_dates else None,
                "event_rows": len(events_by_key.get(key, [])),
                "event_days": len(set(events_by_key.get(key, []))),
                "corporate_action_rows": len(actions_by_key.get(key, [])),
                "corporate_action_days": len(set(actions_by_key.get(key, []))),
                "membership_days": len(membership_by_key.get(key, set())),
                "missing_bars_to_20": windows["20"]["missing_bars"],
                "missing_bars_to_60": windows["60"]["missing_bars"],
                "missing_chips_to_20": windows["20"]["missing_chips"],
                "missing_chips_to_60": windows["60"]["missing_chips"],
                "missing_bar_dates_to_20": windows["20"]["missing_bar_dates"],
                "missing_bar_dates_to_60": windows["60"]["missing_bar_dates"],
                "missing_chip_dates_to_20": windows["20"]["missing_chip_dates"],
                "missing_chip_dates_to_60": windows["60"]["missing_chip_dates"],
                "coverage_reasons": coverage_reasons,
                "ipo_stage": ipo_stage,
                "windows": windows,
            }
        )

    report = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "session_basis": session_basis,
        "baseline": baseline,
        "session_count": len(sessions),
        "sessions": [item.isoformat() for item in sessions],
        "requested_calendar_dates": [item.isoformat() for item in sorted(requested_weekdays)],
        "expected_dates": [item.isoformat() for item in expected_dates],
        "date_coverage": date_coverage,
        "instrument_coverage": instrument_coverage,
        "event_coverage": event_summary,
    }
    status_counts = Counter(item["status"] for item in date_coverage)
    observed_non_index_dates = {
        row.trading_date
        for row in all_bars
        if instrument_by_id.get(row.instrument_id)
        and instrument_by_id[row.instrument_id].instrument_type != "index"
    }
    verified_ohlcv_dates = observed_non_index_dates.intersection(taiex_dates)
    chip_dates = {row.trading_date for row in all_chips}.intersection(taiex_dates)
    latest_observed = max(taiex_dates, default=None)
    target_ohlcv_sessions = (
        target_ohlcv_sessions
        if target_ohlcv_sessions is not None
        else (
            TARGET_OHLCV_TAIEX_SESSIONS
            if require_provenance and not has_manifest
            else min(TARGET_OHLCV_TAIEX_SESSIONS, len(requested_weekdays))
        )
    )
    target_chip_event_sessions = (
        target_chip_event_sessions
        if target_chip_event_sessions is not None
        else (
            TARGET_CHIP_EVENT_SESSIONS
            if require_provenance and not has_manifest
            else min(TARGET_CHIP_EVENT_SESSIONS, len(requested_weekdays))
        )
    )
    target_met = len(sessions) >= target_ohlcv_sessions
    target_met_value: bool | None = target_met
    if require_provenance and not has_manifest and not sessions:
        # Unknown is not the same state as a measured partial run.
        target_met_value = None
    report["summary"] = {
        **_coverage_summary(report),
        "coverage_status": baseline["status"],
        "baseline_kind": baseline["kind"],
        "baseline_source": baseline["source"],
        "baseline_message": baseline["message"],
        "has_backfill_manifest": has_manifest,
        "requested_calendar_sessions": len(requested_weekdays),
        "requested_weekday_sessions": len(requested_weekdays),
        "verified_trading_sessions": len(sessions),
        "verified_ohlcv_sessions": len(verified_ohlcv_dates),
        "verified_taiex_sessions": len(taiex_dates),
        "verified_chip_sessions": len(chip_dates),
        "verified_event_sessions": event_summary["verified_sessions"],
        "target_ohlcv_taiex_sessions": target_ohlcv_sessions,
        "target_chip_event_sessions": target_chip_event_sessions,
        "target_met": target_met_value,
        "status_counts": dict(sorted(status_counts.items())),
        "missing_dates": [
            item["date"] for item in date_coverage if item["status"] == "missing"
        ],
        "stale_dates": [
            item["date"] for item in date_coverage if item["status"] == "stale"
        ],
        "skipped_non_trading_dates": [
            item["date"]
            for item in date_coverage
            if item["status"] == "skipped_non_trading"
        ],
        "stale": bool(latest_observed and latest_observed < end_date),
        "latest_observed": latest_observed.isoformat() if latest_observed else None,
        "data_cutoff": latest_observed.isoformat() if latest_observed else None,
    }
    return report


def backfill_run_dict(run: IngestionRun) -> dict[str, Any]:
    metadata = run.metadata_json or {}
    return {
        "id": run.id,
        "run_type": run.run_type,
        "source": run.source,
        "run_date": run.run_date.isoformat() if run.run_date else None,
        "status": run.status,
        "records": run.records,
        "error": run.error,
        "request_key": run.request_key,
        "data_as_of": run.data_as_of,
        "metadata": metadata,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def _initial_metadata(
    scope_info: dict[str, Any],
    start_date: date,
    end_date: date,
    requested_dates: list[date],
) -> dict[str, Any]:
    extension_candidates = _extension_candidate_dates(start_date, end_date)
    target_sessions = _target_session_count(requested_dates)
    batch_plan = _build_batch_plan(
        scope_info["scope"],
        start_date,
        end_date,
        requested_dates,
    )
    return {
        "workflow": "official_targeted_backfill_v1",
        "scope": scope_info["scope"],
        "scope_semantics": "market=all official market-base rows; priority=portfolio/watchlist/events/candidates union",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "date_semantics": "calendar weekdays are requested; official source responses decide actual trading sessions; weekends are excluded and explicit no-data dates are skipped_non_trading",
        "requested_dates": [item.isoformat() for item in requested_dates],
        "requested_calendar_dates": [item.isoformat() for item in requested_dates],
        "extension_candidate_dates": [item.isoformat() for item in extension_candidates],
        "extension_dates": [],
        "candidate_dates": [item.isoformat() for item in requested_dates],
        "expected_dates": [item.isoformat() for item in requested_dates],
        "completed_dates": [],
        "partial_dates": [],
        "failed_dates": [],
        "skipped_dates": [],
        "skipped_non_trading_dates": [],
        "skipped_non_trading": [],
        "verified_trading_sessions": [],
        "target_met": target_sessions == 0,
        "reused_dates": [],
        "attempts": {},
        "immediate_attempts": {},
        "targeted_retry_attempts": {},
        "retry_exhausted_dates": [],
        "date_results": {},
        "coverage_manifest": {},
        "errors": {},
        "error_refs": {},
        "target_instruments": scope_info["target_instruments"],
        "target_count": scope_info["target_count"],
        "target_type_counts": scope_info.get("target_type_counts", {}),
        "target_etf_categories": scope_info.get("target_etf_categories", []),
        "market_instrument_count": scope_info["all_market_count"],
        "coverage_targets": {
            "ohlcv_taiex_sessions": target_sessions,
            "chips_events_sessions": min(TARGET_CHIP_EVENT_SESSIONS, len(requested_dates)),
            "max_calendar_days": OFFICIAL_MAX_BACKFILL_DAYS,
        },
        "batch_contract": {
            "max_trading_dates": MAX_BATCH_TRADING_DATES,
            "exchange_domain_keyed": True,
            "domains": list(BACKFILL_DOMAINS),
            "exchanges": list(BACKFILL_EXCHANGES),
        },
        "retry_policy": {
            "immediate_attempts": IMMEDIATE_RETRY_ATTEMPTS,
            "targeted_retry_attempts": TARGETED_RETRY_ATTEMPTS,
            "total_attempts_per_date": IMMEDIATE_RETRY_ATTEMPTS + TARGETED_RETRY_ATTEMPTS,
            "backoff": "delegated to official adapter; no unbounded retry",
        },
        "batch_plan": batch_plan,
        "next_retry": None,
        "coverage": None,
    }


def _persist_progress(
    run_id: int,
    metadata: dict[str, Any],
    *,
    status: str = "running",
    error: str | None = None,
    finished: bool = False,
) -> None:
    with pipeline.SessionLocal() as db:
        run = db.get(IngestionRun, run_id)
        if not run:
            return
        run.metadata_json = dict(metadata)
        records = metadata.get("date_results", {})
        run.records = sum(
            int(value.get("records", 0) or 0)
            for value in records.values()
            if isinstance(value, dict) and value.get("status") in {"success", "partial"}
        )
        completed = list(metadata.get("completed_dates", []))
        completed.extend(metadata.get("partial_dates", []))
        run.data_as_of = max(completed) if completed else None
        run.status = status
        run.error = error
        if finished:
            run.finished_at = datetime.utcnow()
        db.commit()


def _collect_raw_audit(run_id: int | None) -> tuple[list[int], list[str]]:
    if not run_id:
        return [], []
    with pipeline.SessionLocal() as db:
        rows = db.scalars(
            select(RawPayload)
            .where(RawPayload.ingestion_run_id == run_id)
            .order_by(RawPayload.id)
        ).all()
        return [row.id for row in rows], [row.endpoint for row in rows]


def _domain_statuses(result: dict[str, Any], *, no_data: bool) -> dict[str, str]:
    """Translate one combined collect result into explicit domain states."""

    result_status = str(result.get("status", "failed"))
    if no_data and not int(result.get("records", 0) or 0):
        return {domain: "skipped_non_trading" for domain in BACKFILL_DOMAINS}

    def state(observed: bool) -> str:
        if observed:
            return "success" if result_status == "success" else "partial"
        if result_status == "failed":
            return "missing"
        return "partial"

    event_coverage = result.get("event_coverage") or {}
    event_status = str(event_coverage.get("status") or "unsupported")
    if event_status in {"complete", "verified_empty"}:
        event_domain_status = "success"
    elif event_status == "unsupported":
        event_domain_status = "unsupported"
    elif event_status == "missing":
        event_domain_status = "missing"
    else:
        event_domain_status = "partial"
    return {
        "ohlcv": state(int(result.get("records", 0) or 0) > 0),
        "taiex": state(int(result.get("taiex_records", 0) or 0) > 0),
        "chips": state(int(result.get("chips", 0) or 0) > 0),
        "events": event_domain_status,
        "corporate_actions": state(int(result.get("actions", 0) or 0) > 0),
        "fundamentals": state(int(result.get("fundamentals", 0) or 0) > 0),
        # Memberships are derived from the authoritative universe and are
        # available whenever the collect had instruments to normalize.
        "membership": state(int(result.get("records", 0) or 0) > 0),
    }


def _market_date_is_verified(
    result: dict[str, Any],
    statuses: dict[str, str],
    *,
    no_data: bool,
) -> bool:
    """Return whether a date can count toward the OHLCV/TAIEX target.

    A collect can contain many security bars while its benchmark response is
    missing, stale, or otherwise partial.  Such a date must remain retryable;
    ``records > 0`` alone is not a verified trading session.
    """

    return bool(
        not no_data
        and int(result.get("records", 0) or 0) > 0
        and statuses.get("ohlcv") == "success"
        and statuses.get("taiex") == "success"
    )


def _update_batch_plan(
    metadata: dict[str, Any],
    iso_date: str,
    result: dict[str, Any],
    *,
    phase: str,
    raw_payload_ids: list[int],
    error_ref: str | None,
) -> dict[str, str]:
    no_data = iso_date in set(result.get("no_data_dates", []) or [])
    statuses = _domain_statuses(result, no_data=no_data)
    result_status = str(result.get("status", "failed"))
    received = int(result.get("records", 0) or 0) > 0
    manifest = metadata.setdefault("coverage_manifest", {})
    date_manifest = manifest.setdefault(
        iso_date,
        {
            "requested_date": iso_date,
            "attempt_history": [],
            "raw_payload_ids": [],
            "error_refs": [],
        },
    )
    date_manifest["status"] = "skipped_non_trading" if no_data else result_status
    date_manifest["phase"] = phase
    date_manifest["received_dates"] = [iso_date] if received else []
    date_manifest["no_data"] = no_data
    date_manifest["data_as_of"] = result.get("data_as_of")
    date_manifest["event_coverage"] = dict(result.get("event_coverage") or {})
    date_manifest["raw_payload_ids"] = sorted(
        set(date_manifest.get("raw_payload_ids", [])) | set(raw_payload_ids)
    )
    if error_ref:
        date_manifest["error_refs"] = sorted(
            set(date_manifest.get("error_refs", [])) | {error_ref}
        )
    date_manifest["domain_status"] = statuses

    for item in metadata.get("batch_plan", []):
        if iso_date not in item.get("requested_dates", []):
            continue
        domain = item["domain"]
        date_states = item.setdefault("date_states", {})
        date_states[iso_date] = statuses.get(domain, result_status)
        item["attempts"] = max(int(item.get("attempts", 0) or 0), int(metadata.get("attempts", {}).get(iso_date, 0) or 0))
        item["immediate_attempts"] = max(
            int(item.get("immediate_attempts", 0) or 0),
            int(metadata.get("immediate_attempts", {}).get(iso_date, 0) or 0),
        )
        item["targeted_attempts"] = max(
            int(item.get("targeted_attempts", 0) or 0),
            int(metadata.get("targeted_retry_attempts", {}).get(iso_date, 0) or 0),
        )
        item["raw_payload_ids"] = sorted(
            set(item.get("raw_payload_ids", [])) | set(raw_payload_ids)
        )
        if error_ref:
            item["error_refs"] = sorted(
                set(item.get("error_refs", [])) | {error_ref}
            )
        item["received_dates"] = sorted(
            day for day, state_value in date_states.items()
            if state_value in {"success", "partial"}
        )
        item["missing_dates"] = sorted(
            day for day, state_value in date_states.items()
            if state_value in {"missing", "failed"}
        )
        states = set(date_states.values())
        if states and states <= {"success"}:
            item["status"] = "success"
        elif states and states <= {"skipped_non_trading"}:
            item["status"] = "skipped_non_trading"
        elif "missing" in states or "failed" in states:
            item["status"] = "partial" if item["received_dates"] else "missing"
        elif "partial" in states or "unsupported" in states:
            item["status"] = "partial"
        else:
            item["status"] = "planned"
    return statuses


def targeted_backfill(
    start_date: date,
    end_date: date,
    *,
    scope: str = "market",
    adapter: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run/resume a bounded official backfill with an auditable manifest.

    A date gets at most three immediate attempts in its first invocation and
    two additional attempts when a later invocation targets its failed or
    partial state.  Successful and explicitly no-data dates are never fetched
    again by the same request key, while a failed retry never replaces a
    previously verified market row because ``pipeline.collect`` upserts inside
    its own transaction and preserves the existing row on rollback.
    """

    _validate_range(start_date, end_date)
    requested_calendar_dates = calendar_weekday_dates(start_date, end_date)
    normalized_scope = scope.strip().lower()
    if normalized_scope not in BACKFILL_SCOPES:
        raise ValueError(f"unsupported backfill scope: {scope}")
    request_key = f"official-backfill:v1:{normalized_scope}:{start_date.isoformat()}:{end_date.isoformat()}"

    pipeline.init_db()
    with pipeline.SessionLocal() as db:
        run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == request_key))
        if (
            run
            and run.status == "success"
            and not force
            and (run.metadata_json or {}).get("target_met", True)
        ):
            return backfill_run_dict(run)

        if run:
            metadata = dict(run.metadata_json or {})
            target_strings = metadata.get("target_instruments", [])
            target_keys = {
                tuple(value.split(":", 1))
                for value in target_strings
                if isinstance(value, str) and ":" in value
            }
            filter_keys: set[tuple[str, str]] | None = None if normalized_scope in {"market", "all"} else target_keys
            # Forward-compatible shape repair for an interrupted pre-Phase-3
            # run: retain its existing audit fields, but add the bounded plan.
            if "batch_plan" not in metadata:
                scope_info = resolve_backfill_scope(db, normalized_scope, start_date, end_date)
                metadata.update(_initial_metadata(scope_info, start_date, end_date, requested_calendar_dates))
            original_strings = metadata.get("requested_calendar_dates") or metadata.get("requested_dates") or [
                item.isoformat() for item in requested_calendar_dates
            ]
            original_dates = [date.fromisoformat(str(item)[:10]) for item in original_strings]
            extension_dates = [
                date.fromisoformat(str(item)[:10])
                for item in metadata.get("extension_dates", [])
            ]
            candidate_dates = original_dates + [item for item in extension_dates if item not in original_dates]
            metadata["requested_calendar_dates"] = [item.isoformat() for item in original_dates]
            metadata["extension_candidate_dates"] = [
                item.isoformat()
                for item in _extension_candidate_dates(start_date, end_date)
                if item not in extension_dates
            ]
            metadata["extension_dates"] = [item.isoformat() for item in extension_dates]
            metadata["candidate_dates"] = [item.isoformat() for item in candidate_dates]
            metadata["requested_dates"] = [item.isoformat() for item in candidate_dates]
            _merge_batch_plan(metadata, normalized_scope, start_date, end_date, candidate_dates)
            if force:
                metadata["completed_dates"] = []
                metadata["partial_dates"] = []
                metadata["failed_dates"] = []
                metadata["skipped_dates"] = []
                metadata["skipped_non_trading_dates"] = []
                metadata["reused_dates"] = []
                metadata["retry_exhausted_dates"] = []
                metadata["attempts"] = {}
                metadata["immediate_attempts"] = {}
                metadata["targeted_retry_attempts"] = {}
                metadata["errors"] = {}
                metadata["error_refs"] = {}
                metadata["date_results"] = {}
                metadata["coverage_manifest"] = {}
                metadata["extension_dates"] = []
                metadata["candidate_dates"] = [item.isoformat() for item in original_dates]
                metadata["requested_dates"] = [item.isoformat() for item in original_dates]
                metadata["verified_trading_sessions"] = []
                metadata["target_met"] = _target_session_count(original_dates) == 0
                metadata["batch_plan"] = _build_batch_plan(
                    normalized_scope, start_date, end_date, original_dates
                )
                candidate_dates = list(original_dates)
        else:
            scope_info = resolve_backfill_scope(db, normalized_scope, start_date, end_date)
            metadata = _initial_metadata(scope_info, start_date, end_date, requested_calendar_dates)
            candidate_dates = list(requested_calendar_dates)
            filter_keys = scope_info["filter_keys"]
            run = IngestionRun(
                run_type="backfill",
                source="official",
                run_date=end_date,
                status="running",
                records=0,
                request_key=request_key,
                metadata_json=metadata,
                started_at=datetime.utcnow(),
            )
            db.add(run)
            db.flush()
        run.run_type = "backfill"
        run.source = "official"
        run.run_date = end_date
        run.status = "running"
        run.error = None
        run.started_at = datetime.utcnow()
        run.finished_at = None
        db.commit()
        run_id = run.id

    if not candidate_dates:
        metadata["skipped_dates"] = []
        metadata["next_retry"] = None
        _persist_progress(run_id, metadata, status="skipped", finished=True)
        with pipeline.SessionLocal() as db:
            return backfill_run_dict(db.get(IngestionRun, run_id))

    if normalized_scope not in {"market", "all"} and not filter_keys:
        metadata["errors"] = {"scope": "scope resolved to no active instruments"}
        metadata["next_retry"] = None
        _persist_progress(
            run_id,
            metadata,
            status="skipped",
            error="scope resolved to no active instruments",
            finished=True,
        )
        with pipeline.SessionLocal() as db:
            return backfill_run_dict(db.get(IngestionRun, run_id))

    delegate = adapter or OfficialMarketDataAdapter()
    scoped_adapter = _ScopedOfficialAdapter(delegate, filter_keys)
    completed = set(metadata.get("completed_dates", []))
    partial = set(metadata.get("partial_dates", []))
    failed = set(metadata.get("failed_dates", []))
    skipped = set(metadata.get("skipped_dates", []))
    reused = set(metadata.get("reused_dates", []))
    exhausted = set(metadata.get("retry_exhausted_dates", []))
    errors = dict(metadata.get("errors", {}))
    error_refs = dict(metadata.get("error_refs", {}))
    attempts = dict(metadata.get("attempts", {}))
    immediate_attempts = dict(metadata.get("immediate_attempts", {}))
    targeted_attempts = dict(metadata.get("targeted_retry_attempts", {}))
    date_results = dict(metadata.get("date_results", {}))

    # Older backfill attempts could mark a date completed when the combined
    # collect returned security bars but no TAIEX row.  Reclassify that stale
    # audit state before resuming so the date receives a bounded retry instead
    # of being silently reused forever.
    for stale_date in list(completed):
        audit = date_results.get(stale_date) or (metadata.get("coverage_manifest") or {}).get(stale_date) or {}
        stale_statuses = audit.get("domain_status") if isinstance(audit, dict) else None
        if isinstance(stale_statuses, dict) and (
            stale_statuses.get("ohlcv") != "success"
            or stale_statuses.get("taiex") != "success"
        ):
            completed.discard(stale_date)
            partial.add(stale_date)
            reused.discard(stale_date)
            errors.setdefault(stale_date, "previous attempt lacked verified OHLCV/TAIEX coverage")
    target_sessions = int(
        (metadata.get("coverage_targets") or {}).get(
            "ohlcv_taiex_sessions",
            _target_session_count(requested_calendar_dates),
        )
        or 0
    )
    extension_dates = set(str(item)[:10] for item in metadata.get("extension_dates", []))
    extension_candidates = [
        str(item)[:10]
        for item in metadata.get("extension_candidate_dates", [])
        if str(item)[:10] not in extension_dates
    ]

    def verified_trading_dates() -> set[str]:
        with pipeline.SessionLocal() as db:
            taiex = set(
                db.scalars(
                    select(MarketBar.trading_date)
                    .join(Instrument, Instrument.id == MarketBar.instrument_id)
                    .where(
                        Instrument.status == "active",
                        Instrument.instrument_type == "index",
                        Instrument.symbol.in_({"TAIEX", "TWII"}),
                        MarketBar.trading_date >= min(candidate_dates),
                        MarketBar.trading_date <= end_date,
                    )
                ).all()
            )
        return {
            item.isoformat() if isinstance(item, date) else str(item)[:10]
            for item in taiex
        }

    def persist_state(status: str = "running", error: str | None = None) -> None:
        verified = sorted(verified_trading_dates())
        for skipped_date in skipped:
            skipped_manifest = metadata.setdefault("coverage_manifest", {}).get(skipped_date)
            if isinstance(skipped_manifest, dict) and skipped_manifest.get("no_data"):
                skipped_manifest["status"] = "skipped_non_trading"
        metadata.update(
            {
                "completed_dates": sorted(completed),
                "partial_dates": sorted(partial),
                "failed_dates": sorted(failed),
                "skipped_dates": sorted(skipped),
                "skipped_non_trading_dates": sorted(skipped),
                "skipped_non_trading": sorted(skipped),
                "requested_dates": [item.isoformat() for item in candidate_dates],
                "candidate_dates": [item.isoformat() for item in candidate_dates],
                "extension_dates": sorted(extension_dates),
                "verified_trading_sessions": verified,
                "target_met": len(verified) >= target_sessions,
                "reused_dates": sorted(reused),
                "retry_exhausted_dates": sorted(exhausted),
                "received_dates": sorted(completed | partial),
                "missing_dates": sorted(failed | partial),
                "attempts": attempts,
                "immediate_attempts": immediate_attempts,
                "targeted_retry_attempts": targeted_attempts,
                "date_results": date_results,
                "errors": errors,
                "error_refs": error_refs,
            }
        )
        _persist_progress(run_id, metadata, status=status, error=error)

    pending_dates = [date.fromisoformat(str(item)[:10]) for item in candidate_dates]

    def maybe_activate_extension() -> bool:
        """Activate one bounded pre-range date after a reused final item too."""

        if not (
            pending_index >= len(pending_dates)
            and target_sessions >= TARGET_OHLCV_TAIEX_SESSIONS
            and skipped
            and not (failed or partial)
            and len(verified_trading_dates()) < target_sessions
            and extension_candidates
        ):
            return False
        extension_iso = extension_candidates.pop(0)
        if extension_iso in {item.isoformat() for item in pending_dates}:
            return False
        extension_dates.add(extension_iso)
        extension_date = date.fromisoformat(extension_iso)
        candidate_dates.append(extension_date)
        pending_dates.append(extension_date)
        _merge_batch_plan(
            metadata,
            normalized_scope,
            start_date,
            end_date,
            candidate_dates,
        )
        metadata["extension_candidate_dates"] = list(extension_candidates)
        persist_state()
        return True

    pending_index = 0
    while pending_index < len(pending_dates):
        trading_date = pending_dates[pending_index]
        pending_index += 1
        iso_date = trading_date.isoformat()
        if (iso_date in completed or iso_date in skipped) and not force:
            reused.add(iso_date)
            maybe_activate_extension()
            continue

        total_before = int(attempts.get(iso_date, 0) or 0)
        immediate_before = int(immediate_attempts.get(iso_date, 0) or 0)
        targeted_before = int(targeted_attempts.get(iso_date, 0) or 0)
        if total_before >= IMMEDIATE_RETRY_ATTEMPTS + TARGETED_RETRY_ATTEMPTS and not force:
            exhausted.add(iso_date)
            continue
        if immediate_before < IMMEDIATE_RETRY_ATTEMPTS and total_before == 0:
            phase = "immediate"
            remaining = IMMEDIATE_RETRY_ATTEMPTS - immediate_before
        else:
            phase = "targeted"
            remaining = TARGETED_RETRY_ATTEMPTS - targeted_before
        if remaining <= 0:
            exhausted.add(iso_date)
            continue

        terminal_result: dict[str, Any] | None = None
        for _ in range(remaining):
            attempts[iso_date] = int(attempts.get(iso_date, 0) or 0) + 1
            if phase == "immediate":
                immediate_attempts[iso_date] = int(immediate_attempts.get(iso_date, 0) or 0) + 1
            else:
                targeted_attempts[iso_date] = int(targeted_attempts.get(iso_date, 0) or 0) + 1
            try:
                result = pipeline.collect(
                    trading_date,
                    adapter=scoped_adapter,
                    # A resumed force run intentionally starts a new verified
                    # attempt.  Normal retries reuse the same request row but
                    # do not bypass its idempotency guard after success.
                    force=force,
                )
            except Exception as exc:  # pragma: no cover - defensive boundary
                result = {
                    "status": "failed",
                    "records": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            result_status = str(result.get("status", "failed"))
            no_data = iso_date in set(result.get("no_data_dates", []) or [])
            raw_ids, _endpoints = _collect_raw_audit(result.get("run_id"))
            error_text = result.get("error")
            error_ref = f"collect:{result.get('run_id')}" if result.get("run_id") else None
            if error_text and error_ref:
                error_refs.setdefault(iso_date, [])
                if error_ref not in error_refs[iso_date]:
                    error_refs[iso_date].append(error_ref)
            statuses = _update_batch_plan(
                metadata,
                iso_date,
                result,
                phase=phase,
                raw_payload_ids=raw_ids,
                error_ref=error_ref,
            )
            history = date_results.setdefault(iso_date, {}).setdefault("attempt_history", [])
            history.append(
                {
                    "attempt": attempts[iso_date],
                    "phase": phase,
                    "status": result_status,
                    "records": int(result.get("records", 0) or 0),
                    "raw_payload_ids": raw_ids,
                    "error_ref": error_ref,
                    "error": error_text,
                    "warnings": list(result.get("warnings", []) or []),
                }
            )
            date_results[iso_date].update(
                {
                    "status": result_status,
                    "records": int(result.get("records", 0) or 0),
                    "run_id": result.get("run_id"),
                    "warnings": list(result.get("warnings", []) or []),
                    "error": error_text,
                    "data_as_of": result.get("data_as_of"),
                    "raw_payload_ids": raw_ids,
                    "domain_status": statuses,
                    "event_coverage": dict(result.get("event_coverage") or {}),
                    "attempts": attempts[iso_date],
                    "immediate_attempts": immediate_attempts.get(iso_date, 0),
                    "targeted_attempts": targeted_attempts.get(iso_date, 0),
                }
            )
            persist_state()
            terminal_result = result
            market_verified = _market_date_is_verified(
                result,
                statuses,
                no_data=no_data,
            )
            if (
                result_status == "skipped"
                or (no_data and not result.get("records"))
                or market_verified
            ):
                break
            if _ == remaining - 1:
                break

        result_status = str((terminal_result or {}).get("status", "failed"))
        result_records = int((terminal_result or {}).get("records", 0) or 0)
        no_data = iso_date in set((terminal_result or {}).get("no_data_dates", []) or [])
        terminal_statuses = _domain_statuses(terminal_result or {}, no_data=no_data)
        market_verified = _market_date_is_verified(
            terminal_result or {},
            terminal_statuses,
            no_data=no_data,
        )
        completed.discard(iso_date)
        partial.discard(iso_date)
        failed.discard(iso_date)
        skipped.discard(iso_date)
        if result_status == "success" and result_records > 0 and market_verified:
            completed.add(iso_date)
            errors.pop(iso_date, None)
        elif result_status == "skipped" or (no_data and result_records == 0):
            skipped.add(iso_date)
            errors.pop(iso_date, None)
        elif result_records > 0:
            partial.add(iso_date)
            errors[iso_date] = (
                "official date completed with partial OHLCV/TAIEX coverage"
                if not market_verified
                else "official date completed with partial coverage"
            )
        else:
            failed.add(iso_date)
            errors[iso_date] = str(
                (terminal_result or {}).get("error")
                or "official date backfill failed"
            )
        if attempts.get(iso_date, 0) >= IMMEDIATE_RETRY_ATTEMPTS + TARGETED_RETRY_ATTEMPTS:
            exhausted.add(iso_date)
        persist_state()

        # Only a full 65-session window activates bounded dates before the
        # original range, and only when an explicit no-data session caused the
        # verified TAIEX/session count to fall short.  Failed/partial dates
        # remain retryable instead of being hidden by extension requests.
        maybe_activate_extension()

    # Persist reuse/no-op transitions as well; otherwise an idempotent resume
    # would be behaviorally correct but its audit manifest would hide the
    # reused date.
    persist_state()

    with pipeline.SessionLocal() as db:
        target_strings = metadata.get("target_instruments", [])
        target_keys = {
            tuple(value.split(":", 1))
            for value in target_strings
            if isinstance(value, str) and ":" in value
            }
        event_coverage_by_date = {
            day: item.get("event_coverage")
            for day, item in (metadata.get("coverage_manifest") or {}).items()
            if isinstance(item, dict) and item.get("event_coverage")
        }
        coverage_start = min(candidate_dates)
        report = coverage_report(
            db,
            coverage_start,
            end_date,
            target_keys=None if normalized_scope in {"market", "all"} else target_keys,
            known_no_data_dates={date.fromisoformat(item) for item in skipped},
            target_ohlcv_sessions=target_sessions,
            target_chip_event_sessions=min(
                TARGET_CHIP_EVENT_SESSIONS,
                len(metadata.get("requested_calendar_dates", requested_calendar_dates)),
            ),
            event_coverage_by_date=event_coverage_by_date,
        )
    metadata["coverage"] = report["summary"]
    metadata["coverage_manifest_summary"] = {
        "requested_dates": len(candidate_dates),
        "requested_calendar_dates": len(metadata.get("requested_calendar_dates", requested_calendar_dates)),
        "extension_dates": len(extension_dates),
        "received_dates": len(completed | partial),
        "missing_dates": len(failed | partial),
        "skipped_non_trading_dates": len(skipped),
        "verified_trading_sessions": len(verified_trading_dates()),
        "target_met": len(verified_trading_dates()) >= target_sessions,
        "status": "success" if not (failed or partial or skipped) else "partial",
        "data_as_of": report["summary"].get("data_cutoff"),
    }
    retryable = {
        item
        for item in (failed | partial)
        if int(attempts.get(item, 0) or 0)
        < IMMEDIATE_RETRY_ATTEMPTS + TARGETED_RETRY_ATTEMPTS
    }
    metadata["next_retry"] = (
        {
            "start_date": min(retryable),
            "end_date": max(retryable),
            "dates": sorted(retryable),
        }
        if retryable
        else None
    )
    if failed:
        final_status = "partial" if (completed or partial or skipped) else "failed"
        final_error = "official backfill failed dates: " + ", ".join(sorted(failed))
    elif partial or skipped:
        final_status = "partial"
        final_error = None
    else:
        final_status = "success"
        final_error = None
    _persist_progress(run_id, metadata, status=final_status, error=final_error, finished=True)
    with pipeline.SessionLocal() as db:
        return backfill_run_dict(db.get(IngestionRun, run_id))


def get_backfill_run(db: Session, run_id: int) -> dict[str, Any] | None:
    run = db.scalar(
        select(IngestionRun).where(
            IngestionRun.id == run_id,
            IngestionRun.run_type == "backfill",
        )
    )
    return backfill_run_dict(run) if run else None
