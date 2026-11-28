"""候選池 candidate_pool_v1 (Issue #1020): sources, caps, written once, the
morning run, the daily step, the CLI, the API and migration 0039.

The fixture is 30 calendar days standing in for sessions (TAIEX has a bar on
each), T the last, with a small ``PoolConfig`` (5-session liquidity, 20-session
high).  Every stock is flat at 100 except where a test needs a source; most
have a 130 hump in the high window, so only the stocks built for it are near
their 240-session (here 20-session) high.
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.candidate_pool as candidate_pool
import app.main as main_module
import app.theme_heat as theme_heat
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
from app import migrations
from app.candidate_pool import (
    CAP,
    EVENING,
    MORNING,
    THEME_CAP,
    Entry,
    Hit,
    PoolConfig,
    compute_evening,
    compute_morning,
    select_entries,
)
from app.db import enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE_READ_VERSIONS
from app.main import app
from app.migration_revisions import REVISIONS
from app.migrations import upgrade_database
from app.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidateRun,
    ChipSnapshot,
    DailyCandidate,
    Event,
    GroupMembership,
    Instrument,
    MarketBar,
    MonthlyRevenue,
    NewsItem,
    NewsLlmResult,
    PortfolioPosition,
    RawPayload,
    Signal,
    StrategyListItem,
    StrategyListRun,
    ThemeClusterMember,
    ThemeClusterRun,
    ThemeGroup,
    ThemeHeatRun,
    ThemeHeatScore,
)
from test_daily_schedule import Steps, runs
from worker.cli import DAILY_EXIT_CODES
from worker.news_llm import PROMPT_VERSION

N = 30
FIRST = date(2026, 10, 1)
DAYS = [FIRST + timedelta(days=offset) for offset in range(N)]
T = DAYS[-1]
REAL_STEP = schedule_runs._candidate_pool_step
CONFIG = PoolConfig(
    liquidity_days=5,
    min_average_lots=5.0,
    near_high_sessions=20,
    near_high_min_sessions=10,
    chips_sessions=3,
    chips_top=2,
    revenue_sessions=3,
    hot_theme_members=3,
    cluster_members=2,
    theme_cap=2,
    morning_cap=2,
)
# 21:40 Taipei on T, UTC-naive: the evening run's computed_at.
EVENING_AT = datetime.combine(T, datetime.min.time()) + timedelta(hours=13, minutes=40)
# 08:20 Taipei the next day.
CHECKED = datetime.combine(T, datetime.min.time()) + timedelta(hours=24, minutes=20)


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    """Taipei ``hour:minute`` on ``day`` as stored (UTC-naive)."""

    return datetime.combine(day, datetime.min.time()) + timedelta(
        hours=hour - 8, minutes=minute
    )


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'pool.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with make() as db:
            yield db

    monkeypatch.setattr(pipeline, "SessionLocal", make)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    monkeypatch.setattr(candidate_pool, "DEFAULT_CONFIG", CONFIG)
    monkeypatch.setattr(candidate_pool, "utcnow", lambda: EVENING_AT)
    monkeypatch.setattr(
        theme_heat, "theme_keywords", lambda table=None: {"theme-b": ["記憶體"]}
    )
    app.dependency_overrides[api_module.get_db] = override_get_db
    yield make
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


class World:
    """The fixture's stocks by name; ``ids[name]`` is the instrument id."""

    def __init__(self, db):
        self.db = db
        self.ids: dict[str, int] = {}
        self.symbols: dict[str, str] = {}
        index = self.instrument("TAIEX", kind="index")
        for k, day in enumerate(DAYS):
            db.add(
                MarketBar(
                    instrument_id=index,
                    trading_date=day,
                    open=1000.0,
                    high=1000.0,
                    low=1000.0,
                    close=1000.0,
                    adj_close=1000.0,
                    volume=0,
                    turnover=0,
                )
            )
        self.raw = RawPayload(source="test", endpoint="fixture")
        db.add(self.raw)
        db.flush()

    def instrument(self, name, kind="stock", **extra) -> int:
        symbol = name if kind == "index" else str(2000 + len(self.ids))
        row = Instrument(
            exchange="TWSE",
            symbol=symbol,
            name=f"名{name}",
            instrument_type=kind,
            status="active",
            **extra,
        )
        self.db.add(row)
        self.db.flush()
        self.ids[name] = row.id
        self.symbols[name] = symbol
        return row.id

    def stock(
        self,
        name,
        *,
        lots=10.0,
        hump=True,
        last=None,
        last_volume=None,
        **extra,
    ) -> int:
        """Flat 100 (a 130 hump on days 10..14 when ``hump``); ``last`` is
        T's (open, high, low, close)."""

        instrument_id = self.instrument(name, **extra)
        for k, day in enumerate(DAYS):
            price = 130.0 if hump and 10 <= k <= 14 else 100.0
            bar = (price, price + 1, price - 1, price)
            volume = lots * 1000
            if k == N - 1:
                bar = last or bar
                volume = last_volume if last_volume is not None else volume
            self.db.add(
                MarketBar(
                    instrument_id=instrument_id,
                    trading_date=day,
                    open=bar[0],
                    high=bar[1],
                    low=bar[2],
                    close=bar[3],
                    adj_close=bar[3],
                    volume=volume,
                    turnover=bar[3] * volume,
                )
            )
        return instrument_id

    def theme(self, group_id, members):
        self.db.add(
            ThemeGroup(
                id=group_id,
                name=group_id,
                display_name_zh=f"題材{group_id[-1].upper()}",
                group_type="theme",
                active=True,
                name_status="verified",
            )
        )
        self.db.flush()
        for name in members:
            self.db.add(
                GroupMembership(
                    group_id=group_id,
                    instrument_id=self.ids[name],
                    role="member",
                    valid_from=DAYS[0],
                )
            )

    def news(self, names, *, collected, published=None, done=True, title="標題"):
        item = NewsItem(
            canonical_key=f"news-{collected.isoformat()}-{title}-{names}",
            source_kind="media",
            source_name="鉅亨",
            title=title,
            published_at=published or collected,
            display_time=published or collected,
            time_precision="datetime",
            collected_at=collected,
            symbols_json=[f"TWSE:{self.symbols[name]}" for name in names],
        )
        self.db.add(item)
        self.db.flush()
        if done:
            self.db.add(
                NewsLlmResult(
                    news_item_id=item.id,
                    prompt_version=PROMPT_VERSION,
                    llm_input_hash="h",
                    llm_status="done",
                    ai_impact_direction="positive",
                )
            )
        return item


