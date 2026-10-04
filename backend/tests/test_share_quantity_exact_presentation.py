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
import math
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
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import api
from app.db import Base
from app.models import IngestionRun, Instrument, MarketBar, PortfolioPosition, Signal, StrategyVersion
from app.portfolio_values import read_portfolio_value
from app.portfolio_quotes import read_close, read_record
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
QUOTE_READS = ("NORMAL", "BADPRICE", "MISSINGBAR", "DIRTYDATE", "METABAD",
               "POISON", "ZEROQ", "BADQ", "HUGEQ", "OVERFLOW")
ACTION_READS = ("A-NORMAL", "B-CLOSE", "C-DATE", "D-METADATA", "E-SOURCE", "F-SUSPEND",
               "G-ADJUST", "H-MISSING", "I-QUNKNOWN", "J-STOPBAD", "K-HISTORY", "L-FUTURE")
STOCK_READS = ("A-NORMAL", "B-CLOSE", "C-DATE", "D-METADATA", "E-SOURCE", "F-SUSPEND",
               "G-VOLUME", "H-OHLC", "I-MISSING", "J-HISTORY", "K-FUTURE", "L-WINDOW")
STOCK_SETUP_MUTATIONS = 0
SIGNAL_READS = ("A-NORMAL", "B-JSON", "C-DATE", "D-METADATA", "E-VERSION", "F-ALTERNATE",
                "G-LATEST", "H-WINDOW", "I-NOBARS", "J-IDENTITY", "K-FUTURE", "L-RR", "M-OBSERVATION")
SIGNAL_SETUP_MUTATIONS = 0
SIGNAL_DIRECT_GETS = 0
SIGNAL_DIGESTS = []
INDEPENDENT_READS = ("A-NORMAL", "B-JSON", "C-DATE", "D-METADATA", "E-CHIP", "F-UNLOCATED",
                     "G-FUTURE", "H-WINDOW", "I-NOBARS", "J-OBSERVATION")
INDEPENDENT_SETUP_MUTATIONS = 0
INDEPENDENT_DIRECT_GETS = 0
INDEPENDENT_DIGESTS = []


