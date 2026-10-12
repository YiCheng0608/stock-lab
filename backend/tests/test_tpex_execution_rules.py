"""RAM-only checks of app.tpex_execution_rules (#97).

Expected tick levels, session clock times and the fee notification threshold are
re-derived here from verbatim source sentences, not copied from the module's
tables. The sentences are the text read on 2026-10-12 from the sources pinned in
SOURCES_SHA256. These are synthetic arithmetic checks; they say nothing about any
real fill or price.
"""

import ast
import builtins
import importlib.util
import re
import socket
import sqlite3
import sys
from dataclasses import FrozenInstanceError
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app import tpex_execution_rules as rules
from app.tpex_execution_rules import (
    CallerFeeTerms, ExecutionRulesError, PendingEvidenceError, broker_fee, round_price,
    sell_tax, session_phase, session_windows, tick_size,
)

D = date(2026, 10, 12)  # Monday, the verification day
SCOPE = {"market": "TPEx", "security_type": "ordinary_share", "rule_version": rules.RULES_VERSION}
OPT_IN = {"accept_published_only": True}

# 業務規則第55條第2項，逐字（2021-01-11 版與 2026-10-05 版相同）。
ART55_SENTENCE = (
    "前項申報買賣價格之最低單位每股市價未滿十元者為一分，十元至未滿五十元者為五分，"
    "五十元至未滿一百元者為一角，一百元至未滿五百元者為五角，五百元至未滿一千元者為一元，"
    "一千元以上者為五元。"
)
# TPEx 官網說明頁「四、升降單位」股票列，逐字。
B1_TICK_LINES = (
    "股價 <  $10 為1分",
    "$10 ≤  股價 < $50 為5分",
    "$50 ≤  股價 < $100 為1角",
    "$100≤ 股價 < $500 為5角",
    "$500≤ 股價 < $1,000 為1元",
    "股價 ≥ $1,000 為5元",
)
# 業務規則第40條第1項第1款、第35條第1項與第4項，逐字片段。
ART40_TEXT = "股票採等價成交系統者為上午九時至下午一時三十分"
ART35_ENTRY_TEXT = "等價成交系統之買賣申報，得自市場交易時間開始前之三十分鐘起輸入"
ART35_DEFER_TEXT = (
    "暫緩當市第一次撮合之有價證券，延緩二分鐘後依序撮合成交。"
    "暫緩收市撮合之有價證券，於一時三十一分起至一時三十三分繼續接受其買賣申報之輸入、取消及變更，"
    "俟一時三十三分依序撮合成交。"
)
# TPEx 官網說明頁「交易時間」「撮合方式」，逐字片段。
B1_SESSION_TEXT = (
    "星期一至星期五，委託時間8:30至13:30，撮合成交時間為9:00至13:30。"
    "其後至13:25分採逐筆交易撮合，13:25至收"
)
# 業務規則第64條第3項片段，逐字。
ART64_TEXT = "證券經紀商所訂手續費率逾成交金額千分之一點四二五者，應於實施前以適當方式通知客戶，並留存紀錄。"

C1_SHA = "c1ddb12e0593a972ef4015b102e65e42ac37bdb186855772ea65ef51471e7d49"
SOURCES_SHA256 = {
    "tpex-mainboard-system-intro": "fd1217d8ef6e8e48769b1e4c3d2aea3b4878148b53879fd33423555d03cb291f",
    "tpex-rules-art55-selaw-20210111": "82f87349047a5173fdbf5a9e558a7956ce004d8130725b36b66e265d5a65642b",
    "tpex-rules-current-selaw-20261005": "2225a9aeec0a42b2fa56162835b8ef84e12a5bbffb2711f356a6dd120aeccf46",
    "tpex-rules-art35-selaw-20261005": C1_SHA,
    "tpex-rules-art40-selaw-20261005": C1_SHA,
    "tpex-rules-art55-selaw-20261005": C1_SHA,
    "tpex-rules-art64-selaw-20261005": C1_SHA,
    "moj-securities-otc-trading-measures": "e15be76abf1cb5d6be5f56c5f171511ef00e43c88783042277b35e01a95082a9",
    "mof-securities-transaction-tax-act": "e5f6388ea66efe64e295c0757d76d6a4c0b8dd4bbc5c6394065c9ff9d2793291",
    "moj-securities-transaction-tax-act": "372ef60403bdfc4ff2108204562a209b7cf56975c99da40cf604802460bd0e48",
    "mof-tax-example-20260310": "6a70c06754ac5d05a9ea4638fdcabbaef747e2d19c6d3b0f8526a6c69076fc66",
}

