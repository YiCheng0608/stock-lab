"""The stock directory and the free-text search of its neighbours (#602)."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import SEARCH_MAX_LENGTH, get_db, router
from app.db import Base, enable_sqlite_foreign_keys
from app.models import GroupMembership, Instrument, MarketBar, Signal, ThemeGroup


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client


def instrument(db, symbol, name, *, exchange="TWSE", instrument_type="stock"):
    row = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=name,
        instrument_type=instrument_type,
        status="active",
    )
    db.add(row)
    db.flush()
    return row


# ``%`` and ``_`` in q are literal text (AC-6): before #602 both were LIKE
# wildcards, so "_" listed every row and "50%" matched any "50...".
SEARCH_ROWS = [
    ("1101", "台泥"),
    ("2330", "台積電"),
    ("00A_1", "底線_名稱"),
    ("00B50", "百分比50%債"),
    ("00C50", "五十檔債"),
]


def seed_search(db):
    rows = [instrument(db, symbol, name) for symbol, name in SEARCH_ROWS]
    for row in rows:
        db.add(
            Signal(
                signal_key=f"analysis-{row.symbol}-2026-11-09",
                signal_date=date(2026, 11, 9),
                instrument_id=row.id,
            )
        )
    db.commit()


def _symbols(client, path, q):
    response = client.get(path, params={"q": q, "page_size": 50})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    if path == "/api/instruments":
        return sorted(item["symbol"] for item in items)
    return sorted(item["instrument"]["symbol"] for item in items)


SEARCH_PATHS = ["/api/stocks", "/api/instruments", "/api/signals"]


@pytest.mark.parametrize("path", SEARCH_PATHS)
def test_search_wildcards_match_literally(db, client, path):
    seed_search(db)
    assert _symbols(client, path, "_") == ["00A_1"]
    assert _symbols(client, path, "A_1") == ["00A_1"]
    assert _symbols(client, path, "%") == ["00B50"]
    assert _symbols(client, path, "50%") == ["00B50"]
    # The escape character itself is literal too.
    assert _symbols(client, path, "/") == []
    # Plain text still matches symbol or name, any case.
    assert _symbols(client, path, "00a") == ["00A_1"]
    assert _symbols(client, path, "台") == ["1101", "2330"]
    assert _symbols(client, path, " 50 ") == ["00B50", "00C50"]


@pytest.mark.parametrize("path", SEARCH_PATHS)
def test_search_longer_than_limit_is_422(db, client, path):
    seed_search(db)
    assert client.get(path, params={"q": "a" * SEARCH_MAX_LENGTH}).status_code == 200
    response = client.get(path, params={"q": "a" * (SEARCH_MAX_LENGTH + 1)})
    assert response.status_code == 422


# ---- sort (AC-2) ----

AS_OF = date(2026, 11, 9)
# (exchange, symbol, name, type, closes by day offset from AS_OF; None = no bar)
DIRECTORY = [
    ("TPEx", "00679B", "元大美債20年", "etf", {0: 26.72}),
    ("TPEx", "006201", "元大富櫃50", "etf", {0: 33.64}),
    ("TWSE", "0050", "元大台灣50", "etf", {0: 33.64}),
    ("TWSE", "1101", "台泥", "stock", {0: 26.8}),
    ("TPEx", "1258", "其祥-KY", "stock", {0: 26.8}),
    ("TWSE", "2330", "台積電", "stock", {-1: 1450.0, 0: 1460.0, 1: 9999.0}),
    ("TPEx", "3105", "穩懋", "stock", {}),
    # The newest bar has no usable close: no price, not the older one.
    ("TWSE", "2002", "中鋼", "stock", {-1: 20.0, 0: 0.0}),
    ("TPEx", "7795", "新上市", "ipo", {0: 120.0}),
    ("TWSE", "7795", "新上市", "ipo", {0: 118.0}),
]


@pytest.fixture
def directory(db, monkeypatch):
    import app.api as api_module

    monkeypatch.setattr(api_module, "latest_official_as_of", lambda _db: (None, AS_OF))
    for exchange, symbol, name, kind, closes in DIRECTORY:
        row = instrument(db, symbol, name, exchange=exchange, instrument_type=kind)
        for offset, close in closes.items():
            day = date.fromordinal(AS_OF.toordinal() + offset)
            db.add(
                MarketBar(
                    instrument_id=row.id,
                    trading_date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adj_close=close,
                    volume=1000,
                    source="twse",
                )
            )
    db.commit()


def _page(client, **params):
    response = client.get("/api/stocks", params={"page_size": 50, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _keys(body):
    return [
        (item["instrument"]["exchange"], item["instrument"]["symbol"])
        for item in body["items"]
    ]


def test_default_order_is_type_then_symbol(client, directory):
    body = _page(client)
    assert body["meta"]["sort"] == "type"
    assert _keys(body) == [
        ("TWSE", "1101"),
        ("TPEx", "1258"),
        ("TWSE", "2002"),
        ("TWSE", "2330"),
        ("TPEx", "3105"),
        ("TWSE", "0050"),
        ("TPEx", "006201"),
        ("TPEx", "00679B"),
        ("TPEx", "7795"),
        ("TWSE", "7795"),
    ]
    assert _keys(_page(client, sort="type")) == _keys(body)


def test_symbol_and_name_orders(client, directory):
    assert [symbol for _, symbol in _keys(_page(client, sort="symbol"))] == [
        "0050",
        "006201",
        "00679B",
        "1101",
        "1258",
        "2002",
        "2330",
        "3105",
        "7795",
        "7795",
    ]
    names = [item["instrument"]["name"] for item in _page(client, sort="name")["items"]]
    assert names == sorted(names)


@pytest.mark.parametrize("sort", ["close_desc", "close_asc"])
def test_close_orders_follow_the_shown_close(client, directory, sort):
    body = _page(client, sort=sort)
    shown = [item["latest_price"] for item in body["items"]]
    priced = [price for price in shown if price is not None]
    # No price last; the bar after the as-of day (9999) is not the close.
    assert shown[len(priced) :] == [None, None]
    assert priced == sorted(priced, reverse=sort == "close_desc")
    assert 9999.0 not in priced and 1460.0 in priced
    assert {key for key, price in zip(_keys(body), shown) if price is None} == {
        ("TWSE", "2002"),
        ("TPEx", "3105"),
    }
    # Equal closes fall back to symbol, then exchange.
    ties = [key for key, price in zip(_keys(body), shown) if price == 33.64]
    assert ties == [("TWSE", "0050"), ("TPEx", "006201")]


@pytest.mark.parametrize("sort", ["action", "exchange", "symbol desc", ""])
def test_unknown_sort_is_422(client, directory, sort):
    assert client.get("/api/stocks", params={"sort": sort}).status_code == 422


@pytest.mark.parametrize("sort", ["type", "symbol", "name", "close_desc", "close_asc"])
def test_pages_never_repeat_or_skip(client, directory, sort):
    full = _keys(_page(client, sort=sort))
    paged = []
    for page in (1, 2, 3, 4):
        body = _page(client, sort=sort, page=page, page_size=3)
        assert body["meta"]["total"] == len(DIRECTORY)
        paged += _keys(body)
    assert paged == full
    assert len(set(paged)) == len(DIRECTORY)


def test_list_rows_carry_only_what_the_table_reads(client, directory):
    items = _page(client)["items"]
    assert all(
        "product_time" not in item and "response_generated_at" not in item
        for item in items
    )
    # One bar is far from 20: every row is short of data and keeps one gap.
    assert {item["action_state"] for item in items} == {"data_insufficient"}
    assert all(len(item["missing_data_priority"]) == 1 for item in items)


def test_theme_filter_keeps_the_sort(db, client, directory):
    group = ThemeGroup(id="cement", name="水泥")
    db.add(group)
    db.flush()
    for symbol in ("1101", "2330", "0050"):
        row = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
        db.add(
            GroupMembership(
                group_id=group.id, instrument_id=row.id, valid_from=date(2026, 1, 1)
            )
        )
    db.commit()
    body = _page(client, theme_id="cement", sort="close_desc")
    assert body["meta"]["total"] == 3
    assert [symbol for _, symbol in _keys(body)] == ["2330", "0050", "1101"]
