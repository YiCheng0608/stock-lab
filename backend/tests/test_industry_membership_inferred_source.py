"""Standalone synthetic boundary runner for Issue 37's inferred industry-membership source.

Run: python -B -X utf8 backend/tests/test_industry_membership_inferred_source.py
Standard library only; no pytest/conftest, provider GET, DB or test artifacts. The audit
hook installed below forbids sockets, DNS, subprocesses and file writes. The policy v2.1
literal below is the published canonical text (global role publication, built by an
independent stdlib script from the published v2 bytes, not by product helpers); the tests
run against the product's shipped pins and never override them.
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
import random
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

# Published policy v2.1 (canonical: sorted keys, compact, UTF-8, no trailing LF); 15,152 bytes.
EXTERNAL_POLICY = '{"acquisition":{"accept":"application/json","accept_encoding":"identity","artifact_bytes":0,"batch_seconds":180,"body_cap_bytes":[4194304,4194304,4194304,2097152],"deadline":"cooperative","hosts":["api.finmindtrade.com","openapi.twse.com.tw","www.tpex.org.tw"],"max_gets":4,"namespace":"issue37-industry-membership-inferred-cutoffs-1005-1006-v2/qa2","order":"FinMind TaiwanStockInfo, TWSE t187ap03_L, TPEx mopsfin_t187ap03_O, FinMind TaiwanStockDelisting","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":50331648,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":12582912,"user_agent":"stock-lab-issue37-local-ram/1"},"acquisition_date":{"earliest":"2026-10-06","latest":"2026-10-31","rule":"D is the Asia/Taipei calendar date when the first GET starts; all four captures must finish on D; each official feed must carry exactly one usable report date (seven digits of a real ROC date) shared by every row that has a usable one, and it must lie in [2026-10-06, D]; a feed without one, with several, or with one outside that range rejects the whole batch; a row without a usable report date is unknown and never a member"},"consumer_version":"industry-membership-inferred-cutoffs-lookup-v1","cutoffs":["2026-10-05","2026-10-06"],"first_availability":"unknown","groups":{"code_basis":"Semiconductor=TWSE 24 and TPEx 24; Optoelectronics=TWSE 26 and TPEx 26; Cultural Innovation=TPEx 32; exchange+exact two-digit code mapped by the INDUSTRY_CLASSIFICATION section 3 mapper (no trim, padding or case folding); FinMind Chinese names compared by exact section 2 market names; the UI support pool 3105, 3293, 5274, 5347, 6488, 6510 and 8069 must each sit in a required group in the official snapshot (a row whose report date is unusable still counts; a code repeated within one feed counts only when every one of its rows does, whatever their order, and the rows of the TPEx feed win over those of the TWSE feed), otherwise the whole batch is rejected before the last GET after all seven are scanned, and the rejection receipt lists every uncovered stock with symbol_index, observed exchange (TWSE, TPEx or absent), raw official industry code (1 to 4 ASCII letters or digits, otherwise the marker <null> or <unrepresentable>) and mapper result (canonical group or unknown)","namespace":"official_industry","required":["Semiconductor","Optoelectronics","Cultural Innovation"],"theme_namespace":"empty set; consumers reject unverified theme groups"},"inference":{"board_transfer":"official listing date after C, or missing or invalid, on one exchange and a retained FinMind row of the other exchange (or a row whose type is unusable) for the same stock_id, evaluated for every ordinary official row whatever its group (including a group outside the required ones, a repeated code and an unusable report date), and the outcome can only reject, never add a member: TWSE with an older tpex row joins the C set as TPEx identity only when it is a member row of a required group, the newest older row\'s date is on or after C and its name maps to the same group; every other outcome rejects, at both cutoffs, the official group when it is required together with every required group reached by the names of the relevant older rows (a conflicting name, tied newest names, a newest date before C, any older row with an unknown date, the reverse direction of a TPEx row with an older twse row, an official listing date that is missing or invalid, or a FinMind row of the stock whose type is unusable), and rejects all three groups of that C when any relevant older name is not a section 2 name of the old row\'s exchange; the relevant older rows are all older rows when a date is unknown, the direction is reverse or the official listing date is unknown, and the rows of the newest date otherwise; a row whose type is unusable may belong to either exchange, so it is relevant in both directions whatever its date and its name is read under both section 2 tables","d_set_agreement":"per group the official (exchange, symbol) set must equal the FinMind newest-date type twse/tpex set after exact section 2 name mapping, excluding FinMind-only rows explained by TaiwanStockDelisting inside [C, D]; any difference rejects the group; a stock whose FinMind rows all carry the same type and industry has a decided value whatever their dates; a stock with differing values and any unknown date has no decided newest row: it is left out of the FinMind set and, at both cutoffs, rejects every required group of its official rows or reached by any of its rows (an unusable type tries both exchanges), while a stock that reaches no required group is ignored; a decided newest row with an unusable type rejects the required groups its industry name reaches under either exchange; an official row with a repeated code or an unusable report date is never a member","delisting":"TaiwanStockDelisting rows with date in [C, D] and a four-digit stock_id: a stock still in an official feed stays a member unless date equals C; a FinMind-only stock takes its group from its newest twse/tpex row (flag finmind_only_delisted_member); undeterminable industry rejects all three groups for that C; date equal to C rejects the group; a row whose date is unknown may equal C and may lie after it, so at both cutoffs an official stock rejects its required group, a FinMind-only stock with a decided group rejects that group when it is required, an undeterminable or tied industry rejects all three groups, and a FinMind-only stock whose newest row is undecided because of unknown dates has an undeterminable industry and rejects all three groups; a date after D is a known date outside every window","identity":"ordinary stock identified by (exchange, four-digit symbol), unique per feed, and never on both exchanges at one cutoff; excludes ETF, TDR 91, managed 80, disabled 18/34, emerging and non-ordinary; a usable code or stock_id that is not exactly four ASCII digits is non-ordinary and is excluded from every set and decision without a reason; an official code outside [0-9A-Z]{4,6}, a null marker or a non-string, and a stock_id that is a non-string, empty, blank, a null marker or over 32 characters, are unusable: the row cannot be attributed to a stock and rejects only the required groups its industry can reach (and, for a FinMind row, its type, trying both exchanges when the type is unusable), all three groups when an official row\'s industry is also unusable or unrecognized, and for a delisting row all three groups of every cutoff whose window may contain its date; a four-digit official code repeated within one feed rejects the required groups of all its rows; innovation board and KY included","new_listing":"official listing date after C is not a member of the C set, equal to C is; a missing, null or invalid listing date rejects the group of that stock; accepted formats are exclusive by character count and separator (8 digits Gregorian yyyyMMdd, 7 digits ROC yyyMMdd, 6 digits ROC yyMMdd, and Y/M/D with a 4-digit Gregorian year and slash only), each must be a real calendar date, and any other shape is unknown without trimming, padding or guessing","outputs":"each lookup carries inferred_from_post_cutoff_snapshot, effective_from=unknown, effective_to=unknown, pit=false, residual risk codes, D, both official report dates and the four source digests"},"instrument_type":"ordinary_stock","limitations":["non-PIT; classification effective and expiry times are unknown","FinMind is the service provider, not an official direct source","snapshot obtained after the cutoffs, so membership is an inference (inferred_from_post_cutoff_snapshot)","TWSE guideline clause 2 and clause 3 item 4 allow off-cycle adjustments; changes between C and D cannot be excluded (off_cycle_reclassification_not_excluded)","TaiwanStockDelisting date semantics (last trading day versus effective date) are undefined"],"market":"TW/TWSE+TPEx","profile":"free_public_local","publication_time":"unknown","residual_risks":["non_pit","classification_effective_dates_unknown","finmind_service_provider_not_official","inferred_from_post_cutoff_snapshot","off_cycle_reclassification_not_excluded","delisting_date_semantics_unknown"],"response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8; anything else rejects","content_type_official":"TWSE/TPEx sources: recorded verbatim in the receipt, not gated; the body is strictly parsed as a UTF-8 JSON array with per-field schema instead","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM","encoding_official":"TWSE/TPEx sources: strict UTF-8; at most one leading UTF-8 BOM is removed and recorded as bom_present; a second BOM or any parse failure is the first failure","extra_fields":"unlisted extra columns are ignored; only structural failures reject the whole batch (a row that is not an object, an outer shape or row-count failure, an official feed without exactly one usable report date in range), while every value-level anomaly is unknown: an unusable identity (non-string, null, absent, empty, blank, a null marker none/null/nan/nat/na/n/a/undefined compared case-insensitively without trimming, a stock_id over 32 characters, or an official code outside [0-9A-Z]{4,6}) cannot be attributed to a stock, a FinMind date that is not a real YYYY-MM-DD date not after D, or an official report date that is not seven-digit ROC, has no date, and an unusable type, industry or listing date is unknown; bare NaN and Infinity literals are non-string values; before any validation every row of each source is counted per value form of its identity and date columns (inspection census: integers only, per source rows and rows_not_object and, per field, the counts of one mutually exclusive class vocabulary that sum to the object rows), the census of every source parsed so far is copied into failure diagnostics as enumerated census_<source>_<field>_<class> integer keys, and the acquisition receipt counts official rows per exchange for each listing-date format (gregorian8, roc7, roc6, ymd_slash, unknown including null or missing), and the counts of one exchange sum to its row count; inspection also reports the resolution counts of the ordinary FinMind stocks (single_row, same_value, newest_unique, newest_tied, date_unresolved_related, date_unresolved_unrelated) and, once inference has completed, for every cutoff and group the D-set difference counts official_only, finmind_only_explained and finmind_only_unexplained","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure"},"revision_time":"unknown","rights":{"finmind":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","finmind_attribution":"FinMind: TaiwanStockInfo, TaiwanStockDelisting; local personal noncommercial RAM snapshot only; no raw redistribution/mirror. FinMind is the service provider; this is not an official direct feed and the Chinese industry-name to code mapping is an explicit inference.","official":"Open Government Data License v1 (https://data.gov.tw/license); local RAM use only; originals are not redistributed","tpex_attribution":"財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 上櫃公司基本資料（dataset25036；www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O；issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；用途限本地 RAM，不再散布原件；2026-10-05與2026-10-06各群組成員為本地推論衍生結果。","twse_attribution":"臺灣證券交易所（Taiwan Stock Exchange, TWSE）[2026] 上市公司基本資料（dataset18419；openapi.twse.com.tw/v1/opendata/t187ap03_L；issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；用途限本地 RAM，不再散布原件；2026-10-05與2026-10-06各群組成員為本地推論衍生結果。"},"schema":"issue37-industry-membership-source-policy/v1","source_use":"local_personal_noncommercial_process_ram_inferred_cutoff_membership_snapshot","sources":[{"dataset":"TaiwanStockInfo","fields":"date,industry_category,stock_id,stock_name,type","format":"JSON object {msg,status,data}","id":"finmind_taiwan_stock_info","method":"GET","provider":"FinMind","role":"D-day identity, market and Chinese industry name; the newest-date row per stock_id decides unless all rows of that stock agree; a row whose date is not a real YYYY-MM-DD date not after D has no date","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"},{"dataset":"t187ap03_L","fields":"出表日期,公司代號,產業別,上市日期","format":"JSON array of objects","id":"twse_t187ap03_l","method":"GET","provider":"TWSE","role":"official exchange+two-digit industry code and listing date for TWSE listed companies","url":"https://openapi.twse.com.tw/v1/opendata/t187ap03_L"},{"dataset":"mopsfin_t187ap03_O","fields":"Date,SecuritiesCompanyCode,SecuritiesIndustryCode,DateOfListing","format":"JSON array of objects","id":"tpex_mopsfin_t187ap03_o","method":"GET","provider":"TPEx","role":"official exchange+two-digit industry code and listing date for TPEx listed companies","url":"https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"},{"dataset":"TaiwanStockDelisting","fields":"date,stock_id,stock_name","format":"JSON object {msg,status,data}","id":"finmind_taiwan_stock_delisting","method":"GET","provider":"FinMind","role":"delisted stocks filtered to [C, D] in RAM; no date parameters are sent; a row whose date is not a real YYYY-MM-DD date is unknown","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockDelisting"}],"storage":"process_RAM","supported_use":["local_personal_noncommercial","process_ram_snapshot","industry_membership_inferred_cutoff_lookup"],"unsupported":["historical_pit","publication_time","first_availability","revision_history","classification_effective_date","off_cycle_reclassification_exclusion","other_cutoffs","theme_membership","hot_group_v1_score","group_return","actionable_strategy","plan","trading","historical_simulation","raw_disk_storage","db_write","redistribution","mirror","deployment"],"version":"issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1"}'.encode("utf-8")
EXTERNAL_PIN = "f6df04241f97fd50948b54d463cf829526b6f12c3b259c642e2c0d20d6b51676"

SOURCE = ROOT / "backend/app/industry_membership_inferred_source.py"
spec = importlib.util.spec_from_file_location("issue37_membership_boundary", SOURCE)
source = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = source
spec.loader.exec_module(source)


NAMESPACE = "issue37-industry-membership-inferred-cutoffs-1005-1006-v2/qa2"
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


MISSING = object()  # the key is absent from the row
# One representative per odd date form: the census class name and a raw JSON value that falls into it (all unknown for FinMind dates).
UNKNOWN_DATES = (("missing", MISSING), ("json_null", None), ("non_string", 20261011), ("empty", ""), ("blank", "   "), ("null_text", "None"),
                 ("iso_future", "2026-10-13"), ("iso_invalid_calendar", "2026-02-30"), ("iso_with_time", "2026-10-11T00:00:00Z"),
                 ("digits8", "20261011"), ("slash_date", "2026/10/11"), ("other_string", "yesterday"))


def dated(row, raw):
    """A copy of a FinMind row whose date is the given raw value (MISSING removes the key)."""
    row = dict(row)
    if raw is MISSING:
        row.pop("date", None)
    else:
        row["date"] = raw
    return row


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

    def assertCensusIdentities(self, snapshot):
        """Every field's classes sum to the object rows; official/FinMind exclusions and listing formats agree with the census."""
        inspected = snapshot.inspection()
        census = inspected["census"]
        for name, record in census.items():
            self.assertEqual(set(record), {"rows", "rows_not_object", *source.CENSUS_VOCABULARY[name]}, name)
            for field, classes in source.CENSUS_VOCABULARY[name].items():
                self.assertEqual(tuple(record[field]), classes, (name, field))
                self.assertEqual(sum(record[field].values()), record["rows"] - record["rows_not_object"], (name, field))
        if len(census) == 4:  # a finished parse of every source
            self.assertEqual(tuple(census[name]["rows"] for name in source.CENSUS_SOURCES), inspected["row_counts"])
            excluded = inspected["excluded_non_ordinary"]
            info_ids = census["info"]["stock_id"]
            self.assertEqual(sum(excluded["finmind"].values()),
                             sum(info_ids[key] for key in ("digits_other_length", "alnum_mixed", "other_ascii", "non_ascii")))
            for exchange in ("TWSE", "TPEx"):
                self.assertEqual(excluded["official"][exchange], census[exchange.lower()]["code"]["grammar_non_ordinary"])
                formats = inspected["listing_date_formats"][exchange]
                listing = census[exchange.lower()]["listing_date"]
                self.assertEqual(formats["unknown"], sum(listing[key] for key in (
                    "invalid_calendar", "missing", "json_null", "non_string", "empty", "blank", "null_text", "other_string")))
                for label in ("gregorian8", "roc7", "roc6", "ymd_slash"):
                    self.assertEqual(formats[label], listing[label])

    def admitAsInferred(self, snapshot):
        """Oracle stand-in for tests that only need an available snapshot: assert exactly the inferred outcomes."""
        outcomes = snapshot.inspection()["outcomes"]
        expected = {key: tuple(tuple(member) for member in outcome.members) for key, outcome in outcomes.items()}
        snapshot.admit_independent_verification(admission(snapshot, expected=entries(
            expected, {key for key, outcome in outcomes.items() if outcome.rejected})))