_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000}
_UNIT = {"分": Decimal("0.01"), "角": Decimal("0.1"), "元": Decimal(1)}
_CN = "零一二三四五六七八九十百千"


def _chinese_int(text):
    total = current = 0
    for ch in text:
        if ch in _DIGITS:
            current = _DIGITS[ch]
        else:
            total += (current or 1) * _UNITS[ch]
            current = 0
    return total + current


def _ladder_from_art55():
    body = ART55_SENTENCE.removeprefix("前項申報買賣價格之最低單位每股市價").removesuffix("。")
    pattern = re.compile(
        r"^(?:(?P<lo>[^元至]+)元至)?(?:未滿(?P<hi>[^元]+)元|(?P<up>[^元]+)元以上)"
        r"者為(?P<n>[一二三四五六七八九])(?P<u>分|角|元)$"
    )
    ladder = []
    for clause in body.split("，"):
        m = pattern.match(clause)
        assert m, clause
        low = m["lo"] or m["up"]
        lower = Decimal(_chinese_int(low)) if low else Decimal(0)
        upper = Decimal(_chinese_int(m["hi"])) if m["hi"] else None
        ladder.append((lower, upper, _chinese_int(m["n"]) * _UNIT[m["u"]]))
    return ladder


def _ladder_from_b1():
    pattern = re.compile(
        r"^(?:\$(?P<lo>[\d,]+)\s*≤\s*)?股價\s*(?:<\s*\$(?P<hi>[\d,]+)|≥\s*\$(?P<up>[\d,]+))"
        r"\s*為(?P<n>\d+)(?P<u>分|角|元)$"
    )
    number = lambda s: Decimal(s.replace(",", ""))
    ladder = []
    for line in B1_TICK_LINES:
        m = pattern.match(line)
        assert m, line
        low = m["lo"] or m["up"]
        lower = number(low) if low else Decimal(0)
        upper = number(m["hi"]) if m["hi"] else None
        ladder.append((lower, upper, int(m["n"]) * _UNIT[m["u"]]))
    return ladder


def _pack_ladder():
    return [(b.lower_inclusive, b.upper_exclusive, b.tick) for b in rules.get_rule_pack(rules.RULES_VERSION).tick.bands]


def test_ladder_matches_both_verbatim_sources():
    assert _ladder_from_art55() == _pack_ladder()
    assert _ladder_from_b1() == _pack_ladder()
    assert len(_pack_ladder()) == 6


def test_every_band_edge_uses_the_band_the_text_gives():
    ladder = _ladder_from_art55()
    for index, (lower, upper, tick) in enumerate(ladder):
        inside = tick_size(lower if lower else Decimal("0.01"), **SCOPE, on_date=D, **OPT_IN)
        assert inside.tick == tick and inside.band_lower_inclusive == lower
        if upper is not None:
            just_below = tick_size(upper - tick, **SCOPE, on_date=D, **OPT_IN)
            at_upper = tick_size(upper, **SCOPE, on_date=D, **OPT_IN)
            assert just_below.tick == tick and just_below.band_upper_exclusive == upper
            assert at_upper.tick == ladder[index + 1][2]
            assert at_upper.band_lower_inclusive == upper


@pytest.mark.parametrize(("price", "tick"), [
    ("0.01", "0.01"), ("0.001", "0.01"), ("9.99", "0.01"), ("10", "0.05"), ("49.95", "0.05"),
    ("50", "0.1"), ("99.9", "0.1"), ("100", "0.5"), ("499.5", "0.5"), ("500", "1"),
    ("999", "1"), ("1000", "5"), ("1005", "5"), ("123456", "5"),
])
def test_tick_size_examples(price, tick):
    assert tick_size(Decimal(price), **SCOPE, on_date=D, **OPT_IN).tick == Decimal(tick)


