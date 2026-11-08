"""Real daily K bars for the TWSE capitalization-weighted index and the TPEx index (Issue #552).

Each index has two monthly reports on its exchange's site (DATA_SOURCES 指數日 K):

* TWSE ``MI_5MINS_HIST`` (open/high/low/close, points) and ``FMTQIK``
  (shares and NT$ of the whole market: regular, odd-lot, after-hours fixed
  price and block trades);
* TPEx ``indexInfo/inx`` (open/high/low/close) and ``afterTrading/tradingIndex``
  (thousand shares and NT$ thousand of listed OTC stocks).

A bar is the price row of a day joined with that day's volume row.  A day
without a price row has no bar; a day whose open/high/low is missing or
inconsistent keeps them empty with ``price_reason`` (never the close); a day
missing from the volume report keeps its volume empty.

The TAIEX close-only rows ``collect`` writes from ``MI_INDEX`` (source
``twse_index``, the trading-day basis) are upgraded in place: only when the
report's close equals the stored close, recording the old source and raw in
``upgraded_rows``.  A TAIEX day without a stored row is not inserted (the
session basis stays ``MI_INDEX``'s), except by the backfill before the stock
history starts (``SESSION_BASIS_START``, Issue #563): there it is index
history only, never a session.  The TPEx index rows are written as new
rows of the ``TPEx``/``TPEX`` index instrument.  An existing real row keeps
its values (a differing value is a conflict) and only gains empty fields,
unless ``force``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.coverage import SESSION_BASIS_START
from app.indicators import SYNTHETIC_BAR_SOURCES
from app.models import Instrument, MarketBar

from .sources import (
    OfficialDataError,
    TPEX_INDEX_HISTORY_ENDPOINT,
    TPEX_INDEX_TRADING_ENDPOINT,
    TWSE_INDEX_HISTORY_ENDPOINT,
    TWSE_MARKET_TRADING_ENDPOINT,
    FetchedPayload,
    parse_roc_date,
)

TWSE_SOURCE = "twse_index_ohlcv"
TPEX_SOURCE = "tpex_index_ohlcv"
INDEX_BAR_SOURCES = frozenset({TWSE_SOURCE, TPEX_SOURCE})
TPEX_SYMBOL = "TPEX"
TPEX_NAME = "櫃買指數"
# Why open/high/low are empty (market_bars.price_reason).
SOURCE_MISSING_OHLC = "source_missing_ohlc"
SOURCE_INVALID_OHLC = "source_invalid_ohlc"
# market_bars.turnover_reason of a day the volume report did not list.
VOLUME_MISSING = "missing"
WARNING_PREFIX = "index bars"

TWSE_PRICE_TITLE = "發行量加權股價指數歷史資料"
TWSE_PRICE_FIELDS = ("日期", "開盤指數", "最高指數", "最低指數", "收盤指數")
TWSE_TRADING_FIELDS = ("日期", "成交股數", "成交金額")
TPEX_PRICE_TITLE = "櫃買指數(月查詢)"
TPEX_PRICE_FIELDS = ("日期", "開市", "最高", "最低", "收市")
TPEX_TRADING_TITLE = "日成交量值指數"
# The volume column was renamed in 2025-01; both are thousand shares.
TPEX_VOLUME_FIELDS = ("成交股數（仟股）", "成交張數")
TPEX_TURNOVER_FIELD = "金額（仟元）"
# TWSE answers a month without rows with this stat instead of "OK".
_NO_DATA_STATS = ("很抱歉，沒有符合條件的資料", "查詢日期大於今日")
_DECIMAL = re.compile(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?")
_INTEGER = re.compile(r"[+]?(?:\d+|\d{1,3}(?:,\d{3})+)")
_MAX_INTEGER = 9223372036854775807


@dataclass(frozen=True)
class PriceRow:
    trading_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    price_reason: str | None = None


@dataclass(frozen=True)
class VolumeRow:
    trading_date: date
    volume: int
    turnover: float


@dataclass(frozen=True)
class IndexBar:
    exchange: str
    symbol: str
    trading_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int | None
    turnover: float | None
    price_reason: str | None
    source: str
    price_sha256: str | None
    volume_sha256: str | None
    data_as_of: str | None = None


@dataclass
class Month:
    year: int
    month: int

    @classmethod
    def of(cls, day: date) -> "Month":
        return cls(day.year, day.month)

    @classmethod
    def parse(cls, value: str) -> "Month":
        match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
        if not match or not 1 <= int(match.group(2)) <= 12:
            raise ValueError(f"month must be YYYY-MM: {value!r}")
        return cls(int(match.group(1)), int(match.group(2)))

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return self.next().first_day - timedelta(days=1)

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def next(self) -> "Month":
        return Month(self.year + (self.month == 12), self.month % 12 + 1)

    def previous(self) -> "Month":
        return Month(self.year - (self.month == 1), (self.month - 2) % 12 + 1)

    def contains(self, day: date) -> bool:
        return (day.year, day.month) == (self.year, self.month)


# During the first days of a month the collect also reads the month before, so
# its last sessions are read once more after the month ends.
PREVIOUS_MONTH_DAYS = 7


def collect_months(end: date) -> list[Month]:
    month = Month.of(end)
    return [month.previous(), month] if end.day <= PREVIOUS_MONTH_DAYS else [month]


def month_range(first: Month, last: Month) -> list[Month]:
    months: list[Month] = []
    cursor = first
    while (cursor.year, cursor.month) <= (last.year, last.month):
        months.append(cursor)
        cursor = cursor.next()
    return months


# --- requests -----------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """One monthly report request: the URL stored as the raw endpoint and the form, if any."""

    exchange: str
    kind: str  # "price" or "volume"
    url: str
    method: str = "GET"
    data: dict[str, str] | None = None


def requests_for(exchange: str, month: Month) -> tuple[Request, Request]:
    if exchange == "TWSE":
        query = f"date={month.first_day:%Y%m%d}&response=json"
        return (
            Request(exchange, "price", f"{TWSE_INDEX_HISTORY_ENDPOINT}?{query}"),
            Request(exchange, "volume", f"{TWSE_MARKET_TRADING_ENDPOINT}?{query}"),
        )
    if exchange == "TPEx":
        form = {"date": f"{month.first_day:%Y/%m/%d}", "response": "json"}
        return (
            Request(exchange, "price", TPEX_INDEX_HISTORY_ENDPOINT, "POST", form),
            Request(exchange, "volume", TPEX_INDEX_TRADING_ENDPOINT, "POST", form),
        )
    raise ValueError(f"no index bars for exchange {exchange!r}")


# --- parsing ------------------------------------------------------------------


def _decimal(value: Any) -> float | None:
    """A finite positive price, or None for a blank/dash/malformed cell."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not _DECIMAL.fullmatch(text):
            return None
        try:
            number = float(Decimal(text.replace(",", "")))
        except InvalidOperation:
            return None
    return number if math.isfinite(number) and number > 0 else None


