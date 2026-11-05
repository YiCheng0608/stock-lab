"""Why a stock's strategy judgement is short of data, in one plain line each (#511).

``build_decision_summary`` marks a stock ``data_insufficient`` from its
blockers (``blocking_reasons``: machine field names such as ``bars_60d``).
Those say *what* is short, not *why*, so the stock page used to say only
「研究資料待補」.  This module turns the facts the summary already read into
reason codes with a sentence each (UI_COPY_SPEC §6.1):

* the 60-session bar coverage (``decision._instrument_coverage``): listed
  inside the window, suspended, an official no-trade day (#454), a quote
  table without the stock, or a session not collected yet;
* the last five chip rows: the official institutional and margin tables list
  only the securities with institutional trades / margin positions that day
  (DATA_SOURCES 法人口徑、融資標的清單);
* the strategy signals' own data reasons (``rule_evidence_json``), for what
  the two above do not explain (an excluded ETF category, a missing input).

Only the explanation is added.  Which stocks are ``data_insufficient``, and
every strategy rule, are unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from .presentation import display_reason

CHIP_WINDOW_SESSIONS = 5
MARGIN_WINDOW_SESSIONS = 6
INSTITUTIONAL_FIELDS = ("foreign_buy", "trust_buy", "dealer_buy")
MARGIN_FIELDS = ("margin_balance", "margin_change")
CHIP_BLOCKERS = {"institutional_flow_5d", *INSTITUTIONAL_FIELDS, *MARGIN_FIELDS}

# The topic a signal's data reason is about: a reason whose topic a coverage
# or chip reason already explains is not repeated.
_BAR_REASONS = {
    "history_under_60_bars",
    "ipo_history_under_20_bars",
    "ipo_observation_only_under_60_bars",
    "bar_count_missing_or_invalid",
    "prior_20_highs_missing_or_invalid",
    "prior_20_volumes_missing_or_invalid",
    "close_missing_or_non_finite",
    "volume_missing_or_non_finite",
    "ma20_missing_or_non_finite",
    "ma60_missing_or_non_finite",
}
_INSTITUTIONAL_REASONS = {
    "institutional_flow_to_turnover_ratio_5d_missing_or_non_finite",
    "institutional_flow_5d_missing_or_incomplete",
}
_MARGIN_REASONS = {
    "margin_balance_change_ratio_5d_missing_or_non_finite",
    "margin_change_5d_missing_or_incomplete",
}
# Codes the coverage reports that do not explain a missing bar.
_NOT_BAR_COVERAGE = {"missing_chips", "etf_not_general_action_eligible"}


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def coverage_gap_reasons(coverage: Mapping[str, Any]) -> list[dict[str, str]]:
    """Reasons for the 20/60-session bar gaps of ``decision._instrument_coverage``."""

    if coverage.get("coverage_status") == "unknown":
        return [
            {
                "code": "coverage_baseline_unknown",
                "label": "尚無已核實的加權指數交易日，無法計算有效交易日",
            }
        ]
    short = any(
        (coverage.get(key) or 0) > 0
        for key in ("missing_bars_to_20", "missing_bars_to_60")
    )
    if not short:
        return []
    codes = set(coverage.get("coverage_reasons") or [])
    reasons: list[dict[str, str]] = []
    eligible = coverage.get("eligible_sessions")
    if "listed_under_threshold" in codes and isinstance(eligible, int):
        reasons.append(
            {
                "code": "listed_under_threshold",
                "label": f"上市（櫃）後只有 {eligible} 個交易日，未滿 60 個交易日",
            }
        )
    counted = (
        ("suspended_or_no_trade", "suspended_dates_to_60", "天停牌"),
        ("official_no_trade", "no_trade_dates_to_60", "天官方行情無成交"),
        (
            "bar_invalid",
            "invalid_bar_dates_to_60",
            "天已收到行情但數值不完整（開高低收或來源無法使用）",
        ),
        (
            "quote_not_listed",
            "quote_not_listed_dates_to_60",
            "天官方行情表未列此股（可能是停止買賣，官方未提供停牌資料）",
        ),
    )
    explained: set[str] = set()
    for code, key, text in counted:
        # Each day under one cause, in this order (a suspended day the quote
        # table also lists without prices is a suspension).
        days = [item for item in coverage.get(key) or [] if item not in explained]
        explained.update(days)
        if code in codes and days:
            reasons.append(
                {"code": code, "label": f"近 60 個交易日有 {len(days)} {text}"}
            )
    if "missing_bar_dates" in codes:
        days = [
            item
            for item in coverage.get("missing_bar_dates_to_60") or []
            if item not in explained
        ]
        label = (
            f"近 60 個交易日有 {len(days)} 天行情尚未收錄"
            if days
            else "近 20 個交易日有行情尚未收錄"
        )
        reasons.append({"code": "missing_bar_dates", "label": label})
    if not reasons and not codes - _NOT_BAR_COVERAGE:
        reasons.append(
            {"code": "missing_bar_dates", "label": "近 60 個交易日有行情尚未收錄"}
        )
    return reasons


def chip_gap_reasons(
    missing: Iterable[str],
    chip_rows: Sequence[Any],
    sessions: Sequence[date],
    signal_codes: Iterable[str] = (),
    chip_collected: Callable[[date, str], bool] | None = None,
) -> list[dict[str, str]]:
    """Reasons for chip blockers: the official tables did not list the stock.

    ``chip_rows`` are the summary's last chip rows and ``sessions`` the
    stock's verified sessions (oldest first).  A session counts as unlisted
    when no row of that day carries the group's values.  A signal whose
    institutional or margin input is missing (``signal_codes``) asks for the
    same check: the summary's chip blockers read the last five rows whatever
    their dates, so old rows can hide the gap there.

    ``chip_collected(day, group)`` says whether any stock of the exchange has
    the group's values that day (``institutional`` or ``margin``).  A day no
    stock has is a collection gap that a backfill can fill, not a day the
    official table left this stock out (#511 review); without the check every
    such day counts as not collected.
    """

    blockers = set(missing) & CHIP_BLOCKERS
    codes = {str(item).split(":", 1)[0] for item in signal_codes}
    if codes & _INSTITUTIONAL_REASONS:
        blockers.add("institutional_flow_5d")
    if codes & _MARGIN_REASONS:
        blockers.add("margin_balance")
    if not blockers:
        return []
    rows_by_day: dict[date, Any] = {}
    for row in chip_rows:
        rows_by_day.setdefault(row.trading_date, row)
    reasons: list[dict[str, str]] = []
    groups = (
        (
            "institutional",
            "institutional_not_listed",
            INSTITUTIONAL_FIELDS,
            "天官方三大法人表未列此股（官方只列當天有法人買賣的股票）",
            "天法人資料尚未收錄",
            blockers & {"institutional_flow_5d", *INSTITUTIONAL_FIELDS},
            CHIP_WINDOW_SESSIONS,
        ),
        (
            "margin",
            "margin_not_listed",
            MARGIN_FIELDS,
            "天官方融資餘額表未列此股",
            "天融資資料尚未收錄",
            blockers & set(MARGIN_FIELDS),
            # The five-day margin change reads the balance five sessions back.
            MARGIN_WINDOW_SESSIONS,
        ),
    )
    for group, code, fields, listed_text, uncollected_text, wanted, size in groups:
        if not wanted:
            continue
        window = list(sessions)[-size:]
        absent = [
            day
            for day in window
            if not (
                day in rows_by_day
                and all(_finite(getattr(rows_by_day[day], field)) for field in fields)
            )
        ]
        collected = [
            day
            for day in absent
            if chip_collected is not None and chip_collected(day, group)
        ]
        uncollected = [day for day in absent if day not in collected]
        if collected:
            reasons.append(
                {
                    "code": code,
                    "label": f"近 {len(window)} 個交易日有 {len(collected)} {listed_text}",
                }
            )
        if uncollected:
            reasons.append(
                {
                    "code": f"{group}_not_collected",
                    "label": f"近 {len(window)} 個交易日有 {len(uncollected)} {uncollected_text}",
                }
            )
        if not absent and (
            code == "margin_not_listed"
            and len(window) == MARGIN_WINDOW_SESSIONS
            and getattr(rows_by_day[window[0]], "margin_balance", None) == 0
        ):
            # Every day is listed, but the ratio's base balance is 0: the
            # five-day change ratio has no denominator (#404).
            reasons.append(
                {
                    "code": "margin_zero_base",
                    "label": "5 個交易日前融資餘額為 0，無法計算融資變化率",
                }
            )
    return reasons


def signal_data_codes(strategy_results: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The stored data reasons of the incomplete signals (``rule_evidence_json``)."""

    codes: list[str] = []
    for result in strategy_results.values():
        if result.get("status") != "data_incomplete":
            continue
        evidence = result.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        for value in evidence.values():
            if (
                isinstance(value, Mapping)
                and value.get("state") == "data_incomplete"
                and isinstance(value.get("reasons"), list)
            ):
                codes.extend(str(item) for item in value["reasons"])
    return list(dict.fromkeys(codes))


# A stock listed fewer than 20 sessions ago has no 20-day turnover or group
# return either: the listing explains these inputs too.
_SHORT_LISTING_REASONS = {
    "group_excess_return_20d_missing_or_non_finite",
    "institutional_flow_to_turnover_ratio_5d_missing_or_non_finite",
    *_MARGIN_REASONS,
}


GROUP_RETURN_REASON = "group_excess_return_20d_missing_or_non_finite"


def signal_gap_reasons(
    codes: Iterable[str],
    explained_topics: set[str],
    group_missing: Iterable[str] = (),
) -> list[dict[str, str]]:
    """Sentences for signal data reasons, minus what is already explained.

    ``group_missing`` is the summary's group blocker: ``theme_membership``
    when the stock belongs to no active group with a score.
    """

    group_missing = set(group_missing)
    reasons: list[dict[str, str]] = []
    for code in codes:
        base = code.split(":", 1)[0]
        if base == GROUP_RETURN_REASON:
            label = (
                "未歸屬任何有效族群，無法計算族群相對加權指數的 20 日報酬"
                if "theme_membership" in group_missing
                else "所屬族群的分數資料不完整，無法計算族群相對加權指數的 20 日報酬"
            )
            if "short_listing" not in explained_topics:
                reasons.append({"code": "group_return_unavailable", "label": label})
            continue
        topic = (
            "bars"
            if base in _BAR_REASONS
            else "institutional"
            if base in _INSTITUTIONAL_REASONS
            else "margin"
            if base in _MARGIN_REASONS
            else None
        )
        if topic is not None and topic in explained_topics:
            continue
        if base in _SHORT_LISTING_REASONS and "short_listing" in explained_topics:
            continue
        label = display_reason(code, fallback="")
        if label:
            reasons.append({"code": base, "label": label})
    return reasons


def data_gap_reasons(
    *,
    coverage: Mapping[str, Any],
    missing: Iterable[str],
    chip_rows: Sequence[Any],
    sessions: Sequence[date],
    strategy_results: Mapping[str, Mapping[str, Any]],
    group_missing: Iterable[str] = (),
    chip_collected: Callable[[date, str], bool] | None = None,
) -> list[dict[str, str]]:
    """Every reason of a ``data_insufficient`` summary, each sentence once."""

    missing = list(missing)
    codes = signal_data_codes(strategy_results)
    bars = coverage_gap_reasons(coverage)
    topics: set[str] = set()
    if bars:
        topics.add("bars")
    eligible = coverage.get("eligible_sessions")
    short_listing = (
        "listed_under_threshold" in (coverage.get("coverage_reasons") or [])
        and isinstance(eligible, int)
        and eligible < 20
    )
    if short_listing:
        topics.add("short_listing")
        codes = [
            code
            for code in codes
            if code.split(":", 1)[0] not in _SHORT_LISTING_REASONS
        ]
    chips = chip_gap_reasons(missing, chip_rows, sessions, codes, chip_collected)
    if any(
        item["code"] in {"institutional_not_listed", "institutional_not_collected"}
        for item in chips
    ):
        topics.add("institutional")
    if any(
        item["code"]
        in {"margin_not_listed", "margin_not_collected", "margin_zero_base"}
        for item in chips
    ):
        topics.add("margin")
    excluded_etf = []
    if "etf_not_general_action_eligible" in (coverage.get("coverage_reasons") or []):
        excluded_etf.append(
            {
                "code": "etf_not_general_action_eligible",
                "label": display_reason(
                    "etf_category_excluded_from_actionable_signals"
                ),
            }
        )
    reasons = [
        *excluded_etf,
        *bars,
        *chips,
        *signal_gap_reasons(codes, topics, group_missing),
    ]
    if not strategy_results and not reasons:
        # No signal and nothing else explains why: the day was not computed.
        reasons.append(
            {
                "code": "signal_not_computed",
                "label": display_reason("signal_not_computed"),
            }
        )
    unique: dict[str, dict[str, str]] = {}
    for item in reasons:
        unique.setdefault(item["label"], item)
    return list(unique.values())
