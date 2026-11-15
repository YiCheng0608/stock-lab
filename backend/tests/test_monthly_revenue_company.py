"""Monthly revenue of delisted and transferred companies in the research database (Issue #782).

The single-company page fixtures are the #781 AC-2 probe's answers
(requests 1 and 2: 2384 勝華, still 公開發行; 2475 華映, not), trimmed of
their trailing script and blank space.  The tests compare the parsed values
with the page's own cells instead of spelling the amounts out.
"""

from __future__ import annotations

import json
import socket
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import IngestionRun, Instrument, MarketBar, MonthlyRevenue, RawPayload
from app.raw_paths import payload_file
from worker import monthly_revenue_company as mc
from worker import sources
from worker.monthly_revenue import Month

PAGES = Path(__file__).resolve().parent / "fixtures" / "mops_t05st10"
FOUND_HTML = (PAGES / "2384_103_06.html").read_text(encoding="utf-8")
NOT_PUBLIC_HTML = (PAGES / "2475_103_06_not_public.html").read_text(encoding="utf-8")
JUNE_2014 = Month(2014, 6)
# 2026-11-06 12:00 Taipei: outside the quiet hours.
NOW = datetime(2026, 11, 6, 4, 0)


def found_page(code: str, month: Month) -> str:
    """The 2384 page as the answer for ``code`` and ``month``."""

    roc = f"{month.year - 1911}{month.month:02d}"
    return (
        FOUND_HTML.replace("value='2384'", f"value='{code}'")
        .replace("value='10306'", f"value='{roc}'")
        .replace("民國103年06月", f"民國{month.year - 1911}年{month.month:02d}月")
    )


def not_public_page(code: str) -> str:
    return NOT_PUBLIC_HTML.replace("該 2475 公開", f"該 {code} 公開")


class Fetcher:
    """Answers each form by its code: ``found``, ``not_public`` or an error."""

    def __init__(self, answers: dict[str, str]):
        self.answers = answers
        self.forms: list[dict[str, str]] = []

    def __call__(self, form):
        self.forms.append(form)
        code = form["co_id"]
        month = Month(int(form["year"]) + 1911, int(form["month"]))
        answer = self.answers[code]
        if answer == "found":
            return found_page(code, month).encode("utf-8")
        if answer == "not_public":
            return not_public_page(code).encode("utf-8")
        if answer == "empty":
            return b""
        raise sources.OfficialDataError(answer)

    @property
    def asked(self) -> list[tuple[str, str]]:
        return [
            (form["co_id"], f"{form['year']}/{form['month']}") for form in self.forms
        ]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, frozen_utcnow):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in company revenue tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    frozen_utcnow.at = NOW
    return frozen_utcnow


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def instrument(db, exchange, symbol, name, status, first=None, last=None):
    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=name,
        instrument_type="stock",
        status=status,
    )
    db.add(item)
    db.flush()
    for day in sorted({first, last} - {None}):
        db.add(
            MarketBar(
                instrument_id=item.id, trading_date=day, close=10.0, adj_close=10.0
            )
        )
    db.flush()
    return item


def revenue_row(db, item, month: Month, revenue=100.0, raw_id=None):
    if raw_id is None:
        raw = RawPayload(source="mops", endpoint="t21sc03", sha256="s")
        db.add(raw)
        db.flush()
        raw_id = raw.id
    row = MonthlyRevenue(
        instrument_id=item.id,
        revenue_month=month.first_day,
        revenue=revenue,
        prior_year_revenue=90.0,
        yoy=11.11,
        cumulative_revenue=revenue,
        announcement_date=month.next().first_day + timedelta(days=9),
        source="mops_t21sc03",
        raw_payload_id=raw_id,
        data_json={"TYPEK": "sii", "announcement_basis": "statutory_deadline"},
        data_as_of=month.last_day.isoformat(),
    )
    db.add(row)
    db.flush()
    return row


def months_of(db, item) -> dict[str, MonthlyRevenue]:
    return {
        row.revenue_month.strftime("%Y-%m"): row
        for row in db.scalars(
            select(MonthlyRevenue).where(MonthlyRevenue.instrument_id == item.id)
        )
    }


# --- months -------------------------------------------------------------------


