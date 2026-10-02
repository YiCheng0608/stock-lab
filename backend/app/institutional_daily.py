"""Explicit local, read-only TPEx single-day evidence for the M1 overview.

Only server environment configuration chooses a capture path and expected date.
No discovery, latest-date inference, network, DB, extraction, or cache is used.
"""
from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import re
from typing import Mapping

from worker.source_registry import RegistryError
from worker.tpex_institutional_capture import (
    InstitutionalCaptureError, REGISTRY_PATH, summarize_capture,
)

VERSION = "institutional-daily/p2b-v1"
REGISTRY_VERSION = "m1-p2a-tpex-institutional-2026-10-03.1"
REGISTRY_DIGEST = "sha256:7ca17724e029c6a417dd2baa1981e6396d74772e977aecd1e823fde0e0090146"
PROFILE = "free_public_local"
CAPTURE_ENV = "STOCK_TPEX_INSTITUTIONAL_CAPTURE_ZIP"
DATE_ENV = "STOCK_TPEX_INSTITUTIONAL_CAPTURE_DATE"


def build_institutional_daily(exchange: str, symbol: str, as_of: date | None,
                              *, environment: Mapping[str, str] | None = None) -> dict:
    """Return one selected original row, with quantities encoded exactly as strings."""
    result = {
        "version": VERSION, "status": "unavailable", "as_of": as_of.isoformat() if type(as_of) is date else None,
        "date": None, "selection_basis": "explicit_configured_single_day", "unit": "shares",
        "quantity_encoding": "canonical_integer_string", "row": None, "provenance": None, "attribution": None,
        "historical_pit": "unsupported", "reasons": [],
        "session_windows": {"status": "unavailable", "horizons": [5, 20],
                            "reasons": ["trading_session_source_not_admitted", "multi_session_institutional_evidence_missing"]},
        "limitations": ["local_evidence_consistency_only", "selected_quantities_only", "complete_m1_not_delivered"],
    }
    def unavailable(reason: str) -> dict:
        result["reasons"] = [reason]
        return result

    # Market and cutoff gates run before even inspecting the configured path.
    if exchange != "TPEx":
        return unavailable("daily_exchange_not_supported")
    if type(as_of) is not date:
        return unavailable("daily_shared_cutoff_missing")
    if not isinstance(symbol, str) or re.fullmatch(r"[0-9A-Z]{4,6}", symbol) is None:
        return unavailable("daily_invalid_symbol")
    config = os.environ if environment is None else environment
    capture_path, expected_day = config.get(CAPTURE_ENV), config.get(DATE_ENV)
    if not capture_path and not expected_day:
        return unavailable("daily_capture_not_configured")
    if (not isinstance(capture_path, str) or not capture_path or capture_path != capture_path.strip()
            or not Path(capture_path).is_absolute() or not isinstance(expected_day, str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", expected_day) is None):
        return unavailable("daily_invalid_configuration")
    try:
        day = date.fromisoformat(expected_day)
    except ValueError:
        return unavailable("daily_invalid_configuration")
    if day > as_of:
        return unavailable("daily_after_cutoff")
    try:
        summary = summarize_capture(capture_path, manifest=REGISTRY_PATH, profile=PROFILE,
                                    expected_registry_version=REGISTRY_VERSION, expected_digest=REGISTRY_DIGEST,
                                    expected_date=day, symbols=[symbol])
    except (ValueError, RegistryError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        # Never disclose a server path or an OS exception in an HTTP response.
        reason = str(exc) if isinstance(exc, InstitutionalCaptureError) else "daily_evidence_invalid"
        if re.fullmatch(r"[a-z0-9_]+(?::[a-z0-9_]+)?", reason) is None:
            reason = "daily_evidence_invalid"
        return unavailable(reason)
    row = summary["rows"][0]
    row = {**row, "total_net": str(row["total_net"]),
           "investors": {key: {**values, **{field: str(values[field]) for field in ("buy", "sell", "net")}}
                         for key, values in row["investors"].items()}}
    result.update(status="available", date=day.isoformat(), row=row,
                  provenance=summary["provenance"], attribution=summary["attribution"],
                  candidate_count=summary["candidate_count"], validation_scope=summary["validation_scope"],
                  summarize_decision=summary["summarize_decision"],
                  runtime_condition_receipts=summary["runtime_condition_receipts"],
                  summary_condition_receipts=summary["summary_condition_receipts"])
    if day < as_of:
        result["reasons"] = ["daily_configured_date_before_cutoff"]
    return result
