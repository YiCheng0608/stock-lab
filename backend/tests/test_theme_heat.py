"""題材熱度 theme_heat_v1 (Issue #1017): spec snapshot, hand-computed fixture,
missing news, the daily step, the CLI range, the API and migration 0035.

The fixture is 30 calendar days standing in for sessions (TAIEX has a bar on
each), T the last.  Group A's three members are built so every component has a
round hand value (the numbers in ``HAND``); group B is flat with no chips;
group C has two members (not on the board); group D's members start after T.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
from app import migrations, theme_heat
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.migration_revisions import REVISIONS
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    CorporateAction,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    NewsLlmResult,
    ThemeGroup,
    ThemeHeatRun,
    ThemeHeatScore,
)
from app.theme_heat import (
    COMPONENTS,
    THEME_HEAT_CONFIG,
    WEIGHTS,
    Inputs,
    NewsCount,
    NewsEntry,
    group_metrics,
    keyword_matches,
    news_counts,
    score_board,
)
from test_daily_schedule import Steps, runs
from worker.cli import DAILY_EXIT_CODES
from worker.news_llm import PROMPT_VERSION
from worker.theme_heat import run_theme_heat, run_theme_heat_range

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "spec" / "theme_heat.md"
N = 30
FIRST = date(2026, 10, 1)
DAYS = [FIRST + timedelta(days=offset) for offset in range(N)]
T = DAYS[-1]
LAST = N - 1
REAL_STEP = schedule_runs._theme_heat_step

INDEX = [1000.0] * (N - 1) + [1050.0]
# Closes (None: no bar) and turnovers (None: a bar with no turnover and no volume).
PRICES = {
    "a0": [10.0] * (N - 1) + [12.0],
    "a1": [10.0] * 10 + [11.0] * (N - 10),
    "a2": [10.0] * (N - 1) + [9.0],
}
AMOUNTS = {
    "a0": [100.0] * 25 + [200.0] * 5,
    "a1": [50.0] * N,
    "a2": [30.0] * 25 + [None, 60.0, 60.0, 60.0, 60.0],
}
# Net shares (foreign, trust, dealer) on days 25..29; a1 has no chip row on T.
CHIPS = {
    "a0": {day: (1.0, None, None) for day in range(25, 30)},
    "a1": {day: (1.0, 0.0, 0.0) for day in range(25, 29)},
    "a2": {day: (-1.0, 0.5, None) for day in range(25, 30)},
}
HAND = {
    # (0.2 + 0 - 0.1) / 3 - 0.05
    "excess_5d": 0.1 / 3 - 0.05,
    # (0.2 + 0.1 - 0.1) / 3 - 0.05
    "excess_20d": 0.2 / 3 - 0.05,
    # (200 + 50 + 240 / 5) / (100 + 50 + 30)
    "turnover_ratio": 298 / 180,
    # a0 1 share x (10, 10, 10, 10, 12) + a2 -0.5 share x (10, 10, 10, 10, 9),
    # over the five days' turnover 298 x 5
    "institutional_ratio": (52 - 24.5) / 1490,
    # a0 and a1 beat the index's 5 %
    "breadth": 2 / 3,
    # (6 / 3) / ((19 + 1) / 20)
    "news": 2.0,
}


# --- AC-1: the spec and the pinned parameters ------------------------------


def test_weights_and_windows_are_pinned():
    assert COMPONENTS == (
        "excess_5d",
        "excess_20d",
        "turnover_ratio",
        "institutional_ratio",
        "breadth",
        "news",
    )
    assert WEIGHTS == {
        "excess_5d": 0.20,
        "excess_20d": 0.20,
        "turnover_ratio": 0.20,
        "institutional_ratio": 0.12,
        "breadth": 0.08,
        "news": 0.20,
    }
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    # Without news the five are #1003 AC-2 §3's left column.
    rest = 1 - WEIGHTS["news"]
    assert [round(WEIGHTS[c] / rest, 10) for c in COMPONENTS[:5]] == [
        0.25,
        0.25,
        0.25,
        0.15,
        0.10,
    ]
    assert THEME_HEAT_CONFIG == {
        "version": "theme_heat_v1",
        "revision": "1.0.0",
        "spec": "docs/spec/theme_heat.md",
        "weights": WEIGHTS,
        "min_eligible_members": 3,
        "return_windows": [5, 20],
        "turnover_windows": [5, 20],
        "flow_sessions": 5,
        "news": {
            "recent_sessions": 3,
            "prior_sessions": 20,
            "min_items": 3,
            "prior_smoothing": 1,
            "source_kind": "media",
            "run_statuses": ["success", "partial"],
        },
        "price_basis": "worker.pipeline._action_factor_by_bar",
        "percentile": "worker.pipeline._percentile",
    }


def test_the_spec_table_states_the_same_weights():
    text = SPEC.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| [^|]+ \| `([a-z0-9_]+)` \| [^|]+ \| ([0-9.]+) \|$", text, re.M
    )
    assert [(key, float(weight)) for key, weight in rows] == [
        (key, WEIGHTS[key]) for key in COMPONENTS
    ]
    for phrase in (
        "近 3 個交易日",
        "前 20 個交易日",
        "至少 3 個成員有 20 日報酬",
        "近 3 日不到 3 則時原值為 0",
        "0.25、0.25、0.25、0.15、0.10",
        "不是買賣訊號",
    ):
        assert phrase in text, phrase


# --- AC-2: hand-computed components -----------------------------------------


def _inputs(chips_close=None) -> Inputs:
    ids = {"a0": 1, "a1": 2, "a2": 3}
    inputs = Inputs(sessions=list(DAYS), index_close=list(INDEX))
    for name, instrument_id in ids.items():
        inputs.price[instrument_id] = list(PRICES[name])
        inputs.amount[instrument_id] = list(AMOUNTS[name])
        flows: list[float | None] = [None] * N
        for day, (foreign, trust, dealer) in CHIPS[name].items():
            flows[day] = (foreign + (trust or 0) + (dealer or 0)) * PRICES[name][day]
        inputs.flow[instrument_id] = flows
    return inputs


def test_five_and_twenty_day_excess_returns_by_hand():
    value = group_metrics([1, 2, 3], LAST, _inputs())
    assert value.excess_5d == pytest.approx(HAND["excess_5d"])
    assert value.excess_20d == pytest.approx(HAND["excess_20d"])
    assert value.eligible_members == 3


def test_turnover_ratio_by_hand():
    value = group_metrics([1, 2, 3], LAST, _inputs())
    assert value.turnover_ratio == pytest.approx(HAND["turnover_ratio"])
    # Fewer than 24 sessions before T: no prior window.
    assert group_metrics([1, 2, 3], 23, _inputs()).turnover_ratio is None


def test_institutional_ratio_by_hand():
    value = group_metrics([1, 2, 3], LAST, _inputs())
    assert value.flow_members == 2  # a1 has no chip row on T
    assert value.institutional_ratio == pytest.approx(HAND["institutional_ratio"])
    inputs = _inputs()
    inputs.flow[3] = [None] * N
    # One member of three (3 // 2 = 1) is enough; the denominator stays all three.
    value = group_metrics([1, 2, 3], LAST, inputs)
    assert (value.flow_members, value.institutional_ratio) == (
        1,
        pytest.approx(52 / 1490),
    )
    inputs.flow[1] = [None] * N
    assert group_metrics([1, 2, 3], LAST, inputs).institutional_ratio is None


def test_breadth_by_hand():
    assert group_metrics([1, 2, 3], LAST, _inputs()).breadth == pytest.approx(
        HAND["breadth"]
    )


def test_news_items_by_hand():
    def entry(day, groups=(), instruments=()):
        return NewsEntry(DAYS[day], frozenset(groups), frozenset(instruments))

    entries = (
        [entry(27, {"A"}), entry(28, {"A"}), entry(29, {"A"}), entry(29, {"A"})]
        + [entry(28, (), {2})]  # the AI names a1: counts for A
        + [entry(29, {"A"}, {2})]  # both: counts once
        + [entry(day, {"A"}) for day in range(7, 26)]  # 19 in the prior window
        + [entry(26, {"A"})]  # S[T-3] itself is the prior window's last day
        + [entry(6, {"A"}), entry(3, {"A"})]  # before the prior window
        + [entry(28, {"B"}), entry(29, {"B"})]
    )
    counts = news_counts(entries, DAYS, LAST, {"A": [1, 2, 3], "B": [4]})
    assert counts["A"] == NewsCount(recent=6, prior=20)
    assert counts["B"] == NewsCount(recent=2, prior=0)
    assert NewsCount(6, 19).raw == pytest.approx(HAND["news"])
    assert NewsCount(2, 0).raw == 0.0  # below 3 items
    assert NewsCount(3, 0).raw == pytest.approx(1 / (1 / 20))


def test_keywords_match_folded_text():
    keywords = {"theme-a": ["DRAM", "記憶體"], "theme-b": ["ABF"]}
    assert keyword_matches("ｄｒａｍ 報價", keywords) == {"theme-a"}
    assert keyword_matches("abf 載板與記憶體", keywords) == {"theme-a", "theme-b"}
    assert keyword_matches("無關", keywords) == set()


# --- the board on the fixture database --------------------------------------


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'heat.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with make() as db:
            yield db

    monkeypatch.setattr(pipeline, "SessionLocal", make)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    monkeypatch.setattr(
        theme_heat,
        "theme_keywords",
        lambda table=None: {"theme-a": ["記憶體"], "theme-b": ["載板"]},
    )
    app.dependency_overrides[api_module.get_db] = override_get_db
    yield make
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


def _utc(day: int, hour: int = 4) -> datetime:
    """Taipei ``hour`` o'clock on DAYS[day], as stored (naive UTC)."""

    return datetime.combine(DAYS[day], datetime.min.time()) + timedelta(hours=hour - 8)


