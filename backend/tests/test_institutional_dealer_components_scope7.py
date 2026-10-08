"""Rebuildable minimal RAM CSV fixtures; no official evidence, files or DB."""
import base64
import csv
import io
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import httpx
from app.institutional_dealer_components_scope7 import API_PATH, DIAGNOSTIC_PATH, create_app
from worker import tpex_institutional_dealer_components_scope7 as w

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def csv_bytes(header, rows):
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")


def fixtures(transform=None, extra_dates=("2026-10-07", "2026-10-08")):
    p = w.policy()
    dates, day = [], date(2026, 9, 1)
    while day <= date(2026, 10, 6):
        text = day.isoformat()
        if day.weekday() < 5 and text not in p["calendar"]["closed_dates"]:
            dates.append(text)
        day += timedelta(days=1)
    last5 = dates[-5:]
    captures = []
    for ordinal, requested in enumerate(["2026-09-01", "2026-10-01", *last5]):
        if ordinal < 2:
            rows = [[d.replace("-", ""), "100", "102", "99", "101", "1"] for d in (*dates, *extra_dates) if d[:7] == requested[:7]]
            header, url = w.INDEX_HEADER, w.INDEX_URLS[ordinal]
        else:
            rows = []
            for i, symbol in enumerate(w.SYMBOLS):
                self_net, hedge_net = (4, -3, 0, 2, -1)[ordinal - 2], (-1, 2, 0, -2, 1)[ordinal - 2]
                trip = lambda n, b: (b + max(n, 0), b + max(-n, 0), n)
                own, hedge = trip(self_net, 10 + i), trip(hedge_net, 6 + i)
                total = tuple(a + b for a, b in zip(own, hedge))
                groups = [(7, 3, 4), (1, 2, -1), (8, 5, 3), (4, 4, 0), own, hedge, total]
                row = [str(int(requested[:4]) - 1911) + requested[5:7] + requested[8:], symbol, w.NAMES[symbol]]
                row += [str(x) for group in groups for x in group]
                row.append(str(4 + total[2]))
                rows.append(row)
            header, url = w.HEADER, w.daily_url(requested)
        if transform:
            transform(ordinal, rows)
        started = NOW + timedelta(seconds=ordinal * 2)
        captures.append(w.Captured(ordinal, requested, url, csv_bytes(header, rows), started, started + timedelta(seconds=1)))
    return captures


def producer(captures=None, failure=None):
    captures = fixtures() if captures is None else captures
    seen = []
    def fetch(url, cap, deadline):
        ordinal = len(seen); seen.append(url)
        if failure == ordinal:
            raise ValueError("synthetic_source_failure")
        c = captures[ordinal]
        assert c.url == url and len(c.body) <= cap
        return {"body": c.body, "status": 200, "content_type": c.content_type, "content_encoding": "identity"}
    return w.Producer(fetch), seen


