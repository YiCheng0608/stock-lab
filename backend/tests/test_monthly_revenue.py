"""Monthly revenue: the daily snapshot, the MOPS t21sc03 backfill and the stock page cutoff (Issue #530).

``monthly_revenue/*.json`` are rows of the 2026-11-06 ``t187ap05_L`` (1101, 2330,
1256 鮮活果汁-KY) and ``mopsfin_t187ap05_O`` (6488, 4442 竣邦-KY) responses,
unchanged.  ``mops_t21sc03/*.html`` are the 115/09 pages fetched the same day
(``_0`` domestic, ``_1`` foreign), decoded from Big5, trimmed to a few
industries and companies, with the source's runs of padding spaces collapsed.
"""

from __future__ import annotations

import json
import socket
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.migrations import upgrade_database
from app.models import IngestionRun, Instrument, MonthlyRevenue, RawPayload
from test_daily_schedule import CodedFetcher, OutageFetcher, combined
from worker import monthly_revenue as mr
from worker import pipeline, sources, trading_calendar

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SNAPSHOTS = FIXTURES / "monthly_revenue"
PAGES = FIXTURES / "mops_t21sc03"
# 2026-11-06 12:00 Taipei: 115/09's deadline (10/10, a Saturday, so 10/12) has
# passed, 115/10's (11/10) is ahead.
NOW = datetime(2026, 11, 6, 4, 0)
SEPTEMBER = mr.Month(2026, 9)
DAY = date(2026, 9, 4)  # FixtureFetcher's session
INSTRUMENTS = (
    ("TWSE", "1101"),
    ("TWSE", "2330"),
    ("TWSE", "2884"),
    ("TWSE", "1256"),
    ("TPEx", "6488"),
    ("TPEx", "4442"),
)


def snapshot(exchange: str) -> list[dict]:
    name = "t187ap05_L" if exchange == "TWSE" else "mopsfin_t187ap05_O"
    return json.loads((SNAPSHOTS / f"{name}_11509.json").read_text(encoding="utf-8"))


def page_html(market: str, page: int, month: mr.Month = SEPTEMBER) -> str:
    html = (PAGES / f"{market}_115_9_{page}.html").read_text(encoding="utf-8")
    return html.replace("115年9月份", f"{month.year - 1911}年{month.month}月份")


class PageFetcher:
    """Answers each t21sc03 URL from the fixtures; records every URL."""

    def __init__(self, fail=()):
        self.urls: list[str] = []
        self.fail = set(fail)

    def __call__(self, url):
        self.urls.append(url)
        if url in self.fail:
            raise sources.OfficialDataError("fixture outage")
        market, rest = url.split("/t21/")[1].split("/t21sc03_")
        year, month, page = rest.removesuffix(".html").split("_")
        return page_html(market, int(page), mr.Month(int(year) + 1911, int(month)))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, frozen_utcnow):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in monthly revenue tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    frozen_utcnow.at = NOW
    return frozen_utcnow


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'revenue.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with made() as db:
        for exchange, symbol in INSTRUMENTS:
            db.add(
                Instrument(
                    market="TW",
                    exchange=exchange,
                    symbol=symbol,
                    name=symbol,
                    instrument_type="stock",
                    status="active",
                )
            )
        db.commit()
    yield made
    engine.dispose()


def store_calendar(db, years):
    def fetcher(url, **_kwargs):
        year = int(url.split("date=")[1][:4])
        return json.loads(
            (FIXTURES / "trading_calendar" / f"{year}.json").read_text("utf-8")
        )

    trading_calendar.store_trading_calendar(
        db, years, run_date=date(2026, 10, 26), fetcher=fetcher
    )
    db.commit()


def rows(db) -> dict[tuple[str, str], MonthlyRevenue]:
    query = select(Instrument.symbol, MonthlyRevenue).join(
        Instrument, Instrument.id == MonthlyRevenue.instrument_id
    )
    return {
        (symbol, row.revenue_month.strftime("%Y-%m")): row
        for symbol, row in db.execute(query).all()
    }


def backfill(factory, fetcher=None, **kwargs):
    with factory() as db:
        return mr.backfill_monthly_revenues(
            db,
            fetcher=fetcher or PageFetcher(),
            sleep=lambda _seconds: None,
            **kwargs,
        )


