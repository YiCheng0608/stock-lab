"""Quarterly EPS and revenue backfill from MOPS t163sb04 (#529).

The fixtures are the 115Q2 listed (sii) and OTC pages as fetched on
2026-11-06, trimmed to a few companies per table; the markup is unchanged.
"""

from __future__ import annotations

import json
import socket
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.migrations import upgrade_database
from app.models import FundamentalSnapshot, IngestionRun, Instrument, RawPayload
from worker import pipeline, sources
from worker import quarterly_fundamentals as qf
from worker import trading_calendar

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PAGES = FIXTURES / "mops_t163sb04"
QUARTER_WORDS = {1: "第一季", 2: "第二季", 3: "第三季", 4: "第四季"}
# 2026-11-06 12:00 Taipei: 115Q3 has ended, its deadlines (11/14, 11/29) are ahead.
NOW = datetime(2026, 11, 6, 4, 0)


def page(market: str, quarter: int = 2) -> str:
    html = (PAGES / f"{market}_115_02.html").read_text(encoding="utf-8")
    return html.replace("第二季資料", f"{QUARTER_WORDS[quarter]}資料")


class PageFetcher:
    """Answers the old-site form per market and quarter; records every form."""

    def __init__(self, fail=()):
        self.forms: list[dict[str, str]] = []
        self.fail = set(fail)

    def __call__(self, url, form):
        assert url == qf.ENDPOINT
        self.forms.append(dict(form))
        key = (form["TYPEK"], int(form["year"]) + 1911, int(form["season"]))
        if key in self.fail:
            raise sources.OfficialDataError("fixture outage")
        return page(form["TYPEK"], int(form["season"]))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, frozen_utcnow):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in quarterly fundamental tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    frozen_utcnow.at = NOW
    return frozen_utcnow


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fundamentals.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with made() as db:
        for exchange, symbol in (
            ("TWSE", "2330"),
            ("TWSE", "2801"),
            ("TWSE", "2884"),
            ("TWSE", "2816"),
            ("TPEx", "5864"),
            ("TPEx", "1240"),
        ):
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


def rows_by_symbol(db):
    query = (
        select(Instrument.symbol, FundamentalSnapshot)
        .join(Instrument, Instrument.id == FundamentalSnapshot.instrument_id)
        .order_by(FundamentalSnapshot.period_end)
    )
    result: dict[str, list[FundamentalSnapshot]] = {}
    for symbol, row in db.execute(query).all():
        result.setdefault(symbol, []).append(row)
    return result


def backfill(factory, fetcher=None, **kwargs):
    with factory() as db:
        return qf.backfill_quarterly_fundamentals(
            db, fetcher=fetcher or PageFetcher(), sleep=lambda _s: None, **kwargs
        )


# --- the page: formats, revenue fields, EPS ------------------------------------


def test_each_report_format_reads_the_snapshot_revenue_and_basic_eps():
    rows = {
        row.symbol: row
        for row in qf.parse_report(page("sii"), "sii", qf.Quarter(2026, 2))
    }
    assert {
        symbol: (row.report_format, row.revenue, row.eps)
        for symbol, row in rows.items()
    } == {
        # bank: 利息淨收益 15,221,502 + 利息以外淨損益 10,607,584 (t187ap14_L 營業收入)
        "2801": ("bank", 25_829_086.0, 0.94),
        "2855": ("securities", 17_544_856.0, 6.96),
        "1101": ("general", 71_289_957.0, 0.38),
        "2330": ("general", 2_404_483_690.0, 49.33),
        "2884": ("holding", 53_843_306.0, 1.32),
        # insurance has no revenue line: left empty, never zero
        "2816": ("insurance", None, 7.84),
        "1409": ("other", 22_040_585.0, 1.18),
    }
    assert rows["2330"].cells["公司名稱"] == "台積電"
    otc = qf.parse_report(page("otc"), "otc", qf.Quarter(2026, 2))
    assert {(row.symbol, row.report_format, row.revenue, row.eps) for row in otc} == {
        ("5864", "securities", 5_225_386.0, 9.80),
        ("1240", "general", 1_440_672.0, 2.85),
    }


