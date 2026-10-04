"""Standalone, reconstructable synthetic boundary checks, entirely in memory.

``--w4-only`` checks the new worker contract without importing the app.
``--w4-api-only`` checks four cutoffs through the real router with an AST
config stub and SQLite :memory:; the original suites remain selectable;
``--serve`` starts an empty MockTransport cache on owned loopback 8781.
Coordinator-only ``--serve --live-source-opt-in`` admits the exact 26 source
GETs once for W4. All modes guard disk writes before imports and use no conftest,
pytest cache, capture file or app.main. Synthetic CSVs are contract checks,
not real source acceptance.
"""
from __future__ import annotations

import csv
import ast
import base64
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

GUARD_COUNTS = {"disk_write_attempts": 0, "network_connect_attempts": 0, "mutation_attempts": 0}
API_MODE = any(mode in sys.argv for mode in ("--api-only", "--w3-api-only", "--w4-api-only", "--serve"))
PRODUCT_HTTP_COUNTS = {"GET": 0, "POST": 0}
LIVE_OPT_IN = "--serve" in sys.argv and "--live-source-opt-in" in sys.argv
LISTEN_PORT = 8781 if "--serve" in sys.argv else None
LIVE_REQUEST_ACTIVE = False
LIVE_APPROVED_ADDRESSES = set()


def socketpair_context():
    frame = sys._getframe(1)
    while frame:
        if "socketpair" in frame.f_code.co_name and frame.f_code.co_filename.endswith("socket.py"):
            return True
        frame = frame.f_back
    return False


def install_zero_disk_guard() -> None:
    import os

    def audit(event, args):
        if event == "open":
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                GUARD_COUNTS["disk_write_attempts"] += 1
                raise AssertionError("unexpected_disk_write")
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            address = args[1] if event in {"socket.connect", "socket.bind"} else args[0]
            local = isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
            allowed = API_MODE and local and socketpair_context()
            allowed = allowed or (event == "socket.bind" and local and address[1] == LISTEN_PORT and LISTEN_PORT is not None)
            if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
                allowed = allowed or address in {"localhost", "127.0.0.1", "::1", None}
                allowed = allowed or (LIVE_OPT_IN and LIVE_REQUEST_ACTIVE and address in {"www.tpex.org.tw", b"www.tpex.org.tw"}
                                      and (event != "socket.getaddrinfo" or args[1] == 443))
            if event == "socket.connect" and LIVE_OPT_IN and LIVE_REQUEST_ACTIVE:
                allowed = isinstance(address, tuple) and len(address) >= 2 and (address[0], address[1]) in LIVE_APPROVED_ADDRESSES
            if allowed:
                return
            GUARD_COUNTS["network_connect_attempts"] += 1
            raise AssertionError("unexpected_real_network")
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink",
                     "tempfile.mkstemp", "tempfile.mkdtemp", "subprocess.Popen"}:
            GUARD_COUNTS["mutation_attempts"] += 1
            raise AssertionError("unexpected_filesystem_or_process_mutation")
        if event == "sqlite3.connect" and not (API_MODE and args[0] == ":memory:"):
            raise AssertionError("unexpected_database")
    sys.addaudithook(audit)


if __name__ == "__main__":
    install_zero_disk_guard()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import tpex_institutional_window as window
import httpx

OBSERVED = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)


