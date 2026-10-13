"""Standalone RAM boundary selftests; no pytest/conftest, provider GET, or disk IO.

Run: python -B -X utf8 backend/tests/test_taiex_price_index_source.py
Reads only this source/test and the pinned git blob d8918bc...:docs/SOURCE_REGISTRY.md
(via git cat-file before the audit hook is installed; never the working-tree registry).
The audit hook then forbids sockets, DNS, subprocesses and file writes. The policy
literal below is the draft in Issue 33 comment 6123915229 (5,038 B) and the old qa1
policy is kept only compressed to prove it is now rejected; neither was produced by
product helpers. Response-shape cases are canned wire bytes parsed by the real
http.client. All price documents are synthetic: they prove no real source, unit,
calendar or independent QA acceptance criterion.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import types
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from math import gcd
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
FORMAL_OBJECT = "d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md"


def _read_pinned_formal_blob():
    """Read the pinned formal blob from git once, before the audit hook forbids subprocess.

    Never the working-tree file: later sections edit it and master merges replace it.
    An unavailable blob (no git, shallow clone) fails loudly: no skip, no fallback."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("cannot read pinned formal blob %s: git executable not found" % FORMAL_OBJECT)
    try:
        done = subprocess.run([git, "cat-file", "blob", FORMAL_OBJECT], cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("cannot read pinned formal blob %s: git cat-file failed to run (%r)" % (FORMAL_OBJECT, error)) from error
    if done.returncode != 0:
        raise RuntimeError("pinned formal blob %s is unavailable (git cat-file exit %d)" % (FORMAL_OBJECT, done.returncode))
    return done.stdout


FORMAL = _read_pinned_formal_blob()


def _audit_boundary(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname", "subprocess.Popen", "os.system"):
        raise AssertionError("standalone boundary runner forbids network/process launch")
    if event == "open":
        _, mode, flags = args
        if (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("standalone boundary runner forbids disk writes")


if not sys.dont_write_bytecode:
    raise RuntimeError("Use -B: the boundary runner does not permit bytecode artifacts")
sys.addaudithook(_audit_boundary)

POLICY = b'{"acquisition":{"accept":"application/json","accept_encoding":"identity","artifact_bytes":0,"batch_seconds":180,"body_cap_bytes":1048576,"deadline":"cooperative","max_gets":1,"namespace":"issue33-taiex-nominal-observation-cutoffs-1005-1006-v1/qa2","order":"one FinMind TaiwanStockPrice GET","redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":1048576,"user_agent":"stock-lab-issue33-local-ram/1"},"arithmetic":{"interval_count":20,"observation_count":21,"ratio":"(C_end-C_start)/C_start as exact reduced integer numerator/positive denominator; no floating/context rounding","windows":"cutoff inclusive; last 21 observed dates at or before cutoff; never shrunk"},"calendar_basis":"cross_market_candidate_inference","consumer_version":"taiex-nominal-price-index-window-summary-v1","cutoffs":["2026-10-05","2026-10-06"],"first_availability":"unknown","formal_calendar":{"blob":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md","bytes":268729,"expected_scope":"in-range FinMind dates must equal exactly the 22 dates derived from formal section 31.2 (Sep20 on or after 2026-09-03 plus Oct4); no closure inferred from missing rows; never shrunk; any mismatch rejects whole batch; equality proves only the provider observation set, not complete TWSE sessions or Sep 25/28 closures","section":"31.2","sha256":"b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"},"identity_as_of":"2026-10-06","instrument_type":"price_index","market":"TW/TWSE","price_basis":"nominal_index_level","price_source":{"basis":"provider_reported_nominal_index_level","data_id":"TAIEX","data_id_evidence":"inference only (maintainer legacy TAIEX name plus current daily v4 route): https://github.com/YiCheng0608/stock-lab/issues/21#issuecomment-6085505949 ; actual acceptance is proven only by the sole QA GET","dataset":"TaiwanStockPrice","documentation":"https://finmind.github.io/tutor/TaiwanMarket/Technical/ (doc GET receipt issue32 comment 6111856880); free tokenless use is inferred, 401/402/403 is first failure","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","fields":{"close":"close","high":"max","low":"min","open":"open"},"known_unadopted_fields":["Trading_Volume","Trading_money","Trading_turnover","spread"],"method":"GET","ohlc_rule":"in-range rows only: open/max/min/close finite positive Decimal and min <= min(open, close) <= max(open, close) <= max; any violation rejects whole batch","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"required_row_keys":["close","date","max","min","open","stock_id"],"rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-09-03","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=TAIEX&start_date=2026-09-03&end_date=2026-10-06"},"profile":"free_public_local","publication_time":"unknown","response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8; anything else rejects","document":"{status:200, msg:success, data:[...]}; every returned row structurally validated (date ISO unique ascending, stock_id exactly TAIEX, required keys present, only known keys) before rows outside 2026-09-03..2026-10-06 are discarded; exactly 22 in-range rows","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure","zero_price_rows":"in-range rows with non-positive OHLC reject the whole batch (accepted risk)"},"revision_time":"unknown","schema":"issue33-taiex-nominal-observed-window-policy/v2","source_use":"local_personal_noncommercial_process_ram_nominal_observation_snapshot","storage":"process_RAM","symbol":"TAIEX","unit_policy":{"OHLC":"index_points_nominal_level","independent_anchor":"none: TWSE MI_5MINS_HIST removed by user decision (issue1 comment 6123465763); oracle/consumer comparisons are internal consistency of one body, not independent scale verification","provider_literal_unit_annotation":false,"scale":1,"unit_mapping_inference":true,"version":"issue33-finmind-only-scale1-v2"},"unsupported":["historical_pit","publication_time","first_availability","revision_history","verified_twse_calendar","canonical_20_trading_day_benchmark","adjusted_basis","total_return","independent_unit_anchor","hot_group_v1","canonical_regime","actionable_strategy","plan","trading","historical_simulation","raw_disk_storage","redistribution","mirror","other_cutoffs"],"version":"issue33-taiex-nominal-observed-window-finmind-v2"}'
POLICY_SHA256_LITERAL = "04be101a61b6eba5ae6ba5773c24314718765c37ae7c67eacfd8813efb64d9dc"
POLICY_PIN = "https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-6123915229"
# Old qa1 policy (Issue 33 comment 6085684135, 4,096 B), zlib+base64, only to prove it is rejected.
OLD_POLICY_B64Z = (
    "eNrtV8uKJEUU3c9XDDUwKJidr3oONIP0DNqLdqR7BBsZgsjMyKqwMyPSiMiqLoYBdy4UV77AATe6ci9u/Btpmb/w3siMrKrO"
    "1HEhuHFTVJ2IuI84N8699fzO3bsjna5YSUcP7o641jWLY89Qzq49IUsuaOHJRDO1Zpm34SKTG6+SBU+3/jocvYXH7SE8fclP"
    "Vkwsg2kw97WR6ZVX0OReHDfbBC2ZrmjKXueIGi6Fl9ZG5rn2wiCY4MfUW4f+J7T1uWZKwy40JVUGh9X2NUG7aPW2TGSBB5++"
    "ffr4wwZsnQH6EfwEIAqiKXj1gondsI9MRwA8s8ecD5JRw26fDhZeEB+cRmTcQ2Y9ZN5DFreRMOghYQ/p+QonPWTaQ3rxhL14"
    "op6vKOohvdyjXjxRL6846N132EOiHvK3LDUFgPQ87x1zlA2RNkTbEHFD1A2RN0TfEIFDFA6ROETjEJFDVA6ROUTnEKFDlA6R"
    "OkTrELFD1B6yZKFnfYqH2Pufqf+SqT42bdmDzxeN1tKCiYwqklDN8VWOUiW1JiVVV8yQlIqMo54SLnKmmEgZEdIQUHyec9Ba"
    "s9GMaKZR/3Uj35XisKuz17YA0sDw+tk1KdiaFdYQzT6utQFDUhEjDexTzNRKNKZqwY1tUPZUJbkwerdCrgDHZXZdQQ8EoOAl"
    "R2OpLBNwiq1rF7iLTq55xhTsNUyBv9ZHTgvNmp6EdwJI2FwQ5FWXTKGfw55mE/JsaK6twc4Sm59rb7lUZV3YZv7GCYGL9k6I"
    "NlSZN/32S7NPYaiQeaWYZsLYwJvEaGoAz+oUsoLs2RIiFxgPNXBjldTc8DUjGWuiAnC01wybG0hlLTDFqMkIzcBSscOD5kpV"
    "sdc1V8ZU+oHvbzabIyT5CO4UvviQKKStz1kllfHPTsnk7PS9C/Lu6cXThxB9BdfFjmXFBLZh6jqBs0YrfpRzAaFmRtHMWkXQ"
    "X4993P8QPzQzx08p31BxgXPL+3jP93GB8OzYzgn37d3ZRn+86xT34YL3sNvjQZ5DjUDa3YDVZnrz7U83L39wkb765vM/vv/x"
    "5ovPbr7+1WE3Lz999fN3Pez33768hX31y+5s37F9R0tFsUZ27s+fnJDLy0v/7Mx/9MhZasGzM4D6hhT7pObqLyad189Jzkwp"
    "hVlhmbW7RofLSww3YVDDjLScwWaj6uaZUJGuoAQVK7pyTaRZEQ2TZZNqWkgQh6aG7aNyQ19dYfFA/LW282chUxQImCIlKoWQ"
    "AsoCatyGAQ8W6k0TuDfitGS/urWglV5J43Shs75XyxwGYKgitMaNu5uqTkA1GiOGl8zhOVcahGlNOQzMHGRi61YUW3MUOtIY"
    "7PBDNXSS6lY7iWsk0b0IEL+lknVF1t1MBWorhQ1TseVeRHCB4JUmBUgtPBtQgc51VVDhvuOL4mK5ixYWu40Z11dwhxuCkdNl"
    "ZxshKCVISPGktky2KyVXSnZZALUgPW4074pJ8eXKDMjGkptVndjnPfhHxLf/ObQfhffsN0u4MB5smkTTII4Xt6Xjn1qc3TY4"
    "my2iaLEIbhtERTlayjWqGhQCA+Ha5dX1xbxRYNdDoFqz+SKcJ+l0vAhZOmf5dDKfjRezRZrP51kYR1GWRxkdxw8ymWr/4skH"
    "5yePyfnjd0Ahzy+PyuxeHB5FXavEfkGgDuC9MGxMrZN/4x4nwWQxXrT/qeCR7Gbukl5bEWHache1N5PIbEuSbaMpYTCeT2ZT"
    "V1tNb4ZicetRsJiFE3c0Y2lBUZKUlEYTMAyZoX60u+N4MhmP46irTescJgfor5numhAGQU262lsI50F3KAPVS23IOwzqlu0j"
    "0Bi4Jc25DrphB6/XwHuGTpxKfCpEimK7L2op+MA9MAxAe5RXnKH+XG8PBoRGIHLQh1rhi5QV0dDwzL4hge3cqAPjIKIgmrYF"
    "2fblZLzdc+fFnxcAWqQ="
)
OLD_POLICY_SHA256_LITERAL = "4b1f44b0e77950bcd12896f5e54f99c6262365fcf4965b4938420edb58e54eca"

MODULE_PATH = ROOT / "backend" / "app" / "taiex_price_index_source.py"
SPEC = importlib.util.spec_from_file_location("issue33_boundary_product", MODULE_PATH)
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)

# Independent literals (AC text / policy), never product constants.
URL_LITERAL = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=TAIEX"
               "&start_date=2026-09-03&end_date=2026-10-06")
NAMESPACE_LITERAL = "issue33-taiex-nominal-observation-cutoffs-1005-1006-v1/qa2"
QA1_NAMESPACE = "issue33-taiex-nominal-observation-cutoffs-1005-1006-v1/qa1"
CONSUMER_LITERAL = "taiex-nominal-price-index-window-summary-v1"
USE_LITERAL = "local_personal_noncommercial_process_ram_nominal_observation_snapshot"
CUTOFFS_LITERAL = ("2026-10-05", "2026-10-06")
CAPS_LITERAL = {"max_gets": 1, "body_cap_bytes": 1048576, "total_raw_cap_bytes": 1048576,
                "retained_roots_estimate_cap_bytes": 33554432, "request_seconds": 20, "batch_seconds": 180,
                "redirects": 0, "retries": 0, "artifact_bytes": 0}
RIGHTS_LITERAL = "FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror"
FINMIND_REQUEST_HEADERS = {"Accept-Encoding": "identity", "Connection": "close",
                           "User-Agent": "stock-lab-issue33-local-ram/1", "Accept": "application/json"}
SEAL_PIN = "https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-9999999999"
UNADOPTED_TEST_KEYS = ("Trading_Volume", "Trading_money", "spread", "Trading_turnover")
# AC-3 sets typed from the Issue text as MM-DD tokens.
WINDOW_1005 = tuple("2026-" + day for day in (
    "09-03 09-04 09-07 09-08 09-09 09-10 09-11 09-14 09-15 09-16 09-17 09-18 09-21 09-22 09-23 09-24 "
    "09-29 09-30 10-01 10-02 10-05").split())
WINDOW_1006 = tuple("2026-" + day for day in (
    "09-04 09-07 09-08 09-09 09-10 09-11 09-14 09-15 09-16 09-17 09-18 09-21 09-22 09-23 09-24 09-29 "
    "09-30 10-01 10-02 10-05 10-06").split())
WINDOWS_LITERAL = {"2026-10-05": WINDOW_1005, "2026-10-06": WINDOW_1006}
DATES = tuple(sorted(set(WINDOW_1005) | set(WINDOW_1006)))
assert len(WINDOW_1005) == len(WINDOW_1006) == 21 and len(DATES) == 22
assert hashlib.sha256(FORMAL).hexdigest() == "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"
CLOSES = {day: Decimal("20000.25") + Decimal(index) * Decimal("13.5") for index, day in enumerate(DATES)}


def row_text(day, close, *, open_=None, high=None, low=None, volume=123456789, money=98765432100, spread="1.5", turnover=4567):
    close = Decimal(close)
    open_ = close - 1 if open_ is None else open_
    high = close + Decimal("2.5") if high is None else high
    low = close - Decimal("3.5") if low is None else low
    return ('{"date":"%s","stock_id":"TAIEX","Trading_Volume":%d,"Trading_money":%d,"open":%s,"max":%s,"min":%s,'
            '"close":%s,"spread":%s,"Trading_turnover":%d}' % (day, volume, money, open_, high, low, close, spread, turnover))


def document_text(rows, status="200", msg='"success"'):
    return '{"msg":%s,"status":%s,"data":[%s]}' % (msg, status, ",".join(rows))


def default_rows():
    return [row_text(day, CLOSES[day]) for day in DATES]


DEFAULT_BODY = document_text(default_rows()).encode("utf-8")


def body_with(rows):
    return document_text(rows).encode("utf-8")


def swap(body, old, new, count=1):
    assert old in body, old
    return body.replace(old, new, count)


class Clock:
    def __init__(self):
        self.elapsed = 0.0
        self.now = datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)

    def monotonic(self):
        return self.elapsed

    def utc(self):
        return self.now + timedelta(seconds=self.elapsed)


