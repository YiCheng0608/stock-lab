import csv
import io
import itertools
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import httpx
from app.institutional_direction_scope7 import API_PATH, DIAGNOSTIC_PATH, create_app
from worker import tpex_institutional_direction_scope7 as w


def fixtures(transform=None, extra_dates=("2026-10-07", "2026-10-08")):
    """Rebuildable synthetic CSV inputs only; no files or official evidence."""
    captures = []
    base = datetime(2026, 10, 8, tzinfo=timezone.utc)
    patterns = ((1, 1, 1), (-1, -1, -1), (1, -1, 0), (1, 0, 0), (0, 0, 0),
                (1, 1, 1), (1, 1, 1), (-1, 0, 1), (0, -1, -1), (0, 0, 0))
    for ordinal, url in enumerate(w.URLS):
        if ordinal < 2:
            month = ("2026-09", "2026-10")[ordinal]
            rows = [[d.replace("-", ""), "100", "102", "99", "101", "1"]
                    for d in (*w.ADOPTED_DATES, *extra_dates) if d.startswith(month)]
            header = w.INDEX_HEADER
        else:
            day = w.DATES[ordinal - 2]
            rows = []
            for j, symbol in enumerate(w.SYMBOLS):
                foreign, trust, dealer = (s * (j + 1) * 1001 for s in patterns[(ordinal - 2 + j) % len(patterns)])
                triple = lambda n: [str(max(n, 0)), str(max(-n, 0)), str(n)]
                groups = (foreign, 0, foreign, trust, dealer, 0, dealer)
                rows.append([str(int(day[:4]) - 1911) + day[5:7] + day[8:], symbol, w.NAMES[symbol]]
                            + [v for n in groups for v in triple(n)] + [str(foreign + trust + dealer)])
            header = w.HEADER
        if transform:
            header, rows = transform(ordinal, list(header), rows)
        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(header); writer.writerows(rows)
        captures.append(w.Captured(ordinal, url, out.getvalue().encode("utf-8"),
                                   base + timedelta(seconds=ordinal), base + timedelta(seconds=ordinal, microseconds=1)))
    assert sum(len(c.body) for c in captures) + len(w.POLICY_CANONICAL.encode()) <= 96 * 1024
    return captures


def producer(captures):
    seen = []
    def fetch(url, cap, deadline):
        ordinal = len(seen)
        seen.append(url)
        assert url == w.URLS[ordinal] and cap in (1048576, 2097152)
        c = captures[ordinal]
        return {"body": c.body, "status": 200, "content_type": c.content_type, "content_encoding": c.content_encoding}
    return w.Producer(fetch), seen


def points(nets):
    return [{"date": w.DATES[-len(nets) + i], "net_shares": {name: str(n) for name in w.INVESTORS}}
            for i, n in enumerate(nets)]


