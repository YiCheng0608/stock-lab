"""券商分點買賣日報表 adapter：官方自爬來源（上市 TWSE + 上櫃 TPEx）。

本檔把「抓取」與「解析」切開：

- `OfficialBrokerBranchSource.fetch(...)` 只負責官方頁面互動、驗證碼與單線程節流。
- `parse_twse_html(...)` / `parse_tpex_html(...)` 是純函式，只吃已取得的 HTML / JSON，
  輸出可直接落 `broker_branch_trades` 的正規化列。

官方免費頁面只提供當日分點資料，因此本 adapter 不提供歷史查詢參數；`date` 僅用於
正規化與呼叫端排程的當日一致性檢查。未來若改接 FinMind，只要替換整個
`BrokerBranchSource` 實作即可，不需要改下游 pipeline。
"""

from __future__ import annotations

import datetime as dt
import random
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import BrokerBranchSource, CaptchaSolver, NormalizedRow
from app.adapters.registry import register

BrokerBranchMarket = Literal["listed", "otc"]

_TWSE_MENU_URL = "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"
_TWSE_CONTENT_URL = "https://bsr.twse.com.tw/bshtm/bsContent.aspx"
_TPEX_PAGE_URL = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"
_TPEX_API_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/brokerBS"

_TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
_TPEX_DAILY_QUOTE_URL = (
    "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php"
)