def build(db) -> World:
    w = World(db)
    # Tier 1 and 2 (illiquid: 1 lot a day).
    w.stock("WAT", lots=1.0, is_watchlisted=True)
    w.stock("HOLD", lots=1.0)
    w.stock("RULE", lots=1.0)
    # Theme A: A1 the leader (largest amount), then A2 > A3 > A4 by 5-day excess.
    w.stock("A1", lots=50.0)
    w.stock("A2", last=(100.0, 104.0, 99.5, 104.0))
    w.stock("A3", last=(100.0, 102.0, 99.5, 102.0))
    w.stock("A4", last=(100.0, 101.0, 99.5, 100.5))
    # Theme B: in the morning's keyword news only.
    w.stock("B1", lots=40.0)
    w.stock("B2", last=(100.0, 103.0, 99.5, 103.0))
    w.stock("X1", lots=1.0)
    w.stock("C1")
    w.stock("C2")
    w.stock("C3")
    w.stock("N1")
    w.stock("N2")
    w.stock("M1", last=(100.0, 105.0, 99.5, 105.0))
    w.stock("M2")
    w.stock("R1")
    w.stock("R2")
    w.stock("R3")
    w.stock("K1")
    w.stock("K2")
    w.stock("K3")
    w.stock("V1", last=(100.0, 101.5, 99.5, 101.0), last_volume=40000)
    w.stock("L1", last=(100.0, 110.0, 99.5, 110.0))
    w.stock("G1", last=(104.0, 105.0, 103.5, 104.5))
    w.stock("G2", last=(104.0, 105.0, 100.5, 104.5))
    w.stock("H1", hump=False, last=(100.0, 101.0, 99.5, 100.5))
    w.stock("THIN", lots=1.0, last=(100.0, 110.0, 99.5, 110.0))
    w.stock("Z1")
    w.theme("theme-a", ["WAT", "A1", "A2", "A3", "A4"])
    w.theme("theme-b", ["B1", "B2"])
    db.add(PortfolioPosition(instrument_id=w.ids["HOLD"], shares=1000))
    # The today list.
    signal = Signal(signal_key="s-rule", signal_date=T, instrument_id=w.ids["RULE"])
    db.add(signal)
    run = CandidateRun(trading_date=T, score_version=CANDIDATE_SCORE_READ_VERSIONS[0])
    db.add(run)
    db.flush()
    db.add(
        DailyCandidate(
            candidate_run_id=run.id,
            trading_date=T,
            instrument_id=w.ids["RULE"],
            signal_id=signal.id,
            strategy="breakout_v3",
            score_version=run.score_version,
            total_score=0.8,
            weight_coverage=1.0,
            rank=1,
            data_as_of=T,
        )
    )
    # Theme heat: A ranked 1; B ranked 6 with no news surge.
    heat = ThemeHeatRun(
        trading_date=T,
        version="theme_heat_v1",
        status="computed",
        news_status="available",
    )
    db.add(heat)
    db.flush()
    for group_id, rank, ratio in (("theme-a", 1, 1.0), ("theme-b", 6, 2.0)):
        db.add(
            ThemeHeatScore(
                run_id=heat.id,
                trading_date=T,
                group_id=group_id,
                version="theme_heat_v1",
                rank=rank,
                heat=0.9 if rank == 1 else 0.2,
                quality="complete",
                components_json={"news": {"raw": ratio, "percentile": 0.5}},
            )
        )
    # H2 rank 1.
    lists = StrategyListRun(
        trading_date=T,
        strategy="h2",
        version="explore_research_v2_X2",
        definitions_sha256="0" * 64,
        status="computed",
    )
    db.add(lists)
    db.flush()
    db.add(
        StrategyListItem(
            run_id=lists.id,
            trading_date=T,
            instrument_id=w.ids["X1"],
            strategy="h2",
            version=lists.version,
            rank=1,
            close=100.0,
        )
    )
    # A cluster of C1..C3 (no theme).
    cluster = ThemeClusterRun(
        trading_date=T, version="theme_cluster_v1", status="computed"
    )
    db.add(cluster)
    db.flush()
    for name, excess in (("C1", 0.3), ("C2", 0.2), ("C3", 0.1)):
        db.add(
            ThemeClusterMember(
                theme_cluster_run_id=cluster.id,
                trading_date=T,
                instrument_id=w.ids[name],
                version="theme_cluster_v1",
                cluster_no=1,
                cluster_size=3,
                cluster_mean_corr=0.6,
                member_mean_corr=0.6,
                excess_return_20d=excess,
                amount_ratio_5_20=1.5,
                average_lots_20d=10.0,
            )
        )
    # News: N1's has an AI reading, N2's does not; an older one is out.
    w.news(["N1"], collected=_utc(T, 10))
    w.news(["N2"], collected=_utc(T, 11), done=False)
    w.news(["Z1"], collected=_utc(DAYS[-5], 10))
    # MOPS: M1 moved 5%, M2 did not.
    for name in ("M1", "M2"):
        db.add(
            Event(
                instrument_id=w.ids[name],
                event_date=T,
                event_type="material_information",
                title=f"{name} 重大訊息",
            )
        )
    # Revenue: R1 yoy 40; R2 turned positive; R3 neither.
    for name, yoy, prior in (("R1", 40.0, 35.0), ("R2", 10.0, -5.0), ("R3", 10.0, 5.0)):
        for month, value in ((date(2026, 9, 1), yoy), (date(2026, 8, 1), prior)):
            db.add(
                MonthlyRevenue(
                    instrument_id=w.ids[name],
                    revenue_month=month,
                    yoy=value,
                    announcement_date=T if month.month == 9 else DAYS[0],
                    source="test",
                    raw_payload_id=w.raw.id,
                    data_as_of="fixture",
                )
            )
    # Chips: K1 > K2 bought on the last 3 sessions, K3 sold.
    for name, buy in (("K1", 3000.0), ("K2", 1000.0), ("K3", -3000.0)):
        for day in DAYS[-3:]:
            db.add(
                ChipSnapshot(
                    instrument_id=w.ids[name],
                    trading_date=day,
                    foreign_buy=buy,
                    trust_buy=0.0,
                    dealer_buy=0.0,
                )
            )
    db.commit()
    return w


