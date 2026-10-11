"""Standalone stdlib/RAM engineering checks; synthetic data is never source QA.

Run exactly: python -B -X utf8 backend/tests/test_tpex_margin_balance_source.py
No pytest/conftest, worker/application/config import, network, DB, filesystem
artifacts, subprocess, or installed dependencies. Only the two source files are
read for direct import and the seal's module hash. HTTPS is mocked at the
connection boundary through the product's ``connection_factory`` seam (never by
replacing the ``http.client.HTTPSConnection`` global); the real transport
reader/order/framing still executes. Constructing the stdlib connection class
never connects, so the regression tests may build it without any network I/O.
AC revision 2: one source (seven FinMind requests); no official CSV, anchor or official oracle.
"""

import hashlib
import http.client
import importlib.util
import io
import json
import os
import socket
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "tpex_margin_balance_source.py"
spec = importlib.util.spec_from_file_location("issue31_standalone_margin", MODULE_PATH)
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)

# Exact externally published qa1 codeblock from issuecomment-6084167671 (SPENT / NO-RETRY): policy v1. Kept only to
# prove by program how the v2 policy below differs from it.
OLD_POLICY = b'{"canonicalCalendarSource":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md#31.2","caps":{"batchCooperativeSeconds":180,"bodyBytes":1048576,"maxRequests":8,"redirects":0,"requestSeconds":20,"retainedRootsEstimateBytes":33554432,"retries":0,"totalRawBytes":8388608},"consumer":"ordinary-margin-change-ratio-v1","financialProvider":"FinMind","firstFailure":"stop_attempted_spent_unattempted_not_spent","formula":"(B[T]-B[T-5])/abs(B[T-5])","instrument":"ordinary_stock","lifecycle":"capture_eof_hash_then_independent_oracle_then_positive_consumer_then_release_and_exit","market":"TPEx","namespace":"issue31-margin-seven-cutoffs-1005-1006-v1/qa1","officialAnchorDates":["2026-10-08","2026-10-09"],"officialAnchorUrl":"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=data","query":{"dataset":"TaiwanStockMarginPurchaseShortSale","end_date":"2026-10-09","start_date":"2026-09-24"},"queryKeyOrder":["dataset","data_id","start_date","end_date"],"ratioRepresentation":{"exactThresholdComparison":"20*numerator<=positiveDenominator","numerator":"B[T]-B[T-5]","positiveDenominator":"abs(B[T-5])","roundedDisplayNotUsedForGate":true,"zeroDenominator":"reject"},"requiredWindows":{"2026-10-05":["2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]},"schema":"ordinary-margin-source-policy/v1","sourceDataset":"TaiwanStockMarginPurchaseShortSale","supportedUse":["local_personal_noncommercial","process_ram_snapshot","margin5_balance_change_ratio","same_date_anchor_trace"],"symbols":["3105","3293","5274","5347","6488","6510","8069"],"threshold":"0.05","transport":{"acceptEncoding":"identity","cookies":false,"proxies":false,"tokens":false},"unitInference":{"canonical":"lots","historicalExtension":"explicit_limited_snapshot_inference","kind":"conditional_combination_inference","numericScale":1,"providerLiteral":false,"requireAllSevenSameDateBothAnchorsExact":true,"requireEachSymbolAtLeastOneNonzeroAnchor":true},"unsupportedUse":["historical_pit","publication_time","first_availability","revision_history","historical_eligibility","historical_membership","actionable_strategy","plan","trading","disk_raw_storage","raw_redistribution","mirror","deployment","other_cutoff"],"version":"ordinary-margin-cutoffs-1005-1006-v1"}'
# The same v1 text with the qa2 namespace (SPENT / NO-RETRY); no longer accepted either.
QA2_POLICY = b'{"canonicalCalendarSource":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md#31.2","caps":{"batchCooperativeSeconds":180,"bodyBytes":1048576,"maxRequests":8,"redirects":0,"requestSeconds":20,"retainedRootsEstimateBytes":33554432,"retries":0,"totalRawBytes":8388608},"consumer":"ordinary-margin-change-ratio-v1","financialProvider":"FinMind","firstFailure":"stop_attempted_spent_unattempted_not_spent","formula":"(B[T]-B[T-5])/abs(B[T-5])","instrument":"ordinary_stock","lifecycle":"capture_eof_hash_then_independent_oracle_then_positive_consumer_then_release_and_exit","market":"TPEx","namespace":"issue31-margin-seven-cutoffs-1005-1006-v1/qa2","officialAnchorDates":["2026-10-08","2026-10-09"],"officialAnchorUrl":"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=data","query":{"dataset":"TaiwanStockMarginPurchaseShortSale","end_date":"2026-10-09","start_date":"2026-09-24"},"queryKeyOrder":["dataset","data_id","start_date","end_date"],"ratioRepresentation":{"exactThresholdComparison":"20*numerator<=positiveDenominator","numerator":"B[T]-B[T-5]","positiveDenominator":"abs(B[T-5])","roundedDisplayNotUsedForGate":true,"zeroDenominator":"reject"},"requiredWindows":{"2026-10-05":["2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]},"schema":"ordinary-margin-source-policy/v1","sourceDataset":"TaiwanStockMarginPurchaseShortSale","supportedUse":["local_personal_noncommercial","process_ram_snapshot","margin5_balance_change_ratio","same_date_anchor_trace"],"symbols":["3105","3293","5274","5347","6488","6510","8069"],"threshold":"0.05","transport":{"acceptEncoding":"identity","cookies":false,"proxies":false,"tokens":false},"unitInference":{"canonical":"lots","historicalExtension":"explicit_limited_snapshot_inference","kind":"conditional_combination_inference","numericScale":1,"providerLiteral":false,"requireAllSevenSameDateBothAnchorsExact":true,"requireEachSymbolAtLeastOneNonzeroAnchor":true},"unsupportedUse":["historical_pit","publication_time","first_availability","revision_history","historical_eligibility","historical_membership","actionable_strategy","plan","trading","disk_raw_storage","raw_redistribution","mirror","deployment","other_cutoff"],"version":"ordinary-margin-cutoffs-1005-1006-v1"}'
# Policy v2 (AC revision 2, ordinary-margin-source-policy/v2) with the qa3 namespace, canonical JSON: the exact
# 2886 bytes the global published in issuecomment-6112134098 (pin below). A policy fixture, not a financial
# expected-value projection of the product.
POLICY = b'{"canonicalCalendarSource":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md#31.2","caps":{"batchCooperativeSeconds":180,"bodyBytes":1048576,"maxRequests":7,"redirects":0,"requestSeconds":20,"retainedRootsEstimateBytes":33554432,"retries":0,"totalRawBytes":8388608},"consumer":"ordinary-margin-change-ratio-v1","financialProvider":"FinMind","firstFailure":"stop_attempted_spent_unattempted_not_spent","formula":"(B[T]-B[T-5])/abs(B[T-5])","instrument":"ordinary_stock","internalConsistency":{"chain":"MarginPurchaseYesterdayBalance[i+1]==MarginPurchaseTodayBalance[i]","requirePostCutoffRow":true,"requiredDaysThroughCutoff":["2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"sameDateSetAcrossSymbols":true},"lifecycle":"capture_eof_hash_then_independent_oracle_then_positive_consumer_then_release_and_exit","market":"TPEx","namespace":"issue31-margin-seven-cutoffs-1005-1006-v1/qa3","query":{"dataset":"TaiwanStockMarginPurchaseShortSale","end_date":"2026-10-09","start_date":"2026-09-24"},"queryKeyOrder":["dataset","data_id","start_date","end_date"],"ratioRepresentation":{"exactThresholdComparison":"20*numerator<=positiveDenominator","numerator":"B[T]-B[T-5]","positiveDenominator":"abs(B[T-5])","roundedDisplayNotUsedForGate":true,"zeroDenominator":"reject"},"requiredWindows":{"2026-10-05":["2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]},"rowSchema":{"extra":"reject","noteMaxChars":256,"noteNullable":true,"numeric":"non-bool-int-0-to-int64-max","optional":["Note"],"required":["date","stock_id","MarginPurchaseBuy","MarginPurchaseCashRepayment","MarginPurchaseLimit","MarginPurchaseSell","MarginPurchaseTodayBalance","MarginPurchaseYesterdayBalance","OffsetLoanAndShort","ShortSaleBuy","ShortSaleCashRepayment","ShortSaleLimit","ShortSaleSell","ShortSaleTodayBalance","ShortSaleYesterdayBalance"],"stringFields":["Note","date","stock_id"]},"schema":"ordinary-margin-source-policy/v2","sourceDataset":"TaiwanStockMarginPurchaseShortSale","supportedUse":["local_personal_noncommercial","process_ram_snapshot","margin5_balance_change_ratio"],"symbols":["3105","3293","5274","5347","6488","6510","8069"],"threshold":"0.05","transport":{"acceptEncoding":"identity","cookies":false,"proxies":false,"tokens":false},"unitInference":{"canonical":"lots","kind":"explicit_provider_inference","numericScale":1,"officialAnchorVerified":false,"providerLiteral":false},"unsupportedUse":["historical_pit","publication_time","first_availability","revision_history","historical_eligibility","historical_membership","actionable_strategy","plan","trading","disk_raw_storage","raw_redistribution","mirror","deployment","other_cutoff","official_unit_verification"],"version":"ordinary-margin-cutoffs-1005-1006-v2"}'

S = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
D = ("2026-09-24", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")
W = (("2026-10-05", D[:6]), ("2026-10-06", D[1:]))
QA = "01a12222-2222-7222-8222-222222222222"
GLOBAL_ID = "01a11111-1111-7111-8111-111111111111"
OWNER = "01a13333-3333-7333-8333-333333333333"
ENGINEER = "01a14444-4444-7444-8444-444444444444"
RUNTIME_ID = "01a15555-5555-7555-8555-555555555555"
TERMINAL = "term_01a16666-6666-7666-8666-666666666666"
MODEL = "claude-sonnet-5-5"
EFFORT = "xhigh"
RUNTIME_ENV = {M.SESSION_ENV: QA, M.EFFORT_ENV: EFFORT}
# The only request headers the product may pass: identity encoding and one fixed, non-personal User-Agent.
REQUEST_HEADERS = {"Accept-Encoding": "identity", "User-Agent": "stock-lab-issue31-local-ram/1"}
SCRIPT =b"# Synthetic RAM test script, not a financial-start authorization.\n"
COMMAND = "python -B -X utf8 synthetic-ram-only"
SHA = "a" * 40


def json_body(document):
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


CHAIN_DAYS = D + ("2026-10-08", "2026-10-09")  # Seven cutoff-calendar days plus two post-cutoff rows.


def make_document(index, days=CHAIN_DAYS, today=None):
    """One chain-consistent FinMind response (documented 16 columns): Yesterday[i+1] == Today[i].

    Note cycles through null, "X" and "" (all valid); tests delete or change it where they need to."""
    # Nonmonotonic values and a legal interior zero expose sums/5-value implementations;
    # repeating ratios test exact Fraction comparisons.
    base = (100 + index, 120 + index, 0, 73, 87, 105 + index, 90 + index, 0, 13 + index)
    today = base if today is None else today
    assert len(today) == len(days)
    data = []
    for number, day in enumerate(days):
        row = {name: 0 for name in M.FINMIND_FIELDS if name not in M.STRING_FIELDS}
        row.update(date=day, stock_id=S[index], Note=(None, "X", "", "")[number % 4],
                   MarginPurchaseTodayBalance=today[number],
                   MarginPurchaseYesterdayBalance=(99 + index) if number == 0 else today[number - 1])
        data.append(row)
    return {"msg": "success", "status": 200, "data": data}


def fixture():
    return [make_document(index) for index in range(len(S))]


def set_today(document, position, value):
    """Change one Today balance and keep the chain consistent (the next row's Yesterday follows)."""
    data = document["data"]
    data[position]["MarginPurchaseTodayBalance"] = value
    if position + 1 < len(data):
        data[position + 1]["MarginPurchaseYesterdayBalance"] = value


class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, seconds):
        if seconds <= 0:
            raise socket.timeout()
        self.timeouts.append(seconds)


