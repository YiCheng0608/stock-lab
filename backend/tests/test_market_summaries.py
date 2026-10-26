"""Market summaries: parsers, collect, raw backfill and dashboard (Issue #275).

The fixtures are the 2026-10-22 official payloads, shortened:
``twse_mi_index_20261022.json`` keeps four rows of the price-index table, one
row of the return-index table, the 大盤統計資訊 and 漲跌證券數合計 tables
whole and two security rows; ``tpex_highlight_20261022.json`` is the whole
one-row ``tpex_mainborad_highlight`` response.
"""

from __future__ import annotations

import copy
import json
import socket
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
import worker.cli as cli
import worker.market_summary as market_summary
import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.market_overview import market_overview
from app.migrations import upgrade_database
from app.models import (
    DataQuality,
    IngestionRun,
    Instrument,
    MarketBar,
    MarketSummary,
    RawPayload,
)
from test_sources import FixtureFetcher

FIXTURES = Path(__file__).parent / "fixtures" / "market_summary"
OCT22 = date(2026, 10, 22)
DAY = date(2026, 9, 4)  # FixtureFetcher's session


def _twse_1022() -> dict:
    return json.loads(
        (FIXTURES / "twse_mi_index_20261022.json").read_text(encoding="utf-8")
    )


def _tpex_1022() -> list:
    return json.loads(
        (FIXTURES / "tpex_highlight_20261022.json").read_text(encoding="utf-8")
    )


