"""Explicit, single-attempt process-memory institutional window store.

Import and ordinary reads do not create files, import app.config, open a DB,
or fetch. The POST action is the only caller of the bounded W3 loader.
"""
from __future__ import annotations

from datetime import date
import os
from threading import Lock
from typing import Any, Mapping

from worker.tpex_institutional_window import MemoryWindowCache, window_policy

VERSION = "institutional-windows/w3-v1"
ENABLE_ENV = "STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE"
POLICY_VERSION = "m1-w3-tpex-window-2026-10-04.1"
POLICY_DIGEST = "sha256:9de27224cc57512f4e38455717eb51f8512eb890667119a5d02444810e0ad4db"
CALENDAR_VERSION = "tpex-2026-09-01_2026-10-02-weekdays-11503027221/v1"
CUTOFFS = (date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2))
SYMBOLS = ("3105", "6488")
SUPPORTED_SCOPE = {"exchange": "TPEx", "symbols": list(SYMBOLS), "supported_cutoffs": [day.isoformat() for day in CUTOFFS],
                   "calendar_from": "2026-09-01", "calendar_to": "2026-10-02"}


class InstitutionalWindowStore:
    def __init__(self, *, transport: Any = None):
        self._lock = Lock()
        self._attempted = False
        self._cache: MemoryWindowCache | None = None
        self._error: str | None = None
        self._transport = transport

    @property
    def raw_captures(self):
        return self._cache.raw_captures if self._cache else ()

    def _base(self, as_of: date | None, enabled: bool, reason: str | None, action: str) -> dict:
        busy = self._lock.locked()
        return {"version": VERSION, "status": "unavailable", "as_of": as_of.isoformat() if type(as_of) is date else None,
                "supported_scope": {**SUPPORTED_SCOPE, "symbols": list(SYMBOLS),
                                    "supported_cutoffs": list(SUPPORTED_SCOPE["supported_cutoffs"])}, "horizons": [5, 20],
                "investors": ["foreign", "trust", "dealer"], "values": None, "windows": {},
                "unit": "shares", "quantity_encoding": "canonical_integer_string", "historical_pit": "unsupported",
                "published_time": "unknown", "first_available_time": "unknown", "revision_time": "unknown",
                "storage": "process_memory", "reasons": [reason] if reason else [],
                "calendar": None, "policy": None, "calculation_version": None, "attribution": None,
                "provenance": None, "failures": [], "limitations": [],
                "capture_state": {"enabled": enabled, "attempted": self._attempted, "busy": busy,
                                  "can_capture": enabled and reason is None and not busy,
                                  "cache_present": bool(self.raw_captures), "action": action,
                                  "request_count": self._cache.request_count if self._cache else 0}}

    def _gate(self, exchange: str, symbol: str, as_of: date | None,
              environment: Mapping[str, str] | None) -> tuple[bool, str | None]:
        setting = (os.environ if environment is None else environment).get(ENABLE_ENV, "")
        if setting not in {"", "0", "1"}:
            return False, "window_capture_configuration_invalid"
        enabled = setting == "1"
        if exchange != "TPEx" or symbol not in SYMBOLS:
            return enabled, "window_market_or_symbol_not_supported"
        if not enabled:
            return False, "window_capture_not_enabled"
        if type(as_of) is not date or as_of not in CUTOFFS:
            return enabled, "window_cutoff_not_supported"
        return True, None

    def read(self, exchange: str, symbol: str, as_of: date | None, *,
             environment: Mapping[str, str] | None = None, action: str = "not_attempted") -> dict:
        enabled, reason = self._gate(exchange, symbol, as_of, environment)
        result = self._base(as_of, enabled, reason, action)
        if reason:
            return result
        if self._lock.locked():
            result["reasons"] = ["window_capture_busy"]
            result["capture_state"]["action"] = "busy"
            return result
        if self._error:
            result["reasons"] = [self._error]
            result["capture_state"]["action"] = "failed"
            return result
        if self._cache is None:
            result["reasons"] = ["window_memory_capture_missing"]
            return result
        try:
            snapshot = self._cache.get(exchange, symbol, as_of)
        except Exception:
            result["reasons"] = ["window_memory_evidence_invalid"]
            return result
        result.update(status=snapshot["status"], windows=snapshot["stocks"][symbol]["windows"],
                      calendar=snapshot.get("calendar"), policy=snapshot.get("policy"),
                      calculation_version=snapshot.get("calculation_version"), attribution=snapshot.get("attribution"),
                      reasons=snapshot["reasons"], failures=snapshot.get("failures", []),
                      limitations=snapshot.get("limitations", []), statistical_basis=snapshot.get("statistical_basis"),
                      provenance={"worker_version": snapshot["version"], "verification": snapshot.get("verification"),
                                  "captured_versions": snapshot.get("captured_versions", [])})
        result["capture_state"]["action"] = action if action != "not_attempted" else "cached"
        return result

    def capture(self, exchange: str, symbol: str, as_of: date | None, *,
                environment: Mapping[str, str] | None = None) -> dict:
        enabled, reason = self._gate(exchange, symbol, as_of, environment)
        if reason:
            return self._base(as_of, enabled, reason, "not_attempted")
        if not self._lock.acquire(blocking=False):
            return self._base(as_of, enabled, "window_capture_busy", "busy")
        action = "cached"
        try:
            if not self._attempted:
                self._attempted = True
                action = "acquired"
                try:
                    self._cache = MemoryWindowCache(policy=window_policy(), profile="free_public_local",
                                                    expected_policy_version=POLICY_VERSION,
                                                    expected_policy_digest=POLICY_DIGEST)
                    self._cache.load(as_of=as_of, calendar_version=CALENDAR_VERSION, transport=self._transport)
                except Exception:
                    self._error = "window_capture_failed"
                    action = "failed"
        finally:
            self._lock.release()
        return self.read(exchange, symbol, as_of, environment=environment, action=action)


STORE = InstitutionalWindowStore()


def build_institutional_windows(exchange: str, symbol: str, as_of: date | None) -> dict:
    return STORE.read(exchange, symbol, as_of)


def capture_institutional_windows(exchange: str, symbol: str, as_of: date | None) -> dict:
    return STORE.capture(exchange, symbol, as_of)