def instruments(db):
    return {
        (item.exchange, item.symbol): item for item in db.scalars(select(Instrument))
    }


def raw(db, sha="s1"):
    row = RawPayload(source="twse", endpoint="t187ap05_L", sha256=sha)
    db.add(row)
    db.flush()
    return row.id


# --- the OpenAPI snapshot -----------------------------------------------------


def test_the_snapshot_reads_month_values_and_its_release_date():
    records = sources.parse_monthly_revenue_rows(
        snapshot("TWSE"),
        exchange="TWSE",
        requested_date=date(2026, 11, 6),
        payload_sha256="abc",
    )
    by_symbol = {record.symbol: record for record in records}
    assert set(by_symbol) == {"1101", "2330", "1256"}
    tsmc = by_symbol["2330"]
    assert (
        tsmc.revenue_month,
        tsmc.revenue,
        tsmc.prior_year_revenue,
        tsmc.yoy,
        tsmc.cumulative_revenue,
        tsmc.announcement_date,
        tsmc.source,
        tsmc.payload_sha256,
    ) == (
        date(2026, 9, 1),
        511857399.0,
        330980920.0,
        54.64861207105231,
        3898726974.0,
        date(2026, 10, 17),
        "mops_t187ap05",
        "abc",
    )
    assert tsmc.details["announcement_basis"] == "release_date"
    assert tsmc.details["備註"] == "因先進製程產品需求增加所致。"


def test_a_blank_percentage_is_no_value_not_zero():
    rows_ = snapshot("TPEx")
    rows_[0]["營業收入-去年同月增減(%)"] = ""
    (first, *_) = sources.parse_monthly_revenue_rows(
        rows_, exchange="TPEx", requested_date=date(2026, 11, 6)
    )
    assert (first.symbol, first.yoy, first.revenue) == ("4442", None, 277084.0)


def test_a_historical_collect_before_the_release_date_reads_no_month():
    assert (
        sources.parse_monthly_revenue_rows(
            snapshot("TWSE"), exchange="TWSE", requested_date=date(2026, 10, 16)
        )
        == []
    )


def _changed(index, **changes):
    rows_ = snapshot("TWSE")
    rows_[index].update(changes)
    return rows_


@pytest.mark.parametrize(
    "payload,message",
    [
        pytest.param([], "non-empty list", id="empty"),
        pytest.param({"data": snapshot("TWSE")}, "non-empty list", id="not-a-list"),
        pytest.param(
            _changed(1, 資料年月="11508"), "share one 資料年月", id="two-months"
        ),
        pytest.param(_changed(0, 資料年月=""), "share one 資料年月", id="no-month"),
        pytest.param(_changed(2, 公司代號="1101"), "1101 twice", id="duplicate"),
        pytest.param(
            _changed(0, 出表日期="1150930"), "出表日期", id="released-in-month"
        ),
        pytest.param(_changed(0, 出表日期=""), "出表日期", id="no-release-date"),
        pytest.param(
            [{**snapshot("TWSE")[0], "公司代號": ""}], "no company", id="no-company"
        ),
    ],
)
def test_a_snapshot_that_cannot_be_read_as_one_month_is_rejected(payload, message):
    with pytest.raises(sources.OfficialDataError, match=message):
        sources.parse_monthly_revenue_rows(
            payload, exchange="TWSE", requested_date=date(2026, 11, 6)
        )


# --- collect (AC-2) -------------------------------------------------------------


class RevenueFetcher(CodedFetcher):
    """The fixture's snapshots (1101 and 7001, August, released 09/03) plus 9998, not an instrument."""

    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url == sources.TPEX_MONTHLY_REVENUE_ENDPOINT:
            return payload + [{**payload[0], "公司代號": "9998"}]
        return payload


@pytest.fixture
def collect_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'collect.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", made)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield made
    engine.dispose()