@pytest.mark.parametrize(("price", "direction", "expected"), [
    ("9.994", "down", "9.99"), ("9.994", "up", "10.00"), ("10.01", "up", "10.05"),
    ("10.04", "down", "10.00"), ("49.96", "up", "50.00"), ("50.01", "up", "50.1"),
    ("99.95", "up", "100"), ("100.2", "down", "100"), ("100.2", "up", "100.5"),
    ("999.5", "up", "1000"), ("1002", "up", "1005"), ("1002", "down", "1000"),
    ("10.05", "up", "10.05"), ("10.05", "down", "10.05"),
])
def test_round_price(price, direction, expected):
    quote = round_price(Decimal(price), direction, **SCOPE, on_date=D, **OPT_IN)
    assert quote.rounded == Decimal(expected)
    assert quote.rounded % quote.tick == 0


@pytest.mark.parametrize("bad", [10, 10.0, "10", None, True, Decimal("NaN"), Decimal("Infinity"),
                                 Decimal(0), Decimal("-1"), Decimal("1E-9"), Decimal("1E13")])
def test_price_input_rejected(bad):
    with pytest.raises(ExecutionRulesError) as err:
        tick_size(bad, **SCOPE, on_date=D, **OPT_IN)
    assert not isinstance(err.value, PendingEvidenceError)


def test_round_price_needs_direction():
    for bad in ("nearest", "UP", None, 1):
        with pytest.raises(ExecutionRulesError, match="direction"):
            round_price(Decimal("10"), bad, **SCOPE, on_date=D, **OPT_IN)


def _terms(**kw):
    values = {"broker": "caller-broker", "rate": Decimal("0.001425"), "discount": Decimal("0.6"),
              "minimum": Decimal(20), "rounding": "half_up"}
    values.update(kw)
    return CallerFeeTerms(**values)


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("market", "TWSE", "market:unknown_or_unsupported"),
    ("market", "TSE", "market:unknown_or_unsupported"),
    ("market", "tpex", "market:unknown_or_unsupported"),
    ("market", "TPEx ", "market:unknown_or_unsupported"),
    ("market", "ESB", "market:unknown_or_unsupported"),
    ("market", "", "market:unknown_or_unsupported"),
    ("market", None, "market:unknown_or_unsupported"),
    ("security_type", "etf", "security_type:unknown_or_unsupported"),
    ("security_type", "ordinary_share ", "security_type:unknown_or_unsupported"),
    ("security_type", None, "security_type:unknown_or_unsupported"),
    ("rule_version", "latest", "rule_version:unknown_or_unsupported"),
    ("rule_version", "tpex-static-rules/2026-10-12/v2", "rule_version:unknown_or_unsupported"),
    ("rule_version", "tpex-static-rules/2026-10-11/v1", "rule_version:unknown_or_unsupported"),
    ("rule_version", None, "rule_version:unknown_or_unsupported"),
])
def test_unknown_scope_rejected_for_every_reader(field, value, reason):
    scope = {**SCOPE, field: value}
    calls = (
        lambda: tick_size(Decimal("10"), **scope, on_date=D, **OPT_IN),
        lambda: round_price(Decimal("10"), "up", **scope, on_date=D, **OPT_IN),
        lambda: session_windows(**scope, on_date=D, **OPT_IN),
        lambda: session_phase(time(10), **scope, on_date=D, **OPT_IN),
        lambda: sell_tax(price=Decimal("90"), quantity=1000, day_trade=False, **scope, on_date=D, **OPT_IN),
        lambda: broker_fee(notional=Decimal("90000"), terms=_terms(), **scope, on_date=D, **OPT_IN),
    )
    for call in calls:
        with pytest.raises(ExecutionRulesError) as err:
            call()
        assert err.value.reason == reason
        assert not isinstance(err.value, PendingEvidenceError)