class Response:
    def __init__(self, body, *, status=200, media="application/json", length="auto", chunked=False,
                 read_error=None, headers=None):
        self.body, self.position, self.status = body, 0, status
        self.length = str(len(body)) if length == "auto" else length
        self.chunked, self.read_error, self.closed = chunked, read_error, False
        self.requests = []
        self.fp = None
        self.headers = headers if headers is not None else [("Content-Type", media)]
        if headers is None:
            if self.length is not None:
                self.headers.append(("Content-Length", self.length))
            if chunked:
                self.headers.append(("Transfer-Encoding", "chunked"))

    def getheaders(self):
        return self.headers

    def isclosed(self):
        return self.closed

    def read(self, count):
        assert count > 0
        self.requests.append(count)
        if self.read_error:
            raise self.read_error
        chunk = self.body[self.position:self.position + count]
        self.position += len(chunk)
        if not chunk or (self.length is not None and self.position == int(self.length)):
            self.closed = True
        return chunk

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, responses):
        self.responses, self.calls, self.connections = responses, [], []

    def connection(self, host, timeout):
        transport = self
        response = self.responses[len(self.connections)]

        class Connection:
            def __init__(self):
                self.sock, self.closed = FakeSocket(), False

            def request(self, method, target, headers):
                transport.calls.append(("https://" + host + target, method, dict(headers)))

            def getresponse(self):
                return response

            def close(self):
                self.closed = True

        connection = Connection()
        self.connections.append(connection)
        return connection


def native_response(body, *, framing="length", connection_close=False):
    """Real stdlib HTTPResponse framing fed only by a RAM fake socket."""
    if framing == "length":
        header = b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        wire_body = body
    elif framing == "chunked":
        header = b"Transfer-Encoding: chunked\r\n"
        wire_body = hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n\r\n"
    else:
        header, wire_body = b"", body
    if connection_close:
        header += b"Connection: close\r\n"
    wire = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + header + b"\r\n" + wire_body
    sock = FakeSocket()

    class WireFile(io.BytesIO):
        raw = SimpleNamespace(_sock=sock)

    sock.makefile = lambda _mode: WireFile(wire)
    response = M.http.client.HTTPResponse(sock)
    response.begin()
    return response


def shape36_headers(connection=None):
    """Names and counts of the 19 response headers of the Issue 36 batch that succeeded against TPEx
    (SOURCE_REGISTRY section 47.6): cache-control x2, vary x3, set-cookie x1, chunked.
    The Content-Type is JSON because the real FinMind shape is unknown. Values are synthetic; ``connection`` None leaves the Connection header out (keep-alive default)."""
    headers = [
        ("Cache-Control", "no-store, no-cache"), ("Cache-Control", "must-revalidate"),
        ("Vary", "Accept-Encoding"), ("Vary", "Cookie"), ("Vary", "Origin"),
        ("Content-Disposition", 'inline; filename="synthetic.json"'), ("Content-Security-Policy", "default-src 'self'"),
        ("Content-Type", "application/json;charset=utf-8"), ("Date", "Mon, 12 Oct 2026 03:00:00 GMT"),
        ("Permissions-Policy", "geolocation=()"), ("Referrer-Policy", "same-origin"), ("Server", "nginx"),
        ("Set-Cookie", "SYNTHETIC_SESSION=private-cookie-marker; Path=/; HttpOnly"),
        ("Strict-Transport-Security", "max-age=31536000"), ("Transfer-Encoding", "chunked"),
        ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "SAMEORIGIN"), ("X-XSS-Protection", "1; mode=block"),
    ]
    if connection is not None:
        headers.append(("Connection", connection))
    return headers


def wire_response(body, headers, *, chunk=4000):
    """Real stdlib HTTPResponse parsing of a chunked HTTP/1.1 200 wire image fed only by a RAM fake socket."""
    pieces = [body[offset:offset + chunk] for offset in range(0, len(body), chunk)]
    wire = b"HTTP/1.1 200 OK\r\n" + b"".join(
        name.encode() + b": " + value.encode() + b"\r\n" for name, value in headers) + b"\r\n"
    wire += b"".join(hex(len(piece))[2:].encode() + b"\r\n" + piece + b"\r\n" for piece in pieces) + b"0\r\n\r\n"
    sock = FakeSocket()

    class WireFile(io.BytesIO):
        raw = SimpleNamespace(_sock=sock)

    sock.makefile = lambda _mode: WireFile(wire)
    response = M.http.client.HTTPResponse(sock)
    response.begin()
    return response


def independent_oracle(capture):
    # This independent synthetic oracle reads every fresh transport body. It
    # does not access product _balances/_links/parsed/getter projections.
    views = capture.originals()
    documents, hashes = [], []
    for index, view in enumerate(views):
        body = view.body("oracle.raw_view." + str(index))
        hashes.append(hashlib.sha256(body).hexdigest())
        text = bytes(body).decode("utf-8")
        capture.roots.hold("oracle.text." + str(index), text)
        document = json.loads(text)
        capture.roots.hold("oracle.document." + str(index), document)
        documents.append(document)
    by_symbol = {}
    for symbol, document in zip(S, documents):
        by_symbol[symbol] = {row["date"]: (row["MarginPurchaseYesterdayBalance"], row["MarginPurchaseTodayBalance"])
                             for row in document["data"]}
    capture.roots.hold("oracle.numeric", by_symbol)
    balances = tuple((symbol, day, by_symbol[symbol][day][1]) for symbol in S for day in D)
    ratios = tuple((symbol, cutoff, by_symbol[symbol][days[-1]][1] - by_symbol[symbol][days[0]][1],
                    abs(by_symbol[symbol][days[0]][1])) for symbol in S for cutoff, days in W)
    links = []
    for symbol in S:
        days = sorted(by_symbol[symbol])
        for previous_day, next_day in zip(days, days[1:]):
            links.append((symbol, previous_day, next_day, by_symbol[symbol][previous_day][1],
                          by_symbol[symbol][next_day][0]))
    return M.OracleApproval(QA, tuple(hashes), balances, ratios, tuple(links))


def positive_consumer(capture):
    results = []
    capture.roots.hold("results.all", results)
    for index, symbol in enumerate(S):
        for cutoff, days in W:
            window = capture.getter(symbol, cutoff)
            consumer = capture.consume(symbol, cutoff)
            expected_values = (100 + index, 120 + index, 0, 73, 87, 105 + index, 90 + index)
            selected = expected_values[:6] if cutoff.endswith("05") else expected_values[1:]
            assert window.observations == tuple(zip(days, selected))
            numerator, denominator = selected[-1] - selected[0], abs(selected[0])
            assert (consumer.numerator, consumer.positive_denominator) == (numerator, denominator)
            assert consumer.exact_ratio == Fraction(numerator, denominator)
            assert consumer.at_most_five_percent == (20 * numerator <= denominator)
            provenance = consumer.provenance
            assert provenance["provider"] == "FinMind" and provenance["numeric_scale"] == 1
            assert provenance["provider_literal_unit"] is False and provenance["historical_pit"] is False
            assert provenance["official_anchor_verified"] is False
            assert provenance["unit_kind"] == "explicit_provider_inference"
            assert "official_receipt" not in provenance and "official_source_date" not in provenance
            assert provenance["receipt"].full_eof and provenance["receipt"].schema_validated
            assert provenance["receipt"].url == M.URLS[index]
            results.append((window.observations, provenance))


