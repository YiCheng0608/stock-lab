from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    Event,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    PortfolioPosition,
    RawPayload,
    Signal,
    SignalEvaluation,
    StrategyVersion,
    ThemeGroup,
)
from app.news import _parse_datetime, sync_news_from_events
from app.decision import build_action_summaries
from app.main import app
from app.taxonomy import canonical_group_id


@pytest.fixture
def product_api(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'product.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    yield factory
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


def _add_base_fixture(db):
    as_of = date(2026, 9, 8)
    run = IngestionRun(
        run_type="collect",
        source="official",
        run_date=as_of,
        status="success",
        records=100,
        data_as_of=as_of.isoformat(),
        request_key="official-fixture-20260908",
    )
    alpha = Instrument(market="TW", exchange="TWSE", symbol="AAA", name="Alpha", instrument_type="stock", industry="24", status="active")
    beta = Instrument(market="TW", exchange="TPEx", symbol="BBB", name="Beta", instrument_type="stock", industry="24", status="active")
    etf = Instrument(market="TW", exchange="TWSE", symbol="00679B", name="Bond fund", instrument_type="etf", etf_category="bond", status="active")
    complete = ThemeGroup(
        id="theme-complete",
        name="Industry · Semiconductor",
        display_name_zh="半導體",
        display_description_zh="官方共同產業族群",
        display_category="股票族群",
        name_status="official",
        active=True,
    )
    incomplete = ThemeGroup(id="theme-incomplete", name="Incomplete", active=True)
    db.add_all([run, alpha, beta, etf, complete, incomplete])
    db.flush()
    db.add_all(
        [
            GroupMembership(group_id=complete.id, instrument_id=alpha.id, valid_from=date(2020, 1, 1), source="official"),
            GroupMembership(group_id=complete.id, instrument_id=beta.id, valid_from=date(2020, 1, 1), source="official"),
            GroupMembership(group_id=complete.id, instrument_id=etf.id, valid_from=date(2020, 1, 1), source="official"),
            GroupDailyScore(
                group_id=complete.id,
                trading_date=as_of,
                relative_return_20d=0.12,
                breadth=0.67,
                volume_strength=0.8,
                institutional_flow=0.05,
                score=90,
                rank=1,
                eligible_members=3,
                data_quality="complete",
                details_json={"benchmark": "TAIEX", "leaderboard": "equity", "candidate_symbols": ["AAA", "BBB"]},
            ),
            GroupDailyScore(
                group_id=incomplete.id,
                trading_date=as_of,
                score=100,
                rank=1,
                eligible_members=2,
                data_quality="insufficient_members",
                details_json={"benchmark": "TAIEX", "leaderboard": "equity"},
            ),
            MarketBar(
                instrument_id=alpha.id,
                trading_date=as_of,
                open=100,
                high=105,
                low=98,
                close=103,
                adj_close=103,
                volume=1000,
                turnover=103000,
                source="official",
            ),
        ]
    )
    db.commit()
    return as_of, alpha, beta, etf


def _add_decision_history(db, alpha, as_of, *, extra_instrument=None):
    """Add explicit fixture sessions needed to exercise action selection.

    The product decision layer deliberately requires verified TAIEX sessions.
    ``official-fixture`` is accepted only by the test coverage helper and is
    never an official product data source.
    """

    taiex = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="TAIEX",
        name="TAIEX",
        instrument_type="index",
        status="active",
    )
    db.add(taiex)
    if extra_instrument is not None:
        db.add(extra_instrument)
    db.flush()
    instruments = [alpha]
    if extra_instrument is not None:
        instruments.append(extra_instrument)
    for index in range(60):
        trading_date = as_of - timedelta(days=index)
        db.add(
            MarketBar(
                instrument_id=taiex.id,
                trading_date=trading_date,
                open=100,
                high=101,
                low=99,
                close=100,
                adj_close=100,
                volume=1000,
                turnover=100000,
                source="official-fixture",
            )
        )
        for instrument in instruments:
            if instrument.id == alpha.id and index == 0:
                # _add_base_fixture already supplies Alpha's latest bar.
                continue
            close = 103 if instrument.id == alpha.id else 50
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=trading_date,
                    open=close,
                    high=close * 1.02,
                    low=close * 0.98,
                    close=close,
                    adj_close=close,
                    volume=1000,
                    turnover=close * 1000,
                    source="official-fixture",
                )
            )
    for index in range(5):
        db.add(
            ChipSnapshot(
                instrument_id=alpha.id,
                trading_date=as_of - timedelta(days=index),
                foreign_buy=10,
                trust_buy=5,
                dealer_buy=2,
                margin_balance=100,
                margin_change=1,
                source="official-fixture",
            )
        )


def _add_signal_pair(
    db,
    instrument,
    as_of,
    *,
    breakout_status="conditional",
    breakout_quality="complete",
    pullback_status="observation",
    pullback_quality="complete",
    breakout_levels=True,
):
    breakout = StrategyVersion(
        name="breakout_v1",
        version="1.0.0",
        kind="technical",
        config_json={},
        canonical_config_snapshot={},
    )
    pullback = StrategyVersion(
        name="pullback_v1",
        version="1.0.0",
        kind="technical",
        config_json={},
        canonical_config_snapshot={},
    )
    db.add_all([breakout, pullback])
    db.flush()
    evidence = {
        "inputs": {
            "group_excess_return_20d": 0.1,
            "institutional_flow_to_turnover_ratio_5d": 0.01,
            "margin_balance_change_ratio_5d": 0.02,
        }
    }
    db.add_all(
        [
            Signal(
                signal_key=f"fixture-{instrument.symbol}-breakout",
                signal_date=as_of,
                instrument_id=instrument.id,
                strategy_version_id=breakout.id,
                status=breakout_status,
                data_quality=breakout_quality,
                entry_type="conditional",
                breakout_price=21.05 if breakout_levels else None,
                invalid_price=20.47 if breakout_levels else None,
                target_1=21.98 if breakout_levels else None,
                target_2=22.80 if breakout_levels else None,
                rationale="breakout fixture",
                rule_evidence_json=evidence,
            ),
            Signal(
                signal_key=f"fixture-{instrument.symbol}-pullback",
                signal_date=as_of,
                instrument_id=instrument.id,
                strategy_version_id=pullback.id,
                status=pullback_status,
                data_quality=pullback_quality,
                entry_type="observation",
                rationale="pullback fixture",
                rule_evidence_json=evidence,
            ),
        ]
    )