class DirectionTests(unittest.TestCase):
    def test_all27_triple_categories_partition(self):
        expected = {
            "all_positive": {(1, 1, 1)}, "all_negative": {(-1, -1, -1)}, "all_zero": {(0, 0, 0)},
            "single_direction_with_zero": {(0, 0, 1), (0, 1, 0), (1, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 0),
                                           (0, 0, -1), (0, -1, 0), (-1, 0, 0), (0, -1, -1), (-1, 0, -1), (-1, -1, 0)},
        }
        expected["opposite"] = set(itertools.product((-1, 0, 1), repeat=3)) - set().union(*expected.values())
        self.assertEqual(sum(map(len, expected.values())), 27)
        for category, values in expected.items():
            for value in values:
                self.assertEqual(w.classify(list(value)), category, value)
        for bad in ([1, 0], [True, 0, 1], [None, 0, 1]):
            with self.assertRaises(w.DirectionError): w.classify(bad)

    def test_zero_breaks_runs_maximal_segments_and_latest(self):
        stats = w.window_stats(points([2, 3, 0, 0, -1]), "foreign")
        self.assertEqual(stats["counts"], {"positive": 2, "negative": 1, "zero": 2})
        self.assertEqual([(s["sign"], s["start_index"], s["end_index"], s["length"], s["earlier_unknown"])
                          for s in stats["segments"]], [("positive", 0, 1, 2, True), ("zero", 2, 3, 2, False), ("negative", 4, 4, 1, False)])
        self.assertEqual(stats["latest_run"], stats["segments"][-1])
        zero = w.window_stats(points([1, 1, -1, 0, 0]), "trust")
        self.assertEqual(zero["latest_run"]["sign"], "zero")
        self.assertEqual(zero["latest_run"]["length"], 2)

    def test_window_start_censor_and_no_longer_window_extension(self):
        full = points([1] * 20)
        for horizon in (5, 20):
            stat = w.window_stats(full[-horizon:], "dealer")
            self.assertEqual(stat["latest_run"]["length"], horizon)
            self.assertTrue(stat["latest_run"]["earlier_unknown"])
            self.assertEqual(stat["latest_run"]["start_index"], 0)
        alternating = w.window_stats(points([1, -1, 0, 1, -1]), "foreign")
        self.assertEqual(len(alternating["segments"]), 5)
        zero = w.window_stats(points([0] * 5), "trust")
        self.assertEqual(zero["counts"], {"positive": 0, "negative": 0, "zero": 5})
        self.assertEqual(len(zero["segments"]), 1)

    def test_all42_counts_segments_raw_triples_originals_calendar(self):
        captures = fixtures()
        result = w.summarize(captures)
        self.assertTrue(result["available"], result["reason"])
        groups = 0
        for stock in result["stocks"]:
            for horizon in ("5", "20"):
                window = stock["windows"][horizon]
                self.assertEqual(len(window["points"]), int(horizon))
                self.assertEqual(sum(window["direction_counts"].values()), int(horizon))
                for point in window["points"]:
                    self.assertEqual(len(point["source_values"]), 25)
                    for investor, offset in (("foreign", 5), ("trust", 14), ("dealer", 23)):
                        self.assertEqual(point["net_shares"][investor], point["source_values"][offset])
                        self.assertEqual(point["net_lots"][investor], w.lots(point["source_values"][offset]))
                for investor, stat in window["investors"].items():
                    values = [int(p["net_shares"][investor]) for p in window["points"]]
                    self.assertEqual(stat["counts"], {"positive": sum(n > 0 for n in values), "negative": sum(n < 0 for n in values), "zero": values.count(0)})
                    expected_lengths = [len(list(group)) for _, group in itertools.groupby(values, lambda n: (n > 0) - (n < 0))]
                    self.assertEqual([s["length"] for s in stat["segments"]], expected_lengths)
                    self.assertEqual(sum(expected_lengths), int(horizon))
                    self.assertEqual(stat["latest_run"], stat["segments"][-1])
                    groups += 1
        self.assertEqual(groups, 42)
        self.assertEqual(result["calendar"]["schema"], w.CALENDAR_SCHEMA)
        self.assertEqual(result["calendar"]["version"], w.CALENDAR_VERSION)
        for c, r in zip(captures, result["receipts"]):
            self.assertEqual(c.original_receipt_bytes.decode(), r["canonical"])
            self.assertEqual(w.digest(c.body), r["original"]["body_sha256"])
        estimate = w.graph_estimate((captures, result))
        self.assertLessEqual(estimate, 1024 * 1024)
        print(json.dumps({"synthetic_source_input_bytes": sum(len(c.body) for c in captures) + len(w.POLICY_CANONICAL.encode()),
                          "retained_graph_estimate_bytes": estimate, "derived_serialization_bytes": len(w.canonical(result)),
                          "estimate": "deduplicated getsizeof, not RSS or construction peak"}))

    def test_dynamic_all_returned_calendar_zero_one_two_excluded_rows(self):
        for dates in ((), ("2026-10-07",), ("2026-10-07", "2026-10-08")):
            result = w.summarize(fixtures(extra_dates=dates))
            self.assertTrue(result["available"], result["reason"])
            self.assertEqual(len(result["calendar"]["rows"]), 24 + len(dates))
            self.assertEqual(result["calendar"]["adopted_dates"], list(w.ADOPTED_DATES))

    def test_invalid_calendar_stops_before_any_daily_and_spent(self):
        for case in ("missing", "closed", "duplicate", "weekend", "future", "wrongmonth", "ohlc", "nan"):
            def change(i, header, rows):
                if i == 1:
                    if case == "missing": rows.pop(0)
                    elif case == "closed": rows.append(["20260925", "100", "102", "99", "101", "1"])
                    elif case == "duplicate": rows.append(rows[0])
                    elif case == "weekend": rows.append(["20261003", "100", "102", "99", "101", "1"])
                    elif case == "future": rows.append(["20261009", "100", "102", "99", "101", "1"])
                    elif case == "wrongmonth": rows[0][0] = "20260930"
                    elif case == "ohlc": rows[-1][2] = "1"
                    elif case == "nan": rows[-1][1] = "NaN"
                return header, rows
            p, seen = producer(fixtures(change))
            with patch.object(w, "utcnow", return_value=datetime(2026, 10, 8, tzinfo=timezone.utc)):
                result = p.capture()
            self.assertFalse(result["available"], case)
            self.assertEqual(len(seen), 2)
            with self.assertRaises(w.DirectionError): p.capture()

    def test_invalid_selected_raw_numeric_components_identity_masks_all(self):
        for case in ("negative", "unsafe", "overflow", "foreign", "dealer", "total", "missing", "duplicate", "name", "date", "header"):
            def change(i, header, rows):
                if i == 2:
                    row = rows[-1]
                    if case == "negative": row[3] = "-1"
                    elif case == "unsafe": row[3] = "1.0"
                    elif case == "overflow": row[3] = str(w.MAX_I64 + 1)
                    elif case == "foreign": row[9] = "1"
                    elif case == "dealer": row[21] = "1"
                    elif case == "total": row[24] = "1"
                    elif case == "missing": rows.pop()
                    elif case == "duplicate": rows.append(rows[0])
                    elif case == "name": row[2] = "wrong"
                    elif case == "date": row[0] = "1150908"
                    elif case == "header": header[-1] = "changed"
                return header, rows
            result = w.summarize(fixtures(change))
            self.assertFalse(result["available"], case)
            self.assertEqual(result["stocks"], []); self.assertIsNone(result["count"])
            self.assertIsNone(result["calendar"]); self.assertEqual(result["receipts"], [])

    def test_root_literal_old_pins_and_original_receipt_tampering(self):
        self.assertEqual(len(w.POLICY_CANONICAL.encode()), 12382)
        self.assertEqual(w.digest(w.POLICY_CANONICAL.encode()), "eb7a4dd688907855dd91250bfbec96b4dd8b2cb65085dce49e7e12c3a80c5348")
        with self.assertRaises(w.DirectionError): w.Producer(lambda *a: None, pin="sha256:ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144")
        for key, value in (("original_receipt_bytes", b"{}"), ("profile", "old"), ("captured_at", datetime(2026, 10, 7, tzinfo=timezone.utc))):
            captures = fixtures()
            object.__setattr__(captures[2], key, value)
            self.assertFalse(w.summarize(captures)["available"])
        self.assertFalse(w.summarize(fixtures()[:-1])["available"])

    def test_partial_first_failure_retains_originals_but_never_retries(self):
        p, seen = producer(fixtures())
        fetch = p.fetch
        def fail(url, cap, deadline):
            if len(seen) == 3: raise ValueError("synthetic_partial_failure")
            return fetch(url, cap, deadline)
        p.fetch = fail
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 8, tzinfo=timezone.utc)):
            result = p.capture()
        self.assertFalse(result["available"]); self.assertEqual(p.request_count, 4)
        self.assertEqual(len(p.diagnostic()["captures"]), 3)
        with self.assertRaises(w.DirectionError): p.capture()
        self.assertEqual(p.request_count, 4)

    def test_factory_rejects_reused_foreign_seeded_before_io(self):
        p, seen = producer(fixtures())
        p.attempted = True
        with self.assertRaises(w.DirectionError): create_app(p)
        p.attempted = False; p._captures = (object(),)
        with self.assertRaises(w.DirectionError): create_app(p)
        with self.assertRaises(w.DirectionError): create_app(object())
        self.assertEqual(seen, [])

    def test_signed_int64_canonical_and_exact_lots(self):
        self.assertEqual(w.integer(str(w.MIN_I64)), w.MIN_I64)
        self.assertEqual(w.integer(str(w.MAX_I64)), w.MAX_I64)
        self.assertEqual(w.lots("-1"), "-0.001")
        for v in ("-0", "+1", "01", "1.0", str(w.MAX_I64 + 1), str(w.MIN_I64 - 1), 1, None):
            with self.assertRaises(w.DirectionError): w.integer(v)


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p, self.seen = producer(fixtures())
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.p), client=("127.0.0.1", 12345)), base_url="http://owned")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_query_body_method_unknown_path_before_state(self):
        for query in ("", "as_of=2026-02-30", "as_of=2026-10-06&as_of=2026-10-06", "as_of=2026-10-06&x=1", "as_of=2026-10-6"):
            self.assertEqual((await self.client.get(API_PATH + "?" + query)).status_code, 422)
        self.assertEqual((await self.client.request("GET", API_PATH + "?as_of=" + w.CUTOFF, content=b"{}")).status_code, 422)
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, content=b"x" * 4097)).status_code, 413)
        for body in (b"", b"[]", b'{"x":1}', b"null"):
            self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, content=body)).status_code, 422)
        for path in ("/api/chips/gross-stock-scope-7", "/api/chips/series-stock-scope-7", "/api/price/saved", "/private"):
            self.assertEqual((await self.client.get(path)).status_code, 404)
        self.assertEqual((await self.client.post(API_PATH + "?as_of=" + w.CUTOFF, json={})).status_code, 405)
        self.assertFalse(self.p.attempted); self.assertEqual(self.p.request_count, 0)

    async def test_unsupported_cutoff_never_inspects_state(self):
        with patch.object(self.p, "read", side_effect=AssertionError("state accessed")), patch.object(self.p, "capture", side_effect=AssertionError("state accessed")):
            for day in ("2026-10-05", "2026-10-07"):
                for method, suffix in (("GET", ""), ("POST", "/capture")):
                    response = await self.client.request(method, API_PATH + suffix + "?as_of=" + day, content=b"{}" if method == "POST" else b"")
                    self.assertEqual(response.status_code, 200); self.assertIsNone(response.json()["count"])

    async def test_first409_capture22_once_read_and_unchanged_original_diagnostic(self):
        self.assertEqual((await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).status_code, 409)
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 8, tzinfo=timezone.utc)):
            response = await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.seen), 22)
        self.assertTrue((await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).json()["available"])
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})).status_code, 409)
        diagnostic = (await self.client.get(DIAGNOSTIC_PATH)).json()
        self.assertEqual(len(diagnostic["captures"]), 22)
        self.assertFalse(diagnostic["preloaded"]); self.assertEqual(diagnostic["seed_count"], 0)
        self.assertEqual((await self.client.get(DIAGNOSTIC_PATH + "?x=1")).status_code, 422)

    async def test_first_failure_masks_all_and_spent(self):
        self.p.fetch = lambda *args: (_ for _ in ()).throw(ValueError("synthetic_missing_source"))
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 8, tzinfo=timezone.utc)):
            response = await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})
        self.assertEqual(response.status_code, 502)
        read = (await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).json()
        self.assertFalse(read["available"]); self.assertIsNone(read["count"])
        self.assertEqual(read["stocks"], []); self.assertIsNone(read["calendar"]); self.assertEqual(read["receipts"], [])
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})).status_code, 409)
        self.assertEqual(self.p.request_count, 1)


if __name__ == "__main__":
    unittest.main()