def _items(db, phase=EVENING) -> dict[str, CandidatePoolItem]:
    names = {row.id: row.name[1:] for row in db.scalars(select(Instrument))}
    return {
        names[row.instrument_id]: row
        for row in db.scalars(
            select(CandidatePoolItem).where(CandidatePoolItem.phase == phase)
        )
    }


def _sources(item) -> dict[str, dict]:
    return {entry["source"]: entry for entry in item.sources_json}


# --- AC-1: every source with its trigger value, data date and source ids ----


def test_every_source_names_its_stocks_with_value_date_and_ids(factory):
    with factory() as db:
        w = build(db)
        run, written = compute_evening(db, T, CONFIG)
        assert written and run.status == "computed"
        items = _items(db)
    expected = {
        "WAT": {"watchlist"},
        "HOLD": {"holding"},
        "RULE": {"rule_signal"},
        "A1": {"hot_theme"},
        "A2": {"hot_theme"},
        "A3": {"hot_theme"},
        "X1": {"h2"},
        "C1": {"cluster"},
        "C2": {"cluster"},
        "N1": {"news"},
        "M1": {"mops_event"},
        "R1": {"revenue"},
        "R2": {"revenue"},
        "K1": {"chips"},
        "K2": {"chips"},
        "V1": {"volume"},
        "L1": {"limit"},
        "G1": {"gap"},
        "H1": {"near_high_240"},
    }
    assert {name: set(_sources(item)) for name, item in items.items()} == expected
    # Not named: the 4th theme member, a news item without an AI reading, a
    # flat MOPS event, a small revenue rise, a seller, a filled gap, an
    # illiquid limit-up, the cluster's third, an old news item.
    for name in ("A4", "N2", "M2", "R3", "K3", "G2", "THIN", "C3", "Z1", "B1"):
        assert name not in items
    for item in items.values():
        assert item.source_count == len(item.sources_json) >= 1
        for entry in item.sources_json:
            assert set(entry) == {"source", "value", "data_date", "source_ids"}
            assert entry["data_date"] and entry["source_ids"]
    s = {name: _sources(item) for name, item in items.items()}
    assert s["WAT"]["watchlist"]["source_ids"] == [f"instrument:{w.ids['WAT']}"]
    assert s["HOLD"]["holding"]["value"] == {"shares": 1000.0}
    assert s["RULE"]["rule_signal"]["value"]["rank"] == 1
    assert s["RULE"]["rule_signal"]["source_ids"][0].startswith("daily_candidate:")
    a1, a2 = s["A1"]["hot_theme"]["value"], s["A2"]["hot_theme"]["value"]
    assert (a1["role"], a1["theme_id"], a1["theme_rank"], a1["reason"]) == (
        "leader",
        "theme-a",
        1,
        "top",
    )
    assert a2["role"] == "second"
    assert s["A1"]["hot_theme"]["source_ids"][0].startswith("theme_heat_score:")
    assert s["X1"]["h2"]["value"]["rank"] == 1
    assert s["C1"]["cluster"]["value"]["cluster_no"] == 1
    news = s["N1"]["news"]
    assert news["value"] == {"news_count": 1, "directions": {"positive": 1}}
    assert news["data_date"] == T.isoformat()
    assert news["source_ids"][0].startswith("news_item:")
    mops = s["M1"]["mops_event"]
    assert mops["value"]["return_1d"] == pytest.approx(0.05)
    assert mops["source_ids"][0].startswith("event:")
    assert s["R1"]["revenue"]["value"]["rule"] == "yoy_threshold"
    assert s["R2"]["revenue"]["value"]["rule"] == "turned_positive"
    assert s["R2"]["revenue"]["value"]["prior_month_yoy"] == -5.0
    assert s["R1"]["revenue"]["source_ids"][0].startswith("monthly_revenue:")
    assert s["K1"]["chips"]["value"]["rank"] == 1
    assert s["K1"]["chips"]["value"]["institutional_ratio_5d"] == pytest.approx(
        9000 / 50000
    )
    assert s["V1"]["volume"]["value"]["volume_ratio"] == pytest.approx(4.0)
    assert s["L1"]["limit"]["value"] == {"return_1d": 0.1, "direction": "up"}
    assert s["G1"]["gap"]["value"] == {"gap": 0.04, "direction": "up"}
    assert s["H1"]["near_high_240"]["value"]["high_gap_240"] == pytest.approx(
        100.5 / 101 - 1, abs=1e-6
    )
    for source in ("volume", "limit", "gap", "near_high_240"):
        name = {"volume": "V1", "limit": "L1", "gap": "G1", "near_high_240": "H1"}[
            source
        ]
        assert s[name][source]["source_ids"][0].startswith("market_bar:")
    # The run's counts and the stock's themes.
    assert run.source_counts_json["hot_theme"] == 3
    assert run.union_count == len(items)
    assert items["A1"].themes_json == [{"theme_id": "theme-a", "name": "題材A"}]
    assert items["A1"].features_json["average_lots_20d"] == pytest.approx(50.0)
    assert run.summary_json["inputs"]["hot_theme"] == "available"


