"""The short-sale balance of the official margin files (Issue #662).

The three margin files collect reads (TWSE ``MI_MARGN`` ``selectType=ALL``,
the TPEx website ``margin/balance`` and the TPEx OpenAPI
``tpex_mainboard_margin_balance``) list each security's 融券今日餘額 next to
its margin balance.  Until #662 collect wrote only the margin columns, so
``chip_snapshots.short_balance`` stayed empty.  The fixture rows are the
2026-11-12 captures' layouts: TWSE short balance at position 12, TPEx website
at position 14 (``券餘額``; ``前券餘額(張)`` contains that text too).
"""

import json
import socket
import sqlite3
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app import chip_provenance as groups_of
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import ChipSnapshot, IngestionRun, Instrument, RawPayload
from app.raw_paths import payload_file
import worker.chip_provenance as chip_provenance
import worker.chip_revisions as chip_revisions
import worker.cli as cli
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher

DAY = date(2026, 9, 4)
NOW = datetime(2026, 9, 4, 13, 30)

TWSE_FIELDS = [
    "代號",
    "名稱",
    "買進",
    "賣出",
    "現金償還",
    "前日餘額",
    "今日餘額",
    "次一營業日限額",
    "買進",
    "賣出",
    "現券償還",
    "前日餘額",
    "今日餘額",
    "次一營業日限額",
    "資券互抵",
    "註記",
]
TPEX_FIELDS = [
    "代號",
    "名稱",
    "前資餘額(張)",
    "資買",
    "資賣",
    "現償",
    "資餘額",
    "資屬證金",
    "資使用率(%)",
    "資限額",
    "前券餘額(張)",
    "券賣",
    "券買",
    "券償",
    "券餘額",
    "券屬證金",
    "券使用率(%)",
    "券限額",
    "資券相抵(張)",
    "備註",
]


def twse_row(code, margin=("16,405", "15,060"), short=("6", "7")):
    # 00400A 2026-11-12: margin 16,405 -> 15,060, short 6 -> 7.
    return [
        code,
        "name",
        "671",
        "1,903",
        "113",
        *margin,
        "608,285",
        "0",
        "1",
        "0",
        *short,
        "608,285",
        "74",
        " ",
    ]


def tpex_row(code, margin=("2,549", "2,994"), short=("23", "22")):
    # 00679B 2026-11-12: margin 2,549 -> 2,994, short 23 -> 22.
    return [
        code,
        "name",
        margin[0],
        "539",
        "93",
        "1",
        margin[1],
        "22",
        "0.2",
        "1,474,548",
        short[0],
        "0",
        "1",
        "0",
        short[1],
        "0",
        "0.0",
        "1,474,548",
        "0",
        "",
    ]


def twse_payload(*rows):
    return {
        "date": "20260904",
        "stat": "OK",
        "tables": [
            {"fields": ["項目"], "data": [["融券(交易單位)"]]},
            {"fields": TWSE_FIELDS, "data": list(rows)},
        ],
    }


def tpex_payload(*rows):
    return {
        "stat": "ok",
        "date": "20260904",
        "tables": [{"fields": TPEX_FIELDS, "data": list(rows)}],
    }


def openapi_row(code, **values):
    row = {
        "Date": "1150904",
        "SecuritiesCompanyCode": code,
        "MarginPurchaseBalancePreviousDay": "18633",
        "MarginPurchaseBalance": "19841",
        "ShortSaleBalancePreviousDay": "2",
        "ShortSaleBalance": "3",
    }
    row.update(values)
    return {key: value for key, value in row.items() if value is not None}


# ---- AC-2: the parsers -------------------------------------------------------