def test_the_months_run_from_a_year_before_the_first_bar_to_the_last():
    months = mc.revenue_months(date(2017, 5, 2), date(2019, 3, 14), date(2026, 11, 6))
    assert months[0] == Month(2016, 5)  # LOOKBACK_MONTHS before 2017-05
    assert months[-1] == Month(2019, 3)  # the last bar's month
    assert len(months) == 12 + 23


def test_the_months_start_no_earlier_than_2013_01():
    months = mc.revenue_months(date(2013, 6, 3), date(2014, 1, 6), date(2026, 11, 6))
    assert months[0] == mc.FIRST_MONTH == Month(2013, 1)
    assert months[-1] == Month(2014, 1)


def test_the_months_stop_at_the_last_month_that_has_ended():
    months = mc.revenue_months(date(2026, 1, 5), date(2026, 11, 5), date(2026, 11, 6))
    assert months[-1] == Month(2026, 10)


# --- the single-company page --------------------------------------------------


def test_the_2384_page_is_found_and_its_values_are_the_tables():
    page = mc.parse_company_page(FOUND_HTML, "2384", JUNE_2014)
    assert page.kind == mc.FOUND
    assert page.name == "勝華科技"
    assert page.company_kind == "公開發行公司"
    cells = page.cells
    assert set(cells) == {key for _label, key in mc.ROWS} | {"備註"}
    assert page.revenue == sources.parse_number(cells["本月"])
    assert page.prior_year_revenue == sources.parse_number(cells["去年同期"])
    assert page.cumulative_revenue == sources.parse_number(cells["本年累計"])
    assert page.yoy == sources.parse_number(cells["本月增減百分比"])
    # The table is consistent with itself: the change is this year less last.
    change = sources.parse_number(cells["本月增減金額"])
    assert page.revenue - page.prior_year_revenue == pytest.approx(change)
    total_change = sources.parse_number(cells["累計增減金額"])
    assert page.cumulative_revenue - sources.parse_number(
        cells["去年累計"]
    ) == pytest.approx(total_change)


def test_a_company_no_longer_public_is_told_apart():
    page = mc.parse_company_page(NOT_PUBLIC_HTML, "2475", JUNE_2014)
    assert page.kind == mc.NOT_PUBLIC
    assert page.revenue is None


def test_a_not_public_answer_for_another_code_is_not_this_ones():
    with pytest.raises(sources.OfficialDataError, match="no revenue table"):
        mc.parse_company_page(NOT_PUBLIC_HTML, "2888", JUNE_2014)


def test_a_page_with_no_filing_is_no_data():
    html = "<html><body><div id='div01'><center><h3>查無資料！</h3></div></body></html>"
    assert mc.parse_company_page(html, "2384", JUNE_2014).kind == mc.NO_DATA


@pytest.mark.parametrize(
    "html, code, month, message",
    [
        (FOUND_HTML, "2384", Month(2014, 7), "answered"),
        (FOUND_HTML, "2330", JUNE_2014, "answered"),
        (
            FOUND_HTML.replace("民國103年06月", "民國103年07月"),
            "2384",
            JUNE_2014,
            "does not print",
        ),
        (
            FOUND_HTML.replace("<TH class='tblHead'>去年同期</TH>", "<TH>上月</TH>"),
            "2384",
            JUNE_2014,
            "columns changed",
        ),
        (FOUND_HTML.replace("公司提供", ""), "2384", JUNE_2014, "does not name"),
        ("<html>查詢過於頻繁</html>", "2384", JUNE_2014, "refused"),
        ("<html><body>系統忙碌</body></html>", "2384", JUNE_2014, "no revenue table"),
    ],
)
def test_a_page_that_cannot_be_trusted_is_rejected(html, code, month, message):
    with pytest.raises(sources.OfficialDataError, match=message):
        mc.parse_company_page(html, code, month)


@pytest.mark.parametrize(
    "one, other, same",
    [
        ("勝華", "勝華科技", True),
        ("台境*", "台境", True),
        ("華映", "勝華科技", False),
        ("", "勝華科技", False),
    ],
)
def test_same_company(one, other, same):
    assert mc.same_company(one, other) is same


def test_the_form_and_the_resume_key():
    form = mc.roc_form("2384", Month(2013, 1))
    assert (form["co_id"], form["year"], form["month"], form["TYPEK"]) == (
        "2384",
        "102",
        "01",
        "all",
    )
    assert mc.company_endpoint("2384", Month(2013, 1)).endswith(
        "?co_id=2384&year=102&month=01"
    )


