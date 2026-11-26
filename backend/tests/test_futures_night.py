"""The TX near-month night session from the TAIFEX download futDataDown (Issue #1040).

The CSVs copy the format of the #1002 probe (19 columns, cp950, the regular and
after-hours rows of every contract month, calendar spreads, ``-`` for the night's
settlement and open interest, a trailing empty column), but every number is made
up (test_futures_history.py: the TAIFEX terms do not allow republishing).
"""

from __future__ import annotations

import socket
from argparse import Namespace
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    FuturesNightBar,
    IngestionRun,
    MarketBar,
    RawPayload,
    TechnicalIndicator,
    TradingCalendarDay,
)
from test_futures_history import HEADER, SiteGet, _row, csv_bytes, csv_text
from worker import futures_history as fh
from worker import sources
from worker.index_bars import Month
from worker.sources import OfficialDataError

# 2026-11-24 (Tuesday): at 08:15 the CSV lists the date with the night of 11/23 only.
DAY = date(2026, 11, 24)
MORNING = datetime(2026, 11, 24, 8, 15)


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in futures night tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'night.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


def night_rows(
    day: date, near: str = "202612", close: int = 21000, **cells
) -> list[str]:
    """The night rows the site lists under ``day`` (made-up numbers)."""

    year, month = int(near[:4]), int(near[4:])
    following = f"{year + (month == 12):04d}{month % 12 + 1:02d}"
    night = {
        "結算價": "-",
        "未沖銷契約數": "-",
        "漲跌價": "-123",
        "漲跌%": "-0.58%",
        "成交量": "45678",
    }
    return [
        _row(day, near, "盤後", close=close, **{**night, **cells}),
        _row(day, following, "盤後", close=close + 50, **night),
        # A calendar spread: never the near month.
        _row(day, f"{near}/{following}  ", "盤後", close=45, **night),
    ]


def morning_csv(day: date = DAY, **cells) -> bytes:
    """What the site answers for ``day``..``day`` before ``day``'s regular session."""

    return csv_bytes([], night_rows(day, **cells))