@pytest.mark.parametrize(
    ("html", "market", "quarter", "message"),
    [
        (page("sii"), "otc", 2, "another market"),
        (page("sii"), "sii", 3, "another quarter"),
        (page("sii").replace("保險服務結果", "新欄位"), "sii", 2, "not recognized"),
        (
            page("sii").replace("基本每股盈餘</th>", "每股盈餘</th>"),
            "sii",
            2,
            "columns changed",
        ),
        (
            "<html><body>FOR SECURITY REASONS, this page can not be accessed</body></html>",
            "sii",
            2,
            "refused",
        ),
        (
            "<html><body><h2>上市公司第二季資料</h2></body></html>",
            "sii",
            2,
            "no report table",
        ),
    ],
)
def test_an_untrustworthy_page_is_refused(html, market, quarter, message):
    with pytest.raises(sources.OfficialDataError, match=message):
        qf.parse_report(html, market, qf.Quarter(2026, quarter))


def test_insurers_before_ifrs17_report_operating_revenue_and_insurance_deadlines(
    factory,
):
    html = (PAGES / "sii_114_02.html").read_text(encoding="utf-8")
    rows = {
        row.symbol: row for row in qf.parse_report(html, "sii", qf.Quarter(2025, 2))
    }
    # 114Q2 still lists insurers with 營業收入, but in a table of their own.
    assert (rows["2816"].report_format, rows["2816"].revenue, rows["2816"].eps) == (
        "insurance_legacy",
        5_154_575.0,
        1.01,
    )
    assert rows["2330"].report_format == "general"
    assert qf.nominal_deadline("insurance_legacy", qf.Quarter(2025, 2)) == date(
        2025, 8, 31
    )


def test_a_page_that_says_no_data_is_an_empty_quarter():
    html = (
        "<html><body><h2>上市公司第三季資料</h2><center>查無資料</center></body></html>"
    )
    assert qf.parse_report(html, "sii", qf.Quarter(2026, 3)) == []


# --- statutory deadline ---------------------------------------------------------


def test_deadlines_follow_the_industry_and_move_off_closed_days(factory):
    q = qf.Quarter
    assert qf.nominal_deadline("general", q(2026, 2)) == date(2026, 8, 14)
    assert qf.nominal_deadline("bank", q(2026, 2)) == date(2026, 8, 31)
    assert qf.nominal_deadline("holding", q(2026, 3)) == date(2026, 11, 29)
    assert qf.nominal_deadline("insurance", q(2026, 1)) == date(2026, 5, 15)
    assert qf.nominal_deadline("holding", q(2025, 4)) == date(2026, 3, 31)
    with factory() as db:
        # 2026-11-14 is a Saturday; no calendar stored: only the weekend moves it.
        assert qf.roll_to_session(db, date(2026, 11, 14)) == (
            date(2026, 11, 16),
            "weekend_only",
        )
        store_calendar(db, [2025, 2026])
        # 2025-05-30 (holding Q1) was the Dragon Boat make-up holiday.
        assert qf.roll_to_session(db, date(2025, 5, 30)) == (
            date(2025, 6, 2),
            "twse_holiday_schedule",
        )
        assert qf.roll_to_session(db, date(2026, 8, 14)) == (
            date(2026, 8, 14),
            "twse_holiday_schedule",
        )


def test_availability_is_the_deadline_or_the_earlier_fetch_date():
    assert qf.availability(date(2026, 8, 14), date(2026, 11, 6)) == (
        date(2026, 8, 14),
        "statutory_deadline",
    )
    assert qf.availability(date(2026, 11, 16), date(2026, 11, 6)) == (
        date(2026, 11, 6),
        "first_seen",
    )


def test_quarters_end_at_the_last_ended_quarter():
    assert qf.Quarter.latest_ended(date(2026, 11, 6)) == qf.Quarter(2026, 3)
    assert qf.Quarter.latest_ended(date(2026, 9, 30)) == qf.Quarter(2026, 2)
    assert [item.label for item in qf.quarter_range(qf.Quarter(2026, 3), 8)] == [
        "2024Q4",
        "2025Q1",
        "2025Q2",
        "2025Q3",
        "2025Q4",
        "2026Q1",
        "2026Q2",
        "2026Q3",
    ]


