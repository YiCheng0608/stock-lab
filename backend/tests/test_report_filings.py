"""Quarterly report upload times from the TWSE e-book page t57sb01 (Issue #1100).

The fixtures in ``fixtures/t57sb01`` are pages the #1096 evaluation stored on
2026-11-27 (``stock-lab-data/evidence/1096/raw``) and the 「查無所需資料」 probe of
#1100 (6669 / 102, 17:23 Taipei), saved as UTF-8 with LF and no trailing blanks;
the tests encode them back to Big5 as the server sends them.  The sha256 of each
source file is in the PR description.
"""

from __future__ import annotations

import json
import socket
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    FinancialReportFiling,
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    RawPayload,
)
from worker import report_filings as rf
from worker import sources

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "t57sb01"
NOW = datetime(2026, 11, 27, 6, 0)  # 14:00 Taipei
TAIPEI = timezone(timedelta(hours=8))


def page(name: str) -> bytes:
    return (FIXTURES / name).read_text(encoding="utf-8").encode(rf.ENCODING)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, frozen_utcnow):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in t57sb01 tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    frozen_utcnow.at = NOW
    return frozen_utcnow


# --- the page -------------------------------------------------------------------


def test_a_general_company_page_reads_every_file():
    result = rf.parse_page(page("general_8067_102.html"), rf.Target("8067", 2013))
    assert result.company == "志旭"
    assert [(row.quarter, row.report_kind, row.file_name) for row in result.rows] == [
        (1, "IFRSs合併財報", "201301_8067_AI1.pdf"),
        (2, "IFRSs合併財報", "201302_8067_AI1.pdf"),
        (3, "IFRSs合併財報", "201303_8067_AI1.pdf"),
        (4, "IFRSs合併財報", "201304_8067_AI1.pdf"),
        (4, "IFRSs個體財報", "201304_8067_AI3.pdf"),
    ]
    first = result.rows[0]
    assert first.uploaded_at == datetime(2013, 5, 14, 15, 53, 36)
    assert first.file_size == 340_134
    assert first.correction == "無"
    assert first.period_end == date(2013, 3, 31)
    # The Q4 report is uploaded the next year, on the year's page.
    assert result.rows[4].uploaded_at == datetime(2014, 4, 1, 9, 44, 33)


def test_a_financial_holding_page_with_check2858_is_its_own_table():
    result = rf.parse_page(page("holding_2888_113.html"), rf.Target("2888", 2024))
    assert result.company == "新光金"
    assert len(result.rows) == 8
    kinds = {row.report_kind for row in result.rows}
    assert kinds == {"IFRSs合併財報", "IFRSs英文版-合併財報"}
    q2 = next(row for row in result.rows if row.file_name == "202402_2888_AI1.pdf")
    # The company's latest correction: the 詳細資料 link of t56sb31_q1.
    assert q2.correction.startswith("http://mopsov.twse.com.tw/mops/web/t56sb31_q1?")
    assert "YEAR_SEASON=202402" in q2.correction


def test_the_form_always_asks_with_check2858():
    form = rf.request_form(rf.Target("2888", 2024))
    assert form == {
        "step": "1",
        "colorchg": "1",
        "co_id": "2888",
        "year": "113",
        "mtype": "A",
        "check2858": "Y",
    }


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("rate_limited.html", "blocked: 查詢過量"),
        ("menu_2888_113.html", "unexpected: subsidiary menu"),
    ],
)
def test_a_rate_limit_or_a_menu_is_a_failure_never_an_empty_page(name, reason):
    assert rf.classify(200, page(name)) == reason
    with pytest.raises(rf.LayoutError):
        rf.parse_page(page(name), rf.Target("2888", 2024))


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (403, b"", "blocked: HTTP 403"),
        (429, b"x", "blocked: HTTP 429"),
        (500, b"x", "HTTP 500"),
        (200, b"", "empty answer"),
        (200, "<html>維護中</html>".encode(rf.ENCODING), "unexpected page"),
        (None, b"", "no answer"),
    ],
)
def test_other_failures(status, body, reason):
    assert rf.classify(status, body) == reason


