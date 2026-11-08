"""Monthly index report payloads in the shapes the TWSE and TPEx sites return (Issue #552).

Shapes copied from the 2026-11-08 captures of ``MI_5MINS_HIST``, ``FMTQIK``,
``indexInfo/inx`` and ``afterTrading/tradingIndex`` (docs/DATA_SOURCES.md 指數日 K).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit

from worker import sources

ENDPOINTS = (
    sources.TWSE_INDEX_HISTORY_ENDPOINT,
    sources.TWSE_MARKET_TRADING_ENDPOINT,
    sources.TPEX_INDEX_HISTORY_ENDPOINT,
    sources.TPEX_INDEX_TRADING_ENDPOINT,
)


def roc(day: date) -> str:
    return f"{day.year - 1911}/{day.month:02d}/{day.day:02d}"


def _num(value: float) -> str:
    return f"{value:,.2f}"


def twse_prices(month: date, rows: Iterable[tuple]) -> dict[str, Any]:
    """rows: (day, open, high, low, close); a None cell is sent as ``--``."""
    data = [
        [roc(day), *("--" if v is None else _num(v) for v in values)]
        for day, *values in rows
    ]
    return {
        "stat": "OK",
        "title": f"{month.year - 1911}年{month.month:02d}月 發行量加權股價指數歷史資料",
        "date": f"{month:%Y%m}01",
        "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
        "data": data,
        "total": len(data),
    }


def twse_volumes(month: date, rows: Iterable[tuple]) -> dict[str, Any]:
    """rows: (day, shares, amount, index close)."""
    return {
        "stat": "OK",
        "date": f"{month:%Y%m}01",
        "title": f"{month.year - 1911}年{month.month:02d}月市場成交資訊",
        "hints": "單位：元、股",
        "fields": [
            "日期",
            "成交股數",
            "成交金額",
            "成交筆數",
            "發行量加權股價指數",
            "漲跌點數",
        ],
        "data": [
            [roc(day), f"{shares:,}", f"{amount:,}", "1,000", _num(close), "0.00"]
            for day, shares, amount, close in rows
        ],
        "notes": ["當日統計資訊含大盤、零股、盤後定價及鉅額交易，不含拍賣、標購。"],
    }


def tpex_prices(month: date, rows: Iterable[tuple]) -> dict[str, Any]:
    """rows: (day, open, high, low, close), Western dates as the site sends."""
    data = [
        [
            f"{day:%Y/%m/%d}",
            *("" if v is None else f"{v:.2f}" for v in values),
            "0.00",
        ]
        for day, *values in rows
    ]
    return {
        "date": f"{month:%Y%m}01",
        "stat": "ok",
        "tables": [
            {
                "title": "櫃買指數(月查詢)",
                "date": f"{month.year - 1911}/{month.month:02d}",
                "totalCount": len(data),
                "fields": ["日期", "開市", "最高", "最低", "收市", "漲/跌"],
                "data": data,
                "summary": [],
                "notes": [],
            }
        ],
    }


def tpex_volumes(
    month: date, rows: Iterable[tuple], *, volume_field: str = "成交張數"
) -> dict[str, Any]:
    """rows: (day, thousand shares, NT$ thousand, index close)."""
    data = [
        [roc(day), f"{volume:,}", f"{amount:,}", "1,000", close, 0.0]
        for day, volume, amount, close in rows
    ]
    return {
        "date": f"{month:%Y%m}01",
        "flagField": volume_field,
        "stat": "ok",
        "tables": [
            {
                "title": "日成交量值指數",
                "date": f"{month:%Y%m}01",
                "fields": [
                    "日期",
                    volume_field,
                    "金額（仟元）",
                    "筆數",
                    "櫃買指數",
                    "漲/跌",
                ],
                "notes": [
                    "上表為於等價、零股、盤後定價等交易系統交易之上櫃股票成交資訊。"
                ],
                "totalCount": len(data),
                "summary": [],
                "data": data,
            }
        ],
    }


def taifex_row(
    day: date,
    contract_month: str,
    values: tuple = (24000, 24100, 23900, 24050, 100000, 24040, 80000),
    *,
    contract: str = "TX",
    session: str = "一般",
) -> dict[str, str]:
    """One DailyMarketReportFut row; values: open, high, low, last, volume, settlement, OI."""
    open_, high, low, last, volume, settlement, interest = (
        "-" if value is None else str(value) for value in values
    )
    return {
        "Date": f"{day:%Y%m%d}",
        "Contract": contract,
        "ContractMonth(Week)": contract_month,
        "Open": open_,
        "High": high,
        "Low": low,
        "Last": last,
        "Change": "0",
        "%": "0.00%",
        "Volume": volume,
        "SettlementPrice": settlement if session == "一般" else "NULL",
        "OpenInterest": interest if session == "一般" else "-",
        "BestBid": last,
        "BestAsk": last,
        "HistoricalHigh": high,
        "HistoricalLow": low,
        "TradingHalt": "",
        "TradingSession": session,
        "Volume(ExecutionsAmongSpreadOrderAndSingleOrderOnly)": "",
    }


def taifex_report(day: date) -> list[dict[str, str]]:
    """The report of session ``day``: TX near/next month, a spread, the after-hours row, MTX."""
    from worker.futures_bars import near_month

    near = near_month(day)
    year, month = int(near[:4]), int(near[4:])
    following = f"{year + (month == 12):04d}{month % 12 + 1:02d}"
    return [
        taifex_row(day, near),
        taifex_row(day, near, session="盤後"),
        taifex_row(day, following, (24050, 24150, 23950, 24100, 3000, 24090, 9000)),
        taifex_row(day, f"{near}/{following}", (50, 55, 45, 50, 500, None, None)),
        taifex_row(day, near, contract="MTX"),
    ]


def requested_month(url: str, data: dict[str, str] | None) -> date:
    """The month a fetcher call asks for (TWSE query ``date``, TPEx form ``date``)."""
    if data and "date" in data:
        year, month, _ = (int(part) for part in data["date"].split("/"))
        return date(year, month, 1)
    value = parse_qs(urlsplit(url).query)["date"][0]
    return date(int(value[:4]), int(value[4:6]), 1)


def is_index_report(url: str) -> bool:
    return any(url.startswith(endpoint) for endpoint in ENDPOINTS)


def empty_report(url: str, data: dict[str, str] | None = None) -> dict[str, Any]:
    """The explicit no-data answer of each report (a month with no session yet)."""
    month = requested_month(url, data)
    if url.startswith(sources.TWSE_INDEX_HISTORY_ENDPOINT) or url.startswith(
        sources.TWSE_MARKET_TRADING_ENDPOINT
    ):
        return {"stat": "很抱歉，沒有符合條件的資料!"}
    if url.startswith(sources.TPEX_INDEX_HISTORY_ENDPOINT):
        return tpex_prices(month, [])
    return tpex_volumes(month, [])