@pytest.mark.parametrize(
    "moment, quiet",
    [
        (datetime(2026, 11, 6, 12, 29), False),  # 20:29 Taipei
        (datetime(2026, 11, 6, 12, 30), True),  # 20:30
        (datetime(2026, 11, 6, 15, 29), True),  # 23:29
        (datetime(2026, 11, 6, 15, 30), False),  # 23:30
        (datetime(2026, 11, 6, 0, 0), True),  # 08:00
        (datetime(2026, 11, 6, 1, 0), False),  # 09:00
    ],
)
def test_quiet_hours(moment, quiet):
    assert mc.quiet_hour(moment) is quiet


# --- transfers ----------------------------------------------------------------


def transfer_db(factory, otc_name="直得", listed_name="直得", listed_first=None):
    """1597: TPEx bars 2017-05-02～2018-12-21, TWSE from 2018-12-24."""

    with factory() as db:
        old = instrument(
            db,
            "TPEx",
            "1597",
            otc_name,
            "transferred",
            date(2017, 5, 2),
            date(2018, 12, 21),
        )
        new = instrument(
            db,
            "TWSE",
            "1597",
            listed_name,
            "active",
            listed_first or date(2018, 12, 24),
            date(2026, 11, 5),
        )
        month = Month(2015, 1)
        while month <= Month(2026, 10):
            revenue_row(db, new, month)
            month = month.next()
        db.commit()
        return old.id, new.id


def test_transfers_copy_the_old_listings_months_and_keep_the_new_ones(factory):
    old_id, new_id = transfer_db(factory)
    with factory() as db:
        planned = mc.transfer_revenues(db)
        assert planned["inserted"] == 12 + 20  # 2016-05～2018-12
        assert not db.scalars(
            select(MonthlyRevenue).where(MonthlyRevenue.instrument_id == old_id)
        ).all()
        assert db.scalar(select(IngestionRun.id)) is None
    with factory() as db:
        result = mc.transfer_revenues(db, apply=True)
        assert result["inserted"] == 32 and not result["skipped"]
        old, new = db.get(Instrument, old_id), db.get(Instrument, new_id)
        copied, kept = months_of(db, old), months_of(db, new)
        assert min(copied) == "2016-05" and max(copied) == "2018-12"
        assert len(kept) == 142  # the TWSE rows stay
        row, origin = copied["2017-03"], kept["2017-03"]
        assert row.source == mc.SOURCE_TRANSFER
        assert (row.revenue, row.announcement_date, row.raw_payload_id) == (
            origin.revenue,
            origin.announcement_date,
            origin.raw_payload_id,
        )
        assert row.data_json["copied_from"] == {
            "instrument_id": new_id,
            "exchange": "TWSE",
            "source": "mops_t21sc03",
        }
        assert row.data_json["TYPEK"] == "sii"
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == mc.RUN_TRANSFER)
        )
        assert run.status == "success" and run.records == 32
    with factory() as db:
        again = mc.transfer_revenues(db, apply=True)
        assert (again["inserted"], again["updated"], again["unchanged"]) == (0, 0, 32)
        # A later correction of the TWSE month reaches the copy on the next run.
        months_of(db, db.get(Instrument, new_id))["2017-03"].revenue = 123.0
        db.commit()
    with factory() as db:
        assert mc.transfer_revenues(db, apply=True)["updated"] == 1
        assert months_of(db, db.get(Instrument, old_id))["2017-03"].revenue == 123.0


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"listed_name": "直得科技"}, "the names differ"),
        ({"listed_first": date(2019, 3, 1)}, "do not meet"),
    ],
)
def test_a_transfer_that_is_not_one_company_is_skipped(factory, kwargs, reason):
    old_id, _new_id = transfer_db(factory, **kwargs)
    with factory() as db:
        result = mc.transfer_revenues(db, apply=True)
        assert result["inserted"] == 0
        assert [item["symbol"] for item in result["skipped"]] == ["1597"]
        assert reason in result["skipped"][0]["skipped"]
        assert not months_of(db, db.get(Instrument, old_id))


# --- classification and backfill ----------------------------------------------


