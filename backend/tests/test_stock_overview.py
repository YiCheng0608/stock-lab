"""Reconstructable small capture evidence and memory-only overview/API checks.

Run with --noconftest: the legacy global conftest allocates unrelated disk roots.
Temporary files are needed only to exercise the production read-only file gate.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import _stock_news_cutoff_filter, get_db, router, stock_detail
from app.db import Base
from app.models import (ChipSnapshot, Event, GroupMembership, IngestionRun, Instrument,
                        MarketBar, NewsItem, Signal, StrategyVersion, TechnicalFeature, ThemeGroup)
from app.stock_overview import (MANIFEST_PATH, PROFILE, REGISTRY_DIGEST, REGISTRY_VERSION,
                                build_stock_overview, _capture_evidence)
from worker.pipeline import _upsert_official_bar, _upsert_raw_payload
from worker.source_runtime import capture
from worker.stock_day_capture import ENDPOINT, SOURCE_ID, load_stock_day_capture

DAY = date(2026, 10, 1)
ROW = {"Date": "1151001", "Code": "1101", "Name": "台泥", "OpeningPrice": "26.30",
       "HighestPrice": "26.40", "LowestPrice": "25.45", "ClosingPrice": "25.55",
       "TradeVolume": "54833108", "TradeValue": "1412587301"}


class StockOverviewTest(unittest.TestCase):
    def setUp(self):
        self.files = tempfile.TemporaryDirectory(prefix="overview-", dir=os.environ["TEMP"])
        self.addCleanup(self.files.cleanup)
        self.root = Path(self.files.name)
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False, autoflush=False)
        self.addCleanup(self.db.close)
        self.instrument = Instrument(exchange="TWSE", symbol="1101", name="台泥", instrument_type="stock", status="active")
        self.run = IngestionRun(run_type="collect", source="official", run_date=DAY, status="success", data_as_of=DAY.isoformat())
        self.db.add_all([self.instrument, self.run])
        self.db.flush()
        self.load_row(ROW)

    def load_row(self, row):
        suffix = len(list(self.root.iterdir()))
        output = self.root / f"capture-{suffix}"
        body = json.dumps([row], ensure_ascii=False).encode()
        receipt = capture(manifest=MANIFEST_PATH, profile=PROFILE, source_id=SOURCE_ID,
                          expected_registry_version=REGISTRY_VERSION, expected_digest=REGISTRY_DIGEST,
                          output_dir=output,
                          transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(body))))
        self.assertEqual(receipt["status"], "capture_complete")
        selected = load_stock_day_capture(output / "capture.zip", manifest=MANIFEST_PATH, profile=PROFILE,
                                         expected_registry_version=REGISTRY_VERSION, expected_digest=REGISTRY_DIGEST,
                                         expected_market_date=DAY, output_dir=self.root / f"consumer-{suffix}")
        records, payload, unavailable = selected.select(["1101"], DAY)
        self.assertEqual(unavailable, [])
        self.raw = _upsert_raw_payload(self.db, self.run, payload)
        self.bar = _upsert_official_bar(self.db, self.instrument, records[0], self.raw.id)
        self.db.flush()

    def overview(self, cutoff=DAY):
        return build_stock_overview(self.db, self.instrument, cutoff)

    def assert_rejected(self, reason):
        price = self.overview()["price"]
        self.assertEqual(price["status"], "unavailable")
        self.assertIsNone(price["latest"])
        self.assertIn(reason, price["reasons"])

    def test_capture_values_and_provenance_without_session_baseline(self):
        value = build_stock_overview(self.db, self.instrument)
        price = value["price"]
        self.assertEqual(value["as_of"], "2026-10-01")
        self.assertEqual(price["valid_count"], 1)
        self.assertEqual(price["from"], price["to"])
        latest = price["latest"]
        self.assertEqual([latest[key] for key in ("open", "high", "low", "close", "volume", "turnover")],
                         [26.3, 26.4, 25.45, 25.55, 54833108, 1412587301])
        self.assertEqual(latest["provenance"]["body_sha256"], self.raw.sha256)
        self.assertEqual(latest["provenance"]["source_id"], SOURCE_ID)
        self.assertEqual(latest["provenance"]["summarize_decision"]["decision"], "allow")
        self.assertEqual(value["historical_pit"], "unsupported")
        self.assertIsNone(value["institutional"]["values"])
        self.assertEqual({item["status"] for item in value["conditions"]}, {"data_insufficient"})

    def test_explicit_zero_and_missing_amount_are_distinct(self):
        zero = deepcopy(ROW)
        zero["TradeValue"] = "0"
        self.load_row(zero)
        self.assertEqual(self.overview()["price"]["latest"]["turnover"], 0)
        missing = deepcopy(ROW)
        missing.pop("TradeValue")
        self.load_row(missing)
        latest = self.overview()["price"]["latest"]
        self.assertIsNone(latest["turnover"])
        self.assertEqual((latest["turnover_status"], latest["turnover_reason"]), ("unavailable", "missing"))

    def test_invalid_amount_does_not_remove_valid_price(self):
        row = deepcopy(ROW)
        row["TradeValue"] = "bad"
        self.load_row(row)
        latest = self.overview()["price"]["latest"]
        self.assertEqual(latest["close"], 25.55)
        self.assertIsNone(latest["turnover"])
        self.assertEqual(latest["turnover_reason"], "invalid")

    def test_zero_volume_is_preserved(self):
        row = deepcopy(ROW)
        row["TradeVolume"] = "0"
        self.load_row(row)
        self.assertEqual(self.overview()["price"]["latest"]["volume"], 0)

    def test_source_name_cannot_replace_exact_endpoint(self):
        self.raw.endpoint = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        self.assert_rejected("price_source_not_admitted")

    def test_other_exchange_cannot_use_twse_raw(self):
        self.instrument.exchange = "TPEx"
        self.assert_rejected("price_source_not_admitted")

    def test_missing_raw_fk_and_ingestion_are_rejected(self):
        self.bar.raw_payload_id = None
        self.assert_rejected("price_raw_evidence_missing")
        self.bar.raw_payload_id = self.raw.id
        self.run.source = "demo"
        self.assert_rejected("price_ingestion_provenance_missing")

    def test_hash_and_receipt_pins_are_required(self):
        self.raw.sha256 = "0" * 64
        self.assert_rejected("price_body_hash_mismatch")
        self.raw.sha256 = json.loads(Path(self.raw.payload_path).with_name("receipt.json").read_bytes())["body_sha256"]
        path = Path(self.raw.payload_path).with_name("receipt.json")
        receipt = json.loads(path.read_bytes())
        receipt["manifest_digest"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(receipt), encoding="utf-8")
        self.assert_rejected("price_receipt_mismatch")

    def test_raw_date_and_capture_time_are_required(self):
        self.raw.data_as_of = "2026-09-30"
        self.assert_rejected("price_raw_date_mismatch")
        self.raw.data_as_of = DAY.isoformat()
        self.raw.collected_at += timedelta(seconds=1)
        self.assert_rejected("price_capture_time_mismatch")

    def test_ohlc_and_volume_boundaries(self):
        for value in (float("inf"), float("nan"), 0, -1):
            with self.subTest(close=value):
                self.bar.close = value
                self.assert_rejected("price_invalid_ohlc")
        self.bar.close = 25.55
        self.bar.low = 27
        self.assert_rejected("price_invalid_ohlc")
        self.bar.low = 25.45
        self.bar.volume = -1
        self.assert_rejected("price_invalid_volume")

    def test_canonical_values_identity_and_amount_cannot_drift(self):
        self.bar.close = 25.6
        self.assert_rejected("price_selected_value_mismatch")
        self.bar.close = 25.55
        self.bar.turnover_status = "unknown"
        self.assert_rejected("price_turnover_state_mismatch")
        self.bar.turnover_status = "available"
        self.instrument.symbol = "2330"
        self.assert_rejected("price_selected_row_invalid")

    def test_duplicate_dates_fail_closed(self):
        db = MagicMock()
        db.scalars.return_value.all.return_value = [self.bar, self.bar]
        db.execute.return_value.all.return_value = []
        price = build_stock_overview(db, self.instrument, DAY)["price"]
        self.assertEqual(price["valid_count"], 0)
        self.assertEqual(len(price["rejected"]), 2)
        self.assertEqual(price["reasons"], ["price_duplicate_date"])

    def test_changed_evidence_is_rejected(self):
        from app.stock_overview import _stable_read
        calls = 0
        def changed(bound, limit):
            nonlocal calls
            calls += 1
            if calls == 3:
                return b"changed"
            return _stable_read(bound, limit)
        with patch("app.stock_overview._stable_read", side_effect=changed):
            self.assert_rejected("price_evidence_changed")

    def test_actual_content_change_during_validation_is_rejected(self):
        from worker.stock_day_capture import _rows
        def mutate_after_parse(body):
            rows = _rows(body)
            Path(self.raw.payload_path).write_bytes(body + b" ")
            return rows
        with patch("app.stock_overview._rows", side_effect=mutate_after_parse):
            self.assert_rejected("body_changed")

    def test_failed_raw_is_checked_once_per_request(self):
        extra = MarketBar(instrument_id=self.instrument.id, trading_date=DAY + timedelta(days=1),
                          open=26.3, high=26.4, low=25.45, close=25.55, adj_close=25.55,
                          volume=54833108, source="twse", raw_payload_id=self.raw.id)
        self.db.add(extra)
        self.db.flush()
        self.raw.sha256 = "0" * 64
        with patch("app.stock_overview._capture_evidence", wraps=_capture_evidence) as validator:
            value = build_stock_overview(self.db, self.instrument)
        self.assertEqual(validator.call_count, 1)
        self.assertEqual(value["price"]["valid_count"], 0)

    def test_newer_unadmitted_row_blocks_latest_and_retains_qualified_history(self):
        self.db.add(MarketBar(instrument_id=self.instrument.id, trading_date=DAY + timedelta(days=1),
                             open=30, high=31, low=29, close=30, adj_close=30, volume=10, source="twse"))
        self.db.flush()
        value = build_stock_overview(self.db, self.instrument)
        self.assertEqual(value["as_of"], "2026-10-02")
        self.assertIsNone(value["price"]["latest"])
        self.assertEqual(value["price"]["status"], "unavailable")
        self.assertEqual([row["date"] for row in value["price"]["bars"]], ["2026-10-01"])
        self.assertEqual(value["price"]["valid_count"], 1)
        self.assertEqual(value["price"]["candidate_count"], 2)
        self.assertIn("price_latest_candidate_unqualified", value["price"]["reasons"])
        self.assertIn("price_raw_evidence_missing", value["price"]["reasons"])

    def test_cutoff_excludes_later_bar_feature_signal_chip_event_and_membership(self):
        future = DAY + timedelta(days=1)
        group = ThemeGroup(id="future", name="Industry · Future")
        version = StrategyVersion(name="breakout_v1", version="1.0.0", kind="rule")
        self.db.add_all([group, version])
        self.db.flush()
        self.db.add_all([
            TechnicalFeature(instrument_id=self.instrument.id, trading_date=future, features_json={"ma20": 999}),
            ChipSnapshot(instrument_id=self.instrument.id, trading_date=future, foreign_buy=999),
            Event(instrument_id=self.instrument.id, event_date=future, event_type="announcement", title="future"),
            GroupMembership(instrument_id=self.instrument.id, group_id=group.id, valid_from=future),
            Signal(instrument_id=self.instrument.id, strategy_version_id=version.id, signal_key="future",
                   signal_date=future, status="conditional", data_quality="complete"),
        ])
        self.db.flush()
        payload = stock_detail("TWSE", "1101", self.db, DAY)
        self.assertEqual(payload["features"], {})
        self.assertEqual(payload["signals"], [])
        self.assertEqual(payload["chips"], [])
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["groups"], [])
        earlier = stock_detail("TWSE", "1101", self.db, DAY - timedelta(days=1))
        self.assertEqual(earlier["bars"], [])
        self.assertIsNone(earlier["overview"]["price"]["latest"])

    def test_news_cutoff_uses_original_role_and_preserves_future_event_announcement(self):
        self.db.add_all([
            NewsItem(canonical_key="published", source_name="TWSE", title="announced", symbols_json=["1101"],
                     published_at=datetime(2026, 10, 1, 10), event_date=DAY + timedelta(days=3), time_consistency="verified"),
            NewsItem(canonical_key="later", source_name="TWSE", title="later", symbols_json=["1101"],
                     published_at=datetime(2026, 10, 1, 17), time_consistency="verified"),
            NewsItem(canonical_key="unknown", source_name="TWSE", title="unknown", symbols_json=["1101"], time_consistency="unverified"),
        ])
        self.db.flush()
        payload = stock_detail("TWSE", "1101", self.db, DAY)
        self.assertEqual([item["title"] for item in payload["news"]], ["announced"])
        self.assertEqual(payload["news"][0]["event_date"], "2026-10-04")
        self.assertEqual(payload["news"][0]["published_at"], "2026-10-01T10:00:00")
        self.assertEqual(payload["news_cutoff"]["filter"], "verified_publication_or_event")

    def test_news_limit_applies_after_cutoff(self):
        self.db.add(NewsItem(canonical_key="old", source_name="TWSE", title="before cutoff", symbols_json=["1101"],
                             published_at=datetime(2026, 9, 30, 10), time_consistency="verified"))
        self.db.add_all([NewsItem(canonical_key=f"later-{index}", source_name="TWSE", title="later", symbols_json=["1101"],
                                  published_at=datetime(2026, 10, 2, 10, 0, index % 60), time_consistency="verified")
                         for index in range(205)])
        self.db.flush()
        payload = stock_detail("TWSE", "1101", self.db, DAY)
        self.assertEqual([item["title"] for item in payload["news"]], ["before cutoff"])

    def test_no_price_uses_existing_independent_record_date(self):
        self.db.delete(self.bar)
        self.db.add(TechnicalFeature(instrument_id=self.instrument.id, trading_date=DAY, features_json={"ma20": 25}))
        self.db.add(ChipSnapshot(instrument_id=self.instrument.id, trading_date=DAY, foreign_buy=100))
        self.db.flush()
        payload = stock_detail("TWSE", "1101", self.db)
        self.assertEqual(payload["overview"]["as_of"], DAY.isoformat())
        self.assertEqual(payload["features"], {"ma20": 25})
        self.assertEqual(len(payload["chips"]), 1)
        self.assertEqual(payload["overview"]["price"]["status"], "unavailable")

    def test_news_only_and_financial_announcement_supply_cutoff(self):
        from app.models import FundamentalSnapshot
        self.db.delete(self.bar)
        self.db.add(NewsItem(canonical_key="only", source_name="TWSE", title="news only", symbols_json=["1101"],
                             published_at=datetime(2026, 10, 1, 17), time_consistency="verified"))
        self.db.flush()
        payload = stock_detail("TWSE", "1101", self.db)
        self.assertEqual(payload["overview"]["as_of"], "2026-10-02")
        self.assertEqual([item["title"] for item in payload["news"]], ["news only"])
        self.db.add(FundamentalSnapshot(instrument_id=self.instrument.id, period_end=date(2026, 6, 30),
                                        fiscal_period="Q2", announcement_date=date(2026, 10, 3), source="mops"))
        self.db.flush()
        payload = stock_detail("TWSE", "1101", self.db)
        self.assertEqual(payload["overview"]["as_of"], "2026-10-03")
        self.assertEqual(len(payload["fundamentals"]), 1)

    def test_null_persisted_time_role_uses_publication_fallback(self):
        # A minimal legacy shape exercises SQL NULL semantics without weakening
        # the canonical mapped NOT NULL schema or creating a disk database.
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE news_items (id INTEGER, event_id INTEGER, display_time TEXT, time_basis TEXT, time_precision TEXT, event_date TEXT, published_at TEXT, event_at TEXT, time_consistency TEXT)")
                connection.exec_driver_sql("CREATE TABLE events (id INTEGER, event_date TEXT)")
                connection.exec_driver_sql("INSERT INTO news_items VALUES (1, NULL, '2026-10-01 10:00:00', NULL, NULL, NULL, '2026-10-01 10:00:00', NULL, 'verified')")
                rows = connection.execute(select(NewsItem.id).outerjoin(Event, NewsItem.event_id == Event.id).where(_stock_news_cutoff_filter(DAY))).all()
                self.assertEqual(rows, [(1,)])
        finally:
            engine.dispose()

    def test_instrument_without_dated_records_has_no_latest_fallback(self):
        self.db.delete(self.bar)
        self.db.flush()
        payload = stock_detail("TWSE", "1101", self.db)
        self.assertIsNone(payload["overview"]["as_of"])
        self.assertEqual(payload["bars"], [])
        self.assertEqual(payload["features"], {})
        self.assertIsNone(payload["decision_summary"])

    def test_api_routes_date_validation_and_existing_detail_contract(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            response = client.get("/api/stocks/TWSE/1101/overview?as_of=2026-10-01")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["price"]["latest"]["close"], 25.55)
            detail = client.get("/api/stocks/TWSE/1101?as_of=2026-09-30")
            self.assertEqual(detail.status_code, 200)
            self.assertIn("strategy_conditions", detail.json())
            self.assertEqual(detail.json()["bars"], [])
            self.assertEqual(client.get("/api/stocks/TWSE/1101?as_of=2026-02-30").status_code, 422)
            self.assertEqual(client.get("/api/stocks/TWSE/missing/overview").status_code, 404)
            self.assertEqual(client.get("/api/instruments/1101?exchange=TWSE").status_code, 200)


if __name__ == "__main__":
    unittest.main()
