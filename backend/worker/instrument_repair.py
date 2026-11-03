"""Replay stored official captures the collector dropped (Issue #212).

Until #212 the collector kept only quote and chip rows whose code was in that
day's issuer master, so a company that left the master (delisted, moved to the
other exchange) lost every row a later backfill fetched for it.  Until #393
the same held for an ETF that left the ETF list.  The exact official payloads
are still in ``raw_payloads``.  This repair:

1. syncs instrument status from the latest stored list captures
   (``pipeline.plan_instrument_status``, the rule the daily collect uses);
2. with ``include_delisted``, creates the instruments of ordinary-share and
   ETF codes that have stored quote rows but were never stored, when the lists
   no longer carry them and their quotes stopped at least ``STALE_SESSIONS``
   sessions before the exchange's latest stored session; the status is
   ``transferred`` when the other exchange lists the code, else ``delisted``;
3. writes every stored quote row and, for the instruments that received bars,
   every stored chip row that the database lacks.  Stored rows are never
   changed (``overwrite=False``).

Dry-run is the default.  ``apply`` writes in one transaction and records a
receipt in ``ingestion_runs``; a second run finds nothing to write.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.raw_paths import payload_file
from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    ChipSnapshot,
    DataQuality,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)
from worker.industry_repair import rescore_recent
from worker.pipeline import (
    OTHER_EXCHANGE,
    STATUS_SYNC_MAX_SHARE,
    TAIPEI,
    TWSE_LEGACY_DAILY_HISTORY_ENDPOINT,
    UNIVERSE_ENDPOINTS,
    _upsert_official_bar,
    _upsert_official_chip,
    _upsert_quality,
    apply_instrument_status,
    plan_instrument_status,
    stored_instrument,
    universe_evidence,
)
from worker.sources import (
    TPEX_CHIP_HISTORY_ENDPOINT,
    TPEX_ETF_ENDPOINT,
    TPEX_HISTORY_API,
    TPEX_LISTED_ENDPOINT,
    TPEX_MARGIN_HISTORY_ENDPOINT,
    TWSE_CHIP_ENDPOINT,
    TWSE_DAILY_ENDPOINT,
    TWSE_DAILY_HISTORY_ENDPOINT,
    TWSE_ETF_ENDPOINT,
    TWSE_LISTED_ENDPOINT,
    TWSE_MARGIN_HISTORY_ENDPOINT,
    TWSE_NEW_LISTING_ENDPOINT,
    BarRecord,
    ChipRecord,
    FetchedPayload,
    OfficialDataError,
    _is_twse_mi_index_no_data,
    _require_reported_date,
    _rows,
    _text,
    is_etf_code,
    is_quoted_security_code,
    merge_chip_records,
    normalize_etf_category,
    parse_tpex_daily_rows,
    parse_tpex_institutional_rows,
    parse_tpex_margin_rows,
    parse_twse_all_daily_payload,
    parse_twse_daily_rows,
    parse_twse_institutional_rows,
    parse_twse_margin_rows,
    tpex_universe_records,
    twse_universe_records,
)

REPAIR_VERSION = "instrument-repair-v1"
RUN_TYPE = "instrument_repair"
# A code whose quotes continue into the last week may be a listing the lists
# have not caught up with; it is reported, never created.
STALE_SESSIONS = 5


class InstrumentRepairError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:20]))
        self.errors = errors


def _load(raw: RawPayload) -> Any:
    if not raw.payload_path or not raw.sha256:
        raise InstrumentRepairError(
            [f"raw_payloads({raw.id}): missing payload path or sha256"]
        )
    encoded = payload_file(raw.payload_path).read_bytes()
    if hashlib.sha256(encoded).hexdigest() != raw.sha256:
        raise InstrumentRepairError(
            [f"raw_payloads({raw.id}): file content does not match sha256"]
        )
    return json.loads(encoded)


def _requested_date(raw: RawPayload) -> date | None:
    try:
        return date.fromisoformat(str(raw.data_as_of)[:10])
    except ValueError:
        return None


def _distinct(db: Session, condition) -> list[RawPayload]:
    """Stored captures matching ``condition``, oldest first, one per content."""

    seen: set[tuple[str, str]] = set()
    result = []
    for raw in db.scalars(
        select(RawPayload)
        .where(condition)
        .order_by(RawPayload.collected_at, RawPayload.id)
    ):
        key = (raw.endpoint, raw.sha256 or "")
        if key not in seen:
            seen.add(key)
            result.append(raw)
    return result


def _latest_lists(db: Session) -> tuple[list, dict[str, dict[str, Any]], dict]:
    """Universe records and evidence from the newest stored list captures."""

    captures: dict[str, FetchedPayload] = {}
    raw_ids: dict[str, int] = {}
    for exchange, endpoints in UNIVERSE_ENDPOINTS.items():
        for endpoint in endpoints:
            raw = db.scalar(
                select(RawPayload)
                .where(RawPayload.endpoint == endpoint)
                .order_by(RawPayload.collected_at.desc(), RawPayload.id.desc())
                .limit(1)
            )
            if raw is None:
                raise InstrumentRepairError([f"no stored capture of {endpoint}"])
            captures[endpoint] = FetchedPayload(
                raw.source,
                endpoint,
                _load(raw),
                raw.data_as_of,
                raw.collected_at,
                payload_file(raw.payload_path),
                raw.sha256,
            )
            raw_ids[endpoint] = raw.id
    evidence = universe_evidence(
        captures.values(), lambda capture: raw_ids[capture.endpoint]
    )
    records = twse_universe_records(
        captures[TWSE_LISTED_ENDPOINT],
        captures[TWSE_ETF_ENDPOINT],
        captures[TWSE_NEW_LISTING_ENDPOINT],
        evidence["TWSE"]["observed_date"],
    ) + tpex_universe_records(
        captures[TPEX_LISTED_ENDPOINT],
        captures[TPEX_ETF_ENDPOINT],
        evidence["TPEx"]["observed_date"],
    )
    return records, evidence, raw_ids


def _names(payload: Any) -> dict[str, str]:
    tables = payload.get("tables") if isinstance(payload, dict) else None
    rows = (
        [row for table in tables if isinstance(table, dict) for row in _rows(table)]
        if isinstance(tables, list)
        else _rows(payload)
    )
    names = {}
    for row in rows:
        code = _text(row, "證券代號", "代號", "SecuritiesCompanyCode", "Code")
        name = _text(row, "證券名稱", "名稱", "CompanyName", "Name")
        if code and name:
            names[code] = name
    return names


def _quote_bars(raw: RawPayload, payload: Any) -> list[BarRecord]:
    """The capture's bars, validated as the collector validates them."""

    endpoint = raw.endpoint
    requested = _requested_date(raw)
    if endpoint == TWSE_DAILY_ENDPOINT:
        return parse_twse_daily_rows(
            payload, data_as_of=raw.data_as_of, payload_sha256=raw.sha256
        )
    if requested is None:
        raise OfficialDataError(f"capture has no requested date: {endpoint}")
    if endpoint == TPEX_HISTORY_API:
        _require_reported_date(payload, requested, endpoint)
        return parse_tpex_daily_rows(
            payload, data_as_of=requested.isoformat(), payload_sha256=raw.sha256
        )
    if _is_twse_mi_index_no_data(payload, endpoint):
        return []
    _require_reported_date(payload, requested, endpoint)
    return parse_twse_all_daily_payload(
        payload,
        requested_date=requested,
        data_as_of=requested.isoformat(),
        payload_sha256=raw.sha256,
    )


