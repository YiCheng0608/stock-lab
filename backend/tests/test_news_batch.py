"""News feed batch on fixture RSS and an in-memory SQLite database (no network)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import get_db, router
from app.db import Base, enable_sqlite_foreign_keys
from app.models import IngestionRun, Instrument, NewsItem, RawPayload, ThemeGroup
from worker import news_batch
from worker.news_batch import RelationMatcher, collect_news
from worker.news_sources import (
    NEWS_SOURCES,
    REQUEST_INTERVAL_SECONDS,
    SOURCES_BY_ID,
    USER_AGENT,
    FeedResponse,
    HttpFeedFetcher,
    NewsFeed,
    NewsSource,
    NewsSourceError,
    canonical_url,
    parse_rss,
)

FIXTURES = Path(__file__).parent / "fixtures" / "news"
FEED_FILES = {
    feed.url: FIXTURES / f"{source.source_id}_{feed.key}.xml"
    for source in NEWS_SOURCES
    for feed in source.feeds
}
RUN_DATE = date(2026, 10, 17)
SEMICONDUCTOR = "official-industry-semi"
OPTO = "official-industry-opto"


def _ok(content: bytes) -> FeedResponse:
    return FeedResponse(200, "application/xml", content, content.decode("utf-8-sig"))


class FixtureFetcher:
    def __init__(self, overrides=None, transform=None):
        self.overrides = overrides or {}
        self.transform = transform
        self.calls: list[str] = []

    def __call__(self, url: str) -> FeedResponse:
        self.calls.append(url)
        override = self.overrides.get(url)
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override
        content = FEED_FILES[url].read_bytes()
        if self.transform:
            content = self.transform(content)
        return _ok(content)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.add_all(
            [
                Instrument(
                    exchange="TWSE",
                    symbol="2330",
                    name="台積電",
                    instrument_type="stock",
                ),
                Instrument(
                    exchange="TWSE", symbol="2409", name="友達", instrument_type="stock"
                ),
                Instrument(
                    exchange="TWSE",
                    symbol="7777",
                    name="甲公司",
                    instrument_type="stock",
                ),
                Instrument(
                    exchange="TPEx",
                    symbol="7777",
                    name="乙電子",
                    instrument_type="stock",
                ),
                Instrument(
                    exchange="TWSE",
                    symbol="0050",
                    name="元大台灣50",
                    instrument_type="etf",
                ),
                ThemeGroup(
                    id=SEMICONDUCTOR,
                    name="Industry · Semiconductor",
                    display_name_zh="半導體",
                    group_type="official_industry",
                    name_status="official",
                    active=True,
                ),
                ThemeGroup(
                    id=OPTO,
                    name="Industry · Optoelectronics",
                    display_name_zh="光電",
                    group_type="official_industry",
                    name_status="official",
                    active=True,
                ),
                ThemeGroup(
                    id="official-industry-other",
                    name="Industry · Other",
                    display_name_zh="其他",
                    group_type="official_industry",
                    name_status="official",
                    active=True,
                ),
                ThemeGroup(
                    id="official-industry-37",
                    name="Industry · 37",
                    display_name_zh="產業代碼 37",
                    group_type="official_industry",
                    name_status="pending",
                    active=True,
                ),
            ]
        )
        session.commit()
        yield session
    engine.dispose()


def _items(db, **filters):
    query = select(NewsItem).order_by(NewsItem.id)
    for key, value in filters.items():
        query = query.where(getattr(NewsItem, key) == value)
    return db.scalars(query).all()


def _by_title(db, title):
    return db.scalar(select(NewsItem).where(NewsItem.title == title))


# AC-1 ------------------------------------------------------------------------


def test_fixture_run_writes_raw_and_news_items(db):
    result = collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())

    assert (
        result["status"] == "success"
        and result["inserted"] == 12
        and result["failed_feeds"] == []
    )
    assert db.scalar(select(func.count(NewsItem.id))) == 12
    assert db.scalar(select(func.count(RawPayload.id))) == 9
    runs = db.scalars(select(IngestionRun).where(IngestionRun.run_type == "news")).all()
    assert sorted(run.source for run in runs) == sorted(
        source.source_id for source in NEWS_SOURCES
    )
    assert {run.status for run in runs} == {"success"} and {
        run.run_date for run in runs
    } == {RUN_DATE}

    cna = _by_title(db, "台積電在熊本建3奈米廠　日本批准補助資格")
    assert (cna.category, cna.source_kind, cna.source_name, cna.language) == (
        "domestic",
        "media",
        "中央社",
        "zh-Hant",
    )
    assert cna.source_item_id == "CNA/2026-10-17/202610170001"
    assert (cna.source_url, cna.source_url_kind) == (
        "https://www.cna.com.tw/news/afe/202610170001.aspx",
        "item",
    )
    assert cna.summary.startswith("（中央社記者台北17日電）")
    assert cna.published_at == datetime(2026, 10, 17, 8, 48, 10)  # +08:00 → UTC
    assert (cna.time_basis, cna.time_precision, cna.event_date) == (
        "published",
        "datetime",
        None,
    )
    assert (
        cna.display_time == cna.published_at
        and cna.time_consistency == "verified"
        and cna.status == "active"
    )
    assert cna.canonical_key.startswith("news:cna:") and len(cna.content_hash) == 64
    assert cna.collected_at is not None and cna.impact_direction == "unknown"
    raw = db.get(RawPayload, cna.raw_payload_id)
    assert (
        raw.source == "news_cna"
        and raw.endpoint == "https://feeds.feedburner.com/rsscna/finance"
    )
    assert Path(raw.payload_path).exists()

    # ctee publishes zone-less Taipei times.
    ctee = _items(db, source_name="工商時報")[0]
    assert (
        ctee.published_at == datetime(2026, 10, 17, 8, 33, 41)
        and ctee.source_item_id == "20261017000001"
    )
    # Yahoo has an empty guid: no source_item_id, the canonical URL identifies the item.
    yahoo = _items(db, source_name="Yahoo奇摩股市")
    assert len(yahoo) == 2 and {item.source_item_id for item in yahoo} == {None}
    fed = _items(db, source_name="Federal Reserve")[0]
    assert (fed.category, fed.source_kind, fed.language) == (
        "international",
        "macro_official",
        "en",
    )
    assert fed.title == "Minutes of the Board's discount rate meetings"
    mw = _items(db, source_name="MarketWatch")[0]
    assert (
        mw.source_url
        == "https://www.marketwatch.com/story/market-leadership-shifts-away-from-tech-8e8516da"
    )
    assert (
        mw.summary
        == "The S&P 500’s tech sector had its worst week in a year and a half."
    )


def test_raw_capture_drops_embedded_article_bodies(db):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    item = _items(db, source_name="鉅亨網")[0]
    raw_path = Path(db.get(RawPayload, item.raw_payload_id).payload_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    assert payload["removed_elements"] == {"content:encoded": 2}
    assert "ARTICLE-BODY-EXCERPT" not in raw_path.read_text(encoding="utf-8")
    assert all("ARTICLE-BODY-EXCERPT" not in (row.summary or "") for row in _items(db))


def test_rerun_is_idempotent_and_keeps_published_at(db):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    before = {
        item.canonical_key: (item.id, item.published_at, item.title)
        for item in _items(db)
    }

    def shifted(content: bytes) -> bytes:
        return content.replace(b"16:48:10 +0800", b"18:00:00 +0800").replace(
            b"10:20:44 GMT", b"12:00:00 GMT"
        )

    result = collect_news(
        db, run_date=RUN_DATE, fetch=FixtureFetcher(transform=shifted)
    )
    assert result["inserted"] == 0 and result["existing"] == 15
    after = {
        item.canonical_key: (item.id, item.published_at, item.title)
        for item in _items(db)
    }
    assert after == before
    assert (
        db.scalar(
            select(func.count(IngestionRun.id)).where(IngestionRun.run_type == "news")
        )
        == 14
    )


# AC-2 ------------------------------------------------------------------------


def test_same_source_duplicate_guid_is_stored_once(db):
    result = collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    cna = next(item for item in result["sources"] if item["source"] == "cna")["feeds"][
        0
    ]
    assert (cna["items"], cna["inserted"], cna["existing"]) == (3, 2, 1)
    assert len(_items(db, source_item_id="CNA/2026-10-17/202610170001")) == 1
    # CNBC reuses one guid across its Top News and Market Insider feeds.
    assert (
        len(_items(db, source_item_id="108400001")) == 1
        and len(_items(db, source_name="CNBC")) == 3
    )


def test_same_source_url_with_different_tracking_parameters_is_stored_once(db):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    rows = _items(
        db, source_url="https://tw.stock.yahoo.com/news/tsmc-kumamoto-100000001.html"
    )
    assert len(rows) == 1
    assert (
        canonical_url("https://a.example/x?utm_source=1&id=7&mod=rss#top")
        == "https://a.example/x?id=7"
    )


def test_cross_source_same_day_same_title_share_cluster_and_both_are_kept(db):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    cna = _by_title(db, "台積電在熊本建3奈米廠　日本批准補助資格")
    yahoo = _by_title(db, "台積電在熊本建3奈米廠 日本批准補助資格！")
    assert cna.source_name != yahoo.source_name and cna.id != yahoo.id
    assert (
        cna.dedupe_cluster_id == yahoo.dedupe_cluster_id
        and cna.dedupe_cluster_id.startswith("news-title:")
    )
    others = {
        item.dedupe_cluster_id
        for item in _items(db)
        if item.id not in {cna.id, yahoo.id}
    }
    assert cna.dedupe_cluster_id not in others


def _single_feed_source(**overrides) -> NewsSource:
    base = dict(
        source_id="probe",
        source_name="測試來源",
        owner="test",
        source_kind="media",
        category="domestic",
        language="zh-Hant",
        feeds=(NewsFeed("main", "main", "https://feed.example/rss"),),
        item_url_rule="test",
        terms="test",
    )
    base.update(overrides)
    return NewsSource(**base)


def _rss(*items: str) -> bytes:
    body = "".join(f"<item>{item}</item>" for item in items)
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode()


def test_same_title_on_another_day_is_another_cluster(db):
    source = _single_feed_source()
    content = _rss(
        "<title>同題</title><link>https://feed.example/1</link><pubDate>Sat, 17 Oct 2026 10:00:00 +0800</pubDate>",
        "<title>同題</title><link>https://feed.example/2</link><pubDate>Sun, 18 Oct 2026 10:00:00 +0800</pubDate>",
    )
    collect_news(db, fetch=lambda url: _ok(content), news_sources=[source])
    first, second = _items(db)
    assert first.dedupe_cluster_id != second.dedupe_cluster_id


def test_date_only_source_time_writes_event_date_without_clock_time(db):
    source = _single_feed_source()
    content = _rss(
        "<title>只有日期</title><link>https://feed.example/d</link><pubDate>2026-10-16</pubDate>"
    )
    collect_news(db, fetch=lambda url: _ok(content), news_sources=[source])
    item = _items(db)[0]
    assert item.published_at is None and item.event_date == date(2026, 10, 16)
    assert (item.time_basis, item.time_precision) == ("event_date", "date")
    assert item.display_time == datetime(2026, 10, 16)


def test_zone_less_time_from_a_source_without_declared_offset_stays_unknown(db):
    source = _single_feed_source()
    content = _rss(
        "<title>無時區</title><link>https://feed.example/n</link><pubDate>2026-10-17T16:33:41</pubDate>"
    )
    collect_news(db, fetch=lambda url: _ok(content), news_sources=[source])
    item = _items(db)[0]
    assert (
        item.published_at is None
        and item.event_date is None
        and item.display_time is None
    )
    assert (item.time_basis, item.time_precision, item.time_consistency) == (
        "unverified",
        "none",
        "unverified",
    )


def test_source_time_in_the_future_is_quarantined_without_relations(db):
    source = _single_feed_source()
    content = _rss(
        "<title>台積電未來稿</title><link>https://feed.example/f</link><pubDate>Fri, 01 Jan 2099 00:00:00 GMT</pubDate>"
    )
    collect_news(db, fetch=lambda url: _ok(content), news_sources=[source])
    item = _items(db)[0]
    assert (item.time_consistency, item.status, item.symbols_json) == (
        "conflict",
        "quarantined",
        [],
    )


# AC-3 ------------------------------------------------------------------------


@pytest.fixture
def matcher(db):
    return RelationMatcher.from_db(db)


def test_code_with_name_matches(matcher):
    assert matcher.symbols("面板廠友達(2409)今天公布營收") == ["TWSE:2409"]


def test_bare_number_does_not_match(matcher):
    assert matcher.symbols("台股終場大漲2330點，成交量放大") == []
    assert matcher.symbols("預計2409年完成") == []


def test_code_with_ticker_suffix_or_code_label_matches_single_listing(matcher):
    assert matcher.symbols("目標價調升：(2330-TW)") == ["TWSE:2330"]
    assert matcher.symbols("股票代號：2330") == ["TWSE:2330"]


def test_same_code_on_two_exchanges_is_not_resolved_by_code(matcher):
    assert matcher.symbols("新訂單(7777-TW)公告") == []
    assert matcher.symbols("代號7777") == []
    assert matcher.symbols("乙電子(7777)接獲新訂單") == ["TPEx:7777"]
    assert matcher.symbols("甲公司(7777)董事會") == ["TWSE:7777"]


def test_two_character_name_needs_its_code_and_three_character_name_matches_alone(
    matcher,
):
    assert matcher.symbols("友達ADR昨日收低") == []
    assert matcher.symbols("台積電熊本廠獲補助") == ["TWSE:2330"]


def test_industry_name_matches_official_verified_theme_only(matcher):
    assert matcher.theme_ids("半導體與光電族群走強") == [OPTO, SEMICONDUCTOR]
    assert matcher.theme_ids("其他產業代碼 37 個股") == []


def test_relations_in_batch_and_unmatched_items_are_kept_with_unknown_direction(db):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    tsmc = _by_title(db, "台積電在熊本建3奈米廠　日本批准補助資格")
    assert (tsmc.symbols_json, tsmc.theme_ids_json, tsmc.impact_scope) == (
        ["TWSE:2330"],
        [SEMICONDUCTOR],
        "instrument",
    )
    assert tsmc.impact_method == news_batch.RELATION_METHOD
    assert _by_title(db, "乙電子(7777-TWO)接獲新訂單 周漲一成").symbols_json == [
        "TPEx:7777"
    ]
    ctee = _items(db, source_name="工商時報")[0]
    assert (ctee.symbols_json, ctee.theme_ids_json) == (["TWSE:2409"], [OPTO])

    bare = _by_title(db, "台股終場大漲2330點　成交量放大")
    assert (bare.symbols_json, bare.theme_ids_json, bare.impact_scope) == (
        [],
        [],
        "unknown",
    )
    assert _by_title(db, "友達ADR下跌 折台股34元").symbols_json == []
    fed = _items(db, source_name="Federal Reserve")[0]
    assert (fed.symbols_json, fed.impact_scope) == ([], "market")
    assert {item.impact_direction for item in _items(db)} == {"unknown"}


# AC-4 ------------------------------------------------------------------------


def _feed_url(source_id: str, index: int = 0) -> str:
    return SOURCES_BY_ID[source_id].feeds[index].url


def test_failing_sources_are_recorded_and_others_still_write(db):
    fetcher = FixtureFetcher(
        overrides={
            _feed_url("cna"): FeedResponse(500, "text/html", b"error", "error"),
            _feed_url("cnyes"): FeedResponse(
                429, "text/html", b"slow down", "slow down"
            ),
            _feed_url("ctee"): _ok(b"<rss><channel><item><title>broken"),
            _feed_url("cnbc", 1): NewsSourceError(
                "request failed: ReadTimeout: timed out"
            ),
        }
    )
    result = collect_news(db, run_date=RUN_DATE, fetch=fetcher)

    assert result["status"] == "partial"
    assert result["failed_feeds"] == [
        "cna/finance",
        "cnyes/tw_stock",
        "ctee/stock",
        "cnbc/market_insider",
    ]
    runs = {
        run.source: run
        for run in db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == "news")
        )
    }
    assert (runs["cna"].status, runs["cna"].error) == ("failed", "finance: HTTP 500")
    assert (runs["cnyes"].status, runs["cnyes"].error) == (
        "failed",
        "tw_stock: rate limited (HTTP 429)",
    )
    assert runs["ctee"].status == "failed" and runs["ctee"].error.startswith(
        "stock: format error"
    )
    assert runs["cnbc"].status == "partial" and "market_insider" in runs["cnbc"].error
    assert {runs[key].status for key in ("yahoo_tw", "marketwatch", "fed")} == {
        "success"
    }
    assert {item.source_name for item in _items(db)} == {
        "Yahoo奇摩股市",
        "CNBC",
        "MarketWatch",
        "Federal Reserve",
    }
    assert len(_items(db, source_name="CNBC")) == 2  # top_news + technology
    # The malformed payload is kept as raw evidence, never as news rows.
    assert (
        db.scalar(
            select(func.count(RawPayload.id)).where(RawPayload.source == "news_ctee")
        )
        == 1
    )


def test_failure_while_writing_a_feed_rolls_back_only_that_feed(db, monkeypatch):
    original = RelationMatcher.symbols

    def flaky(self, text):
        if "不同追蹤參數" in text or "友達ADR" in text:
            raise ValueError("matcher exploded")
        return original(self, text)

    monkeypatch.setattr(RelationMatcher, "symbols", flaky)
    result = collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    assert result["failed_feeds"] == ["yahoo_tw/tw_market"]
    assert _items(db, source_name="Yahoo奇摩股市") == []
    assert len(_items(db, source_name="中央社")) == 2


def test_doctype_and_non_rss_documents_are_format_errors():
    with pytest.raises(NewsSourceError, match="DTD"):
        parse_rss(
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss><channel/></rss>',
            SOURCES_BY_ID["cna"],
        )
    with pytest.raises(NewsSourceError, match="expected <rss><channel>"):
        parse_rss(b"<html><body/></html>", SOURCES_BY_ID["cna"])


def test_http_fetcher_sends_fixed_user_agent_and_waits_between_requests():
    seen, sleeps = [], []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, content=b"<rss/>")

    fetcher = HttpFeedFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append
    )
    fetcher("https://feed.example/a")
    fetcher("https://feed.example/b")
    fetcher.close()
    assert sleeps == [REQUEST_INTERVAL_SECONDS] and seen == [USER_AGENT, USER_AGENT]


def test_run_without_news_table_reports_failure(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    monkeypatch.setattr(news_batch, "SessionLocal", sessionmaker(bind=engine))
    assert news_batch.run_news_batch() == {
        "status": "failed",
        "reason": "news_items_table_missing_run_init_db",
    }
    engine.dispose()


# AC-5 (API part) ----------------------------------------------------------------


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client


def test_api_filters_domestic_and_international_news(db, client):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())

    international = client.get(
        f"{router.prefix}/news", params={"category": "international", "limit": 50}
    ).json()
    assert {item["category"] for item in international["items"]} == {"international"}
    assert {item["source_name"] for item in international["items"]} == {
        "CNBC",
        "MarketWatch",
        "Federal Reserve",
    }
    assert international["meta"]["total"] == 5

    domestic = client.get(
        f"{router.prefix}/news", params={"category": "domestic", "limit": 50}
    ).json()
    assert {item["category"] for item in domestic["items"]} == {"domestic"}
    # Seven stored rows; the CNA/Yahoo cross-source pair is one card.
    assert domestic["meta"]["total"] == 6

    found = client.get(f"{router.prefix}/news", params={"symbol": "7777"}).json()[
        "items"
    ]
    assert len(found) == 1
    item = found[0]
    assert item["instruments"] == [
        {"exchange": "TPEx", "symbol": "7777", "name": "乙電子"}
    ]
    assert item["source"] == {
        "name": "鉅亨網",
        "url": "https://news.cnyes.com/news/id/1000002",
        "url_kind": "item",
    }
    assert (
        item["provenance"]["endpoint"] == _feed_url("cnyes")
        and item["provenance"]["event_id"] is None
    )
    assert item["impact"]["direction"] == "unknown"
