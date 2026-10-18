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
from worker import news_batch, news_llm
from worker.news_batch import RelationMatcher, collect_news
from worker.news_sources import (
    MAX_RESPONSE_BYTES,
    NEWS_SOURCES,
    REQUEST_INTERVAL_SECONDS,
    SOURCES_BY_ID,
    TAIPEI,
    USER_AGENT,
    FeedResponse,
    HttpFeedFetcher,
    NewsFeed,
    NewsSource,
    NewsSourceError,
    _parse_time,
    canonical_url,
    exclusion_reason,
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
                # Names that end in a listing-marker character but have no dash,
                # a marker suffix, and names that are parts of other words.
                Instrument(
                    exchange="TWSE", symbol="3481", name="群創", instrument_type="stock"
                ),
                Instrument(
                    exchange="TPEx",
                    symbol="5314",
                    name="世紀*",
                    instrument_type="stock",
                ),
                Instrument(
                    exchange="TWSE",
                    symbol="4966",
                    name="譜瑞-KY",
                    instrument_type="stock",
                ),
                Instrument(
                    exchange="TWSE",
                    symbol="2412",
                    name="中華電",
                    instrument_type="stock",
                ),
                Instrument(
                    exchange="TWSE",
                    symbol="2383",
                    name="台光電",
                    instrument_type="stock",
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
    assert (
        canonical_url("http://A.Example/x/?ref=home") == "https://a.example/x?ref=home"
    )
    assert canonical_url("https://a.example/") == "https://a.example/"


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


@pytest.mark.parametrize(
    ("raw", "offset", "expected"),
    [
        ("2026-02-30", None, (None, None)),
        ("20261017", TAIPEI, (None, date(2026, 10, 17))),
        ("2026-10-17", TAIPEI, (None, date(2026, 10, 17))),
        ("Sat, 17 Oct 2026", TAIPEI, (None, None)),
        ("Sat, 17 Oct 2026 10:00:00 -0000", TAIPEI, (None, None)),
        ("Sat, 17 Oct 2026 10:00:00 +0000", None, (datetime(2026, 10, 17, 10), None)),
        ("2026-10-17T16:33:41", TAIPEI, (datetime(2026, 10, 17, 8, 33, 41), None)),
        ("2026-10-17T16:33:41", None, (None, None)),
        ("2026-10-17T16:33:41+09:00", None, (datetime(2026, 10, 17, 7, 33, 41), None)),
        ("not a time", TAIPEI, (None, None)),
    ],
)
def test_time_parsing(raw, offset, expected):
    assert _parse_time(raw, offset) == expected


def test_invalid_date_does_not_fail_the_feed(db):
    source = _single_feed_source(naive_offset=TAIPEI)
    content = _rss(
        "<title>壞日期</title><link>https://feed.example/bad</link><pubDate>2026-02-30</pubDate>",
        "<title>基本格式日期</title><link>https://feed.example/basic</link><pubDate>20261017</pubDate>",
    )
    result = collect_news(db, fetch=lambda url: _ok(content), news_sources=[source])
    assert result["status"] == "success"
    bad, basic = _items(db)
    assert (bad.time_basis, bad.published_at, bad.event_date) == (
        "unverified",
        None,
        None,
    )
    assert (basic.time_basis, basic.time_precision, basic.published_at) == (
        "event_date",
        "date",
        None,
    )


def test_text_is_unescaped_before_tags_are_removed_and_cut_to_column_length(db):
    source = _single_feed_source()
    long_title = "長" * 402
    long_guid = "g" * 250
    content = _rss(
        "<title><![CDATA[&amp;lt;b&amp;gt;粗體&amp;lt;/b&amp;gt; S&amp;P]]></title>"
        "<link>https://feed.example/t</link>"
        "<description>&lt;p&gt;第一段&lt;/p&gt;&lt;br/&gt;第二段</description>",
        f"<title>{long_title}</title><link>https://feed.example/long</link><guid>{long_guid}</guid>",
        f"<title>超長連結</title><link>https://feed.example/{'x' * 800}</link>",
    )
    result = collect_news(db, fetch=lambda url: _ok(content), news_sources=[source])
    assert result["sources"][0]["feeds"][0]["skipped"] == 1
    markup, long_item = _items(db)
    assert markup.title == "粗體 S&P" and markup.summary == "第一段 第二段"
    assert len(long_item.title) == 300 and long_item.source_item_id == "g" * 180


def test_raw_and_run_record_the_assumed_offset_of_zone_less_times(db):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    for source_name, source_id, offset in (
        ("工商時報", "ctee", "+08:00"),
        ("中央社", "cna", None),
    ):
        item = _items(db, source_name=source_name)[0]
        raw = json.loads(
            Path(db.get(RawPayload, item.raw_payload_id).payload_path).read_text(
                encoding="utf-8"
            )
        )
        run = db.scalar(select(IngestionRun).where(IngestionRun.source == source_id))
        assert raw["naive_time_offset"] == offset
        assert run.metadata_json["naive_time_offset"] == offset


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


def test_listing_markers_need_a_dash_and_aliases_have_two_characters():
    aliases = news_batch._name_aliases
    assert aliases("群創") == {"群創"}
    assert aliases("世紀*") == {"世紀"}
    assert aliases("譜瑞-KY") == {"譜瑞-KY", "譜瑞"}
    assert aliases("奧義賽博-KY創") == {"奧義賽博-KY創", "奧義賽博"}
    assert aliases("太景*-KY") == {"太景*-KY", "太景"}


def test_number_next_to_a_single_character_of_a_name_does_not_match(matcher):
    assert matcher.symbols("面板族群成交量3481張") == []
    assert matcher.symbols("群創(3481)今日法說") == ["TWSE:3481"]
    assert matcher.symbols("世紀(5314)得標") == ["TPEx:5314"]
    assert matcher.symbols("譜瑞-KY(4966-TW)目標價調升") == ["TWSE:4966"]


def test_longer_phrase_containing_a_name_does_not_match(matcher):
    assert matcher.symbols("中華電視今晚播出財經節目") == []
    assert matcher.symbols("中華電宣布調降資費") == ["TWSE:2412"]


def test_industry_name_needs_an_industry_word_and_verified_theme(matcher):
    assert matcher.theme_ids("半導體與光電族群走強") == [OPTO]
    assert matcher.theme_ids("半導體類股領漲、光電股走弱") == [OPTO, SEMICONDUCTOR]
    assert matcher.theme_ids("半導體產業與半導體業") == [SEMICONDUCTOR]
    assert matcher.theme_ids("國際金融市場震盪") == []
    assert matcher.theme_ids("其他產業代碼 37 個股") == []


def test_generic_theme_names_and_names_inside_company_names_do_not_match(db):
    db.add_all(
        [
            ThemeGroup(
                id="official-industry-composite",
                name="Industry · Composite",
                display_name_zh="綜合",
                group_type="official_industry",
                name_status="official",
                active=True,
            ),
            ThemeGroup(
                id="official-industry-finance",
                name="Industry · Financial",
                display_name_zh="金融",
                group_type="official_industry",
                name_status="official",
                active=True,
            ),
        ]
    )
    db.commit()
    matcher = RelationMatcher.from_db(db)
    assert matcher.theme_ids("（中央社台北17日綜合外電報導）綜合類股") == []
    assert matcher.theme_ids("國際金融市場震盪，金融股走低") == [
        "official-industry-finance"
    ]
    assert matcher.theme_ids("台光電股價創高") == []


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


def test_doctype_after_a_long_prefix_is_still_refused():
    padding = b"<!--" + b"x" * 5000 + b"-->"
    laughs = b'<!DOCTYPE rss [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    document = (
        b'<?xml version="1.0"?>' + padding + laughs + b"<rss><channel><item>"
        b"<title>&b;</title><link>https://feed.example/x</link></item></channel></rss>"
    )
    with pytest.raises(NewsSourceError, match="DTD"):
        parse_rss(document, SOURCES_BY_ID["cna"])


def _fetcher(handler):
    return HttpFeedFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )


def test_http_fetcher_follows_redirects_only_within_the_feed_host():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        if request.url.path == "/new":
            return httpx.Response(200, content=b"<rss/>")
        return httpx.Response(
            302, headers={"location": "https://elsewhere.example/rss"}
        )

    fetcher = _fetcher(handler)
    assert fetcher("https://feed.example/old").content == b"<rss/>"
    with pytest.raises(NewsSourceError, match="another host"):
        fetcher("https://feed.example/away")
    fetcher.close()


def test_http_fetcher_refuses_bodies_over_the_size_limit():
    fetcher = _fetcher(
        lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
    )
    with pytest.raises(NewsSourceError, match="exceeds"):
        fetcher("https://feed.example/big")
    fetcher.close()


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


def test_stock_page_lists_feed_news_by_exchange_and_symbol(db, client):
    collect_news(db, run_date=RUN_DATE, fetch=FixtureFetcher())
    joint = _rss(
        "<title>台積電與乙電子(7777)合作</title><link>https://feed.example/joint</link>"
        "<pubDate>Sat, 17 Oct 2026 12:00:00 +0800</pubDate>"
    )
    collect_news(db, fetch=lambda url: _ok(joint), news_sources=[_single_feed_source()])
    assert _by_title(db, "台積電與乙電子(7777)合作").symbols_json == [
        "TPEx:7777",
        "TWSE:2330",
    ]

    def titles(exchange, symbol):
        body = client.get(
            f"{router.prefix}/stocks/{exchange}/{symbol}",
            params={"as_of": "2026-10-18"},
        ).json()
        return {item["title"] for item in body["news"]}

    assert titles("TPEx", "7777") == {
        "乙電子(7777-TWO)接獲新訂單 周漲一成",
        "台積電與乙電子(7777)合作",
    }
    assert titles("TWSE", "7777") == set()
    assert titles("TWSE", "2330") == {
        "台積電在熊本建3奈米廠　日本批准補助資格",
        "台積電在熊本建3奈米廠 日本批准補助資格！",
        "台積電與乙電子(7777)合作",
    }