def _table(payload: dict, title: str) -> dict:
    return next(t for t in payload["tables"] if title in str(t.get("title")))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def guard(real):
        def call(self, address, *args, **kwargs):
            # The Windows event loop of the API client pairs two loopback sockets.
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
                return real(self, address, *args, **kwargs)
            raise AssertionError("network forbidden in market summary tests")

        return call

    monkeypatch.setattr(socket.socket, "connect", guard(connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(connect_ex))


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'summary.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(market_summary, "SessionLocal", factory)
    monkeypatch.setattr(market_summary, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


# ---- AC-A1: TWSE MI_INDEX ----


def test_twse_summary_reads_the_1022_report():
    record = sources.parse_twse_market_summary(
        _twse_1022(), requested_date=OCT22, payload_sha256="abc"
    )

    assert record == sources.MarketSummaryRecord(
        exchange="TWSE",
        trading_date=OCT22,
        index_name="發行量加權股價指數",
        index_close=46041.43,
        # The sign is the HTML mark <p style ='color:green'>-</p>.
        index_change=-846.34,
        index_change_pct=-0.0181,
        change_pct_method="official",
        # 總計(1~15), not 證券合計(1+6+14+15) 843,735,035,072.
        turnover=933437473560,
        turnover_scope="twse_all_securities",
        # 股票 column: 247(3) and 756(5); 整體市場 has 3,781(10).
        advancers=247,
        decliners=756,
        unchanged=74,
        limit_up=3,
        limit_down=5,
        unmatched=7,
        not_comparable=0,
        breadth_scope="twse_stocks",
        source="twse_mi_index",
        data_as_of="2026-10-22",
        payload_sha256="abc",
    )


@pytest.mark.parametrize(
    ("sign", "points", "expected"),
    [
        ("<p style ='color:green'>-</p>", "846.34", -846.34),
        ("<p style ='color:red'>+</p>", "1,767.60", 1767.6),
        ("<p style= color:red>+</p>", "11.80", 11.8),
        ("+", "3.72", 3.72),
        ("", "0.00", 0.0),
        # A flat mark with points, X (no comparison) and signed points are not guessed.
        ("", "12.00", None),
        ("<p>X</p>", "0.00", None),
        ("<p style ='color:green'>-</p>", "-846.34", None),
        ("<p style ='color:green'>-</p>", "--", None),
        (None, "846.34", None),
    ],
)
def test_twse_change_reads_the_html_sign_mark(sign, points, expected):
    assert sources._twse_signed_change(sign, points) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("247(3)", (247, 3)),
        ("3,781(10)", (3781, 10)),
        ("11,885(107)", (11885, 107)),
        ("74", (74, None)),
        ("19,908", (19908, None)),
        ("0", (0, None)),
        ("247(x)", (None, None)),
        ("24,7(3)", (None, None)),
        ("-", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_twse_breadth_splits_count_and_limit(value, expected):
    assert sources._count_with_limit(value) == expected


def test_twse_missing_parts_are_null_not_zero():
    payload = _twse_1022()
    payload["tables"] = [
        t for t in payload["tables"] if "大盤統計資訊" not in str(t["title"])
    ]
    price = _table(payload, "價格指數(臺灣證券交易所)")
    drop = price["fields"].index("漲跌百分比(%)")
    price["fields"].pop(drop)
    for row in price["data"]:
        row.pop(drop)
    breadth = _table(payload, "漲跌證券數合計")
    breadth["data"] = [row for row in breadth["data"] if row[0] != "無比價"]
    breadth["data"][2][2] = "--"  # 持平

    record = sources.parse_twse_market_summary(payload, requested_date=OCT22)

    assert record.index_close == 46041.43 and record.index_change == -846.34
    assert record.index_change_pct is None
    assert record.turnover is None
    assert record.unchanged is None and record.not_comparable is None
    assert (record.advancers, record.limit_up) == (247, 3)


def test_twse_uses_the_price_index_and_never_the_return_index():
    payload = _twse_1022()
    payload["tables"] = [
        t for t in payload["tables"] if "價格指數" not in str(t["title"])
    ]
    record = sources.parse_twse_market_summary(payload, requested_date=OCT22)
    assert (record.index_close, record.index_change) == (None, None)
    assert record.turnover == 933437473560


def test_twse_sign_and_percentage_that_disagree_are_both_dropped():
    payload = _twse_1022()
    price = _table(payload, "價格指數(臺灣證券交易所)")
    row = next(r for r in price["data"] if r[0] == "發行量加權股價指數")
    row[2] = "<p style ='color:red'>+</p>"
    record = sources.parse_twse_market_summary(payload, requested_date=OCT22)
    assert (record.index_change, record.index_change_pct) == (None, None)
    assert record.index_close == 46041.43


def test_twse_a_repeated_table_or_row_is_not_guessed():
    payload = _twse_1022()
    payload["tables"].append(copy.deepcopy(_table(payload, "大盤統計資訊")))
    breadth = _table(payload, "漲跌證券數合計")
    breadth["data"].append(list(breadth["data"][0]))
    record = sources.parse_twse_market_summary(payload, requested_date=OCT22)
    assert record.turnover is None
    assert (record.advancers, record.limit_up) == (None, None)
    assert record.decliners == 756


@pytest.mark.parametrize("reported", ["20261021", None, ""])
def test_twse_report_of_another_date_is_rejected(reported):
    payload = _twse_1022()
    payload["date"] = reported
    with pytest.raises(sources.OfficialDataError, match="requested 2026-10-22"):
        sources.parse_twse_market_summary(payload, requested_date=OCT22)


def test_twse_report_without_any_summary_table_is_rejected():
    payload = _twse_1022()
    payload["tables"] = [_table(payload, "每日收盤行情")]
    with pytest.raises(sources.OfficialDataError, match="no index, turnover"):
        sources.parse_twse_market_summary(payload, requested_date=OCT22)


# ---- AC-A1: TPEx highlight ----


def test_tpex_highlight_reads_the_1022_row():
    record = sources.parse_tpex_market_highlight(
        _tpex_1022(), requested_date=OCT22, payload_sha256="def"
    )

    assert record == sources.MarketSummaryRecord(
        exchange="TPEx",
        # Date "1151022" is ROC 115 = 2026.
        trading_date=OCT22,
        index_name="櫃買指數",
        index_close=381.69,
        index_change=-13.73,
        # -13.73 / (381.69 + 13.73) from the previous close.
        index_change_pct=round(-13.73 / 395.42, 6),
        change_pct_method="derived",
        # DailyTradingValue 225545 is in millions of yuan.
        turnover=225_545_000_000,
        turnover_scope="tpex_stocks",
        advancers=146,
        decliners=659,
        unchanged=63,
        limit_up=17,
        limit_down=11,
        unmatched=26,
        not_comparable=None,
        breadth_scope="tpex_stocks",
        source="tpex_mainborad_highlight",
        data_as_of="2026-10-22",
        payload_sha256="def",
    )
    assert record.index_change_pct == -0.034723


@pytest.mark.parametrize("reported", ["1151021", "1151023", "", None])
def test_tpex_highlight_of_another_date_is_rejected(reported):
    payload = _tpex_1022()
    payload[0]["Date"] = reported
    with pytest.raises(sources.OfficialDataError, match="requested 2026-10-22"):
        sources.parse_tpex_market_highlight(payload, requested_date=OCT22)


@pytest.mark.parametrize("payload", [[], {}, "x", [{"Date": "1151022"}] * 2])
def test_tpex_highlight_needs_exactly_one_row(payload):
    with pytest.raises(sources.OfficialDataError, match="exactly one row"):
        sources.parse_tpex_market_highlight(payload, requested_date=OCT22)


def test_tpex_missing_or_unreadable_fields_are_null_not_zero():
    payload = _tpex_1022()
    del payload[0]["DailyTradingValue"]
    del payload[0]["IndexChange"]
    payload[0]["PriceFlatCompanyNumbers"] = "--"
    payload[0]["LimitUpCompanyNumbers"] = "1.5"
    record = sources.parse_tpex_market_highlight(payload, requested_date=OCT22)
    assert record.turnover is None
    assert record.index_change is None and record.index_change_pct is None
    assert record.unchanged is None and record.limit_up is None
    assert record.index_close == 381.69 and record.advancers == 146


# ---- AC-A2: adapters ----


def _summary_fetcher(*, highlight=None, mi_index=None):
    """FixtureFetcher whose 09/04 MI_INDEX carries the 10/22 summary tables."""

    def default_mi_index(base):
        report = _twse_1022()
        report["date"] = "20260904"
        # Keep FixtureFetcher's security table (codes 1101 etc.).
        report["tables"] = [
            t for t in report["tables"] if "每日收盤行情" not in str(t["title"])
        ] + [base["tables"][1]]
        return report

    def default_highlight():
        row = _tpex_1022()
        row[0]["Date"] = "1150904"
        return row

    class Fetcher(FixtureFetcher):
        def __call__(self, url, **kwargs):
            if url == sources.TPEX_HIGHLIGHT_ENDPOINT:
                self.calls.append(url)
                value = default_highlight() if highlight is None else highlight
                if isinstance(value, Exception):
                    raise value
                return value
            payload = super().__call__(url, **kwargs)
            if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
                return (mi_index or default_mi_index)(payload)
            if url == sources.TWSE_LISTED_ENDPOINT:
                # Official industry codes, as collect requires.
                return [
                    dict(row, Industry="01" if row["Code"] == "1101" else "24")
                    for row in payload
                ]
            return payload

    return Fetcher()


def _combined(fetcher):
    return sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher)
    )


def test_twse_summary_comes_from_the_taiex_capture_without_another_request(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = _summary_fetcher()

    batch = sources.TwseAdapter(fetcher).fetch(DAY, DAY)

    (summary,) = batch.market_summaries
    (taiex,) = [bar for bar in batch.bars if bar.symbol == "TAIEX"]
    assert summary.payload_sha256 == taiex.payload_sha256
    assert (summary.trading_date, summary.turnover) == (DAY, 933437473560)
    assert taiex.close == summary.index_close == 46041.43
    reports = [
        u for u in fetcher.calls if u.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT)
    ]
    assert len(reports) == 1
    assert sources.TPEX_HIGHLIGHT_ENDPOINT not in fetcher.calls


def test_historical_batches_read_twse_summaries_and_never_the_highlight(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = _summary_fetcher()
    adapter = sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher, snapshot_feeds=False),
        sources.TpexAdapter(fetcher, snapshot_feeds=False),
    )
    batch = adapter.fetch(DAY, DAY)
    assert [item.exchange for item in batch.market_summaries] == ["TWSE"]
    assert sources.TPEX_HIGHLIGHT_ENDPOINT not in fetcher.calls


