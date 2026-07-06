"""公開資訊觀測站（MOPS）除權息、股本變動與股票基本資料 adapter。

本檔同時處理三套公開資訊觀測站頁面，但抓取與解析仍明確分離：

- `parse_security_master`：股票基本資料，輸出 `row_type="security"`，供 `securities` 父表使用。
- `parse_dividend_events`：除權息事件，輸出現金股利與股票股利（每股配股數）。
- `parse_capital_changes`：股本變動，輸出變動股數與變動後股本股數。

MOPS 頁面多為 HTML table，且欄名會隨頁面小幅調整；解析採「欄名語意」而非固定欄位
index，讓固定樣本與官方頁面微調時都能維持穩定。三個 parse 函式皆為純函式，不打外網。
"""

from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import DataSource, NormalizedRow
from app.adapters.registry import register

_MOPS_BASIC_URL = "https://mops.twse.com.tw/mops/web/ajax_t51sb01"
_MOPS_DIVIDEND_URL = "https://mops.twse.com.tw/mops/web/ajax_t108sb27"
_MOPS_CAPITAL_URL = "https://mops.twse.com.tw/mops/web/ajax_t05st03"

_REQUEST_TIMEOUT = 20.0
_DEFAULT_THROTTLE_SECONDS = 0.35

_MOPS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; stock-lab-ingestion/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

_MOPS_SECURITY_ERROR_MARKERS = (
    "FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED",
    "因為安全性考量",
)

_MARKET_TO_TYPEK = {
    "listed": "sii",
    "otc": "otc",
}

_TYPEK_TO_MARKET = {
    "sii": "listed",
    "上市": "listed",
    "twse": "listed",
    "listed": "listed",
    "otc": "otc",
    "上櫃": "otc",
    "tpex": "otc",
}


def _clean_text(value: Any) -> str:
    """把 HTML cell 或一般值正規化成單行文字。"""
    if value is None:
        return ""
    text = value.get_text(" ", strip=True) if hasattr(value, "get_text") else str(value)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _extract_tables(raw: Any) -> list[list[list[str]]]:
    """從 HTML/XML 文字抽出 table -> rows -> cells；格式不符時回空清單。"""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    if not isinstance(raw, str):
        return []

    soup = BeautifulSoup(raw, "lxml")
    tables: list[list[list[str]]] = []
    for table in soup.find_all("table"):
        parsed_rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [_clean_text(cell) for cell in tr.find_all(["th", "td"])]
            if any(cells):
                parsed_rows.append(cells)
        if parsed_rows:
            tables.append(parsed_rows)
    return tables


def _records_from_table(table: list[list[str]], header_predicate) -> list[dict[str, str]]:
    """以符合條件的表頭列，把其後資料列轉成 dict。"""
    for index, row in enumerate(table):
        if not header_predicate(row):
            continue
        headers = [_normalize_header(cell) for cell in row]
        records: list[dict[str, str]] = []
        for data_row in table[index + 1 :]:
            if len(data_row) < 2:
                continue
            padded = data_row[: len(headers)] + [""] * max(0, len(headers) - len(data_row))
            record = {
                header: padded[cell_index].strip()
                for cell_index, header in enumerate(headers)
                if header
            }
            if any(record.values()):
                records.append(record)
        return records
    return []


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("　", " ").strip())


def _coerce_records(raw: Any, header_predicate) -> list[dict[str, str]]:
    """接受 list[dict] 固定樣本或 HTML table，轉成同一種 record 形狀。"""
    if isinstance(raw, Mapping):
        if isinstance(raw.get("records"), list):
            return [_stringify_record(record) for record in raw["records"] if isinstance(record, Mapping)]
        for key in ("html", "body", "text"):
            if key in raw:
                return _coerce_records(raw[key], header_predicate)
    if isinstance(raw, list):
        return [_stringify_record(record) for record in raw if isinstance(record, Mapping)]

    records: list[dict[str, str]] = []
    for table in _extract_tables(raw):
        records.extend(_records_from_table(table, header_predicate))
    return records


def _stringify_record(record: Mapping[str, Any]) -> dict[str, str]:
    return {_normalize_header(str(key)): _clean_text(value) for key, value in record.items()}


def _cell(record: Mapping[str, str], aliases: Iterable[str]) -> str:
    """依多組可能欄名取值；支援完整相等與包含比對。"""
    normalized_aliases = [_normalize_header(alias) for alias in aliases]
    for alias in normalized_aliases:
        value = record.get(alias)
        if value:
            return value
    for header, value in record.items():
        if value and any(alias in header for alias in normalized_aliases):
            return value
    return ""


