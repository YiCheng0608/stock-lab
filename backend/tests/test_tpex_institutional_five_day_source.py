"""Engineering RAM boundary tests, not independent QA or real-source evidence.

Run only this file: python -B -Xutf8 backend/tests/test_tpex_institutional_five_day_source.py
All fixtures, transport stubs, independent engineering oracle and artifacts are RAM.
The external literal below was copied from Issue comment6088588415; its fixed pin
is independently specified, never computed from product policy to make expected.
The seal/runtime-binding cases build synthetic validator-only seals in RAM with
obviously fake UUID-shaped actors; they are never financial-start seals, and the only
native-provider path they reach is a mocked HTTPSConnection (no socket is opened).
"""
from __future__ import annotations

import ast
import builtins
import csv
import hashlib
import http.client
import inspect
import io
import json
import os
import re
import socket
import subprocess
import sys
import types
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

EXTERNAL_LITERAL = "{\"ac_revision\":1,\"admission_authority\":{\"authorized_issue_body_sha256\":\"e51eddb6de3d5ef5bc211e879545cfd1c96bf0f4748f4e386c5d9ffb877de74a\",\"financial_start_seal_required\":true,\"global_actual\":\"01a12102-9891-7293-8c66-a342094e0990\",\"original_user_actual\":\"01a12138-261a-7503-b135-42bac0fa1862\",\"original_user_message\":\"01a12247-8e11-7973-9033-3b6b0226b04f\",\"source_use_receipt\":\"https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6088463678\",\"source_use_receipt_sha256\":\"56240c60afbd88e906efc493d3cc2597070226ea5e47656b86afc9948e0077b0\"},\"calendar_requests\":0,\"consumer\":{\"all_add_subtract_steps_bounded\":true,\"all_six_sources_required\":true,\"category_sums\":42,\"cutoffs\":{\"2026-10-05\":[\"2026-09-29\",\"2026-09-30\",\"2026-10-01\",\"2026-10-02\",\"2026-10-05\"],\"2026-10-06\":[\"2026-09-30\",\"2026-10-01\",\"2026-10-02\",\"2026-10-05\",\"2026-10-06\"]},\"foreign_dealer_double_count\":false,\"getters\":7,\"inclusive\":true,\"investor_net_indices\":{\"dealer_self_plus_hedge\":23,\"foreign_excluding_foreign_dealer\":5,\"trust\":14},\"summaries\":14,\"total_index\":24,\"total_sums\":14,\"version\":\"institutional-five-day-net-summary-two-cutoffs-v1\"},\"csv_contract\":{\"all_returned_rows_structure_date_unique_code_nonempty_name\":true,\"bom\":\"reject\",\"canonical_ascii_integer_strings\":true,\"code_grammar\":\"[0-9A-Z]{4,6}\",\"date_grammar\":\"ROC_YYYMMDD_7_ASCII_DIGITS\",\"dealer_total_equals_self_plus_hedge\":true,\"dialect\":\"stdlib-csv-strict\",\"encoding\":\"UTF-8-strict\",\"foreign_total_equals_foreign_plus_foreign_dealer\":true,\"gross_nonnegative\":true,\"header\":[\"資料日期\",\"代號\",\"名稱\",\"外資及陸資不含外資自營商買進股數\",\"外資及陸資不含外資自營商賣出股數\",\"外資及陸資不含外資自營商買賣超股數\",\"外資自營商買進股數\",\"外資自營商賣出股數\",\"外資自營商買賣超股數\",\"外資及陸資買進股數\",\"外資及陸資賣出股數\",\"外資及陸資買賣超股數\",\"投信買進股數\",\"投信賣出股數\",\"投信買賣超股數\",\"自營商自行買賣買進股數\",\"自營商自行買賣賣出股數\",\"自營商自行買賣買賣超股數\",\"自營商避險買進股數\",\"自營商避險賣出股數\",\"自營商避險買賣超股數\",\"自營商買進股數\",\"自營商賣出股數\",\"自營商買賣超股數\",\"三大法人買賣超股數合計\"],\"integer_abs_max\":\"9223372036854775807\",\"net_equals_buy_minus_sell\":true,\"retain_original_selected_fields_header_ordinal_and_receipts\":true,\"selected_financial_integers\":924,\"selected_original_strings\":1050,\"selected_rows_per_date\":7,\"selected_rows_total\":42,\"source_date_equals_exact_requested_date\":true,\"stream_unselected_rows_with_bounded_scratch\":true,\"three_investor_total_equals_foreign_excluding_foreign_dealer_plus_trust_plus_dealer\":true,\"triplet_offsets\":[3,6,9,12,15,18,21],\"width\":25},\"formal_contract\":{\"archive_reference_only\":true,\"calendar_section\":\"31.2\",\"historical_numeric_file\":\"backend/worker/tpex_institutional_window.py\",\"historical_numeric_file_sha256\":\"3eba55a019a513f3774202fec410085b8d4eaf5429792b83be1f61d98127ae91\",\"master_sha\":\"d8918bc6491ec8ef65874979cf88d1322df2da43\",\"numeric_sections\":[\"13.3\",\"37.2\",\"45.4\",\"46.4\"],\"registry_sha256\":\"b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde\",\"rights_sections\":[\"13.1\",\"45.2\",\"46.2\"]},\"identity\":{\"eligibility\":\"unsupported\",\"historical_membership\":\"unsupported\",\"instrument\":\"ordinary_stock\",\"market\":\"TPEx\",\"symbols\":[\"3105\",\"3293\",\"5274\",\"5347\",\"6488\",\"6510\",\"8069\"]},\"issue\":36,\"lifecycle\":{\"artifacts_bytes\":0,\"cleanup\":\"trace_profile_off_first_then_all_attempt_close_release_clear_and_exit\",\"declared_roots_include\":[\"capture\",\"parser\",\"oracle\",\"getter\",\"consumer\",\"results\",\"diagnostics\",\"error_graph\",\"all_aliases\",\"memoryview_obj_backing\"],\"default_real_https\":true,\"estimate_not_RSS_peak_or_physical_wipe\":true,\"full_eof_and_raw_hash_before_parse\":true,\"independent_stdlib_csv_oracle\":true,\"same_RAM_getters_then_consumers\":true},\"limits\":{\"accept_encoding\":\"identity\",\"aggregate_raw_bytes\":6291456,\"batch_seconds\":180,\"body_bytes\":1048576,\"cookie\":false,\"credentials\":false,\"deadline_mode\":\"cooperative\",\"exact_cap_requires_existing_framing_eof\":true,\"first_failure\":\"STOP_attempted_SPENT\",\"max_attempts_per_url\":1,\"max_requests\":6,\"proxy\":false,\"read_before_body_and_aggregate_remaining\":true,\"redirects\":0,\"request_seconds_per_url_connect_request_header_read_cumulative\":20,\"retries\":0,\"supported_retained_roots_estimate_bytes\":33554432,\"token\":false,\"unknown_length_at_cap\":\"reject_without_plus1_or_read0_probe\"},\"metadata_requests\":0,\"parent_issue\":21,\"policy_version\":\"issue36-tpex-institutional-six-days-two-cutoffs-2026-10-10.1\",\"prior_spent_unchanged\":true,\"profile\":\"free_public_local_ram_institutional_two_cutoffs_v1\",\"rights\":{\"attribution\":\"金融監督管理委員會證券期貨局提供、財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv/issue36-two-cutoffs-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；2026-10-05與2026-10-06各五日三法人淨股數及合計為本地衍生結果。\",\"general_download_limit_preserved\":\"section5\",\"license\":\"Government Open Data License Version 1\",\"license_url\":\"https://data.gov.tw/license\",\"open_data_exception\":\"section7\",\"tpex_terms_url\":\"https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw\",\"uses\":{\"commercial_use\":\"not_admitted\",\"disk_store\":\"not_admitted\",\"historical_pit\":\"unsupported\",\"local_fetch\":\"admitted_for_this_six_request_use_after_fresh_seal\",\"raw_publish\":\"not_admitted\",\"raw_store\":\"RAM_only\",\"summarize\":\"local_RAM_only\"}},\"schema\":\"stock-lab-external-source-policy/v1\",\"source\":{\"dataset\":\"https://data.gov.tw/dataset/11856\",\"dates\":[\"2026-09-29\",\"2026-09-30\",\"2026-10-01\",\"2026-10-02\",\"2026-10-05\",\"2026-10-06\"],\"id\":\"tpex_government_institutional_csv\",\"method\":\"GET\",\"official_query_sla\":\"unknown\",\"owner\":\"財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）\",\"provider\":\"金融監督管理委員會證券期貨局（FSC SFB）\",\"query_order\":[\"l\",\"se\",\"t\",\"o\",\"d\"],\"statistics_basis\":\"original_trade_before_broker_account_corrections\",\"unit\":\"shares\",\"urls\":[\"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F29\",\"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F30\",\"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F01\",\"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F02\",\"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F05\",\"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F06\"],\"version\":\"dataset-11856-dated-csv/issue36-two-cutoffs-v1\"},\"unsupported\":[\"PIT\",\"publication\",\"first_availability\",\"revision_lineage\",\"adjustment\",\"twenty_day_turnover_denominator\",\"shares_div_TWD_as_dimensionless_strategy_gate\",\"full_history_membership\",\"hot_group\",\"strategy\",\"Signal\",\"Plan\",\"API\",\"UI\",\"DB\",\"cross_process\",\"other_dates_routes_or_providers\"]}"
EXTERNAL_BYTES = EXTERNAL_LITERAL.encode("utf-8")
FIXED_SHA = "93d8e746eccbed035d5a79ffbf178b5f89877017c2aea69e6b841d178c1b51a3"
CONTRACT = json.loads(EXTERNAL_LITERAL)
HEADER = CONTRACT["csv_contract"]["header"]
DAYS = tuple(CONTRACT["source"]["dates"])
CODES = tuple(CONTRACT["identity"]["symbols"])
WINDOWS = CONTRACT["consumer"]["cutoffs"]
URLS = tuple(CONTRACT["source"]["urls"])
MAXIMUM = 9223372036854775807
SOURCE_PATH = Path(__file__).resolve().parents[1] / "app" / "tpex_institutional_five_day_source.py"
SOURCE_CODE = SOURCE_PATH.read_bytes()
GUARD = [False]
IO_EVENTS = []


