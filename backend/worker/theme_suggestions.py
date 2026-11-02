"""Aggregate news LLM theme candidates into suggestions awaiting review.

Reads the ``theme_candidates`` of ``news_llm_results`` that are ``done`` and
not ``unsupported``, on active news items, and merges them by normalized theme
name (``app.theme_suggestions.theme_key``) separately per prompt version:
distinct news count, first and last news date (Taipei date of published_at,
else collected_at), the models involved and one link per news item with the
LLM's wording and reason.  A suggestion whose name equals an active theme or
official industry is kept with ``matched_group_id`` (not a new theme).

Every run recomputes from all results and writes only differences, so a rerun
on the same results changes nothing.  Keys and links that no longer appear are
deleted.  Nothing is written to theme_groups, group_memberships or the theme
table file, and no suggestion is ever scored or ranked.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import inspect, or_, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    NewsItem,
    NewsLlmResult,
    ThemeGroup,
    ThemeSuggestion,
    ThemeSuggestionNews,
)
from app.theme_suggestions import (
    AGGREGATION_VERSION,
    MATCHED_GROUP_TYPES,
    STATUS_PENDING,
    theme_key,
)

TAIPEI_OFFSET = timedelta(hours=8)


@dataclass
class _Link:
    news_item_id: int
    news_llm_result_id: int
    theme_text: str
    reason: str | None
    news_date: date


@dataclass
class _Suggestion:
    prompt_version: str
    key: str
    links: dict[int, _Link] = field(default_factory=dict)
    spellings: Counter[str] = field(default_factory=Counter)
    # First (news date, news id) a spelling was seen, for ties.
    first_seen: dict[str, tuple[date, int]] = field(default_factory=dict)
    models: set[str] = field(default_factory=set)

    def fields(self, matched_group_id: str | None) -> dict[str, Any]:
        dates = [link.news_date for link in self.links.values()]
        display = min(
            self.spellings,
            key=lambda name: (-self.spellings[name], self.first_seen[name], name),
        )
        return {
            "display_name": display,
            "aggregation_version": AGGREGATION_VERSION,
            "llm_models_json": sorted(self.models),
            "news_count": len(self.links),
            "first_news_date": min(dates),
            "last_news_date": max(dates),
            "matched_group_id": matched_group_id,
            "status": STATUS_PENDING,
        }


def _taipei_date(value: datetime) -> date:
    # published_at / collected_at are UTC-naive.
    return (value + TAIPEI_OFFSET).date()


def collect_suggestions(db: Session) -> tuple[dict[tuple[str, str], _Suggestion], int]:
    """Group done, supported results by (prompt version, theme key)."""

    rows = db.execute(
        select(NewsLlmResult, NewsItem)
        .join(NewsItem, NewsItem.id == NewsLlmResult.news_item_id)
        .where(
            NewsLlmResult.llm_status == "done",
            or_(
                NewsLlmResult.ai_unsupported.is_(None),
                NewsLlmResult.ai_unsupported.is_(False),
            ),
            NewsItem.status == "active",
        )
        .order_by(NewsLlmResult.id)
    ).all()
    suggestions: dict[tuple[str, str], _Suggestion] = {}
    for result, news in rows:
        moment = news.published_at or news.collected_at
        if moment is None:
            continue
        news_date = _taipei_date(moment)
        for candidate in result.ai_theme_candidates_json or []:
            if not isinstance(candidate, dict) or not isinstance(
                candidate.get("theme"), str
            ):
                continue
            text = candidate["theme"].strip()
            key = theme_key(text)
            if not key:
                continue
            item = suggestions.setdefault(
                (result.prompt_version, key), _Suggestion(result.prompt_version, key)
            )
            if news.id in item.links:
                # The same theme twice in one item (other spelling) counts once.
                continue
            reason = candidate.get("reason")
            item.links[news.id] = _Link(
                news_item_id=news.id,
                news_llm_result_id=result.id,
                theme_text=text,
                reason=reason if isinstance(reason, str) else None,
                news_date=news_date,
            )
            item.spellings[text] += 1
            item.first_seen[text] = min(
                item.first_seen.get(text, (news_date, news.id)), (news_date, news.id)
            )
            if result.llm_model:
                item.models.add(result.llm_model)
    return suggestions, len(rows)


def matched_group_ids(db: Session) -> dict[str, str]:
    """Normalized name -> id of an active theme or official industry."""

    groups = db.scalars(
        select(ThemeGroup).where(
            ThemeGroup.active.is_(True), ThemeGroup.group_type.in_(MATCHED_GROUP_TYPES)
        )
    ).all()
    order = {group_type: index for index, group_type in enumerate(MATCHED_GROUP_TYPES)}
    matched: dict[str, str] = {}
    for group in sorted(groups, key=lambda row: (order[row.group_type], row.id)):
        for name in (group.display_name_zh, group.name):
            if name and theme_key(name):
                matched.setdefault(theme_key(name), group.id)
    return matched


def _link_fields(link: _Link) -> dict[str, Any]:
    return {
        "news_llm_result_id": link.news_llm_result_id,
        "theme_text": link.theme_text,
        "reason": link.reason,
        "news_date": link.news_date,
    }


def _apply(row: Any, values: dict[str, Any]) -> bool:
    changed = False
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed = True
    return changed


def _sync_links(
    db: Session, suggestion: ThemeSuggestion, links: dict[int, _Link]
) -> bool:
    stored = {
        row.news_item_id: row
        for row in db.scalars(
            select(ThemeSuggestionNews).where(
                ThemeSuggestionNews.suggestion_id == suggestion.id
            )
        ).all()
    }
    changed = False
    for news_item_id, row in stored.items():
        if news_item_id not in links:
            db.delete(row)
            changed = True
    for news_item_id, link in links.items():
        row = stored.get(news_item_id)
        if row is None:
            db.add(
                ThemeSuggestionNews(
                    suggestion_id=suggestion.id,
                    news_item_id=news_item_id,
                    **_link_fields(link),
                )
            )
            changed = True
        elif _apply(row, _link_fields(link)):
            changed = True
    return changed


def refresh_theme_suggestions(
    db: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """Recompute every suggestion; rows change only when their content does."""

    computed_at = now or utcnow()
    suggestions, source_results = collect_suggestions(db)
    matched = matched_group_ids(db)
    stored = {
        (row.prompt_version, row.theme_key): row
        for row in db.scalars(select(ThemeSuggestion)).all()
    }
    counts = Counter()
    for key, row in stored.items():
        if key not in suggestions:
            for link in db.scalars(
                select(ThemeSuggestionNews).where(
                    ThemeSuggestionNews.suggestion_id == row.id
                )
            ).all():
                db.delete(link)
            # No ORM relationship orders the deletes; links go first.
            db.flush()
            db.delete(row)
            counts["deleted"] += 1
    for key in sorted(suggestions):
        item = suggestions[key]
        values = item.fields(matched.get(item.key))
        row = stored.get(key)
        if row is None:
            row = ThemeSuggestion(
                prompt_version=item.prompt_version,
                theme_key=item.key,
                computed_at=computed_at,
                **values,
            )
            db.add(row)
            db.flush()
            _sync_links(db, row, item.links)
            counts["inserted"] += 1
            continue
        changed = _apply(row, values)
        changed = _sync_links(db, row, item.links) or changed
        if changed:
            row.computed_at = computed_at
            counts["updated"] += 1
    db.commit()
    new_themes = sum(
        1 for item in suggestions.values() if matched.get(item.key) is None
    )
    return {
        "status": "success",
        "aggregation_version": AGGREGATION_VERSION,
        "source_results": source_results,
        "records": len(suggestions),
        "new_themes": new_themes,
        "matched_existing": len(suggestions) - new_themes,
        "links": sum(len(item.links) for item in suggestions.values()),
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "deleted": counts["deleted"],
    }


def run_theme_suggestions(
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    """Refresh with a new session; daily passes ``pipeline.SessionLocal`` like its other steps."""

    # Like the news batches, no init_db here; run init-db first on a new DB.
    with (session_factory or SessionLocal)() as db:
        if not inspect(db.get_bind()).has_table(ThemeSuggestion.__tablename__):
            return {
                "status": "failed",
                "reason": "theme_suggestions_table_missing_run_init_db",
            }
        return refresh_theme_suggestions(db)