def delisted_db(factory):
    """2384 勝華 (found), 2475 華映 (not public), 9999 named 別家 (its page names 勝華科技)."""

    with factory() as db:
        ids = {
            symbol: instrument(db, exchange, symbol, name, "delisted", first, last).id
            for exchange, symbol, name, first, last in (
                ("TWSE", "2384", "勝華", date(2017, 5, 2), date(2018, 2, 26)),
                ("TWSE", "2475", "華映", date(2017, 8, 1), date(2019, 5, 10)),
                ("TPEx", "9999", "別家", date(2017, 5, 2), date(2017, 12, 29)),
            )
        }
        # Before 2013 and without bars: not asked.
        instrument(
            db,
            "TWSE",
            "1111",
            "老公司",
            "delisted",
            date(2010, 1, 4),
            date(2012, 6, 29),
        )
        instrument(db, "TWSE", "2222", "無日線", "delisted")
        db.commit()
        return ids


ANSWERS = {"2384": "found", "2475": "not_public", "9999": "found"}


def classify(factory, fetcher, **kwargs):
    with factory() as db:
        return mc.classify_companies(
            db, fetcher=fetcher, sleep=lambda _s: None, **kwargs
        )


def backfill(factory, fetcher, **kwargs):
    with factory() as db:
        return mc.backfill_companies(
            db, fetcher=fetcher, sleep=lambda _s: None, **kwargs
        )


def test_classify_asks_once_per_company_and_writes_the_found_month(factory):
    ids = delisted_db(factory)
    with factory() as db:
        planned = mc.classify_companies(db, plan=True)
        assert (planned["companies"], planned["requests"]) == (3, 3)
        assert planned["skipped"] == {"no_bars": 1, "before_first_month": 1}
    fetcher = Fetcher(ANSWERS)
    result = classify(factory, fetcher)
    assert result["status"] == "success"
    assert sorted(fetcher.asked) == [
        ("2384", "107/02"),
        ("2475", "108/05"),
        ("9999", "106/12"),
    ]
    assert result["classes"] == {"found": 1, "name_mismatch": 1, "not_public": 1}
    assert result["listed"] == {
        "name_mismatch": ["TPEx:9999"],
        "not_public": ["TWSE:2475"],
    }
    with factory() as db:
        found = months_of(db, db.get(Instrument, ids["2384"]))
        assert list(found) == ["2018-02"]  # written with the classifying request
        row = found["2018-02"]
        assert row.source == mc.SOURCE_COMPANY
        assert row.data_json["公司名稱"] == "勝華科技"
        assert row.data_json["announcement_basis"] == "statutory_deadline"
        assert row.announcement_date == date(2018, 3, 12)  # 03-10 is a Saturday
        raw = db.get(RawPayload, row.raw_payload_id)
        assert raw.endpoint == mc.company_endpoint("2384", Month(2018, 2))
        kept = json.loads(payload_file(raw.payload_path).read_text("utf-8"))
        assert kept["method"] == "POST" and kept["form"]["co_id"] == "2384"
        # A page naming another company writes nothing (decision 6894566253 3).
        assert not months_of(db, db.get(Instrument, ids["9999"]))
        assert not months_of(db, db.get(Instrument, ids["2475"]))
    # The kept answers are read again, not asked again.
    again = Fetcher(ANSWERS)
    assert classify(factory, again)["requests"] == 0 and again.forms == []
    with factory() as db:
        assert mc.classify_companies(db, plan=True)["requests"] == 0


def test_backfill_asks_the_rest_of_the_found_companys_months(factory):
    ids = delisted_db(factory)
    classify(factory, Fetcher(ANSWERS))
    with factory() as db:
        planned = mc.backfill_companies(db, plan=True)
    # 2016-05～2018-02 is 22 months; 2018-02 came with the classification.
    assert planned["classes"] == {"found": 1, "name_mismatch": 1, "not_public": 1}
    assert (planned["companies"], planned["months"], planned["requests"]) == (1, 21, 21)
    fetcher = Fetcher(ANSWERS)
    result = backfill(factory, fetcher)
    assert result["status"] == "success" and result["inserted"] == 21
    assert {code for code, _month in fetcher.asked} == {"2384"}
    assert ("2384", "107/02") not in fetcher.asked  # not asked a second time
    with factory() as db:
        found = months_of(db, db.get(Instrument, ids["2384"]))
        assert min(found) == "2016-05" and max(found) == "2018-02" and len(found) == 22
    again = Fetcher(ANSWERS)
    assert backfill(factory, again)["requests"] == 0 and again.forms == []


