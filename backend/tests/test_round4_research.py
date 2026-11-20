"""tools/research/round4_research.py: round 4 (C1～C4, each S1 with one layer changed, #878).

The registered numbers are asserted as written in docs/spec/evidence.md
(第四輪：C1～C4).  Each hypothesis's layer is tested by hand (AC-2): on
hand-made bars for C2 and C4, on hand-made returns for C1's strength, and on a
small research copy for C1's members (``REMAP_2023``, the whole population),
C3's margin classes against the product's ``margin_lists``／``margin_zero_base``
and the runs; the gate (AC-3) follows ``explore_research``.  S1 through the
hooks against ``trade_research`` version 1 is in test_trade_research.py.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from array import array
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import (
    Base,
    ChipSnapshot,
    Instrument,
    MarginList,
    MarketBar,
    MonthlyRevenue,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/878#issuecomment-1"


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
er = _tool("exit_research")
ex = _tool("explore_research")
features = _tool("feature_evidence")
tr = _tool("trade_research")
im = _tool("industry_members")
ms = _tool("mainstream_research")
tool = _tool("round4_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAN = float("nan")


# --- the registration, as written ------------------------------------------------


def test_the_hypotheses_are_s1_with_one_layer_changed():
    assert list(tool.HYPOTHESES) == ["C1", "C2", "C3", "C4"]
    s1 = {key: value for key, value in tr.HYPOTHESES["S1"].items() if key != "label"}
    assert tool.S1 == s1
    for name, spec in tool.HYPOTHESES.items():
        rest = {k: v for k, v in spec.items() if k not in ("label", "change")}
        assert rest == s1, name  # every other layer is S1's, R and the target too
    assert {n: s["change"] for n, s in tool.HYPOTHESES.items()} == {
        "C1": "select",
        "C2": "first_key",
        "C3": "select",
        "C4": "stop",
    }
    assert "C1" not in tr.HYPOTHESES and list(tr.HYPOTHESES) == [
        "S1",
        "S2",
        "S3",
        "R1",
        "R2",
    ]


def test_the_parameters_are_the_registration():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (1, 4, 4, 19)
    assert (tool.DESIGN, tool.REGISTRATION_COMMIT) == ("878", "f39d39ea")
    assert ex.validation_min_t(tool.CUMULATIVE) == 2.0  # 19 ≤ 20
    assert tool.RETURN_WINDOWS == (20, 60) and tool.INDEX_CLOSES == 61
    assert (tool.GROUP_COUNT, tool.MIN_MEMBERS) == (5, 5)
    assert tool.BOTH_WINDOW == 5
    assert (tool.BAND_BARS, tool.BAND_BINS, tool.BAND_BUFFER_ATR) == (60, 24, 0.5)
    assert tool.BAND_CLAMP_ATR == (1.0, 3.0)
    assert tool.HYPOTHESES["C1"]["start"] == ("session", date(2014, 12, 1), 20)


def test_the_margin_threshold_is_the_products():
    from app.strategies.base import COMMON_CONFIRMATIONS

    margin = COMMON_CONFIRMATIONS["margin_financing"]
    assert margin["maximum_balance_change_ratio"] == tool.MARGIN_MAX == 0.05
    assert margin["operator"] == "lte"  # > 0.05 is excluded, ≤ 0.05 kept


def test_the_definitions_hash_covers_the_layers_and_the_members(monkeypatch):
    before = tool.definitions_sha256()
    for module, name, value in (
        (tool, "BAND_BINS", 25),
        (tool, "MARGIN_MAX", 0.06),
        (ms, "MEMBERS_SHA256", "0" * 64),
        (tr, "SEGMENTS", {}),
    ):
        with monkeypatch.context() as m:
            m.setattr(module, name, value)
            assert tool.definitions_sha256() != before, name
    assert tool.definitions_sha256() == before


# --- hand-made bars -----------------------------------------------------------------

D0 = date(2020, 1, 6)


def series(
    highs, lows, closes=None, volumes=None, suspended=(), chips=None, iid=1
) -> lib.Series:
    count = len(highs)
    closes = (
        closes if closes is not None else [(h + low) / 2 for h, low in zip(highs, lows)]
    )
    volumes = volumes if volumes is not None else [1000.0] * count
    item = lib.Series(iid)
    for k in range(count):
        day = D0 + timedelta(days=k)
        item.position[day] = k
        item.dates.append(day)
        item.session.append(k)
        item.open.append(closes[k])
        item.high.append(highs[k])
        item.low.append(lows[k])
        item.close.append(closes[k])
        item.volume.append(float(volumes[k]))
        item.scale.append(1.0)
    item.suspended.append(0)
    for k in range(count):
        item.suspended.append(item.suspended[-1] + (1 if k in suspended else 0))
    item.chips = {name: array("d", [NAN]) * count for name in lib.CHIP_FIELDS}
    for name, values in (chips or {}).items():
        for k, value in enumerate(values):
            item.chips[name][k] = NAN if value is None else value
    return item


# --- C2 土洋同買 (AC-2) ------------------------------------------------------------


def chips_item(foreign, trust):
    count = len(foreign)
    return series(
        [11.0] * count,
        [9.0] * count,
        chips={"foreign_buy": foreign, "trust_buy": trust},
    )


def test_c2_counts_the_bars_both_bought_on_the_same_day():
    # only one side buying: 0, whichever side
    assert tool.both_buy_days(chips_item([5, 5, 5, 5, 5], [-1, -1, -1, -1, -1]), 4) == 0
    assert tool.both_buy_days(chips_item([-1, 0, -1, -1, -1], [5] * 5), 4) == 0
    # both on the same day: days 1 and 3 (0 is not a buy)
    item = chips_item([0, 5, -2, 7, 3], [4, 6, 8, 1, -1])
    assert tool.both_buy_days(item, 4) == 2.0
    # each side bought 2 days, never the same day: 0, not min(2, 2)
    assert (
        tool.both_buy_days(chips_item([1, 1, -1, -1, -1], [-1, -1, 1, 1, -1]), 4) == 0
    )
    # the window is at − 4 … at: the older bars do not count
    item = chips_item([9, 9, 1, 1, 1, 1, 1], [9, 9, 1, 1, 1, 1, -1])
    assert tool.both_buy_days(item, 6) == 4.0
    assert tool.both_buy_days(item, 3) is None  # fewer than five bars


def test_c2_a_missing_figure_in_the_window_is_missing_not_zero():
    assert tool.both_buy_days(chips_item([1, None, 1, 1, 1], [1] * 5), 4) is None
    assert tool.both_buy_days(chips_item([1] * 5, [1, 1, 1, None, 1]), 4) is None
    # a row with the three institutional figures null (a Saturday make-up day,
    # #864): C2 and S1's trust_buy_days are both missing, last in the ranking
    item = chips_item([1, 1, 1, 1, None], [1, 1, 1, 1, None])
    assert tool.both_buy_days(item, 4) is None
    assert features.trust_buy_days(item, 4) is None
    hooks = tr.Hooks(first_key=("both_buy_days", tool.both_buy_days))
    keys, functions = tr.score_keys(hooks)
    assert keys == ("both_buy_days", "institutional_flow_20")
    assert functions["both_buy_days"] is tool.both_buy_days
    # a missing first key goes after every present one, then the second key
    present = tr.pr.ranking_key(
        {"both_buy_days": 0.0, "institutional_flow_20": None}, keys, "f"
    )
    missing = tr.pr.ranking_key(
        {"both_buy_days": None, "institutional_flow_20": 9.0}, keys, "0"
    )
    assert present < missing


# --- C4 成交量價位帶停損 (AC-2) ------------------------------------------------------


def band_bars(extra: dict[int, tuple[float, float, float]], close: float = 108.0):
    """60 bars: bar 0 spans [100, 110] with no volume (the range), the rest
    are given as k -> (high, low, volume) or flat at 105 with no volume."""

    highs, lows, volumes = [110.0], [100.0], [0.0]
    for k in range(1, 60):
        high, low, volume = extra.get(k, (105.0, 105.0, 0.0))
        highs.append(high)
        lows.append(low)
        volumes.append(volume)
    closes = [105.0] * 59 + [close]
    return series(highs, lows, closes, volumes)


EDGE = 10.0 / 24  # the bin width on [100, 110]


def test_c4_a_bar_with_high_equal_low_gives_its_volume_to_its_bin():
    item = band_bars({5: (102.0, 102.0, 900.0), 6: (101.0, 101.0, 300.0)})
    band = tool.volume_band(item, 59)
    k = int((102.0 - 100.0) / EDGE)  # 4: [101.667, 102.083)
    assert band.low == pytest.approx(100.0 + k * EDGE)
    assert band.high == pytest.approx(100.0 + (k + 1) * EDGE)
    assert band.volume == 900.0 and band.fallback is None


def test_c4_a_price_on_a_grid_line_goes_to_the_upper_bin_and_the_top_to_the_last():
    # 105 is the edge of bins 11 and 12: bin 12 takes it
    band = tool.volume_band(band_bars({5: (105.0, 105.0, 500.0)}), 59)
    assert band.low == pytest.approx(105.0) and band.volume == 500.0
    # 110 (the highest high) goes to the top bin, 23; with the close at the
    # top every bin is a candidate
    item = band_bars({5: (110.0, 110.0, 9000.0), 6: (105.0, 105.0, 10.0)}, close=110.0)
    band = tool.volume_band(item, 59)
    assert band.low == pytest.approx(100.0 + 23 * EDGE) and band.high == 110.0
    assert band.volume == 9000.0
    # equal volumes: the higher bin
    item = band_bars({5: (101.0, 101.0, 500.0), 6: (103.0, 103.0, 500.0)})
    assert tool.volume_band(item, 59).low == pytest.approx(100.0 + 7 * EDGE)


def test_c4_volume_spreads_over_the_range_by_overlap():
    # [100.2, 101.2] with 1200: bin 0 [100, 100.417) takes 0.217, bin 1 the
    # whole 0.417, bin 2 [100.833, 101.25) the 0.367 to 101.2 (of 1.0)
    item = band_bars({3: (101.2, 100.2, 1200.0), 4: (103.0, 103.0, 450.0)})
    band = tool.volume_band(item, 59)
    assert band.low == pytest.approx(100.0 + EDGE)  # bin 1: 1200 × 0.4167 = 500
    assert band.volume == pytest.approx(1200.0 * EDGE / 1.0)
    # with 600 on 103 (bin 7) that one is denser than bin 1's 500
    item = band_bars({3: (101.2, 100.2, 1200.0), 4: (103.0, 103.0, 600.0)})
    assert tool.volume_band(item, 59).low == pytest.approx(100.0 + 7 * EDGE)


def test_c4_only_bins_under_the_close_count_and_none_falls_back():
    # most volume above the close (bin 20); the candidates are the bins with an
    # upper edge ≤ 104 (bins 0..8): bin 3 has the rest
    item = band_bars({4: (108.6, 108.6, 9000.0), 5: (101.5, 101.5, 10.0)}, close=104.0)
    band = tool.volume_band(item, 59)
    assert band.low == pytest.approx(100.0 + 3 * EDGE) and band.volume == 10.0
    # T's close in the lowest bin: no bin has its upper edge at or below it
    item = band_bars({5: (101.0, 101.0, 10.0)}, close=100.2)
    assert tool.volume_band(item, 59).fallback == tool.NO_CANDIDATE


def test_c4_fewer_than_60_bars_or_a_bar_without_high_low_falls_back():
    item = band_bars({})
    assert tool.volume_band(item, 58).fallback == tool.SHORT  # 59 bars to T
    halted = band_bars({})
    halted.high[30], halted.low[30] = NAN, NAN  # a suspended bar, loaded as NaN
    halted.suspended = array("i", [0] * 31 + [1] * 30)
    assert halted.is_suspended(30)
    assert tool.volume_band(halted, 59).fallback == tool.SUSPENDED
    other = band_bars({})
    other.low[30] = NAN  # not suspended, but no low
    assert tool.volume_band(other, 59).fallback == tool.NO_RANGE
    # 60 bars after it the window no longer holds it: the band is back
    longer = series(
        [*halted.high, *[105.0] * 31], [*halted.low, *[105.0] * 31], volumes=[0.0] * 91
    )
    longer.suspended = array("i", [0] * 31 + [1] * 61)
    assert tool.volume_band(longer, 89).fallback == tool.SUSPENDED  # bars 30..89
    assert tool.volume_band(longer, 90).fallback is None  # bars 31..90


def test_c4_the_stop_is_the_band_less_half_an_atr_clamped_to_1_to_3_atr():
    band = tool.Band(105.0, 105.0 + EDGE, 1.0)
    atr = 2.0  # initial 105 − 1 = 104
    assert tool.band_stop(band, atr, 107.0) == (104.0, tool.BAND)  # d = 3 = 1.5 ATR
    assert tool.band_stop(band, atr, 106.0) == (104.0, tool.BAND)  # d = 1 ATR: kept
    assert tool.band_stop(band, atr, 110.0) == (104.0, tool.BAND)  # d = 3 ATR: kept
    assert tool.band_stop(band, atr, 105.5) == (103.5, tool.CLAMPED_LOW)  # d = 0.75 ATR
    # a fill at or under the initial stop (d ≤ 0, a gap into the band): 1 ATR
    assert tool.band_stop(band, atr, 104.0) == (102.0, tool.CLAMPED_LOW)
    assert tool.band_stop(band, atr, 103.0) == (101.0, tool.CLAMPED_LOW)
    assert tool.band_stop(band, atr, 111.0) == (105.0, tool.CLAMPED_HIGH)  # d = 3.5 ATR
    for fallback in tool.FALLBACK_REASONS:  # S1's stop
        assert tool.band_stop(tool.Band(fallback=fallback), atr, 107.0) == (
            103.0,
            tool.FALLBACK,
        )


def test_c4_the_hook_keeps_the_band_on_the_trade_and_s1s_target():
    item = band_bars({5: (105.0, 105.0, 500.0)})
    stop, fields = tool.c4_stop(item, 59, 2.0, 107.0)
    assert stop == 104.0
    assert fields == {
        "band_low": pytest.approx(105.0),
        "band_high": pytest.approx(105.0 + EDGE),
        "band_fallback": None,
        "band_stop": pytest.approx(104.0),
        "stop_source": tool.BAND,
    }
    assert tool.c4_stop(item, 59, 2.0, None)[0] is None  # abandoned: no stop
    # the target stays fill + 4×ATR14 (R is 2×ATR14): it is not the hook's
    assert tool.HYPOTHESES["C4"]["target_atr"] == 4.0


# --- C1 族群強度 (AC-2) ------------------------------------------------------------


def test_c1_the_strength_is_the_mean_of_the_two_relative_returns():
    returns = {
        1: (0.10, 0.20),
        2: (0.00, 0.10),
        3: (0.05, 0.30),
        4: (0.05, 0.00),
        5: (0.10, 0.10),
        6: (0.50, 0.50),  # in no group
    }
    members = {"g1": {1, 2, 3, 4, 5}}
    index = (0.02, 0.04)
    [(strength, group, count)] = tool.rank_groups(returns, members, index)
    r20 = (0.10 + 0.00 + 0.05 + 0.05 + 0.10) / 5 - 0.02  # 0.04
    r60 = (0.20 + 0.10 + 0.30 + 0.00 + 0.10) / 5 - 0.04  # 0.10
    assert (group, count) == ("g1", 5)
    assert strength == pytest.approx((r20 + r60) / 2)  # 0.07


def test_c1_takes_the_top_5_ties_by_the_group_key_and_needs_5_valued_members():
    returns = {i: (0.01 * (i // 10), 0.01 * (i // 10)) for i in range(10, 90)}
    members = {
        # group -> five members whose returns are 0.01 × the tens digit
        f"g{d}": {10 * d + k for k in range(5)}
        for d in range(1, 9)
    }
    members["tie_b"] = {80 + k for k in range(5)}  # same strength as g8
    members["tie_a"] = {85 + k for k in range(5)}
    members["small"] = {85, 86, 87, 88, 999}  # 999 has no return: 4 valued
    scored = tool.rank_groups(returns, members, (0.0, 0.0))
    order = [group for _s, group, _n in scored]
    assert "small" not in order  # fewer than 5 valued members: not ranked
    assert order[:5] == ["g8", "tie_a", "tie_b", "g7", "g6"]  # equal: key order
    assert len(scored) == 10


def test_c1_the_taiex_return_needs_61_closes_and_a_close_on_t():
    days = [D0 + timedelta(days=k) for k in range(70)]
    closes = {day: 100.0 + k for k, day in enumerate(days)}
    ctx = SimpleNamespace(index_days=days, panel=SimpleNamespace(index_close=closes))
    assert tool.index_returns(ctx, days[59]) is None  # 60 closes
    r20, r60 = tool.index_returns(ctx, days[60])
    assert r20 == pytest.approx(160.0 / 140.0 - 1.0)
    assert r60 == pytest.approx(160.0 / 100.0 - 1.0)
    assert tool.index_returns(ctx, days[-1] + timedelta(days=1)) is None  # no close


def test_c1_a_member_needs_both_returns_on_its_own_bars():
    closes = [10.0 * (1.01**k) for k in range(61)]
    item = series([c + 1 for c in closes], [c - 1 for c in closes], closes)
    returns = tool.member_returns([(item, 60), (item, 59)])
    assert returns[1] == pytest.approx((1.01**20 - 1.0, 1.01**60 - 1.0))
    assert tool.member_returns([(item, 59)]) == {}  # 60 bars: no 60-session return
    item.close[0] = NAN  # the 60-session base is missing
    assert tool.member_returns([(item, 60)]) == {}


# --- the research copy --------------------------------------------------------------

SESSIONS = 130
INDEX_ID = 90
INDEX_FROM = 9  # TAIEX closes from session 9: session 68 has 60, 69 has 61
FIRST_SIGNAL = 68  # the first signal date (start: the 69th session)
SNAPSHOT_AT = (70, 100)  # sessions of the member snapshots: none before 70
SEMI = (1, 2, 3, 4, 5, 6)  # Semiconductor: TWSE 1-4, TPEx 5-6
PARTS = (7, 8, 9, 10, 11)  # TWSE Electronic Parts: exactly 5
OTHER = (12, 13, 14, 15)  # TWSE Other
REMAPPED = 16  # 9921: TWSE 37 in the table, Other before 2023-07-03
NO_GROUP = 17  # in no snapshot; the best trust figures
STOCKS = (*SEMI, *PARTS, *OTHER, REMAPPED, NO_GROUP)
TPEX = (5, 6)
GROWTH = {**dict.fromkeys(SEMI, 0.004), **dict.fromkeys(PARTS, 0.002)}
GROWTH.update({**dict.fromkeys(OTHER, 0.001), REMAPPED: 0.001, NO_GROUP: 0.003})
# C3: margin balances
SURGE = 1  # +2% a session: 10.4% over five steps
ZERO = 2  # always 0: 0 -> 0
ZERO_UP = 3  # 0 on t % 10 < 6, else 1000
NOT_LISTED = 4  # no balance, never on the list
LIST_GAP = 5  # TPEx, no balance, not listed; the TPEx list is missing on t % 7 == 0
HALTED, HALTED_AT = (
    6,
    80,
)  # TPEx; suspended (no high, low) on session 80 (ATR14 back on 94)
NULL_ROW, NULL_AT = 9, 100  # the three institutional figures null on 100


def trading_days() -> list[date]:
    out, day = [], date(2023, 1, 2)
    while len(out) < SESSIONS:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def symbol(i: int) -> str:
    return "9921" if i == REMAPPED else f"{1100 + i}"


def close_of(i: int, t: int) -> float:
    wiggle = 1.0 + 0.002 * (((t * 7 + i) % 5) - 2)
    return round(50.0 * (1.0 + GROWTH[i]) ** t * wiggle, 4)


def margin_of(i: int, t: int) -> float | None:
    if i == SURGE:
        return round(100_000.0 * 1.02**t, 2)
    if i == ZERO:
        return 0.0
    if i == ZERO_UP:
        return 0.0 if t % 10 < 6 else 1000.0
    if i in (NOT_LISTED, LIST_GAP):
        return None
    return 100_000.0


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    with Session(engine) as db:
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TPEx" if i in TPEX else "TWSE",
                    "symbol": symbol(i),
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": "active",
                }
                for i in STOCKS
            ]
            + [
                {
                    "id": INDEX_ID,
                    "exchange": "TWSE",
                    "symbol": "TAIEX",
                    "name": "加權指數",
                    "instrument_type": "index",
                    "status": "active",
                }
            ],
        )
        bars, chips = [], []
        for i in STOCKS:
            for t, day in enumerate(days):
                c = close_of(i, t)
                o = close_of(i, t - 1) if t else c
                halted = i == HALTED and t == HALTED_AT
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": None if halted else o,
                        "high": None if halted else round(max(o, c) * 1.01, 4),
                        "low": None if halted else round(min(o, c) * 0.99, 4),
                        "close": close_of(i, t - 1) if halted else c,
                        "adj_close": c,
                        "volume": 0 if halted else 2_000_000 + 10_000 * ((t + i) % 9),
                        "turnover": c * 2_000_000,
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": halted,
                    }
                )
                null = i == NULL_ROW and t == NULL_AT
                always = i in (NO_GROUP, HALTED)  # trust_buy_days 5: S1's first two
                trust = 1000.0 if always or (t + i) % 5 < 3 else -1000.0
                chips.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "foreign_buy": None
                        if null
                        else (500.0 if (t + 2 * i) % 3 else -500.0),
                        "trust_buy": None if null else trust,
                        "dealer_buy": None if null else 0.0,
                        "margin_balance": margin_of(i, t),
                    }
                )
        for t, day in enumerate(days[INDEX_FROM:], start=INDEX_FROM):
            close = 10_000.0 + 10.0 * t  # always above its MA60
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adj_close": close,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(insert(ChipSnapshot), chips)
        db.execute(
            insert(MonthlyRevenue),
            [
                {
                    "instrument_id": i,
                    "revenue_month": date(2023, month, 1),
                    "revenue": 110.0,
                    "prior_year_revenue": 100.0,
                    "announcement_date": date(2023, month + 1, 10),
                    "source": "test",
                    "raw_payload_id": 1,
                    "data_as_of": "test",
                }
                for i in STOCKS
                for month in range(1, 6)
            ],
        )
        lists = []
        for exchange in ("TWSE", "TPEx"):
            members = {
                symbol(i): ""
                for i in STOCKS
                if (i in TPEX) == (exchange == "TPEx")
                and i not in (NOT_LISTED, LIST_GAP)
            }
            for t, day in enumerate(days):
                if exchange == "TPEx" and t % 7 == 0:
                    continue
                lists.append(
                    {
                        "exchange": exchange,
                        "trading_date": day,
                        "source": "test",
                        "endpoint": "test",
                        "data_as_of": day.isoformat(),
                        "collected_at": datetime(2023, 1, 1),
                        "raw_payload_id": 1,
                        "member_count": len(members),
                        "members_json": members,
                    }
                )
        db.execute(insert(MarginList), lists)
        db.commit()
    engine.dispose()
    return path


# (exchange, code, ids) of every snapshot
GROUPS = (
    ("TWSE", "24", SEMI[:4]),
    ("TPEx", "24", SEMI[4:]),
    ("TWSE", "28", PARTS),
    ("TWSE", "20", OTHER),
    ("TWSE", "37", (REMAPPED,)),
)


def member_rows() -> list[list]:
    days = trading_days()
    rows = []
    for t in SNAPSHOT_AT:
        day = days[t].isoformat()
        for exchange, code, ids in GROUPS:
            label = im.GROUP_LABELS[exchange][code]
            for i in ids:
                rows.append(
                    [
                        day,
                        exchange,
                        code,
                        "",
                        label,
                        im.group_id(label),
                        symbol(i),
                        f"N{i}",
                        im.retroactive(exchange, code, day),
                    ]
                )
    rows.sort()
    return rows


def write_members(folder: Path) -> Path:
    target = folder.joinpath(*ms.MEMBERS_DIR, ms.MEMBERS_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(im.table_bytes(member_rows(), "2023-01", "2023-06"))
    return target


@pytest.fixture(scope="module")
def copy_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("round4")
    write_members(folder)
    return build(folder / "stock.db")


APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
    """research_report.load_actions points these at the copy for app.config."""

    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return run()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def loaded(copy_db, tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    return one_process(
        lambda: tool.load(
            copy_db, ms.members_path(copy_db), date(2022, 1, 1), trading_days()[-1], raw
        )
    )


def test_c1_puts_the_2023_list_back_and_matches_both_markets(loaded):
    days = trading_days()
    members, _retro, remapped = ms.group_members(loaded.groups, days[SNAPSHOT_AT[0]])
    other, semi = im.group_id("Other"), im.group_id("Semiconductor")
    assert members[other] == {*OTHER, REMAPPED}  # 9921 is Other before 2023-07-03
    assert im.group_id("Sports and Leisure") not in members
    assert remapped == {REMAPPED}
    assert members[semi] == set(SEMI)  # TWSE and TPEx 24 are one group
    assert ms.group_members(loaded.groups, days[SNAPSHOT_AT[0] - 1])[0] == {}


def strong_day(loaded, s: int):
    hook = tool.StrongGroups(loaded.groups)
    keep = hook.day(loaded.ctx, s)
    return hook, keep


def test_c1_on_the_copy_the_strength_is_by_hand_and_t_without_a_group_is_out(loaded):
    s = 110
    ctx = loaded.ctx
    day = ctx.panel.sessions[s]
    hook, keep = strong_day(loaded, s)
    universe = {item.instrument_id: (item, at) for item, at in ctx.universe(s)}
    assert set(universe) == set(STOCKS)
    t20 = (10_000.0 + 10 * s) / (10_000.0 + 10 * (s - 20)) - 1.0
    t60 = (10_000.0 + 10 * s) / (10_000.0 + 10 * (s - 60)) - 1.0

    def strength(ids):
        r20 = [close_of(i, s) / close_of(i, s - 20) - 1.0 for i in ids]
        r60 = [close_of(i, s) / close_of(i, s - 60) - 1.0 for i in ids]
        return (sum(r20) / len(r20) - t20 + sum(r60) / len(r60) - t60) / 2

    chosen = hook.chosen[day]
    by_hand = sorted(
        [
            (strength(SEMI), im.group_id("Semiconductor"), 6),
            (strength(PARTS), im.group_id("Electronic Parts"), 5),
            (strength((*OTHER, REMAPPED)), im.group_id("Other"), 5),
        ],
        key=lambda row: (-row[0], row[1]),
    )
    assert [(g, n) for _s, g, n in chosen] == [(g, n) for _s, g, n in by_hand]
    assert [value for value, _g, _n in chosen] == pytest.approx(
        [value for value, _g, _n in by_hand]
    )
    # three rankable groups: all three taken, the day counted as short of 5
    assert hook.years["2023"]["short"] == 1
    # every grouped stock passes; the one without a group does not
    assert [i for i in STOCKS if keep(*universe[i])] == [
        i for i in STOCKS if i != NO_GROUP
    ]


def test_c1_does_not_take_a_day_without_61_taiex_closes_or_a_ranked_group(loaded):
    hook, keep = strong_day(loaded, FIRST_SIGNAL)  # 60 TAIEX closes
    assert keep is None and hook.years["2023"]["taiex"] == 1
    hook, keep = strong_day(loaded, FIRST_SIGNAL + 1)  # 61 closes, no snapshot yet
    assert keep is None and hook.years["2023"]["none"] == 1
    hook, keep = strong_day(loaded, SNAPSHOT_AT[0])
    assert keep is not None


def test_c3_is_the_products_margin_state_on_the_copy(copy_db, loaded):
    """``margin_class`` against the product's two functions on the copy's own
    rows: the six unsuspended bars to T with a chip row, the ratio, the lists."""

    from app import margin_lists, margin_zero_base

    ctx = loaded.ctx
    con = sqlite3.connect(f"file:{copy_db.as_posix()}?mode=ro", uri=True)
    try:
        halted = {
            (i, date.fromisoformat(d))
            for i, d in con.execute(
                "select instrument_id, trading_date from market_bars where is_suspended = 1"
            )
        }
        balance = {
            (i, date.fromisoformat(d)): m
            for i, d, m in con.execute(
                "select instrument_id, trading_date, margin_balance from chip_snapshots"
            )
        }
        lists = {
            (exchange, date.fromisoformat(d)): set(json.loads(text))
            for exchange, d, text in con.execute(
                "select exchange, trading_date, members_json from margin_lists"
            )
        }
    finally:
        con.close()
    seen = set()
    for s in range(FIRST_SIGNAL, SESSIONS):
        for item, at in ctx.universe(s):
            exchange, code, _ = ctx.panel.symbols[item.instrument_id]
            six = [
                d for d in item.dates[: at + 1] if (item.instrument_id, d) not in halted
            ]
            six = six[-6:]
            first, last = (
                balance[(item.instrument_id, six[0])],
                balance[(item.instrument_id, six[-1])],
            )
            ratio = (
                (last - first) / abs(first)
                if first not in (None, 0) and last is not None
                else None
            )
            state = margin_lists.margin_financing_state(
                code, ratio, [lists.get((exchange, d)) for d in six]
            )
            zero = (
                None
                if ratio is not None
                else margin_zero_base.zero_base_state(first, last)
            )
            if state == margin_lists.NOT_APPLICABLE:
                want = tool.NOT_APPLICABLE
            elif ratio is not None:
                want = tool.OVER if ratio > 0.05 else tool.KEPT
            elif zero == margin_zero_base.UNCHANGED:
                want = tool.KEPT
            elif zero == margin_zero_base.INCREASED:
                want = tool.ZERO_BASE_INCREASED
            else:
                want = tool.MISSING
            margin = tr.margin_state(ctx, item, at)
            assert (margin.financing, margin.zero_base) == (state, zero), (
                item.instrument_id,
                s,
            )
            assert margin.ratio == (None if ratio is None else pytest.approx(ratio))
            got = tool.margin_class(margin)
            assert got == want, (item.instrument_id, s)
            seen.add((item.instrument_id, got))
    assert (SURGE, tool.OVER) in seen  # > 5%
    assert (ZERO, tool.KEPT) in seen  # 0 -> 0
    assert (ZERO_UP, tool.ZERO_BASE_INCREASED) in seen  # 0 -> > 0
    assert (NOT_LISTED, tool.NOT_APPLICABLE) in seen
    assert (LIST_GAP, tool.MISSING) in seen  # not listed, but T's list is missing
    assert (LIST_GAP, tool.NOT_APPLICABLE) in seen  # not listed on T's list
    # the suspended bar is skipped: six unsuspended bars, the ratio defined
    assert (HALTED, tool.KEPT) in seen


# --- the runs on the copy -----------------------------------------------------------


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
    """The segments, floors and the start moved into the copy's 130 sessions."""

    days = trading_days()
    segments = {
        "exploration": (None, days[110]),
        "validation": (days[111], days[129]),
        "used": (days[129], days[129]),
    }
    monkeypatch.setattr(tr, "SEGMENTS", segments)
    floors = {"exploration": 20, "validation": 10}
    monkeypatch.setattr(tr, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(tr, "MIN_DAYS", 1)
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("session", days[0], FIRST_SIGNAL + 1)}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(ms, "MEMBERS_SHA256", ex.file_sha256(ms.members_path(db)))
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    monkeypatch.setattr(ex, "delisted_count", lambda db, first, last: 1)  # none here
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path, name: str = "copy") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    write_members(folder)
    return Path(shutil.copy(db, folder / "stock.db"))


