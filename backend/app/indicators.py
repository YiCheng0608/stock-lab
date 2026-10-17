"""Pure technical indicator formulas for the stored daily batch and the bars API.

No database, network or filesystem access.  Callers pass bars in trading-date
order; each bar may carry the cumulative corporate-action factor effective on
its date (``worker.pipeline._action_factor_by_bar`` semantics), so every value
at date T is expressed in T's raw price basis and lines up with T's raw candle.
Formulas, parameters and the "not enough bars" rules are documented in
docs/V1_SPEC.md (技術指標); change them only together with INDICATOR_VERSION.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any


INDICATOR_VERSION = "indicators/v1"
PRICE_BASIS = "as_of_date_raw_basis"

MA_WINDOWS = (5, 10, 20, 60, 120)
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RSI_WINDOWS = (6, 12)
KD_PERIOD, KD_K_SMOOTH, KD_D_SMOOTH = 9, 3, 3
KD_INITIAL = 50.0
BOLLINGER_PERIOD, BOLLINGER_WIDTH = 20, 2.0
VOLUME_MA_WINDOWS = (5, 20)

PARAMETERS: dict[str, Any] = {
    "ma": list(MA_WINDOWS),
    "macd": {"fast": MACD_FAST, "slow": MACD_SLOW, "signal": MACD_SIGNAL},
    "rsi": list(RSI_WINDOWS),
    "kd": {
        "period": KD_PERIOD,
        "k_smooth": KD_K_SMOOTH,
        "d_smooth": KD_D_SMOOTH,
        "initial": KD_INITIAL,
    },
    "bollinger": {"period": BOLLINGER_PERIOD, "width": BOLLINGER_WIDTH},
    "volume_ma": list(VOLUME_MA_WINDOWS),
}

# Usable bars needed (including T) before a field has a value.
REQUIRED_BARS: dict[str, int] = {
    **{f"ma{window}": window for window in MA_WINDOWS},
    "macd_dif": MACD_SLOW,
    "macd_signal": MACD_SLOW + MACD_SIGNAL - 1,
    "macd_hist": MACD_SLOW + MACD_SIGNAL - 1,
    **{f"rsi{window}": window + 1 for window in RSI_WINDOWS},
    "kd_k": KD_PERIOD,
    "kd_d": KD_PERIOD,
    "boll_mid": BOLLINGER_PERIOD,
    "boll_upper": BOLLINGER_PERIOD,
    "boll_lower": BOLLINGER_PERIOD,
    **{f"vol_ma{window}": window for window in VOLUME_MA_WINDOWS},
}
FIELDS = tuple(REQUIRED_BARS)
# Fields measured in price units scale with the as-of basis; RSI and KD are ratios.
_PRICE_FIELDS = frozenset(
    {f"ma{window}" for window in MA_WINDOWS}
    | {"macd_dif", "macd_signal", "macd_hist", "boll_mid", "boll_upper", "boll_lower"}
)

# Reason codes for a null field.
INSUFFICIENT_BARS = "insufficient_bars"
SUSPENDED = "suspended"
INVALID_BAR = "invalid_bar"
NO_PRICE_CHANGE = "no_price_change"

_DIGITS = 6


@dataclass(frozen=True)
class IndicatorBar:
    trading_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    is_suspended: bool = False
    price_factor: float = 1.0


@dataclass
class IndicatorPoint:
    trading_date: date
    bar_count: int
    values: dict[str, float | None] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)


def _finite_positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def bar_problem(bar: IndicatorBar) -> str | None:
    """Why a bar cannot enter the series, or None when it is usable."""
    if bar.is_suspended:
        return SUSPENDED
    prices = (bar.open, bar.high, bar.low, bar.close)
    if not all(_finite_positive(value) for value in prices) or not _finite_positive(
        bar.price_factor
    ):
        return INVALID_BAR
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        return INVALID_BAR
    volume = bar.volume
    if (
        not isinstance(volume, (int, float))
        or isinstance(volume, bool)
        or not math.isfinite(volume)
        or volume < 0
    ):
        return INVALID_BAR
    return None


def _sma(values: Sequence[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        if index >= window - 1:
            result[index] = total / window
    return result


def _ema(values: Sequence[float | None], window: int) -> list[float | None]:
    """EMA with alpha 2/(n+1), seeded by the SMA of the first n defined values."""
    result: list[float | None] = [None] * len(values)
    alpha = 2.0 / (window + 1)
    seed: list[float] = []
    previous: float | None = None
    for index, value in enumerate(values):
        if value is None:
            continue
        if previous is None:
            seed.append(value)
            if len(seed) == window:
                previous = sum(seed) / window
                result[index] = previous
            continue
        previous = alpha * value + (1 - alpha) * previous
        result[index] = previous
    return result


def _rsi(
    closes: Sequence[float], window: int
) -> tuple[list[float | None], list[str | None]]:
    """Wilder RSI: first averages are simple means of n changes, then (prev*(n-1)+x)/n."""
    values: list[float | None] = [None] * len(closes)
    reasons: list[str | None] = [INSUFFICIENT_BARS] * len(closes)
    gain = loss = 0.0
    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]
        up, down = max(change, 0.0), max(-change, 0.0)
        if index <= window:
            gain += up
            loss += down
            if index < window:
                continue
            gain /= window
            loss /= window
        else:
            gain = (gain * (window - 1) + up) / window
            loss = (loss * (window - 1) + down) / window
        if gain + loss > 0:
            values[index] = 100.0 * gain / (gain + loss)
            reasons[index] = None
        else:
            reasons[index] = NO_PRICE_CHANGE
    return values, reasons


def _kd(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> tuple[list[float | None], list[float | None]]:
    """Taiwan KD: RSV over 9 bars, K = K'+(RSV-K')/3, D = D'+(K-D')/3, K'=D'=50 at start.

    A flat 9-bar range (highest == lowest) has no defined RSV; it is taken as 50.
    """
    k_values: list[float | None] = [None] * len(closes)
    d_values: list[float | None] = [None] * len(closes)
    k = d = KD_INITIAL
    for index in range(KD_PERIOD - 1, len(closes)):
        start = index - KD_PERIOD + 1
        highest = max(highs[start : index + 1])
        lowest = min(lows[start : index + 1])
        rsv = (
            50.0
            if highest == lowest
            else 100.0 * (closes[index] - lowest) / (highest - lowest)
        )
        k = k + (rsv - k) / KD_K_SMOOTH
        d = d + (k - d) / KD_D_SMOOTH
        k_values[index] = k
        d_values[index] = d
    return k_values, d_values


def _series(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    first_output: int,
) -> tuple[dict[str, list[float | None]], dict[str, list[str | None]]]:
    """Full series; Bollinger bands only from ``first_output`` (no recursion needed)."""
    columns: dict[str, list[float | None]] = {}
    special: dict[str, list[str | None]] = {}
    for window in MA_WINDOWS:
        columns[f"ma{window}"] = _sma(closes, window)
    fast = _ema(closes, MACD_FAST)
    slow = _ema(closes, MACD_SLOW)
    dif = [
        a - b if a is not None and b is not None else None for a, b in zip(fast, slow)
    ]
    signal = _ema(dif, MACD_SIGNAL)
    columns["macd_dif"] = dif
    columns["macd_signal"] = signal
    columns["macd_hist"] = [
        a - b if a is not None and b is not None else None for a, b in zip(dif, signal)
    ]
    for window in RSI_WINDOWS:
        columns[f"rsi{window}"], special[f"rsi{window}"] = _rsi(closes, window)
    columns["kd_k"], columns["kd_d"] = _kd(highs, lows, closes)
    mid = _sma(closes, BOLLINGER_PERIOD)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for index in range(first_output, len(closes)):
        middle = mid[index]
        if middle is None:
            continue
        window = closes[index - BOLLINGER_PERIOD + 1 : index + 1]
        deviation = math.sqrt(
            sum((value - middle) ** 2 for value in window) / BOLLINGER_PERIOD
        )
        upper[index] = middle + BOLLINGER_WIDTH * deviation
        lower[index] = middle - BOLLINGER_WIDTH * deviation
    columns["boll_mid"], columns["boll_upper"], columns["boll_lower"] = (
        mid,
        upper,
        lower,
    )
    for window in VOLUME_MA_WINDOWS:
        columns[f"vol_ma{window}"] = _sma(volumes, window)
    return columns, special


def compute_indicators(
    bars: Iterable[IndicatorBar], *, since: date | None = None
) -> list[IndicatorPoint]:
    """One point per input bar dated ``since`` or later (all bars by default), in input order.

    Every bar still enters the recursions; ``since`` only limits the output.
    Suspended or invalid bars are excluded from every window (no filling) and
    their own point is all-null with that reason; windows therefore count the
    instrument's usable bars, not calendar or exchange sessions.
    """
    items = list(bars)
    problems = [bar_problem(bar) for bar in items]
    usable = [bar for bar, problem in zip(items, problems) if problem is None]
    # Divide by each bar's own factor to reach one common basis; multiplying a
    # price-unit value by the factor at T maps it back to T's raw basis.
    highs = [bar.high / bar.price_factor for bar in usable]
    lows = [bar.low / bar.price_factor for bar in usable]
    closes = [bar.close / bar.price_factor for bar in usable]
    volumes = [float(bar.volume) for bar in usable]
    first_output = sum(
        1 for bar in usable if since is not None and bar.trading_date < since
    )
    columns, special = _series(highs, lows, closes, volumes, first_output)
    points: list[IndicatorPoint] = []
    position = -1
    for bar, problem in zip(items, problems):
        if since is not None and bar.trading_date < since:
            position += problem is None
            continue
        if problem is not None:
            points.append(
                IndicatorPoint(
                    bar.trading_date,
                    position + 1,
                    {name: None for name in FIELDS},
                    {name: problem for name in FIELDS},
                )
            )
            continue
        position += 1
        point = IndicatorPoint(bar.trading_date, position + 1)
        for name in FIELDS:
            value = columns[name][position]
            if value is None:
                point.values[name] = None
                reason = special[name][position] if name in special else None
                point.reasons[name] = reason or INSUFFICIENT_BARS
                continue
            if name in _PRICE_FIELDS:
                value *= bar.price_factor
            point.values[name] = round(value, _DIGITS)
        points.append(point)
    return points


@dataclass(frozen=True)
class WeeklyBar:
    week_start: date
    week_end: date
    trading_days: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    # The same week in its last day's raw basis, for indicator input.
    calc: IndicatorBar


def aggregate_weekly(bars: Iterable[IndicatorBar]) -> list[WeeklyBar]:
    """Aggregate usable daily bars by ISO week (Monday start).

    open = first day's open, high = max high, low = min low, close = last
    day's close, volume = sum.  Suspended or invalid days are left out; a week
    with no usable day has no bar.
    """
    weeks: dict[tuple[int, int], list[IndicatorBar]] = {}
    for bar in bars:
        if bar_problem(bar) is None:
            weeks.setdefault(bar.trading_date.isocalendar()[:2], []).append(bar)
    result: list[WeeklyBar] = []
    for key in sorted(weeks):
        days = sorted(weeks[key], key=lambda item: item.trading_date)
        last = days[-1]
        scale = [last.price_factor / day.price_factor for day in days]
        calc = IndicatorBar(
            trading_date=last.trading_date,
            open=days[0].open * scale[0],
            high=max(day.high * ratio for day, ratio in zip(days, scale)),
            low=min(day.low * ratio for day, ratio in zip(days, scale)),
            close=last.close,
            volume=sum(float(day.volume) for day in days),
            price_factor=last.price_factor,
        )
        result.append(
            WeeklyBar(
                week_start=days[0].trading_date,
                week_end=last.trading_date,
                trading_days=len(days),
                open=days[0].open,
                high=max(day.high for day in days),
                low=min(day.low for day in days),
                close=last.close,
                volume=calc.volume,
                calc=calc,
            )
        )
    return result
