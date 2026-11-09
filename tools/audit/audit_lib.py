"""Shared pieces of the DB audit (Issue #391): results, numbers, raw files, factors.

Standard library only, except where a stored raw capture is
(``app.raw_paths.payload_file``, #342): no product calculation is imported, the
audit recomputes from the stored inputs and the specification
(docs/spec/), so a product bug is not reproduced by the check itself.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from app.raw_paths import legacy_relative, payload_file  # noqa: E402

# What the audit recomputes against (docs/spec/indicators.md); a product change of
# these must change the audit too (backend/tests/test_audit.py pins them).
INDICATOR_VERSION = "indicators/v1"
# app.coverage.SESSION_BASIS_START: the first session of the stock history.
# The TAIEX rows before it are index history (Issue #563), never a session.
SESSION_BASIS_START = "2024-09-30"
PRICE_BASIS = "as_of_date_raw_basis/v2"
# The official reference prices are published in 0.01 units, cut (docs/spec/indicators.md 還原因子).
REFERENCE_TOLERANCE = 0.02
# Relative tolerance of a recomputed value (stored indicators are rounded to 6 places).
VALUE_TOLERANCE = 1e-6
# Failure examples kept per category in summary.md and findings.json.
EXAMPLES = 20

PASS, FAIL, UNKNOWN = "pass", "fail", "undetermined"
RESULT_LABELS = {PASS: "通過", FAIL: "失敗", UNKNOWN: "無法判定"}


@dataclass
class Check:
    """One audit item: what was compared, what failed and what could not be judged."""

    key: str
    title: str
    issues: str = ""
    scope: str = ""
    compared: int = 0
    failures: Counter = field(default_factory=Counter)
    unknown: Counter = field(default_factory=Counter)
    examples: dict[str, list[Any]] = field(default_factory=dict)
    unknown_examples: dict[str, list[Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0
    skipped: str | None = None

    def ok(self, n: int = 1) -> None:
        self.compared += n

    def fail(self, category: str, example: Any) -> None:
        self.compared += 1
        self.failures[category] += 1
        kept = self.examples.setdefault(category, [])
        if len(kept) < EXAMPLES:
            kept.append(example)

    def undetermined(self, reason: str, example: Any = None) -> None:
        self.unknown[reason] += 1
        if example is not None:
            kept = self.unknown_examples.setdefault(reason, [])
            if len(kept) < EXAMPLES:
                kept.append(example)

    @property
    def result(self) -> str:
        if self.failures:
            return FAIL
        if self.skipped or self.unknown or self.compared == 0:
            return UNKNOWN
        return PASS

    def as_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "issues": self.issues,
            "scope": self.scope,
            "result": self.result,
            "compared": self.compared,
            "failures": dict(self.failures),
            "undetermined": dict(self.unknown),
            "examples": self.examples,
            "undetermined_examples": self.unknown_examples,
            "notes": self.notes,
            "seconds": round(self.seconds, 1),
            "skipped": self.skipped,
        }


def connect(db: Path) -> sqlite3.Connection:
    """A read-only connection: ``mode=ro`` and ``query_only`` (nothing can be written)."""

    uri = Path(db).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only = 1")
    return con


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def tables(con: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in con.execute("select name from sqlite_master where type='table'")
    }


# --- numbers and dates --------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


def num(value: Any) -> float | None:
    """A finite number from a stored value or an official string ('1,234.50'), else None."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = _TAG.sub("", str(value)).replace(",", "").strip()
    for unit in ("元／股", "股", "元"):
        text = text.removesuffix(unit).strip()
    if not _NUMBER.match(text):
        return None
    return float(text)


def finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def positive(value: Any) -> bool:
    return finite(value) and value > 0


def close_enough(
    a: float | None, b: float | None, tolerance: float = VALUE_TOLERANCE
) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tolerance * max(1.0, abs(b))


_ROC_COMPACT = re.compile(r"^(\d{3})(\d{2})(\d{2})$")
_ROC_TEXT = re.compile(r"^(\d{2,3})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})\s*日?$")


def official_date(text: Any) -> str | None:
    """ISO date of an official date: '1151106', '115年11月02日', '115/11/02' or ISO."""

    if text is None:
        return None
    value = str(text).strip()
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        pass
    match = _ROC_COMPACT.match(value) or _ROC_TEXT.match(value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year + 1911, month, day).isoformat()
    except ValueError:
        return None


# --- percentile ---------------------------------------------------------------


