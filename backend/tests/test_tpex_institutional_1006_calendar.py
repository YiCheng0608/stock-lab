"""Calendar-v2 bounded synthetic checks; no source HTTP or private product I/O."""
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
import unittest
import httpx
from worker import tpex_institutional_1006_calendar as chips

def csv_body(header, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")

def daily_row(day, symbol, ordinal):
    groups = [(100 + ordinal, 20), (2, 1), (102 + ordinal, 21), (3, 10 + ordinal),
              (10, 3), (7 + ordinal, 4), (17 + ordinal, 7)]
    values = [str(value) for buy, sell in groups for value in (buy, sell, buy - sell)]
    return [f"115{day.month:02d}{day.day:02d}", symbol, "Synthetic " + symbol, *values, str(83 + ordinal)]

def make_capture(source, day, body):
    now = datetime(2026, 10, 7, 10, 43, 30, tzinfo=timezone.utc)
    return chips.CapturedCSV1006Calendar(source, day, chips.source_url(source, day), body,
        hashlib.sha256(body).hexdigest(), now, now, chips.POLICY_VERSION, chips.POLICY_DIGEST,
        chips.PROFILE, chips.window_policy()["sources"][source]["source_version"])

def synthetic_captures():
    result = []
    for month in chips.MONTH_REQUESTS:
        rows = [[day.strftime("%Y%m%d"), "10", "12", "9", "11", "1"]
                for day in chips.ORIGINAL_EXPECTED_SESSIONS if day.month == month.month]
        result.append(make_capture(chips.INDEX_SOURCE_ID, month, csv_body(chips.INDEX_HEADER, rows)))
    for ordinal, day in enumerate(chips.DAILY_REQUESTS, 1):
        result.append(make_capture(chips.DAILY_SOURCE_ID, day,
            csv_body(chips.DAILY_HEADER, [daily_row(day, symbol, ordinal) for symbol in chips.SYMBOLS])))
    encoded = chips.canonical_bytes([{"url": item.url, "body": item.body.decode("utf-8"),
        "original_receipt": item.original_receipt_bytes.decode("utf-8")} for item in result])
    graph = chips.retained_graph_estimate(result)
    assert len(encoded) <= 81920 and graph <= 524288, (len(encoded), graph)
    return result, len(encoded), graph

def summarize(items):
    return chips.summarize_window_captures(items, policy=chips.window_policy(), profile=chips.PROFILE,
        expected_policy_version=chips.POLICY_VERSION, expected_policy_digest=chips.POLICY_DIGEST,
        as_of=chips.CUTOFF, calendar_version=chips.CALENDAR_VERSION)

def load(items, failing=None):
    bodies = {item.url: item.body for item in items}
    calls = []
    def handler(request):
        assert request.method == "GET" and request.content == b""
        url = str(request.url)
        assert url in bodies and url not in calls
        calls.append(url)
        body = b"bad\n" if failing == len(calls) else bodies[url]
        return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"},
            stream=httpx.ByteStream(body))
    cache = chips.MemoryWindowCache1006Calendar(policy=chips.window_policy(), profile=chips.PROFILE,
        expected_policy_version=chips.POLICY_VERSION, expected_policy_digest=chips.POLICY_DIGEST)
    result = cache.load(as_of=chips.CUTOFF, calendar_version=chips.CALENDAR_VERSION,
                        transport=httpx.MockTransport(handler))
    return cache, result, calls

