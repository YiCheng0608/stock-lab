"""RAM-only boundary tests for Issue 39's institutional-flow / share-volume source.

Every response here is canned bytes (documents built in this file, or real
``http.client`` parsing of canned wire bytes through a fake connection); nothing
touches the network, a database, or the disk. They prove validation, gating, admission,
lease and consumer behavior only. They are not evidence about the real FinMind
responses, which only the single sealed QA run can show.

The expected values below (formal trading days, 2026-10-06 volume anchors, and the 56
net-share anchors) are typed literals, generated once from the pinned formal blob text
with a throw-away script, so the product's parser is checked against them rather than
against itself. The pinned blob is read through ``git cat-file`` inside a fixture and
fails loudly when it is unavailable (no skip, no working-tree fallback).

Network and subprocess are blocked per test by an autouse monkeypatch guard (not a
process-wide audit hook), so importing this file has no effect on other tests.
"""

import hashlib
import http.client
import io
import json
import shutil
import socket
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from app import institutional_flow_ratio_source as m
from app.institutional_flow_ratio import FORMULA_VERSION

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
CUTOFFS = ("2026-10-05", "2026-10-06")
NAMES = ("Foreign_Investor", "Foreign_Dealer_Self", "Investment_Trust", "Dealer_self", "Dealer_Hedging")
FORMAL_DATES = ('2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11', '2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06')
VOLUME_ANCHORS = {'3105': 19731700, '3293': 1495462, '5274': 188693, '5347': 34637793, '6488': 13913614, '6510': 560518, '8069': 10796741}
NET_ANCHORS = {
    ('2026-10-05', '3105'): (28396840, 2812800, 2350894, 33560534),
    ('2026-10-05', '3293'): (6386218, 414000, -12792, 6787426),
    ('2026-10-05', '5274'): (-28586, -40427, 10254, -58759),
    ('2026-10-05', '5347'): (323290, 3600607, 339261, 4263158),
    ('2026-10-05', '6488'): (354337, 1179529, -62262, 1471604),
    ('2026-10-05', '6510'): (186887, -594227, 32887, -374453),
    ('2026-10-05', '8069'): (-4247384, -13040, 64380, -4196044),
    ('2026-10-06', '3105'): (27460450, 2352400, 2227304, 32040154),
    ('2026-10-06', '3293'): (5507085, 420000, -11177, 5915908),
    ('2026-10-06', '5274'): (-13315, -66756, 8894, -71177),
    ('2026-10-06', '5347'): (8820683, 3720607, 407416, 12948706),
    ('2026-10-06', '6488'): (594644, 1330929, -11515, 1914058),
    ('2026-10-06', '6510'): (87416, -660897, 43724, -529757),
    ('2026-10-06', '8069'): (-4053731, -9040, 285782, -3776989),
}
FORMAL_BLOB = "116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md"
FORMAL_SHA256 = "f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240"
HEX40 = "0123456789abcdef0123456789abcdef01234567"
HEX64 = "a" * 64
SESSION = "01234567-89ab-4cde-8f01-23456789abcd"


# --- guards and fixtures ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network_or_process(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("test boundary forbids network and process launch")
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(subprocess.Popen, "__init__", refuse)