# --- the snapshot path keeps the first announcement date -------------------------


def snapshot(symbol: str, released: date, eps: float) -> sources.FundamentalRecord:
    return sources.FundamentalRecord(
        symbol=symbol,
        period_end=date(2026, 6, 30),
        fiscal_period="Q2",
        announcement_date=released,
        revenue=1.0,
        eps=eps,
        details={"出表日期": f"115{released:%m%d}"},
    )


# --- backfill runs ------------------------------------------------------------------


def test_backfill_writes_every_quarter_and_a_rerun_changes_nothing(factory):
    fetcher = PageFetcher()
    result = backfill(factory, fetcher, quarters=2, end=qf.Quarter(2026, 2))
    assert result["status"] == "success"
    assert result["requests"] == 4 and len(fetcher.forms) == 4
    assert fetcher.forms[0] == {
        **qf.FORM_FIELDS,
        "TYPEK": "sii",
        "year": "115",
        "season": "01",
    }
    assert [(f["TYPEK"], f["season"]) for f in fetcher.forms] == [
        ("sii", "01"),
        ("otc", "01"),
        ("sii", "02"),
        ("otc", "02"),
    ]
    # 6 companies in the universe x 2 quarters; 1101, 2855, 1409 are not in it.
    assert (result["inserted"], result["outside_universe"]) == (12, 6)
    with factory() as db:
        rows = rows_by_symbol(db)
        assert [(r.fiscal_period, r.announcement_date) for r in rows["2330"]] == [
            ("Q1", date(2026, 5, 15)),
            ("Q2", date(2026, 8, 14)),
        ]
        # A financial holding's Q2 is due 8/31, not the general 8/14.
        assert rows["2884"][1].announcement_date == date(2026, 8, 31)
        q2 = rows["2330"][1]
        assert (q2.revenue, q2.eps, q2.source) == (2_404_483_690.0, 49.33, qf.SOURCE)
        assert q2.data_json["announcement_basis"] == "statutory_deadline"
        assert q2.data_json["statutory_deadline"] == "2026-08-14"
        assert q2.data_json["report_format"] == "general"
        assert rows["2816"][1].revenue is None and rows["2816"][1].eps == 7.84
        raw = db.get(RawPayload, q2.raw_payload_id)
        assert raw.source == qf.RAW_SOURCE and raw.endpoint == qf.ENDPOINT
        stored = json.loads(Path(raw.payload_path).read_text("utf-8"))
        assert stored["form"]["season"] == "02" and "台積電" in stored["html"]
        run = db.get(IngestionRun, result["run_id"])
        assert run.run_type == qf.RUN_TYPE and run.records == 12

    again = backfill(factory, quarters=2, end=qf.Quarter(2026, 2))
    assert again["status"] == "success"
    assert (again["changed"], again["unchanged"]) == (0, 12)
    with factory() as db:
        assert sum(len(v) for v in rows_by_symbol(db).values()) == 12


def test_backfill_keeps_snapshot_rows_and_only_moves_their_date_earlier(factory):
    with factory() as db:
        instruments = {
            (i.exchange, i.symbol): i for i in db.scalars(select(Instrument))
        }
        pipeline._upsert_fundamental(
            db, snapshot("2330", date(2026, 10, 30), 49.33), instruments, None
        )
        db.commit()
    result = backfill(factory, quarters=1, end=qf.Quarter(2026, 2))
    assert result["dated"] == 1 and result["inserted"] == 5
    with factory() as db:
        (row,) = rows_by_symbol(db)["2330"]
        # Values and source stay the snapshot's; no second Q2 row.
        assert (row.source, row.revenue, row.eps) == ("mops_fundamental", 1.0, 49.33)
        assert row.announcement_date == date(2026, 8, 14)
        assert row.data_json["出表日期"] == "1151030"
        assert row.data_json["announcement_basis"] == "statutory_deadline"
    # A later snapshot keeps the earlier date and its basis.
    with factory() as db:
        instruments = {
            (i.exchange, i.symbol): i for i in db.scalars(select(Instrument))
        }
        pipeline._upsert_fundamental(
            db, snapshot("2330", date(2026, 11, 5), 49.33), instruments, None
        )
        db.commit()
        (row,) = rows_by_symbol(db)["2330"]
        assert row.announcement_date == date(2026, 8, 14)
        assert row.data_json == {
            "出表日期": "1151105",
            "announcement_basis": "statutory_deadline",
            "statutory_deadline": "2026-08-14",
            "deadline_calendar": "weekend_only",
        }
    again = backfill(factory, quarters=1, end=qf.Quarter(2026, 2))
    assert again["changed"] == 0