class CalendarWorkerTests(unittest.TestCase):
    def test_external_pin_and_complete_originals(self):
        items, size, graph = synthetic_captures()
        self.assertEqual(len(chips.canonical_bytes(chips.window_policy())), 5263)
        self.assertEqual(chips._digest(chips.window_policy()), "sha256:1acf97b7dd0f13b9b49ed3293497e52ca52ea077256b8d99d9bc21ed5761d403")
        from worker import tpex_institutional_1006 as old
        self.assertEqual(len(old.canonical_bytes(old.window_policy())), 4264)
        self.assertEqual(old.POLICY_DIGEST, "sha256:36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5")
        result = summarize(items)
        self.assertEqual(result["status"], "available")
        self.assertEqual(len(result["calendar"]["original_rows"]), 25)
        self.assertEqual(len(result["calendar"]["rows"]), 24)
        self.assertEqual(result["calendar"]["post_cutoff_dates"], ["2026-10-07"])
        self.assertEqual(result["calendar"]["evidence"][1]["candidate_count"], 5)
        for item in items:
            self.assertEqual(item.original_receipt_bytes, chips.canonical_bytes(item.receipt()))
            self.assertEqual(item.original_receipt_sha256, hashlib.sha256(item.original_receipt_bytes).hexdigest())
        print(json.dumps({"synthetic_input_serialized_bytes": size, "synthetic_input_graph_estimated_bytes": graph,
            "max_serialized_bytes": 81920, "max_graph_estimated_bytes": 524288,
            "actual_source_get": 0, "actual_private_reads": 0}))

    def test_all_post_cutoff_fields_dates_and_duplicates_rejected(self):
        items, _, _ = synthetic_captures()
        rows = list(csv.reader(io.StringIO(items[1].body.decode("utf-8"))))[1:]
        for position, value in [(0, "20261008"), (0, "20261010"), (0, "20260925"),
                                (0, "20261006"), (1, "NaN"), (2, "8"), (5, "Infinity")]:
            changed = [row[:] for row in rows]
            changed[-1][position] = value
            bad = [items[0], make_capture(chips.INDEX_SOURCE_ID, chips.MONTH_REQUESTS[1],
                csv_body(chips.INDEX_HEADER, changed)), *items[2:]]
            with self.subTest(position=position, value=value):
                self.assertEqual(summarize(bad)["status"], "unavailable")
                _, result, calls = load(bad)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(len(calls), 2)
        missing = [items[0], make_capture(chips.INDEX_SOURCE_ID, chips.MONTH_REQUESTS[1],
            csv_body(chips.INDEX_HEADER, rows[:-1])), *items[2:]]
        _, result, calls = load(missing)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(len(calls), 2)

    def test_first_error_stops_and_never_retries(self):
        items, _, _ = synthetic_captures()
        for failing, expected in [(1, 1), (2, 2), (3, 3), (7, 7)]:
            cache, result, calls = load(items, failing)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(len(calls), expected)
            self.assertEqual(cache.load(as_of=chips.CUTOFF, calendar_version=chips.CALENDAR_VERSION)["status"], "unavailable")
            self.assertEqual(len(calls), expected)

    def test_original_receipt_tamper_and_capture_type_rejected(self):
        items, _, _ = synthetic_captures()
        altered = replace(items[0])
        object.__setattr__(altered, "original_receipt_bytes", b"{}")
        with self.assertRaises(ValueError):
            chips._checked_capture(altered)
        from worker import tpex_institutional_1006 as old
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        oldcapture = old.CapturedCSV1006(items[0].source_id, items[0].requested_date, items[0].url,
            items[0].body, items[0].body_sha256, now, now, old.POLICY_VERSION, old.POLICY_DIGEST,
            old.PROFILE, old.window_policy()["sources"][items[0].source_id]["source_version"])
        self.assertEqual(summarize([oldcapture, *items[1:]])["status"], "unavailable")

    def test_success_has_exact22_and_frozen_receipts(self):
        items, _, _ = synthetic_captures()
        cache, result, calls = load(items)
        self.assertEqual(result["status"], "available")
        self.assertEqual(len(calls), 22)
        self.assertEqual(len(cache.raw_captures), 22)
        self.assertEqual([row["date"] for row in result["calendar"]["rows"]], [day.isoformat() for day in chips.EXPECTED_SESSIONS])
        self.assertEqual(list(chips.WINDOW_DATES[5]), list(chips.EXPECTED_SESSIONS[-5:]))