def test_a_missing_input_is_recorded_not_filled(factory):
    with factory() as db:
        build(db)
        for model in (
            ThemeHeatScore,
            ThemeHeatRun,
            ThemeClusterMember,
            ThemeClusterRun,
        ):
            db.query(model).delete()
        db.commit()
        run, _ = compute_evening(db, T, CONFIG)
        items = _items(db)
    assert run.summary_json["inputs"]["hot_theme"] == "no_heat_run"
    assert run.summary_json["inputs"]["cluster"] == "no_cluster_run"
    assert run.summary_json["inputs"]["x4"] == "no_list"
    assert "hot_theme" not in run.source_counts_json
    assert "A1" not in items


def test_a_day_that_is_not_a_session_fails_without_writing(factory):
    from worker.candidate_pool import run_candidate_pool

    with factory() as db:
        build(db)
    result = run_candidate_pool(T + timedelta(days=1))
    assert result["status"] == "failed" and "no TAIEX bar" in result["error"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CandidatePoolRun)) == 0


# --- AC-2: the caps and the tiers --------------------------------------------


def _entry(instrument_id, sources, themes=(), move=0.0, order=0.0):
    entry = Entry(instrument_id)
    for source in sources:
        entry.add(Hit(source, {}, T, [f"x:{instrument_id}"], order=order))
    entry.themes = [{"theme_id": theme, "name": theme} for theme in themes]
    entry.features = {"return_5d": move}
    return entry


