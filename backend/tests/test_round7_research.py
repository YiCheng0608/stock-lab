"""tools/research/round7_research.py: the registered Y1～Y4 (#912).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第七輪：Y1～Y4.  The features and the order are checked
on hand-made series (the expected numbers worked out in the test); the gate
("each once") runs on a synthetic copy on a compressed calendar
(``compressed``): the segments, floors and starts are moved into the
fixture's 330 sessions, everything else is the registered one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import statistics
import sys
import weakref
from array import array
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import Base, ChipSnapshot, CorporateAction, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/912#issuecomment-1"
NAN = float("nan")


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
pr = _tool("portfolio_research")
ex = _tool("explore_research")
im = _tool("industry_members")
ms = _tool("mainstream_research")
r5 = _tool("round5_research")
r6 = _tool("round6_research")
tool = _tool("round7_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAMES = ("Y1", "Y2", "Y3", "Y4")


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for other in (ex, r5, r6):
        assert not set(h) & set(other.HYPOTHESES)
    rows = {
        name: (spec["subset"], spec["keys"], spec["top"], spec["hold"], spec["start"])
        for name, spec in h.items()
    }
    otc = date(2007, 12, 3)
    assert rows == {
        "Y1": (None, (("margin_flow_20", "low"),), 20, 60, ("session", otc, 21)),
        "Y2": (None, (("turnover_cv_240", "low"),), 20, 60, ("session", otc, 240)),
        "Y3": (None, (("delay_52w", "high"),), 20, 60, ("session", otc, 261)),
        "Y4": (
            ("turnover_60", 150),
            (("ind_rev_20", "low"),),
            20,
            20,
            ("date", date(2013, 2, 1)),
        ),
    }
    assert all(spec["rule"] == "daily" for spec in h.values())


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (1, 7, 4, 30)
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.144
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(30), 3) == 3.144
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "a5d32c89"
    assert (tool.MARGIN_WINDOW, tool.LOT_SHARES) == (20, 1000)
    assert (tool.CV_WINDOW, tool.CV_DDOF) == (240, 1)
    assert (tool.DELAY_STEP, tool.DELAY_POINTS, tool.DELAY_WEEKS, tool.DELAY_LAGS) == (
        5,
        53,
        48,
        4,
    )
    assert (tool.MOMENTUM_WINDOW, tool.SUBSET_SIZE, tool.MIN_PEERS) == (20, 150, 5)


def test_the_definitions_hash_holds_the_threshold_and_the_members(monkeypatch):
    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.144
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.102),
        (tool, "LOT_SHARES", 1),
        (tool, "MIN_PEERS", 4),
        (ms, "MEMBERS_SHA256", "0" * 64),
    ):
        with monkeypatch.context() as m:
            m.setattr(module, name, value)
            assert tool.definitions_sha256() != before, name
    assert tool.definitions_sha256() == before


def test_the_command_has_no_parameter_flags():
    flags = {
        option for action in tool._parser()._actions for option in action.option_strings
    }
    assert flags == {
        "-h",
        "--help",
        "--db",
        "--out",
        "--segment",
        "--min-free-gb",
        "--members",
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master a5d32c89 before this tool existed.
FROZEN = {
    "explore_research": (
        2,
        "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63",
    ),
    "trade_research": (
        1,
        "80329d4669123683783a2153a132931fe90eecfbbe8fbfa382cfed345d8cfbfb",
    ),
    "mainstream_research": (
        1,
        "5e776480b0fa7d023c9f217671c856ac81ea8d4115d7ff94aac7446a263371f2",
    ),
    "round4_research": (
        1,
        "2fa7f1826fc1b1b962eb63b45b6a238122d74fd4912e0a14c8eed0a0cf63aa56",
    ),
    "round5_research": (
        1,
        "a3409f1b9dd24a8e32c04148f5d1e36a5e8282e96df975bd0b36a21101993d75",
    ),
    # merged with #905 (master ac9ee9fc), measured there before this tool
    "round6_research": (
        1,
        "b8e1eb89a20b9ea97db4d6ba38a1461d5ff5bf05b26eb9619c353db7020ac51e",
    ),
}


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(
    closes,
    suspended=(),
    dates=None,
    instrument_id=1,
    volumes=None,
    margin=None,
    sessions=None,
):
    """A series on ``dates`` (weekdays by default); ``sessions`` the market
    session index of each bar (its position by default)."""

    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2014, 1, 1), len(closes))
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at if sessions is None else sessions[at])
        for name in ("open", "high", "low", "close"):
            getattr(item, name).append(close)
        item.volume.append(1.0 if volumes is None else float(volumes[at]))
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    if margin is not None:
        item.chips = {"margin_balance": array("d", margin)}
    return item


def context_for(items, turnover=None, sessions=None, index=None, symbols=None):
    series = {item.instrument_id: item for item in items}
    raw = {item.instrument_id: ([], [], list(item.close), []) for item in items}
    panel = lib.Panel(sessions or [], series, {}, index or {}, symbols or {})
    base = ex.Context(pr.Market(panel, raw, {}, None))
    for instrument_id, values in (turnover or {}).items():
        base.turnover[instrument_id] = array("d", values)
    return tool.Context(base)


def sorted_ids(spec_name: str, values: dict[int, float | None], day: date) -> list[int]:
    keys = tool.HYPOTHESES[spec_name]["keys"]
    name = keys[0][0]
    rows = [(i, {name: v}, pr.tie_break(day, i)) for i, v in values.items()]
    rows.sort(key=lambda row: tool.order_key(row[1], keys, row[2]))
    return [row[0] for row in rows]


def test_the_order_is_small_or_high_first_with_a_missing_value_last():
    day = date(2015, 3, 2)
    values = {1: 0.3, 2: None, 3: -0.2, 4: 0.3, 5: 0.0}
    tied = sorted((1, 4), key=lambda i: pr.tie_break(day, i))
    for name in ("Y1", "Y2", "Y4"):
        assert sorted_ids(name, values, day) == [3, 5, *tied, 2]
    assert sorted_ids("Y3", values, day) == [*tied, 5, 3, 2]


# --- Y1 -------------------------------------------------------------------------


def y1(margin, volumes=None, at=20, n=21):
    item = make_item(
        [10.0] * n,
        volumes=volumes or [2000] * n,
        margin=margin,
    )
    return tool.margin_flow_20(context_for([item]), item, at)


def test_margin_flow_20_is_lots_times_1000_over_the_mean_volume_of_20_bars_before_t():
    margin = [10.0] + [NAN] * 19 + [4.0]  # only bars at − 20 and at are read
    volumes = [2000] * 20 + [10**9]  # T's own volume is not in the mean
    # (4 − 10) lots × 1,000 shares ÷ 2,000 shares
    assert y1(margin, volumes) == pytest.approx(-3.0, rel=1e-12, abs=0)
    volumes = [1000] * 10 + [3000] * 10 + [5]
    assert y1(margin, volumes) == pytest.approx(-6000 / 2000, rel=1e-12, abs=0)


def test_margin_flow_20_needs_at_20():
    assert y1([1.0] * 21, at=19) is None
    assert y1([1.0] * 21, at=20) == 0.0


@pytest.mark.parametrize("where", [0, 20])
def test_margin_flow_20_is_missing_without_a_balance_on_either_bar(where):
    margin = [10.0] * 21
    margin[where] = NAN  # no chip row, or a null margin_balance
    assert y1(margin) is None
    item = make_item([10.0] * 21, volumes=[2000] * 21)  # no chips at all
    assert tool.margin_flow_20(context_for([item]), item, 20) is None


def test_margin_flow_20_is_missing_with_a_mean_volume_of_zero():
    assert y1([10.0] * 21, volumes=[0] * 20 + [5000]) is None


def test_margin_flow_20_of_two_zero_balances_is_zero_not_missing():
    assert y1([0.0] * 21) == 0.0


# --- Y2 -------------------------------------------------------------------------


def y2(turnover, suspended=(), at=None):
    item = make_item([10.0] * len(turnover), suspended=suspended)
    ctx = context_for([item], turnover={1: turnover})
    return tool.turnover_cv_240(ctx, item, len(turnover) - 1 if at is None else at)


def test_turnover_cv_240_is_the_sample_deviation_over_the_mean():
    # 120 of 100 and 120 of 300: mean 200, Σ(x − 200)² = 240 × 100², ddof 1
    window = [100.0, 300.0] * 120
    by_hand = math.sqrt(240 * 100.0**2 / 239) / 200
    assert y2(window) == pytest.approx(by_hand, rel=1e-12, abs=0)
    assert y2([NAN, *window]) == pytest.approx(by_hand, rel=1e-12, abs=0)  # at − 240
    assert y2([5.0] * 240) == 0.0


def test_turnover_cv_240_needs_240_bars():
    assert y2([100.0, 300.0] * 120, at=238) is None


@pytest.mark.parametrize("where", [0, 100, 239])
def test_turnover_cv_240_is_missing_with_a_turnover_not_available(where):
    window = [100.0] * 240
    window[where] = NAN
    assert y2(window) is None


def test_turnover_cv_240_is_missing_with_a_suspended_bar_in_the_240():
    window = [100.0, 300.0] * 120
    assert y2(window, suspended=(5,)) is None
    assert y2(window, suspended=(239,)) is None
    assert y2([1.0, *window], suspended=(0,)) is not None  # at − 240 is outside


def test_turnover_cv_240_is_missing_with_a_mean_not_positive():
    assert y2([0.0] * 240) is None


# --- Y3 -------------------------------------------------------------------------


def wave(salt: str):
    """A random walk on sessions −10 .. 400 (independent daily moves)."""

    levels, level = {}, 100.0
    for s in range(-10, 400):
        digest = hashlib.sha256(f"{salt}:{s}".encode()).digest()
        level *= 1.0 + 0.04 * (digest[0] / 255.0 - 0.5)
        levels[s] = level
    return levels.__getitem__


INDEX = wave("index")
N_SESSIONS = 270  # T is the last; the points go down to session 9


def y3(
    stock,
    index=INDEX,
    skip=(),
    suspended=(),
    index_missing=(),
    n=N_SESSIONS,
    market=None,
):
    """``market``: replaces T's market part (``DelayMarket``) before the stock's
    value is computed."""

    sessions = weekdays(date(2014, 1, 1), n)
    kept = [s for s in range(n) if s not in skip]
    item = make_item(
        [stock(s) for s in kept],
        suspended={k for k, s in enumerate(kept) if s in suspended},
        dates=[sessions[s] for s in kept],
        sessions=kept,
    )
    index_close = {
        day: index(s) for s, day in enumerate(sessions) if s not in index_missing
    }
    ctx = context_for([item], sessions=sessions, index=index_close)
    if market is not None:
        ctx.delay_market[n - 1] = market(tool.delay_market(ctx, n - 1))
    return tool.delay_52w(ctx, item, item.position[sessions[-1]])


def points(n=N_SESSIONS) -> list[int]:
    return [n - 1 - 5 * j for j in range(53)]


def weekly(close) -> list[float]:
    p = points()
    return [close(p[j]) / close(p[j + 1]) - 1 for j in range(52)]


def r_squared(y: list[float], xs: list[list[float]]) -> float:
    """OLS with an intercept on the normal equations (not the tool's centring)."""

    rows = [[1.0, *(x[i] for x in xs)] for i in range(len(y))]
    k = len(rows[0])
    a = [
        [sum(r[i] * r[j] for r in rows) for j in range(k)]
        + [sum(r[i] * v for r, v in zip(rows, y))]
        for i in range(k)
    ]
    for c in range(k):  # Gaussian elimination, then back substitution
        p = max(range(c, k), key=lambda r: abs(a[r][c]))
        a[c], a[p] = a[p], a[c]
        for r in range(c + 1, k):
            f = a[r][c] / a[c][c]
            a[r] = [x - f * z for x, z in zip(a[r], a[c])]
    beta = [0.0] * k
    for c in range(k - 1, -1, -1):
        beta[c] = (a[c][k] - sum(a[c][j] * beta[j] for j in range(c + 1, k))) / a[c][c]
    fitted = [sum(b * x for b, x in zip(beta, r)) for r in rows]
    mean = statistics.fmean(y)
    ssr = sum((v - f) ** 2 for v, f in zip(y, fitted))
    sst = sum((v - mean) ** 2 for v in y)
    return 1 - ssr / sst


def test_delay_52w_is_one_minus_the_ratio_of_the_two_r_squared():
    stock = wave("stock")
    mixed = lambda s: stock(s) * INDEX(s) ** 0.5  # noqa: E731
    r, m = weekly(mixed), weekly(INDEX)
    weeks = range(48)
    y = [r[j] for j in weeks]
    restricted = r_squared(y, [[m[j] for j in weeks]])
    unrestricted = r_squared(y, [[m[j + k] for j in weeks] for k in range(5)])
    assert 0 < restricted < unrestricted < 1
    assert y3(mixed) == pytest.approx(
        1 - restricted / unrestricted, rel=1e-9, abs=1e-12
    )


def test_delay_52w_is_0_when_the_stock_moves_with_the_index():
    assert y3(lambda s: 3.0 * INDEX(s)) == pytest.approx(0.0, abs=1e-12)


def test_delay_52w_is_near_1_when_the_stock_follows_the_index_a_week_late():
    late = lambda s: INDEX(s - 5)  # noqa: E731  r_j = m_{j+1}
    r, m = weekly(late), weekly(INDEX)
    assert r[:51] == pytest.approx(m[1:52], rel=1e-12)
    y, x = r[:48], m[:48]
    # unrestricted R² is 1 (r is a regressor), restricted is corr(r, m)²
    restricted = statistics.correlation(y, x) ** 2
    value = y3(late)
    assert value == pytest.approx(1 - restricted, rel=1e-9)
    assert value > 0.8


def test_delay_52w_samples_every_5th_market_session_not_the_stocks_bars():
    stock = wave("stock")
    off = [p - 1 for p in points()]  # none of the 53 points
    assert y3(stock, skip=off) == pytest.approx(y3(stock), rel=1e-12)
    assert y3(stock, index_missing=off) == pytest.approx(y3(stock), rel=1e-12)
    assert y3(stock, skip=(points()[-1] - 1,)) is not None  # before s_52


@pytest.mark.parametrize("point", [0, 26, 52])
def test_delay_52w_is_missing_without_a_bar_or_suspended_at_a_point(point):
    stock = wave("stock")
    s = points()[point]
    if point:  # T itself always has a bar (it is in the population)
        assert y3(stock, skip=(s,)) is None
    assert y3(stock, suspended=(s,)) is None
    assert y3(lambda t: 0.0 if t == s else stock(t)) is None
    assert y3(lambda t: NAN if t == s else stock(t)) is None
    assert y3(stock, index_missing=(s,)) is None


def test_delay_52w_needs_260_sessions_before_t():
    stock = wave("stock")
    assert y3(stock, n=261) is not None
    assert y3(stock, n=260) is None


def test_delay_52w_is_missing_when_r_squared_is_not_positive():
    assert y3(lambda s: 10.0) is None  # every r is 0: no variance


def test_delay_52w_is_missing_when_r_varies_but_r_squared_unrestricted_is_0():
    """The R²(unrestricted) ≤ 0 branch with a varying r (PR #913 review): the
    centred market columns all 0 (q = C'r = 0), the inverse kept, so the sum of
    squares of r is > 0 but nothing is explained."""

    stock = wave("stock")
    assert y3(stock) is not None  # the same stock on the real market part
    flat = lambda part: tool.DelayMarket(  # noqa: E731
        part.points,
        tuple((0.0,) * tool.DELAY_WEEKS for _ in part.columns),
        part.inverse,
        part.own,
    )
    r = weekly(stock)[: tool.DELAY_WEEKS]
    assert statistics.pvariance(r) > 0
    assert y3(stock, market=flat) is None


# --- Y4 -------------------------------------------------------------------------

SEMI = im.group_id(im.GROUP_LABELS["TWSE"]["24"])
PARTS = im.group_id(im.GROUP_LABELS["TWSE"]["28"])


def member(i: int, code: str) -> ms.Member:
    label = im.GROUP_LABELS["TWSE"][code]
    return ms.Member("TWSE", code, label, im.group_id(label), f"S{i}", False)


def y4_context(momenta, groups, turnover=None, days=61, first=date(2015, 1, 5)):
    """Items with bars on every session: close 100 to at − 20, then 100 × (1 +
    momentum) at T; ``groups`` {snapshot date: {id: code}}."""

    sessions = weekdays(first, days)
    items = []
    for i, momentum in momenta.items():
        closes = [100.0] * days
        if momentum is None:
            closes[days - 21] = NAN
        else:
            closes[-1] = 100.0 * (1 + momentum)
        items.append(make_item(closes, dates=sessions, instrument_id=i))
    symbols = {i: ("TWSE", f"S{i}", "") for i in momenta}
    ctx = context_for(
        items,
        turnover={i: [value] * days for i, value in (turnover or {}).items()},
        sessions=sessions,
        symbols=symbols,
    )
    ctx.groups = ms.build_context(
        ctx.market,
        {
            day: [member(i, code) for i, code in rows.items()]
            for day, rows in groups.items()
        },
    )
    return ctx, sessions


def test_ind_rev_20_is_the_momentum_minus_the_group_mean_with_this_one():
    momenta = {1: 0.10, 2: 0.20, 3: 0.30, 4: 0.40, 5: 0.50, 6: None, 7: 0.1, 8: 0.2}
    momenta[9] = -0.5
    codes = {i: "24" for i in range(1, 7)} | {7: "28", 8: "28"}
    ctx, sessions = y4_context(momenta, {date(2015, 1, 5): codes})
    day = sessions[-1]
    members = [(item, item.position[day]) for item in ctx.panel.series.values()]
    out = tool.industry_day(ctx, day, members)
    assert out[1].momentum == pytest.approx(0.10)
    assert (out[1].group, out[1].peers) == (SEMI, 5)
    assert out[1].mean == pytest.approx(0.30)
    assert out[1].value == pytest.approx(-0.20)
    assert out[3].value == pytest.approx(0.0, abs=1e-12)
    assert out[6].value is None and out[6].momentum is None  # momentum missing
    assert out[7].value is None and out[7].peers == 2  # fewer than 5 valued
    assert out[9].value is None and out[9].group is None  # no group on T
    ranked = tool.rank(ctx, {**REGISTERED["Y4"], "subset": None}, day, members)
    assert +ranked.reasons == {"momentum": 1, "few_peers": 2, "no_group": 1}


def test_ind_rev_20_is_missing_with_fewer_than_5_valued_peers():
    momenta = {1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4, 5: None}
    ctx, sessions = y4_context(
        momenta, {date(2015, 1, 5): dict.fromkeys(momenta, "24")}
    )
    day = sessions[-1]
    members = [(item, item.position[day]) for item in ctx.panel.series.values()]
    assert all(v.value is None for v in tool.industry_day(ctx, day, members).values())


def test_y4_takes_the_150_by_turnover_and_averages_over_the_whole_population():
    ids = range(1, 156)
    momenta = {i: 0.001 * i for i in ids} | {i: 1.0 for i in range(151, 156)}
    codes = {i: "24" for i in ids if i != 150}  # 150: no group, keeps its place
    turnover = {i: 1000.0 * (200 - i) for i in ids}  # 1 is the largest
    ctx, sessions = y4_context(momenta, {date(2015, 1, 5): codes}, turnover=turnover)
    day = sessions[-1]
    members = [(item, item.position[day]) for item in ctx.panel.series.values()]
    ranked = tool.rank(ctx, tool.HYPOTHESES["Y4"], day, members)
    picked = [row[0] for row in ranked.rows]
    assert len(picked) == 150 and ranked.subset == 150
    assert picked == [*range(1, 150), 150]  # small first, the missing one last
    assert 151 not in picked  # no one fills 150's place
    valued = [0.001 * i for i in range(1, 150)] + [1.0] * 5
    mean = statistics.fmean(valued)  # 151～155 are outside the 150 but averaged
    assert ranked.rows[0][1]["ind_rev_20"] == pytest.approx(0.001 - mean)
    assert ranked.rows[0][1]["peers"] == 154
    assert ranked.subset_missing["ind_rev_20"] == 1


def test_a_stock_in_two_groups_takes_the_smaller_group_id_and_counts_in_both():
    """Not in the registration (PR #913 review): the ``group_id`` strings (a
    hash, not the industry code) compared, the smaller one taken; its momentum
    is in both groups' means, as C1 does not deduplicate."""

    momenta = {1: 0.50, 2: 0.10, 3: 0.20, 4: 0.30, 5: 0.40}
    momenta |= {6: 0.05, 7: 0.15, 8: 0.25, 9: 0.35}
    ctx, sessions = y4_context(momenta, {date(2015, 1, 5): {}})
    rows = [member(i, "24") for i in (1, 2, 3, 4, 5)]
    rows += [member(i, "28") for i in (1, 6, 7, 8, 9)]
    ctx.groups = ms.build_context(ctx.market, {date(2015, 1, 5): rows})
    day = sessions[-1]
    members = [(item, item.position[day]) for item in ctx.panel.series.values()]
    out = tool.industry_day(ctx, day, members)
    assert SEMI != PARTS and not SEMI.isdigit()  # hash strings, not "24"／"28"
    smaller, larger = sorted((SEMI, PARTS))
    assert (out[1].group, out[1].groups) == (smaller, 2)
    both = {SEMI: (1, 2, 3, 4, 5), PARTS: (1, 6, 7, 8, 9)}
    for group, ids in both.items():
        mean = statistics.fmean(momenta[i] for i in ids)  # stock 1 in each
        for i in ids[1:]:
            assert (out[i].group, out[i].peers, out[i].groups) == (group, 5, 1)
            assert out[i].mean == pytest.approx(mean)
    assert out[1].mean == pytest.approx(
        statistics.fmean(momenta[i] for i in both[smaller])
    )
    assert out[1].value == pytest.approx(0.50 - out[1].mean)
    ranked = tool.rank(ctx, {**REGISTERED["Y4"], "subset": None}, day, members)
    assert ranked.reasons["several_groups"] == 1


def test_y4_takes_the_latest_snapshot_up_to_t_and_the_last_one_after():
    momenta = {i: 0.01 * i for i in range(1, 6)}
    snapshots = {
        date(2024, 8, 30): dict.fromkeys(momenta, "24"),
        date(2024, 9, 30): dict.fromkeys(momenta, "28"),
    }
    ctx, sessions = y4_context(momenta, snapshots, days=60, first=date(2024, 8, 1))
    for day, group in (
        (date(2024, 8, 29), None),  # before the first snapshot
        (date(2024, 9, 27), SEMI),  # the validation's last day: 2024-08's
        (date(2024, 9, 30), PARTS),
        (date(2024, 10, 22), PARTS),  # the used segment: the last one
    ):
        members = [(item, item.position[day]) for item in ctx.panel.series.values()]
        assert tool.industry_day(ctx, day, members)[1].group == group, day


# --- the verdict ----------------------------------------------------------------


def judged(stage, t):
    excess = {"mean": 0.001, "t": t}
    return ex.explore_judge(
        stage,
        2000,
        True,
        excess,
        0.0005,
        tool.VALIDATION_MIN_T if stage == "validation" else tool.MIN_T,
    )


@pytest.mark.parametrize(
    "t, verdict",
    [
        (2.0, "前瞻觀察"),
        (2.5, "前瞻觀察"),
        (3.102, "前瞻觀察"),  # round 6's threshold is not this round's
        (3.143, "前瞻觀察"),
        (3.144, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_144(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 330
STOCKS = range(1, 25)
DELISTED = {25: 120, 27: 250}  # the last bar's index
TRANSFERRED = {26: 280}
INDEX_ID = 90
UNKNOWN_TURNOVER = (9, 100)  # (id, session): turnover_status "unknown"
NO_CHIPS = 4  # a TPEx stock without any chip row
NULL_MARGIN = (5, 100)  # (id, session): a chip row with a null margin_balance
ZERO_MARGIN = 7  # no one uses margin: both balances 0
GROUP_CODES = {i: "24" if i <= 12 else "28" for i in STOCKS}  # 25～27: no group


def trading_days() -> list[date]:
    return weekdays(date(2013, 1, 1), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int) -> list[float]:
    level, out = 50.0 + i, []
    for t in range(SESSIONS):
        level *= 1.0 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)
        out.append(round(level, 4))
    return out


def index_levels() -> list[float]:
    level, out = 8000.0, []
    for t in range(SESSIONS):
        level *= 1.0 + 0.01 * noise(0, t, "index")
        out.append(round(level, 2))
    return out


def volume(i: int) -> int:
    return 2_000_000 + 10_000 * i


def margin(i: int, t: int) -> float | None:
    if i == ZERO_MARGIN:
        return 0.0
    if (i, t) == NULL_MARGIN:
        return None
    return 1000.0 + 10.0 * t + i


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ends = {**DELISTED, **TRANSFERRED}
    ids = [*STOCKS, *ends]
    with Session(engine) as db:
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TWSE" if i % 2 else "TPEx",
                    "symbol": f"S{i}",
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": "delisted"
                    if i in DELISTED
                    else "transferred"
                    if i in TRANSFERRED
                    else "active",
                }
                for i in ids
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
        for i in ids:
            prices = closes(i)
            for t, day in enumerate(days):
                if t > ends.get(i, SESSIONS):
                    break
                close = prices[t]
                open_ = (prices[t - 1] if t else close) * (1 + 0.004 * noise(i, t, "o"))
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": round(open_, 4),
                        "high": round(max(open_, close) * 1.004, 4),
                        "low": round(min(open_, close) * 0.996, 4),
                        "close": close,
                        "adj_close": close,
                        "volume": volume(i),
                        "turnover": close * volume(i),
                        "turnover_status": "unknown"
                        if (i, t) == UNKNOWN_TURNOVER
                        else "available",
                        "source": "test",
                        "is_suspended": False,
                    }
                )
                if i != NO_CHIPS:
                    chips.append(
                        {
                            "instrument_id": i,
                            "trading_date": day,
                            "margin_balance": margin(i, t),
                            "source": "test",
                        }
                    )
        for t, (day, level) in enumerate(zip(days, index_levels())):
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": level,
                    "high": level,
                    "low": level,
                    "close": level,
                    "adj_close": level,
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
            insert(CorporateAction),
            [
                {
                    "instrument_id": 3,
                    "action_date": days[50],
                    "action_type": "corporate_action",
                    "cash_dividend": 1.0,
                    "stock_dividend_ratio": None,
                    "reference_price": 40.0,
                    "source": "test",
                }
            ],
        )
        db.commit()
    engine.dispose()
    return path


