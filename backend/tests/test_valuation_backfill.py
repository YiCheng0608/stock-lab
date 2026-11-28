"""Daily P/B and issued shares of the research database (Issue #1075).

The fixtures under ``fixtures/valuation`` are answers of the #1074 probe
(2026-11-27, evidence/1074/raw), trimmed to a few codes with ``total`` /
``totalCount`` set to the rows kept and TPEx's notes cut to one:

- ``bwibbu_d_20180702``: TWSE, the layout with 收盤價、股利年度、財報年/季
  (1108 本益比 ``-``, 3711 股價淨值比 ``-``); ``bwibbu_d_20050902``: the first day,
  the older five columns; ``bwibbu_d_20040211_before_first``: the answer before it.
- ``pe_qry_date_20261126``: TPEx with 財報年/季 (1569 本益比 ``N/A``);
  ``pe_qry_date_20070423``: without it (1408 本益比、股價淨值比 ``N/A``).
- ``mi_qfiis_20040211`` (外資) and ``mi_qfiis_20261126`` (外資及陸資).
- ``mi_qfiis_20130701`` and ``mi_qfiis_20240701``: the rows the #1117 scan kept
  (evidence/1117/out/qfiis_samples.json), 0050 holding 0 shares in 2013 and the
  MOPS link around 異動原因 2 in 2024 (Issue #1121).
- ``qfii_20180702``: TPEx ``insti/qfii`` (evidence/1117/raw), 6497 已達上限,
  4413 禁止投資, 3147 holding 0 shares; ``qfii_20070423_empty``: the empty table
  before 2007-05-10.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ForeignHoldingsDaily,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    SharesOutstandingDaily,
    ValuationDaily,
)
from worker import sources
from worker import valuation_backfill as vb

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / "valuation" / name).read_text(encoding="utf-8"))


BW_NEW = load("bwibbu_d_20180702.json")
BW_OLD = load("bwibbu_d_20050902.json")
BW_BEFORE = load("bwibbu_d_20040211_before_first.json")
PE_NEW = load("pe_qry_date_20261126.json")
PE_OLD = load("pe_qry_date_20070423.json")
Q_OLD = load("mi_qfiis_20040211.json")
Q_NEW = load("mi_qfiis_20261126.json")
DAILY_QUOTES = json.loads(
    (FIXTURES / "tpex_daily_quotes" / "dailyquotes_20111101.json").read_text(
        encoding="utf-8"
    )
)
OA_QUOTES = json.loads(
    (FIXTURES / "tpex_openapi" / "oa_quotes_20261109.json").read_text(encoding="utf-8")
)
# 2026-11-06 12:00 Taipei: outside the quiet hours.
NOON = datetime(2026, 11, 6, 4, 0)


def redate(payload, day: date):
    """The answer as if for ``day``: the reported dates rewritten."""

    result = copy.deepcopy(payload)
    result["date"] = day.strftime("%Y%m%d")
    for table in result.get("tables", []):
        table["date"] = f"{day.year - 1911}/{day:%m/%d}"
    return result


# --- parsers ----------------------------------------------------------------------


def test_twse_pb_reads_both_layouts_and_blank_cells_are_null():
    new = vb.parse_twse_pb(BW_NEW, date(2018, 7, 2))
    assert new["1101"] == {
        "pb_ratio": 1.19,
        "pe_ratio": 18.28,
        "dividend_yield": 5.97,
        "report_period": "2018Q1",
    }
    assert new["1108"]["pe_ratio"] is None and new["1108"]["pb_ratio"] == 0.73
    assert new["3711"]["pb_ratio"] is None
    old = vb.parse_twse_pb(BW_OLD, date(2005, 9, 2))
    assert old["1101"] == {
        "pb_ratio": 1.07,
        "pe_ratio": 16.92,
        "dividend_yield": 5.91,
        "report_period": None,
    }
    assert old["1103"]["pe_ratio"] is None and old["1103"]["dividend_yield"] == 0.0


def test_tpex_pb_reads_both_layouts_and_na_is_null():
    new = vb.parse_tpex_pb(PE_NEW, date(2026, 11, 26))
    assert new["1240"] == {
        "pb_ratio": 1.57,
        "pe_ratio": 11.15,
        "dividend_yield": 0.97,
        "report_period": "2026Q3",
    }
    assert new["1569"]["pe_ratio"] is None and new["1569"]["pb_ratio"] == 3.72
    old = vb.parse_tpex_pb(PE_OLD, date(2007, 4, 23))
    assert old["1408"] == {
        "pb_ratio": None,
        "pe_ratio": None,
        "dividend_yield": 0.0,
        "report_period": None,
    }
    assert old["1333"]["pb_ratio"] == 2.07


def test_twse_shares_read_both_layouts():
    assert vb.parse_twse_shares(Q_OLD, date(2004, 2, 11))["0050"] == {
        "shares_issued": 872_000_000
    }
    new = vb.parse_twse_shares(Q_NEW, date(2026, 11, 26))
    assert set(new) == {"0050", "1101", "2330"}
    assert all(isinstance(v["shares_issued"], int) for v in new.values())


def test_tpex_quote_tables_give_issued_shares():
    web = vb.parse_tpex_quote_shares(DAILY_QUOTES, date(2011, 11, 1))
    assert web["006201"] == {"shares_issued": 115_446_000}
    api = vb.parse_tpex_quote_shares(OA_QUOTES, date(2026, 11, 9))
    assert api["00411A"] == {"shares_issued": 469_576_000}
    with pytest.raises(vb.LayoutError, match="row date"):
        vb.parse_tpex_quote_shares(OA_QUOTES, date(2026, 11, 10))


@pytest.mark.parametrize(
    "parser, payload, day",
    [
        (vb.parse_twse_pb, BW_NEW, date(2018, 7, 2)),
        (vb.parse_tpex_pb, PE_NEW, date(2026, 11, 26)),
        (vb.parse_twse_shares, Q_NEW, date(2026, 11, 26)),
        (vb.parse_tpex_quote_shares, DAILY_QUOTES, date(2011, 11, 1)),
    ],
)
def test_a_reported_date_other_than_the_session_fails(parser, payload, day):
    with pytest.raises(vb.LayoutError, match="date"):
        parser(payload, date(2001, 1, 2))
    assert parser(payload, day)


def test_the_tpex_table_date_must_match_too():
    payload = copy.deepcopy(PE_NEW)
    payload["tables"][0]["date"] = "115/11/25"
    with pytest.raises(vb.LayoutError, match="table date"):
        vb.parse_tpex_pb(payload, date(2026, 11, 26))


def test_unknown_columns_fail_the_day():
    renamed = copy.deepcopy(BW_NEW)
    renamed["fields"][6] = "淨值比"
    with pytest.raises(vb.LayoutError, match="unknown columns"):
        vb.parse_twse_pb(renamed, date(2018, 7, 2))
    extra = copy.deepcopy(PE_OLD)
    extra["tables"][0]["fields"].append("備註")
    with pytest.raises(vb.LayoutError):
        vb.parse_tpex_pb(extra, date(2007, 4, 23))
    # The TWSE layout is no TPEx one.
    with pytest.raises(vb.LayoutError):
        vb.parse_twse_shares(redate(BW_NEW, date(2018, 7, 2)), date(2018, 7, 2))


def test_an_unreadable_cell_fails_the_day_instead_of_null():
    odd = copy.deepcopy(BW_NEW)
    odd["data"][0][6] = "X1.2"
    with pytest.raises(vb.LayoutError, match="unreadable value"):
        vb.parse_twse_pb(odd, date(2018, 7, 2))
    period = copy.deepcopy(BW_NEW)
    period["data"][0][7] = "107Q1"
    with pytest.raises(vb.LayoutError, match="statement period"):
        vb.parse_twse_pb(period, date(2018, 7, 2))


def test_the_answer_before_the_first_day_is_no_table():
    with pytest.raises(vb.LayoutError, match="stat"):
        vb.parse_twse_pb(BW_BEFORE, date(2004, 2, 11))


def test_zero_or_blank_shares_are_null():
    assert vb._shares("0") is None and vb._shares("") is None
    assert vb._shares("1,234") == 1234
    with pytest.raises(vb.LayoutError):
        vb._shares("12.5")


# --- the backfill -------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def add_instrument(db, exchange, symbol, days, *, raw_id=None, kind="stock"):
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
                volume=1,
                source=exchange.lower(),
                raw_payload_id=raw_id,
            )
        )
    db.flush()
    return item


class Fetcher:
    """Answers each feed with a fixture redated to the session, or an error."""

    def __init__(self, answers=None):
        self.answers = answers or {
            "twse-pb": BW_NEW,
            "twse-shares": Q_NEW,
            "tpex-pb": PE_NEW,
        }
        self.calls: list[tuple[str, date]] = []

    def __call__(self, feed, day):
        self.calls.append((feed, day))
        answer = self.answers[feed]
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(day)
        return redate(answer, day)


D1, D2 = date(2018, 7, 2), date(2018, 7, 3)


def seed(db):
    add_instrument(db, "TWSE", "1101", [D1, D2])
    add_instrument(db, "TWSE", "2330", [D1, D2])
    add_instrument(db, "TWSE", "1108", [D1])
    add_instrument(db, "TPEx", "1240", [D1, D2])
    add_instrument(db, "TPEx", "1569", [D1])
    db.commit()


def run(factory, fetch, **kwargs):
    kwargs.setdefault("feeds", ["twse-pb", "twse-shares", "tpex-pb"])
    with factory() as db:
        return vb.backfill(
            db,
            date(2018, 1, 1),
            date(2018, 12, 31),
            fetch=fetch,
            now=lambda: NOON,
            sleep=lambda _s: pytest.fail("slept outside the quiet hours"),
            **kwargs,
        )


def test_a_backfill_writes_the_sessions_and_a_rerun_changes_nothing(factory):
    with factory() as db:
        seed(db)
    fetch = Fetcher()
    first = run(factory, fetch)
    assert first["status"] == "success"
    assert first["requests"] == 6 and len(fetch.calls) == 6
    pb = first["feeds"]["twse-pb"]
    # 3711 and 2330's absent bar aside: 1101, 2330, 1108 on D1, 1101 and 2330 on D2.
    assert (pb["inserted"], pb["unmatched"], pb["success"]) == (5, 1 + 2, 2)
    with factory() as db:
        row = db.scalar(
            select(ValuationDaily)
            .join(Instrument)
            .where(Instrument.symbol == "1108", ValuationDaily.trading_date == D1)
        )
        assert (row.pb_ratio, row.pe_ratio, row.report_period) == (0.73, None, "2018Q1")
        assert (row.source, row.data_as_of) == ("twse_bwibbu_d", D1)
        raw = db.get(RawPayload, row.raw_payload_id)
        assert raw.source == "twse" and "BWIBBU_d?date=20180702" in raw.endpoint
        assert raw.collected_at == row.collected_at
        shares = db.scalars(select(SharesOutstandingDaily)).all()
        assert {r.source for r in shares} == {"twse_mi_qfiis"}
        tpex = db.scalars(
            select(ValuationDaily).where(ValuationDaily.source == "tpex_pe_qry_date")
        ).all()
        assert len(tpex) == 3
        manifest = db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == vb.DAY_RUN_TYPE)
        ).all()
        assert len(manifest) == 6 and {r.status for r in manifest} == {"success"}

    again = run(factory, Fetcher())
    assert again["status"] == "success"
    assert again["requests"] == 0 and again["changed"] == 0
    assert again["feeds"]["twse-pb"]["done_before"] == 2

    reapplied = run(factory, Fetcher(), reapply=True)
    assert reapplied["requests"] == 0 and reapplied["changed"] == 0
    assert reapplied["feeds"]["twse-pb"]["unchanged"] == 5
    assert reapplied["feeds"]["tpex-pb"]["reapplied"] == 2


def test_no_request_before_a_feeds_first_day(factory):
    early = date(2005, 9, 1)
    with factory() as db:
        add_instrument(db, "TWSE", "1101", [early, date(2005, 9, 2)])
        db.commit()
    fetch = Fetcher({"twse-pb": BW_OLD, "twse-shares": Q_OLD})
    with factory() as db:
        result = vb.backfill(
            db,
            date(2005, 1, 1),
            date(2005, 12, 31),
            feeds=["twse-pb", "twse-shares"],
            fetch=fetch,
            now=lambda: NOON,
        )
    assert ("twse-pb", early) not in fetch.calls
    assert ("twse-pb", date(2005, 9, 2)) in fetch.calls
    assert ("twse-shares", early) in fetch.calls
    assert result["feeds"]["twse-pb"]["not_published"] == 1
    assert result["feeds"]["twse-shares"]["not_published"] == 0


def test_a_wrong_reported_date_fails_the_session_and_is_asked_again(factory):
    with factory() as db:
        seed(db)
    stale = Fetcher({"twse-pb": lambda _day: redate(BW_NEW, date(2018, 6, 29))})
    result = run(factory, stale, feeds=["twse-pb"])
    assert result["status"] == "partial"
    failed = result["feeds"]["twse-pb"]
    assert failed["failed"] == 2 and failed["inserted"] == 0
    assert "reported date" in failed["failed_days"][0]["error"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ValuationDaily)) == 0
        runs = db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == vb.DAY_RUN_TYPE)
        ).all()
        assert {r.status for r in runs} == {"failed"}
        # The answer is kept for reading what came.
        assert all(r.metadata_json["raw_payload_id"] for r in runs)
    fixed = Fetcher()
    retried = run(factory, fixed, feeds=["twse-pb"])
    assert retried["status"] == "success" and len(fixed.calls) == 2


def test_failed_requests_in_a_row_stop_the_run(factory):
    with factory() as db:
        for n in range(8):
            add_instrument(db, "TWSE", f"11{n:02d}", [date(2018, 7, 2 + n)])
        db.commit()
    fetch = Fetcher({"twse-pb": sources.OfficialDataError("blocked")})
    result = run(factory, fetch, feeds=["twse-pb"])
    assert result["aborted"] and len(fetch.calls) == vb.ABORT_AFTER_FAILURES
    assert result["status"] == "partial"


def test_the_quiet_hours_wait_until_23_30():
    late = datetime(2026, 11, 6, 14, 0)  # 22:00 Taipei
    assert vb.in_quiet_hours(late)
    assert vb.seconds_to_quiet_end(late) == 90 * 60
    assert not vb.in_quiet_hours(datetime(2026, 11, 6, 15, 30))  # 23:30
    assert vb.in_quiet_hours(datetime(2026, 11, 6, 13, 15))  # 21:15


def test_a_request_in_the_quiet_hours_waits(factory):
    with factory() as db:
        add_instrument(db, "TWSE", "1101", [D1])
        db.commit()
    moments = iter([datetime(2026, 11, 6, 14, 0)] * 2 + [NOON] * 10)
    slept: list[float] = []
    with factory() as db:
        vb.backfill(
            db,
            D1,
            D1,
            feeds=["twse-pb"],
            fetch=Fetcher(),
            now=lambda: next(moments),
            sleep=slept.append,
        )
    assert slept == [90 * 60]


def capture(db, tmp_path, payload, endpoint, day, *, under):
    content = sources._encode_payload(payload)
    digest = hashlib.sha256(content).hexdigest()
    path = under / "tpex" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    raw = RawPayload(
        source="tpex",
        endpoint=endpoint,
        payload_path=str(tmp_path / "raw" / "tpex" / f"{digest}.json"),
        sha256=digest,
        data_as_of=day.isoformat(),
        collected_at=datetime(2026, 9, 8, 3, 0),
    )
    db.add(raw)
    db.flush()
    return raw


def test_tpex_shares_come_from_the_capture_the_bars_cite(factory, tmp_path):
    day = date(2011, 11, 1)
    with factory() as db:
        raw = capture(
            db,
            tmp_path,
            DAILY_QUOTES,
            sources.TPEX_HISTORY_API,
            day,
            under=tmp_path / "raw",
        )
        add_instrument(db, "TPEx", "006201", [day], raw_id=raw.id, kind="etf")
        db.commit()
    with factory() as db:
        result = vb.backfill(
            db, day, day, feeds=["tpex-shares"], fetch=Fetcher({}), now=lambda: NOON
        )
    assert result["requests"] == 0 and result["status"] == "success"
    with factory() as db:
        row = db.scalar(select(SharesOutstandingDaily))
        assert (row.shares_issued, row.source, row.raw_payload_id) == (
            115_446_000,
            "tpex_daily_quotes",
            raw.id,
        )


def test_a_seed_capture_is_read_from_the_fallback_raw_dir(
    factory, tmp_path, monkeypatch
):
    from app import config

    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    day = date(2026, 11, 9)
    production = tmp_path / "production_raw"
    with factory() as db:
        raw = capture(
            db, tmp_path, OA_QUOTES, sources.TPEX_DAILY_ENDPOINT, day, under=production
        )
        add_instrument(db, "TPEx", "00411A", [day], raw_id=raw.id, kind="etf")
        db.commit()
    with factory() as db:
        missing = vb.backfill(
            db, day, day, feeds=["tpex-shares"], fetch=Fetcher({}), now=lambda: NOON
        )
    assert missing["status"] == "partial"
    assert "missing" in missing["feeds"]["tpex-shares"]["failed_days"][0]["error"]
    with factory() as db:
        found = vb.backfill(
            db,
            day,
            day,
            feeds=["tpex-shares"],
            fallback_raw_dir=production,
            fetch=Fetcher({}),
            now=lambda: NOON,
        )
    assert found["status"] == "success"
    with factory() as db:
        row = db.scalar(select(SharesOutstandingDaily))
        assert (row.shares_issued, row.source) == (
            469_576_000,
            "tpex_daily_close_quotes",
        )


def test_the_tables_must_exist(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with sessionmaker(bind=engine)() as db, pytest.raises(ValueError, match="init-db"):
        vb.backfill(db, D1, D1, fetch=Fetcher(), now=lambda: NOON)
    engine.dispose()


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
            "valuation",
            "backfill",
            "--start",
            "2018-07-02",
            "--end",
            "2018-07-02",
        ],
    )
    monkeypatch.setattr(
        cli,
        "run_valuation_backfill",
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

    args = argparse.Namespace(command="valuation", valuation_command="backfill")
    assert cli.maintenance_guarded(args) == "valuation backfill"
    assert cli.backfill_command(args) == "valuation backfill"


def test_the_run_keeps_three_and_a_half_seconds_and_restores_the_floor(monkeypatch):
    seen = []
    monkeypatch.setattr(
        vb,
        "backfill",
        lambda *a, **k: seen.append(sources._minimum_host_interval) or {},
    )
    before = sources._minimum_host_interval
    vb.run_valuation_backfill("2018-07-02", "2018-07-02")
    assert seen == [vb.REQUEST_INTERVAL_SECONDS]
    assert sources._minimum_host_interval == before


# --- the migration --------------------------------------------------------------------


@pytest.mark.parametrize(
    "suffix, tables",
    [
        ("_valuation_shares", {"valuation_daily", "shares_outstanding_daily"}),
        ("_foreign_holdings", {"foreign_holdings_daily"}),
    ],
)
def test_the_migration_adds_empty_tables_and_goes_down_again(tmp_path, suffix, tables):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    from app import migrations
    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith(suffix))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
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


def test_null_text_is_null():
    # TPEx peQryDate 2021-07-26 on: 6840 東研信超 has 'null' for 本益比 and 股價淨值比.
    payload = copy.deepcopy(PE_OLD)
    payload["tables"][0]["data"][0][2] = "null"
    payload["tables"][0]["data"][0][6] = "null"
    parsed = vb.parse_tpex_pb(payload, date(2007, 4, 23))
    assert parsed["1333"]["pe_ratio"] is None and parsed["1333"]["pb_ratio"] is None


def test_reapply_reads_a_failed_sessions_answer_and_asks_nothing(factory, monkeypatch):
    with factory() as db:
        seed(db)
    broken = Fetcher(
        {
            "twse-pb": BW_NEW,
            "twse-shares": sources.OfficialDataError("blocked"),
            "tpex-pb": PE_NEW,
        }
    )
    # The parser of that time could not read the answers.
    original = vb.PARSERS["twse-pb"]
    monkeypatch.setitem(
        vb.PARSERS, "twse-pb", lambda *_: (_ for _ in ()).throw(vb.LayoutError("old"))
    )
    first = run(factory, broken)
    assert first["feeds"]["twse-pb"]["failed"] == 2
    assert first["feeds"]["twse-shares"]["failed"] == 2
    monkeypatch.setitem(vb.PARSERS, "twse-pb", original)
    reapplied = run(
        factory, Fetcher({}), reapply=True, feeds=["twse-pb", "twse-shares"]
    )
    assert reapplied["requests"] == 0
    assert reapplied["feeds"]["twse-pb"]["success"] == 2
    assert reapplied["feeds"]["twse-pb"]["inserted"] == 5
    # No answer was kept for the shares: left to a run, never asked by reapply.
    assert reapplied["feeds"]["twse-shares"]["not_answered"] == 2
    asked = Fetcher()
    again = run(factory, asked, feeds=["twse-pb", "twse-shares"])
    assert again["status"] == "success"
    assert {feed for feed, _ in asked.calls} == {"twse-shares"}


def test_a_seed_capture_with_an_old_windows_path_is_read_from_the_fallback(
    factory, tmp_path, monkeypatch
):
    # Seed rows captured before the Docker cutover keep the Windows raw path.
    monkeypatch.setenv("STOCK_STORED_RAW_DIR", str(tmp_path / "raw"))
    day = date(2011, 11, 1)
    production = tmp_path / "production_raw"
    content = sources._encode_payload(DAILY_QUOTES)
    digest = hashlib.sha256(content).hexdigest()
    target = production / "tpex" / "2026" / "10" / "17" / f"{digest}.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    with factory() as db:
        raw = RawPayload(
            source="tpex",
            endpoint=sources.TPEX_HISTORY_API,
            payload_path=(
                "C:\\Users\\YiCheng\\stock-lab-data\\raw\\tpex\\2026\\10\\17\\"
                f"{digest}.json"
            ),
            sha256=digest,
            data_as_of=day.isoformat(),
            collected_at=datetime(2026, 10, 17, 2, 0),
        )
        db.add(raw)
        db.flush()
        add_instrument(db, "TPEx", "006201", [day], raw_id=raw.id, kind="etf")
        db.commit()
    with factory() as db:
        result = vb.backfill(
            db,
            day,
            day,
            feeds=["tpex-shares"],
            fallback_raw_dir=production,
            fetch=Fetcher({}),
            now=lambda: NOON,
        )
    assert result["status"] == "success"
    with factory() as db:
        assert db.scalar(select(SharesOutstandingDaily)).shares_issued == 115_446_000


def test_the_managed_stock_table_gives_shares_too():
    # dailyQuotes' 管理股票 table: the bars of 1107 建台 come from it.
    parsed = vb.parse_tpex_quote_shares(DAILY_QUOTES, date(2011, 11, 1))
    assert parsed["1107"] == {"shares_issued": 314_035_300}
    assert parsed["2341"] == {"shares_issued": 207_812_953}
    twice = copy.deepcopy(DAILY_QUOTES)
    twice["tables"][1]["data"].append(list(twice["tables"][0]["data"][0]))
    with pytest.raises(vb.LayoutError, match="listed twice"):
        vb.parse_tpex_quote_shares(twice, date(2011, 11, 1))
    renamed = copy.deepcopy(DAILY_QUOTES)
    renamed["tables"][1]["fields"][13] = "股數"
    with pytest.raises(vb.LayoutError, match="unknown columns"):
        vb.parse_tpex_quote_shares(renamed, date(2011, 11, 1))


def test_one_blocked_host_stops_the_run_while_the_other_answers(factory):
    # TWSE blocked, TPEx answering: per host, the run stops at TWSE's 5th failure.
    days = [date(2018, 7, 2 + n) for n in range(6)]
    with factory() as db:
        add_instrument(db, "TWSE", "1101", days)
        add_instrument(db, "TPEx", "1240", days)
        db.commit()
    fetch = Fetcher(
        {"twse-pb": sources.OfficialDataError("blocked"), "tpex-pb": PE_NEW}
    )
    result = run(factory, fetch, feeds=["twse-pb", "tpex-pb"])
    twse = [day for feed, day in fetch.calls if feed == "twse-pb"]
    assert len(twse) == vb.ABORT_AFTER_FAILURES
    assert "www.twse.com.tw" in result["aborted"]
    assert result["feeds"]["tpex-pb"]["success"] == vb.ABORT_AFTER_FAILURES - 1


def test_a_total_other_than_the_rows_fails_the_day():
    twse = copy.deepcopy(BW_NEW)
    twse["total"] = len(twse["data"]) + 1
    with pytest.raises(vb.LayoutError, match="total"):
        vb.parse_twse_pb(twse, date(2018, 7, 2))
    tpex = copy.deepcopy(PE_NEW)
    tpex["tables"][0]["totalCount"] = 1
    with pytest.raises(vb.LayoutError, match="totalCount"):
        vb.parse_tpex_pb(tpex, date(2026, 11, 26))


def test_an_empty_table_fails_the_day():
    empty = copy.deepcopy(PE_OLD)
    empty["tables"][0]["data"] = []
    empty["tables"][0]["totalCount"] = 0
    with pytest.raises(vb.LayoutError, match="no rows"):
        vb.parse_tpex_pb(empty, date(2007, 4, 23))
    with pytest.raises(vb.LayoutError, match="no rows"):
        vb.parse_twse_shares({**redate(Q_NEW, D1), "data": [], "total": 0}, D1)


def test_tpex_shares_from_another_capture_replace_the_other_sources_rows(
    factory, tmp_path
):
    day = date(2026, 11, 9)
    with factory() as db:
        web = capture(
            db,
            tmp_path,
            redate(DAILY_QUOTES, day),
            sources.TPEX_HISTORY_API,
            day,
            under=tmp_path / "raw",
        )
        api = capture(
            db,
            tmp_path,
            OA_QUOTES,
            sources.TPEX_DAILY_ENDPOINT,
            day,
            under=tmp_path / "raw",
        )
        item = add_instrument(db, "TPEx", "006201", [day], raw_id=web.id, kind="etf")
        db.commit()
    with factory() as db:
        vb.backfill(
            db, day, day, feeds=["tpex-shares"], fetch=Fetcher({}), now=lambda: NOON
        )
        assert db.scalar(select(SharesOutstandingDaily)).source == "tpex_daily_quotes"
        # The bars now cite the OpenAPI table (a later capture of the session).
        db.get(MarketBar, db.scalar(select(MarketBar.id))).raw_payload_id = api.id
        db.commit()
    with factory() as db:
        again = vb.backfill(
            db,
            day,
            day,
            feeds=["tpex-shares"],
            reapply=True,
            fetch=Fetcher({}),
            now=lambda: NOON,
        )
        assert again["feeds"]["tpex-shares"]["removed"] == 1
        rows = db.scalars(
            select(SharesOutstandingDaily).where(
                SharesOutstandingDaily.instrument_id == item.id
            )
        ).all()
        assert [(r.source, r.shares_issued) for r in rows] == [
            ("tpex_daily_close_quotes", 27_946_000)
        ]


def test_reapply_writes_no_manifest_row_for_a_session_never_asked(factory):
    with factory() as db:
        seed(db)
    result = run(factory, Fetcher({}), reapply=True, feeds=["twse-pb"])
    assert result["requests"] == 0
    assert result["feeds"]["twse-pb"]["not_answered"] == 2
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(IngestionRun)) == 0


# --- foreign holdings (Issue #1121) ------------------------------------------------

QFII = load("qfii_20180702.json")
QFII_EMPTY = load("qfii_20070423_empty.json")
Q_2013 = load("mi_qfiis_20130701.json")
Q_2024 = load("mi_qfiis_20240701.json")
MOPS_LINK = " <a href='https://mopsov.twse.com.tw/mops/web/t98sb02' target=_blank>2</a>"


def test_twse_foreign_reads_the_old_layout_and_the_early_limit_is_null():
    rows = vb.parse_twse_foreign(Q_OLD, date(2004, 2, 11))
    assert rows["1101"] == {
        "shares_issued": 2_546_396_409,
        "foreign_shares_held": 424_513_358,
        "foreign_held_pct": 16.67,
        "foreign_available_shares": 848_684_846,
        # 0.00 on every row up to 2004-07-23: no data (#1117 decision point 4).
        "foreign_limit_pct": None,
        "mainland_limit_pct": None,
        "change_reason": "1",
        "last_filing_date": date(2003, 9, 16),
        "note": None,
    }
    # The number 0: never filed.
    assert rows["0050"]["last_filing_date"] is None


def test_twse_foreign_reads_both_layouts_either_side_of_2009_05_04():
    before = redate(Q_OLD, date(2009, 4, 30))
    before["data"][1][8] = "50.00"
    before["data"][2][8] = "0.00"
    old = vb.parse_twse_foreign(before, date(2009, 4, 30))
    assert old["1101"]["foreign_limit_pct"] == 50.0
    # After 2004-07-23 a 0.00 limit is as published.
    assert old["2330"]["foreign_limit_pct"] == 0.0
    assert old["2330"]["mainland_limit_pct"] is None
    new = vb.parse_twse_foreign(redate(Q_NEW, date(2009, 5, 4)), date(2009, 5, 4))
    assert new["2330"] == {
        "shares_issued": 25_932_370_067,
        "foreign_shares_held": 17_526_865_407,
        "foreign_held_pct": 67.58,
        "foreign_available_shares": 8_405_504_660,
        "foreign_limit_pct": 100.0,
        "mainland_limit_pct": 100.0,
        "change_reason": None,
        "last_filing_date": date(2026, 5, 26),
        "note": None,
    }


def test_twse_foreign_strips_the_html_of_the_change_reason():
    rows = vb.parse_twse_foreign(Q_2024, date(2024, 7, 1))
    assert Q_2024["data"][0][10] == MOPS_LINK
    assert rows["0050"]["change_reason"] == "2"
    assert rows["0050"]["last_filing_date"] == date(2024, 7, 1)
    assert rows["0052"]["change_reason"] is None
    combined = copy.deepcopy(Q_2024)
    combined["data"][0][10] = MOPS_LINK + " 4"
    assert (
        vb.parse_twse_foreign(combined, date(2024, 7, 1))["0050"]["change_reason"]
        == "2 4"
    )
    combined["data"][0][10] = "<a>x</a>"
    with pytest.raises(vb.LayoutError, match="change reason"):
        vb.parse_twse_foreign(combined, date(2024, 7, 1))


def test_twse_foreign_zero_shares_held_is_zero_not_null():
    rows = vb.parse_twse_foreign(Q_2013, date(2013, 7, 1))
    assert rows["0050"]["foreign_shares_held"] == 0
    assert rows["0050"]["foreign_held_pct"] == 0.0
    assert rows["0050"]["foreign_available_shares"] == 1_425_000_000
    assert rows["0050"]["last_filing_date"] is None


@pytest.mark.parametrize(
    "column, cell, error",
    [(11, "92/13/40", "filing date"), (5, "1.5", "share count"), (7, "x", "value")],
)
def test_twse_foreign_unreadable_cells_fail_the_day(column, cell, error):
    payload = copy.deepcopy(Q_NEW)
    payload["data"][1][column] = cell
    with pytest.raises(vb.LayoutError, match=error):
        vb.parse_twse_foreign(payload, date(2026, 11, 26))


def test_tpex_foreign_reads_the_table():
    day = date(2018, 7, 2)
    rows = vb.parse_tpex_foreign(QFII, day)
    assert set(rows) == {"6497", "4413", "1569", "3147"}
    assert rows["6497"] == {
        "shares_issued": 130_128_940,
        "foreign_shares_held": 130_128_940,
        "foreign_held_pct": 100.0,
        "foreign_available_shares": 0,
        "foreign_limit_pct": 100.0,
        "mainland_limit_pct": None,
        "change_reason": None,
        "last_filing_date": None,
        "note": "已達上限",
    }
    assert rows["4413"]["note"] == "禁止投資"
    assert rows["4413"]["foreign_held_pct"] == 7.57
    # 0 shares held is 0, never missing.
    assert rows["3147"]["foreign_shares_held"] == 0
    assert rows["3147"]["foreign_held_pct"] == 0.0
    assert rows["3147"]["note"] is None


def test_tpex_foreign_empty_or_miscounted_or_misdated_tables_fail_the_day():
    with pytest.raises(vb.LayoutError, match="no rows"):
        vb.parse_tpex_foreign(QFII_EMPTY, date(2007, 4, 23))
    short = copy.deepcopy(QFII)
    short["tables"][0]["totalCount"] = 5
    with pytest.raises(vb.LayoutError, match="totalCount 5 but 4 rows"):
        vb.parse_tpex_foreign(short, date(2018, 7, 2))
    del short["tables"][0]["totalCount"]
    with pytest.raises(vb.LayoutError, match="totalCount"):
        vb.parse_tpex_foreign(short, date(2018, 7, 2))
    with pytest.raises(vb.LayoutError, match="reported date"):
        vb.parse_tpex_foreign(QFII, date(2018, 7, 3))
    table_day = copy.deepcopy(QFII)
    table_day["tables"][0]["date"] = "107/07/03"
    with pytest.raises(vb.LayoutError, match="table date"):
        vb.parse_tpex_foreign(table_day, date(2018, 7, 2))


@pytest.mark.parametrize(
    "column, cell, error",
    [(7, "7.57", "ratio"), (7, "a%", "ratio"), (5, "1,2.5", "share count")],
)
def test_tpex_foreign_unreadable_cells_fail_the_day(column, cell, error):
    payload = copy.deepcopy(QFII)
    payload["tables"][0]["data"][1][column] = cell
    with pytest.raises(vb.LayoutError, match=error):
        vb.parse_tpex_foreign(payload, date(2018, 7, 2))


def test_tpex_foreign_unknown_columns_fail_the_day():
    payload = copy.deepcopy(QFII)
    payload["tables"][0]["fields"][5] = "外資持有股數"
    with pytest.raises(vb.LayoutError, match="unknown columns"):
        vb.parse_tpex_foreign(payload, date(2018, 7, 2))


def test_tpex_foreign_posts_to_insti_qfii():
    method, url, form = vb.request_of("tpex-foreign", date(2018, 7, 2))
    assert (method, form) == ("POST", {"date": "2018/07/02", "response": "json"})
    assert url.split("?")[0] == "https://www.tpex.org.tw/www/zh-tw/insti/qfii"
    with pytest.raises(ValueError, match="no request"):
        vb.request_of("twse-foreign", date(2018, 7, 2))


FOREIGN = {"twse-shares": Q_NEW, "tpex-foreign": QFII}


def test_twse_foreign_rereads_the_twse_shares_raw_and_tpex_foreign_requests(
    factory,
):
    with factory() as db:
        seed(db)
    fetch = Fetcher(FOREIGN)
    # twse-foreign named first still runs after twse-shares within a session.
    feeds = ["twse-foreign", "twse-shares", "tpex-foreign"]
    first = run(factory, fetch, feeds=feeds)
    assert first["status"] == "success"
    assert sorted(fetch.calls) == sorted(
        [("twse-shares", d) for d in (D1, D2)] + [("tpex-foreign", d) for d in (D1, D2)]
    )
    twse = first["feeds"]["twse-foreign"]
    assert (twse["requested"], twse["reapplied"], twse["success"]) == (0, 2, 2)
    # 1101, 2330, 1108's missing row on D1; 0050 has no bar.
    assert (twse["inserted"], twse["unmatched"], twse["no_row"]) == (4, 2, 1)
    tpex = first["feeds"]["tpex-foreign"]
    # 1569 on D1 only; 1240 is not in the table; 6497, 4413, 3147 have no bar.
    assert (tpex["requested"], tpex["inserted"], tpex["no_row"]) == (2, 1, 2)
    assert tpex["unmatched"] == 3 + 4
    with factory() as db:
        shares_run = db.scalar(
            select(IngestionRun).where(
                IngestionRun.request_key == f"valuation_backfill:twse-shares:{D1}"
            )
        )
        row = db.scalar(
            select(ForeignHoldingsDaily)
            .join(Instrument)
            .where(Instrument.symbol == "2330", ForeignHoldingsDaily.trading_date == D1)
        )
        assert row.raw_payload_id == shares_run.metadata_json["raw_payload_id"]
        assert (row.source, row.data_as_of) == ("twse_mi_qfiis", D1)
        assert (row.foreign_shares_held, row.mainland_limit_pct) == (
            17_526_865_407,
            100.0,
        )
        assert row.last_filing_date == date(2026, 5, 26)
        otc = db.scalar(
            select(ForeignHoldingsDaily).where(
                ForeignHoldingsDaily.source == "tpex_insti_qfii"
            )
        )
        assert (otc.trading_date, otc.foreign_limit_pct) == (D1, 100.0)
        raw = db.get(RawPayload, otc.raw_payload_id)
        assert raw.source == "tpex" and "insti/qfii?date=2018/07/02" in raw.endpoint

    again = run(factory, Fetcher(FOREIGN), feeds=feeds)
    assert again["requests"] == 0 and again["changed"] == 0
    assert again["feeds"]["twse-foreign"]["done_before"] == 2
    reapplied = run(factory, Fetcher({}), feeds=feeds, reapply=True)
    assert reapplied["requests"] == 0 and reapplied["changed"] == 0
    assert reapplied["feeds"]["twse-foreign"]["unchanged"] == 4
    assert reapplied["feeds"]["tpex-foreign"]["unchanged"] == 1


def test_twse_foreign_waits_for_the_twse_shares_capture(factory):
    with factory() as db:
        seed(db)
    alone = run(factory, Fetcher({}), feeds=["twse-foreign"])
    assert alone["requests"] == 0
    assert alone["feeds"]["twse-foreign"]["not_answered"] == 2
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(IngestionRun)) == 0
    run(factory, Fetcher(FOREIGN), feeds=["twse-shares"])
    later = run(factory, Fetcher({}), feeds=["twse-foreign"])
    assert (
        later["status"] == "success" and later["feeds"]["twse-foreign"]["success"] == 2
    )


def test_a_twse_shares_answer_that_does_not_read_fails_twse_foreign_too(factory):
    with factory() as db:
        seed(db)
    broken = copy.deepcopy(Q_NEW)
    broken["fields"][5] = "外資持有"
    result = run(
        factory, Fetcher({"twse-shares": broken}), feeds=["twse-shares", "twse-foreign"]
    )
    assert result["status"] == "partial"
    assert result["feeds"]["twse-foreign"]["failed"] == 2
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ForeignHoldingsDaily)) == 0


def test_tpex_foreign_asks_nothing_before_2007_05_10(factory):
    days = [date(2007, 5, 9), date(2007, 5, 10)]
    with factory() as db:
        add_instrument(db, "TPEx", "1569", days)
        db.commit()
    fetch = Fetcher({"tpex-foreign": QFII})
    with factory() as db:
        result = vb.backfill(
            db, days[0], days[1], feeds=["tpex-foreign"], fetch=fetch, now=lambda: NOON
        )
    assert fetch.calls == [("tpex-foreign", days[1])]
    assert result["feeds"]["tpex-foreign"]["not_published"] == 1


def test_an_empty_tpex_foreign_answer_writes_nothing_and_is_asked_again(factory):
    with factory() as db:
        seed(db)
    empty = run(factory, Fetcher({"tpex-foreign": QFII_EMPTY}), feeds=["tpex-foreign"])
    assert empty["status"] == "partial"
    assert empty["feeds"]["tpex-foreign"]["failed"] == 2
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ForeignHoldingsDaily)) == 0
    again = run(factory, Fetcher({"tpex-foreign": QFII}), feeds=["tpex-foreign"])
    assert again["requests"] == 2 and again["status"] == "success"