def test_the_highlight_is_one_request_with_its_raw_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = _summary_fetcher()
    batch = _combined(fetcher).fetch(DAY, DAY)
    assert fetcher.calls.count(sources.TPEX_HIGHLIGHT_ENDPOINT) == 1
    (capture,) = [
        p for p in batch.payloads if p.endpoint == sources.TPEX_HIGHLIGHT_ENDPOINT
    ]
    assert capture.payload_path.exists()
    assert [(s.exchange, s.payload_sha256) for s in batch.market_summaries][1] == (
        "TPEx",
        capture.sha256,
    )


# ---- AC-A2: collect ----


def _rows(factory, model):
    with factory() as db:
        return db.scalars(select(model)).all()


def _raw(factory, raw_id):
    with factory() as db:
        return db.get(RawPayload, raw_id)


def _taiex_bar(factory):
    with factory() as db:
        index = db.scalar(select(Instrument).where(Instrument.symbol == "TAIEX"))
        return db.scalar(select(MarketBar).where(MarketBar.instrument_id == index.id))


def test_collect_writes_twse_and_tpex_rows_with_their_raw(database):
    fetcher = _summary_fetcher()

    result = pipeline.collect(DAY, adapter=_combined(fetcher))

    assert result["status"] == "success", result
    assert result["noncore_warnings"] == [] and result["core_warnings"] == []
    assert result["market_summaries"] == {"inserted": 2}
    rows = {row.exchange: row for row in _rows(database, MarketSummary)}
    assert set(rows) == {"TWSE", "TPEx"}
    # Same collect, same MI_INDEX capture as the TAIEX bar.
    assert rows["TWSE"].raw_payload_id == _taiex_bar(database).raw_payload_id
    twse_raw = _raw(database, rows["TWSE"].raw_payload_id)
    assert twse_raw.endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT)
    assert twse_raw.ingestion_run_id == result["run_id"]
    assert rows["TWSE"].collected_at == twse_raw.collected_at
    tpex_raw = _raw(database, rows["TPEx"].raw_payload_id)
    assert tpex_raw.endpoint == sources.TPEX_HIGHLIGHT_ENDPOINT
    assert Path(tpex_raw.payload_path).exists()
    assert (rows["TPEx"].trading_date, rows["TPEx"].turnover) == (DAY, 225545000000)
    with database() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert run.metadata_json["market_summaries"] == {"inserted": 2}