def mid_rank(
    value: float, population: Iterable[float], better: str = "higher"
) -> float:
    """docs/spec/candidate_score.md mid-rank percentile ``(less + (equal - 1) / 2) / (n - 1)``; 0.5 for one value."""

    sign = 1.0 if better == "higher" else -1.0
    target = sign * value
    values = [sign * item for item in population]
    if len(values) <= 1:
        return 0.5
    less = sum(item < target for item in values)
    equal = sum(item == target for item in values)
    return max(0.0, min(1.0, (less + (equal - 1) / 2) / (len(values) - 1)))


# --- raw files ----------------------------------------------------------------


class RawFiles:
    """Read official raw captures, only ever with ``open(path, "rb")`` (#391 決定).

    Where the file is comes from ``app.raw_paths.payload_file``: the stored
    path when it exists, else an old Windows path under ``STOCK_RAW_DIR``.
    ``raw_dir`` (``--raw-dir``, a raw copy) is where an old Windows path is
    looked for when neither exists, like ``STOCK_STORED_RAW_DIR``.  A file that
    cannot be opened or decoded is ``None``: the comparison it feeds is
    undetermined, never failed.
    """

    def __init__(self, raw_dir: Path | None = None, cache_size: int = 8) -> None:
        self.raw_dir = None if raw_dir is None else Path(raw_dir)
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.cache_size = cache_size
        self.read = 0
        self.unreadable = 0

    def path(self, payload_path: str) -> Path:
        found = payload_file(payload_path)
        if self.raw_dir is None or found.exists():
            return found
        relative = legacy_relative(payload_path)
        return found if relative is None else self.raw_dir.joinpath(*relative.parts)

    def load(self, payload_path: str | None) -> Any:
        if not payload_path:
            self.unreadable += 1
            return None
        if payload_path in self.cache:
            self.cache.move_to_end(payload_path)
            return self.cache[payload_path]
        try:
            with open(self.path(payload_path), "rb") as handle:
                data = json.loads(handle.read().decode("utf-8"))
        except (OSError, ValueError):
            self.unreadable += 1
            return None
        self.read += 1
        self.cache[payload_path] = data
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return data


# --- official raw tables ------------------------------------------------------


def openapi_session(payload: Any) -> str | None:
    """ISO session of a TPEx OpenAPI table (Issue #579): every row's ``Date`` the same.

    The OpenAPI tables have no date parameter; a table of another session (the
    margin table before TPEx updates it) is kept as raw under the requested date.
    """

    if not isinstance(payload, list) or not payload:
        return None
    if not all(isinstance(row, dict) for row in payload):
        return None
    days = {official_date(row.get("Date")) for row in payload}
    return days.pop() if len(days) == 1 else None


def _openapi_rows(payload: Any) -> list[dict[str, Any]] | None:
    return payload if openapi_session(payload) is not None else None


def table_rows(
    payload: Any, required: Iterable[str]
) -> Iterable[tuple[list[str], list[Any]]]:
    """(fields, row) of every table of a TWSE/TPEx payload whose fields include ``required``."""

    need = list(required)
    if not isinstance(payload, dict):
        return
    candidates = (
        payload.get("tables") if isinstance(payload.get("tables"), list) else [payload]
    )
    for table in candidates:
        if not isinstance(table, dict):
            continue
        fields = table.get("fields") or []
        if not all(name in fields for name in need):
            continue
        for row in table.get("data") or []:
            if isinstance(row, list):
                yield fields, row


def quote_rows(payload: Any, exchange: str) -> dict[str, dict[str, float | None]]:
    """Code -> OHLC, volume, turnover of a TWSE MI_INDEX or TPEx dailyQuotes capture."""

    names = (
        {
            "code": "證券代號",
            "open": "開盤價",
            "high": "最高價",
            "low": "最低價",
            "close": "收盤價",
            "volume": "成交股數",
            "turnover": "成交金額",
        }
        if exchange == "TWSE"
        else {
            "code": "代號",
            "open": "開盤",
            "high": "最高",
            "low": "最低",
            "close": "收盤",
            "volume": "成交股數",
            "turnover": "成交金額(元)",
        }
    )
    rows: dict[str, dict[str, float | None]] = {}
    if exchange == "TPEx" and isinstance(payload, list):
        # tpex_mainboard_daily_close_quotes: the website table's columns by key.
        keys = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "TradingShares",
            "turnover": "TransactionAmount",
        }
        for row in _openapi_rows(payload) or []:
            code = str(row.get("SecuritiesCompanyCode") or "").strip()
            if code:
                rows[code] = {name: num(row.get(key)) for name, key in keys.items()}
        return rows
    for fields, row in table_rows(payload, names.values()):
        index = {name: fields.index(label) for name, label in names.items()}
        code = str(row[index["code"]]).strip()
        rows[code] = {name: num(row[i]) for name, i in index.items() if name != "code"}
    return rows


