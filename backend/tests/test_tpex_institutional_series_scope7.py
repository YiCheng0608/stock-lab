"""Rebuildable small memory fixtures; no official evidence or disk fixtures."""
import ast
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit
import unittest
from unittest.mock import patch

import httpx

from worker import tpex_institutional_series_scope7 as w

sys.path.append(str(Path(__file__).resolve().parents[2] / "tools"))
import local_runner_gate as gate  # noqa: E402  (the runner's cross-site / DNS-rebinding gate)


def csv_bytes(header, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header); writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def financial_row(day, symbol, nets):
    row = [str(int(day[:4]) - 1911) + day[5:7] + day[8:], symbol, w.NAMES[symbol]]
    def group(net):
        return [str(max(net, 0)), str(max(-net, 0)), str(net)]
    foreign, trust, dealer = nets
    for n in (foreign, 0, foreign, trust, dealer, 0, dealer):
        row.extend(group(n))
    return row + [str(sum(nets))]


def fixtures(overrides=None, transform=None):
    overrides = overrides or {}
    captures = []
    base = datetime(2026, 10, 7, tzinfo=timezone.utc)
    for i, url in enumerate(w.URLS):
        if i < 2:
            month = ("2026-09", "2026-10")[i]
            rows = [[d.replace("-", ""), "100", "102", "99", "101", "1"] for d in w.ORIGINAL_DATES if d.startswith(month)]
            header = w.INDEX_HEADER
        else:
            day = w.DATES[i - 2]
            rows = [financial_row(day, s, overrides.get((day, s), ((i % 5 - 2) * (j + 1) * 100, 0, 0))) for j, s in enumerate(w.SYMBOLS)]
            header = w.HEADER
        if transform:
            header, rows = transform(i, list(header), rows)
        captures.append(w.Captured(i, url, csv_bytes(header, rows), base + timedelta(seconds=i), base + timedelta(seconds=i, microseconds=1)))
    assert sum(len(c.body) for c in captures) + len(w.POLICY_CANONICAL.encode("utf-8")) + 40 <= 96 * 1024
    return captures


def producer(captures):
    seen = []
    def fetch(url, cap, deadline):
        i = len(seen); seen.append(url)
        assert url == w.URLS[i] and cap in (1048576, 2097152)
        c = captures[i]
        return {"body": c.body, "status": 200, "content_type": c.content_type, "content_encoding": c.content_encoding}
    return w.Producer(fetch), seen


