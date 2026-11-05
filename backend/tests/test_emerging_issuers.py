"""TPEx emerging-market roster: parser, collect and storage (Issue #512).

``tpex_emerging_20261105.json`` is three rows of the 2026-11-05
``mopsfin_t187ap03_R`` response (7808 訊聯智藥, 7924 TLC-KY, 8058 耐特) with the
fields the parser reads plus a few for shape; the rest of each row is dropped.
"""

from __future__ import annotations

import copy
import json
import socket
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import EmergingIssuer, IngestionRun, Instrument, RawPayload
from test_sources import FixtureFetcher
from worker.emerging_issuers import store_emerging_issuers

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "emerging_issuers"
    / "tpex_emerging_20261105.json"
)
NOV05 = date(2026, 11, 5)
DAY = date(2026, 9, 4)  # FixtureFetcher's session


def _roster() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in emerging roster tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'emerging.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


# ---- parser ----


def test_the_1105_roster_reads_code_name_and_data_date():
    records = sources.parse_tpex_emerging_issuers(
        _roster(), requested_date=NOV05, payload_sha256="abc"
    )
    assert [(r.symbol, r.name, r.as_of_date, r.payload_sha256) for r in records] == [
        ("7808", "訊聯智藥", NOV05, "abc"),
        ("7924", "TLC-KY", NOV05, "abc"),
        ("8058", "耐特", NOV05, "abc"),
    ]


def test_an_older_roster_keeps_its_own_date():
    # The roster is the current list; a collect day after its Date reads it as of that Date.
    (record, *_) = sources.parse_tpex_emerging_issuers(
        _roster(), requested_date=date(2026, 11, 9)
    )
    assert record.as_of_date == NOV05


def _with(index, **changes):
    rows = copy.deepcopy(_roster())
    rows[index].update(changes)
    return rows


@pytest.mark.parametrize(
    "payload,message",
    [
        pytest.param([], "non-empty list", id="empty"),
        pytest.param({"data": _roster()}, "non-empty list", id="not-a-list"),
        pytest.param(_with(1, Date="1151104"), "share one Date", id="two-dates"),
        pytest.param(_with(0, Date=""), "share one Date", id="no-date"),
        pytest.param(
            _with(2, SecuritiesCompanyCode="7808"), "7808 twice", id="duplicate-code"
        ),
        pytest.param(
            [
                {
                    "Date": "1151105",
                    "SecuritiesCompanyCode": "",
                    "CompanyAbbreviation": "",
                }
            ],
            "no readable company",
            id="no-readable-row",
        ),
    ],
)
def test_a_roster_that_cannot_be_read_as_one_list_is_rejected(payload, message):
    with pytest.raises(sources.OfficialDataError, match=message):
        sources.parse_tpex_emerging_issuers(payload, requested_date=NOV05)


def test_a_roster_dated_after_the_collect_day_is_rejected():
    with pytest.raises(sources.OfficialDataError, match="after 2026-11-04"):
        sources.parse_tpex_emerging_issuers(_roster(), requested_date=date(2026, 11, 4))


def test_a_row_without_a_code_or_short_name_is_left_out():
    rows = _with(0, SecuritiesCompanyCode="780")  # three digits, not a code
    rows = [*rows, {"Date": "1151105", "SecuritiesCompanyCode": "7999"}]
    records = sources.parse_tpex_emerging_issuers(rows, requested_date=NOV05)
    assert [r.symbol for r in records] == ["7924", "8058"]


# ---- adapter ----


def _combined(fetcher, *, snapshot_feeds=True):
    return sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher, snapshot_feeds=snapshot_feeds),
        sources.TpexAdapter(fetcher, snapshot_feeds=snapshot_feeds),
    )


def test_a_snapshot_batch_reads_the_roster_once_with_its_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = FixtureFetcher()
    batch = _combined(fetcher).fetch(DAY, DAY)
    assert fetcher.calls.count(sources.TPEX_EMERGING_ISSUER_ENDPOINT) == 1
    (capture,) = [
        p for p in batch.payloads if p.endpoint == sources.TPEX_EMERGING_ISSUER_ENDPOINT
    ]
    assert capture.payload_path.exists()
    assert [(r.symbol, r.name, r.payload_sha256) for r in batch.emerging_issuers] == [
        ("7808", "訊聯智藥", capture.sha256)
    ]
    # Names only: the roster never becomes a universe instrument.
    assert "7808" not in {item.symbol for item in batch.instruments}