def test_collect_writes_the_snapshot_month_and_a_rerun_changes_nothing(collect_db):
    first = pipeline.collect(DAY, adapter=combined(RevenueFetcher()))

    assert first["status"] == "success", first
    assert first["noncore_warnings"] == []
    with collect_db() as db:
        stored = rows(db)
        assert set(stored) == {("1101", "2026-08"), ("7001", "2026-08")}
        row = stored[("1101", "2026-08")]
        assert (row.revenue, row.yoy, row.announcement_date, row.source) == (
            1000.0,
            25.0,
            date(2026, 9, 3),
            "mops_t187ap05",
        )
        capture = db.get(RawPayload, row.raw_payload_id)
        assert capture.endpoint == sources.TWSE_MONTHLY_REVENUE_ENDPOINT
        assert capture.ingestion_run_id == first["run_id"]
        run = db.get(IngestionRun, first["run_id"])
        # 9998 is not a collected instrument.
        assert run.metadata_json["monthly_revenues"] == {
            "inserted": 2,
            "outside_universe": 1,
        }
        collected_at = row.collected_at

        raw_payload_id = row.raw_payload_id

    # A same-day collect reuses the finished run; force re-collects the session.
    second = pipeline.collect(DAY, adapter=combined(RevenueFetcher()), force=True)

    assert second["status"] == "success", second
    assert "idempotent_reuse" not in second
    with collect_db() as db:
        run = db.get(IngestionRun, second["run_id"])
        assert run.metadata_json["monthly_revenues"] == {
            "unchanged": 2,
            "outside_universe": 1,
        }
        row = rows(db)[("1101", "2026-08")]
        # Unchanged rows keep the capture their values came from.
        assert (row.collected_at, row.raw_payload_id) == (collected_at, raw_payload_id)
        assert db.scalar(select(func.count()).select_from(MonthlyRevenue)) == 2


def test_a_failed_snapshot_is_a_noncore_warning_and_the_collect_succeeds(collect_db):
    failing = (
        sources.TWSE_MONTHLY_REVENUE_ENDPOINT,
        sources.TPEX_MONTHLY_REVENUE_ENDPOINT,
    )
    result = pipeline.collect(DAY, adapter=combined(OutageFetcher(failing)))

    assert result["status"] == "success", result
    assert result["core_warnings"] == []
    assert [w.split(":")[0] for w in result["noncore_warnings"]] == [
        "TWSE monthly revenue unavailable",
        "TPEx monthly revenue unavailable",
    ]
    with collect_db() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyRevenue)) == 0


def test_an_unreadable_snapshot_writes_nothing_and_is_noncore(collect_db):
    class TwoMonths(RevenueFetcher):
        def __call__(self, url, **kwargs):
            payload = super().__call__(url, **kwargs)
            if url == sources.TWSE_MONTHLY_REVENUE_ENDPOINT:
                return payload + [
                    {**payload[0], "公司代號": "2330", "資料年月": "11507"}
                ]
            return payload

    result = pipeline.collect(DAY, adapter=combined(TwoMonths()))

    assert result["status"] == "success", result
    (warning,) = result["noncore_warnings"]
    assert warning.startswith("TWSE monthly revenue unavailable: OfficialDataError: ")
    with collect_db() as db:
        assert set(rows(db)) == {("7001", "2026-08")}


def test_a_store_failure_is_that_exchanges_noncore_warning(factory):
    records = sources.parse_monthly_revenue_rows(
        snapshot("TWSE"), exchange="TWSE", requested_date=date(2026, 11, 6)
    ) + sources.parse_monthly_revenue_rows(
        snapshot("TPEx"),
        exchange="TPEx",
        requested_date=date(2026, 11, 6),
        payload_sha256="s1",
    )
    warnings: list[str] = []
    with factory() as db:
        identifier = raw(db)
        counts = mr.store_monthly_revenues(
            db,
            records,
            instruments(db),
            {"s1": identifier}.get,  # the TWSE rows have no raw
            warnings,
        )
        db.commit()
        assert counts == {"failed": 3, "inserted": 2}
        assert set(rows(db)) == {("6488", "2026-09"), ("4442", "2026-09")}
    (warning,) = warnings
    assert warning.startswith("TWSE monthly revenue unavailable: ValueError: ")


def test_monthly_revenue_warnings_are_noncore():
    core, noncore = pipeline.split_collect_warnings(
        [
            sources.monthly_revenue_warning("TWSE", sources.OfficialDataError("x")),
            sources.monthly_revenue_warning("TPEx", ValueError("y")),
            "monthly revenue unavailable",
        ]
    )
    assert len(noncore) == 2 and core == ["monthly revenue unavailable"]


