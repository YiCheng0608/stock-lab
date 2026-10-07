"""Bounded joint-entry contracts: no product private files or actual source requests."""
from contextlib import contextmanager
import ast
import base64
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app import saved_price_chips_entry as entry, institutional_windows_1006 as windows, institutional_windows as old
from app import price_saved_focus as focus, tpex_price_saved as saved
from worker import tpex_institutional_1006 as chips
import httpx


def synthetic_captures():
    # Reuse only the existing reconstructable fixture builders, without executing
    # that standalone helper's argparse, audit registration or live entry.
    filename = Path(__file__).with_name("test_institutional_windows_1006.py")
    tree = ast.parse(filename.read_text(encoding="utf-8"), filename=str(filename))
    names = {"csv_body", "daily_row", "make_capture", "captures"}
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"chips": chips, "io": io, "csv": csv, "hashlib": hashlib,
                 "OBSERVED": datetime(2026, 10, 7, tzinfo=timezone.utc)}
    exec(compile(tree, str(filename), "exec"), namespace)
    captures = namespace["captures"]()
    encoded = entry.canonical_bytes([{"url": item.url, "body": item.body.decode("utf-8")} for item in captures])
    graph = chips.retained_graph_estimate(captures)
    assert len(encoded) <= 80 * 1024 and graph <= 512 * 1024
    return captures, len(encoded), graph


@contextmanager
def fixture(failure=False):
    import __main__ as runner
    from test_price_saved_focus import accepted_environment, memory_database_snapshot
    source = entry.entry_policy()["independent_pins"]["price_capture"]
    with patch.object(runner.ARGS, "policy_version", source["policy_version"]), patch.object(
            runner.ARGS, "policy_digest", "sha256:" + source["sha256"]):
        current = runner.saved_consumer_fixture()
    items, encoded, graph = synthetic_captures()
    bodies = {item.url: item.body for item in items}
    requests = []
    def handler(request):
        requests.append(str(request.url))
        body = b"bad\n" if failure and len(requests) == 1 else bodies[str(request.url)]
        return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"}, stream=httpx.ByteStream(body))
    current.chips_store = windows.InstitutionalWindowStore1006(transport=httpx.MockTransport(handler))
    current.old_chips_store = old.InstitutionalWindowStore(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("old_source_denied"))))
    current.stack.enter_context(patch.object(windows, "STORE", current.chips_store))
    current.stack.enter_context(patch.object(old, "STORE", current.old_chips_store))
    current.stack.enter_context(patch.dict("os.environ", {**accepted_environment(), windows.ENABLE_ENV: "1",
        windows.VERSION_ENV: chips.POLICY_VERSION, windows.DIGEST_ENV: chips.POLICY_DIGEST, old.ENABLE_ENV: "0"}))
    current.stack.enter_context(patch.object(focus, "MAX_READS", entry.PRODUCER_READ_LIMIT))
    current.stack.enter_context(patch.object(focus, "_READ_COUNT", 0))
    entry.install_request_gate(current.app)
    current.before_full = memory_database_snapshot(current)
    current.source_requests, current.fixture_bytes, current.fixture_graph = requests, encoded, graph
    try:
        yield current
        assert memory_database_snapshot(current) == current.before_full
        assert not current.store._attempted and current.store.raw_capture is None
        assert not current.old_chips_store._attempted and not current.old_chips_store.raw_captures
    finally:
        current.close()


