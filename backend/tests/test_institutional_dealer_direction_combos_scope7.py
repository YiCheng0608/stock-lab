"""Issue 9 dealer direction combos: computation boundaries and chips-only API. RAM fixtures only.

Run (from backend/): python -B -X utf8 -m pytest -p no:cacheprovider -q tests/test_institutional_dealer_direction_combos_scope7.py
or through tools/finmind-dealer-direction-api.py --check. Nothing here opens a file, a database, a port or a
real connection: the source is driven by an in-memory transport, the API by httpx's in-process ASGI transport,
and every non-loopback name resolution or connection is refused by the module guard below. The external policy
is the coordinator's draft v2 (Issue 9 comment 6125240011), pasted as a literal and pinned by the constants
beside it; the corpus is synthetic (built so its sums satisfy the 56 policy anchors) and is not source truth.
All expectations are recomputed here with plain stdlib code, never with the product's helpers.
"""
import asyncio
import base64
import dataclasses
import hashlib
import itertools
import json
import socket
import unittest
from unittest.mock import patch

import httpx

from app import finmind_dealer_direction_source as src
from app import institutional_dealer_direction_combos_scope7 as combos

EXTERNAL_POLICY = b'{"ac_revision":"2a","acquisition":{"accept":"application/json","accept_encoding":"identity","attempted_is_spent":true,"batch_seconds":180,"body_cap_bytes":1048576,"connection":"close","credentials":"no token, cookie or proxy","deadline":"cooperative","max_gets":7,"namespace":"issue9-dealer-direction-combos-finmind-v1/qa1","order":"seven symbols ascending as listed","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608,"user_agent":"stock-lab-issue9-local-ram/1"},"anchor_only_dates":["2026-09-29"],"anchors":{"formal_blob":"116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md","formal_blob_sha256":"f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240","formal_section":"47.6 (issue36 official TPEx CSV, shares)","gate":"whole batch rejects unless all 56 values match exactly before available","mapping":{"dealer_self_plus_hedging":"sum of Dealer_self net + Dealer_Hedging net","foreign_investor":"sum of Foreign_Investor net","investment_trust":"sum of Investment_Trust net","three_total":"foreign_investor + investment_trust + dealer_self_plus_hedging (Foreign_Dealer_Self excluded)"},"values":{"2026-10-05":{"3105":{"dealer_self_plus_hedging":2350894,"foreign_investor":28396840,"investment_trust":2812800,"three_total":33560534},"3293":{"dealer_self_plus_hedging":-12792,"foreign_investor":6386218,"investment_trust":414000,"three_total":6787426},"5274":{"dealer_self_plus_hedging":10254,"foreign_investor":-28586,"investment_trust":-40427,"three_total":-58759},"5347":{"dealer_self_plus_hedging":339261,"foreign_investor":323290,"investment_trust":3600607,"three_total":4263158},"6488":{"dealer_self_plus_hedging":-62262,"foreign_investor":354337,"investment_trust":1179529,"three_total":1471604},"6510":{"dealer_self_plus_hedging":32887,"foreign_investor":186887,"investment_trust":-594227,"three_total":-374453},"8069":{"dealer_self_plus_hedging":64380,"foreign_investor":-4247384,"investment_trust":-13040,"three_total":-4196044}},"2026-10-06":{"3105":{"dealer_self_plus_hedging":2227304,"foreign_investor":27460450,"investment_trust":2352400,"three_total":32040154},"3293":{"dealer_self_plus_hedging":-11177,"foreign_investor":5507085,"investment_trust":420000,"three_total":5915908},"5274":{"dealer_self_plus_hedging":8894,"foreign_investor":-13315,"investment_trust":-66756,"three_total":-71177},"5347":{"dealer_self_plus_hedging":407416,"foreign_investor":8820683,"investment_trust":3720607,"three_total":12948706},"6488":{"dealer_self_plus_hedging":-11515,"foreign_investor":594644,"investment_trust":1330929,"three_total":1914058},"6510":{"dealer_self_plus_hedging":43724,"foreign_investor":87416,"investment_trust":-660897,"three_total":-529757},"8069":{"dealer_self_plus_hedging":285782,"foreign_investor":-4053731,"investment_trust":-9040,"three_total":-3776989}}},"windows":{"2026-10-05":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05"],"2026-10-06":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]}},"calendar":{"calendar_gets":0,"required_returned_dates":["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"rule":"every returned row structurally valid first; rows outside start_date..end_date discarded only after validation; in-range date set of every symbol equals required_returned_dates exactly; no closure inference, no fill, no window shrink","source":"formal verified trading dates, SOURCE_REGISTRY 31.2 (2026-09-25 and 2026-09-28 closed)"},"consumer":{"failure":"any source, pin, schema, name, date, anchor or arithmetic conflict makes all seven unavailable; no skipping, zero fill or window shrink","per_symbol":"daily self/hedge net sign (positive/negative/zero), nine daily combos, opposite-direction day count and dates, per-component direction counts, maximal same-sign segments (zero is its own run and breaks positive/negative runs), latest window-limited segment; first segment earlier_unknown true","trace":"segment -> date -> all five FinMind name rows of that symbol-date (original values, row ordinal, body sha256, receipt sha256, URL) + calendar reference","version":"dealer-self-hedging-direction-combos-five-session-v1"},"cutoff":"2026-10-06","first_availability":"unknown","instrument_type":"ordinary_stock","issue":9,"lease":"held until process exit","lifecycle":"single acquisition inside the QA API process; held for the whole QA browser session; released at process exit; any re-acquisition needs a new quota, namespace and seal","market":"TW/TPEx","profile":"free_public_local","publication_time":"unknown","record_only_comparison":{"expected_zero_set":"within window_dates, among Dealer_self and Dealer_Hedging buy, sell and net for seven symbols (210 values), the only zeros were 5274 Dealer_self sell on 2026-10-05 and 2026-10-06","gate":false,"on_mismatch":"list differences in the receipt; not a source error; no rejection","source":"SOURCE_REGISTRY 46.5 text (issue9 predecessor, official TPEx CSV at 2026-10-08)"},"response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8 (quoted or not); anything else rejects","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM; full EOF and raw hash before parse","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","location":"any location header or 3xx rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure"},"revision_time":"unknown","row_schema":{"buy_sell":"non-bool integer 0..9223372036854775807","date":"ISO YYYY-MM-DD string","envelope":"exactly keys msg, status, data; status 200; msg success; data 1..10000 rows","extra_keys":"reject","keys":["buy","date","name","sell","stock_id"],"names":["Dealer_Hedging","Dealer_self","Foreign_Dealer_Self","Foreign_Investor","Investment_Trust"],"names_rule":"applies to in-range rows (start_date..end_date) after every returned row passed structural validation; each in-range symbol-date has exactly one row per listed name; Dealer or any other name, any missing or duplicate symbol-date-name rejects the whole batch; missing is unknown, never zero","net":"local derived net = buy - sell per row; provider has no net column; every step signed-int64 bounded","stock_id":"string equal to requested data_id","value_label":"API value at acquisition time; buy/sell may later grow by equal same-category late bookings (net unaffected); not PIT"},"source":{"dataset":"TaiwanStockInstitutionalInvestorsBuySell","documentation":"https://finmind.github.io/tutor/TaiwanMarket/Chip/ (doc GET receipt issue9 comment 6124059360, sha256 cfcf26a8269452d0a2c396ca69a5a371bcba68d55b2ab35d432b1ba1de13b5f3); per-stock data_id query carries no backer/sponsor marker; free tokenless use is inferred","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","method":"GET","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-09-29","urls":["https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=3105&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=3293&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=5274&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=5347&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=6488&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=6510&start_date=2026-09-29&end_date=2026-10-06","https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=8069&start_date=2026-09-29&end_date=2026-10-06"]},"source_use":"local_personal_noncommercial_dealer_self_hedging_direction_combos","storage":"process_RAM","symbols":["3105","3293","5274","5347","6488","6510","8069"],"unit_policy":{"provider_literal_unit_annotation":false,"unit":"shares","verification":"56 five-session net anchors below must match exactly; lots = shares/1000 exact, at most 3 decimals"},"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","other_dates","other_symbols","other_cutoffs","ranking","filtering","price","signal","plan","trading","actionable_strategy","raw_disk_storage","cross_process","db","redistribution","mirror","deployment","official_unit_annotation"],"version":"issue9-dealer-direction-combos-finmind-v2","window_dates":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"]}'
EXTERNAL_PIN = "7db5e7a7e17f883e7e4e81de297ce2e4ad8c6c4fcde409b7cbeae0eaa56696b1"
EXTERNAL_BYTES = 9319
POLICY = json.loads(EXTERNAL_POLICY)
NAMESPACE = "issue9-dealer-direction-combos-finmind-v1/qa1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
DATES = ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")
WINDOW = DATES[1:]
ORDER = ("Foreign_Investor", "Foreign_Dealer_Self", "Investment_Trust", "Dealer_self", "Dealer_Hedging")
ANCHORS = POLICY["anchors"]["values"]
URLS = tuple("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=%s&start_date=2026-09-29&end_date=2026-10-06" % s for s in SYMBOLS)
API = "/api/chips/dealer-direction-combos-stock-scope-7"
PORT = 8799
HOST = "127.0.0.1:%d" % PORT
ORIGIN = "http://" + HOST
JSON = {"Content-Type": "application/json"}
Q = "?as_of=2026-10-06"
NAMES = {"3105": "穩懋", "3293": "鈊象", "5274": "信驊", "5347": "世界", "6488": "環球晶", "6510": "精測", "8069": "元太"}
INT64_MAX = 2 ** 63 - 1
LOOPBACK = ("127.0.0.1", "::1", "localhost", None, "")
_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_CONNECT = socket.socket.connect
_PATCHES = []
REFUSALS = []


