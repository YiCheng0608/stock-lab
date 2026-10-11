"""Standalone stdlib/RAM engineering checks; synthetic data is never source QA.

Run exactly: python -B -X utf8 backend/tests/test_tpex_margin_balance_source.py
No pytest/conftest, worker/application/config import, network, DB, filesystem
artifacts, subprocess, or installed dependencies. Only the two source files are
read for direct import and the seal's module hash. HTTPS is mocked at the
connection boundary through the product's ``connection_factory`` seam (never by
replacing the ``http.client.HTTPSConnection`` global); the real transport
reader/order/framing still executes. Constructing the stdlib connection class
never connects, so the regression tests may build it without any network I/O.
"""

import csv
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

# Exact externally published qa1 codeblock from issuecomment-6084167671 (SPENT / NO-RETRY). Kept only to
# prove by program that the qa2 policy below differs from it in the namespace field alone.
OLD_POLICY = b'{"canonicalCalendarSource":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md#31.2","caps":{"batchCooperativeSeconds":180,"bodyBytes":1048576,"maxRequests":8,"redirects":0,"requestSeconds":20,"retainedRootsEstimateBytes":33554432,"retries":0,"totalRawBytes":8388608},"consumer":"ordinary-margin-change-ratio-v1","financialProvider":"FinMind","firstFailure":"stop_attempted_spent_unattempted_not_spent","formula":"(B[T]-B[T-5])/abs(B[T-5])","instrument":"ordinary_stock","lifecycle":"capture_eof_hash_then_independent_oracle_then_positive_consumer_then_release_and_exit","market":"TPEx","namespace":"issue31-margin-seven-cutoffs-1005-1006-v1/qa1","officialAnchorDates":["2026-10-08","2026-10-09"],"officialAnchorUrl":"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=data","query":{"dataset":"TaiwanStockMarginPurchaseShortSale","end_date":"2026-10-09","start_date":"2026-09-24"},"queryKeyOrder":["dataset","data_id","start_date","end_date"],"ratioRepresentation":{"exactThresholdComparison":"20*numerator<=positiveDenominator","numerator":"B[T]-B[T-5]","positiveDenominator":"abs(B[T-5])","roundedDisplayNotUsedForGate":true,"zeroDenominator":"reject"},"requiredWindows":{"2026-10-05":["2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]},"schema":"ordinary-margin-source-policy/v1","sourceDataset":"TaiwanStockMarginPurchaseShortSale","supportedUse":["local_personal_noncommercial","process_ram_snapshot","margin5_balance_change_ratio","same_date_anchor_trace"],"symbols":["3105","3293","5274","5347","6488","6510","8069"],"threshold":"0.05","transport":{"acceptEncoding":"identity","cookies":false,"proxies":false,"tokens":false},"unitInference":{"canonical":"lots","historicalExtension":"explicit_limited_snapshot_inference","kind":"conditional_combination_inference","numericScale":1,"providerLiteral":false,"requireAllSevenSameDateBothAnchorsExact":true,"requireEachSymbolAtLeastOneNonzeroAnchor":true},"unsupportedUse":["historical_pit","publication_time","first_availability","revision_history","historical_eligibility","historical_membership","actionable_strategy","plan","trading","disk_raw_storage","raw_redistribution","mirror","deployment","other_cutoff"],"version":"ordinary-margin-cutoffs-1005-1006-v1"}'
# qa2 canonical policy: the user-granted replacement quota (issuecomment-6110713412), bound to the namespace
# approved in issuecomment-6110894588. A policy fixture, not a financial expected-value projection.
POLICY = b'{"canonicalCalendarSource":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md#31.2","caps":{"batchCooperativeSeconds":180,"bodyBytes":1048576,"maxRequests":8,"redirects":0,"requestSeconds":20,"retainedRootsEstimateBytes":33554432,"retries":0,"totalRawBytes":8388608},"consumer":"ordinary-margin-change-ratio-v1","financialProvider":"FinMind","firstFailure":"stop_attempted_spent_unattempted_not_spent","formula":"(B[T]-B[T-5])/abs(B[T-5])","instrument":"ordinary_stock","lifecycle":"capture_eof_hash_then_independent_oracle_then_positive_consumer_then_release_and_exit","market":"TPEx","namespace":"issue31-margin-seven-cutoffs-1005-1006-v1/qa2","officialAnchorDates":["2026-10-08","2026-10-09"],"officialAnchorUrl":"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=data","query":{"dataset":"TaiwanStockMarginPurchaseShortSale","end_date":"2026-10-09","start_date":"2026-09-24"},"queryKeyOrder":["dataset","data_id","start_date","end_date"],"ratioRepresentation":{"exactThresholdComparison":"20*numerator<=positiveDenominator","numerator":"B[T]-B[T-5]","positiveDenominator":"abs(B[T-5])","roundedDisplayNotUsedForGate":true,"zeroDenominator":"reject"},"requiredWindows":{"2026-10-05":["2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]},"schema":"ordinary-margin-source-policy/v1","sourceDataset":"TaiwanStockMarginPurchaseShortSale","supportedUse":["local_personal_noncommercial","process_ram_snapshot","margin5_balance_change_ratio","same_date_anchor_trace"],"symbols":["3105","3293","5274","5347","6488","6510","8069"],"threshold":"0.05","transport":{"acceptEncoding":"identity","cookies":false,"proxies":false,"tokens":false},"unitInference":{"canonical":"lots","historicalExtension":"explicit_limited_snapshot_inference","kind":"conditional_combination_inference","numericScale":1,"providerLiteral":false,"requireAllSevenSameDateBothAnchorsExact":true,"requireEachSymbolAtLeastOneNonzeroAnchor":true},"unsupportedUse":["historical_pit","publication_time","first_availability","revision_history","historical_eligibility","historical_membership","actionable_strategy","plan","trading","disk_raw_storage","raw_redistribution","mirror","deployment","other_cutoff"],"version":"ordinary-margin-cutoffs-1005-1006-v1"}'

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