def test_no_data_is_an_answered_empty_year():
    body = page("no_data.html")
    assert rf.classify(200, body) is None
    assert rf.parse_page(body, rf.Target("6669", 2013)) == rf.Page(None, ())


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "<td align='center'>8067</td><td align='center'>102 年 第二季</td>",
            "<td align='center'>8068</td><td align='center'>102 年 第二季</td>",
            "code",
        ),
        ("102 年 第二季", "101 年 第二季", "資料年度"),
        (
            '>IFRSs合併財報</td><td align=\'center\'>&nbsp;</td><td><a href=\'javascript:readfile2("A","8067","201302',
            '>IFRSs精簡財報</td><td align=\'center\'>&nbsp;</td><td><a href=\'javascript:readfile2("A","8067","201302',
            "unknown 資料細節說明",
        ),
        ("102/08/13 14:10:26", "102/02/30 14:10:26", "上傳日期"),
        (">201302_8067_AI1.pdf<", ">201303_8067_AI1.pdf<", "file name"),
    ],
)
def test_a_row_that_does_not_read_fails_the_page(old, new, message):
    text = (FIXTURES / "general_8067_102.html").read_text(encoding="utf-8")
    assert old in text
    body = text.replace(old, new, 1).encode(rf.ENCODING)
    with pytest.raises(rf.LayoutError, match=message):
        rf.parse_page(body, rf.Target("8067", 2013))


def test_the_notes_below_the_table_are_not_rows():
    # The holding page ends with a table of notes of two cells a row.
    result = rf.parse_page(page("holding_2888_113.html"), rf.Target("2888", 2024))
    assert all(row.file_name.endswith(".pdf") for row in result.rows)


# --- filing date ----------------------------------------------------------------


def row(kind, moment, quarter=4, name=None):
    return rf.FilingRow(
        symbol="1314",
        year=2013,
        quarter=quarter,
        report_kind=kind,
        file_name=name or f"{kind}.pdf",
        file_size=1,
        uploaded_at=moment,
        correction="無",
    )


def test_the_filing_date_is_the_earliest_chinese_statement():
    rows = [
        row("IFRSs個體財報", datetime(2014, 3, 31, 14, 56)),
        row("IFRSs合併財報", datetime(2014, 3, 31, 14, 17)),
        row("IFRSs英文版-合併財報", datetime(2014, 3, 1)),
    ]
    assert rf.filing_date(rows) == datetime(2014, 3, 31, 14, 17)


def test_a_supplementary_report_uploaded_first_is_no_filing_date():
    # Decision 7214693152 point 3: the quarter's figures are public with the
    # statements, not with an earlier 關係企業合併報表.
    rows = [
        row("關係企業合併報表", datetime(2014, 3, 20, 9, 0)),
        row("外國企業實際營運地之個體財報", datetime(2014, 3, 21, 9, 0)),
        row("IFRSs合併財報", datetime(2014, 3, 31, 14, 17)),
    ]
    assert rf.filing_date(rows) == datetime(2014, 3, 31, 14, 17)


def test_an_individual_report_counts_and_a_restatement_only_quarter_is_empty():
    assert rf.filing_date([row("IFRSs個別財報", datetime(2013, 5, 13, 11, 7))]) == (
        datetime(2013, 5, 13, 11, 7)
    )
    assert rf.filing_date([row("IFRSs合併財報(重編)", datetime(2014, 6, 1))]) is None
    assert rf.filing_date([]) is None


# --- names ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("db_name", "page_name", "same"),
    [
        ("志旭", "志旭", True),
        ("瑞傳", "瑞傳科技", True),
        ("聯嘉光電", "聯嘉", True),
        ("F-聯德", "聯德控股-KY", True),
        ("億而得-創", "億而得", True),
        ("*佳醫", "佳醫", True),
        ("南璋", "福格創新", False),
        ("中壽", "凱基人壽", False),
        # Decision 7214693152 point 4: under 2 characters never matches.
        ("台", "台積電", False),
        ("F-", "F-KY", False),
    ],
)
def test_names(db_name, page_name, same):
    assert rf.names_match(db_name, page_name) is same