class DealerTests(unittest.TestCase):
    def test_root_canonical_and_wrong_external_pins(self):
        raw = w.POLICY_CANONICAL.encode("utf-8")
        self.assertEqual((len(raw), w.digest(raw), len(w.policy()["rights"]["attribution"].encode("utf-8"))), (9245, "54347a73a5d725e702599eb582e9c75550f2c24c6839afd61c890e37bed99eab", 774))
        for kwargs in ({"pin": "old"}, {"version": "old"}, {"profile": "old"}):
            with self.assertRaises(w.DealerComponentsError):
                w.Producer(lambda *a: self.fail("source executed"), **kwargs)

    def test_new_empty_once_dynamic_all35_and_golden_totals(self):
        p, seen = producer()
        self.assertFalse(p.read()["available"]); self.assertFalse(p.attempted)
        self.assertEqual(p.request_urls, w.INDEX_URLS)
        with patch.object(w, "utcnow", return_value=NOW):
            result = p.capture()
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual((len(seen), p.request_count, len(p._captures)), (7, 7, 7))
        self.assertEqual(result["calendar"]["daily_dates"], ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"])
        self.assertEqual(len(result["calendar"]["rows"]), 26)
        self.assertEqual(sum(len(s["window"]["points"]) for s in result["stocks"]), 35)
        first = result["stocks"][0]["window"]
        self.assertEqual([first["totals"][c]["net_shares"] for c in w.COMPONENTS], ["2", "0", "2"])
        self.assertEqual([(first["totals"][c]["buy_shares"], first["totals"][c]["sell_shares"]) for c in w.COMPONENTS], [("56", "54"), ("33", "33"), ("89", "87")])
        self.assertTrue(first["totals"]["hedge"]["verified_net_zero"])
        self.assertEqual(first["points"][0]["components"]["hedge"]["net_lots"], "-0.001")
        diagnostic = p.diagnostic()
        for original, item in zip(p._captures, diagnostic["captures"]):
            self.assertEqual(base64.b64decode(item["body_base64"]), original.body)
            self.assertEqual(base64.b64decode(item["original_receipt_base64"]), original.original_receipt_bytes)
            self.assertEqual(item["body_sha256"], w.digest(original.body))
            self.assertEqual(item["original_receipt_sha256"], w.digest(original.original_receipt_bytes))
        reread = p.read(); reread["stocks"].clear()
        self.assertEqual(len(p.read()["stocks"]), 7)
        with self.assertRaises(w.DealerComponentsError): p.capture()
        self.assertEqual(len(seen), 7)

    def test_full_calendar_invalid_before_any_daily_and_spent(self):
        for change in ("missing", "duplicate", "postcutoff", "closed"):
            def transform(ordinal, rows):
                if ordinal == 0 and change == "missing": rows.pop(0)
                if ordinal == 0 and change == "duplicate": rows.append(rows[0].copy())
                if ordinal == 1 and change == "postcutoff": rows[-1][2] = "1"
                if ordinal == 0 and change == "closed": rows.append(["20260925", "100", "102", "99", "101", "1"])
            p, seen = producer(fixtures(transform))
            with patch.object(w, "utcnow", return_value=NOW): result = p.capture()
            self.assertFalse(result["available"], change)
            self.assertLessEqual(len(seen), 2)
            with self.assertRaises(w.DealerComponentsError): p.capture()

    def test_calendar_no_assumed_count_and_unsorted_originals(self):
        captures = fixtures(lambda ordinal, rows: rows.reverse() if ordinal < 2 else None, extra_dates=())
        result = w.summarize(captures)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual((len(result["calendar"]["rows"]), len(result["calendar"]["daily_dates"])), (24, 5))

    def test_whole7_missing_identity_all22_and_noncanonical_rejected(self):
        changes = [lambda rows: rows.pop(), lambda rows: rows.append(rows[0].copy()), lambda rows: rows[6].__setitem__(2, "wrong"),
                   lambda rows: rows[0].__setitem__(3, "-1"), lambda rows: rows[0].__setitem__(17, "-0"),
                   lambda rows: rows[0].__setitem__(24, "9223372036854775808"), lambda rows: rows[0].__setitem__(21, "3"),
                   lambda rows: rows[0].__setitem__(0, "1151007"), lambda rows: rows[0].pop()]
        for change in changes:
            captures = fixtures(lambda ordinal, rows: change(rows) if ordinal == 2 else None)
            result = w.summarize(captures)
            self.assertFalse(result["available"])
            self.assertEqual((result["stocks"], result["count"], result["calendar"], result["receipts"]), ([], None, None, []))

    def test_selected_non_dealer_component_and_grand_total_steps_checked(self):
        def transform(ordinal, rows):
            if ordinal == 2:
                row = rows[0]
                groups = [(w.MAX_I64, 0, w.MAX_I64), (0, 0, 0), (w.MAX_I64, 0, w.MAX_I64), (1, 0, 1), (0, 1, -1), (0, 0, 0), (0, 1, -1)]
                row[3:] = [str(x) for g in groups for x in g] + [str(w.MAX_I64)]
        result = w.summarize(fixtures(transform))
        self.assertFalse(result["available"]); self.assertIn("overflow", result["reason"])

    def test_window_net_sum_step_overflow_even_final_in_range(self):
        def transform(ordinal, rows):
            if ordinal >= 2:
                n = [w.MAX_I64, 1, -w.MAX_I64, 0, 0][ordinal - 2]
                own = (max(n, 0), max(-n, 0), n)
                groups = [(0, 0, 0)] * 4 + [own, (0, 0, 0), own]
                rows[0][3:] = [str(x) for g in groups for x in g] + [str(n)]
        result = w.summarize(fixtures(transform))
        self.assertFalse(result["available"]); self.assertIn("window_sum_step", result["reason"])

    def test_original_tamper_url_and_other_capture_type(self):
        captures = fixtures(); object.__setattr__(captures[2], "original_receipt_bytes", b"{}")
        self.assertFalse(w.summarize(captures)["available"])
        captures = fixtures(); object.__setattr__(captures[2], "url", "https://wrong.invalid/")
        self.assertFalse(w.summarize(captures)["available"])
        captures = fixtures(); captures[2] = object()
        self.assertFalse(w.summarize(captures)["available"])

    def test_first_failure_spent_partial_originals_and_no_retry(self):
        p, seen = producer(failure=3)
        with patch.object(w, "utcnow", return_value=NOW): result = p.capture()
        self.assertFalse(result["available"]); self.assertEqual((len(seen), len(p._captures)), (4, 3))
        self.assertEqual(len(p.diagnostic()["captures"]), 3)
        with self.assertRaises(w.DealerComponentsError): p.capture()
        self.assertEqual(len(seen), 4)

    def test_observation_date_guard_before_fetch(self):
        p, seen = producer()
        with patch.object(w, "utcnow", return_value=NOW - timedelta(days=1)): result = p.capture()
        self.assertFalse(result["available"]); self.assertEqual(seen, [])
        self.assertTrue(p.attempted)
        with self.assertRaises(w.DealerComponentsError): p.capture()

    def test_exact_lots_integer_boundary_and_new_factory(self):
        self.assertEqual([w.lots(s) for s in ("0", "-1", "1200")], ["0", "-0.001", "1.2"])
        self.assertEqual(w.integer("-9223372036854775808"), w.MIN_I64)
        for text in ("-0", "+1", "01", "1.0", "9223372036854775808"):
            with self.assertRaises(w.DealerComponentsError): w.integer(text)
        p, _ = producer(); p.attempted = True
        with self.assertRaises(w.DealerComponentsError): create_app(p)
        with self.assertRaises(w.DealerComponentsError): create_app(object())


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p, self.seen = producer()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.p)), base_url="http://testclient")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_exact_queries_methods_and_bodies_before_state(self):
        for query in ("", "?as_of=", "?as_of=2026-10-06&x=1", "?as_of=2026-10-06&as_of=2026-10-06", "?as_of=2026-02-30"):
            self.assertEqual((await self.client.get(API_PATH + query)).status_code, 422)
        self.assertEqual((await self.client.put(API_PATH + "?as_of=2026-10-06")).status_code, 405)
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=2026-10-06", json={"x": 1})).status_code, 422)
        self.assertEqual((await self.client.request("GET", API_PATH + "?as_of=2026-10-06", content=b"x")).status_code, 422)
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=2026-10-06", content=b"x" * 4097)).status_code, 413)
        self.assertEqual((await self.client.get(DIAGNOSTIC_PATH + "?x=1")).status_code, 422)
        self.assertEqual(self.seen, [])

    async def test_unsupported_cutoff_never_fetches_or_marks_first(self):
        for method, suffix in (("GET", ""), ("POST", "/capture")):
            r = await self.client.request(method, API_PATH + suffix + "?as_of=2026-10-07", json={} if method == "POST" else None)
            self.assertEqual(r.status_code, 200); self.assertFalse(r.json()["available"])
        self.assertFalse(self.p.attempted); self.assertEqual(self.seen, [])

    async def test_first409_capture7_read_and_originals_repeat409(self):
        query = "?as_of=2026-10-06"
        self.assertEqual((await self.client.get(API_PATH + query)).status_code, 409)
        with patch.object(w, "utcnow", return_value=NOW): r = await self.client.post(API_PATH + "/capture" + query, json={})
        self.assertEqual(r.status_code, 200); self.assertTrue(r.json()["available"])
        self.assertEqual((await self.client.get(API_PATH + query)).json(), r.json())
        before = (await self.client.get(DIAGNOSTIC_PATH)).json()
        self.assertEqual(len(before["captures"]), 7)
        self.assertEqual((await self.client.post(API_PATH + "/capture" + query, json={})).status_code, 409)
        self.assertEqual((await self.client.get(DIAGNOSTIC_PATH)).json(), before)
        self.assertEqual(len(self.seen), 7)

    async def test_first502_clears_all_then_read_unavailable_and_spent409(self):
        self.p.fetch = lambda *a: (_ for _ in ()).throw(ValueError("synthetic_source_failure"))
        query = "?as_of=2026-10-06"
        with patch.object(w, "utcnow", return_value=NOW): r = await self.client.post(API_PATH + "/capture" + query, json={})
        self.assertEqual(r.status_code, 502)
        self.assertEqual((r.json()["stocks"], r.json()["calendar"], r.json()["receipts"], r.json()["count"]), ([], None, [], None))
        self.assertFalse((await self.client.get(API_PATH + query)).json()["available"])
        self.assertEqual((await self.client.post(API_PATH + "/capture" + query, json={})).status_code, 409)
        self.assertEqual(self.p.request_count, 1)


if __name__ == "__main__":
    unittest.main()
