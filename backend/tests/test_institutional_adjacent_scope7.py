"""Rebuildable RAM CSV fixtures only; no official evidence or files."""
import base64
import csv
import io
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import httpx
from app.institutional_adjacent_scope7 import API_PATH, DIAGNOSTIC_PATH, create_app
from worker import tpex_institutional_adjacent_scope7 as w


def fixtures(transform=None, extra_dates=("2026-10-07", "2026-10-08"), foreign=None):
    p = w.policy()
    dates, day = [], date(2026, 9, 1)
    while day <= date(2026, 10, 6):
        text = day.isoformat()
        if day.weekday() < 5 and text not in p["calendar"]["closed_dates"]:
            dates.append(text)
        day += timedelta(days=1)
    daily = dates[-10:]
    requested = ["2026-09-01", "2026-10-01", *daily]
    captures = []
    patterns = (1, -2, 0, 3, 0, -3, 2, 1, 0, -1)
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    for ordinal, target in enumerate(requested):
        if ordinal < 2:
            rows = [[d.replace("-", ""), "100", "102", "99", "101", "1"] for d in (*dates, *extra_dates) if d[:7] == target[:7]]
            header, url = w.INDEX_HEADER, w.INDEX_URLS[ordinal]
        else:
            rows = []
            for j, symbol in enumerate(w.SYMBOLS):
                n = foreign[ordinal - 2] if foreign is not None else patterns[(ordinal - 2 + j) % 10] * (j + 1) * 1001
                trust, dealer = (0, 0) if foreign is not None else (patterns[(ordinal - 1 + j) % 10] * 7, patterns[(ordinal + j) % 10] * 13)
                triple = lambda value: [str(max(value, 0)), str(max(-value, 0)), str(value)]
                rows.append([str(int(target[:4]) - 1911) + target[5:7] + target[8:], symbol, w.NAMES[symbol]]
                            + [v for n in (n, 0, n, trust, dealer, 0, dealer) for v in triple(n)] + [str(n + trust + dealer)])
            header, url = w.HEADER, w.daily_url(target)
        if transform:
            header, rows = transform(ordinal, list(header), rows)
        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(header); writer.writerows(rows)
        captures.append(w.Captured(ordinal, target, url, out.getvalue().encode("utf-8"), start + timedelta(seconds=ordinal), start + timedelta(seconds=ordinal, microseconds=1)))
    assert sum(len(c.body) for c in captures) + len(w.POLICY_CANONICAL.encode()) <= 96 * 1024
    return captures


def producer(captures, fail=None):
    seen = []
    def fetch(url, cap, deadline):
        ordinal = len(seen)
        seen.append(url)
        if fail == ordinal:
            raise ValueError("synthetic_first_failure")
        c = captures[ordinal]
        assert url == c.url and cap in (1048576, 2097152)
        return {"body": c.body, "status": 200, "content_type": c.content_type, "content_encoding": c.content_encoding}
    return w.Producer(fetch), seen


