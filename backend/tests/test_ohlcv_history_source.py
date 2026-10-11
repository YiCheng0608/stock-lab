"""Standalone synthetic boundary runner; no source requests or test artifacts.

Run: python -B -X utf8 backend/tests/test_ohlcv_history_source.py
Reads only this source/test and the public pinned repo SOURCE_REGISTRY reference.
The policy literal below was independently read from original Issue 32 comment
6084911117, not obtained from product policy/expected-value helpers. Synthetic
prices exercise boundaries and arithmetic; they are not QA financial truth.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from fractions import Fraction
from dataclasses import replace
from datetime import date, timedelta
import unittest
from unittest.mock import patch
import os
import sys


def _audit_boundary(event, args):
    if event in ("socket.connect", "socket.connect_ex", "subprocess.Popen"):
        raise AssertionError("standalone boundary runner forbids network/process launch")
    if event == "open":
        _, mode, flags = args
        if (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("standalone boundary runner forbids disk writes")


if not sys.dont_write_bytecode:
    raise RuntimeError("Use -B: the boundary runner does not permit bytecode artifacts")
sys.addaudithook(_audit_boundary)

EXTERNAL_POLICY = b'{"acquisition":{"accept_encoding":"identity","batch_seconds":180,"body_cap_bytes":1048576,"deadline":"cooperative","max_gets":8,"namespace":"issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa1","order":"newJuly calendar then seven price ascending","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608},"arithmetic":{"last60":"cutoff inclusive; no later rows","ma20":"last20 cutoff inclusive","ma60":"last60 cutoff inclusive","means":"exact reduced integer rational numerator/positive denominator; no floating/context rounding","prior20":"20 sessions strictly before cutoff","prior20_high":"exact maximum nominal high"},"calendar_source":{"expected_scope":"2026-07 full 23 weekdays; exact positive dates required; no missing-day closure inference","format":"UTF8_CSV","government_dataset":11391,"header":["\xe8\xb3\x87\xe6\x96\x99\xe6\x97\xa5\xe6\x9c\x9f","\xe9\x96\x8b\xe5\xb8\x82","\xe6\x9c\x80\xe9\xab\x98\xe5\x83\xb9","\xe6\x9c\x80\xe4\xbd\x8e\xe5\x83\xb9","\xe6\x94\xb6\xe5\xb8\x82","\xe6\xbc\xb2\xe8\xb7\x8c"],"method":"GET","prior_calendar_formal_blob":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md","prior_calendar_formal_sha256":"b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde","prior_verified_counts":{"August":21,"October_through_6":4,"September":20},"provider":"TPEx","rights":"OGL-1.0 government dataset resource / TPEx terms section 7 exception; TPEx attribution","url":"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F07%2F01","version":"tpex-july23-plus-formal-aug21-sep20-oct4/issue32-v1"},"consumer_version":"ordinary-nominal-ohlcv-window-summary-v1","cutoffs":["2026-10-05","2026-10-06"],"first_availability":"unknown","identity_as_of":"2026-10-06","instrument_type":"ordinary_stock","market":"TW/TPEx","price_source":{"basis":"provider_reported_nominal_ohlcv","dataset":"TaiwanStockPrice","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","fields":{"amount":"Trading_money","close":"close","high":"max","low":"min","open":"open","volume":"Trading_Volume"},"method":"GET","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-07-01"},"profile":"free_public_local","publication_time":"unknown","revision_time":"unknown","source_use":"local_personal_noncommercial_observed_nominal_ohlcv_snapshot","storage":"process_RAM","symbols":["3105","3293","5274","5347","6488","6510","8069"],"unit_policy":{"OHLC":"TWD/share","all_seven_must_match":true,"amount":"TWD","independent_latest_anchor":"stock-lab/master:d8918bc6491ec8ef65874979cf88d1322df2da43:SOURCE_REGISTRY/32.2:2026-10-06:42-fields","provider_literal_unit_annotation":false,"scale":1,"unit_mapping_inference":true,"version":"issue32-composite-six-field-scale1-v1","volume":"shares"},"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","adjusted_prices","company_actions","suspension_comparability","whole_window_historical_membership","historical_eligibility","actionable_strategy","plan","trading","historical_simulation","raw_disk_storage","redistribution","other_cutoffs"],"version":"issue32-ordinary-nominal-ohlcv-history-seven-cutoffs-v1"}'
EXTERNAL_PIN = "0f8c95eca6f0dcd08ca9b874996c4f41f8f8cf356f3282fee1e1c3f23734292d"

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/app/ohlcv_history_source.py"
spec = importlib.util.spec_from_file_location("issue32_ohlcv_boundary", SOURCE)
source = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = source
spec.loader.exec_module(source)
FORMAL = (ROOT / "docs/SOURCE_REGISTRY.md").read_bytes()

# External formal table, independently read rather than projected from source.
ANCHORS = {
    "3105": (615, 623, 588, 592, 19731700, 11863581093),
    "3293": (794, 794, 772, 780, 1495462, 1164617657),
    "5274": (19520, 19895, 18855, 18985, 188693, 3627465565),
    "5347": (184.5, 195, 184.5, 191, 34637793, 6615109776),
    "6488": (1175, 1260, 1145, 1205, 13913614, 16835605385),
    "6510": (3125, 3140, 3050, 3055, 560518, 1729347985),
    "8069": (147, 151.5, 145, 149, 10796741, 1607943663),
}
SYMBOLS = tuple(ANCHORS)
CUTOFFS = ("2026-10-05", "2026-10-06")
NAMESPACE = "issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa1"

# Issue 32 financial-start identity guard (user approval 6109493002, design
# 6109319936): issuer/coordinator/implementer ids arrive in the seal and the QA
# holder/model/effort are runtime read-backs. The ids below are synthetic; the
# product pins no session or model, so none of these are product constants.
SEAL_ISSUER = "f0000000-0000-0000-0000-0000000000a1"
SEAL_COORDINATORS = ("f0000000-0000-0000-0000-0000000000b1", "f0000000-0000-0000-0000-0000000000b2")
SEAL_IMPLEMENTERS = ("f0000000-0000-0000-0000-0000000000c1", "f0000000-0000-0000-0000-0000000000c2")
CLAUDE_QA_HOLDER = "5d2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d"
SEAL_URL = "https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-9999999999"
SEAL_URL_THRESHOLD = 6085344604


def declaration(holder=CLAUDE_QA_HOLDER, model="claude-sonnet-5-5", url=SEAL_URL):
    # Pure configuration boundary only; these synthetic declarations are NEVER
    # passed to a real transport/source constructor or used for acquisition.
    binding = source.ExecutionBinding(holder, holder, None, model, "xhigh", "a" * 40, "b" * 64, "c" * 64,
                                      "NOAUTH RAM pure guard; no financial execution")
    start = source.FinancialStart("issue32-financial-start-v1", SEAL_ISSUER, SEAL_COORDINATORS,
                                  SEAL_IMPLEMENTERS, NAMESPACE, EXTERNAL_PIN, url, binding, True, True)
    return start, binding


def days(start, stop):
    value, end = date.fromisoformat(start), date.fromisoformat(stop)
    result = []
    while value <= end:
        if value.weekday() < 5 and value.isoformat() not in ("2026-09-25", "2026-09-28"):
            result.append(value.isoformat())
        value += timedelta(days=1)
    return tuple(result)


DATES = days("2026-07-01", "2026-10-06")
JULY = days("2026-07-01", "2026-07-31")
assert len(DATES) == 68 and len(JULY) == 23
assert hashlib.sha256(FORMAL).hexdigest() == "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"


def corpus():
    """Small regenerable RAM corpus; no provider transport or fixture files."""
    header = "資料日期,開市,最高價,最低價,收市,漲跌\n"
    calendar = header + "".join(day.replace("-", "") + ",100,105,95,101,-1\n" for day in JULY)
    documents = []
    for stock_index, symbol in enumerate(SYMBOLS):
        rows = []
        for index, day in enumerate(DATES):
            close = 100 + stock_index * 10 + index
            if index == 8:
                close += 1  # force a nonterminating /60 mean at one cutoff
            row = {"date": day, "stock_id": symbol, "open": close,
                   "max": close + 2, "min": close - 2, "close": close,
                   "Trading_Volume": 1000 + index * 3,
                   "Trading_money": 100000 + index * 13,
                   "spread": -1, "Trading_turnover": 2}
            if day == "2026-10-06":
                o, h, l, c, v, a = ANCHORS[symbol]
                row.update(open=o, max=h, min=l, close=c, Trading_Volume=v, Trading_money=a)
            rows.append(row)
        documents.append({"status": 200, "msg": "success", "data": rows})
    return calendar.encode("utf8"), documents


def canonical(value):
    """Independent stdlib serialization, never the product's policy helper."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def body_docs(calendar=None, documents=None):
    default_calendar, default_documents = corpus()
    return [calendar if calendar is not None else default_calendar] + [
        json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf8")
        for document in (documents if documents is not None else default_documents)]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Response:
    def __init__(self, body, *, declared=True, eof=True, clock=None, read_delay=0, status=200, headers=None, close_raises=False):
        self.body = body
        self.offset = 0
        self.status = status
        self.headers = headers if headers is not None else (("Content-Length", str(len(body))),) if declared else ()
        self.closed = False
        self.eof_enabled = eof
        self.clock = clock
        self.read_delay = read_delay
        self.read_calls = []
        self.close_raises = close_raises
        self.close_calls = 0

    @property
    def known_eof(self):
        return self.eof_enabled and self.offset == len(self.body)

    def read(self, count, timeout):
        self.read_calls.append((count, timeout))
        assert count > 0
        if self.clock:
            self.clock.now += self.read_delay
        chunk = self.body[self.offset:self.offset + count]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True
        self.close_calls += 1
        if self.close_raises:
            raise OSError("DO_NOT_RETAIN_RAW" * 1000)