def test_selection_follows_the_tiers_and_records_cap_and_theme_cap():
    entries = [
        _entry(1, ["gap"], move=0.5),
        _entry(2, ["gap", "news"], move=0.01),
        _entry(3, ["h2"]),
        _entry(4, ["hot_theme"], themes=["t"], order=10),
        _entry(5, ["hot_theme"], themes=["t"], order=11),
        _entry(6, ["hot_theme"], themes=["t"], order=12),
        _entry(7, ["rule_signal"], themes=["t"]),
        _entry(8, ["watchlist"], themes=["t"]),
        _entry(9, ["news"], move=-0.6),
        _entry(10, ["volume"], themes=["t"], move=0.9),
    ]
    ordered = select_entries(entries, cap=6, theme_cap=2)
    picked = [(e.instrument_id, e.rank, e.tier) for e in ordered if e.selected]
    # Tier 1, 2 first (they fill theme t, exempt); theme t's others are
    # theme_cap; then H2; then tier 5: more sources first, then |5-day move|.
    assert picked == [(8, 1, 1), (7, 2, 2), (3, 3, 4), (2, 4, 5), (9, 5, 5), (1, 6, 5)]
    reasons = {e.instrument_id: e.reject_reason for e in ordered if not e.selected}
    assert reasons == {4: THEME_CAP, 5: THEME_CAP, 6: THEME_CAP, 10: THEME_CAP}
    # The total cap: past it every entry is cap, whatever its theme.
    ordered = select_entries(entries, cap=3, theme_cap=2)
    reasons = {e.instrument_id: e.reject_reason for e in ordered if not e.selected}
    assert reasons[4] == THEME_CAP and reasons[9] == CAP and reasons[1] == CAP
    assert [e.instrument_id for e in ordered if e.selected] == [8, 7, 3]


def test_tier_five_ranks_by_sources_then_the_five_day_move_only():
    # chips and cluster carry an order (their rank, the cluster number); tier 5
    # does not read it, so the bigger 5-day move goes first (review 7190403114).
    entries = [
        _entry(1, ["gap"], move=0.01),
        _entry(2, ["chips"], move=0.20, order=1),
        _entry(3, ["cluster"], move=-0.15, order=10),
        _entry(4, ["news"], move=0.05),
        _entry(5, ["mops_event", "chips"], move=0.0, order=30),
    ]
    ordered = select_entries(entries, cap=10, theme_cap=4)
    assert [e.instrument_id for e in ordered] == [5, 2, 3, 4, 1]
    # The morning's one source keeps its order: more news first.
    morning = [
        _entry(6, ["morning_news"], move=0.30, order=-1),
        _entry(7, ["morning_news"], move=0.01, order=-3),
    ]
    assert [e.instrument_id for e in select_entries(morning, 10, 4)] == [7, 6]
    # Tiers 2-4 still read theirs: the H2 rank before the move.
    lists = [_entry(8, ["h2"], move=0.5, order=9), _entry(9, ["h2"], order=1)]
    assert [e.instrument_id for e in select_entries(lists, 10, 4)] == [9, 8]


def test_tier_one_and_two_are_not_held_by_the_theme_cap():
    entries = [
        _entry(1, ["hot_theme"], themes=["t"], order=1),
        _entry(2, ["hot_theme"], themes=["t"], order=2),
        _entry(3, ["watchlist"], themes=["t"]),
        _entry(4, ["holding"], themes=["t"]),
        _entry(5, ["rule_signal"], themes=["t"]),
    ]
    ordered = select_entries(entries, cap=10, theme_cap=2)
    assert {e.instrument_id for e in ordered if e.selected} == {3, 4, 5}
    assert {e.reject_reason for e in ordered if not e.selected} == {THEME_CAP}


