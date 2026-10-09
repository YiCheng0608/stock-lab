"""Standalone RAM boundary selftests; no pytest/conftest, provider GET, or disk IO.

Run with Python -B -X utf8 this-file. The only control-plane GET reads the pinned
Issue33 canonical policy. All price documents below are synthetic and prove no
real source, unit, calendar or independent QA acceptance criterion.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "taiex_price_index_source.py"
SPEC = importlib.util.spec_from_file_location("issue33_boundary_product", MODULE_PATH)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
POLICY_RAW = None


class Clock:
    def __init__(self):
        self.elapsed = 0.0
        self.now = datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)

    def monotonic(self):
        return self.elapsed

    def utc(self):
        return self.now + timedelta(seconds=self.elapsed)


class Response:
    def __init__(self, body, *, declared=True, cap_eof=True, status=200, headers=None, oversize=False, clock=None, slow=False, read_seconds=0):
        self.body, self.position, self.closed = body, 0, False
        self.declared, self.cap_eof, self.oversize = declared, cap_eof, oversize
        self.status = status
        self.headers = headers if headers is not None else ([("Content-Length", str(len(body)))] if declared else [])
        self.read_sizes, self.clock, self.slow = [], clock, slow
        self.read_seconds = read_seconds

    @property
    def framing_eof(self):
        return self.position == len(self.body) and self.cap_eof

    def read(self, count, timeout):
        assert 0 < count <= 65536 and 0 < timeout <= 20
        self.read_sizes.append(count)
        if self.slow:
            self.clock.elapsed += 21
        self.clock.elapsed += self.read_seconds
        result = self.body[self.position:self.position + count + int(self.oversize)]
        self.position += len(result)
        return result

    def close(self):
        self.closed = True
        self.body = b""


class Transport:
    def __init__(self, owner, bodies, options, clock):
        self.bodies = owner.track("fake_transport_bodies", list(bodies))
        self.options, self.clock, self.opened, self.responses = options, clock, [], []

    def open(self, url, timeout):
        ordinal = len(self.opened)
        self.opened.append(url)
        response = Response(self.bodies[ordinal], clock=self.clock, **self.options.get(ordinal, {}))
        self.responses.append(response)
        return response


def policy():
    return M.ExternalPolicy.from_external(POLICY_RAW, M.POLICY_SHA256, M.POLICY_PIN)


def seal_for(p, clock, mutate=None):
    command = ["python", "-B", "-X", "utf8", "synthetic-boundary-only"]
    binding = {"candidate_sha": "d8918bc6491ec8ef65874979cf88d1322df2da43",
               "module_sha256": hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest(),
               "script_sha256": "2" * 64, "loader_sha256": "3" * 64,
               "command_sha256": hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest(),
               "command": command,
               "qa_thread": "11111111-1111-1111-1111-111111111111",
               "qa_session": "11111111-1111-1111-1111-111111111111",
               "owner_thread": "22222222-2222-2222-2222-222222222222"}
    document = {"schema": "issue33-financial-start-seal/v1", "issue": "YiCheng0608/stock-lab#33",
                "namespace": M.NAMESPACE, "policy_sha256": p.sha256, "policy_pin": p.pin,
                **binding, "parent_thread": None,
                "authorized_by": "33333333-3333-3333-3333-333333333333",
                "financial_start": True, "issued_at_utc": "2026-10-10T00:59:00Z",
                "expires_at_utc": "2026-10-10T01:05:00Z", "consumer": M.CONSUMER,
                "supported_use": M.SUPPORTED_USE, "urls": p.document["urls"],
                "cutoffs": p.document["cutoffs"], "caps": p.document["caps"]}
    if mutate:
        mutate(document)
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    return M.FinancialStartSeal.from_external(raw, hashlib.sha256(raw).hexdigest(),
                                            "https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-0", p, binding), binding


def documents(p):
    # Explicit synthetic sequence, never a provider sample or fixture acceptance.
    dates = p.document["observed_dates"]
    rows = [{"date": day, "stock_id": "TAIEX", "Trading_Volume": 0, "Trading_money": 0,
             "open": 20000 + ordinal, "max": 20001 + ordinal, "min": 19999 + ordinal,
             "close": 20000 + ordinal, "spread": 1, "Trading_turnover": 0}
            for ordinal, day in enumerate(dates)]
    header = ",".join(p.document["official_schema"]) + "\n"
    official = header + "115/10/05,20020,20021,20019,20020\n1151006,20021,20022,20020,20021\n"
    return official.encode("utf-8"), json.dumps({"status": 200, "msg": "success", "data": rows}).encode("utf-8")


def independent_hooks(owner, *, observer=None, official=None, finmind=None):
    def observe(raw, receipt):
        assert receipt["eof"] is True
        assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
        owner.track("original_alias_" + str(receipt["ordinal"]), memoryview(raw))
        if observer:
            observer(raw, receipt)

    def official_oracle(raw, receipt):
        text = owner.track("oracle_csv_text", raw.decode("utf-8-sig"))
        stream = owner.stringio("oracle_csv_native", text)
        rows = owner.track("oracle_csv_rows", [])
        try:
            parsed = csv.reader(stream, strict=True)
            assert next(parsed) == ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"]
            for fields in parsed:
                if not fields:
                    continue
                assert len(fields) == 5
                match = re.fullmatch(r"([0-9]{3})/?([0-9]{2})/?([0-9]{2})", fields[0])
                assert match is not None
                day = f"{int(match[1]) + 1911:04d}-{match[2]}-{match[3]}"
                values = [Decimal(value.replace(",", "")) for value in fields[1:]]
                rows.append(dict(zip(("date", "open", "high", "low", "close"), [day, *values])))
        finally:
            stream.close()
        return official(raw, receipt, rows) if official else rows

    def finmind_oracle(raw, receipt):
        text = owner.track("oracle_json_text", raw.decode("utf-8"))
        document = owner.track("oracle_json_document", json.loads(text, parse_float=Decimal))
        rows = owner.track("oracle_json_rows", [])
        for original in document["data"]:
            row = dict(original)
            for field in ("open", "max", "min", "close", "spread"):
                row[field] = Decimal(row[field])
            rows.append(row)
        return finmind(raw, receipt, rows) if finmind else rows

    return M.OracleHooks(observe, official_oracle, finmind_oracle, owner)


class Boundaries(unittest.TestCase):
    def build(self, *, body_transform=None, options=None, hooks_options=None, use=M.SUPPORTED_USE, seal_mutate=None, clock=None, ledger=None):
        p, clock = policy(), clock or Clock()
        seal, binding = seal_for(p, clock, seal_mutate)
        owner = M.RootOwner("qa_boundary")
        bodies = documents(p)
        if body_transform:
            bodies = body_transform(*bodies)
        transport = Transport(owner, bodies, options or {}, clock)
        hooks = independent_hooks(owner, **(hooks_options or {}))
        source = M.TaiexNominalSource(p, seal, hooks, binding=binding, supported_use=use,
                                    boundary_only=True, transport=transport,
                                    ledger=ledger or M.AttemptLedger(), monotonic=clock.monotonic, utc_now=clock.utc)
        return source, owner, transport, clock

    def expect_failure(self, source, code, attempted):
        error = None
        try:
            source.acquire()
        except M.TaiexSourceError as actual:
            error = actual
            self.assertEqual(actual.code, code)
            M.clear_error_graph(actual)
        self.assertIsNotNone(error)
        report = source.diagnostic_report()
        self.assertEqual(len(report["attempted_urls"]), attempted)
        self.assertTrue(report["declared_roots_empty"])
        self.assertEqual(report["cleanup_failures"], [])
        self.assertEqual(report["artifact_bytes"], 0)
        self.assertIsNotNone(report["first_product_failure"])
        return report

    def test_two_windows_and_consumers_release(self):
        source, owner, transport, clock = self.build()
        handles = []
        with source:
            for cutoff, first, last in (("2026-10-05", 20000, 20020), ("2026-10-06", 20001, 20021)):
                getter = source.get_taiex_nominal21(cutoff)
                def check_series(payload):
                    self.assertEqual(len(payload["observations"]), 21)
                    self.assertEqual(payload["observations"][0]["close"], Decimal(first))
                    self.assertEqual(payload["observations"][-1]["close"], Decimal(last))
                    self.assertEqual(payload["calendar_basis"], "cross_market_candidate_inference")
                    self.assertEqual(payload["price_basis"], "nominal_index_level")
                    self.assertIs(payload["benchmark20d_ready"], False)
                    self.assertIs(payload["provenance"]["provider_literal_unit"], False)
                    self.assertEqual(payload["provenance"]["external_calendar_basis"], "cross_market_candidate_inference_not_verified_twse_sessions")
                    self.assertEqual(payload["provenance"]["external_price_basis"], "nominal_price_index_level_not_adjusted_or_total_return")
                    owner.track("series_alias_" + cutoff, payload)
                getter.visit(check_series, owner)
                summary = source.summarize(cutoff)
                def check_summary(payload):
                    ratio = Fraction(last - first, first)
                    self.assertIs(type(payload["return"]), Fraction)
                    self.assertEqual(payload["return"], ratio)
                    self.assertEqual(payload["return_numerator"], ratio.numerator)
                    self.assertGreater(payload["return_denominator"], 0)
                    self.assertEqual(payload["return_denominator"], ratio.denominator)
                    self.assertEqual(payload["interval_count"], 20)
                    self.assertEqual(payload["consumer"], M.CONSUMER)
                    owner.track("summary_alias_" + cutoff, payload)
                summary.visit(check_summary, owner)
                handles.extend((getter, summary))
            self.assertEqual(transport.opened, list(M.URLS))
            self.assertEqual(source.state, "available")
        for handle in handles:
            with self.assertRaises(M.TaiexSourceError) as caught:
                handle.visit(lambda payload: None, owner)
            self.assertEqual(caught.exception.code, "lease_released")
            M.clear_error_graph(caught.exception)
        report = source.diagnostic_report()
        self.assertTrue(report["declared_roots_empty"])
        self.assertEqual(report["cleanup_failures"], [])
        self.assertTrue(all(item.closed for item in transport.responses))
        self.assertGreater(report["declared_roots_estimate_high_water"], 0)
        self.assertLess(report["measurement_calls"], 32)
        self.assertGreater(report["measurement_seconds"], 0)
        print(json.dumps({"synthetic_positive_getters": 2, "synthetic_positive_consumers": 2,
                          "declared_roots_estimate_high_water": report["declared_roots_estimate_high_water"],
                          "measurement_calls": report["measurement_calls"], "measurement_seconds": report["measurement_seconds"],
                          "declared_roots_empty": report["declared_roots_empty"], "artifact_bytes": 0,
                          "evidence": "engineering synthetic boundary only, not real source QA"}), flush=True)

    def test_external_pin_and_typed_boolean_rejection(self):
        with self.assertRaises(M.TaiexSourceError) as caught:
            M.ExternalPolicy.from_external(POLICY_RAW.replace(b'"scale": 1', b'"scale": true'), M.POLICY_SHA256, M.POLICY_PIN)
        self.assertEqual(caught.exception.code, "external_policy_pin")
        M.clear_error_graph(caught.exception)

    def test_seal_caps_and_shared_qa_rejected(self):
        for change in (lambda item: item["caps"].update(body_bytes=1048577),
                       lambda item: item.update(qa_session="22222222-2222-2222-2222-222222222222"),
                       lambda item: item.update(financial_start=1),
                       lambda item: item.update(extra="unknown")):
            with self.assertRaises(M.TaiexSourceError) as caught:
                self.build(seal_mutate=change)
            M.clear_error_graph(caught.exception)

    def test_unsupported_preget(self):
        source, owner, transport, clock = self.build(use="hot_group_v1")
        self.expect_failure(source, "unsupported_use_preget", 0)
        self.assertEqual(transport.opened, [])

    def test_pending_and_expired(self):
        source, owner, transport, clock = self.build()
        with self.assertRaises(M.TaiexSourceError) as caught:
            source.get_taiex_nominal21("2026-10-05")
        self.assertEqual(caught.exception.code, "lease_pending")
        M.clear_error_graph(caught.exception)
        self.assertEqual(source.state, "failed")
        self.assertTrue(source.diagnostic_report()["declared_roots_empty"])
        source, owner, transport, clock = self.build()
        source.acquire()
        handle = source.summarize("2026-10-05")
        clock.elapsed = 180
        with self.assertRaises(M.TaiexSourceError) as caught:
            handle.visit(lambda payload: None, owner)
        self.assertEqual(caught.exception.code, "lease_expired")
        M.clear_error_graph(caught.exception)
        source.release()

    def assert_terminal_results(self, source, owner, handle, original_code):
        report = source.diagnostic_report()
        self.assertEqual(report["state"], "failed")
        self.assertEqual(report["first_product_failure"]["code"], original_code)
        self.assertTrue(report["declared_roots_empty"])
        for action in (lambda: source.get_taiex_nominal21("2026-10-05"),
                       lambda: source.summarize("2026-10-06"),
                       lambda: handle.visit(lambda payload: None, owner),
                       lambda: source.acquire()):
            with self.assertRaises(M.TaiexSourceError) as caught:
                action()
            self.assertEqual(caught.exception.code, "lease_failed")
            M.clear_error_graph(caught.exception)
        self.assertEqual(source.diagnostic_report()["first_product_failure"], report["first_product_failure"])
        self.assertTrue(source.diagnostic_report()["declared_roots_empty"])

    def test_caught_result_callback_failure_terminal_inside_with(self):
        source, owner, transport, clock = self.build()
        with source:
            handle = source.get_taiex_nominal21("2026-10-05")
            def rejected(payload):
                raise RuntimeError("synthetic result failure")
            with self.assertRaises(M.TaiexSourceError) as caught:
                handle.visit(rejected, owner)
            self.assertEqual(caught.exception.code, "callback_failure")
            M.clear_error_graph(caught.exception)
            self.assert_terminal_results(source, owner, handle, "callback_failure")
            self.assertEqual(source.diagnostic_report()["first_product_failure"]["phase"], "result_visit")
            self.assertEqual(source.diagnostic_report()["first_product_failure"]["location"], "TaiexNominalSource._callback")
            self.assertTrue(all(response.closed for response in transport.responses))
        self.assertEqual(source.state, "failed")

    def test_caught_result_root_failures_terminal_for_all_operations(self):
        for operation in ("getter", "summary", "visit"):
            source, owner, transport, clock = self.build()
            with source:
                handle = source.get_taiex_nominal21("2026-10-05")
                if operation == "visit":
                    def visit_bad_root(payload):
                        owner.track("opaque_result_alias", object())
                    action = lambda: handle.visit(visit_bad_root, owner)
                else:
                    owner.track("opaque_result_alias", object())
                    action = (lambda: source.get_taiex_nominal21("2026-10-06")) if operation == "getter" else (lambda: source.summarize("2026-10-06"))
                with self.assertRaises(M.TaiexSourceError) as caught:
                    action()
                self.assertEqual(caught.exception.code, "opaque_source_root")
                M.clear_error_graph(caught.exception)
                self.assert_terminal_results(source, owner, handle, "opaque_source_root")
                self.assertTrue(all(response.closed for response in transport.responses))
            self.assertEqual(source.state, "failed")

    def test_observer_preparse_first_failure_and_exception_cycles(self):
        original = ValueError("synthetic secret, must not enter diagnostic")
        original.__cause__ = original
        original.__context__ = original
        def observer(raw, receipt):
            raise original
        source, owner, transport, clock = self.build(hooks_options={"observer": observer})
        report = self.expect_failure(source, "callback_failure", 1)
        self.assertEqual(report["first_product_failure"]["phase"], "original_observer")
        self.assertFalse(any(item["code"] == "parse_begin" for item in report["events"]))
        self.assertIsNone(original.__cause__)
        self.assertIsNone(original.__context__)
        self.assertIsNone(original.__traceback__)
        self.assertEqual(original.args, ())

    def test_exception_dict_slot_unicode_and_native_payload_aliases(self):
        class SlottedError(Exception):
            __slots__ = ("payload",)
        buffer = bytearray(b"synthetic-source")
        view = memoryview(buffer)
        cycle = [view]
        cycle.append(cycle)
        native = io.StringIO("synthetic-source")
        unicode_error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "synthetic")
        error = SlottedError(unicode_error)
        error.payload = cycle
        error.extra = {"native": native, "nested_error": unicode_error}
        error.__cause__ = error
        self.assertEqual(M.clear_error_graph(error), [])
        self.assertIsNone(error.payload)
        self.assertEqual(error.__dict__, {})
        self.assertEqual(error.args, ())
        self.assertEqual(unicode_error.object, b"")
        self.assertEqual(unicode_error.args, ())
        self.assertEqual(buffer, bytearray())
        self.assertEqual(cycle, [])
        self.assertTrue(native.closed)
        with self.assertRaises(ValueError):
            len(view)

    def test_exception_attribute_guard_cannot_interrupt_cleanup(self):
        class PropertyError(Exception):
            @property
            def object(self):
                raise RuntimeError("synthetic inaccessible payload")
        error = PropertyError("synthetic")
        error.raw_alias = bytearray(b"synthetic-source")
        alias = error.raw_alias
        self.assertEqual(M.clear_error_graph(error), ["exception_attribute_read"])
        self.assertEqual(error.__dict__, {})
        self.assertEqual(alias, bytearray())

    def test_all_official_rows_not_only_anchors(self):
        source, owner, transport, clock = self.build(body_transform=lambda csv_body, json_body: (csv_body + b"115/10/07,20000,19000,18000,20000\n", json_body))
        self.expect_failure(source, "official_ohlc_range", 1)

    def test_official_missing_anchor_stops_before_finmind(self):
        source, owner, transport, clock = self.build(body_transform=lambda a, b: (a.replace(b"1151006,20021,20022,20020,20021\n", b""), b))
        self.expect_failure(source, "official_missing_anchor", 1)

    def test_official_header_width_date_and_future(self):
        variations = [
            (lambda a: a.replace("日期".encode(), b"Date"), "official_schema"),
            (lambda a: a.replace(b"1151006", b"20261006"), "official_roc_date"),
            (lambda a: a.replace(b"1151006", b"1151012"), "official_month_weekday_future"),
            (lambda a: a.replace(b"1151006,", b"1151006,1,"), "official_row_width_or_count"),
            (lambda a: a + b"1151006,20021,20022,20020,20021\n", "official_duplicate_date"),
        ]
        for change, expected in variations:
            source, owner, transport, clock = self.build(body_transform=lambda a, b: (change(a), b))
            self.expect_failure(source, expected, 1)

    def test_bom_and_grouped_numbers(self):
        source, owner, transport, clock = self.build(body_transform=lambda a, b: (b"\xef\xbb\xbf" + a.replace(b",20020", b',"20,020"').replace(b",20021", b',"20,021"').replace(b",20019", b',"20,019"').replace(b",20022", b',"20,022"'), b))
        with source:
            source.summarize("2026-10-06").visit(lambda payload: self.assertEqual(payload["return"], Fraction(20, 20001)), owner)

    def test_independent_full_official_oracle_gate(self):
        source, owner, transport, clock = self.build(hooks_options={"official": lambda raw, receipt, rows: rows[:1]})
        self.expect_failure(source, "official_full_oracle_mismatch", 1)

    def test_full_finmind_schema_duplicates_bool_and_exponent(self):
        variations = [
            (lambda b: b.replace(b'"stock_id": "TAIEX"', b'"stock_id": "^TWII"', 1), "finmind_stock_id"),
            (lambda b: b.replace(b'"spread": 1', b'"spread": 1, "extra": 0', 1), "finmind_full_row_schema"),
            (lambda b: b.replace(b'"close": 20000', b'"close": true', 1), "finmind_numeric_type"),
            (lambda b: b.replace(b'"close": 20000', b'"close": 1e1000000', 1), "numeric_range"),
            (lambda b: b.replace(b'"close": 20000', b'"close": NaN', 1), "json_nonfinite"),
            (lambda b: b.replace(b'"status": 200', b'"status": 200, "status": 200', 1), "duplicate_json_key"),
            (lambda b: b.replace(b'"date": "2026-09-04"', b'"date": "2026-09-03"', 1), "finmind_date_set_or_duplicate"),
            (lambda b: b.replace(b'"status": 200', b'"status": true', 1), "finmind_status_msg"),
        ]
        for change, expected in variations:
            source, owner, transport, clock = self.build(body_transform=lambda a, b: (a, change(b)))
            self.expect_failure(source, expected, 2)

    def test_anchor_scale1_and_complete_finmind_oracle(self):
        source, owner, transport, clock = self.build(body_transform=lambda a, b: (a.replace(b",20020\n", b",20019\n"), b))
        self.expect_failure(source, "anchor_exact_scale1", 2)
        source, owner, transport, clock = self.build(hooks_options={"finmind": lambda raw, receipt, rows: rows[:-1]})
        self.expect_failure(source, "finmind_full_oracle_mismatch", 2)

    def test_observer_and_oracle_cannot_mutate_original(self):
        def observer(raw, receipt):
            raw[0] = 0
        source, owner, transport, clock = self.build(hooks_options={"observer": observer})
        self.expect_failure(source, "original_observer_mutated_raw", 1)

    def test_exact_cap_known_eof_and_unknown_failclosed(self):
        def pad(a, b):
            return a + b"\n" * (1048576 - len(a)), b
        source, owner, transport, clock = self.build(body_transform=pad)
        with source:
            self.assertEqual(source.receipts[0]["body_bytes"], 1048576)
        self.assertEqual(sum(transport.responses[0].read_sizes), 1048576)
        self.assertTrue(all(size > 0 for size in transport.responses[0].read_sizes))
        source, owner, transport, clock = self.build(body_transform=pad, options={0: {"declared": False, "cap_eof": False}})
        self.expect_failure(source, "exact_cap_without_framing_eof", 1)
        self.assertEqual(sum(transport.responses[0].read_sizes), 1048576)
        source, owner, transport, clock = self.build(body_transform=pad, options={0: {"declared": False, "cap_eof": True}})
        self.expect_failure(source, "exact_cap_without_framing_eof", 1)
        self.assertEqual(sum(transport.responses[0].read_sizes), 1048576)

    def test_headers_status_and_declared_cap_before_read(self):
        for options, expected in [({"status": 403}, "http_status_stop"),
                                  ({"headers": [("Content-Encoding", "gzip")]}, "identity_encoding_required"),
                                  ({"headers": [("Location", "https://other.invalid")]}, "redirect_cookie_stop"),
                                  ({"headers": [("Content-Length", "1048577")]}, "declared_body_limit"),
                                  ({"headers": [("Content-Length", "1"), ("content-length", "1")]}, "duplicate_http_header")]:
            source, owner, transport, clock = self.build(options={0: options})
            self.expect_failure(source, expected, 1)
            self.assertEqual(transport.responses[0].read_sizes, [])

    def test_request_deadline_and_spent_no_retry(self):
        ledger = M.AttemptLedger()
        source, owner, transport, clock = self.build(options={0: {"slow": True}}, ledger=ledger)
        self.expect_failure(source, "request_deadline", 1)
        source, owner, transport, clock = self.build(ledger=ledger)
        self.expect_failure(source, "namespace_spent", 1)
        self.assertEqual(transport.opened, [])

    def test_cumulative_request_budget_two_attempts(self):
        source, owner, transport, clock = self.build(options={0: {"read_seconds": 12}, 1: {"read_seconds": 9}})
        report = self.expect_failure(source, "request_deadline", 2)
        self.assertEqual(report["cumulative_request_elapsed_seconds"], 21)
        self.assertEqual(report["attempted_urls"], list(M.URLS))
        self.assertTrue(report["namespace_spent"])
        self.assertEqual(report["state"], "failed")
        self.assertFalse(any(event["code"] == "available" for event in report["events"]))
        self.assertEqual(report["first_product_failure"]["phase"], "request")
        self.assertEqual(report["first_product_failure"]["location"], "TaiexNominalSource._request_remaining")
        self.assertEqual(report["first_product_failure"]["cumulative_request_elapsed_seconds"], 21)
        self.assertTrue(all(response.closed for response in transport.responses))
        self.assertEqual(len(transport.responses), 2)
        print(json.dumps({"synthetic_request_budget": "12+9 rejects", "original_code": report["first_product_failure"]["code"],
                          "cumulative_request_elapsed_seconds": report["cumulative_request_elapsed_seconds"],
                          "attempted_spent": 2, "atomic_available": False, "all_closed": True,
                          "declared_roots_empty": report["declared_roots_empty"]}), flush=True)

    def test_cumulative_request_budget_within_cap(self):
        source, owner, transport, clock = self.build(options={0: {"read_seconds": 12}, 1: {"read_seconds": 7}})
        with source:
            self.assertEqual(source.state, "available")
            self.assertEqual(source.request_seconds_used, 19)
            self.assertEqual([receipt["request_elapsed_seconds"] for receipt in source.receipts], [12, 7])
            self.assertEqual([receipt["cumulative_request_elapsed_seconds"] for receipt in source.receipts], [12, 19])
            for cutoff in ("2026-10-05", "2026-10-06"):
                source.get_taiex_nominal21(cutoff).visit(lambda payload: self.assertEqual(payload["observation_count"], 21), owner)
                source.summarize(cutoff).visit(lambda payload: self.assertEqual(payload["interval_count"], 20), owner)
        report = source.diagnostic_report()
        self.assertEqual(report["cumulative_request_elapsed_seconds"], 19)
        self.assertTrue(report["declared_roots_empty"])
        self.assertEqual(report["cleanup_failures"], [])
        self.assertTrue(all(response.closed for response in transport.responses))
        print(json.dumps({"synthetic_request_budget": "12+7 accepts", "cumulative_request_elapsed_seconds": 19,
                          "synthetic_positive_getters": 2, "synthetic_positive_consumers": 2,
                          "all_closed": True, "declared_roots_empty": True}), flush=True)

    def test_opaque_root_failclosed_and_supported_backings(self):
        def opaque(raw, receipt):
            owner.track("unknown", object())
        source, owner, transport, clock = self.build(hooks_options={"observer": opaque})
        self.expect_failure(source, "opaque_source_root", 1)
        backing = bytearray(100)
        owner = M.RootOwner("root_test")
        view = owner.track("view", memoryview(backing))
        stream = owner.stringio("native", "abcdef")
        cycle = owner.track("cycle", [])
        cycle.append(cycle)
        size, count = M.estimate_roots([owner])
        self.assertGreater(size, 100)
        self.assertLess(count, 20)
        self.assertEqual(M._release_roots([owner]), [])
        self.assertEqual(backing, bytearray())
        self.assertTrue(stream.closed)
        self.assertEqual(cycle, [])
        with self.assertRaises(ValueError):
            len(view)

    def test_cleanup_failure_is_separate(self):
        source, owner, transport, clock = self.build()
        source.acquire()
        original_close = transport.responses[0].close
        def bad_close():
            original_close()
            raise RuntimeError("must not appear in diagnostic")
        transport.responses[0].close = bad_close
        source.release()
        report = source.diagnostic_report()
        self.assertTrue(report["declared_roots_empty"])
        self.assertEqual(report["cleanup_failures"], ["transport_close"])
        self.assertIsNone(report["first_product_failure"])
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_pending_transport_and_active_read_block_declared(self):
        source, owner, transport, clock = self.build()
        observed = {"pending": 0, "active": 0}
        actual_open = transport.open
        def checked_open(url, timeout):
            ordinal = len(transport.opened)
            root = source.product.roots["transport_" + str(ordinal)]
            self.assertIs(type(root), M.NativeTransport)
            self.assertIsNone(root.response)
            self.assertEqual(root.native_bytes, 262144)
            self.assertTrue(any(event["phase"] == "transport_pending" for event in source.diagnostics))
            observed["pending"] += 1
            return actual_open(url, timeout)
        transport.open = checked_open
        actual_remaining = source._request_remaining
        def checked_remaining(started):
            for ordinal in (0, 1):
                key = "active_read_block_" + str(ordinal)
                if key in source.product.roots:
                    self.assertIs(type(source.product.roots[key]), bytes)
                    self.assertEqual(source.product.roots["read_allowance_" + str(ordinal)].native_bytes, 65536)
                    owner.track("active_block_alias_" + str(ordinal), source.product.roots[key])
                    observed["active"] += 1
            return actual_remaining(started)
        source._request_remaining = checked_remaining
        with source:
            self.assertFalse(any(key.startswith("active_read_block_") for key in source.product.roots))
        self.assertEqual(observed, {"pending": 2, "active": 2})
        self.assertTrue(source.diagnostic_report()["declared_roots_empty"])
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_failed_postread_guard_cleans_named_block_alias(self):
        source, owner, transport, clock = self.build(options={0: {"read_seconds": 12}, 1: {"read_seconds": 9}})
        actual_remaining = source._request_remaining
        observed = []
        def checked_remaining(started):
            if "active_read_block_1" in source.product.roots:
                owner.track("failed_active_read_alias", source.product.roots["active_read_block_1"])
                observed.append(True)
            return actual_remaining(started)
        source._request_remaining = checked_remaining
        report = self.expect_failure(source, "request_deadline", 2)
        self.assertEqual(observed, [True])
        self.assertTrue(report["declared_roots_empty"])
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_released_memoryview_root_other_backings_continue(self):
        owner = M.RootOwner("released_root_test")
        released = memoryview(b"synthetic")
        released.release()
        owner.track("released", released)
        backing = owner.track("backing", bytearray(b"live-synthetic"))
        live = owner.track("live", memoryview(backing))
        native = owner.stringio("native", "live-synthetic")
        cycle = owner.track("alias_cycle", [backing])
        cycle.append(cycle)
        notes = []
        size, nodes = M.estimate_roots([owner], notes=notes)
        self.assertGreater(size, 0)
        self.assertEqual(M._release_roots([owner], notes=notes), [])
        self.assertEqual(notes, ["memoryview_already_released"])
        self.assertEqual(backing, bytearray())
        self.assertEqual(cycle, [])
        self.assertTrue(native.closed)
        self.assertEqual(owner.roots, {})
        with self.assertRaises(ValueError):
            len(live)

    def test_released_view_exception_payload_preserves_primary(self):
        class SlottedError(Exception):
            __slots__ = ("payload",)
        source, owner, transport, clock = self.build()
        released = memoryview(b"synthetic")
        released.release()
        owner.track("released_payload_view", released)
        buffer = owner.track("live_payload_buffer", bytearray(b"synthetic-live"))
        live = owner.track("live_payload_view", memoryview(buffer))
        native = owner.stringio("live_payload_native", "synthetic-live")
        cycle = owner.track("live_payload_cycle", [released, live, native, buffer])
        cycle.append(cycle)
        original = SlottedError(released)
        original.payload = cycle
        original.__cause__ = original
        with source:
            handle = source.get_taiex_nominal21("2026-10-05")
            def rejected(payload):
                raise original
            with self.assertRaises(M.TaiexSourceError) as caught:
                handle.visit(rejected, owner)
            self.assertEqual(caught.exception.code, "callback_failure")
            M.clear_error_graph(caught.exception)
            self.assert_terminal_results(source, owner, handle, "callback_failure")
        report = source.diagnostic_report()
        self.assertIn("memoryview_already_released", report["cleanup_notes"])
        self.assertEqual(report["cleanup_failures"], [])
        self.assertEqual(buffer, bytearray())
        self.assertEqual(cycle, [])
        self.assertTrue(native.closed)
        self.assertIsNone(original.payload)
        self.assertIsNone(original.__cause__)
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_serialization_failure_always_cleans_and_preserves_first_cause(self):
        source, owner, transport, clock = self.build()
        original_serializer = M.json.dumps
        def failed_serializer(*args, **kwargs):
            raise RuntimeError("synthetic serializer unavailable")
        with source:
            handle = source.get_taiex_nominal21("2026-10-05")
            buffer = owner.track("serialize_live_buffer", bytearray(b"synthetic"))
            native = owner.stringio("serialize_live_native", "synthetic")
            cycle = owner.track("serialize_alias_cycle", [buffer])
            cycle.append(cycle)
            try:
                M.json.dumps = failed_serializer
                sys.settrace(lambda frame, event, arg: None)
                sys.setprofile(lambda frame, event, arg: None)
                def rejected(payload):
                    raise RuntimeError("synthetic original consumer error")
                with self.assertRaises(M.TaiexSourceError) as caught:
                    handle.visit(rejected, owner)
                self.assertEqual(caught.exception.code, "callback_failure")
                M.clear_error_graph(caught.exception)
                report = source.diagnostic_report()
                self.assertEqual(report["first_product_failure"]["code"], "callback_failure")
                self.assertIn("audit_serialization_failure", report["cleanup_failures"])
                self.assertTrue(any(item["code"] == "audit_serialization_failure" for item in report["secondary"]))
                self.assertTrue(report["declared_roots_empty"])
                self.assertTrue(all(response.closed for response in transport.responses))
                self.assertEqual(len(transport.responses), 2)
                self.assertIsNone(sys.gettrace())
                self.assertIsNone(sys.getprofile())
                self.assertEqual(buffer, bytearray())
                self.assertEqual(cycle, [])
                self.assertTrue(native.closed)
            finally:
                M.json.dumps = original_serializer
                sys.settrace(None)
                sys.setprofile(None)
        self.assertEqual(source.state, "failed")


def main():
    global POLICY_RAW
    record = json.loads(subprocess.check_output(["gh", "api", "repos/YiCheng0608/stock-lab/issues/comments/6085684135"], encoding="utf-8"))
    assert record["issue_url"].endswith("/issues/33") and record["user"]["login"] == "YiCheng0608"
    fence = chr(96) * 3
    fragments = re.findall(r"(?m)^" + fence + r"json\n(.*?)\n" + fence + r"\s*$", record["body"], re.S)
    assert len(fragments) == 1
    POLICY_RAW = fragments[0].encode("utf-8")
    assert len(POLICY_RAW) == 4096 and hashlib.sha256(POLICY_RAW).hexdigest() == M.POLICY_SHA256
    print("Engineering RAM synthetic boundary only; financial/provider metadata GET0; artifact0B; not QA AC acceptance", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Boundaries))
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                      "financial_gets": 0, "provider_metadata_gets": 0, "artifact_bytes": 0,
                      "real_namespace_spent": M._REAL_LEDGER.spent, "policy_pin": M.POLICY_PIN,
                      "policy_sha256": M.POLICY_SHA256}), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
