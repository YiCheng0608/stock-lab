"""Private price save/read actions, separately enabled; no import I/O or network."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import os
from threading import Lock
from typing import Any, Mapping

from worker.tpex_price_capture import NEW_CUTOFF, SEVENTH_SCOPE_POLICY_VERSION, PriceCaptureError
from worker.tpex_price_storage import (CAPTURE_POLICY_DIGEST, STORAGE_POLICY_VERSION, STORAGE_POLICY_DIGEST,
    PriceStorageError, reopen_capture, save_capture, storage_policy, validate_storage_policy)
from . import tpex_price

VERSION = "stock-price-saved/m1-v1"
ENABLE_ENV = "STOCK_TPEX_PRICE_PRIVATE_STORE"
ROOT_ENV = "STOCK_TPEX_PRICE_PRIVATE_ROOT"
VERSION_ENV = "STOCK_TPEX_PRICE_PRIVATE_POLICY_VERSION"
DIGEST_ENV = "STOCK_TPEX_PRICE_PRIVATE_POLICY_DIGEST"
_LOCK = Lock()


def _base(instrument: Any, as_of: date | None, enabled: bool, action: str, reason: str | None = None) -> dict:
    return {"version": VERSION, "origin": "private_local", "status": "unavailable",
        "exchange": instrument.exchange, "symbol": instrument.symbol, "as_of": as_of.isoformat() if type(as_of) is date else None,
        "supported_scope": {**deepcopy(storage_policy()["scope"]), "symbols": list(storage_policy()["scope"]["symbols"])}, "unit": "shares", "quantity_encoding": "canonical_integer_string",
        "price_unit": "TWD_per_share", "latest": None, "bars": [], "provenance": None, "storage_provenance": None,
        "attribution": None, "historical_pit": "unsupported", "published_time": "unknown",
        "first_available_time": "unknown", "revision_time": "unknown", "limitations": storage_policy()["limitations"],
        "reasons": [reason] if reason else [], "storage_state": {"enabled": enabled, "action": action,
            "verified": False, "network_requests": 0}}


def _gate(instrument: Any, as_of: date | None, env: Mapping[str, str]) -> tuple[bool, str | None]:
    setting = env.get(ENABLE_ENV, "")
    if setting not in {"", "0", "1"}:
        return False, "price_private_configuration_invalid"
    enabled = setting == "1"
    if type(as_of) is not date or as_of != NEW_CUTOFF:
        return enabled, "price_saved_cutoff_not_supported"
    names = storage_policy()["scope"]["symbols"]
    if (instrument.exchange != "TPEx" or instrument.symbol not in names or instrument.name != names[instrument.symbol]
            or instrument.market != "TW" or instrument.instrument_type != "stock" or instrument.etf_category
            or getattr(instrument, "currency", "TWD") != "TWD"):
        return enabled, "price_saved_instrument_not_supported"
    if not enabled:
        return False, "price_private_store_not_enabled"
    if (env.get(VERSION_ENV), env.get(DIGEST_ENV)) != (STORAGE_POLICY_VERSION, STORAGE_POLICY_DIGEST):
        return True, "price_storage_policy_pins_mismatch"
    if (env.get(tpex_price.POLICY_VERSION_ENV), env.get(tpex_price.POLICY_DIGEST_ENV)) != (SEVENTH_SCOPE_POLICY_VERSION, CAPTURE_POLICY_DIGEST):
        return True, "price_storage_source_pins_mismatch"
    if not env.get(ROOT_ENV):
        return True, "price_storage_root_invalid"
    try:
        validate_storage_policy(storage_policy(), env[VERSION_ENV], env[DIGEST_ENV])
    except (PriceStorageError, PriceCaptureError) as exc:
        return True, str(exc)
    return True, None


def _project(result: dict, capture, receipt: dict, receipt_sha: str, action: str) -> dict:
    original = capture.receipt
    source = {**deepcopy(original), "receipt_sha256": hashlib.sha256(capture.receipt_bytes).hexdigest(),
        "verification": "private_raw_csv_selected_values", "raw_payload_id": None, "ingestion_run_id": None,
        "capture_id": "tpex-11370:" + capture.parsed["date"] + ":" + original["body_sha256"]}
    bar = {**deepcopy(capture.parsed["selected"][result["symbol"]]), "id": None, "origin": "private_local",
        "exchange": "TPEx", "source": "tpex", "currency": "TWD", "is_suspended": False, "adj_close": None,
        "data_as_of": capture.parsed["date"], "collected_at": original["captured_at"], "provenance": deepcopy(source)}
    result.update(status="available", latest=bar, bars=[deepcopy(bar)], provenance=source,
        storage_provenance={**deepcopy(receipt), "storage_receipt_sha256": receipt_sha}, attribution=deepcopy(original["attribution"]), reasons=[])
    result["storage_state"].update(action=action, verified=True)
    return result


def private_price(instrument: Any, as_of: date | None, *, save: bool = False, environment: Mapping[str, str] | None = None) -> dict:
    env = os.environ if environment is None else environment
    enabled, reason = _gate(instrument, as_of, env)
    result = _base(instrument, as_of, enabled, "not_attempted", reason)
    if reason:
        return result
    if not _LOCK.acquire(blocking=False):
        result["reasons"] = ["price_storage_busy"]
        result["storage_state"]["action"] = "busy"
        return result
    try:
        options = {"root": env[ROOT_ENV], "policy": storage_policy(), "expected_policy_version": env[VERSION_ENV], "expected_policy_digest": env[DIGEST_ENV]}
        if save:
            # This getter cannot call capture or increment a source request.
            capture = tpex_price.STORE.raw_capture
            if capture is None:
                raise PriceStorageError("price_saved_memory_capture_missing")
            captured, receipt, sha, action = save_capture(capture, **options)
        else:
            captured, receipt, sha = reopen_capture(**options)
            action = "reopened"
        return _project(result, captured, receipt, sha, action)
    except (PriceStorageError, PriceCaptureError) as exc:
        result["reasons"] = [str(exc)]
    except OSError:
        result["reasons"] = ["price_private_storage_io_failed"]
    finally:
        _LOCK.release()
    result["storage_state"]["action"] = "failed"
    return result