class MemoryFixture:
    def __init__(self, *, value_reads=False, quantity_trust=False, quote_reads=False, action_reads=False, stock_reads=False, stock_cases=False, signal_reads=False, signal_cases=False, independent_reads=False):
        self.stock_reads = stock_reads
        self.signal_reads = signal_reads
        self.independent_reads = independent_reads
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.app = FastAPI()
        api.configure_cors(self.app)
        self.app.include_router(api.router)
        self.server = None
        with Session(self.engine) as db:
            for exchange in (("TWSE",) if stock_reads else ("TWSE", "TPEx")):
                for symbol in (INDEPENDENT_READS if independent_reads else SIGNAL_READS if signal_reads else STOCK_READS if stock_reads else ACTION_READS if action_reads else QUOTE_READS if quote_reads else (*QUANTITY_READS, "ABSENT") if quantity_trust else READ_VALUES if value_reads else (*CASES, "NEW")):
                    instrument = Instrument(market="TW", exchange=exchange, symbol=symbol,
                                            name="synthetic user quantity " + symbol,
                                            instrument_type="stock", status="active")
                    db.add(instrument)
                    db.flush()
                    db.add(MarketBar(instrument_id=instrument.id, trading_date=READ_DAY if value_reads or quantity_trust or quote_reads or action_reads or stock_reads else DAY,
                                     open=10, high=11, low=9, close=10.5, adj_close=10.5,
                                      volume=1000, turnover=10500, source="fixture-stock-detail" if stock_reads else "fixture-portfolio-quote-read" if quote_reads else "fixture-portfolio-quantity-trust" if quantity_trust else "fixture-portfolio-value-read" if value_reads else "synthetic-user-quantity"))
                    if quote_reads:
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=1000, shares_integer=1000,
                            average_cost=10, stop_price=9, note="synthetic local quote; all SQL columns retained", updated_at=datetime(2026, 10, 4)))
                    elif quantity_trust and symbol != "ABSENT":
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=1000, shares_integer=1000,
                            average_cost=10, note="synthetic quantity trust; whole row retained", updated_at=datetime(2026, 10, 4)))
                    elif value_reads or action_reads or stock_reads:
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=1000, shares_integer=1000,
                            average_cost=10, note="whole row retained", updated_at=datetime(2026, 10, 4)))
                    elif symbol in CASES:
                        db.add(PortfolioPosition(instrument_id=instrument.id, shares=CASES[symbol], average_cost=10))
            db.commit()

        if value_reads or quantity_trust or action_reads or stock_reads:
            self.seed_value_reads()
        if quantity_trust:
            self.seed_quantity_reads()
        if quote_reads:
            self.seed_quote_reads()
        if action_reads:
            self.seed_action_reads()
        if stock_reads and stock_cases:
            self.seed_stock_reads()
        if signal_reads and signal_cases:
            self.seed_signal_reads()
        if independent_reads:
            self.seed_independent_reads()
        self.read_mutations = 0
        if action_reads or stock_reads:
            @event.listens_for(self.engine, "before_cursor_execute")
            def count_read_mutations(_connection, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
                    self.read_mutations += 1

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
            if independent_reads:
                self.product_requests += not request.url.path.startswith("/__review__/")
                self.review_requests += request.url.path.startswith("/__review__/")
                if self.product_requests > (96 if self.server is not None else 160) or self.review_requests > 8:
                    raise AssertionError("independent HTTP scope cap exceeded")
            if request.method not in {"GET", "OPTIONS"} and not (shutdown or (
                    not (value_reads or quantity_trust or quote_reads or action_reads or stock_reads) and (portfolio_write or portfolio_delete))):
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

        if quote_reads:
            @self.app.get("/__review__/quote-read-snapshot")
            def quote_read_snapshot():
                rows = self.raw_quote_rows()
                return {"whole_sql_sha256": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(),
                        "position_count": len(rows["portfolio_positions"]), "bar_count": len(rows["market_bars"]),
                        "includes": ["both whole tables", "all columns", "all typeof()", "note", "updated_at"],
                        "fixture_date": str(READ_DAY), "storage": "memory_only"}

        if action_reads:
            @self.app.get("/__review__/action-read-snapshot")
            def action_read_snapshot():
                rows = self.raw_quote_rows()
                return {"whole_sql_sha256": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(),
                        "position_count": len(rows["portfolio_positions"]), "bar_count": len(rows["market_bars"]),
                        "read_mutations": self.read_mutations,
                        "includes": ["both whole tables", "all columns", "all typeof()", "note", "updated_at"],
                        "fixture_date": str(READ_DAY), "storage": "memory_only"}

        if stock_reads:
            @self.app.get("/__review__/stock-read-snapshot")
            def stock_read_snapshot():
                rows = self.raw_quote_rows()
                return {"whole_sql_sha256": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(),
                        "position_count": len(rows["portfolio_positions"]), "bar_count": len(rows["market_bars"]),
                        "read_mutations": self.read_mutations, "fixture_date": str(READ_DAY), "storage": "memory_only",
                        "includes": ["both whole tables", "all columns", "all typeof()", "note", "updated_at"]}

        if signal_reads:
            @self.app.get("/__review__/signal-read-snapshot")
            def signal_read_snapshot():
                rows = self.raw_signal_rows()
                return {"whole_sql_sha256": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(),
                        "table_counts": {table: len(items) for table, items in rows.items()},
                        "includes": ["signals", "strategy_versions", "portfolio_positions", "market_bars", "all columns", "all typeof()"],
                        "read_mutations": self.read_mutations, "setup_mutations": SIGNAL_SETUP_MUTATIONS,
                        "fixture_date": str(READ_DAY), "storage": "memory_only"}

        if independent_reads:
            @self.app.get("/__review__/independent-read-snapshot")
            def independent_read_snapshot():
                rows = self.raw_independent_rows()
                return {"whole_sql_sha256": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(),
                        "table_counts": {table: len(items) for table, items in rows.items()},
                        "includes": [*rows, "all columns", "all typeof()"], "read_mutations": self.read_mutations,
                        "targeted_setup_mutations": INDEPENDENT_SETUP_MUTATIONS,
                        "product_requests": self.product_requests, "review_requests": self.review_requests,
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

    def raw_quote_rows(self):
        with self.engine.connect() as connection:
            result = {}
            for table in ("portfolio_positions", "market_bars"):
                columns = [row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
                types = ", ".join(f"typeof({column})" for column in columns)
                result[table] = [tuple(row) for row in connection.exec_driver_sql(f"SELECT *, {types} FROM {table} ORDER BY id")]
            return result

    def raw_signal_rows(self):
        with self.engine.connect() as connection:
            result = {}
            for table in ("signals", "strategy_versions", "portfolio_positions", "market_bars"):
                columns = [row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
                types = ", ".join(f"typeof({column})" for column in columns)
                result[table] = [tuple(row) for row in connection.exec_driver_sql(f"SELECT *, {types} FROM {table} ORDER BY id")]
            return result

    def raw_independent_rows(self):
        with self.engine.connect() as connection:
            result = {}
            for table in ("technical_features", "chip_snapshots", "signals", "strategy_versions", "portfolio_positions", "market_bars"):
                columns = [row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
                types = ", ".join(f"typeof({column})" for column in columns)
                result[table] = [tuple(row) for row in connection.exec_driver_sql(f"SELECT *, {types} FROM {table} ORDER BY id")]
            return result

    def independent_change(self, statement, parameters=()):
        global INDEPENDENT_SETUP_MUTATIONS
        INDEPENDENT_SETUP_MUTATIONS += 1
        if INDEPENDENT_SETUP_MUTATIONS > 256:
            raise AssertionError("independent targeted setup cap exceeded")
        with self.engine.begin() as connection:
            connection.exec_driver_sql(statement, parameters)

    def seed_independent_reads(self):
        self.product_requests = self.review_requests = 0
        for symbol in INDEPENDENT_READS:
            self.independent_change("INSERT INTO technical_features(instrument_id,trading_date,features_json,source,created_at) "
                "SELECT id,?,'{\"ma20\":10,\"ma60\":9}', 'fixture-derived', '2026-10-04 00:00:00' FROM instruments WHERE symbol=?", (str(READ_DAY), symbol))
        self.independent_change("INSERT INTO technical_features(instrument_id,trading_date,features_json,source,created_at) "
            "SELECT id,'2026-10-03','{\"ma20\":999}', 'fixture-derived','2026-10-03 00:00:00' FROM instruments WHERE symbol='B-JSON'")
        self.independent_change("UPDATE technical_features SET features_json='{bad' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='B-JSON') AND trading_date='2026-10-04'")
        self.independent_change("UPDATE technical_features SET trading_date='!unknown' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol IN ('C-DATE'))")
        self.independent_change("UPDATE technical_features SET source=?,created_at=? WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='D-METADATA')", (b'bad-source', b'bad-time'))
        self.independent_change("INSERT INTO technical_features(instrument_id,trading_date,features_json,source,created_at) "
            "SELECT id,'2026-10-05','{bad','fixture-derived','bad-time' FROM instruments WHERE symbol='G-FUTURE'")
        chip_rows = []
        for symbol, amount in (("A-NORMAL", 5), ("D-METADATA", 1), ("E-CHIP", 1), ("F-UNLOCATED", 121),
                               ("G-FUTURE", 1), ("H-WINDOW", 121), ("I-NOBARS", 1)):
            for offset in range(amount):
                chip_rows.append((str(READ_DAY - timedelta(days=offset)), symbol))
        self.independent_change("INSERT INTO chip_snapshots(instrument_id,trading_date,foreign_buy,trust_buy,dealer_buy,margin_balance,margin_change,"
            "short_balance,borrowed_sell,day_trade_ratio,source,data_as_of,collected_at,raw_payload_id) SELECT id,?,1000,-100,0,100,-2,0,0,0.2,"
            "'twse_t86+twse_margin','2026-10-04 00:00:00','2026-10-04 00:00:00',NULL FROM instruments WHERE symbol=?", chip_rows)
        self.independent_change("UPDATE chip_snapshots SET source=?,data_as_of=?,collected_at=?,raw_payload_id=? "
            "WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='D-METADATA')", (b'bad-source', 'bad-time', b'bad-time', 'bad-id'))
        self.independent_change("UPDATE chip_snapshots SET foreign_buy=?,margin_change=? WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='E-CHIP')", (float('inf'), b'bad-float'))
        self.independent_change("INSERT INTO chip_snapshots(instrument_id,trading_date,foreign_buy,trust_buy,dealer_buy,margin_balance,margin_change,source,collected_at) "
            "SELECT id,'!unknown',1000,0,0,100,0,'fixture-chip','bad-time' FROM instruments WHERE symbol='F-UNLOCATED'")
        self.independent_change("INSERT INTO chip_snapshots(instrument_id,trading_date,foreign_buy,trust_buy,dealer_buy,margin_balance,margin_change,source,collected_at) "
            "SELECT id,'2026-10-05',9999,0,0,100,0,'fixture-chip','bad-time' FROM instruments WHERE symbol='G-FUTURE'")
        self.independent_change("UPDATE chip_snapshots SET foreign_buy='bad-value' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='H-WINDOW') AND trading_date='2026-10-04'")
        self.independent_change("DELETE FROM market_bars WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='I-NOBARS')")
        self.independent_change("UPDATE chip_snapshots SET trading_date='!unknown' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='I-NOBARS')")
        self.independent_change("UPDATE signals SET status='observation',breakout_price=NULL,invalid_price=NULL,target_1=NULL "
            "WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='J-OBSERVATION')")

    def signal_change(self, statement, parameters=()):
        global SIGNAL_SETUP_MUTATIONS
        SIGNAL_SETUP_MUTATIONS += 1
        if SIGNAL_SETUP_MUTATIONS > 96:
            raise AssertionError("signal targeted setup cap exceeded")
        with self.engine.begin() as connection:
            connection.exec_driver_sql(statement, parameters)

    def change_signal(self, symbol, expression, parameters=()):
        self.signal_change("UPDATE signals SET " + expression + " WHERE instrument_id=(SELECT id FROM instruments WHERE symbol=?)", (*parameters, symbol))

    def add_signal_copy(self, symbol, key, day, version=None):
        self.signal_change("INSERT INTO signals (signal_key,signal_date,instrument_id,strategy_version_id,status,entry_type,breakout_price,reference_entry,pullback_low,pullback_high,invalid_price,target_1,data_quality,data_cutoff,rule_evidence_json,created_at) "
            "SELECT ?,?,instrument_id,COALESCE(?,strategy_version_id),'conditional','conditional',12,12,11,12,8,20,'complete',data_cutoff,rule_evidence_json,created_at "
            "FROM signals WHERE instrument_id=(SELECT id FROM instruments WHERE symbol=?) ORDER BY id LIMIT 1", (key, day, version, symbol))

    def seed_signal_reads(self):
        self.change_signal("B-JSON", "rule_evidence_json=?", ("{malformed",))
        self.change_signal("C-DATE", "signal_date=?", ("0000-01-01",))
        for version, symbol in (("optional-metadata", "D-METADATA"), ("9.9.9", "E-VERSION")):
            self.signal_change("INSERT INTO strategy_versions(name,version,kind,config_json,canonical_config_snapshot,active,created_at) VALUES('breakout_v1',?,'technical','{}','{}',1,'2026-10-04 00:00:00')", (version,))
            self.change_signal(symbol, "strategy_version_id=(SELECT id FROM strategy_versions WHERE name='breakout_v1' AND version=?)", (version,))
        self.signal_change("UPDATE strategy_versions SET config_json='{bad',canonical_config_snapshot='[]',created_at='malformed-time' WHERE version='optional-metadata'")
        self.change_signal("D-METADATA", "created_at=?,execution_date=?,confidence=?,source_report=?", ("bad", "2026-02-30", float("inf"), b"bad"))
        self.signal_change("INSERT INTO strategy_versions(name,version,kind,config_json,canonical_config_snapshot,active,created_at) VALUES('pullback_v1','1.0.0','technical','{}','{}',1,'2026-10-04 00:00:00')")
        with self.engine.connect() as connection:
            pullback_id = connection.exec_driver_sql("SELECT id FROM strategy_versions WHERE name='pullback_v1'").scalar_one()
        self.add_signal_copy("F-ALTERNATE", "healthy-alternate", str(READ_DAY), pullback_id)
        self.change_signal("F-ALTERNATE", "rule_evidence_json=?", ("[]",))
        self.signal_change("UPDATE signals SET rule_evidence_json='{}' WHERE signal_key='healthy-alternate'")
        self.add_signal_copy("G-LATEST", "older-healthy", str(READ_DAY - timedelta(days=1)))
        self.signal_change("UPDATE signals SET breakout_price='malformed-price' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='G-LATEST') AND signal_date=?", (str(READ_DAY),))
        self.signal_change("INSERT INTO strategy_versions(name,version,kind,config_json,canonical_config_snapshot,active,created_at) VALUES('custom-research','1.0.0','technical','{}','{}',1,'2026-10-04 00:00:00')")
        with self.engine.connect() as connection:
            custom_id = connection.exec_driver_sql("SELECT id FROM strategy_versions WHERE name='custom-research'").scalar_one()
        # One targeted statement creates the finite 22-row window boundary.
        self.signal_change("WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<22) "
            "INSERT INTO signals(signal_key,signal_date,instrument_id,strategy_version_id,status,entry_type,data_quality,rule_evidence_json,created_at) "
            "SELECT 'window-'||n,?,(SELECT id FROM instruments WHERE symbol='H-WINDOW'),?,'observation','conditional','complete','{bad','2026-10-04 00:00:00' FROM seq", (str(READ_DAY), custom_id))
        self.signal_change("DELETE FROM market_bars WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='I-NOBARS')")
        self.change_signal("I-NOBARS", "signal_date=?", ("0000-01-01",))
        self.change_signal("J-IDENTITY", "strategy_version_id=999999")
        self.add_signal_copy("K-FUTURE", "future-invalid", str(READ_DAY + timedelta(days=1)), 999999)
        self.signal_change("UPDATE signals SET rule_evidence_json='null' WHERE signal_key='future-invalid'")
        self.change_signal("L-RR", "breakout_price=?,invalid_price=?,target_1=?", (1e-308, 5e-309, 1e308))
        self.change_signal("M-OBSERVATION", "status='observation',breakout_price=NULL,invalid_price=NULL,target_1=NULL,earliest_execution_date=NULL")

    def seed_quote_reads(self):
        with self.engine.begin() as connection:
            def change(table, expression, symbol, parameters=()):
                connection.exec_driver_sql(f"UPDATE {table} SET {expression} WHERE instrument_id IN "
                    "(SELECT id FROM instruments WHERE symbol=?)", (*parameters, symbol))
            change("market_bars", "close=-1", "BADPRICE")
            connection.exec_driver_sql("DELETE FROM market_bars WHERE instrument_id IN "
                                      "(SELECT id FROM instruments WHERE symbol='MISSINGBAR')")
            change("market_bars", "trading_date='not-a-date'", "DIRTYDATE")
            change("market_bars", "source=?, data_as_of=?, collected_at=?", "METABAD", (b"twse", "invalid-time", "2026-02-30 00:00:00"))
            change("market_bars", "open=?, high=?, low=?, adj_close=?, volume=?, turnover=?", "POISON",
                   (float("inf"), b"bad-high", "bad-low", float("-inf"), float("inf"), float("inf")))
            change("market_bars", "source=?, data_as_of=?", "POISON", ("S" * 120, "2026-10-04T00:00:00." + "0" * 44))
            change("portfolio_positions", "shares_integer=0", "ZEROQ")
            change("portfolio_positions", "shares_integer='bad-quantity'", "BADQ")
            change("portfolio_positions", "shares_integer=?", "HUGEQ", (SAFE + 2,))
            change("market_bars", "close=1e308", "OVERFLOW")

    def stock_change(self, symbol, expression, parameters=(), day=READ_DAY):
        global STOCK_SETUP_MUTATIONS
        STOCK_SETUP_MUTATIONS += 1
        if STOCK_SETUP_MUTATIONS > 32:
            raise AssertionError("stock setup mutation cap exceeded")
        with self.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE market_bars SET " + expression + " WHERE trading_date=? AND instrument_id IN "
                "(SELECT id FROM instruments WHERE symbol=?)", (*parameters, str(day), symbol))

    def seed_stock_reads(self):
        global STOCK_SETUP_MUTATIONS
        self.stock_change("B-CLOSE", "close=?", (b"bad-close",))
        self.stock_change("C-DATE", "trading_date='z-invalid-date'")
        self.stock_change("D-METADATA", "data_as_of='bad-time',collected_at='2026-02-30',adj_close=?,turnover=?", (b"bad-adjustment", float("inf")))
        self.stock_change("E-SOURCE", "source=?", (b"twse",))
        self.stock_change("F-SUSPEND", "is_suspended='bad-boolean'")
        self.stock_change("G-VOLUME", "volume=?", (b"bad-volume",))
        self.stock_change("H-OHLC", "high=1")
        self.stock_change("J-HISTORY", "close=?", (float("inf"),), READ_DAY - timedelta(days=1))
        STOCK_SETUP_MUTATIONS += 4
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM market_bars WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol='I-MISSING')")
            connection.exec_driver_sql("INSERT INTO market_bars (instrument_id,trading_date,open,high,low,close,adj_close,volume,turnover,source,collected_at,is_suspended) "
                "SELECT id,?,10,11,9,10.5,10.5,1000,10500,'fixture-stock-detail','bad-unused-time',0 FROM instruments WHERE symbol='K-FUTURE'", (str(READ_DAY + timedelta(days=1)),))
            connection.exec_driver_sql("INSERT INTO market_bars (instrument_id,trading_date,open,high,low,close,adj_close,volume,turnover,source,collected_at,is_suspended) "
                "SELECT id,?,10,11,9,10.5,10.5,1000,10500,'fixture-stock-detail','2026-10-04 00:00:00',0 FROM instruments WHERE symbol='L-WINDOW'",
                [(str(READ_DAY - timedelta(days=index)),) for index in range(60, 122)])
            connection.exec_driver_sql("INSERT INTO market_bars (instrument_id,trading_date,open,high,low,close,adj_close,volume,turnover,source,collected_at,is_suspended) "
                "SELECT id,'0000-invalid',10,11,9,10.5,10.5,1000,10500,'fixture-stock-detail','2026-10-04 00:00:00',0 FROM instruments WHERE symbol='L-WINDOW'")

    def seed_action_reads(self):
        with self.engine.begin() as connection:
            def change(table, expression, symbol, parameters=()):
                suffix = " AND trading_date=?" if table == "market_bars" else ""
                connection.exec_driver_sql(f"UPDATE {table} SET {expression} WHERE instrument_id IN "
                    "(SELECT id FROM instruments WHERE symbol=?)" + suffix,
                    (*parameters, symbol, *((str(READ_DAY),) if suffix else ())))
            change("market_bars", "close=-1", "B-CLOSE")
            change("market_bars", "trading_date='z-invalid-date'", "C-DATE")
            change("market_bars", "data_as_of='bad-time', collected_at='2026-02-30', open=?, high=?, volume=?",
                   "D-METADATA", (b"unused-open", "unused-high", b"unused-volume"))
            change("market_bars", "source=?", "E-SOURCE", (b"twse",))
            change("market_bars", "is_suspended='bad-boolean'", "F-SUSPEND")
            change("market_bars", "adj_close=-1", "G-ADJUST")
            connection.exec_driver_sql("DELETE FROM market_bars WHERE instrument_id IN "
                                      "(SELECT id FROM instruments WHERE symbol='H-MISSING')")
            change("portfolio_positions", "shares_integer='bad-quantity'", "I-QUNKNOWN")
            change("portfolio_positions", "stop_price=-1", "J-STOPBAD")
            change("market_bars", "close=1e308, adj_close=1e308", "L-FUTURE")
            connection.exec_driver_sql("UPDATE market_bars SET close=? WHERE trading_date=? AND instrument_id IN "
                "(SELECT id FROM instruments WHERE symbol='K-HISTORY')", (b"bad-history-close", str(READ_DAY - timedelta(days=1))))
            connection.exec_driver_sql("UPDATE instruments SET is_watchlisted=1 WHERE symbol='A-NORMAL'")
            connection.exec_driver_sql("INSERT INTO market_bars (instrument_id, trading_date, open, high, low, close, "
                "adj_close, volume, turnover, source, collected_at, is_suspended) SELECT id, ?, 5000, 5000, 5000, "
                "5000, 5000, 1, 1, 'fixture-portfolio-value-read', 'bad-unused-time', 0 FROM instruments WHERE symbol='L-FUTURE'",
                (str(READ_DAY + timedelta(days=1)),))

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
                        source="fixture-stock-detail" if self.stock_reads else "fixture-portfolio-value-read"))
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


class PortfolioQuoteReadTest(unittest.TestCase):
    safe_json = PortfolioValueReadTest.safe_json

    def fixture(self):
        fixture = MemoryFixture(quote_reads=True)
        self.addCleanup(fixture.close)
        return fixture

    def test_pure_close_and_record_boundaries_without_coercion(self):
        for value in (1, 10.5, 1e308):
            self.assertEqual(read_close(value), (float(value), "known"))
        self.assertEqual(read_close(None), (None, "missing"))
        for value in (0, -0.0, -1, True, False, "10.5", b"10.5", Decimal("10.5"), [], {},
                      float("nan"), float("inf"), float("-inf"), 10**400):
            self.assertEqual(read_close(value), (None, "invalid"))
        for field in ("date", "source", "data_as_of", "collected_at"):
            self.assertEqual(read_record(None, field), (None, "missing"))
            for value in (True, 1, b"twse", [], {}, "", "\ud800"):
                self.assertEqual(read_record(value, field), (None, "invalid"))
        for value in ("2026-10-04", "2024-02-29", "0001-01-01"):
            self.assertEqual(read_record(value, "date"), (value, "known"))
        for value in ("0000-01-01", "2026-02-29", "2026-2-01", "2026-10-04 "):
            self.assertEqual(read_record(value, "date"), (None, "invalid"))
        for value in ("2026-10-04 00:00:00.000000", "2026-10-04T00:00:00+00:00"):
            self.assertEqual(read_record(value, "data_as_of"), (value, "known"))
        for value in ("2026-10-04", "2026-02-30 00:00:00", "2026-10-04 25:00:00",
                      "2026-10-04T00:00:00+01:99", "2026-10-04T00:00:00+0100",
                      "2026-10-04T00:00:00." + "0" * 46):
            self.assertEqual(read_record(value, "collected_at"), (None, "invalid"))
        boundary = "2026-10-04T00:00:00." + "0" * 44
        self.assertEqual(len(boundary), 64)
        self.assertEqual(read_record(boundary, "data_as_of"), (boundary, "known"))
        for value in ("twse", "unknown", "not-an-admitted-source", "\U0001f600" * 120):
            self.assertEqual(read_record(value, "source"), (value, "known"))
        for value in (" ", "\ufeff", "\x85", "twse\x00", "twse\x7f", "s" * 121, "\U0001f600" * 121):
            self.assertEqual(read_record(value, "source"), (None, "invalid"))

    def test_actual_router_projection_keeps_whole_sql_and_unverified_records(self):
        fixture = self.fixture()
        before = fixture.raw_quote_rows()
        with TestClient(fixture.app) as client:
            payload = self.safe_json(client.get("/api/portfolio?page_size=100"))
            self.assertEqual(len(payload["items"]), 20)
            for row in payload["items"]:
                symbol = row["instrument"]["symbol"]
                quote = row["portfolio_quote"]
                self.assertEqual((quote["source_verification"], quote["date_verification"]), ("unverified", "unverified"))
                self.assertEqual(row["portfolio_value_status"]["average_cost"], "known")
                expected = {"BADPRICE": "invalid", "MISSINGBAR": "missing", "BADQ": "quantity_unknown",
                            "HUGEQ": "precision_unsupported", "OVERFLOW": "invalid"}.get(symbol, "local_estimate")
                self.assertEqual(row["valuation_status"], dict.fromkeys(("market_value", "unrealized_pnl"), expected))
                if expected != "local_estimate":
                    self.assertIsNone(row["market_value"])
                    self.assertIsNone(row["unrealized_pnl"])
                elif symbol == "ZEROQ":
                    self.assertEqual((row["market_value"], row["unrealized_pnl"]), (0, 0))
                else:
                    self.assertEqual((row["market_value"], row["unrealized_pnl"]), (10500, 500))
                if symbol == "MISSINGBAR":
                    self.assertIsNone(row["latest_bar"])
                else:
                    self.assertEqual(set(row["latest_bar"]), {"date", "close", "source", "data_as_of", "collected_at"})
                if symbol == "DIRTYDATE":
                    self.assertIsNone(quote["recorded"]["date"])
                    self.assertEqual(quote["record_status"]["date"], "invalid")
                if symbol == "METABAD":
                    for field in ("source", "data_as_of", "collected_at"):
                        self.assertIsNone(quote["recorded"][field])
                        self.assertEqual(quote["record_status"][field], "invalid")
            self.assertEqual(client.post("/api/portfolio", json={}).status_code, 405)
            self.assertEqual(client.delete("/api/portfolio/1").status_code, 405)
        self.assertEqual(fixture.raw_quote_rows(), before)

    def test_actual_sqlite_affinity_and_not_null_rejections_do_not_repair_prices(self):
        from sqlalchemy.exc import IntegrityError
        fixture = self.fixture()
        cases = [(1, float, "known"), (0, float, "invalid"), (-1, float, "invalid"),
                 (float("inf"), float, "invalid"), (float("-inf"), float, "invalid"),
                 ("bad-price", str, "invalid"), (b"bad-price", bytes, "invalid"),
                 (True, float, "known"), ("12.5", float, "known")]
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                for value, value_type, expected in cases:
                    with fixture.engine.begin() as connection:
                        connection.exec_driver_sql("UPDATE market_bars SET close=? WHERE instrument_id IN "
                            "(SELECT id FROM instruments WHERE symbol='NORMAL' AND exchange=?)", (value, exchange))
                        loaded = connection.exec_driver_sql("SELECT close FROM market_bars WHERE instrument_id IN "
                            "(SELECT id FROM instruments WHERE symbol='NORMAL' AND exchange=?)", (exchange,)).scalar()
                    self.assertIs(type(loaded), value_type)
                    before = fixture.raw_quote_rows()
                    row = next(row for row in self.safe_json(client.get("/api/portfolio?q=NORMAL"))["items"]
                               if row["instrument"]["exchange"] == exchange)
                    self.assertEqual(row["portfolio_quote"]["close_status"], expected)
                    self.assertEqual(row["portfolio_quote"]["close"], read_close(loaded)[0])
                    self.assertEqual(row["valuation_status"]["market_value"], "local_estimate" if expected == "known" else "invalid")
                    self.assertEqual(fixture.raw_quote_rows(), before)
                for missing in (None, float("nan")):
                    before = fixture.raw_quote_rows()
                    with self.assertRaises(IntegrityError):
                        with fixture.engine.begin() as connection:
                            connection.exec_driver_sql("UPDATE market_bars SET close=? WHERE instrument_id IN "
                                "(SELECT id FROM instruments WHERE symbol='NORMAL' AND exchange=?)", (missing, exchange))
                    self.assertEqual(fixture.raw_quote_rows(), before)

    def test_invalid_latest_does_not_fallback_and_metadata_does_not_verify_dates(self):
        fixture = self.fixture()
        with fixture.engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO market_bars (instrument_id, trading_date, open, high, low, close, "
                "adj_close, volume, turnover, source, collected_at, is_suspended) SELECT instrument_id, '2026-10-03', "
                "10,11,9,50,50,1000,50000,'twse','2026-10-03 00:00:00',0 FROM portfolio_positions "
                "WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol='BADPRICE')")
            connection.exec_driver_sql("UPDATE market_bars SET source='twse', data_as_of='2026-01-01 00:00:00', "
                "collected_at='2099-01-01 00:00:00', is_suspended=1 WHERE instrument_id IN "
                "(SELECT id FROM instruments WHERE symbol='NORMAL')")
        before = fixture.raw_quote_rows()
        with TestClient(fixture.app) as client:
            for row in self.safe_json(client.get("/api/portfolio?page_size=100"))["items"]:
                if row["instrument"]["symbol"] == "BADPRICE":
                    self.assertEqual(row["portfolio_quote"]["close_status"], "invalid")
                    self.assertIsNone(row["market_value"])
                if row["instrument"]["symbol"] == "NORMAL":
                    self.assertEqual(row["portfolio_quote"]["recorded"]["source"], "twse")
                    self.assertEqual(row["portfolio_quote"]["record_status"]["data_as_of"], "known")
                    self.assertEqual(row["portfolio_quote"]["date_verification"], "unverified")
                    self.assertEqual(row["valuation_status"]["market_value"], "local_estimate")
        self.assertEqual(fixture.raw_quote_rows(), before)

    def test_quantity_cost_and_overflow_priority_at_actual_router(self):
        fixture = self.fixture()
        with TestClient(fixture.app) as client:
            for quantity, price, cost, market_status, pnl_status in (
                ("bad", -1, -1, "quantity_unknown", "quantity_unknown"),
                (SAFE + 2, -1, -1, "precision_unsupported", "precision_unsupported"),
                (0, 10.5, 10, "local_estimate", "local_estimate"),
                (0, -1, 10, "invalid", "invalid"),
                (1000, -1, None, "invalid", "missing"),
                (1000, 10.5, -1, "local_estimate", "invalid"),
                (1000, 10.5, None, "local_estimate", "missing"),
                (1000, 10.5, 1e308, "local_estimate", "invalid"),
                (1000, 1e308, 10, "invalid", "invalid"),
            ):
                with fixture.engine.begin() as connection:
                    connection.exec_driver_sql("UPDATE portfolio_positions SET shares_integer=?, average_cost=? "
                        "WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol='NORMAL')", (quantity, cost))
                    connection.exec_driver_sql("UPDATE market_bars SET close=? WHERE instrument_id IN "
                        "(SELECT id FROM instruments WHERE symbol='NORMAL')", (price,))
                before = fixture.raw_quote_rows()
                for row in self.safe_json(client.get("/api/portfolio?q=NORMAL"))["items"]:
                    self.assertEqual(row["valuation_status"], {"market_value": market_status, "unrealized_pnl": pnl_status})
                    if market_status != "local_estimate":
                        self.assertIsNone(row["market_value"])
                    if pnl_status != "local_estimate":
                        self.assertIsNone(row["unrealized_pnl"])
                self.assertEqual(fixture.raw_quote_rows(), before)

    def test_post_response_uses_same_projection_after_owned_memory_save(self):
        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        with fixture.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE market_bars SET close=?, trading_date='invalid-date', "
                "open=?, collected_at='invalid-time' WHERE instrument_id IN "
                "(SELECT id FROM instruments WHERE symbol='NEW')", (float("inf"), float("inf")))
        bars_before = fixture.raw_quote_rows()["market_bars"]
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                row = self.safe_json(client.post("/api/portfolio", json={"symbol": "NEW", "exchange": exchange,
                    "shares": 1000, "average_cost": 10, "stop_price": 9}))
                self.assertEqual(row["shares_exact"], "1000")
                self.assertEqual(row["portfolio_value_status"]["stop_price"], "known")
                self.assertEqual(row["portfolio_quote"]["close_status"], "invalid")
                self.assertIsNone(row["market_value"])
        self.assertEqual(fixture.raw_quote_rows()["market_bars"], bars_before)


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
                        expected_status = "quantity_unknown" if total is None else "precision_unsupported" if total > SAFE else "local_estimate"
                        self.assertEqual(row["valuation_status"], dict.fromkeys(("market_value", "unrealized_pnl"), expected_status))
                        if expected_status == "local_estimate":
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
                    self.assertEqual(row["valuation_status"]["market_value"], "local_estimate")
                    self.assertEqual(row["valuation_status"]["unrealized_pnl"], "local_estimate" if expected == "known" else expected)
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


class StockMarketReadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = MemoryFixture(stock_reads=True, stock_cases=True)
        cls.addClassCleanup(cls.shared.close)

    def fixture(self):
        fixture = MemoryFixture(stock_reads=True)
        self.addCleanup(fixture.close)
        return fixture

    def gets(self, fixture, routes):
        before = fixture.raw_quote_rows()
        fixture.read_mutations = 0
        with TestClient(fixture.app) as client:
            results = []
            for route in routes:
                response = client.get(route)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertLessEqual(len(response.content), 2 * 1024 * 1024)
                payload = response.json()
                json.dumps(payload, allow_nan=False)
                results.append(payload)
        self.assertEqual(fixture.raw_quote_rows(), before)
        self.assertEqual(fixture.read_mutations, 0)
        with Session(fixture.engine) as db:
            self.assertLessEqual(len(db.scalars(select(Instrument)).all()), 16)
            self.assertLessEqual(len(db.scalars(select(Signal)).all()), 32)
        self.assertLessEqual(len(before["market_bars"]), 1600)
        self.assertLessEqual(len(before["portfolio_positions"]), 16)
        return results

    def route(self, symbol, explicit=True):
        return f"/api/stocks/TWSE/{symbol}" + (f"?as_of={READ_DAY}" if explicit else "")

    def test_actual_router_polluted_identity_core_and_optional_metadata(self):
        results = self.gets(self.shared, [self.route(symbol) for symbol in STOCK_READS])
        for symbol, payload in zip(STOCK_READS, results):
            self.assertEqual(payload["instrument"]["symbol"], symbol)
            self.assertIsNone(payload["overview"]["price"]["latest"])
            self.assertEqual(payload["overview"]["version"], "stock-overview/p6c-v1")
            if symbol in {"B-CLOSE", "C-DATE", "E-SOURCE", "F-SUSPEND", "G-VOLUME", "H-OHLC", "L-WINDOW"}:
                self.assertEqual(payload["market_read"]["status"], "invalid")
                self.assertNotEqual(payload["quality_summary"]["market"]["status"], "complete")
            elif symbol == "I-MISSING":
                self.assertEqual(payload["market_read"]["status"], "missing")
                self.assertEqual(payload["bars"], [])
            else:
                self.assertEqual(payload["market_read"]["status"], "known")
            if symbol == "D-METADATA":
                latest = payload["bars"][-1]
                self.assertEqual((latest["open"], latest["high"], latest["low"], latest["close"], latest["volume_exact"]), (10, 11, 9, 10.5, "1000"))
                for field in ("data_as_of", "collected_at", "adj_close", "turnover"):
                    self.assertIsNone(latest[field])
                    self.assertEqual(latest["market_read"]["metadata_fields"][field], "invalid")
        instrument = self.gets(self.shared, [f"/api/instruments/D-METADATA?exchange=TWSE&as_of={READ_DAY}"])[0]
        self.assertEqual(instrument["market_read"]["status"], "known")

    def test_default_unknown_date_has_no_older_or_independent_cutoff_fallback(self):
        for symbol in ("C-DATE", "L-WINDOW"):
            default, explicit = self.gets(self.shared, [self.route(symbol, False), self.route(symbol)])
            self.assertIsNone(default["overview"]["as_of"])
            self.assertIsNone(default["decision_summary"])
            self.assertEqual(explicit["overview"]["as_of"], str(READ_DAY))
            self.assertIsNotNone(explicit["decision_summary"])
            self.assertEqual(default["market_read"]["unlocated_count"], 1)
            self.assertEqual(explicit["market_read"]["unlocated_count"], 1)
            self.assertIsNone(explicit["overview"]["price"]["latest"])

    def test_window_cap_order_future_filter_and_outside_unknown_date(self):
        window, future = self.gets(self.shared, [self.route("L-WINDOW"), self.route("K-FUTURE")])
        self.assertEqual(len(window["bars"]), 120)
        self.assertEqual(window["market_read"]["candidate_count"], 120)
        self.assertEqual(window["overview"]["price"]["candidate_count"], 120)
        self.assertEqual(window["bars"][0]["date"], str(READ_DAY - timedelta(days=119)))
        self.assertTrue(all(row["date"] is not None for row in window["bars"]))
        self.assertEqual(window["market_read"]["unlocated_count"], 1)
        self.assertEqual(future["bars"][-1]["date"], str(READ_DAY))
        self.assertEqual(len(future["bars"]), 60)
        history = self.gets(self.shared, [self.route("J-HISTORY")])[0]
        self.assertEqual(len(history["bars"]), 60)
        self.assertIsNone(history["bars"][-2]["close"])
        self.assertEqual(history["bars"][-1]["close"], 10.5)

    def test_volume_affinity_exact_string_and_optional_time_classification(self):
        fixture = self.fixture()
        for value, expected in ((0, 0), (9223372036854775807, 9223372036854775807), (1.5, None), (-1, None), (b"0", None)):
            fixture.stock_change("A-NORMAL", "volume=?", (value,))
            latest = self.gets(fixture, [self.route("A-NORMAL")])[0]["bars"][-1]
            self.assertEqual(latest["volume"], expected)
            self.assertEqual(latest["volume_exact"], str(expected) if expected is not None else None)
        fixture.stock_change("A-NORMAL", "volume=1000,data_as_of=?,collected_at=?", ("2026-10-04 00:00:00", "2026-10-04T01:02:03+08:00"))
        latest = self.gets(fixture, [self.route("A-NORMAL")])[0]["bars"][-1]
        self.assertEqual(latest["market_read"]["status"], "known")
        self.assertEqual(latest["data_as_of"], "2026-10-04T00:00:00")
        self.assertEqual(latest["collected_at"], "2026-10-04T01:02:03+08:00")

    def test_original_m1_source_and_raw_evidence_gates_still_reject(self):
        fixture = self.fixture()
        fixture.stock_change("A-NORMAL", "source='twse',data_as_of='2026-10-04 00:00:00'")
        result = self.gets(fixture, [self.route("A-NORMAL")])[0]
        self.assertEqual(result["market_read"]["status"], "known")
        self.assertIsNone(result["overview"]["price"]["latest"])
        self.assertIn("price_raw_evidence_missing", result["overview"]["price"]["reasons"])
        self.assertIn("price_latest_candidate_unqualified", result["overview"]["price"]["reasons"])
        self.assertEqual(result["overview"]["price"]["valid_count"], 0)
        self.assertEqual(result["overview"]["price"]["candidate_count"], 60)
        self.assertEqual(result["overview"]["historical_pit"], "unsupported")


