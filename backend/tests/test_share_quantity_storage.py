"""Reconstructable M3-P2 memory checks and one bounded synthetic SQLite file.

Run directly with -B -X utf8. Default mode creates no files or directories.
Disk modes require the exact reviewed --root; --disk removes each sequential
case and the root in finally. --prepare/--serve retain the one DB solely for
the reviewed cross-process product check; --cleanup ends that check.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import closing
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch

STANDALONE = __name__ == "__main__"
OWNED_ROOT = Path("C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m3-share-storage-01a10250")
OWNED_DB = OWNED_ROOT / "data" / "quantity.db"
OWNED_FILES = {OWNED_DB, Path(str(OWNED_DB) + "-journal")}
OWNED_DIRS = {OWNED_ROOT, OWNED_ROOT / "data", OWNED_ROOT / "raw"}
SAFE, ODD, MAXIMUM = 9007199254740991, 9007199254740993, 9223372036854775807
HEAD, PREVIOUS = "0008_portfolio_share_integer", "0007_turnover_availability"
DAY = date(2026, 10, 3)
PEAK = {"files": 0, "directories": 0, "bytes": 0, "db_bytes": 0}
UNEXPECTED_DENIALS = []
DISK = False
SERVING = False
ARGS = None


def _nonreparse(path):
    stat = path.lstat()
    if path.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("refusing a reparse point: " + str(path))


def inventory():
    """Check only the exact owned root, without following unknown directories."""
    for parent in [OWNED_ROOT, *OWNED_ROOT.parents]:
        if parent.exists():
            _nonreparse(parent)
    if not OWNED_ROOT.exists():
        return {"files": 0, "directories": 0, "bytes": 0, "db_bytes": 0}
    files, directories, total, db_bytes = 0, 1, 0, 0
    pending = [OWNED_ROOT]
    while pending:
        directory = pending.pop()
        for child in directory.iterdir():
            _nonreparse(child)
            if child.is_dir():
                if child not in OWNED_DIRS:
                    raise RuntimeError("unexpected owned directory: " + str(child))
                directories += 1
                pending.append(child)
            elif child.is_file() and child in OWNED_FILES:
                files += 1
                size = child.stat().st_size
                total += size
                if child == OWNED_DB:
                    db_bytes = size
            else:
                raise RuntimeError("unexpected owned file: " + str(child))
    observed = dict(files=files, directories=directories, bytes=total, db_bytes=db_bytes)
    if files > 2 or directories > 3 or total > 2 * 1024**2 or db_bytes > 1024**2:
        raise RuntimeError("owned disk quota exceeded: " + json.dumps(observed))
    for key, value in observed.items():
        PEAK[key] = max(PEAK[key], value)
    return observed


def remove_database():
    inventory()
    for path in sorted(OWNED_FILES):
        if path.exists():
            _nonreparse(path)
            path.unlink()
    inventory()


def cleanup():
    """Never remove an unknown file, reparse point or another root."""
    remove_database()
    for path in sorted(OWNED_DIRS, key=lambda item: len(item.parts), reverse=True):
        if path.exists():
            _nonreparse(path)
            path.rmdir()
    return inventory()


def _socketpair_context():
    frame = sys._getframe(1)
    while frame:
        if "socketpair" in frame.f_code.co_name and frame.f_code.co_filename.endswith("socket.py"):
            return True
        frame = frame.f_back
    return False


def _audit(event, args):
    forbidden = event in {"os.rename", "os.link", "os.symlink", "os.truncate", "os.chmod", "os.utime",
                          "os.system", "subprocess.Popen", "os.posix_spawn", "os.exec", "os.fork", "os.startfile",
                          "socket.sendto", "socket.sendmsg"}
    if event in {"os.mkdir", "os.remove", "os.rmdir"}:
        allowed = OWNED_DIRS if event in {"os.mkdir", "os.rmdir"} else OWNED_FILES
        forbidden = not DISK or Path(args[0]).absolute() not in allowed
        if not forbidden:
            inventory()
    if event == "open":
        mode, flags = args[1:3]
        writes = (isinstance(mode, str) and any(char in mode for char in "wax+")) or bool(
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writes:
            forbidden = not DISK or not isinstance(args[0], (str, bytes, os.PathLike)) or Path(args[0]).absolute() not in OWNED_FILES
    if event == "sqlite3.connect":
        target = str(args[0])
        if target == ":memory:":
            forbidden = False
        elif DISK and target == str(OWNED_DB):
            inventory()
            forbidden = False
        elif DISK and target == OWNED_DB.as_uri() + "?mode=ro":
            inventory()
            forbidden = False
        else:
            forbidden = True
    if event in {"socket.bind", "socket.connect"}:
        address = args[1]
        local = isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
        forbidden = not (local and (_socketpair_context() or (
            SERVING and event == "socket.bind" and address[1] == 8779)))
    if event == "socket.getaddrinfo":
        forbidden = args[0] not in {"localhost", "127.0.0.1", "::1", None}
    if event in {"socket.gethostbyname", "socket.gethostbyaddr"}:
        forbidden = args[0] not in {"localhost", "127.0.0.1", "::1"}
    if forbidden:
        UNEXPECTED_DENIALS.append(event)
        raise PermissionError("bounded share storage validation denied " + event)


if STANDALONE:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    for mode in ("disk", "prepare", "serve", "inspect", "cleanup"):
        modes.add_argument("--" + mode, action="store_true")
    modes.add_argument("--memory-storage", action="store_true", help="run only affected storage memory cases")
    parser.add_argument("--root")
    ARGS = parser.parse_args()
    DISK = any(getattr(ARGS, mode) for mode in ("disk", "prepare", "serve", "inspect", "cleanup"))
    SERVING = ARGS.serve
    if DISK and (ARGS.root is None or Path(ARGS.root).absolute() != OWNED_ROOT):
        parser.error("disk mode requires the exact reviewed --root " + str(OWNED_ROOT))
    if not DISK and ARGS.root is not None:
        parser.error("memory mode does not use a disk root")
    # Evaluate the real config without its directory-creation expressions;
    # formal DB paths are never imported by this standalone test process.
    config_path = Path(__file__).resolve().parents[1] / "app" / "config.py"
    tree = ast.parse(config_path.read_text(encoding="utf-8"), filename=str(config_path))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "mkdir")]
    config_stub = types.ModuleType("app.config")
    config_stub.__file__ = str(config_path)
    exec(compile(tree, str(config_path), "exec"), config_stub.__dict__)
    config_stub.DATA_DIR = OWNED_ROOT / "data" if DISK else Path("__memory_only__")
    config_stub.RAW_DIR = OWNED_ROOT / "raw" if DISK else Path("__memory_only__/raw")
    config_stub.DB_PATH = OWNED_DB if DISK else Path(":memory:")
    sys.modules["app.config"] = config_stub
    sys.dont_write_bytecode = True
    sys.addaudithook(_audit)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from sqlalchemy.pool import NullPool

from app import api, database_readiness as readiness, migrations
from app.db import Base, enable_sqlite_foreign_keys
from app.models import Instrument, MarketBar, PortfolioPosition
from app.portfolio_share_migration import check_portfolio_share_column
from app.units import shares_from_position_quantity, trusted_position_shares
from test_share_quantity_exact_presentation import MemoryFixture, ShareQuantityExactTest


def engine_for(path=None):
    engine = create_engine("sqlite:///:memory:" if path is None else "sqlite:///" + str(path), poolclass=NullPool if path else None)
    # A memory DB must keep its one connection; NullPool is only for disk.
    enable_sqlite_foreign_keys(engine)
    return engine


def upgrade(engine, mode):
    (migrations.upgrade_database if mode == "alembic" else migrations._fallback_upgrade)(engine)


def rows(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT id,instrument_id,shares,typeof(shares),average_cost,stop_price,risk_budget,note,updated_at "
            "FROM portfolio_positions ORDER BY id"
        ).all()


def snapshot(engine):
    with engine.connect() as connection:
        schema = connection.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all()
        values = {}
        for kind, name, _, _ in schema:
            if kind == "table":
                quoted = '"' + name.replace('"', '""') + '"'
                values[name] = connection.exec_driver_sql("SELECT * FROM " + quoted).all()
        return schema, values


def legacy(engine, *, parent=False, marker=True, marker_mode="alembic"):
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        if parent:
            connection.exec_driver_sql("DROP TABLE instruments")
            ddl = str(CreateTable(Instrument.__table__).compile(engine)).replace(
                "uq_instrument_exchange_symbol UNIQUE (exchange, symbol)",
                "uq_instrument_market_symbol UNIQUE (market, symbol)")
            ddl = ddl.replace("exchange VARCHAR(20) DEFAULT 'TWSE' NOT NULL", "exchange VARCHAR(20) NOT NULL DEFAULT 'TWSE'")
            connection.exec_driver_sql(ddl)
        else:
            connection.exec_driver_sql("ALTER TABLE portfolio_positions DROP COLUMN shares_integer")
        exchanges = ("TWSE",) if parent else ("TWSE", "TPEx")
        position_id = 0
        cases = {"ZERO0": 0.0, "LOT1": 1000.0, "MIXED": 1500.0, "SAFE": float(SAFE),
                 "ODDFLOAT": float(ODD), "MAXFLOAT": float(MAXIMUM), "FRACTION": 1.5,
                 "NEGATIVE": -1.0, "INF": float("inf"), "TEXT": "invalid", "BLOB": b"\x00\xca\xfe"}
        for exchange in exchanges:
            for symbol, shares in cases.items():
                position_id += 1
                connection.exec_driver_sql(
                    "INSERT INTO instruments(id,market,exchange,symbol,name,instrument_type,is_watchlisted,status,created_at) "
                    "VALUES (?,'TW',?,?,'synthetic user quantity','stock',0,'active','2026-10-03 00:00:00')",
                    (position_id, exchange, symbol))
                connection.exec_driver_sql(
                    "INSERT INTO portfolio_positions(id,instrument_id,shares,average_cost,stop_price,risk_budget,note,updated_at) "
                    "VALUES (?,?,?,10,9,20,'synthetic 2026-10-03','2026-10-03 00:00:00')",
                    (position_id, position_id, shares))
        if parent:
            connection.exec_driver_sql("UPDATE portfolio_positions SET shares_integer=? WHERE id=1", (ODD,))
        if marker:
            if marker_mode == "alembic":
                connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
                connection.exec_driver_sql("INSERT INTO alembic_version VALUES (?)", ("0001_schema_v1" if parent else PREVIOUS,))
            else:
                connection.exec_driver_sql("CREATE TABLE schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at DATETIME NOT NULL)")
                revisions = readiness.REVISIONS[:1] if parent else readiness.REVISIONS[:-1]
                for revision in revisions:
                    connection.exec_driver_sql("INSERT INTO schema_migrations VALUES (?, '2026-10-03 00:00:00')", (revision,))
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()


def assert_migrated(test, engine, mode, before):
    test.assertEqual(rows(engine), before)
    with engine.connect() as connection:
        test.assertTrue(check_portfolio_share_column(connection))
        typed = connection.exec_driver_sql(
            "SELECT i.symbol,p.shares_integer,typeof(p.shares_integer) FROM portfolio_positions p "
            "JOIN instruments i ON i.id=p.instrument_id ORDER BY p.id").all()
        expected = {"ZERO0": 0, "LOT1": 1000, "MIXED": 1500, "SAFE": SAFE}
        for symbol, integer, stored_type in typed:
            test.assertEqual(integer, expected.get(symbol))
            test.assertEqual(stored_type, "integer" if symbol in expected else "null")
        test.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").all(), [])
        test.assertEqual(connection.exec_driver_sql("PRAGMA integrity_check").scalar(), "ok")
        if mode == "alembic":
            test.assertEqual(connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(), HEAD)
        else:
            test.assertFalse(inspect(connection).has_table("alembic_version"))
            test.assertEqual(connection.exec_driver_sql("SELECT version FROM schema_migrations ORDER BY version").scalars().all(), list(readiness.REVISIONS))


class StorageMemoryTest(unittest.TestCase):
    def test_existing_turnover_memory_boundaries_and_revision_chain(self):
        import test_turnover_availability_migration as turnover
        import test_database_readiness as startup
        import test_units as units
        for function in (units.test_position_quantity_converts_to_total_shares,
                         units.test_position_quantity_rejects_ambiguous_or_non_positive_values):
            mark = next(item for item in function.pytestmark if item.name == "parametrize")
            names = mark.args[0]
            for case in mark.args[1]:
                function(**({names: case} if isinstance(names, str) else dict(zip(names, case))))
        units.test_share_quantity_display_keeps_lots_and_remainder_explicit()
        startup.test_current_head_and_fallback_count_in_memory()
        startup.test_readiness_revision_constants_match_checked_in_single_chain()
        for mode in ("alembic", "fallback"):
            turnover.test_upgrade_classifies_only_legacy_rows_and_preserves_values(mode)
            turnover.test_fresh_in_memory_schema_has_turnover_columns(mode)
            turnover.test_failed_upgrade_rolls_back_columns_and_success_marker(mode)

    def test_full_string_range_and_numeric_compatibility(self):
        for field in ("shares", "quantity", "quantity_lots", "odd_lot_shares"):
            for value in (1, SAFE, "1", str(ODD), str(MAXIMUM)):
                fields = {field: value}
                if field == "quantity":
                    fields["unit"] = "odd_lot"
                multiplier = 1000 if field == "quantity_lots" else 1
                limit = MAXIMUM if type(value) is str else SAFE
                if int(value) * multiplier <= limit:
                    self.assertEqual(shares_from_position_quantity(**fields), int(value) * multiplier)
                else:
                    with self.assertRaises(ValueError):
                        shares_from_position_quantity(**fields)
        for bad in ("", "0", "00", "01", "+1", "-1", " 1", "1 ", "1\n", "1\r", "1\t", "1\u2028", "1\u2029",
                    "1.0", "1e3", "1,000", "\uff11", str(MAXIMUM + 1), "9" * 1000, True, 1.0, float("inf")):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                shares_from_position_quantity(shares=bad)

    def test_trust_priority_and_invalid_new_field(self):
        self.assertEqual(trusted_position_shares(float(ODD), ODD), ODD)
        self.assertEqual(trusted_position_shares(float(MAXIMUM), MAXIMUM), MAXIMUM)
        self.assertEqual(trusted_position_shares(float(SAFE), None), SAFE)
        self.assertEqual(trusted_position_shares(0.0, None), 0)
        for invalid in (True, -1, 1.0, "1000", MAXIMUM + 1, float("nan")):
            self.assertIsNone(trusted_position_shares(1000.0, invalid))
        fixture = MemoryFixture()
        try:
            with Session(fixture.engine) as db:
                instrument = db.query(Instrument).first()
                for invalid in (True, -1, 1.0, "1000", MAXIMUM + 1):
                    item = PortfolioPosition(instrument_id=instrument.id, shares=1000.0, shares_integer=invalid)
                    payload = api.position_dict(db, item)
                    self.assertIsNone(payload["shares_exact"])
                    self.assertIsNone(payload["quantity"])
                    self.assertIsNone(payload["shares"])
        finally:
            fixture.close()

    def test_both_migrations_backfill_once_and_keep_values(self):
        for mode in ("alembic", "fallback"):
            with self.subTest(mode=mode):
                engine = engine_for()
                try:
                    legacy(engine, marker_mode=mode)
                    before = rows(engine)
                    upgrade(engine, mode)
                    assert_migrated(self, engine, mode, before)
                    with engine.begin() as connection:
                        connection.exec_driver_sql("UPDATE portfolio_positions SET shares_integer=? WHERE id=1", (MAXIMUM,))
                        connection.exec_driver_sql("UPDATE portfolio_positions SET shares=1000 WHERE id=5")
                    upgrade(engine, mode)
                    with engine.connect() as connection:
                        self.assertEqual(connection.exec_driver_sql("SELECT shares_integer FROM portfolio_positions WHERE id=1").scalar(), MAXIMUM)
                        self.assertIsNone(connection.exec_driver_sql("SELECT shares_integer FROM portfolio_positions WHERE id=5").scalar())
                finally:
                    engine.dispose()

    def test_fresh_both_paths_and_readiness_no_writes(self):
        for mode in ("alembic", "fallback"):
            engine = engine_for()
            try:
                upgrade(engine, mode)
                before = snapshot(engine)
                upgrade(engine, mode)
                with engine.connect() as connection:
                    raw = connection.connection.driver_connection
                    tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                    readiness._check_markers(raw, tables)
                    readiness._check_schema(raw, tables)
                    self.assertTrue(check_portfolio_share_column(connection))
                # Fallback timestamps can legitimately be rewritten on repeat;
                # readiness itself must leave the complete DB snapshot intact.
                stable = snapshot(engine)
                with engine.connect() as connection:
                    raw = connection.connection.driver_connection
                    readiness._check_schema(raw, {row[0] for row in raw.execute("SELECT name FROM sqlite_schema WHERE type='table'")})
                self.assertEqual(snapshot(engine), stable)
                self.assertEqual(before[0], stable[0])
            finally:
                engine.dispose()

    def test_both_paths_fault_rollback_and_retry(self):
        for mode in ("alembic", "fallback"):
            engine = engine_for()
            try:
                legacy(engine, marker_mode=mode)
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TRIGGER block_quantity BEFORE UPDATE ON portfolio_positions BEGIN SELECT RAISE(ABORT,'blocked_quantity_backfill'); END")
                before = snapshot(engine)
                with self.assertRaisesRegex(Exception, "blocked_quantity_backfill"):
                    upgrade(engine, mode)
                self.assertEqual(snapshot(engine), before)
                with engine.begin() as connection:
                    connection.exec_driver_sql("DROP TRIGGER block_quantity")
                preserved = rows(engine)
                upgrade(engine, mode)
                assert_migrated(self, engine, mode, preserved)
            finally:
                engine.dispose()

    def test_wrong_column_shapes_refused_before_marker(self):
        for definition in ("FLOAT", "INTEGER NOT NULL DEFAULT 0", "INTEGER DEFAULT 0",
                           "INTEGER GENERATED ALWAYS AS (CAST(shares AS INTEGER)) VIRTUAL"):
            for mode in ("alembic", "fallback"):
                engine = engine_for()
                try:
                    legacy(engine, marker_mode=mode)
                    with engine.begin() as connection:
                        connection.exec_driver_sql("ALTER TABLE portfolio_positions ADD COLUMN shares_integer " + definition)
                    before = snapshot(engine)
                    with self.assertRaisesRegex(RuntimeError, "ordinary nullable INTEGER"):
                        upgrade(engine, mode)
                    self.assertEqual(snapshot(engine), before)
                    with engine.connect() as connection:
                        raw = connection.connection.driver_connection
                        with self.assertRaisesRegex(readiness.DatabaseReadinessError, "ordinary nullable INTEGER"):
                            readiness._check_schema(raw, {row[0] for row in raw.execute("SELECT name FROM sqlite_schema WHERE type='table'")})
                finally:
                    engine.dispose()

    def test_parent_rebuild_preserves_child_integer_and_legacy(self):
        for mode in ("alembic", "fallback"):
            engine = engine_for()
            try:
                legacy(engine, parent=True, marker_mode=mode)
                before = rows(engine)
                with engine.connect() as connection:
                    exact = connection.exec_driver_sql("SELECT shares_integer FROM portfolio_positions ORDER BY id").all()
                upgrade(engine, mode)
                self.assertEqual(rows(engine), before)
                with engine.connect() as connection:
                    self.assertEqual(connection.exec_driver_sql("SELECT shares_integer FROM portfolio_positions ORDER BY id").all(), exact)
                    self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").all(), [])
            finally:
                engine.dispose()

    def test_fallback_does_not_override_stale_alembic_readiness(self):
        engine = engine_for()
        try:
            legacy(engine, marker_mode="alembic")
            upgrade(engine, "fallback")
            before = snapshot(engine)
            with engine.connect() as connection:
                self.assertEqual(connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(), PREVIOUS)
                raw = connection.connection.driver_connection
                tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                with self.assertRaisesRegex(readiness.DatabaseReadinessError, "current head revision"):
                    readiness._check_markers(raw, tables)
            self.assertEqual(snapshot(engine), before)
        finally:
            engine.dispose()


class StorageDiskTest(unittest.TestCase):
    def run_case(self, mode, fault=False):
        remove_database()
        engine = engine_for(OWNED_DB)
        try:
            legacy(engine, marker_mode=mode)
            before = rows(engine)
            if fault:
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TRIGGER block_quantity BEFORE UPDATE ON portfolio_positions BEGIN SELECT RAISE(ABORT,'blocked_quantity_backfill'); END")
                frozen = snapshot(engine)
                with self.assertRaisesRegex(Exception, "blocked_quantity_backfill"):
                    upgrade(engine, mode)
                engine.dispose()
                inventory()
                engine = engine_for(OWNED_DB)
                self.assertEqual(snapshot(engine), frozen)
                with engine.begin() as connection:
                    connection.exec_driver_sql("DROP TRIGGER block_quantity")
            upgrade(engine, mode)
            engine.dispose()
            inventory()
            engine = engine_for(OWNED_DB)
            assert_migrated(self, engine, mode, before)
            upgrade(engine, mode)
            engine.dispose()
            fingerprint = hashlib.sha256(OWNED_DB.read_bytes()).hexdigest()
            readiness.check_database_readiness(OWNED_DB)
            readiness.check_database_readiness(OWNED_DB)
            self.assertEqual(hashlib.sha256(OWNED_DB.read_bytes()).hexdigest(), fingerprint)
            # Actual API commit/refresh followed by a completely new engine.
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(api.router)
            engine = engine_for(OWNED_DB)
            def database():
                with Session(engine) as db:
                    yield db
            app.dependency_overrides[api.get_db] = database
            with TestClient(app) as client:
                for exchange in ("TWSE", "TPEx"):
                    response = client.post("/api/portfolio", json={"symbol": "MIXED", "exchange": exchange,
                                           "shares": str(ODD if exchange == "TWSE" else MAXIMUM), "average_cost": 10})
                    self.assertEqual(response.status_code, 200, response.text)
            app.dependency_overrides.clear()
            engine.dispose()
            with closing(sqlite3.connect(OWNED_DB.as_uri() + "?mode=ro", uri=True)) as connection:
                stored = connection.execute("SELECT i.exchange,p.shares_integer,typeof(p.shares_integer) FROM portfolio_positions p JOIN instruments i ON i.id=p.instrument_id WHERE i.symbol='MIXED' ORDER BY i.exchange").fetchall()
                self.assertEqual(stored, [("TPEx", MAXIMUM, "integer"), ("TWSE", ODD, "integer")])
            print(json.dumps({"mode": mode, "fault": fault, "disk_commit_close_reopen": "passed", "inventory": inventory()}), flush=True)
        finally:
            engine.dispose()
            remove_database()

    def test_sequential_both_paths_reopen_and_failure_retry(self):
        for mode in ("alembic", "fallback"):
            for fault in (False, True):
                with self.subTest(mode=mode, fault=fault):
                    self.run_case(mode, fault)


def prepare():
    if OWNED_DB.exists():
        raise RuntimeError("prepare refuses to overwrite the existing owned DB")
    engine = engine_for(OWNED_DB)
    try:
        legacy(engine, marker_mode="alembic")
        upgrade(engine, "alembic")
        # Invalid Float/text/blob legacy states remain covered by runner tests;
        # the UI fixture includes the named usable/pending states only.
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM portfolio_positions WHERE instrument_id IN (SELECT id FROM instruments WHERE symbol IN ('FRACTION','NEGATIVE','INF','TEXT','BLOB'))")
        with Session(engine) as db:
            for exchange in ("TWSE", "TPEx"):
                db.add(Instrument(market="TW", exchange=exchange, symbol="NEW", name="synthetic user quantity NEW", instrument_type="stock", status="active"))
            for instrument in db.query(Instrument).all():
                db.add(MarketBar(instrument_id=instrument.id, trading_date=DAY, open=10, high=11, low=9, close=10.5,
                                 adj_close=10.5, volume=1000, turnover=10500, source="synthetic-user-quantity"))
            db.commit()
    finally:
        engine.dispose()
    readiness.check_database_readiness(OWNED_DB)
    print(json.dumps({"prepared": str(OWNED_DB), "fixture_date": str(DAY), "source": "synthetic user quantities; no official/live claim", "inventory": inventory()}), flush=True)


def serve():
    from app import main
    import uvicorn
    # Use the actual main lifespan, router, and configured file engine. Restrict
    # all mutations to owned portfolio routes and this process's shutdown.
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8779, access_log=False))
    @main.app.middleware("http")
    async def owned_only(request, call_next):
        from starlette.responses import JSONResponse
        portfolio_write = request.url.path == "/api/portfolio" and request.method == "POST"
        portfolio_delete = request.url.path.startswith("/api/portfolio/") and request.method == "DELETE"
        shutdown = request.url.path == "/__review__/shutdown" and request.method == "POST"
        if request.method not in {"GET", "OPTIONS"} and not (portfolio_write or portfolio_delete or shutdown):
            return JSONResponse({"detail": "only owned synthetic portfolio mutations permitted"}, status_code=405)
        response = await call_next(request)
        inventory()
        return response
    @main.app.post("/__review__/shutdown")
    def stop():
        server.should_exit = True
        return {"owned_storage_server": "stopping"}
    print(json.dumps({"owned_storage_server": "starting", "pid": os.getpid(), "url": "http://127.0.0.1:8779", "db": str(OWNED_DB)}), flush=True)
    try:
        server.run()
        if not server.started:
            raise RuntimeError("owned storage server failed to start")
    finally:
        from app.db import engine
        engine.dispose()
        print(json.dumps({"owned_storage_server": "closed", "retained_for_reviewed_reopen": str(OWNED_DB), "inventory": inventory()}), flush=True)


def main():
    test_exit, cleanup_exit = 0, 0
    retain = False
    try:
        if DISK:
            inventory()
            if ARGS.disk or ARGS.prepare:
                if OWNED_DB.exists():
                    raise RuntimeError("new disk work refuses an occupied owned DB")
                for directory in (OWNED_ROOT, OWNED_ROOT / "data", OWNED_ROOT / "raw"):
                    if not directory.exists():
                        directory.mkdir()
                inventory()
            if ARGS.cleanup:
                cleanup()
            elif ARGS.prepare:
                prepare()
                retain = True
            elif ARGS.serve:
                readiness.check_database_readiness(OWNED_DB)
                retain = True
                serve()
            elif ARGS.inspect:
                retain = True
                with closing(sqlite3.connect(OWNED_DB.as_uri() + "?mode=ro", uri=True)) as connection:
                    values = connection.execute("SELECT i.exchange,i.symbol,p.shares_integer,typeof(p.shares_integer),p.shares FROM portfolio_positions p JOIN instruments i ON i.id=p.instrument_id ORDER BY p.id").fetchall()
                print(json.dumps({"rows": values, "sha256": hashlib.sha256(OWNED_DB.read_bytes()).hexdigest(), "inventory": inventory()}), flush=True)
            else:
                result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StorageDiskTest))
                test_exit = 0 if result.wasSuccessful() else 1
        else:
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(StorageMemoryTest)
            if not ARGS.memory_storage:
                suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(ShareQuantityExactTest), suite])
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            test_exit = 0 if result.wasSuccessful() else 1
        if UNEXPECTED_DENIALS:
            test_exit = 1
    except BaseException as error:
        retain = False
        test_exit = 1
        print(json.dumps({"validation_error": type(error).__name__, "message": str(error)}), flush=True)
    finally:
        if DISK and not retain:
            try:
                cleanup()
            except BaseException as error:
                cleanup_exit = 1
                print(json.dumps({"cleanup_error": type(error).__name__, "message": str(error), "root": str(OWNED_ROOT)}), flush=True)
        print(json.dumps({"test_exit": test_exit, "cleanup_exit": cleanup_exit, "peak": PEAK,
                          "unexpected_denials": UNEXPECTED_DENIALS, "retained_for_reviewed_reopen": retain,
                          "disk_mode": DISK, "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version}), flush=True)
    return test_exit or cleanup_exit


if STANDALONE:
    raise SystemExit(main())
