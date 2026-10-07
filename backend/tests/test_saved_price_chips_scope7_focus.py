"""New joint seven-stock consumer tests; all finance bodies and private seams are synthetic."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import json
import os
from threading import Event, Thread
import unittest
from unittest.mock import patch
import httpx
from app import saved_price_chips_scope7_focus as joint, saved_price_chips_scope7_entry as entry
from app import price_saved_focus as saved_focus, institutional_windows_1006_scope7 as windows
from worker import tpex_institutional_1006_scope7 as chips
from test_price_saved_focus import synthetic_snapshot, synthetic_guard, accepted_environment
from test_tpex_institutional_1006_scope7 import synthetic_captures

def inputs(**changes):
    return {"as_of": "2026-10-06", "min_lots": "0.000", "day_move": "all", "min_turnover": "0",
        "min_range_pct": "0.000", "investor": "foreign", "horizon": "5", "min_net_lots": "0.000", **changes}

def environment():
    return {**accepted_environment(), joint.ENABLE_ENV: "1", joint.VERSION_ENV: joint.POLICY_VERSION,
        joint.DIGEST_ENV: joint.POLICY_DIGEST, joint.JOINT_VERSION_ENV: entry.POLICY_VERSION,
        joint.JOINT_DIGEST_ENV: entry.POLICY_DIGEST, windows.ENABLE_ENV: "1",
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
        assert request.method == "GET" and request.content == b"" and target in bodies and target not in requests
        requests.append(target)
        return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"},
            stream=httpx.ByteStream(b"bad\n" if failure else bodies[target]))
    store = windows.InstitutionalWindowStore1006Scope7(transport=httpx.MockTransport(handler))
    def fake_read(items, as_of, env):
        assert as_of == date(2026, 10, 6)
        reads.append(as_of)
        guard = synthetic_guard()
        guard.start()
        return deepcopy(views), guard
    current.stack.enter_context(patch.object(joint, "STATE", joint.ConsumerState()))
    current.stack.enter_context(patch.object(windows, "STORE", store))
    current.stack.enter_context(patch.dict(os.environ, environment()))
    current.stack.enter_context(patch.object(saved_focus, "_READ_COUNT", 0))
    current.stack.enter_context(patch.object(saved_focus, "MAX_READS", entry.PRODUCER_READ_LIMIT))
    current.stack.enter_context(patch.object(saved_focus, "_read", fake_read))
    current.chips_store, current.source_requests, current.private_reads = store, requests, reads
    current.instruments = instruments
    current.before_full = runner.database_snapshot(current)
    joint.install_request_gate(current.app)
    serialized = raw_bytes + len(raw_price.body)
    graph = chips.retained_graph_estimate((captures, raw_price.body, views))
    assert serialized <= 81920 and graph <= 524288, (serialized, graph)
    try:
        yield current
        assert current.before_full == runner.database_snapshot(current)
        assert not current.store._attempted and current.store.raw_capture is None
    finally:
        current.close()
    print(json.dumps({"synthetic_input_serialized_bytes": serialized, "synthetic_input_graph_estimated_bytes": graph,
        "max_serialized_bytes": 81920, "max_graph_estimated_bytes": 524288,
        "memory_database_tables": len(current.before_full), "all_schema_index_trigger_values_cell_typeofs_preserved": True,
        "actual_private_reads": 0, "actual_source_get": 0}))

def loaded(current):
    joint.build_focus(current.instruments, inputs())
    current.chips_store.capture("TPEx", "3105", date(2026, 10, 6))

class Scope7FocusTests(unittest.TestCase):
    def test_normal_router_rejects_streamed_body_before_db_and_consumer(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from fastapi import FastAPI
        from app import api

        application = FastAPI()
        application.include_router(api.router)
        databases, consumers, private, source, chunks = [], [], [], [], []
        def database():
            databases.append(True)
            return SimpleNamespace(no_autoflush=nullcontext(),
                scalars=lambda statement: SimpleNamespace(all=lambda: []))
        def consumer(instruments, values):
            consumers.append(values)
            return {"normal_router": True}
        def no_private(*args, **kwargs):
            private.append(True)
            raise AssertionError("normal-router rejected body must not read private data")
        def no_source(*args, **kwargs):
            source.append(True)
            raise AssertionError("normal-router rejected body must not request a source")
        application.dependency_overrides[api.get_db] = database
        async def stream():
            for ordinal, value in enumerate((b"", b"x", b"unread-tail")):
                chunks.append(ordinal)
                yield value
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://owned.invalid") as client:
                path = "/api/focus/price-saved-chips-stock-scope-7"
                for body in (b"{}", b" ", b"x" * 1024):
                    result = await client.request("GET", path, params=inputs(), content=body)
                    self.assertEqual(result.status_code, 422)
                    self.assertEqual(result.json()["detail"], "joint_focus_empty_get_body_required")
                result = await client.request("GET", path, params=inputs(), content=stream())
                self.assertEqual(result.status_code, 422)
                self.assertEqual(chunks, [0, 1])
                self.assertEqual((databases, consumers, private, source), ([], [], [], []))
                for query in (list(inputs().items()) + [("investor", "foreign")],
                              list(inputs().items()) + [("unknown", "1")],
                              inputs(investor="unknown"), inputs(min_net_lots="-0.000"),
                              inputs(min_net_lots="+1"), inputs(min_net_lots="1 ")):
                    invalid = await client.get(path, params=query)
                    self.assertEqual(invalid.status_code, 422)
                    self.assertEqual((databases, consumers, private, source), ([], [], [], []))
                empty = await client.get(path, params=inputs())
                self.assertEqual(empty.status_code, 200)
                self.assertEqual(empty.json(), {"normal_router": True})
                self.assertEqual((len(databases), len(consumers), private, source), (1, 1, [], []))
        with patch.object(joint, "STATE", joint.ConsumerState()), patch.object(joint, "build_focus", consumer), \
                patch.object(saved_focus, "_read", no_private), patch.object(chips.MemoryWindowCache1006Scope7, "load", no_source):
            asyncio.run(run())

    def test_external_pins_and_shared_read_bounds(self):
        self.assertEqual(len(joint.canonical_bytes(joint.focus_policy())), 17021)
        self.assertEqual(len(entry.canonical_bytes(entry.entry_policy())), 13404)
        pins = {key: (pin["policy_version"], "sha256:" + pin["sha256"]) for key, pin in joint.focus_policy()["independent_pins"].items()}
        joint.validate_admission(joint.POLICY_VERSION, joint.POLICY_DIGEST, pins)
        self.assertEqual(entry.PRODUCER_READ_LIMIT, 26)
        bounds = joint.focus_policy()["private_use"]["bounds"]
        self.assertEqual((bounds["inherited_bundle_reads"], bounds["new_bundle_read_limit"], bounds["producer_new_snapshot_limit"], bounds["root_new_snapshot_limit"]), (35, 29, 26, 3))
        with patch.object(saved_focus, "_READ_COUNT", 25), patch.object(saved_focus, "MAX_READS", 26):
            synthetic_guard().start()
            with self.assertRaises(ValueError):
                synthetic_guard().start()
            self.assertEqual(saved_focus._READ_COUNT, 26)

    def test_matching_verified_zero_signed_inclusive_and_complete_gate(self):
        with fixture() as current:
            first = joint.build_focus(current.instruments, inputs())
            self.assertTrue(first["price_ready"])
            self.assertIsNone(first["count"])
            self.assertEqual(len(current.source_requests), 0)
            current.chips_store.capture("TPEx", "3105", date(2026, 10, 6))
            data = joint.build_focus(current.instruments, inputs())
            self.assertEqual([item["symbol"] for item in data["items"]], list(chips.SYMBOLS))
            for investor in ("foreign", "trust", "dealer"):
                for horizon in ("5", "20"):
                    net = int(data["institutional"][0]["windows"][horizon]["values"][investor])
                    lots = ("-" if net < 0 else "") + f"{abs(net)//1000}.{abs(net)%1000:03d}"
                    same = joint.build_focus(current.instruments, inputs(investor=investor, horizon=horizon, min_net_lots=lots))
                    self.assertEqual(same["count"], 7)
            zero = joint.build_focus(current.instruments, inputs(min_net_lots="1000000.000"))
            self.assertEqual((zero["status"], zero["count"], zero["items"]), ("available", 0, []))
            broken = deepcopy(data["institutional"])
            broken[1]["calendar"]["original_rows"][-1]["source_values"]["開市"] = "NaN"
            with self.assertRaises(ValueError):
                joint.project(data["price"], broken, inputs(min_lots="1000000.000"))
            broken = deepcopy(data["institutional"])
            broken[1]["windows"]["20"]["daily_evidence"][-1]["row"]["source_values"][chips.DAILY_HEADER[6]] = "9"
            with self.assertRaises(ValueError):
                joint.project(data["price"], broken, inputs())
            self.assertEqual(len(current.source_requests), 22)

    def test_router_three_actions_precapture_duplicate_body_and_unavailable(self):
        async def run(current):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=current.app), base_url="http://owned.invalid") as client:
                path = "/api/focus/price-saved-chips-stock-scope-7"
                post = "/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06"
                self.assertEqual((await client.post(post, content=b"{}")).status_code, 409)
                for query in [inputs(as_of="2026-10-07"), inputs(as_of="2026-10-05")]:
                    result = await client.get(path, params=query)
                    self.assertEqual(result.status_code, 200)
                    self.assertIsNone(result.json()["count"])
                self.assertEqual(len(current.private_reads), 0)
                for suffix in ("&unknown=1", "&investor=foreign"):
                    self.assertEqual((await client.get(path + "?" + str(httpx.QueryParams(inputs())) + suffix)).status_code, 422)
                self.assertEqual((await client.request("GET", path, params=inputs(), content=b"{}")).status_code, 422)
                self.assertEqual((await client.get("/api/focus/price-saved-chips", params=inputs())).status_code, 405)
                initial = (await client.get(path, params=inputs())).json()
                self.assertTrue(initial["can_capture"])
                self.assertEqual(len(current.private_reads), 1)
                self.assertEqual((await client.post(post, content=b"{}")).status_code, 200)
                self.assertEqual(len(current.private_reads), 1)
                self.assertEqual(len(current.source_requests), 22)
                result = (await client.get(path, params=inputs())).json()
                self.assertEqual(result["count"], 7)
                held = current.chips_store.read("TPEx", "3105", date(2026, 10, 6))
                self.assertFalse(held["capture_state"]["can_capture"])
                self.assertEqual(held["capture_state"]["request_count"], 22)
                self.assertEqual((await client.post(post, content=b"{}")).status_code, 409)
                for body in (b"", b"null", b"[]", b'{"x":1}', b" " * 4097):
                    self.assertIn((await client.post(post, content=body)).status_code, (409, 413, 422))
                self.assertEqual(len(current.source_requests), 22)
        with fixture() as current:
            asyncio.run(run(current))

    def test_readiness_generation_and_failure_clear_without_retry(self):
        with fixture(failure=True) as current:
            loaded(current)
            result = joint.build_focus(current.instruments, inputs())
            self.assertEqual(result["status"], "unavailable")
            self.assertFalse(result["price_ready"])
            self.assertIsNone(result["count"])
            self.assertEqual(len(current.source_requests), 1)
            failed = current.chips_store.read("TPEx", "3105", date(2026, 10, 6))
            self.assertFalse(failed["capture_state"]["can_capture"])
            self.assertEqual(failed["capture_state"]["request_count"], 1)
            repeated = current.chips_store.capture("TPEx", "3105", date(2026, 10, 6))
            self.assertFalse(repeated["capture_state"]["can_capture"])
            self.assertEqual(repeated["capture_state"]["request_count"], 1)
            self.assertEqual(len(current.source_requests), 1)
        with fixture() as current:
            entered, release = Event(), Event()
            original = saved_focus.build_saved_focus
            results = []
            def slow(*args, **kwargs):
                entered.set()
                assert release.wait(2)
                return original(*args, **kwargs)
            with patch.object(saved_focus, "build_saved_focus", slow):
                thread = Thread(target=lambda: results.append(joint.build_focus(current.instruments, inputs())))
                thread.start()
                self.assertTrue(entered.wait(2))
                joint.STATE.observe()
                release.set()
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertFalse(joint.STATE.price_ready)
            self.assertEqual(results[0]["reasons"], ["joint_focus_stale_consumer"])

    def test_original_diagnostics_no_private_reads(self):
        import base64
        with fixture() as current:
            loaded(current)
            count = len(current.private_reads)
            diagnostic = entry.held_diagnostic(current.chips_store)
            self.assertEqual(len(diagnostic["original_captures"]), 22)
            for index, capture in enumerate(current.chips_store.raw_captures):
                raw = entry.held_raw(current.chips_store, index)
                self.assertEqual(base64.b64decode(raw["original_receipt_base64"]), capture.original_receipt_bytes)
                self.assertEqual(base64.b64decode(raw["body_base64"]), capture.body)
            self.assertEqual(len(current.private_reads), count)

    def test_request_local_authority_exact_context_and_other_thread(self):
        import __main__ as runner
        context = runner.CHIPS_CONTEXT
        target = entry.source_urls()[0]
        with patch.object(runner, "SCOPE7_ACTIVE", True):
            context.active, context.method, context.body = True, "GET", b""
            context.target, context.urls, context.request_count = target, frozenset(entry.source_urls()), 1
            context.addresses = {("1.2.3.4", 443)}
            self.assertTrue(runner.calendar_transport_allowed("socket.getaddrinfo", ("www.tpex.org.tw", 443)))
            self.assertTrue(runner.calendar_transport_allowed("socket.connect", (None, ("1.2.3.4", 443))))
            for event, args in [("socket.getaddrinfo", ("other.invalid", 443)), ("socket.getaddrinfo", ("www.tpex.org.tw", 80)),
                                ("socket.connect", (None, ("1.2.3.4", 80))), ("socket.connect", (None, ("5.6.7.8", 443)))]:
                self.assertFalse(runner.calendar_transport_allowed(event, args))
            result = []
            thread = Thread(target=lambda: result.append(runner.calendar_transport_allowed("socket.connect", (None, ("1.2.3.4", 443)))))
            thread.start(); thread.join(2)
            self.assertEqual(result, [False])
            for field, bad in [("method", "POST"), ("body", b"{}"), ("request_count", 2), ("target", "https://other.invalid")]:
                prior = getattr(context, field)
                setattr(context, field, bad)
                self.assertFalse(runner.calendar_transport_allowed("socket.getaddrinfo", ("www.tpex.org.tw", 443)))
                setattr(context, field, prior)
            context.active = False
            context.addresses.clear()
            self.assertFalse(runner.calendar_transport_allowed("socket.connect", (None, ("1.2.3.4", 443))))



    def test_all_seven_complete_before_price_zero_and_raw_names(self):
        with fixture() as current:
            loaded(current)
            data = joint.build_focus(current.instruments, inputs())
            zero = inputs(min_lots="1000000.000")
            for index, symbol in enumerate(chips.SYMBOLS):
                missing = data["institutional"][:index] + data["institutional"][index+1:]
                with self.assertRaises(ValueError):
                    joint.project(data["price"], missing, zero)
                broken = deepcopy(data["institutional"])
                broken[index]["windows"]["20"]["daily_evidence"][0]["row"]["source_values"][chips.DAILY_HEADER[2]] = "Wrong identity"
                with self.assertRaises(ValueError):
                    joint.project(data["price"], broken, zero)
            self.assertEqual((len(current.source_requests), len(data["institutional"])), (22, 7))
            diagnostic = entry.held_diagnostic(current.chips_store)
            self.assertEqual((diagnostic["producer_snapshot_ceiling"], diagnostic["inherited_bundle_reads"],
                diagnostic["inherited_file_reads"], diagnostic["shared_new_bundle_limit"]), (26,35,105,29))
