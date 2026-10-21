"""GET /api/strategies row identity: ``id`` and the stored ``formula_version``.

RAM SQLite and an app that mounts only the API router: no migrations, no files
and no network, so the formal database and ``app.main`` startup are untouched.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api_module
from app.models import StrategyVersion

V1 = "institutional-flow/v1-shares-per-twd-turnover"
V2 = "institutional-flow/v2-shares-per-share-volume"
ROW_KEYS = {
    "id",
    "name",
    "version",
    "formula_version",
    "kind",
    "active",
    "config",
    "canonical_config_snapshot",
    "created_at",
}


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    StrategyVersion.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                # One name/version, several formulas: the case that broke the card key.
                StrategyVersion(
                    name="breakout_v1",
                    version="1.0.0",
                    formula_version=V1,
                    kind="breakout",
                    active=False,
                    config_json={"a": 1},
                    canonical_config_snapshot={"snap": 1},
                    created_at=datetime(2026, 10, 1, 2, 3, 4),
                ),
                StrategyVersion(
                    name="breakout_v1",
                    version="1.0.0",
                    formula_version=V2,
                    kind="breakout",
                    active=True,
                    config_json={"a": 2},
                    canonical_config_snapshot={"snap": 2},
                ),
                StrategyVersion(
                    name="breakout_v1",
                    version="1.0.0",
                    formula_version="unclassified/empty_snapshot",
                    kind="breakout",
                    active=False,
                ),
                # No formula_version given: the column's server default is returned as stored.
                StrategyVersion(
                    name="breakout_v1", version="1.0.0", kind="breakout", active=False
                ),
                StrategyVersion(
                    name="pullback_v1",
                    version="1.0.0",
                    formula_version=V2,
                    kind="pullback",
                    active=True,
                ),
            ]
        )
        db.commit()

    def override_get_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(api_module.router)
    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_strategy_rows_expose_id_and_stored_formula_version(client):
    items = client.get("/api/strategies?page=1&page_size=10").json()["items"]
    assert len(items) == 5
    assert all(set(item) == ROW_KEYS for item in items)
    assert all(isinstance(item["id"], int) for item in items)
    assert len({item["id"] for item in items}) == 5
    same_version = [
        item
        for item in items
        if (item["name"], item["version"]) == ("breakout_v1", "1.0.0")
    ]
    assert len(same_version) == 4
    # Raw stored values, not translated or inferred; unclassified rows stay unclassified.
    assert sorted(item["formula_version"] for item in same_version) == sorted(
        [V1, V2, "unclassified/empty_snapshot", "unclassified/unspecified"]
    )


def test_existing_strategy_fields_are_unchanged(client):
    items = {
        item["formula_version"]: item
        for item in client.get("/api/strategies").json()["items"]
        if item["name"] == "breakout_v1"
    }
    v1, v2 = items[V1], items[V2]
    assert (
        v1["version"],
        v1["kind"],
        v1["active"],
        v1["config"],
        v1["canonical_config_snapshot"],
    ) == ("1.0.0", "breakout", False, {"a": 1}, {"snap": 1})
    assert v1["created_at"] == "2026-10-01T02:03:04"
    assert (v2["active"], v2["config"], v2["canonical_config_snapshot"]) == (
        True,
        {"a": 2},
        {"snap": 2},
    )
    assert v2["created_at"] is not None
    empty = items["unclassified/empty_snapshot"]
    assert empty["config"] == {} and empty["canonical_config_snapshot"] == {}


def test_order_search_and_paging_are_unchanged(client):
    everything = client.get("/api/strategies?page=1&page_size=10").json()
    assert [(item["name"], item["version"]) for item in everything["items"]] == [
        ("breakout_v1", "1.0.0")
    ] * 4 + [("pullback_v1", "1.0.0")]
    ids = [item["id"] for item in everything["items"]]
    assert ids[:4] == sorted(ids[:4])

    pullback = client.get("/api/strategies?q=pull").json()
    assert [item["name"] for item in pullback["items"]] == ["pullback_v1"]
    assert pullback["items"][0]["formula_version"] == V2

    first = client.get("/api/strategies?page=1&page_size=2").json()
    second = client.get("/api/strategies?page=2&page_size=2").json()
    assert [item["id"] for item in first["items"] + second["items"]] == ids[:4]
    assert first["pagination"]["total"] == 5 and first["pagination"]["has_next"] is True
