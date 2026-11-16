"""Fugle's intraday quote, the source of the intraday alerts (#801, docs/DATA_SOURCES.md 盤中報價).

``GET https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}`` with the header
``X-API-KEY``: one request per stock. The free plan (基本用戶) allows 60 intraday requests a
minute, so a minute's round asks at most MAX_SYMBOLS stocks and leaves 10 to spare.

``fetch`` makes one request and never raises: it returns a ``Fetched`` with the HTTP code (or
``timeout``/``network``), the milliseconds and, on a 200, the parsed ``Quote`` or the
reason the body is not one (``malformed:<field>``). What each outcome means for the run
(skip the stock this minute, stop the stock for the day, stop reading for the day) is
``outcome``'s, so that the run and the tests share one table:

- 200 with a quote: ``ok``.
- timeout (TIMEOUT_SECONDS), a connection failure or a 5xx: ``skip`` (this minute, no retry).
- 401 (the key is wrong), 403 (the plan does not have it), 429 (rate limited): ``stop_day``.
- 404 (no such symbol): ``drop`` (the stock only, logged).
- a 200 without ``highPrice``, ``lowPrice`` or ``lastTrade``: ``drop`` as malformed. Before
  the stock's first trade of the day (no ``lastTrade``, high, low, open or volume) the quote
  is ``no_trade`` instead: nothing to judge yet, asked again next minute.
- any other code: ``skip``.

The times Fugle gives (``lastUpdated``, ``lastTrade.time``) are microseconds since the epoch.
The key never reaches a log line: nothing here prints, and ``fetch``'s reasons hold no
header.

Only the standard library: serve imports worker.intraday, which imports this.
"""

from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

API_BASE = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote"
KEY_ENV = "FUGLE_API_KEY"
KEY_HEADER = "X-API-KEY"
TIMEOUT_SECONDS = 10.0
# The free plan's 60 intraday requests a minute, less 10 to spare (#801 scope 1).
MAX_SYMBOLS = 50
# What a code means for the run (module docstring).
OK = "ok"
SKIP = "skip"
DROP = "drop"
STOP_DAY = "stop_day"
NO_TRADE = "no_trade"
STOP_DAY_CODES = {401: "key_invalid", 403: "plan_not_allowed", 429: "rate_limited"}
REQUIRED = ("highPrice", "lowPrice", "lastTrade")


@dataclass(frozen=True)
class Quote:
    """The fields of one intraday quote the alerts read (docs/DATA_SOURCES.md 盤中報價)."""

    symbol: str
    high: float | None
    low: float | None
    open: float | None
    last_price: float | None
    last_time: datetime | None
    is_trial: bool
    limit_up_price: bool = False
    limit_down_price: bool = False
    limit_up_bid: bool = False
    limit_down_ask: bool = False
    bid: float | None = None
    ask: float | None = None
    last_updated: datetime | None = None
    # The quote's trading day, YYYY-MM-DD (``date``): the run judges only today's.
    day: str | None = None

    @property
    def locked_up(self) -> bool:
        """At the limit up with the best bid there too (漲停鎖住)."""

        return self.limit_up_price and self.limit_up_bid

    @property
    def locked_down(self) -> bool:
        """At the limit down with the best ask there too (跌停鎖住)."""

        return self.limit_down_price and self.limit_down_ask


@dataclass(frozen=True)
class Fetched:
    """One request: its code (``200``, ``404``, ``timeout``, ``network``), milliseconds, and
    the quote or why the body is none."""

    symbol: str
    code: str
    ms: int
    quote: Quote | None = None
    reason: str = ""

    @property
    def outcome(self) -> str:
        return outcome(self)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value <= 0:
        return None
    return float(value)


def _moment(value: Any) -> datetime | None:
    """A Fugle time (microseconds since the epoch) as an aware UTC datetime."""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _best(levels: Any) -> float | None:
    """The best price of ``bids``/``asks`` (their first entry), or None."""

    if not isinstance(levels, list) or not levels or not isinstance(levels[0], dict):
        return None
    return _number(levels[0].get("price"))