TAIEX_ROW = "發行量加權股價指數"


def taiex_close(payload: Any) -> float | None:
    for fields, row in table_rows(payload, ("指數", "收盤指數")):
        if str(row[fields.index("指數")]).strip() == TAIEX_ROW:
            return num(row[fields.index("收盤指數")])
    return None


# tpex_3insti_daily_trading keys of the website table's columns 4, 13 and 22.
TPEX_OPENAPI_INSTITUTIONAL = (
    "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
    "SecuritiesInvestmentTrustCompanies-Difference",
    "Dealers-Difference",
)


def institutional_rows(
    payload: Any, exchange: str
) -> dict[str, tuple[float | None, float | None, float | None]] | None:
    """Code -> (foreign excl. foreign dealers, trust, dealer total) of T86 / TPEx dailyTrade."""

    rows: dict[str, tuple[float | None, float | None, float | None]] = {}
    if exchange == "TWSE":
        labels = (
            "證券代號",
            "外陸資買賣超股數(不含外資自營商)",
            "投信買賣超股數",
            "自營商買賣超股數",
        )
        found = False
        for fields, row in table_rows(payload, labels):
            found = True
            i = [fields.index(label) for label in labels]
            rows[str(row[i[0]]).strip()] = (
                num(row[i[1]]),
                num(row[i[2]]),
                num(row[i[3]]),
            )
        return rows if found else None
    if isinstance(payload, list):
        # tpex_3insti_daily_trading: the same three columns by key.
        listed = _openapi_rows(payload)
        if listed is None:
            return None
        for row in listed:
            code = str(row.get("SecuritiesCompanyCode") or "").strip()
            if code:
                rows[code] = tuple(
                    num(row.get(key)) for key in TPEX_OPENAPI_INSTITUTIONAL
                )
        return rows
    # TPEx: 24 columns, the 買賣超 of 外資及陸資(不含外資自營商), 投信 and 自營商合計
    # are columns 4, 13 and 22 (the headers repeat, so positions are the contract).
    found = False
    for fields, row in table_rows(payload, ("代號",)):
        if len(fields) != 24 or len(row) < 24:
            continue
        found = True
        rows[str(row[0]).strip()] = (num(row[4]), num(row[13]), num(row[22]))
    return rows if found else None


def margin_rows(
    payload: Any, exchange: str
) -> dict[str, tuple[float | None, float | None]] | None:
    """Code -> (previous, current) margin balance of MI_MARGN / TPEx margin balance."""

    rows: dict[str, tuple[float | None, float | None]] = {}
    found = False
    if exchange == "TPEx" and isinstance(payload, list):
        # tpex_mainboard_margin_balance: 前資餘額(張) and 資餘額 by key.
        listed = _openapi_rows(payload)
        if listed is None:
            return None
        for row in listed:
            code = str(row.get("SecuritiesCompanyCode") or "").strip()
            if code:
                rows[code] = (
                    num(row.get("MarginPurchaseBalancePreviousDay")),
                    num(row.get("MarginPurchaseBalance")),
                )
        return rows
    if exchange == "TWSE":
        for fields, row in table_rows(payload, ("代號", "前日餘額", "今日餘額")):
            found = True
            rows[str(row[0]).strip()] = (
                num(row[fields.index("前日餘額")]),
                num(row[fields.index("今日餘額")]),
            )
    else:
        for fields, row in table_rows(payload, ("代號", "前資餘額(張)", "資餘額")):
            found = True
            rows[str(row[0]).strip()] = (
                num(row[fields.index("前資餘額(張)")]),
                num(row[fields.index("資餘額")]),
            )
    return rows if found else None


def action_rows(payload: Any, endpoint: str) -> list[tuple[str, str, str]] | None:
    """(exchange, code, ISO ex-date) of every event of an official ex-rights capture."""

    events: list[tuple[str, str, str]] = []
    if "TWT48U_ALL" in endpoint:
        if not isinstance(payload, list):
            return None
        for row in payload:
            day = official_date(row.get("Date")) if isinstance(row, dict) else None
            if day and row.get("Code"):
                events.append(("TWSE", str(row["Code"]).strip(), day))
        return events
    if "tpex_exright_daily" in endpoint:
        if not isinstance(payload, list):
            return None
        for row in payload:
            day = official_date(row.get("Date")) if isinstance(row, dict) else None
            if day and row.get("SecuritiesCompanyCode"):
                events.append(("TPEx", str(row["SecuritiesCompanyCode"]).strip(), day))
        return events
    if "TWT49U" in endpoint and "Detail" not in endpoint:
        if not isinstance(payload, dict):
            return None
        for fields, row in table_rows(payload, ("資料日期", "股票代號")):
            day = official_date(row[fields.index("資料日期")])
            if day:
                events.append(("TWSE", str(row[fields.index("股票代號")]).strip(), day))
        return events
    if "exDailyQ" in endpoint:
        if not isinstance(payload, dict):
            return None
        for fields, row in table_rows(payload, ("除權息日期", "代號")):
            day = official_date(row[fields.index("除權息日期")])
            if day:
                events.append(("TPEx", str(row[fields.index("代號")]).strip(), day))
        return events
    return None