def test_accepted_names_need_every_field(tmp_path):
    path = tmp_path / "accept.json"
    path.write_text(json.dumps([{"symbol": "4712", "page_name": "福格創新"}]))
    with pytest.raises(rf.Refused):
        rf.read_accepted_names(str(path))
    path.write_text(
        json.dumps(
            [
                {
                    "symbol": "4712",
                    "page_name": "福格創新",
                    "db_name": "南璋",
                    "reason": "改名",
                }
            ]
        )
    )
    assert rf.read_accepted_names(str(path)) == {("4712", "福格創新", "南璋")}


# --- quiet hours ----------------------------------------------------------------


def taipei(hour, minute=0, day=27):
    return datetime(2026, 11, day, hour, minute, tzinfo=TAIPEI)


@pytest.mark.parametrize(
    ("moment", "allowed"),
    [
        (taipei(13, 0), taipei(13, 0)),
        (taipei(13, 49), taipei(13, 49)),
        (taipei(13, 50), taipei(14, 10)),
        (taipei(14, 9), taipei(14, 10)),
        (taipei(14, 10), taipei(14, 10)),
        (taipei(20, 29), taipei(20, 29)),
        (taipei(20, 30), taipei(23, 30)),
        (taipei(21, 45), taipei(23, 30)),
        (taipei(23, 49), taipei(23, 49)),
        (taipei(23, 55), taipei(0, 10, day=28)),
        (taipei(7, 55), taipei(9, 0)),
        (taipei(8, 30), taipei(9, 0)),
        (taipei(9, 55), taipei(10, 10)),
    ],
)
def test_next_allowed(moment, allowed):
    assert rf.next_allowed(moment) == allowed


# --- fetch ----------------------------------------------------------------------


class FakeTime:
    def __init__(self, start: datetime) -> None:
        self.at = start
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.at += timedelta(seconds=seconds)

    def clock(self) -> float:
        return self.at.timestamp()

    def now(self) -> datetime:
        return self.at


def plan(directory: Path, *targets: tuple[str, int]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / rf.PLAN).write_text(
        json.dumps(
            {
                "targets": [
                    {"symbol": s, "year": y, "instruments": []} for s, y in targets
                ]
            }
        ),
        encoding="utf-8",
    )


class Server:
    """Answers each form from PAGES (symbol -> list of answers, last one repeats)."""

    def __init__(self, pages: dict[str, list[object]], fake: FakeTime) -> None:
        self.pages = pages
        self.fake = fake
        self.asked: list[tuple[datetime, str, str]] = []

    def __call__(self, form):
        assert form["check2858"] == "Y"
        self.asked.append((self.fake.at, form["co_id"], form["year"]))
        answers = self.pages[form["co_id"]]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            return answer
        return 200, "text/html;charset=big5", answer


def fetch(directory, server, fake, **kwargs):
    return rf.fetch_pages(
        directory,
        getter=server,
        sleep=fake.sleep,
        clock=fake.clock,
        now=fake.now,
        **kwargs,
    )


def test_fetch_stores_pages_six_seconds_apart_and_a_rerun_sends_nothing(tmp_path):
    directory = tmp_path / "out"
    plan(directory, ("8067", 2013), ("2888", 2024), ("6669", 2013))
    fake = FakeTime(taipei(14, 20))
    server = Server(
        {
            "8067": [page("general_8067_102.html")],
            "2888": [page("holding_2888_113.html")],
            "6669": [page("no_data.html")],
        },
        fake,
    )
    out = fetch(directory, server, fake)
    assert out["status"] == "success"
    assert out["counts"] == {"filings": 2, "no_data": 1}
    assert out["last_success"] == "6669/102"
    times = [moment for moment, _, _ in server.asked]
    assert all(b - a >= timedelta(seconds=6) for a, b in zip(times, times[1:]))
    manifest = rf.read_manifest(directory)
    assert manifest["pages"]["8067/102"]["path"] == "raw/8067/102.json"
    stored, body = rf.read_envelope((directory / "raw/8067/102.json").read_bytes())
    assert body == page("general_8067_102.html")
    assert stored["form"]["co_id"] == "8067" and stored["method"] == "POST"
    lines = (directory / rf.REQUESTS).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    # From the stored raw: nothing is asked again.
    again = Server({}, fake)
    out = fetch(directory, again, fake)
    assert again.asked == [] and out["counts"] == {"kept": 3}
    assert out["requests"] == 0 and out["status"] == "success"


