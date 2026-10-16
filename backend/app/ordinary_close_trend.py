"""Read-only MA20 / 20-day return / close-over-MA20 from the issue 7 saved ordinary closes (issue 8).

The only data input is ``ordinary_close_source.load_saved_closes`` for the one supported
cutoff, called without ``pins`` so the product's externally published policy pin applies.
Nothing is fetched, saved or cached; an unsupported cutoff or instrument never reaches the
environment or the disk. The root is read from ``STOCK_ORDINARY_CLOSE_PRIVATE_ROOT`` at request
time, never at import.

The values follow the existing quantitative contract (docs/STOCK_RESEARCH_PAGE.md section 3.2):
MA20 is the simple average of the latest 20 trading-day closes, the 20-day return is
``close[T] / close[T-20] - 1`` (21 closes) and the ratio is ``close[T] / MA20[T]``. All three
are exact rationals; rounding happens once, only for the ``display`` text. No trend formula
exists in that contract, so the trend entry is always ``formula_not_defined``.
"""
from __future__ import annotations

import os
import re
from datetime import date
from fractions import Fraction
from typing import Any, Mapping, Sequence

from . import ordinary_close_source as source

VERSION = "ordinary-close-trend/m1-v1"
CUTOFF = source.IDENTITY_AS_OF
SYMBOLS = source.SYMBOLS
MA_DAYS = 20
RETURN_DAYS = 20
RETURN_CLOSES = RETURN_DAYS + 1
ROUNDING = "half_up_away_from_zero"
PLACES = {"ma20": 2, "return_20d": 2, "close_over_ma20": 4}
# Verbatim ``unsupported`` of the externally published policy v1 (SHA-256 f7659362...9968).
UNSUPPORTED = (
    "historical_pit", "publication_time", "first_availability", "revision_guarantee", "adjusted_prices",
    "company_actions", "suspension_comparability", "whole_window_historical_membership",
    "historical_eligibility", "actionable_strategy", "plan", "trading", "historical_simulation",
    "raw_body_storage", "redistribution", "other_cutoffs",
)
LIMITATIONS = (
    "provider_reported_nominal_closes_not_adjusted_for_company_actions",
    "suspension_comparability_not_established",
    "trend_judgement_formula_not_defined_not_inferred",
    "not_historical_pit_not_a_plan_signal_or_trade",
)
_CODE = re.compile(r"[a-z0-9_]{1,64}")


