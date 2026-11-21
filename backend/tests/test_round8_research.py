"""tools/research/round8_research.py: the registered Z1～Z4 (#918).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第八輪：Z1～Z4.  The features and the order are checked
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
import sys
import weakref
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import Base, CorporateAction, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/918#issuecomment-1"
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
r5 = _tool("round5_research")
r6 = _tool("round6_research")
r7 = _tool("round7_research")
tool = _tool("round8_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAMES = ("Z1", "Z2", "Z3", "Z4")


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for other in (ex, r5, r6, r7):
        assert not set(h) & set(other.HYPOTHESES)
    rows = {
        name: (spec["subset"], spec["keys"], spec["top"], spec["hold"], spec["start"])
        for name, spec in h.items()
    }
    otc = date(2007, 12, 3)
    assert rows == {
        "Z1": (None, (("abvol_5_60", "high"),), 20, 20, ("session", otc, 65)),
        "Z2": (None, (("skew_240", "low"),), 20, 60, ("session", otc, 241)),
        "Z3": (None, (("beta_240", "low"),), 20, 60, ("session", otc, 242)),
        "Z4": (None, (("overnight_20", "low"),), 20, 20, ("session", otc, 21)),
    }
    assert all(spec["rule"] == "daily" for spec in h.values())


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (1, 8, 4, 34)
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.180
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(34), 3) == 3.180
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "df0aa8b5"
    assert (tool.ABVOL_RECENT, tool.ABVOL_BASE) == (5, 60)
    assert (tool.SKEW_RETURNS, tool.BETA_SESSIONS, tool.BETA_DAYS) == (240, 242, 240)
    assert tool.OVERNIGHT_TERMS == 20


def test_the_definitions_hash_holds_the_threshold_and_the_windows(monkeypatch):
    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.180
    for name, value in (
        ("VALIDATION_MIN_T", 3.144),
        ("ABVOL_BASE", 59),
        ("SKEW_RETURNS", 239),
        ("BETA_DAYS", 239),
        ("OVERNIGHT_TERMS", 19),
        ("MARKET_DEGENERATE", "x"),
    ):
        with monkeypatch.context() as m:
            m.setattr(tool, name, value)
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
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master df0aa8b5 before this tool existed.
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
    "round6_research": (
        1,
        "b8e1eb89a20b9ea97db4d6ba38a1461d5ff5bf05b26eb9619c353db7020ac51e",
    ),
    "round7_research": (
        1,
        "180c21a4307b5cfd16db0b246478f5da3406a9779b0956dfc13cb32dc0cd47d7",
    ),
}


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


def test_the_docs_tool_section_says_what_the_program_does():
    """The degenerate criteria and the coverage wording are the program's
    strings (PR #913 review: the docs were wider than the code)."""

    text = (ROOT / "docs" / "spec" / "evidence.md").read_text(encoding="utf-8")
    section = text.split("**第八輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for phrase in (
        tool.SKEW_DEGENERATE,
        tool.MARKET_DEGENERATE,
        tool.NO_MARKET_NOTE,
        tool.MISSING_SHARE_NOTE,
        f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}",
    ):
        assert phrase in section, phrase


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
    opens=None,
    sessions=None,
):
    """A series on ``dates`` (weekdays by default); ``sessions`` the market
    session index of each bar (its position by default); the opens are the
    closes unless given."""

    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2014, 1, 1), len(closes))
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at if sessions is None else sessions[at])
        item.open.append(close if opens is None else opens[at])
        for name in ("high", "low", "close"):
            getattr(item, name).append(close)
        item.volume.append(1.0 if volumes is None else float(volumes[at]))
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    return item


def context_for(items, sessions=None, index=None, symbols=None):
    series = {item.instrument_id: item for item in items}
    raw = {item.instrument_id: ([], [], list(item.close), []) for item in items}
    panel = lib.Panel(sessions or [], series, {}, index or {}, symbols or {})
    return tool.Context(ex.Context(pr.Market(panel, raw, {}, None)))


def sorted_ids(spec_name: str, values: dict[int, float | None], day: date) -> list[int]:
    keys = tool.HYPOTHESES[spec_name]["keys"]
    name = keys[0][0]
    rows = [(i, {name: v}, pr.tie_break(day, i)) for i, v in values.items()]
    rows.sort(key=lambda row: tool.order_key(row[1], keys, row[2]))
    return [row[0] for row in rows]