def csv_bytes(header, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def synthetic_row(day, symbol="3105", *, large=False, zero=False, ordinal=0):
    """Independent synthetic component arithmetic; no saved official raw rows."""
    if zero:
        groups = [(0, 0, 0)] * 7
        total = 0
    elif large:
        maximum = 9223372036854775807
        groups = [(maximum, 0, maximum), (0, 0, 0), (maximum, 0, maximum)] + [(0, 0, 0)] * 4
        total = maximum
    elif symbol == "3105":
        groups = [(1000, 100, 900), (20, 10, 10), (1020, 110, 910), (10, 40, -30),
                  (20, 50, -30), (10, 15, -5), (30, 65, -35)]
        total = 835  # 900 - 30 - 35; the foreign-dealer 10 is not added again.
    else:
        groups = [(100, 600, -500), (2, 1, 1), (102, 601, -499), (50, 20, 30),
                  (10, 0, 10), (0, 15, -15), (10, 15, -5)]
        total = -475  # -500 + 30 - 5.
    if ordinal:
        groups = list(groups)
        for index, buy_delta, sell_delta in ((0, ordinal * 100, 0), (3, 0, ordinal), (4, ordinal * 3, 0)):
            buy, sell, _ = groups[index]
            groups[index] = (buy + buy_delta, sell + sell_delta, buy + buy_delta - sell - sell_delta)
        groups[2] = tuple(a + b for a, b in zip(groups[0], groups[1]))
        groups[6] = tuple(a + b for a, b in zip(groups[4], groups[5]))
        total = sum(groups[index][2] for index in (0, 3, 6))
    return [f"{day.year - 1911:03d}{day.month:02d}{day.day:02d}", symbol, "Synthetic " + symbol] + [
        str(quantity) for group in groups for quantity in group] + [str(total)]


def make_capture(source_id, day, body, **overrides):
    capture = window.CapturedCSV(source_id, day, window.source_url(source_id, day), body,
                                hashlib.sha256(body).hexdigest(), OBSERVED, OBSERVED + timedelta(seconds=1),
                                window.POLICY_VERSION, window.POLICY_DIGEST, window.PROFILE)
    return replace(capture, **overrides)


def synthetic_captures(*, large=False, zero=False, varying=False):
    captures = []
    for month in window.MONTH_REQUESTS:
        rows = [[day.strftime("%Y%m%d"), "100", "105", "95", "101", "-1"]
                for day in window.EXPECTED_SESSIONS if day.month == month.month]
        if month == date(2026, 8, 1):
            before = (3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21, 24, 25, 26, 27, 28)
            rows = [[f"202608{day:02d}", "100", "105", "95", "101", "-1"] for day in before] + rows
        captures.append(make_capture(window.INDEX_SOURCE_ID, month, csv_bytes(window.INDEX_HEADER, rows)))
    for ordinal, day in enumerate(window.DAILY_REQUESTS, 1):
        rows = [synthetic_row(day, symbol, large=large, zero=zero, ordinal=ordinal if varying else 0)
                for symbol in ("3105", "6488")]
        captures.append(make_capture(window.DAILY_SOURCE_ID, day, csv_bytes(window.DAILY_HEADER, rows)))
    return captures


def summarize(captures, **overrides):
    arguments = dict(policy=window.window_policy(), profile=window.PROFILE,
                     expected_policy_version=window.POLICY_VERSION, expected_policy_digest=window.POLICY_DIGEST,
                     as_of=window.CUTOFF, calendar_version=window.CALENDAR_VERSION)
    return window.summarize_window_captures(captures, **(arguments | overrides))


def replace_body(capture, rows, *, header=None):
    selected_header = header or (window.DAILY_HEADER if capture.source_id == window.DAILY_SOURCE_ID else window.INDEX_HEADER)
    body = csv_bytes(selected_header, rows)
    return replace(capture, body=body, body_sha256=hashlib.sha256(body).hexdigest())


def make_cache(**overrides):
    arguments = dict(policy=window.window_policy(), profile=window.PROFILE,
                     expected_policy_version=window.POLICY_VERSION, expected_policy_digest=window.POLICY_DIGEST)
    return window.MemoryWindowCache(**(arguments | overrides))


class WindowCalculationTests(unittest.TestCase):
    def setUp(self):
        self.captures = synthetic_captures()

    def window(self, result, horizon=5, symbol="3105"):
        return result["stocks"][symbol]["windows"][str(horizon)]

    def assert_daily_rejected(self, captures, reason):
        result = summarize(captures)
        self.assertEqual(result["calendar"]["status"], "available")
        self.assertIsNone(self.window(result)["values"])
        self.assertIn(reason, [item["reason"] for item in result["failures"]])
        self.assertIn("2026-10-02", self.window(result)["missing_dates"])

    def test_expected_calendar_and_independent_exact_totals(self):
        result = summarize(self.captures)
        self.assertEqual(result["status"], "available")
        self.assertEqual(len(result["calendar"]["valid_dates"]), 22)
        self.assertEqual(self.window(result)["required_dates"],
                         ["2026-09-24", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"])
        self.assertEqual(self.window(result, 20)["from"], "2026-09-03")
        self.assertEqual(self.window(result)["values"], {"foreign": "4500", "trust": "-150", "dealer": "-175"})
        self.assertEqual(self.window(result, 20)["values"], {"foreign": "18000", "trust": "-600", "dealer": "-700"})
        self.assertEqual(self.window(result, 5, "6488")["values"], {"foreign": "-2500", "trust": "150", "dealer": "-25"})
        self.assertEqual(self.window(result, 20, "6488")["values"], {"foreign": "-10000", "trust": "600", "dealer": "-100"})
        self.assertEqual(self.window(result)["daily_evidence"][0]["row"]["total_net"], "835")
        self.assertEqual(result["historical_pit"], "unsupported")
        self.assertEqual(result["revision_time"], "unknown")
        self.assertEqual(len(result["captured_versions"]), window.MAX_REQUESTS)

    def test_verified_zero_and_unbounded_integer_window_sum(self):
        zero = self.window(summarize(synthetic_captures(zero=True)), 20)
        self.assertEqual(zero["values"], {"foreign": "0", "trust": "0", "dealer": "0"})
        large = self.window(summarize(synthetic_captures(large=True)), 20)
        self.assertEqual(large["values"]["foreign"], "184467440737095516140")
        self.assertGreater(int(large["values"]["foreign"]), 9223372036854775807)

    def test_five_available_twenty_missing_never_uses_earlier_replacement(self):
        missing = window.WINDOW_DATES[20][0]
        captures = [capture for capture in self.captures if capture.requested_date != missing]
        result = summarize(captures)
        self.assertEqual(self.window(result)["status"], "available")
        self.assertIsNone(self.window(result, 20)["values"])
        self.assertEqual(self.window(result, 20)["missing_dates"], ["2026-09-03"])
        self.assertEqual(self.window(result, 20)["required_dates"][0], "2026-09-03")

    def test_invalid_early_day_keeps_five_available(self):
        bad = next(item for item in self.captures if item.source_id == window.DAILY_SOURCE_ID
                   and item.requested_date == window.WINDOW_DATES[20][0])
        captures = [replace(bad, body_sha256="0" * 64) if item is bad else item for item in self.captures]
        result = summarize(captures)
        self.assertEqual(self.window(result)["status"], "available")
        self.assertIsNone(self.window(result, 20)["values"])
        self.assertEqual(self.window(result, 20)["invalid_dates"],
                         [{"date": "2026-09-03", "reason": "capture_body_hash_mismatch"}])

    def test_competing_daily_revision_discards_both_versions(self):
        early = next(item for item in self.captures if item.source_id == window.DAILY_SOURCE_ID
                     and item.requested_date == window.WINDOW_DATES[20][0])
        captures = [item for item in self.captures if not (
            item.source_id == window.DAILY_SOURCE_ID and item.requested_date == date(2026, 9, 1))] + [early]
        result = summarize(captures)
        self.assertEqual(self.window(result)["status"], "available")
        self.assertIsNone(self.window(result, 20)["values"])
        self.assertIn("daily_competing_revision", [item["reason"] for item in result["failures"]])

    def test_policy_profile_version_digest_purpose_source_and_cutoff_gates(self):
        refused = window.window_policy()
        refused["sources"][window.DAILY_SOURCE_ID]["purposes"]["summarize"] = "unknown"
        altered = window.window_policy()
        altered["sources"][window.DAILY_SOURCE_ID]["exact_url"] = "https://example.com/csv"
        for arguments, reason in [
            ({"profile": "other"}, "policy_profile_not_supported"),
            ({"expected_policy_version": "old"}, "policy_version_mismatch"),
            ({"expected_policy_digest": "sha256:" + "0" * 64}, "policy_digest_mismatch"),
            ({"policy": refused}, "policy_purpose_not_admitted"),
            ({"policy": altered}, "policy_digest_mismatch"),
            ({"as_of": date(2026, 9, 29)}, "cutoff_not_supported"),
            ({"calendar_version": "unknown"}, "calendar_version_not_supported"),
        ]:
            with self.subTest(reason=reason):
                result = summarize(self.captures, **arguments)
                self.assertEqual(result["reasons"], [reason])
                self.assertIsNone(self.window(result)["values"])
        foreign = replace(self.captures[-1], source_id="twse_t86")
        self.assertEqual(summarize(self.captures[:-1] + [foreign])["reasons"], ["source_not_supported"])

    def test_capture_pins_method_url_time_and_header_are_rechecked(self):
        last = self.captures[-1]
        cases = [({"policy_digest": "bad"}, "capture_policy_mismatch"),
                 ({"method": "POST"}, "capture_url_or_method_mismatch"),
                 ({"url": last.url.replace("https:", "http:")}, "capture_url_or_method_mismatch"),
                 ({"url": last.url + "&extra=1"}, "capture_url_or_method_mismatch"),
                 ({"captured_at": OBSERVED - timedelta(seconds=1)}, "capture_timestamps_nonmonotonic"),
                 ({"content_type": "application/json"}, "capture_content_type_invalid"),
                 ({"content_encoding": "gzip"}, "capture_content_encoding_invalid")]
        for changes, reason in cases:
            with self.subTest(reason=reason):
                self.assert_daily_rejected(self.captures[:-1] + [replace(last, **changes)], reason)

    def test_untrusted_capture_field_shapes_fail_closed_without_receipt_exception(self):
        last = self.captures[-1]
        cases = [({"requested_date": "secret/path"}, "capture_request_date_invalid"),
                 ({"request_started_at": "secret/path"}, "capture_timestamp_not_utc"),
                 ({"captured_at": None}, "capture_timestamp_not_utc"),
                 ({"captured_at": OBSERVED.replace(tzinfo=None)}, "capture_timestamp_not_utc"),
                 ({"captured_at": OBSERVED.astimezone(timezone(timedelta(hours=8)))}, "capture_timestamp_not_utc"),
                 ({"body": bytearray(last.body)}, "capture_body_type_invalid"),
                 ({"content_type": None}, "capture_metadata_type_invalid"),
                 ({"content_encoding": []}, "capture_metadata_type_invalid"),
                 ({"http_status": True}, "capture_http_status_invalid")]
        for changes, reason in cases:
            with self.subTest(reason=reason, changes=changes.keys()):
                result = summarize(self.captures[:-1] + [replace(last, **changes)])
                self.assertEqual(result["reasons"], [reason])
                self.assertIsNone(self.window(result)["values"])
                self.assertNotIn("secret/path", repr(result))
        changed = replace(last, url="C:/secret/path")
        result = summarize(self.captures[:-1] + [changed])
        self.assertIsNone(self.window(result)["values"])
        self.assertNotIn("C:/secret/path", repr(result))

    def test_bad_csv_encoding_header_column_count_and_exact_dates(self):
        day = window.CUTOFF
        rows = [synthetic_row(day, symbol) for symbol in window.SYMBOLS]
        wrong_date = [row[:] for row in rows]
        wrong_date[1][0] = "1151001"
        bad_header = list(window.DAILY_HEADER)
        bad_header[-1] += "extra"
        bodies = [(csv_bytes(bad_header, rows), "csv_header_mismatch"),
                  (csv_bytes(window.DAILY_HEADER, [rows[0][:-1], rows[1]]), "csv_column_count_mismatch"),
                  (csv_bytes(window.DAILY_HEADER, wrong_date), "daily_payload_date_mismatch"),
                  (b"\xef\xbb\xbf" + self.captures[-1].body, "csv_header_mismatch"),
                  (b"\xff", "csv_encoding_or_structure_invalid")]
        for body, reason in bodies:
            with self.subTest(reason=reason):
                bad = replace(self.captures[-1], body=body, body_sha256=hashlib.sha256(body).hexdigest())
                self.assert_daily_rejected(self.captures[:-1] + [bad], reason)

    def test_structure_and_date_are_validated_on_unselected_rows(self):
        rows = [synthetic_row(window.CUTOFF, symbol) for symbol in window.SYMBOLS]
        extra = synthetic_row(window.CUTOFF, "A001")
        extra[0] = "1151001"
        self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows + [extra])],
                                   "daily_payload_date_mismatch")
        extra[0], extra[1] = "1151002", "bad"
        self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows + [extra])],
                                   "daily_security_code_invalid")
        extra[1], extra[2] = "A001", "   "
        self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows + [extra])],
                                   "daily_company_name_missing")

    def test_duplicate_and_missing_selected_security_fail_closed(self):
        rows = [synthetic_row(window.CUTOFF, symbol) for symbol in window.SYMBOLS]
        self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows + [rows[0]])],
                                   "daily_security_code_duplicate")
        self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows[:1])],
                                   "daily_selected_symbol_missing")

    def test_canonical_quantity_negative_buy_int64_and_component_arithmetic(self):
        for value, reason in [(value, "share_quantity_invalid") for value in ["1.0", "1e3", "1,000", " 1", "01", "+1", "-0"]] + [
            ("-1", "negative_buy_or_sell"), ("9223372036854775808", "share_quantity_outside_int64")]:
            with self.subTest(value=value):
                rows = [synthetic_row(window.CUTOFF, symbol) for symbol in window.SYMBOLS]
                rows[0][3] = value
                self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows)], reason)
        for offset, value, reason in [(5, "901", "daily_net_mismatch:foreign"),
                                      (9, "1021", "daily_net_mismatch:foreign_total"),
                                      (11, "911", "daily_net_mismatch:foreign_total"),
                                      (23, "-34", "daily_net_mismatch:dealer"),
                                      (24, "845", "daily_three_investor_total_mismatch")]:
            with self.subTest(offset=offset):
                rows = [synthetic_row(window.CUTOFF, symbol) for symbol in window.SYMBOLS]
                rows[0][offset] = value
                self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows)], reason)
        for start, values, reason in [(9, ["1030", "110", "920"], "daily_foreign_components_mismatch"),
                                      (21, ["31", "65", "-34"], "daily_dealer_components_mismatch")]:
            rows = [synthetic_row(window.CUTOFF, symbol) for symbol in window.SYMBOLS]
            rows[0][start:start + 3] = values
            self.assert_daily_rejected(self.captures[:-1] + [replace_body(self.captures[-1], rows)], reason)

    def test_index_missing_closed_duplicate_wrong_month_and_ohlc_reject_all_windows(self):
        original = self.captures[0]
        normal = list(csv.reader(io.StringIO(original.body.decode("utf-8"))))[1:]
        malformed = [row[:] for row in normal]
        malformed[0][1] = "0"
        bad_high = [row[:] for row in normal]
        bad_high[0][2] = "99"
        cases = [(normal[1:], "calendar_expected_dates_missing"),
                 (normal + [["20260925", "100", "105", "95", "101", "-1"]], "index_closed_date_conflict"),
                 (normal + [normal[0]], "index_date_duplicate"),
                 (normal + [["20261001", "100", "105", "95", "101", "-1"]], "index_date_outside_scope"),
                 (malformed, "index_numeric_invalid"), (bad_high, "index_ohlc_bounds_invalid")]
        for rows, reason in cases:
            with self.subTest(reason=reason):
                result = summarize([replace_body(original, rows)] + self.captures[1:])
                self.assertEqual(result["calendar"]["status"], "unavailable")
                self.assertEqual(result["reasons"], [reason])
                self.assertIsNone(self.window(result)["values"])
                self.assertIsNone(self.window(result, 20)["values"])

    def test_index_nonfinite_bad_header_and_competing_revision(self):
        index = self.captures[1]
        rows = [["20261001", "100", "105", "95", "101", "NaN"],
                ["20261002", "100", "105", "95", "101", "-1"]]
        self.assertEqual(summarize(self.captures[:1] + [replace_body(index, rows)] + self.captures[2:])["reasons"],
                         ["index_numeric_invalid"])
        header = list(window.INDEX_HEADER)
        header[1] = "Open"
        self.assertEqual(summarize(self.captures[:1] + [replace_body(index, rows, header=header)] + self.captures[2:])["reasons"],
                         ["csv_header_mismatch"])
        self.assertEqual(summarize(self.captures[:2] + [self.captures[0]] + self.captures[3:])["reasons"],
                         ["calendar_competing_revision"])

    def test_body_and_aggregate_limits_are_checked_before_parsing(self):
        body = b"x" * (2 * 1024 * 1024 + 1)
        large = replace(self.captures[-1], body=body, body_sha256=hashlib.sha256(body).hexdigest())
        self.assert_daily_rejected(self.captures[:-1] + [large], "capture_body_size_limit")
        with patch.object(window, "MAX_TOTAL_BYTES", 1):
            self.assertEqual(summarize(self.captures)["reasons"], ["capture_total_size_limit"])
        self.assertEqual(summarize(self.captures + [self.captures[-1]])["reasons"], ["capture_count_limit"])


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.captures = synthetic_captures()
        self.bodies = {capture.url: capture.body for capture in self.captures}
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.headers["Accept-Encoding"], "identity")
        self.assertEqual(request.extensions["timeout"]["read"], 15.0)
        return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"},
                              stream=httpx.ByteStream(self.bodies[str(request.url)]))

    def load(self, cache=None, handler=None):
        cache = cache or make_cache()
        result = cache.load(as_of=window.CUTOFF, calendar_version=window.CALENDAR_VERSION,
                            transport=httpx.MockTransport(handler or self.handler))
        return cache, result

    def test_one_bounded_load_shared_by_two_symbols_and_read_get_never_fetches(self):
        cache, result = self.load()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["request_count"], window.MAX_REQUESTS)
        self.assertEqual(len(self.requests), window.MAX_REQUESTS)
        self.assertEqual(len(cache.raw_captures), window.MAX_REQUESTS)
        for symbol in ("3105", "6488"):
            read = cache.get("TPEx", symbol, window.CUTOFF)
            self.assertEqual(set(read["stocks"]), {symbol})
            read["stocks"][symbol]["windows"]["5"]["values"]["foreign"] = "tampered"
            self.assertNotEqual(cache.get("TPEx", symbol, window.CUTOFF)["stocks"][symbol]["windows"]["5"]["values"]["foreign"], "tampered")
        self.assertEqual(len(self.requests), window.MAX_REQUESTS)
        self.assertEqual(cache.get("TWSE", "3105", window.CUTOFF)["reasons"], ["window_market_or_symbol_not_supported"])
        self.assertEqual(cache.get("TPEx", "3105", None)["reasons"], ["cutoff_not_supported"])
        self.assertEqual(cache.load(as_of=window.CUTOFF, calendar_version=window.CALENDAR_VERSION)["reasons"],
                         ["window_load_already_attempted"])
        self.assertEqual(len(self.requests), window.MAX_REQUESTS)
        with self.assertRaises(FrozenInstanceError):
            cache.raw_captures[0].body = b"tampered"

    def test_invalid_policy_and_cutoff_perform_no_request(self):
        for cache, arguments, reason in [
            (make_cache(expected_policy_version="wrong"), {}, "policy_version_mismatch"),
            (make_cache(profile="other"), {}, "policy_profile_not_supported"),
            (make_cache(), {"as_of": date(2026, 9, 29)}, "cutoff_not_supported"),
            (make_cache(), {"calendar_version": "unknown"}, "calendar_version_not_supported")]:
            result = cache.load(**({"as_of": window.CUTOFF, "calendar_version": window.CALENDAR_VERSION} | arguments),
                                transport=httpx.MockTransport(self.handler))
            self.assertEqual(result["reasons"], [reason])
            self.assertEqual(cache.request_count, 0)
        self.assertEqual(self.requests, [])

    def test_daily_timeout_redirect_http_failure_are_not_retried_and_keep_other_dates(self):
        first_daily = next(item.url for item in self.captures if item.source_id == window.DAILY_SOURCE_ID
                           and item.requested_date == window.WINDOW_DATES[20][0])
        for failure in ("timeout", "redirect", "refused"):
            with self.subTest(failure=failure):
                self.requests = []
                def handler(request):
                    if str(request.url) != first_daily:
                        return self.handler(request)
                    self.requests.append(request)
                    if failure == "timeout":
                        raise httpx.ReadTimeout("synthetic timeout", request=request)
                    return httpx.Response(302 if failure == "redirect" else 403,
                                          headers={"Location": "https://example.com/forbidden"})
                cache, result = self.load(handler=handler)
                self.assertEqual(len(self.requests), window.MAX_REQUESTS)
                self.assertEqual(sum(str(request.url) == first_daily for request in self.requests), 1)
                self.assertEqual(result["stocks"]["3105"]["windows"]["5"]["status"], "available")
                self.assertIsNone(result["stocks"]["3105"]["windows"]["20"]["values"])
                self.assertEqual(result["stocks"]["3105"]["windows"]["20"]["missing_dates"], ["2026-09-03"])
                self.assertIn("request_timeout" if failure == "timeout" else "http_status:" + ("302" if failure == "redirect" else "403"),
                              [item["reason"] for item in result["failures"]])

    def test_bad_daily_body_retains_hash_and_time_but_not_values(self):
        last_url = self.captures[-1].url
        self.bodies[last_url] = csv_bytes(["bad header"], [["1151002"]])
        cache, result = self.load()
        self.assertEqual(len(cache.raw_captures), window.MAX_REQUESTS)
        self.assertIsNone(result["stocks"]["3105"]["windows"]["5"]["values"])
        self.assertEqual(cache.raw_captures[-1].body_sha256, hashlib.sha256(self.bodies[last_url]).hexdigest())
        self.assertEqual(cache.raw_captures[-1].captured_at.utcoffset(), timedelta(0))
        self.assertIn("csv_header_mismatch", [item["reason"] for item in result["failures"]])

    def test_invalid_calendar_stops_daily_requests_and_redirect_is_not_followed(self):
        for content in ("missing", "redirect"):
            with self.subTest(content=content):
                self.requests = []
                first_index = self.captures[0].url
                def handler(request):
                    if str(request.url) != first_index:
                        return self.handler(request)
                    self.requests.append(request)
                    if content == "redirect":
                        return httpx.Response(302, headers={"Location": "https://example.com/forbidden"})
                    rows = list(csv.reader(io.StringIO(self.bodies[first_index].decode("utf-8"))))
                    return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"},
                                          stream=httpx.ByteStream(csv_bytes(rows[0], rows[2:])))
                _, result = self.load(handler=handler)
                self.assertEqual(len(self.requests), 2)
                self.assertEqual(result["calendar"]["status"], "unavailable")
                self.assertIsNone(result["stocks"]["3105"]["windows"]["5"]["values"])

    def test_stream_body_limit_keeps_no_oversized_capture(self):
        bad_url = self.captures[-1].url
        def handler(request):
            if str(request.url) != bad_url:
                return self.handler(request)
            self.requests.append(request)
            return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"},
                                  stream=httpx.ByteStream(b"x" * (2 * 1024 * 1024 + 1)))
        cache, result = self.load(handler=handler)
        self.assertEqual(len(self.requests), window.MAX_REQUESTS)
        self.assertEqual(len(cache.raw_captures), window.MAX_REQUESTS - 1)
        self.assertIn("capture_body_size_limit", [item["reason"] for item in result["failures"]])
        self.assertIsNone(result["stocks"]["3105"]["windows"]["5"]["values"])