class _Rejected(Exception):
    """The verified bundle does not describe the requested cutoff and window."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def round_half_up(value: Fraction, places: int) -> str:
    """Decimal text rounded half away from zero; a result of zero never carries a sign."""
    scaled = abs(value) * 10 ** places
    units = (scaled.numerator * 2 + scaled.denominator) // (scaled.denominator * 2)
    whole, part = divmod(units, 10 ** places)
    text = str(whole) if places == 0 else f"{whole}.{part:0{places}d}"
    return "-" + text if value < 0 and units else text


def _row(close: Any) -> dict[str, str]:
    return {"date": close.date, "close": close.text}


def _insufficient(unit: str, scale: int) -> dict[str, Any]:
    return {"status": "data_insufficient", "reasons": ["ordinary_close_window_insufficient"], "exact": None,
            "display": None, "display_unit": unit, "display_scale": scale, "display_places": None, "rounding": ROUNDING}


def _value(kind: str, exact: Fraction, unit: str, scale: int, **trace: Any) -> dict[str, Any]:
    return {"status": "available", "reasons": [], "exact": fraction_text(exact),
            "display": round_half_up(exact * scale, PLACES[kind]), "display_unit": unit, "display_scale": scale,
            "display_places": PLACES[kind], "rounding": ROUNDING, **trace}


def derive_values(rows: Sequence[Any]) -> dict[str, Any]:
    """The three contract values from ascending closes (``date``, ``text``, exact ``value``)."""
    latest = rows[-1] if rows else None
    ma20 = (sum((close.value for close in rows[-MA_DAYS:]), Fraction(0)) / MA_DAYS) if len(rows) >= MA_DAYS else None
    values: dict[str, Any] = {
        "latest": _row(latest) if latest else None,
        "ma20": _insufficient("TWD_per_share", 1), "return_20d": _insufficient("percent", 100),
        "close_over_ma20": _insufficient("ratio", 1),
        "trend": {"status": "formula_not_defined", "reasons": ["trend_formula_not_defined"], "exact": None, "display": None},
    }
    if ma20 is not None:
        start = rows[-MA_DAYS]
        values["ma20"] = _value("ma20", ma20, "TWD_per_share", 1, window_start=start.date, window_end=latest.date, count=MA_DAYS)
        values["close_over_ma20"] = _value("close_over_ma20", latest.value / ma20, "ratio", 1, latest_date=latest.date,
                                           latest_close=latest.text, ma20_window_start=start.date, ma20_window_end=latest.date)
    if len(rows) >= RETURN_CLOSES:
        base = rows[-RETURN_CLOSES]
        values["return_20d"] = _value("return_20d", latest.value / base.value - 1, "percent", 100, base_date=base.date,
                                      base_close=base.text, latest_date=latest.date, latest_close=latest.text)
    return values


def _envelope(instrument: Any, as_of: date | None) -> dict[str, Any]:
    return {
        "version": VERSION, "status": "unavailable", "origin": "private_local",
        "exchange": instrument.exchange, "symbol": instrument.symbol,
        "as_of": as_of.isoformat() if type(as_of) is date else None,
        "supported_scope": {"cutoff": CUTOFF, "symbols": list(SYMBOLS), "market": source.MARKET,
                            "instrument_type": source.INSTRUMENT_TYPE},
        "price_basis": "provider_reported_nominal_close", "unit": "TWD_per_share",
        "windows": {"ma_days": MA_DAYS, "return_days": RETURN_DAYS, "return_closes": RETURN_CLOSES},
        "closes": [], "values": None, "provenance": None,
        "unsupported": list(UNSUPPORTED), "limitations": [*source.LIMITATIONS, *LIMITATIONS],
        "reasons": [], "read_state": {"verified": False, "read_only": True, "network_requests": 0, "writes": 0},
    }


def _gate(instrument: Any, as_of: date | None) -> str | None:
    if type(as_of) is not date or as_of.isoformat() != CUTOFF:
        return "ordinary_close_cutoff_not_supported"
    if (instrument.exchange != "TPEx" or instrument.symbol not in SYMBOLS or instrument.market != "TW"
            or instrument.instrument_type != "stock" or instrument.etf_category):
        return "ordinary_close_instrument_not_supported"
    return None


def _reason(code: Any) -> str:
    return "ordinary_close_" + code if type(code) is str and _CODE.fullmatch(code) else "ordinary_close_read_failed"


def _provenance(loaded: Any) -> dict[str, Any]:
    receipt: Mapping[str, Any] = loaded.receipt
    policy, reference = receipt["source_policy"], receipt["closes"]
    return {
        "storage": receipt["storage"], "storage_schema": receipt["storage_schema"],
        "consumer_version": receipt["consumer_version"],
        "source_policy": {"version": policy["version"], "sha256": policy["sha256"], "bytes": policy["bytes"]},
        "cutoff": loaded.cutoff, "closes_file": reference["file"], "closes_bytes": reference["bytes"],
        "closes_sha256": loaded.closes_sha256, "receipt_sha256": loaded.receipt_sha256, "saved_at": receipt["saved_at"],
        "calendar": {"source_version": receipt["trading_date_source_version"], "rows": receipt["calendar_rows"],
                     "window": {"start_date": receipt["window"]["start_date"], "end_date": receipt["window"]["end_date"]},
                     "timezone": "Asia/Taipei trading calendar date"},
        "adapter": {name: sha for name, sha in receipt["adapter"].items()},
        "attribution": receipt["attribution"],
        "rights": {name: text for name, text in receipt["rights"].items()},
        "publication_time": receipt["publication_time"], "first_availability": receipt["first_availability"],
        "revision_time": receipt["revision_time"], "historical_pit": "unsupported",
    }


def _project(loaded: Any, symbol: str) -> dict[str, Any]:
    rows = loaded.window(symbol, RETURN_CLOSES)
    dates = list(loaded.trading_dates)
    if (loaded.policy_version != source.POLICY_VERSION or loaded.cutoff != CUTOFF or not dates or dates[-1] != CUTOFF
            or len(rows) != RETURN_CLOSES or [close.date for close in rows] != dates[-RETURN_CLOSES:]):
        raise _Rejected("ordinary_close_window_mismatch")
    return {"closes": [_row(close) for close in rows], "values": derive_values(rows), "provenance": _provenance(loaded)}


def read_ordinary_close_trend(instrument: Any, as_of: date | None, *, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    """One explicit read of the saved bundle for one supported stock; failures carry reasons and no values."""
    result = _envelope(instrument, as_of)
    reason = _gate(instrument, as_of)
    if reason:
        result["reasons"] = [reason]
        return result
    try:
        root = source.configured_root(os.environ if environment is None else environment)
        loaded = source.load_saved_closes(root, source.POLICY_VERSION, CUTOFF)
        projection = _project(loaded, instrument.symbol)
    except source.SourceError as error:
        result["reasons"] = [_reason(error.code)]
        return result
    except _Rejected as error:
        result["reasons"] = [error.reason]
        return result
    except OSError:
        result["reasons"] = ["ordinary_close_storage_io_failed"]
        return result
    result.update(projection, status="available")
    result["read_state"]["verified"] = True
    return result