class ActionMarketReadTest(unittest.TestCase):
    def fixture(self):
        fixture = MemoryFixture(action_reads=True)
        self.addCleanup(fixture.close)
        return fixture

    def safe_json(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        json.dumps(payload, allow_nan=False)
        return payload

    def read_only_gets(self, fixture, routes):
        before = fixture.raw_quote_rows()
        fixture.read_mutations = 0
        with TestClient(fixture.app) as client:
            results = [self.safe_json(client.get(route)) for route in routes]
        self.assertEqual(fixture.raw_quote_rows(), before)
        self.assertEqual(fixture.read_mutations, 0)
        return results

    def test_actual_lists_state_counts_search_and_cursor_keep_polluted_identity(self):
        fixture = self.fixture()
        routes = ["/api/actions?limit=5", "/api/actions?q=A-NORMAL&limit=20",
                  "/api/actions?state=data_insufficient&limit=20", "/api/actions?held_only=true&limit=30",
                  "/api/actions?watchlist_only=true&limit=20", "/api/dashboard", "/api/stocks?page_size=30"]
        first, search, state, held, watched, dashboard, stocks = self.read_only_gets(fixture, routes)
        self.assertEqual(first["summary"]["total"], 24)
        self.assertEqual(first["summary"]["held"], 22)
        self.assertEqual(first["summary"]["held_unknown"], 2)
        self.assertEqual(first["summary"]["scope"], "page_for_actionable_and_data_insufficient_counts")
        self.assertEqual(first["summary"]["data_insufficient"], sum(row["action_state"] == "data_insufficient" for row in first["items"]))
        self.assertEqual(search["summary"]["total"], 2)
        self.assertEqual(state["summary"], {"total": 12, "actionable": 0, "data_insufficient": 12,
                         "held": 12, "held_unknown": 0, "scope": "filtered_results"})
        self.assertEqual(held["summary"]["total"], 22)
        self.assertEqual(held["summary"]["held_unknown"], 0)
        self.assertFalse(any(row["instrument"]["symbol"] == "I-QUNKNOWN" for row in held["items"]))
        self.assertEqual(watched["summary"]["total"], 2)
        self.assertTrue(dashboard["actions"])
        self.assertEqual(stocks["meta"]["total"], 24)
        before = fixture.raw_quote_rows()
        fixture.read_mutations = 0
        pages, items, cursor = 0, [], None
        with TestClient(fixture.app) as client:
            while True:
                payload = self.safe_json(client.get("/api/actions", params={"limit": 5, **({"cursor": cursor} if cursor else {})}))
                items.extend(payload["items"]); pages += 1
                cursor = payload["meta"]["next_cursor"]
                if not cursor:
                    break
            for exchange in ("TWSE", "TPEx"):
                for symbol in ACTION_READS:
                    detail = self.safe_json(client.get(f"/api/actions/{exchange}/{symbol}"))["decision_summary"]
                    row = next(row for row in items if row["instrument"]["exchange"] == exchange and row["instrument"]["symbol"] == symbol)
                    for field in ("action_state", "market_read", "current_price", "price_change", "price_as_of", "held"):
                        self.assertEqual(row[field], detail[field])
                    if symbol in {"B-CLOSE", "C-DATE", "E-SOURCE", "F-SUSPEND"}:
                        self.assertEqual(row["market_read"]["status"], "invalid")
                        self.assertEqual(row["action_state"], "data_insufficient")
                        self.assertIsNone(row["current_price"])
                        self.assertIsNone(row["price_change"])
                        self.assertEqual(row["primary_levels"], {})
                        self.assertIn("market_bar_read_invalid", row["blocking_reasons"])
                        self.assertTrue(any(ref.startswith("market_bar:") for ref in detail["evidence_refs"]))
                    elif symbol == "H-MISSING":
                        self.assertEqual(row["market_read"]["status"], "missing")
                    elif symbol == "K-HISTORY":
                        self.assertEqual(row["market_read"]["status"], "known")
                        self.assertEqual(detail["coverage"]["effective_bar_sessions"], 59)
                        self.assertEqual(row["action_state"], "data_insufficient")
                    elif symbol in {"I-QUNKNOWN", "J-STOPBAD"}:
                        self.assertEqual(row["action_state"], "manual_review")
                    else:
                        self.assertEqual(row["action_state"], "hold_observe")
                        self.assertEqual(row["current_price"], 1e308 if symbol == "L-FUTURE" else 10.5)
                    if symbol == "L-FUTURE":
                        self.assertEqual(row["market_read"], {"status": "known", "invalid_fields": []})
                        self.assertEqual(row["price_as_of"], str(READ_DAY))
                        self.assertTrue(math.isfinite(row["price_change"]))
                        self.assertTrue(math.isfinite(row["price_change_pct"]))
                    if symbol == "G-ADJUST":
                        self.assertIsNone(row["price_change"])
                    if symbol == "D-METADATA":
                        self.assertEqual(row["price_change"], 0)
        self.assertEqual((pages, len(items), len({row["instrument"]["id"] for row in items})), (5, 24, 24))
        self.assertEqual(fixture.raw_quote_rows(), before)
        self.assertEqual(fixture.read_mutations, 0)

    def test_actual_sql_types_invalid_latest_never_coerce_or_fall_back(self):
        fixture = self.fixture()
        with fixture.engine.connect() as connection:
            instrument_id = connection.exec_driver_sql("SELECT id FROM instruments WHERE exchange='TWSE' AND symbol='A-NORMAL'").scalar()
        for field, values in (
            ("close", [-1, 0, float("inf"), float("-inf"), "not-a-price", b"bad-price"]),
            ("source", ["", " ", "bad\nsource", b"twse"]),
            ("is_suspended", [-1, 2, "bad-boolean", b"0"]),
        ):
            for value in values:
                with self.subTest(field=field, value=repr(value)):
                    with fixture.engine.begin() as connection:
                        connection.exec_driver_sql(f"UPDATE market_bars SET {field}=? WHERE instrument_id=? AND trading_date=?",
                                                   (value, instrument_id, str(READ_DAY)))
                        stored, sql_type = connection.exec_driver_sql(f"SELECT {field}, typeof({field}) FROM market_bars "
                            "WHERE instrument_id=? AND trading_date=?", (instrument_id, str(READ_DAY))).one()
                        self.assertEqual(type(stored), float if field == "close" and type(value) in {int, float} else type(value))
                        self.assertIn(sql_type, {"integer", "real", "text", "blob"})
                    result = self.read_only_gets(fixture, ["/api/actions/TWSE/A-NORMAL"])[0]["decision_summary"]
                    self.assertEqual(result["market_read"]["status"], "invalid")
                    self.assertIn(field, result["market_read"]["invalid_fields"])
                    self.assertIsNone(result["current_price"])
                    self.assertEqual(result["action_state"], "data_insufficient")
                    self.assertEqual(result["primary_levels"], {})
                    with fixture.engine.begin() as connection:
                        connection.exec_driver_sql(f"UPDATE market_bars SET {field}=? WHERE instrument_id=? AND trading_date=?",
                            ({"close": 10.5, "source": "fixture-portfolio-value-read", "is_suspended": 0}[field], instrument_id, str(READ_DAY)))
        # NUMERIC affinity transformations are observed, not claimed as original input types.
        for raw, expected in [("10.5", 10.5), (True, 1.0)]:
            with fixture.engine.begin() as connection:
                connection.exec_driver_sql("UPDATE market_bars SET close=? WHERE instrument_id=? AND trading_date=?",
                                          (raw, instrument_id, str(READ_DAY)))
                stored, kind = connection.exec_driver_sql("SELECT close, typeof(close) FROM market_bars WHERE instrument_id=? AND trading_date=?",
                                                         (instrument_id, str(READ_DAY))).one()
            self.assertEqual((stored, kind), (expected, "real"))
            result = self.read_only_gets(fixture, ["/api/actions/TWSE/A-NORMAL"])[0]["decision_summary"]
            self.assertEqual((result["current_price"], result["market_read"]["status"]), (expected, "known"))

    def test_unlocated_dates_outside_cutoff_and_history_cannot_expose_older_close(self):
        from app.decision import _latest_bar, _bars
        fixture = self.fixture()
        for malformed in ("z-invalid-date", "!", "2026-10-00", "2026-02-30", b"bad-date"):
            with fixture.engine.begin() as connection:
                instrument_id, bar_id = connection.exec_driver_sql("SELECT i.id, b.id FROM instruments i JOIN market_bars b "
                    "ON b.instrument_id=i.id WHERE i.exchange='TWSE' AND i.symbol='A-NORMAL' AND b.trading_date=?", (str(READ_DAY),)).one()
                connection.exec_driver_sql("UPDATE market_bars SET trading_date=? WHERE id=?", (malformed, bar_id))
            result = self.read_only_gets(fixture, ["/api/actions/TWSE/A-NORMAL"])[0]["decision_summary"]
            self.assertEqual(result["market_read"], {"status": "invalid", "invalid_fields": ["trading_date"]})
            self.assertIsNone(result["current_price"])
            self.assertIsNone(result["price_as_of"])
            self.assertEqual(result["primary_levels"], {})
            self.assertIn(f"market_bar:{bar_id}", result["evidence_refs"])
            with Session(fixture.engine) as db:
                for cutoff in (None, READ_DAY, READ_DAY - timedelta(days=10)):
                    self.assertEqual(_latest_bar(db, instrument_id, cutoff).id, bar_id)
                    self.assertIsNone(_latest_bar(db, instrument_id, cutoff).trading_date)
                    self.assertTrue(any(row.core_valid for row in _bars(db, instrument_id, cutoff)))
            with fixture.engine.begin() as connection:
                connection.exec_driver_sql("UPDATE market_bars SET trading_date=? WHERE id=?", (str(READ_DAY), bar_id))

    def test_history_cap_cutoff_fallback_batch_and_scope_replacement(self):
        from app.decision import _latest_bar, _bars, _prepare_decision_context, _instrument_coverage
        fixture = self.fixture()
        with fixture.engine.begin() as connection:
            instrument_id = connection.exec_driver_sql("SELECT id FROM instruments WHERE exchange='TWSE' AND symbol='A-NORMAL'").scalar()
            second_id = connection.exec_driver_sql("SELECT id FROM instruments WHERE exchange='TWSE' AND symbol='C-DATE'").scalar()
            connection.exec_driver_sql("DELETE FROM market_bars WHERE instrument_id=?", (instrument_id,))
            for index in range(122):
                connection.exec_driver_sql("INSERT INTO market_bars (instrument_id,trading_date,open,high,low,close,adj_close,volume,turnover,source,collected_at,is_suspended) "
                    "VALUES (?,?,10,11,9,?,10.5,1000,10500,'fixture-portfolio-value-read','unused-invalid',0)",
                    (instrument_id, str(READ_DAY - timedelta(days=index)), b"bad-history" if index == 1 else 10.5))
            connection.exec_driver_sql("INSERT INTO market_bars (instrument_id,trading_date,open,high,low,close,adj_close,volume,turnover,source,collected_at,is_suspended) "
                "VALUES (?,?,100,100,100,100,100,1,1,'fixture-portfolio-value-read','unused-invalid',0)", (instrument_id, str(READ_DAY + timedelta(days=1))))
        before = fixture.raw_quote_rows()
        fixture.read_mutations = 0
        with Session(fixture.engine) as db:
            fallback = _bars(db, instrument_id, READ_DAY)
            self.assertEqual(len(fallback), 120)
            self.assertEqual(fallback[0].trading_date, READ_DAY - timedelta(days=119))
            self.assertEqual(sum(row.core_valid for row in fallback), 119)
            self.assertEqual(_latest_bar(db, instrument_id, READ_DAY).close, 10.5)
            self.assertEqual(_latest_bar(db, instrument_id, None).close, 100)
            self.assertEqual(_latest_bar(db, instrument_id, READ_DAY - timedelta(days=2)).trading_date, READ_DAY - timedelta(days=2))
            old = _prepare_decision_context(db, READ_DAY, [instrument_id])
            self.assertEqual(_bars(db, instrument_id, READ_DAY), fallback)
            new = _prepare_decision_context(db, READ_DAY, [instrument_id, second_id])
            self.assertIsNot(old, new)
            self.assertEqual(new["instrument_ids"], {instrument_id, second_id})
            self.assertIs(_prepare_decision_context(db, READ_DAY, [instrument_id]), new)
            self.assertEqual(_bars(db, instrument_id, READ_DAY), fallback)
            self.assertFalse(_latest_bar(db, second_id, READ_DAY).core_valid)
            coverage = _instrument_coverage(db, db.get(Instrument, instrument_id), READ_DAY, fallback)
            self.assertEqual(coverage["effective_bar_sessions"], 59)
            self.assertEqual(coverage["missing_bars_to_60"], 1)
            # Unknown-date rows outside the 120-row window still prevent latest fallback.
            with fixture.engine.begin() as connection:
                connection.exec_driver_sql("UPDATE market_bars SET trading_date='!' WHERE instrument_id=? AND trading_date=?",
                                          (instrument_id, str(READ_DAY - timedelta(days=121))))
            db.info.clear()
            self.assertIsNone(_latest_bar(db, instrument_id, READ_DAY).trading_date)
        # The last operation above is an intentional fixture mutation, before a new read receipt.
        self.assertNotEqual(fixture.raw_quote_rows(), before)
        self.read_only_gets(fixture, ["/api/actions/TWSE/A-NORMAL"])

    def test_taiex_projection_retains_provenance_and_unknown_baseline(self):
        from app.coverage import verified_taiex_sessions
        fixture = self.fixture()
        with fixture.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE market_bars SET collected_at='unused-invalid',data_as_of='unused-invalid', "
                "close=?,volume=? WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol='TAIEX')", (b"unused-price", b"unused-volume"))
        before = fixture.raw_quote_rows()
        fixture.read_mutations = 0
        with Session(fixture.engine) as db:
            self.assertEqual(len(verified_taiex_sessions(db, end_date=READ_DAY)), 60)
        self.assertEqual(fixture.raw_quote_rows(), before)
        self.assertEqual(fixture.read_mutations, 0)
        with fixture.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE market_bars SET trading_date='z-invalid-date' WHERE trading_date=? "
                "AND instrument_id IN (SELECT id FROM instruments WHERE symbol='TAIEX')", (str(READ_DAY),))
        with Session(fixture.engine) as db:
            self.assertEqual(len(verified_taiex_sessions(db, end_date=READ_DAY)), 59)
            self.assertEqual(len(verified_taiex_sessions(db, require_provenance=False)), 59)
        with fixture.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE market_bars SET source='twse' WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol='TAIEX')")
        result = self.read_only_gets(fixture, ["/api/actions/TWSE/A-NORMAL"])[0]["decision_summary"]
        self.assertEqual(result["coverage"]["coverage_status"], "unknown")
        self.assertIsNone(result["coverage"]["effective_bar_sessions"])
        self.assertIsNone(result["coverage"]["missing_bars_to_60"])
        self.assertEqual(result["action_state"], "data_insufficient")
        self.assertEqual(result["primary_levels"], {})

    def test_adjacent_ratio_and_percent_overflow_remain_unverified_json(self):
        fixture = self.fixture()
        for current, previous, current_adjusted, previous_adjusted in (
            (1e308, 1e-308, 1e308, 1e-308),  # Finite basis, overflowing percentage.
            (1e-308, 1e-308, 1e308, 1e308),  # Both basis ratios overflow to infinity.
            (1e308, 1e308, 1e-308, 1e-308),  # Both positive ratios underflow to zero.
            (11, 10, 11, 10),
        ):
            with fixture.engine.begin() as connection:
                for day, close, adjusted in ((READ_DAY, current, current_adjusted),
                                             (READ_DAY - timedelta(days=1), previous, previous_adjusted)):
                    connection.exec_driver_sql("UPDATE market_bars SET close=?,adj_close=? WHERE trading_date=? "
                        "AND instrument_id IN (SELECT id FROM instruments WHERE symbol='A-NORMAL')", (close, adjusted, str(day)))
            results = self.read_only_gets(fixture, ["/api/actions?q=A-NORMAL&limit=20", "/api/actions/TWSE/A-NORMAL"])
            rows = [*results[0]["items"], results[1]["decision_summary"]]
            for row in rows:
                self.assertEqual(row["current_price"], current)
                self.assertEqual(row["market_read"]["status"], "known")
                if current == 11:
                    self.assertEqual((row["previous_close"], row["price_change"], row["price_change_pct"]), (10, 1, 0.1))
                else:
                    self.assertEqual((row["previous_close"], row["price_change"], row["price_change_pct"]), (None, None, None))

    def test_existing_run_cutoff_strategy_quantity_stop_and_no_asof_gates(self):
        fixture = self.fixture()
        for change, restore in (
            ("UPDATE ingestion_runs SET status='failed'", "UPDATE ingestion_runs SET status='success'"),
            ("UPDATE signals SET data_cutoff='2026-10-05'", "UPDATE signals SET data_cutoff='2026-10-04'"),
            ("UPDATE signals SET data_quality='partial'", "UPDATE signals SET data_quality='complete'"),
            ("UPDATE ingestion_runs SET data_as_of='invalid'", "UPDATE ingestion_runs SET data_as_of='2026-10-04'"),
        ):
            with fixture.engine.begin() as connection:
                connection.exec_driver_sql(change)
            results = self.read_only_gets(fixture, [f"/api/actions/TWSE/{symbol}" for symbol in ("A-NORMAL", "B-CLOSE", "I-QUNKNOWN", "J-STOPBAD")])
            for result in results:
                summary = result["decision_summary"]
                self.assertEqual(summary["action_state"], "data_insufficient")
                self.assertEqual(summary["primary_levels"], {})
                self.assertTrue(summary["blocking_reasons"])
            self.assertIsNone(results[2]["decision_summary"]["held"])
            self.assertEqual(results[3]["decision_summary"]["stop_price_semantics"]["reason"], "invalid_position_stop")
            with fixture.engine.begin() as connection:
                connection.exec_driver_sql(restore)
        with fixture.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE portfolio_positions SET stop_price=11 WHERE instrument_id IN "
                                      "(SELECT id FROM instruments WHERE symbol='A-NORMAL')")
        result = self.read_only_gets(fixture, ["/api/actions/TWSE/A-NORMAL"])[0]["decision_summary"]
        self.assertEqual(result["action_state"], "reduce_exit")
        self.assertEqual(result["stop_price_semantics"]["kind"], "user_position_risk_input")


class StockSignalReadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "--signal-read-case" in sys.argv:
            return
        cls.shared = MemoryFixture(stock_reads=True, signal_reads=True, signal_cases=True)
        cls.addClassCleanup(cls.shared.close)

    def fixture(self):
        fixture = MemoryFixture(stock_reads=True, signal_reads=True)
        self.addCleanup(fixture.close)
        return fixture

    def route(self, symbol, explicit=True):
        return f"/api/stocks/TWSE/{symbol}" + ("?as_of=2026-10-04" if explicit else "")

    def gets(self, fixture, routes):
        global SIGNAL_DIRECT_GETS
        before = fixture.raw_signal_rows()
        fixture.read_mutations = 0
        with TestClient(fixture.app) as client:
            result = []
            for route in routes:
                SIGNAL_DIRECT_GETS += 1
                self.assertLessEqual(SIGNAL_DIRECT_GETS, 96)
                response = client.get(route)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertLessEqual(len(response.content), 2 * 1024 * 1024)
                payload = response.json()
                json.dumps(payload, allow_nan=False)
                result.append(payload)
        after = fixture.raw_signal_rows()
        self.assertEqual(after, before)
        self.assertEqual(fixture.read_mutations, 0)
        digest = hashlib.sha256(repr(before).encode("utf-8")).hexdigest()
        SIGNAL_DIGESTS.append({"sha256": digest, "before_after_equal": True, "table_counts": {table: len(rows) for table, rows in before.items()}})
        self.assertLessEqual(len(before["signals"]), 64)
        self.assertLessEqual(len(before["strategy_versions"]), 16)
        self.assertLessEqual(len(before["market_bars"]), 1600)
        self.assertLessEqual(len(before["portfolio_positions"]), 16)
        with fixture.engine.connect() as connection:
            self.assertLessEqual(connection.exec_driver_sql("SELECT count(*) FROM instruments").scalar_one(), 16)
        return result

    def test_strict_json_date_and_optional_datetime_bounds(self):
        from app.stock_signal_reads import _datetime, read_research_json
        from app.decision_market_reads import read_market_date
        invalid = ["[]", "[1]", "1", '"text"', "true", "null", "{bad", '{"a":1,"a":2}',
                   '{"n":NaN}', '{"n":Infinity}', '{"n":1e309}', '{"n":' + str(10 ** 400) + '}',
                   '{"s":"\\ud800"}', '{"s":"' + "x" * 65536 + '"}', '{"nested":' + "[" * 34 + "0" + "]" * 34 + "}",
                   '{"nodes":[' + ",".join("0" for _ in range(16384)) + "]}", b"{}"]
        for raw in invalid:
            self.assertEqual(read_research_json(raw), (None, "invalid"))
        self.assertEqual(read_research_json(None), (None, "missing"))
        self.assertEqual(read_research_json("{}"), ({}, "known"))
        self.assertEqual(read_research_json('{"n":9223372036854775807}')[1], "known")
        for raw in ("0000-01-01", "2026-02-30", " 2026-10-04", "2026-10-04T00:00:00", READ_DAY, b"2026-10-04"):
            self.assertIsNone(read_market_date(raw))
        self.assertIsNotNone(_datetime("2026-10-04 00:00:00"))
        for raw in ("2026-10-04 00:00:00+00:60", "2026-10-04 00:00:00+01:99", "2026-10-04 00:00:00+24:00"):
            self.assertIsNone(_datetime(raw))

    def test_actual_router_matrix_keeps_identity_slots_and_optional_metadata(self):
        rows = self.gets(self.shared, [self.route(symbol) for symbol in SIGNAL_READS])
        data = dict(zip(SIGNAL_READS, rows))
        self.assertEqual(data["A-NORMAL"]["decision_summary"]["action_state"], "hold_observe")
        self.assertEqual(data["B-JSON"]["signals"][0]["rule_evidence"], None)
        self.assertEqual(data["B-JSON"]["research_read"]["blocked_strategies"], ["breakout_v1"])
        self.assertEqual(data["D-METADATA"]["research_read"]["status"], "known")
        self.assertEqual(data["D-METADATA"]["signals"][0]["signal_read"]["metadata_fields"]["strategy.created_at"], "invalid")
        self.assertEqual(data["D-METADATA"]["decision_summary"]["action_state"], "hold_observe")
        self.assertEqual(data["E-VERSION"]["decision_summary"]["level_semantics"]["kind"], "unknown")
        self.assertEqual(data["E-VERSION"]["decision_summary"]["action_state"], "hold_observe")
        alternate = data["F-ALTERNATE"]
        self.assertEqual(alternate["research_read"]["blocked_strategies"], ["breakout_v1"])
        self.assertEqual(alternate["decision_summary"]["primary_strategy"], "pullback_v1")
        self.assertEqual(alternate["decision_summary"]["action_state"], "hold_observe")
        latest = data["G-LATEST"]
        self.assertEqual(latest["decision_summary"]["action_state"], "data_insufficient")
        self.assertEqual(latest["research_read"]["latest"]["breakout_v1"]["signal_id"], latest["signals"][0]["id"])
        self.assertNotEqual(latest["signals"][0]["id"], latest["signals"][1]["id"])
        window = data["H-WINDOW"]
        self.assertEqual(len(window["signals"]), 20)
        self.assertTrue(all(row["strategy"]["name"] == "custom-research" for row in window["signals"]))
        self.assertNotIn(window["research_read"]["latest"]["breakout_v1"]["signal_id"], window["research_read"]["candidate_order"])
        self.assertEqual(window["decision_summary"]["action_state"], "hold_observe")
        self.assertEqual(data["J-IDENTITY"]["research_read"]["decision_block_scope"], "instrument")
        self.assertEqual(data["K-FUTURE"]["research_read"]["future_count"], 1)
        self.assertEqual(data["K-FUTURE"]["research_read"]["identity_unlocated_count"], 0)
        self.assertEqual(data["K-FUTURE"]["decision_summary"]["action_state"], "hold_observe")
        self.assertIsNone(data["L-RR"]["decision_summary"]["risk_reward"])
        self.assertEqual(data["M-OBSERVATION"]["decision_summary"]["action_state"], "hold_observe")
        self.assertIsNone(data["M-OBSERVATION"]["decision_summary"]["primary_strategy"])
        for row in rows:
            self.assertIsNone(row["overview"]["price"]["latest"])
            self.assertTrue(all(condition["status"] == "data_insufficient" for condition in row["overview"]["conditions"]))

    def test_default_nobars_unlocated_explicit_and_independent_price_cutoff(self):
        dated, nobars, explicit, overview = self.gets(self.shared, [self.route("C-DATE", False), self.route("I-NOBARS", False), self.route("I-NOBARS"), "/api/stocks/TWSE/I-NOBARS/overview"])
        self.assertEqual(dated["overview"]["as_of"], str(READ_DAY))
        self.assertEqual(dated["market_read"]["status"], "known")
        self.assertEqual(dated["decision_summary"]["action_state"], "data_insufficient")
        self.assertIsNone(nobars["overview"]["as_of"])
        self.assertIsNone(nobars["decision_summary"])
        self.assertIsNone(overview["as_of"])
        self.assertEqual(explicit["overview"]["as_of"], str(READ_DAY))

    def test_unlocated_outside_twenty_blocks_research_without_hiding_bars(self):
        fixture = self.fixture()
        fixture.signal_change("WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<22) "
            "INSERT INTO signals(signal_key,signal_date,instrument_id,strategy_version_id,status,entry_type,data_quality,rule_evidence_json,created_at) "
            "SELECT 'bounded-'||n,?,(SELECT id FROM instruments WHERE symbol='A-NORMAL'),1,'observation','conditional','complete','{}','2026-10-04 00:00:00' FROM seq", (str(READ_DAY),))
        fixture.add_signal_copy("A-NORMAL", "outside-date", "0000-01-01")
        explicit, default = self.gets(fixture, [self.route("A-NORMAL"), self.route("A-NORMAL", False)])
        for data in (explicit, default):
            state = data["research_read"]
            self.assertEqual(state["candidate_count"], 20)
            self.assertEqual(state["unlocated_count"], 1)
            self.assertNotIn(state["unlocated_signal_id"], state["candidate_order"])
            self.assertEqual(state["decision_block_scope"], "instrument")
            self.assertEqual(data["market_read"]["status"], "known")
            self.assertEqual(data["decision_summary"]["action_state"], "data_insufficient")

    def test_present_evidence_shape_affinity_and_null_fallback_at_router(self):
        fixture = self.fixture()
        for raw in ("[]", "1", "null", '{"inputs":[]}', '{"levels":null}', '{"inputs":{"group_excess_return_20d":"0.1"}}', '{"risk_reward":1e309}'):
            fixture.change_signal("A-NORMAL", "rule_evidence_json=?", (raw,))
            data = self.gets(fixture, [self.route("A-NORMAL")])[0]
            self.assertEqual(data["research_read"]["blocked_strategies"], ["breakout_v1"])
            self.assertEqual(data["decision_summary"]["action_state"], "data_insufficient")
        for raw in ("{}", '{"risk_reward":null}'):
            fixture.change_signal("A-NORMAL", "rule_evidence_json=?,breakout_price=?", (raw, "12"))
            data = self.gets(fixture, [self.route("A-NORMAL")])[0]
            self.assertEqual(data["decision_summary"]["action_state"], "hold_observe")
            self.assertEqual(data["signals"][0]["breakout_price"], 12)
            self.assertEqual(data["signals"][0]["signal_read"]["metadata_fields"]["rule_evidence"], "known")
        # SQL NULL cannot be stored under the current NOT NULL schema. Exercise
        # its raw projection and original RR fallback without changing that gate.
        from app.stock_signal_reads import _project
        from app.decision import _strategy_result
        with fixture.engine.connect() as connection:
            row = dict(connection.exec_driver_sql("SELECT * FROM signals WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')").mappings().one())
            version = connection.exec_driver_sql("SELECT * FROM strategy_versions WHERE id=?", (row["strategy_version_id"],)).mappings().one()
        row.update(("version_" + key, value) for key, value in version.items())
        row["rule_evidence_json"] = None
        signal = _project(row)
        self.assertIsNone(signal.to_dict(None)["rule_evidence"])
        self.assertEqual(signal.read_state()["metadata_fields"]["rule_evidence"], "missing")
        result = _strategy_result(signal, "breakout_v1", READ_DAY, strategy_version=signal.strategy)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["risk_reward"], 2)
        self.assertIsNone(result["evidence"])
        from app.stock_signal_reads import read_research_json
        for raw in ('{"payload":[' + ','.join('0' for _ in range(16381)) + ']}', '{"payload":"' + 'x' * 65522 + '"}'):
            parsed, state = read_research_json(raw)
            self.assertEqual(state, "known")
            row["rule_evidence_json"] = raw
            projected = _project(row).to_dict(None)
            self.assertEqual(projected["signal_read"]["status"], "known")
            self.assertEqual(projected["rule_evidence"]["payload"], parsed["payload"])
            self.assertIn("level_semantics", projected["rule_evidence"])

    def test_complete_observation_with_null_expected_levels_preserves_holding(self):
        fixture = self.fixture()
        fixture.change_signal("A-NORMAL", "status='observation',breakout_price=NULL,invalid_price=NULL,target_1=NULL,earliest_execution_date=NULL")
        data = self.gets(fixture, [self.route("A-NORMAL")])[0]
        action = data["decision_summary"]
        self.assertEqual(action["action_state"], "hold_observe")
        self.assertEqual(action["data_quality"], "complete")
        self.assertIsNone(action["primary_strategy"])
        self.assertEqual(action["strategies"][0]["missing"], [])
        self.assertTrue(action["strategies"][0]["wait_missing"])
        fixture.change_signal("A-NORMAL", "earliest_execution_date='2026-02-30'")
        invalid = self.gets(fixture, [self.route("A-NORMAL")])[0]
        self.assertEqual(invalid["research_read"]["blocked_strategies"], ["breakout_v1"])

    def test_run_coverage_precede_unknown_quantity_and_invalid_stop(self):
        fixture = self.fixture()
        fixture.signal_change("UPDATE portfolio_positions SET shares_integer='bad',stop_price='bad' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')")
        first = self.gets(fixture, [self.route("A-NORMAL")])[0]["decision_summary"]
        self.assertEqual(first["action_state"], "manual_review")
        self.assertIn("股數", first["display_instruction"])
        fixture.signal_change("UPDATE ingestion_runs SET status='failed'")
        failed = self.gets(fixture, [self.route("A-NORMAL")])[0]["decision_summary"]
        self.assertEqual(failed["action_state"], "data_insufficient")
        fixture.signal_change("UPDATE ingestion_runs SET status='success'")
        fixture.signal_change("DELETE FROM market_bars WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='TAIEX')")
        unknown = self.gets(fixture, [self.route("A-NORMAL")])[0]["decision_summary"]
        self.assertEqual(unknown["action_state"], "data_insufficient")
        self.assertIn("taiex_session_baseline", unknown["blocking_reasons"])

    def test_stock_aliases_and_context_mode_do_not_change_legacy_callers(self):
        fixture = self.fixture()
        stock, instrument = self.gets(fixture, [self.route("A-NORMAL"), "/api/instruments/A-NORMAL?exchange=TWSE&as_of=2026-10-04"])
        self.assertEqual(stock["research_read"], instrument["research_read"])
        from app.decision import build_decision_summary
        with Session(fixture.engine) as db:
            item = db.scalar(select(Instrument).where(Instrument.symbol == "A-NORMAL"))
            raw = build_decision_summary(db, item, READ_DAY, stock_research_reads=True)
            self.assertTrue(db.info["_decision_contexts"][str(READ_DAY)]["stock_research_reads"])
            legacy = build_decision_summary(db, item, READ_DAY)
            self.assertFalse(db.info["_decision_contexts"][str(READ_DAY)]["stock_research_reads"])
            self.assertEqual(legacy["action_state"], raw["action_state"])
            self.assertNotIn("research_read", legacy)


class StockIndependentReadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = MemoryFixture(stock_reads=True, independent_reads=True)
        cls.addClassCleanup(cls.shared.close)

    def route(self, symbol, explicit=True):
        return f"/api/stocks/TWSE/{symbol}" + ("?as_of=2026-10-04" if explicit else "")

    def gets(self, routes):
        global INDEPENDENT_DIRECT_GETS
        fixture = self.shared
        before = fixture.raw_independent_rows()
        fixture.read_mutations = 0
        results = []
        with TestClient(fixture.app) as client:
            for route in routes:
                INDEPENDENT_DIRECT_GETS += 1
                self.assertLessEqual(INDEPENDENT_DIRECT_GETS, 160)
                response = client.get(route)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertLessEqual(len(response.content), 2 * 1024 * 1024)
                payload = response.json()
                json.dumps(payload, allow_nan=False)
                results.append(payload)
        self.assertEqual(fixture.raw_independent_rows(), before)
        self.assertEqual(fixture.read_mutations, 0)
        caps = {"technical_features": 32, "chip_snapshots": 256, "signals": 64, "strategy_versions": 16,
                "portfolio_positions": 16, "market_bars": 1600}
        for table, rows in before.items():
            self.assertLessEqual(len(rows), caps[table])
        with fixture.engine.connect() as connection:
            self.assertLessEqual(connection.exec_driver_sql("SELECT count(*) FROM instruments").scalar(), 16)
        digest = hashlib.sha256(repr(before).encode("utf-8")).hexdigest()
        receipt = {"sha256": digest, "before_after_equal": True,
                   "table_counts": {table: len(rows) for table, rows in before.items()}}
        if receipt not in INDEPENDENT_DIGESTS:
            INDEPENDENT_DIGESTS.append(receipt)
        return results

    def test_pure_complete_dtos_and_strict_json_bounds(self):
        from app.stock_independent_reads import CHIP_NUMBERS, project_chip, project_feature
        base = {"id": 1, "instrument_id": 2, "trading_date": "2026-10-04", "source": "fixture",
                "created_at": "2026-10-04 00:00:00", "features_json": '{"ma20":-1,"ma60":0}'}
        feature = project_feature(base)
        self.assertEqual(feature.features_json, {"ma20": -1.0, "ma60": 0.0})
        self.assertEqual(feature.read_state()["status"], "known")
        self.assertEqual(len(feature.fields), 8)
        # SQL NULL is a pure projection distinction; the actual JSON column is NOT NULL.
        for raw, expected in ((None, "missing"), ('null', "invalid"), ('[]', "invalid"), ('1', "invalid"),
                              ('{"a":1,"a":2}', "invalid"), ('{"a":NaN}', "invalid"),
                              ('{"a":1e999}', "invalid"), ('{"a":"\\ud800"}', "invalid"),
                              ('{"a":"' + 'x' * 65536 + '"}', "invalid"),
                              ('{"a":' + '[' * 33 + '0' + ']' * 33 + '}', "invalid"),
                              ('{"a":[' + ','.join('0' for _ in range(16384)) + ']}', "invalid")):
            self.assertEqual(project_feature({**base, "features_json": raw}).fields["features_json"], expected)
        for raw in ('{"ma20":true}', '{"ma20":"10"}', '{"ma20":{}}'):
            row = project_feature({**base, "features_json": raw})
            self.assertEqual(row.features_json["ma20"], None)
            self.assertEqual(row.read_state()["status"], "invalid")
        for key in ("trading_date", "created_at", "source", "id", "instrument_id"):
            self.assertEqual(project_feature({**base, key: b'bad'}).fields[key], "invalid")
        chip = {"id": 1, "instrument_id": 2, "trading_date": "2026-10-04", "source": "fixture",
                "data_as_of": "2026-10-04T00:00:00+08:00", "collected_at": "2026-10-04 00:00:00", "raw_payload_id": None,
                **{key: -1 for key in CHIP_NUMBERS}}
        self.assertEqual(len(project_chip(chip).fields), 15)
        self.assertEqual(project_chip(chip).read_state()["status"], "known")
        for key in CHIP_NUMBERS:
            for raw, expected in ((None, 'missing'), ('1', 'invalid'), (True, 'invalid'), (float('inf'), 'invalid'), (b'bad', 'invalid')):
                self.assertEqual(project_chip({**chip, key: raw}).fields[key], expected)

    def test_actual_matrix_local_isolation_and_no_latest_fallback(self):
        rows = dict(zip(INDEPENDENT_READS, self.gets([self.route(symbol) for symbol in INDEPENDENT_READS])))
        for symbol, payload in rows.items():
            self.assertEqual(payload["overview"]["price"]["latest"], None)
            self.assertEqual(payload["overview"]["historical_pit"], "unsupported")
            if symbol != "I-NOBARS":
                self.assertEqual(payload["market_read"]["status"], "known")
                self.assertEqual(payload["decision_summary"]["action_state"], "hold_observe")
        self.assertIsNone(rows["B-JSON"]["feature_snapshot"]["features_json"])
        self.assertEqual(rows["B-JSON"]["features"], {})
        self.assertEqual(rows["B-JSON"]["feature_read"]["candidate_count"], 1)
        self.assertEqual(rows["C-DATE"]["feature_read"]["unlocated_count"], 1)
        self.assertIsNone(rows["C-DATE"]["feature_snapshot"]["trading_date"])
        self.assertEqual(rows["D-METADATA"]["feature_read"]["status"], "known")
        self.assertEqual(rows["D-METADATA"]["chips"][0]["row_read"]["status"], "known")
        for key in ("source", "data_as_of", "collected_at", "raw_payload_id"):
            self.assertIsNone(rows["D-METADATA"]["chips"][0][key])
        self.assertIsNone(rows["E-CHIP"]["chips"][0]["foreign_buy"])
        self.assertIsNone(rows["E-CHIP"]["chips"][0]["margin_change"])
        self.assertEqual(rows["J-OBSERVATION"]["decision_summary"]["primary_strategy"], None)
        self.assertEqual(rows["J-OBSERVATION"]["decision_summary"]["primary_levels"]["kind"], "risk")
        self.assertIsNone(rows["J-OBSERVATION"]["decision_summary"]["primary_levels"]["stop"])
        self.assertTrue(all(rows["J-OBSERVATION"]["decision_summary"][key] is None for key in
                            ("trigger_price", "entry_low", "entry_high", "invalid_price", "stop_price", "target_1", "target_2")))

    def test_actual_float_affinity_keeps_all_eight_nullable_fields(self):
        from app.stock_independent_reads import CHIP_NUMBERS
        fixture = self.shared
        for field in CHIP_NUMBERS:
            with fixture.engine.connect() as connection:
                chip_id, original = connection.exec_driver_sql(f"SELECT id,{field} FROM chip_snapshots WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL') ORDER BY trading_date DESC LIMIT 1").one()
            for raw, expected in ((None, 'missing'), (0, 'known'), (-1, 'known'), ('12.5', 'known'), (True, 'known'),
                                  (float('inf'), 'invalid'), ('bad-value', 'invalid'), (b'bad-value', 'invalid')):
                fixture.independent_change(f"UPDATE chip_snapshots SET {field}=? WHERE id=?", (raw, chip_id))
                try:
                    payload = self.gets([self.route('A-NORMAL')])[0]
                    latest = payload['chips'][-1]
                    self.assertEqual(latest['row_read']['metadata_fields'][field], expected)
                    self.assertEqual(payload['decision_summary']['action_state'], 'hold_observe')
                    with fixture.engine.connect() as connection:
                        stored, kind = connection.exec_driver_sql(f"SELECT {field},typeof({field}) FROM chip_snapshots WHERE id=?", (chip_id,)).one()
                    if expected == 'known':
                        self.assertEqual(latest[field], stored)
                        self.assertIn(kind, ('integer', 'real'))
                    else:
                        self.assertIsNone(latest[field])
                finally:
                    fixture.independent_change(f"UPDATE chip_snapshots SET {field}=? WHERE id=?", (original, chip_id))

    def test_actual_json_consumed_values_and_nullable_ma(self):
        fixture = self.shared
        for raw, expected in (('[]','invalid'), ('null','invalid'), ('1','invalid'), ('{"a":1,"a":2}','invalid'),
                              ('{"a":NaN}','invalid'), ('{"a":1e999}','invalid'), ('{"ma20":true}','invalid'),
                              ('{"ma20":"10"}','invalid'), ('{"ma20":-1,"ma60":0}','known'), ('{}','known')):
            fixture.independent_change("UPDATE technical_features SET features_json=? WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')", (raw,))
            try:
                payload = self.gets([self.route('A-NORMAL')])[0]
                self.assertEqual(payload['feature_read']['status'], expected)
                self.assertEqual(payload['decision_summary']['action_state'], 'hold_observe')
            finally:
                fixture.independent_change("UPDATE technical_features SET features_json='{\"ma20\":10,\"ma60\":9}' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')")

    def test_actual_date_datetime_and_source_processors_are_bypassed(self):
        fixture = self.shared
        for table, field in (("technical_features", "trading_date"), ("technical_features", "created_at"),
                             ("chip_snapshots", "trading_date"), ("chip_snapshots", "data_as_of"), ("chip_snapshots", "collected_at")):
            with fixture.engine.connect() as connection:
                row_id, original = connection.exec_driver_sql(f"SELECT id,{field} FROM {table} WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL') ORDER BY trading_date DESC LIMIT 1").one()
            for raw in ('!bad-time', b'bad-time'):
                fixture.independent_change(f"UPDATE {table} SET {field}=? WHERE id=?", (raw, row_id))
                try:
                    payload = self.gets([self.route('A-NORMAL')])[0]
                    if table == 'technical_features':
                        row = payload['feature_snapshot']
                    else:
                        row = next(row for row in payload['chips'] if row['id'] == row_id)
                    self.assertEqual(row['row_read']['metadata_fields'][field], 'invalid')
                    self.assertEqual(payload['decision_summary']['action_state'], 'hold_observe')
                finally:
                    fixture.independent_change(f"UPDATE {table} SET {field}=? WHERE id=?", (original, row_id))

    def test_window_unlocated_default_and_explicit_cutoff_scopes(self):
        future, window, unlocated, default, explicit, healthy = self.gets([
            self.route('G-FUTURE'), self.route('H-WINDOW'), self.route('F-UNLOCATED'),
            self.route('I-NOBARS', False), self.route('I-NOBARS'), self.route('C-DATE', False)])
        self.assertEqual(future['feature_read']['future_count'], 1)
        self.assertEqual(future['chip_read']['future_count'], 1)
        self.assertEqual(future['feature_snapshot']['trading_date'], str(READ_DAY))
        self.assertEqual(len(window['chips']), 120)
        self.assertEqual(window['chip_read']['scanned_count'], 121)
        self.assertIsNone(window['chips'][-1]['foreign_buy'])
        self.assertEqual(unlocated['chip_read']['candidate_count'], 120)
        self.assertEqual(unlocated['chip_read']['unlocated_count'], 1)
        self.assertFalse(any(row['date'] is None for row in unlocated['chips']))
        self.assertIsNone(default['overview']['as_of'])
        self.assertIsNone(default['decision_summary'])
        self.assertEqual(explicit['overview']['as_of'], str(READ_DAY))
        self.assertEqual(healthy['overview']['as_of'], str(READ_DAY))
        self.assertEqual(healthy['decision_summary']['action_state'], 'hold_observe')

    def test_necessary_chip_gate_and_existing_decision_priorities(self):
        fixture = self.shared
        fixture.independent_change("UPDATE portfolio_positions SET shares_integer=0 WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='F-UNLOCATED')")
        try:
            self.assertEqual(self.gets([self.route('F-UNLOCATED')])[0]['decision_summary']['action_state'], 'conditional_entry')
        finally:
            fixture.independent_change("UPDATE portfolio_positions SET shares_integer=1000 WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='F-UNLOCATED')")
        fixture.independent_change("UPDATE signals SET data_quality='partial' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='F-UNLOCATED')")
        try:
            summary = self.gets([self.route('F-UNLOCATED')])[0]['decision_summary']
            self.assertEqual(summary['action_state'], 'data_insufficient')
            self.assertIn('institutional_flow_5d', summary['blocking_reasons'])
        finally:
            fixture.independent_change("UPDATE signals SET data_quality='complete' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='F-UNLOCATED')")
        for change, restore, expected in (
            ("UPDATE portfolio_positions SET shares_integer='bad' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')",
             "UPDATE portfolio_positions SET shares_integer=1000 WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')", 'manual_review'),
            ("UPDATE portfolio_positions SET stop_price='bad' WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')",
             "UPDATE portfolio_positions SET stop_price=NULL WHERE instrument_id=(SELECT id FROM instruments WHERE symbol='A-NORMAL')", 'manual_review'),
            ("UPDATE ingestion_runs SET status='failed'", "UPDATE ingestion_runs SET status='success'", 'data_insufficient')):
            fixture.independent_change(change)
            try:
                self.assertEqual(self.gets([self.route('A-NORMAL')])[0]['decision_summary']['action_state'], expected)
            finally:
                fixture.independent_change(restore)

    def test_aliases_and_raw_legacy_context_purpose_remain_separate(self):
        from app.decision import build_decision_summary
        from app.stock_independent_reads import StockChipRead
        fixture = self.shared
        before = fixture.raw_independent_rows()
        with Session(fixture.engine) as db:
            instrument = db.scalar(select(Instrument).where(Instrument.symbol == 'A-NORMAL'))
            for raw in (True, False, True):
                build_decision_summary(db, instrument, READ_DAY, stock_research_reads=raw)
                context = db.info['_decision_contexts'][str(READ_DAY)]
                self.assertEqual(context['stock_research_reads'], raw)
                self.assertEqual(isinstance(context['chips_by_instrument'][instrument.id][0], StockChipRead), raw)
        self.assertEqual(before, fixture.raw_independent_rows())
        stock, alias = self.gets([self.route('A-NORMAL'), '/api/instruments/A-NORMAL?exchange=TWSE&as_of=2026-10-04'])
        self.assertEqual(stock['feature_read'], alias['feature_read'])
        self.assertEqual(stock['chip_read'], alias['chip_read'])


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
    parser.add_argument("--quote-read-only", action="store_true", help="local quote projection and calculation boundaries; zero disk")
    parser.add_argument("--quote-read-fixture", action="store_true", help="serve twenty owned read-only local quote positions")
    parser.add_argument("--action-read-only", action="store_true", help="action market read isolation and necessary guarded regressions; zero disk")
    parser.add_argument("--action-read-fixture", action="store_true", help="serve twenty-four read-only synthetic action positions with explicit fixture sessions")
    parser.add_argument("--stock-read-only", action="store_true", help="stock detail read isolation through actual router; zero disk")
    parser.add_argument("--stock-read-fixture", action="store_true", help="serve twelve read-only stock detail cases; no admitted M1 raw files")
    parser.add_argument("--stock-read-case", choices=["router-matrix"], help="necessary affected stock router regression only")
    parser.add_argument("--signal-read-only", action="store_true", help="stock research raw reads through actual router; zero disk")
    parser.add_argument("--signal-read-case", choices=["evidence-shape"], help="only the affected evidence method; preserve prior valid receipts")
    parser.add_argument("--signal-read-fixture", action="store_true", help="serve thirteen read-only synthetic stock research cases")
    parser.add_argument("--independent-read-only", action="store_true", help="only stock feature/chip raw projections and necessary memory checks")
    parser.add_argument("--independent-read-fixture", action="store_true", help="serve ten bounded read-only independent snapshot cases")
    parser.add_argument("--independent-read-case", choices=["router-matrix"], help="only affected new router matrix; retain passed receipts")
    args = parser.parse_args()
    if args.serve:
        if args.port != 8777:
            parser.error("only owned loopback port 8777 is authorized")
        _listen_port = args.port
        fixture = MemoryFixture(value_reads=args.finance_read_fixture, quantity_trust=args.quantity_trust_fixture, quote_reads=args.quote_read_fixture,
                                 action_reads=args.action_read_fixture, stock_reads=args.stock_read_fixture or args.signal_read_fixture or args.independent_read_fixture, stock_cases=args.stock_read_fixture,
                                 signal_reads=args.signal_read_fixture, signal_cases=args.signal_read_fixture, independent_reads=args.independent_read_fixture)
        try:
            import uvicorn
            fixture.server = uvicorn.Server(uvicorn.Config(fixture.app, host="127.0.0.1", port=args.port,
                                                          lifespan="off", access_log=False))
            print(json.dumps({"mode": "synthetic-independent-read-memory-actual-router" if args.independent_read_fixture else "synthetic-signal-read-memory-actual-router" if args.signal_read_fixture else "synthetic-stock-read-memory-actual-router" if args.stock_read_fixture else "synthetic-action-read-memory-actual-router" if args.action_read_fixture else "synthetic-local-quote-memory-actual-router" if args.quote_read_fixture else "synthetic-quantity-trust-memory-actual-router" if args.quantity_trust_fixture else "synthetic-value-read-memory-actual-router" if args.finance_read_fixture else "synthetic-user-quantity-memory-actual-router",
                              "fixture_date": str(READ_DAY if args.finance_read_fixture or args.quantity_trust_fixture or args.quote_read_fixture or args.action_read_fixture or args.stock_read_fixture or args.signal_read_fixture or args.independent_read_fixture else DAY),
                              "pid": os.getpid(), "url": f"http://127.0.0.1:{args.port}", "disk_artifacts": 0,
                              "disk_save_reopen": "not_tested"}), flush=True)
            fixture.server.run()
        finally:
            fixture.close()
            if args.independent_read_fixture:
                print(json.dumps({"mode": "independent-read-owned-server-final", "pid": os.getpid(),
                    "actual_http_requests_including_review_shutdown": HTTP_REQUESTS,
                    "product_requests": fixture.product_requests, "review_requests": fixture.review_requests,
                    "read_mutations": fixture.read_mutations, "targeted_setup_mutations": INDEPENDENT_SETUP_MUTATIONS,
                    "unexpected_denials": UNEXPECTED_DENIALS, "disk_artifacts": 0, "disk_save_reopen": "not_tested"}), flush=True)
            if args.signal_read_fixture:
                print(json.dumps({"mode": "signal-read-owned-server-final", "actual_http_requests_including_review_shutdown": HTTP_REQUESTS,
                    "read_mutations": fixture.read_mutations, "setup_mutations": SIGNAL_SETUP_MUTATIONS,
                    "unexpected_denials": UNEXPECTED_DENIALS, "disk_artifacts": 0, "disk_save_reopen": "not_tested"}), flush=True)
            if args.stock_read_fixture:
                print(json.dumps({"mode": "stock-read-owned-server-final", "actual_http_requests_including_review_shutdown": HTTP_REQUESTS,
                    "read_mutations": fixture.read_mutations, "setup_mutations": STOCK_SETUP_MUTATIONS,
                    "unexpected_denials": UNEXPECTED_DENIALS, "disk_artifacts": 0,
                    "disk_save_reopen": "not_tested"}), flush=True)
    else:
        if args.independent_read_only:
            suite = unittest.TestSuite([StockIndependentReadTest("test_actual_matrix_local_isolation_and_no_latest_fallback")]) if args.independent_read_case else unittest.TestSuite([
                unittest.defaultTestLoader.loadTestsFromTestCase(StockIndependentReadTest), ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        elif args.signal_read_only:
            suite = unittest.TestSuite([StockSignalReadTest("test_present_evidence_shape_affinity_and_null_fallback_at_router")]) if args.signal_read_case else unittest.TestSuite([
                unittest.defaultTestLoader.loadTestsFromTestCase(StockSignalReadTest), ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        elif args.stock_read_only:
            suite = unittest.TestSuite([StockMarketReadTest("test_actual_router_polluted_identity_core_and_optional_metadata")]) if args.stock_read_case else unittest.TestSuite([
                unittest.defaultTestLoader.loadTestsFromTestCase(StockMarketReadTest), ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        elif args.action_read_only:
            suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(ActionMarketReadTest),
                PortfolioValueReadTest("test_existing_source_time_and_strategy_gates_precede_invalid_stop"),
                ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        elif args.quote_read_only:
            suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(PortfolioQuoteReadTest),
                QuantityTrustReadTest("test_valuation_status_missing_invalid_and_finite_guard"),
                ShareQuantityExactTest("test_audit_denies_disk_external_network_and_subprocess")])
        elif args.quantity_trust_only:
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
        print(json.dumps({"tests": result.testsRun, "success": success, "fixture_date": str(READ_DAY if args.finance_read_only or args.quantity_trust_only or args.quote_read_only or args.action_read_only or args.stock_read_only or args.signal_read_only or args.independent_read_only else DAY),
                          "actual_router_requests": HTTP_REQUESTS, "disk_artifacts": 0,
                          "expected_denials": EXPECTED_DENIALS, "unexpected_denials": UNEXPECTED_DENIALS,
                          **({"independent_direct_gets": INDEPENDENT_DIRECT_GETS, "targeted_setup_mutations": INDEPENDENT_SETUP_MUTATIONS,
                              "read_mutations": 0,
                              "whole_sql_scope": "technical_features + chip_snapshots + signals + strategy_versions + portfolio_positions + market_bars: all columns and all typeof()",
                              "digest_receipts": INDEPENDENT_DIGESTS, "source_and_date_evidence": "synthetic only; no source/PIT or M1 raw gate upgrade",
                              "python": sys.version.split()[0], "sqlalchemy": sys.modules["sqlalchemy"].__version__,
                              "pydantic": sys.modules["pydantic"].__version__} if args.independent_read_only else {}),
                          **({"signal_direct_gets": SIGNAL_DIRECT_GETS, "setup_mutations": SIGNAL_SETUP_MUTATIONS, "read_mutations": 0,
                              "whole_sql_scope": "signals + strategy_versions + portfolio_positions + market_bars: all columns and all typeof()",
                              "digest_receipts": SIGNAL_DIGESTS, "source_and_date_evidence": "synthetic only; source/time/M1 raw filesystem gates unchanged",
                              "python": sys.version.split()[0], "sqlalchemy": sys.modules["sqlalchemy"].__version__,
                              "pydantic": sys.modules["pydantic"].__version__} if args.signal_read_only else {}),
                          **({"stock_ui_records": 12, "read_mutations": 0, "setup_mutations": STOCK_SETUP_MUTATIONS,
                              "whole_sql_scope": "portfolio_positions + market_bars: all columns and all typeof()",
                              "source_and_date_evidence": "unverified; M1 source/raw filesystem admission unchanged",
                              "python": sys.version.split()[0], "sqlalchemy": sys.modules["sqlalchemy"].__version__,
                              "pydantic": sys.modules["pydantic"].__version__} if args.stock_read_only else {}),
                          **({"action_ui_records": 24, "read_mutations": 0,
                              "whole_sql_scope": "portfolio_positions + market_bars: all columns and all typeof()",
                              "decision_calendar": "sixty explicit synthetic fixture dates, not real official sessions",
                              "python": sys.version.split()[0], "sqlalchemy": sys.modules["sqlalchemy"].__version__,
                              "pydantic": sys.modules["pydantic"].__version__} if args.action_read_only else {}),
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
                          **({"quote_ui_records": 20, "read_mutations": 0, "owned_memory_save_requests": 2,
                              "whole_sql_scope": "portfolio_positions + market_bars: all columns and all typeof()",
                              "sqlite_close_conversions": "REAL affinity: bool/numeric text become float; None/NaN rejected by NOT NULL",
                              "source_and_date_evidence": "unverified; no filesystem gate or market calendar verification",
                              "python": sys.version.split()[0], "sqlalchemy": sys.modules["sqlalchemy"].__version__,
                              "pydantic": sys.modules["pydantic"].__version__} if args.quote_read_only else {}),
                          "disk_save_reopen": "not_tested"}), flush=True)
        return 0 if success else 1
    print(json.dumps({"owned_memory_server": "closed", "unexpected_denials": UNEXPECTED_DENIALS}), flush=True)
    return 0 if not UNEXPECTED_DENIALS else 1


if __name__ == "__main__":
    raise SystemExit(main())