class SeriesTests(unittest.TestCase):
    def test_full_42_exact_series_zero_window_reset_and_small_fixture(self):
        captures = fixtures()
        result = w.summarize(captures)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual(result["count"], 7)
        total = 0
        for s in result["stocks"]:
            for investor in w.INVESTORS:
                for horizon in ("5", "20"):
                    window = s["series"][investor][horizon]
                    self.assertEqual(window["points"][0]["date"], "2026-09-30" if horizon == "5" else "2026-09-07")
                    self.assertEqual(window["points"][0]["cumulative_shares"], window["points"][0]["net_shares"])
                    self.assertEqual(int(window["total_shares"]), sum(int(p["net_shares"]) for p in window["points"]))
                    self.assertEqual(window["points"][-1]["cumulative_shares"], window["total_shares"])
                    total += 1
        self.assertEqual(total, 42)
        self.assertEqual(w.lots(-1), "-0.001")
        self.assertEqual(w.lots(1000), "1")
        self.assertLessEqual(w.graph_estimate((captures, result)), 1024 * 1024)
        print(json.dumps({"synthetic_source_input_bytes": sum(len(c.body) for c in captures) + len(w.POLICY_CANONICAL.encode("utf-8")) + 40,
                          "retained_graph_estimate_bytes": w.graph_estimate((captures, result)),
                          "derived_expanded_serialization_bytes": len(w.canonical(result)),
                          "estimate": "deduplicated getsizeof, not RSS or construction peak"}))
        self.assertEqual(result["calendar"]["original_dates"][-1], "2026-10-07")
        self.assertEqual(result["calendar"]["adopted_dates"][-1], w.CUTOFF)

    def test_signed_integer_min_max_and_noncanonical_rejected(self):
        self.assertEqual(w.integer(str(w.MIN_I64)), w.MIN_I64)
        self.assertEqual(w.integer(str(w.MAX_I64)), w.MAX_I64)
        for bad in ("-0", "+1", "01", "1.0", str(w.MAX_I64 + 1), str(w.MIN_I64 - 1)):
            with self.assertRaises(w.SeriesError): w.integer(bad)

    def test_running_prefix_overflow_while_final_in_range_masks_all(self):
        overrides = {(day, "3105"): (0, 0, 0) for day in w.DATES}
        overrides.update({(w.DATES[i], "3105"): (n, 0, 0) for i, n in enumerate((w.MAX_I64, 1, -1))})
        result = w.summarize(fixtures(overrides))
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "running_prefix_int64_overflow")
        self.assertIsNone(result["count"])
        self.assertEqual(result["stocks"], [])
        self.assertIsNone(result["calendar"])

    def test_aggregate_and_negative_prefix_overflow(self):
        for values, reason in (((w.MAX_I64, 1), "aggregate_int64_overflow"), ((-w.MAX_I64, -2, 2), "running_prefix_int64_overflow")):
            overrides = {(day, "3105"): (0, 0, 0) for day in w.DATES}
            overrides.update({(w.DATES[i], "3105"): (n, 0, 0) for i, n in enumerate(values)})
            result = w.summarize(fixtures(overrides))
            self.assertFalse(result["available"])
            self.assertEqual(result["reason"], reason)

    def test_invalid_header_identity_date_missing_and_daily_overflow(self):
        def change(case):
            def transform(i, header, rows):
                if i == 2:
                    if case == "header": header[3] += "changed"
                    elif case == "identity": rows[0][2] = "wrong"
                    elif case == "date": rows[0][0] = "1150908"
                    elif case == "missing": rows.pop()
                    elif case == "overflow": rows[0][3] = str(w.MAX_I64 + 1)
                return header, rows
            return transform
        for case in ("header", "identity", "date", "missing", "overflow"):
            with self.subTest(case=case): self.assertFalse(w.summarize(fixtures(transform=change(case)))["available"])

    def test_calendar_extra_observation_mismatch_stops_before_daily(self):
        def transform(i, header, rows):
            if i == 1: rows.pop()
            return header, rows
        p, seen = producer(fixtures(transform=transform))
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 7, tzinfo=timezone.utc)):
            result = p.capture()
        self.assertFalse(result["available"])
        self.assertEqual(len(seen), 2)
        with self.assertRaises(w.SeriesError): p.capture()
        self.assertEqual(len(seen), 2)

    def test_policy_profile_and_original_receipt_tampering(self):
        self.assertEqual(len(w.POLICY_CANONICAL.encode()), 9733)
        self.assertEqual(w.digest(w.POLICY_CANONICAL.encode()), "143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31")
        captures = fixtures()
        object.__setattr__(captures[2], "original_receipt_bytes", b"{}")
        self.assertEqual(w.summarize(captures)["reason"], "original_receipt_tampered")
        self.assertFalse(w.summarize(fixtures(), profile="old")["available"])
        changed = w.policy(); changed["series"]["overflow"] = "ignore"
        self.assertFalse(w.summarize(fixtures(), admitted_policy=changed)["available"])

    def test_one_empty_producer_source_once_and_read_no_fetch(self):
        p, seen = producer(fixtures())
        self.assertFalse(p.read()["available"]); self.assertEqual(seen, [])
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 7, tzinfo=timezone.utc)):
            self.assertTrue(p.capture()["available"])
        self.assertEqual(len(seen), 22)
        self.assertTrue(p.read()["available"])
        with self.assertRaises(w.SeriesError): p.capture()
        self.assertEqual(len(seen), 22)
        diagnostic = p.diagnostic()
        self.assertEqual(len(diagnostic["captures"]), 22)
        self.assertEqual(diagnostic["seed_count"], 0)
        self.assertFalse(diagnostic["preloaded"])

    def test_observation_change_stops_before_first_source(self):
        p, seen = producer(fixtures())
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 8, tzinfo=timezone.utc)):
            self.assertFalse(p.capture()["available"])
        self.assertEqual(seen, [])
        p, seen = producer(fixtures())
        with patch.object(w, "utcnow", side_effect=[datetime(2026, 10, 7, tzinfo=timezone.utc), datetime(2026, 10, 8, tzinfo=timezone.utc)]):
            self.assertFalse(p.capture()["available"])
        self.assertEqual(seen, [])

    def test_runner_guards_reject_before_private_db_subprocess_network_io(self):
        path = Path(__file__).resolve().parents[2] / "tools/tpex-chips-series-api.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"audit", "deny"}]
        scope = {"os": os, "CONTEXT": threading.local(), "COUNTS": dict.fromkeys(("disk_writes", "mutations", "private_reads", "databases", "subprocesses", "network_rejections"), 0),
                 "ARGS": type("Args", (), {"serve": False, "port": 8799})()}
        exec(compile(ast.Module(body=funcs, type_ignores=[]), str(path), "exec"), scope)
        for event, args in (("open", ("C:/Users/YiCheng/AppData/Local/taiwan-stock-research/forbidden.csv", "r", 0)), ("open", ("unused", "w", os.O_WRONLY)), ("sqlite3.connect", (":memory:",)), ("subprocess.Popen", ("unused",)), ("socket.getaddrinfo", ("example.org", 443)), ("socket.connect", (None, ("127.0.0.1", 8799)))):
            with self.assertRaises(PermissionError): scope["audit"](event, args)

    def test_runner_whole_request_deadline_and_finally_clear_without_network(self):
        path = Path(__file__).resolve().parents[2] / "tools/tpex-chips-series-api.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        fetch = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fetch")
        clock, closed, budgets = [0.0], [], []
        class Response:
            status = 200
            fp = None
            def getheaders(self): return [("Content-Type", "text/csv")]
            def getheader(self, key, default=None): return "text/csv" if key == "Content-Type" else default
            def read1(self, cap): clock[0] += 4; return b"x"
        class Connection:
            def __init__(self, *args, **kwargs): budgets.append(kwargs["timeout"]); self.sock = SimpleNamespace(settimeout=budgets.append)
            def connect(self): clock[0] += 6
            def request(self, *args, **kwargs): clock[0] += 4
            def getresponse(self): clock[0] += 2; return Response()
            def close(self): closed.append(True)
        context = threading.local()
        scope = {"ARGS": SimpleNamespace(serve=True, chips_series_stock_scope_7_opt_in=True),
                 "series": w, "REQUESTS": 0, "urlsplit": urlsplit, "CONTEXT": context,
                 "time": SimpleNamespace(monotonic=lambda: clock[0]),
                 "ssl": SimpleNamespace(create_default_context=lambda: None),
                 "http": SimpleNamespace(client=SimpleNamespace(HTTPSConnection=Connection)), "json": json}
        exec(compile(ast.Module(body=[fetch], type_ignores=[]), str(path), "exec"), scope)
        with self.assertRaises(TimeoutError): scope["fetch"](w.URLS[0], 1048576, 180)
        self.assertEqual(scope["REQUESTS"], 1)
        self.assertEqual(budgets, [15.0, 9.0, 5.0, 3.0])
        self.assertEqual(closed, [True])
        self.assertFalse(context.active); self.assertEqual(context.addresses, set())

    def test_runner_serves_the_app_through_the_browser_gate(self):
        path = Path(__file__).resolve().parents[2] / "tools/tpex-chips-series-api.py"
        main = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "main")
        front = [ast.unparse(n.value) for n in ast.walk(main) if isinstance(n, ast.Assign) and [ast.unparse(t) for t in n.targets] == ["front"]]
        served = [ast.unparse(n.args[0]) for n in ast.walk(main) if isinstance(n, ast.Call) and ast.unparse(n.func) == "uvicorn.run"]
        self.assertEqual(front, ["gate.wrap(create_app(producer), port=ARGS.port)"])
        self.assertEqual(served, ["front"])