def fixture(anchor_day="2026-10-09"):
    documents = []
    rows = []
    for index, symbol in enumerate(S):
        # Nonmonotonic values and a legal interior zero expose sums/5-value
        # implementations; repeating ratios test exact Fraction comparisons.
        balances = (100 + index, 120 + index, 0, 73, 87, 105 + index, 90 + index)
        data = []
        for day, balance in zip(D + ("2026-10-08", "2026-10-09"), balances + (0, 13 + index)):
            row = {name: 0 for name in M.FINMIND_FIELDS[2:]}
            row.update(date=day, stock_id=symbol, MarginPurchaseTodayBalance=balance,
                       MarginPurchaseYesterdayBalance=0 if day == "2026-10-09" else 13 + index)
            data.append(row)
        documents.append({"msg": "success", "status": 200, "data": data})
        row = [anchor_day, symbol, "Synthetic " + symbol] + ["0"] * 17 + [""]
        row[3], row[7] = ("0", str(13 + index)) if anchor_day.endswith("09") else (str(13 + index), "0")
        row[9] = "0.00"
        row[17] = "0.00%"
        rows.append(row)
    return rows, documents


def csv_body(rows, header=None):
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows([list(M.OFFICIAL_FIELDS) if header is None else header] + rows)
    result = output.getvalue().encode("utf-8")
    output.close()
    return result


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
    wire = b"HTTP/1.1 200 OK\r\nContent-Type: text/csv\r\n" + header + b"\r\n" + wire_body
    sock = FakeSocket()

    class WireFile(io.BytesIO):
        raw = SimpleNamespace(_sock=sock)

    sock.makefile = lambda _mode: WireFile(wire)
    response = M.http.client.HTTPResponse(sock)
    response.begin()
    return response


def independent_official_oracle(capture):
    views = capture.originals()
    assert len(views) == 1
    body = views[0].body("official_oracle.raw")
    text = bytes(body).decode("utf-8-sig")
    capture.roots.hold("official_oracle.text", text)
    rows = list(csv.reader(io.StringIO(text)))
    capture.roots.hold("official_oracle.document", rows)
    # Engineering fixture oracle; the actual QA must independently audit the
    # full strict schema/date/identity/numeric grammar from original AC.
    expected_fields = ("資料日期", "代號", "名稱", "前資餘額", "資買", "資賣", "現償", "資餘額", "資屬證金",
        "資使用率", "資限額", "前券餘額", "券賣", "券買", "券償", "券餘額", "券屬證金", "券使用率", "券限額", "資券相抵", "備註")
    assert tuple(rows[0]) == expected_fields
    by_code = {}
    for ordinal, row in enumerate(rows[1:], 2):
        literal = row[0]
        if literal in ("2026-10-08", "2026/10/08", "20261008", "115/10/08", "1151008"):
            day = "2026-10-08"
        else:
            assert literal == "2026-10-09"
            day = literal
        assert row[1] not in by_code
        by_code[row[1]] = (day, int(row[3].replace(",", "")), int(row[7].replace(",", "")), ordinal)
    anchors = tuple((symbol, *by_code[symbol]) for symbol in S)
    return M.OfficialOracleApproval(QA, hashlib.sha256(body).hexdigest(), expected_fields, anchors)


