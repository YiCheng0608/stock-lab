"""Pure indicator formulas against hand values and a naive reference (no DB, no files)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app import indicators as ind
from app.indicators import IndicatorBar, aggregate_weekly, compute_indicators


def _weekdays(start: date, count: int) -> list[date]:
    days, cursor = [], start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bars(closes, *, start=date(2026, 1, 5), volumes=None, spread=1.0):
    days = _weekdays(start, len(closes))
    return [
        IndicatorBar(
            day,
            close,
            close + spread,
            close - spread,
            close,
            (volumes[i] if volumes else 1000 + 10 * i),
        )
        for i, (day, close) in enumerate(zip(days, closes))
    ]


def _walk(count: int) -> list[float]:
    return [
        round(100 + 8 * math.sin(i / 5) + 3 * math.cos(i / 2.3) + i * 0.05, 2)
        for i in range(count)
    ]


# --- naive references written directly from the published definitions ---


def ref_sma(values, n, i):
    return sum(values[i - n + 1 : i + 1]) / n if i >= n - 1 else None


def ref_ema_series(values, n):
    prev, alpha = None, 2 / (n + 1)
    defined = [(i, v) for i, v in enumerate(values) if v is not None]
    result = [None] * len(values)
    for k, (i, v) in enumerate(defined):
        if k == n - 1:
            prev = sum(x for _, x in defined[:n]) / n
            result[i] = prev
        elif k >= n:
            prev = alpha * v + (1 - alpha) * prev
            result[i] = prev
    return result


def ref_rsi(closes, n, i):
    if i < n:
        return None
    changes = [closes[k] - closes[k - 1] for k in range(1, i + 1)]
    gain = sum(max(c, 0) for c in changes[:n]) / n
    loss = sum(max(-c, 0) for c in changes[:n]) / n
    for c in changes[n:]:
        gain = (gain * (n - 1) + max(c, 0)) / n
        loss = (loss * (n - 1) + max(-c, 0)) / n
    return 100 * gain / (gain + loss)


def ref_kd(highs, lows, closes, i):
    if i < 8:
        return None, None
    k = d = 50.0
    for t in range(8, i + 1):
        hh, ll = max(highs[t - 8 : t + 1]), min(lows[t - 8 : t + 1])
        rsv = 50.0 if hh == ll else (closes[t] - ll) / (hh - ll) * 100
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k
    return k, d


def ref_boll(closes, i):
    if i < 19:
        return None
    window = closes[i - 19 : i + 1]
    mid = sum(window) / 20
    sd = math.sqrt(sum((x - mid) ** 2 for x in window) / 20)
    return mid, mid + 2 * sd, mid - 2 * sd


def assert_matches_reference(points, bars):
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    vols = [b.volume for b in bars]
    fast, slow = ref_ema_series(closes, 12), ref_ema_series(closes, 26)
    dif = [
        f - s if f is not None and s is not None else None for f, s in zip(fast, slow)
    ]
    dea = ref_ema_series(dif, 9)
    for i, point in enumerate(points):
        values = point.values
        expected = {f"ma{n}": ref_sma(closes, n, i) for n in (5, 10, 20, 60, 120)}
        expected.update(
            {"vol_ma5": ref_sma(vols, 5, i), "vol_ma20": ref_sma(vols, 20, i)}
        )
        expected.update(
            {
                "macd_dif": dif[i],
                "macd_signal": dea[i],
                "macd_hist": dif[i] - dea[i] if dea[i] is not None else None,
            }
        )
        expected.update(
            {"rsi6": ref_rsi(closes, 6, i), "rsi12": ref_rsi(closes, 12, i)}
        )
        expected["kd_k"], expected["kd_d"] = ref_kd(highs, lows, closes, i)
        boll = ref_boll(closes, i)
        expected.update(
            dict(
                zip(
                    ("boll_mid", "boll_upper", "boll_lower"), boll or (None, None, None)
                )
            )
        )
        assert set(expected) == set(ind.FIELDS)
        for name, want in expected.items():
            if want is None:
                assert values[name] is None, (i, name)
                assert point.reasons[name] == ind.INSUFFICIENT_BARS, (i, name)
            else:
                assert values[name] == pytest.approx(want, abs=1e-6), (i, name)
                assert name not in point.reasons


def test_matches_naive_reference_over_long_walk():
    bars = _bars(_walk(160))
    points = compute_indicators(bars)
    assert [p.trading_date for p in points] == [b.trading_date for b in bars]
    assert [p.bar_count for p in points] == list(range(1, 161))
    assert_matches_reference(points, bars)
    last = points[-1].values
    assert all(last[name] is not None for name in ind.FIELDS)


def test_hand_computed_values():
    closes = [10, 11, 12, 13, 14, 15]
    points = compute_indicators(_bars(closes, volumes=[100, 200, 300, 400, 500, 600]))
    assert points[4].values["ma5"] == pytest.approx(12.0)
    assert points[5].values["ma5"] == pytest.approx(13.0)
    assert points[4].values["vol_ma5"] == pytest.approx(300.0)
    # Only gains: Wilder RSI is 100 once six changes exist (needs 7 bars).
    assert (
        points[5].values["rsi6"] is None
        and points[5].reasons["rsi6"] == ind.INSUFFICIENT_BARS
    )
    up = compute_indicators(_bars([10, 11, 12, 13, 14, 15, 16]))
    assert up[6].values["rsi6"] == pytest.approx(100.0)
    # One loss of 1 among six changes of +1: gain 5/6, loss 1/6 -> RSI 83.333333.
    mixed = compute_indicators(_bars([10, 11, 12, 13, 12, 13, 14]))
    assert mixed[6].values["rsi6"] == pytest.approx(100 * (5 / 6) / (6 / 6))


def test_kd_first_value_and_flat_range():
    # 9 bars, highs 11..19, lows 9..17, close 18 on the 9th: RSV = (18-9)/(19-9) = 90.
    bars = [
        IndicatorBar(day, c, c + 1, c - 1, c, 1000)
        for day, c in zip(_weekdays(date(2026, 3, 2), 9), range(10, 19))
    ]
    point = compute_indicators(bars)[8]
    k = 50 + (90 - 50) / 3
    assert point.values["kd_k"] == pytest.approx(k)
    assert point.values["kd_d"] == pytest.approx(50 + (k - 50) / 3)
    flat = compute_indicators(
        [
            IndicatorBar(day, 20, 20, 20, 20, 1000)
            for day in _weekdays(date(2026, 3, 2), 12)
        ]
    )
    assert flat[-1].values["kd_k"] == pytest.approx(50.0) and flat[-1].values[
        "kd_d"
    ] == pytest.approx(50.0)
    assert (
        flat[-1].values["rsi6"] is None
        and flat[-1].reasons["rsi6"] == ind.NO_PRICE_CHANGE
    )
    assert (
        flat[-1].values["boll_upper"] is None
        and flat[-1].reasons["boll_upper"] == ind.INSUFFICIENT_BARS
    )


@pytest.mark.parametrize("count", [0, 1, 4, 25, 33, 34, 119, 120])
def test_insufficient_bars_boundaries(count):
    points = compute_indicators(_bars(_walk(count)))
    assert len(points) == count
    if not count:
        return
    last = points[-1]
    for name, required in ind.REQUIRED_BARS.items():
        if count < required:
            assert (
                last.values[name] is None
                and last.reasons[name] == ind.INSUFFICIENT_BARS
            ), name
        else:
            assert last.values[name] is not None and name not in last.reasons, name
    assert ind.REQUIRED_BARS["macd_signal"] == 34 and ind.REQUIRED_BARS["rsi12"] == 13


def test_suspended_and_missing_days_are_excluded_not_filled():
    bars = _bars(_walk(60))
    # Session 30 is suspended (row kept, zero prices) and session 31 has no row at all.
    with_gap = (
        bars[:30]
        + [
            IndicatorBar(
                bars[30].trading_date, 0.0, 0.0, 0.0, 0.0, 0, is_suspended=True
            )
        ]
        + bars[32:]
    )
    points = compute_indicators(with_gap)
    contiguous = compute_indicators([b for b in with_gap if not b.is_suspended])
    gap_point = points[30]
    assert gap_point.values == {name: None for name in ind.FIELDS}
    assert gap_point.reasons == {name: ind.SUSPENDED for name in ind.FIELDS}
    assert gap_point.bar_count == 30
    usable_points = [p for p in points if p is not gap_point]
    assert [p.values for p in usable_points] == [p.values for p in contiguous]
    assert usable_points[-1].bar_count == 58


@pytest.mark.parametrize(
    "broken",
    [
        {"close": 0.0},
        {"close": float("nan")},
        {"high": float("inf")},
        {"low": -1.0},
        {"volume": -5},
        {"volume": None},
        {"high": 1.0},
        {"price_factor": 0.0},
    ],
)
def test_invalid_bar_is_excluded(broken):
    bars = _bars(_walk(30))
    fields = {
        k: getattr(bars[10], k)
        for k in (
            "trading_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "is_suspended",
            "price_factor",
        )
    }
    fields.update(broken)
    bars[10] = IndicatorBar(**fields)
    points = compute_indicators(bars)
    assert points[10].reasons == {name: ind.INVALID_BAR for name in ind.FIELDS}
    reference = compute_indicators(bars[:10] + bars[11:])
    assert points[-1].values == reference[-1].values


def test_corporate_action_factor_uses_as_of_basis():
    # A 2-for-1 split on day 25: raw prices halve; factor 0.5 from that date.
    raw = [100.0 + i for i in range(40)]
    days = _weekdays(date(2026, 4, 6), 40)
    bars = [
        IndicatorBar(
            d,
            c if i < 25 else c / 2,
            (c if i < 25 else c / 2) + 1,
            (c if i < 25 else c / 2) - 1,
            c if i < 25 else c / 2,
            1000,
            price_factor=1.0 if i < 25 else 0.5,
        )
        for i, (d, c) in enumerate(zip(days, raw))
    ]
    points = compute_indicators(bars)
    for i in (24, 25, 39):
        basis = [
            IndicatorBar(
                b.trading_date,
                b.open * bars[i].price_factor / b.price_factor,
                b.high * bars[i].price_factor / b.price_factor,
                b.low * bars[i].price_factor / b.price_factor,
                b.close * bars[i].price_factor / b.price_factor,
                b.volume,
            )
            for b in bars[: i + 1]
        ]
        expected = compute_indicators(basis)[-1].values
        for name in ind.FIELDS:
            if expected[name] is None:
                assert points[i].values[name] is None
            else:
                assert points[i].values[name] == pytest.approx(
                    expected[name], abs=1e-6
                ), (i, name)
    # MA5 just after the split is in post-split raw basis (about half the pre-split level).
    assert points[25].values["ma5"] == pytest.approx(sum(raw[21:26]) / 5 / 2)


def test_weekly_aggregation_across_month_and_year():
    # Thu/Fri in August, then a week spanning Aug 31 - Sep 4 with Sep 2 suspended.
    days = [
        date(2026, 8, 27),
        date(2026, 8, 28),
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 7),
    ]
    bars = [
        IndicatorBar(d, 0, 0, 0, 0, 0, is_suspended=True)
        if d == date(2026, 9, 2)
        else IndicatorBar(d, 10 + i, 12 + i, 9 + i, 11 + i, 100 * (i + 1))
        for i, d in enumerate(days)
    ]
    weeks = aggregate_weekly(bars)
    assert [(w.week_start, w.week_end, w.trading_days) for w in weeks] == [
        (date(2026, 8, 27), date(2026, 8, 28), 2),
        (date(2026, 8, 31), date(2026, 9, 4), 4),
        (date(2026, 9, 7), date(2026, 9, 7), 1),
    ]
    month_week = weeks[1]
    included = [
        b
        for b in bars
        if date(2026, 8, 31) <= b.trading_date <= date(2026, 9, 4)
        and not b.is_suspended
    ]
    assert month_week.open == included[0].open
    assert month_week.high == max(b.high for b in included)
    assert month_week.low == min(b.low for b in included)
    assert month_week.close == included[-1].close
    assert month_week.volume == sum(b.volume for b in included)
    year = aggregate_weekly(
        [
            IndicatorBar(date(2025, 12, 31), 5, 6, 4, 5, 1),
            IndicatorBar(date(2026, 1, 2), 6, 7, 5, 6, 2),
            IndicatorBar(date(2026, 1, 5), 7, 8, 6, 7, 3),
        ]
    )
    assert [(w.week_start, w.week_end) for w in year] == [
        (date(2025, 12, 31), date(2026, 1, 2)),
        (date(2026, 1, 5), date(2026, 1, 5)),
    ]
    assert (
        aggregate_weekly(
            [IndicatorBar(date(2026, 9, 9), 0, 0, 0, 0, 0, is_suspended=True)]
        )
        == []
    )


def test_weekly_indicators_recompute_on_weekly_series():
    daily = _bars(_walk(200))
    weeks = aggregate_weekly(daily)
    points = compute_indicators(w.calc for w in weeks)
    weekly_bars = [
        IndicatorBar(w.week_end, w.open, w.high, w.low, w.close, w.volume)
        for w in weeks
    ]
    assert_matches_reference(points, weekly_bars)
    assert points[4].values["ma5"] == pytest.approx(sum(w.close for w in weeks[:5]) / 5)


def test_weekly_split_week_uses_week_end_basis():
    days = _weekdays(
        date(2026, 5, 4), 10
    )  # two full weeks, split on the second Wednesday
    bars = []
    for i, d in enumerate(days):
        factor = 0.5 if i >= 7 else 1.0
        price = 100.0 * factor
        bars.append(
            IndicatorBar(
                d,
                price,
                price + 2 * factor,
                price - 2 * factor,
                price,
                1000,
                price_factor=factor,
            )
        )
    second = aggregate_weekly(bars)[1]
    assert (second.open, second.high, second.low, second.close) == (
        100.0,
        102.0,
        49.0,
        50.0,
    )
    assert (second.calc.open, second.calc.high, second.calc.low, second.calc.close) == (
        50.0,
        51.0,
        49.0,
        50.0,
    )


def test_since_limits_output_but_not_history():
    bars = _bars(_walk(150))
    bars[100] = IndicatorBar(bars[100].trading_date, 0, 0, 0, 0, 0, is_suspended=True)
    full = compute_indicators(bars)
    for since in (
        bars[0].trading_date,
        bars[99].trading_date,
        bars[100].trading_date,
        bars[-1].trading_date,
        bars[-1].trading_date + timedelta(days=1),
    ):
        tail = compute_indicators(bars, since=since)
        expected = [p for p in full if p.trading_date >= since]
        assert [(p.trading_date, p.bar_count, p.values, p.reasons) for p in tail] == [
            (p.trading_date, p.bar_count, p.values, p.reasons) for p in expected
        ]