def _count(value: Any) -> int | None:
    """An exact nonnegative integer count (the 日行情成交量整數規則, DATA_SOURCES)."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_INTEGER else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _INTEGER.fullmatch(text):
        return None
    number = int(text.replace(",", "").lstrip("+") or "0")
    return number if number <= _MAX_INTEGER else None


def _no_data(payload: dict[str, Any]) -> bool:
    stat = str(payload.get("stat") or "")
    return any(marker in stat for marker in _NO_DATA_STATS)


def _single_table(payload: Any, title: str, name: str) -> dict[str, Any] | None:
    """The one table with ``title`` (TPEx shape), None for an explicit no-data answer."""

    if not isinstance(payload, dict) or str(payload.get("stat", "")).lower() != "ok":
        raise OfficialDataError(f"{name}: stat is not ok")
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise OfficialDataError(f"{name}: no tables")
    matches = [
        table
        for table in tables
        if isinstance(table, dict) and str(table.get("title", "")).strip() == title
    ]
    if len(matches) != 1:
        raise OfficialDataError(f"{name}: expected one table titled {title}")
    table = matches[0]
    if not table.get("data"):
        return None
    return table


def _field_positions(fields: Any, wanted: Iterable[str], name: str) -> dict[str, int]:
    if not isinstance(fields, list):
        raise OfficialDataError(f"{name}: fields missing")
    labels = [str(item).strip() for item in fields]
    positions: dict[str, int] = {}
    for label in wanted:
        if labels.count(label) != 1:
            raise OfficialDataError(f"{name}: field {label} not found exactly once")
        positions[label] = labels.index(label)
    return positions


def _row_date(value: Any, month: Month, name: str) -> date:
    day = parse_roc_date(value)
    if day is None:
        raise OfficialDataError(f"{name}: unreadable date {value!r}")
    if not month.contains(day):
        raise OfficialDataError(
            f"{name}: row date {day.isoformat()} is outside {month.label}"
        )
    return day


def _price_row(day: date, values: tuple[Any, Any, Any, Any]) -> PriceRow | None:
    open_, high, low, close = (_decimal(value) for value in values)
    if close is None:
        return None
    if open_ is None or high is None or low is None:
        return PriceRow(day, None, None, None, close, SOURCE_MISSING_OHLC)
    if not low <= min(open_, close) or not max(open_, close) <= high:
        return PriceRow(day, None, None, None, close, SOURCE_INVALID_OHLC)
    return PriceRow(day, open_, high, low, close)


def _price_rows(
    rows: list[Any],
    positions: dict[str, int],
    labels: tuple[str, ...],
    month: Month,
    name: str,
) -> list[PriceRow]:
    result: dict[date, PriceRow] = {}
    width = max(positions.values()) + 1
    for values in rows:
        if not isinstance(values, (list, tuple)) or len(values) < width:
            raise OfficialDataError(f"{name}: a row has too few columns")
        day = _row_date(values[positions[labels[0]]], month, name)
        if day in result:
            raise OfficialDataError(f"{name}: {day.isoformat()} listed twice")
        row = _price_row(day, tuple(values[positions[label]] for label in labels[1:]))
        if row is not None:
            result[day] = row
    return [result[day] for day in sorted(result)]


def parse_twse_prices(payload: Any, month: Month) -> list[PriceRow]:
    """``MI_5MINS_HIST``: one row per session of ``month``; [] when TWSE has none yet."""

    name = f"TWSE MI_5MINS_HIST {month.label}"
    if not isinstance(payload, dict):
        raise OfficialDataError(f"{name}: not a JSON object")
    if _no_data(payload):
        return []
    if str(payload.get("stat", "")).upper() != "OK":
        raise OfficialDataError(f"{name}: stat {payload.get('stat')!r}")
    if str(payload.get("date", "")) != f"{month.first_day:%Y%m%d}":
        raise OfficialDataError(f"{name}: reported date {payload.get('date')!r}")
    if TWSE_PRICE_TITLE not in str(payload.get("title", "")):
        raise OfficialDataError(f"{name}: title {payload.get('title')!r}")
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        raise OfficialDataError(f"{name}: data is not a list")
    if not rows:
        return []
    positions = _field_positions(payload.get("fields"), TWSE_PRICE_FIELDS, name)
    return _price_rows(rows, positions, TWSE_PRICE_FIELDS, month, name)


def parse_twse_volumes(payload: Any, month: Month) -> list[VolumeRow]:
    """``FMTQIK``: 成交股數 (shares) and 成交金額 (NT$) per session of ``month``."""

    name = f"TWSE FMTQIK {month.label}"
    if not isinstance(payload, dict):
        raise OfficialDataError(f"{name}: not a JSON object")
    if _no_data(payload):
        return []
    if str(payload.get("stat", "")).upper() != "OK":
        raise OfficialDataError(f"{name}: stat {payload.get('stat')!r}")
    if str(payload.get("date", "")) != f"{month.first_day:%Y%m%d}":
        raise OfficialDataError(f"{name}: reported date {payload.get('date')!r}")
    hints = str(payload.get("hints", ""))
    if "元" not in hints or "股" not in hints:
        raise OfficialDataError(f"{name}: units {hints!r} are not 元、股")
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        raise OfficialDataError(f"{name}: data is not a list")
    if not rows:
        return []
    positions = _field_positions(payload.get("fields"), TWSE_TRADING_FIELDS, name)
    return _volume_rows(rows, positions, TWSE_TRADING_FIELDS, 1, month, name)


def _volume_rows(
    rows: list[Any],
    positions: dict[str, int],
    labels: tuple[str, str, str],
    multiplier: int,
    month: Month,
    name: str,
) -> list[VolumeRow]:
    result: dict[date, VolumeRow] = {}
    width = max(positions.values()) + 1
    for values in rows:
        if not isinstance(values, (list, tuple)) or len(values) < width:
            raise OfficialDataError(f"{name}: a row has too few columns")
        day = _row_date(values[positions[labels[0]]], month, name)
        if day in result:
            raise OfficialDataError(f"{name}: {day.isoformat()} listed twice")
        volume = _count(values[positions[labels[1]]])
        turnover = _count(values[positions[labels[2]]])
        if volume is None or turnover is None:
            # An unreadable count is missing, never zero (the day keeps no volume).
            continue
        result[day] = VolumeRow(day, volume * multiplier, float(turnover * multiplier))
    return [result[day] for day in sorted(result)]


def parse_tpex_prices(payload: Any, month: Month) -> list[PriceRow]:
    """``indexInfo/inx``: 開市／最高／最低／收市 per session (Western dates)."""

    name = f"TPEx inx {month.label}"
    table = _single_table(payload, TPEX_PRICE_TITLE, name)
    if table is None:
        return []
    positions = _field_positions(table.get("fields"), TPEX_PRICE_FIELDS, name)
    return _price_rows(table["data"], positions, TPEX_PRICE_FIELDS, month, name)


def parse_tpex_volumes(payload: Any, month: Month) -> list[VolumeRow]:
    """``tradingIndex``: thousand shares and NT$ thousand, stored as shares and NT$."""

    name = f"TPEx tradingIndex {month.label}"
    table = _single_table(payload, TPEX_TRADING_TITLE, name)
    if table is None:
        return []
    fields = [str(item).strip() for item in table.get("fields") or []]
    volume_labels = [label for label in TPEX_VOLUME_FIELDS if label in fields]
    if len(volume_labels) != 1:
        raise OfficialDataError(
            f"{name}: volume field is not one of {list(TPEX_VOLUME_FIELDS)}: {fields}"
        )
    labels = ("日期", volume_labels[0], TPEX_TURNOVER_FIELD)
    positions = _field_positions(table.get("fields"), labels, name)
    return _volume_rows(table["data"], positions, labels, 1000, month, name)


PARSERS: dict[tuple[str, str], Callable[[Any, Month], list[Any]]] = {
    ("TWSE", "price"): parse_twse_prices,
    ("TWSE", "volume"): parse_twse_volumes,
    ("TPEx", "price"): parse_tpex_prices,
    ("TPEx", "volume"): parse_tpex_volumes,
}


def build_bars(
    exchange: str,
    prices: list[PriceRow],
    volumes: list[VolumeRow] | None,
    *,
    price_sha256: str | None,
    volume_sha256: str | None,
) -> list[IndexBar]:
    """Join the price rows with the volume rows of the same day."""

    symbol, source = (
        ("TAIEX", TWSE_SOURCE) if exchange == "TWSE" else (TPEX_SYMBOL, TPEX_SOURCE)
    )
    by_day = {row.trading_date: row for row in volumes or []}
    bars = []
    for price in prices:
        volume = by_day.get(price.trading_date)
        bars.append(
            IndexBar(
                exchange=exchange,
                symbol=symbol,
                trading_date=price.trading_date,
                open=price.open,
                high=price.high,
                low=price.low,
                close=price.close,
                volume=volume.volume if volume else None,
                turnover=volume.turnover if volume else None,
                price_reason=price.price_reason,
                source=source,
                price_sha256=price_sha256,
                volume_sha256=volume_sha256 if volume else None,
                data_as_of=price.trading_date.isoformat(),
            )
        )
    return bars


# --- fetching -----------------------------------------------------------------


@dataclass
class MonthResult:
    """What one exchange-month fetch produced (bars, captures, the warning if any)."""

    exchange: str
    month: Month
    bars: list[IndexBar] = field(default_factory=list)
    payloads: list[FetchedPayload] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def index_bar_warning(exchange: str, month: Month, exc: Exception) -> str:
    """The non-core warning text (pipeline.NONCORE_WARNING_PATTERN)."""

    return (
        f"{WARNING_PREFIX} unavailable for {exchange} {month.label}: "
        f"{type(exc).__name__}: {exc}"
    )


def fetch_month(
    exchange: str,
    month: Month,
    get: Callable[[Request], Any],
    capture: Callable[[Request, Any, str], FetchedPayload],
) -> MonthResult:
    """Fetch, capture and parse both reports of one exchange-month.

    ``get(request)`` returns the JSON; ``capture(request, payload, data_as_of)``
    stores it as raw.  Every answer is captured, rejected ones too; its
    ``data_as_of`` is the report's latest row date, the month's last day when
    it has no readable row.  A failed or rejected price report gives no bars;
    a failed volume report gives bars without volume.  Both leave a warning.
    """

    result = MonthResult(exchange, month)
    parsed: dict[str, tuple[list[Any], FetchedPayload]] = {}
    for request in requests_for(exchange, month):
        try:
            payload = get(request)
        except (OfficialDataError, ValueError, TypeError) as exc:
            result.warnings.append(index_bar_warning(exchange, month, exc))
            continue
        try:
            rows = PARSERS[(exchange, request.kind)](payload, month)
            error = None
        except (OfficialDataError, ValueError, TypeError, KeyError) as exc:
            rows, error = [], exc
        latest = max((row.trading_date for row in rows), default=month.last_day)
        captured = capture(request, payload, latest.isoformat())
        result.payloads.append(captured)
        if error is not None:
            result.warnings.append(index_bar_warning(exchange, month, error))
            continue
        parsed[request.kind] = (rows, captured)
    if "price" not in parsed:
        return result
    prices, price_capture = parsed["price"]
    volumes, volume_capture = parsed.get("volume", (None, None))
    result.bars = build_bars(
        exchange,
        prices,
        volumes,
        price_sha256=price_capture.sha256,
        volume_sha256=volume_capture.sha256 if volume_capture else None,
    )
    return result


# --- writing ------------------------------------------------------------------


OUTCOMES = (
    "inserted",
    "upgraded",
    "filled",
    "unchanged",
    "conflict",
    "close_mismatch",
    "no_close_row",
    "other_source",
)


@dataclass
class WriteResult:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(OUTCOMES, 0))
    upgraded_rows: list[dict[str, Any]] = field(default_factory=list)
    close_mismatches: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    skipped_dates: dict[str, list[str]] = field(default_factory=dict)
    written: list[tuple[int, date]] = field(default_factory=list)

    def merge(self, other: "WriteResult") -> None:
        for name, value in other.counts.items():
            self.counts[name] = self.counts.get(name, 0) + value
        self.upgraded_rows.extend(other.upgraded_rows)
        self.close_mismatches.extend(other.close_mismatches)
        self.conflicts.extend(other.conflicts)
        self.fills.extend(other.fills)
        for key, days in other.skipped_dates.items():
            self.skipped_dates.setdefault(key, []).extend(days)
        self.written.extend(other.written)

    def metadata(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "upgraded_rows": self.upgraded_rows,
            "close_mismatches": self.close_mismatches,
            "conflicts": self.conflicts,
            "fills": self.fills,
            "skipped_dates": self.skipped_dates,
        }


def tpex_index_instrument(db: Session) -> Instrument:
    item = db.scalar(
        select(Instrument).where(
            Instrument.exchange == "TPEx", Instrument.symbol == TPEX_SYMBOL
        )
    )
    if item is None:
        item = Instrument(
            market="TW",
            exchange="TPEx",
            symbol=TPEX_SYMBOL,
            name=TPEX_NAME,
            instrument_type="index",
            industry="Index",
            is_watchlisted=False,
            status="active",
        )
        db.add(item)
        db.flush()
    return item


def _taiex_instrument(db: Session) -> Instrument | None:
    return db.scalar(
        select(Instrument).where(
            Instrument.exchange == "TWSE",
            Instrument.symbol == "TAIEX",
            Instrument.instrument_type == "index",
        )
    )


def _same_close(first: float | None, second: float | None) -> bool:
    # Both publish two decimals; compare at that precision.
    return (
        first is not None
        and second is not None
        and round(float(first), 2) == round(float(second), 2)
    )


def _values(bar: IndexBar) -> dict[str, Any]:
    return {
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "adj_close": bar.close,
        "volume": bar.volume,
    }


def _turnover(bar: IndexBar) -> tuple[float, str, str | None]:
    if bar.turnover is None:
        return 0.0, "unavailable", VOLUME_MISSING
    return float(bar.turnover), "available", None


def _set_all(
    row: MarketBar,
    bar: IndexBar,
    price_raw: int | None,
    volume_raw: int | None,
) -> None:
    for name, value in _values(bar).items():
        setattr(row, name, value)
    if bar.volume is None:
        # MarketBar.volume defaults to 0 on insert; an unpublished volume is NULL.
        row.volume = null()
    row.turnover, row.turnover_status, row.turnover_reason = _turnover(bar)
    row.price_reason = bar.price_reason
    row.is_suspended = False
    row.source = bar.source
    row.data_as_of = datetime.combine(bar.trading_date, datetime.min.time())
    row.collected_at = utcnow()
    row.raw_payload_id = price_raw
    row.volume_raw_payload_id = volume_raw


def _merge_existing(
    row: MarketBar,
    bar: IndexBar,
    price_raw: int | None,
    volume_raw: int | None,
    result: WriteResult,
    label: str,
) -> str:
    """Same-source re-read: keep stored values, fill empty ones, list conflicts."""

    filled: list[str] = []
    conflicts = 0
    prices = {name: getattr(bar, name) for name in ("open", "high", "low")}
    if row.open is None and bar.open is not None:
        for name, value in prices.items():
            setattr(row, name, value)
        row.price_reason = None
        filled.append("ohlc")
    elif bar.open is not None and any(
        not _same_close(getattr(row, name), value) for name, value in prices.items()
    ):
        conflicts += 1
        result.conflicts.append(
            {
                "row": label,
                "field": "ohlc",
                "stored": [row.open, row.high, row.low],
                "incoming": [bar.open, bar.high, bar.low],
            }
        )
    if not _same_close(row.close, bar.close):
        conflicts += 1
        result.conflicts.append(
            {"row": label, "field": "close", "stored": row.close, "incoming": bar.close}
        )
    if row.volume is None and bar.volume is not None:
        row.volume = bar.volume
        row.turnover, row.turnover_status, row.turnover_reason = _turnover(bar)
        row.volume_raw_payload_id = volume_raw
        filled.append("volume")
    elif bar.volume is not None and (
        row.volume != bar.volume or row.turnover != float(bar.turnover or 0)
    ):
        conflicts += 1
        result.conflicts.append(
            {
                "row": label,
                "field": "volume",
                "stored": [row.volume, row.turnover],
                "incoming": [bar.volume, bar.turnover],
            }
        )
    if filled:
        result.fills.append(
            {
                "row": label,
                "fields": filled,
                "raw_payload_id": price_raw,
                "volume_raw_payload_id": volume_raw,
            }
        )
        return "filled"
    return "conflict" if conflicts else "unchanged"


def store_index_bars(
    db: Session,
    bars: Iterable[IndexBar],
    raw_id: Callable[[str | None], int | None],
    *,
    force: bool = False,
    history_before: date | None = None,
) -> WriteResult:
    """Write the bars (rules in the module docstring); the caller commits.

    ``history_before`` (the backfill passes ``SESSION_BASIS_START``, Issue
    #563): a TAIEX day before it without a stored row is inserted as index
    history.  There is no MI_INDEX row to upgrade before the stock history
    starts, and coverage never counts such a row as a session.
    """

    result = WriteResult()
    taiex = None
    tpex = None
    for bar in bars:
        if bar.exchange == "TWSE":
            taiex = taiex or _taiex_instrument(db)
            instrument = taiex
        else:
            tpex = tpex or tpex_index_instrument(db)
            instrument = tpex
        label = (
            f"market_bars:{bar.exchange}:{bar.symbol}:{bar.trading_date.isoformat()}"
        )
        price_raw = raw_id(bar.price_sha256)
        volume_raw = raw_id(bar.volume_sha256) if bar.volume_sha256 else None
        if price_raw is None:
            raise ValueError(f"no raw payload for {label}")
        row = (
            db.scalar(
                select(MarketBar).where(
                    MarketBar.instrument_id == instrument.id,
                    MarketBar.trading_date == bar.trading_date,
                )
            )
            if instrument is not None
            else None
        )
        if row is None:
            if instrument is None:
                # No TAIEX instrument yet: nothing to attach the day to.
                outcome = "no_close_row"
            elif bar.exchange == "TWSE" and not (
                history_before is not None and bar.trading_date < history_before
            ):
                # The session basis stays MI_INDEX's: no new TAIEX day here.
                outcome = "no_close_row"
            else:
                row = MarketBar(
                    instrument_id=instrument.id, trading_date=bar.trading_date
                )
                db.add(row)
                _set_all(row, bar, price_raw, volume_raw)
                outcome = "inserted"
        elif row.source in SYNTHETIC_BAR_SOURCES and bar.exchange == "TWSE":
            if not _same_close(row.close, bar.close):
                outcome = "close_mismatch"
                result.close_mismatches.append(
                    {
                        "trading_date": bar.trading_date.isoformat(),
                        "stored_close": row.close,
                        "report_close": bar.close,
                        "raw_payload_id": price_raw,
                    }
                )
            else:
                result.upgraded_rows.append(
                    {
                        "trading_date": bar.trading_date.isoformat(),
                        "old_source": row.source,
                        "old_raw_payload_id": row.raw_payload_id,
                        "raw_payload_id": price_raw,
                        "volume_raw_payload_id": volume_raw,
                    }
                )
                _set_all(row, bar, price_raw, volume_raw)
                outcome = "upgraded"
        elif row.source == bar.source:
            if force:
                if not _same_close(row.close, bar.close):
                    # Overwritten, but kept on record (PR #556 review).
                    result.conflicts.append(
                        {
                            "row": label,
                            "field": "close",
                            "stored": row.close,
                            "incoming": bar.close,
                            "forced": True,
                        }
                    )
                _set_all(row, bar, price_raw, volume_raw)
                outcome = "upgraded"
            else:
                outcome = _merge_existing(
                    row, bar, price_raw, volume_raw, result, label
                )
        else:
            outcome = "other_source"
        result.counts[outcome] += 1
        if outcome in {"no_close_row", "close_mismatch", "other_source"}:
            result.skipped_dates.setdefault(f"{bar.exchange}:{outcome}", []).append(
                bar.trading_date.isoformat()
            )
        if outcome in {"inserted", "upgraded", "filled"}:
            result.written.append((instrument.id, bar.trading_date))
    db.flush()
    return result


def warnings_for(result: WriteResult) -> list[str]:
    """Non-core warnings for rows the reports could not upgrade."""

    warnings = []
    if result.close_mismatches:
        days = ", ".join(item["trading_date"] for item in result.close_mismatches)
        # KD reads every high/low since the first bar, so a day left close-only
        # keeps the later TAIEX KD empty until it is upgraded (PR #556 review).
        warnings.append(
            f"{WARNING_PREFIX} close mismatch for TWSE TAIEX, not upgraded "
            f"(TAIEX KD stays empty from the first such day): {days}"
        )
    if result.conflicts:
        warnings.append(
            f"{WARNING_PREFIX} kept {len(result.conflicts)} stored value(s) that differ from the report"
        )
    return warnings


def taipei_today(now: datetime | None = None) -> date:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment + timedelta(hours=8)).date()


# --- backfill -----------------------------------------------------------------

RUN_TYPE = "index_bar_backfill"
# The index history starts about a year before the stock history (2024-09-30,
# app.coverage.SESSION_BASIS_START), so the index's 240-session average exists
# on the stocks' first day (#1 6723720803, Issue #563).  Earlier sessions of
# the first month are read but not written.
HISTORY_START = date(2023, 9, 1)
DEFAULT_FIRST_MONTH = "2023-09"
MAX_MONTHS = 36
EXCHANGES = ("TWSE", "TPEx")
RAW_SOURCES = {"TWSE": "twse", "TPEx": "tpex"}


def rebuild_derived(db: Session, instrument_ids: Iterable[int]) -> dict[str, Any]:
    """Rebuild the indicator and feature rows of instruments whose bars a backfill changed.

    ``technical_indicators`` in full (an earlier bar changes every later
    average) and ``technical_features`` as analyze writes them, so both match
    the new bars before the next daily.  Shared by the index, US index and TX
    history backfills (Issue #563).
    """

    from .indicator_batch import compute_market_indicators
    from .pipeline import _calculate_features

    changed = sorted(set(instrument_ids))
    if not changed:
        return {"status": "skipped", "reason": "no_changed_bars"}
    indicators = compute_market_indicators(db, rebuild=True, instrument_ids=changed)
    for instrument_id in changed:
        _calculate_features(db, db.get(Instrument, instrument_id))
    db.flush()
    return indicators


def _default_get(request: Request) -> Any:
    from .sources import fetch_json

    return fetch_json(request.url, method=request.method, data=request.data)


def backfill_index_bars(
    db: Session,
    *,
    first: Month,
    last: Month,
    get: Callable[[Request], Any] = _default_get,
    sleep: Callable[[float], None] | None = None,
    interval_seconds: float = 3.0,
    force: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """Fetch ``first``..``last`` for both indexes and write them (module docstring rules).

    One ``index_bar_backfill`` ingestion run.  Every report is fetched first
    (months oldest first, TWSE before TPEx, ``interval_seconds`` between
    requests); then the raws, the bars, the rebuilt indicators and features
    and the run's status are written and committed together, so a run killed
    or failing midway leaves every row as it was (rerun to fetch again).  The
    indicator and feature rows of the instruments it changed are rebuilt at the
    end.  Sessions before ``HISTORY_START`` are not written.
    A month after the current Taipei month or more than ``MAX_MONTHS`` months
    are refused before any request.
    """

    import time

    from app.models import IngestionRun

    from .pipeline import _upsert_raw_payload
    from .sources import capture_payload

    sleep = sleep or time.sleep
    today = today or taipei_today()
    months = month_range(first, last)
    if not months:
        raise ValueError(f"{first.label} is after {last.label}")
    if (last.year, last.month) > (today.year, today.month):
        raise ValueError(f"{last.label} is after the current month {today:%Y-%m}")
    if len(months) > MAX_MONTHS:
        raise ValueError(f"at most {MAX_MONTHS} months per run")
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=today,
        status="running",
        started_at=now,
        data_as_of=min(last.last_day, today).isoformat(),
        metadata_json={
            "first_month": first.label,
            "last_month": last.label,
            "force": force,
            "trigger": "manual",
        },
    )
    db.add(run)
    db.commit()
    manifest: dict[str, dict[str, Any]] = {}
    total = WriteResult()
    warnings: list[str] = []
    requests_made = 0

    def get_spaced(request: Request) -> Any:
        nonlocal requests_made
        if requests_made:
            sleep(interval_seconds)
        requests_made += 1
        return get(request)

    def capture(request: Request, payload: Any, data_as_of: str) -> FetchedPayload:
        return capture_payload(
            RAW_SOURCES[request.exchange], request.url, payload, data_as_of
        )

    # Fetch everything first (the captures are files only), then write it all
    # in one transaction: an upgraded TAIEX row points at this run's report,
    # and coverage trusts that report only once the run is success/partial.
    # A run killed or failing midway therefore changes no row (PR #556 review).
    fetched_months: list[tuple[str, MonthResult]] = []
    try:
        for month in months:
            for exchange in EXCHANGES:
                fetched_months.append(
                    (
                        f"{month.label}:{exchange}",
                        fetch_month(exchange, month, get_spaced, capture),
                    )
                )
        for key, fetched in fetched_months:
            raw_ids = {
                item.sha256: _upsert_raw_payload(db, run, item).id
                for item in fetched.payloads
            }
            bars = [
                bar
                for bar in fetched.bars
                if HISTORY_START <= bar.trading_date <= today
            ]
            written = store_index_bars(
                db,
                bars,
                raw_ids.get,
                force=force,
                history_before=SESSION_BASIS_START,
            )
            total.merge(written)
            warnings.extend(fetched.warnings)
            manifest[key] = {
                "bars": len(bars),
                "before_history_start": sum(
                    bar.trading_date < HISTORY_START for bar in fetched.bars
                ),
                "raw_payload_ids": sorted(raw_ids.values()),
                "counts": {k: v for k, v in written.counts.items() if v},
                "warnings": fetched.warnings,
            }
        changed = sorted({instrument_id for instrument_id, _ in total.written})
        indicators = rebuild_derived(db, changed)
        warnings.extend(warnings_for(total))
        failed_months = [key for key, item in manifest.items() if item["warnings"]]
        run.status = "partial" if failed_months or total.close_mismatches else "success"
        run.records = sum(
            total.counts[name] for name in ("inserted", "upgraded", "filled")
        )
        run.finished_at = utcnow()
        run.metadata_json = {
            **run.metadata_json,
            "coverage_manifest": manifest,
            **total.metadata(),
            "warnings": warnings,
            "requests": requests_made,
            "indicators": indicators,
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        failed = db.get(IngestionRun, run.id)
        if failed is not None:
            failed.status = "failed"
            failed.error = f"{type(exc).__name__}: {exc}"
            failed.finished_at = utcnow()
            failed.metadata_json = {
                **(failed.metadata_json or {}),
                "coverage_manifest": manifest,
                "requests": requests_made,
            }
            db.commit()
        raise
    return {
        "status": run.status,
        "run_id": run.id,
        "months": [month.label for month in months],
        "requests": requests_made,
        "counts": dict(total.counts),
        "upgraded_rows": len(total.upgraded_rows),
        "close_mismatches": total.close_mismatches,
        "conflicts": len(total.conflicts),
        "skipped_dates": total.skipped_dates,
        "indicators": indicators,
        "warnings": warnings,
    }


def run_index_bar_backfill(
    first: str | None, last: str | None, *, force: bool = False
) -> dict[str, Any]:
    from app.db import SessionLocal

    today = taipei_today()
    try:
        first_month = Month.parse(first or DEFAULT_FIRST_MONTH)
        last_month = Month.parse(last) if last else Month.of(today)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    with SessionLocal() as db:
        try:
            return backfill_index_bars(
                db, first=first_month, last=last_month, force=force, today=today
            )
        except ValueError as exc:
            db.rollback()
            return {"status": "failed", "error": str(exc)}