def test_the_order_is_high_or_small_first_with_a_missing_value_last():
    day = date(2015, 3, 2)
    values = {1: 0.3, 2: None, 3: -0.2, 4: 0.3, 5: 0.0}
    tied = sorted((1, 4), key=lambda i: pr.tie_break(day, i))
    assert sorted_ids("Z1", values, day) == [*tied, 5, 3, 2]  # high first
    for name in ("Z2", "Z3", "Z4"):
        assert sorted_ids(name, values, day) == [3, 5, *tied, 2]


# --- Z1 -------------------------------------------------------------------------


def z1(volumes, suspended=(), at=None):
    item = make_item([10.0] * len(volumes), volumes=volumes, suspended=suspended)
    at = len(volumes) - 1 if at is None else at
    return tool.abvol_5_60(context_for([item]), item, at)


def test_abvol_5_60_is_the_5_bar_mean_over_the_60_bars_before_them():
    # at = 64: at − 64 .. at − 5 are 60 bars of 100 and 300, at − 4 .. at 5 bars
    base = [100.0, 300.0] * 30  # mean 200
    recent = [400.0, 500.0, 600.0, 700.0, 800.0]  # mean 600
    assert z1(base + recent) == pytest.approx(600 / 200, rel=1e-12, abs=0)
    # a bar before at − 64 is not read
    assert z1([10.0**9, *base, *recent]) == pytest.approx(3.0, rel=1e-12, abs=0)
    # the 5th bar from the end belongs to the numerator, the 6th to the denominator
    shifted = base[:-1] + [0.0] + recent
    assert z1(shifted) == pytest.approx(600 / (sum(base[:-1]) / 60), rel=1e-12)


def test_abvol_5_60_needs_at_64():
    volumes = [100.0] * 65
    assert z1(volumes) == pytest.approx(1.0)
    assert z1(volumes, at=63) is None


@pytest.mark.parametrize("where", [0, 30, 59, 60, 64])
def test_abvol_5_60_is_missing_with_a_suspended_bar_in_the_65(where):
    assert z1([100.0] * 65, suspended=(where,)) is None


def test_abvol_5_60_reads_no_bar_before_the_65():
    assert z1([100.0] * 66, suspended=(0,)) == pytest.approx(1.0)


def test_abvol_5_60_is_missing_with_a_denominator_not_positive():
    assert z1([0.0] * 60 + [100.0] * 5) is None
    assert z1([100.0] * 60 + [0.0] * 5) == 0.0  # a numerator of 0 is a value


# --- Z2 -------------------------------------------------------------------------


def wave(salt: str, start: int = -10, stop: int = 400, size: float = 0.04):
    """A random walk on sessions ``start`` .. ``stop`` (independent daily moves)."""

    levels, level = {}, 100.0
    for s in range(start, stop):
        digest = hashlib.sha256(f"{salt}:{s}".encode()).digest()
        level *= 1.0 + size * (digest[0] / 255.0 - 0.5)
        levels[s] = level
    return levels.__getitem__


def population_skew(returns: list[float]) -> float:
    """By hand: the population moments with n = len(returns)."""

    n = len(returns)
    mean = math.fsum(returns) / n
    second = math.fsum((r - mean) ** 2 for r in returns) / n
    third = math.fsum((r - mean) ** 3 for r in returns) / n
    return third / second**1.5


def z2(closes, suspended=(), at=None):
    item = make_item(closes, suspended=suspended)
    at = len(closes) - 1 if at is None else at
    return tool.skew_240(context_for([item]), item, at)


def test_skew_240_is_the_population_skewness_of_240_returns():
    walk = wave("skew")
    closes = [walk(s) for s in range(241)]
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, 241)]
    assert len(returns) == 240
    by_hand = population_skew(returns)
    assert z2(closes) == pytest.approx(by_hand, rel=1e-9, abs=1e-12)
    # n = 240, not the sample correction n − 1
    corrected = by_hand * math.sqrt(240 * 239) / 238
    assert z2(closes) != pytest.approx(corrected, rel=1e-6)