class AdjacentTests(unittest.TestCase):
    def test_root_literal_and_independent_policy(self):
        raw = w.POLICY_CANONICAL.encode()
        self.assertEqual((len(raw), w.digest(raw)), (9284, "092f86d7fd2797b88f12f92e0474beb120139143ba5c3f3e27edb0c52f5c235e"))
        self.assertEqual(len(w.policy()["rights"]["attribution"].encode()), 685)
        self.assertEqual(w.canonical(w.policy()), raw)
        for kwargs in ({"pin": "sha256:eb7a4dd688907855dd91250bfbec96b4dd8b2cb65085dce49e7e12c3a80c5348"}, {"profile": "old"}, {"version": "old"}):
            with self.assertRaises(w.AdjacentError): w.Producer(lambda *args: self.fail("I/O"), **kwargs)
        modified = w.policy(); modified["scope"]["cutoff"] = "2026-10-07"
        self.assertFalse(w.summarize(fixtures(), admitted_policy=modified)["available"])

    def test_dynamic_calendar_before_daily_sequence_and_all70_originals(self):
        originals = fixtures()
        p, seen = producer(originals)
        self.assertEqual(p.request_urls, w.INDEX_URLS)
        self.assertFalse(p.attempted); self.assertEqual(p.diagnostic()["captures"], [])
        read = p.capture()
        self.assertTrue(read["available"], read["reason"])
        self.assertEqual(len(seen), 12)
        cal = read["calendar"]
        self.assertEqual(cal["daily_dates"], cal["adopted_dates"][-10:])
        self.assertEqual(cal["previous_dates"], cal["daily_dates"][:5])
        self.assertEqual(cal["recent_dates"], cal["daily_dates"][5:])
        self.assertEqual(p.request_urls, w.INDEX_URLS + tuple(w.daily_url(day) for day in cal["daily_dates"]))
        raw_rows = {c.requested_date: list(csv.reader(io.StringIO(c.body.decode())))[1:] for c in originals[2:]}
        count = 0
        for stock in read["stocks"]:
            for name in ("previous", "recent"):
                window = stock["windows"][name]
                self.assertEqual(window["horizon"], 5)
                self.assertEqual([p["date"] for p in window["points"]], cal[name + "_dates"])
                for point in window["points"]:
                    row = raw_rows[point["date"]][point["row_ordinal"] - 1]
                    self.assertEqual(point["source_values"], row)
                    self.assertEqual(point["net_shares"], dict(zip(w.INVESTORS, (row[5], row[14], row[23]))))
                    count += 1
                for investor in w.INVESTORS:
                    stats = window["investors"][investor]
                    nets = [int(point["net_shares"][investor]) for point in window["points"]]
                    self.assertEqual(stats["total_shares"], str(sum(nets)))
                    self.assertEqual(stats["counts"], {"positive": sum(n > 0 for n in nets), "negative": sum(n < 0 for n in nets), "zero": sum(n == 0 for n in nets)})
                    self.assertEqual(stats["verified_zero"], sum(nets) == 0)
            for investor in w.INVESTORS:
                old, new = (stock["windows"][name]["investors"][investor] for name in ("previous", "recent"))
                comparison = stock["comparisons"][investor]
                delta = int(new["total_shares"]) - int(old["total_shares"])
                self.assertEqual(comparison["net_delta_shares"], str(delta))
                self.assertEqual(sum(int(pair["net_delta_shares"][investor]) for pair in stock["pairs"]), delta)
                for index, pair in enumerate(stock["pairs"]):
                    a, b = (stock["windows"][name]["points"][index] for name in ("previous", "recent"))
                    self.assertEqual((pair["position"], pair["previous_date"], pair["recent_date"]), (index + 1, a["date"], b["date"]))
                    self.assertEqual(pair["net_delta_shares"][investor], str(int(b["net_shares"][investor]) - int(a["net_shares"][investor])))
        self.assertEqual(count, 70)
        diagnostic = p.diagnostic()
        for expected, observed in zip(p._captures, diagnostic["captures"]):
            self.assertEqual(base64.b64decode(observed["body_base64"]), expected.body)
            self.assertEqual(base64.b64decode(observed["original_receipt_base64"]), expected.original_receipt_bytes)
            self.assertEqual(observed["original_receipt_sha256"], expected.original_receipt_sha256)
        self.assertEqual(p.read(), read)
        with self.assertRaises(w.AdjacentError): p.capture()
        self.assertEqual(len(seen), 12)

    def test_dynamic_postcutoff_rows_no_assumed_count_and_unsorted_source(self):
        for extras in ((), ("2026-10-07",), ("2026-10-07", "2026-10-08")):
            read = w.summarize(fixtures(extra_dates=extras))
            self.assertTrue(read["available"], read["reason"])
            self.assertEqual(read["calendar"]["post_cutoff_excluded"], list(extras))
        def reverse(ordinal, header, rows): return (header, list(reversed(rows))) if ordinal < 2 else (header, rows)
        self.assertTrue(w.summarize(fixtures(reverse))["available"])

    def test_bad_full_calendar_stops_before_daily_and_spent(self):
        mutations = (lambda rows: rows[1:], lambda rows: rows + [rows[0]], lambda rows: rows[:-1] + [[*rows[-1][:2], "1", *rows[-1][3:]]])
        for mutate in mutations:
            def change(ordinal, header, rows): return (header, mutate(rows)) if ordinal == 1 else (header, rows)
            p, seen = producer(fixtures(change))
            read = p.capture()
            self.assertFalse(read["available"])
            self.assertEqual((len(seen), p.request_count, p.request_urls), (2, 2, w.INDEX_URLS))
            self.assertEqual((read["stocks"], read["calendar"], read["receipts"], read["count"]), ([], None, [], None))
            with self.assertRaises(w.AdjacentError): p.capture()
            self.assertEqual(len(seen), 2)

    def test_missing_structure_identity_components_and_noncanonical_mask_all(self):
        mutations = (lambda rows: rows[:-1], lambda rows: rows + [rows[0]],
                     lambda rows: [[*rows[0][:2], "wrong", *rows[0][3:]], *rows[1:]],
                     lambda rows: [[*rows[0][:5], "-0", *rows[0][6:]], *rows[1:]],
                     lambda rows: [[*rows[0][:23], "999", rows[0][24]], *rows[1:]],
                     lambda rows: [[*rows[0][:24], "1"], *rows[1:]])
        for mutate in mutations:
            def change(ordinal, header, rows): return (header, mutate(rows)) if ordinal == 2 else (header, rows)
            p, seen = producer(fixtures(change))
            result = p.capture()
            self.assertFalse(result["available"])
            self.assertEqual(len(seen), 3)
            self.assertEqual((result["count"], result["stocks"], result["receipts"]), (None, [], []))

    def test_daily_component_addition_and_total_step_overflow(self):
        def components(ordinal, header, rows):
            if ordinal == 2:
                rows[0][3:12] = [str(w.MAX_I64), "0", str(w.MAX_I64), "1", "0", "1", str(w.MAX_I64), "0", str(w.MAX_I64)]
            return header, rows
        self.assertFalse(w.summarize(fixtures(components))["available"])
        def total(ordinal, header, rows):
            if ordinal == 2:
                rows[0][3:] = [str(w.MAX_I64), "0", str(w.MAX_I64), "0", "0", "0", str(w.MAX_I64), "0", str(w.MAX_I64), "1", "0", "1", "0", "1", "-1", "0", "0", "0", "0", "1", "-1", str(w.MAX_I64)]
            return header, rows
        self.assertFalse(w.summarize(fixtures(total))["available"])

    def test_window_sum_step_overflow_even_when_final_in_range(self):
        result = w.summarize(fixtures(foreign=[w.MAX_I64, 1, -w.MAX_I64, 0, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(result["reason"], "window_sum_step_int64_overflow")

    def test_pair_subtraction_overflow(self):
        result = w.summarize(fixtures(foreign=[-w.MAX_I64, 0, 0, 0, 0, w.MAX_I64, 0, 0, 0, 0]))
        self.assertEqual(result["reason"], "pair_delta_int64_overflow")

    def test_total_subtraction_overflow_with_each_pair_in_range(self):
        result = w.summarize(fixtures(foreign=[-w.MAX_I64, 0, 0, 0, 0, 0, w.MAX_I64, 0, 0, 0]))
        self.assertEqual(result["reason"], "total_delta_int64_overflow")

    def test_pair_sum_step_overflow_with_both_totals_zero(self):
        half = w.MAX_I64 // 2 + 1
        result = w.summarize(fixtures(foreign=[-half, 0, half, 0, 0, 0, half, 0, -half, 0]))
        self.assertEqual(result["reason"], "pair_delta_sum_step_int64_overflow")

    def test_zero_breaks_runs_and_distinct_total_delta_zero(self):
        read = w.summarize(fixtures(foreign=[2, 3, 0, 0, -1, 0, 4, 0, 0, 0]))
        self.assertTrue(read["available"], read["reason"])
        stock = read["stocks"][0]
        previous = stock["windows"]["previous"]["investors"]["foreign"]
        recent = stock["windows"]["recent"]["investors"]["foreign"]
        self.assertEqual(previous["counts"], {"positive": 2, "negative": 1, "zero": 2})
        self.assertEqual([(s["sign"], s["length"], s["earlier_unknown"]) for s in previous["segments"]], [("positive", 2, True), ("zero", 2, False), ("negative", 1, False)])
        self.assertEqual((recent["latest_run"]["sign"], recent["latest_run"]["length"]), ("zero", 3))
        self.assertTrue(stock["comparisons"]["foreign"]["verified_delta_zero"])
        self.assertFalse(previous["verified_zero"])
        allzero = w.summarize(fixtures(foreign=[0] * 10))["stocks"][0]
        self.assertEqual(allzero["windows"]["previous"]["investors"]["foreign"]["latest_run"]["length"], 5)
        self.assertTrue(allzero["windows"]["recent"]["investors"]["foreign"]["verified_zero"])

    def test_original_tamper_wrong_dynamic_url_and_foreign_capture_type(self):
        captures = fixtures(); object.__setattr__(captures[3], "original_receipt_bytes", b"{}")
        self.assertFalse(w.summarize(captures)["available"])
        captures = fixtures(); object.__setattr__(captures[3], "url", captures[4].url)
        self.assertFalse(w.summarize(captures)["available"])
        self.assertFalse(w.summarize([object()] * 12)["available"])

    def test_empty_factory_rejects_reused_seeded_or_other_producer(self):
        p, _ = producer(fixtures()); p.capture()
        with self.assertRaises(w.AdjacentError): create_app(p)
        p, _ = producer(fixtures()); p._captures = tuple(fixtures())
        with self.assertRaises(w.AdjacentError): create_app(p)
        with self.assertRaises(w.AdjacentError): create_app(object())

    def test_failed_first_is_spent_without_retry_and_partial_originals_retained(self):
        for fail in (0, 1, 4):
            p, seen = producer(fixtures(), fail)
            self.assertFalse(p.capture()["available"])
            self.assertEqual((p.request_count, len(p._captures)), (fail + 1, fail))
            original = p.diagnostic()
            with self.assertRaises(w.AdjacentError): p.capture()
            self.assertEqual(p.diagnostic(), original)
            self.assertEqual(len(seen), fail + 1)

    def test_observation_changed_before_source_and_int64_lots(self):
        p, seen = producer(fixtures())
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 9, tzinfo=timezone.utc)):
            self.assertFalse(p.capture()["available"])
        self.assertEqual(seen, [])
        self.assertEqual(w.integer(str(w.MIN_I64)), w.MIN_I64)
        for bad in ("-0", "+1", "01", "1.0", "9223372036854775808", 1):
            with self.assertRaises(w.AdjacentError): w.integer(bad)
        self.assertEqual((w.lots("-1"), w.lots("1200")), ("-0.001", "1.2"))


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p, self.seen = producer(fixtures())
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.p)), base_url="http://testclient")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_exact_queries_methods_bodies_before_state(self):
        for query in ("", "as_of=", "as_of=2026-02-30", "as_of=2026-10-06&as_of=2026-10-06", "as_of=2026-10-06&investor=trust", "as_of=2026-10-06&x=1"):
            self.assertEqual((await self.client.get(API_PATH + "?" + query)).status_code, 422)
        for body in ([], {"x": 1}, None):
            self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=2026-10-06", content=json.dumps(body))).status_code, 422)
        self.assertEqual((await self.client.request("GET", API_PATH + "?as_of=2026-10-06", content="x")).status_code, 422)
        self.assertEqual((await self.client.put(API_PATH)).status_code, 405)
        self.assertEqual((await self.client.get("/api/price")).status_code, 404)
        self.assertEqual((await self.client.get(DIAGNOSTIC_PATH + "?x=1")).status_code, 422)
        self.assertEqual(self.seen, [])

    async def test_unsupported_valid_cutoff_never_inspects_producer(self):
        with patch.object(self.p, "read", side_effect=AssertionError("state")), patch.object(self.p, "capture", side_effect=AssertionError("state")):
            for method, path in (("GET", API_PATH), ("POST", API_PATH + "/capture")):
                r = await self.client.request(method, path + "?as_of=2026-10-07", content="{}" if method == "POST" else None)
                self.assertEqual(r.status_code, 200); self.assertFalse(r.json()["available"])
        self.assertEqual(self.seen, [])

    async def test_first409_capture12_read_diagnostic_originals_repeat409(self):
        query = "?as_of=2026-10-06"
        self.assertEqual((await self.client.get(API_PATH + query)).status_code, 409)
        captured = await self.client.post(API_PATH + "/capture" + query, json={})
        self.assertEqual(captured.status_code, 200)
        self.assertTrue(captured.json()["available"])
        self.assertEqual((await self.client.get(API_PATH + query)).json(), captured.json())
        before = (await self.client.get(DIAGNOSTIC_PATH)).json()
        self.assertEqual(len(before["captures"]), 12)
        self.assertEqual((await self.client.post(API_PATH + "/capture" + query, json={})).status_code, 409)
        self.assertEqual((await self.client.get(DIAGNOSTIC_PATH)).json(), before)
        self.assertEqual(len(self.seen), 12)

    async def test_first_source_failure502_then_blank_read_and_spent409(self):
        self.p.fetch = lambda *args: (_ for _ in ()).throw(ValueError("synthetic_failure"))
        query = "?as_of=2026-10-06"
        first = await self.client.post(API_PATH + "/capture" + query, json={})
        self.assertEqual(first.status_code, 502)
        self.assertEqual((first.json()["stocks"], first.json()["count"], first.json()["calendar"]), ([], None, None))
        read = await self.client.get(API_PATH + query)
        self.assertEqual(read.status_code, 200); self.assertFalse(read.json()["available"])
        self.assertEqual((await self.client.post(API_PATH + "/capture" + query, json={})).status_code, 409)
        self.assertEqual(self.p.request_count, 1)


if __name__ == "__main__":
    unittest.main()
