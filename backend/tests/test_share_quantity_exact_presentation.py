"""Synthetic 2026-10-03 user quantities through the real router, memory only.

Direct -B -X utf8 execution avoids pytest/conftest, app.main, initialization and
migrations. --serve permits portfolio writes only in this owned memory fixture.
Commit/refresh/GET evidence is not a disk-save or reopen acceptance.
"""
from __future__ import annotations

import argparse
import ast
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import types
import unittest

STANDALONE = __name__ == "__main__"
DAY = date(2026, 10, 3)
READ_DAY = date(2026, 10, 4)
SAFE = 9007199254740991
MAXIMUM = 9223372036854775807
EXPECTED_DENIALS = []
UNEXPECTED_DENIALS = []
_expected_probe = False
_listen_port = None
HTTP_REQUESTS = 0
CASES = {"ZERO0": 0, "LOT1": 1000, "MIXED": 1500, "SAFE": SAFE,
          "ODDFLOAT": float(9007199254740993), "MAXFLOAT": float(MAXIMUM)}
READ_VALUES = {"MISSING": None, "ZERO": 0, "NORMAL": 12.5, "NEGATIVE": -1,
               "INFINITY": float("inf"), "TEXT": "malformed-value", "BLOB": b"malformed-value"}
VALUE_FIELDS = ("average_cost", "stop_price", "risk_budget")


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
    if event == "sqlite3.connect":
        forbidden = str(args[0]) != ":memory:"
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
    sys.addaudithook(_audit)
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

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import api
from app.db import Base
from app.models import IngestionRun, Instrument, MarketBar, PortfolioPosition, Signal, StrategyVersion
from app.portfolio_values import read_portfolio_value
from app.units import share_quantity_dict, shares_from_position_quantity, split_shares
from app.units import position_held, trusted_position_shares


# Sixteen UI records keep both exchanges inside the first portfolio page.
# Additional affinity/boundary cases mutate one owned record in direct tests.
QUANTITY_READS = {
    "INTPOS": (0, 1000), "INTZERO": (1000, 0), "LEGZERO": (0, None),
    "BADINT": (1000, "malformed-integer"), "UNSAFE": (float(9007199254740993), None),
    "ODD": (float(9007199254740993), 9007199254740993),
    "MAX": (float(MAXIMUM), MAXIMUM), "GATEFAIL": (1000, "malformed-integer"),
}