def main(db: Path, out: Path, *extra: str) -> int:
    return one_process(
        lambda: tool.main(
            ["--db", str(db), "--out", str(out), "--min-free-gb", "0", *extra]
        )
    )


def explore(db: Path, out: Path, hypotheses: str | None = "C1,C2,C3,C4") -> int:
    chosen = [] if hypotheses is None else ["--hypotheses", hypotheses]
    return main(db, out, "--segment", "exploration", *chosen)


def validate(db: Path, out: Path, report: Path, sha: str | None = None, url=URL) -> int:
    sha = sha if sha is not None else ex.file_sha256(report)
    return main(
        db,
        out,
        "--segment",
        "validation",
        "--exploration-report",
        str(report),
        "--exploration-sha256",
        sha,
        "--exploration-url",
        url,
    )


@pytest.fixture
def explored(copy_db, tmp_path, monkeypatch):
    compressed(monkeypatch, tmp_path, copy_db)
    db = copy_of(copy_db, tmp_path)
    out = tmp_path / "exploration"
    assert explore(db, out) == 0
    return db, out


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def refused(capsys) -> list[str]:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]


def test_the_exploration_runs_each_layer_and_lists_it(explored):
    db, out = explored
    days = trading_days()
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["round"]) == (
        "round4_research",
        "878",
        4,
    )
    assert (report["round_size"], report["cumulative"]) == (4, 19)
    assert report["engine"] == {"tool": "trade_research", "version": 1}
    assert report["definitions_sha256"] == tool.definitions_sha256()
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert (
        text.splitlines()[0]
        == f"explore.json 的 sha256：`{ex.file_sha256(out / 'explore.json')}`"
    )
    assert "本輪 4 個、累計 19 個" in text
    trades = {name: read_csv(out / name / "trades.csv") for name in REGISTERED}
    # C1: never the stock without a group (S1's best trust figures), no signal
    # before the first snapshot (68: TAIEX short, 69: no group)
    assert trades["C1"] and all(
        row["symbol"] != symbol(NO_GROUP) for row in trades["C1"]
    )
    assert (
        min(row["signal_date"] for row in trades["C1"])
        == days[SNAPSHOT_AT[0]].isoformat()
    )
    tables = read_json(out / "C1" / "tables.json")
    year = tables["listed"]["c1"]["years"]["2023"]
    assert (year["taiex"], year["none"]) == (1, 1)
    assert year["days"] == 110 - FIRST_SIGNAL  # every signal date passing the filter
    assert year["short"] == year["days"] - 2  # three groups only
    # C2: the rows carry both_buy_days; the top-10 missing count is listed
    assert all("both_buy_days" in row for row in trades["C2"])
    c2 = read_json(out / "C2" / "tables.json")["listed"]["c2"]
    assert c2["signals"] == len(trades["C2"])
    assert c2["first_key_missing"] == sum(
        1 for row in trades["C2"] if row["both_buy_days"] == ""
    )
    # C3: the surging stock is never a signal; the classes are counted
    assert all(row["symbol"] != symbol(SURGE) for row in trades["C3"])
    c3 = read_json(out / "C3" / "tables.json")["listed"]["c3"]["years"]["2023"]
    assert c3["over"] > 0 and c3["not_applicable"] > 0  # missing: in the coverage
    # C4: every filled trade has a stop source; the suspended bar falls back
    c4 = read_json(out / "C4" / "tables.json")["listed"]["c4"]
    assert sum(c4["sources"].values()) == c4["trades"] > 0
    # every filled C4 trade's stop is the band's of its T and fill, its
    # target S1's (R stays 2×ATR14)
    ctx = one_process(
        lambda: tr.load(db, date(2022, 1, 1), days[110], db.parent / "raw")
    )
    ids = {symbol(i): i for i in STOCKS}
    filled = [row for row in trades["C4"] if row["net"]]
    assert filled
    for row in filled:
        item = ctx.panel.series[ids[row["symbol"]]]
        at = item.position[date.fromisoformat(row["signal_date"])]
        fill, atr = float(row["fill_price"]), float(row["atr14"])
        stop, source = tool.band_stop(tool.volume_band(item, at), atr, fill)
        assert (float(row["stop"]), row["stop_source"]) == (pytest.approx(stop), source)
        assert float(row["target"]) == pytest.approx(fill + 4 * atr)
        assert 1 * atr - 1e-9 <= fill - stop <= 3 * atr + 1e-9
    summary = (out / "C4" / "summary.md").read_text(encoding="utf-8")
    assert "退回 S1：停牌根缺高低價" in summary


