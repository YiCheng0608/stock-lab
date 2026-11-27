"""Foreign issuers' own Q2 filing deadline (#1101).

公開發行公司財務報告及營運情形公告申報特殊適用範圍辦法 第3條第3款: from the
2021 fiscal year a 第一上市（櫃）公司 files Q2 within two months (8/31), not
45 days.  The page fixtures are #529's 115Q2 pages; which company is foreign
comes from the stored markers the tests add.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
import test_quarterly_fundamentals as base
from sqlalchemy import select
from test_quarterly_fundamentals import (
    backfill,
    rows_by_symbol,
    snapshot,
    store_calendar,
)

from app.models import (
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    MonthlyRevenue,
    RawPayload,
)
from worker import foreign_issuers as fi
from worker import monthly_revenue as mr
from worker import monthly_revenue_company as mrc
from worker import pipeline
from worker import quarterly_fundamentals as qf

Q = qf.Quarter
# #529's fixtures: the database with the page's companies, no network, NOW.
factory = base.factory
isolated = base.isolated


def instrument(db, exchange, symbol):
    return db.scalar(
        select(Instrument).where(
            Instrument.exchange == exchange, Instrument.symbol == symbol
        )
    )


def add_revenue(db, item, source, details, month=date(2026, 6, 1)):
    raw = RawPayload(source="mops", endpoint="fixture", data_as_of="2026-06-30")
    db.add(raw)
    db.flush()
    db.add(
        MonthlyRevenue(
            instrument_id=item.id,
            revenue_month=month,
            revenue=1.0,
            announcement_date=date(2026, 7, 10),
            source=source,
            raw_payload_id=raw.id,
            data_json=details,
            data_as_of=month.isoformat(),
        )
    )


def mark_foreign_page(db, exchange, symbol):
    """The MOPS t21sc03 foreign-company page (``_1``) lists the company."""

    add_revenue(db, instrument(db, exchange, symbol), mr.SOURCE, {"page": 1})


# --- the rule -----------------------------------------------------------------------


def test_a_foreign_issuers_q2_is_due_two_months_after_the_half_year_from_2021():
    assert qf.nominal_deadline("general", Q(2021, 2), foreign=True) == date(2021, 8, 31)
    assert qf.nominal_deadline("general", Q(2026, 2), foreign=True) == date(2026, 8, 31)
    # Before the 110 fiscal year it was the general 8/14.
    assert qf.nominal_deadline("general", Q(2020, 2), foreign=True) == date(2020, 8, 14)
    # Q1, Q3 and the annual report are a domestic company's.
    assert qf.nominal_deadline("general", Q(2024, 1), foreign=True) == date(2024, 5, 15)
    assert qf.nominal_deadline("general", Q(2024, 3), foreign=True) == date(
        2024, 11, 14
    )
    assert qf.nominal_deadline("general", Q(2024, 4), foreign=True) == date(2025, 3, 31)
    # A format due later keeps its own (financial holding 11/29).
    assert qf.nominal_deadline("holding", Q(2024, 3), foreign=True) == date(
        2024, 11, 29
    )
    assert qf.nominal_deadline("holding", Q(2024, 2), foreign=True) == date(2024, 8, 31)
    # A domestic company is unchanged.
    assert qf.nominal_deadline("general", Q(2024, 2)) == date(2024, 8, 14)


def test_the_foreign_deadline_moves_off_a_closed_day(factory):
    with factory() as db:
        store_calendar(db, [2025])
        # 2025-08-31 is a Sunday.
        assert qf.roll_to_session(
            db, qf.nominal_deadline("general", Q(2025, 2), foreign=True)
        ) == (date(2025, 9, 1), "twse_holiday_schedule")


def test_the_rule_keys_are_written_only_where_the_rule_applies():
    assert qf.deadline_details(Q(2026, 2), fi.BASIS_PAGE) == {
        "deadline_rule": qf.FOREIGN_RULE,
        "foreign_issuer_basis": fi.BASIS_PAGE,
    }
    assert qf.deadline_details(Q(2026, 1), fi.BASIS_PAGE) == {}
    assert qf.deadline_details(Q(2020, 2), fi.BASIS_PAGE) == {}
    assert qf.deadline_details(Q(2026, 2), None) == {}


# --- who is foreign -------------------------------------------------------------------


def test_the_monthly_modules_names_are_the_ones_read():
    assert fi.PAGE_SOURCE == mr.SOURCE
    assert fi.COMPANY_SOURCE == mrc.SOURCE_COMPANY
    assert fi.COMPANY_RUN_TYPES == (mrc.RUN_CLASSIFY, mrc.RUN_BACKFILL)
    assert fi.FOREIGN_EXEMPT == mrc.FOREIGN_EXEMPT


@pytest.mark.parametrize(
    ("name", "foreign"),
    [
        ("鼎炫-KY", True),
        ("錼創科技-KY創", True),
        ("F-晨星", True),
        ("英瑞－ＫＹ", True),  # full width, NFKC
        ("台積電", False),
        ("KY科技", False),
        ("F 公司", False),
    ],
)
def test_the_name_rule(name, foreign):
    assert fi.name_marks_foreign(name) is foreign


def test_official_markers_come_first_and_the_name_only_fills_the_rest(factory):
    with factory() as db:
        for exchange, symbol, name in (
            ("TWSE", "8499", "鼎炫-KY"),  # the _1 page
            ("TPEx", "1258", "其祥-KY"),  # 免申報 single-company page
            ("TWSE", "1592", "英瑞-KY"),  # dual-currency layout
            ("TWSE", "6854", "錼創科技-KY創"),  # the _1 page, no -KY suffix
            ("TWSE", "8427", "基勝-KY"),  # no marker: the name
            ("TWSE", "9999", "國內"),  # domestic page only
        ):
            db.add(
                Instrument(
                    market="TW",
                    exchange=exchange,
                    symbol=symbol,
                    name=name,
                    instrument_type="stock",
                    status="active",
                )
            )
        db.flush()
        mark_foreign_page(db, "TWSE", "8499")
        mark_foreign_page(db, "TWSE", "6854")
        add_revenue(db, instrument(db, "TWSE", "9999"), mr.SOURCE, {"page": 0})
        add_revenue(
            db,
            instrument(db, "TWSE", "1592"),
            mrc.SOURCE_COMPANY,
            {"幣別": "新台幣", "功能性貨幣": "功能性貨幣(美金)"},
        )
        db.add(
            IngestionRun(
                run_type=mrc.RUN_CLASSIFY,
                source="official",
                run_date=date(2026, 11, 19),
                metadata_json={
                    "manifest": {
                        "TPEx:1258:2023-05": {"class": "foreign_exempt"},
                        "TPEx:1333:2020-04": {"class": "not_public"},
                    }
                },
            )
        )
        db.commit()
        found = fi.foreign_issuers(db)
        named = {
            (item.exchange, item.symbol): found.get(item.id)
            for item in db.scalars(select(Instrument))
        }
    assert named["TWSE", "8499"] == fi.BASIS_PAGE
    assert named["TWSE", "6854"] == fi.BASIS_PAGE
    assert named["TPEx", "1258"] == fi.BASIS_EXEMPT
    assert named["TWSE", "1592"] == fi.BASIS_CURRENCY
    assert named["TWSE", "8427"] == fi.BASIS_NAME
    assert named["TWSE", "9999"] is None
    assert named["TWSE", "2330"] is None  # the fixture's domestic companies


# --- backfill ---------------------------------------------------------------------------


def test_the_backfill_gives_a_foreign_issuer_its_q2_deadline(factory):
    with factory() as db:
        mark_foreign_page(db, "TPEx", "1240")
        db.commit()
    result = backfill(factory, quarters=2, end=Q(2026, 2))
    assert result["status"] == "success"
    assert result["quarters"]["2026Q2:otc"]["deadlines"] == {
        f"general:{qf.FOREIGN_RULE}": {
            "date": "2026-08-31",
            "calendar": "weekend_only",
        },
        "securities": {"date": "2026-08-31", "calendar": "weekend_only"},
    }
    with factory() as db:
        rows = rows_by_symbol(db)
        q1, q2 = rows["1240"]
        assert q2.announcement_date == date(2026, 8, 31)
        assert q2.data_json["statutory_deadline"] == "2026-08-31"
        assert q2.data_json["deadline_rule"] == qf.FOREIGN_RULE
        assert q2.data_json["foreign_issuer_basis"] == fi.BASIS_PAGE
        # Q1 follows the general deadline and carries no rule keys.
        assert q1.announcement_date == date(2026, 5, 15)
        assert "deadline_rule" not in q1.data_json
        # A domestic company in the same table is unchanged.
        assert rows["2330"][1].announcement_date == date(2026, 8, 14)
        assert "deadline_rule" not in rows["2330"][1].data_json
    again = backfill(factory, quarters=2, end=Q(2026, 2))
    assert again["changed"] == 0


def test_a_rerun_after_the_fix_corrects_a_foreign_issuers_snapshot_row(factory):
    # The snapshot row the old rule dated 8/14 moves to 8/31 with its values.
    with factory() as db:
        instruments = {
            (i.exchange, i.symbol): i for i in db.scalars(select(Instrument))
        }
        pipeline._upsert_fundamental(
            db, snapshot("2330", date(2026, 10, 30), 49.33), instruments, None
        )
        db.commit()
    backfill(factory, quarters=1, end=Q(2026, 2))
    with factory() as db:
        assert rows_by_symbol(db)["2330"][0].announcement_date == date(2026, 8, 14)
        mark_foreign_page(db, "TWSE", "2330")
        db.commit()
    result = backfill(factory, quarters=1, end=Q(2026, 2))
    assert result["dated"] == 1
    with factory() as db:
        (row,) = rows_by_symbol(db)["2330"]
        assert (row.source, row.eps, row.announcement_date) == (
            "mops_fundamental",
            49.33,
            date(2026, 8, 31),
        )
        assert row.data_json["出表日期"] == "1151030"
        assert row.data_json["deadline_rule"] == qf.FOREIGN_RULE


def test_a_snapshot_date_earlier_than_the_foreign_deadline_is_kept(factory):
    # A foreign issuer's own 出表日期 8/29 is earlier than 8/31: first seen wins.
    with factory() as db:
        mark_foreign_page(db, "TWSE", "2330")
        instruments = {
            (i.exchange, i.symbol): i for i in db.scalars(select(Instrument))
        }
        pipeline._upsert_fundamental(
            db, snapshot("2330", date(2026, 8, 29), 49.33), instruments, None
        )
        db.commit()
    result = backfill(factory, quarters=1, end=Q(2026, 2))
    assert result["dated"] == 0
    with factory() as db:
        (row,) = rows_by_symbol(db)["2330"]
        assert row.announcement_date == date(2026, 8, 29)
        assert "deadline_rule" not in row.data_json


# --- recompute ----------------------------------------------------------------------------


def stored_rows(db):
    return {
        (sym, row.period_end): (
            row.announcement_date,
            dict(row.data_json),
            row.raw_payload_id,
        )
        for sym, row in db.execute(
            select(Instrument.symbol, FundamentalSnapshot).join(
                Instrument, Instrument.id == FundamentalSnapshot.instrument_id
            )
        ).all()
    }


def test_recompute_moves_only_foreign_q2_deadline_rows_and_is_idempotent(factory):
    # The old rule's rows: 2025Q1, 2025Q2 and 2026Q3 (first seen) for everyone.
    backfill(factory, quarters=2, end=Q(2025, 2))
    backfill(factory, quarters=1, end=Q(2026, 3))
    with factory() as db:
        store_calendar(db, [2025, 2026])
        before = stored_rows(db)
        assert before["1240", date(2025, 6, 30)][0] == date(2025, 8, 14)
        mark_foreign_page(db, "TPEx", "1240")
        db.commit()

        dry = qf.recompute_foreign_deadlines(db, apply=False)
        assert (dry["changed"], dry["unchanged"]) == (1, 0)
        assert dry["changes"][0]["before"] == "2025-08-14"
        assert dry["changes"][0]["after"] == "2025-09-01"  # 8/31 is a Sunday
        assert dry["groups"] == {
            f"2025Q2:TPEx:{fi.BASIS_PAGE}": {"2025-08-14->2025-09-01": 1}
        }
        assert stored_rows(db) == before
        assert (
            db.scalar(
                select(IngestionRun).where(
                    IngestionRun.run_type == qf.RECOMPUTE_RUN_TYPE
                )
            )
            is None
        )

        done = qf.recompute_foreign_deadlines(db, apply=True)
        assert done["changed"] == 1
        after = stored_rows(db)
        moved = after["1240", date(2025, 6, 30)]
        assert moved[0] == date(2025, 9, 1)
        assert moved[1]["statutory_deadline"] == "2025-09-01"
        assert moved[1]["deadline_calendar"] == "twse_holiday_schedule"
        assert moved[1]["deadline_rule"] == qf.FOREIGN_RULE
        assert moved[1]["foreign_issuer_basis"] == fi.BASIS_PAGE
        # Values and the raw payload stay.
        assert moved[2] == before["1240", date(2025, 6, 30)][2]
        # Every other row is as it was: Q1, the first-seen Q3, other companies.
        assert {k: v for k, v in after.items() if k != ("1240", date(2025, 6, 30))} == {
            k: v for k, v in before.items() if k != ("1240", date(2025, 6, 30))
        }
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == qf.RECOMPUTE_RUN_TYPE)
        )
        assert run.records == 1 and run.status == "success"

        again = qf.recompute_foreign_deadlines(db, apply=True)
        assert (again["changed"], again["unchanged"]) == (0, 1)
        assert stored_rows(db) == after


def test_recompute_leaves_first_seen_rows_and_moves_a_dated_snapshot_row(factory):
    with factory() as db:
        instruments = {
            (i.exchange, i.symbol): i for i in db.scalars(select(Instrument))
        }
        pipeline._upsert_fundamental(
            db, snapshot("2330", date(2026, 10, 30), 49.33), instruments, None
        )
        db.commit()
    backfill(factory, quarters=1, end=Q(2026, 2))
    backfill(factory, quarters=1, end=Q(2026, 3))
    with factory() as db:
        mark_foreign_page(db, "TWSE", "2330")
        q3 = db.scalar(
            select(FundamentalSnapshot).where(
                FundamentalSnapshot.instrument_id == instrument(db, "TWSE", "2330").id,
                FundamentalSnapshot.fiscal_period == "Q3",
            )
        )
        assert q3.data_json["announcement_basis"] == "first_seen"
        q3_before = (q3.announcement_date, dict(q3.data_json))
        db.commit()
        result = qf.recompute_foreign_deadlines(db, apply=True)
        assert (result["changed"], result["not_deadline"]) == (1, 0)
        rows = rows_by_symbol(db)["2330"]
        q2 = rows[0]
        assert (q2.source, q2.eps, q2.announcement_date) == (
            "mops_fundamental",
            49.33,
            date(2026, 8, 31),
        )
        assert (rows[1].announcement_date, rows[1].data_json) == q3_before


def test_recompute_never_dates_a_row_after_the_day_it_was_collected(factory):
    # Collected 8/20, before the 8/31 deadline: available from that day.
    with factory() as db:
        item = instrument(db, "TWSE", "2330")
        db.add(
            FundamentalSnapshot(
                instrument_id=item.id,
                period_end=date(2026, 6, 30),
                fiscal_period="Q2",
                announcement_date=date(2026, 8, 14),
                eps=1.0,
                source=qf.SOURCE,
                data_json={
                    "report_format": "general",
                    "announcement_basis": "statutory_deadline",
                    "statutory_deadline": "2026-08-14",
                    "deadline_calendar": "weekend_only",
                },
                data_as_of="2026-06-30",
                collected_at=datetime(2026, 8, 20, 10, 0) - timedelta(hours=8),
            )
        )
        mark_foreign_page(db, "TWSE", "2330")
        db.commit()
        result = qf.recompute_foreign_deadlines(db, apply=True)
        assert result["changes"][0]["after"] == "2026-08-20"
        assert result["changes"][0]["basis"] == "first_seen"


# --- XBRL archives -----------------------------------------------------------------------


def test_the_xbrl_apply_gives_a_delisted_foreign_issuer_its_q2_deadline(
    factory, tmp_path
):
    from test_quarterly_xbrl import archive, eps_member, store

    from worker import quarterly_xbrl as qx

    quarter = Q(2021, 2)
    with factory() as db:
        for symbol, name in (("8427", "基勝-KY"), ("1234", "國內")):
            item = Instrument(
                market="TW",
                exchange="TWSE",
                symbol=symbol,
                name=name,
                instrument_type="stock",
                status="delisted",
            )
            db.add(item)
            db.flush()
            db.add(
                MarketBar(
                    instrument_id=item.id,
                    trading_date=quarter.period_end + timedelta(days=10),
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    adj_close=10,
                    volume=1000,
                )
            )
        db.commit()
    directory = tmp_path / "xbrl"
    store(
        directory,
        quarter,
        archive(
            dict(
                [
                    eps_member("8427", "1.00", quarter=quarter),
                    eps_member("1234", "2.00", quarter=quarter),
                ]
            )
        ),
    )
    with factory() as db:
        result = qx.apply_archives(db, directory, quarter, quarter)
    assert result["status"] == "success", result
    with factory() as db:
        rows = {
            sym: row
            for sym, row in db.execute(
                select(Instrument.symbol, FundamentalSnapshot).join(
                    Instrument, Instrument.id == FundamentalSnapshot.instrument_id
                )
            ).all()
        }
        assert rows["8427"].announcement_date == date(2021, 8, 31)
        assert rows["8427"].data_json["foreign_issuer_basis"] == fi.BASIS_NAME
        assert rows["1234"].announcement_date == date(2021, 8, 16)  # 8/14 Saturday
        assert "deadline_rule" not in rows["1234"].data_json


def test_the_cli_writes_only_with_apply_and_outside_the_daily_hours():
    import argparse

    from worker.cli import DAILY_WINDOW_REFUSED, maintenance_guarded

    def args(apply):
        return argparse.Namespace(
            command="fundamentals",
            fundamentals_command="foreign-deadlines",
            apply=apply,
        )

    assert maintenance_guarded(args(False)) is None
    assert maintenance_guarded(args(True)) == "fundamentals foreign-deadlines --apply"
    assert "fundamentals foreign-deadlines --apply" in DAILY_WINDOW_REFUSED