class World:
    def __init__(self, db):
        self.db = db
        self.ids: dict[str, int] = {}
        taiex = self._instrument("TAIEX", "index")
        for day, close in zip(DAYS, INDEX):
            self._bar(taiex, DAYS.index(day), close, 0, 0)

    def _instrument(self, symbol, kind="stock"):
        instrument = Instrument(
            market="TW",
            exchange="TWSE",
            symbol=symbol,
            name=f"N{symbol}",
            instrument_type=kind,
            status="active",
        )
        self.db.add(instrument)
        self.db.flush()
        self.ids[symbol] = instrument.id
        return instrument.id

    def _bar(self, instrument_id, day, close, volume, turnover):
        self.db.add(
            MarketBar(
                instrument_id=instrument_id,
                trading_date=DAYS[day],
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                volume=volume,
                turnover=turnover,
                source="fixture",
            )
        )

    def stock(self, symbol, closes, amounts, chips=None):
        instrument_id = self._instrument(symbol)
        for day, close in enumerate(closes):
            if close is None:
                continue
            amount = amounts[day]
            # A missing amount is a bar with no turnover and no volume.
            self._bar(
                instrument_id,
                day,
                close,
                None if amount is None else 1000,
                0.0 if amount is None else amount,
            )
        for day, (foreign, trust, dealer) in (chips or {}).items():
            self.db.add(
                ChipSnapshot(
                    instrument_id=instrument_id,
                    trading_date=DAYS[day],
                    foreign_buy=foreign,
                    trust_buy=trust,
                    dealer_buy=dealer,
                    source="fixture",
                )
            )
        return instrument_id

    def group(self, group_id, symbols, *, valid_from=date(2026, 1, 1), active=True):
        self.db.add(
            ThemeGroup(
                id=group_id,
                name=group_id,
                group_type="theme",
                active=active,
                display_name_zh=f"題材{group_id[-1].upper()}",
                name_status="verified",
            )
        )
        self.db.flush()
        for symbol in symbols:
            self.member(group_id, symbol, valid_from)

    def member(self, group_id, symbol, valid_from, valid_to=None):
        self.db.add(
            GroupMembership(
                group_id=group_id,
                instrument_id=self.ids[symbol],
                valid_from=valid_from,
                valid_to=valid_to,
                source="fixture",
            )
        )

    def news(self, day, title, *, hour=4, kind="media", status="active", names=()):
        item = NewsItem(
            canonical_key=f"k{len(self.db.new)}-{day}-{title}-{hour}-{kind}-{status}",
            source_kind=kind,
            source_name="fixture",
            category="domestic",
            title=title,
            published_at=_utc(day, hour),
            collected_at=_utc(day, hour),
            status=status,
        )
        self.db.add(item)
        self.db.flush()
        if names:
            self.db.add(
                NewsLlmResult(
                    news_item_id=item.id,
                    prompt_version=PROMPT_VERSION,
                    llm_input_hash="x",
                    llm_status="done",
                    ai_symbol_candidates_json=[
                        {"symbol": f"TWSE:{name}"} for name in names
                    ],
                )
            )

    def news_run(self, day, status="success"):
        self.db.add(
            IngestionRun(
                run_type="news",
                source="fixture",
                run_date=DAYS[day],
                status=status,
            )
        )


