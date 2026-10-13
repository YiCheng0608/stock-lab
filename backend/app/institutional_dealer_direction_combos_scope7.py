"""Issue 9 dealer self/hedging direction combos: pure computation and a chips-only API factory.

No database, price, private-store, worker or HTTP-client imports; no import-time I/O. The source
(``DealerDirectionSource``) is supplied by the caller and owns the only upstream path. Everything here is
derived in RAM from its ``available`` records: the per-day self/hedging net (``buy - sell``), the sign of each,
the nine same-day combinations, the opposite-direction days, per-component sign counts, maximal same-sign
segments (zero is its own run and breaks positive/negative runs) and the latest window-limited segment. The
first segment always says ``earlier_unknown``: nothing before the five-session window is inferred.

Missing or unknown is never zero: any source, schema, name, date, anchor or arithmetic conflict makes all
seven symbols unavailable. Every point keeps the five original FinMind name rows of its symbol-date (original
values, row ordinal, key order) plus the body SHA-256, canonical receipt SHA-256 and URL so a segment can be
traced back to its original rows.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import uuid
from datetime import date
from types import MappingProxyType
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .finmind_dealer_direction_source import (
    CONSUMER_VERSION, CUTOFF, INT64_MAX, NAME_HEDGE, NAME_SELF, NAMESPACE, SYMBOLS, URLS, WINDOW_DATES,
    DealerDirectionSource, OracleAdmission, SourceError)

READ_SCHEMA = "dealer-direction-combos-read/finmind-stock-scope-7-v1"
CALCULATION = "dealer-self-hedging-sign-combos-counts-maximal-segments/five-session-int64-v1"
API_PATH = "/api/chips/dealer-direction-combos-stock-scope-7"
CAPTURE_PATH = API_PATH + "/capture"
DIAGNOSTIC_PATH = "/__dealer_direction_root_receipt"
ADMIT_PATH = "/__dealer_direction_admit"
IDENTITIES = MappingProxyType({"3105": "穩懋", "3293": "鈊象", "5274": "信驊", "5347": "世界", "6488": "環球晶", "6510": "精測", "8069": "元太"})
COMPONENTS = ("self", "hedge")
COMPONENT_NAMES = MappingProxyType({"self": NAME_SELF, "hedge": NAME_HEDGE})
SIGNS = ("positive", "negative", "zero")
COMBINATION_KEYS = tuple(a + "_" + b for a in SIGNS for b in SIGNS)
OPPOSITE_KEYS = ("positive_negative", "negative_positive")
CLOSED_DATES = ("2026-09-25", "2026-09-28")
MIN_I64 = -INT64_MAX - 1
LOCAL_HOSTS = ("127.0.0.1", "::1", "testclient")
JSON_MEDIA = re.compile(r"application/json(?:\s*;\s*charset=utf-8)?", re.I)
ADMISSION_FIELDS = ("namespace", "policy_sha256", "holder_session_id", "candidate_sha", "script_sha256",
                    "receipt_sha256s", "name_rows", "stock_days", "anchor_values", "record_only_matches", "independent")


class DirectionComboError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise DirectionComboError(reason)


def bounded(n, reason="arithmetic_int64_overflow"):
    require(type(n) is int and MIN_I64 <= n <= INT64_MAX, reason)
    return n


def sign(n):
    bounded(n, "sign_int64_required")
    return "positive" if n > 0 else "negative" if n < 0 else "zero"


def lots(n):
    """Exact shares / 1000, at most three decimals, never float."""
    bounded(n)
    whole, rest = divmod(abs(n), 1000)
    return ("-" if n < 0 else "") + str(whole) + (("." + str(rest).zfill(3).rstrip("0")) if rest else "")


def net_of(buy, sell):
    require(type(buy) is int and type(sell) is int and 0 <= buy <= INT64_MAX and 0 <= sell <= INT64_MAX, "gross_int64_required")
    return bounded(buy - sell)


def combination(self_sign, hedge_sign):
    require(self_sign in SIGNS and hedge_sign in SIGNS, "sign_required")
    return self_sign + "_" + hedge_sign


def segments_of(signs, dates):
    """Maximal same-sign runs covering the window once; only the first run is ``earlier_unknown``."""
    require(len(signs) == len(dates) and len(signs) > 0 and all(s in SIGNS for s in signs), "segment_input")
    segments = []
    for index, current in enumerate(signs):
        if segments and segments[-1]["sign"] == current:
            segments[-1].update(end_index=index, end_date=dates[index], length=segments[-1]["length"] + 1)
        else:
            segments.append({"sign": current, "start_index": index, "end_index": index, "start_date": dates[index],
                             "end_date": dates[index], "length": 1, "earlier_unknown": index == 0})
    require(sum(s["length"] for s in segments) == len(signs), "segments_cover_window")
    require(all(a["sign"] != b["sign"] and a["end_index"] + 1 == b["start_index"] for a, b in zip(segments, segments[1:])), "segments_maximal")
    return segments


def _amounts(row):
    net = net_of(row.buy, row.sell)
    return {"row_index": row.row_index, "buy_shares": str(row.buy), "sell_shares": str(row.sell),
            "net_shares": str(net), "net_lots": lots(net), "sign": sign(net)}


def _row_trace(row):
    return {"row_index": row.row_index, "key_order": list(row.key_order), "date": row.date, "stock_id": row.stock_id,
            "name": row.name, "buy_shares": str(row.buy), "sell_shares": str(row.sell)}


def window_result(records, receipt_by_index):
    """Pure per-symbol result from exactly the five window-date records (original FinMind rows)."""
    require(type(records) is tuple and len(records) == len(WINDOW_DATES), "five_session_window_required")
    require(tuple(r.date for r in records) == WINDOW_DATES and len({r.symbol for r in records}) == 1, "window_dates")
    dates = list(WINDOW_DATES)
    points, signs = [], {c: [] for c in COMPONENTS}
    for index, record in enumerate(records):
        receipt = receipt_by_index[record.source_index]
        point = {"date": record.date, "index": index, "request_index": record.source_index,
                 "url": receipt["url"], "receipt_sha256": receipt["sha256"], "body_sha256": receipt["body_sha256"],
                 "rows": [_row_trace(r) for r in record.rows]}
        for component in COMPONENTS:
            amounts = _amounts(record.row(COMPONENT_NAMES[component]))
            point[component] = amounts
            signs[component].append(amounts["sign"])
        key = combination(point["self"]["sign"], point["hedge"]["sign"])
        point["combination"], point["opposite"] = key, key in OPPOSITE_KEYS
        points.append(point)
    counts = {c: {s: signs[c].count(s) for s in SIGNS} for c in COMPONENTS}
    require(all(sum(counts[c].values()) == len(points) for c in COMPONENTS), "counts_reconciliation")
    combination_dates = {k: [p["date"] for p in points if p["combination"] == k] for k in COMBINATION_KEYS}
    combination_counts = {k: len(v) for k, v in combination_dates.items()}
    require(sum(combination_counts.values()) == len(points), "combination_reconciliation")
    opposite_dates = [p["date"] for p in points if p["opposite"]]
    require(len(opposite_dates) == sum(combination_counts[k] for k in OPPOSITE_KEYS), "opposite_reconciliation")
    segments = {c: segments_of(signs[c], dates) for c in COMPONENTS}
    return {"horizon": len(points), "points": points, "counts": counts, "segments": segments,
            "latest": {c: dict(segments[c][-1]) for c in COMPONENTS},
            "combination_counts": combination_counts, "combination_dates": combination_dates,
            "opposite": {"count": len(opposite_dates), "dates": opposite_dates}}


def _plain(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _receipts(source):
    result = []
    for index, receipt in enumerate(source.receipts):
        text = receipt.canonical_bytes.decode("utf-8")
        result.append({"request_index": index, "symbol": SYMBOLS[index], "url": receipt.url, "canonical": text,
                       "sha256": receipt.canonical_sha256, "body_sha256": receipt.body_sha256, "body_bytes": receipt.body_bytes})
    return result


def blank(reason, state, *, generation=None, as_of=CUTOFF, attempted=False, request_count=0, failure=None):
    return {"schema": READ_SCHEMA, "calculation_version": CALCULATION, "consumer_version": CONSUMER_VERSION,
            "namespace": NAMESPACE, "as_of": as_of, "generation": generation, "state": state,
            "available": False, "reason": reason, "failure": failure, "count": None,
            "window_dates": list(WINDOW_DATES), "stocks": [], "calendar": None, "receipts": [], "provenance": None,
            "attempted": attempted, "request_count": request_count}


def calendar_reference():
    return {"reference": "SOURCE_REGISTRY 31.2", "closed_dates": list(CLOSED_DATES), "calendar_gets": 0,
            "window_dates": list(WINDOW_DATES), "anchor_only_dates": ["2026-09-29"],
            "meaning": "fixed verified trading days; no calendar GET, no closure inference"}


def read_result(source, generation):
    """The READ payload: complete and available, or a blank with the state and the first failure code."""
    state = source.state
    attempted = len(source.ledger.attempted) if source.ledger is not None else 0
    if state != "available":
        failure = None
        if state == "failed":
            diag = source.diagnostics
            failure = {key: diag[key] for key in ("primary_code", "primary_stage") if key in diag}
        reason = {"new": "not_acquired", "acquiring": "acquiring", "pending": "pending_independent_admission"}.get(state, state)
        return blank(reason, state, generation=generation, attempted=state != "new", request_count=attempted, failure=failure)
    try:
        receipts = _receipts(source)
        by_index = {r["request_index"]: r for r in receipts}
        stocks = []
        for symbol in SYMBOLS:
            window = window_result(source.window_records(symbol), by_index)
            stocks.append({"symbol": symbol, "name": IDENTITIES[symbol], "exchange": "TPEx", "security_type": "stock",
                           "currency": "TWD", "unit": "shares", "window": window})
        provenance = _plain(source.provenance)
        return blank(None, "available", generation=generation, attempted=True, request_count=attempted) | {
            "available": True, "count": len(stocks), "stocks": stocks, "calendar": calendar_reference(),
            "receipts": receipts, "provenance": provenance}
    except (DirectionComboError, SourceError, ValueError, TypeError, KeyError, AttributeError, IndexError):
        return blank("calculation_conflict", "available", generation=generation, attempted=True, request_count=attempted)


def diagnostic_result(source, generation):
    """Root-local raw originals for an independent auditor; bodies stay in RAM and are never stored."""
    state = source.state
    attempted = len(source.ledger.attempted) if source.ledger is not None else 0
    captures = []
    if state in ("pending", "available", "failed"):
        for capture in source.inspection()["captures"]:
            captures.append({"body_base64": base64.b64encode(capture.body).decode("ascii"),
                             "canonical_receipt_base64": base64.b64encode(capture.receipt.canonical_bytes).decode("ascii"),
                             "receipt_sha256": capture.receipt.canonical_sha256, "body_sha256": capture.receipt.body_sha256,
                             "url": capture.receipt.url})
    return {"generation": generation, "state": state, "attempted": attempted, "request_count": attempted,
            "policy_sha256": source.policy_sha256, "namespace": NAMESPACE, "urls": list(URLS), "captures": captures}


def _error(reason, status):
    return JSONResponse({"reason": reason}, status_code=status)


def browser_gate(headers, own_host):
    """Cross-site and DNS-rebinding guard for a localhost-only service: (status, reason) to refuse, else None.

    Pure on purpose. The service never emits CORS headers, so a cross-origin preflight fails by itself; this
    additionally refuses the simple requests a foreign page can still send, before any state is touched or quota
    is spent: the Host must be exactly ``127.0.0.1:<port>``, ``Sec-Fetch-Site`` (when sent) must be same-origin or
    none, and ``Origin`` (when sent) must be this service's own origin.
    """
    if headers.getlist("host") != [own_host]:
        return 403, "host_not_admitted"
    site = headers.getlist("sec-fetch-site")
    if site and (len(site) != 1 or site[0].lower() not in ("same-origin", "none")):
        return 403, "cross_site_rejected"
    origin = headers.getlist("origin")
    if origin and origin != ["http://" + own_host]:
        return 403, "origin_not_admitted"
    return None


def json_content_type_gate(headers):
    """Every POST must declare application/json (a form or text/plain simple request is refused)."""
    values = headers.getlist("content-type")
    if len(values) != 1 or JSON_MEDIA.fullmatch(values[0].strip()) is None:
        return 415, "content_type_json_required"
    return None


def create_app(source: DealerDirectionSource, *, port):
    """Chips-only API for ONE new source on 127.0.0.1:<port>. No lifespan, DB or private store."""
    require(type(source) is DealerDirectionSource and source.state == "new", "new_unattempted_source_required")
    require(type(port) is int and 1024 <= port <= 65535, "local_port_required")
    own_host = "127.0.0.1:%d" % port
    generation = str(uuid.uuid4())
    lock = threading.Lock()
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    allowed = {API_PATH: "GET", CAPTURE_PATH: "POST", DIAGNOSTIC_PATH: "GET", ADMIT_PATH: "POST"}

    @app.middleware("http")
    async def exact_gate(request: Request, call_next):
        path, method = request.url.path, request.method
        refused = browser_gate(request.headers, own_host)
        if refused is not None:
            return _error(refused[1], refused[0])
        if path not in allowed:
            return _error("path_not_admitted", 404)
        if method != allowed[path]:
            return _error("method_not_admitted", 405)
        if method == "POST":
            refused = json_content_type_gate(request.headers)
            if refused is not None:
                return _error(refused[1], refused[0])
        local_only = path in (DIAGNOSTIC_PATH, ADMIT_PATH)
        if local_only and (request.client is None or request.client.host not in LOCAL_HOSTS):
            return _error("root_local_only", 403)
        as_of = CUTOFF
        if local_only:
            if request.scope.get("query_string"):
                return _error("query_rejected", 422)
        else:
            try:
                pairs = parse_qsl(request.scope["query_string"].decode("ascii"), keep_blank_values=True, strict_parsing=True, encoding="utf-8", errors="strict")
                if len(pairs) != 1 or pairs[0][0] != "as_of":
                    raise ValueError("exact_query_keys_required")
                as_of = pairs[0][1]
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of) is None or date.fromisoformat(as_of).isoformat() != as_of:
                    raise ValueError("invalid_date")
            except (ValueError, UnicodeError):
                return _error("exact_query_keys_and_iso_date_required", 422)
        cap = 8192 if path == ADMIT_PATH else 4096 if method == "POST" else 0
        try:
            declared = request.headers.get("content-length")
            if declared is not None and (not declared.isdecimal() or int(declared) > cap):
                return _error("body_limit", 413 if method == "POST" else 422)
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > cap:
                    return _error("body_limit", 413 if method == "POST" else 422)
                body.extend(chunk)
            if method == "POST":
                raw = bytes(body)
                if path == CAPTURE_PATH:
                    # The one-shot capture carries exactly the two bytes `{}`: no BOM, whitespace, `{ }` or UTF-16/32 spelling.
                    if raw != b"{}":
                        raise ValueError("empty_object_bytes_required")
                    parsed = {}
                else:
                    parsed = json.loads(raw)
                    if type(parsed) is not dict:
                        raise ValueError("object_required")
                request.state.json_body = parsed
        except (ValueError, UnicodeError, RecursionError):  # RecursionError is a RuntimeError: deep nesting must not become a 500
            return _error("json_object_required", 422)
        if not local_only and as_of != CUTOFF:
            return JSONResponse(blank("cutoff_not_supported", source.state, generation=generation, as_of=as_of), status_code=409)
        return await call_next(request)

    @app.get(API_PATH)
    def read():
        with lock:
            result = read_result(source, generation)
        return JSONResponse(result, status_code=200 if result["available"] else 409)

    @app.post(CAPTURE_PATH)
    def capture():
        with lock:
            if source.state != "new":
                return JSONResponse(blank("already_attempted", source.state, generation=generation, attempted=True,
                                          request_count=len(source.ledger.attempted)), status_code=409)
            try:
                source.acquire()
            except SourceError:
                return JSONResponse(read_result(source, generation), status_code=502)
            return JSONResponse(read_result(source, generation), status_code=200)

    @app.post(ADMIT_PATH)
    def admit(request: Request):
        body = request.state.json_body
        with lock:
            try:
                if set(body) != set(ADMISSION_FIELDS) or type(body["receipt_sha256s"]) is not list:
                    raise SourceError("oracle_type")
                source.admit_independent_verification(OracleAdmission(**{**body, "receipt_sha256s": tuple(body["receipt_sha256s"])}))
            except SourceError as exc:
                return JSONResponse({"reason": exc.code, "state": source.state}, status_code=409)
            except TypeError:
                return JSONResponse({"reason": "oracle_type", "state": source.state}, status_code=422)
            return JSONResponse({"state": source.state})

    @app.get(DIAGNOSTIC_PATH)
    def diagnostic():
        with lock:
            return JSONResponse(diagnostic_result(source, generation))

    return app
