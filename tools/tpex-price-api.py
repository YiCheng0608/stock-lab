"""Guarded memory checks/router preview; private files require explicit scoped opt-in."""
from __future__ import annotations
import argparse
import ast
import base64
import ctypes
from contextlib import ExitStack
from datetime import date
import json
import os
from pathlib import Path
import socket
import stat
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
mode.add_argument("--saved-focus-check", action="store_true")
mode.add_argument("--private-save-check", action="store_true")
mode.add_argument("--serve", action="store_true")
parser.add_argument("--port", type=int, default=8795)
parser.add_argument("--live-source-opt-in", action="store_true")
parser.add_argument("--policy-version")
parser.add_argument("--policy-digest")
parser.add_argument("--cutoff", choices=("2026-10-05", "2026-10-06"), default="2026-10-05")
parser.add_argument("--private-store-root")
parser.add_argument("--private-policy-version")
parser.add_argument("--private-policy-digest")
parser.add_argument("--saved-source-only", action="store_true")
parser.add_argument("--saved-focus-policy-version")
parser.add_argument("--saved-focus-policy-digest")
parser.add_argument("--disk-phase", choices=("check", "write", "read", "faults", "cleanup"), default="check")
ARGS = parser.parse_args()
if ARGS.live_source_opt_in and not ARGS.serve:
    parser.error("live source is only admitted in root-owned serve")
if not 1024 <= ARGS.port <= 65535:
    parser.error("invalid owned port")
PRIVATE_ROOT = Path(ARGS.private_store_root).absolute() if ARGS.private_store_root else None
PRIVATE_PARENT = Path(os.environ.get("LOCALAPPDATA", "")) / "taiwan-stock-research"
PRODUCT_ROOT = PRIVATE_PARENT / "price-save-01a11367"
TEST_ROOT = PRIVATE_PARENT / "price-save-tests-01a11367"
if PRIVATE_ROOT:
    if PRIVATE_ROOT != (TEST_ROOT if ARGS.private_save_check else PRODUCT_ROOT) or not (ARGS.private_save_check or ARGS.serve):
        parser.error("private root outside exact owned scope")
    if (ARGS.private_policy_version, ARGS.private_policy_digest) != ("m1-price-save-tpex-11370-2026-10-06.1", "sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e"):
        parser.error("independently accepted private storage pins required")
elif ARGS.private_save_check or ARGS.saved_source_only or ARGS.disk_phase != "check":
    parser.error("explicit private root required")
if ARGS.saved_source_only and (not ARGS.serve or ARGS.live_source_opt_in):
    parser.error("saved-source-only requires serve and excludes source acquisition")
SAVED_FOCUS_ACTIVE = bool(ARGS.saved_focus_policy_version or ARGS.saved_focus_policy_digest)
if SAVED_FOCUS_ACTIVE and (not ARGS.saved_source_only or
        (ARGS.saved_focus_policy_version, ARGS.saved_focus_policy_digest) !=
        ("m1-saved-price-focus-tpex-11370-2026-10-06.1", "sha256:93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b")):
    parser.error("saved focus requires saved-source-only and independently admitted consumer pins")
if ARGS.disk_phase != "check" and not ARGS.private_save_check:
    parser.error("disk phases are private synthetic checks only")
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests"), str(Path(ARGS.deps).resolve())]
COUNTS = {"disk_writes": 0, "mutations": 0, "unapproved_network": 0, "subprocesses": 0}
ALLOWED_DISK = {"writes": 0, "mutations": 0}
PRIVATE_DIRECTORY = "tpex-11370-2026-10-06-m1-v1"
PRIVATE_STAGING = ".pending-" + PRIVATE_DIRECTORY
PRIVATE_FILES = {"body.csv", "capture-receipt.json", "storage-receipt.json"}
DISK_ACTIVE = bool(PRIVATE_ROOT and (ARGS.serve or ARGS.disk_phase != "check") and not ARGS.saved_source_only)
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
            if DISK_ACTIVE and (approved_private_path(args[0], file=True) or approved_private_fd(args[0])):
                ALLOWED_DISK["writes"] += 1
            else:
                COUNTS["disk_writes"] += 1
                raise AssertionError("disk write denied")
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "tempfile.mkstemp", "tempfile.mkdtemp"}:
        allowed = DISK_ACTIVE and event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link"}
        if event == "os.rename":
            allowed = allowed and approved_private_path(args[0]) and approved_private_path(args[1])
        elif event == "os.link":
            allowed = allowed and ARGS.private_save_check and approved_private_path(args[0], file=True) and approved_private_path(args[1], file=True)
        else:
            allowed = allowed and approved_private_path(args[0], parent=event in {"os.mkdir", "os.rmdir"})
        if allowed:
            ALLOWED_DISK["mutations"] += 1
        else:
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


