"""Synthetic 2026-10-03 user quantities through the real router, memory only.

Direct -B -X utf8 execution avoids pytest/conftest, app.main, initialization and
migrations. --serve permits portfolio writes only in this owned memory fixture.
Commit/refresh/GET evidence is not a disk-save or reopen acceptance.
"""
from __future__ import annotations

import argparse
import ast
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import types
import unittest

STANDALONE = __name__ == "__main__"
DAY = date(2026, 10, 3)
SAFE = 9007199254740991
MAXIMUM = 9223372036854775807
EXPECTED_DENIALS = []
UNEXPECTED_DENIALS = []
_expected_probe = False
_listen_port = None
HTTP_REQUESTS = 0
CASES = {"ZERO0": 0, "LOT1": 1000, "MIXED": 1500, "SAFE": SAFE,
         "ODDFLOAT": float(9007199254740993), "MAXFLOAT": float(MAXIMUM)}


def _socketpair_context():
    frame = sys._getframe(1)
    while frame:
        if "socketpair" in frame.f_code.co_name and frame.f_code.co_filename.endswith("socket.py"):
            return True
        frame = frame.f_back
    return False


def _audit(event, args):
    forbidden = event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink",
                          "os.truncate", "os.chmod", "os.utime", "os.system", "subprocess.Popen",
                          "os.posix_spawn", "os.exec", "os.fork", "os.startfile", "socket.sendto", "socket.sendmsg"}
    if event == "open":
        mode, flags = args[1:3]
        forbidden = (isinstance(mode, str) and any(char in mode for char in "wax+")) or bool(
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    if event in {"socket.bind", "socket.connect"}:
        address = args[1]
        local = isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
        pair = local and _socketpair_context()
        owned = event == "socket.bind" and local and address[1] == _listen_port and _listen_port is not None
        forbidden = not (pair or owned)
    if event == "socket.getaddrinfo":
        forbidden = args[0] not in {"localhost", "127.0.0.1", "::1", None}
    if event in {"socket.gethostbyname", "socket.gethostbyaddr"}:
        forbidden = args[0] not in {"localhost", "127.0.0.1", "::1"}
    if forbidden:
        (EXPECTED_DENIALS if _expected_probe else UNEXPECTED_DENIALS).append(event)
        raise PermissionError("memory-only validation denied " + event)


if STANDALONE:
    sys.dont_write_bytecode = True
    config_path = Path(__file__).resolve().parents[1] / "app" / "config.py"
    config_ast = ast.parse(config_path.read_text(encoding="utf-8"), filename=str(config_path))
    config_ast.body = [node for node in config_ast.body if not (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "mkdir")]
    config_stub = types.ModuleType("app.config")
    config_stub.__file__ = str(config_path)
    exec(compile(config_ast, str(config_path), "exec"), config_stub.__dict__)
    config_stub.DATA_DIR = Path("__memory_only__")
    config_stub.RAW_DIR = config_stub.DATA_DIR / "raw"
    config_stub.DB_PATH = Path(":memory:")
    sys.modules["app.config"] = config_stub
    sys.addaudithook(_audit)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import api
from app.db import Base
from app.models import Instrument, MarketBar, PortfolioPosition
from app.units import share_quantity_dict, shares_from_position_quantity, split_shares


class MemoryFixture:
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.app = FastAPI()
        api.configure_cors(self.app)
        self.app.include_router(api.router)
        self.server = None
        with Session(self.engine) as db:
            for exchange in ("TWSE", "TPEx"):
                for symbol in (*CASES, "NEW"):
                    instrument = Instrument(market="TW", exchange=exchange, symbol=symbol,
                                            name="synthetic user quantity " + symbol,
                                            instrument_type="stock", status="active")
                    db.add(instrument)
                    db.flush()
                    db.add(MarketBar(instrument_id=instrument.id, trading_date=DAY,
                                     open=10, high=11, low=9, close=10.5, adj_close=10.5,
                                     volume=1000, turnover=10500, source="synthetic-user-quantity"))
                    if symbol in CASES:
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=CASES[symbol], average_cost=10))
            db.commit()

        def database():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[api.get_db] = database

        @self.app.middleware("http")
        async def owned_portfolio_only(request, call_next):
            global HTTP_REQUESTS
            HTTP_REQUESTS += 1
            portfolio_write = request.url.path == "/api/portfolio" and request.method == "POST"
            portfolio_delete = request.url.path.startswith("/api/portfolio/") and request.method == "DELETE"
            shutdown = request.url.path == "/__review__/shutdown" and request.method == "POST"
            if request.method not in {"GET", "OPTIONS"} and not (portfolio_write or portfolio_delete or shutdown):
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "only owned memory portfolio writes permitted"}, status_code=405)
            return await call_next(request)

        @self.app.post("/__review__/shutdown")
        def shutdown():
            if self.server is not None:
                self.server.should_exit = True
            return {"owned_memory_server": "stopping"}

    def close(self):
        self.app.dependency_overrides.clear()
        self.engine.dispose()


