"""Explicit 10/06 dispatcher and independent, pinned memory store.

Default/resolved dates and all old cutoffs retain the immutable W8 store.
Import/read do not import config, open a database, fetch or create files.
"""
from __future__ import annotations

from datetime import date
import os
from threading import Lock
from typing import Any, Mapping

from worker import tpex_institutional_1006 as worker
from . import institutional_windows as old

VERSION = "institutional-windows/chips-1006-v1"
SCHEMA_VERSION = "institutional-windows-read/chips-1006-v1"
ENABLE_ENV = "STOCK_TPEX_INSTITUTIONAL_1006_MEMORY_CAPTURE"
VERSION_ENV = "STOCK_TPEX_INSTITUTIONAL_1006_POLICY_VERSION"
DIGEST_ENV = "STOCK_TPEX_INSTITUTIONAL_1006_POLICY_DIGEST"


class InstitutionalWindowStore1006:
    def __init__(self, *, transport: Any = None, clock=None):
        self._lock = Lock()
        self._transport, self._clock = transport, clock
        self._attempted, self._cache, self._error = False, None, None

    @property
    def raw_captures(self):
        return self._cache.raw_captures if self._cache else ()

    def _gate(self, exchange, symbol, as_of, environment):
        env = os.environ if environment is None else environment
        setting = env.get(ENABLE_ENV, "")
        if setting not in {"", "0", "1"}:
            return False, "chips_capture_configuration_invalid"
        enabled = setting == "1"
        if exchange != "TPEx" or symbol not in worker.SYMBOLS:
            return enabled, "chips_market_or_symbol_not_supported"
        if type(as_of) is not date or as_of != worker.CUTOFF:
            return enabled, "chips_cutoff_not_supported"
        if not enabled:
            return False, "chips_capture_not_enabled"
        if env.get(VERSION_ENV) != worker.POLICY_VERSION or env.get(DIGEST_ENV) != worker.POLICY_DIGEST:
            return True, "chips_external_policy_pin_mismatch"
        return True, None

    def _base(self, exchange, symbol, as_of, enabled, reason, action):
        busy = self._lock.locked()
        return {"schema_version": SCHEMA_VERSION, "version": VERSION, "exchange": exchange, "symbol": symbol,
                "status": "unavailable", "as_of": as_of.isoformat() if type(as_of) is date else None,
                "supported_scope": worker.window_policy()["scope"], "horizons": [5, 20],
                "investors": ["foreign", "trust", "dealer"], "values": None, "windows": {},
                "unit": "shares", "quantity_encoding": "canonical_integer_string", "historical_pit": "unsupported",
                "published_time": "unknown", "first_available_time": "unknown", "revision_time": "unknown",
                "storage": "process_memory", "reasons": [reason] if reason else [], "calendar": None, "policy": None,
                "calculation_version": None, "attribution": None, "provenance": None, "failures": [], "limitations": [],
                "capture_state": {"enabled": enabled, "attempted": self._attempted, "busy": busy,
                                  "can_capture": enabled and reason is None and not busy,
                                  "cache_present": bool(self.raw_captures), "action": action,
                                  "request_count": self._cache.request_count if self._cache else 0}}

    def read(self, exchange, symbol, as_of, *, environment: Mapping[str, str] | None = None, action="not_attempted"):
        enabled, reason = self._gate(exchange, symbol, as_of, environment)
        result = self._base(exchange, symbol, as_of, enabled, reason, action)
        if reason:
            return result
        if self._lock.locked():
            result["reasons"], result["capture_state"]["action"] = ["chips_capture_busy"], "busy"
            return result
        if self._error:
            result["reasons"], result["capture_state"]["action"] = [self._error], "failed"
            return result
        if self._cache is None:
            result["reasons"] = ["chips_memory_capture_missing"]
            return result
        try:
            snapshot = self._cache.snapshot()
        except (ValueError, TypeError, KeyError, AttributeError):
            result["reasons"] = ["chips_memory_evidence_invalid"]
            return result
        result.update(status=snapshot["status"], windows=snapshot["stocks"][symbol]["windows"],
                      calendar=snapshot.get("calendar"), policy=snapshot.get("policy"),
                      calculation_version=snapshot.get("calculation_version"), attribution=snapshot.get("attribution"),
                      reasons=snapshot["reasons"], failures=snapshot.get("failures", []), limitations=snapshot.get("limitations", []),
                      statistical_basis=snapshot.get("statistical_basis"), memory_estimate=snapshot.get("memory_estimate"),
                      execution=snapshot.get("execution"), provenance={"worker_version": snapshot["version"],
                          "worker_schema_version": snapshot["schema_version"], "verification": snapshot.get("verification"),
                          "captured_versions": snapshot.get("captured_versions", [])})
        result["capture_state"]["action"] = action if action != "not_attempted" else "cached"
        return result

    def capture(self, exchange, symbol, as_of, *, environment: Mapping[str, str] | None = None):
        enabled, reason = self._gate(exchange, symbol, as_of, environment)
        if reason:
            return self._base(exchange, symbol, as_of, enabled, reason, "not_attempted")
        if not self._lock.acquire(blocking=False):
            return self._base(exchange, symbol, as_of, enabled, "chips_capture_busy", "busy")
        action = "cached"
        try:
            if not self._attempted:
                self._attempted = True
                action = "acquired"
                self._cache = worker.MemoryWindowCache1006(policy=worker.window_policy(), profile=worker.PROFILE,
                    expected_policy_version=worker.POLICY_VERSION, expected_policy_digest=worker.POLICY_DIGEST, clock=self._clock)
                try:
                    self._cache.load(as_of=as_of, calendar_version=worker.CALENDAR_VERSION, transport=self._transport)
                except Exception:
                    self._error, action = "chips_capture_failed", "failed"
        finally:
            self._lock.release()
        return self.read(exchange, symbol, as_of, environment=environment, action=action)


STORE = InstitutionalWindowStore1006()


def build_institutional_windows(exchange, symbol, as_of, *, explicit_as_of=None):
    if type(explicit_as_of) is date and explicit_as_of == worker.CUTOFF:
        return STORE.read(exchange, symbol, as_of)
    return old.build_institutional_windows(exchange, symbol, as_of)


def capture_institutional_windows(exchange, symbol, as_of, *, explicit_as_of=None):
    if type(explicit_as_of) is date and explicit_as_of == worker.CUTOFF:
        return STORE.capture(exchange, symbol, as_of)
    return old.capture_institutional_windows(exchange, symbol, as_of)