class Get:
    """``get`` recording the requests; answers ``content`` (or raises it)."""

    def __init__(self, content) -> None:
        self.content = content
        self.requests: list[fh.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        if isinstance(self.content, Exception):
            raise self.content
        return self.content


def collect(factory, get, **kwargs):
    kwargs.setdefault("now", MORNING)
    with factory() as db:
        return fh.collect_night(db, get=get, **kwargs)


def stored(factory) -> list[FuturesNightBar]:
    with factory() as db:
        return list(
            db.scalars(select(FuturesNightBar).order_by(FuturesNightBar.trading_date))
        )


# --- parsing ------------------------------------------------------------------------


def test_the_near_month_night_row_is_read_with_its_signed_change():
    request = fh.Request(Month.of(DAY), DAY, DAY)

    parsed = fh.parse_month(fh.decode(morning_csv()), request)

    assert parsed.bars == [] and parsed.after_hours_only_dates == [DAY.isoformat()]
    assert parsed.night_bars == [
        fh.NightBar(
            trading_date=DAY,
            contract_month="202612",
            open=20970.0,
            high=21040.0,
            low=20950.0,
            close=21000.0,
            change=-123.0,
            volume=45678,
            price_reason=None,
        )
    ]
    assert parsed.night_unusable_dates == []


def test_the_regular_bars_are_the_same_with_the_night_rows_read():
    """The regular-session rule is unchanged (AC-1): night rows add nothing to ``bars``."""

    day = date(2024, 10, 4)
    request = fh.request_for(Month(2024, 10), date(2026, 11, 9))
    plain = fh.parse_month(csv_text([day]), request)

    parsed = fh.parse_month(
        csv_text([day], night_rows(date(2024, 10, 7), "202410")), request
    )

    assert parsed.bars == plain.bars and len(parsed.bars) == 1
    assert parsed.bars[0].contract_month == "202410"
    assert [bar.trading_date for bar in parsed.night_bars] == [day, date(2024, 10, 7)]


@pytest.mark.parametrize(
    "day, near",
    [
        # 2024-10: the third Wednesday is 10/16, 202410's last trading day. The night
        # filed under 10/15 trades 202410; the one filed under 10/16 is 202411's, as
        # the regular-session rule takes 202411 from that day on.
        (date(2024, 10, 15), "202410"),
        (date(2024, 10, 16), "202411"),
        # December rolls into January of the next year.
        (date(2024, 12, 18), "202501"),
    ],
)
def test_the_night_takes_the_near_month_of_its_trading_date(day, near):
    from worker.futures_bars import near_month

    expiring = f"{day.year:04d}{day.month:02d}"
    rows = night_rows(day, near)
    if expiring != near:
        # The expiring month is still listed before the near one.
        rows = [_row(day, expiring, "盤後", close=19000, 結算價="-")] + rows
    request = fh.Request(Month.of(day), day, day)

    parsed = fh.parse_month(csv_text([], rows), request)

    assert near_month(day) == near
    assert [(b.trading_date, b.contract_month) for b in parsed.night_bars] == [
        (day, near)
    ]
    assert parsed.night_bars[0].close == 21000.0


def test_a_night_without_trades_is_listed_unusable_and_a_missing_open_is_empty():
    other = date(2026, 11, 23)
    rows = night_rows(DAY, 開盤價="-") + [
        _row(other, "202612", "盤後", 收盤價="-", 成交量="0", 結算價="-")
    ]
    request = fh.Request(Month.of(DAY), other, DAY)

    parsed = fh.parse_month(csv_text([], rows), request)

    assert [(b.open, b.high, b.low) for b in parsed.night_bars] == [(None, None, None)]
    assert parsed.night_bars[0].price_reason == "source_missing_ohlc"
    assert parsed.night_unusable_dates == [other.isoformat()]


# --- the collect ----------------------------------------------------------------------


def test_the_night_is_stored_with_its_source_raw_and_date(factory):
    get = Get(morning_csv())

    result = collect(factory, get)

    assert result["status"] == "success" and result["requests"] == 1
    assert [request.form for request in get.requests] == [
        {
            "down_type": "1",
            "commodity_id": "TX",
            "queryStartDate": "2026/11/24",
            "queryEndDate": "2026/11/24",
        }
    ]
    [row] = stored(factory)
    assert (row.symbol, row.trading_date, row.contract_month) == ("TX", DAY, "202612")
    assert (row.open, row.high, row.low, row.close) == (
        20970.0,
        21040.0,
        20950.0,
        21000.0,
    )
    assert (row.change, row.volume, row.price_reason) == (-123.0, 45678, None)
    assert row.source == "taifex_futdatadown"
    assert row.data_as_of == datetime(2026, 11, 24)
    with factory() as db:
        raw = db.get(RawPayload, row.raw_payload_id)
        run = db.get(IngestionRun, result["run_id"])
        # The regular-session bars and their indicators are untouched (AC-1).
        assert db.scalar(select(func.count()).select_from(MarketBar)) == 0
        assert db.scalar(select(func.count()).select_from(TechnicalIndicator)) == 0
    assert raw.source == "taifex_web" and raw.data_as_of == DAY.isoformat()
    assert raw.endpoint.startswith(fh.ENDPOINT + "?down_type=1&commodity_id=TX")
    assert raw.ingestion_run_id == run.id
    assert (run.run_type, run.status, run.run_date) == (
        "futures_night_collect",
        "success",
        DAY,
    )
    assert run.metadata_json["nights"] == [DAY.isoformat()]


def test_the_regular_tx_bars_are_kept_as_they_are(factory):
    """A month read stores the nights only: the history's TX rows do not move (AC-1)."""

    oct_days = [date(2024, 10, 1), date(2024, 10, 2)]
    with factory() as db:
        history = fh.backfill_futures_history(
            db,
            first=Month(2024, 10),
            last=Month(2024, 10),
            get=SiteGet(oct_days),
            sleep=lambda _: None,
            today=date(2026, 11, 9),
        )
        before = [
            (bar.trading_date, bar.close, bar.source, bar.raw_payload_id)
            for bar in db.scalars(select(MarketBar).order_by(MarketBar.trading_date))
        ]
        indicators = db.scalar(select(func.count()).select_from(TechnicalIndicator))
    assert history["counts"]["inserted"] == 2
    # The history wrote no night (it reads the regular rows only).
    assert stored(factory) == []

    result = collect(
        factory,
        Get(csv_bytes(oct_days)),
        month=Month(2024, 10),
        now=datetime(2026, 11, 9, 8, 15),
    )

    assert result["status"] == "success"
    assert [row.trading_date for row in stored(factory)] == oct_days
    with factory() as db:
        after = [
            (bar.trading_date, bar.close, bar.source, bar.raw_payload_id)
            for bar in db.scalars(select(MarketBar).order_by(MarketBar.trading_date))
        ]
        assert db.scalar(select(func.count()).select_from(TechnicalIndicator)) == (
            indicators
        )
    assert after == before


def test_the_same_night_read_again_is_idempotent(factory):
    first = collect(factory, Get(morning_csv()))
    [row] = stored(factory)

    again = Get(morning_csv())
    second = collect(factory, again)
    forced = collect(factory, Get(morning_csv()), force=True)
    month = collect(factory, Get(morning_csv()), month=Month(2026, 11))

    assert first["status"] == "success"
    # Stored: no request at all.
    assert second["status"] == "already_complete" and again.requests == []
    assert second["requests"] == 0
    # Asked again: the same values change nothing.
    assert forced["status"] == "success" and forced["counts"]["unchanged"] == 1
    assert month["status"] == "success" and month["counts"]["unchanged"] == 1
    [kept] = stored(factory)
    assert (kept.id, kept.raw_payload_id, kept.collected_at) == (
        row.id,
        row.raw_payload_id,
        row.collected_at,
    )


def test_a_night_read_with_other_values_is_a_conflict_unless_forced(factory):
    collect(factory, Get(morning_csv()))
    changed = morning_csv(close=21500)

    kept = collect(factory, Get(changed), month=Month(2026, 11))
    assert kept["counts"]["conflict"] == 1 and stored(factory)[0].close == 21000.0
    assert "differ from the report" in kept["warnings"][-1]

    forced = collect(factory, Get(changed), force=True)
    assert forced["counts"]["replaced"] == 1 and stored(factory)[0].close == 21500.0


@pytest.mark.parametrize(
    "content, message",
    [
        (
            '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">\r\n<html>日期時間錯誤</html>',
            "HTML",
        ),
        ("交易日期,契約,到期月份\r\n", "header"),
        (HEADER + "\r\n2026/11/24,TX,202612\r\n", "columns"),
        (csv_text([], night_rows(date(2026, 11, 23))), "outside"),
        (csv_text([], night_rows(DAY, 契約="MTX")), "MTX"),
        (b"\xff\xfe\xfa", "cp950"),
        ("", "nothing"),
    ],
)
def test_a_broken_answer_is_rejected_whole_as_the_history_does(
    factory, content, message
):
    result = collect(factory, Get(content))

    assert result["status"] == "failed" and message in result["error"]
    assert stored(factory) == []
    with factory() as db:
        run = db.get(IngestionRun, result["run_id"])
        raw = db.get(RawPayload, result["raw_payload_id"])
    # The error is on the run (as us-collect), and the answer is kept as raw.
    assert run.status == "failed" and message in run.error
    assert raw is not None and raw.source == "taifex_web"


def test_a_transport_failure_is_a_failed_run(factory):
    result = collect(factory, Get(OfficialDataError("TAIFEX futDataDown answered 503")))

    assert result["status"] == "failed" and "503" in result["error"]
    assert result["raw_payload_id"] is None and stored(factory) == []
    with factory() as db:
        assert "503" in db.get(IngestionRun, result["run_id"]).error


def test_a_night_not_listed_yet_is_partial(factory):
    result = collect(factory, Get(csv_bytes([])))

    assert result["status"] == "partial" and stored(factory) == []
    assert "lists no TX night for 2026-11-24 yet" in result["warnings"][0]


def test_a_night_still_trading_before_0500_is_not_stored(factory):
    early = collect(factory, Get(morning_csv()), now=datetime(2026, 11, 24, 1, 6))
    assert early["status"] == "partial" and early["in_progress_dates"] == ["2026-11-24"]
    assert stored(factory) == []

    after = collect(factory, Get(morning_csv()), now=datetime(2026, 11, 24, 5, 0))
    assert after["status"] == "success" and len(stored(factory)) == 1


def test_a_closed_day_asks_nothing(factory):
    with factory() as db:
        raw = RawPayload(source="twse_holiday_schedule", endpoint="holidaySchedule")
        db.add(raw)
        db.flush()
        db.add(
            TradingCalendarDay(
                exchange="TWSE",
                calendar_date=DAY,
                year=2026,
                kind="closed",
                name="放假",
                source="twse_holiday_schedule",
                collected_at=datetime(2026, 1, 1),
                raw_payload_id=raw.id,
            )
        )
        db.commit()
    get = Get(morning_csv())

    closed = collect(factory, get)
    weekend = collect(factory, get, day=date(2026, 11, 22))

    assert closed["status"] == weekend["status"] == "non_trading_day"
    assert get.requests == []


def test_a_job_skip_is_a_skipped_run_without_a_request(factory):
    get = Get(morning_csv())

    result = collect(factory, get, skip_reason="low_memory")

    assert result["status"] == "skipped" and get.requests == []
    with factory() as db:
        run = db.get(IngestionRun, result["run_id"])
    assert run.metadata_json["skip_reason"] == "low_memory"


def test_a_future_day_or_month_is_refused_before_any_run(factory):
    get = Get(morning_csv())
    with factory() as db:
        with pytest.raises(ValueError, match="after today"):
            fh.collect_night(db, day=date(2026, 11, 25), get=get, now=MORNING)
        with pytest.raises(ValueError, match="after the current month"):
            fh.collect_night(db, month=Month(2026, 12), get=get, now=MORNING)
        assert db.scalar(select(func.count()).select_from(IngestionRun)) == 0
    assert get.requests == []


# --- the command ------------------------------------------------------------------------


def test_futures_night_runs_without_maintenance_mode():
    # One request into its own table, idempotent: no maintenance (as us-collect).
    from worker.cli import maintenance_guarded

    args = Namespace(command="index-bars", index_bars_command="futures-night")

    assert maintenance_guarded(args) is None


def test_the_exit_codes_of_futures_night():
    from worker.cli import FUTURES_NIGHT_EXIT_CODES

    assert FUTURES_NIGHT_EXIT_CODES == {
        "success": 0,
        "already_complete": 0,
        "non_trading_day": 0,
        "skipped": 0,
        "partial": 2,
    }


# --- the migration -----------------------------------------------------------------------

NIGHT_INDEXES = {
    "ix_futures_night_bars_trading_date",
    "ix_futures_night_bars_raw_payload_id",
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


def _schema(engine):
    names = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        indexes = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        version = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        fk = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    return names, indexes, version, fk


def test_the_migration_goes_down_and_up_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command

    from app.migration_revisions import REVISIONS

    revision = next(name for name in REVISIONS if name.endswith("_futures_night_bars"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'down.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = _alembic_config(engine)
    try:
        command.upgrade(config, revision)
        with Session(engine) as db:
            raw = RawPayload(source="taifex_web", endpoint=fh.ENDPOINT)
            db.add(raw)
            db.flush()
            db.add(
                FuturesNightBar(
                    symbol="TX",
                    trading_date=DAY,
                    contract_month="202612",
                    open=20970.0,
                    high=21040.0,
                    low=20950.0,
                    close=21000.0,
                    change=-123.0,
                    volume=45678,
                    source=fh.SOURCE,
                    data_as_of=datetime(2026, 11, 24),
                    raw_payload_id=raw.id,
                )
            )
            db.commit()
        names, indexes, version, _fk = _schema(engine)
        assert "futures_night_bars" in names and NIGHT_INDEXES <= indexes
        assert version == [(revision,)]

        command.downgrade(config, previous)
        names, indexes, version, fk = _schema(engine)
        assert "futures_night_bars" not in names and not NIGHT_INDEXES & indexes
        assert version == [(previous,)] and fk == []

        command.upgrade(config, revision)
        names, indexes, version, fk = _schema(engine)
        assert "futures_night_bars" in names and NIGHT_INDEXES <= indexes
        assert version == [(revision,)] and fk == []
    finally:
        engine.dispose()