QUOTE_CONDITION = (
    (RawPayload.endpoint == TPEX_HISTORY_API)
    | (RawPayload.endpoint == TWSE_DAILY_ENDPOINT)
    | RawPayload.endpoint.startswith(TWSE_DAILY_HISTORY_ENDPOINT + "?")
    | RawPayload.endpoint.startswith(TWSE_LEGACY_DAILY_HISTORY_ENDPOINT + "?")
)
CHIP_PARSERS: list[tuple[str, str, str, Callable[..., list[ChipRecord]]]] = [
    ("TWSE", "institutional", TWSE_CHIP_ENDPOINT, parse_twse_institutional_rows),
    ("TWSE", "margin", TWSE_MARGIN_HISTORY_ENDPOINT, parse_twse_margin_rows),
    (
        "TPEx",
        "institutional",
        TPEX_CHIP_HISTORY_ENDPOINT,
        parse_tpex_institutional_rows,
    ),
    ("TPEx", "margin", TPEX_MARGIN_HISTORY_ENDPOINT, parse_tpex_margin_rows),
]


def plan_repair(
    db: Session,
    *,
    include_delisted: bool = False,
    max_status_share: float = STATUS_SYNC_MAX_SHARE,
) -> dict[str, Any]:
    records, evidence, list_raw_ids = _latest_lists(db)
    status_plan = plan_instrument_status(
        db, records, evidence, max_share=max_status_share
    )
    listed = {(record.exchange, record.symbol) for record in records}
    stored = {
        (item.exchange, item.symbol): item
        for item in db.scalars(select(Instrument).where(Instrument.market == "TW"))
    }
    have_bars: set[tuple[int, date]] = set(
        db.execute(select(MarketBar.instrument_id, MarketBar.trading_date)).all()
    )

    rejected: list[dict[str, Any]] = []
    quote_payloads = 0
    missing: dict[tuple[str, str, date], tuple[BarRecord, int]] = {}
    unstored: dict[tuple[str, str], dict[str, Any]] = {}
    latest_session: dict[str, date] = {}
    sessions: dict[str, set[date]] = defaultdict(set)
    for raw in _distinct(db, QUOTE_CONDITION):
        payload = _load(raw)
        try:
            bars = _quote_bars(raw, payload)
        except OfficialDataError as exc:
            rejected.append({"raw_payload_id": raw.id, "reason": str(exc)})
            continue
        quote_payloads += 1
        names = None
        for bar in bars:
            if bar.symbol == "TAIEX":
                continue
            sessions[bar.exchange].add(bar.trading_date)
            if not is_quoted_security_code(bar.symbol):
                continue
            key = (bar.exchange, bar.symbol)
            instrument = stored.get(key)
            if (
                instrument is not None
                and (instrument.id, bar.trading_date) in have_bars
            ):
                continue
            if instrument is None:
                if names is None:
                    names = _names(payload)
                entry = unstored.setdefault(
                    key,
                    {"name": names.get(bar.symbol), "dates": set(), "raw_ids": set()},
                )
                entry["name"] = entry["name"] or names.get(bar.symbol)
                entry["dates"].add(bar.trading_date)
                entry["raw_ids"].add(raw.id)
            missing.setdefault((*key, bar.trading_date), (bar, raw.id))
    for exchange, days in sessions.items():
        latest_session[exchange] = max(days)

    to_create: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for (exchange, symbol), entry in sorted(unstored.items()):
        dates = sorted(entry["dates"])
        recent = sorted(d for d in sessions[exchange] if d > dates[-1])
        item = {
            "exchange": exchange,
            "symbol": symbol,
            "name": entry["name"],
            "first_date": dates[0],
            "last_date": dates[-1],
            "rows": len(dates),
            "sessions_since_last_quote": len(recent),
            "raw_payload_ids": sorted(entry["raw_ids"])[:5],
        }
        reason = None
        if (exchange, symbol) in listed:
            reason = "listed_today_but_not_stored"
        elif len(recent) < STALE_SESSIONS:
            reason = "quotes_too_recent_to_call_delisted"
        elif not include_delisted:
            reason = "include_delisted_not_requested"
        if reason:
            unmatched.append({**item, "reason": reason})
            continue
        moved = (OTHER_EXCHANGE[exchange], symbol) in listed
        to_create.append(
            {
                **item,
                "instrument_type": "etf" if is_etf_code(symbol) else "stock",
                "status": "transferred" if moved else "delisted",
                "reason": "listed_on_other_exchange"
                if moved
                else "absent_from_official_lists",
            }
        )
    creatable = {(item["exchange"], item["symbol"]) for item in to_create}
    bars = [
        (bar, raw_id)
        for (exchange, symbol, _day), (bar, raw_id) in sorted(missing.items())
        if (exchange, symbol) in stored or (exchange, symbol) in creatable
    ]
    targets = {(bar.exchange, bar.symbol) for bar, _raw_id in bars}

    have_chips: set[tuple[int, date]] = set(
        db.execute(select(ChipSnapshot.instrument_id, ChipSnapshot.trading_date)).all()
    )
    found: dict[tuple[str, str], dict[tuple[str, date], ChipRecord]] = defaultdict(dict)
    chip_raw_ids: dict[str, int] = {}
    chip_payloads = 0
    if targets:
        for exchange, kind, endpoint, parse in CHIP_PARSERS:
            symbols = {symbol for ex, symbol in targets if ex == exchange}
            if not symbols:
                continue
            condition = (
                RawPayload.endpoint == endpoint
                if exchange == "TPEx"
                else RawPayload.endpoint.startswith(endpoint + "?")
            )
            for raw in _distinct(db, condition):
                requested = _requested_date(raw)
                payload = _load(raw)
                try:
                    if requested is None:
                        raise OfficialDataError("capture has no requested date")
                    _require_reported_date(payload, requested, endpoint)
                except OfficialDataError as exc:
                    rejected.append({"raw_payload_id": raw.id, "reason": str(exc)})
                    continue
                chip_payloads += 1
                chip_raw_ids[raw.sha256] = raw.id
                for record in parse(
                    payload,
                    trading_date=requested,
                    data_as_of=requested.isoformat(),
                    payload_sha256=raw.sha256,
                ):
                    if record.symbol in symbols:
                        found[(exchange, kind)].setdefault(
                            (record.symbol, record.trading_date), record
                        )
    chips = []
    for exchange in ("TWSE", "TPEx"):
        merged = merge_chip_records(
            found[(exchange, "institutional")].values(),
            found[(exchange, "margin")].values(),
            allowed_symbols={symbol for ex, symbol in targets if ex == exchange},
            exchange=exchange,
        )
        for record in sorted(merged, key=lambda r: (r.symbol, r.trading_date)):
            instrument = stored.get((exchange, record.symbol))
            if (
                instrument is not None
                and (instrument.id, record.trading_date) in have_chips
            ):
                continue
            chips.append(
                (
                    record,
                    chip_raw_ids.get(record.payload_sha256),
                    chip_raw_ids.get(record.margin_payload_sha256),
                )
            )

    return {
        "evidence": evidence,
        "list_raw_ids": list_raw_ids,
        "status_plan": status_plan,
        "to_create": to_create,
        "unmatched": unmatched,
        "bars": bars,
        "chips": chips,
        "stored": stored,
        "latest_session": latest_session,
        "payloads": {
            "quotes": quote_payloads,
            "chips": chip_payloads,
            "rejected": rejected,
        },
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _by_instrument(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[date]] = defaultdict(list)
    for record, *_raw_ids in rows:
        grouped[(record.exchange, record.symbol)].append(record.trading_date)
    return [
        {
            "exchange": exchange,
            "symbol": symbol,
            "rows": len(days),
            "first_date": min(days).isoformat(),
            "last_date": max(days).isoformat(),
        }
        for (exchange, symbol), days in sorted(grouped.items())
    ]


def _summary(plan: dict[str, Any]) -> dict[str, Any]:
    changes = plan["status_plan"]["changes"]
    return {
        "lists": {
            exchange: {
                "observed_date": item["observed_date"].isoformat(),
                "raw_payload_ids": [
                    capture["raw_payload_id"] for capture in item["captures"]
                ],
            }
            for exchange, item in plan["evidence"].items()
        },
        "status_sync": {
            exchange: {
                key: _jsonable(value)
                for key, value in item.items()
                if key not in {"captures", "observed_date"}
            }
            for exchange, item in plan["status_plan"]["exchanges"].items()
        },
        "status_changes": [
            {
                "exchange": change["instrument"].exchange,
                "symbol": change["instrument"].symbol,
                "name": change["instrument"].name,
                "instrument_type": change["instrument"].instrument_type,
                "status": change["status"],
                "close_day": change["close_day"].isoformat(),
                "memberships": len(change["memberships"]),
            }
            for change in changes
        ],
        "status_change_counts": dict(Counter(change["status"] for change in changes)),
        "instruments_to_create": _jsonable(plan["to_create"]),
        "unmatched": _jsonable(plan["unmatched"]),
        "bars_to_write": len(plan["bars"]),
        "bars_by_instrument": _by_instrument(plan["bars"]),
        "chips_to_write": len(plan["chips"]),
        "chips_by_instrument": _by_instrument(plan["chips"]),
        "latest_session": _jsonable(plan["latest_session"]),
        "payloads": {
            "quotes": plan["payloads"]["quotes"],
            "chips": plan["payloads"]["chips"],
            "rejected": len(plan["payloads"]["rejected"]),
            "rejected_samples": plan["payloads"]["rejected"][:10],
        },
    }


def repair_instruments(
    db: Session,
    *,
    apply: bool = False,
    include_delisted: bool = False,
    max_status_share: float = STATUS_SYNC_MAX_SHARE,
) -> dict[str, Any]:
    """Plan, and with ``apply`` write, the repair in the caller's transaction."""

    plan = plan_repair(
        db, include_delisted=include_delisted, max_status_share=max_status_share
    )
    summary = _summary(plan)
    pending = (
        plan["status_plan"]["changes"]
        or plan["to_create"]
        or plan["bars"]
        or plan["chips"]
    )
    if not apply:
        return {"status": "dry_run", "version": REPAIR_VERSION, **summary}
    if not pending:
        return {"status": "no_change", "version": REPAIR_VERSION, **summary}

    status_result = apply_instrument_status(db, plan["status_plan"])
    instruments = dict(plan["stored"])
    for item in plan["to_create"]:
        instrument = Instrument(
            market="TW",
            exchange=item["exchange"],
            symbol=item["symbol"],
            name=item["name"] or item["symbol"],
            instrument_type=item["instrument_type"],
            etf_category=normalize_etf_category(
                None, symbol=item["symbol"], name=item["name"] or ""
            )
            if item["instrument_type"] == "etf"
            else None,
            status=item["status"],
            is_watchlisted=False,
        )
        db.add(instrument)
        db.flush()
        instruments[(item["exchange"], item["symbol"])] = instrument
        _upsert_quality(
            db,
            "instrument_status",
            f"{item['exchange']}:{item['symbol']}",
            plan["evidence"][item["exchange"]]["observed_date"],
            item["status"],
            [],
            _jsonable(
                {
                    "version": REPAIR_VERSION,
                    **item,
                    "previous_status": None,
                    "created_from": "stored official quote rows",
                    "evidence": plan["evidence"][item["exchange"]]["captures"],
                }
            ),
            source=item["exchange"].lower(),
        )
    for record, raw_id in plan["bars"]:
        _upsert_official_bar(
            db,
            instruments[(record.exchange, record.symbol)],
            record,
            raw_id,
            overwrite=False,
        )
    for record, raw_id, margin_raw_id in plan["chips"]:
        _upsert_official_chip(
            db,
            record,
            instruments,
            raw_id,
            margin_raw_payload_id=margin_raw_id,
            overwrite=False,
        )
    db.flush()
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=now.replace(tzinfo=timezone.utc).astimezone(TAIPEI).date(),
        status="success",
        records=len(plan["bars"]),
        data_as_of=max(plan["latest_session"].values()).isoformat()
        if plan["latest_session"]
        else None,
        metadata_json={
            "version": REPAIR_VERSION,
            "include_delisted": include_delisted,
            "max_status_share": max_status_share,
            **summary,
            "status_sync_result": status_result,
        },
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


def run_instrument_repair(
    *,
    apply: bool = False,
    include_delisted: bool = False,
    rescore_days: int = 0,
    max_status_share: float = STATUS_SYNC_MAX_SHARE,
) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            result = repair_instruments(
                db,
                apply=apply,
                include_delisted=include_delisted,
                max_status_share=max_status_share,
            )
        except InstrumentRepairError as exc:
            db.rollback()
            return {"status": "failed", "version": REPAIR_VERSION, "errors": exc.errors}
        if apply and rescore_days and result["status"] == "applied":
            result["rescored_dates"] = rescore_recent(db, rescore_days)
        if apply:
            db.commit()
        return result


# ---- bars of codes that got an instrument later (Issue #388) ----

BACKFILL_VERSION = "unmatched-bar-backfill-v1"


def _is_quote_capture(endpoint: str) -> bool:
    return (
        endpoint in {TPEX_HISTORY_API, TWSE_DAILY_ENDPOINT}
        or endpoint.startswith(TWSE_DAILY_HISTORY_ENDPOINT + "?")
        or endpoint.startswith(TWSE_LEGACY_DAILY_HISTORY_ENDPOINT + "?")
    )


def _stored_quote_bars(
    db: Session, raw_id: int, cache: dict[int, list[BarRecord] | str]
) -> list[BarRecord] | str:
    """The bars of one stored quote capture, or why it cannot be read."""

    if raw_id not in cache:
        raw = db.get(RawPayload, raw_id)
        if raw is None:
            cache[raw_id] = "raw_payload_row_missing"
        elif not _is_quote_capture(raw.endpoint):
            cache[raw_id] = "not_a_quote_capture"
        else:
            try:
                cache[raw_id] = _quote_bars(raw, _load(raw))
            except FileNotFoundError:
                cache[raw_id] = "raw_file_missing"
            except (OSError, ValueError, InstrumentRepairError) as exc:
                cache[raw_id] = f"raw_unreadable: {exc}"[:200]
            except OfficialDataError as exc:
                cache[raw_id] = f"raw_rejected: {exc}"[:200]
            except Exception as exc:
                # A parser bug on one old capture keeps only its rows open.
                cache[raw_id] = f"raw_unparsed: {type(exc).__name__}: {exc}"[:200]
    return cache[raw_id]


# The official chip files of a session, by group (Issue #415).
CHIP_FILES: dict[str, dict[str, tuple[str, Callable[..., list[ChipRecord]]]]] = {
    exchange: {
        kind: (endpoint, parse)
        for ex, kind, endpoint, parse in CHIP_PARSERS
        if ex == exchange
    }
    for exchange in ("TWSE", "TPEx")
}
# One stored capture of a chip file: (raw_id, {symbol: record} or None, reason).
# Records are None when the file cannot be read; then the reason says why.
ChipCapture = tuple[int, dict[str, ChipRecord] | None, str | None]
DayChips = dict[str, list[ChipCapture]]


def _stored_chip_files(
    db: Session,
    exchange: str,
    day: date,
    cache: dict[tuple[str, date], DayChips],
) -> DayChips:
    """The day's stored institutional and margin captures, oldest first.

    Each is read like the quote captures (``_load`` checks the SHA-256) and
    parsed as collect parses it.  A capture whose reported date is not the
    day (the exchange's fallback to another session) says nothing about the
    day and gets empty records; a file that is missing, does not match its
    SHA-256 or cannot be parsed gets ``None`` and its reason.
    """

    key = (exchange, day)
    if key in cache:
        return cache[key]
    result: DayChips = {}
    for group, (endpoint, parse) in CHIP_FILES[exchange].items():
        captures: list[ChipCapture] = []
        for raw in db.scalars(
            select(RawPayload)
            .where(
                RawPayload.data_as_of == day.isoformat(),
                (RawPayload.endpoint == endpoint)
                | RawPayload.endpoint.startswith(endpoint + "?"),
            )
            .order_by(RawPayload.collected_at, RawPayload.id)
        ):
            try:
                payload = _load(raw)
                _require_reported_date(payload, day, endpoint)
                records = parse(
                    payload,
                    trading_date=day,
                    data_as_of=day.isoformat(),
                    payload_sha256=raw.sha256,
                )
            except FileNotFoundError:
                captures.append((raw.id, None, "raw_file_missing"))
                continue
            except (OSError, ValueError, InstrumentRepairError) as exc:
                captures.append((raw.id, None, f"raw_unreadable: {exc}"[:200]))
                continue
            except OfficialDataError as exc:
                captures.append((raw.id, {}, f"raw_rejected: {exc}"[:200]))
                continue
            except Exception as exc:
                reason = f"raw_unparsed: {type(exc).__name__}: {exc}"[:200]
                captures.append((raw.id, None, reason))
                continue
            captures.append(
                (
                    raw.id,
                    {r.symbol: r for r in records if r.exchange == exchange},
                    None,
                )
            )
        result[group] = captures
    cache[key] = result
    return result


def _chip_group(
    captures: list[ChipCapture], symbol: str
) -> tuple[str, tuple[int, ChipRecord] | None, dict[str, Any] | None]:
    """What one file says about ``symbol`` on the day.

    The newest capture that has individual rows, or cannot be read, decides
    (#387: the later capture holds).  A capture without individual rows (the
    18:30 MI_MARGN before the exchange publishes it) or of another date is
    passed over.  Returns ``("found", (raw_id, record), None)``,
    ``("absent", None, None)`` when that capture has no row of the symbol,
    or ``("unavailable", None, reason)`` when it cannot be read or no
    capture has individual rows; an older capture never stands in for a
    newer unreadable one.
    """

    for raw_id, records, reason in reversed(captures):
        if records is None:
            return "unavailable", None, {"raw_payload_id": raw_id, "reason": reason}
        if not records:
            continue
        if symbol in records:
            return "found", (raw_id, records[symbol]), None
        return "absent", None, None
    return (
        "unavailable",
        None,
        {"reason": "no_capture_with_rows" if captures else "no_capture"},
    )


def _backfill_chip(
    db: Session,
    instrument: Instrument,
    day: date,
    cache: dict[tuple[str, date], DayChips],
) -> dict[str, Any]:
    """Write the chip row of a backfilled first-session bar from stored raw.

    Each group is what its file's deciding capture says (``_chip_group``).
    A stored row is never changed (``existing``).  When a group is
    ``unavailable`` nothing is written and the date is ``unavailable``, to
    be retried; otherwise the found groups are written (``written``), or
    ``no_row`` when neither file has the symbol.
    """

    exchange, symbol = instrument.exchange, instrument.symbol
    if db.scalar(
        select(ChipSnapshot.id).where(
            ChipSnapshot.instrument_id == instrument.id,
            ChipSnapshot.trading_date == day,
        )
    ):
        return {"trading_date": day.isoformat(), "status": "existing"}
    files = _stored_chip_files(db, exchange, day, cache)
    decided = {
        group: _chip_group(captures, symbol) for group, captures in files.items()
    }
    blocked = [
        {"group": group, **reason}
        for group, (state, _found, reason) in decided.items()
        if state == "unavailable"
    ]
    if blocked:
        return {
            "trading_date": day.isoformat(),
            "status": "unavailable",
            "raws": blocked,
        }
    institutional, margin = decided["institutional"][1], decided["margin"][1]
    if institutional is None and margin is None:
        return {"trading_date": day.isoformat(), "status": "no_row"}
    (record,) = merge_chip_records(
        [institutional[1]] if institutional else [],
        [margin[1]] if margin else [],
        allowed_symbols={symbol},
        exchange=exchange,
    )
    institutional_raw = institutional[0] if institutional else None
    margin_raw = margin[0] if margin else None
    _upsert_official_chip(
        db,
        record,
        {(exchange, symbol): instrument},
        institutional_raw if institutional_raw is not None else margin_raw,
        margin_raw_payload_id=margin_raw,
        overwrite=False,
    )
    return {
        "trading_date": day.isoformat(),
        "status": "written",
        "institutional_raw_payload_id": institutional_raw,
        "margin_raw_payload_id": margin_raw,
    }


def backfill_unmatched_bars(db: Session) -> dict[str, Any]:
    """Write the bars of ``unmatched_bar`` rows whose code now has an instrument.

    A code with official quote rows but no instrument is recorded, not
    written (#212).  A new listing whose list lags its first session is such
    a code until a later collect creates the instrument.  Its recorded dates
    are written from the recorded raw captures, newest capture first, as the
    collector parses them; nothing is fetched.  A stored bar is never
    changed.  The row becomes ``complete`` when every date has a bar; a date
    whose capture is gone stays unwritten and the row is retried next time.

    A date whose bar this backfill wrote also gets its chip row from the
    day's stored institutional and margin captures (Issue #415,
    ``_backfill_chip``), including rows already ``complete``.  Each settled
    date is kept in ``backfill.chips``, so a rerun reads no chip raw again.
    Writes in the caller's transaction.
    """

    rows = db.scalars(
        select(DataQuality)
        .where(DataQuality.entity_type == "unmatched_bar")
        .order_by(DataQuality.entity_key, DataQuality.as_of_date)
    ).all()
    cache: dict[int, list[BarRecord] | str] = {}
    chip_cache: dict[tuple[str, date], DayChips] = {}
    written: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    chips_written: list[dict[str, Any]] = []
    chips_pending: list[dict[str, Any]] = []
    checked = 0
    chips_checked = 0
    for row in rows:
        exchange, _, symbol = row.entity_key.partition(":")
        checks = dict(row.checks_json or {})
        before = checks.get("backfill") or {}
        if row.status == "complete" and not before.get("written"):
            continue
        instrument = stored_instrument(db, exchange, symbol)
        if instrument is None:
            continue
        if row.status == "complete":
            backfill = dict(before)
            status = "complete"
            changed = False
        else:
            checked += 1
            backfill, status = _backfill_row_bars(
                db, instrument, exchange, symbol, before, checks, cache, written
            )
            changed = True
        chips = list(before.get("chips", []))
        settled = {item["trading_date"] for item in chips}
        for item in backfill["written"]:
            if item["trading_date"] in settled:
                continue
            outcome = _backfill_chip(
                db, instrument, date.fromisoformat(item["trading_date"]), chip_cache
            )
            if outcome["status"] == "unavailable":
                chips_pending.append(
                    {"exchange": exchange, "symbol": symbol, **outcome}
                )
                continue
            chips.append(outcome)
            settled.add(item["trading_date"])
            chips_checked += 1
            changed = True
            if outcome["status"] == "written":
                chips_written.append(
                    {"exchange": exchange, "symbol": symbol, **outcome}
                )
        if not changed:
            continue
        if chips:
            backfill["chips"] = sorted(chips, key=lambda item: item["trading_date"])
        backfill["checked_at"] = utcnow().isoformat()
        checks["backfill"] = backfill
        _upsert_quality(
            db,
            "unmatched_bar",
            row.entity_key,
            row.as_of_date,
            status,
            [] if status == "complete" else ["raw_payload"],
            checks,
            source=row.source,
        )
        if status != "complete":
            pending.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "as_of_date": row.as_of_date.isoformat(),
                    "status": status,
                    "unavailable": [
                        item["trading_date"] for item in backfill["unavailable"]
                    ],
                }
            )
    db.flush()
    return {
        "version": BACKFILL_VERSION,
        "rows_checked": checked,
        "written": written,
        "pending": pending,
        "chips_checked": chips_checked,
        "chips_written": chips_written,
        "chips_pending": chips_pending,
    }