def test_twse_margin_file_gives_the_short_balance_and_no_value_for_a_dash():
    rows = sources.parse_twse_margin_rows(
        twse_payload(twse_row("00400A"), twse_row("2330", short=("5", "--"))),
        trading_date=DAY,
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["00400A"].short_balance == 7
    assert by_symbol["00400A"].margin_balance == 15060
    assert by_symbol["00400A"].margin_change == 15060 - 16405
    assert by_symbol["2330"].short_balance is None
    assert by_symbol["2330"].margin_balance == 15060


def test_twse_margin_file_without_the_short_columns_gives_no_short_balance():
    payload = twse_payload(twse_row("00400A")[:7])
    payload["tables"][1]["fields"] = TWSE_FIELDS[:7]
    (row,) = sources.parse_twse_margin_rows(payload, trading_date=DAY)
    assert row.margin_balance == 15060
    assert row.short_balance is None


def test_tpex_website_file_gives_the_short_balance_not_the_previous_day():
    rows = sources.parse_tpex_margin_rows(
        tpex_payload(tpex_row("00679B"), tpex_row("6488", short=("4", ""))),
        trading_date=DAY,
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["00679B"].short_balance == 22
    assert by_symbol["00679B"].margin_balance == 2994
    assert by_symbol["6488"].short_balance is None
    short_less = tpex_payload(tpex_row("00679B")[:10])
    (row,) = sources.parse_tpex_margin_rows(short_less, trading_date=DAY)
    assert row.margin_balance == 2994
    assert row.short_balance is None


@pytest.mark.parametrize("header", ["券餘額", "券餘額(張)"])
def test_tpex_website_rows_as_dicts_read_the_short_balance_not_the_previous_day(
    header,
):
    # Review 6840422442 (7): a fields/data payload without ``tables`` goes
    # through the dict path; 前券餘額(張) must never be read.
    fields = [header if name == "券餘額" else name for name in TPEX_FIELDS]
    payload = {"fields": fields, "data": [tpex_row("00679B")]}
    (row,) = sources.parse_tpex_margin_rows(payload, trading_date=DAY)
    assert (row.margin_balance, row.short_balance) == (2994, 22)
    only_previous = {
        "fields": [name for name in fields if name != header],
        "data": [[cell for i, cell in enumerate(tpex_row("00679B")) if i != 14]],
    }
    (row,) = sources.parse_tpex_margin_rows(only_previous, trading_date=DAY)
    assert row.short_balance is None


def test_tpex_openapi_row_gives_the_short_balance_by_its_exact_key():
    rows = sources.parse_tpex_margin_rows(
        [
            openapi_row("00411A"),
            openapi_row("1240", ShortSaleBalance="--"),
            # Only the previous day's value: never read as the current one.
            openapi_row("3105", ShortSaleBalance=None),
        ],
        trading_date=DAY,
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["00411A"].short_balance == 3
    assert by_symbol["00411A"].margin_balance == 19841
    assert by_symbol["1240"].short_balance is None
    assert by_symbol["3105"].short_balance is None


def test_the_merged_record_keeps_the_margin_files_short_balance():
    institutional = sources.ChipRecord(
        symbol="1101", trading_date=DAY, foreign_buy=1, source="twse_t86"
    )
    (margin,) = sources.parse_twse_margin_rows(
        twse_payload(twse_row("1101")), trading_date=DAY
    )
    (merged,) = sources.merge_chip_records(
        [institutional], [margin], allowed_symbols={"1101"}, exchange="TWSE"
    )
    assert merged.short_balance == 7
    assert merged.foreign_buy == 1


def test_the_margin_group_holds_the_short_balance():
    assert "short_balance" in groups_of.GROUP_FIELDS[groups_of.MARGIN]
    assert "short_balance" not in groups_of.GROUP_FIELDS[groups_of.INSTITUTIONAL]


# ---- AC-2: collect writes it -------------------------------------------------


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in short balance tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'short.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sources, "utcnow", lambda: NOW)
    # 12:00 Taipei: outside the fill's stop window whenever the tests run.
    monkeypatch.setattr(chip_revisions, "utcnow", lambda: datetime(2026, 9, 5, 4))
    yield factory
    engine.dispose()


class Fetcher(FixtureFetcher):
    """The fixture feeds with a short-sale balance in both margin files."""

    def __init__(self, twse_short="88", tpex_short="45"):
        super().__init__()
        self.twse_short, self.tpex_short = twse_short, tpex_short

    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            # Official numeric industry codes, as test_institutional_revisions.
            return [
                dict(row, Industry="01" if row["Code"] == "1101" else "24")
                for row in payload
            ]
        if url.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT):
            table = payload["tables"][1]
            row = list(table["data"][0])
            row[11], row[12] = "77", self.twse_short
            return dict(payload, tables=[payload["tables"][0], dict(table, data=[row])])
        if url == sources.TPEX_MARGIN_HISTORY_ENDPOINT:
            table = payload["tables"][0]
            row = list(table["data"][0])
            row[10], row[14] = "40", self.tpex_short
            return dict(payload, tables=[dict(table, data=[row])])
        return payload


def collect(fetcher):
    return pipeline.collect(
        DAY,
        adapter=sources.OfficialMarketDataAdapter(
            sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher)
        ),
    )


def chip(db, symbol):
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    return db.scalar(
        select(ChipSnapshot).where(
            ChipSnapshot.instrument_id == instrument.id,
            ChipSnapshot.trading_date == DAY,
        )
    )


def margin_capture(db, endpoint):
    return db.scalar(
        select(RawPayload.id).where(RawPayload.endpoint.like(f"{endpoint}%"))
    )


def test_collect_writes_the_short_balance_with_the_margin_capture(database):
    result = collect(Fetcher())
    assert result["status"] == "success", result
    with database() as db:
        twse, tpex = chip(db, "1101"), chip(db, "7001")
        assert (twse.margin_balance, twse.short_balance) == (11242, 88)
        assert (tpex.margin_balance, tpex.short_balance) == (110, 45)
        assert twse.margin_raw_payload_id == margin_capture(
            db, sources.TWSE_MARGIN_HISTORY_ENDPOINT
        )
        assert tpex.margin_raw_payload_id == margin_capture(
            db, sources.TPEX_MARGIN_HISTORY_ENDPOINT
        )
        assert twse.margin_source == "twse_margin"
        assert tpex.margin_source == "tpex_margin"


def test_collect_leaves_a_dash_short_balance_empty_not_zero(database):
    result = collect(Fetcher(twse_short="--", tpex_short=""))
    assert result["status"] == "success", result
    with database() as db:
        assert chip(db, "1101").short_balance is None
        assert chip(db, "1101").margin_balance == 11242
        assert chip(db, "7001").short_balance is None
        assert chip(db, "7001").margin_balance == 110


def test_a_later_capture_does_not_fill_the_short_balance_of_another_captures_row(
    database,
):
    # Review 6840422442 (3): the row's margin group stays on capture A, so a
    # later capture B must not give it B's short balance.
    collect(Fetcher(twse_short="--"))
    with database() as db:
        db.execute(update(IngestionRun).values(status="partial"))
        db.commit()
        group = groups_of.explicit_groups(chip(db, "1101"))[groups_of.MARGIN]
    collect(Fetcher(twse_short="88"))
    with database() as db:
        row = chip(db, "1101")
        assert row.margin_raw_payload_id != margin_capture_latest(
            db, sources.TWSE_MARGIN_HISTORY_ENDPOINT
        )
        assert row.short_balance is None
        assert groups_of.explicit_groups(row)[groups_of.MARGIN] == group
        # chips short-balance reads A, which has no value: skipped, partial.
        result = chip_revisions.fill_short_balance(db, apply=True)
    assert result["status"] == "partial"
    assert result["rows_no_short_value"] == 1
    assert result["rows_skipped"] == 1


def test_a_forced_collect_writes_the_short_balance_with_its_own_capture(database):
    collect(Fetcher(twse_short="--"))
    pipeline.collect(
        DAY,
        adapter=sources.OfficialMarketDataAdapter(
            sources.TwseAdapter(Fetcher(twse_short="88")),
            sources.TpexAdapter(Fetcher(twse_short="88")),
        ),
        force=True,
    )
    with database() as db:
        row = chip(db, "1101")
        assert row.short_balance == 88
        assert row.margin_raw_payload_id == margin_capture_latest(
            db, sources.TWSE_MARGIN_HISTORY_ENDPOINT
        )


def margin_capture_latest(db, endpoint):
    return db.scalar(
        select(RawPayload.id)
        .where(RawPayload.endpoint.like(f"{endpoint}%"))
        .order_by(RawPayload.id.desc())
    )


# ---- chips provenance: rows written before #662 still match ------------------


def test_an_empty_short_balance_does_not_make_a_margin_capture_unequal():
    row = ChipSnapshot(margin_balance=15060, margin_change=-1345, short_balance=None)
    (record,) = sources.parse_twse_margin_rows(
        twse_payload(twse_row("00400A")), trading_date=DAY
    )
    assert record.short_balance == 7
    assert chip_provenance._equal(row, record, groups_of.MARGIN)
    row.short_balance = 7
    assert chip_provenance._equal(row, record, groups_of.MARGIN)
    row.short_balance = 8
    assert not chip_provenance._equal(row, record, groups_of.MARGIN)


# ---- AC-3: chips short-balance -----------------------------------------------

OTHER_COLUMNS = [
    column.name
    for column in ChipSnapshot.__table__.columns
    if column.name != "short_balance"
]


def snapshot(db):
    return {
        row.id: {name: getattr(row, name) for name in OTHER_COLUMNS}
        for row in db.scalars(select(ChipSnapshot))
    }


@pytest.fixture
def before_662(database):
    """A collected day whose rows were written without the short balance."""

    assert collect(Fetcher())["status"] == "success"
    with database() as db:
        db.execute(update(ChipSnapshot).values(short_balance=None))
        db.commit()
        return snapshot(db)


def db_file(database):
    return database.kw["bind"].url.database


def test_short_balance_fill_dry_run_writes_nothing(database, before_662, monkeypatch):
    # Review 6840422442 (1): the dry run takes no write lock, so another
    # connection writes while it reads each capture.
    load = chip_revisions._load
    writes = []

    def load_and_write(capture):
        other = sqlite3.connect(db_file(database), timeout=0)
        try:
            other.execute("update instruments set name = name || '' where id = 1")
            other.commit()
            writes.append(capture.id)
        finally:
            other.close()
        return load(capture)

    monkeypatch.setattr(chip_revisions, "_load", load_and_write)
    with database() as db:
        result = chip_revisions.fill_short_balance(db)
    assert len(writes) == 2
    assert result["status"] == "success", result
    assert result["applied"] is False
    assert result["rows_filled"] == 2
    assert result["rows_skipped"] == 0
    with database() as db:
        assert chip(db, "1101").short_balance is None
        assert (
            db.scalar(
                select(IngestionRun).where(
                    IngestionRun.run_type == chip_revisions.SHORT_BALANCE_RUN_TYPE
                )
            )
            is None
        )


def test_short_balance_fill_writes_only_the_short_balance(database, before_662):
    with database() as db:
        result = chip_revisions.fill_short_balance(db, apply=True)
    assert result["status"] == "success", result
    assert (result["rows_filled"], result["captures"], result["filled_dates"]) == (
        2,
        2,
        1,
    )
    with database() as db:
        assert chip(db, "1101").short_balance == 88
        assert chip(db, "7001").short_balance == 45
        assert snapshot(db) == before_662
        run = db.scalar(
            select(IngestionRun).where(
                IngestionRun.run_type == chip_revisions.SHORT_BALANCE_RUN_TYPE
            )
        )
        assert run.status == "success"
        assert run.records == 2
        assert run.metadata_json["rows_filled"] == 2
    with database() as db:
        again = chip_revisions.fill_short_balance(db, apply=True)
    assert (again["rows_filled"], again["captures"]) == (0, 0)


def test_short_balance_fill_skips_a_row_its_capture_disagrees_with(
    database, before_662
):
    with database() as db:
        row = chip(db, "1101")
        row.margin_balance = 1
        db.commit()
        result = chip_revisions.fill_short_balance(db, apply=True)
    assert result["status"] == "partial"
    assert result["rows_margin_mismatch"] == 1
    assert result["rows_filled"] == 1
    assert result["skipped_samples"][0]["symbol"] == "1101"
    with database() as db:
        assert chip(db, "1101").short_balance is None
        assert chip(db, "7001").short_balance == 45


def test_short_balance_fill_lists_an_unreadable_capture_as_partial(
    database, before_662
):
    with database() as db:
        capture = db.get(
            RawPayload, margin_capture(db, sources.TPEX_MARGIN_HISTORY_ENDPOINT)
        )
    # The file no longer matches its SHA-256.
    payload_file(capture.payload_path).write_text(
        json.dumps({"changed": True}), encoding="utf-8"
    )
    with database() as db:
        result = chip_revisions.fill_short_balance(db, apply=True)
    assert result["status"] == "partial"
    assert [item["raw_payload_id"] for item in result["unreadable_captures"]] == [
        capture.id
    ]
    assert result["rows_capture_skipped"] == 1
    assert result["rows_filled"] == 1
    with database() as db:
        assert chip(db, "7001").short_balance is None
        assert chip(db, "1101").short_balance == 88


def test_short_balance_fill_lists_a_missing_raw_row_as_partial(database, before_662):
    # Review 6840422442 (6): a cited raw_payloads row that is gone.
    with database() as db:
        raw_id = margin_capture(db, sources.TPEX_MARGIN_HISTORY_ENDPOINT)
    plain = sqlite3.connect(db_file(database))  # foreign keys off
    plain.execute("delete from raw_payloads where id = ?", (raw_id,))
    plain.commit()
    plain.close()
    with database() as db:
        result = chip_revisions.fill_short_balance(db, apply=True)
    assert result["status"] == "partial"
    assert result["unreadable_captures"] == [
        {"raw_payload_id": raw_id, "error": "raw_payloads row not found"}
    ]
    assert (result["rows_capture_skipped"], result["rows_filled"]) == (1, 1)
    with database() as db:
        assert chip(db, "1101").short_balance == 88
        assert chip(db, "7001").short_balance is None


@pytest.mark.parametrize(
    ("taipei", "inside"),
    [((21, 24), False), ((21, 25), True), ((23, 29), True), ((23, 30), False)],
)
def test_the_fill_stop_window_is_21_25_to_23_30_taipei(taipei, inside):
    moment = datetime(2026, 11, 13, *taipei, tzinfo=pipeline.TAIPEI)
    naive_utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    assert chip_revisions.in_short_balance_stop_window(naive_utc) is inside


def test_the_apply_stops_before_a_capture_once_21_25_comes(database, before_662):
    # Review 6840422442 (2): the first capture is written at 21:24, the
    # second is left for a rerun.
    times = iter(
        [
            datetime(2026, 11, 13, 13, 24),
            datetime(2026, 11, 13, 13, 25),
            datetime(2026, 11, 13, 13, 25),
        ]
    )
    with database() as db:
        result = chip_revisions.fill_short_balance(
            db, apply=True, clock=lambda: next(times)
        )
    assert result["status"] == "partial"
    assert result["stopped_at"] == "2026-11-13T13:25:00"
    assert result["rows_filled"] == 1
    with database() as db:
        again = chip_revisions.fill_short_balance(db, apply=True)
    assert (again["status"], again["rows_filled"]) == ("success", 1)


def test_a_fill_of_only_the_short_balance_names_no_margin_capture(database):
    # Review 6840422442 (4).
    with database() as db:
        run = IngestionRun(
            run_type="collect",
            source="official",
            run_date=DAY,
            status="success",
            records=0,
            metadata_json={},
            started_at=NOW,
            finished_at=NOW,
        )
        db.add(run)
        db.flush()
        raw = RawPayload(
            source="twse",
            endpoint=sources.TWSE_MARGIN_HISTORY_ENDPOINT,
            data_as_of=DAY.isoformat(),
            payload_path="x.json",
            sha256="0" * 64,
            ingestion_run_id=run.id,
            collected_at=NOW,
        )
        db.add(raw)
        db.flush()

        def fill(fields, symbol):
            return {
                "table": "chip_snapshots",
                "exchange": "TWSE",
                "trading_date": DAY.isoformat(),
                "symbols": [symbol],
                "fields": fields,
                "raw_payload_id": raw.id,
            }

        run.metadata_json = {
            "value_fill_groups": [
                fill(["short_balance"], "1101"),
                fill(["margin_balance", "short_balance"], "2330"),
            ]
        }
        db.flush()
        runs = chip_provenance._fill_runs(db)
    assert ("TWSE", DAY.isoformat(), "1101") not in runs
    assert runs[("TWSE", DAY.isoformat(), "2330")] == [run.id]


def test_short_balance_fill_keeps_to_its_dates(database, before_662):
    with database() as db:
        result = chip_revisions.fill_short_balance(
            db, date(2026, 9, 5), date(2026, 9, 30), apply=True
        )
    assert (result["rows_filled"], result["captures"]) == (0, 0)


# ---- CLI: maintenance mode and the daily window ------------------------------


def test_the_apply_holds_maintenance_mode_and_the_dry_run_does_not():
    parser_args = cli.argparse.Namespace(
        command="chips", chips_command="short-balance", apply=True
    )
    assert cli.maintenance_guarded(parser_args) == "chips short-balance --apply"
    parser_args.apply = False
    assert cli.maintenance_guarded(parser_args) is None


@pytest.mark.parametrize(
    ("taipei", "inside"),
    [
        ((21, 14), False),
        ((21, 15), True),
        ((21, 30), True),
        ((23, 29), True),
        ((23, 30), False),
        ((4, 0), False),
    ],
)
def test_the_start_is_refused_from_21_15_to_23_30_taipei(taipei, inside):
    hour, minute = taipei
    moment = datetime(2026, 11, 13, hour, minute, tzinfo=pipeline.TAIPEI)
    assert cli.in_daily_window(moment.astimezone(timezone.utc)) is inside


def test_the_apply_is_refused_in_the_daily_window(monkeypatch, capsys):
    monkeypatch.setattr(cli, "in_daily_window", lambda: True)
    called = []
    monkeypatch.setattr(cli, "run_command", lambda *args: called.append(args))
    monkeypatch.setattr(
        cli.sys, "argv", ["worker.cli", "chips", "short-balance", "--apply"]
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == cli.scheduled_job.MAINTENANCE_REFUSED_EXIT
    assert called == []
    assert "21:15" in capsys.readouterr().err
