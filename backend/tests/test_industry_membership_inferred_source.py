"""Standalone synthetic boundary runner for Issue 37's inferred industry-membership source.

Run: python -B -X utf8 backend/tests/test_industry_membership_inferred_source.py
Standard library only; no pytest/conftest, provider GET, DB or test artifacts. The audit
hook installed below forbids sockets, DNS, subprocesses and file writes. The policy v1
literal below is the published canonical text (global role publication, built by an
independent stdlib script, not by product helpers); the tests run against the product's
shipped pins and never override them.
Every corpus below is synthetic: it exercises inference/guard boundaries and proves no
real source, classification truth, FinMind category naming or QA acceptance criterion.
"""
from __future__ import annotations

import ast
import hashlib
import http.client
import importlib.util
import io
import json
import re
import sys
import types
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def _audit_boundary(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname",
                 "subprocess.Popen"):
        raise AssertionError("standalone boundary runner forbids network/process launch")
    if event == "open":
        _, mode, flags = args
        import os
        if (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("standalone boundary runner forbids disk writes")


if not sys.dont_write_bytecode:
    raise RuntimeError("Use -B: the boundary runner does not permit bytecode artifacts")
sys.addaudithook(_audit_boundary)

# Published policy v1 (canonical: sorted keys, compact, UTF-8, no trailing LF); 10,370 bytes.
EXTERNAL_POLICY = '{"acquisition":{"accept":"application/json","accept_encoding":"identity","artifact_bytes":0,"batch_seconds":180,"body_cap_bytes":[4194304,4194304,4194304,2097152],"deadline":"cooperative","hosts":["api.finmindtrade.com","openapi.twse.com.tw","www.tpex.org.tw"],"max_gets":4,"namespace":"issue37-industry-membership-inferred-cutoffs-1005-1006-v1/qa1","order":"FinMind TaiwanStockInfo, TWSE t187ap03_L, TPEx mopsfin_t187ap03_O, FinMind TaiwanStockDelisting","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":50331648,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":12582912,"user_agent":"stock-lab-issue37-local-ram/1"},"acquisition_date":{"earliest":"2026-10-06","latest":"2026-10-31","rule":"D is the Asia/Taipei calendar date when the first GET starts; all four captures must finish on D; each official feed must carry one report date shared by all rows and both must lie in [2026-10-06, D]; otherwise the whole batch is rejected"},"consumer_version":"industry-membership-inferred-cutoffs-lookup-v1","cutoffs":["2026-10-05","2026-10-06"],"first_availability":"unknown","groups":{"code_basis":"Semiconductor=TWSE 24 and TPEx 24; Optoelectronics=TWSE 26 and TPEx 26; Cultural Innovation=TPEx 32; exchange+exact two-digit code mapped by the INDUSTRY_CLASSIFICATION section 3 mapper (no trim, padding or case folding); FinMind Chinese names compared by exact section 2 market names; the UI support pool 3105, 3293, 5274, 5347, 6488, 6510 and 8069 must each sit in a required group in the official snapshot, otherwise the whole batch is rejected before the last GET after all seven are scanned, and the rejection receipt lists every uncovered stock with symbol_index, observed exchange (TWSE, TPEx or absent), raw official industry code (1 to 4 ASCII letters or digits, otherwise the marker <null> or <unrepresentable>) and mapper result (canonical group or unknown)","namespace":"official_industry","required":["Semiconductor","Optoelectronics","Cultural Innovation"],"theme_namespace":"empty set; consumers reject unverified theme groups"},"inference":{"board_transfer":"official listing date after C on one exchange and a retained FinMind row of the other exchange for the same stock_id: TWSE with an older tpex row joins the C set as TPEx identity only when that row\'s date is on or after C and its name maps to the same group; a non-unique, conflicting or reverse-direction transfer rejects the group, and an old name that is not a section 2 name rejects all three groups of that C","d_set_agreement":"per group the official (exchange, symbol) set must equal the FinMind newest-date type twse/tpex set after exact section 2 name mapping, excluding FinMind-only rows explained by TaiwanStockDelisting inside [C, D]; any difference rejects the group","delisting":"TaiwanStockDelisting rows with date in [C, D] and a four-digit stock_id: a stock still in an official feed stays a member unless date equals C; a FinMind-only stock takes its group from its newest twse/tpex row (flag finmind_only_delisted_member); undeterminable industry rejects all three groups for that C; date equal to C rejects the group","identity":"ordinary stock identified by (exchange, four-digit symbol), unique per feed, and never on both exchanges at one cutoff; excludes ETF, TDR 91, managed 80, disabled 18/34, emerging and non-ordinary; innovation board and KY included","new_listing":"official listing date after C is not a member of the C set, equal to C is; a missing, null or invalid listing date rejects the group of that stock; accepted formats are exclusive by character count and separator (8 digits Gregorian yyyyMMdd, 7 digits ROC yyyMMdd, 6 digits ROC yyMMdd, and Y/M/D with a 4-digit Gregorian year and slash only), each must be a real calendar date, and any other shape is unknown without trimming, padding or guessing","outputs":"each lookup carries inferred_from_post_cutoff_snapshot, effective_from=unknown, effective_to=unknown, pit=false, residual risk codes, D, both official report dates and the four source digests"},"instrument_type":"ordinary_stock","limitations":["non-PIT; classification effective and expiry times are unknown","FinMind is the service provider, not an official direct source","snapshot obtained after the cutoffs, so membership is an inference (inferred_from_post_cutoff_snapshot)","TWSE guideline clause 2 and clause 3 item 4 allow off-cycle adjustments; changes between C and D cannot be excluded (off_cycle_reclassification_not_excluded)","TaiwanStockDelisting date semantics (last trading day versus effective date) are undefined"],"market":"TW/TWSE+TPEx","profile":"free_public_local","publication_time":"unknown","residual_risks":["non_pit","classification_effective_dates_unknown","finmind_service_provider_not_official","inferred_from_post_cutoff_snapshot","off_cycle_reclassification_not_excluded","delisting_date_semantics_unknown"],"response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8; anything else rejects","content_type_official":"TWSE/TPEx sources: recorded verbatim in the receipt, not gated; the body is strictly parsed as a UTF-8 JSON array with per-field schema instead","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM","encoding_official":"TWSE/TPEx sources: strict UTF-8; at most one leading UTF-8 BOM is removed and recorded as bom_present; a second BOM or any parse failure is the first failure","extra_fields":"unlisted extra columns are ignored; identity columns (date, stock_id, official code and report date) must be strings, while industry, type and official listing-date columns may be null or absent and then count as unknown or missing; the acquisition receipt counts official rows per exchange for each listing-date format (gregorian8, roc7, roc6, ymd_slash, unknown including null or missing), and the counts of one exchange sum to its row count","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure"},"revision_time":"unknown","rights":{"finmind":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","finmind_attribution":"FinMind: TaiwanStockInfo, TaiwanStockDelisting; local personal noncommercial RAM snapshot only; no raw redistribution/mirror. FinMind is the service provider; this is not an official direct feed and the Chinese industry-name to code mapping is an explicit inference.","official":"Open Government Data License v1 (https://data.gov.tw/license); local RAM use only; originals are not redistributed","tpex_attribution":"財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 上櫃公司基本資料（dataset25036；www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O；issue37-industry-membership-inferred-cutoffs-1005-1006-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；用途限本地 RAM，不再散布原件；2026-10-05與2026-10-06各群組成員為本地推論衍生結果。","twse_attribution":"臺灣證券交易所（Taiwan Stock Exchange, TWSE）[2026] 上市公司基本資料（dataset18419；openapi.twse.com.tw/v1/opendata/t187ap03_L；issue37-industry-membership-inferred-cutoffs-1005-1006-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；用途限本地 RAM，不再散布原件；2026-10-05與2026-10-06各群組成員為本地推論衍生結果。"},"schema":"issue37-industry-membership-source-policy/v1","source_use":"local_personal_noncommercial_process_ram_inferred_cutoff_membership_snapshot","sources":[{"dataset":"TaiwanStockInfo","fields":"date,industry_category,stock_id,stock_name,type","format":"JSON object {msg,status,data}","id":"finmind_taiwan_stock_info","method":"GET","provider":"FinMind","role":"D-day identity, market and Chinese industry name; the newest-date row per stock_id decides","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"},{"dataset":"t187ap03_L","fields":"出表日期,公司代號,產業別,上市日期","format":"JSON array of objects","id":"twse_t187ap03_l","method":"GET","provider":"TWSE","role":"official exchange+two-digit industry code and listing date for TWSE listed companies","url":"https://openapi.twse.com.tw/v1/opendata/t187ap03_L"},{"dataset":"mopsfin_t187ap03_O","fields":"Date,SecuritiesCompanyCode,SecuritiesIndustryCode,DateOfListing","format":"JSON array of objects","id":"tpex_mopsfin_t187ap03_o","method":"GET","provider":"TPEx","role":"official exchange+two-digit industry code and listing date for TPEx listed companies","url":"https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"},{"dataset":"TaiwanStockDelisting","fields":"date,stock_id,stock_name","format":"JSON object {msg,status,data}","id":"finmind_taiwan_stock_delisting","method":"GET","provider":"FinMind","role":"delisted stocks filtered to [C, D] in RAM; no date parameters are sent","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockDelisting"}],"storage":"process_RAM","supported_use":["local_personal_noncommercial","process_ram_snapshot","industry_membership_inferred_cutoff_lookup"],"unsupported":["historical_pit","publication_time","first_availability","revision_history","classification_effective_date","off_cycle_reclassification_exclusion","other_cutoffs","theme_membership","hot_group_v1_score","group_return","actionable_strategy","plan","trading","historical_simulation","raw_disk_storage","db_write","redistribution","mirror","deployment"],"version":"issue37-industry-membership-inferred-cutoffs-1005-1006-v1"}'.encode("utf-8")
EXTERNAL_PIN = "8f6de996077b836a8a6d3129401d70bdf3a044b1cc126c709c5f5aa566fe2f06"

SOURCE = ROOT / "backend/app/industry_membership_inferred_source.py"
spec = importlib.util.spec_from_file_location("issue37_membership_boundary", SOURCE)
source = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = source
spec.loader.exec_module(source)

NAMESPACE = "issue37-industry-membership-inferred-cutoffs-1005-1006-v1/qa1"
C1, C2 = "2026-10-05", "2026-10-06"
SEMI, OPTO, CULT = "Semiconductor", "Optoelectronics", "Cultural Innovation"
BOM = b"\xef\xbb\xbf"
MIB = 1048576
UTC_NOW = datetime(2026, 10, 12, 6, 0, 0, tzinfo=timezone.utc)  # 2026-10-12 14:00 Taipei = D


# --- synthetic world ------------------------------------------------------------------
def twse(code, industry, listing, report="1151012", **extra):
    return {"出表日期": report, "公司代號": code, "公司名稱": "N" + code, "產業別": industry, "上市日期": listing, **extra}


def tpex(code, industry, listing, report="1151012", **extra):
    return {"Date": report, "SecuritiesCompanyCode": code, "CompanyName": "N" + code,
            "SecuritiesIndustryCode": industry, "DateOfListing": listing, **extra}


def info(stock_id, kind, name, day="2026-10-11"):
    return {"date": day, "industry_category": name, "stock_id": stock_id, "stock_name": "S" + stock_id, "type": kind}


def delist(stock_id, day):
    return {"date": day, "stock_id": stock_id, "stock_name": "S" + stock_id}


def world():
    w = types.SimpleNamespace()
    w.twse = [twse("2330", "24", "19940905"), twse("2454", "24", "20010723"), twse("3008", "26", "20020101"),
              twse("2409", "26", "19961105"), twse("1101", "01", "19620209"), twse("2002", "10", "19710101"),
              twse("9103", "91", "20030101")]
    w.tpex = [tpex("3105", "24", "1100304"), tpex("5274", "24", "20170101"), tpex("5347", "24", "2010/05/04"),
              tpex("6488", "24", "1061212"), tpex("6510", "24", "20190101"), tpex("8069", "26", "20110101"),
              tpex("3293", "32", "20150101"), tpex("6999", "24", "20261005"), tpex("6998", "24", "20261006"),
              tpex("6997", "24", "20261008"), tpex("5009", "17", "19990101"), tpex("8888", "80", "20000101"),
              tpex("7000", "", "20000101")]
    w.info = [info("2330", "twse", "半導體業"), info("2454", "twse", "半導體業"), info("3008", "twse", "光電業"),
              info("2409", "twse", "光電業"), info("1101", "twse", "水泥工業"), info("2002", "twse", "鋼鐵工業"),
              info("9103", "twse", "存託憑證"), info("0050", "twse", "ETF"), info("TAIEX", "twse", "Index"),
              info("3105", "tpex", "半導體業"), info("5274", "tpex", "半導體業"), info("5347", "tpex", "半導體業"),
              info("6488", "tpex", "半導體業"), info("6510", "tpex", "半導體業"), info("8069", "tpex", "光電業"),
              info("3293", "tpex", "文化創意業"), info("6999", "tpex", "半導體業"), info("6998", "tpex", "半導體業"),
              info("6997", "tpex", "半導體業"), info("5009", "tpex", "金融業"), info("8888", "tpex", "管理股票"),
              info("7777", "emerging", "半導體業")]
    w.delist = [delist("1234", "2024-03-01"), delist("006208", "2026-10-08")]
    return w


def M(*pairs):
    return tuple(sorted(pairs))


SEMI_C1 = M(("TWSE", "2330"), ("TWSE", "2454"), ("TPEx", "3105"), ("TPEx", "5274"), ("TPEx", "5347"),
            ("TPEx", "6488"), ("TPEx", "6510"), ("TPEx", "6999"))
SEMI_C2 = M(*SEMI_C1, ("TPEx", "6998"))
OPTO_MEMBERS = M(("TWSE", "2409"), ("TWSE", "3008"), ("TPEx", "8069"))
CULT_MEMBERS = M(("TPEx", "3293"))
EXPECTED = {(C1, SEMI): SEMI_C1, (C2, SEMI): SEMI_C2, (C1, OPTO): OPTO_MEMBERS, (C2, OPTO): OPTO_MEMBERS,
            (C1, CULT): CULT_MEMBERS, (C2, CULT): CULT_MEMBERS}


def finmind_body(rows):
    return json.dumps({"msg": "success", "status": 200, "data": rows}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def official_body(rows, bom=False):
    body = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return BOM + body if bom else body


def bodies(w):
    return [finmind_body(w.info), official_body(w.twse), official_body(w.tpex), finmind_body(w.delist)]


# --- fake transport / clocks ----------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class UTC:
    """Sequence of wall-clock readings; the last one repeats."""

    def __init__(self, *moments):
        self.moments, self.calls = list(moments), 0

    def __call__(self):
        value = self.moments[min(self.calls, len(self.moments) - 1)]
        self.calls += 1
        return value


JSON_TYPE = (("Content-Type", "application/json"),)


class Response:
    def __init__(self, body, *, declared=True, eof=True, clock=None, read_delay=0, status=200, headers=None, close_raises=False):
        self.body, self.offset, self.status = body, 0, status
        self.headers = headers if headers is not None else (((("Content-Length", str(len(body))),) if declared else ()) + JSON_TYPE)
        self.closed, self.eof_enabled, self.clock, self.read_delay = False, eof, clock, read_delay
        self.read_calls, self.close_raises, self.close_calls = [], close_raises, 0

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
    def __init__(self, payloads=None, *, response_options=None, clock=None, open_delay=0, fail_at=None):
        self.payloads = payloads if payloads is not None else bodies(world())
        self.response_options = response_options or {}
        self.clock, self.open_delay, self.fail_at = clock, open_delay, fail_at
        self.opens, self.responses = [], []

    def open(self, url, timeout):
        index = len(self.opens)
        self.opens.append((url, timeout))
        if self.clock:
            self.clock.now += self.open_delay
        if index == self.fail_at:
            raise OSError("synthetic transport failure")
        response = Response(self.payloads[index], **self.response_options.get(index, {}))
        self.responses.append(response)
        return response


def build(w=None, *, transport=None, clock=None, ledger=None, now=None, **kwargs):
    transport = transport or Transport(bodies(w or world()))
    clock = clock or Clock()
    snapshot = source.MembershipSource(policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN, transport=transport,
                                       ledger=ledger or source.AttemptLedger(NAMESPACE), clock=clock,
                                       utc_now=now or UTC(UTC_NOW), **kwargs)
    return snapshot, transport, clock


def entries(expected=EXPECTED, rejected=()):
    return tuple((cutoff, group, "rejected" if (cutoff, group) in rejected else "members",
                  () if (cutoff, group) in rejected else members) for (cutoff, group), members in expected.items())


def admission(snapshot, expected=None, **changes):
    inspected = snapshot.inspection()
    counts = inspected["row_counts"]
    value = source.OracleAdmission(
        NAMESPACE, EXTERNAL_PIN, "synthetic-boundary-oracle", "a" * 40, "b" * 64,
        tuple(c.receipt.canonical_sha256 for c in inspected["captures"]), "2026-10-12", "2026-10-12", "2026-10-12",
        counts[0], counts[1], counts[2], counts[3], expected if expected is not None else entries(), True)
    return replace(value, **changes) if changes else value


def pending(w=None, **kwargs):
    snapshot, transport, clock = build(w, **kwargs)
    snapshot.acquire()
    return snapshot, transport, clock


def available(w=None, **kwargs):
    snapshot, transport, clock = pending(w, **kwargs)
    snapshot.admit_independent_verification(admission(snapshot))
    return snapshot, transport, clock


# --- response-shape replay: canned wire bytes -> real http.client -> the real transport -----
class ReplayFile(io.BytesIO):
    pass


class ReplaySocket:
    def __init__(self, wire):
        self.wire, self.timeouts = wire, []

    def makefile(self, mode="rb", *args, **kwargs):
        stream = ReplayFile(self.wire)
        stream.raw = types.SimpleNamespace(_sock=self)
        return stream

    def settimeout(self, value):
        self.timeouts.append(value)


class ReplayTransport:
    def __init__(self, wires):
        self.wires, self.opens, self.requests = list(wires), [], []

    def open(self, url, timeout):
        wire = self.wires[len(self.opens)]
        self.opens.append(url)
        owner = self

        class Connection:
            def __init__(self, host, timeout, context):
                self.host, self.sock = host, ReplaySocket(wire)

            def connect(self):
                pass

            def request(self, method, target, headers):
                owner.requests.append((self.host, method, target, dict(headers)))

            def getresponse(self):
                response = http.client.HTTPResponse(self.sock, method="GET")
                response.begin()
                if response.will_close:
                    self.sock = None
                return response

            def close(self):
                self.sock = None

        with patch.object(source.http.client, "HTTPSConnection", Connection), \
                patch.object(source.ssl, "create_default_context", lambda: object()):
            return source._HTTPSTransport().open(url, timeout)


def chunk_encode(body, size=61):
    out = b""
    for offset in range(0, len(body), size):
        part = body[offset:offset + size]
        out += b"%x\r\n" % len(part) + part + b"\r\n"
    return out + b"0\r\n\r\n"


def raw_http(headers, body=b"", *, status=200, reason="OK", version="1.1"):
    head = f"HTTP/{version} {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers) + "\r\n"
    return head.encode("utf-8") + body


def wire(body, *, framing="length", content_type="application/json", extra=(), status=200, reason="OK",
         content_encoding=None):
    headers = [("Date", "Mon, 12 Oct 2026 06:00:00 GMT"), ("Server", "synthetic"), ("Vary", "Accept-Encoding")]
    if content_type is not None:
        headers.append(("Content-Type", content_type))
    data = body
    if framing == "length":
        headers.append(("Content-Length", str(len(body))))
    elif framing == "chunked":
        headers.append(("Transfer-Encoding", "chunked"))
        data = chunk_encode(body)
    elif framing == "both":
        headers += [("Content-Length", str(len(body))), ("Transfer-Encoding", "chunked")]
        data = chunk_encode(body)
    if content_encoding is not None:
        headers.append(("Content-Encoding", content_encoding))
    return raw_http(headers + list(extra), data, status=status, reason=reason)


def wires(w=None, **options):
    return [wire(body, **options) for body in bodies(w or world())]


def replay(payload_wires, **kwargs):
    transport = ReplayTransport(payload_wires)
    snapshot, _, _ = build(transport=transport, **kwargs)
    return snapshot, transport


FOUR_HEADERS = {"Accept-Encoding": "identity", "Connection": "close",
                "User-Agent": "stock-lab-issue37-local-ram/1", "Accept": "application/json"}
# Independent literals (policy sources[].url), not product constants.
URL_LITERALS = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo",
                "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
                "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockDelisting")
REQUEST_LITERALS = (("api.finmindtrade.com", "GET", "/api/v4/data?dataset=TaiwanStockInfo"),
                    ("openapi.twse.com.tw", "GET", "/v1/opendata/t187ap03_L"),
                    ("www.tpex.org.tw", "GET", "/openapi/v1/mopsfin_t187ap03_O"),
                    ("api.finmindtrade.com", "GET", "/api/v4/data?dataset=TaiwanStockDelisting"))


class Base(unittest.TestCase):
    def assertFailure(self, expected, function, *args, **kwargs):
        with self.assertRaises(source.SourceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def outcomes(self, snapshot):
        return snapshot.inspection()["outcomes"]

    def assertSets(self, snapshot, expected=EXPECTED):
        outcomes = self.outcomes(snapshot)
        for key, members in expected.items():
            self.assertFalse(outcomes[key].rejected, (key, outcomes[key].reasons))
            self.assertEqual(outcomes[key].members, members, key)

    def assertRejected(self, snapshot, cutoff, group, *reasons):
        outcome = self.outcomes(snapshot)[(cutoff, group)]
        self.assertTrue(outcome.rejected, (cutoff, group))
        self.assertEqual(outcome.members, ())
        for reason in reasons:
            self.assertIn(reason, outcome.reasons, (cutoff, group))

    def assertUsable(self, snapshot, *keys):
        for key in keys:
            self.assertFalse(self.outcomes(snapshot)[key].rejected, (key, self.outcomes(snapshot)[key].reasons))


class PolicyTests(Base):
    def test_shipped_pins_equal_the_published_policy_and_nothing_overrides_them(self):
        # The runner never assigns the product constants; these are the values the module ships with.
        self.assertEqual(source.POLICY_SHA256, "8f6de996077b836a8a6d3129401d70bdf3a044b1cc126c709c5f5aa566fe2f06")
        self.assertEqual(source.POLICY_BYTES, 10370)
        self.assertEqual(source.POLICY_SHA256, EXTERNAL_PIN)
        self.assertEqual(source.POLICY_BYTES, len(EXTERNAL_POLICY))
        self.assertEqual(hashlib.sha256(EXTERNAL_POLICY).hexdigest(), source.POLICY_SHA256)
        self.assertEqual(json.loads(EXTERNAL_POLICY)["version"], source.POLICY_VERSION)
        self.assertEqual(source.validate_policy(EXTERNAL_POLICY, EXTERNAL_PIN)["version"], source.POLICY_VERSION)
        # Exact bytes and pin pass; a wrong supplied pin, a different product SHA pin, or a different byte pin rejects.
        flipped = EXTERNAL_PIN[:-1] + ("0" if EXTERNAL_PIN[-1] != "0" else "1")
        self.assertFailure("policy_pin", source.validate_policy, EXTERNAL_POLICY, flipped)
        with patch.object(source, "POLICY_SHA256", flipped):
            self.assertFailure("policy_pin", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN)
        for delta in (-1, 1):
            with self.subTest(bytes_delta=delta), patch.object(source, "POLICY_BYTES", len(EXTERNAL_POLICY) + delta):
                self.assertFailure("policy_canonical_mismatch", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN)
        # Same length, one character different: the shipped SHA pin rejects it.
        changed = EXTERNAL_POLICY.replace(b"local_personal", b"local_Personal", 1)
        self.assertEqual((len(changed), changed == EXTERNAL_POLICY), (len(EXTERNAL_POLICY), False))
        self.assertFailure("policy_canonical_mismatch", source.validate_policy, changed, EXTERNAL_PIN)
        self.assertFailure("policy_pin", source.validate_policy, changed, hashlib.sha256(changed).hexdigest())

    def test_published_policy_validates_with_shipped_pins_and_is_frozen(self):
        policy = source.validate_policy(EXTERNAL_POLICY, EXTERNAL_PIN)
        self.assertEqual(policy["version"], "issue37-industry-membership-inferred-cutoffs-1005-1006-v1")
        self.assertEqual(policy["acquisition"]["namespace"], NAMESPACE)
        self.assertFalse(EXTERNAL_POLICY.endswith(b"\n"))
        with self.assertRaises(TypeError):
            policy["version"] = "x"
        with self.assertRaises(TypeError):
            policy["acquisition"]["max_gets"] = 5
        self.assertIsInstance(policy["sources"], tuple)
        self.assertEqual(tuple(item["url"] for item in policy["sources"]), URL_LITERALS)

    def test_unset_pins_reject_every_policy(self):
        # Stand-in module constants only (restored on exit); the shipped values are asserted above and never edited.
        with patch.object(source, "POLICY_SHA256", ""), patch.object(source, "POLICY_BYTES", 0):
            self.assertFailure("policy_pin_unset", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN)
            self.assertFailure("policy_pin_unset", source.validate_policy, EXTERNAL_POLICY, "")
            self.assertFailure("policy_pin_unset", source.MembershipSource, policy_canonical=EXTERNAL_POLICY,
                               policy_sha256=EXTERNAL_PIN, transport=Transport(), ledger=source.AttemptLedger(NAMESPACE))

    def test_input_pin_canonical_and_shape_rejections(self):
        self.assertFailure("policy_input_type", source.validate_policy, EXTERNAL_POLICY.decode("utf-8"), EXTERNAL_PIN)
        self.assertFailure("policy_input_type", source.validate_policy, EXTERNAL_POLICY, None)
        self.assertFailure("policy_pin", source.validate_policy, EXTERNAL_POLICY, "0" * 64)
        for label, mutated in (("trailing LF", EXTERNAL_POLICY + b"\n"), ("space", EXTERNAL_POLICY.replace(b",", b", ", 1)),
                               ("BOM", BOM + EXTERNAL_POLICY), ("pretty", json.dumps(json.loads(EXTERNAL_POLICY), indent=1, ensure_ascii=False).encode("utf-8")),
                               ("unsorted", json.dumps(dict(reversed(list(json.loads(EXTERNAL_POLICY).items()))), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))):
            with self.subTest(label), patch.object(source, "POLICY_SHA256", hashlib.sha256(mutated).hexdigest()), \
                    patch.object(source, "POLICY_BYTES", len(mutated)):
                with self.assertRaises(source.SourceError):
                    source.validate_policy(mutated, hashlib.sha256(mutated).hexdigest())
        with patch.object(source, "POLICY_BYTES", len(EXTERNAL_POLICY) + 1):
            self.assertFailure("policy_canonical_mismatch", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN)
        for label, text in (("duplicate key", EXTERNAL_POLICY.replace(b'"storage":"process_RAM"', b'"storage":"process_RAM","storage":"x"', 1)),
                            ("nan", EXTERNAL_POLICY.replace(b'"artifact_bytes":0', b'"artifact_bytes":NaN', 1)),
                            ("not json", b"[")):
            with self.subTest(label), patch.object(source, "POLICY_SHA256", hashlib.sha256(text).hexdigest()), \
                    patch.object(source, "POLICY_BYTES", len(text)):
                with self.assertRaises(source.SourceError):
                    source.validate_policy(text, hashlib.sha256(text).hexdigest())

    def repinned(self, document):
        raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return raw, hashlib.sha256(raw).hexdigest()

    def test_every_leaf_type_and_every_key_is_schema_checked_when_repinned(self):
        policy = json.loads(EXTERNAL_POLICY)
        paths = []

        def walk(value, path):
            if isinstance(value, dict):
                for key in value:
                    walk(value[key], path + (key,))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, path + (index,))
            else:
                paths.append(path)
        walk(policy, ())
        self.assertGreater(len(paths), 100)

        def rebuilt(path, mutate):
            document = json.loads(EXTERNAL_POLICY)
            target = document
            for part in path[:-1]:
                target = target[part]
            mutate(target, path[-1])
            raw, pin = self.repinned(document)
            with patch.object(source, "POLICY_SHA256", pin), patch.object(source, "POLICY_BYTES", len(raw)):
                with self.assertRaises(source.SourceError):
                    source.validate_policy(raw, pin)
        for path in paths:
            leaf = policy
            for part in path:
                leaf = leaf[part]
            wrong = "x" if not isinstance(leaf, str) else 1
            rebuilt(path, lambda target, key, wrong=wrong: target.__setitem__(key, wrong))
            if isinstance(path[-1], str):
                rebuilt(path, lambda target, key: target.pop(key))
                rebuilt(path, lambda target, key: target.__setitem__("zz_extra", "x"))

    def test_bound_policy_fields_reject_when_repinned(self):
        cases = (("version", ("version",), "v2"), ("schema", ("schema",), "other/v1"),
                 ("namespace", ("acquisition", "namespace"), NAMESPACE.replace("qa1", "qa2")),
                 ("source_use", ("source_use",), "other"), ("consumer", ("consumer_version",), "other"),
                 ("storage", ("storage",), "disk"), ("profile", ("profile",), "paid"),
                 ("max_gets", ("acquisition", "max_gets"), 5), ("redirects", ("acquisition", "redirects"), 1),
                 ("retries", ("acquisition", "retries"), 1), ("artifact", ("acquisition", "artifact_bytes"), 1),
                 ("stop", ("acquisition", "stop_on_first_failure"), False), ("ua", ("acquisition", "user_agent"), "x"),
                 ("accept", ("acquisition", "accept"), "text/csv"), ("request_seconds", ("acquisition", "request_seconds"), 21),
                 ("batch_seconds", ("acquisition", "batch_seconds"), 181), ("roots", ("acquisition", "retained_roots_estimate_cap_bytes"), 1),
                 ("raw cap", ("acquisition", "total_raw_cap_bytes"), 1), ("earliest", ("acquisition_date", "earliest"), "2026-10-05"),
                 ("latest", ("acquisition_date", "latest"), "2026-11-30"), ("required", ("groups", "required"), ["Semiconductor", "Optoelectronics", "Food"]),
                 ("body caps", ("acquisition", "body_cap_bytes"), [1, 2, 3, 4]), ("hosts", ("acquisition", "hosts"), ["a", "b", "c"]),
                 ("cutoffs", ("cutoffs",), ["2026-10-05", "2026-10-07"]),
                 ("risks", ("residual_risks",), ["a", "b", "c", "d", "e", "f"]))
        for label, path, value in cases:
            with self.subTest(label):
                document = json.loads(EXTERNAL_POLICY)
                target = document
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                raw, pin = self.repinned(document)
                with patch.object(source, "POLICY_SHA256", pin), patch.object(source, "POLICY_BYTES", len(raw)):
                    with self.assertRaises(source.SourceError):
                        source.validate_policy(raw, pin)
        for index in range(4):
            for key in ("url", "id", "method"):
                with self.subTest(source=index, key=key):
                    document = json.loads(EXTERNAL_POLICY)
                    document["sources"][index][key] = "https://example.org/x" if key == "url" else "x"
                    raw, pin = self.repinned(document)
                    with patch.object(source, "POLICY_SHA256", pin), patch.object(source, "POLICY_BYTES", len(raw)):
                        with self.assertRaises(source.SourceError):
                            source.validate_policy(raw, pin)

    def test_transport_fields_shared_with_issue32_v3_are_verbatim(self):
        text = (ROOT / "backend/tests/test_ohlcv_history_source.py").read_text(encoding="utf-8")
        match = re.search(r"^EXTERNAL_POLICY = (b'.*')$", text, re.M)
        self.assertIsNotNone(match)
        reference = json.loads(ast.literal_eval(match.group(1)))
        published = json.loads(EXTERNAL_POLICY)
        self.assertEqual(reference["version"], "issue32-ordinary-nominal-ohlcv-history-seven-cutoffs-v3")
        for key in ("accept", "accept_encoding", "batch_seconds", "deadline", "per_source_max_gets", "redirects",
                    "request_seconds", "retries", "stop_on_first_failure"):
            self.assertEqual(published["acquisition"][key], reference["acquisition"][key], key)
            self.assertIs(type(published["acquisition"][key]), type(reference["acquisition"][key]), key)
        for key in ("content_encoding", "content_type", "duplicate_identity_headers", "encoding", "framing",
                    "set_cookie", "status"):
            self.assertEqual(published["response_shape"][key], reference["response_shape"][key], key)
        for key in ("first_availability", "profile", "publication_time", "revision_time", "storage", "instrument_type", "cutoffs"):
            self.assertEqual(published[key], reference[key], key)
        self.assertEqual(published["rights"]["finmind"], reference["price_source"]["rights"])
        # The approved differences, and nothing else, change in acquisition.
        different = {key for key in published["acquisition"] if key in reference["acquisition"]
                     and published["acquisition"][key] != reference["acquisition"][key]}
        self.assertEqual(different, {"body_cap_bytes", "max_gets", "namespace", "order", "retained_roots_estimate_cap_bytes",
                                     "total_raw_cap_bytes", "user_agent"})
        self.assertEqual(set(published["acquisition"]) - set(reference["acquisition"]), {"artifact_bytes", "hosts"})

    def test_embedded_mapper_equals_taxonomy_and_industry_classification_section_two(self):
        taxonomy_spec = importlib.util.spec_from_file_location("issue37_taxonomy_readonly", ROOT / "backend/app/taxonomy.py")
        taxonomy = importlib.util.module_from_spec(taxonomy_spec)
        sys.modules[taxonomy_spec.name] = taxonomy
        taxonomy_spec.loader.exec_module(taxonomy)
        official = taxonomy.INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE
        self.assertEqual(dict(source._CODE_TO_GROUP["TWSE"]), dict(official["TWSE"]))
        self.assertEqual(dict(source._CODE_TO_GROUP["TPEx"]), dict(official["TPEX"]))
        for exchange in ("TWSE", "TPEx"):
            for code, label in source._CODE_TO_GROUP[exchange].items():
                self.assertEqual(taxonomy.canonical_industry_label(exchange, code), label)
        document = (ROOT / "docs/INDUSTRY_CLASSIFICATION.md").read_text(encoding="utf-8")
        table = document.split("## 2. ", 1)[1].split("## 3. ", 1)[0]
        names = {"TWSE": {}, "TPEx": {}}
        for line in table.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 4 and re.fullmatch(r"[0-9]{2}", cells[0]):
                for exchange, cell in (("TWSE", cells[1]), ("TPEx", cells[2])):
                    if cell not in ("—", "") and not cell.startswith("一般表") and cells[0] not in ("80", "91"):
                        names[exchange][cell] = cells[0]
        self.assertEqual(names["TWSE"], dict(source._NAME_TO_CODE["TWSE"]))
        # TPEx 18/34 are disabled and 80 is special: neither has a name entry; every named code is a mapped ordinary code.
        self.assertEqual(names["TPEx"], dict(source._NAME_TO_CODE["TPEx"]))
        for exchange in ("TWSE", "TPEx"):
            for code in source._NAME_TO_CODE[exchange].values():
                self.assertIn(code, source._CODE_TO_GROUP[exchange])
        # Mapper contract: exact two digits, no trim/pad, no cross-market, specials unknown.
        for exchange, code in (("TWSE", "91"), ("TWSE", "00"), ("TWSE", "07"), ("TWSE", "32"), ("TPEx", "80"), ("TPEx", "18"),
                               ("TPEx", "34"), ("TPEx", "09"), ("TWSE", " 24"), ("TWSE", "24 "), ("TWSE", "024"), ("TWSE", "4"),
                               ("TWSE", ""), ("TWSE", None), ("TWSE", 24), ("OTC", "24")):
            self.assertIsNone(source._group_of_code(exchange, code), (exchange, code))
        self.assertEqual(source._group_of_code("TWSE", "24"), SEMI)
        self.assertEqual(source._group_of_code("TPEx", "32"), CULT)
        self.assertEqual(source._group_of_name("TPEx", "文化創意業"), CULT)
        self.assertIsNone(source._group_of_name("TWSE", "文化創意業"))
        self.assertIsNone(source._group_of_name("TWSE", "半導體"))
        self.assertIsNone(source._group_of_name("TWSE", "半導體業 "))
        self.assertEqual(source._group_of_name("TWSE", "生技醫療業"), "Biotechnology")
        self.assertEqual(source._group_of_name("TPEx", "生技醫療"), "Biotechnology")
        self.assertIsNone(source._group_of_name("TPEx", "生技醫療業"))


def declaration(holder="5d2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d", model="claude-sonnet-5-5", url=None):
    url = url or "https://github.com/YiCheng0608/stock-lab/issues/37#issuecomment-9999999999"
    binding = source.ExecutionBinding(holder, holder, None, model, "xhigh", "a" * 40, "b" * 64, "c" * 64,
                                      "NOAUTH RAM pure guard; no financial execution")
    start = source.FinancialStart("issue37-financial-start-v1", "f0000000-0000-0000-0000-0000000000a1",
                                  ("f0000000-0000-0000-0000-0000000000b1",), ("f0000000-0000-0000-0000-0000000000c1",),
                                  NAMESPACE, EXTERNAL_PIN, url, binding, True, True)
    return start, binding


class FinancialStartTests(Base):
    def test_default_transport_requires_exact_typed_binding_and_new_issue37_seal(self):
        start, binding = declaration()
        source._financial_start(start, binding)
        self.assertFailure("financial_start_required", source._financial_start, None, None)
        self.assertFailure("financial_start_required", source._financial_start, start, None)
        self.assertFailure("financial_binding_mismatch", source._financial_start, start, replace(binding, model="other-model"))
        for label, url in (("old issue", "https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-9999999999"),
                           ("floor", f"https://github.com/YiCheng0608/stock-lab/issues/37#issuecomment-{source.SEAL_COMMENT_FLOOR}"),
                           ("below", "https://github.com/YiCheng0608/stock-lab/issues/37#issuecomment-1"),
                           ("shape", "https://github.com/YiCheng0608/stock-lab/issues/37")):
            with self.subTest(label):
                bad, bad_binding = declaration(url=url)
                self.assertFailure("financial_new_explicit_seal_required", source._financial_start, bad, bad_binding)
        accepted, accepted_binding = declaration(url=f"https://github.com/YiCheng0608/stock-lab/issues/37#issuecomment-{source.SEAL_COMMENT_FLOOR + 1}")
        source._financial_start(accepted, accepted_binding)
        for label, kwargs, code in (
                ("not top level", dict(parent_thread_id="x"), "financial_qa_not_top_level"),
                ("low effort", dict(reasoning_effort="medium"), "financial_qa_identity"),
                ("split ids", dict(holder_session_id="5d2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c7e"), "financial_qa_identity"),
                ("bad candidate", dict(candidate_sha="a" * 39), "financial_candidate"),
                ("bad script", dict(script_sha256="z" * 64), "financial_script_binding")):
            with self.subTest(label):
                broken = replace(binding, **kwargs)
                self.assertFailure(code, source._financial_start, replace(start, binding=broken), broken)
        for label, kwargs, code in (
                ("namespace", dict(namespace=NAMESPACE.replace("qa1", "qa2")), "financial_start_scope"),
                ("pin", dict(policy_sha256="0" * 64), "financial_start_scope"),
                ("version", dict(version="issue32-financial-start-v1"), "financial_start_scope"),
                ("authorized", dict(authorized=False), "financial_start_not_authorized"),
                ("whole batch", dict(whole_batch=False), "financial_start_not_authorized"),
                ("role reuse", dict(implementer_session_ids=("f0000000-0000-0000-0000-0000000000a1",)), "financial_start_scope"),
                ("qa is a role", dict(issuer_thread_id=binding.holder_thread_id), "financial_qa_identity")):
            with self.subTest(label):
                self.assertFailure(code, source._financial_start, replace(start, **kwargs), binding)

    def test_default_transport_refuses_without_start_and_boundary_refuses_with_start(self):
        self.assertFailure("financial_start_required", source.MembershipSource, policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN)
        start, binding = declaration()
        self.assertFailure("financial_start_with_boundary_transport", source.MembershipSource, policy_canonical=EXTERNAL_POLICY,
                           policy_sha256=EXTERNAL_PIN, transport=Transport(), ledger=source.AttemptLedger(NAMESPACE),
                           financial_start=start, execution_binding=binding)
        self.assertFailure("default_clock_required_for_financial", source.MembershipSource, policy_canonical=EXTERNAL_POLICY,
                           policy_sha256=EXTERNAL_PIN, financial_start=start, execution_binding=binding, clock=Clock())
        self.assertFailure("default_clock_required_for_financial", source.MembershipSource, policy_canonical=EXTERNAL_POLICY,
                           policy_sha256=EXTERNAL_PIN, financial_start=start, execution_binding=binding, utc_now=UTC(UTC_NOW))
        self.assertFailure("boundary_ledger_required", source.MembershipSource, policy_canonical=EXTERNAL_POLICY,
                           policy_sha256=EXTERNAL_PIN, transport=Transport())
        self.assertFailure("unsupported_purpose", source.MembershipSource, policy_canonical=EXTERNAL_POLICY,
                           policy_sha256=EXTERNAL_PIN, purpose="historical_pit", transport=Transport(),
                           ledger=source.AttemptLedger(NAMESPACE))
        self.assertFailure("quota_namespace", source.AttemptLedger, NAMESPACE.replace("qa1", "qa2"))
        self.assertFailure("lease_seconds", source.MembershipSource, policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN,
                           transport=Transport(), ledger=source.AttemptLedger(NAMESPACE), lease_seconds=181)


class ParseTests(Base):
    def test_listing_date_formats_are_exclusive_by_length_and_separator(self):
        for raw, iso, label in (("19940905", "1994-09-05", "gregorian8"), ("20240229", "2024-02-29", "gregorian8"),
                                ("1100304", "2021-03-04", "roc7"), ("0990101", "2010-01-01", "roc7"),
                                ("1130229", "2024-02-29", "roc7"),  # ROC 113 = 2024 is a leap year
                                ("990101", "2010-01-01", "roc6"), ("991231", "2010-12-31", "roc6"),
                                ("2010/05/04", "2010-05-04", "ymd_slash"), ("2024/1/2", "2024-01-02", "ymd_slash"),
                                ("2024/12/9", "2024-12-09", "ymd_slash")):
            self.assertEqual(source._listing_date_format(raw), (iso, label), raw)
            self.assertEqual(source._listing_date(raw), iso, raw)
        for raw in ("", " 19940905", "19940905 ", "19940905\n", "1994090", "199409055", "20261340", "2026-13-45", "9999999999",
                    "abc", "1.0", "２０２６１００５", None, 20261005, b"20261005", "99999999", "0000000",
                    "1120229", "20230229", "990229", "2024/2/30", "2024/13/1", "1130431",  # not real calendar dates (ROC 112 = 2023 and ROC 99 = 2010 are not leap years)
                    "113/1/2", "099/01/01", "2024-01-02", "2010-5-4", "2010-05-04",  # 3-digit ROC with separators and '-' separators
                    "2024/01/02 ", "2024/1/2/3", "2024//1/2", "2024/001/02", "2024/1/002", "24/1/2", "2024.1.2", "2024／1／2",
                    "1130101 ", "113-01-01", "99/01/01", "990101 "):
            with self.subTest(raw=raw):
                self.assertEqual(source._listing_date_format(raw), (None, "unknown"), raw)
                self.assertIsNone(source._listing_date(raw), raw)
        self.assertEqual(source.LISTING_FORMATS, ("gregorian8", "roc7", "roc6", "ymd_slash", "unknown"))

    def test_official_rows_schema_duplicates_report_date_and_range(self):
        ok = source._parse_official([twse("2330", "24", "19940905"), twse("1101", "01", "19620209", 公司簡稱="x")], "TWSE", "2026-10-12")
        rows, report = ok
        self.assertEqual(report, "2026-10-12")
        self.assertEqual([(r.exchange, r.symbol, r.group, r.listing) for r in rows],
                         [("TWSE", "2330", SEMI, "1994-09-05"), ("TWSE", "1101", "Cement", "1962-02-09")])
        for label, document, code in (
                ("not list", {"a": 1}, "official_rows"), ("empty", [], "official_rows"), ("row not dict", [1], "official_row_schema"),
                ("missing code", [{"出表日期": "1151012", "產業別": "24", "上市日期": "19940905"}], "official_row_schema"),
                ("missing report", [{"公司代號": "2330", "產業別": "24", "上市日期": "19940905"}], "official_row_schema"),
                ("industry number", [twse("2330", 24, "19940905")], "row_schema_type"),
                ("number code", [{**twse("2330", "24", "19940905"), "公司代號": 2330}], "official_row_schema"),
                ("bad symbol", [twse("23", "24", "19940905")], "official_symbol"),
                ("lowercase symbol", [twse("23a0", "24", "19940905")], "official_symbol"),
                ("duplicate", [twse("2330", "24", "19940905"), twse("2330", "26", "19940905")], "official_duplicate_symbol"),
                ("not uniform", [twse("2330", "24", "19940905"), twse("2454", "24", "20010723", report="1151011")], "official_report_date_not_uniform"),
                ("report gregorian", [twse("2330", "24", "19940905", report="20261012")], "official_report_date"),
                ("report invalid", [twse("2330", "24", "19940905", report="1151032")], "official_report_date"),
                ("report before", [twse("2330", "24", "19940905", report="1151005")], "official_report_date_out_of_range"),
                ("report after D", [twse("2330", "24", "19940905", report="1151013")], "official_report_date_out_of_range")):
            with self.subTest(label):
                self.assertFailure(code, source._parse_official, document, "TWSE", "2026-10-12")
        rows, report = source._parse_official([tpex("3105", "24", "x")], "TPEx", "2026-10-12")
        self.assertIsNone(rows[0].listing)  # invalid listing date is not a parse failure: it rejects the group later
        # Null/absent industry or listing columns are unknown/missing, never a whole-batch failure; a wrong-typed listing is invalid.
        rows, _ = source._parse_official([{**twse("2330", None, None)}, {k: v for k, v in twse("2454", "24", "x").items() if k != "上市日期"},
                                          {**twse("3008", "", 20010723)}, {k: v for k, v in twse("2409", "26", "x").items() if k != "產業別"}],
                                         "TWSE", "2026-10-12")
        self.assertEqual([(r.symbol, r.industry, r.group, r.listing) for r in rows],
                         [("2330", "", None, None), ("2454", "24", SEMI, None), ("3008", "", None, None), ("2409", "", None, None)])
        self.assertFailure("official_row_schema", source._parse_official, [twse("2330", "24", "19940905")], "TPEx", "2026-10-12")

    def test_finmind_documents_status_rows_and_extra_columns(self):
        rows = source._parse_info({"status": 200, "msg": "success", "data": [
            {**info("2330", "twse", "半導體業"), "extra": 1}]}, "2026-10-12")
        self.assertEqual(rows, (source.InfoRow("2026-10-11", "2330", "twse", "半導體業"),))
        nulls = source._parse_info({"status": 200, "msg": "success", "data": [
            {"date": "2026-10-11", "stock_id": "2330", "type": None, "industry_category": None}]}, "2026-10-12")
        self.assertEqual(nulls, (source.InfoRow("2026-10-11", "2330", "", ""),))  # unknown: never a member of any group
        good = {"status": 200, "msg": "success", "data": [info("2330", "twse", "半導體業")]}
        for label, document, code in (
                ("not dict", [], "finmind_document"), ("extra key", {**good, "x": 1}, "finmind_document"),
                ("missing key", {"status": 200, "data": []}, "finmind_document"),
                ("status 400", {**good, "status": 400}, "finmind_document_status"),
                ("status bool", {**good, "status": True}, "finmind_document_status"),
                ("status str", {**good, "status": "200"}, "finmind_document_status"),
                ("msg", {**good, "msg": "ok"}, "finmind_document_status"),
                ("empty data", {**good, "data": []}, "finmind_rows"), ("data not list", {**good, "data": {}}, "finmind_rows")):
            with self.subTest(label):
                self.assertFailure(code, source._parse_info, document, "2026-10-12")
        for label, row, code in (
                ("number id", {**info("2330", "twse", "x"), "stock_id": 2330}, "info_row_schema"),
                ("type number", {**info("2330", "twse", "x"), "type": 1}, "row_schema_type"),
                ("industry list", {**info("2330", "twse", "x"), "industry_category": []}, "row_schema_type"),
                ("missing date", {k: v for k, v in info("2330", "twse", "x").items() if k != "date"}, "info_row_schema"),
                ("bad date", info("2330", "twse", "x", day="2026/10/11"), "info_date"),
                ("future date", info("2330", "twse", "x", day="2026-10-13"), "info_date_after_acquisition"),
                ("empty id", info("", "twse", "x"), "info_stock_id"), ("long id", info("1" * 33, "twse", "x"), "info_stock_id")):
            with self.subTest(label):
                self.assertFailure(code, source._parse_info, {**good, "data": [row]}, "2026-10-12")
        self.assertEqual(source._parse_delisting({**good, "data": [delist("1234", "2024-03-01")]}), (source.DelistRow("2024-03-01", "1234"),))
        for label, row, code in (("bad date", delist("1234", "20240301"), "delisting_date"),
                                 ("number", {**delist("1234", "2024-03-01"), "stock_id": 1234}, "delisting_row_schema"),
                                 ("id missing", {"date": "2024-03-01", "stock_name": "x"}, "delisting_row_schema"),
                                 ("empty id", delist("", "2024-03-01"), "delisting_stock_id")):
            with self.subTest(label):
                self.assertFailure(code, source._parse_delisting, {**good, "data": [row]})
        self.assertEqual(source._parse_delisting({**good, "data": [delist("1234", "2099-01-01")]})[0].date, "2099-01-01")
        self.assertEqual(len(source._parse_delisting({**good, "data": [{"date": "2024-03-01", "stock_id": "1234"}]})), 1)  # stock_name is unused

    @staticmethod
    def uncovered(error):
        """The receipt's per-stock observations as (symbol_index, exchange, code, group) tuples, read key by key."""
        diagnostics = error.diagnostics
        return [tuple(diagnostics[f"uncovered_{item}_{name}"] for name in ("symbol_index", "exchange", "code", "group"))
                for item in range(1, diagnostics["uncovered_count"] + 1)]

    def test_seven_symbols_must_sit_in_required_groups(self):
        w = world()
        official = source._parse_official(w.twse, "TWSE", "2026-10-12")[0] + source._parse_official(w.tpex, "TPEx", "2026-10-12")[0]
        source.check_seven_symbols_covered(official)
        # One stock in another group: index, observed exchange, raw code and mapper result are all recorded.
        moved = tuple(replace(row, industry="27", group="Communications") if row.symbol == "8069" else row for row in official)
        error = self.assertFailure("seven_stock_group_not_required", source.check_seven_symbols_covered, moved)
        self.assertEqual(self.uncovered(error), [(6, "TPEx", "27", "Communications")])
        self.assertEqual(error.diagnostics["uncovered_count"], 1)
        self.assertNotIn("symbol_index", error.diagnostics)
        # One stock absent from both feeds.
        absent = tuple(row for row in official if row.symbol != "3105")
        error = self.assertFailure("seven_stock_group_not_required", source.check_seven_symbols_covered, absent)
        self.assertEqual(self.uncovered(error), [(0, "absent", "<null>", "unknown")])
        # Every uncovered stock is reported, not only the first: absent (0), null industry (2), unmapped code (3) and
        # unrepresentable raw codes (4, 5). Stock 1 is covered by its TPEx row and stock 6 is untouched.
        mixed = []
        for row in official:
            if row.symbol == "3105":
                continue
            if row.symbol == "3293":
                row = source.OfficialRow("TWSE", "3293", "28", "Electronic Parts", "2015-01-01")
            elif row.symbol == "5274":
                row = replace(row, industry="", group=None)
            elif row.symbol == "5347":
                row = replace(row, industry="91", group=None)
            elif row.symbol == "6488":
                row = replace(row, industry="２４", group=None)
            elif row.symbol == "6510":
                row = replace(row, industry="24 DO_NOT_RETAIN_THIS_RAW_TEXT", group=None)
            mixed.append(row)
        mixed = tuple(mixed) + (source.OfficialRow("TPEx", "3293", "32", "Cultural Innovation", "2015-01-01"),)  # TPEx wins: 3293 is covered
        error = self.assertFailure("seven_stock_group_not_required", source.check_seven_symbols_covered, mixed)
        self.assertEqual(self.uncovered(error), [(0, "absent", "<null>", "unknown"), (2, "TPEx", "<null>", "unknown"),
                                                 (3, "TPEx", "91", "unknown"), (4, "TPEx", "<unrepresentable>", "unknown"),
                                                 (5, "TPEx", "<unrepresentable>", "unknown")])
        self.assertNotIn("DO_NOT_RETAIN", repr(dict(error.diagnostics)))
        # With 3293 only on TWSE (a non-required group there), the observed exchange is TWSE.
        twse_only = tuple(row for row in mixed if not (row.exchange == "TPEx" and row.symbol == "3293"))
        error = self.assertFailure("seven_stock_group_not_required", source.check_seven_symbols_covered, twse_only)
        self.assertIn((1, "TWSE", "28", "Electronic Parts"), self.uncovered(error))
        self.assertEqual(error.diagnostics["uncovered_count"], 6)
        # All seven uncovered: the receipt is bounded at seven entries.
        error = self.assertFailure("seven_stock_group_not_required", source.check_seven_symbols_covered, ())
        self.assertEqual(self.uncovered(error), [(index, "absent", "<null>", "unknown") for index in range(7)])
        self.assertEqual(sum(1 for key in error.diagnostics if key.startswith("uncovered_") and key.endswith("_symbol_index")), 7)

    def test_failure_values_whitelists_the_uncovered_receipt(self):
        def values(**diagnostics):
            return source._failure_values(source.SourceError("seven_stock_group_not_required", **diagnostics), "batch")
        good = dict(uncovered_count=2, uncovered_1_symbol_index=0, uncovered_1_exchange="TWSE", uncovered_1_code="2330",
                    uncovered_1_group="Semiconductor", uncovered_2_symbol_index=6, uncovered_2_exchange="absent",
                    uncovered_2_code="<null>", uncovered_2_group="unknown")
        kept = values(**good)
        self.assertEqual({key: value for key, value in kept.items() if key.startswith("uncovered_")}, good)
        self.assertEqual(values(**{key: value for key, value in kept.items() if key != "code"}), kept)  # idempotent
        # Raw strings never pass through: odd codes become the marker, odd groups become unknown.
        for raw in ("ABCDE", "24\n", "２４", " 24", "", "<script>", "半導體業", "x" * 5000, "<unrepresentable>", None, 24, b"24"):
            with self.subTest(code=raw):
                sanitized = values(**{**good, "uncovered_1_code": raw})
                self.assertEqual(sanitized["uncovered_1_code"], "<unrepresentable>")
        for raw in ("Semiconductor ", "semiconductor", "x" * 5000, "", None, 1, "Cultural  Innovation"):
            with self.subTest(group=raw):
                self.assertEqual(values(**{**good, "uncovered_1_group": raw})["uncovered_1_group"], "unknown")
        for raw in ("Communications", "Cultural Innovation", "unknown"):
            self.assertEqual(values(**{**good, "uncovered_1_group": raw})["uncovered_1_group"], raw)
        for raw in ("a", "A1b2", "0", "9999", "<null>"):
            self.assertEqual(values(**{**good, "uncovered_1_code": raw})["uncovered_1_code"], raw)
        # An entry with a bad index or exchange is omitted and counted; the remaining entries are renumbered.
        for field, raw in (("uncovered_1_exchange", "EVIL"), ("uncovered_1_exchange", "twse"), ("uncovered_1_exchange", None),
                           ("uncovered_1_symbol_index", 7), ("uncovered_1_symbol_index", -1), ("uncovered_1_symbol_index", True),
                           ("uncovered_1_symbol_index", "0"), ("uncovered_1_symbol_index", 0.0)):
            with self.subTest(field=field, raw=raw):
                sanitized = values(**{**good, field: raw})
                self.assertEqual((sanitized["uncovered_count"], sanitized["uncovered_omitted"]), (1, 1))
                self.assertEqual((sanitized["uncovered_1_symbol_index"], sanitized["uncovered_1_exchange"]), (6, "absent"))
                self.assertNotIn("uncovered_2_symbol_index", sanitized)
        # A count outside 1..7 drops the whole receipt; stray keys and the retired top-level index never survive.
        for count in (0, 8, -1, True, "2", None, 2.0):
            with self.subTest(count=count):
                sanitized = values(**{**good, "uncovered_count": count})
                self.assertFalse([key for key in sanitized if key.startswith("uncovered_")])
        stray = values(**good, uncovered_9_code="9999", uncovered_omitted=3, symbol_index=3, unknown_key="x")
        self.assertNotIn("uncovered_9_code", stray)
        self.assertNotIn("symbol_index", stray)
        self.assertNotIn("unknown_key", stray)
        self.assertNotIn("uncovered_omitted", stray)
        # Plain failures carry no receipt fields.
        self.assertFalse([key for key in source._failure_values(source.SourceError("http_status", source_index=1), "x") if key.startswith("uncovered_")])


class PipelineTests(Base):
    def test_baseline_two_cutoffs_three_groups_exact_sets(self):
        snapshot, transport, _ = pending()
        self.assertEqual(snapshot.state, "pending")
        self.assertEqual(tuple(url for url, _ in transport.opens), URL_LITERALS)
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3))
        self.assertEqual(snapshot.ledger.unrun, ())
        self.assertSets(snapshot)
        for outcome in self.outcomes(snapshot).values():
            self.assertEqual(outcome.flags, ())
        inspected = snapshot.inspection()
        self.assertEqual(inspected["acquisition_date"], "2026-10-12")
        self.assertEqual(dict(inspected["report_dates"]), {"TWSE": "2026-10-12", "TPEx": "2026-10-12"})
        self.assertEqual(inspected["row_counts"], (len(world().info), 7, 13, 2))
        for capture, payload in zip(inspected["captures"], bodies(world())):
            self.assertEqual(capture.body, payload)
            self.assertEqual(capture.receipt.body_sha256, hashlib.sha256(payload).hexdigest())

    def test_new_listing_equal_after_and_missing_or_invalid_listing_dates(self):
        snapshot, _, _ = pending()
        self.assertNotIn(("TPEx", "6998"), self.outcomes(snapshot)[(C1, SEMI)].members)
        self.assertIn(("TPEx", "6998"), self.outcomes(snapshot)[(C2, SEMI)].members)
        self.assertIn(("TPEx", "6999"), self.outcomes(snapshot)[(C1, SEMI)].members)
        for listing in ("", "2026-13-45", "20261340", "abc", " 20170101"):
            with self.subTest(listing=listing):
                w = world()
                w.tpex[1] = tpex("5274", "24", listing)
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "listing_date_missing_or_invalid")
                self.assertUsable(snapshot, (C1, OPTO), (C2, CULT))
        w = world()
        w.twse[4] = twse("1101", "01", "")  # a stock outside the required groups does not matter
        snapshot, _, _ = pending(w)
        self.assertSets(snapshot)
        w = world()
        w.twse.append(twse("2399", "26", ""))
        w.info.append(info("2399", "twse", "光電業"))
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, OPTO, "listing_date_missing_or_invalid")
        self.assertUsable(snapshot, (C1, SEMI), (C1, CULT))

    def test_delisting_finmind_only_member_flag_and_explained_difference(self):
        w = world()
        w.info.append(info("6001", "tpex", "半導體業"))
        w.delist.append(delist("6001", "2026-10-08"))
        snapshot, _, _ = pending(w)
        self.assertSets(snapshot, {**EXPECTED, (C1, SEMI): M(*SEMI_C1, ("TPEx", "6001")), (C2, SEMI): M(*SEMI_C2, ("TPEx", "6001"))})
        for cutoff in (C1, C2):
            self.assertEqual(self.outcomes(snapshot)[(cutoff, SEMI)].flags, ((("TPEx", "6001"), "finmind_only_delisted_member"),))
        w = world()
        w.info.append(info("2799", "twse", "光電業"))
        w.delist.append(delist("2799", "2026-10-12"))  # date == D is inside [C, D]
        snapshot, _, _ = pending(w)
        self.assertEqual(self.outcomes(snapshot)[(C1, OPTO)].members, M(*OPTO_MEMBERS, ("TWSE", "2799")))

    def test_delisting_date_equal_to_cutoff_rejects_only_that_group_and_cutoff(self):
        w = world()
        w.info.append(info("6001", "tpex", "半導體業"))
        w.delist.append(delist("6001", C1))
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, SEMI, "delisting_date_equals_cutoff")
        # Before C2 the row is outside [C2, D], so FinMind's retained row stays unexplained and the cross-check rejects.
        self.assertRejected(snapshot, C2, SEMI, "cross_source_mismatch")
        self.assertUsable(snapshot, (C1, OPTO), (C1, CULT), (C2, OPTO), (C2, CULT))
        w = world()
        w.info.append(info("6001", "tpex", "半導體業"))
        w.delist.append(delist("6001", C2))
        snapshot, _, _ = pending(w)
        self.assertEqual(self.outcomes(snapshot)[(C1, SEMI)].members, M(*SEMI_C1, ("TPEx", "6001")))
        self.assertRejected(snapshot, C2, SEMI, "delisting_date_equals_cutoff")
        w = world()
        w.delist.append(delist("2330", C1))  # still in the official feed, date == C: semantics unknown
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, SEMI, "delisting_date_equals_cutoff")
        self.assertUsable(snapshot, (C2, SEMI), (C1, OPTO))
        w = world()
        w.delist.append(delist("2330", "2026-10-08"))  # still listed in the official feed after C: stays, unflagged
        snapshot, _, _ = pending(w)
        self.assertSets(snapshot)

    def test_delisting_undeterminable_industry_rejects_all_three_groups_for_that_cutoff(self):
        for label, mutate in (
                ("no info row", lambda w: None),
                ("emerging only", lambda w: w.info.append(info("6001", "emerging", "半導體業"))),
                ("unknown name", lambda w: w.info.append(info("6001", "tpex", "半導體"))),
                ("tie twse vs tpex", lambda w: w.info.extend([info("6001", "tpex", "半導體業"), info("6001", "twse", "半導體業")]))):
            with self.subTest(label):
                w = world()
                mutate(w)
                w.delist.append(delist("6001", "2026-10-08"))
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    for group in (SEMI, OPTO, CULT):
                        self.assertRejected(snapshot, cutoff, group)
        w = world()
        w.delist.append(delist("6001", C1))  # inside [C1, D] but before C2
        snapshot, _, _ = pending(w)
        for group in (SEMI, OPTO, CULT):
            self.assertRejected(snapshot, C1, group, "delisted_industry_undeterminable")
        self.assertSets(snapshot, {key: value for key, value in EXPECTED.items() if key[0] == C2})

    def test_null_or_absent_columns_reject_only_the_affected_group_never_the_batch(self):
        w = world()
        w.tpex[1] = {k: v for k, v in tpex("5274", "24", "x").items() if k != "DateOfListing"}  # listing date absent
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "listing_date_missing_or_invalid")
        self.assertUsable(snapshot, (C1, OPTO), (C2, CULT))
        w = world()
        w.tpex[7] = tpex("6999", None, "20261005")  # official industry null: unknown, so it disagrees with FinMind's Semiconductor row
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, SEMI, "cross_source_mismatch")
        self.assertUsable(snapshot, (C1, OPTO), (C1, CULT))
        w = world()
        w.info[11] = {"date": "2026-10-11", "stock_id": "5347", "stock_name": None, "type": None, "industry_category": None}
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, SEMI, "cross_source_mismatch")
        self.assertUsable(snapshot, (C1, OPTO), (C2, CULT))

    def test_delisting_filters_irrelevant_rows(self):
        w = world()
        w.info.append(info("1999", "tpex", "食品工業"))
        w.delist += [delist("1999", "2026-10-08"),      # known non-required group: no effect
                     delist("006208", "2026-10-07"),    # non-ordinary shape (ETF) is ignored
                     delist("2330A", "2026-10-07"),
                     delist("1234", "2026-10-04"),      # before C1
                     delist("5555", "2026-10-13"),      # after D
                     delist("6001", "2026-10-08"), delist("6001", "2026-10-08")]
        w.info.append(info("6001", "tpex", "食品工業"))
        snapshot, _, _ = pending(w)
        self.assertSets(snapshot)

    def test_delisting_before_cutoff_with_retained_finmind_row_is_a_difference(self):
        w = world()
        w.info.append(info("6001", "tpex", "半導體業"))
        w.delist.append(delist("6001", "2026-10-04"))
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, SEMI, "cross_source_mismatch")
        self.assertRejected(snapshot, C2, SEMI, "cross_source_mismatch")
        self.assertUsable(snapshot, (C1, OPTO), (C2, CULT))

    def transfer(self, **changes):
        w = world()
        w.twse.append(twse("6200", "24", "20261008"))
        w.info += [info("6200", "twse", "半導體業", day="2026-10-11"), info("6200", "tpex", "半導體業", day="2026-10-08")]
        w.delist.append(delist("6200", "2026-10-08"))
        for key, value in changes.items():
            setattr(w, key, value(w) if callable(value) else value)
        return w

    def test_board_transfer_old_tpex_row_joins_cutoff_set_as_tpex_identity(self):
        snapshot, _, _ = pending(self.transfer())
        for cutoff, base in ((C1, SEMI_C1), (C2, SEMI_C2)):
            self.assertEqual(self.outcomes(snapshot)[(cutoff, SEMI)].members, M(*base, ("TPEx", "6200")))
            self.assertEqual(self.outcomes(snapshot)[(cutoff, SEMI)].flags, ((("TPEx", "6200"), "board_transfer_old_tpex_identity"),))
            self.assertNotIn(("TWSE", "6200"), self.outcomes(snapshot)[(cutoff, SEMI)].members)
        w = world()
        w.twse.append(twse("6200", "24", "20261008"))
        w.info.append(info("6200", "twse", "半導體業"))
        snapshot, _, _ = pending(w)
        self.assertSets(snapshot)  # no older tpex row: a plain new listing after the cutoff
        w = self.transfer()
        w.twse[-1] = twse("6200", "24", C1.replace("-", ""))  # listed on C1: a member at C1, not a transfer
        snapshot, _, _ = pending(w)
        self.assertIn(("TWSE", "6200"), self.outcomes(snapshot)[(C1, SEMI)].members)
        self.assertEqual(self.outcomes(snapshot)[(C1, SEMI)].flags, ())

    def test_board_transfer_conflicts_and_ambiguity_reject(self):
        def old_rows(*rows):
            def apply(w):
                kept = [row for row in w.info if not (row["stock_id"] == "6200" and row["type"] == "tpex")]
                return kept + list(rows)
            return apply
        for label, rows, groups, reason in (
                ("other required group", [info("6200", "tpex", "光電業", day="2026-10-08")], (SEMI, OPTO), "board_transfer_industry_conflict"),
                ("non required group", [info("6200", "tpex", "食品工業", day="2026-10-08")], (SEMI,), "board_transfer_industry_conflict"),
                ("same date two names", [info("6200", "tpex", "半導體業", day="2026-10-08"), info("6200", "tpex", "光電業", day="2026-10-08")],
                 (SEMI,), "board_transfer_ambiguous"),
                ("evidence before cutoff", [info("6200", "tpex", "半導體業", day="2026-10-01")], (SEMI,), "board_transfer_evidence_before_cutoff")):
            with self.subTest(label):
                snapshot, _, _ = pending(self.transfer(info=old_rows(*rows)))
                for cutoff in (C1, C2):
                    for group in groups:
                        self.assertRejected(snapshot, cutoff, group, reason)
                self.assertUsable(snapshot, (C1, CULT), (C2, CULT))
        snapshot, _, _ = pending(self.transfer(info=old_rows(info("6200", "tpex", "電子工業", day="2026-10-08"))))
        for cutoff in (C1, C2):
            for group in (SEMI, OPTO, CULT):
                self.assertRejected(snapshot, cutoff, group, "board_transfer_old_industry_unknown")
        # The newest of several tpex rows decides; an older conflicting row is history.
        snapshot, _, _ = pending(self.transfer(info=old_rows(info("6200", "tpex", "光電業", day="2026-10-06"),
                                                             info("6200", "tpex", "半導體業", day="2026-10-08"))))
        self.assertIn(("TPEx", "6200"), self.outcomes(snapshot)[(C1, SEMI)].members)

    def test_the_same_identity_joining_twice_is_a_duplicate(self):
        w = self.transfer()
        w.tpex.append(tpex("6200", "24", "20261001"))  # TPEx still lists it AND the transfer evidence adds the TPEx identity
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "duplicate_identity", "cross_source_mismatch")
        self.assertUsable(snapshot, (C1, OPTO), (C2, CULT))

    def test_board_transfer_reverse_direction_is_not_supported(self):
        w = world()
        w.tpex.append(tpex("6300", "24", "20261008"))
        w.info += [info("6300", "tpex", "半導體業", day="2026-10-11"), info("6300", "twse", "半導體業", day="2026-10-08")]
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "board_transfer_reverse_direction")
        self.assertUsable(snapshot, (C1, OPTO), (C2, CULT))

    def test_cross_source_differences_reject_the_group(self):
        def alter(label, mutate, rejected):
            with self.subTest(label):
                w = world()
                mutate(w)
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    for group in (SEMI, OPTO, CULT):
                        if group in rejected:
                            self.assertRejected(snapshot, cutoff, group, "cross_source_mismatch")
                        else:
                            self.assertUsable(snapshot, (cutoff, group))
        alter("industry differs", lambda w: w.info.__setitem__(0, info("2330", "twse", "光電業")), (SEMI, OPTO))
        alter("finmind row missing", lambda w: w.info.__delitem__(11), (SEMI,))
        alter("finmind only stock", lambda w: w.info.append(info("2999", "twse", "半導體業")), (SEMI,))
        alter("market differs", lambda w: w.info.__setitem__(0, info("2330", "tpex", "半導體業")), (SEMI,))
        alter("unknown finmind name", lambda w: w.info.__setitem__(15, info("3293", "tpex", "文化創意")), (CULT,))
        alter("twse name used on tpex", lambda w: w.info.__setitem__(14, info("8069", "tpex", "光電")), (OPTO,))
        alter("official code unmappable", lambda w: w.tpex.__setitem__(7, tpex("6999", "024", "20261005")), (SEMI,))
        alter("official code padded", lambda w: w.tpex.__setitem__(7, tpex("6999", "24 ", "20261005")), (SEMI,))
        alter("official uses other group", lambda w: w.twse.__setitem__(0, twse("2330", "27", "19940905")), (SEMI,))
        alter("emerging row cannot replace", lambda w: w.info.__setitem__(11, info("5347", "emerging", "半導體業")), (SEMI,))
        alter("older row cannot win", lambda w: w.info.append(info("2330", "twse", "光電業", day="2026-10-01")), ())
        alter("newest row wins", lambda w: (w.info.__setitem__(0, info("2330", "twse", "光電業", day="2026-10-01")), w.info.append(info("2330", "twse", "半導體業", day="2026-10-11"))), ())
        alter("identical duplicates tolerated", lambda w: w.info.append(info("2330", "twse", "半導體業")), ())

    def test_finmind_tie_rows_reject_the_affected_groups(self):
        w = world()
        w.info.append(info("2330", "twse", "光電業"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "finmind_multiple_valid_records")
            self.assertRejected(snapshot, cutoff, OPTO, "finmind_multiple_valid_records")
            self.assertUsable(snapshot, (cutoff, CULT))
        w = world()
        w.info.append(info("1101", "twse", "食品工業"))  # ambiguity outside the required groups does not matter
        snapshot, _, _ = pending(w)
        self.assertSets(snapshot)

    def test_identity_rules(self):
        w = world()
        w.twse.append(twse("2330", "24", "19940905"))
        self.assertFailure("official_duplicate_symbol", pending, w)
        w = world()
        w.tpex.append(tpex("2330", "24", "19940905"))  # the same symbol on both exchanges
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "symbol_on_two_exchanges")
        w = world()
        w.twse[6] = twse("9103", "24", "20030101")  # a TDR-looking code with an ordinary industry is not special-cased by code
        w.info[6] = info("9103", "twse", "半導體業")
        snapshot, _, _ = pending(w)
        self.assertIn(("TWSE", "9103"), self.outcomes(snapshot)[(C1, SEMI)].members)
        # Special / disabled / blank classifications and non-listed boards never become members.
        snapshot, _, _ = pending()
        everything = {m for o in self.outcomes(snapshot).values() for m in o.members}
        for member in (("TWSE", "9103"), ("TPEx", "8888"), ("TPEx", "7000"), ("TPEx", "7777"), ("TWSE", "0050"), ("TWSE", "TAIEX"), ("TWSE", "1101")):
            self.assertNotIn(member, everything)

    @staticmethod
    def excluded(snapshot):
        return {source_name: dict(per_exchange) for source_name, per_exchange in snapshot.inspection()["excluded_non_ordinary"].items()}

    def assertAllSix(self, snapshot):
        """Every cutoff x group is a member set equal to the baseline, with no rejection reason at all."""
        self.assertSets(snapshot)
        for key, outcome in self.outcomes(snapshot).items():
            self.assertEqual((outcome.rejected, outcome.reasons), (False, ()), key)

    def test_non_ordinary_identities_are_excluded_never_rejected(self):
        # Official non-ordinary codes (QA's four examples) in a required group, with FinMind rows for two of them.
        w = world()
        for code in ("2330A", "00631L", "9103X", "23301", "23A0", "A230"):  # the last two have four characters but not four digits
            w.twse.append(twse(code, "24", "19940905"))
        w.info += [info("2330A", "twse", "半導體業"), info("00631L", "twse", "半導體業")]
        snapshot, _, _ = pending(w)
        self.assertAllSix(snapshot)
        # Baseline FinMind TAIEX is a non-ordinary twse row; the two matching rows add two more.
        self.assertEqual(self.excluded(snapshot), {"official": {"TWSE": 6, "TPEx": 0}, "finmind": {"TWSE": 3, "TPEx": 0, "other": 0}})
        # FinMind side: a five-digit id with a required-group industry, conflicting newest rows for it, and other types.
        w = world()
        w.info += [info("00878", "twse", "半導體業"), info("00878", "twse", "光電業"), info("00878B", "tpex", "文化創意業"),
                   info("A230", "tpex", "文化創意業"), info("7777X", "emerging", "半導體業")]
        snapshot, _, _ = pending(w)
        self.assertAllSix(snapshot)
        self.assertEqual(self.excluded(snapshot), {"official": {"TWSE": 0, "TPEx": 0}, "finmind": {"TWSE": 3, "TPEx": 2, "other": 1}})
        # They add no identity, two-exchange, listing-date or board-transfer reason either.
        w = world()
        w.twse += [twse("2330A", "24", "19940905"), twse("2412B", "24", "not a date")]
        w.tpex += [tpex("2330A", "24", "19940905"), tpex("3105B", "32", "20261008")]  # a new listing with an older twse row
        w.info.append(info("3105B", "twse", "半導體業"))
        snapshot, _, _ = pending(w)
        self.assertAllSix(snapshot)
        self.assertEqual(self.excluded(snapshot), {"official": {"TWSE": 2, "TPEx": 2}, "finmind": {"TWSE": 2, "TPEx": 0, "other": 0}})
        # Non-ordinary neighbours do not hide a real difference of the ordinary stock beside them.
        w = world()
        w.twse += [twse("2999", "24", "19940905"), twse("2999A", "24", "19940905")]
        w.info.append(info("2999A", "twse", "半導體業"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "cross_source_mismatch")
            self.assertNotIn("2999A", repr(self.outcomes(snapshot)[(cutoff, SEMI)].reasons))
        self.assertUsable(snapshot, (C1, OPTO), (C2, OPTO), (C1, CULT), (C2, CULT))
        # An ordinary code with a letter-free shape next to its lettered sibling is still a member.
        w = world()
        w.twse.append(twse("2330A", "24", "19940905"))
        snapshot, _, _ = pending(w)
        self.assertIn(("TWSE", "2330"), self.outcomes(snapshot)[(C1, SEMI)].members)
        self.assertNotIn(("TWSE", "2330A"), {m for o in self.outcomes(snapshot).values() for m in o.members})

    def test_excluded_non_ordinary_counts_are_counts_only(self):
        w = world()
        w.twse.append(twse("SECRET", "24", "19940905"))
        w.info.append(info("DO_NOT_RETAIN_THIS_ID", "twse", "半導體業"))
        snapshot, _, _ = pending(w)
        excluded = snapshot.inspection()["excluded_non_ordinary"]
        self.assertEqual(set(excluded), {"official", "finmind"})
        self.assertEqual(set(excluded["official"]), {"TWSE", "TPEx"})
        self.assertEqual(set(excluded["finmind"]), {"TWSE", "TPEx", "other"})
        for per_exchange in excluded.values():
            for count in per_exchange.values():
                self.assertIs(type(count), int)
        self.assertNotIn("SECRET", repr(dict(excluded)))
        self.assertNotIn("DO_NOT_RETAIN", repr(dict(excluded)))
        with self.assertRaises(TypeError):
            excluded["official"]["TWSE"] = 9
        with self.assertRaises(TypeError):
            excluded["extra"] = {}
        # Counts survive a failed batch for the feeds it parsed, and are zero when nothing was parsed.
        w = world()
        w.twse.append(twse("2330A", "24", "19940905"))
        w.tpex[5] = tpex("8069", "27", "20110101")
        snapshot, _, _ = build(w)
        self.assertFailure("seven_stock_group_not_required", snapshot.acquire)
        self.assertEqual(self.excluded(snapshot), {"official": {"TWSE": 1, "TPEx": 0}, "finmind": {"TWSE": 1, "TPEx": 0, "other": 0}})
        snapshot, _, _ = build(transport=Transport(fail_at=0))
        self.assertFailure("transport_or_parse_failure", snapshot.acquire)
        self.assertEqual(self.excluded(snapshot), {"official": {"TWSE": 0, "TPEx": 0}, "finmind": {"TWSE": 0, "TPEx": 0, "other": 0}})

    def test_identity_grammar_still_rejects_the_whole_batch(self):
        # Official code: a string of 4 to 6 uppercase ASCII letters or digits, unique within its feed.
        for label, code in (("3 chars", "233"), ("trailing space", "2330 "), ("leading space", " 2330"), ("fullwidth", "２３３０"),
                            ("hyphen", "23-30"), ("lowercase", "23a0"), ("seven chars", "1234567"), ("empty", ""), ("dot", "2330.")):
            with self.subTest(label):
                self.assertFailure("official_symbol", source._parse_official, [twse(code, "24", "19940905")], "TWSE", "2026-10-12")
                self.assertFailure("official_symbol", source._parse_official, [tpex(code, "24", "19940905")], "TPEx", "2026-10-12")
        self.assertFailure("official_row_schema", source._parse_official, [{**twse("2330", "24", "19940905"), "公司代號": 2330}], "TWSE", "2026-10-12")
        self.assertFailure("official_duplicate_symbol", source._parse_official,
                           [twse("2330A", "24", "19940905"), twse("2330A", "24", "19940905")], "TWSE", "2026-10-12")
        for code in ("2330A", "00631L", "9103X", "23301", "ABCD", "ABCDEF"):
            rows, _ = source._parse_official([twse(code, "24", "19940905")], "TWSE", "2026-10-12")  # parsed here, excluded later
            self.assertEqual([row.symbol for row in rows], [code])
        # Through the whole batch: the third feed is never reached after a malformed official code in the second.
        w = world()
        w.twse.append(twse("233", "24", "19940905"))
        snapshot, transport, _ = build(w)
        error = self.assertFailure("official_symbol", snapshot.acquire)
        self.assertEqual((error.diagnostics["source_index"], snapshot.ledger.attempted, len(transport.opens)), (1, (0, 1), 2))
        # FinMind stock_id: a non-empty string of at most 32 characters; anything longer or empty is a schema failure.
        good = {"status": 200, "msg": "success", "data": [info("2330", "twse", "半導體業")]}
        for label, stock_id, code in (("empty", "", "info_stock_id"), ("33 chars", "9" * 33, "info_stock_id")):
            with self.subTest(label):
                self.assertFailure(code, source._parse_info, {**good, "data": [info(stock_id, "twse", "半導體業")]}, "2026-10-12")
        self.assertEqual(len(source._parse_info({**good, "data": [info("X" * 32, "twse", "半導體業")]}, "2026-10-12")), 1)
        self.assertEqual(source._parse_info({**good, "data": [info("00878", "twse", "半導體業")]}, "2026-10-12")[0].stock_id, "00878")

    def test_innovation_board_and_ky_are_ordinary_members(self):
        w = world()
        w.twse += [twse("2599", "24", "20240102"), twse("4999", "26", "20230505")]
        w.info += [info("2599", "twse", "半導體業"), info("4999", "twse", "光電業")]
        snapshot, _, _ = pending(w)
        self.assertIn(("TWSE", "2599"), self.outcomes(snapshot)[(C1, SEMI)].members)
        self.assertIn(("TWSE", "4999"), self.outcomes(snapshot)[(C2, OPTO)].members)

    def test_seven_stock_pool_not_covered_stops_before_the_delisting_get(self):
        w = world()
        w.tpex[5] = tpex("8069", "27", "20110101")
        w.info[14] = info("8069", "tpex", "通信網路業")
        snapshot, transport, _ = build(w)
        error = self.assertFailure("seven_stock_group_not_required", snapshot.acquire)
        self.assertEqual(ParseTests.uncovered(error), [(6, "TPEx", "27", "Communications")])
        self.assertNotIn("symbol_index", error.diagnostics)
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2))
        self.assertEqual(len(transport.opens), 3)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(len(snapshot.inspection()["captures"]), 3)
        self.assertEqual(dict(snapshot.diagnostics)["uncovered_1_group"], "Communications")

    def test_seven_stock_rejection_reports_every_uncovered_stock_through_the_batch(self):
        w = world()
        w.tpex[0] = tpex("3105", "27", "1100304")  # index 0: other group
        w.tpex[3] = tpex("6488", "24 DO_NOT_RETAIN_THIS_RAW_TEXT", "1061212")  # index 4: unrepresentable raw code
        w.tpex[5] = tpex("8069", None, "20110101")  # index 6: null industry
        del w.tpex[4]  # index 5 (6510) absent from the feed
        snapshot, transport, _ = build(w)
        error = self.assertFailure("seven_stock_group_not_required", snapshot.acquire)
        self.assertEqual(ParseTests.uncovered(error), [(0, "TPEx", "27", "Communications"), (4, "TPEx", "<unrepresentable>", "unknown"),
                                                       (5, "absent", "<null>", "unknown"), (6, "TPEx", "<null>", "unknown")])
        self.assertEqual(dict(snapshot.diagnostics)["uncovered_count"], 4)
        self.assertEqual(dict(snapshot.inspection()["diagnostics"]), dict(snapshot.diagnostics))
        self.assertNotIn("DO_NOT_RETAIN", repr(dict(snapshot.diagnostics)) + repr(error.diagnostics))
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2))  # still rejected before the last GET
        self.assertEqual(len(transport.opens), 3)

    def test_listing_date_format_counts_per_exchange_in_the_receipt(self):
        def counts(snapshot):
            return {exchange: dict(per_format) for exchange, per_format in snapshot.inspection()["listing_date_formats"].items()}
        snapshot, _, _ = pending()
        self.assertEqual(counts(snapshot), {"TWSE": {"gregorian8": 7, "roc7": 0, "roc6": 0, "ymd_slash": 0, "unknown": 0},
                                            "TPEx": {"gregorian8": 10, "roc7": 2, "roc6": 0, "ymd_slash": 1, "unknown": 0}})
        # All five formats on each exchange separately; the rows below sit outside the required groups, so the sets stay.
        w = world()
        w.twse[4] = twse("1101", "01", "620209")  # roc6
        w.twse[5] = twse("2002", "10", None)  # null -> unknown
        w.twse[6] = twse("9103", "91", "2003-01-01")  # '-' separators -> unknown
        w.tpex[10] = tpex("5009", "17", "1999/1/1")  # ymd_slash
        w.tpex[11] = tpex("8888", "80", "113/1/2")  # 3-digit ROC with separators -> unknown
        w.tpex[12] = {key: value for key, value in tpex("7000", "", "x").items() if key != "DateOfListing"}  # missing -> unknown
        snapshot, _, _ = pending(w)
        self.assertSets(snapshot)
        inspected = snapshot.inspection()
        self.assertEqual(counts(snapshot), {"TWSE": {"gregorian8": 4, "roc7": 0, "roc6": 1, "ymd_slash": 0, "unknown": 2},
                                            "TPEx": {"gregorian8": 7, "roc7": 2, "roc6": 0, "ymd_slash": 2, "unknown": 2}})
        for exchange, total in zip(("TWSE", "TPEx"), inspected["row_counts"][1:3]):
            self.assertEqual(sum(inspected["listing_date_formats"][exchange].values()), total)
        self.assertEqual(tuple(inspected["listing_date_formats"]["TWSE"]), source.LISTING_FORMATS)
        with self.assertRaises(TypeError):
            inspected["listing_date_formats"]["TWSE"]["roc7"] = 5
        # A format that rejects a required-group stock is counted as unknown as well.
        w = world()
        w.tpex[1] = tpex("5274", "24", "2017-01-01")
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, SEMI, "listing_date_missing_or_invalid")
        self.assertEqual(counts(snapshot)["TPEx"]["unknown"], 1)
        # The failed batch of the seven-stock rejection keeps the counts of the feeds it parsed.
        w = world()
        w.tpex[6] = tpex("3293", "28", "20150101")
        snapshot, _, _ = build(w)
        self.assertFailure("seven_stock_group_not_required", snapshot.acquire)
        self.assertEqual(sum(counts(snapshot)["TPEx"].values()), 13)


