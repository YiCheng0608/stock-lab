"""Two admitted TPEx stocks filtered by exact lots; no database or source I/O on import."""
from __future__ import annotations

from datetime import date
import re
from typing import Any
from urllib.parse import urlencode

from . import tpex_price
from worker.tpex_price_capture import CUTOFF, SYMBOLS

VERSION = "price-lot-focus/m2-v1"
MAX_SHARES = "9223372036854775807"


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


def detail_path(symbol: str, as_of: str, min_lots: str) -> str:
    query = urlencode({"as_of": as_of, "from": "price-lots", "focus_as_of": as_of, "focus_min_lots": min_lots})
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


def build_price_focus(instruments: list[Any], as_of: date, min_lots: str, *, capture: bool = False) -> dict:
    minimum = parse_min_lots(min_lots)
    result = {"version": VERSION, "status": "unavailable", "as_of": as_of.isoformat() if type(as_of) is date else None,
              "min_lots": min_lots, "min_shares": minimum, "count": None, "items": [], "reads": [],
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
    for read in result["reads"]:
        memory = read["price_memory"]
        bar = memory["latest"]
        volume = bar["volume_exact"]
        if int(volume) >= int(minimum):
            symbol = read["instrument"]["symbol"]
            result["items"].append({"exchange": "TPEx", "symbol": symbol, "name": read["instrument"]["name"],
                                    "volume_exact": volume, "volume_lots": lots_text(volume), "min_lots": min_lots,
                                    "min_shares": minimum, "reason": "volume_at_least_min_lots", "source_date": bar["date"],
                                    "source_version": memory["provenance"]["source_version"], "detail_url": detail_path(symbol, as_of.isoformat(), min_lots)})
    result.update(status="available", count=len(result["items"]), reasons=[], can_capture=False)
    return result