def import_memory_api():
    """Read the real config AST, omit its mkdir, retain constants, use memory DB."""
    if __name__ == "__main__" and "app.config" not in sys.modules:
        config_path = Path(__file__).resolve().parents[1] / "app" / "config.py"
        tree = ast.parse(config_path.read_text(encoding="utf-8"), filename=str(config_path))
        tree.body = [node for node in tree.body if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "mkdir")]
        config = types.ModuleType("app.config")
        config.__file__ = str(config_path)
        exec(compile(tree, str(config_path), "exec"), config.__dict__)
        config.DATA_DIR, config.RAW_DIR, config.DB_PATH = Path("__memory_only__"), Path("__memory_only__/raw"), Path(":memory:")
        sys.modules["app.config"] = config
    from app import api, institutional_windows
    return api, institutional_windows


class ApprovedLiveTransport(httpx.BaseTransport):
    """Opt-in serve only: worker URLs/methods/bounds checked before each socket."""
    def __init__(self):
        if not LIVE_OPT_IN:
            raise ValueError("live_source_opt_in_required")
        import socket
        self.original_resolver = socket.getaddrinfo
        def resolve(host, port, *args, **kwargs):
            answers = self.original_resolver(host, port, *args, **kwargs)
            if LIVE_REQUEST_ACTIVE and host in {"www.tpex.org.tw", b"www.tpex.org.tw"} and port == 443:
                LIVE_APPROVED_ADDRESSES.update((answer[4][0], answer[4][1]) for answer in answers)
            return answers
        self.resolver = resolve
        socket.getaddrinfo = self.resolver
        self.inner = httpx.HTTPTransport(retries=0, trust_env=False)
        self.urls = {capture.url for capture in synthetic_captures()}
        self.requests = []

    def handle_request(self, request):
        global LIVE_REQUEST_ACTIVE
        target = str(request.url)
        if request.method != "GET" or target not in self.urls or target in self.requests or len(self.requests) >= window.MAX_REQUESTS:
            raise AssertionError("unapproved_source_request")
        self.requests.append(target)
        LIVE_REQUEST_ACTIVE = True
        try:
            return self.inner.handle_request(request)
        finally:
            LIVE_REQUEST_ACTIVE = False

    def close(self):
        import socket
        self.inner.close()
        if socket.getaddrinfo is self.resolver:
            socket.getaddrinfo = self.original_resolver