class Checks(unittest.TestCase):
    def setUp(self):
        self.spent = patch.object(M, "_SPENT_NAMESPACES", set())
        self.spent.start()
        # The live process must expose the sealed Claude session and effort.
        self.environment = patch.dict(os.environ, RUNTIME_ENV)
        self.environment.start()
        # Belt and braces: a test that reached the real stdlib transport would
        # fail here instead of opening a socket or resolving a name.
        for name in ("create_connection", "getaddrinfo"):
            patcher = patch.object(socket, name, side_effect=AssertionError("standalone tests must not use the network"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.environment.stop()
        self.spent.stop()
        self.assertIsNone(sys.gettrace())

    def capture(self, seal_changes=None, runtime_changes=None, **changes):
        seal = replace(base_seal(), **(seal_changes or {}))
        arguments = dict(use=M.UseRequest(), external_policy_utf8=POLICY, seal=seal,
            runtime=replace(capture_runtime(), **(runtime_changes or {})), full_script_utf8=SCRIPT, full_command=COMMAND)
        arguments.update(changes)
        return M.MarginCapture(**arguments)

    def execute(self, documents=None, *, oracle=independent_oracle, consumer=positive_consumer, responses=None):
        documents = fixture() if documents is None else documents
        responses = responses or [Response(json_body(d)) for d in documents]
        transport = Transport(responses)
        original_class = http.client.HTTPSConnection
        capture = self.capture(connection_factory=transport.connection)
        report = capture.run(oracle, consumer)
        self.assertIs(http.client.HTTPSConnection, original_class)  # The seam never replaces the stdlib global.
        self.assertEqual(report.transport, "caller_factory")
        self.assertEqual([r.request_started for r in report.receipts], [True] * len(report.receipts))
        self.assertTrue(all(r.closed for r in responses[:len(transport.calls)]))
        self.assertTrue(all(c.closed for c in transport.connections))
        self.assertEqual(capture._originals, [])
        self.assertEqual(capture._balances, {})
        self.assertEqual(capture._links, [])
        self.assertEqual(capture.roots.values, {})
        self.assertEqual(report.artifact_bytes, 0)
        self.assertTrue(report.requires_process_exit)
        return capture, report, transport

    def rejected(self, documents=None, error=None, attempted=None, **kwargs):
        capture, report, transport = self.execute(documents, **kwargs)
        self.assertFalse(report.success)
        if error:
            self.assertEqual(report.primary_error, error)
        if attempted is not None:
            self.assertEqual(len(report.attempted_spent), attempted)
            self.assertEqual(len(report.unattempted_not_spent), 7 - attempted)
        self.assertEqual(report.consumer_count, 0)
        for symbol in S:
            for cutoff, _days in W:
                with self.assertRaisesRegex(M.MarginSourceError, "read_unavailable"):
                    capture.getter(symbol, cutoff)
        return report, transport

    def fresh(self):
        """A new one-time namespace for another full run inside one test."""
        return patch.object(M, "_SPENT_NAMESPACES", set())

    def test_external_policy_exact_pin_and_positive_two_cutoffs(self):
        # Literals copied from the global's publication (issuecomment-6112134098), not derived from the module.
        published_pin = "7d8cd5b1835b84138e2bc982d86a93d4b3b4a3bba809842341c279fe566a9ceb"
        self.assertEqual((len(POLICY), hashlib.sha256(POLICY).hexdigest()), (2886, published_pin))
        self.assertEqual((M.POLICY_BYTES, M.POLICY_SHA256), (2886, published_pin))
        capture, report, transport = self.execute()
        self.assertTrue(report.success, report)
        self.assertEqual(report.state, "released")
        self.assertEqual(report.consumer_count, 14)
        self.assertEqual(report.getter_count, 28)
        self.assertEqual(len(M.URLS), 7)
        self.assertEqual(tuple(c[0] for c in transport.calls), M.URLS)
        self.assertTrue(all("api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id=" in c[0]
                            and c[0].endswith("&start_date=2026-09-24&end_date=2026-10-09") for c in transport.calls))
        self.assertTrue(all(c[1:] == ("GET", REQUEST_HEADERS) for c in transport.calls))
        self.assertTrue(all(r.body_sha256 and r.full_eof and r.schema_validated for r in report.receipts))
        self.assertTrue(all(r.provider == "FinMind" and r.declared_schema == M.FINMIND_FIELDS for r in report.receipts))
        self.assertEqual(len(report.receipts), 7)
        self.assertEqual(report.unattempted_not_spent, ())
        self.assertLess(report.retained_estimate_high_water, 33_554_432)
        self.assertIn("oracle.numeric", report.cleared_roots)
        self.assertEqual(M.CAPS.max_requests, 7)
        with self.assertRaisesRegex(M.MarginSourceError, "capture_once"):
            capture.run(independent_oracle, positive_consumer)

    def test_no_official_source_remains_in_the_module(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for removed in ("tpex.org.tw", "OFFICIAL_", "ANCHOR_DATES", "OfficialOracleApproval", "_approve_official",
                        "independent_official_oracle", "dataset11387", "text/plain", "octet-stream"):
            self.assertNotIn(removed, source)
        for name in ("OfficialOracleApproval", "OFFICIAL_URL", "OFFICIAL_FIELDS", "ANCHOR_DATES", "FINMIND_URLS"):
            self.assertFalse(hasattr(M, name), name)

    def test_read_before_oracle_and_all_revocable_paths(self):
        handles = []

        def oracle(capture):
            for symbol in S:
                for cutoff, _days in W:
                    with self.assertRaisesRegex(M.MarginSourceError, "read_unavailable"):
                        capture.getter(symbol, cutoff)
                    with self.assertRaisesRegex(M.MarginSourceError, "read_unavailable"):
                        capture.consume(symbol, cutoff)
            handles.append(capture.originals()[0])
            return independent_oracle(capture)

        def consume(capture):
            handles.extend((capture.getter(S[0], W[0][0]), capture.consume(S[0], W[0][0])))
            positive_consumer(capture)

        _capture, report, _transport = self.execute(oracle=oracle, consumer=consume)
        self.assertTrue(report.success, report)
        for action in [lambda: handles[0].receipt, lambda: handles[0].body("late"), lambda: handles[1].observations,
                       lambda: handles[1].provenance, lambda: handles[2].numerator, lambda: handles[2].positive_denominator,
                       lambda: handles[2].exact_ratio, lambda: handles[2].at_most_five_percent, lambda: handles[2].provenance]:
            with self.assertRaisesRegex(M.MarginSourceError, "read_unavailable"):
                action()

    def test_unsupported_uses_and_bindings_have_zero_get(self):
        capture = self.capture()
        for use in [replace(M.UseRequest(), historical_pit=True), replace(M.UseRequest(), purpose="plan"),
                    replace(M.UseRequest(), purpose="actionable_strategy"), replace(M.UseRequest(), purpose="trading"),
                    replace(M.UseRequest(), process_ram_snapshot=False), replace(M.UseRequest(), market="TWSE"),
                    replace(M.UseRequest(), instrument="ETF"), replace(M.UseRequest(), cutoffs=("2026-10-09",)),
                    replace(M.UseRequest(), local_personal_noncommercial=1)]:
            with self.assertRaisesRegex(M.MarginSourceError, "unsupported_use"):
                self.capture(use=use)
        for arguments, error in [({"external_policy_utf8": POLICY + b" "}, "external_policy_pin"),
            ({"runtime": replace(capture_runtime(), parent_session_id=ENGINEER)}, "sole_qa_runtime"),
            ({"runtime": replace(capture_runtime(), candidate_sha="b" * 40)}, "candidate_binding"),
            ({"full_script_utf8": b"changed"}, "script_binding"), ({"full_command": "changed"}, "command_binding")]:
            with self.assertRaisesRegex(M.MarginSourceError, error):
                self.capture(**arguments)

    def test_finmind_all_rows_and_integer_types(self):
        bad_values = (-1, True, 1.0, "1", None, 2 ** 63)
        # Every one of the thirteen numeric columns is checked on every row, including post-cutoff rows.
        int_fields = [name for name in M.FINMIND_FIELDS if name not in M.STRING_FIELDS]
        self.assertEqual(len(int_fields), 13)
        for number, name in enumerate(int_fields):
            documents = fixture()
            documents[2]["data"][-1][name] = bad_values[number % len(bad_values)]
            with self.fresh():
                self.rejected(documents, error="integer_int64", attempted=3)
        for value in bad_values:
            documents = fixture()
            documents[0]["data"][3]["ShortSaleLimit"] = value
            with self.fresh():
                self.rejected(documents, error="integer_int64", attempted=1)
        for value in (0, 1, 2 ** 63 - 1):  # Boundaries that are valid.
            documents = fixture()
            documents[0]["data"][-1]["ShortSaleLimit"] = value
            with self.fresh():
                _capture, report, _transport = self.execute(documents)
            self.assertTrue(report.success, (value, report))

    def test_fifteen_required_columns_strict_and_note_optional(self):
        self.assertEqual(len(M.FINMIND_FIELDS), 16)
        self.assertEqual(M.STRING_FIELDS, ("date", "stock_id", "Note"))
        self.assertEqual(M.OPTIONAL_FIELDS, ("Note",))
        self.assertEqual(M.REQUIRED_FIELDS, tuple(name for name in M.FINMIND_FIELDS if name != "Note"))
        self.assertEqual(len(M.REQUIRED_FIELDS), 15)
        for name in M.REQUIRED_FIELDS:  # Every required column missing from the rows is rejected.
            documents = fixture()
            for row in documents[0]["data"]:
                del row[name]
            with self.fresh():
                self.rejected(documents, error="finmind_schema", attempted=1)
            documents = fixture()  # ... and from a single row of a later symbol.
            del documents[3]["data"][4][name]
            with self.fresh():
                self.rejected(documents, error="finmind_schema", attempted=4)
        for extra in ("Unknown", "note", "NOTE", "Remark", ""):  # Any other key is rejected, Note spelled otherwise too.
            documents = fixture()
            documents[0]["data"][4][extra] = 0
            with self.fresh():
                self.rejected(documents, error="finmind_schema", attempted=1)
        documents = fixture()  # One extra key on a post-cutoff row of the last symbol rejects the whole batch.
        documents[6]["data"][-1]["Extra"] = "x"
        self.rejected(documents, error="finmind_schema", attempted=7)

    def test_note_absent_null_string_all_accepted_and_never_enter_the_computation(self):
        shapes = {
            "absent_everywhere": lambda row, number: row.pop("Note"),
            "null_everywhere": lambda row, number: row.update(Note=None),
            "empty_everywhere": lambda row, number: row.update(Note=""),
            "x_everywhere": lambda row, number: row.update(Note="X"),
            "exactly_256": lambda row, number: row.update(Note="x" * 256),
            "non_ascii": lambda row, number: row.update(Note="註記é"),
            "mixed": lambda row, number: row.pop("Note") if number % 3 == 0 else row.update(Note=(None, "X", "")[number % 3]),
        }
        for name, change in shapes.items():
            documents = fixture()
            for document in documents:
                for number, row in enumerate(document["data"]):
                    change(row, number)
            with self.fresh():
                _capture, report, _transport = self.execute(documents)
            self.assertTrue(report.success, (name, report))
        # Different Note shapes for different symbols are fine too: the values never enter a computation.
        documents = fixture()
        for index, document in enumerate(documents):
            for row in document["data"]:
                if index % 2:
                    row.pop("Note", None)
                else:
                    row["Note"] = None
        with self.fresh():
            _capture, report, _transport = self.execute(documents)
        self.assertTrue(report.success, report)

    def test_note_other_types_and_over_256_characters_are_rejected(self):
        for value in (1, 0, True, False, 1.5, ["X"], [], {"a": 1}, {}, "x" * 257, "x" * 1000):
            for position in (0, 4, 8):  # Any row, including the first and the last post-cutoff row.
                documents = fixture()
                documents[0]["data"][position]["Note"] = value
                with self.fresh():
                    self.rejected(documents, error="finmind_schema", attempted=1)
        documents = fixture()  # A bad Note on a later symbol rejects the whole batch there.
        documents[5]["data"][2]["Note"] = 7
        self.rejected(documents, error="finmind_schema", attempted=6)
        self.assertEqual(M.NOTE_MAX_CHARS, 256)

    def test_documented_example_rows_are_accepted_with_their_note_values(self):
        # The FinMind documentation example for 2330 (Chip page): integers, Note "X" or blank, chain-consistent.
        today = (26285, 24666, 24286, 23395, 23804, 23000, 22800, 22700, 22600)
        documents = fixture()
        documents[0] = make_document(0, today=today)
        documents[0]["data"][0]["MarginPurchaseYesterdayBalance"] = 25648
        for row, note in zip(documents[0]["data"], ("X", "X", "", "", None, "", "", "", "")):
            row["Note"] = note

        def consumer(capture):
            window = capture.getter(S[0], "2026-10-05")
            assert [value for _day, value in window.observations[:5]] == [26285, 24666, 24286, 23395, 23804]
            for symbol in S:
                for cutoff, _days in W:
                    capture.consume(symbol, cutoff)

        _capture, report, _transport = self.execute(documents, consumer=consumer)
        self.assertTrue(report.success, report)

    def test_finmind_envelope_dates_identity_and_duplicates(self):
        cases = (
            (lambda d: d.update(extra=1), "finmind_envelope"),
            (lambda d: d.pop("msg"), "finmind_envelope"),
            (lambda d: d.update(status=True), "finmind_status"),
            (lambda d: d.update(status=402), "finmind_status"),
            (lambda d: d.update(msg="requires paid plan"), "finmind_status"),
            (lambda d: d.update(data={}), "finmind_rows"),
            (lambda d: d.update(data=[]), "finmind_rows"),
            (lambda d: d.update(data=[{}] * 10_001), "finmind_rows"),
            (lambda d: d["data"].__setitem__(0, 5), "finmind_schema"),
            (lambda d: d["data"].append(dict(d["data"][0])), "finmind_identity"),
            (lambda d: d["data"][0].update(date="2026-09-23"), "finmind_date_range"),
            (lambda d: d["data"][-1].update(date="2026-10-10"), "finmind_date_range"),
            (lambda d: d["data"][-1].update(date="2026-02-30"), "date_invalid"),
            (lambda d: d["data"][-1].update(stock_id="9999"), "finmind_identity"),
            (lambda d: d["data"][-1].update(stock_id=3105), "finmind_identity"),
            (lambda d: d["data"][-1].update(date=20261009), "date_type"),
            (lambda d: d["data"][-1].update(date="2026/10/09"), "date_grammar"),
            (lambda d: d["data"][-1].update(date="2026-10-09T00:00:00"), "date_grammar"),
        )
        for mutate, error in cases:
            documents = fixture()
            mutate(documents[0])
            with self.fresh():
                self.rejected(documents, error=error, attempted=1)
        documents = fixture()  # A later symbol's failure keeps the earlier URLs SPENT and the rest unattempted.
        documents[3]["data"][0]["stock_id"] = S[2]
        self.rejected(documents, error="finmind_identity", attempted=4)

    def test_one_zero_baseline_invalidates_all_two_cutoffs(self):
        for baseline in (0, 1):
            documents = fixture()
            set_today(documents[-1], baseline, 0)
            with self.fresh():
                self.rejected(documents, error="zero_denominator", attempted=7)
        # A zero that is not a baseline is legal (the fixture already carries one at 2026-09-30).
        documents = fixture()
        set_today(documents[0], 6, 0)

        def consume_all(capture):
            for symbol in S:
                for cutoff, _days in W:
                    capture.consume(symbol, cutoff)
            ratio = capture.consume(S[0], "2026-10-06")
            self.assertEqual((ratio.numerator, ratio.positive_denominator), (-120, 120))
            self.assertTrue(ratio.at_most_five_percent)

        _capture, report, _transport = self.execute(documents, consumer=consume_all)
        self.assertTrue(report.success, report)

    def test_internal_chain_replaces_the_anchor_and_must_not_break(self):
        for position in range(1, 9):  # Every adjacent pair, including the two post-cutoff links.
            for field_delta in (1, -1):
                documents = fixture()
                row = documents[0]["data"][position]
                row["MarginPurchaseYesterdayBalance"] += field_delta if row["MarginPurchaseYesterdayBalance"] > 0 else 1
                with self.fresh():
                    self.rejected(documents, error="finmind_chain_break", attempted=1)
        documents = fixture()  # A later symbol breaking at the very last link still rejects the whole batch.
        documents[6]["data"][-1]["MarginPurchaseYesterdayBalance"] += 1
        self.rejected(documents, error="finmind_chain_break", attempted=7)
        documents = fixture()  # The first row's Yesterday has no earlier row in range: it is not chained.
        documents[0]["data"][0]["MarginPurchaseYesterdayBalance"] = 7
        with self.fresh():
            _capture, report, _transport = self.execute(documents)
        self.assertTrue(report.success, report)
        documents = fixture()  # Source order does not matter: the chain follows the date-sorted rows.
        for document in documents:
            document["data"].reverse()
        with self.fresh():
            _capture, report, _transport = self.execute(documents)
        self.assertTrue(report.success, report)
        # No official anchor and no scaling: values stay exactly as received.
        documents = fixture()
        for document in documents:
            for row in document["data"]:
                for name in ("MarginPurchaseTodayBalance", "MarginPurchaseYesterdayBalance"):
                    row[name] *= 1000
        def consumer(capture):
            window = capture.getter(S[0], "2026-10-05")
            assert window.observations[0] == ("2026-09-24", 100_000) and window.observations[1] == ("2026-09-29", 120_000)
            for symbol in S:
                for cutoff, _days in W:
                    capture.consume(symbol, cutoff)
        with self.fresh():
            _capture, report, _transport = self.execute(documents, consumer=consumer)
        self.assertTrue(report.success, report)

    def test_required_day_set_is_exactly_the_verified_calendar(self):
        post = ("2026-10-08", "2026-10-09")
        cases = {
            "missing_first_day": (D[1:] + post, (120, 0, 73, 87, 105, 90, 0, 13)),
            "missing_interior_day": ((D[0],) + D[2:] + post, (100, 0, 73, 87, 105, 90, 0, 13)),
            "missing_cutoff_day": (D[:-1] + post, (100, 120, 0, 73, 87, 105, 0, 13)),
            "extra_day_inside_calendar": (D[:1] + ("2026-09-25",) + D[1:] + post, (100, 5, 120, 0, 73, 87, 105, 90, 0, 13)),
        }
        for name, (days, today) in cases.items():
            documents = fixture()
            documents[0] = make_document(0, days=days, today=today)
            with self.fresh():
                self.rejected(documents, error="required_day_set_mismatch", attempted=1)
        documents = fixture()  # The same failure on the last symbol still rejects the whole batch.
        documents[6] = make_document(6, days=D[1:] + post, today=(120, 0, 73, 87, 105, 90, 0, 13))
        self.rejected(documents, error="required_day_set_mismatch", attempted=7)

    def test_a_row_after_the_last_cutoff_is_required_but_never_enters_the_formula(self):
        for today in ((100, 120, 0, 73, 87, 105, 90), (100, 120, 0, 73, 87, 105, 2 ** 63 - 1)):
            documents = fixture()
            documents[0] = make_document(0, days=D, today=today)
            with self.fresh():
                self.rejected(documents, error="post_cutoff_row_missing", attempted=1)
        # Any single post-cutoff date is enough; its value only takes part in the chain.
        for post in (("2026-10-07",), ("2026-10-09",), ("2026-10-07", "2026-10-08", "2026-10-09")):
            documents = [make_document(index, days=D + post, today=(
                100 + index, 120 + index, 0, 73, 87, 105 + index, 90 + index) + tuple(
                2 ** 63 - 1 - number for number in range(len(post)))) for index in range(7)]
            with self.fresh():
                _capture, report, _transport = self.execute(documents)
            self.assertTrue(report.success, (post, report))

    def test_all_seven_symbols_must_have_the_same_date_set(self):
        extra = D + ("2026-10-07", "2026-10-08", "2026-10-09")
        for index in (1, 3, 6):
            documents = fixture()
            documents[index] = make_document(index, days=extra, today=(100 + index, 120 + index, 0, 73, 87, 105 + index,
                                                                      90 + index, 5, 0, 13 + index))
            with self.fresh():
                self.rejected(documents, error="symbol_date_set_mismatch", attempted=index + 1)
        documents = fixture()  # One symbol short of a trailing row that the first symbol has.
        del documents[4]["data"][-1]
        self.rejected(documents, error="symbol_date_set_mismatch", attempted=5)
        # Other symbols may differ in values, only the date sets must agree.
        documents = [make_document(index, days=extra, today=(100 + index, 120 + index, 0, 73, 87, 105 + index,
                                                             90 + index, 5, 0, 13 + index)) for index in range(7)]
        with self.fresh():
            _capture, report, _transport = self.execute(documents)
        self.assertTrue(report.success, report)

    def test_json_duplicate_keys_nan_utf8_and_non_json(self):
        document = fixture()[0]
        base = json_body(document)
        bad_bodies = [(base.replace(b'"status":200', b'"status":200,"status":200'), "json_duplicate_key"),
                      (base.replace(b'"ShortSaleLimit":0', b'"ShortSaleLimit":NaN', 1), "json_nonfinite"),
                      (base.replace(b'"ShortSaleLimit":0', b'"ShortSaleLimit":Infinity', 1), "json_nonfinite"),
                      (b"<html>login</html>", "json_invalid"), (base + b"\xff", "utf8_invalid"),
                      (base[:-1], "json_invalid"), (b"\xef\xbb\xbf" + base, "bom_rejected"),
                      (base.replace(b'"Note":"X"', b'"Note":"X","Note":"Y"', 1), "json_duplicate_key")]
        for body, error in bad_bodies:
            with self.fresh():
                self.rejected(responses=[Response(body)], error=error, attempted=1)

    def test_oracle_gate_checks_all_hashes_values_ratios_chain_links_and_types(self):
        def bad_oracle(kind):
            def oracle(capture):
                approval = independent_oracle(capture)
                if kind == "holder":
                    return replace(approval, holder_actual="engineer")
                if kind == "hash":
                    return replace(approval, body_sha256=("0" * 64,) + approval.body_sha256[1:])
                if kind == "hash_count":
                    return replace(approval, body_sha256=approval.body_sha256[:-1])
                if kind == "balances":
                    return replace(approval, balances=approval.balances[:-1])
                if kind == "bool":
                    rows = list(approval.balances)
                    rows[2] = (*rows[2][:2], False)
                    return replace(approval, balances=tuple(rows))
                if kind == "ratios":
                    return replace(approval, ratios=approval.ratios[:-1])
                links = list(approval.chain_links)
                if kind == "links_missing":
                    return replace(approval, chain_links=tuple(links[:-1]))
                if kind == "links_extra":
                    return replace(approval, chain_links=tuple(links + [links[-1]]))
                if kind == "links_value":
                    first = links[0]
                    links[0] = (*first[:3], first[3] + 1, first[4] + 1)  # Equal pair, but not the received value.
                    return replace(approval, chain_links=tuple(links))
                if kind == "links_broken":
                    first = links[0]
                    links[0] = (*first[:4], first[4] + 1)
                    return replace(approval, chain_links=tuple(links))
                if kind == "links_order":
                    links[0], links[1] = links[1], links[0]
                    return replace(approval, chain_links=tuple(links))
                if kind == "links_date":
                    first = links[0]
                    links[0] = (first[0], first[1], "2026-09-25", *first[3:])
                    return replace(approval, chain_links=tuple(links))
                if kind == "links_bool":
                    links[0] = (links[0][0], links[0][1], links[0][2], True, True)
                    return replace(approval, chain_links=tuple(links))
                return replace(approval, chain_links=None)
            return oracle
        for kind in ("holder", "hash", "hash_count", "balances", "bool", "ratios", "links_missing", "links_extra",
                     "links_value", "links_broken", "links_order", "links_date", "links_bool", "links_none"):
            with self.fresh():
                report, _transport = self.rejected(oracle=bad_oracle(kind), attempted=7)
                self.assertTrue(report.primary_error.startswith("oracle_"), (kind, report.primary_error))
            self.assertEqual(report.failure_stage, "independent_oracle")

    def test_oracle_chain_links_cover_every_adjacent_pair_of_every_symbol(self):
        seen = []

        def oracle(capture):
            approval = independent_oracle(capture)
            seen.extend(approval.chain_links)
            return approval

        _capture, report, _transport = self.execute(oracle=oracle)
        self.assertTrue(report.success, report)
        self.assertEqual(len(seen), 7 * 8)  # nine rows per symbol, eight adjacent pairs.
        self.assertTrue(all(link[3] == link[4] for link in seen))
        self.assertEqual({link[0] for link in seen}, set(S))
        self.assertIn(("3105", "2026-10-06", "2026-10-08", 90, 90), seen)  # The post-cutoff link is chain evidence.

    def test_post_cutoff_rows_are_not_calendar_or_ratio(self):
        post = ("2026-10-07", "2026-10-08", "2026-10-09")
        documents = [make_document(index, days=D + post, today=(100 + index, 120 + index, 0, 73, 87, 105 + index,
                                                                90 + index, 2 ** 63 - 1, 1, 2 ** 63 - 2)) for index in range(7)]
        _capture, report, _transport = self.execute(documents)
        self.assertTrue(report.success, report)

    def test_exact_fraction_and_integer_gate_no_rounding(self):
        def consumer(capture):
            for s in S:
                for cutoff, _days in W:
                    capture.consume(s, cutoff)
            for symbol, numerator, denominator, passed in (("3105", 5, 100, True), ("3293", 5, 101, True)):
                result = capture.consume(symbol, "2026-10-05")
                self.assertEqual((result.numerator, result.positive_denominator), (numerator, denominator))
                self.assertEqual(result.exact_ratio, Fraction(numerator, denominator))
                self.assertEqual(result.at_most_five_percent, passed)
        _capture, report, _transport = self.execute(consumer=consumer)
        self.assertTrue(report.success, report)

    def test_first_failure_http_auth_redirect_encoding_and_duplicate_headers(self):
        document = fixture()[0]
        for response in [Response(b"x", status=401), Response(b"x", status=402), Response(b"x", status=403),
            Response(b"x", status=429), Response(b"x", status=302), Response(b"x", media="text/html"),
            Response(b"x", headers=[("Content-Type", "application/json"), ("Content-Encoding", "gzip")]),
            Response(b"x", headers=[("Content-Type", "application/json"), ("Content-Encoding", "br")]),
            Response(b"x", headers=[("Content-Type", "application/json"), ("Content-Length", "1"), ("Content-Length", "1")]),
            Response(json_body(document), headers=[("Content-Type", "application/json"), ("Location", "/new")]),
            Response(json_body(document), headers=[("Content-Type", "application/json"), ("Location", "/a"), ("Location", "/b")]),
            Response(b"x", headers=[("Content-Type", "application/json"), ("Content-Length", "1"), ("Transfer-Encoding", "chunked")])]:
            with self.fresh():
                report, _transport = self.rejected(responses=[response], attempted=1)
                self.assertFalse(report.receipts[0].full_eof)
                self.assertIsNone(report.receipts[0].body_sha256)
        # A later URL's HTTP failure keeps the earlier ones SPENT and the rest unattempted, FinMind included.
        documents = fixture()
        responses = [Response(json_body(d)) for d in documents[:2]] + [Response(b"x", status=402)]
        with self.fresh():
            report, _transport = self.rejected(responses=responses, error="http_status", attempted=3)
        self.assertEqual(report.attempted_spent, M.URLS[:3])
        self.assertEqual(report.unattempted_not_spent, M.URLS[3:])

    def test_untrusted_content_type_does_not_enter_receipts_or_diagnostics(self):
        for media in ("text/csv; raw=private marker", "text/csv; charset=big5", "private marker" * 10000):
            response = Response(b"x", media=media)
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(responses=[response], error="http_content_type", attempted=1)
                self.assertEqual(report.receipts[0].content_type, "")
                self.assertNotIn("private marker", repr(report))

    def test_cap_read_before_no_plus_one_unknown_exact_cap(self):
        for chunked in (False, True):
            response = Response(b"x" * 1_048_576, length=None, chunked=chunked)
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(responses=[response], error="bounded_prefix_no_eof", attempted=1)
                self.assertEqual(sum(response.requests), 1_048_576)
                self.assertEqual(report.receipts[0].body_bytes, 1_048_576)
                self.assertIsNone(report.receipts[0].body_sha256)

    def test_exact_content_length_cap_eof_hash_before_parse(self):
        response = Response(b"x" * 1_048_576)
        report, _transport = self.rejected(responses=[response], attempted=1)
        self.assertTrue(report.receipts[0].full_eof)
        self.assertEqual(report.receipts[0].body_sha256, hashlib.sha256(response.body).hexdigest())
        self.assertEqual(sum(response.requests), 1_048_576)
        self.assertEqual(report.failure_stage, "finmind_parse")

    def test_oversize_declared_body_rejected_before_read(self):
        response = Response(b"x", length="1048577")
        self.rejected(responses=[response], error="raw_cap", attempted=1)
        self.assertEqual(response.requests, [])

    def test_unknown_under_cap_and_truncated_framing(self):
        documents = fixture()
        responses = [Response(json_body(d), length=None) for d in documents]
        _capture, report, _transport = self.execute(responses=responses)
        self.assertTrue(report.success, report)
        with self.fresh():
            self.rejected(responses=[Response(b"x", length="2")], error="truncated_body", attempted=1)

    def test_aggregate_remaining_limits_read_without_extra_probe(self):
        # Exercise the real reader with pre-existing cumulative RAM bytes.
        capture = self.capture()
        capture._deadline = M.time.monotonic() + 180
        capture._raw_total = 8_388_608 - 7
        response = Response(b"abcdefgh", length=None)
        transport = Transport([response])
        capture._connection_factory = transport.connection
        with self.assertRaisesRegex(M.MarginSourceError, "bounded_prefix_no_eof"):
            capture._fetch(0)
        self.assertEqual(response.requests, [7])
        self.assertIsNone(capture._originals[0].receipt.body_sha256)
        capture.release()

    def test_retained_roots_deduplicate_and_enforce_cap(self):
        shared = bytearray(b"abc")
        self.assertEqual(M.retained_estimate(shared, shared), M.retained_estimate(shared))
        view = memoryview(shared)
        self.assertEqual(M.retained_estimate(view), sys.getsizeof(view) + sys.getsizeof(shared))
        self.assertEqual(M.retained_estimate(view, shared), M.retained_estimate(view))
        view.release()
        def oracle(capture):
            capture.roots.hold("oracle.too_large", bytearray(33_554_433))
            capture._measure()
        self.rejected(oracle=oracle, error="retained_roots_cap", attempted=7)

    def test_expiry_never_resets_or_extends_on_read(self):
        def oracle(capture):
            result = independent_oracle(capture)
            capture._deadline = M.time.monotonic() - 1
            return result
        self.rejected(oracle=oracle, error="expired", attempted=7)
        # New fixture lifecycle: expiry during the positive consumer fails and
        # denies previously created handles without changing the deadline.
        with patch.object(M, "_SPENT_NAMESPACES", set()):
            def consumer(capture):
                handle = capture.consume(S[0], "2026-10-05")
                capture._deadline = M.time.monotonic() - 1
                before = capture._deadline
                with self.assertRaisesRegex(M.MarginSourceError, "expired"):
                    handle.exact_ratio
                self.assertEqual(capture._deadline, before)
            _capture, report, _transport = self.execute(consumer=consumer)
            self.assertFalse(report.success)

    def test_request_timeout_and_batch_clock_cooperate(self):
        capture = self.capture()
        capture._deadline = M.time.monotonic() + 180
        transport = Transport([Response(b"a")])
        capture._connection_factory = transport.connection
        baseline = M.time.monotonic()
        # Creation succeeds, but elapsed request budget fails before any read.
        with patch.object(M.time, "monotonic", side_effect=[baseline, baseline, baseline, baseline + 21, baseline + 21]):
            with self.assertRaisesRegex(M.MarginSourceError, "request_timeout"):
                capture._fetch(0)
        self.assertEqual(transport.responses[0].requests, [])
        capture.release()

    def test_failure_trace_and_cause_context_raw_aliases_cleanup(self):
        saved = {}

        def oracle(capture):
            view = capture.originals()[0]
            raw = view.body("oracle.alias_view")
            document = {"raw": bytearray(raw), "parsed": ["private raw marker"]}
            capture.roots.hold("oracle.alias_document", document)
            saved["view"], saved["document"] = raw, document
            try:
                raise json.JSONDecodeError("private raw marker", "private raw marker" * 10000, 1)
            except BaseException as cause:
                capture.roots.hold("exception.cause_alias", cause)
                saved["cause"] = cause
                try:
                    raise RuntimeError("private raw marker" * 10000) from cause
                except BaseException as exc:
                    capture.roots.hold("exception.alias", exc)
                    saved["exception"] = exc
                    raise

        report, _transport = self.rejected(oracle=oracle, error="unexpected_exception", attempted=7)
        self.assertTrue(report.trace_events)
        self.assertNotIn("private raw marker", repr(report))
        self.assertEqual(saved["document"], {})
        with self.assertRaises(ValueError):
            len(saved["view"])
        for exc in (saved["exception"], saved["cause"]):
            self.assertIsNone(exc.__traceback__)
            self.assertIsNone(exc.__cause__)
            self.assertIsNone(exc.__context__)
            self.assertEqual(exc.args, ("scrubbed_exception",))
            self.assertFalse(getattr(exc, "doc", None))

    def test_secondary_cleanup_error_does_not_replace_first_failure(self):
        response = Response(b"x", status=403)
        def close():
            raise RuntimeError("must not expose raw")
        response.close = close
        # execute's close assertions don't fit an intentionally failed close.
        transport = Transport([response])
        capture = self.capture(connection_factory=transport.connection)
        report = capture.run(independent_oracle, positive_consumer)
        self.assertEqual(report.primary_error, "http_status")
        self.assertIn("response_close_failed", report.secondary_diagnostics)
        self.assertNotIn("must not expose raw", repr(report))
        self.assertTrue(transport.connections[0].closed)

    def test_new_transport_cleanup_failure_stops_after_one_attempt(self):
        response = Response(json_body(fixture()[0]))
        def close():
            raise RuntimeError("private close diagnostic")
        response.close = close
        transport = Transport([response])
        capture = self.capture(connection_factory=transport.connection)
        report = capture.run(independent_oracle, positive_consumer)
        self.assertFalse(report.success)
        self.assertEqual(report.primary_error, "transport_cleanup_failed")
        self.assertEqual(report.attempted_spent, (M.URLS[0],))
        self.assertEqual(report.unattempted_not_spent, M.URLS[1:])
        self.assertTrue(report.receipts[0].full_eof)
        self.assertIn("response_close_failed", report.secondary_diagnostics)
        self.assertNotIn("private close diagnostic", repr(report))

    def test_pending_failure_no_positive_callback_or_replay(self):
        called = []
        def consumer(_capture):
            called.append(True)
        report, _transport = self.rejected(oracle=lambda c: None, consumer=consumer, attempted=7)
        self.assertEqual(called, [])
        capture = self.capture()
        with self.assertRaisesRegex(M.MarginSourceError, "namespace_already_spent"):
            capture.run(independent_oracle, positive_consumer)

    def test_all_14_positive_consumers_required(self):
        _capture, report, _transport = self.execute(consumer=lambda c: c.consume(S[0], "2026-10-05"))
        self.assertFalse(report.success)
        self.assertEqual(report.primary_error, "positive_consumer_incomplete")

    def test_unsupported_getter_consumer_and_trace_guard(self):
        capture = self.capture()
        with self.assertRaisesRegex(M.MarginSourceError, "unsupported_selector"):
            capture.getter(S[0], "2026-10-10")
        with self.assertRaisesRegex(M.MarginSourceError, "unsupported_consumer"):
            capture.consume(S[0], "2026-10-05", consumer="plan")
        with patch.object(M.sys, "gettrace", return_value=object()):
            with self.assertRaisesRegex(M.MarginSourceError, "trace_already_active"):
                capture.run(independent_oracle, positive_consumer)
        self.assertEqual(capture._attempted, [])

    def test_exact_types_cannot_use_custom_equality(self):
        class Equal:
            def __eq__(self, _other):
                return True
        class Str(str):
            pass
        for name in ("market", "instrument", "purpose", "symbols", "cutoffs"):
            with self.assertRaisesRegex(M.MarginSourceError, "unsupported_use"):
                self.capture(use=replace(M.UseRequest(), **{name: Equal()}))
        with self.assertRaisesRegex(M.MarginSourceError, "unsupported_use"):
            self.capture(use=replace(M.UseRequest(), symbols=(Str("3105"),) + S[1:]))
        capture = self.capture()
        for name in ("global_actual", "owner_actual", "engineer_actual", "holder_actual", "model", "effort",
                     "runtime_id", "terminal_handle", "receipt_url", "issue", "namespace", "candidate_sha",
                     "module_sha256", "full_script_sha256", "full_command_sha256", "policy_sha256", "expires_at_utc"):
            with self.assertRaisesRegex(M.MarginSourceError, "seal_field_type"):
                self.capture(seal=replace(capture._seal, **{name: Equal()}))
            with self.assertRaisesRegex(M.MarginSourceError, "seal_field_type"):
                self.capture(seal=replace(capture._seal, **{name: Str(getattr(capture._seal, name))}))
        for name in ("session_id", "model", "effort", "candidate_sha"):
            with self.assertRaisesRegex(M.MarginSourceError, "runtime_field_type"):
                self.capture(runtime=replace(capture_runtime(), **{name: Equal()}))
        with self.assertRaisesRegex(M.MarginSourceError, "runtime_field_type"):
            self.capture(runtime=replace(capture_runtime(), parent_session_id=Equal()))
        for factory in (Equal(), "not callable", 7):
            with self.assertRaisesRegex(M.MarginSourceError, "connection_factory_type"):
                self.capture(connection_factory=factory)
        def oracle(c):
            return replace(independent_oracle(c), body_sha256=Equal())
        self.rejected(oracle=oracle, error="oracle_hashes", attempted=7)

    def test_unicode_digits_are_not_the_declared_ascii_date_grammar(self):
        for day in ("２０２６-０９-２４", "٢٠٢٦-٠٩-٢٤", "2026-9-24", "20260924", " 2026-09-24"):
            documents = fixture()
            documents[0]["data"][0]["date"] = day
            with self.fresh():
                self.rejected(documents, error="date_grammar", attempted=1)

    def test_receipt_declared_schema_is_not_failed_actual_validation(self):
        documents = fixture()
        documents[-1]["data"][-1]["ShortSaleLimit"] = True
        report, _transport = self.rejected(documents, error="integer_int64", attempted=7)
        self.assertTrue(all(r.schema_validated for r in report.receipts[:-1]))
        self.assertFalse(report.receipts[-1].schema_validated)
        self.assertEqual(report.receipts[-1].declared_schema, M.FINMIND_FIELDS)

    def test_native_httpresponse_ram_framing_and_detached_close_socket(self):
        body = json_body(fixture()[0])
        for framing in ("length", "unknown", "chunked"):
            response = native_response(body, framing=framing, connection_close=True)
            transport = Transport([response])
            create = transport.connection
            def detached(host, timeout):
                conn = create(host, timeout)
                get = conn.getresponse
                def getresponse():
                    result = get()
                    conn.sock = None  # Detach only after the actual header phase.
                    return result
                conn.getresponse = getresponse
                return conn
            capture = self.capture(connection_factory=detached)
            capture._deadline = M.time.monotonic() + 180
            original = capture._fetch(0)
            self.assertTrue(original.receipt.full_eof)
            self.assertEqual(original.receipt.body_sha256, hashlib.sha256(body).hexdigest())
            self.assertTrue(response.isclosed())
            capture.release()
        # Keep-alive (no Connection: close): the socket stays attached and the same EOF proof applies.
        for framing in ("length", "chunked"):
            response = native_response(body, framing=framing, connection_close=False)
            transport = Transport([response])
            capture = self.capture(connection_factory=transport.connection)
            capture._deadline = M.time.monotonic() + 180
            original = capture._fetch(0)
            self.assertTrue(original.receipt.full_eof and response.isclosed())
            self.assertEqual(bytes(original.buffer), body)
            capture.release()
        # At an exact cap, the real chunked decoder has not read the terminal
        # zero chunk; no extra byte/framing probe is allowed to prove EOF.
        response = native_response(b"x" * 1_048_576, framing="chunked")
        transport = Transport([response])
        capture = self.capture(connection_factory=transport.connection)
        capture._deadline = M.time.monotonic() + 180
        with self.assertRaisesRegex(M.MarginSourceError, "bounded_prefix_no_eof"):
            capture._fetch(0)
        self.assertIsNone(capture._originals[0].receipt.body_sha256)
        capture.release()

    def test_remaining_request_budget_is_refreshed_between_phases(self):
        response = Response(json_body(fixture()[0]))
        transport, now = Transport([response]), [1000.0]
        capture = self.capture()
        capture._deadline = 1180.0
        create = transport.connection
        def phases(host, timeout):
            self.assertEqual(timeout, 20)
            conn = create(host, timeout)
            request, get = conn.request, conn.getresponse
            def send(*args, **kwargs):
                request(*args, **kwargs)
                now[0] += 19
            def headers():
                now[0] += 0.5
                return get()
            conn.request, conn.getresponse = send, headers
            return conn
        capture._connection_factory = phases
        with patch.object(M.time, "monotonic", side_effect=lambda: now[0]):
            original = capture._fetch(0)
        self.assertTrue(original.receipt.full_eof)
        self.assertEqual(transport.connections[0].sock.timeouts[0], 1)
        self.assertTrue(all(seconds <= 1 for seconds in transport.connections[0].sock.timeouts))
        capture.release()

    def test_header_or_read_overrun_stops_before_parse_or_next_request(self):
        body = json_body(fixture()[0])
        for overrun_phase in ("headers", "read"):
            response = Response(body)
            transport, capture, now = Transport([response]), self.capture(), [1000.0]
            capture._deadline = 1180.0
            create = transport.connection
            def phases(host, timeout):
                conn = create(host, timeout)
                get = conn.getresponse
                def headers():
                    if overrun_phase == "headers":
                        now[0] += 21
                    return get()
                conn.getresponse = headers
                return conn
            read = response.read
            def read_body(count):
                data = read(count)
                if overrun_phase == "read":
                    now[0] += 21
                return data
            response.read = read_body
            capture._connection_factory = phases
            with patch.object(M.time, "monotonic", side_effect=lambda: now[0]):
                with self.assertRaisesRegex(M.MarginSourceError, "request_timeout"):
                    capture._fetch(0)
            self.assertEqual(len(capture._attempted), 1)
            self.assertFalse(capture._originals[0].receipt.full_eof)
            self.assertIsNone(capture._originals[0].receipt.body_sha256)
            self.assertIsNone(capture._originals[0].text)
            self.assertIsNone(capture._originals[0].document)
            capture.release()

    def test_declared_approval_alias_is_cleared_after_release(self):
        saved = []
        def oracle(capture):
            approval = independent_oracle(capture)
            saved.append(approval)
            capture.roots.hold("oracle.approval_alias", approval)
            return approval
        _capture, report, _transport = self.execute(oracle=oracle)
        self.assertTrue(report.success, report)
        self.assertIsNone(saved[0].balances)
        self.assertIsNone(saved[0].ratios)
        self.assertIsNone(saved[0].chain_links)
        self.assertIsNone(saved[0].body_sha256)

    def test_above_threshold_stays_exact_with_large_int64_values(self):
        documents = fixture()
        set_today(documents[0], 5, 106)
        set_today(documents[1], 0, (1 << 63) - 10)
        set_today(documents[1], 5, (1 << 63) - 1)
        def consumer(capture):
            for symbol in S:
                for cutoff, _days in W:
                    capture.consume(symbol, cutoff)
            above = capture.consume(S[0], "2026-10-05")
            self.assertEqual(above.exact_ratio, Fraction(6, 100))
            self.assertFalse(above.at_most_five_percent)
            large = capture.consume(S[1], "2026-10-05")
            self.assertEqual(large.numerator, 9)
            self.assertEqual(large.positive_denominator, (1 << 63) - 10)
            self.assertTrue(large.at_most_five_percent)
        _capture, report, _transport = self.execute(documents, consumer=consumer)
        self.assertTrue(report.success, report)

    def test_claude_runtime_identity_comes_from_the_seal_not_the_module(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        retired_global = "01a12102-9891-7293-8c66-a342094e0990"
        for retired in ("gpt-6.1-sol", retired_global):
            self.assertNotIn(retired, source)
        self.assertFalse(hasattr(M, "GLOBAL"))
        # The retired values are ordinary data now. Any consistent Claude model
        # and effort pass; nothing about them is fixed in the module.
        for model, effort in (("claude-sonnet-5-5", "xhigh"), ("claude-opus-5-5", "medium"), ("claude-haiku-5-5", "max")):
            with patch.dict(os.environ, {M.SESSION_ENV: QA, M.EFFORT_ENV: effort}):
                self.capture(seal_changes=dict(global_actual=retired_global, model=model, effort=effort),
                             runtime_changes=dict(model=model, effort=effort))
        _capture, report, _transport = self.execute()
        self.assertTrue(report.success, report)

    def test_identity_format_independence_and_runtime_binding_are_not_relaxed(self):
        other = "01a17777-7777-7777-8777-777777777777"
        for changes, code in (
            (dict(seal_changes=dict(global_actual="not-a-uuid")), "runtime_identity_invalid"),
            (dict(seal_changes=dict(owner_actual=QA.upper())), "runtime_identity_invalid"),
            (dict(seal_changes=dict(runtime_id="x")), "runtime_identity_invalid"),
            (dict(seal_changes=dict(model="gpt-6.1-sol")), "model_invalid"),
            (dict(seal_changes=dict(model="Claude-sonnet")), "model_invalid"),
            (dict(seal_changes=dict(effort="ultra")), "effort_invalid"),
            (dict(seal_changes=dict(effort="")), "effort_invalid"),
            (dict(seal_changes=dict(terminal_handle="terminal")), "runtime_binding_invalid"),
            (dict(seal_changes=dict(terminal_handle="term_ bad")), "runtime_binding_invalid"),
            (dict(seal_changes=dict(global_actual=QA)), "qa_not_independent"),
            (dict(seal_changes=dict(owner_actual=QA)), "qa_not_independent"),
            (dict(seal_changes=dict(engineer_actual=QA)), "qa_not_independent"),
            (dict(seal_changes=dict(owner_actual=ENGINEER)), "role_actors_not_distinct"),
            (dict(seal_changes=dict(global_actual=OWNER)), "role_actors_not_distinct"),
            (dict(runtime_changes=dict(session_id=other)), "sole_qa_runtime"),
            (dict(runtime_changes=dict(parent_session_id=OWNER)), "sole_qa_runtime"),
            (dict(runtime_changes=dict(model="claude-opus-5-5")), "sole_qa_runtime"),
            (dict(runtime_changes=dict(effort="high")), "sole_qa_runtime"),
            (dict(seal_changes=dict(namespace=M.NAMESPACE + "x")), "seal_authority"),
            (dict(seal_changes=dict(issue="YiCheng0608/stock-lab#32")), "seal_authority"),
            (dict(seal_changes=dict(receipt_url="https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-1")),
             "seal_receipt"),
        ):
            with self.assertRaisesRegex(M.MarginSourceError, "^" + code + "$"):
                self.capture(**changes)

    def test_live_claude_environment_must_match_the_seal(self):
        base = {k: v for k, v in os.environ.items() if k not in (M.SESSION_ENV, M.EFFORT_ENV)}
        for environment, code in (
            ({}, "runtime_env_missing"),
            ({M.SESSION_ENV: QA}, "runtime_env_missing"),
            ({M.EFFORT_ENV: EFFORT}, "runtime_env_missing"),
            ({M.SESSION_ENV: "", M.EFFORT_ENV: EFFORT}, "runtime_env_missing"),
            ({M.SESSION_ENV: QA, M.EFFORT_ENV: ""}, "runtime_env_missing"),
            # The legacy Codex variables are never a substitute.
            ({"CODEX_THREAD_ID": QA, "CODEX_SESSION_ID": QA, M.EFFORT_ENV: EFFORT}, "runtime_env_missing"),
            ({M.SESSION_ENV: ENGINEER, M.EFFORT_ENV: EFFORT}, "actual_binding_conflict"),
            ({M.SESSION_ENV: QA, M.EFFORT_ENV: "high"}, "runtime_effort_conflict"),
        ):
            with patch.dict(os.environ, {**base, **environment}, clear=True):
                with self.assertRaisesRegex(M.MarginSourceError, "^" + code + "$"):
                    self.capture()

    def test_live_environment_is_rechecked_before_anything_is_spent(self):
        capture = self.capture(connection_factory=Transport([]).connection)
        with patch.dict(os.environ, {M.SESSION_ENV: ENGINEER}):
            with self.assertRaisesRegex(M.MarginSourceError, "^actual_binding_conflict$"):
                capture.run(independent_oracle, positive_consumer)
        self.assertEqual(capture._attempted, [])
        self.assertEqual(capture._originals, [])
        self.assertEqual(M._SPENT_NAMESPACES, set())
        self.assertIsNone(sys.gettrace())

    def test_seal_expiry_and_one_time_namespace_are_not_relaxed(self):
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        naive = (datetime.now() + timedelta(hours=1)).isoformat()
        for value in (past, naive, "2099-01-01T00:00:00Z", "2099-01-01 00:00:00+00:00", "", "tomorrow"):
            with self.assertRaisesRegex(M.MarginSourceError, "^seal_expiry$"):
                self.capture(seal_changes=dict(expires_at_utc=value))
        _capture, report, _transport = self.execute()  # A success consumes the one-time namespace too.
        self.assertTrue(report.success, report)
        self.assertEqual(M._SPENT_NAMESPACES, {M.NAMESPACE})
        with self.assertRaisesRegex(M.MarginSourceError, "^namespace_already_spent$"):
            self.capture(connection_factory=Transport([]).connection).run(
                independent_oracle, positive_consumer)

    def test_policy_v2_differs_from_v1_only_by_the_approved_keys(self):
        def canonical(document):
            return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

        def diff(old, new, path=""):
            result = []
            for key in sorted(set(old) | set(new)):
                here = path + "/" + key
                if key not in new:
                    result.append((here, "removed"))
                elif key not in old:
                    result.append((here, "added"))
                elif isinstance(old[key], dict) and isinstance(new[key], dict):
                    result.extend(diff(old[key], new[key], here))
                elif old[key] != new[key]:
                    result.append((here, "changed"))
            return result

        base = "issue31-margin-seven-cutoffs-1005-1006-v1/"
        old, new = json.loads(OLD_POLICY), json.loads(POLICY)
        self.assertEqual(canonical(new), POLICY)  # Canonical: sorted keys, compact UTF-8.
        self.assertEqual((len(POLICY), hashlib.sha256(POLICY).hexdigest()), (M.POLICY_BYTES, M.POLICY_SHA256))
        self.assertEqual((new["namespace"], M.NAMESPACE), (base + "qa3", base + "qa3"))
        self.assertEqual(diff(old, new), [
            ("/caps/maxRequests", "changed"), ("/internalConsistency", "added"), ("/namespace", "changed"),
            ("/officialAnchorDates", "removed"), ("/officialAnchorUrl", "removed"), ("/rowSchema", "added"),
            ("/schema", "changed"), ("/supportedUse", "changed"), ("/unitInference/historicalExtension", "removed"),
            ("/unitInference/kind", "changed"), ("/unitInference/officialAnchorVerified", "added"),
            ("/unitInference/requireAllSevenSameDateBothAnchorsExact", "removed"),
            ("/unitInference/requireEachSymbolAtLeastOneNonzeroAnchor", "removed"),
            ("/unsupportedUse", "changed"), ("/version", "changed")])
        self.assertEqual((old["schema"], new["schema"]), ("ordinary-margin-source-policy/v1", "ordinary-margin-source-policy/v2"))
        self.assertEqual((old["version"], new["version"]),
                         ("ordinary-margin-cutoffs-1005-1006-v1", "ordinary-margin-cutoffs-1005-1006-v2"))
        self.assertEqual((old["caps"]["maxRequests"], new["caps"]["maxRequests"]), (8, 7))
        self.assertEqual({k: v for k, v in old["caps"].items() if k != "maxRequests"},
                         {k: v for k, v in new["caps"].items() if k != "maxRequests"})
        self.assertEqual([x for x in old["supportedUse"] if x not in new["supportedUse"]], ["same_date_anchor_trace"])
        self.assertEqual(new["supportedUse"], [x for x in old["supportedUse"] if x != "same_date_anchor_trace"])
        self.assertEqual(new["unsupportedUse"], old["unsupportedUse"] + ["official_unit_verification"])
        self.assertEqual(new["unitInference"], {"canonical": "lots", "kind": "explicit_provider_inference",
                                                "numericScale": 1, "officialAnchorVerified": False, "providerLiteral": False})
        self.assertEqual(new["internalConsistency"], {
            "chain": "MarginPurchaseYesterdayBalance[i+1]==MarginPurchaseTodayBalance[i]",
            "requiredDaysThroughCutoff": list(D), "requirePostCutoffRow": True, "sameDateSetAcrossSymbols": True})
        self.assertEqual(new["rowSchema"], {
            "extra": "reject", "noteMaxChars": 256, "noteNullable": True, "numeric": "non-bool-int-0-to-int64-max",
            "optional": ["Note"], "required": list(M.REQUIRED_FIELDS), "stringFields": ["Note", "date", "stock_id"]})
        self.assertEqual(len(new["rowSchema"]["required"]), 15)
        self.assertNotIn("Note", new["rowSchema"]["required"])
        self.assertEqual(M.NOTE_MAX_CHARS, new["rowSchema"]["noteMaxChars"])
        self.assertNotIn("historicalExtension", new["unitInference"])
        # Unchanged on purpose: the rest of v1 (windows, formula, threshold, transport, lifecycle...).
        for key in ("requiredWindows", "formula", "threshold", "ratioRepresentation", "transport", "lifecycle",
                    "firstFailure", "symbols", "query", "queryKeyOrder", "canonicalCalendarSource", "consumer"):
            self.assertEqual(new[key], old[key], key)
        self.assertEqual(new["requiredWindows"], {cutoff: list(days) for cutoff, days in W})
        self.assertTrue(all(url.count("data_id=") == 1 for url in M.URLS))
        # SPENT / NO-RETRY: the published v1 text (qa1 and qa2 namespaces) is no longer accepted.
        for spent in (OLD_POLICY, QA2_POLICY):
            with self.assertRaisesRegex(M.MarginSourceError, "^external_policy_pin$"):
                self.capture(external_policy_utf8=spent)
        for namespace in (base + "qa1", base + "qa2"):
            with self.assertRaisesRegex(M.MarginSourceError, "^seal_authority$"):
                self.capture(seal_changes=dict(namespace=namespace))
        for pin in ("47ea789e4bac27cf736f9294f5c0563425b15cd5541748567f985ae262f224d7",
                    "b95e8d9f6b7b2cff8b9984bc54ace823c5d8b36c322d5311136cebafeae0fed9"):
            self.assertNotEqual(M.POLICY_SHA256, pin)
            with self.assertRaisesRegex(M.MarginSourceError, "^seal_authority$"):
                self.capture(seal_changes=dict(policy_sha256=pin))

    def test_content_type_rule_matches_issue36_and_whitelists_application_json_only(self):
        documents = fixture()
        ok = ("application/json", "application/json; charset=utf-8", 'application/json;charset="utf-8"',
              " Application/JSON ; Charset=\"UTF-8\" ", "application/json;charset=UTF-8")
        for media in ok:
            responses = [Response(json_body(d), media=media) for d in documents]
            with self.fresh():
                _capture, report, _transport = self.execute(responses=responses)
            self.assertTrue(report.success, (media, report))
            self.assertEqual(report.receipts[0].content_type, ";".join(p.strip() for p in media.lower().split(";")))
        bad = ("application/json;charset=latin-1", "application/json;charset=utf-16", "application/json;charset=utf-8;format=x",
               "application/json;", "application/json;;charset=utf-8", "application/json;charset=utf-8;charset=big5",
               "application/csv", "application/csv;charset=utf-8", "text/csv", "text/plain", "application/octet-stream",
               "application/vnd.ms-excel", "text/html", "text/json", "application/jsonx", "", "application/json" + ";" * 200)
        for media in bad:
            with self.fresh():
                report, _transport = self.rejected(responses=[Response(b"x", media=media)], error="http_content_type", attempted=1)
            self.assertEqual((report.receipts[0].content_type, report.receipts[0].body_bytes), ("", 0))
        with self.fresh():  # No Content-Type header at all.
            self.rejected(responses=[Response(b"x", headers=[("Content-Length", "1")])], error="http_content_type", attempted=1)
        # Every one of the seven URLs applies the same rule (not only the first).
        for position in (1, 6):
            responses = [Response(json_body(d)) for d in documents]
            responses[position] = Response(json_body(documents[position]), media="text/csv")
            with self.fresh():
                self.rejected(responses=responses, error="http_content_type", attempted=position + 1)

    def test_documented_response_shapes_replay_through_real_httpresponse_framing(self):
        # The Issue 36 TPEx shape (chunked, cache-control x2, vary x3, set-cookie) is the only real shape known; the
        # FinMind shape is unverified, so Content-Length and close-delimited framing are replayed as well.
        document = fixture()[0]
        document["data"] = document["data"] * 120  # Not a valid batch: transport only, > 64 KiB and many chunks.
        body = json_body(document)
        self.assertGreater(len(body), 65_536)
        self.assertLess(len(body), 1_048_576)
        for connection_header in ("close", "keep-alive", None):
            headers = shape36_headers(connection_header)
            response = wire_response(body, headers)
            transport = Transport([response])
            create = transport.connection

            def factory(host, timeout, create=create, detach=(connection_header == "close")):
                connection = create(host, timeout)
                get = connection.getresponse

                def getresponse():
                    result = get()
                    if detach:
                        connection.sock = None  # The stdlib detaches the socket of a will_close response.
                    return result

                connection.getresponse = getresponse
                return connection

            capture = self.capture(connection_factory=factory)
            capture._deadline = M.time.monotonic() + 180
            original = capture._fetch(0)
            receipt = original.receipt
            self.assertTrue(receipt.full_eof and receipt.request_started, connection_header)
            self.assertEqual((receipt.status, receipt.content_type, receipt.body_bytes),
                             (200, "application/json;charset=utf-8", len(body)))
            self.assertEqual(receipt.body_sha256, hashlib.sha256(body).hexdigest())
            self.assertEqual(bytes(original.buffer), body)
            self.assertTrue(response.isclosed())
            # The replayed wire really carried the shape, parsed by the stdlib itself.
            names = [name.lower() for name, _value in response.getheaders()]
            self.assertEqual((names.count("cache-control"), names.count("vary"), names.count("set-cookie")), (2, 3, 1))
            self.assertEqual(len(names), 18 if connection_header is None else 19)
            self.assertTrue(response.chunked)
            self.assertNotIn("private-cookie-marker", repr(receipt))
            self.assertEqual(transport.calls[0][2], REQUEST_HEADERS)  # Nothing but the fixed headers; no cookie is sent back.
            capture.release()

    def test_documented_response_shape_full_lifecycle_for_all_seven_urls(self):
        documents = fixture()
        shapes = []
        for index, document in enumerate(documents):
            body = json_body(document)
            if index % 3 == 0:
                shapes.append(wire_response(body, shape36_headers("close"), chunk=64))
            elif index % 3 == 1:
                shapes.append(native_response(body, framing="length", connection_close=False))
            else:
                shapes.append(native_response(body, framing="unknown", connection_close=True))
        _capture, report, transport = self.execute(responses=shapes)
        self.assertTrue(report.success, report)
        self.assertEqual(report.receipts[0].content_type, "application/json;charset=utf-8")
        self.assertEqual([r.body_sha256 for r in report.receipts],
                         [hashlib.sha256(json_body(d)).hexdigest() for d in documents])
        self.assertEqual((report.consumer_count, report.unattempted_not_spent), (14, ()))
        self.assertNotIn("private-cookie-marker", repr(report))
        self.assertTrue(all(call[2] == REQUEST_HEADERS for call in transport.calls))

    def test_empty_read_is_eof_only_with_the_framing_parsers_closed_state(self):
        class NeverClosed(Response):
            def read(self, count):
                self.requests.append(count)
                chunk = self.body[self.position:self.position + count]
                self.position += len(chunk)
                return chunk  # Never marks the response closed, even after the last byte.

            def isclosed(self):
                return False

        for response in (NeverClosed(b"x", length=None), NeverClosed(b"x")):
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(responses=[response], error="framing_eof_missing", attempted=1)
            self.assertFalse(report.receipts[0].full_eof)
            self.assertIsNone(report.receipts[0].body_sha256)

    # Transport seam: root cause of the sealed run's first failure (constructor).

    def test_regression_replacing_the_stdlib_global_breaks_a_composed_native_connection(self):
        native = http.client.HTTPSConnection

        class Audit:  # The failing harness shape: global replaced, native class composed inside it.
            def __init__(self, host, timeout):
                self.native = native(host, timeout=timeout)

        with patch.object(http.client, "HTTPSConnection", Audit):
            with self.assertRaises(TypeError):
                Audit("example.invalid", 20)
        self.assertIs(http.client.HTTPSConnection, native)
        connection = native("example.invalid", timeout=20)  # Restored: constructs without connecting.
        try:
            self.assertIsNone(connection.sock)
        finally:
            connection.close()

    def test_native_connection_builds_the_unconnected_stdlib_class(self):
        connection = M.native_connection("api.finmindtrade.com", 20)
        try:
            self.assertIs(type(connection), http.client.HTTPSConnection)
            self.assertEqual((connection.host, connection.port, connection.timeout), ("api.finmindtrade.com", 443, 20))
            self.assertIsNone(connection.sock)
        finally:
            connection.close()

    def test_replaced_stdlib_class_is_refused_before_anything_is_spent(self):
        class Replacement:
            pass

        with patch.object(http.client, "HTTPSConnection", Replacement):
            with self.assertRaisesRegex(M.MarginSourceError, "^transport_class_replaced$"):
                M.native_connection("example.invalid", 20)
            # Default (native) transport and an auditor's connection_factory are refused alike.
            unused = Transport([])
            for capture in (self.capture(), self.capture(connection_factory=unused.connection)):
                with self.assertRaisesRegex(M.MarginSourceError, "^transport_class_replaced$"):
                    capture.run(independent_oracle, positive_consumer)
                self.assertEqual(capture._attempted, [])
                self.assertEqual(capture._originals, [])
                self.assertEqual(M._SPENT_NAMESPACES, set())
                self.assertIsNone(sys.gettrace())
            self.assertEqual(unused.connections, [])  # The factory was never called.
        # A replacement installed before the module was imported is captured as
        # "native"; the class identity check still refuses it, factory or not.
        with patch.object(M, "_SPENT_NAMESPACES", set()), patch.object(
                http.client, "HTTPSConnection", Replacement), patch.object(M, "_NATIVE_HTTPS_CONNECTION", Replacement):
            with self.assertRaisesRegex(M.MarginSourceError, "^transport_class_replaced$"):
                M.native_connection("example.invalid", 20)
            unused = Transport([])
            for capture in (self.capture(), self.capture(connection_factory=unused.connection)):
                with self.assertRaisesRegex(M.MarginSourceError, "^transport_class_replaced$"):
                    capture.run(independent_oracle, positive_consumer)
                self.assertEqual(capture._attempted, [])
            self.assertEqual(unused.connections, [])
            self.assertEqual(M._SPENT_NAMESPACES, set())

    def test_default_transport_goes_through_native_connection(self):
        transport = Transport([Response(json_body(d)) for d in fixture()])
        capture = self.capture()
        with patch.object(M, "native_connection", transport.connection):
            report = capture.run(independent_oracle, positive_consumer)
        self.assertTrue(report.success, report)
        self.assertEqual(report.transport, "native_direct")
        self.assertEqual(len(transport.connections), 7)
        self.assertIsNone(capture._connection_factory)

    def test_request_headers_are_exactly_identity_and_the_fixed_user_agent(self):
        self.assertEqual(M.REQUEST_USER_AGENT, "stock-lab-issue31-local-ram/1")
        self.assertTrue(M.REQUEST_USER_AGENT.isascii())
        _capture, report, transport = self.execute()
        self.assertTrue(report.success, report)
        self.assertEqual(len(transport.calls), 7)
        for _url, method, headers in transport.calls:  # What the product passes, for each of the 8 requests.
            self.assertEqual(method, "GET")
            self.assertEqual(headers, REQUEST_HEADERS)
            self.assertEqual(sorted(key.lower() for key in headers), ["accept-encoding", "user-agent"])

    def test_wire_request_headers_through_the_real_stdlib_class_are_exact(self):
        response = Response(json_body(fixture()[0]))
        sent = []

        class Recorder(FakeSocket):
            def sendall(self, data):
                sent.append(bytes(data))

            def close(self):
                pass

        class Wire:  # Real stdlib request serialization into RAM; nothing is connected or sent anywhere.
            def __init__(self, host, timeout):
                self.native = M.native_connection(host, timeout)
                self.native.sock = Recorder()

            @property
            def sock(self):
                return self.native.sock

            def request(self, method, target, headers):
                self.native.request(method, target, headers=headers)

            def getresponse(self):
                return response

            def close(self):
                self.native.close()

        capture = self.capture(connection_factory=Wire)
        capture._deadline = M.time.monotonic() + 180
        original = capture._fetch(0)
        self.assertTrue(original.receipt.full_eof)
        head, separator, body = b"".join(sent).partition(b"\r\n\r\n")
        self.assertEqual((separator, body), (b"\r\n\r\n", b""))
        lines = head.decode("ascii").split("\r\n")
        self.assertEqual(lines[0], "GET /api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id=3105"
                                   "&start_date=2026-09-24&end_date=2026-10-09 HTTP/1.1")
        self.assertEqual(sorted(line.split(": ", 1) for line in lines[1:]), sorted([
            ["Host", "api.finmindtrade.com"], ["Accept-Encoding", "identity"],
            ["User-Agent", "stock-lab-issue31-local-ram/1"]]))
        capture.release()

    def test_audit_wrapper_composes_native_connection_without_replacing_the_global(self):
        transport = Transport([Response(json_body(d)) for d in fixture()])
        audit = []

        class AuditConnection:
            def __init__(self, host, timeout):
                self.native = M.native_connection(host, timeout)  # Real stdlib class, composed and never connected.
                self.inner = transport.connection(host, timeout)
                audit.append(self)

            @property
            def sock(self):
                return self.inner.sock

            def request(self, method, target, headers):
                self.inner.request(method, target, headers)

            def getresponse(self):
                return self.inner.getresponse()

            def close(self):
                self.inner.close()
                self.native.close()

        original_class = http.client.HTTPSConnection
        capture = self.capture(connection_factory=AuditConnection)
        report = capture.run(independent_oracle, positive_consumer)
        self.assertTrue(report.success, report)
        self.assertEqual(report.transport, "caller_factory")
        self.assertIs(http.client.HTTPSConnection, original_class)
        self.assertEqual(len(audit), 7)
        for item in audit:
            self.assertIs(type(item.native), original_class)
            self.assertIsNone(item.native.sock)  # Nothing was sent through the real class.
        self.assertIsNone(capture._connection_factory)

    def test_constructor_failure_is_spent_but_never_reports_a_started_request(self):
        def factory(host, timeout):
            raise RuntimeError("private constructor diagnostic")

        capture = self.capture(connection_factory=factory)
        report = capture.run(independent_oracle, positive_consumer)
        self.assertFalse(report.success)
        self.assertEqual(report.failure_stage, "finmind_capture")
        self.assertEqual(report.primary_error, "unexpected_exception")
        self.assertEqual(report.attempted_spent, (M.URLS[0],))
        self.assertEqual(report.unattempted_not_spent, M.URLS[1:])
        self.assertEqual(len(report.receipts), 1)
        self.assertFalse(report.receipts[0].request_started)
        self.assertEqual((report.receipts[0].body_bytes, report.receipts[0].body_sha256, report.receipts[0].status),
                         (0, None, None))
        self.assertTrue(any(event[:2] == ("finmind_capture", "_fetch") for event in report.trace_events))
        self.assertNotIn("private constructor diagnostic", repr(report))
        self.assertEqual(M._SPENT_NAMESPACES, {M.NAMESPACE})
        self.assertEqual((report.consumer_count, report.getter_count), (0, 0))

    def test_request_failure_after_construction_reports_a_started_request(self):
        class Connection:
            sock = FakeSocket()

            def request(self, method, target, headers):
                raise OSError("private request diagnostic")

            def close(self):
                pass

        capture = self.capture(connection_factory=lambda host, timeout: Connection())
        report = capture.run(independent_oracle, positive_consumer)
        self.assertFalse(report.success)
        self.assertEqual(report.attempted_spent, (M.URLS[0],))
        self.assertTrue(report.receipts[0].request_started)
        self.assertNotIn("private request diagnostic", repr(report))


def capture_runtime():
    return M.RuntimeIdentity(QA, None, MODEL, EFFORT, SHA)


def base_seal():
    return M.FinancialStartSeal(GLOBAL_ID, OWNER, ENGINEER, QA, MODEL, EFFORT, RUNTIME_ID, TERMINAL,
        "https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-9999999999", M.ISSUE, M.NAMESPACE,
        SHA, hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest(), hashlib.sha256(SCRIPT).hexdigest(),
        hashlib.sha256(COMMAND.encode()).hexdigest(), M.POLICY_SHA256, M.CAPS,
        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())


if __name__ == "__main__":
    unittest.main(verbosity=2)