class PolicyTests(Base):
    def test_shipped_pins_equal_the_published_policy_and_nothing_overrides_them(self):
        # The runner never assigns the product constants; these are the values the module ships with.
        self.assertEqual(source.POLICY_SHA256, "f6df04241f97fd50948b54d463cf829526b6f12c3b259c642e2c0d20d6b51676")
        self.assertEqual(source.POLICY_BYTES, 15152)
        self.assertEqual(source.POLICY_VERSION, "issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1")
        self.assertEqual(source.NAMESPACE, "issue37-industry-membership-inferred-cutoffs-1005-1006-v2/qa2")  # v2.1 keeps the qa2 namespace
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
        self.assertEqual(policy["version"], "issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1")
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
                 ("namespace", ("acquisition", "namespace"), NAMESPACE.replace("qa2", "qa1")),
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
        # The floor is the policy v2.1 publication comment: the spent qa1 seal, both earlier publications, the v2.1 publication
        # itself and everything older are refused; the first later comment is accepted. Literal ids, independent of the product constant.
        self.assertEqual(source.SEAL_COMMENT_FLOOR, 6174861923)
        for label, comment in (("spent qa1 seal", 6149274670), ("qa1 schedule", 6149286656), ("v2 publication", 6171178641),
                               ("v2 publication plus one", 6171178642), ("v1 publication", 6134816304), ("earlier approval", 6128163640),
                               ("v2.1 publication", 6174861923), ("just below", 6174861922)):
            with self.subTest(label):
                bad, bad_binding = declaration(url=f"https://github.com/YiCheng0608/stock-lab/issues/37#issuecomment-{comment}")
                self.assertFailure("financial_new_explicit_seal_required", source._financial_start, bad, bad_binding)
        for comment in (6174861924, 6180000000):
            with self.subTest(accepted=comment):
                good, good_binding = declaration(url=f"https://github.com/YiCheng0608/stock-lab/issues/37#issuecomment-{comment}")
                source._financial_start(good, good_binding)
        # The declaration version names the FinancialStart schema, which this round does not change.
        self.assertEqual(source.FINANCIAL_START_VERSION, "issue37-financial-start-v1")
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
                ("namespace", dict(namespace=NAMESPACE.replace("qa2", "qa1")), "financial_start_scope"),
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
        self.assertFailure("quota_namespace", source.AttemptLedger, NAMESPACE.replace("qa2", "qa1"))
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

    def test_value_form_classifiers_return_the_first_matching_class_and_only_real_dates(self):
        day = "2026-10-12"
        for raw, expected in ((source._MISSING, ("missing", None)), (None, ("json_null", None)), (20261011, ("non_string", None)), (True, ("non_string", None)),
                              ("", ("empty", None)), ("  \t", ("blank", None)), ("NaT", ("null_text", None)), ("n/A", ("null_text", None)),
                              ("2026-10-11", ("iso_valid", "2026-10-11")), ("2026-10-12", ("iso_valid", "2026-10-12")),
                              ("2026-10-13", ("iso_future", "2026-10-13")), ("2026-02-30", ("iso_invalid_calendar", None)),
                              ("0000-00-00", ("iso_invalid_calendar", None)), ("2026-10-11T00:00:00Z", ("iso_with_time", None)),
                              ("2026-10-11 00:00", ("iso_with_time", None)), ("2026-10-11T00:00:00.123+08:00", ("iso_with_time", None)),
                              ("20261011", ("digits8", None)), ("2026/10/11", ("slash_date", None)), ("yesterday", ("other_string", None)),
                              (" 2026-10-11", ("other_string", None)), ("2026-10-11T", ("other_string", None)), ("2026-10-11\n", ("other_string", None))):
            with self.subTest(date=raw):
                self.assertEqual(source._iso_date_class(raw, day), expected)
        self.assertEqual(source._iso_date_class("2099-01-01"), ("iso_valid", "2099-01-01"))  # without D nothing is in the future
        for raw, expected in ((source._MISSING, ("missing", None)), (None, ("json_null", None)), (1151012, ("non_string", None)), ("", ("empty", None)),
                              (" ", ("blank", None)), ("None", ("null_text", None)), ("1151012", ("roc7_valid", "2026-10-12")),
                              ("1151032", ("roc7_invalid_calendar", None)), ("0000000", ("roc7_invalid_calendar", None)),
                              ("20261012", ("digits8", None)), ("2026-10-12", ("iso_shape", None)), ("2026-13-45", ("iso_shape", None)),
                              ("115101", ("other_string", None)), ("1151012 ", ("other_string", None))):
            with self.subTest(report=raw):
                self.assertEqual(source._report_date_class(raw), expected)
        for raw, expected in ((source._MISSING, "missing"), (None, "json_null"), (7, "non_string"), ("", "empty"), (" ", "blank"), ("Null", "null_text"),
                              ("9" * 33, "oversize"), ("2330", "ordinary"), ("0050", "ordinary"), ("00878", "digits_other_length"), ("1", "digits_other_length"),
                              ("2330A", "alnum_mixed"), ("TAIEX", "alnum_mixed"), (" 2330", "other_ascii"), ("23-30", "other_ascii"), ("２３３０", "non_ascii"),
                              ("9" * 32, "digits_other_length")):
            with self.subTest(stock_id=raw):
                self.assertEqual(source._finmind_id_class(raw), expected)
        for raw, expected in ((source._MISSING, "missing"), (None, "json_null"), (7, "non_string"), ("", "empty"), (" ", "blank"), ("NONE", "null_text"),
                              ("2330", "ordinary"), ("2330A", "grammar_non_ordinary"), ("00631L", "grammar_non_ordinary"), ("ABCDEF", "grammar_non_ordinary"),
                              ("233", "bad_grammar"), ("1234567", "bad_grammar"), ("23a0", "bad_grammar"), (" 2330", "bad_grammar"), ("２３３０", "bad_grammar")):
            with self.subTest(code=raw):
                self.assertEqual(source._official_code_class(raw), expected)
        for raw, expected in ((source._MISSING, "missing"), (None, "json_null"), (1, "non_string"), ("", "empty"), (" ", "blank"), ("nan", "null_text"),
                              ("twse", "twse"), ("tpex", "tpex"), ("TWSE", "other_string"), ("emerging", "other_string")):
            with self.subTest(type=raw):
                self.assertEqual(source._type_class(raw), expected)
        for raw, expected in ((source._MISSING, "missing"), (None, "json_null"), ([], "non_string"), ("", "empty"), (" ", "blank"), ("na", "null_text"),
                              ("半導體業", "required_name"), ("光電業", "required_name"), ("文化創意業", "required_name"), ("水泥工業", "other_name"),
                              ("金融業", "other_name"), ("ETF", "unknown_name"), ("半導體業 ", "unknown_name")):
            with self.subTest(industry_name=raw):
                self.assertEqual(source._industry_name_class(raw), expected)
        for exchange, raw, expected in (("TWSE", source._MISSING, "missing"), ("TWSE", None, "json_null"), ("TWSE", 24, "non_string"), ("TWSE", "", "empty"),
                                        ("TWSE", " ", "blank"), ("TWSE", "none", "null_text"), ("TWSE", "24", "required_group"), ("TWSE", "26", "required_group"),
                                        ("TPEx", "32", "required_group"), ("TWSE", "32", "unmapped_two_digit"), ("TWSE", "01", "other_group"),
                                        ("TWSE", "91", "unmapped_two_digit"), ("TPEx", "80", "unmapped_two_digit"), ("TWSE", "024", "other_string"),
                                        ("TWSE", "24 ", "other_string"), ("TWSE", "zz", "other_string")):
            with self.subTest(exchange=exchange, industry_code=raw):
                self.assertEqual(source._official_industry_class(exchange, raw), expected)
        for raw, expected in (("19940905", "gregorian8"), ("1100304", "roc7"), ("990101", "roc6"), ("2010/05/04", "ymd_slash"), (source._MISSING, "missing"),
                              (None, "json_null"), (20010723, "non_string"), ("", "empty"), (" ", "blank"), ("null", "null_text"), ("20230229", "invalid_calendar"),
                              ("1120229", "invalid_calendar"), ("2024/2/30", "invalid_calendar"), ("x", "other_string"), ("2010-05-04", "other_string")):
            with self.subTest(listing=raw):
                self.assertEqual(source._listing_class(raw), expected)

    def test_official_structure_failures_and_value_level_unknowns(self):
        ok = source._parse_official([twse("2330", "24", "19940905"), twse("1101", "01", "19620209", 公司簡稱="x")], "TWSE", "2026-10-12")
        rows, report = ok
        self.assertEqual(report, "2026-10-12")
        self.assertEqual([(r.exchange, r.symbol, r.group, r.listing, r.report_ok) for r in rows],
                         [("TWSE", "2330", SEMI, "1994-09-05", True), ("TWSE", "1101", "Cement", "1962-02-09", True)])
        for label, document, code in (
                ("not list", {"a": 1}, "official_rows"), ("empty", [], "official_rows"), ("row not dict", [1], "row_not_object"),
                ("one row not dict", [twse("2330", "24", "19940905"), "x"], "row_not_object"),
                ("not uniform", [twse("2330", "24", "19940905"), twse("2454", "24", "20010723", report="1151011")], "official_report_date_not_uniform"),
                ("missing report", [{"公司代號": "2330", "產業別": "24", "上市日期": "19940905"}], "official_report_date"),
                ("report gregorian", [twse("2330", "24", "19940905", report="20261012")], "official_report_date"),
                ("report invalid", [twse("2330", "24", "19940905", report="1151032")], "official_report_date"),
                ("report null", [{**twse("2330", "24", "19940905"), "出表日期": None}], "official_report_date"),
                ("report before", [twse("2330", "24", "19940905", report="1151005")], "official_report_date_out_of_range"),
                ("report after D", [twse("2330", "24", "19940905", report="1151013")], "official_report_date_out_of_range")):
            with self.subTest(label):
                self.assertFailure(code, source._parse_official, document, "TWSE", "2026-10-12")
        # Official TWSE keys parsed as TPEx: no row carries a usable report date.
        self.assertFailure("official_report_date", source._parse_official, [twse("2330", "24", "19940905")], "TPEx", "2026-10-12")
        rows, report = source._parse_official([tpex("3105", "24", "x")], "TPEx", "2026-10-12")
        self.assertIsNone(rows[0].listing)  # invalid listing date is not a parse failure: it rejects the group later
        # Null/absent/wrong-typed industry or listing columns are unknown/missing, never a whole-batch failure.
        rows, _ = source._parse_official([{**twse("2330", None, None)}, {k: v for k, v in twse("2454", "24", "x").items() if k != "上市日期"},
                                          {**twse("3008", "", 20010723)}, {k: v for k, v in twse("2409", "26", "x").items() if k != "產業別"},
                                          twse("1101", 1, "20000101")], "TWSE", "2026-10-12")
        self.assertEqual([(r.symbol, r.industry, r.group, r.listing, r.industry_class) for r in rows],
                         [("2330", "", None, None, "json_null"), ("2454", "24", SEMI, None, "required_group"),
                          ("3008", "", None, None, "empty"), ("2409", "", None, None, "missing"), ("1101", "", None, "2000-01-01", "non_string")])
        # An unusable code (never a batch failure) leaves the row without a symbol; the group, industry and report flag survive.
        for label, raw in (("number", 2330), ("null", None), ("empty", ""), ("blank", "  "), ("null marker", "NONE"), ("3 chars", "233"),
                           ("lowercase", "23a0"), ("7 chars", "2330000"), ("full-width", "２３３０"), ("padded", " 2330"),
                           ("hyphen", "23-30"), ("dot", "2330."), ("list", ["2330"])):
            with self.subTest(code=label):
                rows, _ = source._parse_official([twse("2330", "24", "19940905"), {**twse("1101", "01", "19620209"), "公司代號": raw}], "TWSE", "2026-10-12")
                self.assertEqual([(r.symbol, r.group, r.report_ok) for r in rows], [("2330", SEMI, True), (None, "Cement", True)])
        rows, _ = source._parse_official([twse("2330", "24", "19940905"), {k: v for k, v in twse("1101", "01", "19620209").items() if k != "公司代號"}],
                                         "TWSE", "2026-10-12")
        self.assertIsNone(rows[1].symbol)
        # A grammar-conforming non-ordinary code keeps its symbol (excluded later, not unknown).
        rows, _ = source._parse_official([twse(code, "24", "19940905") for code in ("2330A", "00631L", "23301", "ABCD", "ABCDEF")], "TWSE", "2026-10-12")
        self.assertEqual([r.symbol for r in rows], ["2330A", "00631L", "23301", "ABCD", "ABCDEF"])
        # A duplicated code is kept twice (the inference rejects the groups its rows reach, not the batch).
        rows, _ = source._parse_official([twse("2330", "24", "19940905"), twse("2330", "26", "19940905")], "TWSE", "2026-10-12")
        self.assertEqual([(r.symbol, r.group) for r in rows], [("2330", SEMI), ("2330", "Optoelectronics")])
        # A row without a usable report date is kept and flagged; the feed date is the one value shared by the usable rows.
        rows, report = source._parse_official([twse("2330", "24", "19940905"), twse("2454", "24", "20010723", report="1151032"),
                                               twse("3008", "26", "20020101", report="x"), {**twse("2409", "26", "19961105"), "出表日期": 1151012}],
                                              "TWSE", "2026-10-12")
        self.assertEqual((report, [r.report_ok for r in rows]), ("2026-10-12", [True, False, False, False]))

    def test_finmind_documents_status_rows_and_extra_columns(self):
        rows = source._parse_info({"status": 200, "msg": "success", "data": [
            {**info("2330", "twse", "半導體業"), "extra": 1}]}, "2026-10-12")
        self.assertEqual(rows, (source.InfoRow("2026-10-11", "2330", "twse", "半導體業"),))
        nulls = source._parse_info({"status": 200, "msg": "success", "data": [
            {"date": "2026-10-11", "stock_id": "2330", "type": None, "industry_category": None}]}, "2026-10-12")
        self.assertEqual(nulls, (source.InfoRow("2026-10-11", "2330", "", "", False),))  # unknown: never a member of any group
        good = {"status": 200, "msg": "success", "data": [info("2330", "twse", "半導體業")]}
        for label, document, code in (
                ("not dict", [], "finmind_document"), ("extra key", {**good, "x": 1}, "finmind_document"),
                ("missing key", {"status": 200, "data": []}, "finmind_document"),
                ("status 400", {**good, "status": 400}, "finmind_document_status"),
                ("status bool", {**good, "status": True}, "finmind_document_status"),
                ("status str", {**good, "status": "200"}, "finmind_document_status"),
                ("msg", {**good, "msg": "ok"}, "finmind_document_status"),
                ("empty data", {**good, "data": []}, "finmind_rows"), ("data not list", {**good, "data": {}}, "finmind_rows"),
                ("row not object", {**good, "data": [info("2330", "twse", "x"), "2330"]}, "row_not_object"),
                ("null row", {**good, "data": [None]}, "row_not_object")):
            with self.subTest(label):
                self.assertFailure(code, source._parse_info, document, "2026-10-12")
        # Every value-level anomaly is unknown (None date/identity, unusable type or industry), never a batch failure.
        for label, row, expected in (
                ("number id", {**info("2330", "twse", "x"), "stock_id": 2330}, source.InfoRow("2026-10-11", None, "twse", "x")),
                ("type number", {**info("2330", "twse", "x"), "type": 1}, source.InfoRow("2026-10-11", "2330", "", "x", False)),
                ("industry list", {**info("2330", "twse", "x"), "industry_category": []}, source.InfoRow("2026-10-11", "2330", "twse", "")),
                ("missing date", {k: v for k, v in info("2330", "twse", "x").items() if k != "date"}, source.InfoRow(None, "2330", "twse", "x")),
                ("bad date", info("2330", "twse", "x", day="2026/10/11"), source.InfoRow(None, "2330", "twse", "x")),
                ("future date", info("2330", "twse", "x", day="2026-10-13"), source.InfoRow(None, "2330", "twse", "x")),
                ("date with time", info("2330", "twse", "x", day="2026-10-11T00:00:00"), source.InfoRow(None, "2330", "twse", "x")),
                ("empty id", info("", "twse", "x"), source.InfoRow("2026-10-11", None, "twse", "x")),
                ("long id", info("1" * 33, "twse", "x"), source.InfoRow("2026-10-11", None, "twse", "x")),
                ("other type", info("2330", "emerging", "x"), source.InfoRow("2026-10-11", "2330", "emerging", "x")),
                ("padded id is not ordinary", info(" 2330", "twse", "x"), source.InfoRow("2026-10-11", " 2330", "twse", "x")),
                ("etf id", info("00878", "twse", "x"), source.InfoRow("2026-10-11", "00878", "twse", "x")),
                ("null marker id", info("None", "twse", "x"), source.InfoRow("2026-10-11", None, "twse", "x"))):
            with self.subTest(label):
                self.assertEqual(source._parse_info({**good, "data": [row]}, "2026-10-12"), (expected,))
        self.assertEqual(source._parse_delisting({**good, "data": [delist("1234", "2024-03-01")]}), (source.DelistRow("2024-03-01", "1234"),))
        for label, row, expected in (("bad date", delist("1234", "20240301"), source.DelistRow(None, "1234")),
                                     ("date null", {**delist("1234", "2024-03-01"), "date": None}, source.DelistRow(None, "1234")),
                                     ("number id", {**delist("1234", "2024-03-01"), "stock_id": 1234}, source.DelistRow("2024-03-01", None)),
                                     ("id missing", {"date": "2024-03-01", "stock_name": "x"}, source.DelistRow("2024-03-01", None)),
                                     ("empty id", delist("", "2024-03-01"), source.DelistRow("2024-03-01", None)),
                                     ("blank id", delist("   ", "2024-03-01"), source.DelistRow("2024-03-01", None)),
                                     ("long id", delist("1" * 33, "2024-03-01"), source.DelistRow("2024-03-01", None)),
                                     ("etf id", delist("006208", "2026-10-08"), source.DelistRow("2026-10-08", "006208"))):
            with self.subTest(label):
                self.assertEqual(source._parse_delisting({**good, "data": [row]}), (expected,))
        self.assertFailure("row_not_object", source._parse_delisting, {**good, "data": [delist("1234", "2024-03-01"), []]})
        # A delisting date after D is a known date (it lies outside every window); only malformed dates are unknown.
        self.assertEqual(source._parse_delisting({**good, "data": [delist("1234", "2099-01-01")]})[0].date, "2099-01-01")
        self.assertEqual(source._parse_delisting({**good, "data": [delist("1234", "2099-01-01")]}, "2026-10-12")[0].date, "2099-01-01")
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
                kept = [row for row in w.info if not (row["stock_id"] == "6200" and row.get("type") == "tpex")]
                return kept + list(rows)
            return apply
        for label, rows, groups, reason in (
                ("other required group", [info("6200", "tpex", "光電業", day="2026-10-08")], (SEMI, OPTO), "board_transfer_industry_conflict"),
                ("non required group", [info("6200", "tpex", "食品工業", day="2026-10-08")], (SEMI,), "board_transfer_industry_conflict"),
                ("same date two names", [info("6200", "tpex", "半導體業", day="2026-10-08"), info("6200", "tpex", "光電業", day="2026-10-08")],
                 (SEMI, OPTO), "board_transfer_ambiguous"),
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
        # The official group of a tied stock is rejected for the tie itself, not only through the missing FinMind member.
        w = world()
        w.info[0] = info("2330", "twse", "食品工業")  # 2330 is official Semiconductor; its two newest FinMind rows name non-required groups
        w.info.append(info("2330", "twse", "水泥工業"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "finmind_multiple_valid_records", "cross_source_mismatch")
            self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))

    def test_identity_rules(self):
        w = world()
        w.twse.append(twse("2330", "24", "19940905"))  # repeated within one feed: the groups its rows reach are rejected, not the batch
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "official_duplicate_symbol")
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

    def test_unusable_identities_reject_only_the_groups_they_reach_never_the_batch(self):
        def rows_with(**changes):
            w = world()
            for key, value in changes.items():
                setattr(w, key, value(w))
            return w
        # Official side: an unusable code leaves a row nobody can attribute; it rejects the required group its industry reaches.
        for label, code in (("3 chars", "233"), ("trailing space", "2330 "), ("fullwidth", "２３３０"), ("lowercase", "23a0"),
                            ("seven chars", "1234567"), ("empty", ""), ("dot", "2330."), ("number", 2330), ("null", None),
                            ("null marker", "NONE"), ("blank", "   ")):
            for feed, industry, rejected in (("twse", "24", (SEMI,)), ("twse", "26", (OPTO,)), ("tpex", "24", (SEMI,)),
                                             ("tpex", "26", (OPTO,)), ("tpex", "32", (CULT,))):
                with self.subTest(code=label, feed=feed, industry=industry):
                    make = twse if feed == "twse" else tpex
                    key = "公司代號" if feed == "twse" else "SecuritiesCompanyCode"
                    w = world()
                    getattr(w, feed).append({**make("9999", industry, "20000101"), key: code})
                    snapshot, transport, _ = pending(w)
                    self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3))
                    for cutoff in (C1, C2):
                        for group in (SEMI, OPTO, CULT):
                            if group in rejected:
                                self.assertRejected(snapshot, cutoff, group, "official_identity_unusable")
                            else:
                                self.assertUsable(snapshot, (cutoff, group))
                                self.assertEqual(self.outcomes(snapshot)[(cutoff, group)].members, EXPECTED[(cutoff, group)])
        # Industries that provably sit outside every required group (other group, or a two-digit code the mapper lacks) are ignored.
        for industry in ("01", "17", "91", "80", "18"):
            with self.subTest(industry=industry):
                w = world()
                w.twse.append({**twse("9999", industry, "20000101"), "公司代號": "233"})
                snapshot, _, _ = pending(w)
                self.assertAllSix(snapshot)
        # An industry that cannot be shown to be outside the required groups could be any of them: all three are rejected.
        for label, industry in (("null", None), ("empty", ""), ("blank", " "), ("number", 26), ("garbage", "zz"), ("padded", "24 "), ("marker", "null")):
            with self.subTest(industry=label):
                w = world()
                w.twse.append({**twse("9999", industry, "20000101"), "公司代號": None})
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    for group in (SEMI, OPTO, CULT):
                        self.assertRejected(snapshot, cutoff, group, "official_identity_unusable")
        # A missing code key is the same as an unusable code.
        w = world()
        w.tpex.append({k: v for k, v in tpex("9999", "32", "20000101").items() if k != "SecuritiesCompanyCode"})
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, CULT, "official_identity_unusable")
            self.assertUsable(snapshot, (cutoff, SEMI), (cutoff, OPTO))
        # Through the whole batch every GET is spent and the census still counts what was seen.
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3))
        self.assertEqual(snapshot.inspection()["census"]["tpex"]["code"]["missing"], 1)

    def test_official_duplicate_codes_reject_the_groups_their_rows_reach(self):
        def appended(feed, *rows):
            w = world()
            getattr(w, feed).extend(rows)
            return pending(w)[0]
        snapshot = appended("twse", twse("2330", "24", "19940905"))  # the same stock twice, same group
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "official_duplicate_symbol")
            self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
            self.assertNotIn(("TWSE", "2330"), self.outcomes(snapshot)[(cutoff, SEMI)].members)
            self.assertNotIn("duplicate_identity", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)  # the repeated rows are never members
            self.assertIn("cross_source_mismatch", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)  # so FinMind's 2330 has no official counterpart
        snapshot = appended("twse", twse("2330", "26", "19940905"))  # one of the two rows sits in another required group
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "official_duplicate_symbol")
            self.assertRejected(snapshot, cutoff, OPTO, "official_duplicate_symbol")
            self.assertUsable(snapshot, (cutoff, CULT))
        snapshot = appended("tpex", tpex("3293", "32", "20150101"))
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, CULT, "official_duplicate_symbol")
        snapshot = appended("twse", twse("1101", "01", "19620209"))  # duplicates outside the required groups do not matter
        self.assertAllSix(snapshot)
        snapshot = appended("twse", twse("2330A", "24", "19940905"), twse("2330A", "24", "19940905"))  # non-ordinary duplicates are excluded
        self.assertAllSix(snapshot)
        # Duplicates are tolerated by the parser, so the batch is never spent early.
        w = world()
        w.twse.append(twse("2330", "24", "19940905"))
        snapshot, _, _ = pending(w)
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3))

    def test_official_rows_without_a_usable_report_date_reject_their_group_not_the_batch(self):
        for label, raw in (("gregorian", "20261012"), ("invalid", "1151032"), ("null", None), ("empty", ""), ("number", 1151012), ("iso", "2026-10-12"),
                           ("marker", "NaT"), ("garbage", "x")):
            with self.subTest(report=label):
                w = world()
                w.twse[0] = twse("2330", "24", "19940905", report=raw)  # a semiconductor stock
                snapshot, _, _ = pending(w)
                self.assertEqual(snapshot.inspection()["report_dates"]["TWSE"], "2026-10-12")
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "official_row_report_date_unknown")
                    self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
        # Outside the required groups the same anomaly changes nothing.
        w = world()
        w.twse[4] = twse("1101", "01", "19620209", report="x")
        snapshot, _, _ = pending(w)
        self.assertAllSix(snapshot)
        # The seven-stock pool check does not look at report dates: a pool stock with an unusable date still counts as covered.
        w = world()
        w.tpex[0] = tpex("3105", "24", "1100304", report=None)
        snapshot, _, _ = pending(w)
        self.assertEqual(snapshot.state, "pending")
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "official_row_report_date_unknown")
        # The row stays in the identity index: a delisting inside the window is not read as a FinMind-only stock, so the
        # stock is not "explained" and the FinMind side still shows the difference.
        w = world()
        w.twse[3] = twse("2409", "26", "19961105", report="x")
        w.delist.append(delist("2409", "2026-10-08"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, OPTO, "official_row_report_date_unknown", "cross_source_mismatch")

    def test_unusable_info_identity_and_type_reject_only_what_they_could_reach(self):
        def extra(*rows):
            w = world()
            w.info.extend(rows)
            return pending(w)[0]
        for label, stock_id in (("null", None), ("empty", ""), ("blank", "  "), ("number", 2330), ("null marker", "NaN"), ("33 chars", "9" * 33)):
            with self.subTest(stock_id=label):
                snapshot = extra({**info("0", "twse", "半導體業"), "stock_id": stock_id})
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "info_identity_unusable")
                    self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
        snapshot = extra({**info("0", "tpex", "文化創意業"), "stock_id": None})
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, CULT, "info_identity_unusable")
            self.assertUsable(snapshot, (cutoff, SEMI), (cutoff, OPTO))
        # An unusable type tries both exchanges; an unlisted type or an unknown or non-required name reaches nothing.
        snapshot = extra({**info("0", "twse", "文化創意業"), "stock_id": None, "type": None})
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, CULT, "info_identity_unusable")
        snapshot = extra({**info("0", "twse", "文化創意業"), "stock_id": None})  # twse has no such name
        self.assertAllSix(snapshot)
        self.assertAllSix(extra({**info("0", "emerging", "半導體業"), "stock_id": None}))
        self.assertAllSix(extra({**info("0", "twse", "存託憑證"), "stock_id": None, "type": None}))
        self.assertAllSix(extra({**info("0", "twse", "水泥工業"), "stock_id": None}))
        self.assertAllSix(extra({**info("0", "twse", None), "stock_id": None}))
        # T-1: a decided newest row with an unusable type could be a member under either exchange.
        for label, raw in (("null", None), ("number", 3), ("empty", ""), ("blank", " "), ("marker", "None")):
            with self.subTest(type=label):
                w = world()
                w.info.append({**info("5555", "twse", "半導體業"), "type": raw})  # a FinMind-only stock that official does not list
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "info_type_unusable")
                    self.assertNotIn("cross_source_mismatch", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
                    self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
        w = world()
        w.info.append({**info("5555", "twse", "半導體業"), "type": "emerging"})  # a real other type is not unknown
        self.assertAllSix(pending(w)[0])
        w = world()
        w.info[0] = {**info("2330", "twse", "半導體業"), "type": None}  # the official member loses its type: both reasons
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "info_type_unusable", "cross_source_mismatch")
        # Unknown names never reach a group.
        w = world()
        w.info.append({**info("5555", "twse", "半導體業"), "industry_category": None})
        self.assertAllSix(pending(w)[0])

    def test_unknown_info_dates_never_reject_the_batch_and_single_row_stocks_need_no_date(self):
        # Every FinMind row carries the odd date form: each stock has one row, so its newest row is decided without any date.
        for label, raw in UNKNOWN_DATES:
            with self.subTest(date=label):
                w = world()
                w.info = [dated(row, raw) for row in w.info]
                snapshot, _, _ = pending(w)
                self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3))
                self.assertAllSix(snapshot)
                inspected = snapshot.inspection()
                self.assertEqual(inspected["census"]["info"]["date"][label], len(w.info))
                self.assertEqual(inspected["stock_resolution"]["single_row"], sum(1 for row in w.info if re.fullmatch(r"[0-9]{4}", row["stock_id"])))
        # A non-ordinary or unrelated stock with an odd date changes nothing, whatever else its rows say.
        for label, raw in UNKNOWN_DATES:
            with self.subTest(non_ordinary=label):
                w = world()
                w.info += [dated(info("TAIEX", "twse", "Index"), raw), dated(info("00878", "twse", "半導體業"), raw),
                           dated(info("00878", "twse", "光電業"), raw), dated(info("1101", "twse", "食品工業"), raw)]
                self.assertAllSix(pending(w)[0])

    def test_unknown_info_date_with_differing_values_rejects_the_groups_it_reaches(self):
        for label, raw in UNKNOWN_DATES:
            with self.subTest(date=label):
                # An older-looking row of another group whose date is unknown: the newest row of 2330 is undecided.
                w = world()
                w.info.append(dated(info("2330", "twse", "光電業", day="2026-10-01"), raw))
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "finmind_latest_date_unresolved")
                    self.assertRejected(snapshot, cutoff, OPTO, "finmind_latest_date_unresolved")
                    self.assertUsable(snapshot, (cutoff, CULT))
                    self.assertEqual(self.outcomes(snapshot)[(cutoff, CULT)].members, EXPECTED[(cutoff, CULT)])
                self.assertEqual(snapshot.inspection()["stock_resolution"]["date_unresolved_related"], 1)
                # The same unknown date next to an identical value cannot change what the newest row says.
                w = world()
                w.info.append(dated(info("2330", "twse", "半導體業"), raw))
                snapshot, _, _ = pending(w)
                self.assertAllSix(snapshot)
                self.assertEqual(snapshot.inspection()["stock_resolution"]["same_value"], 1)
                # A stock that reaches no required group is ignored.
                w = world()
                w.info += [dated(info("1101", "twse", "食品工業"), raw), dated(info("2002", "twse", "水泥工業"), raw)]
                snapshot, _, _ = pending(w)
                self.assertAllSix(snapshot)
                self.assertEqual(snapshot.inspection()["stock_resolution"]["date_unresolved_unrelated"], 2)
        # All dates known: an older row of another group is history (unchanged v1 behaviour).
        w = world()
        w.info.append(info("2330", "twse", "光電業", day="2026-09-01"))
        snapshot, _, _ = pending(w)
        self.assertAllSix(snapshot)
        self.assertEqual(snapshot.inspection()["stock_resolution"]["newest_unique"], 1)
        # Making that older row's date unknown makes the newest row undecided.
        w = world()
        w.info.append(dated(info("2330", "twse", "光電業"), None))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "finmind_latest_date_unresolved")
        # The official group alone is enough to reach a group: the FinMind rows of 3008 name no required group.
        w = world()
        w.info[2] = dated(info("3008", "twse", "食品工業"), None)
        w.info.append(info("3008", "twse", "水泥工業", day="2026-10-10"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, OPTO, "finmind_latest_date_unresolved")
            self.assertUsable(snapshot, (cutoff, SEMI), (cutoff, CULT))
        # An unusable type reaches both exchanges: a culture-board name on a "twse" row with an unusable type and an unknown date.
        w = world()
        w.info.append(dated({**info("3293", "twse", "半導體業"), "type": None}, "x"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, CULT, "finmind_latest_date_unresolved")  # official group of 3293
            self.assertRejected(snapshot, cutoff, SEMI, "finmind_latest_date_unresolved")  # the extra row's name reaches it
            self.assertUsable(snapshot, (cutoff, OPTO))

    def test_unknown_delisting_dates_reject_what_the_date_could_decide(self):
        for label, raw in UNKNOWN_DATES:
            if label == "iso_future":
                continue  # a real date after D is a known date, covered below
            with self.subTest(date=label):
                # An official stock that might be delisted on a cutoff: its required group is rejected at both cutoffs.
                w = world()
                w.delist.append(dated(delist("2330", "2026-10-08"), raw))
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "delisting_date_unknown")
                    self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
                # An official stock outside the required groups changes nothing.
                w = world()
                w.delist.append(dated(delist("1101", "2026-10-08"), raw))
                self.assertAllSix(pending(w)[0])
                # A FinMind-only stock with a decided required group rejects that group; a non-required one is ignored.
                w = world()
                w.info.append(info("5555", "twse", "半導體業"))
                w.delist.append(dated(delist("5555", "2026-10-08"), raw))
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "delisting_date_unknown", "cross_source_mismatch")
                    self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
                w = world()
                w.info.append(info("5555", "twse", "食品工業"))
                w.delist.append(dated(delist("5555", "2026-10-08"), raw))
                self.assertAllSix(pending(w)[0])
                # Nothing is known about the stock: it may have been a member of any group, so every group is rejected.
                w = world()
                w.delist.append(dated(delist("9999", "2026-10-08"), raw))
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    for group in (SEMI, OPTO, CULT):
                        self.assertRejected(snapshot, cutoff, group, "delisted_industry_undeterminable")
                # A tie of the newest rows (same known date, two values) is as undeterminable as with a known delisting date.
                w = world()
                w.info += [info("5555", "twse", "半導體業"), info("5555", "twse", "食品工業")]
                w.delist.append(dated(delist("5555", "2026-10-08"), raw))
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "delisted_record_ambiguous")
                # Non-ordinary ids are ignored whatever the date.
                w = world()
                w.delist += [dated(delist("006208", "2026-10-08"), raw), dated(delist("TAIEX", "2026-10-08"), raw)]
                self.assertAllSix(pending(w)[0])
        # A real date after D, or before every cutoff, is a known date outside every window.
        w = world()
        w.info.append(info("5555", "twse", "半導體業"))
        w.delist += [delist("9999", "2099-01-01"), delist("2330", "2099-01-01"), delist("9998", "2026-10-04")]
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "cross_source_mismatch")  # 5555 is simply a FinMind-only stock
            self.assertNotIn("delisting_date_unknown", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
            self.assertNotIn("delisted_industry_undeterminable", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
            self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
        # F-3: a FinMind-only stock whose newest row is undecided by unknown dates has an undeterminable industry, exactly like a
        # tie of known dates: all three groups of every cutoff whose window holds (or may hold) its delisting date are rejected,
        # whatever industries its rows name.
        undecided = (
            (info("5555", "twse", "半導體業", day="2026-10-01"), dated(info("5555", "twse", "光電業"), "x")),
            (info("5555", "twse", "水泥工業", day="2026-10-01"), dated(info("5555", "twse", "鋼鐵工業"), "x")),
            (info("5555", "twse", "半導體業", day="2026-10-01"), dated(info("5555", "twse", "存託憑證"), "x")),
            (info("5555", "tpex", "文化創意業", day="2026-10-01"), dated(info("5555", "twse", "食品工業"), None)))
        for rows in undecided:
            for delisting_date, cutoffs in (("2026-10-08", (C1, C2)), ("2026-10-05", (C1,)), ("2026-10-06", (C1, C2)), (None, (C1, C2)), ("bad", (C1, C2))):
                with self.subTest(rows=rows[1]["industry_category"], delisting=delisting_date):
                    w = world()
                    w.info += list(rows)
                    w.delist.append({**delist("5555", "2026-10-08"), "date": delisting_date})
                    snapshot, _, _ = pending(w)
                    for cutoff in cutoffs:
                        for group in (SEMI, OPTO, CULT):
                            self.assertRejected(snapshot, cutoff, group, "delisted_industry_undeterminable")
        # Outside every window the undecided stock only follows the D-set rule (groups it can reach, both cutoffs).
        w = world()
        w.info += list(undecided[0])
        w.delist.append(delist("5555", "2026-10-04"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "finmind_latest_date_unresolved")
            self.assertRejected(snapshot, cutoff, OPTO, "finmind_latest_date_unresolved")
            self.assertUsable(snapshot, (cutoff, CULT))
            self.assertNotIn("delisted_industry_undeterminable", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
        # The same two rows with known dates are resolved by the newest date: no rejection beyond the ordinary rules.
        w = world()
        w.info += [info("5555", "twse", "水泥工業", day="2026-10-01"), info("5555", "twse", "鋼鐵工業", day="2026-10-02")]
        w.delist.append(delist("5555", "2026-10-08"))
        self.assertAllSix(pending(w)[0])

    def test_delisting_rows_without_a_usable_identity_reject_the_cutoffs_whose_window_may_hold_them(self):
        for label, stock_id in (("null", None), ("empty", ""), ("blank", "  "), ("number", 1234), ("marker", "null"), ("33 chars", "9" * 33)):
            with self.subTest(stock_id=label):
                for day, rejected_cutoffs in (("2026-10-08", (C1, C2)), ("2026-10-05", (C1,)), ("2026-10-06", (C1, C2)),
                                              ("2026-10-04", ()), ("2099-01-01", ()), ("bad", (C1, C2)), (None, (C1, C2))):
                    w = world()
                    w.delist.append({**delist("1234", "2026-10-08"), "stock_id": stock_id, "date": day})
                    snapshot, _, _ = pending(w)
                    for cutoff in (C1, C2):
                        for group in (SEMI, OPTO, CULT):
                            if cutoff in rejected_cutoffs:
                                self.assertRejected(snapshot, cutoff, group, "delisted_identity_unusable")
                            else:
                                self.assertUsable(snapshot, (cutoff, group))
                                self.assertEqual(self.outcomes(snapshot)[(cutoff, group)].members, EXPECTED[(cutoff, group)])
        w = world()
        w.delist.append({"date": "2026-10-08"})  # no stock_id key at all
        snapshot, _, _ = pending(w)
        self.assertRejected(snapshot, C1, SEMI, "delisted_identity_unusable")

    def test_board_transfer_needs_a_known_date_on_every_older_tpex_row(self):
        for label, raw in UNKNOWN_DATES:
            with self.subTest(date=label):
                snapshot, _, _ = pending(self.transfer(info=lambda w: [dated(row, raw) if row["stock_id"] == "6200" and row.get("type") == "tpex" else row for row in w.info]))
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "board_transfer_evidence_date_unknown")
                    self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
                # One known older row is not enough while another is unknown.
                snapshot, _, _ = pending(self.transfer(info=lambda w: w.info + [dated(info("6200", "tpex", "半導體業", day="2026-10-09"), raw)]))
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "board_transfer_evidence_date_unknown")

    def old_tpex_rows(self, *rows):
        """A transfer world whose old tpex evidence for stock 6200 is replaced by the given rows."""
        def apply(w):
            return [row for row in w.info if not (row["stock_id"] == "6200" and row.get("type") == "tpex")] + list(rows)
        return apply

    def test_f2_unknown_dated_old_tpex_row_with_a_name_outside_section_two_rejects_all_three_groups(self):
        # QA F-2: the row without a date may be the newest, and its name is outside section 2, so the old TPEx identity
        # could belong to any group. With a known date this was already three groups; the unknown date must not loosen it.
        for name in ("", "存託憑證", "未知產業", None):
            for label, raw in (("known", "2026-10-10"),) + UNKNOWN_DATES:
                with self.subTest(name=name, date=label):
                    row = dated({**info("6200", "tpex", "x"), "industry_category": name}, raw)
                    snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(row)))
                    for cutoff in (C1, C2):
                        for group in (SEMI, OPTO, CULT):
                            self.assertRejected(snapshot, cutoff, group, "board_transfer_old_industry_unknown")
                        if label != "known":
                            self.assertIn("board_transfer_evidence_date_unknown", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
        # The same shape with the official stock in Optoelectronics (the QA reproduction).
        w = self.transfer(twse=lambda w: w.twse[:-1] + [twse("6200", "26", "20261008")],
                          info=self.old_tpex_rows(dated(info("6200", "tpex", ""), "garbage")))
        w.info = [{**row, "industry_category": "光電業"} if row["stock_id"] == "6200" and row.get("type") == "twse" else row for row in w.info]
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            for group in (SEMI, OPTO, CULT):
                self.assertRejected(snapshot, cutoff, group, "board_transfer_old_industry_unknown")
        # One bad name among several old rows is enough, whichever row carries the missing date.
        for rows in ((dated(info("6200", "tpex", "半導體業"), None), info("6200", "tpex", "存託憑證", day="2026-10-09")),
                     (info("6200", "tpex", "半導體業", day="2026-10-09"), dated(info("6200", "tpex", "存託憑證"), None)),
                     (dated(info("6200", "tpex", "存託憑證"), "x"), dated(info("6200", "tpex", "半導體業"), "y"))):
            snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(*rows)))
            for cutoff in (C1, C2):
                for group in (SEMI, OPTO, CULT):
                    self.assertRejected(snapshot, cutoff, group, "board_transfer_old_industry_unknown")

    def test_f2_unknown_dated_old_tpex_rows_with_section_two_names_still_reject_only_the_official_group(self):
        for name in ("半導體業", "光電業", "食品工業"):
            for label, raw in UNKNOWN_DATES:
                with self.subTest(name=name, date=label):
                    snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(dated(info("6200", "tpex", name), raw))))
                    for cutoff in (C1, C2):
                        self.assertRejected(snapshot, cutoff, SEMI, "board_transfer_evidence_date_unknown")
                        self.assertNotIn("board_transfer_old_industry_unknown", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
                        self.assertUsable(snapshot, (cutoff, CULT))
                        if name == "光電業":  # the row without a date could be the newest of the stock, so Optoelectronics is reached too
                            self.assertRejected(snapshot, cutoff, OPTO, "finmind_latest_date_unresolved")
                        else:
                            self.assertUsable(snapshot, (cutoff, OPTO))
        # A non-section-2 name on an OLDER row whose newest row is known is history: the transfer still joins.
        snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "存託憑證", day="2026-10-06"),
                                                                       info("6200", "tpex", "半導體業", day="2026-10-08"))))
        self.assertIn(("TPEx", "6200"), self.outcomes(snapshot)[(C1, SEMI)].members)

    def test_f4_the_transfer_rule_still_runs_for_official_rows_that_cannot_become_members(self):
        for label, raw in (("gregorian", "20261012"), ("invalid", "1151032"), ("null", None), ("empty", ""), ("number", 1151012),
                           ("iso", "2026-10-12"), ("marker", "NaT"), ("garbage", "x")):
            # A name outside section 2: all three groups are rejected although the official row is no member.
            with self.subTest(report=label, old="outside section 2"):
                w = self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "", day="2026-10-10")))
                w.twse[-1] = twse("6200", "24", "20261008", report=raw)
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    for group in (SEMI, OPTO, CULT):
                        self.assertRejected(snapshot, cutoff, group, "board_transfer_old_industry_unknown")
                    self.assertIn("official_row_report_date_unknown", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
            # A conflicting section 2 name rejects both groups involved, the third stays usable.
            with self.subTest(report=label, old="conflicting name"):
                w = self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "光電業", day="2026-10-10")))
                w.twse[-1] = twse("6200", "24", "20261008", report=raw)
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "board_transfer_industry_conflict")
                    self.assertRejected(snapshot, cutoff, OPTO, "board_transfer_industry_conflict")
                    self.assertUsable(snapshot, (cutoff, CULT))
            # A matching name must not add the TPEx identity: the row is not a member, its group stays rejected.
            with self.subTest(report=label, old="matching name"):
                w = self.transfer()
                w.twse[-1] = twse("6200", "24", "20261008", report=raw)
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    self.assertRejected(snapshot, cutoff, SEMI, "official_row_report_date_unknown")
                    self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))
                    self.assertNotIn(("TPEx", "6200"), self.outcomes(snapshot)[(cutoff, SEMI)].members)
        # A repeated code is no member either, and the rule still runs for every repeated row.
        for old_name, rejected in (("", (SEMI, OPTO, CULT)), ("光電業", (SEMI, OPTO)), ("半導體業", (SEMI,))):
            with self.subTest(duplicate=True, old=old_name):
                w = self.transfer(info=self.old_tpex_rows(info("6200", "tpex", old_name, day="2026-10-10")))
                w.twse.append(twse("6200", "24", "20261008"))
                snapshot, _, _ = pending(w)
                for cutoff in (C1, C2):
                    for group in (SEMI, OPTO, CULT):
                        if group in rejected:
                            self.assertRejected(snapshot, cutoff, group)
                        else:
                            self.assertUsable(snapshot, (cutoff, group))
                    self.assertIn("official_duplicate_symbol", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
        # Rows that cannot become members add neither a listing-date reason nor a second TPEx identity.
        w = self.transfer()
        w.twse[-1] = twse("6200", "24", None, report="x")
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "official_row_report_date_unknown")
            self.assertNotIn("listing_date_missing_or_invalid", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
        w = self.transfer()
        w.twse[-1] = twse("6200", "24", "20261008", report="x")
        w.tpex.append(tpex("6200", "24", "20261001"))  # TPEx itself still lists the stock as a member
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "official_row_report_date_unknown")
            self.assertNotIn("duplicate_identity", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
        # The rule is only for rows listed after the cutoff: a row listed before it is not a transfer.
        w = self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "", day="2026-10-10")))
        w.twse[-1] = twse("6200", "24", "20260105", report="x")
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "official_row_report_date_unknown")
            self.assertNotIn("board_transfer_old_industry_unknown", self.outcomes(snapshot)[(cutoff, SEMI)].reasons)
            self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))

    def test_obs_a_seven_stock_coverage_does_not_depend_on_the_order_of_repeated_codes(self):
        base = world()
        official = source._parse_official(base.twse, "TWSE", "2026-10-12")[0] + source._parse_official(base.tpex, "TPEx", "2026-10-12")[0]
        source.check_seven_symbols_covered(official)
        required = next(r for r in official if r.symbol == "8069")
        self.assertEqual(required.group, OPTO)
        for industry, group in (("27", "Communications"), ("28", "Electronic Parts"), ("91", None), ("", None), ("zz", None)):
            repeated = source.OfficialRow("TPEx", "8069", industry, group, "2011-01-01", "gregorian8", "other_group")
            for rows in ((required, repeated), (repeated, required)):
                with self.subTest(industry=industry, order=rows[0] is required):
                    mixed = tuple(r for r in official if r.symbol != "8069") + rows
                    error = self.assertFailure("seven_stock_group_not_required", source.check_seven_symbols_covered, mixed)
                    self.assertEqual(ParseTests.uncovered(error), [(6, "TPEx", industry or "<null>", group or "unknown")])
        # Two uncovered rows: the receipt describes the same one whatever the order.
        first = source.OfficialRow("TPEx", "8069", "28", "Electronic Parts", "2011-01-01")
        second = source.OfficialRow("TPEx", "8069", "27", "Communications", "2011-01-01")
        for rows in ((first, second), (second, first), (first, required, second), (second, required, first)):
            error = self.assertFailure("seven_stock_group_not_required", source.check_seven_symbols_covered,
                                       tuple(r for r in official if r.symbol != "8069") + rows)
            self.assertEqual(ParseTests.uncovered(error), [(6, "TPEx", "27", "Communications")])
        # Every repeated row in a required group: covered in either order.
        other_required = source.OfficialRow("TPEx", "8069", "24", SEMI, "2011-01-01")
        for rows in ((required, other_required), (other_required, required)):
            source.check_seven_symbols_covered(tuple(r for r in official if r.symbol != "8069") + rows)
        # The TPEx feed rows win over TWSE rows: a TWSE row outside the groups does not matter next to covered TPEx rows.
        twse_outside = source.OfficialRow("TWSE", "8069", "28", "Electronic Parts", "2011-01-01")
        source.check_seven_symbols_covered(official + (twse_outside,))
        # Through the whole batch, both orders reject after the third GET with the same receipt.
        receipts = []
        for rows in ((tpex("8069", "26", "20110101"), tpex("8069", "27", "20110101")), (tpex("8069", "27", "20110101"), tpex("8069", "26", "20110101"))):
            w = world()
            w.tpex = [row for row in w.tpex if row["SecuritiesCompanyCode"] != "8069"] + list(rows)
            snapshot, _, _ = build(w)
            error = self.assertFailure("seven_stock_group_not_required", snapshot.acquire)
            self.assertEqual(snapshot.ledger.attempted, (0, 1, 2))
            receipts.append(ParseTests.uncovered(error))
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(receipts[0], [(6, "TPEx", "27", "Communications")])
        # Repeated and all covered: the batch goes on and the repeated code rejects its group.
        w = world()
        w.tpex.append(tpex("8069", "26", "20110101"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, OPTO, "official_duplicate_symbol")

    @staticmethod
    def tightens(before, after):
        """I-1 for one (cutoff, group): the outcome is unchanged, or the group is rejected."""
        return after.rejected or (not before.rejected and (after.members, after.flags) == (before.members, before.flags))

    def test_board_transfer_unknowns_only_tighten_never_add_members_or_lift_rejections(self):
        odd_dates = [raw for label, raw in UNKNOWN_DATES if label in ("json_null", "empty", "other_string", "iso_invalid_calendar", "missing")]
        odd_reports = (None, "x", "20261012", "1151032")
        checked = tightened = 0
        for official_industry, group_name in (("24", "Semiconductor"), ("26", "Optoelectronics"), ("01", "Cement")):
            for old_name in ("半導體業", "光電業", "食品工業", "存託憑證", "", None):
                for known in ("2026-10-10", "2026-10-01"):
                    def build_world(old_date, report="1151012", duplicate=False, official_listing="20261008", old_type="tpex"):
                        old_row = {**info("6200", "tpex", "x"), "industry_category": old_name, "type": old_type}
                        if old_type is MISSING:
                            old_row.pop("type")
                        w = self.transfer(info=self.old_tpex_rows(dated(old_row, old_date)),
                                          twse=lambda w: w.twse[:-1] + [twse("6200", official_industry, official_listing, report=report)])
                        newest = {"24": "半導體業", "26": "光電業", "01": "水泥工業"}[official_industry]  # FinMind agrees with the official group
                        w.info = [{**row, "industry_category": newest} if row["stock_id"] == "6200" and row.get("type") == "twse" else row for row in w.info]
                        if duplicate:
                            w.twse.append(twse("6200", official_industry, official_listing))
                        return pending(w)[0].inspection()["outcomes"]
                    base = build_world(known)
                    variants = [build_world(raw) for raw in odd_dates] + [build_world(known, report=raw) for raw in odd_reports]
                    variants += [build_world(known, duplicate=True), build_world(odd_dates[0], report="x", duplicate=True)]
                    variants += [build_world(known, official_listing=raw) for raw in (None, "x", "20261340", "1130431", 20261005)]
                    variants += [build_world(known, official_listing=None, report="x", duplicate=True), build_world(odd_dates[1], official_listing=None)]
                    variants += [build_world(known, old_type=raw) for raw in (None, "", 5, MISSING)]  # the old row's type becomes unusable
                    variants += [build_world(odd_dates[0], old_type=None), build_world(known, old_type=None, official_listing=None, report="x")]
                    for variant in variants:
                        for key, before in base.items():
                            checked += 1
                            tightened += variant[key].rejected and not before.rejected
                            self.assertTrue(self.tightens(before, variant[key]), (group_name, old_name, known, key, before, variant[key]))
        self.assertGreater(checked, 3500)
        self.assertGreater(tightened, 90)

    def test_finmind_only_delisting_unknowns_only_tighten_never_add_members_or_lift_rejections(self):
        odd_dates = [raw for label, raw in UNKNOWN_DATES if label in ("json_null", "other_string", "iso_invalid_calendar", "missing")]
        checked = tightened = 0
        for names in (("半導體業", "光電業"), ("食品工業", "水泥工業"), ("半導體業", "存託憑證"), ("文化創意業", "文化創意業"), ("半導體業", "半導體業")):
            for delisting_date in ("2026-10-08", "2026-10-05", "2026-10-06", "2026-10-04", "2099-01-01"):
                def outcomes(old_date="2026-10-01", new_date="2026-10-10", delisting=delisting_date):
                    w = world()
                    w.info += [dated(info("5555", "tpex", names[0]), old_date), dated(info("5555", "tpex", names[1]), new_date)]
                    w.delist.append(dated(delist("5555", "2026-10-08"), delisting))
                    return pending(w)[0].inspection()["outcomes"]
                base = outcomes()
                variants = [outcomes(old_date=raw) for raw in odd_dates] + [outcomes(new_date=raw) for raw in odd_dates]
                variants += [outcomes(delisting=raw) for raw in odd_dates] + [outcomes(old_date=odd_dates[0], delisting=odd_dates[1])]
                for variant in variants:
                    for key, before in base.items():
                        checked += 1
                        tightened += variant[key].rejected and not before.rejected
                        self.assertTrue(self.tightens(before, variant[key]), (names, delisting_date, key, before, variant[key]))
        self.assertGreater(checked, 1000)
        self.assertGreater(tightened, 50)

    def outside_transfer(self, old_rows, *, official_industry="01", official_name="水泥工業", listing="20261008", report="1151012", duplicate=False):
        """Official TWSE 6200 in a group that is NOT required (cement by default), listed after both cutoffs, with the given old tpex rows."""
        w = self.transfer(info=self.old_tpex_rows(*old_rows),
                          twse=lambda w: w.twse[:-1] + [twse("6200", official_industry, listing, report=report)])
        w.info = [{**row, "industry_category": official_name} if row["stock_id"] == "6200" and row.get("type") == "twse" else row for row in w.info]
        if duplicate:
            w.twse.append(twse("6200", official_industry, listing))
        return w

    def assertOnly(self, snapshot, rejected, reason=None):
        """Exactly the given groups are rejected at both cutoffs (all with ``reason`` when given); the others keep the baseline members."""
        for cutoff in (C1, C2):
            for group in (SEMI, OPTO, CULT):
                if group in rejected:
                    self.assertRejected(snapshot, cutoff, group, *([reason] if reason else []))
                else:
                    self.assertUsable(snapshot, (cutoff, group))
                    self.assertEqual(self.outcomes(snapshot)[(cutoff, group)].members, EXPECTED[(cutoff, group)], (cutoff, group))

    def test_o1_transfer_rule_runs_for_official_rows_outside_the_required_groups(self):
        everything = (SEMI, OPTO, CULT)
        # An old name that reaches a required group rejects it (a conflict with the official group), and nothing else.
        for name, group in (("半導體業", SEMI), ("光電業", OPTO), ("文化創意業", CULT)):
            with self.subTest(old=name):
                snapshot, _, _ = pending(self.outside_transfer([info("6200", "tpex", name, day="2026-10-10")]))
                self.assertOnly(snapshot, (group,), "board_transfer_industry_conflict")
        # A name outside section 2 could belong to any group, with a known or an unknown date.
        for name in ("", "存託憑證", "未知產業", None):
            with self.subTest(old=name, date="known"):
                row = {**info("6200", "tpex", "x", day="2026-10-10"), "industry_category": name}
                snapshot, _, _ = pending(self.outside_transfer([row]))
                self.assertOnly(snapshot, everything, "board_transfer_old_industry_unknown")
            for label, raw in UNKNOWN_DATES:
                with self.subTest(old=name, date=label):
                    row = dated({**info("6200", "tpex", "x"), "industry_category": name}, raw)
                    snapshot, _, _ = pending(self.outside_transfer([row]))
                    self.assertOnly(snapshot, everything, "board_transfer_old_industry_unknown")
        # An unknown date with a name of a required group rejects that group.
        for label, raw in UNKNOWN_DATES:
            with self.subTest(date=label):
                snapshot, _, _ = pending(self.outside_transfer([dated(info("6200", "tpex", "半導體業"), raw)]))
                self.assertOnly(snapshot, (SEMI,), "board_transfer_evidence_date_unknown")
        # Evidence older than both cutoffs and tied newest rows reject the groups the names reach.
        snapshot, _, _ = pending(self.outside_transfer([info("6200", "tpex", "半導體業", day="2026-10-01")]))
        self.assertOnly(snapshot, (SEMI,), "board_transfer_evidence_before_cutoff")
        snapshot, _, _ = pending(self.outside_transfer([info("6200", "tpex", "存託憑證", day="2026-10-01")]))
        self.assertOnly(snapshot, everything, "board_transfer_old_industry_unknown")
        snapshot, _, _ = pending(self.outside_transfer([info("6200", "tpex", "半導體業", day="2026-10-10"), info("6200", "tpex", "光電業", day="2026-10-10")]))
        self.assertOnly(snapshot, (SEMI, OPTO), "board_transfer_ambiguous")
        snapshot, _, _ = pending(self.outside_transfer([info("6200", "tpex", "半導體業", day="2026-10-10"), info("6200", "tpex", "存託憑證", day="2026-10-10")]))
        self.assertOnly(snapshot, everything, "board_transfer_old_industry_unknown")
        # Names of groups that are not required reach nothing; a history row older than the newest is ignored.
        for rows in ([info("6200", "tpex", "食品工業", day="2026-10-10")], [info("6200", "tpex", "鋼鐵工業", day="2026-10-10")],
                     [dated(info("6200", "tpex", "食品工業"), "x")], [info("6200", "tpex", "食品工業", day="2026-10-01")],
                     [info("6200", "tpex", "食品工業", day="2026-10-10"), info("6200", "tpex", "鋼鐵工業", day="2026-10-10")],
                     [info("6200", "tpex", "存託憑證", day="2026-10-06"), info("6200", "tpex", "食品工業", day="2026-10-10")]):
            with self.subTest(rows=[row["industry_category"] for row in rows]):
                self.assertAllSix(pending(self.outside_transfer(rows))[0])
        # Not a transfer: listed on or before the cutoff, no listing date, or no old tpex row at all.
        evidence = [info("6200", "tpex", "半導體業", day="2026-10-10")]
        self.assertAllSix(pending(self.outside_transfer(evidence, listing="20260105"))[0])
        snapshot, _, _ = pending(self.outside_transfer(evidence, listing=None))  # O-3: an unknown listing date is not "not a transfer"
        self.assertOnly(snapshot, (SEMI,), "board_transfer_listing_date_unknown")
        self.assertAllSix(pending(self.outside_transfer([]))[0])
        # Rows that cannot be members are evaluated too, and the evaluation never adds a member.
        for report in ("x", None, "20261012"):
            snapshot, _, _ = pending(self.outside_transfer(evidence, report=report))
            self.assertOnly(snapshot, (SEMI,), "board_transfer_industry_conflict")
        snapshot, _, _ = pending(self.outside_transfer(evidence, duplicate=True))
        self.assertOnly(snapshot, (SEMI,), "board_transfer_industry_conflict")
        snapshot, _, _ = pending(self.outside_transfer([info("6200", "tpex", "", day="2026-10-10")], duplicate=True))
        self.assertOnly(snapshot, everything, "board_transfer_old_industry_unknown")

    def test_o1_reverse_direction_reaches_the_groups_of_the_old_twse_rows(self):
        def reverse(official_industry, *old_rows):
            w = world()
            w.tpex.append(tpex("6300", official_industry, "20261008"))
            w.info += [info("6300", "tpex", "金融業" if official_industry == "17" else "半導體業")] + list(old_rows)
            return pending(w)[0]
        # Official TPEx row outside the required groups (financial, 17): the old TWSE identity may have been a member of a required group.
        self.assertOnly(reverse("17", info("6300", "twse", "半導體業", day="2026-10-08")), (SEMI,), "board_transfer_reverse_direction")
        self.assertOnly(reverse("17", info("6300", "twse", "光電業", day="2026-10-08")), (OPTO,), "board_transfer_reverse_direction")
        self.assertOnly(reverse("17", info("6300", "twse", "存託憑證", day="2026-10-08")), (SEMI, OPTO, CULT), "board_transfer_old_industry_unknown")
        self.assertOnly(reverse("17", dated(info("6300", "twse", "半導體業"), "x")), (SEMI,), "board_transfer_reverse_direction")
        self.assertAllSix(reverse("17", info("6300", "twse", "食品工業", day="2026-10-08")))
        # A required official group is rejected as before, together with the groups of the old names; a name outside section 2 rejects all.
        self.assertOnly(reverse("24", info("6300", "twse", "光電業", day="2026-10-08")), (SEMI, OPTO), "board_transfer_reverse_direction")
        self.assertOnly(reverse("24", info("6300", "twse", "存託憑證", day="2026-10-08")), (SEMI, OPTO, CULT), "board_transfer_old_industry_unknown")
        # A TWSE section 2 name is not a TPEx one: the culture board does not exist on TWSE, so its name is outside section 2 there.
        self.assertOnly(reverse("17", info("6300", "twse", "文化創意業", day="2026-10-08")), (SEMI, OPTO, CULT), "board_transfer_old_industry_unknown")

    def test_o2_tied_newest_old_rows_with_a_name_outside_section_two_reject_all_three_groups(self):
        everything = (SEMI, OPTO, CULT)
        for other in ("存託憑證", "", "未知產業", None):
            with self.subTest(other=other):
                rows = [info("6200", "tpex", "半導體業", day="2026-10-08"), {**info("6200", "tpex", "x", day="2026-10-08"), "industry_category": other}]
                snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(*rows)))
                self.assertOnly(snapshot, everything, "board_transfer_old_industry_unknown")
                self.assertIn("board_transfer_ambiguous", self.outcomes(snapshot)[(C1, SEMI)].reasons)
        # Names that all belong to section 2 keep the ambiguity rejection, now for every required group they reach.
        snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "半導體業", day="2026-10-08"), info("6200", "tpex", "光電業", day="2026-10-08"))))
        self.assertOnly(snapshot, (SEMI, OPTO), "board_transfer_ambiguous")
        snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "光電業", day="2026-10-08"), info("6200", "tpex", "文化創意業", day="2026-10-08"))))
        self.assertOnly(snapshot, everything, "board_transfer_ambiguous")
        snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "半導體業", day="2026-10-08"), info("6200", "tpex", "食品工業", day="2026-10-08"))))
        self.assertOnly(snapshot, (SEMI,), "board_transfer_ambiguous")
        # An older, non-tied row with a bad name is history.
        snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "存託憑證", day="2026-10-03"), info("6200", "tpex", "半導體業", day="2026-10-08"))))
        self.assertIn(("TPEx", "6200"), self.outcomes(snapshot)[(C1, SEMI)].members)
        # Evidence older than the cutoffs and unique but outside section 2: all three; section 2: the groups reached.
        snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "存託憑證", day="2026-10-01"))))
        self.assertOnly(snapshot, everything, "board_transfer_old_industry_unknown")
        snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(info("6200", "tpex", "光電業", day="2026-10-01"))))
        self.assertOnly(snapshot, (SEMI, OPTO), "board_transfer_evidence_before_cutoff")

    def test_o3_an_official_listing_date_that_is_unknown_is_treated_like_an_undated_old_row(self):
        forms = (MISSING, None, "x", "20261340", 20261005, "", "2026-10-08", "1130431")
        everything = (SEMI, OPTO, CULT)

        def with_listing(w, raw):
            if raw is MISSING:
                w.twse[-1].pop("上市日期")
            else:
                w.twse[-1]["上市日期"] = raw
            return w
        for raw in forms:
            # Official TWSE 6200 in a required group (semiconductor): its own group is rejected for the missing listing date, and the
            # old tpex rows (all of them) decide what else: groups their names reach, or all three for a name outside section 2.
            for label, old_rows, rejected, reason in (
                    ("same group", [info("6200", "tpex", "半導體業", day="2026-10-08")], (SEMI,), "board_transfer_listing_date_unknown"),
                    ("other group", [info("6200", "tpex", "光電業", day="2026-10-08")], (SEMI, OPTO), "board_transfer_listing_date_unknown"),
                    ("old row undated", [dated(info("6200", "tpex", "光電業"), None)], (SEMI, OPTO), "board_transfer_listing_date_unknown"),
                    ("outside section 2", [info("6200", "tpex", "存託憑證", day="2026-10-08")], everything, "board_transfer_old_industry_unknown"),
                    ("history row outside section 2", [info("6200", "tpex", "存託憑證", day="2026-10-01"), info("6200", "tpex", "半導體業", day="2026-10-08")],
                     everything, "board_transfer_old_industry_unknown"),
                    ("section 2 but not required", [info("6200", "tpex", "食品工業", day="2026-10-08")], (SEMI,), "listing_date_missing_or_invalid")):
                with self.subTest(listing=raw, case=label):
                    snapshot, _, _ = pending(with_listing(self.transfer(info=self.old_tpex_rows(*old_rows)), raw))
                    self.assertOnly(snapshot, rejected, reason)
                    self.assertIn("listing_date_missing_or_invalid", self.outcomes(snapshot)[(C1, SEMI)].reasons)  # the existing rule stays
            with self.subTest(listing=raw, case="no old row"):  # nothing to be a transfer of: only the existing reason
                snapshot, _, _ = pending(with_listing(self.transfer(info=self.old_tpex_rows()), raw))
                self.assertOnly(snapshot, (SEMI,), "listing_date_missing_or_invalid")
                self.assertNotIn("board_transfer_listing_date_unknown", self.outcomes(snapshot)[(C1, SEMI)].reasons)
            # Official TWSE 6200 in a group that is not required: no listing rule of its own, but the same transfer evaluation.
            for label, old_rows, rejected, reason in (
                    ("required name", [info("6200", "tpex", "半導體業", day="2026-10-08")], (SEMI,), "board_transfer_listing_date_unknown"),
                    ("two required names", [info("6200", "tpex", "半導體業", day="2026-10-06"), info("6200", "tpex", "光電業", day="2026-10-08")],
                     (SEMI, OPTO), "board_transfer_listing_date_unknown"),
                    ("outside section 2", [info("6200", "tpex", "", day="2026-10-08")], everything, "board_transfer_old_industry_unknown"),
                    ("old row undated", [dated(info("6200", "tpex", "文化創意業"), "x")], (CULT,), "board_transfer_listing_date_unknown")):
                with self.subTest(listing=raw, case="outside: " + label):
                    w = self.outside_transfer(old_rows, listing=None if raw is MISSING else raw)
                    if raw is MISSING:
                        w.twse[-1].pop("上市日期")
                    snapshot, _, _ = pending(w)
                    self.assertOnly(snapshot, rejected, reason)
            with self.subTest(listing=raw, case="outside: names reach nothing"):
                for old_rows in ([info("6200", "tpex", "食品工業", day="2026-10-08")], [dated(info("6200", "tpex", "鋼鐵工業"), None)], []):
                    w = self.outside_transfer(old_rows, listing=None if raw is MISSING else raw)
                    if raw is MISSING:
                        w.twse[-1].pop("上市日期")
                    self.assertAllSix(pending(w)[0])
        # Rows that cannot be members are evaluated too, and a valid listing date on or before the cutoff is not a transfer at all.
        evidence = [info("6200", "tpex", "半導體業", day="2026-10-08")]
        for report in ("x", None):
            snapshot, _, _ = pending(self.outside_transfer(evidence, listing=None, report=report))
            self.assertOnly(snapshot, (SEMI,), "board_transfer_listing_date_unknown")
        snapshot, _, _ = pending(self.outside_transfer(evidence, listing=None, duplicate=True))
        self.assertOnly(snapshot, (SEMI,), "board_transfer_listing_date_unknown")
        self.assertAllSix(pending(self.outside_transfer(evidence, listing="20260105"))[0])
        # Reverse direction: an official TPEx row without a listing date and an older twse row.
        def reverse(official_industry, *old_rows, listing=None):
            w = world()
            w.tpex.append(tpex("6300", official_industry, listing))
            w.info += [info("6300", "tpex", "金融業" if official_industry == "17" else "半導體業")] + list(old_rows)
            return pending(w)[0]
        self.assertOnly(reverse("17", info("6300", "twse", "半導體業", day="2026-10-08")), (SEMI,), "board_transfer_listing_date_unknown")
        self.assertOnly(reverse("17", info("6300", "twse", "存託憑證", day="2026-10-08")), everything, "board_transfer_old_industry_unknown")
        self.assertOnly(reverse("17", info("6300", "twse", "文化創意業", day="2026-10-08")), everything, "board_transfer_old_industry_unknown")  # TWSE has no culture board
        self.assertOnly(reverse("24", info("6300", "twse", "光電業", day="2026-10-08")), (SEMI, OPTO), "board_transfer_listing_date_unknown")
        self.assertAllSix(reverse("17", info("6300", "twse", "食品工業", day="2026-10-08")))
        self.assertAllSix(reverse("17"))

    def test_o4_a_finmind_row_with_an_unusable_type_is_old_evidence_of_either_exchange(self):
        everything = (SEMI, OPTO, CULT)
        unusable_types = (None, "", " ", 5, "None", MISSING)

        def typeless(raw, name, day="2026-10-08"):
            row = {**info("6200", "tpex", "x", day=day), "industry_category": name, "type": raw}
            if raw is MISSING:
                row.pop("type")
            return row
        for raw in unusable_types:
            # Official TWSE 6200 in a required group: its group is rejected, with every required group the name reaches under
            # either exchange's section 2 table (the culture board exists only on TPEx); outside both tables: all three.
            for name, rejected, reason in (("半導體業", (SEMI,), "board_transfer_type_unknown"), ("光電業", (SEMI, OPTO), "board_transfer_type_unknown"),
                                           ("文化創意業", (SEMI, CULT), "board_transfer_type_unknown"), ("食品工業", (SEMI,), "board_transfer_type_unknown"),
                                           ("生技醫療業", (SEMI,), "board_transfer_type_unknown"),
                                           ("存託憑證", everything, "board_transfer_old_industry_unknown"), ("", everything, "board_transfer_old_industry_unknown"),
                                           (None, everything, "board_transfer_old_industry_unknown")):
                with self.subTest(type=raw, name=name):
                    snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(typeless(raw, name))))
                    self.assertOnly(snapshot, rejected, reason)
            # Whatever its date: unknown or older than both cutoffs.
            for day in ("2026-10-01", None, "x"):
                with self.subTest(type=raw, day=day):
                    snapshot, _, _ = pending(self.transfer(info=self.old_tpex_rows(dated(typeless(raw, "光電業"), day))))
                    self.assertOnly(snapshot, (SEMI, OPTO), "board_transfer_type_unknown")
            # Official row outside the required groups (cement), listed after the cutoffs, with a missing listing date, or a row that cannot be a member.
            for name, rejected, reason in (("半導體業", (SEMI,), "board_transfer_type_unknown"), ("光電業", (OPTO,), "board_transfer_type_unknown"),
                                           ("文化創意業", (CULT,), "board_transfer_type_unknown"),
                                           ("存託憑證", everything, "board_transfer_old_industry_unknown")):
                for kwargs in ({}, {"listing": None}, {"report": "x"}, {"duplicate": True}):
                    with self.subTest(type=raw, outside=name, **{k: str(v) for k, v in kwargs.items()}):
                        snapshot, _, _ = pending(self.outside_transfer([typeless(raw, name)], **kwargs))
                        self.assertOnly(snapshot, rejected, reason)
            self.assertAllSix(pending(self.outside_transfer([typeless(raw, "食品工業")]))[0])  # a name that reaches nothing
        # A valid listing date on or before the cutoff is not a transfer: nothing to evaluate, the stock stays a member.
        for raw in unusable_types:
            w = self.transfer(info=self.old_tpex_rows(typeless(raw, "光電業")))
            w.twse[-1] = twse("6200", "24", "20260105")
            snapshot, _, _ = pending(w)
            for cutoff in (C1, C2):
                self.assertUsable(snapshot, (cutoff, SEMI), (cutoff, OPTO), (cutoff, CULT))
                self.assertIn(("TWSE", "6200"), self.outcomes(snapshot)[(cutoff, SEMI)].members)
        # A type that is usable but unlisted (emerging) is a real other board, not an unknown type.
        self.assertAllSix(pending(self.outside_transfer([typeless("emerging", "半導體業")]))[0])
        # Reverse direction and the only FinMind row of the stock.
        def reverse(official_industry, row):
            w = world()
            w.tpex.append(tpex("6300", official_industry, "20261008"))
            w.info += [info("6300", "tpex", "金融業" if official_industry == "17" else "半導體業"), row]
            return pending(w)[0]
        for raw in unusable_types:
            row = {**info("6300", "twse", "光電業", day="2026-10-08"), "type": raw}
            if raw is MISSING:
                row.pop("type")
            self.assertOnly(reverse("17", row), (OPTO,), "board_transfer_type_unknown")
            self.assertOnly(reverse("24", row), (SEMI, OPTO), "board_transfer_type_unknown")
        w = world()
        w.twse.append(twse("6201", "24", "20261008"))
        w.info.append({**info("6201", "twse", "半導體業"), "type": None})  # the stock's only row: both the type rule and the latest-row rule apply
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertRejected(snapshot, cutoff, SEMI, "board_transfer_type_unknown", "info_type_unusable")
            self.assertUsable(snapshot, (cutoff, OPTO), (cutoff, CULT))

    @staticmethod
    def nonzero(counts):
        return {key: value for key, value in counts.items() if value}

    def test_census_vocabulary_is_enumerated_and_bounded(self):
        sizes = {name: {field: len(classes) for field, classes in fields.items()} for name, fields in source.CENSUS_VOCABULARY.items()}
        self.assertEqual(sizes, {"info": {"date": 13, "stock_id": 12, "type": 9, "industry_category": 9},
                                 "delisting": {"date": 13, "stock_id": 12},
                                 "twse": {"report_date": 11, "code": 9, "industry_code": 10, "listing_date": 12},
                                 "tpex": {"report_date": 11, "code": 9, "industry_code": 10, "listing_date": 12}})
        self.assertEqual(source.CENSUS_SOURCES, ("info", "twse", "tpex", "delisting"))
        self.assertEqual(len(source._CENSUS_KEYS), 160)  # 152 class counters + rows and rows_not_object for each of four sources
        for name, fields in source.CENSUS_VOCABULARY.items():
            for field, classes in fields.items():
                self.assertEqual(len(set(classes)), len(classes), (name, field))
                for klass in classes:
                    self.assertIn(f"census_{name}_{field}_{klass}", source._CENSUS_KEYS)
        for key in source._CENSUS_KEYS:
            self.assertTrue(re.fullmatch(r"census_[a-z]+_[a-z0-9_]+", key) and len(key) <= 64, key)
        self.assertEqual(source.DATE_CLASSES, ("missing", "json_null", "non_string", "empty", "blank", "null_text", "iso_valid", "iso_future",
                                               "iso_invalid_calendar", "iso_with_time", "digits8", "slash_date", "other_string"))

    def test_baseline_census_counts_every_row_by_form(self):
        snapshot, _, _ = pending()
        inspected = snapshot.inspection()
        census = inspected["census"]
        self.assertEqual(set(census), {"info", "twse", "tpex", "delisting"})
        self.assertEqual((census["info"]["rows"], census["twse"]["rows"], census["tpex"]["rows"], census["delisting"]["rows"]), (22, 7, 13, 2))
        self.assertEqual(tuple(record["rows_not_object"] for record in census.values()), (0, 0, 0, 0))
        info_census = census["info"]
        self.assertEqual(self.nonzero(info_census["date"]), {"iso_valid": 22})
        self.assertEqual(self.nonzero(info_census["stock_id"]), {"ordinary": 21, "alnum_mixed": 1})
        self.assertEqual(self.nonzero(info_census["type"]), {"twse": 9, "tpex": 12, "other_string": 1})
        self.assertEqual(self.nonzero(info_census["industry_category"]), {"required_name": 15, "other_name": 3, "unknown_name": 4})
        self.assertEqual(self.nonzero(census["twse"]["report_date"]), {"roc7_valid": 7})
        self.assertEqual(self.nonzero(census["twse"]["code"]), {"ordinary": 7})
        self.assertEqual(self.nonzero(census["twse"]["industry_code"]), {"required_group": 4, "other_group": 2, "unmapped_two_digit": 1})
        self.assertEqual(self.nonzero(census["twse"]["listing_date"]), {"gregorian8": 7})
        self.assertEqual(self.nonzero(census["tpex"]["report_date"]), {"roc7_valid": 13})
        self.assertEqual(self.nonzero(census["tpex"]["industry_code"]), {"required_group": 10, "other_group": 1, "unmapped_two_digit": 1, "empty": 1})
        self.assertEqual(self.nonzero(census["tpex"]["listing_date"]), {"gregorian8": 10, "roc7": 2, "ymd_slash": 1})
        self.assertEqual(self.nonzero(census["delisting"]["date"]), {"iso_valid": 2})
        self.assertEqual(self.nonzero(census["delisting"]["stock_id"]), {"ordinary": 1, "digits_other_length": 1})
        self.assertCensusIdentities(snapshot)
        # Immutable counts only.
        with self.assertRaises(TypeError):
            census["info"] = {}
        with self.assertRaises(TypeError):
            census["info"]["date"]["iso_valid"] = 0
        for record in census.values():
            for value in record.values():
                for count in (value.values() if isinstance(value, types.MappingProxyType) else (value,)):
                    self.assertIs(type(count), int)

    def test_census_counts_odd_forms_in_every_source_and_sums_to_the_object_rows(self):
        w = world()
        w.info += [dated(info("2330", "twse", "半導體業"), raw) for _, raw in UNKNOWN_DATES]  # 12 rows, one per odd date form
        w.info += [{**info("0", "twse", "x"), "stock_id": raw} for raw in (None, "", "  ", 7, "none", "9" * 33, "00878", "AB12", "a-b", "２３３０")]
        w.info += [{**info("1", "twse", "x"), "type": raw, "industry_category": raw} for raw in (None, "", " ", 5, "NA", "emerging", "tpex")]
        w.twse += [{**twse(raw if isinstance(raw, str) else "7000", "zz", "x", report="20261012"), "公司代號": raw} for raw in
                   ("2330A", "233", " 2330", None, "", "N/A", 5)]
        w.tpex += [tpex("9999", raw, raw, report=raw) for raw in (None, "", "  ", 9, "nat", "99", "x")]
        w.delist += [{**delist("1", "2026-10-08"), "stock_id": raw, "date": raw} for raw in (None, "", "  ", 3, "NaN", "2026-02-30", "20261001", "2026/10/01")]
        snapshot, _, _ = build(w)
        snapshot.acquire()
        inspected = snapshot.inspection()
        census = inspected["census"]
        self.assertCensusIdentities(snapshot)
        self.assertEqual(self.nonzero(census["info"]["date"]), {
            "iso_valid": 22 + 10 + 7, "missing": 1, "json_null": 1, "non_string": 1, "empty": 1, "blank": 1, "null_text": 1, "iso_future": 1,
            "iso_invalid_calendar": 1, "iso_with_time": 1, "digits8": 1, "slash_date": 1, "other_string": 1})
        self.assertEqual(self.nonzero(census["info"]["stock_id"]), {
            "ordinary": 21 + 12, "alnum_mixed": 1 + 1, "json_null": 1, "empty": 1, "blank": 1, "non_string": 1, "null_text": 1, "oversize": 1,
            "digits_other_length": 1 + 7, "other_ascii": 1, "non_ascii": 1})  # "00878" and the seven rows of stock "1"
        self.assertEqual(self.nonzero(census["info"]["type"]), {
            "twse": 9 + 12 + 10, "tpex": 12 + 1, "other_string": 1 + 1, "json_null": 1, "empty": 1, "blank": 1, "non_string": 1, "null_text": 1})
        self.assertEqual(self.nonzero(census["twse"]["code"]), {
            "ordinary": 7, "grammar_non_ordinary": 1, "bad_grammar": 2, "json_null": 1, "empty": 1, "null_text": 1, "non_string": 1})
        self.assertEqual(self.nonzero(census["twse"]["report_date"]), {"roc7_valid": 7, "digits8": 7})
        self.assertEqual(self.nonzero(census["twse"]["industry_code"]), {
            "required_group": 4, "other_group": 2, "unmapped_two_digit": 1, "other_string": 7})
        self.assertEqual(self.nonzero(census["tpex"]["report_date"]), {"roc7_valid": 13, "json_null": 1, "empty": 1, "blank": 1, "non_string": 1,
                                                                        "null_text": 1, "other_string": 2})
        self.assertEqual(self.nonzero(census["delisting"]["date"]), {
            "iso_valid": 2, "json_null": 1, "empty": 1, "blank": 1, "non_string": 1, "null_text": 1, "iso_invalid_calendar": 1, "digits8": 1, "slash_date": 1})
        self.assertEqual(self.nonzero(census["delisting"]["stock_id"]), {
            "ordinary": 1, "digits_other_length": 2, "json_null": 1, "empty": 1, "blank": 1, "non_string": 1, "null_text": 1, "other_ascii": 2})
        # No rows are lost: the odd rows are rows of the parse, so the oracle counts equal the census rows.
        self.assertEqual(inspected["row_counts"], tuple(census[name]["rows"] for name in source.CENSUS_SOURCES))

    def test_census_survives_structural_failures_in_the_diagnostics(self):
        w = world()
        w.info[5] = "2330"
        snapshot, _, _ = build(w)
        error = self.assertFailure("row_not_object", snapshot.acquire)
        flat = {key: value for key, value in error.diagnostics.items() if key.startswith("census_")}
        self.assertEqual(flat["census_info_rows"], 22)
        self.assertEqual(flat["census_info_rows_not_object"], 1)
        self.assertEqual(flat["census_info_date_iso_valid"], 21)  # only object rows are classified
        self.assertEqual(sum(value for key, value in flat.items() if key.startswith("census_info_date_")), 21)
        self.assertFalse([key for key in flat if not key.startswith("census_info_")])  # only the sources parsed so far
        self.assertEqual(len(flat), 2 + 13 + 12 + 9 + 9)
        self.assertEqual(snapshot.ledger.attempted, (0,))
        self.assertEqual(set(snapshot.inspection()["census"]), {"info"})
        self.assertEqual({key: value for key, value in snapshot.diagnostics.items() if key.startswith("census_")}, flat)
        # A later source fails: the census of every source parsed so far is in the failure, not the unreached ones.
        w = world()
        w.tpex[0] = tpex("3105", "24", "1100304", report="1151011")
        snapshot, _, _ = build(w)
        error = self.assertFailure("official_report_date_not_uniform", snapshot.acquire)
        self.assertEqual(error.diagnostics["source_index"], 2)
        names = {key.split("_")[1] for key in error.diagnostics if key.startswith("census_")}
        self.assertEqual(names, {"info", "twse", "tpex"})
        self.assertEqual(error.diagnostics["census_tpex_report_date_roc7_valid"], 13)
        self.assertEqual(error.diagnostics["census_tpex_rows"], 13)
        self.assertEqual(set(snapshot.inspection()["census"]), {"info", "twse", "tpex"})
        # A failure after the parse (the seven-stock pool) carries the census as well.
        w = world()
        w.tpex[5] = tpex("8069", "27", "20110101")
        snapshot, _, _ = build(w)
        error = self.assertFailure("seven_stock_group_not_required", snapshot.acquire)
        self.assertEqual(error.diagnostics["census_tpex_industry_code_required_group"], 9)
        self.assertEqual(error.diagnostics["census_info_rows"], 22)
        self.assertNotIn("census_delisting_rows", error.diagnostics)
        # A transport failure before any parse has no census at all.
        snapshot, _, _ = build(transport=Transport(fail_at=0))
        error = self.assertFailure("transport_or_parse_failure", snapshot.acquire)
        self.assertFalse([key for key in error.diagnostics if key.startswith("census_")])
        self.assertEqual(dict(snapshot.inspection()["census"]), {})
        # The failing body's own structural rejection (an outer shape error) happens before any row is counted.
        payload = bodies(world())
        payload[0] = b'{"status":200,"msg":"success","data":[]}'
        snapshot, _, _ = build(transport=Transport(payload))
        error = self.assertFailure("finmind_rows", snapshot.acquire)
        self.assertFalse([key for key in error.diagnostics if key.startswith("census_")])

    def test_failure_values_whitelists_census_keys_values_and_names(self):
        def values(**diagnostics):
            return source._failure_values(source.SourceError("row_not_object", **diagnostics), "batch")
        good = {"census_info_rows": 5, "census_info_rows_not_object": 0, "census_info_date_iso_valid": 3, "census_delisting_stock_id_empty": 200000,
                "census_twse_listing_date_invalid_calendar": 0, "census_tpex_industry_code_unmapped_two_digit": 1}
        kept = values(**good)
        self.assertEqual({key: value for key, value in kept.items() if key.startswith("census_")}, good)
        self.assertEqual(values(**{key: value for key, value in kept.items() if key != "code"}), kept)  # idempotent
        for name in ("census_info_date_secret", "census_evil_rows", "census_info_rows_extra", "census_info_date", "census", "census_",
                     "census_twse_listing_date_unknown", "census_info_stock_id_DIGITS_OTHER_LENGTH", "census_info_date_iso_valid ",
                     "census_info_type_iso_valid", "census_delisting_type_twse", "uncovered_census_info_rows"):
            with self.subTest(name=name):
                self.assertFalse([key for key in values(**{name: 3}) if key.startswith("census")], name)
        for raw in (True, False, -1, 200001, 1.0, "3", None, 10 ** 30, [3], b"3", float("nan")):
            with self.subTest(value=raw):
                self.assertNotIn("census_info_rows", values(census_info_rows=raw))
        self.assertEqual(values(census_info_rows=0)["census_info_rows"], 0)
        self.assertEqual(values(census_info_rows=source.MAX_ROWS)["census_info_rows"], source.MAX_ROWS)
        # The explicit bag is validated the same way and merged with what the exception already carries.
        merged = source._failure_values(source.SourceError("x", census_info_rows=4), "batch",
                                        census={"census_twse_rows": 7, "census_twse_date": 1, "bogus": 2, "census_tpex_rows": True})
        self.assertEqual({key: value for key, value in merged.items() if key.startswith("census")}, {"census_info_rows": 4, "census_twse_rows": 7})
        self.assertEqual(sum(1 for key in source._failure_values(source.SourceError("x", **{key: 1 for key in source._CENSUS_KEYS}), "batch")
                             if key.startswith("census_")), 160)
        # Plain failures carry no census keys.
        self.assertFalse([key for key in source._failure_values(source.SourceError("http_status", source_index=1), "x") if key.startswith("census")])
        self.assertFalse([key for key in source._failure_values(OSError("x"), "x") if key.startswith("census")])

    def test_census_and_diagnostics_never_retain_raw_strings(self):
        w = world()
        secret = "SECRET-VALUE-DO-NOT-RETAIN"
        w.info += [{**info(secret[:32], "twse", secret), "date": secret, "type": secret},
                   {**info("1111", secret, secret), "date": secret + "2", "stock_id": secret * 3}]
        w.twse += [{**twse("SECRET", secret, secret, report=secret), "公司代號": secret[:6]}, {**twse("1", secret, secret, report=secret), "公司代號": secret}]
        w.tpex += [tpex(secret, secret, secret, report=secret)]
        w.delist += [delist(secret, secret), delist(secret * 2, "2026-10-08")]
        snapshot, _, _ = build(w)
        snapshot.acquire()
        self.assertNotIn("SECRET", repr(dict(snapshot.inspection()["census"])))
        self.assertNotIn("SECRET", repr(dict(snapshot.inspection()["d_set_difference"])))
        self.assertNotIn("SECRET", repr(dict(snapshot.inspection()["stock_resolution"])))
        self.assertNotIn("SECRET", repr(dict(snapshot.inspection()["excluded_non_ordinary"])))
        for outcome in self.outcomes(snapshot).values():
            self.assertNotIn("SECRET", repr(outcome.reasons))
        # The same rows with a structural failure behind them: the diagnostics carry only enumerated counters.
        w.info.append(7)
        snapshot, _, _ = build(w)
        error = self.assertFailure("row_not_object", snapshot.acquire)
        self.assertNotIn("SECRET", repr(dict(error.diagnostics)))
        self.assertNotIn("SECRET", repr(dict(snapshot.diagnostics)))
        self.assertNotIn("SECRET", repr(dict(snapshot.inspection()["census"])))

    def test_stock_resolution_counts_partition_the_ordinary_stocks(self):
        w = world()
        w.info += [info("2330", "twse", "半導體業", day="2026-10-10"),  # same value again: order cannot matter
                   info("2454", "twse", "光電業", day="2026-09-01"),  # older different value: the newest date decides
                   info("3008", "twse", "半導體業"),  # same newest date, another value: tied
                   dated(info("2409", "twse", "半導體業"), "x"),  # different value, unknown date: undecided and reaches the groups
                   dated(info("1101", "twse", "食品工業"), "x")]  # undecided but reaches no required group
        snapshot, _, _ = pending(w)
        counts = snapshot.inspection()["stock_resolution"]
        self.assertEqual(tuple(counts), source.RESOLUTION_STATES)
        self.assertEqual(dict(counts), {"single_row": 16, "same_value": 1, "newest_unique": 1, "newest_tied": 1,
                                        "date_unresolved_related": 1, "date_unresolved_unrelated": 1})
        self.assertEqual(sum(counts.values()), len({row["stock_id"] for row in w.info if re.fullmatch(r"[0-9]{4}", row["stock_id"])}))
        self.assertAllCountsAreInts(counts)
        # The state is the same before and after oracle admission, and after a failed parse of a later source it still reads what was parsed.
        self.admitAsInferred(snapshot)
        self.assertEqual(dict(snapshot.inspection()["stock_resolution"]), dict(counts))
        failing = world()
        failing.tpex[0] = tpex("3105", "24", "1100304", report="1151011")
        snapshot, _, _ = build(failing)
        self.assertFailure("official_report_date_not_uniform", snapshot.acquire)
        self.assertEqual(sum(snapshot.inspection()["stock_resolution"].values()), 21)  # the parsed Info rows stay readable after a failed batch

    def assertAllCountsAreInts(self, mapping):
        for value in mapping.values():
            self.assertIs(type(value), int)

    def difference(self, snapshot):
        return {cutoff: {group: dict(counts) for group, counts in groups.items()}
                for cutoff, groups in snapshot.inspection()["d_set_difference"].items()}

    def test_d_set_difference_counts_the_gap_between_the_two_sources(self):
        zero = {"official_only": 0, "finmind_only_explained": 0, "finmind_only_unexplained": 0}
        snapshot, _, _ = pending()
        self.assertEqual(self.difference(snapshot), {cutoff: {group: dict(zero) for group in (SEMI, OPTO, CULT)} for cutoff in (C1, C2)})
        self.assertEqual(source.DIFFERENCE_KEYS, ("official_only", "finmind_only_explained", "finmind_only_unexplained"))
        # Official lists a stock FinMind lacks.
        w = world()
        w.info.__delitem__(11)  # 5347 (TPEx, Semiconductor)
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertEqual(self.difference(snapshot)[cutoff][SEMI], {**zero, "official_only": 1})
            self.assertRejected(snapshot, cutoff, SEMI, "cross_source_mismatch")
            self.assertEqual(self.difference(snapshot)[cutoff][OPTO], zero)
        # FinMind lists stocks the official feed lacks (kept, never named: counts only).
        w = world()
        w.info += [info("2999", "twse", "半導體業"), info("2998", "twse", "半導體業"), info("2997", "tpex", "文化創意業")]
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertEqual(self.difference(snapshot)[cutoff][SEMI], {**zero, "finmind_only_unexplained": 2})
            self.assertEqual(self.difference(snapshot)[cutoff][CULT], {**zero, "finmind_only_unexplained": 1})
        # A FinMind-only stock delisted inside [C, D] is explained; one delisted exactly on C1 is explained at C1 and not at C2.
        w = world()
        w.info += [info("5555", "twse", "半導體業"), info("5556", "tpex", "光電業"), info("5557", "tpex", "半導體業")]
        w.delist += [delist("5555", "2026-10-08"), delist("5556", "2026-10-05"), delist("5557", "2026-10-04")]
        snapshot, _, _ = pending(w)
        diff = self.difference(snapshot)
        self.assertEqual(diff[C1][SEMI], {**zero, "finmind_only_explained": 1, "finmind_only_unexplained": 1})  # 5557 left before C1
        self.assertEqual(diff[C2][SEMI], {**zero, "finmind_only_explained": 1, "finmind_only_unexplained": 1})
        self.assertEqual(diff[C1][OPTO], {**zero, "finmind_only_explained": 1})
        self.assertEqual(diff[C2][OPTO], {**zero, "finmind_only_unexplained": 1})
        self.assertRejected(snapshot, C1, SEMI, "cross_source_mismatch")
        self.assertRejected(snapshot, C1, OPTO, "delisting_date_equals_cutoff")
        self.assertRejected(snapshot, C2, OPTO, "cross_source_mismatch")
        # Stocks without a decided FinMind newest row are not in the FinMind set, so official lists them as official-only.
        w = world()
        w.info.append(dated(info("2330", "twse", "光電業"), "x"))
        snapshot, _, _ = pending(w)
        for cutoff in (C1, C2):
            self.assertEqual(self.difference(snapshot)[cutoff][SEMI], {**zero, "official_only": 1})

    def test_d_set_difference_agrees_with_the_mismatch_reason_and_is_counts_only(self):
        worlds = []
        for index in range(6):
            w = world()
            if index == 1:
                w.info.append(info("2999", "twse", "半導體業"))
            elif index == 2:
                w.info.__delitem__(0)
            elif index == 3:
                w.info += [info("5555", "twse", "光電業")]
                w.delist.append(delist("5555", "2026-10-08"))
            elif index == 4:
                w.twse.append(twse("2999", "26", "19940905"))
            elif index == 5:
                w.tpex[7] = tpex("6999", "24", "20261005", report="x")
            worlds.append(w)
        for w in worlds:
            snapshot, _, _ = pending(w)
            for (cutoff, group), outcome in self.outcomes(snapshot).items():
                counts = self.difference(snapshot)[cutoff][group]
                self.assertEqual(counts["official_only"] + counts["finmind_only_unexplained"] > 0, "cross_source_mismatch" in outcome.reasons,
                                 (cutoff, group, counts))
                self.assertEqual(set(counts), set(source.DIFFERENCE_KEYS))
                for count in counts.values():
                    self.assertIs(type(count), int)
        diff = snapshot.inspection()["d_set_difference"]
        self.assertEqual(set(diff), {C1, C2})
        self.assertEqual(set(diff[C1]), {SEMI, OPTO, CULT})
        with self.assertRaises(TypeError):
            diff[C1] = {}
        with self.assertRaises(TypeError):
            diff[C1][SEMI]["official_only"] = 9
        self.assertNotIn("2999", repr(dict(diff)))

    def test_d_set_difference_exists_only_once_inference_has_completed(self):
        snapshot, _, _ = build()
        with self.assertRaises(source.SourceError):
            snapshot.inspection()  # new: nothing to inspect
        snapshot.acquire()
        self.assertEqual(snapshot.state, "pending")
        self.assertEqual(len(self.difference(snapshot)), 2)  # readable before the oracle admission
        snapshot.admit_independent_verification(admission(snapshot))
        self.assertEqual(snapshot.state, "available")
        self.assertEqual(len(self.difference(snapshot)), 2)
        # A batch that fails before inference has none; a wrong oracle assertion ends the snapshot and clears it.
        failing = world()
        failing.tpex[5] = tpex("8069", "27", "20110101")
        snapshot, _, _ = build(failing)
        self.assertFailure("seven_stock_group_not_required", snapshot.acquire)
        self.assertEqual(dict(snapshot.inspection()["d_set_difference"]), {})
        snapshot, _, _ = pending()
        wrong = entries(rejected=((C1, SEMI),))
        self.assertFailure("oracle_set_mismatch", snapshot.admit_independent_verification, admission(snapshot, expected=wrong))
        self.assertEqual(dict(snapshot.inspection()["d_set_difference"]), {})
        snapshot, _, _ = pending()
        snapshot.release()
        self.assertFailure("inspection_unavailable", snapshot.inspection)

    def test_bare_nan_and_infinity_literals_are_non_string_values_not_parse_failures(self):
        base = world()
        for literal in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(literal=literal):
                rows = [{**info("2330", "twse", "半導體業"), "date": "LITERAL"}, {**info("2454", "twse", "半導體業"), "type": "LITERAL"},
                        {**info("0", "twse", "半導體業"), "stock_id": "LITERAL"}, {**info("0", "twse", "半導體業"), "industry_category": "LITERAL"}]
                rest = [row for row in base.info if row["stock_id"] not in ("2330", "2454")]
                payload = bodies(base)
                payload[0] = finmind_body(rest + rows).replace(b'"LITERAL"', literal)
                payload[1] = official_body(base.twse[:6] + [{**twse("9999", "24", "20000101"), "產業別": "LITERAL"}]).replace(b'"LITERAL"', literal)
                payload[3] = finmind_body(base.delist + [{**delist("1234", "2026-10-08"), "date": "LITERAL"}]).replace(b'"LITERAL"', literal)
                snapshot, _, _ = pending(transport=Transport(payload))
                census = snapshot.inspection()["census"]
                self.assertEqual(census["info"]["date"]["non_string"], 1)
                self.assertEqual(census["info"]["type"]["non_string"], 1)
                self.assertEqual(census["info"]["stock_id"]["non_string"], 1)
                self.assertEqual(census["info"]["industry_category"]["non_string"], 1)
                self.assertEqual(census["twse"]["industry_code"]["non_string"], 1)
                self.assertEqual(census["delisting"]["date"]["non_string"], 1)
        # In a structural position the literal still fails the document check.
        for body in (b'{"status":NaN,"msg":"success","data":[]}', b'{"status":200,"msg":NaN,"data":[]}'):
            payload = bodies(base)
            payload[0] = body
            snapshot, _, _ = build(transport=Transport(payload))
            self.assertFailure("finmind_document_status", snapshot.acquire)
        payload = bodies(base)
        payload[0] = b'{"status":200,"msg":"success","data":NaN}'
        snapshot, _, _ = build(transport=Transport(payload))
        self.assertFailure("finmind_rows", snapshot.acquire)
        # Duplicate keys remain structural.
        payload = bodies(base)
        payload[1] = b'[{"a":1,"a":NaN}]'
        snapshot, _, _ = build(transport=Transport(payload))
        self.assertFailure("duplicate_json_key", snapshot.acquire)

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
                 ("twse no usable report date", lambda w: setattr(w, "twse", [{**r, "出表日期": "20261012"} for r in w.twse]), "official_report_date", (0, 1)),
                 ("tpex no usable report date", lambda w: setattr(w, "tpex", [{**r, "Date": None} for r in w.tpex]), "official_report_date", (0, 1, 2)),
                 ("info row not an object", lambda w: w.info.__setitem__(0, "2330"), "row_not_object", (0,)),
                 ("twse row not an object", lambda w: w.twse.__setitem__(0, [1]), "row_not_object", (0, 1)),
                 ("tpex row not an object", lambda w: w.tpex.__setitem__(0, None), "row_not_object", (0, 1, 2)),
                 ("delisting row not an object", lambda w: w.delist.__setitem__(0, 7), "row_not_object", (0, 1, 2, 3)))
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
                 ("namespace", dict(namespace=NAMESPACE.replace("qa2", "qa1")), "oracle_scope"),
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
            (1, b'[{"a":1},]', "json_invalid"), (1, b"[NaN]", "row_not_object"),
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


