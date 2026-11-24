"""主流族群前 20 (mainstream_v1, Issue #768): definition, daily step and API.

AC-2 locks the definition on a fixture database (``compute_mainstream``),
AC-3 the daily step (``worker.mainstream`` through ``schedule_runs``), AC-4
``GET /api/mainstream``.  Every stock's bars are 100 until its last bar, which
is ``100 × (1 + return)``, so the W-session return is the one asked for.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
from app import mainstream, migrations
from app.db import enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE_VERSION
from app.main import app
from app.migration_revisions import REVISIONS
from app.migrations import upgrade_database
from app.models import (
    CandidateRun,
    CorporateAction,
    DailyCandidate,
    GroupMembership,
    Instrument,
    MainstreamItem,
    MainstreamRun,
    MarketBar,
    Signal,
    ThemeGroup,
)
from test_daily_schedule import Steps, runs
from worker.cli import DAILY_EXIT_CODES
from worker.mainstream import run_mainstream

T = date(2026, 11, 13)
W = mainstream.WINDOW
# Consecutive calendar days stand in for sessions; TAIEX has a bar on each.
DAYS = [T - timedelta(days=offset) for offset in range(W + 30, -1, -1)]
REAL_MAINSTREAM_STEP = schedule_runs._mainstream_step


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'mainstream.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with make() as db:
            yield db

    monkeypatch.setattr(pipeline, "SessionLocal", make)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    yield make
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


class World:
    def __init__(self, db, index_return=0.1):
        self.db = db
        self.ids: dict[str, int] = {}
        taiex = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="TAIEX",
            name="TAIEX",
            instrument_type="index",
            status="active",
        )
        db.add(taiex)
        db.flush()
        self.taiex = taiex.id
        for day in DAYS:
            close = 1000 * (1 + index_return) if day == T else 1000.0
            self._bar(taiex.id, day, close, 0)

    def _bar(self, instrument_id, day, close, volume, suspended=False):
        self.db.add(
            MarketBar(
                instrument_id=instrument_id,
                trading_date=day,
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                volume=volume,
                turnover=close * volume,
                source="twse-fixture",
                is_suspended=suspended,
            )
        )

    def stock(
        self,
        symbol,
        ret,
        *,
        bars=W + 1,
        volume=2_000_000,
        kind="stock",
        suspended=False,
        then=100.0,
        now=None,
    ):
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
        last = then * (1 + ret) if now is None else now
        for day in DAYS[-bars:]:
            self._bar(
                instrument.id,
                day,
                last if day == T else then,
                volume,
                suspended and day == T,
            )
        return instrument.id

    def group(
        self,
        group_id,
        symbols,
        *,
        kind="theme",
        active=True,
        valid=None,
    ):
        self.db.add(
            ThemeGroup(
                id=group_id,
                name=group_id,
                group_type=kind,
                active=active,
                display_name_zh=f"族群{group_id}",
                name_status="verified",
            )
        )
        self.db.flush()
        for symbol in symbols:
            valid_from, valid_to = (valid or {}).get(symbol, (date(2020, 1, 1), None))
            self.db.add(
                GroupMembership(
                    group_id=group_id,
                    instrument_id=self.ids[symbol],
                    valid_from=valid_from,
                    valid_to=valid_to,
                    source="fixture",
                )
            )

    def stocks(self, prefix, returns, **kwargs):
        symbols = []
        for index, ret in enumerate(returns):
            symbol = f"{prefix}{index}"
            self.stock(symbol, ret, **kwargs)
            symbols.append(symbol)
        return symbols

    def compute(self):
        self.db.commit()
        return mainstream.compute_mainstream(self.db, T)

    def symbols(self, run):
        by_id = {value: key for key, value in self.ids.items()}
        rows = self.db.scalars(
            select(MainstreamItem)
            .where(MainstreamItem.mainstream_run_id == run.id)
            .order_by(MainstreamItem.rank)
        ).all()
        return [by_id[row.instrument_id] for row in rows]


def _groups(run):
    return [group["group_id"] for group in run.groups_json]


# --- AC-2: the definition -------------------------------------------------


def test_the_definition_is_pinned():
    assert mainstream.MAINSTREAM_VERSION == "mainstream_v1"
    assert (mainstream.WINDOW, mainstream.GROUP_COUNT, mainstream.LIST_SIZE) == (
        240,
        5,
        20,
    )
    assert (mainstream.MIN_MEMBERS, mainstream.DEDUP_OVERLAP) == (5, 0.8)
    assert mainstream.GROUP_TYPES == ("official_industry", "theme")


@pytest.mark.parametrize(
    ("members", "top"), [(5, 3), (6, 3), (7, 3), (9, 3), (10, 4), (12, 4), (31, 11)]
)
def test_top_third_rounds_up_and_takes_at_least_three(members, top):
    assert mainstream.top_count(members) == top


def test_group_strength_is_the_top_third_mean_minus_taiex(factory):
    with factory() as db:
        world = World(db, index_return=0.1)
        # Seven members: ⌈7/3⌉ = 3, the mean of 0.7, 0.6, 0.5 is 0.6.
        world.group("A", world.stocks("a", [0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]))
        run = world.compute()
        group = run.groups_json[0]
        assert (group["group_id"], group["member_count"], group["top_count"]) == (
            "A",
            7,
            3,
        )
        assert group["strength"] == pytest.approx(0.6 - 0.1)
        assert run.index_return == pytest.approx(0.1)
        item = db.scalar(select(MainstreamItem).where(MainstreamItem.rank == 1))
        assert (item.return_w, item.excess_w) == (
            pytest.approx(0.7),
            pytest.approx(0.6),
        )


def test_only_the_five_strongest_groups_are_chosen(factory):
    with factory() as db:
        world = World(db)
        for index, ret in enumerate([0.1, 0.7, 0.3, 0.5, 0.2, 0.6, 0.4]):
            name = "G" + "abcdefg"[index]
            world.group(name, world.stocks(name.lower(), [ret] * 5))
        run = world.compute()
        assert _groups(run) == ["Gb", "Gf", "Gd", "Gg", "Gc"]
        assert [group["rank"] for group in run.groups_json] == [1, 2, 3, 4, 5]
        assert run.ranked_group_count == 7
        assert run.status == "computed"


def test_members_count_only_on_their_valid_days(factory):
    with factory() as db:
        world = World(db)
        symbols = world.stocks("a", [0.5, 0.4, 0.3, 0.2, 0.1, 0.9, 0.8, 0.7])
        world.group(
            "A",
            symbols,
            valid={
                "a5": (date(2020, 1, 1), T - timedelta(days=1)),  # ended before T
                "a6": (T + timedelta(days=1), None),  # starts after T
                "a7": (date(2020, 1, 1), T),  # ends on T: still a member
            },
        )
        run = world.compute()
        assert world.symbols(run) == ["a7", "a0", "a1", "a2", "a3", "a4"]
        assert run.groups_json[0]["member_count"] == 6


def test_the_universe_needs_a_traded_bar_liquidity_and_w_plus_one_bars(factory):
    with factory() as db:
        world = World(db)
        good = world.stocks("a", [0.1, 0.2, 0.3, 0.4])
        world.stock("ipo", 0.05, kind="ipo")
        world.stock("susp", 0.9, suspended=True)
        # 20-bar mean of 999 lots, just under the 1,000-lot floor.
        world.stock("thin", 0.9, volume=999_999)
        world.stock("short", 0.9, bars=W)
        world.stock("etf", 0.9, kind="etf")
        world.group("A", good + ["ipo", "susp", "thin", "short", "etf"])
        run = world.compute()
        assert world.symbols(run) == ["a3", "a2", "a1", "a0", "ipo"]
        assert run.universe_count == 5


def test_a_group_with_fewer_than_five_valued_members_is_not_ranked(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.1] * 5))
        small = world.stocks("b", [0.9] * 4)
        world.stock("bthin", 0.9, volume=1000)
        world.group("B", small + ["bthin"])
        run = world.compute()
        assert _groups(run) == ["A"]
        assert run.ranked_group_count == 1


def test_equal_returns_are_ordered_by_the_hash(factory):
    with factory() as db:
        world = World(db)
        symbols = world.stocks("a", [0.3] * 6)
        world.group("A", symbols)
        run = world.compute()

        def key(symbol):
            text = f"{T.isoformat()}:{world.ids[symbol]}"
            return hashlib.sha256(text.encode()).hexdigest()

        assert world.symbols(run) == sorted(symbols, key=key)


def test_a_stock_in_two_chosen_groups_lists_both_in_group_rank_order(factory):
    with factory() as db:
        world = World(db)
        a = world.stocks("a", [0.9, 0.8, 0.8, 0.8, 0.8])
        b = world.stocks("b", [0.5, 0.5, 0.5, 0.5])
        world.group("A", a)
        world.group("B", b + ["a0"])  # 1 of 5 inside A: not a duplicate
        run = world.compute()
        assert _groups(run) == ["A", "B"]
        item = db.scalar(
            select(MainstreamItem).where(
                MainstreamItem.instrument_id == world.ids["a0"]
            )
        )
        assert (item.rank, item.group_ids_json) == (1, ["A", "B"])


def test_no_cap_per_group(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.9 - index * 0.01 for index in range(15)]))
        for name, ret in zip("BCDE", [0.5, 0.4, 0.3, 0.2]):
            world.group(name, world.stocks(name.lower(), [ret] * 5))
        run = world.compute()
        listed = world.symbols(run)
        assert len(listed) == 20
        assert sum(symbol.startswith("a") for symbol in listed) == 15
        assert sum(symbol.startswith("b") for symbol in listed) == 5


def test_fewer_than_twenty_are_all_listed(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.6, 0.5, 0.4, 0.3, 0.2, 0.1]))
        run = world.compute()
        assert world.symbols(run) == ["a0", "a1", "a2", "a3", "a4", "a5"]
        assert run.item_count == 6


def test_a_group_mostly_inside_the_chosen_ones_is_skipped(factory):
    with factory() as db:
        world = World(db)
        a = world.stocks("a", [0.95, 0.95, 0.95, 0.8, 0.8, 0.8])
        world.group("A", a)
        world.stock("bnew", 0.9)
        world.stock("cnew1", 0.3)
        world.stock("cnew2", 0.3)
        # B (strength 0.883 - index): 4 of 5 (80 %) in A, skipped although second.
        world.group("B", a[2:] + ["bnew"])
        # C (0.8 - index): 3 of 5 (60 %) in A, kept.
        world.group("C", a[3:] + ["cnew1", "cnew2"])
        run = world.compute()
        assert _groups(run) == ["A", "C"]
        assert "bnew" not in world.symbols(run)


def test_only_active_industry_and_theme_groups_rank(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.1] * 5), kind="official_industry")
        world.group("ETF", world.stocks("e", [0.9] * 5), kind="etf")
        world.group("NEW", world.stocks("n", [0.9] * 5), kind="daily_hot_group")
        world.group("OFF", world.stocks("o", [0.9] * 5), active=False)
        run = world.compute()
        assert _groups(run) == ["A"]


def test_a_split_in_the_window_counts_the_holders_return(factory):
    with factory() as db:
        world = World(db)
        others = world.stocks("a", [0.0] * 4)
        # Raw 100 -> 60 across a 2-for-1 split on T: +20 % for the holder.
        world.stock("split", 0.0, now=60.0)
        db.add(
            CorporateAction(
                instrument_id=world.ids["split"],
                action_date=T,
                action_type="split",
                split_ratio=2.0,
                source="fixture",
            )
        )
        world.group("A", others + ["split"])
        run = world.compute()
        item = db.scalar(select(MainstreamItem).where(MainstreamItem.rank == 1))
        assert world.symbols(run)[0] == "split"
        assert item.return_w == pytest.approx(0.2)


def test_no_ranked_group_is_a_zero_run(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.1] * 4))
        run = world.compute()
        assert (run.status, run.groups_json, run.item_count) == ("zero", [], 0)


def test_no_taiex_bar_on_the_day_is_an_error(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.1] * 5))
        db.execute(
            MarketBar.__table__.delete().where(
                MarketBar.instrument_id == world.taiex, MarketBar.trading_date == T
            )
        )
        db.commit()
        with pytest.raises(mainstream.MainstreamDataError):
            mainstream.compute_mainstream(db, T)


# --- AC-3: the daily step -------------------------------------------------


def _five_groups(world):
    for name, ret in zip("ABCDE", [0.5, 0.4, 0.3, 0.2, 0.1]):
        world.group(name, world.stocks(name.lower(), [ret] * 5))


def _real_mainstream(monkeypatch, **results):
    steps = Steps(monkeypatch, **results)
    monkeypatch.setattr(schedule_runs, "_mainstream_step", REAL_MAINSTREAM_STEP)
    return steps


def test_the_daily_computes_and_stores_the_list_after_the_today_list(
    factory, monkeypatch
):
    with factory() as db:
        _five_groups(World(db))
        db.commit()
    steps = _real_mainstream(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert "candidates" in steps.calls
    assert result["mainstream"]["status"] == "success"
    rows, by_run = runs(factory)
    logged = by_run[rows[0].id]
    step = logged["mainstream"]
    assert (step.status, step.records, step.sequence) == ("success", 20, 7)
    # After the today list: the step rows are ordered by sequence.
    assert logged["candidates"].sequence < step.sequence
    assert logged["candidates"].finished_at <= step.started_at
    with factory() as db:
        run = db.scalar(select(MainstreamRun))
        assert (run.trading_date, run.status, _groups(run)) == (
            T,
            "computed",
            ["A", "B", "C", "D", "E"],
        )
        assert db.scalar(select(func.count()).select_from(MainstreamItem)) == 20


def test_a_failed_list_leaves_the_today_list_the_run_and_the_exit_code(
    factory, monkeypatch
):
    with factory() as db:
        World(db)
        db.commit()

    def broken(db, day):
        raise RuntimeError("fixture mainstream crash")

    monkeypatch.setattr("worker.mainstream.compute_mainstream", broken)
    steps = _real_mainstream(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert DAILY_EXIT_CODES[result["status"]] == 0
    assert result["candidates"] == steps.results["candidates"]
    assert steps.calls[-3:] == ["action_tiers", "candidate_notes", "theme_discovery"]
    rows, by_run = runs(factory)
    logged = by_run[rows[0].id]
    assert rows[0].status == "success" and rows[0].error is None
    assert logged["candidates"].status == "success"
    assert logged["mainstream"].status == "failed"
    assert "fixture mainstream crash" in logged["mainstream"].error
    assert rows[0].summary_json["steps"]["mainstream"] == "failed"


def test_a_failure_is_a_warning_line_and_keeps_the_previous_list(factory, capsys):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.1] * 5))
        db.commit()
    assert run_mainstream(T)["records"] == 5
    with factory() as db:
        db.execute(
            MarketBar.__table__.delete().where(
                MarketBar.instrument_id == world.taiex, MarketBar.trading_date == T
            )
        )
        db.commit()
    result = run_mainstream(T)
    assert result["status"] == "failed"
    assert "MainstreamDataError" in result["error"]
    assert capsys.readouterr().err.startswith(
        f"warning: mainstream_v1 {T.isoformat()} failed: MainstreamDataError"
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MainstreamItem)) == 5


def test_a_rerun_of_the_day_replaces_the_whole_list(factory, monkeypatch):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.6, 0.5, 0.4, 0.3, 0.2, 0.1]))
        db.commit()
        ids = dict(world.ids)
    assert run_mainstream(T)["records"] == 6
    with factory() as db:
        # a5 leaves the group before the rerun: the old list must not survive.
        db.execute(
            GroupMembership.__table__.update()
            .where(GroupMembership.instrument_id == ids["a5"])
            .values(valid_to=T - timedelta(days=1))
        )
        db.commit()
    assert run_mainstream(T)["records"] == 5
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MainstreamRun)) == 1
        items = db.scalars(select(MainstreamItem)).all()
        assert len(items) == 5 and ids["a5"] not in {
            item.instrument_id for item in items
        }
        run = db.scalar(select(MainstreamRun))
        assert {item.mainstream_run_id for item in items} == {run.id}


def test_the_list_is_made_when_the_today_list_fails(factory, monkeypatch):
    with factory() as db:
        _five_groups(World(db))
        db.commit()
    _real_mainstream(monkeypatch, candidates=RuntimeError("fixture candidate crash"))
    result = pipeline.run_daily(T)
    assert result["status"] == "failed"  # the today list's failure, as before
    assert result["mainstream"]["status"] == "success"
    body = TestClient(app).get("/api/mainstream").json()
    assert body["status"] == "computed" and len(body["items"]) == 20
    assert [item["today_list"] for item in body["items"]] == [None] * 20


# --- AC-4: the API --------------------------------------------------------


def _today_list(db, world, ranks):
    run = CandidateRun(trading_date=T, score_version=CANDIDATE_SCORE_VERSION)
    db.add(run)
    db.flush()
    for symbol, (rank, entry_type) in ranks.items():
        signal = Signal(
            signal_key=f"fixture-{symbol}",
            signal_date=T,
            instrument_id=world.ids[symbol],
            status="conditional",
            entry_type=entry_type,
        )
        db.add(signal)
        db.flush()
        db.add(
            DailyCandidate(
                candidate_run_id=run.id,
                trading_date=T,
                instrument_id=world.ids[symbol],
                signal_id=signal.id,
                strategy="breakout_v3",
                score_version=CANDIDATE_SCORE_VERSION,
                total_score=80.0,
                weight_coverage=1.0,
                rank=rank,
                data_as_of=T,
            )
        )


def test_the_api_returns_a_computed_list_with_the_today_list(factory):
    with factory() as db:
        world = World(db, index_return=0.1)
        world.group("A", world.stocks("a", [0.6, 0.5, 0.4, 0.3, 0.2]))
        _today_list(db, world, {"a1": (3, "breakout"), "a4": (7, "pullback")})
        world.compute()
    client = TestClient(app)
    body = client.get("/api/mainstream").json()
    assert body == client.get(f"/api/mainstream?date={T.isoformat()}").json()
    assert (body["status"], body["trading_date"], body["version"]) == (
        "computed",
        T.isoformat(),
        "mainstream_v1",
    )
    assert (body["window"], body["group_count"]) == (240, 5)
    assert body["groups"] == [
        {
            "id": "A",
            "name": "族群A",
            "group_type": "theme",
            "strength": pytest.approx(0.5 - 0.1),
            "rank": 1,
            "member_count": 5,
            "top_count": 3,
        }
    ]
    items = body["items"]
    assert [item["instrument"]["symbol"] for item in items] == [
        "a0",
        "a1",
        "a2",
        "a3",
        "a4",
    ]
    first = items[0]
    assert first["rank"] == 1
    assert first["groups"] == [
        {"id": "A", "name": "族群A", "group_type": "theme", "rank": 1}
    ]
    assert (first["return_w"], first["excess_w"]) == (
        pytest.approx(0.6),
        pytest.approx(0.5),
    )
    assert first["market"]["close"] == pytest.approx(160.0)
    assert first["market"]["change_pct"] == pytest.approx(0.6)
    # The same shape as /api/candidates' recent_closes: 30 sessions, old to new.
    closes = first["recent_closes"]
    assert set(closes) == {"dates", "closes"}
    assert len(closes["dates"]) == len(closes["closes"]) == 30
    assert closes["dates"][-1] == T.isoformat()
    assert closes["closes"][-2:] == [100.0, pytest.approx(160.0)]
    assert [item["today_list"] for item in items] == [
        None,
        {"rank": 3, "entry_type": "breakout", "score_version": CANDIDATE_SCORE_VERSION},
        None,
        None,
        {"rank": 7, "entry_type": "pullback", "score_version": CANDIDATE_SCORE_VERSION},
    ]


def test_a_day_without_a_list_is_missing(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.1] * 5))
        world.compute()
    client = TestClient(app)
    body = client.get("/api/mainstream?date=2026-11-12").json()
    assert (body["status"], body["trading_date"], body["items"], body["groups"]) == (
        "missing",
        "2026-11-12",
        [],
        [],
    )
    with factory() as db:
        db.execute(MainstreamItem.__table__.delete())
        db.execute(MainstreamRun.__table__.delete())
        db.commit()
    assert client.get("/api/mainstream").json()["status"] == "missing"


def test_a_day_without_a_ranked_group_is_zero(factory):
    with factory() as db:
        world = World(db)
        world.group("A", world.stocks("a", [0.1] * 4))
        world.compute()
    body = TestClient(app).get("/api/mainstream").json()
    assert (body["status"], body["groups"], body["items"]) == ("zero", [], [])
    assert body["trading_date"] == T.isoformat()


# --- migration 0033 -------------------------------------------------------


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
    with closing(sqlite3.connect(path)) as connection:

        def indexes(table):
            return {
                row[1]: [
                    info[2]
                    for info in connection.execute(f"PRAGMA index_info('{row[1]}')")
                ]
                for row in connection.execute(f"PRAGMA index_list('{table}')")
            }

        def foreign(table):
            return {
                row[3]: row[2]
                for row in connection.execute(f"PRAGMA foreign_key_list('{table}')")
            }

        def not_null(table):
            return {
                row[1]: bool(row[3])
                for row in connection.execute(f"PRAGMA table_info('{table}')")
            }

        runs_index, items_index = (
            indexes("mainstream_runs"),
            indexes("mainstream_items"),
        )
        assert foreign("mainstream_runs") == {}
        assert foreign("mainstream_items") == {
            "mainstream_run_id": "mainstream_runs",
            "instrument_id": "instruments",
        }
        run_columns, item_columns = (
            not_null("mainstream_runs"),
            not_null("mainstream_items"),
        )
        marker = (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if entry == "alembic"
            else connection.execute(
                "SELECT version FROM schema_migrations "
                "WHERE version = '0033_mainstream_lists'"
            ).fetchall()
        )
    assert runs_index["ix_mainstream_runs_trading_date"] == ["trading_date"]
    assert ["trading_date", "version"] in runs_index.values()
    for column in ("mainstream_run_id", "trading_date", "instrument_id"):
        assert items_index[f"ix_mainstream_items_{column}"] == [column]
    assert ["trading_date", "instrument_id", "version"] in items_index.values()
    assert all(run_columns.values()) and set(run_columns) == {
        column.name for column in MainstreamRun.__table__.columns
    }
    assert all(item_columns.values()) and set(item_columns) == {
        column.name for column in MainstreamItem.__table__.columns
    }
    if entry == "alembic":
        # Later revisions move the head (#881): 0033 is in the chain below it.
        assert "0033_mainstream_lists" in REVISIONS
        assert marker == [(REVISIONS[-1],)]
    else:
        assert marker == [("0033_mainstream_lists",)]
