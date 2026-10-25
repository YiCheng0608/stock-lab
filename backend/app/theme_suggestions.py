"""News theme suggestions awaiting review (``/api/theme-suggestions``).

``worker.theme_suggestions`` aggregates the ``theme_candidates`` of done
news_llm_results into ``theme_suggestions`` / ``theme_suggestion_news``; this
module holds the shared name normalization and only reads the stored rows.
Suggestions are LLM inference: never scored, ranked or written to
theme_groups, and always shown as pending verification.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import NewsItem, ThemeGroup, ThemeSuggestion, ThemeSuggestionNews

AGGREGATION_VERSION = "theme_suggestions_v1"
STATUS_PENDING = "pending_verification"
# Existing product groups a suggestion is compared with by normalized name.
MATCHED_GROUP_TYPES = ("theme", "official_industry")
# news_v1 and news_v2 theme candidates carry no confidence (only symbol
# candidates do).
CONFIDENCE_NOT_PROVIDED = "not_provided"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
NEWS_PER_SUGGESTION = 5

_WHITESPACE = re.compile(r"\s+")


def theme_key(name: str) -> str:
    """Merge key: NFKC, all whitespace removed, casefolded; no synonyms."""

    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", name)).casefold()


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _utc(value: datetime | None) -> str | None:
    # computed_at is stored UTC-naive; send it with its offset.
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _matched_groups(db: Session, ids: set[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = db.scalars(select(ThemeGroup).where(ThemeGroup.id.in_(ids))).all()
    return {
        row.id: {
            "group_id": row.id,
            "name": row.display_name_zh or row.name,
            "group_type": row.group_type,
        }
        for row in rows
    }


def _news(
    db: Session, suggestion_ids: list[int], per_suggestion: int | None
) -> dict[int, list[dict[str, Any]]]:
    if not suggestion_ids:
        return {}
    rows = db.execute(
        select(ThemeSuggestionNews, NewsItem)
        .join(NewsItem, NewsItem.id == ThemeSuggestionNews.news_item_id)
        .where(ThemeSuggestionNews.suggestion_id.in_(suggestion_ids))
        .order_by(
            ThemeSuggestionNews.suggestion_id,
            ThemeSuggestionNews.news_date.desc(),
            ThemeSuggestionNews.news_item_id.desc(),
        )
    ).all()
    result: dict[int, list[dict[str, Any]]] = {}
    for link, news in rows:
        items = result.setdefault(link.suggestion_id, [])
        if per_suggestion is None or len(items) < per_suggestion:
            items.append(
                {
                    "news_id": news.id,
                    "title": news.title,
                    "source_name": news.source_name,
                    "news_date": _date(link.news_date),
                    "theme_text": link.theme_text,
                    "reason": link.reason,
                }
            )
    return result


def suggestion_list(
    db: Session,
    *,
    include_matched: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Stored suggestions, most news first; new themes only unless asked."""

    query = select(ThemeSuggestion).where(ThemeSuggestion.status == STATUS_PENDING)
    if not include_matched:
        query = query.where(ThemeSuggestion.matched_group_id.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    matched_total = (
        db.scalar(
            select(func.count()).where(
                ThemeSuggestion.status == STATUS_PENDING,
                ThemeSuggestion.matched_group_id.is_not(None),
            )
        )
        or 0
    )
    rows = db.scalars(
        query.order_by(
            ThemeSuggestion.news_count.desc(),
            ThemeSuggestion.last_news_date.desc(),
            ThemeSuggestion.theme_key,
            ThemeSuggestion.prompt_version,
        ).limit(limit)
    ).all()
    news = _news(db, [row.id for row in rows], NEWS_PER_SUGGESTION)
    groups = _matched_groups(
        db, {row.matched_group_id for row in rows if row.matched_group_id}
    )
    items = [_item(row, groups, news) for row in rows]
    updated_at = db.scalar(select(func.max(ThemeSuggestion.computed_at)))
    return {
        "items": items,
        "meta": {
            "total": total,
            "limit": limit,
            "include_matched": include_matched,
            "matched_total": matched_total,
            "news_per_suggestion": NEWS_PER_SUGGESTION,
            "aggregation_version": AGGREGATION_VERSION,
            "updated_at": _utc(updated_at),
            "sort": "news_count desc, last_news_date desc, theme_key asc",
        },
    }


def suggestion_detail(db: Session, suggestion_id: int) -> dict[str, Any] | None:
    """One stored suggestion with all of its news."""

    row = db.get(ThemeSuggestion, suggestion_id)
    if row is None:
        return None
    groups = _matched_groups(
        db, {row.matched_group_id} if row.matched_group_id else set()
    )
    return _item(row, groups, _news(db, [row.id], None))


def _item(
    row: ThemeSuggestion,
    groups: dict[str, dict[str, Any]],
    news: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "id": row.id,
        "theme_key": row.theme_key,
        "display_name": row.display_name,
        "status": row.status,
        "inference": True,
        "news_count": row.news_count,
        "first_news_date": _date(row.first_news_date),
        "last_news_date": _date(row.last_news_date),
        "confidence": CONFIDENCE_NOT_PROVIDED,
        "matched_group": groups.get(row.matched_group_id)
        if row.matched_group_id
        else None,
        "prompt_version": row.prompt_version,
        "aggregation_version": row.aggregation_version,
        "llm_models": list(row.llm_models_json or []),
        "computed_at": _utc(row.computed_at),
        "news": news.get(row.id, []),
    }
