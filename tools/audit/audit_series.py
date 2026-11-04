"""Per-instrument series of the audit: indicators and the window inputs (Issue #391).

Written from docs/spec/ (indicators.md, breakout_pullback.md breakout_v1 法人／融資,
hot_group.md, candidate_score.md candidate_score_v1), not from the product code: plain loops over the stored
bars, one common price basis (each bar divided by its own factor) and
price-unit values mapped back to T by the factor at T.
"""

from __future__ import annotations

import bisect
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from audit_lib import Action, factors_by_bar, finite, load_actions, positive

FIELDS = (
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ma120",
    "macd_dif",
    "macd_signal",
    "macd_hist",
    "rsi6",
    "rsi12",
    "kd_k",
    "kd_d",
    "boll_mid",
    "boll_upper",
    "boll_lower",
    "vol_ma5",
    "vol_ma20",
)
PRICE_FIELDS = {
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ma120",
    "macd_dif",
    "macd_signal",
    "macd_hist",
    "boll_mid",
    "boll_upper",
    "boll_lower",
}
SYNTHETIC_SOURCES = {"twse_index"}


@dataclass
class Bar:
    day: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    suspended: bool
    synthetic: bool
    source: str
    collected_at: str = ""


def usable(bar: Bar, factor: float) -> bool:
    """docs/spec/indicators.md: not suspended, OHLC finite positive and consistent, volume >= 0."""

    if bar.suspended or not positive(factor):
        return False
    prices = (bar.open, bar.high, bar.low, bar.close)
    if not all(positive(value) for value in prices):
        return False
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        return False
    return finite(bar.volume) and bar.volume >= 0


def indicators(
    bars: list[Bar], factors: list[float]
) -> list[tuple[int, dict[str, float | None]]]:
    """(bar_count, values) for every bar, unusable bars all-null (docs/spec/indicators.md)."""

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []
    synthetic: list[bool] = []
    out: list[tuple[int, dict[str, float | None]]] = []
    ema12 = ema26 = signal = None
    difs: list[float] = []
    gains = {6: 0.0, 12: 0.0}
    losses = {6: 0.0, 12: 0.0}
    k_value = d_value = 50.0
    synthetic_seen = False
    for bar, factor in zip(bars, factors):
        if not usable(bar, factor):
            out.append((len(closes), {name: None for name in FIELDS}))
            continue
        closes.append(bar.close / factor)
        highs.append(bar.high / factor)
        lows.append(bar.low / factor)
        volumes.append(float(bar.volume))
        synthetic.append(bar.synthetic)
        synthetic_seen = synthetic_seen or bar.synthetic
        n = len(closes)
        values: dict[str, float | None] = {}
        for window in (5, 10, 20, 60, 120):
            values[f"ma{window}"] = (
                sum(closes[-window:]) / window if n >= window else None
            )
        # EMA seeded with the simple mean of the first n closes.
        if n == 12:
            ema12 = sum(closes) / 12
        elif n > 12:
            ema12 = ema12 + 2 / 13 * (closes[-1] - ema12)
        if n == 26:
            ema26 = sum(closes) / 26
        elif n > 26:
            ema26 = ema26 + 2 / 27 * (closes[-1] - ema26)
        dif = ema12 - ema26 if n >= 26 else None
        if dif is not None:
            difs.append(dif)
            if len(difs) == 9:
                signal = sum(difs) / 9
            elif len(difs) > 9:
                signal = signal + 2 / 10 * (dif - signal)
        values["macd_dif"] = dif
        values["macd_signal"] = signal if len(difs) >= 9 else None
        values["macd_hist"] = dif - signal if len(difs) >= 9 else None
        # Wilder RSI over the changes between usable closes.
        if n >= 2:
            change = closes[-1] - closes[-2]
            for window in (6, 12):
                changes = n - 1
                if changes <= window:
                    gains[window] += max(change, 0.0)
                    losses[window] += max(-change, 0.0)
                    if changes == window:
                        gains[window] /= window
                        losses[window] /= window
                else:
                    gains[window] = (
                        gains[window] * (window - 1) + max(change, 0.0)
                    ) / window
                    losses[window] = (
                        losses[window] * (window - 1) + max(-change, 0.0)
                    ) / window
        for window in (6, 12):
            total = gains[window] + losses[window]
            values[f"rsi{window}"] = (
                100 * gains[window] / total if n >= window + 1 and total > 0 else None
            )
        if n >= 9:
            h9, l9 = max(highs[-9:]), min(lows[-9:])
            rsv = 50.0 if h9 == l9 else 100 * (closes[-1] - l9) / (h9 - l9)
            k_value = (2 * k_value + rsv) / 3
            d_value = (2 * d_value + k_value) / 3
        kd_ok = n >= 9 and not synthetic_seen
        values["kd_k"] = k_value if kd_ok else None
        values["kd_d"] = d_value if kd_ok else None
        if n >= 20:
            window = closes[-20:]
            middle = sum(window) / 20
            deviation = math.sqrt(sum((value - middle) ** 2 for value in window) / 20)
            values["boll_mid"], values["boll_upper"], values["boll_lower"] = (
                middle,
                middle + 2 * deviation,
                middle - 2 * deviation,
            )
        else:
            values["boll_mid"] = values["boll_upper"] = values["boll_lower"] = None
        for window in (5, 20):
            enough = n >= window and not any(synthetic[-window:])
            values[f"vol_ma{window}"] = (
                sum(volumes[-window:]) / window if enough else None
            )
        for name in PRICE_FIELDS:
            if values[name] is not None:
                values[name] *= factor
        out.append((n, values))
    return out