def test_c1_counts_the_occupied_stocks_in_the_strength(
    copy_db, loaded, monkeypatch, tmp_path
):
    """The parts group has exactly five valued members: a day with one of them
    occupied still ranks it (占用 is C1's own trading, C1-g)."""

    compressed(monkeypatch, tmp_path, copy_db)
    run = tool.Run(loaded.groups)
    results = tr.run_segment(
        loaded.ctx,
        copy_db,
        ["C1"],
        "exploration",
        hypotheses=tool.HYPOTHESES,
        hooks=run,
    )
    trades = results["C1"]["_trades"]
    parts = im.group_id("Electronic Parts")
    busy_days = 0
    for day, chosen in run.made["C1"].chosen.items():
        occupied = [
            row
            for row in trades
            if row["instrument_id"] in PARTS
            and row["signal_date"] < day <= (row["exit_date"] or row["abandoned_date"])
        ]
        if occupied:
            busy_days += 1
            assert parts in {group for _s, group, _n in chosen}, day
    assert busy_days > 0


def test_the_coverage_lists_counts_and_no_return(copy_db, tmp_path, monkeypatch):
    compressed(monkeypatch, tmp_path, copy_db)
    db = copy_of(copy_db, tmp_path)
    out = tmp_path / "coverage"
    assert main(db, out, "--segment", "exploration", "--coverage-only") == 0
    body = read_json(out / "coverage.json")
    assert set(path.name for path in out.iterdir()) >= {"coverage.json", "coverage.md"}
    assert not (out / "explore.json").exists()
    assert not (db.parent / ex.LEDGER_NAME).exists()  # no ledger: any number of runs
    text = json.dumps(body, ensure_ascii=False)
    for word in ('"net"', '"excess"', '"taiex_excess"', '"absolute"', "verdict"):
        assert word not in text
    year = body["years"]["2023"]
    assert year["days"] == 110 - FIRST_SIGNAL
    assert year["filter_passed"] == year["days"]
    assert body["c1"]["2023"]["taiex"] == 1 and body["c1"]["2023"]["none"] == 1
    assert year["c2_top"] == 10 * year["days"]
    assert year["c4_top"] == 10 * year["days"]
    sources = sum(year.get(f"c4_source_{s}", 0) for s in tool.STOP_SOURCES)
    assert sources + year.get("c4_unfilled", 0) == year["c4_top"]
    assert year.get("c4_no_band_suspended_bar", 0) > 0
    c3 = body["c3"]["2023"]
    assert c3["days"] == year["days"]
    assert min(c3[k] for k in (tool.OVER, tool.ZERO_BASE_INCREASED, tool.MISSING)) > 0
    assert c3[tool.NOT_APPLICABLE] > 0 and c3[tool.KEPT] > 0
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "C4 停損來源" in md and "停牌根缺高低價" in md
    assert (
        main(db, tmp_path / "again", "--segment", "exploration", "--coverage-only") == 0
    )
    for bad in (["--hypotheses", "C1"], ["--segment", "validation"]):
        with pytest.raises(SystemExit):
            main(
                db, tmp_path / "x", "--segment", "exploration", "--coverage-only", *bad
            )