def test_news_order_dedupe_and_official_feed_provenance(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        raw = RawPayload(
            source="twse",
            endpoint="https://www.twse.com.tw/rwd/zh/fund/T86",
            sha256="a" * 64,
            data_as_of=as_of.isoformat(),
        )
        db.add(raw)
        db.flush()
        db.add_all(
            [
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=1),
                    event_type="material_information",
                    title="Older official notice",
                    description="Official summary",
                    source="mops_material_information",
                    endpoint="https://mops.twse.com.tw/mops/web/t05st01",
                    raw_payload_id=raw.id,
                    data_as_of=(as_of - timedelta(days=1)).isoformat(),
                    collected_at=datetime(2026, 9, 8, 10, 0),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of,
                    event_type="suspension",
                    title="New official notice",
                    source="tpex_suspension_history",
                    endpoint="https://www.tpex.org.tw/openapi/v1/tpex_spendi_history",
                    raw_payload_id=raw.id,
                    data_as_of=as_of.isoformat(),
                    collected_at=datetime(2026, 9, 8, 11, 0),
                ),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        first = client.get("/api/news?limit=1")
        first_again = client.get("/api/news?limit=10")
        next_page = client.get(f"/api/news?limit=1&cursor={first.json()['meta']['next_cursor']}")

    assert first.status_code == 200
    assert first.json()["items"][0]["title"] == "New official notice"
    assert first.json()["items"][0]["source"]["url_kind"] == "feed"
    assert first.json()["items"][0]["provenance"]["raw_payload_id"] == 1
    assert len(first_again.json()["items"]) == 2
    assert next_page.json()["items"][0]["title"] == "Older official notice"

    with product_api() as db:
        assert db.scalar(select(func_count_news())) == 2


def test_news_projection_persists_once_and_hides_unverified_theme(product_api):
    with product_api() as db:
        as_of, _alpha, _beta, _etf = _add_base_fixture(db)
        gamma = Instrument(market="TW", exchange="TWSE", symbol="GAM", name="Gamma", instrument_type="stock", status="active")
        pending = ThemeGroup(id="theme-pending", name="Industry · Shipping", active=True, name_status="pending")
        db.add_all([gamma, pending])
        db.flush()
        db.add(GroupMembership(group_id=pending.id, instrument_id=gamma.id, valid_from=date(2020, 1, 1), source="official"))
        long_description = "官方公告內容 " * 40
        db.add(
            Event(
                instrument_id=gamma.id,
                event_date=as_of,
                event_type="material_information",
                title="Gamma official notice",
                description=long_description,
                source="mops_material_information",
                endpoint="https://mops.twse.com.tw/mops/web/t05st01",
                collected_at=datetime(2026, 9, 8, 12, 0),
            )
        )
        db.commit()

    with TestClient(app) as client:
        first = client.get("/api/news?limit=10")
    assert first.status_code == 200
    item = next(row for row in first.json()["items"] if row["title"] == "Gamma official notice")
    assert item["themes"] == []
    assert item["instruments"] == [{"exchange": "TWSE", "symbol": "GAM", "name": "Gamma"}]
    assert item["summary"] == long_description
    assert item["summary_preview"]
    assert len(item["summary_preview"]) <= 120

    with product_api() as db:
        projected = db.scalar(select(NewsItem).where(NewsItem.title == "Gamma official notice"))
        assert projected is not None
        projected.status = "retracted"
        db.commit()

    with TestClient(app) as client:
        second = client.get("/api/news?limit=10")
    assert second.status_code == 200
    assert all(row["title"] != "Gamma official notice" for row in second.json()["items"])
    with product_api() as db:
        assert db.scalar(select(func_count_news())) == 1
        assert db.scalar(select(NewsItem.status).where(NewsItem.title == "Gamma official notice")) == "retracted"

        # A later reconciliation state is also terminal.  Refreshing the
        # projection must never make an operator-suppressed item active again.
        projected = db.scalar(select(NewsItem).where(NewsItem.title == "Gamma official notice"))
        assert projected is not None
        projected.status = "superseded"
        db.commit()

    with TestClient(app) as client:
        third = client.get("/api/news?limit=10")
    assert third.status_code == 200
    assert all(row["title"] != "Gamma official notice" for row in third.json()["items"])
    with product_api() as db:
        assert db.scalar(select(NewsItem.status).where(NewsItem.title == "Gamma official notice")) == "superseded"


def test_dashboard_news_and_group_rows_use_compact_projections(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add(
            Event(
                instrument_id=alpha.id,
                event_date=as_of,
                event_type="announcement",
                title="Compact dashboard notice",
                description="公告正文 " * 200,
                source="mops_material_information",
                endpoint="https://mops.twse.com.tw/mops/web/t05st01",
                collected_at=datetime(2026, 9, 8, 12, 0),
            )
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200
    item = next(row for row in response.json()["news"] if row["title"] == "Compact dashboard notice")
    assert "summary" not in item
    assert "provenance" not in item
    assert len(item["summary_preview"]) <= 120
    assert response.json()["groups"]
    assert all("methodology" not in row for row in response.json()["groups"])


def test_official_cross_exchange_taxonomy_conflict_is_hidden_from_theme_product_list(product_api):
    """A stale official-looking mixed group must not become a product theme."""

    with product_api() as db:
        as_of, _alpha, _beta, _etf = _add_base_fixture(db)
        instrument = Instrument(
            market="TW",
            exchange="TPEx",
            symbol="4105",
            name="東洋",
            industry="22",  # TPEx 22 is biotechnology, not TWSE shipping.
            instrument_type="stock",
            status="active",
        )
        group = ThemeGroup(
            id=canonical_group_id("industry", "Shipping"),
            name="Industry · Shipping",
            group_type="official_industry",
            source="TWSE/TPEx official OpenAPI",
            display_name_zh="航運",
            display_description_zh="官方共同產業族群",
            display_category="股票族群",
            name_status="official",
            active=True,
        )
        db.add_all([instrument, group])
        db.flush()
        db.add(
            GroupMembership(
                group_id=group.id,
                instrument_id=instrument.id,
                valid_from=date(2020, 1, 1),
                source="TWSE/TPEx official OpenAPI; exchange=TPEx",
            )
        )
        db.add(
            GroupDailyScore(
                group_id=group.id,
                trading_date=as_of,
                score=90,
                rank=1,
                eligible_members=3,
                data_quality="complete",
                details_json={"benchmark": "TAIEX", "leaderboard": "equity"},
            )
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get("/api/themes?only_qualified=false")

    assert response.status_code == 200
    assert all(item["theme_id"] != group.id for item in response.json()["items"])

def test_news_cursor_has_stable_collected_event_id_order(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add_all(
            [
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=2),
                    event_type="announcement",
                    title="same-time older event",
                    source="mops_material_information",
                    collected_at=datetime(2026, 9, 8, 10, 0),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=1),
                    event_type="announcement",
                    title="same-time newer event",
                    source="mops_material_information",
                    collected_at=datetime(2026, 9, 8, 10, 0),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of,
                    event_type="announcement",
                    title="later collected event",
                    source="mops_material_information",
                    collected_at=datetime(2026, 9, 8, 11, 0),
                ),
            ]
        )
        db.commit()

    titles: list[str] = []
    cursor = None
    with TestClient(app) as client:
        for _ in range(3):
            query = "/api/news?limit=1" + (f"&cursor={cursor}" if cursor else "")
            response = client.get(query)
            assert response.status_code == 200
            page = response.json()
            titles.extend(row["title"] for row in page["items"])
            cursor = page["meta"]["next_cursor"]
            if not cursor:
                break
    assert titles == ["later collected event", "same-time newer event", "same-time older event"]
    assert len(titles) == len(set(titles))


def test_news_order_prioritizes_published_then_event_then_collected_and_detail(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add_all(
            [
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=4),
                    event_type="announcement",
                    title="Latest collected but old event",
                    source="mops_material_information",
                    collected_at=datetime(2026, 9, 8, 23, 0),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=1),
                    event_type="announcement",
                    title="Newer event",
                    source="mops_material_information",
                    collected_at=datetime(2026, 9, 8, 8, 0),
                ),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get("/api/news?limit=1")
        first_id = response.json()["items"][0]["id"]
        detail = client.get(f"/api/news/{first_id}")
        missing = client.get("/api/news/999999")

    assert response.status_code == 200
    assert response.json()["items"][0]["title"] == "Newer event"
    assert response.json()["meta"]["sort"] == "display_time_desc,time_basis_desc,time_precision_desc,canonical_key_desc,id_desc"
    assert detail.status_code == 200
    assert detail.json()["title"] == "Newer event"
    assert detail.json()["collected_at"] is not None
    assert missing.status_code == 404


def test_news_temporal_contract_and_mops_conflict_quarantine(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add_all(
            [
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=5),
                    event_type="announcement",
                    title="Published time event",
                    source="mops_material_information",
                    details_json={"published_at": "2026-09-08T09:30:00"},
                    collected_at=datetime(2026, 9, 10, 9, 0),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=2),
                    event_type="announcement",
                    title="Event time event",
                    source="tpex_suspension_history",
                    details_json={"event_at": "2026-09-08T08:00:00"},
                    collected_at=datetime(2026, 9, 10, 9, 1),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of,
                    event_type="announcement",
                    title="Conflicting MOPS event",
                    description="公告內容所述事實日期為 2026/09/01。",
                    source="mops_material_information",
                    collected_at=datetime(2026, 9, 10, 9, 2),
                ),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        default = client.get("/api/news?limit=1")
        next_page = client.get(f"/api/news?limit=1&cursor={default.json()['meta']['next_cursor']}")
        conflicts = client.get("/api/news?limit=10&time_consistency=conflict")

    assert default.status_code == 200
    first = default.json()["items"][0]
    assert first["title"] == "Published time event"
    assert first["time_basis"] == "published"
    assert first["time_precision"] == "datetime"
    assert first["display_time"].startswith("2026-09-08T09:30:00")
    assert len(default.json()["meta"]["next_cursor"]) > 10
    assert next_page.status_code == 200
    assert next_page.json()["items"][0]["title"] == "Event time event"
    assert next_page.json()["items"][0]["time_basis"] == "event"
    assert len(conflicts.json()["items"]) == 1
    conflict = conflicts.json()["items"][0]
    assert conflict["title"] == "Conflicting MOPS event"
    assert conflict["time_consistency"] == "conflict"
    assert conflict["symbols"] == []
    assert conflict["themes"] == []

    with product_api() as db:
        quarantined = db.scalar(select(NewsItem).where(NewsItem.title == "Conflicting MOPS event"))
        assert quarantined is not None
        assert quarantined.status == "quarantined"

    with TestClient(app) as client:
        detail = client.get(f"/api/news/{conflict['id']}")
    assert detail.status_code == 200
    assert detail.json()["time_consistency"] == "conflict"


def _feed_news(canonical_key, **overrides):
    """A media feed row as worker.news_batch writes it: naive UTC DateTime columns."""

    values = {
        "canonical_key": canonical_key,
        "dedupe_cluster_id": canonical_key,
        "category": "domestic",
        "source_kind": "media",
        "source_name": "中央社",
        "title": f"feed {canonical_key}",
        "published_at": None,
        "event_at": None,
        "event_date": None,
        "display_time": None,
        "time_basis": "unverified",
        "time_precision": "none",
        "time_consistency": "verified",
        "collected_at": datetime(2026, 10, 17, 9, 0, 5),
        "status": "active",
    }
    values.update(overrides)
    return NewsItem(**values)


def _news_by_title(client, titles):
    """Return {title: (list item, detail)} so one assertion covers both endpoints."""

    listing = client.get("/api/news?limit=20")
    assert listing.status_code == 200
    items = {item["title"]: item for item in listing.json()["items"]}
    result = {}
    for title in titles:
        detail = client.get(f"/api/news/{items[title]['id']}")
        assert detail.status_code == 200
        result[title] = (items[title], detail.json())
    return result


def test_feed_news_api_exposes_aware_utc_and_known_published_at(product_api):
    published = datetime(2026, 10, 17, 8, 48, 10)
    with product_api() as db:
        db.add_all(
            [
                _feed_news(
                    "published",
                    title="feed published",
                    published_at=published,
                    display_time=published,
                    time_basis="published",
                    time_precision="datetime",
                ),
                _feed_news(
                    "date-only",
                    title="feed date only",
                    event_date=date(2026, 10, 16),
                    display_time=datetime(2026, 10, 16),
                    time_basis="event_date",
                    time_precision="date",
                ),
                _feed_news("no-time", title="feed no time"),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        rows = _news_by_title(client, ["feed published", "feed date only", "feed no time"])

    for payload in rows["feed published"]:
        roles = payload["product_time"]["roles"]
        assert roles["published_at"]["status"] == "known"
        assert roles["published_at"]["precision"] == "instant"
        assert roles["published_at"]["value"] == "2026-10-17T08:48:10+00:00"
        assert roles["published_at"]["value"].endswith("+00:00")
        assert roles["collected_at"]["status"] == "known"
        assert roles["collected_at"]["value"] == "2026-10-17T09:00:05+00:00"
        # The top-level fields state the same instant as product_time.
        assert payload["published_at"] == roles["published_at"]["value"]
        assert payload["display_time"] == roles["published_at"]["value"]
        assert payload["collected_at"] == roles["collected_at"]["value"]
        assert payload["event_at"] is None
        assert payload["time_basis"] == "published" and payload["time_precision"] == "datetime"

    # Without published_at the item keeps the event／date rules: no instant is invented.
    for payload in rows["feed date only"]:
        roles = payload["product_time"]["roles"]
        assert roles["published_at"]["status"] == "unknown"
        assert roles["event_at"]["status"] == "unknown"
        assert roles["event_date"]["status"] == "known"
        assert roles["event_date"]["precision"] == "date"
        assert roles["event_date"]["value"] == "2026-10-16"
        assert payload["published_at"] is None
        assert payload["event_date"] == "2026-10-16"
        assert payload["display_time"] == "2026-10-16T00:00:00"

    for payload in rows["feed no time"]:
        roles = payload["product_time"]["roles"]
        assert roles["published_at"]["status"] == "unknown"
        assert roles["event_date"]["status"] == "unknown"
        assert payload["published_at"] is None and payload["event_at"] is None
        # The row has no source time, so the sort view falls back to the collection instant.
        assert payload["time_basis"] == "collected" and payload["time_precision"] == "datetime"
        assert payload["display_time"] == "2026-10-17T09:00:05+00:00"
        assert payload["collected_at"] == "2026-10-17T09:00:05+00:00"


def test_official_news_date_only_stays_naive_and_event_time_becomes_aware(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add_all(
            [
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of,
                    event_type="announcement",
                    title="Official date only",
                    source="mops_material_information",
                    collected_at=datetime(2026, 9, 8, 8, 0),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=1),
                    event_type="announcement",
                    title="Official with published time",
                    source="mops_material_information",
                    details_json={"published_at": "2026-09-07T09:30:00"},
                    collected_at=datetime(2026, 9, 8, 8, 1),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of - timedelta(days=2),
                    event_type="announcement",
                    title="Official with event time",
                    source="tpex_suspension_history",
                    details_json={"event_at": "2026-09-06T08:00:00"},
                    collected_at=datetime(2026, 9, 8, 8, 2),
                ),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        rows = _news_by_title(
            client, ["Official date only", "Official with published time", "Official with event time"]
        )

    for payload in rows["Official date only"]:
        roles = payload["product_time"]["roles"]
        assert payload["time_basis"] == "event_date" and payload["time_precision"] == "date"
        assert payload["display_time"] == "2026-09-08T00:00:00"
        assert payload["published_at"] is None and payload["event_at"] is None
        assert payload["event_date"] == "2026-09-08"
        assert roles["event_date"]["status"] == "known" and roles["event_date"]["precision"] == "date"
        assert roles["event_date"]["value"] == "2026-09-08"
        assert roles["published_at"]["status"] == "unknown"
        assert roles["event_at"]["status"] == "unknown"

    for payload in rows["Official with published time"]:
        roles = payload["product_time"]["roles"]
        assert payload["published_at"] == "2026-09-07T09:30:00+00:00"
        assert payload["display_time"] == "2026-09-07T09:30:00+00:00"
        assert roles["published_at"]["status"] == "known"
        assert roles["published_at"]["value"] == "2026-09-07T09:30:00+00:00"
        assert roles["event_date"]["value"] == "2026-09-07"

    for payload in rows["Official with event time"]:
        roles = payload["product_time"]["roles"]
        assert payload["event_at"] == "2026-09-06T08:00:00+00:00"
        assert payload["display_time"] == "2026-09-06T08:00:00+00:00"
        assert roles["event_at"]["status"] == "known"
        assert roles["event_at"]["value"] == "2026-09-06T08:00:00+00:00"
        assert roles["published_at"]["status"] == "unknown"


def test_official_news_offset_times_are_converted_to_utc(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add_all(
            [
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of,
                    event_type="announcement",
                    title="Published +08:00",
                    source="mops_material_information",
                    details_json={
                        "published_at": "2026-09-07T09:30:00+08:00",
                        "event_at": "2026-09-07T09:00:00+08:00",
                    },
                    collected_at=datetime(2026, 9, 8, 8, 0),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of,
                    event_type="announcement",
                    title="Event only -05:00",
                    source="tpex_suspension_history",
                    details_json={"event_at": "2026-09-07T20:00:00-05:00"},
                    collected_at=datetime(2026, 9, 8, 8, 1),
                ),
                Event(
                    instrument_id=alpha.id,
                    event_date=as_of,
                    event_type="announcement",
                    title="Published Z",
                    source="mops_material_information",
                    details_json={"published_at": "2026-09-07T09:30:00Z"},
                    collected_at=datetime(2026, 9, 8, 8, 2),
                ),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        rows = _news_by_title(client, ["Published +08:00", "Event only -05:00", "Published Z"])

    # 09:30 in Taipei is 01:30 UTC; the same instant, not the same clock reading.
    for payload in rows["Published +08:00"]:
        roles = payload["product_time"]["roles"]
        assert payload["published_at"] == "2026-09-07T01:30:00+00:00"
        assert payload["event_at"] == "2026-09-07T01:00:00+00:00"
        assert payload["display_time"] == "2026-09-07T01:30:00+00:00"
        assert payload["time_basis"] == "published" and payload["time_precision"] == "datetime"
        assert roles["published_at"]["status"] == "known"
        assert roles["published_at"]["value"] == "2026-09-07T01:30:00+00:00"

    # A negative offset moves the instant forward, across the UTC day boundary.
    for payload in rows["Event only -05:00"]:
        roles = payload["product_time"]["roles"]
        assert payload["published_at"] is None
        assert payload["event_at"] == "2026-09-08T01:00:00+00:00"
        assert payload["display_time"] == "2026-09-08T01:00:00+00:00"
        assert payload["time_basis"] == "event" and payload["time_precision"] == "datetime"
        assert roles["event_at"]["value"] == "2026-09-08T01:00:00+00:00"

    for payload in rows["Published Z"]:
        assert payload["published_at"] == "2026-09-07T09:30:00+00:00"

    with product_api() as db:
        stored = {item.title: item for item in db.scalars(select(NewsItem))}
    # The database keeps naive UTC, the same convention as the media feed rows.
    assert stored["Published +08:00"].published_at == datetime(2026, 9, 7, 1, 30)
    assert stored["Published +08:00"].event_at == datetime(2026, 9, 7, 1, 0)
    assert stored["Published +08:00"].published_at.tzinfo is None
    assert stored["Event only -05:00"].event_at == datetime(2026, 9, 8, 1, 0)
    # The official calendar date is not shifted by the time conversion.
    assert stored["Published +08:00"].event_date == date(2026, 9, 8)


def test_official_news_date_only_marker_is_not_promoted_to_an_instant(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add(
            Event(
                instrument_id=alpha.id,
                event_date=as_of,
                event_type="announcement",
                title="Date only marker",
                source="mops_material_information",
                details_json={"published_at": "2026-09-07", "event_at": "20260907"},
                collected_at=datetime(2026, 9, 8, 8, 0),
            )
        )
        db.commit()

    with TestClient(app) as client:
        rows = _news_by_title(client, ["Date only marker"])

    for payload in rows["Date only marker"]:
        roles = payload["product_time"]["roles"]
        assert payload["published_at"] is None and payload["event_at"] is None
        assert payload["time_basis"] == "event_date" and payload["time_precision"] == "date"
        assert payload["display_time"] == "2026-09-08T00:00:00"
        assert roles["published_at"]["status"] == "unknown"
        assert roles["event_at"]["status"] == "unknown"
        assert roles["event_date"]["value"] == "2026-09-08"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Offset-aware: converted to UTC, then stored as naive UTC.
        ("2026-09-07T09:30:00+08:00", datetime(2026, 9, 7, 1, 30)),
        ("2026-09-07 09:30:00+08:00", datetime(2026, 9, 7, 1, 30)),
        ("2026-09-07T00:30:00+08:00", datetime(2026, 9, 6, 16, 30)),
        ("2026-09-07T20:00:00-05:00", datetime(2026, 9, 8, 1, 0)),
        ("2026-09-07T09:30:00.123456+08:00", datetime(2026, 9, 7, 1, 30, 0, 123456)),
        ("2026-09-07T09:30:00Z", datetime(2026, 9, 7, 9, 30)),
        ("2026-09-07T09:30:00+00:00", datetime(2026, 9, 7, 9, 30)),
        # Naive: already the database convention (naive UTC), kept as is.
        ("2026-09-07T09:30:00", datetime(2026, 9, 7, 9, 30)),
        ("  2026-09-07T09:30:00  ", datetime(2026, 9, 7, 9, 30)),
        # Not an instant: no value, no time of day, or not a time.
        (None, None),
        ("", None),
        ("   ", None),
        ("2026-09-07", None),
        ("20260907", None),
        ("not a time", None),
        ("0001-01-01T00:00:00+08:00", None),
    ],
)
def test_parse_datetime_normalizes_offset_to_naive_utc(value, expected):
    assert _parse_datetime(value) == expected
    if expected is not None:
        assert _parse_datetime(value).tzinfo is None


def test_news_cursor_and_sort_keep_working_with_aware_display_time(product_api):
    with product_api() as db:
        db.add_all(
            [
                _feed_news(
                    f"n{index}",
                    title=f"feed {index}",
                    published_at=datetime(2026, 10, 17, 8, index),
                    display_time=datetime(2026, 10, 17, 8, index),
                    time_basis="published",
                    time_precision="datetime",
                )
                for index in range(3)
            ]
        )
        db.commit()

    titles = []
    with TestClient(app) as client:
        cursor = None
        for _ in range(5):
            page = client.get("/api/news?limit=1" + (f"&cursor={cursor}" if cursor else "")).json()
            titles.extend(item["title"] for item in page["items"])
            cursor = page["meta"]["next_cursor"]
            if not cursor:
                break
    assert titles == ["feed 2", "feed 1", "feed 0"]


def test_stock_quality_explains_market_and_research_as_separate_purposes(product_api):
    with product_api() as db:
        _as_of, alpha, _beta, _etf = _add_base_fixture(db)

    with TestClient(app) as client:
        response = client.get(f"/api/stocks/{alpha.exchange}/{alpha.symbol}")

    assert response.status_code == 200
    quality = response.json()["quality_summary"]
    assert quality["market"]["label"] == "當日行情來源完整"
    assert quality["research"]["label"] == "策略判斷資料待補"
    assert "bars_20d" in quality["research"]["missing_fields"]
    conditions = response.json()["strategy_conditions"]
    assert conditions["breakout"]["source"] == "系統固定研究規則"
    assert conditions["pullback"]["source"] == "系統固定研究規則"
    assert "官方固定研究規則" not in str(conditions)


def test_product_price_change_requires_adjacent_verified_same_basis(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        run = db.scalar(select(IngestionRun).where(IngestionRun.run_type == "collect"))
        assert run is not None
        raw_previous = RawPayload(
            ingestion_run_id=run.id,
            source="twse",
            endpoint="https://www.twse.com.tw/rwd/zh/fund/MI_INDEX",
            sha256="b" * 64,
            data_as_of="2026-09-07",
        )
        raw_current = RawPayload(
            ingestion_run_id=run.id,
            source="twse",
            endpoint="https://www.twse.com.tw/rwd/zh/fund/MI_INDEX",
            sha256="c" * 64,
            data_as_of=as_of.isoformat(),
        )
        taiex = Instrument(market="TW", exchange="TWSE", symbol="TAIEX", name="TAIEX", instrument_type="index", status="active")
        db.add_all([raw_previous, raw_current, taiex])
        db.flush()
        current = db.scalar(select(MarketBar).where(MarketBar.instrument_id == alpha.id, MarketBar.trading_date == as_of))
        assert current is not None
        current.source = "official"
        current.raw_payload_id = raw_current.id
        db.add(
            MarketBar(
                instrument_id=alpha.id,
                trading_date=date(2026, 9, 7),
                open=98,
                high=101,
                low=97,
                close=100,
                adj_close=100,
                volume=1000,
                turnover=100000,
                source="official",
                raw_payload_id=raw_previous.id,
            )
        )
        db.add_all(
            [
                MarketBar(
                    instrument_id=taiex.id,
                    trading_date=date(2026, 9, 7),
                    open=99,
                    high=101,
                    low=98,
                    close=100,
                    adj_close=100,
                    volume=1000,
                    turnover=100000,
                    source="official",
                    raw_payload_id=raw_previous.id,
                ),
                MarketBar(
                    instrument_id=taiex.id,
                    trading_date=as_of,
                    open=100,
                    high=104,
                    low=99,
                    close=102,
                    adj_close=102,
                    volume=1000,
                    turnover=102000,
                    source="official",
                    raw_payload_id=raw_current.id,
                ),
            ]
        )
        db.commit()
        first = build_action_summaries(db, instrument_ids=[alpha.id])[0]
        current.adj_close = 90
        db.commit()
        # The decision context is a per-Session snapshot of DecisionMarketRead
        # values, so a fixture mutation needs a fresh context before re-reading.
        db.info.clear()
        second = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert first["previous_close"] == pytest.approx(100)
    assert first["price_change"] == pytest.approx(3)
    assert first["price_change_pct"] == pytest.approx(0.03)
    assert second["previous_close"] is None
    assert second["price_change_pct"] is None


def func_count_news():
    # Kept as a tiny selectable helper so the assertion remains independent of
    # a database-specific COUNT implementation in the API test above.
    from sqlalchemy import func
    from app.models import NewsItem

    return func.count(NewsItem.id)


def test_themes_exclude_incomplete_rank_and_glossary_is_structured(product_api):
    with product_api() as db:
        _as_of, _alpha, _beta, _etf = _add_base_fixture(db)

    with TestClient(app) as client:
        qualified = client.get("/api/themes")
        all_themes = client.get("/api/themes?only_qualified=false")
        glossary = client.get("/api/glossary?q=突破")
        stock = client.get("/api/stocks/TWSE/AAA")
        members = client.get("/api/themes/theme-complete/members?page=1&page_size=2")

    assert qualified.status_code == 200
    assert [item["display_name"] for item in qualified.json()["items"]] == ["半導體"]
    assert all_themes.json()["meta"]["total"] == 2
    term = glossary.json()["items"][0]
    assert term["term_id"] == "breakout"
    assert term["limitations"]
    assert stock.status_code == 200 and stock.json()["instrument"]["symbol"] == "AAA"
    assert members.status_code == 200 and members.json()["items"]


def test_actions_are_deduplicated_and_prioritize_held_data_quality(product_api):
    with product_api() as db:
        _as_of, alpha, _beta, _etf = _add_base_fixture(db)
        db.add(PortfolioPosition(instrument_id=alpha.id, shares=10, average_cost=100))
        strategy = StrategyVersion(name="breakout_v1", version="1.0.0", kind="technical", config_json={}, canonical_config_snapshot={})
        db.add(strategy)
        db.flush()
        db.add(
            Signal(
                signal_key="fixture-breakout",
                signal_date=date(2026, 9, 8),
                instrument_id=alpha.id,
                strategy_version_id=strategy.id,
                status="data_incomplete",
                data_quality="incomplete",
                entry_type="conditional",
                rule_evidence_json={"inputs": {"institutional_flow_to_turnover_ratio_5d": None}},
            )
        )
        db.commit()
        summaries = build_action_summaries(db)
        assert len([item for item in summaries if item["instrument"]["symbol"] == "AAA"]) == 1
        assert summaries[0]["action_state"] == "data_insufficient"
        assert summaries[0]["held"] is True
        assert summaries[0]["missing_data_priority"]

    with TestClient(app) as client:
        response = client.get("/api/actions?held_only=true&limit=10")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["action_label_zh"] == "資料不足"
    assert response.json()["items"][0]["action_instruction"] == "現在：先不行動"
    assert "尚不能計算進場、失效與目標價" in response.json()["items"][0]["data_gap"]


def test_action_list_is_compact_while_detail_keeps_audit_evidence(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(db, alpha, as_of)
        db.commit()

    with TestClient(app) as client:
        listing = client.get("/api/actions?limit=1")
        detail = client.get("/api/actions/TWSE/AAA")

    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert "strategies" not in item
    assert "evidence_refs" not in item
    assert "coverage" not in item
    assert len(listing.content) < 40000
    assert detail.status_code == 200
    detail_summary = detail.json()["decision_summary"]
    assert detail_summary["strategies"]
    assert detail_summary["evidence_refs"]
    assert detail_summary["level_semantics"]["kind"] == "rule_reference"
    assert detail_summary["level_semantics"]["version"] == "signal-level-semantics/v1"
    assert detail_summary["level_semantics"]["formula"]["version"] == "legacy-risk-levels/v1"
    assert detail_summary["level_semantics"]["fields"]["trigger_price"]["source_field"] == "breakout_price"
    assert detail_summary["level_semantics"]["price_basis"]["value"] is None
    assert detail_summary["level_semantics"]["decision_at"]["value"] is None
    assert detail_summary["level_semantics"]["generated_at"]["value"] is None
    assert detail_summary["stop_price_semantics"]["origin"] == "signal.invalid_price"
    assert detail_summary["primary_levels"]["semantics"]["trigger"]["source_field"] == "breakout_price"
    assert detail_summary["primary_levels"]["semantics"]["invalid"]["source_field"] == "invalid_price"
    assert item["level_semantics"]["kind"] == "rule_reference"
    assert item["level_semantics"]["fields"]["trigger_price"]["label_zh"] == "規則觸發價"


def test_nonempty_tracking_projects_signal_product_time(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_signal_pair(db, alpha, as_of)
        db.flush()
        signal = db.scalar(select(Signal).where(Signal.signal_key == "fixture-AAA-breakout"))
        assert signal is not None
        db.add(
            SignalEvaluation(
                signal_id=signal.id,
                session_date=as_of + timedelta(days=1),
                session_no=1,
                status="未觸發",
                data_quality="complete",
            )
        )
        db.commit()

    with TestClient(app) as client:
        tracking = client.get("/api/tracking")
        scoped = client.get("/api/tracking/fixture-AAA-breakout")

    assert tracking.status_code == 200
    assert tracking.json()["rows"]
    row_signal = tracking.json()["rows"][0]["signal"]
    assert row_signal["product_time"]["version"] == "product-time/v1"
    assert row_signal["product_time"]["roles"]["market_date"]["status"] == "known"
    assert row_signal["product_time"]["roles"]["earliest_execution_at"]["status"] == "unknown"
    assert scoped.status_code == 200
    assert scoped.json()["signal"]["product_time"]["version"] == "product-time/v1"


def test_action_stop_semantics_preserve_position_origin(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(db, alpha, as_of)
        db.add(PortfolioPosition(instrument_id=alpha.id, shares=10, average_cost=100, stop_price=101))
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "hold_observe"
    assert summary["stop_price_semantics"]["kind"] == "user_position_risk_input"
    assert summary["stop_price_semantics"]["origin"] == "portfolio_position.stop_price"
    assert summary["primary_levels"]["semantics"]["stop"]["kind"] == "user_position_risk_input"
    assert summary["primary_levels"]["semantics"]["stop"]["is_rule_reference"] is False


def test_action_context_does_not_issue_per_field_queries(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(db, alpha, as_of)
        db.commit()
        statements: list[str] = []
        bind = db.get_bind()

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(bind, "after_cursor_execute", capture)
        try:
            build_action_summaries(db, as_of, instrument_ids=[alpha.id])
        finally:
            event.remove(bind, "after_cursor_execute", capture)

    # One summary should be served by the batched context, not a query for
    # each strategy/coverage/evidence field.
    assert len(statements) <= 25
    strategy_queries = [statement for statement in statements if "from strategy_versions" in statement.lower()]
    assert len(strategy_queries) <= 1


def test_complete_conditional_wins_over_observation_without_level_pollution(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(db, alpha, as_of)
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "conditional_entry"
    assert summary["display_action"] == "符合條件後可研究進場"
    assert summary["display_instruction"].startswith("僅在觸發價與資料條件同時成立時研究進場")
    assert summary["primary_reason"]["scope"] == "breakout"
    assert summary["primary_levels"]["kind"] == "trigger_invalid"
    assert summary["primary_strategy"] == "breakout_v1"
    assert summary["alternative_strategies"] == ["pullback_v1"]
    assert summary["trigger_price"] == pytest.approx(21.05)
    assert summary["invalid_price"] == pytest.approx(20.47)
    assert summary["target_1"] == pytest.approx(21.98)
    assert summary["risk_reward"] == pytest.approx((21.98 - 21.05) / (21.05 - 20.47))
    assert summary["blocking_reasons"] == []
    assert summary["strategies"][1]["missing"] == []
    assert summary["strategies"][1]["wait_missing"]


def test_unqualified_theme_does_not_block_complete_conditional(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        score = db.scalar(select(GroupDailyScore).where(GroupDailyScore.group_id == "theme-complete"))
        assert score is not None
        score.data_quality = "partial"
        score.eligible_members = 2
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(db, alpha, as_of, pullback_status="data_incomplete", pullback_quality="incomplete")
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "conditional_entry"
    assert summary["primary_strategy"] == "breakout_v1"
    assert "qualified_theme" not in summary["blocking_reasons"]
    assert summary["theme_ids"] == ["theme-complete"]


def test_incomplete_primary_strategy_fails_closed_but_exposes_alternative(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(
            db,
            alpha,
            as_of,
            breakout_status="data_incomplete",
            breakout_quality="incomplete",
            pullback_status="data_incomplete",
            pullback_quality="incomplete",
        )
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "data_insufficient"
    assert summary["primary_strategy"] is None
    assert summary["trigger_price"] is None
    assert "signal_data_quality" in summary["blocking_reasons"]
    assert "data_incomplete" in summary["blocking_reasons"]
    assert {item["strategy"] for item in summary["strategies"]} == {"breakout_v1", "pullback_v1"}


def test_complete_observations_without_wait_levels_are_no_condition(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(
            db,
            alpha,
            as_of,
            breakout_status="observation",
            pullback_status="observation",
            breakout_levels=False,
        )
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "no_condition"
    assert summary["blocking_reasons"] == []
    assert summary["primary_strategy"] is None
    assert all(summary[key] is None for key in ("trigger_price", "invalid_price", "target_1", "risk_reward"))
    assert {item["strategy"] for item in summary["strategies"]} == {"breakout_v1", "pullback_v1"}
    assert all(item["data_quality"] == "complete" for item in summary["strategies"])


def test_complete_observation_is_not_polluted_by_incomplete_alternative(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(
            db,
            alpha,
            as_of,
            breakout_status="observation",
            pullback_status="data_incomplete",
            pullback_quality="incomplete",
            breakout_levels=False,
        )
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "no_condition"
    assert summary["blocking_reasons"] == []
    assert summary["primary_strategy"] is None
    assert summary["strategies"][0]["data_quality"] == "complete"
    assert summary["strategies"][1]["status"] == "data_incomplete"
    assert summary["strategies"][1]["missing"]


def test_observation_can_wait_without_incomplete_alternative_blocking(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        _add_decision_history(db, alpha, as_of)
        _add_signal_pair(db, alpha, as_of, breakout_status="observation", pullback_status="data_incomplete", pullback_quality="incomplete")
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "wait_breakout"
    assert summary["primary_strategy"] == "breakout_v1"
    assert summary["trigger_price"] == pytest.approx(21.05)
    assert summary["blocking_reasons"] == []


def test_actions_include_complete_conditional_outside_qualified_candidates(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        outsider = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="OUT",
            name="Outside candidate",
            instrument_type="stock",
            status="active",
        )
        _add_decision_history(db, alpha, as_of, extra_instrument=outsider)
        _add_signal_pair(db, outsider, as_of, pullback_status="data_incomplete", pullback_quality="incomplete")
        db.commit()

        summaries = build_action_summaries(db, as_of)
        outsider_summary = next(item for item in summaries if item["instrument"]["symbol"] == "OUT")
        assert outsider_summary["action_state"] == "conditional_entry"

    with TestClient(app) as client:
        response = client.get("/api/actions?limit=100")
    assert response.status_code == 200
    assert any(item["instrument"]["symbol"] == "OUT" for item in response.json()["items"])


def test_action_summary_preserves_two_strategy_conflict(product_api):
    with product_api() as db:
        as_of, alpha, _beta, _etf = _add_base_fixture(db)
        # Enough historical rows for both canonical strategy families.  The
        # exact calendar is synthetic fixture data; it is never exposed as an
        # official source.
        taiex = Instrument(market="TW", exchange="TWSE", symbol="TAIEX", name="TAIEX", instrument_type="index", status="active")
        db.add(taiex)
        db.flush()
        for index in range(0, 61):
            trading_date = as_of - timedelta(days=index)
            db.add(
                MarketBar(
                    instrument_id=taiex.id,
                    trading_date=trading_date,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    adj_close=100,
                    volume=1000,
                    turnover=100000,
                    source="official-fixture",
                )
            )
        for index in range(1, 61):
            trading_date = as_of - timedelta(days=index)
            db.add(
                MarketBar(
                    instrument_id=alpha.id,
                    trading_date=trading_date,
                    open=100,
                    high=105,
                    low=95,
                    close=100 + (index % 3),
                    adj_close=100 + (index % 3),
                    volume=1000,
                    turnover=100000,
                    source="official-fixture",
                )
            )
        for index in range(5):
            trading_date = as_of - timedelta(days=index)
            from app.models import ChipSnapshot

            db.add(
                ChipSnapshot(
                    instrument_id=alpha.id,
                    trading_date=trading_date,
                    foreign_buy=10,
                    trust_buy=5,
                    dealer_buy=2,
                    margin_balance=100,
                    margin_change=1,
                    source="official-fixture",
                )
            )
        breakout = StrategyVersion(name="breakout_v1", version="1.0.0", kind="technical", config_json={}, canonical_config_snapshot={})
        pullback = StrategyVersion(name="pullback_v1", version="1.0.0", kind="technical", config_json={}, canonical_config_snapshot={})
        db.add_all([breakout, pullback])
        db.flush()
        common_evidence = {"inputs": {"group_excess_return_20d": 0.1, "institutional_flow_to_turnover_ratio_5d": 0.01, "margin_balance_change_ratio_5d": 0.02}}
        db.add_all(
            [
                Signal(
                    signal_key="fixture-breakout-complete",
                    signal_date=as_of,
                    instrument_id=alpha.id,
                    strategy_version_id=breakout.id,
                    status="conditional",
                    data_quality="complete",
                    entry_type="conditional",
                    breakout_price=110,
                    invalid_price=90,
                    target_1=140,
                    rule_evidence_json=common_evidence,
                ),
                Signal(
                    signal_key="fixture-pullback-complete",
                    signal_date=as_of,
                    instrument_id=alpha.id,
                    strategy_version_id=pullback.id,
                    status="conditional",
                    data_quality="complete",
                    entry_type="conditional",
                    reference_entry=100,
                    pullback_low=99,
                    pullback_high=101,
                    invalid_price=90,
                    target_1=120,
                    rule_evidence_json=common_evidence,
                ),
            ]
        )
        db.commit()
        summary = build_action_summaries(db, instrument_ids=[alpha.id])[0]

    assert summary["action_state"] == "manual_review"
    assert set(summary["alternative_strategies"] + [summary["primary_strategy"]]) == {"breakout_v1", "pullback_v1"}
    assert summary["conflicts"]


def test_product_redirect_targets_are_available_in_api_surface(product_api):
    # The SPA owns browser redirects; these product endpoints must exist so a
    # redirected route never falls back to a raw admin response.
    with product_api():
        pass
    with TestClient(app) as client:
        assert client.get("/api/stocks?page=1&page_size=1").status_code == 200
        assert client.get("/api/actions?limit=1").status_code == 200
        assert client.get("/api/system/data-quality?limit=1").status_code == 200