def member_rows() -> list[list]:
    rows = []
    for t in (0, 150):  # two snapshots
        day = trading_days()[t].isoformat()
        for i, code in GROUP_CODES.items():
            label = im.GROUP_LABELS["TWSE"][code]
            rows.append(
                [
                    day,
                    "TWSE",
                    code,
                    "",
                    label,
                    im.group_id(label),
                    f"S{i}",
                    f"N{i}",
                    im.retroactive("TWSE", code, day),
                ]
            )
    rows.sort()
    return rows


def write_members(folder: Path) -> Path:
    target = folder.joinpath(*ms.MEMBERS_DIR, ms.MEMBERS_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(im.table_bytes(member_rows(), "2013-01", "2013-08"))
    return target


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("round7")
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
def loaded(fixture_db, tmp_path_factory):
    days = trading_days()
    raw = tmp_path_factory.mktemp("raw")
    members = ms.members_path(fixture_db)
    return one_process(
        lambda: tool.load(fixture_db, members, date(1990, 1, 1), days[-1], raw)
    )


def test_y1_reads_the_margin_balance_in_lots_and_the_volume_in_shares(loaded):
    days = trading_days()
    item = loaded.panel.series[3]
    at = item.position[days[100]]
    # (1000 + 10 × 100 + 3) − (1000 + 10 × 80 + 3) = 200 lots
    by_hand = 200 * 1000 / volume(3)
    assert tool.margin_flow_20(loaded, item, at) == pytest.approx(by_hand, rel=1e-12)
    zero = loaded.panel.series[ZERO_MARGIN]
    assert tool.margin_flow_20(loaded, zero, zero.position[days[100]]) == 0.0
    no_chips = loaded.panel.series[NO_CHIPS]
    assert tool.margin_flow_20(loaded, no_chips, no_chips.position[days[100]]) is None
    null = loaded.panel.series[NULL_MARGIN[0]]
    for t, missing in ((99, False), (100, True), (120, True), (121, False)):
        value = tool.margin_flow_20(loaded, null, null.position[days[t]])
        assert (value is None) is missing, t


def test_y2_divides_the_unadjusted_turnover(loaded):
    days = trading_days()
    item = loaded.panel.series[3]
    at = item.position[days[260]]
    assert item.scale[at - 230] != pytest.approx(1.0)  # adjusted before session 50
    raw = [closes(3)[k] * volume(3) for k in range(at - 239, at + 1)]
    by_hand = statistics.stdev(raw) / statistics.fmean(raw)
    assert tool.turnover_cv_240(loaded, item, at) == pytest.approx(by_hand, rel=1e-9)
    adjusted = [item.close[k] * volume(3) for k in range(at - 239, at + 1)]
    assert tool.turnover_cv_240(loaded, item, at) != pytest.approx(
        statistics.stdev(adjusted) / statistics.fmean(adjusted), rel=1e-9
    )
    nine = loaded.panel.series[9]  # turnover_status unknown on session 100
    assert tool.turnover_cv_240(loaded, nine, nine.position[days[329]]) is None
    assert tool.turnover_cv_240(loaded, item, item.position[days[238]]) is None


def test_y3_uses_the_taiex_of_the_copy(loaded):
    days = trading_days()
    item = loaded.panel.series[3]
    assert tool.delay_52w(loaded, item, item.position[days[259]]) is None
    value = tool.delay_52w(loaded, item, item.position[days[260]])
    assert value is not None and 0 <= value <= 1
    gone = loaded.panel.series[27]  # its last bar is 250: a point without a bar
    assert 27 not in [i for i, _ in lib.universe(loaded.panel, days[260], 1000)]
    assert gone.position.get(days[260]) is None


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[199]),
            "validation": (days[200], days[279]),
            "used": (days[280], days[329]),
        },
    )
    floors = {"exploration": 100, "validation": 60}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("session", days[0], 61)}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(ms, "MEMBERS_SHA256", ex.file_sha256(ms.members_path(db)))
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    shutil.copytree(db.parent / ms.MEMBERS_DIR[0], folder / ms.MEMBERS_DIR[0])
    return Path(shutil.copy(db, folder / "stock.db"))


