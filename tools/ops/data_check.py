"""The daily data check of one trading date (Issue #390), run by the watchdog.

After a daily ``success`` the watchdog compares what that day's collect wrote
into the database with the official raw captures it wrote it from, through a
read-only connection (``mode=ro`` and ``query_only``).  Nothing is repaired:
every disagreement is a finding the watchdog comments on #1.

The raw captures are read with the collector's own parsers and the write
rules of ``worker.pipeline`` (docs/ops/SCHEDULING.md 重跑與回補的冪等), so a finding is a row the
write step got wrong, missed or did not revise; a parser that misreads a
field the same way today is not caught here (the full audit, #391, is).

Checks of trading date ``day``:

- ``bar_value``: each stored bar (OHLC, volume, turnover, suspension) against
  the capture it cites; a value another capture of the day supplies is a fill
  and passes.  ``bar_missing``: a capture's quote row of an active instrument
  without a bar.  ``unmatched_bar``: an ``unmatched_bar`` row of the last
  ``UNMATCHED_SESSIONS`` sessions still open while its code has an
  instrument (#388).
- ``chip_value``: institutional flow against the day's latest capture of the
  institutional file, which #387 makes the stored one (``chip_revision`` when
  the row still holds an earlier capture's values); margin against the
  capture the row cites, or any capture of the day (a fill).
  ``chip_missing``: an institutional or margin row of an active instrument
  with a bar of the day but no chip row.
- ``action_value``: a corporate action dated ``day`` against the daily feed
  row it was written from (TWT48U, tpex_exright_daily), after the #386 guard.
  ``action_missing``: a row of the day's feeds, or of an earlier TWT48U that
  announced ``day``, without a stored event.
- With ``official`` (the default), TWSE TWT49U (+ TWT49UDetail) and TPEx
  exDailyQ for ``day`` are requested (#402 review): a TWT48U row's factor is
  checked against the official prices (``action_factor``), another row's
  fields against the official row (``action_value``), an official event
  without a stored one is ``action_missing`` and a stored event the official
  tables do not have is ``action_not_official`` (not for an event whose
  TWT49UDetail could not be read).  All official requests share
  ``OFFICIAL_BUDGET_SECONDS``; past it the rest is
  ``action_official_unavailable`` and the local comparisons above still
  stand.  The captures go to a temporary directory that is removed afterwards.
- ``row_count``: a market's common-stock bars of the day are
  ``ROW_DROP_PERCENT`` percent or more below the median of its previous
  ``ROW_DROP_SESSIONS`` sessions.
- ``institutional_refetch``: the day's institutional refetch (#396; the 23:00
  daily since #466) ended ``failed`` or ``partial``, or a daily that succeeded
  before 21:00 (a manual run) has no refetch (institutional flow compared with a
  file from before 21:00 only); still running makes the result ``pending``.

One event is one finding: the TWT48U and official ``action_missing`` of an
event, and the ``unmatched_bar`` and ``bar_missing`` of one code and date,
are merged with their sources in the note.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import re
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

BACKEND = Path(__file__).resolve().parents[2] / "backend"

MAX_LISTED = 20
ROW_DROP_PERCENT = 3
ROW_DROP_SESSIONS = 5
UNMATCHED_SESSIONS = 5
# How far back a TWT48U capture may have announced the day's events.
ANNOUNCEMENT_DAYS = 120
EXCHANGES = ("TWSE", "TPEx")
COMMON_STOCK_TYPES = ("stock", "ipo")
QUOTED_TYPES = ("stock", "ipo", "etf")
BAR_FIELDS = ("open", "high", "low", "close", "volume", "is_suspended")
ACTION_FIELDS = ("cash_dividend", "stock_dividend_ratio", "split_ratio")
REFETCH_FAILED = ("failed", "partial")
# A daily that succeeded from 21:00 Taipei (13:00 naive UTC) on collected the
# late institutional files itself; one before that (a manual run) needs a later
# refetch.
LATE_COLLECT_UTC_HOUR = 13
# All official result-table requests of one check (#408 review). fetch_json
# may retry 3 times at 30 s, so one request can overrun it by about 95 s,
# still inside the watchdog's 240-second helper limit.
OFFICIAL_BUDGET_SECONDS = 120
# Without these (a database before them) there is nothing to check.
TABLES = (
    "instruments",
    "raw_payloads",
    "market_bars",
    "chip_snapshots",
    "corporate_actions",
    "data_quality",
    "schedule_runs",
    "schedule_run_steps",
)

LABELS = {
    "bar_value": "日線 raw 與 DB 不符",
    "bar_missing": "raw 有行情、DB 沒有日線",
    "unmatched_bar": "已建立的標的仍掛 unmatched_bar",
    "chip_value": "籌碼 raw 與 DB 不符",
    "chip_revision": "較晚的法人 capture 與 DB 不同",
    "chip_missing": "raw 有籌碼、DB 沒有籌碼列",
    "action_value": "除權息 raw 與 DB 不符",
    "action_missing": "raw 有除權息、DB 沒有",
    "action_factor": "TWT48U 列因子與官方結果表不符",
    "action_not_official": "DB 有、官方結果表沒有的除權息",
    "action_official_unavailable": "官方結果表讀取失敗",
    "row_count": "普通股列數驟減",
    "institutional_refetch": "法人重抓失敗或沒有執行",
}
DETAIL_WARNING = re.compile(r"TWT49UDetail (?:unavailable|has no row) for (\S+) ")


@dataclass(frozen=True)
class Finding:
    check: str
    exchange: str
    symbol: str
    day: str
    field: str
    raw: Any
    db: Any
    note: str = ""


def stored_raw_dir(environ) -> str:
    """The raw directory app.config would use with ENVIRON, before _prepare moves it."""

    data = environ.get("STOCK_DATA_DIR") or str(BACKEND.parent / "data")
    return environ.get("STOCK_RAW_DIR") or str(Path(data) / "raw")


def _prepare(scratch: Path) -> None:
    """Make ``app``/``worker`` importable without touching the production paths.

    ``app.config`` creates its data and raw directories on import and
    ``app.db`` binds an engine to ``STOCK_DB_PATH``; both point into
    ``scratch`` so nothing of the watchdog's data directory is created,
    opened or written.  A process that already imported ``app.config`` (the
    tests) keeps its own paths.
    """

    if "app.config" not in sys.modules:
        # The captures it reads stay the real ones (app.raw_paths, #342).
        os.environ.setdefault("STOCK_STORED_RAW_DIR", stored_raw_dir(os.environ))
        os.environ["STOCK_DATA_DIR"] = str(scratch / "data")
        os.environ["STOCK_DB_PATH"] = str(scratch / "data" / "unused.db")
        os.environ["STOCK_RAW_DIR"] = str(scratch / "raw")
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def read_only_engine(db: str):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    uri = Path(db).resolve().as_uri() + "?mode=ro"

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only=ON")
        return conn

    return create_engine("sqlite://", creator=connect, poolclass=NullPool)


def _same(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return left == right
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


class DayCheck:
    def __init__(
        self,
        db: Any,
        day: date,
        *,
        fetcher: Callable[..., Any] | None = None,
        official: bool = True,
        official_budget: float = OFFICIAL_BUDGET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        from sqlalchemy import select

        from app.models import Instrument

        self.db = db
        self.day = day
        self.iso = day.isoformat()
        self.fetcher = fetcher
        self.official = official
        self.official_budget = official_budget
        self.clock = clock
        self.findings: list[Finding] = []
        self.facts: Counter[str] = Counter()
        self.pending: list[str] = []
        self.instruments = {
            (row.exchange, row.symbol): row
            for row in db.scalars(
                select(Instrument).where(Instrument.exchange.in_(EXCHANGES))
            )
        }

    def add(
        self,
        check: str,
        exchange: str,
        symbol: str,
        field: str,
        raw,
        db,
        note="",
        day=None,
    ):
        self.findings.append(
            Finding(check, exchange, symbol, day or self.iso, field, raw, db, note)
        )

    def _active(self, exchange: str, symbol: str, types: Iterable[str]) -> Any:
        instrument = self.instruments.get((exchange, symbol))
        if (
            instrument is None
            or instrument.status != "active"
            or instrument.instrument_type not in types
        ):
            return None
        return instrument

    # --- bars ---------------------------------------------------------------

    def bars(self) -> None:
        from sqlalchemy import select

        from app.models import Instrument, MarketBar, RawPayload
        from worker import instrument_repair as repair
        from worker.sources import OfficialDataError

        captures = [
            raw
            for raw in self.db.scalars(
                select(RawPayload)
                .where(RawPayload.data_as_of == self.iso)
                .order_by(RawPayload.collected_at, RawPayload.id)
            )
            if repair._is_quote_capture(raw.endpoint or "")
        ]
        parsed: dict[int, dict[tuple[str, str], Any] | str] = {}

        def records(raw) -> dict[tuple[str, str], Any] | str:
            if raw.id not in parsed:
                try:
                    bars = repair._quote_bars(raw, repair._load(raw))
                    parsed[raw.id] = {
                        (bar.exchange, bar.symbol): bar
                        for bar in bars
                        if bar.trading_date == self.day
                    }
                except (OSError, ValueError, OfficialDataError) as exc:
                    parsed[raw.id] = f"{type(exc).__name__}: {exc}"[:160]
                except repair.InstrumentRepairError as exc:
                    parsed[raw.id] = str(exc)[:160]
            return parsed[raw.id]

        raws = {raw.id: raw for raw in captures}
        stored = self.db.execute(
            select(MarketBar, Instrument)
            .join(Instrument, Instrument.id == MarketBar.instrument_id)
            .where(
                MarketBar.trading_date == self.day,
                Instrument.exchange.in_(EXCHANGES),
                Instrument.instrument_type != "index",
            )
        ).all()
        have = set()
        for bar, instrument in stored:
            key = (instrument.exchange, instrument.symbol)
            have.add(key)
            self.facts["bars"] += 1
            raw = raws.get(bar.raw_payload_id) if bar.raw_payload_id else None
            if raw is None and bar.raw_payload_id is not None:
                raw = self.db.get(RawPayload, bar.raw_payload_id)
            if raw is None or not repair._is_quote_capture(raw.endpoint or ""):
                self.facts["bars_without_quote_capture"] += 1
                self.add(
                    "bar_value",
                    *key,
                    "raw_payload_id",
                    "（當日行情 capture）",
                    bar.raw_payload_id,
                    "日線沒有指向當日行情 raw",
                )
                continue
            cited = records(raw)
            if isinstance(cited, str):
                self.add(
                    "bar_value",
                    *key,
                    "raw_payload_id",
                    cited,
                    bar.raw_payload_id,
                    "raw 讀不出來",
                )
                continue
            record = cited.get(key)
            if record is None:
                self.add(
                    "bar_value",
                    *key,
                    "raw_payload_id",
                    "（raw 沒有這一列）",
                    bar.raw_payload_id,
                )
                continue
            expected = {name: getattr(record, name) for name in BAR_FIELDS}
            expected["turnover"] = (record.turnover, record.turnover_status)
            actual = {name: getattr(bar, name) for name in BAR_FIELDS}
            actual["turnover"] = (bar.turnover, bar.turnover_status)
            for name, value in expected.items():
                if self._equal(value, actual[name]):
                    continue
                # A value another capture of the day supplies is a fill.
                if any(
                    not isinstance(other := records(capture), str)
                    and other.get(key) is not None
                    and self._equal(self._bar_value(other[key], name), actual[name])
                    for capture in captures
                ):
                    continue
                self.add(
                    "bar_value",
                    *key,
                    name,
                    self._shown(value),
                    self._shown(actual[name]),
                )
        missing: dict[tuple[str, str], int] = {}
        for capture in captures:
            found = records(capture)
            if isinstance(found, str):
                continue
            for key in found:
                if key not in have and self._active(*key, QUOTED_TYPES):
                    missing.setdefault(key, capture.id)
        for key, raw_id in sorted(missing.items()):
            record = records(raws[raw_id])[key]
            self.add(
                "bar_missing",
                *key,
                "close",
                record.close,
                None,
                f"raw_payload {raw_id}",
            )
        self._unmatched()

    @staticmethod
    def _bar_value(record: Any, name: str) -> Any:
        if name == "turnover":
            return (record.turnover, record.turnover_status)
        return getattr(record, name)

    @staticmethod
    def _equal(left: Any, right: Any) -> bool:
        if isinstance(left, tuple):
            return all(_same(a, b) for a, b in zip(left, right))
        return _same(left, right)

    @staticmethod
    def _shown(value: Any) -> Any:
        if isinstance(value, tuple):
            return f"{value[0]} ({value[1]})"
        return value

    def _sessions(self, count: int, exchange: str | None = None) -> list[date]:
        """The latest ``count`` stored stock sessions on or before the day."""
        from sqlalchemy import select

        from app.models import Instrument, MarketBar

        query = (
            select(MarketBar.trading_date)
            .join(Instrument, Instrument.id == MarketBar.instrument_id)
            .where(
                MarketBar.trading_date <= self.day,
                Instrument.instrument_type.in_(COMMON_STOCK_TYPES),
            )
        )
        if exchange is not None:
            query = query.where(Instrument.exchange == exchange)
        return list(
            self.db.scalars(
                query.distinct().order_by(MarketBar.trading_date.desc()).limit(count)
            )
        )

    def _unmatched(self) -> None:
        from sqlalchemy import select

        from app.models import DataQuality, MarketBar

        sessions = self._sessions(UNMATCHED_SESSIONS)
        if not sessions:
            return
        for row in self.db.scalars(
            select(DataQuality)
            .where(
                DataQuality.entity_type == "unmatched_bar",
                DataQuality.status != "complete",
                DataQuality.as_of_date >= min(sessions),
                DataQuality.as_of_date <= self.day,
            )
            .order_by(DataQuality.entity_key, DataQuality.as_of_date)
        ):
            exchange, _, symbol = row.entity_key.partition(":")
            instrument = self.instruments.get((exchange, symbol))
            if instrument is None:
                continue
            for text in (row.checks_json or {}).get("trading_dates") or []:
                bar = self.db.scalar(
                    select(MarketBar.id).where(
                        MarketBar.instrument_id == instrument.id,
                        MarketBar.trading_date == date.fromisoformat(text),
                    )
                )
                if bar is None:
                    self.add(
                        "unmatched_bar",
                        exchange,
                        symbol,
                        "market_bars",
                        "（raw 有成交）",
                        None,
                        f"data_quality {row.status}，標的已建立",
                        day=text,
                    )

    # --- chips --------------------------------------------------------------

    def chips(self) -> None:
        from sqlalchemy import select

        from app.chip_provenance import GROUP_FIELDS, INSTITUTIONAL, MARGIN
        from app.models import ChipSnapshot, Instrument, MarketBar
        from worker import chip_provenance
        from worker.pipeline import _safe_float

        captures = chip_provenance._Captures(self.db, self.day)
        if captures.unreadable:
            for item in captures.unreadable:
                self.add(
                    "chip_value",
                    "-",
                    "-",
                    "raw_payload_id",
                    item["error"][:160],
                    item["raw_payload_id"],
                    "raw 讀不出來",
                )

        def found(exchange: str, group: str) -> list[tuple[Any, dict[str, Any]]]:
            key = (exchange, group)
            result = []
            for capture in captures.by_group.get(key, []):
                try:
                    result.append((capture, captures.records(key, capture)))
                except chip_provenance.ProvenanceError as exc:
                    self.add(
                        "chip_value",
                        exchange,
                        "-",
                        "raw_payload_id",
                        str(exc)[:160],
                        capture.id,
                        "raw 與 sha256 不符",
                    )
            return result

        groups = {
            (exchange, group): found(exchange, group)
            for exchange in EXCHANGES
            for group in (INSTITUTIONAL, MARGIN)
        }
        have = set()
        for row, instrument in self.db.execute(
            select(ChipSnapshot, Instrument)
            .join(Instrument, Instrument.id == ChipSnapshot.instrument_id)
            .where(
                ChipSnapshot.trading_date == self.day,
                Instrument.exchange.in_(EXCHANGES),
            )
        ).all():
            key = (instrument.exchange, instrument.symbol)
            have.add(key)
            self.facts["chips"] += 1
            stored = {
                name: getattr(row, name)
                for group in (INSTITUTIONAL, MARGIN)
                for name in GROUP_FIELDS[group]
            }
            # Institutional: the latest capture with the symbol (#387).
            files = groups[(instrument.exchange, INSTITUTIONAL)]
            latest = next(
                (
                    (capture, rows[instrument.symbol])
                    for capture, rows in reversed(files)
                    if instrument.symbol in rows
                ),
                None,
            )
            if latest is not None:
                capture, record = latest
                expected = {
                    name: _safe_float(getattr(record, name))
                    for name in GROUP_FIELDS[INSTITUTIONAL]
                }
                # An empty incoming value never replaces a stored one.
                differs = [
                    name
                    for name, value in expected.items()
                    if value is not None and not _same(value, stored[name])
                ]
                if differs:
                    earlier = any(
                        instrument.symbol in rows
                        and all(
                            _same(
                                _safe_float(getattr(rows[instrument.symbol], name)),
                                stored[name],
                            )
                            for name in GROUP_FIELDS[INSTITUTIONAL]
                        )
                        for other, rows in files
                        if other.id != capture.id
                    )
                    for name in differs:
                        self.add(
                            "chip_revision" if earlier else "chip_value",
                            *key,
                            name,
                            expected[name],
                            stored[name],
                            f"最新 capture raw_payload {capture.id}",
                        )
            elif (
                any(stored[name] is not None for name in GROUP_FIELDS[INSTITUTIONAL])
                and files
            ):
                self.add(
                    "chip_value",
                    *key,
                    "foreign_buy",
                    "（raw 沒有這一列）",
                    stored["foreign_buy"],
                )
            # Margin: the cited capture, or any capture of the day (a fill).
            margins = groups[(instrument.exchange, MARGIN)]
            values = [
                (
                    capture,
                    {
                        name: _safe_float(getattr(rows[instrument.symbol], name))
                        for name in GROUP_FIELDS[MARGIN]
                    },
                )
                for capture, rows in margins
                if instrument.symbol in rows
            ]
            if not values:
                if (
                    any(stored[name] is not None for name in GROUP_FIELDS[MARGIN])
                    and margins
                ):
                    self.add(
                        "chip_value",
                        *key,
                        "margin_balance",
                        "（raw 沒有這一列）",
                        stored["margin_balance"],
                    )
                continue
            cited = next(
                (v for c, v in values if c.id == row.margin_raw_payload_id), None
            )
            for name in GROUP_FIELDS[MARGIN]:
                if all(v[name] is None for _c, v in values):
                    continue
                if cited is not None and _same(cited[name], stored[name]):
                    continue
                if any(_same(v[name], stored[name]) for _c, v in values):
                    continue
                first = next((v[name] for _c, v in values if v[name] is not None), None)
                self.add(
                    "chip_value",
                    *key,
                    name,
                    cited[name] if cited else first,
                    stored[name],
                )
        bars = {
            (exchange, symbol)
            for exchange, symbol in self.db.execute(
                select(Instrument.exchange, Instrument.symbol)
                .join(MarketBar, MarketBar.instrument_id == Instrument.id)
                .where(MarketBar.trading_date == self.day)
            )
        }
        missing: dict[tuple[str, str], tuple[str, int]] = {}
        for (exchange, group), files in groups.items():
            for capture, rows in files:
                for symbol in rows:
                    key = (exchange, symbol)
                    if (
                        key not in have
                        and key in bars
                        and self._active(*key, QUOTED_TYPES)
                    ):
                        missing.setdefault(key, (group, capture.id))
        for key, (group, raw_id) in sorted(missing.items()):
            self.add(
                "chip_missing",
                *key,
                group,
                "（raw 有這一列）",
                None,
                f"raw_payload {raw_id}",
            )

    # --- corporate actions --------------------------------------------------

    def _stored_actions(self) -> dict[tuple[str, str], list[Any]]:
        from sqlalchemy import select

        from app.models import CorporateAction, Instrument

        stored: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for action, instrument in self.db.execute(
            select(CorporateAction, Instrument)
            .join(Instrument, Instrument.id == CorporateAction.instrument_id)
            .where(
                CorporateAction.action_date == self.day,
                Instrument.exchange.in_(EXCHANGES),
            )
            .order_by(CorporateAction.id)
        ).all():
            stored[(instrument.exchange, instrument.symbol)].append(action)
        return stored

    @staticmethod
    def _written(record: Any) -> dict[str, Any]:
        """The fields ``pipeline._upsert_action`` writes for ``record``."""
        from worker.pipeline import action_factor_check

        check = action_factor_check(record)
        if check is not None and not check["passed"]:
            return {name: None for name in ACTION_FIELDS}
        return {name: getattr(record, name) for name in ACTION_FIELDS}

    def actions(self) -> None:
        from sqlalchemy import select

        from app.models import RawPayload
        from worker import instrument_repair as repair
        from worker.sources import (
            TPEX_ACTION_ENDPOINT,
            TWSE_ACTION_ENDPOINT,
            OfficialDataError,
            parse_tpex_action_rows,
            parse_twse_action_rows,
        )

        feeds = {
            TWSE_ACTION_ENDPOINT: parse_twse_action_rows,
            TPEX_ACTION_ENDPOINT: parse_tpex_action_rows,
        }
        stored = self._stored_actions()
        self.facts["actions"] = sum(len(rows) for rows in stored.values())
        parsed: dict[int, list[Any] | str] = {}

        def records(raw: Any, as_of: date) -> list[Any] | str:
            if raw.id not in parsed:
                try:
                    parsed[raw.id] = feeds[raw.endpoint](
                        repair._load(raw), as_of=as_of, payload_sha256=raw.sha256
                    )
                except (OSError, ValueError, OfficialDataError) as exc:
                    parsed[raw.id] = f"{type(exc).__name__}: {exc}"[:160]
                except repair.InstrumentRepairError as exc:
                    parsed[raw.id] = str(exc)[:160]
            return parsed[raw.id]

        # Each stored row against the daily feed row it was written from.
        for (exchange, symbol), rows in stored.items():
            for action in rows:
                raw = (
                    self.db.get(RawPayload, action.raw_payload_id)
                    if action.raw_payload_id
                    else None
                )
                if raw is None or raw.endpoint not in feeds:
                    continue
                found = records(raw, self.day)
                if isinstance(found, str):
                    self.add(
                        "action_value",
                        exchange,
                        symbol,
                        "raw_payload_id",
                        found,
                        action.raw_payload_id,
                        "raw 讀不出來",
                    )
                    continue
                record = next(
                    (
                        item
                        for item in found
                        if item.symbol == symbol
                        and item.action_date == self.day
                        and item.action_type == action.action_type
                    ),
                    None,
                )
                if record is None:
                    self.add(
                        "action_value",
                        exchange,
                        symbol,
                        "raw_payload_id",
                        "（raw 沒有這一列）",
                        action.raw_payload_id,
                    )
                    continue
                for name, value in self._written(record).items():
                    if not _same(value, getattr(action, name)):
                        self.add(
                            "action_value",
                            exchange,
                            symbol,
                            name,
                            value,
                            getattr(action, name),
                            f"raw_payload {raw.id}",
                        )
        # The day's TPEx feed and the latest TWT48U up to the day: TWT48U
        # announces future dates, so an ex-date that was not collected is
        # still in the last capture before it (#386 A2); an event a later
        # capture dropped (cancelled) is not expected.
        earliest = (self.day - timedelta(days=ANNOUNCEMENT_DAYS)).isoformat()
        latest: dict[str, Any] = {}
        for raw in self.db.scalars(
            select(RawPayload)
            .where(RawPayload.endpoint.in_(list(feeds)))
            .where(RawPayload.data_as_of <= self.iso, RawPayload.data_as_of >= earliest)
            .order_by(RawPayload.data_as_of, RawPayload.collected_at, RawPayload.id)
        ):
            if raw.data_as_of == self.iso or raw.endpoint == TWSE_ACTION_ENDPOINT:
                latest[raw.endpoint] = raw
        announced: dict[tuple[str, str], tuple[Any, int]] = {}
        for raw in latest.values():
            found = records(raw, self.day)
            if isinstance(found, str):
                continue
            for record in found:
                if record.action_date == self.day:
                    announced.setdefault(
                        (record.exchange, record.symbol), (record, raw.id)
                    )
        for key, (record, raw_id) in sorted(announced.items()):
            if key not in stored and self._active(*key, QUOTED_TYPES):
                self.add(
                    "action_missing",
                    *key,
                    "action_date",
                    self.iso,
                    None,
                    f"raw_payload {raw_id}",
                )
        if self.official:
            self._official(stored)

    def _official(self, stored: dict[tuple[str, str], list[Any]]) -> None:
        from worker import corporate_action_sync
        from worker.pipeline import action_factor_check
        from worker.sources import ActionRecord, OfficialDataError, fetch_json

        fetcher = self.fetcher or fetch_json
        started = self.clock()
        over = f"官方結果表的總預算 {self.official_budget:g} 秒用完"

        def counted(url: str, **kwargs: Any) -> Any:
            if self.clock() - started > self.official_budget:
                raise OfficialDataError(over)
            # One call; fetch_json's retries inside it are not counted.
            self.facts["official_requests_no_retry"] += 1
            return fetcher(url, **kwargs)

        try:
            records, _payloads, warnings = corporate_action_sync._fetch(
                self.day, self.day, counted
            )
        except OfficialDataError as exc:
            self.add(
                "action_official_unavailable",
                "-",
                "-",
                "TWT49U/exDailyQ",
                str(exc)[:160],
                None,
                "除權息官方核對未完成",
            )
            return
        unchecked = {
            match.group(1) for match in map(DETAIL_WARNING.search, warnings) if match
        }
        budget = [warning for warning in warnings if over in warning]
        if budget:
            self.add(
                "action_official_unavailable",
                "-",
                "-",
                "TWT49UDetail",
                over,
                None,
                f"{len(budget)} 個權類事件未核對",
            )
        for warning in warnings:
            if over in warning:
                continue
            self.add(
                "action_official_unavailable",
                "-",
                "-",
                "TWT49UDetail",
                warning[:160],
                None,
                "該筆未核對",
            )
        official: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for record in records:
            if record.action_date == self.day:
                official[(record.exchange, record.symbol)].append(record)
        self.facts["official_actions"] = sum(len(rows) for rows in official.values())
        for key, rows in sorted(official.items()):
            if key not in stored:
                if key in self.instruments:
                    self.add(
                        "action_missing",
                        *key,
                        "action_date",
                        self.iso,
                        None,
                        "官方結果表",
                    )
                continue
            for action in stored[key]:
                record = next(
                    (item for item in rows if item.action_type == action.action_type),
                    rows[0],
                )
                if action_factor_check(action) is None:
                    # TWT48U publishes no official prices: check its factor.
                    probe = ActionRecord(
                        symbol=key[1],
                        action_date=self.day,
                        action_type=action.action_type,
                        cash_dividend=action.cash_dividend,
                        stock_dividend_ratio=action.stock_dividend_ratio,
                        split_ratio=action.split_ratio,
                        reference_price=action.reference_price,
                        details=record.details,
                        exchange=key[0],
                    )
                    check = action_factor_check(probe)
                    if check is not None and not check["passed"]:
                        self.add(
                            "action_factor",
                            *key,
                            "factor",
                            check["official_factor"],
                            check["field_factor"],
                            f"參考價 官方 {check['official_reference']}、欄位推算 {check['implied_reference']}",
                        )
                    continue
                for name, value in self._written(record).items():
                    if not _same(value, getattr(action, name)):
                        self.add(
                            "action_value",
                            *key,
                            name,
                            value,
                            getattr(action, name),
                            "官方結果表",
                        )
        for key, rows in sorted(stored.items()):
            # An event whose detail could not be read is not in ``records``.
            if key in official or (key[0] == "TWSE" and key[1] in unchecked):
                continue
            for action in rows:
                self.add(
                    "action_not_official",
                    *key,
                    "action_type",
                    None,
                    action.action_type,
                    f"source {action.source}",
                )

    # --- row counts and the institutional refetch ----------------------------

    def row_counts(self) -> None:
        from sqlalchemy import func, select

        from app.models import Instrument, MarketBar

        for exchange in EXCHANGES:
            sessions = self._sessions(ROW_DROP_SESSIONS + 1, exchange)
            counts = dict(
                self.db.execute(
                    select(MarketBar.trading_date, func.count(MarketBar.id))
                    .join(Instrument, Instrument.id == MarketBar.instrument_id)
                    .where(
                        Instrument.exchange == exchange,
                        Instrument.instrument_type.in_(COMMON_STOCK_TYPES),
                        MarketBar.trading_date.in_(sessions),
                    )
                    .group_by(MarketBar.trading_date)
                ).all()
            )
            today = counts.get(self.day, 0)
            earlier = [counts[item] for item in sessions if item != self.day]
            self.facts[f"{exchange.lower()}_stock_bars"] = today
            if len(earlier) < ROW_DROP_SESSIONS:
                continue
            # The median of five counts is one of them, an integer.
            median = int(statistics.median(earlier[:ROW_DROP_SESSIONS]))
            if today * 100 <= median * (100 - ROW_DROP_PERCENT):
                self.add(
                    "row_count",
                    exchange,
                    "-",
                    "普通股日線列數",
                    median,
                    today,
                    f"前 {ROW_DROP_SESSIONS} 個交易日中位數，少 {1 - today / median:.1%}",
                )

    def refetch(self) -> None:
        from sqlalchemy import select

        from app.models import ScheduleRun, ScheduleRunStep

        row = self.db.execute(
            select(ScheduleRunStep.status, ScheduleRunStep.error, ScheduleRun.id)
            .join(ScheduleRun, ScheduleRun.id == ScheduleRunStep.schedule_run_id)
            .where(
                ScheduleRun.job == "daily",
                ScheduleRun.target_date == self.day,
                ScheduleRunStep.step == "institutional_refetch",
            )
            .order_by(ScheduleRun.id.desc())
            .limit(1)
        ).first()
        if row is None:
            self.facts["refetch"] = "none"
            started = self.db.scalar(
                select(ScheduleRun.started_at)
                .where(
                    ScheduleRun.job == "daily",
                    ScheduleRun.target_date == self.day,
                    ScheduleRun.status == "success",
                )
                .order_by(ScheduleRun.id.desc())
                .limit(1)
            )
            late = datetime.combine(self.day, datetime.min.time()) + timedelta(
                hours=LATE_COLLECT_UTC_HOUR
            )
            if started is not None and started < late:
                self.add(
                    "institutional_refetch",
                    "-",
                    "-",
                    "status",
                    "（應有之後的重抓）",
                    "（沒有）",
                    "daily 在 21:00 前成功、之後沒有重抓：法人只跟 21:00 前的資料比過",
                )
            return
        status, error, run_id = row
        self.facts["refetch"] = status
        if status == "running":
            self.pending.append(f"institutional_refetch_running:{run_id}")
        elif status in REFETCH_FAILED:
            self.add(
                "institutional_refetch",
                "-",
                "-",
                "status",
                "success",
                status,
                f"schedule_run {run_id}：{(error or '')[:120]}",
            )

    def run(self) -> None:
        self.refetch()
        if self.pending:
            return
        self.bars()
        self.chips()
        self.actions()
        self.row_counts()
        self.findings = merged(self.findings)


# Findings of one event from several sources become one (#408 review).
SAME_EVENT = {
    "action_missing": "action_missing",
    "unmatched_bar": "unmatched_bar",
    "bar_missing": "unmatched_bar",
}


def merged(findings: list[Finding]) -> list[Finding]:
    groups: dict[tuple[str, str, str, str], list[Finding]] = {}
    order: list[Finding | tuple[str, str, str, str]] = []
    for item in findings:
        name = SAME_EVENT.get(item.check)
        if name is None:
            order.append(item)
            continue
        key = (name, item.exchange, item.symbol, item.day)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    out: list[Finding] = []
    for entry in order:
        if isinstance(entry, Finding):
            out.append(entry)
            continue
        items = groups[entry]
        if len(items) == 1:
            out.append(items[0])
            continue
        # The quote row's close says more than a placeholder.
        base = next((i for i in items if i.check == "bar_missing"), items[0])
        notes = list(dict.fromkeys(i.note for i in items if i.note))
        out.append(replace(base, check=entry[0], note="；".join(notes)))
    return out


def _cell(value: Any) -> str:
    if value is None:
        return "（空）"
    if isinstance(value, float):
        text = f"{value:.10g}"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("`", "'").replace("\n", " ")


def details(check: DayCheck, *, limit: int | None = MAX_LISTED) -> str:
    findings = check.findings
    counts = Counter(item.check for item in findings)
    lines = [
        f"當日資料核對（交易日 {check.iso}，`tools/ops/data_check.py`）共 {len(findings)} 筆不一致：",
        "",
    ]
    lines += [
        f"- {LABELS.get(name, name)}（`{name}`）：{count} 筆"
        for name, count in sorted(counts.items())
    ]
    if "official_requests_no_retry" in check.facts:
        lines.append(
            "- 官方結果表請求數（不含重試）："
            f"{check.facts['official_requests_no_retry']}"
        )
    shown = findings if limit is None else findings[:limit]
    lines += [
        "",
        "| 項目 | 市場 | 代號 | 日期 | 欄位 | raw 值 | DB 值 | 說明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{item.check}` | {item.exchange} | {item.symbol} | {item.day} | `{item.field}` | {_cell(item.raw)} | {_cell(item.db)} | {_cell(item.note) if item.note else ''} |"
        for item in shown
    ]
    if len(shown) < len(findings):
        lines += [
            "",
            f"只列前 {len(shown)} 筆，共 {len(findings)} 筆。全部：`python tools/ops/watchdog_helper.py data-check <stock.db> {check.iso} --all`",
        ]
    return "\n".join(lines)


def status_line(check: DayCheck) -> str:
    counts = Counter(item.check for item in check.findings)
    if check.pending:
        state = "pending"
    elif check.findings:
        state = "violation"
    else:
        state = "ok"
    facts = [f"date={check.iso}", f"findings={len(check.findings)}"]
    facts += [f"{name}={count}" for name, count in sorted(counts.items())]
    facts += [f"{name}={value}" for name, value in sorted(check.facts.items())]
    if check.pending:
        facts.append(f"pending={','.join(check.pending)}")
    return f"data_check {state} " + " ".join(facts)


def data_check(
    db: str,
    day: str,
    *,
    official: bool = True,
    fetcher: Callable[..., Any] | None = None,
    limit: int | None = MAX_LISTED,
    scratch_parent: str | None = None,
) -> str:
    """The status line, then (on a violation) the Markdown details.

    The temporary directory is made in ``scratch_parent`` when given: the
    watchdog passes its own work directory, which its EXIT trap removes even
    when ``timeout`` kills this process before the ``finally`` below.
    """

    scratch = Path(tempfile.mkdtemp(prefix="data-check-", dir=scratch_parent))
    try:
        _prepare(scratch)
        from sqlalchemy.orm import Session

        target = date.fromisoformat(day)
        engine = read_only_engine(db)
        try:
            from sqlalchemy import inspect

            missing = sorted(set(TABLES) - set(inspect(engine).get_table_names()))
            if missing:
                return f"data_check skip date={day} missing_tables={','.join(missing)}"
            with Session(engine, autoflush=False) as session:
                check = DayCheck(session, target, fetcher=fetcher, official=official)
                check.run()
                session.rollback()
        finally:
            engine.dispose()
        line = status_line(check)
        if check.findings and not check.pending:
            return line + "\n" + details(check, limit=limit)
        return line
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