def _audit(event, args):
    if GUARD[0] and (event == "open" or event.startswith("socket.") or event in ("os.remove", "os.mkdir", "subprocess.Popen")):
        IO_EVENTS.append(event)
        raise AssertionError("forbidden selftest IO:" + event)


sys.addaudithook(_audit)


def load_product(name):
    module = types.ModuleType(name)
    module.__file__ = str(SOURCE_PATH)
    sys.modules[name] = module
    exec(compile(SOURCE_CODE, str(SOURCE_PATH), "exec"), module.__dict__)
    return module


m = load_product("issue36_engineering_source")
NOW = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self):
        self.seconds = 0.0
        self.utc_offset = 0.0

    def monotonic(self):
        return self.seconds

    def utcnow(self):
        return NOW + timedelta(seconds=self.utc_offset + self.seconds)

    def advance(self, seconds):
        self.seconds += seconds


def numeric_row(foreign, trust, dealer_self, dealer_hedge, foreign_dealer=0):
    def triplet(net):
        return [max(net, 0), max(-net, 0), net]
    foreign_values, fd = triplet(foreign), triplet(foreign_dealer)
    ds, dh = triplet(dealer_self), triplet(dealer_hedge)
    ft = [a + b for a, b in zip(foreign_values, fd)]
    de = [a + b for a, b in zip(ds, dh)]
    return [str(v) for g in (foreign_values, fd, ft, triplet(trust), ds, dh, de) for v in g] + [
        str(foreign + trust + dealer_self + dealer_hedge)]


def fixture_rows():
    result = []
    for d, day in enumerate(DAYS):
        roc = "115" + day[5:7] + day[8:]
        rows = [list(HEADER)]
        for i, symbol in enumerate(CODES):
            rows.append([roc, symbol, "合成股" + symbol] +
                        numeric_row((-1 if (i + d) % 2 else 1) * (i + d + 2),
                                    (0, -3, 4)[(i + d) % 3], i - 3, d - 2, (i + d) % 2))
        # Contract requires all rows' structure/date/code/name, not unselected
        # financial validation. Preserve this difference explicitly.
        rows.append([roc, "ABCD", "合成非標的"] + ["unselected"] * 22)
        result.append(rows)
    return result