def test_undated_components_are_pending_evidence_by_default():
    for label, call in (
        ("tick", lambda: tick_size(Decimal("10"), **SCOPE, on_date=D)),
        ("tick", lambda: round_price(Decimal("10"), "up", **SCOPE, on_date=D)),
        ("session", lambda: session_windows(**SCOPE, on_date=D)),
        ("session", lambda: session_phase(time(10), **SCOPE, on_date=D)),
        ("broker_fee", lambda: broker_fee(notional=Decimal("90000"), terms=_terms(), **SCOPE, on_date=D)),
        ("sell_tax", lambda: sell_tax(price=Decimal("90"), quantity=1000, day_trade=False, **SCOPE, on_date=D)),
    ):
        with pytest.raises(PendingEvidenceError) as err:
            call()
        assert err.value.reason == label + ":effective_date_unverified"


def test_opt_in_labels_the_result_as_unverified_and_names_the_sources():
    tick = tick_size(Decimal("10"), **SCOPE, on_date=D, **OPT_IN)
    assert tick.basis.effective_date_status == "effective_date_unverified"
    assert tick.basis.published_on == date(2021, 1, 11)
    assert tick.basis.source_ids == ("tpex-rules-art55-selaw-20210111", "tpex-rules-art55-selaw-20261005")
    assert tick.basis.rule_version == rules.RULES_VERSION and tick.basis.on_date == D
    win = session_windows(**SCOPE, on_date=D, **OPT_IN)
    assert win.basis.effective_date_status == "effective_date_unverified"
    assert win.basis.published_on == date(2026, 10, 5)
    assert win.basis.source_ids == ("tpex-rules-art40-selaw-20261005", "tpex-rules-art35-selaw-20261005",
                                    "tpex-mainboard-system-intro")
    assert win.closing_call_basis == "website_description_only_not_in_rule_text"
    fee = broker_fee(notional=Decimal("90000"), terms=_terms(), **SCOPE, on_date=D, **OPT_IN)
    assert fee.basis.effective_date_status == "effective_date_unverified"
    assert fee.basis.source_ids == ("tpex-rules-art64-selaw-20261005", "moj-securities-otc-trading-measures")


def test_dates_outside_the_evidence_window_are_rejected_even_when_opted_in():
    with pytest.raises(ExecutionRulesError) as err:
        tick_size(Decimal("10"), **SCOPE, on_date=date(2021, 1, 10), **OPT_IN)
    assert err.value.reason == "tick:before_published_date"
    assert tick_size(Decimal("10"), **SCOPE, on_date=date(2021, 1, 11), **OPT_IN).tick == Decimal("0.05")
    with pytest.raises(ExecutionRulesError) as err:
        tick_size(Decimal("10"), **SCOPE, on_date=date(2021, 1, 10))  # outside beats pending
    assert err.value.reason == "tick:before_published_date"
    before_version = date(2026, 10, 2)
    for call, label in (
        (lambda d, **kw: session_windows(**SCOPE, on_date=d, **kw), "session"),
        (lambda d, **kw: broker_fee(notional=Decimal("90000"), terms=_terms(), **SCOPE, on_date=d, **kw), "broker_fee"),
    ):
        for kw in (OPT_IN, {}):
            with pytest.raises(ExecutionRulesError) as err:
                call(before_version, **kw)
            assert err.value.reason == label + ":before_published_date"
            assert not isinstance(err.value, PendingEvidenceError)
        call(date(2026, 10, 5), **OPT_IN)
    for call, label in (
        (lambda d: tick_size(Decimal("10"), **SCOPE, on_date=d, **OPT_IN), "tick"),
        (lambda d: session_windows(**SCOPE, on_date=d, **OPT_IN), "session"),
        (lambda d: sell_tax(price=Decimal("90"), quantity=1000, day_trade=False, **SCOPE, on_date=d), "sell_tax"),
        (lambda d: broker_fee(notional=Decimal("90000"), terms=_terms(), **SCOPE, on_date=d, **OPT_IN), "broker_fee"),
    ):
        with pytest.raises(ExecutionRulesError) as err:
            call(date(2026, 10, 13))
        assert err.value.reason == label + ":after_verified_date"
        assert not isinstance(err.value, PendingEvidenceError)