class GateRuleTests(unittest.IsolatedAsyncioTestCase):
    """Explicit expectations for the shared gate (the same rules the Issue 9 combos service enforces)."""
    PORT = 8799

    def raw(self, *pairs):
        return [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in pairs]

    def test_rules_admit_only_the_own_origin_and_json_posts(self):
        host, origin = ("Host", "127.0.0.1:8799"), "http://127.0.0.1:8799"
        own = "127.0.0.1:8799"
        for method, pairs in (("GET", [host]), ("GET", [host, ("Sec-Fetch-Site", "same-origin"), ("Origin", origin)]), ("GET", [host, ("Sec-Fetch-Site", "none")]),
                              ("GET", [host, ("Sec-Fetch-Site", "SAME-ORIGIN")]), ("POST", [host, ("Content-Type", "application/json")]),
                              ("POST", [host, ("Content-Type", "Application/JSON; charset=UTF-8")]), ("DELETE", [host]), ("PUT", [host])):
            self.assertIsNone(gate.refusal(method, self.raw(*pairs), own), (method, pairs))
        for method, pairs, expected in (
                ("GET", [], (403, "host_not_admitted")), ("GET", [host, host], (403, "host_not_admitted")), ("GET", [("Host", "localhost:8799")], (403, "host_not_admitted")),
                ("GET", [("Host", "127.0.0.1:8798")], (403, "host_not_admitted")), ("GET", [host, ("Sec-Fetch-Site", "cross-site")], (403, "cross_site_rejected")),
                ("GET", [host, ("Sec-Fetch-Site", "same-site")], (403, "cross_site_rejected")), ("GET", [host, ("Origin", "http://evil.example")], (403, "origin_not_admitted")),
                ("GET", [host, ("Origin", "null")], (403, "origin_not_admitted")), ("DELETE", [host, ("Origin", "http://evil.example")], (403, "origin_not_admitted")),
                ("POST", [host], (415, "content_type_json_required")), ("POST", [host, ("Content-Type", "text/plain")], (415, "content_type_json_required")),
                ("POST", [host, ("Content-Type", "application/x-www-form-urlencoded")], (415, "content_type_json_required")),
                ("POST", [host, ("Content-Type", "multipart/form-data; boundary=x")], (415, "content_type_json_required")),
                ("POST", [host, ("Content-Type", "application/json"), ("Content-Type", "text/plain")], (415, "content_type_json_required")),
                # A foreign page's no-cors POST is refused on site and origin before its Content-Type is even considered.
                ("POST", [host, ("Content-Type", "text/plain"), ("Origin", "http://evil.example"), ("Sec-Fetch-Site", "cross-site")], (403, "cross_site_rejected"))):
            self.assertEqual(gate.refusal(method, self.raw(*pairs), own), expected, (method, pairs))

    async def test_front_door_refuses_before_the_app_and_never_admits_websockets(self):
        seen, sent = [], []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            sent.append(message)

        front = gate.wrap(inner, port=self.PORT)
        await front({"type": "http", "method": "GET", "path": "/", "headers": []}, receive, send)  # no Host at all (HTTP/1.0 style)
        self.assertEqual((sent[0]["status"], sent[1]["body"]), (403, b'{"reason":"host_not_admitted"}'))
        await front({"type": "websocket", "path": "/", "headers": self.raw(("Host", "127.0.0.1:8799"))}, receive, send)
        self.assertEqual(sent[2], {"type": "websocket.close", "code": 1008})
        self.assertEqual(seen, [])
        await front({"type": "lifespan"}, receive, send)
        await front({"type": "http", "method": "GET", "path": "/", "headers": self.raw(("Host", "127.0.0.1:8799"))}, receive, send)
        self.assertEqual(seen, ["lifespan", "http"])
        self.assertEqual(front.refusals, {"host_not_admitted": 1})
        for port in (80, 1023, 65536, "8799", None):
            with self.assertRaises(ValueError):
                gate.wrap(inner, port=port)


