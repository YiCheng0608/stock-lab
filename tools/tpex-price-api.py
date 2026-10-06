"""M1-PRICE-1: guarded checks or root-owned actual router preview, no disk artifacts."""
from __future__ import annotations
import argparse
import ast
import base64
from datetime import date
import json
import os
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--deps", required=True, help="existing backend/.deps, read-only")
mode = parser.add_mutually_exclusive_group()
mode.add_argument("--check", action="store_true")
mode.add_argument("--focus-check", action="store_true")
mode.add_argument("--serve", action="store_true")
parser.add_argument("--port", type=int, default=8795)
parser.add_argument("--live-source-opt-in", action="store_true")
parser.add_argument("--policy-version")
parser.add_argument("--policy-digest")
parser.add_argument("--cutoff", choices=("2026-10-05", "2026-10-06"), default="2026-10-05")
ARGS = parser.parse_args()
if ARGS.live_source_opt_in and not ARGS.serve:
    parser.error("live source is only admitted in root-owned serve")
if not 1024 <= ARGS.port <= 65535:
    parser.error("invalid owned port")
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests"), str(Path(ARGS.deps).resolve())]
COUNTS = {"disk_writes": 0, "mutations": 0, "unapproved_network": 0, "subprocesses": 0}
LIVE_ACTIVE = False
APPROVED_ADDRESSES = set()
SOURCE_REQUESTS = []
PRELOADED_SOURCE = False
RUNNER_SOURCE_REQUESTS = 0
original_resolver = socket.getaddrinfo


def socketpair_context():
    frame = sys._getframe(1)
    while frame:
        if "socketpair" in frame.f_code.co_name and frame.f_code.co_filename.endswith("socket.py"):
            return True
        frame = frame.f_back
    return False


def audit(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            COUNTS["disk_writes"] += 1
            raise AssertionError("disk write denied")
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "tempfile.mkstemp", "tempfile.mkdtemp"}:
        COUNTS["mutations"] += 1
        raise AssertionError("filesystem mutation denied")
    if event == "subprocess.Popen":
        COUNTS["subprocesses"] += 1
        raise AssertionError("subprocess denied")
    if event == "sqlite3.connect" and args[0] != ":memory:":
        raise AssertionError("only memory database admitted")
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        address = args[1] if event in {"socket.connect", "socket.bind"} else args[0]
        local = isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
        allowed = local and socketpair_context()
        if event == "socket.bind": allowed = allowed or (ARGS.serve and local and address[1] == ARGS.port)
        if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            allowed = allowed or address in {"localhost", "127.0.0.1", "::1", None}
            allowed = allowed or (ARGS.live_source_opt_in and LIVE_ACTIVE and address in {"www.tpex.org.tw", b"www.tpex.org.tw"} and (event != "socket.getaddrinfo" or args[1] == 443))
        if event == "socket.connect" and ARGS.live_source_opt_in and LIVE_ACTIVE:
            allowed = isinstance(address, tuple) and (address[0], address[1]) in APPROVED_ADDRESSES
        if not allowed:
            COUNTS["unapproved_network"] += 1
            raise AssertionError("network outside owned scope denied")


sys.addaudithook(audit)


def resolver(host, port, *args, **kwargs):
    answers = original_resolver(host, port, *args, **kwargs)
    if LIVE_ACTIVE and host in {"www.tpex.org.tw", b"www.tpex.org.tw"} and port == 443:
        APPROVED_ADDRESSES.update((answer[4][0], answer[4][1]) for answer in answers)
    return answers


socket.getaddrinfo = resolver


def memory_config():
    config_path = ROOT / "backend/app/config.py"
    tree = ast.parse(config_path.read_text(encoding="utf-8"), filename=str(config_path))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "mkdir")]
    config = types.ModuleType("app.config")
    config.__file__ = str(config_path)
    exec(compile(tree, str(config_path), "exec"), config.__dict__)
    config.DATA_DIR, config.RAW_DIR, config.DB_PATH = Path("__memory_only__"), Path("__memory_only__/raw"), Path(":memory:")
    sys.modules["app.config"] = config


memory_config()
from worker import tpex_price_capture as worker
from app import tpex_price
from test_tpex_price_api import MemoryAPIFixture


def receipt(fixture=None, include_raw=False):
    import fastapi, sqlalchemy, httpx
    result = {"pid": os.getpid(), "runtime": {"python": sys.version.split()[0], "fastapi": fastapi.__version__, "sqlalchemy": sqlalchemy.__version__, "httpx": httpx.__version__},
              "guard": dict(COUNTS), "disk_artifacts": 0, "source_requests": list(SOURCE_REQUESTS),
              "source_request_count": len(SOURCE_REQUESTS), "runner_source_request_count": RUNNER_SOURCE_REQUESTS, "preloaded_source": PRELOADED_SOURCE,
              "policy_version": tpex_price.policy_pins(date.fromisoformat(ARGS.cutoff), policy_version=ARGS.policy_version)[0], "policy_digest": tpex_price.policy_pins(date.fromisoformat(ARGS.cutoff), policy_version=ARGS.policy_version)[1],
              "scope": "tuple-scoped ordinary TPEx stocks, " + ARGS.cutoff + ", single day; no history/MA20/PIT/save acceptance"}
    if fixture:
        raw = fixture.store.raw_capture
        result["db_preserved"] = fixture.before == fixture.snapshot()
        result["capture_state"] = fixture.store.read("TPEx", "3105", date.fromisoformat(ARGS.cutoff), instrument_type="stock", currency="TWD")["capture_state"]
        result["capture_receipt"] = raw.receipt if raw else None
        result["selected"] = raw.parsed["selected"] if raw else None
        result["fixture_kind"] = fixture.catalogue_kind + ("; live admitted source" if ARGS.live_source_opt_in or PRELOADED_SOURCE else "; synthetic private test anchors; not official raw")
        if include_raw:
            result["raw_base64"] = base64.b64encode(raw.body).decode("ascii") if raw else None
            result["receipt_base64"] = base64.b64encode(raw.receipt_bytes).decode("ascii") if raw else None
    return result


