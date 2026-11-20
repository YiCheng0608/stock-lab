"""tools/research/restore_instruments.py: undo an old-date collect's rewrite (#838)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import worker.instrument_repair as instrument_repair
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import DataQuality, Instrument
from worker.sources import InstrumentRecord

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    path = ROOT / "tools" / "research" / "restore_instruments.py"
    spec = importlib.util.spec_from_file_location("restore_instruments", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["restore_instruments"] = module
    spec.loader.exec_module(module)
    return module


tool = _tool()

# (exchange, symbol): (stored type, stored status, latest instrument_status row)
SEEDED = {
    # a delisted ipo the rewrite made active; the lists' newlisting row is
    # not recent against the capture day, so the fixed rule does not list it
    ("TWSE", "8427"): ("ipo", "active", "delisted"),
    ("TWSE", "6505"): ("ipo", "active", None),  # listed 2003: stock
    ("TWSE", "1339"): ("stock", "active", None),  # listed 50 days ago: ipo
    ("TWSE", "1589"): ("stock", "dormant", "dormant"),  # recent: ipo
    ("TPEx", "8047"): ("ipo", "active", "transferred"),
    ("TWSE", "0050"): ("etf", "active", None),  # not stock/ipo: kept
    ("TWSE", "2330"): ("stock", "active", None),  # already right
    ("TWSE", "4144"): ("stock", "delisted", "delisted"),  # not listed: kept
}
LISTS = [
    InstrumentRecord("6505", "台塑化", exchange="TWSE", instrument_type="stock"),
    InstrumentRecord("1339", "昭輝", exchange="TWSE", instrument_type="ipo"),
    InstrumentRecord("1589", "永冠-KY", exchange="TWSE", instrument_type="ipo"),
    InstrumentRecord("8047", "星雲", exchange="TPEx", instrument_type="stock"),
    InstrumentRecord("0050", "元大台灣50", exchange="TWSE", instrument_type="stock"),
    InstrumentRecord("2330", "台積電", exchange="TWSE", instrument_type="stock"),
]


@pytest.fixture
def research_db(tmp_path, monkeypatch):
    db = tmp_path / "stock.db"
    engine = create_engine(f"sqlite:///{db}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    with Session(engine) as session:
        for (exchange, symbol), (kind, status, observed) in SEEDED.items():
            session.add(
                Instrument(
                    market="TW",
                    exchange=exchange,
                    symbol=symbol,
                    name=symbol,
                    instrument_type=kind,
                    status=status,
                )
            )
            if observed:
                key = f"{exchange}:{symbol}"
                # an older row first: only the latest one counts
                for day, value in (
                    (date(2025, 1, 2), "active"),
                    (date(2026, 10, 23), observed),
                ):
                    session.add(
                        DataQuality(
                            entity_type="instrument_status",
                            entity_key=key,
                            as_of_date=day,
                            status=value,
                            missing_fields_json=[],
                            checks_json={},
                            source="test",
                        )
                    )
        session.commit()
    engine.dispose()
    (tmp_path / tool.MARKER_NAME).write_text(
        json.dumps({"purpose": "research_history"}), encoding="utf-8"
    )
    evidence = {
        "TWSE": {
            "observed_date": date(2026, 11, 16),
            "captures": [{"raw_payload_id": 7}],
        }
    }
    monkeypatch.setattr(
        instrument_repair, "_latest_lists", lambda session: (LISTS, evidence, {})
    )
    monkeypatch.setattr(sources, "taipei_today", lambda: date(2026, 11, 17))
    return db


def _state(db: Path) -> dict[tuple[str, str], tuple[str, str]]:
    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as session:
        state = {
            (item.exchange, item.symbol): (item.instrument_type, item.status)
            for item in session.scalars(select(Instrument))
        }
    engine.dispose()
    return state


RESTORED = {
    ("TWSE", "8427"): ("ipo", "delisted"),
    ("TWSE", "6505"): ("stock", "active"),
    ("TWSE", "1339"): ("ipo", "active"),
    ("TWSE", "1589"): ("ipo", "dormant"),
    ("TPEx", "8047"): ("stock", "transferred"),
    ("TWSE", "0050"): ("etf", "active"),
    ("TWSE", "2330"): ("stock", "active"),
    ("TWSE", "4144"): ("stock", "delisted"),
}


def test_dry_run_plans_the_restore_and_writes_nothing(research_db):
    before = _state(research_db)

    code, summary = tool.run(research_db, apply=False, expect=None)

    assert code == 0 and summary["status"] == "planned"
    assert {item["code"] for item in summary["changes"]} == {
        "TWSE:8427",
        "TWSE:6505",
        "TWSE:1339",
        "TWSE:1589",
        "TPEx:8047",
    }
    assert summary["lists"] == {
        "TWSE": {"observed_date": "2026-11-16", "age_days": 1, "raw_payload_ids": [7]}
    }
    assert summary["warnings"] == []
    assert _state(research_db) == before


def test_apply_restores_and_a_second_run_changes_nothing(research_db):
    code, summary = tool.run(research_db, apply=True, expect=5)

    assert code == 0 and summary["status"] == "applied" and summary["count"] == 5
    assert _state(research_db) == RESTORED

    code, again = tool.run(research_db, apply=True, expect=None)
    assert code == 0 and again["count"] == 0 and again["changes"] == []
    assert _state(research_db) == RESTORED


def test_an_unexpected_count_writes_nothing(research_db):
    before = _state(research_db)

    code, summary = tool.run(research_db, apply=True, expect=32)

    assert code == 1
    assert summary["status"] == "unexpected" and summary["count"] == 5
    assert _state(research_db) == before


def test_a_database_without_the_research_marker_is_refused(research_db):
    (research_db.parent / tool.MARKER_NAME).unlink()
    before = _state(research_db)

    code, summary = tool.run(research_db, apply=True, expect=None)

    assert code == 2 and "not a research database" in summary["refused"]
    assert _state(research_db) == before


def test_reference_shows_its_values_and_what_still_differs(research_db, tmp_path):
    reference = tmp_path / "prod" / "stock.db"
    reference.parent.mkdir()
    engine = create_engine(f"sqlite:///{reference}")
    upgrade_database(engine)
    with Session(engine) as session:
        for (exchange, symbol), (kind, status) in RESTORED.items():
            if symbol == "6505":
                kind = "ipo"  # the reference disagrees with the rule here
            session.add(
                Instrument(
                    market="TW",
                    exchange=exchange,
                    symbol=symbol,
                    name=symbol,
                    instrument_type=kind,
                    status=status,
                )
            )
        session.commit()
    engine.dispose()

    code, summary = tool.run(research_db, apply=False, expect=None, reference=reference)

    assert code == 0
    by_code = {item["code"]: item["reference"] for item in summary["changes"]}
    assert by_code["TWSE:8427"] == ["ipo", "delisted"]
    assert by_code["TWSE:6505"] == ["ipo", "active"]
    assert summary["reference_common"] == len(RESTORED)
    assert summary["differs_from_reference_after"] == ["TWSE:6505"]


def test_lists_older_than_a_day_are_warned_about(research_db, monkeypatch):
    monkeypatch.setattr(sources, "taipei_today", lambda: date(2026, 11, 19))

    code, summary = tool.run(research_db, apply=False, expect=None)

    assert code == 0
    assert summary["lists"]["TWSE"]["age_days"] == 3
    assert summary["warnings"] == [
        "TWSE lists were captured 2026-11-16, 3 days ago: "
        "compare the ipo/stock types with --reference"
    ]


def test_unreadable_lists_or_reference_exit_3_and_write_nothing(
    research_db, monkeypatch, tmp_path
):
    before = _state(research_db)

    code, summary = tool.run(
        research_db, apply=True, expect=None, reference=tmp_path / "none" / "x.db"
    )
    assert code == tool.ERROR_EXIT and summary["status"] == "error"
    assert summary["error"].startswith("OperationalError")

    def broken(session):
        raise instrument_repair.InstrumentRepairError(["no stored capture of X"])

    monkeypatch.setattr(instrument_repair, "_latest_lists", broken)
    code, summary = tool.run(research_db, apply=True, expect=None)
    assert code == tool.ERROR_EXIT
    assert summary["error"] == "InstrumentRepairError: no stored capture of X"
    assert _state(research_db) == before