@pytest.mark.parametrize("bad", [datetime(2026, 10, 12), "2026-10-12", None, 20261012])
def test_on_date_must_be_a_date(bad):
    with pytest.raises(ExecutionRulesError, match="on_date"):
        tick_size(Decimal("10"), **SCOPE, on_date=bad, **OPT_IN)


@pytest.mark.parametrize("bad", [1, "yes", None])
def test_opt_in_must_be_a_bool(bad):
    with pytest.raises(ExecutionRulesError, match="accept_published_only"):
        tick_size(Decimal("10"), **SCOPE, on_date=D, accept_published_only=bad)


def _clock(text, *, afternoon=False):
    m = re.search(rf"(?P<half>上午|下午)?(?P<h>[{_CN}]+)時(?:(?P<m>[{_CN}]+)分)?", text)
    assert m, text
    hour = _chinese_int(m["h"])
    if m["half"] == "下午" or (afternoon and hour < 12):
        hour += 12
    return time(hour, _chinese_int(m["m"]) if m["m"] else 0)


def _shift(clock, minutes):
    return (datetime.combine(date(2000, 1, 1), clock) + timedelta(minutes=minutes)).time()


def _session_clock_from_texts():
    open_ = _clock(ART40_TEXT.split("至")[0])
    close = _clock(ART40_TEXT.split("至", 1)[1])
    entry_minutes = _chinese_int(re.search(rf"開始前之([{_CN}]+)分鐘", ART35_ENTRY_TEXT)[1])
    defer_minutes = _chinese_int(re.search(rf"延緩([{_CN}]+)分鐘", ART35_DEFER_TEXT)[1])
    defer_close = _clock(re.search(rf"俟([{_CN}]+時[{_CN}]+分)依序撮合", ART35_DEFER_TEXT)[1], afternoon=True)
    web = re.search(r"委託時間(\d+:\d+)至(\d+:\d+)，撮合成交時間為(\d+:\d+)至(\d+:\d+)", B1_SESSION_TEXT)
    call = re.search(r"其後至(\d+:\d+)分採逐筆交易撮合，(\d+:\d+)至收", B1_SESSION_TEXT)
    assert web and call and call[1] == call[2]
    parse = lambda s: time(*map(int, s.split(":")))
    return {
        "order_entry_open": _shift(open_, -entry_minutes), "matching_open": open_, "close": close,
        "deferred_open_until": _shift(open_, defer_minutes), "deferred_close_until": defer_close,
        "closing_call_start": parse(call[1]),
        "web": (parse(web[1]), parse(web[2]), parse(web[3]), parse(web[4])),
    }


def test_session_windows_match_the_source_sentences():
    expected = _session_clock_from_texts()
    assert expected["web"] == (time(8, 30), time(13, 30), time(9, 0), time(13, 30))
    win = session_windows(**SCOPE, on_date=D, **OPT_IN)
    assert win.order_entry_open == expected["order_entry_open"] == expected["web"][0] == time(8, 30)
    assert win.matching_open == expected["matching_open"] == expected["web"][2] == time(9, 0)
    assert win.close == expected["close"] == expected["web"][1] == expected["web"][3] == time(13, 30)
    assert win.deferred_open_until == expected["deferred_open_until"] == time(9, 2)
    assert win.deferred_close_until == expected["deferred_close_until"] == time(13, 33)
    assert win.closing_call_start == expected["closing_call_start"] == time(13, 25)
    assert win.deferred_semantics == "only_for_securities_meeting_the_deferral_standard"


@pytest.mark.parametrize(("at", "phase"), [
    (time(0, 0), "closed"), (time(7, 59, 59), "closed"),
    (time(8, 30, 0, 1), "order_entry_before_open"), (time(8, 59, 59, 999999), "order_entry_before_open"),
    (time(9, 0, 0, 1), "continuous_matching"), (time(12, 0), "continuous_matching"),
    (time(13, 24, 59, 999999), "continuous_matching"),
    (time(13, 25, 0, 1), "closing_call_auction"), (time(13, 29, 59, 999999), "closing_call_auction"),
    (time(13, 30, 0, 1), "closed"), (time(13, 33), "closed"), (time(23, 59, 59), "closed"),
])
def test_session_phase_interior_times(at, phase):
    quote = session_phase(at, **SCOPE, on_date=D, **OPT_IN)
    assert quote.phase == phase and quote.boundary_at is None and quote.boundary_semantics is None


