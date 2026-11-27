"""The official trade count (成交筆數) of the daily quote rows (Issue #1094).

Parsers of the four quote tables (TWSE ``MI_INDEX`` / OpenAPI ``STOCK_DAY_ALL``,
TPEx ``dailyQuotes`` / OpenAPI ``tpex_mainboard_daily_close_quotes``), the bar
upsert's rule for the new column, and ``worker.cli trade-count reread``, which
fills the research DB's nulls from the captures the bars cite.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Instrument, MarketBar, RawPayload
from worker import trade_count_reread
from worker.pipeline import _upsert_official_bar
from worker.sources import BarRecord

FIXTURES = Path(__file__).parent / "fixtures"
MI_INDEX = FIXTURES / "market_summary" / "twse_mi_index_20190430.json"
DAILY_QUOTES = FIXTURES / "tpex_daily_quotes" / "dailyquotes_20111101.json"
WWW_QUOTES = FIXTURES / "tpex_openapi" / "www_quotes_20261109.json"
OA_QUOTES = FIXTURES / "tpex_openapi" / "oa_quotes_20261109.json"
MI_DAY, DQ_DAY = date(2019, 4, 30), date(2011, 11, 1)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _by_symbol(records):
    return {record.symbol: record for record in records}


def _stock_day_all_row(**changes):
    row = {
        "Date": "1151111",
        "Code": "2330",
        "Name": "台積電",
        "TradeVolume": "33056476",
        "TradeValue": "77900786705",
        "OpeningPrice": "2370.00",
        "HighestPrice": "2400.00",
        "LowestPrice": "2365.00",
        "ClosingPrice": "2395.00",
        "Change": "25.0000",
        "Transaction": "119978",
    }
    row.update(changes)
    return row


# --- parsers ------------------------------------------------------------------------


def test_mi_index_reads_the_trade_count_column_with_thousands_commas():
    payload = _json(MI_INDEX)
    table = next(t for t in payload["tables"] if "證券代號" in (t.get("fields") or []))
    table["data"][0][3] = "160,941"
    bars = _by_symbol(
        sources.parse_twse_all_daily_payload(payload, requested_date=MI_DAY)
    )
    assert bars["0050"].trade_count == 160941
    assert bars["0051"].trade_count == 5


def test_mi_index_reads_by_column_name_not_position():
    payload = _json(MI_INDEX)
    table = next(t for t in payload["tables"] if "證券代號" in (t.get("fields") or []))
    order = list(reversed(range(len(table["fields"]))))
    table["fields"] = [table["fields"][i] for i in order]
    table["data"] = [[row[i] for i in order] for row in table["data"]]
    bars = _by_symbol(
        sources.parse_twse_all_daily_payload(payload, requested_date=MI_DAY)
    )
    assert (bars["0050"].trade_count, bars["0051"].trade_count) == (1525, 5)
    assert bars["0050"].volume == 3247891


def test_stock_day_all_reads_transaction_and_a_blank_is_null_not_zero():
    bars = sources.parse_twse_daily_rows(
        [
            _stock_day_all_row(),
            _stock_day_all_row(Code="1101", Transaction="0"),
            _stock_day_all_row(Code="1102", Transaction=""),
            _stock_day_all_row(Code="1103", Transaction="12.5"),
            _stock_day_all_row(Code="1104", Transaction="--"),
            _stock_day_all_row(Code="1105", Transaction="-3"),
        ]
    )
    counts = {bar.symbol: bar.trade_count for bar in bars}
    assert counts == {
        "2330": 119978,
        "1101": 0,
        "1102": None,
        "1103": None,
        "1104": None,
        "1105": None,
    }


def test_tpex_daily_quotes_reads_the_trade_count_of_both_tables_and_layouts():
    old = _by_symbol(
        sources.parse_tpex_daily_rows(
            _json(DAILY_QUOTES), data_as_of=DQ_DAY.isoformat()
        )
    )
    # 上櫃股票行情 and 管理股票 (2007-04-23..2020 layout).
    assert old["006201"].trade_count == 31
    assert old["1107"].trade_count == 13
    current = _by_symbol(
        sources.parse_tpex_daily_rows(_json(WWW_QUOTES), data_as_of="2026-11-09")
    )
    assert current["00411A"].trade_count == 1184
    assert current["006201"].trade_count == 658


def test_tpex_daily_quotes_commas_blank_and_fraction():
    payload = _json(WWW_QUOTES)
    table = payload["tables"][0]
    column = table["fields"].index("成交筆數")
    table["data"][0][column] = "1,234,567"
    table["data"][1][column] = "--"
    bars = _by_symbol(sources.parse_tpex_daily_rows(payload, data_as_of="2026-11-09"))
    assert bars["00411A"].trade_count == 1234567
    assert bars["006201"].trade_count is None
    table["data"][1][column] = "3.5"
    bars = _by_symbol(sources.parse_tpex_daily_rows(payload, data_as_of="2026-11-09"))
    assert bars["006201"].trade_count is None
    assert bars["006201"].volume == 1320756


def test_tpex_openapi_reads_transaction_number():
    payload = _json(OA_QUOTES)
    bars = _by_symbol(sources.parse_tpex_daily_rows(payload))
    assert bars["00411A"].trade_count == 1184
    payload[0]["TransactionNumber"] = "0"
    payload[1]["TransactionNumber"] = ""
    bars = _by_symbol(sources.parse_tpex_daily_rows(payload))
    assert bars["00411A"].trade_count == 0
    assert bars["006201"].trade_count is None


def test_openapi_and_website_tables_of_one_day_agree():
    website = _by_symbol(
        sources.parse_tpex_daily_rows(_json(WWW_QUOTES), data_as_of="2026-11-09")
    )
    openapi = _by_symbol(sources.parse_tpex_daily_rows(_json(OA_QUOTES)))
    shared = sorted(set(website) & set(openapi))
    assert shared
    assert [website[s].trade_count for s in shared] == [
        openapi[s].trade_count for s in shared
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("160,941", 160941),
        ("0", 0),
        (" 12 ", 12),
        (7, 7),
        ("", None),
        ("--", None),
        ("12.0", None),
        ("1,23", None),
        ("-1", None),
        ("9" * 5000, None),
        ("9223372036854775808", None),
        ("9,223,372,036,854,775,807", 9223372036854775807),
        (True, None),
        (3.0, None),
        (None, None),
    ],
)
def test_the_trade_count_value_rule(value, expected):
    assert sources._trade_count_from_row({"成交筆數": value}, "成交筆數") == expected


def test_index_and_close_only_bars_carry_no_trade_count():
    assert BarRecord("TAIEX", MI_DAY, 1, 1, 1, 1, 0, 0).trade_count is None


# --- upsert -------------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trade_count.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


def _record(trade_count, **changes):
    values = dict(
        symbol="2330",
        trading_date=date(2026, 11, 11),
        open=2370.0,
        high=2400.0,
        low=2365.0,
        close=2395.0,
        volume=33056476,
        turnover=77900786705.0,
        turnover_status="available",
        source="twse",
        data_as_of="2026-11-11",
        trade_count=trade_count,
    )
    values.update(changes)
    return BarRecord(**values)


def _upsert(db, *args, **kwargs):
    bar = _upsert_official_bar(db, *args, **kwargs)
    db.flush()
    return bar


def _instrument(db, symbol="2330", exchange="TWSE"):
    instrument = Instrument(
        symbol=symbol, name=symbol, exchange=exchange, instrument_type="stock"
    )
    db.add(instrument)
    db.flush()
    return instrument


def test_upsert_fills_a_null_keeps_the_first_value_and_force_rewrites(factory):
    with factory() as db:
        instrument = _instrument(db)
        bar = _upsert(db, instrument, _record(None), None)
        assert bar.trade_count is None
        fills, conflicts = [], []
        _upsert(
            db,
            instrument,
            _record(119978),
            None,
            overwrite=False,
            conflicts=conflicts,
            fills=fills,
        )
        assert bar.trade_count == 119978
        assert [fill["fields"] for fill in fills] == [["trade_count"]]
        assert conflicts == []
        fills, conflicts = [], []
        _upsert(
            db,
            instrument,
            _record(5),
            None,
            overwrite=False,
            conflicts=conflicts,
            fills=fills,
        )
        assert bar.trade_count == 119978
        assert [(c["field"], c["stored"], c["incoming"]) for c in conflicts] == [
            ("trade_count", 119978, 5)
        ]
        assert fills == []
        # Same value: nothing to fill, nothing in conflict.
        fills, conflicts = [], []
        _upsert(
            db,
            instrument,
            _record(119978),
            None,
            overwrite=False,
            conflicts=conflicts,
            fills=fills,
        )
        assert (fills, conflicts) == ([], [])
        # A blank incoming value never clears a stored one, even with --force.
        _upsert(db, instrument, _record(None), None, overwrite=True)
        assert bar.trade_count == 119978
        _upsert(db, instrument, _record(5), None, overwrite=True)
        assert bar.trade_count == 5


def test_an_upsert_without_trade_counts_reports_what_it_did_before(factory):
    """Bars whose rows have no trade count: the same fills and conflicts as before."""

    with factory() as db:
        instrument = _instrument(db)
        _upsert(db, instrument, _record(None), None)
        fills, conflicts = [], []
        bar = _upsert(
            db,
            instrument,
            _record(None, close=2400.0),
            None,
            overwrite=False,
            conflicts=conflicts,
            fills=fills,
        )
        assert fills == []
        assert [c["field"] for c in conflicts] == ["close", "adj_close"]
        assert bar.trade_count is None
        assert bar.close == 2395.0


# --- reread -------------------------------------------------------------------------


def _store_raw(db, root: Path, payload, endpoint: str, day: date, *, path=None):
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    file = root / "twse" / "2026" / "11" / "16" / f"{digest}.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(encoded)
    raw = RawPayload(
        source="test",
        endpoint=endpoint,
        payload_path=path or str(file),
        sha256=digest,
        data_as_of=day.isoformat(),
        collected_at=datetime(2026, 11, 16),
    )
    db.add(raw)
    db.flush()
    return raw, file


def _bars_from(db, raw, records, instruments):
    for record in records:
        key = (record.exchange, record.symbol)
        if key not in instruments:
            instruments[key] = _instrument(db, record.symbol, record.exchange)
        # The rows as the research DB has them: written before #1094.
        _upsert_official_bar(
            db,
            instruments[key],
            BarRecord(**{**record.__dict__, "trade_count": None}),
            raw.id,
        )


def _seed(db, raw_root: Path):
    instruments: dict = {}
    mi = _json(MI_INDEX)
    endpoint = f"{sources.TWSE_DAILY_HISTORY_ENDPOINT}?date=20190430&type=ALLBUT0999"
    raw, _ = _store_raw(db, raw_root, mi, endpoint, MI_DAY)
    _bars_from(
        db,
        raw,
        sources.parse_twse_all_daily_payload(mi, requested_date=MI_DAY),
        instruments,
    )
    dq = _json(DAILY_QUOTES)
    raw, _ = _store_raw(db, raw_root, dq, sources.TPEX_HISTORY_API, DQ_DAY)
    _bars_from(
        db,
        raw,
        sources.parse_tpex_daily_rows(dq, data_as_of=DQ_DAY.isoformat()),
        instruments,
    )
    db.commit()


def _counts(db):
    return {
        (symbol, day.isoformat()): count
        for symbol, day, count in db.execute(
            select(
                Instrument.symbol, MarketBar.trading_date, MarketBar.trade_count
            ).join(Instrument, Instrument.id == MarketBar.instrument_id)
        )
    }


EXPECTED = {
    ("0050", "2019-04-30"): 1525,
    ("0051", "2019-04-30"): 5,
    ("006201", "2011-11-01"): 31,
}


def test_reread_fills_every_null_from_the_bars_own_capture(factory, tmp_path):
    raw_root = tmp_path / "data" / "raw"
    with factory() as db:
        _seed(db, raw_root)
        result = trade_count_reread.reread(db)
        counts = _counts(db)
    assert result["status"] == "success", result
    assert result["written"] == len(counts) == 11
    assert all(value is not None for value in counts.values())
    assert {key: counts[key] for key in EXPECTED} == EXPECTED
    assert counts[("1107", "2011-11-01")] == 13
    assert result["by_year"] == {"2011": {"tpex": 9}, "2019": {"twse": 2}}
    assert result["months"] == (2019 - 2011) * 12 + 4 - 11 + 1
    assert result["captures_read"] == {"volume": 2, "fallback": 0}


def test_a_second_reread_writes_nothing_and_keeps_the_values(factory, tmp_path):
    with factory() as db:
        _seed(db, tmp_path / "data" / "raw")
        trade_count_reread.reread(db)
        first = _counts(db)
        again = trade_count_reread.reread(db)
        assert again["status"] == "success"
        assert again["written"] == 0
        assert again["captures_read"] == {"volume": 0, "fallback": 0}
        assert _counts(db) == first


def test_reread_only_fills_nulls(factory, tmp_path):
    with factory() as db:
        _seed(db, tmp_path / "data" / "raw")
        bar = db.scalar(
            select(MarketBar)
            .join(Instrument, Instrument.id == MarketBar.instrument_id)
            .where(Instrument.symbol == "0050")
        )
        bar.trade_count = 7
        db.commit()
        result = trade_count_reread.reread(db)
        assert result["written"] == 10
        assert _counts(db)[("0050", "2019-04-30")] == 7


def test_reread_uses_the_bars_raw_not_one_dated_by_data_as_of(factory, tmp_path):
    """A STOCK_DAY_ALL captured the next day (stale table) is never read for a bar."""

    raw_root = tmp_path / "data" / "raw"
    with factory() as db:
        _seed(db, raw_root)
        # Same volume as the 0050 bar, so only the choice of capture can tell.
        stale = [
            _stock_day_all_row(
                Date="1080430", Code="0050", TradeVolume="3247891", Transaction="999"
            )
        ]
        _store_raw(db, raw_root, stale, sources.TWSE_DAILY_ENDPOINT, MI_DAY)
        db.commit()
        trade_count_reread.reread(db)
        assert _counts(db)[("0050", "2019-04-30")] == 1525


def test_a_seed_rows_windows_path_is_read_from_the_fallback_raw_dir(factory, tmp_path):
    """A seed row copied from production: an old Windows path, file only in /prod."""

    prod = tmp_path / "prod" / "raw"
    with factory() as db:
        mi = _json(MI_INDEX)
        endpoint = f"{sources.TWSE_DAILY_HISTORY_ENDPOINT}?date=20190430"
        legacy = (
            "C:\\Users\\YiCheng\\stock-lab-data\\raw\\twse\\2026\\10\\17\\seed.json"
        )
        raw, file = _store_raw(db, tmp_path / "elsewhere", mi, endpoint, MI_DAY)
        raw.payload_path = legacy
        target = prod / "twse" / "2026" / "10" / "17" / "seed.json"
        target.parent.mkdir(parents=True)
        file.rename(target)
        _bars_from(
            db,
            raw,
            sources.parse_twse_all_daily_payload(mi, requested_date=MI_DAY),
            {},
        )
        db.commit()

        missing = trade_count_reread.reread(db)
        assert missing["status"] == "partial"
        assert missing["not_written"] == {"raw_file_missing": 2}
        assert missing["samples"][0]["raw_payload_id"] == raw.id

        found = trade_count_reread.reread(db, fallback_raw_dir=str(prod))
        assert found["status"] == "success", found
        assert found["written"] == 2
        assert found["captures_read"] == {"volume": 0, "fallback": 1}
        assert _counts(db)[("0050", "2019-04-30")] == 1525


def test_a_data_raw_path_missing_here_is_read_from_the_fallback(factory, tmp_path):
    raw_root = tmp_path / "data" / "raw"
    prod = tmp_path / "prod" / "raw"
    with factory() as db:
        dq = _json(DAILY_QUOTES)
        raw, file = _store_raw(db, raw_root, dq, sources.TPEX_HISTORY_API, DQ_DAY)
        target = prod / file.relative_to(raw_root)
        target.parent.mkdir(parents=True)
        file.rename(target)
        _bars_from(
            db,
            raw,
            sources.parse_tpex_daily_rows(dq, data_as_of=DQ_DAY.isoformat()),
            {},
        )
        db.commit()
        result = trade_count_reread.reread(db, fallback_raw_dir=str(prod))
    assert result["status"] == "success", result
    assert result["written"] == 9


def test_a_changed_file_or_row_is_not_written(factory, tmp_path):
    raw_root = tmp_path / "data" / "raw"
    with factory() as db:
        _seed(db, raw_root)
        mi_raw = db.scalar(
            select(RawPayload).where(RawPayload.endpoint.contains("MI_INDEX"))
        )
        Path(mi_raw.payload_path).write_text("{}", encoding="utf-8")
        bar = db.scalar(
            select(MarketBar)
            .join(Instrument, Instrument.id == MarketBar.instrument_id)
            .where(Instrument.symbol == "1107")
        )
        bar.volume += 1
        db.commit()
        result = trade_count_reread.reread(db)
        counts = _counts(db)
    assert result["status"] == "partial"
    assert result["not_written"] == {"raw_sha256_mismatch": 2, "volume_mismatch": 1}
    assert counts[("0050", "2019-04-30")] is None
    assert counts[("1107", "2011-11-01")] is None
    assert counts[("006201", "2011-11-01")] == 31


def test_index_and_other_sources_are_left_alone(factory, tmp_path):
    with factory() as db:
        _seed(db, tmp_path / "data" / "raw")
        index = _instrument(db, "TAIEX")
        index.instrument_type = "index"
        db.add(
            MarketBar(
                instrument_id=index.id,
                trading_date=MI_DAY,
                close=10000.0,
                adj_close=10000.0,
                source="twse_index_ohlcv",
            )
        )
        db.commit()
        result = trade_count_reread.reread(db)
        assert result["status"] == "success"
        assert _counts(db)[("TAIEX", "2019-04-30")] is None


def test_a_range_limits_the_months(factory, tmp_path):
    with factory() as db:
        _seed(db, tmp_path / "data" / "raw")
        result = trade_count_reread.reread(db, date(2019, 4, 1), date(2019, 4, 30))
        assert result["by_year"] == {"2019": {"twse": 2}}
        assert result["months"] == 1
        assert _counts(db)[("006201", "2011-11-01")] is None


# --- command ------------------------------------------------------------------------


def _cli(monkeypatch, argv):
    import worker.cli as cli_module

    monkeypatch.setattr("sys.argv", ["worker.cli", *argv])
    try:
        cli_module.main()
    except SystemExit as exc:
        return exc.code
    return 0


def test_the_command_refuses_a_database_without_the_research_marker(
    monkeypatch, tmp_path, capsys
):
    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")

    def never(*args, **kwargs):
        raise AssertionError("no reread without the research marker")

    class NoHold:
        def __init__(self, *args, **kwargs):
            raise AssertionError("refused before maintenance mode")

    monkeypatch.setattr(cli_module, "run_trade_count_reread", never)
    monkeypatch.setattr(cli_module.scheduled_job, "MaintenanceHold", NoHold)
    assert _cli(monkeypatch, ["trade-count", "reread"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "research-db.json" in out["error"]


def test_the_runner_refuses_without_the_marker(tmp_path):
    (tmp_path / "stock.db").write_bytes(b"")
    out = trade_count_reread.run_trade_count_reread(db_path=tmp_path / "stock.db")
    assert out["status"] == "refused"


def test_the_command_holds_maintenance_mode_and_passes_its_options(
    monkeypatch, tmp_path
):
    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    (tmp_path / "research-db.json").write_text('{"purpose": "research_history"}')
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")
    seen = {}

    def run(start, end, *, fallback_raw_dir, db_path):
        seen.update(start=start, end=end, fallback=fallback_raw_dir, db=db_path)
        return {"status": "partial"}

    monkeypatch.setattr(cli_module, "run_trade_count_reread", run)
    held = []

    class Hold:
        def __init__(self, data_dir, command, reason=None):
            held.append(command)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli_module.scheduled_job, "MaintenanceHold", Hold)
    argv = [
        "trade-count",
        "reread",
        "--from",
        "2024-01-01",
        "--to",
        "2024-01-31",
        "--fallback-raw-dir",
        "/prod/raw",
    ]
    assert _cli(monkeypatch, argv) == 2
    assert held == ["trade-count reread"]
    assert seen == {
        "start": "2024-01-01",
        "end": "2024-01-31",
        "fallback": "/prod/raw",
        "db": tmp_path / "stock.db",
    }


def _alembic_config(engine):
    from alembic.config import Config

    from app import migrations

    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    return config


def _bar_table(path: Path):
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(market_bars)")
        }
        names = [name for name in columns if name != "trade_count"]
        rows = connection.execute(
            f"SELECT {', '.join(names)} FROM market_bars ORDER BY id"
        ).fetchall()
        counts = (
            connection.execute(
                "SELECT trade_count FROM market_bars ORDER BY id"
            ).fetchall()
            if "trade_count" in columns
            else None
        )
        checks = (
            connection.execute("PRAGMA integrity_check").fetchall(),
            connection.execute("PRAGMA foreign_key_check").fetchall(),
        )
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
    return columns, rows, counts, checks, version


def test_the_migration_goes_down_and_up_again_keeping_every_row(tmp_path):
    """0045 down drops only the column; up adds it back nullable (add_column runs)."""

    pytest.importorskip("alembic")
    from alembic import command

    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith("_trade_count"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    path = tmp_path / "down.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = _alembic_config(engine)
    try:
        command.upgrade(config, revision)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO instruments (id, market, exchange, symbol, name, "
                "instrument_type, is_watchlisted, status, created_at) VALUES "
                "(1, 'TW', 'TWSE', '2330', '台積電', 'stock', 0, 'active', "
                "'2026-11-11 10:00:00')"
            )
            for bar_id, day, count in (
                (1, "2026-11-11", 119978),
                (2, "2026-11-12", None),
            ):
                connection.exec_driver_sql(
                    "INSERT INTO market_bars (id, instrument_id, trading_date, open, "
                    "high, low, close, adj_close, volume, turnover, turnover_status, "
                    "source, collected_at, is_suspended, trade_count) VALUES "
                    f"({bar_id}, 1, '{day}', 2370, 2400, 2365, 2395, 2395, 33056476, "
                    "77900786705, 'available', 'twse', '2026-11-12 10:00:00', 0, ?)",
                    (count,),
                )
        columns, rows, counts, checks, version = _bar_table(path)
        assert columns["trade_count"][2] == "INTEGER"
        assert columns["trade_count"][3] == 0  # nullable
        assert counts == [(119978,), (None,)]
        assert version == [(revision,)]

        command.downgrade(config, previous)
        down_columns, down_rows, down_counts, down_checks, down_version = _bar_table(
            path
        )
        assert "trade_count" not in down_columns
        assert set(down_columns) == set(columns) - {"trade_count"}
        assert down_rows == rows and down_counts is None
        assert down_checks == ([("ok",)], [])
        assert down_version == [(previous,)]

        command.upgrade(config, revision)
        up_columns, up_rows, up_counts, up_checks, up_version = _bar_table(path)
        assert up_columns["trade_count"][2] == "INTEGER"
        assert up_columns["trade_count"][3] == 0
        assert up_rows == rows and up_counts == [(None,), (None,)]
        assert up_checks == ([("ok",)], [])
        assert up_version == [(revision,)]
    finally:
        engine.dispose()
