"""日價量（K 線）adapter：上市（證交所）與上櫃（櫃買）雙市場，落 `daily_prices` 原始價。

依 docs/design.md §3、§7：
- 資料源為證交所/櫃買「官方 OpenAPI 與每日收盤行情」，歷史可整批回補十年以上。
- 本期只落**原始價**（`daily_prices.*_raw`）；除權息還原價（`*_adj`）由 spec-10
  依 `corporate_actions` 自算回填，本檔不計算、不觸碰。

兩市場官方端點回應格式不同（欄位順序、每頁表格結構都不一樣），故本檔提供
**兩組獨立的 fetch/parse**、各自對應一個 `DataSource` 子類別，正規化到同一份
`NormalizedRow` 形狀（symbol/market/date + OHLCV），供下游 pipeline（spec-11）
以 `symbol`+`market` 查找或建立 `securities` 列、再寫入 `daily_prices`。

兩端點都是**全市場單一請求**（一次拿到當天所有股票的收盤行情），而不是逐檔查詢：
- TWSE 的逐檔端點（STOCK_DAY）回傳「整月」資料，形狀與本檔逐日抓取的粒度不符；
  MI_INDEX 每呼叫一次即為當日全市場，對「每日批次回補」更省請求數也更貼合排程。
- 因此 `fetch` 的 `target` 引數在兩來源中都不使用（僅為滿足 `DataSource` 契約簽章保留），
  一次回應本身已含所有股票，篩不篩選交給呼叫端在 `parse` 之後處理。

兩端點皆為公開 JSON 端點、不需金鑰；因此無「缺金鑰 skip」情境。若未來換成需要
金鑰的來源（例如付費資料源），比照本檔模式在對應 `fetch` 內讀取 env、缺值時
記 log 並回傳空清單（不 crash），不需更動 `parse` 或呼叫端。

已知的官方端點怪癖（會影響回補邏輯，非本檔 bug）：
- TWSE 非交易日（假日）：回應沒有 `tables`、`stat` 為錯誤訊息 —— `parse_twse` 對此
  回傳空清單，是正確結果而非解析失敗。
- TPEx 非交易日：官方端點會**靜默**回傳「最近一個交易日」的資料，而不是報錯；
  但回應內的 `date` 欄位會誠實標出實際交易日。`parse_tpex` 一律以回應自帶的
  `date` 為準（不假設等於呼叫時要求的日期），因此即使呼叫端對週末逐日回補，
  每個非交易日都會正規化出「同一個實際交易日」的重複列——落庫時靠
  `daily_prices` 的 (security_id, date) unique constraint 去重即可，屬預期行為。
"""

from __future__ import annotations

import datetime as dt
import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.adapters.base import DataSource, NormalizedRow
from app.adapters.registry import register

_TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
_TPEX_DAILY_QUOTE_URL = (
    "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php"
)

# TWSE 回應裡「每日收盤行情」表格的標題不含日期以外的部分是固定字串，用子字串比對
# 而非固定表格 index，避免官方調整表格順序時整批解析失效。
_TWSE_TABLE_TITLE_HINT = "每日收盤行情"

_REQUEST_TIMEOUT = 10.0
# 對官方端點做基本節流，避免日期區間回補時短時間內大量請求觸發限流或被視為濫用。
_DEFAULT_THROTTLE_SECONDS = 0.35

_UA_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-lab-ingestion/1.0)"}
# TPEx 的舊版行情端點會依 Referer 判斷是否為瀏覽器來源請求，缺少時可能回拒。
_TPEX_HEADERS = {
    **_UA_HEADERS,
    "Referer": "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote.php?l=zh-tw",
}


