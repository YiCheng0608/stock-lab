"""Words of a data_insufficient stock say what is short (#524, UI_COPY_SPEC §5, §6.1, §9).

Only a gap we did not collect and can backfill says 「待回補」; an official table
without the stock says so; anything else is 「資料不足」.  Labels only: the
states, tiers and ``gap_reasons`` codes are unchanged.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app import decision
from app.api import compact_action_summary
from app.gap_reasons import chip_gap_reasons, coverage_gap_reasons
from app.glossary import glossary_terms
from app.presentation import DISPLAY_ACTION_LABELS, REASON_LABELS, display_reason

DAYS = [date(2026, 11, day) for day in (2, 3, 4, 5, 6)]


def test_the_state_and_tier_say_short_of_data():
    assert DISPLAY_ACTION_LABELS["data_insufficient"] == "資料不足，無法判斷"
    tier = decision.ACTION_TIERS[5]
    assert (tier.tier, tier.key, tier.label) == (5, "data_insufficient", "資料不足")


def test_no_reason_label_says_pending():
    assert not [code for code, label in REASON_LABELS.items() if "待補" in label]
    assert REASON_LABELS["data_incomplete"] == "此研究條件資料不足"
    assert (
        REASON_LABELS["institutional_flow_to_turnover_ratio_5d_missing_or_non_finite"]
        == "近 5 日法人籌碼資料不足"
    )
    assert display_reason("missing=ma60_missing_or_non_finite") == (
        "缺少資料：60 日均線資料不足"
    )
    assert display_reason("group=missing") == "族群條件資料不足"
    assert display_reason("breakout=data_incomplete:ma60_missing_or_non_finite") == (
        "突破研究條件：資料不足（60 日均線資料不足）"
    )


def _row(day: date, **values):
    fields = dict.fromkeys(
        ("foreign_buy", "trust_buy", "dealer_buy", "margin_balance", "margin_change"),
        1.0,
    )
    return SimpleNamespace(trading_date=day, **{**fields, **values})


def test_only_a_gap_we_did_not_collect_says_backfill():
    rows = [_row(day) for day in DAYS[:-1]]
    uncollected = chip_gap_reasons(
        ["foreign_buy"], rows, DAYS, chip_collected=lambda day, group: False
    )
    assert uncollected == [
        {
            "code": "institutional_not_collected",
            "label": "近 5 個交易日有 1 天法人資料尚未收錄（待回補）",
        }
    ]
    listed = chip_gap_reasons(
        ["foreign_buy"], rows, DAYS, chip_collected=lambda day, group: True
    )
    assert [item["code"] for item in listed] == ["institutional_not_listed"]
    assert "待補" not in listed[0]["label"]
    bars = coverage_gap_reasons(
        {
            "coverage_status": "known",
            "missing_bars_to_20": 0,
            "missing_bars_to_60": 2,
            "coverage_reasons": ["missing_bar_dates"],
            "missing_bar_dates_to_60": ["2026-11-03", "2026-11-04"],
        }
    )
    assert bars == [
        {
            "code": "missing_bar_dates",
            "label": "近 60 個交易日有 2 天行情尚未收錄（待回補）",
        }
    ]


def test_the_group_event_gap_keeps_its_name_and_says_why():
    term = next(t for t in glossary_terms() if t["term_id"] == "event_data_pending")
    assert term["name"] == "事件資料待補"
    assert "回補" in term["limitations"]


def test_the_action_list_keeps_the_causes():
    # The list and the dashboard send the compact projection; the watch list names an
    # excluded ETF category and words its note from these (#524).
    reasons = [{"code": "etf_not_general_action_eligible", "label": "ETF 類別不適用"}]
    summary = {"action_state": "data_insufficient", "gap_reasons": reasons}
    assert compact_action_summary(summary)["gap_reasons"] == reasons
