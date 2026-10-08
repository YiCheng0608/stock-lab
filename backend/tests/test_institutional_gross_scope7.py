import unittest
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import httpx
from app.institutional_gross_scope7 import API_PATH, create_app
from worker import tpex_institutional_gross_scope7 as w


def csv_bytes(header, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def fixtures(transform=None, extra_dates=("2026-10-07", "2026-10-08")):
    """Small, rebuildable synthetic inputs, never official evidence or disk files."""
    captures = []
    base = datetime(2026, 10, 8, tzinfo=timezone.utc)
    for i, url in enumerate(w.URLS):
        if i < 2:
            month = ("2026-09", "2026-10")[i]
            rows = [[d.replace("-", ""), "100", "102", "99", "101", "1"]
                    for d in (*w.ADOPTED_DATES, *extra_dates) if d.startswith(month)]
            header = w.INDEX_HEADER
        else:
            day = w.DATES[i - 2]
            rows = []
            for j, symbol in enumerate(w.SYMBOLS):
                def triple(n):
                    return [str(max(n, 0)), str(max(-n, 0)), str(n)]
                n = (i % 5 - 2) * (j + 1)
                groups = (n * 100, 0, n * 100, n * 10, n, 0, n)
                rows.append([str(int(day[:4]) - 1911) + day[5:7] + day[8:], symbol, w.NAMES[symbol]]
                            + [s for net in groups for s in triple(net)] + [str(n * 111)])
            header = w.HEADER
        if transform:
            header, rows = transform(i, list(header), rows)
        captures.append(w.Captured(i, url, csv_bytes(header, rows), base + timedelta(seconds=i),
                                   base + timedelta(seconds=i, microseconds=1)))
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


class GrossTests(unittest.TestCase):
    def test_all84gross42net_prefixes_reset_and_original_receipts(self):
        captures = fixtures()
        result = w.summarize(captures)
        self.assertTrue(result["available"], result["reason"])
        windows = 0
        for stock in result["stocks"]:
            for investor in w.INVESTORS:
                for horizon in ("5", "20"):
                    window = stock["series"][investor][horizon]
                    self.assertEqual(window["points"][0]["date"], "2026-09-30" if horizon == "5" else "2026-09-07")
                    for component in ("buy", "sell", "net"):
                        prefix = 0
                        for point in window["points"]:
                            prefix += int(point[component + "_shares"])
                            self.assertEqual(int(point["cumulative_" + component + "_shares"]), prefix)
                        self.assertEqual(str(prefix), window["total_" + component + "_shares"])
                    self.assertEqual(int(window["total_buy_shares"]) - int(window["total_sell_shares"]), int(window["total_net_shares"]))
                    windows += 1
        self.assertEqual(windows, 42)
        self.assertEqual(result["calendar"]["post_cutoff_excluded"], ["2026-10-07", "2026-10-08"])
        for c, r in zip(captures, result["receipts"]):
            self.assertEqual(c.original_receipt_bytes.decode(), r["canonical"])
        print(json.dumps({"synthetic_source_input_bytes": sum(len(c.body) for c in captures) + len(w.POLICY_CANONICAL.encode()),
                          "retained_graph_estimate_bytes": w.graph_estimate((captures, result)),
                          "derived_serialization_bytes": len(w.canonical(result)), "estimate": "deduplicated getsizeof, not RSS/peak"}))

    def test_dynamic_postcutoff_zero_one_two_rows(self):
        for dates in ((), ("2026-10-07",), ("2026-10-07", "2026-10-08")):
            result = w.summarize(fixtures(extra_dates=dates))
            self.assertTrue(result["available"], result["reason"])
            self.assertEqual(len(result["calendar"]["rows"]), 24 + len(dates))
            self.assertEqual(result["calendar"]["adopted_dates"], list(w.ADOPTED_DATES))

    def test_bad_all_returned_calendar_stops_before_daily(self):
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
            p, seen = producer(fixtures(transform=change))
            with patch.object(w, "utcnow", return_value=datetime(2026, 10, 8, tzinfo=timezone.utc)):
                result = p.capture()
            self.assertFalse(result["available"], case)
            self.assertEqual(len(seen), 2)
            with self.assertRaises(w.GrossError): p.capture()

    def test_bad_daily_schema_gross_int64_or_relations_masks_whole7(self):
        for case in ("negative", "unsafe", "overflow", "foreign", "dealer", "total", "missing", "duplicate", "name", "date"):
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
                return header, rows
            result = w.summarize(fixtures(transform=change))
            self.assertFalse(result["available"], case)
            self.assertEqual(result["stocks"], [])
            self.assertIsNone(result["calendar"])

    def test_gross_aggregate_overflow_even_with_net_zero(self):
        def change(i, header, rows):
            if i >= 2:
                row = rows[-1]
                row[3:25] = ["0"] * 22
                for start in (3, 9):
                    row[start:start + 3] = [str(w.MAX_I64 if i == 2 else 1), str(w.MAX_I64 if i == 2 else 1), "0"]
            return header, rows
        result = w.summarize(fixtures(transform=change))
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "aggregate_int64_overflow")

    def test_new_pins_original_receipt_and_no_old_capture_hydration(self):
        self.assertEqual(len(w.POLICY_CANONICAL.encode()), 10654)
        self.assertEqual(w.digest(w.POLICY_CANONICAL.encode()), "ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144")
        with self.assertRaises(w.GrossError): w.Producer(lambda *a: None, pin="sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31")
        captures = fixtures()
        object.__setattr__(captures[2], "original_receipt_bytes", b"{}")
        self.assertEqual(w.summarize(captures)["reason"], "original_receipt_tampered")
        captures = fixtures()
        object.__setattr__(captures[2], "profile", "old")
        self.assertFalse(w.summarize(captures)["available"])
        self.assertEqual(w.lots(-1), "-0.001")
        for value in ("-0", "+1", "01", "1.0"):
            with self.assertRaises(w.GrossError): w.integer(value)

    def test_factory_rejects_reused_or_foreign_producer_before_io(self):
        p, seen = producer(fixtures())
        p.attempted = True
        with self.assertRaises(w.GrossError): create_app(p)
        class ForeignProducer:
            attempted = False
            request_count = 0
            _captures = ()
        with self.assertRaises(w.GrossError): create_app(ForeignProducer())
        self.assertEqual(seen, [])


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p, self.seen = producer(fixtures())
        self.app = create_app(self.p)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("127.0.0.1", 12345)), base_url="http://owned")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_exact_query_body_and_method_gate_before_state(self):
        for query in ("", "as_of=2026-02-30", "as_of=2026-10-06&as_of=2026-10-06", "as_of=2026-10-06&x=1", "as_of=2026-10-6"):
            self.assertEqual((await self.client.get(API_PATH + "?" + query)).status_code, 422)
        self.assertEqual((await self.client.request("GET", API_PATH + "?as_of=" + w.CUTOFF, content=b"{}")).status_code, 422)
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, content=b"x" * 4097)).status_code, 413)
        for body in (b"", b"[]", b'{"x":1}', b"null"):
            self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, content=body)).status_code, 422)
        for path in ("/api/stocks/TPEx/3105", "/api/price/saved", "/private"):
            self.assertEqual((await self.client.get(path)).status_code, 404)
        self.assertEqual((await self.client.post(API_PATH + "?as_of=" + w.CUTOFF, json={})).status_code, 405)
        self.assertFalse(self.p.attempted); self.assertEqual(self.p.request_count, 0); self.assertEqual(self.seen, [])

    async def test_unsupported_valid_cutoff_does_not_read_state(self):
        with patch.object(self.p, "read", side_effect=AssertionError("state accessed")), patch.object(self.p, "capture", side_effect=AssertionError("state accessed")):
            for day in ("2026-10-05", "2026-10-07"):
                for method, suffix in (("GET", ""), ("POST", "/capture")):
                    response = await self.client.request(method, API_PATH + suffix + "?as_of=" + day, content=b"{}" if method == "POST" else b"")
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(response.json()["available"]); self.assertIsNone(response.json()["count"])

    async def test_first_read409_capture22_once_and_original_diagnostic(self):
        self.assertEqual((await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).status_code, 409)
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 8, tzinfo=timezone.utc)):
            response = await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.seen), 22)
        self.assertTrue((await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).json()["available"])
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})).status_code, 409)
        diagnostic = (await self.client.get("/__gross_root_receipt")).json()
        self.assertEqual(len(diagnostic["captures"]), 22)
        self.assertEqual(len(self.seen), 22)

    async def test_failed_source_masks_all_and_never_retries(self):
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