class Response:
    def __init__(self, body, *, declared=True, cap_eof=True, status=200, headers=None, extra=(), oversize=False,
                 clock=None, slow=False, read_seconds=0):
        self.body, self.position, self.closed = body, 0, False
        self.declared, self.cap_eof, self.oversize = declared, cap_eof, oversize
        self.status = status
        default = [("Content-Type", "application/json")] + ([("Content-Length", str(len(body)))] if declared else [])
        self.headers = (list(headers) if headers is not None else default) + list(extra)
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
    def __init__(self, owner, body, options, clock):
        self.body = owner.track("fake_transport_body", body)
        self.options, self.clock, self.opened, self.responses = options, clock, [], []

    def open(self, url, timeout):
        self.opened.append(url)
        response = Response(self.body, clock=self.clock, **self.options)
        self.responses.append(response)
        return response


def policy():
    return M.ExternalPolicy.from_external(POLICY, M.POLICY_SHA256, POLICY_PIN)


def seal_for(p, mutate=None, pin=SEAL_PIN):
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
                "namespace": NAMESPACE_LITERAL, "policy_sha256": p.sha256, "policy_pin": p.pin,
                **binding, "parent_thread": None,
                "authorized_by": "33333333-3333-3333-3333-333333333333",
                "financial_start": True, "issued_at_utc": "2026-10-10T00:59:00Z",
                "expires_at_utc": "2026-10-10T01:05:00Z", "consumer": CONSUMER_LITERAL,
                "supported_use": USE_LITERAL, "urls": [URL_LITERAL],
                "cutoffs": list(CUTOFFS_LITERAL), "caps": dict(CAPS_LITERAL)}
    if mutate:
        mutate(document)
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    return M.FinancialStartSeal.from_external(raw, hashlib.sha256(raw).hexdigest(), pin, p, binding), binding


def independent_hooks(owner, *, observer=None, finmind=None):
    def observe(raw, receipt):
        assert receipt["eof"] is True
        assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
        owner.track("original_alias", memoryview(raw))
        if observer:
            observer(raw, receipt)

    def finmind_oracle(raw, receipt):
        # Independent stdlib parse of the ENTIRE original: every returned row, all columns.
        text = owner.track("oracle_json_text", raw.decode("utf-8"))
        document = owner.track("oracle_json_document", json.loads(text, parse_float=Decimal, parse_int=Decimal))
        rows = owner.track("oracle_json_rows", [])
        for original in document["data"]:
            rows.append({key: (value if key in ("date", "stock_id") or key in UNADOPTED_TEST_KEYS else Decimal(value))
                         for key, value in original.items()})
        return finmind(raw, receipt, rows) if finmind else rows

    return M.OracleHooks(observe, finmind_oracle, owner)


# ---- real http.client replay (the audit guard bans real sockets) --------------------------------

class ReplayFile(io.BytesIO):
    """Response file whose .raw._sock mirrors socket.SocketIO as in the stdlib path."""


class ReplaySocket:
    def __init__(self, wire):
        self.wire = wire
        self.timeouts = []

    def makefile(self, mode="rb", *args, **kwargs):
        stream = ReplayFile(self.wire)
        stream.raw = types.SimpleNamespace(_sock=self)
        return stream

    def settimeout(self, value):
        self.timeouts.append(value)


class ReplayTransport:
    """Runs the REAL M.HTTPSOneShot.open over canned wire bytes parsed by the real http.client."""

    def __init__(self, wires):
        self.wires = list(wires)
        self.opened = []
        self.requests = []

    def open(self, url, timeout):
        wire = self.wires[len(self.opened)]
        self.opened.append(url)
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
                if response.will_close:  # stdlib hands the socket to the response
                    self.sock = None
                return response

            def close(self):
                self.sock = None

        with patch.object(M.http.client, "HTTPSConnection", Connection), \
                patch.object(M.ssl, "create_default_context", lambda: object()):
            return M.HTTPSOneShot().open(url, timeout)


def chunk_encode(body, size=61):
    out = b""
    for offset in range(0, len(body), size):
        part = body[offset:offset + size]
        out += b"%x\r\n" % len(part) + part + b"\r\n"
    return out + b"0\r\n\r\n"


def raw_http(headers, body=b"", *, status=200, reason="OK", version="1.1"):
    head = f"HTTP/{version} {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers) + "\r\n"
    return head.encode("utf-8") + body


def finmind_wire(body, *, framing="length", content_type="application/json", extra=(), status=200,
                 reason="OK", version="1.1", content_encoding=None, te="chunked"):
    headers = [("Date", "Mon, 12 Oct 2026 00:00:00 GMT"), ("Server", "synthetic"), ("CF-RAY", "synthetic-0000"),
               ("Vary", "Accept-Encoding"), ("Alt-Svc", 'h3=":443"')]
    if content_type is not None:
        headers.append(("Content-Type", content_type))
    wire = body
    if framing == "length":
        headers.append(("Content-Length", str(len(body))))
    elif framing == "chunked":
        headers.append(("Transfer-Encoding", te))
        wire = chunk_encode(body)
    elif framing == "both":
        headers += [("Content-Length", str(len(body))), ("Transfer-Encoding", "chunked")]
        wire = chunk_encode(body)
    elif framing == "close":
        pass  # EOF-delimited
    if content_encoding is not None:
        headers.append(("Content-Encoding", content_encoding))
    return raw_http(headers + list(extra), wire, status=status, reason=reason, version=version)