def rich_world():
    """The baseline plus a board transfer, FinMind-only delisted stocks, multi-row stocks and in-window delistings."""
    w = world()
    w.twse += [twse("6200", "24", "20261008"), twse("6201", "24", "20261009")]
    w.info += [info("6200", "twse", "半導體業"), info("6200", "tpex", "半導體業", day="2026-10-08"),
               info("5555", "twse", "半導體業"), info("5556", "tpex", "光電業"), info("5558", "tpex", "文化創意業"),
               info("2330", "twse", "光電業", day="2026-09-01"), info("3008", "twse", "水泥工業", day="2026-09-01"),
               info("1101", "twse", "食品工業", day="2026-09-01"),
               info("6201", "twse", "半導體業"), info("6201", "tpex", "半導體業", day="2026-10-09"),
               info("5559", "tpex", "半導體業", day="2026-10-01"), info("5559", "tpex", "文化創意業", day="2026-10-10")]
    w.delist += [delist("6200", "2026-10-08"), delist("5555", "2026-10-08"), delist("5556", "2026-10-05"), delist("5558", "2026-10-09"),
                 delist("2409", "2026-10-09"), delist("9998", "2026-10-04"), delist("2002", "2026-10-06"), delist("5559", "2026-10-08")]
    return w


class FuzzTests(Base):
    @staticmethod
    def set_field(row, key, raw):
        if raw is MISSING:
            row.pop(key, None)
        else:
            row[key] = raw

    def date_mutations(self, w):
        """Every place a date can turn unknown, with the pool of unknown forms valid there."""
        unknown = tuple(raw for _, raw in UNKNOWN_DATES)
        delisting_unknown = tuple(raw for label, raw in UNKNOWN_DATES if label != "iso_future")
        listing_unknown = (None, 20261011, "", "   ", "None", "2026-02-30", "yesterday", "2026-10-11T00:00:00Z", MISSING)
        places = [(row, "date", unknown) for row in w.info] + [(row, "date", delisting_unknown) for row in w.delist]
        for feed, report_key, listing_key in ((w.twse, "出表日期", "上市日期"), (w.tpex, "Date", "DateOfListing")):
            places += [(row, report_key, unknown) for row in feed[1:]]  # the first row keeps the feed's report date usable
            places += [(row, listing_key, listing_unknown) for row in feed]
        return places

    def test_unknown_dates_only_tighten_never_add_members_or_lift_rejections(self):
        rng = random.Random(37)
        baseline, _, _ = pending(rich_world())
        before = baseline.inspection()["outcomes"]
        self.assertTrue(any(outcome.rejected for outcome in before.values()))
        self.assertTrue(any(not outcome.rejected for outcome in before.values()))
        tightened = unchanged = 0
        for iteration in range(300):
            w = rich_world()
            places = self.date_mutations(w)
            for row, key, pool in rng.sample(places, rng.randint(1, 5)):
                self.set_field(row, key, rng.choice(pool))
            snapshot, _, _ = pending(w)
            after = snapshot.inspection()["outcomes"]
            for key, old in before.items():
                new = after[key]
                if old.rejected:
                    self.assertTrue(new.rejected, (iteration, key))
                elif new.rejected:
                    tightened += 1
                else:
                    unchanged += 1
                    self.assertEqual((new.members, new.flags), (old.members, old.flags), (iteration, key))
        self.assertGreater(tightened, 20)
        self.assertGreater(unchanged, 20)

    def test_garbage_values_never_fail_the_batch_and_the_counters_stay_consistent(self):
        rng = random.Random(3737)
        garbage = (None, "", " ", "None", "NaN", 0, 1, True, False, 1.5, [], {}, "x", "x" * 40, "２３３０", "2330 ", "00878", "TAIEX", "2026-02-30",
                   "2026-10-11T00:00:00", "20261011", "2026/10/11", "1151012", "24", "26", "32", "半導體業", "光電業", "文化創意業", "twse", "tpex", MISSING)
        outcomes_seen = {"pending": 0, "seven": 0}
        for iteration in range(300):
            w = rich_world()
            places = []
            for row in w.info:
                places += [(row, key) for key in ("date", "stock_id", "type", "industry_category")]
            for row in w.delist:
                places += [(row, key) for key in ("date", "stock_id")]
            for feed, keys in ((w.twse, ("出表日期", "公司代號", "產業別", "上市日期")), (w.tpex, ("Date", "SecuritiesCompanyCode", "SecuritiesIndustryCode", "DateOfListing"))):
                for position, row in enumerate(feed):
                    places += [(row, key) for index, key in enumerate(keys) if not (position == 0 and index == 0)]
            for row, key in rng.sample(places, rng.randint(1, 8)):
                self.set_field(row, key, rng.choice(garbage))
            snapshot, _, _ = build(w)
            try:
                snapshot.acquire()
            except source.SourceError as error:
                # The seven-stock pool is the only value-dependent whole-batch check; everything else is a group-level unknown.
                self.assertEqual(error.code, "seven_stock_group_not_required", (iteration, error.code, dict(error.diagnostics)))
                self.assertEqual(snapshot.ledger.attempted, (0, 1, 2))
                self.assertTrue([key for key in error.diagnostics if key.startswith("census_tpex_")])
                self.assertCensusIdentities(snapshot)
                outcomes_seen["seven"] += 1
                continue
            outcomes_seen["pending"] += 1
            self.assertEqual((snapshot.state, snapshot.ledger.attempted), ("pending", (0, 1, 2, 3)), iteration)
            self.assertCensusIdentities(snapshot)
            inspected = snapshot.inspection()
            distinct = {row.stock_id for row in snapshot._info if row.stock_id is not None and re.fullmatch(r"[0-9]{4}", row.stock_id)}
            self.assertEqual(sum(inspected["stock_resolution"].values()), len(distinct), iteration)
            self.assertEqual(len(inspected["outcomes"]), 6)
            for (cutoff, group), outcome in inspected["outcomes"].items():
                counts = inspected["d_set_difference"][cutoff][group]
                if not outcome.rejected:
                    self.assertEqual((outcome.reasons, counts["official_only"], counts["finmind_only_unexplained"]), ((), 0, 0), (iteration, cutoff, group))
                self.assertEqual(bool(outcome.reasons), outcome.rejected)
                if "cross_source_mismatch" in outcome.reasons:
                    self.assertGreater(counts["official_only"] + counts["finmind_only_unexplained"], 0)
            # The independent oracle path still works: admit exactly what the inference says.
            self.admitAsInferred(snapshot)
        self.assertGreater(outcomes_seen["pending"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