def test_a_historical_batch_never_reads_the_snapshots(tmp_path, monkeypatch):
    fetcher = RevenueFetcher()
    adapter = sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher, snapshot_feeds=False),
        sources.TpexAdapter(fetcher, snapshot_feeds=False),
    )
    batch = adapter.fetch(DAY, DAY)
    assert sources.TWSE_MONTHLY_REVENUE_ENDPOINT not in fetcher.calls
    assert sources.TPEX_MONTHLY_REVENUE_ENDPOINT not in fetcher.calls
    assert batch.monthly_revenues == []


# --- the t21sc03 page -----------------------------------------------------------


def test_the_domestic_page_reads_every_company_and_skips_industry_totals():
    parsed = mr.parse_page(page_html("sii", 0), "sii", SEPTEMBER, 0)
    by_symbol = {row.symbol: row for row in parsed}
    assert list(by_symbol) == ["1101", "1102", "2330", "2816", "2884"]
    tsmc = by_symbol["2330"]
    assert (
        tsmc.name,
        tsmc.revenue,
        tsmc.prior_year_revenue,
        tsmc.yoy,
        tsmc.cumulative_revenue,
    ) == ("台積電", 511857399.0, 330980920.0, 54.64, 3898726974.0)
    assert tsmc.cells["備註"] == "因先進製程產品需求增加所致。"


def test_the_foreign_pages_list_ky_and_dr_companies():
    assert [
        row.symbol for row in mr.parse_page(page_html("sii", 1), "sii", SEPTEMBER, 1)
    ] == [
        "1256",
        "9105",
    ]
    assert [
        row.symbol for row in mr.parse_page(page_html("otc", 1), "otc", SEPTEMBER, 1)
    ] == [
        "4442",
        "5543",
    ]


@pytest.mark.parametrize(
    "html,market,month,page,message",
    [
        pytest.param(
            page_html("sii", 0),
            "sii",
            mr.Month(2026, 8),
            0,
            "not the",
            id="other-month",
        ),
        pytest.param(
            page_html("sii", 0), "otc", SEPTEMBER, 0, "not the", id="other-market"
        ),
        pytest.param(
            page_html("sii", 0),
            "sii",
            SEPTEMBER,
            1,
            "no 全部國外上市公司合計",
            id="other-page",
        ),
        pytest.param(
            page_html("sii", 0).replace("當月累計營收", "累計營收", 1),
            "sii",
            SEPTEMBER,
            0,
            "columns changed",
            id="header",
        ),
        pytest.param(
            page_html("sii", 0).replace("<td align=left>台泥</td>", "", 1),
            "sii",
            SEPTEMBER,
            0,
            "malformed row",
            id="short-row",
        ),
        pytest.param(
            page_html("sii", 0).replace(
                "<td align=center>1102</td>", "<td align=center>1101</td>", 1
            ),
            "sii",
            SEPTEMBER,
            0,
            "1101 twice",
            id="duplicate",
        ),
        pytest.param(
            "<html>FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED!</html>",
            "sii",
            SEPTEMBER,
            0,
            "refused",
            id="blocked",
        ),
    ],
)
def test_a_page_that_cannot_be_trusted_is_rejected(html, market, month, page, message):
    with pytest.raises(sources.OfficialDataError, match=message):
        mr.parse_page(html, market, month, page)


def test_fetch_page_decodes_big5_and_retries_a_502(monkeypatch):
    body = page_html("sii", 1).encode("cp950")
    answers = [
        httpx.Response(502, content=b"Unreachable Server"),
        httpx.Response(200, content=body),
    ]
    monkeypatch.setattr(mr.httpx, "get", lambda *args, **kwargs: answers.pop(0))
    monkeypatch.setattr(mr, "_throttle_official_host", lambda url: None)
    monkeypatch.setattr(mr.time, "sleep", lambda seconds: None)

    html = mr.fetch_page(mr.page_url("sii", SEPTEMBER, 1))

    assert answers == []
    assert [row.name for row in mr.parse_page(html, "sii", SEPTEMBER, 1)] == [
        "鮮活果汁-KY",
        "泰金寶-DR",
    ]


def test_page_urls_and_deadlines():
    assert mr.page_url("otc", SEPTEMBER, 1) == (
        "https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_115_9_1.html"
    )
    assert mr.nominal_deadline(mr.Month(2026, 12)) == date(2027, 1, 10)
    assert mr.Month.latest_ended(date(2026, 1, 3)) == mr.Month(2025, 12)
    assert [m.label for m in mr.month_range(mr.Month(2026, 2), 3)] == [
        "2025-12",
        "2026-01",
        "2026-02",
    ]


