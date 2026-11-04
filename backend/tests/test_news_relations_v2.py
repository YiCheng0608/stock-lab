"""News relation rule v2: short names, two-character names, ETFs, rerelation (#451).

In-memory SQLite and instrument rows named after the real listings the 2026-11-03～04
news mentioned; no network.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.clock import utcnow
from app.db import Base, enable_sqlite_foreign_keys
from app.models import IngestionRun, Instrument, NewsItem
from worker import news_batch
from worker.news_batch import RelationMatcher, collect_news

RUN_DATE = date(2026, 11, 4)
V1 = "rule:exact-name-code/v1"

INSTRUMENTS = [
    # exchange, symbol, name, type, status
    ("TWSE", "3711", "日月光投控", "stock", "active"),
    ("TWSE", "2303", "聯電", "stock", "active"),
    ("TPEx", "4905", "台聯電", "stock", "active"),
    ("TPEx", "2643", "捷迅", "stock", "active"),
    ("TWSE", "2409", "友達", "stock", "active"),
    ("TWSE", "3481", "群創", "stock", "active"),
    ("TWSE", "2317", "鴻海", "stock", "active"),
    ("TWSE", "1459", "聯發", "stock", "active"),
    ("TWSE", "2454", "聯發科", "stock", "active"),
    ("TWSE", "1303", "南亞", "stock", "active"),
    ("TWSE", "1473", "台南", "stock", "active"),
    ("TPEx", "5906", "台南-KY", "stock", "active"),
    ("TWSE", "5007", "三星", "stock", "active"),
    ("TPEx", "8923", "時報", "stock", "active"),
    ("TWSE", "4807", "日成-KY", "stock", "active"),
    ("TWSE", "9905", "大華", "stock", "active"),
    ("TPEx", "3718", "中光電投控", "ipo", "active"),
    ("TPEx", "5371", "中光電", "stock", "delisted"),
    ("TWSE", "0050", "元大台灣50", "etf", "active"),
    ("TWSE", "00981A", "主動統一台股增長", "etf", "active"),
    ("TWSE", "0060", "新台灣", "etf", "active"),
    # #457 review: a full name starting with another stock's two-character name.
    ("TWSE", "1229", "聯華", "stock", "active"),
    ("TWSE", "2412", "中華電", "stock", "active"),
    ("TWSE", "2204", "中華", "stock", "active"),
    # Common-word names.
    ("TWSE", "2605", "新興", "stock", "active"),
    ("TWSE", "2455", "全新", "stock", "active"),
    ("TPEx", "3167", "大量", "stock", "active"),
    ("TWSE", "9940", "信義", "stock", "active"),
    ("TWSE", "2331", "精英", "stock", "active"),
    ("TPEx", "4420", "光明", "stock", "active"),
    ("TWSE", "1210", "大成", "stock", "active"),
    ("TWSE", "2723", "美食-KY", "stock", "active"),
    ("TWSE", "2371", "大同", "stock", "active"),
    ("TWSE", "2515", "中工", "stock", "active"),
    ("TWSE", "3105", "穩懋", "stock", "active"),
    # Only listed rows decide whether a two-character name is unique.
    ("TPEx", "8908", "欣雄", "stock", "transferred"),
    ("TWSE", "8908", "欣雄", "stock", "active"),
    ("TWSE", "3598", "奕力", "stock", "delisted"),
    ("TWSE", "6962", "奕力", "stock", "active"),
    ("TWSE", "4444", "舊名", "stock", "delisted"),
    # #457 second review: foreign companies and more common words.
    ("TWSE", "2374", "佳能", "stock", "active"),
    ("TWSE", "1445", "大宇", "stock", "active"),
    ("TPEx", "3570", "大塚", "stock", "active"),
    ("TWSE", "4739", "康普", "stock", "active"),
    ("TWSE", "2609", "陽明", "stock", "active"),
    ("TPEx", "8109", "博大", "stock", "active"),
    ("TWSE", "8201", "無敵", "stock", "active"),
    ("TWSE", "1218", "泰山", "stock", "active"),
    ("TWSE", "6531", "愛普*", "stock", "active"),
    # #461: full names without their industry words, and the measurement.
    ("TWSE", "2385", "群光", "stock", "active"),
    ("TWSE", "6412", "群電", "stock", "active"),
    ("TWSE", "2002", "中鋼", "stock", "active"),
    ("TWSE", "1723", "中碳", "stock", "active"),
    ("TPEx", "5213", "亞昕", "stock", "active"),
]


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.add_all(
            Instrument(
                exchange=exchange,
                symbol=symbol,
                name=name,
                instrument_type=kind,
                status=status,
            )
            for exchange, symbol, name, kind, status in INSTRUMENTS
        )
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def matcher(db):
    return RelationMatcher.from_db(db)


# Short names --------------------------------------------------------------------


def test_holding_company_short_name_matches_without_its_ending(matcher):
    assert matcher.symbols("日月光CPO和台積電COUPE差在哪") == ["TWSE:3711"]
    assert matcher.symbols("主動ETF連14日買超 狂掃日月光、聯發科") == [
        "TWSE:2454",
        "TWSE:3711",
    ]


def test_holding_ending_yields_to_another_stocks_official_name(matcher):
    # 中光電 is the official name of 5371, so it is not read as 3718 中光電投控.
    assert matcher.symbols("中光電投控今天舉行線上法說") == ["TPEx:3718"]
    assert matcher.symbols("中光電今天舉行線上法說") == ["TPEx:5371"]


def test_new_listing_counts_as_a_stock(matcher):
    assert matcher.symbols("中光電投控(3718)董事會") == ["TPEx:3718"]


# Two-character names --------------------------------------------------------------


def test_two_character_name_at_the_start_of_a_title_segment_matches(matcher):
    assert matcher.symbols("聯電ADR2日下跌") == ["TWSE:2303"]
    assert matcher.symbols("捷迅Q3 EPS創同期新高") == ["TPEx:2643"]
    assert matcher.symbols("《航運股》捷迅三引擎催動") == ["TPEx:2643"]
    assert matcher.symbols("量價雙增王　鴻海與面板雙虎") == ["TWSE:2317"]


def test_two_character_name_forming_a_whole_segment_of_the_summary_matches(matcher):
    assert matcher.symbols(
        "台股盤後焦點", "電子權值股走弱，群創、友達、鴻海。包含聯電都下跌"
    ) == ["TWSE:2317", "TWSE:2409", "TWSE:3481"]


def test_two_character_name_inside_a_sentence_does_not_match(matcher):
    # Preceded by a CJK character: not the start of a segment.
    assert matcher.symbols("賣友達比賣台積電還慘") == []
    # In the summary it must also end the segment.
    assert matcher.symbols("台股盤後焦點", "隨後聯電股價走低") == []
    assert matcher.symbols("台股盤後焦點", "，聯電今日開低") == []
    # The end of the summary closes a segment.
    assert matcher.symbols("台股盤中速報", "焦點個股領跌。其中 聯電") == ["TWSE:2303"]


def test_two_character_name_inside_a_longer_name_or_word_does_not_match(matcher):
    assert matcher.symbols("台聯電今日公告") == ["TPEx:4905"]
    assert matcher.symbols("聯發科如何撐台股") == ["TWSE:2454"]
    assert matcher.symbols("美、歐、東南亞航空運價有上漲") == []


def test_two_character_name_after_a_digit_or_letter_does_not_match(matcher):
    assert matcher.symbols("截至中午12時報46,361點") == []
    assert matcher.symbols("雙成長引擎 22日成興櫃新兵") == []


def test_two_character_name_shared_by_two_markets_needs_its_code(matcher):
    assert matcher.symbols("台南藝術節今天開幕") == []
    assert matcher.symbols("台南(1473)公告董事會決議") == ["TWSE:1473"]


def test_two_character_stopwords_need_their_code(matcher):
    assert matcher.symbols("韓媒：三星德州二廠將為特斯拉代工") == []
    assert matcher.symbols("【時報記者王小明台北報導】") == []
    assert matcher.symbols("三星(5007)第3季獲利") == ["TWSE:5007"]


def test_a_longer_phrase_that_means_another_company_blocks_a_two_character_name(
    matcher,
):
    assert matcher.symbols("台股重挫1612點　大華銀投信這樣看") == []
    assert matcher.symbols("大華(9905)董事會決議") == ["TWSE:9905"]


# ETFs ---------------------------------------------------------------------------


def test_full_name_starting_with_another_two_character_name_is_its_own_company(
    matcher,
):
    # 聯華 (1229) opens 聯華電子, the full name of 2303 聯電.
    assert matcher.symbols("聯華電子第三季營收創高") == ["TWSE:2303"]
    assert matcher.symbols("中華電信ADR下跌") == ["TWSE:2412"]
    assert matcher.symbols("聯華今日公告") == ["TWSE:1229"]


def test_full_name_aliases_come_from_the_masters_and_start_with_a_two_character_name():
    rows = news_batch.load_full_name_aliases()
    assert ("TWSE", "2303", "聯華電子") in rows
    assert all(len(name) > 2 for _, _, name in rows)


@pytest.mark.parametrize(
    "title",
    [
        "新興市場資金流向",
        "全新iPhone開賣",
        "大量資金湧入台股",
        "信義區房價創高",
        "精英人才搶手",
        "光明前景可期",
        "大成長時代來臨",
        "美食外送平台競爭",
        "大同小異的財報",
        "中工程進度落後",
        # A space after the name does not end the segment (#457 second review).
        "全新 iPhone 17 登場",
        "大量 資金湧入",
        "新興 市場",
        "信義 房屋",
        "大同 小異",
        # Added after the pre-registered draw (#457 second review).
        "陽明山國家公園",
        "南亞市場需求",
        "博大精深",
        "無敵鐵金剛",
        "泰山區房價創高",
    ],
)
def test_common_word_names_do_not_match_as_words(matcher, title):
    assert matcher.symbols(title) == []


@pytest.mark.parametrize(
    "title",
    ["佳能新相機開賣", "大宇造船接單", "大塚製藥", "康普裁員", "愛普生印表機"],
)
def test_foreign_company_homonyms_need_their_code(matcher, title):
    assert matcher.symbols(title) == []


def test_foreign_company_homonyms_match_next_to_their_code(matcher):
    assert matcher.symbols("佳能(2374)第3季獲利") == ["TWSE:2374"]
    assert matcher.symbols("愛普(6531)營收創高") == ["TWSE:6531"]


def test_common_word_names_still_match_as_a_whole_segment(matcher):
    assert matcher.symbols("微波通訊元件領跌", "其中 全新、穩懋 跌停") == [
        "TWSE:2455",
        "TWSE:3105",
    ]
    assert matcher.symbols("盤中速報", "焦點個股領跌。其中 全新") == ["TWSE:2455"]
    assert matcher.symbols("全新(2455)第3季獲利") == ["TWSE:2455"]
    # Spaces before the closing punctuation are skipped.
    assert matcher.symbols("盤中速報", "其中 全新 、穩懋 跌停") == [
        "TWSE:2455",
        "TWSE:3105",
    ]
    assert matcher.symbols("盤中速報", "陽明、萬海齊揚") == ["TWSE:2609"]


# #461 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # 群光電能科技 without 科技 is 6412 群電, not 2385 群光.
        ("群光電能營收創新高", ["TWSE:6412"]),
        ("群光電能科技第3季獲利", ["TWSE:6412"]),
        # 中鋼碳素化學 without 化學 is 1723 中碳, not 2002 中鋼.
        ("中鋼碳素調價", ["TWSE:1723"]),
        # The two-character names alone are still their own stocks.
        ("群光營收創新高", ["TWSE:2385"]),
        ("中鋼調價", ["TWSE:2002"]),
    ],
)
def test_a_full_name_without_its_industry_words_is_its_own_company(
    matcher, title, expected
):
    assert matcher.symbols(title) == expected


def test_full_name_aliases_include_names_without_industry_words():
    rows = news_batch.load_full_name_aliases()
    assert ("TWSE", "6412", "群光電能") in rows
    assert ("TWSE", "1723", "中鋼碳素") in rows
    assert not [row for row in rows if row[2] in ("群光", "中鋼")]


def test_taishan_the_district_needs_its_code_even_in_a_list(matcher):
    # 1218 泰山 matched 「將推桃園、泰山、台南5案」 (#457 out-of-sample review).
    assert matcher.symbols("建案", "將推桃園、泰山、台南5案") == []
    assert matcher.symbols("泰山區房價創高") == []
    assert matcher.symbols("泰山(1218)第3季獲利") == ["TWSE:1218"]


def test_another_company_that_starts_with_a_two_character_name_is_blocked(matcher):
    # 亞昕科技 registered on the emerging market; 5213 亞昕 is a builder (#461).
    assert matcher.symbols("亞昕科技23日每股120元登興櫃") == []
    assert matcher.symbols("亞昕(5213)推案") == ["TPEx:5213"]


def test_only_listed_rows_decide_two_character_names(matcher):
    # The transferred TPEx row and the delisted 3598 row do not make the listed
    # name ambiguous, and a delisted stock's name needs its code.
    assert matcher.symbols("欣雄法說會登場") == ["TWSE:8908"]
    assert matcher.symbols("奕力第3季獲利") == ["TWSE:6962"]
    assert matcher.symbols("舊名今日公告") == []
    assert matcher.symbols("舊名(4444)今日公告") == ["TWSE:4444"]


def test_etf_matches_by_code_with_its_name_or_by_a_long_name(matcher):
    assert matcher.symbols("元大台灣50（0050）成交量居冠") == ["TWSE:0050"]
    assert matcher.symbols("主動統一台股增長(00981A)規模創高") == ["TWSE:00981A"]
    assert matcher.symbols("主動統一台股增長規模創高") == ["TWSE:00981A"]
    assert matcher.symbols("ETF冠軍竟然不是0050") == []
    # Short ETF names are ordinary phrases; they need the code.
    assert matcher.symbols("新台灣經濟模式") == []


# Rerelation of stored items -------------------------------------------------------


def _item(db, key, title, *, published_at, method=V1, status="active", symbols=()):
    item = NewsItem(
        canonical_key=key,
        category="domestic",
        source_kind="media",
        source_name="鉅亨網",
        title=title,
        summary=None,
        published_at=published_at,
        collected_at=published_at,
        display_time=published_at,
        symbols_json=list(symbols),
        theme_ids_json=[],
        impact_scope="instrument" if symbols else "unknown",
        impact_method=method,
        status=status,
    )
    db.add(item)
    db.commit()
    return item


def test_recent_items_of_an_older_rule_are_related_again_and_the_old_values_kept(db):
    now = datetime(2026, 11, 4, 9, 0)
    recent = _item(db, "a", "聯電ADR2日下跌", published_at=now - timedelta(days=2))
    old = _item(db, "b", "聯電ADR下跌", published_at=now - timedelta(days=4))
    same = _item(
        db, "e", "台積電熊本廠", published_at=now - timedelta(days=1), symbols=()
    )
    conflict = _item(
        db,
        "c",
        "聯電ADR下跌",
        published_at=now - timedelta(days=1),
        method="time_consistency_conflict",
    )
    excluded = _item(
        db, "d", "聯電ADR下跌", published_at=now - timedelta(days=1), status="excluded"
    )

    result = news_batch._rerelate_recent(db, RelationMatcher.from_db(db), RUN_DATE, now)

    assert (result["rerelated"], result["changed"]) == (2, 1)
    assert (
        recent.symbols_json,
        recent.impact_scope,
        recent.impact_method,
    ) == (["TWSE:2303"], "instrument", news_batch.RELATION_METHOD)
    for untouched, method in ((old, V1), (conflict, "time_consistency_conflict")):
        assert (untouched.symbols_json, untouched.impact_method) == ([], method)
    assert excluded.impact_method == V1
    run = db.scalar(
        select(IngestionRun).where(IngestionRun.run_type == "news_relations")
    )
    assert run.id == result["run_id"]
    assert (run.status, run.records) == ("success", 2)
    assert run.metadata_json["items"] == [
        {
            "news_item_id": recent.id,
            "previous": {
                "method": V1,
                "symbols": [],
                "theme_ids": [],
                "impact_scope": "unknown",
            },
            "symbols": ["TWSE:2303"],
            "theme_ids": [],
            "impact_scope": "instrument",
        }
    ]
    assert run.metadata_json["unchanged"] == {V1: [same.id]}
    # Nothing is due on the next run, so no further run is opened.
    assert (
        news_batch._rerelate_recent(db, RelationMatcher.from_db(db), RUN_DATE, now)
        is None
    )
    assert len(db.scalars(select(IngestionRun)).all()) == 1
    assert same.impact_method == news_batch.RELATION_METHOD


def test_news_collection_relates_recent_older_rule_items_before_the_feeds(db):
    item = _item(
        db, "a", "《航運股》捷迅三引擎催動", published_at=utcnow() - timedelta(hours=5)
    )
    result = collect_news(
        db, run_date=RUN_DATE, fetch=lambda url: None, news_sources=()
    )
    assert result["relations"]["rerelated"] == 1
    db.refresh(item)
    assert (item.symbols_json, item.impact_method) == (
        ["TPEx:2643"],
        news_batch.RELATION_METHOD,
    )


def test_a_failing_rerelation_leaves_the_old_relations_and_still_collects(
    db, monkeypatch
):
    item = _item(db, "a", "聯電ADR2日下跌", published_at=utcnow() - timedelta(hours=5))
    fetched: list[str] = []

    def explode(*args, **kwargs):
        raise ValueError("matcher exploded")

    monkeypatch.setattr(news_batch, "_rerelate_recent", explode)
    result = collect_news(
        db,
        run_date=RUN_DATE,
        fetch=lambda url: fetched.append(url),
        news_sources=news_batch.NEWS_SOURCES[:1],
    )
    assert result["relations"] == {
        "status": "failed",
        "error": "ValueError: matcher exploded",
    }
    assert fetched  # the feeds were still fetched
    db.refresh(item)
    assert (item.symbols_json, item.impact_method) == ([], V1)