def _backfill_row_bars(
    db: Session,
    instrument: Instrument,
    exchange: str,
    symbol: str,
    before: dict[str, Any],
    checks: dict[str, Any],
    cache: dict[int, list[BarRecord] | str],
    written: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Write one open ``unmatched_bar`` row's dates; its ``backfill`` and status."""

    done = list(before.get("written", []))
    done_dates = {item["trading_date"] for item in done}
    existing = set(before.get("existing", []))
    unavailable: list[dict[str, Any]] = []
    raw_ids = sorted(
        {int(item) for item in checks.get("raw_payload_ids", [])}, reverse=True
    )
    for day_text in checks.get("trading_dates", []):
        if day_text in done_dates or day_text in existing:
            continue
        day = date.fromisoformat(day_text)
        if db.scalar(
            select(MarketBar.id).where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date == day,
            )
        ):
            existing.add(day_text)
            continue
        found: tuple[BarRecord, int] | None = None
        reasons: list[dict[str, Any]] = []
        for raw_id in raw_ids:
            bars = _stored_quote_bars(db, raw_id, cache)
            if isinstance(bars, str):
                reasons.append({"raw_payload_id": raw_id, "reason": bars})
                continue
            match = next(
                (
                    bar
                    for bar in bars
                    if bar.exchange == exchange
                    and bar.symbol == symbol
                    and bar.trading_date == day
                ),
                None,
            )
            if match is not None:
                found = (match, raw_id)
                break
            reasons.append({"raw_payload_id": raw_id, "reason": "no_row"})
        if found is None:
            unavailable.append(
                {
                    "trading_date": day_text,
                    "raws": reasons or [{"reason": "no_raw_payload_id"}],
                }
            )
            continue
        record, raw_id = found
        _upsert_official_bar(db, instrument, record, raw_id, overwrite=False)
        done.append({"trading_date": day_text, "raw_payload_id": raw_id})
        done_dates.add(day_text)
        written.append(
            {
                "exchange": exchange,
                "symbol": symbol,
                "trading_date": day_text,
                "raw_payload_id": raw_id,
            }
        )
    if not unavailable:
        status = "complete"
    elif done or existing:
        status = "partial"
    else:
        status = "missing"
    backfill = {
        "version": BACKFILL_VERSION,
        "instrument_id": instrument.id,
        "written": done,
        "existing": sorted(existing),
        "unavailable": unavailable,
    }
    return backfill, status


def run_unmatched_backfill(*, apply: bool = False) -> dict[str, Any]:
    """``backfill_unmatched_bars`` on its own; dry-run rolls the writes back."""

    with SessionLocal() as db:
        result = backfill_unmatched_bars(db)
        if not apply:
            db.rollback()
            return {"status": "dry_run", **result}
        db.commit()
        return {
            "status": "applied"
            if result["rows_checked"] or result["chips_checked"]
            else "no_change",
            **result,
        }