def encode_rows(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerows(rows)
    return bytearray(stream.getvalue().encode("utf-8"))


def bodies_for(rows=None):
    return [encode_rows(day) for day in (fixture_rows() if rows is None else rows)]


class FakeResponse:
    def __init__(self, body, *, headers=None, status=200, unknown=False, chunked=False,
                 eof_at_end=False, short_read=None, clock=None, read_seconds=0,
                 close_failure=False, wire_length=None):
        self.body = body
        self.status = status
        self.offset = 0
        self.unknown = unknown
        self.chunked = chunked
        self.eof_at_end = eof_at_end
        self.short_read = short_read
        self.clock = clock
        self.read_seconds = read_seconds
        self.close_failure = close_failure
        self.close_calls = 0
        self.read_sizes = []
        self.closed = False
        self.length = None if unknown or chunked else (len(body) if wire_length is None else wire_length)
        self.headers = ([("Content-Type", "text/csv; charset=UTF-8")] +
                        ([("Transfer-Encoding", "chunked")] if chunked else
                         ([] if unknown else [("Content-Length", str(self.length))]))) if headers is None else headers

    def getheaders(self):
        return self.headers

    def read(self, amount):
        self.read_sizes.append(amount)
        if self.clock:
            self.clock.advance(self.read_seconds)
        count = amount if self.short_read is None else min(amount, self.short_read)
        piece = bytes(self.body[self.offset:self.offset + count])
        self.offset += len(piece)
        if self.length is not None:
            self.length -= len(piece)
            if self.length == 0:
                self.closed = True
        elif not piece or self.eof_at_end and self.offset == len(self.body):
            self.closed = True
        return piece

    def isclosed(self):
        return self.closed

    def close(self):
        self.close_calls += 1
        self.closed = True
        if self.close_failure:
            raise RuntimeError("synthetic response close failure")


class FakeConnection:
    def __init__(self, response, clock, *, phase_seconds=(0, 0, 0), fail_phase=None, close_failure=False):
        self.response = response
        self.clock = clock
        self.phase_seconds = phase_seconds
        self.fail_phase = fail_phase
        self.close_failure = close_failure
        self.close_calls = 0
        self.requests = []
        self.timeouts = []
        self.sock = self
        self.timeout = None

    def settimeout(self, value):
        self.timeouts.append(value)

    def connect(self):
        self.clock.advance(self.phase_seconds[0])
        if self.fail_phase == "connect":
            raise OSError("synthetic connect failure")

    def request(self, method, path, *, headers):
        self.requests.append((method, path, headers))
        self.clock.advance(self.phase_seconds[1])
        if self.fail_phase == "request":
            raise OSError("synthetic request failure")

    def getresponse(self):
        self.clock.advance(self.phase_seconds[2])
        if self.fail_phase == "headers":
            raise OSError("synthetic headers failure")
        return self.response

    def close(self):
        self.close_calls += 1
        if self.close_failure:
            raise OSError("synthetic connection close failure")


def setup_capture(*, bodies=None, options=None, connection_options=None, auth=True):
    raw = bodies_for() if bodies is None else bodies
    clock, connections = FakeClock(), []
    holders = {"fixture_originals": raw}
    opts = {} if options is None else options
    c_opts = {} if connection_options is None else connection_options

    def factory(host, timeout):
        ordinal = len(connections)
        if ordinal >= 6:
            raise AssertionError("attempt beyond six")
        response = FakeResponse(raw[ordinal], clock=clock, **opts.get(ordinal, {}))
        connection = FakeConnection(response, clock, **c_opts.get(ordinal, {}))
        connection.timeout = timeout
        connections.append(connection)
        return connection

    provider = m.SyntheticHTTPSProvider(factory, roots=holders)
    authorization = m.SyntheticAuthorization("synthetic:engineering-" + str(id(holders)),
                                             expires_at=NOW + timedelta(hours=1)) if auth else None
    policy = m.ExternalPolicy(EXTERNAL_BYTES, expected_sha256=FIXED_SHA)
    capture = m.RAMCapture(policy, authorization, provider=provider, clock=clock)
    return capture, raw, connections, clock


@contextmanager
def recording_releases(events):
    # Use real observer switches and inspect their actual state at each release.
    # Logging disable alone would miss an earlier transport or frame release.
    settrace, setprofile = sys.settrace, sys.setprofile
    prior_trace, prior_profile = sys.gettrace(), sys.getprofile()

    def record(label):
        events.append((label, sys.gettrace() is None, sys.getprofile() is None))

    def wrapped(label, operation):
        def call(*args, **kwargs):
            record(label)
            return operation(*args, **kwargs)
        return call

    settrace(lambda *args: None)
    setprofile(lambda *args: None)
    try:
        with ExitStack() as stack:
            for target, name, label in (
                    (sys, "settrace", "trace_off"), (sys, "setprofile", "profile_off"),
                    (FakeResponse, "close", "response_close"),
                    (FakeConnection, "close", "connection_close"),
                    (m.traceback, "clear_frames", "frame_release"),
                    (m.SupportedRoots, "release", "supported_backing_release"),
                    (m._MemoryReader, "close", "parser_view_release")):
                stack.enter_context(mock.patch.object(target, name, wrapped(label, getattr(target, name))))
            yield
    finally:
        settrace(prior_trace)
        setprofile(prior_profile)


def engineering_oracle(view):
    # Independent engineering expectations: no product parser/numeric helpers.
    text = bytes(view).decode("utf-8", "strict")
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    if rows[0] != HEADER:
        raise AssertionError("external header conflict")
    selected = {}
    codes = set()
    for ordinal, row in enumerate(rows[1:], 2):
        if len(row) != 25 or not re.fullmatch(r"[0-9A-Z]{4,6}", row[1]) or row[1] in codes or not row[2].strip():
            raise AssertionError("oracle structure")
        codes.add(row[1])
        source_day = datetime(int(row[0][:3]) + 1911, int(row[0][3:5]), int(row[0][5:])).date().isoformat()
        if row[1] in CODES:
            integers = [int(x) for x in row[3:]]
            if any(abs(x) > MAXIMUM for x in integers):
                raise AssertionError("oracle bound")
            for offset in (3, 6, 9, 12, 15, 18, 21):
                if int(row[offset]) - int(row[offset + 1]) != int(row[offset + 2]):
                    raise AssertionError("oracle triplet")
            for a, b, total in ((3, 6, 9), (15, 18, 21)):
                if any(int(row[a + k]) + int(row[b + k]) != int(row[total + k]) for k in range(3)):
                    raise AssertionError("oracle components")
            if sum(int(row[i]) for i in (5, 14, 23)) != int(row[24]):
                raise AssertionError("oracle total")
            selected[row[1]] = {"fields": row, "numbers": integers, "date": source_day, "ordinal": ordinal}
    if set(selected) != set(CODES):
        raise AssertionError("oracle selected")
    return selected


# ---- Synthetic validator-only seal fixtures (RAM; never a financial-start seal) ----
SEAL_URL = "https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-1"
# Obviously fake UUID-shaped values: these are not real session ids.
ROLE_IDS = {
    "qa_actual": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "global_actual": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "owner_actual": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "engineer_actual": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "runtime_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
}
QA_ID = ROLE_IDS["qa_actual"]
REVIEW_KEYS = ("qa_actual", "model", "effort", "runtime_id", "terminal_handle", "global_actual", "owner_actual",
               "engineer_actual", "candidate_sha", "source_sha256", "tests_sha256", "script_sha256",
               "loader_sha256", "typed_input_sha256", "command")
HASH_KEYS = ("source_sha256", "tests_sha256", "script_sha256", "loader_sha256", "typed_input_sha256")
SWITCHES = " -I -B -X utf8 -c "
# Independent oracle for the fixed seal scope: values come from the external policy
# literal where it carries them, never from the product module.
SEAL_FIXED = {
    "schema": "stock-lab-financial-start-seal/v1", "issue": 36,
    "base_sha": CONTRACT["formal_contract"]["master_sha"],
    "namespace": "issue36-seven-institutional-five-day-two-cutoffs-v1/qa1",
    "policy_sha256": FIXED_SHA,
    "source_use_receipt": CONTRACT["admission_authority"]["source_use_receipt"],
    "source_use_receipt_sha256": CONTRACT["admission_authority"]["source_use_receipt_sha256"],
    "cwd": "C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-36-institutional-five-day-source",
    "parent_thread_id": None,
    "urls": list(URLS), "dates": list(DAYS), "symbols": list(CODES),
    "body_bytes": CONTRACT["limits"]["body_bytes"], "aggregate_raw_bytes": CONTRACT["limits"]["aggregate_raw_bytes"],
    "retained_estimate_bytes": CONTRACT["limits"]["supported_retained_roots_estimate_bytes"],
    "per_url_seconds": CONTRACT["limits"]["request_seconds_per_url_connect_request_header_read_cumulative"],
    "batch_seconds": CONTRACT["limits"]["batch_seconds"],
    "requests": 6, "per_url_attempts": 1, "redirects": 0, "retries": 0,
    "metadata_requests": 0, "calendar_requests": 0, "artifacts_bytes": 0,
    "accept_encoding": "identity", "credentials": False, "token": False, "cookie": False, "proxy": False,
}


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def synthetic_fields(**overrides):
    loader = "import sys\nsys.stdout.write('synthetic loader')\n"
    argv = ["C:\\synthetic\\python.exe", "-I", "-B", "-X", "utf8", "-c", loader]
    fields = dict(ROLE_IDS)
    fields.update(
        model="claude-sonnet-5-5", effort="xhigh", terminal_handle="term_synthetic", candidate_sha="1" * 40,
        source_sha256=sha(b"synthetic source"), tests_sha256=sha(b"synthetic tests"),
        script_sha256=sha(b"synthetic script"), loader_sha256=sha(loader.encode("utf-8")),
        typed_input_sha256=sha(canonical_bytes({"candidate": "1" * 40})), command=subprocess.list2cmdline(argv))
    fields.update(overrides)
    return fields


def synthetic_seal(fields=None, *, drop=(), extra=None, issued="2026-01-01T00:00:00.000000Z",
                   expires="2099-12-31T00:00:00.000000Z", url=SEAL_URL, pretty=False):
    """Return (binding, raw, pin, url). Facts = fixed scope + binding fields + times."""
    fields = synthetic_fields() if fields is None else fields
    facts = dict(SEAL_FIXED)
    facts.update(fields)
    facts.update(issued_at=issued, expires_at=expires, receipt_url=url)
    for key in drop:
        facts.pop(key)
    facts.update(extra or {})
    raw = (json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8") if pretty else canonical_bytes(facts))
    return m.ReviewBinding(**fields), raw, sha(raw), url


def build_seal(fields=None, **options):
    binding, raw, pin, url = synthetic_seal(fields, **options)
    return m.FinancialStartSeal(raw, expected_sha256=pin, receipt_url=url, reviewed=binding)


@contextmanager
def claude_env(session=QA_ID, effort="xhigh", legacy=None):
    """Set exactly the runtime variables given; None means the variable is absent."""
    with mock.patch.dict(os.environ):
        for name in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT", "CODEX_THREAD_ID"):
            os.environ.pop(name, None)
        for name, value in (("CLAUDE_CODE_SESSION_ID", session), ("CLAUDE_EFFORT", effort),
                            ("CODEX_THREAD_ID", legacy)):
            if value is not None:
                os.environ[name] = value
        yield


@contextmanager
def no_network():
    def refuse(*args, **kwargs):
        raise AssertionError("forbidden selftest network")
    with mock.patch.object(socket, "create_connection", refuse), mock.patch.object(socket, "getaddrinfo", refuse), \
         mock.patch.object(socket.socket, "connect", refuse):
        yield


class EngineeringRAMTests(unittest.TestCase):
    def assert_release_order(self, events, *, required):
        labels = [event[0] for event in events]
        self.assertEqual(labels[:2], ["trace_off", "profile_off"])
        self.assertTrue(set(required).issubset(labels), labels)
        releases = [event for event in events if event[0] not in ("trace_off", "profile_off")]
        self.assertTrue(releases)
        self.assertTrue(all(trace_off and profile_off for _, trace_off, profile_off in releases), events)

    def assert_failed(self, capture, code=None):
        self.assertEqual(capture.state, "failed")
        if code:
            self.assertIn(code, capture.failure_code)
        self.assertFalse(capture.originals)
        self.assertFalse(capture.selected)
        self.assertFalse(capture.supported_roots())

    def test_import_constructor_and_default_refusal_zero_io(self):
        before = list(IO_EVENTS)
        fresh = load_product("issue36_constructor_guard")
        capture = fresh.RAMCapture(None)
        with mock.patch.object(http.client, "HTTPSConnection") as native:
            capture.capture()
            self.assertEqual(capture.state, "failed")
            self.assertFalse(capture.attempts)
            native.assert_not_called()
        policy = fresh.ExternalPolicy(EXTERNAL_BYTES, expected_sha256=FIXED_SHA)
        capture = fresh.RAMCapture(policy)
        with mock.patch.object(http.client, "HTTPSConnection") as native:
            capture.capture()
            self.assertEqual(capture.failure_code, "authorization_missing_or_kind_conflict")
            native.assert_not_called()
        self.assertEqual(IO_EVENTS, before)

    def test_exact_external_policy_pin_and_mutations(self):
        self.assertEqual(len(EXTERNAL_BYTES), 7500)
        self.assertEqual(hashlib.sha256(EXTERNAL_BYTES).hexdigest(), FIXED_SHA)
        for raw, pin in ((EXTERNAL_BYTES + b"\n", FIXED_SHA), (EXTERNAL_BYTES, "0" * 64),
                         (EXTERNAL_BYTES.replace(b'"issue":36', b'"issue":35'), FIXED_SHA)):
            with self.subTest(length=len(raw), pin=pin[:4]):
                with self.assertRaises(m.SourceError):
                    m.ExternalPolicy(raw, expected_sha256=pin)
        capture, raw, connections, clock = setup_capture(auth=False)
        capture.capture()
        self.assert_failed(capture, "authorization")
        self.assertFalse(connections)
        self.assertTrue(all(not b for b in raw))

    def test_kind_separation_and_no_engineering_financial_seal(self):
        capture, raw, connections, clock = setup_capture()
        capture.provider = m.HTTPSProvider()
        with mock.patch.object(http.client, "HTTPSConnection") as native:
            capture.capture()
            self.assert_failed(capture, "authorization")
            native.assert_not_called()
        # The policy's old admission actor is no authority and the product keeps no
        # default global/owner/engineer actor of its own.
        self.assertEqual(CONTRACT["admission_authority"]["global_actual"], "01a12102-9891-7293-8c66-a342094e0990")
        for name in ("GLOBAL_ACTUAL", "OWNER_ACTUAL", "ENGINEER_ACTUAL"):
            self.assertFalse(hasattr(m, name), name)
        # Only rejection inputs: no financial seal issued, no native positive.
        with self.assertRaisesRegex(m.SourceError, "^seal_length_invalid$"):
            m.FinancialStartSeal(b"", expected_sha256="0" * 64, receipt_url=SEAL_URL,
                                 reviewed=m.ReviewBinding(**synthetic_fields()))

    def test_42_original_rows_924_integers_seven_getters_and_fourteen_consumers(self):
        capture, raw, connections, clock = setup_capture()
        retained = {"oracle": {}, "getters": [], "consumers": [], "views": []}
        capture.declare_root("oracle_getter_consumer_results_allaliases", retained)
        backing_aliases, row_aliases, result_aliases = [], [], []
        with capture:
            capture.capture()
            self.assertEqual(capture.state, "available", capture.failure_code)
            profile = capture.profile()
            result_aliases.append(profile)
            self.assertEqual(profile.value["symbols"], list(CODES))
            self.assertEqual(profile.value["kind"], "synthetic_boundary")
            self.assertEqual(profile.value["unit"], "shares")
            for i, day in enumerate(DAYS):
                view = capture.original_view(i)
                retained["views"].append(view)
                backing_aliases.append(view.obj)
                self.assertEqual(bytes(view), bytes(raw[i]))
                retained["oracle"][day] = engineering_oracle(view)
                receipt = capture.original_view(i, receipt=True)
                retained["views"].append(receipt)
                facts = json.loads(bytes(receipt))
                self.assertEqual(facts["url"], URLS[i])
                self.assertTrue(facts["complete_eof"])
                self.assertEqual(facts["kind"], "synthetic_boundary")
                self.assertEqual(facts["body_sha256"], hashlib.sha256(view).hexdigest())
            strings = integers = 0
            for symbol in CODES:
                handle = capture.getter(symbol)
                retained["getters"].append(handle.value)
                result_aliases.append(handle)
                getter = handle.value
                self.assertEqual(getter["kind"], "synthetic_boundary")
                self.assertEqual(getter["unit"], "shares")
                self.assertEqual(getter["dates"], list(DAYS))
                for row in getter["rows"]:
                    expected = retained["oracle"][row["date"]][symbol]
                    self.assertEqual(row["original_fields"], expected["fields"])
                    self.assertEqual(row["financial_integers"], expected["numbers"])
                    self.assertEqual(row["row_ordinal"], expected["ordinal"])
                    self.assertEqual(row["header"], HEADER)
                    strings += len(row["original_fields"])
                    integers += len(row["financial_integers"])
                    row_aliases.append(row["original_fields"])
                for cutoff, days in WINDOWS.items():
                    handle = capture.consumer(symbol, cutoff)
                    result_aliases.append(handle)
                    result = handle.value
                    retained["consumers"].append(result)
                    expected = {key: str(sum(int(retained["oracle"][day][symbol]["fields"][index]) for day in days))
                                for key, index in (("foreign", 5), ("trust", 14), ("dealer", 23))}
                    self.assertEqual(result["category_net"], expected)
                    self.assertEqual(result["total_net"], str(sum(int(v) for v in expected.values())))
                    self.assertEqual(result["dates"], days)
                    self.assertEqual(len(result["source_rows"]), 5)
                    self.assertEqual(result["unit"], "shares")
                    if cutoff == "2026-10-05":
                        self.assertNotIn("2026-10-06", [r["date"] for r in result["source_rows"]])
            self.assertEqual((strings, integers), (1050, 924))
            self.assertLess(capture.retained_estimate(), 32 * 1024 * 1024)
            self.assertEqual(len(connections), 6)
            for i, connection in enumerate(connections):
                method, path, headers = connection.requests[0]
                self.assertEqual(method, "GET")
                self.assertEqual(path, URLS[i].split("www.tpex.org.tw")[1])
                self.assertEqual(headers["Accept-Encoding"], "identity")
                self.assertFalse(set(k.lower() for k in headers) & {"authorization", "cookie", "proxy-authorization"})
                self.assertEqual(connection.close_calls, 1)
                self.assertEqual(connection.response.close_calls, 1)
        self.assertFalse(retained)
        self.assertTrue(all(not a for a in backing_aliases + row_aliases + raw))
        for handle in result_aliases:
            with self.assertRaises(m.SourceError):
                _ = handle.value
        self.assertFalse(capture.cleanup_failures)

    def test_all_924_selected_numeric_positions_reject_noncanonical(self):
        tested = 0
        for d in range(6):
            for i in range(7):
                for column in range(3, 25):
                    rows = fixture_rows()
                    rows[d][i + 1][column] = "01"
                    capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
                    capture.capture()
                    if capture.state != "failed" or "share_quantity_invalid" not in capture.failure_code:
                        self.fail(f"numeric position d={d},symbol={CODES[i]},column={column},state={capture.state},code={capture.failure_code}")
                    self.assertTrue(all(not b for b in raw))
                    tested += 1
        self.assertEqual(tested, 924)

    def test_schema_date_identity_missing_and_duplicate_fail_whole_profile(self):
        def cases():
            rows = fixture_rows(); rows[0][0][0] = "changed"; yield "header", rows
            rows = fixture_rows(); rows[0][1].pop(); yield "row_width", rows
            for value in ("1151000", "1150930", "20260929", "１１５０９２９"):
                rows = fixture_rows(); rows[0][1][0] = value; yield "date", rows
            for value in ("", " ", "lower", "AAA", "ABCDEFG"):
                rows = fixture_rows(); rows[0][-1][1] = value; yield "code", rows
            rows = fixture_rows(); rows[0][-1][2] = " \t"; yield "name_empty", rows
            rows = fixture_rows(); rows[0].append(list(rows[0][1])); yield "duplicate_code", rows
            rows = fixture_rows(); rows[0].pop(1); yield "selected_missing", rows
        for label, rows in cases():
            with self.subTest(label=label):
                capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
                capture.capture()
                self.assert_failed(capture)
                for symbol in CODES:
                    with self.assertRaises(m.SourceError):
                        capture.getter(symbol)
                self.assertTrue(all(not b for b in raw))

    def test_integer_grammar_gross_components_and_total(self):
        for value in ("+1", "-0", "00", "1.0", "1e2", "1,000", " 1", "١", str(MAXIMUM + 1), str(-MAXIMUM - 1)):
            rows = fixture_rows(); rows[0][1][5] = value
            capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
            capture.capture()
            self.assert_failed(capture)
        for column in (3, 4, 6, 7, 9, 10, 12, 13, 15, 16, 18, 19, 21, 22):
            rows = fixture_rows(); rows[0][1][column] = "-1"
            capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
            capture.capture()
            self.assert_failed(capture, "negative_buy_or_sell")
        for column in (5, 8, 11, 14, 17, 20, 23, 24):
            rows = fixture_rows(); rows[0][1][column] = str(int(rows[0][1][column]) + 1)
            capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
            capture.capture()
            self.assert_failed(capture)

    def test_daily_and_window_intermediate_overflow_even_when_final_math_fits(self):
        rows = fixture_rows()
        rows[0][1][3:] = numeric_row(MAXIMUM, 1, -1, 0)
        capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
        capture.capture()
        self.assert_failed(capture, "integer_overflow")
        # Every field fits, but foreign component addition would overflow.
        rows = fixture_rows(); rows[0][1][3:] = numeric_row(MAXIMUM, 0, 0, 0)
        rows[0][1][6:9] = ["1", "0", "1"]
        capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
        capture.capture()
        self.assert_failed(capture, "integer_overflow")
        # Five-day intermediate MAX+1-1, not just the final aggregate.
        rows = fixture_rows()
        for d, net in enumerate((MAXIMUM, 1, -1, 0, 0, 0)):
            rows[d][1][3:] = numeric_row(net, 0, 0, 0)
        capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
        capture.capture(); self.assertEqual(capture.state, "available", capture.failure_code)
        old = capture.getter(CODES[0])
        with self.assertRaises(m.SourceError):
            capture.consumer(CODES[0], "2026-10-05")
        self.assert_failed(capture, "integer_overflow")
        with self.assertRaises(m.SourceError):
            _ = old.value
        # Categories each fit, but ordered three-category total MAX+1-1 fails.
        rows = fixture_rows()
        for d in range(6):
            rows[d][1][3:] = numeric_row(MAXIMUM if d == 0 else 0, 1 if d == 1 else 0, -1 if d == 1 else 0, 0)
        capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
        capture.capture(); self.assertEqual(capture.state, "available", capture.failure_code)
        with self.assertRaises(m.SourceError):
            capture.consumer(CODES[0], "2026-10-05")
        self.assert_failed(capture, "integer_overflow")

    def test_distinct_synthetic_pending_failed_expired_and_released(self):
        pending, raw, connections, clock = setup_capture()
        with self.assertRaises(m.SourceError):
            pending.getter(CODES[0])
        self.assertEqual(pending.state, "pending")
        self.assertFalse(connections)
        pending.close()
        failed, raw, connections, clock = setup_capture(options={0: {"status": 403}})
        failed.capture(); self.assert_failed(failed)
        expired, raw, connections, clock = setup_capture()
        expired.capture(); self.assertEqual(expired.state, "available")
        handle = expired.getter(CODES[0])
        clock.utc_offset = 3601
        with self.assertRaises(m.SourceError):
            _ = handle.value
        self.assertEqual(expired.state, "expired")
        self.assertTrue(all(not b for b in raw))
        released, raw, connections, clock = setup_capture()
        released.close()
        with self.assertRaises(m.SourceError):
            released.consumer(CODES[0], DAYS[-1])
        self.assertEqual(released.state, "released")
        self.assertFalse(connections)
        before, raw, connections, clock = setup_capture()
        clock.utc_offset = 3601
        before.capture(); self.assert_failed(before, "synthetic_expired")
        self.assertFalse(connections)

    def test_http_first_failure_stop_attempted_spent_no_retry(self):
        for index in range(6):
            capture, raw, connections, clock = setup_capture(options={index: {"status": (401, 403, 429)[index % 3]}})
            capture.capture(); self.assert_failed(capture, "http_status")
            self.assertEqual(len(connections), index + 1)
            self.assertEqual(len(capture.authorization.spent), index + 1)
            self.assertEqual([a["url"] for a in capture.attempts], list(URLS[:index + 1]))
            self.assertTrue(all(a["spent"] for a in capture.attempts))
            self.assertTrue(all(c.close_calls == 1 and c.response.close_calls == 1 for c in connections))
            with self.assertRaises(m.SourceError):
                capture.capture()
            self.assertEqual(len(connections), index + 1)
        for phase in ("connect", "request", "headers"):
            capture, raw, connections, clock = setup_capture(connection_options={0: {"fail_phase": phase}})
            capture.capture(); self.assert_failed(capture)
            self.assertEqual(len(connections), 1)
            self.assertEqual(connections[0].close_calls, 1)

    def test_transport_header_framing_encoding_and_utf8_refusal(self):
        examples = [
            [("Content-Type", "text/csv"), ("Content-Length", "1"), ("Transfer-Encoding", "chunked")],
            [("Content-Type", "text/csv"), ("Content-Length", "01")],
            [("Content-Type", "text/csv"), ("Content-Length", "1"), ("content-length", "1")],
            [("Content-Type", "text/csv"), ("Content-Encoding", "gzip")],
            [("Content-Type", "text/html")],
            [("Content-Type", "text/csv;charset=big5")],
            [("Content-Type", "text/csv"), ("Transfer-Encoding", "gzip")],
        ]
        for headers in examples:
            capture, raw, connections, clock = setup_capture(options={0: {"headers": headers}})
            capture.capture(); self.assert_failed(capture)
            self.assertFalse(connections[0].response.read_sizes)
        for prefix in (b"\xef\xbb\xbf", b"\xff"):
            raw = bodies_for(); raw[0][:0] = prefix
            capture, raw, connections, clock = setup_capture(bodies=raw)
            with mock.patch.object(m.RAMCapture, "_parse") as parser:
                capture.capture()
                self.assert_failed(capture)
                parser.assert_not_called()
        raw = bodies_for()
        capture, raw, connections, clock = setup_capture(bodies=raw, options={0: {"wire_length": len(raw[0]) + 1}})
        capture.capture(); self.assert_failed(capture, "premature_eof")
        capture, raw, connections, clock = setup_capture(options={0: {"short_read": 1}})
        with capture:
            capture.capture()
            self.assertEqual(capture.state, "available", capture.failure_code)

    def test_exact_body_and_six_mib_aggregate_with_existing_framing_no_probe(self):
        raw = [bytearray(b"x" * 1048576) for _ in range(6)]
        capture, raw, connections, clock = setup_capture(bodies=raw)
        try:
            capture.authorization.started = True
            capture.state = "capturing"
            capture.batch_start = clock.monotonic()
            for ordinal in range(6):
                capture._fetch(ordinal)
            self.assertEqual(capture.raw_bytes, 6291456)
            self.assertTrue(all(len(capture.originals[i]["body"]) == 1048576 for i in range(6)))
            for connection in connections:
                self.assertEqual(sum(connection.response.read_sizes), 1048576)
                self.assertTrue(all(0 < n <= 16384 for n in connection.response.read_sizes))
                self.assertEqual(connection.response.length, 0)
        finally:
            capture.close()
        self.assertTrue(all(not b for b in raw))
        self.assertFalse(capture.cleanup_failures)

    def test_unknown_length_exactcap_rejects_without_plus_one_or_read_zero(self):
        for chunked in (False, True):
            raw = [bytearray(b"x" * 1048576)] + bodies_for()[1:]
            capture, raw, connections, clock = setup_capture(bodies=raw, options={0: {"unknown": not chunked, "chunked": chunked}})
            try:
                capture.authorization.started = True
                capture.state = "capturing"
                capture.batch_start = clock.monotonic()
                with self.assertRaisesRegex(m.SourceError, "unknown_length_at_cap"):
                    capture._fetch(0)
                sizes = connections[0].response.read_sizes
                self.assertEqual(sum(sizes), 1048576)
                self.assertTrue(all(0 < n <= 16384 for n in sizes))
            finally:
                capture.close()
        raw = [bytearray(b"x" * 1048576)] + bodies_for()[1:]
        capture, raw, connections, clock = setup_capture(bodies=raw, options={0: {"chunked": True, "eof_at_end": True}})
        try:
            capture.state = "capturing"; capture.batch_start = clock.monotonic()
            capture._fetch(0)
            self.assertEqual(len(capture.originals[0]["body"]), 1048576)
        finally:
            capture.close()

    def test_read_before_dual_remaining_and_declared_cap_rejects(self):
        raw = [bytearray(b"xxx")] + bodies_for()[1:]
        capture, raw, connections, clock = setup_capture(bodies=raw, options={0: {"unknown": True}})
        try:
            capture.state = "capturing"; capture.batch_start = clock.monotonic()
            capture.raw_bytes = 6291454
            with self.assertRaises(m.SourceError):
                capture._fetch(0)
            self.assertEqual(connections[0].response.read_sizes, [2])
        finally:
            capture.close()
        raw = [bytearray(b"x" * 1048577)] + bodies_for()[1:]
        capture, raw, connections, clock = setup_capture(bodies=raw)
        try:
            capture.state = "capturing"; capture.batch_start = clock.monotonic()
            with self.assertRaisesRegex(m.SourceError, "declared_length_cap"):
                capture._fetch(0)
            self.assertFalse(connections[0].response.read_sizes)
        finally:
            capture.close()

    def test_cumulative_transport_and_cooperative_batch_deadlines(self):
        capture, raw, connections, clock = setup_capture(
            options={0: {"read_seconds": 4}}, connection_options={0: {"phase_seconds": (6, 7, 4)}})
        capture.capture(); self.assert_failed(capture, "cooperative_deadline")
        self.assertEqual(len(connections), 1)
        self.assertLessEqual(max(connections[0].timeouts), 20)
        capture, raw, connections, clock = setup_capture(connection_options={0: {"phase_seconds": (20, 0, 0)}})
        capture.capture(); self.assert_failed(capture, "cooperative_deadline")
        self.assertFalse(connections[0].requests)
        capture, raw, connections, clock = setup_capture()
        original_parse = m.RAMCapture._parse

        def slow_parse(instance, ordinal):
            original_parse(instance, ordinal)
            clock.advance(46)

        with mock.patch.object(m.RAMCapture, "_parse", slow_parse):
            capture.capture()
        self.assert_failed(capture, "cooperative_batch_deadline")
        self.assertEqual(len(connections), 6)

    def test_six_eof_before_any_parse_and_late_parse_whole_profile(self):
        raw = bodies_for(); raw[5][:0] = b"\xff"
        capture, raw, connections, clock = setup_capture(bodies=raw)
        with mock.patch.object(m.RAMCapture, "_parse") as parse:
            capture.capture(); self.assert_failed(capture, "utf8_invalid")
            parse.assert_not_called()
        rows = fixture_rows(); rows[5][1][24] = "bad"
        capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
        capture.capture(); self.assert_failed(capture, "share_quantity_invalid")
        self.assertEqual(len(connections), 6)
        self.assertTrue(all(not b for b in raw))

    def test_body_receipt_selected_and_policy_tampering_revokes_all_results(self):
        for target in ("body", "receipt", "selected", "policy"):
            capture, raw, connections, clock = setup_capture()
            capture.capture(); self.assertEqual(capture.state, "available")
            result = capture.getter(CODES[0])
            alias = result.value
            if target == "body":
                view = capture.original_view(0); view.obj[-1] ^= 1
            elif target == "receipt":
                view = capture.original_view(0, receipt=True); view.obj[-1] ^= 1
            elif target == "selected":
                alias["rows"][0]["original_fields"][5] = "0"
            else:
                capture.policy.facts["issue"] = 35
            with self.assertRaises(m.SourceError):
                capture.consumer(CODES[0], "2026-10-05")
            self.assert_failed(capture)
            self.assertFalse(alias)
            self.assertTrue(all(not b for b in raw))
            with self.assertRaises(m.SourceError):
                _ = result.value

    def test_supported_graph_deduplicates_views_backing_and_actually_clears_aliases(self):
        capture, raw, connections, clock = setup_capture()
        capture.capture()
        body = capture.original_view(0)
        backing = body.obj
        child = body[1:20]
        extra = memoryview(backing)
        aliases = {"capture": body, "parser": child, "oracle": extra, "getter": [backing, backing],
                   "consumer": {}, "results": [], "diagnostics": {}, "allaliases": [child], "memoryview.obj": backing}
        capture.declare_root("all_QA_supported_declared_roots", aliases)
        self.assertLess(capture.retained_estimate(), 33554432)
        capture.close()
        self.assertFalse(backing)
        self.assertFalse(aliases)
        for view in (body, child, extra):
            with self.assertRaises(ValueError):
                _ = view.obj
        self.assertFalse(capture.cleanup_failures)
        self.assertFalse(capture.supported_roots())

    def test_retained_estimate_overflow_and_unsupported_roots_fail_closed(self):
        capture, raw, connections, clock = setup_capture()
        capture.capture()
        holder = {"estimate_boundary": "synthetic-known-object"}
        original_size = m.sys.getsizeof
        def size(value):
            return 33554433 if value is holder["estimate_boundary"] else original_size(value)
        with mock.patch.object(m.sys, "getsizeof", size):
            with self.assertRaises(m.SourceError):
                capture.declare_root("oversized_estimate", holder)
        self.assertEqual(capture.state, "failed")
        self.assertFalse(holder)
        self.assertTrue(all(not b for b in raw))
        capture, raw, connections, clock = setup_capture()
        capture.capture()
        with self.assertRaises(m.SourceError):
            capture.declare_root("unsupported", {"opaque": object()})
        self.assertEqual(capture.state, "failed")
        self.assertTrue(all(not b for b in raw))

    def test_trace_profile_first_all_attempt_close_even_when_close_raises(self):
        for status, primary in ((200, "transport_close_failed"), (403, "http_status_rejected")):
            with self.subTest(status=status):
                capture, raw, connections, clock = setup_capture(
                    options={0: {"status": status, "close_failure": True}},
                    connection_options={0: {"close_failure": True}})
                events = []
                with recording_releases(events):
                    capture.capture()
                self.assert_failed(capture, primary)
                self.assert_release_order(events, required=("response_close", "connection_close",
                                                           "frame_release", "supported_backing_release"))
                self.assertEqual(len(connections), 1)
                self.assertEqual(connections[0].response.close_calls, 2)
                self.assertEqual(connections[0].close_calls, 2)
                self.assertEqual(set(capture.attempts[0]["close_failures"]),
                                 {"response_close_failed", "connection_close_failed"})
                self.assertIn("response_close_failed", capture.cleanup_failures)
                self.assertIn("connection_close_failed", capture.cleanup_failures)
                self.assertTrue(all(not b for b in raw))

    def test_getter_consumer_refusal_disables_before_frames_and_actual_backings(self):
        for boundary in ("getter", "consumer"):
            with self.subTest(boundary=boundary):
                capture, raw, connections, clock = setup_capture()
                capture.capture()
                view = capture.original_view(0)
                backing = view.obj
                result = capture.getter(CODES[0])
                payload = result.value
                events = []
                with recording_releases(events):
                    with self.assertRaises(m.SourceError):
                        if boundary == "getter":
                            capture.getter("0000")
                        else:
                            capture.consumer(CODES[0], "2026-10-07")
                self.assert_failed(capture, "symbol_not_admitted" if boundary == "getter" else
                                   "consumer_scope_invalid")
                self.assert_release_order(events, required=("frame_release", "supported_backing_release"))
                labels = [event[0] for event in events]
                self.assertLess(labels.index("frame_release"), labels.index("supported_backing_release"))
                self.assertFalse(payload)
                self.assertFalse(backing)
                self.assertTrue(all(not b for b in raw))
                with self.assertRaises(ValueError):
                    _ = view.obj
                self.assertFalse(capture.cleanup_failures)

    def test_frame_clear_failure_keeps_primary_and_does_not_skip_backing_cleanup(self):
        capture, raw, connections, clock = setup_capture(options={0: {"status": 403}})
        events = []
        with mock.patch.object(m.traceback, "clear_frames", side_effect=RuntimeError("synthetic frame clear failure")), \
             recording_releases(events):
            capture.capture()
        self.assert_failed(capture, "http_status_rejected")
        self.assert_release_order(events, required=("response_close", "connection_close", "frame_release",
                                                   "supported_backing_release"))
        self.assertEqual(capture.cleanup_failures, ("traceback_clear_failed",))
        self.assertEqual(len(connections), 1)
        self.assertEqual(connections[0].response.close_calls, 1)
        self.assertEqual(connections[0].close_calls, 1)
        self.assertTrue(all(not b for b in raw))

    def test_inner_parser_release_and_success_scope_disable_observers_first(self):
        for boundary in ("parser_failure", "success_scope"):
            raw = bodies_for()
            if boundary == "parser_failure":
                raw[0][:] = b"invalid,header\n"
            capture, raw, connections, clock = setup_capture(bodies=raw)
            events = []
            with recording_releases(events):
                with capture:
                    capture.capture()
                    if boundary == "parser_failure":
                        self.assert_failed(capture, "header_invalid")
                    else:
                        self.assertEqual(capture.state, "available")
            self.assert_release_order(events, required=("response_close", "connection_close",
                                                       "parser_view_release", "supported_backing_release"))
            self.assertEqual(capture.state, "released")
            self.assertTrue(all(not b for b in raw))
            self.assertFalse(capture.cleanup_failures)

    def test_audit_output_and_error_chains_finally_release_actual_backings(self):
        for boundary in ("action", "audit", "output"):
            capture, raw, connections, clock = setup_capture()
            aliases, views, backings = {}, [], []
            capture.declare_root("QA_results_diagnostics_aliases", aliases)

            def action(instance):
                view = instance.original_view(0)
                views.append(view); backings.append(view.obj)
                result = instance.getter(CODES[0])
                aliases["result"] = result.value
                aliases["view"] = view
                if boundary == "action":
                    try:
                        raise ValueError(view)
                    except ValueError as cause:
                        raise RuntimeError(view) from cause
                return result

            def fail(result):
                raise RuntimeError("synthetic audit or output failure")

            try:
                m.run_in_ram(capture, action, audit=fail if boundary == "audit" else None,
                             output=fail if boundary == "output" else None)
            except RuntimeError as failure:
                self.assertFalse(failure.args)
                self.assertIsNone(failure.__cause__)
            else:
                self.fail("failure boundary did not fire")
            self.assertEqual(capture.state, "released")
            self.assertFalse(aliases)
            self.assertTrue(all(not b for b in backings + raw))
            for view in views:
                with self.assertRaises(ValueError):
                    _ = view.obj
            self.assertTrue(all(c.close_calls == 1 and c.response.close_calls == 1 for c in connections))
            self.assertFalse(capture.cleanup_failures)

    def test_inactive_error_frame_view_released_before_backing_clear(self):
        capture, raw, connections, clock = setup_capture()
        backing_aliases = []

        def action(instance):
            view = instance.original_view(0)
            backing_aliases.append(view.obj)
            # A view retained only by an inactive exception frame, rather than
            # exception.args, must be destroyed before bytearray.clear().
            hidden = memoryview(view.obj)
            self.assertGreater(len(hidden), 0)
            raise RuntimeError("synthetic inactive-frame-only alias")

        with self.assertRaises(RuntimeError):
            m.run_in_ram(capture, action)
        self.assertTrue(all(not b for b in backing_aliases + raw))
        self.assertFalse(capture.cleanup_failures)

    def test_primary_failure_survives_both_transport_close_failures(self):
        capture, raw, connections, clock = setup_capture(options={0: {"status": 403, "close_failure": True}},
                                                         connection_options={0: {"close_failure": True}})
        capture.capture()
        self.assert_failed(capture, "http_status_rejected")
        self.assertEqual(len(connections), 1)
        self.assertEqual(set(capture.attempts[0]["close_failures"]),
                         {"response_close_failed", "connection_close_failed"})
        self.assertTrue(all(not b for b in raw))

    def test_constructor_budget_rejection_releases_adopted_roots(self):
        raw = bodies_for()
        with mock.patch.object(m, "ROOT_CAP", 1):
            with self.assertRaisesRegex(m.SourceError, "constructor_retained_estimate_cap"):
                setup_capture(bodies=raw)
        self.assertTrue(all(not b for b in raw))

    def test_constructor_unsupported_root_releases_policy_and_supported_siblings_zero_request(self):
        policy = m.ExternalPolicy(EXTERNAL_BYTES, expected_sha256=FIXED_SHA)
        policy_backing, policy_facts = policy.raw, policy.facts
        backing, sibling = bytearray(b"synthetic backing"), bytearray(b"supported sibling")
        view = memoryview(backing)
        holder = {"supported_siblings": [view, backing, sibling], "unsupported": object()}
        requests, adopted, failed_capture, events = [], {}, [], []
        provider = m.SyntheticHTTPSProvider(lambda *args: requests.append(args), roots=holder)
        original_adopt = m.SupportedRoots._adopt_initial
        original_cleanup = m.RAMCapture._cleanup

        def adopt(roots, name, value):
            adopted[name] = value
            return original_adopt(roots, name, value)

        def cleanup(capture, state):
            failed_capture.append(capture)
            return original_cleanup(capture, state)

        with recording_releases(events), \
             mock.patch.object(m.SupportedRoots, "_adopt_initial", adopt), \
             mock.patch.object(m.RAMCapture, "_cleanup", cleanup):
            with self.assertRaisesRegex(m.SourceError, "^unsupported_root_type$") as caught:
                m.RAMCapture(policy, provider=provider)
        self.assert_release_order(events, required=("frame_release", "supported_backing_release"))
        self.assertFalse(requests)
        self.assertEqual(set(adopted), {"capture", "parser", "selected_integrity", "policy_raw", "policy",
                                       "synthetic_provider_0"})
        self.assertTrue(all(not root for root in adopted.values()))
        self.assertTrue(policy.released)
        self.assertFalse(policy_backing)
        self.assertFalse(policy_facts)
        self.assertFalse(holder)
        self.assertFalse(backing)
        self.assertFalse(sibling)
        with self.assertRaises(ValueError):
            _ = view.obj
        self.assertEqual(len(failed_capture), 1)
        capture = failed_capture[0]
        self.assert_failed(capture, "unsupported_root_type")
        self.assertFalse(capture.attempts)
        self.assertEqual(capture.cleanup_failures, ("unsupported_root_type",))
        self.assertEqual(caught.exception.cleanup_failures, ("unsupported_root_type",))

    def test_mutated_unsupported_graph_still_releases_all_supported_siblings(self):
        capture, raw, connections, clock = setup_capture()
        capture.capture()
        view = capture.original_view(0)
        backing = view.obj
        holder = {"view": view}
        capture.declare_root("late_mutation", holder)
        holder["unsupported"] = object()
        capture.close()
        self.assertFalse(backing)
        self.assertFalse(holder)
        self.assertTrue(all(not b for b in raw))
        self.assertIn("unsupported_root_type", capture.cleanup_failures)

    def test_repeated_close_preserves_release_failures_and_forbids_new_roots(self):
        capture, raw, connections, clock = setup_capture(options={0: {"close_failure": True}})
        capture.capture()
        recorded = capture.cleanup_failures
        self.assertIn("response_close_failed", recorded)
        capture.close()
        self.assertEqual(capture.cleanup_failures, recorded)
        with self.assertRaisesRegex(m.SourceError, "root_scope_released"):
            capture.declare_root("after_release", {"new": "data"})
        self.assertFalse(capture.supported_roots())
        self.assertTrue(all(not b for b in raw))

    def test_existing_result_rechecks_mutable_declared_root_estimate(self):
        capture, raw, connections, clock = setup_capture()
        holder = {}
        capture.declare_root("mutable_QA_oracle", holder)
        capture.capture()
        result = capture.getter(CODES[0])
        holder["added_later"] = "synthetic-estimate-growth"
        oversized = holder["added_later"]
        original_size = m.sys.getsizeof
        with mock.patch.object(m.sys, "getsizeof", side_effect=lambda value:
                               33554433 if value is oversized else original_size(value)):
            with self.assertRaises(m.SourceError):
                _ = result.value
        self.assert_failed(capture, "retained_estimate_cap")
        self.assertFalse(holder)
        self.assertTrue(all(not b for b in raw))

    def test_consumption_checks_batch_after_complete_integrity_revalidation(self):
        capture, raw, connections, clock = setup_capture()
        capture.capture()
        original = m.RAMCapture._original

        def delayed_original(instance, ordinal):
            receipt = original(instance, ordinal)
            clock.advance(31)
            return receipt

        with mock.patch.object(m.RAMCapture, "_original", delayed_original):
            with self.assertRaises(m.SourceError):
                capture.profile()
        self.assert_failed(capture, "cooperative_batch_deadline")
        self.assertTrue(all(not b for b in raw))

    def test_daily_total_is_foreign_excluding_foreign_dealer_plus_trust_plus_dealer(self):
        # SOURCE_REGISTRY section 8 (TotalDifference = the three category nets, the foreign
        # dealer is not added again) and section 13 (total adds foreign-excluding-foreign-dealer,
        # trust and dealer only; the foreign dealer is already counted in the dealer category).
        foreign, trust, dealer_self, dealer_hedge, foreign_dealer = 5, 2, 1, 1, 3
        rows = fixture_rows()
        rows[0][1][3:] = numeric_row(foreign, trust, dealer_self, dealer_hedge, foreign_dealer)
        self.assertEqual(rows[0][1][24], str(foreign + trust + dealer_self + dealer_hedge))
        capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
        with capture:
            capture.capture()
            self.assertEqual(capture.state, "available", capture.failure_code)
        for label, total in (("foreign_dealer_double_counted", foreign + foreign_dealer + trust + dealer_self + dealer_hedge),
                             ("foreign_dealer_added_to_three", foreign + trust + dealer_self + dealer_hedge + foreign_dealer),
                             ("trust_omitted", foreign + dealer_self + dealer_hedge)):
            with self.subTest(label=label):
                rows = fixture_rows()
                rows[0][1][3:] = numeric_row(foreign, trust, dealer_self, dealer_hedge, foreign_dealer)
                rows[0][1][24] = str(total)
                capture, raw, connections, clock = setup_capture(bodies=bodies_for(rows))
                capture.capture()
                self.assert_failed(capture, "daily_total_mismatch")


class SealRuntimeBindingTests(unittest.TestCase):
    """Claude runtime binding, caller-supplied actors and binding-hash definitions (RAM only)."""

    def refused(self, code, build, *, env=None):
        with claude_env(**(env or {})):
            with self.assertRaisesRegex(m.SourceError, "^" + code + "$"):
                build()

    def test_review_binding_has_no_defaults_and_product_has_no_hardcoded_identity(self):
        parameters = inspect.signature(m.ReviewBinding).parameters
        self.assertEqual(tuple(parameters), REVIEW_KEYS)
        self.assertTrue(all(p.default is inspect.Parameter.empty for p in parameters.values()))
        with self.assertRaises(TypeError):
            m.ReviewBinding()
        for name in ("GLOBAL_ACTUAL", "OWNER_ACTUAL", "ENGINEER_ACTUAL"):
            self.assertFalse(hasattr(m, name), name)
        text = SOURCE_CODE.decode("utf-8")
        for forbidden in ("01a1240a-495c-7b51-bc4a-cfb13897fcf3", "01a12410-9185-7832-a907-e5fd89f76bae",
                          "01a1241f-43b2-7fe1-8320-26cda9e97274", "CODEX_THREAD_ID", "gpt-6.1-sol", "reasoning"):
            self.assertNotIn(forbidden, text)
        # The only environment access is os.environ.get(<name>) with no default, for the
        # two Claude runtime variables.
        tree = ast.parse(SOURCE_CODE)
        os_attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                         and isinstance(n.value, ast.Name) and n.value.id == "os"}
        self.assertEqual(os_attributes, {"environ"})
        gets = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and isinstance(n.func.value, ast.Attribute)
                and n.func.value.attr == "environ"]
        self.assertEqual(sorted(call.args[0].id for call in gets), ["EFFORT_ENV", "SESSION_ENV"])
        self.assertTrue(all(len(call.args) == 1 and not call.keywords for call in gets))
        self.assertEqual((m.SESSION_ENV, m.EFFORT_ENV), ("CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT"))

    def test_claude_runtime_binding_accepts_reviewed_values_only(self):
        seal = build_seal()
        with claude_env():
            seal.validate(FakeClock())
        self.assertEqual(seal.kind, "native_https")
        for key in ("qa_actual", "global_actual", "owner_actual", "engineer_actual", "model", "effort"):
            self.assertEqual(seal.facts[key], synthetic_fields()[key])
        self.assertNotIn("reasoning", seal.facts)
        # Nothing about model or effort is fixed by the product.
        for model in ("claude-opus-5-5", "claude-fable-5-1", "claude-haiku-5-5", "claude-sonnet-4-5-20250929"):
            for effort in ("low", "medium", "high", "xhigh", "max"):
                with self.subTest(model=model, effort=effort):
                    fields = synthetic_fields(model=model, effort=effort)
                    with claude_env(effort=effort):
                        build_seal(fields).validate(FakeClock())

    def test_runtime_environment_is_required_exact_and_never_defaulted(self):
        seal = build_seal()
        for label, env in (("no_session", dict(session=None)), ("empty_session", dict(session="")),
                           ("no_effort", dict(effort=None)), ("empty_effort", dict(effort="")),
                           ("neither", dict(session=None, effort=None)),
                           ("legacy_codex_only", dict(session=None, effort=None, legacy=QA_ID))):
            with self.subTest(label=label):
                self.refused("runtime_env_missing", lambda: seal.validate(FakeClock()), env=env)
        for label, env in (("other_session", dict(session=ROLE_IDS["engineer_actual"])),
                           ("uppercase_session", dict(session=QA_ID.upper())),
                           ("padded_session", dict(session=QA_ID + " ")),
                           ("legacy_cannot_stand_in", dict(session=ROLE_IDS["owner_actual"], legacy=QA_ID))):
            with self.subTest(label=label):
                self.refused("actual_binding_conflict", lambda: seal.validate(FakeClock()), env=env)
        for effort in ("high", "XHIGH", "xhigh ", "max"):
            with self.subTest(effort=effort):
                self.refused("runtime_effort_conflict", lambda: seal.validate(FakeClock()), env=dict(effort=effort))
        seal.started = True
        self.refused("seal_already_spent", lambda: seal.validate(FakeClock()))
        # Validity window is still enforced.
        for label, window in (("expired", ("2026-10-09T00:00:00.000000Z", "2026-10-10T05:00:00.000000Z")),
                              ("pending", ("2026-10-10T07:00:00.000000Z", "2026-10-11T07:00:00.000000Z"))):
            with self.subTest(label=label):
                late = build_seal(issued=window[0], expires=window[1])
                self.refused("seal_expired_or_pending", lambda: late.validate(FakeClock()))
        self.refused("seal_interval_invalid", lambda: build_seal(issued="2026-10-10T07:00:00.000000Z",
                                                                  expires="2026-10-10T07:00:00.000000Z"))

    def test_actor_independence_and_format_are_validated_not_defaulted(self):
        roles = ("global_actual", "owner_actual", "engineer_actual")
        for role in roles:
            with self.subTest(overlap="qa=" + role):
                self.refused("qa_not_independent", lambda: build_seal(synthetic_fields(**{role: QA_ID})))
        for first, second in (("owner_actual", "engineer_actual"), ("global_actual", "owner_actual"),
                              ("global_actual", "engineer_actual")):
            with self.subTest(overlap=first + "=" + second):
                self.refused("role_actors_not_distinct",
                             lambda: build_seal(synthetic_fields(**{second: ROLE_IDS[first]})))
        self.refused("role_actors_not_distinct", lambda: build_seal(synthetic_fields(
            owner_actual=ROLE_IDS["global_actual"], engineer_actual=ROLE_IDS["global_actual"])))
        # The old Codex actors are ordinary, syntactically valid inputs now: nothing is bound to them.
        build_seal(synthetic_fields(global_actual="01a1240a-495c-7b51-bc4a-cfb13897fcf3",
                                    owner_actual="01a12410-9185-7832-a907-e5fd89f76bae",
                                    engineer_actual="01a1241f-43b2-7fe1-8320-26cda9e97274"))
        for name in ("qa_actual", "runtime_id", "global_actual", "owner_actual", "engineer_actual"):
            for bad in ("", "not-a-uuid", "-" * 36, QA_ID.upper(), QA_ID[:-1], QA_ID + "0", " " + QA_ID, None, 7):
                with self.subTest(name=name, bad=bad):
                    self.refused("runtime_identity_invalid", lambda: build_seal(synthetic_fields(**{name: bad})))

    def test_seal_must_equal_binding_scope_and_old_shape_is_refused(self):
        fields = synthetic_fields()
        for key in REVIEW_KEYS:
            with self.subTest(drop=key):
                self.refused("seal_fields_invalid", lambda: build_seal(fields, drop=(key,)))
            with self.subTest(differs=key):
                self.refused("seal_review_conflict", lambda: build_seal(fields, extra={key: str(fields[key]) + "x"}))
        self.refused("seal_fields_invalid", lambda: build_seal(fields, extra={"reasoning": "xhigh"}))
        self.refused("seal_fields_invalid", lambda: build_seal(fields, drop=("effort",), extra={"reasoning": "xhigh"}))
        self.refused("seal_fields_invalid", lambda: build_seal(fields, extra={"unexpected": 1}))
        for key, value in (("requests", 7), ("issue", 35), ("cwd", "C:/elsewhere"), ("urls", list(URLS[:5])),
                           ("base_sha", "0" * 40), ("policy_sha256", "0" * 64), ("parent_thread_id", "x")):
            with self.subTest(scope=key):
                self.refused("seal_scope_conflict", lambda: build_seal(fields, extra={key: value}))
        # Old Codex-shaped seal: hard-coded model/reasoning, old actors, no owner/engineer keys.
        self.refused("seal_fields_invalid", lambda: build_seal(
            fields, drop=("effort", "owner_actual", "engineer_actual"),
            extra={"model": "gpt-6.1-sol", "reasoning": "xhigh", "global_actual": "01a1240a-495c-7b51-bc4a-cfb13897fcf3"}))
        binding, raw, pin, url = synthetic_seal(fields)
        self.refused("seal_digest_invalid", lambda: m.FinancialStartSeal(
            raw, expected_sha256="0" * 64, receipt_url=url, reviewed=binding))
        self.refused("seal_receipt_invalid", lambda: m.FinancialStartSeal(
            raw, expected_sha256=pin, receipt_url=url + "x", reviewed=binding))
        self.refused("seal_receipt_invalid", lambda: m.FinancialStartSeal(
            raw, expected_sha256=pin, receipt_url="", reviewed=binding))
        self.refused("review_binding_missing", lambda: m.FinancialStartSeal(
            raw, expected_sha256=pin, receipt_url=url, reviewed=dict(fields)))
        binding, raw, pin, url = synthetic_seal(fields, pretty=True)
        self.refused("seal_not_canonical", lambda: m.FinancialStartSeal(
            raw, expected_sha256=pin, receipt_url=url, reviewed=binding))

    def test_model_effort_terminal_candidate_hash_and_command_formats(self):
        cases = (
            ("model_invalid", "model", ("gpt-6.1-sol", "", "Claude-sonnet-5-5", "claude-", "claude-x\n",
                                       "claude-" + "a" * 64, None, 7)),
            ("effort_invalid", "effort", ("", "ultra", "XHIGH", "xhigh ", None, 7)),
            ("runtime_binding_invalid", "terminal_handle", ("", "terminal", "term_", None)),
            ("candidate_invalid", "candidate_sha", ("", "1" * 39, "A" * 40, "g" * 40, None)),
        )
        for code, name, values in cases:
            for bad in values:
                with self.subTest(name=name, bad=bad):
                    self.refused(code, lambda: build_seal(synthetic_fields(**{name: bad})))
        for name in HASH_KEYS:
            for bad in ("", "a" * 63, "A" * 64, "g" * 64, "a" * 65, None, 7):
                with self.subTest(name=name, bad=bad):
                    self.refused("candidate_hash_invalid", lambda: build_seal(synthetic_fields(**{name: bad})))
        prefix = "python.exe -I -B -X utf8 -c "
        limit = 32766
        for label, command in (("empty", ""), ("none", None), ("no_switches", "python.exe -"), ("missing_I", "python.exe -B -X utf8 -c x"),
                               ("switch_order", "python.exe -B -I -X utf8 -c x"), ("no_loader", prefix),
                               ("blank_loader", prefix + "   "), ("one_unit_over", prefix + "x" * (limit - len(prefix) + 1)),
                               ("astral_units_over", prefix + "\U0001F600" * 16384)):
            with self.subTest(command=label):
                self.refused("command_invalid", lambda: build_seal(synthetic_fields(command=command)))
        for label, command in (("exact_limit", prefix + "x" * (limit - len(prefix))),
                               ("astral_in_limit", prefix + "\U0001F600" * 16000)):
            with self.subTest(command=label):
                self.assertLessEqual(len(command) + sum(1 for c in command if ord(c) >= 0x10000), limit)
                build_seal(synthetic_fields(command=command))

    def test_binding_hash_definitions_worked_example(self):
        # Exactly the bytes ReviewBinding documents; core carries nothing derived from the seal.
        loader = "import sys\nprint(\"loader text with spaces\")\n"
        script = "print('payload text')\n"
        core = {"candidate": "2" * 40, "pins": {"policy_sha256": FIXED_SHA, "source": {"sha256": sha(b"source bytes")}}}
        python = "C:\\synthetic\\python.exe"
        argv = [python, "-I", "-B", "-X", "utf8", "-c", loader]
        command = subprocess.list2cmdline(argv)
        self.assertEqual(m._canonical(core), canonical_bytes(core))
        self.assertEqual(canonical_bytes({"b": 1, "a": "\u4e2d"}), '{"a":"\u4e2d","b":1}'.encode("utf-8"))
        fields = synthetic_fields(
            candidate_sha="2" * 40, script_sha256=sha(script.encode("utf-8")), loader_sha256=sha(loader.encode("utf-8")),
            typed_input_sha256=sha(canonical_bytes(core)), command=command)
        binding, raw, pin, url = synthetic_seal(fields)
        for covered in (canonical_bytes(core), script.encode("utf-8"), loader.encode("utf-8"), command.encode("utf-8")):
            self.assertNotIn(pin.encode("ascii"), covered)
            self.assertNotIn(url.encode("ascii"), covered)
        seal = m.FinancialStartSeal(raw, expected_sha256=pin, receipt_url=url, reviewed=binding)
        with claude_env():
            seal.validate(FakeClock())
        self.assertTrue(command.startswith(python + SWITCHES))
        for name in ("source_sha256", "tests_sha256", "script_sha256", "loader_sha256", "typed_input_sha256",
                     "command", "qa_actual", "model", "effort", "CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT"):
            self.assertIn(name, m.ReviewBinding.__doc__ + m.FinancialStartSeal.__doc__)

    def test_capture_gate_uses_live_claude_runtime_and_mocked_transport_only(self):
        for label, env, code in (("no_session", dict(session=None), "runtime_env_missing"),
                                 ("no_effort", dict(effort=None), "runtime_env_missing"),
                                 ("wrong_session", dict(session=ROLE_IDS["owner_actual"]), "actual_binding_conflict"),
                                 ("wrong_effort", dict(effort="high"), "runtime_effort_conflict")):
            with self.subTest(label=label):
                seal = build_seal()
                capture = m.RAMCapture(m.ExternalPolicy(EXTERNAL_BYTES, expected_sha256=FIXED_SHA), seal)
                with claude_env(**env), no_network(), mock.patch.object(http.client, "HTTPSConnection") as native:
                    capture.capture()
                    native.assert_not_called()
                self.assert_gate_failed(capture, code)
                self.assertFalse(capture.attempts)
                self.assertFalse(seal.started)
        # Correct runtime passes the gate, spends exactly one URL and fails closed on the mock
        # response (a MagicMock status is not 200). No socket exists in this process.
        seal = build_seal()
        capture = m.RAMCapture(m.ExternalPolicy(EXTERNAL_BYTES, expected_sha256=FIXED_SHA), seal)
        with claude_env(), no_network(), mock.patch.object(http.client, "HTTPSConnection") as native:
            capture.capture()
            self.assertEqual(native.call_count, 1)
        self.assert_gate_failed(capture, "http_status_rejected")
        self.assertEqual([a["url"] for a in capture.attempts], [URLS[0]])
        self.assertEqual(seal.spent, {URLS[0]})
        self.assertTrue(seal.started)

    def assert_gate_failed(self, capture, code):
        self.assertEqual(capture.state, "failed")
        self.assertEqual(capture.failure_code, code)
        self.assertFalse(capture.originals)
        self.assertFalse(capture.supported_roots())


if __name__ == "__main__":
    GUARD[0] = True
    print("Engineering synthetic RAM only; financial/provider metadata/calendar requests=0; native seals issued=0 (validator-only synthetic seals in RAM); artifacts=0B", flush=True)
    try:
        unittest.main(verbosity=2)
    finally:
        GUARD[0] = False
        print("Selftest process exiting; independent QA and real HTTPS positives remain Unverified; artifact writes=0B", flush=True)

