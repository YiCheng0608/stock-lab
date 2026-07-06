"""籌碼 adapter：三大法人、融資券、借券賣出餘額。

本檔只負責「抓取官方每日統計」與「純解析成 chips 正規化列」：

- TWSE（上市）：三大法人買賣超 `T86`、融資融券 `MI_MARGN`、信用額度總量管制餘額 `TWT93U`。
- TPEx（上櫃）：三大法人買賣明細 `insti/dailyTrade`、融資融券 `margin/balance`、
  融券借券賣出餘額 `margin/sbl`。

融資券官方表格以交易單位（張）揭露，本模型欄位以股數保存，因此解析時統一乘以 1000；
借券賣出餘額來源本身已是股數，不再轉換。
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.adapters.base import DataSource, NormalizedRow
from app.adapters.registry import register

_REQUEST_TIMEOUT = 10.0
_DEFAULT_THROTTLE_SECONDS = 0.35

_UA_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-lab-ingestion/1.0)"}
_TPEX_HEADERS = {
    **_UA_HEADERS,
    "Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/margin-trading/transactions.html",
}

_TWSE_INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
_TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
_TWSE_LENDING_URL = "https://www.twse.com.tw/exchangeReport/TWT93U"

_TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
_TPEX_MARGIN_URL = "https://www.tpex.org.tw/www/zh-tw/margin/balance"
_TPEX_LENDING_URL = "https://www.tpex.org.tw/www/zh-tw/margin/sbl"

_LOT_SIZE = 1000

TWSE_INSTITUTIONAL = "twse_institutional"
TWSE_MARGIN = "twse_margin"
TWSE_LENDING = "twse_lending"
TPEX_INSTITUTIONAL = "tpex_institutional"
TPEX_MARGIN = "tpex_margin"
TPEX_LENDING = "tpex_lending"


def _to_int(raw: Any) -> int | None:
    """把官方數字字串轉為 `int`；空值、破折號或不可解析值回傳 `None`。"""
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if not text or text in {"-", "--", "---"}:
        return None
    try:
        return int(Decimal(text))
    except InvalidOperation:
        return None


def _to_lot_shares(raw: Any) -> int | None:
    value = _to_int(raw)
    if value is None:
        return None
    return value * _LOT_SIZE


def _to_date(raw: Any) -> dt.date | None:
    """接受西元 `YYYYMMDD` / `YYYY/MM/DD` 與民國 `YYY/MM/DD` 日期。"""
    text = str(raw or "").strip()
    if not text:
        return None

    if len(text) == 8 and text.isdigit():
        year = int(text[:4])
        month = int(text[4:6])
        day = int(text[6:8])
    else:
        normalized = text.replace("年", "/").replace("月", "/").replace("日", "")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return None
        year, month, day = (int(part) for part in parts)
        if year < 1911:
            year += 1911

    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _first_table(raw: Mapping[str, Any], title_hint: str | None = None) -> Mapping[str, Any] | None:
    tables = raw.get("tables") or []
    if not isinstance(tables, list):
        return None
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        if title_hint is None or title_hint in str(table.get("title") or ""):
            return table
    return None


def _table_date(raw: Mapping[str, Any], table: Mapping[str, Any] | None = None) -> dt.date | None:
    return _to_date(raw.get("date")) or _to_date((table or {}).get("date"))


def _base_row(symbol: Any, market: str, trading_date: dt.date) -> NormalizedRow | None:
    normalized_symbol = str(symbol or "").strip()
    if not normalized_symbol:
        return None
    return {"symbol": normalized_symbol, "market": market, "date": trading_date}


def parse_twse_institutional(raw: Any) -> list[NormalizedRow]:
    """解析 TWSE 三大法人買賣超日報，產出上市個股法人買賣超股數。"""
    if not isinstance(raw, Mapping):
        return []
    trading_date = _table_date(raw)
    if trading_date is None:
        return []

    rows: list[NormalizedRow] = []
    for record in raw.get("data", []):
        if not isinstance(record, list) or len(record) < 12:
            continue
        row = _base_row(record[0], "listed", trading_date)
        foreign_net = _to_int(record[4])
        investment_trust_net = _to_int(record[10])
        dealer_net = _to_int(record[11])
        if row is None or None in (foreign_net, investment_trust_net, dealer_net):
            continue
        row.update(
            {
                "foreign_net": foreign_net,
                "investment_trust_net": investment_trust_net,
                "dealer_net": dealer_net,
            }
        )
        rows.append(row)
    return rows


def parse_tpex_institutional(raw: Any) -> list[NormalizedRow]:
    """解析 TPEx 三大法人買賣明細，產出上櫃個股法人買賣超股數。"""
    if not isinstance(raw, Mapping):
        return []
    table = _first_table(raw)
    trading_date = _table_date(raw, table)
    if table is None or trading_date is None:
        return []

    rows: list[NormalizedRow] = []
    for record in table.get("data", []):
        if not isinstance(record, list) or len(record) < 23:
            continue
        row = _base_row(record[0], "otc", trading_date)
        foreign_net = _to_int(record[4])
        investment_trust_net = _to_int(record[13])
        dealer_net = _to_int(record[22])
        if row is None or None in (foreign_net, investment_trust_net, dealer_net):
            continue
        row.update(
            {
                "foreign_net": foreign_net,
                "investment_trust_net": investment_trust_net,
                "dealer_net": dealer_net,
            }
        )
        rows.append(row)
    return rows


def parse_twse_margin(raw: Any) -> list[NormalizedRow]:
    """解析 TWSE 融資融券彙總表，將交易單位轉為股數。"""
    if not isinstance(raw, Mapping):
        return []
    table = _first_table(raw, "融資融券彙總")
    trading_date = _table_date(raw, table)
    if table is None or trading_date is None:
        return []

    rows: list[NormalizedRow] = []
    for record in table.get("data", []):
        if not isinstance(record, list) or len(record) < 13:
            continue
        row = _base_row(record[0], "listed", trading_date)
        margin_balance = _to_lot_shares(record[6])
        short_balance = _to_lot_shares(record[12])
        if row is None or None in (margin_balance, short_balance):
            continue
        row.update({"margin_balance": margin_balance, "short_balance": short_balance})
        rows.append(row)
    return rows


def parse_tpex_margin(raw: Any) -> list[NormalizedRow]:
    """解析 TPEx 融資融券餘額表，將交易單位（張）轉為股數。"""
    if not isinstance(raw, Mapping):
        return []
    table = _first_table(raw)
    trading_date = _table_date(raw, table)
    if table is None or trading_date is None:
        return []

    rows: list[NormalizedRow] = []
    for record in table.get("data", []):
        if not isinstance(record, list) or len(record) < 15:
            continue
        row = _base_row(record[0], "otc", trading_date)
        margin_balance = _to_lot_shares(record[6])
        short_balance = _to_lot_shares(record[14])
        if row is None or None in (margin_balance, short_balance):
            continue
        row.update({"margin_balance": margin_balance, "short_balance": short_balance})
        rows.append(row)
    return rows


def parse_twse_lending(raw: Any) -> list[NormalizedRow]:
    """解析 TWSE 信用額度總量管制餘額表，取借券賣出當日餘額（股數）。"""
    if not isinstance(raw, Mapping):
        return []
    trading_date = _table_date(raw)
    if trading_date is None:
        return []

    rows: list[NormalizedRow] = []
    for record in raw.get("data", []):
        if not isinstance(record, list) or len(record) < 13:
            continue
        row = _base_row(record[0], "listed", trading_date)
        securities_lending_balance = _to_int(record[12])
        if row is None or securities_lending_balance is None:
            continue
        row.update({"securities_lending_balance": securities_lending_balance})
        rows.append(row)
    return rows


def parse_tpex_lending(raw: Any) -> list[NormalizedRow]:
    """解析 TPEx 信用額度總量管制餘額表，取借券賣出當日餘額（股數）。"""
    if not isinstance(raw, Mapping):
        return []
    table = _first_table(raw)
    trading_date = _table_date(raw, table)
    if table is None or trading_date is None:
        return []

    rows: list[NormalizedRow] = []
    for record in table.get("data", []):
        if not isinstance(record, list) or len(record) < 13:
            continue
        row = _base_row(record[0], "otc", trading_date)
        securities_lending_balance = _to_int(record[12])
        if row is None or securities_lending_balance is None:
            continue
        row.update({"securities_lending_balance": securities_lending_balance})
        rows.append(row)
    return rows


def _merge_rows(source_rows: Iterable[NormalizedRow]) -> list[NormalizedRow]:
    merged: dict[tuple[str, str, dt.date], NormalizedRow] = {}
    for row in source_rows:
        symbol = row.get("symbol")
        market = row.get("market")
        trading_date = row.get("date")
        if not isinstance(symbol, str) or not isinstance(market, str) or not isinstance(
            trading_date, dt.date
        ):
            continue

        key = (symbol, market, trading_date)
        current = merged.setdefault(
            key,
            {
                "symbol": symbol,
                "market": market,
                "date": trading_date,
            },
        )
        current.update(
            {
                name: value
                for name, value in row.items()
                if name not in current or value is not None
            }
        )

    return sorted(merged.values(), key=lambda row: (row["market"], row["symbol"], row["date"]))


def parse_chips(raw: Any) -> list[NormalizedRow]:
    """合併六個官方來源，正規化為 `(symbol, market, date)` 一列。"""
    if not isinstance(raw, Mapping):
        return []

    source_rows: list[NormalizedRow] = []
    source_rows.extend(parse_twse_institutional(raw.get(TWSE_INSTITUTIONAL)))
    source_rows.extend(parse_twse_margin(raw.get(TWSE_MARGIN)))
    source_rows.extend(parse_twse_lending(raw.get(TWSE_LENDING)))
    source_rows.extend(parse_tpex_institutional(raw.get(TPEX_INSTITUTIONAL)))
    source_rows.extend(parse_tpex_margin(raw.get(TPEX_MARGIN)))
    source_rows.extend(parse_tpex_lending(raw.get(TPEX_LENDING)))
    return _merge_rows(source_rows)


@register("chips")
class ChipsSource(DataSource):
    """上市與上櫃籌碼來源：三大法人、融資券、借券賣出餘額。"""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        throttle_seconds: float = _DEFAULT_THROTTLE_SECONDS,
    ) -> None:
        self._client = client
        self._throttle_seconds = throttle_seconds

    def fetch(self, target: str | None, date: dt.date) -> dict[str, Any]:
        """取得指定日期六個官方來源原始 JSON；`target` 保留給契約簽章，不用於查詢。"""
        del target
        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        try:
            return self._fetch_all(client, date)
        finally:
            if self._client is None:
                client.close()

    def parse(self, raw: Any) -> list[NormalizedRow]:
        return parse_chips(raw)

    def fetch_range(
        self,
        date_from: dt.date,
        date_to: dt.date,
        *,
        throttle_seconds: float = _DEFAULT_THROTTLE_SECONDS,
    ) -> list[dict[str, Any]]:
        """日期區間便利方法；每一天回傳一份六來源原始 payload，解析仍由呼叫端另外執行。"""
        raws: list[dict[str, Any]] = []
        current = date_from
        while current <= date_to:
            raws.append(self.fetch(None, current))
            if current != date_to and throttle_seconds > 0:
                time.sleep(throttle_seconds)
            current += dt.timedelta(days=1)
        return raws

    def _fetch_all(self, client: httpx.Client, date: dt.date) -> dict[str, Any]:
        sources = [
            (
                TWSE_INSTITUTIONAL,
                _TWSE_INSTITUTIONAL_URL,
                {"date": date.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"},
                _UA_HEADERS,
            ),
            (
                TWSE_MARGIN,
                _TWSE_MARGIN_URL,
                {"date": date.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"},
                _UA_HEADERS,
            ),
            (
                TWSE_LENDING,
                _TWSE_LENDING_URL,
                {"date": date.strftime("%Y%m%d"), "response": "json"},
                _UA_HEADERS,
            ),
            (
                TPEX_INSTITUTIONAL,
                _TPEX_INSTITUTIONAL_URL,
                {
                    "date": date.strftime("%Y/%m/%d"),
                    "type": "Daily",
                    "sect": "EW",
                    "response": "json",
                },
                _TPEX_HEADERS,
            ),
            (
                TPEX_MARGIN,
                _TPEX_MARGIN_URL,
                {"date": date.strftime("%Y/%m/%d"), "response": "json"},
                _TPEX_HEADERS,
            ),
            (
                TPEX_LENDING,
                _TPEX_LENDING_URL,
                {"date": date.strftime("%Y/%m/%d"), "response": "json"},
                _TPEX_HEADERS,
            ),
        ]

        raw: dict[str, Any] = {}
        for index, (name, url, params, headers) in enumerate(sources):
            raw[name] = self._fetch_json(client, url, params=params, headers=headers)
            if index != len(sources) - 1 and self._throttle_seconds > 0:
                time.sleep(self._throttle_seconds)
        return raw

    @staticmethod
    def _fetch_json(
        client: httpx.Client,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Any:
        resp = client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


__all__ = [
    "ChipsSource",
    "parse_chips",
    "parse_twse_institutional",
    "parse_tpex_institutional",
    "parse_twse_margin",
    "parse_tpex_margin",
    "parse_twse_lending",
    "parse_tpex_lending",
]