def build(db, *, news_run_on_t=True):
    world = World(db)
    for name in ("a0", "a1", "a2"):
        world.stock(name, PRICES[name], AMOUNTS[name], CHIPS[name])
    world.stock("a3", [10.0] * N, [10.0] * N)
    for name in ("b0", "b1", "b2", "c0", "c1", "d0", "d1", "d2"):
        world.stock(name, [10.0] * N, [10.0] * N)
    world.group("theme-a", ["a0", "a1", "a2"])
    # Added the day after T: not on T's board (no backdating).
    world.member("theme-a", "a3", T + timedelta(days=1))
    world.group("theme-b", ["b0", "b1", "b2"])
    world.group("theme-c", ["c0", "c1"])
    world.group("theme-d", ["d0", "d1", "d2"], valid_from=T + timedelta(days=1))
    # Group A: 6 items in the recent window, 19 in the prior one.
    for day in (27, 28, 29):
        world.news(day, "記憶體報價")
    # 07:00 Taipei on T is the day before in UTC: still T.
    world.news(29, "記憶體缺貨", hour=7)
    world.news(28, "a1 接單", names=("a1",))
    world.news(29, "記憶體與 a1", names=("a1",))
    for day in range(7, 26):
        world.news(day, "記憶體")
    # Not counted: before the window, official, excluded.
    world.news(3, "記憶體")
    world.news(28, "記憶體公告", kind="official_disclosure")
    world.news(28, "記憶體重複", status="excluded")
    world.news(28, "載板")
    world.news(29, "載板")
    world.news_run(0)
    if news_run_on_t:
        world.news_run(LAST)
    db.commit()
    return world