def test_a_rerun_after_the_calendar_is_loaded_corrects_the_deadline(factory):
    backfill(factory, quarters=1, end=qf.Quarter(2025, 1))
    with factory() as db:
        row = rows_by_symbol(db)["2884"][0]
        assert (row.announcement_date, row.data_json["deadline_calendar"]) == (
            date(2025, 5, 30),
            "weekend_only",
        )
        store_calendar(db, [2025])
    again = backfill(factory, quarters=1, end=qf.Quarter(2025, 1))
    # Every row records the calendar now used; only the holding company's
    # deadline fell on the make-up holiday and moves.
    assert (again["updated"], again["changed"]) == (6, 6)
    with factory() as db:
        rows = rows_by_symbol(db)
        assert (
            rows["2884"][0].announcement_date,
            rows["2884"][0].data_json["deadline_calendar"],
        ) == (date(2025, 6, 2), "twse_holiday_schedule")
        assert rows["2330"][0].announcement_date == date(2025, 5, 15)


def test_a_quarter_before_its_deadline_is_available_from_the_fetch_date(factory):
    result = backfill(factory, quarters=1, end=qf.Quarter(2026, 3))
    assert result["status"] == "success"
    with factory() as db:
        row = rows_by_symbol(db)["2330"][0]
        assert row.fiscal_period == "Q3"
        assert row.announcement_date == date(2026, 11, 6)
        assert row.data_json["announcement_basis"] == "first_seen"
        assert row.data_json["statutory_deadline"] == "2026-11-16"


def test_a_failed_market_quarter_is_partial_and_the_rest_is_stored(factory):
    result = backfill(
        factory,
        PageFetcher(fail={("otc", 2026, 2)}),
        quarters=1,
        end=qf.Quarter(2026, 2),
    )
    assert result["status"] == "partial"
    assert result["quarters"]["2026Q2:otc"]["status"] == "failed"
    assert result["quarters"]["2026Q2:sii"]["inserted"] == 4
    with factory() as db:
        assert "5864" not in rows_by_symbol(db)


def test_backfill_stops_after_consecutive_failures(factory):
    fail = {
        (m, y, s) for m in ("sii", "otc") for y in (2025, 2026) for s in (1, 2, 3, 4)
    }
    fetcher = PageFetcher(fail=fail)
    result = backfill(factory, fetcher, quarters=4, end=qf.Quarter(2026, 2))
    assert result["status"] == "partial"
    assert len(fetcher.forms) == qf.ABORT_AFTER_FAILURES
    assert result["aborted"].startswith("stopped after 3 failures")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quarters": 0},
        {"quarters": qf.MAX_QUARTERS + 1},
        {"quarters": 1, "end": qf.Quarter(2026, 4)},
    ],
)
def test_backfill_refuses_before_any_request(factory, kwargs):
    fetcher = PageFetcher()
    with pytest.raises(ValueError):
        backfill(factory, fetcher, **kwargs)
    assert fetcher.forms == []


# --- the stock page's as-of filter -------------------------------------------------


def test_the_stock_page_hides_a_quarter_until_its_availability_date(factory):
    backfill(factory, quarters=1, end=qf.Quarter(2026, 2))

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:

            def periods(symbol, as_of):
                body = client.get(
                    f"/api/stocks/TWSE/{symbol}", params={"as_of": as_of}
                ).json()
                return [row["fiscal_period"] for row in body["fundamentals"]]

            assert periods("2330", "2026-08-13") == []
            assert periods("2330", "2026-08-14") == ["Q2"]
            # The holding company's Q2 deadline is 8/31.
            assert periods("2884", "2026-08-14") == []
            assert periods("2884", "2026-08-31") == ["Q2"]
    finally:
        app.dependency_overrides.pop(api_module.get_db, None)