class MemoryFixture:
    def __init__(self, *, value_reads=False, quantity_trust=False):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.app = FastAPI()
        api.configure_cors(self.app)
        self.app.include_router(api.router)
        self.server = None
        with Session(self.engine) as db:
            for exchange in ("TWSE", "TPEx"):
                for symbol in ((*QUANTITY_READS, "ABSENT") if quantity_trust else READ_VALUES if value_reads else (*CASES, "NEW")):
                    instrument = Instrument(market="TW", exchange=exchange, symbol=symbol,
                                            name="synthetic user quantity " + symbol,
                                            instrument_type="stock", status="active")
                    db.add(instrument)
                    db.flush()
                    db.add(MarketBar(instrument_id=instrument.id, trading_date=READ_DAY if value_reads or quantity_trust else DAY,
                                     open=10, high=11, low=9, close=10.5, adj_close=10.5,
                                      volume=1000, turnover=10500, source="fixture-portfolio-quantity-trust" if quantity_trust else "fixture-portfolio-value-read" if value_reads else "synthetic-user-quantity"))
                    if quantity_trust and symbol != "ABSENT":
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=1000, shares_integer=1000,
                            average_cost=10, note="synthetic quantity trust; whole row retained", updated_at=datetime(2026, 10, 4)))
                    elif value_reads:
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=1000, shares_integer=1000,
                            average_cost=10, note="whole row retained", updated_at=datetime(2026, 10, 4)))
                    elif symbol in CASES:
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=CASES[symbol], average_cost=10))
            db.commit()

        if value_reads or quantity_trust:
            self.seed_value_reads()
        if quantity_trust:
            self.seed_quantity_reads()

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
            if request.method not in {"GET", "OPTIONS"} and not (shutdown or (
                    not (value_reads or quantity_trust) and (portfolio_write or portfolio_delete))):
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "only owned memory portfolio writes permitted"}, status_code=405)
            return await call_next(request)

        if value_reads:
            @self.app.get("/__review__/value-read-snapshot")
            def value_read_snapshot():
                # A fixture-only digest covers complete SQL rows and typeof(),
                # without echoing the malformed values through product JSON.
                rows = self.raw_position_rows()
                return {"whole_row_sha256": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(),
                        "row_count": len(rows), "includes": ["all columns", "note", "updated_at", "three typeof()"],
                        "fixture_date": str(READ_DAY), "storage": "memory_only"}

        if quantity_trust:
            @self.app.get("/__review__/quantity-trust-snapshot")
            def quantity_trust_snapshot():
                rows = self.raw_quantity_rows()
                return {"whole_row_sha256": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(),
                        "row_count": len(rows), "includes": ["all columns", "note", "updated_at", "two quantity typeof()"],
                        "fixture_date": str(READ_DAY), "storage": "memory_only"}

        @self.app.post("/__review__/shutdown")
        def shutdown():
            if self.server is not None:
                self.server.should_exit = True
            return {"owned_memory_server": "stopping"}

    def close(self):
        self.app.dependency_overrides.clear()
        self.engine.dispose()

    def raw_position_rows(self):
        with self.engine.connect() as connection:
            return [tuple(row) for row in connection.exec_driver_sql(
                "SELECT *, typeof(average_cost), typeof(stop_price), typeof(risk_budget) "
                "FROM portfolio_positions ORDER BY id")]

    def raw_quantity_rows(self):
        with self.engine.connect() as connection:
            return [tuple(row) for row in connection.exec_driver_sql(
                "SELECT *, typeof(shares), typeof(shares_integer) FROM portfolio_positions ORDER BY id")]

    def seed_quantity_reads(self):
        with self.engine.begin() as connection:
            for symbol, (legacy, integer) in QUANTITY_READS.items():
                connection.exec_driver_sql("UPDATE portfolio_positions SET shares=?, shares_integer=? "
                    "WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol=?)", (legacy, integer, symbol))
            connection.exec_driver_sql("UPDATE signals SET data_quality='partial' WHERE instrument_id IN "
                                      "(SELECT id FROM instruments WHERE symbol='GATEFAIL')")

    def seed_value_reads(self):
        # Real SQLite affinity and SQLAlchemy Float result handling are part of
        # this read fixture. ORM Float bind coercion cannot seed TEXT or BLOB.
        with self.engine.begin() as connection:
            for symbol, value in READ_VALUES.items():
                connection.exec_driver_sql(
                    "UPDATE portfolio_positions SET average_cost=?, stop_price=?, risk_budget=? "
                    "WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol=?)",
                    (value, value, value, symbol))
        with Session(self.engine) as db:
            instruments = list(db.scalars(select(Instrument)))
            taiex = Instrument(market="TW", exchange="TWSE", symbol="TAIEX", name="Explicit synthetic sessions",
                               instrument_type="index", status="active")
            version = StrategyVersion(name="breakout_v1", version="1.0.0", kind="technical",
                                      config_json={}, canonical_config_snapshot={})
            db.add_all([taiex, version, IngestionRun(run_type="collect", source="official", run_date=READ_DAY,
                status="success", records=0, data_as_of=str(READ_DAY), request_key="portfolio-value-read-fixture")])
            db.flush()
            # Sixty explicitly named fixture sessions satisfy the existing
            # coverage consumer; no production completeness gate is patched.
            for index in range(60):
                trading_date = READ_DAY - timedelta(days=index)
                for instrument in [taiex, *instruments]:
                    if index == 0 and instrument is not taiex:
                        continue
                    db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date,
                        open=10, high=11, low=9, close=10.5, adj_close=10.5, volume=1000, turnover=10500,
                        source="fixture-portfolio-value-read"))
            for instrument in instruments:
                db.add(Signal(signal_key=f"read-fixture-{instrument.id}", signal_date=READ_DAY,
                    instrument_id=instrument.id, strategy_version_id=version.id, status="conditional",
                    data_quality="complete", entry_type="conditional", breakout_price=12,
                    invalid_price=8, target_1=20, data_cutoff=str(READ_DAY),
                    earliest_execution_date=READ_DAY + timedelta(days=1),
                    rule_evidence_json={"inputs": {"group_excess_return_20d": 0.1,
                        "institutional_flow_to_turnover_ratio_5d": 0.01, "margin_balance_change_ratio_5d": 0.02}}))
            db.commit()


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
                  ({"quantity_lots": 9007199254740}, "9007199254740000"),
                  ({"shares": "9007199254740993"}, "9007199254740993"),
                  ({"unit": "odd_lot", "quantity": str(MAXIMUM)}, str(MAXIMUM)),
                  ({"unit": "lot", "quantity": "9223372036854775"}, "9223372036854775000"),
                  ({"quantity_lots": "9223372036854775"}, "9223372036854775000"),
                  ({"odd_lot_shares": str(MAXIMUM)}, str(MAXIMUM))]
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
                            self.assertEqual(stored.shares, float(int(expected)))
                            self.assertIs(type(stored.shares_integer), int)
                            self.assertEqual(stored.shares_integer, int(expected))
                        read = client.get("/api/portfolio?q=NEW").json()["items"]
                        row = next(item for item in read if item["id"] == payload["id"])
                        self.assertEqual(row["shares_exact"], expected)
                        if int(expected) <= SAFE:
                            self.assertEqual(row["market_value"], 10.5 * int(expected))
                            self.assertEqual(row["unrealized_pnl"], 10.5 * int(expected) - 10 * int(expected))
                        else:
                            self.assertIsNone(row["market_value"])
                            self.assertIsNone(row["unrealized_pnl"])
                            self.assertEqual(row["valuation_status"], dict.fromkeys(
                                ("market_value", "unrealized_pnl"), "precision_unsupported"))

    def test_invalid_input_refuses_before_commit_and_retains_existing_position(self):
        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        invalid = [{}, {"unit": "wrong", "quantity": 1}, {"unit": "lot"},
                   {"shares": 1, "quantity_lots": 1}, {"unit": "lot", "quantity": 1, "odd_lot_shares": 1},
                   {"shares": 1, "unit": "lot"}, {"quantity": 1}, {"quantity_lots": 1, "unit": "lot"}]
        for field in ("shares", "quantity", "quantity_lots", "odd_lot_shares"):
            for value in (None, True, False, 0, -1, 1.5, "01", "0", "1\n", "9223372036854775808", SAFE + 1, 9007199254740993, MAXIMUM):
                invalid.append({field: value, **({"unit": "odd_lot"} if field == "quantity" else {})})
        invalid += [{"unit": "lot", "quantity": 9007199254741}, {"quantity_lots": 9007199254741},
                    {"quantity_lots": "9223372036854776"}, {"unit": "lot", "quantity": str(MAXIMUM)}]
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
        import sqlite3
        _expected_probe = True
        try:
            for action in (lambda: os.mkdir("__share_quantity_forbidden__"), lambda: open("__share_quantity_forbidden__", "w"),
                           lambda: socket.getaddrinfo("example.com", 443), lambda: subprocess.run([sys.executable, "--version"]),
                           lambda: sys.audit("socket.sendto", None, ("192.0.2.1", 53)),
                           lambda: sqlite3.connect("__share_quantity_forbidden__.db")):
                with self.assertRaises(PermissionError):
                    action()
        finally:
            _expected_probe = False