def test_an_old_highlight_writes_no_tpex_row_and_is_a_noncore_warning(database):
    stale = _tpex_1022()
    stale[0]["Date"] = "1150903"  # the feed has not been updated for 09/04 yet
    fetcher = _summary_fetcher(highlight=stale)

    result = pipeline.collect(DAY, adapter=_combined(fetcher))

    assert result["status"] == "success"
    assert result["core_warnings"] == []
    (warning,) = result["noncore_warnings"]
    assert warning.startswith("TPEx market summary unavailable for 2026-09-04: ")
    assert "'1150903'" in warning
    assert [row.exchange for row in _rows(database, MarketSummary)] == ["TWSE"]
    # The capture is kept like every other raw payload.
    with database() as db:
        assert db.scalar(
            select(RawPayload).where(
                RawPayload.endpoint == sources.TPEX_HIGHLIGHT_ENDPOINT
            )
        )


def _collect_and_analyze(tmp_path, monkeypatch, name, fetcher, *, patch=None):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with monkeypatch.context() as scoped:
        scoped.setattr(pipeline, "SessionLocal", factory)
        scoped.setattr(pipeline, "init_db", lambda: None)
        scoped.setattr(sources, "RAW_DIR", tmp_path / f"raw-{name}")
        if patch:
            patch(scoped)
        collected = pipeline.collect(DAY, adapter=_combined(fetcher))
        analyzed = pipeline.analyze(
            init_schema=False, collect_run_id=collected["run_id"]
        )
        with factory() as db:
            bars = sorted(
                (b.instrument_id, b.trading_date, b.close)
                for b in db.scalars(select(MarketBar))
            )
            quality = db.scalar(
                select(DataQuality).where(DataQuality.entity_type == "ingestion_run")
            )
            state = (bars, quality.status, quality.missing_fields_json)
    engine.dispose()
    return collected, analyzed, state