def _to_decimal(value: Any) -> Decimal | None:
    text = _clean_text(value)
    if not text or text in {"-", "--", "---", "無", "不適用", "N/A"}:
        return None
    text = text.replace(",", "").replace("，", "")
    text = re.sub(r"[％%元股\s]", "", text)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _to_int(value: Any) -> int | None:
    number = _to_decimal(value)
    if number is None:
        return None
    return int(number)


def _parse_date(value: Any) -> dt.date | None:
    """解析民國/西元日期；支援 `113/7/1`、`2024-07-01`、`113年7月1日`。"""
    text = _clean_text(value)
    if not text or text in {"-", "--", "---", "無"}:
        return None
    numbers = [int(part) for part in re.findall(r"\d+", text)]
    if len(numbers) < 3:
        return None
    year, month, day = numbers[:3]
    if year < 1911:
        year += 1911
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _normalize_symbol(value: Any) -> str:
    text = _clean_text(value)
    match = re.search(r"[0-9A-Za-z]{2,16}", text)
    return match.group(0) if match else text


def _normalize_market(value: Any, fallback: str | None = None) -> str | None:
    text = _clean_text(value).lower()
    if text in _TYPEK_TO_MARKET:
        return _TYPEK_TO_MARKET[text]
    for key, market in _TYPEK_TO_MARKET.items():
        if key.lower() in text:
            return market
    return fallback


def _par_value(record: Mapping[str, str]) -> Decimal:
    raw = _cell(record, ["普通股每股面額", "每股面額", "面額"])
    parsed = _to_decimal(raw)
    return parsed if parsed and parsed > 0 else Decimal("10")


def _capital_amount_to_shares(value: Any, par_value: Decimal) -> int | None:
    amount = _to_decimal(value)
    if amount is None:
        return None
    try:
        return int(amount / par_value)
    except (InvalidOperation, ZeroDivisionError):
        return None


def _security_header(row: list[str]) -> bool:
    joined = "".join(_normalize_header(cell) for cell in row)
    return "公司代號" in joined and ("公司名稱" in joined or "證券名稱" in joined)


def _dividend_header(row: list[str]) -> bool:
    joined = "".join(_normalize_header(cell) for cell in row)
    return "公司代號" in joined and ("除權息" in joined or "除息交易日" in joined or "除權交易日" in joined)


def _capital_header(row: list[str]) -> bool:
    joined = "".join(_normalize_header(cell) for cell in row)
    has_date = any(key in joined for key in ("變更日期", "異動日期", "發行日期", "核准日期", "基準日"))
    has_capital = any(key in joined for key in ("股本", "股數", "資本額"))
    return has_date and has_capital


def parse_security_master(raw: Any, *, market: str | None = None) -> list[NormalizedRow]:
    """解析 MOPS 股票基本資料頁，輸出 `securities` 需要的父表列。"""
    context_market = _normalize_market(_context_value(raw, "market"), market)
    records = _coerce_records(raw, _security_header)

    rows: list[NormalizedRow] = []
    for record in records:
        symbol = _normalize_symbol(_cell(record, ["公司代號", "證券代號", "股票代號", "代號"]))
        name = _cell(record, ["公司名稱", "證券名稱", "股票名稱", "簡稱", "名稱"])
        row_market = _normalize_market(
            _cell(record, ["市場別", "上市櫃", "上市或上櫃", "TYPEK"]),
            context_market,
        )
        if not symbol or not name or row_market not in {"listed", "otc"}:
            continue

        outstanding_shares = _to_int(
            _cell(record, ["已發行普通股數或TDR原股發行股數", "已發行普通股數", "普通股股數"])
        )
        if outstanding_shares is None:
            outstanding_shares = _capital_amount_to_shares(
                _cell(record, ["實收資本額", "實收資本總額", "資本額"]),
                _par_value(record),
            )

        rows.append(
            {
                "row_type": "security",
                "symbol": symbol,
                "name": name,
                "market": row_market,
                "outstanding_shares": outstanding_shares,
                "is_active": True,
            }
        )
    return rows


