"""The TX (臺股期貨) near-month daily bar from the TAIFEX open-data report (Issue #552).

Source: TAIFEX OpenAPI ``DailyMarketReportFut`` (data.gov.tw 11319, 政府資料開放
授權條款第1版).  It only has the latest session of every futures contract and
takes no date, so the bars accumulate from the first collect on: a session the
collect missed cannot be fetched later (DATA_SOURCES 台指期).

One row per session of the ``TAIFEX``/``TX`` futures instrument: the regular
session (``TradingSession`` 一般; the after-hours session is not stored) of the
near-month contract.  The near month of session D is D's month until the third
Wednesday of that month (the last trading day; a holiday moves it later, which
the rule also covers), and the next month from that day on.  Each row keeps its
``contract_month``, ``open_interest`` (contracts) and ``settlement_price``; the
volume is contracts; no turnover is published.  Calendar spreads (``202611/202612``)
and weekly contracts are never the near month.  Bars are not adjusted across a
roll.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import Instrument, MarketBar

from .sources import OfficialDataError

SOURCE = "taifex_daily_futures"
EXCHANGE = "TAIFEX"
SYMBOL = "TX"
NAME = "臺股期貨近月"
CONTRACT = "TX"
REGULAR_SESSION = "一般"
SOURCE_MISSING_OHLC = "source_missing_ohlc"
NO_TURNOVER = "not_published"
WARNING_PREFIX = "futures bars"
_MONTH = re.compile(r"\d{6}")
_DECIMAL = re.compile(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?")
_INTEGER = re.compile(r"(?:\d+|\d{1,3}(?:,\d{3})+)")


@dataclass(frozen=True)
class FuturesBar:
    trading_date: date
    contract_month: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int
    settlement_price: float | None
    open_interest: int | None
    price_reason: str | None
    payload_sha256: str | None = None


def third_wednesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(2 - first.weekday()) % 7 + 14)


def near_month(day: date) -> str:
    """The near-month contract of session ``day`` (``YYYYMM``)."""

    if day < third_wednesday(day.year, day.month):
        return f"{day.year:04d}{day.month:02d}"
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return f"{year:04d}{month:02d}"


def _price(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
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
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value).strip()
    return int(text.replace(",", "")) if _INTEGER.fullmatch(text) else None


def report_date(payload: Any) -> date | None:
    """The one ``Date`` every row shares, or None."""

    if not isinstance(payload, list):
        return None
    values = {
        str(row.get("Date", "")).strip() for row in payload if isinstance(row, dict)
    }
    if len(values) != 1:
        return None
    value = values.pop()
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def parse_near_month(
    payload: Any, *, requested_date: date, payload_sha256: str | None = None
) -> FuturesBar:
    """The TX near-month regular-session row of ``requested_date``.

    Raises OfficialDataError when the report is not that session (not updated
    yet, or a later one), or has no single readable near-month row.
    """

    if not isinstance(payload, list) or not payload:
        raise OfficialDataError("TAIFEX DailyMarketReportFut is not a non-empty list")
    reported = report_date(payload)
    if reported != requested_date:
        raise OfficialDataError(
            f"TAIFEX DailyMarketReportFut reports {reported} instead of "
            f"{requested_date.isoformat()}"
        )
    contract = near_month(requested_date)
    rows = [
        row
        for row in payload
        if isinstance(row, dict)
        and str(row.get("Contract", "")).strip() == CONTRACT
        and str(row.get("TradingSession", "")).strip() == REGULAR_SESSION
        and str(row.get("ContractMonth(Week)", "")).strip() == contract
    ]
    if len(rows) != 1:
        raise OfficialDataError(
            f"TAIFEX DailyMarketReportFut has {len(rows)} TX {contract} regular rows"
        )
    row = rows[0]
    close = _price(row.get("Last"))
    volume = _count(row.get("Volume"))
    if close is None or volume is None:
        raise OfficialDataError(f"TX {contract} has no readable close or volume")
    open_, high, low = (_price(row.get(key)) for key in ("Open", "High", "Low"))
    reason = None
    if (
        open_ is None
        or high is None
        or low is None
        or not low <= min(open_, close)
        or not max(open_, close) <= high
    ):
        open_ = high = low = None
        reason = SOURCE_MISSING_OHLC
    return FuturesBar(
        trading_date=requested_date,
        contract_month=contract,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        settlement_price=_price(row.get("SettlementPrice")),
        open_interest=_count(row.get("OpenInterest")),
        price_reason=reason,
        payload_sha256=payload_sha256,
    )


def futures_warning(exc: Exception) -> str:
    """The non-core warning text (pipeline.NONCORE_WARNING_PATTERN)."""

    return f"{WARNING_PREFIX} unavailable for TAIFEX TX: {type(exc).__name__}: {exc}"


def futures_instrument(db: Session) -> Instrument:
    item = db.scalar(
        select(Instrument).where(
            Instrument.exchange == EXCHANGE, Instrument.symbol == SYMBOL
        )
    )
    if item is None:
        item = Instrument(
            market="TW",
            exchange=EXCHANGE,
            symbol=SYMBOL,
            name=NAME,
            instrument_type="futures",
            industry="Futures",
            is_watchlisted=False,
            status="active",
        )
        db.add(item)
        db.flush()
    return item


_FIELDS = (
    "contract_month",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "settlement_price",
    "open_interest",
    "price_reason",
)


@dataclass
class FuturesWriteResult:
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "inserted": 0,
            "replaced": 0,
            "unchanged": 0,
            "conflict": 0,
        }
    )
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    written: list[tuple[int, date]] = field(default_factory=list)

    def metadata(self) -> dict[str, Any]:
        return {"counts": dict(self.counts), "conflicts": self.conflicts}


def store_futures_bars(
    db: Session,
    bars: Iterable[FuturesBar],
    raw_id: Callable[[str | None], int | None],
    *,
    force: bool = False,
) -> FuturesWriteResult:
    """Insert new sessions; a stored session keeps its values (a difference is a conflict) unless ``force``."""

    result = FuturesWriteResult()
    instrument = None
    for bar in bars:
        instrument = instrument or futures_instrument(db)
        raw = raw_id(bar.payload_sha256)
        if raw is None:
            raise ValueError(f"no raw payload for TX {bar.trading_date.isoformat()}")
        row = db.scalar(
            select(MarketBar).where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date == bar.trading_date,
            )
        )
        incoming = {name: getattr(bar, name) for name in _FIELDS}
        if row is not None and not force:
            stored = {name: getattr(row, name) for name in _FIELDS}
            if stored == incoming:
                result.counts["unchanged"] += 1
            else:
                result.counts["conflict"] += 1
                result.conflicts.append(
                    {
                        "trading_date": bar.trading_date.isoformat(),
                        "stored": stored,
                        "incoming": incoming,
                        "raw_payload_id": raw,
                    }
                )
            continue
        outcome = "replaced" if row is not None else "inserted"
        if row is None:
            row = MarketBar(instrument_id=instrument.id, trading_date=bar.trading_date)
            db.add(row)
        for name, value in incoming.items():
            setattr(row, name, value)
        row.adj_close = bar.close
        row.turnover, row.turnover_status, row.turnover_reason = (
            0.0,
            "unavailable",
            NO_TURNOVER,
        )
        row.is_suspended = False
        row.source = SOURCE
        row.data_as_of = datetime.combine(bar.trading_date, datetime.min.time())
        row.collected_at = utcnow()
        row.raw_payload_id = raw
        row.volume_raw_payload_id = None
        result.counts[outcome] += 1
        result.written.append((instrument.id, bar.trading_date))
    db.flush()
    return result