def test_skew_240_of_a_hand_made_window():
    # 239 returns of +1% and one of −10%: a long left tail
    closes = [100.0]
    for i in range(240):
        closes.append(closes[-1] * (0.9 if i == 100 else 1.01))
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, 241)]
    assert z2(closes) == pytest.approx(population_skew(returns), rel=1e-9)
    assert z2(closes) < -10


def test_skew_240_needs_241_bars():
    closes = [wave("skew")(s) for s in range(241)]
    assert z2(closes) is not None
    assert z2(closes, at=239) is None


@pytest.mark.parametrize("where", [0, 120, 240])
@pytest.mark.parametrize("bad", [NAN, 0.0, -1.0])
def test_skew_240_is_missing_with_a_close_missing_or_not_positive(where, bad):
    closes = [wave("skew")(s) for s in range(241)]
    closes[where] = bad
    assert z2(closes) is None


@pytest.mark.parametrize("where", [0, 120, 240])
def test_skew_240_is_missing_with_a_suspended_bar_in_the_241(where):
    closes = [wave("skew")(s) for s in range(241)]
    assert z2(closes, suspended=(where,)) is None


def test_skew_240_reads_no_bar_before_the_241():
    closes = [wave("skew")(s) for s in range(242)]
    closes[0] = NAN
    assert z2(closes, suspended=(0,)) is not None


def test_skew_240_is_missing_when_the_second_moment_is_exactly_0():
    assert z2([50.0] * 241) is None  # every return 0: m2 is 0.0
    assert z2([50.0] * 240 + [50.5]) is not None  # one move: not degenerate


# --- Z3 -------------------------------------------------------------------------

INDEX = wave("index", size=0.03)
N_SESSIONS = 250  # T is the last; the 242 sampling sessions are 8 .. 249


def z3_context(
    stock,
    index=INDEX,
    skip=(),
    suspended=(),
    index_missing=(),
    n=N_SESSIONS,
):
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
    return ctx, item, item.position[sessions[-1]]


def z3(stock, **kwargs):
    ctx, item, at = z3_context(stock, **kwargs)
    return tool.beta_240(ctx, item, at)


def ols(y: list[float], xs: list[list[float]]) -> list[float]:
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
    return beta


def sampled(close, n=N_SESSIONS) -> list[float]:
    """The returns of the 242 sampling sessions, j = 1 .. 241 (index j − 1)."""

    points = range(n - 242, n)
    values = [close(s) for s in points]
    return [values[j] / values[j - 1] - 1 for j in range(1, 242)]


def test_beta_240_is_b0_plus_b1_of_the_dimson_regression():
    stock = wave("stock")
    mixed = lambda s: stock(s) * INDEX(s) ** 0.7 * INDEX(s - 1) ** 0.4  # noqa: E731
    r, m = sampled(mixed), sampled(INDEX)
    # the latest 240 days j = 2 .. 241: r_j on m_j and m_{j−1}
    y = r[1:]
    same, lag = m[1:], m[:-1]
    assert len(y) == len(same) == len(lag) == 240
    _a, b0, b1 = ols(y, [same, lag])
    ctx, item, at = z3_context(mixed)
    assert tool.dimson(ctx, item, at) == pytest.approx((b0, b1), rel=1e-9, abs=1e-12)
    assert tool.beta_240(ctx, item, at) == pytest.approx(b0 + b1, rel=1e-9, abs=1e-12)
    assert 0.5 < b0 + b1 < 1.6


def test_beta_240_is_1_when_the_stock_moves_with_the_index():
    ctx, item, at = z3_context(lambda s: 3.0 * INDEX(s))
    b0, b1 = tool.dimson(ctx, item, at)
    assert (b0, b1) == pytest.approx((1.0, 0.0), abs=1e-9)
    assert tool.beta_240(ctx, item, at) == pytest.approx(1.0, abs=1e-9)


def test_beta_240_puts_a_one_day_lag_in_b1():
    ctx, item, at = z3_context(lambda s: INDEX(s - 1))  # r_j = m_{j−1}
    b0, b1 = tool.dimson(ctx, item, at)
    assert b0 == pytest.approx(0.0, abs=1e-9)
    assert b1 == pytest.approx(1.0, abs=1e-9)
    assert tool.beta_240(ctx, item, at) == pytest.approx(1.0, abs=1e-9)


