"""``worker.cli instruments repair``: replay stored captures (Issue #212)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.instrument_repair as repair
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    DataQuality,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    ThemeGroup,
)

SESSIONS = [date(2026, 10, 12) + timedelta(days=i) for i in range(11)]
SESSIONS = [day for day in SESSIONS if day.weekday() < 5]  # 10-12 .. 10-22
LISTS_AT = datetime(2026, 10, 23, 10, 30)  # 18:30 Taipei


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'repair.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _store(db, source, endpoint, payload, data_as_of, collected_at=LISTS_AT):
    capture = sources.capture_payload(
        source, endpoint, payload, data_as_of, collected_at=collected_at
    )
    db.add(
        RawPayload(
            source=source,
            endpoint=endpoint,
            payload_path=str(capture.payload_path),
            sha256=capture.sha256,
            data_as_of=data_as_of,
            collected_at=collected_at,
        )
    )
    db.flush()


def _tpex_quotes(day, codes):
    return {
        "stat": "ok",
        "date": day.strftime("%Y%m%d"),
        "tables": [
            {
                "fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低"]
                + ["均價", "成交股數", "成交金額(元)"],
                "data": [
                    [code, f"名稱{code}", "10", "0", "10", "11", "9", "10", "1000"]
                    + ["10000"]
                    for code in codes
                ],
            }
        ],
    }


def _tpex_institutional(day, codes):
    row = ["1", "2", "10", "1", "2", "1", "1", "2", "1", "2", "3", "4"]
    row += ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    return {
        "stat": "ok",
        "date": day.strftime("%Y%m%d"),
        "tables": [
            {
                "fields": [f"f{i}" for i in range(24)],
                "data": [[code, f"名稱{code}", *row] for code in codes],
            }
        ],
    }


def _seed(db):
    """TPEx 6488 trades every session; 8908 moved to TWSE on 10-16 and lost
    its last two TPEx bars; 5371 left both lists long ago and was never
    stored; 7777 still trades but no list carries it yet."""

    lists = [
        (
            "twse",
            sources.TWSE_LISTED_ENDPOINT,
            [{"公司代號": "2330", "公司簡稱": "台積電", "上市日期": "19940905"}],
        ),
        ("twse", sources.TWSE_ETF_ENDPOINT, []),
        (
            "twse",
            sources.TWSE_NEW_LISTING_ENDPOINT,
            [{"Code": "8908", "Company": "欣雄", "ApprovedListingDate": "1151016"}],
        ),
        (
            "tpex",
            sources.TPEX_LISTED_ENDPOINT,
            [
                {
                    "SecuritiesCompanyCode": "6488",
                    "CompanyAbbreviation": "環球晶",
                    "DateOfListing": "20010101",
                    "SecuritiesIndustryCode": "24",
                }
            ],
        ),
        ("tpex", sources.TPEX_ETF_ENDPOINT, []),
    ]
    # An older capture of a list must not be the one the sync reads.
    _store(
        db,
        "tpex",
        sources.TPEX_LISTED_ENDPOINT,
        [{"SecuritiesCompanyCode": "8908", "CompanyAbbreviation": "欣雄"}],
        "2026-09-08",
        collected_at=datetime(2026, 9, 8, 3),
    )
    for source, endpoint, payload in lists:
        _store(db, source, endpoint, payload, "2026-10-23")
    for index, day in enumerate(SESSIONS):
        codes = ["6488", "700019", "7777" if day == SESSIONS[-1] else "6488"]
        if index < 3:
            codes += ["8908"]
        if index < 2:
            codes += ["5371"]
        _store(
            db,
            "tpex",
            sources.TPEX_HISTORY_API,
            _tpex_quotes(day, codes),
            day.isoformat(),
            collected_at=datetime.combine(day, datetime.min.time())
            + timedelta(hours=10),
        )
        _store(
            db,
            "tpex",
            sources.TPEX_CHIP_HISTORY_ENDPOINT,
            _tpex_institutional(day, codes),
            day.isoformat(),
            collected_at=datetime.combine(day, datetime.min.time())
            + timedelta(hours=10),
        )
    group = ThemeGroup(id="official-industry-demo", name="Industry · Demo")
    db.add(group)
    ids = {}
    for exchange, symbol in (("TWSE", "2330"), ("TPEx", "6488"), ("TPEx", "8908")):
        item = Instrument(
            market="TW", exchange=exchange, symbol=symbol, name=symbol, status="active"
        )
        db.add(item)
        db.flush()
        ids[symbol] = item.id
    db.add(
        GroupMembership(
            group_id=group.id,
            instrument_id=ids["8908"],
            valid_from=date(2026, 9, 8),
            source="TWSE/TPEx official OpenAPI; exchange=TPEx",
        )
    )
    for day in SESSIONS:
        db.add(_bar(ids["6488"], day))
    db.add(_bar(ids["8908"], SESSIONS[0]))
    db.commit()
    return ids


def _bar(instrument_id, day):
    return MarketBar(
        instrument_id=instrument_id,
        trading_date=day,
        open=10,
        high=11,
        low=9,
        close=10,
        adj_close=10,
        volume=1000,
        turnover=10000,
        source="tpex",
        data_as_of=datetime.combine(day, datetime.min.time()),
    )


def _count(db, model, instrument_id):
    return db.scalar(
        select(func.count())
        .select_from(model)
        .where(model.instrument_id == instrument_id)
    )


def test_dry_run_plans_without_writing(db):
    ids = _seed(db)

    result = repair.repair_instruments(db, include_delisted=True)

    assert result["status"] == "dry_run"
    assert result["lists"]["TPEx"]["observed_date"] == "2026-10-23"
    assert [
        (c["symbol"], c["status"], c["close_day"]) for c in result["status_changes"]
    ] == [("8908", "transferred", "2026-10-15")]
    assert [
        (item["symbol"], item["status"], item["rows"])
        for item in result["instruments_to_create"]
    ] == [("5371", "delisted", 2)]
    assert [(item["symbol"], item["reason"]) for item in result["unmatched"]] == [
        ("7777", "quotes_too_recent_to_call_delisted")
    ]
    assert result["bars_to_write"] == 4  # 8908 x2, 5371 x2; 6488 complete
    assert result["chips_to_write"] == 5  # 8908 x3, 5371 x2
    db.rollback()
    assert db.get(Instrument, ids["8908"]).status == "active"
    assert _count(db, MarketBar, ids["8908"]) == 1


def test_apply_writes_once_and_a_rerun_writes_nothing(db):
    ids = _seed(db)

    applied = repair.repair_instruments(db, apply=True, include_delisted=True)
    db.commit()

    assert applied["status"] == "applied"
    moved = db.get(Instrument, ids["8908"])
    assert moved.status == "transferred"
    assert _count(db, MarketBar, ids["8908"]) == 3
    assert _count(db, ChipSnapshot, ids["8908"]) == 3
    bar = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == ids["8908"],
            MarketBar.trading_date == SESSIONS[2],
        )
    )
    raw = db.get(RawPayload, bar.raw_payload_id)
    assert raw.endpoint == sources.TPEX_HISTORY_API
    assert raw.data_as_of == SESSIONS[2].isoformat()
    # The stored bar of the first session is untouched.
    first = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == ids["8908"],
            MarketBar.trading_date == SESSIONS[0],
        )
    )
    assert first.raw_payload_id is None
    membership = db.scalar(
        select(GroupMembership).where(GroupMembership.instrument_id == ids["8908"])
    )
    assert membership.valid_to == date(2026, 10, 15)

    created = db.scalar(select(Instrument).where(Instrument.symbol == "5371"))
    assert (created.exchange, created.status, created.instrument_type) == (
        "TPEx",
        "delisted",
        "stock",
    )
    assert created.name == "名稱5371"
    assert _count(db, MarketBar, created.id) == 2
    quality = db.scalar(
        select(DataQuality).where(
            DataQuality.entity_type == "instrument_status",
            DataQuality.entity_key == "TPEx:5371",
        )
    )
    assert quality.status == "delisted"
    assert quality.checks_json["created_from"] == "stored official quote rows"
    assert db.scalar(select(Instrument).where(Instrument.symbol == "7777")) is None
    assert db.scalar(select(Instrument).where(Instrument.symbol == "700019")) is None
    run = db.get(IngestionRun, applied["ingestion_run_id"])
    assert run.run_type == "instrument_repair" and run.records == 4

    again = repair.repair_instruments(db, apply=True, include_delisted=True)
    assert again["status"] == "no_change"
    assert again["bars_to_write"] == 0 and again["chips_to_write"] == 0
    assert again["status_changes"] == [] and again["instruments_to_create"] == []


def test_without_include_delisted_unstored_codes_are_only_reported(db):
    _seed(db)

    result = repair.repair_instruments(db, apply=True)

    assert result["instruments_to_create"] == []
    assert {(item["symbol"], item["reason"]) for item in result["unmatched"]} == {
        ("5371", "include_delisted_not_requested"),
        ("7777", "quotes_too_recent_to_call_delisted"),
    }
    assert result["bars_to_write"] == 2
    assert db.scalar(select(Instrument).where(Instrument.symbol == "5371")) is None


def test_a_capture_that_no_longer_matches_its_sha256_stops_the_repair(db):
    _seed(db)
    raw = db.scalar(
        select(RawPayload).where(RawPayload.endpoint == sources.TPEX_HISTORY_API)
    )
    with open(raw.payload_path, "ab") as handle:
        handle.write(b" ")

    with pytest.raises(repair.InstrumentRepairError, match="does not match sha256"):
        repair.repair_instruments(db)