def test_the_stored_pool_keeps_the_left_out_with_their_reason(factory):
    with factory() as db:
        build(db)
        run, _ = compute_evening(db, T, CONFIG)
        items = _items(db)
    # Theme A: WAT (tier 1) and A1 fill the cap of 2; A2 and A3 are left out.
    assert items["WAT"].selected and items["A1"].selected
    assert (items["A2"].selected, items["A2"].reject_reason) == (False, THEME_CAP)
    assert (items["A3"].selected, items["A3"].reject_reason) == (False, THEME_CAP)
    assert items["A2"].rank is None
    assert [items[n].rank for n in ("WAT", "HOLD", "RULE", "A1", "X1")] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert run.summary_json["rejected"] == {THEME_CAP: 2}
    assert run.selected_count == run.union_count - 2


def test_a_small_cap_selects_the_first_tiers(factory):
    with factory() as db:
        build(db)
        run, _ = compute_evening(
            db, T, PoolConfig(**{**CONFIG.__dict__, "evening_cap": 3})
        )
        items = _items(db)
    assert {n for n, item in items.items() if item.selected} == {"WAT", "HOLD", "RULE"}
    # Past the cap every one is cap, also A2 and A3 (theme_cap with room).
    assert Counter(
        item.reject_reason for item in items.values() if not item.selected
    ) == {CAP: len(items) - 3}
    assert run.cap == 3 and run.selected_count == 3
    assert run.config_json["evening_cap"] == 3


def test_the_three_caps_are_settings_with_the_agreed_defaults():
    config = PoolConfig()
    assert (config.evening_cap, config.morning_cap, config.theme_cap) == (40, 10, 4)
    assert config.as_json()["version"] == "candidate_pool_v1"


# --- AC-3: one run per day and phase, written once ----------------------------


def test_a_rerun_returns_the_stored_run_and_writes_nothing(factory):
    with factory() as db:
        w = build(db)
        first, written = compute_evening(db, T, CONFIG)
        assert written
        before = {(i.instrument_id, i.rank, i.selected) for i in _items(db).values()}
        # New data after the run does not change it.
        w.news(["Z1"], collected=_utc(T, 12))
        db.commit()
        again, written = compute_evening(db, T, CONFIG)
        assert not written and again.id == first.id
        assert {
            (i.instrument_id, i.rank, i.selected) for i in _items(db).values()
        } == before
        assert db.scalar(select(func.count()).select_from(CandidatePoolRun)) == 1
        morning, written = compute_morning(db, T, CHECKED, CONFIG)
        assert written
        again, written = compute_morning(db, T, CHECKED + timedelta(hours=1), CONFIG)
        assert not written and again.id == morning.id
        assert db.scalar(select(func.count()).select_from(CandidatePoolRun)) == 2


def test_the_table_refuses_a_second_run_of_a_day_and_phase(factory):
    from sqlalchemy.exc import IntegrityError

    with factory() as db:
        build(db)
        compute_evening(db, T, CONFIG)
        db.add(
            CandidatePoolRun(
                trading_date=T,
                version="candidate_pool_v1",
                phase=EVENING,
                status="computed",
                cap=40,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_the_dry_run_writes_nothing(factory):
    from worker.candidate_pool import run_candidate_pool, run_morning_pool

    with factory() as db:
        build(db)
    result = run_candidate_pool(T, dry_run=True)
    assert result["status"] == "success" and result["dry_run"]
    assert result["run_id"] is None and result["reason"] is None
    assert result["selected"][0]["sources"] == ["watchlist"]
    assert run_morning_pool(T, CHECKED, dry_run=True)["reason"] == "no_evening_run"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CandidatePoolRun)) == 0


# --- AC-4: the morning run ------------------------------------------------------


