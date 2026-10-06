"""Explicit single-attempt process-memory TPEx price store; reads/imports have no I/O."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import os
from threading import Lock
from typing import Any, Mapping

from worker.tpex_price_capture import CUTOFF, NEW_CUTOFF, APPROVED_CUTOFFS, ENDPOINT, SOURCE_ID, SYMBOLS, SCOPE_POLICY_VERSION, PriceCapture, PriceCaptureError, canonical_bytes, capture_price, parse_price_csv, price_policy, validate_policy, worker_version

VERSION = "stock-price-memory/m1-v1"
ENABLE_ENV = "STOCK_TPEX_PRICE_MEMORY_CAPTURE"
POLICY_VERSION_ENV = "STOCK_TPEX_PRICE_POLICY_VERSION"
POLICY_DIGEST_ENV = "STOCK_TPEX_PRICE_POLICY_DIGEST"
# Independently accepted by coordinator; never replace with a self-computed admission pin.
POLICY_VERSION = "m1-price-tpex-11370-2026-10-05.1"
POLICY_DIGEST = "sha256:452b9b8cfa3d050b79ea1a85b3e4ed643c40cf3d17882b8cb809ffdb7143deea"
POLICY_VERSION_20261006 = "m1-price-tpex-11370-2026-10-06.1"
POLICY_DIGEST_20261006 = "sha256:fc7b1451f6ae47145a5b40c3e08cdcad7ac8b9dafc64c7bf89f95c67cfefc288"
POLICY_DIGEST_STOCK_SCOPE = "sha256:6e662d5fc91957b586becdf41f351d5abf2c41cec09909de468e62e76cda4a78"


def policy_pins(cutoff: date, *, policy_version: str | None = None) -> tuple[str, str]:
    if type(cutoff) is not date or cutoff not in APPROVED_CUTOFFS:
        raise PriceCaptureError("price_cutoff_not_supported")
    version = price_policy(cutoff, policy_version=policy_version)["version"]
    if version == SCOPE_POLICY_VERSION:
        return version, POLICY_DIGEST_STOCK_SCOPE
    return (POLICY_VERSION, POLICY_DIGEST) if cutoff == CUTOFF else (POLICY_VERSION_20261006, POLICY_DIGEST_20261006)


def active_policy_version(cutoff: date | None, environment: Mapping[str, str] | None = None) -> str:
    """Select only a known tuple; invalid external pins still fail the Store gate."""
    day = cutoff if type(cutoff) is date and cutoff in APPROVED_CUTOFFS else CUTOFF
    env = os.environ if environment is None else environment
    requested = env.get(POLICY_VERSION_ENV) or None
    try:
        return price_policy(day, policy_version=requested)["version"]
    except PriceCaptureError:
        return price_policy(day)["version"]


def supported_symbols(cutoff: date | None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    day = cutoff if type(cutoff) is date and cutoff in APPROVED_CUTOFFS else CUTOFF
    return price_policy(day, policy_version=active_policy_version(day, environment))["scope"]["symbols"]


def projection_version(policy_version: str) -> str:
    return "stock-price-memory/m2-stock-scope-v1" if policy_version == SCOPE_POLICY_VERSION else VERSION


class TpexPriceStore:
    def __init__(self, *, loader=capture_price):
        self._lock = Lock()
        self._attempted = False
        self._capture: PriceCapture | None = None
        self._error: str | None = None
        self._request_count = 0
        self._loader = loader

    @property
    def raw_capture(self) -> PriceCapture | None:
        value = self._capture
        return PriceCapture(value.body, value.receipt_bytes, deepcopy(value.parsed)) if value else None

    @staticmethod
    def _validated_capture(value: PriceCapture, cutoff: date | None = None) -> PriceCapture:
        if not isinstance(value, PriceCapture):
            raise PriceCaptureError("price_memory_evidence_invalid")
        try:
            actual_date = date.fromisoformat(value.parsed["date"])
            cutoff = actual_date if cutoff is None else cutoff
            version, pin = policy_pins(cutoff, policy_version=value.receipt["policy_version"])
            policy = price_policy(cutoff, policy_version=version)
        except (KeyError, TypeError, ValueError) as error:
            raise PriceCaptureError("price_memory_evidence_invalid") from error
        if actual_date != cutoff:
            raise PriceCaptureError("price_memory_evidence_invalid")
        receipt = value.receipt
        required = {"worker_version": worker_version(cutoff, policy_version=version), "source_id": SOURCE_ID, "source_version": "tpex-11370/" + cutoff.isoformat(),
                    "endpoint": ENDPOINT, "method": "GET", "http_status": 200, "request_count": 1,
                    "body_sha256": policy["validation"]["expected_body_sha256"], "body_bytes": len(value.body),
                    "policy_version": version, "policy_digest": pin, "profile": "free_public_local",
                    "storage": "process_memory", "historical_pit": "unsupported", "selected_symbols": list(policy["scope"]["symbols"]),
                    "attribution": policy["attribution"], "limitations": policy["limitations"]}
        if any(receipt.get(key) != expected for key, expected in required.items()) or value.receipt_bytes != canonical_bytes(receipt):
            raise PriceCaptureError("price_memory_evidence_invalid")
        if hashlib.sha256(value.body).hexdigest() != receipt["body_sha256"]:
            raise PriceCaptureError("price_memory_evidence_invalid")
        try:
            start = datetime.fromisoformat(receipt["request_started_at"])
            end = datetime.fromisoformat(receipt["captured_at"])
            if start.utcoffset() != timezone.utc.utcoffset(start) or end.utcoffset() != timezone.utc.utcoffset(end) or not 0 <= (end - start).total_seconds() <= 30:
                raise ValueError()
        except (KeyError, TypeError, ValueError) as error:
            raise PriceCaptureError("price_memory_evidence_invalid") from error
        parsed = parse_price_csv(value.body, cutoff=cutoff, policy_version=version)
        if parsed != value.parsed or any(receipt.get(key) != parsed[key] for key in ("row_count", "structural_validation", "financial_validation")):
            raise PriceCaptureError("price_memory_evidence_invalid")
        return PriceCapture(value.body, value.receipt_bytes, deepcopy(parsed))

    def _gate(self, exchange: str, symbol: str, as_of: date | None, instrument_type: str, currency: str,
              environment: Mapping[str, str] | None) -> tuple[bool, str | None]:
        env = os.environ if environment is None else environment
        setting = env.get(ENABLE_ENV, "")
        enabled = setting == "1"
        if setting not in {"", "0", "1"}:
            return False, "price_capture_configuration_invalid"
        if exchange != "TPEx" or symbol not in supported_symbols(as_of, env) or instrument_type != "stock" or currency != "TWD":
            return enabled, "price_instrument_not_supported"
        if type(as_of) is not date or as_of not in APPROVED_CUTOFFS:
            return enabled, "price_cutoff_not_supported"
        if not enabled:
            return False, "price_capture_not_enabled"
        version, pin = policy_pins(as_of, policy_version=active_policy_version(as_of, env))
        if env.get(POLICY_VERSION_ENV) != version or env.get(POLICY_DIGEST_ENV) != pin:
            return True, "price_external_policy_pins_mismatch"
        try:
            validate_policy(price_policy(as_of, policy_version=version), version, pin)
        except ValueError:
            return True, "price_policy_pins_mismatch"
        return True, None

    def _base(self, exchange: str, symbol: str, as_of: date | None, enabled: bool, reason: str | None, action: str,
              environment: Mapping[str, str] | None = None) -> dict:
        busy = self._lock.locked()
        return {
            "version": projection_version(active_policy_version(as_of, environment)), "origin": "process_memory", "status": "unavailable",
            "exchange": exchange, "symbol": symbol, "as_of": as_of.isoformat() if type(as_of) is date else None,
            "supported_scope": {"exchange": "TPEx", "asset_type": "stock", "currency": "TWD",
                                "symbols": list(supported_symbols(as_of, environment)), "cutoff": as_of.isoformat() if type(as_of) is date and as_of in APPROVED_CUTOFFS else CUTOFF.isoformat()},
            "unit": "shares", "quantity_encoding": "canonical_integer_string", "price_unit": "TWD_per_share",
            "latest": None, "bars": [], "provenance": None, "attribution": None,
            "historical_pit": "unsupported", "published_time": "unknown", "first_available_time": "unknown", "revision_time": "unknown",
            "reasons": [reason] if reason else [], "limitations": list(price_policy()["limitations"]),
            "capture_state": {"enabled": enabled, "attempted": self._attempted, "busy": busy,
                              "can_capture": enabled and reason is None and not busy and not self._attempted,
                              "cache_present": self._capture is not None, "request_count": self._request_count, "action": action},
        }

    def read(self, exchange: str, symbol: str, as_of: date | None, *, instrument_type: str, currency: str,
             environment: Mapping[str, str] | None = None, action: str = "not_attempted") -> dict:
        enabled, reason = self._gate(exchange, symbol, as_of, instrument_type, currency, environment)
        result = self._base(exchange, symbol, as_of, enabled, reason, action, environment)
        if reason:
            return result
        if self._lock.locked():
            result["reasons"] = ["price_capture_busy"]
            result["capture_state"]["action"] = "busy"
            return result
        if self._error:
            result["reasons"] = [self._error]
            result["capture_state"]["action"] = "failed"
            return result
        if self._capture is None:
            result["reasons"] = ["price_memory_capture_missing"]
            return result
        capture = self._capture
        if capture.parsed["date"] != as_of.isoformat():
            result["reasons"] = ["price_memory_capture_date_mismatch"]
            return result
        receipt = capture.receipt
        if receipt["policy_version"] != active_policy_version(as_of, environment):
            result["reasons"] = ["price_memory_capture_policy_mismatch"]
            return result
        if hashlib.sha256(capture.body).hexdigest() != receipt["body_sha256"]:
            result["reasons"] = ["price_memory_evidence_invalid"]
            return result
        selected = deepcopy(capture.parsed["selected"][symbol])
        provenance = {
            **receipt, "receipt_sha256": hashlib.sha256(capture.receipt_bytes).hexdigest(),
            "verification": "pinned_raw_csv_selected_values", "raw_payload_id": None, "ingestion_run_id": None,
            "memory_capture_id": "tpex-11370:" + as_of.isoformat() + ":" + receipt["body_sha256"],
        }
        bar = {**selected, "id": None, "origin": "process_memory", "exchange": "TPEx", "source": "tpex",
               "currency": "TWD", "is_suspended": False, "adj_close": None, "data_as_of": selected["date"],
               "collected_at": receipt["captured_at"], "provenance": deepcopy(provenance)}
        result.update(status="available", latest=bar, bars=[deepcopy(bar)], provenance=provenance,
                      attribution=deepcopy(receipt["attribution"]), reasons=[])
        result["capture_state"]["action"] = action if action != "not_attempted" else "cached"
        return result

    def capture(self, exchange: str, symbol: str, as_of: date | None, *, instrument_type: str, currency: str,
                environment: Mapping[str, str] | None = None) -> dict:
        enabled, reason = self._gate(exchange, symbol, as_of, instrument_type, currency, environment)
        if reason:
            return self._base(exchange, symbol, as_of, enabled, reason, "not_attempted", environment)
        if not self._lock.acquire(blocking=False):
            return self._base(exchange, symbol, as_of, enabled, "price_capture_busy", "busy", environment)
        action = "cached"
        try:
            if not self._attempted:
                self._attempted = True
                action = "acquired"
                def on_request():
                    self._request_count += 1
                try:
                    version, pin = policy_pins(as_of, policy_version=active_policy_version(as_of, environment))
                    captured = self._loader(policy=price_policy(as_of, policy_version=version), expected_policy_version=version,
                                            expected_policy_digest=pin, on_request=on_request)
                    self._capture = self._validated_capture(captured, as_of)
                except PriceCaptureError as error:
                    self._error = str(error)
                    action = "failed"
                except Exception:
                    self._error = "price_capture_failed"
                    action = "failed"
        finally:
            self._lock.release()
        return self.read(exchange, symbol, as_of, instrument_type=instrument_type, currency=currency,
                         environment=environment, action=action)


STORE = TpexPriceStore()


def build_tpex_price(instrument: Any, as_of: date | None) -> dict:
    kind, currency = _instrument_scope(instrument, as_of)
    return STORE.read(instrument.exchange, instrument.symbol, as_of, instrument_type=kind, currency=currency)


def capture_tpex_price(instrument: Any, as_of: date | None) -> dict:
    kind, currency = _instrument_scope(instrument, as_of)
    return STORE.capture(instrument.exchange, instrument.symbol, as_of, instrument_type=kind, currency=currency)


def _instrument_scope(instrument: Any, as_of: date | None) -> tuple[str, str]:
    # The catalogue has no currency column. TWD is an accepted tuple-scoped policy
    # identity, admitted only after the exact TW ordinary-stock identity gate.
    identity_known = (instrument.market == "TW" and instrument.exchange == "TPEx"
                      and supported_symbols(as_of).get(instrument.symbol) == instrument.name
                      and instrument.instrument_type == "stock" and not instrument.etf_category
                      and getattr(instrument, "currency", "TWD") == "TWD")
    return ("stock", "TWD") if identity_known else ("unsupported", "unknown")