def _getaddrinfo(host, *args, **kwargs):
    if host not in LOOPBACK:
        REFUSALS.append(("getaddrinfo", host))
        raise AssertionError("module guard: external name resolution refused")
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def _connect(self, address):
    if not (isinstance(address, tuple) and address and address[0] in LOOPBACK):
        REFUSALS.append(("connect", address))
        raise AssertionError("module guard: external connection refused")
    return _REAL_CONNECT(self, address)


def setUpModule():
    _PATCHES.extend([patch.object(socket, "getaddrinfo", _getaddrinfo), patch.object(socket.socket, "connect", _connect)])
    for item in _PATCHES:
        item.start()


def tearDownModule():
    for item in reversed(_PATCHES):
        item.stop()
    assert REFUSALS == [], REFUSALS


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


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
    nets["Dealer_self"] = [a["dealer_self_plus_hedging"] - sum(x + y for x, y in zip(s[:4], h[:4]))] + s
    nets["Dealer_Hedging"] = [0] + h
    nets["Foreign_Dealer_Self"] = [11, -12, 13, -14, 15, -16]
    return nets


def corpus(patterns=None):
    documents = []
    for si, symbol in enumerate(SYMBOLS):
        nets = day_nets(symbol, patterns)
        rows = []
        for di, day in enumerate(DATES):
            for ni, name in enumerate(ORDER):
                net, base = nets[name][di], 100 + 7 * si + di + 3 * ni
                zero = symbol == "5274" and name == "Dealer_self" and day in ("2026-10-05", "2026-10-06")
                sell = 0 if zero else base + max(-net, 0)
                buy = net if zero else base + max(net, 0)
                assert buy - sell == net and buy >= 0 and sell >= 0
                rows.append({"date": day, "stock_id": symbol, "buy": buy, "name": name, "sell": sell})
        documents.append({"msg": "success", "status": 200, "data": rows})
    return documents


def bodies_of(documents):
    return [json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8") for d in documents]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Response:
    def __init__(self, body):
        self.body, self.offset, self.status = body, 0, 200
        self.headers = (("Content-Length", str(len(body))), ("Content-Type", "application/json"))
        self.closed = False

    @property
    def known_eof(self):
        return self.offset == len(self.body)

    def read(self, count, timeout):
        chunk = self.body[self.offset:self.offset + count]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, bodies=None):
        self.bodies = bodies or bodies_of(corpus())
        self.opens = []

    def open(self, url, timeout):
        self.opens.append(url)
        return Response(self.bodies[len(self.opens) - 1])


def new_source(transport=None, clock=None, ledger=None, **kwargs):
    transport = transport or Transport()
    clock = clock or Clock()
    return src.DealerDirectionSource(policy_canonical=EXTERNAL_POLICY, expected_policy_sha256=EXTERNAL_PIN,
                                     expected_policy_bytes=EXTERNAL_BYTES, transport=transport,
                                     ledger=ledger or src.AttemptLedger(NAMESPACE), clock=clock, **kwargs), transport, clock


def receipt_sha(receipt):
    return hashlib.sha256(canonical({f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt)})).hexdigest()


def admit(source, **overrides):
    values = dict(namespace=NAMESPACE, policy_sha256=EXTERNAL_PIN, holder_session_id="synthetic-oracle", candidate_sha="a" * 40,
                  script_sha256="b" * 64, receipt_sha256s=tuple(receipt_sha(c.receipt) for c in source.inspection()["captures"]),
                  name_rows=210, stock_days=42, anchor_values=56, record_only_matches=True, independent=True)
    values.update(overrides)
    source.admit_independent_verification(src.OracleAdmission(**values))


def available_source(**kwargs):
    source, transport, clock = new_source(**kwargs)
    source.acquire()
    admit(source)
    return source, transport, clock


# --- independent expectations (plain stdlib; never the product's helpers) ---
def sign_of(n):
    return "positive" if n > 0 else "negative" if n < 0 else "zero"


def lots_of(n):
    sign_text = "-" if n < 0 else ""
    whole, rest = divmod(abs(n), 1000)
    return sign_text + str(whole) + ("." + ("%03d" % rest).rstrip("0") if rest else "")


def runs(signs):
    out, index = [], 0
    for value, group in itertools.groupby(signs):
        length = len(list(group))
        out.append({"sign": value, "start_index": index, "end_index": index + length - 1, "start_date": WINDOW[index],
                    "end_date": WINDOW[index + length - 1], "length": length, "earlier_unknown": index == 0})
        index += length
    return out


def expected_window(document):
    by = {(r["date"], r["name"]): r for r in document["data"]}
    nets = {c: [by[(d, n)]["buy"] - by[(d, n)]["sell"] for d in WINDOW] for c, n in (("self", "Dealer_self"), ("hedge", "Dealer_Hedging"))}
    signs = {c: [sign_of(v) for v in nets[c]] for c in nets}
    pairs = [signs["self"][i] + "_" + signs["hedge"][i] for i in range(5)]
    keys = [a + "_" + b for a in ("positive", "negative", "zero") for b in ("positive", "negative", "zero")]
    return {"nets": nets, "signs": signs, "pairs": pairs,
            "counts": {c: {s: signs[c].count(s) for s in ("positive", "negative", "zero")} for c in nets},
            "segments": {c: runs(signs[c]) for c in nets},
            "combination_counts": {k: pairs.count(k) for k in keys},
            "combination_dates": {k: [WINDOW[i] for i in range(5) if pairs[i] == k] for k in keys},
            "opposite": [WINDOW[i] for i in range(5) if pairs[i] in ("positive_negative", "negative_positive")]}