# Non-market filter (#189) ---------------------------------------------------------

NON_MARKET_REASONS = {
    "今彩539第115252期開獎": "section:ahel",
    "今彩539第115252期　頭獎3注中獎": "section:ahel",
    "男子持刀闖超商搶劫　警方1小時內逮人": "section:asoc",
    "大樂透第115097期　頭獎槓龜": "title:lottery",
    "國道連環車禍　3車追撞2人輕傷": "title:society",
}
MARKET_TITLES = {
    "台積電在熊本建3奈米廠　日本批准補助資格",
    "穆迪調升埃及信評　維持正面展望",
    "中信金前3季獲利創高　台彩子公司貢獻穩定",
    "產險業第3季車險理賠升溫　汽機車保費調整",
}


def _collect_cna_mixed(db):
    content = (FIXTURES / "cna_finance_non_market.xml").read_bytes()
    return collect_news(
        db,
        run_date=RUN_DATE,
        fetch=lambda url: _ok(content),
        news_sources=[SOURCES_BY_ID["cna"]],
    )


def _cna_run(db):
    return db.scalars(
        select(IngestionRun)
        .where(IngestionRun.run_type == "news", IngestionRun.source == "cna")
        .order_by(IngestionRun.id.desc())
    ).first()


def test_lottery_and_society_items_are_excluded_with_reasons_and_market_news_kept(db):
    result = _collect_cna_mixed(db)

    assert (result["inserted"], result["excluded"]) == (9, 5)
    assert {item.title: item.status for item in _items(db)} == {
        **{title: "excluded" for title in NON_MARKET_REASONS},
        **{title: "active" for title in MARKET_TITLES},
    }
    run = _cna_run(db)
    assert run.status == "success" and run.records == 9
    assert run.metadata_json["filter"] == {
        "version": "news-filter/v1",
        "existing_excluded": [],
    }
    feed = run.metadata_json["feeds"][0]
    assert feed["excluded"] == 5
    assert {item["title"]: item["reason"] for item in feed["excluded_items"]} == (
        NON_MARKET_REASONS
    )
    lottery = _by_title(db, "今彩539第115252期開獎")
    assert {
        "canonical_key": lottery.canonical_key,
        "title": lottery.title,
        "url": "https://www.cna.com.tw/news/ahel/202610170173.aspx",
        "reason": "section:ahel",
    } in feed["excluded_items"]
    # The raw feed is kept whole, excluded items included.
    raw = db.get(RawPayload, lottery.raw_payload_id)
    assert "今彩539第115252期開獎" in Path(raw.payload_path).read_text(encoding="utf-8")


def test_rerun_counts_excluded_items_as_existing(db):
    _collect_cna_mixed(db)
    result = _collect_cna_mixed(db)

    assert (result["inserted"], result["existing"], result["excluded"]) == (0, 9, 0)
    assert result["existing_excluded"] == 0
    assert len(_items(db, status="excluded")) == 5