@dataclass
class Chip:
    foreign: float | None
    trust: float | None
    dealer: float | None
    margin: float | None
    source: str
    raw_payload_id: int | None
    # Latest collected_at of the row (and of its source groups, #395).
    collected_at: str = ""
    # The row cites a capture later than the first of its day: a later
    # official file revised it (#387) after the first derived rows were written.
    revised: bool = False


@dataclass
class Series:
    """One instrument's stored inputs with the windows of the strategies and scores."""

    instrument_id: int
    exchange: str
    symbol: str
    instrument_type: str
    status: str
    bars: list[Bar]
    factors: list[float]
    chips: dict[str, Chip]
    actions: list[Action]
    days: list[str] = field(init=False)
    active_days: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.days = [bar.day for bar in self.bars]
        self.index = {day: i for i, day in enumerate(self.days)}
        self.active_days = [bar.day for bar in self.bars if not bar.suspended]

    def effective(self, day: str, window: int) -> list[str]:
        """The last ``window`` non-suspended bar dates on or before ``day``."""

        end = bisect.bisect_right(self.active_days, day)
        return self.active_days[max(0, end - window) : end]

    def flow(
        self, day: str, window: int, *, absent_evidence=None, require_last: bool = False
    ) -> tuple[float, float, list[str]] | None:
        """(sum of foreign+trust+dealer over the last ``window`` of 20 sessions, sum of their 20 volumes, zero-filled days)."""

        dates = self.effective(day, 20)
        if len(dates) != 20 or (require_last and dates[-1] != day):
            return None
        volumes = [self.bars[self.index[d]].volume for d in dates]
        if any(not positive(v) for v in volumes):
            return None
        total = 0.0
        zero_filled: list[str] = []
        for d in dates[-window:]:
            chip = self.chips.get(d)
            parts = (
                (chip.foreign, chip.trust, chip.dealer) if chip else (None, None, None)
            )
            if all(finite(p) for p in parts):
                total += sum(parts)
                continue
            if absent_evidence is None:
                return None
            from_official = chip is not None and chip.source.split("+")[0] in (
                "twse_t86",
                "tpex_3insti",
            )
            if (
                from_official
                or any(p is not None for p in parts)
                or not absent_evidence(self.exchange, d)
            ):
                return None
            zero_filled.append(d)
        return total, sum(volumes), zero_filled

    def changed(
        self,
        day: str,
        window: int,
        after: str | None = None,
        *,
        prices: bool = False,
        chip_window: int | None = None,
    ) -> bool:
        """Whether the inputs of the last ``window`` sessions up to ``day`` changed later.

        Only what the value reads counts (#418 review): the chip rows of the
        window (the last ``chip_window`` of them), its bars (volumes) when ``after`` is known, and with ``prices``
        the corporate actions dated inside the window, the only ones that move
        a price ratio between two of its bars (``dates[0] < action <= day``).
        ``after`` is the row's stored write time: an input collected after it.
        Without it (group scores have no write time): a chip row a later
        capture revised, or an action collected after ``day`` (a backfill).
        """

        dates = self.effective(day, window)
        if not dates:
            return False
        chip_dates = set(dates[-chip_window:] if chip_window else dates)
        for d in dates:
            chip = self.chips.get(d) if d in chip_dates else None
            if chip is not None and (
                chip.collected_at > after if after else chip.revised
            ):
                return True
            if after and self.bars[self.index[d]].collected_at > after:
                return True
        if not prices:
            return False
        for action in self.actions:
            if not (dates[0] < action.action_date <= day) or not action.collected_at:
                continue
            if action.collected_at > after if after else action.collected_at[:10] > day:
                return True
        return False

    def margin_change(self, day: str, *, require_last: bool = False) -> float | None:
        """5-day margin balance change ratio: the 6 sessions including T all need a chip row."""

        dates = self.effective(day, 6)
        if len(dates) < 6 or (require_last and dates[-1] != day):
            return None
        chips = [self.chips.get(d) for d in dates]
        if any(chip is None for chip in chips):
            return None
        first, last = chips[0].margin, chips[-1].margin
        if first in (None, 0) or last is None:
            return None
        return (last - first) / abs(first)

    def normalized_close(self, at: int, to: int) -> float:
        return self.bars[at].close * self.factors[to] / self.factors[at]

    def price_return(self, day: str, window: int) -> float | None:
        """Close return over ``window`` non-suspended bars up to ``day``, in ``day``'s basis."""

        if day not in self.index:
            return None
        to = self.index[day]
        end = bisect.bisect_right(self.active_days, day)
        if end < window + 1:
            return None
        current = self.normalized_close(self.index[self.active_days[end - 1]], to)
        previous = self.normalized_close(
            self.index[self.active_days[end - window - 1]], to
        )
        return current / previous - 1 if previous else None

    def prior_20(self, day: str) -> list[int]:
        """Indexes of the up-to-20 bars before ``day`` (suspended ones included)."""

        end = bisect.bisect_left(self.days, day)
        return list(range(max(0, end - 20), end))