def test_the_morning_adds_only_stocks_named_after_the_evening(factory):
    with factory() as db:
        w = build(db)
        compute_evening(db, T, CONFIG)
        # Before the evening run: not counted.
        w.news(["A4"], collected=EVENING_AT - timedelta(minutes=1))
        # After it: Z1 by its code (twice), N1 is already in the evening.
        w.news(["Z1"], collected=_utc(T, 22), title="一")
        w.news(["Z1"], collected=_utc(T, 23), title="二", done=False)
        w.news(["N1"], collected=_utc(T, 22, 30))
        # A theme keyword: theme B's leader and next (morning_theme_members 3).
        w.news(["THIN"], collected=_utc(T + timedelta(days=1), 7), title="記憶體報價")
        # Collected after the check: not counted.
        w.news(["M2"], collected=CHECKED + timedelta(minutes=1))
        db.commit()
        run, written = compute_morning(db, T, CHECKED, CONFIG)
        items = _items(db, MORNING)
    assert written and run.phase == MORNING and run.base_run_id is not None
    assert set(items) == {"Z1", "B1", "B2"}
    z1 = _sources(items["Z1"])["morning_news"]
    assert z1["value"]["via"] == "symbol" and z1["value"]["news_count"] == 2
    assert z1["value"]["directions"] == {"not_judged": 1, "positive": 1}
    assert len(z1["source_ids"]) == 2
    b1 = _sources(items["B1"])["morning_news"]["value"]
    assert (b1["via"], b1["theme_id"], b1["role"]) == ("theme", "theme-b", "leader")
    # morning_cap 2: Z1 first (2 news), then B2 (1 news, moved 3%) before B1
    # (1 news, flat); B1 is cap.
    assert [n for n in ("Z1", "B2") if items[n].selected] == ["Z1", "B2"]
    assert (items["B1"].selected, items["B1"].reject_reason) == (False, CAP)
    assert run.summary_json["window_start"] == EVENING_AT.isoformat()
    assert run.summary_json["news_items"] == 4


def test_the_morning_cap_is_ten_by_default_and_skips_without_an_evening(factory):
    config = PoolConfig(**{**CONFIG.__dict__, "morning_cap": 10})
    with factory() as db:
        w = build(db)
        assert compute_morning(db, T, CHECKED, config) == (None, False)
        for k in range(12):
            w.stock(f"P{k}")
        db.commit()
        compute_evening(db, T, config)
        for k in range(12):
            w.news([f"P{k}"], collected=_utc(T, 22), title=f"p{k}")
        db.commit()
        run, _ = compute_morning(db, T, CHECKED, config)
        items = _items(db, MORNING)
    assert run.selected_count == 10 and run.union_count == 12
    assert Counter(i.reject_reason for i in items.values()) == {None: 10, CAP: 2}


def test_a_morning_not_after_the_evening_fails_and_writes_nothing(factory):
    from worker.candidate_pool import run_morning_pool

    with factory() as db:
        build(db)
        compute_evening(db, T, CONFIG)
        with pytest.raises(candidate_pool.CandidatePoolDataError):
            compute_morning(db, T, EVENING_AT, CONFIG)
    result = run_morning_pool(T, EVENING_AT - timedelta(minutes=1))
    assert result["status"] == "failed" and "is not after" in result["error"]
    with factory() as db:
        assert cp_runs(db, MORNING) == 0


def cp_runs(db, phase) -> int:
    return db.scalar(
        select(func.count())
        .select_from(CandidatePoolRun)
        .where(CandidatePoolRun.phase == phase)
    )


def test_the_morning_counts_the_evening_toward_the_theme_cap(factory):
    with factory() as db:
        w = build(db)
        compute_evening(db, T, CONFIG)
        # A4 is in theme A, which has 2 selected in the evening (WAT, A1).
        w.news(["A4"], collected=_utc(T, 22))
        db.commit()
        compute_morning(db, T, CHECKED, CONFIG)
        items = _items(db, MORNING)
    assert (items["A4"].selected, items["A4"].reject_reason) == (False, THEME_CAP)


# --- the daily step, the CLI and the API --------------------------------------


def _real_step(monkeypatch, **results):
    steps = Steps(monkeypatch, **results)
    monkeypatch.setattr(schedule_runs, "_candidate_pool_step", REAL_STEP)
    return steps


def test_the_daily_writes_the_evening_last(factory, monkeypatch):
    with factory() as db:
        build(db)
    steps = _real_step(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert result["candidate_pool"]["status"] == "success"
    # The real step is not a recorded fake: it runs between theme_discovery and
    # premarket_score (#1043) and ai_list_score (#1147).
    assert steps.calls[-3:] == ["theme_discovery", "premarket_score", "ai_list_score"]
    rows, by_run = runs(factory)
    step = by_run[rows[0].id]["candidate_pool"]
    assert (step.status, step.sequence) == ("success", 17)
    assert step.records == result["candidate_pool"]["records"] > 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CandidatePoolRun)) == 1