def test_beta_240_samples_the_242_market_sessions():
    stock = wave("stock")
    first = N_SESSIONS - 242
    # a bar or a TAIEX close before the 242 sampling sessions is not read
    assert z3(stock, skip=(first - 1,)) == pytest.approx(z3(stock), rel=1e-12)
    assert z3(stock, index_missing=(first - 1,)) == pytest.approx(z3(stock), rel=1e-12)
    assert z3(stock, n=242) is not None
    assert z3(stock, n=241) is None  # 241 sessions: T − 241 is before the copy


@pytest.mark.parametrize("j", [0, 1, 120, 240])
def test_beta_240_is_missing_without_a_bar_at_a_sampling_session(j):
    """T itself always has a bar (it is in the population); a session of the
    market without this stock's bar, even with 242 bars of its own before T."""

    stock = wave("stock")
    s = N_SESSIONS - 242 + j
    assert z3(stock, skip=(s,)) is None


@pytest.mark.parametrize("j", [0, 1, 120, 241])
def test_beta_240_is_missing_with_a_bad_sampling_day(j):
    stock = wave("stock")
    s = N_SESSIONS - 242 + j
    assert z3(stock, suspended=(s,)) is None
    assert z3(lambda t: 0.0 if t == s else stock(t)) is None
    assert z3(lambda t: NAN if t == s else stock(t)) is None
    assert z3(stock, index_missing=(s,)) is None
    assert z3(stock, index=lambda t: 0.0 if t == s else INDEX(t)) is None


def flat_index(*steps: int):
    """A TAIEX of 100 that steps up 1% on the given sampling days and stays:
    only m_j of those days is not 0."""

    first = N_SESSIONS - 242
    return lambda s: 100.0 * 1.01 ** sum(1 for d in steps if s - first >= d)


def test_beta_240_is_missing_when_a_market_column_has_no_variance():
    stock = wave("stock")
    # only m_1 moves: the same-day column m_2 .. m_241 is all 0, S00 = 0
    assert z3(stock, index=flat_index(1)) is None
    # only m_241 moves: the lag column m_1 .. m_240 is all 0, S11 = 0
    assert z3(stock, index=flat_index(241)) is None
    # the flat index: both 0
    assert z3(stock, index=lambda s: 100.0) is None
    # two moves inside: both columns vary, not collinear
    assert z3(stock, index=flat_index(60, 180)) is not None


def test_the_market_weights_refuse_exactly_collinear_columns_only():
    same = [math.sin(j) * 0.01 for j in range(240)]
    assert tool.market_weights(same, [2.0 * v for v in same]) is None  # det = 0
    assert tool.market_weights(same, [0.0] * 240) is None  # S11 = 0
    assert tool.market_weights([0.5] * 240, same) is None  # S00 = 0
    # nearly collinear (det > 0 but tiny) is not caught
    near = [2.0 * v + (1e-9 if j == 7 else 0.0) for j, v in enumerate(same)]
    assert tool.market_weights(same, near) is not None


def test_the_market_part_is_computed_once_a_day(monkeypatch):
    calls = []
    real = tool.market_weights
    monkeypatch.setattr(tool, "market_weights", lambda *a: calls.append(1) or real(*a))
    ctx, item, at = z3_context(wave("stock"))
    assert tool.beta_240(ctx, item, at) == tool.beta_240(ctx, item, at)
    assert len(calls) == 1


# --- Z4 -------------------------------------------------------------------------


def z4(opens, closes, suspended=(), at=None):
    item = make_item(closes, opens=opens, suspended=suspended)
    at = len(closes) - 1 if at is None else at
    return tool.overnight_20(context_for([item]), item, at)


def z4_bars(n=21):
    closes = [100.0 + i for i in range(n)]
    opens = [closes[i - 1] * (1 + 0.001 * (i % 5 - 2)) if i else 99.0 for i in range(n)]
    return opens, closes


def test_overnight_20_sums_the_20_logs_of_open_over_the_previous_close():
    opens, closes = z4_bars()
    by_hand = math.fsum(math.log(opens[i] / closes[i - 1]) for i in range(1, 21))
    assert z4(opens, closes) == pytest.approx(by_hand, rel=1e-12, abs=1e-15)
    # the open of at − 20 and the close of at are not read
    opens[0], closes[20] = NAN, NAN
    assert z4(opens, closes) == pytest.approx(by_hand, rel=1e-12, abs=1e-15)