class ShareQuantityExactTest(unittest.TestCase):
    def test_pure_int64_and_safe_float_projection_have_distinct_bounds(self):
        cases = [(0, 0, 0, "0 股（零股）"), (1, 0, 1, "1 股（零股）"),
                 (999, 0, 999, "999 股（零股）"), (1000, 1, 0, "1 張"),
                 (1001, 1, 1, "1 張 1 股"),
                 (SAFE, 9007199254740, 991, "9,007,199,254,740 張 991 股"),
                 (9007199254740993, 9007199254740, 993, "9,007,199,254,740 張 993 股"),
                 (MAXIMUM, 9223372036854775, 807, "9,223,372,036,854,775 張 807 股")]
        for total, lots, remainder, display in cases:
            with self.subTest(total=total):
                self.assertEqual(split_shares(total), (lots, remainder))
                quantity = share_quantity_dict(total)
                self.assertEqual(quantity["total_shares"], total)
                self.assertEqual(quantity["total_shares_exact"], str(total))
                self.assertEqual(quantity["quantity_lots_exact"], str(lots))
                self.assertEqual(quantity["display"], display)
                if total <= SAFE:
                    self.assertEqual(share_quantity_dict(float(total)), quantity)
        for value in (None, True, False, "1", "1000", Decimal("1000"), -1, -1.0, 1.5,
                      float("nan"), float("inf"), float("-inf"), SAFE + 1.0,
                      float(9007199254740993), float(MAXIMUM), MAXIMUM + 1):
            with self.subTest(invalid=value):
                with self.assertRaises(ValueError):
                    share_quantity_dict(value)

    def test_actual_four_inputs_commit_refresh_and_get_in_memory(self):
        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        inputs = [({"shares": 1001}, "1001"), ({"unit": "lot", "quantity": 2}, "2000"),
                  ({"unit": "odd_lot", "quantity": 1500}, "1500"), ({"quantity_lots": 3}, "3000"),
                  ({"odd_lot_shares": 999}, "999"), ({"shares": SAFE}, str(SAFE)),
                  ({"unit": "odd_lot", "quantity": SAFE}, str(SAFE)),
                  ({"quantity_lots": 9007199254740}, "9007199254740000")]
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                for fields, expected in inputs:
                    with self.subTest(exchange=exchange, fields=fields):
                        response = client.post("/api/portfolio", json={"symbol": "NEW", "exchange": exchange,
                                                                     "average_cost": 10, **fields})
                        self.assertEqual(response.status_code, 200, response.text)
                        payload = response.json()
                        self.assertEqual(payload["shares_exact"], expected)
                        self.assertEqual(payload["quantity"]["total_shares_exact"], expected)
                        with Session(fixture.engine) as db:
                            stored = db.get(PortfolioPosition, payload["id"])
                            self.assertIs(type(stored.shares), float)
                            self.assertEqual(stored.shares, int(expected))
                        read = client.get("/api/portfolio?q=NEW").json()["items"]
                        row = next(item for item in read if item["id"] == payload["id"])
                        self.assertEqual(row["shares_exact"], expected)
                        self.assertEqual(row["market_value"], 10.5 * int(expected))
                        self.assertEqual(row["unrealized_pnl"], 10.5 * int(expected) - 10 * int(expected))

    def test_invalid_input_refuses_before_commit_and_retains_existing_position(self):
        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        invalid = [{}, {"unit": "wrong", "quantity": 1}, {"unit": "lot"},
                   {"shares": 1, "quantity_lots": 1}, {"unit": "lot", "quantity": 1, "odd_lot_shares": 1},
                   {"shares": 1, "unit": "lot"}, {"quantity": 1}, {"quantity_lots": 1, "unit": "lot"}]
        for field in ("shares", "quantity", "quantity_lots", "odd_lot_shares"):
            for value in (None, True, False, 0, -1, 1.5, "1", SAFE + 1, 9007199254740993, MAXIMUM):
                invalid.append({field: value, **({"unit": "odd_lot"} if field == "quantity" else {})})
        invalid += [{"unit": "lot", "quantity": 9007199254741}, {"quantity_lots": 9007199254741}]
        with TestClient(fixture.app) as client:
            baseline = client.get("/api/portfolio?q=MIXED").json()["items"][0]
            for fields in invalid:
                with self.subTest(fields=fields):
                    response = client.post("/api/portfolio", json={"symbol": "MIXED", "exchange": "TWSE",
                                                                 "average_cost": 999, **fields})
                    self.assertEqual(response.status_code, 422, response.text)
                    row = client.get("/api/portfolio?q=MIXED").json()["items"][0]
                    self.assertEqual(row, baseline)
            # Raw invalid JSON numbers bypass the convenience client's encoder.
            for token in ("NaN", "Infinity", "-Infinity", "1e400"):
                response = client.post("/api/portfolio", content='{"symbol":"MIXED","exchange":"TWSE","shares":' + token + '}',
                                       headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(client.get("/api/portfolio?q=MIXED").json()["items"][0], baseline)

    def test_unsafe_legacy_float_get_is_unknown_and_delete_remains_explicit(self):
        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        with Session(fixture.engine) as db:
            for index, value in enumerate((-1.0, 1.5, float("inf"), float("-inf"))):
                instrument = Instrument(market="TW", exchange="TWSE", symbol=f"BAD{index}", name="synthetic invalid",
                                        instrument_type="stock", status="active")
                db.add(instrument)
                db.flush()
                db.add(PortfolioPosition(instrument_id=instrument.id, shares=value, average_cost=10))
            db.commit()
        with TestClient(fixture.app) as client:
            response = client.get("/api/portfolio?page_size=100")
            self.assertEqual(response.status_code, 200, response.text)
            for row in response.json()["items"]:
                symbol = row["instrument"]["symbol"]
                if symbol in {"ODDFLOAT", "MAXFLOAT"} or symbol.startswith("BAD"):
                    self.assertIsNone(row["shares_exact"])
                    self.assertIsNone(row["quantity"])
                elif symbol == "SAFE":
                    self.assertEqual(row["shares_exact"], str(SAFE))
                    self.assertEqual(row["quantity"]["display"], "9,007,199,254,740 張 991 股")
                elif symbol == "ZERO0":
                    self.assertEqual(row["shares_exact"], "0")
            unsafe_id = next(row["id"] for row in response.json()["items"] if row["instrument"]["symbol"] == "ODDFLOAT")
            self.assertEqual(client.delete(f"/api/portfolio/{unsafe_id}").status_code, 200)
            self.assertEqual(client.delete(f"/api/portfolio/{unsafe_id}").status_code, 404)
            self.assertFalse(any(row["id"] == unsafe_id for row in client.get("/api/portfolio?page_size=100").json()["items"]))
        # Null/NaN cannot be persisted to this non-null Float column; exercise
        # serialization directly without claiming those states as SQLite rows.
        with Session(fixture.engine) as db:
            instrument = db.scalar(select(Instrument).where(Instrument.symbol == "NEW", Instrument.exchange == "TWSE"))
            for value in (None, float("nan"), True):
                payload = api.position_dict(db, PortfolioPosition(instrument_id=instrument.id, shares=value, average_cost=10))
                self.assertIsNone(payload["shares_exact"])
                self.assertIsNone(payload["quantity"])
                self.assertIsNone(payload["shares"])
                self.assertIsNone(payload["market_value"])

    @unittest.skipUnless(STANDALONE, "audit probes are limited to the guarded direct runner")
    def test_audit_denies_disk_external_network_and_subprocess(self):
        global _expected_probe
        import socket
        import subprocess
        _expected_probe = True
        try:
            for action in (lambda: os.mkdir("__share_quantity_forbidden__"), lambda: open("__share_quantity_forbidden__", "w"),
                           lambda: socket.getaddrinfo("example.com", 443), lambda: subprocess.run([sys.executable, "--version"]),
                           lambda: sys.audit("socket.sendto", None, ("192.0.2.1", 53))):
                with self.assertRaises(PermissionError):
                    action()
        finally:
            _expected_probe = False


def main():
    global _listen_port
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()
    if args.serve:
        if args.port != 8777:
            parser.error("only owned loopback port 8777 is authorized")
        _listen_port = args.port
        fixture = MemoryFixture()
        try:
            import uvicorn
            fixture.server = uvicorn.Server(uvicorn.Config(fixture.app, host="127.0.0.1", port=args.port,
                                                          lifespan="off", access_log=False))
            print(json.dumps({"mode": "synthetic-user-quantity-memory-actual-router", "fixture_date": str(DAY),
                              "pid": os.getpid(), "url": f"http://127.0.0.1:{args.port}", "disk_artifacts": 0,
                              "disk_save_reopen": "not_tested"}), flush=True)
            fixture.server.run()
        finally:
            fixture.close()
    else:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ShareQuantityExactTest))
        success = result.wasSuccessful() and not UNEXPECTED_DENIALS
        print(json.dumps({"tests": result.testsRun, "success": success, "fixture_date": str(DAY),
                          "actual_router_requests": HTTP_REQUESTS, "disk_artifacts": 0,
                          "expected_denials": EXPECTED_DENIALS, "unexpected_denials": UNEXPECTED_DENIALS,
                          "disk_save_reopen": "not_tested"}), flush=True)
        return 0 if success else 1
    print(json.dumps({"owned_memory_server": "closed", "unexpected_denials": UNEXPECTED_DENIALS}), flush=True)
    return 0 if not UNEXPECTED_DENIALS else 1


if __name__ == "__main__":
    raise SystemExit(main())