def _scores(make, day=T):
    with make() as db:
        run = db.scalar(select(ThemeHeatRun).where(ThemeHeatRun.trading_date == day))
        rows = db.scalars(
            select(ThemeHeatScore).where(ThemeHeatScore.run_id == run.id)
        ).all()
        return run, {row.group_id: row for row in rows}


def test_the_board_by_hand_on_the_database(factory):
    with factory() as db:
        build(db)
        run = theme_heat.compute_theme_heat(db, T)
    assert (run.status, run.news_status, run.theme_count, run.ranked_count) == (
        "computed",
        "available",
        3,
        2,
    )
    run, rows = _scores(factory)
    assert set(rows) == {"theme-a", "theme-b", "theme-c"}  # theme-d starts after T
    a, b, c = rows["theme-a"], rows["theme-b"], rows["theme-c"]
    assert (a.member_count, a.eligible_members) == (3, 3)
    for component, value in HAND.items():
        assert a.components_json[component]["raw"] == pytest.approx(value, abs=1e-6)
    assert a.details_json == {"flow_members": 2, "news_recent": 6, "news_prior": 19}
    assert {k: v["percentile"] for k, v in a.components_json.items()} == {
        "excess_5d": 1.0,
        "excess_20d": 1.0,
        "turnover_ratio": 1.0,
        "institutional_ratio": 0.5,  # b has none: a is alone
        "breadth": 1.0,
        "news": 1.0,
    }
    assert a.heat == pytest.approx(0.2 + 0.2 + 0.2 + 0.12 * 0.5 + 0.08 + 0.2)
    assert (a.rank, a.quality, a.available_weight) == (1, "complete", 1.0)
    # b: flat, no chips, two news items (below 3: a fixed 0).
    assert b.components_json["institutional_ratio"] == {
        "raw": None,
        "percentile": None,
    }
    assert b.components_json["news"] == {"raw": 0.0, "percentile": 0.0}
    assert (b.rank, b.quality, b.heat) == (2, "partial", 0.0)
    assert b.available_weight == pytest.approx(0.88)
    assert (c.rank, c.heat, c.quality, c.eligible_members) == (
        None,
        None,
        "insufficient_data",
        0,
    )
    assert all(
        v == {"raw": None, "percentile": None} for v in c.components_json.values()
    )
    assert run.config_json == THEME_HEAT_CONFIG


