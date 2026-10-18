"""Issue #211: stock-detail groups carry a display name and verification flag."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.migrations import upgrade_database
from app.models import GroupMembership, Instrument, MarketBar, ThemeGroup
from app.taxonomy import INDUSTRY_DISPLAY_ZH, canonical_group_id

OFFICIAL = "TWSE/TPEx official OpenAPI"
D0 = date(2026, 9, 8)


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'groups.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    with factory() as db:
        _seed(db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


def _industry(db, label):
    group = ThemeGroup(
        id=canonical_group_id("industry", label),
        name=f"Industry · {label}",
        group_type="official_industry",
        source=OFFICIAL,
        display_name_zh=INDUSTRY_DISPLAY_ZH[label],
        name_status="official",
        active=True,
    )
    db.add(group)
    return group


def _seed(db):
    """Mirror the production pre-D0 mismatch: 2881 (code 17) sat in Communications."""

    financial = _industry(db, "Financial")
    communications = _industry(db, "Communications")
    semiconductor = _industry(db, "Semiconductor")
    fubon = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="2881",
        name="富邦金",
        instrument_type="stock",
        industry="17",
        status="active",
    )
    tsmc = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="2330",
        name="台積電",
        instrument_type="stock",
        industry="24",
        status="active",
    )
    cht = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="2412",
        name="中華電",
        instrument_type="stock",
        industry="27",
        status="active",
    )
    db.add_all([fubon, tsmc, cht])
    db.flush()
    source = f"{OFFICIAL}; exchange=TWSE"
    db.add_all(
        [
            GroupMembership(
                group_id=communications.id,
                instrument_id=cht.id,
                valid_from=date(2000, 10, 27),
                source=source,
            ),
            GroupMembership(
                group_id=communications.id,
                instrument_id=fubon.id,
                valid_from=date(2001, 12, 19),
                valid_to=date(2026, 9, 7),
                source=source,
            ),
            GroupMembership(
                group_id=financial.id,
                instrument_id=fubon.id,
                valid_from=D0,
                source=source,
            ),
            GroupMembership(
                group_id=semiconductor.id,
                instrument_id=tsmc.id,
                valid_from=date(1994, 9, 5),
                source=source,
            ),
            MarketBar(
                instrument_id=fubon.id,
                trading_date=date(2026, 10, 16),
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
                volume=1,
                source="official",
            ),
        ]
    )
    db.commit()


def _groups(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return response.json()["groups"]


def test_cutoff_after_d0_returns_verified_display_name(client):
    for path in ("/api/stocks/TWSE/2881", "/api/stocks/TWSE/2881?as_of=2026-09-10"):
        assert _groups(client, path) == [
            {
                "id": canonical_group_id("industry", "Financial"),
                "name": "Industry · Financial",
                "display_name": "金融",
                "verified": True,
                "valid_from": "2026-09-08",
                "valid_to": None,
            }
        ]


def test_cutoff_before_d0_keeps_mismatched_row_fail_closed(client):
    rows = _groups(client, "/api/stocks/TWSE/2881?as_of=2026-09-01")
    assert rows == [
        {
            "id": canonical_group_id("industry", "Communications"),
            "name": None,
            "display_name": None,
            "verified": False,
            "valid_from": "2001-12-19",
            "valid_to": "2026-09-07",
        }
    ]
    # A group whose members were already correct before D0 stays visible.
    tsmc = _groups(client, "/api/stocks/TWSE/2330?as_of=2026-09-01")
    assert [(row["display_name"], row["verified"]) for row in tsmc] == [
        ("半導體", True)
    ]


def test_row_is_checked_against_the_instrument_code_without_cutoff(client):
    # No cutoff returns every historical row. Communications passes the group gate
    # today (only 2412 remains), but this old row's code (17) does not match it.
    rows = _groups(client, "/api/instruments/2881?exchange=TWSE")
    assert [
        (row["valid_from"], row["display_name"], row["verified"]) for row in rows
    ] == [
        ("2001-12-19", None, False),
        ("2026-09-08", "金融", True),
    ]
