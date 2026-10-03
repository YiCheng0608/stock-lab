"""One bounded synthetic STOCK_DAY_ALL integration case, using its own runner.

This checks current-schema persistence, not legacy migration or live official
data. Only ancillary endpoint capture metadata is replaced with memory fixtures.
The target capture, selection, TWSE/combined adapters, collector, and API remain
real. An empty TPEx boundary fixture avoids exercising an unrelated exchange.
The API router is mounted in a test app without the production startup lifespan.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sqlite3
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

VALIDATION_ROOT = os.environ.get("STOCK_DAY_SELECTED_INVALID_VALIDATION_ROOT")
if not VALIDATION_ROOT:
    if __name__ == "__main__":
        raise SystemExit("Run tools/Invoke-StockDaySelectedInvalidValidation.ps1")
    raise unittest.SkipTest("Requires the bounded selected-invalid runner")

ROOT = Path(VALIDATION_ROOT).resolve()
OWNER = os.environ.get("STOCK_DAY_SELECTED_INVALID_RUN_OWNER", "")
TEMP_BASE = Path(os.environ["LOCALAPPDATA"]).resolve() / "Temp"
if (not re.fullmatch(r"[A-Za-z0-9]{8}", OWNER)
        or not re.fullmatch(r"taiwan-stock-r1a2-si-" + OWNER + r"-[a-f0-9]{32}", ROOT.name)
        or ROOT.parent != TEMP_BASE or not ROOT.is_dir()):
    raise RuntimeError("Invalid owned validation root")
DB_PATH = ROOT / "data" / "selected-invalid.db"
EXPECTED_ENV = {"STOCK_DATA_DIR": ROOT / "data", "STOCK_RAW_DIR": ROOT / "raw", "STOCK_DB_PATH": DB_PATH}
for key, path in EXPECTED_ENV.items():
    if Path(os.environ[key]).resolve() != path:
        raise RuntimeError("Validation environment mismatch: " + key)
PEAKS = {"files": 0, "directories": 0, "bytes": 0, "db_bytes": 0}


def observe_disk() -> None:
    files, directories, total_bytes = 0, 1, 0
    fixed = {DB_PATH, Path(str(DB_PATH) + "-journal"), ROOT / "capture" / "capture.zip",
             ROOT / "capture" / ".capture.lock", ROOT / "raw" / "body.bin",
             ROOT / "raw" / "receipt.json", ROOT / "raw" / ".stock-day.lock"}
    allowed_dirs = {ROOT / "data", ROOT / "raw", ROOT / "capture"}
    if ROOT.is_symlink() or ROOT.is_junction():
        raise RuntimeError("Validation refuses a root reparse point")
    for path in ROOT.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError("Validation refuses a reparse point: " + str(path))
        if path.is_dir():
            directories += 1
            if path not in allowed_dirs:
                raise RuntimeError("Unexpected validation directory: " + str(path))
        else:
            files += 1
            total_bytes += path.stat().st_size
            stage = path.parent == ROOT / "capture" and re.fullmatch(r"\.capture-[A-Za-z0-9_-]+\.tmp", path.name)
            if path not in fixed and not stage:
                raise RuntimeError("Unexpected validation file: " + str(path))
            limit = {"capture.zip": 64 * 1024, "body.bin": 32 * 1024, "receipt.json": 32 * 1024}.get(path.name)
            if limit is not None and path.stat().st_size > limit:
                raise RuntimeError("Fixture file size limit exceeded: " + str(path))
            if stage and path.stat().st_size > 64 * 1024:
                raise RuntimeError("Capture staging size limit exceeded")
    db_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    for key, value in (("files", files), ("directories", directories), ("bytes", total_bytes), ("db_bytes", db_bytes)):
        PEAKS[key] = max(PEAKS[key], value)
    if files > 5 or directories > 4 or total_bytes > 2 * 1024 * 1024 or db_bytes > 1024 * 1024:
        raise RuntimeError("Validation disk budget exceeded: " + str(PEAKS))


# app.config creates only the two approved data/raw directories after env gates.
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import api, db as app_db, models
from app.coverage import verified_taiex_sessions
from worker import pipeline, source_registry, source_runtime, sources, stock_day_capture

DAY = date(2026, 9, 4)
CAPTURED_AT = datetime(2026, 9, 5, 0, 0, 1)
INVALID_AMOUNTS = {"NEGATIVE": "-1", "MALFORMED": "12xyz", "BADCOMMAS": "12,34"}
REJECTION_CASES = {
    "MISSING": (None, "missing_symbol"),
    "PRICE": ({"OpeningPrice": ""}, "invalid_or_missing_OpeningPrice"),
    "VOLUME": ({"TradeVolume": "1.5"}, "invalid_or_missing_TradeVolume"),
    "RANGE": ({"HighestPrice": "199"}, "inconsistent_ohlc_range"),
}
REJECTIONS = {name + suffix: (changes, reason) for name, (changes, reason) in REJECTION_CASES.items()
              for suffix in ("_EXISTING", "_EMPTY")}
SYMBOLS = list(INVALID_AMOUNTS) + list(REJECTIONS)


def capture_row(symbol, **changes):
    return {"Code": symbol, "Date": "1150904", "OpeningPrice": "200", "HighestPrice": "205",
            "LowestPrice": "198", "ClosingPrice": "203", "TradeVolume": "1,234", "TradeValue": "250,000", **changes}


class MemoryEndpointFetcher:
    """Deterministic ancillary fixtures; every unexpected endpoint fails closed."""

    def __init__(self):
        self.calls = []

    def __call__(self, endpoint, **_kwargs):
        self.calls.append(endpoint)
        if endpoint == sources.TWSE_LISTED_ENDPOINT:
            return [{"Code": symbol, "Name": symbol, "DateOfListing": "2020/01/02", "Industry": "24"}
                    for symbol in SYMBOLS]
        if endpoint in {sources.TWSE_ETF_ENDPOINT, sources.TWSE_NEW_LISTING_ENDPOINT,
                        sources.TWSE_ACTION_ENDPOINT, sources.TWSE_EVENT_ENDPOINT, sources.TWSE_FUNDAMENTAL_ENDPOINT}:
            return []
        if endpoint == sources.TWSE_INDEX_ENDPOINT:
            return [{"\u6307\u6578": "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578",
                     "\u65e5\u671f": "1150904", "\u6536\u76e4\u6307\u6578": "24000"}]
        if endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT + "?"):
            return {"date": "20260904", "tables": [
                {"title": "115\u5e7409\u670804\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                 "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578"],
                 "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "24000"]]},
                {"title": "\u6bcf\u65e5\u6536\u76e4\u884c\u60c5",
                 "fields": ["Code", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"],
                 "data": [[symbol, "50", "55", "48", "53", "500", "26500"] for symbol in SYMBOLS]},
            ]}
        if endpoint.startswith(sources.TWSE_CHIP_ENDPOINT + "?") or endpoint.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT + "?"):
            return {"date": "20260904", "fields": ["Code"], "data": []}
        raise AssertionError("Unexpected fixture endpoint: " + endpoint)


def memory_ancillary_capture(source, endpoint, payload, data_as_of=None, *, collected_at=None):
    if source != "twse" or endpoint == sources.TWSE_DAILY_ENDPOINT:
        raise AssertionError("Target capture must never use the ancillary fixture substitute")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    # This is an explicit synthetic URI, not a claim of a retained raw file.
    return sources.FetchedPayload(source, endpoint, payload, data_as_of, collected_at or CAPTURED_AT,
                                  "memory-fixture://" + digest, digest)


class EmptyTpexFixture:
    """An unrelated exchange boundary; no TPEx behavior is validated here."""

    def fetch(self, start, end):
        return sources.OfficialBatch()


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


def file_digests():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("capture/capture.zip", "raw/body.bin", "raw/receipt.json")}


class StockDaySelectedInvalidFileIntegrationTests(unittest.TestCase):
    def test_invalid_amounts_and_rejected_rows_survive_reopen_and_api(self):
        self.assertFalse(DB_PATH.exists(), "Requires a fresh owned DB")
        self.engine = app_db.engine
        self.reopened = None
        self.addCleanup(self._dispose)
        observe_disk()
        rows = [capture_row(symbol, TradeValue=value) for symbol, value in INVALID_AMOUNTS.items()]
        rows.extend(capture_row(symbol, **changes) for symbol, (changes, _) in REJECTIONS.items() if changes is not None)
        body = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.assertLessEqual(len(body), 32 * 1024)
        manifest = source_registry.load_manifest()
        pins = dict(manifest=source_registry.REGISTRY_PATH, profile="free_public_local",
                    expected_registry_version=manifest["registry_version"], expected_digest=manifest["content_digest"])
        fsync, link = os.fsync, os.link

        def observed_fsync(fd):
            result = fsync(fd)
            observe_disk()
            return result

        def observed_link(src, dst, *args, **kwargs):
            result = link(src, dst, *args, **kwargs)
            observe_disk()
            return result

        # Delegating observers count publication staging and lock files too.
        with patch.object(os, "fsync", observed_fsync), patch.object(os, "link", observed_link):
            receipt = source_runtime.capture(**pins, source_id=stock_day_capture.SOURCE_ID,
                output_dir=ROOT / "capture", transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, stream=httpx.ByteStream(body))))
            self.assertEqual(receipt["status"], "capture_complete", receipt)
            capture = stock_day_capture.load_stock_day_capture(ROOT / "capture" / "capture.zip", **pins,
                expected_market_date=DAY, output_dir=ROOT / "raw")
        self.assertEqual(capture.body, body)
        evidence_before = file_digests()
        self.assertEqual(evidence_before["raw/body.bin"], capture.sha256)
        selected, raw, unavailable = capture.select(SYMBOLS, DAY)
        self.assertEqual({bar.symbol for bar in selected}, set(INVALID_AMOUNTS))
        expected_reasons = [{"symbol": symbol, "reason": reason} for symbol, (_, reason) in REJECTIONS.items()]
        self.assertEqual(unavailable, expected_reasons)
        self.assertEqual(raw.sha256, capture.sha256)
        for bar in selected:
            self.assertEqual((bar.open, bar.high, bar.low, bar.close, bar.volume), (200, 205, 198, 203, 1234))
            self.assertEqual((bar.turnover, bar.turnover_status, bar.turnover_reason), (0, "unavailable", "invalid"))

        cap_engine(self.engine)
        app_db.init_db()  # Real current-schema initialization; no legacy fixture.
        with app_db.SessionLocal() as session:
            original_raw = models.RawPayload(source="synthetic-existing", endpoint="fixture://existing-bar",
                payload_path=None, sha256="a" * 64, data_as_of=DAY.isoformat(), collected_at=CAPTURED_AT)
            session.add(original_raw)
            session.flush()
            existing_ids = {}
            for index, symbol in enumerate((s for s in REJECTIONS if s.endswith("_EXISTING")), start=1):
                instrument = models.Instrument(symbol=symbol, exchange="TWSE", name=symbol, instrument_type="stock",
                    listing_date=date(2020, 1, 2), industry="24")
                session.add(instrument)
                session.flush()
                status, reason = [("available", None), ("unavailable", "invalid"),
                                  ("unknown", "legacy_zero_ambiguous"), ("unavailable", "missing")][index - 1]
                bar = models.MarketBar(instrument_id=instrument.id, trading_date=DAY,
                    open=90.25 + index, high=99.75 + index, low=85.5 + index, close=95.5 + index,
                    adj_close=94.75 + index, volume=700 + index, turnover=12345.5 + index,
                    turnover_status=status, turnover_reason=reason, source="synthetic-existing",
                    data_as_of=datetime(2026, 9, 4, 13, 30, index), collected_at=CAPTURED_AT,
                    raw_payload_id=original_raw.id, is_suspended=index == 4)
                session.add(bar)
                session.flush()
                existing_ids[symbol] = bar.id
            session.commit()
            original_raw_id = original_raw.id
            old_raw_snapshot = typed_snapshot(session, models.RawPayload.__table__, original_raw_id)
            old_bar_snapshots = {symbol: typed_snapshot(session, models.MarketBar.__table__, key)
                                 for symbol, key in existing_ids.items()}

        fetcher = MemoryEndpointFetcher()
        adapter = sources.TwseAdapter(fetcher, stock_day_capture=capture)
        combined = sources.OfficialMarketDataAdapter(twse=adapter, tpex=EmptyTpexFixture())
        with patch.object(sources, "capture_payload", memory_ancillary_capture):
            result = pipeline.collect(DAY, adapter=combined, force=True)
        self.assertEqual(result["status"], "partial", result)
        self.assertFalse(result.get("idempotent_reuse", False))
        self.assertEqual(adapter.stock_day_unavailable, expected_reasons)
        self.assertNotIn(sources.TWSE_DAILY_ENDPOINT, fetcher.calls)
        self.assertTrue(any(endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT + "?") for endpoint in fetcher.calls))
        for symbol in INVALID_AMOUNTS:
            self.assertTrue(any("stock_day_capture_turnover_unavailable" in warning and symbol in warning
                                and "invalid" in warning for warning in result["warnings"]), symbol)
        for symbol, (_, reason) in REJECTIONS.items():
            self.assertTrue(any("stock_day_capture_unavailable" in warning and symbol in warning and reason in warning
                                for warning in result["warnings"]), symbol)

        self.engine.dispose()
        self.reopened = create_engine(f"sqlite:///{DB_PATH.as_posix()}", poolclass=NullPool,
                                      connect_args={"check_same_thread": False})
        self.assertIsNot(self.reopened, self.engine)
        app_db.enable_sqlite_foreign_keys(self.reopened)
        cap_engine(self.reopened)
        factory = sessionmaker(bind=self.reopened, autoflush=False, expire_on_commit=False)
        with factory() as session:
            self.assertEqual(typed_snapshot(session, models.RawPayload.__table__, original_raw_id), old_raw_snapshot)
            for symbol, key in existing_ids.items():
                self.assertEqual(typed_snapshot(session, models.MarketBar.__table__, key), old_bar_snapshots[symbol], symbol)
            for symbol in REJECTIONS:
                rows_for_symbol = session.scalars(select(models.MarketBar).join(models.Instrument).where(
                    models.Instrument.exchange == "TWSE", models.Instrument.symbol == symbol,
                    models.MarketBar.trading_date == DAY)).all()
                self.assertEqual(len(rows_for_symbol), 1 if symbol.endswith("_EXISTING") else 0, symbol)
            accepted = session.scalars(select(models.MarketBar).join(models.Instrument).where(
                models.Instrument.symbol.in_(INVALID_AMOUNTS), models.MarketBar.trading_date == DAY)).all()
            self.assertEqual(len(accepted), 3)
            self.assertEqual(len({bar.raw_payload_id for bar in accepted}), 1)
            target_raw = session.get(models.RawPayload, accepted[0].raw_payload_id)
            self.assertEqual((target_raw.source, target_raw.endpoint, target_raw.payload_path, target_raw.sha256),
                             ("twse", sources.TWSE_DAILY_ENDPOINT, str(capture.body_path), capture.sha256))
            self.assertEqual(target_raw.data_as_of, DAY.isoformat())
            self.assertEqual(target_raw.collected_at, capture.captured_at.astimezone(timezone.utc).replace(tzinfo=None))
            self.assertEqual(target_raw.ingestion_run_id, result["run_id"])
            self.assertEqual(session.get(models.IngestionRun, result["run_id"]).status, "partial")
            self.assertEqual(verified_taiex_sessions(session), [DAY])
            for bar in accepted:
                self.assertEqual((bar.open, bar.high, bar.low, bar.close, bar.volume), (200, 205, 198, 203, 1234))
                self.assertEqual((bar.turnover, bar.turnover_status, bar.turnover_reason), (0, "unavailable", "invalid"))
            self.assertEqual(session.connection().exec_driver_sql("PRAGMA integrity_check").scalar(), "ok")
            self.assertEqual(session.connection().exec_driver_sql("PRAGMA foreign_key_check").all(), [])

        # Production handler/serialization through HTTP, using only the new engine.
        # Startup readiness is outside this focused test; no lifespan is installed.
        test_app = FastAPI()
        test_app.include_router(api.router)

        def reopened_session():
            with factory() as session:
                yield session

        test_app.dependency_overrides[api.get_db] = reopened_session
        with TestClient(test_app) as client:
            for symbol in SYMBOLS:
                response = client.get(f"/api/instruments/{symbol}?exchange=TWSE&as_of={DAY.isoformat()}")
                self.assertEqual(response.status_code, 200, response.text)
                bars = response.json()["bars"]
                if symbol in INVALID_AMOUNTS:
                    self.assertEqual(len(bars), 1)
                    self.assertEqual(tuple(bars[0][key] for key in ("open", "high", "low", "close", "volume")),
                                     (200, 205, 198, 203, 1234))
                    self.assertEqual(tuple(bars[0][key] for key in ("turnover", "turnover_status", "turnover_reason")),
                                     (0, "unavailable", "invalid"))
                elif symbol.endswith("_EMPTY"):
                    self.assertEqual(bars, [], symbol)
                else:
                    with factory() as session:
                        self.assertEqual(bars, [api.bar_dict(session.get(models.MarketBar, existing_ids[symbol]))], symbol)
        self.assertEqual(file_digests(), evidence_before)
        # Revalidate the same capture's materialized bytes after ingestion/API.
        self.assertEqual(capture.select(SYMBOLS, DAY)[2], expected_reasons)
        observe_disk()

    def _dispose(self):
        if self.reopened is not None:
            self.reopened.dispose()
        self.engine.dispose()
        observe_disk()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(StockDaySelectedInvalidFileIntegrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    versions = {name: importlib.metadata.version(name) for name in
                ("SQLAlchemy", "alembic", "fastapi", "httpx", "pydantic", "starlette")}
    print("R1A2_SELECTED_INVALID_METRICS=" + json.dumps({
        "tests_run": result.testsRun, "skipped": len(result.skipped), "peaks": PEAKS,
        "python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "versions": versions,
        "invalid_amount_cases": 3, "rejection_cases": 8, "api_startup": "not_exercised",
        "target_source": "local_unsigned_synthetic_fixture",
        "adapter_scope": "TWSE_target_via_combined_with_empty_TPEx_fixture",
    }, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun == 1 and not result.skipped else 1)
