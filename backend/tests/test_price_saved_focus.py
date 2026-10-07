"""Bounded memory contracts; never open the retained private product files.

Synthetic financial rows and mocked read seams are not source/disk acceptance.
The independently admitted consumer policy is never patched or weakened.
"""
from contextlib import nullcontext
from copy import deepcopy
import csv
from datetime import date
import hashlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import price_saved_focus as focus, tpex_price, tpex_price_saved as saved
from worker import tpex_price_capture as worker, tpex_price_storage as storage


def accepted_environment():
    p = focus.focus_policy()
    return {focus.ENABLE_ENV: "1", focus.VERSION_ENV: p["version"], focus.DIGEST_ENV: focus.POLICY_DIGEST,
        saved.ENABLE_ENV: "1", saved.ROOT_ENV: p["private_root"], saved.VERSION_ENV: p["storage_policy_version"],
        saved.DIGEST_ENV: p["storage_policy_digest"], tpex_price.ENABLE_ENV: "0",
        tpex_price.POLICY_VERSION_ENV: p["capture_policy_version"], tpex_price.POLICY_DIGEST_ENV: p["capture_policy_digest"]}


def synthetic_snapshot():
    p = focus.focus_policy()
    instruments = [SimpleNamespace(id=None, market="TW", exchange="TPEx", symbol=symbol, name=name,
        instrument_type="stock", currency="TWD", etf_category=None, is_watchlisted=False, status="active")
        for symbol, name in p["scope"]["symbols"].items()]
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(worker.HEADER)
    for item in instruments:
        opening, high, low, close, volume, amount = ("3125.00", "3140.00", "3050.00", "3055.00", "560518", "1729347985") if item.symbol == "6510" else (
            "100.00", "104.00", "99.00", "99.00" if item.symbol == "3105" else "100.00" if item.symbol == "5274" else "101.00", "1000000", "2000000000")
        writer.writerow(["1151006", item.symbol, item.name, close, "", opening, high, low, close, volume, amount, "1", "", "", "1", close, high, low])
    body = text.getvalue().encode("utf-8")
    parsed = worker.parse_price_csv(body, cutoff=focus.CUTOFF, policy_version=p["capture_policy_version"])
    receipt = {"source_version": "synthetic-memory-seven/2026-10-06", "captured_at": "2026-10-06T23:32:21.005311+00:00",
        "request_started_at": "2026-10-06T23:32:17.666931+00:00", "body_sha256": hashlib.sha256(body).hexdigest(),
        "attribution": storage.storage_policy()["attribution"], "storage": "process_memory", "selected_symbols": list(p["scope"]["symbols"])}
    capture = worker.PriceCapture(body, worker.canonical_bytes(receipt), parsed)
    stored = {"saved_at": p["validation"]["expected_saved_at"], "test_evidence": "synthetic_memory_only"}
    views = [saved._project(saved._base(item, focus.CUTOFF, True, "reopened"), capture, stored, "a" * 64, "reopened") for item in instruments]
    assert len(parsed["selected"]) == 7 and len(body) <= 80 * 1024
    assert focus.estimate_graph([capture.body, capture.receipt_bytes, views]) <= 512 * 1024
    return instruments, views, capture, stored


def synthetic_guard():
    guard = focus.SnapshotGuard()
    guard.estimated_bytes = 1024
    return guard