def records_from(symbol, nets_self, nets_hedge, source_index=0, base=10):
    """Direct DayRecords (original row order) for pure computation cases."""
    result = []
    for i, day in enumerate(WINDOW):
        rows = []
        for ordinal, (name, net) in enumerate((("Foreign_Investor", 5), ("Foreign_Dealer_Self", 0), ("Investment_Trust", -5),
                                               ("Dealer_self", nets_self[i]), ("Dealer_Hedging", nets_hedge[i]))):
            buy, sell = base + max(net, 0), base + max(-net, 0)
            rows.append(src.NameRow(i * 5 + ordinal, ("date", "stock_id", "buy", "name", "sell"), day, symbol, name, buy, sell))
        result.append(src.DayRecord(symbol, day, source_index, tuple(rows)))
    return tuple(result)


FAKE_RECEIPTS = {0: {"url": URLS[0], "sha256": "1" * 64, "body_sha256": "2" * 64}}

def expected_from(nets_self, nets_hedge):
    nets = {"self": list(nets_self), "hedge": list(nets_hedge)}
    signs = {c: [sign_of(v) for v in nets[c]] for c in nets}
    pairs = [signs["self"][i] + "_" + signs["hedge"][i] for i in range(5)]
    keys = [a + "_" + b for a in ("positive", "negative", "zero") for b in ("positive", "negative", "zero")]
    return {"nets": nets, "signs": signs, "pairs": pairs,
            "counts": {c: {s: signs[c].count(s) for s in ("positive", "negative", "zero")} for c in nets},
            "segments": {c: runs(signs[c]) for c in nets},
            "combination_counts": {k: pairs.count(k) for k in keys},
            "combination_dates": {k: [WINDOW[i] for i in range(5) if pairs[i] == k] for k in keys},
            "opposite": [WINDOW[i] for i in range(5) if pairs[i] in ("positive_negative", "negative_positive")]}


def check_window(case, window, expected):
    case.assertEqual(window["horizon"], 5)
    case.assertEqual([p["date"] for p in window["points"]], list(WINDOW))
    case.assertEqual([p["index"] for p in window["points"]], [0, 1, 2, 3, 4])
    for component in ("self", "hedge"):
        case.assertEqual([p[component]["net_shares"] for p in window["points"]], [str(v) for v in expected["nets"][component]])
        case.assertEqual([p[component]["net_lots"] for p in window["points"]], [lots_of(v) for v in expected["nets"][component]])
        case.assertEqual([p[component]["sign"] for p in window["points"]], expected["signs"][component])
        case.assertEqual(window["counts"][component], expected["counts"][component])
        case.assertEqual(window["segments"][component], expected["segments"][component])
        case.assertEqual(window["latest"][component], expected["segments"][component][-1])
    case.assertEqual([p["combination"] for p in window["points"]], expected["pairs"])
    case.assertEqual(window["combination_counts"], expected["combination_counts"])
    case.assertEqual(window["combination_dates"], expected["combination_dates"])
    case.assertEqual(window["opposite"], {"count": len(expected["opposite"]), "dates": expected["opposite"]})
    case.assertEqual([p["opposite"] for p in window["points"]], [d in expected["opposite"] for d in WINDOW])
    case.assertEqual(sum(window["combination_counts"].values()), 5)
    case.assertEqual(list(window["combination_counts"]), [a + "_" + b for a in ("positive", "negative", "zero") for b in ("positive", "negative", "zero")])


def broken_documents():
    documents = corpus()
    documents[2]["data"] = [r for r in documents[2]["data"] if not (r["date"] == "2026-10-02" and r["name"] == "Dealer_Hedging")]
    return documents