def test_overnight_20_of_opens_at_the_previous_close_is_0():
    closes = [100.0 + i for i in range(21)]
    opens = [closes[i - 1] if i else 100.0 for i in range(21)]
    assert z4(opens, closes) == 0.0


def test_overnight_20_needs_at_20():
    opens, closes = z4_bars()
    assert z4(opens, closes, at=19) is None
    assert z4(opens, closes, at=20) is not None


@pytest.mark.parametrize("where", [0, 10, 20])
def test_overnight_20_is_missing_with_a_suspended_bar_in_the_21(where):
    opens, closes = z4_bars()
    assert z4(opens, closes, suspended=(where,)) is None


def test_overnight_20_reads_no_bar_before_the_21():
    opens, closes = z4_bars(22)
    assert z4(opens, closes, suspended=(0,)) is not None


@pytest.mark.parametrize("bad", [NAN, 0.0, -1.0])
@pytest.mark.parametrize("where", [1, 20])
def test_overnight_20_is_missing_with_an_open_missing_or_not_positive(where, bad):
    opens, closes = z4_bars()
    opens[where] = bad
    assert z4(opens, closes) is None


@pytest.mark.parametrize("bad", [NAN, 0.0, -1.0])
@pytest.mark.parametrize("where", [0, 19])
def test_overnight_20_is_missing_with_a_close_missing_or_not_positive(where, bad):
    opens, closes = z4_bars()
    closes[where] = bad
    assert z4(opens, closes) is None


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
        (3.144, "前瞻觀察"),  # round 7's threshold is not this round's
        (3.179, "前瞻觀察"),
        (3.180, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_180(t, verdict):
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
# Stock 28 trades flat at 40 and goes ex-dividend 1 on session EX_DAY, opening
# at 39 = 40 − 1 and staying there: no other price change (docs 第八輪實作釋義).
DIVIDEND, EX_DAY, CASH = 28, 150, 1.0


def trading_days() -> list[date]:
    return weekdays(date(2013, 1, 1), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int) -> list[float]:
    if i == DIVIDEND:
        return [40.0 if t < EX_DAY else 40.0 - CASH for t in range(SESSIONS)]
    level, out = 50.0 + i, []
    for t in range(SESSIONS):
        level *= 1.0 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)
        out.append(round(level, 4))
    return out


def opens(i: int) -> list[float]:
    prices = closes(i)
    if i == DIVIDEND:
        return [prices[t - 1] - (CASH if t == EX_DAY else 0.0) if t else 40.0
                for t in range(SESSIONS)]  # fmt: skip
    return [
        round((prices[t - 1] if t else prices[t]) * (1 + 0.004 * noise(i, t, "o")), 4)
        for t in range(SESSIONS)
    ]


def index_levels() -> list[float]:
    level, out = 8000.0, []
    for t in range(SESSIONS):
        level *= 1.0 + 0.01 * noise(0, t, "index")
        out.append(round(level, 2))
    return out


def volume(i: int, t: int) -> int:
    surge = 3 if (i, t) == (5, 100) else 1  # stock 5's volume triples on 100
    return (2_000_000 + 10_000 * i) * surge


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ends = {**DELISTED, **TRANSFERRED}
    ids = [*STOCKS, *ends, DIVIDEND]
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
        bars = []
        for i in ids:
            prices, starts = closes(i), opens(i)
            for t, day in enumerate(days):
                if t > ends.get(i, SESSIONS):
                    break
                close, open_ = prices[t], starts[t]
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": open_,
                        "high": round(max(open_, close) * 1.004, 4),
                        "low": round(min(open_, close) * 0.996, 4),
                        "close": close,
                        "adj_close": close,
                        "volume": volume(i, t),
                        "turnover": close * volume(i, t),
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": False,
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
        db.execute(
            insert(CorporateAction),
            [
                {
                    "instrument_id": DIVIDEND,
                    "action_date": days[EX_DAY],
                    "action_type": "corporate_action",
                    "cash_dividend": CASH,
                    "stock_dividend_ratio": None,
                    "reference_price": 40.0,
                    "source": "test",
                }
            ],
        )
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round8") / "stock.db")


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
    return one_process(lambda: tool.load(fixture_db, date(1990, 1, 1), days[-1], raw))