def independent_oracle(capture):
    # This independent synthetic oracle reads every fresh transport body. It
    # does not access product _balances/_anchors/parsed/getter projections.
    views = capture.originals()
    documents, hashes = [], []
    for index, view in enumerate(views):
        body = view.body("oracle.raw_view." + str(index))
        hashes.append(hashlib.sha256(body).hexdigest())
        text = bytes(body).decode("utf-8-sig")
        capture.roots.hold("oracle.text." + str(index), text)
        doc = list(csv.reader(io.StringIO(text))) if index == 0 else json.loads(text)
        capture.roots.hold("oracle.document." + str(index), doc)
        documents.append(doc)
    by_symbol = {}
    for symbol, document in zip(S, documents[1:]):
        by_symbol[symbol] = {row["date"]: row["MarginPurchaseTodayBalance"] for row in document["data"]}
    capture.roots.hold("oracle.numeric", by_symbol)
    balances = tuple((symbol, day, by_symbol[symbol][day]) for symbol in S for day in D)
    ratios = tuple((symbol, cutoff, by_symbol[symbol][days[-1]] - by_symbol[symbol][days[0]],
                    abs(by_symbol[symbol][days[0]])) for symbol in S for cutoff, days in W)
    raw_anchors = {row[1]: (row[0], int(row[3].replace(",", "")), int(row[7].replace(",", "")))
                   for row in documents[0][1:]}
    anchors = tuple((symbol, *raw_anchors[symbol]) for symbol in S)
    return M.OracleApproval(QA, tuple(hashes), balances, ratios, anchors)


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
            assert provenance["official_source_date"] in ("2026-10-08", "2026-10-09")
            assert provenance["receipt"].full_eof and provenance["official_receipt"].full_eof
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

    def execute(self, rows=None, documents=None, *, oracle=independent_oracle, consumer=positive_consumer,
                official_oracle=independent_official_oracle, responses=None):
        default_rows, default_documents = fixture()
        rows = default_rows if rows is None else rows
        documents = default_documents if documents is None else documents
        responses = responses or [Response(csv_body(rows), media="text/csv")] + [Response(json_body(d)) for d in documents]
        transport = Transport(responses)
        original_class = http.client.HTTPSConnection
        capture = self.capture(connection_factory=transport.connection)
        report = capture.run(oracle, consumer, independent_official_oracle=official_oracle)
        self.assertIs(http.client.HTTPSConnection, original_class)  # The seam never replaces the stdlib global.
        self.assertEqual(report.transport, "caller_factory")
        self.assertEqual([r.request_started for r in report.receipts], [True] * len(report.receipts))
        self.assertTrue(all(r.closed for r in responses[:len(transport.calls)]))
        self.assertTrue(all(c.closed for c in transport.connections))
        self.assertEqual(capture._originals, [])
        self.assertEqual(capture._balances, {})
        self.assertEqual(capture.roots.values, {})
        self.assertEqual(report.artifact_bytes, 0)
        self.assertTrue(report.requires_process_exit)
        return capture, report, transport

    def rejected(self, rows=None, documents=None, error=None, attempted=None, **kwargs):
        capture, report, transport = self.execute(rows, documents, **kwargs)
        self.assertFalse(report.success)
        if error:
            self.assertEqual(report.primary_error, error)
        if attempted is not None:
            self.assertEqual(len(report.attempted_spent), attempted)
            self.assertEqual(len(report.unattempted_not_spent), 8 - attempted)
        self.assertEqual(report.consumer_count, 0)
        for symbol in S:
            for cutoff, _days in W:
                with self.assertRaisesRegex(M.MarginSourceError, "read_unavailable"):
                    capture.getter(symbol, cutoff)
        return report, transport

    def test_external_policy_exact_pin_and_positive_two_cutoffs(self):
        self.assertEqual(len(POLICY), 2399)
        self.assertEqual(hashlib.sha256(POLICY).hexdigest(), "b95e8d9f6b7b2cff8b9984bc54ace823c5d8b36c322d5311136cebafeae0fed9")
        capture, report, transport = self.execute()
        self.assertTrue(report.success, report)
        self.assertEqual(report.state, "released")
        self.assertEqual(report.consumer_count, 14)
        self.assertEqual(report.getter_count, 28)
        self.assertEqual(tuple(c[0] for c in transport.calls), M.URLS)
        self.assertTrue(all(c[1:] == ("GET", REQUEST_HEADERS) for c in transport.calls))
        self.assertTrue(all(r.body_sha256 and r.full_eof for r in report.receipts))
        self.assertEqual(report.unattempted_not_spent, ())
        self.assertLess(report.retained_estimate_high_water, 33_554_432)
        self.assertIn("oracle.numeric", report.cleared_roots)
        with self.assertRaisesRegex(M.MarginSourceError, "capture_once"):
            capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)

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

    def test_both_supported_anchor_dates_and_declared_source_date_grammars(self):
        for source_date in ("2026-10-08", "2026/10/08", "20261008", "115/10/08", "1151008"):
            rows, documents = fixture("2026-10-08")
            for row in rows:
                row[0] = source_date
            responses = [Response(csv_body(rows), media="text/csv")] + [Response(json_body(d)) for d in documents]
            # Test oracle normalizes its own date, independently of product.
            def oracle(capture):
                approval = independent_oracle(capture)
                return replace(approval, anchors=tuple((s, "2026-10-08", p, c) for s, _d, p, c in approval.anchors))
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                _capture, report, _transport = self.execute(responses=responses, oracle=oracle)
                self.assertTrue(report.success, report)

    def test_official_unknown_header_and_preamble_stop_before_finmind(self):
        rows, _documents = fixture()
        for body in [csv_body(rows, header=list(reversed(M.OFFICIAL_FIELDS))), b"title\n" + csv_body(rows),
                     csv_body(rows).replace("資料日期".encode(), "日期".encode(), 1), csv_body(rows) + b"\n"]:
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(responses=[Response(body, media="text/csv")], attempted=1)
                self.assertEqual(report.failure_stage, "official_parse")

    def test_official_source_date_must_be_explicit_same_day_and_fixed(self):
        for value in ("", "2026-10-10", "2026-10-06", "115/10/9", "2026-02-30", "2026-10-09T00:00:00Z"):
            rows, documents = fixture()
            rows[0][0] = value
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(rows, documents, attempted=1)
        rows, documents = fixture()
        rows[0][0] = "2026-10-08"
        self.rejected(rows, documents, error="official_source_date", attempted=1)

    def test_official_missing_duplicate_and_zero_scale(self):
        rows, documents = fixture()
        for changed, error in [(rows[:-1], "official_selected_missing"), (rows + [rows[0][:]], "official_identity")]:
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(changed, documents, error=error, attempted=1)
        rows[0][7] = "0"
        self.rejected(rows, documents, error="ambiguous_zero_scale", attempted=1)

    def test_full_official_rows_are_checked_before_selected(self):
        rows, documents = fixture()
        bad = rows[0][:]
        bad[1], bad[2], bad[12] = "9999", "Not selected", "-1"
        self.rejected(rows + [bad], documents, error="integer_grammar", attempted=1)

    def test_official_numeric_and_shape_boundaries(self):
        for column, value in [(3, "1.0"), (4, "-1"), (8, str(2 ** 63)), (10, "1,00"), (11, "True"),
                              (9, "NaN"), (17, "101.00"), (2, ""), (20, "text\ntext")]:
            rows, documents = fixture()
            rows[0][column] = value
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(rows, documents, attempted=1)

    def test_finmind_all_rows_and_integer_types(self):
        for value in (-1, True, 1.0, "1", None, 2 ** 63):
            rows, documents = fixture()
            # Post-cutoff row still requires numeric validation.
            documents[2]["data"][-1]["ShortSaleLimit"] = value
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(rows, documents, error="integer_int64", attempted=4)

    def test_finmind_missing_bad_dates_identity_duplicates_schema(self):
        cases = (
            (lambda d: d["data"].pop(1), "required_day_missing"),
            (lambda d: d["data"].append(dict(d["data"][0])), "finmind_identity"),
            (lambda d: d["data"][0].update(date="2026-09-23"), "finmind_date_range"),
            (lambda d: d["data"][-1].update(date="2026-10-10"), "finmind_date_range"),
            (lambda d: d["data"][-1].update(date="2026-02-30"), "date_invalid"),
            (lambda d: d["data"][-1].update(stock_id="9999"), "finmind_identity"),
            (lambda d: d["data"][-1].update(extra=0), "finmind_schema"),
            (lambda d: d.update(status=True), "finmind_status"),
            (lambda d: d.update(msg="requires paid plan"), "finmind_status"),
        )
        for mutate, error in cases:
            rows, documents = fixture()
            mutate(documents[0])
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(rows, documents, error=error, attempted=2)

    def test_anchor_both_exact_no_scaling_or_partial_available(self):
        for field in ("MarginPurchaseTodayBalance", "MarginPurchaseYesterdayBalance"):
            rows, documents = fixture()
            documents[6]["data"][-1][field] += 1
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(rows, documents, error="anchor_exact_mismatch", attempted=8)
        rows, documents = fixture()
        for row in documents[0]["data"]:
            for field in M.FINMIND_FIELDS[2:]:
                row[field] *= 1000
        self.rejected(rows, documents, error="anchor_exact_mismatch", attempted=2)

    def test_one_zero_baseline_invalidates_all_two_cutoffs(self):
        for baseline in (0, 1):
            rows, documents = fixture()
            documents[-1]["data"][baseline]["MarginPurchaseTodayBalance"] = 0
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(rows, documents, error="zero_denominator", attempted=8)

    def test_json_duplicate_keys_nan_utf8_and_non_json(self):
        rows, documents = fixture()
        base = json_body(documents[0])
        bad_bodies = [base.replace(b'"status":200', b'"status":200,"status":200'),
                      base.replace(b'"ShortSaleLimit":0', b'"ShortSaleLimit":NaN', 1), b"<html>login</html>",
                      base + b"\xff", base[:-1]]
        for body in bad_bodies:
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(responses=[Response(csv_body(rows), media="text/csv"), Response(body)], attempted=2)

    def test_oracle_gate_checks_all_hashes_values_ratios_anchors_and_types(self):
        def bad_oracle(kind):
            def oracle(capture):
                approval = independent_oracle(capture)
                if kind == "holder":
                    return replace(approval, holder_actual="engineer")
                if kind == "hash":
                    return replace(approval, body_sha256=("0" * 64,) + approval.body_sha256[1:])
                if kind == "balances":
                    return replace(approval, balances=approval.balances[:-1])
                if kind == "bool":
                    rows = list(approval.balances)
                    rows[2] = (*rows[2][:2], False)
                    return replace(approval, balances=tuple(rows))
                if kind == "ratios":
                    return replace(approval, ratios=approval.ratios[:-1])
                return replace(approval, anchors=approval.anchors[:-1])
            return oracle
        for kind in ("holder", "hash", "balances", "bool", "ratios", "anchors"):
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(oracle=bad_oracle(kind), attempted=8)
                self.assertTrue(report.primary_error.startswith("oracle_"))

    def test_post_cutoff_valid_rows_are_not_calendar_or_ratio(self):
        rows, documents = fixture()
        for d in documents:
            row = dict(d["data"][0])
            row["date"] = "2026-10-07"
            row["MarginPurchaseTodayBalance"] = 2 ** 63 - 1
            d["data"].append(row)
        _capture, report, _transport = self.execute(rows, documents)
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
        rows, _documents = fixture()
        for response in [Response(b"x", status=401), Response(b"x", status=403), Response(b"x", status=302),
            Response(b"x", media="text/html"), Response(b"x", headers=[("Content-Type", "text/csv"), ("Content-Encoding", "gzip")]),
            Response(b"x", headers=[("Content-Type", "text/csv"), ("Content-Length", "1"), ("Content-Length", "1")]),
            Response(csv_body(rows), headers=[("Content-Type", "text/csv"), ("Location", "/new")]),
            Response(b"x", headers=[("Content-Type", "text/csv"), ("Content-Length", "1"), ("Transfer-Encoding", "chunked")])]:
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(responses=[response], attempted=1)
                self.assertFalse(report.receipts[0].full_eof)
                self.assertIsNone(report.receipts[0].body_sha256)

    def test_untrusted_content_type_does_not_enter_receipts_or_diagnostics(self):
        for media in ("text/csv; raw=private marker", "text/csv; charset=big5", "private marker" * 10000):
            response = Response(b"x", media=media)
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(responses=[response], error="http_content_type", attempted=1)
                self.assertEqual(report.receipts[0].content_type, "")
                self.assertNotIn("private marker", repr(report))

    def test_cap_read_before_no_plus_one_unknown_exact_cap(self):
        for chunked in (False, True):
            response = Response(b"x" * 1_048_576, media="text/csv", length=None, chunked=chunked)
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(responses=[response], error="bounded_prefix_no_eof", attempted=1)
                self.assertEqual(sum(response.requests), 1_048_576)
                self.assertEqual(report.receipts[0].body_bytes, 1_048_576)
                self.assertIsNone(report.receipts[0].body_sha256)

    def test_exact_content_length_cap_eof_hash_before_parse(self):
        response = Response(b"x" * 1_048_576, media="text/csv")
        report, _transport = self.rejected(responses=[response], attempted=1)
        self.assertTrue(report.receipts[0].full_eof)
        self.assertEqual(report.receipts[0].body_sha256, hashlib.sha256(response.body).hexdigest())
        self.assertEqual(sum(response.requests), 1_048_576)
        self.assertEqual(report.failure_stage, "official_parse")

    def test_oversize_declared_body_rejected_before_read(self):
        response = Response(b"x", media="text/csv", length="1048577")
        self.rejected(responses=[response], error="raw_cap", attempted=1)
        self.assertEqual(response.requests, [])

    def test_unknown_under_cap_and_truncated_framing(self):
        rows, documents = fixture()
        responses = [Response(csv_body(rows), media="text/csv", length=None)] + [Response(json_body(d), length=None) for d in documents]
        _capture, report, _transport = self.execute(responses=responses)
        self.assertTrue(report.success, report)
        with patch.object(M, "_SPENT_NAMESPACES", set()):
            self.rejected(responses=[Response(b"x", media="text/csv", length="2")], error="truncated_body", attempted=1)

    def test_aggregate_remaining_limits_read_without_extra_probe(self):
        # Exercise the real reader with pre-existing cumulative RAM bytes.
        capture = self.capture()
        capture._deadline = M.time.monotonic() + 180
        capture._raw_total = 8_388_608 - 7
        response = Response(b"abcdefgh", media="text/csv", length=None)
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
        self.rejected(oracle=oracle, error="retained_roots_cap", attempted=8)

    def test_expiry_never_resets_or_extends_on_read(self):
        def oracle(capture):
            result = independent_oracle(capture)
            capture._deadline = M.time.monotonic() - 1
            return result
        self.rejected(oracle=oracle, error="expired", attempted=8)
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
        transport = Transport([Response(b"a", media="text/csv")])
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

        report, _transport = self.rejected(oracle=oracle, error="unexpected_exception", attempted=8)
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
        report = capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
        self.assertEqual(report.primary_error, "http_status")
        self.assertIn("response_close_failed", report.secondary_diagnostics)
        self.assertNotIn("must not expose raw", repr(report))
        self.assertTrue(transport.connections[0].closed)

    def test_new_transport_cleanup_failure_stops_after_one_attempt(self):
        rows, _documents = fixture()
        response = Response(csv_body(rows), media="text/csv")
        def close():
            raise RuntimeError("private close diagnostic")
        response.close = close
        transport = Transport([response])
        capture = self.capture(connection_factory=transport.connection)
        report = capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
        self.assertFalse(report.success)
        self.assertEqual(report.primary_error, "transport_cleanup_failed")
        self.assertEqual(report.attempted_spent, (M.OFFICIAL_URL,))
        self.assertEqual(report.unattempted_not_spent, M.FINMIND_URLS)
        self.assertTrue(report.receipts[0].full_eof)
        self.assertIn("response_close_failed", report.secondary_diagnostics)
        self.assertNotIn("private close diagnostic", repr(report))

    def test_pending_failure_no_positive_callback_or_replay(self):
        called = []
        def consumer(_capture):
            called.append(True)
        report, _transport = self.rejected(oracle=lambda c: None, consumer=consumer, attempted=8)
        self.assertEqual(called, [])
        capture = self.capture()
        with self.assertRaisesRegex(M.MarginSourceError, "namespace_already_spent"):
            capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)

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
                capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
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
        self.rejected(oracle=oracle, error="oracle_hashes", attempted=8)

    def test_unicode_digits_are_not_the_declared_ascii_date_grammar(self):
        for day in ("２０２６-１０-０９", "٢٠٢٦-١٠-٠٩", "１１５１００９"):
            rows, documents = fixture()
            rows[0][0] = day
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                self.rejected(rows, documents, error="date_grammar", attempted=1)
        rows, documents = fixture()
        documents[0]["data"][0]["date"] = "２０２６-０９-２４"
        self.rejected(rows, documents, error="date_grammar", attempted=2)

    def test_receipt_declared_schema_is_not_failed_actual_validation(self):
        rows, documents = fixture()
        documents[-1]["data"][-1]["ShortSaleLimit"] = True
        report, _transport = self.rejected(rows, documents, error="integer_int64", attempted=8)
        self.assertTrue(all(r.schema_validated for r in report.receipts[:-1]))
        self.assertFalse(report.receipts[-1].schema_validated)
        self.assertEqual(report.receipts[-1].declared_schema, M.FINMIND_FIELDS)

    def test_native_httpresponse_ram_framing_and_detached_close_socket(self):
        rows, _documents = fixture()
        for framing in ("length", "unknown", "chunked"):
            response = native_response(csv_body(rows), framing=framing, connection_close=True)
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
            self.assertEqual(original.receipt.body_sha256, hashlib.sha256(csv_body(rows)).hexdigest())
            self.assertTrue(response.isclosed())
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
        rows, _documents = fixture()
        response = Response(csv_body(rows), media="text/csv")
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
        rows, _documents = fixture()
        for overrun_phase in ("headers", "read"):
            response = Response(csv_body(rows), media="text/csv")
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
            def body(count):
                data = read(count)
                if overrun_phase == "read":
                    now[0] += 21
                return data
            response.read = body
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
        self.assertIsNone(saved[0].anchors)
        self.assertIsNone(saved[0].body_sha256)

    def test_official_independent_oracle_failure_spends_only_official(self):
        for change, code in [(dict(holder_actual="wrong"), "official_oracle_holder"),
                             (dict(body_sha256="0" * 64), "official_oracle_hash"),
                             (dict(fields=("wrong",)), "official_oracle_fields"),
                             (dict(anchors=()), "official_oracle_anchors")]:
            def oracle(capture):
                return replace(independent_official_oracle(capture), **change)
            with patch.object(M, "_SPENT_NAMESPACES", set()):
                report, _transport = self.rejected(official_oracle=oracle, error=code, attempted=1)
                self.assertEqual(report.failure_stage, "independent_official_oracle")
                self.assertEqual(report.unattempted_not_spent, M.FINMIND_URLS)

    def test_official_oracle_pending_reads_and_saved_alias_cleanup(self):
        saved = []
        def oracle(capture):
            self.assertEqual(len(capture.originals()), 1)
            for symbol in S:
                for cutoff, _days in W:
                    with self.assertRaisesRegex(M.MarginSourceError, "read_unavailable"):
                        capture.consume(symbol, cutoff)
            approval = independent_official_oracle(capture)
            saved.extend([capture.originals()[0], approval])
            capture.roots.hold("official_oracle.approval_alias", approval)
            return approval
        _capture, report, _transport = self.execute(official_oracle=oracle)
        self.assertTrue(report.success, report)
        with self.assertRaisesRegex(M.MarginSourceError, "read_unavailable"):
            saved[0].body("released")
        self.assertIsNone(saved[1].anchors)
        self.assertIsNone(saved[1].fields)
        self.assertIsNone(saved[1].body_sha256)

    def test_above_threshold_stays_exact_with_large_int64_values(self):
        rows, documents = fixture()
        documents[0]["data"][5]["MarginPurchaseTodayBalance"] = 106
        documents[1]["data"][0]["MarginPurchaseTodayBalance"] = (1 << 63) - 10
        documents[1]["data"][5]["MarginPurchaseTodayBalance"] = (1 << 63) - 1
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
        _capture, report, _transport = self.execute(rows, documents, consumer=consumer)
        self.assertTrue(report.success, report)

    # Identity guard: every actor, model and effort comes from the seal.

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
                capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
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
                independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)

    def test_qa2_policy_differs_from_published_qa1_policy_only_by_namespace(self):
        def canonical(document):
            return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

        old, new = json.loads(OLD_POLICY), json.loads(POLICY)
        qa1, qa2 = "issue31-margin-seven-cutoffs-1005-1006-v1/qa1", "issue31-margin-seven-cutoffs-1005-1006-v1/qa2"
        self.assertEqual(set(old), set(new))
        self.assertEqual([key for key in old if old[key] != new[key]], ["namespace"])
        self.assertEqual((old["namespace"], new["namespace"]), (qa1, qa2))
        self.assertEqual(M.NAMESPACE, qa2)
        # Byte level: the qa1 text with its namespace suffix swapped is exactly the qa2 text.
        self.assertEqual(OLD_POLICY.count(b"/qa1"), 1)
        self.assertEqual(OLD_POLICY.replace(b"/qa1", b"/qa2"), POLICY)
        # Both are canonical (sorted keys, compact), same length; the new SHA matches the canonical bytes.
        self.assertEqual((canonical(old), canonical(new)), (OLD_POLICY, POLICY))
        self.assertEqual((len(OLD_POLICY), len(POLICY)), (2399, 2399))
        retired_pin = "47ea789e4bac27cf736f9294f5c0563425b15cd5541748567f985ae262f224d7"
        self.assertEqual(hashlib.sha256(OLD_POLICY).hexdigest(), retired_pin)
        self.assertEqual(hashlib.sha256(POLICY).hexdigest(), M.POLICY_SHA256)
        self.assertNotEqual(M.POLICY_SHA256, retired_pin)
        # qa1 stays SPENT / NO-RETRY: neither its policy text nor its namespace is accepted any more.
        with self.assertRaisesRegex(M.MarginSourceError, "^external_policy_pin$"):
            self.capture(external_policy_utf8=OLD_POLICY)
        with self.assertRaisesRegex(M.MarginSourceError, "^seal_authority$"):
            self.capture(seal_changes=dict(namespace=qa1))
        with self.assertRaisesRegex(M.MarginSourceError, "^seal_authority$"):
            self.capture(seal_changes=dict(policy_sha256=retired_pin))

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
        connection = M.native_connection("www.tpex.org.tw", 20)
        try:
            self.assertIs(type(connection), http.client.HTTPSConnection)
            self.assertEqual((connection.host, connection.port, connection.timeout), ("www.tpex.org.tw", 443, 20))
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
                    capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
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
                    capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
                self.assertEqual(capture._attempted, [])
            self.assertEqual(unused.connections, [])
            self.assertEqual(M._SPENT_NAMESPACES, set())

    def test_default_transport_goes_through_native_connection(self):
        rows, documents = fixture()
        transport = Transport([Response(csv_body(rows), media="text/csv")] + [Response(json_body(d)) for d in documents])
        capture = self.capture()
        with patch.object(M, "native_connection", transport.connection):
            report = capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
        self.assertTrue(report.success, report)
        self.assertEqual(report.transport, "native_direct")
        self.assertEqual(len(transport.connections), 8)
        self.assertIsNone(capture._connection_factory)

    def test_request_headers_are_exactly_identity_and_the_fixed_user_agent(self):
        self.assertEqual(M.REQUEST_USER_AGENT, "stock-lab-issue31-local-ram/1")
        self.assertTrue(M.REQUEST_USER_AGENT.isascii())
        _capture, report, transport = self.execute()
        self.assertTrue(report.success, report)
        self.assertEqual(len(transport.calls), 8)
        for _url, method, headers in transport.calls:  # What the product passes, for each of the 8 requests.
            self.assertEqual(method, "GET")
            self.assertEqual(headers, REQUEST_HEADERS)
            self.assertEqual(sorted(key.lower() for key in headers), ["accept-encoding", "user-agent"])

    def test_wire_request_headers_through_the_real_stdlib_class_are_exact(self):
        rows, _documents = fixture()
        response = Response(csv_body(rows), media="text/csv")
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
        self.assertEqual(lines[0], "GET /web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=data HTTP/1.1")
        self.assertEqual(sorted(line.split(": ", 1) for line in lines[1:]), sorted([
            ["Host", "www.tpex.org.tw"], ["Accept-Encoding", "identity"], ["User-Agent", "stock-lab-issue31-local-ram/1"]]))
        capture.release()

    def test_audit_wrapper_composes_native_connection_without_replacing_the_global(self):
        rows, documents = fixture()
        transport = Transport([Response(csv_body(rows), media="text/csv")] + [Response(json_body(d)) for d in documents])
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
        report = capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
        self.assertTrue(report.success, report)
        self.assertEqual(report.transport, "caller_factory")
        self.assertIs(http.client.HTTPSConnection, original_class)
        self.assertEqual(len(audit), 8)
        for item in audit:
            self.assertIs(type(item.native), original_class)
            self.assertIsNone(item.native.sock)  # Nothing was sent through the real class.
        self.assertIsNone(capture._connection_factory)

    def test_constructor_failure_is_spent_but_never_reports_a_started_request(self):
        def factory(host, timeout):
            raise RuntimeError("private constructor diagnostic")

        capture = self.capture(connection_factory=factory)
        report = capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
        self.assertFalse(report.success)
        self.assertEqual(report.failure_stage, "official_capture")
        self.assertEqual(report.primary_error, "unexpected_exception")
        self.assertEqual(report.attempted_spent, (M.OFFICIAL_URL,))
        self.assertEqual(report.unattempted_not_spent, M.FINMIND_URLS)
        self.assertEqual(len(report.receipts), 1)
        self.assertFalse(report.receipts[0].request_started)
        self.assertEqual((report.receipts[0].body_bytes, report.receipts[0].body_sha256, report.receipts[0].status),
                         (0, None, None))
        self.assertTrue(any(event[:2] == ("official_capture", "_fetch") for event in report.trace_events))
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
        report = capture.run(independent_oracle, positive_consumer, independent_official_oracle=independent_official_oracle)
        self.assertFalse(report.success)
        self.assertEqual(report.attempted_spent, (M.OFFICIAL_URL,))
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