class Transport:
    def __init__(self, bodies=None, *, response_options=None, clock=None, open_delay=0, fail_at=None):
        self.bodies = bodies or body_docs()
        self.response_options = response_options or {}
        self.clock, self.open_delay, self.fail_at = clock, open_delay, fail_at
        self.opens = []
        self.responses = []

    def open(self, url, timeout):
        index = len(self.opens)
        self.opens.append((url, timeout))
        if self.clock:
            self.clock.now += self.open_delay
        if index == self.fail_at:
            raise OSError("synthetic transport failure")
        options = self.response_options.get(index, {})
        response = Response(self.bodies[index], **options)
        self.responses.append(response)
        return response


def build(*, transport=None, clock=None, ledger=None, **kwargs):
    transport = transport or Transport()
    clock = clock or Clock()
    snapshot = source.HistorySource(policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN,
                                    formal_blob=FORMAL, transport=transport,
                                    ledger=ledger or source.AttemptLedger(NAMESPACE), clock=clock, **kwargs)
    return snapshot, transport, clock


def admission(snapshot):
    captures = snapshot.inspection()["captures"]
    return source.OracleAdmission(NAMESPACE, EXTERNAL_PIN, "synthetic-boundary-oracle",
                                  "a" * 40, "b" * 64,
                                  tuple(c.receipt.canonical_sha256 for c in captures),
                                  23, 476, 2856, 42, True)


def available():
    snapshot, transport, clock = build()
    snapshot.acquire()
    snapshot.admit_independent_verification(admission(snapshot))
    return snapshot, transport, clock