class ComputationTests(unittest.TestCase):
    def run_window(self, nets_self, nets_hedge):
        window = combos.window_result(records_from("3105", nets_self, nets_hedge), FAKE_RECEIPTS)
        check_window(self, window, expected_from(nets_self, nets_hedge))
        return window

    def test_scalar_helpers_and_int64_bounds(self):
        for value, text in ((0, "0"), (1, "0.001"), (-1, "-0.001"), (999, "0.999"), (1000, "1"), (1234, "1.234"), (-1500, "-1.5"),
                            (10 ** 12, "1000000000"), (INT64_MAX, "9223372036854775.807"), (-INT64_MAX - 1, "-9223372036854775.808")):
            self.assertEqual(combos.lots(value), text)
            self.assertEqual(lots_of(value), text)
        for value in (INT64_MAX + 1, -INT64_MAX - 2, True, 1.0, "1", None):
            with self.assertRaises(combos.DirectionComboError):
                combos.sign(value)
        self.assertEqual([combos.sign(v) for v in (5, -5, 0, INT64_MAX, -INT64_MAX - 1)], ["positive", "negative", "zero", "positive", "negative"])
        self.assertEqual(combos.net_of(INT64_MAX, 0), INT64_MAX)
        self.assertEqual(combos.net_of(0, INT64_MAX), -INT64_MAX)
        self.assertEqual(combos.net_of(INT64_MAX, INT64_MAX), 0)
        for buy, sell in ((-1, 0), (0, -1), (INT64_MAX + 1, 0), (0, INT64_MAX + 1), (True, 0), (1.5, 0), ("1", 0)):
            with self.assertRaises(combos.DirectionComboError):
                combos.net_of(buy, sell)

    def test_the_nine_keys_are_self_then_hedge_in_a_fixed_order(self):
        self.assertEqual(combos.COMBINATION_KEYS, ("positive_positive", "positive_negative", "positive_zero", "negative_positive", "negative_negative",
                                                   "negative_zero", "zero_positive", "zero_negative", "zero_zero"))
        self.assertEqual(combos.combination("positive", "zero"), "positive_zero")
        self.assertEqual(combos.combination("zero", "positive"), "zero_positive")
        with self.assertRaises(combos.DirectionComboError):
            combos.combination("unknown", "zero")
        self.assertEqual(combos.OPPOSITE_KEYS, ("positive_negative", "negative_positive"))

    def test_golden_mixed_window_with_true_zeros(self):
        window = self.run_window([5, 0, -2, -3, 4], [-1, -1, 0, 7, 7])
        self.assertEqual([p["combination"] for p in window["points"]], ["positive_negative", "zero_negative", "negative_zero", "negative_positive", "positive_positive"])
        self.assertEqual(window["opposite"], {"count": 2, "dates": ["2026-09-30", "2026-10-05"]})
        self.assertEqual(window["counts"]["self"], {"positive": 2, "negative": 2, "zero": 1})
        self.assertEqual(window["counts"]["hedge"], {"positive": 2, "negative": 2, "zero": 1})
        self.assertEqual([(s["sign"], s["start_index"], s["end_index"], s["length"], s["earlier_unknown"]) for s in window["segments"]["self"]],
                         [("positive", 0, 0, 1, True), ("zero", 1, 1, 1, False), ("negative", 2, 3, 2, False), ("positive", 4, 4, 1, False)])
        self.assertEqual([(s["sign"], s["start_index"], s["end_index"], s["length"], s["earlier_unknown"]) for s in window["segments"]["hedge"]],
                         [("negative", 0, 1, 2, True), ("zero", 2, 2, 1, False), ("positive", 3, 4, 2, False)])
        self.assertEqual(window["latest"]["self"]["sign"], "positive")
        self.assertEqual((window["latest"]["hedge"]["start_date"], window["latest"]["hedge"]["end_date"]), ("2026-10-05", "2026-10-06"))
        self.assertIsNot(window["latest"]["self"], window["segments"]["self"][-1])  # a copy, not an alias

    def test_zero_is_its_own_run_and_breaks_positive_and_negative_runs(self):
        window = self.run_window([1, 0, 1, 0, 1], [-1, -1, 0, -1, -1])
        self.assertEqual([s["length"] for s in window["segments"]["self"]], [1, 1, 1, 1, 1])
        self.assertEqual([s["sign"] for s in window["segments"]["hedge"]], ["negative", "zero", "negative"])
        self.assertEqual([s["length"] for s in window["segments"]["hedge"]], [2, 1, 2])
        window = self.run_window([0, 1, 1, 1, 0], [1, 1, 1, 1, 1])
        self.assertEqual([s["sign"] for s in window["segments"]["self"]], ["zero", "positive", "zero"])
        self.assertEqual(window["latest"]["self"]["sign"], "zero")  # latest zero interrupts the run
        self.assertEqual(window["latest"]["self"]["length"], 1)

    def test_only_the_first_segment_says_earlier_unknown_and_nothing_is_inferred_before_the_window(self):
        for nets in ([1, 1, 1, 1, 1], [-1, -1, -1, -1, -1], [0, 0, 0, 0, 0], [1, -1, 1, -1, 1], [3, 3, -3, -3, 0]):
            window = self.run_window(nets, list(reversed(nets)))
            for component in ("self", "hedge"):
                flags = [s["earlier_unknown"] for s in window["segments"][component]]
                self.assertEqual(flags, [True] + [False] * (len(flags) - 1))
                self.assertEqual(window["segments"][component][0]["start_index"], 0)
                self.assertEqual(sum(s["length"] for s in window["segments"][component]), 5)
        window = self.run_window([1, 1, 1, 1, 1], [1, 1, 1, 1, 1])
        self.assertEqual(window["segments"]["self"], [{"sign": "positive", "start_index": 0, "end_index": 4, "start_date": "2026-09-30", "end_date": "2026-10-06", "length": 5, "earlier_unknown": True}])
        self.assertEqual(window["latest"]["self"]["earlier_unknown"], True)  # a run reaching the window start is still window-limited

    def test_all_zero_and_alternating_windows(self):
        window = self.run_window([0] * 5, [0] * 5)
        self.assertEqual(window["combination_counts"]["zero_zero"], 5)
        self.assertEqual(window["opposite"], {"count": 0, "dates": []})
        self.assertEqual(window["counts"]["self"], {"positive": 0, "negative": 0, "zero": 5})
        window = self.run_window([1, -1, 1, -1, 1], [-1, 1, -1, 1, -1])
        self.assertEqual(window["opposite"]["count"], 5)
        self.assertEqual(window["combination_counts"]["positive_negative"], 3)
        self.assertEqual(window["combination_counts"]["negative_positive"], 2)
        self.assertEqual(len(window["segments"]["self"]), 5)

    def test_every_one_of_the_nine_combinations_is_reachable(self):
        for a, b in itertools.product((1, -1, 0), repeat=2):
            window = self.run_window([a] * 5, [b] * 5)
            key = sign_of(a) + "_" + sign_of(b)
            self.assertEqual(window["combination_counts"][key], 5)
            self.assertEqual(sum(1 for v in window["combination_counts"].values() if v), 1)

    def test_extreme_int64_values_stay_exact(self):
        window = combos.window_result(records_from("3105", [INT64_MAX, -INT64_MAX, 0, 1, -1], [-INT64_MAX, INT64_MAX, 0, -1, 1], base=0), FAKE_RECEIPTS)
        point = window["points"][0]
        self.assertEqual((point["self"]["net_shares"], point["self"]["net_lots"]), (str(INT64_MAX), "9223372036854775.807"))
        self.assertEqual((point["hedge"]["net_shares"], point["hedge"]["net_lots"]), (str(-INT64_MAX), "-9223372036854775.807"))
        self.assertEqual(window["points"][1]["self"]["net_shares"], str(-INT64_MAX))
        self.assertEqual(window["points"][0]["combination"], "positive_negative")

    def test_window_and_row_gates(self):
        good = records_from("3105", [1] * 5, [1] * 5)
        with self.assertRaises(combos.DirectionComboError):
            combos.window_result(good[:4], FAKE_RECEIPTS)
        with self.assertRaises(combos.DirectionComboError):
            combos.window_result(list(good), FAKE_RECEIPTS)  # a list, not the tuple of records
        with self.assertRaises(combos.DirectionComboError):
            combos.window_result(tuple(reversed(good)), FAKE_RECEIPTS)
        mixed = good[:4] + (dataclasses.replace(good[4], symbol="3293"),)
        with self.assertRaises(combos.DirectionComboError):
            combos.window_result(mixed, FAKE_RECEIPTS)
        with self.assertRaises(combos.DirectionComboError):
            combos.segments_of(["positive", "bogus"], ["a", "b"])
        with self.assertRaises(combos.DirectionComboError):
            combos.segments_of([], [])
        with self.assertRaises(combos.DirectionComboError):
            combos.segments_of(["positive"], ["a", "b"])

    def test_a_missing_name_row_is_unknown_never_zero(self):
        good = records_from("3105", [1] * 5, [1] * 5)
        broken = dataclasses.replace(good[2], rows=tuple(r for r in good[2].rows if r.name != "Dealer_Hedging"))
        with self.assertRaises(ValueError) as caught:
            combos.window_result(good[:2] + (broken,) + good[3:], FAKE_RECEIPTS)
        self.assertEqual(caught.exception.code, "name_missing")

    def test_trace_keeps_all_five_original_rows_in_order_with_their_values(self):
        records = records_from("3105", [3, -3, 0, 2, -2], [1, 1, 1, -1, -1])
        window = combos.window_result(records, FAKE_RECEIPTS)
        for point, record in zip(window["points"], records):
            self.assertEqual([r["name"] for r in point["rows"]], [r.name for r in record.rows])
            self.assertEqual([r["row_index"] for r in point["rows"]], [r.row_index for r in record.rows])
            self.assertEqual([(r["buy_shares"], r["sell_shares"]) for r in point["rows"]], [(str(r.buy), str(r.sell)) for r in record.rows])
            self.assertTrue(all(r["key_order"] == ["date", "stock_id", "buy", "name", "sell"] and r["date"] == point["date"] and r["stock_id"] == "3105" for r in point["rows"]))
            self.assertEqual((point["url"], point["receipt_sha256"], point["body_sha256"], point["request_index"]), (URLS[0], "1" * 64, "2" * 64, 0))
        self.assertEqual(window["points"][2]["self"]["net_shares"], "0")
        self.assertEqual(window["points"][2]["self"]["sign"], "zero")