# --- backfill -----------------------------------------------------------------


def test_backfill_writes_both_markets_and_pages_and_a_rerun_changes_nothing(factory):
    with factory() as db:
        store_calendar(db, [2026])
    fetcher = PageFetcher()

    first = backfill(factory, fetcher, months=1, end=SEPTEMBER)

    assert fetcher.urls == [
        mr.page_url("sii", SEPTEMBER, 0),
        mr.page_url("sii", SEPTEMBER, 1),
        mr.page_url("otc", SEPTEMBER, 0),
        mr.page_url("otc", SEPTEMBER, 1),
    ]
    assert first["status"] == "success", first
    assert (first["requests"], first["inserted"], first["outside_universe"]) == (
        4,
        6,
        5,
    )
    with factory() as db:
        stored = rows(db)
        assert set(stored) == {
            (symbol, "2026-09")
            for symbol in ("1101", "2330", "2884", "1256", "6488", "4442")
        }
        tsmc = stored[("2330", "2026-09")]
        # 10/10 is a Saturday; the deadline rolls to Monday 10/12.
        assert (tsmc.announcement_date, tsmc.source, tsmc.yoy) == (
            date(2026, 10, 12),
            "mops_t21sc03",
            54.64,
        )
        assert tsmc.data_json["announcement_basis"] == "statutory_deadline"
        assert tsmc.data_json["statutory_deadline"] == "2026-10-12"
        assert tsmc.data_json["deadline_calendar"] == "twse_holiday_schedule"
        assert tsmc.data_as_of == "2026-09-30"
        capture = db.get(RawPayload, tsmc.raw_payload_id)
        assert capture.endpoint == mr.page_url("sii", SEPTEMBER, 0)
        run = db.get(IngestionRun, first["run_id"])
        assert run.run_type == "revenue_backfill" and run.status == "success"
        assert set(run.metadata_json["coverage_manifest"]) == {
            "2026-09:sii:0",
            "2026-09:sii:1",
            "2026-09:otc:0",
            "2026-09:otc:1",
        }

    second = backfill(factory, months=1, end=SEPTEMBER)

    assert second["status"] == "success"
    assert (second["changed"], second["unchanged"]) == (0, 6)


def test_backfill_keeps_snapshot_values_and_only_moves_their_date_earlier(factory):
    records = sources.parse_monthly_revenue_rows(
        snapshot("TWSE"),
        exchange="TWSE",
        requested_date=date(2026, 11, 6),
        payload_sha256="s1",
    )
    with factory() as db:
        identifier = raw(db)
        assert mr.store_monthly_revenues(
            db, records, instruments(db), {"s1": identifier}.get, []
        ) == {"inserted": 3}
        db.commit()

    result = backfill(factory, months=1, end=SEPTEMBER)

    # 1101, 2330 and 1256 had snapshot rows; 2884, 6488, 4442 are new.
    assert (result["dated"], result["inserted"]) == (3, 3)
    with factory() as db:
        tsmc = rows(db)[("2330", "2026-09")]
        assert (tsmc.source, tsmc.yoy, tsmc.raw_payload_id) == (
            "mops_t187ap05",
            54.64861207105231,
            identifier,
        )
        assert tsmc.announcement_date == date(2026, 10, 12)
        assert tsmc.data_json["announcement_basis"] == "statutory_deadline"
        assert tsmc.data_json["營業收入-當月營收"] == "511857399"

    # A later snapshot (restamped 出表日期) keeps the earlier date and changes nothing.
    restamped = [{**row, "出表日期": "1151105"} for row in snapshot("TWSE")]
    later = sources.parse_monthly_revenue_rows(
        restamped,
        exchange="TWSE",
        requested_date=date(2026, 11, 6),
        payload_sha256="s2",
    )
    with factory() as db:
        second = raw(db, "s2")
        assert mr.store_monthly_revenues(
            db, later, instruments(db), {"s2": second}.get, []
        ) == {"unchanged": 3}
        db.commit()
    assert backfill(factory, months=1, end=SEPTEMBER)["changed"] == 0