def approved_private_path(value, *, file=False, parent=False):
    if not isinstance(value, (str, bytes, os.PathLike)) or isinstance(value, bytes):
        return False
    path = Path(value).absolute()
    if parent and path == PRIVATE_PARENT:
        return True
    if not PRIVATE_ROOT or not path.is_relative_to(PRIVATE_ROOT):
        return False
    parts = path.relative_to(PRIVATE_ROOT).parts
    if not parts:
        return not file
    if parts[0] not in {PRIVATE_DIRECTORY, PRIVATE_STAGING}:
        return False
    if len(parts) == 1:
        return not file
    return len(parts) == 2 and parts[1] in PRIVATE_FILES | ({"probe.json"} if ARGS.private_save_check else set())


def approved_private_fd(value):
    if type(value) is not int or os.name != "nt":
        return False
    import msvcrt
    try:
        info = os.fstat(value)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 1024:
            return False
        function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
        function.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        function.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(msvcrt.get_osfhandle(value), buffer, len(buffer), 0)
        return 0 < length < len(buffer) and approved_private_path(buffer.value.removeprefix("\\\\?\\"), file=True)
    except (OSError, ValueError):
        return False


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


def database_snapshot(fixture):
    """All memory tables: schema, stored values and every SQLite cell typeof."""
    with fixture.engine.connect() as connection:
        names = [row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result = {}
        for name in names:
            table = '"' + name.replace('"', '""') + '"'
            schema = [tuple(row) for row in connection.exec_driver_sql('PRAGMA table_info(' + table + ')')]
            definitions = [tuple(row) for row in connection.exec_driver_sql(
                "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name=? ORDER BY type,name", (name,))]
            columns = ['"' + row[1].replace('"', '""') + '"' for row in schema]
            values = [tuple(row) for row in connection.exec_driver_sql('SELECT * FROM ' + table + ' ORDER BY rowid')]
            types = [tuple(row) for row in connection.exec_driver_sql('SELECT ' + ','.join('typeof(' + column + ')' for column in columns) + ' FROM ' + table + ' ORDER BY rowid')]
            result[name] = {"schema": {"columns": schema, "definitions": definitions}, "values": values, "cell_typeofs": types}
        return result


def saved_consumer_fixture():
    """Seven verified identities only; zero seeded finance, no private read at startup."""
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app import api
    from app.db import Base
    from app.models import Instrument
    from app.price_saved_focus import focus_policy
    fixture = MemoryAPIFixture.__new__(MemoryAPIFixture)
    fixture.api, fixture.wrapper, fixture.fixture = api, tpex_price, None
    fixture.stack = ExitStack()
    fixture.catalogue_kind = "memory ordinary identity catalogue; finance_seed_rows=0; actual private raw read only after explicit product action"
    fixture.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(fixture.engine)
    with Session(fixture.engine) as db:
        for symbol, name in focus_policy()["scope"]["symbols"].items():
            db.add(Instrument(exchange="TPEx", symbol=symbol, name=name, instrument_type="stock", market="TW", etf_category=None))
        db.commit()
    fixture.app = FastAPI()
    fixture.app.include_router(api.router)
    def database():
        with Session(fixture.engine) as db:
            yield db
    fixture.app.dependency_overrides[api.get_db] = database
    fixture.store = tpex_price.TpexPriceStore()
    fixture.stack.enter_context(patch.object(tpex_price, "STORE", fixture.store))
    fixture.stack.enter_context(patch.dict(os.environ, {tpex_price.ENABLE_ENV: "0", tpex_price.POLICY_VERSION_ENV: ARGS.policy_version,
        tpex_price.POLICY_DIGEST_ENV: ARGS.policy_digest}))
    fixture.before = fixture.snapshot()
    return fixture


def receipt(fixture=None, include_raw=False):
    import fastapi, sqlalchemy, httpx
    result = {"pid": os.getpid(), "runtime": {"python": sys.version.split()[0], "fastapi": fastapi.__version__, "sqlalchemy": sqlalchemy.__version__, "httpx": httpx.__version__},
              "guard": dict(COUNTS), "allowed_private_disk": dict(ALLOWED_DISK), "disk_artifacts": private_disk_metrics(), "source_requests": list(SOURCE_REQUESTS),
              "source_request_count": len(SOURCE_REQUESTS), "runner_source_request_count": RUNNER_SOURCE_REQUESTS, "preloaded_source": PRELOADED_SOURCE,
              "policy_version": tpex_price.policy_pins(date.fromisoformat(ARGS.cutoff), policy_version=ARGS.policy_version)[0], "policy_digest": tpex_price.policy_pins(date.fromisoformat(ARGS.cutoff), policy_version=ARGS.policy_version)[1],
              "scope": "tuple-scoped ordinary TPEx stocks, " + ARGS.cutoff + ", single day; no history/MA20/PIT; "
                  + ("scoped private save/reopen enabled; helper receipt does not prove product acceptance" if PRIVATE_ROOT
                     else "process memory only, no disk save/reopen"),
              "private_storage": {"enabled": bool(PRIVATE_ROOT), "saved_source_only": ARGS.saved_source_only,
                  "policy_version": ARGS.private_policy_version, "policy_digest": ARGS.private_policy_digest}}
    if fixture:
        raw = fixture.store.raw_capture
        result["db_preserved"] = fixture.before == fixture.snapshot()
        result["capture_state"] = fixture.store.read("TPEx", "3105", date.fromisoformat(ARGS.cutoff), instrument_type="stock", currency="TWD")["capture_state"]
        result["capture_receipt"] = raw.receipt if raw else None
        result["selected"] = raw.parsed["selected"] if raw else None
        result["fixture_kind"] = fixture.catalogue_kind + ("; retained independently admitted private source, explicit read only" if SAVED_FOCUS_ACTIVE else
            "; live admitted source" if ARGS.live_source_opt_in or PRELOADED_SOURCE else "; synthetic private test anchors; not official raw")
        if SAVED_FOCUS_ACTIVE:
            current = database_snapshot(fixture)
            before = fixture.validation_baseline
            result["database_preservation"] = {"table_count": len(current), "schema_preserved": set(before) == set(current) and all(before[name]["schema"] == current[name]["schema"] for name in before),
                "all_values_preserved": set(before) == set(current) and all(before[name]["values"] == current[name]["values"] for name in before),
                "cell_typeofs_preserved": set(before) == set(current) and all(before[name]["cell_typeofs"] == current[name]["cell_typeofs"] for name in before)}
            result["finance_seed_rows"] = 0
            result["empty_store"] = raw is None and not fixture.store._attempted and fixture.store._request_count == 0
        if include_raw:
            result["raw_base64"] = base64.b64encode(raw.body).decode("ascii") if raw else None
            result["receipt_base64"] = base64.b64encode(raw.receipt_bytes).decode("ascii") if raw else None
    if SAVED_FOCUS_ACTIVE:
        from app.price_saved_focus import read_diagnostics
        result["saved_focus_consumer"] = read_diagnostics()
    return result


def private_disk_metrics():
    if not PRIVATE_ROOT or not PRIVATE_ROOT.exists():
        return 0
    def plain_directory(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise AssertionError("unsafe private metrics directory")
    plain_directory(PRIVATE_ROOT)
    folders = list(PRIVATE_ROOT.iterdir())
    if len(folders) > 2 or any(folder.name not in {PRIVATE_DIRECTORY, PRIVATE_STAGING} for folder in folders):
        raise AssertionError("private metrics unexpected root entries")
    sizes = {}
    for folder in folders:
        plain_directory(folder)
        children = list(folder.iterdir())
        if len(children) > 6:
            raise AssertionError("private metrics bounded entries exceeded")
        for item in children:
            info = item.lstat()
            if (item.name not in PRIVATE_FILES | ({"probe.json"} if ARGS.private_save_check else set())
                    or not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024):
                raise AssertionError("unsafe private metrics file")
            sizes[str(item.relative_to(PRIVATE_ROOT))] = info.st_size
    directories = 1 + len(folders)
    limit = 262144 if ARGS.private_save_check else 3170304
    if len(sizes) > (6 if ARGS.private_save_check else 3) or directories > 3 or sum(sizes.values()) > limit:
        raise AssertionError("private owned disk quota exceeded")
    return {"files": len(sizes), "directories": directories, "bytes": sum(sizes.values()), "sizes": sizes}


def check():
    if ARGS.private_save_check:
        from test_tpex_price_saved import run_phase
        result = run_phase(ARGS.disk_phase, PRIVATE_ROOT)
        output = receipt()
        output.update(private_save=result, disk_phase=ARGS.disk_phase)
        print(json.dumps(output, ensure_ascii=False), flush=True)
        return 0 if result["passed"] and not any(COUNTS.values()) else 1
    suite = unittest.TestSuite()
    for name in (("test_price_saved_focus",) if ARGS.saved_focus_check else ("test_price_focus",) if ARGS.focus_check else ("test_tpex_price_capture", "test_tpex_price_store", "test_tpex_price_api")):
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
    if (ARGS.live_source_opt_in or preloaded_store is not None or ARGS.saved_source_only) and (ARGS.policy_version, ARGS.policy_digest) != tpex_price.policy_pins(cutoff, policy_version=ARGS.policy_version):
        raise ValueError("external accepted policy pins required for live preview")
    fixture = saved_consumer_fixture() if SAVED_FOCUS_ACTIVE else MemoryAPIFixture(live=ARGS.live_source_opt_in or preloaded_store is not None or ARGS.saved_source_only, cutoff=cutoff, policy_version=ARGS.policy_version)
    if SAVED_FOCUS_ACTIVE:
        fixture.validation_baseline = database_snapshot(fixture)
    if PRIVATE_ROOT:
        from app import tpex_price_saved
        fixture.stack.enter_context(patch.dict(os.environ, {tpex_price_saved.ENABLE_ENV: "1", tpex_price_saved.ROOT_ENV: str(PRIVATE_ROOT),
            tpex_price_saved.VERSION_ENV: ARGS.private_policy_version, tpex_price_saved.DIGEST_ENV: ARGS.private_policy_digest}))
    if ARGS.saved_source_only:
        if preloaded_store is not None:
            raise ValueError("reopen uses a new empty Store, not preloaded memory")
        fixture.stack.enter_context(patch.dict(os.environ, {tpex_price.ENABLE_ENV: "0"}))
        def no_source(**kwargs):
            raise AssertionError("saved-source-only must never call a source loader")
        fixture.store._loader = no_source
    if SAVED_FOCUS_ACTIVE:
        from app import price_saved_focus as focus
        fixture.stack.enter_context(patch.dict(os.environ, {focus.ENABLE_ENV: "1", focus.VERSION_ENV: ARGS.saved_focus_policy_version,
            focus.DIGEST_ENV: ARGS.saved_focus_policy_digest}))
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
        save_paths = {f"/api/stocks/TPEx/{symbol}/prices/save" for symbol in worker.policy_symbols(cutoff, policy_version=ARGS.policy_version)} if PRIVATE_ROOT else set()
        post_paths = set() if ARGS.saved_source_only else capture_paths | save_paths | {"/api/focus/price-lots/capture"}
        # All private reads in the new mode pass through the consumer's shared budget.
        if SAVED_FOCUS_ACTIVE and request.url.path.endswith("/prices/saved"):
            return JSONResponse({"detail": "use the admitted saved-focus reader"}, status_code=405)
        allowed = request.method in {"GET", "OPTIONS"} or (request.method == "POST" and request.url.path in post_paths)
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