class GateMatrixMixin:
    """One chips profile's served app behind the runner's gate: every endpoint refuses a foreign page before any state, quota or fetch."""
    PORT = 8799
    CUTOFF = "2026-10-06"

    def new_producer(self):
        raise NotImplementedError

    def observed(self):
        raise NotImplementedError

    async def asyncSetUp(self):
        self.p, self.seen = self.new_producer()
        self.app = gate.wrap(self.create_app(self.p), port=self.PORT)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("127.0.0.1", 12345)), base_url="http://127.0.0.1:%d" % self.PORT)

    async def asyncTearDown(self):
        await self.client.aclose()

    def endpoints(self):
        return (("GET", self.API_PATH + "?as_of=" + self.CUTOFF), ("POST", self.API_PATH + "/capture?as_of=" + self.CUTOFF), ("GET", self.DIAGNOSTIC_PATH))

    async def test_gate_refuses_every_endpoint_before_state_quota_or_fetch(self):
        refused = 0
        for method, target in self.endpoints():
            for label, headers, status, reason in gate.refusal_variants(method, self.PORT):
                response = await self.client.request(method, target, headers=headers, content=b"{}" if method == "POST" else None)
                self.assertEqual((response.status_code, response.json()), (status, {"reason": reason}), (method, target, label))
                refused += 1
        self.assertFalse(self.p.attempted); self.assertEqual((self.p.request_count, self.seen), (0, []))
        self.assertEqual(sum(self.app.refusals.values()), refused)

    async def test_same_origin_operation_is_unchanged(self):
        read, capture, diagnostic = self.endpoints()
        for _, headers in gate.admitted_variants("GET", self.PORT):
            self.assertEqual((await self.client.request("GET", read[1], headers=headers)).status_code, 409)  # nothing captured yet
            self.assertEqual((await self.client.request("GET", diagnostic[1], headers=headers)).status_code, 200)
        self.assertEqual(self.seen, [])
        posts = gate.admitted_variants("POST", self.PORT)
        with self.observed():
            first = await self.client.request("POST", capture[1], headers=posts[0][1], content=b"{}")
        self.assertEqual(first.status_code, 200); self.assertEqual(len(self.seen), self.FETCHES)
        for _, headers in posts[1:]:  # every other admitted shape reaches the app and meets the spent one-shot
            self.assertEqual((await self.client.request("POST", capture[1], headers=headers, content=b"{}")).status_code, 409)
        for _, headers in gate.admitted_variants("GET", self.PORT):
            self.assertTrue((await self.client.request("GET", read[1], headers=headers)).json()["available"])
        self.assertEqual(len(self.seen), self.FETCHES)
        self.assertEqual(self.app.refusals, {})


if __name__ == "__main__":
    unittest.main()