def parse(symbol: str, body: Any) -> tuple[Quote | None, str]:
    """BODY (a decoded 200) as a Quote and "", or None and the reason:
    ``malformed:<field>`` or ``no_trade``."""

    if not isinstance(body, dict):
        return None, "malformed:body"
    is_trial = body.get("isTrial") is True
    trade = body.get("lastTrade")
    high, low = _number(body.get("highPrice")), _number(body.get("lowPrice"))
    if not is_trial:
        missing = [
            name
            for name, value in (
                ("highPrice", high),
                ("lowPrice", low),
                ("lastTrade", trade if isinstance(trade, dict) else None),
            )
            if value is None
        ]
        if missing:
            total = body.get("total")
            volume = total.get("tradeVolume") if isinstance(total, dict) else None
            opened = _number(body.get("openPrice")) is not None
            if len(missing) == len(REQUIRED) and not volume and not opened:
                return None, NO_TRADE
            return None, f"malformed:{','.join(missing)}"
    trade = trade if isinstance(trade, dict) else {}
    return (
        Quote(
            symbol=symbol,
            high=high,
            low=low,
            open=_number(body.get("openPrice")),
            last_price=_number(trade.get("price")),
            last_time=_moment(trade.get("time")),
            is_trial=is_trial,
            limit_up_price=body.get("isLimitUpPrice") is True,
            limit_down_price=body.get("isLimitDownPrice") is True,
            limit_up_bid=body.get("isLimitUpBid") is True,
            limit_down_ask=body.get("isLimitDownAsk") is True,
            bid=_best(body.get("bids")),
            ask=_best(body.get("asks")),
            last_updated=_moment(body.get("lastUpdated")),
            day=body.get("date") if isinstance(body.get("date"), str) else None,
        ),
        "",
    )


def outcome(fetched: Fetched) -> str:
    """What FETCHED means for the run (module docstring)."""

    if fetched.code == "200":
        if fetched.quote is not None:
            return OK
        return NO_TRADE if fetched.reason == NO_TRADE else DROP
    if fetched.code.isdigit():
        code = int(fetched.code)
        if code in STOP_DAY_CODES:
            return STOP_DAY
        if code == 404:
            return DROP
    return SKIP


Opener = Callable[..., Any]


def fetch(
    symbol: str,
    key: str,
    *,
    opener: Opener | None = None,
    timeout: float = TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> Fetched:
    """One quote request; never raises. OPENER is ``urllib.request.urlopen``'s shape (the
    tests' fake HTTP)."""

    request = urllib.request.Request(
        f"{API_BASE}/{symbol}",
        headers={KEY_HEADER: key, "Accept": "application/json"},
        method="GET",
    )
    started = clock()

    def elapsed() -> int:
        return round((clock() - started) * 1000)

    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        reason = STOP_DAY_CODES.get(exc.code, "")
        return Fetched(symbol, str(exc.code), elapsed(), reason=reason)
    except urllib.error.URLError as exc:
        cause = exc.reason
        if isinstance(cause, (TimeoutError, socket.timeout)):
            return Fetched(symbol, "timeout", elapsed(), reason="timeout")
        name = type(cause).__name__ if isinstance(cause, BaseException) else "URLError"
        return Fetched(symbol, "network", elapsed(), reason=f"network:{name}")
    except (TimeoutError, socket.timeout):
        return Fetched(symbol, "timeout", elapsed(), reason="timeout")
    except (OSError, http.client.HTTPException) as exc:
        return Fetched(
            symbol, "network", elapsed(), reason=f"network:{type(exc).__name__}"
        )
    ms = elapsed()
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return Fetched(symbol, "200", ms, reason="malformed:json")
    quote, reason = parse(symbol, body)
    return Fetched(symbol, "200", ms, quote=quote, reason=reason)


def cap(symbols: list[str], limit: int = MAX_SYMBOLS) -> tuple[list[str], list[str]]:
    """The first LIMIT of SYMBOLS (already in priority order) and the ones left out."""

    return symbols[:limit], symbols[limit:]