class CorpusPayloadTests(unittest.TestCase):
    def test_every_symbol_matches_an_independent_recomputation(self):
        documents = corpus()
        source, transport, _ = available_source(transport=Transport(bodies_of(documents)))
        result = combos.read_result(source, "generation-1")
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual((result["state"], result["count"], result["reason"], result["failure"], result["generation"]), ("available", 7, None, None, "generation-1"))
        self.assertEqual([s["symbol"] for s in result["stocks"]], list(SYMBOLS))
        for index, stock in enumerate(result["stocks"]):
            self.assertEqual((stock["name"], stock["exchange"], stock["security_type"], stock["currency"], stock["unit"]), (NAMES[stock["symbol"]], "TPEx", "stock", "TWD", "shares"))
            check_window(self, stock["window"], expected_from(*[expected_window(documents[index])["nets"][c] for c in ("self", "hedge")]))
            for point in stock["window"]["points"]:
                original = {(r["date"], r["name"]): (i, r) for i, r in enumerate(documents[index]["data"])}
                self.assertEqual([r["name"] for r in point["rows"]], [r["name"] for r in documents[index]["data"] if r["date"] == point["date"]])
                for row in point["rows"]:
                    position, source_row = original[(row["date"], row["name"])]
                    self.assertEqual((row["row_index"], row["buy_shares"], row["sell_shares"], row["stock_id"], row["key_order"]),
                                     (position, str(source_row["buy"]), str(source_row["sell"]), source_row["stock_id"], list(source_row)))
                for component, name in (("self", "Dealer_self"), ("hedge", "Dealer_Hedging")):
                    position, source_row = original[(point["date"], name)]
                    self.assertEqual((point[component]["row_index"], point[component]["buy_shares"], point[component]["sell_shares"]),
                                     (position, str(source_row["buy"]), str(source_row["sell"])))
                self.assertEqual((point["url"], point["request_index"]), (URLS[index], index))
        # Known shapes of the synthetic patterns (guards the expectation code itself).
        by_symbol = {s["symbol"]: s["window"] for s in result["stocks"]}
        self.assertEqual(by_symbol["6510"]["opposite"]["count"], 5)
        self.assertEqual(by_symbol["6510"]["combination_counts"]["positive_negative"], 5)
        self.assertEqual(by_symbol["5347"]["opposite"]["count"], 0)
        self.assertEqual(len(by_symbol["5347"]["segments"]["self"]), 5)

    def test_receipts_are_the_original_canonical_records_and_bind_the_bodies(self):
        transport = Transport()
        source, transport, _ = available_source(transport=transport)
        result = combos.read_result(source, "g")
        self.assertEqual([r["symbol"] for r in result["receipts"]], list(SYMBOLS))
        for index, receipt in enumerate(result["receipts"]):
            self.assertEqual(hashlib.sha256(receipt["canonical"].encode("utf-8")).hexdigest(), receipt["sha256"])
            fields = json.loads(receipt["canonical"])
            self.assertEqual((fields["url"], fields["body_sha256"], fields["body_bytes"], fields["namespace"], fields["policy_sha256"], fields["method"], fields["status"]),
                             (URLS[index], hashlib.sha256(transport.bodies[index]).hexdigest(), len(transport.bodies[index]), NAMESPACE, EXTERNAL_PIN, "GET", 200))
            self.assertEqual((receipt["url"], receipt["body_sha256"], receipt["body_bytes"], receipt["request_index"]),
                             (URLS[index], fields["body_sha256"], fields["body_bytes"], index))
            self.assertEqual(receipt["canonical"].encode("utf-8"), canonical(fields))
        for stock, receipt in zip(result["stocks"], result["receipts"]):
            for point in stock["window"]["points"]:
                self.assertEqual((point["receipt_sha256"], point["body_sha256"], point["url"]), (receipt["sha256"], receipt["body_sha256"], receipt["url"]))
        self.assertEqual(len({r["sha256"] for r in result["receipts"]}), 7)

    def test_contract_key_sets_are_exact(self):
        source, _, _ = available_source()
        result = combos.read_result(source, "g")
        self.assertEqual(sorted(result), sorted(["schema", "calculation_version", "consumer_version", "namespace", "as_of", "generation", "state", "available", "reason",
                                                 "failure", "count", "window_dates", "stocks", "calendar", "receipts", "provenance", "attempted", "request_count"]))
        stock = result["stocks"][0]
        self.assertEqual(sorted(stock), sorted(["symbol", "name", "exchange", "security_type", "currency", "unit", "window"]))
        self.assertEqual(sorted(stock["window"]), sorted(["horizon", "points", "counts", "segments", "latest", "combination_counts", "combination_dates", "opposite"]))
        point = stock["window"]["points"][0]
        self.assertEqual(sorted(point), sorted(["date", "index", "request_index", "url", "receipt_sha256", "body_sha256", "rows", "self", "hedge", "combination", "opposite"]))
        self.assertEqual(sorted(point["self"]), sorted(["row_index", "buy_shares", "sell_shares", "net_shares", "net_lots", "sign"]))
        self.assertEqual(sorted(point["rows"][0]), sorted(["row_index", "key_order", "date", "stock_id", "name", "buy_shares", "sell_shares"]))
        self.assertEqual(sorted(stock["window"]["segments"]["self"][0]), sorted(["sign", "start_index", "end_index", "start_date", "end_date", "length", "earlier_unknown"]))
        self.assertEqual(sorted(result["receipts"][0]), sorted(["request_index", "symbol", "url", "canonical", "sha256", "body_sha256", "body_bytes"]))
        self.assertEqual(sorted(result["calendar"]), sorted(["reference", "closed_dates", "calendar_gets", "window_dates", "anchor_only_dates", "meaning"]))
        self.assertEqual((result["schema"], result["calculation_version"], result["consumer_version"], result["namespace"], result["as_of"]),
                         ("dealer-direction-combos-read/finmind-stock-scope-7-v1", "dealer-self-hedging-sign-combos-counts-maximal-segments/five-session-int64-v1",
                          "dealer-self-hedging-direction-combos-five-session-v1", NAMESPACE, "2026-10-06"))
        self.assertEqual(result["window_dates"], list(WINDOW))
        self.assertEqual((result["calendar"]["reference"], result["calendar"]["calendar_gets"], result["calendar"]["closed_dates"], result["calendar"]["anchor_only_dates"]),
                         ("SOURCE_REGISTRY 31.2", 0, ["2026-09-25", "2026-09-28"], ["2026-09-29"]))
        provenance = result["provenance"]
        self.assertEqual((provenance["anchors_checked"], provenance["policy_sha256"], provenance["publication_time"], provenance["storage"]), (56, EXTERNAL_PIN, "unknown", "process_RAM"))
        self.assertIn("not PIT", provenance["value_label"])
        self.assertTrue(provenance["record_only_comparison"]["matches"])
        json.dumps(result)  # JSON-safe: no proxies, tuples of objects or bytes

    def test_non_available_states_return_blank_with_the_state_and_no_values(self):
        source, _, clock = new_source()
        blank = combos.read_result(source, "g")
        self.assertEqual((blank["available"], blank["state"], blank["reason"], blank["attempted"], blank["stocks"], blank["receipts"], blank["calendar"], blank["provenance"]),
                         (False, "new", "not_acquired", False, [], [], None, None))
        source.acquire()
        blank = combos.read_result(source, "g")
        self.assertEqual((blank["state"], blank["reason"], blank["attempted"], blank["request_count"], blank["stocks"]), ("pending", "pending_independent_admission", True, 7, []))
        admit(source)
        source.release()
        blank = combos.read_result(source, "g")
        self.assertEqual((blank["state"], blank["reason"], blank["stocks"]), ("released", "released", []))
        failed, _, _ = new_source(transport=Transport(bodies_of(broken_documents())))
        with self.assertRaises(src.SourceError):
            failed.acquire()
        blank = combos.read_result(failed, "g")
        self.assertEqual((blank["state"], blank["reason"], blank["failure"], blank["request_count"]), ("failed", "failed", {"primary_code": "name_missing", "primary_stage": "decode_parse"}, 3))
        expiring, _, clock = new_source()
        expiring.acquire()
        admit(expiring)
        clock.now += 10 ** 7
        self.assertEqual(combos.read_result(expiring, "g")["state"], "available")  # nothing expires by clock
        expiring.release(expired=True)  # the lifecycle owner's declaration is the only path into `expired`
        blank = combos.read_result(expiring, "g")
        self.assertEqual((blank["state"], blank["reason"], blank["stocks"]), ("expired", "expired", []))

    def test_a_computation_conflict_hides_every_symbol(self):
        source, _, _ = available_source()
        with patch.object(combos, "window_result", side_effect=combos.DirectionComboError("synthetic")):
            blank = combos.read_result(source, "g")
        self.assertEqual((blank["available"], blank["reason"], blank["stocks"], blank["receipts"]), (False, "calculation_conflict", [], []))
        self.assertEqual(combos.read_result(source, "g")["count"], 7)  # the source itself is unaffected


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source, self.transport, self.clock = new_source()
        self.app = combos.create_app(self.source, port=PORT)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.source.release()

    def remote(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("203.0.113.9", 5000)), base_url=ORIGIN)

    async def first(self):
        return await self.client.post(API + "/capture" + Q, json={})

    async def diagnostic(self):
        return (await self.client.get(combos.DIAGNOSTIC_PATH)).json()

    async def admission_body(self, **overrides):
        diag = await self.diagnostic()
        for capture in diag["captures"]:
            self.assertEqual(hashlib.sha256(base64.b64decode(capture["canonical_receipt_base64"])).hexdigest(), capture["receipt_sha256"])
        body = dict(namespace=NAMESPACE, policy_sha256=EXTERNAL_PIN, holder_session_id="synthetic-oracle", candidate_sha="a" * 40, script_sha256="b" * 64,
                    receipt_sha256s=[c["receipt_sha256"] for c in diag["captures"]], name_rows=210, stock_days=42, anchor_values=56,
                    record_only_matches=True, independent=True)
        body.update(overrides)
        return body

    async def admitted(self):
        self.assertEqual((await self.first()).status_code, 200)
        response = await self.client.post(combos.ADMIT_PATH, json=await self.admission_body())
        self.assertEqual((response.status_code, response.json()), (200, {"state": "available"}))

    def test_create_app_requires_one_new_source(self):
        for bad in (object(), None, "x"):
            with self.assertRaises(combos.DirectionComboError):
                combos.create_app(bad, port=PORT)
        source, _, _ = new_source()
        for port in (80, 1023, 65536, True, "8799", None, 8799.0):
            with self.assertRaises(combos.DirectionComboError, msg=repr(port)):
                combos.create_app(source, port=port)
        with self.assertRaises(TypeError):
            combos.create_app(source)  # the port is required: Host admission cannot silently default
        source.acquire()
        with self.assertRaises(combos.DirectionComboError):
            combos.create_app(source, port=PORT)

    async def test_exact_queries_methods_and_bodies_are_checked_before_any_state(self):
        for query in ("", "?as_of=", "?as_of=2026-10-06&x=1", "?as_of=2026-10-06&as_of=2026-10-06", "?as_of=2026-02-30", "?x=2026-10-06", "?as_of=20261006", "?as_of=2026-10-06&"):
            self.assertEqual((await self.client.get(API + query)).status_code, 422, query)
            self.assertEqual((await self.client.post(API + "/capture" + query, json={})).status_code, 422, query)
        self.assertEqual((await self.client.put(API + Q)).status_code, 405)
        self.assertEqual((await self.client.delete(API + "/capture" + Q)).status_code, 405)
        self.assertEqual((await self.client.get(API + "/capture" + Q)).status_code, 405)
        self.assertEqual((await self.client.post(API + Q, json={})).status_code, 405)
        self.assertEqual((await self.client.get("/api/chips/other")).status_code, 404)
        self.assertEqual((await self.client.get("/docs")).status_code, 404)
        self.assertEqual((await self.client.get("/openapi.json")).status_code, 404)
        self.assertEqual((await self.client.post(API + "/capture" + Q, json={"x": 1})).status_code, 422)
        self.assertEqual((await self.client.post(API + "/capture" + Q, json=[])).status_code, 422)
        self.assertEqual((await self.client.post(API + "/capture" + Q, content=b"not json", headers=JSON)).status_code, 422)
        self.assertEqual((await self.client.post(API + "/capture" + Q, content=b"", headers=JSON)).status_code, 422)
        self.assertEqual((await self.client.request("GET", API + Q, content=b"x")).status_code, 422)
        self.assertEqual((await self.client.post(API + "/capture" + Q, content=b"x" * 4097, headers=JSON)).status_code, 413)
        self.assertEqual((await self.client.get(combos.DIAGNOSTIC_PATH + "?x=1")).status_code, 422)
        self.assertEqual((await self.client.post(combos.ADMIT_PATH + "?x=1", json={})).status_code, 422)
        self.assertEqual((await self.client.post(combos.ADMIT_PATH, content=b"x" * 8193, headers=JSON)).status_code, 413)
        self.assertEqual((await self.client.post(combos.ADMIT_PATH, json=[])).status_code, 422)
        self.assertEqual(self.transport.opens, [])
        self.assertEqual(self.source.state, "new")

    async def test_unsupported_cutoff_never_fetches_or_spends(self):
        for method, suffix in (("GET", ""), ("POST", "/capture")):
            response = await self.client.request(method, API + suffix + "?as_of=2026-10-07", json={} if method == "POST" else None)
            self.assertEqual(response.status_code, 409)  # R1-5: unavailable answers are uniformly 409
            body = response.json()
            self.assertEqual((body["available"], body["reason"], body["as_of"], body["stocks"]), (False, "cutoff_not_supported", "2026-10-07", []))
        self.assertEqual((self.transport.opens, self.source.state), ([], "new"))

    async def test_local_only_endpoints_refuse_remote_clients(self):
        async with self.remote() as remote:
            self.assertEqual((await remote.get(combos.DIAGNOSTIC_PATH)).status_code, 403)
            self.assertEqual((await remote.post(combos.ADMIT_PATH, json={})).status_code, 403)
            self.assertEqual((await remote.get(API + Q)).status_code, 409)  # the chips read itself is not root-only
        self.assertEqual(self.source.state, "new")

    async def test_first_then_pending_then_admission_then_held_reads(self):
        self.assertEqual((await self.client.get(API + Q)).status_code, 409)
        self.assertEqual((await self.client.get(API + Q)).json()["reason"], "not_acquired")
        first = await self.first()
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual((body["available"], body["state"], body["reason"], body["attempted"], body["request_count"], body["stocks"]),
                         (False, "pending", "pending_independent_admission", True, 7, []))
        self.assertEqual(self.transport.opens, list(URLS))
        read = await self.client.get(API + Q)
        self.assertEqual((read.status_code, read.json()["reason"], read.json()["stocks"]), (409, "pending_independent_admission", []))
        again = await self.first()
        self.assertEqual((again.status_code, again.json()["reason"]), (409, "already_attempted"))
        self.assertEqual(len(self.transport.opens), 7)
        diag = await self.diagnostic()
        self.assertEqual((diag["state"], diag["attempted"], diag["policy_sha256"], diag["namespace"], diag["urls"]), ("pending", 7, EXTERNAL_PIN, NAMESPACE, list(URLS)))
        for original, item in zip(self.transport.bodies, diag["captures"]):
            self.assertEqual(base64.b64decode(item["body_base64"]), original)
            self.assertEqual(item["body_sha256"], hashlib.sha256(original).hexdigest())
        wrong = await self.client.post(combos.ADMIT_PATH, json=await self.admission_body(name_rows=209))
        self.assertEqual((wrong.status_code, wrong.json()), (409, {"reason": "oracle_complete_scope", "state": "pending"}))
        good = await self.client.post(combos.ADMIT_PATH, json=await self.admission_body())
        self.assertEqual((good.status_code, good.json()), (200, {"state": "available"}))
        reads = [await self.client.get(API + Q) for _ in range(3)]
        self.assertTrue(all(r.status_code == 200 for r in reads))
        self.assertEqual(reads[0].json(), reads[1].json())
        self.assertEqual(reads[1].json(), reads[2].json())
        payload = reads[0].json()
        self.assertEqual((payload["state"], payload["available"], payload["count"], payload["generation"]), ("available", True, 7, body["generation"]))
        documents = corpus()
        for stock, document in zip(payload["stocks"], documents):
            expected = expected_window(document)
            check_window(self, stock["window"], expected_from(expected["nets"]["self"], expected["nets"]["hedge"]))
        self.assertEqual(len(self.transport.opens), 7)  # READ never fetches
        repeat = await self.client.post(combos.ADMIT_PATH, json=await self.admission_body())
        self.assertEqual((repeat.status_code, repeat.json()["reason"]), (409, "oracle_pending_required"))
        self.assertEqual((await self.first()).status_code, 409)
        self.assertEqual(len(self.transport.opens), 7)

    async def test_admission_body_is_validated_without_changing_state(self):
        await self.first()
        cases = (
            (dict(extra=1), 409, "oracle_type"),
            (dict(name_rows="210"), 409, "oracle_type"),
            (dict(receipt_sha256s="x"), 409, "oracle_type"),
            (dict(independent=False), 409, "oracle_scope"),
            (dict(policy_sha256="0" * 64), 409, "oracle_scope"),
            (dict(record_only_matches=False), 409, "oracle_record_only"),
            (dict(anchor_values=55), 409, "oracle_complete_scope"),
        )
        for override, status, reason in cases:
            body = await self.admission_body()
            body.update(override)
            response = await self.client.post(combos.ADMIT_PATH, json=body)
            self.assertEqual((response.status_code, response.json()["reason"], response.json()["state"]), (status, reason, "pending"), override)
        missing = await self.admission_body()
        del missing["independent"]
        self.assertEqual((await self.client.post(combos.ADMIT_PATH, json=missing)).json()["reason"], "oracle_type")
        swapped = await self.admission_body()
        swapped["receipt_sha256s"][0], swapped["receipt_sha256s"][1] = swapped["receipt_sha256s"][1], swapped["receipt_sha256s"][0]
        self.assertEqual((await self.client.post(combos.ADMIT_PATH, json=swapped)).json()["reason"], "oracle_capture_binding")
        self.assertEqual(self.source.state, "pending")

    async def test_admission_before_capture_is_refused(self):
        body = dict(namespace=NAMESPACE, policy_sha256=EXTERNAL_PIN, holder_session_id="x", candidate_sha="a" * 40, script_sha256="b" * 64,
                    receipt_sha256s=[], name_rows=210, stock_days=42, anchor_values=56, record_only_matches=True, independent=True)
        response = await self.client.post(combos.ADMIT_PATH, json=body)
        self.assertEqual((response.status_code, response.json()), (409, {"reason": "oracle_pending_required", "state": "new"}))
        diag = await self.diagnostic()
        self.assertEqual((diag["state"], diag["captures"], diag["attempted"]), ("new", [], 0))

    async def test_failed_capture_is_502_spent_and_masks_everything(self):
        self.source.release()
        self.source, self.transport, self.clock = new_source(transport=Transport(bodies_of(broken_documents())))
        self.app = combos.create_app(self.source, port=PORT)
        await self.client.aclose()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN)
        first = await self.first()
        body = first.json()
        self.assertEqual(first.status_code, 502)
        self.assertEqual((body["available"], body["state"], body["reason"], body["failure"], body["request_count"], body["stocks"], body["receipts"]),
                         (False, "failed", "failed", {"primary_code": "name_missing", "primary_stage": "decode_parse"}, 3, [], []))
        read = await self.client.get(API + Q)
        self.assertEqual((read.status_code, read.json()["reason"], read.json()["stocks"]), (409, "failed", []))
        again = await self.first()
        self.assertEqual((again.status_code, again.json()["reason"]), (409, "already_attempted"))
        self.assertEqual(len(self.transport.opens), 3)  # first failure stops; nothing else is requested
        diag = await self.diagnostic()
        self.assertEqual((diag["state"], len(diag["captures"])), ("failed", 3))
        admit_response = await self.client.post(combos.ADMIT_PATH, json=await self.admission_body())
        self.assertEqual((admit_response.status_code, admit_response.json()["reason"]), (409, "oracle_pending_required"))

    async def test_two_simultaneous_first_actions_spend_exactly_one_batch(self):
        results = await asyncio.gather(self.first(), self.first(), self.first())
        self.assertEqual(sorted(r.status_code for r in results), [200, 409, 409])
        self.assertEqual(len(self.transport.opens), 7)
        self.assertEqual(self.source.ledger.attempted, tuple(range(7)))

    async def test_released_and_expired_sources_serve_no_values(self):
        await self.admitted()
        self.assertEqual((await self.client.get(API + Q)).status_code, 200)
        self.source.release()
        read = await self.client.get(API + Q)
        self.assertEqual((read.status_code, read.json()["reason"], read.json()["stocks"], read.json()["receipts"]), (409, "released", [], []))
        self.assertEqual((await self.first()).status_code, 409)
        diag = await self.diagnostic()
        self.assertEqual((diag["state"], diag["captures"]), ("released", []))
        self.assertEqual(len(self.transport.opens), 7)

    async def test_expiry_declared_by_the_lifecycle_owner_masks_values(self):
        await self.admitted()
        self.clock.now += 10 ** 7
        self.assertEqual((await self.client.get(API + Q)).status_code, 200)  # held until process exit: no clock-based expiry
        self.source.release(expired=True)
        read = await self.client.get(API + Q)
        self.assertEqual((read.status_code, read.json()["reason"], read.json()["stocks"]), (409, "expired", []))
        self.assertEqual((await self.first()).status_code, 409)
        diag = await self.diagnostic()
        self.assertEqual((diag["state"], diag["captures"]), ("expired", []))
        self.assertEqual(len(self.transport.opens), 7)

    async def test_responses_carry_only_json_and_no_cross_origin_or_cookie_headers(self):
        response = await self.client.get(API + Q)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertNotIn("set-cookie", response.headers)
        self.assertFalse([h for h in response.headers if h.startswith("access-control")])

    # --- R1-1: cross-site and DNS-rebinding guard (every refusal happens before any state or quota is touched) ---
    def assert_untouched(self):
        self.assertEqual((self.transport.opens, self.source.state), ([], "new"))
        self.assertEqual(self.source.ledger.attempted, ())

    async def calls(self, **headers):
        """The four admitted call shapes with extra/overridden headers: (label, response) pairs."""
        return [
            ("read", await self.client.get(API + Q, headers=headers)),
            ("capture", await self.client.post(API + "/capture" + Q, json={}, headers=headers)),
            ("diagnostic", await self.client.get(combos.DIAGNOSTIC_PATH, headers=headers)),
            ("admit", await self.client.post(combos.ADMIT_PATH, json={}, headers=headers)),
        ]

    async def test_host_must_be_exactly_the_own_loopback_authority(self):
        for host in ("localhost:%d" % PORT, "127.0.0.1", "127.0.0.1:%d" % (PORT + 1), "127.0.0.1:%d.evil.example" % PORT, "evil.example",
                     "evil.example:%d" % PORT, "[::1]:%d" % PORT, "127.0.0.1:0%d" % PORT, "127.0.0.1:%d x" % PORT, "", "127.0.0.2:%d" % PORT):
            for label, response in await self.calls(Host=host):
                self.assertEqual((response.status_code, response.json()), (403, {"reason": "host_not_admitted"}), (host, label))
        # Unknown paths and wrong methods are refused by the Host rule first, not leaked as 404/405.
        for method, path in (("GET", "/anything"), ("PUT", API + Q), ("DELETE", "/__dealer_direction_admit")):
            response = await self.client.request(method, path, headers={"Host": "evil.example"})
            self.assertEqual((response.status_code, response.json()["reason"]), (403, "host_not_admitted"))
        self.assert_untouched()
        # Positive case: the exact Host is admitted on all four shapes (the capture call spends the one batch).
        results = await self.calls(Host=HOST)
        self.assertEqual([r.status_code for _, r in results], [409, 200, 200, 409])
        self.assertEqual(self.transport.opens, list(URLS))

    async def test_a_rebound_name_cannot_read_the_originals_or_forge_an_admission(self):
        await self.first()
        before = await self.diagnostic()
        self.assertEqual(len(before["captures"]), 7)
        attack = await self.client.get(combos.DIAGNOSTIC_PATH, headers={"Host": "attacker.example:%d" % PORT})
        self.assertEqual((attack.status_code, attack.json()), (403, {"reason": "host_not_admitted"}))
        self.assertNotIn("captures", attack.text)
        forged = await self.client.post(combos.ADMIT_PATH, json=await self.admission_body(), headers={"Host": "attacker.example:%d" % PORT})
        self.assertEqual(forged.status_code, 403)
        self.assertEqual(self.source.state, "pending")

    async def test_sec_fetch_site_must_be_same_origin_or_none_when_present(self):
        for value in ("cross-site", "same-site", "Cross-Site", "", "same-origin, cross-site", "unknown"):
            for label, response in await self.calls(**{"Sec-Fetch-Site": value}):
                self.assertEqual((response.status_code, response.json()["reason"]), (403, "cross_site_rejected"), (value, label))
        self.assert_untouched()
        for value in ("same-origin", "none", "SAME-ORIGIN"):
            for label, response in await self.calls(**{"Sec-Fetch-Site": value}):
                self.assertNotEqual(response.status_code, 403, (value, label))
            self.assertIn(self.source.state, ("new", "pending"))

    async def test_origin_must_equal_the_own_origin_when_present(self):
        for value in ("http://evil.example", "null", "http://localhost:%d" % PORT, "http://127.0.0.1:%d" % (PORT + 1), "https://%s" % HOST,
                      "http://127.0.0.1:%d/" % PORT, "http://%s.evil.example" % HOST, "", "http://evil.example, " + ORIGIN):
            for label, response in await self.calls(Origin=value):
                self.assertEqual((response.status_code, response.json()["reason"]), (403, "origin_not_admitted"), (value, label))
        self.assert_untouched()
        for label, response in await self.calls(Origin=ORIGIN):
            self.assertNotEqual(response.status_code, 403, label)

    async def test_every_post_must_declare_json_and_a_simple_cross_site_post_cannot_spend_the_quota(self):
        for content_type in ("text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
                             "application/json5", "application/jsonx", "text/json", "application/json; charset=latin-1", "application/json; boundary=x", ""):
            headers = {"Content-Type": content_type}
            for path in (API + "/capture" + Q, combos.ADMIT_PATH):
                response = await self.client.post(path, content=b"{}", headers=headers)
                self.assertEqual((response.status_code, response.json()), (415, {"reason": "content_type_json_required"}), (content_type, path))
        no_header = await self.client.post(API + "/capture" + Q, content=b"{}")
        self.assertEqual((no_header.status_code, no_header.json()["reason"]), (415, "content_type_json_required"))
        # The classic CSRF shape: a no-cors text POST carrying '{}' from a foreign page.
        foreign = await self.client.post(API + "/capture" + Q, content=b"{}", headers={"Content-Type": "text/plain", "Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(foreign.status_code, 403)
        self.assert_untouched()
        for content_type in ("application/json; charset=utf-8", "Application/JSON", "application/json;charset=UTF-8"):
            response = await self.client.post(combos.ADMIT_PATH, content=b"{}", headers={"Content-Type": content_type})
            self.assertEqual((response.status_code, response.json()["reason"]), (409, "oracle_type"), content_type)  # admitted; the body itself is invalid
        response = await self.client.post(API + "/capture" + Q, content=b"{}", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.transport.opens, list(URLS))  # exactly one batch, only after every refusal above

    async def test_a_duplicated_guard_header_is_refused(self):
        headers = httpx.Headers([("Host", HOST), ("Host", "evil.example")])
        response = await self.client.get(API + Q, headers=headers)
        self.assertEqual((response.status_code, response.json()["reason"]), (403, "host_not_admitted"))
        headers = httpx.Headers([("Origin", ORIGIN), ("Origin", "http://evil.example")])
        self.assertEqual((await self.client.get(API + Q, headers=headers)).status_code, 403)
        headers = httpx.Headers([("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")])
        self.assertEqual((await self.client.get(API + Q, headers=headers)).status_code, 403)
        headers = httpx.Headers([("Content-Type", "application/json"), ("Content-Type", "text/plain")])
        self.assertEqual((await self.client.post(API + "/capture" + Q, content=b"{}", headers=headers)).status_code, 415)
        self.assert_untouched()

    async def test_no_cors_headers_so_a_cross_origin_preflight_cannot_succeed(self):
        for headers in ({"Origin": "http://evil.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
                        {"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}):
            response = await self.client.options(API + "/capture" + Q, headers=headers)
            self.assertIn(response.status_code, (403, 405))
            self.assertFalse([h for h in response.headers if h.lower().startswith("access-control")])
        self.assert_untouched()

    async def test_a_spent_quota_is_reported_failed_not_new(self):
        spender, _, _ = new_source()
        spender.acquire()
        source, transport, _ = new_source(ledger=spender.ledger)
        app = combos.create_app(source, port=PORT)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            first = await client.post(API + "/capture" + Q, json={})
            body = first.json()
            self.assertEqual(first.status_code, 502)
            self.assertEqual((body["available"], body["state"], body["reason"], body["failure"], body["stocks"]),
                             (False, "failed", "failed", {"primary_code": "quota_spent", "primary_stage": "quota"}, []))
            read = await client.get(API + Q)
            self.assertEqual((read.status_code, read.json()["state"], read.json()["reason"]), (409, "failed", "failed"))
            again = await client.post(API + "/capture" + Q, json={})
            self.assertEqual((again.status_code, again.json()["reason"]), (409, "already_attempted"))
        self.assertEqual(transport.opens, [])