def _decode_json_payload(raw: Any) -> dict[str, Any] | None:
    """接受已解碼 JSON dict 或原始 JSON 文字/位元組；格式不符回傳 `None`。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _to_decimal(raw: str) -> Decimal | None:
    """把官方回應裡的價格字串轉成 `Decimal`；無法解析（如 `--`、空字串）回傳 `None`。"""
    text = (raw or "").strip()
    if not text or text in {"--", "-", "---"}:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _to_int(raw: str) -> int | None:
    """把官方回應裡的整數字串（可能含千分位逗號）轉成 `int`；無法解析回傳 `None`。"""
    text = (raw or "").strip().replace(",", "")
    if not text or text in {"--", "-", "---"}:
        return None
    try:
        return int(Decimal(text))
    except InvalidOperation:
        return None


def _to_trading_date(yyyymmdd: str) -> dt.date | None:
    """把兩來源回應共通的西元 `YYYYMMDD` 字串轉成 `date`；格式不符回傳 `None`。"""
    text = (yyyymmdd or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return dt.date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def parse_twse(raw: Any) -> list[NormalizedRow]:
    """把 TWSE MI_INDEX 回應轉成正規化日 OHLCV 列（原始價，上市）。

    純函式：只讀 `raw`，不觸發任何網路請求。非交易日（官方回應無 `tables`、
    `stat` 非 `'OK'`）回傳空清單，是正確結果而非錯誤。
    """
    payload = _decode_json_payload(raw)
    if payload is None:
        return []
    trading_date = _to_trading_date(payload.get("date", ""))
    if trading_date is None:
        return []

    tables = payload.get("tables") or []
    table = next(
        (
            t
            for t in tables
            if isinstance(t, dict) and _TWSE_TABLE_TITLE_HINT in (t.get("title") or "")
        ),
        None,
    )
    if table is None:
        return []

    rows: list[NormalizedRow] = []
    for record in table.get("data") or []:
        # 欄位順序（見官方回應 fields）：
        # 證券代號, 證券名稱, 成交股數, 成交筆數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, ...
        if len(record) < 9:
            continue
        symbol, _name, volume_shares, _count, _amount, open_, high, low, close = record[:9]

        open_raw = _to_decimal(open_)
        high_raw = _to_decimal(high)
        low_raw = _to_decimal(low)
        close_raw = _to_decimal(close)
        volume = _to_int(volume_shares)
        if None in (open_raw, high_raw, low_raw, close_raw, volume):
            # 當日無成交（全部為 '--'）或格式異常：略過此列，不塞假資料進正規化結果。
            continue

        rows.append(
            {
                "symbol": symbol.strip(),
                "market": "listed",
                "date": trading_date,
                "open_raw": open_raw,
                "high_raw": high_raw,
                "low_raw": low_raw,
                "close_raw": close_raw,
                "volume": volume,
            }
        )
    return rows


def parse_tpex(raw: Any) -> list[NormalizedRow]:
    """把 TPEx（櫃買）日收盤行情回應轉成正規化日 OHLCV 列（原始價，上櫃）。

    純函式：只讀 `raw`，不觸發任何網路請求。一律以回應內 `date` 欄位為實際交易日
    （見模組說明：TPEx 對非交易日會靜默回傳最近交易日資料而非報錯）。
    """
    payload = _decode_json_payload(raw)
    if payload is None:
        return []
    trading_date = _to_trading_date(payload.get("date", ""))
    if trading_date is None:
        return []

    tables = payload.get("tables") or []
    if not tables:
        return []
    table = tables[0]
    if not isinstance(table, dict):
        return []

    rows: list[NormalizedRow] = []
    for record in table.get("data") or []:
        # 欄位順序（見官方回應 fields）：
        # 代號, 名稱, 收盤, 漲跌, 開盤, 最高, 最低, 均價, 成交股數, ...
        if len(record) < 9:
            continue
        symbol, _name, close, _change, open_, high, low, _avg, volume_shares = record[:9]

        open_raw = _to_decimal(open_)
        high_raw = _to_decimal(high)
        low_raw = _to_decimal(low)
        close_raw = _to_decimal(close)
        volume = _to_int(volume_shares)
        if None in (open_raw, high_raw, low_raw, close_raw, volume):
            continue

        rows.append(
            {
                "symbol": symbol.strip(),
                "market": "otc",
                "date": trading_date,
                "open_raw": open_raw,
                "high_raw": high_raw,
                "low_raw": low_raw,
                "close_raw": close_raw,
                "volume": volume,
            }
        )
    return rows


@register("daily_price_twse")
class TwseDailyPriceSource(DataSource):
    """上市（證交所）日 OHLCV 來源：`MI_INDEX` 每日收盤行情（全市場單一請求）。"""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        """`client` 可注入既有 `httpx.Client`（例如測試假 transport）；預設每次呼叫各開一個。"""
        self._client = client

    def fetch(self, target: str | None, date: dt.date) -> Any:
        """取得 `date` 當天全市場日收盤行情原始 JSON 位元組。

        `target` 不使用（見模組說明：本端點一次回應即含全市場，不需逐檔查詢），
        僅為符合 `DataSource` 契約簽章保留。
        """
        params = {"date": date.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"}
        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        try:
            resp = client.get(_TWSE_MI_INDEX_URL, params=params, headers=_UA_HEADERS)
            resp.raise_for_status()
            return resp.content
        finally:
            if self._client is None:
                client.close()

    def parse(self, raw: Any) -> list[NormalizedRow]:
        return parse_twse(raw)

    def fetch_range(
        self,
        date_from: dt.date,
        date_to: dt.date,
        *,
        throttle_seconds: float = _DEFAULT_THROTTLE_SECONDS,
    ) -> list[Any]:
        """十年回補等情境的日期區間便利方法：逐日呼叫 `fetch` 並收集原始回應清單。

        呼叫端對每個元素各自呼叫 `parse`（保持抓取／解析分離）。非交易日的官方
        回應本身即代表「無資料」，不在此特別跳過或判斷。
        """
        raws: list[Any] = []
        current = date_from
        while current <= date_to:
            raws.append(self.fetch(None, current))
            if current != date_to and throttle_seconds > 0:
                time.sleep(throttle_seconds)
            current += dt.timedelta(days=1)
        return raws


@register("daily_price_tpex")
class TpexDailyPriceSource(DataSource):
    """上櫃（櫃買）日 OHLCV 來源：日收盤行情（全市場單一請求）。"""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        """`client` 可注入既有 `httpx.Client`（例如測試假 transport）；預設每次呼叫各開一個。"""
        self._client = client

    def fetch(self, target: str | None, date: dt.date) -> Any:
        """取得 `date` 當天全市場日收盤行情原始 JSON 位元組。

        `target` 不使用（理由同 `TwseDailyPriceSource.fetch`）。查詢參數需民國年格式
        （`d=YYY/MM/DD`），是官方端點的既有慣例，與回應內容的西元日期無關。
        """
        roc_year = date.year - 1911
        params = {"l": "zh-tw", "d": f"{roc_year}/{date.month:02d}/{date.day:02d}", "se": "EW"}
        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        try:
            resp = client.get(_TPEX_DAILY_QUOTE_URL, params=params, headers=_TPEX_HEADERS)
            resp.raise_for_status()
            return resp.content
        finally:
            if self._client is None:
                client.close()

    def parse(self, raw: Any) -> list[NormalizedRow]:
        return parse_tpex(raw)

    def fetch_range(
        self,
        date_from: dt.date,
        date_to: dt.date,
        *,
        throttle_seconds: float = _DEFAULT_THROTTLE_SECONDS,
    ) -> list[Any]:
        """十年回補等情境的日期區間便利方法，行為同 `TwseDailyPriceSource.fetch_range`。

        注意模組說明提到的 TPEx 非交易日靜默回退行為：區間內的假日會與最近交易日
        產出相同的正規化列，落庫時交由 `daily_prices` 的 unique constraint 去重。
        """
        raws: list[Any] = []
        current = date_from
        while current <= date_to:
            raws.append(self.fetch(None, current))
            if current != date_to and throttle_seconds > 0:
                time.sleep(throttle_seconds)
            current += dt.timedelta(days=1)
        return raws
