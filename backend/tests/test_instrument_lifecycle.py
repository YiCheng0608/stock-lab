"""Quote rows outside today's lists and instrument status sync (Issue #212).

Official quote tables keep a company's rows after it leaves the issuer master
(delisting, transfer to the other exchange, a list that lags a new listing).
The collector used to drop those rows twice: the adapters filtered quotes by
today's lists and ``collect`` skipped a row whose code was not in the batch.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
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
    ThemeGroup,
)

SCORE_DATE = date(2026, 10, 16)
CAPTURED = datetime(2026, 10, 16, 10, 0)  # 18:00 Taipei


@pytest.fixture
def pipeline_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


def _capture(source: str, endpoint: str, payload) -> sources.FetchedPayload:
    return sources.capture_payload(
        source, endpoint, payload, SCORE_DATE.isoformat(), collected_at=CAPTURED
    )


def _bar(symbol: str, exchange: str, sha: str, day: date = SCORE_DATE):
    return sources.BarRecord(
        symbol=symbol,
        trading_date=day,
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume=1000,
        turnover=10500,
        exchange=exchange,
        source="twse_index" if symbol == "TAIEX" else exchange.lower(),
        data_as_of=day.isoformat(),
        payload_sha256=sha,
        turnover_status="available",
    )


def _chip(symbol: str, exchange: str, sha: str):
    return sources.ChipRecord(
        symbol,
        SCORE_DATE,
        foreign_buy=1.0,
        trust_buy=2.0,
        dealer_buy=3.0,
        margin_balance=40.0,
        margin_change=5.0,
        exchange=exchange,
        source=f"{exchange.lower()}_fixture",
        data_as_of=SCORE_DATE.isoformat(),
        payload_sha256=sha,
    )


def _instrument(db, exchange, symbol, *, instrument_type="stock", status="active"):
    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=f"{exchange} {symbol}",
        instrument_type=instrument_type,
        status=status,
    )
    db.add(item)
    db.flush()
    return item


class FakeAdapter:
    def __init__(self, batch):
        self.batch = batch

    def fetch(self, start, end):
        return self.batch


def _historical_batch(*codes: tuple[str, str]) -> sources.OfficialBatch:
    """A catch-up batch: TWSE 2330 is listed; ``codes`` only have quote rows."""

    quotes = _capture("tpex", sources.TPEX_HISTORY_API, {"fixture": "quotes"})
    return sources.OfficialBatch(
        instruments=[
            sources.InstrumentRecord(
                "TAIEX", "TAIEX", exchange="TWSE", instrument_type="index"
            ),
            sources.InstrumentRecord("2330", "TSMC", exchange="TWSE", industry="24"),
        ],
        bars=[
            _bar("TAIEX", "TWSE", quotes.sha256),
            _bar("2330", "TWSE", quotes.sha256),
            *(_bar(symbol, exchange, quotes.sha256) for exchange, symbol in codes),
        ],
        chips=[_chip(symbol, exchange, quotes.sha256) for exchange, symbol in codes],
        payloads=[quotes],
        data_as_of=SCORE_DATE.isoformat(),
        snapshot_feeds=False,
    )


# ---- AC-1: the collector no longer drops a stored instrument's quote rows ----


def test_collect_writes_quotes_of_a_stored_instrument_missing_from_the_lists(
    pipeline_env,
):
    with pipeline_env() as db:
        moved = _instrument(db, "TPEx", "8908")
        db.commit()
        moved_id = moved.id

    result = pipeline.collect(
        SCORE_DATE, adapter=FakeAdapter(_historical_batch(("TPEx", "8908")))
    )

    assert result["status"] == "success"
    assert result["records"] == 3
    with pipeline_env() as db:
        bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == moved_id))
        chip = db.scalar(
            select(ChipSnapshot).where(ChipSnapshot.instrument_id == moved_id)
        )
        assert bar is not None and bar.close == 10.5 and bar.raw_payload_id
        assert chip is not None and chip.foreign_buy == 1.0
        # Writing the rows does not touch the instrument's status.
        assert db.get(Instrument, moved_id).status == "active"


def test_collect_records_quotes_with_no_instrument_instead_of_dropping_them(
    pipeline_env,
):
    result = pipeline.collect(
        SCORE_DATE, adapter=FakeAdapter(_historical_batch(("TPEx", "5371")))
    )

    # A list that lags a new listing must not hold back the day's analysis.
    assert result["status"] == "success"
    assert result["records"] == 2
    with pipeline_env() as db:
        assert db.scalar(select(Instrument).where(Instrument.symbol == "5371")) is None
        quality = db.scalar(
            select(DataQuality).where(DataQuality.entity_type == "unmatched_bar")
        )
        run = db.get(IngestionRun, result["run_id"])
    assert quality.entity_key == "TPEx:5371"
    assert quality.as_of_date == SCORE_DATE
    assert quality.status == "missing"
    assert quality.checks_json["trading_dates"] == [SCORE_DATE.isoformat()]
    assert quality.checks_json["source"] == "tpex"
    assert quality.checks_json["raw_payload_ids"]
    assert run.metadata_json["unmatched_bars"] == [
        {
            "exchange": "TPEx",
            "symbol": "5371",
            "first_date": SCORE_DATE.isoformat(),
            "last_date": SCORE_DATE.isoformat(),
            "rows": 1,
        }
    ]
    assert any("unmatched_bar" in notice for notice in run.metadata_json["notices"])


def test_collect_has_no_silent_skip_of_a_quote_row():
    """Every ``continue`` in the bar loop is the date window or a recorded row."""

    import inspect

    source = inspect.getsource(pipeline.collect)
    loop = source[source.index("for record in batch.bars:") :]
    loop = loop[: loop.index("normalized_date_set")]
    assert loop.count("continue") == 2
    assert "note_unmatched_bar(" in loop


# ---- adapters pass ordinary-share codes and nothing else ----


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("2330", True),
        ("8908", True),
        ("2881A", False),  # preferred share
        ("0050", False),  # ETF
        ("00679B", False),  # bond ETF
        ("030001", False),  # warrant
        ("700019", False),  # TPEx warrant
        ("9103", False),  # TWSE depositary receipt
        ("910322", False),  # TWSE depositary receipt
        ("65331", False),  # convertible bond
        ("", False),
    ],
)
def test_common_stock_code(symbol, expected):
    assert sources.is_common_stock_code(symbol) is expected


def _tpex_quotes(rows):
    fields = [
        "代號",
        "名稱",
        "收盤",
        "漲跌",
        "開盤",
        "最高",
        "最低",
        "均價",
        "成交股數",
        "成交金額(元)",
    ]
    return {
        "stat": "ok",
        "date": "20261016",
        "tables": [
            {
                "fields": fields,
                "data": [
                    [code, name, "10", "0", "10", "11", "9", "10", "1000", "10000"]
                    for code, name in rows
                ],
            }
        ],
    }


def test_tpex_quotes_keep_ordinary_shares_outside_the_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    payload = _tpex_quotes(
        [
            ("6488", "環球晶"),
            ("8908", "欣雄"),
            ("006201", "元大富櫃50"),
            ("00679B", "元大美債20年"),
            ("700019", "某某購01"),
            ("65331", "某某一"),
        ]
    )
    adapter = sources.TpexAdapter(lambda url, **_: payload)

    bars, _ = adapter.fetch_bars(["6488"], SCORE_DATE, SCORE_DATE)

    assert sorted(bar.symbol for bar in bars) == ["6488", "8908"]


def test_twse_quotes_keep_ordinary_shares_outside_the_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fields = [
        "Code",
        "OpeningPrice",
        "HighestPrice",
        "LowestPrice",
        "ClosingPrice",
        "TradeVolume",
        "TradeValue",
    ]
    codes = ["2330", "2888", "2881A", "0056", "9103", "910322", "030001"]
    rows = [[code, "10", "11", "9", "10", "1000", "10000"] for code in codes]

    def fetch(url, **_):
        if url == sources.TWSE_DAILY_ENDPOINT:
            return [dict(zip(fields, row)) | {"Date": "1151016"} for row in rows]
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            return {
                "date": "20261016",
                "tables": [
                    {
                        "title": "115年10月16日 價格指數(臺灣證券交易所)",
                        "fields": ["指數", "收盤指數"],
                        "data": [["發行量加權股價指數", "24000"]],
                    },
                    {"fields": fields, "data": rows},
                ],
            }
        raise AssertionError(url)

    bars, _ = sources.TwseAdapter(fetch).fetch_bars(["2330"], SCORE_DATE, SCORE_DATE)

    assert sorted(bar.symbol for bar in bars) == ["2330", "2888", "TAIEX"]


def test_newlisting_rows_outside_the_listing_window_are_not_listings(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    listed = _capture(
        "twse",
        sources.TWSE_LISTED_ENDPOINT,
        [
            {
                "公司代號": "2330",
                "公司簡稱": "台積電",
                "上市日期": "19940905",
                "產業別": "24",
            }
        ],
    )
    etf = _capture("twse", sources.TWSE_ETF_ENDPOINT, [])
    newlisting = _capture(
        "twse",
        sources.TWSE_NEW_LISTING_ENDPOINT,
        [
            # Listed in 2011 and delisted since: no longer in the master.
            {"Code": "3598", "Company": "奕力", "ApprovedListingDate": "1000111"},
            # Effective today, not yet in the master: still a listing.
            {"Code": "8908", "Company": "欣雄", "ApprovedListingDate": "1151016"},
            # Approved for a later date: not yet listed.
            {"Code": "6467", "Company": "泰合", "ApprovedListingDate": "1151020"},
        ],
    )

    records = sources.twse_universe_records(listed, etf, newlisting, SCORE_DATE)

    by_symbol = {record.symbol: record for record in records}
    assert set(by_symbol) == {"2330", "8908"}
    assert by_symbol["8908"].instrument_type == "ipo"
    assert by_symbol["8908"].listing_date == SCORE_DATE


# ---- status sync from today's lists ----


def _lists(twse_codes, tpex_codes, *, twse_listing=None):
    """Universe records and evidence for both exchanges, as collect builds them."""

    twse_listing = twse_listing or {}
    captures = [
        _capture("twse", sources.TWSE_LISTED_ENDPOINT, {"codes": sorted(twse_codes)}),
        _capture("twse", sources.TWSE_ETF_ENDPOINT, []),
        _capture("twse", sources.TWSE_NEW_LISTING_ENDPOINT, []),
        _capture("tpex", sources.TPEX_LISTED_ENDPOINT, {"codes": sorted(tpex_codes)}),
        _capture("tpex", sources.TPEX_ETF_ENDPOINT, []),
    ]
    records = [
        sources.InstrumentRecord(
            code,
            code,
            exchange="TWSE",
            instrument_type="ipo" if code in twse_listing else "stock",
            listing_date=twse_listing.get(code),
            industry="23",
            payload_sha256=captures[0].sha256,
        )
        for code in twse_codes
    ] + [
        sources.InstrumentRecord(
            code,
            code,
            exchange="TPEx",
            industry="23",
            payload_sha256=captures[3].sha256,
        )
        for code in tpex_codes
    ]
    return records, captures


def _seed_market(db, twse_codes, tpex_codes):
    group = ThemeGroup(
        id="official-industry-oil-gas-electricity",
        name="Industry · Oil, Gas and Electricity",
        group_type="official_industry",
        definition_version="official-v1",
        source=pipeline.OFFICIAL_INDUSTRY_SOURCE,
    )
    theme = ThemeGroup(id="theme-demo", name="Demo theme", group_type="theme")
    db.add_all([group, theme])
    ids = {}
    for exchange, codes in (("TWSE", twse_codes), ("TPEx", tpex_codes)):
        for code in codes:
            item = _instrument(db, exchange, code)
            ids[(exchange, code)] = item.id
            db.add(
                GroupMembership(
                    group_id=group.id,
                    instrument_id=item.id,
                    valid_from=date(2026, 9, 8),
                    source=f"{pipeline.OFFICIAL_INDUSTRY_SOURCE}; exchange={exchange}",
                )
            )
    db.flush()
    return ids


TWSE_CODES = [f"1{index:03d}" for index in range(30)]
TPEX_CODES = [f"6{index:03d}" for index in range(30)]


def test_status_sync_marks_delisted_and_transferred_and_closes_memberships(
    pipeline_env,
):
    with pipeline_env() as db:
        ids = _seed_market(db, TWSE_CODES, TPEX_CODES + ["8908", "8183"])
        db.add(
            GroupMembership(
                group_id="theme-demo",
                instrument_id=ids[("TPEx", "8183")],
                valid_from=date(2026, 10, 1),
                source="theme_table",
            )
        )
        db.flush()
        records, captures = _lists(
            TWSE_CODES + ["8908"], TPEX_CODES, twse_listing={"8908": SCORE_DATE}
        )
        for record in records:
            pipeline._upsert_official_instrument(db, record)
        plan = pipeline.plan_instrument_status(
            db, records, pipeline.universe_evidence(captures, lambda _: 7)
        )
        result = pipeline.apply_instrument_status(db, plan)
        db.commit()

        moved = db.get(Instrument, ids[("TPEx", "8908")])
        gone = db.get(Instrument, ids[("TPEx", "8183")])
        assert moved.status == "transferred"
        assert gone.status == "delisted"
        assert result["warnings"] == []
        assert {
            (item["symbol"], item["status"], item["close_day"])
            for item in result["changes"]
        } == {
            ("8908", "transferred", "2026-10-15"),  # day before the TWSE listing
            ("8183", "delisted", "2026-10-15"),  # day before the observation
        }
        memberships = db.scalars(
            select(GroupMembership).where(
                GroupMembership.instrument_id.in_([moved.id, gone.id])
            )
        ).all()
        assert len(memberships) == 3  # closed, never deleted
        assert {(m.group_id, m.valid_to) for m in memberships} == {
            ("official-industry-oil-gas-electricity", date(2026, 10, 15)),
            ("theme-demo", date(2026, 10, 15)),
        }
        quality = db.scalar(
            select(DataQuality).where(
                DataQuality.entity_type == "instrument_status",
                DataQuality.entity_key == "TPEx:8908",
            )
        )
        assert quality.status == "transferred"
        assert quality.as_of_date == SCORE_DATE
        assert quality.checks_json["reason"] == "listed_on_other_exchange"
        assert quality.checks_json["moved_to"] == {
            "exchange": "TWSE",
            "listing_date": SCORE_DATE.isoformat(),
        }
        assert [item["raw_payload_id"] for item in quality.checks_json["evidence"]] == [
            7,
            7,
        ]
        # Instruments still in the lists stay active.
        assert db.get(Instrument, ids[("TPEx", "6000")]).status == "active"

        # A second sync changes nothing.
        again = pipeline.apply_instrument_status(
            db,
            pipeline.plan_instrument_status(
                db, records, pipeline.universe_evidence(captures, lambda _: 7)
            ),
        )
        assert again["changes"] == []


def test_status_sync_membership_end_never_precedes_its_start(pipeline_env):
    with pipeline_env() as db:
        ids = _seed_market(db, TWSE_CODES + ["6423"], TPEX_CODES)
        records, captures = _lists(TWSE_CODES, TPEX_CODES + ["6423"])
        records = [
            record
            if record.symbol != "6423"
            else sources.InstrumentRecord(
                "6423",
                "6423",
                exchange="TPEx",
                listing_date=date(2026, 1, 22),
                industry="24",
                payload_sha256=record.payload_sha256,
            )
            for record in records
        ]
        result = pipeline.apply_instrument_status(
            db,
            pipeline.plan_instrument_status(
                db, records, pipeline.universe_evidence(captures, lambda _: None)
            ),
        )
        membership = db.scalar(
            select(GroupMembership).where(
                GroupMembership.instrument_id == ids[("TWSE", "6423")]
            )
        )
        assert result["changes"][0]["close_day"] == "2026-01-21"
        assert membership.valid_to == membership.valid_from == date(2026, 9, 8)


def test_status_sync_skips_an_exchange_whose_list_looks_incomplete(pipeline_env):
    with pipeline_env() as db:
        ids = _seed_market(db, TWSE_CODES, TPEX_CODES)
        # 6 of 30 TPEx codes missing: above the floor of 5.
        records, captures = _lists(TWSE_CODES, TPEX_CODES[6:])
        result = pipeline.apply_instrument_status(
            db,
            pipeline.plan_instrument_status(
                db, records, pipeline.universe_evidence(captures, lambda _: None)
            ),
        )
        assert db.get(Instrument, ids[("TPEx", "6000")]).status == "active"
        assert result["changes"] == []
        assert result["exchanges"]["TPEx"]["status"] == "skipped"
        assert result["exchanges"]["TWSE"]["status"] == "applied"
        assert result["warnings"] == [
            "instrument status sync skipped for TPEx: 6 of 30 active instruments "
            "are absent from the official lists (limit 5)"
        ]
        rows = {
            row.entity_key: row
            for row in db.scalars(
                select(DataQuality).where(
                    DataQuality.entity_type == "instrument_status_sync"
                )
            )
        }
        assert rows["TPEx"].status == "skipped"
        assert rows["TWSE"].status == "applied"
    # The skip is a non-core warning: the collect stays successful.
    core, noncore = pipeline.split_collect_warnings(result["warnings"])
    assert core == [] and noncore == result["warnings"]


def test_status_sync_needs_every_list_of_an_exchange(pipeline_env):
    records, captures = _lists(TWSE_CODES, TPEX_CODES)
    without_tpex_etf = [
        item for item in captures if item.endpoint != sources.TPEX_ETF_ENDPOINT
    ]
    evidence = pipeline.universe_evidence(without_tpex_etf, lambda _: None)
    assert set(evidence) == {"TWSE"}
    assert evidence["TWSE"]["observed_date"] == SCORE_DATE


def test_relisted_instrument_becomes_active_again(pipeline_env):
    with pipeline_env() as db:
        item = _instrument(db, "TPEx", "8183", status="delisted")
        pipeline._upsert_official_instrument(
            db, sources.InstrumentRecord("8183", "精星", exchange="TPEx")
        )
        assert item.status == "active"


def test_snapshot_collect_syncs_status_and_historical_collect_does_not(
    pipeline_env,
):
    with pipeline_env() as db:
        ids = _seed_market(db, TWSE_CODES, TPEX_CODES + ["8183"])
        db.commit()
    records, captures = _lists(TWSE_CODES, TPEX_CODES)
    index = sources.InstrumentRecord(
        "TAIEX", "TAIEX", exchange="TWSE", instrument_type="index", industry="Index"
    )
    batch = sources.OfficialBatch(
        instruments=records + [index],
        bars=[
            _bar(record.symbol, record.exchange, captures[0].sha256)
            for record in records
        ]
        + [_bar("TAIEX", "TWSE", captures[0].sha256)],
        payloads=captures,
        data_as_of=SCORE_DATE.isoformat(),
        snapshot_feeds=False,
    )

    historical = pipeline.collect(SCORE_DATE, adapter=FakeAdapter(batch))
    with pipeline_env() as db:
        assert db.get(Instrument, ids[("TPEx", "8183")]).status == "active"
        assert (
            db.get(IngestionRun, historical["run_id"]).metadata_json[
                "instrument_status_sync"
            ]["status"]
            == "not_requested"
        )

    batch.snapshot_feeds = True
    snapshot = pipeline.collect(SCORE_DATE, adapter=FakeAdapter(batch), force=True)
    assert snapshot["status"] == "success"
    with pipeline_env() as db:
        assert db.get(Instrument, ids[("TPEx", "8183")]).status == "delisted"
        changes = db.get(IngestionRun, snapshot["run_id"]).metadata_json[
            "instrument_status_sync"
        ]["changes"]
    assert [(item["symbol"], item["status"]) for item in changes] == [
        ("8183", "delisted")
    ]
    assert SCORE_DATE - timedelta(days=1) == date.fromisoformat(changes[0]["close_day"])
