"""The common strategy lists (Issue #1014): write, read and the registry.

A strategy list is one day's ranked stocks of a frozen definition, stored in
``strategy_list_runs`` / ``strategy_list_items`` and read by
``GET /api/strategy-lists/{strategy}``.  A strategy gives two functions only:
``compute`` (one day: the universe size and the ranked entries) and
``present`` (the stored run and items, or none, to its API response).  The
rest is here: a rerun of the date, strategy and version replaces the run and
its items; the API reads the latest run when no date is asked.  A strategy's
own values of a stock go in ``values_json`` by name.

``read_list`` adds ``recent_picks`` (#1021): the stocks of the list's last
``RECENT_SESSIONS`` sessions (``session_window``: the days with a ``stock``
bar up to the list's date), each with how many of those days' stored lists
it is in and the first and last of them, and each of the day's items gets its
own ``recent_picks``.  ``days`` is how many of the sessions have a stored
list (fewer than 60 before the backfill), ``since`` the first of them.  It
says which days a stock was listed, nothing of a position.  ``/api/h2`` does
not carry it (``recent=False``).  ``backfill`` writes the window's lists day
by day (``worker.cli strategy-lists``), a stored day kept unless forced.

``STRATEGIES`` is the registry (``strategies()``): ``h2`` is ``app.h2_list``
(its ``/api/h2`` stays and answers the same) and ``x4`` is ``app.x4_list``
(#1016).  Migration 0035 moved H2's rows
here from ``h2_runs`` / ``h2_items`` (``move_h2_in``, and back with
``move_h2_out``).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, desc, inspect, select, text
from sqlalchemy.orm import Session

from .clock import utcnow
from .models import Instrument, MarketBar, StrategyListItem, StrategyListRun

# The holding period the research measured each day's list over (#1021).
RECENT_SESSIONS = 60
# 60 sessions are about 87 calendar days; 150 covers the longest holidays.
WINDOW_LOOKBACK_DAYS = 150
SESSION_TYPE = "stock"


@dataclass(frozen=True)
class Entry:
    instrument_id: int
    rank: int
    close: float
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Computed:
    universe_count: int
    entries: list[Entry]


@dataclass(frozen=True)
class Strategy:
    key: str
    version: str
    definitions_sha256: str
    config: dict[str, Any]
    # One day's list; raises when the day cannot be computed (nothing is written).
    compute: Callable[[Session, date], Computed]
    # (db, run or None, its items by rank, the asked date) -> the API response.
    present: Callable[
        [Session, StrategyListRun | None, list[StrategyListItem], date | None],
        dict[str, Any],
    ]


class UnknownStrategy(KeyError):
    """No strategy of that key in the registry."""


def strategies() -> dict[str, Strategy]:
    """The registry, by key.  Imported here: each strategy imports this module."""

    from .h2_list import H2
    from .x4_list import X4

    return {strategy.key: strategy for strategy in (H2, X4)}


def strategy(key: str) -> Strategy:
    found = strategies().get(key)
    if found is None:
        raise UnknownStrategy(key)
    return found


def write_list(db: Session, entry: Strategy, day: date) -> StrategyListRun:
    """Compute ``day``'s list and replace any stored run of the date, strategy
    and version; a failed computation writes nothing."""

    computed = entry.compute(db, day)
    old = db.scalars(
        select(StrategyListRun.id).where(
            StrategyListRun.trading_date == day,
            StrategyListRun.strategy == entry.key,
            StrategyListRun.version == entry.version,
        )
    ).all()
    if old:
        db.execute(delete(StrategyListItem).where(StrategyListItem.run_id.in_(old)))
        db.execute(delete(StrategyListRun).where(StrategyListRun.id.in_(old)))
        db.flush()
    run = StrategyListRun(
        trading_date=day,
        strategy=entry.key,
        version=entry.version,
        definitions_sha256=entry.definitions_sha256,
        status="computed" if computed.entries else "zero",
        universe_count=computed.universe_count,
        item_count=len(computed.entries),
        config_json=dict(entry.config),
        computed_at=utcnow(),
    )
    db.add(run)
    db.flush()
    db.add_all(
        StrategyListItem(
            run_id=run.id,
            trading_date=day,
            instrument_id=item.instrument_id,
            strategy=entry.key,
            version=entry.version,
            rank=item.rank,
            close=item.close,
            values_json=dict(item.values),
        )
        for item in computed.entries
    )
    db.commit()
    return run


def stored(
    db: Session, entry: Strategy, trading_date: date | None
) -> tuple[StrategyListRun | None, list[StrategyListItem]]:
    """The stored run of ``trading_date`` (the latest when None) and its items."""

    query = select(StrategyListRun).where(
        StrategyListRun.strategy == entry.key,
        StrategyListRun.version == entry.version,
    )
    if trading_date is not None:
        query = query.where(StrategyListRun.trading_date == trading_date)
    run = db.scalar(
        query.order_by(
            desc(StrategyListRun.trading_date), desc(StrategyListRun.id)
        ).limit(1)
    )
    if run is None:
        return None, []
    items = db.scalars(
        select(StrategyListItem)
        .where(StrategyListItem.run_id == run.id)
        .order_by(StrategyListItem.rank)
    ).all()
    return run, list(items)


def read_list(
    db: Session, key: str, trading_date: date | None, *, recent: bool = True
) -> dict[str, Any]:
    """The API response of ``key``'s list; ``UnknownStrategy`` for a key not
    in the registry.  ``recent`` adds ``recent_picks`` (#1021)."""

    entry = strategy(key)
    run, items = stored(db, entry, trading_date)
    response = entry.present(db, run, items, trading_date)
    if not recent:
        return response
    if run is None:
        response["recent_picks"] = None
        return response
    picks = recent_picks(db, entry, run.trading_date)
    by_id = {row["instrument"]["id"]: row for row in picks["items"]}
    for item in response["items"]:
        row = by_id.get(item["instrument"]["id"])
        item["recent_picks"] = (
            {key: row[key] for key in ("count", "first_date", "last_date")}
            if row
            else None
        )
    response["recent_picks"] = picks
    return response


def session_window(db: Session, until: date, sessions: int) -> list[date]:
    """The last ``sessions`` days with a ``stock`` bar up to ``until``, old to new."""

    # Bounded so the read stays on the index; more sessions look back further.
    lookback = WINDOW_LOOKBACK_DAYS * max(1, -(-sessions // RECENT_SESSIONS))
    days = db.scalars(
        select(MarketBar.trading_date)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.instrument_type == SESSION_TYPE,
            MarketBar.trading_date <= until,
            MarketBar.trading_date >= until - timedelta(days=lookback),
        )
        .distinct()
        .order_by(desc(MarketBar.trading_date))
        .limit(sessions)
    ).all()
    return sorted(days)


def latest_session(db: Session) -> date | None:
    """The latest day with a ``stock`` bar."""

    return db.scalar(
        select(MarketBar.trading_date)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(Instrument.instrument_type == SESSION_TYPE)
        .order_by(desc(MarketBar.trading_date))
        .limit(1)
    )


def recent_picks(
    db: Session, entry: Strategy, day: date, sessions: int = RECENT_SESSIONS
) -> dict[str, Any]:
    """Every stock of the stored lists of the last ``sessions`` sessions to
    ``day``: how many of those lists it is in, the first and the last; the
    most often first, then the latest, then the symbol."""

    window = session_window(db, day, sessions) or [day]
    first, last = window[0], window[-1]
    days = set(window)
    run_days = sorted(
        run_day
        for run_day in db.scalars(
            select(StrategyListRun.trading_date).where(
                StrategyListRun.strategy == entry.key,
                StrategyListRun.version == entry.version,
                StrategyListRun.trading_date >= first,
                StrategyListRun.trading_date <= last,
            )
        ).all()
        if run_day in days
    )
    picked: dict[int, list[date]] = {}
    ranks: dict[int, int] = {}
    for instrument_id, picked_day, rank in db.execute(
        select(
            StrategyListItem.instrument_id,
            StrategyListItem.trading_date,
            StrategyListItem.rank,
        ).where(
            StrategyListItem.strategy == entry.key,
            StrategyListItem.version == entry.version,
            StrategyListItem.trading_date >= first,
            StrategyListItem.trading_date <= last,
        )
    ):
        if picked_day not in days:
            continue
        picked.setdefault(instrument_id, []).append(picked_day)
        if picked_day == day:
            ranks[instrument_id] = rank
    instruments = {
        row.id: row
        for row in db.execute(
            select(
                Instrument.id,
                Instrument.exchange,
                Instrument.symbol,
                Instrument.name,
                Instrument.instrument_type,
            ).where(Instrument.id.in_(list(picked)))
        )
    }
    rows = []
    for instrument_id, picked_days in picked.items():
        instrument = instruments[instrument_id]
        rows.append(
            {
                "instrument": {
                    "id": instrument.id,
                    "exchange": instrument.exchange,
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "instrument_type": instrument.instrument_type,
                },
                "count": len(picked_days),
                "first_date": min(picked_days).isoformat(),
                "last_date": max(picked_days).isoformat(),
                "today_rank": ranks.get(instrument_id),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["count"],
            -date.fromisoformat(row["last_date"]).toordinal(),
            row["instrument"]["symbol"],
            row["instrument"]["exchange"],
        )
    )
    return {
        "sessions": sessions,
        "days": len(run_days),
        "since": run_days[0].isoformat() if run_days else None,
        "items": rows,
    }


def backfill(
    db: Session,
    entry: Strategy,
    until: date,
    sessions: int = RECENT_SESSIONS,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Write the lists of the last ``sessions`` sessions to ``until``, old to
    new, one day at a time.  A day with a stored list of the version is kept
    (a rerun writes only the days still missing) unless ``force``; a day that
    cannot be computed is reported and the next one goes on."""

    started = time.monotonic()
    window = session_window(db, until, sessions)
    have = set(
        db.scalars(
            select(StrategyListRun.trading_date).where(
                StrategyListRun.strategy == entry.key,
                StrategyListRun.version == entry.version,
                StrategyListRun.trading_date.in_(window),
            )
        ).all()
    )
    written, kept, failed = [], [], []
    for day in window:
        if day in have and not force:
            kept.append(day.isoformat())
            continue
        try:
            write_list(db, entry, day)
        except Exception as exc:  # noqa: BLE001 - reported, the next day goes on
            db.rollback()
            failed.append(
                {"date": day.isoformat(), "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        written.append(day.isoformat())
    return {
        "status": "failed" if failed or not window else "success",
        "strategy": entry.key,
        "version": entry.version,
        "sessions": len(window),
        "since": window[0].isoformat() if window else None,
        "until": window[-1].isoformat() if window else None,
        "written": len(written),
        "kept": len(kept),
        "failed": failed,
        "seconds": round(time.monotonic() - started, 1),
    }


# --- migration 0035: H2's rows in and out ----------------------------------

H2_KEY = "h2"
H2_VALUE = "high_gap_240"
_RUN_COLUMNS = (
    "id, trading_date, version, definitions_sha256, status, universe_count, "
    "item_count, config_json, computed_at"
)


def move_h2_in(connection) -> int:
    """Copy every ``h2_runs`` / ``h2_items`` row into the strategy list tables
    (ids, dates and values unchanged; ``high_gap_240`` into ``values_json``)
    and drop the two tables.  Returns the items moved; 0 without ``h2_runs``."""

    tables = set(inspect(connection).get_table_names())
    if "h2_runs" not in tables:
        return 0
    connection.execute(
        text(
            f"INSERT INTO strategy_list_runs (strategy, {_RUN_COLUMNS}) "
            f"SELECT :key, {_RUN_COLUMNS} FROM h2_runs"
        ),
        {"key": H2_KEY},
    )
    moved = 0
    if "h2_items" in tables:
        rows = connection.execute(
            text(
                "SELECT id, h2_run_id, trading_date, instrument_id, version, rank, "
                "high_gap_240, close FROM h2_items ORDER BY id"
            )
        ).all()
        connection.execute(
            text(
                "INSERT INTO strategy_list_items (id, run_id, trading_date, "
                "instrument_id, strategy, version, rank, close, values_json) "
                "SELECT id, h2_run_id, trading_date, instrument_id, :key, version, "
                "rank, close, :empty FROM h2_items"
            ),
            {"key": H2_KEY, "empty": "{}"},
        )
        if rows:
            # Python's JSON writes a float that reads back as the same float.
            connection.execute(
                text("UPDATE strategy_list_items SET values_json = :v WHERE id = :id"),
                [
                    {"id": row.id, "v": json.dumps({H2_VALUE: row.high_gap_240})}
                    for row in rows
                ],
            )
        moved = len(rows)
        connection.execute(text("DROP TABLE h2_items"))
    connection.execute(text("DROP TABLE h2_runs"))
    return moved


def move_h2_out(connection) -> int:
    """The reverse of ``move_h2_in`` into existing empty ``h2_runs`` /
    ``h2_items``: H2's rows only (another strategy's are not kept by 0034).
    Returns the items moved."""

    connection.execute(
        text(
            f"INSERT INTO h2_runs ({_RUN_COLUMNS}) "
            f"SELECT {_RUN_COLUMNS} FROM strategy_list_runs WHERE strategy = :key"
        ),
        {"key": H2_KEY},
    )
    rows = connection.execute(
        text(
            "SELECT id, run_id, trading_date, instrument_id, version, rank, close, "
            "values_json FROM strategy_list_items WHERE strategy = :key ORDER BY id"
        ),
        {"key": H2_KEY},
    ).all()
    if rows:
        connection.execute(
            text(
                "INSERT INTO h2_items (id, h2_run_id, trading_date, instrument_id, "
                "version, rank, high_gap_240, close) VALUES (:id, :run_id, "
                ":trading_date, :instrument_id, :version, :rank, :value, :close)"
            ),
            [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "trading_date": row.trading_date,
                    "instrument_id": row.instrument_id,
                    "version": row.version,
                    "rank": row.rank,
                    "value": _loaded(row.values_json).get(H2_VALUE),
                    "close": row.close,
                }
                for row in rows
            ],
        )
    return len(rows)


def _loaded(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return json.loads(value) if value else {}
