"""The TX (臺股期貨) near-month daily bar from the TAIFEX open-data report (Issue #552).

Source: TAIFEX OpenAPI ``DailyMarketReportFut`` (data.gov.tw 11319, 政府資料開放
授權條款第1版).  It only has the latest published session of every futures
contract and takes no date.  It answers a UTF-8 CSV with Chinese headers
(since 2026-11, Issue #586) or, as before, a JSON list; both are read.  The
report changes to a session late in the evening or the next day, so the daily
collect stores the session the report holds (``report_date``), when that is a
verified session the database has no TX row of; a session the report has
moved past is filled from the website history (``worker.futures_history``).

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

import base64
import csv
import io
import json
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
CSV_ENCODING = "utf-8"
# The CSV answer's headers and the JSON keys they carry (2026-11-09 answer,
# Issue #586): the CSV rows are read as the JSON rows are.
CSV_FIELDS = {
    "日期": "Date",
    "契約代號": "Contract",
    "到期月份(週別)": "ContractMonth(Week)",
    "開盤價": "Open",
    "最高價": "High",
    "最低價": "Low",
    "最後成交價": "Last",
    "漲跌價": "Change",
    "漲跌%": "%",
    "合計成交量": "Volume",
    "結算價": "SettlementPrice",
    "未沖銷契約數": "OpenInterest",
    "最後最佳買價": "BestBid",
    "最後最佳賣價": "BestAsk",
    "歷史最高價": "HistoricalHigh",
    "歷史最低價": "HistoricalLow",
    "是否因訊息面暫停交易": "TradingHalt",
    "交易時段": "TradingSession",
    "價差對單式委託成交量": "Volume(ExecutionsAmongSpreadOrderAndSingleOrderOnly)",
}
# The columns the near-month bar is read from: a CSV without one is refused.
CSV_REQUIRED = (
    "日期",
    "契約代號",
    "到期月份(週別)",
    "開盤價",
    "最高價",
    "最低價",
    "最後成交價",
    "合計成交量",
    "結算價",
    "未沖銷契約數",
    "交易時段",
)
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


def capture_form(answer: Any) -> Any:
    """The answer as its raw capture stores it.

    A JSON list stays as it is; a CSV (bytes or text, UTF-8 with or without a
    byte-order mark) becomes ``{"format": "csv", "encoding": "utf-8", "csv":
    <text>}``; bytes that are not UTF-8 are kept as base64 so the raw still
    records the answer (``report_rows`` then refuses it).
    """

    if isinstance(answer, (bytes, bytearray)):
        data = bytes(answer)
        try:
            answer = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return {
                "format": "binary",
                "base64": base64.b64encode(data).decode("ascii"),
            }
    if isinstance(answer, str):
        text = answer.lstrip(chr(0xFEFF))
        if text.lstrip().startswith(("[", "{")):
            try:
                return json.loads(text)
            except ValueError:
                pass
        return {"format": "csv", "encoding": CSV_ENCODING, "csv": text}
    return answer


def _csv_rows(text: Any) -> list[dict[str, Any]]:
    if not isinstance(text, str):
        raise OfficialDataError("TAIFEX DailyMarketReportFut CSV is not text")
    body = text.lstrip(chr(0xFEFF))
    if body.lstrip().startswith("<"):
        raise OfficialDataError("TAIFEX DailyMarketReportFut answered an HTML page")
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        raise OfficialDataError("TAIFEX DailyMarketReportFut answered nothing")
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = [cell.strip() for cell in next(reader)]
    missing = [name for name in CSV_REQUIRED if name not in header]
    if missing:
        raise OfficialDataError(
            f"TAIFEX DailyMarketReportFut CSV has no {', '.join(missing[:3])} "
            f"column: {header[:5]}"
        )
    needed = max(header.index(name) for name in CSV_REQUIRED) + 1
    rows: list[dict[str, Any]] = []
    for cells in reader:
        if len(cells) < needed:
            raise OfficialDataError(
                f"TAIFEX DailyMarketReportFut CSV row has {len(cells)} columns: "
                f"{cells[:3]}"
            )
        rows.append(
            {
                CSV_FIELDS.get(name, name): cells[i].strip()
                for i, name in enumerate(header)
                if name and i < len(cells)
            }
        )
    return rows


def report_rows(payload: Any) -> list[dict[str, Any]]:
    """The report's rows under the JSON keys, from either answer format.

    ``payload`` is the JSON list, the CSV capture (``capture_form``) or the
    CSV itself.  OfficialDataError for anything else, an HTML page, a CSV
    without the near-month columns or with a row shorter than them.
    """

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, (bytes, bytearray, str)):
        return report_rows(capture_form(payload))
    if isinstance(payload, dict) and payload.get("format") == "csv":
        return _csv_rows(payload.get("csv"))
    raise OfficialDataError(
        "TAIFEX DailyMarketReportFut is neither a JSON list nor a UTF-8 CSV"
    )


def _rows_date(rows: list[dict[str, Any]]) -> date | None:
    values = {str(row.get("Date", "")).strip() for row in rows}
    if len(values) != 1:
        return None
    value = values.pop()
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def report_date(payload: Any) -> date | None:
    """The one ``Date`` every row shares (the session the report holds), or None."""

    try:
        return _rows_date(report_rows(payload))
    except OfficialDataError:
        return None


def parse_near_month(payload: Any, *, payload_sha256: str | None = None) -> FuturesBar:
    """The TX near-month regular-session row of the session the report holds.

    The session is the report's own ``Date`` (``report_date``), whatever day
    the collect is for: the caller decides whether that session is stored.
    Raises OfficialDataError for an unreadable answer, rows of more than one
    date, or no single readable near-month row.
    """

    rows_all = report_rows(payload)
    if not rows_all:
        raise OfficialDataError("TAIFEX DailyMarketReportFut has no rows")
    reported = _rows_date(rows_all)
    if reported is None:
        raise OfficialDataError(
            "TAIFEX DailyMarketReportFut rows do not share one readable date"
        )
    contract = near_month(reported)
    rows = [
        row
        for row in rows_all
        if str(row.get("Contract", "")).strip() == CONTRACT
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
        trading_date=reported,
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


def not_published_warning(day: date, reported: date) -> str:
    """The report still holds an earlier session than ``day`` (non-core)."""

    return (
        f"{WARNING_PREFIX} not yet published for TAIFEX TX {day.isoformat()}: "
        f"DailyMarketReportFut reports {reported.isoformat()}"
    )


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
            "kept_other_source": 0,
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
    source: str = SOURCE,
) -> FuturesWriteResult:
    """Insert new sessions; a stored session keeps its values (a difference is a conflict) unless ``force``.

    ``source`` names the report the rows come from: the OpenAPI daily report
    (``SOURCE``) or the website history (``worker.futures_history``, Issue
    #563).  A stored row of another source is never replaced, even with
    ``force``: with the same values it is ``kept_other_source`` (the two
    reports of one session, Issue #586), with other values a conflict.
    """

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
        if row is not None and (not force or row.source != source):
            stored = {name: getattr(row, name) for name in _FIELDS}
            if stored == incoming:
                result.counts[
                    "unchanged" if row.source == source else "kept_other_source"
                ] += 1
            else:
                result.counts["conflict"] += 1
                result.conflicts.append(
                    {
                        "trading_date": bar.trading_date.isoformat(),
                        "stored": {**stored, "source": row.source},
                        "incoming": {**incoming, "source": source},
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
        row.source = source
        row.data_as_of = datetime.combine(bar.trading_date, datetime.min.time())
        row.collected_at = utcnow()
        row.raw_payload_id = raw
        row.volume_raw_payload_id = None
        result.counts[outcome] += 1
        result.written.append((instrument.id, bar.trading_date))
    db.flush()
    return result
