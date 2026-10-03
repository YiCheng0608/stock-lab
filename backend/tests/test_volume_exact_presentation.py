"""Synthetic 2026-10-01 volume fixtures through the real router, entirely in memory.

Run this file directly with -B, without pytest/conftest or app.main. --serve starts
an owned loopback API for full-page review. Only _capture_evidence is replaced:
the production filesystem evidence gate is not tested or admitted by this file.
"""
from __future__ import annotations

import argparse
import ast
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

STANDALONE = __name__ == "__main__"
DAY = date(2026, 10, 1)
CASES = {"ZERO0": 0, "ONE1": 1, "N999": 999, "LOT1": 1000, "LOT01": 1001,
         "SAFE": 9007199254740991, "ODD": 9007199254740993, "MAX": 9223372036854775807}
EXPECTED_DENIALS = []
UNEXPECTED_DENIALS = []
_expected_probe = False
_listen_port = None


def _socketpair_context() -> bool:
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
    # The real config creates directories on import. Direct execution uses its
    # actual constants, excluding mkdir calls and replacing only runtime paths.
    # Ordinary suite imports retain the existing conftest/config contract and
    # do not install a process-wide audit hook or replace app.config.
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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import api
from app.db import Base
from app.models import IngestionRun, Instrument, MarketBar, RawPayload
from app.units import volume_exact_text
from worker.sources import parse_tpex_daily_rows, parse_twse_daily_rows
from worker.stock_day_capture import _rows


class MemoryFixture:
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.app = FastAPI()
        api.configure_cors(self.app)
        self.app.include_router(api.router)
        self.rows = []
        for symbol, volume in CASES.items():
            self.rows.append({"Date": "1151001", "Code": symbol, "Name": "synthetic-volume-" + symbol,
                              "OpeningPrice": "10", "HighestPrice": "11", "LowestPrice": "9",
                              "ClosingPrice": "10.5", "TradeVolume": str(volume), "TradeValue": "1000"})
        body = json.dumps(self.rows, ensure_ascii=False).encode("utf-8")
        self.digest = hashlib.sha256(body).hexdigest()
        self.selected_rows, selected_day = _rows(body)
        assert selected_day == DAY
        twse = parse_twse_daily_rows(json.loads(body, parse_float=Decimal), payload_sha256=self.digest)
        tpex_rows = [{"Date": "1151001", "SecuritiesCompanyCode": symbol, "Open": "10", "High": "11",
                      "Low": "9", "Close": "10.5", "TradingShares": str(volume), "TransactionAmount": "1000"}
                     for symbol, volume in CASES.items()]
        tpex_body = json.dumps(tpex_rows).encode("utf-8")
        tpex = parse_tpex_daily_rows(json.loads(tpex_body, parse_float=Decimal), payload_sha256=hashlib.sha256(tpex_body).hexdigest())
        assert len(twse) == len(tpex) == len(CASES)
        with Session(self.engine) as db:
            run = IngestionRun(run_type="collect", source="synthetic-memory", run_date=DAY,
                               status="success", data_as_of=DAY.isoformat())
            db.add(run)
            db.flush()
            raw = RawPayload(ingestion_run_id=run.id, source="twse", endpoint="synthetic-memory",
                             payload_path=None, sha256=self.digest, data_as_of=DAY.isoformat(),
                             collected_at=datetime(2026, 10, 1, 8))
            db.add(raw)
            db.flush()
            self.raw_id, self.run_id = raw.id, run.id
            for record in twse + tpex:
                assert type(record.volume) is int and record.volume == CASES[record.symbol]
                instrument = Instrument(market="TW", exchange=record.exchange, symbol=record.symbol,
                                        name="記憶體合成成交量測試 " + record.symbol,
                                        instrument_type="stock", status="active")
                db.add(instrument)
                db.flush()
                db.add(MarketBar(instrument_id=instrument.id, trading_date=record.trading_date,
                                 open=record.open, high=record.high, low=record.low, close=record.close,
                                 adj_close=record.close, volume=record.volume, turnover=record.turnover,
                                 turnover_status=record.turnover_status, turnover_reason=record.turnover_reason,
                                 source=record.source, data_as_of=datetime(2026, 10, 1),
                                 collected_at=datetime(2026, 10, 1, 8),
                                 raw_payload_id=raw.id if record.exchange == "TWSE" else None,
                                 is_suspended=False))
            db.commit()

        def database():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[api.get_db] = database
        self.evidence_patch = patch("app.stock_overview._capture_evidence", side_effect=self.evidence)
        self.evidence_patch.start()

        @self.app.middleware("http")
        async def preview_read_only(request, call_next):
            # Review exercises the real GET router; capture/write endpoints are
            # outside the synthetic preview's scope and never dispatch.
            if request.method not in {"GET", "OPTIONS"}:
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "synthetic preview is read-only"}, status_code=405)
            return await call_next(request)

    def evidence(self, raw, _run, _manifest):
        return {"rows": self.selected_rows, "date": DAY, "provenance": {
            "raw_payload_id": raw.id, "ingestion_run_id": self.run_id, "source_id": "synthetic-memory",
            "source_version": "synthetic-memory", "endpoint": "http://127.0.0.1/synthetic-memory",
            "body_sha256": self.digest, "receipt_sha256": "0" * 64,
            "registry_version": "synthetic-memory", "manifest_digest": "synthetic-memory",
            "captured_at": "2026-10-01T08:00:00+00:00", "raw_collected_at": "2026-10-01T08:00:00",
            "verification": "synthetic_memory_only", "license": {}, "summarize_decision": {}}}

    def close(self):
        self.evidence_patch.stop()
        self.app.dependency_overrides.clear()
        self.engine.dispose()