class MemoryAPIFixture:
    """Synthetic catalog only; institution data is MockTransport unless opt-in."""
    def __init__(self, *, live=False, failure=None, large=False, varying=False):
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from starlette.responses import JSONResponse
        self.api, self.wrapper = import_memory_api()
        from app.db import Base
        from app.models import Instrument, MarketBar
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.include_router(self.api.router)
        with Session(self.engine) as db:
            for exchange, symbol in (("TPEx", "3105"), ("TPEx", "6488"), ("TPEx", "9999"), ("TWSE", "3105")):
                item = Instrument(market="TW", exchange=exchange, symbol=symbol, name="Synthetic catalog " + symbol,
                                  instrument_type="stock", status="active")
                db.add(item)
                db.flush()
                db.add(MarketBar(instrument_id=item.id, trading_date=window.CUTOFF, open=10, high=11, low=9,
                                 close=10, adj_close=10, volume=1000, source="synthetic-memory", is_suspended=False))
            db.commit()
        def database():
            with Session(self.engine) as db:
                yield db
        self.app.dependency_overrides[self.api.get_db] = database
        self.requests = []
        captures = synthetic_captures(varying=varying)
        self.bodies = {capture.url: capture.body for capture in captures}
        if large:
            for capture in captures:
                if capture.source_id != window.DAILY_SOURCE_ID:
                    continue
                self.bodies[capture.url] = csv_bytes(window.DAILY_HEADER, [synthetic_row(capture.requested_date, symbol, large=True) for symbol in window.SYMBOLS])
        def handler(request):
            self.requests.append(str(request.url))
            if failure == "calendar" and str(request.url) == captures[0].url:
                return httpx.Response(200, headers={"Content-Type": "application/csv"}, stream=httpx.ByteStream(b"bad\n"))
            if failure == "status" and str(request.url) == window.source_url(window.DAILY_SOURCE_ID, date(2026, 8, 31)):
                return httpx.Response(503, stream=httpx.ByteStream(b"synthetic unavailable"))
            failed_date = date(2026, 9, 3) if failure == "partial" else failure
            if any(str(request.url) == item.url and item.source_id == window.DAILY_SOURCE_ID
                   and item.requested_date == failed_date for item in captures):
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"}, stream=httpx.ByteStream(self.bodies[str(request.url)]))
        self.transport = ApprovedLiveTransport() if live else httpx.MockTransport(handler)
        self.store = self.wrapper.InstitutionalWindowStore(transport=self.transport)
        self.store_patch = patch.object(self.wrapper, "STORE", self.store)
        self.env_patch = patch.dict(os.environ, {self.wrapper.ENABLE_ENV: "1"})
        self.store_patch.start()
        self.env_patch.start()
        self.before = self.database_snapshot()
        @self.app.middleware("http")
        async def preview_scope(request, call_next):
            path = request.url.path
            if request.method in PRODUCT_HTTP_COUNTS:
                PRODUCT_HTTP_COUNTS[request.method] += 1
            allowed_post = request.method == "POST" and path in {
                f"/api/stocks/{exchange}/{symbol}/institutional-windows/capture"
                for exchange, symbol in (("TPEx", "3105"), ("TPEx", "6488"), ("TPEx", "9999"), ("TWSE", "3105"), ("TPEx", "missing"))}
            if request.method not in {"GET", "OPTIONS"} and not allowed_post:
                return JSONResponse({"detail": "preview operation outside scope"}, status_code=405)
            return await call_next(request)
        @self.app.get("/__window_validation/receipt")
        def receipt(include_raw: bool = False):
            value = self.receipt(include_raw=include_raw)
            if include_raw and len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")) > 8 * 1024 * 1024:
                return JSONResponse({"detail": "validation raw response exceeds 8 MiB"}, status_code=413)
            print(json.dumps({"validation_receipt": True, "mode": value["mode"], "pid": value["pid"],
                              "request_count": value["request_count"], "captures": len(value["captures"]),
                              "selected_raw_rows": len(value["selected_raw_rows"]),
                              "supported_cutoffs": list(value["cutoff_snapshots"]),
                              "db_preserved": value["db_preserved"], "db_tables": value["db_tables"],
                              "guard": value["guard"], "disk_artifacts": 0}), flush=True)
            return value

    def database_snapshot(self):
        with self.engine.connect() as connection:
            names = [row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            result = {}
            for name in names:
                quoted = '"' + name.replace('"', '""') + '"'
                columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(" + quoted + ")")]
                expressions = ','.join('typeof("' + column.replace('"', '""') + '")' for column in columns)
                result[name] = [tuple(row) for row in connection.exec_driver_sql("SELECT *," + expressions + " FROM " + quoted + " ORDER BY rowid")]
            return result

    def receipt(self, *, include_raw=False):
        cache = self.store._cache
        snapshot = cache.snapshot() if cache else None
        captures = self.store.raw_captures
        selected_raw_rows = []
        for capture in captures:
            if capture.source_id != window.DAILY_SOURCE_ID:
                continue
            for ordinal, row in enumerate(list(csv.reader(io.StringIO(capture.body.decode("utf-8"))))[1:], 1):
                if len(row) == 25 and row[1] in window.SYMBOLS:
                    selected_raw_rows.append({"date": capture.requested_date.isoformat(), "body_sha256": capture.body_sha256,
                                              "row_ordinal": ordinal, "fields": row})
        result = {"mode": "live-approved-source-memory" if LIVE_OPT_IN else "synthetic-memory",
                "pid": os.getpid(), "parent_pid": os.getppid(), "port": LISTEN_PORT, "request_count": cache.request_count if cache else 0,
                "captures": [capture.receipt() for capture in captures], "snapshot": snapshot,
                "cutoff_snapshots": {day.isoformat(): cache.snapshot(day) for day in window.CUTOFFS} if cache else {},
                "selected_raw_rows": selected_raw_rows,
                "db_preserved": self.before == self.database_snapshot(), "db_tables": len(self.before),
                "guard": dict(GUARD_COUNTS), "live_socket_scope": "exact transport URL + resolved www.tpex.org.tw:443 addresses while request active",
                "live_resolved_addresses": sorted(LIVE_APPROVED_ADDRESSES), "disk_artifacts": 0}
        if include_raw:
            result["raw_csv_captures"] = [{"source_id": item.source_id, "requested_date": item.requested_date.isoformat(),
                                           "url": item.url, "body_sha256": item.body_sha256,
                                           "body_base64": base64.b64encode(item.body).decode("ascii")} for item in captures]
        return result

    def close(self):
        self.env_patch.stop()
        self.store_patch.stop()
        self.app.dependency_overrides.clear()
        self.transport.close()
        self.engine.dispose()


class InstitutionalWindowAPITests(unittest.TestCase):
    def fixture(self, **kwargs):
        fixture = MemoryAPIFixture(**kwargs)
        self.addCleanup(fixture.close)
        self.addCleanup(lambda: self.assertEqual(fixture.before, fixture.database_snapshot()))
        return fixture

    def test_get_is_offline_first_post_shares_one_version_and_same_cutoff(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            before = client.get("/api/stocks/TPEx/3105/overview?as_of=2026-10-02").json()
            self.assertEqual(before["institutional"]["reasons"], ["window_memory_capture_missing"])
            self.assertEqual(fixture.requests, [])
            first = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-02").json()
            self.assertEqual(first["status"], "available")
            self.assertEqual(first["capture_state"]["action"], "acquired")
            self.assertEqual(len(fixture.requests), window.MAX_REQUESTS)
            for symbol, expected in (("3105", "4500"), ("6488", "-2500")):
                repeated = client.post(f"/api/stocks/TPEx/{symbol}/institutional-windows/capture?as_of=2026-10-02").json()
                detail = client.get(f"/api/stocks/TPEx/{symbol}?as_of=2026-10-02").json()
                overview = client.get(f"/api/stocks/TPEx/{symbol}/overview?as_of=2026-10-02").json()
                self.assertEqual(detail["overview"]["as_of"], "2026-10-02")
                self.assertEqual(repeated, detail["overview"]["institutional"])
                self.assertEqual(repeated, overview["institutional"])
                self.assertEqual(repeated["windows"]["5"]["values"]["foreign"], expected)
                self.assertTrue(all(item["status"] == "data_insufficient" for item in overview["conditions"]))
                self.assertEqual(repeated["provenance"], first["provenance"])
            default = client.post("/api/stocks/TPEx/3105/institutional-windows/capture").json()
            self.assertEqual(default["as_of"], "2026-10-02")
            self.assertEqual(default["capture_state"]["request_count"], window.MAX_REQUESTS)
            self.assertEqual(len(fixture.requests), window.MAX_REQUESTS)

    def test_disabled_invalid_unknown_market_symbol_and_cutoff_never_fetch(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            missing_cutoff = fixture.store.read("TPEx", "3105", None, environment={fixture.wrapper.ENABLE_ENV: ""})
            self.assertEqual(missing_cutoff["reasons"], ["window_capture_not_enabled"])
            self.assertEqual(missing_cutoff["windows"], {})
            self.assertEqual(missing_cutoff["capture_state"]["request_count"], 0)
            self.assertFalse(missing_cutoff["capture_state"]["attempted"])
            for setting, reason in (("", "window_capture_not_enabled"), ("0", "window_capture_not_enabled"), ("true", "window_capture_configuration_invalid")):
                with patch.dict(os.environ, {fixture.wrapper.ENABLE_ENV: setting}):
                    result = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-02").json()
                    self.assertEqual(result["reasons"], [reason])
            for route, reason in (("TWSE/3105", "window_market_or_symbol_not_supported"), ("TPEx/9999", "window_market_or_symbol_not_supported")):
                self.assertEqual(client.post(f"/api/stocks/{route}/institutional-windows/capture?as_of=2026-10-02").json()["reasons"], [reason])
            self.assertEqual(client.post("/api/stocks/TPEx/missing/institutional-windows/capture?as_of=2026-10-02").status_code, 404)
            for cutoff in ("2026-09-29", "2026-10-03", "2099-01-01"):
                result = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=" + cutoff).json()
                self.assertEqual(result["as_of"], cutoff)
                self.assertEqual(result["supported_scope"]["supported_cutoffs"], [day.isoformat() for day in window.CUTOFFS])
                self.assertEqual(result["windows"], {})
                self.assertEqual(result["reasons"], ["window_cutoff_not_supported"])
            self.assertEqual(client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=bad").status_code, 422)
            self.assertEqual(fixture.requests, [])
            self.assertFalse(fixture.store._attempted)

    def test_partial_keeps_five_failed_calendar_keeps_all_unavailable_and_never_retries(self):
        from fastapi.testclient import TestClient
        for failure, requests in (("partial", window.MAX_REQUESTS), ("calendar", 2)):
            fixture = MemoryAPIFixture(failure=failure)
            try:
                with TestClient(fixture.app) as client:
                    result = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-02").json()
                    self.assertEqual(result["windows"]["5"]["status"], "available" if failure == "partial" else "unavailable")
                    self.assertIsNone(result["windows"]["20"]["values"])
                    if failure == "partial":
                        self.assertEqual(result["windows"]["20"]["missing_dates"], ["2026-09-03"])
                    for _ in range(2):
                        client.post("/api/stocks/TPEx/6488/institutional-windows/capture?as_of=2026-10-02")
                    self.assertEqual(len(fixture.requests), requests)
                    self.assertEqual(fixture.before, fixture.database_snapshot())
            finally:
                fixture.close()

    def test_busy_lock_and_pinned_policy_failure_are_defined_and_not_retried(self):
        fixture = self.fixture()
        fixture.store._lock.acquire()
        try:
            result = fixture.store.capture("TPEx", "3105", window.CUTOFF)
            self.assertEqual(result["reasons"], ["window_capture_busy"])
            self.assertFalse(fixture.store._attempted)
        finally:
            fixture.store._lock.release()
        with patch.object(fixture.wrapper, "POLICY_DIGEST", "sha256:" + "0" * 64):
            result = fixture.store.capture("TPEx", "3105", window.CUTOFF)
        self.assertEqual(result["reasons"], ["policy_digest_mismatch"])
        self.assertEqual(fixture.requests, [])
        fixture.store.capture("TPEx", "6488", window.CUTOFF)
        self.assertEqual(fixture.requests, [])

    def test_api_serializes_large_window_integer_and_refuses_cached_future(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture(large=True)
        with TestClient(fixture.app) as client:
            result = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-02").json()
            self.assertEqual(result["windows"]["20"]["values"]["foreign"], "184467440737095516140")
            refused = client.get("/api/stocks/TPEx/3105/overview?as_of=2026-10-03").json()
            self.assertEqual(refused["institutional"]["windows"], {})
            self.assertEqual(refused["institutional"]["reasons"], ["window_cutoff_not_supported"])
            self.assertEqual(len(fixture.requests), window.MAX_REQUESTS)


W3_SESSIONS = tuple(date.fromisoformat(day) for day in (
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08",
    "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16",
    "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
    "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"))
W3_DATES = {
    date(2026, 9, 30): {5: W3_SESSIONS[15:20], 20: W3_SESSIONS[:20]},
    date(2026, 10, 1): {5: W3_SESSIONS[16:21], 20: W3_SESSIONS[1:21]},
    date(2026, 10, 2): {5: W3_SESSIONS[17:22], 20: W3_SESSIONS[2:22]},
}


def w3_expected(symbol, days):
    # Independent arithmetic over the fixed test dates, not production windows
    # or reported net values. Day variation makes leaked/fallback dates visible.
    base = (900, -30, -35) if symbol == "3105" else (-500, 30, -5)
    ordinals = [W3_SESSIONS.index(day) + 1 for day in days]
    return {key: str(sum(base[index] + ordinal * delta for ordinal in ordinals))
            for index, (key, delta) in enumerate((("foreign", 100), ("trust", -1), ("dealer", 3)))}


class WindowCutoffTests(unittest.TestCase):
    def setUp(self):
        self.captures = synthetic_captures(varying=True)

    def test_exact_external_policy_pin_and_new_bounded_request_union(self):
        encoded = json.dumps(window.window_policy(), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual("sha256:" + hashlib.sha256(encoded).hexdigest(),
                         "sha256:9de27224cc57512f4e38455717eb51f8512eb890667119a5d02444810e0ad4db")
        self.assertEqual(window.POLICY_DIGEST, "sha256:9de27224cc57512f4e38455717eb51f8512eb890667119a5d02444810e0ad4db")
        self.assertEqual(window.POLICY_VERSION, "m1-w3-tpex-window-2026-10-04.1")
        self.assertEqual(window.DAILY_REQUESTS, W3_SESSIONS)
        self.assertEqual((window.MAX_REQUESTS, window.MAX_TOTAL_BYTES), (24, 48234496))
        self.assertEqual(len(self.captures), 24)
        self.assertEqual(window.window_policy()["scope"]["supported_cutoffs"], [day.isoformat() for day in W3_DATES])
        self.assertNotIn("as_of", window.window_policy()["scope"])

    def test_three_fixed_cutoffs_all_36_nets_and_no_future_window_evidence(self):
        checked = 0
        for cutoff, horizons in W3_DATES.items():
            result = summarize(self.captures, as_of=cutoff)
            self.assertEqual(result["as_of"], cutoff.isoformat())
            self.assertEqual(result["version"], "tpex-institutional-window/w3-v1")
            self.assertEqual(result["calendar"]["valid_dates"], [day.isoformat() for day in W3_SESSIONS])
            for symbol in ("3105", "6488"):
                for horizon, days in horizons.items():
                    item = result["stocks"][symbol]["windows"][str(horizon)]
                    self.assertEqual(item["required_dates"], [day.isoformat() for day in days])
                    self.assertEqual(item["valid_dates"], item["required_dates"])
                    self.assertEqual(item["values"], w3_expected(symbol, days))
                    self.assertEqual([row["row"]["date"] for row in item["daily_evidence"]], item["required_dates"])
                    self.assertTrue(all(row["row"]["date"] <= result["as_of"] for row in item["daily_evidence"]))
                    self.assertTrue(all(row["provenance"]["requested_date"] == row["row"]["date"]
                                        for row in item["daily_evidence"]))
                    checked += len(item["values"])
            self.assertEqual(len(result["captured_versions"]), 24)
            self.assertEqual(result["historical_pit"], "unsupported")
        self.assertEqual(checked, 36)

    def test_missing_or_invalid_dates_only_affect_windows_that_require_them(self):
        for failed_day in (date(2026, 9, 1), date(2026, 9, 2), date(2026, 10, 2)):
            for invalid in (False, True):
                with self.subTest(failed_day=failed_day, invalid=invalid):
                    captures = [replace(item, body_sha256="0" * 64) if invalid and item.source_id == window.DAILY_SOURCE_ID
                                and item.requested_date == failed_day
                                else item for item in self.captures if invalid or not (
                                    item.source_id == window.DAILY_SOURCE_ID and item.requested_date == failed_day)]
                    for cutoff, horizons in W3_DATES.items():
                        result = summarize(captures, as_of=cutoff)
                        for symbol in ("3105", "6488"):
                            for horizon, days in horizons.items():
                                item = result["stocks"][symbol]["windows"][str(horizon)]
                                missing = [failed_day.isoformat()] if failed_day in days else []
                                self.assertEqual(item["missing_dates"], missing)
                                self.assertEqual(item["required_dates"], [day.isoformat() for day in days])
                                self.assertEqual(item["values"], None if missing else w3_expected(symbol, days))
                                self.assertEqual(item["invalid_dates"], [{"date": failed_day.isoformat(),
                                                  "reason": "capture_body_hash_mismatch"}] if missing and invalid else [])

    def test_competing_new_date_discards_both_versions_without_fallback(self):
        duplicate = next(item for item in self.captures if item.source_id == window.DAILY_SOURCE_ID
                         and item.requested_date == date(2026, 9, 2))
        captures = self.captures[:-1] + [duplicate]  # 24 total: competing 9/2 and missing 10/2.
        for cutoff, horizons in W3_DATES.items():
            result = summarize(captures, as_of=cutoff)
            for horizon, days in horizons.items():
                item = result["stocks"]["3105"]["windows"][str(horizon)]
                missing = [day.isoformat() for day in days if day in (date(2026, 9, 2), date(2026, 10, 2))]
                self.assertEqual(item["missing_dates"], missing)
                self.assertEqual(item["values"], None if missing else w3_expected("3105", days))
            self.assertIn("daily_competing_revision", [item["reason"] for item in result["failures"]])

    def test_full_calendar_failure_rejects_even_the_earlier_cutoff(self):
        index = self.captures[1]
        rows = list(csv.reader(io.StringIO(index.body.decode("utf-8"))))[1:-1]
        captures = self.captures[:1] + [replace_body(index, rows)] + self.captures[2:]
        for cutoff in W3_DATES:
            result = summarize(captures, as_of=cutoff)
            self.assertEqual(result["calendar"]["status"], "unavailable")
            self.assertEqual(result["as_of"], cutoff.isoformat())
            self.assertTrue(all(item["values"] is None for stock in result["stocks"].values()
                                for item in stock["windows"].values()))

    def test_once_only_loader_and_cutoff_reads_share_immutable_24_capture_batch(self):
        bodies = {item.url: item.body for item in self.captures}
        requests = []
        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"},
                                  stream=httpx.ByteStream(bodies[str(request.url)]))
        cache = make_cache()
        first = cache.load(as_of=date(2026, 9, 30), calendar_version=window.CALENDAR_VERSION,
                           transport=httpx.MockTransport(handler))
        self.assertEqual(first["as_of"], "2026-09-30")
        self.assertEqual(len(requests), 24)
        self.assertEqual(len(set(requests)), 24)
        versions = first["captured_versions"]
        for cutoff in W3_DATES:
            for symbol in ("3105", "6488"):
                item = cache.get("TPEx", symbol, cutoff)
                self.assertEqual(item["captured_versions"], versions)
                self.assertEqual(item["stocks"][symbol]["windows"]["20"]["values"], w3_expected(symbol, W3_DATES[cutoff][20]))
                item["stocks"][symbol]["windows"]["20"]["values"]["foreign"] = "tampered"
                self.assertNotEqual(cache.get("TPEx", symbol, cutoff)["stocks"][symbol]["windows"]["20"]["values"]["foreign"], "tampered")
        self.assertEqual(cache.load(as_of=date(2026, 10, 1), calendar_version=window.CALENDAR_VERSION)["reasons"],
                         ["window_load_already_attempted"])
        self.assertEqual(len(requests), 24)

    def test_new_pin_and_outside_cutoff_or_request_date_are_rejected(self):
        altered = window.window_policy()
        altered["scope"]["supported_cutoffs"].append("2026-10-03")
        self.assertEqual(summarize(self.captures, policy=altered)["reasons"], ["policy_digest_mismatch"])
        for cutoff in (date(2026, 9, 29), date(2026, 10, 3)):
            result = summarize(self.captures, as_of=cutoff)
            self.assertEqual(result["as_of"], cutoff.isoformat())
            self.assertEqual(result["reasons"], ["cutoff_not_supported"])
            self.assertEqual(result["stocks"]["3105"]["windows"], {})
        for day in (date(2026, 8, 31), date(2026, 9, 25), date(2026, 10, 5)):
            with self.assertRaises(window.WindowEvidenceError):
                window.source_url(window.DAILY_SOURCE_ID, day)
        for arguments in ({"as_of": date(2026, 9, 29)}, {"calendar_version": "wrong"}):
            cache = make_cache()
            result = cache.load(**({"as_of": date(2026, 9, 30), "calendar_version": window.CALENDAR_VERSION} | arguments),
                                transport=httpx.MockTransport(lambda request: self.fail("must not request")))
            self.assertEqual(cache.request_count, 0)
            self.assertEqual(result["status"], "unavailable")
        cache = make_cache(expected_policy_digest="sha256:" + "0" * 64)
        cache.load(as_of=date(2026, 9, 30), calendar_version=window.CALENDAR_VERSION,
                   transport=httpx.MockTransport(lambda request: self.fail("must not request")))
        self.assertEqual(cache.request_count, 0)


class WindowCutoffAPITests(unittest.TestCase):
    def fixture(self, **kwargs):
        fixture = MemoryAPIFixture(varying=True, **kwargs)
        self.addCleanup(fixture.close)
        self.addCleanup(lambda: self.assertEqual(fixture.before, fixture.database_snapshot()))
        return fixture

    def test_actual_router_detail_overview_and_posts_share_three_cutoffs_and_one_batch(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            for cutoff in W3_DATES:
                for symbol in ("3105", "6488"):
                    before = client.get(f"/api/stocks/TPEx/{symbol}/overview?as_of={cutoff}").json()
                    self.assertEqual(before["institutional"]["reasons"], ["window_memory_capture_missing"])
            self.assertEqual(fixture.requests, [])
            first = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-09-30").json()
            self.assertEqual(first["capture_state"]["action"], "acquired")
            for cutoff, horizons in W3_DATES.items():
                for symbol in ("3105", "6488"):
                    item = client.post(f"/api/stocks/TPEx/{symbol}/institutional-windows/capture?as_of={cutoff}").json()
                    detail = client.get(f"/api/stocks/TPEx/{symbol}?as_of={cutoff}").json()
                    overview = client.get(f"/api/stocks/TPEx/{symbol}/overview?as_of={cutoff}").json()
                    self.assertEqual((overview["version"], item["version"]), ("stock-overview/w3-v1", "institutional-windows/w3-v1"))
                    self.assertEqual(overview["as_of"], str(cutoff))
                    self.assertEqual(detail["overview"]["as_of"], str(cutoff))
                    self.assertEqual(item["as_of"], str(cutoff))
                    self.assertEqual(item, overview["institutional"])
                    self.assertEqual(item, detail["overview"]["institutional"])
                    self.assertEqual(item["provenance"], first["provenance"])
                    for horizon, days in horizons.items():
                        self.assertEqual(item["windows"][str(horizon)]["values"], w3_expected(symbol, days))
                    self.assertTrue(all(condition["status"] == "data_insufficient" for condition in overview["conditions"]))
            self.assertEqual(len(fixture.requests), 24)
            self.assertEqual(fixture.receipt()["request_count"], 24)

    def test_first_post_also_accepts_each_later_supported_cutoff(self):
        from fastapi.testclient import TestClient
        for cutoff in (date(2026, 10, 1), date(2026, 10, 2)):
            fixture = MemoryAPIFixture(varying=True)
            try:
                with TestClient(fixture.app) as client:
                    item = client.post(f"/api/stocks/TPEx/6488/institutional-windows/capture?as_of={cutoff}").json()
                    self.assertEqual(item["as_of"], str(cutoff))
                    self.assertEqual(item["windows"]["20"]["values"], w3_expected("6488", W3_DATES[cutoff][20]))
                    self.assertEqual(item["capture_state"]["request_count"], 24)
                self.assertEqual(fixture.before, fixture.database_snapshot())
            finally:
                fixture.close()

    def test_unsupported_before_or_after_cache_and_independent_app_pin_never_fetch(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            for cutoff in ("2026-09-29", "2026-10-03", "2099-01-01"):
                item = client.post(f"/api/stocks/TPEx/3105/institutional-windows/capture?as_of={cutoff}").json()
                self.assertEqual(item["windows"], {})
                self.assertEqual(item["reasons"], ["window_cutoff_not_supported"])
            self.assertEqual(fixture.requests, [])
            self.assertFalse(fixture.store._attempted)
            client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-01")
            for cutoff in ("2026-09-29", "2026-10-03", "2099-01-01"):
                item = client.get(f"/api/stocks/TPEx/3105/overview?as_of={cutoff}").json()["institutional"]
                self.assertEqual(item["as_of"], cutoff)
                self.assertEqual(item["windows"], {})
                self.assertEqual(item["reasons"], ["window_cutoff_not_supported"])
            self.assertEqual(len(fixture.requests), 24)
        isolated = fixture.wrapper.InstitutionalWindowStore(transport=httpx.MockTransport(lambda request: self.fail("must not fetch")))
        with patch.object(fixture.wrapper, "POLICY_DIGEST", "sha256:" + "0" * 64):
            result = isolated.capture("TPEx", "3105", date(2026, 9, 30))
        self.assertEqual(result["reasons"], ["policy_digest_mismatch"])
        self.assertEqual(isolated.capture("TPEx", "6488", date(2026, 10, 1))["capture_state"]["request_count"], 0)

    def test_future_daily_failure_keeps_earlier_api_windows_available(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture(failure=date(2026, 10, 2))
        with TestClient(fixture.app) as client:
            first = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-09-30").json()
            self.assertEqual(first["status"], "available")
            for cutoff in W3_DATES:
                for symbol in ("3105", "6488"):
                    item = client.get(f"/api/stocks/TPEx/{symbol}/overview?as_of={cutoff}").json()["institutional"]
                    self.assertEqual(item["status"], "unavailable" if cutoff == date(2026, 10, 2) else "available")
                    for horizon in (5, 20):
                        self.assertEqual(item["windows"][str(horizon)]["missing_dates"],
                                         ["2026-10-02"] if cutoff == date(2026, 10, 2) else [])
            self.assertEqual(len(fixture.requests), 24)

    def test_new_cutoff_api_keeps_window_integer_strings_exact(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture(large=True)
        with TestClient(fixture.app) as client:
            first = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-01").json()
            overview = client.get("/api/stocks/TPEx/3105/overview?as_of=2026-10-01").json()
            self.assertEqual(first["windows"]["20"]["values"]["foreign"], "184467440737095516140")
            self.assertEqual(overview["institutional"]["windows"], first["windows"])


W4_SESSIONS = (date(2026, 8, 31),) + W3_SESSIONS
W4_DATES = {
    date(2026, 9, 29): {5: W4_SESSIONS[15:20], 20: W4_SESSIONS[:20]},
    date(2026, 9, 30): {5: W4_SESSIONS[16:21], 20: W4_SESSIONS[1:21]},
    date(2026, 10, 1): {5: W4_SESSIONS[17:22], 20: W4_SESSIONS[2:22]},
    date(2026, 10, 2): {5: W4_SESSIONS[18:23], 20: W4_SESSIONS[3:23]},
}


def w4_expected(symbol, days):
    base = (900, -30, -35) if symbol == "3105" else (-500, 30, -5)
    return {key: str(sum(base[index] + (W4_SESSIONS.index(day) + 1) * delta for day in days))
            for index, (key, delta) in enumerate((("foreign", 100), ("trust", -1), ("dealer", 3)))}


class WindowEarlierCutoffTests(unittest.TestCase):
    def setUp(self):
        self.captures = synthetic_captures(varying=True)

    def test_external_pin_26_requests_and_exact_new_query_forms(self):
        encoded = json.dumps(window.window_policy(), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        pin = "sha256:576e72676c23efedd3fc857a90e57c2e58f438a8669ba39dea2faa132f7616df"
        self.assertEqual((len(encoded), "sha256:" + hashlib.sha256(encoded).hexdigest()), (3509, pin))
        self.assertEqual((window.POLICY_VERSION, window.POLICY_DIGEST), ("m1-w4-tpex-window-2026-10-04.1", pin))
        self.assertEqual((window.MAX_REQUESTS, window.MAX_TOTAL_BYTES), (26, 51380224))
        self.assertEqual(window.DAILY_REQUESTS, W4_SESSIONS)
        self.assertEqual(window.CUTOFFS, tuple(W4_DATES))
        self.assertEqual(len(self.captures), 26)
        self.assertEqual(window.source_url(window.DAILY_SOURCE_ID, date(2026, 8, 31)),
                         "https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F08%2F31")
        self.assertEqual(window.source_url(window.INDEX_SOURCE_ID, date(2026, 8, 1)),
                         "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F08%2F01")

    def test_four_fixed_cutoffs_48_nets_exact_dates_and_future_exclusion(self):
        checked = 0
        for cutoff, horizons in W4_DATES.items():
            result = summarize(self.captures, as_of=cutoff)
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["version"], "tpex-institutional-window/w4-v1")
            self.assertEqual(result["calendar"]["valid_dates"], [str(day) for day in W4_SESSIONS])
            self.assertEqual(len(result["captured_versions"]), 26)
            for symbol in ("3105", "6488"):
                for horizon, days in horizons.items():
                    item = result["stocks"][symbol]["windows"][str(horizon)]
                    self.assertEqual(item["required_dates"], [str(day) for day in days])
                    self.assertEqual(item["valid_dates"], item["required_dates"])
                    self.assertEqual(item["values"], w4_expected(symbol, days))
                    self.assertEqual([entry["row"]["date"] for entry in item["daily_evidence"]], item["required_dates"])
                    self.assertTrue(all(entry["row"]["date"] <= str(cutoff)
                                        and entry["provenance"]["requested_date"] == entry["row"]["date"]
                                        for entry in item["daily_evidence"]))
                    checked += len(item["values"])
        self.assertEqual(checked, 48)

    def test_august_all_21_rows_are_validated_but_only_last_is_adopted(self):
        result = summarize(self.captures, as_of=date(2026, 9, 29))
        receipt = result["calendar"]["evidence"][0]
        self.assertEqual((receipt["candidate_count"], receipt["adopted_count"], receipt["pre_calendar_row_count"]), (21, 1, 20))
        self.assertEqual(receipt["validation_scope"], "all_returned_month_rows")
        first = result["calendar"]["rows"][0]
        self.assertEqual((first["date"], first["row_ordinal"]), ("2026-08-31", 21))
        self.assertTrue(all(row["date"] >= "2026-08-31" for row in result["calendar"]["rows"]))

    def test_missing_and_bad_august_31_september_21_or_future_day_affect_only_required_windows(self):
        for failed_day in (date(2026, 8, 31), date(2026, 9, 21), date(2026, 10, 2)):
            for invalid in (False, True):
                captures = [replace(item, body_sha256="0" * 64) if invalid and item.source_id == window.DAILY_SOURCE_ID
                            and item.requested_date == failed_day else item for item in self.captures
                            if invalid or not (item.source_id == window.DAILY_SOURCE_ID and item.requested_date == failed_day)]
                for cutoff, horizons in W4_DATES.items():
                    result = summarize(captures, as_of=cutoff)
                    for symbol in ("3105", "6488"):
                        for horizon, days in horizons.items():
                            item = result["stocks"][symbol]["windows"][str(horizon)]
                            missing = [str(failed_day)] if failed_day in days else []
                            self.assertEqual(item["missing_dates"], missing)
                            self.assertEqual(item["values"], None if missing else w4_expected(symbol, days))
                            self.assertEqual(item["invalid_dates"], [{"date": str(failed_day), "reason": "capture_body_hash_mismatch"}]
                                             if missing and invalid else [])

    def test_invalid_pre_calendar_rows_are_never_hidden_by_adoption_filter(self):
        august = self.captures[0]
        original = list(csv.reader(io.StringIO(august.body.decode("utf-8"))))[1:]
        cases = []
        for column, value, reason in ((1, "NaN", "index_numeric_invalid"), (2, "0", "index_numeric_invalid"),
                                      (3, "104", "index_ohlc_bounds_invalid"), (5, "Infinity", "index_numeric_invalid"),
                                      (0, "20260731", "index_date_outside_scope"), (0, "20260801", "index_closed_date_conflict")):
            rows = [list(row) for row in original]
            rows[0][column] = value
            cases.append((rows, reason))
        cases.extend([(original + [original[0]], "index_date_duplicate"),
                      (original + [original[-1]], "index_date_duplicate"),
                      ([original[0][:-1]] + original[1:], "csv_column_count_mismatch")])
        for rows, reason in cases:
            with self.subTest(reason=reason, first=rows[0]):
                for cutoff in W4_DATES:
                    result = summarize([replace_body(august, rows)] + self.captures[1:], as_of=cutoff)
                    self.assertEqual(result["calendar"]["status"], "unavailable")
                    self.assertEqual(result["reasons"], [reason])
                    self.assertTrue(all(item["values"] is None for stock in result["stocks"].values()
                                        for item in stock["windows"].values()))

    def test_incomplete_closed_extra_and_future_index_days_reject_full_calendar(self):
        for position, extra, reason in ((0, None, "calendar_expected_dates_missing"),
                                        (1, "20260925", "index_closed_date_conflict"),
                                        (1, "20260926", "index_closed_date_conflict"),
                                        (2, "20261005", "index_date_outside_scope")):
            index = self.captures[position]
            rows = list(csv.reader(io.StringIO(index.body.decode("utf-8"))))[1:]
            rows = rows[:-1] if extra is None else rows + [[extra, "100", "105", "95", "101", "-1"]]
            captures = self.captures[:position] + [replace_body(index, rows)] + self.captures[position + 1:]
            for cutoff in W4_DATES:
                result = summarize(captures, as_of=cutoff)
                self.assertEqual(result["reasons"], [reason])
                self.assertEqual(result["calendar"]["status"], "unavailable")

    def test_once_only_loader_holds_26_immutable_versions_for_both_stocks_four_cutoffs(self):
        bodies = {item.url: item.body for item in self.captures}
        requests = []
        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, headers={"Content-Type": "application/csv;charset=utf-8"},
                                  stream=httpx.ByteStream(bodies[str(request.url)]))
        cache = make_cache()
        first = cache.load(as_of=date(2026, 9, 29), calendar_version=window.CALENDAR_VERSION,
                           transport=httpx.MockTransport(handler))
        self.assertEqual((cache.request_count, len(requests), len(set(requests))), (26, 26, 26))
        versions = first["captured_versions"]
        for cutoff, horizons in W4_DATES.items():
            for symbol in ("3105", "6488"):
                item = cache.get("TPEx", symbol, cutoff)
                self.assertEqual(item["captured_versions"], versions)
                self.assertEqual(item["stocks"][symbol]["windows"]["20"]["values"], w4_expected(symbol, horizons[20]))
                item["stocks"][symbol]["windows"]["20"]["values"]["foreign"] = "tampered"
                self.assertNotEqual(cache.get("TPEx", symbol, cutoff)["stocks"][symbol]["windows"]["20"]["values"]["foreign"], "tampered")
        self.assertEqual(cache.load(as_of=date(2026, 10, 2), calendar_version=window.CALENDAR_VERSION)["reasons"], ["window_load_already_attempted"])
        self.assertEqual(len(requests), 26)

    def test_old_pin_profile_outside_cutoff_and_new_url_corruption_fail_without_fetch(self):
        for arguments in ({"expected_policy_digest": "sha256:9de27224cc57512f4e38455717eb51f8512eb890667119a5d02444810e0ad4db"},
                          {"expected_policy_version": "m1-w3-tpex-window-2026-10-04.1"}, {"profile": "production"}):
            cache = make_cache(**arguments)
            self.assertEqual(cache.load(as_of=date(2026, 9, 29), calendar_version=window.CALENDAR_VERSION,
                                       transport=httpx.MockTransport(lambda request: self.fail("must not request")))["status"], "unavailable")
            self.assertEqual(cache.request_count, 0)
        for cutoff in (date(2026, 8, 28), date(2026, 9, 28), date(2026, 10, 3)):
            cache = make_cache()
            self.assertEqual(cache.load(as_of=cutoff, calendar_version=window.CALENDAR_VERSION,
                                       transport=httpx.MockTransport(lambda request: self.fail("must not request")))["reasons"], ["cutoff_not_supported"])
            self.assertEqual(cache.request_count, 0)
        for day in (date(2026, 8, 28), date(2026, 9, 25), date(2026, 10, 5)):
            with self.assertRaises(window.WindowEvidenceError):
                window.source_url(window.DAILY_SOURCE_ID, day)
        daily = self.captures[3]
        result = summarize(self.captures[:3] + [replace(daily, url=daily.url + "&unapproved=1")] + self.captures[4:], as_of=date(2026, 9, 29))
        self.assertEqual(result["stocks"]["3105"]["windows"]["20"]["invalid_dates"],
                         [{"date": "2026-08-31", "reason": "capture_url_or_method_mismatch"}])

    def test_large_int64_inputs_exact_unbounded_window_sums_and_zero(self):
        for cutoff in W4_DATES:
            large = summarize(synthetic_captures(large=True), as_of=cutoff)
            zero = summarize(synthetic_captures(zero=True), as_of=cutoff)
            for symbol in ("3105", "6488"):
                for horizon in (5, 20):
                    values = large["stocks"][symbol]["windows"][str(horizon)]["values"]
                    self.assertEqual(values["foreign"], str(9223372036854775807 * horizon))
                    self.assertEqual(zero["stocks"][symbol]["windows"][str(horizon)]["values"], {"foreign": "0", "trust": "0", "dealer": "0"})
        daily = self.captures[3]
        rows = [synthetic_row(date(2026, 8, 31), symbol, large=True) for symbol in ("3105", "6488")]
        rows[0][3] = "9223372036854775808"
        result = summarize(self.captures[:3] + [replace_body(daily, rows)] + self.captures[4:], as_of=date(2026, 9, 29))
        self.assertEqual(result["stocks"]["3105"]["windows"]["20"]["invalid_dates"][0]["reason"], "share_quantity_outside_int64")


class WindowEarlierCutoffAPITests(unittest.TestCase):
    def fixture(self, **kwargs):
        fixture = MemoryAPIFixture(varying=True, **kwargs)
        self.addCleanup(fixture.close)
        self.addCleanup(lambda: self.assertEqual(fixture.before, fixture.database_snapshot()))
        return fixture

    def test_actual_router_both_stocks_four_cutoffs_48_nets_and_one_26_version_batch(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            before = client.get("/api/stocks/TPEx/3105/overview?as_of=2026-09-29").json()
            self.assertEqual(before["institutional"]["reasons"], ["window_memory_capture_missing"])
            self.assertEqual(fixture.requests, [])
            first = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-09-29").json()
            self.assertEqual(first["capture_state"]["action"], "acquired")
            checked = 0
            for cutoff, horizons in W4_DATES.items():
                for symbol in ("3105", "6488"):
                    item = client.post(f"/api/stocks/TPEx/{symbol}/institutional-windows/capture?as_of={cutoff}").json()
                    detail = client.get(f"/api/stocks/TPEx/{symbol}?as_of={cutoff}").json()
                    overview = client.get(f"/api/stocks/TPEx/{symbol}/overview?as_of={cutoff}").json()
                    self.assertEqual((overview["version"], item["version"]), ("stock-overview/w4-v1", "institutional-windows/w4-v1"))
                    self.assertEqual(item["as_of"], str(cutoff))
                    self.assertEqual(item, detail["overview"]["institutional"])
                    self.assertEqual(item, overview["institutional"])
                    self.assertEqual(item["provenance"], first["provenance"])
                    self.assertEqual(item["capture_state"]["request_count"], 26)
                    for horizon, days in horizons.items():
                        self.assertEqual(item["windows"][str(horizon)]["values"], w4_expected(symbol, days))
                        checked += 3
            self.assertEqual((checked, len(fixture.requests)), (48, 26))
            self.assertTrue(fixture.receipt()["db_preserved"])
            self.assertNotIn("raw_csv_captures", fixture.receipt())
            raw = client.get("/__window_validation/receipt?include_raw=1").json()["raw_csv_captures"]
            self.assertEqual(len(raw), 26)
            for entry, held in zip(raw, fixture.store.raw_captures):
                body = base64.b64decode(entry["body_base64"], validate=True)
                self.assertEqual(body, held.body)
                self.assertEqual(hashlib.sha256(body).hexdigest(), entry["body_sha256"])
            self.assertEqual(len(fixture.requests), 26)

    def test_first_post_accepts_each_other_supported_cutoff(self):
        from fastapi.testclient import TestClient
        for cutoff in tuple(W4_DATES)[1:]:
            fixture = MemoryAPIFixture(varying=True)
            try:
                with TestClient(fixture.app) as client:
                    item = client.post(f"/api/stocks/TPEx/6488/institutional-windows/capture?as_of={cutoff}").json()
                    overview = client.get(f"/api/stocks/TPEx/6488/overview?as_of={cutoff}").json()
                    self.assertEqual(item["windows"]["20"]["values"], w4_expected("6488", W4_DATES[cutoff][20]))
                    self.assertEqual(overview["institutional"]["windows"], item["windows"])
                    self.assertEqual(overview["institutional"]["provenance"], item["provenance"])
                    self.assertEqual(item["capture_state"]["action"], "acquired")
                    self.assertEqual(overview["institutional"]["capture_state"]["action"], "cached")
                    self.assertEqual(len(fixture.requests), 26)
                self.assertEqual(fixture.before, fixture.database_snapshot())
            finally:
                fixture.close()

    def test_unsupported_date_market_status_and_old_wrapper_pin_never_fetch_or_show_stale_values(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            for cutoff in ("2026-09-28", "2026-10-03"):
                item = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=" + cutoff).json()
                self.assertEqual(item["windows"], {})
                self.assertEqual(item["reasons"], ["window_cutoff_not_supported"])
            item = client.post("/api/stocks/TWSE/3105/institutional-windows/capture?as_of=2026-09-29").json()
            self.assertEqual(item["reasons"], ["window_market_or_symbol_not_supported"])
            self.assertEqual(client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=bad").status_code, 422)
            self.assertEqual(fixture.requests, [])
            client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-09-29")
            for item in (client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-09-28").json(),
                         client.get("/api/stocks/TPEx/3105/overview?as_of=2026-09-28").json()["institutional"]):
                self.assertEqual(item["windows"], {})
                self.assertEqual(item["capture_state"]["request_count"], 26)
            self.assertEqual(len(fixture.requests), 26)
        isolated = fixture.wrapper.InstitutionalWindowStore(transport=httpx.MockTransport(lambda request: self.fail("must not fetch")))
        with patch.object(fixture.wrapper, "POLICY_DIGEST", "sha256:9de27224cc57512f4e38455717eb51f8512eb890667119a5d02444810e0ad4db"):
            item = isolated.capture("TPEx", "3105", date(2026, 9, 29))
        self.assertEqual(item["reasons"], ["policy_digest_mismatch"])
        self.assertEqual(isolated.capture("TPEx", "6488", date(2026, 10, 2))["capture_state"]["request_count"], 0)

    def test_status_timeout_and_bad_calendar_failures_never_retry_and_keep_unaffected_cutoffs(self):
        from fastapi.testclient import TestClient
        for failure in ("status", date(2026, 8, 31), date(2026, 10, 2), "calendar"):
            fixture = MemoryAPIFixture(varying=True, failure=failure)
            try:
                with TestClient(fixture.app) as client:
                    client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-09-29")
                    for cutoff in W4_DATES:
                        item = client.get(f"/api/stocks/TPEx/6488/overview?as_of={cutoff}").json()["institutional"]
                        unavailable = failure == "calendar" or (failure in ("status", date(2026, 8, 31)) and cutoff == date(2026, 9, 29)) or failure == cutoff
                        self.assertEqual(item["status"], "unavailable" if unavailable else "available")
                        if failure in ("status", date(2026, 8, 31)) and cutoff == date(2026, 9, 29):
                            self.assertEqual(item["windows"]["5"]["status"], "available")
                            self.assertEqual(item["windows"]["20"]["missing_dates"], ["2026-08-31"])
                    self.assertEqual(len(fixture.requests), 3 if failure == "calendar" else 26)
                self.assertEqual(fixture.before, fixture.database_snapshot())
            finally:
                fixture.close()

    def test_new_earlier_cutoff_api_preserves_exact_large_integer_strings(self):
        from fastapi.testclient import TestClient
        fixture = self.fixture(large=True)
        with TestClient(fixture.app) as client:
            item = client.post("/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-09-29").json()
            overview = client.get("/api/stocks/TPEx/3105/overview?as_of=2026-09-29").json()
            self.assertEqual(item["windows"]["20"]["values"]["foreign"], "184467440737095516140")
            self.assertEqual(item["windows"], overview["institutional"]["windows"])


def main():
    if "--live-source-opt-in" in sys.argv and not LIVE_OPT_IN:
        raise ValueError("live_requires_serve")
    if "--serve" in sys.argv:
        import uvicorn
        fixture = MemoryAPIFixture(live=LIVE_OPT_IN, varying=any(mode in sys.argv for mode in ("--w3-only", "--w4-only")))
        try:
            print(json.dumps({"mode": "live-opt-in-empty-cache" if LIVE_OPT_IN else "mock-empty-cache", "pid": os.getpid(),
                              "parent_pid": os.getppid(), "port": LISTEN_PORT, "api": "http://127.0.0.1:8781",
                              "catalog": "synthetic-memory", "capture_env": "1", "capture_attempts": 0, "disk_artifacts": 0}), flush=True)
            uvicorn.run(fixture.app, host="127.0.0.1", port=LISTEN_PORT, lifespan="off", access_log=False)
        finally:
            print(json.dumps({"shutdown": True, "db_preserved": fixture.before == fixture.database_snapshot(), "guard": GUARD_COUNTS}), flush=True)
            fixture.close()
        return 0
    if "--w4-api-only" in sys.argv:
        suite, suite_name = unittest.defaultTestLoader.loadTestsFromTestCase(WindowEarlierCutoffAPITests), "w4-api-only"
        if "--w4-api-case" in sys.argv:
            selected = sys.argv[sys.argv.index("--w4-api-case") + 1]
            if selected != "first-post":
                raise ValueError("unsupported_w4_api_case")
            suite = unittest.TestSuite([WindowEarlierCutoffAPITests("test_first_post_accepts_each_other_supported_cutoff")])
            suite_name = "w4-api-first-post-only"
    elif "--w4-only" in sys.argv:
        suite, suite_name = unittest.defaultTestLoader.loadTestsFromTestCase(WindowEarlierCutoffTests), "w4-worker-only"
    elif "--w3-api-only" in sys.argv:
        suite, suite_name = unittest.defaultTestLoader.loadTestsFromTestCase(WindowCutoffAPITests), "w3-api-only"
    elif "--w3-only" in sys.argv:
        suite, suite_name = unittest.defaultTestLoader.loadTestsFromTestCase(WindowCutoffTests), "w3-worker-only"
    elif API_MODE:
        suite, suite_name = unittest.defaultTestLoader.loadTestsFromTestCase(InstitutionalWindowAPITests), "new-api-only"
    else:
        suite, suite_name = unittest.TestSuite([
            unittest.defaultTestLoader.loadTestsFromTestCase(WindowCalculationTests),
            unittest.defaultTestLoader.loadTestsFromTestCase(LoaderTests)]), "legacy-worker"
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"synthetic_only": True, "suite": suite_name, "cases": outcome.testsRun,
                      "python": sys.version.split()[0], "httpx": httpx.__version__, "policy_version": window.POLICY_VERSION,
                      "policy_digest": window.POLICY_DIGEST, "guard": GUARD_COUNTS,
                      "product_http": PRODUCT_HTTP_COUNTS, "disk_artifacts": 0}), flush=True)
    return 0 if outcome.wasSuccessful() and not any(GUARD_COUNTS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
