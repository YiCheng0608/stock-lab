"""Small reconstructed CSVs are synthetic contract fixtures, never official raw."""
from __future__ import annotations
from contextlib import ExitStack
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
from http.client import HTTPResponse
import io
import unittest
from unittest.mock import patch

from worker import tpex_price_capture as worker


def csv_body(rows=None, header=None):
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\r\n").writerows([header or worker.HEADER, *(rows if rows is not None else fixture_rows())])
    return stream.getvalue().encode("utf-8")


def fixture_rows(cutoff=worker.CUTOFF, *, policy_version=None):
    # Reconstructed selected six values from root receipt; other fields are synthetic.
    if cutoff == worker.NEW_CUTOFF:
        rows = [
            ["1151006", "3105", "穩懋", "592.00", "0", "615.00", "623.00", "588.00", "0", "19731700", "11863581093", "0", "0", "0", "0", "0", "0", "0"],
            ["1151006", "6488", "環球晶", "1205.00", "0", "1175.00", "1260.00", "1145.00", "0", "13913614", "16835605385", "0", "0", "0", "0", "0", "0", "0"],
        ]
        if policy_version == worker.SCOPE_POLICY_VERSION:
            rows.insert(1, ["1151006", "5347", "世界", "191.00", "0", "184.50", "195.00", "184.50", "0", "34637793", "6615109776", "0", "0", "0", "0", "0", "0", "0"])
        return rows
    return [
        ["1151005", "3105", "穩懋", "615.00", "0", "614.00", "630.00", "604.00", "0", "48127911", "29694939981", "0", "0", "0", "0", "0", "0", "0"],
        ["1151005", "6488", "環球晶", "1180.00", "0", "1220.00", "1235.00", "1175.00", "0", "18982607", "22887612060", "0", "0", "0", "0", "0", "0", "0"],
        ["1151005", "9999", "synthetic structural-only row", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad", "bad"],
    ]


class Response:
    def __init__(self, body, status=200, url=worker.ENDPOINT, headers=None):
        self.body = io.BytesIO(body)
        self.status = status
        self.url = url
        self.headers = {"Content-Type": "application/csv;charset=utf-8", **(headers or {})}
    def geturl(self): return self.url
    def read1(self, size): return self.body.read(size)
    def __enter__(self): return self
    def __exit__(self, *args): self.body.close()


class Opener:
    def __init__(self, body, **options):
        self.body, self.options, self.calls = body, options, []
    def open(self, request, timeout):
        self.calls.append((request.full_url, request.method, timeout))
        return Response(self.body, **self.options)


class SyntheticPolicyScope:
    """Test-only private policy/body anchors. Production anchors remain unchanged."""
    def __init__(self, body=None, *, cutoff=worker.CUTOFF, policy_version=None):
        self.cutoff = cutoff
        self.policy_version = policy_version or (worker.POLICY_VERSION if cutoff == worker.CUTOFF else "m1-price-tpex-11370-2026-10-06.1")
        self.body = csv_body(fixture_rows(cutoff, policy_version=self.policy_version)) if body is None else body
        self.stack = ExitStack()
    def __enter__(self):
        from app import tpex_price as store
        policy = worker.price_policy(self.cutoff, policy_version=self.policy_version)
        policy["validation"]["expected_body_sha256"] = hashlib.sha256(self.body).hexdigest()
        scope = self.policy_version == worker.SCOPE_POLICY_VERSION
        self.stack.enter_context(patch.object(worker, "_POLICY_STOCK_SCOPE_20261006" if scope else "_POLICY" if self.cutoff == worker.CUTOFF else "_POLICY_20261006", policy))
        self.stack.enter_context(patch.object(store, "POLICY_DIGEST_STOCK_SCOPE" if scope else "POLICY_DIGEST" if self.cutoff == worker.CUTOFF else "POLICY_DIGEST_20261006", worker.digest(policy)))
        self.store_module = store
        version, pin = store.policy_pins(self.cutoff, policy_version=self.policy_version)
        self.env = {store.ENABLE_ENV: "1", store.POLICY_VERSION_ENV: version, store.POLICY_DIGEST_ENV: pin}
        self.opener = Opener(self.body)
        self.timeouts = []
        def loader(**kwargs):
            return worker.capture_price(**kwargs, opener=self.opener,
                set_timeout=lambda response, seconds: self.timeouts.append(seconds),
                now=lambda: datetime(2026, 10, 5, 14, 1, 32, tzinfo=timezone.utc))
        self.loader = loader
        return self
    def __exit__(self, *args): return self.stack.__exit__(*args)


class PriceParserTests(unittest.TestCase):
    def test_three_stock_tuple_preserves_old_policies_and_rejects_bad_third(self):
        old = worker.price_policy()
        legacy = worker.price_policy(worker.NEW_CUTOFF, policy_version="m1-price-tpex-11370-2026-10-06.1")
        scope = worker.price_policy(worker.NEW_CUTOFF)
        self.assertEqual((scope["version"], len(worker.canonical_bytes(scope)), worker.digest(scope)),
                         (worker.SCOPE_POLICY_VERSION, 1484, "sha256:6e662d5fc91957b586becdf41f351d5abf2c41cec09909de468e62e76cda4a78"))
        self.assertEqual(worker.digest(old), "sha256:452b9b8cfa3d050b79ea1a85b3e4ed643c40cf3d17882b8cb809ffdb7143deea")
        self.assertEqual(worker.digest(legacy), "sha256:fc7b1451f6ae47145a5b40c3e08cdcad7ac8b9dafc64c7bf89f95c67cfefc288")
        self.assertEqual(worker.SYMBOLS, {"3105": "穩懋", "6488": "環球晶"})
        worker.validate_policy(scope, scope["version"], worker.digest(scope))
        rows = fixture_rows(worker.NEW_CUTOFF, policy_version=worker.SCOPE_POLICY_VERSION)
        selected = worker.parse_price_csv(csv_body(rows), cutoff=worker.NEW_CUTOFF)["selected"]
        self.assertEqual(list(selected), ["3105", "5347", "6488"])
        self.assertEqual(tuple(selected["5347"][key] for key in ("open", "high", "low", "close", "volume_exact", "turnover_exact")),
                         (184.5, 195, 184.5, 191, "34637793", "6615109776"))
        for change in ((2, "wrong"), (3, "0"), (6, "180"), (9, "01"), (10, "9223372036854775808")):
            bad = deepcopy(rows); bad[1][change[0]] = change[1]
            with self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(csv_body(bad), cutoff=worker.NEW_CUTOFF)
        with self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(csv_body([rows[0], rows[2]]), cutoff=worker.NEW_CUTOFF)
        with self.assertRaises(worker.PriceCaptureError): worker.price_policy(worker.NEW_CUTOFF, policy_version="unknown")
        self.assertEqual(set(worker.parse_price_csv(csv_body(rows), cutoff=worker.NEW_CUTOFF, policy_version=legacy["version"])["selected"]), set(worker.SYMBOLS))
        with SyntheticPolicyScope(cutoff=worker.NEW_CUTOFF, policy_version=worker.SCOPE_POLICY_VERSION) as f:
            capture = f.loader(policy=worker.price_policy(worker.NEW_CUTOFF), expected_policy_version=worker.SCOPE_POLICY_VERSION,
                               expected_policy_digest=f.env[f.store_module.POLICY_DIGEST_ENV])
            self.assertEqual((capture.receipt["worker_version"], capture.receipt["selected_symbols"]),
                             ("tpex-price-capture/m2-stock-scope-v1", ["3105", "5347", "6488"]))

    def test_two_immutable_policy_versions_and_new_date_structure(self):
        old, new = worker.price_policy(), worker.price_policy(worker.NEW_CUTOFF, policy_version="m1-price-tpex-11370-2026-10-06.1")
        self.assertEqual(worker.digest(new), "sha256:fc7b1451f6ae47145a5b40c3e08cdcad7ac8b9dafc64c7bf89f95c67cfefc288")
        self.assertEqual(len(worker.canonical_bytes(new)), 1462)
        worker.validate_policy(new, "m1-price-tpex-11370-2026-10-06.1", worker.digest(new))
        for policy, version, pin in ((old, new["version"], worker.digest(new)), (new, old["version"], worker.digest(old))):
            with self.assertRaises(worker.PriceCaptureError): worker.validate_policy(policy, version, pin)
        new["scope"]["cutoff"] = "2026-10-07"
        self.assertEqual(worker.price_policy(worker.NEW_CUTOFF)["scope"]["cutoff"], "2026-10-06")
        body = csv_body(fixture_rows(worker.NEW_CUTOFF))
        parsed = worker.parse_price_csv(body, cutoff=worker.NEW_CUTOFF, policy_version="m1-price-tpex-11370-2026-10-06.1")
        self.assertEqual((parsed["row_count"], parsed["date"]), (2, "2026-10-06"))
        self.assertEqual(tuple(parsed["selected"]["3105"][key] for key in ("open", "high", "low", "close", "volume_exact", "turnover_exact")), (615, 623, 588, 592, "19731700", "11863581093"))
        with self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(body)
        with self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(csv_body(), cutoff=worker.NEW_CUTOFF)

    def test_approved_policy_anchor_and_source_scope(self):
        policy = worker.price_policy()
        self.assertEqual(worker.digest(policy), "sha256:452b9b8cfa3d050b79ea1a85b3e4ed643c40cf3d17882b8cb809ffdb7143deea")
        worker.validate_policy(policy, worker.POLICY_VERSION, worker.digest(policy))
        for version, digest in (("other", worker.digest(policy)), (worker.POLICY_VERSION, "sha256:" + "0" * 64)):
            with self.assertRaises(worker.PriceCaptureError): worker.validate_policy(policy, version, digest)

    def test_reconstructed_selected_twelve_values_and_all_row_structure(self):
        value = worker.parse_price_csv(csv_body())
        self.assertEqual(value["row_count"], 3)
        self.assertEqual(value["financial_validation"], "selected_symbols_only")
        expected = {"3105": (614, 630, 604, 615, "48127911", "29694939981"), "6488": (1220, 1235, 1175, 1180, "18982607", "22887612060")}
        for symbol, numbers in expected.items():
            self.assertEqual(tuple(value["selected"][symbol][key] for key in ("open", "high", "low", "close", "volume_exact", "turnover_exact")), numbers)

    def test_structure_date_name_duplicate_missing_and_encoding_rejected(self):
        original = fixture_rows()
        examples = []
        for row, column, value in ((0, 0, "1151002"), (2, 0, "1151006"), (0, 2, "wrong"), (2, 1, "bad!")):
            rows = deepcopy(original); rows[row][column] = value; examples.append(csv_body(rows))
        rows = deepcopy(original); rows[2].pop(); examples.append(csv_body(rows))
        examples.extend((csv_body([*original, original[2]]), csv_body(original[:1]), csv_body(header=list(reversed(worker.HEADER))), b"\xff"))
        for body in examples:
            with self.subTest(size=len(body)), self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(body)

    def test_financial_quantity_boundary_and_invalid_whole_strings(self):
        for value in ("01", "-0", "+1", "1\n", "1\r", " 1", "1 ", "1.0", "1e3", "null", "9223372036854775808", ""):
            rows = fixture_rows(); rows[0][9] = value
            with self.subTest(value=value), self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(csv_body(rows))
        for value in ("0", "1", "9007199254740993", "9223372036854775807"):
            rows = fixture_rows(); rows[0][9] = value
            parsed = worker.parse_price_csv(csv_body(rows))["selected"]["3105"]
            self.assertEqual(parsed["volume_exact"], value)
            self.assertEqual(parsed["volume"], int(value) if int(value) <= 9007199254740991 else None)

    def test_ohlc_positive_decimal_and_bounds(self):
        for column, value in ((5, "0"), (6, "600"), (7, "620"), (3, "NaN"), (3, "1e3"), (3, "-1"), (3, "615.00\n")):
            rows = fixture_rows(); rows[0][column] = value
            with self.subTest(column=column, value=value), self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(csv_body(rows))

    def test_amount_missing_zero_invalid_are_distinct(self):
        for source, expected, status in (("", None, "unavailable"), ("0", "0", "available"), ("9223372036854775807", "9223372036854775807", "available")):
            rows = fixture_rows(); rows[0][10] = source
            selected = worker.parse_price_csv(csv_body(rows))["selected"]["3105"]
            self.assertEqual((selected["turnover_exact"], selected["turnover_status"]), (expected, status))
        rows = fixture_rows(); rows[0][10] = "null"
        with self.assertRaises(worker.PriceCaptureError): worker.parse_price_csv(csv_body(rows))


class PriceLoaderTests(unittest.TestCase):
    def test_pure_observed_admission_without_loader_and_reject_invalid_metadata(self):
        with SyntheticPolicyScope(cutoff=worker.NEW_CUTOFF) as fixture:
            policy = worker.price_policy(worker.NEW_CUTOFF, policy_version=fixture.policy_version)
            kwargs = dict(body=fixture.body, http_status=200, endpoint=worker.ENDPOINT,
                          request_started_at="2026-10-06T09:21:17.268510+00:00", captured_at="2026-10-06T09:21:22.201440+00:00",
                          policy=policy, expected_policy_version=policy["version"], expected_policy_digest=worker.digest(policy))
            value = worker.admit_observed_price_capture(**kwargs)
            worker.admit_observed_price_capture(**{**kwargs, "captured_at": "2026-10-06T09:21:47.268510+00:00"})
            self.assertEqual((value.receipt["worker_version"], value.receipt["source_version"], value.parsed["date"]),
                             ("tpex-price-capture/m1-v2", "tpex-11370/2026-10-06", "2026-10-06"))
            for key, bad in (("body", b"changed"), ("body", b""), ("http_status", 201), ("http_status", True),
                             ("endpoint", worker.ENDPOINT + "&date=1151006"), ("expected_policy_version", worker.POLICY_VERSION),
                             ("expected_policy_digest", "wrong"), ("captured_at", "2026-10-06T09:22:22+00:00"),
                             ("captured_at", "2026-10-06T09:21:16+00:00"), ("request_started_at", "2026-10-06T09:21:17"),
                             ("request_started_at", "malformed"), ("request_started_at", "2026-10-06T10:21:17.268510+01:00")):
                with self.subTest(key=key, bad=bad), self.assertRaises(worker.PriceCaptureError): worker.admit_observed_price_capture(**{**kwargs, key: bad})
            self.assertEqual(fixture.opener.calls, [])

    def test_one_request_receipt_and_remaining_deadline(self):
        with SyntheticPolicyScope() as fixture:
            capture = fixture.loader(policy=worker.price_policy(), expected_policy_version=worker.POLICY_VERSION,
                                     expected_policy_digest=worker.digest(worker.price_policy()))
            self.assertEqual(len(fixture.opener.calls), 1)
            self.assertEqual(fixture.opener.calls[0][:2], (worker.ENDPOINT, "GET"))
            self.assertTrue(all(0 < value <= 30 for value in fixture.timeouts))
            self.assertEqual(capture.receipt["body_sha256"], hashlib.sha256(fixture.body).hexdigest())
            self.assertEqual(capture.parsed["row_count"], 3)

    def test_total_deadline_before_next_read(self):
        with SyntheticPolicyScope() as fixture:
            ticks = iter((0, 0, 29, 29, 31))
            with self.assertRaisesRegex(worker.PriceCaptureError, "price_total_deadline_exceeded"):
                worker.capture_price(policy=worker.price_policy(), expected_policy_version=worker.POLICY_VERSION,
                    expected_policy_digest=worker.digest(worker.price_policy()), opener=fixture.opener,
                    clock=lambda: next(ticks), set_timeout=lambda response, seconds: fixture.timeouts.append(seconds))
            self.assertEqual(fixture.timeouts, [1])

    def test_httpresponse_closed_fp_fixed_length_chunked_and_truncation(self):
        class MemorySocket:
            def __init__(self, value): self.value = value
            def makefile(self, mode): return io.BytesIO(self.value)
        with SyntheticPolicyScope() as fixture:
            bodies = [(b"Content-Length: " + str(len(fixture.body)).encode() + b"\r\n", fixture.body, True),
                      (b"", fixture.body, True),
                      (b"Transfer-Encoding: chunked\r\n", hex(len(fixture.body))[2:].encode() + b"\r\n" + fixture.body + b"\r\n0\r\n\r\n", True),
                      (b"Content-Length: " + str(len(fixture.body) + 1).encode() + b"\r\n", fixture.body, False)]
            for header, body, succeeds in bodies:
                response = HTTPResponse(MemorySocket(b"HTTP/1.1 200 OK\r\nContent-Type: application/csv\r\n" + header + b"\r\n" + body))
                response.begin()
                response.geturl = lambda: worker.ENDPOINT
                opener = Opener(b"")
                opener.open = lambda request, timeout: response
                def timeout_check(value, seconds):
                    self.assertIsNotNone(value.fp, "never set socket timeout after normal closed-fp EOF")
                    self.assertGreater(seconds, 0)
                kwargs = dict(policy=worker.price_policy(), expected_policy_version=worker.POLICY_VERSION,
                              expected_policy_digest=worker.digest(worker.price_policy()), opener=opener, set_timeout=timeout_check)
                with self.subTest(header=header):
                    if succeeds: self.assertEqual(worker.capture_price(**kwargs).body, fixture.body)
                    else:
                        with self.assertRaisesRegex(worker.PriceCaptureError, "price_body_truncated"): worker.capture_price(**kwargs)

    def test_body_redirect_encoding_status_and_version_fail_closed(self):
        with SyntheticPolicyScope() as fixture:
            for opener in (Opener(fixture.body, status=302), Opener(fixture.body, url="https://example.com"),
                           Opener(fixture.body, headers={"Content-Encoding": "gzip"}), Opener(fixture.body, status=503),
                           Opener(fixture.body, headers={"Content-Length": str(worker.MAX_BODY_BYTES + 1)}), Opener(b"changed")):
                with self.subTest(options=opener.options), self.assertRaises(worker.PriceCaptureError):
                    worker.capture_price(policy=worker.price_policy(), expected_policy_version=worker.POLICY_VERSION,
                        expected_policy_digest=worker.digest(worker.price_policy()), opener=opener, set_timeout=lambda *args: None)
                self.assertEqual(len(opener.calls), 1)
            class VirtualResponse(Response):
                remaining = worker.MAX_BODY_BYTES + 1
                def read1(self, size):
                    amount = min(size, self.remaining); self.remaining -= amount; return b"x" * amount
            opener = Opener(b"")
            opener.open = lambda request, timeout: VirtualResponse(b"")
            with self.assertRaisesRegex(worker.PriceCaptureError, "price_body_size_invalid"):
                worker.capture_price(policy=worker.price_policy(), expected_policy_version=worker.POLICY_VERSION,
                    expected_policy_digest=worker.digest(worker.price_policy()), opener=opener, set_timeout=lambda *args: None)
