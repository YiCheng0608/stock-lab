"""#752: the streamed ``portfolio_research.load_market`` is the old one, byte for byte.

``reference_load_market`` below is a reference implementation kept only for
this equivalence check: the body of ``load_market`` before #752 (the whole
``research_report.benchmark_universe`` read first, ``raw`` as lists).  It
calls the unchanged ``benchmark_universe``, ``load_actions`` and
``evidence_lib._series``; only the part that built the series and ``raw``
from them is copied.

On the fixtures of ``test_explore_research``, ``test_trade_research`` and
``test_portfolio_research`` the old and the new loader give the same panel
(every ``Series`` field, ``raw``, ``listed`` and its order), and the tools run
with each give the same outputs: ``explore.json`` without ``VOLATILE_KEYS``,
every hypothesis's ``tables.json``, ``trades.csv``, ``picks.csv`` and the
rest (decision 6886660983).
"""

from __future__ import annotations

from array import array
from datetime import date

import pytest
import test_explore_research as te
import test_portfolio_research as tp
import test_trade_research as tt
from test_explore_research import explore_db  # noqa: F401 - fixture
from test_portfolio_research import copy_db  # noqa: F401 - fixture
from test_trade_research import golden_db  # noqa: F401 - fixture

FLOAT_FIELDS = ("open", "high", "low", "close", "volume", "scale")


def reference_load_market(pr):
    """``pr.load_market`` as it was before #752 (reference for this test only)."""

    lib = pr.lib

    def load_market(db, start, raw_dir, fundamentals=False, end=None):
        report = lib.research_report()
        con = lib.connect_read_only(db)
        try:
            instruments, listed = report.benchmark_universe(con, start, end)
            sessions = report.market_sessions(con, start, end)
            index_close = report.index_closes(con, start, end)
            factor_of = report.load_actions(db, instruments, start, raw_dir, end)
            session_index = {day: index for index, day in enumerate(sessions)}
            series = {
                instrument_id: lib._series(
                    instrument_id, instrument, factor_of, session_index
                )
                for instrument_id, instrument in instruments.items()
            }
            raw = {}
            for instrument_id, instrument in instruments.items():
                kept = [
                    bar for bar in instrument.bars if bar.trading_date in session_index
                ]
                raw[instrument_id] = (
                    [bar.low or 0.0 for bar in kept],
                    [bar.high or 0.0 for bar in kept],
                    [bar.close or 0.0 for bar in kept],
                    [bool(bar.is_suspended) for bar in kept],
                )
            lib._load_chips(con, series, start, end)
            if fundamentals:
                lib._load_revenues(con, series, end)
                lib._load_quarters(con, series, end)
            symbols, kinds, listings = {}, {}, {}
            for instrument_id, exchange, symbol, name, kind in con.execute(
                "select id, exchange, symbol, name, instrument_type from instruments"
            ):
                kinds[instrument_id] = kind
                listings[instrument_id] = symbol
                if instrument_id in series:
                    symbols[instrument_id] = (exchange, symbol, name)
        finally:
            con.close()
        from app.strategies import levels

        return pr.Market(
            lib.Panel(sessions, series, dict(listed), index_close, symbols),
            raw,
            kinds,
            levels,
            listings,
        )

    return load_market


def _bits(values) -> bytes:
    return array("d", values).tobytes()  # NaN-safe: the same bits


def assert_same_market(old, new) -> None:
    a, b = old.panel, new.panel
    assert a.sessions == b.sessions
    assert list(a.series) == list(b.series)
    assert list(a.listed) == list(b.listed)
    assert a.listed == b.listed
    assert a.index_close == b.index_close and a.symbols == b.symbols
    assert old.kinds == new.kinds and old.listings == new.listings
    assert list(old.raw) == list(new.raw)
    for instrument_id, x in a.series.items():
        y = b.series[instrument_id]
        assert x.dates == y.dates and x.position == y.position
        assert list(x.position) == list(y.position)
        assert x.session == y.session and x.suspended == y.suspended
        for name in FLOAT_FIELDS:
            assert _bits(getattr(x, name)) == _bits(getattr(y, name)), name
        assert list(x.chips) == list(y.chips)
        for name in x.chips:
            assert _bits(x.chips[name]) == _bits(y.chips[name]), name
        assert x.revenues == y.revenues and x.quarters == y.quarters
        low, high, close, flags = old.raw[instrument_id]
        nlow, nhigh, nclose, nflags = new.raw[instrument_id]
        for before, after in ((low, nlow), (high, nhigh), (close, nclose)):
            assert after.typecode == "d" and _bits(before) == after.tobytes()
        assert nflags.typecode == "b" and [bool(v) for v in nflags] == flags
        # C: the bars of a day share the session's date object.
        assert all(day is b.sessions[k] for day, k in zip(y.dates, y.session))
    # C: every listing of an instrument is its series key's id object.
    keys = {key: key for key in b.series}
    for day, ids in b.listed.items():
        assert all(i is keys[i] for i in ids), day


