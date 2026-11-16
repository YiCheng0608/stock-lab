"""The older TPEx dailyQuotes layout's ``0.00`` prices are a no-trade row (Issue #819).

From 2007-04-23 to 2011-11-11 ``dailyQuotes`` wrote ``0.00`` in 收盤, 開盤, 最高
and 最低 for a security with no regular-session trade, where the current layout
writes ``---``.  Read as numbers, those rows became bars closing at 0 (14,121 in
the research DB).  All four zero is now the same official no-trade row as all
four blank: a ``NoTradeRecord``, never a ``BarRecord``.

``fixtures/tpex_daily_quotes/dailyquotes_20111101.json`` is raw 53651 of the
research DB (2011-11-01), shortened to the first six rows of 上櫃股票行情 plus
5011 久陽 and the whole 管理股票 table; the header counts are the original's.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import worker.sources as sources

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "tpex_daily_quotes"
    / "dailyquotes_20111101.json"
)
DAY = date(2011, 11, 1)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _parse(payload: dict) -> tuple[dict, dict]:
    bars = sources.parse_tpex_daily_rows(
        payload, data_as_of=DAY.isoformat(), payload_sha256="sha-819"
    )
    no_trade = sources.parse_tpex_no_trade_rows(
        payload, data_as_of=DAY.isoformat(), payload_sha256="sha-819"
    )
    return {bar.symbol: bar for bar in bars}, {row.symbol: row for row in no_trade}


def test_all_zero_prices_row_is_a_no_trade_record_not_a_bar():
    bars, no_trade = _parse(_payload())

    # 5011 久陽 traded 36 odd-lot shares (均價 31.89) and no regular-session lot.
    assert "5011" not in bars
    assert no_trade["5011"] == sources.NoTradeRecord(
        symbol="5011",
        trading_date=DAY,
        exchange="TPEx",
        source="tpex",
        data_as_of="2011-11-01",
        payload_sha256="sha-819",
    )
    # Zero volume too (006202), and in the 管理股票 table (4801).
    assert set(no_trade) == {"006202", "5011", "4801"}
    assert not any(bar.close == 0 for bar in bars.values())


def test_traded_rows_of_the_same_day_stay_bars():
    bars, _no_trade = _parse(_payload())

    assert set(bars) == {
        "006201",
        "01006T",
        "1333",
        "1336",
        "1558",
        "1107",
        "2341",
        "2381",
        "5318",
    }
    bar = bars["1558"]
    assert (bar.trading_date, bar.open, bar.high, bar.low, bar.close) == (
        DAY,
        103.0,
        103.5,
        101.0,
        102.0,
    )
    assert (bar.volume, bar.turnover, bar.exchange, bar.source) == (
        222361,
        22776322.0,
        "TPEx",
        "tpex",
    )


def _with_row(payload: dict, row: list[str]) -> dict:
    changed = copy.deepcopy(payload)
    changed["tables"][0]["data"].append(row)
    return changed


def test_a_row_with_only_some_prices_zero_is_read_as_before():
    """Only all four zero is a no-trade row.  A row with some of them ``0.00``
    is parsed as it always was: a bar carrying the zero it reads (no such row
    is in the stored 2007-04..2011-11 raw; the replay of #819 AC-2 counts 0)."""

    traded = next(r for r in _payload()["tables"][0]["data"] if r[0] == "1333")
    row = list(traded)
    row[0] = "9999"
    row[4] = "0.00"  # 開盤 only
    bars, no_trade = _parse(_with_row(_payload(), row))

    assert "9999" not in no_trade
    assert (bars["9999"].open, bars["9999"].close) == (0.0, 5.10)


def test_zero_mixed_with_blank_prices_is_neither_a_bar_nor_a_no_trade_row():
    traded = next(r for r in _payload()["tables"][0]["data"] if r[0] == "1333")
    row = list(traded)
    row[0] = "9998"
    row[2], row[4], row[5], row[6] = "0.00", "---", "0.00", "0.00"
    bars, no_trade = _parse(_with_row(_payload(), row))

    assert "9998" not in bars
    assert "9998" not in no_trade
