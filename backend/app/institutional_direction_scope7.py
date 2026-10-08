"""Direction-only router factory; no database, price or private-store imports."""
from datetime import date
import json
import re
from urllib.parse import parse_qsl
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from worker.tpex_institutional_direction_scope7 import CUTOFF, DirectionError, Producer, blank, check_policy, policy, require

EXPECTED_VERSION = "m1-chips-direction-segments-stock-scope-7-tpex-2026-10-06.1"
EXPECTED_DIGEST = "sha256:eb7a4dd688907855dd91250bfbec96b4dd8b2cb65085dce49e7e12c3a80c5348"
EXPECTED_PROFILE = "free_public_local_chips_only_direction_segments_stock_scope_7"
API_PATH = "/api/chips/direction-stock-scope-7"
DIAGNOSTIC_PATH = "/__direction_root_receipt"


def create_app(producer, *, version=EXPECTED_VERSION, pin=EXPECTED_DIGEST, profile=EXPECTED_PROFILE):
    check_policy(policy(), version, pin, profile)
    require(type(producer) is Producer and not producer.attempted and producer.request_count == 0 and producer._captures == (), "new_empty_direction_producer_required")
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def exact_gate(request: Request, call_next):
        path, method = request.url.path, request.method
        allowed = {API_PATH: "GET", API_PATH + "/capture": "POST", DIAGNOSTIC_PATH: "GET"}
        if path not in allowed:
            return JSONResponse({"reason": "path_not_admitted"}, status_code=404)
        if method != allowed[path]:
            return JSONResponse({"reason": "method_not_admitted"}, status_code=405)
        if path == DIAGNOSTIC_PATH:
            if request.client is None or request.client.host not in ("127.0.0.1", "::1", "testclient"):
                return JSONResponse({"reason": "root_local_only"}, status_code=403)
            if request.scope.get("query_string"):
                return JSONResponse({"reason": "diagnostic_query_rejected"}, status_code=422)
            as_of = CUTOFF
        else:
            try:
                raw = request.scope["query_string"].decode("ascii")
                pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, encoding="utf-8", errors="strict")
                if len(pairs) != 1 or pairs[0][0] != "as_of":
                    raise ValueError("exact_query_keys_required")
                as_of = pairs[0][1]
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of) is None or date.fromisoformat(as_of).isoformat() != as_of:
                    raise ValueError("invalid_date")
            except (ValueError, UnicodeError):
                return JSONResponse({"reason": "exact_query_keys_and_iso_date_required"}, status_code=422)
        cap = 4096 if method == "POST" else 0
        try:
            declared = request.headers.get("content-length")
            if declared is not None and (not declared.isdecimal() or int(declared) > cap):
                return JSONResponse({"reason": "body_limit"}, status_code=413 if method == "POST" else 422)
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > cap:
                    return JSONResponse({"reason": "body_limit"}, status_code=413 if method == "POST" else 422)
                body.extend(chunk)
            if method == "POST":
                parsed = json.loads(bytes(body))
                if type(parsed) is not dict or parsed != {}:
                    raise ValueError("empty_object_required")
        except (ValueError, UnicodeError):
            return JSONResponse({"reason": "empty_json_object_required"}, status_code=422)
        if as_of != CUTOFF:
            return JSONResponse(blank("cutoff_not_supported", as_of))
        return await call_next(request)

    @app.get(API_PATH)
    def read():
        result = producer.read()
        return JSONResponse(result, status_code=200 if result["attempted"] else 409)

    @app.post(API_PATH + "/capture")
    def capture():
        try:
            result = producer.capture()
        except DirectionError as exc:
            return JSONResponse(blank(str(exc), generation=producer.generation), status_code=409)
        return JSONResponse(result, status_code=200 if result["available"] else 502)

    @app.get(DIAGNOSTIC_PATH)
    def diagnostic():
        return JSONResponse(producer.diagnostic())

    return app