class AcquisitionDateTests(Base):
    def at(self, text):
        return UTC(datetime.fromisoformat(text).replace(tzinfo=timezone.utc))

    def test_acquisition_window_is_enforced_before_any_charge(self):
        for text in ("2026-10-05T06:00:00", "2026-10-06T15:59:00", "2026-11-01T06:00:00", "2026-12-01T06:00:00"):
            with self.subTest(now=text):
                ledger = source.AttemptLedger(NAMESPACE)
                snapshot, transport, _ = build(ledger=ledger, now=self.at(text))
                code = "acquisition_too_close_to_midnight" if text.endswith("15:59:00") else "acquisition_date_out_of_range"
                self.assertFailure(code, snapshot.acquire)
                self.assertEqual((ledger.attempted, transport.opens, snapshot.state), ((), [], "failed"))
                # The quota was never spent: the same ledger still serves a valid batch.
                again, _, _ = build(ledger=ledger, transport=Transport(bodies(world())))
                again.acquire()
                self.assertEqual(again.state, "pending")
        # Boundaries: D=10-06 with report 10-06, D=10-31 are inside; the midnight guard is 210 seconds.
        w = world()
        w.twse = [{**row, "出表日期": "1151006"} for row in w.twse]
        w.tpex = [{**row, "Date": "1151006"} for row in w.tpex]
        w.info = [{**row, "date": "2026-10-06"} for row in w.info]
        snapshot, _, _ = build(w, now=self.at("2026-10-06T00:00:00"))
        snapshot.acquire()
        self.assertEqual(snapshot.inspection()["acquisition_date"], "2026-10-06")
        w = world()
        w.twse = [{**row, "出表日期": "1151031"} for row in w.twse]
        w.tpex = [{**row, "Date": "1151031"} for row in w.tpex]
        snapshot, _, _ = build(w, now=self.at("2026-10-31T00:00:00"))
        snapshot.acquire()
        self.assertEqual(snapshot.inspection()["acquisition_date"], "2026-10-31")
        w = world()
        snapshot, _, _ = build(w, now=self.at("2026-10-12T15:56:30"))
        snapshot.acquire()
        snapshot, _, _ = build(w, now=self.at("2026-10-12T15:56:31"))
        self.assertFailure("acquisition_too_close_to_midnight", snapshot.acquire)

    def test_taipei_date_change_during_the_batch_rejects(self):
        moments = [datetime(2026, 10, 12, 15, 50, tzinfo=timezone.utc)] * 2 + [datetime(2026, 10, 12, 16, 1, tzinfo=timezone.utc)]
        snapshot, transport, _ = build(now=UTC(*moments))
        self.assertFailure("acquisition_date_changed", snapshot.acquire)
        self.assertEqual(snapshot.ledger.attempted, (0,))
        self.assertEqual(len(transport.opens), 1)
        for bad in (None, "2026-10-12", datetime(2026, 10, 12, 6, 0)):
            snapshot, _, _ = build(now=lambda bad=bad: bad)
            self.assertFailure("invalid_utc_clock", snapshot.acquire)
            self.assertEqual(snapshot.ledger.attempted, ())

    def test_report_date_and_info_date_failures_stop_before_later_gets(self):
        cases = (("twse after D", lambda w: setattr(w, "twse", [{**r, "出表日期": "1151013"} for r in w.twse]), "official_report_date_out_of_range", (0, 1)),
                 ("twse before window", lambda w: setattr(w, "twse", [{**r, "出表日期": "1151005"} for r in w.twse]), "official_report_date_out_of_range", (0, 1)),
                 ("tpex before window", lambda w: setattr(w, "tpex", [{**r, "Date": "1150930"} for r in w.tpex]), "official_report_date_out_of_range", (0, 1, 2)),
                 ("tpex not uniform", lambda w: w.tpex.__setitem__(0, tpex("3105", "24", "1100304", report="1151011")), "official_report_date_not_uniform", (0, 1, 2)),
                 ("info after D", lambda w: w.info.__setitem__(0, info("2330", "twse", "半導體業", day="2026-10-13")), "info_date_after_acquisition", (0,)))
        for label, mutate, code, attempted in cases:
            with self.subTest(label):
                w = world()
                mutate(w)
                snapshot, transport, _ = build(w)
                self.assertFailure(code, snapshot.acquire)
                self.assertEqual(snapshot.ledger.attempted, attempted)
                self.assertEqual(len(transport.opens), len(attempted))
                self.assertEqual(snapshot.state, "failed")