class VolumeExactTest(unittest.TestCase):
    def test_strict_canonical_helper_and_unchanged_legacy_volume(self):
        for value in CASES.values():
            with self.subTest(value=value):
                self.assertEqual(volume_exact_text(value), str(value))
                bar = MarketBar(trading_date=DAY, volume=value)
                payload = api.bar_dict(bar)
                self.assertEqual(payload["volume"], value)
                self.assertEqual(payload["volume_exact"], str(value))
        for value in (None, True, False, 0.0, 1000.0, -1, 1.5, "0", "01", Decimal("1"), 9223372036854775808):
            with self.subTest(invalid=value):
                self.assertIsNone(volume_exact_text(value))
                payload = api.bar_dict(MarketBar(trading_date=DAY, volume=value))
                self.assertEqual(payload["volume"], value)
                self.assertIsNone(payload["volume_exact"])

    def test_two_market_parsers_memory_sqlite_real_http_router(self):
        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        with TestClient(fixture.app) as client:
            for exchange in ("TWSE", "TPEx"):
                for symbol, expected in CASES.items():
                    with self.subTest(exchange=exchange, symbol=symbol):
                        stock = client.get(f"/api/stocks/{exchange}/{symbol}?as_of={DAY}")
                        instrument = client.get(f"/api/instruments/{symbol}?exchange={exchange}&as_of={DAY}")
                        overview = client.get(f"/api/stocks/{exchange}/{symbol}/overview?as_of={DAY}")
                        self.assertEqual(stock.status_code, 200, stock.text)
                        self.assertEqual(instrument.status_code, 200, instrument.text)
                        self.assertEqual(overview.status_code, 200, overview.text)
                        for response in (stock, instrument):
                            self.assertIn(f'"volume_exact":"{expected}"'.encode(), response.content)
                            self.assertIn(f'"volume":{expected}'.encode(), response.content)
                            bar = response.json()["bars"][0]
                            self.assertEqual(bar["volume"], expected)
                            self.assertEqual(bar["volume_exact"], str(expected))
                        price = stock.json()["overview"]["price"]
                        self.assertEqual(overview.json()["price"], price)
                        if exchange == "TWSE":
                            self.assertEqual(price["latest"]["volume_exact"], str(expected))
                            self.assertEqual(price["bars"][0]["volume_exact"], str(expected))
                        else:
                            self.assertIsNone(price["latest"])
                            self.assertEqual(price["bars"], [])
                            self.assertIn("price_source_not_admitted", price["reasons"])

    @unittest.skipUnless(STANDALONE, "audit probes are restricted to the guarded direct runner")
    def test_audit_rejects_writes_network_and_subprocess(self):
        global _expected_probe
        import socket
        import subprocess
        _expected_probe = True
        try:
            for action in (lambda: os.mkdir("__volume_exact_forbidden__"),
                           lambda: open("__volume_exact_forbidden__", "w"),
                           lambda: socket.getaddrinfo("example.com", 443),
                           lambda: subprocess.run([sys.executable, "--version"]),
                           lambda: sys.audit("socket.sendto", None, ("192.0.2.1", 53)),
                           lambda: sys.audit("socket.gethostbyname", "example.com")):
                with self.assertRaises(PermissionError):
                    action()
        finally:
            _expected_probe = False


def main():
    global _listen_port
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.serve:
        _listen_port = args.port
        fixture = MemoryFixture()
        try:
            import uvicorn
            print(json.dumps({"mode": "synthetic-memory-actual-router", "date": str(DAY), "cases": CASES,
                              "url": f"http://127.0.0.1:{args.port}", "disk_evidence_gate": "not_tested"}), flush=True)
            uvicorn.run(fixture.app, host="127.0.0.1", port=args.port, lifespan="off", access_log=False)
        finally:
            fixture.close()
    else:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(VolumeExactTest))
        success = result.wasSuccessful() and not UNEXPECTED_DENIALS
        print(json.dumps({"tests": result.testsRun, "success": success,
                          "fixture_date": str(DAY), "disk_artifacts": 0, "expected_denials": EXPECTED_DENIALS,
                          "unexpected_denials": UNEXPECTED_DENIALS,
                          "disk_evidence_gate": "not_tested"}), flush=True)
        return 0 if success else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
