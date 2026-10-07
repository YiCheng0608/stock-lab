"""Tuple-scoped admitted TPEx stocks filtered by exact lots, turnover, O/C and range."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import re
from typing import Any
from urllib.parse import urlencode

from . import tpex_price
from worker.tpex_price_capture import CUTOFF, APPROVED_CUTOFFS, SYMBOLS

VERSION = "price-lot-focus/m2-v10"
MAX_SHARES = "9223372036854775807"
DAY_MOVES = ("all", "up", "down", "flat")
DAY_MOVE_REASONS = {"up": "close_above_open", "down": "close_below_open", "flat": "close_equal_open"}


def parse_day_move(value: Any) -> str:
    if type(value) is not str or value not in DAY_MOVES:
        raise ValueError("day_move must be all, up, down or flat")
    return value


def exact_day_move(bar: Any) -> tuple[str, str, str] | None:
    fields = bar.get("source_fields") if isinstance(bar, dict) else None
    if not isinstance(fields, dict):
        return None
    prices = [fields.get(key) for key in ("開盤", "收盤")]
    if any(type(value) is not str or len(value) > 64 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value, flags=re.ASCII) for value in prices):
        return None
    opening, closing = (Decimal(value) for value in prices)
    if not opening.is_finite() or not closing.is_finite() or opening <= 0 or closing <= 0:
        return None
    return ("up" if closing > opening else "down" if closing < opening else "flat", *prices)


def parse_min_lots(value: Any) -> str:
    """Keep the supplied lots condition, but compare its canonical integer shares."""
    if type(value) is not str or len(value) > 20 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,3})?", value, flags=re.ASCII):
        raise ValueError("min_lots must be a nonnegative decimal string with at most three decimal places")
    whole, _, fraction = value.partition(".")
    shares = (whole + fraction.ljust(3, "0")).lstrip("0") or "0"
    if (len(shares), shares) > (len(MAX_SHARES), MAX_SHARES):
        raise ValueError("min_lots exceeds the int64 share limit")
    return shares


def parse_min_range_pct(value: Any) -> str:
    """The percentage uses the same exact thousandth/int64 string contract."""
    try:
        return parse_min_lots(value)
    except ValueError as error:
        raise ValueError("min_range_pct must be a nonnegative decimal string with at most three decimal places within the int64 thousandth limit") from error


def exact_day_range(bar: Any) -> tuple[str, str, str, int, int, int] | None:
    fields = bar.get("source_fields") if isinstance(bar, dict) else None
    if not isinstance(fields, dict):
        return None
    prices = [fields.get(key) for key in ("開盤", "最高", "最低")]
    if any(type(value) is not str or len(value) > 64 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value, flags=re.ASCII) for value in prices):
        return None
    parts = [value.partition(".") for value in prices]
    scale = max(len(part[2]) for part in parts)
    opening, high, low = (int(whole + fraction.ljust(scale, "0")) for whole, _, fraction in parts)
    if not high >= opening >= low > 0:
        return None
    return (*prices, opening, high, low)


def range_meets_minimum(prices: tuple[str, str, str, int, int, int], minimum: str) -> bool:
    _, _, _, opening, high, low = prices
    return 100000 * (high - low) >= int(minimum) * opening


def lots_text(shares: str) -> str:
    padded = shares.zfill(4)
    fraction = padded[-3:].rstrip("0")
    return padded[:-3] + ("." + fraction if fraction else "")


def parse_min_turnover(value: Any) -> str:
    if (type(value) is not str or len(value) > 19 or not re.fullmatch(r"(?:0|[1-9][0-9]*)", value, flags=re.ASCII)
            or (len(value), value) > (len(MAX_SHARES), MAX_SHARES)):
        raise ValueError("min_turnover must be a nonnegative int64 integer TWD string")
    return value


def exact_turnover(bar: Any) -> str | None:
    if not isinstance(bar, dict) or bar.get("currency") != "TWD":
        return None
    fields = bar.get("source_fields")
    amount = bar.get("turnover_exact")
    try:
        parse_min_turnover(amount)
    except ValueError:
        return None
    return amount if (isinstance(fields, dict) and fields.get("成交金額") == amount
                      and bar.get("turnover_status") == "available" and bar.get("turnover_reason", "missing") is None) else None


def detail_path(symbol: str, as_of: str, min_lots: str, day_move: str = "all", min_turnover: str = "0", min_range_pct: str = "0") -> str:
    query = urlencode({"as_of": as_of, "from": "price-lots", "focus_as_of": as_of, "focus_min_lots": min_lots,
                       "focus_day_move": day_move, "focus_min_turnover": min_turnover, "focus_min_range_pct": min_range_pct})
    return f"/stocks/TPEx/{symbol}?{query}"


def _identity(item: Any, symbols: dict[str, str]) -> bool:
    return (getattr(item, "market", None) == "TW" and getattr(item, "exchange", None) == "TPEx"
            and symbols.get(getattr(item, "symbol", None)) == getattr(item, "name", None)
            and getattr(item, "symbol", None) in symbols and getattr(item, "instrument_type", None) == "stock"
            and not getattr(item, "etf_category", None) and getattr(item, "currency", "TWD") == "TWD")


def _instrument(item: Any) -> dict:
    return {key: getattr(item, key, None) for key in ("id", "market", "exchange", "symbol", "name", "instrument_type", "etf_category", "is_watchlisted", "status")} | {"currency": "TWD"}


def _available(read: dict, as_of: date) -> bool:
    memory = read["price_memory"]
    if not memory or memory.get("status") != "available":
        return False
    bar = memory.get("latest")
    volume = bar.get("volume_exact") if isinstance(bar, dict) else None
    return (isinstance(bar, dict) and memory.get("as_of") == as_of.isoformat() and memory.get("unit") == "shares"
            and bar.get("date") == as_of.isoformat() and bar.get("symbol") == read["instrument"]["symbol"]
            and type(volume) is str and re.fullmatch(r"(?:0|[1-9][0-9]*)", volume, flags=re.ASCII) is not None
            and (len(volume), volume) <= (len(MAX_SHARES), MAX_SHARES) and isinstance(memory.get("provenance"), dict))


def build_price_focus(instruments: list[Any], as_of: date, min_lots: str, day_move: str = "all", min_turnover: str = "0", min_range_pct: str = "0", *, capture: bool = False) -> dict:
    minimum = parse_min_lots(min_lots)
    parse_day_move(day_move)
    parse_min_turnover(min_turnover)
    minimum_range = parse_min_range_pct(min_range_pct)
    symbols = tpex_price.supported_symbols(as_of)
    policy_version = tpex_price.active_policy_version(as_of)
    version = VERSION if policy_version == tpex_price.EIGHTH_SCOPE_POLICY_VERSION else "price-lot-focus/m2-v9" if policy_version == tpex_price.SEVENTH_SCOPE_POLICY_VERSION else "price-lot-focus/m2-v8" if policy_version == tpex_price.SIXTH_SCOPE_POLICY_VERSION else "price-lot-focus/m2-v7" if policy_version == tpex_price.FIFTH_SCOPE_POLICY_VERSION else "price-lot-focus/m2-v6" if policy_version == tpex_price.EXTENDED_SCOPE_POLICY_VERSION else "price-lot-focus/m2-v5"
    result = {"version": version, "status": "unavailable", "as_of": as_of.isoformat() if type(as_of) is date else None,
              "min_lots": min_lots, "min_shares": minimum, "day_move": day_move, "min_turnover": min_turnover, "min_range_pct": min_range_pct, "count": None, "items": [], "reads": [],
              "supported_scope": {"exchange": "TPEx", "symbols": list(symbols), "cutoff": as_of.isoformat() if type(as_of) is date and as_of in APPROVED_CUTOFFS else CUTOFF.isoformat(), "currency": "TWD", "asset_type": "stock"},
              "can_capture": False, "reasons": [], "historical_pit": "unsupported", "sort": "code_ascending"}
    if type(as_of) is not date or as_of not in APPROVED_CUTOFFS:
        result["reasons"] = ["price_cutoff_not_supported"]
        return result
    by_symbol = {getattr(item, "symbol", None): item for item in instruments}
    if len(instruments) != len(symbols) or set(by_symbol) != set(symbols) or not all(_identity(item, symbols) for item in instruments):
        result["reasons"] = ["price_focus_catalogue_not_supported"]
        return result
    if capture:
        tpex_price.capture_tpex_price(by_symbol[sorted(symbols)[0]], as_of)
    for symbol in sorted(symbols):
        instrument = by_symbol[symbol]
        try:
            memory = tpex_price.build_tpex_price(instrument, as_of)
        except (KeyError, TypeError, ValueError):
            memory = None
        result["reads"].append({"instrument": _instrument(instrument), "price_memory": memory})
    memories = [read["price_memory"] for read in result["reads"]]
    result["can_capture"] = all(memory and memory["capture_state"]["can_capture"] for memory in memories)
    if not all(_available(read, as_of) for read in result["reads"]):
        result["reasons"] = list(dict.fromkeys(reason for memory in memories for reason in (memory["reasons"] if memory else ["price_focus_read_invalid"])))
        if not result["reasons"]:
            result["reasons"] = ["price_focus_read_invalid"]
        return result
    if any(memory["provenance"] != memories[0]["provenance"] for memory in memories[1:]):
        result["reasons"] = ["price_focus_source_mismatch"]
        return result
    directions = [exact_day_move(memory["latest"]) for memory in memories]
    if any(direction is None for direction in directions):
        result["reasons"] = ["price_focus_direction_unavailable"]
        return result
    amounts = [exact_turnover(memory["latest"]) for memory in memories]
    if any(amount is None for amount in amounts):
        result["reasons"] = ["price_focus_turnover_unavailable"]
        return result
    ranges = [exact_day_range(memory["latest"]) for memory in memories]
    if any(prices is None for prices in ranges):
        result["reasons"] = ["price_focus_range_unavailable"]
        return result
    for read, direction, amount, prices in zip(result["reads"], directions, amounts, ranges):
        memory = read["price_memory"]
        bar = memory["latest"]
        volume = bar["volume_exact"]
        actual_move, opening, closing = direction
        if (int(volume) >= int(minimum) and int(amount) >= int(min_turnover)
                and (day_move == "all" or day_move == actual_move) and range_meets_minimum(prices, minimum_range)):
            symbol = read["instrument"]["symbol"]
            result["items"].append({"exchange": "TPEx", "symbol": symbol, "name": read["instrument"]["name"],
                                    "volume_exact": volume, "volume_lots": lots_text(volume), "min_lots": min_lots,
                                    "min_shares": minimum, "min_turnover": min_turnover, "turnover_exact": amount,
                                    "day_move": actual_move, "open_exact": opening, "close_exact": closing,
                                    "min_range_pct": min_range_pct, "high_exact": prices[1], "low_exact": prices[2],
                                    "reasons": ["volume_at_least_min_lots", "turnover_at_least_min_turnover", DAY_MOVE_REASONS[actual_move], "range_at_least_min_range_pct"], "source_date": bar["date"],
                                    "source_version": memory["provenance"]["source_version"], "detail_url": detail_path(symbol, as_of.isoformat(), min_lots, day_move, min_turnover, min_range_pct)})
    result.update(status="available", count=len(result["items"]), reasons=[], can_capture=False)
    return result