def explore(
    db: Path, out: Path, *extra: str, hypotheses: str | None = "Y1,Y2,Y3,Y4"
) -> int:
    chosen = [] if hypotheses is None else ["--hypotheses", hypotheses]
    return one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "exploration",
                "--min-free-gb",
                "0",
                *chosen,
                *extra,
            ]
        )  # fmt: skip
    )


def validate(db: Path, out: Path, report: Path | None, sha: str | None = None, url=URL):
    argv = ["--db", str(db), "--out", str(out), "--segment", "validation",
            "--min-free-gb", "0"]  # fmt: skip
    if report is not None:
        sha = sha if sha is not None else ex.file_sha256(report)
        argv += ["--exploration-report", str(report), "--exploration-sha256", sha]
        argv += ["--exploration-url", url]
    return one_process(lambda: tool.main(argv))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def refused(capsys) -> list[str]:
    return json.loads(capsys.readouterr().out)["refused"]


@pytest.fixture
def copied(fixture_db, tmp_path, monkeypatch) -> Path:
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path, db)
    return db


@pytest.fixture
def explored(copied, tmp_path):
    out = tmp_path / "exploration"
    assert explore(copied, out) == 0
    return copied, out


def passed_report(out: Path, tmp_path: Path, *names: str) -> Path:
    data = read_json(out / "explore.json")
    for name in NAMES:
        data["hypotheses"][name]["verdict"] = (
            ex.EXPLORATION_PASSED if name in names else ex.EXPLORATION_FAILED
        )
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return report


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round7_research",
        "912",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (7, 4, 30)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.144)
    assert report["read_until"] == trading_days()[199].isoformat()
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 4 個、累計 30 個" in text and "驗證段 t ≥ 3.144" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round7_research", 7, "exploration", 1) for name in NAMES]
    for name in NAMES:
        for file in (
            "summary.md",
            "tables.json",
            "equity.csv",
            "picks.csv",
            "trades.csv",
        ):
            assert (out / name / file).is_file(), (name, file)
    header = (out / "Y4" / "picks.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == (
        "signal_date,rank,exchange,symbol,turnover_60,ind_rev_20,"
        "momentum_20,industry_20,peers,tie"
    )