def parse_dividend_events(raw: Any, *, market: str | None = None) -> list[NormalizedRow]:
    """解析 MOPS 除權息頁，輸出足以計算還原係數的 corporate action 列。"""
    context_market = _normalize_market(_context_value(raw, "market"), market)
    records = _coerce_records(raw, _dividend_header)

    rows: list[NormalizedRow] = []
    for record in records:
        symbol = _normalize_symbol(_cell(record, ["公司代號", "證券代號", "股票代號", "代號"]))
        name = _cell(record, ["公司名稱", "證券名稱", "股票名稱", "簡稱", "名稱"]) or None
        row_market = _normalize_market(_cell(record, ["市場別", "上市櫃", "TYPEK"]), context_market)
        cash_date = _parse_date(_cell(record, ["除息交易日", "除權息交易日", "除權息日"]))
        stock_date = _parse_date(_cell(record, ["除權交易日", "除權息交易日", "除權息日"]))
        if not symbol or row_market not in {"listed", "otc"}:
            continue

        cash_dividend = _cash_dividend(record)
        stock_dividend = _stock_dividend(record)
        if cash_dividend is None and stock_dividend is None:
            continue

        if cash_date is not None and cash_date == stock_date:
            rows.append(
                _dividend_row(
                    symbol=symbol,
                    name=name,
                    market=row_market,
                    ex_rights_date=cash_date,
                    cash_dividend=cash_dividend,
                    stock_dividend=stock_dividend,
                )
            )
            continue
        if cash_dividend is not None and cash_date is not None:
            rows.append(
                _dividend_row(
                    symbol=symbol,
                    name=name,
                    market=row_market,
                    ex_rights_date=cash_date,
                    cash_dividend=cash_dividend,
                    stock_dividend=None,
                )
            )
        if stock_dividend is not None and stock_date is not None:
            rows.append(
                _dividend_row(
                    symbol=symbol,
                    name=name,
                    market=row_market,
                    ex_rights_date=stock_date,
                    cash_dividend=None,
                    stock_dividend=stock_dividend,
                )
            )
    return rows


def parse_capital_changes(raw: Any, *, symbol: str | None = None, market: str | None = None) -> list[NormalizedRow]:
    """解析 MOPS 股本變動頁，輸出 corporate action 股本變動列。"""
    context_symbol = _normalize_symbol(_context_value(raw, "symbol") or symbol or "")
    context_name = _context_value(raw, "name") or None
    context_market = _normalize_market(_context_value(raw, "market"), market)
    records = _coerce_records(raw, _capital_header)

    rows: list[NormalizedRow] = []
    previous_after_shares: int | None = None
    for record in sorted(records, key=lambda item: _parse_date(_capital_date_cell(item)) or dt.date.min):
        row_symbol = _normalize_symbol(
            _cell(record, ["公司代號", "證券代號", "股票代號", "代號"]) or context_symbol
        )
        row_name = _cell(record, ["公司名稱", "證券名稱", "股票名稱", "簡稱", "名稱"]) or context_name
        row_market = _normalize_market(_cell(record, ["市場別", "上市櫃", "TYPEK"]), context_market)
        change_date = _parse_date(_capital_date_cell(record))
        if not row_symbol or row_market not in {"listed", "otc"} or change_date is None:
            continue

        par_value = _par_value(record)
        capital_after_shares = _capital_after_shares(record, par_value)
        capital_change_shares = _capital_change_shares(record, par_value)
        if capital_change_shares is None and capital_after_shares is not None and previous_after_shares is not None:
            capital_change_shares = capital_after_shares - previous_after_shares
        if capital_after_shares is not None:
            previous_after_shares = capital_after_shares
        if capital_change_shares is None and capital_after_shares is None:
            continue

        rows.append(
            {
                "row_type": "corporate_action",
                "action_type": "capital_change",
                "symbol": row_symbol,
                "name": row_name,
                "market": row_market,
                "ex_rights_date": change_date,
                "capital_change_date": change_date,
                "cash_dividend_per_share": None,
                "stock_dividend_per_share": None,
                "capital_change_shares": capital_change_shares,
                "capital_after_shares": capital_after_shares,
            }
        )
    return rows


def _context_value(raw: Any, key: str) -> str:
    return _clean_text(raw.get(key)) if isinstance(raw, Mapping) else ""


