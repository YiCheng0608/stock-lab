"""Insider holdings, pledges and transfer declarations of the research DB (Issue #1133).

The fixtures under ``fixtures/insider`` are answers of the #1129 probe
(2026-11-28, evidence/1129/raw), cut to a few rows; company names of the siis
files and every person's name are fakes, and the links of the t56sb21 cells
(which carry the filer's id) are cut to their text:

- ``irb110_sii_9707`` / ``irb130_sii_9707``: Big5, 1101, 2384, 2475 of 2008-07.
- ``irb110_otc_10207``: UTF-16LE with its BOM, 3105, 5483, 8299 of 2013-07.
- ``t56sb21_sii_107``: 2018, five rows: two 信託, a 鉅額逐筆交易 changed by a later
  declaration (both rows), and 一般交易 盤後定價交易 with two share counts.
- ``t56sb21_sii_92``: 2003, ten rows of 01, 04 and 05: the placeholder zeros of
  01..04 and a real April row (2451, 80,000).
- ``t56sb21_otc_90``: 2001, 無持股轉讓之情形.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    IngestionRun,
    InsiderHoldingsMonthly,
    InsiderPledgesMonthly,
    InsiderTransferDeclaration,
    Instrument,
    MarketBar,
)
from worker import insider_backfill as ib
from worker import sources

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "insider"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


IRB110_SII = load("irb110_sii_9707.htm")
IRB130_SII = load("irb130_sii_9707.htm")
IRB110_OTC_UTF16 = load("irb110_otc_10207.htm")
T56_2018 = load("t56sb21_sii_107.htm")
T56_2003 = load("t56sb21_sii_92.htm")
T56_2001 = load("t56sb21_otc_90.htm")
JULY_2008 = date(2008, 7, 1)
JULY_2013 = date(2013, 7, 1)
# 2026-11-06 12:20 Taipei: outside the quiet hours and the even-hour margins.
NOON = datetime(2026, 11, 6, 4, 20)


# --- parsers ----------------------------------------------------------------------


def test_irb110_reads_a_big5_file():
    parsed = ib.parse_irb("irb110", IRB110_SII, JULY_2008)
    assert parsed["encoding"] == "cp950"
    assert parsed["data_as_of"] == date(2008, 8, 21)
    assert list(parsed["rows"]) == ["1101", "2384", "2475"]
    assert parsed["rows"]["1101"] == {
        "shares_issued": 3_248_637_197,
        "director_increase": 4_800_000,
        "director_decrease": 198_000,
        "director_held": 338_408_887,
        "director_held_pct": 10.41,
        "manager_held": 40_579_991,
        "major_holder_held": 0,
    }
    # The delisted company is in the report of its time (#1129).
    assert parsed["rows"]["2384"]["shares_issued"] == 1_148_405_155
    assert parsed["rows"]["2384"]["director_held"] == 147_176_455


def test_irb110_reads_a_utf16_file_by_its_bom():
    assert IRB110_OTC_UTF16[:2] == b"\xff\xfe"
    parsed = ib.parse_irb("irb110", IRB110_OTC_UTF16, JULY_2013)
    assert parsed["encoding"] == "utf-16"
    assert parsed["data_as_of"] == date(2013, 8, 22)
    assert list(parsed["rows"]) == ["3105", "5483", "8299"]
    assert all(
        isinstance(v, (int, float))
        for row in parsed["rows"].values()
        for v in row.values()
    )


def test_irb130_reads_its_nine_columns():
    parsed = ib.parse_irb("irb130", IRB130_SII, JULY_2008)
    assert parsed["rows"]["1101"] == {
        "director_held": 338_408_887,
        "director_pledge_set": 2_000_000,
        "director_pledge_released": 0,
        "director_pledged": 84_532_000,
        "director_pledged_pct": 24.97,
        "manager_held": 40_579_991,
        "major_holder_held": 0,
        "manager_major_pledged": 11_000_000,
        "manager_major_pledged_pct": 27.10,
    }
    holdings = ib.parse_irb("irb110", IRB110_SII, JULY_2008)["rows"]
    assert all(
        row["director_held"] == holdings[code]["director_held"]
        for code, row in parsed["rows"].items()
    )


def test_a_month_other_than_the_one_asked_fails_the_file():
    with pytest.raises(ib.LayoutError, match="資料年月 9707 is not 2008-08"):
        ib.parse_irb("irb110", IRB110_SII, date(2008, 8, 1))


def test_the_other_report_fails_the_file():
    with pytest.raises(ib.LayoutError, match="not an IRB130 file"):
        ib.parse_irb("irb130", IRB110_SII, JULY_2008)


def test_an_unreadable_number_fails_the_file():
    broken = IRB110_SII.replace(b"4,800,000", b"4,800,00x", 1)
    with pytest.raises(ib.LayoutError, match="unreadable share count"):
        ib.parse_irb("irb110", broken, JULY_2008)


def test_a_blank_cell_is_null_and_a_zero_stays_zero():
    text = IRB110_SII.decode("cp950")
    blank = re.sub(
        r"(<TD ALIGN=RIGHT>)\s*40,579,991(</TD>)", r"\1 \2", text, count=1
    ).encode("cp950")
    row = ib.parse_irb("irb110", blank, JULY_2008)["rows"]["1101"]
    assert row["manager_held"] is None and row["major_holder_held"] == 0


def test_unknown_columns_fail_the_file():
    text = IRB110_SII.decode("cp950").replace("減  少  股  數", "其  他  股  數")
    with pytest.raises(ib.LayoutError, match="unknown columns"):
        ib.parse_irb("irb110", text.encode("cp950"), JULY_2008)


def test_t56sb21_reads_methods_side_by_side_and_change_rows():
    parsed = ib.parse_t56sb21(T56_2018, 2018)
    rows = parsed["rows"]
    assert [row["row_no"] for row in rows] == [1, 2, 3, 4, 5]
    both = rows[4]
    assert both["code"] == "6452"
    assert both["method_raw"] == "一般交易 盤後定價交易"
    assert both["method_shares_raw"] == "200,000 2,000,000"
    assert both["intraday_max_shares"] == 108_000
    assert both["planned_own"] == 2_200_000
    assert both["period_start"] == date(2018, 6, 18)
    assert both["period_end"] == date(2018, 7, 17)
    assert both["unfinished_declared"] == 1
    changed, change = rows[2], rows[3]
    assert changed["change_note"] == "已於107/10/30 申報變更"
    assert change["change_note"] == "本單為變更 107/10/26之申報"
    assert change["filed_date"] == date(2018, 10, 30)
    assert (changed["method_raw"], change["method_raw"]) == ("鉅額逐筆交易", "一般交易")
    assert changed["insider_type"] == "director" and changed["relation"] == "nominee"
    trust = rows[0]
    assert trust["method_raw"] == "信託" and trust["method_shares_raw"] is None
    assert trust["intraday_max_shares"] is None and trust["held_trust"] == 0
    assert trust["unfinished_declared"] is None and trust["change_note"] is None


def test_t56sb21_rows_other_than_the_total_fail_the_year():
    broken = T56_2018.replace("總計：5筆".encode(), "總計：6筆".encode())
    with pytest.raises(ib.LayoutError, match="總計 6 筆 but 5 rows"):
        ib.parse_t56sb21(broken, 2018)


def test_t56sb21_a_row_of_another_year_fails():
    with pytest.raises(ib.LayoutError, match="is not in 2019"):
        ib.parse_t56sb21(T56_2018, 2019)


def test_t56sb21_placeholder_zeros_before_2003_05_are_null():
    parsed = ib.parse_t56sb21(T56_2003, 2003)
    by_day = {(row["code"], row["filed_date"]): row for row in parsed["rows"]}
    zero = by_day[("1314", date(2003, 1, 9))]
    assert zero["method_shares_raw"] is None
    assert all(zero[name] is None for name in ib.SHARE_FIELDS)
    april = by_day[("2451", date(2003, 4, 30))]
    assert april["method_shares_raw"] == "80,000" and april["held_own"] > 0
    assert april["held_trust"] == 0
    may = by_day[("1101", date(2003, 5, 6))]
    assert may["method_shares_raw"] == "500,000" and may["held_trust"] == 0
    assert parsed["placeholder_rows"] == sum(
        row["filed_date"] < ib.PLACEHOLDER_BEFORE and row["held_own"] is None
        for row in parsed["rows"]
    )
    # 1101 (01, 04), 1108, 1216, 1314, 2462; 1711's 贈與 of 04-29 has real counts.
    assert parsed["placeholder_rows"] == 6
    assert by_day[("1711", date(2003, 4, 29))]["held_own"] == 239_470


def test_t56sb21_a_year_without_transfers_is_no_rows():
    assert ib.parse_t56sb21(T56_2001, 2001) == {
        "rows": [],
        "no_transfer": True,
        "placeholder_rows": 0,
    }


def test_t56sb21_the_block_page_stops():
    page = "<html><body>查詢過於頻繁，請稍後再試</body></html>".encode()
    with pytest.raises(ib.Blocked):
        ib.parse_t56sb21(page, 2018)


@pytest.mark.parametrize(
    ("role", "split"),
    [
        ("董事本人", ("director", "self", 0)),
        ("法人董事代表人配偶", ("director", "representative_spouse", 0)),
        ("法人監察人代表人本人", ("supervisor", "representative", 0)),
        ("董事本人 及由受託人持有者", ("director", "self", 1)),
        ("子公司經理人配偶 及由受託人持有者", ("subsidiary_manager", "spouse", 1)),
        (
            "子公司法人董事代表人未成年子女",
            ("subsidiary_director", "representative_minor_child", 0),
        ),
        ("大股東利用他人名義持有者", ("major_holder", "nominee", 0)),
        ("特定人本人", ("specific_person", "self", 0)),
        ("法人經理人代表人本人", (None, None, 0)),
        ("董事長", (None, None, 0)),
    ],
)
def test_roles_split_or_stay_null(role, split):
    assert ib.split_role(role) == split


def test_the_waits_before_a_request():
    taipei = lambda h, m: datetime(2026, 11, 6, h, m) - (  # noqa: E731
        datetime(2026, 11, 6, 8) - datetime(2026, 11, 6, 0)
    )
    assert ib.seconds_to_wait(taipei(12, 20)) == 0
    assert ib.seconds_to_wait(taipei(13, 30)) == 0
    assert ib.seconds_to_wait(taipei(13, 55)) == 15 * 60
    assert ib.seconds_to_wait(taipei(14, 5)) == 5 * 60
    assert ib.seconds_to_wait(taipei(14, 10)) == 0
    assert ib.seconds_to_wait(taipei(21, 20)) == (2 * 60 + 10) * 60


# --- the backfill -------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def add_instrument(db, exchange, symbol, days):
    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type="stock",
        status="active",
    )
    db.add(item)
    db.flush()
    for day in days:
        db.add(
            MarketBar(
                instrument_id=item.id,
                trading_date=day,
                open=10,
                high=10,
                low=10,
                close=10,
                adj_close=10,
                volume=1,
                source=exchange.lower(),
            )
        )
    db.flush()
    return item


class Fetcher:
    """Answers each url with its bytes (404 when not given), or an error."""

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, url, form, *, sleep):
        self.calls.append((method, url, form))
        key = (url, (form or {}).get("TYPEK"), (form or {}).get("year"))
        answer = self.answers.get(key, self.answers.get(url))
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return ib.Answer(404, b"<html>404</html>"), 0
        return ib.Answer(200, answer), 0


def url(feed, market, month):
    return ib.request_of(feed, market, month)[1]


def run(factory, fetch, start, end, **kwargs):
    with factory() as db:
        return ib.backfill(
            db,
            start,
            end,
            fetch=fetch,
            now=lambda: NOON,
            sleep=lambda _s: None,
            monotonic=lambda: 1000.0,
            **kwargs,
        )


def test_monthly_rows_are_written_and_a_rerun_asks_nothing(factory):
    with factory() as db:
        add_instrument(db, "TWSE", "1101", [date(2008, 7, 1), date(2008, 7, 31)])
        add_instrument(db, "TWSE", "2384", [date(2008, 7, 15)])
        db.commit()
    answers = {
        url("irb110", "sii", JULY_2008): IRB110_SII,
        url("irb130", "sii", JULY_2008): IRB130_SII,
    }
    fetch = Fetcher(answers)
    result = run(
        factory,
        fetch,
        JULY_2008,
        JULY_2008,
        feeds=["irb110", "irb130"],
        markets=["sii"],
    )
    assert result["status"] == "success" and result["requests"] == 2
    holdings = result["feeds"]["irb110"]
    assert (holdings["written"], holdings["unmatched"]) == (2, 1)
    with factory() as db:
        rows = db.scalars(select(InsiderHoldingsMonthly)).all()
        assert {r.period_month for r in rows} == {JULY_2008}
        assert {r.data_as_of for r in rows} == {date(2008, 8, 21)}
        assert {r.source for r in rows} == {"siis_irb110"}
        assert {r.market for r in rows} == {"sii"}
        assert (
            db.scalar(
                select(InsiderPledgesMonthly.director_pledged).where(
                    InsiderPledgesMonthly.director_pledge_set == 2_000_000
                )
            )
            == 84_532_000
        )
        run_row = db.scalar(
            select(IngestionRun).where(
                IngestionRun.request_key == "insider_backfill:irb110:sii:2008-07"
            )
        )
        assert run_row.status == "success"
        assert run_row.metadata_json["unmatched_codes"] == ["2475"]
    again = run(
        factory,
        fetch,
        JULY_2008,
        JULY_2008,
        feeds=["irb110", "irb130"],
        markets=["sii"],
    )
    assert again["requests"] == 0 and again["feeds"]["irb110"]["done_before"] == 1
    reapplied = run(
        factory,
        Fetcher({}),
        JULY_2008,
        JULY_2008,
        feeds=["irb110", "irb130"],
        markets=["sii"],
        reapply=True,
    )
    assert reapplied["requests"] == 0 and reapplied["changed"] == 0
    assert reapplied["feeds"]["irb110"]["unchanged"] == 2


def test_a_404_is_not_published_and_asked_again(factory):
    fetch = Fetcher({})
    month = date(2026, 11, 1)
    result = run(factory, fetch, month, month, feeds=["irb110"], markets=["sii"])
    counts = result["feeds"]["irb110"]
    assert (counts["not_published"], counts["failed"]) == (1, 0)
    assert result["status"] == "success"
    again = run(factory, fetch, month, month, feeds=["irb110"], markets=["sii"])
    assert again["requests"] == 1


def test_no_request_before_the_first_month(factory):
    fetch = Fetcher({})
    result = run(
        factory,
        fetch,
        date(2003, 6, 1),
        date(2003, 7, 1),
        feeds=["irb110"],
        markets=["sii"],
    )
    assert result["requests"] == 0 and result["feeds"]["irb110"]["not_published"] == 2


def test_a_wrong_month_fails_and_writes_nothing(factory):
    with factory() as db:
        add_instrument(db, "TWSE", "1101", [date(2008, 8, 1)])
        db.commit()
    august = date(2008, 8, 1)
    fetch = Fetcher({url("irb110", "sii", august): IRB110_SII})
    result = run(factory, fetch, august, august, feeds=["irb110"], markets=["sii"])
    assert result["status"] == "partial"
    assert "資料年月" in result["feeds"]["irb110"]["failed_units"][0]["error"]
    with factory() as db:
        assert db.scalars(select(InsiderHoldingsMonthly)).all() == []
        run_row = db.scalar(select(IngestionRun))
        assert run_row.status == "failed"
        assert run_row.metadata_json["raw_payload_id"] is not None


def test_a_company_moved_board_that_month_is_found_on_the_other_one(factory):
    # The 2013-07 OTC report's 3105 has bars on TWSE only that month (as 6177,
    # in the TWSE report of the month it moved, #1129).
    with factory() as db:
        moved = add_instrument(db, "TWSE", "3105", [date(2013, 7, 30)])
        add_instrument(db, "TPEx", "5483", [date(2013, 7, 1)])
        add_instrument(db, "TPEx", "8299", [date(2013, 6, 28)])
        db.commit()
        moved_id = moved.id
    fetch = Fetcher({url("irb110", "otc", JULY_2013): IRB110_OTC_UTF16})
    result = run(
        factory, fetch, JULY_2013, JULY_2013, feeds=["irb110"], markets=["otc"]
    )
    counts = result["feeds"]["irb110"]
    assert (counts["written"], counts["cross_market"], counts["unmatched"]) == (2, 1, 1)
    with factory() as db:
        row = db.scalar(
            select(InsiderHoldingsMonthly).where(
                InsiderHoldingsMonthly.instrument_id == moved_id
            )
        )
        assert row.market == "otc"


def test_the_report_board_wins_when_both_have_bars(factory):
    with factory() as db:
        add_instrument(db, "TPEx", "1101", [date(2008, 7, 1)])
        listed = add_instrument(db, "TWSE", "1101", [date(2008, 7, 20)])
        db.commit()
        listed_id = listed.id
    fetch = Fetcher({url("irb110", "sii", JULY_2008): IRB110_SII})
    run(factory, fetch, JULY_2008, JULY_2008, feeds=["irb110"], markets=["sii"])
    with factory() as db:
        assert db.scalar(select(InsiderHoldingsMonthly.instrument_id)) == listed_id


def test_transfer_declarations_replace_the_year_asked_again(factory, monkeypatch):
    with factory() as db:
        for code in ("1101", "4414", "6452"):
            add_instrument(db, "TWSE", code, [date(2018, 6, 1), date(2018, 10, 1)])
        db.commit()
    key = (ib.T56SB21_ENDPOINT, "sii", "107")
    fetch = Fetcher({key: T56_2018})
    year = date(2018, 1, 1)
    asked_in_2018 = datetime(2018, 11, 6, 4, 20)
    with factory() as db:
        result = ib.backfill(
            db,
            year,
            year,
            feeds=["t56sb21"],
            markets=["sii"],
            fetch=fetch,
            now=lambda: asked_in_2018,
            sleep=lambda _s: None,
            monotonic=lambda: 1.0,
        )
    assert result["feeds"]["t56sb21"]["written"] == 5
    with factory() as db:
        rows = db.scalars(
            select(InsiderTransferDeclaration).order_by(
                InsiderTransferDeclaration.row_no
            )
        ).all()
        assert [r.row_no for r in rows] == [1, 2, 3, 4, 5]
        assert all(r.data_as_of == r.filed_date for r in rows)
        assert {r.source for r in rows} == {"mops_t56sb21"}
        first_raw = rows[0].raw_payload_id
    # The year was asked before it ended: asked again, the rows replaced.
    shorter = T56_2018.replace("總計：5筆".encode(), "總計：4筆".encode())
    shorter = re.sub(
        rb"<tr class='(?:odd|even)'>(?:(?!</tr>).)*6452(?:(?!</tr>).)*</tr>",
        b"",
        shorter,
        flags=re.S,
    )
    fetch.answers[key] = shorter
    result = run(factory, fetch, year, year, feeds=["t56sb21"], markets=["sii"])
    counts = result["feeds"]["t56sb21"]
    assert result["requests"] == 1
    assert (counts["inserted"], counts["removed"]) == (4, 5)
    with factory() as db:
        rows = db.scalars(select(InsiderTransferDeclaration)).all()
        assert len(rows) == 4 and first_raw not in {r.raw_payload_id for r in rows}
    # Asked after the year ended: done.
    again = run(factory, fetch, year, year, feeds=["t56sb21"], markets=["sii"])
    assert again["requests"] == 0


def test_a_year_without_transfers_is_a_success_with_no_rows(factory):
    year = date(2001, 1, 1)
    result = run(factory, Fetcher({}), year, year, feeds=["t56sb21"])
    assert result["requests"] == 0  # before 2002
    year = date(2002, 1, 1)
    fetch = Fetcher({ib.T56SB21_ENDPOINT: T56_2001})
    result = run(factory, fetch, year, year, feeds=["t56sb21"], markets=["otc"])
    counts = result["feeds"]["t56sb21"]
    assert (counts["success"], counts["no_transfer"], counts["written"]) == (1, 1, 0)


def test_the_block_page_stops_the_feed(factory):
    page = "<html>FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED!</html>".encode()
    fetch = Fetcher({ib.T56SB21_ENDPOINT: page})
    result = run(factory, fetch, date(2010, 1, 1), date(2012, 12, 1), feeds=["t56sb21"])
    counts = result["feeds"]["t56sb21"]
    assert result["requests"] == 1 and counts["blocked"]
    assert result["status"] == "partial"


def test_failed_requests_in_a_row_stop_the_run(factory):
    fetch = Fetcher(
        {
            ib.request_of("irb110", m, d)[1]: OSError("down")
            for m in ("sii", "otc")
            for d in ib.periods(ib.FEEDS["irb110"], date(2010, 1, 1), date(2010, 12, 1))
        }
    )
    result = run(factory, fetch, date(2010, 1, 1), date(2010, 12, 1), feeds=["irb110"])
    assert result["requests"] == ib.ABORT_AFTER_FAILURES
    assert result["aborted"].startswith(
        "5 failed requests in a row to siis.twse.com.tw"
    )


def test_requests_to_a_host_keep_the_interval_and_wait_out_the_quiet_hours(factory):
    clock = {"t": 0.0}
    moments = iter(
        [datetime(2026, 11, 6, 13, 20)]  # 21:20 Taipei: wait to 23:30
        + [datetime(2026, 11, 6, 15, 40)] * 10
    )
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    with factory() as db:
        ib.backfill(
            db,
            date(2010, 1, 1),
            date(2010, 2, 1),
            feeds=["irb110"],
            markets=["sii"],
            fetch=Fetcher({}),
            now=lambda: next(moments),
            sleep=sleep,
            monotonic=lambda: clock["t"],
        )
    assert slept[0] == (2 * 60 + 10) * 60
    assert slept[1:] == [ib.REQUEST_INTERVAL_SECONDS]


def test_the_tables_must_exist(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with sessionmaker(bind=engine)() as db, pytest.raises(ValueError, match="init-db"):
        ib.backfill(db, JULY_2008, JULY_2008, fetch=Fetcher({}), now=lambda: NOON)
    engine.dispose()


def test_the_post_form_asks_the_whole_year():
    method, endpoint, form = ib.request_of("t56sb21", "otc", date(2008, 1, 1))
    assert (method, endpoint) == ("POST", ib.T56SB21_ENDPOINT)
    assert form == {
        "step": "1",
        "TYPEK": "otc",
        "year": "97",
        "smonth": "01",
        "emonth": "12",
        "sstep": "1",
        "firstin": "true",
    }
    assert ib.request_of("irb130", "sii", date(2013, 7, 1))[1] == (
        "https://siis.twse.com.tw/publish/sii/102IRB130_07.HTM"
    )


# --- the command ----------------------------------------------------------------------


def test_the_command_refuses_a_database_without_the_research_marker(
    tmp_path, monkeypatch, capsys
):
    from worker import cli

    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "stock.db")
    (tmp_path / "stock.db").write_bytes(b"")
    monkeypatch.setattr(
        "sys.argv",
        ["worker.cli", "insider", "backfill", "--start", "2008-07", "--end", "2008-07"],
    )
    monkeypatch.setattr(
        cli,
        "run_insider_backfill",
        lambda *a, **k: pytest.fail("ran without the marker"),
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "research-db.json" in out["error"]


def test_the_command_holds_maintenance_and_the_backfill_floor():
    from worker import cli

    args = argparse.Namespace(command="insider", insider_command="backfill")
    assert cli.maintenance_guarded(args) == "insider backfill"
    assert cli.backfill_command(args) == "insider backfill"


# --- the migration --------------------------------------------------------------------


def test_the_migration_adds_three_empty_tables_and_goes_down_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    from app import migrations
    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith("_insider_filings"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    tables = {
        "insider_holdings_monthly",
        "insider_pledges_monthly",
        "insider_transfer_declarations",
    }
    try:
        command.upgrade(config, revision)
        assert tables <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            for table in tables:
                assert (
                    connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()
                    == 0
                )
        command.downgrade(config, previous)
        assert not tables & set(inspect(engine).get_table_names())
        command.upgrade(config, revision)
        assert tables <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