# --- AC-3: no news run is null, never 0 -------------------------------------


def test_no_news_run_on_t_leaves_news_null_and_renormalises(factory):
    with factory() as db:
        build(db, news_run_on_t=False)
        run = theme_heat.compute_theme_heat(db, T)
    assert run.news_status == "no_news_run"
    assert run.news_through_id is None
    _, rows = _scores(factory)
    a = rows["theme-a"]
    assert a.components_json["news"] == {"raw": None, "percentile": None}
    assert a.details_json["news_recent"] is None
    # 0.25 + 0.25 + 0.25 + 0.15 x 0.5 + 0.10: the no-news column.
    assert a.heat == pytest.approx(0.925)
    assert (a.quality, a.available_weight) == ("partial", 0.8)
    assert rows["theme-b"].components_json["news"]["percentile"] is None


def test_news_before_the_first_run_is_history_short(factory):
    with factory() as db:
        build(db)
        db.execute(
            IngestionRun.__table__.update()
            .where(IngestionRun.run_date == DAYS[0])
            .values(run_date=DAYS[10])
        )
        db.commit()
        run = theme_heat.compute_theme_heat(db, T)
    assert run.news_status == "history_short"
    _, rows = _scores(factory)
    assert rows["theme-a"].components_json["news"]["percentile"] is None


def test_a_failed_news_run_is_not_a_run(factory):
    with factory() as db:
        build(db, news_run_on_t=False)
        World.news_run(type("W", (), {"db": db})(), LAST, status="failed")
        db.commit()
        assert theme_heat.compute_theme_heat(db, T).news_status == "no_news_run"


def test_the_pure_board_without_news_renormalises():
    rows = score_board({"A": [1, 2, 3]}, LAST, _inputs(), None)
    (row,) = rows
    assert row.percentile["news"] is None
    # Alone on the board: every present component is 0.5.
    assert row.heat == pytest.approx(0.5)
    assert row.available_weight == pytest.approx(0.8)


# --- price basis and members ------------------------------------------------


def test_a_split_in_the_window_is_the_holders_return(factory):
    with factory() as db:
        build(db)
        # b0: 10 -> 6 across a 2-for-1 split on day 27: +20 % for the holder.
        db.execute(
            MarketBar.__table__.update()
            .where(
                MarketBar.instrument_id
                == db.scalar(select(Instrument.id).where(Instrument.symbol == "b0")),
                MarketBar.trading_date >= DAYS[27],
            )
            .values(close=6.0, adj_close=6.0)
        )
        db.add(
            CorporateAction(
                instrument_id=db.scalar(
                    select(Instrument.id).where(Instrument.symbol == "b0")
                ),
                action_date=DAYS[27],
                action_type="split",
                split_ratio=2.0,
                source="fixture",
            )
        )
        db.commit()
        theme_heat.compute_theme_heat(db, T)
    _, rows = _scores(factory)
    # (0.2 + 0 + 0) / 3 - 0.05
    assert rows["theme-b"].components_json["excess_5d"]["raw"] == pytest.approx(
        0.2 / 3 - 0.05, abs=1e-6
    )


