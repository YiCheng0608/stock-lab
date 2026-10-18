"""Theme table (題材表) schema, sync, industry/theme boards and themes API."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
import worker.pipeline as pipeline
import worker.themes as themes_module
from app.db import enable_sqlite_foreign_keys
from app.domain import GROUP_SCORE_WEIGHTS
from app.main import app
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    NewsLlmResult,
    TechnicalFeature,
    ThemeGroup,
)
from app.theme_table import (
    THEME_CANDIDATE_GROUP_TYPE,
    THEME_CANDIDATE_NAME_STATUS,
    THEME_TABLE_PATH,
    ThemeTableError,
    load_theme_table,
    parse_membership_source,
    validate_theme_table,
)
from worker.theme_suggestions import refresh_theme_suggestions

SCORE_DATE = date(2026, 9, 4)
LOCAL_API = "http://127.0.0.1:8000"


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'themes.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _member(instrument: str, **overrides):
    member = {
        "instrument": instrument,
        "relation": "core_business",
        "relevance": "high",
        "evidence": [
            {
                "url": f"https://example.com/{instrument.replace(':', '-')}",
                "title": "fixture evidence",
                "quote": "fixture quote",
            }
        ],
    }
    member.update(overrides)
    return member


def _table(**overrides):
    table = {
        "schema_version": "theme-table/v1",
        "table": "themes_v1",
        "version": "2026.09.01",
        "themes": [
            {
                "id": "alpha",
                "name": "甲題材",
                "description": "測試題材甲",
                "valid_from": "2026-08-01",
                "members": [
                    _member("TWSE:1001"),
                    _member("TWSE:1002"),
                    _member("TPEx:2001"),
                ],
            }
        ],
    }
    table.update(overrides)
    return table


def _add_instruments(db, symbols, instrument_type="stock"):
    rows = []
    for exchange, symbol in symbols:
        row = Instrument(
            market="TW",
            exchange=exchange,
            symbol=symbol,
            name=symbol,
            instrument_type=instrument_type,
            status="active",
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def _memberships(db):
    return sorted(
        (
            row.group_id,
            row.instrument_id,
            row.valid_from,
            row.valid_to,
            row.source,
            row.role,
        )
        for row in db.scalars(select(GroupMembership)).all()
    )


# AC-1: schema validation


def test_repo_theme_table_is_valid_and_every_member_has_evidence():
    table = load_theme_table(THEME_TABLE_PATH)
    assert 10 <= len(table["themes"]) <= 15
    for theme in table["themes"]:
        assert len(theme["members"]) >= 3, theme["id"]
        for member in theme["members"]:
            assert member["evidence"] and all(
                item["url"].startswith(("https://", "http://"))
                for item in member["evidence"]
            )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda t: t["themes"][0]["members"][1].update(evidence=[]),
            "themes[0](alpha).members[1](TWSE:1002).evidence: at least one",
        ),
        (
            lambda t: t["themes"][0]["members"][1]["evidence"][0].pop("quote"),
            "themes[0](alpha).members[1](TWSE:1002).evidence[0].quote: non-empty text required",
        ),
        (
            lambda t: t["themes"][0]["members"][1].pop("evidence"),
            "themes[0](alpha).members[1](TWSE:1002).evidence: at least one",
        ),
        (
            lambda t: t["themes"][0]["members"][0]["evidence"][0].update(
                url="not-a-url"
            ),
            "themes[0](alpha).members[0](TWSE:1001).evidence[0].url",
        ),
        (
            lambda t: t["themes"][0]["members"][2].update(
                valid_from="2026-09-10", valid_to="2026-09-01"
            ),
            "themes[0](alpha).members[2](TPEx:2001): valid_to 2026-09-01 is before valid_from 2026-09-10",
        ),
        (
            lambda t: t["themes"][0].update(valid_to="2026-07-01"),
            "themes[0](alpha): valid_to 2026-07-01 is before valid_from 2026-08-01",
        ),
        (
            lambda t: t["themes"][0]["members"].append(_member("TWSE:1001")),
            "themes[0](alpha).members[3](TWSE:1001): duplicate member in theme",
        ),
        (
            lambda t: t["themes"][0]["members"][0].update(instrument="2330"),
            "themes[0](alpha).members[0].instrument",
        ),
        (
            lambda t: t["themes"][0]["members"][0].update(relation="rumour"),
            "themes[0](alpha).members[0](TWSE:1001).relation",
        ),
        (
            lambda t: t["themes"].append(copy.deepcopy(t["themes"][0])),
            "themes[1](alpha).id: duplicate theme id",
        ),
        (
            lambda t: t["themes"][0]["members"][0]["evidence"][0].update(
                url="https://example.com/" + "x" * 480
            ),
            "themes[0](alpha).members[0](TWSE:1001).evidence: stored evidence exceeds 500 characters",
        ),
    ],
)
def test_schema_rejects_with_location(mutate, expected):
    table = _table()
    mutate(table)
    errors = validate_theme_table(table)
    assert any(error.startswith(expected) for error in errors), errors


def test_valid_fixture_has_no_errors():
    assert validate_theme_table(_table()) == []


def test_sync_rejects_unknown_and_non_stock_instruments_without_writing(factory):
    with factory() as db:
        _add_instruments(db, [("TWSE", "1001"), ("TWSE", "1002")])
        _add_instruments(db, [("TPEx", "2001")], instrument_type="etf")
        table = _table()
        table["themes"][0]["members"].append(_member("TWSE:9999"))
        with pytest.raises(ThemeTableError) as error:
            themes_module.apply_theme_table(db, table)
        assert (
            "themes[0](alpha).members[2](TPEx:2001): instrument_type=etf is not a stock"
            in error.value.errors
        )
        assert (
            "themes[0](alpha).members[3](TWSE:9999): unknown instrument"
            in error.value.errors
        )
        assert db.scalars(select(ThemeGroup)).all() == []
        assert _memberships(db) == []


# AC-1: sync idempotency and closing members


def test_sync_twice_is_identical_and_valid_to_closes_without_deleting(factory):
    with factory() as db:
        rows = _add_instruments(
            db, [("TWSE", "1001"), ("TWSE", "1002"), ("TPEx", "2001")]
        )
        first = themes_module.apply_theme_table(db, _table())
        snapshot = _memberships(db)
        second = themes_module.apply_theme_table(db, _table())
        assert first["groups_created"] == 1 and first["memberships_created"] == 3
        assert {
            key: second[key]
            for key in second
            if key.startswith(("groups_", "memberships_"))
        } == dict.fromkeys(
            (
                "groups_created",
                "groups_updated",
                "memberships_created",
                "memberships_updated",
                "memberships_closed",
            ),
            0,
        )
        assert _memberships(db) == snapshot
        group = db.get(ThemeGroup, "theme-alpha")
        assert (group.group_type, group.definition_version, group.name_status) == (
            "theme",
            "themes_v1:2026.09.01",
            "verified",
        )
        evidence = parse_membership_source(snapshot[0][4])
        assert set(json.loads(snapshot[0][4])) == {
            "kind",
            "url",
            "relation",
            "relevance",
            "theme_version",
        }
        assert evidence == {
            "url": "https://example.com/TWSE-1001",
            "relation": "core_business",
            "relevance": "high",
            "theme_version": "themes_v1:2026.09.01",
        }

        version_two = _table(version="2026.09.20")
        version_two["themes"][0]["members"][1]["valid_to"] = "2026-09-19"
        result = themes_module.apply_theme_table(db, version_two)
        themes_module.apply_theme_table(db, version_two)
        assert result["memberships_closed"] == 1
        closed = db.scalar(
            select(GroupMembership).where(GroupMembership.instrument_id == rows[1].id)
        )
        assert closed.valid_to == date(2026, 9, 19)
        assert len(_memberships(db)) == 3
        assert (
            db.get(ThemeGroup, "theme-alpha").definition_version
            == "themes_v1:2026.09.20"
        )
        assert (
            pipeline._effective_memberships(
                db, "theme-alpha", date(2026, 9, 19)
            ).__len__()
            == 3
        )
        assert (
            pipeline._effective_memberships(
                db, "theme-alpha", date(2026, 9, 20)
            ).__len__()
            == 2
        )


def test_sync_rejects_removed_member_or_theme_without_valid_to(factory):
    with factory() as db:
        _add_instruments(db, [("TWSE", "1001"), ("TWSE", "1002"), ("TPEx", "2001")])
        themes_module.apply_theme_table(db, _table())
        removed = _table()
        removed["themes"][0]["members"].pop(1)
        with pytest.raises(ThemeTableError) as error:
            themes_module.apply_theme_table(db, removed)
        assert (
            "themes[0](alpha): TWSE:1002 has an open membership but is missing from the table; set valid_to"
            in error.value.errors
        )

        renamed = _table()
        renamed["themes"][0]["id"] = "beta"
        with pytest.raises(ThemeTableError) as error:
            themes_module.apply_theme_table(db, renamed)
        assert (
            "theme_groups(theme-alpha): theme missing from table; keep it with valid_to instead of deleting"
            in error.value.errors
        )


def test_sync_rejects_older_version_and_same_version_content_change(factory):
    with factory() as db:
        _add_instruments(db, [("TWSE", "1001"), ("TWSE", "1002"), ("TPEx", "2001")])
        themes_module.apply_theme_table(db, _table(version="2026.09.10"))
        snapshot = _memberships(db)

        with pytest.raises(ThemeTableError) as error:
            themes_module.apply_theme_table(db, _table(version="2026.09.01"))
        assert error.value.errors == [
            "$.version: themes_v1:2026.09.01 is lower than DB definition_version themes_v1:2026.09.10"
        ]

        edited = _table(version="2026.09.10")
        edited["themes"][0]["members"][1]["relevance"] = "low"
        edited["themes"][0]["description"] = "改過的說明"
        with pytest.raises(ThemeTableError) as error:
            themes_module.apply_theme_table(db, edited)
        assert error.value.errors == [
            "themes[0](alpha): content differs from DB but $.version equals DB definition_version themes_v1:2026.09.10; bump $.version",
            "themes[0](alpha).members[1](TWSE:1002): content differs from DB but $.version equals DB definition_version themes_v1:2026.09.10; bump $.version",
        ]
        assert _memberships(db) == snapshot
        assert (
            db.get(ThemeGroup, "theme-alpha").definition_version
            == "themes_v1:2026.09.10"
        )

        # A sub-version bump with the same edit is accepted.
        result = themes_module.apply_theme_table(
            db, {**edited, "version": "2026.09.10.1"}
        )
        assert (result["groups_updated"], result["memberships_updated"]) == (1, 3)


def test_cli_sync_reports_located_errors_and_commits_valid_table(
    factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(themes_module, "SessionLocal", factory)
    with factory() as db:
        _add_instruments(db, [("TWSE", "1001"), ("TWSE", "1002"), ("TPEx", "2001")])
        db.commit()
    bad = _table()
    bad["themes"][0]["members"][0]["evidence"] = []
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    failed = themes_module.sync_themes(bad_path)
    assert failed["status"] == "failed"
    assert failed["errors"][0].startswith(
        "themes[0](alpha).members[0](TWSE:1001).evidence"
    )
    good_path = tmp_path / "good.json"
    good_path.write_text(json.dumps(_table()), encoding="utf-8")
    assert themes_module.sync_themes(good_path)["memberships_created"] == 3
    assert themes_module.sync_themes(good_path)["memberships_created"] == 0
    with factory() as db:
        assert len(_memberships(db)) == 3


# AC-2: industry and theme boards


def _market_fixture(db, growth: dict[str, float]):
    """TAIEX plus one stock per symbol with a constant daily growth rate."""

    dates = pipeline.business_days(SCORE_DATE, 25)
    benchmark = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="TAIEX",
        name="TAIEX",
        instrument_type="index",
        status="active",
    )
    db.add(benchmark)
    instruments = {
        symbol: row
        for symbol, row in zip(
            growth, _add_instruments(db, [("TWSE", s) for s in growth])
        )
    }
    db.flush()
    for index, trading_date in enumerate(dates):
        level = 100 + index * 0.1
        db.add(
            MarketBar(
                instrument_id=benchmark.id,
                trading_date=trading_date,
                open=level,
                high=level,
                low=level,
                close=level,
                adj_close=level,
                volume=0,
                turnover=0,
                source="fixture",
            )
        )
        for symbol, rate in growth.items():
            close = 50 * (1 + rate) ** index
            volume = 1000 + 10 * index * (1 + int(symbol[-1]))
            db.add(
                MarketBar(
                    instrument_id=instruments[symbol].id,
                    trading_date=trading_date,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adj_close=close,
                    volume=volume,
                    turnover=close * volume,
                    turnover_status="available",
                    source="fixture",
                )
            )
            db.add(
                ChipSnapshot(
                    instrument_id=instruments[symbol].id,
                    trading_date=trading_date,
                    foreign_buy=10 * int(symbol[-1]),
                    trust_buy=5,
                    dealer_buy=1,
                    margin_balance=1000,
                    margin_change=0,
                    source="fixture",
                )
            )
    for row in instruments.values():
        for trading_date in dates[-3:]:
            db.add(
                TechnicalFeature(
                    instrument_id=row.id,
                    trading_date=trading_date,
                    features_json={},
                    source="fixture",
                )
            )
    db.flush()
    return instruments, dates


def _group(db, group_id, group_type, members, start, **fields):
    group = ThemeGroup(
        id=group_id,
        name=fields.pop("name", group_id),
        group_type=group_type,
        active=fields.pop("active", True),
        **fields,
    )
    db.add(group)
    db.flush()
    for instrument in members:
        db.add(
            GroupMembership(
                group_id=group_id,
                instrument_id=instrument.id,
                valid_from=start,
                source="fixture",
            )
        )
    db.flush()


def _scores(db):
    return {
        row.group_id: row
        for row in db.scalars(
            select(GroupDailyScore).where(GroupDailyScore.trading_date == SCORE_DATE)
        ).all()
    }


def _board_fixture(db):
    growth = {
        f"S{i}": rate
        for i, rate in enumerate(
            [0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009]
        )
    }
    stocks, dates = _market_fixture(db, growth)
    s = [stocks[f"S{i}"] for i in range(9)]
    _group(db, "ind-low", "official_industry", s[0:3], dates[0])
    _group(db, "ind-high", "official_industry", s[6:9], dates[0])
    _group(
        db,
        "theme-mid",
        "theme",
        [s[3], s[4], s[5]],
        dates[0],
        display_name_zh="中題材",
        name_status="verified",
    )
    _group(
        db,
        "theme-top",
        "theme",
        [s[5], s[7], s[8]],
        dates[0],
        display_name_zh="頂題材",
        name_status="verified",
    )
    _group(
        db,
        "theme-small",
        "theme",
        s[0:2],
        dates[0],
        display_name_zh="小題材",
        name_status="verified",
    )
    _group(db, "new-listings", "daily_hot_group", s[1:4], dates[0])
    _group(
        db,
        "candidate-x",
        THEME_CANDIDATE_GROUP_TYPE,
        s[6:9],
        dates[0],
        active=False,
        display_name_zh="候選",
        name_status=THEME_CANDIDATE_NAME_STATUS,
    )
    return s, dates


def test_industry_and_theme_boards_rank_and_percentile_independently(factory):
    with factory() as db:
        stocks, dates = _board_fixture(db)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        rows = _scores(db)
        board = {group_id: row.details_json["board"] for group_id, row in rows.items()}
        assert board == {
            "ind-low": "industry",
            "ind-high": "industry",
            "theme-mid": "theme",
            "theme-top": "theme",
            "theme-small": "theme",
            "new-listings": "other",
        }
        assert (rows["ind-high"].rank, rows["ind-low"].rank) == (1, 2)
        assert (rows["theme-top"].rank, rows["theme-mid"].rank) == (1, 2)
        assert rows["new-listings"].rank == 1
        # Fewer than 3 members never enters a board.
        assert (
            rows["theme-small"].eligible_members,
            rows["theme-small"].score,
            rows["theme-small"].rank,
        ) == (2, None, None)
        assert rows["theme-small"].data_quality == "insufficient_members"
        assert rows["theme-top"].details_json["member_count"] == 3
        # Theme percentiles use theme peers only (the unranked small theme is
        # still a percentile peer, as before): small < mid < top.
        assert (
            rows["theme-mid"].details_json["normalized_values"]["relative_return"]
            == 0.5
        )
        assert (
            rows["theme-top"].details_json["normalized_values"]["relative_return"]
            == 1.0
        )
        assert (
            rows["ind-low"].details_json["normalized_values"]["relative_return"] == 0.0
        )
        theme_snapshot = {
            group_id: (
                row.score,
                row.rank,
                row.volume_strength,
                row.institutional_flow,
                row.details_json["normalized_values"],
            )
            for group_id, row in rows.items()
            if board[group_id] == "theme"
        }

        # A new, strongest industry changes the industry board but not the theme board.
        _group(db, "ind-new", "official_industry", stocks[6:9], dates[0])
        db.get(ThemeGroup, "ind-low").active = False
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        after = _scores(db)
        assert {
            group_id: (
                row.score,
                row.rank,
                row.volume_strength,
                row.institutional_flow,
                row.details_json["normalized_values"],
            )
            for group_id, row in after.items()
            if board.get(group_id) == "theme"
        } == theme_snapshot
        assert {after["ind-high"].rank, after["ind-new"].rank} == {1, 2}


def test_member_count_counts_effective_members_and_eligible_needs_full_history(
    factory,
):
    with factory() as db:
        stocks, dates = _board_fixture(db)
        # S9 is a member with only 5 bars: counted, but not eligible.
        short = _add_instruments(db, [("TWSE", "S9")])[0]
        for trading_date in dates[-5:]:
            db.add(
                MarketBar(
                    instrument_id=short.id,
                    trading_date=trading_date,
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    adj_close=10,
                    volume=1000,
                    turnover=10000,
                    turnover_status="available",
                    source="fixture",
                )
            )
        # An inactive instrument and an expired membership are not counted.
        gone = _add_instruments(db, [("TWSE", "S10")])[0]
        gone.status = "delisted"
        _group(db, "theme-four", "theme", [*stocks[0:3], short, gone], dates[0])
        db.add(
            GroupMembership(
                group_id="theme-four",
                instrument_id=stocks[4].id,
                valid_from=dates[0],
                valid_to=dates[-2],
                source="fixture",
            )
        )
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        row = _scores(db)["theme-four"]
        assert row.details_json["member_count"] == 4
        assert row.eligible_members == 3
        # hot_group_v1 1.1.0: flow coverage is measured against eligible members.
        assert row.details_json["institutional_flow_coverage"]["eligible"] == 3
        assert row.details_json["institutional_flow_coverage"]["member_count"] == 4


def test_theme_candidates_are_never_scored_or_ranked(factory):
    with factory() as db:
        _board_fixture(db)
        # Even if a candidate were activated by mistake it must not be scored.
        db.get(ThemeGroup, "candidate-x").active = True
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        assert "candidate-x" not in _scores(db)


def test_missing_catalyst_keeps_v1_partial_policy_on_both_boards(factory):
    with factory() as db:
        _board_fixture(db)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        for group_id in ("ind-high", "theme-top"):
            row = _scores(db)[group_id]
            normalized = row.details_json["normalized_values"]
            # No verified official event: catalyst is null (unsupported), not 0.
            assert row.catalyst is None and normalized["catalyst"] is None
            assert row.data_quality == "partial"
            four = sum(
                GROUP_SCORE_WEIGHTS[key] * normalized[key]
                for key in (
                    "relative_return",
                    "breadth",
                    "volume_strength",
                    "institutional_flow",
                )
            )
            assert row.score == round(four / 0.90 * 100, 2)


def test_strategy_group_input_ignores_theme_scores(factory):
    with factory() as db:
        stocks, _dates = _board_fixture(db)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        rows = _scores(db)
        # S5 is in theme-mid and theme-top (both scored) and no industry: no strategy group.
        assert rows["theme-top"].score is not None
        assert pipeline._best_group_for_signal(db, stocks[5].id, SCORE_DATE) is None
        # S8 is in ind-high and theme-top: the industry is used.
        assert (
            pipeline._best_group_for_signal(db, stocks[8].id, SCORE_DATE).group_id
            == "ind-high"
        )


# AC-4: API


@pytest.fixture
def api_client(factory, monkeypatch):
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app, base_url=LOCAL_API) as client:
        yield client
    app.dependency_overrides.pop(api_module.get_db, None)


def _scored_api_fixture(factory, *, run=True):
    with factory() as db:
        stocks, dates = _board_fixture(db)
        db.get(
            ThemeGroup, "theme-top"
        ).source = "theme_table:backend/data/themes/themes_v1.json"
        membership = db.scalar(
            select(GroupMembership).where(
                GroupMembership.group_id == "theme-top",
                GroupMembership.instrument_id == stocks[5].id,
            )
        )
        membership.source = json.dumps(
            {
                "kind": "theme_table",
                "url": "https://example.com/s5",
                "relation": "supply_chain",
                "relevance": "medium",
                "theme_version": "themes_v1:2026.09.01",
            }
        )
        for trading_date in dates[-3:]:
            pipeline._calculate_group_scores(db, trading_date)
        if run:
            db.add(
                IngestionRun(
                    run_type="collect",
                    source="official",
                    run_date=SCORE_DATE,
                    status="success",
                    records=1,
                    data_as_of=SCORE_DATE.isoformat(),
                )
            )
        db.commit()
        return stocks, dates


def test_api_board_switch_top_n_quality_and_dates(factory, api_client):
    _stocks, dates = _scored_api_fixture(factory)
    industry = api_client.get("/api/themes", params={"board": "industry"}).json()
    theme = api_client.get("/api/themes", params={"board": "theme", "limit": 1}).json()
    older = api_client.get(
        "/api/themes", params={"board": "theme", "date": dates[-2].isoformat()}
    ).json()

    assert [item["theme_id"] for item in industry["items"]] == ["ind-high", "ind-low"]
    assert industry["meta"]["trading_date"] == SCORE_DATE.isoformat()
    assert industry["meta"]["data_as_of"] == SCORE_DATE.isoformat()
    assert {item["board"] for item in industry["items"]} == {"industry"}
    assert [item["theme_id"] for item in theme["items"]] == ["theme-top"]
    assert theme["meta"]["total"] == 2 and theme["meta"]["limit"] == 1
    top = theme["items"][0]
    assert (
        top["rank"] == 1
        and top["quality"] == "partial"
        and top["display_name"] == "頂題材"
    )
    assert set(top["components"]) == {
        "relative_return",
        "breadth",
        "volume_strength",
        "institutional_flow",
        "catalyst",
    }
    assert (
        top["components"]["catalyst"] is None
        and top["components"]["relative_return"] == 1.0
    )
    assert (top["eligible_members"], top["member_count"], top["trading_date"]) == (
        3,
        3,
        SCORE_DATE.isoformat(),
    )
    assert (
        older["meta"]["trading_date"] == dates[-2].isoformat()
        and len(older["items"]) == 2
    )
    # Without board the existing product listing is unchanged.
    legacy = api_client.get("/api/themes", params={"only_qualified": "false"}).json()
    # Legacy listing: same fields, industries before themes, then the rest.
    prefixes = [item["theme_id"].split("-")[0] for item in legacy["items"]]
    assert prefixes == ["ind", "ind", "theme", "theme", "theme", "new"]
    assert legacy["meta"]["sort"].startswith("qualified desc, board")
    assert "page" in legacy["meta"] and "board" not in legacy["meta"]


def test_api_board_without_scores_or_ranked_groups(factory, api_client):
    with factory() as db:
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=SCORE_DATE,
                status="success",
                records=1,
                data_as_of=SCORE_DATE.isoformat(),
            )
        )
        db.commit()
    body = api_client.get("/api/themes", params={"board": "industry"}).json()
    assert body["meta"]["empty_reason"] == "no_board_scores"
    with factory() as db:
        _group(db, "lonely", "official_industry", [], SCORE_DATE)
        db.add(
            GroupDailyScore(
                group_id="lonely",
                trading_date=SCORE_DATE,
                eligible_members=1,
                data_quality="insufficient_members",
                details_json={"board": "industry", "benchmark": "TAIEX"},
            )
        )
        db.commit()
    body = api_client.get("/api/themes", params={"board": "industry"}).json()
    assert body["items"] == [] and body["meta"]["empty_reason"] == "no_ranked_groups"
    assert body["meta"]["trading_date"] == SCORE_DATE.isoformat()


def test_api_board_empty_states_explain_why(factory, api_client):
    # Scores exist but no successful official run: fail closed, with or without a date.
    _scored_api_fixture(factory, run=False)
    for params in (
        {"board": "theme"},
        {"board": "theme", "date": SCORE_DATE.isoformat()},
    ):
        no_run = api_client.get("/api/themes", params=params).json()
        assert no_run["items"] == []
        assert no_run["meta"]["empty_reason"] == "no_official_run"
    with factory() as db:
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=SCORE_DATE,
                status="success",
                records=1,
                data_as_of=SCORE_DATE.isoformat(),
            )
        )
        db.commit()
    assert (
        len(api_client.get("/api/themes", params={"board": "theme"}).json()["items"])
        == 2
    )
    holiday = api_client.get(
        "/api/themes", params={"board": "theme", "date": "2026-09-05"}
    ).json()
    assert (
        holiday["items"] == []
        and holiday["meta"]["empty_reason"] == "no_scores_for_date"
    )
    assert holiday["meta"]["empty_message"]
    assert api_client.get("/api/themes", params={"board": "etf"}).status_code == 422


def test_api_theme_detail_trend_and_members_with_evidence(factory, api_client):
    stocks, dates = _scored_api_fixture(factory)
    body = api_client.get("/api/themes/theme-top").json()
    assert body["board"] == "theme"
    assert [point["trading_date"] for point in body["trend"]] == [
        d.isoformat() for d in dates[-3:]
    ]
    assert all(
        point["rank"] is not None and point["quality"] == "partial"
        for point in body["trend"]
    )
    assert body["members_as_of"] == SCORE_DATE.isoformat()
    members = {item["symbol"]: item for item in body["members"]}
    assert set(members) == {"S5", "S7", "S8"}
    assert members["S5"]["theme_evidence"] == {
        "url": "https://example.com/s5",
        "relation": "supply_chain",
        "relevance": "medium",
        "theme_version": "themes_v1:2026.09.01",
    }
    assert members["S7"]["theme_evidence"] is None
    paged = api_client.get("/api/themes/theme-top/members").json()
    assert {
        item["symbol"]: item["theme_evidence"] is not None for item in paged["items"]
    } == {"S5": True, "S7": False, "S8": False}
    assert (body["members_total"], body["members_truncated"]) == (3, False)
    assert body["members_endpoint"] == "/api/themes/theme-top/members"
    industry = api_client.get("/api/themes/ind-high").json()
    assert industry["board"] == "industry" and len(industry["trend"]) == 3


def test_api_theme_detail_inlines_at_most_one_page_of_members(
    factory, api_client, monkeypatch
):
    _scored_api_fixture(factory)
    monkeypatch.setattr(api_module, "MAX_PAGE_SIZE", 2)
    body = api_client.get("/api/themes/theme-top").json()
    assert len(body["members"]) == 2
    assert (body["members_total"], body["members_truncated"]) == (3, True)
    full = api_client.get("/api/themes/theme-top/members", params={"page_size": 3})
    assert full.json()["meta"]["total"] == 3


# #216 AC-3: news theme suggestions never enter a board


def _ranked(body):
    return [
        (
            item.get("theme_id") or item.get("group_id"),
            item.get("display_name") or item.get("name"),
            item.get("rank"),
            item.get("score"),
        )
        for item in body["items"]
    ]


def test_news_theme_suggestions_are_never_scored_ranked_or_grouped(
    factory, api_client
):
    _stocks, dates = _scored_api_fixture(factory)
    endpoints = [
        ("/api/themes", {"board": "industry"}),
        ("/api/themes", {"board": "theme"}),
        ("/api/themes", {"only_qualified": False}),
        ("/api/groups", {}),
    ]
    before = [_ranked(api_client.get(path, params=params).json()) for path, params in endpoints]
    with factory() as db:

        def group_state():
            return (
                [(row.id, row.group_type, row.active) for row in db.scalars(select(ThemeGroup).order_by(ThemeGroup.id))],
                _memberships(db),
                sorted((row.group_id, row.trading_date, row.rank, row.score) for row in db.scalars(select(GroupDailyScore))),
            )

        groups_before = group_state()
        for index, names in enumerate((["新題材甲", "頂題材"], ["新題材甲"])):
            news = NewsItem(
                canonical_key=f"news:ac3:{index}",
                source_name="鉅亨網",
                title=f"題材新聞{index}",
                published_at=datetime(2026, 9, 4, 1, 0),
                collected_at=datetime(2026, 9, 4, 1, 0),
                status="active",
            )
            db.add(news)
            db.flush()
            db.add(
                NewsLlmResult(
                    news_item_id=news.id,
                    prompt_version="news_v1",
                    llm_model="claude-haiku-5-5",
                    llm_input_hash="0" * 64,
                    llm_status="done",
                    ai_unsupported=False,
                    ai_symbol_candidates_json=[],
                    ai_theme_candidates_json=[{"theme": name, "reason": "理由"} for name in names],
                )
            )
        db.commit()
        result = refresh_theme_suggestions(db)
        assert (result["records"], result["new_themes"], result["matched_existing"]) == (2, 1, 1)
        # Rescoring after the refresh sees the same groups and writes the same boards.
        for trading_date in dates[-3:]:
            pipeline._calculate_group_scores(db, trading_date)
        db.commit()
        assert group_state() == groups_before

    after = [_ranked(api_client.get(path, params=params).json()) for path, params in endpoints]
    assert after == before
    assert "新題材甲" not in json.dumps(after, ensure_ascii=False)
    listed = api_client.get("/api/theme-suggestions").json()
    assert [item["display_name"] for item in listed["items"]] == ["新題材甲"]
    assert listed["items"][0]["status"] == "pending_verification"
    matched = api_client.get("/api/theme-suggestions", params={"include_matched": True}).json()
    assert {item["display_name"]: (item["matched_group"] or {}).get("group_id") for item in matched["items"]} == {
        "新題材甲": None,
        "頂題材": "theme-top",
    }