def _dividend_row(
    *,
    symbol: str,
    name: str | None,
    market: str,
    ex_rights_date: dt.date,
    cash_dividend: Decimal | None,
    stock_dividend: Decimal | None,
) -> NormalizedRow:
    return {
        "row_type": "corporate_action",
        "action_type": "ex_rights_dividend",
        "symbol": symbol,
        "name": name,
        "market": market,
        "ex_rights_date": ex_rights_date,
        "cash_dividend_per_share": cash_dividend,
        "stock_dividend_per_share": stock_dividend,
        "capital_change_shares": None,
        "capital_after_shares": None,
    }


def _cash_dividend(record: Mapping[str, str]) -> Decimal | None:
    total = _first_matching_decimal(
        record,
        lambda header: "現金" in header and any(key in header for key in ("合計", "總計", "總額")),
    )
    if total is not None:
        return total
    return _sum_matching_decimals(
        record,
        lambda header: "現金" in header and any(key in header for key in ("股利", "配息", "盈餘分配")),
    )


def _stock_dividend(record: Mapping[str, str]) -> Decimal | None:
    total = _first_matching_decimal(
        record,
        lambda header: ("股票股利" in header or "無償配股" in header or "配股率" in header)
        and any(key in header for key in ("合計", "總計", "總額", "每股", "每仟股", "每千股", "率")),
        transform=_stock_dividend_value,
    )
    if total is not None:
        return total
    return _sum_matching_decimals(
        record,
        lambda header: any(key in header for key in ("股票股利", "轉增資配股", "無償配股")),
        transform=_stock_dividend_value,
    )


def _first_matching_decimal(record: Mapping[str, str], predicate, transform=None) -> Decimal | None:
    for header, value in record.items():
        if not predicate(header):
            continue
        parsed = _to_decimal(value)
        if parsed is None:
            continue
        return transform(header, parsed) if transform else parsed
    return None


def _sum_matching_decimals(record: Mapping[str, str], predicate, transform=None) -> Decimal | None:
    total: Decimal | None = None
    for header, value in record.items():
        if not predicate(header):
            continue
        parsed = _to_decimal(value)
        if parsed is None:
            continue
        parsed = transform(header, parsed) if transform else parsed
        total = parsed if total is None else total + parsed
    return total


def _stock_dividend_value(header: str, value: Decimal) -> Decimal:
    """轉成每股配股數；MOPS 不同頁面可能用每仟股、百分率或元/股揭露。"""
    normalized_header = _normalize_header(header)
    if "每仟股" in normalized_header or "每千股" in normalized_header:
        return value / Decimal("1000")
    if "元/股" in normalized_header or "元／股" in normalized_header:
        return value / Decimal("10")
    if "%" in normalized_header or "％" in normalized_header:
        return value / Decimal("100")
    if "率" in normalized_header and value > 1:
        return value / Decimal("100")
    return value


def _capital_date_cell(record: Mapping[str, str]) -> str:
    return _cell(record, ["變更日期", "異動日期", "發行日期", "核准日期", "基準日", "日期"])


def _capital_after_shares(record: Mapping[str, str], par_value: Decimal) -> int | None:
    shares = _to_int(
        _cell(record, ["變動後股數", "變更後股數", "實收股數", "已發行普通股數", "股數"])
    )
    if shares is not None:
        return shares
    return _capital_amount_to_shares(
        _cell(record, ["變動後股本", "變更後股本", "實收資本額", "股本", "資本額"]),
        par_value,
    )


def _capital_change_shares(record: Mapping[str, str], par_value: Decimal) -> int | None:
    shares = _to_int(_cell(record, ["增減股數", "變動股數", "股本變動股數", "本次發行股數"]))
    if shares is not None:
        return shares
    return _capital_amount_to_shares(
        _cell(record, ["增減股本", "變動股本", "股本變動金額", "本次發行金額"]),
        par_value,
    )


def _iter_market_inputs(target: Any) -> list[str]:
    if isinstance(target, Mapping):
        markets = target.get("markets") or target.get("market")
        if isinstance(markets, str):
            return [markets]
        if isinstance(markets, Iterable):
            return [str(market) for market in markets]
    return ["listed", "otc"]


def _iter_symbol_inputs(target: Any) -> list[dict[str, str]]:
    if target is None:
        return []
    if isinstance(target, str):
        return [{"symbol": target, "market": ""}]
    if isinstance(target, Mapping):
        symbols = target.get("symbols") or target.get("symbol") or []
        if isinstance(symbols, str):
            return [{"symbol": symbols, "market": _clean_text(target.get("market"))}]
        if isinstance(symbols, Iterable):
            items: list[dict[str, str]] = []
            for item in symbols:
                if isinstance(item, Mapping):
                    items.append(
                        {
                            "symbol": _clean_text(item.get("symbol") or item.get("co_id")),
                            "market": _clean_text(item.get("market") or target.get("market")),
                            "name": _clean_text(item.get("name")),
                        }
                    )
                else:
                    items.append({"symbol": _clean_text(item), "market": _clean_text(target.get("market"))})
            return [item for item in items if item.get("symbol")]
    return []


