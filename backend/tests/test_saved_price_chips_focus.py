"""New joint predicate checks; pure fixture builders, zero old suites/actual I/O."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
import unittest
from unittest.mock import patch

import httpx
from app import saved_price_chips_focus as joint, saved_price_chips_entry as old_entry
from app import price_saved_focus as saved_focus, institutional_windows_1006 as windows
from worker import tpex_institutional_1006 as chips
from test_price_saved_focus import synthetic_snapshot, synthetic_guard, accepted_environment
from test_saved_price_chips_entry import synthetic_captures


def inputs(**changes):
    return {"as_of": "2026-10-06", "min_lots": "0.000", "day_move": "all", "min_turnover": "0",
            "min_range_pct": "0.000", "investor": "foreign", "horizon": "5", "min_net_lots": "0.000", **changes}


def environment():
    return {**accepted_environment(), joint.ENABLE_ENV: "1", joint.VERSION_ENV: joint.POLICY_VERSION,
            joint.DIGEST_ENV: joint.POLICY_DIGEST, joint.JOINT_VERSION_ENV: old_entry.POLICY_VERSION,
            joint.JOINT_DIGEST_ENV: old_entry.POLICY_DIGEST, windows.ENABLE_ENV: "1",
            windows.VERSION_ENV: chips.POLICY_VERSION, windows.DIGEST_ENV: chips.POLICY_DIGEST}


@contextmanager
def fixture(failure=False):
    import __main__ as runner
    pin = joint.focus_policy()["independent_pins"]["price_capture"]
    with patch.object(runner.ARGS, "policy_version", pin["policy_version"]), patch.object(runner.ARGS, "policy_digest", "sha256:" + pin["sha256"]):
        current = runner.saved_consumer_fixture()
    instruments, views, raw_price, _ = synthetic_snapshot()
    captures, raw_bytes, _ = synthetic_captures()
    bodies, requests, reads = {item.url: item.body for item in captures}, [], []
    def handler(request):
        target = str(request.url)
        assert target in bodies and target not in requests
        requests.append(target)
        return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"}, stream=httpx.ByteStream(b"bad\n" if failure else bodies[target]))
    store = windows.InstitutionalWindowStore1006(transport=httpx.MockTransport(handler))
    def fake_read(items, as_of, env):
        assert len(items) == 7 and as_of == date(2026, 10, 6)
        reads.append(as_of)
        guard = synthetic_guard(); guard.start()
        return deepcopy(views), guard
    state = joint.ConsumerState()
    current.stack.enter_context(patch.object(joint, "STATE", state))
    current.stack.enter_context(patch.object(windows, "STORE", store))
    current.stack.enter_context(patch.dict(os.environ, environment()))
    current.stack.enter_context(patch.object(saved_focus, "_READ_COUNT", 0))
    current.stack.enter_context(patch.object(saved_focus, "MAX_READS", 61))
    current.stack.enter_context(patch.object(saved_focus, "_read", fake_read))
    current.chips_store, current.source_requests, current.private_reads = store, requests, reads
    current.instruments = instruments
    current.before_full = runner.database_snapshot(current)
    joint.install_request_gate(current.app)
    fixture_bytes = raw_bytes + len(raw_price.body)
    input_graph = chips.retained_graph_estimate((captures, raw_price.body, views))
    assert fixture_bytes <= 81920 and input_graph <= 524288
    try:
        yield current
        assert current.before_full == runner.database_snapshot(current)
        assert not current.store._attempted and not current.store.raw_capture
    finally:
        current.close()
    print(json.dumps({"synthetic_input_serialized_bytes": fixture_bytes, "synthetic_input_graph_estimated_bytes": input_graph,
                      "max_serialized_bytes": 81920, "max_graph_estimated_bytes": 524288, "actual_private_reads": 0, "actual_source_get": 0}))


class JointFocusTests(unittest.TestCase):
    def test_current_generation_only_unlocks_first_source_after_slow_success(self):
        from threading import Event, Thread
        with fixture() as current:
            entered, release = Event(), Event()
            import app.price_saved_focus as price
            original = price.build_saved_focus
            result = []
            def slow(*args, **kwargs):
                entered.set(); self.assertTrue(release.wait(2))
                return original(*args, **kwargs)
            with patch.object(price, "build_saved_focus", slow):
                thread = Thread(target=lambda: result.append(joint.build_focus(current.instruments, inputs())))
                thread.start(); self.assertTrue(entered.wait(2))
                joint.STATE.observe()  # A newer rejected/unsupported request invalidates the ticket.
                release.set(); thread.join(2); self.assertFalse(thread.is_alive())
            self.assertFalse(joint.STATE.price_ready)
            self.assertEqual(result[0]["reasons"], ["joint_focus_stale_consumer"])
            self.assertEqual(joint.request_error("POST", "/api/stocks/TPEx/3105/institutional-windows/capture", "as_of=2026-10-06", b"{}")[0], 409)
            joint.build_focus(current.instruments, inputs())
            self.assertTrue(joint.STATE.price_ready)

    def test_exact_root_policy_all_five_external_pins_and_parser_bounds(self):
        policy = joint.focus_policy(); encoded = joint.canonical_bytes(policy)
        self.assertEqual(len(encoded), 14399)
        self.assertEqual("sha256:" + hashlib.sha256(encoded).hexdigest(), joint.POLICY_DIGEST)
        pins = {key: (value["policy_version"], "sha256:" + value["sha256"]) for key, value in policy["independent_pins"].items()}
        joint.validate_admission(joint.POLICY_VERSION, joint.POLICY_DIGEST, pins)
        for key in pins:
            with self.assertRaises(ValueError): joint.validate_admission(joint.POLICY_VERSION, joint.POLICY_DIGEST, {**pins, key: (pins[key][0], "sha256:" + "0" * 64)})
        for raw, expected in (("0", "0"), ("0.000", "0"), ("-0.001", "-1"), ("1.010", "1010"), ("-9223372036854775.808", "-9223372036854775808"), ("9223372036854775.807", "9223372036854775807")):
            self.assertEqual(joint.parse_net_lots(raw), expected)
        for raw in ("-0", "-0.0", "-0.00", "-0.000", "+1", "01", "1,000", "1e2", " 1", "1 ", "1.0000", "9223372036854775.808", "-9223372036854775.809"):
            with self.assertRaises(ValueError): joint.parse_net_lots(raw)

    def test_router_readiness_exact_eight_pre_io_refusals_and_separate_capture(self):
        async def run(current):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=current.app), base_url="http://test") as client:
                capture = "/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06"
                self.assertEqual((await client.post(capture, json={})).status_code, 409)
                for params in ({**inputs(), "extra": "1"}, {**inputs(), "min_net_lots": "-0.000"}, {**inputs(), "horizon": "05"}):
                    self.assertEqual((await client.get("/api/focus/price-saved-chips", params=params)).status_code, 422)
                duplicate = list(inputs().items()) + [("investor", "foreign")]
                self.assertEqual((await client.get("/api/focus/price-saved-chips", params=duplicate)).status_code, 422)
                unsupported = (await client.get("/api/focus/price-saved-chips", params=inputs(as_of="2026-10-05"))).json()
                self.assertEqual((unsupported["status"], unsupported["count"], unsupported["items"]), ("unavailable", None, []))
                self.assertEqual(current.private_reads, [])
                self.assertEqual(current.source_requests, [])
                progress = (await client.get("/api/focus/price-saved-chips", params=inputs(min_lots="999999"))).json()
                self.assertTrue(progress["price_ready"] and progress["can_capture"])
                self.assertEqual((progress["count"], progress["items"], progress["price"], progress["institutional"]), (None, [], None, []))
                self.assertEqual(len(current.private_reads), 1)
                acquired = await client.post(capture, json={})
                self.assertEqual(acquired.json()["status"], "available")
                self.assertEqual(len(current.source_requests), 22)
                self.assertEqual(len(current.private_reads), 1, "capture completion cannot read private files")
                answer = (await client.get("/api/focus/price-saved-chips", params=inputs())).json()
                self.assertEqual((answer["status"], answer["count"], [item["symbol"] for item in answer["items"]]), ("available", 2, ["3105", "6488"]))
                self.assertEqual(len(current.private_reads), 2)
                self.assertEqual(len(current.source_requests), 22)
                self.assertEqual(len(list(__import__('urllib.parse', fromlist=['parse_qsl']).parse_qsl(answer['items'][0]['detail_url'].split('?')[1]))), 11)
        with fixture() as current: asyncio.run(run(current))

    def test_all_six_signed_inclusive_projections_zero_and_corrupt_other_stock(self):
        with fixture() as current:
            first = joint.build_focus(current.instruments, inputs())
            self.assertIsNone(first["count"])
            current.chips_store.capture("TPEx", "3105", chips.CUTOFF)
            full = joint.build_focus(current.instruments, inputs())
            self.assertEqual(full["count"], 2)
            for investor in ("foreign", "trust", "dealer"):
                for horizon in ("5", "20"):
                    shares = int(full["institutional"][0]["windows"][horizon]["values"][investor])
                    raw = ("-" if shares < 0 else "") + f"{abs(shares)//1000}.{abs(shares)%1000:03d}"
                    result = joint.build_focus(current.instruments, inputs(investor=investor, horizon=horizon, min_net_lots=raw))
                    self.assertEqual(result["count"], 2)
                    above = shares + 1
                    raw_above = ("-" if above < 0 else "") + f"{abs(above)//1000}.{abs(above)%1000:03d}"
                    self.assertEqual(joint.build_focus(current.instruments, inputs(investor=investor, horizon=horizon, min_net_lots=raw_above))["count"], 0)
            broken = deepcopy(full["institutional"])
            broken[1]["windows"]["20"]["values"]["foreign"] = "0"
            with self.assertRaises(ValueError): joint.project(full["price"], broken, inputs(min_lots="999999"))
            bad_price = deepcopy(full["price"]); bad_price["reads"].pop()
            with self.assertRaises(ValueError): joint.project(bad_price, full["institutional"], inputs())
            self.assertEqual(len(current.source_requests), 22)

    def test_failed_capture_no_retry_and_unavailable_after_full_price(self):
        with fixture(failure=True) as current:
            joint.build_focus(current.instruments, inputs())
            current.chips_store.capture("TPEx", "3105", chips.CUTOFF)
            count = len(current.source_requests)
            failed = joint.build_focus(current.instruments, inputs())
            self.assertEqual((failed["count"], failed["items"], failed["price"], failed["institutional"]), (None, [], None, []))
            self.assertFalse(joint.STATE.price_ready)
            current.chips_store.capture("TPEx", "6488", chips.CUTOFF)
            self.assertEqual(len(current.source_requests), count)

    def test_shared_private_read_budget_and_diagnostic_no_read(self):
        with patch.object(saved_focus, "MAX_READS", 61), patch.object(saved_focus, "_READ_COUNT", 60):
            saved_focus.SnapshotGuard().start()
            with self.assertRaises(ValueError): saved_focus.SnapshotGuard().start()
        self.assertEqual(old_entry.PRODUCER_READ_LIMIT + old_entry.ROOT_OBSERVATION_RESERVE, 64)
        with fixture() as current:
            before = list(current.private_reads)
            self.assertFalse(joint.STATE.diagnostic()["price_ready"])
            self.assertEqual(current.private_reads, before)