@pytest.mark.parametrize("at", [time(8, 30), time(9, 0), time(13, 25), time(13, 30)])
def test_exact_boundaries_are_reported_unspecified(at):
    quote = session_phase(at, **SCOPE, on_date=D, **OPT_IN)
    assert (quote.phase, quote.boundary_at, quote.boundary_semantics) == ("boundary", at, "unspecified_by_source")


@pytest.mark.parametrize("bad", [datetime(2026, 10, 12, 10), "10:00", None, 10,
                                 time(10, tzinfo=timezone.utc)])
def test_session_time_must_be_a_naive_time(bad):
    with pytest.raises(ExecutionRulesError, match="at:naive_time_required"):
        session_phase(bad, **SCOPE, on_date=D, **OPT_IN)


@pytest.mark.parametrize("day", [date(2026, 10, 10), date(2026, 10, 11)])
def test_weekend_is_not_a_stated_trading_weekday(day):
    for call in (lambda: session_windows(**SCOPE, on_date=day, **OPT_IN),
                 lambda: session_phase(time(10), **SCOPE, on_date=day, **OPT_IN)):
        with pytest.raises(ExecutionRulesError) as err:
            call()
        assert err.value.reason == "session:not_a_stated_trading_weekday"


def test_stated_weekdays_are_monday_to_friday_only():
    assert [session_windows(**SCOPE, on_date=date(2026, 10, d), **OPT_IN).basis.on_date.weekday()
            for d in (5, 6, 7, 8, 9)] == [0, 1, 2, 3, 4]


def _sell(**kw):
    values = {"price": Decimal("90"), "quantity": 1000, "day_trade": False, "on_date": D, **SCOPE, **OPT_IN}
    values.update(kw)
    return sell_tax(**values)


def test_official_tax_example():
    # 財政部臺北國稅局算例：200,000 股 × 90 元，總價 18,000,000 元，×3‰ = 54,000 元。
    quote = _sell(quantity=200_000)
    assert quote.notional == Decimal(18_000_000)
    assert quote.rate == Decimal("0.003")
    assert quote.tax_exact == Decimal(54_000)
    assert quote.basis.effective_date_status == "effective_date_unverified"
    assert quote.basis.published_on == date(2025, 1, 2)
    assert quote.basis.source_ids == ("mof-securities-transaction-tax-act", "moj-securities-transaction-tax-act")


def test_tax_without_a_stated_effective_date_is_pending_evidence_by_default():
    for kw in ({"accept_published_only": False}, {}):
        values = {"price": Decimal("90"), "quantity": 1000, "day_trade": False, "on_date": D, **SCOPE, **kw}
        with pytest.raises(PendingEvidenceError) as err:
            sell_tax(**values)
        assert err.value.reason == "sell_tax:effective_date_unverified"


def test_tax_rounding_is_not_defined_by_sources():
    quote = _sell(price=Decimal("45.15"))
    assert quote.tax_exact == Decimal("135.45")
    assert (quote.rounding_policy, quote.tax_rounded) == (None, None)
    assert quote.rounding_basis == "not_defined_by_sources"
    assert quote.official_rounding_status == "pending_evidence"


@pytest.mark.parametrize(("price", "qty", "policy", "expected"), [
    ("45.15", 1000, "floor", "135"), ("45.15", 1000, "ceil", "136"), ("45.15", 1000, "half_up", "135"),
    ("10.05", 1000, "half_up", "30"), ("10.05", 1000, "ceil", "31"),
    ("0.5", 1000, "floor", "1"), ("0.5", 1000, "half_up", "2"), ("0.5", 1000, "ceil", "2"),
    ("50", 1000, "floor", "150"), ("50", 1000, "ceil", "150"), ("50", 1000, "half_up", "150"),
])
def test_caller_declared_tax_rounding_is_labelled(price, qty, policy, expected):
    quote = _sell(price=Decimal(price), quantity=qty, rounding=policy)
    assert quote.tax_rounded == Decimal(expected)
    assert quote.rounding_basis == "caller_declared:" + policy
    assert quote.official_rounding_status == "pending_evidence"


