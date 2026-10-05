"""Actual router checks with the real catalogue schema and SQLite :memory: only."""
from contextlib import ExitStack
from datetime import date
import os
import unittest
from unittest.mock import patch
from test_tpex_price_capture import SyntheticPolicyScope
from worker import tpex_price_capture as worker


class MemoryAPIFixture:
    def __init__(self, *, live=False):
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from app import api, tpex_price
        from app.db import Base
        from app.models import Instrument, MarketBar
        self.api, self.wrapper = api, tpex_price
        self.stack = ExitStack()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            for exchange, symbol, name, kind, market, category in (
                ("TPEx", "3105", "穩懋", "stock", "TW", None), ("TPEx", "6488", "環球晶", "stock", "TW", None),
                ("TWSE", "3105", "穩懋", "stock", "TW", None), ("TPEx", "9999", "unknown", "stock", "TW", None),
                ("TPEx", "00620", "synthetic ETF", "etf", "TW", "domestic")):
                item = Instrument(exchange=exchange, symbol=symbol, name=name, instrument_type=kind, market=market, etf_category=category)
                db.add(item); db.flush()
                # Explicit earlier synthetic row ensures default cutoff does not drift.
                db.add(MarketBar(instrument_id=item.id, trading_date=date(2026, 10, 2), open=10, high=11, low=9,
                                 close=10, adj_close=10, volume=1000, source="synthetic", is_suspended=False))
            db.commit()
        self.app = FastAPI()
        self.app.include_router(api.router)
        def database():
            with Session(self.engine) as db: yield db
        self.app.dependency_overrides[api.get_db] = database
        if live:
            self.fixture = None
            self.store = tpex_price.TpexPriceStore()
            env = {tpex_price.ENABLE_ENV: "1", tpex_price.POLICY_VERSION_ENV: tpex_price.POLICY_VERSION, tpex_price.POLICY_DIGEST_ENV: tpex_price.POLICY_DIGEST}
        else:
            self.fixture = self.stack.enter_context(SyntheticPolicyScope())
            self.store = tpex_price.TpexPriceStore(loader=self.fixture.loader)
            env = self.fixture.env
        self.stack.enter_context(patch.object(tpex_price, "STORE", self.store))
        self.stack.enter_context(patch.dict(os.environ, env))
        self.before = self.snapshot()

    def snapshot(self):
        with self.engine.connect() as connection:
            names = [row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name: [tuple(row) for row in connection.exec_driver_sql('SELECT * FROM "' + name + '" ORDER BY rowid')] for name in names}

    def close(self):
        self.stack.close()
        self.engine.dispose()


class PriceAPITests(unittest.TestCase):
    def test_actual_router_get_default_and_unsupported_are_zero_source(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client:
                for path in ("/api/stocks/TPEx/3105", "/api/stocks/TPEx/6488?as_of=2026-10-05",
                             "/api/stocks/TPEx/3105/overview?as_of=2026-10-05"):
                    result = client.get(path)
                    self.assertEqual(result.status_code, 200)
                for route in ("TPEx/3105", "TWSE/3105", "TPEx/9999", "TPEx/00620"):
                    value = client.post("/api/stocks/" + route + "/prices/capture?as_of=2026-10-02").json()
                    self.assertEqual(value["status"], "unavailable")
                self.assertEqual(client.post("/api/stocks/TPEx/3105/prices/capture").json()["reasons"], ["price_cutoff_not_supported"])
                self.assertEqual(client.post("/api/stocks/TPEx/missing/prices/capture?as_of=2026-10-05").status_code, 404)
                self.assertEqual(client.post("/api/stocks/TPEx/3105/prices/capture?as_of=bad").status_code, 422)
            self.assertEqual(fixture.fixture.opener.calls, [])
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_actual_router_twelve_values_cache_null_ids_and_no_cutoff_leak(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client:
                first = client.post("/api/stocks/TPEx/3105/prices/capture?as_of=2026-10-05").json()
                self.assertEqual(first["status"], "available")
                for symbol, expected in (("3105", (614, 630, 604, 615, "48127911", "29694939981")),
                                         ("6488", (1220, 1235, 1175, 1180, "18982607", "22887612060"))):
                    detail = client.get("/api/stocks/TPEx/" + symbol + "?as_of=2026-10-05").json()
                    memory = detail["overview"]["price_memory"]
                    bar = memory["latest"]
                    self.assertEqual(tuple(bar[key] for key in ("open", "high", "low", "close", "volume_exact", "turnover_exact")), expected)
                    self.assertEqual(memory["as_of"], detail["overview"]["as_of"])
                    self.assertEqual(bar["date"], "2026-10-05")
                    self.assertIsNone(bar["id"])
                    self.assertIsNone(memory["provenance"]["raw_payload_id"])
                    self.assertIsNone(memory["provenance"]["ingestion_run_id"])
                    self.assertEqual(memory["origin"], "process_memory")
                    self.assertEqual(detail["bars"][-1]["date"], "2026-10-02")
                    self.assertEqual(detail["overview"]["price"]["status"], "unavailable")
                    self.assertEqual(client.post("/api/stocks/TPEx/" + symbol + "/prices/capture?as_of=2026-10-05").json()["capture_state"]["action"], "cached")
                earlier = client.get("/api/stocks/TPEx/3105?as_of=2026-10-02").json()
                default = client.get("/api/stocks/TPEx/3105").json()
                self.assertIsNone(earlier["overview"]["price_memory"]["latest"])
                self.assertEqual(default["overview"]["as_of"], "2026-10-02")
                self.assertIsNone(default["overview"]["price_memory"]["latest"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

