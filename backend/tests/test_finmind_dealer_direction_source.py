"""Standalone synthetic boundary runner for the Issue 9 FinMind dealer source; no source requests or artifacts.

Run from the repository root: python -B -X utf8 backend/tests/test_finmind_dealer_direction_source.py

Stdlib only, no conftest. Reads only this test and the product source file. The external policy below is the
task coordinator's draft v2 (Issue 9 comment 6125240011, 9,319 B), pasted as a literal and pinned by the
constants beside it; the product receives policy bytes and pin from this runner and can derive neither. Every
network name resolution and connection is refused by an audit hook, subprocess launch and disk writes too, so
no case here makes a real request. Response-shape cases are canned wire bytes parsed by the real http.client;
the corpus is synthetic (constructed so that its sums satisfy the 56 policy anchors) and is not source truth.
"""
from __future__ import annotations

import dataclasses
import hashlib
import http.client
import importlib.util
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "backend/app/finmind_dealer_direction_source.py"
GUARD_EVENTS = []


def _audit_boundary(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname", "subprocess.Popen"):
        GUARD_EVENTS.append(event)
        raise AssertionError("standalone boundary runner forbids network, name resolution and process launch")
    if event == "open":
        _, mode, flags = args
        if (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            GUARD_EVENTS.append(event)
            raise AssertionError("standalone boundary runner forbids disk writes")


if not sys.dont_write_bytecode:
    raise RuntimeError("Use -B: the boundary runner does not permit bytecode artifacts")


def load_module(name="issue9_dealer_source"):
    """A fresh module object (the process-wide real ledger lives in module globals)."""
    spec = importlib.util.spec_from_file_location(name, SOURCE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


source = load_module()
sys.addaudithook(_audit_boundary)

EXTERNAL_POLICY = b'{"ac_revision":"2a","acquisition":{"accept":"application/json","accept_encoding":"identity","attempted_is_spent":true,"batch_seconds":180,"body_cap_bytes":1048576,"connection":"close","credentials":"no token, cookie or proxy","deadline":"cooperative","max_gets":7,"namespace":"issue9-dealer-direction-combos-finmind-v1/qa1","order":"seven symbols ascending as listed","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608,"user_agent":"stock-lab-issue9-local-ram/1"},"anchor_only_dates":["2026-09-29"],"anchors":{"formal_blob":"116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md","formal_blob_sha256":"f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240","formal_section":"47.6 (issue36 official TPEx CSV, shares)","gate":"whole batch rejects unless all 56 values match exactly before available","mapping":{"dealer_self_plus_hedging":"sum of Dealer_self net + Dealer_Hedging net","foreign_investor":"sum of Foreign_Investor net","investment_trust":"sum of Investment_Trust net","three_total":"foreign_investor + investment_trust + dealer_self_plus_hedging (Foreign_Dealer_Self excluded)"},"values":{"2026-10-05":{"3105":{"dealer_self_plus_hedging":2350894,"foreign_investor":28396840,"investment_trust":2812800,"three_total":33560534},"3293":{"dealer_self_plus_hedging":-12792,"foreign_investor":6386218,"investment_trust":414000,"three_total":6787426},"5274":{"dealer_self_plus_hedging":10254,"foreign_investor":-28586,"investment_trust":-40427,"three_total":-58759},"5347":{"dealer_self_plus_hedging":339261,"foreign_investor":323290,"investment_trust":3600607,"three_total":4263158},"6488":{"dealer_self_plus_hedging":-62262,"foreign_investor":354337,"investment_trust":1179529,"three_total":1471604},"6510":{"dealer_self_plus_hedging":32887,"foreign_investor":186887,"investment_trust":-594227,"three_total":-374453},"8069":{"dealer_self_plus_hedging":64380,"foreign_investor":-4247384,"investment_trust":-13040,"three_total":-4196044}},"2026-10-06":{"3105":{"dealer_self_plus_hedging":2227304,"foreign_investor":27460450,"investment_trust":2352400,"three_total":32040154},"3293":{"dealer_self_plus_hedging":-11177,"foreign_investor":5507085,"investment_trust":420000,"three_total":5915908},"5274":{"dealer_self_plus_hedging":8894,"foreign_investor":-13315,"investment_trust":-66756,"three_total":-71177},"5347":{"dealer_self_plus_hedging":407416,"foreign_investor":8820683,"investment_trust":3720607,"three_total":12948706},"6488":{"dealer_self_plus_hedging":-11515,"foreign_investor":594644,"investment_trust":1330929,"three_total":1914058},"6510":{"dealer_self_plus_hedging":43724,"foreign_investor":87416,"investment_trust":-660897,"three_total":-529757},"8069":{"dealer_self_plus_hedging":285782,"foreign_investor":-4053731,"investment_trust":-9040,"three_total":-3776989}}},"windows":{"2026-10-05":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]}},"calendar":{"calendar_gets":0,"required_returned_dates":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"rule":"every returned row structurally valid first; rows outside start_date..end_date discarded only after validation; in-range date set of every symbol equals required_returned_dates exactly; no closure inference, no fill, no window shrink","source":"formal verified trading dates, SOURCE_REGISTRY 31.2 (2026-09-25 and 2026-09-28 closed)"},"consumer":{"failure":"any source, pin, schema, name, date, anchor or arithmetic conflict makes all seven unavailable; no skipping, zero fill or window shrink","per_symbol":"daily self/hedge net sign (positive/negative/zero), nine daily combos, opposite-direction day count and dates, per-component direction counts, maximal same-sign segments (zero is its own run and breaks positive/negative runs), latest window-limited segment; first segment earlier_unknown true","trace":"segment -> date -> all five FinMind name rows of that symbol-date (original values, row ordinal, body sha256, receipt sha256, URL) + calendar reference","version":"dealer-self-hedging-direction-combos-five-session-v1"},"cutoff":"2026-10-06","first_availability":"unknown","instrument_type":"ordinary_stock","issue":9,"lease":"held until process exit","lifecycle":"single acquisition inside the QA API process; held for the whole QA browser session; released at process exit; any re-acquisition needs a new quota, namespace and seal","market":"TW/TPEx","profile":"free_public_local","publication_time":"unknown","record_only_comparison":{"expected_zero_set":"within window_dates, among Dealer_self and Dealer_Hedging buy, sell and net for seven symbols (210 values), the only zeros were 5274 Dealer_self sell on 2026-10-05 and 2026-10-06","gate":false,"on_mismatch":"list differences in the receipt; not a source error; no rejection","source":"SOURCE_REGISTRY 46.5 text (issue9 predecessor, official TPEx CSV at 2026-10-08)"},"response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8 (quoted or not); anything else rejects","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM; full EOF and raw hash before parse","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","location":"any location header or 3xx rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure"},"revision_time":"unknown","row_schema":{"buy_sell":"non-bool integer 0..9223372036854775807","date":"ISO YYYY-MM-DD string","envelope":"exactly keys msg, status, data; status 200; msg success; data 1..10000 rows","extra_keys":"reject","keys":["buy","date","name","sell","stock_id"],"names":["Dealer_Hedging","Dealer_self","Foreign_Dealer_Self","Foreign_Investor","Investment_Trust"],"names_rule":"applies to in-range rows (start_date..end_date) after every returned row passed structural validation; each in-range symbol-date has exactly one row per listed name; Dealer or any other name, any missing or duplicate symbol-date-name rejects the whole batch; missing is unknown, never zero","net":"local derived net = buy - sell per row; provider has no net column; every step signed-int64 bounded","stock_id":"string equal to requested data_id","value_label":"API value at acquisition time; buy/sell may later grow by equal same-category late bookings (net unaffected); not PIT"},"source":{"dataset":"TaiwanStockInstitutionalInvestorsBuySell","documentation":"https://finmind.github.io/tutor/TaiwanMarket/Chip/ (doc GET receipt issue9 comment 6124059360, sha256 cfcf26a8269452d0a2c396ca69a5a371bcba68d55b2ab35d432b1ba1de13b5f3); per-stock data_id query carries no backer/sponsor marker; free tokenless use is inferred","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","method":"GET","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-09-29","urls":["https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=3105&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=3293&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=5274&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=5347&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=6488&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=6510&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=8069&start_date=2026-09-29&end_date=2026-10-06"]},"source_use":"local_personal_noncommercial_dealer_self_hedging_direction_combos","storage":"process_RAM","symbols":["3105","3293","5274","5347","6488","6510","8069"],"unit_policy":{"provider_literal_unit_annotation":false,"unit":"shares","verification":"56 five-session net anchors below must match exactly; lots = shares/1000 exact, at most 3 decimals"},"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","other_dates","other_symbols","other_cutoffs","ranking","filtering","price","signal","plan","trading","actionable_strategy","raw_disk_storage","cross_process","db","redistribution","mirror","deployment","official_unit_annotation"],"version":"issue9-dealer-direction-combos-finmind-v2","window_dates":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]}'
EXTERNAL_PIN = "7db5e7a7e17f883e7e4e81de297ce2e4ad8c6c4fcde409b7cbeae0eaa56696b1"
EXTERNAL_BYTES = 9319
# Draft v1 (comment 6124225468) is superseded and must now be refused.
V1_POLICY = b'{"ac_revision":"2a","acquisition":{"accept":"application/json","accept_encoding":"identity","attempted_is_spent":true,"batch_seconds":180,"body_cap_bytes":1048576,"connection":"close","credentials":"no token, cookie or proxy","deadline":"cooperative","max_gets":7,"namespace":"issue9-dealer-direction-combos-finmind-v1/qa1","order":"seven symbols ascending as listed","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608,"user_agent":"stock-lab-issue9-local-ram/1"},"anchor_only_dates":["2026-09-29"],"anchors":{"formal_blob":"116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md","formal_blob_sha256":"f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240","formal_section":"47.6 (issue36 official TPEx CSV, shares)","gate":"whole batch rejects unless all 56 values match exactly before available","mapping":{"dealer_self_plus_hedging":"sum of Dealer_self net + Dealer_Hedging net","foreign_investor":"sum of Foreign_Investor net","investment_trust":"sum of Investment_Trust net","three_total":"foreign_investor + investment_trust + dealer_self_plus_hedging (Foreign_Dealer_Self excluded)"},"values":{"2026-10-05":{"3105":{"dealer_self_plus_hedging":2350894,"foreign_investor":28396840,"investment_trust":2812800,"three_total":33560534},"3293":{"dealer_self_plus_hedging":-12792,"foreign_investor":6386218,"investment_trust":414000,"three_total":6787426},"5274":{"dealer_self_plus_hedging":10254,"foreign_investor":-28586,"investment_trust":-40427,"three_total":-58759},"5347":{"dealer_self_plus_hedging":339261,"foreign_investor":323290,"investment_trust":3600607,"three_total":4263158},"6488":{"dealer_self_plus_hedging":-62262,"foreign_investor":354337,"investment_trust":1179529,"three_total":1471604},"6510":{"dealer_self_plus_hedging":32887,"foreign_investor":186887,"investment_trust":-594227,"three_total":-374453},"8069":{"dealer_self_plus_hedging":64380,"foreign_investor":-4247384,"investment_trust":-13040,"three_total":-4196044}},"2026-10-06":{"3105":{"dealer_self_plus_hedging":2227304,"foreign_investor":27460450,"investment_trust":2352400,"three_total":32040154},"3293":{"dealer_self_plus_hedging":-11177,"foreign_investor":5507085,"investment_trust":420000,"three_total":5915908},"5274":{"dealer_self_plus_hedging":8894,"foreign_investor":-13315,"investment_trust":-66756,"three_total":-71177},"5347":{"dealer_self_plus_hedging":407416,"foreign_investor":8820683,"investment_trust":3720607,"three_total":12948706},"6488":{"dealer_self_plus_hedging":-11515,"foreign_investor":594644,"investment_trust":1330929,"three_total":1914058},"6510":{"dealer_self_plus_hedging":43724,"foreign_investor":87416,"investment_trust":-660897,"three_total":-529757},"8069":{"dealer_self_plus_hedging":285782,"foreign_investor":-4053731,"investment_trust":-9040,"three_total":-3776989}}},"windows":{"2026-10-05":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]}},"calendar":{"calendar_gets":0,"required_returned_dates":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"rule":"every returned row structurally valid first; rows outside start_date..end_date discarded only after validation; in-range date set of every symbol equals required_returned_dates exactly; no closure inference, no fill, no window shrink","source":"formal verified trading dates, SOURCE_REGISTRY 31.2 (2026-09-25 and 2026-09-28 closed)"},"consumer":{"failure":"any source, pin, schema, name, date, anchor or arithmetic conflict makes all seven unavailable; no skipping, zero fill or window shrink","per_symbol":"daily self/hedge net sign (positive/negative/zero), nine daily combos, opposite-direction day count and dates, per-component direction counts, maximal same-sign segments (zero is its own run and breaks positive/negative runs), latest window-limited segment; first segment earlier_unknown true","trace":"segment -> date -> all five FinMind name rows of that symbol-date (original values, row ordinal, body sha256, receipt sha256, URL) + calendar reference","version":"dealer-self-hedging-direction-combos-five-session-v1"},"cutoff":"2026-10-06","first_availability":"unknown","instrument_type":"ordinary_stock","issue":9,"lifecycle":"single acquisition inside the QA API process; held for the whole QA browser session; released at process exit; any re-acquisition needs a new quota, namespace and seal","market":"TW/TPEx","profile":"free_public_local","publication_time":"unknown","record_only_comparison":{"expected_zero_set":"within window_dates, among Dealer_self and Dealer_Hedging buy, sell and net for seven symbols (210 values), the only zeros were 5274 Dealer_self sell on 2026-10-05 and 2026-10-06","gate":false,"on_mismatch":"list differences in the receipt; not a source error; no rejection","source":"SOURCE_REGISTRY 46.5 text (issue9 predecessor, official TPEx CSV at 2026-10-08)"},"response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8 (quoted or not); anything else rejects","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM; full EOF and raw hash before parse","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","location":"any location header or 3xx rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure"},"revision_time":"unknown","row_schema":{"buy_sell":"non-bool integer 0..9223372036854775807","date":"ISO YYYY-MM-DD string","envelope":"exactly keys msg, status, data; status 200; msg success; data 1..10000 rows","extra_keys":"reject","keys":["buy","date","name","sell","stock_id"],"names":["Dealer_Hedging","Dealer_self","Foreign_Dealer_Self","Foreign_Investor","Investment_Trust"],"names_rule":"each symbol-date has exactly one row per listed name; Dealer or any other name, any missing or duplicate symbol-date-name rejects the whole batch; missing is unknown, never zero","net":"local derived net = buy - sell per row; provider has no net column; every step signed-int64 bounded","stock_id":"string equal to requested data_id","value_label":"API value at acquisition time; buy/sell may later grow by equal same-category late bookings (net unaffected); not PIT"},"source":{"dataset":"TaiwanStockInstitutionalInvestorsBuySell","documentation":"https://finmind.github.io/tutor/TaiwanMarket/Chip/ (doc GET receipt issue9 comment 6124059360, sha256 cfcf26a8269452d0a2c396ca69a5a371bcba68d55b2ab35d432b1ba1de13b5f3); per-stock data_id query carries no backer/sponsor marker; free tokenless use is inferred","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","method":"GET","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-09-29","urls":["https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=3105&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=3293&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=5274&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=5347&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=6488&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=6510&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=8069&start_date=2026-09-29&end_date=2026-10-06"]},"source_use":"local_personal_noncommercial_dealer_self_hedging_direction_combos","storage":"process_RAM","symbols":["3105","3293","5274","5347","6488","6510","8069"],"unit_policy":{"provider_literal_unit_annotation":false,"unit":"shares","verification":"56 five-session net anchors below must match exactly; lots = shares/1000 exact, at most 3 decimals"},"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","other_dates","other_symbols","other_cutoffs","ranking","filtering","price","signal","plan","trading","actionable_strategy","raw_disk_storage","cross_process","db","redistribution","mirror","deployment","official_unit_annotation"],"version":"issue9-dealer-direction-combos-finmind-v1","window_dates":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]}'
V1_PIN = "09d96db18af61571d808e767ec344e2b5eb684a789f706335778dde74319908b"
POLICY = json.loads(EXTERNAL_POLICY)
NAMESPACE = "issue9-dealer-direction-combos-finmind-v1/qa1"

SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
DATES = ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")
WINDOW = DATES[1:]
ORDER = ("Foreign_Investor", "Foreign_Dealer_Self", "Investment_Trust", "Dealer_self", "Dealer_Hedging")
ANCHORS = POLICY["anchors"]["values"]
URLS = tuple("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=%s&start_date=2026-09-29&end_date=2026-10-06" % s for s in SYMBOLS)

SEAL_ISSUER = "f0000000-0000-0000-0000-0000000000a1"
SEAL_COORDINATORS = ("f0000000-0000-0000-0000-0000000000b1", "f0000000-0000-0000-0000-0000000000b2")
SEAL_IMPLEMENTERS = ("f0000000-0000-0000-0000-0000000000c1",)
QA_HOLDER = "5d2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d"
SEAL_URL = "https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-9999999999"


def canonical(value):
    """Independent stdlib serialization, never the product's helper."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


# --- Synthetic corpus: per symbol, dealer self/hedge window patterns chosen freely; one residual entry
# absorbs what the policy anchor needs. Foreign/trust: free middle days, ends solved from the anchors.
PATTERNS = {
    "3105": ([4, -3, 6, 2, 5], [-2, 5, -1, 3, -7]),
    "3293": ([-4, -4, 3, 3, -1], [2, -6, -6, 1, 8]),
    "5274": ([4, -3, 6, 2, 5], [3, 3, -2, -2, 1]),
    "5347": ([1, -1, 1, -1, 1], [1, -1, 1, -1, 1]),
    "6488": ([-1, -2, -3, -4, -5], [1, 2, 3, 4, 5]),
    "6510": ([5, 5, 5, 5, 5], [-5, -5, -5, -5, -5]),
    "8069": ([2, 3, -4, -4, -4], [1, -1, -1, 1, 1]),
}


def day_nets(symbol, patterns=None):
    """Return {name: [net per DATES]} satisfying both anchor windows exactly."""
    a, b = ANCHORS["2026-10-05"][symbol], ANCHORS["2026-10-06"][symbol]
    nets = {}
    for key, name in (("foreign_investor", "Foreign_Investor"), ("investment_trust", "Investment_Trust")):
        middle = [1000 * i for i in (1, 2, 3, 4)]
        nets[name] = [a[key] - sum(middle)] + middle + [b[key] - sum(middle)]
    s, h = [list(x) for x in (patterns or PATTERNS)[symbol]]
    residual = b["dealer_self_plus_hedging"] - sum(s) - sum(h)
    for target in (s, h):
        index = next((i for i, v in enumerate(target) if v != 0 and (v > 0) == (residual > 0)), None)
        if index is not None:
            target[index] += residual
            break
    else:
        raise AssertionError("synthetic pattern has no absorber for the dealer anchor")
    total_first = a["dealer_self_plus_hedging"] - sum(x + y for x, y in zip(s[:4], h[:4]))
    nets["Dealer_self"] = [total_first] + s
    nets["Dealer_Hedging"] = [0] + h
    nets["Foreign_Dealer_Self"] = [11, -12, 13, -14, 15, -16]
    return nets


def gross(net, base, zero_sell=False):
    sell = 0 if zero_sell else base + max(-net, 0)
    return (sell + net if zero_sell else base + max(net, 0)), sell


def corpus(patterns=None, zero_sell_5274=True):
    documents = []
    for si, symbol in enumerate(SYMBOLS):
        nets = day_nets(symbol, patterns)
        rows = []
        for di, day in enumerate(DATES):
            for ni, name in enumerate(ORDER):
                net = nets[name][di]
                base = 100 + 7 * si + di + 3 * ni
                zero = zero_sell_5274 and symbol == "5274" and name == "Dealer_self" and day in ("2026-10-05", "2026-10-06")
                buy, sell = gross(net, base, zero)
                assert buy - sell == net and buy >= 0 and sell >= 0
                rows.append({"date": day, "stock_id": symbol, "buy": buy, "name": name, "sell": sell})
        documents.append({"msg": "success", "status": 200, "data": rows})
    return documents


def encode(document):
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def body_docs(documents=None):
    return [encode(d) for d in (documents if documents is not None else corpus())]


def mutated_docs(fn):
    docs = corpus()
    fn(docs)
    return docs


def rows_of(docs, symbol_index):
    return docs[symbol_index]["data"]


def find(docs, symbol, day, name):
    return next(r for r in docs[SYMBOLS.index(symbol)]["data"] if r["date"] == day and r["name"] == name)


def policy_args(mutator=None):
    if mutator is None:
        return {"policy_canonical": EXTERNAL_POLICY, "expected_policy_sha256": EXTERNAL_PIN, "expected_policy_bytes": EXTERNAL_BYTES}
    data = json.loads(EXTERNAL_POLICY)
    mutator(data)
    raw = canonical(data)
    return {"policy_canonical": raw, "expected_policy_sha256": hashlib.sha256(raw).hexdigest(), "expected_policy_bytes": len(raw)}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


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
    def __init__(self, bodies=None, *, response_options=None, clock=None, open_delay=0, fail_at=None):
        self.bodies = bodies or body_docs()
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
        response = Response(self.bodies[index], **self.response_options.get(index, {}))
        self.responses.append(response)
        return response


def build(*, transport=None, clock=None, ledger=None, policy=None, **kwargs):
    transport = transport or Transport()
    clock = clock or Clock()
    snapshot = source.DealerDirectionSource(**(policy or policy_args()), transport=transport,
                                            ledger=ledger or source.AttemptLedger(NAMESPACE), clock=clock, **kwargs)
    return snapshot, transport, clock


def receipt_hash(receipt):
    return hashlib.sha256(canonical({f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt)})).hexdigest()


def admission(snapshot, module=None, **overrides):
    module = module or source
    captures = snapshot.inspection()["captures"]
    values = dict(namespace=NAMESPACE, policy_sha256=snapshot.policy_sha256, holder_session_id="synthetic-boundary-oracle",
                  candidate_sha="a" * 40, script_sha256="b" * 64,
                  receipt_sha256s=tuple(receipt_hash(c.receipt) for c in captures),
                  name_rows=210, stock_days=42, anchor_values=56, record_only_matches=True, independent=True)
    values.update(overrides)
    return module.OracleAdmission(**values)


def admission_stub():
    return source.OracleAdmission(NAMESPACE, EXTERNAL_PIN, "x", "a" * 40, "b" * 64, (), 210, 42, 56, True, True)


def available(**kwargs):
    snapshot, transport, clock = build(**kwargs)
    snapshot.acquire()
    snapshot.admit_independent_verification(admission(snapshot))
    return snapshot, transport, clock


def declaration(holder=QA_HOLDER, model="claude-sonnet-5-5", effort="xhigh", url=SEAL_URL, module=None, **start_overrides):
    # Pure configuration; these synthetic declarations never reach a real network path.
    module = module or source
    binding = module.ExecutionBinding(holder, model, effort, "a" * 40, "b" * 64, "c" * 64, "NOAUTH RAM pure guard; no financial execution")
    values = dict(version="issue9-financial-start-v1", issuer_session_id=SEAL_ISSUER, coordinator_session_ids=SEAL_COORDINATORS,
                  implementer_session_ids=SEAL_IMPLEMENTERS, namespace=NAMESPACE, policy_sha256=EXTERNAL_PIN,
                  seal_comment_url=url, binding=binding, authorized=True, whole_batch=True)
    values.update(start_overrides)
    return module.FinancialStart(**values), binding


# --- Response-shape replay: canned wire bytes -> real http.client parsing -> the real _HTTPSTransport /
# _HTTPSResponse / _capture path through connection_factory composition. Only socket and TLS are replaced.
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


class ReplayConnection:
    def __init__(self, owner, wire, host):
        self.owner, self.host, self.sock, self.timeout = owner, host, ReplaySocket(wire), None
        self.closed = False
        self.response = None

    def connect(self):
        pass

    def request(self, method, target, headers):
        self.owner.requests.append((self.host, method, target, dict(headers)))

    def getresponse(self):
        response = http.client.HTTPResponse(self.sock, method="GET")
        response.begin()
        self.response = response
        return response

    def close(self):
        self.closed = True


class ReplayFactory:
    def __init__(self, wires):
        self.wires, self.requests, self.connections = list(wires), [], []

    def __call__(self, host, timeout):
        connection = ReplayConnection(self, self.wires[len(self.connections)], host)
        self.connections.append(connection)
        return connection


def wire(body, *, headers=None, status="200 OK", chunked=False, with_length=True):
    head = ["HTTP/1.1 " + status, "Content-Type: application/json"]
    if headers is not None:
        head = ["HTTP/1.1 " + status] + list(headers)
    elif chunked:
        head.append("Transfer-Encoding: chunked")
    elif with_length:
        head.append("Content-Length: %d" % len(body))
    payload = body
    if chunked:
        payload = b"".join(b"%x\r\n" % len(body[i:i + 100]) + body[i:i + 100] + b"\r\n" for i in range(0, len(body), 100)) + b"0\r\n\r\n"
    return ("\r\n".join(head) + "\r\n\r\n").encode("ascii") + payload


def real_source(factory, module=None, **kwargs):
    module = module or load_module("issue9_dealer_source_real_%d" % len(sys.modules))
    start, binding = declaration(module=module)
    args = dict(**policy_args(), financial_start=start, execution_binding=binding, connection_factory=factory)
    args.update(kwargs)
    return module, module.DealerDirectionSource(**args)


def expect(case, code, function, *args, **kwargs):
    # Compared by class name: replay cases load fresh module objects whose SourceError classes differ.
    with case.assertRaises(ValueError) as caught:
        function(*args, **kwargs)
    case.assertEqual(type(caught.exception).__name__, "SourceError")
    case.assertEqual(caught.exception.code, code)
    return caught.exception


def fails(code, transport=None, policy=None, **kwargs):
    snapshot, transport, _ = build(transport=transport, policy=policy, **kwargs)
    with_exc = None
    try:
        snapshot.acquire()
    except source.SourceError as exc:
        with_exc = exc
    return snapshot, transport, with_exc


class PolicyTests(unittest.TestCase):
    def test_draft_literal_matches_its_pin_and_is_canonical(self):
        self.assertEqual(len(EXTERNAL_POLICY), EXTERNAL_BYTES)
        self.assertEqual(hashlib.sha256(EXTERNAL_POLICY).hexdigest(), EXTERNAL_PIN)
        self.assertEqual(canonical(POLICY), EXTERNAL_POLICY)

    def test_product_constants_equal_the_independent_literal(self):
        self.assertEqual(source.SYMBOLS, SYMBOLS)
        self.assertEqual(source.REQUIRED_DATES, DATES)
        self.assertEqual(source.WINDOW_DATES, WINDOW)
        self.assertEqual(tuple(source.NAMES), tuple(sorted(ORDER)))
        self.assertEqual(source.URLS, URLS)
        self.assertEqual(source.NAMESPACE, NAMESPACE)
        self.assertEqual(source.USER_AGENT, "stock-lab-issue9-local-ram/1")
        self.assertEqual(list(source.URLS), POLICY["source"]["urls"])
        self.assertEqual(source.ANCHOR_COUNT, 56)

    def test_valid_policy_is_frozen_and_pin_reported(self):
        snapshot, _, _ = build()
        self.assertEqual(snapshot.state, "new")
        self.assertEqual(snapshot.policy_sha256, EXTERNAL_PIN)

    def test_pin_and_input_gates(self):
        good = policy_args()
        expect(self, "policy_pin", source.validate_policy, EXTERNAL_POLICY, "0" * 64, EXTERNAL_BYTES)
        expect(self, "policy_pin", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN, EXTERNAL_BYTES + 1)
        expect(self, "policy_pin_form", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN.upper(), EXTERNAL_BYTES)
        expect(self, "policy_pin_form", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN, 0)
        expect(self, "policy_input_type", source.validate_policy, bytearray(EXTERNAL_POLICY), EXTERNAL_PIN, EXTERNAL_BYTES)
        expect(self, "policy_input_type", source.validate_policy, EXTERNAL_POLICY, EXTERNAL_PIN, True)
        expect(self, "policy_input_type", source.validate_policy, EXTERNAL_POLICY, None, EXTERNAL_BYTES)
        # The product cannot derive the pin: a changed policy with a stale pin is refused.
        stale = EXTERNAL_POLICY.replace(b'"ac_revision":"2a"', b'"ac_revision":"2b"')
        self.assertEqual(len(stale), EXTERNAL_BYTES)
        expect(self, "policy_pin", source.validate_policy, stale, EXTERNAL_PIN, EXTERNAL_BYTES)
        self.assertEqual(source.validate_policy(**good)["version"], "issue9-dealer-direction-combos-finmind-v2")

    def raw_args(self, raw):
        return (raw, hashlib.sha256(raw).hexdigest(), len(raw))

    def test_canonical_form_duplicate_keys_floats_and_encoding(self):
        spaced = json.dumps(POLICY, sort_keys=True).encode("ascii")
        expect(self, "policy_canonical_mismatch", source.validate_policy, *self.raw_args(spaced))
        unsorted = json.dumps(dict(reversed(list(POLICY.items()))), separators=(",", ":")).encode("ascii")
        expect(self, "policy_canonical_mismatch", source.validate_policy, *self.raw_args(unsorted))
        raw = EXTERNAL_POLICY[:-1] + b',"cutoff":"2026-10-06"}'
        expect(self, "duplicate_json_key", source.validate_policy, *self.raw_args(raw))
        raw = EXTERNAL_POLICY.replace(b'"issue":9', b'"issue":9.0')
        expect(self, "float_json_number", source.validate_policy, *self.raw_args(raw))
        expect(self, "nonfinite_json_number", source.validate_policy, *self.raw_args(EXTERNAL_POLICY.replace(b'"issue":9', b'"issue":NaN')))
        expect(self, "policy_encoding", source.validate_policy, *self.raw_args(b"\xff\xfe"))
        expect(self, "policy_encoding", source.validate_policy, *self.raw_args(b"{"))
        expect(self, "policy_encoding", source.validate_policy, *self.raw_args(b"\xef\xbb\xbf" + EXTERNAL_POLICY))

    def test_shape_and_type_gates(self):
        def drop(path):
            def mutate(data):
                node = data
                for key in path[:-1]:
                    node = node[key]
                del node[path[-1]]
            return mutate

        def add(path):
            def mutate(data):
                node = data
                for key in path:
                    node = node[key]
                node["extra"] = "x"
            return mutate

        for mutator, code in (
                (drop(("cutoff",)), "policy_keys"), (add(()), "policy_keys"), (drop(("lease",)), "policy_keys"),
                (drop(("acquisition", "namespace")), "policy_keys"), (add(("acquisition",)), "policy_keys"),
                (drop(("row_schema", "net")), "policy_keys"), (add(("source",)), "policy_keys"),
                (lambda d: d.update(issue="9"), "policy_type"), (lambda d: d["acquisition"].update(max_gets=7.0), "float_json_number"),
                (lambda d: d["acquisition"].update(retries=False), "policy_type"),
                (lambda d: d.update(symbols=d["symbols"][:6]), "policy_list"),
                (lambda d: d.update(unsupported=[]), "policy_list"),
                (lambda d: d.update(unsupported=["x", 1]), "policy_type"),
                (lambda d: d["anchors"].update(values=[]), "policy_type")):
            with self.subTest(code=code):
                args = policy_args(mutator)
                expect(self, code, source.validate_policy, args["policy_canonical"], args["expected_policy_sha256"], args["expected_policy_bytes"])

    def test_semantic_cross_checks_against_the_module(self):
        cases = (
            (lambda d: d["acquisition"].update(namespace=NAMESPACE.replace("qa1", "qa2")), "policy_acquisition"),
            (lambda d: d["acquisition"].update(user_agent="stock-lab-issue32-local-ram/1"), "policy_acquisition"),
            (lambda d: d["acquisition"].update(max_gets=8), "policy_acquisition"),
            (lambda d: d["acquisition"].update(redirects=1), "policy_acquisition"),
            (lambda d: d["acquisition"].update(retries=1), "policy_acquisition"),
            (lambda d: d["acquisition"].update(body_cap_bytes=2097152), "policy_acquisition"),
            (lambda d: d["acquisition"].update(batch_seconds=181), "policy_acquisition"),
            (lambda d: d["acquisition"].update(stop_on_first_failure=False), "policy_acquisition"),
            (lambda d: d["acquisition"].update(attempted_is_spent=False), "policy_acquisition"),
            (lambda d: d["source"].update(dataset="TaiwanStockPrice"), "policy_source"),
            (lambda d: d["source"].update(provider="TPEx"), "policy_source"),
            (lambda d: d["source"].update(start_date="2026-09-28"), "policy_source"),
            (lambda d: d["source"].update(urls=list(reversed(d["source"]["urls"]))), "policy_source"),
            (lambda d: d["source"].update(query_order=["dataset", "start_date", "data_id", "end_date"]), "policy_source"),
            (lambda d: d["row_schema"].update(names=["Dealer"] + d["row_schema"]["names"][1:]), "policy_row_schema"),
            (lambda d: d["row_schema"].update(keys=["buy", "date", "name", "sell", "Note"]), "policy_row_schema"),
            (lambda d: d.update(version="issue9-dealer-direction-combos-finmind-v3"), "policy_identity"),
            (lambda d: d.update(source_use="x"), "policy_identity"),
            (lambda d: d.update(issue=32), "policy_identity"),
            (lambda d: d.update(ac_revision="2"), "policy_identity"),
            (lambda d: d.update(cutoff="2026-10-05"), "policy_identity"),
            (lambda d: d.update(window_dates=d["window_dates"][::-1]), "policy_scope"),
            (lambda d: d.update(symbols=d["symbols"][::-1]), "policy_scope"),
            (lambda d: d.update(anchor_only_dates=["2026-09-28"]), "policy_scope"),
            (lambda d: d["calendar"].update(calendar_gets=1), "policy_calendar"),
            (lambda d: d["calendar"].update(required_returned_dates=d["calendar"]["required_returned_dates"][::-1]), "policy_calendar"),
            (lambda d: d["record_only_comparison"].update(gate=True), "policy_record_only"),
            (lambda d: d["consumer"].update(version="x"), "policy_consumer"),
            (lambda d: d.update(lease="expires after 180 s"), "policy_lease"),
            (lambda d: d.update(version="issue9-dealer-direction-combos-finmind-v1"), "policy_identity"),
            (lambda d: d.update(storage="disk"), "policy_fixed_fields"),
            (lambda d: d.update(market="TW/TWSE"), "policy_fixed_fields"),
            (lambda d: d.update(publication_time="2026-10-06T09:00:00Z"), "policy_fixed_fields"),
            (lambda d: d.update(revision_time="none"), "policy_fixed_fields"),
            (lambda d: d["unit_policy"].update(unit="lots"), "policy_unit"),
            (lambda d: d["unit_policy"].update(provider_literal_unit_annotation=True), "policy_unit"),
            (lambda d: d.update(unsupported=[x for x in d["unsupported"] if x != "raw_disk_storage"]), "policy_unsupported"),
            (lambda d: d.update(unsupported=[x for x in d["unsupported"] if x != "historical_pit"]), "policy_unsupported"),
            (lambda d: d["anchors"]["windows"].update({"2026-10-06": d["anchors"]["windows"]["2026-10-06"][:4]}), "policy_anchor_windows"),
            (lambda d: d["anchors"]["values"].pop("2026-10-05"), "policy_anchor_values"),
            (lambda d: d["anchors"]["values"]["2026-10-05"].pop("3105"), "policy_anchor_values"),
            (lambda d: d["anchors"]["values"]["2026-10-05"]["3105"].update(three_total=1), "policy_anchor_total"),
            (lambda d: d["anchors"]["values"]["2026-10-05"]["3105"].update(foreign_investor=2 ** 63, three_total=2 ** 63 + 1), "policy_anchor_values"),
            (lambda d: d["anchors"]["values"]["2026-10-05"]["3105"].pop("three_total"), "policy_keys"),
            (lambda d: d["anchors"].update(formal_blob_sha256="x"), "policy_anchor_blob"),
        )
        for mutator, code in cases:
            with self.subTest(code=code, mutator=mutator.__code__.co_firstlineno):
                snapshot_policy = policy_args(mutator)
                expect(self, code, source.validate_policy, snapshot_policy["policy_canonical"], snapshot_policy["expected_policy_sha256"], snapshot_policy["expected_policy_bytes"])


class ConstructionTests(unittest.TestCase):
    def real(self, **kwargs):
        start, binding = declaration()
        args = dict(**policy_args(), financial_start=start, execution_binding=binding)
        args.update(kwargs)
        return source.DealerDirectionSource(**args)

    def test_purpose_lease_clock_and_ledger_gates(self):
        def construct(**kwargs):
            values = dict(**policy_args(), transport=Transport(), ledger=source.AttemptLedger(NAMESPACE), clock=Clock())
            values.update(kwargs)
            return source.DealerDirectionSource(**values)
        expect(self, "unsupported_purpose", construct, purpose="strategy")
        for lease in (0, -1, 1, 60, 180.5, 86400, 86401, True, False, float("nan"), float("inf"), "60"):
            with self.subTest(lease=lease):
                expect(self, "lease_policy_conflict", construct, lease_seconds=lease)  # R2-2: the policy holds the originals until exit
        self.assertEqual(construct(lease_seconds=None).state, "new")
        expect(self, "clock_or_roots_type", construct, clock=None)
        expect(self, "clock_or_roots_type", construct, observer_roots=1)
        expect(self, "boundary_ledger_required", source.DealerDirectionSource, **policy_args(), transport=Transport())
        expect(self, "quota_namespace", source.AttemptLedger, "issue9-dealer-direction-combos-finmind-v1/qa2")
        wrong = source.AttemptLedger(NAMESPACE)
        wrong.namespace = "other"
        expect(self, "boundary_ledger_required", source.DealerDirectionSource, **policy_args(), transport=Transport(), ledger=wrong)

    def test_roots_cap_applies_at_construction(self):
        expect(self, "retained_roots_estimate_cap", source.DealerDirectionSource, **policy_args(), transport=Transport(),
               ledger=source.AttemptLedger(NAMESPACE), observer_roots=lambda: bytearray(source.ROOTS_CAP + 1))

    def test_default_transport_requires_a_matching_explicit_seal(self):
        expect(self, "financial_start_required", source.DealerDirectionSource, **policy_args())
        start, binding = declaration()
        self.assertEqual(self.real().state, "new")
        expect(self, "financial_start_with_boundary_transport", source.DealerDirectionSource, **policy_args(),
               transport=Transport(), ledger=source.AttemptLedger(NAMESPACE), financial_start=start, execution_binding=binding)
        expect(self, "financial_start_with_boundary_transport", source.DealerDirectionSource, **policy_args(),
               transport=Transport(), ledger=source.AttemptLedger(NAMESPACE), connection_factory=lambda h, t: None)
        expect(self, "default_transport_required_for_financial", self.real, ledger=source.AttemptLedger(NAMESPACE))
        expect(self, "financial_start_required", self.real, financial_start=None)
        expect(self, "financial_start_required", self.real, execution_binding=None)

    def test_seal_declaration_gates(self):
        other_start, other_binding = declaration(holder="6e2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d")
        cases = (
            ("financial_binding_mismatch", dict(financial_start=other_start)),
            ("financial_qa_identity", dict(zip(("financial_start", "execution_binding"), declaration(holder=SEAL_ISSUER)))),
            ("financial_qa_identity", dict(zip(("financial_start", "execution_binding"), declaration(holder=SEAL_COORDINATORS[1])))),
            ("financial_qa_identity", dict(zip(("financial_start", "execution_binding"), declaration(holder=SEAL_IMPLEMENTERS[0])))),
            ("financial_qa_identity", dict(zip(("financial_start", "execution_binding"), declaration(holder="not-a-uuid")))),
            ("financial_qa_identity", dict(zip(("financial_start", "execution_binding"), declaration(effort="high")))),
            ("financial_qa_identity", dict(zip(("financial_start", "execution_binding"), declaration(model="bad model")))),
            ("financial_new_explicit_seal_required", dict(zip(("financial_start", "execution_binding"), declaration(url="https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-9999999999")))),
            ("financial_new_explicit_seal_required", dict(zip(("financial_start", "execution_binding"), declaration(url="https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6124225468")))),
            ("financial_new_explicit_seal_required", dict(zip(("financial_start", "execution_binding"), declaration(url="https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-1")))),
            ("financial_new_explicit_seal_required", dict(zip(("financial_start", "execution_binding"), declaration(url=SEAL_URL + "x")))),
            ("financial_start_scope", dict(zip(("financial_start", "execution_binding"), declaration(version="issue32-financial-start-v1")))),
            ("financial_start_scope", dict(zip(("financial_start", "execution_binding"), declaration(namespace=NAMESPACE.replace("qa1", "qa2"))))),
            ("financial_start_scope", dict(zip(("financial_start", "execution_binding"), declaration(policy_sha256="0" * 64)))),
            ("financial_start_scope", dict(zip(("financial_start", "execution_binding"), declaration(issuer_session_id="bad")))),
            ("financial_start_scope", dict(zip(("financial_start", "execution_binding"), declaration(coordinator_session_ids=(SEAL_ISSUER,))))),
            ("financial_start_scope", dict(zip(("financial_start", "execution_binding"), declaration(implementer_session_ids=(SEAL_COORDINATORS[0],))))),
            ("financial_start_not_authorized", dict(zip(("financial_start", "execution_binding"), declaration(authorized=False)))),
            ("financial_start_not_authorized", dict(zip(("financial_start", "execution_binding"), declaration(whole_batch=False)))),
            ("financial_start_type", dict(zip(("financial_start", "execution_binding"), declaration(coordinator_session_ids=())))),
            ("financial_start_type", dict(zip(("financial_start", "execution_binding"), declaration(seal_comment_url=None)))),
        )
        for code, kwargs in cases:
            with self.subTest(code=code):
                expect(self, code, self.real, **kwargs)
        binding = source.ExecutionBinding(QA_HOLDER, "claude-sonnet-5-5", "xhigh", "short", "b" * 64, "c" * 64, "x")
        start, _ = declaration()
        start = dataclasses.replace(start, binding=binding)
        expect(self, "financial_candidate", self.real, financial_start=start, execution_binding=binding)
        binding = source.ExecutionBinding(QA_HOLDER, "claude-sonnet-5-5", "xhigh", "a" * 40, "b" * 63, "c" * 64, "x")
        start = dataclasses.replace(declaration()[0], binding=binding)
        expect(self, "financial_script_binding", self.real, financial_start=start, execution_binding=binding)
        binding = source.ExecutionBinding(QA_HOLDER, "", "xhigh", "a" * 40, "b" * 64, "c" * 64, "x")
        start = dataclasses.replace(declaration()[0], binding=binding)
        expect(self, "financial_binding_type", self.real, financial_start=start, execution_binding=binding)
        expect(self, "financial_binding_type", self.real, financial_start=dataclasses.replace(declaration()[0], binding=None), execution_binding=declaration()[1])

    def test_ledger_is_one_whole_batch(self):
        ledger = source.AttemptLedger(NAMESPACE)
        expect(self, "quota_order", ledger.charge, 0)
        ledger.begin()
        expect(self, "quota_spent", ledger.begin)
        expect(self, "quota_order", ledger.charge, 1)
        ledger.charge(0)
        self.assertEqual(ledger.attempted, (0,))
        self.assertEqual(ledger.unrun, (1, 2, 3, 4, 5, 6))
        expect(self, "quota_order", ledger.charge, 0)
        expect(self, "quota_order", ledger.charge, True)
        for index in range(1, 7):
            ledger.charge(index)
        expect(self, "quota_order", ledger.charge, 7)
        self.assertFalse(any(hasattr(ledger, name) for name in ("reset", "release", "retry", "clear")))


class LeasePolicyTests(unittest.TestCase):
    HELD = "held until process exit"

    def refuses(self, code, mutator):
        args = policy_args(mutator)
        expect(self, code, source.validate_policy, args["policy_canonical"], args["expected_policy_sha256"], args["expected_policy_bytes"])

    def test_draft_v1_is_superseded_and_refused(self):
        self.assertNotIn("lease", json.loads(V1_POLICY))
        self.assertEqual(hashlib.sha256(V1_POLICY).hexdigest(), V1_PIN)
        expect(self, "policy_pin", source.validate_policy, V1_POLICY, EXTERNAL_PIN, EXTERNAL_BYTES)  # a v1 body under the v2 pin
        expect(self, "policy_keys", source.validate_policy, V1_POLICY, V1_PIN, len(V1_POLICY))  # even with its own pin: no `lease`
        expect(self, "policy_keys", source.DealerDirectionSource, policy_canonical=V1_POLICY, expected_policy_sha256=V1_PIN,
               expected_policy_bytes=len(V1_POLICY), transport=Transport(), ledger=source.AttemptLedger(NAMESPACE), clock=Clock())
        # A v2-shaped policy that still names the v1 version is refused for its identity.
        self.refuses("policy_identity", lambda d: d.update(version="issue9-dealer-direction-combos-finmind-v1"))
        self.assertEqual(source.POLICY_VERSION, "issue9-dealer-direction-combos-finmind-v2")

    def test_lease_is_required_exact_and_typed(self):
        self.assertEqual(POLICY["lease"], self.HELD)
        self.refuses("policy_keys", lambda d: d.pop("lease"))
        for bad in ("held until process exit.", "60", "Held until process exit", " held until process exit", "", "expires after 180 s"):
            with self.subTest(lease=bad):
                self.refuses("policy_lease", lambda d, bad=bad: d.update(lease=bad))
        for bad in (180, None, True, ["held until process exit"], {"v": 1}):
            with self.subTest(lease=bad):
                self.refuses("policy_type", lambda d, bad=bad: d.update(lease=bad))

    def test_provenance_states_the_lifecycle_and_nothing_expires_by_clock(self):
        snapshot, _, clock = build()
        snapshot.acquire()
        clock.now += 10 ** 7
        self.assertEqual(snapshot.state, "pending")  # no clock-based expiry while pending ...
        snapshot.admit_independent_verification(admission(snapshot))
        clock.now += 10 ** 7
        self.assertEqual(snapshot.state, "available")  # ... or while available
        self.assertEqual(snapshot.provenance["lease_policy"], self.HELD)
        self.assertNotIn("lease_expires_monotonic", snapshot.provenance)

    def test_a_caller_lease_is_refused_before_anything_else_is_built(self):
        for lease in (1, 60, 180.5, 86400, 10 ** 9, 0, -1):
            with self.subTest(lease=lease):
                idle = Transport()
                expect(self, "lease_policy_conflict", source.DealerDirectionSource, **policy_args(), transport=idle,
                       ledger=source.AttemptLedger(NAMESPACE), clock=Clock(), lease_seconds=lease)
                self.assertEqual(idle.opens, [])
        # Real path: the same refusal precedes the seal check, so no financial declaration is needed to hit it.
        expect(self, "lease_policy_conflict", source.DealerDirectionSource, **policy_args(), lease_seconds=60)

    def test_expired_is_reachable_only_when_the_lifecycle_owner_declares_it(self):
        # `release(expired=True)` is the one path into `expired`; this is how the state is exercised.
        for admitted in (False, True):
            snapshot, _, clock = build()
            snapshot.acquire()
            if admitted:
                snapshot.admit_independent_verification(admission(snapshot))
                self.assertEqual(snapshot.state, "available")
            snapshot.release(expired=True)
            self.assertEqual(snapshot.state, "expired")
            expect(self, "consumer_unavailable", lambda: snapshot.window_records("3105"))
            expect(self, "consumer_unavailable", lambda: snapshot.receipts)
            expect(self, "consumer_unavailable", lambda: snapshot.provenance)
            expect(self, "inspection_unavailable", snapshot.inspection)
            expect(self, "oracle_pending_required", snapshot.admit_independent_verification, admission_stub())
            expect(self, "snapshot_already_attempted", snapshot.acquire)
            self.assertEqual(snapshot.ledger.attempted, tuple(range(7)))  # expiry never refunds the quota
        plain, _, _ = build()
        plain.acquire()
        plain.release()
        self.assertEqual(plain.state, "released")


class AcquireTests(unittest.TestCase):
    def test_exact_sequence_headers_and_pending_state(self):
        snapshot, transport, _ = build()
        self.assertIs(snapshot.acquire(), snapshot)
        self.assertEqual([url for url, _ in transport.opens], list(URLS))
        self.assertTrue(all(0 < timeout <= 20 for _, timeout in transport.opens))
        self.assertTrue(all(response.closed and response.close_calls == 1 for response in transport.responses))
        self.assertEqual(snapshot.state, "pending")
        self.assertEqual(snapshot.ledger.attempted, tuple(range(7)))
        self.assertEqual(snapshot.ledger.unrun, ())
        captures = snapshot.inspection()["captures"]
        self.assertEqual(len(captures), 7)
        for index, capture in enumerate(captures):
            self.assertEqual(capture.body, transport.bodies[index])
            receipt = capture.receipt
            self.assertEqual((receipt.source_id, receipt.source_version, receipt.method, receipt.url, receipt.status),
                             ("finmind_institutional_investors/" + SYMBOLS[index], "issue9-dealer-direction-combos-finmind-v2", "GET", URLS[index], 200))
            self.assertEqual((receipt.body_bytes, receipt.body_sha256, receipt.full_eof, receipt.content_encoding, receipt.namespace, receipt.policy_sha256),
                             (len(capture.body), hashlib.sha256(capture.body).hexdigest(), True, "identity", NAMESPACE, EXTERNAL_PIN))
            self.assertEqual(receipt.canonical_sha256, receipt_hash(receipt))
            self.assertEqual(receipt.canonical_bytes, canonical({f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt)}))
        self.assertEqual(len({c.receipt.canonical_sha256 for c in captures}), 7)
        self.assertEqual(snapshot.diagnostics, {})

    def test_pending_is_consumer_inert_until_independent_admission(self):
        snapshot, _, _ = build()
        expect(self, "consumer_unavailable", lambda: snapshot.window_records("3105"))  # new
        snapshot.acquire()
        for accessor in (lambda: snapshot.window_records("3105"), lambda: snapshot.receipts, lambda: snapshot.provenance):
            expect(self, "consumer_unavailable", accessor)
        snapshot.admit_independent_verification(admission(snapshot))
        self.assertEqual(snapshot.state, "available")
        self.assertEqual(len(snapshot.receipts), 7)

    def test_available_records_are_the_original_rows_in_original_order(self):
        docs = corpus()
        order = list(range(len(docs[0]["data"])))
        for symbol_index, doc in enumerate(docs):
            doc["data"] = [doc["data"][i] for i in reversed(order)] if symbol_index % 2 else doc["data"]
        snapshot, _, _ = available(transport=Transport(body_docs(docs)))
        for symbol_index, symbol in enumerate(SYMBOLS):
            records = snapshot.window_records(symbol)
            self.assertEqual([r.date for r in records], list(WINDOW))
            for record in records:
                self.assertEqual((record.symbol, record.source_index), (symbol, symbol_index))
                self.assertEqual(sorted(r.name for r in record.rows), sorted(ORDER))
                self.assertEqual([r.row_index for r in record.rows], sorted(r.row_index for r in record.rows))
                for row in record.rows:
                    original = docs[symbol_index]["data"][row.row_index]
                    self.assertEqual((row.date, row.stock_id, row.name, row.buy, row.sell), (original["date"], original["stock_id"], original["name"], original["buy"], original["sell"]))
                    self.assertEqual(row.key_order, tuple(original))
                self.assertIs(record.row("Dealer_self").name == "Dealer_self", True)
            self.assertNotIn("2026-09-29", [r.date for r in records])
        expect(self, "unsupported_scope", snapshot.window_records, "2330")
        expect(self, "unsupported_scope", snapshot.window_records, 3105)

    def test_provenance_is_complete_and_unknowns_stay_unknown(self):
        snapshot, _, _ = available()
        p = snapshot.provenance
        self.assertEqual((p["namespace"], p["policy_sha256"], p["consumer_version"], p["cutoff"]), (NAMESPACE, EXTERNAL_PIN, "dealer-self-hedging-direction-combos-five-session-v1", "2026-10-06"))
        self.assertEqual((p["publication_time"], p["first_availability"], p["revision_time"], p["storage"]), ("unknown", "unknown", "unknown", "process_RAM"))
        self.assertEqual((p["calendar_reference"], p["calendar_gets"], p["anchors_checked"], p["unit"]), ("SOURCE_REGISTRY 31.2", 0, 56, "shares"))
        self.assertEqual((p["required_dates"], p["window_dates"], p["anchor_only_dates"]), (tuple(DATES), tuple(WINDOW), ("2026-09-29",)))
        self.assertIn("not PIT", p["value_label"])
        self.assertIn("historical_pit", p["unsupported"])
        self.assertIs(p["retained_roots_estimate_is_rss_or_peak"], False)
        self.assertTrue(p["record_only_comparison"]["matches"])
        self.assertEqual(p["lease_policy"], "held until process exit")
        self.assertNotIn("lease_expires_monotonic", p)  # no clock-based lease exists any more

    def test_one_shot_snapshot_and_ledger(self):
        snapshot, transport, _ = build()
        snapshot.acquire()
        expect(self, "snapshot_already_attempted", snapshot.acquire)
        self.assertEqual(len(transport.opens), 7)
        idle = Transport()
        other = source.DealerDirectionSource(**policy_args(), transport=idle, ledger=snapshot.ledger, clock=Clock())
        error = expect(self, "quota_spent", other.acquire)
        # R1-2: a spent quota is a FAILED snapshot, never a silent retryable `new`.
        self.assertEqual(other.state, "failed")
        self.assertEqual((other.diagnostics["code"], other.diagnostics["primary_stage"], other.diagnostics["attempts"]), ("quota_spent", "quota", 0))
        self.assertEqual((error.diagnostics["attempts"], error.diagnostics["raw_bytes"]), (0, 0))
        expect(self, "snapshot_already_attempted", other.acquire)
        expect(self, "consumer_unavailable", lambda: other.window_records("3105"))
        self.assertEqual(other.inspection()["captures"], ())
        self.assertEqual(len(snapshot.ledger.attempted), 7)
        self.assertEqual(idle.opens, [])

    def test_release_expiry_and_no_replay(self):
        snapshot, _, clock = available()
        clock.now += 10 ** 6
        self.assertEqual(snapshot.state, "available")  # no clock-based lease
        snapshot.release(expired=True)
        self.assertEqual(snapshot.state, "expired")
        expect(self, "consumer_unavailable", lambda: snapshot.window_records("3105"))
        expect(self, "inspection_unavailable", snapshot.inspection)
        expect(self, "snapshot_already_attempted", snapshot.acquire)
        self.assertEqual(snapshot.ledger.attempted, tuple(range(7)))
        held, _, clock = available()
        clock.now += 10 ** 6
        self.assertEqual(held.state, "available")
        held.release()
        self.assertEqual(held.state, "released")
        expect(self, "consumer_unavailable", lambda: held.window_records("3105"))
        expect(self, "inspection_unavailable", held.inspection)
        expect(self, "snapshot_already_attempted", held.acquire)
        expect(self, "oracle_pending_required", held.admit_independent_verification, admission_stub())
        pending, _, _ = build()
        pending.acquire()
        pending.release(expired=True)
        self.assertEqual(pending.state, "expired")

    def test_clock_must_be_monotonic_and_finite(self):
        class Backwards:
            def __init__(self):
                self.values = iter([100.0, 99.0, 99.0, 99.0])

            def __call__(self):
                return next(self.values, 99.0)
        snapshot, transport, _ = build(clock=Backwards())
        error = expect(self, "invalid_monotonic_clock", snapshot.acquire)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(error.diagnostics["attempts"], 0)
        snapshot, _, _ = build(clock=lambda: float("nan"))
        expect(self, "invalid_monotonic_clock", snapshot.acquire)

    def test_admission_gates(self):
        snapshot, _, _ = build()
        expect(self, "oracle_pending_required", snapshot.admit_independent_verification, object())
        snapshot.acquire()
        good = admission(snapshot)
        hashes = list(good.receipt_sha256s)
        swapped = [hashes[1], hashes[0]] + hashes[2:]
        cases = (
            ("oracle_pending_required", {}, "not-an-admission"),
            ("oracle_type", dict(receipt_sha256s=list(hashes)), None),
            ("oracle_type", dict(name_rows=210.0), None),
            ("oracle_type", dict(independent=1), None),
            ("oracle_type", dict(record_only_matches=None), None),
            ("oracle_scope", dict(namespace=NAMESPACE.replace("qa1", "qa2")), None),
            ("oracle_scope", dict(policy_sha256="0" * 64), None),
            ("oracle_scope", dict(independent=False), None),
            ("oracle_receipt_type", dict(receipt_sha256s=("x",) * 7), None),
            ("oracle_receipt_type", dict(receipt_sha256s=(1,) * 7), None),
            ("oracle_complete_scope", dict(name_rows=209), None),
            ("oracle_complete_scope", dict(stock_days=41), None),
            ("oracle_complete_scope", dict(anchor_values=55), None),
            ("oracle_capture_binding", dict(receipt_sha256s=tuple(swapped)), None),
            ("oracle_capture_binding", dict(receipt_sha256s=tuple(hashes[:6])), None),
            ("oracle_record_only", dict(record_only_matches=False), None),
        )
        for code, override, direct in cases:
            with self.subTest(code=code, override=sorted(override)):
                value = direct if direct is not None else admission(snapshot, **override)
                expect(self, code, snapshot.admit_independent_verification, value)
                self.assertEqual(snapshot.state, "pending")
        snapshot.admit_independent_verification(good)
        self.assertEqual(snapshot.state, "available")
        expect(self, "oracle_pending_required", snapshot.admit_independent_verification, good)

    def test_failed_batch_exposes_captures_but_no_consumer(self):
        docs = mutated_docs(lambda d: find(d, "6488", "2026-10-06", "Foreign_Investor").update(buy=find(d, "6488", "2026-10-06", "Foreign_Investor")["buy"] + 1))
        snapshot, _, error = fails("anchor_mismatch", Transport(body_docs(docs)))
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(len(snapshot.inspection()["captures"]), 7)
        expect(self, "consumer_unavailable", lambda: snapshot.window_records("3105"))
        expect(self, "oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))


class TransportGateTests(unittest.TestCase):
    def check(self, code, index=0, **options):
        transport = Transport(response_options={index: options})
        snapshot, transport, error = fails(code, transport)
        self.assertIsNotNone(error, code)
        self.assertEqual(error.code, code, error.diagnostics)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(error.diagnostics["attempts"], index + 1)
        self.assertEqual(len(transport.opens), index + 1)  # first failure stops, nothing is retried
        self.assertEqual(snapshot.ledger.attempted, tuple(range(index + 1)))
        self.assertTrue(all(r.closed for r in transport.responses))
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(error.diagnostics) + str(error))
        return snapshot, error

    def accepted(self, index=0, **options):
        snapshot, transport, error = fails("", Transport(response_options={index: options}))
        self.assertIsNone(error, getattr(error, "diagnostics", None))
        self.assertEqual(snapshot.state, "pending")
        return snapshot

    def test_status_must_be_200_and_login_or_payment_is_a_first_failure(self):
        for status in (301, 302, 307, 400, 401, 402, 403, 404, 429, 500, 503):
            with self.subTest(status=status):
                _, error = self.check("http_status", status=status)
                self.assertEqual(error.diagnostics["source_index"], 0)
        self.check("http_status", index=3, status=402)
        self.check("http_status", index=6, status=401)

    def test_redirect_headers_and_encodings(self):
        body = body_docs()[0]
        self.check("http_redirect", headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("Location", "https://example.invalid/")))
        self.check("http_redirect", headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("location", "x")))
        self.check("duplicate_framing_header", headers=(("Content-Length", str(len(body))), ("Content-Length", str(len(body))), ("Content-Type", "application/json")))
        self.check("duplicate_framing_header", headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("content-type", "application/json")))
        self.check("duplicate_framing_header", headers=(("Transfer-Encoding", "chunked"), ("Transfer-Encoding", "chunked"), ("Content-Type", "application/json")))
        self.check("duplicate_framing_header", headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("Content-Encoding", "identity"), ("Content-Encoding", "identity")))
        self.check("duplicate_framing_header", headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("Location", "a"), ("Location", "b")))
        for encoding in ("gzip", "br", "deflate", "identity, gzip"):
            self.check("content_encoding", headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("Content-Encoding", encoding)))
        for variant in ("identity", "IDENTITY", " identity "):
            self.accepted(headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("Content-Encoding", variant)))

    def test_content_type_policy(self):
        body = body_docs()[0]
        length = (("Content-Length", str(len(body))),)
        for bad in ("text/html", "", "application/x-ndjson", "application/json-patch+json", "text/json", "application/json; charset=latin-1",
                    "application/json; boundary=x", "application/json; charset=utf-8; boundary=x", "application/jsonx", "application/json;charset=utf-8x",
                    "application/json; charset='utf-8'", "x" * 200):
            with self.subTest(content_type=bad):
                self.check("content_type", headers=length + (("Content-Type", bad),))
        for good in ("application/json", "APPLICATION/JSON", "application/json; charset=utf-8", "application/json;charset=UTF-8", 'application/json; charset="utf-8"',
                     'application/json;charset="UTF-8"', "  application/json  "):
            with self.subTest(content_type=good):
                self.accepted(headers=length + (("Content-Type", good),))
        self.check("content_type", headers=length)

    def test_framing_rules(self):
        body = body_docs()[0]
        for bad in ("abc", "-1", "01", "1.0", "", "0x10"):
            with self.subTest(length=bad):
                self.check("content_length", headers=(("Content-Length", bad), ("Content-Type", "application/json")))
        self.check("declared_body_cap", headers=(("Content-Length", str(source.BODY_CAP + 1)), ("Content-Type", "application/json")))
        self.check("incomplete_content_length", headers=(("Content-Length", str(len(body) + 10)), ("Content-Type", "application/json")))
        self.check("incomplete_content_length", headers=(("Content-Length", str(len(body) - 10)), ("Content-Type", "application/json")))
        self.check("ambiguous_framing", headers=(("Content-Length", str(len(body))), ("Transfer-Encoding", "chunked"), ("Content-Type", "application/json")))
        self.check("ambiguous_framing", headers=(("Transfer-Encoding", "gzip"), ("Content-Type", "application/json")))
        self.accepted(headers=(("Transfer-Encoding", "chunked"), ("Content-Type", "application/json")))  # chunked alone
        self.accepted(declared=False)  # close-delimited
        self.accepted(headers=(("Content-Length", str(len(body))), ("Content-Type", "application/json"), ("Set-Cookie", "a=1"), ("Cache-Control", "x"), ("Cache-Control", "y"), ("Vary", "a"), ("Vary", "b")))
        self.check("missing_known_eof", eof=False)
        self.check("missing_known_eof", declared=False, eof=False)

    def test_empty_body_and_cap_without_eof(self):
        transport = Transport(bodies=[b""] + body_docs()[1:], response_options={0: dict(headers=(("Content-Length", "0"), ("Content-Type", "application/json")))})
        snapshot, transport, error = fails("empty_body", transport)
        self.assertEqual(error.code, "empty_body")
        big = b"x" * (source.BODY_CAP + 100)
        transport = Transport(bodies=[big] + body_docs()[1:], response_options={0: dict(declared=False)})
        snapshot, transport, error = fails("body_cap_without_known_eof", transport)
        self.assertEqual(error.code, "body_cap_without_known_eof")
        self.assertLessEqual(sum(count for count, _ in transport.responses[0].read_calls), source.BODY_CAP)
        exact = body_docs()[0]
        padding = b" " * (source.BODY_CAP - len(exact))
        transport = Transport(bodies=[exact + padding] + body_docs()[1:], response_options={0: dict(declared=False)})
        snapshot, transport, error = fails("", transport)
        self.assertIsNone(error)  # exactly at the cap with a known EOF is accepted

    def test_transport_exceptions_and_cleanup_failures_keep_no_raw(self):
        snapshot, transport, error = fails("", Transport(fail_at=2))
        self.assertEqual((error.code, error.diagnostics["primary_stage"], error.diagnostics["attempts"]), ("transport_or_parse_failure", "capture_open", 3))
        self.assertEqual(len(transport.opens), 3)
        snapshot, transport, error = fails("", Transport(response_options={1: dict(close_raises=True)}))
        self.assertEqual(error.code, "cleanup_failure")
        self.assertEqual(error.diagnostics["primary_stage"], "capture_response_close")
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(error.diagnostics) + str(error))
        self.assertEqual(len(transport.opens), 2)
        snapshot, transport, error = fails("", Transport(response_options={0: dict(status=500, close_raises=True)}))
        self.assertEqual(error.code, "http_status")
        self.assertEqual((error.diagnostics["secondary_cleanup_count"], error.diagnostics["secondary_cleanup_1_code"]), (1, "cleanup_failure"))

    def test_cooperative_deadlines(self):
        clock = Clock()
        snapshot, transport, error = fails("cooperative_deadline", Transport(clock=clock, open_delay=25), clock=clock)
        self.assertEqual(error.code, "cooperative_deadline")
        clock = Clock()
        snapshot, transport, error = fails("cooperative_deadline", Transport(clock=clock, response_options={0: dict(clock=clock, read_delay=25)}), clock=clock)
        self.assertEqual(error.code, "cooperative_deadline")
        clock = Clock()
        snapshot, transport, error = fails("", Transport(clock=clock, open_delay=19), clock=clock)
        self.assertIsNone(error)  # 7 x 19 s stays inside the 180 s batch

    def test_body_text_gates(self):
        good = body_docs()
        cases = (
            ("bom_rejected", b"\xef\xbb\xbf" + good[0]),
            ("transport_or_parse_failure", good[0][:-1] + b"\xff}"),
            ("transport_or_parse_failure", good[0][:50]),
            ("transport_or_parse_failure", b"not json"),
            ("duplicate_json_key", b'{"msg":"success","status":200,"data":[],"data":[]}'),
            ("nonfinite_json_number", b'{"msg":"success","status":200,"data":[{"buy":NaN}]}'),
            ("nonfinite_json_number", b'{"msg":"success","status":200,"data":[{"buy":Infinity}]}'),
            ("float_json_number", b'{"msg":"success","status":200.0,"data":[]}'),
            ("document_envelope", b"[]"),
            ("document_envelope", b'"x"'),
        )
        for code, body in cases:
            with self.subTest(code=code, body=body[:20]):
                transport = Transport(bodies=[body] + good[1:], response_options={0: dict(declared=False)})
                snapshot, transport, error = fails(code, transport)
                self.assertEqual(error.code, code)
                self.assertEqual(error.diagnostics["source_index"], 0)
        raw = b'{"msg":"success","status":200,"data":[{"date":"2026-10-06","stock_id":"3105","name":"Dealer_self","buy":1,"sell":1,"buy":2}]}'
        snapshot, transport, error = fails("duplicate_json_key", Transport(bodies=[raw] + good[1:], response_options={0: dict(declared=False)}))
        self.assertEqual(error.code, "duplicate_json_key")


class SchemaGateTests(unittest.TestCase):
    def check(self, code, mutate, index=0):
        docs = mutated_docs(mutate)
        snapshot, transport, error = fails(code, Transport(body_docs(docs)))
        self.assertIsNotNone(error, code)
        self.assertEqual(error.code, code, error.diagnostics)
        self.assertEqual(error.diagnostics["source_index"], index)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(len(transport.opens), index + 1)
        return snapshot

    def accepted(self, mutate):
        snapshot, transport, error = fails("", Transport(body_docs(mutated_docs(mutate))))
        self.assertIsNone(error, getattr(error, "diagnostics", None))
        self.assertEqual(snapshot.state, "pending")
        return snapshot

    def test_envelope(self):
        self.check("document_envelope", lambda d: d[0].update(extra=1))
        self.check("document_envelope", lambda d: d[0].pop("msg"))
        self.check("document_status", lambda d: d[0].update(status=201))
        self.check("document_status", lambda d: d[0].update(status=True))
        self.check("document_status", lambda d: d[0].update(status="200"))
        self.check("document_status", lambda d: d[0].update(msg="fail"))
        self.check("document_status", lambda d: d[0].update(msg=None))
        self.check("document_rows", lambda d: d[0].update(data=[]))
        self.check("document_rows", lambda d: d[0].update(data={}))
        many = {"date": "2026-10-06", "stock_id": "3105", "buy": 1, "name": "x", "sell": 1}
        self.check("document_rows", lambda d: d[0].update(data=[dict(many) for _ in range(10001)]))

    def test_row_fields_and_types(self):
        first = lambda d: d[0]["data"][0]
        self.check("row_fields", lambda d: first(d).update(Note="x"))
        self.check("row_fields", lambda d: first(d).pop("sell"))
        self.check("row_fields", lambda d: d[0]["data"].append(7))
        for bad in ("2026-13-01", "20261001", "2026-10-1", "2026-02-30", 20261001, None, " 2026-10-01"):
            with self.subTest(date=bad):
                self.check("row_date", lambda d, bad=bad: first(d).update(date=bad))
        self.check("row_stock_id", lambda d: first(d).update(stock_id="3293"))
        self.check("row_stock_id", lambda d: first(d).update(stock_id=3105))
        self.check("row_stock_id", lambda d: d[4]["data"][3].update(stock_id="3105"), index=4)
        self.check("row_name_type", lambda d: first(d).update(name=5))
        for field in ("buy", "sell"):
            for bad in (True, False, "5", -1, 2 ** 63, None, [1]):
                with self.subTest(field=field, value=bad):
                    self.check("canonical_int64", lambda d, f=field, b=bad: first(d).update({f: b}))
        self.check("float_json_number", lambda d: first(d).update(buy=1.5))
        self.check("float_json_number", lambda d: first(d).update(sell=1e3))

    def test_name_gate_and_per_day_uniqueness(self):
        dealer = lambda d: find(d, "3105", "2026-10-06", "Dealer_self")
        for bad in ("Dealer", "dealer_self", "Dealer_Self", "Dealer_hedging", "Foreign_Dealer", "", "Total", "Foreign_Investors"):
            with self.subTest(name=bad):
                self.check("name_not_admitted", lambda d, b=bad: dealer(d).update(name=b))
        self.check("name_not_admitted", lambda d: d[0]["data"].append({"date": "2026-10-06", "stock_id": "3105", "buy": 1, "name": "Dealer", "sell": 1}))
        self.check("name_not_admitted", lambda d: d[5]["data"].append({"date": "2026-09-29", "stock_id": "6510", "buy": 0, "name": "Other", "sell": 0}), index=5)
        self.check("duplicate_symbol_date_name", lambda d: d[0]["data"].append(dict(dealer(d))))
        self.check("duplicate_symbol_date_name", lambda d: find(d, "3293", "2026-10-05", "Dealer_Hedging").update(name="Dealer_self"), index=1)
        self.check("name_missing", lambda d: d[0]["data"].remove(dealer(d)))
        self.check("name_missing", lambda d: d[6]["data"].remove(find(d, "8069", "2026-09-29", "Foreign_Dealer_Self")), index=6)
        self.check("name_missing", lambda d: d[0]["data"].remove(find(d, "3105", "2026-10-01", "Investment_Trust")))

    def test_date_set_is_exactly_the_fixed_calendar(self):
        self.check("calendar_dates_mismatch", lambda d: d[0].update(data=[r for r in d[0]["data"] if r["date"] != "2026-10-02"]))
        self.check("calendar_dates_mismatch", lambda d: d[1].update(data=[r for r in d[1]["data"] if r["date"] != "2026-09-29"]), index=1)
        self.check("calendar_dates_mismatch", lambda d: d[2].update(data=[r for r in d[2]["data"] if r["date"] != "2026-10-06"]), index=2)

        def extra_day(day):
            def mutate(d):
                d[0]["data"].extend({"date": day, "stock_id": "3105", "buy": 1, "name": n, "sell": 1} for n in ORDER)
            return mutate
        for day, code in (("2026-10-03", "calendar_dates_mismatch"), ("2026-10-04", "calendar_dates_mismatch"),
                          ("2026-10-06", "duplicate_symbol_date_name")):
            self.check(code, extra_day(day))
        # Closure days 09-25/09-28 are outside 09-29..10-06 so they are discarded, not interpreted.
        self.accepted(lambda d: d[0]["data"].extend({"date": "2026-09-28", "stock_id": "3105", "buy": 1, "name": n, "sell": 1} for n in ("Dealer", "Other", "Dealer_self")))
        self.accepted(lambda d: d[0]["data"].extend({"date": "2026-10-07", "stock_id": "3105", "buy": 1, "name": "Dealer", "sell": 1} for _ in range(2)))

    def test_out_of_range_rows_are_validated_then_discarded(self):
        row = lambda **kw: dict({"date": "2026-09-28", "stock_id": "3105", "buy": 1, "name": "Dealer_self", "sell": 1}, **kw)
        self.check("row_fields", lambda d: d[0]["data"].append(row(Note="x")))
        self.check("row_date", lambda d: d[0]["data"].append(row(date="2026-09-31")))
        self.check("row_stock_id", lambda d: d[0]["data"].append(row(stock_id="9999")))
        self.check("canonical_int64", lambda d: d[0]["data"].append(row(buy=-1)))
        self.check("canonical_int64", lambda d: d[0]["data"].append(row(sell=True)))
        self.check("row_name_type", lambda d: d[0]["data"].append(row(name=1)))
        snapshot = self.accepted(lambda d: d[0]["data"].insert(0, row()))
        self.assertEqual(snapshot.inspection()["results"]["3105"][0].rows[0].row_index, 1)  # ordinals keep the full-document position

    def test_provider_filtering_is_irrelevant(self):
        docs = corpus()
        for doc in docs:
            doc["data"] = [r for r in doc["data"] if r["date"] != "2026-09-29"] + [r for r in doc["data"] if r["date"] == "2026-09-29"]
        snapshot, _, error = fails("", Transport(body_docs(docs)))
        self.assertIsNone(error)
        self.assertEqual(snapshot.state, "pending")

    def test_failure_at_a_later_symbol_stops_the_batch(self):
        snapshot = self.check("name_missing", lambda d: d[4]["data"].remove(find(d, "6488", "2026-10-05", "Dealer_self")), index=4)
        self.assertEqual(snapshot.ledger.attempted, (0, 1, 2, 3, 4))
        self.assertEqual(snapshot.ledger.unrun, (5, 6))
        self.assertEqual(snapshot.diagnostics["code"], "name_missing")
        self.assertEqual(snapshot.diagnostics["attempts"], 5)

    def test_int64_extremes_on_unanchored_rows(self):
        def mutate(d):
            row = find(d, "3105", "2026-10-01", "Foreign_Dealer_Self")
            row.update(buy=2 ** 63 - 1, sell=2 ** 63 - 1)
        snapshot = self.accepted(mutate)
        self.assertEqual(snapshot.inspection()["results"]["3105"][2].row("Foreign_Dealer_Self").buy, 2 ** 63 - 1)

    def test_anchored_arithmetic_overflow_is_rejected(self):
        def mutate(d):
            for day in WINDOW:
                find(d, "3105", day, "Foreign_Investor").update(buy=2 ** 63 - 1, sell=0)
        snapshot, transport, error = fails("arithmetic_int64_overflow", Transport(body_docs(mutated_docs(mutate))))
        self.assertEqual(error.code, "arithmetic_int64_overflow")
        self.assertEqual((snapshot.state, len(transport.opens)), ("failed", 7))


class AnchorGateTests(unittest.TestCase):
    def anchor_failure(self, docs=None, policy=None):
        snapshot, transport, error = fails("anchor_mismatch", Transport(body_docs(docs)) if docs is not None else None, policy=policy)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "anchor_mismatch", error.diagnostics)
        self.assertEqual(len(transport.opens), 7)  # all seven are spent before the whole-batch gate
        self.assertEqual(snapshot.state, "failed")
        return error

    def test_baseline_satisfies_all_56_values(self):
        snapshot, _, _ = available()
        self.assertEqual(snapshot.provenance["anchors_checked"], 56)
        for end, per_symbol in ANCHORS.items():
            window = [d for d in DATES if (d <= end if end == "2026-10-05" else d >= "2026-09-30")]
            for symbol, expected in per_symbol.items():
                records = [r for r in snapshot.inspection()["results"][symbol] if r.date in window]
                self.assertEqual(len(records), 5)
                net = lambda name: sum(r.row(name).buy - r.row(name).sell for r in records)
                self.assertEqual((net("Foreign_Investor"), net("Investment_Trust"), net("Dealer_self") + net("Dealer_Hedging")),
                                 (expected["foreign_investor"], expected["investment_trust"], expected["dealer_self_plus_hedging"]))
                self.assertEqual(expected["three_total"], expected["foreign_investor"] + expected["investment_trust"] + expected["dealer_self_plus_hedging"])

    def test_each_of_the_42_component_anchors_is_gated_by_the_policy_value(self):
        components = (("dealer_self_plus_hedging", "dealer_self_plus_hedging"), ("foreign_investor", "foreign_investor"), ("investment_trust", "investment_trust"))
        count = 0
        for end in ANCHORS:
            for symbol in SYMBOLS:
                for key, label in components:
                    def mutate(data, end=end, symbol=symbol, key=key):
                        entry = data["anchors"]["values"][end][symbol]
                        entry[key] += 1
                        entry["three_total"] += 1
                    with self.subTest(end=end, symbol=symbol, key=key):
                        error = self.anchor_failure(policy=policy_args(mutate))
                        self.assertEqual(error.diagnostics["mismatch_count"], 2)
                        self.assertEqual(error.diagnostics["first_label"], "%s/%s/%s" % (end, symbol, label))
                        count += 1
        self.assertEqual(count, 42)

    def test_a_corpus_change_that_moves_a_net_by_one_share_is_rejected(self):
        docs = mutated_docs(lambda d: find(d, "6488", "2026-10-06", "Foreign_Investor").update(buy=find(d, "6488", "2026-10-06", "Foreign_Investor")["buy"] + 1))
        error = self.anchor_failure(docs)
        self.assertEqual((error.diagnostics["mismatch_count"], error.diagnostics["first_label"]), (2, "2026-10-06/6488/foreign_investor"))
        docs = mutated_docs(lambda d: find(d, "3105", "2026-09-29", "Investment_Trust").update(sell=find(d, "3105", "2026-09-29", "Investment_Trust")["sell"] + 1))
        error = self.anchor_failure(docs)
        self.assertEqual((error.diagnostics["mismatch_count"], error.diagnostics["first_label"]), (2, "2026-10-05/3105/investment_trust"))
        docs = mutated_docs(lambda d: find(d, "8069", "2026-10-01", "Dealer_Hedging").update(buy=find(d, "8069", "2026-10-01", "Dealer_Hedging")["buy"] + 5))
        error = self.anchor_failure(docs)
        self.assertEqual(error.diagnostics["mismatch_count"], 4)  # both windows contain 10-01: dealer and total, twice
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(error.diagnostics))

    def test_numbers_never_leak_into_failure_diagnostics(self):
        docs = mutated_docs(lambda d: find(d, "6488", "2026-10-06", "Foreign_Investor").update(buy=find(d, "6488", "2026-10-06", "Foreign_Investor")["buy"] + 1))
        error = self.anchor_failure(docs)
        text = repr(dict(error.diagnostics))
        for value in ("594644", "594645", "1330929"):
            self.assertNotIn(value, text)

    def test_unanchored_and_offsetting_changes_are_accepted(self):
        # Foreign_Dealer_Self is outside the policy mapping; a self/hedge swap leaves only their SUM anchored.
        def mutate(d):
            find(d, "5347", "2026-10-02", "Foreign_Dealer_Self").update(buy=999, sell=1)
            find(d, "5347", "2026-10-02", "Dealer_self")["buy"] += 7
            find(d, "5347", "2026-10-02", "Dealer_Hedging")["sell"] += 7
        snapshot, _, error = fails("", Transport(body_docs(mutated_docs(mutate))))
        self.assertIsNone(error)
        self.assertEqual(snapshot.state, "pending")


class RecordOnlyComparisonTests(unittest.TestCase):
    def pending(self, docs):
        snapshot, _, error = fails("", Transport(body_docs(docs)))
        self.assertIsNone(error, getattr(error, "diagnostics", None))
        self.assertEqual(snapshot.state, "pending")
        return snapshot.inspection()["record_only_comparison"], snapshot

    def test_matching_shape(self):
        comparison, _ = self.pending(corpus())
        expected = (("2026-10-05", "5274", "Dealer_self", "sell"), ("2026-10-06", "5274", "Dealer_self", "sell"))
        self.assertEqual(comparison["observed_zero_set"], expected)
        self.assertEqual((comparison["matches"], comparison["gate"], comparison["compared_values"], comparison["only_expected"], comparison["only_observed"]), (True, False, 210, (), ()))

    def test_late_booking_changes_gross_but_never_rejects(self):
        def mutate(d):
            row = find(d, "5274", "2026-10-05", "Dealer_self")
            row["buy"] += 40
            row["sell"] += 40
        comparison, snapshot = self.pending(mutated_docs(mutate))
        self.assertFalse(comparison["matches"])
        self.assertEqual(comparison["only_expected"], (("2026-10-05", "5274", "Dealer_self", "sell"),))
        self.assertEqual(comparison["only_observed"], ())
        snapshot.admit_independent_verification(admission(snapshot, record_only_matches=False))
        self.assertEqual(snapshot.state, "available")
        self.assertFalse(snapshot.provenance["record_only_comparison"]["matches"])

    def test_extra_or_missing_zero_is_recorded_not_rejected(self):
        comparison, _ = self.pending(corpus(zero_sell_5274=False))
        self.assertEqual((comparison["observed_zero_set"], comparison["matches"], len(comparison["only_expected"])), ((), False, 2))
        patterns = dict(PATTERNS)
        patterns["3293"] = ([-4, -4, 3, 3, -1], [2, -6, -6, 0, 8])
        comparison, _ = self.pending(corpus(patterns))
        self.assertIn(("2026-10-05", "3293", "Dealer_Hedging", "net"), comparison["only_observed"])
        self.assertFalse(comparison["matches"])

    def test_zero_values_outside_the_window_are_ignored(self):
        docs = corpus()
        find(docs, "3105", "2026-09-29", "Dealer_Hedging").update(buy=0, sell=0)  # 09-29 is anchor-only and net-neutral
        comparison, _ = self.pending(docs)
        self.assertTrue(comparison["matches"])


class RealPathReplayTests(unittest.TestCase):
    def wires(self, **kwargs):
        return [wire(body, **kwargs) for body in body_docs()]

    def test_http_client_parses_each_framing_and_the_request_is_exact(self):
        for label, kwargs in (("content-length", {}), ("chunked", dict(chunked=True)), ("close-delimited", dict(with_length=False))):
            with self.subTest(framing=label):
                factory = ReplayFactory(self.wires(**kwargs))
                module, snapshot = real_source(factory)
                self.assertIs(snapshot.acquire(), snapshot)
                self.assertEqual(snapshot.state, "pending")
                self.assertEqual(len(factory.requests), 7)
                for index, (host, method, target, headers) in enumerate(factory.requests):
                    self.assertEqual((host, method), ("api.finmindtrade.com", "GET"))
                    self.assertEqual("https://api.finmindtrade.com" + target, URLS[index])
                    self.assertEqual(headers, {"Accept-Encoding": "identity", "Connection": "close", "User-Agent": "stock-lab-issue9-local-ram/1", "Accept": "application/json"})
                self.assertTrue(all(c.closed for c in factory.connections))
                self.assertEqual([c.body for c in snapshot.inspection()["captures"]], body_docs())
                self.assertEqual(snapshot.ledger.attempted, tuple(range(7)))
                self.assertTrue(all(c.sock.timeouts for c in factory.connections))

    def test_real_admission_must_match_the_sealed_qa_binding(self):
        factory = ReplayFactory(self.wires())
        module, snapshot = real_source(factory)
        snapshot.acquire()
        bad = (dict(holder_session_id="6e2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d", candidate_sha="a" * 40, script_sha256="c" * 64),
               dict(holder_session_id=QA_HOLDER, candidate_sha="d" * 40, script_sha256="c" * 64),
               dict(holder_session_id=QA_HOLDER, candidate_sha="a" * 40, script_sha256="d" * 64))
        for override in bad:
            expect(self, "oracle_qa_binding", snapshot.admit_independent_verification, admission(snapshot, module=module, **override))
        self.assertEqual(snapshot.state, "pending")
        snapshot.admit_independent_verification(admission(snapshot, module=module, holder_session_id=QA_HOLDER, candidate_sha="a" * 40, script_sha256="c" * 64))
        self.assertEqual(snapshot.state, "available")

    def test_real_ledger_is_process_wide_per_loaded_module(self):
        factory = ReplayFactory(self.wires())
        module, snapshot = real_source(factory)
        snapshot.acquire()
        snapshot.release()
        factory_again = ReplayFactory(self.wires())
        _, again = real_source(factory_again, module=module)
        expect(self, "quota_spent", again.acquire)
        self.assertEqual(again.state, "failed")  # R1-2
        self.assertEqual((factory_again.connections, factory_again.requests), ([], []))

    def test_response_shape_failures_through_real_http_client(self):
        body = body_docs()[0]
        base = [wire(b, ) for b in body_docs()]
        cases = (
            ("http_status", wire(body, status="403 Forbidden")),
            ("http_status", wire(body, status="302 Found", headers=["Location: https://example.invalid/", "Content-Length: %d" % len(body)])),
            ("http_redirect", wire(body, headers=["Content-Type: application/json", "Content-Length: %d" % len(body), "Location: /x"])),
            ("content_encoding", wire(body, headers=["Content-Type: application/json", "Content-Length: %d" % len(body), "Content-Encoding: gzip"])),
            ("content_type", wire(body, headers=["Content-Type: text/html", "Content-Length: %d" % len(body)])),
            ("duplicate_framing_header", wire(body, headers=["Content-Type: application/json", "Content-Length: %d" % len(body), "Content-Length: %d" % len(body)])),
            ("ambiguous_framing", wire(body, headers=["Content-Type: application/json", "Content-Length: %d" % len(body), "Transfer-Encoding: chunked"], chunked=True)),
        )
        for code, wire_bytes in cases:
            with self.subTest(code=code):
                factory = ReplayFactory([wire_bytes] + base[1:])
                _, snapshot = real_source(factory)
                error = expect(self, code, snapshot.acquire)
                self.assertEqual(len(factory.requests), 1)
                self.assertTrue(all(c.closed for c in factory.connections))
        extras = wire(body, headers=["Content-Type: application/json; charset=\"utf-8\"", "Content-Length: %d" % len(body), "Set-Cookie: a=1", "Cache-Control: a", "Cache-Control: b", "Vary: x", "Vary: y"])
        factory = ReplayFactory([extras] + base[1:])
        _, snapshot = real_source(factory)
        snapshot.acquire()
        self.assertEqual(snapshot.state, "pending")

    def test_replaced_connection_class_is_refused_before_anything_is_spent(self):
        module = load_module("issue9_dealer_source_replaced")
        start, binding = declaration(module=module)
        snapshot = module.DealerDirectionSource(**policy_args(), financial_start=start, execution_binding=binding)
        original = http.client.HTTPSConnection

        class Wrapper(original):
            pass
        http.client.HTTPSConnection = Wrapper
        try:
            expect(self, "transport_class_replaced", snapshot.acquire)
            self.assertEqual(snapshot.state, "new")
            self.assertIsNone(snapshot.ledger)
            expect(self, "transport_class_replaced", module.native_connection, "api.finmindtrade.com", 1)
        finally:
            http.client.HTTPSConnection = original
        # The refusal consumed nothing: with the class restored the same snapshot may still try (here through a replay factory).
        self.assertEqual(snapshot.state, "new")
        self.assertEqual(GUARD_EVENTS, [])

    def test_a_replaced_class_is_refused_with_a_composed_factory_too(self):
        module = load_module("issue9_dealer_source_replaced_factory")
        factory = ReplayFactory(self.wires())
        start, binding = declaration(module=module)
        snapshot = module.DealerDirectionSource(**policy_args(), financial_start=start, execution_binding=binding, connection_factory=factory)
        original = http.client.HTTPSConnection
        http.client.HTTPSConnection = type("Wrapper", (original,), {})
        try:
            expect(self, "transport_class_replaced", snapshot.acquire)
        finally:
            http.client.HTTPSConnection = original
        self.assertEqual((snapshot.state, snapshot.ledger, factory.connections, factory.requests), ("new", None, [], []))
        snapshot.acquire()  # nothing was spent, so the same snapshot still runs once the class is intact (replay factory only)
        self.assertEqual(snapshot.state, "pending")

    def test_transport_url_gate(self):
        module = load_module("issue9_dealer_source_url")
        transport = module._HTTPSTransport(lambda h, t: self.fail("must not connect"))
        for url in ("http://api.finmindtrade.com/api/v4/data?x=1", "https://example.com/api/v4/data?x=1", "https://api.finmindtrade.com:444/api/v4/data?x=1",
                    "https://user@api.finmindtrade.com/api/v4/data?x=1", "ftp://api.finmindtrade.com/x"):
            with self.subTest(url=url):
                expect(self, "transport_url", transport.open, url, 5)


class ZGuardTests(unittest.TestCase):
    def test_module_has_no_import_time_io_and_no_environment_reads(self):
        before = list(GUARD_EVENTS)
        load_module("issue9_dealer_source_import_probe")
        self.assertEqual(GUARD_EVENTS, before)
        text = SOURCE_PATH.read_text(encoding="utf-8")
        for token in ("os.environ", "getenv", "subprocess", "import socket", "import os", "urllib.request", "http.cookiejar", "import requests", "import httpx"):
            self.assertNotIn(token, text, token)
        self.assertNotRegex(text, r"(?m)^\s*(?:with\s+)?open\(")

    def test_1_no_network_name_resolution_process_or_disk_write_happened(self):
        self.assertEqual(GUARD_EVENTS, [])

    def test_2_the_guard_itself_refuses_resolution_and_connection(self):
        import socket
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("api.finmindtrade.com", 443)
        with self.assertRaises(AssertionError):
            socket.create_connection(("127.0.0.1", 9), timeout=0.01)
        self.assertEqual(GUARD_EVENTS[0], "socket.getaddrinfo")
        GUARD_EVENTS.clear()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], "-v"], verbosity=2)
