"""Memory-only checks: -B, --noconftest, -p no:cacheprovider -p no:logging -s.

The optional live checks read STOCK_TEST_TPEX_CAPTURE_ZIP without modifying it.
memory_api() exposes the actual router backed solely by SQLite :memory: for
reviewers; it does not run app.main's database readiness/lifespan. Configuration
mkdir calls are intercepted only for the already-existing repository directory.
This does not replace the consumer's previously accepted filesystem contract.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

import pytest

from app import institutional_daily as daily
from worker import tpex_institutional_capture as consumer

DAY = date(2026, 10, 2)
REPO = Path(__file__).resolve().parents[2]
LIVE_ENV = "STOCK_TEST_TPEX_CAPTURE_ZIP"


def install_zero_disk_guard() -> None:
    """Reject disk mutations/DBs and external network; allow Windows asyncio IPC."""
    def audit(event, args):
        if event == "open":
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                raise AssertionError("unexpected_disk_write:" + str(args[0]))
        if event == "socket.connect":
            caller = sys._getframe(1)
            # Windows' stdlib socketpair uses loopback for asyncio's wake-up
            # pipe. This exception cannot admit HTTP/source-provider requests.
            if (caller.f_code.co_name == "_fallback_socketpair"
                    and Path(caller.f_code.co_filename) == Path(__import__("socket").__file__)
                    and isinstance(args[1], tuple) and args[1][0] in {"127.0.0.1", "::1"}):
                return
            raise AssertionError("unexpected_external_connection")
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "tempfile.mkstemp", "tempfile.mkdtemp", "subprocess.Popen"}:
            raise AssertionError("unexpected_mutation_or_network:" + event)
        if event == "sqlite3.connect" and args[0] != ":memory:":
            raise AssertionError("unexpected_disk_database")
    sys.addaudithook(audit)


def configuration(path: str | None = None, day="2026-10-02") -> dict:
    return {daily.CAPTURE_ENV: path or str(REPO / "never-read.zip"), daily.DATE_ENV: day}


@contextmanager
def memory_api(capture_zip: str | None = None):
    """Real API/router and model schema; no persisted DB, fixture files or startup."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    def existing_directory_only(target, *args, **kwargs):
        assert target == REPO and target.is_dir(), "unexpected config mkdir"

    environment = {"STOCK_DATA_DIR": str(REPO), "STOCK_RAW_DIR": str(REPO), "STOCK_DB_PATH": ":memory:",
                   daily.CAPTURE_ENV: capture_zip or "", daily.DATE_ENV: "2026-10-02" if capture_zip else "",
                   "STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE": ""}
    with patch.dict(os.environ, environment), patch.object(Path, "mkdir", existing_directory_only):
        from app.api import get_db, router
        from app.db import Base, enable_sqlite_foreign_keys
        from app.models import Instrument

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        enable_sqlite_foreign_keys(engine)
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        with sessions() as db:
            db.add_all([Instrument(exchange=exchange, symbol=symbol, name=name)
                        for exchange, symbol, name in [("TPEx", "3105", "穩懋"), ("TPEx", "6488", "環球晶"),
                                                      ("TWSE", "3105", "相同代號測試")]])
            db.commit()
        def memory_db():
            with sessions() as db:
                yield db
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = memory_db
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
            engine.dispose()


def test_unconfigured_and_early_gates_do_not_read_files(monkeypatch):
    monkeypatch.setattr(Path, "open", lambda *_a, **_k: pytest.fail("evidence must not be read"))
    for exchange, cutoff, config, reason in [
        ("TPEx", DAY, {}, "daily_capture_not_configured"),
        ("TWSE", DAY, configuration(), "daily_exchange_not_supported"),
        ("TPEx", None, configuration(), "daily_shared_cutoff_missing"),
        ("TPEx", date(2026, 10, 1), configuration(), "daily_after_cutoff"),
        ("TPEx", DAY, configuration("relative.zip"), "daily_invalid_configuration"),
        ("TPEx", DAY, {daily.CAPTURE_ENV: str(REPO / "missing.zip")}, "daily_invalid_configuration"),
        ("TPEx", DAY, configuration(day="2026-02-30"), "daily_invalid_configuration"),
    ]:
        result = daily.build_institutional_daily(exchange, "3105", cutoff, environment=config)
        assert result["status"] == "unavailable" and result["reasons"] == [reason]
        assert result["row"] is result["date"] is result["provenance"] is None


def test_bad_local_path_does_not_leak_or_raise(monkeypatch):
    monkeypatch.setattr(daily, "summarize_capture", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("secret server path")))
    result = daily.build_institutional_daily("TPEx", "3105", DAY, environment=configuration())
    assert result["reasons"] == ["daily_evidence_invalid"] and "secret" not in json.dumps(result)


@pytest.fixture
def live_capture():
    path = os.environ.get(LIVE_ENV)
    if not path:
        pytest.skip("explicit read-only live capture path not supplied")
    assert Path(path).is_absolute()
    return path