class Boundaries(unittest.TestCase):
    def build(self, *, body=None, options=None, transport=None, hooks_options=None, use=USE_LITERAL,
              consumer=CONSUMER_LITERAL, seal_mutate=None, clock=None, ledger=None, formal=FORMAL):
        p, clock = policy(), clock or Clock()
        seal, binding = seal_for(p, seal_mutate)
        owner = M.RootOwner("qa_boundary")
        if transport is None:
            transport = Transport(owner, DEFAULT_BODY if body is None else body, options or {}, clock)
        hooks = independent_hooks(owner, **(hooks_options or {}))
        source = M.TaiexNominalSource(p, seal, hooks, binding=binding, formal_blob=formal, supported_use=use,
                                      consumer=consumer, boundary_only=True, transport=transport,
                                      ledger=ledger or M.AttemptLedger(), monotonic=clock.monotonic, utc_now=clock.utc)
        return source, owner, transport, clock

    def assertFailure(self, code, function, *args, **kwargs):
        with self.assertRaises(M.TaiexSourceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        M.clear_error_graph(caught.exception)

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
        self.assertEqual(report["state"], "failed")
        self.assertEqual(report["first_product_failure"]["code"], code)
        return report

    def rejects(self, body, code, **options):
        source, owner, transport, clock = self.build(body=body, **options)
        report = self.expect_failure(source, code, 1)
        self.assertEqual(transport.opened, [URL_LITERAL])
        return report

    # ---- AC-4: external policy, pins, qa1/old policy -------------------------------------------

    def test_policy_literal_pins_and_independent_constants(self):
        self.assertEqual((len(POLICY), hashlib.sha256(POLICY).hexdigest()), (5038, POLICY_SHA256_LITERAL))
        self.assertEqual((M.POLICY_BYTES, M.POLICY_SHA256), (5038, POLICY_SHA256_LITERAL))
        self.assertFalse(POLICY.endswith(b"\n"))
        self.assertTrue(all(byte < 128 for byte in POLICY))
        document = json.loads(POLICY)
        self.assertEqual(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(), POLICY)
        self.assertEqual((M.URL, M.URLS, M.NAMESPACE, M.CONSUMER, M.SUPPORTED_USE, M.CUTOFFS),
                         (URL_LITERAL, (URL_LITERAL,), NAMESPACE_LITERAL, CONSUMER_LITERAL, USE_LITERAL, CUTOFFS_LITERAL))
        self.assertEqual(M.CAPS, CAPS_LITERAL)
        self.assertEqual(M.REQUEST_HEADERS, FINMIND_REQUEST_HEADERS)
        self.assertEqual(M.WINDOWS, WINDOWS_LITERAL)
        self.assertEqual(M.OBSERVED_DATES, DATES)
        self.assertTrue(M.NAMESPACE.endswith("/qa2"))
        acquisition, source = document["acquisition"], document["price_source"]
        self.assertEqual({key: acquisition[key] for key in CAPS_LITERAL}, CAPS_LITERAL)
        self.assertEqual((acquisition["namespace"], acquisition["user_agent"], acquisition["accept"], acquisition["accept_encoding"]),
                         (NAMESPACE_LITERAL, "stock-lab-issue33-local-ram/1", "application/json", "identity"))
        self.assertEqual((source["url"], source["rights"], source["data_id"], source["dataset"]),
                         (URL_LITERAL, RIGHTS_LITERAL, "TAIEX", "TaiwanStockPrice"))
        self.assertEqual(source["query_order"], ["dataset", "data_id", "start_date", "end_date"])
        self.assertEqual((document["source_use"], document["consumer_version"], document["cutoffs"]),
                         (USE_LITERAL, CONSUMER_LITERAL, list(CUTOFFS_LITERAL)))
        self.assertEqual((document["unit_policy"]["scale"], document["unit_policy"]["provider_literal_unit_annotation"]), (1, False))
        self.assertEqual((document["publication_time"], document["first_availability"], document["revision_time"]),
                         ("unknown", "unknown", "unknown"))
        self.assertEqual(len(document["unsupported"]), 19)
        # The 22 dates and both windows are NOT policy values (no expected built from the tested policy).
        self.assertNotIn(b"2026-09-04", POLICY)
        self.assertNotIn(b"2026-09-24", POLICY)
        self.assertEqual(policy().sha256, POLICY_SHA256_LITERAL)

    def tampered(self, mutate, code, *, dump=None):
        document = json.loads(POLICY)
        mutate(document)
        raw = (dump or (lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))(document).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        with patch.object(M, "POLICY_SHA256", digest), patch.object(M, "POLICY_BYTES", len(raw)):
            self.assertFailure(code, M.ExternalPolicy.from_external, raw, digest, POLICY_PIN)

    def test_policy_external_pin_and_every_binding_rejected(self):
        for raw, digest, pin in ((POLICY + b"\n", POLICY_SHA256_LITERAL, POLICY_PIN),
                                 (POLICY[:-1], POLICY_SHA256_LITERAL, POLICY_PIN),
                                 (POLICY.replace(b"qa2", b"qa1"), POLICY_SHA256_LITERAL, POLICY_PIN),
                                 (POLICY, "0" * 64, POLICY_PIN),
                                 (POLICY, POLICY_SHA256_LITERAL.upper(), POLICY_PIN),
                                 (POLICY, POLICY_SHA256_LITERAL, "https://github.com/YiCheng0608/stock-lab/issues/33"),
                                 (POLICY, POLICY_SHA256_LITERAL, "http://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-1"),
                                 (POLICY, POLICY_SHA256_LITERAL, "https://github.com/other/stock-lab/issues/33#issuecomment-1"),
                                 (POLICY, POLICY_SHA256_LITERAL, None),
                                 (POLICY.decode(), POLICY_SHA256_LITERAL, POLICY_PIN),
                                 (bytearray(POLICY), POLICY_SHA256_LITERAL, POLICY_PIN)):
            self.assertFailure("external_policy_pin", M.ExternalPolicy.from_external, raw, digest, pin)
        bindings = [
            (lambda d: d["acquisition"].update(namespace=QA1_NAMESPACE), "policy_binding"),
            (lambda d: d.update(version="ordinary-taiex-nominal-observed-window-v1"), "policy_binding"),
            (lambda d: d.update(source_use="strategy"), "policy_binding"),
            (lambda d: d.update(consumer_version="other-consumer"), "policy_binding"),
            (lambda d: d.update(symbol="^TWII"), "policy_binding"),
            (lambda d: d["price_source"].update(url=URL_LITERAL.replace("TAIEX", "%5ETWII")), "policy_query_binding"),
            (lambda d: d["price_source"].update(data_id="^TWII"), "policy_query_binding"),
            (lambda d: d["price_source"].update(dataset="TaiwanStockPriceAdj"), "policy_query_binding"),
            (lambda d: d["price_source"].update(start_date="2026-09-02"), "policy_query_binding"),
            (lambda d: d["price_source"].update(endpoint="https://example.org/api/v4/data"), "policy_query_binding"),
            (lambda d: d["price_source"].update(query_order=["data_id", "dataset", "start_date", "end_date"]), "policy_query_binding"),
            (lambda d: d["price_source"].update(required_row_keys=["close", "date", "max", "min", "open", "volume"]), "policy_query_binding"),
            (lambda d: d["price_source"].update(known_unadopted_fields=["Trading_Volume", "Trading_money", "Trading_turnover", "other"]), "policy_query_binding"),
            (lambda d: d["acquisition"].update(body_cap_bytes=2097152), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(total_raw_cap_bytes=2097152), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(max_gets=2), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(request_seconds=30), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(batch_seconds=181), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(retries=1), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(redirects=1), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(artifact_bytes=1), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(retained_roots_estimate_cap_bytes=67108864), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(accept_encoding="gzip"), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(user_agent="other/1"), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(accept="*/*"), "policy_caps_binding"),
            (lambda d: d["acquisition"].update(stop_on_first_failure=False), "policy_caps_binding"),
            (lambda d: d["formal_calendar"].update(sha256="0" * 64), "policy_formal_binding"),
            (lambda d: d["formal_calendar"].update(bytes=268730), "policy_formal_binding"),
            (lambda d: d["formal_calendar"].update(section="31.3"), "policy_formal_binding"),
            (lambda d: d["unit_policy"].update(scale=1000), "policy_unit_binding"),
            (lambda d: d["unit_policy"].update(provider_literal_unit_annotation=True), "policy_unit_binding"),
            (lambda d: d.update(calendar_basis="verified_twse_calendar"), "policy_unit_binding"),
            (lambda d: d.update(price_basis="adjusted"), "policy_unit_binding"),
            (lambda d: d["arithmetic"].update(observation_count=22), "policy_unit_binding"),
            (lambda d: d.update(extra_key=1), "policy_keys"),
            (lambda d: d.pop("storage"), "policy_keys"),
            (lambda d: d["acquisition"].update(extra=1), "policy_keys"),
            (lambda d: d["price_source"]["fields"].update(volume="Trading_Volume"), "policy_keys"),
            (lambda d: d["response_shape"].pop("framing"), "policy_keys"),
            (lambda d: d["unit_policy"].update(scale=True), "policy_type"),
            (lambda d: d["unit_policy"].update(scale=1.0), "policy_type"),
            (lambda d: d["acquisition"].update(stop_on_first_failure=1), "policy_type"),
            (lambda d: d["cutoffs"].__setitem__(0, 20261005), "policy_type"),
            (lambda d: d.update(cutoffs=["2026-10-05", "2026-10-06", "2026-10-07"]), "policy_list"),
            (lambda d: d["unsupported"].pop(), "policy_list"),
        ]
        for mutate, code in bindings:
            self.tampered(mutate, code)
        # Non-canonical re-serializations of the same content.
        self.tampered(lambda d: None, "policy_canonical_mismatch", dump=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))
        self.tampered(lambda d: None, "policy_canonical_mismatch", dump=lambda value: json.dumps(dict(reversed(list(value.items()))), separators=(",", ":")))
        self.tampered(lambda d: None, "policy_canonical_mismatch", dump=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        for raw, code in ((POLICY.replace(b"{", b'{"version":"duplicate",', 1), "duplicate_json_key"),
                          (b"\xff" + POLICY[1:], "external_policy_utf8"),
                          (POLICY.replace(b'"scale":1', b'"scale":NaN'), "json_nonfinite"),
                          (b"[" * 17 + b"]" * 17 + b" " * (len(POLICY) - 34), "json_depth")):
            digest = hashlib.sha256(raw).hexdigest()
            with patch.object(M, "POLICY_SHA256", digest), patch.object(M, "POLICY_BYTES", len(raw)):
                self.assertFailure(code, M.ExternalPolicy.from_external, raw, digest, POLICY_PIN)

    def test_old_policy_and_qa1_are_rejected(self):
        old = zlib.decompress(base64.b64decode("".join(OLD_POLICY_B64Z)))
        self.assertEqual((len(old), hashlib.sha256(old).hexdigest()), (4096, OLD_POLICY_SHA256_LITERAL))
        old_document = json.loads(old)
        self.assertEqual(old_document["namespace"], QA1_NAMESPACE)
        self.assertEqual(len(old_document["urls"]), 2)
        for digest in (OLD_POLICY_SHA256_LITERAL, POLICY_SHA256_LITERAL):
            self.assertFailure("external_policy_pin", M.ExternalPolicy.from_external, old, digest, POLICY_PIN)
        with patch.object(M, "POLICY_SHA256", OLD_POLICY_SHA256_LITERAL), patch.object(M, "POLICY_BYTES", 4096):
            self.assertFailure("policy_keys", M.ExternalPolicy.from_external, old, OLD_POLICY_SHA256_LITERAL, POLICY_PIN)
        # A leftover qa1 seal (qa1 namespace, old policy hash, two URLs) is refused.
        p = policy()
        for mutate in (lambda d: d.update(namespace=QA1_NAMESPACE),
                       lambda d: d.update(policy_sha256=OLD_POLICY_SHA256_LITERAL),
                       lambda d: d.update(urls=old_document["urls"]),
                       lambda d: d.update(namespace=QA1_NAMESPACE, policy_sha256=OLD_POLICY_SHA256_LITERAL, urls=old_document["urls"],
                                          caps=old_document["caps"])):
            self.assertFailure("seal_policy_binding", seal_for, p, mutate)

    def test_seal_rejections_and_comment_floor(self):
        p = policy()
        cases = [
            (lambda d: d["caps"].update(body_cap_bytes=1048577), "seal_policy_binding"),
            (lambda d: d["caps"].update(total_raw_cap_bytes=2097152), "seal_policy_binding"),
            (lambda d: d["caps"].update(max_gets=2), "seal_policy_binding"),
            (lambda d: d.update(qa_session="22222222-2222-2222-2222-222222222222"), "seal_execution_binding"),
            (lambda d: d.update(qa_thread="22222222-2222-2222-2222-222222222222", qa_session="22222222-2222-2222-2222-222222222222"), "seal_execution_binding"),
            (lambda d: d.update(authorized_by="11111111-1111-1111-1111-111111111111"), "seal_independent_top_qa"),
            (lambda d: d.update(parent_thread="44444444-4444-4444-4444-444444444444"), "seal_independent_top_qa"),
            (lambda d: d.update(financial_start=1), "seal_policy_binding"),
            (lambda d: d.update(extra="unknown"), "seal_full_keys"),
            (lambda d: d.pop("caps"), "seal_full_keys"),
            (lambda d: d.update(urls=[URL_LITERAL, URL_LITERAL]), "seal_policy_binding"),
            (lambda d: d.update(cutoffs=["2026-10-06", "2026-10-05"]), "seal_policy_binding"),
            (lambda d: d.update(consumer="other"), "seal_policy_binding"),
            (lambda d: d.update(supported_use="hot_group_v1"), "seal_policy_binding"),
            (lambda d: d.update(namespace=QA1_NAMESPACE), "seal_policy_binding"),
            (lambda d: d.update(policy_pin=POLICY_PIN + "0"), "seal_policy_binding"),
            (lambda d: d.update(expires_at_utc="2026-10-10T00:58:00Z"), "seal_validity_order"),
            (lambda d: d.update(issued_at_utc="2026-10-10 01:00"), "seal_utc_grammar"),
            (lambda d: d.update(command=["python", "other"]), "seal_execution_binding"),
            (lambda d: d.update(candidate_sha="g" * 40), "seal_execution_binding"),
        ]
        for mutate, code in cases:
            self.assertFailure(code, seal_for, p, mutate)
        for pin, code in (("https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-9999999999", "external_seal_pin"),
                          ("https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-x", "external_seal_pin"),
                          ("https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-6123688628", "financial_new_explicit_seal_required"),
                          ("https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-6085684135", "financial_new_explicit_seal_required"),
                          (None, "external_seal_pin")):
            self.assertFailure(code, seal_for, p, None, pin)
        seal, _ = seal_for(p, None, "https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-6123688629")
        self.assertEqual(seal.pin.rsplit("-", 1)[1], "6123688629")

    def test_unsupported_preget(self):
        uses = json.loads(POLICY)["unsupported"] + ["strategy", "hot_group_v1", "", "benchmark20d_ready"]
        for use in uses:
            source, owner, transport, clock = self.build(use=use)
            report = self.expect_failure(source, "unsupported_use_preget", 0)
            self.assertEqual(transport.opened, [])
            self.assertFalse(report["namespace_spent"])
        source, owner, transport, clock = self.build(consumer="other-consumer")
        self.expect_failure(source, "unsupported_use_preget", 0)
        self.assertEqual(transport.opened, [])

    def test_seal_validity_window_before_any_get(self):
        for now, code in ((datetime(2026, 10, 10, 1, 5, tzinfo=timezone.utc), "lease_expired"),
                          (datetime(2026, 10, 10, 0, 58, tzinfo=timezone.utc), "seal_not_yet_valid")):
            clock = Clock()
            clock.now = now
            source, owner, transport, clock = self.build(clock=clock)
            self.expect_failure(source, code, 0)
            self.assertEqual(transport.opened, [])

    # ---- AC-2: formal blob, 22 dates, windows ---------------------------------------------------

    def test_formal_blob_derives_the_ac3_sets_independently(self):
        self.assertEqual((len(FORMAL), hashlib.sha256(FORMAL).hexdigest()),
                         (268729, "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"))
        observed, windows = M.formal_observed_dates(FORMAL)
        self.assertEqual((observed, windows), (DATES, WINDOWS_LITERAL))
        # Independent line scan of section 31.2 (no product helper).
        lines = [line for line in FORMAL.decode("utf-8").splitlines() if line.startswith(("- Sep20：", "- Oct4："))]
        self.assertEqual(len(lines), 2)
        september = ["2026-09-%02d" % int(part) for part in lines[0].split("/", 1)[1].rstrip("。").split("、")]
        october = ["2026-10-%02d" % int(part) for part in lines[1].split("/", 1)[1].rstrip("。").split("、")]
        self.assertEqual((len(september), len(october)), (20, 4))
        self.assertEqual(tuple(day for day in september + october if day >= "2026-09-03"), DATES)
        self.assertIn("2026-09-24", DATES)
        self.assertNotIn("2026-09-25", DATES)
        self.assertNotIn("2026-09-28", DATES)

    def test_formal_blob_pin_rejects_before_any_get(self):
        flipped = FORMAL[:100] + bytes([FORMAL[100] ^ 1]) + FORMAL[101:]
        for label, blob in (("appended", FORMAL + b" "), ("truncated", FORMAL[:-1]), ("flipped", flipped), ("empty", b"")):
            with self.subTest(blob=label):
                source, owner, transport, clock = self.build(formal=blob)
                report = self.expect_failure(source, "formal_blob_pin", 0)
                self.assertEqual(transport.opened, [])
                self.assertFalse(report["namespace_spent"])
        for bad in ("text", None, bytearray(FORMAL)):
            with self.subTest(constructor=repr(type(bad))):
                self.assertFailure("formal_blob_type", self.build, formal=bad)

    def test_formal_calendar_derivation_failures(self):
        text = FORMAL.decode("utf-8")
        sep = "- Sep20：9/1、2、3、4、7、8、9、10、11、14、15、16、17、18、21、22、23、24、29、30。"
        self.assertIn(sep, text)
        cases = [
            (sep, "- SepX：9/1。", "formal_calendar_evidence"),
            (sep, sep.replace("、30。", "、31。"), "formal_calendar_evidence"),
            (sep, sep.replace("1、2、3", "1、x、3"), "formal_calendar_evidence"),
            (sep, sep.replace("2、3、", "2、"), "formal_calendar_count"),
            (sep, sep.replace("29、30", "26、30"), "formal_calendar_order"),
            (sep, sep.replace("23、24", "24、23"), "formal_calendar_order"),
            (sep, sep.replace("23、24", "23、23"), "formal_calendar_order"),
            (sep, sep.replace("、24、", "、25、"), "formal_calendar_mismatch"),
            ("- Oct4：10/1、2、5、6。", "- Oct4：10/1、2、5、7。", "formal_calendar_mismatch"),
            ("### 31.2", "### 31.9", "formal_section"),
        ]
        for old, new, code in cases:
            with self.subTest(code=code, new=new[:20]):
                blob = text.replace(old, new, 1).encode("utf-8")
                self.assertNotEqual(blob, FORMAL)
                with patch.object(M, "FORMAL_BYTES", len(blob)), patch.object(M, "FORMAL_SHA256", hashlib.sha256(blob).hexdigest()):
                    self.assertFailure(code, M.formal_observed_dates, blob)
        blob = b"\xff" + FORMAL[1:]
        with patch.object(M, "FORMAL_SHA256", hashlib.sha256(blob).hexdigest()):
            self.assertFailure("formal_blob_utf8", M.formal_observed_dates, blob)

    # ---- positive path: AC-1 body, AC-2 values, AC-3 consumers ---------------------------------

    def test_single_get_both_windows_exact_values_and_release(self):
        source, owner, transport, clock = self.build()
        handles = []
        with source:
            for cutoff, window in (("2026-10-05", WINDOW_1005), ("2026-10-06", WINDOW_1006)):
                getter = source.get_taiex_nominal21(cutoff)

                def check_series(payload, cutoff=cutoff, window=window):
                    self.assertEqual(payload["cutoff"], cutoff)
                    self.assertEqual(payload["observations"], [{"date": day, "close": CLOSES[day]} for day in window])
                    for observation in payload["observations"]:
                        self.assertIs(type(observation["close"]), Decimal)
                    self.assertEqual((payload["first_date"], payload["last_date"]), (window[0], window[-1]))
                    self.assertEqual((payload["observation_count"], payload["interval_count"]), (21, 20))
                    self.assertEqual(payload["calendar_basis"], "cross_market_candidate_inference")
                    self.assertEqual(payload["price_basis"], "nominal_index_level")
                    self.assertIs(payload["benchmark20d_ready"], False)
                    provenance = payload["provenance"]
                    self.assertIs(provenance["provider_literal_unit_annotation"], False)
                    self.assertIs(provenance["independent_unit_anchor"], False)
                    self.assertEqual((provenance["unit"], provenance["scale"]), ("index_points", 1))
                    self.assertIn("internal consistency", provenance["unit_limitation"])
                    self.assertEqual(provenance["rights"], RIGHTS_LITERAL)
                    self.assertEqual(len(provenance["sources"]), 1)
                    self.assertIn("FinMind", provenance["sources"][0])
                    self.assertNotIn("TWSE", json.dumps(provenance["sources"]))
                    self.assertNotIn("OGL", json.dumps(provenance["sources"]))
                    self.assertEqual((provenance["publication_time"], provenance["first_availability"], provenance["revision_time"]),
                                     ("unknown", "unknown", "unknown"))
                    self.assertEqual(provenance["unsupported"], json.loads(POLICY)["unsupported"])
                    self.assertIs(provenance["verified_twse_calendar"], False)
                    self.assertIs(provenance["adjusted_basis"], False)
                    self.assertEqual(provenance["namespace"], NAMESPACE_LITERAL)
                    self.assertEqual(provenance["policy_sha256"], POLICY_SHA256_LITERAL)
                    self.assertEqual(provenance["formal_calendar"]["blob"], FORMAL_OBJECT)
                    receipt = provenance["capture_receipts"][0]
                    self.assertEqual((receipt["url"], receipt["status"], receipt["body_bytes"], receipt["eof"]),
                                     (URL_LITERAL, 200, len(DEFAULT_BODY), True))
                    self.assertEqual(receipt["sha256"], hashlib.sha256(DEFAULT_BODY).hexdigest())
                    owner.track("series_alias_" + cutoff, payload)
                getter.visit(check_series, owner)
                summary = source.summarize(cutoff)

                def check_summary(payload, cutoff=cutoff, window=window):
                    first, last = Fraction(str(CLOSES[window[0]])), Fraction(str(CLOSES[window[-1]]))
                    expected = (last - first) / first  # exact: no Decimal context rounding
                    self.assertIs(type(payload["return"]), Fraction)
                    self.assertEqual(payload["return"], expected)
                    self.assertEqual((payload["return_numerator"], payload["return_denominator"]), (expected.numerator, expected.denominator))
                    self.assertGreater(payload["return_denominator"], 0)
                    self.assertEqual(gcd(payload["return_numerator"], payload["return_denominator"]), 1)
                    self.assertEqual(payload["formula"], "(C_end-C_start)/C_start")
                    self.assertEqual((payload["first_date"], payload["last_date"]), (window[0], window[-1]))
                    self.assertEqual((payload["observation_count"], payload["interval_count"]), (21, 20))
                    self.assertEqual(payload["consumer"], CONSUMER_LITERAL)
                    self.assertIs(payload["benchmark20d_ready"], False)
                    self.assertEqual((payload["calendar_basis"], payload["price_basis"]), ("cross_market_candidate_inference", "nominal_index_level"))
                    owner.track("summary_alias_" + cutoff, payload)
                summary.visit(check_summary, owner)
                handles.extend((getter, summary))
            self.assertEqual(transport.opened, [URL_LITERAL])
            self.assertEqual(source.ledger.attempted_urls, [URL_LITERAL])
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
        self.assertEqual(report["attempted_urls"], [URL_LITERAL])
        self.assertGreater(report["declared_roots_estimate_high_water"], 0)
        self.assertLess(report["measurement_calls"], 32)
        print(json.dumps({"synthetic_positive_getters": 2, "synthetic_positive_consumers": 2,
                          "declared_roots_estimate_high_water": report["declared_roots_estimate_high_water"],
                          "measurement_calls": report["measurement_calls"], "declared_roots_empty": True, "artifact_bytes": 0,
                          "evidence": "engineering synthetic boundary only, not real source QA"}), flush=True)

    def test_values_are_exact_decimals_scale1_and_flat_rows_accepted(self):
        rows = default_rows()
        rows[0] = row_text("2026-09-03", "22345.678901234", open_=Decimal("22345.678901234"), high=Decimal("22345.678901234"),
                           low=Decimal("22345.678901234"))
        rows[20] = row_text("2026-10-05", "22999.5")
        source, owner, transport, clock = self.build(body=body_with(rows))
        with source:
            def check(payload):
                self.assertEqual(payload["observations"][0]["close"], Decimal("22345.678901234"))
                self.assertEqual(str(payload["observations"][0]["close"]), "22345.678901234")
                self.assertEqual(payload["observations"][-1]["close"], Decimal("22999.5"))
                self.assertNotEqual(payload["observations"][0]["close"], Decimal("22345678.901234"))
                owner.track("alias", payload)
            source.get_taiex_nominal21("2026-10-05").visit(check, owner)

            def check_ratio(payload):
                self.assertEqual(payload["return"], (Fraction(Decimal("22999.5")) - Fraction(Decimal("22345.678901234"))) / Fraction(Decimal("22345.678901234")))
                owner.track("ratio_alias", payload)
            source.summarize("2026-10-05").visit(check_ratio, owner)

    def test_out_of_range_rows_validated_then_discarded(self):
        rows = [row_text("2026-08-31", "0", open_=0, high=0, low=0), row_text("2026-09-02", "19000.5")] + default_rows() + [row_text("2026-10-07", "21000.25"), row_text("2026-12-31", "21500.75")]
        source, owner, transport, clock = self.build(body=body_with(rows))
        with source:
            def check(payload):
                self.assertEqual([item["date"] for item in payload["observations"]], list(WINDOW_1006))
                self.assertEqual(payload["observations"][0]["close"], CLOSES["2026-09-04"])
                owner.track("alias", payload)
            source.get_taiex_nominal21("2026-10-06").visit(check, owner)
            self.assertNotIn("2026-10-07", source.product.roots["closes"])
            self.assertNotIn("2026-09-02", source.product.roots["closes"])
            self.assertEqual(len(source.product.roots["finmind_rows"]), 26)
        # The oracle must cover every returned row, not only the 22 kept rows.
        source, owner, transport, clock = self.build(body=body_with(rows), hooks_options={"finmind": lambda raw, receipt, full: full[2:24]})
        self.expect_failure(source, "finmind_full_oracle_mismatch", 1)

    def test_out_of_range_rows_still_need_valid_structure_and_order(self):
        outside = [
            (row_text("2026-09-02", "19000.5").replace('"stock_id":"TAIEX"', '"stock_id":"^TWII"'), "finmind_stock_id"),
            (row_text("2026-09-02", "19000.5").replace('"spread":1.5', '"spread":1.5,"extra":0'), "finmind_row_keys"),
            (row_text("2026-09-02", "19000.5").replace('"close":19000.5', '"close":null'), "finmind_numeric_type"),
            (row_text("2026-09-02", "19000.5").replace('"spread":1.5', '"spread":true'), "finmind_unadopted_type"),
            (row_text("2026-09-02", "19000.5").replace('"close":19000.5,', ""), "finmind_row_keys"),
            (row_text("2026-09-02", "19000.5").replace("2026-09-02", "2026-9-2"), "finmind_date_grammar"),
        ]
        for text, code in outside:
            with self.subTest(code=code):
                self.rejects(body_with([text] + default_rows()), code)
        # A late out-of-range row that breaks ascending order is a structural failure too.
        self.rejects(body_with(default_rows() + [row_text("2026-10-06", "20500.5")]), "finmind_date_order")
        self.rejects(body_with(default_rows() + [row_text("2026-10-01", "20500.5")]), "finmind_date_order")

    def test_document_and_status_gates(self):
        good = document_text(default_rows())
        variants = [
            (good[:-1] + ',"extra":1}', "finmind_document_schema"),
            ("[" + good + "]", "finmind_document_schema"),
            (document_text(default_rows(), status="201"), "finmind_status_msg"),
            (document_text(default_rows(), status='"200"'), "finmind_status_msg"),
            (document_text(default_rows(), status="true"), "finmind_status_msg"),
            (document_text(default_rows(), msg='"Success"'), "finmind_status_msg"),
            (document_text(default_rows(), msg="null"), "finmind_status_msg"),
            (good.replace('"data":[', '"data":null,"x":['), "finmind_document_schema"),
            ('{"msg":"success","status":200,"data":null}', "finmind_rows"),
            ('{"msg":"success","status":200,"data":{}}', "finmind_rows"),
            ('{"msg":"success","status":200,"data":[]}', "finmind_rows"),
            ('{"msg":"Your level is register. Please update your user level.","status":402}', "finmind_document_schema"),
            ('{"msg":"login required","status":401,"data":[]}', "finmind_status_msg"),
            ('{"msg":"success","status":200,"status":200,"data":[]}', "duplicate_json_key"),
            (good.replace('"stock_id":"TAIEX"', '"stock_id":"TAIEX","stock_id":"TAIEX"', 1), "duplicate_json_key"),
            (good.replace('"close":20000.25', '"close":NaN', 1), "json_nonfinite"),
            (good.replace('"close":20000.25', '"close":Infinity', 1), "json_nonfinite"),
            (good.replace('"close":20000.25', '"close":-Infinity', 1), "json_nonfinite"),
            (good.replace('"close":20000.25', '"close":1e1000000', 1), "numeric_range"),
            (good.replace('"Trading_money":98765432100', '"Trading_money":10000000000000000000', 1), "integer_range"),
            (good.replace('"Trading_money":98765432100', '"Trading_money":1' + "0" * 70, 1), "integer_lexical_limit"),
            (good.replace('"close":20000.25', '"close":1.' + "1" * 70, 1), "numeric_lexical_limit"),
            ("[" * 17 + "]" * 17, "json_depth"),
            (good + " trailing", "json_invalid"),
            ("", None),
        ]
        for text, code in variants:
            if code is None:
                continue
            with self.subTest(code=code, text=text[:40]):
                self.rejects(text.encode("utf-8"), code)

    def test_every_returned_row_structure(self):
        base = default_rows()
        first = base[0]
        variants = [
            (first.replace('"close":20000.25,', ""), "finmind_row_keys"),
            (first.replace('"open":19999.25,', ""), "finmind_row_keys"),
            (first.replace('"stock_id":"TAIEX",', ""), "finmind_row_keys"),
            (first.replace('"spread":1.5', '"spread":1.5,"adj_close":1'), "finmind_row_keys"),
            (first.replace('"spread":1.5', '"spread":1.5,"Volume":1'), "finmind_row_keys"),
            ("123", "finmind_row_keys"),
            ("[]", "finmind_row_keys"),
            (first.replace('"TAIEX"', '"^TWII"'), "finmind_stock_id"),
            (first.replace('"TAIEX"', '"taiex"'), "finmind_stock_id"),
            (first.replace('"TAIEX"', '"TAIEX "'), "finmind_stock_id"),
            (first.replace('"TAIEX"', "1"), "finmind_stock_id"),
            (first.replace('"TAIEX"', "null"), "finmind_stock_id"),
            (first.replace("2026-09-03", "20260903"), "finmind_date_grammar"),
            (first.replace("2026-09-03", "2026-9-3"), "finmind_date_grammar"),
            (first.replace("2026-09-03", "2026-09-03 "), "finmind_date_grammar"),
            (first.replace("2026-09-03", "2026-09-03T00:00:00"), "finmind_date_grammar"),
            (first.replace('"2026-09-03"', "20260903"), "finmind_date_grammar"),
            (first.replace('"2026-09-03"', "null"), "finmind_date_grammar"),
            (first.replace("2026-09-03", "2026-02-30"), "finmind_invalid_date"),
            (first.replace("2026-09-03", "2026-13-01"), "finmind_invalid_date"),
            (first.replace('"close":20000.25', '"close":"20000.25"'), "finmind_numeric_type"),
            (first.replace('"close":20000.25', '"close":true'), "finmind_numeric_type"),
            (first.replace('"close":20000.25', '"close":null'), "finmind_numeric_type"),
            (first.replace('"close":20000.25', '"close":[1]'), "finmind_numeric_type"),
            (first.replace('"open":19999.25', '"open":"19999.25"'), "finmind_numeric_type"),
            (first.replace('"max":20002.75', '"max":null'), "finmind_numeric_type"),
            (first.replace('"min":19996.75', '"min":false'), "finmind_numeric_type"),
            (first.replace('"Trading_turnover":4567', '"Trading_turnover":true'), "finmind_unadopted_type"),
            (first.replace('"Trading_money":98765432100', '"Trading_money":{}'), "finmind_unadopted_type"),
        ]
        for text, code in variants:
            with self.subTest(code=code, row=text[:50]):
                self.rejects(body_with([text] + base[1:]), code)
        # Order: duplicate and descending dates over ALL returned rows.
        self.rejects(body_with([base[0], base[0]] + base[1:]), "finmind_date_order")
        self.rejects(body_with([base[1], base[0]] + base[2:]), "finmind_date_order")
        self.rejects(body_with(list(reversed(base))), "finmind_date_order")
        # Known unadopted columns may be absent (only the six required keys) or negative spread.
        slim = ['{"date":"%s","stock_id":"TAIEX","open":%s,"max":%s,"min":%s,"close":%s}' % (
            day, CLOSES[day] - 1, CLOSES[day] + 2, CLOSES[day] - 2, CLOSES[day]) for day in DATES]
        source, owner, transport, clock = self.build(body=body_with(slim))
        with source:
            self.assertEqual(source.state, "available")
        negative_spread = [row_text(day, CLOSES[day], spread="-3.25") for day in DATES]
        source, owner, transport, clock = self.build(body=body_with(negative_spread))
        with source:
            self.assertEqual(source.state, "available")

    def test_unadopted_columns_accept_number_string_null_and_stay_unused(self):
        marker = "UNADOPTED-MARKER-9f3"
        defaults = {"Trading_Volume": "123456789", "Trading_money": "98765432100", "spread": "1.5", "Trading_turnover": "4567"}

        def with_fields(text, **values):
            for field, raw in values.items():
                old = '"%s":%s' % (field, defaults[field])
                self.assertIn(old, text)
                text = text.replace(old, '"%s":%s' % (field, raw))
            return text
        rows = []
        for index, day in enumerate(DATES):
            text = row_text(day, CLOSES[day])
            if index % 4 == 0:
                text = with_fields(text, Trading_Volume='"%s"' % marker, spread="null")
            elif index % 4 == 1:
                text = with_fields(text, Trading_money="null", Trading_turnover='"4,567"')
            elif index % 4 == 2:
                text = with_fields(text, spread='"+1.5"', Trading_Volume="-1")
            else:  # numbers with no range or sign meaning for any unadopted column
                text = with_fields(text, Trading_Volume="0", Trading_money="-5.5", spread="-3.25", Trading_turnover="0.5")
            rows.append(text)
        outside = [with_fields(row_text("2026-09-02", "19000.5"), spread="null", Trading_money='"n/a"')]
        body = body_with(outside + rows + [with_fields(row_text("2026-10-07", "21000.25"), Trading_turnover='""')])
        source, owner, transport, clock = self.build(body=body)
        with source:
            kept = source.product.roots["finmind_rows"]
            self.assertEqual(len(kept), 24)
            self.assertEqual((kept[1]["Trading_Volume"], kept[1]["spread"]), (marker, None))
            self.assertEqual((kept[2]["Trading_money"], kept[2]["Trading_turnover"]), (None, "4,567"))
            self.assertEqual((kept[3]["spread"], kept[3]["Trading_Volume"]), ("+1.5", Decimal(-1)))
            self.assertEqual((kept[4]["Trading_money"], kept[4]["spread"]), (Decimal("-5.5"), Decimal("-3.25")))
            for cutoff in CUTOFFS_LITERAL:
                def check(payload, cutoff=cutoff):
                    dump = json.dumps(payload, default=str)
                    self.assertNotIn(marker, dump)  # never exported
                    self.assertNotIn("Trading_", dump)
                    self.assertNotIn("4,567", dump)
                    self.assertEqual([item["date"] for item in payload["observations"]], list(WINDOWS_LITERAL[cutoff]))
                    owner.track("alias_" + cutoff, payload)
                source.get_taiex_nominal21(cutoff).visit(check, owner)

                def check_ratio(payload, cutoff=cutoff):
                    window = WINDOWS_LITERAL[cutoff]
                    first, last = Fraction(str(CLOSES[window[0]])), Fraction(str(CLOSES[window[-1]]))
                    self.assertEqual(payload["return"], (last - first) / first)  # unadopted columns never enter arithmetic
                    owner.track("ratio_alias_" + cutoff, payload)
                source.summarize(cutoff).visit(check_ratio, owner)
        # The independent oracle must reproduce the unadopted columns exactly as parsed.
        for label, hook in (
                ("string_to_decimal", lambda raw, receipt, full: [dict(row, Trading_Volume=Decimal(1)) if row.get("Trading_Volume") == marker else row for row in full]),
                ("null_to_string", lambda raw, receipt, full: [dict(row, spread="None") if row.get("spread") is None else row for row in full]),
                ("column_dropped", lambda raw, receipt, full: [{k: v for k, v in row.items() if k != "Trading_money"} if row.get("Trading_money") is None and "Trading_money" in row else row for row in full])):
            with self.subTest(oracle=label):
                source, owner, transport, clock = self.build(body=body, hooks_options={"finmind": hook})
                self.expect_failure(source, "finmind_full_oracle_mismatch", 1)
        # bool, list and object are refused in every unadopted column, in-range and out-of-range.
        base = default_rows()
        for field in defaults:
            for bad in ("true", "false", "[1]", "[]", "{}", '{"a":1}'):
                with self.subTest(field=field, bad=bad):
                    self.rejects(body_with([with_fields(base[0], **{field: bad})] + base[1:]), "finmind_unadopted_type")
                    self.rejects(body_with(base[:-1] + [with_fields(base[-1], **{field: bad})]), "finmind_unadopted_type")
                    self.rejects(body_with([with_fields(row_text("2026-09-02", "19000.5"), **{field: bad})] + base), "finmind_unadopted_type")
        # Adopted columns still need numbers; document-level gates still cover unadopted values.
        for key, raw in (("open", "19999.25"), ("max", "20002.75"), ("min", "19996.75")):
            for bad in ('"%s"' % raw, "null", "true", "[1]", "{}"):
                with self.subTest(adopted=key, bad=bad):
                    self.rejects(body_with([base[0].replace('"%s":%s' % (key, raw), '"%s":%s' % (key, bad))] + base[1:]), "finmind_numeric_type")
        for raw, code in (("NaN", "json_nonfinite"), ("-Infinity", "json_nonfinite"), ("1e1000000", "numeric_range"),
                          ("1" + "0" * 70, "integer_lexical_limit"), ("10000000000000000000", "integer_range")):
            with self.subTest(document_gate=raw[:20]):
                self.rejects(body_with([with_fields(base[0], spread=raw)] + base[1:]), code)
        self.rejects(body_with([base[0].replace('"spread":1.5', '"spread":1.5,"spread":null')] + base[1:]), "duplicate_json_key")

    def test_ohlc_bounds_positive_and_in_range_gate(self):
        base = default_rows()

        def with_row(index, text):
            rows = list(base)
            rows[index] = text
            return body_with(rows)
        day = DATES[5]
        close = CLOSES[day]
        cases = [
            (row_text(day, close, open_=close - 1, high=close - Decimal("0.25"), low=close - 3), "finmind_ohlc_range"),
            (row_text(day, close, open_=close + 5, high=close + 2, low=close - 3), "finmind_ohlc_range"),
            (row_text(day, close, open_=close - 1, high=close + 2, low=close + Decimal("0.25")), "finmind_ohlc_range"),
            (row_text(day, close, open_=close - 5, high=close + 2, low=close - 3), "finmind_ohlc_range"),
            (row_text(day, close, open_=close - 1, high=close - 1, low=close + 3), "finmind_ohlc_range"),
            (row_text(day, close, open_=close - 1, high=close + 2, low=close - 3).replace('"close":%s' % close, '"close":0'), "finmind_positive_ohlc"),
            (row_text(day, close, open_=Decimal("0"), high=close + 2, low=close - 3), "finmind_positive_ohlc"),
            (row_text(day, close, open_=close - 1, high=Decimal("-5"), low=close - 3), "finmind_positive_ohlc"),
            (row_text(day, close, open_=close - 1, high=close + 2, low=Decimal("0")), "finmind_positive_ohlc"),
            (row_text(day, "-20000.25"), "finmind_positive_ohlc"),
        ]
        for text, code in cases:
            with self.subTest(code=code, row=text[40:110]):
                self.rejects(with_row(5, text), code)
        flat = row_text(day, close, open_=close, high=close, low=close)
        source, owner, transport, clock = self.build(body=with_row(5, flat))
        with source:
            self.assertEqual(source.state, "available")

    def test_calendar_equality_without_inference_or_shrink(self):
        base = default_rows()
        index = {day: i for i, day in enumerate(DATES)}
        drop_0924 = [row for i, row in enumerate(base) if i != index["2026-09-24"]]
        drop_first = base[1:]
        drop_last = base[:-1]
        with_0925 = base[:index["2026-09-29"]] + [row_text("2026-09-25", "20500.5")] + base[index["2026-09-29"]:]
        swap_0925 = list(base)
        swap_0925[index["2026-09-24"]] = row_text("2026-09-25", "20500.5")
        weekend = list(base)
        weekend[index["2026-09-07"]] = row_text("2026-09-05", "20500.5")
        shifted = list(base)
        shifted[index["2026-10-06"]] = row_text("2026-10-07", "20500.5")
        for rows, code in ((drop_0924, "finmind_in_range_count"), (drop_first, "finmind_in_range_count"),
                           (drop_last, "finmind_in_range_count"), (with_0925, "finmind_in_range_count"),
                           (swap_0925, "finmind_calendar_mismatch"), (weekend, "finmind_calendar_mismatch"),
                           (shifted, "finmind_in_range_count"), ([], "finmind_rows")):
            with self.subTest(code=code, rows=len(rows)):
                self.rejects(body_with(rows), code)

    def test_full_oracle_gate_all_columns(self):
        variants = {
            "drop_last": lambda raw, receipt, rows: rows[:-1],
            "empty": lambda raw, receipt, rows: [],
            "close_changed": lambda raw, receipt, rows: [dict(rows[0], close=rows[0]["close"] + 1)] + rows[1:],
            "column_dropped": lambda raw, receipt, rows: rows[:3] + [{k: v for k, v in rows[3].items() if k != "Trading_turnover"}] + rows[4:],
            "column_added": lambda raw, receipt, rows: [dict(rows[0], extra=Decimal(1))] + rows[1:],
            "int_instead_of_decimal": lambda raw, receipt, rows: [dict(rows[0], close=20000)] + rows[1:],
            "float_instead_of_decimal": lambda raw, receipt, rows: [dict(rows[0], close=float(rows[0]["close"]))] + rows[1:],
            "reordered": lambda raw, receipt, rows: list(reversed(rows)),
            "not_a_list": lambda raw, receipt, rows: tuple(rows),
        }
        for label, hook in variants.items():
            with self.subTest(oracle=label):
                source, owner, transport, clock = self.build(hooks_options={"finmind": hook})
                self.expect_failure(source, "finmind_full_oracle_mismatch", 1)
        source, owner, transport, clock = self.build(hooks_options={"finmind": lambda raw, receipt, rows: True})
        self.expect_failure(source, "finmind_full_oracle_mismatch", 1)

        def mutate(raw, receipt, rows):
            raw[0] = 0
            return rows
        source, owner, transport, clock = self.build(hooks_options={"finmind": mutate})
        self.expect_failure(source, "finmind_oracle_mutated_raw", 1)

    def test_observer_cannot_mutate_original(self):
        def observer(raw, receipt):
            raw[0] = 0
        source, owner, transport, clock = self.build(hooks_options={"observer": observer})
        self.expect_failure(source, "original_observer_mutated_raw", 1)

    # ---- AC-1 wire: fake-response boundaries -----------------------------------------------------

    def test_exact_cap_known_eof_and_unknown_failclosed(self):
        def pad(body):
            return body + b" " * (1048576 - len(body))
        source, owner, transport, clock = self.build(body=pad(DEFAULT_BODY))
        with source:
            self.assertEqual(source.receipts[0]["body_bytes"], 1048576)
        self.assertEqual(sum(transport.responses[0].read_sizes), 1048576)
        self.assertTrue(all(0 < size <= 65536 for size in transport.responses[0].read_sizes))
        source, owner, transport, clock = self.build(body=pad(DEFAULT_BODY), options={"declared": False, "cap_eof": True})
        with source:
            self.assertEqual(source.receipts[0]["body_bytes"], 1048576)
        for options in ({"declared": False, "cap_eof": False}, {"declared": True, "cap_eof": False}):
            source, owner, transport, clock = self.build(body=pad(DEFAULT_BODY), options=options)
            self.expect_failure(source, "body_cap_without_known_eof", 1)
            self.assertEqual(sum(transport.responses[0].read_sizes), 1048576)
            self.assertTrue(all(0 < size <= 65536 for size in transport.responses[0].read_sizes))

    def test_headers_status_and_declared_cap_before_read(self):
        json_type = ("Content-Type", "application/json")
        cases = [
            ({"status": 401}, "http_auth_or_payment_stop"), ({"status": 402}, "http_auth_or_payment_stop"),
            ({"status": 403}, "http_auth_or_payment_stop"), ({"status": 429}, "http_status_stop"),
            ({"status": 302, "extra": [("Location", "https://other.invalid")]}, "http_status_stop"),
            ({"status": "200"}, "http_status_stop"), ({"status": True}, "http_status_stop"),
            ({"extra": [("Content-Encoding", "gzip")]}, "content_encoding"),
            ({"extra": [("Content-Encoding", "br")]}, "content_encoding"),
            ({"headers": [json_type, ("Content-Length", "1048577")]}, "declared_body_cap"),
            ({"headers": [json_type, ("Content-Length", "01")]}, "content_length"),
            ({"headers": [json_type, ("Content-Length", "1"), ("content-length", "1")]}, "duplicate_identity_header"),
            ({"headers": [json_type, ("content-type", "application/json"), ("Content-Length", "1")]}, "duplicate_identity_header"),
            ({"headers": [("Content-Type", "text/html"), ("Content-Length", "1")]}, "content_type"),
            ({"headers": [("Content-Length", "1")]}, "content_type"),
            ({"headers": [json_type, ("Content-Length", "1"), ("Transfer-Encoding", "chunked")]}, "ambiguous_framing"),
            ({"headers": [json_type, ("Content-Length", 5)]}, "http_header_type"),
            ({"headers": [("X-%d" % n, "v") for n in range(129)]}, "http_headers"),
        ]
        for options, code in cases:
            with self.subTest(code=code, options=str(options)[:60]):
                source, owner, transport, clock = self.build(options=options)
                self.expect_failure(source, code, 1)
                self.assertEqual(transport.responses[0].read_sizes, [])
        # Accepted: set-cookie and non-identity duplicates are ignored, charset allowed.
        source, owner, transport, clock = self.build(options={"extra": [("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"), ("Vary", "x"), ("Vary", "y")],
                                                             "headers": [("Content-Type", "application/json; charset=UTF-8"),
                                                                         ("Content-Length", str(len(DEFAULT_BODY)))]})
        with source:
            self.assertEqual(source.state, "available")
        # Over-delivering transport and declared-length truncation.
        source, owner, transport, clock = self.build(body=DEFAULT_BODY + b" " * 70000, options={"oversize": True, "declared": False})
        self.expect_failure(source, "invalid_transport_read", 1)
        source, owner, transport, clock = self.build(options={"headers": [("Content-Type", "application/json"), ("Content-Length", str(len(DEFAULT_BODY) + 5))]})
        self.expect_failure(source, "incomplete_content_length", 1)

    def test_request_deadline_spent_and_no_retry(self):
        ledger = M.AttemptLedger()
        source, owner, transport, clock = self.build(options={"slow": True}, ledger=ledger)
        self.expect_failure(source, "request_deadline", 1)
        self.assertEqual(ledger.attempted_urls, [URL_LITERAL])
        source, owner, transport, clock = self.build(ledger=ledger)
        report = self.expect_failure(source, "namespace_spent", 1)
        self.assertEqual(transport.opened, [])
        self.assertTrue(report["namespace_spent"])
        # A failed attempt never reopens: 401/402/403 are first failures that spend the single attempt.
        ledger = M.AttemptLedger()
        source, owner, transport, clock = self.build(options={"status": 403}, ledger=ledger)
        self.expect_failure(source, "http_auth_or_payment_stop", 1)
        self.assertEqual(len(transport.opened), 1)
        source, owner, transport, clock = self.build(ledger=ledger)
        self.expect_failure(source, "namespace_spent", 1)
        self.assertEqual(transport.opened, [])
        # A pre-GET refusal does not spend the namespace.
        ledger = M.AttemptLedger()
        source, owner, transport, clock = self.build(use="strategy", ledger=ledger)
        self.expect_failure(source, "unsupported_use_preget", 0)
        self.assertFalse(ledger.spent)

    def test_cumulative_request_budget_single_attempt(self):
        source, owner, transport, clock = self.build(options={"read_seconds": 20})
        report = self.expect_failure(source, "request_deadline", 1)
        self.assertEqual(report["first_product_failure"]["phase"], "request")
        self.assertEqual(report["first_product_failure"]["location"], "TaiexNominalSource._request_remaining")
        self.assertEqual(report["first_product_failure"]["cumulative_request_elapsed_seconds"], 20)
        self.assertTrue(report["namespace_spent"])
        self.assertFalse(any(event["code"] == "available" for event in report["events"]))
        self.assertTrue(all(response.closed for response in transport.responses))
        source, owner, transport, clock = self.build(options={"read_seconds": 19})
        with source:
            self.assertEqual(source.state, "available")
            self.assertEqual(source.request_seconds_used, 19)
            self.assertEqual(source.receipts[0]["request_elapsed_seconds"], 19)
        self.assertEqual(source.diagnostic_report()["cumulative_request_elapsed_seconds"], 19)

    def test_roots_estimate_cap_fails_closed(self):
        def big(raw, receipt):
            owner.track("oversize_alias", bytearray(34 * 1024 * 1024))
        source, owner, transport, clock = self.build(hooks_options={"observer": big})
        self.expect_failure(source, "root_bytes_limit", 1)
        self.assertEqual(owner.roots, {})

    # ---- AC-1 wire: real http.client replay over HTTPSOneShot ---------------------------------

    def replay(self, wire):
        transport = ReplayTransport([wire])
        source, owner, _, clock = self.build(transport=transport)
        return source, transport

    def test_replay_accepts_every_documented_shape(self):
        accepted = (
            ("ct_plain", {}),
            ("ct_charset_utf8", dict(content_type="application/json; charset=utf-8")),
            ("ct_charset_upper_no_space", dict(content_type="application/json;charset=UTF-8")),
            ("ct_mixed_case", dict(content_type="Application/JSON; Charset=UTF-8")),
            ("ct_space_before_semicolon", dict(content_type="application/json ;charset=utf-8")),
            ("framing_content_length", dict(framing="length")),
            ("framing_chunked", dict(framing="chunked")),
            ("framing_chunked_mixed_case_token", dict(framing="chunked", te="Chunked")),
            ("framing_close_delimited_http11", dict(framing="close")),
            ("framing_close_delimited_http10", dict(framing="close", version="1.0")),
            ("encoding_identity", dict(content_encoding="identity")),
            ("encoding_identity_mixed_case", dict(content_encoding="Identity")),
            ("set_cookie_once", dict(extra=[("Set-Cookie", "__cf_bm=synthetic; Path=/; HttpOnly")])),
            ("set_cookie_twice", dict(extra=[("Set-Cookie", "__cf_bm=synthetic; Path=/; HttpOnly"), ("Set-Cookie", "other=1")])),
            ("duplicate_non_identity_headers", dict(extra=[("Vary", "Origin"), ("Vary", "Accept"), ("Cache-Control", "no-store"),
                                                          ("Cache-Control", "no-cache"), ("X-Ratelimit-Remaining", "299"),
                                                          ("X-Ratelimit-Remaining", "298")])),
            ("connection_header_values", dict(extra=[("Connection", "keep-alive")])),
        )
        for label, options in accepted:
            with self.subTest(accepted=label):
                source, transport = self.replay(finmind_wire(DEFAULT_BODY, **options))
                source.acquire()
                self.assertEqual(source.state, "available")
                self.assertEqual(transport.opened, [URL_LITERAL])
                self.assertEqual(source.ledger.attempted_urls, [URL_LITERAL])
                for host, method, target, headers in transport.requests:
                    self.assertEqual((host, method, headers), ("api.finmindtrade.com", "GET", FINMIND_REQUEST_HEADERS))
                    self.assertEqual(target, URL_LITERAL.split("api.finmindtrade.com", 1)[1])
                self.assertFalse(any(key.lower() in ("cookie", "authorization", "proxy-authorization")
                                     for request in transport.requests for key in request[3]))
                self.assertEqual(source.receipts[0]["content_encoding"], "identity")
                self.assertEqual(source.receipts[0]["status"], 200)
                self.assertEqual(source.receipts[0]["sha256"], hashlib.sha256(DEFAULT_BODY).hexdigest())
                source.release()
                self.assertTrue(source.diagnostic_report()["declared_roots_empty"])

    def test_replay_rejects_every_documented_shape_with_first_failure_stop(self):
        header_rejects = []
        for status, reason in ((201, "Created"), (204, "No Content"), (206, "Partial Content"), (304, "Not Modified"),
                               (400, "Bad Request"), (404, "Not Found"), (429, "Too Many Requests"),
                               (500, "Internal Server Error"), (503, "Service Unavailable")):
            header_rejects.append((f"status_{status}", lambda body, s=status, r=reason: finmind_wire(body, status=s, reason=r), "http_status_stop"))
        for status, reason in ((401, "Unauthorized"), (402, "Payment Required"), (403, "Forbidden")):
            header_rejects.append((f"status_{status}", lambda body, s=status, r=reason: finmind_wire(body, status=s, reason=r), "http_auth_or_payment_stop"))
        for status, reason in ((301, "Moved Permanently"), (302, "Found"), (307, "Temporary Redirect"), (308, "Permanent Redirect")):
            header_rejects.append((f"redirect_{status}", lambda body, s=status, r=reason: finmind_wire(
                body, status=s, reason=r, extra=[("Location", "https://example.invalid/next")]), "http_status_stop"))
        for label, content_type in (("missing", None), ("empty", ""), ("text_html", "text/html; charset=utf-8"),
                                    ("application_csv", "application/csv"), ("text_json", "text/json"),
                                    ("x_json", "application/x-json"), ("jsonp", "application/jsonp"),
                                    ("charset_big5", "application/json; charset=big5"),
                                    ("charset_latin1", "application/json; charset=iso-8859-1"),
                                    ("extra_parameter", "application/json; charset=utf-8; boundary=x")):
            header_rejects.append((f"content_type_{label}", lambda body, c=content_type: finmind_wire(body, content_type=c), "content_type"))
        for value in ("gzip", "br", "deflate", "zstd", "gzip, identity", ""):
            header_rejects.append((f"content_encoding_{value or 'empty'}", lambda body, v=value: finmind_wire(body, content_encoding=v), "content_encoding"))
        header_rejects += [
            ("content_length_and_chunked", lambda body: finmind_wire(body, framing="both"), "ambiguous_framing"),
            ("transfer_encoding_gzip_chunked", lambda body: finmind_wire(body, framing="close", extra=[("Transfer-Encoding", "gzip, chunked")]), "ambiguous_framing"),
            ("transfer_encoding_identity", lambda body: finmind_wire(body, framing="close", extra=[("Transfer-Encoding", "identity")]), "ambiguous_framing"),
            ("content_length_leading_zero", lambda body: finmind_wire(body, framing="close", extra=[("Content-Length", "0" + str(len(body)))]), "content_length"),
            ("content_length_plus_sign", lambda body: finmind_wire(body, framing="close", extra=[("Content-Length", "+" + str(len(body)))]), "content_length"),
            ("content_length_17_digits", lambda body: finmind_wire(body, framing="close", extra=[("Content-Length", "1" * 17)]), "content_length"),
            ("content_length_over_body_cap", lambda body: finmind_wire(body, framing="close", extra=[("Content-Length", str(M.BODY_CAP + 1))]), "declared_body_cap"),
            ("duplicate_content_length", lambda body: finmind_wire(body, extra=[("Content-Length", str(len(body)))]), "duplicate_identity_header"),
            ("duplicate_content_length_lower_case", lambda body: finmind_wire(body, extra=[("content-length", str(len(body)))]), "duplicate_identity_header"),
            ("duplicate_content_type", lambda body: finmind_wire(body, extra=[("Content-Type", "application/json")]), "duplicate_identity_header"),
            ("duplicate_content_type_upper_case", lambda body: finmind_wire(body, extra=[("CONTENT-TYPE", "application/json")]), "duplicate_identity_header"),
            ("duplicate_content_encoding", lambda body: finmind_wire(body, content_encoding="identity", extra=[("content-encoding", "identity")]), "duplicate_identity_header"),
            ("duplicate_transfer_encoding", lambda body: finmind_wire(body, framing="chunked", extra=[("Transfer-Encoding", "chunked")]), "duplicate_identity_header"),
        ]
        junk = b"x" * (M.BODY_CAP + 1024)
        body_rejects = [
            ("content_length_longer_than_body", lambda body: raw_http([("Content-Type", "application/json"), ("Content-Length", "999")], b"x" * 10), "incomplete_content_length"),
            ("chunked_truncated", lambda body: raw_http([("Content-Type", "application/json"), ("Transfer-Encoding", "chunked")], chunk_encode(body)[:-5]), "source_failure"),
            ("close_delimited_cap_reached_without_eof", lambda body: finmind_wire(junk, framing="close"), "body_cap_without_known_eof"),
            ("close_delimited_exactly_cap_no_eof_seen", lambda body: finmind_wire(b"x" * M.BODY_CAP, framing="close"), "body_cap_without_known_eof"),
            ("chunked_cap_reached_without_eof", lambda body: finmind_wire(junk, framing="chunked"), "body_cap_without_known_eof"),
            ("empty_body_content_length_zero", lambda body: finmind_wire(b""), "empty_body"),
            ("empty_body_close_delimited", lambda body: finmind_wire(b"", framing="close"), "empty_body"),
            ("utf8_bom", lambda body: finmind_wire(b"\xef\xbb\xbf" + body), "json_invalid"),
            ("invalid_utf8", lambda body: finmind_wire(b"\xff" + body), "finmind_utf8"),
            ("utf16_body", lambda body: finmind_wire(body.decode("utf8").encode("utf-16")), "finmind_utf8"),
            ("html_error_page_with_200", lambda body: finmind_wire(b"<html>blocked</html>"), "json_invalid"),
            ("paid_json_with_200", lambda body: finmind_wire(b'{"msg":"Your level is register. Please update your user level.","status":402}'), "finmind_document_schema"),
            ("login_json_with_200", lambda body: finmind_wire(b'{"msg":"login required","status":401,"data":[]}'), "finmind_status_msg"),
        ]
        for label, build_wire, code in header_rejects + body_rejects:
            with self.subTest(rejected=label):
                source, transport = self.replay(build_wire(DEFAULT_BODY))
                self.expect_failure(source, code, 1)
                self.assertEqual(transport.opened, [URL_LITERAL])  # no redirect follow, no retry, no second GET
                self.assertEqual(source.ledger.attempted_urls, [URL_LITERAL])
                self.assertEqual(source.state, "failed")
                self.assertFailure("lease_failed", source.get_taiex_nominal21, "2026-10-06")

    def test_replay_exact_cap_content_length_is_known_eof(self):
        body = DEFAULT_BODY + b" " * (M.BODY_CAP - len(DEFAULT_BODY))
        for options in (dict(framing="length"), dict(framing="close")):
            with self.subTest(options=options):
                source, transport = self.replay(finmind_wire(body, **options))
                if options["framing"] == "length":
                    source.acquire()
                    self.assertEqual(source.receipts[0]["body_bytes"], M.BODY_CAP)
                    source.release()
                else:
                    self.expect_failure(source, "body_cap_without_known_eof", 1)

    # ---- default stdlib transport with an in-memory HTTPSConnection ---------------------------

    def test_default_https_request_headers_hosts_and_refused_urls(self):
        class Socket:
            def settimeout(self, value):
                pass

        class HTTPBody:
            status = 200
            length = 0
            fp = None
            closed = False

            def getheaders(self):
                return (("Content-Length", "0"),)

            def isclosed(self):
                return self.closed

            def close(self):
                self.closed = True

        connections = []

        class Connection:
            def __init__(self, host, timeout, context):
                self.host, self.timeout, self.context = host, timeout, context
                self.sock, self.body, self.requests = Socket(), HTTPBody(), []
                self.tunnel_used = False
                connections.append(self)

            def connect(self):
                pass

            def set_tunnel(self, *args, **kwargs):
                self.tunnel_used = True

            def request(self, method, target, headers):
                self.requests.append((method, target, headers))

            def getresponse(self):
                return self.body

            def close(self):
                pass

        forbidden = {"cookie", "set-cookie", "authorization", "proxy-authorization", "proxy-connection", "x-api-key", "token"}
        with patch.object(M.http.client, "HTTPSConnection", Connection), patch.object(M.ssl, "create_default_context", lambda: object()):
            M.HTTPSOneShot().open(URL_LITERAL, 20).close()
        connection = connections[-1]
        self.assertEqual(connection.host, "api.finmindtrade.com")
        self.assertFalse(connection.tunnel_used)
        method, target, headers = connection.requests[0]
        self.assertEqual((method, len(connection.requests)), ("GET", 1))
        self.assertEqual(target, "/api/v4/data?dataset=TaiwanStockPrice&data_id=TAIEX&start_date=2026-09-03&end_date=2026-10-06")
        self.assertEqual(headers, FINMIND_REQUEST_HEADERS)
        self.assertTrue(forbidden.isdisjoint(key.lower() for key in headers))
        built = len(connections)
        for bad in ("https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=open_data",
                    URL_LITERAL.replace("TAIEX", "%5ETWII"), URL_LITERAL.replace("TaiwanStockPrice", "TaiwanStockTradingDate"),
                    URL_LITERAL.replace("2026-10-06", "2026-10-07"), URL_LITERAL + "&token=x",
                    URL_LITERAL.replace("https://", "http://"), URL_LITERAL.replace("finmindtrade.com", "finmindtrade.com:443"),
                    URL_LITERAL.replace("https://", "https://user@"), "https://example.org/a?b=1"):
            with self.subTest(refused=bad[:70]), patch.object(M.http.client, "HTTPSConnection", Connection):
                self.assertFailure("transport_url", M.HTTPSOneShot().open, bad, 20)
        self.assertEqual(len(connections), built)

    def test_default_https_budget_boundaries_and_header_failure_closes_response(self):
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
                clock.elapsed += 12

            def request(self, method, target, headers):
                self.requests.append((method, target, headers))
                clock.elapsed += 3

            def getresponse(self):
                clock.elapsed += header_delay[0]
                return self.body

            def close(self):
                self.closed = True
        for delay in (1, 6):
            header_delay = [delay]
            clock.elapsed = 100
            connections = []

            def factory(*args, **kwargs):
                value = Connection(*args, **kwargs)
                connections.append(value)
                return value
            with patch.object(M.time, "monotonic", clock.monotonic), patch.object(M.http.client, "HTTPSConnection", factory), \
                    patch.object(M.ssl, "create_default_context", lambda: object()):
                if delay == 1:
                    M.HTTPSOneShot().open(URL_LITERAL, 20).close()
                else:
                    self.assertFailure("cooperative_deadline", M.HTTPSOneShot().open, URL_LITERAL, 20)
            connection = connections[0]
            self.assertEqual(connection.timeout, 20)
            self.assertEqual(connection.sock.timeouts, [8, 5])
            self.assertTrue(connection.closed)
            self.assertTrue(connection.body.closed)
            self.assertEqual(connection.requests[0][2], FINMIND_REQUEST_HEADERS)

    def test_https_response_closes_both_and_open_failure_closes_primary_preserved(self):
        order = []

        class Body:
            status = 200
            length = 0
            fp = None

            def getheaders(self):
                return ()

            def isclosed(self):
                return True

            def close(self):
                order.append("response")
                raise RuntimeError("synthetic response close failure")

        class Connection:
            sock = None

            def close(self):
                order.append("connection")
                raise RuntimeError("synthetic connection close failure")
        response = M._HTTPSResponse(Connection(), Body())
        with self.assertRaises(RuntimeError) as caught:
            response.close()
        self.assertEqual(order, ["response", "connection"])
        self.assertEqual(str(caught.exception), "synthetic response close failure")
        M.clear_error_graph(caught.exception)

        events = []

        class FailingConnection:
            def __init__(self, host, timeout, context):
                self.sock = types.SimpleNamespace(settimeout=lambda value: None)

            def connect(self):
                events.append("connect")

            def request(self, method, target, headers):
                events.append("request")

            def getresponse(self):
                raise OSError("synthetic header failure")

            def close(self):
                events.append("connection_close")
                raise RuntimeError("synthetic cleanup failure")
        with patch.object(M.http.client, "HTTPSConnection", FailingConnection), patch.object(M.ssl, "create_default_context", lambda: object()):
            with self.assertRaises(OSError) as caught:
                M.HTTPSOneShot().open(URL_LITERAL, 20)
        self.assertEqual(events, ["connect", "request", "connection_close"])
        self.assertEqual(str(caught.exception), "synthetic header failure")
        M.clear_error_graph(caught.exception)

    # ---- AC-5: lifecycle and original failures --------------------------------------------------

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

    def test_unsupported_getter_consumer_and_cutoff_are_terminal(self):
        actions = (lambda s: s.get_taiex_nominal21("2026-10-05", supported_use="hot_group_v1"),
                   lambda s: s.summarize("2026-10-05", consumer="other"),
                   lambda s: s.summarize("2026-10-05", supported_use="strategy"),
                   lambda s: s.get_taiex_nominal21("2026-10-07"),
                   lambda s: s.summarize("2026-10-04"),
                   lambda s: s.get_taiex_nominal21(20261005))
        codes = ("unsupported_getter_use", "unsupported_consumer_use", "unsupported_consumer_use",
                 "unsupported_cutoff", "unsupported_cutoff", "unsupported_cutoff")
        for action, code in zip(actions, codes):
            source, owner, transport, clock = self.build()
            with source:
                handle = source.get_taiex_nominal21("2026-10-06")
                with self.assertRaises(M.TaiexSourceError) as caught:
                    action(source)
                self.assertEqual(caught.exception.code, code)
                M.clear_error_graph(caught.exception)
                self.assert_terminal_results(source, owner, handle, code)
            self.assertEqual(source.state, "failed")

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

                    def action():
                        return handle.visit(visit_bad_root, owner)
                else:
                    owner.track("opaque_result_alias", object())

                    def action():
                        return source.get_taiex_nominal21("2026-10-06") if operation == "getter" else source.summarize("2026-10-06")
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
        self.assertNotIn("synthetic secret", json.dumps(report, default=str))
        self.assertIsNone(original.__cause__)
        self.assertIsNone(original.__context__)
        self.assertIsNone(original.__traceback__)
        self.assertEqual(original.args, ())

    def test_trace_sees_full_original_before_parse_and_is_turned_off_on_failure(self):
        seen = []

        def trace(frame, event, arg):
            if event == "call" and frame.f_globals.get("__name__") == SPEC.name and frame.f_code.co_name == "_finmind":
                seen.append((bytes(frame.f_locals["raw"]), dict(frame.f_locals["self"].receipts[0])))
            return None
        source, owner, transport, clock = self.build(hooks_options={"finmind": lambda raw, receipt, rows: rows[:-1]})
        try:
            sys.settrace(trace)
            self.expect_failure(source, "finmind_full_oracle_mismatch", 1)
            self.assertIsNone(sys.gettrace())  # turned off by the product's own release
        finally:
            sys.settrace(None)
        self.assertEqual(len(seen), 1)
        body, receipt = seen[0]
        self.assertEqual(body, DEFAULT_BODY)
        self.assertEqual((receipt["sha256"], receipt["body_bytes"], receipt["eof"]), (hashlib.sha256(DEFAULT_BODY).hexdigest(), len(DEFAULT_BODY), True))
        seen.clear()
        self.assertTrue(source.diagnostic_report()["declared_roots_empty"])
        source, owner, transport, clock = self.build(body=b'{"msg":"success","status":200,"data":null}')
        sys.settrace(lambda frame, event, arg: None)
        sys.setprofile(lambda frame, event, arg: None)
        try:
            self.expect_failure(source, "finmind_rows", 1)
            self.assertIsNone(sys.gettrace())
            self.assertIsNone(sys.getprofile())
        finally:
            sys.settrace(None)
            sys.setprofile(None)

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
        self.assertNotIn("must not appear", json.dumps(report, default=str))
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_pending_transport_and_active_read_block_declared(self):
        source, owner, transport, clock = self.build()
        observed = {"pending": 0, "active": 0}
        actual_open = transport.open

        def checked_open(url, timeout):
            root = source.product.roots["transport"]
            self.assertIs(type(root), M.NativeTransport)
            self.assertIsNone(root.response)
            self.assertEqual(root.native_bytes, 262144)
            self.assertTrue(any(event["phase"] == "transport_pending" for event in source.diagnostics))
            observed["pending"] += 1
            return actual_open(url, timeout)
        transport.open = checked_open
        actual_remaining = source._request_remaining

        def checked_remaining(started):
            if "active_read_block" in source.product.roots:
                self.assertIs(type(source.product.roots["active_read_block"]), bytes)
                self.assertEqual(source.product.roots["read_allowance"].native_bytes, 65536)
                owner.track("active_block_alias", source.product.roots["active_read_block"])
                observed["active"] += 1
            return actual_remaining(started)
        source._request_remaining = checked_remaining
        with source:
            self.assertNotIn("active_read_block", source.product.roots)
        self.assertEqual(observed["pending"], 1)
        self.assertGreaterEqual(observed["active"], 1)
        self.assertTrue(source.diagnostic_report()["declared_roots_empty"])
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_failed_postread_guard_cleans_named_block_alias(self):
        source, owner, transport, clock = self.build(options={"read_seconds": 20})
        actual_remaining = source._request_remaining
        observed = []

        def checked_remaining(started):
            if "active_read_block" in source.product.roots:
                owner.track("failed_active_read_alias", source.product.roots["active_read_block"])
                observed.append(True)
            return actual_remaining(started)
        source._request_remaining = checked_remaining
        report = self.expect_failure(source, "request_deadline", 1)
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
                self.assertEqual(len(transport.responses), 1)
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

    # ---- structural guards -------------------------------------------------------------------------

    def test_government_csv_path_is_gone_and_real_namespace_untouched(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        for needle in ("MI_5MINS_HIST", "twse.com.tw", "import csv", "official_", "ROC", "data.gov.tw"):
            self.assertNotIn(needle, text)
        self.assertEqual(M.URLS, (URL_LITERAL,))
        self.assertFalse(hasattr(M, "POLICY_PIN"))
        self.assertFalse(M._REAL_LEDGER.spent)
        self.assertEqual(M._REAL_LEDGER.attempted_urls, [])
        with self.assertRaises(TypeError):
            M.OracleHooks(lambda *args: None, lambda *args: None, lambda *args: None, M.RootOwner("x"))


def main():
    print("Engineering RAM synthetic boundary only; financial/provider metadata GET0; artifact0B; not QA AC acceptance", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Boundaries))
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                      "financial_gets": 0, "provider_metadata_gets": 0, "github_gets": 0, "artifact_bytes": 0,
                      "real_namespace_spent": M._REAL_LEDGER.spent, "policy_bytes": M.POLICY_BYTES,
                      "policy_sha256": M.POLICY_SHA256}), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