def test_z4_on_the_ex_dividend_day_is_0_on_the_adjusted_prices(loaded):
    """docs 第八輪實作釋義 Z4 的還原基準: the ex-dividend open and the close
    before it are on one basis, so a day with no other price change adds 0."""

    item = loaded.panel.series[DIVIDEND]
    days = trading_days()
    ex_at = item.position[days[EX_DAY]]
    # the raw open is 1 below the raw close before (the dividend) ...
    assert item.open[ex_at] / item.scale[ex_at] == pytest.approx(39.0)
    assert item.close[ex_at - 1] / item.scale[ex_at - 1] == pytest.approx(40.0)
    assert item.scale[ex_at - 1] == pytest.approx(39 / 40) and item.scale[ex_at] == 1.0
    # ... and on the adjusted prices that overnight term is 0
    assert math.log(item.open[ex_at] / item.close[ex_at - 1]) == pytest.approx(
        0.0, abs=1e-12
    )
    for at in (ex_at, ex_at + 5, ex_at + 19):  # the ex day inside the 20 terms
        value = tool.overnight_20(loaded, item, at)
        assert value == pytest.approx(0.0, abs=1e-12), at
    # the unadjusted prices would have put ln(39 ÷ 40) in it
    assert math.log(39 / 40) < -0.02


def test_z1_reads_the_volume_in_shares(loaded):
    days = trading_days()
    item = loaded.panel.series[5]
    at = item.position[days[102]]  # 100 is in at − 4 .. at
    by_hand = (1 + 1 + 3 + 1 + 1) / 5  # over the 60 bars before them, all 1
    assert tool.abvol_5_60(loaded, item, at) == pytest.approx(by_hand, rel=1e-12)
    at = item.position[days[160]]  # 100 is in at − 64 .. at − 5
    assert tool.abvol_5_60(loaded, item, at) == pytest.approx(60 / 62, rel=1e-12)


def test_z2_and_z3_on_the_copy(loaded):
    days = trading_days()
    item = loaded.panel.series[3]
    assert tool.skew_240(loaded, item, item.position[days[239]]) is None
    assert tool.skew_240(loaded, item, item.position[days[240]]) is not None
    assert tool.beta_240(loaded, item, item.position[days[240]]) is None
    assert tool.beta_240(loaded, item, item.position[days[241]]) is not None
    flat = loaded.panel.series[DIVIDEND]  # adjusted closes all 39: m2 is 0
    assert tool.skew_240(loaded, flat, flat.position[days[300]]) is None
    assert tool.beta_240(loaded, flat, flat.position[days[300]]) == pytest.approx(
        0.0, abs=1e-12
    )


def compressed(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    return Path(shutil.copy(db, folder / "stock.db"))


def explore(
    db: Path, out: Path, *extra: str, hypotheses: str | None = "Z1,Z2,Z3,Z4"
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
    compressed(monkeypatch, tmp_path)
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
        "round8_research",
        "918",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (8, 4, 34)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.18)
    assert report["read_until"] == trading_days()[199].isoformat()
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 4 個、累計 34 個" in text and "驗證段 t ≥ 3.180" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round8_research", 8, "exploration", 1) for name in NAMES]
    for name in NAMES:
        for file in (
            "summary.md",
            "tables.json",
            "equity.csv",
            "picks.csv",
            "trades.csv",
        ):
            assert (out / name / file).is_file(), (name, file)
    header = (out / "Z3" / "picks.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "signal_date,rank,exchange,symbol,beta_240,tie"


def test_z1_picks_the_largest_volume_surge_first(explored):
    _db, out = explored
    day = trading_days()[100].isoformat()
    lines = (out / "Z1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    rows = [line.split(",") for line in lines[1:] if line.startswith(day)]
    values = [float(row[4]) for row in rows]
    assert values == sorted(values, reverse=True) and len(rows) == 20
    assert rows[0][3] == "S5"  # its volume tripled on T


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="Z2") == 2
    assert any("Z2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_the_repository_ledger_refuses_the_exploration_too(copied, tmp_path, capsys):
    ex.write_ledger(
        ex.REPO_LEDGER,
        [
            {
                "hypothesis": "Z4",
                "tool": "round8_research",
                "segment": "exploration",
                "version": 1,
            }
        ],
    )
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="Z4") == 2
    assert any("Z4 already in" in line for line in refused(capsys))


def test_unregistered_or_y_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="Z1,Y1") == 2
    assert any("Y1 not registered" in line for line in refused(capsys))


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