def test_stored_active_non_market_items_are_marked_excluded_not_deleted(
    db, monkeypatch
):
    # Rows written before the filter existed.
    monkeypatch.setattr(news_batch, "exclusion_reason", lambda *args: None)
    _collect_cna_mixed(db)
    monkeypatch.undo()
    assert len(_items(db, status="active")) == 9
    before = {item.id: (item.title, item.impact_method) for item in _items(db)}

    empty = _rss()
    result = collect_news(
        db,
        run_date=RUN_DATE,
        fetch=lambda url: _ok(empty),
        news_sources=[SOURCES_BY_ID["cna"]],
    )

    assert result["existing_excluded"] == 5
    assert {item.id: (item.title, item.impact_method) for item in _items(db)} == before
    assert {item.title for item in _items(db, status="excluded")} == set(
        NON_MARKET_REASONS
    )
    moved = _cna_run(db).metadata_json["filter"]["existing_excluded"]
    assert {item["title"]: item["reason"] for item in moved} == NON_MARKET_REASONS
    # A second pass finds nothing left to move.
    collect_news(
        db,
        run_date=RUN_DATE,
        fetch=lambda url: _ok(empty),
        news_sources=[SOURCES_BY_ID["cna"]],
    )
    assert _cna_run(db).metadata_json["filter"]["existing_excluded"] == []


class _Killed(BaseException):
    """Stands in for a crash or kill that no feed-level handler catches."""


def test_moved_rows_are_recorded_in_run_metadata_before_feeds_are_fetched(
    db, monkeypatch
):
    monkeypatch.setattr(news_batch, "exclusion_reason", lambda *args: None)
    _collect_cna_mixed(db)
    monkeypatch.undo()

    def killed(url):
        raise _Killed

    with pytest.raises(_Killed):
        collect_news(
            db, run_date=RUN_DATE, fetch=killed, news_sources=[SOURCES_BY_ID["cna"]]
        )
    db.rollback()

    run = _cna_run(db)
    assert run.status == "running"
    moved = run.metadata_json["filter"]["existing_excluded"]
    assert {item["title"]: item["reason"] for item in moved} == NON_MARKET_REASONS
    assert {item.title for item in _items(db, status="excluded")} == set(
        NON_MARKET_REASONS
    )


def test_excluded_items_are_hidden_from_api_and_llm_selection(db, client):
    _collect_cna_mixed(db)
    listed = client.get(f"{router.prefix}/news", params={"limit": 50}).json()
    assert {item["title"] for item in listed["items"]} == MARKET_TITLES
    lottery = _by_title(db, "今彩539第115252期開獎")
    assert client.get(f"{router.prefix}/news/{lottery.id}").status_code == 404

    selected = news_llm.select_items(db, now=datetime(2026, 10, 17, 15, 0))
    assert {item.title for item in selected} == MARKET_TITLES


@pytest.mark.parametrize(
    ("source_id", "title", "url", "expected"),
    [
        # Sections count only as a directory of the item URL, per source.
        (
            "cnbc",
            "Pumpkin farm brings in $2 million",
            "https://www.cnbc.com/make-it/2026/10/17/farm.html",
            "section:make-it",
        ),
        (
            "cnbc",
            "Best credit cards",
            "https://www.cnbc.com/select/best-cards/",
            "section:select",
        ),
        ("cnbc", "Stocks fall", "https://www.cnbc.com/2026/10/17/make-it.html", None),
        ("yahoo_tw", "台股收黑", "https://tw.stock.yahoo.com/asoc/news/x.html", None),
        # Titles are NFKC-normalised and case-folded.
        (
            "cnbc",
            "POWERBALL jackpot climbs",
            "https://www.cnbc.com/2026/10/17/p.html",
            "title:lottery",
        ),
        (
            "yahoo_tw",
            "今彩５３９頭獎開出",
            "https://tw.stock.yahoo.com/news/a.html",
            "title:lottery",
        ),
        (
            "ctee",
            "工廠命案震驚地方",
            "https://www.ctee.com.tw/news/1-x",
            "title:society",
        ),
        ("cnyes", "台股量縮整理", "https://news.cnyes.com/news/id/1", None),
    ],
)
def test_exclusion_reason(source_id, title, url, expected):
    assert exclusion_reason(SOURCES_BY_ID[source_id], title, url) == expected
