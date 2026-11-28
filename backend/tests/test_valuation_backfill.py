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


def test_the_migration_adds_two_empty_tables_and_goes_down_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    from app import migrations
    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith("_valuation_shares"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    tables = {"valuation_daily", "shares_outstanding_daily"}
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
            "ix_valuation_daily_trading_date",
            "ix_valuation_daily_raw_payload_id",
            "ix_shares_outstanding_daily_trading_date",
            "ix_shares_outstanding_daily_raw_payload_id",
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


# --- TPEx 50 constituents (#1134) -------------------------------------------------
#
# ``r50_20100430`` (the first day), ``r50_20100429_before_first`` (stat ok, empty)
# and ``r50_20210419`` (-KY names) are whole answers of the #1130 probe
# (2026-11-28, evidence/1130/raw), a newline added.

R50_FIRST = load("r50_20100430.json")
R50_BEFORE = load("r50_20100429_before_first.json")
R50_2021 = load("r50_20210419.json")
T1, T2 = date(2010, 4, 30), date(2010, 5, 3)


def r50_drop(payload, code: str, *, count=None):
    """The answer without ``code``'s cell; ``totalCount`` set to ``count``."""

    result = copy.deepcopy(payload)
    table = result["tables"][0]
    for row in table["data"]:
        for at in range(1, len(row), 2):
            if str(row[at]).startswith(f"{code}&nbsp;"):
                row[at - 1], row[at] = "", ""
    # Renumber 1..n as the source writes them.
    number = 0
    for at in range(0, 8, 2):
        for row in table["data"]:
            if row[at] != "":
                number += 1
                row[at] = number
    table["totalCount"] = number if count is None else count
    return result


def test_r50_cells_split_into_code_and_name():
    parsed = vb.parse_tpex50(R50_FIRST, T1)
    assert len(parsed) == 50
    assert list(parsed)[:3] == ["1565", "1785", "1815"]
    assert parsed["1565"] == {"name_in_source": "精華"}
    assert parsed["8938"] == {"name_in_source": "明安"}
    later = vb.parse_tpex50(R50_2021, date(2021, 4, 19))
    assert later["4966"] == {"name_in_source": "譜瑞-KY"}
    assert {"3078", "3691", "6244", "6411"} <= set(later)


def test_r50_request_is_the_cnst_form():
    method, endpoint, form = vb.request_of("tpex50-daily", T1)
    assert method == "POST"
    assert endpoint.startswith(vb.TPEX50_ENDPOINT + "?")
    assert form == {"type": "cnst", "date": "2010/04/30", "response": "json"}


def test_r50_total_count_other_than_the_cells_fails_the_day():
    payload = copy.deepcopy(R50_FIRST)
    payload["tables"][0]["totalCount"] = 51
    with pytest.raises(vb.LayoutError, match="totalCount 51 but 50"):
        vb.parse_tpex50(payload, T1)
    with pytest.raises(vb.LayoutError, match="totalCount 50 but 49"):
        vb.parse_tpex50(r50_drop(R50_FIRST, "1565", count=50), T1)


def test_r50_empty_table_fails_the_day():
    with pytest.raises(vb.LayoutError, match="no rows"):
        vb.parse_tpex50(R50_BEFORE, date(2010, 4, 29))


@pytest.mark.parametrize("where", ["date", "table"])
def test_r50_reported_date_other_than_the_session_fails(where):
    payload = copy.deepcopy(R50_FIRST)
    if where == "date":
        payload["date"] = "20100503"
    else:
        payload["tables"][0]["date"] = "99/05/03"
    with pytest.raises(vb.LayoutError, match="date"):
        vb.parse_tpex50(payload, T1)


@pytest.mark.parametrize(
    "cell",
    ["1565 精華", "1565 精華", "1565&nbsp;", "&nbsp;精華", "1565精華", 1565, None],
)
def test_r50_unreadable_cell_fails_the_day(cell):
    payload = copy.deepcopy(R50_FIRST)
    payload["tables"][0]["data"][0][1] = cell
    with pytest.raises(vb.LayoutError, match="unreadable cell"):
        vb.parse_tpex50(payload, T1)


def test_r50_unreadable_number_or_columns_fail_the_day():
    payload = copy.deepcopy(R50_FIRST)
    payload["tables"][0]["data"][0][0] = "1"
    with pytest.raises(vb.LayoutError, match="序號"):
        vb.parse_tpex50(payload, T1)
    payload = copy.deepcopy(R50_FIRST)
    payload["tables"][0]["fields"] = payload["tables"][0]["fields"][:6]
    with pytest.raises(vb.LayoutError, match="unknown columns"):
        vb.parse_tpex50(payload, T1)
    payload = copy.deepcopy(R50_FIRST)
    payload["tables"][0]["data"][1][1] = payload["tables"][0]["data"][0][1]
    with pytest.raises(vb.LayoutError, match="listed twice"):
        vb.parse_tpex50(payload, T1)


def seed_r50(db, *, missing=("8938",)):
    """TPEx instruments with bars on T1 and T2 for the first day's codes."""

    for code in vb.parse_tpex50(R50_FIRST, T1):
        if code not in missing:
            add_instrument(db, "TPEx", code, [T1, T2])
    # The day before the first one: a TPEx session, never asked.
    add_instrument(db, "TPEx", "9999", [date(2010, 4, 29), T1, T2])
    db.commit()


def run_r50(factory, fetch, **kwargs):
    with factory() as db:
        return vb.backfill(
            db,
            date(2010, 4, 1),
            date(2010, 5, 31),
            feeds=["tpex50-daily"],
            fetch=fetch,
            now=lambda: NOON,
            sleep=lambda _s: pytest.fail("slept outside the quiet hours"),
            **kwargs,
        )


def test_r50_backfill_writes_every_code_and_counts_unmatched(factory):
    with factory() as db:
        seed_r50(db)
    fetch = Fetcher({"tpex50-daily": R50_FIRST})
    first = run_r50(factory, fetch)
    assert first["status"] == "success"
    # 2010-04-29 is a session before the first day: not asked.
    assert fetch.calls == [("tpex50-daily", T1), ("tpex50-daily", T2)]
    counts = first["feeds"]["tpex50-daily"]
    assert (counts["sessions"], counts["not_published"]) == (3, 1)
    assert (counts["success"], counts["inserted"], counts["unmatched"]) == (2, 100, 2)
    assert (counts["not_50"], counts["not_50_days"]) == (0, [])
    with factory() as db:
        rows = db.scalars(
            select(vb.IndexConstituentDaily).where(
                vb.IndexConstituentDaily.trading_date == T1
            )
        ).all()
        assert len(rows) == 50
        by_code = {row.symbol: row for row in rows}
        # No TPEx instrument with a bar: written, instrument_id NULL, no instrument.
        assert by_code["8938"].instrument_id is None
        assert db.scalar(select(Instrument).where(Instrument.symbol == "8938")) is None
        row = by_code["1565"]
        assert row.instrument_id == db.scalar(
            select(Instrument.id).where(Instrument.symbol == "1565")
        )
        assert (row.index_code, row.name_in_source) == ("TPEX50", "精華")
        assert (row.source, row.data_as_of) == ("tpex_indexinfo_r50", T1)
        raw = db.get(RawPayload, row.raw_payload_id)
        assert raw.source == "tpex" and "indexInfo/r50?type=cnst" in raw.endpoint
        assert raw.collected_at == row.collected_at
        run_row = db.scalar(
            select(IngestionRun).where(
                IngestionRun.request_key == "valuation_backfill:tpex50-daily:2010-04-30"
            )
        )
        assert run_row.status == "success" and run_row.records == 50
        assert run_row.metadata_json["unmatched_codes"] == ["8938"]

    again = run_r50(factory, Fetcher({}))
    assert again["requests"] == 0 and again["changed"] == 0
    assert again["feeds"]["tpex50-daily"]["done_before"] == 2
    reapplied = run_r50(factory, Fetcher({}), reapply=True)
    assert reapplied["requests"] == 0 and reapplied["changed"] == 0
    assert reapplied["feeds"]["tpex50-daily"]["unchanged"] == 100


def test_r50_a_list_of_other_than_50_is_written_and_listed(factory):
    with factory() as db:
        seed_r50(db, missing=())
    short = r50_drop(R50_FIRST, "1565")
    fetch = Fetcher({"tpex50-daily": lambda day: redate(short, day)})
    result = run_r50(factory, fetch)
    assert result["status"] == "success"
    counts = result["feeds"]["tpex50-daily"]
    assert counts["not_50"] == 2
    assert counts["not_50_days"] == [
        {"date": "2010-04-30", "count": 49},
        {"date": "2010-05-03", "count": 49},
    ]
    with factory() as db:
        assert (
            db.scalar(select(func.count()).select_from(vb.IndexConstituentDaily)) == 98
        )
    # The source corrects the day: a session asked again is rewritten whole.
    with factory() as db:
        for run_row in db.scalars(
            select(IngestionRun).where(IngestionRun.source == "tpex50-daily")
        ):
            run_row.status = "failed"
        db.commit()
    fixed = run_r50(factory, Fetcher({"tpex50-daily": R50_FIRST}))
    assert fixed["feeds"]["tpex50-daily"]["inserted"] == 2
    assert fixed["feeds"]["tpex50-daily"]["not_50"] == 0


def test_r50_a_failed_day_writes_nothing_and_is_asked_again(factory):
    with factory() as db:
        seed_r50(db)
    bad = copy.deepcopy(R50_FIRST)
    bad["tables"][0]["totalCount"] = 49
    first = run_r50(factory, Fetcher({"tpex50-daily": bad}))
    assert first["status"] == "partial"
    assert first["feeds"]["tpex50-daily"]["failed"] == 2
    with factory() as db:
        assert (
            db.scalar(select(func.count()).select_from(vb.IndexConstituentDaily)) == 0
        )
    fetch = Fetcher({"tpex50-daily": R50_FIRST})
    again = run_r50(factory, fetch)
    assert again["status"] == "success" and len(fetch.calls) == 2


def test_the_r50_migration_adds_an_empty_table_and_goes_down_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    from app import migrations
    from app.migration_revisions import REVISIONS

    revision = next(n for n in REVISIONS if n.endswith("_index_constituents"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    table = "index_constituents_daily"
    try:
        command.upgrade(config, revision)
        assert table in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()
                == 0
            )
        assert {i["name"] for i in inspect(engine).get_indexes(table)} == {
            "ix_index_constituents_daily_trading_date",
            "ix_index_constituents_daily_instrument_id",
            "ix_index_constituents_daily_raw_payload_id",
        }
        command.downgrade(config, previous)
        assert table not in inspect(engine).get_table_names()
        # The way an older database comes up: 0049 creates the table itself.
        command.upgrade(config, revision)
        schema = inspect(engine)
        assert table in schema.get_table_names()
        columns = {c["name"]: c["nullable"] for c in schema.get_columns(table)}
        assert columns == {
            "id": False,
            "index_code": False,
            "trading_date": False,
            "symbol": False,
            "instrument_id": True,
            "name_in_source": False,
            "source": False,
            "data_as_of": False,
            "raw_payload_id": False,
            "collected_at": False,
        }
        assert {
            (tuple(fk["constrained_columns"]), fk["referred_table"])
            for fk in schema.get_foreign_keys(table)
        } == {
            (("instrument_id",), "instruments"),
            (("raw_payload_id",), "raw_payloads"),
        }
        assert {i["name"] for i in schema.get_indexes(table)} == {
            "ix_index_constituents_daily_trading_date",
            "ix_index_constituents_daily_instrument_id",
            "ix_index_constituents_daily_raw_payload_id",
        }
        assert [
            tuple(u["column_names"]) for u in schema.get_unique_constraints(table)
        ] == [("index_code", "trading_date", "symbol")]
    finally:
        engine.dispose()


def test_r50_a_table_of_padding_only_fails_the_day():
    payload = copy.deepcopy(R50_BEFORE)
    payload["tables"][0]["data"] = [["", "", "", "", "", "", "", ""]]
    with pytest.raises(vb.LayoutError, match="no codes"):
        vb.parse_tpex50(payload, date(2010, 4, 29))


@pytest.mark.parametrize(
    "feed, endpoint, form",
    [
        (
            "tpex-pb",
            vb.PE_QRY_DATE_ENDPOINT,
            {"date": "2010/04/30", "response": "json"},
        ),
        (
            "tpex50-daily",
            vb.TPEX50_ENDPOINT,
            {"type": "cnst", "date": "2010/04/30", "response": "json"},
        ),
    ],
)
def test_the_post_feeds_send_their_own_endpoint_and_form(
    monkeypatch, feed, endpoint, form
):
    sent = []
    monkeypatch.setattr(
        sources,
        "fetch_json",
        lambda url, **kwargs: sent.append((url, kwargs)) or {"stat": "ok"},
    )
    assert vb.fetch_official(feed, T1) == {"stat": "ok"}
    assert sent == [(endpoint, {"method": "POST", "data": form})]


def test_a_database_before_0049_still_runs_the_older_feeds(tmp_path, monkeypatch):
    from app.models import Base

    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(
        engine,
        tables=[
            t
            for name, t in Base.metadata.tables.items()
            if name != "index_constituents_daily"
        ],
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        add_instrument(db, "TPEx", "1240", [D1])
        db.commit()
        result = vb.backfill(
            db,
            D1,
            D1,
            feeds=["tpex-pb"],
            fetch=Fetcher(),
            now=lambda: NOON,
        )
        assert result["status"] == "success"
        with pytest.raises(ValueError, match="index_constituents_daily is missing"):
            vb.backfill(
                db, D1, D1, feeds=["tpex50-daily"], fetch=Fetcher(), now=lambda: NOON
            )
    engine.dispose()
