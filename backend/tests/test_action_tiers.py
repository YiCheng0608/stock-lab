"""Action-center tiers (action_tier_v1, #277-A / #278).

The list order is a cheap projection; the decision summaries are built only
for the requested page.  Most tests replace ``build_decision_summary`` with a
stub that returns a fixed action state, so the projection, paging and
filters are tested without the full decision history.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.decision as decision
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.domain import (
    CANDIDATE_SCORE_VERSION,
    INSTITUTIONAL_FLOW_FORMULA_VERSION,
    STRATEGY_LEVELS_VERSION,
)
from app.main import app
from app.migrations import upgrade_database
from app.models import (
    CandidateRun,
    DailyCandidate,
    Event,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    PortfolioPosition,
    Signal,
    StrategyLevel,
    StrategyVersion,
    ThemeGroup,
)
from app.strategies import REGISTRY
from app.strategies import levels as level_rules

AS_OF = date(2026, 10, 22)
# The verified sessions the summaries' 60-day bar readiness counts.
SESSIONS = [AS_OF - timedelta(days=index) for index in range(60)]


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tiers.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with make() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    yield make
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


class Market:
    """A small action-center universe on AS_OF."""

    def __init__(self, db):
        self.db = db
        self.ids: dict[str, int] = {}
        self.versions = {}
        for key, strategy in REGISTRY.items():
            version = StrategyVersion(
                name=key,
                version=strategy.version,
                formula_version=INSTITUTIONAL_FLOW_FORMULA_VERSION,
                kind="technical",
                config_json={},
                canonical_config_snapshot={},
            )
            db.add(version)
            self.versions[key] = version
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=AS_OF,
                status="success",
                records=1,
                data_as_of=AS_OF.isoformat(),
                request_key="tiers-fixture",
            )
        )
        self.run = CandidateRun(
            trading_date=AS_OF, score_version=CANDIDATE_SCORE_VERSION
        )
        db.add(self.run)
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
        self.bars(taiex.id, len(SESSIONS))

    def bars(self, instrument_id, count):
        for day in SESSIONS[:count]:
            self.db.add(
                MarketBar(
                    instrument_id=instrument_id,
                    trading_date=day,
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    adj_close=10,
                    volume=1000,
                    turnover=10000,
                    source="official-fixture",
                )
            )

    def stock(
        self, symbol, *, etf=False, watch=False, exchange="TWSE", bars=60, listed=None
    ):
        instrument = Instrument(
            market="TW",
            exchange=exchange,
            symbol=symbol,
            name=f"N{symbol}",
            instrument_type="etf" if etf else "stock",
            etf_category="equity" if etf else None,
            status="active",
            is_watchlisted=watch,
            listing_date=listed,
        )
        self.db.add(instrument)
        self.db.flush()
        self.ids[symbol] = instrument.id
        self.bars(instrument.id, bars)
        return instrument

    def signal(self, symbol, status, *, strategy="breakout_v1", quality="complete"):
        signal = Signal(
            signal_key=f"analysis-{symbol}-{strategy}",
            signal_date=AS_OF,
            instrument_id=self.ids[symbol],
            strategy_version_id=self.versions[strategy].id,
            status=status,
            data_quality=quality,
            entry_type="conditional",
        )
        self.db.add(signal)
        self.db.flush()
        return signal

    def candidate(self, symbol, rank):
        signal = self.signal(symbol, "conditional")
        self.db.add(
            DailyCandidate(
                candidate_run_id=self.run.id,
                trading_date=AS_OF,
                instrument_id=self.ids[symbol],
                signal_id=signal.id,
                strategy="breakout_v1",
                score_version=CANDIDATE_SCORE_VERSION,
                total_score=90 - rank,
                weight_coverage=1.0,
                rank=rank,
                data_as_of=AS_OF,
            )
        )

    def group(self, group_id, rank, members):
        self.db.add(ThemeGroup(id=group_id, name=group_id, active=True))
        self.db.flush()
        self.db.add(
            GroupDailyScore(
                group_id=group_id,
                trading_date=AS_OF,
                score=50,
                rank=rank,
                eligible_members=len(members),
                data_quality="complete",
                details_json={},
            )
        )
        for symbol in members:
            self.db.add(
                GroupMembership(
                    group_id=group_id,
                    instrument_id=self.ids[symbol],
                    valid_from=date(2020, 1, 1),
                    source="official",
                )
            )

    def levels(self, signal, unmet):
        strategy = REGISTRY["breakout_v1"]
        codes = list(level_rules.condition_defaults(strategy))
        self.db.add(
            StrategyLevel(
                signal_id=signal.id,
                levels_version=STRATEGY_LEVELS_VERSION,
                availability="levels",
                conditions_json=[
                    {"code": code, "satisfied": index >= unmet}
                    for index, code in enumerate(codes)
                ],
                price_basis="next_session_raw_basis",
            )
        )

    def hold(self, symbol, shares=1000):
        self.db.add(
            PortfolioPosition(
                instrument_id=self.ids[symbol], shares=shares, average_cost=10
            )
        )


# Holding states of the stubbed summaries; every other row is no_condition.
HOLDING_STATES = {
    "H1": "hold_observe",
    "H2": "data_insufficient",
    "H3": "manual_review",
    "H4": "reduce_exit",
}
FULL_ORDER = [
    # 0 holdings by state, not by code (HOLDING_STATE_ORDER); the ETF is held
    "H4",
    "H3",
    "H2",
    "H1",
    "HE",
    # 1 candidates by rank
    "C2",
    "C1",
    # 2 conditional by best group rank, then code; no group last; a cut stock and an ETF
    "E1",
    "K2",
    "K4",
    "K1",
    "K3",
    # 4 observation by unmet conditions; no strategy_levels row last
    "O2",
    "EV",
    "EO",
    "O1",
    "W1",
    "O3",
    # 5 data insufficient: the watchlist first; short of 60 days of bars too
    "D1",
    "B1",
    "B2",
    "D0",
    "D2",
]


def build_market(db) -> Market:
    market = Market(db)
    for symbol in ("H1", "H2", "H3", "H4"):
        market.stock(symbol)
        market.hold(symbol)
        market.signal(symbol, "observation")
    market.stock("HE", etf=True)
    market.hold("HE")
    for symbol, rank in (("C1", 2), ("C2", 1)):
        market.stock(symbol)
        market.candidate(symbol, rank)
    for symbol in ("K1", "K2", "K3", "K4"):
        market.stock(symbol)
        market.signal(symbol, "conditional")
    market.stock("E1", etf=True)
    market.signal("E1", "conditional")
    market.group("g-rank3", 3, ["K1", "C1"])
    market.group("g-rank1", 1, ["K2", "K4", "E1"])
    market.group("g-rank5", 5, ["K4"])
    observations = {}
    for symbol, kwargs in (
        ("O1", {}),
        ("O2", {}),
        ("O3", {}),
        ("W1", {"watch": True}),
        ("EV", {}),
        ("EO", {"etf": True}),
    ):
        market.stock(symbol, **kwargs)
        observations[symbol] = market.signal(symbol, "observation")
    market.levels(observations["O1"], 3)
    market.levels(observations["O2"], 1)
    market.levels(observations["W1"], 3)
    market.levels(observations["EV"], 2)
    market.levels(observations["EO"], 3)
    # A recent official event does not raise a tier (action_tier_v1).
    db.add(
        Event(
            instrument_id=market.ids["EV"],
            event_date=AS_OF - timedelta(days=1),
            event_type="material",
            title="event",
            source="mops",
        )
    )
    # Complete signals without 60 days of bars: a missing day, a recent listing.
    market.stock("B1", bars=59)
    market.signal("B1", "observation")
    market.stock("B2", listed=AS_OF - timedelta(days=10))
    market.signal("B2", "conditional")
    for symbol, watch in (("D2", False), ("D1", True), ("D0", False)):
        market.stock(symbol, watch=watch)
        market.signal(symbol, "data_incomplete", quality="incomplete")
    # D0 and D2 are listed through a recent event; D1 through the watchlist.
    for symbol in ("D0", "D2"):
        db.add(
            Event(
                instrument_id=market.ids[symbol],
                event_date=AS_OF,
                event_type="material",
                title="event",
                source="mops",
            )
        )
    db.commit()
    return market


@pytest.fixture
def stub_summaries(monkeypatch):
    """Replace the decision builder; returns the list of built instrument ids."""

    calls: list[int] = []

    def fake(db, instrument, as_of=None):
        calls.append(instrument.id)
        return {
            "instrument": {
                "id": instrument.id,
                "exchange": instrument.exchange,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "instrument_type": instrument.instrument_type,
            },
            "as_of": as_of.isoformat() if as_of else None,
            "action_state": HOLDING_STATES.get(instrument.symbol, "no_condition"),
            "held": instrument.symbol in HOLDING_STATES or instrument.symbol == "HE",
        }

    monkeypatch.setattr(decision, "build_decision_summary", fake)
    return calls


def _symbols(items):
    return [item["instrument"]["symbol"] for item in items]


def test_the_tier_rules_are_pinned_to_the_version():
    assert decision.ACTION_TIER_VERSION == "action_tier_v1"
    assert [
        (tier.tier, tier.key, tier.label, tier.order) for tier in decision.ACTION_TIERS
    ] == [
        (0, "holding_risk", "持倉風險", ("holding_state", "symbol", "exchange")),
        (1, "candidate", "今日候選", ("candidate_rank", "symbol", "exchange")),
        (2, "conditional", "其他成立條件", ("group_rank", "symbol", "exchange")),
        (3, "near", "接近成立", ("symbol", "exchange")),
        (4, "observation", "其他觀察", ("unmet_conditions", "symbol", "exchange")),
        (5, "data_insufficient", "資料待補", ("watchlist_first", "symbol", "exchange")),
    ]
    assert decision.HOLDING_STATE_ORDER == (
        "reduce_exit",
        "manual_review",
        "data_insufficient",
        "hold_observe",
    )
    assert decision.ACTION_VIEWS == {
        "focus": (0, 1, 2, 3),
        "with_observation": (0, 1, 2, 3, 4),
        "all": (0, 1, 2, 3, 4, 5),
    }
    assert decision.DEFAULT_ACTION_VIEW == "focus"
    # Tiers 2 and 4 need a bar on each of the last 60 verified sessions.
    assert decision.ACTION_TIER_BAR_SESSIONS == 60
    assert set(decision.ACTION_TIER_SORT_FIELDS) == {
        field for tier in decision.ACTION_TIERS for field in tier.order
    }


def test_the_projection_orders_every_tier(factory):
    with factory() as db:
        market = build_market(db)
        states = {market.ids[symbol]: state for symbol, state in HOLDING_STATES.items()}
        rows = decision.action_tier_rows(db, AS_OF, holding_states=states)
    assert [row.symbol for row in rows] == FULL_ORDER
    tiers = {row.symbol: row.tier for row in rows}
    assert [tiers[symbol] for symbol in FULL_ORDER] == [0] * 5 + [1] * 2 + [2] * 5 + [
        4
    ] * 6 + [5] * 5
    by_symbol = {row.symbol: row for row in rows}
    # The watchlist and a recent event keep their own tier.
    assert by_symbol["W1"].watchlisted and by_symbol["W1"].tier == 4
    assert by_symbol["EV"].tier == 4 and by_symbol["EV"].unmet_conditions == 2
    assert by_symbol["D1"].tier == 5
    assert (by_symbol["C2"].candidate_rank, by_symbol["C2"].candidate_score) == (1, 89)
    assert by_symbol["K4"].group_rank == 1 and by_symbol["K3"].group_rank is None
    assert by_symbol["O3"].unmet_conditions is None
    # Complete signals without a bar on each of the last 60 sessions: the
    # summary says data_insufficient (bars_60d), so the projection does too.
    assert by_symbol["B1"].tier == 5 and by_symbol["B2"].tier == 5


def test_the_60_session_bar_rule(factory):
    """action_tier_v1: a missing day or a listing within the window is tier 5."""

    with factory() as db:
        market = build_market(db)
        for symbol, kwargs in (
            ("F1", {}),  # every one of the 60 sessions
            ("M1", {"bars": 59}),  # one day missing
            ("N1", {"listed": SESSIONS[59] + timedelta(days=1)}),  # 59 sessions
            ("N2", {"listed": SESSIONS[59]}),  # listed on the window's first day
        ):
            market.stock(symbol, **kwargs)
            market.signal(symbol, "observation")
        db.commit()
        tiers = {row.symbol: row.tier for row in decision.action_tier_rows(db, AS_OF)}
    assert (tiers["F1"], tiers["N2"]) == (4, 4)
    assert (tiers["M1"], tiers["N1"]) == (5, 5)


def test_without_60_verified_sessions_tiers_2_and_4_are_data_insufficient(factory):
    with factory() as db:
        market = build_market(db)
        db.query(MarketBar).filter(
            MarketBar.instrument_id
            == db.query(Instrument.id)
            .filter(Instrument.symbol == "TAIEX")
            .scalar_subquery(),
            MarketBar.trading_date == SESSIONS[-1],
        ).delete(synchronize_session=False)
        db.commit()
        rows = decision.action_tier_rows(db, AS_OF)
    tiers = {row.symbol: row.tier for row in rows}
    assert {tiers[symbol] for symbol in ("K1", "E1", "O1", "W1")} == {5}
    # Holdings and the day's candidates keep their tiers.
    assert (tiers["H1"], tiers["C2"]) == (0, 1)
    assert market.ids["K1"]


def test_holdings_without_their_states_are_in_code_order(factory):
    with factory() as db:
        build_market(db)
        rows = decision.action_tier_rows(db, AS_OF)
    assert [row.symbol for row in rows][:5] == ["H1", "H2", "H3", "H4", "HE"]
    assert decision.prioritized_instrument_ids(db, AS_OF) == [
        row.instrument_id for row in rows
    ]


def test_build_action_summaries_keeps_the_callers_order(factory, stub_summaries):
    with factory() as db:
        market = build_market(db)
        ids = [market.ids[symbol] for symbol in ("D2", "H4", "C1", "O1")]
        summaries = decision.build_action_summaries(db, AS_OF, instrument_ids=ids)
    assert _symbols(summaries) == ["D2", "H4", "C1", "O1"]


def _walk(client, query, limit):
    items, cursor, pages = [], None, 0
    while True:
        url = f"/api/actions?{query}&limit={limit}" + (
            f"&cursor={cursor}" if cursor else ""
        )
        body = client.get(url).json()
        items += body["items"]
        pages += 1
        cursor = body["meta"]["next_cursor"]
        if not cursor:
            return items, body, pages


def test_cursor_pages_concatenate_to_the_whole_order(factory, stub_summaries):
    with factory() as db:
        build_market(db)
    with TestClient(app) as client:
        for limit in (1, 3, 4, 7, 100):
            items, body, pages = _walk(client, "view=all&include_etf=true", limit)
            assert _symbols(items) == FULL_ORDER, limit
            assert body["meta"]["total"] == len(FULL_ORDER)
            assert pages == -(-len(FULL_ORDER) // limit)
            assert all(item["tier"] is not None for item in items)
        tier_items, _body, _pages = _walk(client, "view=all&include_etf=true&tier=0", 2)
    assert _symbols(tier_items) == ["H4", "H3", "H2", "H1", "HE"]


def test_the_default_view_hides_etfs_observation_and_data_gaps(factory, stub_summaries):
    with factory() as db:
        build_market(db)
    with TestClient(app) as client:
        body = client.get("/api/actions?limit=100").json()
        with_etf = client.get("/api/actions?limit=100&include_etf=true").json()
        observation = client.get("/api/actions?limit=100&view=with_observation").json()
        everything = client.get("/api/actions?limit=100&view=all").json()
    # Holdings (the held ETF too) and the watchlist show in every view.
    assert _symbols(body["items"]) == [
        "H4", "H3", "H2", "H1", "HE", "C2", "C1", "K2", "K4", "K1", "K3", "W1", "D1",
    ]  # fmt: skip
    assert [item["tier"] for item in body["items"]] == [0] * 5 + [1] * 2 + [2] * 4 + [
        4,
        5,
    ]
    assert body["items"][5]["candidate"] == {"rank": 1, "total_score": 89}
    assert body["items"][7]["candidate"] is None
    # include_etf adds the ETFs only.
    assert set(_symbols(with_etf["items"])) - set(_symbols(body["items"])) == {"E1"}
    assert set(_symbols(observation["items"])) - set(_symbols(body["items"])) == {
        "O2",
        "EV",
        "O1",
        "O3",
    }
    assert set(_symbols(everything["items"])) - set(_symbols(observation["items"])) == {
        "B1",
        "B2",
        "D0",
        "D2",
    }
    summary = body["summary"]
    assert summary["tier_version"] == "action_tier_v1"
    assert (summary["view"], summary["include_etf"]) == ("focus", False)
    assert summary["hidden"] == {"etf": 2, "observation": 4, "data_insufficient": 4}
    assert summary["views"] == {"focus": 13, "with_observation": 17, "all": 21}
    assert summary["etf"] == 1
    assert with_etf["summary"]["hidden"] == {
        "etf": 0,
        "observation": 5,
        "data_insufficient": 4,
    }
    assert with_etf["summary"]["etf"] == 1
    assert everything["summary"]["etf"] == 2
    assert body["meta"]["sort"].startswith("action_tier_v1: tier asc; 0 holding_risk")


def test_the_header_counts_are_the_projection_counts(factory, stub_summaries):
    with factory() as db:
        build_market(db)
        rows = decision.action_tier_rows(db, AS_OF)
    with TestClient(app) as client:
        summary = client.get("/api/actions?limit=5").json()["summary"]
    expected = []
    for tier in decision.ACTION_TIERS:
        members = [row for row in rows if row.tier == tier.tier]
        shown = [
            row
            for row in members
            if decision.action_view_hidden_reason(row, "focus", False) is None
        ]
        expected.append(
            {
                "tier": tier.tier,
                "key": tier.key,
                "label": tier.label,
                "stock": sum(not row.is_etf for row in members),
                "etf": sum(row.is_etf for row in members),
                "shown": len(shown),
            }
        )
    assert summary["tiers"] == expected
    assert [item["shown"] for item in summary["tiers"]] == [5, 2, 4, 0, 1, 1]
    assert summary["total"] == 13


def test_a_search_reaches_every_tier_and_reports_it(factory, stub_summaries):
    with factory() as db:
        build_market(db)
    with TestClient(app) as client:
        etf = client.get("/api/actions?q=NE1").json()
        hidden = client.get("/api/actions?q=nd").json()
    assert [(item["instrument"]["symbol"], item["tier"]) for item in etf["items"]] == [
        ("E1", 2)
    ]
    assert [
        (item["instrument"]["symbol"], item["tier"]) for item in hidden["items"]
    ] == [
        ("D1", 5),
        ("D0", 5),
        ("D2", 5),
    ]
    # The header keeps the browsing filters' counts.
    assert hidden["summary"]["hidden"]["data_insufficient"] == 4


def test_a_tier_lists_one_tier(factory, stub_summaries):
    with factory() as db:
        build_market(db)
    with TestClient(app) as client:
        candidates = client.get("/api/actions?tier=1").json()
        observation = client.get("/api/actions?tier=4").json()
        all_observation = client.get("/api/actions?tier=4&view=all").json()
        bad = client.get("/api/actions?tier=6")
    assert _symbols(candidates["items"]) == ["C2", "C1"]
    assert candidates["meta"]["total"] == 2
    # The default view lists only the watchlisted observation.
    assert _symbols(observation["items"]) == ["W1"]
    assert _symbols(all_observation["items"]) == ["O2", "EV", "O1", "W1", "O3"]
    assert bad.status_code == 422


@pytest.mark.parametrize("view", ["focus", "with_observation", "all"])
@pytest.mark.parametrize("include_etf", ["false", "true"])
@pytest.mark.parametrize("tier", [None, 0, 1, 2, 3, 4, 5])
def test_a_request_builds_at_most_limit_summaries(
    factory, stub_summaries, view, include_etf, tier
):
    with factory() as db:
        build_market(db)
    query = f"view={view}&include_etf={include_etf}" + (
        f"&tier={tier}" if tier is not None else ""
    )
    with TestClient(app) as client:
        for limit in (1, 2, 5, 20):
            cursor = None
            while True:
                stub_summaries.clear()
                url = f"/api/actions?{query}&limit={limit}" + (
                    f"&cursor={cursor}" if cursor else ""
                )
                body = client.get(url).json()
                # AC-A3 as confirmed (#278 6420102565): the first page that
                # reaches tier 0 builds every holding once (five here), so it
                # stays within holdings + limit; every later page passes the
                # order on in its cursor and stays within the limit.
                bound = limit + 5 if cursor is None else limit
                assert len(stub_summaries) <= bound, url
                assert len(set(stub_summaries)) == len(stub_summaries), url
                cursor = body["meta"]["next_cursor"]
                if not cursor:
                    break


def test_more_holdings_than_the_limit_build_them_once(factory, stub_summaries):
    with factory() as db:
        build_market(db)
    builds, symbols, cursor = [], [], None
    with TestClient(app) as client:
        while True:
            stub_summaries.clear()
            body = client.get(
                "/api/actions?view=all&include_etf=true&limit=2"
                + (f"&cursor={cursor}" if cursor else "")
            ).json()
            builds.append(len(stub_summaries))
            symbols += _symbols(body["items"])
            cursor = body["meta"]["next_cursor"]
            if not cursor:
                break
        # A cursor whose holdings no longer match is ignored, not trusted.
        stale = api_module._encode_action_cursor(2, [1, 2])
        stub_summaries.clear()
        rebuilt = client.get(
            f"/api/actions?view=all&include_etf=true&limit=2&cursor={stale}"
        ).json()
    # Five holdings, limit 2: the first page builds the five (<= 5 + 2), the
    # holding pages after it build their own rows only.
    assert builds[0] == 5
    assert all(count <= 2 for count in builds[1:])
    assert symbols == FULL_ORDER
    assert _symbols(rebuilt["items"]) == ["H2", "H1"]
    assert len(stub_summaries) == 5


def test_holdings_ignore_the_etf_filter(factory, stub_summaries):
    with factory() as db:
        build_market(db)
    with TestClient(app) as client:
        body = client.get("/api/actions?tier=0").json()
    assert _symbols(body["items"]) == ["H4", "H3", "H2", "H1", "HE"]
    assert body["items"][-1]["instrument"]["instrument_type"] == "etf"


def test_the_dashboard_returns_every_holding(factory, stub_summaries):
    """#297 review L1: the holding-risk line read only the first 8 actions."""

    with factory() as db:
        market = Market(db)
        for index in range(10):
            symbol = f"P{index:02d}"
            market.stock(symbol)
            market.hold(symbol)
        db.commit()
        ids = dict(market.ids)
    risky = {ids["P09"]}
    with pytest.MonkeyPatch.context() as patch:
        real = decision.build_decision_summary

        def risk(db, instrument, as_of=None):
            item = real(db, instrument, as_of)
            if instrument.id in risky:
                item["action_state"] = "reduce_exit"
            return item

        patch.setattr(decision, "build_decision_summary", risk)
        with TestClient(app) as client:
            body = client.get("/api/dashboard").json()
    assert len(body["actions"]) == 8
    holdings = body["holding_actions"]
    assert len(holdings) == 10
    # The reduce_exit holding comes first, though its code is last.
    assert holdings[0]["instrument"]["symbol"] == "P09"
    assert holdings[0]["action_state"] == "reduce_exit"
    assert {item["instrument"]["symbol"] for item in holdings} == set(ids)
