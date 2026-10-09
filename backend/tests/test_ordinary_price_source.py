"""RAM-only boundaries, not true FinMind acquisition or independent QA.

Direct entry: python -B -X utf8 backend/tests/test_ordinary_price_source.py
No pytest/conftest, application config, database, service or artifact creation.
The synthetic last-day prices use accepted public anchor facts; every preceding
value is fabricated for arithmetic tests and is never represented as old raw.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import contextlib
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import ssl
import sys
import threading
import time
import types
import typing
import unittest
from unittest.mock import patch
import urllib.parse
import uuid


SOURCE_FILE = Path(__file__).resolve().parents[1] / "app" / "ordinary_price_source.py"
GUARD_EVENTS: list[str] = []
RETAINED_ESTIMATES: list[int] = []


def _audit_guard(event: str, arguments: tuple) -> None:
    prohibited = {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink",
                  "os.truncate", "os.chmod", "os.utime", "os.system", "subprocess.Popen",
                  "socket.connect", "socket.getaddrinfo", "socket.bind", "sqlite3.connect"}
    if event in prohibited:
        GUARD_EVENTS.append(event)
        raise RuntimeError("unapproved I/O: " + event)
    if event == "open":
        filename, mode, flags = arguments
        writes = isinstance(mode, str) and any(letter in mode for letter in "wax+")
        writes = writes or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        allowed = False
        if not writes and isinstance(filename, (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(filename)).resolve()
            library = Path(sys.base_prefix).resolve()
            allowed = path == SOURCE_FILE or path == Path(__file__).resolve() or library in path.parents
        if writes or not allowed:
            GUARD_EVENTS.append("open/write" if writes else "open/private-read")
            raise RuntimeError("unapproved file I/O")


if __name__ == "__main__":
    if not sys.dont_write_bytecode:
        raise RuntimeError("This entry requires -B")
    sys.addaudithook(_audit_guard)

# Compile exactly the whitelisted source bytes, with no package import/cache.
SOURCE_BYTES = SOURCE_FILE.read_bytes()
LOADED_SOURCE_SHA256 = hashlib.sha256(SOURCE_BYTES).hexdigest()
m = types.ModuleType("ordinary_price_source_under_test")
m.__file__ = str(SOURCE_FILE)
sys.modules[m.__name__] = m
exec(compile(SOURCE_BYTES, str(SOURCE_FILE), "exec"), m.__dict__)

# External Issue #7 receipt 6081459941, independently supplied to this caller.
EXTERNAL_POLICY = json.loads('{"version":"issue7-ordinary-close-source-use-v1","scope":{"market":"TW/TPEx","symbols":["3105","3293","5274","5347","6488","6510","8069"],"as_of":"2026-10-06","start_date":"2026-09-04","end_date":"2026-10-06","calendar_version":"tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1"},"provider":"FinMind","dataset":"TaiwanStockPrice","method":"GET","source_use":"local_personal_noncommercial_observed_nominal_close_window","consumer_version":"ordinary-close-window-summary-v1","unit_policy":{"version":"finmind-tpex-reported-close-composite-twd-per-share-v1","unit":"TWD/share","basis":"provider_reported_nominal_close","evidence":"FinMind llms-full.txt lines170-178 + master d8918bc SOURCE_REGISTRY section32.2 actual TPEx OHLC canonical unit contract","provider_literal_unit_annotation":false,"inference":true,"requires_independent_qa_latest_close_anchor_match":true},"rights":"FinMind attribution; no raw redistribution, mirror, commercial use or deployment","unsupported":["historical_pit","publication_time","first_availability","revision_history","adjustment_verified","whole_window_historical_membership_verified","strategy_or_trading_use","other_cutoff"],"network":{"qa_namespace":"issue7-seven-ordinary-close-1006-v1/qa1","max_gets":7,"per_symbol_max_gets":1,"body_cap_bytes":1048576,"total_raw_cap_bytes":7340032,"retained_roots_estimate_cap_bytes":33554432,"request_seconds":20,"batch_lease_seconds":180,"deadline":"cooperative","accept_encoding":"identity","redirects":0,"retries":0,"stop_on_first_failure":true},"lifecycle":"QA sole process; full body/hash -> independent oracle -> positive getter/consumer -> finally release and exit; artifact0B"}')
EXTERNAL_POLICY_BYTES = json.dumps(EXTERNAL_POLICY, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
EXTERNAL_PIN = "97938e771f08b2a1c338916ad6afd9ae1e4174e58fadf0f4eaddf6b35f919601"
EXPECTED_DAYS = (
    "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
    "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
    "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
    "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06",
)
EXPECTED_SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
PUBLIC_ANCHORS = dict(zip(EXPECTED_SYMBOLS, map(Decimal, ("592", "780", "18985", "191", "1205", "3055", "149"))))
FIXTURE_CANDIDATE_SHA = "d8918bc6491ec8ef65874979cf88d1322df2da43"
FIXTURE_QA_SESSION = "11111111-1111-4111-8111-111111111111"
FIXTURE_ENGINEER_SESSION = "22222222-2222-4222-8222-222222222222"


def explicit_use():
    return m.ExplicitUse(EXTERNAL_PIN, EXTERNAL_POLICY["source_use"], EXTERNAL_POLICY["consumer_version"],
                         "TW/TPEx", EXPECTED_SYMBOLS, "2026-10-06", EXTERNAL_POLICY["scope"]["calendar_version"],
                         EXTERNAL_POLICY["unit_policy"]["version"], "provider_reported_nominal_close", ())


def synthetic_grant():
    # This is a synthetic test seam, never a valid external QA-start authorization.
    return m.QAReadGrant("issue7-explicit-qa-start",
                         "https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-9999999999",
                         FIXTURE_CANDIDATE_SHA, LOADED_SOURCE_SHA256, FIXTURE_QA_SESSION, FIXTURE_ENGINEER_SESSION,
                         "python -B -X utf8 synthetic-unittest-network-zero", m.QA_NAMESPACE,
                         EXTERNAL_PIN, EXTERNAL_POLICY["consumer_version"], m.ANCHOR_VERSION)


def fixture_document(symbol):
    return {"msg": "success", "status": 200,
            "data": [{"date": day, "stock_id": symbol, "close": int(PUBLIC_ANCHORS[symbol]) - 20 + index}
                     for index, day in enumerate(EXPECTED_DAYS)]}


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeResponse:
    def __init__(self, body, url, *, status=200, headers=None, failure=None, on_read=None, close_failure=None):
        self.body, self.url, self.status = body, url, status
        self.headers = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body)),
                        "Content-Encoding": "identity"} if headers is None else headers
        self.failure, self.on_read, self.close_failure = failure, on_read, close_failure
        self.offset, self.closed, self.read_calls = 0, False, 0

    def read(self, size):
        self.read_calls += 1
        if self.on_read:
            self.on_read()
        if self.failure:
            raise self.failure
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True
        if self.close_failure:
            raise self.close_failure


class OrdinaryPriceSourceTests(unittest.TestCase):
    def setUp(self):
        # Only this synthetic process, always guarded against real network.
        m._SEALED_NAMESPACES.clear()
        self.use, self.grant, self.clock = explicit_use(), synthetic_grant(), FakeClock()
        self.originals, self.oracle, self.results = {}, {}, []
        self.attempts, self.responses = [], []
        self.documents = {symbol: fixture_document(symbol) for symbol in EXPECTED_SYMBOLS}
        self.response_change = None
        self.observer_change = None
        self.release_calls = 0

    def tearDown(self):
        self.originals.clear()
        self.oracle.clear()
        self.results.clear()

    def roots(self):
        return m.RetainedRoots(self.originals, self.oracle, self.results)

    def release(self):
        self.release_calls += 1
        self.originals.clear()
        self.oracle.clear()
        self.results.clear()

    def transport(self, url, timeout, headers):
        symbol = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["data_id"][0]
        self.attempts.append((symbol, url, timeout, headers))
        body = json.dumps(self.documents[symbol], separators=(",", ":")).encode("utf-8")
        response = FakeResponse(body, url)
        if self.response_change:
            self.response_change(symbol, response)
        self.responses.append(response)
        return response

    def observe(self, body, receipt, budget):
        self.originals[receipt.symbol] = (body, receipt)
        # Expected observations come from independent stdlib parsing, never the
        # product parser/getter/summary. This remains a synthetic boundary test.
        document = json.loads(body.decode("utf-8"), parse_float=Decimal, parse_int=Decimal)
        observations = tuple(m.CloseObservation(row["date"], Decimal(row["close"]), ordinal)
                             for ordinal, row in enumerate(document["data"], 1))
        self.oracle[receipt.symbol] = m.SymbolOracle(receipt.symbol, hashlib.sha256(body).hexdigest(),
                                                   observations, PUBLIC_ANCHORS[receipt.symbol])
        if self.observer_change:
            self.observer_change(receipt.symbol, budget)
        budget.checkpoint(document)

    def evidence(self):
        return m.IndependentOracleEvidence(FIXTURE_QA_SESSION, FIXTURE_CANDIDATE_SHA, LOADED_SOURCE_SHA256,
                                            self.grant.namespace, EXTERNAL_PIN, self.grant.consumer_version,
                                            self.grant.anchor_version, tuple(self.oracle[s] for s in EXPECTED_SYMBOLS))

    def acquire(self, **changes):
        parameters = dict(policy_bytes=EXTERNAL_POLICY_BYTES, expected_policy_sha256=EXTERNAL_PIN,
                          transport=self.transport, monotonic=self.clock,
                          utc_now=lambda: datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc))
        parameters.update(changes)
        return m.acquire_once(self.grant, self.use, self.observe, self.roots, self.release, **parameters)

    def assert_error(self, code, operation):
        with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def assert_acquire_error(self, code, expected_attempts=1, expected_release=True):
        prior_releases = self.release_calls
        def operation():
            with self.acquire():
                self.fail("Bad source became available")
        error = self.assert_error(code, operation)
        self.assertEqual(len(self.attempts), expected_attempts)
        self.assertTrue(all(response.closed for response in self.responses))
        self.assertFalse(self.originals)
        self.assertFalse(self.oracle)
        self.assertFalse(self.results)
        self.assertEqual(self.release_calls, prior_releases + int(expected_release))
        return error

    def test_import_has_no_application_or_io_side_effects(self):
        self.assertNotIn("app.config", sys.modules)
        self.assertNotIn("app.main", sys.modules)
        self.assertNotIn("worker.sources", sys.modules)
        self.assertNotIn("conftest", sys.modules)
        self.assertEqual(GUARD_EVENTS, [])

    def test_external_policy_pin_and_exact_git_candidate_format(self):
        self.assertEqual(len(EXTERNAL_POLICY_BYTES), 1665)
        self.assertEqual(hashlib.sha256(EXTERNAL_POLICY_BYTES).hexdigest(), EXTERNAL_PIN)
        self.assertEqual(len(self.grant.candidate_sha), 40)
        with self.acquire() as bundle:
            self.assertEqual(bundle.state, "pending_oracle")
            self.assertEqual(bundle.request_count, 7)

    def test_unauthorized_engineering_receipt_and_invalid_grants_before_get(self):
        for changes, code in (
            ({"approval_receipt": "https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-6081459941"}, "qa_grant_binding_invalid"),
            ({"candidate_sha": "a" * 64}, "qa_grant_binding_invalid"),
            ({"module_sha256": "a" * 40}, "qa_grant_binding_invalid"),
            ({"qa_session_id": FIXTURE_ENGINEER_SESSION}, "qa_session_not_independent"),
            ({"command": "python synthetic"}, "qa_grant_binding_invalid"),
            ({"namespace": "other"}, "qa_grant_binding_invalid"),
            ({"anchor_version": "self-pinned"}, "qa_grant_binding_invalid"),
        ):
            with self.subTest(changes=changes):
                self.grant = replace(synthetic_grant(), **changes)
                self.assert_acquire_error(code, 0, expected_release=False)
                self.assertNotIn(m.QA_NAMESPACE, m._SEALED_NAMESPACES)
                self.release_calls = 0

    def test_missing_grant_before_get(self):
        self.grant = None
        with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
            with self.acquire():
                pass
        self.assertEqual(caught.exception.code, "explicit_qa_grant_required")
        self.assertFalse(self.attempts)

    def test_all_unsupported_capabilities_rejected_before_get(self):
        for capability in EXTERNAL_POLICY["unsupported"]:
            with self.subTest(capability=capability):
                self.use = replace(explicit_use(), required_capabilities=(capability,))
                with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
                    with self.acquire():
                        pass
                self.assertEqual(caught.exception.code, "required_capability_not_supported")
                self.assertFalse(self.attempts)
                self.assertNotIn(m.QA_NAMESPACE, m._SEALED_NAMESPACES)

    def test_other_cutoff_market_scope_basis_and_self_policy_rejected_before_get(self):
        for field, value in (("as_of", "2026-10-07"), ("market", "TW/TWSE"), ("symbols", ("0056",)),
                             ("basis", "adjusted_close"), ("expected_policy_sha256", "a" * 64),
                             ("required_capabilities", [])):
            with self.subTest(field=field):
                self.use = replace(explicit_use(), **{field: value})
                with self.assertRaises(m.OrdinaryPriceSourceError):
                    with self.acquire():
                        pass
                self.assertFalse(self.attempts)
        self.use = explicit_use()
        forged = EXTERNAL_POLICY_BYTES.replace(b"FinMind", b"Forged!")
        with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
            with self.acquire(policy_bytes=forged, expected_policy_sha256=hashlib.sha256(forged).hexdigest()):
                pass
        self.assertEqual(caught.exception.code, "external_policy_pin_mismatch")
        self.assertFalse(self.attempts)

    def test_pending_oracle_blocks_getter_and_consumer(self):
        with self.acquire() as bundle:
            self.assert_error("independent_oracle_required", lambda: m.get_21_closes(bundle, "3105", "2026-10-06", self.use))
            self.assert_error("independent_oracle_required", lambda: m.summarize_ordinary_close_window(bundle, self.use))
            self.assertEqual(len(self.attempts), 7)

    def test_same_original_reference_full_147_and_last_20_exact_consumer(self):
        with self.acquire() as bundle:
            self.assertEqual(tuple(receipt.symbol for receipt in bundle.receipts), EXPECTED_SYMBOLS)
            for capture in bundle._captures:
                self.assertIs(capture.body, self.originals[capture.receipt.symbol][0])
                self.assertIs(capture.receipt, self.originals[capture.receipt.symbol][1])
                self.assertEqual(capture.receipt.body_sha256, hashlib.sha256(capture.body).hexdigest())
                self.assertTrue(capture.receipt.eof)
            m.confirm_independent_oracle(bundle, self.evidence(), self.use)
            summary = m.summarize_ordinary_close_window(bundle, self.use)
            self.results.append(summary)
            self.assertEqual(bundle.state, "available")
            self.assertEqual(sum(len(item.series.observations) for item in summary.symbols), 147)
            self.assertEqual(sum(item.count for item in summary.symbols), 140)
            for result in summary.symbols:
                symbol = result.series.symbol
                anchor = PUBLIC_ANCHORS[symbol]
                self.assertEqual(result.series.observations, self.oracle[symbol].observations)
                self.assertEqual(result.window_dates, EXPECTED_DAYS[1:])
                self.assertEqual(result.mean, anchor - Decimal("9.5"))
                self.assertEqual((result.latest_close, result.previous_close, result.latest_minus_previous),
                                 (anchor, anchor - 1, Decimal(1)))
                provenance = result.series.provenance
                self.assertEqual(provenance.attribution, "FinMind")
                self.assertTrue(provenance.unit_mapping_inference)
                self.assertFalse(provenance.provider_literal_unit_annotation)
                self.assertEqual(provenance.unit, "TWD/share")
                self.assertEqual(provenance.calendar_version, EXTERNAL_POLICY["scope"]["calendar_version"])
                self.assertEqual(provenance.date_timezone, "Asia/Taipei")
                self.assertEqual(provenance.independent_oracle_session, FIXTURE_QA_SESSION)
                self.assertEqual((provenance.publication_time, provenance.first_availability, provenance.revision_time),
                                 ("unknown", "unknown", "unknown"))
                self.assertFalse(provenance.adjustment_verified)
                self.assertFalse(provenance.whole_window_historical_membership_verified)
            bundle._budget.checkpoint(summary)
            self.assertGreater(bundle.estimated_retained_bytes, 0)
            self.assertLess(bundle.estimated_retained_bytes, 1_048_576)
            RETAINED_ESTIMATES.append(bundle.estimated_retained_bytes)
            self.assertEqual(len(self.attempts), 7)
        self.assertEqual(bundle.state, "released")
        self.assertFalse(self.originals or self.oracle or self.results)
        self.assert_error("lease_released", lambda: m.get_21_closes(bundle, "3105", "2026-10-06", self.use))
        self.assert_error("lease_released", lambda: m.summarize_ordinary_close_window(bundle, self.use))

    def test_summary_uses_local_decimal_precision(self):
        with self.acquire() as bundle:
            m.confirm_independent_oracle(bundle, self.evidence(), self.use)
            prior = getcontext().prec
            try:
                getcontext().prec = 5
                summary = m.summarize_ordinary_close_window(bundle, self.use)
                self.assertEqual(summary.symbols[2].mean, Decimal("18975.5"))
            finally:
                getcontext().prec = prior

    def test_reader_invalid_arguments_do_not_refetch(self):
        with self.acquire() as bundle:
            m.confirm_independent_oracle(bundle, self.evidence(), self.use)
            for symbol, cutoff in (("0056", "2026-10-06"), ("3105", "2026-10-07"), (3105, "2026-10-06")):
                self.assert_error("symbol_or_cutoff_not_admitted", lambda: m.get_21_closes(bundle, symbol, cutoff, self.use))
            self.assert_error("required_capability_not_supported",
                              lambda: m.summarize_ordinary_close_window(bundle, replace(self.use, required_capabilities=("historical_pit",))))
            self.assertEqual(len(self.attempts), 7)
            self.assertEqual(bundle.state, "available")

    def test_exact_url_headers_timeout_and_default_product_transport_seam(self):
        outer = self
        class Connection:
            def __init__(self, host, timeout):
                outer.assertEqual(host, "api.finmindtrade.com")
                outer.assertEqual(timeout, 20)
                self.response = None
            def request(self, method, target, headers):
                outer.assertEqual(method, "GET")
                self.response = outer.transport("https://api.finmindtrade.com" + target, 20, headers)
            def getresponse(self):
                return self.response
            def close(self):
                if self.response:
                    self.response.close()
        with patch.object(m.http.client, "HTTPSConnection", Connection):
            with self.acquire(transport=None):
                pass
        self.assertEqual(tuple(row[0] for row in self.attempts), EXPECTED_SYMBOLS)
        for symbol, url, timeout, headers in self.attempts:
            self.assertEqual(url, "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=" +
                             symbol + "&start_date=2026-09-04&end_date=2026-10-06")
            self.assertEqual(headers["Accept-Encoding"], "identity")
            self.assertEqual(timeout, 20)

    def test_failure_spends_seal_and_stops_remaining_six(self):
        self.response_change = lambda symbol, response: setattr(response, "status", 429)
        self.assert_acquire_error("http_status_or_redirect")
        self.response_change = None
        self.assert_acquire_error("qa_namespace_spent", 1)
        self.assertEqual(self.release_calls, 2)

    def test_middle_symbol_failure_never_publishes_partial_bundle(self):
        self.documents["5347"]["data"][0]["close"] = 0
        self.assert_acquire_error("close_not_finite_positive", 4)

    def test_http_redirect_and_encoding_are_not_followed(self):
        for mutation, code in ((lambda r: setattr(r, "status", 302), "http_status_or_redirect"),
                               (lambda r: setattr(r, "url", r.url + "&other=1"), "http_status_or_redirect"),
                               (lambda r: r.headers.update({"Content-Encoding": "gzip"}), "content_encoding_not_identity"),
                               (lambda r: r.headers.update({"Content-Type": "text/html"}), "content_type_not_json_utf8"),
                               (lambda r: r.headers.update({"Content-Type": "application/json; charset=big5"}), "content_type_not_json_utf8"),
                               (lambda r: r.headers.update({"Content-Type": "application/json; charset = big5"}), "content_type_not_json_utf8")):
            with self.subTest(code=code):
                m._SEALED_NAMESPACES.clear()
                self.attempts.clear(); self.responses.clear(); self.release_calls = 0
                self.response_change = lambda symbol, response: mutation(response)
                self.assert_acquire_error(code)

    def test_body_length_cap_full_eof_and_chunk_shape(self):
        for mutation, code in (
            (lambda r: r.headers.update({"Content-Length": str(m.BODY_CAP + 1)}), "body_cap_exceeded"),
            (lambda r: r.headers.update({"Content-Length": str(len(r.body) + 1)}), "body_length_or_eof"),
            (lambda r: r.headers.update({"Content-Length": "-1"}), "content_length_invalid"),
            (lambda r: setattr(r, "read", lambda size: bytearray(b"{}")), "transport_chunk_invalid"),
        ):
            with self.subTest(code=code):
                m._SEALED_NAMESPACES.clear()
                self.attempts.clear(); self.responses.clear(); self.release_calls = 0
                self.response_change = lambda symbol, response: mutation(response)
                self.assert_acquire_error(code)
        m._SEALED_NAMESPACES.clear()
        self.attempts.clear(); self.responses.clear(); self.release_calls = 0
        self.response_change = lambda symbol, response: response.headers.pop("Content-Length")
        with self.acquire():
            self.assertEqual(self.responses[-1].offset, len(self.responses[-1].body))
            self.assertEqual(self.responses[-1].read_calls, 2)

    def test_chunk_body_over_cap_and_aggregate_cap(self):
        self.response_change = lambda symbol, r: (r.headers.pop("Content-Length"), setattr(r, "body", b"x" * (m.BODY_CAP + 1)))
        self.assert_acquire_error("body_cap_exceeded")
        m._SEALED_NAMESPACES.clear()
        self.attempts.clear(); self.responses.clear(); self.release_calls = 0
        self.response_change = None
        first_size = len(json.dumps(self.documents["3105"], separators=(",", ":")).encode("utf-8"))
        with patch.object(m, "TOTAL_RAW_CAP", first_size + 1):
            self.assert_acquire_error("body_cap_exceeded", 2)

    def test_network_and_observer_failures_release_and_stop(self):
        self.response_change = lambda symbol, response: setattr(response, "failure", OSError("synthetic disconnected"))
        self.assert_acquire_error("source_acquisition_failed")
        m._SEALED_NAMESPACES.clear()
        self.attempts.clear(); self.responses.clear(); self.release_calls = 0
        self.response_change = None
        def failing_observer(symbol, budget):
            raise RuntimeError("synthetic oracle failed")
        self.observer_change = failing_observer
        self.assert_acquire_error("source_acquisition_failed")

    def test_request_deadline_and_remaining_batch_timeout(self):
        self.response_change = lambda symbol, response: setattr(response, "on_read", lambda: setattr(self.clock, "value", 20))
        self.assert_acquire_error("request_deadline")
        m._SEALED_NAMESPACES.clear()
        self.attempts.clear(); self.responses.clear(); self.release_calls = 0
        self.clock.value = 0
        self.response_change = None
        self.observer_change = lambda symbol, budget: setattr(self.clock, "value", 179) if symbol == "3105" else None
        with self.acquire():
            self.assertEqual(self.attempts[1][2], 1)

    def test_expiry_is_latched_even_if_clock_is_rewound(self):
        with self.acquire() as bundle:
            m.confirm_independent_oracle(bundle, self.evidence(), self.use)
            self.clock.value = 180
            self.assert_error("lease_expired", lambda: m.get_21_closes(bundle, "3105", "2026-10-06", self.use))
            self.assertEqual(bundle.state, "released")
            self.assertFalse(self.originals or self.oracle)
            self.clock.value = 0
            self.assert_error("lease_released", lambda: m.summarize_ordinary_close_window(bundle, self.use))

    def test_roots_callback_missing_failing_hidden_or_over_cap_fail_closed(self):
        for roots, code in ((lambda: None, "retained_roots_required"),
                            (lambda: m.RetainedRoots(None, {}, []), "retained_roots_required"),
                            (lambda: m.RetainedRoots({"hidden": object()}, {}, []), "retained_root_type_unsupported")):
            with self.subTest(code=code):
                with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
                    with m.acquire_once(self.grant, self.use, self.observe, roots, self.release,
                                        policy_bytes=EXTERNAL_POLICY_BYTES, expected_policy_sha256=EXTERNAL_PIN,
                                        transport=self.transport, monotonic=self.clock):
                        pass
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(self.attempts)
        def bad_roots():
            raise RuntimeError("unavailable oracle roots")
        with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
            with m.acquire_once(self.grant, self.use, self.observe, bad_roots, self.release,
                                policy_bytes=EXTERNAL_POLICY_BYTES, expected_policy_sha256=EXTERNAL_PIN,
                                transport=self.transport, monotonic=self.clock):
                pass
        self.assertEqual(caught.exception.code, "retained_roots_callback_failed")
        with patch.object(m.sys, "getsizeof", return_value=m.RETAINED_CAP + 1):
            with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
                with self.acquire():
                    pass
        self.assertEqual(caught.exception.code, "retained_roots_cap_exceeded")
        self.assertFalse(self.attempts)

    def test_external_roots_are_checked_on_consumer_and_deduplicated(self):
        shared = b"x" * 1024
        self.assertLess(m._estimate_roots([shared] * 100), 10_000)
        with self.acquire() as bundle:
            m.confirm_independent_oracle(bundle, self.evidence(), self.use)
            self.results.append({"unexpected": object()})
            self.assert_error("retained_root_type_unsupported", lambda: m.summarize_ordinary_close_window(bundle, self.use))
            self.assertEqual(bundle.state, "released")
            self.results.clear()
            self.assert_error("lease_released", lambda: m.get_21_closes(bundle, "3105", "2026-10-06", self.use))

    def test_all_row_dates_identity_schema_and_numeric_boundaries(self):
        mutations = (
            (lambda d: d["data"].pop(), "window_row_count"),
            (lambda d: d["data"].append(dict(d["data"][-1])), "window_row_count"),
            (lambda d: d["data"][0].pop("close"), "row_schema_invalid"),
            (lambda d: d["data"][0].update(date="2026/09/04"), "row_date_shape"),
            (lambda d: d["data"][0].update(date="2026-02-30"), "row_date_invalid"),
            (lambda d: d["data"][1].update(date="2026-09-04"), "row_date_duplicate"),
            (lambda d: d["data"][0].update(date="2026-09-25"), "row_date_not_in_calendar"),
            (lambda d: d["data"][-1].update(date="2026-10-07"), "row_date_not_in_calendar"),
            (lambda d: d["data"].reverse(), "window_date_order_or_missing"),
            (lambda d: d["data"][0].update(stock_id=3105), "row_symbol_invalid"),
            (lambda d: d["data"][0].update(stock_id="0056"), "row_symbol_invalid"),
            (lambda d: d["data"][0].update(close=True), "close_not_numeric"),
            (lambda d: d["data"][0].update(close="592"), "close_not_numeric"),
            (lambda d: d["data"][0].update(close=0), "close_not_finite_positive"),
            (lambda d: d["data"][0].update(close=-1), "close_not_finite_positive"),
            (lambda d: d.update(status=True), "provider_schema_invalid"),
        )
        for mutation, code in mutations:
            with self.subTest(code=code):
                m._SEALED_NAMESPACES.clear()
                self.attempts.clear(); self.responses.clear(); self.release_calls = 0
                self.documents["3105"] = fixture_document("3105")
                mutation(self.documents["3105"])
                self.assert_acquire_error(code)

    def test_utf8_json_duplicate_key_nonfinite_and_decimal_precision(self):
        for body, code in ((b"\xff", "body_json_invalid"), (b"{}", "provider_schema_invalid"),
                           (b'{"status":200,"status":200}', "json_duplicate_key"),
                           (b'{"value":NaN}', "json_nonfinite_number"),
                           (b'{"value":Infinity}', "json_nonfinite_number"),
                           (b'{"status":200', "body_json_invalid")):
            with self.subTest(code=code):
                m._SEALED_NAMESPACES.clear()
                self.attempts.clear(); self.responses.clear(); self.release_calls = 0
                def change(symbol, response):
                    response.body = body
                    response.headers["Content-Length"] = str(len(body))
                self.response_change = change
                self.assert_acquire_error(code)
        self.response_change = None
        m._SEALED_NAMESPACES.clear()
        self.attempts.clear(); self.responses.clear(); self.release_calls = 0
        self.documents["3105"]["data"][0]["close"] = 571.125
        with self.acquire() as bundle:
            m.confirm_independent_oracle(bundle, self.evidence(), self.use)
            self.assertEqual(m.get_21_closes(bundle, "3105", "2026-10-06", self.use).observations[0].close, Decimal("571.125"))

    def test_oracle_identity_binding_failure_latches_release(self):
        for field, wrong in (("candidate_sha", "a" * 40), ("module_sha256", "a" * 64),
                             ("qa_session_id", FIXTURE_ENGINEER_SESSION), ("policy_sha256", "a" * 64),
                             ("namespace", "other"), ("consumer_version", "other"), ("anchor_version", "self")):
            with self.subTest(field=field):
                m._SEALED_NAMESPACES.clear()
                self.attempts.clear(); self.responses.clear()
                with self.acquire() as bundle:
                    valid = self.evidence()
                    self.assert_error("independent_oracle_binding_invalid",
                                      lambda: m.confirm_independent_oracle(bundle, replace(valid, **{field: wrong}), self.use))
                    self.assertEqual(bundle.state, "released")
                    self.assert_error("lease_released", lambda: m.confirm_independent_oracle(bundle, valid, self.use))
                    self.assertFalse(self.originals or self.oracle)

    def test_all_seven_hash_anchor_and_147_sequence_failures_are_atomic(self):
        for symbol in EXPECTED_SYMBOLS:
            with self.subTest(symbol=symbol):
                m._SEALED_NAMESPACES.clear()
                self.attempts.clear(); self.responses.clear()
                with self.acquire() as bundle:
                    evidence = self.evidence()
                    index = EXPECTED_SYMBOLS.index(symbol)
                    bad_symbol = replace(evidence.symbols[index], latest_close_anchor=PUBLIC_ANCHORS[symbol] * 1000)
                    bad = replace(evidence, symbols=evidence.symbols[:index] + (bad_symbol,) + evidence.symbols[index + 1:])
                    self.assert_error("independent_latest_close_anchor_mismatch", lambda: m.confirm_independent_oracle(bundle, bad, self.use))
                    self.assertEqual(bundle.state, "released")
        for mutation, code in (
            (lambda oracle: replace(oracle, body_sha256="a" * 64), "independent_oracle_source_mismatch"),
            (lambda oracle: replace(oracle, observations=oracle.observations[:-1]), "independent_oracle_source_mismatch"),
            (lambda oracle: replace(oracle, observations=(replace(oracle.observations[0], close=Decimal(1)),) + oracle.observations[1:]),
             "independent_oracle_sequence_mismatch"),
            (lambda oracle: replace(oracle, observations=(replace(oracle.observations[0], row_ordinal=True),) + oracle.observations[1:]),
             "independent_oracle_sequence_mismatch"),
            (lambda oracle: replace(oracle, latest_close_anchor=True), "independent_latest_close_anchor_mismatch"),
        ):
            with self.subTest(code=code):
                m._SEALED_NAMESPACES.clear()
                self.attempts.clear(); self.responses.clear()
                with self.acquire() as bundle:
                    evidence = self.evidence()
                    bad = replace(evidence, symbols=(mutation(evidence.symbols[0]),) + evidence.symbols[1:])
                    self.assert_error(code, lambda: m.confirm_independent_oracle(bundle, bad, self.use))
                    self.assertEqual(bundle.state, "released")

    def test_true_raw_scale_conflict_cannot_be_repaired_by_same_oracle(self):
        self.documents["8069"]["data"][-1]["close"] *= 1000
        with self.acquire() as bundle:
            self.assert_error("independent_latest_close_anchor_mismatch",
                              lambda: m.confirm_independent_oracle(bundle, self.evidence(), self.use))
            self.assertEqual(bundle.state, "released")
            self.assertEqual(len(self.attempts), 7)

    def test_frozen_evidence_and_mutation_rechecked_on_read(self):
        with self.acquire() as bundle:
            evidence = self.evidence()
            with self.assertRaises(FrozenInstanceError):
                evidence.policy_sha256 = "changed"
            m.confirm_independent_oracle(bundle, evidence, self.use)
            first = bundle._captures[0]
            bundle._captures = (replace(first, observations=first.observations[:-1]),) + bundle._captures[1:]
            self.assert_error("independent_oracle_source_mismatch", lambda: m.get_21_closes(bundle, "3105", "2026-10-06", self.use))
            self.assertEqual(bundle.state, "released")

    def test_mutually_replaced_oracle_and_capture_still_bound_to_original_raw(self):
        with self.acquire() as bundle:
            evidence = self.evidence()
            first = bundle._captures[0]
            changed_rows = (replace(first.observations[0], close=Decimal(1)),) + first.observations[1:]
            bundle._captures = (replace(first, observations=changed_rows),) + bundle._captures[1:]
            changed_oracle = replace(evidence.symbols[0], observations=changed_rows)
            changed_evidence = replace(evidence, symbols=(changed_oracle,) + evidence.symbols[1:])
            self.assert_error("source_projection_not_bound_to_raw",
                              lambda: m.confirm_independent_oracle(bundle, changed_evidence, self.use))
            self.assertEqual(bundle.state, "released")

    def test_summary_arithmetic_failure_releases_and_cannot_resume(self):
        with self.acquire() as bundle:
            m.confirm_independent_oracle(bundle, self.evidence(), self.use)
            with patch.object(m, "_exact_arithmetic", side_effect=ArithmeticError("synthetic arithmetic unavailable")):
                self.assert_error("summary_arithmetic_failed", lambda: m.summarize_ordinary_close_window(bundle, self.use))
            self.assertEqual(bundle.state, "released")
            self.assert_error("lease_released", lambda: m.summarize_ordinary_close_window(bundle, self.use))

    def test_context_exception_always_releases_roots(self):
        with self.assertRaisesRegex(RuntimeError, "caller operation failed"):
            with self.acquire() as bundle:
                m.confirm_independent_oracle(bundle, self.evidence(), self.use)
                self.results.append(m.summarize_ordinary_close_window(bundle, self.use))
                raise RuntimeError("caller operation failed")
        self.assertEqual(bundle.state, "released")
        self.assertFalse(self.originals or self.oracle or self.results)

    def test_original_failure_preserved_when_response_or_observer_cleanup_fails(self):
        self.response_change = lambda symbol, response: (setattr(response, "status", 500),
                                                         setattr(response, "close_failure", RuntimeError("close failed")))
        error = self.assert_acquire_error("http_status_or_redirect")
        self.assertTrue(any("Response close" in note for note in error.__notes__))
        m._SEALED_NAMESPACES.clear()
        self.attempts.clear(); self.responses.clear(); self.release_calls = 0
        self.response_change = lambda symbol, response: setattr(response, "status", 500)
        def bad_release():
            self.release()
            raise RuntimeError("release failed")
        with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
            with m.acquire_once(self.grant, self.use, self.observe, self.roots, bad_release,
                                policy_bytes=EXTERNAL_POLICY_BYTES, expected_policy_sha256=EXTERNAL_PIN,
                                transport=self.transport, monotonic=self.clock):
                pass
        self.assertEqual(caught.exception.code, "http_status_or_redirect")
        self.assertEqual(caught.exception.cleanup_error, "observer_release_failed")

    def test_utc_observation_cannot_be_naive_or_reverse(self):
        with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
            with self.acquire(utc_now=lambda: datetime(2026, 10, 9)):
                pass
        self.assertEqual(caught.exception.code, "observation_utc_required")
        self.assertFalse(self.attempts)
        m._SEALED_NAMESPACES.clear()
        times = iter((datetime(2026, 10, 9, 13, tzinfo=timezone.utc), datetime(2026, 10, 9, 12, tzinfo=timezone.utc)))
        with self.assertRaises(m.OrdinaryPriceSourceError) as caught:
            with self.acquire(utc_now=lambda: next(times)):
                pass
        self.assertEqual(caught.exception.code, "observation_time_order")
        self.assertEqual(len(self.attempts), 1)


if __name__ == "__main__":
    print(json.dumps({"entry": "ordinary-close-source-RAM-boundaries", "source_sha256": LOADED_SOURCE_SHA256,
                      "policy_sha256": EXTERNAL_PIN, "fixture_only": True, "real_source_gets": 0,
                      "private_io": 0, "artifact_bytes": 0}, sort_keys=True))
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OrdinaryPriceSourceTests))
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                      "guard_events": GUARD_EVENTS, "artifact_bytes": 0, "real_source_gets": 0,
                      "declared_roots_estimate_high_water_bytes": max(RETAINED_ESTIMATES, default=0),
                      "estimate_is_not_rss_or_construction_peak": True}, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not GUARD_EVENTS else 1)
