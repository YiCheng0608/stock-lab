"""The stock page says why a strategy judgement is short of data (#511).

``data_insufficient`` used to come with field names only (``bars_60d``,
``foreign_buy`` …), so the page said 「研究資料待補」 and, for a field the
front end did not know, 「待補資料」.  The summary now carries
``gap_reasons``: one code and sentence per cause, from facts it already
reads (official no-trade days, the listing date, suspensions, the quote and
chip tables).  Which stocks are ``data_insufficient`` does not change: the
60-session counts the readiness reads are asserted unchanged below.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.decision import build_decision_summary
from app.gap_reasons import (
    chip_gap_reasons,
    coverage_gap_reasons,
    data_gap_reasons,
)
from app.migrations import upgrade_database
from app.models import (
    Event,
    IngestionRun,
    Instrument,
    MarketBar,
    NoTradeDay,
    RawPayload,
)

AS_OF = date(2026, 10, 22)
# 60 verified sessions, newest first (weekends included: only TAIEX rows count).
SESSIONS = [AS_OF - timedelta(days=index) for index in range(60)]
GAP_DAY = SESSIONS[10]


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gaps.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with make() as session:
        session.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=AS_OF,
                status="success",
                records=1,
                data_as_of=AS_OF.isoformat(),
                request_key="gaps-fixture",
            )
        )
        taiex = _instrument(session, "TAIEX", kind="index")
        _bars(session, taiex, SESSIONS)
        session.commit()
        yield session
    engine.dispose()


def _instrument(db, symbol, *, kind="stock", listing_date=None, exchange="TWSE"):
    row = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
        status="active",
        listing_date=listing_date,
    )
    db.add(row)
    db.flush()
    return row


def _bars(db, instrument, days):
    for day in days:
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=10,
                high=10,
                low=10,
                close=10,
                adj_close=10,
                volume=1000,
                turnover=10000,
                source="official-fixture",
            )
        )


def _no_trade(db, instrument, day):
    raw = RawPayload(source="twse", endpoint="MI_INDEX", data_as_of=day.isoformat())
    db.add(raw)
    db.flush()
    db.add(
        NoTradeDay(
            instrument_id=instrument.id,
            trading_date=day,
            source="twse",
            endpoint="MI_INDEX",
            data_as_of=day.isoformat(),
            collected_at=datetime(2026, 10, 22, 10),
            raw_payload_id=raw.id,
        )
    )


def _summary(db, instrument):
    db.commit()
    db.info.clear()
    return build_decision_summary(db, instrument, AS_OF)


def _codes(summary):
    return [item["code"] for item in summary.get("gap_reasons") or []]


def _bar_reasons(summary):
    # The fixture has no chip rows; those reasons are another test's.
    return [
        item
        for item in summary["coverage"]["coverage_reasons"]
        if item != "missing_chips"
    ]


def test_an_official_no_trade_day_is_named_not_left_as_a_gap(db):
    full = _instrument(db, "FULL")
    _bars(db, full, SESSIONS)
    stock = _instrument(db, "THIN")
    _bars(db, stock, [day for day in SESSIONS if day != GAP_DAY])
    _no_trade(db, stock, GAP_DAY)

    summary = _summary(db, stock)

    coverage = summary["coverage"]
    # The readiness is unchanged: a no-trade day is still no bar.
    assert coverage["missing_bars_to_60"] == 1
    assert summary["action_state"] == "data_insufficient"
    assert "official_no_trade" in coverage["coverage_reasons"]
    assert "missing_bar_dates" not in coverage["coverage_reasons"]
    assert coverage["no_trade_dates_to_60"] == [GAP_DAY.isoformat()]
    assert _codes(summary)[0] == "official_no_trade"
    assert summary["gap_reasons"][0]["label"] == "近 60 個交易日有 1 天官方行情無成交"
    # The card's main reason is the cause, not a machine field name.
    assert summary["primary_reason"]["label"] == summary["gap_reasons"][0]["label"]


def test_a_day_the_quote_table_left_the_stock_out_is_not_called_uncollected(db):
    full = _instrument(db, "FULL")
    _bars(db, full, SESSIONS)
    stock = _instrument(db, "GAPPY")
    _bars(db, stock, [day for day in SESSIONS if day != GAP_DAY])

    summary = _summary(db, stock)

    assert _bar_reasons(summary) == ["quote_not_listed"]
    assert summary["coverage"]["quote_not_listed_dates_to_60"] == [GAP_DAY.isoformat()]
    assert _codes(summary) == ["quote_not_listed"]
    assert summary["gap_reasons"][0]["label"].startswith(
        "近 60 個交易日有 1 天官方行情表未列此股"
    )


def test_a_session_no_stock_of_the_exchange_has_is_uncollected(db):
    full = _instrument(db, "FULL")
    _bars(db, full, [day for day in SESSIONS if day != GAP_DAY])
    stock = _instrument(db, "GAPPY")
    _bars(db, stock, [day for day in SESSIONS if day != GAP_DAY])

    summary = _summary(db, stock)

    assert _bar_reasons(summary) == ["missing_bar_dates"]
    assert summary["gap_reasons"] == [
        {
            "code": "missing_bar_dates",
            "label": "近 60 個交易日有 1 天行情尚未收錄（待回補）",
        }
    ]


def test_a_stock_listed_inside_the_window_says_so_whatever_its_type(db):
    full = _instrument(db, "FULL")
    _bars(db, full, SESSIONS)
    listed = SESSIONS[29]
    stock = _instrument(db, "NEW", kind="stock", listing_date=listed)
    _bars(db, stock, SESSIONS[:30])

    summary = _summary(db, stock)

    assert summary["coverage"]["missing_bars_to_60"] == 30
    assert _bar_reasons(summary) == ["listed_under_threshold"]
    assert summary["gap_reasons"][0] == {
        "code": "listed_under_threshold",
        "label": "上市（櫃）後只有 30 個交易日，未滿 60 個交易日",
    }


def test_a_suspension_covers_the_sessions_until_its_resumption(db):
    full = _instrument(db, "FULL")
    _bars(db, full, SESSIONS)
    stock = _instrument(db, "HALT")
    halted = SESSIONS[20:23]  # three sessions, newest first
    _bars(db, stock, [day for day in SESSIONS if day not in halted])
    for day, kind in ((halted[-1], "suspension"), (SESSIONS[19], "resumption")):
        db.add(
            Event(
                instrument_id=stock.id,
                event_date=day,
                event_type=kind,
                title=kind,
                source="twse",
                details_json={},
            )
        )

    summary = _summary(db, stock)

    assert _bar_reasons(summary) == ["suspended_or_no_trade"]
    assert summary["coverage"]["suspended_dates_to_60"] == sorted(
        day.isoformat() for day in halted
    )
    assert summary["gap_reasons"][0]["label"] == "近 60 個交易日有 3 天停牌"


def test_a_complete_stock_has_no_gap_reasons(db):
    stock = _instrument(db, "FULL")
    _bars(db, stock, SESSIONS)

    summary = _summary(db, stock)

    assert _bar_reasons(summary) == []
    assert summary["coverage"]["missing_bars_to_60"] == 0
    # The fixture has no chips or signals, so the summary is still short of
    # data, but no bar reason may appear for a stock with every session.
    assert coverage_gap_reasons(summary["coverage"]) == []
    bar_codes = {
        "listed_under_threshold",
        "suspended_or_no_trade",
        "official_no_trade",
        "bar_invalid",
        "quote_not_listed",
        "missing_bar_dates",
    }
    assert not bar_codes & set(_codes(summary))


def test_a_stored_bar_with_unusable_values_is_not_called_unlisted(db):
    # Review of PR 514: the official table listed the stock that day; the
    # stored bar is just not usable (core_valid false).
    full = _instrument(db, "FULL")
    _bars(db, full, SESSIONS)
    stock = _instrument(db, "BAD")
    _bars(db, stock, [day for day in SESSIONS if day != GAP_DAY])
    db.add(
        MarketBar(
            instrument_id=stock.id,
            trading_date=GAP_DAY,
            open=10,
            high=10,
            low=10,
            close=0,
            adj_close=0,
            volume=1000,
            turnover=10000,
            source="official-fixture",
        )
    )

    summary = _summary(db, stock)

    assert summary["coverage"]["missing_bars_to_60"] == 1
    assert _bar_reasons(summary) == ["bar_invalid"]
    assert summary["coverage"]["invalid_bar_dates_to_60"] == [GAP_DAY.isoformat()]
    assert summary["coverage"]["quote_not_listed_dates_to_60"] == []
    assert summary["gap_reasons"][0] == {
        "code": "bar_invalid",
        "label": "近 60 個交易日有 1 天已收到行情但數值不完整（開高低收或來源無法使用）",
    }


def test_a_resumption_and_a_suspension_on_one_day(db):
    # The earlier suspension ends on the day, the new one starts on it.
    full = _instrument(db, "FULL")
    _bars(db, full, SESSIONS)
    stock = _instrument(db, "TWICE")
    first, day, last = SESSIONS[25], SESSIONS[24], SESSIONS[22]
    halted = {first, day, SESSIONS[23]}
    _bars(db, stock, [item for item in SESSIONS if item not in halted])
    for when, kind in (
        (first, "suspension"),
        (day, "suspension"),
        (day, "resumption"),
        (last, "resumption"),
    ):
        db.add(
            Event(
                instrument_id=stock.id,
                event_date=when,
                event_type=kind,
                title=kind,
                source="tpex",
                details_json={},
            )
        )

    summary = _summary(db, stock)

    assert summary["coverage"]["suspended_dates_to_60"] == sorted(
        item.isoformat() for item in halted
    )


def _chip(day, *, institutional=True, margin=True):
    value = 1.0
    return SimpleNamespace(
        trading_date=day,
        foreign_buy=value if institutional else None,
        trust_buy=value if institutional else None,
        dealer_buy=value if institutional else None,
        margin_balance=value if margin else None,
        margin_change=value if margin else None,
    )


def test_chip_days_off_the_official_tables_are_counted():
    days = sorted(SESSIONS[:6])
    rows = [_chip(day, institutional=day != days[-1]) for day in days]

    reasons = chip_gap_reasons(
        ["foreign_buy", "trust_buy"], rows, days, chip_collected=lambda *_: True
    )

    assert reasons == [
        {
            "code": "institutional_not_listed",
            "label": "近 5 個交易日有 1 天官方三大法人表未列此股（官方只列當天有法人買賣的股票）",
        }
    ]
    # A signal whose input is missing asks for the check even when the
    # summary's own chip blocker read old rows as complete.
    margin = chip_gap_reasons(
        [],
        [_chip(day) for day in days[1:]],
        days,
        ["margin_balance_change_ratio_5d_missing_or_non_finite"],
        chip_collected=lambda *_: True,
    )
    assert margin == [
        {
            "code": "margin_not_listed",
            "label": "近 6 個交易日有 1 天官方融資餘額表未列此股",
        }
    ]


def test_a_chip_day_no_stock_of_the_exchange_has_is_not_collected():
    # Review of PR 514: when the whole exchange has no institutional (or
    # margin) values on a day, the table was not collected; a backfill can
    # fill it, so it is not 「官方未列此股」.
    days = sorted(SESSIONS[:6])
    missing_day = days[-1]
    rows = [_chip(day) for day in days[:-1]]

    def collected(day, group):
        return day != missing_day

    reasons = chip_gap_reasons(
        ["foreign_buy", "margin_balance"], rows, days, chip_collected=collected
    )

    assert reasons == [
        {
            "code": "institutional_not_collected",
            "label": "近 5 個交易日有 1 天法人資料尚未收錄（待回補）",
        },
        {
            "code": "margin_not_collected",
            "label": "近 6 個交易日有 1 天融資資料尚未收錄（待回補）",
        },
    ]
    # One stock left out on a collected day, another day not collected.
    rows = [_chip(day, institutional=day != days[-2]) for day in days[:-1]]
    mixed = chip_gap_reasons(["foreign_buy"], rows, days, chip_collected=collected)
    assert [item["code"] for item in mixed] == [
        "institutional_not_listed",
        "institutional_not_collected",
    ]


def test_the_exchange_chip_check_reads_the_day_of_that_exchange(db):
    from app.decision import _exchange_has_chips
    from app.models import ChipSnapshot

    twse = _instrument(db, "LISTED")
    tpex = _instrument(db, "OTC", exchange="TPEx")
    db.add(ChipSnapshot(instrument_id=twse.id, trading_date=GAP_DAY, foreign_buy=1.0))
    db.add(
        ChipSnapshot(instrument_id=tpex.id, trading_date=GAP_DAY, margin_balance=5.0)
    )
    db.commit()
    db.info.clear()

    assert _exchange_has_chips(db, "TWSE", GAP_DAY, "institutional") is True
    assert _exchange_has_chips(db, "TWSE", GAP_DAY, "margin") is False
    assert _exchange_has_chips(db, "TPEx", GAP_DAY, "institutional") is False
    assert _exchange_has_chips(db, "TPEx", GAP_DAY, "margin") is True
    assert _exchange_has_chips(db, "TWSE", SESSIONS[0], "institutional") is False


def _incomplete(*codes):
    return {
        "breakout_v3": {
            "status": "data_incomplete",
            "evidence": {
                "breakout": {"state": "data_incomplete", "reasons": list(codes)}
            },
        }
    }


def test_structural_reasons_for_etfs_groups_and_new_listings():
    verified = {"coverage_status": "verified", "coverage_reasons": []}
    etf = data_gap_reasons(
        coverage={**verified, "coverage_reasons": ["etf_not_general_action_eligible"]},
        missing=["signal_data_quality", "data_incomplete"],
        chip_rows=[],
        sessions=[],
        strategy_results=_incomplete(
            "etf_category_excluded_from_actionable_signals:bond"
        ),
    )
    assert [item["code"] for item in etf] == ["etf_not_general_action_eligible"]
    assert etf[0]["label"] == "債券、槓桿或反向 ETF 不適用一般突破／回踩研究條件"

    group = data_gap_reasons(
        coverage=verified,
        missing=["data_incomplete"],
        chip_rows=[],
        sessions=[],
        strategy_results=_incomplete("group_excess_return_20d_missing_or_non_finite"),
        group_missing=["theme_membership"],
    )
    assert group == [
        {
            "code": "group_return_unavailable",
            "label": "未歸屬任何有效族群，無法計算族群相對加權指數的 20 日報酬",
        }
    ]

    young = data_gap_reasons(
        coverage={
            "coverage_status": "verified",
            "coverage_reasons": ["listed_under_threshold"],
            "eligible_sessions": 8,
            "missing_bars_to_20": 12,
            "missing_bars_to_60": 52,
        },
        missing=["bars_20d", "bars_60d"],
        chip_rows=[],
        sessions=[],
        strategy_results=_incomplete(
            "ipo_history_under_20_bars",
            "group_excess_return_20d_missing_or_non_finite",
            "institutional_flow_to_turnover_ratio_5d_missing_or_non_finite",
        ),
    )
    # The listing explains every input that needs 20 sessions.
    assert [item["code"] for item in young] == ["listed_under_threshold"]


def test_every_reason_is_a_sentence_never_a_pending_placeholder():
    coverage = {
        "coverage_status": "verified",
        "coverage_reasons": [
            "official_no_trade",
            "quote_not_listed",
            "missing_bar_dates",
            "suspended_or_no_trade",
        ],
        "missing_bars_to_60": 4,
        "missing_bar_dates_to_60": [
            "2026-10-01",
            "2026-10-02",
            "2026-10-03",
            "2026-10-04",
        ],
        "no_trade_dates_to_60": ["2026-10-01"],
        "quote_not_listed_dates_to_60": ["2026-10-02"],
        "suspended_dates_to_60": ["2026-10-03"],
    }
    reasons = coverage_gap_reasons(coverage)
    assert [item["code"] for item in reasons] == [
        "suspended_or_no_trade",
        "official_no_trade",
        "quote_not_listed",
        "missing_bar_dates",
    ]
    assert reasons[-1]["label"] == "近 60 個交易日有 1 天行情尚未收錄（待回補）"
    assert not any("待補" in item["label"] for item in reasons)
    assert coverage_gap_reasons({"coverage_status": "unknown"})[0]["code"] == (
        "coverage_baseline_unknown"
    )


def test_a_day_is_counted_under_one_cause_only():
    # A suspended day the quote table also lists without prices (3587 閎康,
    # 2026-07-31 on the production copy) is a suspension, not also a no-trade day.
    reasons = coverage_gap_reasons(
        {
            "coverage_status": "verified",
            "coverage_reasons": ["suspended_or_no_trade", "official_no_trade"],
            "missing_bars_to_60": 2,
            "missing_bar_dates_to_60": ["2026-07-31", "2026-08-05"],
            "suspended_dates_to_60": ["2026-07-31"],
            "no_trade_dates_to_60": ["2026-07-31", "2026-08-05"],
        }
    )
    assert [item["label"] for item in reasons] == [
        "近 60 個交易日有 1 天停牌",
        "近 60 個交易日有 1 天官方行情無成交",
    ]
