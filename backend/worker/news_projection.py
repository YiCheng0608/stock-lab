"""Project every official Event into the news once (``worker.cli news-project``).

The worker projects before committing its own Event and membership writes,
and the news GETs project when the stored fingerprint no longer matches
(Issue #476).  Run this after deploying a version that bumps
``NEWS_PROJECTION_VERSION``, so the first page view does not pay for it.
"""

from __future__ import annotations

from typing import Any

from app.models import NewsProjectionState
from app.news import NEWS_PROJECTION_STATE_KEY, NEWS_PROJECTION_VERSION, project_news
from worker import pipeline


def run_news_project() -> dict[str, Any]:
    with pipeline.SessionLocal() as db:
        changed = project_news(db)
        state = db.get(NewsProjectionState, NEWS_PROJECTION_STATE_KEY)
        result = {
            "status": "success",
            "version": NEWS_PROJECTION_VERSION,
            "changed": changed,
            "fingerprint": state.fingerprint if state else None,
        }
        db.commit()
    return result
