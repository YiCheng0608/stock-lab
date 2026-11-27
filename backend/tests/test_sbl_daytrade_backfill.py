"""Daily securities lending and day trades of the research database (Issue #1089).

The fixtures under ``fixtures/sbl_daytrade`` are answers of the #1085 probe
(2026-11-27, evidence/1085/raw), trimmed to a few codes with ``total`` /
``totalCount`` set to the rows kept and the notes cut to one:

- ``twt93u_20261126`` and ``twt93u_20120319``: TWSE lending, the 15 columns;
  ``twt93u_20120316``: the 14 columns before (賣出、庫存異動、今日餘額);
  these three end with the 合計 row, as published from 2012-03-16, and their
  ``total`` counts it; ``twt93u_20080701``: 14 columns without a 合計 row;
  ``twt93u_20050630_before_first``: the answer before the first day.
- ``tpex_sbl_20261126``: TPEx lending.
- ``twtb4u_20261126`` (1201 marked ``Y``) and ``twtb4u_20140106`` (1201 listed
  with 0): TWSE day trades.
- ``tpex_intraday_stat_20261126``: TPEx day trades with the mark column;
  ``tpex_intraday_stat_20140106``: the five columns of 2014 (1240 not listed).
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    DayTradeDaily,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    SecuritiesLendingDaily,
)
from worker import sbl_daytrade_backfill as sd
from worker import sources

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sbl_daytrade"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


SBL_NEW = load("twt93u_20261126.json")
SBL_0319 = load("twt93u_20120319.json")
SBL_OLD = load("twt93u_20120316.json")
SBL_2008 = load("twt93u_20080701.json")
SBL_BEFORE = load("twt93u_20050630_before_first.json")
TPEX_SBL = load("tpex_sbl_20261126.json")
DT_NEW = load("twtb4u_20261126.json")
DT_2014 = load("twtb4u_20140106.json")
TPEX_DT_NEW = load("tpex_intraday_stat_20261126.json")
TPEX_DT_2014 = load("tpex_intraday_stat_20140106.json")
# 2026-11-06 12:30 Taipei: outside every quiet time.
NOON = datetime(2026, 11, 6, 4, 30)


def roc_title(day: date) -> str:
    return f"{day.year - 1911}年{day:%m}月{day:%d}日"


def redate(payload, day: date):
    """The answer as if for ``day``: the reported dates rewritten."""

    result = copy.deepcopy(payload)
    result["date"] = day.strftime("%Y%m%d")
    for table in result.get("tables", []):
        if "date" in table:
            table["date"] = f"{day.year - 1911}/{day:%m/%d}"
        title = table.get("title") or ""
        if "年" in title:
            table["title"] = roc_title(day) + title.split("日", 1)[1]
    return result


# --- parsers ----------------------------------------------------------------------


def test_twse_lending_reads_the_current_layout():
    rows = sd.parse_twse_sbl(SBL_NEW, date(2026, 11, 26))
    assert set(rows) == {"0050", "1101", "1102", "2317", "2330"}
    assert rows["2330"] == {
        "sbl_sell_shares": 136_000,
        "sbl_return_shares": 12_000,
        "sbl_balance_shares": 17_410_514,
        "note": None,
    }
    # 0 stays 0: listed, nothing sold.
    assert (
        sd.parse_twse_sbl(SBL_0319, date(2012, 3, 19))["0050"]["sbl_sell_shares"] == 0
    )


def test_twse_lending_before_2012_03_19_has_no_return_column():
    rows = sd.parse_twse_sbl(SBL_OLD, date(2012, 3, 16))
    # 1101: 賣出 0, 庫存異動 -1,164,000 (not read), 今日餘額 17,732,733.
    assert rows["1101"] == {
        "sbl_sell_shares": 0,
        "sbl_return_shares": None,
        "sbl_balance_shares": 17_732_733,
        "note": None,
    }
    assert rows["2317"]["sbl_sell_shares"] == 52_000
    assert rows["2317"]["sbl_balance_shares"] == 50_673_137


def test_tpex_lending_reads_its_table():
    rows = sd.parse_tpex_sbl(TPEX_SBL, date(2026, 11, 26))
    assert rows["8069"] == {
        "sbl_sell_shares": 24_000,
        "sbl_return_shares": 209_000,
        "sbl_balance_shares": 75_426_022,
        "note": None,
    }
    assert len(rows) == 8


def test_twse_day_trades_of_both_years():
    rows = sd.parse_twse_day_trade(DT_NEW, date(2026, 11, 26))
    assert rows["2330"] == {
        "day_trade_shares": 13_666_000,
        "day_trade_buy_value": 29_347_400_000.0,
        "day_trade_sell_value": 29_370_735_000.0,
        "sell_first_suspended": None,
    }
    assert rows["1201"]["sell_first_suspended"] == "Y"
    old = sd.parse_twse_day_trade(DT_2014, date(2014, 1, 6))
    assert old["1201"]["day_trade_shares"] == 0
    # The market table is not read as a security.
    assert all(code.isalnum() for code in old)


def test_tpex_day_trades_of_2014_have_no_mark_column():
    old = sd.parse_tpex_day_trade(TPEX_DT_2014, date(2014, 1, 6))
    assert old["1565"] == {
        "day_trade_shares": 11_000,
        "day_trade_buy_value": 9_232_000.0,
        "day_trade_sell_value": 9_237_000.0,
        "sell_first_suspended": None,
    }
    assert "1240" not in old
    new = sd.parse_tpex_day_trade(TPEX_DT_NEW, date(2026, 11, 26))
    assert new["1240"]["day_trade_shares"] == 0
    assert new["3105"]["sell_first_suspended"] is None  # " " is blank


def test_blank_and_dash_are_null_never_zero():
    payload = copy.deepcopy(SBL_NEW)
    payload["data"][1][9] = "-"
    payload["data"][1][10] = ""
    payload["data"][1][14] = "Z "
    row = sd.parse_twse_sbl(payload, date(2026, 11, 26))["1101"]
    assert row["sbl_sell_shares"] is None and row["sbl_return_shares"] is None
    assert row["note"] == "Z"
    assert row["sbl_balance_shares"] == 98_907_742


@pytest.mark.parametrize(
    "parser, payload, day",
    [
        (sd.parse_twse_sbl, SBL_NEW, date(2026, 11, 26)),
        (sd.parse_tpex_sbl, TPEX_SBL, date(2026, 11, 26)),
        (sd.parse_twse_day_trade, DT_NEW, date(2026, 11, 26)),
        (sd.parse_tpex_day_trade, TPEX_DT_NEW, date(2026, 11, 26)),
    ],
)
def test_a_reported_date_other_than_the_session_fails(parser, payload, day):
    with pytest.raises(sd.LayoutError, match="date"):
        parser(payload, date(2001, 1, 2))
    assert parser(payload, day)


def test_the_table_dates_must_match_too():
    tpex = copy.deepcopy(TPEX_DT_NEW)
    tpex["tables"][1]["date"] = "115/11/25"
    with pytest.raises(sd.LayoutError, match="table date"):
        sd.parse_tpex_day_trade(tpex, date(2026, 11, 26))
    twse = copy.deepcopy(DT_NEW)
    twse["tables"][1]["title"] = "115年11月25日 當日沖銷交易標的及成交量值"
    with pytest.raises(sd.LayoutError, match="title date"):
        sd.parse_twse_day_trade(twse, date(2026, 11, 26))


def test_unknown_columns_fail_the_day():
    renamed = copy.deepcopy(SBL_NEW)
    renamed["fields"][9] = "借券賣出"
    with pytest.raises(sd.LayoutError, match="unknown columns"):
        sd.parse_twse_sbl(renamed, date(2026, 11, 26))
    # The 14 columns with 當日還券 in place of 庫存異動 are neither layout.
    mixed = copy.deepcopy(SBL_OLD)
    mixed["fields"][10] = "當日還券"
    with pytest.raises(sd.LayoutError, match="unknown columns"):
        sd.parse_twse_sbl(mixed, date(2012, 3, 16))
    # TWSE has no five-column day trade layout.
    five = copy.deepcopy(DT_2014)
    five["tables"][1]["fields"].pop(2)
    for row in five["tables"][1]["data"]:
        row.pop(2)
    with pytest.raises(sd.LayoutError, match="unknown columns"):
        sd.parse_twse_day_trade(five, date(2014, 1, 6))


def test_an_unreadable_cell_or_count_fails_the_day():
    odd = copy.deepcopy(TPEX_SBL)
    odd["tables"][0]["data"][0][9] = "1.5"
    with pytest.raises(sd.LayoutError, match="share count"):
        sd.parse_tpex_sbl(odd, date(2026, 11, 26))
    negative = copy.deepcopy(SBL_NEW)
    negative["data"][0][12] = "-5"
    with pytest.raises(sd.LayoutError, match="unreadable value"):
        sd.parse_twse_sbl(negative, date(2026, 11, 26))
    short = copy.deepcopy(DT_NEW)
    short["tables"][1]["total"] = "7"
    with pytest.raises(sd.LayoutError, match="stated 7 rows"):
        sd.parse_twse_day_trade(short, date(2026, 11, 26))
    twice = copy.deepcopy(TPEX_DT_NEW)
    table = twice["tables"][1]
    table["data"].append(list(table["data"][0]))
    table["totalCount"] = str(len(table["data"]))
    with pytest.raises(sd.LayoutError, match="listed twice"):
        sd.parse_tpex_day_trade(twice, date(2026, 11, 26))


def test_the_twse_total_row_is_dropped_and_counted():
    for payload, day in (
        (SBL_NEW, date(2026, 11, 26)),
        (SBL_0319, date(2012, 3, 19)),
        (SBL_OLD, date(2012, 3, 16)),
    ):
        assert payload["data"][-1][:2] == ["", "合計"]
        assert payload["total"] == len(payload["data"])
        assert set(sd.parse_twse_sbl(payload, day)) == {
            "0050",
            "1101",
            "1102",
            "2317",
            "2330",
        }
    # 2008: no 合計 row, the old layout.
    assert SBL_2008["data"][-1][0] == "2330"
    old = sd.parse_twse_sbl(SBL_2008, date(2008, 7, 1))
    assert old["2330"] == {
        "sbl_sell_shares": 500_000,
        "sbl_return_shares": None,
        "sbl_balance_shares": 44_423_000,
        "note": None,
    }


def test_a_blank_code_other_than_the_last_total_row_fails():
    middle = copy.deepcopy(SBL_NEW)
    middle["data"].insert(2, middle["data"].pop())
    with pytest.raises(sd.LayoutError, match="without a code"):
        sd.parse_twse_sbl(middle, date(2026, 11, 26))
    renamed = copy.deepcopy(SBL_NEW)
    renamed["data"][-1][1] = "小計"
    with pytest.raises(sd.LayoutError, match="without a code"):
        sd.parse_twse_sbl(renamed, date(2026, 11, 26))
    # The total counts the 合計 row: one row fewer is a mismatch.
    short = copy.deepcopy(SBL_NEW)
    short["total"] = len(short["data"]) - 1
    with pytest.raises(sd.LayoutError, match="stated"):
        sd.parse_twse_sbl(short, date(2026, 11, 26))
    # Only TWT93U has one: a TPEx 合計 row is not dropped.
    tpex = copy.deepcopy(TPEX_SBL)
    table = tpex["tables"][0]
    table["data"].append(["", "合計", *table["data"][0][2:]])
    table["totalCount"] = len(table["data"])
    with pytest.raises(sd.LayoutError, match="without a code"):
        sd.parse_tpex_sbl(tpex, date(2026, 11, 26))


def test_an_empty_table_or_the_answer_before_the_first_day_fails():
    with pytest.raises(sd.LayoutError, match="stat"):
        sd.parse_twse_sbl(SBL_BEFORE, date(2005, 6, 30))
    empty = copy.deepcopy(TPEX_SBL)
    empty["tables"][0]["data"] = []
    empty["tables"][0]["totalCount"] = 0
    with pytest.raises(sd.LayoutError, match="no rows"):
        sd.parse_tpex_sbl(empty, date(2026, 11, 26))


def test_the_requests_of_the_four_feeds():
    day = date(2026, 11, 26)
    assert sd.request_of("twse-sbl", day) == (
        "GET",
        "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=20261126&response=json",
        None,
    )
    assert sd.request_of("twse-daytrade", day)[1].endswith(
        "dayTrading/TWTB4U?date=20261126&selectType=All&response=json"
    )
    assert sd.request_of("tpex-sbl", day)[2] == {
        "date": "2026/11/26",
        "response": "json",
    }
    method, url, form = sd.request_of("tpex-daytrade", day)
    assert method == "POST" and url.startswith(sd.TPEX_DAY_TRADE_ENDPOINT)
    assert form == {"date": "2026/11/26", "type": "Daily", "response": "json"}


# --- quiet times ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "taipei, wait_minutes",
    [
        ((12, 30), 0),
        ((22, 0), 90),  # the daily: to 23:30
        ((21, 15), 135),
        ((23, 30), 0),
        ((11, 50), 20),  # before noon: to 12:10
        ((12, 9), 1),
        ((12, 10), 0),
        ((13, 49), 0),  # 13 is odd; 14:00 is 11 minutes away
        ((13, 55), 15),
        ((23, 55), 15),  # midnight is even
        ((0, 5), 5),
        ((21, 0), 0),
        ((20, 55), 0),  # 21:00 is odd
        ((19, 50), 20),
    ],
)
def test_the_quiet_times(taipei, wait_minutes):
    hour, minute = taipei
    moment = datetime(2026, 11, 6, hour, minute) - (
        datetime(2026, 11, 6, 8) - datetime(2026, 11, 6, 0)
    )
    assert sd.quiet_wait_seconds(moment) == wait_minutes * 60


# --- the backfill -------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def add_instrument(db, exchange, symbol, days, *, kind="stock", volume=1000):
    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
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
                volume=volume,
                source=exchange.lower(),
            )
        )
    db.flush()
    return item


ANSWERS = {
    "twse-sbl": SBL_NEW,
    "tpex-sbl": TPEX_SBL,
    "twse-daytrade": DT_NEW,
    "tpex-daytrade": TPEX_DT_NEW,
}


class Fetcher:
    """Answers each feed with a fixture redated to the session, or an error."""

    def __init__(self, answers=None):
        self.answers = answers or ANSWERS
        self.calls: list[tuple[str, date]] = []

    def __call__(self, feed, day):
        self.calls.append((feed, day))
        answer = self.answers[feed]
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(day)
        return redate(answer, day)


# Final for both kinds: more than DAY_TRADE_FINAL_DAYS before NOON.
D1, D2 = date(2026, 10, 1), date(2026, 10, 2)


def seed(db):
    add_instrument(db, "TWSE", "1101", [D1, D2])
    add_instrument(db, "TWSE", "2330", [D1, D2])
    # Listed in neither TWSE table's fixture: no row, never a 0.
    add_instrument(db, "TWSE", "9999", [D1])
    add_instrument(db, "TPEx", "8069", [D1, D2])
    add_instrument(db, "TPEx", "1240", [D1])
    db.commit()


def run(factory, fetch, **kwargs):
    with factory() as db:
        return sd.backfill(
            db,
            date(2026, 1, 1),
            date(2026, 12, 31),
            fetch=fetch,
            now=lambda: NOON,
            sleep=lambda _s: pytest.fail("slept outside the quiet times"),
            **kwargs,
        )


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_a_backfill_writes_the_sessions_and_a_rerun_changes_nothing(factory):
    with factory() as db:
        seed(db)
    fetch = Fetcher()
    first = run(factory, fetch)
    assert first["status"] == "success"
    assert first["requests"] == 8 and len(fetch.calls) == 8
    sbl = first["feeds"]["twse-sbl"]
    # 1101 and 2330 on both days; 9999 has no row; 0050, 1102, 2317 unmatched.
    assert (sbl["inserted"], sbl["no_row"], sbl["unmatched"]) == (4, 1, 3 + 3)
    with factory() as db:
        row = db.scalar(
            select(SecuritiesLendingDaily)
            .join(Instrument)
            .where(
                Instrument.symbol == "2330", SecuritiesLendingDaily.trading_date == D1
            )
        )
        assert (row.sbl_sell_shares, row.sbl_return_shares) == (136_000, 12_000)
        assert (row.source, row.data_as_of) == ("twse_twt93u", D1)
        raw = db.get(RawPayload, row.raw_payload_id)
        assert raw.source == "twse" and "TWT93U?date=20261001" in raw.endpoint
        assert raw.collected_at == row.collected_at
        # No instrument was made for an unmatched code.
        assert db.scalar(select(func.count()).select_from(Instrument)) == 5
        nine = db.scalar(select(Instrument.id).where(Instrument.symbol == "9999"))
        for model in (SecuritiesLendingDaily, DayTradeDaily):
            assert not db.scalars(
                select(model).where(model.instrument_id == nine)
            ).all()
        tpex = db.scalars(
            select(DayTradeDaily).where(DayTradeDaily.source == "tpex_intraday_stat")
        ).all()
        # 8069 on both days and 1240 (listed with 0) on D1.
        assert sorted(r.day_trade_shares for r in tpex) == [0, 3_511_000, 3_511_000]
        assert {r.source for r in db.scalars(select(SecuritiesLendingDaily))} == {
            "twse_twt93u",
            "tpex_sbl",
        }
        manifest = db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == sd.DAY_RUN_TYPE)
        ).all()
        assert len(manifest) == 8 and {r.status for r in manifest} == {"success"}
        totals = (count(db, SecuritiesLendingDaily), count(db, DayTradeDaily))

    again = run(factory, Fetcher())
    assert again["status"] == "success"
    assert again["requests"] == 0 and again["changed"] == 0
    assert again["feeds"]["twse-sbl"]["done_before"] == 2

    reapplied = run(factory, Fetcher(), reapply=True)
    assert reapplied["requests"] == 0 and reapplied["changed"] == 0
    assert reapplied["feeds"]["twse-sbl"]["unchanged"] == 4
    assert reapplied["feeds"]["tpex-daytrade"]["reapplied"] == 2
    with factory() as db:
        assert (count(db, SecuritiesLendingDaily), count(db, DayTradeDaily)) == totals


def test_no_request_before_a_feeds_first_day(factory):
    days = [
        date(2005, 6, 30),
        date(2005, 7, 1),
        date(2012, 10, 1),
        date(2012, 10, 2),
        date(2014, 1, 3),
        date(2014, 1, 6),
    ]
    with factory() as db:
        add_instrument(db, "TWSE", "1101", days)
        add_instrument(db, "TPEx", "8069", days)
        db.commit()
    fetch = Fetcher()
    with factory() as db:
        result = sd.backfill(
            db, days[0], days[-1], fetch=fetch, now=lambda: NOON, sleep=lambda _s: None
        )
    asked = {(feed, day) for feed, day in fetch.calls}
    assert {day for feed, day in asked if feed == "twse-sbl"} == set(days[1:])
    assert {day for feed, day in asked if feed == "tpex-sbl"} == set(days[3:])
    for feed in ("twse-daytrade", "tpex-daytrade"):
        assert {day for f, day in asked if f == feed} == {days[-1]}
    assert result["feeds"]["twse-sbl"]["not_published"] == 1
    assert result["feeds"]["tpex-sbl"]["not_published"] == 3
    assert result["feeds"]["tpex-daytrade"]["not_published"] == 5


def test_a_wrong_reported_date_fails_the_session_and_is_asked_again(factory):
    with factory() as db:
        seed(db)
    stale = Fetcher(
        {**ANSWERS, "twse-sbl": lambda _day: redate(SBL_NEW, date(2026, 10, 30))}
    )
    result = run(factory, stale, feeds=["twse-sbl"])
    assert result["status"] == "partial"
    failed = result["feeds"]["twse-sbl"]
    assert failed["failed"] == 2 and failed["inserted"] == 0
    assert "reported date" in failed["failed_days"][0]["error"]
    with factory() as db:
        assert count(db, SecuritiesLendingDaily) == 0
        runs = db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == sd.DAY_RUN_TYPE)
        ).all()
        assert {r.status for r in runs} == {"failed"}
        # The answer is kept for reading what came.
        assert all(r.metadata_json["raw_payload_id"] for r in runs)
    fixed = Fetcher()
    retried = run(factory, fixed, feeds=["twse-sbl"])
    assert retried["status"] == "success" and len(fixed.calls) == 2


def test_a_code_dropped_from_a_reread_table_loses_its_row(factory):
    with factory() as db:
        seed(db)
    run(factory, Fetcher(), feeds=["tpex-daytrade"])
    without = copy.deepcopy(TPEX_DT_NEW)
    table = without["tables"][1]
    table["data"] = [row for row in table["data"] if row[0] != "1240"]
    table["totalCount"] = str(len(table["data"]))
    with factory() as db:
        for item in db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == sd.DAY_RUN_TYPE)
        ):
            # A failed day without a kept answer: asked again.
            item.status = "failed"
            item.metadata_json = {}
        db.commit()
    second = run(factory, Fetcher({"tpex-daytrade": without}), feeds=["tpex-daytrade"])
    assert second["feeds"]["tpex-daytrade"]["removed"] == 1
    with factory() as db:
        assert count(db, DayTradeDaily) == 2


def test_failed_requests_in_a_row_stop_the_run(factory):
    with factory() as db:
        for n in range(8):
            add_instrument(db, "TWSE", f"11{n:02d}", [date(2026, 10, 1 + n)])
        db.commit()
    fetch = Fetcher({"twse-sbl": sources.OfficialDataError("blocked")})
    result = run(factory, fetch, feeds=["twse-sbl"])
    assert result["aborted"] and len(fetch.calls) == sd.ABORT_AFTER_FAILURES
    assert result["status"] == "partial"


def test_a_request_in_a_quiet_time_waits(factory):
    with factory() as db:
        add_instrument(db, "TWSE", "1101", [D1])
        db.commit()
    # The plan reads the clock once; the request then meets 22:00 Taipei.
    moments = iter([NOON, datetime(2026, 11, 6, 14, 0)] + [NOON] * 10)
    slept: list[float] = []
    with factory() as db:
        sd.backfill(
            db,
            D1,
            D1,
            feeds=["twse-sbl"],
            fetch=Fetcher(),
            now=lambda: next(moments),
            sleep=slept.append,
        )
    assert slept == [90 * 60]


def test_the_tables_must_exist(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with sessionmaker(bind=engine)() as db, pytest.raises(ValueError, match="init-db"):
        sd.backfill(db, D1, D1, fetch=Fetcher(), now=lambda: NOON)
    engine.dispose()


def test_a_feed_whose_tables_stop_reading_stops(factory):
    days = [date(2026, 10, 1 + n) for n in range(8)]
    with factory() as db:
        add_instrument(db, "TWSE", "1101", days)
        add_instrument(db, "TPEx", "8069", days)
        db.commit()
    renamed = copy.deepcopy(SBL_NEW)
    renamed["fields"][9] = "借券賣出"
    fetch = Fetcher({**ANSWERS, "twse-sbl": renamed})
    result = run(factory, fetch, feeds=["twse-sbl", "tpex-sbl"])
    assert result["status"] == "partial" and result["aborted"] is None
    twse = result["feeds"]["twse-sbl"]
    assert twse["requested"] == sd.LAYOUT_STOP_AFTER
    assert twse["not_asked_after_stop"] == 8 - sd.LAYOUT_STOP_AFTER
    assert twse["stopped"]["first_date"] == "2026-10-01"
    assert "unknown columns" in twse["stopped"]["error"]
    # The other feed goes on.
    assert result["feeds"]["tpex-sbl"]["success"] == 8


def test_a_failed_day_rereads_its_stored_answer_before_asking(factory, monkeypatch):
    with factory() as db:
        seed(db)
    parser = sd.PARSERS["twse-sbl"]

    def unreadable(_payload, _day):
        raise sd.LayoutError("a parser that could not read it yet")

    monkeypatch.setitem(sd.PARSERS, "twse-sbl", unreadable)
    first = run(factory, Fetcher(), feeds=["twse-sbl"])
    assert first["feeds"]["twse-sbl"]["failed"] == 2
    monkeypatch.setitem(sd.PARSERS, "twse-sbl", parser)
    fixed = run(
        factory,
        Fetcher({"twse-sbl": sources.OfficialDataError("not asked")}),
        feeds=["twse-sbl"],
    )
    assert fixed["status"] == "success" and fixed["requests"] == 0
    assert fixed["feeds"]["twse-sbl"]["reread"] == 2
    with factory() as db:
        assert count(db, SecuritiesLendingDaily) == 4


def test_days_not_final_yet_are_not_asked(factory):
    # NOON is 2026-11-06 Taipei; the research DB has bars to 11-06.
    days = [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]
    days += [date(2026, 11, 5), date(2026, 11, 6)]
    with factory() as db:
        add_instrument(db, "TWSE", "1101", days)
        db.commit()
    fetch = Fetcher()
    result = run(factory, fetch, feeds=["twse-sbl", "twse-daytrade"])
    asked = {(feed, day) for feed, day in fetch.calls}
    # Lending: every day before today.
    assert {d for f, d in asked if f == "twse-sbl"} == set(days[:-1])
    assert result["feeds"]["twse-sbl"]["not_final"] == 1
    # Day trades: three later sessions (11-02 and 11-03 only).
    assert {d for f, d in asked if f == "twse-daytrade"} == set(days[:2])
    assert result["feeds"]["twse-daytrade"]["not_final"] == 3
    assert result["status"] == "success"


def test_finality_by_calendar_days():
    feed = sd.FEEDS["tpex-daytrade"]
    today = date(2026, 11, 27)
    assert not sd.is_final(feed, date(2026, 11, 14), 0, today)
    assert sd.is_final(feed, date(2026, 11, 13), 0, today)
    assert sd.is_final(feed, date(2026, 11, 24), 3, today)
    lending = sd.FEEDS["tpex-sbl"]
    assert sd.is_final(lending, date(2026, 11, 26), 0, today)
    assert not sd.is_final(lending, today, 5, today)


# --- the command ----------------------------------------------------------------------


def test_the_command_refuses_a_database_without_the_research_marker(
    tmp_path, monkeypatch, capsys
):
    from worker import cli

    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "stock.db")
    (tmp_path / "stock.db").write_bytes(b"")
    monkeypatch.setattr(
        "sys.argv",
        [
            "worker.cli",
            "sbl-daytrade",
            "backfill",
            "--start",
            "2026-11-02",
            "--end",
            "2026-11-02",
        ],
    )
    monkeypatch.setattr(
        cli,
        "run_sbl_daytrade_backfill",
        lambda *a, **k: pytest.fail("ran without the marker"),
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "research-db.json" in out["error"]
    (tmp_path / "research-db.json").write_text('{"purpose": "production"}\n')
    with pytest.raises(SystemExit):
        cli.main()
    assert json.loads(capsys.readouterr().out)["status"] == "refused"


def test_the_command_holds_maintenance_and_the_backfill_floor():
    import argparse

    from worker import cli

    args = argparse.Namespace(command="sbl-daytrade", sbl_daytrade_command="backfill")
    assert cli.maintenance_guarded(args) == "sbl-daytrade backfill"
    assert cli.backfill_command(args) == "sbl-daytrade backfill"


def test_the_run_keeps_three_and_a_half_seconds_and_restores_the_floor(monkeypatch):
    seen = []
    monkeypatch.setattr(
        sd,
        "backfill",
        lambda *a, **k: seen.append(sources._minimum_host_interval) or {},
    )
    before = sources._minimum_host_interval
    sd.run_sbl_daytrade_backfill("2026-11-02", "2026-11-02")
    assert seen == [sd.REQUEST_INTERVAL_SECONDS]
    assert sources._minimum_host_interval == before


# --- the migration --------------------------------------------------------------------


def test_the_migration_adds_two_empty_tables_and_goes_down_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    from app import migrations
    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith("_sbl_day_trade"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    tables = {"securities_lending_daily", "day_trade_daily"}
    try:
        command.upgrade(config, revision)
        assert tables <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            for table in tables:
                assert (
                    connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()
                    == 0
                )
            indexes = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        assert {
            f"ix_{table}_{column}"
            for table in tables
            for column in ("trading_date", "raw_payload_id")
        } <= indexes
        command.downgrade(config, previous)
        assert not tables & set(inspect(engine).get_table_names())
        command.upgrade(config, revision)
        assert tables <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
