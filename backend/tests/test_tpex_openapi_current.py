"""The current TPEx session's core feeds come from OpenAPI (Issue #579, #555 決定 B).

The daily collect of today's Taipei session reads the quotes, institutional
and margin OpenAPI tables first.  A table of another session (the margin table
is usually still the previous session's at 21:30) or an unavailable one makes
that feed read the website report; the run metadata ``feed_sources`` records
which endpoint each feed used and why.  Catch-up, backfill and any other date
read the website reports.

The fixtures are the 2026-11-09 responses of #555 P1/P2 and of the 11-09 21:30
daily, cut to twelve codes: two ETFs, a bond ETF and three stocks without a
trade that day (``---`` prices), a warrant (not a security of the universe),
stocks whose margin note is ``OX`` (停止融資融券) and ``11  *A C``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.chip_provenance as chip_provenance
import worker.chip_revisions as chip_revisions
import worker.instrument_repair as repair
import worker.margin_lists as margin_lists
import worker.no_trade_days as no_trade_days
import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    Instrument,
    MarginList,
    MarketBar,
    NoTradeDay,
)

DAY = date(2026, 11, 9)
FIXTURES = Path(__file__).parent / "fixtures" / "tpex_openapi"
OA_QUOTES = sources.TPEX_DAILY_ENDPOINT
OA_INSTI = sources.TPEX_CHIP_ENDPOINT
OA_MARGIN = sources.TPEX_MARGIN_ENDPOINT
WWW_QUOTES = sources.TPEX_HISTORY_API
WWW_INSTI = sources.TPEX_CHIP_HISTORY_ENDPOINT
WWW_MARGIN = sources.TPEX_MARGIN_HISTORY_ENDPOINT
OPENAPI = (OA_QUOTES, OA_INSTI, OA_MARGIN)
WEBSITE = (WWW_QUOTES, WWW_INSTI, WWW_MARGIN)
NO_TRADE = {"00982B", "2724", "3064", "4305"}


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _payloads(margin: str = "oa_margin_20261109.json") -> dict[str, object]:
    return {
        sources.TPEX_LISTED_ENDPOINT: fixture("mops_listed_20261109.json"),
        sources.TPEX_ETF_ENDPOINT: fixture("etf_filter_20261109.json"),
        OA_QUOTES: fixture("oa_quotes_20261109.json"),
        OA_INSTI: fixture("oa_insti_20261109.json"),
        OA_MARGIN: fixture(margin),
        WWW_QUOTES: fixture("www_quotes_20261109.json"),
        WWW_INSTI: fixture("www_insti_20261109.json"),
        WWW_MARGIN: fixture("www_margin_20261109.json"),
        sources.TPEX_ACTION_ENDPOINT: [],
    }


class Fetcher:
    """Answers the fixture endpoints; any other request fails (a non-core feed)."""

    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, object]] = []

    def __call__(self, url: str, method: str = "GET", data=None, **_kwargs):
        self.calls.append((url, data))
        if url not in self.payloads:
            raise RuntimeError(f"not a fixture endpoint: {url}")
        value = self.payloads[url]
        if isinstance(value, Exception):
            raise value
        if url in WEBSITE:
            assert data["date"] == "2026/11/09"
        return copy.deepcopy(value)

    def asked(self, url: str) -> bool:
        return any(call == url for call, _data in self.calls)


@pytest.fixture(autouse=True)
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


def _fetch(payloads=None, *, today=DAY, snapshot=True):
    fetcher = Fetcher(payloads or _payloads())
    adapter = sources.TpexAdapter(fetcher, snapshot_feeds=snapshot, today=lambda: today)
    return adapter.fetch(DAY, DAY), fetcher


def _openapi_warnings(batch) -> list[str]:
    return [item for item in batch.warnings if item.startswith("TPEx OpenAPI ")]


def _stale(rows: list[dict], reported: str = "1151106") -> list[dict]:
    return [{**row, "Date": reported} for row in rows]


# ---- AC-1: which endpoint each feed reads ------------------------------------


def test_current_session_reads_the_three_openapi_tables_only():
    batch, fetcher = _fetch()

    assert all(fetcher.asked(url) for url in OPENAPI)
    assert not any(fetcher.asked(url) for url in WEBSITE)
    tpex = batch.feed_sources["TPEx"]
    assert tpex["session"] == "2026-11-09"
    for feed, endpoint in (
        ("quotes", OA_QUOTES),
        ("institutional", OA_INSTI),
        ("margin", OA_MARGIN),
    ):
        assert tpex[feed]["source"] == "openapi"
        assert tpex[feed]["endpoint"] == endpoint
        assert tpex[feed]["reported_date"] == "2026-11-09"
    captured = {item.sha256: item.endpoint for item in batch.payloads}
    assert {captured[bar.payload_sha256] for bar in batch.bars} == {OA_QUOTES}
    assert {
        captured[chip.payload_sha256]
        for chip in batch.chips
        if chip.source.startswith("tpex_3insti")
    } == {OA_INSTI}
    assert {
        captured[chip.margin_payload_sha256]
        for chip in batch.chips
        if chip.margin_payload_sha256
    } == {OA_MARGIN}
    assert _openapi_warnings(batch) == []


def test_previous_session_margin_table_reads_the_website_report_without_warning():
    # 21:07 and 21:24 on 11-09 the OpenAPI margin table was still 11-06's.
    batch, fetcher = _fetch(_payloads(margin="oa_margin_20261106.json"))

    assert fetcher.asked(OA_MARGIN) and fetcher.asked(WWW_MARGIN)
    assert not fetcher.asked(WWW_QUOTES) and not fetcher.asked(WWW_INSTI)
    margin = batch.feed_sources["TPEx"]["margin"]
    assert margin["source"] == "website"
    assert margin["endpoint"] == WWW_MARGIN
    assert margin["reason"] == "openapi_not_current"
    assert margin["openapi_reported_date"] == "2026-11-06"
    assert batch.feed_sources["TPEx"]["institutional"]["source"] == "openapi"
    # The margin values are the website report's, the stale table is kept as
    # raw under the requested date (a reader's reported-date check rejects it).
    by_sha = {item.sha256: item for item in batch.payloads}
    assert {
        by_sha[chip.margin_payload_sha256].endpoint
        for chip in batch.chips
        if chip.margin_payload_sha256
    } == {WWW_MARGIN}
    stale = by_sha[margin["openapi_payload_sha256"]]
    assert stale.endpoint == OA_MARGIN and stale.data_as_of == "2026-11-09"
    assert _openapi_warnings(batch) == []
    assert not any("margin" in item for item in batch.warnings)


@pytest.mark.parametrize(
    ("feed", "openapi", "website"),
    [("quotes", OA_QUOTES, WWW_QUOTES), ("institutional", OA_INSTI, WWW_INSTI)],
)
def test_previous_session_quote_or_institutional_table_reads_the_website_with_warning(
    feed, openapi, website
):
    payloads = _payloads()
    payloads[openapi] = _stale(payloads[openapi])
    batch, fetcher = _fetch(payloads)

    assert fetcher.asked(openapi) and fetcher.asked(website)
    record = batch.feed_sources["TPEx"][feed]
    assert record["source"] == "website" and record["endpoint"] == website
    assert record["reason"] == "openapi_not_current"
    assert record["openapi_reported_date"] == "2026-11-06"
    warnings = _openapi_warnings(batch)
    assert warnings == [
        f"TPEx OpenAPI {feed} not used for 2026-11-09 (reported 2026-11-06); "
        f"read {website}"
    ]
    # Non-core: the session still has every row, so the collect stays success.
    core, noncore = pipeline.split_collect_warnings(warnings)
    assert core == [] and noncore == warnings
    # Nothing of the stale table is mapped to another session.
    assert {bar.trading_date for bar in batch.bars} == {DAY}
    assert {chip.trading_date for chip in batch.chips} == {DAY}


def test_unavailable_openapi_table_reads_the_website_with_warning():
    payloads = _payloads()
    payloads[OA_QUOTES] = RuntimeError("HTTP 503")
    batch, fetcher = _fetch(payloads)

    assert fetcher.asked(WWW_QUOTES)
    record = batch.feed_sources["TPEx"]["quotes"]
    assert record["reason"] == "openapi_unavailable"
    assert "HTTP 503" in record["openapi_error"]
    assert len(_openapi_warnings(batch)) == 1
    assert len(batch.bars) == 7  # the traded stocks and ETFs, as from OpenAPI


def test_mixed_dates_in_an_openapi_table_are_not_one_session():
    payloads = _payloads()
    rows = payloads[OA_INSTI]
    rows[0] = {**rows[0], "Date": "1151106"}
    batch, fetcher = _fetch(payloads)

    assert fetcher.asked(WWW_INSTI)
    record = batch.feed_sources["TPEx"]["institutional"]
    assert record["openapi_reported_date"] is None
    assert "reported no single date" in _openapi_warnings(batch)[0]


@pytest.mark.parametrize(
    ("today", "snapshot"),
    [
        (date(2026, 11, 10), True),  # a past session: catch-up, manual collect
        (DAY, False),  # the historical adapter (catch-up, chunked backfill)
    ],
)
def test_other_collects_read_the_website_reports_only(today, snapshot):
    batch, fetcher = _fetch(today=today, snapshot=snapshot)

    assert not any(fetcher.asked(url) for url in OPENAPI)
    assert all(fetcher.asked(url) for url in WEBSITE)
    tpex = batch.feed_sources["TPEx"]
    assert tpex["session"] is None and tpex["reason"] == "not_current_session"
    assert tpex["margin"] == {"source": "website", "endpoint": WWW_MARGIN}


def test_combined_adapter_carries_the_tpex_feed_sources():
    class Twse:
        captured_payloads: list = []

        def fetch(self, start, end):
            return sources.OfficialBatch(
                instruments=[sources.InstrumentRecord("TAIEX", "TAIEX", "TWSE")],
                bars=[_taiex(None)],
            )

    fetcher = Fetcher(_payloads())
    adapter = sources.OfficialMarketDataAdapter(
        twse=Twse(),
        tpex=sources.TpexAdapter(fetcher, today=lambda: DAY),
        mops_fetcher=fetcher,
    )
    batch = adapter.fetch(DAY, DAY)
    assert batch.feed_sources["TPEx"]["quotes"]["source"] == "openapi"


# ---- 管理股票 --------------------------------------------------------------


def test_managed_stock_missing_from_the_openapi_quotes_is_a_noncore_warning():
    # No TPEx stock has been in industry 80 since 2024-09; mark 1781 as one.
    payloads = _payloads()
    for row in payloads[sources.TPEX_LISTED_ENDPOINT]:
        if row["SecuritiesCompanyCode"] == "1781":
            row["SecuritiesIndustryCode"] = sources.TPEX_MANAGED_INDUSTRY_CODE
    payloads[OA_QUOTES] = [
        row for row in payloads[OA_QUOTES] if row["SecuritiesCompanyCode"] != "1781"
    ]
    batch, fetcher = _fetch(payloads)

    quotes = batch.feed_sources["TPEx"]["quotes"]
    assert quotes["source"] == "openapi"  # reported, not switched
    assert not fetcher.asked(WWW_QUOTES)
    assert quotes["managed_stocks"] == ["1781"]
    assert quotes["managed_stocks_missing"] == ["1781"]
    warnings = _openapi_warnings(batch)
    assert warnings == [
        "TPEx OpenAPI quotes omit managed stocks (industry 80) listed by "
        f"{sources.TPEX_LISTED_ENDPOINT}: 1781"
    ]
    assert pipeline.split_collect_warnings(warnings) == ([], warnings)


def test_managed_stock_in_the_openapi_quotes_is_not_reported():
    payloads = _payloads()
    for row in payloads[sources.TPEX_LISTED_ENDPOINT]:
        if row["SecuritiesCompanyCode"] == "1781":
            row["SecuritiesIndustryCode"] = sources.TPEX_MANAGED_INDUSTRY_CODE
    batch, _fetcher = _fetch(payloads)

    assert batch.feed_sources["TPEx"]["quotes"]["managed_stocks_missing"] == []
    assert _openapi_warnings(batch) == []


def test_website_managed_stock_table_rows_are_read():
    # The website's 管理股票 table has been empty in all 559 stored captures;
    # a real main-table row moved there is still read like any other row.
    payloads = _payloads()
    main, managed = payloads[WWW_QUOTES]["tables"]
    row = next(item for item in main["data"] if item[0] == "1781")
    main["data"].remove(row)
    managed["data"] = [row]
    web, _ = _fetch(payloads, today=date(2026, 11, 10))
    api, _ = _fetch()

    def bar(batch):
        found = next(item for item in batch.bars if item.symbol == "1781")
        return replace(found, payload_sha256=None)

    assert bar(web) == bar(api)


# ---- AC-2: the rows collect writes are the same from either source -----------


INDEX = sources.InstrumentRecord(
    "TAIEX", "TAIEX", exchange="TWSE", instrument_type="index"
)


def _taiex(sha: str | None) -> sources.BarRecord:
    return sources.BarRecord(
        symbol="TAIEX",
        trading_date=DAY,
        open=100,
        high=100,
        low=100,
        close=100,
        volume=0,
        turnover=0,
        exchange="TWSE",
        source="twse_index",
        data_as_of=DAY.isoformat(),
        payload_sha256=sha,
    )


class FakeAdapter:
    def __init__(self, batch):
        self.batch = batch

    def fetch(self, start, end):
        return self.batch


def _collect_into(tmp_path, monkeypatch, name: str, batch) -> sessionmaker:
    """One collect of DAY with ``batch`` (plus a TAIEX row) into a new database."""

    engine = create_engine(f"sqlite:///{tmp_path / f'{name}.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    first = batch.payloads[0].sha256
    collected = replace(
        batch,
        instruments=[INDEX, *batch.instruments],
        bars=[_taiex(first), *batch.bars],
        snapshot_feeds=False,
    )
    result = pipeline.collect(DAY, adapter=FakeAdapter(collected))
    assert result["status"] in {"success", "partial"}, result
    return factory


def _rows(factory, model, skip: set[str]) -> dict[str, dict]:
    columns = [c.name for c in model.__table__.columns if c.name not in skip]
    with factory() as db:
        found = db.execute(
            select(Instrument.symbol, model)
            .join(Instrument, Instrument.id == model.instrument_id)
            .where(Instrument.exchange == "TPEx")
        ).all()
        return {
            symbol: {name: getattr(row, name) for name in columns}
            for symbol, row in found
        }


# Provenance columns: ids and collection times differ between two databases;
# the endpoint is the actual source on purpose.
PROVENANCE = {
    "id",
    "instrument_id",
    "collected_at",
    "raw_payload_id",
    "volume_raw_payload_id",
    "institutional_raw_payload_id",
    "institutional_collected_at",
    "margin_raw_payload_id",
    "margin_collected_at",
    "endpoint",
}


@pytest.fixture
def written(tmp_path, monkeypatch):
    api, _ = _fetch()
    web, _ = _fetch(today=date(2026, 11, 10))
    assert {p.endpoint for p in api.payloads} >= set(OPENAPI)
    assert not {p.endpoint for p in api.payloads} & set(WEBSITE)
    assert not {p.endpoint for p in web.payloads} & set(OPENAPI)
    return (
        _collect_into(tmp_path, monkeypatch, "openapi", api),
        _collect_into(tmp_path, monkeypatch, "website", web),
    )


def test_quote_rows_are_column_for_column_the_websites(written):
    api, web = written
    api_rows = _rows(api, MarketBar, PROVENANCE)
    web_rows = _rows(web, MarketBar, PROVENANCE)
    # Two ETFs and five stocks traded; the warrant is not a security of the
    # universe and the four ``---`` rows have no bar.
    assert set(api_rows) == {"00411A", "006201", "1240", "1781", "2221", "3105", "6488"}
    assert api_rows == web_rows
    assert api_rows["6488"]["volume"] == 6_430_510
    assert api_rows["00411A"]["turnover"] == 34_831_471
    # The no-trade rows (#454) come from either table alike.
    api_none = _rows(api, NoTradeDay, PROVENANCE)
    assert set(api_none) == NO_TRADE
    assert api_none == _rows(web, NoTradeDay, PROVENANCE)


def test_institutional_rows_are_column_for_column_the_websites(written):
    api, web = written
    columns = {"foreign_buy", "trust_buy", "dealer_buy", "institutional_source"}
    skip = (
        {c.name for c in ChipSnapshot.__table__.columns} - columns - {"instrument_id"}
    )
    api_rows = _rows(api, ChipSnapshot, skip | {"instrument_id"})
    assert api_rows == _rows(web, ChipSnapshot, skip | {"instrument_id"})
    # The #555 P1 samples: 6488 total -1,696,638 = foreign + trust + dealer.
    row = api_rows["6488"]
    assert row["institutional_source"] == "tpex_3insti"
    assert row["foreign_buy"] + row["trust_buy"] + row["dealer_buy"] == -1_696_638
    assert set(api_rows) >= {"00411A", "006201", "1781", "2221"}


def test_margin_rows_are_column_for_column_the_websites(written):
    api, web = written
    api_rows = _rows(api, ChipSnapshot, PROVENANCE)
    assert api_rows == _rows(web, ChipSnapshot, PROVENANCE)
    # 1781 (OX: 停止融資融券) and the no-trade 3064 still have margin rows.
    assert api_rows["1781"]["margin_source"] == "tpex_margin"
    assert api_rows["3064"]["margin_balance"] is not None
    assert api_rows["3064"]["source"] == "tpex_margin"
    assert api_rows["6488"]["source"] == "tpex_3insti+tpex_margin"


# ---- AC-3: readers of the stored captures -----------------------------------


def test_margin_list_from_the_openapi_table_equals_the_websites(written):
    api, web = written

    def stored(factory):
        with factory() as db:
            row = db.scalar(select(MarginList).where(MarginList.exchange == "TPEx"))
            return row.endpoint, row.member_count, row.members_json, row.source

    api_list, web_list = stored(api), stored(web)
    assert api_list[0] == OA_MARGIN and web_list[0] == WWW_MARGIN
    assert api_list[1:] == web_list[1:]
    assert api_list[2]["1781"] == "OX" and api_list[2]["2221"] == "11  *A C"


def test_stale_openapi_capture_is_not_evidence_for_its_requested_date(
    tmp_path, monkeypatch
):
    # The 11-06 margin table captured on 11-09: the list and the chips are the
    # website report's.
    batch, _ = _fetch(_payloads(margin="oa_margin_20261106.json"))
    factory = _collect_into(tmp_path, monkeypatch, "stale", batch)
    with factory() as db:
        row = db.scalar(select(MarginList).where(MarginList.exchange == "TPEx"))
        assert row.endpoint == WWW_MARGIN
        metadata = db.scalar(
            select(pipeline.IngestionRun.metadata_json).where(
                pipeline.IngestionRun.run_type == "collect"
            )
        )
    assert metadata["feed_sources"]["TPEx"]["margin"]["reason"] == "openapi_not_current"


def test_hot_group_evidence_accepts_the_openapi_institutional_file(written):
    api, web = written
    with api() as db:
        assert set(pipeline._official_institutional_file_evidence(db, DAY)) == {"TPEx"}
    with web() as db:
        assert set(pipeline._official_institutional_file_evidence(db, DAY)) == {"TPEx"}


def test_status_sync_quote_rows_accept_the_openapi_table(written):
    api, web = written
    with api() as db:
        api_codes = pipeline._stored_quote_rows(db, "TPEx", [DAY])
    with web() as db:
        web_codes = pipeline._stored_quote_rows(db, "TPEx", [DAY])
    assert api_codes is not None and web_codes is not None
    # Every row, traded or not, warrant included.
    assert api_codes[0] == web_codes[0]
    assert {"3064", "700019"} <= api_codes[0]


def test_no_trade_rows_cite_the_openapi_table(written):
    api, _web = written
    with api() as db:
        endpoints = set(
            db.scalars(
                select(NoTradeDay.endpoint)
                .join(Instrument, Instrument.id == NoTradeDay.instrument_id)
                .where(Instrument.exchange == "TPEx")
            )
        )
    assert endpoints == {OA_QUOTES}


def test_chip_revision_replays_the_openapi_institutional_capture(written):
    api, _web = written
    with api() as db:
        result = chip_revisions.revise_institutional(db, DAY, DAY)
    assert result["status"] == "success"
    assert result["captures_replayed"] == 1
    assert result["revised_rows"] == 0 and result["value_conflicts"] == 0


def test_chip_provenance_finds_the_openapi_captures(written):
    api, _web = written
    with api() as db:
        for row in db.scalars(select(ChipSnapshot)):
            for group in ("institutional", "margin"):
                for suffix in (
                    "source",
                    "raw_payload_id",
                    "data_as_of",
                    "collected_at",
                ):
                    setattr(row, f"{group}_{suffix}", None)
        db.flush()
        result = chip_provenance.fill_provenance(db)
    assert result["unmatched_samples"] == []
    assert result["institutional_mismatch_samples"] == []
    assert result["unreadable_captures"] == []
    assert result["pending_after"] == 0


def test_instrument_repair_reads_the_openapi_captures(written):
    api, web = written
    with api() as db:
        files = repair._stored_chip_files(db, "TPEx", DAY, {})
        quotes = db.scalar(
            select(pipeline.RawPayload).where(pipeline.RawPayload.endpoint == OA_QUOTES)
        )
        api_bars = repair._quote_bars(quotes, repair._load(quotes))
    with web() as db:
        web_files = repair._stored_chip_files(db, "TPEx", DAY, {})
        quotes = db.scalar(
            select(pipeline.RawPayload).where(
                pipeline.RawPayload.endpoint == WWW_QUOTES
            )
        )
        web_bars = repair._quote_bars(quotes, repair._load(quotes))

    def values(day_files):
        return {
            group: {
                symbol: replace(record, payload_sha256=None, margin_payload_sha256=None)
                for _raw, records, _reason in captures
                for symbol, record in (records or {}).items()
            }
            for group, captures in day_files.items()
        }

    assert all(len(captures) == 1 for captures in files.values())
    assert values(files) == values(web_files)
    assert [replace(b, payload_sha256=None) for b in api_bars] == [
        replace(b, payload_sha256=None) for b in web_bars
    ]
    assert repair._is_quote_capture(OA_QUOTES)


def test_readers_reject_a_stale_openapi_capture(tmp_path, monkeypatch):
    payloads = _payloads(margin="oa_margin_20261106.json")
    payloads[OA_INSTI] = _stale(payloads[OA_INSTI])
    batch, _ = _fetch(payloads)
    factory = _collect_into(tmp_path, monkeypatch, "stale2", batch)
    with factory() as db:
        files = repair._stored_chip_files(db, "TPEx", DAY, {})
        # Each group: the stale OpenAPI capture is passed over, the website
        # report decides.
        for captures in files.values():
            assert len(captures) == 2
            assert captures[0][1] == {} and "mismatch" in captures[0][2]
            assert captures[1][1]
        result = chip_revisions.revise_institutional(db, DAY, DAY)
    # The stale OpenAPI table is skipped, not unreadable: no partial run.
    assert result["status"] == "success"
    assert result["captures_replayed"] == 1
    assert result["unreadable_captures"] == []
    stale = next(item for item in batch.payloads if item.endpoint == OA_INSTI).sha256
    with factory() as db:
        stale_id = db.scalar(
            select(pipeline.RawPayload.id).where(pipeline.RawPayload.sha256 == stale)
        )
    assert result["other_session_captures"] == [stale_id]


def test_blank_openapi_margin_balance_is_unknown_not_the_previous_day():
    # "marginpurchasebalance" is a prefix of the previous-day key: a blank
    # balance must stay blank, as the website table's position read keeps it.
    rows = fixture("oa_margin_20261109.json")
    rows[0] = {**rows[0], "MarginPurchaseBalance": ""}
    parsed = {
        item.symbol: item
        for item in sources.parse_tpex_margin_rows(rows, trading_date=DAY)
    }
    assert rows[0]["SecuritiesCompanyCode"] == "00411A"
    assert parsed["00411A"].margin_balance is None
    assert parsed["00411A"].margin_change is None
    assert parsed["006201"].margin_balance is not None


def _store_capture(factory, endpoint: str, payload, day: date, hour: int) -> int:
    """A stored raw capture of ``endpoint`` requested for ``day``."""

    captured = sources.capture_payload(
        "tpex",
        endpoint,
        payload,
        day.isoformat(),
        collected_at=datetime(day.year, day.month, day.day, hour),
    )
    with factory() as db:
        row = pipeline.RawPayload(
            source="tpex",
            endpoint=endpoint,
            payload_path=str(captured.payload_path),
            sha256=captured.sha256,
            data_as_of=day.isoformat(),
            collected_at=captured.collected_at,
        )
        db.add(row)
        db.commit()
        return row.id


def test_a_newer_stale_openapi_table_does_not_replace_the_websites_evidence(written):
    # The website collect of DAY, then a later OpenAPI capture requested for
    # DAY that still reports 11-06: the newest capture, but not DAY's table.
    _api, web = written
    _store_capture(web, OA_QUOTES, _stale(fixture("oa_quotes_20261109.json")), DAY, 20)
    _store_capture(web, OA_MARGIN, fixture("oa_margin_20261106.json"), DAY, 20)
    with web() as db:
        no_trade = no_trade_days.store_no_trade_days(db, "TPEx", DAY)
        margin = margin_lists.store_margin_list(db, "TPEx", DAY)
        endpoints = set(
            db.scalars(
                select(NoTradeDay.endpoint)
                .join(Instrument, Instrument.id == NoTradeDay.instrument_id)
                .where(Instrument.exchange == "TPEx")
            )
        )
        listed = db.scalar(select(MarginList).where(MarginList.exchange == "TPEx"))
    assert no_trade["outcome"] == "unchanged" and endpoints == {WWW_QUOTES}
    assert margin == "unchanged" and listed.endpoint == WWW_MARGIN


def test_an_only_stale_openapi_table_is_no_evidence(written):
    # 11-10 before TPEx updated: the only capture requested for 11-10 is the
    # 11-09 table (the website request failed).  It is no answer for 11-10.
    _api, web = written
    next_day = date(2026, 11, 10)
    _store_capture(web, OA_QUOTES, fixture("oa_quotes_20261109.json"), next_day, 13)
    _store_capture(web, OA_MARGIN, fixture("oa_margin_20261109.json"), next_day, 13)
    with web() as db:
        no_trade = no_trade_days.store_no_trade_days(db, "TPEx", next_day)
        margin = margin_lists.store_margin_list(db, "TPEx", next_day)
        rows = db.scalar(
            select(func.count())
            .select_from(NoTradeDay)
            .where(NoTradeDay.trading_date == next_day)
        )
    assert no_trade == {"outcome": "missing", "rows": 0, "unmatched": []}
    assert margin == "missing" and rows == 0