class LifecycleTests(Base):
    def test_pending_is_inert_until_every_oracle_assertion_matches(self):
        snapshot, _, _ = pending()
        self.assertFailure("consumer_unavailable", snapshot.lookup, C1, SEMI)
        self.assertFailure("consumer_unavailable", lambda: snapshot.provenance)
        snapshot.admit_independent_verification(admission(snapshot))
        self.assertEqual(snapshot.state, "available")
        for cutoff, group in EXPECTED:
            handle = snapshot.lookup(cutoff, group)
            self.assertEqual(handle.members, EXPECTED[(cutoff, group)])
        self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))

    def test_oracle_assertions_bind_captures_dates_counts_and_every_set(self):
        def fresh():
            snapshot, _, _ = pending()
            return snapshot
        base = admission(fresh())
        cases = (("receipts", dict(receipt_sha256s=base.receipt_sha256s[:3]), "oracle_capture_binding"),
                 ("receipt order", dict(receipt_sha256s=base.receipt_sha256s[::-1]), "oracle_capture_binding"),
                 ("namespace", dict(namespace=NAMESPACE.replace("qa1", "qa2")), "oracle_scope"),
                 ("pin", dict(policy_sha256="0" * 64), "oracle_scope"),
                 ("not independent", dict(independent=False), "oracle_scope"),
                 ("receipt type", dict(receipt_sha256s=("x",) * 4), "oracle_receipt_type"),
                 ("D", dict(acquisition_date="2026-10-13"), "oracle_dates"),
                 ("twse date", dict(twse_report_date="2026-10-11"), "oracle_dates"),
                 ("tpex date", dict(tpex_report_date="2026-10-11"), "oracle_dates"),
                 ("info rows", dict(info_rows=base.info_rows - 1), "oracle_complete_scope"),
                 ("twse rows", dict(twse_rows=0), "oracle_complete_scope"),
                 ("tpex rows", dict(tpex_rows=base.tpex_rows + 1), "oracle_complete_scope"),
                 ("delisting rows", dict(delisting_rows=0), "oracle_complete_scope"),
                 ("type", dict(info_rows="1"), "oracle_type"), ("bool as int", dict(twse_rows=True), "oracle_type"),
                 ("expected list", dict(expected=list(base.expected)), "oracle_type"),
                 ("five entries", dict(expected=base.expected[:5]), "oracle_expected_scope"),
                 ("seven entries", dict(expected=base.expected + ((C1, "Food", "members", ()),)), "oracle_expected_scope"),
                 ("duplicate entry", dict(expected=base.expected[:5] + (base.expected[0],)), "oracle_expected_shape"),
                 ("bad status", dict(expected=(base.expected[0][:2] + ("ok", ()),) + base.expected[1:]), "oracle_expected_shape"),
                 ("rejected with members", dict(expected=(base.expected[0][:2] + ("rejected", base.expected[0][3]),) + base.expected[1:]), "oracle_expected_shape"),
                 ("member shape", dict(expected=(base.expected[0][:3] + ((("TWSE",),),),) + base.expected[1:]), "oracle_expected_shape"))
        for label, changes, code in cases:
            with self.subTest(label):
                snapshot = fresh()
                self.assertFailure(code, snapshot.admit_independent_verification, replace(admission(snapshot), **changes))
                self.assertIn(snapshot.state, ("pending", "failed"))
                self.assertFailure("consumer_unavailable", snapshot.lookup, C1, SEMI)

    def test_a_wrong_set_status_or_member_ends_the_snapshot_without_a_second_try(self):
        wrong_member = {**EXPECTED, (C1, SEMI): M(*SEMI_C1, ("TPEx", "6998"))}
        missing_member = {**EXPECTED, (C2, OPTO): OPTO_MEMBERS[1:]}
        for label, expected in (("extra member", entries(wrong_member)), ("missing member", entries(missing_member)),
                                ("rejected claimed", entries(rejected=((C1, CULT),))),
                                ("exchange swapped", entries({**EXPECTED, (C1, CULT): M(("TWSE", "3293"))}))):
            with self.subTest(label):
                snapshot, _, _ = pending()
                self.assertFailure("oracle_set_mismatch", snapshot.admit_independent_verification, admission(snapshot, expected))
                self.assertEqual(snapshot.state, "failed")
                self.assertEqual(dict(self.outcomes(snapshot)), {})
                self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))
                self.assertFailure("consumer_unavailable", snapshot.lookup, C1, SEMI)
        # A rejected group cannot be claimed as an empty member set: status is compared, not only members.
        w = world()
        w.tpex[1] = tpex("5274", "24", "")
        snapshot, _, _ = pending(w)
        self.assertFailure("oracle_set_mismatch", snapshot.admit_independent_verification,
                           admission(snapshot, entries({**EXPECTED, (C1, SEMI): ()}, rejected=((C2, SEMI),))))
        self.assertEqual(snapshot.state, "failed")
        # An oracle that agrees a group is rejected admits the snapshot, and the rejected group stays refused.
        w = world()
        w.tpex[1] = tpex("5274", "24", "")
        snapshot, _, _ = pending(w)
        expected = entries({key: value for key, value in EXPECTED.items()}, rejected=((C1, SEMI), (C2, SEMI)))
        snapshot.admit_independent_verification(admission(snapshot, expected))
        error = self.assertFailure("group_rejected", snapshot.lookup, C1, SEMI)
        self.assertIn("listing_date_missing_or_invalid", error.diagnostics["reasons"])
        self.assertEqual(snapshot.lookup(C1, OPTO).members, OPTO_MEMBERS)

    def test_lookup_refuses_wrong_cutoff_group_namespace_and_types(self):
        snapshot, _, _ = available()
        for cutoff in ("2026-10-04", "2026-10-07", "2026-10-06 ", "20261006", "", None, 20261006, ("2026-10-06",)):
            with self.subTest(cutoff=cutoff):
                self.assertFailure("unsupported_cutoff", snapshot.lookup, cutoff, SEMI)
        for group in ("Food", "semiconductor", "半導體業", "Semiconductor ", "", None, ["Semiconductor"], "Electronic Parts"):
            with self.subTest(group=group):
                self.assertFailure("unsupported_group", snapshot.lookup, C1, group)
        self.assertFailure("theme_namespace_unverified", snapshot.lookup, C1, SEMI, namespace="theme")
        self.assertFailure("unsupported_namespace", snapshot.lookup, C1, SEMI, namespace="hot_group")
        self.assertFailure("unsupported_namespace", snapshot.lookup, C1, SEMI, namespace=None)
        self.assertFailure("unsupported_namespace", snapshot.lookup, C1, SEMI, namespace="official_industry ")
        self.assertEqual(source.lookup_inferred_membership(snapshot, C1, CULT).members, CULT_MEMBERS)
        self.assertFailure("snapshot_required", source.lookup_inferred_membership, object(), C1, SEMI)

    def test_every_result_carries_the_inference_provenance(self):
        snapshot, transport, _ = available(self_world := world())
        handle = snapshot.lookup(C2, SEMI)
        provenance = handle.provenance
        self.assertIs(provenance["inferred_from_post_cutoff_snapshot"], True)
        self.assertEqual((provenance["effective_from"], provenance["effective_to"]), ("unknown", "unknown"))
        self.assertIs(provenance["pit"], False)
        self.assertEqual(tuple(provenance["residual_risk_codes"]), tuple(json.loads(EXTERNAL_POLICY)["residual_risks"]))
        self.assertIn("off_cycle_reclassification_not_excluded", provenance["residual_risk_codes"])
        self.assertEqual(provenance["acquisition_date"], "2026-10-12")
        self.assertEqual(dict(provenance["official_report_dates"]), {"TWSE": "2026-10-12", "TPEx": "2026-10-12"})
        self.assertEqual(dict(provenance["source_digests"]),
                         {source_id: hashlib.sha256(body).hexdigest() for source_id, body in zip(
                             ("finmind_taiwan_stock_info", "twse_t187ap03_l", "tpex_mopsfin_t187ap03_o", "finmind_taiwan_stock_delisting"), bodies(self_world))})
        self.assertEqual((provenance["cutoff"], provenance["group"], provenance["namespace"], provenance["policy_sha256"]),
                         (C2, SEMI, NAMESPACE, EXTERNAL_PIN))
        self.assertEqual((provenance["publication_time"], provenance["first_availability"], provenance["revision_time"], provenance["storage"]),
                         ("unknown", "unknown", "unknown", "process_RAM"))
        self.assertIn("historical_pit", provenance["unsupported"])
        self.assertIn("theme_membership", provenance["unsupported"])
        self.assertEqual(len(provenance["receipts"]), 4)
        with self.assertRaises(TypeError):
            provenance["pit"] = True
        self.assertEqual(handle.flags, ())

    def test_release_and_expiry_revoke_held_handles_and_clear_roots(self):
        snapshot, _, clock = available()
        handle = snapshot.lookup(C1, SEMI)
        self.assertEqual(len(handle.members), 8)
        snapshot.release()
        self.assertEqual(snapshot.state, "released")
        for read in (lambda: handle.members, lambda: handle.flags, lambda: handle.provenance, lambda: snapshot.provenance):
            self.assertFailure("consumer_unavailable", read)
        self.assertFailure("consumer_unavailable", snapshot.lookup, C1, SEMI)
        self.assertFailure("inspection_unavailable", snapshot.inspection)
        self.assertEqual((snapshot._captures, snapshot._outcomes, snapshot._info, snapshot._twse, snapshot._tpex, snapshot._delisting, snapshot._report_dates),
                         ([], {}, (), (), (), (), {}))
        self.assertEqual(len(snapshot._capture_buffer), 0)
        self.assertIsNone(snapshot._transport)
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3))
        self.assertFailure("snapshot_already_attempted", snapshot.acquire)
        self.assertFailure("quota_spent", lambda: build(ledger=snapshot.ledger)[0].acquire())
        snapshot, _, clock = available()
        handle = snapshot.lookup(C1, SEMI)
        clock.now += 181
        self.assertEqual(snapshot.state, "expired")
        self.assertFailure("consumer_unavailable", lambda: handle.members)
        self.assertEqual(snapshot._outcomes, {})
        snapshot, _, clock = pending()
        clock.now += 181
        self.assertEqual(snapshot.state, "expired")
        self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(pending()[0]))

    def test_failed_batches_keep_originals_for_diagnosis_then_release(self):
        w = world()
        w.tpex = []
        snapshot, transport, _ = build(w)
        self.assertFailure("official_rows", snapshot.acquire)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2))
        self.assertEqual(len(snapshot.inspection()["captures"]), 3)
        self.assertEqual(snapshot.diagnostics["primary_code"], "official_rows")
        self.assertEqual(snapshot.diagnostics["source_index"], 2)
        self.assertFailure("consumer_unavailable", snapshot.lookup, C1, SEMI)
        snapshot.release()
        self.assertEqual(snapshot._captures, [])
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_roots_cap_is_enforced_before_io_and_on_observers(self):
        self.assertFailure("retained_roots_estimate_cap", build, observer_roots=lambda: (bytes(source.ROOTS_CAP + 1),))
        snapshot, transport, _ = build(observer_roots=lambda: ())
        self.assertEqual(transport.opens, [])
        self.assertGreater(snapshot._roots_estimate, 0)
        self.assertFailure("clock_or_roots_type", build, observer_roots=3)
        holder = []
        snapshot, transport, _ = build(observer_roots=lambda: (holder,))
        holder.append(bytes(source.ROOTS_CAP))
        error = self.assertFailure("retained_roots_estimate_cap", snapshot.acquire)
        self.assertGreater(error.diagnostics["estimate_bytes"], source.ROOTS_CAP)
        self.assertEqual(snapshot.state, "failed")
        self.assertLessEqual(len(transport.opens), 1)

    def test_diagnostics_never_retain_messages_or_response_text(self):
        transport = Transport(bodies(world()), response_options={0: dict(close_raises=True)})
        snapshot, _, _ = build(transport=transport)
        error = self.assertFailure("cleanup_failure", snapshot.acquire)
        text = repr(dict(error.diagnostics)) + repr(dict(snapshot.diagnostics))
        self.assertNotIn("DO_NOT_RETAIN_RAW", text)
        self.assertEqual(snapshot.ledger.attempted, (0,))
        self.assertEqual(error.diagnostics["primary_stage"], "capture_response_close")
        # A primary failure survives a cleanup failure and reports it as secondary.
        transport = Transport(bodies(world()), response_options={1: dict(close_raises=True, status=500)})
        snapshot, _, _ = build(transport=transport)
        error = self.assertFailure("http_status", snapshot.acquire)
        self.assertEqual((error.diagnostics["secondary_cleanup_count"], error.diagnostics["secondary_cleanup_1_code"]), (1, "cleanup_failure"))
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))
        self.assertEqual(snapshot.ledger.attempted, (0, 1))