def test_a_failure_is_a_warning_and_keeps_the_run(factory, monkeypatch, capsys):
    with factory() as db:
        build(db)

    def broken(db, day, **_kwargs):
        raise RuntimeError("fixture pool crash")

    monkeypatch.setattr("worker.candidate_pool.compute_evening", broken)
    _real_step(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert DAILY_EXIT_CODES[result["status"]] == 0
    assert "warning: candidate_pool_v1 evening" in capsys.readouterr().err
    rows, by_run = runs(factory)
    assert rows[0].status == "success" and rows[0].error is None
    assert by_run[rows[0].id]["candidate_pool"].status == "failed"


def test_the_cli_dispatches_both_phases(factory, monkeypatch, capsys):
    import worker.cli as cli

    calls = []
    monkeypatch.setattr(
        cli,
        "run_candidate_pool",
        lambda day, dry_run: calls.append(("evening", day, dry_run))
        or {"status": "success"},
    )
    monkeypatch.setattr(
        cli,
        "run_morning_pool",
        lambda day, at, dry_run: calls.append(("morning", day, at, dry_run))
        or {"status": "skipped", "reason": "no_evening_run"},
    )
    monkeypatch.setattr(
        sys, "argv", ["worker.cli", "candidate-pool", "--date", T.isoformat()]
    )
    cli.main()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker.cli",
            "candidate-pool",
            "--date",
            T.isoformat(),
            "--phase",
            "morning",
            "--now",
            f"{(T + timedelta(days=1)).isoformat()}T08:20",
            "--dry-run",
        ],
    )
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 1
    assert calls == [("evening", T, False), ("morning", T, CHECKED, True)]
    assert '"reason": "no_evening_run"' in capsys.readouterr().out
    # Not ISO 8601: a usage error, not a traceback.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker.cli",
            "candidate-pool",
            "--date",
            T.isoformat(),
            "--phase",
            "morning",
            "--now",
            "8:20 tomorrow",
        ],
    )
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 2
    # --now is the morning's only.
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker.cli", "candidate-pool", "--date", T.isoformat(), "--now", "08:20"],
    )
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 2


def test_the_api_tells_a_missing_morning_from_an_empty_one(factory):
    with factory() as db:
        w = build(db)
        compute_evening(db, T, CONFIG)
    client = TestClient(app)
    body = client.get("/api/candidate-pool").json()
    meta = body["meta"]
    assert (meta["trading_date"], meta["not_a_signal"], meta["empty_reason"]) == (
        T.isoformat(),
        "不是買賣訊號",
        None,
    )
    assert meta["phases"]["evening"]["selected_count"] == len(body["items"])
    assert meta["phases"]["morning"] is None
    first = body["items"][0]
    assert first["instrument"]["symbol"] == w.symbols["WAT"]
    assert (first["rank"], first["tier"], first["phase"]) == (1, 1, EVENING)
    assert first["sources"][0]["source"] == "watchlist"
    assert all(item["selected"] for item in body["items"])
    full = client.get(
        f"/api/candidate-pool?date={T.isoformat()}&include_rejected=true"
    ).json()
    rejected = [item for item in full["items"] if not item["selected"]]
    assert {item["reject_reason"] for item in rejected} == {THEME_CAP}
    with factory() as db:
        compute_morning(db, T, CHECKED, CONFIG)
    after = client.get(f"/api/candidate-pool?date={T.isoformat()}").json()
    morning = after["meta"]["phases"]["morning"]
    # A morning with no news: stored, zero, not null.
    assert (morning["status"], morning["selected_count"]) == ("zero", 0)
    none = client.get(f"/api/candidate-pool?date={DAYS[3].isoformat()}").json()
    assert (none["items"], none["meta"]["empty_reason"]) == ([], "not_computed")
    assert none["meta"]["phases"] == {"evening": None, "morning": None}


# --- migration 0039 -----------------------------------------------------------


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
                "SELECT name FROM sqlite_master WHERE name LIKE 'ix_candidate_pool_%'"
            )
        }
    return tables & {"candidate_pool_runs", "candidate_pool_items"}, indexes


# The candidate pool's revision, found by name so a renumbering keeps the test.
MIGRATION = next(name for name in REVISIONS if name.endswith("_candidate_pool"))
INDEXES = {
    "ix_candidate_pool_runs_trading_date",
    "ix_candidate_pool_items_run_id",
    "ix_candidate_pool_items_trading_date",
    "ix_candidate_pool_items_instrument_id",
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
    assert _tables(path) == ({"candidate_pool_runs", "candidate_pool_items"}, INDEXES)
    with closing(sqlite3.connect(path)) as connection:
        if entry == "alembic":
            assert MIGRATION in REVISIONS
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall() == [(REVISIONS[-1],)]
        else:
            assert connection.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                (MIGRATION,),
            ).fetchall() == [(MIGRATION,)]


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
        command.upgrade(config, MIGRATION)
        command.downgrade(config, REVISIONS[REVISIONS.index(MIGRATION) - 1])
        assert _tables(path) == (set(), set())
        command.upgrade(config, MIGRATION)
    finally:
        engine.dispose()
    assert _tables(path) == ({"candidate_pool_runs", "candidate_pool_items"}, INDEXES)