def test_y1_picks_the_largest_margin_decrease_first(explored):
    _db, out = explored
    day = trading_days()[150].isoformat()
    lines = (out / "Y1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "signal_date,rank,exchange,symbol,margin_flow_20,tie"
    rows = [line.split(",") for line in lines[1:] if line.startswith(day)]
    values = [float(row[4]) if row[4] else None for row in rows]
    valued = [v for v in values if v is not None]
    assert valued == sorted(valued) and len(rows) == 20
    assert rows[0][3] == f"S{ZERO_MARGIN}"  # 0 is below every increase


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="Y2") == 2
    assert any("Y2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_the_repository_ledger_refuses_the_exploration_too(copied, tmp_path, capsys):
    ex.write_ledger(
        ex.REPO_LEDGER,
        [
            {
                "hypothesis": "Y4",
                "tool": "round7_research",
                "segment": "exploration",
                "version": 1,
            }
        ],
    )
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="Y4") == 2
    assert any("Y4 already in" in line for line in refused(capsys))


def test_unregistered_or_w_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="Y1,W1") == 2
    assert any("W1 not registered" in line for line in refused(capsys))


def test_a_member_table_not_779s_is_refused_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ms, "MEMBERS_SHA256", "0" * 64)
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="Y4") == 2
    assert any("not the member table's" in line for line in refused(capsys))
    assert opened == [] and not (tmp_path / "x").exists()