def test_a_damaged_stored_page_is_asked_again(tmp_path):
    directory = tmp_path / "out"
    plan(directory, ("8067", 2013))
    fake = FakeTime(taipei(14, 20))
    fetch(directory, Server({"8067": [page("general_8067_102.html")]}, fake), fake)
    (directory / "raw/8067/102.json").write_bytes(b"{}")
    server = Server({"8067": [page("general_8067_102.html")]}, fake)
    assert fetch(directory, server, fake)["requests"] == 1


def test_three_failures_in_a_row_stop_with_the_last_success(tmp_path):
    directory = tmp_path / "out"
    plan(
        directory,
        ("8067", 2013),
        ("1111", 2013),
        ("2222", 2013),
        ("3333", 2013),
        ("4444", 2013),
    )
    fake = FakeTime(taipei(14, 20))
    limited = page("rate_limited.html")
    server = Server(
        {
            "8067": [page("general_8067_102.html")],
            "1111": [limited],
            "2222": [(429, "text/html", b"")],
            "3333": [page("menu_2888_113.html")],
            "4444": [page("no_data.html")],
        },
        fake,
    )
    out = fetch(directory, server, fake)
    assert out["status"] == "failed"
    assert [symbol for _, symbol, _ in server.asked] == ["8067", "1111", "2222", "3333"]
    assert out["last_success"] == "8067/102"
    assert "last success 8067/102" in out["stopped"]
    assert set(out["failed"]) == {"1111/102", "2222/102", "3333/102"}
    # Never stored as a page; the bodies are kept for reading.
    assert set(rf.read_manifest(directory)["pages"]) == {"8067/102"}
    assert list((directory / rf.FAILED_DIR / "1111").iterdir())
    # The interval is not lengthened after a block.
    times = [moment for moment, _, _ in server.asked]
    assert {b - a for a, b in zip(times, times[1:])} == {timedelta(seconds=6)}


def test_a_success_resets_the_failure_count(tmp_path):
    directory = tmp_path / "out"
    plan(directory, ("1111", 2013), ("2222", 2013), ("8067", 2013), ("3333", 2013))
    fake = FakeTime(taipei(14, 20))
    limited = page("rate_limited.html")
    server = Server(
        {
            "1111": [limited],
            "2222": [httpx.ReadTimeout("slow")],
            "8067": [page("general_8067_102.html")],
            "3333": [limited],
        },
        fake,
    )
    out = fetch(directory, server, fake)
    assert out["status"] == "partial" and out["stopped"] is None
    assert out["failed"]["2222/102"] == "no answer: ReadTimeout"
    # The failed ones are asked on the next run.
    server = Server(
        {
            "1111": [page("no_data.html")],
            "2222": [page("no_data.html")],
            "3333": [page("no_data.html")],
        },
        fake,
    )
    out = fetch(directory, server, fake)
    assert out["status"] == "success" and out["requests"] == 3


def test_fetch_waits_out_the_quiet_hours(tmp_path):
    directory = tmp_path / "out"
    plan(directory, ("8067", 2013))
    fake = FakeTime(taipei(21, 0))
    server = Server({"8067": [page("general_8067_102.html")]}, fake)
    fetch(directory, server, fake)
    assert server.asked[0][0] == taipei(23, 30)


def test_max_requests_stops_for_the_next_run(tmp_path):
    directory = tmp_path / "out"
    plan(directory, ("8067", 2013), ("6669", 2013))
    fake = FakeTime(taipei(14, 20))
    server = Server(
        {"8067": [page("general_8067_102.html")], "6669": [page("no_data.html")]}, fake
    )
    out = fetch(directory, server, fake, max_requests=1)
    assert out["status"] == "partial" and out["remaining"] == 1
    assert len(server.asked) == 1


def test_a_plan_before_2013_is_refused(tmp_path):
    plan(tmp_path, ("2330", 2011))
    with pytest.raises(rf.Refused):
        rf.read_plan(tmp_path)


# --- write ----------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'filings.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


def add(db, symbol, name, year, quarters, *, exchange="TWSE", status="active"):
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
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    for quarter in quarters:
        db.add(
            FundamentalSnapshot(
                instrument_id=item.id,
                period_end=date(year, *ends[quarter]),
                fiscal_period=f"Q{quarter}",
                source="mops_t163sb04",
            )
        )
    db.flush()
    return item