def test_a_member_counts_only_on_its_valid_days(factory):
    with factory() as db:
        build(db)
        db.execute(
            GroupMembership.__table__.update()
            .where(
                GroupMembership.group_id == "theme-b",
                GroupMembership.instrument_id
                == db.scalar(select(Instrument.id).where(Instrument.symbol == "b2")),
            )
            .values(valid_to=DAYS[20])
        )
        db.execute(
            ThemeGroup.__table__.update()
            .where(ThemeGroup.id == "theme-c")
            .values(active=False)
        )
        db.commit()
        theme_heat.compute_theme_heat(db, T)
    _, rows = _scores(factory)
    assert set(rows) == {"theme-a", "theme-b"}
    assert (rows["theme-b"].member_count, rows["theme-b"].rank) == (2, None)


def test_a_day_that_is_not_a_session_fails_without_writing(factory):
    with factory() as db:
        build(db)
        with pytest.raises(theme_heat.ThemeHeatDataError):
            theme_heat.compute_theme_heat(db, T + timedelta(days=1))
        assert db.scalar(select(func.count()).select_from(ThemeHeatRun)) == 0


# --- the daily step, the range and the API -----------------------------------


def _real_step(monkeypatch, **results):
    steps = Steps(monkeypatch, **results)
    monkeypatch.setattr(schedule_runs, "_theme_heat_step", REAL_STEP)
    return steps


def test_the_daily_writes_the_day_after_h2(factory, monkeypatch):
    with factory() as db:
        build(db)
    steps = _real_step(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert result["theme_heat"]["status"] == "success"
    assert steps.calls.index("h2_list") < steps.calls.index("plan_tracking")
    rows, by_run = runs(factory)
    logged = by_run[rows[0].id]
    step = logged["theme_heat"]
    assert (step.status, step.records, step.sequence) == ("success", 2, 9)
    assert logged["h2_list"].sequence < step.sequence
    run, scores = _scores(factory)
    assert run.status == "computed" and scores["theme-a"].rank == 1


def test_a_failure_is_a_warning_and_keeps_the_run(factory, monkeypatch, capsys):
    with factory() as db:
        build(db)
    assert run_theme_heat(T)["records"] == 2

    def broken(db, day):
        raise RuntimeError("fixture heat crash")

    monkeypatch.setattr("worker.theme_heat.compute_theme_heat", broken)
    _real_step(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert DAILY_EXIT_CODES[result["status"]] == 0
    assert "warning: theme_heat_v1" in capsys.readouterr().err
    rows, by_run = runs(factory)
    assert rows[0].status == "success" and rows[0].error is None
    assert by_run[rows[0].id]["theme_heat"].status == "failed"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ThemeHeatScore)) == 3


def test_a_rerun_replaces_the_day(factory):
    with factory() as db:
        build(db)
    run_theme_heat(T)
    run_theme_heat(T)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ThemeHeatRun)) == 1
        assert db.scalar(select(func.count()).select_from(ThemeHeatScore)) == 3


def test_the_range_recomputes_every_session_and_reports_weeks(factory):
    with factory() as db:
        build(db)
    result = run_theme_heat_range(DAYS[20], T, weekly=True)
    assert (result["status"], result["days"]) == ("success", 10)
    with factory() as db:
        days = db.scalars(select(ThemeHeatRun.trading_date)).all()
    assert sorted(days) == DAYS[20:]
    # Days before 24 sessions of history: no turnover ratio, but still ranked.
    weeks = result["weekly"]
    assert [week["date"] for week in weeks] == [
        max(d for d in DAYS[20:] if d.isocalendar()[:2] == k).isoformat()
        for k in sorted({d.isocalendar()[:2] for d in DAYS[20:]})
    ]
    assert weeks[-1]["ranking"][0]["theme_id"] == "theme-a"
    failed = run_theme_heat_range(T + timedelta(days=1), T + timedelta(days=3))
    assert failed["status"] == "failed"