def test_the_validation_refuses_round_7s_report(explored, tmp_path, capsys):
    db, out = explored
    data = read_json(out / "explore.json")
    data["design"] = "912"
    data["hypotheses"]["Z1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_180(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "Z1")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("Z1", "round8_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["Z1"]
    assert validation["min_t"] == 3.18
    assert read_json(tmp_path / "validation" / "Z1" / "tables.json")["min_t"] == 3.18
    assert validation["read_until"] == trading_days()[279].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.180" in text
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

    def spy(db, start, end, raw_dir):
        alive = [ref() is not None for _s, _e, ref, _a in loads]
        ctx = real_load(db, start, end, raw_dir)
        loads.append((start, end, weakref.ref(ctx.panel), alive))
        return ctx

    monkeypatch.setattr(ex, "explore_judge", judge)
    monkeypatch.setattr(tool, "load", spy)
    report = passed_report(out, tmp_path, "Z3")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    warmup = timedelta(days=tool.WARMUP_CALENDAR_DAYS)
    assert [(start, end) for start, end, _r, _a in loads] == [
        (days[200] - warmup, days[279]),
        (days[280] - warmup, days[329]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["Z3"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["Z3"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "Z3" / "used" / file).is_file(), file
    assert "## 已用段" in (tmp_path / "validation" / "explore.md").read_text(
        encoding="utf-8"
    )


def test_a_forward_watch_verdict_runs_no_used_segment(explored, tmp_path, monkeypatch):
    db, out = explored
    loads = []
    real_load = tool.load
    monkeypatch.setattr(tool, "load", lambda *a: loads.append(a[1]) or real_load(*a))
    monkeypatch.setattr(ex, "explore_judge", lambda *a, **k: ex.FORWARD_WATCH)
    report = passed_report(out, tmp_path, "Z2")
    assert validate(db, tmp_path / "validation", report) == 0
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["Z2"]["verdict"] == ex.FORWARD_WATCH
    assert "used" not in validation and len(loads) == 1


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
    days = year["Z1"]["days"]
    assert days == 139  # signal dates 60 .. 198, all in 2013
    # Z1 needs at ≥ 64: T = 60 .. 63 for the 28 stocks, all with bars from 0
    assert year["Z1"]["missing"]["abvol_5_60"] == 4 * 28
    # Z2 needs 241 bars and Z3 242 sessions: none before session 200
    assert year["Z2"]["missing"]["skew_240"] == year["Z2"]["members"]
    assert year["Z3"]["missing"]["beta_240"] == year["Z3"]["members"]
    assert year["Z3"]["no_market_days"] == days
    assert year["Z4"]["missing"]["overnight_20"] == 0
    seconds = body["hypotheses"]["Z3"]["seconds"]
    assert set(seconds) == {"plan", "beta_240"} and seconds["plan"] >= 0
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    assert tool.NO_MARKET_NOTE in md and tool.SKEW_DEGENERATE in md
    z3 = md.split("## Z3", 1)[1].split("## Z4", 1)[0]
    assert "大盤部分缺值的訊號日" in z3 and f"| 2013 | {days:,} |" in z3


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "Z1"]
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


def test_an_unwritable_ledger_refuses_the_exploration_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    """On any platform: the gate's ledger check is the one #899 added."""

    problem = "x/explore-ledger.json is not writable"
    monkeypatch.setattr(ex, "ledger_write_problem", lambda db: problem)
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    assert explore(copied, tmp_path / "out", hypotheses="Z1") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "Z1")
    problem = "x/explore-ledger.json is not writable"
    monkeypatch.setattr(ex, "ledger_write_problem", lambda db: problem)
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "v").exists()


@READ_ONLY
def test_a_read_only_ledger_folder_refuses_the_exploration_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    opened = no_reads(monkeypatch)
    out = tmp_path / "out"
    copied.parent.chmod(0o555)
    try:
        assert explore(copied, out, hypotheses="Z1") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "Z1")
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