def load_series(
    con: sqlite3.Connection,
    row: tuple,
    chip_columns: set[str],
    first_captures: set[int] | None = None,
) -> Series:
    instrument_id, exchange, symbol, instrument_type, status = row
    bars = [
        Bar(
            day,
            o,
            h,
            lo,
            c,
            v,
            bool(s),
            src in SYNTHETIC_SOURCES or reason == "synthetic_index",
            src,
            str(collected or ""),
        )
        for day, o, h, lo, c, v, s, src, reason, collected in con.execute(
            "select trading_date, open, high, low, close, volume, is_suspended, source, turnover_reason, collected_at"
            " from market_bars where instrument_id=? order by trading_date",
            (instrument_id,),
        )
    ]
    actions = load_actions(con, instrument_id)
    as_tuples = [(bar.day, bar.open, bar.high, bar.low, bar.close) for bar in bars]
    factors = factors_by_bar(as_tuples, actions) if actions else [1.0] * len(bars)
    grouped = {
        "institutional_raw_payload_id",
        "institutional_collected_at",
        "margin_raw_payload_id",
        "margin_collected_at",
    } <= chip_columns
    extra = (
        ", institutional_raw_payload_id, margin_raw_payload_id, institutional_collected_at, margin_collected_at"
        if grouped
        else ", null, null, null, null"
    )
    chips = {}
    for day, f, t, d, m, src, raw, collected, raw_i, raw_m, col_i, col_m in con.execute(
        "select trading_date, foreign_buy, trust_buy, dealer_buy, margin_balance, source, raw_payload_id, collected_at"
        + extra
        + " from chip_snapshots where instrument_id=?",
        (instrument_id,),
    ):
        cited = [x for x in (raw, raw_i, raw_m) if x is not None]
        revised = first_captures is not None and any(
            x not in first_captures for x in cited
        )
        latest = (
            max(str(x) for x in (collected, col_i, col_m) if x is not None)
            if any(x is not None for x in (collected, col_i, col_m))
            else ""
        )
        chips[day] = Chip(f, t, d, m, src or "", raw, latest, revised)
    return Series(
        instrument_id,
        exchange,
        symbol,
        instrument_type,
        status,
        bars,
        factors,
        chips,
        actions,
    )


def evidence_lookup(con: sqlite3.Connection) -> dict[tuple[str, str], int]:
    """(exchange, day) -> raw id proving the official institutional file was received (hot_group 1.1.0)."""

    endpoints = {
        "TWSE": "https://www.twse.com.tw/rwd/zh/fund/T86",
        "TPEx": "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
    }
    sources = {"TWSE": "twse_t86", "TPEx": "tpex_3insti"}
    found: dict[tuple[str, str], int] = {}
    query = (
        "select i.exchange, c.trading_date, c.source, r.id, r.endpoint, r.data_as_of from chip_snapshots c"
        " join instruments i on i.id=c.instrument_id join raw_payloads r on r.id=c.raw_payload_id"
        " group by i.exchange, c.trading_date, c.source, r.id"
    )
    for exchange, day, source, raw_id, endpoint, data_as_of in con.execute(query):
        if exchange not in sources or (source or "").split("+")[0] != sources[exchange]:
            continue
        if (endpoint or "").split("?", 1)[0] != endpoints[
            exchange
        ] or data_as_of != day:
            continue
        key = (exchange, day)
        found[key] = min(raw_id, found.get(key, raw_id))
    return found


def as_number(value: Any) -> float | None:
    return float(value) if finite(value) else None