FIXTURE_OF = {
    "8067": "general_8067_102.html",
    "2888": "holding_2888_113.html",
    "4712": "renamed_4712_102.html",
    "1752": "old_kind_1752_102.html",
    "1314": "supplementary_1314_102.html",
    "6669": "no_data.html",
}


def seed(factory):
    with factory() as db:
        ids = {
            "8067": add(db, "8067", "志旭", 2013, [1, 2, 3, 4], exchange="TPEx").id,
            "2888": add(db, "2888", "新光金", 2024, [1, 2, 3, 4], status="delisted").id,
            "4712": add(db, "4712", "南璋", 2013, [1, 2, 3], status="delisted").id,
            "1752": add(db, "1752", "南光", 2013, [1, 2, 3, 4]).id,
            "1314": add(db, "1314", "中石化", 2013, [4]).id,
            "6669": add(db, "6669", "緯穎", 2013, [4]).id,
            "9999": add(db, "9999", "未抓", 2013, [1]).id,
        }
        # 2012 and earlier are never asked.
        add(db, "2330", "台積電", 2012, [4])
        db.commit()
    return ids


def fetched(factory, tmp_path, skip=("9999",)):
    directory = tmp_path / "out"
    with factory() as db:
        result = rf.write_plan(directory, db)
    assert result["targets"] == 7
    fake = FakeTime(taipei(14, 20))
    pages = {symbol: [page(name)] for symbol, name in FIXTURE_OF.items()}
    pages.update({symbol: [page("rate_limited.html")] for symbol in skip})
    fetch(directory, Server(pages, fake), fake)
    return directory


def written(db):
    return {
        (row.instrument_id, row.file_name): row
        for row in db.scalars(select(FinancialReportFiling))
    }


def test_write_end_to_end(factory, tmp_path):
    ids = seed(factory)
    directory = fetched(factory, tmp_path)
    with factory() as db:
        out = rf.write_filings(db, directory)
    counts, lists = out["counts"], out["lists"]
    assert out["status"] == "success"
    assert lists["not_fetched"] == ["9999/102"]
    assert lists["no_data"] == ["6669/102"]
    assert lists["name_mismatch"] == [
        {
            "key": "4712/102",
            "instrument_id": ids["4712"],
            "status": "delisted",
            "db_name": "南璋",
            "page_name": "福格創新",
        }
    ]
    # 1752 南光 102Q4 has only 母公司財報: an old-layout quarter; Q1-Q3 are written.
    assert lists["old_layout"] == ["1752/102Q4"]
    assert counts["old_kind_rows"] == 1
    assert counts["page_failed"] == 0
    with factory() as db:
        rows = written(db)
        assert {iid for iid, _ in rows} == {
            ids["8067"],
            ids["2888"],
            ids["1752"],
            ids["1314"],
        }
        assert sorted(name for iid, name in rows if iid == ids["1752"]) == [
            "201301_1752_AI2.pdf",
            "201302_1752_AI2.pdf",
            "201303_1752_AI2.pdf",
        ]
        # The supplementary report is written, never the filing date.
        a03 = rows[(ids["1314"], "201304_1314_A03.pdf")]
        assert a03.report_kind == "關係企業合併報表"
        q1 = rows[(ids["8067"], "201301_8067_AI1.pdf")]
        assert q1.source == rf.SOURCE and q1.fiscal_period == "Q1"
        assert q1.uploaded_at == datetime(2013, 5, 14, 15, 53, 36)
        assert q1.data_as_of == date(2026, 11, 27)
        raw = db.get(RawPayload, q1.raw_payload_id)
        assert raw.source == rf.RAW_SOURCE
        assert raw.endpoint == rf.request_endpoint(rf.Target("8067", 2013))
        assert Path(raw.payload_path).name == f"{raw.sha256}.json"
        assert Path(raw.payload_path).is_file()
        assert len(rows) == counts["inserted"]
        dates = rf.filing_dates(db)
        assert dates[(ids["1314"], date(2013, 12, 31))] == datetime(
            2014, 3, 31, 14, 17, 25
        )
        assert (ids["1752"], date(2013, 12, 31)) not in dates
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == rf.RUN_TYPE)
        )
        assert run.status == "success" and run.records == counts["inserted"]
        raw_count = db.scalar(select(func.count()).select_from(RawPayload))
    # A rerun from the same raw changes nothing.
    with factory() as db:
        again = rf.write_filings(db, directory)
        assert again["counts"]["inserted"] == 0 and again["counts"]["updated"] == 0
        assert again["counts"]["unchanged"] == counts["inserted"]
        assert db.scalar(select(func.count()).select_from(RawPayload)) == raw_count