def test_the_validation_needs_a_published_exploration_report(
    explored, tmp_path, capsys
):
    db, out = explored
    capsys.readouterr()
    assert validate(db, tmp_path / "v1", None) == 2
    assert any("needs --exploration-report" in line for line in refused(capsys))
    report = out / "explore.json"
    assert validate(db, tmp_path / "v2", report, sha="0" * 64) == 2
    assert any("not the published one" in line for line in refused(capsys))
    assert validate(db, tmp_path / "v3", report, url="https://example.com/x") == 2
    assert any("--exploration-url" in line for line in refused(capsys))
    for name in ("v1", "v2", "v3"):
        assert not (tmp_path / name).exists()


def test_the_validation_refuses_round_6s_report(explored, tmp_path, capsys):
    db, out = explored
    data = read_json(out / "explore.json")
    data["design"] = "903"
    data["hypotheses"]["Y1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_144(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "Y1")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("Y1", "round7_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["Y1"]
    assert validation["min_t"] == 3.144
    assert read_json(tmp_path / "validation" / "Y1" / "tables.json")["min_t"] == 3.144
    assert validation["read_until"] == trading_days()[279].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.144" in text
    capsys.readouterr()
    assert validate(db, tmp_path / "validation-2", report) == 2
    assert any("the validation runs once" in line for line in refused(capsys))
    assert not (tmp_path / "validation-2").exists()


def test_the_validation_needs_the_research_marker(explored, tmp_path, capsys):
    db, out = explored
    (db.parent / "research-db.json").unlink()
    capsys.readouterr()
    assert validate(db, tmp_path / "v", out / "explore.json") == 2
    assert any("research marker" in line for line in refused(capsys))


def test_a_passed_validation_lets_its_panel_go_before_the_used_segment(
    explored, tmp_path, monkeypatch
):
    """Only one panel at a time: the validation's is collected before the used
    segment is loaded (PR #905 review 7053124013), and the used segment of the
    passed hypothesis is written."""

    db, out = explored
    real_judge, real_load = ex.explore_judge, tool.load

    def judge(stage, *args, **kwargs):
        verdict = real_judge(stage, *args, **kwargs)
        return ex.PASSED if stage == "validation" else verdict

    loads: list[tuple] = []  # (start, end, weakref to the panel, earlier ones alive)

    def spy(db, members, start, end, raw_dir):
        alive = [ref() is not None for _s, _e, ref, _a in loads]
        ctx = real_load(db, members, start, end, raw_dir)
        loads.append((start, end, weakref.ref(ctx.panel), alive))
        return ctx

    monkeypatch.setattr(ex, "explore_judge", judge)
    monkeypatch.setattr(tool, "load", spy)
    report = passed_report(out, tmp_path, "Y4")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    warmup = timedelta(days=tool.WARMUP_CALENDAR_DAYS)
    assert [(start, end) for start, end, _r, _a in loads] == [
        (days[200] - warmup, days[279]),
        (days[280] - warmup, days[329]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["Y4"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["Y4"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "Y4" / "used" / file).is_file(), file
    assert "## 已用段" in (tmp_path / "validation" / "explore.md").read_text(
        encoding="utf-8"
    )


def test_coverage_only_computes_no_return(copied, tmp_path):
    out = tmp_path / "coverage"
    assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    text = json.dumps(body)
    for word in ("excess", "absolute", "verdict", "equity"):
        assert word not in text
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)
    year = {name: body["hypotheses"][name]["coverage"]["2013"] for name in NAMES}
    days = year["Y1"]["days"]
    assert days == 139  # signal dates 60 .. 198, all in 2013
    # Y1 by market: TPEx stock 4 has no chip row; TWSE stock 5's null balance
    # on session 100 is read on T = 100 and T = 120
    markets = year["Y1"]["markets"]
    assert markets["TPEx"]["missing"] == days
    assert markets["TWSE"]["missing"] == 2
    assert year["Y1"]["missing"]["margin_flow_20"] == days + 2
    # Y2 needs 240 bars and Y3 260 sessions: none before session 200
    assert year["Y2"]["missing"]["turnover_cv_240"] == year["Y2"]["members"]
    assert year["Y3"]["missing"]["delay_52w"] == year["Y3"]["members"]
    assert year["Y3"]["no_index_days"] == days
    # Y4: 25～27 have no group; the population is at most 27, all with a
    # turnover_60 in the 150
    reasons = year["Y4"]["reasons"]
    assert reasons["momentum"] == 0 and reasons["few_peers"] == 0
    assert reasons["no_group"] == year["Y4"]["members"] - 24 * days
    # stock 9's unknown turnover (session 100) keeps it out on T = 100 .. 159
    assert year["Y4"]["subset"] == year["Y4"]["members"] - 60
    seconds = body["hypotheses"]["Y3"]["seconds"]
    assert set(seconds) == {"plan", "delay_52w"} and seconds["plan"] >= 0
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    y1 = md.split("## Y1", 1)[1].split("## Y2", 1)[0]
    assert "### Y1 第 6 點：依年、依市場的 `margin_flow_20` 缺值比例" in y1
    assert f"| 2013 | {markets['TWSE']['members']:,} |" in y1
    assert f"| {tool._share(days, markets['TPEx']['members'])} |" in y1


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "Y1"]
        )  # fmt: skip


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
    copied, tmp_path, monkeypatch, capsys
):
    opened = no_reads(monkeypatch)
    out = tmp_path / "out"
    copied.parent.chmod(0o555)
    try:
        assert explore(copied, out, hypotheses="Y1") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "Y1")
    ledger = db.parent / ex.LEDGER_NAME
    before = ledger.read_bytes()
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    db.parent.chmod(0o555)
    ledger.chmod(0o444)
    try:
        assert validate(db, tmp_path / "v", report) == 2
    finally:
        ledger.chmod(0o644)
        db.parent.chmod(0o755)
    assert unwritable(refused(capsys), db)
    assert opened == [] and not (tmp_path / "v").exists()
    assert ledger.read_bytes() == before


@READ_ONLY
def test_coverage_only_runs_on_a_read_only_ledger_folder(copied, tmp_path):
    out = tmp_path / "coverage"
    copied.parent.chmod(0o555)
    try:
        assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    finally:
        copied.parent.chmod(0o755)
    assert (out / "coverage.json").is_file()