@pytest.fixture(scope="module")
def formal_blob():
    git = shutil.which("git")
    if git is None:
        pytest.fail("cannot read pinned formal blob: git executable not found")
    done = subprocess.run([git, "cat-file", "blob", FORMAL_BLOB], cwd=ROOT,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    if done.returncode != 0:
        pytest.fail("pinned formal blob %s is unavailable (git exit %d): %s" % (
            FORMAL_BLOB, done.returncode, done.stderr.decode("utf-8", "replace").strip()))
    assert hashlib.sha256(done.stdout).hexdigest() == FORMAL_SHA256
    return done.stdout


# The externally generated canonical policy v1 (global coordinator, Issue 39 comment 6126200268),
# typed as data. Its pin is asserted independently in test_policy_v1_is_exactly_the_externally_pinned_document.
POLICY_V1_CANONICAL = (
    '{"acquisition":{"accept":"application/json","accept_encoding":"identity","batch_seconds":180,"bo'
    'dy_cap_bytes":1048576,"deadline":"cooperative","max_gets":15,"namespace":"issue39-seven-flow-to-'
    'volume-ratio-two-cutoffs-v1/qa1","order":"calendar, seven prices, seven flows","per_source_max_g'
    'ets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries"'
    ':0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608,"user_agent":"stock-lab-issue39-lo'
    'cal-ram/1"},"arithmetic":{"flow_window":"five trading days ending on and including the cutoff","'
    'gate":"ratio >= -3/1000, exact comparison","oracle":"independent integer rational arithmetic","r'
    'atio":"total net shares divided by the twenty-day mean volume, exact rational","volume_window":"'
    'twenty trading days ending on and including the cutoff"},"consumer_version":"institutional-flow-'
    'volume-ratio-two-cutoffs-v1","cutoffs":["2026-10-05","2026-10-06"],"first_availability":"unknown'
    '","flow_source":{"category_mapping":{"dealer":["Dealer_self","Dealer_Hedging"],"excluded":"Forei'
    'gn_Dealer_Self","foreign":"Foreign_Investor","investment_trust":"Investment_Trust"},"dataset":"T'
    'aiwanStockInstitutionalInvestorsBuySell","documentation":"https://finmind.github.io/tutor/Taiwan'
    'Market/Chip/ (doc GET receipt issue9 comment 6124059360; per-stock data_id query has no backer/s'
    'ponsor mark); free tokenless use is inferred, 401/402/403 is first failure","end_date":"2026-10-'
    '06","endpoint":"https://api.finmindtrade.com/api/v4/data","fields":{"buy":"buy","date":"date","n'
    'ame":"name","sell":"sell","stock_id":"stock_id"},"method":"GET","names":["Foreign_Investor","For'
    'eign_Dealer_Self","Investment_Trust","Dealer_self","Dealer_Hedging"],"net":"buy - sell, signed i'
    'nt64 shares","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"r'
    'ights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror",'
    '"start_date":"2026-09-01","version":"finmind-institutional-flow/issue39-v1"},"identity_as_of":"2'
    '026-10-06","instrument_type":"ordinary_stock","market":"TW/TPEx","price_source":{"basis":"provid'
    'er_reported_nominal_ohlcv","dataset":"TaiwanStockPrice","end_date":"2026-10-06","endpoint":"http'
    's://api.finmindtrade.com/api/v4/data","fields":{"amount":"Trading_money","close":"close","high":'
    '"max","low":"min","open":"open","volume":"Trading_Volume"},"method":"GET","provider":"FinMind","'
    'query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommerc'
    'ial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-09-01","version"'
    ':"finmind-price/issue39-v1"},"profile":"free_public_local","publication_time":"unknown","respons'
    'e_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type'
    '":"application/json with or without charset=utf-8; anything else rejects","duplicate_identity_he'
    'aders":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; oth'
    'er duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM","flow_rows":"ex'
    'actly the five names for each formal day, each once; Dealer or other names rejected","flow_value'
    's":"buy and sell are non-negative canonical int64; zero is a normal value","framing":"content-le'
    'ngth, chunked, or close-delimited (read to EOF within body cap); content-length and chunked toge'
    'ther rejects; cap reached without EOF rejects","set_cookie":"accepted, never stored or sent","st'
    'atus":"200 only; 401/402/403 or any paid/login response is first failure","zero_price_rows":"Fin'
    'Mind no-posted-price rows with zero OHLC, volume or amount reject the whole batch (accepted risk'
    '; suspension unsupported)"},"revision_time":"unknown","source_use":"local_personal_noncommercial'
    '_institutional_flow_to_volume_ratio","storage":"process_RAM","symbols":["3105","3293","5274","53'
    '47","6488","6510","8069"],"trading_date_source":{"dataset":"TaiwanStockTradingDate","documentati'
    'on":"https://finmind.github.io/tutor/TaiwanMarket/Technical/ (doc GET receipt issue32 comment 61'
    '11856880); free tokenless use is inferred, 401/402/403 is first failure","endpoint":"https://api'
    '.finmindtrade.com/api/v4/data","expected_scope":"formal 24 trading days 2026-09-01..2026-10-06 ('
    'SOURCE_REGISTRY 31.2), exact","fields":{"date":"date"},"formal_calendar_blob":"116bfab818fc5f72a'
    '650573c611d62b662372026:docs/SOURCE_REGISTRY.md","formal_calendar_sha256":"f27024ba1f4d5874610e3'
    '446cae34401dbeab4ea485706704e78cd4ef3844240","formal_counts":{"October_through_6":4,"September":'
    '20},"format":"json","method":"GET","provider":"FinMind","rights":"FinMind personal noncommercial'
    ' local RAM; attribution; no raw redistribution or mirror","url":"https://api.finmindtrade.com/ap'
    'i/v4/data?dataset=TaiwanStockTradingDate&start_date=2026-09-01&end_date=2026-10-06","version":"f'
    'inmind-trading-dates-checked-against-formal-sep1-oct6/issue39-v1"},"unit_policy":{"all_seven_mus'
    't_match":true,"flow":"shares","net_anchor":"SOURCE_REGISTRY 47.6 two cutoffs x seven stocks x fo'
    'ur net values, exact","provider_literal_unit_annotation":false,"scale":1,"unit_mapping_inference'
    '":true,"version":"composite-unit-inference/issue39-v1","volume":"shares","volume_anchor":"SOURCE'
    '_REGISTRY 32.2 2026-10-06 seven volumes, exact"},"unsupported":["raw_disk_storage","redistributi'
    'on","historical_pit","adjusted_prices","company_actions","trading_halt_comparability","twd_denom'
    'inator","strategy_full_chain","api_ui_db","other_cutoffs","other_symbols","gross_flow_shape_anch'
    'or"],"version":"issue39-institutional-flow-to-volume-two-cutoffs-v1"}'
)

POLICY_V1_SHA256 = "00ab692d13bfb7ea242eb5d02dc361def40f51a0b4a583a173df265bd2fd910d"
POLICY_V1_BYTES = 5541


def policy_v1():
    """A fresh dict of the pinned policy v1."""
    return json.loads(POLICY_V1_CANONICAL)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


@pytest.fixture(autouse=True)
def pinned_policy(monkeypatch):
    # The product carries policy v1's pin itself; only the process-wide one-shot ledger is reset per test.
    monkeypatch.setattr(m, "_REAL_LEDGER", None)
    return canonical(policy_v1())


def repin(monkeypatch, policy):
    raw = canonical(policy)
    monkeypatch.setattr(m, "POLICY_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(m, "POLICY_BYTES", len(raw))
    return raw, hashlib.sha256(raw).hexdigest()


def policy_args():
    raw = canonical(policy_v1())
    return {"policy_canonical": raw, "policy_sha256": hashlib.sha256(raw).hexdigest()}


# --- canned documents ------------------------------------------------------------------


def volume_for(symbol, day_index):
    if day_index == len(FORMAL_DATES) - 1:
        return VOLUME_ANCHORS[symbol]
    return 1000 + 37 * day_index + 11 * SYMBOLS.index(symbol)


def day_nets(symbol):
    """Per-day (foreign, trust, dealer) nets whose two five-day windows hit the anchors exactly."""
    first = NET_ANCHORS[("2026-10-05", symbol)]
    last = NET_ANCHORS[("2026-10-06", symbol)]
    table = {index: [0, 0, 0] for index in range(len(FORMAL_DATES))}
    for category in range(3):
        table[18][category] = first[category]    # 2026-09-29 (only in the 10-05 window)
        table[19][category] = 5                  # 2026-09-30
        table[20][category] = -5                 # 2026-10-01
        table[23][category] = last[category]     # 2026-10-06 (only in the 10-06 window)
    return table


def split_buy_sell(net, day_index):
    base = 1000 + 3 * day_index
    return (net + base, base) if net >= 0 else (base, base - net)


def flow_rows(symbol):
    rows = []
    nets = day_nets(symbol)
    for index, day in enumerate(FORMAL_DATES):
        foreign, trust, dealer = nets[index]
        per_name = {
            "Foreign_Investor": foreign,
            "Foreign_Dealer_Self": -30,
            "Investment_Trust": trust,
            "Dealer_self": dealer - 7,
            "Dealer_Hedging": 7,
        }
        for name in NAMES:
            buy, sell = split_buy_sell(per_name[name], index)
            rows.append({"date": day, "stock_id": symbol, "buy": buy, "name": name, "sell": sell})
    return rows


def price_rows(symbol):
    rows = []
    for index, day in enumerate(FORMAL_DATES):
        volume = volume_for(symbol, index)
        rows.append({"date": day, "stock_id": symbol, "Trading_Volume": volume, "Trading_money": volume * 100,
                     "open": 100, "max": 110.5, "min": 90, "close": 105, "spread": 1.5, "Trading_turnover": 40})
    return rows


def document(rows):
    return {"status": 200, "msg": "success", "data": rows}


def encode(doc):
    return json.dumps(doc, separators=(",", ":")).encode("utf-8")


def calendar_doc():
    return document([{"date": day} for day in FORMAL_DATES])


def good_documents():
    docs = [calendar_doc()]
    docs += [document(price_rows(symbol)) for symbol in SYMBOLS]
    docs += [document(flow_rows(symbol)) for symbol in SYMBOLS]
    return docs


def good_bodies():
    return [encode(doc) for doc in good_documents()]


def expected_urls():
    return ([m.TRADING_DATE_URL] + [m.PRICE_URL.format(symbol) for symbol in SYMBOLS]
            + [m.FLOW_URL.format(symbol) for symbol in SYMBOLS])


# --- boundary transport ----------------------------------------------------------------


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.status = status
        self.headers = tuple(headers if headers is not None else (
            ("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))))
        self._body = body
        self._position = 0
        self.closed = False

    @property
    def known_eof(self):
        return self._position >= len(self._body)

    def read(self, count, timeout):
        chunk = self._body[self._position:self._position + count]
        self._position += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class FakeTransport:
    """Serves the good documents; ``override[index]`` replaces one response (bytes, FakeResponse or Exception)."""

    def __init__(self, override=None, bodies=None):
        self.bodies = bodies if bodies is not None else good_bodies()
        self.override = override or {}
        self.urls = []
        self.responses = []

    def open(self, url, timeout):
        index = len(self.urls)
        self.urls.append(url)
        item = self.override.get(index, self.bodies[index])
        if isinstance(item, BaseException):
            raise item
        response = item if isinstance(item, FakeResponse) else FakeResponse(item)
        self.responses.append(response)
        return response


def make_source(transport=None, *, blob=None, ledger=None, clock=None, **extra):
    arguments = dict(policy_args())
    arguments.update(formal_blob=blob, transport=transport if transport is not None else FakeTransport(),
                     ledger=ledger if ledger is not None else m.AttemptLedger(m.NAMESPACE))
    if clock is not None:
        arguments["clock"] = clock
    arguments.update(extra)
    return m.FlowVolumeSource(**arguments)


def expect_failure(callable_, code):
    with pytest.raises(m.SourceError) as failure:
        callable_()
    assert failure.value.code == code, failure.value.diagnostics
    return failure.value


def admission(source, **override):
    hashes = tuple(capture.receipt.canonical_sha256 for capture in source.inspection()["captures"])
    values = dict(namespace=m.NAMESPACE, policy_sha256=m.POLICY_SHA256, holder_thread_id=SESSION,
                  candidate_sha=HEX40, script_sha256=HEX64, receipt_sha256s=hashes,
                  calendar_rows=24, price_rows=168, price_fields=1008, flow_rows=840, flow_fields=1680,
                  volume_anchor_fields=7, net_anchor_fields=56, independent=True)
    values.update(override)
    return m.OracleAdmission(**values)


@pytest.fixture
def available(formal_blob):
    source = make_source(blob=formal_blob)
    source.acquire()
    source.admit_independent_verification(admission(source))
    return source


class Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def expected_ratio(symbol, cutoff):
    """Independent integer-rational oracle built only from this file's typed expectations."""
    cut = FORMAL_DATES.index(cutoff)
    window = [volume_for(symbol, index) for index in range(cut - 19, cut + 1)]
    total = NET_ANCHORS[(cutoff, symbol)][3]
    return Fraction(total * 20, sum(window))


# --- formal reference ------------------------------------------------------------------


def test_formal_reference_matches_independent_typed_expectations(formal_blob):
    dates, volumes, nets = m._formal_reference(formal_blob)
    assert dates == FORMAL_DATES
    assert dict(volumes) == VOLUME_ANCHORS
    assert dict(nets) == NET_ANCHORS
    assert len(nets) * 4 == 56


@pytest.mark.parametrize("blob", [b"", b"x" * 10, "text", None])
def test_formal_blob_must_be_the_pinned_bytes(blob):
    expect_failure(lambda: m._formal_reference(blob), "formal_blob_pin")


def test_any_changed_byte_of_the_blob_is_rejected(formal_blob):
    changed = formal_blob.replace(b"### 47.6", b"### 47.5x", 1)
    assert changed != formal_blob
    expect_failure(lambda: m._formal_reference(changed), "formal_blob_pin")


def patched_blob(monkeypatch, blob, old, new):
    mutated = blob.replace(old, new, 1)
    assert mutated != blob
    monkeypatch.setattr(m, "FORMAL_SHA256", hashlib.sha256(mutated).hexdigest())
    return mutated


@pytest.mark.parametrize("old,new,code", [
    ("- Sep20：9/1、2、3、4、7、8、9、10、11、14、15、16、17、18、21、22、23、24、29、30。",
     "- Sep20：9/1、2、3、4、7、8、9、10、11、14、15、16、17、18、21、22、23、24、29。", "formal_calendar_count"),
    ("- Oct4：10/1、2、5、6。", "- Oct4：10/1、2、6、5。", "formal_calendar_order"),
    ("- Oct4：10/1、2、5、6。", "- Oct5：10/1、2、5、6。", "formal_calendar_evidence"),
    ("| 3105 | 28,396,840 | 2,812,800 | 2,350,894 | 33,560,534 |",
     "| 3105 | 28,396,840 | 2,812,800 | 2,350,894 | 33,560,535 |", "formal_net_anchor_values"),
    ("| 3293 | 6,386,218 | 414,000 | -12,792 | 6,787,426 |",
     "| 3105 | 6,386,218 | 414,000 | -12,792 | 6,787,426 |", "formal_net_anchor_set"),
    ("| 3105 | 615／623／588／592 | 19731700／", "| 3105 | 615／623／588／592 | 19731700x／", "formal_anchor_set"),
], ids=["sep_short", "oct_unordered", "oct_label", "net_total", "net_duplicate", "volume_row"])
def test_formal_blob_structure_errors_are_rejected(formal_blob, monkeypatch, old, new, code):
    mutated = patched_blob(monkeypatch, formal_blob, old.encode("utf-8"), new.encode("utf-8"))
    expect_failure(lambda: m._formal_reference(mutated), code)


def test_missing_net_anchor_section_is_rejected(formal_blob, monkeypatch):
    mutated = patched_blob(monkeypatch, formal_blob, "### 47.6".encode(), "### 47.9".encode())
    expect_failure(lambda: m._formal_reference(mutated), "formal_section")


# --- policy ----------------------------------------------------------------------------


def test_policy_v1_is_exactly_the_externally_pinned_document():
    raw = canonical(policy_v1())
    assert raw == POLICY_V1_CANONICAL.encode("utf-8")
    assert (len(raw), hashlib.sha256(raw).hexdigest()) == (5541, POLICY_V1_SHA256)
    # the product carries that pin itself (typed here, not read from the product)
    assert (m.POLICY_BYTES, m.POLICY_SHA256) == (5541, "00ab692d13bfb7ea242eb5d02dc361def40f51a0b4a583a173df265bd2fd910d")


def test_policy_v1_is_accepted_with_the_products_own_pin_and_frozen():
    policy = m.validate_policy(**policy_args())
    assert policy["acquisition"]["max_gets"] == 15 and policy["version"] == "issue39-institutional-flow-to-volume-two-cutoffs-v1"
    with pytest.raises(TypeError):
        policy["acquisition"]["max_gets"] = 1


def test_unset_policy_pin_rejects_everything(monkeypatch):
    monkeypatch.setattr(m, "POLICY_SHA256", "")
    monkeypatch.setattr(m, "POLICY_BYTES", 0)
    expect_failure(lambda: m.validate_policy(**policy_args()), "policy_pin_unset")


def test_wrong_pin_noncanonical_and_type_inputs_are_rejected():
    raw = canonical(policy_v1())
    expect_failure(lambda: m.validate_policy(raw, "0" * 64), "policy_pin")
    expect_failure(lambda: m.validate_policy(str(raw), m.POLICY_SHA256), "policy_input_type")
    expect_failure(lambda: m.validate_policy(raw, None), "policy_input_type")
    spaced = json.dumps(policy_v1(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    expect_failure(lambda: m.validate_policy(spaced, m.POLICY_SHA256), "policy_canonical_mismatch")
    expect_failure(lambda: m.validate_policy(raw[:-1] + b"\xff", m.POLICY_SHA256), "policy_encoding")


def mutate(path, value):
    def apply(policy):
        target = policy
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return apply


POLICY_CASES = [
    ("extra_key", lambda p: p.update(extra=1), "policy_keys"),
    ("missing_key", lambda p: p.pop("storage"), "policy_keys"),
    ("type", mutate(("acquisition", "max_gets"), "15"), "policy_type"),
    ("bool_as_int", mutate(("acquisition", "redirects"), False), "policy_type"),
    ("list_length", lambda p: p["unsupported"].pop(), "policy_list"),
    ("names_length", lambda p: p["flow_source"]["names"].pop(), "policy_list"),
    ("namespace", mutate(("acquisition", "namespace"), "issue39-seven-flow-to-volume-ratio-two-cutoffs-v1/qa2"), "policy_constant_mismatch"),
    ("max_gets", mutate(("acquisition", "max_gets"), 8), "policy_constant_mismatch"),
    ("user_agent", mutate(("acquisition", "user_agent"), "stock-lab-issue32-local-ram/1"), "policy_constant_mismatch"),
    ("accept", mutate(("acquisition", "accept"), "text/html"), "policy_constant_mismatch"),
    ("redirects", mutate(("acquisition", "redirects"), 1), "policy_constant_mismatch"),
    ("stop_on_first_failure", mutate(("acquisition", "stop_on_first_failure"), False), "policy_constant_mismatch"),
    ("source_use", mutate(("source_use",), "other_use"), "policy_constant_mismatch"),
    ("consumer_version", mutate(("consumer_version",), "other"), "policy_constant_mismatch"),
    ("symbols_order", lambda p: p["symbols"].reverse(), "policy_constant_mismatch"),
    ("cutoffs", lambda p: p["cutoffs"].reverse(), "policy_constant_mismatch"),
    ("names_order", lambda p: p["flow_source"]["names"].reverse(), "policy_constant_mismatch"),
    ("flow_dataset", mutate(("flow_source", "dataset"), "TaiwanStockHoldingSharesPer"), "policy_constant_mismatch"),
    ("price_dataset", mutate(("price_source", "dataset"), "TaiwanStockPriceAdj"), "policy_constant_mismatch"),
    ("flow_dates", mutate(("flow_source", "start_date"), "2026-07-01"), "policy_constant_mismatch"),
    ("formal_pin", mutate(("trading_date_source", "formal_calendar_sha256"), "0" * 64), "policy_constant_mismatch"),
    ("formal_blob", mutate(("trading_date_source", "formal_calendar_blob"),
                           "d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md"), "policy_constant_mismatch"),
]


@pytest.mark.parametrize("name,change,code", POLICY_CASES, ids=[c[0] for c in POLICY_CASES])
def test_policy_shape_and_constant_mismatches_are_rejected(monkeypatch, name, change, code):
    policy = policy_v1()
    change(policy)
    raw, digest = repin(monkeypatch, policy)
    expect_failure(lambda: m.validate_policy(raw, digest), code)


def test_source_rejects_unsupported_purpose(formal_blob):
    expect_failure(lambda: make_source(blob=formal_blob, purpose="strategy"), "unsupported_purpose")
    expect_failure(lambda: make_source(blob=formal_blob, purpose=None), "unsupported_purpose")


# --- financial start (real transport) ---------------------------------------------------


def valid_binding(**override):
    values = dict(holder_thread_id=SESSION, holder_session_id=SESSION, parent_thread_id=None,
                  model="gpt-test-1", reasoning_effort="xhigh", candidate_sha=HEX40,
                  loaded_source_sha256="b" * 64, consumer_source_sha256="c" * 64,
                  script_sha256=HEX64, native_command="python -B script.py")
    values.update(override)
    return m.ExecutionBinding(**values)


def valid_start(binding=None, **override):
    binding = binding if binding is not None else valid_binding()
    values = dict(version=m.FINANCIAL_START_VERSION,
                  issuer_thread_id="11111111-1111-4111-8111-111111111111",
                  coordinator_session_ids=("22222222-2222-4222-8222-222222222222",),
                  implementer_session_ids=("33333333-3333-4333-8333-333333333333",),
                  namespace=m.NAMESPACE, policy_sha256=m.POLICY_SHA256,
                  seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/39#issuecomment-6130000000",
                  binding=binding, authorized=True, whole_batch=True)
    values.update(override)
    return m.FinancialStart(**values)


def test_real_transport_requires_financial_start_and_binding(formal_blob):
    expect_failure(lambda: m.FlowVolumeSource(**policy_args(), formal_blob=formal_blob), "financial_start_required")


def test_valid_seal_is_accepted_and_builds_a_real_source_without_connecting(formal_blob):
    binding = valid_binding()
    source = m.FlowVolumeSource(**policy_args(), formal_blob=formal_blob,
                                financial_start=valid_start(binding), execution_binding=binding)
    assert source.state == "new"
    assert isinstance(source._transport, m._HTTPSTransport)


SEAL_CASES = [
    ("not_authorized", dict(authorized=False), "financial_start_not_authorized"),
    ("not_whole_batch", dict(whole_batch=False), "financial_start_not_authorized"),
    ("wrong_version", dict(version="issue32-financial-start-v1"), "financial_start_scope"),
    ("wrong_namespace", dict(namespace="issue39-seven-flow-to-volume-ratio-two-cutoffs-v1/qa2"), "financial_start_scope"),
    ("wrong_policy", dict(policy_sha256="d" * 64), "financial_start_scope"),
    ("issue32_seal", dict(seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6130000000"), "financial_new_explicit_seal_required"),
    ("old_seal", dict(seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/39#issuecomment-6124891317"), "financial_new_explicit_seal_required"),
    ("not_a_url", dict(seal_comment_url="seal"), "financial_new_explicit_seal_required"),
    ("empty_coordinators", dict(coordinator_session_ids=()), "financial_start_type"),
    ("bad_role_id", dict(issuer_thread_id="not-a-session"), "financial_start_scope"),
    ("duplicate_roles", dict(implementer_session_ids=("22222222-2222-4222-8222-222222222222",)), "financial_start_scope"),
    ("qa_is_a_role", dict(issuer_thread_id=SESSION), "financial_qa_identity"),
    ("text_flag", dict(authorized="yes"), "financial_start_not_authorized"),
]


@pytest.mark.parametrize("name,override,code", SEAL_CASES, ids=[c[0] for c in SEAL_CASES])
def test_seal_scope_and_identity_errors_are_rejected(formal_blob, name, override, code):
    binding = valid_binding()
    start = valid_start(binding, **override)
    expect_failure(lambda: m.FlowVolumeSource(**policy_args(), formal_blob=formal_blob,
                                              financial_start=start, execution_binding=binding), code)


BINDING_CASES = [
    ("parent_present", dict(parent_thread_id="x"), "financial_qa_not_top_level"),
    ("effort", dict(reasoning_effort="high"), "financial_qa_identity"),
    ("thread_session_differ", dict(holder_session_id="44444444-4444-4444-8444-444444444444"), "financial_qa_identity"),
    ("bad_holder", dict(holder_thread_id="x", holder_session_id="x"), "financial_qa_identity"),
    ("bad_model", dict(model="bad model!"), "financial_qa_identity"),
    ("bad_candidate", dict(candidate_sha="abc"), "financial_candidate"),
    ("bad_source_hash", dict(loaded_source_sha256="z" * 64), "financial_script_binding"),
    ("bad_consumer_hash", dict(consumer_source_sha256="short"), "financial_script_binding"),
    ("bad_script_hash", dict(script_sha256="A" * 64), "financial_script_binding"),
    ("empty_command", dict(native_command=""), "financial_binding_type"),
]


@pytest.mark.parametrize("name,override,code", BINDING_CASES, ids=[c[0] for c in BINDING_CASES])
def test_execution_binding_errors_are_rejected(formal_blob, name, override, code):
    binding = valid_binding(**override)
    start = valid_start(binding)
    expect_failure(lambda: m.FlowVolumeSource(**policy_args(), formal_blob=formal_blob,
                                              financial_start=start, execution_binding=binding), code)


def test_binding_must_equal_the_seals_binding(formal_blob):
    binding = valid_binding()
    other = valid_binding(model="gpt-test-2")
    expect_failure(lambda: m.FlowVolumeSource(**policy_args(), formal_blob=formal_blob,
                                              financial_start=valid_start(other), execution_binding=binding),
                   "financial_binding_mismatch")


def test_boundary_transport_rejects_a_seal_and_requires_its_own_ledger(formal_blob):
    binding = valid_binding()
    expect_failure(lambda: make_source(blob=formal_blob, financial_start=valid_start(binding), execution_binding=binding),
                   "financial_start_with_boundary_transport")
    expect_failure(lambda: m.FlowVolumeSource(**policy_args(), formal_blob=formal_blob, transport=FakeTransport()),
                   "boundary_ledger_required")
    expect_failure(lambda: make_source(blob=formal_blob, ledger=object()), "boundary_ledger_required")
    with pytest.raises(m.SourceError):
        m.AttemptLedger("issue39-seven-flow-to-volume-ratio-two-cutoffs-v1/qa2")


# --- success path, admission and consumer -----------------------------------------------


def failed_run(formal_blob, override, **extra):
    transport = FakeTransport(override)
    source = make_source(transport, blob=formal_blob, **extra)
    with pytest.raises(m.SourceError) as caught:
        source.acquire()
    return source, transport, caught.value


def test_acquire_requests_fifteen_urls_in_the_fixed_order_and_returns_pending(formal_blob):
    transport = FakeTransport()
    source = make_source(transport, blob=formal_blob)
    assert source.state == "new"
    expect_failure(source.inspection, "inspection_unavailable")
    assert source.acquire() is source
    assert transport.urls == expected_urls()
    assert len(transport.urls) == 15 == len(set(transport.urls))
    assert source.state == "pending"
    assert source.ledger.attempted == tuple(range(15)) and source.ledger.unrun == ()
    assert all(response.closed for response in transport.responses)
    inspection = source.inspection()
    assert len(inspection["captures"]) == 15 and len(inspection["documents"]) == 15
    assert tuple(inspection["results"]) == SYMBOLS and tuple(inspection["flows"]) == SYMBOLS
    assert [c.receipt.source_id for c in inspection["captures"]][:2] == ["finmind_trading_dates", "finmind_price/3105"]
    assert inspection["captures"][-1].receipt.source_id == "finmind_institutional_flow/8069"
    # Pending is consumer-inert until an independent oracle admits all fifteen captures.
    expect_failure(lambda: m.institutional_flow_volume_ratio_v1(source, "3105", "2026-10-05"), "consumer_unavailable")
    expect_failure(lambda: m.get_ratio_inputs(source, "3105", "2026-10-05"), "consumer_unavailable")
    expect_failure(lambda: source.provenance, "consumer_unavailable")
    expect_failure(source.acquire, "snapshot_already_attempted")


ADMISSION_CASES = [
    ("calendar_rows", dict(calendar_rows=23), "oracle_complete_scope"),
    ("price_rows", dict(price_rows=167), "oracle_complete_scope"),
    ("price_fields", dict(price_fields=1007), "oracle_complete_scope"),
    ("flow_rows", dict(flow_rows=839), "oracle_complete_scope"),
    ("flow_fields", dict(flow_fields=1679), "oracle_complete_scope"),
    ("volume_anchors", dict(volume_anchor_fields=6), "oracle_complete_scope"),
    ("net_anchors", dict(net_anchor_fields=55), "oracle_complete_scope"),
    ("not_independent", dict(independent=False), "oracle_scope"),
    ("namespace", dict(namespace="issue39-seven-flow-to-volume-ratio-two-cutoffs-v1/qa2"), "oracle_scope"),
    ("policy", dict(policy_sha256="e" * 64), "oracle_scope"),
    ("no_receipts", dict(receipt_sha256s=()), "oracle_capture_binding"),
    ("receipt_hex", dict(receipt_sha256s=("zz",) * 15), "oracle_receipt_type"),
    ("int_rows", dict(calendar_rows="24"), "oracle_type"),
    ("int_flag", dict(independent=1), "oracle_type"),
    ("list_receipts", dict(receipt_sha256s=[]), "oracle_type"),
]


@pytest.mark.parametrize("name,override,code", ADMISSION_CASES, ids=[c[0] for c in ADMISSION_CASES])
def test_admission_errors_are_rejected_and_the_snapshot_stays_pending(formal_blob, name, override, code):
    source = make_source(blob=formal_blob)
    source.acquire()
    expect_failure(lambda: source.admit_independent_verification(admission(source, **override)), code)
    assert source.state == "pending"
    expect_failure(lambda: m.institutional_flow_volume_ratio_v1(source, "3105", "2026-10-05"), "consumer_unavailable")


def test_admission_binds_the_fifteen_receipts_in_order_and_is_one_way(formal_blob):
    source = make_source(blob=formal_blob)
    source.acquire()
    good = admission(source)
    expect_failure(lambda: source.admit_independent_verification(admission(source, receipt_sha256s=good.receipt_sha256s[::-1])),
                   "oracle_capture_binding")
    expect_failure(lambda: source.admit_independent_verification(admission(source, receipt_sha256s=good.receipt_sha256s[:14])),
                   "oracle_capture_binding")
    expect_failure(lambda: source.admit_independent_verification("admitted"), "oracle_pending_required")
    source.admit_independent_verification(good)
    assert source.state == "available"
    expect_failure(lambda: source.admit_independent_verification(good), "oracle_pending_required")


def test_fourteen_ratios_equal_the_independent_integer_rational_oracle(available):
    outcomes = set()
    for symbol in SYMBOLS:
        for cutoff in CUTOFFS:
            values = m.institutional_flow_volume_ratio_v1(available, symbol, cutoff).values
            expected = expected_ratio(symbol, cutoff)
            assert (values["ratio"].numerator, values["ratio"].denominator) == (expected.numerator, expected.denominator)
            foreign, trust, dealer, total = NET_ANCHORS[(cutoff, symbol)]
            assert (values["foreign_net_shares"], values["investment_trust_net_shares"],
                    values["dealer_net_shares"], values["total_net_shares"]) == (foreign, trust, dealer, total)
            cut = FORMAL_DATES.index(cutoff)
            assert values["volume_shares_sum"] == sum(volume_for(symbol, i) for i in range(cut - 19, cut + 1))
            assert values["gate_passed"] is (expected >= Fraction(-3, 1000))
            assert values["threshold"] == m.Rational(-3, 1000)
            assert (values["flow_window_start"], values["flow_window_end"]) == (FORMAL_DATES[cut - 4], cutoff)
            assert (values["volume_window_start"], values["volume_window_end"]) == (FORMAL_DATES[cut - 19], cutoff)
            assert values["consumer_version"] == m.CONSUMER_VERSION and values["formula_version"] == FORMULA_VERSION
            outcomes.add(values["gate_passed"])
    assert outcomes == {True, False}


def test_ratio_inputs_are_the_exact_stage_one_payload_and_immutable(available):
    payload = m.get_ratio_inputs(available, "3105", "2026-10-05")
    assert payload["formula_version"] == FORMULA_VERSION and payload["purpose"] == "strategy_gate"
    assert payload["cutoff_date"] == "2026-10-05"
    assert dict(payload["flow"]) == {
        "unit": "shares", "window_trading_days": 5, "basis": "inclusive_cutoff",
        "window_start": "2026-09-29", "window_end": "2026-10-05",
        "foreign_net_shares": 28396840, "investment_trust_net_shares": 2812800,
        "dealer_net_shares": 2350894, "total_net_shares": 33560534}
    daily = payload["volume"]["daily"]
    assert isinstance(daily, tuple) and len(daily) == 20
    assert (daily[0]["date"], daily[-1]["date"]) == ("2026-09-04", "2026-10-05")
    assert [row["shares"] for row in daily] == [volume_for("3105", i) for i in range(3, 23)]
    with pytest.raises(TypeError):
        payload["flow"]["total_net_shares"] = 1
    with pytest.raises(TypeError):
        daily[0]["shares"] = 1


@pytest.mark.parametrize("symbol,cutoff", [
    ("3105", "2026-10-07"), ("3105", "2026-10-02"), ("3105", None), ("2330", "2026-10-05"),
    (3105, "2026-10-05"), (None, "2026-10-05"), ("3105 ", "2026-10-05"),
])
def test_unsupported_symbol_or_cutoff_is_rejected_after_acquisition(available, symbol, cutoff):
    expect_failure(lambda: m.institutional_flow_volume_ratio_v1(available, symbol, cutoff), "unsupported_window_scope")
    expect_failure(lambda: m.get_ratio_inputs(available, symbol, cutoff), "unsupported_window_scope")


def test_functions_require_a_snapshot_and_provenance_lists_unsupported_uses(available):
    expect_failure(lambda: m.institutional_flow_volume_ratio_v1(None, "3105", "2026-10-05"), "snapshot_required")
    expect_failure(lambda: m.get_ratio_inputs(object(), "3105", "2026-10-05"), "snapshot_required")
    provenance = available.provenance
    assert (provenance["publication_time"], provenance["first_availability"], provenance["revision_time"]) == ("unknown",) * 3
    assert provenance["namespace"] == m.NAMESPACE and provenance["formal_blob"] == m.FORMAL_BLOB
    assert provenance["trading_dates"] == FORMAL_DATES and len(provenance["receipts"]) == 15
    assert "twd_denominator" in provenance["unsupported"] and "raw_disk_storage" in provenance["unsupported"]
    assert provenance["storage"] == "process_RAM" and provenance["retained_roots_estimate_is_rss_or_peak"] is False


def test_stage_one_rejection_is_reported_as_a_plain_coded_failure(available, monkeypatch):
    def refuse(_payload):
        raise m.InstitutionalFlowRatioError("zero_volume_row", "volume.daily[3].shares")
    monkeypatch.setattr(m, "compute_institutional_flow_ratio", refuse)
    failure = expect_failure(lambda: m.institutional_flow_volume_ratio_v1(available, "3105", "2026-10-05"), "consumer_rejected")
    assert failure.diagnostics["consumer_code"] == "zero_volume_row"
    assert "shares" not in str(failure)


# --- lease, release and one-shot quota ----------------------------------------------------


def test_pending_lease_expiry_makes_the_snapshot_unusable(formal_blob):
    clock = Clock()
    source = make_source(blob=formal_blob, clock=clock, lease_seconds=30)
    source.acquire()
    assert source.state == "pending"
    clock.now += 31
    assert source.state == "expired"
    expect_failure(source.inspection, "inspection_unavailable")
    expect_failure(lambda: source.admit_independent_verification(admission_unbound()), "oracle_pending_required")


def admission_unbound():
    return m.OracleAdmission(m.NAMESPACE, m.POLICY_SHA256, SESSION, HEX40, HEX64, (), 24, 168, 1008, 840, 1680, 7, 56, True)


def test_available_lease_expiry_makes_consumers_unusable(formal_blob):
    clock = Clock()
    source = make_source(blob=formal_blob, clock=clock, lease_seconds=30)
    source.acquire()
    source.admit_independent_verification(admission(source))
    assert m.institutional_flow_volume_ratio_v1(source, "3105", "2026-10-06").values["symbol"] == "3105"
    clock.now += 30
    assert source.state == "expired"
    expect_failure(lambda: m.institutional_flow_volume_ratio_v1(source, "3105", "2026-10-06"), "consumer_unavailable")


def test_ratio_handle_stops_working_after_release_and_state_is_cleared(available):
    handle = m.institutional_flow_volume_ratio_v1(available, "6488", "2026-10-06")
    assert handle.values["symbol"] == "6488"
    available.release()
    assert available.state == "released"
    expect_failure(lambda: handle.values, "consumer_unavailable")
    expect_failure(lambda: handle.provenance, "consumer_unavailable")
    expect_failure(available.inspection, "inspection_unavailable")
    expect_failure(lambda: m.get_ratio_inputs(available, "6488", "2026-10-06"), "consumer_unavailable")
    assert not (available._captures or available._decoded_texts or available._documents
                or available._results or available._flows or available._ratios)
    assert available._formal_blob == b"" and available._dates == () and available._transport is None
    assert len(available._net_anchors) == 0 and len(available._volume_anchors) == 0
    assert available.ledger.attempted == tuple(range(15))  # the one-shot ledger is never reset


def test_quota_is_one_batch_per_ledger_even_after_release(formal_blob):
    ledger = m.AttemptLedger(m.NAMESPACE)
    first = make_source(blob=formal_blob, ledger=ledger)
    first.acquire()
    first.release()
    second = make_source(blob=formal_blob, ledger=ledger)
    expect_failure(second.acquire, "quota_spent")
    assert second.state == "new" and ledger.attempted == tuple(range(15))  # refused before any request or state change
    with pytest.raises(m.SourceError):
        ledger.charge(15)


def test_cooperative_batch_deadline_stops_the_batch(formal_blob):
    class StepClock:
        now = 0.0

        def __call__(self):
            self.now += 2.0
            return self.now
    source, transport, failure = failed_run(formal_blob, {}, clock=StepClock())
    assert failure.code == "cooperative_deadline"
    assert source.state == "failed" and len(transport.urls) < 15


def test_non_monotonic_clock_is_rejected(formal_blob):
    values = iter([100.0, 99.0] + [100.0] * 1000)
    source, _transport, failure = failed_run(formal_blob, {}, clock=lambda: next(values))
    assert failure.code == "invalid_monotonic_clock" and source.state == "failed"


def test_retained_roots_cap_stops_the_batch(formal_blob):
    holder = [None]
    transport = FakeTransport()
    source = make_source(transport, blob=formal_blob, observer_roots=lambda: holder[0])
    holder[0] = bytearray(m.ROOTS_CAP + 1)  # an external alias that pushes the estimate over the cap
    failure = expect_failure(source.acquire, "retained_roots_estimate_cap")
    assert source.state == "failed" and failure.diagnostics["estimate_bytes"] > m.ROOTS_CAP
    # and a cap breach at construction is refused before any request
    expect_failure(lambda: make_source(FakeTransport(), blob=formal_blob, observer_roots=lambda: bytearray(m.ROOTS_CAP + 1)),
                   "retained_roots_estimate_cap")


def test_response_close_failure_rejects_a_successful_capture(formal_blob):
    class BadClose(FakeResponse):
        def close(self):
            raise RuntimeError("secret detail must not be retained")
    body = good_bodies()[2]
    source, transport, failure = failed_run(formal_blob, {2: BadClose(body)})
    assert failure.code == "cleanup_failure" and "secret detail" not in repr(failure.diagnostics)
    assert source.state == "failed"


def test_transport_exception_is_a_first_failure_with_plain_diagnostics(formal_blob):
    source, transport, failure = failed_run(formal_blob, {3: OSError("connection reset secret=abc")})
    assert failure.code == "transport_or_parse_failure"
    assert len(transport.urls) == 4 and source.ledger.attempted == (0, 1, 2, 3)
    assert "secret" not in repr(dict(failure.diagnostics)) and "secret" not in repr(dict(source.diagnostics))
    assert source.diagnostics["attempts"] == 4 and source.diagnostics["primary_stage"] == "capture_open"


# --- calendar gate (before any price request) ----------------------------------------------


def with_calendar(rows=None, **doc):
    value = document([{"date": day} for day in FORMAL_DATES] if rows is None else rows)
    value.update(doc)
    return encode(value)


def calendar_rows_without(day):
    return [{"date": d} for d in FORMAL_DATES if d != day]


def calendar_rows_with(extra):
    return [{"date": d} for d in sorted(set(FORMAL_DATES) | {extra})]


CALENDAR_CASES = [
    ("missing_day", with_calendar(calendar_rows_without("2026-09-24")), "trading_dates_formal_mismatch"),
    ("missing_first_day", with_calendar(calendar_rows_without("2026-09-01")), "trading_dates_formal_mismatch"),
    ("missing_cutoff", with_calendar(calendar_rows_without("2026-10-05")), "trading_dates_cutoff"),
    ("extra_closure_day", with_calendar(calendar_rows_with("2026-09-25")), "trading_dates_formal_mismatch"),
    ("extra_weekend", with_calendar(calendar_rows_with("2026-09-26")), "trading_dates_weekday"),
    ("duplicate", with_calendar([{"date": d} for d in FORMAL_DATES[:5] + FORMAL_DATES[4:]]), "trading_dates_order"),
    ("unordered", with_calendar([{"date": d} for d in FORMAL_DATES[::-1]]), "trading_dates_order"),
    ("short_iso", with_calendar([{"date": "2026-9-1"}] + [{"date": d} for d in FORMAL_DATES[1:]]), "trading_dates_date"),
    ("compact_date", with_calendar([{"date": "20260901"}] + [{"date": d} for d in FORMAL_DATES[1:]]), "trading_dates_date"),
    ("int_date", with_calendar([{"date": 20260901}] + [{"date": d} for d in FORMAL_DATES[1:]]), "trading_dates_date"),
    ("impossible_date", with_calendar([{"date": "2026-02-30"}] + [{"date": d} for d in FORMAL_DATES]), "trading_dates_date"),
    ("row_extra_key", with_calendar([{"date": FORMAL_DATES[0], "note": 1}] + [{"date": d} for d in FORMAL_DATES[1:]]), "trading_dates_row"),
    ("row_missing_key", with_calendar([{}] + [{"date": d} for d in FORMAL_DATES[1:]]), "trading_dates_row"),
    ("row_not_object", with_calendar(["2026-09-01"] + [{"date": d} for d in FORMAL_DATES[1:]]), "trading_dates_row"),
    ("status", with_calendar(status=500), "trading_dates_status"),
    ("status_text", with_calendar(status="200"), "trading_dates_status"),
    ("msg", with_calendar(msg="error"), "trading_dates_status"),
    ("top_extra", with_calendar(extra=1), "trading_dates_document"),
    ("empty", with_calendar([]), "trading_dates_rows"),
    ("data_not_list", with_calendar(data={}), "trading_dates_rows"),
    ("outside_bad_date", with_calendar([{"date": "bad"}] + [{"date": d} for d in FORMAL_DATES]), "trading_dates_date"),
    ("outside_unordered", with_calendar([{"date": "2026-09-02"}, {"date": "2026-08-31"}] + [{"date": d} for d in FORMAL_DATES[1:]]), "trading_dates_order"),
]


@pytest.mark.parametrize("name,body,code", CALENDAR_CASES, ids=[c[0] for c in CALENDAR_CASES])
def test_calendar_errors_stop_the_batch_before_any_price_request(formal_blob, name, body, code):
    source, transport, failure = failed_run(formal_blob, {0: body})
    # document-level errors carry source_index 0; whole-calendar gates run in acquire() itself
    assert failure.code == code and failure.diagnostics.get("source_index", 0) == 0
    assert transport.urls == [m.TRADING_DATE_URL] and source.ledger.attempted == (0,)
    assert source.state == "failed"


@pytest.mark.parametrize("extra", [
    [{"date": "2026-08-31"}], [{"date": "2026-07-01"}, {"date": "2026-08-31"}], [{"date": "2026-10-07"}],
    [{"date": "2026-10-07"}, {"date": "2026-10-08"}],
], ids=["day_before", "two_before", "day_after", "two_after"])
def test_valid_rows_outside_the_window_are_dropped_after_structural_validation(formal_blob, extra):
    before = [row for row in extra if row["date"] < m.WINDOW_START]
    after = [row for row in extra if row["date"] > m.WINDOW_END]
    rows = before + [{"date": d} for d in FORMAL_DATES] + after
    source = make_source(FakeTransport({0: with_calendar(rows)}), blob=formal_blob)
    source.acquire()
    assert source.state == "pending" and source._dates == FORMAL_DATES


# --- price gate ----------------------------------------------------------------------------


def price_body(symbol_index, change):
    symbol = SYMBOLS[symbol_index]
    doc = document(price_rows(symbol))
    change(doc)
    return encode(doc)


def set_row(index, **values):
    def apply(doc):
        doc["data"][index].update(values)
    return apply


PRICE_CASES = [
    ("row_dropped", lambda d: d["data"].pop(), "price_row_count"),
    ("row_added", lambda d: d["data"].append(dict(d["data"][0])), "price_row_count"),
    ("stock_id", set_row(5, stock_id="3105"), "price_stock_id"),
    ("stock_id_int", set_row(5, stock_id=3293), "price_stock_id"),
    ("duplicate_date", set_row(5, date="2026-09-07"), "price_duplicate_or_calendar"),
    ("date_not_formal", set_row(5, date="2026-09-25"), "price_duplicate_or_calendar"),
    ("bad_date", set_row(5, date="2026-9-9"), "price_date"),
    ("missing_close", lambda d: d["data"][5].pop("close"), "price_row_fields"),
    ("unknown_key", set_row(5, extra=1), "price_row_fields"),
    ("open_zero", set_row(5, open=0), "nonpositive_price"),
    ("close_negative", set_row(5, close=-1), "nonpositive_price"),
    ("high_below_close", set_row(5, max=104), "ohlc_bounds"),
    ("low_above_open", set_row(5, min=101), "ohlc_bounds"),
    ("price_text", set_row(5, open="100"), "price_number_type"),
    ("price_bool", set_row(5, open=True), "price_number_type"),
    ("volume_zero", set_row(5, Trading_Volume=0), "canonical_int64"),
    ("volume_negative", set_row(5, Trading_Volume=-5), "canonical_int64"),
    ("volume_float", set_row(5, Trading_Volume=1000.5), "canonical_int64"),
    ("volume_text", set_row(5, Trading_Volume="1000"), "canonical_int64"),
    ("volume_bool", set_row(5, Trading_Volume=True), "canonical_int64"),
    ("volume_huge", set_row(5, Trading_Volume=2**63), "canonical_int64"),
    ("amount_zero", set_row(5, Trading_money=0), "canonical_int64"),
    ("turnover_negative", set_row(5, Trading_turnover=-1), "canonical_int64"),
    ("status", lambda d: d.update(status=403), "price_document_status"),
    ("msg", lambda d: d.update(msg="fail"), "price_document_status"),
    ("top_key", lambda d: d.update(extra=1), "price_document"),
    ("data_not_list", lambda d: d.update(data={}), "price_row_count"),
    ("anchor_volume_off_by_one", set_row(23, Trading_Volume=VOLUME_ANCHORS["3293"] + 1), "volume_anchor_mismatch"),
    ("anchor_on_wrong_day", lambda d: d["data"][22].update(Trading_Volume=VOLUME_ANCHORS["3293"]) or
     d["data"][23].update(Trading_Volume=VOLUME_ANCHORS["3293"] + 2), "volume_anchor_mismatch"),
]


@pytest.mark.parametrize("name,change,code", PRICE_CASES, ids=[c[0] for c in PRICE_CASES])
def test_price_errors_stop_the_batch_before_any_flow_request(formal_blob, name, change, code):
    source, transport, failure = failed_run(formal_blob, {2: price_body(1, change)})
    assert failure.code == code and failure.diagnostics["source_index"] == 2
    assert transport.urls == expected_urls()[:3] and source.ledger.attempted == (0, 1, 2)
    assert source.state == "failed"


def test_non_json_and_malformed_price_bodies_are_rejected(formal_blob):
    for body, code in [
        (b"\xef\xbb\xbf" + good_bodies()[1], "transport_or_parse_failure"),
        (good_bodies()[1][:-5], "transport_or_parse_failure"),
        (b"\xff\xfe", "transport_or_parse_failure"),
        (good_bodies()[1].replace(b'"date"', b'"date":"2026-09-01","date"', 1), "duplicate_json_key"),
        (good_bodies()[1].replace(b'"open":100', b'"open":NaN', 1), "nonfinite_json_number"),
        (good_bodies()[1].replace(b'"open":100', b'"open":Infinity', 1), "nonfinite_json_number"),
    ]:
        source, transport, failure = failed_run(formal_blob, {1: body})
        assert failure.code == code and failure.diagnostics["source_index"] == 1
        assert transport.urls == expected_urls()[:2]


def test_price_rows_may_omit_the_optional_columns(formal_blob):
    rows = price_rows("3105")
    for row in rows:
        row.pop("spread")
        row.pop("Trading_turnover")
    source = make_source(FakeTransport({1: encode(document(rows))}), blob=formal_blob)
    source.acquire()
    assert source.state == "pending"


def test_volume_anchor_failure_at_the_last_symbol_still_precedes_every_flow_request(formal_blob):
    body = price_body(6, set_row(23, Trading_Volume=VOLUME_ANCHORS["8069"] - 1))
    source, transport, failure = failed_run(formal_blob, {7: body})
    assert failure.code == "volume_anchor_mismatch" and failure.diagnostics["source_index"] == 7
    assert transport.urls == expected_urls()[:8]


# --- institutional flow gate -----------------------------------------------------------------


def flow_body(symbol_index, change):
    symbol = SYMBOLS[symbol_index]
    doc = document(flow_rows(symbol))
    change(doc)
    return encode(doc)


def flow_row(doc, day, name):
    return next(row for row in doc["data"] if row["date"] == day and row["name"] == name)


FLOW_CASES = [
    ("row_dropped", lambda d: d["data"].pop(), "flow_row_count"),
    ("row_added", lambda d: d["data"].append(dict(d["data"][0])), "flow_row_count"),
    ("missing_sell", lambda d: d["data"][7].pop("sell"), "flow_row_fields"),
    ("missing_name", lambda d: d["data"][7].pop("name"), "flow_row_fields"),
    ("extra_key", lambda d: d["data"][7].update(id=1), "flow_row_fields"),
    ("stock_id", lambda d: d["data"][7].update(stock_id="3105"), "flow_stock_id"),
    ("name_dealer", lambda d: d["data"][7].update(name="Dealer"), "flow_name"),
    ("name_case", lambda d: d["data"][7].update(name="foreign_investor"), "flow_name"),
    ("name_space", lambda d: d["data"][7].update(name="Dealer_self "), "flow_name"),
    ("name_none", lambda d: d["data"][7].update(name=None), "flow_name"),
    ("name_int", lambda d: d["data"][7].update(name=3), "flow_name"),
    ("date_not_formal", lambda d: d["data"][7].update(date="2026-09-25"), "flow_calendar"),
    ("date_bad", lambda d: d["data"][7].update(date="2026-9-9"), "flow_date"),
    ("duplicate_pair", lambda d: d["data"][1].update(name="Foreign_Investor"), "flow_duplicate"),
    ("buy_float", lambda d: d["data"][7].update(buy=1000.5), "canonical_int64"),
    ("buy_negative", lambda d: d["data"][7].update(buy=-1), "canonical_int64"),
    ("buy_text", lambda d: d["data"][7].update(buy="1000"), "canonical_int64"),
    ("buy_bool", lambda d: d["data"][7].update(buy=True), "canonical_int64"),
    ("buy_null", lambda d: d["data"][7].update(buy=None), "canonical_int64"),
    ("sell_huge", lambda d: d["data"][7].update(sell=2**63), "canonical_int64"),
    ("sell_negative", lambda d: d["data"][7].update(sell=-1), "canonical_int64"),
    ("status", lambda d: d.update(status=402), "flow_document_status"),
    ("msg", lambda d: d.update(msg="payment required"), "flow_document_status"),
    ("top_key", lambda d: d.update(token=1), "flow_document"),
    ("data_not_list", lambda d: d.update(data="x"), "flow_row_count"),
]


@pytest.mark.parametrize("name,change,code", FLOW_CASES, ids=[c[0] for c in FLOW_CASES])
def test_flow_structure_errors_stop_the_batch_at_that_symbol(formal_blob, name, change, code):
    source, transport, failure = failed_run(formal_blob, {10: flow_body(2, change)})
    assert failure.code == code and failure.diagnostics["source_index"] == 10
    assert transport.urls == expected_urls()[:11] and source.ledger.attempted == tuple(range(11))
    assert source.state == "failed"


NET_CASES = [
    ("foreign_plus_one", lambda d: flow_row(d, "2026-10-02", "Foreign_Investor").update(
        buy=flow_row(d, "2026-10-02", "Foreign_Investor")["buy"] + 1)),
    ("trust_minus_one", lambda d: flow_row(d, "2026-10-05", "Investment_Trust").update(
        sell=flow_row(d, "2026-10-05", "Investment_Trust")["sell"] + 1)),
    ("dealer_self_only", lambda d: flow_row(d, "2026-10-01", "Dealer_self").update(
        buy=flow_row(d, "2026-10-01", "Dealer_self")["buy"] + 1)),
    ("hedging_only", lambda d: flow_row(d, "2026-09-29", "Dealer_Hedging").update(
        sell=flow_row(d, "2026-09-29", "Dealer_Hedging")["sell"] + 1)),
    ("only_in_10_06_window", lambda d: flow_row(d, "2026-10-06", "Foreign_Investor").update(
        buy=flow_row(d, "2026-10-06", "Foreign_Investor")["buy"] + 1)),
    ("only_in_10_05_window", lambda d: flow_row(d, "2026-09-29", "Investment_Trust").update(
        buy=flow_row(d, "2026-09-29", "Investment_Trust")["buy"] + 1)),
]


@pytest.mark.parametrize("name,change", NET_CASES, ids=[c[0] for c in NET_CASES])
def test_a_single_share_of_net_difference_rejects_the_whole_batch(formal_blob, name, change):
    source, transport, failure = failed_run(formal_blob, {12: flow_body(4, change)})
    assert failure.code == "net_anchor_mismatch" and failure.diagnostics["source_index"] == 12
    assert transport.urls == expected_urls()[:13] and source.state == "failed"


def test_a_total_preserving_shift_between_categories_is_still_rejected(formal_blob):
    def shift(doc):
        row = flow_row(doc, "2026-10-02", "Foreign_Investor")
        row["buy"] += 1
        other = flow_row(doc, "2026-10-02", "Investment_Trust")
        other["buy"] -= 1
    _source, _transport, failure = failed_run(formal_blob, {8: flow_body(0, shift)})
    assert failure.code == "net_anchor_mismatch"


def test_foreign_dealer_self_and_dealer_self_hedging_split_do_not_change_the_result(formal_blob):
    def reshuffle(doc):
        for row in doc["data"]:
            if row["name"] == "Foreign_Dealer_Self":
                row["buy"] += 12345
        flow_row(doc, "2026-10-02", "Dealer_self")["buy"] += 9
        flow_row(doc, "2026-10-02", "Dealer_Hedging")["sell"] += 9
    source = make_source(FakeTransport({9: flow_body(1, reshuffle)}), blob=formal_blob)
    source.acquire()
    source.admit_independent_verification(admission(source))
    values = m.institutional_flow_volume_ratio_v1(source, "3293", "2026-10-05").values
    assert values["total_net_shares"] == NET_ANCHORS[("2026-10-05", "3293")][3]


def test_zero_buy_and_sell_rows_are_kept_as_normal_values(formal_blob):
    def zero(doc):
        row = flow_row(doc, "2026-09-02", "Foreign_Dealer_Self")
        row.update(buy=0, sell=0)
    source = make_source(FakeTransport({8: flow_body(0, zero)}), blob=formal_blob)
    source.acquire()
    zero_rows = [r for r in source.inspection()["flows"]["3105"] if r.date == "2026-09-02" and r.name == "Foreign_Dealer_Self"]
    assert [(r.buy, r.sell, r.net) for r in zero_rows] == [(0, 0, 0)]


# --- default transport: real http.client parsing of canned wire bytes -----------------------


class RawWire(io.RawIOBase):
    """Like socket.SocketIO: a raw reader that knows its socket (``_sock``), which the default
    transport uses to apply read timeouts after http.client has closed its own reference."""

    def __init__(self, data, sock):
        self._view = memoryview(data)
        self._position = 0
        self._sock = sock

    def readable(self):
        return True

    def readinto(self, buffer):
        count = min(len(buffer), len(self._view) - self._position)
        buffer[:count] = self._view[self._position:self._position + count]
        self._position += count
        return count


class WireSocket:
    def __init__(self):
        self.wire = b""
        self.sent = bytearray()

    def makefile(self, mode="rb", *args, **kwargs):
        return io.BufferedReader(RawWire(self.wire, self))

    def sendall(self, data):
        self.sent.extend(data)

    def settimeout(self, value):
        pass

    def close(self):
        pass


class WireConnection(http.client.HTTPConnection):
    """Real stdlib request formatting and response parsing; only the socket is replaced.

    It derives from HTTPConnection (not HTTPSConnection): http.client's HTTPSConnection calls
    ``super(HTTPSConnection, self)`` by global name, so replacing that name with a subclass of
    itself would recurse. Port 443 is the HTTPS default, so the formatted request is identical."""
    server = {}
    log = []

    def __init__(self, host, port=None, timeout=None, context=None, **kwargs):
        super().__init__(host, port, timeout=timeout if timeout is not None else socket._GLOBAL_DEFAULT_TIMEOUT)

    def connect(self):
        self.sock = WireSocket()

    def request(self, method, url, body=None, headers=None, **kwargs):
        super().request(method, url, body, headers or {}, **kwargs)
        full = "https://" + self.host + url
        type(self).log.append((full, bytes(self.sock.sent)))
        item = type(self).server[full]
        if isinstance(item, BaseException):
            raise item
        self.sock.wire = item


DEFAULT_HEADERS = (("Content-Type", "application/json; charset=utf-8"), ("Server", "test"),
                   ("Date", "Mon, 12 Oct 2026 12:00:00 GMT"), ("Connection", "close"))


def crlf_wire(body, *, status="200 OK", headers=DEFAULT_HEADERS, framing="length", length=None):
    lines = ["HTTP/1.1 " + status] + ["%s: %s" % pair for pair in headers]
    if framing == "length":
        lines.append("Content-Length: %s" % (len(body) if length is None else length))
    elif framing == "chunked":
        lines.append("Transfer-Encoding: chunked")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    if framing == "chunked":
        chunks = b"".join(b"%x\r\n" % len(body[i:i + 100]) + body[i:i + 100] + b"\r\n" for i in range(0, len(body), 100))
        return head + chunks + b"0\r\n\r\n"
    return head + body


@pytest.fixture
def wire(monkeypatch):
    WireConnection.server = dict(zip(expected_urls(), (crlf_wire(body) for body in good_bodies())))
    WireConnection.log = []
    monkeypatch.setattr(http.client, "HTTPSConnection", WireConnection)
    return WireConnection


def real_source(blob):
    binding = valid_binding()
    return m.FlowVolumeSource(**policy_args(), formal_blob=blob,
                              financial_start=valid_start(binding), execution_binding=binding)


def expected_request(url):
    path = url[len("https://api.finmindtrade.com"):]
    return ("GET %s HTTP/1.1\r\nHost: api.finmindtrade.com\r\nAccept-Encoding: identity\r\n"
            "Connection: close\r\nUser-Agent: %s\r\nAccept: application/json\r\n\r\n" % (path, m.USER_AGENT)).encode("ascii")


def test_default_transport_sends_the_exact_requests_and_the_real_ledger_is_spent(formal_blob, wire):
    source = real_source(formal_blob)
    source.acquire()
    assert [url for url, _sent in wire.log] == expected_urls()
    for url, sent in wire.log:
        assert sent == expected_request(url)
        assert b"Cookie" not in sent and b"Authorization" not in sent and b"Proxy" not in sent
    assert source.state == "pending" and source.ledger is m._REAL_LEDGER
    assert source.ledger.attempted == tuple(range(15))
    source.admit_independent_verification(admission(source))
    assert source.state == "available"
    # a second real source in this process has no quota and sends nothing
    again = real_source(formal_blob)
    expect_failure(again.acquire, "quota_spent")
    assert len(wire.log) == 15


def test_admission_must_carry_the_sealed_qa_identity_on_the_real_path(formal_blob, wire):
    source = real_source(formal_blob)
    source.acquire()
    for override in (dict(holder_thread_id="55555555-5555-4555-8555-555555555555"),
                     dict(candidate_sha="f" * 40), dict(script_sha256="f" * 64)):
        expect_failure(lambda: source.admit_independent_verification(admission(source, **override)), "oracle_qa_binding")
    assert source.state == "pending"


ACCEPTED_WIRES = [
    ("chunked", dict(framing="chunked")),
    ("close_delimited", dict(framing="close")),
    ("plain_json", dict(headers=(("Content-Type", "application/json"),))),
    ("mixed_case", dict(headers=(("content-type", "Application/JSON; Charset=UTF-8"),))),
    ("tight_charset", dict(headers=(("Content-Type", "application/json;charset=utf-8"),))),
    ("set_cookie", dict(headers=DEFAULT_HEADERS + (("Set-Cookie", "session=secret-cookie-value; Path=/"),))),
    ("duplicate_non_identity", dict(headers=DEFAULT_HEADERS + (("Cache-Control", "a"), ("Cache-Control", "b"),
                                                              ("Vary", "x"), ("Vary", "y"), ("Vary", "z")))),
]


@pytest.mark.parametrize("name,options", ACCEPTED_WIRES, ids=[c[0] for c in ACCEPTED_WIRES])
def test_accepted_framings_and_ignored_headers(formal_blob, wire, name, options):
    body = good_bodies()[0]
    wire.server[expected_urls()[0]] = crlf_wire(body, **options)
    source = real_source(formal_blob)
    source.acquire()
    assert source.state == "pending"
    assert source.inspection()["captures"][0].body == body
    assert "secret-cookie-value" not in repr(source.inspection()) and "secret-cookie-value" not in repr(source.diagnostics)
    assert all(b"secret-cookie-value" not in sent for _url, sent in wire.log)


REJECTED_WIRES = [
    ("http_401", dict(status="401 Unauthorized"), "http_status"),
    ("http_402", dict(status="402 Payment Required"), "http_status"),
    ("http_403", dict(status="403 Forbidden"), "http_status"),
    ("http_404", dict(status="404 Not Found"), "http_status"),
    ("http_429", dict(status="429 Too Many Requests"), "http_status"),
    ("http_500", dict(status="500 Server Error"), "http_status"),
    ("redirect_is_not_followed", dict(status="302 Found", headers=DEFAULT_HEADERS + (("Location", "https://example.com/"),)), "http_status"),
    ("gzip", dict(headers=DEFAULT_HEADERS + (("Content-Encoding", "gzip"),)), "content_encoding"),
    ("brotli", dict(headers=DEFAULT_HEADERS + (("Content-Encoding", "br"),)), "content_encoding"),
    ("dup_content_type", dict(headers=DEFAULT_HEADERS + (("Content-Type", "application/json"),)), "duplicate_framing_header"),
    ("dup_content_encoding", dict(headers=DEFAULT_HEADERS + (("Content-Encoding", "identity"), ("Content-Encoding", "identity"))), "duplicate_framing_header"),
    ("dup_content_length", dict(headers=DEFAULT_HEADERS + (("Content-Length", "5"),)), "duplicate_framing_header"),
    ("dup_transfer_encoding", dict(framing="none", headers=DEFAULT_HEADERS + (("Transfer-Encoding", "chunked"), ("Transfer-Encoding", "chunked"))), "duplicate_framing_header"),
    ("length_and_chunked", dict(headers=DEFAULT_HEADERS + (("Transfer-Encoding", "chunked"),)), "ambiguous_framing"),
    ("html", dict(headers=(("Content-Type", "text/html"),)), "content_type"),
    ("no_content_type", dict(headers=(("Server", "test"),)), "content_type"),
    ("json_prefix", dict(headers=(("Content-Type", "application/jsonx"),)), "content_type"),
    ("latin1", dict(headers=(("Content-Type", "application/json; charset=latin-1"),)), "content_type"),
    ("quoted_charset", dict(headers=(("Content-Type", 'application/json; charset="utf-8"'),)), "content_type"),
    ("bad_length_text", dict(framing="none", headers=DEFAULT_HEADERS + (("Content-Length", "abc"),)), "content_length"),
    ("negative_length", dict(framing="none", headers=DEFAULT_HEADERS + (("Content-Length", "-1"),)), "content_length"),
    ("leading_zero_length", dict(framing="none", headers=DEFAULT_HEADERS + (("Content-Length", "007"),)), "content_length"),
    ("declared_over_cap", dict(length=m.BODY_CAP + 1), "declared_body_cap"),
    ("empty_body", dict(body=b""), "empty_body"),
    ("truncated_body", dict(length=10**6), "missing_known_eof"),
]


@pytest.mark.parametrize("name,options,code", REJECTED_WIRES, ids=[c[0] for c in REJECTED_WIRES])
def test_rejected_responses_are_first_failures_with_one_request(formal_blob, wire, name, options, code):
    options = dict(options)
    body = options.pop("body", good_bodies()[0])
    wire.server[expected_urls()[0]] = crlf_wire(body, **options)
    source = real_source(formal_blob)
    expect_failure(source.acquire, code)
    assert len(wire.log) == 1 and source.ledger.attempted == (0,) and source.state == "failed"


def test_a_body_that_fills_the_cap_without_an_end_is_rejected(formal_blob, wire):
    body = b"x" * m.BODY_CAP
    wire.server[expected_urls()[0]] = crlf_wire(body, framing="close")
    source = real_source(formal_blob)
    expect_failure(source.acquire, "body_cap_without_known_eof")
    assert len(wire.log) == 1


def test_connection_errors_are_first_failures_with_a_plain_code(formal_blob, wire):
    wire.server[expected_urls()[2]] = OSError("connection reset by peer secret=abc")
    source = real_source(formal_blob)
    failure = expect_failure(source.acquire, "https_request_failure")
    assert len(wire.log) == 3 and source.ledger.attempted == (0, 1, 2)
    assert "secret" not in repr(dict(failure.diagnostics))


@pytest.mark.parametrize("url", [
    "https://example.com/api/v4/data?dataset=TaiwanStockPrice",
    "http://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice",
    "https://api.finmindtrade.com:8443/api/v4/data?dataset=TaiwanStockPrice",
    "https://user@api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice",
    "https://api.finmindtrade.com.evil.test/api/v4/data",
])
def test_default_transport_only_opens_the_finmind_https_host(url):
    expect_failure(lambda: m._HTTPSTransport().open(url, 5), "transport_url")


def test_the_test_guard_really_blocks_network_and_processes():
    with pytest.raises(AssertionError):
        socket.create_connection(("api.finmindtrade.com", 443))
    with pytest.raises(AssertionError):
        socket.socket().connect(("127.0.0.1", 9))
    with pytest.raises(AssertionError):
        subprocess.run(["git", "--version"])


# --- the machinery shared with Issue 32 stays textually identical ---------------------------


@pytest.mark.parametrize("name", [
    "_HTTPSResponse", "_HTTPSTransport", "_close_all", "_failure_values", "_raise_failure",
    "_unique_pairs", "_nonfinite", "_json", "_canonical", "_shape", "_freeze", "retained_roots_estimate",
    "_number", "_integer", "_bounds", "_iso_date", "_trading_dates", "_prices", "Receipt", "Capture", "Bar",
    "SourceError", "Rational",
])
def test_shared_transport_and_parsing_machinery_is_identical_to_issue_32(name):
    import inspect
    from app import ohlcv_history_source as issue32
    assert inspect.getsource(getattr(m, name)) == inspect.getsource(getattr(issue32, name))


def test_a_failure_at_the_last_flow_still_uses_all_fourteen_earlier_attempts(formal_blob):
    source, transport, failure = failed_run(formal_blob, {14: flow_body(6, lambda d: d["data"].pop())})
    assert failure.code == "flow_row_count" and source.ledger.attempted == tuple(range(15))
    assert source.state == "failed" and source.diagnostics["attempts"] == 15
    assert source.diagnostics["primary_code"] == "flow_row_count"
    expect_failure(lambda: m.get_ratio_inputs(source, "3105", "2026-10-05"), "consumer_unavailable")
    assert source.inspection()["diagnostics"]["code"] == "flow_row_count"


# --- the QA runner (tools/issue39_flow_volume_ratio_qa.py), exercised on canned bytes only ----------


def load_qa():
    import importlib.util
    spec = importlib.util.spec_from_file_location("issue39_qa_under_test", ROOT / "tools" / "issue39_flow_volume_ratio_qa.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def qa():
    return load_qa()


def test_qa_formal_reader_agrees_with_the_typed_expectations_and_the_pin(qa, formal_blob):
    days, volumes, nets = qa.read_formal(formal_blob)
    assert days == FORMAL_DATES and volumes == VOLUME_ANCHORS and nets == NET_ANCHORS
    assert (qa.FORMAL_BLOB, qa.FORMAL_SHA256, qa.NAMESPACE) == (FORMAL_BLOB, FORMAL_SHA256, m.NAMESPACE)
    assert qa.URLS == expected_urls() and qa.SYMBOLS == SYMBOLS and qa.CUTOFFS == CUTOFFS and qa.NAMES == NAMES
    with pytest.raises(ValueError):
        qa.read_formal(formal_blob + b"\n")


def test_qa_runner_passes_fourteen_of_fourteen_on_canned_data(qa, formal_blob):
    raw = canonical(policy_v1())
    summary = qa.run_qa(policy=raw, policy_sha256=hashlib.sha256(raw).hexdigest(), formal_blob=formal_blob,
                        transport=FakeTransport())
    assert summary["mismatches"] == [] and "failure" not in summary
    assert summary["steps"]["acquire"] == "pending" and summary["steps"]["oracle_source"] == "pass"
    assert summary["steps"]["getter_parity"] == "pass" and summary["steps"]["admission"] == "available"
    assert summary["steps"]["wrong_admissions_refused"] == 3 and summary["steps"]["ratios_matched"] == "14/14"
    assert summary["steps"]["refusals"] == {"cutoff_2026-10-07": "unsupported_window_scope",
                                            "symbol_2330": "unsupported_window_scope", "no_snapshot": "snapshot_required"}
    assert summary["steps"]["after_release"] == {"state": "released", "handle": "consumer_unavailable",
                                                 "inspection": "inspection_unavailable"}
    assert len(summary["receipts"]) == 15 and len(summary["ratios"]) == 14 and summary["ledger_attempted"] == list(range(15))
    assert all(item["product_match"] for item in summary["ratios"]) and summary["cleanup"] == {"state": "released"}
    assert summary["elapsed_within_batch_budget"] is True
    for item in summary["ratios"]:
        expected = expected_ratio(item["symbol"], item["cutoff"])
        assert item["ratio"] == "%d/%d" % (expected.numerator, expected.denominator)


def test_qa_runner_on_the_real_default_transport_path_with_the_sealed_identity(qa, formal_blob, wire):
    raw = canonical(policy_v1())
    binding = valid_binding()
    summary = qa.run_qa(policy=raw, policy_sha256=hashlib.sha256(raw).hexdigest(), formal_blob=formal_blob,
                        financial_start=valid_start(binding), binding=binding)
    assert summary["mismatches"] == [] and summary["steps"]["ratios_matched"] == "14/14"
    assert [url for url, _sent in wire.log] == expected_urls() == qa.URLS


def test_qa_runner_reports_a_first_failure_without_inventing_results(qa, formal_blob):
    raw = canonical(policy_v1())
    body = flow_body(3, lambda d: d["data"].pop())
    summary = qa.run_qa(policy=raw, policy_sha256=hashlib.sha256(raw).hexdigest(), formal_blob=formal_blob,
                        transport=FakeTransport({11: body}))
    assert summary["steps"]["acquire"] == "failed" and summary["failure"]["code"] == "flow_row_count"
    assert summary["attempts"] == 12 and summary["ratios"] == [] and summary["receipts"] == []


def test_qa_oracle_catches_a_wrong_product_ratio_even_when_the_source_gates_pass(qa, formal_blob, monkeypatch):
    from dataclasses import replace
    real = m.compute_institutional_flow_ratio

    def skewed(payload):
        result = real(payload)
        return replace(result, ratio=result.ratio + Fraction(1, 10**9))
    monkeypatch.setattr(m, "compute_institutional_flow_ratio", skewed)
    raw = canonical(policy_v1())
    summary = qa.run_qa(policy=raw, policy_sha256=hashlib.sha256(raw).hexdigest(), formal_blob=formal_blob,
                        transport=FakeTransport())
    assert summary["steps"]["ratios_matched"] == "0/14" and len(summary["mismatches"]) == 14
    assert all(label.startswith("ratio[") for label in summary["mismatches"])


def test_qa_getter_parity_catches_product_rows_that_differ_from_the_raw_bytes(qa, formal_blob, monkeypatch):
    from types import MappingProxyType
    original = m.FlowVolumeSource.inspection

    def tampered(self):
        view = dict(original(self))
        results = dict(view["results"])
        bars = list(results["5274"])
        bars[4] = m.Bar(bars[4].date, bars[4].stock_id, bars[4].open, bars[4].high, bars[4].low, bars[4].close,
                        bars[4].volume + 1, bars[4].amount, bars[4].source_index)
        results["5274"] = tuple(bars)
        view["results"] = MappingProxyType(results)
        return MappingProxyType(view)
    monkeypatch.setattr(m.FlowVolumeSource, "inspection", tampered)
    raw = canonical(policy_v1())
    summary = qa.run_qa(policy=raw, policy_sha256=hashlib.sha256(raw).hexdigest(), formal_blob=formal_blob,
                        transport=FakeTransport())
    assert summary["mismatches"] == ["product_prices[5274]"] and summary["steps"]["getter_parity"] == "fail"


def good_captures(formal_blob):
    source = make_source(blob=formal_blob)
    source.acquire()
    return source.inspection()["captures"]


def tamper(captures, index, change=None, *, body=None):
    from dataclasses import replace
    if body is None:
        doc = json.loads(captures[index].body)
        change(doc)
        body = encode(doc)
    receipt = replace(captures[index].receipt, body_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest())
    result = list(captures)
    result[index] = m.Capture(body, receipt)
    return result


def row_of(doc, day, name):
    return next(r for r in doc["data"] if r["date"] == day and r.get("name") == name)


ORACLE_CASES = [
    ("calendar_day_missing", 0, lambda d: d["data"].pop(5), "calendar_equals_formal_24"),
    ("calendar_extra_day", 0, lambda d: d["data"].insert(19, {"date": "2026-09-25"}), "calendar_equals_formal_24"),
    ("price_volume_anchor", 2, lambda d: d["data"][23].update(Trading_Volume=d["data"][23]["Trading_Volume"] + 1), "volume_anchor[3293]"),
    ("price_ohlc", 3, lambda d: d["data"][4].update(max=1), "ohlc[5274]"),
    ("price_duplicate_date", 4, lambda d: d["data"][4].update(date=d["data"][3]["date"]), "price_identity[5347]"),
    ("price_zero_amount", 5, lambda d: d["data"][4].update(Trading_money=0), "price_integers[6488]"),
    ("price_float_volume", 6, lambda d: d["data"][4].update(Trading_Volume=1000.5), "price_integers[6510]"),
    ("flow_net_off_by_one", 12, lambda d: row_of(d, "2026-10-02", "Foreign_Investor").update(
        buy=row_of(d, "2026-10-02", "Foreign_Investor")["buy"] + 1), "net_anchor[2026-10-05,6488]"),
    ("flow_bad_name", 9, lambda d: d["data"][3].update(name="Dealer"), "flow_row[3293]"),
    ("flow_negative", 8, lambda d: d["data"][3].update(sell=-1), "flow_row[3105]"),
    ("flow_missing_row", 14, lambda d: d["data"].pop(), "flow_shell[8069]"),
]


@pytest.mark.parametrize("name,index,change,label", ORACLE_CASES, ids=[c[0] for c in ORACLE_CASES])
def test_qa_oracle_independently_flags_what_the_product_gates_would_reject(qa, formal_blob, name, index, change, label):
    captures = tamper(good_captures(formal_blob), index, change)
    result = qa.oracle(captures, qa.read_formal(formal_blob))
    assert label in result["mismatches"], result["mismatches"]


def test_qa_oracle_flags_receipt_and_encoding_problems(qa, formal_blob):
    from dataclasses import replace
    captures = good_captures(formal_blob)
    formal = qa.read_formal(formal_blob)
    assert qa.oracle(captures, formal)["mismatches"] == []
    bad_hash = list(captures)
    bad_hash[3] = m.Capture(captures[3].body, replace(captures[3].receipt, body_sha256="0" * 64))
    assert "receipt_body[3]" in qa.oracle(bad_hash, formal)["mismatches"]
    bad_url = list(captures)
    bad_url[4] = m.Capture(captures[4].body, replace(captures[4].receipt, url=captures[5].receipt.url))
    assert "receipt_url[4]" in qa.oracle(bad_url, formal)["mismatches"]
    bad_type = list(captures)
    bad_type[2] = m.Capture(captures[2].body, replace(captures[2].receipt, content_type="text/html"))
    assert "content_type[2]" in qa.oracle(bad_type, formal)["mismatches"]
    assert "json[6]" in qa.oracle(tamper(captures, 6, body=b"\xef\xbb\xbf" + captures[6].body), formal)["mismatches"]
    duplicate_key = captures[7].body.replace(b'"status":200', b'"status":200,"status":200', 1)
    assert "json[7]" in qa.oracle(tamper(captures, 7, body=duplicate_key), formal)["mismatches"]
    assert "capture_count" in qa.oracle(captures[:14], formal)["mismatches"]


def seal_bytes(**override):
    seal = {"version": "issue39-financial-start-v1", "issuer_thread_id": "11111111-1111-4111-8111-111111111111",
            "coordinator_session_ids": ["22222222-2222-4222-8222-222222222222"],
            "implementer_session_ids": ["33333333-3333-4333-8333-333333333333"], "namespace": m.NAMESPACE,
            "policy_sha256": "a" * 64, "valid_from_utc": "2026-10-13T00:00:00Z", "valid_until_utc": "2026-10-13T00:45:00Z",
            "authorized": True, "whole_batch": True}
    seal.update(override)
    return json.dumps(seal, sort_keys=True).encode("utf-8")


def test_qa_seal_must_match_its_pin_keys_window_and_scope(qa):
    from datetime import datetime, timezone
    inside = datetime(2026, 10, 13, 0, 10, tzinfo=timezone.utc)
    raw = seal_bytes()
    assert qa.parse_seal(raw, hashlib.sha256(raw).hexdigest(), inside)["namespace"] == m.NAMESPACE
    for bad_raw, now in [
        (raw, inside.replace(hour=1)),                      # expired
        (raw, inside.replace(day=12)),                      # not yet valid
        (seal_bytes(namespace="other"), inside),
        (seal_bytes(version="issue32-financial-start-v1"), inside),
        (seal_bytes(extra=1), inside),
    ]:
        with pytest.raises(ValueError):
            qa.parse_seal(bad_raw, hashlib.sha256(bad_raw).hexdigest(), now)
    with pytest.raises(ValueError):
        qa.parse_seal(raw, "0" * 64, inside)


def test_qa_preflight_reports_problems_and_never_touches_the_network(qa, formal_blob, monkeypatch, tmp_path, capsys):
    from datetime import datetime, timezone
    policy = canonical(policy_v1())
    policy_file, seal_file = tmp_path / "policy.json", tmp_path / "seal.json"
    policy_file.write_bytes(policy)
    seal = seal_bytes(policy_sha256=hashlib.sha256(policy).hexdigest())
    seal_file.write_bytes(seal)
    state = {"status": b"", "rev": b"0123456789abcdef0123456789abcdef01234567\n"}

    def fake_git(*args):
        if args[0] == "cat-file":
            return formal_blob
        if args[0] == "rev-parse":
            return state["rev"]
        return state["status"]
    monkeypatch.setattr(qa, "git", fake_git)

    from types import SimpleNamespace
    Args = SimpleNamespace(policy_file=str(policy_file), policy_sha256=hashlib.sha256(policy).hexdigest(),
                           seal_file=str(seal_file), seal_sha256=hashlib.sha256(seal).hexdigest())
    now = datetime(2026, 10, 13, 0, 10, tzinfo=timezone.utc)
    # The product carries policy v1's pin itself, so pre-flight with the real product file is clean.
    info, raw_policy, parsed_seal, blob = qa.preflight(Args, now)
    assert info["problems"] == [] and raw_policy == policy and blob == formal_blob
    assert info["candidate_sha"] == "0123456789abcdef0123456789abcdef01234567"
    assert info["product_sha256"] == hashlib.sha256((ROOT / "backend/app/institutional_flow_ratio_source.py").read_bytes()).hexdigest()
    # A different policy (valid for its own pin and seal) is reported as not matching the product's pin.
    other = canonical({**policy_v1(), "profile": "free_public_local_other"})
    other_file, other_seal = tmp_path / "other.json", tmp_path / "other_seal.json"
    other_file.write_bytes(other)
    other_seal_raw = seal_bytes(policy_sha256=hashlib.sha256(other).hexdigest())
    other_seal.write_bytes(other_seal_raw)
    different = SimpleNamespace(policy_file=str(other_file), policy_sha256=hashlib.sha256(other).hexdigest(),
                                seal_file=str(other_seal), seal_sha256=hashlib.sha256(other_seal_raw).hexdigest())
    assert qa.preflight(different, now)[0]["problems"] == ["product POLICY_SHA256 is not the supplied policy pin",
                                                           "product POLICY_BYTES is not the supplied policy length"]
    # An unset product pin (a scratch copy of the module text) is reported the same way.
    unset = (ROOT / "backend/app/institutional_flow_ratio_source.py").read_text(encoding="utf-8")
    unset = unset.replace('POLICY_SHA256 = "%s"' % Args.policy_sha256, 'POLICY_SHA256 = ""', 1).replace("POLICY_BYTES = 5541", "POLICY_BYTES = 0", 1)
    scratch = tmp_path / "product_unset.py"
    scratch.write_text(unset, encoding="utf-8")
    monkeypatch.setattr(qa, "PRODUCT_FILE", scratch)
    assert qa.preflight(Args, now)[0]["problems"] == ["product POLICY_SHA256 is not the supplied policy pin",
                                                      "product POLICY_BYTES is not the supplied policy length"]
    monkeypatch.setattr(qa, "PRODUCT_FILE", ROOT / "backend/app/institutional_flow_ratio_source.py")
    assert info["consumer_sha256"] == hashlib.sha256((ROOT / "backend/app/institutional_flow_ratio.py").read_bytes()).hexdigest()
    state["status"] = b" M backend/app/x.py\n"
    assert "working tree is not clean" in qa.preflight(Args, now)[0]["problems"]
    state["status"] = b""

    wrong = SimpleNamespace(**{**vars(Args), "policy_sha256": "0" * 64})
    assert "policy bytes do not match --policy-sha256" in qa.preflight(wrong, now)[0]["problems"]


def test_qa_guard_allows_only_the_finmind_https_host_and_blocks_processes_and_writes(qa, monkeypatch):
    import os
    import sys
    captured = []
    monkeypatch.setattr(sys, "addaudithook", captured.append)  # never install a real process-wide hook in tests
    fresh = qa.install_guard()
    with pytest.raises(AssertionError):                         # no resolve of the allowed host yet
        captured[0]("socket.connect", (None, ("104.18.0.1", 443)))
    assert fresh == {"resolve_ok": 0, "connect_ok": 0, "blocked": 1}
    stats = qa.install_guard()
    audit = captured[1]
    audit("socket.getaddrinfo", ("api.finmindtrade.com", 443, 0, 1, 0, 0))
    audit("socket.connect", (None, ("104.18.0.1", 443)))
    audit("socket.connect", (None, ("2606:4700::1", 443, 0, 0)))  # a dual-stack second attempt is legitimate
    audit("open", ("module.py", "rb", os.O_RDONLY))
    assert stats == {"resolve_ok": 1, "connect_ok": 2, "blocked": 0}
    for event, args in [
        ("socket.getaddrinfo", ("example.com", 443, 0, 1, 0, 0)),
        ("socket.getaddrinfo", ("api.finmindtrade.com", 80, 0, 1, 0, 0)),
        ("socket.connect", (None, ("104.18.0.1", 80))),
        ("socket.connect_ex", (None, ("104.18.0.1", 443))),
        ("subprocess.Popen", ("git", ["git"], None, None)),
        ("os.system", ("echo",)),
        ("open", ("out.txt", "w", os.O_WRONLY)),
        ("open", ("out.txt", "r+", os.O_RDWR)),
        ("os.remove", ("out.txt", None)),
    ]:
        with pytest.raises(AssertionError):
            audit(event, args)
    assert stats["blocked"] == 9 and stats["connect_ok"] == 2
