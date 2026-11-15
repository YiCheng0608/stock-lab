"""tools/audit/raw_files.py: the raw captures the database cites whose file is damaged (#772)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.migrations import upgrade_database
from app.models import Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "audit"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import raw_files  # noqa: E402


def _database(tmp_path: Path) -> Path:
    db = tmp_path / "stock.db"
    engine = create_engine(f"sqlite:///{db}")
    upgrade_database(engine)
    engine.dispose()
    return db


def _raw(
    con: sqlite3.Connection, raw_id: int, path: Path, content: bytes | None, sha=None
):
    if content is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    con.execute(
        "INSERT INTO raw_payloads (id, source, endpoint, payload_path, sha256, collected_at) "
        "VALUES (?, 'twse', ?, ?, ?, '2023-11-22 09:30:00')",
        (
            raw_id,
            f"endpoint-{raw_id}",
            str(path),
            sha or hashlib.sha256(b"whole").hexdigest(),
        ),
    )


def test_the_scan_lists_missing_empty_and_mismatched_files_with_their_citations(
    tmp_path,
):
    db = _database(tmp_path)
    raw = tmp_path / "raw"
    con = sqlite3.connect(db)
    _raw(con, 1, raw / "whole.json", b"whole")
    _raw(con, 2, raw / "empty.json", b"")
    _raw(con, 3, raw / "missing.json", None)
    _raw(con, 4, raw / "other.json", b"other bytes")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as session:
        session.add(Instrument(id=1, symbol="2330", name="台積電"))
        for day, raw_id in ((21, 1), (22, 2), (23, 2)):
            session.add(
                MarketBar(
                    instrument_id=1,
                    trading_date=date(2023, 11, day),
                    close=1.0,
                    adj_close=1.0,
                    raw_payload_id=raw_id,
                )
            )
        session.commit()
    engine.dispose()

    full = raw_files.scan(db, None, quick=False)
    assert (full["raw_payloads"], full["damaged"]) == (4, 3)
    assert full["by_state"] == {"empty": 1, "missing": 1, "sha_mismatch": 1}
    by_id = {item["raw_id"]: item for item in full["files"]}
    assert by_id[2]["state"] == "empty"
    assert by_id[2]["referenced_by"] == {"market_bars.raw_payload_id": 2}
    assert by_id[2]["endpoint"] == "endpoint-2"
    assert by_id[2]["collected_at"] == "2023-11-22 09:30:00"
    assert by_id[3]["referenced_by"] == {}
    assert full["referenced_damaged"] == 1

    quick = raw_files.scan(db, None, quick=True)
    assert quick["by_state"] == {"empty": 1, "missing": 1}


def test_every_foreign_key_to_raw_payloads_is_counted(tmp_path):
    con = sqlite3.connect(_database(tmp_path))
    columns = raw_files.referencing_columns(con)
    con.close()
    assert ("market_bars", "raw_payload_id") in columns
    assert ("chip_snapshots", "raw_payload_id") in columns
    # One per ForeignKey("raw_payloads.id") in app.models.
    models = (ROOT / "backend" / "app" / "models.py").read_text(encoding="utf-8")
    assert len(columns) == models.count('ForeignKey("raw_payloads.id")')


def test_the_scan_only_reads(tmp_path, capsys, monkeypatch):
    db = _database(tmp_path)
    con = sqlite3.connect(db)
    _raw(con, 1, tmp_path / "raw" / "empty.json", b"")
    con.commit()
    con.close()
    before = db.read_bytes()
    monkeypatch.setattr(
        raw_files, "datetime", _At(datetime(2026, 11, 15, 4, 0, tzinfo=timezone.utc))
    )
    assert raw_files.main(["--db", str(db)]) == 1
    assert json.loads(capsys.readouterr().out)["damaged"] == 1
    assert db.read_bytes() == before


def test_the_scan_refuses_the_daily_window(tmp_path, capsys, monkeypatch):
    db = _database(tmp_path)
    # 22:00 in Taipei.
    monkeypatch.setattr(
        raw_files, "datetime", _At(datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc))
    )
    assert raw_files.main(["--db", str(db)]) == 2
    assert "refused" in json.loads(capsys.readouterr().out)


class _At:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self, tz=None):
        return self.at
