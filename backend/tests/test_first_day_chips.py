"""A backfilled first session also gets its chip row from stored raw (Issue #415).

The 10-28 collect wrote TWSE 7710's 10-27 bar from the stored quote raw
(#388), but not its chip row, although the stored 10-27 T86 (raw 7843) has
7710: foreign investors bought 6,000 shares.  The TPEx institutional file of
10-27 has no 6938 row, so 6938 gets none.  These tests store the day's chip
captures as the 10-27 collects did and check that the backfill writes the row
with each group's own provenance (#395) and never touches it again.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

import worker.instrument_repair as repair
import worker.pipeline as pipeline
import worker.sources as sources
import test_unmatched_backfill as backfill
from app.models import ChipSnapshot, IngestionRun, Instrument
from test_unmatched_backfill import DAY1, _first_session, _quality, _second_session

# The #388 fixture: an upgraded temporary DB and raw directory.
env = backfill.env

DAY1_AS_OF = datetime(2026, 10, 27)
AT_1830 = datetime(2026, 10, 27, 10, 30)
AT_2130 = datetime(2026, 10, 27, 13, 30)
T86_FIELDS = [
    "Code",
    "ForeignBuySellDifferenceExcludingForeignDealer",
    "InvestmentTrustBuySellDifference",
    "DealerBuySellDifference",
]
MARGIN_FIELDS = [
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
]
GROUP_COLUMNS = (
    "institutional_source",
    "institutional_raw_payload_id",
    "institutional_data_as_of",
    "margin_source",
    "margin_raw_payload_id",
    "margin_data_as_of",
)


def _t86(rows):
    return {"stat": "OK", "date": "20261027", "fields": T86_FIELDS, "data": rows}


def _margin(rows):
    return {
        "stat": "OK",
        "date": "20261027",
        "tables": [
            {"fields": ["summary"], "data": [["summary"]]},
            {"fields": MARGIN_FIELDS, "data": rows},
        ],
    }


def _margin_row(code, balance, previous):
    return [code, f"名稱{code}", "1", "0", "0", previous, balance] + ["0"] * 6


def _tpex_chips(rows):
    return {
        "stat": "ok",
        "date": "20261027",
        "tables": [{"fields": [f"f{i}" for i in range(24)], "data": rows}],
    }


def _tpex_margin(rows):
    return {
        "stat": "ok",
        "date": "20261027",
        "tables": [{"fields": [f"m{i}" for i in range(20)], "data": rows}],
    }


def _tpex_row(code):
    return [code, f"名稱{code}"] + ["1"] * 22


def _tpex_margin_row(code):
    return [code, f"名稱{code}", "100", "1", "2", "3", "110"] + ["0"] * 13


T86_URL = (
    f"{sources.TWSE_CHIP_ENDPOINT}?date=20261027&selectType=ALLBUT0999&response=json"
)
MARGIN_URL = (
    f"{sources.TWSE_MARGIN_HISTORY_ENDPOINT}?date=20261027&selectType=ALL&response=json"
)


def _store(env, *captures):
    """Store chip captures of 10-27 as a collect stores its payloads."""

    with env() as db:
        run = db.scalar(select(IngestionRun).order_by(IngestionRun.id))
        ids = [pipeline._upsert_raw_payload(db, run, item).id for item in captures]
        db.commit()
    return ids


def _capture(source, endpoint, payload, when):
    return sources.capture_payload(
        source, endpoint, payload, DAY1.isoformat(), collected_at=when
    )


def _chip(db, exchange, symbol, day=DAY1):
    return db.scalar(
        select(ChipSnapshot)
        .join(Instrument, Instrument.id == ChipSnapshot.instrument_id)
        .where(
            Instrument.exchange == exchange,
            Instrument.symbol == symbol,
            ChipSnapshot.trading_date == day,
        )
    )


def _columns(row):
    return {
        column.name: getattr(row, column.name) for column in ChipSnapshot.__table__.c
    }


def _day_chip_raws(env, *, twse_margin=True):
    """10-27's stored chip files: T86 at 18:30 and its 21:30 revision, MI_MARGN
    and both TPEx files, none of which has 6938."""

    captures = [
        _capture(
            "twse",
            T86_URL,
            _t86([["2330", "1", "1", "1"], ["7710", "5,000", "0", "0"]]),
            AT_1830,
        ),
        _capture(
            "twse",
            T86_URL,
            _t86([["2330", "1", "1", "1"], ["7710", "6,000", "0", "0"]]),
            AT_2130,
        ),
        _capture(
            "tpex",
            sources.TPEX_CHIP_HISTORY_ENDPOINT,
            _tpex_chips([_tpex_row("7001")]),
            AT_1830,
        ),
        _capture(
            "tpex",
            sources.TPEX_MARGIN_HISTORY_ENDPOINT,
            _tpex_margin([_tpex_margin_row("7001")]),
            AT_2130,
        ),
    ]
    if twse_margin:
        captures.append(
            _capture(
                "twse",
                MARGIN_URL,
                _margin(
                    [
                        _margin_row("2330", "100", "90"),
                        _margin_row("7710", "4,321", "0"),
                    ]
                ),
                AT_2130,
            )
        )
    else:
        # MI_MARGN without 7710 (a security that is not a margin security).
        captures.append(
            _capture(
                "twse", MARGIN_URL, _margin([_margin_row("2330", "100", "90")]), AT_2130
            )
        )
    first_t86, latest_t86, _tpex_inst, _tpex_margin_raw, margin = _store(env, *captures)
    return {"first_t86": first_t86, "t86": latest_t86, "margin": margin}


# ---- AC-1: the first session's chip row, each group from its own capture ----


def test_the_first_session_gets_its_chip_row_from_the_days_stored_files(env):
    _first_session()
    raws = _day_chip_raws(env)

    second, _ = _second_session()

    with env() as db:
        row = _chip(db, "TWSE", "7710")
        assert row is not None, "7710 has a 10-27 bar but no chip row"
        # The latest T86 capture of the day (#387), not the 18:30 one.
        assert (row.foreign_buy, row.trust_buy, row.dealer_buy) == (6000, 0, 0)
        assert (row.margin_balance, row.margin_change) == (4321, 4321)
        assert {name: getattr(row, name) for name in GROUP_COLUMNS} == {
            "institutional_source": "twse_t86",
            "institutional_raw_payload_id": raws["t86"],
            "institutional_data_as_of": DAY1_AS_OF,
            "margin_source": "twse_margin",
            "margin_raw_payload_id": raws["margin"],
            "margin_data_as_of": DAY1_AS_OF,
        }
        assert row.institutional_collected_at is not None
        assert row.margin_collected_at is not None
        assert row.source == "twse_t86+twse_margin"
        assert row.raw_payload_id == raws["t86"]
        # 6938 is in neither TPEx file: no row is written.
        assert _chip(db, "TPEx", "6938") is None
        assert _quality(db, "TWSE:7710").checks_json["backfill"]["chips"] == [
            {
                "trading_date": "2026-10-27",
                "status": "written",
                "institutional_raw_payload_id": raws["t86"],
                "margin_raw_payload_id": raws["margin"],
            }
        ]
        assert _quality(db, "TPEx:6938").checks_json["backfill"]["chips"] == [
            {"trading_date": "2026-10-27", "status": "no_row"}
        ]
    backfill = second["unmatched_backfill"]
    assert backfill["status"] == "success"
    assert backfill["chips_written"] == [
        {
            "exchange": "TWSE",
            "symbol": "7710",
            "trading_date": "2026-10-27",
            "status": "written",
            "institutional_raw_payload_id": raws["t86"],
            "margin_raw_payload_id": raws["margin"],
        }
    ]


def test_a_symbol_only_the_institutional_file_has_gets_only_that_group(env):
    _first_session()
    raws = _day_chip_raws(env, twse_margin=False)

    _second_session()

    with env() as db:
        row = _chip(db, "TWSE", "7710")
        assert row is not None, "7710 has a 10-27 bar but no chip row"
        assert row.foreign_buy == 6000
        assert (row.margin_balance, row.margin_change) == (None, None)
        assert (row.institutional_source, row.institutional_raw_payload_id) == (
            "twse_t86",
            raws["t86"],
        )
        assert (row.margin_source, row.margin_raw_payload_id) == (None, None)
        assert row.source == "twse_t86"


def test_without_a_stored_chip_file_nothing_is_written_and_the_date_is_retried(env):
    _first_session()

    second, _ = _second_session()

    backfill = second["unmatched_backfill"]
    assert backfill["chips_written"] == []
    assert {item["symbol"] for item in backfill["chips_pending"]} == {"7710", "6938"}
    with env() as db:
        assert db.scalar(select(func.count(ChipSnapshot.id))) == 0
        assert "chips" not in _quality(db, "TWSE:7710").checks_json["backfill"]
    assert repair.run_unmatched_backfill(apply=True)["status"] == "no_change"

    # The files are stored later: the complete row's date gets its chip row,
    # the state of production 7710 before #415.
    raws = _day_chip_raws(env)
    dry = repair.run_unmatched_backfill()
    assert dry["status"] == "dry_run"
    assert [item["symbol"] for item in dry["chips_written"]] == ["7710"]
    with env() as db:
        assert _chip(db, "TWSE", "7710") is None
    applied = repair.run_unmatched_backfill(apply=True)
    assert applied["status"] == "applied" and applied["rows_checked"] == 0
    assert [
        (item["symbol"], item["institutional_raw_payload_id"])
        for item in applied["chips_written"]
    ] == [("7710", raws["t86"])]
    with env() as db:
        assert _chip(db, "TWSE", "7710").foreign_buy == 6000
        assert _quality(db, "TWSE:7710").status == "complete"


# ---- AC-2: a rerun writes nothing and never changes a stored row ----


def test_a_rerun_writes_no_chip_and_changes_no_row(env):
    _first_session()
    _day_chip_raws(env)
    _second_session()
    with env() as db:
        rows = db.scalar(select(func.count(ChipSnapshot.id)))
        stored = _columns(_chip(db, "TWSE", "7710"))
        checks = _quality(db, "TWSE:7710").checks_json

    again = repair.run_unmatched_backfill(apply=True)

    assert again["status"] == "no_change"
    assert again["chips_written"] == [] and again["chips_checked"] == 0
    with env() as db:
        assert db.scalar(select(func.count(ChipSnapshot.id))) == rows
        assert _columns(_chip(db, "TWSE", "7710")) == stored
        assert _quality(db, "TWSE:7710").checks_json == checks


def test_a_stored_chip_row_is_not_changed(env):
    _first_session()
    _day_chip_raws(env)
    with pytest.MonkeyPatch.context() as patch:
        # 10-28 creates the instrument without the backfill; a chip row of
        # 10-27 is stored before the backfill runs.
        patch.setattr(
            repair,
            "backfill_unmatched_bars",
            lambda db: {"rows_checked": 0, "written": [], "pending": []},
        )
        _second_session()
    with env() as db:
        listing = db.scalar(
            select(Instrument).where(
                Instrument.exchange == "TWSE", Instrument.symbol == "7710"
            )
        )
        db.add(
            ChipSnapshot(
                instrument_id=listing.id,
                trading_date=DAY1,
                foreign_buy=1,
                source="manual",
            )
        )
        db.commit()
        stored = _columns(_chip(db, "TWSE", "7710"))

    result = repair.run_unmatched_backfill(apply=True)

    assert [item["symbol"] for item in result["written"]] == ["6938", "7710"]
    assert result["chips_written"] == []
    with env() as db:
        assert _columns(_chip(db, "TWSE", "7710")) == stored
        assert _quality(db, "TWSE:7710").checks_json["backfill"]["chips"] == [
            {"trading_date": "2026-10-27", "status": "existing"}
        ]
