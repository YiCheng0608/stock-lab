"""Finite, opt-in derivation of one retained private TPEx snapshot; no import I/O."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import os
import time
from typing import Any, Mapping
from urllib.parse import urlencode

from worker.tpex_price_capture import HEADER, canonical_bytes, digest
from worker.tpex_price_storage import PriceStorageError
from . import tpex_price, tpex_price_saved as saved
from .price_focus import (DAY_MOVE_REASONS, _identity, _instrument, exact_day_move, exact_day_range,
                          exact_turnover, lots_text, parse_day_move, parse_min_lots,
                          parse_min_range_pct, parse_min_turnover, range_meets_minimum)

VERSION = "price-saved-focus/m1-v1"
POLICY_VERSION = "m1-saved-price-focus-tpex-11370-2026-10-06.1"
# Accepted independently by ROOT before implementation. A computed digest is not admission.
POLICY_DIGEST = "sha256:93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b"
ENABLE_ENV = "STOCK_TPEX_PRICE_SAVED_FOCUS"
VERSION_ENV = "STOCK_TPEX_PRICE_SAVED_FOCUS_POLICY_VERSION"
DIGEST_ENV = "STOCK_TPEX_PRICE_SAVED_FOCUS_POLICY_DIGEST"
CUTOFF = date(2026, 10, 6)
MAX_READS = 96
_READ_COUNT = 0
_POLICY = json.loads(r'''{"version":"m1-saved-price-focus-tpex-11370-2026-10-06.1","profile":"free_public_local","purposes":["private_saved_read","local_derive_focus"],"projection_version":"price-saved-focus/m1-v1","origin":"private_local","private_root":"C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367","directory":"tpex-11370-2026-10-06-m1-v1","source_id":"tpex_11370_daily_close_csv","scope":{"exchange":"TPEx","asset_type":"stock","currency":"TWD","cutoff":"2026-10-06","symbols":{"3105":"穩懋","3293":"鈊象","5274":"信驊","5347":"世界","6488":"環球晶","6510":"精測","8069":"元太"}},"capture_policy_version":"m2-stock-scope-tpex-11370-2026-10-06.5","capture_policy_digest":"sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040","storage_policy_version":"m1-price-save-tpex-11370-2026-10-06.1","storage_policy_digest":"sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e","storage_receipt_version":"tpex-price-storage-receipt/m1-v1","saved_projection_version":"stock-price-saved/m1-v1","files":{"body.csv":{"bytes":1788599,"sha256":"ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200"},"capture-receipt.json":{"bytes":1461,"sha256":"871a6887a3b87bd7c23c20fc3a25ec98d369d0df2ed8eedbe8cb040e5242cd36"},"storage-receipt.json":{"bytes":1584,"sha256":"436465b4d13d604965327fe1be7eff98edf65274b0f16c7871474280feb0197b"}},"validation":{"structural":"all_rows_header_width_date_unique_date_code","financial":"selected_symbols_only","header_fields":18,"canonical_receipts":"exact_original_capture_and_storage_schema","expected_saved_at":"2026-10-06T23:32:45.499432+00:00","identity":"TW_TPEx_ordinary_stock_TWD_exact_seven"},"rules":{"quantity":"canonical_int64_shares_divide_1000","day_move":"compare_close_to_open_only","turnover":"canonical_int64_TWD_source_amount","range":"100_times_high_minus_low_divide_open","range_comparison":"100000_times_high_minus_low_gte_threshold_thousandths_times_open","thresholds":"inclusive","order":"code_ascending","filters":"as_of_min_lots_day_move_min_turnover_min_range_pct"},"bounds":{"max_raw_bytes":3145728,"max_capture_receipt_bytes":8192,"max_storage_receipt_bytes":16384,"max_bundle_bytes":3170304,"max_files":3,"max_bundles":1,"deadline_seconds":10,"max_retained_graph_bytes":33554432,"source_requests":0,"disk_writes":0,"db_mutations":0},"error_behavior":"unavailable_count_null_clear_values_no_fallback","limitations":["single_day_only","publication_first_available_revision_unknown","capture_saved_read_times_not_publication","historical_pit_unsupported","no_history_calendar_ma20_signal_or_plan","no_capture_hydrate_copy_export_publish_delete_or_new_disk_cases"]}''')


def focus_policy() -> dict:
    return deepcopy(_POLICY)


def validate_focus_policy(policy: dict, version: str, pin: str) -> None:
    if (policy != _POLICY or version != POLICY_VERSION or pin != POLICY_DIGEST
            or len(canonical_bytes(policy)) != 2677 or digest(policy) != POLICY_DIGEST):
        raise PriceStorageError("price_saved_focus_policy_pins_mismatch")


def read_diagnostics() -> dict:
    return {"snapshot_read_attempts": _READ_COUNT, "max_snapshot_reads": MAX_READS,
            "deadline_seconds": 10, "deadline_semantics": "cooperative_post_read_and_parse"}


def estimate_graph(value: Any, seen: set[int] | None = None) -> int:
    """Bounded retained-object estimate; neither RSS nor transient/peak measurement."""
    seen = set() if seen is None else seen
    if isinstance(value, bytes):
        return 64 + len(value)
    if isinstance(value, str):
        return 64 + 4 * len(value)
    if not isinstance(value, (dict, list, tuple)):
        return 32
    if id(value) in seen:
        return 0
    seen.add(id(value))
    children = [part for pair in value.items() for part in pair] if isinstance(value, dict) else value
    return 128 + sum(32 + estimate_graph(child, seen) for child in children)


class SnapshotGuard:
    def __init__(self, *, clock=time.monotonic):
        self.clock, self.started = clock, clock()
        self.estimated_bytes = 0

    def deadline(self):
        elapsed = self.clock() - self.started
        if not 0 <= elapsed <= _POLICY["bounds"]["deadline_seconds"]:
            raise PriceStorageError("price_saved_focus_deadline_exceeded")

    def start(self):
        global _READ_COUNT
        # The shared snapshot lock serializes this reservation; no retries.
        self.deadline()
        if _READ_COUNT >= MAX_READS:
            raise PriceStorageError("price_saved_focus_read_budget_exceeded")
        _READ_COUNT += 1

    def bytes(self, body: bytes, capture_bytes: bytes, storage_bytes: bytes):
        self.deadline()  # Cooperative after bounded file reads, never OS preemption.
        for name, value in zip(("body.csv", "capture-receipt.json", "storage-receipt.json"),
                               (body, capture_bytes, storage_bytes)):
            expected = _POLICY["files"][name]
            if type(value) is not bytes or len(value) != expected["bytes"] or hashlib.sha256(value).hexdigest() != expected["sha256"]:
                raise PriceStorageError("price_saved_focus_snapshot_mismatch")
        self.deadline()

    def parsed(self, capture, receipt: dict, storage_bytes: bytes):
        self.deadline()  # Full CSV and canonical-receipt parsing has completed.
        if (receipt.get("saved_at") != _POLICY["validation"]["expected_saved_at"]
                or capture.parsed.get("row_count") != 12194 or capture.parsed.get("date") != CUTOFF.isoformat()
                or set(capture.parsed.get("selected", {})) != set(_POLICY["scope"]["symbols"])):
            raise PriceStorageError("price_saved_focus_snapshot_mismatch")
        self.estimated_bytes = estimate_graph([capture.body, capture.receipt_bytes, capture.parsed, receipt, storage_bytes])
        self.graph()

    def graph(self, projection=None):
        size = self.estimated_bytes + (estimate_graph(projection) if projection is not None else 0)
        if size > _POLICY["bounds"]["max_retained_graph_bytes"]:
            raise PriceStorageError("price_saved_focus_graph_bound_exceeded")
        self.deadline()
        return size

    def proof(self, projection) -> dict:
        return {"policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST,
                "projection_version": VERSION, "origin": "private_local", "source_requests": 0,
                "disk_writes": 0, "db_mutations": 0, "deadline_seconds": 10,
                "deadline_semantics": "cooperative_post_read_and_parse",
                "retained_graph_estimated_bytes": self.graph(projection), "max_retained_graph_bytes": 33554432}


def _gate(as_of: date | None, env: Mapping[str, str]) -> str | None:
    if type(as_of) is not date or as_of != CUTOFF:
        return "price_saved_focus_cutoff_not_supported"
    if env.get(ENABLE_ENV, "") not in {"", "0", "1"}:
        return "price_saved_focus_configuration_invalid"
    if env.get(ENABLE_ENV) != "1":
        return "price_saved_focus_not_enabled"
    try:
        validate_focus_policy(focus_policy(), env.get(VERSION_ENV, ""), env.get(DIGEST_ENV, ""))
    except PriceStorageError as error:
        return str(error)
    # Literal path admission is separate from the existing Windows path-safety checks.
    if env.get(saved.ROOT_ENV, "").replace("\\", "/") != _POLICY["private_root"]:
        return "price_saved_focus_root_not_admitted"
    if env.get(tpex_price.ENABLE_ENV, "") != "0":
        return "price_saved_focus_memory_capture_not_disabled"
    if env.get(saved.ENABLE_ENV) != "1":
        return "price_private_store_not_enabled"
    if (env.get(saved.VERSION_ENV), env.get(saved.DIGEST_ENV)) != (_POLICY["storage_policy_version"], _POLICY["storage_policy_digest"]):
        return "price_storage_policy_pins_mismatch"
    if (env.get(tpex_price.POLICY_VERSION_ENV), env.get(tpex_price.POLICY_DIGEST_ENV)) != (_POLICY["capture_policy_version"], _POLICY["capture_policy_digest"]):
        return "price_storage_source_pins_mismatch"
    return None


def detail_path(symbol: str, as_of: str, min_lots: str, day_move: str, min_turnover: str, min_range_pct: str) -> str:
    return f"/stocks/TPEx/{symbol}?" + urlencode({"as_of": as_of, "from": "price-saved-focus",
        "source_mode": "private_saved", "focus_as_of": as_of, "focus_min_lots": min_lots,
        "focus_day_move": day_move, "focus_min_turnover": min_turnover, "focus_min_range_pct": min_range_pct})


def _base(as_of, min_lots, day_move, min_turnover, min_range_pct):
    return {"version": VERSION, "origin": "private_local", "status": "unavailable",
        "as_of": as_of.isoformat() if type(as_of) is date else None, "min_lots": min_lots,
        "min_shares": parse_min_lots(min_lots), "day_move": day_move, "min_turnover": min_turnover,
        "min_range_pct": min_range_pct, "count": None, "items": [], "reads": [],
        "supported_scope": {**deepcopy(_POLICY["scope"]), "symbols": list(_POLICY["scope"]["symbols"])},
        "consumer_provenance": None, "can_capture": False, "reasons": [], "historical_pit": "unsupported",
        "sort": "code_ascending", "limitations": list(_POLICY["limitations"])}


def _read(instruments, as_of, env):
    guard = SnapshotGuard()
    views = saved.read_private_snapshot(instruments, as_of, environment=env,
        on_start=guard.start, on_bytes=guard.bytes, on_parsed=guard.parsed)
    return views, guard


def derive_focus(reads: list[dict], result: dict) -> dict:
    """Pure derivation seam for bounded synthetic checks; no admission or I/O."""
    names = _POLICY["scope"]["symbols"]
    if len(reads) != 7 or [read.get("instrument", {}).get("symbol") for read in reads] != sorted(names):
        raise PriceStorageError("price_saved_focus_snapshot_invalid")
    views = [read.get("price_saved") for read in reads]
    for read, view in zip(reads, views):
        bar = view.get("latest") if isinstance(view, dict) else None
        fields = bar.get("source_fields") if isinstance(bar, dict) else None
        if (not isinstance(view, dict) or view.get("status") != "available" or view.get("origin") != "private_local"
                or view.get("version") != _POLICY["saved_projection_version"] or view.get("as_of") != result["as_of"]
                or not isinstance(bar, dict) or bar.get("date") != result["as_of"]
                or bar.get("symbol") != read["instrument"]["symbol"] or bar.get("origin") != "private_local"
                or read["instrument"].get("name") != names[bar["symbol"]]
                or not isinstance(fields, dict) or tuple(fields) != HEADER
                or fields.get("成交股數") != bar.get("volume_exact") or fields.get("資料日期") != "1151006"
                or fields.get("代號") != bar.get("symbol") or fields.get("名稱") != names[bar["symbol"]]
                or view.get("unit") != "shares" or view.get("quantity_encoding") != "canonical_integer_string"
                or view.get("price_unit") != "TWD_per_share" or view.get("bars") != [bar]
                or view.get("storage_state") != {"enabled": True, "action": "reopened", "verified": True, "network_requests": 0}):
            raise PriceStorageError("price_saved_focus_snapshot_invalid")
        try:
            parse_min_turnover(bar["volume_exact"])
        except (ValueError, KeyError) as error:
            raise PriceStorageError("price_saved_focus_volume_unavailable") from error
        if exact_day_move(bar) is None or exact_day_range(bar) is None or exact_turnover(bar) is None:
            raise PriceStorageError("price_saved_focus_financial_unavailable")
    if any(view.get("provenance") != views[0].get("provenance") or view.get("storage_provenance") != views[0].get("storage_provenance") for view in views[1:]):
        raise PriceStorageError("price_saved_focus_source_mismatch")
    minimum, range_minimum = result["min_shares"], parse_min_range_pct(result["min_range_pct"])
    items = []
    for read, view in zip(reads, views):
        bar = view["latest"]
        move, opening, closing = exact_day_move(bar)
        prices, amount = exact_day_range(bar), exact_turnover(bar)
        if (int(bar["volume_exact"]) >= int(minimum) and int(amount) >= int(result["min_turnover"])
                and (result["day_move"] == "all" or move == result["day_move"])
                and range_meets_minimum(prices, range_minimum)):
            symbol = bar["symbol"]
            items.append({"exchange": "TPEx", "symbol": symbol, "name": names[symbol],
                "volume_exact": bar["volume_exact"], "volume_lots": lots_text(bar["volume_exact"]),
                "min_lots": result["min_lots"], "min_shares": minimum, "min_turnover": result["min_turnover"],
                "turnover_exact": amount, "day_move": move, "open_exact": opening, "close_exact": closing,
                "min_range_pct": result["min_range_pct"], "high_exact": prices[1], "low_exact": prices[2],
                "reasons": ["volume_at_least_min_lots", "turnover_at_least_min_turnover", DAY_MOVE_REASONS[move], "range_at_least_min_range_pct"],
                "source_date": bar["date"], "source_version": view["provenance"]["source_version"],
                "detail_url": detail_path(symbol, result["as_of"], result["min_lots"], result["day_move"], result["min_turnover"], result["min_range_pct"])})
    result.update(status="available", count=len(items), items=items, reads=reads, reasons=[])
    return result


def build_saved_focus(instruments: list[Any], as_of: date, min_lots: str, day_move="all", min_turnover="0", min_range_pct="0", *, environment=None) -> dict:
    parse_day_move(day_move)
    parse_min_turnover(min_turnover)
    parse_min_range_pct(min_range_pct)
    result = _base(as_of, min_lots, day_move, min_turnover, min_range_pct)
    env = os.environ if environment is None else environment
    reason = _gate(as_of, env)
    names = _POLICY["scope"]["symbols"]
    if not reason and (len(instruments) != 7 or {getattr(item, "symbol", None) for item in instruments} != set(names)
                       or not all(_identity(item, names) for item in instruments)):
        reason = "price_saved_focus_catalogue_not_supported"
    if reason:
        result["reasons"] = [reason]
        return result
    try:
        instruments = sorted(instruments, key=lambda item: item.symbol)
        views, guard = _read(instruments, as_of, env)
        derive_focus([{"instrument": _instrument(item), "price_saved": view} for item, view in zip(instruments, views)], result)
        result["consumer_provenance"] = guard.proof(result)
        return result
    except (PriceStorageError, KeyError, TypeError, ValueError) as error:
        reason = str(error) if isinstance(error, PriceStorageError) else "price_saved_focus_snapshot_invalid"
    except OSError:
        reason = "price_private_storage_io_failed"
    result = _base(as_of, min_lots, day_move, min_turnover, min_range_pct)
    result["reasons"] = [reason]
    return result


def read_saved_focus_stock(instrument: Any, as_of: date | None, *, environment=None) -> dict:
    env = os.environ if environment is None else environment
    result = saved._base(instrument, as_of, env.get(ENABLE_ENV) == "1", "not_attempted")
    result["focus_consumer"] = None
    reason = _gate(as_of, env)
    if not reason and not _identity(instrument, _POLICY["scope"]["symbols"]):
        reason = "price_saved_focus_instrument_not_supported"
    if reason:
        result["reasons"] = [reason]
        return result
    try:
        views, guard = _read([instrument], as_of, env)
        result = views[0]
        result["focus_consumer"] = guard.proof(result)
        return result
    except (PriceStorageError, KeyError, TypeError, ValueError) as error:
        reason = str(error) if isinstance(error, PriceStorageError) else "price_saved_focus_snapshot_invalid"
    except OSError:
        reason = "price_private_storage_io_failed"
    # A post-projection deadline/graph failure must discard the projected values.
    result = saved._base(instrument, as_of, env.get(ENABLE_ENV) == "1", "failed")
    result["focus_consumer"] = None
    result["reasons"] = [reason]
    return result
