"""Attention notices and disposals of the research database (Issue #1090).

The fixtures under ``fixtures/trading_notices`` are answers of the #1086 probe
(2026-11-27, evidence/1086/probe), trimmed to a few rows of one month, with the
answered period (TWSE ``params``, TPEx ``date``) set to this command's window
and TWSE ``total`` to the rows kept:

- ``twse_notice_202011``: 1220 (﹝第九款﹞ in a ``<font>`` tag), 2009 (第一、五款),
  2038 (本益比 ``-----``), 6153; ``twse_notice_200805``: the 2008 answer
  (two-digit ROC years ``97.05.16``).
- ``tpex_attention_202011``: 11/30 of 3522, 3552, 3228 (with 款次);
  ``tpex_attention_200810``: three rows without 款次 and the placeholder rows
  「本日無公布注意交易資訊」.
- ``twse_punish_202011`` (window 11/01～12/31): 2321 (announced 10/21), 1414,
  1456 (11/27 and 12/02), 1475 (12/24); ``twse_punish_200805``: blank 處置內容,
  處置措施 「收足五成款券」.
- ``tpex_disposal_202011`` (window 11/01～12/31): 4419 (10/30), 3228 (11/27),
  5468 and 6244 (announced 11/30, from 12/01), placeholders of 11/18 and 12/28;
  the TWSE punish answers have no ``params``: their title names the period.
  ``tpex_disposal_200805``: 2008, no 處置措施, placeholders.
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
    IngestionRun,
    Instrument,
    RawPayload,
    TradingAttention,
    TradingDisposal,
)
from worker import sources
from worker import trading_notices as tn

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "trading_notices"


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


NOTICE_NEW, NOTICE_OLD = load("twse_notice_202011"), load("twse_notice_200805")
ATTENTION_NEW, ATTENTION_OLD = (
    load("tpex_attention_202011"),
    load("tpex_attention_200810"),
)
PUNISH_NEW, PUNISH_OLD = load("twse_punish_202011"), load("twse_punish_200805")
DISPOSAL_NEW, DISPOSAL_OLD = (
    load("tpex_disposal_202011"),
    load("tpex_disposal_200805"),
)
NOV, DEC = date(2020, 11, 1), date(2020, 12, 1)
# 2026-11-27 11:30 Taipei: away from the quiet and the even hours.
MORNING = datetime(2026, 11, 27, 3, 30)


def feed(name):
    return tn.FEEDS[name]


def rewindow(payload, feed_name, month):
    """The answer as if asked for ``month`` of the feed: its period rewritten."""

    first, last = tn.window(feed(feed_name), month)
    result = copy.deepcopy(payload)
    if "tables" in result:
        result["date"] = f"{first:%Y%m%d}~{last:%Y%m%d}"
    elif "params" in result:
        result["params"].update(startDate=f"{first:%Y%m%d}", endDate=f"{last:%Y%m%d}")
    else:
        roc = "{}/{:%m/%d}"
        result["title"] = (
            f"公布處置有價證券資訊 ({roc.format(first.year - 1911, first)} 至 "
            f"{roc.format(last.year - 1911, last)})"
        )
    return result


# --- cells ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, value",
    [
        ("5", 5),
        ("45", 45),
        ("五", 5),
        ("十", 10),
        ("二十", 20),
        ("廿五", 25),
        ("四十五", 45),
        ("六十", 60),
        ("二百七十", 270),
        ("十一", 11),
        ("二五", None),
        ("", None),
    ],
)
def test_numerals(text, value):
    assert tn.numeral(text) == value


def test_clause_interval_and_prepayment_unread_are_null():
    assert tn.clauses_of("最近六個營業日累積之最後成交價跌幅達31.41%") is None
    # A 款 outside brackets (an article of the rules) is no 款次.
    assert tn.clauses_of("達本中心作業要點第四條第一項第一款") is None
    assert tn.clauses_of("漲幅達59.03%(第一款)<br>比率為46.74%(第五款)") == "1,5"
    assert tn.interval_of(None) is None
    assert tn.interval_of("各證券商自九十三年十二月二十三日起每日買進") is None
    # Two different intervals: which one holds is not said.
    assert tn.interval_of("約每五分鐘撮合一次，其後約每二十分鐘撮合一次") is None
    assert tn.interval_of("（約每5分鐘撮合一次）") == 5
    assert tn.prepayment_of(None) is None
    assert tn.prepayment_of("") is None
    assert tn.prepayment_of("申報金額總公司不得超過新台幣四千萬元") is False
    assert tn.prepayment_of("應就其當日已委託之買賣，向該投資人收取全部之買進價金")


# --- parsers ------------------------------------------------------------------------


def test_twse_notice_current_layout_and_no_cumulative():
    parsed = tn.parse(feed("twse-notice"), NOTICE_NEW, NOV)
    assert parsed.empty_days == set()
    row = parsed.rows[("1220", date(2020, 11, 16))]
    assert row["clauses"] == "9" and "<font" not in row["detail"]
    assert row["detail"].endswith("﹝第九款﹞。")
    assert (row["close_price"], row["pe_ratio"]) == (12.40, 12.92)
    assert parsed.rows[("2009", date(2020, 11, 30))]["clauses"] == "1,5"
    assert parsed.rows[("2038", date(2020, 11, 30))]["pe_ratio"] is None
    # 累計次數 is in the answer but counts within the query period.
    assert {r["cumulative_count"] for r in parsed.rows.values()} == {None}


def test_twse_notice_2008_layout():
    parsed = tn.parse(feed("twse-notice"), NOTICE_OLD, date(2008, 5, 1))
    assert len(parsed.rows) == len(NOTICE_OLD["data"])
    days = {key[1] for key in parsed.rows}
    assert days and all(day.year == 2008 and day.month == 5 for day in days)
    assert all(r["clauses"] for r in parsed.rows.values())


def test_tpex_attention_current_layout_keeps_cumulative():
    parsed = tn.parse(feed("tpex-attention"), ATTENTION_NEW, NOV)
    row = parsed.rows[("3522", date(2020, 11, 30))]
    assert row["clauses"] == "1,5" and row["cumulative_count"] == 11
    assert "<br>" not in row["detail"] and "\n" in row["detail"]
    assert row["pe_ratio"] is None  # N/A


def test_tpex_attention_2008_has_no_clauses_and_placeholders_are_empty_days():
    parsed = tn.parse(feed("tpex-attention"), ATTENTION_OLD, date(2008, 10, 1))
    assert {r["clauses"] for r in parsed.rows.values()} == {None}
    assert all(code for code, _ in parsed.rows)
    assert parsed.empty_days == {
        date(2008, 10, 14),
        date(2008, 10, 15),
        date(2008, 10, 16),
        date(2008, 10, 24),
    }
    assert parsed.answer_rows == len(ATTENTION_OLD["tables"][0]["data"])


def test_twse_punish_2008_blank_content_is_null_not_guessed():
    parsed = tn.parse(feed("twse-punish"), PUNISH_OLD, date(2008, 5, 1))
    row = parsed.rows[("1227", date(2008, 5, 13), date(2008, 5, 14))]
    assert row["end_date"] == date(2008, 5, 20)
    assert row["measure"] == "收足五成款券"
    assert (row["detail"], row["match_interval_minutes"], row["prepayment"]) == (
        None,
        None,
        None,
    )
    assert row["reason"] == "連續五次" and row["cumulative_count"] is None


def test_twse_punish_current_layout():
    parsed = tn.parse(feed("twse-punish"), PUNISH_NEW, NOV)
    row = parsed.rows[("1414", date(2020, 11, 10), date(2020, 11, 11))]
    assert row["end_date"] == date(2020, 11, 24)
    assert (row["match_interval_minutes"], row["prepayment"]) == (5, True)
    assert row["measure"] == "第一次處置" and row["cumulative_count"] is None
    assert row["reason"] == "最近十個營業日已有六次"


def test_tpex_disposal_layouts():
    new = tn.parse(feed("tpex-disposal"), DISPOSAL_NEW, NOV)
    row = new.rows[("3228", date(2020, 11, 27), date(2020, 11, 30))]
    assert row["security_name"] == "金麗科"
    assert (row["match_interval_minutes"], row["prepayment"]) == (5, True)
    assert row["cumulative_count"] == 1
    assert new.empty_days == {date(2020, 11, 18), date(2020, 12, 28)}
    old = tn.parse(feed("tpex-disposal"), DISPOSAL_OLD, date(2008, 5, 1))
    assert old.rows and {r["measure"] for r in old.rows.values()} == {None}
    assert all(r["match_interval_minutes"] for r in old.rows.values())
    assert old.empty_days


def test_the_disposal_window_runs_to_the_next_months_end():
    assert tn.window(feed("tpex-disposal"), NOV) == (NOV, date(2020, 12, 31))
    assert tn.window(feed("twse-punish"), date(2020, 12, 1)) == (
        date(2020, 12, 1),
        date(2021, 1, 31),
    )
    assert tn.window(feed("twse-notice"), NOV) == (NOV, date(2020, 11, 30))
    url, form = tn.request_of(feed("tpex-disposal"), NOV)
    assert form == {
        "startDate": "2020/11/01",
        "endDate": "2020/12/31",
        "response": "json",
    }
    assert url.endswith(
        "disposal?startDate=2020/11/01&endDate=2020/12/31&response=json"
    )
    url, form = tn.request_of(feed("twse-notice"), NOV)
    assert form is None and "startDate=20201101&endDate=20201130" in url


@pytest.mark.parametrize(
    "name, payload",
    [
        ("twse-notice", NOTICE_NEW),
        ("twse-punish", PUNISH_NEW),
        ("tpex-attention", ATTENTION_NEW),
        ("tpex-disposal", DISPOSAL_NEW),
    ],
)
def test_unknown_columns_or_another_period_fail_the_month(name, payload):
    changed = copy.deepcopy(payload)
    fields = (
        changed["tables"][0]["fields"] if "tables" in changed else changed["fields"]
    )
    fields[2] = "名稱"
    with pytest.raises(tn.LayoutError, match="unknown columns"):
        tn.parse(feed(name), changed, NOV)
    with pytest.raises(tn.LayoutError, match="period"):
        tn.parse(feed(name), payload, DEC)


def test_a_row_outside_the_window_or_an_unknown_blank_row_fails():
    changed = copy.deepcopy(NOTICE_NEW)
    changed["data"][0][5] = "109.12.01"
    with pytest.raises(tn.LayoutError, match="outside the query period"):
        tn.parse(feed("twse-notice"), changed, NOV)
    changed = copy.deepcopy(ATTENTION_OLD)
    blank = next(r for r in changed["tables"][0]["data"] if not r[1].strip())
    blank[4] = "系統維護中"
    with pytest.raises(tn.LayoutError, match="without a code"):
        tn.parse(feed("tpex-attention"), changed, date(2008, 10, 1))
    changed = copy.deepcopy(NOTICE_NEW)
    changed["data"][1] = [*changed["data"][0]]
    changed["data"][1][6] = "99.00"
    with pytest.raises(tn.LayoutError, match="two different rows"):
        tn.parse(feed("twse-notice"), changed, NOV)


# --- the backfill ------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def add_instrument(db, exchange, symbol, kind="stock", status="active"):
    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
        status=status,
    )
    db.add(item)
    db.flush()
    return item


def seed(db):
    for symbol in ("1220", "2009", "2038", "1414", "1456", "1475", "2321"):
        add_instrument(db, "TWSE", symbol)
    for symbol in ("3522", "3552", "3228", "4419", "5468"):
        add_instrument(db, "TPEx", symbol)
    # 6244 is listed on TWSE only here: the TPEx row must not take it.
    add_instrument(db, "TWSE", "6244")
    db.commit()


ANSWERS = {
    ("twse-notice", NOV): NOTICE_NEW,
    ("twse-punish", NOV): PUNISH_NEW,
    ("tpex-attention", NOV): ATTENTION_NEW,
    ("tpex-disposal", NOV): DISPOSAL_NEW,
}


class Fetcher:
    def __init__(self, answers=None):
        self.answers = dict(ANSWERS if answers is None else answers)
        self.calls: list[tuple[str, date]] = []

    def __call__(self, feed_, month):
        self.calls.append((feed_.name, month))
        answer = self.answers.get((feed_.name, month))
        if answer is None:
            raise RuntimeError(f"no answer for {feed_.name} {month}")
        if isinstance(answer, Exception):
            raise answer
        return copy.deepcopy(answer)


def run(factory, fetch, start=NOV, end=NOV, **kwargs):
    with factory() as db:
        return tn.backfill(
            db,
            start,
            end,
            fetch=fetch,
            now=lambda: MORNING,
            sleep=lambda _s: pytest.fail("slept outside the quiet hours"),
            **kwargs,
        )


def test_a_backfill_writes_the_month_and_a_rerun_changes_nothing(factory):
    with factory() as db:
        seed(db)
    fetch = Fetcher()
    first = run(factory, fetch)
    assert first["status"] == "success", first
    assert first["requests"] == 4 and len(fetch.calls) == 4
    with factory() as db:
        notices = db.scalars(
            select(TradingAttention).where(TradingAttention.source == "twse_notice")
        ).all()
        assert len(notices) == len(NOTICE_NEW["data"])
        by_code = {r.symbol: r for r in notices}
        assert by_code["1220"].instrument_id is not None
        # 6153 is no instrument here: kept with the code, no instrument.
        assert by_code["6153"].instrument_id is None
        assert by_code["1220"].data_as_of == date(2020, 11, 16)
        raw = db.get(RawPayload, by_code["1220"].raw_payload_id)
        assert raw.source == "twse" and "announcement/notice?" in raw.endpoint
        assert raw.collected_at == by_code["1220"].collected_at
        tpex = db.scalars(
            select(TradingDisposal).where(TradingDisposal.source == "tpex_disposal")
        ).all()
        # 4419 (10/30) belongs to October; the 11/30 ones starting 12/01 are here.
        assert sorted((r.symbol, r.announced_date.day) for r in tpex) == [
            ("3228", 27),
            ("5468", 30),
            ("6244", 30),
        ]
        assert {r.symbol: r.instrument_id is None for r in tpex}["6244"] is True
        manifest = db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == tn.MONTH_RUN_TYPE)
        ).all()
        assert len(manifest) == 4 and {r.status for r in manifest} == {"success"}
        disposal_run = next(r for r in manifest if r.source == "tpex-disposal")
        assert disposal_run.metadata_json["empty_days"] == ["2020-11-18"]
        assert disposal_run.metadata_json["other_month"] == 1
        assert disposal_run.data_as_of == "2020-11-01~2020-12-31"
    assert first["feeds"]["tpex-disposal"]["empty_days"] == 1

    again = run(factory, Fetcher())
    assert again["status"] == "success"
    assert again["requests"] == 0 and again["changed"] == 0
    assert again["feeds"]["twse-notice"]["done_before"] == 1

    reapplied = run(factory, Fetcher({}), reapply=True)
    assert reapplied["status"] == "success", reapplied
    assert reapplied["requests"] == 0 and reapplied["changed"] == 0
    assert reapplied["feeds"]["twse-punish"]["reapplied"] == 1


def test_overlapping_disposal_months_give_each_period_once(factory):
    with factory() as db:
        seed(db)
    answers = {
        ("twse-punish", NOV): PUNISH_NEW,
        # December's answer has the November rows still in force as well.
        ("twse-punish", DEC): rewindow(PUNISH_NEW, "twse-punish", DEC),
    }
    result = run(factory, Fetcher(answers), end=DEC, feeds=["twse-punish"])
    assert result["status"] == "success", result
    assert result["requests"] == 2
    with factory() as db:
        rows = db.execute(
            select(
                TradingDisposal.symbol,
                TradingDisposal.announced_date,
                TradingDisposal.start_date,
            ).order_by(TradingDisposal.announced_date)
        ).all()
        keys = [(s, a.isoformat(), b.isoformat()) for s, a, b in rows]
        assert keys == [
            ("1414", "2020-11-10", "2020-11-11"),
            ("1456", "2020-11-27", "2020-11-30"),
            ("1456", "2020-12-02", "2020-12-03"),
            ("1475", "2020-12-24", "2020-12-25"),
        ]
        assert db.scalar(select(func.count()).select_from(TradingDisposal)) == 4


def test_a_row_gone_from_the_source_is_removed_on_reread(factory):
    with factory() as db:
        seed(db)
    run(factory, Fetcher({("twse-notice", NOV): NOTICE_NEW}), feeds=["twse-notice"])
    with factory() as db:
        for row in db.scalars(select(IngestionRun)):
            row.status = "failed"
        db.commit()
    smaller = copy.deepcopy(NOTICE_NEW)
    smaller["data"] = smaller["data"][1:]
    smaller["total"] = len(smaller["data"])
    result = run(
        factory, Fetcher({("twse-notice", NOV): smaller}), feeds=["twse-notice"]
    )
    assert result["feeds"]["twse-notice"]["removed"] == 1
    assert result["feeds"]["twse-notice"]["unchanged"] == len(smaller["data"])


def test_a_month_that_does_not_read_writes_nothing_and_is_asked_again(factory):
    with factory() as db:
        seed(db)
    broken = copy.deepcopy(NOTICE_NEW)
    broken["fields"][4] = "內容"
    result = run(
        factory, Fetcher({("twse-notice", NOV): broken}), feeds=["twse-notice"]
    )
    assert result["status"] == "partial"
    assert result["feeds"]["twse-notice"]["failed_months"][0]["month"] == "2020-11"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TradingAttention)) == 0
        month = db.scalar(select(IngestionRun))
        assert month.status == "failed" and "unknown columns" in month.error
        # The capture that did not read is kept for reading what came.
        assert db.get(RawPayload, month.metadata_json["raw_payload_id"])
    again = run(factory, Fetcher(), feeds=["twse-notice"])
    assert again["status"] == "success" and again["requests"] == 1


def test_max_requests_stops_and_the_next_run_goes_on(factory):
    with factory() as db:
        seed(db)
    first = run(factory, Fetcher(), max_requests=2)
    assert first["status"] == "partial" and first["requests"] == 2
    assert first["remaining_months"] == 2 and "max-requests" in first["stopped"]
    second = run(factory, Fetcher())
    assert second["status"] == "success" and second["requests"] == 2


def test_failed_requests_in_a_row_stop_the_run(factory):
    answers = {
        (name, date(2020, month, 1)): RuntimeError("503")
        for name in tn.FEEDS
        for month in (1, 2)
    }
    result = run(
        factory, Fetcher(answers), start=date(2020, 1, 1), end=date(2020, 2, 1)
    )
    assert result["requests"] == tn.ABORT_AFTER_FAILURES
    assert "in a row" in result["stopped"] and result["status"] == "partial"


def test_no_request_before_a_feeds_first_month(factory):
    fetch = Fetcher({("twse-notice", date(2001, 1, 1)): RuntimeError("x")})
    result = run(
        factory,
        fetch,
        start=date(2000, 6, 1),
        end=date(2001, 1, 1),
        feeds=["twse-notice", "tpex-disposal"],
    )
    assert fetch.calls == [("twse-notice", date(2001, 1, 1))]
    assert result["feeds"]["tpex-disposal"]["months"] == 0


def test_only_complete_months(factory):
    with factory() as db, pytest.raises(ValueError, match="not a complete month"):
        tn.backfill(db, date(2026, 11, 1), date(2026, 11, 1), now=lambda: MORNING)
    assert tn.latest_complete_month(MORNING) == date(2026, 10, 1)
    # 2026-11-30 17:00 UTC is 12-01 01:00 Taipei: November is complete.
    assert tn.latest_complete_month(datetime(2026, 11, 30, 17, 0)) == date(2026, 11, 1)


@pytest.mark.parametrize(
    "taipei, wait_minutes",
    [
        ((11, 30), 0),
        ((13, 49), 0),
        ((13, 55), 15),
        ((14, 5), 5),
        ((14, 10), 0),
        ((15, 55), 15),
        ((16, 59), 0),
        ((21, 14), 0),
        ((21, 15), 135),
        ((23, 29), 1),
        ((23, 50), 0),  # exactly 10 minutes before: outside
        ((23, 51), 19),
        ((0, 5), 5),
        ((19, 55), 15),
        ((20, 55), 0),
    ],
)
def test_the_wait_for_the_quiet_and_the_even_hours(taipei, wait_minutes):
    hour, minute = taipei
    moment = datetime(2026, 11, 27, hour, minute, tzinfo=tn.TAIPEI)
    assert tn.seconds_to_wait(moment) == wait_minutes * 60


def test_a_request_in_the_quiet_hours_waits(factory):
    slept = []
    with factory() as db:
        tn.backfill(
            db,
            NOV,
            NOV,
            feeds=["twse-notice"],
            fetch=Fetcher(),
            now=lambda: datetime(2026, 11, 27, 13, 20),  # 21:20 Taipei
            sleep=slept.append,
        )
    assert slept == [130 * 60]


def test_the_tables_must_exist(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with sessionmaker(bind=engine)() as db, pytest.raises(ValueError, match="init-db"):
        tn.backfill(db, NOV, NOV, fetch=Fetcher(), now=lambda: MORNING)
    engine.dispose()


# --- the command --------------------------------------------------------------------


def test_the_command_refuses_a_database_without_the_research_marker(
    tmp_path, monkeypatch, capsys
):
    from worker import cli

    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "stock.db")
    (tmp_path / "stock.db").write_bytes(b"")
    monkeypatch.setattr(
        "sys.argv",
        ["worker.cli", "trading-notices", "backfill", "--end-month", "2020-11"],
    )
    monkeypatch.setattr(
        cli,
        "run_trading_notices_backfill",
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

    args = argparse.Namespace(
        command="trading-notices", trading_notices_command="backfill"
    )
    assert cli.maintenance_guarded(args) == "trading-notices backfill"
    assert cli.backfill_command(args) == "trading-notices backfill"


def test_the_run_keeps_three_and_a_half_seconds_and_restores_the_floor(monkeypatch):
    seen = []
    monkeypatch.setattr(
        tn,
        "backfill",
        lambda *a, **k: seen.append(sources._minimum_host_interval) or {},
    )
    before = sources._minimum_host_interval
    tn.run_trading_notices_backfill("2020-11", "2020-11")
    assert seen == [tn.REQUEST_INTERVAL_SECONDS]
    assert sources._minimum_host_interval == before
    assert tn.run_trading_notices_backfill("2020-13")["status"] == "failed"


# --- the migration --------------------------------------------------------------------


def test_the_migration_adds_two_empty_tables_and_goes_down_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    from app import migrations
    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith("_trading_notices"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    tables = {"trading_attentions", "trading_disposals"}
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
            "ix_trading_attentions_attention_date",
            "ix_trading_attentions_raw_payload_id",
            "ix_trading_attentions_instrument_id",
            "ix_trading_disposals_announced_date",
            "ix_trading_disposals_start_date",
            "ix_trading_disposals_raw_payload_id",
            "ix_trading_disposals_instrument_id",
        } <= indexes
        command.downgrade(config, previous)
        assert not tables & set(inspect(engine).get_table_names())
        command.upgrade(config, revision)
        assert tables <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