def test_tax_date_window_and_day_trade_exclusion():
    assert _sell(on_date=date(2025, 1, 2)).tax_exact == Decimal(270)
    for kw in (OPT_IN, {"accept_published_only": False}):
        with pytest.raises(ExecutionRulesError) as err:
            _sell(on_date=date(2025, 1, 1), **kw)
        assert err.value.reason == "sell_tax:before_published_date"
        assert not isinstance(err.value, PendingEvidenceError)
    with pytest.raises(ExecutionRulesError) as err:
        _sell(day_trade=True)
    assert err.value.reason == "sell_tax:day_trade_rate_not_supported"
    for bad in (None, 0, 1, "no"):
        with pytest.raises(ExecutionRulesError, match="day_trade:bool_required"):
            _sell(day_trade=bad)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "1000", None, 1_000_000_001])
def test_tax_quantity_rejected(bad):
    with pytest.raises(ExecutionRulesError, match="quantity"):
        _sell(quantity=bad)


@pytest.mark.parametrize("bad", [90, 90.0, "90", Decimal(0), Decimal("-90"), Decimal("NaN")])
def test_tax_price_rejected(bad):
    with pytest.raises(ExecutionRulesError, match="price"):
        _sell(price=bad)


def test_tax_rounding_policy_rejected():
    for bad in ("round", "FLOOR", 1, True):
        with pytest.raises(ExecutionRulesError, match="rounding:unsupported_policy"):
            _sell(rounding=bad)


def _threshold_from_art64():
    m = re.search(rf"千分之([{_CN}]+)點([{_CN}]+)", ART64_TEXT)
    assert m
    fraction = "".join(str(_DIGITS[ch]) for ch in m[2])
    return Decimal(f"{_chinese_int(m[1])}.{fraction}") / 1000


def test_fee_threshold_is_the_notification_threshold_not_a_ceiling():
    assert _threshold_from_art64() == Decimal("0.001425")
    assert "應於實施前以適當方式通知客戶" in ART64_TEXT and "上限" not in ART64_TEXT
    fee = lambda rate: broker_fee(notional=Decimal("100000"), terms=_terms(rate=Decimal(rate)),
                                  **SCOPE, on_date=D, **OPT_IN)
    at, over, under = fee("0.001425"), fee("0.001426"), fee("0.001")
    assert at.notification_threshold_rate == _threshold_from_art64()
    assert (at.above_notification_threshold, over.above_notification_threshold,
            under.above_notification_threshold) == (False, True, False)
    assert over.fee == Decimal("86")  # a rate above the threshold is flagged, never rejected
    assert over.official_terms_status == "broker_set_and_filed_no_uniform_rate_or_minimum"


@pytest.mark.parametrize(("notional", "rounding", "fee", "min_applied"), [
    ("100000", "half_up", "86", False),   # 100000 x 0.001425 x 0.6 = 85.5
    ("100000", "floor", "85", False),
    ("100000", "ceil", "86", False),
    ("10000", "half_up", "20", True),     # 8.55 -> 9 < 20
    ("22807", "half_up", "20", True),     # 19.499985 -> 19 < 20
    ("22808", "half_up", "20", False),    # 19.50084 -> 20 = minimum
    ("23391", "floor", "20", True),       # 19.999305 -> 19 < 20
    ("23391", "ceil", "20", False),       # 19.999305 -> 20 = minimum
    ("1000000", "floor", "855", False),   # exactly 855
])
def test_caller_declared_fee(notional, rounding, fee, min_applied):
    quote = broker_fee(notional=Decimal(notional), terms=_terms(rounding=rounding), **SCOPE,
                       on_date=D, **OPT_IN)
    assert quote.fee == Decimal(fee) and quote.minimum_applied is min_applied
    assert quote.terms_basis == "caller_declared"
    assert quote.official_terms_status == "broker_set_and_filed_no_uniform_rate_or_minimum"