class PortfolioValueInputTest(unittest.TestCase):
    """Finite Float-compatible user values; no exact-money or legacy repair claim."""

    FIELDS = ("average_cost", "stop_price", "risk_budget")

    def fixture(self):
        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        return fixture

    def stored_rows(self, fixture):
        with Session(fixture.engine) as db:
            return [dict(row) for row in db.execute(
                select(PortfolioPosition.__table__).order_by(PortfolioPosition.id)).mappings()]

    def assert_safe_rejection(self, response, field):
        self.assertEqual(response.status_code, 422, response.text)

        def invalid_constant(token):
            raise AssertionError("nonfinite error JSON token: " + token)

        detail = json.loads(response.text, parse_constant=invalid_constant)["detail"]
        self.assertTrue(any(error["loc"][-1] == field for error in detail), detail)

    def test_nullable_zero_and_finite_values_save_as_float_in_both_markets(self):
        fixture = self.fixture()
        cases = [{field: value for field in self.FIELDS} for value in (None, 0, 0.0, 12, 12.5, 1e100)]
        cases.append({"average_cost": 10, "stop_price": 20, "risk_budget": 30})
        cases.append({})  # Omission remains full-row clearing, not PATCH.
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                for fields in cases:
                    with self.subTest(exchange=exchange, fields=fields):
                        response = client.post("/api/portfolio", json={"symbol": "NEW", "exchange": exchange,
                                                                     "shares": "9007199254740993", **fields})
                        self.assertEqual(response.status_code, 200, response.text)
                        row = response.json()
                        read = client.get("/api/portfolio?q=NEW").json()["items"]
                        self.assertEqual(next(item for item in read if item["id"] == row["id"]), row)
                        with Session(fixture.engine) as db:
                            stored = db.get(PortfolioPosition, row["id"])
                            self.assertEqual(stored.shares_integer, 9007199254740993)
                            for field in self.FIELDS:
                                value = fields.get(field)
                                self.assertEqual(row[field], value)
                                self.assertEqual(getattr(stored, field), value)
                                if value is not None:
                                    self.assertIs(type(getattr(stored, field)), float)
                            if fields.get("average_cost") == 0:
                                self.assertEqual(row["unrealized_pnl"], row["market_value"])
                            elif fields.get("average_cost") is None:
                                self.assertIsNone(row["unrealized_pnl"])

    def test_each_invalid_value_retains_entire_database_and_json_rows(self):
        fixture = self.fixture()
        invalid = (-1, -0.5, True, False, "0", "12.5", "Infinity", "NaN", "", [], {}, [1], {"value": 1}, 10**400)
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                saved = client.post("/api/portfolio", json={"symbol": "MIXED", "exchange": exchange,
                    "shares": "9007199254740993", "average_cost": 10, "stop_price": 9, "risk_budget": 100,
                    "note": "retained whole row"})
                self.assertEqual(saved.status_code, 200, saved.text)
            baseline_json = client.get("/api/portfolio?page_size=100").json()
            baseline_db = self.stored_rows(fixture)
            for exchange in ("TWSE", "TPEx"):
                for field in self.FIELDS:
                    for value in invalid:
                        with self.subTest(exchange=exchange, field=field, value=value):
                            response = client.post("/api/portfolio", json={"symbol": "MIXED", "exchange": exchange,
                                "shares": "9223372036854775807", "average_cost": 90, "stop_price": 80,
                                "risk_budget": 70, "note": "must not replace", field: value})
                            self.assert_safe_rejection(response, field)
                            self.assertEqual(self.stored_rows(fixture), baseline_db)
                            self.assertEqual(client.get("/api/portfolio?page_size=100").json(), baseline_json)

    def test_raw_nonfinite_and_nested_values_reject_with_safe_json_and_no_add(self):
        fixture = self.fixture()
        tokens = ("NaN", "Infinity", "-Infinity", "1e400", "-1e400", "[Infinity]", '{"value":NaN}')
        with TestClient(fixture.app) as client:
            baseline_json = client.get("/api/portfolio?page_size=100").json()
            baseline_db = self.stored_rows(fixture)
            for symbol in ("MIXED", "NEW", "UNKNOWN"):
                for field in self.FIELDS:
                    for token in tokens:
                        with self.subTest(symbol=symbol, field=field, token=token):
                            content = '{"symbol":"' + symbol + '","exchange":"TWSE","shares":1,"' + field + '":' + token + '}'
                            response = client.post("/api/portfolio", content=content, headers={"Content-Type": "application/json"})
                            self.assert_safe_rejection(response, field)
                            self.assertEqual(self.stored_rows(fixture), baseline_db)
                            self.assertEqual(client.get("/api/portfolio?page_size=100").json(), baseline_json)
            response = client.post("/api/portfolio", json={"symbol": "NEW", "exchange": "TPEx", "shares": 1,
                "average_cost": True, "stop_price": "9", "risk_budget": []})
            self.assert_safe_rejection(response, "average_cost")
            self.assert_safe_rejection(response, "stop_price")
            self.assert_safe_rejection(response, "risk_budget")
            self.assertEqual(self.stored_rows(fixture), baseline_db)