def test_a_snapshot_takes_backfilled_values_and_keeps_the_earlier_date(factory):
    backfill(factory, months=1, end=SEPTEMBER)
    records = sources.parse_monthly_revenue_rows(
        snapshot("TWSE"),
        exchange="TWSE",
        requested_date=date(2026, 11, 6),
        payload_sha256="s1",
    )
    with factory() as db:
        identifier = raw(db)
        assert mr.store_monthly_revenues(
            db, records, instruments(db), {"s1": identifier}.get, []
        ) == {"updated": 3}
        db.commit()
        tsmc = rows(db)[("2330", "2026-09")]
        assert (tsmc.source, tsmc.yoy, tsmc.raw_payload_id) == (
            "mops_t187ap05",
            54.64861207105231,
            identifier,
        )
        # Without a 2026 holiday calendar the weekend-only roll gives 10/12 too.
        assert tsmc.announcement_date == date(2026, 10, 12)
        assert tsmc.data_json["announcement_basis"] == "statutory_deadline"
        assert tsmc.data_json["deadline_calendar"] == "weekend_only"


def test_a_month_before_its_deadline_is_dated_by_the_fetch_day(factory):
    october = mr.Month(2026, 10)
    result = backfill(factory, months=1, end=october)

    assert result["status"] == "success"
    with factory() as db:
        tsmc = rows(db)[("2330", "2026-10")]
        assert tsmc.announcement_date == date(2026, 11, 6)
        assert tsmc.data_json["announcement_basis"] == "first_seen"
        assert tsmc.data_json["statutory_deadline"] == "2026-11-10"


def test_failed_pages_are_partial_and_three_in_a_row_stop_the_run(factory):
    fail = {
        mr.page_url("sii", mr.Month(2026, 8), 1),
        mr.page_url("otc", mr.Month(2026, 8), 0),
        mr.page_url("otc", mr.Month(2026, 8), 1),
    }
    fetcher = PageFetcher(fail)

    result = backfill(factory, fetcher, months=2, end=SEPTEMBER)

    assert result["status"] == "partial"
    assert result["aborted"] == "stopped after 3 failures at 2026-08:otc:1"
    assert len(fetcher.urls) == 4 and len(result["warnings"]) == 3
    with factory() as db:
        assert {key for key in rows(db)} == {
            ("1101", "2026-08"),
            ("2330", "2026-08"),
            ("2884", "2026-08"),
        }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"months": 0},
        {"months": mr.MAX_MONTHS + 1},
        {"months": 1, "end": mr.Month(2026, 11)},
    ],
)
def test_backfill_refuses_before_any_request(factory, kwargs):
    fetcher = PageFetcher()
    with pytest.raises(ValueError):
        backfill(factory, fetcher, **kwargs)
    assert fetcher.urls == []


def test_run_revenue_backfill_reports_a_bad_month(monkeypatch):
    assert mr.run_revenue_backfill(24, "2026-13")["status"] == "failed"


# --- the stock page's as-of filter (AC-2) -----------------------------------------


def test_the_stock_page_hides_a_month_until_its_availability_date(factory):
    with factory() as db:
        store_calendar(db, [2026])
    backfill(factory, months=2, end=SEPTEMBER)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:

            def months(as_of):
                body = client.get(
                    "/api/stocks/TWSE/2330", params={"as_of": as_of}
                ).json()
                return [row["revenue_month"] for row in body["monthly_revenues"]]

            # 115/08's deadline is 9/10 (a Thursday), 115/09's rolls to 10/12.
            assert months("2026-09-09") == []
            assert months("2026-09-10") == ["2026-08"]
            assert months("2026-10-11") == ["2026-08"]
            assert months("2026-10-12") == ["2026-09", "2026-08"]
            body = client.get(
                "/api/stocks/TWSE/2330", params={"as_of": "2026-10-12"}
            ).json()
            assert body["monthly_revenues"][0] == {
                "revenue_month": "2026-09",
                "revenue": 511857399.0,
                "prior_year_revenue": 330980920.0,
                "yoy": 54.64,
                "cumulative_revenue": 3898726974.0,
                "announcement_date": "2026-10-12",
                "announcement_basis": "statutory_deadline",
                "source": "mops_t21sc03",
                "data_as_of": "2026-09-30",
            }
    finally:
        app.dependency_overrides.pop(api_module.get_db, None)