def memory_database_snapshot(fixture):
    """Independent pure read of all schema, values and per-cell SQLite types."""
    with fixture.engine.connect() as db:
        names = [row[0] for row in db.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        snapshot = {}
        for name in names:
            table = '"' + name.replace('"', '""') + '"'
            schema = [tuple(row) for row in db.exec_driver_sql('PRAGMA table_info(' + table + ')')]
            definitions = [tuple(row) for row in db.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name=? ORDER BY type,name", (name,))]
            columns = ['"' + row[1].replace('"', '""') + '"' for row in schema]
            snapshot[name] = {"schema": {"columns": schema, "definitions": definitions}, "values": [tuple(row) for row in db.exec_driver_sql('SELECT * FROM ' + table + ' ORDER BY rowid')],
                "cell_typeofs": [tuple(row) for row in db.exec_driver_sql('SELECT ' + ','.join('typeof(' + column + ')' for column in columns) + ' FROM ' + table + ' ORDER BY rowid')]}
        return snapshot


class SavedFocusMemoryTests(unittest.TestCase):
    def test_independent_immutable_admission_and_pre_io_gates(self):
        policy = focus.focus_policy()
        self.assertEqual(len(worker.canonical_bytes(policy)), 2677)
        self.assertEqual(worker.digest(policy), focus.POLICY_DIGEST)
        self.assertEqual(len(worker.canonical_bytes(storage.storage_policy())), 2437)
        original = worker.canonical_bytes(storage.storage_policy())
        damaged = deepcopy(policy); damaged["bounds"]["disk_writes"] = 1
        with self.assertRaises(storage.PriceStorageError):
            focus.validate_focus_policy(damaged, focus.POLICY_VERSION, focus.POLICY_DIGEST)
        instruments, _, _, _ = synthetic_snapshot()
        env = accepted_environment()
        variants = [({focus.ENABLE_ENV: "0"}, "price_saved_focus_not_enabled"),
            ({focus.ENABLE_ENV: "x"}, "price_saved_focus_configuration_invalid"),
            ({focus.VERSION_ENV: "wrong"}, "price_saved_focus_policy_pins_mismatch"),
            ({focus.DIGEST_ENV: "wrong"}, "price_saved_focus_policy_pins_mismatch"),
            ({saved.ROOT_ENV: policy["private_root"] + "-other"}, "price_saved_focus_root_not_admitted"),
            ({tpex_price.ENABLE_ENV: "1"}, "price_saved_focus_memory_capture_not_disabled"),
            ({saved.ENABLE_ENV: "0"}, "price_private_store_not_enabled"),
            ({saved.DIGEST_ENV: "bad"}, "price_storage_policy_pins_mismatch"),
            ({tpex_price.POLICY_DIGEST_ENV: "bad"}, "price_storage_source_pins_mismatch")]
        with patch.object(saved, "read_private_snapshot", side_effect=AssertionError("no private read admitted")):
            for changes, reason in variants:
                result = focus.build_saved_focus(instruments, focus.CUTOFF, "0", environment={**env, **changes})
                self.assertEqual(result["reasons"], [reason])
                self.assertEqual((result["count"], result["reads"], result["items"], result["consumer_provenance"]), (None, [], [], None))
                self.assertEqual(focus.read_saved_focus_stock(instruments[0], focus.CUTOFF, environment={**env, **changes})["reasons"], [reason])
            for cutoff in (None, date(2026, 10, 5), date(2026, 10, 7)):
                self.assertEqual(focus.build_saved_focus(instruments, cutoff, "0", environment=env)["reasons"], ["price_saved_focus_cutoff_not_supported"])
            for field, value in (("name", "wrong"), ("instrument_type", "etf"), ("exchange", "TWSE"), ("currency", "USD")):
                with patch.object(instruments[0], field, value):
                    self.assertEqual(focus.build_saved_focus(instruments, focus.CUTOFF, "0", environment=env)["reasons"], ["price_saved_focus_catalogue_not_supported"])
        self.assertEqual(worker.canonical_bytes(storage.storage_policy()), original)
        self.assertEqual(worker.digest(focus.focus_policy()), focus.POLICY_DIGEST)

    def test_four_exact_inclusive_rules_and_true_zero(self):
        instruments, views, _, _ = synthetic_snapshot()
        reads = [{"instrument": focus._instrument(item), "price_saved": view} for item, view in zip(instruments, views)]
        cases = [("0.000", "all", "0", "0.000", list(focus.focus_policy()["scope"]["symbols"])),
            ("560.518", "down", "1729347985", "2.880", ["3105", "6510"]),
            ("560.519", "down", "1729347985", "2.880", ["3105"]),
            ("560.518", "down", "1729347986", "2.880", ["3105"]),
            ("560.518", "down", "1729347985", "2.881", ["3105"]),
            ("0", "flat", "0", "0", ["5274"]), ("0", "all", "0", "10", [])]
        for lots, direction, amount, value_range, expected in cases:
            result = focus.derive_focus(reads, focus._base(focus.CUTOFF, lots, direction, amount, value_range))
            self.assertEqual([item["symbol"] for item in result["items"]], expected)
            self.assertEqual(result["count"], len(expected))
            self.assertEqual(result["status"], "available")
            if "6510" in expected:
                item = next(item for item in result["items"] if item["symbol"] == "6510")
                self.assertEqual((item["volume_exact"], item["volume_lots"], item["open_exact"], item["close_exact"]), ("560518", "560.518", "3125.00", "3055.00"))
                self.assertIn("source_mode=private_saved", item["detail_url"])
        wide = deepcopy(reads)
        bar = wide[0]["price_saved"]["latest"]
        bar["volume_exact"] = bar["source_fields"]["成交股數"] = "9007199254740993"
        wide[0]["price_saved"]["bars"] = [deepcopy(bar)]
        result = focus.derive_focus(wide, focus._base(focus.CUTOFF, "9007199254740.993", "all", "0", "0"))
        self.assertEqual([item["symbol"] for item in result["items"]], ["3105"])
        for name, value in (("parse_min_lots", "1.0001"), ("parse_min_lots", "01"), ("parse_min_turnover", "1.0"), ("parse_min_range_pct", "-1"), ("parse_day_move", "rise")):
            with self.assertRaises(ValueError):
                getattr(focus, name)(value)

    def test_missing_or_mixed_seventh_prevents_zero_or_partial_success(self):
        instruments, views, _, _ = synthetic_snapshot()
        variants = []
        missing = deepcopy(views); missing[-1]["latest"]["turnover_exact"] = None; missing[-1]["latest"]["source_fields"]["成交金額"] = ""; missing[-1]["latest"]["turnover_status"] = "unavailable"; variants.append(missing)
        mixed = deepcopy(views); mixed[-1]["storage_provenance"]["saved_at"] = "different"; variants.append(mixed)
        variants.append(views[:-1])
        for bad in variants:
            with patch.object(focus, "_read", return_value=(bad, synthetic_guard())):
                result = focus.build_saved_focus(instruments, focus.CUTOFF, "0", min_range_pct="10", environment=accepted_environment())
                self.assertEqual((result["status"], result["count"], result["reads"], result["items"], result["consumer_provenance"]), ("unavailable", None, [], [], None))
        with patch.object(focus, "_read", side_effect=OSError("synthetic connection-independent read failure")):
            result = focus.read_saved_focus_stock(instruments[0], focus.CUTOFF, environment=accepted_environment())
            self.assertIsNone(result["latest"]); self.assertEqual(result["bars"], []); self.assertIsNone(result["focus_consumer"])
        rejected_guard = SimpleNamespace(proof=lambda value: (_ for _ in ()).throw(storage.PriceStorageError("price_saved_focus_deadline_exceeded")))
        with patch.object(focus, "_read", return_value=([views[0]], rejected_guard)):
            result = focus.read_saved_focus_stock(instruments[0], focus.CUTOFF, environment=accepted_environment())
            self.assertEqual(result["status"], "unavailable")
            self.assertIsNone(result["latest"]); self.assertEqual(result["bars"], [])
            self.assertIsNone(result["provenance"]); self.assertIsNone(result["storage_provenance"]); self.assertIsNone(result["focus_consumer"])

    def test_deadline_exact_bytes_graph_and_shared_budget(self):
        moment = [0.0]
        guard = focus.SnapshotGuard(clock=lambda: moment[0])
        moment[0] = 10.0; guard.deadline()
        moment[0] = 10.001
        with self.assertRaisesRegex(storage.PriceStorageError, "deadline"):
            guard.bytes(b"synthetic", b"{}", b"{}")
        with self.assertRaisesRegex(storage.PriceStorageError, "deadline"):
            guard.parsed(None, {}, b"{}")
        guard = focus.SnapshotGuard()
        with self.assertRaisesRegex(storage.PriceStorageError, "snapshot_mismatch"):
            guard.bytes(b"synthetic", b"{}", b"{}")
        guard.estimated_bytes = 33554433
        with self.assertRaisesRegex(storage.PriceStorageError, "graph_bound"):
            guard.graph()
        with patch.object(focus, "_READ_COUNT", 95):
            focus.SnapshotGuard().start()
            self.assertEqual(focus.read_diagnostics()["snapshot_read_attempts"], 96)
            with self.assertRaisesRegex(storage.PriceStorageError, "read_budget"):
                focus.SnapshotGuard().start()

    def test_shared_snapshot_once_phase_order_and_release_without_disk(self):
        instruments, views, capture, stored = synthetic_snapshot()
        storage_bytes = worker.canonical_bytes(stored)
        events = []
        class VirtualPath:
            def __init__(self, name="root"): self.name = name
            def __truediv__(self, name): return VirtualPath(name)
            def exists(self): return True
            def iterdir(self): return [VirtualPath(name) for name in storage.FILES]
        def memory_read(path, cap):
            events.append(path.name)
            return {"body.csv": capture.body, "capture-receipt.json": capture.receipt_bytes, "storage-receipt.json": storage_bytes}[path.name]
        with patch.object(storage, "_root_scope", return_value=nullcontext(VirtualPath())) as root_scope, patch.object(storage, "_tree"), \
                patch.object(storage, "_hold_directory", side_effect=lambda path: nullcontext()), patch.object(storage, "_read", side_effect=memory_read) as reader, \
                patch.object(storage, "verified_capture", return_value=capture), patch.object(storage, "_receipt", return_value=stored):
            result = saved.read_private_snapshot(instruments, focus.CUTOFF, environment=accepted_environment(), on_start=lambda: events.append("start"),
                on_bytes=lambda *parts: events.append("bytes"), on_parsed=lambda *parts: events.append("parsed"))
            self.assertEqual(reader.call_count, 3)
            self.assertEqual(events, ["start", *storage.FILES, "bytes", "parsed"])
            self.assertEqual(len(result), 7)
            self.assertEqual([view["latest"]["symbol"] for view in result], [item.symbol for item in instruments])
            self.assertFalse(root_scope.call_args.kwargs["create"])
            with self.assertRaisesRegex(storage.PriceStorageError, "synthetic_guard_failure"):
                saved.read_private_snapshot(instruments, focus.CUTOFF, environment=accepted_environment(), on_start=lambda: None,
                    on_bytes=lambda *parts: (_ for _ in ()).throw(storage.PriceStorageError("synthetic_guard_failure")), on_parsed=lambda *parts: None)
        self.assertTrue(saved._LOCK.acquire(blocking=False)); saved._LOCK.release()
        self.assertIsNone(tpex_price.STORE.raw_capture)

    def test_actual_router_memory_contract_and_all_table_preservation(self):
        from fastapi.testclient import TestClient
        from test_tpex_price_api import MemoryAPIFixture
        instruments, views, _, _ = synthetic_snapshot()
        fixture = MemoryAPIFixture(live=True, cutoff=focus.CUTOFF, policy_version=focus.focus_policy()["capture_policy_version"])
        try:
            before = memory_database_snapshot(fixture)
            self.assertEqual(len(before), 19)
            with patch.dict(focus.os.environ, accepted_environment()), patch.object(focus, "_read", return_value=(views, synthetic_guard())) as reader, TestClient(fixture.app) as client:
                result = client.get("/api/focus/price-saved?as_of=2026-10-06&min_lots=560.518&day_move=down&min_turnover=1729347985&min_range_pct=2.880")
                self.assertEqual(result.status_code, 200)
                self.assertEqual([item["symbol"] for item in result.json()["items"]], ["3105", "6510"])
                for suffix in ("&min_lots=0", "&unknown=x", "&day_move=all", "&min_range_pct=1.0001"):
                    self.assertEqual(client.get("/api/focus/price-saved?as_of=2026-10-06&min_lots=1&day_move=down" + suffix).status_code, 422)
                for query in ("", "?as_of=bad&min_lots=0", "?as_of=2026-10-06&min_lots=-1"):
                    self.assertEqual(client.get("/api/focus/price-saved" + query).status_code, 422)
                count = reader.call_count
                for cutoff in ("2026-10-05", "2026-10-07"):
                    payload = client.get("/api/focus/price-saved?as_of=" + cutoff + "&min_lots=0").json()
                    self.assertEqual((payload["count"], payload["reads"]), (None, []))
                self.assertEqual(reader.call_count, count)
                self.assertEqual(client.get("/api/stocks/TPEx/6510/prices/saved-focus?as_of=2026-10-06&as_of=2026-10-06").status_code, 422)
                self.assertEqual(client.get("/api/stocks/TPEx/6510/prices/saved-focus?as_of=2026-10-06&unknown=1").status_code, 422)
                with patch.object(focus, "_read", return_value=([views[5]], synthetic_guard())):
                    stock = client.get("/api/stocks/TPEx/6510/prices/saved-focus?as_of=2026-10-06").json()
                    self.assertEqual(stock["latest"]["symbol"], "6510")
                    self.assertEqual(stock["focus_consumer"]["policy_digest"], focus.POLICY_DIGEST)
                self.assertEqual(client.get("/api/focus/price-lots?as_of=2026-10-06&min_lots=0").json()["status"], "unavailable")
            self.assertEqual(before, memory_database_snapshot(fixture))
            self.assertIsNone(fixture.store.raw_capture)
            self.assertEqual(fixture.store._request_count, 0)
            self.assertFalse(fixture.store._attempted)
        finally:
            fixture.close()
