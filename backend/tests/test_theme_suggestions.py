"""News theme suggestions: aggregation, idempotency, versions and the API."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import get_db, router
from app.db import Base, enable_sqlite_foreign_keys
from app.models import (
    NewsItem,
    NewsLlmResult,
    ThemeGroup,
    ThemeSuggestion,
    ThemeSuggestionNews,
)
from app.theme_suggestions import AGGREGATION_VERSION, STATUS_PENDING, theme_key
from worker import theme_suggestions
from worker.theme_suggestions import refresh_theme_suggestions

# 2026-10-17 10:00 Taipei
BASE_TIME = datetime(2026, 10, 17, 2, 0)
NOW = datetime(2026, 10, 18, 1, 0)


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


_counter = iter(range(1, 10_000))


def _news(
    db,
    themes,
    *,
    days_ago=0,
    status="done",
    unsupported=False,
    prompt="news_v1",
    model="claude-haiku-5-5",
    news_status="active",
    published_at=...,
    item=None,
):
    """One news item (or ``item``) with one LLM result carrying ``themes``."""

    if item is None:
        index = next(_counter)
        moment = BASE_TIME - timedelta(days=days_ago)
        item = NewsItem(
            canonical_key=f"news:test:{index}",
            category="domestic",
            source_kind="media",
            source_name="鉅亨網",
            title=f"新聞標題{index}",
            published_at=moment if published_at is ... else published_at,
            collected_at=moment,
            status=news_status,
        )
        db.add(item)
        db.flush()
    result = NewsLlmResult(
        news_item_id=item.id,
        prompt_version=prompt,
        llm_model=model,
        llm_input_hash="0" * 64,
        llm_status=status,
        ai_unsupported=unsupported if status == "done" else None,
        ai_symbol_candidates_json=[],
        ai_theme_candidates_json=[
            theme
            if isinstance(theme, dict)
            else {"theme": theme, "reason": f"{theme}理由"}
            for theme in themes
        ],
    )
    db.add(result)
    db.commit()
    return item, result


def _rows(db):
    return {row.theme_key: row for row in db.scalars(select(ThemeSuggestion)).all()}


def _links(db, suggestion):
    return db.scalars(
        select(ThemeSuggestionNews)
        .where(ThemeSuggestionNews.suggestion_id == suggestion.id)
        .order_by(ThemeSuggestionNews.news_item_id)
    ).all()


def _snapshot(db):
    rows = []
    for row in db.scalars(select(ThemeSuggestion).order_by(ThemeSuggestion.id)).all():
        links = [
            (
                link.news_item_id,
                link.news_llm_result_id,
                link.theme_text,
                link.reason,
                link.news_date,
            )
            for link in _links(db, row)
        ]
        rows.append(
            (
                row.id,
                row.prompt_version,
                row.theme_key,
                row.display_name,
                row.aggregation_version,
                row.llm_models_json,
                row.news_count,
                row.first_news_date,
                row.last_news_date,
                row.matched_group_id,
                row.status,
                row.computed_at,
                links,
            )
        )
    return rows


def test_theme_key_merges_width_case_and_spaces_only():
    assert (
        theme_key("AI 伺服器")
        == theme_key("AI伺服器")
        == theme_key("ａｉ　伺服器")
        == "ai伺服器"
    )
    # No synonyms or partial matches.
    assert theme_key("半導體業") != theme_key("半導體")


def test_same_name_is_merged_and_counted_once_per_news(db):
    _news(db, ["AI 伺服器"], days_ago=3)
    _news(db, ["AI伺服器", "ＡＩ 伺服器"], days_ago=1)  # one item, two spellings: once
    _news(db, ["AI 伺服器", "散熱"], days_ago=0)
    result = refresh_theme_suggestions(db, now=NOW)

    rows = _rows(db)
    assert set(rows) == {"ai伺服器", "散熱"}
    server = rows["ai伺服器"]
    assert server.news_count == 3
    # Most frequent spelling wins.
    assert server.display_name == "AI 伺服器"
    assert (server.first_news_date, server.last_news_date) == (
        date(2026, 10, 14),
        date(2026, 10, 17),
    )
    links = _links(db, server)
    assert [link.theme_text for link in links] == ["AI 伺服器", "AI伺服器", "AI 伺服器"]
    assert [link.reason for link in links] == [
        "AI 伺服器理由",
        "AI伺服器理由",
        "AI 伺服器理由",
    ]
    assert server.status == STATUS_PENDING
    assert result["status"] == "success"
    assert (
        result["records"],
        result["links"],
        result["inserted"],
        result["source_results"],
    ) == (2, 4, 2, 3)


def test_display_name_tie_takes_the_earliest_spelling(db):
    _news(db, ["光通訊"], days_ago=1)
    _news(db, ["光 通訊"], days_ago=2)
    refresh_theme_suggestions(db, now=NOW)
    assert _rows(db)["光通訊"].display_name == "光 通訊"


def test_only_done_supported_results_on_active_news_count(db):
    _news(db, ["航太"])
    _news(db, ["航太", "機器人"], unsupported=True)
    _news(db, ["機器人"], status="pending")
    _news(db, ["機器人"], status="skipped_stale")
    _news(db, ["機器人"], news_status="superseded")
    _news(db, [{"theme": "  ", "reason": "空白"}, {"reason": "缺題材"}, "航太"])
    result = refresh_theme_suggestions(db, now=NOW)
    rows = _rows(db)
    assert set(rows) == {"航太"}
    assert rows["航太"].news_count == 2
    assert result["source_results"] == 2


def test_news_date_is_the_taipei_date_and_falls_back_to_collected_at(db):
    # 2026-10-17 17:30 UTC is 2026-10-18 01:30 in Taipei.
    _news(db, ["玻纖布"], published_at=datetime(2026, 10, 17, 17, 30))
    item, _result = _news(db, ["玻纖布"], published_at=None, days_ago=2)
    refresh_theme_suggestions(db, now=NOW)
    row = _rows(db)["玻纖布"]
    assert (row.first_news_date, row.last_news_date) == (
        date(2026, 10, 15),
        date(2026, 10, 18),
    )
    assert item.published_at is None


def test_prompt_versions_stay_separate_and_versions_are_recorded(db):
    item, first = _news(db, ["記憶體"], model="claude-haiku-5-5")
    _item, _other = _news(db, ["記憶體"], model="claude-haiku-5-6")
    _news(db, ["記憶體"], prompt="news_v2", model="claude-sonnet-5-5", item=item)
    refresh_theme_suggestions(db, now=NOW)

    rows = db.scalars(
        select(ThemeSuggestion).order_by(ThemeSuggestion.prompt_version)
    ).all()
    assert [(row.prompt_version, row.theme_key, row.news_count) for row in rows] == [
        ("news_v1", "記憶體", 2),
        ("news_v2", "記憶體", 1),
    ]
    assert rows[0].llm_models_json == ["claude-haiku-5-5", "claude-haiku-5-6"]
    assert rows[1].llm_models_json == ["claude-sonnet-5-5"]
    assert {row.aggregation_version for row in rows} == {AGGREGATION_VERSION}
    assert all(row.computed_at == NOW for row in rows)
    assert _links(db, rows[0])[0].news_llm_result_id == first.id


def test_rerun_is_idempotent_and_only_changed_rows_are_rewritten(db):
    _news(db, ["AI 伺服器"], days_ago=1)
    _news(db, ["散熱"], days_ago=1)
    item, result = _news(db, ["散熱", "無人機"])
    refresh_theme_suggestions(db, now=NOW)
    before = _snapshot(db)

    again = refresh_theme_suggestions(db, now=NOW + timedelta(days=1))
    assert (again["inserted"], again["updated"], again["deleted"]) == (0, 0, 0)
    assert _snapshot(db) == before

    # A new item changes only its suggestion; a result turning unsupported
    # removes its links and a suggestion left without news.
    _news(db, ["散熱"], days_ago=0)
    result.ai_unsupported = True
    db.commit()
    later = NOW + timedelta(days=2)
    changed = refresh_theme_suggestions(db, now=later)
    rows = _rows(db)
    assert (changed["inserted"], changed["updated"], changed["deleted"]) == (0, 1, 1)
    assert set(rows) == {"ai伺服器", "散熱"}
    assert rows["散熱"].news_count == 2 and rows["散熱"].computed_at == later
    assert rows["ai伺服器"].computed_at == NOW
    assert item.id not in {link.news_item_id for link in _links(db, rows["散熱"])}


def test_existing_theme_or_industry_name_is_marked_not_new(db):
    db.add_all(
        [
            ThemeGroup(
                id="official-industry-semi",
                name="Industry · Semiconductor",
                group_type="official_industry",
                display_name_zh="半導體",
                active=True,
            ),
            ThemeGroup(
                id="theme-cpo",
                name="矽光子",
                group_type="theme",
                display_name_zh="CPO 矽光子",
                active=True,
            ),
            ThemeGroup(
                id="official-industry-old",
                name="Industry · Old",
                group_type="official_industry",
                display_name_zh="航運",
                active=False,
            ),
            ThemeGroup(
                id="candidate-x",
                name="候選",
                group_type="theme_candidate",
                display_name_zh="無人機",
                active=False,
            ),
            ThemeGroup(
                id="etf-x",
                name="ETF",
                group_type="etf",
                display_name_zh="高股息",
                active=True,
            ),
        ]
    )
    db.commit()
    _news(db, ["半導體", "矽光子", "CPO矽光子", "航運", "無人機", "高股息"])
    result = refresh_theme_suggestions(db, now=NOW)
    matched = {key: row.matched_group_id for key, row in _rows(db).items()}
    assert matched == {
        "半導體": "official-industry-semi",
        "矽光子": "theme-cpo",
        "cpo矽光子": "theme-cpo",
        "航運": None,
        "無人機": None,
        "高股息": None,
    }
    assert (result["new_themes"], result["matched_existing"]) == (3, 3)
    # Nothing is written to the group tables.
    assert db.scalar(select(ThemeGroup).where(ThemeGroup.id.like("%無人機%"))) is None
    assert len(db.scalars(select(ThemeGroup)).all()) == 5


def test_run_without_the_table_fails_with_a_reason(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    monkeypatch.setattr(theme_suggestions, "SessionLocal", lambda: Session(engine))
    assert theme_suggestions.run_theme_suggestions() == {
        "status": "failed",
        "reason": "theme_suggestions_table_missing_run_init_db",
    }
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def test_api_lists_new_themes_first_by_news_count_with_versions(db, client):
    db.add(
        ThemeGroup(
            id="official-industry-semi",
            name="Industry · Semiconductor",
            group_type="official_industry",
            display_name_zh="半導體",
            active=True,
        )
    )
    db.commit()
    for days_ago in range(7):
        _news(db, ["無人機", "半導體"], days_ago=days_ago)
    _news(db, ["液冷"], days_ago=0)
    _news(db, ["液冷"], days_ago=1)
    _news(db, ["德州投資"], days_ago=0)
    _news(db, ["石化"], days_ago=3)
    refresh_theme_suggestions(db, now=NOW)

    body = client.get("/api/theme-suggestions").json()
    assert [item["display_name"] for item in body["items"]] == [
        "無人機",
        "液冷",
        "德州投資",
        "石化",
    ]
    first = body["items"][0]
    assert first["status"] == "pending_verification" and first["inference"] is True
    assert first["confidence"] == "not_provided"
    assert (first["news_count"], first["first_news_date"], first["last_news_date"]) == (
        7,
        "2026-10-11",
        "2026-10-17",
    )
    assert (
        first["prompt_version"],
        first["aggregation_version"],
        first["llm_models"],
    ) == (
        "news_v1",
        AGGREGATION_VERSION,
        ["claude-haiku-5-5"],
    )
    assert first["matched_group"] is None
    # Newest five news, each with its own wording and reason.
    assert len(first["news"]) == 5
    assert [news["news_date"] for news in first["news"]] == [
        "2026-10-17",
        "2026-10-16",
        "2026-10-15",
        "2026-10-14",
        "2026-10-13",
    ]
    assert set(first["news"][0]) == {
        "news_id",
        "title",
        "source_name",
        "news_date",
        "theme_text",
        "reason",
    }
    assert first["news"][0]["reason"] == "無人機理由"
    meta = body["meta"]
    assert (meta["total"], meta["matched_total"], meta["include_matched"]) == (
        4,
        1,
        False,
    )
    assert meta["updated_at"] == "2026-10-18T01:00:00+00:00"

    limited = client.get("/api/theme-suggestions", params={"limit": 1}).json()
    assert [item["display_name"] for item in limited["items"]] == ["無人機"]
    assert limited["meta"]["total"] == 4

    matched = client.get(
        "/api/theme-suggestions", params={"include_matched": True}
    ).json()
    semi = next(item for item in matched["items"] if item["display_name"] == "半導體")
    assert semi["matched_group"] == {
        "group_id": "official-industry-semi",
        "name": "半導體",
        "group_type": "official_industry",
    }
    assert matched["meta"]["total"] == 5

    detail = client.get(f"/api/theme-suggestions/{first['id']}").json()
    assert len(detail["news"]) == 7
    assert client.get("/api/theme-suggestions/999999").status_code == 404


def test_api_is_empty_before_the_first_run(client):
    body = client.get("/api/theme-suggestions").json()
    assert body["items"] == []
    assert (body["meta"]["total"], body["meta"]["updated_at"]) == (0, None)


# Timestamps written below (#376). `frozen_utcnow` (conftest) makes app.clock answer one
# instant to every caller, so a stamp taken from local time or the real clock stores a
# value other than the one asserted here.


def test_suggestions_are_computed_at_the_clock(db, frozen_utcnow):
    first = frozen_utcnow.at
    _news(db, ["AI 伺服器"], days_ago=1)
    _news(db, ["散熱"], days_ago=1)
    refresh_theme_suggestions(db)
    assert {row.computed_at for row in _rows(db).values()} == {first}

    # Only the suggestion whose content changed takes the new instant.
    _news(db, ["AI 伺服器"], days_ago=0)
    later = first + timedelta(hours=3)
    frozen_utcnow.at = later
    refresh_theme_suggestions(db)
    rows = _rows(db)
    assert rows["ai伺服器"].computed_at == later
    assert rows["散熱"].computed_at == first
