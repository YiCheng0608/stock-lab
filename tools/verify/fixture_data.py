"""Fixed fake rows for the verify-stock-lab fixture database (Issue #241).

Every value is invented or computed from the constants below; nothing is read
from the production database or fetched from a source, and no timestamp comes
from the clock, so two builds are identical.  ``tools/verify/fixture_db.py``
writes ``TABLES`` into a database migrated to the Alembic head.

Three lists keep the data honest against the schema
(``backend/tests/test_verify_fixture.py`` checks them with ``PRAGMA table_info``):

- ``TABLES``: one list of complete rows per table.  Every row carries every
  head column that is not in ``INTENTIONALLY_EMPTY``, and every such column has
  a non-null value in at least one row.
- ``INTENTIONALLY_EMPTY``: columns no row writes, with the reason.
- ``OMITTED_TABLES``: head tables with no rows, with the reason.

``EXPECTED`` holds what each of the five main pages' APIs return for this data.

Imports app.domain, app.indicators and app.taxonomy, which do no I/O; the
caller puts ``backend/`` on ``sys.path``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.domain import (
    CANDIDATE_NOTE_PROMPT_VERSION,
    CANDIDATE_SCORE,
    CANDIDATE_SCORE_VERSION,
    GROUP_SCORE_WEIGHTS,
    HOT_GROUP_CONFIG,
    HOT_GROUP_VERSION,
    INSTITUTIONAL_FLOW_FORMULA_VERSION,
    SIGNAL_CONFIDENCE_SEMANTICS,
    calculate_group_score,
)
from app.strategies import canonical_config_snapshot, canonical_configs
from app.indicators import (
    FIELDS,
    INDICATOR_VERSION,
    PRICE_BASIS,
    IndicatorBar,
    compute_indicators,
)
from app.taxonomy import INDUSTRY_DISPLAY_ZH, canonical_group_id

# ---- calendar ----

TRADING_DATE = date(2026, 10, 16)  # a Friday; the latest session in the fixture
SESSION_COUNT = 130  # enough for MA120 and MACD on the last session
NEXT_SESSION = date(2026, 10, 19)


def _weekdays(end: date, count: int) -> list[date]:
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


SESSIONS = _weekdays(TRADING_DATE, SESSION_COUNT)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    """A naive UTC instant, as every DateTime column stores it."""
    return datetime(day.year, day.month, day.day, hour, minute)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


T = TRADING_DATE
COLLECTED_AT = _at(T, 9, 30)  # 17:30 Taipei, after the official files
CREATED_AT = _at(date(2026, 1, 2), 0)

# ---- instruments ----

TWSE_DAILY_ENDPOINT = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY_ENDPOINT = (
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
)
OFFICIAL_INDUSTRY_SOURCE = "TWSE/TPEx official OpenAPI"

# id, exchange, symbol, name, type, etf_category, industry code, listing date
_INSTRUMENTS = (
    (1, "TWSE", "9101", "示範晶圓", "stock", None, "24", date(2001, 3, 5)),
    (2, "TWSE", "9102", "示範封測", "stock", None, "24", date(2004, 7, 1)),
    (3, "TWSE", "9103", "示範電腦", "stock", None, "25", date(1998, 9, 14)),
    (4, "TPEx", "9201", "示範矽材", "stock", None, "24", date(2012, 11, 20)),
    (5, "TPEx", "9202", "示範板卡", "stock", None, "25", date(2009, 5, 6)),
    (6, "TPEx", "9203", "示範散熱", "stock", None, "25", date(2015, 2, 16)),
    (7, "TPEx", "9204", "示範生技", "stock", None, "22", date(2018, 8, 8)),
    (8, "TWSE", "00990", "示範台灣五十", "etf", "broad_market", None, date(2020, 6, 1)),
    (9, "TWSE", "TAIEX", "發行量加權股價指數", "index", None, None, None),
    # Instrument lifecycle (Issue #212), see LIFECYCLE.
    (10, "TPEx", "9205", "示範下市", "stock", None, "22", date(2010, 4, 1)),
    (11, "TPEx", "9206", "示範轉市", "stock", None, "25", date(2011, 6, 1)),
)
# symbol -> first close, daily drift, base volume in lots
PRICE_PLAN = {
    "9101": (300.0, 0.0020, 8000),
    "9102": (150.0, 0.0012, 5000),
    "9103": (80.0, 0.0018, 12000),
    "9201": (60.0, 0.0016, 3000),
    "9202": (45.0, 0.0010, 2500),
    "9203": (110.0, 0.0005, 1800),
    "9204": (90.0, -0.0004, 1200),
    "00990": (50.0, 0.0008, 20000),
    "TAIEX": (22000.0, 0.0006, 5000000),
    "9205": (30.0, -0.0010, 900),
    "9206": (70.0, 0.0009, 1500),
}
BREAKS_OUT = {"9101", "9103", "9201", "00990"}  # close above the 20-day high on T
WATCHLIST = {"9201"}
INSTRUMENT_IDS = {row[2]: row[0] for row in _INSTRUMENTS}
STOCKS = [row for row in _INSTRUMENTS if row[4] == "stock"]
NO_CHIPS = {"9204"}  # the no-data case: no institutional or margin rows at all

# ---- instrument lifecycle (Issue #212) ----
# The rows the collector leaves for a TPEx stock that left the official lists
# (9205) and one that moved to TWSE (9206); backend/tests/
# test_instrument_lifecycle.py rebuilds them with the worker.  Neither is in a
# current list, page or count; their history stays.
DELISTED, TRANSFERRED = "9205", "9206"
# 9206 kept trading on TPEx after the TPEx list stopped carrying it: the quote
# rows from LIST_GAP_FROM to its last bar are the rows #212 stopped dropping.
LIST_GAP_FROM = SESSIONS[-13]
# symbol: status, last bar, day the lists were observed without it, TWSE
# listing date (a transfer) or None
LIFECYCLE = {
    DELISTED: ("delisted", SESSIONS[-21], SESSIONS[-15], None),
    TRANSFERRED: ("transferred", SESSIONS[-11], SESSIONS[-10], SESSIONS[-10]),
}


def lifecycle_close_day(symbol: str) -> date:
    """The last day its memberships count: before the new listing or observation."""

    _status, _last_bar, observed, listed_elsewhere = LIFECYCLE[symbol]
    return (listed_elsewhere or observed) - timedelta(days=1)


def _instrument_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": item_id,
            "market": "TW",
            "exchange": exchange,
            "symbol": symbol,
            "name": name,
            "instrument_type": kind,
            "etf_category": category,
            "industry": industry,
            "listing_date": listed,
            "is_watchlisted": symbol in WATCHLIST,
            "status": LIFECYCLE[symbol][0] if symbol in LIFECYCLE else "active",
            "created_at": CREATED_AT,
        }
        for item_id, exchange, symbol, name, kind, category, industry, listed in (
            _INSTRUMENTS
        )
    ]


# ---- bars and indicators ----


def _series(symbol: str) -> list[dict[str, Any]]:
    """Deterministic OHLCV; a breakout stock closes above its 20-day high on T."""

    p0, drift, base_volume = PRICE_PLAN[symbol]
    rows = []
    for i, day in enumerate(SESSIONS):
        trend = p0 * (1 + drift * i)
        close = round(trend + p0 * 0.012 * (((i * 37) % 13) - 6) / 6, 2)
        open_ = round(close - p0 * 0.004 * (((i * 11) % 5) - 2), 2)
        high = round(max(open_, close) + p0 * 0.006, 2)
        low = round(min(open_, close) - p0 * 0.006, 2)
        volume = int(base_volume * 1000 * (1 + ((i * 29) % 7) / 10))
        rows.append(
            {
                "day": day,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    if symbol in LIFECYCLE:
        rows = [row for row in rows if row["day"] <= LIFECYCLE[symbol][1]]
    if symbol in BREAKS_OUT:
        prior = rows[-21:-1]
        last = rows[-1]
        last["close"] = round(max(row["high"] for row in prior) * 1.02, 2)
        last["open"] = round(last["close"] * 0.99, 2)
        last["high"] = round(last["close"] * 1.004, 2)
        last["low"] = round(last["open"] * 0.996, 2)
        last["volume"] = int(sum(row["volume"] for row in prior) / 20 * 1.6)
    return rows


SERIES = {row[2]: _series(row[2]) for row in _INSTRUMENTS}
RAW_PAYLOAD_BY_EXCHANGE = {"TWSE": 1, "TPEx": 2}


def _bar_rows() -> list[dict[str, Any]]:
    rows = []
    next_id = 1
    for item_id, exchange, symbol, _name, kind, *_rest in _INSTRUMENTS:
        if kind == "index":
            # coverage.verified_taiex_sessions accepts a TAIEX row whose source
            # names it as test data; the fixture has no MI_INDEX files.
            source = "twse_index_fixture"
        else:
            source = "twse" if exchange == "TWSE" else "tpex"
        for bar in SERIES[symbol]:
            day = bar["day"]
            rows.append(
                {
                    "id": next_id,
                    "instrument_id": item_id,
                    "trading_date": day,
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "adj_close": bar["close"],
                    "volume": bar["volume"],
                    "turnover": round(bar["close"] * bar["volume"], 0),
                    "turnover_status": "available",
                    "source": source,
                    "data_as_of": _at(day, 6),
                    "collected_at": _at(day, 9, 30),
                    # Only T came from the fixture's official collect run.
                    "raw_payload_id": RAW_PAYLOAD_BY_EXCHANGE[exchange]
                    if day == T and kind != "index"
                    else None,
                    "is_suspended": False,
                }
            )
            next_id += 1
    return rows


def _indicator_rows() -> list[dict[str, Any]]:
    rows = []
    next_id = 1
    for item_id, _exchange, symbol, _name, kind, *_rest in _INSTRUMENTS:
        if kind == "index":
            continue
        points = compute_indicators(
            IndicatorBar(
                trading_date=bar["day"],
                open=bar["open"],
                high=bar["high"],
                low=bar["low"],
                close=bar["close"],
                volume=bar["volume"],
            )
            for bar in SERIES[symbol]
        )
        for point in points:
            rows.append(
                {
                    "id": next_id,
                    "instrument_id": item_id,
                    "trading_date": point.trading_date,
                    "formula_version": INDICATOR_VERSION,
                    "price_basis": PRICE_BASIS,
                    "bar_count": point.bar_count,
                    **{name: point.values.get(name) for name in FIELDS},
                    "null_reasons": point.reasons,
                    "source": "derived:market_bars",
                    "computed_at": COLLECTED_AT,
                }
            )
            next_id += 1
    return rows


# ---- chips ----

CHIP_SESSIONS = SESSIONS[-25:]
CHIP_SOURCE_BY_EXCHANGE = {"TWSE": "twse_t86", "TPEx": "tpex_3insti"}


def _chip_rows() -> list[dict[str, Any]]:
    rows = []
    next_id = 1
    for item_id, exchange, symbol, _name, kind, *_rest in STOCKS:
        if symbol in NO_CHIPS or symbol in LIFECYCLE:
            continue
        for i, day in enumerate(CHIP_SESSIONS):
            wobble = ((i * 7 + item_id) % 5) - 2
            rows.append(
                {
                    "id": next_id,
                    "instrument_id": item_id,
                    "trading_date": day,
                    "foreign_buy": float(150000 + 40000 * wobble + 10000 * item_id),
                    "trust_buy": float(30000 + 8000 * wobble),
                    "dealer_buy": float(-5000 + 2000 * wobble),
                    "margin_balance": float(2000 - 15 * i + 100 * item_id),
                    "margin_change": -15.0 if i else 0.0,
                    "short_balance": float(120 + 3 * wobble),
                    "borrowed_sell": float(40 + wobble),
                    "day_trade_ratio": round(0.18 + 0.01 * wobble, 4),
                    "source": CHIP_SOURCE_BY_EXCHANGE[exchange],
                    "data_as_of": _at(day, 8),
                    "collected_at": _at(day, 9, 30),
                }
            )
            next_id += 1
    return rows


def _data_quality_rows() -> list[dict[str, Any]]:
    rows = []
    for item_id, exchange, symbol, _name, kind, *_rest in _INSTRUMENTS:
        if kind == "index":
            continue
        missing = (
            ["foreign_buy", "trust_buy", "dealer_buy", "institutional_flow_5d"]
            if symbol in NO_CHIPS
            else []
        )
        rows.append(
            {
                "id": item_id,
                "entity_type": "instrument",
                "entity_key": f"{exchange}:{symbol}",
                "as_of_date": T,
                "status": "partial" if missing else "complete",
                "missing_fields_json": missing,
                "checks_json": {
                    "market_bar": True,
                    "bars_60d": True,
                    "institutional_flow_5d": not missing,
                },
                "source": "official",
                "checked_at": COLLECTED_AT,
            }
        )
    for offset, (symbol, (status, _last, observed, listed)) in enumerate(
        sorted(LIFECYCLE.items())
    ):
        rows.append(
            {
                "id": 100 + offset,
                "entity_type": "instrument_status",
                "entity_key": f"TPEx:{symbol}",
                "as_of_date": observed,
                "status": status,
                "missing_fields_json": [],
                "checks_json": {
                    "previous_status": "active",
                    "status": status,
                    "reason": "listed_on_other_exchange"
                    if listed
                    else "absent_from_official_lists",
                    "close_day": lifecycle_close_day(symbol).isoformat(),
                },
                "source": "tpex",
                "checked_at": _at(observed, 10),
            }
        )
    return rows


# ---- groups ----

SEMICONDUCTOR_ID = canonical_group_id("industry", "Semiconductor")
COMPUTER_ID = canonical_group_id("industry", "Computer and Peripherals")
BIOTECH_ID = canonical_group_id("industry", "Biotechnology")
AI_SERVER_ID = "theme-demo-ai-server"
PACKAGING_ID = "theme-demo-advanced-packaging"
THEME_VERSION = "themes_v1:2026.10.01"
THEME_SOURCE = "theme_table:tools/verify/fixture_data.py"


def _industry_group(group_id: str, label: str) -> dict[str, Any]:
    return {
        "id": group_id,
        "name": f"Industry · {label}",
        "group_type": "official_industry",
        "definition_version": "official-v1",
        "source": OFFICIAL_INDUSTRY_SOURCE,
        "active": True,
        "display_name_zh": INDUSTRY_DISPLAY_ZH[label],
        "display_description_zh": "依官方共同產業分類建立的市場族群。",
        "display_category": "股票族群",
        "name_source": "TWSE/TPEx official classification",
        "name_status": "official",
    }


def _theme_group(group_id: str, name: str, description: str) -> dict[str, Any]:
    return {
        "id": group_id,
        "name": name,
        "group_type": "theme",
        "definition_version": THEME_VERSION,
        "source": THEME_SOURCE,
        "active": True,
        "display_name_zh": name,
        "display_description_zh": description,
        "display_category": "題材",
        "name_source": THEME_SOURCE,
        "name_status": "verified",
    }


GROUPS = [
    _industry_group(SEMICONDUCTOR_ID, "Semiconductor"),
    _industry_group(COMPUTER_ID, "Computer and Peripherals"),
    _industry_group(BIOTECH_ID, "Biotechnology"),
    _theme_group(
        AI_SERVER_ID, "示範 AI 伺服器", "虛構題材：AI 伺服器組裝與板卡供應鏈。"
    ),
    _theme_group(PACKAGING_ID, "示範先進封裝", "虛構題材：晶圓代工與先進封裝材料。"),
]
# group id -> (board, members in candidate order, rank on T, data quality)
GROUP_PLAN = {
    SEMICONDUCTOR_ID: ("industry", ["9101", "9201", "9102"], 1, "complete"),
    COMPUTER_ID: ("industry", ["9103", "9202", "9203"], 2, "complete"),
    # One member is below MIN_GROUP_MEMBERS: stored unscored and unranked.
    # The delisted 9205 and the moved 9206 left these groups (LIFECYCLE).
    BIOTECH_ID: ("industry", ["9204"], None, "insufficient_members"),
    AI_SERVER_ID: ("theme", ["9101", "9103", "9202"], 1, "complete"),
    PACKAGING_ID: ("theme", ["9101", "9201", "9102"], 2, "complete"),
}
SYMBOL_EXCHANGE = {row[2]: row[1] for row in _INSTRUMENTS}
MEMBERS_FROM = date(2026, 1, 2)


def _membership_source(group_id: str, symbol: str) -> str:
    board = GROUP_PLAN[group_id][0]
    if board == "industry":
        return f"{OFFICIAL_INDUSTRY_SOURCE}; exchange={SYMBOL_EXCHANGE[symbol]}"
    return (
        '{"kind":"theme_table","url":"https://example.com/demo/'
        f'{symbol}","relation":"product_line","relevance":"high",'
        f'"theme_version":"{THEME_VERSION}"}}'
    )


def _membership_rows() -> list[dict[str, Any]]:
    rows = []
    next_id = 1
    for group_id, (_board, members, _rank, _quality) in GROUP_PLAN.items():
        for symbol in sorted(members):
            rows.append(
                {
                    "id": next_id,
                    "group_id": group_id,
                    "instrument_id": INSTRUMENT_IDS[symbol],
                    "role": "member",
                    "confidence": 1.0,
                    "valid_from": MEMBERS_FROM,
                    "valid_to": None,
                    "source": _membership_source(group_id, symbol),
                }
            )
            next_id += 1
    for symbol, group_id in ((DELISTED, BIOTECH_ID), (TRANSFERRED, COMPUTER_ID)):
        rows.append(
            {
                "id": next_id,
                "group_id": group_id,
                "instrument_id": INSTRUMENT_IDS[symbol],
                "role": "member",
                "confidence": 1.0,
                "valid_from": MEMBERS_FROM,
                "valid_to": lifecycle_close_day(symbol),
                "source": f"{OFFICIAL_INDUSTRY_SOURCE}; exchange=TPEx",
            }
        )
        next_id += 1
    return rows


SCORE_SESSIONS = SESSIONS[-5:]


def _score_rows() -> list[dict[str, Any]]:
    rows = []
    next_id = 1
    for offset, day in enumerate(SCORE_SESSIONS):
        for group_id, (board, members, rank, quality) in GROUP_PLAN.items():
            lead = rank == 1
            ranked = rank is not None
            step = offset - (len(SCORE_SESSIONS) - 1)  # 0 on T
            relative = {
                "1d": round((0.012 if lead else 0.004) + 0.001 * step, 6),
                "5d": round((0.035 if lead else 0.015) + 0.002 * step, 6),
                "20d": round((0.080 if lead else 0.030) + 0.003 * step, 6),
            }
            flow_complete = not any(symbol in NO_CHIPS for symbol in members)
            normalized = {
                "relative_return": 1.0 if lead else 0.0,
                "breadth": round((0.9 if lead else 0.6) + 0.01 * step, 6),
                "volume_strength": 1.0 if lead else 0.0,
                "institutional_flow": (1.0 if lead else 0.0) if flow_complete else None,
                "catalyst": round((0.6 if lead else 0.3) + 0.02 * step, 6),
            }
            score = calculate_group_score(normalized) if ranked else None
            candidates = (
                [
                    {
                        "instrument_id": INSTRUMENT_IDS[symbol],
                        "exchange": SYMBOL_EXCHANGE[symbol],
                        "symbol": symbol,
                    }
                    for symbol in members
                ]
                if ranked
                else []
            )
            rows.append(
                {
                    "id": next_id,
                    "group_id": group_id,
                    "trading_date": day,
                    "relative_return": relative["20d"],
                    "relative_return_1d": relative["1d"],
                    "relative_return_5d": relative["5d"],
                    "relative_return_20d": relative["20d"],
                    "breadth": normalized["breadth"],
                    "volume_strength": normalized["volume_strength"],
                    "institutional_flow": normalized["institutional_flow"],
                    "catalyst": normalized["catalyst"],
                    "score": score,
                    "rank": rank,
                    "eligible_members": len(members),
                    "data_quality": quality,
                    "details_json": {
                        "hot_group_version": HOT_GROUP_VERSION,
                        "benchmark": "TAIEX",
                        "benchmark_returns": {"1d": 0.004, "5d": 0.011, "20d": 0.025},
                        "candidate_identity_version": "instrument-id-v1",
                        "candidate_instruments": candidates,
                        "candidate_symbols": [item["symbol"] for item in candidates],
                        "minimum_candidate_policy": [2, 4],
                        "normalized_values": normalized,
                        "institutional_flow_coverage": {
                            "available": sum(
                                symbol not in NO_CHIPS for symbol in members
                            ),
                            "eligible": len(members),
                            "member_count": len(members),
                            "complete": flow_complete,
                        },
                        "leaderboard": "equity",
                        "board": board,
                        "member_count": len(members),
                        "weights": GROUP_SCORE_WEIGHTS,
                        "methodology": HOT_GROUP_CONFIG["components"],
                    },
                }
            )
            next_id += 1
    return rows


# ---- strategies and signals ----

STRATEGY_IDS = {"breakout_v1": 1, "pullback_v1": 2, "hot_group_v1": 3}


def _strategy_rows() -> list[dict[str, Any]]:
    snapshots = canonical_config_snapshot()
    return [
        {
            "id": STRATEGY_IDS[key],
            "name": config["name"],
            "version": config["version"],
            "formula_version": INSTITUTIONAL_FLOW_FORMULA_VERSION,
            "kind": config["kind"],
            "config_json": snapshots[key],
            "canonical_config_snapshot": snapshots[key],
            "active": True,
            "created_at": CREATED_AT,
        }
        for key, config in canonical_configs().items()
    ]


# symbol -> (breakout status, pullback status); the ETF's conditional breakout
# is excluded from the candidate pool (stock and ipo only).
SIGNAL_PLAN = {
    "9101": ("conditional", "observation"),
    "9102": ("observation", "observation"),
    "9103": ("conditional", "observation"),
    "9201": ("conditional", "observation"),
    "9202": ("observation", "observation"),
    "9203": ("observation", "observation"),
    "9204": ("data_incomplete", "data_incomplete"),
    "00990": ("conditional", "observation"),
}
GROUP_OF = {
    "9101": SEMICONDUCTOR_ID,
    "9102": SEMICONDUCTOR_ID,
    "9201": SEMICONDUCTOR_ID,
}


def _signal_rows() -> list[dict[str, Any]]:
    rows = []
    next_id = 1
    for symbol, statuses in SIGNAL_PLAN.items():
        item_id = INSTRUMENT_IDS[symbol]
        exchange = SYMBOL_EXCHANGE[symbol]
        bars = SERIES[symbol]
        prior = bars[-21:-1]
        close = bars[-1]["close"]
        closes = [bar["close"] for bar in bars]
        ma20 = round(sum(closes[-20:]) / 20, 4)
        ma60 = round(sum(closes[-60:]) / 60, 4)
        for strategy, status in zip(("breakout_v1", "pullback_v1"), statuses):
            breakout = strategy == "breakout_v1"
            conditional = status == "conditional"
            entry = close
            invalid = round(entry * 0.95, 2) if conditional else None
            target_1 = (
                round(entry + 1.6 * (entry - invalid), 2) if conditional else None
            )
            target_2 = (
                round(entry + 2.4 * (entry - invalid), 2) if conditional else None
            )
            incomplete = status == "data_incomplete"
            rows.append(
                {
                    "id": next_id,
                    "signal_key": f"analysis-{exchange}-{symbol}-{T.isoformat()}-{strategy}-1.0.0",
                    "signal_date": T,
                    "instrument_id": item_id,
                    "strategy_version_id": STRATEGY_IDS[strategy],
                    "status": status,
                    "entry_type": "breakout" if breakout else "pullback",
                    "breakout_price": entry if conditional else None,
                    "invalid_price": invalid,
                    "target_1": target_1,
                    "target_2": target_2,
                    "rationale": (
                        f"breakout={'passed' if conditional else 'not_triggered'}; "
                        f"pullback=not_triggered; "
                        + (
                            "missing=institutional_flow_to_turnover_ratio_5d"
                            if incomplete
                            else "required inputs complete"
                        )
                    ),
                    "data_cutoff": f"{T.isoformat()} 13:30 Asia/Taipei",
                    "source_report": "twse" if exchange == "TWSE" else "tpex",
                    "earliest_execution_date": NEXT_SESSION,
                    "data_quality": "incomplete" if incomplete else "complete",
                    "rule_evidence_json": {
                        "strategy": strategy,
                        "strategy_version": "1.0.0",
                        "confidence_semantics": SIGNAL_CONFIDENCE_SEMANTICS,
                        "actionable": conditional,
                        "breakout": {
                            "state": "passed"
                            if breakout and conditional
                            else "not_triggered",
                            "reasons": [],
                        },
                        "pullback": {"state": "not_triggered", "reasons": []},
                        "inputs": {
                            "prior_20_highs": [bar["high"] for bar in prior],
                            "prior_20_volumes": [bar["volume"] for bar in prior],
                            "group_excess_return_20d": 0.08
                            if symbol in GROUP_OF
                            else 0.03,
                            "institutional_flow_to_turnover_ratio_5d": None
                            if incomplete
                            else 0.12,
                            "strategy_institutional_flow_to_average_volume_ratio_5d": None
                            if incomplete
                            else 0.12,
                            "institutional_flow_ratio_denominator": "average_daily_volume_20d",
                            "institutional_flow_formula_version": INSTITUTIONAL_FLOW_FORMULA_VERSION,
                            "margin_balance_change_ratio_5d": None
                            if incomplete
                            else -0.03,
                            "bar_count_60d": 60,
                            "ma20": ma20,
                            "ma60": ma60,
                        },
                        "risk_validation": {"valid": True, "errors": []},
                        "execution": {
                            "signal_time": "T_close",
                            "earliest": NEXT_SESSION.isoformat(),
                            "fill_policy": "next_session_open_or_better_plus_adverse_slippage",
                        },
                    },
                    "created_at": COLLECTED_AT,
                }
            )
            next_id += 1
    return rows


# ---- runs and payloads ----


def _ingestion_rows() -> list[dict[str, Any]]:
    def run(
        item_id,
        run_type,
        source,
        records,
        data_as_of,
        metadata,
        start,
        *,
        run_date=T,
        status="success",
    ):
        return {
            "id": item_id,
            "run_type": run_type,
            "source": source,
            "run_date": run_date,
            "status": status,
            "records": records,
            "request_key": f"{run_type}:{source}:{run_date.isoformat()}",
            "data_as_of": data_as_of,
            "metadata_json": metadata,
            "started_at": start,
            "finished_at": start + timedelta(minutes=10),
            "updated_at": start + timedelta(minutes=10),
        }

    return [
        run(1, "collect", "official", 7, T.isoformat(), {"fixture": True}, _at(T, 9)),
        run(
            2,
            "news",
            "news",
            5,
            f"{T.isoformat()}T10:00:00+08:00",
            {"feeds": 2},
            _at(T, 2),
        ),
        run(
            3,
            "news_llm",
            "claude",
            4,
            None,
            {"prompt_version": NEWS_PROMPT_VERSION, "calls": 4},
            _at(T, 3),
        ),
        run(
            4,
            "candidate_notes",
            "claude",
            3,
            None,
            {"prompt_version": CANDIDATE_NOTE_PROMPT_VERSION, "calls": 3},
            _at(T, 10),
        ),
        # The next weekday was a market holiday (Issue #249): the newest official
        # collect run found no data, and the pages keep showing T.
        run(
            5,
            "collect",
            "official",
            0,
            None,
            {"fixture": True, "no_data_dates": [NEXT_SESSION.isoformat()]},
            _at(NEXT_SESSION, 13, 20),
            run_date=NEXT_SESSION,
            status="skipped",
        ),
    ]


def _raw_payload_rows() -> list[dict[str, Any]]:
    def raw(item_id, run_id, source, endpoint, data_as_of):
        digest = _sha(f"{source}|{endpoint}|{data_as_of}")
        return {
            "id": item_id,
            "ingestion_run_id": run_id,
            "source": source,
            "endpoint": endpoint,
            # Fictional location; the fixture ships no raw files.
            "payload_path": f"raw/{source}/{T:%Y/%m/%d}/{digest}.json",
            "sha256": digest,
            "data_as_of": data_as_of,
            "collected_at": COLLECTED_AT,
        }

    return [
        raw(1, 1, "twse", TWSE_DAILY_ENDPOINT, T.isoformat()),
        raw(2, 1, "tpex", TPEX_DAILY_ENDPOINT, T.isoformat()),
        raw(
            3, 2, "news:demo_finance", "https://example.com/rss/finance", T.isoformat()
        ),
        raw(4, 2, "news:demo_wire", "https://example.org/rss/markets", T.isoformat()),
        raw(
            5, 1, "mops", "https://example.net/mops/material-information", T.isoformat()
        ),
    ]


# ---- news ----

DOMESTIC_SOURCE = "示範財經社"
INTERNATIONAL_SOURCE = "Demo Wire"


def _news(
    item_id: int,
    *,
    category: str,
    source_kind: str,
    source_name: str,
    title: str,
    summary: str,
    published_at: datetime | None,
    event_date: date | None = None,
    symbols: list[str],
    raw_payload_id: int,
    language: str = "zh-Hant",
) -> dict[str, Any]:
    key = f"news:fixture:{item_id}"
    if published_at is not None:
        temporal = {
            "published_at": published_at,
            "event_date": None,
            "time_basis": "published",
            "time_precision": "datetime",
            "display_time": published_at,
        }
    else:
        temporal = {
            "published_at": None,
            "event_date": event_date,
            "time_basis": "event_date",
            "time_precision": "date",
            "display_time": datetime(event_date.year, event_date.month, event_date.day),
        }
    return {
        "id": item_id,
        "canonical_key": key,
        "dedupe_cluster_id": key,
        "category": category,
        "source_kind": source_kind,
        "source_name": source_name,
        "source_url": f"https://example.com/news/{item_id}",
        "source_url_kind": "item",
        "source_item_id": f"fixture-{item_id}",
        "title": title,
        "summary": summary,
        "language": language,
        **temporal,
        "time_consistency": "verified",
        "collected_at": COLLECTED_AT,
        "symbols_json": symbols,
        "theme_ids_json": [],
        "impact_scope": "instrument" if symbols else "market",
        "impact_direction": "unknown",
        "impact_method": "default_unknown",
        "confidence": "unknown",
        "raw_payload_id": raw_payload_id,
        "content_hash": _sha(f"{key}|{title}|{summary}"),
        "status": "active",
    }


def _news_rows() -> list[dict[str, Any]]:
    yesterday = SESSIONS[-2]
    return [
        _news(
            1,
            category="domestic",
            source_kind="media",
            source_name=DOMESTIC_SOURCE,
            title="示範晶圓第三季營收創新高 先進製程需求續強",
            summary="虛構新聞：示範晶圓公布第三季營收，年增兩成，先進製程占比提高。",
            published_at=_at(T, 1, 30),
            symbols=["TWSE:9101"],
            raw_payload_id=3,
        ),
        _news(
            2,
            category="domestic",
            source_kind="media",
            source_name=DOMESTIC_SOURCE,
            title="伺服器需求升溫 示範電腦液冷機櫃接單轉強",
            summary="虛構新聞：示範電腦表示液冷機櫃訂單能見度延伸至明年上半年。",
            published_at=_at(yesterday, 5, 0),
            symbols=["TWSE:9103"],
            raw_payload_id=3,
        ),
        _news(
            3,
            category="domestic",
            source_kind="media",
            source_name=DOMESTIC_SOURCE,
            title="示範散熱新廠擴產進度延後一季",
            summary="虛構新聞：示範散熱新廠設備進駐時程延後，尚未產生 AI 判讀。",
            published_at=_at(yesterday, 3, 0),
            symbols=["TPEx:9203"],
            raw_payload_id=3,
        ),
        _news(
            4,
            category="international",
            source_kind="media",
            source_name=INTERNATIONAL_SOURCE,
            title="Demo: global chip equipment orders rise for a third month",
            summary="Fictional story: equipment makers report higher orders from foundries.",
            published_at=_at(yesterday, 13, 0),
            symbols=[],
            raw_payload_id=4,
            language="en",
        ),
        _news(
            5,
            category="international",
            source_kind="media",
            source_name=INTERNATIONAL_SOURCE,
            title="Demo: cloud provider trims next-year capex guidance",
            summary="Fictional story: a cloud provider lowers its capital spending plan.",
            published_at=_at(T, 0, 30),
            symbols=[],
            raw_payload_id=4,
            language="en",
        ),
        _news(
            6,
            category="company",
            source_kind="official_disclosure",
            source_name="MOPS",
            title="示範封測 公告董事會通過現金股利分派",
            summary="虛構公告：董事會決議每股配發現金股利 3 元。",
            published_at=None,
            event_date=T,
            symbols=["TWSE:9102"],
            raw_payload_id=5,
        ),
    ]


LLM_MODEL = "claude-sonnet-5-5"
# The news prompt version the current candidate score reads (#262).
NEWS_PROMPT_VERSION = CANDIDATE_SCORE["components"]["news_sentiment"][
    "llm_prompt_version"
]


def _llm_rows() -> list[dict[str, Any]]:
    def result(item_id, news_id, summary, symbols, themes, direction, scope, rationale):
        return {
            "id": item_id,
            "news_item_id": news_id,
            "prompt_version": NEWS_PROMPT_VERSION,
            "llm_model": LLM_MODEL,
            "llm_input_hash": _sha(f"{NEWS_PROMPT_VERSION}|{news_id}"),
            "llm_run_at": _at(T, 3, item_id),
            "llm_status": "done",
            "ai_summary": summary,
            "ai_symbol_candidates_json": symbols,
            "ai_theme_candidates_json": themes,
            "ai_impact_direction": direction,
            "ai_impact_scope": scope,
            "ai_impact_rationale": rationale,
            "ai_unsupported": False,
            "ingestion_run_id": 3,
        }

    return [
        result(
            1,
            1,
            "示範晶圓營收成長，先進製程需求支撐獲利。",
            [{"symbol": "TWSE:9101", "reason": "營收創新高", "confidence": "high"}],
            [{"theme": "示範車用晶片", "reason": "先進製程需求來自車用"}],
            "positive",
            "instrument",
            "營收與製程占比提升屬正面訊息。",
        ),
        result(
            2,
            2,
            "示範電腦液冷機櫃訂單增加。",
            [{"symbol": "TWSE:9103", "reason": "液冷機櫃接單", "confidence": "medium"}],
            [{"theme": "示範液冷散熱", "reason": "液冷機櫃需求"}],
            "positive",
            "instrument",
            "訂單能見度延長。",
        ),
        result(
            3,
            4,
            "全球設備訂單連三月成長。",
            [],
            [{"theme": "示範液冷散熱", "reason": "資料中心擴建帶動"}],
            "positive",
            "market",
            "設備訂單增加反映晶圓廠擴產。",
        ),
        result(
            4,
            5,
            "雲端業者下修資本支出。",
            [],
            [],
            "negative",
            "market",
            "資本支出下修可能壓抑伺服器需求。",
        ),
    ]


def _suggestion_rows() -> list[dict[str, Any]]:
    yesterday = SESSIONS[-2]

    def suggestion(item_id, name, count, first, last):
        return {
            "id": item_id,
            "theme_key": name,  # theme_key(): NFKC, no whitespace, casefold
            "display_name": name,
            "prompt_version": NEWS_PROMPT_VERSION,
            "aggregation_version": "theme_suggestions_v1",
            "llm_models_json": [LLM_MODEL],
            "news_count": count,
            "first_news_date": first,
            "last_news_date": last,
            "status": "pending_verification",
            "computed_at": _at(T, 4),
        }

    return [
        suggestion(1, "示範液冷散熱", 2, yesterday, yesterday),
        suggestion(2, "示範車用晶片", 1, T, T),
    ]


def _suggestion_news_rows() -> list[dict[str, Any]]:
    yesterday = SESSIONS[-2]
    return [
        {
            "id": 1,
            "suggestion_id": 1,
            "news_item_id": 2,
            "news_llm_result_id": 2,
            "theme_text": "示範液冷散熱",
            "reason": "液冷機櫃需求",
            "news_date": yesterday,
        },
        {
            "id": 2,
            "suggestion_id": 1,
            "news_item_id": 4,
            "news_llm_result_id": 3,
            "theme_text": "示範液冷散熱",
            "reason": "資料中心擴建帶動",
            "news_date": yesterday,
        },
        {
            "id": 3,
            "suggestion_id": 2,
            "news_item_id": 1,
            "news_llm_result_id": 1,
            "theme_text": "示範車用晶片",
            "reason": "先進製程需求來自車用",
            "news_date": T,
        },
    ]


# ---- daily candidates ----

# The scoring output of worker.candidates.compute_daily_candidates on these rows,
# frozen so the fixture never runs the scorer or reads the clock.  Refresh it
# with tools/verify/freeze_candidates.py; the backend test runs its --check.
_FROZEN_CANDIDATES = json.loads(
    (Path(__file__).with_name("fixture_candidates.json")).read_text(encoding="utf-8")
)


def _candidate_run_rows() -> list[dict[str, Any]]:
    run = _FROZEN_CANDIDATES["run"]
    return [
        {
            "id": 1,
            "trading_date": T,
            "score_version": CANDIDATE_SCORE_VERSION,
            "status": "success",
            "evaluated_signals": run["evaluated_signals"],
            "pool_count": run["pool_count"],
            "candidate_count": run["candidate_count"],
            "exclusions_json": run["exclusions_json"],
            "config_json": json.loads(json.dumps(CANDIDATE_SCORE)),
            "summary_json": run["summary_json"],
            "computed_at": _at(T, 10),
        }
    ]


def _daily_candidate_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": index,
            "candidate_run_id": 1,
            "trading_date": T,
            "instrument_id": row["instrument_id"],
            "signal_id": row["signal_id"],
            "strategy": row["strategy"],
            "score_version": CANDIDATE_SCORE_VERSION,
            "total_score": row["total_score"],
            "weight_coverage": row["weight_coverage"],
            "rank": row["rank"],
            "components_json": row["components_json"],
            "reasons_json": row["reasons_json"],
            "groups_json": row["groups_json"],
            "data_as_of": T,
            "created_at": _at(T, 10),
        }
        for index, row in enumerate(_FROZEN_CANDIDATES["rows"], start=1)
    ]


_NOTES = {
    "9101": (
        "突破 20 日高點且量比 1.6，所屬半導體產業熱度第 1。",
        "進場參考突破價，跌破停損價出場。",
        "營收動能若放緩，突破可能失敗。",
    ),
    "9103": (
        "突破整理區間，液冷機櫃新聞偏多。",
        "依突破價進場，目標價為規則數值。",
        "電腦及週邊族群熱度第 2，資金集中度低於半導體。",
    ),
    "9201": (
        "上櫃矽材突破 20 日高點，外資投信同步買超。",
        "停損設於規則失效價。",
        "成交量偏低，價格波動可能放大。",
    ),
}


def _candidate_note_rows() -> list[dict[str, Any]]:
    symbols = {item_id: symbol for symbol, item_id in INSTRUMENT_IDS.items()}
    rows = []
    for index, candidate in enumerate(_daily_candidate_rows(), start=1):
        selection, levels, risks = _NOTES[symbols[candidate["instrument_id"]]]
        rows.append(
            {
                "id": index,
                "daily_candidate_id": candidate["id"],
                "candidate_run_id": 1,
                "trading_date": T,
                "prompt_version": CANDIDATE_NOTE_PROMPT_VERSION,
                "llm_model": LLM_MODEL,
                "llm_input_hash": _sha(
                    f"{CANDIDATE_NOTE_PROMPT_VERSION}|{candidate['id']}"
                ),
                "llm_run_at": _at(T, 10, 10 + index),
                "llm_status": "done",
                "ai_selection": selection,
                "ai_levels": levels,
                "ai_risks": risks,
                "ingestion_run_id": 4,
            }
        )
    return rows


# ---- portfolio ----


def _portfolio_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "instrument_id": INSTRUMENT_IDS["9102"],
            "shares": 2000.0,
            "shares_integer": 2000,
            "average_cost": 150.0,
            "stop_price": 140.0,
            "risk_budget": 20000.0,
            "note": "示範庫存（虛構）",
            "updated_at": _at(date(2026, 10, 1), 2),
        }
    ]


# ---- assembled tables (insertion order respects foreign keys) ----

TABLES: dict[str, list[dict[str, Any]]] = {
    "ingestion_runs": _ingestion_rows(),
    "raw_payloads": _raw_payload_rows(),
    "instruments": _instrument_rows(),
    "strategy_versions": _strategy_rows(),
    "theme_groups": GROUPS,
    "group_memberships": _membership_rows(),
    "market_bars": _bar_rows(),
    "technical_indicators": _indicator_rows(),
    "chip_snapshots": _chip_rows(),
    "data_quality": _data_quality_rows(),
    "group_daily_scores": _score_rows(),
    "signals": _signal_rows(),
    "news_items": _news_rows(),
    "news_llm_results": _llm_rows(),
    "theme_suggestions": _suggestion_rows(),
    "theme_suggestion_news": _suggestion_news_rows(),
    "candidate_runs": _candidate_run_rows(),
    "daily_candidates": _daily_candidate_rows(),
    "candidate_llm_notes": _candidate_note_rows(),
    "portfolio_positions": _portfolio_rows(),
}

INTENTIONALLY_EMPTY: dict[str, dict[str, str]] = {
    "candidate_llm_notes": {
        "llm_error": "三則筆記都是 done，沒有錯誤",
        "raw_payload_id": "LLM 筆記不保存原始回應檔",
    },
    "candidate_runs": {"zero_reason": "當日有 3 檔候選，不是零候選"},
    "chip_snapshots": {"raw_payload_id": "假資料不附法人原始檔"},
    "ingestion_runs": {"error": "沒有失敗的執行；休市日的 skipped 不寫 error"},
    "market_bars": {
        "turnover_reason": "成交值都是 available；原因只在 unavailable／unknown 時寫"
    },
    "news_items": {
        "event_at": "媒體新聞用發布時間、官方公告用事件日，沒有事件時刻",
        "impact_rationale": "規則關聯不判方向（impact_direction=unknown），方向判讀在 news_llm_results",
        "event_id": "不放 events（見 OMITTED_TABLES）",
        "supersedes_id": "沒有更正或取代的新聞",
    },
    "news_llm_results": {
        "llm_error": "四筆判讀都是 done，沒有錯誤",
        "raw_payload_id": "LLM 判讀不保存原始回應檔",
    },
    "signals": {
        "reference_entry": "沒有成立的拉回訊號；拉回價位只在 pullback 成立時寫",
        "pullback_low": "同 reference_entry",
        "pullback_high": "同 reference_entry",
        "confidence": "新訊號不寫信心值（SIGNAL_CONFIDENCE_SEMANTICS：未校準）",
        "execution_date": "最早可成交日 2026-10-19 休市（ingestion_runs id 5 skipped），還沒有成交",
        "execution_price": "同 execution_date",
    },
    "theme_suggestions": {"matched_group_id": "兩個建議都是新題材，未對應既有族群"},
}

OMITTED_TABLES: dict[str, str] = {
    "alembic_version": "migration 自己寫入 head 版本，假資料不寫",
    "corporate_actions": "沒有除權息或分割；個股頁不需還原價格",
    "events": (
        "官方公告直接寫成 news_items（source_kind=official_disclosure）；"
        "有 events 時 sync_news_from_events 會在 GET 時改寫 news_items"
    ),
    "fundamental_snapshots": "五個主導航的檢查不讀基本面；個股頁該區顯示無資料",
    "group_daily_score_archive": "只在 hot_group 版本升級時封存舊分數；假資料只有現行版本",
    "schedule_runs": "排程紀錄只給看門狗與系統頁",
    "schedule_run_steps": "同 schedule_runs",
    "signal_evaluations": "訊號在最後一個交易日產生，還沒有後續交易日可評估",
    "signal_settlements": "同 signal_evaluations，尚無結算",
    "strategy_levels": "條件價位還沒有頁面與 API（#274 策略總表加 API 時一起加假資料）",
    "technical_features": "舊版特徵表；K 線與指標讀 technical_indicators",
    "tracking_plans": "使用者追蹤計畫還沒有頁面與 API（#253 加頁面時一起加假資料）",
    "tracking_plan_sessions": "同 tracking_plans",
}

# ---- expected API results per main page ----
#
# Endpoints are those of .claude/skills/verify-stock-lab/features/*.md, with the
# values those files carry between pages filled in: T (today board #1) is the
# semiconductor group, and E/S (its first member by price) is TWSE 9101.
# Each check is (path under /api, JSON path, expected).  JSON path segments are
# dict keys or list indexes; "[]" maps the rest of the path over a list.  A list
# compared with an int is compared by length; anything else by value.

D = T.isoformat()  # dashboard as_of, every board's trading_date, candidates' date
TOP_THEME = SEMICONDUCTOR_ID
E, S = "TWSE", "9101"
NO_DATA_STOCK = ("TPEx", "9204")

EXPECTED: dict[str, list[tuple[str, str, Any]]] = {
    "today": [
        ("dashboard", "as_of", D),
        ("dashboard", "market.instruments", 8),  # 7 stocks + 1 ETF, not TAIEX
        ("dashboard", "news", 6),
        ("dashboard", "news[].id", ["1", "5", "6", "4", "2", "3"]),
        # The today card carries the detail's ai block (#233).
        (
            "dashboard",
            "news[].ai.status",
            ["done", "done", None, "done", "done", None],
        ),
        ("dashboard", "themes", 5),
        (
            "dashboard",
            "candidates",
            5,
        ),  # 4 conditional entries (one is the ETF) + held 9102
        ("dashboard", "actions", 7),
        ("dashboard", "action_counts.held", 1),
        ("themes?board=industry&limit=10", "meta.trading_date", D),
        ("themes?board=industry&limit=10", "items", 2),
        ("themes?board=industry&limit=10", "items.0.theme_id", TOP_THEME),
        ("themes?board=industry&limit=10", "items.0.display_name", "半導體"),
        ("candidates", "status", "success"),
        ("candidates", "trading_date", D),
        ("candidates", "candidate_count", 3),
        ("candidates", "items[].instrument.symbol", ["9101", "9103", "9201"]),
        ("candidates", "items[].llm_note.status", ["done", "done", "done"]),
        ("news/1", "ai.status", "done"),
        ("news/5", "ai.status", "done"),
        ("news/6", "ai", None),
    ],
    "news": [
        ("news?category=domestic&limit=20", "items", 3),
        (
            "news?category=domestic&limit=20",
            "items[].ai.status",
            ["done", "done", None],
        ),
        ("news?category=international&limit=20", "items", 2),
        ("news?category=international&limit=20", "items[].ai.status", ["done", "done"]),
        ("news?source_kind=official_disclosure&limit=20", "items", 1),
        (
            "news?source_kind=official_disclosure&limit=20",
            "items.0.source_name",
            "MOPS",
        ),
        ("news/1", "ai.model", LLM_MODEL),
        ("news/1", "ai.prompt_version", NEWS_PROMPT_VERSION),
        # llm_run_at is stored naive UTC; the API states the zone (#234).
        ("news/1", "ai.generated_at", f"{D}T03:01:00+00:00"),
    ],
    "themes": [
        ("themes?board=industry&limit=100", "meta.total", 2),
        (
            "themes?board=industry&limit=100",
            "items[].display_name",
            ["半導體", "電腦及週邊"],
        ),
        ("themes?board=theme&limit=100", "meta.total", 2),
        ("themes?board=theme&limit=100", "meta.trading_date", D),
        (
            "themes?board=theme&limit=100",
            "items[].display_name",
            ["示範 AI 伺服器", "示範先進封裝"],
        ),
        ("theme-suggestions?limit=20", "meta.total", 2),
        ("theme-suggestions?limit=20", "items[].news_count", [2, 1]),
        (f"themes/{TOP_THEME}", "members_total", 3),
        # The delisted 9205 and the moved 9206 left these groups (LIFECYCLE).
        (f"themes/{BIOTECH_ID}", "members_total", 1),
        (f"themes/{COMPUTER_ID}", "members_total", 3),
        (f"themes/{TOP_THEME}", "trend", 5),
        (f"themes/{TOP_THEME}/members?page=1&page_size=30&sort=price", "meta.total", 3),
        (
            f"themes/{TOP_THEME}/members?page=1&page_size=30&sort=price",
            "items[].symbol",
            ["9101", "9102", "9201"],
        ),
    ],
    "stocks": [
        ("stocks?page=1&page_size=30", "meta.total", 8),
        ("stocks?page=1&page_size=30", "items", 8),
        # Neither lifecycle stock is a current instrument; their history stays.
        (
            "stocks?q=920&page=1&page_size=30",
            "items[].instrument.symbol",
            ["9201", "9202", "9203", "9204"],
        ),
        (f"stocks/TPEx/{DELISTED}", "instrument.status", "delisted"),
        (f"stocks/TPEx/{TRANSFERRED}", "instrument.status", "transferred"),
        (
            f"stocks/TPEx/{DELISTED}/bars?interval=day&limit=250",
            "bars.-1.date",
            LIFECYCLE[DELISTED][1].isoformat(),
        ),
        (f"stocks/{E}/{S}", "chips", 25),
        (f"stocks/{E}/{S}", "news", 1),
        (f"stocks/{E}/{S}", "candidate.rank", 1),
        (f"stocks/{E}/{S}", "decision_summary.action_state", "conditional_entry"),
        (f"stocks/{E}/{S}/bars?interval=day&limit=250", "bars", SESSION_COUNT),
        (f"stocks/{E}/{S}/bars?interval=day&limit=250", "bars.-1.date", D),
        (f"stocks/{E}/{S}/bars?interval=day&limit=250", "bars.-1.reasons", {}),
        (f"news?symbol={S}&limit=50", "items", 1),
        # The no-data case: no institutional or margin rows.
        ("stocks/{}/{}".format(*NO_DATA_STOCK), "chips", 0),
        (
            "stocks/{}/{}".format(*NO_DATA_STOCK),
            "decision_summary.action_state",
            "data_insufficient",
        ),
    ],
    "actions": [
        ("actions?limit=20", "meta.total", 7),
        ("actions?limit=20", "items", 7),
        ("actions?limit=20", "items.0.instrument.symbol", "9102"),  # the held position
        ("actions?limit=20", "summary.held", 1),
        ("actions?limit=20", "summary.actionable", 5),
        ("portfolio?page=1&page_size=20", "pagination.total", 1),
        ("portfolio?page=1&page_size=20", "items", 1),
        (f"actions/{E}/{S}", "decision_summary.action_state", "conditional_entry"),
    ],
}


def resolve(payload: Any, path: str) -> Any:
    """The value at ``path`` (see EXPECTED); None when a step is missing."""

    if not path:
        return payload
    head, _, rest = path.partition(".")
    mapped = head.endswith("[]")
    key = head[:-2] if mapped else head
    if isinstance(payload, list):
        try:
            payload = payload[int(key)]
        except (ValueError, IndexError):
            return None
    elif isinstance(payload, dict):
        payload = payload.get(key)
    else:
        return None
    if mapped:
        return (
            [resolve(item, rest) for item in payload]
            if isinstance(payload, list)
            else None
        )
    return resolve(payload, rest)


def actual_for(payload: Any, path: str, expected: Any) -> Any:
    """What ``expected`` is compared with: a list's length when an int is expected."""

    value = resolve(payload, path)
    if isinstance(value, list) and type(expected) is int:
        return len(value)
    return value