# --- corporate-action factors (docs/spec/indicators.md 還原因子) --------------------------------

# (除權息前收盤價, 除權息參考價) and (除權息前收盤價, 減除股利參考價): TPEx, then TWSE.
EX_RIGHTS_PRICES = (
    ("ClosePriceBeforeExRightsDiviend", "ExRightsDiviendQuote"),
    ("除權息前收盤價", "除權息參考價"),
)
DIVIDEND_DEDUCTED_PRICES = (
    ("ClosePriceBeforeExRightsDiviend", "DividendDeductedQuote"),
    ("除權息前收盤價", "減除股利參考價"),
)


@dataclass(frozen=True)
class Action:
    action_date: str
    cash: float | None
    stock_ratio: float | None
    split: float | None
    reference: float | None
    details: dict[str, Any]
    collected_at: str | None = None


def official_prices(
    details: dict[str, Any], keys=EX_RIGHTS_PRICES
) -> tuple[float, float] | None:
    for before_key, after_key in keys:
        before, after = num(details.get(before_key)), num(details.get(after_key))
        if positive(before) and positive(after):
            return before, after
    return None


def field_factor(action: Action, reference: float | None) -> float:
    """Split, ``1 / (1 + 配股率)`` and ``(參考價 - 現金股利) / 參考價``."""

    factor = 1.0
    if positive(action.split):
        factor = factor / action.split if action.split > 1 else factor * action.split
    if positive(action.stock_ratio):
        factor /= 1.0 + action.stock_ratio
    if positive(action.cash) and positive(reference) and reference > action.cash:
        factor *= (reference - action.cash) / reference
    return factor


def action_factor(
    action: Action, previous_close: float | None, basis: str = PRICE_BASIS
) -> float:
    """One event's price factor under ``basis`` (v1: steps 1 and 3; v2: 1, 2, 3)."""

    explicit = num(action.details.get("price_factor"))
    if positive(explicit):
        return explicit
    if basis.endswith("/v2"):
        prices = official_prices(action.details)
        if prices is not None:
            before, quote = prices
            implied = field_factor(action, before) * before
            if round(abs(implied - quote), 6) > REFERENCE_TOLERANCE:
                return quote / before
    reference = action.reference if action.reference is not None else previous_close
    return field_factor(action, reference)


def load_actions(con: sqlite3.Connection, instrument_id: int) -> list[Action]:
    rows = con.execute(
        "select action_date, cash_dividend, stock_dividend_ratio, split_ratio, reference_price, details_json, collected_at"
        " from corporate_actions where instrument_id=? order by action_date, id",
        (instrument_id,),
    ).fetchall()
    actions = []
    for day, cash, ratio, split, reference, details, collected in rows:
        try:
            parsed = json.loads(details) if details else {}
        except ValueError:
            parsed = {}
        actions.append(
            Action(
                day,
                cash,
                ratio,
                split,
                reference,
                parsed if isinstance(parsed, dict) else {},
                collected,
            )
        )
    return actions


def factors_by_bar(
    bars: list[tuple], actions: list[Action], basis: str = PRICE_BASIS
) -> list[float]:
    """Cumulative factor of the events dated on or before each bar (bars: (date, ..., close at 4))."""

    own: list[tuple[str, float]] = []
    for action in actions:
        previous = None
        for bar in reversed(bars):
            if bar[0] < action.action_date and finite(bar[4]):
                previous = bar[4]
                break
        own.append((action.action_date, action_factor(action, previous, basis)))
    own.sort(key=lambda item: item[0])
    result: list[float] = []
    cumulative, index = 1.0, 0
    for bar in bars:
        while index < len(own) and own[index][0] <= bar[0]:
            cumulative *= own[index][1]
            index += 1
        result.append(cumulative if finite(cumulative) and cumulative > 0 else 1.0)
    return result