def check():
    suite = unittest.TestSuite()
    for name in (("test_price_focus",) if ARGS.focus_check else ("test_tpex_price_capture", "test_tpex_price_store", "test_tpex_price_api")):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    run = unittest.TextTestRunner(verbosity=2).run(suite)
    output = receipt()
    output.update(tests=run.testsRun, failures=len(run.failures), errors=len(run.errors), fixtures="reconstructed tuple-scoped selected values plus synthetic rows, memory only")
    print(json.dumps(output, ensure_ascii=False), flush=True)
    return 0 if run.wasSuccessful() and not any(COUNTS.values()) else 1


def serve(preloaded_store=None):
    global PRELOADED_SOURCE
    from starlette.responses import JSONResponse
    import uvicorn
    cutoff = date.fromisoformat(ARGS.cutoff)
    if (ARGS.live_source_opt_in or preloaded_store is not None) and (ARGS.policy_version, ARGS.policy_digest) != tpex_price.policy_pins(cutoff, policy_version=ARGS.policy_version):
        raise ValueError("external accepted policy pins required for live preview")
    fixture = MemoryAPIFixture(live=ARGS.live_source_opt_in or preloaded_store is not None, cutoff=cutoff, policy_version=ARGS.policy_version)
    if preloaded_store is not None:
        raw = preloaded_store.raw_capture
        if not isinstance(preloaded_store, tpex_price.TpexPriceStore) or raw is None or not preloaded_store._attempted or preloaded_store._request_count != 1 or preloaded_store._error:
            fixture.close()
            raise ValueError("existing admitted same-process capture required")
        tpex_price.TpexPriceStore._validated_capture(raw, cutoff)
        fixture.store = preloaded_store
        fixture.stack.enter_context(patch.object(tpex_price, "STORE", preloaded_store))
        PRELOADED_SOURCE = True
        SOURCE_REQUESTS.append({"method": "GET", "url": raw.receipt["endpoint"], "origin": "preloaded_same_process_capture",
                                "request_started_at": raw.receipt["request_started_at"], "captured_at": raw.receipt["captured_at"], "body_sha256": raw.receipt["body_sha256"]})
    elif ARGS.live_source_opt_in:
        def loader(**kwargs):
            global LIVE_ACTIVE, RUNNER_SOURCE_REQUESTS
            if SOURCE_REQUESTS:
                raise worker.PriceCaptureError("price_capture_already_attempted")
            original_on_request = kwargs.pop("on_request")
            def on_request():
                global RUNNER_SOURCE_REQUESTS
                SOURCE_REQUESTS.append({"method": "GET", "url": worker.ENDPOINT})
                RUNNER_SOURCE_REQUESTS += 1
                original_on_request()
            LIVE_ACTIVE = True
            try:
                return worker.capture_price(**kwargs, on_request=on_request)
            finally:
                LIVE_ACTIVE = False
        fixture.store._loader = loader
    @fixture.app.middleware("http")
    async def scope(request, call_next):
        capture_paths = {f"/api/stocks/TPEx/{symbol}/prices/capture" for symbol in worker.policy_symbols(cutoff, policy_version=ARGS.policy_version)}
        allowed = request.method in {"GET", "OPTIONS"} or (request.method == "POST" and request.url.path in capture_paths | {"/api/focus/price-lots/capture"})
        if not allowed: return JSONResponse({"detail": "preview operation outside scope"}, status_code=405)
        return await call_next(request)
    @fixture.app.get("/__price_validation/receipt")
    def diagnostic(include_raw: bool = False):
        result = receipt(fixture, include_raw)
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 8 * 1024 * 1024:
            return JSONResponse({"detail": "diagnostic response bound"}, status_code=413)
        return result
    print(json.dumps({"mode": "owned actual router, memory catalogue", "live_source_opt_in": ARGS.live_source_opt_in,
                      "pid": os.getpid(), "host": "127.0.0.1", "port": ARGS.port, "initial_receipt": receipt(fixture)}, ensure_ascii=False), flush=True)
    try:
        uvicorn.run(fixture.app, host="127.0.0.1", port=ARGS.port, log_level="warning", access_log=False)
    finally:
        print(json.dumps({"stopped": True, "receipt": receipt(fixture)}, ensure_ascii=False), flush=True)
        fixture.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve() if ARGS.serve else check())