def test_real_capture_exact_selected_values_and_cutoff(live_capture):
    result = daily.build_institutional_daily("TPEx", "3105", DAY, environment=configuration(live_capture))
    assert result["status"] == "available" and result["date"] == result["as_of"] == "2026-10-02"
    row = result["row"]
    assert row["row_ordinal"] == 175 and row["source_date"] == "1151002"
    assert [(values["buy"], values["sell"], values["net"]) for values in row["investors"].values()] == [
        ("10547941", "3264551", "7283390"), ("0", "27000", "-27000"), ("1070812", "86707", "984105")]
    assert row["total_net"] == "8240495"
    assert result["provenance"]["body_sha256"] == "2d058996bf67a375e152f381dda1a8610c32cf3ecd1ed31240c89ac7fd020402"
    assert result["provenance"]["receipt_sha256"] == "2a3bf3deb5ee892da4ca24e7770c7a1a9633ce45322a6c53504e9abe71a4efea"
    assert result["provenance"]["registry_version"] == daily.REGISTRY_VERSION
    assert result["provenance"]["manifest_digest"] == daily.REGISTRY_DIGEST
    assert result["session_windows"]["status"] == "unavailable" and result["historical_pit"] == "unsupported"
    assert daily.build_institutional_daily("TPEx", "3105", date(2026, 10, 3), environment=configuration(live_capture))["reasons"] == ["daily_configured_date_before_cutoff"]


def repack(body, receipt):
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("body.bin", body)
        archive.writestr("receipt.json", json.dumps(receipt, ensure_ascii=False).encode())
    return memory.getvalue()


def test_actual_receipt_and_selected_quantity_mutations_are_rejected_in_memory(live_capture, monkeypatch):
    with zipfile.ZipFile(live_capture) as archive:
        body = archive.read("body.bin")
        receipt = json.loads(archive.read("receipt.json"))
    changed = repack(body, {**receipt, "body_sha256": "0" * 64})
    monkeypatch.setattr(consumer, "_stable_zip_read", lambda _path: changed)
    result = daily.build_institutional_daily("TPEx", "3105", DAY, environment=configuration(live_capture))
    assert result["status"] == "unavailable" and result["reasons"] == ["receipt_mismatch:body_sha256"]
    rows = json.loads(body)
    rows[174][consumer.FIELDS["foreign"][2]] = "7283391"
    changed_body = json.dumps(rows, ensure_ascii=False).encode()
    import hashlib
    changed = repack(changed_body, {**receipt, "body_sha256": hashlib.sha256(changed_body).hexdigest(), "body_bytes": len(changed_body)})
    result = daily.build_institutional_daily("TPEx", "3105", DAY, environment=configuration(live_capture))
    assert result["status"] == "unavailable" and result["reasons"] == ["selected_net_mismatch:foreign"]
    assert result["row"] is None


def test_quantity_encoding_preserves_int64_in_memory(monkeypatch, live_capture):
    summary = consumer.summarize_capture(live_capture, manifest=consumer.REGISTRY_PATH, profile=daily.PROFILE,
        expected_registry_version=daily.REGISTRY_VERSION, expected_digest=daily.REGISTRY_DIGEST, expected_date=DAY, symbols=["3105"])
    # This check exercises only JSON projection, not the consumer's source gate.
    summary["rows"][0]["investors"]["foreign"]["buy"] = 9223372036854775807
    summary["rows"][0]["investors"]["foreign"]["net"] = -9223372036854775807
    monkeypatch.setattr(daily, "summarize_capture", lambda *_a, **_k: summary)
    row = daily.build_institutional_daily("TPEx", "3105", DAY, environment=configuration(live_capture))["row"]
    restored = json.loads(json.dumps(row))
    assert restored["investors"]["foreign"]["buy"] == "9223372036854775807"
    assert restored["investors"]["foreign"]["net"] == "-9223372036854775807"


def test_api_defaults_are_unavailable_without_legacy_fallback():
    with memory_api() as client:
        response = client.get("/api/stocks/TPEx/3105/overview?as_of=2026-10-02")
        assert response.status_code == 200
        result = response.json()
        assert result["institutional_daily"]["reasons"] == ["daily_capture_not_configured"]
        assert result["institutional"]["values"] is None
        assert result["institutional"]["reasons"] == ["window_capture_not_enabled"]
        assert result["institutional"]["windows"] == {} and result["institutional"]["capture_state"]["request_count"] == 0


def test_real_capture_through_actual_api_router(live_capture):
    with memory_api(live_capture) as client:
        for symbol, ordinal, nets, total in [("3105", 175, ["7283390", "-27000", "984105"], "8240495"),
                                             ("6488", 648, ["-862867", "105839", "226556"], "-530472")]:
            response = client.get(f"/api/stocks/TPEx/{symbol}/overview?as_of=2026-10-02")
            assert response.status_code == 200
            result = response.json()
            row = result["institutional_daily"]["row"]
            assert row["row_ordinal"] == ordinal and row["total_net"] == total
            assert [row["investors"][key]["net"] for key in ("foreign", "trust", "dealer")] == nets
            assert result["institutional"]["status"] == "unavailable" and result["institutional"]["values"] is None
            assert result["institutional"]["reasons"] == ["window_capture_not_enabled"]
            assert result["institutional"]["windows"] == {} and result["institutional"]["capture_state"]["request_count"] == 0
            detail = client.get(f"/api/stocks/TPEx/{symbol}?as_of=2026-10-02")
            assert detail.status_code == 200
            assert detail.json()["overview"]["institutional_daily"] == result["institutional_daily"]
            assert detail.json()["news_cutoff"]["as_of"] == result["as_of"]
            print(json.dumps({"api_symbol": symbol, "overview_version": result["version"], "row": row,
                              "provenance": result["institutional_daily"]["provenance"],
                              "windows": result["institutional"]}, ensure_ascii=True))
        assert client.get("/api/stocks/TPEx/3105/overview?as_of=2026-10-01").json()["institutional_daily"]["reasons"] == ["daily_after_cutoff"]
        assert client.get("/api/stocks/TWSE/3105/overview?as_of=2026-10-02").json()["institutional_daily"]["reasons"] == ["daily_exchange_not_supported"]
        assert client.get("/api/stocks/TPEx/3105/overview").json()["institutional_daily"]["reasons"] == ["daily_shared_cutoff_missing"]