@register("corporate_actions_mops")
class MopsCorporateActionsSource(DataSource):
    """MOPS 股票基本資料、除權息與股本變動來源。"""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def fetch(self, target: Any, date: dt.date) -> dict[str, Any]:
        """抓取 MOPS 原始 HTML。

        `target` 可為：
        - `None`：抓上市與上櫃基本資料、當年度除權息。
        - `{"markets": ["listed", "otc"], "symbols": [...]}`：再額外逐檔抓股本變動。

        回傳值只含原始 HTML 與解析所需的 symbol/market context；`parse` 再做正規化。
        """
        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True)
        try:
            raws: dict[str, Any] = {"basic": [], "dividend": [], "capital": []}
            for market in _iter_market_inputs(target):
                normalized_market = _normalize_market(market)
                if normalized_market not in _MARKET_TO_TYPEK:
                    continue
                typek = _MARKET_TO_TYPEK[normalized_market]
                raws["basic"].append(
                    {
                        "market": normalized_market,
                            "html": self._post(
                            client,
                            _MOPS_BASIC_URL,
                            params={
                                "encodeURIComponent": "1",
                                "step": "1",
                                "firstin": "1",
                                "off": "1",
                                "TYPEK": typek,
                            },
                            referer="https://mops.twse.com.tw/mops/web/t51sb01",
                        ),
                    }
                )
                raws["dividend"].append(
                    {
                        "market": normalized_market,
                            "html": self._post(
                            client,
                            _MOPS_DIVIDEND_URL,
                            params={
                                "encodeURIComponent": "1",
                                "step": "1",
                                "firstin": "1",
                                "off": "1",
                                "TYPEK": typek,
                                "year": str(date.year - 1911),
                                "type": "2",
                            },
                            referer="https://mops.twse.com.tw/mops/web/t108sb27",
                        ),
                    }
                )
                time.sleep(_DEFAULT_THROTTLE_SECONDS)

            for item in _iter_symbol_inputs(target):
                market = _normalize_market(item.get("market")) or "listed"
                typek = _MARKET_TO_TYPEK.get(market, "sii")
                raws["capital"].append(
                    {
                        "symbol": item["symbol"],
                        "name": item.get("name", ""),
                        "market": market,
                            "html": self._post(
                            client,
                            _MOPS_CAPITAL_URL,
                            params={
                                "encodeURIComponent": "1",
                                "step": "1",
                                "firstin": "1",
                                "off": "1",
                                "co_id": item["symbol"],
                                "TYPEK": typek,
                            },
                            referer="https://mops.twse.com.tw/mops/web/t05st03",
                        ),
                    }
                )
                time.sleep(_DEFAULT_THROTTLE_SECONDS)
            return raws
        finally:
            if self._client is None:
                client.close()

    def parse(self, raw: Any) -> list[NormalizedRow]:
        """把 `fetch` 回傳的三類原始資料合併成正規化列。"""
        if isinstance(raw, Mapping) and any(key in raw for key in ("basic", "dividend", "capital")):
            rows: list[NormalizedRow] = []
            for item in raw.get("basic", []):
                rows.extend(parse_security_master(item))
            for item in raw.get("dividend", []):
                rows.extend(parse_dividend_events(item))
            for item in raw.get("capital", []):
                rows.extend(parse_capital_changes(item))
            return rows

        rows = []
        rows.extend(parse_security_master(raw))
        rows.extend(parse_dividend_events(raw))
        rows.extend(parse_capital_changes(raw))
        return rows

    def _post(
        self,
        client: httpx.Client,
        url: str,
        *,
        params: Mapping[str, str],
        referer: str,
    ) -> str:
        headers = {**_MOPS_HEADERS, "Referer": referer}
        response = client.post(url, data=params, headers=headers)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        text = response.text
        if any(marker in text for marker in _MOPS_SECURITY_ERROR_MARKERS):
            raise RuntimeError("MOPS 回應安全攔截頁，無法取得公開資訊觀測站資料")
        return text
