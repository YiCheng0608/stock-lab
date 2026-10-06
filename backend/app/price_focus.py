"""Two admitted TPEx stocks filtered by exact lots, TWD turnover and O/C."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import re
from typing import Any
from urllib.parse import urlencode

from . import tpex_price
from worker.tpex_price_capture import CUTOFF, SYMBOLS

VERSION = "price-lot-focus/m2-v3"
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


def detail_path(symbol: str, as_of: str, min_lots: str, day_move: str = "all", min_turnover: str = "0") -> str:
    query = urlencode({"as_of": as_of, "from": "price-lots", "focus_as_of": as_of, "focus_min_lots": min_lots,
                       "focus_day_move": day_move, "focus_min_turnover": min_turnover})
    return f"/stocks/TPEx/{symbol}?{query}"


def _identity(item: Any) -> bool:
    return (getattr(item, "market", None) == "TW" and getattr(item, "exchange", None) == "TPEx"
            and SYMBOLS.get(getattr(item, "symbol", None)) == getattr(item, "name", None)
            and getattr(item, "symbol", None) in SYMBOLS and getattr(item, "instrument_type", None) == "stock"
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


def build_price_focus(instruments: list[Any], as_of: date, min_lots: str, day_move: str = "all", min_turnover: str = "0", *, capture: bool = False) -> dict:
    minimum = parse_min_lots(min_lots)
    parse_day_move(day_move)
    parse_min_turnover(min_turnover)
    result = {"version": VERSION, "status": "unavailable", "as_of": as_of.isoformat() if type(as_of) is date else None,
              "min_lots": min_lots, "min_shares": minimum, "day_move": day_move, "min_turnover": min_turnover, "count": None, "items": [], "reads": [],
              "supported_scope": {"exchange": "TPEx", "symbols": list(SYMBOLS), "cutoff": CUTOFF.isoformat(), "currency": "TWD", "asset_type": "stock"},
              "can_capture": False, "reasons": [], "historical_pit": "unsupported", "sort": "code_ascending"}
    if type(as_of) is not date or as_of != CUTOFF:
        result["reasons"] = ["price_cutoff_not_supported"]
        return result
    by_symbol = {getattr(item, "symbol", None): item for item in instruments}
    if len(instruments) != 2 or set(by_symbol) != set(SYMBOLS) or not all(_identity(item) for item in instruments):
        result["reasons"] = ["price_focus_catalogue_not_supported"]
        return result
    if capture:
        tpex_price.capture_tpex_price(by_symbol["3105"], as_of)
    for symbol in sorted(SYMBOLS):
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
    if memories[0]["provenance"] != memories[1]["provenance"]:
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
    for read, direction, amount in zip(result["reads"], directions, amounts):
        memory = read["price_memory"]
        bar = memory["latest"]
        volume = bar["volume_exact"]
        actual_move, opening, closing = direction
        if int(volume) >= int(minimum) and int(amount) >= int(min_turnover) and (day_move == "all" or day_move == actual_move):
            symbol = read["instrument"]["symbol"]
            result["items"].append({"exchange": "TPEx", "symbol": symbol, "name": read["instrument"]["name"],
                                    "volume_exact": volume, "volume_lots": lots_text(volume), "min_lots": min_lots,
                                    "min_shares": minimum, "min_turnover": min_turnover, "turnover_exact": amount,
                                    "day_move": actual_move, "open_exact": opening, "close_exact": closing,
                                    "reasons": ["volume_at_least_min_lots", "turnover_at_least_min_turnover", DAY_MOVE_REASONS[actual_move]], "source_date": bar["date"],
                                    "source_version": memory["provenance"]["source_version"], "detail_url": detail_path(symbol, as_of.isoformat(), min_lots, day_move, min_turnover)})
    result.update(status="available", count=len(result["items"]), reasons=[], can_capture=False)
    return result