def test_backfill_waits_for_a_company_not_classified(factory):
    delisted_db(factory)
    with factory() as db:
        planned = mc.backfill_companies(db, plan=True)
    assert planned["classes"] == {"unclassified": 3}
    assert planned["requests"] == 0


def test_a_page_naming_another_company_in_backfill_is_skipped(factory):
    ids = delisted_db(factory)
    classify(factory, Fetcher(ANSWERS))
    with factory() as db:
        db.get(Instrument, ids["2384"]).name = "勝華"
        db.commit()

    class Renamed(Fetcher):
        def __call__(self, form):
            return (
                super().__call__(form).replace("勝華科技".encode(), "別的公司".encode())
            )

    result = backfill(factory, Renamed(ANSWERS))
    assert result["name_mismatch"] == 21 and "inserted" not in result
    with factory() as db:
        assert list(months_of(db, db.get(Instrument, ids["2384"]))) == ["2018-02"]


@pytest.mark.parametrize("failure", ["empty", "official endpoint answered 503"])
def test_three_failures_in_a_row_stop_the_run(factory, failure):
    delisted_db(factory)
    fetcher = Fetcher({"2384": failure, "2475": failure, "9999": failure})
    result = classify(factory, fetcher)
    assert result["status"] == "partial"
    assert result["failed"] == 3 and len(fetcher.forms) == 3
    assert result["aborted"].startswith("stopped after 3 failures")
    with factory() as db:
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == mc.RUN_CLASSIFY)
        )
        assert run.status == "partial" and run.error == result["aborted"]


def test_a_failure_is_asked_again_on_the_next_run(factory):
    delisted_db(factory)
    first = classify(factory, Fetcher({**ANSWERS, "2475": "empty"}))
    assert first["status"] == "partial" and first["failed"] == 1
    fetcher = Fetcher(ANSWERS)
    assert classify(factory, fetcher)["status"] == "success"
    assert fetcher.asked == [("2475", "108/05")]


def test_requests_keep_the_interval(factory):
    delisted_db(factory)
    waits: list[float] = []
    with factory() as db:
        mc.classify_companies(db, fetcher=Fetcher(ANSWERS), sleep=waits.append)
    assert waits == [mc.INTERVAL_SECONDS] * 2 and mc.INTERVAL_SECONDS >= 5


def test_max_requests_stops_and_the_rerun_goes_on(factory):
    delisted_db(factory)
    first = classify(factory, Fetcher(ANSWERS), max_requests=2)
    assert first["status"] == "partial" and first["requests"] == 2
    assert "--max-requests 2" in first["aborted"]
    rest = Fetcher(ANSWERS)
    assert classify(factory, rest)["requests"] == 1


def test_quiet_hours_stop_before_any_request(factory, isolated):
    delisted_db(factory)
    isolated.at = datetime(2026, 11, 6, 13, 0)  # 21:00 Taipei
    fetcher = Fetcher(ANSWERS)
    result = classify(factory, fetcher)
    assert result["status"] == "partial" and fetcher.forms == []
    assert result["aborted"].startswith("quiet hours")


def test_the_commands_refuse_a_database_without_the_research_marker(tmp_path):
    db_path = tmp_path / "stock.db"
    for run in (
        lambda: mc.run_revenue_transfers(True, db_path),
        lambda: mc.run_revenue_company_classify(False, None, db_path),
        lambda: mc.run_revenue_company_backfill(False, None, db_path),
    ):
        result = run()
        assert result["status"] == "refused" and "research-db.json" in result["error"]
    (tmp_path / "research-db.json").write_text('{"purpose": "production"}\n')
    assert mc.refusal(db_path) is not None
    (tmp_path / "research-db.json").write_text('{"purpose": "research_history"}\n')
    assert mc.refusal(db_path) is None


def test_the_cli_exits_2_when_refused(tmp_path, monkeypatch, capsys):
    from worker import cli

    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "stock.db")
    # Without --apply: no maintenance hold, the refusal alone decides.
    monkeypatch.setattr("sys.argv", ["worker.cli", "revenue", "transfers"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert '"refused"' in capsys.readouterr().out
