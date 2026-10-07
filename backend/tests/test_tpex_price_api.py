"""Actual router checks with the real catalogue schema and SQLite :memory: only."""
from contextlib import ExitStack
from datetime import date
import os
import unittest
from unittest.mock import patch
from test_tpex_price_capture import SyntheticPolicyScope
from worker import tpex_price_capture as worker


class MemoryAPIFixture:
    def __init__(self, *, live=False, cutoff=worker.CUTOFF, policy_version=None):
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from app import api, tpex_price
        from app.db import Base
        from app.models import Instrument, MarketBar
        self.api, self.wrapper = api, tpex_price
        self.stack = ExitStack()
        version = policy_version or (worker.price_policy(cutoff)["version"] if live else worker.POLICY_VERSION if cutoff == worker.CUTOFF else "m1-price-tpex-11370-2026-10-06.1")
        selected = worker.policy_symbols(cutoff, policy_version=version)
        self.catalogue_kind = "memory operational catalogue from root-verified selected identities; retained bars and unsupported anchors synthetic" if live else "synthetic contract catalogue"
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.finance_seed_rows = 0
        with Session(self.engine) as db:
            for exchange, symbol, name, kind, market, category in (
                *(("TPEx", symbol, name, "stock", "TW", None) for symbol, name in selected.items()),
                ("TWSE", "3105", "穩懋", "stock", "TW", None), ("TPEx", "9999", "unknown", "stock", "TW", None),
                ("TPEx", "00620", "synthetic ETF", "etf", "TW", "domestic")):
                item = Instrument(exchange=exchange, symbol=symbol, name=name, instrument_type=kind, market=market, etf_category=category)
                db.add(item); db.flush()
                # Explicit earlier synthetic row ensures default cutoff does not drift.
                if not (live and cutoff == worker.EIGHTH_CUTOFF):
                    db.add(MarketBar(instrument_id=item.id, trading_date=date(2026, 10, 2), open=10, high=11, low=9,
                                     close=10, adj_close=10, volume=1000, source="synthetic", is_suspended=False))
                    self.finance_seed_rows += 1
            db.commit()
        self.app = FastAPI()
        self.app.include_router(api.router)
        def database():
            with Session(self.engine) as db: yield db
        self.app.dependency_overrides[api.get_db] = database
        if live:
            self.fixture = None
            self.store = tpex_price.TpexPriceStore()
            version, pin = tpex_price.policy_pins(cutoff, policy_version=version)
            env = {tpex_price.ENABLE_ENV: "1", tpex_price.POLICY_VERSION_ENV: version, tpex_price.POLICY_DIGEST_ENV: pin}
        else:
            self.fixture = self.stack.enter_context(SyntheticPolicyScope(cutoff=cutoff, policy_version=version))
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
    def test_eighth_runner_body_and_request_gate_before_loader(self):
        import ast
        import json
        from pathlib import Path
        from fastapi.testclient import TestClient
        tree = ast.parse((Path(__file__).resolve().parents[2] / "tools/tpex-price-api.py").read_text(encoding="utf-8"))
        names = {"scope_request_error", "install_scope6_guard", "database_snapshot"}
        namespace = {"json": json}
        exec(compile(ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[]), "runner-gate-memory-ast", "exec"), namespace)
        live = MemoryAPIFixture(live=True, cutoff=worker.EIGHTH_CUTOFF, policy_version=worker.EIGHTH_SCOPE_POLICY_VERSION)
        try:
            baseline = namespace["database_snapshot"](live)
            self.assertEqual(len(baseline), 19); self.assertEqual(live.finance_seed_rows, 0)
            self.assertFalse(live.store._attempted); self.assertIsNone(live.store.raw_capture); self.assertEqual(live.store._request_count, 0)
            self.assertTrue(all(not table["values"] for name, table in baseline.items() if name != "instruments"))
            self.assertEqual(baseline, namespace["database_snapshot"](live))
            print(json.dumps({"scope6_empty_store_memory_catalogue": True, "finance_seed_rows": 0, "table_count": 19, "schema_values_typeofs_preserved": True}))
        finally: live.close()
        del live, baseline
        fixture = MemoryAPIFixture(cutoff=worker.EIGHTH_CUTOFF, policy_version=worker.EIGHTH_SCOPE_POLICY_VERSION)
        namespace["install_scope6_guard"](fixture.app)
        checks = 0
        try:
            baseline = namespace["database_snapshot"](fixture)
            with TestClient(fixture.app) as client:
                query = "as_of=2026-10-07&min_lots=896.441&day_move=up&min_turnover=4984488555&min_range_pct=10.000"
                def verify(method, route, body, expected):
                    nonlocal checks
                    self.assertEqual(client.request(method, route, content=body).status_code, expected); checks += 1
                for method in ("GET", "POST"):
                    route = "/api/focus/price-lots" + ("/capture" if method == "POST" else "") + "?" + query
                    for suffix in ("&x=1", "&min_lots=896.441"):
                        verify(method, route + suffix, b"{}" if method == "POST" else b"", 422)
                    verify(method, route.replace("&min_range_pct=10.000", ""), b"{}" if method == "POST" else b"", 422)
                    verify(method, route.replace("896.441", "9223372036854775.808"), b"{}" if method == "POST" else b"", 422)
                    if method == "GET": verify(method, route, b"{}", 422)
                    else:
                        for body in (b"", b"null", b"[]", b'{"x":1}', b"\xff", b" " * 4097):
                            verify(method, route, body, 413 if len(body) > 4096 else 422)
                for path in ("/api/stocks/TPEx/6223/prices/save", "/api/stocks/TPEx/6223/institutional-windows/capture", "/api/stocks/TPEx/9999/prices/capture"):
                    verify("POST", path + "?as_of=2026-10-07", b"{}", 405)
                verify("POST", "/api/stocks/TPEx/6223/prices/capture?as_of=2026-10-06", b"{}", 422)
                for cutoff in ("2026-10-05", "2026-10-06"):
                    verify("GET", "/api/focus/price-lots?" + query.replace("2026-10-07", cutoff), b"", 200)
                self.assertEqual(fixture.fixture.opener.calls, [])
                verify("POST", "/api/focus/price-lots/capture?" + query, b"{}", 200)
                self.assertEqual(len(fixture.fixture.opener.calls), 1)
                for symbol in worker.policy_symbols(worker.EIGHTH_CUTOFF):
                    verify("POST", f"/api/stocks/TPEx/{symbol}/prices/capture?as_of=2026-10-07", b"{}", 200)
                self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(baseline, namespace["database_snapshot"](fixture))
            print(json.dumps({"scope6_runner_guard_checks": checks, "synthetic_loader_calls": 1, "tables": 19, "schema_values_typeofs_preserved": True}))
        finally: fixture.close()

    def test_eighth_runner_request_local_transport(self):
        import ast
        from pathlib import Path
        from threading import local, Thread
        tree = ast.parse((Path(__file__).resolve().parents[2] / "tools/tpex-price-api.py").read_text(encoding="utf-8"))
        context = local()
        namespace = {"NEW_PRICE_LIVE": True, "PRICE_CONTEXT": context, "LIVE_ACTIVE": True, "PRICE_ENDPOINT_URL": worker.ENDPOINT}
        functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"price_live_active", "price_transport_allowed"}], type_ignores=[])
        exec(compile(functions, "runner-memory-ast", "exec"), namespace)
        allowed = namespace["price_transport_allowed"]
        request = (worker.ENDPOINT, None, {}, "GET")
        self.assertFalse(allowed("urllib.Request", request)); context.active = True; context.request_count = 0; context.addresses = set()
        self.assertTrue(allowed("urllib.Request", request))
        for args in ((worker.ENDPOINT + "&other=1", None, {}, "GET"), (worker.ENDPOINT, b"payload", {}, "GET"), (worker.ENDPOINT, None, {}, "POST")):
            self.assertFalse(allowed("urllib.Request", args))
        self.assertFalse(allowed("socket.getaddrinfo", ("www.tpex.org.tw", 443)))
        context.request_count = 1; self.assertFalse(allowed("urllib.Request", request))
        self.assertTrue(allowed("socket.getaddrinfo", ("www.tpex.org.tw", 443)))
        self.assertFalse(allowed("socket.getaddrinfo", ("www.tpex.org.tw", 80)))
        context.addresses.add(("192.0.2.1", 443))
        self.assertTrue(allowed("socket.connect", (None, ("192.0.2.1", 443))))
        self.assertFalse(allowed("socket.connect", (None, ("192.0.2.2", 443))))
        background = []
        thread = Thread(target=lambda: background.append((namespace["price_live_active"](), allowed("socket.getaddrinfo", ("www.tpex.org.tw", 443)))))
        thread.start(); thread.join(); self.assertEqual(background, [(False, False)])
        context.active = False; self.assertFalse(allowed("socket.connect", (None, ("192.0.2.1", 443))))

    def test_eighth_new_day_router_read_only_and_explicit_cutoff(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture(cutoff=worker.EIGHTH_CUTOFF, policy_version=worker.EIGHTH_SCOPE_POLICY_VERSION)
        try:
            with TestClient(fixture.app) as client:
                for suffix in ("", "?as_of=2026-10-06", "?as_of=2026-10-07"):
                    self.assertIsNone(client.get("/api/stocks/TPEx/6223" + suffix).json()["overview"]["price_memory"]["latest"])
                self.assertEqual(fixture.fixture.opener.calls, [])
                first = client.post("/api/stocks/TPEx/6223/prices/capture?as_of=2026-10-07").json()
                self.assertEqual(first["version"], "stock-price-memory/m2-stock-scope-v6")
                for symbol in worker.policy_symbols(worker.EIGHTH_CUTOFF):
                    memory = client.get(f"/api/stocks/TPEx/{symbol}?as_of=2026-10-07").json()["overview"]["price_memory"]
                    self.assertEqual(memory["provenance"], first["provenance"]); self.assertEqual(memory["latest"]["id"], None)
                for suffix in ("", "?as_of=2026-10-06", "?as_of=2026-10-08"):
                    self.assertIsNone(client.get("/api/stocks/TPEx/6223" + suffix).json()["overview"]["price_memory"]["latest"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1); self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_seven_stock_router_cache_and_seventh_cutoff_preserve_catalogue(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture(cutoff=worker.NEW_CUTOFF, policy_version=worker.SEVENTH_SCOPE_POLICY_VERSION)
        try:
            with TestClient(fixture.app) as client:
                self.assertEqual(client.post("/api/stocks/TPEx/6510/prices/capture?as_of=2026-10-06").json()["status"], "available")
                symbols = ["3105", "3293", "5274", "5347", "6488", "6510", "8069"]
                for symbol in symbols:
                    memory = client.get(f"/api/stocks/TPEx/{symbol}?as_of=2026-10-06").json()["overview"]["price_memory"]
                    self.assertEqual(memory["version"], "stock-price-memory/m2-stock-scope-v5")
                    self.assertEqual(memory["provenance"]["selected_symbols"], symbols)
                    self.assertIsNone(memory["latest"]["id"])
                    self.assertEqual(client.post(f"/api/stocks/TPEx/{symbol}/prices/capture?as_of=2026-10-06").json()["capture_state"]["action"], "cached")
                    if symbol == "6510":
                        self.assertEqual(tuple(memory["latest"][key] for key in ("open", "high", "low", "close", "volume_exact", "turnover_exact")), (3125, 3140, 3050, 3055, "560518", "1729347985"))
                for suffix in ("", "?as_of=2026-10-02", "?as_of=2026-10-05"):
                    self.assertIsNone(client.get("/api/stocks/TPEx/6510" + suffix).json()["overview"]["price_memory"]["latest"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_six_stock_router_cache_and_sixth_cutoff_do_not_mutate_catalogue(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture(cutoff=worker.NEW_CUTOFF, policy_version=worker.SIXTH_SCOPE_POLICY_VERSION)
        try:
            with TestClient(fixture.app) as client:
                self.assertEqual(client.post("/api/stocks/TPEx/8069/prices/capture?as_of=2026-10-06").json()["status"], "available")
                for symbol in ("3105", "3293", "5274", "5347", "6488", "8069"):
                    detail = client.get(f"/api/stocks/TPEx/{symbol}?as_of=2026-10-06").json()
                    memory = detail["overview"]["price_memory"]
                    self.assertEqual(memory["version"], "stock-price-memory/m2-stock-scope-v4")
                    self.assertEqual(memory["provenance"]["selected_symbols"], ["3105", "3293", "5274", "5347", "6488", "8069"])
                    self.assertIsNone(memory["latest"]["id"])
                    self.assertEqual(client.post(f"/api/stocks/TPEx/{symbol}/prices/capture?as_of=2026-10-06").json()["capture_state"]["action"], "cached")
                    if symbol == "8069":
                        self.assertEqual(tuple(memory["latest"][key] for key in ("open", "high", "low", "close", "volume_exact", "turnover_exact")), (147, 151.5, 145, 149, "10796741", "1607943663"))
                for suffix in ("", "?as_of=2026-10-02", "?as_of=2026-10-05"):
                    self.assertIsNone(client.get("/api/stocks/TPEx/8069" + suffix).json()["overview"]["price_memory"]["latest"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_third_stock_actual_router_cache_and_catalogue_scope_are_read_only(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture(cutoff=worker.NEW_CUTOFF, policy_version=worker.SCOPE_POLICY_VERSION)
        try:
            with TestClient(fixture.app) as client:
                first = client.post("/api/stocks/TPEx/5347/prices/capture?as_of=2026-10-06").json()
                self.assertEqual((first["status"], first["latest"]["open"], first["latest"]["close"]), ("available", 184.5, 191))
                for symbol in ("3105", "5347", "6488"):
                    detail = client.get(f"/api/stocks/TPEx/{symbol}?as_of=2026-10-06").json()
                    self.assertEqual(detail["overview"]["price_memory"]["provenance"], first["provenance"])
                    self.assertEqual(client.post(f"/api/stocks/TPEx/{symbol}/prices/capture?as_of=2026-10-06").json()["capture_state"]["action"], "cached")
                for suffix in ("", "?as_of=2026-10-02", "?as_of=2026-10-05"):
                    self.assertIsNone(client.get("/api/stocks/TPEx/5347" + suffix).json()["overview"]["price_memory"]["latest"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_new_date_m1_exact_values_and_legacy_default_do_not_leak(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture(cutoff=worker.NEW_CUTOFF)
        try:
            with TestClient(fixture.app) as client:
                result = client.post("/api/stocks/TPEx/3105/prices/capture?as_of=2026-10-06").json()
                self.assertEqual((result["status"], result["latest"]["close"]), ("available", 592))
                for symbol, prices in (("3105", (615, 623, 588, 592, "19731700", "11863581093")), ("6488", (1175, 1260, 1145, 1205, "13913614", "16835605385"))):
                    overview = client.get(f"/api/stocks/TPEx/{symbol}?as_of=2026-10-06").json()["overview"]
                    bar = overview["price_memory"]["latest"]
                    self.assertEqual(tuple(bar[key] for key in ("open", "high", "low", "close", "volume_exact", "turnover_exact")), prices)
                    self.assertEqual((overview["as_of"], bar["data_as_of"]), ("2026-10-06", "2026-10-06"))
                default = client.get("/api/stocks/TPEx/3105").json()["overview"]
                self.assertEqual(default["as_of"], "2026-10-02")
                self.assertIsNone(default["price_memory"]["latest"])
                self.assertIsNone(client.get("/api/stocks/TPEx/3105?as_of=2026-10-05").json()["overview"]["price_memory"]["latest"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

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