def test_a_historical_batch_never_reads_the_roster(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = FixtureFetcher()
    batch = _combined(fetcher, snapshot_feeds=False).fetch(DAY, DAY)
    assert sources.TPEX_EMERGING_ISSUER_ENDPOINT not in fetcher.calls
    assert batch.emerging_issuers == []


# ---- collect ----


class RosterFetcher(FixtureFetcher):
    """FixtureFetcher with official industry codes (collect requires them)."""

    def __init__(self, roster=None):
        super().__init__()
        self.roster = roster

    def __call__(self, url, **kwargs):
        if url == sources.TPEX_EMERGING_ISSUER_ENDPOINT and self.roster is not None:
            self.calls.append(url)
            return self.roster
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            return [
                dict(row, Industry="01" if row["Code"] == "1101" else "24")
                for row in payload
            ]
        return payload


def _rows(factory):
    with factory() as db:
        return {
            row.symbol: (row.name, row.market, row.as_of_date, row.raw_payload_id)
            for row in db.scalars(select(EmergingIssuer))
        }


def test_collect_writes_the_roster_with_its_raw_and_no_instrument(database):
    result = pipeline.collect(DAY, adapter=_combined(RosterFetcher()))

    assert result["status"] == "success", result
    assert result["core_warnings"] == [] and result["noncore_warnings"] == []
    rows = _rows(database)
    assert set(rows) == {"7808"}
    name, market, as_of, raw_id = rows["7808"]
    assert (name, market, as_of) == ("訊聯智藥", "emerging", DAY)
    with database() as db:
        raw = db.get(RawPayload, raw_id)
        assert raw.endpoint == sources.TPEX_EMERGING_ISSUER_ENDPOINT
        assert raw.sha256 and Path(raw.payload_path).exists()
        assert raw.ingestion_run_id == result["run_id"]
        assert db.scalar(select(Instrument).where(Instrument.symbol == "7808")) is None
        run = db.get(IngestionRun, result["run_id"])
        assert run.metadata_json["emerging_issuers"] == {"inserted": 1}


def test_an_unreadable_roster_is_a_noncore_warning_and_writes_nothing(database):
    stale = [
        {"Date": "1150905", "SecuritiesCompanyCode": "7808", "CompanyAbbreviation": "x"}
    ]

    result = pipeline.collect(DAY, adapter=_combined(RosterFetcher(stale)))

    assert result["status"] == "success", result
    assert result["core_warnings"] == []
    (warning,) = result["noncore_warnings"]
    assert warning.startswith("TPEx emerging issuers unavailable: OfficialDataError: ")
    assert _rows(database) == {}


def test_emerging_roster_warnings_are_noncore():
    core, noncore = pipeline.split_collect_warnings(
        [
            sources.emerging_issuer_warning(sources.OfficialDataError("x")),
            "emerging issuers unavailable",
        ]
    )
    assert len(noncore) == 1 and len(core) == 1


# ---- storage ----


def _record(symbol, name, as_of, sha="s1"):
    return sources.EmergingIssuerRecord(
        symbol=symbol, name=name, as_of_date=as_of, payload_sha256=sha
    )


def _raws(db):
    first = RawPayload(source="tpex", endpoint="roster", sha256="s1")
    second = RawPayload(source="tpex", endpoint="roster", sha256="s2")
    db.add_all([first, second])
    db.flush()
    return {"s1": first.id, "s2": second.id}


def test_a_newer_roster_moves_the_row_and_an_older_one_never_rolls_it_back(
    database,
):
    with database() as db:
        raws = _raws(db)
        warnings: list[str] = []
        assert store_emerging_issuers(
            db, [_record("7808", "訊聯", date(2026, 11, 4))], raws.get, warnings
        ) == {"inserted": 1}
        assert store_emerging_issuers(
            db, [_record("7808", "訊聯智藥", NOV05, "s2")], raws.get, warnings
        ) == {"updated": 1}
        assert store_emerging_issuers(
            db, [_record("7808", "舊名", date(2026, 11, 3))], raws.get, warnings
        ) == {"older": 1}
        assert store_emerging_issuers(
            db, [_record("7808", "訊聯智藥", NOV05, "s2")], raws.get, warnings
        ) == {"unchanged": 1}
        db.commit()
        assert warnings == []
    assert _rows(database) == {"7808": ("訊聯智藥", "emerging", NOV05, raws["s2"])}


def test_a_row_without_its_raw_writes_none_of_the_roster(database):
    with database() as db:
        raws = _raws(db)
        warnings: list[str] = []
        outcome = store_emerging_issuers(
            db,
            [
                _record("7808", "訊聯智藥", NOV05),
                _record("8058", "耐特", NOV05, "none"),
            ],
            raws.get,
            warnings,
        )
        db.commit()
    assert outcome == {"failed": 2}
    (warning,) = warnings
    assert warning.startswith("TPEx emerging issuers unavailable: ValueError: ")
    assert _rows(database) == {}