def test_coverage_by_year_and_status(factory, tmp_path):
    ids = seed(factory)
    directory = fetched(factory, tmp_path)
    with factory() as db:
        rf.write_filings(db, directory)
        table = {
            (cell["year"], cell["status"]): cell
            for cell in rf.coverage(db)["by_year_status"]
        }
    active = table[(2013, "active")]
    # 8067 4, 1752 3 of 4, 1314 1, 6669 0, 9999 0 quarters.
    assert active["quarters"] == 11 and active["quarters_with_filing"] == 8
    assert active["companies"] == 5 and active["companies_with_filing"] == 3
    assert set(active["companies_without_filing"]) == {ids["6669"], ids["9999"]}
    assert table[(2013, "delisted")]["quarters_with_filing"] == 0
    assert table[(2024, "delisted")]["quarters_with_filing"] == 4
    assert 2012 not in {year for year, _ in table}


def test_accepted_names_write_a_renamed_company(factory, tmp_path):
    ids = seed(factory)
    directory = fetched(factory, tmp_path)
    with factory() as db:
        out = rf.write_filings(
            db, directory, accepted=frozenset({("4712", "福格創新", "南璋")})
        )
        assert out["lists"]["name_mismatch"] == []
        assert any(iid == ids["4712"] for iid, _ in written(db))


def test_a_dry_run_writes_nothing(factory, tmp_path):
    seed(factory)
    directory = fetched(factory, tmp_path)
    with factory() as db:
        out = rf.write_filings(db, directory, dry_run=True)
        assert out["run_id"] is None and out["counts"]["rows"] > 0
        assert written(db) == {}
        assert db.scalar(select(func.count()).select_from(RawPayload)) == 0


def test_a_page_that_does_not_read_writes_and_counts_nothing(factory, tmp_path):
    ids = seed(factory)
    directory = fetched(factory, tmp_path)
    text = (FIXTURES / "general_8067_102.html").read_text(encoding="utf-8")
    broken = text.replace("102/11/12 14:07:08", "102/11/12 25:07:08").encode(
        rf.ENCODING
    )
    fake = FakeTime(taipei(15, 20))
    manifest = rf.read_manifest(directory)
    del manifest["pages"]["8067/102"]
    rf._write_json(directory / rf.MANIFEST, manifest)
    fetch(
        directory,
        Server({"9999": [page("rate_limited.html")], "8067": [broken]}, fake),
        fake,
    )
    with factory() as db:
        out = rf.write_filings(db, directory)
        assert out["counts"]["page_failed"] == 1
        assert out["lists"]["page_failed"][0]["key"] == "8067/102"
        assert not any(iid == ids["8067"] for iid, _ in written(db))
        assert out["counts"]["inserted"] == len(written(db))


def test_a_transferred_code_splits_its_quarters_between_the_instruments(
    factory, tmp_path
):
    with factory() as db:
        old = add(
            db, "8067", "志旭", 2013, [1, 2], exchange="TPEx", status="transferred"
        )
        new = add(db, "8067", "志旭", 2013, [3, 4])
        db.commit()
    directory = tmp_path / "out"
    with factory() as db:
        assert rf.write_plan(directory, db)["targets"] == 1
    fake = FakeTime(taipei(14, 20))
    fetch(directory, Server({"8067": [page("general_8067_102.html")]}, fake), fake)
    with factory() as db:
        rf.write_filings(db, directory)
        rows = written(db)
    assert sorted(name for iid, name in rows if iid == old.id) == [
        "201301_8067_AI1.pdf",
        "201302_8067_AI1.pdf",
    ]
    assert len([name for iid, name in rows if iid == new.id]) == 3