class Boundaries(unittest.TestCase):
    def assertFailure(self, expected, function, *args, **kwargs):
        with self.assertRaises(source.SourceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def test_external_policy_all_recursive_keys_types_values_and_canonical(self):
        self.assertEqual(len(EXTERNAL_POLICY), 3266)
        self.assertEqual(hashlib.sha256(EXTERNAL_POLICY).hexdigest(), EXTERNAL_PIN)
        source.validate_policy(EXTERNAL_POLICY, EXTERNAL_PIN)
        policy = json.loads(EXTERNAL_POLICY)
        nodes = []
        def visit(value):
            if isinstance(value, dict):
                nodes.append(value)
                for child in value.values():
                    visit(child)
        visit(policy)
        for index, node in enumerate(nodes):
            for mode in ("extra", "missing"):
                mutated = copy.deepcopy(policy)
                cloned_nodes = []
                def collect(value):
                    if isinstance(value, dict):
                        cloned_nodes.append(value)
                        for child in value.values():
                            collect(child)
                collect(mutated)
                target = cloned_nodes[index]
                if mode == "extra":
                    target["unexpected"] = 1
                else:
                    del target[next(iter(target))]
                self.assertFailure("policy_keys", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        paths = [("calendar_source", "government_dataset"), ("unit_policy", "scale"),
                 ("acquisition", "max_gets"), ("acquisition", "request_seconds")]
        for outer, key in paths:
            for replacement in (True, 1.0, "1", None):
                mutated = copy.deepcopy(policy)
                mutated[outer][key] = replacement
                self.assertFailure("policy_type", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        for replacement in (1, "true", None):
            mutated = copy.deepcopy(policy)
            mutated["unit_policy"]["unit_mapping_inference"] = replacement
            self.assertFailure("policy_type", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        for outer, key, value in (("unit_policy", "scale", 1000), ("acquisition", "namespace", "other"),
                                  ("price_source", "dataset", "other")):
            mutated = copy.deepcopy(policy)
            mutated[outer][key] = value
            self.assertFailure("policy_canonical_mismatch", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        self.assertFailure("policy_pin", source.validate_policy, EXTERNAL_POLICY, "0" * 64)
        self.assertFailure("policy_canonical_mismatch", source.validate_policy, EXTERNAL_POLICY + b" ", EXTERNAL_PIN)
        self.assertFailure("duplicate_json_key", source.validate_policy, EXTERNAL_POLICY.replace(b'{', b'{"version":"duplicate",', 1), EXTERNAL_PIN)

    def test_unsupported_every_purpose_before_transport(self):
        for purpose in json.loads(EXTERNAL_POLICY)["unsupported"] + ["strategy", "storage", "random", None]:
            transport = Transport()
            self.assertFailure("unsupported_purpose", build, transport=transport, purpose=purpose)
            self.assertEqual(transport.opens, [])
        self.assertFailure("financial_start_required", source.HistorySource,
                           policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN, formal_blob=FORMAL)
        self.assertFailure("formal_blob_pin", source.HistorySource,
                           policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN, formal_blob=FORMAL + b" ")

    def test_financial_start_requires_exact_typed_reviewed_binding(self):
        start, binding = declaration(model="gpt-6.1-sol")
        source._financial_start(start, binding)
        cases = [
            (replace(start, authorized=1), binding, "financial_start_not_authorized"),
            (replace(start, namespace="other"), binding, "financial_start_scope"),
            (replace(start, policy_sha256="0" * 64), binding, "financial_start_scope"),
            (replace(start, seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6084911117"), binding, "financial_new_explicit_seal_required"),
            (start, replace(binding, candidate_sha="d" * 40), "financial_binding_mismatch"),
            (start, replace(binding, script_sha256="e" * 64), "financial_binding_mismatch"),
        ]
        for seal, runtime, code in cases:
            self.assertFailure(code, source._financial_start, seal, runtime)
        self.assertFailure("financial_start_with_boundary_transport", build, financial_start=start, execution_binding=binding)

    def test_financial_start_seal_supplied_identity_pure_guards(self):
        # NOAUTH: synthetic declarations validate only the pure guard; no
        # constructor/acquire and no network. Identities come from the seal.
        self.assertFalse(hasattr(source, "GLOBAL_ISSUER"))
        for model in ("claude-sonnet-5-5", "claude-opus-5-5", "gpt-6.1-sol"):
            with self.subTest(case="runtime_model_is_read_back", model=model):
                self.assertIsNone(source._financial_start(*declaration(model=model)))
        # Former hard-coded session ids carry no special status unless the seal lists them.
        for holder in ("01a12416-7c0d-7143-87e3-5da9e0ab4394", "01a12102-9891-7293-8c66-a342094e0990"):
            with self.subTest(case="unlisted_holder_not_pinned", holder=holder):
                self.assertIsNone(source._financial_start(*declaration(holder=holder)))
        start, binding = declaration()
        for holder in (SEAL_ISSUER,) + SEAL_COORDINATORS + SEAL_IMPLEMENTERS:
            with self.subTest(case="qa_not_independent_of_seal_role", holder=holder):
                self.assertFailure("financial_qa_identity", source._financial_start, *declaration(holder=holder))
        for label, role in (
                ("issuer_is_coordinator", {"issuer_thread_id": SEAL_COORDINATORS[0]}),
                ("issuer_is_implementer", {"issuer_thread_id": SEAL_IMPLEMENTERS[0]}),
                ("coordinator_is_implementer", {"coordinator_session_ids": (SEAL_IMPLEMENTERS[0],)}),
                ("duplicate_implementer", {"implementer_session_ids": (SEAL_IMPLEMENTERS[0], SEAL_IMPLEMENTERS[0])}),
                ("issuer_malformed", {"issuer_thread_id": "not-a-session-id"}),
                ("coordinator_uppercase", {"coordinator_session_ids": (SEAL_COORDINATORS[0].upper(),)}),
                ("implementer_malformed", {"implementer_session_ids": ("x",)})):
            with self.subTest(case=label):
                self.assertFailure("financial_start_scope", source._financial_start, replace(start, **role), binding)
        for label, role in (
                ("coordinators_empty", {"coordinator_session_ids": ()}),
                ("implementers_empty", {"implementer_session_ids": ()}),
                ("coordinators_list", {"coordinator_session_ids": list(SEAL_COORDINATORS)}),
                ("implementers_non_str", {"implementer_session_ids": (SEAL_IMPLEMENTERS[0], 1)}),
                ("issuer_non_str", {"issuer_thread_id": None})):
            with self.subTest(case=label):
                self.assertFailure("financial_start_type", source._financial_start, replace(start, **role), binding)
        for label, url, code in (
                ("seal_at_threshold", f"https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-{SEAL_URL_THRESHOLD}",
                 "financial_new_explicit_seal_required"),
                ("seal_other_issue", "https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-9999999999",
                 "financial_new_explicit_seal_required"),
                ("seal_after_threshold", f"https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-{SEAL_URL_THRESHOLD + 1}",
                 None)):
            with self.subTest(case=label):
                if code is None:
                    self.assertIsNone(source._financial_start(*declaration(url=url)))
                else:
                    self.assertFailure(code, source._financial_start, *declaration(url=url))

        cases = (
            ("start_type", None, binding, "financial_start_required"),
            ("binding_type", start, None, "financial_start_required"),
            ("seal_binding_type", replace(start, binding=None), binding, "financial_binding_type"),
            ("authorized_bool", replace(start, authorized=1), binding, "financial_start_not_authorized"),
            ("authorized_false", replace(start, authorized=False), binding, "financial_start_not_authorized"),
            ("whole_batch_bool", replace(start, whole_batch=1), binding, "financial_start_not_authorized"),
            ("whole_batch_false", replace(start, whole_batch=False), binding, "financial_start_not_authorized"),
            ("namespace", replace(start, namespace="other"), binding, "financial_start_scope"),
            ("policy_pin", replace(start, policy_sha256="0" * 64), binding, "financial_start_scope"),
            ("seal_threshold", replace(start, seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6084911117"), binding, "financial_new_explicit_seal_required"),
            ("candidate_mismatch", start, replace(binding, candidate_sha="d" * 40), "financial_binding_mismatch"),
            ("script_mismatch", start, replace(binding, script_sha256="e" * 64), "financial_binding_mismatch"),
        )
        for label, seal, runtime, code in cases:
            with self.subTest(case=label):
                self.assertFailure(code, source._financial_start, seal, runtime)
        for label, runtime, code in (
                ("not_top_level", replace(binding, parent_thread_id=SEAL_ISSUER), "financial_qa_not_top_level"),
                ("session_mismatch", replace(binding, holder_session_id=SEAL_ISSUER), "financial_qa_identity"),
                ("holder_malformed", replace(binding, holder_thread_id="NOT-A-SESSION", holder_session_id="NOT-A-SESSION"), "financial_qa_identity"),
                ("holder_uppercase", replace(binding, holder_thread_id=CLAUDE_QA_HOLDER.upper(), holder_session_id=CLAUDE_QA_HOLDER.upper()), "financial_qa_identity"),
                ("model_shape", replace(binding, model="bad model"), "financial_qa_identity"),
                ("model_too_long", replace(binding, model="m" * 65), "financial_qa_identity"),
                ("model_empty", replace(binding, model=""), "financial_binding_type"),
                ("effort", replace(binding, reasoning_effort="ultra"), "financial_qa_identity")):
            with self.subTest(case=label):
                self.assertFailure(code, source._financial_start, replace(start, binding=runtime), runtime)

    def test_calendar_csv_exact_all_rows_and_stop_unrun(self):
        calendar, documents = corpus()
        lines = calendar.decode("utf8").splitlines()
        variants = [
            (b'{"data":[]}', "calendar_header_or_count"),
            (b"<html>failed</html>", "calendar_header_or_count"),
            (calendar.replace("資料日期".encode(), "日期".encode()), "calendar_header_or_count"),
            ("\n".join(lines[:-1]).encode(), "calendar_header_or_count"),
            ((calendar.decode() + lines[1] + "\n").encode(), "calendar_header_or_count"),
            (calendar.replace(b"20260701", b"20260702", 1), "calendar_exact_dates"),
            (calendar.replace(b"20260701", b"20260803", 1), "calendar_exact_dates"),
            (calendar.replace(b"20260701", b"20260704", 1), "calendar_exact_dates"),
            (calendar.replace(b"20260701", b"20260230", 1), "calendar_value"),
            (calendar.replace(b"20260701", b"1150701", 1), "calendar_row"),
            (calendar.replace(b",105,95,", b",99,95,", 1), "ohlc_bounds"),
            (calendar.replace(b",100,105", b",0,105", 1), "calendar_number"),
            (calendar.replace(b",-1\n", b",NaN\n", 1), "calendar_number"),
        ]
        for raw, code in variants:
            with self.subTest(code=code):
                snapshot, transport, _ = build(transport=Transport(body_docs(raw, documents)))
                self.assertFailure(code, snapshot.acquire)
                self.assertEqual(snapshot.state, "failed")
                self.assertEqual(snapshot.ledger.attempted, (0,))
                self.assertEqual(snapshot.ledger.unrun, tuple(range(1, 8)))
                self.assertEqual(len(transport.opens), 1)
                self.assertTrue(transport.responses[0].closed)
                self.assertEqual(snapshot._capture_buffer, b"")
                self.assertEqual(len(snapshot.inspection()["captures"]), 1)
                self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
                snapshot.release()

    def test_all_price_rows_gate_no_partial_symbol_or_calendar(self):
        _, original = corpus()
        mutations = [
            (lambda row: row.update(stock_id="6488"), "price_stock_id"),
            (lambda row: row.update(date="2026-09-25"), "price_duplicate_or_calendar"),
            (lambda row: row.update(date="2026-10-07"), "price_duplicate_or_calendar"),
            (lambda row: row.update(date="2026-02-30"), "price_date"),
            (lambda row: row.update(date=20260701), "price_date"),
            (lambda row: row.update(close=0), "nonpositive_price"),
            (lambda row: row.update(open=True), "price_number_type"),
            (lambda row: row.update(close="100"), "price_number_type"),
            (lambda row: row.update(max=1), "ohlc_bounds"),
            (lambda row: row.update(Trading_Volume=True), "canonical_int64"),
            (lambda row: row.update(Trading_money=1.0), "canonical_int64"),
            (lambda row: row.update(Trading_money=9223372036854775808), "canonical_int64"),
            (lambda row: row.update(spread="bad"), "price_number_type"),
            (lambda row: row.update(Trading_turnover=-1), "canonical_int64"),
        ]
        for mutate, code in mutations:
            documents = copy.deepcopy(original)
            mutate(documents[0]["data"][0])  # validates pre-last60 rows too
            snapshot, transport, _ = build(transport=Transport(body_docs(documents=documents)))
            self.assertFailure(code, snapshot.acquire)
            self.assertEqual(len(transport.opens), 2)
            self.assertEqual(snapshot.ledger.attempted, (0, 1))
            snapshot.release()
        for mode in ("missing", "extra", "duplicate", "anchor", "last_symbol"):
            documents = copy.deepcopy(original)
            if mode == "missing":
                documents[0]["data"].pop(0)
                code, expected = "price_row_count", 2
            elif mode == "extra":
                documents[0]["data"].append(copy.deepcopy(documents[0]["data"][0]))
                code, expected = "price_row_count", 2
            elif mode == "duplicate":
                documents[0]["data"][0] = copy.deepcopy(documents[0]["data"][1])
                code, expected = "price_duplicate_or_calendar", 2
            elif mode == "anchor":
                documents[0]["data"][-1]["Trading_money"] += 1
                code, expected = "latest_anchor_mismatch", 2
            else:
                documents[-1]["data"][0]["close"] = 0
                code, expected = "nonpositive_price", 8
            snapshot, transport, _ = build(transport=Transport(body_docs(documents=documents)))
            self.assertFailure(code, snapshot.acquire)
            self.assertEqual(len(transport.opens), expected)
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
            snapshot.release()

    def test_price_json_duplicate_nonfinite_full_document(self):
        for raw, expected in ((b'{"status":200,"status":200,"msg":"success","data":[]}', "duplicate_json_key"),
                              (b'{"status":200,"msg":"success","data":[],"extra":NaN}', "nonfinite_json_number"),
                              (b'{"status":200,"msg":"success","data":[],"extra":Infinity}', "nonfinite_json_number")):
            bodies = body_docs()
            bodies[1] = raw
            snapshot, _, _ = build(transport=Transport(bodies))
            self.assertFailure(expected, snapshot.acquire)
            snapshot.release()

    def test_pending_oracle_exact_captures_tamper_counts_then_admit(self):
        snapshot, transport, _ = build()
        pending = snapshot.acquire()
        self.assertIs(pending, snapshot)
        self.assertEqual(snapshot.state, "pending")
        self.assertEqual(tuple(url for url, _ in transport.opens), (
            "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F07%2F01",
            *(f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={s}&start_date=2026-07-01&end_date=2026-10-06" for s in SYMBOLS)))
        self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
        proof = admission(snapshot)
        for mutation in (replace(proof, price_rows=475), replace(proof, latest_anchor_fields=41)):
            self.assertFailure("oracle_complete_scope", snapshot.admit_independent_verification, mutation)
        self.assertFailure("oracle_type", snapshot.admit_independent_verification, replace(proof, calendar_rows=True))
        self.assertFailure("oracle_receipt_type", snapshot.admit_independent_verification, replace(proof, receipt_sha256s=(1,) * 8))
        for hashes in (proof.receipt_sha256s[:-1], proof.receipt_sha256s[::-1],
                       proof.receipt_sha256s[:-1] + (proof.receipt_sha256s[0],), ("0" * 64,) * 8):
            self.assertFailure("oracle_capture_binding", snapshot.admit_independent_verification, replace(proof, receipt_sha256s=hashes))
        snapshot.admit_independent_verification(proof)
        self.assertEqual(snapshot.state, "available")
        self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, proof)
        snapshot.release()

    def test_fourteen_windows_values_exact_rationals_and_prior_exclusion(self):
        snapshot, _, _ = available()
        _, documents = corpus()
        nonterminating = False
        for index, symbol in enumerate(SYMBOLS):
            for cutoff in CUTOFFS:
                records = [row for row in documents[index]["data"] if row["date"] <= cutoff][-60:]
                prior = [row for row in documents[index]["data"] if row["date"] < cutoff][-20:]
                window = source.get_nominal_ohlcv60(snapshot, symbol, cutoff)
                self.assertEqual(len(window.bars), 60)
                self.assertEqual(window.bars[0].date, "2026-07-10" if cutoff.endswith("05") else "2026-07-13")
                for actual, expected in zip(window.bars, records):
                    self.assertEqual(actual.date, expected["date"])
                    for field, provider in (("open", "open"), ("high", "max"), ("low", "min"), ("close", "close")):
                        self.assertEqual(getattr(actual, field), Fraction(str(expected[provider])))
                    self.assertEqual(actual.volume, expected["Trading_Volume"])
                    self.assertEqual(actual.amount, expected["Trading_money"])
                summary = source.ordinary_nominal_ohlcv_window_summary_v1(snapshot, symbol, cutoff).values
                def exact(values):
                    total = sum((Fraction(str(value)) for value in values), Fraction(0))
                    return total / len(values)
                expectations = {
                    "ma20_close": exact([r["close"] for r in records[-20:]]),
                    "ma60_close": exact([r["close"] for r in records]),
                    "prior20_high": max(Fraction(str(r["max"])) for r in prior),
                    "prior20_volume_mean": exact([r["Trading_Volume"] for r in prior]),
                    "prior20_amount_mean": exact([r["Trading_money"] for r in prior]),
                }
                for field, expected in expectations.items():
                    actual = summary[field]
                    self.assertEqual((actual.numerator, actual.denominator), (expected.numerator, expected.denominator))
                    self.assertGreater(actual.denominator, 0)
                    self.assertEqual(math.gcd(actual.numerator, actual.denominator), 1)
                denominator = summary["ma60_close"].denominator
                while denominator % 2 == 0:
                    denominator //= 2
                while denominator % 5 == 0:
                    denominator //= 5
                nonterminating |= denominator > 1
                self.assertLess(summary["prior20_end"], cutoff)
                self.assertEqual(summary["prior20_end"], prior[-1]["date"])
        self.assertTrue(nonterminating)
        provenance = snapshot.provenance
        self.assertEqual(provenance["unit_policy"]["scale"], 1)
        self.assertIs(provenance["unit_policy"]["unit_mapping_inference"], True)
        self.assertIs(provenance["unit_policy"]["provider_literal_unit_annotation"], False)
        self.assertEqual((provenance["publication_time"], provenance["first_availability"], provenance["revision_time"]), ("unknown",) * 3)
        for symbol, cutoff in (("0000", "2026-10-05"), ("3105", "2026-10-07"), ("3105", "2026-09-30")):
            self.assertFailure("unsupported_window_scope", snapshot.get_nominal_ohlcv60, symbol, cutoff)
        snapshot.release()

    def test_release_expiry_invalidates_held_windows_summaries_and_roots(self):
        for expiry in (False, True):
            snapshot, _, clock = available()
            window = snapshot.get_nominal_ohlcv60("3105", "2026-10-05")
            summary = snapshot.summarize_nominal_ohlcv60("3105", "2026-10-05")
            if expiry:
                clock.now += 180
                self.assertEqual(snapshot.state, "expired")
            else:
                snapshot.release()
            self.assertFailure("consumer_unavailable", lambda: window.bars)
            self.assertFailure("consumer_unavailable", lambda: summary.values)
            self.assertFailure("consumer_unavailable", lambda: snapshot.provenance)
            for value in (snapshot._captures, snapshot._decoded_texts, snapshot._documents, snapshot._results, snapshot._summaries, snapshot._capture_buffer, snapshot._formal_blob, snapshot._anchors):
                self.assertFalse(value)
            self.assertIsNone(snapshot._transport)
            self.assertIsNone(snapshot._observer_roots)
            self.assertEqual(snapshot.ledger.attempted, tuple(range(8)))
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)

    def test_attempt_charged_before_open_no_reacquire_same_ledger(self):
        ledger = source.AttemptLedger(NAMESPACE)
        snapshot, transport, _ = build(ledger=ledger, transport=Transport(fail_at=0))
        self.assertFailure("transport_or_parse_failure", snapshot.acquire)
        self.assertEqual(ledger.attempted, (0,))
        snapshot.release()
        another, other_transport, _ = build(ledger=ledger)
        self.assertFailure("quota_spent", another.acquire)
        self.assertEqual(other_transport.opens, [])
        self.assertEqual(ledger.unrun, tuple(range(1, 8)))

    def test_known_eof_exact_cap_no_plus_one_unknown_exact_cap_rejects(self):
        body = b"x" * source.BODY_CAP
        for known in (False, True):
            transport = Transport([body], response_options={0: {"declared": False, "eof": known}})
            snapshot, _, _ = build(transport=transport)
            code = "calendar_csv_syntax" if known else "body_cap_without_known_eof"
            self.assertFailure(code, snapshot.acquire)
            response = transport.responses[0]
            self.assertEqual(sum(count for count, _ in response.read_calls), source.BODY_CAP)
            self.assertEqual(len(response.read_calls), 16)
            self.assertTrue(all(count > 0 for count, _ in response.read_calls))
            self.assertEqual(len(snapshot.inspection()["captures"]), int(known))
            self.assertTrue(response.closed)
            self.assertEqual(snapshot._capture_buffer, b"")
            snapshot.release()

    def test_remaining_aggregate_and_declared_length_fail_closed(self):
        transport = Transport(response_options={0: {"headers": (("Content-Length", str(source.BODY_CAP + 1)),)}})
        snapshot, _, _ = build(transport=transport)
        self.assertFailure("declared_body_cap", snapshot.acquire)
        self.assertEqual(transport.responses[0].read_calls, [])
        self.assertEqual(snapshot._captures, [])
        snapshot.release()
        # Direct capture boundary starts with a synthetic used-byte scalar;
        # still charges before open, never reads beyond aggregate remaining.
        for known in (False, True):
            transport = Transport([b"12345"], response_options={0: {"declared": False, "eof": known}})
            snapshot, _, clock = build(transport=transport)
            snapshot._ledger.begin()
            snapshot._batch_deadline = clock.now + 180
            snapshot._raw_bytes = source.RAW_CAP - 5
            if known:
                capture = snapshot._capture(0, source.CALENDAR_URL)
                self.assertEqual(capture.body, b"12345")
                self.assertTrue(capture.receipt.full_eof)
            else:
                self.assertFailure("body_cap_without_known_eof", snapshot._capture, 0, source.CALENDAR_URL)
                self.assertEqual(snapshot._captures, [])
            self.assertEqual(transport.responses[0].read_calls[0][0], 5)
            self.assertEqual(len(transport.responses[0].read_calls), 1)
            self.assertEqual(snapshot._raw_bytes, source.RAW_CAP)
            snapshot.release()
        transport = Transport([b"123"], response_options={0: {"headers": (("Content-Length", "4"),)}})
        snapshot, _, _ = build(transport=transport)
        self.assertFailure("incomplete_content_length", snapshot.acquire)
        self.assertEqual(snapshot._captures, [])
        snapshot.release()

    def test_framing_encoding_http_and_close_failure_boundaries(self):
        variants = [
            ({"status": 302}, "http_status"),
            ({"headers": (("Content-Encoding", "gzip"),)}, "content_encoding"),
            ({"headers": (("Content-Length", "01"),)}, "content_length"),
            ({"headers": (("Content-Length", "1"), ("Content-Length", "1"))}, "duplicate_framing_header"),
            ({"headers": (("Transfer-Encoding", "chunked"), ("Content-Length", "1"))}, "ambiguous_framing"),
            ({"headers": (("Transfer-Encoding", "other"),)}, "ambiguous_framing"),
        ]
        for options, code in variants:
            transport = Transport(response_options={0: options})
            snapshot, _, _ = build(transport=transport)
            self.assertFailure(code, snapshot.acquire)
            self.assertTrue(transport.responses[0].closed)
            self.assertEqual(len(transport.opens), 1)
            snapshot.release()

    def test_capture_primary_survives_close_raise_and_cleanup_only_rejects(self):
        for status, code, stage, secondary in ((302, "http_status", "capture_headers", 1),
                                               (200, "cleanup_failure", "capture_response_close", 0)):
            transport = Transport(response_options={0: {"status": status, "close_raises": True}})
            snapshot, _, _ = build(transport=transport)
            error = self.assertFailure(code, snapshot.acquire)
            self.assertEqual(error.diagnostics["primary_code"], code)
            self.assertEqual(error.diagnostics["primary_stage"], stage)
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], secondary)
            self.assertEqual(snapshot.diagnostics["code"], code)
            self.assertEqual(snapshot.diagnostics["primary_stage"], stage)
            if secondary:
                self.assertEqual(snapshot.diagnostics["secondary_cleanup_1_stage"], "capture_response_close")
                self.assertEqual(snapshot.diagnostics["secondary_cleanup_1_code"], "cleanup_failure")
            self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
            self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(snapshot.diagnostics)))
            self.assertEqual(transport.responses[0].close_calls, 1)
            self.assertEqual(snapshot.state, "failed")
            self.assertEqual(snapshot.ledger.attempted, (0,))
            self.assertEqual(snapshot.ledger.unrun, tuple(range(1, 8)))
            self.assertEqual(snapshot._capture_buffer, b"")
            self.assertEqual(len(snapshot.inspection()["captures"]), int(status == 200))
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
            self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))
            snapshot.release()
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)

    def test_https_response_both_closes_attempted_first_cleanup_preserved(self):
        calls = []
        class Body:
            status = 200
            fp = None
            def getheaders(self):
                return ()
            def close(self):
                calls.append("response")
                raise OSError("DO_NOT_RETAIN_RAW_response")
        class Connection:
            sock = object()
            def close(self):
                calls.append("connection")
                raise RuntimeError("DO_NOT_RETAIN_RAW_connection")
        response = source._HTTPSResponse(Connection(), Body())
        error = self.assertFailure("cleanup_failure", response.close)
        self.assertEqual(calls, ["response", "connection"])
        self.assertIsNone(response.socket)
        self.assertEqual(error.diagnostics["primary_stage"], "https_response_close")
        self.assertEqual(error.diagnostics["secondary_cleanup_count"], 1)
        self.assertEqual(error.diagnostics["secondary_cleanup_1_stage"], "https_connection_close")
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))
        # The outer capture already has an HTTP failure: preserve that primary
        # while flattening both close failures from the real response wrapper.
        calls.clear()
        class WrappedTransport:
            def open(self, url, timeout):
                body = Body()
                body.status = 302
                return source._HTTPSResponse(Connection(), body)
        snapshot, _, _ = build(transport=WrappedTransport())
        error = self.assertFailure("http_status", snapshot.acquire)
        self.assertEqual(calls, ["response", "connection"])
        self.assertEqual(error.diagnostics["primary_stage"], "capture_headers")
        self.assertEqual(error.diagnostics["secondary_cleanup_count"], 2)
        self.assertEqual(error.diagnostics["secondary_cleanup_1_stage"], "https_response_close")
        self.assertEqual(error.diagnostics["secondary_cleanup_2_stage"], "https_connection_close")
        self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(snapshot.diagnostics)))
        self.assertEqual(snapshot.ledger.attempted, (0,))
        self.assertEqual(snapshot.state, "failed")
        snapshot.release()

    def test_https_open_connect_header_primary_survives_multiple_cleanup(self):
        clock = Clock()
        for phase in ("connect", "headers"):
            calls = []
            class Body:
                def close(self):
                    calls.append("response_close")
                    raise OSError("DO_NOT_RETAIN_RAW_response")
            class Socket:
                def settimeout(self, value):
                    pass
            class Connection:
                def __init__(self, *args, **kwargs):
                    self.sock = Socket()
                def connect(self):
                    calls.append("connect")
                    if phase == "connect":
                        raise OSError("DO_NOT_RETAIN_RAW_connect")
                def request(self, *args, **kwargs):
                    calls.append("request")
                def getresponse(self):
                    calls.append("headers")
                    clock.now += 21
                    return Body()
                def close(self):
                    calls.append("connection_close")
                    raise RuntimeError("DO_NOT_RETAIN_RAW_connection")
            expected = "https_connect_failure" if phase == "connect" else "cooperative_deadline"
            with patch.object(source.time, "monotonic", clock), patch.object(source.http.client, "HTTPSConnection", Connection), patch.object(source.ssl, "create_default_context", lambda: object()):
                error = self.assertFailure(expected, source._HTTPSTransport().open, source.CALENDAR_URL, 20)
            self.assertEqual(error.diagnostics["primary_stage"], "https_" + phase)
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], 1 if phase == "connect" else 2)
            self.assertEqual(calls, ["connect", "connection_close"] if phase == "connect" else ["connect", "request", "headers", "response_close", "connection_close"])
            self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))

    def test_cumulative_request_and_batch_cooperative_deadlines(self):
        clock = Clock()
        transport = Transport(clock=clock, open_delay=12,
                              response_options={0: {"clock": clock, "read_delay": 9}})
        snapshot, _, _ = build(transport=transport, clock=clock)
        self.assertFailure("cooperative_deadline", snapshot.acquire)
        self.assertEqual(transport.responses[0].read_calls[0][1], 8)
        self.assertEqual(snapshot._raw_bytes, len(transport.bodies[0]))
        self.assertEqual(snapshot.ledger.attempted, (0,))
        self.assertTrue(transport.responses[0].closed)
        snapshot.release()
        # Independent direct-capture seam makes the last batch budget 3 seconds;
        # request budget is 20, so every I/O must receive the tighter 3.
        clock = Clock()
        transport = Transport(response_options={0: {"clock": clock, "read_delay": 4}})
        snapshot, _, _ = build(transport=transport, clock=clock)
        snapshot._ledger.begin()
        snapshot._batch_deadline = clock.now + 3
        self.assertFailure("cooperative_deadline", snapshot._capture, 0, source.CALENDAR_URL)
        self.assertEqual(transport.opens[0][1], 3)
        self.assertEqual(transport.responses[0].read_calls[0][1], 3)
        self.assertTrue(transport.responses[0].closed)
        snapshot.release()

    def test_observer_roots_dedup_and_over_cap_before_io(self):
        root = bytearray(1024)
        self.assertEqual(source.retained_roots_estimate(root, root), source.retained_roots_estimate(root))
        huge = bytearray(source.ROOTS_CAP)
        transport = Transport()
        self.assertFailure("retained_roots_estimate_cap", build, transport=transport, observer_roots=lambda: (huge,))
        self.assertEqual(transport.opens, [])
        huge.clear()

    def test_cleanup_primary_survives_later_failure_roots_cap(self):
        external = []
        failure_checks = []
        def observer():
            if external:
                failure_checks.append(True)
            return external
        class GrowingCloseTransport(Transport):
            def open(self, url, timeout):
                response = super().open(url, timeout)
                def close():
                    response.closed = True
                    response.close_calls += 1
                    external.append(bytearray(source.ROOTS_CAP))
                    raise OSError("DO_NOT_RETAIN_RAW" * 1000)
                response.close = close
                return response
        snapshot, transport, _ = build(transport=GrowingCloseTransport(), observer_roots=observer)
        try:
            error = self.assertFailure("cleanup_failure", snapshot.acquire)
            self.assertEqual(error.diagnostics["primary_stage"], "capture_response_close")
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], 0)
            self.assertEqual(error.diagnostics["secondary_validation_count"], 1)
            self.assertEqual(error.diagnostics["secondary_validation_1_code"], "retained_roots_estimate_cap")
            self.assertEqual(error.diagnostics["secondary_validation_1_stage"], "batch_failure_roots")
            self.assertGreater(error.diagnostics["secondary_validation_1_estimate_bytes"], source.ROOTS_CAP)
            self.assertEqual(failure_checks, [True])
            self.assertEqual(transport.responses[0].close_calls, 1)
            self.assertEqual(snapshot.ledger.attempted, (0,))
            self.assertEqual(snapshot.ledger.unrun, tuple(range(1, 8)))
            self.assertEqual(snapshot.state, "failed")
            self.assertEqual(snapshot._capture_buffer, b"")
            self.assertEqual(len(snapshot.inspection()["captures"]), 1)
            self.assertEqual(snapshot.diagnostics["primary_code"], "cleanup_failure")
            self.assertEqual(snapshot.diagnostics["secondary_validation_count"], 1)
            self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
            self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(snapshot.diagnostics)))
            self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)
        finally:
            snapshot.release()
            external.clear()

    def test_parse_primary_survives_later_failure_roots_caps(self):
        external = []
        failure_checks = []
        def observer():
            if external:
                failure_checks.append(True)
            return external
        calendar, documents = corpus()
        documents[0]["data"][0]["close"] = 0
        snapshot, transport, _ = build(transport=Transport(body_docs(calendar, documents)), observer_roots=observer)
        def trace(frame, event, arg):
            if (frame.f_globals.get("__name__") == spec.name and frame.f_code.co_name == "_prices"
                    and event == "exception" and isinstance(arg[1], source.SourceError)
                    and arg[1].code == "nonpositive_price" and not external):
                # Add the observed alias only after the actual price validator
                # has failed. The mandatory failure-path checks must still run.
                external.append(bytearray(source.ROOTS_CAP))
            return trace
        try:
            sys.settrace(trace)
            error = self.assertFailure("nonpositive_price", snapshot.acquire)
            sys.settrace(None)
            self.assertEqual(error.diagnostics["primary_stage"], "decode_parse")
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], 0)
            self.assertEqual(error.diagnostics["secondary_validation_count"], 2)
            for index, stage in enumerate(("parse_failure_roots", "batch_failure_roots"), 1):
                self.assertEqual(error.diagnostics[f"secondary_validation_{index}_code"], "retained_roots_estimate_cap")
                self.assertEqual(error.diagnostics[f"secondary_validation_{index}_stage"], stage)
                self.assertGreater(error.diagnostics[f"secondary_validation_{index}_estimate_bytes"], source.ROOTS_CAP)
            self.assertEqual(failure_checks, [True, True])
            self.assertEqual([response.close_calls for response in transport.responses], [1, 1])
            self.assertEqual(snapshot.ledger.attempted, (0, 1))
            self.assertEqual(snapshot.ledger.unrun, tuple(range(2, 8)))
            self.assertEqual(snapshot.state, "failed")
            self.assertEqual(snapshot._capture_buffer, b"")
            self.assertEqual(len(snapshot.inspection()["captures"]), 2)
            self.assertEqual(snapshot.diagnostics["primary_code"], "nonpositive_price")
            self.assertEqual(snapshot.diagnostics["secondary_validation_count"], 2)
            self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
            self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-06")
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)
        finally:
            sys.settrace(None)
            snapshot.release()
            external.clear()

    def test_active_root_cap_invalidates_consumers_and_handles_are_immutable(self):
        external = []
        snapshot, _, _ = build(observer_roots=lambda: external)
        snapshot.acquire()
        snapshot.admit_independent_verification(admission(snapshot))
        window = snapshot.get_nominal_ohlcv60("3105", "2026-10-05")
        with self.assertRaises(AttributeError):
            window.cutoff = "2026-10-07"
        external.append(bytearray(source.ROOTS_CAP))
        self.assertFailure("retained_roots_estimate_cap", lambda: window.bars)
        self.assertEqual(snapshot.state, "failed")
        self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
        snapshot.release()
        external.clear()

    def test_default_https_budget_boundaries_and_header_failure_closes_response(self):
        # The actual stdlib transport implementation is exercised with an
        # in-memory HTTPConnection boundary; the audit guard bans real sockets.
        clock = Clock()
        class Socket:
            def __init__(self):
                self.timeouts = []
            def settimeout(self, value):
                self.timeouts.append(value)
        class HTTPBody:
            status = 200
            length = 0
            fp = None
            def __init__(self):
                self.closed = False
            def getheaders(self):
                return (("Content-Length", "0"),)
            def isclosed(self):
                return self.closed
            def close(self):
                self.closed = True
        class Connection:
            def __init__(self, host, timeout, context):
                self.host, self.timeout, self.context = host, timeout, context
                self.sock = Socket()
                self.closed = False
                self.body = HTTPBody()
                self.requests = []
            def connect(self):
                clock.now += 12
            def request(self, method, target, headers):
                self.requests.append((method, target, headers))
                clock.now += 3
            def getresponse(self):
                clock.now += header_delay[0]
                return self.body
            def close(self):
                self.closed = True
        for delay in (1, 6):
            header_delay = [delay]
            clock.now = 100
            connections = []
            def factory(*args, **kwargs):
                value = Connection(*args, **kwargs)
                connections.append(value)
                return value
            with patch.object(source.time, "monotonic", clock), patch.object(source.http.client, "HTTPSConnection", factory), patch.object(source.ssl, "create_default_context", lambda: object()):
                if delay == 1:
                    response = source._HTTPSTransport().open(source.CALENDAR_URL, 20)
                    response.close()
                else:
                    self.assertFailure("cooperative_deadline", source._HTTPSTransport().open, source.CALENDAR_URL, 20)
            connection = connections[0]
            self.assertEqual(connection.timeout, 20)
            self.assertEqual(connection.sock.timeouts, [8, 5])
            self.assertTrue(connection.closed)
            self.assertTrue(connection.body.closed)
            self.assertEqual(connection.requests[0][0], "GET")
            self.assertEqual(connection.requests[0][2], {"Accept-Encoding": "identity", "Connection": "close"})

    def test_trace_same_body_receipt_before_parse_and_error_roots(self):
        events = {"during": [], "ready": [], "error": []}
        calendar, documents = corpus()
        documents[0]["data"][0]["close"] = 0
        snapshot, transport, _ = build(transport=Transport(body_docs(calendar, documents)),
                                      observer_roots=lambda: events)
        def trace(frame, event, arg):
            if frame.f_globals.get("__name__") != spec.name:
                return trace
            name = frame.f_code.co_name
            if name == "_capture" and event == "line" and frame.f_locals.get("capture_buffer"):
                events["during"].append(frame.f_locals["capture_buffer"])
            if name == "_capture_ready" and event == "return":
                events["ready"].append((frame.f_locals["full_body"], frame.f_locals["receipt"]))
            if name == "_parse_capture" and event == "exception":
                events["error"].append({key: frame.f_locals.get(key) for key in
                                         ("full_body", "receipt", "decoded_text", "document", "parse_results", "diagnostics")})
            return trace
        try:
            sys.settrace(trace)
            self.assertFailure("nonpositive_price", snapshot.acquire)
        finally:
            sys.settrace(None)
        self.assertTrue(events["during"])
        self.assertEqual(len(events["ready"]), 2)
        for index, (body, receipt) in enumerate(events["ready"]):
            self.assertIs(body, snapshot._captures[index].body)
            self.assertEqual(hashlib.sha256(body).hexdigest(), receipt.body_sha256)
            self.assertEqual(len(body), receipt.body_bytes)
            self.assertTrue(receipt.full_eof)
        self.assertTrue(any(event["document"] is not None and event["decoded_text"] is not None for event in events["error"]))
        self.assertEqual(snapshot.diagnostics["primary_code"], "nonpositive_price")
        self.assertEqual(snapshot.diagnostics["primary_stage"], "decode_parse")
        self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
        snapshot.release()
        events.clear()
        self.assertEqual(snapshot._capture_buffer, b"")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        sys.modules.pop(spec.name, None)
