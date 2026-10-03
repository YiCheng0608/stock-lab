"""Bounded synthetic legacy TWSE/TPEx volume persistence; direct runner only.

Target fetching, JSON capture, parsing, combined adapter, collect, current-schema
initialization and HTTP serialization are real. Ancillary endpoint captures use
explicit memory fixture URIs. This does not validate live official data, API
startup, legacy migration, selected capture or the full backend suite.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import socket
import sqlite3
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


VALIDATION_ROOT = os.environ.get("LEGACY_DAILY_VOLUME_VALIDATION_ROOT")
if not VALIDATION_ROOT:
    if __name__ == "__main__":
        raise SystemExit("Run tools/Invoke-LegacyDailyVolumeValidation.ps1")
    raise unittest.SkipTest("Requires the bounded legacy-volume runner")

ROOT = Path(VALIDATION_ROOT).resolve()
OWNER = os.environ.get("LEGACY_DAILY_VOLUME_RUN_OWNER", "")
TEMP_BASE = Path(os.environ["LOCALAPPDATA"]).resolve() / "Temp"
if (not re.fullmatch(r"[A-Za-z0-9]{8}", OWNER)
        or not re.fullmatch(r"taiwan-stock-r1a2-lv-" + OWNER + r"-[a-f0-9]{32}", ROOT.name)
        or ROOT.parent != TEMP_BASE or not ROOT.is_dir()):
    raise RuntimeError("Invalid owned validation root")
DB_PATH = ROOT / "data" / "legacy-volume.db"
RAW_DIR = ROOT / "raw"
for key, expected in {"STOCK_DATA_DIR": ROOT / "data", "STOCK_RAW_DIR": RAW_DIR,
                      "STOCK_DB_PATH": DB_PATH, "TEMP": ROOT, "TMP": ROOT}.items():
    if Path(os.environ[key]).resolve() != expected:
        raise RuntimeError("Validation environment mismatch: " + key)
if not sys.dont_write_bytecode:
    raise RuntimeError("Requires Python -B")

ALLOWED_FILES = {DB_PATH, Path(str(DB_PATH) + "-journal")}
ALLOWED_DIRS = {ROOT, ROOT / "data", RAW_DIR}
for source in ("twse", "tpex"):
    current = RAW_DIR / source
    for component in (None, "2026", "09", "05"):
        if component is not None:
            current = current / component
        ALLOWED_DIRS.add(current)
PEAKS = {"files": 0, "directories": 0, "bytes": 0, "db_bytes": 0, "journal_bytes": 0}
GUARD = {"expected_denials": 0, "unexpected_denials": 0, "local_socketpair_events": 0}
PROBING_GUARD = False


def checked_path(value) -> Path:
    if isinstance(value, int):
        raise RuntimeError("Unowned descriptor mutation is forbidden")
    path = Path(os.fsdecode(value)).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise RuntimeError("Mutation outside owned validation root: " + str(path))
    return path


def in_socketpair() -> bool:
    # Windows asyncio may implement its local wake-up socketpair using a
    # loopback TCP pair. Only that standard-library call stack is admitted.
    code = getattr(socket.socketpair, "__code__", None)
    frame = sys._getframe(1)
    while frame:
        if frame.f_code is code:
            return True
        frame = frame.f_back
    return False


def disk_audit(event, args) -> None:
    try:
        if event == "sqlite3.connect":
            if checked_path(args[0]) != DB_PATH:
                raise RuntimeError("Only the owned SQLite file may be opened")
        elif event == "open":
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and checked_path(args[0]) not in ALLOWED_FILES:
                raise RuntimeError("Unapproved validation file")
        elif event == "os.mkdir":
            if checked_path(args[0]) not in ALLOWED_DIRS:
                raise RuntimeError("Unapproved validation directory")
        elif event in {"os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
            if checked_path(args[0]) not in ALLOWED_FILES | ALLOWED_DIRS:
                raise RuntimeError("Unapproved validation mutation")
        elif event in {"os.rename", "os.link", "os.symlink"}:
            raise RuntimeError("Validation does not require rename/link/symlink")
        elif event in {"subprocess.Popen", "os.system", "os.startfile", "os.posix_spawn"}:
            raise RuntimeError("Validation subprocess is forbidden")
        elif event.startswith("socket.") and event in {
                "socket.__new__", "socket.connect", "socket.bind", "socket.sendto", "socket.getaddrinfo"}:
            local_pair = in_socketpair()
            if event in {"socket.connect", "socket.bind"}:
                address = args[1]
                local_pair = local_pair and isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
            elif event == "socket.getaddrinfo":
                local_pair = local_pair and args[0] in {"127.0.0.1", "::1"}
            elif event == "socket.sendto":
                local_pair = False
            if not local_pair:
                raise RuntimeError("Validation outbound network is forbidden")
            GUARD["local_socketpair_events"] += 1
    except RuntimeError:
        GUARD["expected_denials" if PROBING_GUARD else "unexpected_denials"] += 1
        raise


sys.addaudithook(disk_audit)


def observe_disk() -> None:
    files, directories, total = 0, 1, 0
    if ROOT.is_symlink() or ROOT.is_junction():
        raise RuntimeError("Validation root is a reparse point")
    for path in ROOT.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError("Validation reparse point: " + str(path))
        if path.is_dir():
            directories += 1
            if path not in ALLOWED_DIRS:
                raise RuntimeError("Unexpected validation directory: " + str(path))
        else:
            files += 1
            size = path.stat().st_size
            total += size
            if path not in ALLOWED_FILES:
                raise RuntimeError("Unexpected validation file: " + str(path))
            limit = 1024 * 1024 if path in {DB_PATH, Path(str(DB_PATH) + "-journal")} else (
                8 * 1024 if path.name.endswith(".meta.json") else 32 * 1024)
            if size > limit:
                raise RuntimeError("Validation file size limit exceeded: " + str(path))
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    journal = Path(str(DB_PATH) + "-journal")
    journal_size = journal.stat().st_size if journal.exists() else 0
    for key, value in (("files", files), ("directories", directories), ("bytes", total),
                       ("db_bytes", db_size), ("journal_bytes", journal_size)):
        PEAKS[key] = max(PEAKS[key], value)
    if files > 14 or directories > 11 or total > 3 * 1024 * 1024:
        raise RuntimeError("Validation disk budget exceeded: " + str(PEAKS))


# The environment and audit gate precede all application imports and mkdir.
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import api, db as app_db, models
from worker import pipeline, sources


DAY = date(2026, 9, 4)
CAPTURED_AT = datetime(2026, 9, 5, 0, 0, 1)
ODD = 9007199254740993
MAX64 = 9223372036854775807
LEGAL = {"ZERO": 0, "ODD": ODD, "MAX": MAX64}
INVALID = {"FRACTION": "1.5", "NEGATIVE": "-1", "COMMAS": "12,34",
           "BOOL": True, "FLOAT": 1234.0, "OVERFLOW": "9223372036854775808"}
CASES = {}
for exchange, base in (("TWSE", 1100), ("TPEx", 3100)):
    offset = 1
    for label, value in LEGAL.items():
        CASES[(exchange, str(base + offset))] = (label, value)
        offset += 1
    for label, value in INVALID.items():
        for state in ("EXISTING", "EMPTY"):
            CASES[(exchange, str(base + offset))] = (label + "_" + state, value)
            offset += 1
TARGET_CAPTURES = []
REAL_CAPTURE = sources.capture_payload
VERIFIED = {"http_responses": 0, "accepted_collects": 0, "failed_collects": 0}


def volume_row(exchange, symbol, value):
    if exchange == "TWSE":
        return {"Code": symbol, "Date": DAY.isoformat(), "OpeningPrice": "100", "HighestPrice": "105",
                "LowestPrice": "98", "ClosingPrice": "103", "TradeVolume": value, "TradeValue": "103000"}
    return {"SecuritiesCompanyCode": symbol, "Date": DAY.isoformat(), "Open": "100", "High": "105",
            "Low": "98", "Close": "103", "TradingShares": value, "TransactionAmount": "103000"}


def table(rows):
    return {"fields": list(rows[0]), "data": [list(row.values()) for row in rows]}


class MemoryEndpointFetcher:
    """Synthetic JSON-native body fixtures with exact request allowlists."""

    def __init__(self, all_invalid=False):
        self.all_invalid = all_invalid
        self.calls = []

    def rows(self, exchange):
        result = []
        for (market, symbol), (label, value) in CASES.items():
            if market != exchange:
                continue
            if self.all_invalid and label in LEGAL:
                value = "1.5"
            elif label == "ZERO":
                value = 0 if exchange == "TWSE" else "0"
            elif label == "ODD":
                value = "9,007,199,254,740,993"
            result.append(volume_row(exchange, symbol, value))
        return result

    def __call__(self, endpoint, *, method="GET", data=None):
        self.calls.append((endpoint, method, data))
        if endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT + "?"):
            if (method != "GET" or data is not None or parse_qs(urlsplit(endpoint).query) !=
                    {"date": ["20260904"], "type": ["ALLBUT0999"], "response": ["json"]}):
                raise AssertionError("Unexpected TWSE history request")
            return {"date": "20260904", "tables": [
                {"title": "115\u5e7409\u670804\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                 "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578"],
                 "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "24000"]]},
                table(self.rows("TWSE"))]}
        if endpoint == sources.TPEX_HISTORY_API:
            if method != "POST" or data != {"date": "2026/09/04", "response": "json"}:
                raise AssertionError("Unexpected TPEx history request")
            return {"date": "20260904", "tables": [table(self.rows("TPEx"))]}
        post_requests = {
            sources.TPEX_ETF_ENDPOINT: {"response": "json"},
            sources.TPEX_CHIP_HISTORY_ENDPOINT: {"type": "Daily", "sect": "EW", "date": "2026/09/04", "response": "json"},
            sources.TPEX_MARGIN_HISTORY_ENDPOINT: {"date": "2026/09/04", "response": "json"},
        }
        if endpoint in post_requests:
            if method != "POST" or data != post_requests[endpoint]:
                raise AssertionError("Unexpected ancillary POST request")
            return [] if endpoint == sources.TPEX_ETF_ENDPOINT else {"date": "20260904", "fields": ["Code"], "data": []}
        if method != "GET" or data is not None:
            raise AssertionError("Unexpected fixture request method")
        if endpoint == sources.TWSE_DAILY_ENDPOINT:
            return self.rows("TWSE")
        if endpoint in {sources.TWSE_LISTED_ENDPOINT, sources.TPEX_LISTED_ENDPOINT}:
            exchange = "TWSE" if endpoint == sources.TWSE_LISTED_ENDPOINT else "TPEx"
            return [{"Code": symbol, "SecuritiesCompanyCode": symbol, "Name": "Synthetic " + label,
                     "CompanyAbbreviation": "Synthetic " + label, "DateOfListing": "2020/01/02", "Industry": "24"}
                    for (market, symbol), (label, _value) in CASES.items() if market == exchange]
        if endpoint == sources.TWSE_INDEX_ENDPOINT:
            return [{"\u6307\u6578": "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578",
                     "\u65e5\u671f": "1150904", "\u6536\u76e4\u6307\u6578": "24000"}]
        if endpoint in {sources.TWSE_ETF_ENDPOINT, sources.TWSE_NEW_LISTING_ENDPOINT,
                        sources.TWSE_ACTION_ENDPOINT, sources.TWSE_EVENT_ENDPOINT, sources.TWSE_FUNDAMENTAL_ENDPOINT,
                        sources.TPEX_ACTION_ENDPOINT, sources.TPEX_SUSPEND_ENDPOINT, sources.TPEX_SUSPEND_HISTORY_ENDPOINT,
                        sources.TPEX_EVENT_ENDPOINT, sources.TPEX_FUNDAMENTAL_ENDPOINT}:
            return []
        for base in (sources.TWSE_CHIP_ENDPOINT, sources.TWSE_MARGIN_HISTORY_ENDPOINT):
            if endpoint.startswith(base + "?") and parse_qs(urlsplit(endpoint).query) == {
                    "date": ["20260904"], "selectType": ["ALL"], "response": ["json"]}:
                return {"date": "20260904", "fields": ["Code"], "data": []}
        raise AssertionError("Unexpected fixture endpoint: " + endpoint)


def bounded_capture(source, endpoint, payload, data_as_of=None, *, collected_at=None):
    target = ((source == "twse" and (endpoint == sources.TWSE_DAILY_ENDPOINT or
               endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT + "?"))) or
              (source == "tpex" and endpoint == sources.TPEX_HISTORY_API))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if not target:
        return sources.FetchedPayload(source, endpoint, payload, data_as_of, CAPTURED_AT,
                                      "memory-fixture://" + digest, digest)
    if len(encoded) > 32 * 1024 or len(TARGET_CAPTURES) >= 6:
        raise RuntimeError("Target capture budget exceeded")
    body = RAW_DIR / source / "2026/09/05" / (digest + ".json")
    ALLOWED_FILES.update({body, body.with_suffix(".meta.json")})
    capture = REAL_CAPTURE(source, endpoint, payload, data_as_of, collected_at=CAPTURED_AT)
    TARGET_CAPTURES.append(capture)
    observe_disk()
    return capture


def cap_engine(engine):
    @event.listens_for(engine, "connect")
    def limit_file(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=DELETE")
            if cursor.fetchone()[0] != "delete":
                raise RuntimeError("Requires SQLite DELETE journaling")
            cursor.execute("PRAGMA page_size=4096")
            cursor.execute("PRAGMA page_size")
            if cursor.fetchone()[0] != 4096:
                raise RuntimeError("Requires 4096-byte SQLite pages")
            cursor.execute("PRAGMA max_page_count=256")
            if cursor.fetchone()[0] != 256:
                raise RuntimeError("Cannot enforce the 1 MiB DB limit")
        finally:
            cursor.close()
        observe_disk()

    @event.listens_for(engine, "after_cursor_execute")
    def observe_statement(*_args):
        observe_disk()


def typed_snapshot(session, table, key):
    row = session.execute(select(*table.columns).where(table.c.id == key)).one()
    return tuple((type(value).__name__, value) for value in row)


class LegacyDailyVolumeFileIntegrationTests(unittest.TestCase):
    def reopen(self):
        self.engine.dispose()
        if self.reopened is not None:
            self.reopened.dispose()
        self.reopened = create_engine(f"sqlite:///{DB_PATH.as_posix()}", poolclass=NullPool,
                                      connect_args={"check_same_thread": False})
        app_db.enable_sqlite_foreign_keys(self.reopened)
        cap_engine(self.reopened)
        return sessionmaker(bind=self.reopened, autoflush=False, expire_on_commit=False)

    def assert_captures(self, factory, run_id):
        with factory() as session:
            for capture in TARGET_CAPTURES:
                raw = session.scalar(select(models.RawPayload).where(models.RawPayload.ingestion_run_id == run_id,
                    models.RawPayload.source == capture.source, models.RawPayload.endpoint == capture.endpoint,
                    models.RawPayload.sha256 == capture.sha256))
                self.assertIsNotNone(raw)
                body = Path(raw.payload_path)
                self.assertEqual(body, capture.payload_path)
                encoded = body.read_bytes()
                self.assertEqual(encoded, sources._encode_payload(capture.payload))
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), capture.sha256)
                self.assertEqual(json.loads(encoded), capture.payload)
                metadata = json.loads(body.with_suffix(".meta.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata, {"source": capture.source, "endpoint": capture.endpoint,
                    "sha256": capture.sha256, "data_as_of": DAY.isoformat(), "collected_at": CAPTURED_AT.isoformat()})
                self.assertEqual((raw.data_as_of, raw.collected_at), (DAY.isoformat(), CAPTURED_AT))

    def assert_http(self, factory, expected):
        test_app = FastAPI()
        test_app.include_router(api.router)

        def reopened_session():
            with factory() as session:
                yield session

        test_app.dependency_overrides[api.get_db] = reopened_session
        with TestClient(test_app) as client:
            for (exchange, symbol), (_label, _value) in CASES.items():
                response = client.get(f"/api/instruments/{symbol}?exchange={exchange}&as_of={DAY.isoformat()}")
                self.assertEqual(response.status_code, 200, response.text)
                bars = response.json()["bars"]
                self.assertEqual(bars, expected[(exchange, symbol)])
                if bars:
                    volume = bars[0]["volume"]
                    self.assertIs(type(volume), int)
                    tokens = re.findall(r'"volume"\s*:\s*([^,}\s]+)', response.text)
                    self.assertEqual(tokens, [str(volume)])
                    if volume == ODD:
                        self.assertNotEqual(volume, int(float(ODD)))
                        self.assertEqual(str(volume), "9007199254740993")
                VERIFIED["http_responses"] += 1

    def test_exact_volume_and_rejections_survive_disk_reopen_and_http(self):
        global PROBING_GUARD
        self.assertFalse(DB_PATH.exists(), "Requires a fresh owned DB")
        self.engine = app_db.engine
        self.reopened = None
        self.addCleanup(self.dispose)
        # These are audit signals only; no denied operation is actually issued.
        for event_name, args in (
                ("open", (str(ROOT / "unapproved.txt"), "w", os.O_CREAT)),
                ("os.mkdir", (str(ROOT / "unapproved-dir"), 0o777, -1)),
                ("sqlite3.connect", (str(ROOT.parent / "unowned.db"),)),
                ("socket.connect", (None, ("203.0.113.1", 443))),
                ("subprocess.Popen", ("unapproved", [], None, None))):
            PROBING_GUARD = True
            try:
                with self.assertRaises(RuntimeError):
                    sys.audit(event_name, *args)
            finally:
                PROBING_GUARD = False
        cap_engine(self.engine)
        app_db.init_db()
        existing_ids = {}
        with app_db.SessionLocal() as session:
            original_raw = models.RawPayload(source="synthetic-existing", endpoint="fixture://existing-bars",
                payload_path=None, sha256="a" * 64, data_as_of=DAY.isoformat(), collected_at=CAPTURED_AT)
            session.add(original_raw)
            session.flush()
            for index, ((exchange, symbol), (label, _value)) in enumerate(CASES.items(), start=1):
                if not label.endswith("_EXISTING"):
                    continue
                instrument = models.Instrument(symbol=symbol, exchange=exchange, name="Synthetic " + label,
                    instrument_type="stock", listing_date=date(2020, 1, 2), industry="24")
                session.add(instrument)
                session.flush()
                bar = models.MarketBar(instrument_id=instrument.id, trading_date=DAY,
                    open=90.25 + index, high=99.75 + index, low=85.5 + index, close=95.5 + index,
                    adj_close=94.75 + index, volume=700 + index, turnover=12345.5 + index,
                    turnover_status="unknown", turnover_reason="legacy_zero_ambiguous", source="synthetic-existing",
                    data_as_of=datetime(2026, 9, 4, 13, 30, index), collected_at=CAPTURED_AT,
                    raw_payload_id=original_raw.id, is_suspended=index % 2 == 0)
                session.add(bar)
                session.flush()
                existing_ids[(exchange, symbol)] = bar.id
            session.commit()
            original_raw_id = original_raw.id
            original_raw_snapshot = typed_snapshot(session, models.RawPayload.__table__, original_raw_id)
            existing_snapshots = {key: typed_snapshot(session, models.MarketBar.__table__, bar_id)
                                  for key, bar_id in existing_ids.items()}

        fetcher = MemoryEndpointFetcher()
        twse, tpex = sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher)
        self.assertIsNone(twse.stock_day_capture)
        adapter = sources.OfficialMarketDataAdapter(twse=twse, tpex=tpex)
        with patch.object(sources, "capture_payload", bounded_capture):
            result = pipeline.collect(DAY, adapter=adapter, force=True)
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual((result["records"], result["taiex_records"], result["no_data_dates"]), (7, 1, []))
        self.assertEqual(len(TARGET_CAPTURES), 3)
        self.assertEqual(twse.no_data_dates, [])
        self.assertEqual(tpex.no_data_dates, [])
        self.assertEqual(sum(endpoint == sources.TWSE_DAILY_ENDPOINT for endpoint, _, _ in fetcher.calls), 1)
        self.assertEqual(sum(endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT + "?") for endpoint, _, _ in fetcher.calls), 1)
        self.assertEqual(sum(endpoint == sources.TPEX_HISTORY_API for endpoint, _, _ in fetcher.calls), 1)
        VERIFIED["accepted_collects"] += 1
        factory = self.reopen()
        self.assert_captures(factory, result["run_id"])
        expected_http, preserved_bars, preserved_raw = {}, {}, {}
        history_digest = {capture.source: capture.sha256 for capture in TARGET_CAPTURES
                          if capture.endpoint != sources.TWSE_DAILY_ENDPOINT}
        with factory() as session:
            self.assertEqual(typed_snapshot(session, models.RawPayload.__table__, original_raw_id), original_raw_snapshot)
            for key, (label, _raw_value) in CASES.items():
                exchange, symbol = key
                bars = session.scalars(select(models.MarketBar).join(models.Instrument).where(
                    models.Instrument.exchange == exchange, models.Instrument.symbol == symbol,
                    models.MarketBar.trading_date == DAY)).all()
                self.assertEqual(len(bars), 0 if label.endswith("_EMPTY") else 1, key)
                expected_http[key] = [api.bar_dict(bar) for bar in bars]
                if label in LEGAL:
                    bar = bars[0]
                    self.assertIs(type(bar.volume), int)
                    self.assertEqual((bar.volume, str(bar.volume)), (LEGAL[label], str(LEGAL[label])))
                    storage_type = session.connection().exec_driver_sql(
                        "SELECT typeof(volume) FROM market_bars WHERE id=?", (bar.id,)).scalar()
                    self.assertEqual(storage_type, "integer")
                    self.assertEqual((bar.open, bar.high, bar.low, bar.close, bar.turnover,
                                      bar.turnover_status, bar.turnover_reason), (100, 105, 98, 103, 103000, "available", None))
                    self.assertEqual(session.get(models.RawPayload, bar.raw_payload_id).sha256,
                                     history_digest["twse" if exchange == "TWSE" else "tpex"])
                    if label == "ODD":
                        self.assertNotEqual(bar.volume, int(float(ODD)))
                elif label.endswith("_EXISTING"):
                    self.assertEqual(typed_snapshot(session, models.MarketBar.__table__, existing_ids[key]), existing_snapshots[key])
            for bar in session.scalars(select(models.MarketBar)):
                preserved_bars[bar.id] = typed_snapshot(session, models.MarketBar.__table__, bar.id)
            for raw in session.scalars(select(models.RawPayload)):
                preserved_raw[raw.id] = typed_snapshot(session, models.RawPayload.__table__, raw.id)
            self.assertEqual(len(preserved_bars), 19)  # Six accepted, twelve existing, TAIEX.
            self.assertEqual(session.connection().exec_driver_sql("PRAGMA integrity_check").scalar(), "ok")
            self.assertEqual(session.connection().exec_driver_sql("PRAGMA foreign_key_check").all(), [])
        self.assert_http(factory, expected_http)
        before_files = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in ALLOWED_FILES if path.suffix == ".json" and path.exists()}

        # Both markets contain rows, all security rows are invalid, and the
        # valid TAIEX must not turn this into success or a legal no-data day.
        invalid_fetcher = MemoryEndpointFetcher(all_invalid=True)
        invalid_twse, invalid_tpex = sources.TwseAdapter(invalid_fetcher), sources.TpexAdapter(invalid_fetcher)
        invalid_adapter = sources.OfficialMarketDataAdapter(twse=invalid_twse, tpex=invalid_tpex)
        with patch.object(sources, "capture_payload", bounded_capture):
            failed = pipeline.collect(DAY, adapter=invalid_adapter, force=True)
        self.assertEqual(failed["status"], "failed", failed)
        self.assertEqual((failed["records"], failed["no_data_dates"], failed["run_id"]), (0, [], result["run_id"]))
        self.assertIn("official payloads contained no normalized security OHLCV rows", failed["error"])
        self.assertEqual((invalid_twse.no_data_dates, invalid_tpex.no_data_dates), ([], []))
        self.assertEqual(len(TARGET_CAPTURES), 6)
        self.assertEqual(len({capture.payload_path for capture in TARGET_CAPTURES}), 6)
        VERIFIED["failed_collects"] += 1
        factory = self.reopen()
        self.assert_captures(factory, failed["run_id"])
        with factory() as session:
            for bar_id, snapshot in preserved_bars.items():
                self.assertEqual(typed_snapshot(session, models.MarketBar.__table__, bar_id), snapshot)
            self.assertEqual(session.scalar(select(func.count(models.MarketBar.id))), len(preserved_bars))
            for raw_id, snapshot in preserved_raw.items():
                self.assertEqual(typed_snapshot(session, models.RawPayload.__table__, raw_id), snapshot)
            run = session.get(models.IngestionRun, failed["run_id"])
            self.assertEqual((run.status, run.records, run.data_as_of), ("failed", 0, None))
            attempt = run.metadata_json["industry_observation_attempt"]
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(attempt["raw_persistence_errors"], [])
            for capture in TARGET_CAPTURES[3:]:
                raw = session.scalar(select(models.RawPayload).where(models.RawPayload.ingestion_run_id == run.id,
                    models.RawPayload.source == capture.source, models.RawPayload.endpoint == capture.endpoint,
                    models.RawPayload.sha256 == capture.sha256))
                self.assertIn(raw.id, attempt["raw_payload_ids"])
            self.assertEqual(session.connection().exec_driver_sql("PRAGMA integrity_check").scalar(), "ok")
            self.assertEqual(session.connection().exec_driver_sql("PRAGMA foreign_key_check").all(), [])
        self.assert_http(factory, expected_http)
        for path, digest in before_files.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(GUARD["expected_denials"], 5)
        self.assertEqual(GUARD["unexpected_denials"], 0)
        self.assertEqual(VERIFIED, {"http_responses": 60, "accepted_collects": 1, "failed_collects": 1})
        observe_disk()

    def dispose(self):
        if self.reopened is not None:
            self.reopened.dispose()
        self.engine.dispose()
        observe_disk()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LegacyDailyVolumeFileIntegrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("R1A2_LEGACY_VOLUME_METRICS=" + json.dumps({
        "tests_run": result.testsRun, "skipped": len(result.skipped), "peaks": PEAKS, "guard": GUARD,
        "verified": VERIFIED,
        "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        "versions": {name: importlib.metadata.version(name) for name in
                     ("SQLAlchemy", "alembic", "fastapi", "httpx", "pydantic", "starlette")},
        "legal_cases": 6, "rejection_cases": 24, "forced_all_invalid_runs": 1,
        "target_captures": len(TARGET_CAPTURES), "api_startup": "not_exercised",
        "target_source": "local_unsigned_synthetic_fixture", "adapter_scope": "real_TWSE_and_TPEx_via_combined",
    }, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun == 1 and not result.skipped else 1)