_REQUEST_TIMEOUT = 20.0
_DEFAULT_UNIVERSE_LIMIT = 50
_UA_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-lab-ingestion/1.0)"}
_TPEX_HEADERS = {
    **_UA_HEADERS,
    "Referer": _TPEX_PAGE_URL,
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass(frozen=True)
class BrokerBranchTarget:
    """單一分點查詢目標。"""

    symbol: str
    market: BrokerBranchMarket


@dataclass(frozen=True)
class BrokerBranchRaw:
    """`fetch` 回傳的原始資料包，解析仍只讀這個輸入，不碰外部狀態。"""

    symbol: str
    market: BrokerBranchMarket
    date: dt.date
    pages: tuple[str, ...]


@dataclass(frozen=True)
class ThrottleConfig:
    """每檔之間的單線程保守節流設定。"""

    min_seconds: float = 3.0
    max_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.min_seconds < 0 or self.max_seconds < 0:
            raise ValueError("節流秒數不可為負數")
        if self.max_seconds < self.min_seconds:
            raise ValueError("max_seconds 不可小於 min_seconds")


@dataclass
class SingleThreadThrottle:
    """序列化每次外站查詢；可注入 clock/sleep 讓測試驗證間隔。"""

    config: ThrottleConfig = field(default_factory=ThrottleConfig)
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _last_request_at: float | None = None

    def wait(self) -> None:
        now = self.monotonic()
        if self._last_request_at is not None:
            interval = random.uniform(self.config.min_seconds, self.config.max_seconds)
            elapsed = now - self._last_request_at
            if elapsed < interval:
                self.sleep(interval - elapsed)
                now = self.monotonic()
        self._last_request_at = now


class DdddOcrCaptchaSolver(CaptchaSolver):
    """預設驗證碼辨識器；延遲 import，避免只測 parser 時需要載入 OCR 模型。"""

    def __init__(self) -> None:
        import ddddocr

        self._ocr = ddddocr.DdddOcr(show_ad=False)

    def solve(self, image: bytes) -> str:
        return str(self._ocr.classification(image)).strip()


def parse_twse_html(html: str, *, symbol: str | None = None) -> list[NormalizedRow]:
    """解析 TWSE `bsr.twse.com.tw` 買賣日報表 HTML，回傳上市分點列。"""

    return _parse_broker_branch_html(html, market="listed", symbol=symbol)


def parse_tpex_html(html: str, *, symbol: str | None = None) -> list[NormalizedRow]:
    """解析 TPEx 券商買賣證券日報表 HTML，回傳上櫃分點列。"""

    return _parse_broker_branch_html(html, market="otc", symbol=symbol)


def parse_tpex_json(raw: Any, *, symbol: str | None = None) -> list[NormalizedRow]:
    """解析 TPEx tables API JSON；保留給 fetch 直接取得 JSON 時使用。"""

    if not isinstance(raw, dict) or raw.get("stat") != "ok":
        return []
    trading_date = _coerce_date(raw.get("date"))
    html_parts: list[str] = []
    if trading_date is not None:
        html_parts.append(f"<p>日期: {trading_date.isoformat()}</p>")
    for table in raw.get("tables") or []:
        fields = table.get("fields") or []
        rows = table.get("data") or []
        if not isinstance(fields, list) or not isinstance(rows, list):
            continue
        header = "".join(f"<th>{field}</th>" for field in fields)
        body = "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in rows
            if isinstance(row, list)
        )
        html_parts.append(f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>")
    if not html_parts:
        return []
    return parse_tpex_html("\n".join(html_parts), symbol=symbol)


@register("broker_branch_official")
class OfficialBrokerBranchSource(BrokerBranchSource):
    """官方免費頁面自爬版分點來源，之後可由 FinMind 版整段替換。"""

    def __init__(
        self,
        captcha_solver: CaptchaSolver | None = None,
        *,
        client: httpx.Client | None = None,
        throttle: SingleThreadThrottle | None = None,
        default_market: BrokerBranchMarket = "listed",
        universe: Sequence[str] | dict[BrokerBranchMarket, Sequence[str]] | None = None,
        universe_limit: int = _DEFAULT_UNIVERSE_LIMIT,
        today: Callable[[], dt.date] = dt.date.today,
        tpex_turnstile_token: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(captcha_solver or DdddOcrCaptchaSolver())
        self._client = client
        self._throttle = throttle or SingleThreadThrottle()
        self._default_market = default_market
        self._universe = universe
        self._universe_limit = universe_limit
        self._today = today
        self._tpex_turnstile_token = tpex_turnstile_token

    def fetch(self, target: str | BrokerBranchTarget, date: dt.date) -> BrokerBranchRaw:
        """取得單股當日多頁原始資料；每次查詢前都經過單線程節流。"""

        resolved = self._resolve_target(target)
        self._ensure_today_only(date)
        self._throttle.wait()

        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True)
        try:
            if resolved.market == "listed":
                pages = self._fetch_twse_pages(client, resolved.symbol)
            else:
                pages = self._fetch_tpex_pages(client, resolved.symbol)
            return BrokerBranchRaw(
                symbol=resolved.symbol,
                market=resolved.market,
                date=date,
                pages=tuple(pages),
            )
        finally:
            if self._client is None:
                client.close()

    def parse(self, raw: Any) -> list[NormalizedRow]:
        """把 `fetch` 的原始資料包轉成正規化分點列；純函式。"""

        if isinstance(raw, BrokerBranchRaw):
            rows: list[NormalizedRow] = []
            for page in raw.pages:
                if raw.market == "listed":
                    page_rows = parse_twse_html(page, symbol=raw.symbol)
                else:
                    page_rows = parse_tpex_html(page, symbol=raw.symbol)
                for row in page_rows:
                    if row.get("date") is None:
                        row["date"] = raw.date
                rows.extend(page_rows)
            return _merge_duplicate_branches(rows)

        if isinstance(raw, dict):
            market = raw.get("market")
            symbol = raw.get("symbol")
            if "tables" in raw:
                return parse_tpex_json(raw, symbol=symbol)
            pages = raw.get("pages")
            if market in {"listed", "otc"} and isinstance(pages, Iterable) and not isinstance(pages, str):
                return self.parse(
                    BrokerBranchRaw(
                        symbol=str(symbol or ""),
                        market=market,
                        date=_coerce_date(raw.get("date")) or self._today(),
                        pages=tuple(str(page) for page in pages),
                    )
                )

        if isinstance(raw, str):
            return parse_twse_html(raw)
        return []

    def fetch_many(
        self,
        targets: Iterable[str | BrokerBranchTarget],
        date: dt.date,
    ) -> list[BrokerBranchRaw]:
        """保守單線程逐檔抓取；每檔都會套用同一個 throttle。"""

        return [self.fetch(target, date) for target in targets]

    def resolve_universe(self, date: dt.date, market: BrokerBranchMarket) -> list[BrokerBranchTarget]:
        """取得可設定 universe；未設定時取當日成交量前 N 名，不引用自選股表。"""

        configured = self._configured_universe(market)
        if configured is not None:
            return [BrokerBranchTarget(symbol=symbol, market=market) for symbol in configured]
        symbols = self._fetch_top_volume_symbols(date, market, self._universe_limit)
        return [BrokerBranchTarget(symbol=symbol, market=market) for symbol in symbols]

    def _resolve_target(self, target: str | BrokerBranchTarget) -> BrokerBranchTarget:
        if isinstance(target, BrokerBranchTarget):
            return target
        text = str(target).strip()
        if ":" in text:
            market_text, symbol = text.split(":", 1)
            market = _normalize_market(market_text) or self._default_market
            return BrokerBranchTarget(symbol=symbol.strip(), market=market)
        return BrokerBranchTarget(symbol=text, market=self._default_market)

    def _ensure_today_only(self, date: dt.date) -> None:
        today = self._today()
        if date != today:
            raise ValueError(f"官方分點頁只提供當日資料：要求 {date.isoformat()}，今日 {today.isoformat()}")

    def _fetch_twse_pages(self, client: httpx.Client, symbol: str) -> list[str]:
        menu = client.get(_TWSE_MENU_URL, headers=_UA_HEADERS)
        menu.raise_for_status()
        soup = BeautifulSoup(menu.text, "lxml")
        captcha_url = _find_captcha_url(soup, _TWSE_MENU_URL)
        if captcha_url is None:
            raise RuntimeError("TWSE 分點頁找不到驗證碼圖片")

        captcha = client.get(captcha_url, headers={**_UA_HEADERS, "Referer": _TWSE_MENU_URL})
        captcha.raise_for_status()
        captcha_text = self.captcha_solver.solve(captcha.content)

        form = _extract_form_fields(soup)
        form.update(
            {
                "RadioButton_Normal": "RadioButton_Normal",
                "TextBox_Stkno": symbol,
                "CaptchaControl1": captcha_text,
                "btnOK": "查詢",
            }
        )
        submitted = client.post(
            _TWSE_MENU_URL,
            data=form,
            headers={**_UA_HEADERS, "Referer": _TWSE_MENU_URL},
        )
        submitted.raise_for_status()

        pages = [submitted.text]
        for url in _discover_twse_content_urls(submitted.text):
            resp = client.get(url, headers={**_UA_HEADERS, "Referer": _TWSE_MENU_URL})
            resp.raise_for_status()
            pages.append(resp.text)
            pages.extend(self._fetch_twse_linked_pages(client, resp.text))

        if len(pages) == 1:
            content = client.get(_TWSE_CONTENT_URL, headers={**_UA_HEADERS, "Referer": _TWSE_MENU_URL})
            if content.status_code < 400 and content.text.strip():
                pages.append(content.text)
                pages.extend(self._fetch_twse_linked_pages(client, content.text))
        return _dedupe_pages(pages)

    def _fetch_twse_linked_pages(self, client: httpx.Client, html: str) -> list[str]:
        pages: list[str] = []
        for url in _discover_twse_content_urls(html):
            resp = client.get(url, headers={**_UA_HEADERS, "Referer": _TWSE_CONTENT_URL})
            if resp.status_code < 400 and resp.text.strip():
                pages.append(resp.text)
        return pages

    def _fetch_tpex_pages(self, client: httpx.Client, symbol: str) -> list[str]:
        landing = client.get(_TPEX_PAGE_URL, headers=_UA_HEADERS)
        landing.raise_for_status()

        payload = {"code": symbol, "response": "json"}
        if self._tpex_turnstile_token is not None:
            token = self._tpex_turnstile_token()
            if token:
                payload["cf-turnstile-response"] = token

        resp = client.post(_TPEX_API_URL, data=payload, headers=_TPEX_HEADERS)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            return [resp.text]
        if data.get("stat") != "ok":
            return [resp.text]
        rows = parse_tpex_json(data, symbol=symbol)
        if not rows:
            return [resp.text]
        return [_rows_to_fixture_html(rows)]

    def _configured_universe(self, market: BrokerBranchMarket) -> list[str] | None:
        if self._universe is None:
            return None
        if isinstance(self._universe, dict):
            return [str(symbol).strip() for symbol in self._universe.get(market, []) if str(symbol).strip()]
        return [str(symbol).strip() for symbol in self._universe if str(symbol).strip()]

    def _fetch_top_volume_symbols(
        self,
        date: dt.date,
        market: BrokerBranchMarket,
        limit: int,
    ) -> list[str]:
        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        try:
            if market == "listed":
                params = {"date": date.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"}
                resp = client.get(_TWSE_MI_INDEX_URL, params=params, headers=_UA_HEADERS)
                resp.raise_for_status()
                return _top_twse_symbols(resp.json(), limit)

            roc_year = date.year - 1911
            params = {"l": "zh-tw", "d": f"{roc_year}/{date.month:02d}/{date.day:02d}", "se": "EW"}
            resp = client.get(_TPEX_DAILY_QUOTE_URL, params=params, headers=_TPEX_HEADERS)
            resp.raise_for_status()
            return _top_tpex_symbols(resp.json(), limit)
        finally:
            if self._client is None:
                client.close()


def _parse_broker_branch_html(
    html: str,
    *,
    market: BrokerBranchMarket,
    symbol: str | None,
) -> list[NormalizedRow]:
    soup = BeautifulSoup(html or "", "lxml")
    text = soup.get_text(" ", strip=True)
    trading_date = _extract_date(text)
    resolved_symbol = symbol or _extract_symbol(text)

    rows: list[NormalizedRow] = []
    for table in soup.find_all("table"):
        matrix = _table_matrix(table)
        if len(matrix) < 2:
            continue
        rows.extend(_parse_table_matrix(matrix, market, resolved_symbol, trading_date))
    return _merge_duplicate_branches(rows)


def _parse_table_matrix(
    matrix: list[list[str]],
    market: BrokerBranchMarket,
    symbol: str | None,
    trading_date: dt.date | None,
) -> list[NormalizedRow]:
    header_index, groups = _find_header_groups(matrix)
    if groups is None:
        return _parse_table_without_header(matrix, market, symbol, trading_date)

    rows: list[NormalizedRow] = []
    for record in matrix[header_index + 1 :]:
        for indexes in groups:
            if max(indexes.values(), default=-1) >= len(record):
                continue
            branch = record[indexes["branch"]]
            buy_volume = _to_int(record[indexes["buy"]])
            sell_volume = _to_int(record[indexes["sell"]])
            row = _make_row(
                market=market,
                symbol=symbol,
                trading_date=trading_date,
                branch=branch,
                buy_volume=buy_volume,
                sell_volume=sell_volume,
            )
            if row is not None:
                rows.append(row)
    return rows


def _parse_table_without_header(
    matrix: list[list[str]],
    market: BrokerBranchMarket,
    symbol: str | None,
    trading_date: dt.date | None,
) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    for record in matrix:
        if len(record) < 3:
            continue
        branch_index = next((i for i, cell in enumerate(record) if _parse_branch(cell) is not None), None)
        if branch_index is None:
            continue
        numbers = [_to_int(cell) for i, cell in enumerate(record) if i != branch_index]
        volumes = [number for number in numbers if number is not None]
        if len(volumes) < 2:
            continue
        row = _make_row(
            market=market,
            symbol=symbol,
            trading_date=trading_date,
            branch=record[branch_index],
            buy_volume=volumes[0],
            sell_volume=volumes[1],
        )
        if row is not None:
            rows.append(row)
    return rows


def _find_header_groups(matrix: list[list[str]]) -> tuple[int, list[dict[str, int]] | None]:
    for row_index, row in enumerate(matrix):
        branch_indexes: list[int] = []
        for cell_index, cell in enumerate(row):
            normalized = _compact(cell)
            if "券商" in normalized or "分點" in normalized:
                branch_indexes.append(cell_index)
        groups: list[dict[str, int]] = []
        for position, branch_index in enumerate(branch_indexes):
            next_branch_index = (
                branch_indexes[position + 1] if position + 1 < len(branch_indexes) else len(row)
            )
            indexes = {"branch": branch_index}
            for cell_index in range(branch_index + 1, next_branch_index):
                normalized = _compact(row[cell_index])
                if _is_buy_header(normalized):
                    indexes.setdefault("buy", cell_index)
                elif _is_sell_header(normalized):
                    indexes.setdefault("sell", cell_index)
            if {"branch", "buy", "sell"}.issubset(indexes):
                groups.append(indexes)
        if groups:
            return row_index, groups
    return -1, None


def _is_buy_header(normalized: str) -> bool:
    return (
        "金額" not in normalized
        and ("買進" in normalized or "買入" in normalized or normalized == "買")
    )


def _is_sell_header(normalized: str) -> bool:
    return (
        "金額" not in normalized
        and ("賣出" in normalized or "賣超" in normalized or normalized == "賣")
    )


def _make_row(
    *,
    market: BrokerBranchMarket,
    symbol: str | None,
    trading_date: dt.date | None,
    branch: str,
    buy_volume: int | None,
    sell_volume: int | None,
) -> NormalizedRow | None:
    parsed_branch = _parse_branch(branch)
    if parsed_branch is None or buy_volume is None or sell_volume is None:
        return None
    branch_code, branch_name = parsed_branch
    row: NormalizedRow = {
        "symbol": symbol,
        "market": market,
        "date": trading_date,
        "broker_branch_code": branch_code,
        "broker_branch_name": branch_name,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
    }
    return row


def _merge_duplicate_branches(rows: Iterable[NormalizedRow]) -> list[NormalizedRow]:
    merged: dict[tuple[Any, ...], NormalizedRow] = {}
    for row in rows:
        key = (
            row.get("symbol"),
            row.get("market"),
            row.get("date"),
            row.get("broker_branch_code"),
        )
        if key not in merged:
            merged[key] = dict(row)
            continue
        merged[key]["buy_volume"] = int(merged[key]["buy_volume"]) + int(row["buy_volume"])
        merged[key]["sell_volume"] = int(merged[key]["sell_volume"]) + int(row["sell_volume"])
        if not merged[key].get("broker_branch_name") and row.get("broker_branch_name"):
            merged[key]["broker_branch_name"] = row["broker_branch_name"]
    return list(merged.values())


def _table_matrix(table: Any) -> list[list[str]]:
    matrix: list[list[str]] = []
    for tr in table.find_all("tr"):
        row = [_clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if row and any(row):
            matrix.append(row)
    return matrix


def _parse_branch(raw: str) -> tuple[str, str | None] | None:
    text = _clean_text(raw)
    if not text or any(skip in text for skip in ("合計", "總計", "序號", "券商")):
        return None
    match = re.match(r"^(?P<code>\d{3,5}[A-Za-z]?)[\s\-]*(?P<name>.*)$", text)
    if match is None:
        return None
    code = match.group("code")
    name = match.group("name").strip(" -　") or None
    return code, name


def _extract_date(text: str) -> dt.date | None:
    patterns = (
        r"(?P<year>\d{4})[年/\-.](?P<month>\d{1,2})[月/\-.](?P<day>\d{1,2})",
        r"(?<!\d)(?P<year>\d{3})[年/\-.](?P<month>\d{1,2})[月/\-.](?P<day>\d{1,2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match is None:
            continue
        year = int(match.group("year"))
        if year < 1911:
            year += 1911
        try:
            return dt.date(year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            return None
    return None


def _coerce_date(raw: Any) -> dt.date | None:
    if isinstance(raw, dt.date):
        return raw
    if isinstance(raw, str):
        parsed = _extract_date(raw)
        if parsed is not None:
            return parsed
        try:
            return dt.date.fromisoformat(raw.strip())
        except ValueError:
            return None
    return None


def _extract_symbol(text: str) -> str | None:
    match = re.search(r"(?:證券代號|股票代碼|代號)[:：\s]*(\d{4,6})", text)
    if match is not None:
        return match.group(1)
    match = re.search(r"\b(\d{4})\b", text)
    return match.group(1) if match else None


def _to_int(raw: Any) -> int | None:
    text = _clean_text(str(raw)).replace(",", "")
    text = re.sub(r"[^\d\-.]", "", text)
    if not text or text in {"-", "--", "---", "."}:
        return None
    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _clean_text(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").replace("\xa0", " ")).strip()


def _compact(raw: str) -> str:
    return re.sub(r"\s+", "", raw or "")


def _normalize_market(raw: str) -> BrokerBranchMarket | None:
    text = raw.strip().lower()
    if text in {"listed", "twse", "上市"}:
        return "listed"
    if text in {"otc", "tpex", "上櫃", "櫃買"}:
        return "otc"
    return None


def _extract_form_fields(soup: BeautifulSoup) -> dict[str, str]:
    fields: dict[str, str] = {}
    for input_ in soup.find_all("input"):
        name = input_.get("name")
        if not name:
            continue
        input_type = (input_.get("type") or "").lower()
        if input_type in {"submit", "button", "image"}:
            continue
        fields[str(name)] = str(input_.get("value") or "")
    return fields


def _find_captcha_url(soup: BeautifulSoup, base_url: str) -> str | None:
    for img in soup.find_all("img"):
        src = str(img.get("src") or "")
        if "captcha" in src.lower():
            return urljoin(base_url, src)
    return None


def _discover_twse_content_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    urls: list[str] = []
    for node in soup.find_all(["a", "frame", "iframe"]):
        href = str(node.get("href") or node.get("src") or "")
        if "bsContent" in href:
            urls.append(urljoin(_TWSE_CONTENT_URL, href))
    return list(dict.fromkeys(urls))


def _dedupe_pages(pages: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for page in pages:
        marker = page.strip()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(page)
    return result


def _rows_to_fixture_html(rows: Sequence[NormalizedRow]) -> str:
    body = "\n".join(
        "<tr>"
        f"<td>{row.get('broker_branch_code', '')} {row.get('broker_branch_name') or ''}</td>"
        f"<td>{row.get('buy_volume', 0)}</td>"
        f"<td>{row.get('sell_volume', 0)}</td>"
        "</tr>"
        for row in rows
    )
    return f"<table><tr><th>券商</th><th>買進股數</th><th>賣出股數</th></tr>{body}</table>"


def _top_twse_symbols(raw: Any, limit: int) -> list[str]:
    if not isinstance(raw, dict):
        return []
    table = next(
        (table for table in raw.get("tables", []) if "每日收盤行情" in (table.get("title") or "")),
        None,
    )
    if table is None:
        return []
    ranked = []
    for row in table.get("data", []):
        if not isinstance(row, list) or len(row) < 3:
            continue
        volume = _to_int(row[2]) or 0
        ranked.append((volume, str(row[0]).strip()))
    ranked.sort(reverse=True)
    return [symbol for _, symbol in ranked[:limit] if symbol]


def _top_tpex_symbols(raw: Any, limit: int) -> list[str]:
    if not isinstance(raw, dict):
        return []
    tables = raw.get("tables") or []
    if not tables:
        return []
    ranked = []
    for row in tables[0].get("data", []):
        if not isinstance(row, list) or len(row) < 9:
            continue
        volume = _to_int(row[8]) or 0
        ranked.append((volume, str(row[0]).strip()))
    ranked.sort(reverse=True)
    return [symbol for _, symbol in ranked[:limit] if symbol]
