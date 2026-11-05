"""The audit items (Issue #391); each returns a ``Check`` and never writes anything.

Data items read the database and the raw captures; derived items recompute
indicators, the 5/20-day chip ratios, candidate scores and group scores
from the stored bars, chips and corporate actions (``audit_series``).
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from audit_lib import (
    DIVIDEND_DEDUCTED_PRICES,
    INDICATOR_VERSION,
    PRICE_BASIS,
    REFERENCE_TOLERANCE,
    Action,
    Check,
    RawFiles,
    action_rows,
    close_enough,
    columns,
    field_factor,
    finite,
    institutional_rows,
    margin_rows,
    mid_rank,
    num,
    official_prices,
    positive,
    quote_rows,
    taiex_close,
    tables,
)
from audit_series import FIELDS, Series, evidence_lookup, indicators, load_series

QUOTE_ENDPOINTS = {
    "TWSE": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
    "TPEx": "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
}
INSTITUTIONAL_ENDPOINTS = {
    "TWSE": "https://www.twse.com.tw/rwd/zh/fund/T86",
    "TPEx": "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
}
MARGIN_ENDPOINTS = {
    "TWSE": "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
    "TPEx": "https://www.tpex.org.tw/www/zh-tw/margin/balance",
}
ACTION_ENDPOINTS = (
    "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL",
    "https://www.twse.com.tw/rwd/zh/exRight/TWT49U",
    "https://www.tpex.org.tw/openapi/v1/tpex_exright_daily",
    "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ",
)
QUOTED_TYPES = ("stock", "ipo", "etf")
COMMON_TYPES = ("stock", "ipo")
ROW_DROP = 0.03
ROW_DROP_SESSIONS = 5
# --quick: one instrument in QUICK_MODULUS by the hash of exchange:symbol, plus these.
QUICK_MODULUS = 20
QUICK_FIXED = {
    ("TWSE", "2330"),
    ("TWSE", "2317"),
    ("TPEx", "4549"),
    ("TPEx", "6590"),
    ("TPEx", "3691"),
    ("TWSE", "7710"),
    ("TPEx", "6938"),
    ("TWSE", "TAIEX"),
}
HOT_GROUP_WEIGHTS = {
    "relative_return": 0.35,
    "breadth": 0.25,
    "volume_strength": 0.15,
    "institutional_flow": 0.15,
    "catalyst": 0.10,
}
HOT_GROUP_MINIMUM_WEIGHT = 0.90
# Versions whose four components and score are recomputed.  1.2.0 changed only
# the catalyst (dated MOPS coverage, #453); 1.3.0 only its formula (#474).
AUDITED_HOT_GROUP_VERSIONS = frozenset({"1.1.0", "1.2.0", "1.3.0"})
# Versions whose catalyst follows the dated coverage and is recomputed from the
# events of its window (docs/spec/hot_group.md).
COVERAGE_HOT_GROUP_VERSIONS = frozenset({"1.2.0", "1.3.0"})
# Coverage versions written before the 20-session rule (#474): 1.2.0 called any
# answered window complete, a TAIEX history shorter than 20 sessions too (#501).
SHORT_WINDOW_HOT_GROUP_VERSIONS = frozenset({"1.2.0"})
CATALYST_WINDOW_SESSIONS = 20
CATALYST_SOURCES = (
    "mops_material_information",
    "twse_tpex_official_announcement",
    "issuer_filing",
)
CATALYST_WEIGHTS = {1: 0.50, 5: 0.30, 20: 0.20}
WINDOW_WEIGHTS = {1: 0.20, 5: 0.30, 20: 0.50}


def quick_sample(exchange: str, symbol: str) -> bool:
    if (exchange, symbol) in QUICK_FIXED:
        return True
    digest = hashlib.sha256(f"{exchange}:{symbol}".encode()).hexdigest()
    return int(digest, 16) % QUICK_MODULUS == 0


@dataclass
class Context:
    con: sqlite3.Connection
    raw: RawFiles
    quick: bool = False
    instruments: dict[int, tuple] = field(default_factory=dict)
    by_code: dict[tuple[str, str], int] = field(default_factory=dict)
    raw_payloads: list[tuple] = field(default_factory=list)
    first_day: str | None = None
    last_day: str | None = None
    # TAIEX index bar dates, read once by liquidity_lots.
    taiex_days: list[str] | None = None
    # hot_group catalyst windows (20 TAIEX sessions) by score date (#474).
    catalyst_windows: dict[str, list[str]] = field(default_factory=dict)

    def load(self) -> None:
        self.instruments = {
            row[0]: row
            for row in self.con.execute(
                "select id, exchange, symbol, instrument_type, status, listing_date from instruments"
            )
        }
        self.by_code = {(row[1], row[2]): row[0] for row in self.instruments.values()}
        self.raw_payloads = self.con.execute(
            "select id, endpoint, data_as_of, collected_at, payload_path from raw_payloads order by collected_at, id"
        ).fetchall()
        self.first_day, self.last_day = self.con.execute(
            "select min(trading_date), max(trading_date) from market_bars"
        ).fetchone()

    def first_captures(self) -> set[int]:
        """The earliest capture of each (chip endpoint, day): a row citing another was revised."""

        first: dict[tuple[str, str], int] = {}
        wanted = set(INSTITUTIONAL_ENDPOINTS.values()) | set(MARGIN_ENDPOINTS.values())
        for row in self.raw_payloads:
            endpoint = (row[1] or "").split("?", 1)[0]
            if endpoint in wanted:
                first.setdefault((endpoint, (row[2] or "")[:10]), row[0])
        return set(first.values())

    def captures(self, endpoint: str) -> dict[str, list[tuple]]:
        """data_as_of -> captures of ``endpoint`` (no query string), oldest first."""

        found: dict[str, list[tuple]] = defaultdict(list)
        for row in self.raw_payloads:
            if (row[1] or "").split("?", 1)[0] == endpoint:
                found[(row[2] or "")[:10]].append(row)
        return found


def _sql_count(con, sql: str, *args) -> int:
    return con.execute(sql, args).fetchone()[0]


# --- 1. 日行情合理性 --------------------------------------------------------------

BAR_RULES = {
    "high_below_low": "high < low",
    "close_outside_range": "close > high + 1e-9 or close < low - 1e-9",
    "open_outside_range": "open > high + 1e-9 or open < low - 1e-9",
    "price_not_positive": "open <= 0 or high <= 0 or low <= 0 or close <= 0",
    "volume_negative": "volume < 0 or turnover < 0",
    "suspended_with_volume": "is_suspended = 1 and volume > 0",
    "weekend_date": "strftime('%w', trading_date) in ('0', '6')",
}


def bars_integrity(ctx: Context) -> Check:
    check = Check("bars_integrity", "日行情合理性", scope="market_bars 全部列")
    total = _sql_count(ctx.con, "select count(*) from market_bars")
    latest_capture = (
        _sql_count(ctx.con, "select max(substr(collected_at, 1, 10)) from raw_payloads")
        if total
        else None
    )
    rules = dict(BAR_RULES)
    if latest_capture:
        rules["date_after_latest_capture"] = f"trading_date > '{latest_capture}'"
    bad = 0
    for category, condition in rules.items():
        rows = ctx.con.execute(
            "select i.exchange, i.symbol, b.trading_date, b.open, b.high, b.low, b.close, b.volume, b.is_suspended"
            f" from market_bars b join instruments i on i.id=b.instrument_id where {condition}"
            " order by b.trading_date, i.exchange, i.symbol"
        ).fetchall()
        for row in rows:
            check.fail(category, list(row))
        bad += len(rows)
    check.ok(max(0, total - bad))
    duplicates = _sql_count(
        ctx.con,
        "select count(*) from (select 1 from market_bars group by instrument_id, trading_date having count(*) > 1)",
    )
    if duplicates:
        check.fail("duplicate_instrument_date", {"count": duplicates})
    return check


# --- 2. 日行情完整性 --------------------------------------------------------------


def bars_coverage(ctx: Context) -> Check:
    check = Check(
        "bars_coverage",
        "日行情完整性（列數與交易所日期）",
        scope=f"普通股每日列數比前 {ROW_DROP_SESSIONS} 個交易日中位數少 {ROW_DROP:.0%} 以上即失敗",
    )
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    for day, exchange, n in ctx.con.execute(
        "select b.trading_date, i.exchange, count(*) from market_bars b join instruments i on i.id=b.instrument_id"
        " where i.instrument_type in ('stock','ipo') and b.source in ('twse','tpex') group by 1, 2 order by 1"
    ):
        counts[day][exchange] = n
    days = sorted(counts)
    for exchange in ("TWSE", "TPEx"):
        history: list[int] = []
        for day in days:
            n = counts[day].get(exchange, 0)
            if n == 0:
                check.fail(
                    "exchange_missing_on_a_trading_date",
                    {"date": day, "exchange": exchange, "other": counts[day]},
                )
                continue
            if len(history) >= ROW_DROP_SESSIONS:
                median = statistics.median(history[-ROW_DROP_SESSIONS:])
                if n < median * (1 - ROW_DROP):
                    check.fail(
                        "row_count_drop",
                        {
                            "date": day,
                            "exchange": exchange,
                            "rows": n,
                            "median_of_previous": median,
                        },
                    )
                else:
                    check.ok()
            else:
                check.ok()
            history.append(n)
    holidays: dict[str, str] = {}
    if "trading_calendar_days" in tables(ctx.con):
        holidays = {
            d: k
            for d, k in ctx.con.execute(
                "select calendar_date, kind from trading_calendar_days where exchange in ('TWSE','ALL') or 1"
            )
        }
    gaps = Counter()
    gap_days: list[str] = []
    if days:
        day, end = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        present = set(days)
        while day <= end:
            iso = day.isoformat()
            if day.weekday() < 5 and iso not in present:
                kind = holidays.get(iso, "not_in_holiday_table")
                gaps[kind] += 1
                if kind == "not_in_holiday_table":
                    gap_days.append(iso)
            day += timedelta(days=1)
    check.notes.append(
        f"休市表 {len(holidays)} 列；沒有日線的週間日：{dict(gaps)}；不在休市表的：{', '.join(gap_days) or '無'}（颱風等臨時休市不在休市表，只列出、不判定）"
    )
    return check


# --- 3. raw 對照：日行情 -----------------------------------------------------------


def bars_raw(ctx: Context) -> list[Check]:
    values = Check(
        "bars_raw_values",
        "raw 對照：日線值",
        scope="每根日線對它引用的 raw（MI_INDEX／dailyQuotes）",
    )
    missing = Check(
        "bars_raw_missing",
        "raw 有行情、active 標的沒有日線",
        issues="A4、#388",
        scope="raw 每份 capture 有成交價、代號是 active 的 stock／ipo／etf",
    )
    inactive = Check(
        "bars_raw_missing_inactive",
        "raw 有行情、非 active 標的沒有日線",
        issues="#393",
        scope="同上，標的狀態不是 active",
    )
    unknown_codes = Counter()
    captures = {
        exchange: ctx.captures(endpoint)
        for exchange, endpoint in QUOTE_ENDPOINTS.items()
    }
    days = sorted(set(captures["TWSE"]) | set(captures["TPEx"]))
    for day in days:
        bars = ctx.con.execute(
            "select i.exchange, i.symbol, i.instrument_type, b.open, b.high, b.low, b.close, b.volume, b.turnover, b.raw_payload_id, b.is_suspended, b.source"
            " from market_bars b join instruments i on i.id=b.instrument_id where b.trading_date=?",
            (day,),
        ).fetchall()
        stored: dict[str, dict[str, tuple]] = defaultdict(dict)
        for row in bars:
            stored[row[0]][row[1]] = row
        for exchange in ("TWSE", "TPEx"):
            parsed: dict[int, Any] = {}
            readable_any = False
            for capture in captures[exchange].get(day, []):
                payload = ctx.raw.load(capture[4])
                if payload is None:
                    parsed[capture[0]] = None
                    continue
                rows = quote_rows(payload, exchange)
                parsed[capture[0]] = (
                    rows,
                    taiex_close(payload) if exchange == "TWSE" else None,
                )
                readable_any = True
            if not captures[exchange].get(day):
                continue
            for symbol, row in stored[exchange].items():
                raw_id, suspended = row[9], row[10]
                if raw_id not in parsed:
                    continue  # cites another endpoint (the TWSE openapi index rows)
                capture = parsed[raw_id]
                if capture is None:
                    values.undetermined(
                        "raw_unreadable", [exchange, symbol, day, raw_id]
                    )
                    continue
                rows, taiex = capture
                if row[2] == "index":
                    if symbol == "TAIEX" and taiex is not None:
                        (
                            values.ok()
                            if close_enough(row[6], taiex, 1e-9)
                            else values.fail(
                                "index_close", [exchange, symbol, day, row[6], taiex]
                            )
                        )
                    continue
                quote = rows.get(symbol)
                if quote is None:
                    values.fail("not_in_cited_capture", [exchange, symbol, day, raw_id])
                    continue
                if suspended:
                    (
                        values.ok()
                        if quote["close"] is None
                        else values.fail(
                            "suspended_but_raw_has_price",
                            [exchange, symbol, day, quote],
                        )
                    )
                    continue
                bad = [
                    [name, row[3 + i], quote[name]]
                    for i, name in enumerate(
                        ("open", "high", "low", "close", "volume", "turnover")
                    )
                    if not close_enough(row[3 + i], quote[name], 1e-9)
                ]
                (
                    values.fail("value", [exchange, symbol, day, bad])
                    if bad
                    else values.ok()
                )
            if not readable_any:
                missing.undetermined("raw_unreadable", [exchange, day])
                continue
            seen: dict[str, dict] = {}
            for capture in parsed.values():
                if capture:
                    for symbol, quote in capture[0].items():
                        if quote["close"] is not None:
                            seen.setdefault(symbol, quote)
            for symbol, quote in sorted(seen.items()):
                if symbol in stored[exchange]:
                    missing.ok()
                    continue
                instrument_id = ctx.by_code.get((exchange, symbol))
                if instrument_id is None:
                    unknown_codes[exchange] += 1
                    continue
                instrument = ctx.instruments[instrument_id]
                if instrument[3] not in QUOTED_TYPES:
                    continue
                example = [
                    exchange,
                    symbol,
                    day,
                    instrument[3],
                    instrument[4],
                    quote["close"],
                    quote["volume"],
                ]
                (missing if instrument[4] == "active" else inactive).fail(
                    "raw_row_without_bar", example
                )
            for symbol in stored[exchange]:
                instrument_id = ctx.by_code.get((exchange, symbol))
                if instrument_id and ctx.instruments[instrument_id][4] != "active":
                    inactive.ok()
    missing.notes.append(
        f"raw 有成交、主檔沒有這個代號的列（權證等，不審）：{dict(unknown_codes)}"
    )
    return [values, missing, inactive]


# --- 4. raw 對照：籌碼 -------------------------------------------------------------


def chips_raw(ctx: Context) -> list[Check]:
    institutional = Check(
        "chips_raw_institutional",
        "raw 對照：三大法人（當日最晚 capture）",
        issues="A3、#387",
        scope="每列法人值對該日該市場最晚一份 T86／dailyTrade",
    )
    margin = Check(
        "chips_raw_margin",
        "raw 對照：融資餘額與增減",
        scope="每列融資對該日任一份 MI_MARGN／margin balance",
    )
    inst_captures = {
        exchange: ctx.captures(endpoint)
        for exchange, endpoint in INSTITUTIONAL_ENDPOINTS.items()
    }
    margin_captures = {
        exchange: ctx.captures(endpoint)
        for exchange, endpoint in MARGIN_ENDPOINTS.items()
    }
    days = sorted(
        set().union(
            *(set(c) for c in inst_captures.values()),
            *(set(c) for c in margin_captures.values()),
        )
    )
    for day in days:
        rows = ctx.con.execute(
            "select i.exchange, i.symbol, i.status, c.foreign_buy, c.trust_buy, c.dealer_buy, c.margin_balance, c.margin_change,"
            " exists(select 1 from market_bars b where b.instrument_id=c.instrument_id and b.trading_date=c.trading_date)"
            " from chip_snapshots c join instruments i on i.id=c.instrument_id where c.trading_date=?",
            (day,),
        ).fetchall()
        stored: dict[str, dict[str, tuple]] = defaultdict(dict)
        for row in rows:
            stored[row[0]][row[1]] = row
        for exchange in ("TWSE", "TPEx"):
            listed = inst_captures[exchange].get(day, [])
            if listed:
                latest = listed[-1]
                payload = ctx.raw.load(latest[4])
                parsed = (
                    None if payload is None else institutional_rows(payload, exchange)
                )
                if parsed is None:
                    institutional.undetermined(
                        "raw_unreadable", [exchange, day, latest[0]]
                    )
                else:
                    for symbol, row in sorted(stored[exchange].items()):
                        db_values = row[3:6]
                        official = parsed.get(symbol)
                        if all(v is None for v in db_values):
                            if (
                                official is not None
                                and row[2] == "active"
                                and row[8]
                                and all(v is not None for v in official)
                            ):
                                institutional.fail(
                                    "institutional_missing",
                                    [exchange, symbol, day, list(official)],
                                )
                            continue
                        if official is None:
                            institutional.fail(
                                "not_in_latest_capture",
                                [exchange, symbol, day, list(db_values), latest[0]],
                            )
                            continue
                        bad = [
                            n
                            for n, a, b in zip(
                                ("foreign", "trust", "dealer"), db_values, official
                            )
                            if not close_enough(a, b, 1e-9)
                        ]
                        if bad:
                            institutional.fail(
                                "value",
                                [
                                    exchange,
                                    symbol,
                                    day,
                                    bad,
                                    list(db_values),
                                    list(official),
                                    latest[0],
                                ],
                            )
                        else:
                            institutional.ok()
            listed = margin_captures[exchange].get(day, [])
            if listed:
                parsed_all = []
                for capture in listed:
                    payload = ctx.raw.load(capture[4])
                    rows_m = None if payload is None else margin_rows(payload, exchange)
                    if rows_m is not None:
                        parsed_all.append(rows_m)
                    elif payload is None:
                        margin.undetermined(
                            "raw_unreadable", [exchange, day, capture[0]]
                        )
                if not parsed_all:
                    continue
                for symbol, row in sorted(stored[exchange].items()):
                    balance, change = row[6], row[7]
                    offered = [p[symbol] for p in parsed_all if symbol in p]
                    if balance is None and change is None:
                        if (
                            offered
                            and offered[-1][1] is not None
                            and row[2] == "active"
                            and row[8]
                        ):
                            margin.fail(
                                "margin_missing",
                                [exchange, symbol, day, list(offered[-1])],
                            )
                        continue
                    if not offered:
                        margin.fail(
                            "not_in_any_capture",
                            [exchange, symbol, day, balance, change],
                        )
                        continue

                    def same(item):
                        previous, current = item
                        expected_change = (
                            None
                            if previous is None or current is None
                            else current - previous
                        )
                        return close_enough(balance, current, 1e-9) and close_enough(
                            change, expected_change, 1e-9
                        )

                    (
                        margin.ok()
                        if any(same(item) for item in offered)
                        else margin.fail(
                            "value",
                            [
                                exchange,
                                symbol,
                                day,
                                [balance, change],
                                list(offered[-1]),
                            ],
                        )
                    )
    return [institutional, margin]


# --- 5. 除權息欄位 ---------------------------------------------------------------


def actions_fields(ctx: Context) -> Check:
    check = Check(
        "actions_fields",
        "除權息欄位對官方價格與配股數",
        issues="A1、#386",
        scope="corporate_actions 全部列：欄位推出的參考價對減除股利參考價（差 ≤ 0.02 元）、上櫃配股率對每仟股配股",
    )
    rows = ctx.con.execute(
        "select i.exchange, i.symbol, c.action_date, c.action_type, c.cash_dividend, c.stock_dividend_ratio, c.split_ratio, c.reference_price, c.details_json"
        " from corporate_actions c join instruments i on i.id=c.instrument_id order by c.action_date, i.exchange, i.symbol"
    ).fetchall()
    for exchange, symbol, day, kind, cash, ratio, split, reference, details in rows:
        try:
            parsed = json.loads(details) if details else {}
        except ValueError:
            parsed = {}
        action = Action(
            day,
            cash,
            ratio,
            split,
            reference,
            parsed if isinstance(parsed, dict) else {},
        )
        key = [exchange, symbol, day, kind]
        problems = []
        thousand = num(action.details.get("StockDivdendThousandShares"))
        if thousand is not None:
            expected = thousand / 1000
            if ratio is None and expected > 0:
                check.undetermined("fields_left_empty", key + [expected])
                continue
            if not close_enough(ratio or 0.0, expected):
                problems.append(("stock_ratio_vs_thousand_shares", [ratio, expected]))
        prices = official_prices(action.details, DIVIDEND_DEDUCTED_PRICES)
        if prices is not None:
            before, deducted = prices
            if cash is None and ratio is None and split is None:
                check.undetermined("fields_left_empty", key)
                continue
            implied = field_factor(action, before) * before
            if round(abs(implied - deducted), 6) > REFERENCE_TOLERANCE:
                problems.append(
                    ("implied_reference", [round(implied, 4), deducted, before])
                )
        elif "Exdividend" in action.details and "CashDividend" in action.details:
            # TWT48U (no official prices): the fields against the announcement.
            raw_cash, raw_ratio = (
                num(action.details.get("CashDividend")),
                num(action.details.get("StockDividendRatio")),
            )
            if not close_enough(cash or 0.0, raw_cash or 0.0) or not close_enough(
                ratio or 0.0, raw_ratio or 0.0
            ):
                problems.append(
                    ("fields_vs_announcement", [[cash, ratio], [raw_cash, raw_ratio]])
                )
        if problems:
            for category, detail in problems:
                check.fail(category, key + [detail])
        else:
            check.ok()
    return check


# --- 6. raw 有除權息、DB 沒有 -----------------------------------------------------


def actions_missing(ctx: Context) -> Check:
    check = Check(
        "actions_missing",
        "raw 有除權息事件、corporate_actions 沒有",
        issues="A2、#386",
        scope="TWT48U／TWT49U／tpex_exright_daily／exDailyQ 的事件，標的為 stock／ipo／etf、除權息日在該標的日線範圍內；只有 TWT48U 預告、而 TWT49U 結果表涵蓋該日卻沒有的事件記「預告未執行」，不算缺漏",
    )
    stored = set(
        ctx.con.execute("select instrument_id, action_date from corporate_actions")
    )
    spans = {
        iid: (a, b)
        for iid, a, b in ctx.con.execute(
            "select instrument_id, min(trading_date), max(trading_date) from market_bars group by 1"
        )
    }
    events: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    covered: list[tuple[str, str]] = []  # TWT49U result-table ranges that were read
    for row in ctx.raw_payloads:
        endpoint = (row[1] or "").split("?", 1)[0]
        if endpoint not in ACTION_ENDPOINTS:
            continue
        payload = ctx.raw.load(row[4])
        if payload is None:
            check.undetermined("raw_unreadable", [endpoint, row[2], row[0]])
            continue
        source = endpoint.rsplit("/", 1)[-1]
        found = action_rows(payload, endpoint)
        if found is None:
            if (
                isinstance(payload, dict)
                and not payload.get("data")
                and not payload.get("tables")
            ):
                found = []  # an official "no data" answer
            else:
                check.undetermined("raw_unparsable", [endpoint, row[2], row[0]])
                continue
        if source == "TWT49U" and row[2]:
            first, _, last = row[2].partition("~")
            covered.append((first[:10], (last or first)[:10]))
        for event in found:
            events[event].add(source)
    not_executed = []
    for (exchange, symbol, day), sources in sorted(
        events.items(), key=lambda item: (item[0][2], item[0][0], item[0][1])
    ):
        instrument_id = ctx.by_code.get((exchange, symbol))
        if (
            instrument_id is None
            or ctx.instruments[instrument_id][3] not in QUOTED_TYPES
        ):
            continue
        span = spans.get(instrument_id)
        if span is None or not (span[0] < day <= span[1]):
            continue
        if (instrument_id, day) in stored:
            check.ok()
        elif sources == {"TWT48U_ALL"} and any(a <= day <= b for a, b in covered):
            not_executed.append(f"{exchange}:{symbol} {day}")
            check.ok()
        else:
            check.fail(
                "event_not_stored",
                [
                    exchange,
                    symbol,
                    day,
                    ctx.instruments[instrument_id][3],
                    sorted(sources),
                ],
            )
    check.notes.append(
        f"TWT48U 預告、TWT49U 結果表涵蓋該日卻沒有（預告未執行，不算缺漏）：{len(not_executed)} 筆 {', '.join(not_executed[:20])}"
    )
    return check


# --- 7. 來源與日期欄位 ------------------------------------------------------------


def provenance(ctx: Context) -> Check:
    check = Check(
        "provenance",
        "來源與日期欄位",
        scope="market_bars、chip_snapshots、corporate_actions、technical_indicators",
    )
    rules: list[tuple[str, str]] = []
    for table in ("market_bars", "chip_snapshots"):
        rules += [
            (
                f"{table}:source_missing",
                f"select count(*) from {table} where source is null or source in ('', 'unknown')",
            ),
            (
                f"{table}:data_as_of_missing",
                f"select count(*) from {table} where data_as_of is null",
            ),
            (
                f"{table}:data_as_of_not_trading_date",
                f"select count(*) from {table} where substr(data_as_of, 1, 10) != trading_date",
            ),
            (
                f"{table}:collected_at_missing",
                f"select count(*) from {table} where collected_at is null",
            ),
            (
                f"{table}:raw_payload_missing",
                f"select count(*) from {table} where raw_payload_id is null",
            ),
            (
                f"{table}:raw_payload_not_found",
                f"select count(*) from {table} x left join raw_payloads r on r.id=x.raw_payload_id where x.raw_payload_id is not null and r.id is null",
            ),
            (
                f"{table}:raw_date_not_trading_date",
                f"select count(*) from {table} x join raw_payloads r on r.id=x.raw_payload_id where substr(r.data_as_of, 1, 10) != x.trading_date",
            ),
            (
                f"{table}:collected_before_raw",
                f"select count(*) from {table} x join raw_payloads r on r.id=x.raw_payload_id where x.collected_at < r.collected_at",
            ),
        ]
    chip_cols = columns(ctx.con, "chip_snapshots")
    if "institutional_raw_payload_id" in chip_cols:
        rules += [
            (
                "chip_snapshots:institutional_group_missing",
                "select count(*) from chip_snapshots where foreign_buy is not null and (institutional_source is null or institutional_raw_payload_id is null or institutional_data_as_of is null or institutional_collected_at is null)",
            ),
            (
                "chip_snapshots:margin_group_missing",
                "select count(*) from chip_snapshots where margin_balance is not null and (margin_source is null or margin_raw_payload_id is null or margin_data_as_of is null or margin_collected_at is null)",
            ),
        ]
    rules += [
        (
            "corporate_actions:raw_or_dates_missing",
            "select count(*) from corporate_actions where raw_payload_id is null or data_as_of is null or collected_at is null",
        ),
        (
            "corporate_actions:raw_payload_not_found",
            "select count(*) from corporate_actions x left join raw_payloads r on r.id=x.raw_payload_id where x.raw_payload_id is not null and r.id is null",
        ),
        (
            "technical_indicators:computed_before_bar",
            "select count(*) from technical_indicators t join market_bars b on b.instrument_id=t.instrument_id and b.trading_date=t.trading_date where t.computed_at < b.collected_at",
        ),
        (
            "technical_indicators:source_missing",
            "select count(*) from technical_indicators where source is null or source = ''",
        ),
    ]
    for category, sql in rules:
        n = _sql_count(ctx.con, sql)
        if n:
            check.fail(category, {"rows": n})
        else:
            check.ok()
    return check


# --- 8.～11. 由日線重算的項目 -----------------------------------------------------


@dataclass
class Derived:
    """What the instrument loop collects for the cross-sectional items."""

    candidate_days: set[str] = field(default_factory=set)
    group_needs: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    pool_needs: dict[int, set[tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(set)
    )
    chips_by_day: dict[str, dict[int, dict[str, float | None]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    technical: dict[tuple[int, str, str], dict[str, float | None]] = field(
        default_factory=dict
    )
    members: dict[tuple[int, str], dict[str, Any]] = field(default_factory=dict)
    benchmark: dict[str, dict[int, float | None]] = field(default_factory=dict)
    evidence: dict[tuple[str, str], int] = field(default_factory=dict)
    run_times: dict[str, str] = field(default_factory=dict)
    changed: dict[tuple[int, str], bool] = field(default_factory=dict)
    changed_prices: dict[tuple[int, str], bool] = field(default_factory=dict)
    # (run id, instrument id) -> recomputed 20-session lots (runs with a floor).
    liquidity: dict[tuple[int, int], float | None] = field(default_factory=dict)


def breakout_strategy(name: str) -> bool:
    return name.startswith("breakout")


def liquidity_lots(
    ctx: Context, instrument_id: int, day: str, window: int, shares_per_lot: int
) -> float | None:
    """candidate_score.md candidate_score_v6: 20-session average volume in lots.

    Sessions are the TAIEX index bar dates; a suspended bar is skipped, a
    session without a bar is 0 lots with an official no-trade row and missing
    otherwise; missing data, a date that is not a session or fewer sessions
    than the window (since listing) give None.
    """

    if ctx.taiex_days is None:
        ctx.taiex_days = [
            row[0]
            for row in ctx.con.execute(
                "select distinct b.trading_date from market_bars b join instruments i on i.id=b.instrument_id"
                " where i.instrument_type='index' and i.exchange='TWSE' and i.symbol in ('TAIEX','TWII')"
                " order by b.trading_date"
            )
        ]
    sessions = [d for d in ctx.taiex_days if d <= day]
    if not sessions or sessions[-1] != day:
        return None
    start = sessions[-min(len(sessions), 120)]
    bars = {
        row[0]: (row[1], row[2])
        for row in ctx.con.execute(
            "select trading_date, volume, is_suspended from market_bars where instrument_id=? and trading_date between ? and ?",
            (instrument_id, start, day),
        )
    }
    no_trade = {
        row[0]
        for row in ctx.con.execute(
            "select trading_date from no_trade_days where instrument_id=? and trading_date between ? and ?",
            (instrument_id, start, day),
        )
    }
    listing = (ctx.instruments.get(instrument_id) or (None,) * 6)[5]
    total, counted = 0.0, 0
    for session in reversed(sessions[-120:]):
        if counted == window:
            break
        if listing and session < str(listing)[:10]:
            break
        volume, suspended = bars.get(session, (None, None))
        if session in bars and suspended:
            continue
        counted += 1
        if session not in bars:
            if session in no_trade:
                continue
            return None
        if not finite(volume) or volume < 0:
            return None
        total += volume
    if counted < window:
        return None
    return total / window / shares_per_lot


def derived_checks(ctx: Context, stop: Callable[[], str | None]) -> list[Check]:
    """Indicators, chip ratios of the signals, candidate and group scores, in one pass over the instruments."""

    ind = Check(
        "indicators",
        "技術指標全標的全歷史重算",
        issues="A1、#386、#394",
        scope=f"{INDICATOR_VERSION}，價格基準 {PRICE_BASIS}（docs/spec/indicators.md）",
    )
    ratios = Check(
        "chips_ratios",
        "訊號的法人 5 日比率與融資 5 日變動比",
        scope="analysis 訊號 rule_evidence_json.inputs 重算",
    )
    cands = Check(
        "candidates",
        "候選分數重算",
        scope="每個 candidate run：流動性門檻（v6 起，20 日均量張數與入池）、籌碼分項值與全市場 percentile、技術分項值與同策略池 percentile、族群分項、分項分數、總分、名次",
    )
    groups = Check(
        "groups",
        "族群分數重算",
        scope="每列 group_daily_scores：成員超額報酬、量能、法人，群組相對報酬、廣度、催化劑（1.2.0 起依覆蓋與事件重算）、同榜 percentile、分數與名次",
    )
    if ctx.quick:
        ind.scope += (
            f"；--quick：exchange:symbol 雜湊 mod {QUICK_MODULUS} 為 0 的標的加固定清單"
        )
        ratios.scope += "；--quick 同上"

    derived = Derived()
    runs = ctx.con.execute(
        "select id, trading_date, score_version, config_json, pool_count, computed_at from candidate_runs order by trading_date, score_version"
    ).fetchall()
    derived.candidate_days = {row[1] for row in runs}
    for row in runs:
        derived.run_times[row[1]] = min(row[5], derived.run_times.get(row[1], row[5]))
    pools: dict[int, list[tuple]] = {}
    for run_id, day, version, config, _pool, _computed in runs:
        try:
            pool_config = json.loads(config).get("pool", {})
        except (ValueError, AttributeError):
            pool_config = {}
        strategies = pool_config.get("strategies") or []
        legacy = set(pool_config.get("legacy_actionable_statuses") or [])
        types = set(pool_config.get("instrument_types") or COMMON_TYPES)
        namespace = pool_config.get("signal_namespace", "analysis")
        entries = []
        if strategies:
            marks = ",".join("?" * len(strategies))
            for (
                instrument_id,
                name,
                status,
                entry_type,
                ref,
                brk,
                invalid,
                t1,
                t2,
                evidence,
            ) in ctx.con.execute(
                "select s.instrument_id, sv.name, s.status, s.entry_type, s.reference_entry, s.breakout_price, s.invalid_price, s.target_1, s.target_2, s.rule_evidence_json"
                f" from signals s join strategy_versions sv on sv.id=s.strategy_version_id where s.signal_date=? and s.signal_key like ? and sv.name in ({marks}) and sv.active=1",
                (day, f"{namespace}-%", *strategies),
            ):
                try:
                    flag = json.loads(evidence or "{}").get("actionable")
                except (ValueError, AttributeError):
                    flag = None
                if not (flag is True if flag is not None else status in legacy):
                    continue
                instrument = ctx.instruments.get(instrument_id)
                if (
                    instrument is None
                    or instrument[3] not in types
                    or instrument[4] != "active"
                ):
                    continue
                if entry_type != (
                    "breakout" if breakout_strategy(name) else "pullback"
                ):
                    continue
                entry = brk if entry_type == "breakout" else ref
                if not (
                    positive(entry)
                    and positive(invalid)
                    and positive(t1)
                    and invalid < entry < t1
                ):
                    continue
                if t2 is not None and not (positive(t2) and t2 > t1):
                    continue
                if (t1 - entry) / (entry - invalid) < 1.5:
                    continue
                floor = pool_config.get("liquidity")
                if isinstance(floor, dict):
                    lots = liquidity_lots(
                        ctx,
                        instrument_id,
                        day,
                        int(floor.get("window_sessions", 20)),
                        int(floor.get("shares_per_lot", 1000)),
                    )
                    derived.liquidity[(run_id, instrument_id)] = lots
                    if lots is None or lots < float(floor["minimum_lots"]):
                        continue
                entries.append((instrument_id, name))
                derived.pool_needs[instrument_id].add((day, name))
        pools[run_id] = entries

    group_rows = []
    for gid, day, details, *stored in ctx.con.execute(
        "select group_id, trading_date, details_json, relative_return_1d, relative_return_5d, relative_return_20d, breadth, volume_strength, institutional_flow, catalyst, score, rank, eligible_members, data_quality"
        " from group_daily_scores order by trading_date, group_id"
    ):
        try:
            parsed = json.loads(details)
        except ValueError:
            parsed = {}
        group_rows.append((gid, day, parsed, stored))
        for member in parsed.get("member_returns") or []:
            if isinstance(member, dict) and member.get("instrument_id") is not None:
                derived.group_needs[member["instrument_id"]].add(day)

    derived.evidence = evidence_lookup(ctx.con)
    chip_cols = columns(ctx.con, "chip_snapshots")
    first_captures = ctx.first_captures()
    order = sorted(ctx.instruments.values(), key=lambda row: (row[1], row[2]))
    has_bars = {
        row[0]
        for row in ctx.con.execute("select distinct instrument_id from market_bars")
    }
    for instrument in order:
        if instrument[0] not in has_bars:
            continue
        reason = stop()
        if reason:
            for check in (ind, ratios, cands, groups):
                check.skipped = reason
            return [ind, ratios, cands, groups]
        series = load_series(ctx.con, instrument[:5], chip_cols, first_captures)
        sampled = not ctx.quick or quick_sample(series.exchange, series.symbol)
        computed = indicators(series.bars, series.factors)
        if sampled:
            _compare_indicators(ctx, series, computed, ind)
            _compare_signal_ratios(ctx, series, ratios)
        _collect(ctx, series, computed, derived)
    _check_candidates(ctx, runs, pools, derived, cands)
    _check_groups(ctx, group_rows, derived, groups)
    return [ind, ratios, cands, groups]


def _compare_indicators(ctx: Context, series: Series, computed, check: Check) -> None:
    stored = {
        row[0]: row
        for row in ctx.con.execute(
            "select trading_date, price_basis, bar_count, "
            + ", ".join(FIELDS)
            + " from technical_indicators where instrument_id=? and formula_version=?",
            (series.instrument_id, INDICATOR_VERSION),
        )
    }
    code = [series.exchange, series.symbol]
    old_basis = 0
    for bar, (count, values) in zip(series.bars, computed):
        row = stored.pop(bar.day, None)
        if row is None:
            check.fail("row_missing", code + [bar.day])
            continue
        if row[1] != PRICE_BASIS:
            old_basis += 1
        if row[2] != count:
            check.fail("bar_count", code + [bar.day, row[2], count])
        bad = []
        for i, name in enumerate(FIELDS):
            mine, theirs = values[name], row[3 + i]
            if mine is None and theirs is None:
                continue
            if mine is None or theirs is None or not close_enough(theirs, mine):
                bad.append([name, theirs, None if mine is None else round(mine, 6)])
        if bad:
            category = (
                "value"
                if all(b[1] is not None and b[2] is not None for b in bad)
                else "null_mismatch"
            )
            check.fail(category, code + [bar.day, row[1], bad[:4]])
        else:
            check.ok()
    if old_basis:
        check.fail("older_price_basis", code + [old_basis])
    for day in sorted(stored):
        check.fail("row_without_bar", code + [day])


def _compare_signal_ratios(ctx: Context, series: Series, check: Check) -> None:
    for day, key, evidence, created in ctx.con.execute(
        "select signal_date, signal_key, rule_evidence_json, created_at from signals where instrument_id=? and signal_key not like 'backtest-%' order by signal_date, id",
        (series.instrument_id,),
    ):
        try:
            inputs = json.loads(evidence or "{}").get("inputs") or {}
        except (ValueError, AttributeError):
            continue
        code = [series.exchange, series.symbol, day, key]
        if (
            "strategy_institutional_flow_to_average_volume_ratio_5d" in inputs
            or "institutional_flow_to_turnover_ratio_5d" in inputs
        ):
            version = inputs.get("institutional_flow_formula_version")
            if version != "institutional-flow/v2-shares-per-share-volume":
                check.undetermined("older_flow_formula", code + [version])
            else:
                stored = inputs.get(
                    "strategy_institutional_flow_to_average_volume_ratio_5d",
                    inputs.get("institutional_flow_to_turnover_ratio_5d"),
                )
                flow = series.flow(day, 5)
                mine = None if flow is None else flow[0] / (flow[1] / 20)
                _judge(
                    check,
                    "institutional_flow_5d",
                    stored,
                    mine,
                    code,
                    series.changed(day, 20, created, chip_window=5),
                    1e-9,
                )
        if "margin_balance_change_ratio_5d" in inputs:
            stored = inputs["margin_balance_change_ratio_5d"]
            mine = series.margin_change(day)
            _judge(
                check,
                "margin_change_5d",
                stored,
                mine,
                code,
                series.changed(day, 6, created),
                1e-9,
            )


CHANGED = "inputs_changed_after_write"


def _judge(
    check: Check,
    category: str,
    stored,
    mine,
    code: list,
    changed: bool,
    tolerance: float = 1e-9,
) -> bool:
    """Pass, fail, or undetermined when the inputs changed after the row was written."""

    if close_enough(stored, mine, tolerance):
        check.ok()
        return True
    if changed:
        check.undetermined(CHANGED, code + [category, stored, mine])
    else:
        check.fail(category, code + [stored, mine])
    return False


def _collect(ctx: Context, series: Series, computed, derived: Derived) -> None:
    common = series.instrument_type in COMMON_TYPES and series.status == "active"
    if series.instrument_type == "index" and series.symbol == "TAIEX":
        for day in (
            set().union(*derived.group_needs.values()) if derived.group_needs else set()
        ):
            derived.benchmark[day] = {
                w: series.price_return(day, w) for w in (1, 5, 20)
            }
    for day in derived.candidate_days:
        if not common:
            continue
        five = series.flow(day, 5, require_last=True)
        twenty = series.flow(day, 20, require_last=True)
        when = derived.run_times.get(day)
        derived.changed[(series.instrument_id, day)] = series.changed(day, 20, when)
        derived.changed_prices[(series.instrument_id, day)] = series.changed(
            day, 21, when, prices=True
        )
        derived.chips_by_day[day][series.instrument_id] = {
            "institutional_flow_5d": None if five is None else five[0] / (five[1] / 20),
            "institutional_flow_20d": None
            if twenty is None
            else twenty[0] / (twenty[1] / 20),
            "margin_change_5d": series.margin_change(day, require_last=True),
        }
    for day, strategy in derived.pool_needs.get(series.instrument_id, ()):
        i = series.index.get(day)
        if i is None:
            continue
        bar = series.bars[i]
        prior = series.prior_20(day)
        volume_ratio = distance = None
        if len(prior) == 20:
            average = sum(series.bars[j].volume for j in prior) / 20
            volume_ratio = bar.volume / average if average > 0 else None
            if breakout_strategy(strategy):
                highest = max(
                    round(
                        series.bars[j].high * series.factors[i] / series.factors[j], 6
                    )
                    for j in prior
                )
                distance = bar.close / highest - 1 if highest > 0 else None
        if not breakout_strategy(strategy):
            ma20 = computed[i][1]["ma20"]
            distance = abs(bar.close / ma20 - 1) if ma20 else None
        derived.technical[(series.instrument_id, day, strategy)] = {
            "volume_ratio": volume_ratio,
            "distance": distance,
        }
    for day in derived.group_needs.get(series.instrument_id, ()):
        i = series.index.get(day)
        if i is None:
            derived.members[(series.instrument_id, day)] = {"missing_bar": True}
            continue
        prior = series.prior_20(day)
        last_five = [series.bars[j].volume for j in range(max(0, i - 4), i + 1)]
        average = sum(series.bars[j].volume for j in prior) / len(prior) if prior else 0
        volume_raw = None
        if prior and average > 0 and len(last_five) == 5:
            volume_raw = 0.5 * (series.bars[i].volume / average) + 0.5 * (
                (sum(last_five) / 5) / average
            )
        flow = series.flow(
            day,
            5,
            absent_evidence=lambda exchange, d: (exchange, d) in derived.evidence,
        )
        derived.members[(series.instrument_id, day)] = {
            "returns": {w: series.price_return(day, w) for w in (1, 5, 20)},
            "volume_raw": volume_raw,
            "flow": None if flow is None else flow[0] / flow[1],
            "zero_filled": [] if flow is None else flow[2],
            "margin": series.margin_change(day),
            "changed": series.changed(day, 21, prices=True),
        }


def _component(items: dict[str, Any]) -> float | None:
    usable = [
        (v.get("weight") or 0.0, v.get("percentile"))
        for v in items.values()
        if isinstance(v, dict)
        and v.get("percentile") is not None
        and (v.get("weight") or 0) > 0
    ]
    total = sum(w for w, _ in usable)
    return sum(w * p for w, p in usable) / total if total else None


def _check_candidates(
    ctx: Context, runs, pools, derived: Derived, check: Check
) -> None:
    for run_id, day, version, _config, pool_count, _computed in runs:
        rows = ctx.con.execute(
            "select d.instrument_id, i.exchange, i.symbol, d.strategy, d.total_score, d.weight_coverage, d.rank, d.components_json, d.groups_json"
            " from daily_candidates d join instruments i on i.id=d.instrument_id where d.candidate_run_id=? order by d.rank",
            (run_id,),
        ).fetchall()
        population = derived.chips_by_day.get(day, {})
        population_changed = any(derived.changed.get((iid, day)) for iid in population)
        pool = pools.get(run_id, [])
        if len(pool) != pool_count:
            check.undetermined(
                "pool_rebuilt_with_another_size", [day, version, pool_count, len(pool)]
            )
        ranked = []
        for (
            instrument_id,
            exchange,
            symbol,
            strategy,
            total,
            coverage,
            rank,
            components,
            groups_json,
        ) in rows:
            code = [day, version, exchange, symbol]
            try:
                comp = json.loads(components)
                groups_list = json.loads(groups_json)
            except ValueError:
                check.fail("unreadable_json", code)
                continue
            # chips: values and whole-market percentiles
            chips = comp.get("chips", {})
            mine = population.get(instrument_id)
            for key, better in (
                ("institutional_flow_5d", "higher"),
                ("institutional_flow_20d", "higher"),
                ("margin_change_5d", "lower"),
            ):
                item = (chips.get("items") or {}).get(key) or {}
                value = None if mine is None else mine[key]
                if not _judge(
                    check,
                    f"chips:{key}:value",
                    item.get("value"),
                    value,
                    code,
                    bool(derived.changed.get((instrument_id, day))),
                ):
                    continue
                peers = [
                    row[key] for row in population.values() if row[key] is not None
                ]
                stored_size = (chips.get("population") or {}).get(key)
                if value is None:
                    continue
                if stored_size != len(peers):
                    check.undetermined(
                        "chips_population_size", code + [key, stored_size, len(peers)]
                    )
                    continue
                _judge(
                    check,
                    f"chips:{key}:percentile",
                    item.get("percentile"),
                    mid_rank(value, peers, better),
                    code,
                    population_changed,
                )
            # liquidity floor (candidate_score_v6): the stored 20-session lots
            if (run_id, instrument_id) in derived.liquidity:
                _judge(
                    check,
                    "liquidity:average_volume_lots_20d",
                    (comp.get("liquidity") or {}).get("average_volume_lots_20d"),
                    derived.liquidity[(run_id, instrument_id)],
                    code,
                    bool(derived.changed.get((instrument_id, day))),
                    1e-3,
                )
            # technical: values and same-strategy pool percentiles
            technical = comp.get("technical", {})
            mine_t = derived.technical.get((instrument_id, day, strategy))
            peers_t = [
                derived.technical.get((iid, day, name))
                for iid, name in pool
                if name == strategy
            ]
            for key in ("volume_ratio", "distance"):
                item = (technical.get("items") or {}).get(key) or {}
                value = None if mine_t is None else mine_t[key]
                if not _judge(
                    check,
                    f"technical:{key}:value",
                    item.get("value"),
                    value,
                    code,
                    bool(derived.changed_prices.get((instrument_id, day))),
                    1e-6,
                ):
                    continue
                if value is None:
                    continue
                if technical.get("population") != len(peers_t) or any(
                    p is None for p in peers_t
                ):
                    check.undetermined(
                        "technical_pool_size",
                        code + [technical.get("population"), len(peers_t)],
                    )
                    continue
                better = item.get("better") or "higher"
                values = [p[key] for p in peers_t if p[key] is not None]
                expected = mid_rank(value, values, better)
                _judge(
                    check,
                    f"technical:{key}:percentile",
                    item.get("percentile"),
                    expected,
                    code,
                    any(derived.changed_prices.get((iid, day)) for iid, _name in pool),
                )
            # group: best qualified board percentile and the score row it cites
            qualified = [
                g for g in groups_list if isinstance(g, dict) and g.get("qualified")
            ]
            expected_group = None
            for g in qualified:
                size = g.get("board_size") or 0
                value = 0.5 if size <= 1 else 1 - (g["rank"] - 1) / (size - 1)
                expected_group = (
                    value if expected_group is None else max(expected_group, value)
                )
                score_row = ctx.con.execute(
                    "select rank, data_quality from group_daily_scores where group_id=? and trading_date=?",
                    (g.get("group_id"), day),
                ).fetchone()
                if score_row is None:
                    check.fail(
                        "group:cited_score_row_missing", code + [g.get("group_id")]
                    )
                elif score_row[0] != g.get("rank") or score_row[1] != "complete":
                    # The run keeps the group snapshot of its day; a later rescore (#409) may move the row.
                    check.undetermined(
                        "group_row_differs_from_run_snapshot",
                        code + [g.get("group_id"), g.get("rank"), list(score_row)],
                    )
                else:
                    check.ok()
            stored_group = (comp.get("group") or {}).get("score")
            (
                check.ok()
                if close_enough(stored_group, expected_group, 1e-9)
                else check.fail("group:value", code + [stored_group, expected_group])
            )
            # component scores, total and coverage from the stored sub-items
            weight_total = weighted = 0.0
            for name, component in comp.items():
                if (
                    not isinstance(component, dict)
                    or "weight" not in component
                    or "items" not in component
                ):
                    continue
                expected = _component(component["items"])
                (
                    check.ok()
                    if close_enough(component.get("score"), expected, 1e-9)
                    else check.fail(
                        f"component:{name}", code + [component.get("score"), expected]
                    )
                )
                if component.get("score") is not None:
                    weight_total += component["weight"]
                    weighted += component["weight"] * component["score"]
            expected_total = weighted / weight_total if weight_total else None
            (
                check.ok()
                if close_enough(total, expected_total, 1e-6)
                else check.fail("total", code + [total, expected_total])
            )
            (
                check.ok()
                if close_enough(coverage, weight_total, 1e-9)
                else check.fail("weight_coverage", code + [coverage, weight_total])
            )
            ranked.append(
                (
                    rank,
                    total,
                    (comp.get("technical") or {}).get("score") or 0.0,
                    (comp.get("chips") or {}).get("score") or 0.0,
                    exchange,
                    symbol,
                )
            )
        expected_order = sorted(ranked, key=lambda r: (-r[1], -r[2], -r[3], r[4], r[5]))
        if [r[0] for r in expected_order] != list(range(1, len(ranked) + 1)):
            check.fail("rank_order", [day, version, [r[0] for r in expected_order]])
        elif ranked:
            check.ok()


def _catalyst_window(ctx: Context, day: str) -> list[str]:
    """The 20 TAIEX sessions (not suspended) ending ``day``, oldest first."""

    cache = ctx.catalyst_windows
    if day not in cache:
        rows = ctx.con.execute(
            "select b.trading_date from market_bars b join instruments i on i.id = b.instrument_id"
            " where i.instrument_type = 'index' and i.symbol = 'TAIEX' and b.trading_date <= ?"
            " and (b.is_suspended = 0 or b.is_suspended is null)"
            " order by b.trading_date desc limit 20",
            (day,),
        ).fetchall()
        cache[day] = sorted(str(row[0]) for row in rows)
    return cache[day]


def _recomputed_catalyst(
    ctx: Context, version: str, window: list[str], member_ids: list[int], through_id
) -> float | None:
    """The raw catalyst of a covered window, from the events table.

    1.2.0: weighted distinct events of the eligible members over 3, capped
    at 1.  1.3.0 (#474): weighted share of eligible members with an event,
    counting only events up to the id the row recorded.
    """

    if not member_ids:
        return None
    marks = ",".join("?" * len(member_ids))
    dates = ",".join("?" * len(window))
    sources = ",".join("?" * len(CATALYST_SOURCES))
    sql = (
        f"select id, instrument_id, event_date from events where instrument_id in ({marks})"
        f" and event_date in ({dates}) and source in ({sources})"
    )
    args: list[Any] = [*member_ids, *window, *CATALYST_SOURCES]
    if version != "1.2.0":
        sql += " and id <= ?"
        args.append(through_id)
    position = {value: index + 1 for index, value in enumerate(window)}
    events = {w: set() for w in CATALYST_WEIGHTS}
    members = {w: set() for w in CATALYST_WEIGHTS}
    for event_id, instrument_id, event_date in ctx.con.execute(sql, args):
        session = position.get(str(event_date))
        for w in CATALYST_WEIGHTS:
            if session is not None and session > len(window) - w:
                events[w].add(event_id)
                members[w].add(instrument_id)
    if version == "1.2.0":
        weighted = sum(CATALYST_WEIGHTS[w] * len(events[w]) for w in CATALYST_WEIGHTS)
        return max(0.0, min(1.0, weighted / 3.0))
    eligible = len(set(member_ids))
    return sum(
        CATALYST_WEIGHTS[w] * len(members[w]) / eligible for w in CATALYST_WEIGHTS
    )


def _check_catalyst(ctx: Context, day, version, details, stored, code, check) -> None:
    """Coverage rule (1.2.0, #453; 20 sessions from 1.3.0) and the recomputed raw catalyst (#474).

    A window that differs from TAIEX now, or a 1.2.0 window under 20
    sessions, is undetermined (#501, docs/spec/hot_group.md).
    """

    coverage = details.get("catalyst_coverage")
    if not isinstance(coverage, dict):
        check.fail("catalyst_coverage_missing", code)
        return
    complete = coverage.get("complete")
    if not complete:
        # Without a fully answered window the catalyst is null.
        if stored[6] is None:
            check.ok()
        else:
            check.fail(
                "catalyst_without_coverage",
                code + [stored[6], coverage.get("unanswered_dates")],
            )
        return
    sessions = coverage.get("sessions")
    stored_window = coverage.get("window")
    if sessions != CATALYST_WINDOW_SESSIONS:
        if version in SHORT_WINDOW_HOT_GROUP_VERSIONS:
            # 1.2.0 did not require 20 sessions (#501): the row followed its
            # own rule, which the audit does not hold it to.
            check.undetermined(
                "catalyst_window_short_before_1_3_0",
                code + [version, sessions, stored_window],
            )
        else:
            # 1.3.0 (#474): a complete window has all 20 TAIEX sessions.
            check.fail("catalyst_coverage_window", code + [sessions, stored_window])
        return
    window = _catalyst_window(ctx, day)
    now = window[:1] + window[-1:]
    if len(window) != CATALYST_WINDOW_SESSIONS or stored_window != now:
        # The row stored 20 sessions; TAIEX now gives another window (a bar
        # backfilled, or is_suspended changed, after the row was written).
        # The audit keeps no TAIEX snapshot to tell that from a wrong write,
        # and the events of the stored window cannot be recounted (#501).
        check.undetermined(
            "catalyst_window_changed_after_write", code + [stored_window, now]
        )
        return
    member_ids = [
        m["instrument_id"]
        for m in details.get("member_returns") or []
        if isinstance(m, dict) and m.get("instrument_id") is not None
    ]
    if stored[9] and stored[6] is None:
        # An answered window with eligible members has a value (0 without
        # events); null there drops a component the group had.
        check.fail("catalyst_null_with_full_coverage", code)
        return
    if not member_ids:
        check.ok()
        return
    inputs = details.get("catalyst_inputs") or {}
    through_id = inputs.get("events_through_id")
    if version != "1.2.0" and through_id is None:
        check.fail("catalyst_inputs_missing", code)
        return
    mine = _recomputed_catalyst(ctx, version, window, member_ids, through_id)
    # 1.2.0 rows did not record which events they counted: an event collected
    # after the row (a later list, a backfill) makes the recount differ.
    _judge(
        check,
        "group_raw_catalyst",
        (details.get("raw_values") or {}).get("catalyst"),
        mine,
        code,
        version == "1.2.0",
    )


def _check_groups(ctx: Context, group_rows, derived: Derived, check: Check) -> None:
    active = {
        gid: bool(flag)
        for gid, flag in ctx.con.execute("select id, active from theme_groups")
    }
    by_day: dict[str, list] = defaultdict(list)
    for gid, day, details, stored in group_rows:
        by_day[day].append((gid, details, stored))
    for day, rows in sorted(by_day.items()):
        bench = derived.benchmark.get(day)
        computed = []
        for gid, details, stored in rows:
            code = [day, gid]
            version = details.get("hot_group_version")
            if version not in AUDITED_HOT_GROUP_VERSIONS:
                # hot_group 1.0.0 (turnover denominator, members by symbol) is not recomputed.
                check.undetermined("hot_group_version_not_audited", code + [version])
                continue
            if version in COVERAGE_HOT_GROUP_VERSIONS:
                _check_catalyst(ctx, day, version, details, stored, code, check)
            members = details.get("member_returns") or []
            stored_bench = details.get("benchmark_returns") or {}
            if bench is None:
                check.undetermined("benchmark_missing", code)
            else:
                for w in (1, 5, 20):
                    value = stored_bench.get(str(w), stored_bench.get(w))
                    _judge(
                        check, "benchmark_return", value, bench[w], code + [w], False
                    )
            excess = {1: [], 5: [], 20: []}
            volumes, flows = [], []
            flow_complete = True
            group_changed = False
            for member in members:
                metrics = derived.members.get((member.get("instrument_id"), day))
                mcode = code + [member.get("symbol")]
                if metrics is None or metrics.get("missing_bar") or bench is None:
                    check.undetermined("member_not_recomputed", mcode)
                    flow_complete = False
                    group_changed = True
                    continue
                changed = metrics["changed"]
                group_changed = group_changed or changed
                for w in (1, 5, 20):
                    ret = metrics["returns"][w]
                    mine = None if ret is None or bench[w] is None else ret - bench[w]
                    _judge(
                        check,
                        f"member_excess_{w}d",
                        member.get(f"excess_return_{w}d"),
                        mine,
                        mcode,
                        changed,
                    )
                    if mine is not None:
                        excess[w].append(mine)
                _judge(
                    check,
                    "member_volume_strength",
                    member.get("volume_strength_raw"),
                    metrics["volume_raw"],
                    mcode,
                    changed,
                )
                if metrics["volume_raw"] is not None:
                    volumes.append(metrics["volume_raw"])
                _judge(
                    check,
                    "member_institutional_flow",
                    member.get("hot_group_institutional_flow_to_sum_volume_ratio_5d"),
                    metrics["flow"],
                    mcode,
                    changed,
                )
                zero = [
                    d.get("trading_date")
                    for d in member.get("institutional_flow_absent_from_official_file")
                    or []
                ]
                if zero == metrics["zero_filled"]:
                    check.ok()
                elif changed:
                    check.undetermined(
                        CHANGED,
                        mcode
                        + [
                            "member_flow_zero_filled_days",
                            zero,
                            metrics["zero_filled"],
                        ],
                    )
                else:
                    check.fail(
                        "member_flow_zero_filled_days",
                        mcode + [zero, metrics["zero_filled"]],
                    )
                if metrics["flow"] is None:
                    flow_complete = False
                else:
                    flows.append(metrics["flow"])
                _judge(
                    check,
                    "member_margin_change",
                    member.get("margin_balance_change_ratio_5d"),
                    metrics["margin"],
                    mcode,
                    changed,
                )
            eligible = len(members)
            _judge(check, "eligible_members", stored[9], eligible, code, False)
            raw: dict[str, float | None] = {}
            if eligible and all(len(excess[w]) == eligible for w in (1, 5, 20)):
                rr = {w: sum(excess[w]) / eligible for w in (1, 5, 20)}
                for w, column in ((1, 0), (5, 1), (20, 2)):
                    _judge(
                        check,
                        f"group_relative_return_{w}d",
                        stored[column],
                        rr[w],
                        code,
                        group_changed,
                    )
                raw["relative_return"] = sum(
                    WINDOW_WEIGHTS[w] * rr[w] for w in (1, 5, 20)
                )
                raw["breadth"] = sum(
                    WINDOW_WEIGHTS[w] * sum(x > 0 for x in excess[w]) / eligible
                    for w in (1, 5, 20)
                )
                _judge(
                    check,
                    "group_breadth",
                    stored[3],
                    raw["breadth"],
                    code,
                    group_changed,
                )
            else:
                raw["relative_return"] = raw["breadth"] = None
            raw["volume_strength"] = (
                statistics.median(volumes)
                if volumes and len(volumes) == eligible
                else None
            )
            raw["institutional_flow"] = (
                sum(flows) / eligible
                if eligible and flow_complete and len(flows) == eligible
                else None
            )
            stored_raw = details.get("raw_values") or {}
            for key in (
                "relative_return",
                "breadth",
                "volume_strength",
                "institutional_flow",
            ):
                _judge(
                    check,
                    f"group_raw_{key}",
                    stored_raw.get(key),
                    raw[key],
                    code,
                    group_changed,
                )
            computed.append(
                (gid, details, stored, group_changed, active.get(gid, True))
            )
        _check_board(day, computed, check)


def _percentile_matches(
    value, normalized, peers_all, peers_active
) -> tuple[bool, float | None]:
    """The stored percentile against the board with, or without, its inactive groups.

    A rescore after a group was deactivated (#409) ranks the board without it,
    while the rows of days not rescored still count it.
    """

    expected = None
    for peers in (peers_all, peers_active):
        if value is None or not peers:
            candidate = None
        else:
            candidate = mid_rank(value, peers)
        expected = candidate if expected is None else expected
        if close_enough(normalized, candidate, 1e-9):
            return True, candidate
    return False, expected


def _check_board(day: str, computed, check: Check) -> None:
    boards: dict[tuple, list] = defaultdict(list)
    for item in computed:
        boards[(item[1].get("leaderboard"), item[1].get("board"))].append(item)
    for board, items in boards.items():
        board_changed = any(item[3] for item in items)
        for gid, details, stored, _changed, _active in items:
            code = [day, gid]
            stored_raw = details.get("raw_values") or {}
            normalized = details.get("normalized_values") or {}
            for key in ("relative_return", "volume_strength", "institutional_flow"):
                value = stored_raw.get(key)
                peers_all = [
                    p
                    for p in ((o[1].get("raw_values") or {}).get(key) for o in items)
                    if finite(p)
                ]
                peers_active = [
                    p
                    for p in (
                        (o[1].get("raw_values") or {}).get(key) for o in items if o[4]
                    )
                    if finite(p)
                ]
                matched, expected = _percentile_matches(
                    value, normalized.get(key), peers_all, peers_active
                )
                if matched:
                    check.ok()
                elif board_changed:
                    check.undetermined(
                        CHANGED,
                        code + [f"percentile_{key}", normalized.get(key), expected],
                    )
                else:
                    check.fail(
                        f"percentile_{key}", code + [normalized.get(key), expected]
                    )
            # 1.3.0 (#474): the catalyst is the board percentile of the raw
            # member share, and no event stays 0; before, it was the raw value.
            percentile_catalyst = details.get("hot_group_version") == "1.3.0"
            for key in ("breadth", "catalyst"):
                if key == "catalyst" and percentile_catalyst:
                    continue
                _judge(
                    check,
                    f"normalized_{key}",
                    normalized.get(key),
                    stored_raw.get(key),
                    code,
                    False,
                )
            if percentile_catalyst:
                value = stored_raw.get("catalyst")
                peers_all = [
                    p
                    for p in (
                        (o[1].get("raw_values") or {}).get("catalyst") for o in items
                    )
                    if finite(p)
                ]
                peers_active = [
                    p
                    for p in (
                        (o[1].get("raw_values") or {}).get("catalyst")
                        for o in items
                        if o[4]
                    )
                    if finite(p)
                ]
                if value == 0:
                    _judge(
                        check,
                        "percentile_catalyst",
                        normalized.get("catalyst"),
                        0.0,
                        code,
                        False,
                    )
                else:
                    matched, expected = _percentile_matches(
                        value, normalized.get("catalyst"), peers_all, peers_active
                    )
                    if matched:
                        check.ok()
                    elif board_changed:
                        # Same fallback as the other percentiles (#501).
                        check.undetermined(
                            CHANGED,
                            code
                            + [
                                "percentile_catalyst",
                                normalized.get("catalyst"),
                                expected,
                            ],
                        )
                    else:
                        check.fail(
                            "percentile_catalyst",
                            code + [normalized.get("catalyst"), expected],
                        )
            for key, column in (
                ("volume_strength", 4),
                ("institutional_flow", 5),
                ("catalyst", 6),
            ):
                _judge(
                    check,
                    f"column_{key}",
                    stored[column],
                    normalized.get(key),
                    code,
                    False,
                )
            usable = {
                k: normalized.get(k)
                for k in HOT_GROUP_WEIGHTS
                if finite(normalized.get(k))
            }
            weight = sum(HOT_GROUP_WEIGHTS[k] for k in usable)
            if stored[9] is not None and stored[9] < 3:
                expected_score = None
            elif weight + 1e-12 < HOT_GROUP_MINIMUM_WEIGHT:
                expected_score = None
            else:
                expected_score = round(
                    sum(
                        max(0.0, min(1.0, usable[k])) * HOT_GROUP_WEIGHTS[k]
                        for k in usable
                    )
                    / weight
                    * 100,
                    2,
                )
            _judge(check, "score", stored[7], expected_score, code, False)
        # Ranks: 1..n by score within the board; an inactive group keeps its score without a rank.
        scored = sorted(
            (
                item
                for item in items
                if item[2][7] is not None and (item[4] or item[2][8] is not None)
            ),
            key=lambda item: -item[2][7],
        )
        ranks = [item[2][8] for item in scored]
        scores = [item[2][7] for item in scored]
        ok = (
            sorted(r for r in ranks if r is not None) == list(range(1, len(scored) + 1))
            and None not in ranks
        )
        for (a, ra), (b, rb) in zip(zip(scores, ranks), zip(scores[1:], ranks[1:])):
            if ra is not None and rb is not None and a > b and ra > rb:
                ok = False
        if ok:
            check.ok()
        elif board_changed:
            check.undetermined(CHANGED, [day, list(board), "rank"])
        else:
            check.fail(
                "rank",
                [
                    day,
                    list(board),
                    list(zip([i[0] for i in scored], scores, ranks))[:10],
                ],
            )