def test_summary_failures_change_neither_collect_nor_analyze(tmp_path, monkeypatch):
    baseline = _collect_and_analyze(tmp_path, monkeypatch, "a.db", _summary_fetcher())

    real_upsert = market_summary.upsert_market_summary

    def twse_write_fails(db, record, raw, **kwargs):
        if record.exchange == "TWSE":
            raise RuntimeError("fixture write failure")
        return real_upsert(db, record, raw, **kwargs)

    failing = _collect_and_analyze(
        tmp_path,
        monkeypatch,
        "b.db",
        _summary_fetcher(highlight=sources.OfficialDataError("fixture 503")),
        patch=lambda scoped: scoped.setattr(
            market_summary, "upsert_market_summary", twse_write_fails
        ),
    )

    collected, analyzed, state = failing
    assert collected["status"] == baseline[0]["status"] == "success"
    assert collected["core_warnings"] == []
    assert sorted(w.split(":")[0] for w in collected["noncore_warnings"]) == [
        "TPEx market summary unavailable for 2026-09-04",
        "TWSE market summary unavailable for 2026-09-04",
    ]
    assert collected["market_summaries"] == {"failed": 1}
    for key in ("records", "taiex_records", "chips", "actions", "events"):
        assert collected[key] == baseline[0][key], key
    assert analyzed["status"] == baseline[1]["status"]
    assert {k: v for k, v in analyzed.items() if k != "run_id"} == {
        k: v for k, v in baseline[1].items() if k != "run_id"
    }
    assert state == baseline[2] and state[1] == "success" and state[2] == []


def test_market_summary_warnings_are_noncore_and_others_stay_core():
    core, noncore = pipeline.split_collect_warnings(
        [
            "TWSE market summary unavailable for 2026-09-04: OfficialDataError: x",
            "TPEx market summary unavailable for 2026-09-04: OfficialDataError: y",
            "TWSE MI_INDEX unavailable for 2026-09-04 endpoint=x: y",
            "market summary unavailable",
        ]
    )
    assert len(noncore) == 2 and len(core) == 2


def _record(**changes):
    record = sources.parse_twse_market_summary(_twse_1022(), requested_date=OCT22)
    return sources.MarketSummaryRecord(**{**record.__dict__, **changes})


def test_a_recollect_keeps_the_first_capture_fills_nulls_and_force_overwrites(
    database,
):
    with database() as db:
        first = RawPayload(
            source="twse", endpoint="first", collected_at=datetime(2026, 10, 22, 10)
        )
        second = RawPayload(
            source="twse", endpoint="second", collected_at=datetime(2026, 10, 22, 13)
        )
        db.add_all([first, second])
        db.flush()
        upsert = market_summary.upsert_market_summary
        assert upsert(db, _record(turnover=None), first) == "inserted"
        assert upsert(db, _record(turnover=None), second) == "unchanged"
        assert upsert(db, _record(), second) == "filled"
        assert upsert(db, _record(index_close=1.0), second) == "conflict"
        row = db.scalar(select(MarketSummary))
        assert (row.index_close, row.turnover) == (46041.43, 933437473560)
        assert row.raw_payload_id == first.id
        assert (
            upsert(db, _record(index_close=1.0, unmatched=None), second, overwrite=True)
            == "overwritten"
        )
        assert (row.index_close, row.unmatched) == (1.0, 7)
        assert (row.raw_payload_id, row.collected_at) == (
            second.id,
            second.collected_at,
        )


# ---- AC-A3: raw backfill CLI ----


