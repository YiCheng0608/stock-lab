"""Replay stored official captures the collector dropped (Issue #212).

Until #212 the collector kept only quote and chip rows whose code was in that
day's issuer master, so a company that left the master (delisted, moved to the
other exchange) lost every row a later backfill fetched for it.  The exact
official payloads are still in ``raw_payloads``.  This repair:

1. syncs instrument status from the latest stored list captures
   (``pipeline.plan_instrument_status``, the rule the daily collect uses);
2. with ``include_delisted``, creates the instruments of ordinary-share codes
   that have stored quote rows but were never stored, when the lists no longer
   carry them and their quotes stopped at least ``STALE_SESSIONS`` sessions
   before the exchange's latest stored session; the status is ``transferred``
   when the other exchange lists the code, else ``delisted``;
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
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import ChipSnapshot, IngestionRun, Instrument, MarketBar, RawPayload
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
    is_common_stock_code,
    merge_chip_records,
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
    encoded = Path(raw.payload_path).read_bytes()
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
                Path(raw.payload_path),
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
            if not is_common_stock_code(bar.symbol):
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
            chips.append((record, chip_raw_ids.get(record.payload_sha256)))

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


def _by_instrument(rows: list[tuple[Any, int | None]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[date]] = defaultdict(list)
    for record, _raw_id in rows:
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
            instrument_type="stock",
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
    for record, raw_id in plan["chips"]:
        _upsert_official_chip(db, record, instruments, raw_id, overwrite=False)
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