def both_loaders(module, monkeypatch, run):
    """``run(label)`` with the old loader, then with the new; their results."""

    pr = module.pr
    new = pr.load_market
    results = {}
    for label, loader in (("old", reference_load_market(pr)), ("new", new)):
        monkeypatch.setattr(pr, "load_market", loader)
        results[label] = run(label)
    monkeypatch.setattr(pr, "load_market", new)
    return results["old"], results["new"]


# --- the panels ---------------------------------------------------------------------


@pytest.mark.parametrize("end", [None, date(2013, 6, 28)])
def test_the_explore_fixture_panel_is_the_same(explore_db, tmp_path, end):  # noqa: F811
    pr = te.tool.pr
    load = lambda: te.one_process(  # noqa: E731
        lambda: pr.load_market(
            explore_db, date(1990, 1, 1), tmp_path / "raw", fundamentals=True, end=end
        )
    )
    new = load()
    old = te.one_process(
        lambda: reference_load_market(pr)(
            explore_db, date(1990, 1, 1), tmp_path / "raw", fundamentals=True, end=end
        )
    )
    assert len(new.panel.series) > 1
    assert_same_market(old, new)


def test_the_trade_fixture_panel_is_the_same(golden_db, tmp_path):  # noqa: F811
    pr = tt.tool.pr
    args = (golden_db, date(1990, 1, 1), tmp_path / "raw")
    new = tt.one_process(lambda: pr.load_market(*args, fundamentals=True))
    old = tt.one_process(lambda: reference_load_market(pr)(*args, fundamentals=True))
    assert any(any(flags) for *_rest, flags in new.raw.values())  # a suspension
    assert_same_market(old, new)


def test_the_portfolio_fixture_panel_is_the_same(copy_db, tmp_path):  # noqa: F811
    pr = tp.tool
    args = (copy_db, tp.trading_days()[0], tmp_path / "raw")
    assert_same_market(
        te.one_process(lambda: reference_load_market(pr)(*args)),
        te.one_process(lambda: pr.load_market(*args)),
    )


# --- the outputs --------------------------------------------------------------------


def test_explore_research_outputs_are_the_same(explore_db, tmp_path, monkeypatch):  # noqa: F811
    te.compressed(monkeypatch, tmp_path)

    def run(label: str) -> tuple[dict, dict]:
        folder = tmp_path / label
        folder.mkdir()
        db = te.copy_of(explore_db, folder)
        exploration = folder / "exploration"
        assert te.explore(db, exploration) == 0
        validation = folder / "validation"
        names = list(te.tool.HYPOTHESES)
        te.one_process(
            lambda: te.tool.run_validation(
                db, validation, names, {"sha256": "x", "url": te.URL}, "cmd"
            )
        )
        return te.outputs(exploration), te.outputs(validation)

    old, new = both_loaders(te.tool, monkeypatch, run)
    for before, after in zip(old, new):
        assert sorted(before) == sorted(after)
        assert any(name.endswith("trades.csv") for name in after)
        assert any(name.endswith("picks.csv") for name in after)
        for name in before:
            assert before[name] == after[name], name


def test_trade_research_outputs_are_the_same(golden_db, tmp_path, monkeypatch):  # noqa: F811
    tt.compressed(monkeypatch, tmp_path)
    names = list(tt.tool.HYPOTHESES)

    def run(label: str) -> tuple[dict, dict]:
        db = tt.copy_of(golden_db, tmp_path, label)
        exploration = tmp_path / f"{label}-exploration"
        assert tt.explore(db, exploration, ",".join(names)) == 0
        validation = tmp_path / f"{label}-validation"
        tt.one_process(
            lambda: tt.tool.run_validation(
                db, validation, names, {"sha256": "x", "url": tt.URL}, "cmd"
            )
        )
        return te.outputs(exploration), te.outputs(validation)

    old, new = both_loaders(tt.tool, monkeypatch, run)
    assert any(name.endswith("trades.csv") for name in new[0])  # the exploration
    for before, after in zip(old, new):
        assert sorted(before) == sorted(after)
        for name in before:
            assert before[name] == after[name], name


def test_portfolio_research_outputs_are_the_same(copy_db, tmp_path, monkeypatch):  # noqa: F811
    research = tp.lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)

    def run(label: str) -> dict:
        folder = tmp_path / label
        folder.mkdir()
        out = te.one_process(lambda: tp.run_v1(copy_db, folder, ["--rankings", "689"]))
        return {"v1": tp.v1_digests(out), "rankings": tp.rankings_digests(out)}

    pr_holder = type("Holder", (), {"pr": tp.tool})
    old, new = both_loaders(pr_holder, monkeypatch, run)
    assert old == new
    assert new["v1"] == tp.V1_DIGESTS and new["rankings"] == tp.RANKINGS_DIGESTS


def test_the_streamed_query_is_the_universe_query(explore_db):  # noqa: F811
    report = te.lib.research_report()
    con = te.lib.connect_read_only(explore_db)
    try:
        instruments, _listed = report.benchmark_universe(con, date(1990, 1, 1))
        grouped = list(report.benchmark_bars(con, date(1990, 1, 1)))
    finally:
        con.close()
    assert [i for i, _bars in grouped] == list(instruments)
    assert all(bars == instruments[i].bars for i, bars in grouped)
    assert len({i for i, _bars in grouped}) == len(grouped)  # each id once