def test_the_api_returns_the_latest_and_a_date(factory):
    with factory() as db:
        build(db)
    run_theme_heat(DAYS[25])
    run_theme_heat(T)
    client = TestClient(app)
    body = client.get("/api/theme-heat").json()
    dated = client.get(f"/api/theme-heat?date={T.isoformat()}").json()
    assert dated["items"] == body["items"]
    assert (body["meta"]["requested_date"], dated["meta"]["requested_date"]) == (
        None,
        T.isoformat(),
    )
    meta = body["meta"]
    assert (meta["trading_date"], meta["news_status"], meta["not_a_signal"]) == (
        T.isoformat(),
        "available",
        "不是買賣訊號",
    )
    assert (meta["theme_count"], meta["ranked_count"], meta["empty_reason"]) == (
        3,
        2,
        None,
    )
    assert meta["weights"] == WEIGHTS
    assert [item["theme_id"] for item in body["items"]] == [
        "theme-a",
        "theme-b",
        "theme-c",
    ]
    first = body["items"][0]
    assert first["display_name"] == "題材A"
    assert first["components"]["institutional_ratio"] == 0.5
    assert first["raw"]["news"] == pytest.approx(2.0)
    assert first["news_items"] == {"recent": 6, "prior": 19}
    assert body["items"][2]["rank"] is None
    older = client.get(f"/api/theme-heat?date={(T - timedelta(days=1)).isoformat()}")
    assert older.json()["meta"]["trading_date"] == DAYS[25].isoformat()
    none = client.get(f"/api/theme-heat?date={DAYS[3].isoformat()}").json()
    assert (none["items"], none["meta"]["empty_reason"]) == ([], "not_computed")


# --- migration 0035 ---------------------------------------------------------


def _tables(path):
    with closing(sqlite3.connect(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'ix_theme_heat_%'"
            )
        }
        foreign = {
            row[3]: row[2]
            for row in connection.execute(
                "PRAGMA foreign_key_list('theme_heat_scores')"
            )
        }
    return tables & {"theme_heat_runs", "theme_heat_scores"}, indexes, foreign


INDEXES = {
    "ix_theme_heat_runs_trading_date",
    "ix_theme_heat_scores_run_id",
    "ix_theme_heat_scores_trading_date",
    "ix_theme_heat_scores_group_id",
}


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_the_upgrade_adds_the_two_tables(tmp_path, monkeypatch, entry):
    if entry == "alembic":
        pytest.importorskip("alembic")
    path = tmp_path / f"{entry}.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    if entry == "fallback":
        monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    try:
        upgrade_database(engine)
    finally:
        engine.dispose()
    tables, indexes, foreign = _tables(path)
    assert tables == {"theme_heat_runs", "theme_heat_scores"}
    assert indexes == INDEXES
    assert foreign == {"run_id": "theme_heat_runs", "group_id": "theme_groups"}
    with closing(sqlite3.connect(path)) as connection:
        if entry == "alembic":
            assert "0035_theme_heat" in REVISIONS
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall() == [(REVISIONS[-1],)]
        else:
            assert connection.execute(
                "SELECT version FROM schema_migrations WHERE version = '0035_theme_heat'"
            ).fetchall() == [("0035_theme_heat",)]


def test_the_downgrade_drops_the_two_tables_and_the_upgrade_makes_them_again(
    tmp_path,
):
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config

    path = tmp_path / "down.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    try:
        command.upgrade(config, "0035_theme_heat")
        command.downgrade(config, "0034_h2_lists")
        tables, indexes, _ = _tables(path)
        assert (tables, indexes) == (set(), set())
        command.upgrade(config, "0035_theme_heat")
    finally:
        engine.dispose()
    tables, indexes, _ = _tables(path)
    assert tables == {"theme_heat_runs", "theme_heat_scores"}
    assert indexes == INDEXES