class ResponseShapeTests(Base):
    def test_four_fixed_urls_headers_and_targets_through_the_real_transport(self):
        for options in ({}, dict(framing="chunked", extra=[("Set-Cookie", "synthetic=1; HttpOnly"), ("Vary", "Origin")]), dict(framing="close")):
            with self.subTest(**options):
                snapshot, transport = replay(wires(**options))
                snapshot.acquire()
                self.assertEqual(snapshot.state, "pending")
                self.assertEqual(tuple(transport.opens), URL_LITERALS)
                self.assertEqual(tuple(request[:3] for request in transport.requests), REQUEST_LITERALS)
                for request in transport.requests:
                    self.assertEqual(request[3], FOUR_HEADERS)
                    self.assertTrue({"cookie", "authorization", "proxy-authorization", "x-api-key", "token"}.isdisjoint(k.lower() for k in request[3]))
                self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3))
                snapshot.admit_independent_verification(admission(snapshot))
                self.assertEqual(snapshot.lookup(C1, CULT).members, CULT_MEMBERS)
                snapshot.release()

    def test_official_content_type_is_recorded_not_gated_and_finmind_is_gated(self):
        odd = ["text/html; charset=big5", "application/csv", "", None, "APPLICATION/JSON ; Charset=UTF-8"]
        for content_type in odd:
            with self.subTest(official=content_type):
                payload = wires()
                payload[1] = wire(bodies(world())[1], content_type=content_type)
                payload[2] = wire(bodies(world())[2], content_type=content_type)
                snapshot, _ = replay(payload)
                snapshot.acquire()
                receipts = [c.receipt for c in snapshot.inspection()["captures"]]
                self.assertEqual([r.content_type for r in receipts[1:3]], [(content_type or "").strip()] * 2)
                self.assertEqual(receipts[0].content_type, "application/json")
        for index in (0, 3):
            for content_type in ("text/plain", "application/csv", "", None, "application/json; charset=latin-1", "application/jsonx"):
                with self.subTest(finmind=index, content_type=content_type):
                    payload = wires()
                    payload[index] = wire(bodies(world())[index], content_type=content_type)
                    snapshot, transport = replay(payload)
                    self.assertFailure("content_type", snapshot.acquire)
                    self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))
                    self.assertEqual(len(transport.opens), index + 1)
        for content_type in ("application/json", "application/json; charset=utf-8", "Application/JSON;charset=UTF-8"):
            payload = wires()
            payload[0] = wire(bodies(world())[0], content_type=content_type)
            snapshot, _ = replay(payload)
            snapshot.acquire()

    def test_bom_official_one_leading_bom_recorded_finmind_none(self):
        w = world()
        payload = [wire(finmind_body(w.info)), wire(official_body(w.twse, bom=True)), wire(official_body(w.tpex, bom=True)), wire(finmind_body(w.delist))]
        snapshot, _ = replay(payload)
        snapshot.acquire()
        receipts = [c.receipt for c in snapshot.inspection()["captures"]]
        self.assertEqual([r.bom_present for r in receipts], [False, True, True, False])
        self.assertEqual(receipts[1].body_bytes, len(official_body(w.twse, bom=True)))  # the digest covers the original bytes
        self.assertEqual(receipts[1].body_sha256, hashlib.sha256(official_body(w.twse, bom=True)).hexdigest())
        snapshot.admit_independent_verification(admission(snapshot))
        for index in (0, 3):
            payload = wires(w)
            payload[index] = wire(BOM + bodies(w)[index])
            snapshot, _ = replay(payload)
            self.assertFailure("finmind_bom", snapshot.acquire)
            self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))
        for index in (1, 2):
            payload = wires(w)
            payload[index] = wire(BOM + BOM + bodies(w)[index])
            snapshot, _ = replay(payload)
            self.assertFailure("json_invalid", snapshot.acquire)
            self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))

    def test_body_must_be_strict_utf8_json_with_the_documented_top_level(self):
        w = world()
        cases = (
            (1, b"<html>poison</html>", "json_invalid"), (1, b"", "empty_body"), (1, b"\xff\xfe[]", "utf8_decode"),
            (1, official_body(w.twse)[:-1], "json_invalid"), (1, b'{"a":1}', "official_rows"), (1, b"[]", "official_rows"),
            (1, b'[{"a":1},]', "json_invalid"), (1, b"[NaN]", "nonfinite_json_number"),
            (1, b'[{"x":1,"x":2}]', "duplicate_json_key"),
            (2, b'{"data":[]}', "official_rows"), (2, finmind_body(w.tpex), "official_rows"),
            (0, official_body(w.info), "finmind_document"), (0, b'{"status":200,"msg":"success","data":[]}', "finmind_rows"),
            (0, b'{"status":402,"msg":"payment required","data":[]}', "finmind_document_status"),
            (3, b'{"msg":"success","status":200}', "finmind_document"), (3, b"[]", "finmind_document"))
        for index, body, code in cases:
            with self.subTest(index=index, code=code, body=body[:20]):
                payload = wires(w)
                payload[index] = wire(body)
                snapshot, transport = replay(payload)
                self.assertFailure(code, snapshot.acquire)
                self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))
                self.assertEqual(len(transport.opens), index + 1)
                self.assertEqual(snapshot.state, "failed")

    def test_status_codes_stop_the_batch_and_auth_or_payment_has_its_own_code(self):
        for index in range(4):
            for status, code in ((401, "http_auth_or_payment_stop"), (402, "http_auth_or_payment_stop"), (403, "http_auth_or_payment_stop"),
                                 (404, "http_status"), (429, "http_status"), (500, "http_status"), (301, "http_status"),
                                 (302, "http_status"), (204, "http_status"), (206, "http_status")):
                with self.subTest(index=index, status=status):
                    payload = wires()
                    payload[index] = wire(b"{}", status=status, reason="X", extra=[("Location", "https://example.org/")])
                    snapshot, transport = replay(payload)
                    error = self.assertFailure(code, snapshot.acquire)
                    self.assertEqual(error.diagnostics["source_index"], index)
                    self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))
                    self.assertEqual(len(transport.opens), index + 1)  # no redirect is followed, no later GET

    def test_framing_encoding_and_duplicate_identity_headers(self):
        w = world()
        for index in range(4):
            body = bodies(w)[index]
            for label, replacement, code in (
                    ("gzip", wire(body, content_encoding="gzip"), "content_encoding"),
                    ("br", wire(body, content_encoding="br"), "content_encoding"),
                    ("both", wire(body, framing="both"), "ambiguous_framing"),
                    ("dup length", wire(body, extra=[("Content-Length", str(len(body)))]), "duplicate_framing_header"),
                    ("dup type", wire(body, extra=[("Content-Type", "application/json")]), "duplicate_framing_header"),
                    ("dup encoding", wire(body, extra=[("Content-Encoding", "identity"), ("Content-Encoding", "identity")]), "duplicate_framing_header"),
                    ("signed length", raw_http([("Content-Type", "application/json"), ("Content-Length", "+5")], b"x" * 5), "content_length"),
                    ("short body", raw_http([("Content-Type", "application/json"), ("Content-Length", str(len(body) + 9))], body), None)):
                with self.subTest(index=index, label=label):
                    payload = wires(w)
                    payload[index] = replacement
                    snapshot, transport = replay(payload)
                    with self.assertRaises(source.SourceError) as caught:
                        snapshot.acquire()
                    if code is not None:
                        self.assertEqual(caught.exception.code, code)
                    self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))
                    self.assertEqual(len(transport.opens), index + 1)
        payload = wires(w)
        payload[1] = wire(bodies(w)[1], content_encoding="identity", extra=[("Other", "a"), ("Other", "b")])
        snapshot, _ = replay(payload)
        snapshot.acquire()  # other duplicate headers are accepted and ignored

    def test_per_source_body_caps_and_aggregate_cap(self):
        self.assertEqual(source.BODY_CAPS, (4 * MIB, 4 * MIB, 4 * MIB, 2 * MIB))
        self.assertEqual((source.RAW_CAP, source.ROOTS_CAP), (12 * MIB, 48 * MIB))
        for index, cap in enumerate(source.BODY_CAPS):
            for delta, code in ((1, "declared_body_cap"), (0, None)):
                with self.subTest(index=index, declared=cap + delta - 1 if delta else cap):
                    snapshot, transport, _ = build(transport=Transport(bodies(world())))
                    snapshot._raw_bytes = 0
                    snapshot._state = "acquiring"
                    snapshot._batch_deadline = snapshot._now() + 180
                    snapshot._ledger.begin()
                    for earlier in range(index):
                        snapshot._ledger.charge(earlier)
                    transport.payloads = list(transport.payloads)
                    transport.opens.extend([("skipped", 0)] * index)  # Transport answers by open count
                    transport.response_options = {index: dict(headers=(("Content-Length", str(cap + delta)),) + JSON_TYPE)}
                    transport.payloads[index] = b"x" * 10
                    if code:
                        self.assertFailure(code, snapshot._capture, index)
                    else:
                        # Exactly the cap is declared fine; the short body then fails the length check, not the cap.
                        self.assertFailure("incomplete_content_length", snapshot._capture, index)
        for index, cap in enumerate(source.BODY_CAPS):
            with self.subTest(unknown_length_hits_cap=index):
                snapshot, transport, _ = build(transport=Transport([b"x" * (cap + 1)] * 4, response_options={index: dict(declared=False, eof=False)}))
                snapshot._state = "acquiring"
                snapshot._batch_deadline = snapshot._now() + 180
                snapshot._ledger.begin()
                for earlier in range(index):
                    snapshot._ledger.charge(earlier)
                transport.opens.extend([("skipped", 0)] * index)
                self.assertFailure("body_cap_without_known_eof", snapshot._capture, index)
                self.assertEqual(snapshot._raw_bytes, cap)
        snapshot, transport, _ = build()
        snapshot._state = "acquiring"
        snapshot._batch_deadline = snapshot._now() + 180
        snapshot._ledger.begin()
        snapshot._raw_bytes = source.RAW_CAP - 10
        transport.response_options = {0: dict(headers=(("Content-Length", "11"),) + JSON_TYPE)}
        self.assertFailure("declared_body_cap", snapshot._capture, 0)

    def test_transport_refuses_everything_but_the_four_fixed_urls(self):
        built = []

        class Connection:
            def __init__(self, *args, **kwargs):
                built.append(args)
        for bad in ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice",
                    "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo&data_id=2330",
                    "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo&start_date=2026-10-05",
                    "https://api.finmindtrade.com/api/v4/data",
                    "https://openapi.twse.com.tw/v1/opendata/t187ap03_L?x=1", "https://openapi.twse.com.tw/v1/opendata/t187ap03_O",
                    "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
                    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_L", "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx",
                    "https://www.twse.com.tw/v1/opendata/t187ap03_L", "http://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo",
                    "https://api.finmindtrade.com:443/api/v4/data?dataset=TaiwanStockInfo",
                    "https://user@api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo", "https://example.org/", ""):
            with self.subTest(bad), patch.object(source.http.client, "HTTPSConnection", Connection):
                self.assertFailure("transport_url", source._HTTPSTransport().open, bad, 20)
        self.assertEqual(built, [])

    def test_default_https_budget_boundaries_and_response_cleanup(self):
        clock = Clock()

        class Socket:
            def __init__(self):
                self.timeouts = []

            def settimeout(self, value):
                self.timeouts.append(value)

        class HTTPBody:
            status, length, fp = 200, 0, None

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
                self.host, self.timeout, self.sock, self.closed, self.body = host, timeout, Socket(), False, HTTPBody()

            def connect(self):
                clock.now += 12

            def request(self, method, target, headers):
                clock.now += 3

            def getresponse(self):
                clock.now += delay[0]
                return self.body

            def close(self):
                self.closed = True
        for delay_value in (1, 6):
            delay = [delay_value]
            clock.now = 100
            made = []

            def factory(*args, **kwargs):
                made.append(Connection(*args, **kwargs))
                return made[-1]
            with patch.object(source.time, "monotonic", clock), patch.object(source.http.client, "HTTPSConnection", factory), \
                    patch.object(source.ssl, "create_default_context", lambda: object()):
                if delay_value == 1:
                    source._HTTPSTransport().open(URL_LITERALS[1], 20).close()
                else:
                    self.assertFailure("cooperative_deadline", source._HTTPSTransport().open, URL_LITERALS[1], 20)
            self.assertEqual(made[0].sock.timeouts, [8, 5])
            self.assertTrue(made[0].closed and made[0].body.closed)

    def test_cooperative_request_and_batch_deadlines(self):
        clock = Clock()
        transport = Transport(bodies(world()), clock=clock, open_delay=1, response_options={0: dict(clock=clock, read_delay=21)})
        snapshot, _, _ = build(transport=transport, clock=clock)
        self.assertFailure("cooperative_deadline", snapshot.acquire)
        self.assertEqual(snapshot.ledger.attempted, (0,))
        clock = Clock()
        transport = Transport(bodies(world()), clock=clock, open_delay=50)
        snapshot, _, _ = build(transport=transport, clock=clock)
        self.assertFailure("cooperative_deadline", snapshot.acquire)
        self.assertEqual(snapshot.state, "failed")
        clock = Clock()
        transport = Transport(bodies(world()), clock=clock, open_delay=19)
        snapshot, _, _ = build(transport=transport, clock=clock)
        snapshot.acquire()  # 4 x 19 s stays inside the 180 s batch, each request inside 20 s
        self.assertEqual(snapshot.state, "pending")
        self.assertLessEqual(snapshot._expiry - 100, 180)

    def test_open_failure_is_spent_and_stops_the_batch(self):
        for index in range(4):
            with self.subTest(index=index):
                snapshot, transport, _ = build(transport=Transport(bodies(world()), fail_at=index))
                self.assertFailure("transport_or_parse_failure", snapshot.acquire)
                self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))
                self.assertEqual(snapshot.ledger.unrun, tuple(range(index + 1, 4)))
                self.assertEqual(len(transport.opens), index + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