def test_a_quarter_neither_instrument_has_is_not_guessed(factory, tmp_path):
    with factory() as db:
        add(db, "8067", "志旭", 2013, [1], exchange="TPEx", status="transferred")
        add(db, "8067", "志旭", 2013, [2])
        db.commit()
    directory = tmp_path / "out"
    with factory() as db:
        rf.write_plan(directory, db)
    fake = FakeTime(taipei(14, 20))
    fetch(directory, Server({"8067": [page("general_8067_102.html")]}, fake), fake)
    with factory() as db:
        out = rf.write_filings(db, directory)
    assert out["lists"]["unassigned"] == ["8067/102Q3", "8067/102Q4"]
    assert out["counts"]["inserted"] == 2


def test_a_changed_correction_updates_the_row(factory, tmp_path):
    seed(factory)
    directory = fetched(factory, tmp_path)
    with factory() as db:
        rf.write_filings(db, directory)
    text = (FIXTURES / "general_8067_102.html").read_text(encoding="utf-8")
    marker = "<td align='center'>無</td>"
    assert marker in text
    corrected = text.replace(
        marker,
        "<td align='center'><input type='button' onclick=\"location.href='http://"
        "mopsov.twse.com.tw/mops/web/t56sb31_q1?step=2';\" value='詳細資料'></td>",
        1,
    ).encode(rf.ENCODING)
    manifest = rf.read_manifest(directory)
    del manifest["pages"]["8067/102"]
    rf._write_json(directory / rf.MANIFEST, manifest)
    fake = FakeTime(taipei(15, 20))
    fetch(
        directory,
        Server({"9999": [page("rate_limited.html")], "8067": [corrected]}, fake),
        fake,
    )
    with factory() as db:
        out = rf.write_filings(db, directory)
        assert out["counts"]["updated"] == 1
        changed = [
            row
            for row in written(db).values()
            if row.correction != "無" and row.file_name.endswith("_8067_AI1.pdf")
        ]
        assert [row.file_name for row in changed] == ["201301_8067_AI1.pdf"]


# --- the command ----------------------------------------------------------------


def _cli(monkeypatch, argv):
    import worker.cli as cli_module

    monkeypatch.setattr(sys, "argv", ["worker.cli", *argv])
    try:
        cli_module.main()
    except SystemExit as exc:
        return exc.code
    return 0


@pytest.mark.parametrize(
    "argv",
    [
        ["filings", "plan", "--dir", "X"],
        ["filings", "write", "--dir", "X"],
        ["filings", "write", "--dir", "X", "--dry-run"],
        ["filings", "coverage"],
    ],
)
def test_the_db_commands_refuse_without_the_research_marker(
    monkeypatch, tmp_path, capsys, argv
):
    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")

    def never(*args, **kwargs):
        raise AssertionError("no session without the research marker")

    for name in ("run_plan", "run_write", "run_coverage"):
        monkeypatch.setattr(rf, name, never)
    argv = [str(tmp_path) if part == "X" else part for part in argv]
    assert _cli(monkeypatch, argv) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "research-db.json" in out["error"]


def test_write_holds_maintenance_mode_and_a_dry_run_does_not(tmp_path):
    import argparse

    import worker.cli as cli_module

    def args(command, **extra):
        return argparse.Namespace(
            command="filings", filings_command=command, dir=str(tmp_path), **extra
        )

    assert cli_module.maintenance_guarded(args("write", dry_run=False)) == (
        "filings write"
    )
    assert cli_module.maintenance_guarded(args("write", dry_run=True)) is None
    fetch_args = args("fetch", max_requests=None)
    assert cli_module.maintenance_guarded(fetch_args) is None
    # The fetch needs no database, so no research marker either.
    assert cli_module.research_command_refusal(fetch_args) is None


def test_a_stopped_fetch_exits_1_and_a_partial_one_3(monkeypatch, tmp_path):
    monkeypatch.setattr(rf, "run_fetch", lambda *a, **k: {"status": "failed"})
    assert _cli(monkeypatch, ["filings", "fetch", "--dir", str(tmp_path)]) == 1
    monkeypatch.setattr(rf, "run_fetch", lambda *a, **k: {"status": "partial"})
    assert _cli(monkeypatch, ["filings", "fetch", "--dir", str(tmp_path)]) == 3