class JointEntryTests(unittest.TestCase):
    def test_runner_configuration_transport_thread_scope_and_zero_startup_private_io(self):
        import __main__ as runner
        from threading import Thread
        from test_price_saved_focus import memory_database_snapshot
        policy = entry.entry_policy()
        items, _, _ = synthetic_captures()
        bodies = {item.url: item.body for item in items}
        seen = []
        class MemoryHTTPTransport:
            def __init__(self, *, retries, trust_env):
                self.assertions = (retries, trust_env)
            def handle_request(self, request):
                self_context = getattr(runner.CHIPS_CONTEXT, "active", False)
                other = []
                thread = Thread(target=lambda: other.append(getattr(runner.CHIPS_CONTEXT, "active", False)))
                thread.start(); thread.join()
                assert self_context and other == [False]
                seen.append(str(request.url))
                return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"}, stream=httpx.ByteStream(bodies[str(request.url)]))
            def close(self):
                pass
        with fixture() as current:
            current.validation_baseline = runner.database_snapshot(current)
            changes = {"cutoff": "2026-10-06", "saved_source_only": True, "joint_policy_version": entry.POLICY_VERSION, "joint_policy_digest": entry.POLICY_DIGEST}
            for name, prefix in (("price_capture", "policy"), ("price_storage", "private_policy"), ("saved_focus", "saved_focus_policy"), ("institutional", "chips_policy")):
                changes[prefix + "_version"] = policy["independent_pins"][name]["policy_version"]
                changes[prefix + "_digest"] = "sha256:" + policy["independent_pins"][name]["sha256"]
            with patch.multiple(runner.ARGS, **changes), patch.object(runner, "JOINT_ACTIVE", True), patch.object(
                    runner, "SAVED_FOCUS_ACTIVE", True), patch.object(runner, "PRIVATE_ROOT", Path(policy["private_use"]["root"])), patch.object(
                    httpx, "HTTPTransport", MemoryHTTPTransport), patch.object(runner, "private_disk_metrics", side_effect=AssertionError("startup metadata I/O forbidden")) as metrics:
                runner.configure_joint(current)
                result = runner.receipt(current)
                self.assertEqual(result["joint_entry"]["source_request_count"], 0)
                self.assertEqual(result["saved_focus_consumer"]["max_snapshot_reads"], 61)
                metrics.assert_not_called()
                self.assertEqual(current.chips_transport.inner.assertions, (0, False))
                url = entry.source_urls()[0]
                current.chips_transport.handle_request(httpx.Request("GET", url))
                self.assertFalse(getattr(runner.CHIPS_CONTEXT, "active", False))
                for method, target in (("GET", url), ("POST", entry.source_urls()[1]), ("GET", "https://www.tpex.org.tw/not-admitted")):
                    with self.assertRaises(AssertionError):
                        current.chips_transport.handle_request(httpx.Request(method, target))
                self.assertEqual(seen, [url])
                self.assertEqual(memory_database_snapshot(current), current.before_full)

    def test_canonical_independent_pins_and_producer_reserve(self):
        policy = entry.entry_policy()
        self.assertEqual(len(entry.canonical_bytes(policy)), 10702)
        self.assertEqual("sha256:" + hashlib.sha256(entry.canonical_bytes(policy)).hexdigest(), entry.POLICY_DIGEST)
        pins = {key: (value["policy_version"], "sha256:" + value["sha256"]) for key, value in policy["independent_pins"].items()}
        entry.validate_admission(entry.POLICY_VERSION, entry.POLICY_DIGEST, pins)
        for name in pins:
            wrong = {**pins, name: (pins[name][0], "sha256:" + "0" * 64)}
            with self.assertRaises(ValueError):
                entry.validate_admission(entry.POLICY_VERSION, entry.POLICY_DIGEST, wrong)
        with patch.object(focus, "MAX_READS", entry.PRODUCER_READ_LIMIT), patch.object(focus, "_READ_COUNT", 60):
            focus.SnapshotGuard().start()
            self.assertEqual(focus._READ_COUNT, 61)
            with self.assertRaisesRegex(ValueError, "read_budget_exceeded"):
                focus.SnapshotGuard().start()
        self.assertEqual(entry.PRODUCER_READ_LIMIT + entry.ROOT_OBSERVATION_RESERVE, 64)

    def test_request_gate_exact_query_body_and_diagnostic_bounds(self):
        path = "/api/stocks/TPEx/3105/institutional-windows/capture"
        for body in (b"{}", b" \r\n{ }\t"):
            self.assertIsNone(entry.request_error("POST", path, "as_of=2026-10-06", body))
        for body in (b"", b"null", b"[]", b"1", b'{"x":1}', b"{bad", "{}".encode("utf-16"), "{}".encode("utf-32")):
            self.assertEqual(entry.request_error("POST", path, "as_of=2026-10-06", body)[0], 422)
        self.assertEqual(entry.request_error("POST", path, "as_of=2026-10-06", b" " * 4097)[0], 413)
        self.assertEqual(entry.static_request_error("POST", "/api/stocks/TPEx/3105/prices/save")[0], 405)
        for query in ("", "as_of=2026-10-05", "as_of=2026-10-06&as_of=2026-10-06", "as_of=2026-10-06&x=1"):
            self.assertEqual(entry.request_error("POST", path, query, b"{}")[0], 422)
        for path in ("/api/stocks/TPEx/6510/institutional-windows/capture", "/api/stocks/TPEx/3105/prices/capture",
                     "/api/stocks/TPEx/3105/prices/save", "/api/focus/price-lots/capture"):
            self.assertEqual(entry.request_error("POST", path, "as_of=2026-10-06", b"{}")[0], 405)
        self.assertIsNone(entry.request_error("GET", "/api/focus/price-saved", "as_of=2026-10-05&min_lots=0", b""))
        for index in ("0", "9", "10", "21"):
            self.assertIsNone(entry.request_error("GET", "/__price_validation/chips/raw", "index=" + index, b""))
        for index in ("", "00", "01", "-1", "22", "1.0"):
            self.assertEqual(entry.request_error("GET", "/__price_validation/chips/raw", "index=" + index, b"")[0], 422)
        self.assertEqual(entry.MAX_RAW_RESPONSE_BYTES, 3 * 1024 * 1024)

    def test_actual_router_pre_io_rejections_and_unsupported_focus(self):
        import asyncio
        async def run(current):
            transport = httpx.ASGITransport(app=current.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with patch.object(saved, "read_private_snapshot", side_effect=AssertionError("private_file_read_not_admitted")) as private:
                    for path, body in (("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06&x=1", b"{}"),
                        ("/api/stocks/TPEx/6488/institutional-windows/capture?as_of=2026-10-06&as_of=2026-10-06", b"{}"),
                        ("/api/stocks/TPEx/6510/institutional-windows/capture?as_of=2026-10-06", b"{}"),
                        ("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06", b""),
                        ("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06", b"null"),
                        ("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06", b" " * 4097)):
                        response = await client.post(path, content=body)
                        self.assertIn(response.status_code, (405, 413, 422))
                    for path in ("/api/stocks/TPEx/3105/prices/saved-focus?as_of=2026-10-06&x=1",
                        "/api/stocks/TWSE/3105/prices/saved-focus?as_of=2026-10-06",
                        "/api/stocks/TPEx/3105/prices/saved?as_of=2026-10-06"):
                        self.assertIn((await client.get(path)).status_code, (405, 422))
                    self.assertEqual((await client.request("GET", "/api/stocks/TPEx/3105?as_of=2026-10-06", content=b"{}")).status_code, 422)
                    response = await client.get("/api/focus/price-saved?as_of=2026-10-05&min_lots=0")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual((response.json()["status"], response.json()["count"], response.json()["items"]), ("unavailable", None, []))
                    response = await client.get("/api/stocks/TPEx/3105?as_of=2026-10-06")
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(response.json()["overview"]["institutional"]["capture_state"]["attempted"])
                    private.assert_not_called()
            self.assertEqual(current.source_requests, [])
        with fixture() as current:
            asyncio.run(run(current))

    def test_one_capture_two_identities_original_raw_and_database_preservation(self):
        import asyncio
        async def run(current):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=current.app), base_url="http://test") as client:
                response = await client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06", json={})
                self.assertEqual((response.status_code, response.json()["status"]), (200, "available"))
                self.assertEqual(len(current.source_requests), 22)
                for symbol in ("3105", "6488"):
                    response = await client.get("/api/stocks/TPEx/" + symbol + "?as_of=2026-10-06")
                    self.assertEqual(response.json()["overview"]["institutional"]["symbol"], symbol)
                    for horizon in (5, 20):
                        values = response.json()["overview"]["institutional"]["windows"][str(horizon)]["values"]
                        self.assertEqual(values["foreign"], str(sum(80 + ordinal for ordinal in range(21 - horizon, 21))))
                    response = await client.post("/api/stocks/TPEx/" + symbol + "/institutional-windows/capture?as_of=2026-10-06", json={})
                    self.assertEqual(response.json()["capture_state"]["action"], "cached")
                self.assertEqual(len(current.source_requests), 22)
                for index, item in enumerate(current.chips_store.raw_captures):
                    raw = entry.held_raw(current.chips_store, index)
                    self.assertEqual(base64.b64decode(raw["body_base64"]), item.body)
                    original = base64.b64decode(raw["original_receipt_base64"])
                    self.assertEqual(original, entry.canonical_bytes(item.receipt()))
                    self.assertEqual(hashlib.sha256(original).hexdigest(), raw["original_receipt_sha256"])
                diagnostic = entry.held_diagnostic(current.chips_store)
                self.assertEqual(len(diagnostic["original_captures"]), 22)
                self.assertLess(len(entry.canonical_bytes(diagnostic)), entry.MAX_RECEIPT_BYTES)
                self.assertEqual(len(current.source_requests), 22)
        with fixture() as current:
            asyncio.run(run(current))
            print(json.dumps({"joint_fixture_serialized_bytes": current.fixture_bytes, "joint_fixture_graph_estimated_bytes": current.fixture_graph,
                              "max_serialized_bytes": 81920, "max_graph_estimated_bytes": 524288, "source_kind": "synthetic_memory_only"}))

    def test_failed_calendar_attempt_never_retries_and_absent_raw(self):
        import asyncio
        async def run(current):
            self.assertIsNone(entry.held_raw(current.chips_store, 0))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=current.app), base_url="http://test") as client:
                path = "/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06"
                first = await client.post(path, json={})
                self.assertEqual(first.json()["status"], "unavailable")
                count = len(current.source_requests)
                self.assertLessEqual(count, 2)
                second = await client.post(path, json={})
                self.assertEqual(second.json()["status"], "unavailable")
                await client.get("/api/stocks/TPEx/6488?as_of=2026-10-06")
                self.assertEqual(len(current.source_requests), count)
        with fixture(failure=True) as current:
            asyncio.run(run(current))
