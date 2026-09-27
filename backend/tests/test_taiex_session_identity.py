"""TAIEX identity checks with a guarded, in-memory standalone runner.

Normal pytest/unittest imports do not alter process globals or import the app.
Run this file directly with Python -B and PYTHONDONTWRITEBYTECODE=1 to execute
the guarded cases without entering pytest's filesystem-backed conftest.
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import os
import socket
import sqlite3
import sys
import unittest
from contextlib import ExitStack, contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND
RAW_DIR = BACKEND / "worker"

_open = builtins.open
_io_open = io.open
_os_open = os.open
_sqlite_connect = sqlite3.connect
_allowed_mkdir: list[Path] = []


def _deny(operation: str):
    raise RuntimeError(f"zero-disk/network guard blocked {operation}")


def _read_only_open(file, mode="r", *args, **kwargs):
    if any(char in mode for char in "wax+"):
        _deny(f"open({file!s}, mode={mode!r})")
    return _open(file, mode, *args, **kwargs)


def _read_only_io_open(file, mode="r", *args, **kwargs):
    if any(char in mode for char in "wax+"):
        _deny(f"io.open({file!s}, mode={mode!r})")
    return _io_open(file, mode, *args, **kwargs)


def _read_only_os_open(file, flags, *args, **kwargs):
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    if flags & write_flags:
        _deny(f"os.open({file!s}, flags={flags})")
    return _os_open(file, flags, *args, **kwargs)


def _existing_config_mkdir(path: Path, *args, **kwargs):
    if path not in {DATA_DIR, RAW_DIR} or not path.is_dir():
        _deny(f"Path.mkdir({path!s})")
    _allowed_mkdir.append(path)


def _memory_sqlite_connect(database, *args, **kwargs):
    if database != ":memory:":
        _deny(f"sqlite3.connect({database!s})")
    return _sqlite_connect(database, *args, **kwargs)


def _blocked(*args, **kwargs):
    _deny("unexpected filesystem or network mutation")


def _default_db_forbidden(*args, **kwargs):
    _deny("default app.db engine/SessionLocal connection")


@contextmanager
def standalone_guard():
    """Guard the direct runner and restore every process-wide patch on exit."""

    if not sys.dont_write_bytecode or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
        raise RuntimeError("standalone run requires Python -B and PYTHONDONTWRITEBYTECODE=1")
    if not DATA_DIR.is_dir() or not RAW_DIR.is_dir():
        raise RuntimeError("the two pre-existing import directories are required")
    if "app.config" in sys.modules:
        raise RuntimeError("project imports must occur after the standalone guard")

    _allowed_mkdir.clear()
    original_path = sys.path.copy()
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            "STOCK_DATA_DIR": str(DATA_DIR),
            "STOCK_RAW_DIR": str(RAW_DIR),
            "STOCK_DB_PATH": ":memory:",
        }))
        stack.enter_context(patch.object(builtins, "open", _read_only_open))
        stack.enter_context(patch.object(io, "open", _read_only_io_open))
        stack.enter_context(patch.object(os, "open", _read_only_os_open))
        stack.enter_context(patch.object(Path, "mkdir", _existing_config_mkdir))
        for name in ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir"):
            stack.enter_context(patch.object(os, name, _blocked))
        stack.enter_context(patch.object(socket.socket, "connect", _blocked))
        stack.enter_context(patch.object(socket.socket, "connect_ex", _blocked))
        stack.enter_context(patch.object(socket, "create_connection", _blocked))
        stack.enter_context(patch.object(sqlite3, "connect", _memory_sqlite_connect))
        stack.enter_context(patch.object(sqlite3.dbapi2, "connect", _memory_sqlite_connect))
        sys.path.insert(0, str(BACKEND))
        if (BACKEND / ".deps").is_dir():
            sys.path.insert(0, str(BACKEND / ".deps"))
        try:
            yield stack
        finally:
            sys.path[:] = original_path


DAY = date(2026, 9, 8)
MI_INDEX_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX?date=20260908&type=ALLBUT0999"


@contextmanager
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    if engine.url.database != ":memory:":
        raise AssertionError("test engine must be in memory")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def instrument(db: Session, exchange: str, symbol: str, *, kind: str = "stock", status: str = "active") -> Instrument:
    row = Instrument(market="TW", exchange=exchange, symbol=symbol, name=symbol, instrument_type=kind, status=status)
    db.add(row)
    db.flush()
    return row


def bar(db: Session, owner: Instrument, day: date = DAY, *, source: str = "fixture", raw_id: int | None = None) -> None:
    db.add(MarketBar(
        instrument_id=owner.id,
        trading_date=day,
        open=100,
        high=101,
        low=99,
        close=100,
        adj_close=100,
        volume=100,
        turnover=10000,
        source=source,
        raw_payload_id=raw_id,
    ))
    db.flush()


def official_raw(db: Session, *, source: str = "twse", payload_path: str | None = None) -> RawPayload:
    run = IngestionRun(run_type="collect", source="official", run_date=DAY, status="success", records=1)
    db.add(run)
    db.flush()
    raw = RawPayload(
        ingestion_run_id=run.id,
        source=source,
        endpoint=MI_INDEX_URL,
        payload_path=payload_path,
        sha256="a" * 64,
        data_as_of=DAY.isoformat(),
    )
    db.add(raw)
    db.flush()
    return raw


@unittest.skipUnless(__name__ == "__main__", "run through the standalone zero-disk runner")
class TaiexSessionIdentityTests(unittest.TestCase):
    def test_import_guard_used_only_existing_directories(self):
        self.assertEqual(_allowed_mkdir, [DATA_DIR, RAW_DIR])

    def test_foreign_exchange_taiex_and_twii_do_not_verify_session(self):
        for alias in ("TAIEX", "TWII"):
            for require_provenance in (False, True):
                with self.subTest(alias=alias, require_provenance=require_provenance), memory_db() as db:
                    foreign_index = instrument(db, "TPEx", alias, kind="index")
                    stock = instrument(db, "TWSE", "1101")
                    bar(db, foreign_index)
                    bar(db, stock)
                    self.assertEqual(verified_taiex_sessions(db, DAY, DAY, require_provenance=require_provenance), [])
                    report = backfill.coverage_report(
                        db, DAY, DAY, target_keys={("TWSE", "1101")}, require_provenance=require_provenance,
                    )
                    self.assertEqual(report["sessions"], [])
                    self.assertEqual(report["summary"]["verified_taiex_sessions"], 0)
                    self.assertEqual(report["summary"]["verified_ohlcv_sessions"], 0)
                    self.assertEqual(report["date_coverage"][0]["taiex_rows"], 0)
                    self.assertEqual(report["date_coverage"][0]["status"], "partial")
                    row = report["instrument_coverage"][0]
                    self.assertEqual(row["effective_bar_sessions"], 0)
                    self.assertEqual(row["windows"]["20"]["bar_days"], 0)

    def test_twse_aliases_keep_fixture_and_raw_linked_positive_paths(self):
        for alias in ("TAIEX", "TWII"):
            for evidence in ("fixture", "raw"):
                for require_provenance in (False, True):
                    with self.subTest(alias=alias, evidence=evidence, require_provenance=require_provenance), memory_db() as db:
                        index = instrument(db, "TWSE", alias, kind="index")
                        stock = instrument(db, "TWSE", "1101")
                        raw = official_raw(db) if evidence == "raw" else None
                        bar(db, index, source="twse_index" if raw else "fixture", raw_id=raw.id if raw else None)
                        bar(db, stock)
                        self.assertEqual(verified_taiex_sessions(db, DAY, DAY, require_provenance=require_provenance), [DAY])
                        report = backfill.coverage_report(
                            db, DAY, DAY, target_keys={("TWSE", "1101")}, require_provenance=require_provenance,
                        )
                        self.assertEqual(report["sessions"], [DAY.isoformat()])
                        self.assertEqual(report["date_coverage"][0]["taiex_rows"], 1)
                        self.assertEqual(report["instrument_coverage"][0]["effective_bar_sessions"], 1)

    def test_unlinked_twse_bar_still_requires_provenance(self):
        with memory_db() as db:
            index = instrument(db, "TWSE", "TAIEX", kind="index")
            bar(db, index, source="twse_index")
            self.assertEqual(verified_taiex_sessions(db, DAY, DAY, require_provenance=False), [DAY])
            self.assertEqual(verified_taiex_sessions(db, DAY, DAY, require_provenance=True), [])

    def test_same_symbol_on_both_exchanges_counts_only_twse_benchmark(self):
        for require_provenance in (False, True):
            with self.subTest(require_provenance=require_provenance), memory_db() as db:
                twse_index = instrument(db, "TWSE", "TAIEX", kind="index")
                tpex_index = instrument(db, "TPEx", "TAIEX", kind="index")
                twse_stock = instrument(db, "TWSE", "1101")
                tpex_stock = instrument(db, "TPEx", "1101")
                for owner in (twse_index, tpex_index, twse_stock, tpex_stock):
                    bar(db, owner)
                report = backfill.coverage_report(
                    db, DAY, DAY,
                    target_keys={("TWSE", "1101"), ("TPEx", "1101")},
                    require_provenance=require_provenance,
                )
                self.assertEqual(report["sessions"], [DAY.isoformat()])
                self.assertEqual(report["summary"]["verified_taiex_sessions"], 1)
                self.assertEqual(report["date_coverage"][0]["taiex_rows"], 1)
                by_key = {(row["exchange"], row["symbol"]): row for row in report["instrument_coverage"]}
                self.assertEqual(by_key[("TWSE", "1101")]["effective_bar_sessions"], 1)
                self.assertEqual(by_key[("TPEx", "1101")]["effective_bar_sessions"], 1)

    def test_date_type_and_active_gates_still_exclude_rows(self):
        for excluded in ("outside_range", "not_index", "inactive"):
            for require_provenance in (False, True):
                with self.subTest(excluded=excluded, require_provenance=require_provenance), memory_db() as db:
                    index = instrument(
                        db, "TWSE", "TAIEX",
                        kind="stock" if excluded == "not_index" else "index",
                        status="inactive" if excluded == "inactive" else "active",
                    )
                    stock = instrument(db, "TWSE", "1101")
                    bar(db, index, DAY + timedelta(days=1) if excluded == "outside_range" else DAY)
                    bar(db, stock)
                    self.assertEqual(verified_taiex_sessions(db, DAY, DAY, require_provenance=require_provenance), [])
                    report = backfill.coverage_report(
                        db, DAY, DAY, target_keys={("TWSE", "1101")}, require_provenance=require_provenance,
                    )
                    self.assertEqual(report["sessions"], [])
                    self.assertEqual(report["summary"]["verified_taiex_sessions"], 0)

    def test_raw_only_fallback_keeps_date_and_source_checks(self):
        raw_path = BACKEND / "tests" / "in-memory-taiex.json"
        valid_payload = {
            "date": "20260908",
            "tables": [{
                "title": "115年09月08日 價格指數(臺灣證券交易所)",
                "fields": ["指數", "收盤指數"],
                "data": [["發行量加權股價指數", "47105.78"]],
            }],
        }
        for variant in ("valid", "wrong_date", "tpex_source"):
            with self.subTest(variant=variant), memory_db() as db:
                stock = instrument(db, "TWSE", "1101")
                bar(db, stock)
                official_raw(db, source="tpex" if variant == "tpex_source" else "twse", payload_path=str(raw_path))
                payload = dict(valid_payload, date="20260907") if variant == "wrong_date" else valid_payload
                reads: list[Path] = []

                def read_from_memory(path: Path, *args, **kwargs) -> str:
                    if path != raw_path:
                        _deny(f"unexpected raw read({path!s})")
                    reads.append(path)
                    return json.dumps(payload, ensure_ascii=False)

                with patch.object(Path, "read_text", read_from_memory):
                    report = backfill.coverage_report(
                        db, DAY, DAY, target_keys={("TWSE", "1101")}, require_provenance=True,
                    )
                expected = variant == "valid"
                self.assertEqual(report["sessions"], [DAY.isoformat()] if expected else [])
                self.assertEqual(report["date_coverage"][0]["taiex_rows"], int(expected))
                self.assertEqual(report["instrument_coverage"][0]["effective_bar_sessions"], int(expected))
                self.assertEqual(report["date_coverage"][0]["status"], "success" if expected else "partial")
                self.assertEqual(len(reads), 0 if variant == "tpex_source" else 1)


def run_standalone() -> int:
    global create_engine, Session, Base, IngestionRun, Instrument, MarketBar, RawPayload
    global verified_taiex_sessions, backfill

    def process_snapshot():
        return (
            builtins.open, io.open, os.open, Path.mkdir,
            os.mkdir, os.makedirs, os.remove, os.unlink, os.rename, os.replace, os.rmdir,
            socket.socket.connect, socket.socket.connect_ex, socket.create_connection,
            sqlite3.connect, sqlite3.dbapi2.connect,
            tuple(sys.path),
            tuple(os.environ.get(key) for key in ("STOCK_DATA_DIR", "STOCK_RAW_DIR", "STOCK_DB_PATH")),
        )

    before = process_snapshot()
    with standalone_guard() as stack:
        sqlalchemy = importlib.import_module("sqlalchemy")
        create_engine = sqlalchemy.create_engine
        Session = importlib.import_module("sqlalchemy.orm").Session
        app_db = importlib.import_module("app.db")
        verified_taiex_sessions = importlib.import_module("app.coverage").verified_taiex_sessions
        Base = app_db.Base
        models = importlib.import_module("app.models")
        IngestionRun = models.IngestionRun
        Instrument = models.Instrument
        MarketBar = models.MarketBar
        RawPayload = models.RawPayload
        backfill = importlib.import_module("worker.backfill")
        pipeline = importlib.import_module("worker.pipeline")
        if app_db.engine.url.database != ":memory:":
            raise RuntimeError("default app.db engine must never target a file")
        stack.enter_context(patch.object(app_db.engine, "connect", _default_db_forbidden))
        stack.enter_context(patch.object(app_db.engine, "raw_connection", _default_db_forbidden))
        stack.enter_context(patch.object(app_db, "SessionLocal", _default_db_forbidden))
        stack.enter_context(patch.object(pipeline, "SessionLocal", _default_db_forbidden))
        result = unittest.main(module=__name__, verbosity=2, exit=False).result
    if process_snapshot() != before:
        raise RuntimeError("standalone guard did not restore process globals")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(run_standalone())