def _store_report(factory, day: date, payload, *, sha=None) -> int:
    capture = sources.capture_payload(
        "twse",
        f"{sources.TWSE_DAILY_HISTORY_ENDPOINT}?date={day:%Y%m%d}&type=ALLBUT0999&response=json",
        payload,
        day.isoformat(),
        collected_at=datetime(day.year, day.month, day.day, 10, 30),
    )
    with factory() as db:
        raw = RawPayload(
            source=capture.source,
            endpoint=capture.endpoint,
            payload_path=str(capture.payload_path),
            sha256=sha or capture.sha256,
            data_as_of=capture.data_as_of,
            collected_at=capture.collected_at,
        )
        db.add(raw)
        db.commit()
        return raw.id


@pytest.fixture
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("market-summary must not send a request")

    for name in ("get", "post", "request", "stream"):
        monkeypatch.setattr(httpx, name, forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(sources, "fetch_json", forbidden)


def test_backfill_reads_only_stored_twse_raw(database, offline, monkeypatch, capsys):
    oct22 = _store_report(database, OCT22, _twse_1022())
    holiday = _store_report(
        database, date(2026, 10, 23), {"stat": "很抱歉，沒有符合條件的資料!"}
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker.cli", "market-summary", "--from", "2026-10-21", "--to", "2026-10-25"],
    )

    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "success" and result["written"] == 1
    assert [(d["date"], d["status"], d["raw_payload_id"]) for d in result["dates"]] == [
        ("2026-10-21", "no_raw", None),
        ("2026-10-22", "inserted", oct22),
        ("2026-10-23", "no_data", holiday),
    ]
    (row,) = _rows(database, MarketSummary)
    assert (row.exchange, row.trading_date, row.raw_payload_id) == (
        "TWSE",
        OCT22,
        oct22,
    )
    assert row.collected_at == datetime(2026, 10, 22, 10, 30)
    assert row.turnover == 933437473560
    # TPEx has no history: nothing to backfill.
    assert not [r for r in _rows(database, MarketSummary) if r.exchange == "TPEx"]


def test_backfill_uses_the_newest_capture_and_reports_bad_raw(database, offline):
    _store_report(database, OCT22, {"date": "20261022", "stat": "OK", "tables": []})
    newest = _store_report(database, OCT22, _twse_1022())
    with database() as db:
        db.get(RawPayload, newest).collected_at = datetime(2026, 10, 23, 1)
        db.commit()
    wrong_date = _twse_1022()
    wrong_date["date"] = "20261020"
    _store_report(database, date(2026, 10, 21), wrong_date)
    _store_report(database, date(2026, 10, 20), _twse_1022(), sha="0" * 64)

    result = market_summary.backfill_market_summaries(date(2026, 10, 20), OCT22)

    statuses = {d["date"]: d["status"] for d in result["dates"]}
    assert statuses == {
        "2026-10-20": "unreadable",
        "2026-10-21": "rejected",
        "2026-10-22": "inserted",
    }
    assert result["status"] == "partial"
    (row,) = _rows(database, MarketSummary)
    assert row.raw_payload_id == newest


def test_backfill_rejects_an_inverted_range():
    with pytest.raises(ValueError):
        market_summary.backfill_market_summaries(OCT22, date(2026, 10, 21))


# ---- AC-A4: dashboard.market_overview ----


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    yield factory
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


def _seed(factory, *, as_of="2026-10-22", rows=()):
    with factory() as db:
        if as_of:
            db.add(
                IngestionRun(
                    run_type="collect",
                    source="official",
                    run_date=date.fromisoformat(as_of),
                    status="success",
                    records=10,
                    data_as_of=as_of,
                )
            )
        raw = RawPayload(
            source="twse",
            endpoint="fixture",
            collected_at=datetime(2026, 10, 22, 10, 30, 5),
        )
        db.add(raw)
        db.flush()
        for exchange, day in rows:
            parse = (
                sources.parse_twse_market_summary
                if exchange == "TWSE"
                else sources.parse_tpex_market_highlight
            )
            record = parse(
                _twse_1022() if exchange == "TWSE" else _tpex_1022(),
                requested_date=OCT22,
            )
            record = sources.MarketSummaryRecord(
                **{**record.__dict__, "trading_date": day}
            )
            market_summary.upsert_market_summary(db, record, raw)
        db.commit()


def _overview(factory):
    with TestClient(app) as client:
        response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["market_overview"]["trading_date"] == payload["as_of"]
    return payload["market_overview"]


def test_dashboard_overview_with_both_exchanges(api_db):
    _seed(api_db, rows=[("TWSE", OCT22), ("TPEx", OCT22)])

    overview = _overview(api_db)

    twse, tpex = overview["exchanges"]
    assert twse == {
        "exchange": "TWSE",
        "status": "available",
        "index": {
            "name": "加權指數",
            "close": 46041.43,
            "change": -846.34,
            "change_pct": -0.0181,
            "change_pct_method": "official",
        },
        "turnover": {
            "value": 933437473560,
            "scope": "twse_all_securities",
            "scope_label": "集中市場總計（含 ETF、權證等）",
        },
        "breadth": {
            "advancers": 247,
            "decliners": 756,
            "unchanged": 74,
            "limit_up": 3,
            "limit_down": 5,
            "unmatched": 7,
            "not_comparable": 0,
            "scope": "twse_stocks",
        },
        "source": {
            "label": "臺灣證券交易所 MI_INDEX",
            "collected_at": "2026-10-22T10:30:05+00:00",
            "data_as_of": "2026-10-22",
            "raw_payload_id": 1,
        },
    }
    assert tpex["status"] == "available"
    assert tpex["index"]["name"] == "櫃買指數"
    assert tpex["index"]["change_pct_method"] == "derived"
    assert tpex["turnover"] == {
        "value": 225545000000,
        "scope": "tpex_stocks",
        "scope_label": "上櫃股票",
    }
    assert tpex["breadth"]["not_comparable"] is None


def test_dashboard_overview_with_one_exchange_keeps_the_other(api_db):
    _seed(api_db, rows=[("TWSE", OCT22)])
    twse, tpex = _overview(api_db)["exchanges"]
    assert twse["status"] == "available"
    assert tpex == {
        "exchange": "TPEx",
        "status": "unavailable",
        "reason": "not_collected",
        "latest_trading_date": None,
    }


def test_dashboard_overview_never_shows_a_row_of_another_date(api_db):
    # The highlight row of 10/21 must not stand in for the 10/22 dashboard.
    _seed(api_db, rows=[("TWSE", OCT22), ("TPEx", date(2026, 10, 21))])
    twse, tpex = _overview(api_db)["exchanges"]
    assert twse["status"] == "available"
    assert tpex == {
        "exchange": "TPEx",
        "status": "unavailable",
        "reason": "row_date_mismatch",
        "latest_trading_date": "2026-10-21",
    }


def test_dashboard_overview_with_neither_exchange(api_db):
    _seed(api_db)
    overview = _overview(api_db)
    assert [item["status"] for item in overview["exchanges"]] == [
        "unavailable",
        "unavailable",
    ]
    assert {item["reason"] for item in overview["exchanges"]} == {"not_collected"}


def test_dashboard_overview_without_a_verified_session(api_db):
    _seed(api_db, as_of=None, rows=[("TWSE", OCT22)])
    with TestClient(app) as client:
        payload = client.get("/api/dashboard").json()
    assert payload["as_of"] is None
    assert payload["market_overview"] == {
        "trading_date": None,
        "exchanges": [
            {
                "exchange": "TWSE",
                "status": "unavailable",
                "reason": "no_verified_session",
            },
            {
                "exchange": "TPEx",
                "status": "unavailable",
                "reason": "no_verified_session",
            },
        ],
    }


def test_market_overview_turnover_scopes_are_the_two_known_ones(database):
    with database() as db:
        for exchange, payload, parse in (
            ("TWSE", _twse_1022(), sources.parse_twse_market_summary),
            ("TPEx", _tpex_1022(), sources.parse_tpex_market_highlight),
        ):
            market_summary.upsert_market_summary(
                db, parse(payload, requested_date=OCT22), None
            )
        overview = market_overview(db, "2026-10-22")
    assert [e["turnover"]["scope"] for e in overview["exchanges"]] == [
        "twse_all_securities",
        "tpex_stocks",
    ]