class PortfolioValueReadTest(unittest.TestCase):
    def fixture(self, *, value_reads=False):
        fixture = MemoryFixture(value_reads=value_reads)
        self.addCleanup(fixture.close)
        return fixture

    def safe_json(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        def invalid_constant(token):
            raise AssertionError("nonfinite product JSON token: " + token)
        return json.loads(response.text, parse_constant=invalid_constant)

    def test_read_classifier_keeps_missing_zero_and_invalid_distinct(self):
        for value in (0, -0.0, 12, 12.5, 1e308):
            self.assertEqual(read_portfolio_value(value), (float(value), "known"))
        self.assertEqual(read_portfolio_value(None), (None, "missing"))
        for value in (True, False, "0", "12.5", "", "Infinity", b"12.5", Decimal("12.5"),
                      [], {}, -1, -0.5, float("nan"), float("inf"), float("-inf"), 10**400):
            self.assertEqual(read_portfolio_value(value), (None, "invalid"))

    def test_actual_sqlite_orm_router_types_and_whole_rows_are_retained(self):
        fixture = self.fixture()
        cases = [(None, type(None), "missing"), (0, float, "known"), (12.5, float, "known"),
                 (1e308, float, "known"), (-1, float, "invalid"), (float("inf"), float, "invalid"),
                 (float("-inf"), float, "invalid"), ("malformed-value", str, "invalid"),
                 (b"malformed-value", bytes, "invalid"), (True, float, "known"),
                 ("12.5", float, "known"), (float("nan"), type(None), "missing")]
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                with Session(fixture.engine) as db:
                    instrument = db.scalar(select(Instrument).where(Instrument.exchange == exchange, Instrument.symbol == "MIXED"))
                    position_id = db.scalar(select(PortfolioPosition.id).where(PortfolioPosition.instrument_id == instrument.id))
                with fixture.engine.begin() as connection:
                    connection.exec_driver_sql("UPDATE portfolio_positions SET note='whole row retained', "
                                              "updated_at='2026-10-04 00:00:00.000000' WHERE id=?", (position_id,))
                for field in VALUE_FIELDS:
                    for value, expected_type, expected_status in cases:
                        with self.subTest(exchange=exchange, field=field, input_type=type(value).__name__, status=expected_status):
                            with fixture.engine.begin() as connection:
                                connection.exec_driver_sql(f"UPDATE portfolio_positions SET {field}=? WHERE id=?", (value, position_id))
                            before = fixture.raw_position_rows()
                            with Session(fixture.engine) as db:
                                loaded = getattr(db.get(PortfolioPosition, position_id), field)
                                self.assertIs(type(loaded), expected_type)
                                trusted, status = read_portfolio_value(loaded)
                                self.assertEqual(status, expected_status)
                            payload = self.safe_json(client.get("/api/portfolio?page_size=100"))
                            row = next(item for item in payload["items"] if item["id"] == position_id)
                            self.assertEqual(row["portfolio_value_status"][field], expected_status)
                            self.assertEqual(row[field], trusted)
                            self.assertEqual(row["note"], "whole row retained")
                            self.assertEqual(row["shares_exact"], "1500")
                            if field == "average_cost":
                                if status != "known" or loaded == 1e308:
                                    self.assertIsNone(row["unrealized_pnl"])
                                elif loaded == 0:
                                    self.assertEqual(row["unrealized_pnl"], row["market_value"])
                                else:
                                    self.assertEqual(row["unrealized_pnl"], (10.5 - trusted) * 1500)
                            self.assertEqual(fixture.raw_position_rows(), before)

    def test_actual_complete_decision_and_all_read_callers_keep_stop_origin(self):
        fixture = self.fixture(value_reads=True)
        cases = [(11, "reduce_exit", 11, "user_position_risk_input"),
                 (10.5, "reduce_exit", 10.5, "user_position_risk_input"),
                 (10, "hold_observe", 10, "user_position_risk_input"),
                 (0, "hold_observe", 0, "user_position_risk_input"),
                 (None, "hold_observe", 8, "rule_reference"),
                 (-1, "manual_review", None, "unknown"), (float("inf"), "manual_review", None, "unknown"),
                 (float("-inf"), "manual_review", None, "unknown"),
                 ("malformed-value", "manual_review", None, "unknown"),
                 (b"malformed-value", "manual_review", None, "unknown")]
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                for raw, state, stop, kind in cases:
                    with fixture.engine.begin() as connection:
                        connection.exec_driver_sql("UPDATE portfolio_positions SET stop_price=? WHERE instrument_id IN "
                            "(SELECT id FROM instruments WHERE exchange=? AND symbol='TEXT')", (raw, exchange))
                    before = fixture.raw_position_rows()
                    summary = self.safe_json(client.get(f"/api/actions/{exchange}/TEXT"))["decision_summary"]
                    self.assertEqual(summary["data_quality"], "complete")
                    self.assertEqual(summary["blocking_reasons"], [])
                    self.assertEqual(summary["action_state"], state)
                    self.assertEqual(summary["stop_price"], stop)
                    semantics = summary["stop_price_semantics"]
                    self.assertEqual(semantics["kind"], kind)
                    if state == "manual_review":
                        self.assertEqual(semantics["origin"], "portfolio_position.stop_price")
                        self.assertEqual(semantics["reason"], "invalid_position_stop")
                        self.assertEqual(summary["display_instruction"], "庫存停損待核實，先核對原記錄。")
                        self.assertEqual(summary["primary_reason"]["label"], summary["display_instruction"])
                        self.assertEqual(summary["conflicts"], [])
                    self.assertEqual(fixture.raw_position_rows(), before)
            before = fixture.raw_position_rows()
            for route in ("/api/actions?held_only=true&limit=20", "/api/stocks?page_size=20", "/api/dashboard"):
                self.safe_json(client.get(route))
            for exchange in ("TWSE", "TPEx"):
                summary = self.safe_json(client.get(f"/api/stocks/{exchange}/TEXT"))["decision_summary"]
                self.assertEqual(summary["action_state"], "manual_review")
                self.assertIsNone(summary["stop_price"])
                self.assertEqual(summary["stop_price_semantics"]["reason"], "invalid_position_stop")
                research = self.safe_json(client.get(f"/api/instruments/TEXT?exchange={exchange}"))["quality_summary"]["research"]
                self.assertEqual(research["action_state"], "manual_review")
                self.assertEqual(research["status"], "complete")
            self.assertEqual(fixture.raw_position_rows(), before)

    def test_existing_source_time_and_strategy_gates_precede_invalid_stop(self):
        fixture = self.fixture(value_reads=True)
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                for change, restore in (
                    ("UPDATE ingestion_runs SET status='failed'", "UPDATE ingestion_runs SET status='success'"),
                    ("UPDATE signals SET data_cutoff='2026-10-05'", "UPDATE signals SET data_cutoff='2026-10-04'"),
                    ("UPDATE signals SET data_quality='partial'", "UPDATE signals SET data_quality='complete'")):
                    with fixture.engine.begin() as connection:
                        connection.exec_driver_sql(change)
                    before = fixture.raw_position_rows()
                    summary = self.safe_json(client.get(f"/api/actions/{exchange}/NEGATIVE"))["decision_summary"]
                    self.assertEqual(summary["action_state"], "data_insufficient")
                    self.assertTrue(summary["blocking_reasons"])
                    self.assertIsNone(summary["stop_price"])
                    self.assertEqual(summary["stop_price_semantics"]["reason"], "invalid_position_stop")
                    self.assertEqual(fixture.raw_position_rows(), before)
                    with fixture.engine.begin() as connection:
                        connection.exec_driver_sql(restore)

    def test_post_read_metadata_preserves_input_contract_and_rejection(self):
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                for raw, status in ((0, "known"), (None, "missing")):
                    saved = self.safe_json(client.post("/api/portfolio", json={"symbol": "NEW", "exchange": exchange,
                        "shares": "9007199254740993", **dict.fromkeys(VALUE_FIELDS, raw)}))
                    self.assertEqual(saved["portfolio_value_status"], dict.fromkeys(VALUE_FIELDS, status))
                    self.assertEqual(saved["shares_exact"], "9007199254740993")
                    read = self.safe_json(client.get("/api/portfolio?q=NEW"))
                    self.assertEqual(next(item for item in read["items"] if item["id"] == saved["id"]), saved)
                before = fixture.raw_position_rows()
                rejected = client.post("/api/portfolio", json={"symbol": "NEW", "exchange": exchange,
                    "shares": 1, "stop_price": -1})
                self.assertEqual(rejected.status_code, 422)
                self.assertEqual(fixture.raw_position_rows(), before)


class QuantityTrustReadTest(unittest.TestCase):
    safe_json = PortfolioValueReadTest.safe_json

    def fixture(self):
        fixture = MemoryFixture(quantity_trust=True)
        self.addCleanup(fixture.close)
        return fixture

    def test_pure_trusted_total_and_three_way_holding_boundaries(self):
        for legacy, integer, total in (
            (1000.0, None, 1000), (0.0, None, 0), (0.0, 1000, 1000), (1000.0, 0, 0),
            (float(SAFE), None, SAFE), (float(SAFE + 1), SAFE + 1, SAFE + 1),
            (float(9007199254740993), 9007199254740993, 9007199254740993),
            (float(MAXIMUM), MAXIMUM, MAXIMUM), (float("inf"), 1000, 1000),
            (1000.0, "1000", None), (1000.0, True, None), (1000.0, 1.0, None),
            (1000.0, MAXIMUM + 1, None), (1000.0, -1, None), (1000.0, b"1000", None),
            (True, None, None), (None, None, None), (float("nan"), None, None),
            (float("inf"), None, None), (float("-inf"), None, None),
            (-1.0, None, None), (1.5, None, None), ("1000", None, None),
            (b"1000", None, None), (float(9007199254740993), None, None),
        ):
            with self.subTest(legacy=repr(legacy), integer=repr(integer)):
                self.assertEqual(trusted_position_shares(legacy, integer), total)
                self.assertIs(position_held(legacy, integer), None if total is None else total > 0)

    def test_actual_sqlite_affinity_conflicts_json_and_whole_rows(self):
        fixture = self.fixture()
        cases = [
            (0, 1000, 1000, float, int), (1000, 0, 0, float, int),
            (1000, None, 1000, float, type(None)), (0, None, 0, float, type(None)),
            (SAFE, None, SAFE, float, type(None)), (float(SAFE + 1), SAFE + 1, SAFE + 1, float, int),
            (float(9007199254740993), 9007199254740993, 9007199254740993, float, int),
            (float(MAXIMUM), MAXIMUM, MAXIMUM, float, int),
            (float(9007199254740993), None, None, float, type(None)),
            (1000, "malformed-integer", None, float, str), (1000, b"malformed-integer", None, float, bytes),
            (1000, -1, None, float, int), (1000, 1.5, None, float, float),
            (1000, float("inf"), None, float, float), (1000, float(MAXIMUM), None, float, float),
            (-1, None, None, float, type(None)), (1.5, None, None, float, type(None)),
            (float("inf"), None, None, float, type(None)), (float("-inf"), None, None, float, type(None)),
            ("malformed-value", None, None, str, type(None)), (b"malformed-value", None, None, bytes, type(None)),
            # Actual SQLite affinity conversions are distinguished from pure
            # helper inputs: the original bool/text/REAL cannot be recovered.
            (True, None, 1, float, type(None)), ("1000", None, 1000, float, type(None)),
            (0, True, 1, float, int), (0, "1000", 1000, float, int), (0, 1000.0, 1000, float, int),
            (1000, float("nan"), 1000, float, type(None)),
        ]
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                with Session(fixture.engine) as db:
                    item = db.scalar(select(PortfolioPosition).join(Instrument).where(
                        Instrument.exchange == exchange, Instrument.symbol == "INTPOS"))
                    position_id = item.id
                for legacy, integer, total, legacy_type, integer_type in cases:
                    with self.subTest(exchange=exchange, legacy=repr(legacy), integer=repr(integer)):
                        with fixture.engine.begin() as connection:
                            connection.exec_driver_sql("UPDATE portfolio_positions SET shares=?, shares_integer=? WHERE id=?",
                                                      (legacy, integer, position_id))
                        before = fixture.raw_quantity_rows()
                        with Session(fixture.engine) as db:
                            item = db.get(PortfolioPosition, position_id)
                            self.assertIs(type(item.shares), legacy_type)
                            self.assertIs(type(item.shares_integer), integer_type)
                        row = next(item for item in self.safe_json(client.get("/api/portfolio?q=INTPOS"))["items"]
                                   if item["id"] == position_id)
                        self.assertEqual(row["shares_exact"], str(total) if total is not None else None)
                        self.assertEqual(row["shares"], total if total is not None and total <= SAFE else None)
                        self.assertEqual(row["position_quantity_status"], "unknown" if total is None else "known")
                        expected_status = "quantity_unknown" if total is None else "precision_unsupported" if total > SAFE else "known"
                        self.assertEqual(row["valuation_status"], dict.fromkeys(("market_value", "unrealized_pnl"), expected_status))
                        if expected_status == "known":
                            self.assertEqual(row["market_value"], 10.5 * total)
                            self.assertEqual(row["unrealized_pnl"], 10.5 * total - 10 * total)
                        else:
                            self.assertIsNone(row["market_value"])
                            self.assertIsNone(row["unrealized_pnl"])
                        summary = self.safe_json(client.get(f"/api/actions/{exchange}/INTPOS"))["decision_summary"]
                        self.assertIs(summary["held"], None if total is None else total > 0)
                        self.assertEqual(summary["position_quantity_status"], row["position_quantity_status"])
                        self.assertEqual(summary["action_state"], "manual_review" if total is None else "hold_observe" if total > 0 else "conditional_entry")
                        self.assertEqual(fixture.raw_quantity_rows(), before)

    def test_actual_callers_filtered_counts_pagination_and_record_retention(self):
        fixture = self.fixture()
        before = fixture.raw_quantity_rows()
        with TestClient(fixture.app) as client:
            actions = self.safe_json(client.get("/api/actions?limit=4"))
            self.assertEqual(actions["meta"]["total"], 18)
            self.assertEqual(actions["summary"]["held"], 6)
            self.assertEqual(actions["summary"]["held_unknown"], 6)
            self.assertEqual(len(actions["items"]), 4)
            for params, total, held, unknown in (
                ("held_only=true", 6, 6, 0), ("state=manual_review", 4, 0, 4),
                ("state=data_insufficient", 2, 0, 2), ("state=data_insufficient&held_only=true", 0, 0, 0),
                ("q=BADINT", 2, 0, 2), ("q=INTZERO", 2, 0, 0), ("q=ABSENT", 2, 0, 0),
            ):
                result = self.safe_json(client.get("/api/actions?limit=100&" + params))
                self.assertEqual(result["meta"]["total"], total)
                self.assertEqual(result["summary"]["held"], held)
                self.assertEqual(result["summary"]["held_unknown"], unknown)
                self.assertEqual(result["summary"]["scope"], "filtered_results" if "state=" in params else
                                 "page_for_actionable_and_data_insufficient_counts")
            seen, cursor = [], None
            while True:
                result = self.safe_json(client.get("/api/actions?limit=4" + ("&cursor=" + cursor if cursor else "")))
                seen.extend(item["instrument"]["id"] for item in result["items"])
                cursor = result["meta"]["next_cursor"]
                if not cursor:
                    break
            self.assertEqual(len(seen), 18)
            self.assertEqual(len(set(seen)), 18)
            dashboard = self.safe_json(client.get("/api/dashboard"))
            self.assertEqual(dashboard["action_counts"]["scope"], "compact_first_page")
            self.assertEqual(dashboard["action_counts"]["held"], 6)
            self.assertEqual(dashboard["action_counts"]["held_unknown"], 2)
            self.assertTrue(any(item["position_quantity_status"] == "unknown" for item in dashboard["actions"]))
            for exchange in ("TWSE", "TPEx"):
                for symbol in QUANTITY_READS:
                    result = self.safe_json(client.get(f"/api/stocks/{exchange}/{symbol}"))["decision_summary"]
                    detail = self.safe_json(client.get(f"/api/actions/{exchange}/{symbol}"))["decision_summary"]
                    for key in ("held", "position_quantity_status", "action_state", "display_instruction"):
                        self.assertEqual(result[key], detail[key])
                    if detail["position_quantity_status"] == "unknown":
                        self.assertIn("股數待核實", detail["context_badges"])
                        self.assertEqual(detail["primary_levels"], {})
                        if symbol != "GATEFAIL":
                            self.assertEqual(detail["display_instruction"], "庫存股數待核實，先核對原記錄。")
                            self.assertEqual(detail["primary_reason"]["label"], detail["display_instruction"])
                        else:
                            self.assertEqual(detail["action_state"], "data_insufficient")
                            self.assertEqual(detail["priority"], 1)
                            self.assertTrue(detail["blocking_reasons"])
                absent = self.safe_json(client.get(f"/api/actions/{exchange}/ABSENT"))["decision_summary"]
                self.assertIs(absent["held"], False)
                self.assertEqual(absent["position_quantity_status"], "absent")
            self.safe_json(client.get("/api/stocks?page_size=100"))
            for exchange in ("TWSE", "TPEx"):
                self.safe_json(client.get(f"/api/instruments/BADINT?exchange={exchange}"))
            self.assertEqual(client.post("/api/portfolio", json={}).status_code, 405)
            self.assertEqual(client.delete("/api/portfolio/1").status_code, 405)
        self.assertEqual(fixture.raw_quantity_rows(), before)

    def test_source_time_strategy_gates_precede_unknown_and_no_as_of_retains_records(self):
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            for change, restore in (
                ("UPDATE ingestion_runs SET status='failed'", "UPDATE ingestion_runs SET status='success'"),
                ("UPDATE signals SET data_cutoff='2026-10-05'", "UPDATE signals SET data_cutoff='2026-10-04'"),
                ("UPDATE signals SET data_quality='partial' WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol='BADINT')",
                 "UPDATE signals SET data_quality='complete' WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol='BADINT')"),
            ):
                with fixture.engine.begin() as connection:
                    connection.exec_driver_sql(change)
                before = fixture.raw_quantity_rows()
                for exchange in ("TWSE", "TPEx"):
                    summary = self.safe_json(client.get(f"/api/actions/{exchange}/BADINT"))["decision_summary"]
                    self.assertEqual(summary["action_state"], "data_insufficient")
                    self.assertTrue(summary["blocking_reasons"])
                    self.assertIsNone(summary["held"])
                    self.assertEqual(summary["priority"], 1)
                    self.assertIn("股數待核實", summary["context_badges"])
                    self.assertEqual(summary["primary_levels"], {})
                    self.assertTrue(summary["display_instruction"].startswith("目前無法產生研究動作。"))
                self.assertEqual(fixture.raw_quantity_rows(), before)
                with fixture.engine.begin() as connection:
                    connection.exec_driver_sql(restore)
            with fixture.engine.begin() as connection:
                connection.exec_driver_sql("DELETE FROM ingestion_runs")
            before = fixture.raw_quantity_rows()
            result = self.safe_json(client.get("/api/actions?limit=100"))
            self.assertEqual(result["meta"]["total"], 16)
            self.assertEqual(result["summary"]["held"], 6)
            self.assertEqual(result["summary"]["held_unknown"], 6)
            self.assertEqual(sum(item["held"] is False for item in result["items"]), 4)
            self.assertEqual(fixture.raw_quantity_rows(), before)

    def test_valuation_status_missing_invalid_and_finite_guard(self):
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            for raw, expected in ((None, "missing"), (-1, "invalid"), ("malformed-value", "invalid"),
                                  (b"malformed-value", "invalid"), (float("inf"), "invalid"),
                                  (1e308, "invalid"), (0, "known"), (10, "known")):
                with fixture.engine.begin() as connection:
                    connection.exec_driver_sql("UPDATE portfolio_positions SET average_cost=? WHERE instrument_id IN "
                                              "(SELECT id FROM instruments WHERE symbol='INTPOS')", (raw,))
                before = fixture.raw_quantity_rows()
                for row in self.safe_json(client.get("/api/portfolio?q=INTPOS"))["items"]:
                    self.assertEqual(row["valuation_status"]["market_value"], "known")
                    self.assertEqual(row["valuation_status"]["unrealized_pnl"], expected)
                    if expected != "known":
                        self.assertIsNone(row["unrealized_pnl"])
                self.assertEqual(fixture.raw_quantity_rows(), before)
            with fixture.engine.begin() as connection:
                connection.exec_driver_sql("UPDATE market_bars SET close=1e308 WHERE instrument_id IN "
                                          "(SELECT id FROM instruments WHERE symbol='INTPOS')")
            before = fixture.raw_quantity_rows()
            for row in self.safe_json(client.get("/api/portfolio?q=INTPOS"))["items"]:
                self.assertEqual(row["valuation_status"], dict.fromkeys(("market_value", "unrealized_pnl"), "invalid"))
                self.assertIsNone(row["market_value"])
                self.assertIsNone(row["unrealized_pnl"])
            self.assertEqual(fixture.raw_quantity_rows(), before)


def main():
    global _listen_port
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--finance-only", action="store_true", help="only finite portfolio input checks and the audit guard")
    parser.add_argument("--finance-read-only", action="store_true", help="only legacy value read checks and the audit guard")
    parser.add_argument("--finance-read-fixture", action="store_true", help="serve fourteen owned read-only value positions")
    parser.add_argument("--quantity-trust-only", action="store_true", help="trusted quantity reads, necessary regressions and the audit guard")
    parser.add_argument("--quantity-trust-fixture", action="store_true", help="serve sixteen owned read-only synthetic quantity positions")
    args = parser.parse_args()
    if args.serve:
        if args.port != 8777:
            parser.error("only owned loopback port 8777 is authorized")
        _listen_port = args.port
        fixture = MemoryFixture(value_reads=args.finance_read_fixture, quantity_trust=args.quantity_trust_fixture)
        try:
            import uvicorn
            fixture.server = uvicorn.Server(uvicorn.Config(fixture.app, host="127.0.0.1", port=args.port,
                                                          lifespan="off", access_log=False))
            print(json.dumps({"mode": "synthetic-quantity-trust-memory-actual-router" if args.quantity_trust_fixture else "synthetic-value-read-memory-actual-router" if args.finance_read_fixture else "synthetic-user-quantity-memory-actual-router",
                              "fixture_date": str(READ_DAY if args.finance_read_fixture or args.quantity_trust_fixture else DAY),
                              "pid": os.getpid(), "url": f"http://127.0.0.1:{args.port}", "disk_artifacts": 0,
                              "disk_save_reopen": "not_tested"}), flush=True)
            fixture.server.run()
        finally:
            fixture.close()
    else:
        if args.quantity_trust_only:
            # Reuse only the changed, memory-only storage assertion. Disk and
            # migration modes remain outside this suite and its acceptance.
            sys.modules.setdefault("test_share_quantity_exact_presentation", sys.modules[__name__])
            from test_share_quantity_storage import StorageMemoryTest
            suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(QuantityTrustReadTest),
                StorageMemoryTest("test_trust_priority_and_invalid_new_field"),
                ShareQuantityExactTest("test_actual_four_inputs_commit_refresh_and_get_in_memory"),
                PortfolioValueReadTest("test_actual_complete_decision_and_all_read_callers_keep_stop_origin"),
                PortfolioValueReadTest("test_existing_source_time_and_strategy_gates_precede_invalid_stop"),
                ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        elif args.finance_read_only:
            suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(PortfolioValueReadTest),
                                       ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        elif args.finance_only:
            suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(PortfolioValueInputTest),
                                       ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        else:
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(ShareQuantityExactTest)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        success = result.wasSuccessful() and not UNEXPECTED_DENIALS
        print(json.dumps({"tests": result.testsRun, "success": success, "fixture_date": str(READ_DAY if args.finance_read_only or args.quantity_trust_only else DAY),
                          "actual_router_requests": HTTP_REQUESTS, "disk_artifacts": 0,
                          "expected_denials": EXPECTED_DENIALS, "unexpected_denials": UNEXPECTED_DENIALS,
                          **({"sqlite_read_conversions": "REAL affinity: bool/numeric text become float; NaN becomes NULL",
                              "decision_calendar": "sixty explicit synthetic fixture dates, not real official sessions",
                              "python": sys.version.split()[0], "sqlalchemy": sys.modules["sqlalchemy"].__version__,
                              "pydantic": sys.modules["pydantic"].__version__, "sqlite_read_cases": 72,
                              "complete_stop_cases": 20, "precedence_cases": 6} if args.finance_read_only else {}),
                          **({"sqlite_quantity_cases": 54, "quantity_ui_records": 16,
                              "decision_calendar": "sixty explicit synthetic fixture dates, not real official sessions",
                              "sqlite_quantity_conversions": "affinity: bool/numeric text/whole REAL may become numeric; integer NaN becomes NULL",
                              "python": sys.version.split()[0], "sqlalchemy": sys.modules["sqlalchemy"].__version__,
                              "pydantic": sys.modules["pydantic"].__version__} if args.quantity_trust_only else {}),
                          "disk_save_reopen": "not_tested"}), flush=True)
        return 0 if success else 1
    print(json.dumps({"owned_memory_server": "closed", "unexpected_denials": UNEXPECTED_DENIALS}), flush=True)
    return 0 if not UNEXPECTED_DENIALS else 1


if __name__ == "__main__":
    raise SystemExit(main())