def test_fee_terms_rejected():
    ok = {"notional": Decimal("100000"), **SCOPE, "on_date": D, **OPT_IN}
    for bad, reason in (
        (_terms(rate=Decimal(1)), "rate_or_discount_out_of_range"),
        (_terms(rate=Decimal("-0.001")), "outside_supported_range"),
        (_terms(discount=Decimal(0)), "positive_decimal_required"),
        (_terms(discount=Decimal("1.1")), "rate_or_discount_out_of_range"),
        (_terms(minimum=Decimal("20.5")), "whole_dollar_required"),
        (_terms(minimum=Decimal("-1")), "outside_supported_range"),
        (_terms(rounding="round"), "unsupported_policy"),
        (_terms(broker=" "), "nonempty_string_required"),
        (_terms(rate=0.001425), "finite_decimal_required"),
        ({"rate": "0.001425"}, "caller_fee_terms_required"),
        (None, "caller_fee_terms_required"),
    ):
        with pytest.raises(ExecutionRulesError, match=reason):
            broker_fee(terms=bad, **ok)
    for bad in (100000, Decimal(0), Decimal("NaN"), "100000"):
        with pytest.raises(ExecutionRulesError, match="notional"):
            broker_fee(notional=bad, terms=_terms(), **{k: v for k, v in ok.items() if k != "notional"})


def test_registry_sources_are_complete_and_pinned():
    pack = rules.get_rule_pack(rules.RULES_VERSION)
    by_id = {src.source_id: src for src in rules.pack_sources(pack)}
    assert {k: v.sha256 for k, v in by_id.items()} == SOURCES_SHA256
    for src in by_id.values():
        assert src.url.startswith("https://") and src.locator and src.document and src.issuer
        assert src.retrieved_at.utcoffset().total_seconds() == 0
        assert src.retrieved_at.date() == date(2026, 10, 12)
        assert src.effective_from is None and src.effective_through is None
        assert src.effective_basis == ("not_a_rule_example_only" if src is pack.sell_tax.example
                                       else "not_stated_on_page")
    aggregated = {k for k, v in by_id.items() if "selaw" in v.url}
    assert aggregated == {k for k in SOURCES_SHA256 if "-selaw-" in k}
    for key in aggregated:
        assert by_id[key].via and "非發布機關原件" in by_id[key].via
    # The four article sources share one saved original but point at different articles.
    shared = [by_id[k] for k in aggregated if SOURCES_SHA256[k] == C1_SHA]
    assert len({s.url for s in shared}) == 1 and len({s.locator for s in shared}) == len(shared) == 4
    assert all(s.published_on == date(2026, 10, 5) and s.effective_from is None for s in shared)
    assert (pack.market, pack.security_type, pack.version) == ("TPEx", "ordinary_share", rules.RULES_VERSION)
    assert pack.sell_tax.rate == Decimal("0.003") and pack.sell_tax.rounding_status == "pending_evidence"
    assert pack.broker_fee.notification_threshold_rate == Decimal("0.001425")
    assert pack.broker_fee.rounding_status == "not_stated"


def test_results_are_immutable():
    quote = tick_size(Decimal("10"), **SCOPE, on_date=D, **OPT_IN)
    with pytest.raises(FrozenInstanceError):
        quote.tick = Decimal(1)
    with pytest.raises(FrozenInstanceError):
        rules.get_rule_pack(rules.RULES_VERSION).sell_tax.rate = Decimal(0)


def test_module_has_no_io_imports_or_calls():
    tree = ast.parse(Path(rules.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "print", "exec", "eval", "compile", "__import__", "input"}
    assert imported <= {"__future__", "dataclasses", "datetime", "decimal", "urllib.parse"}


def test_import_performs_no_file_network_or_database_access(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("I/O during import")

    spec = importlib.util.spec_from_file_location("tpex_rules_isolated_copy", rules.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "dont_write_bytecode", True)
            patch.setattr(builtins, "open", boom)
            patch.setattr(socket, "socket", boom)
            patch.setattr(socket, "create_connection", boom)
            patch.setattr(socket, "getaddrinfo", boom)
            patch.setattr(sqlite3, "connect", boom)
            spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    assert module.RULES_VERSION == rules.RULES_VERSION