# --- the gate and the ledger (AC-3) ------------------------------------------------


def test_the_exploration_runs_once_per_hypothesis_and_version(explored, capsys):
    db, out = explored
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["segment"], e["version"]) for e in entries
    ] == [(name, "round4_research", "exploration", 1) for name in REGISTERED]
    assert read_json(out / "ledger-entries.json")["entries"] == entries
    capsys.readouterr()
    assert explore(db, out.parent / "again", "C3") == 2
    assert any("C3 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_the_exploration_takes_only_c1_to_c4(copy_db, tmp_path, monkeypatch, capsys):
    compressed(monkeypatch, tmp_path, copy_db)
    db = copy_of(copy_db, tmp_path)
    assert explore(db, tmp_path / "o1", None) == 2
    assert refused(capsys) == ["--segment exploration needs --hypotheses (e.g. C1,C2)"]
    assert explore(db, tmp_path / "o2", "S1,C1,C1") == 2  # S1 is trade_research's
    problems = refused(capsys)
    assert any("S1 not registered" in line for line in problems)
    assert any("C1 given more than once" in line for line in problems)


def test_the_member_table_must_be_779s(copy_db, tmp_path, monkeypatch, capsys):
    compressed(monkeypatch, tmp_path, copy_db)
    db = copy_of(copy_db, tmp_path)
    monkeypatch.setattr(ms, "MEMBERS_SHA256", "0" * 64)
    assert explore(db, tmp_path / "o") == 2
    assert any("not the member table" in line for line in refused(capsys))


def passed_report(out: Path, names=("C1",)) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "explore.json"
    body = {
        "design": tool.DESIGN,
        "segment": "exploration",
        "definitions_sha256": tool.definitions_sha256(),
        "hypotheses": {name: {"verdict": ex.EXPLORATION_PASSED} for name in names},
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_validation_refuses_before_a_public_exploration_report(
    explored, tmp_path, capsys
):
    db, out = explored
    report = passed_report(tmp_path / "passed")
    assert validate(db, tmp_path / "v1", report, sha="0" * 64) == 2
    assert any("not the published one" in line for line in refused(capsys))
    assert validate(db, tmp_path / "v2", report, url="https://example.com/x") == 2
    assert any("not an Issue comment" in line for line in refused(capsys))
    assert main(db, tmp_path / "v3", "--segment", "validation") == 2
    assert any("needs --exploration-report" in line for line in refused(capsys))
    # trade_research's report (design 726) is not this tool's
    other = tmp_path / "other"
    other.mkdir()
    body = read_json(report)
    (other / "explore.json").write_text(
        json.dumps({**body, "design": "726"}), encoding="utf-8"
    )
    assert validate(db, tmp_path / "v4", other / "explore.json") == 2
    assert any(
        "not an exploration report of this tool" in line for line in refused(capsys)
    )
    # the real exploration report: nothing passed on the copy
    assert validate(db, tmp_path / "v5", out / "explore.json") == 2
    assert any("no hypothesis passed" in line for line in refused(capsys))
    for name in ("v1", "v2", "v3", "v4", "v5"):
        assert not (tmp_path / name).exists()


def test_the_validation_runs_once(explored, tmp_path, capsys):
    db, _out = explored
    report = passed_report(tmp_path / "passed", ("C2",))
    assert validate(db, tmp_path / "v1", report) == 0
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    mine = [e for e in entries if e["segment"] == "validation"]
    assert [(e["hypothesis"], e["tool"], e["status"]) for e in mine] == [
        ("C2", "round4_research", "finished")
    ]
    capsys.readouterr()
    assert validate(db, tmp_path / "v2", report) == 2
    assert any("C2 already in" in line for line in refused(capsys))


def test_the_other_tools_ledger_rows_do_not_block(copy_db, tmp_path, monkeypatch):
    compressed(monkeypatch, tmp_path, copy_db)
    db = copy_of(copy_db, tmp_path)
    ex.write_ledger(
        db.parent / ex.LEDGER_NAME,
        [
            {
                "hypothesis": "S1",
                "tool": "trade_research",
                "segment": "exploration",
                "version": 1,
            },
            {
                "hypothesis": "M1",
                "tool": "mainstream_research",
                "segment": "exploration",
                "version": 1,
            },
        ],
    )
    assert explore(db, tmp_path / "o", "C4") == 0


# --- the ledger must be writable (#899) -------------------------------------------

# A directory a non-root POSIX user cannot write, as the research volume
# mounted :ro is in the container; Windows and root ignore the mode (#899).
READ_ONLY = pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0,
    reason="a read-only directory needs a non-root POSIX user (CI's runner)",
)


def no_reads(monkeypatch) -> list:
    """Every sqlite3.connect from here on is recorded and fails."""

    opened: list = []

    def connect(*args, **kwargs):
        opened.append(args)
        raise AssertionError(f"the DB was opened: {args}")

    monkeypatch.setattr(sqlite3, "connect", connect)
    return opened


def unwritable(problems: list[str], db: Path) -> bool:
    # the only refusal: a run refused for another reason proves nothing here
    return len(problems) == 1 and all(
        str(db.parent / ex.LEDGER_NAME) in text
        and "not writable" in text
        and ":ro" in text
        and "第 2 步的工具" in text
        for text in problems
    )


@READ_ONLY
def test_a_read_only_ledger_folder_refuses_the_exploration_before_anything_is_read(
    copy_db, tmp_path, monkeypatch, capsys
):
    db = copy_of(copy_db, tmp_path)
    compressed(monkeypatch, tmp_path, copy_db)
    opened = no_reads(monkeypatch)
    out = tmp_path / "out"
    db.parent.chmod(0o555)
    try:
        assert explore(db, out, "C1") == 2
    finally:
        db.parent.chmod(0o755)
    assert unwritable(refused(capsys), db)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_coverage_only_runs_on_a_read_only_ledger_folder(
    copy_db, tmp_path, monkeypatch
):
    compressed(monkeypatch, tmp_path, copy_db)
    db = copy_of(copy_db, tmp_path)
    out = tmp_path / "coverage"
    db.parent.chmod(0o555)
    try:
        assert main(db, out, "--segment", "exploration", "--coverage-only") == 0
    finally:
        db.parent.chmod(0o755)
    assert (out / "coverage.json").is_file()
