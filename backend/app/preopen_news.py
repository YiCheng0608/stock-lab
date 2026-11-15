"""The pre-open check of the today list's overnight news (Issue #755).

Each trading day before the open, ``worker.preopen`` looks again at the list the
page shows, the run ``app.candidate_runs.read_run`` gives for the session before,
and stores per candidate the news its ``daily`` had not seen
(``preopen_news_checks``, one row per candidate):

- **Window** (#755 decision 6888598143, A): collected after the list's
  ``candidate_runs.computed_at``, right after ``worker.candidates._news_inputs`` read
  the news, so the items not yet in the database then (published from 20:00 and
  collected by the 22:00 news run, for one); and published from the list date's
  00:00 Taipei up to the check. An item of a date only (``time_precision=date``)
  counts by its ``event_date``, from the list date to the check's Taipei date.
  Collected after the check is not counted either.
- **Relation**: the stock page's news list rule (``api._news_symbol_filter``): the
  bare code or ``exchange:code`` in ``news_items.symbols_json``. AI symbol
  candidates do not link an item (they do not on the stock page either).
  A story several feeds carry (the same canonical key, dedupe cluster or content hash)
  counts once per stock, as /api/news lists it.
- **AI direction**: the done result of the current prompt (``news_llm.done_results``,
  as the news cards read it), unsupported reads ``unknown``; without one the item is
  listed as not judged yet (``None``). Kept as it was at the check.

Display only: no score, rank or list condition reads it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import delete, literal_column, or_, select
from sqlalchemy.orm import Session

from .models import (
    CandidateRun,
    DailyCandidate,
    Instrument,
    NewsItem,
    PreopenNewsCheck,
)

DIRECTIONS = ("positive", "negative", "mixed", "unknown")
TAIPEI_OFFSET = timedelta(hours=8)
# The page's definition of 隔夜新聞 (UI_COPY_SPEC §10).
DEFINITION = "名單產生之後才收到的新聞"


def _prompt():
    # worker.news_llm is the writer of the results; imported here as app.api does.
    from worker.news_llm import PROMPT_VERSION, done_results

    return PROMPT_VERSION, done_results


def _taipei_day_start_utc(day: date) -> datetime:
    """The UTC-naive instant of DAY's 00:00 Taipei (news instants are UTC-naive)."""

    return datetime.combine(day, time.min) - TAIPEI_OFFSET


def _in_window(item: NewsItem, list_date: date, checked_at: datetime) -> bool:
    if item.time_precision == "datetime":
        return (
            item.display_time is not None
            and _taipei_day_start_utc(list_date) <= item.display_time <= checked_at
        )
    if item.time_precision == "date":
        day = item.event_date or (
            item.display_time.date() if item.display_time else None
        )
        return (
            day is not None and list_date <= day <= (checked_at + TAIPEI_OFFSET).date()
        )
    return False


def direction_of(result: Any) -> str | None:
    """The stored direction of a done result; None when there is none."""

    if result is None:
        return None
    if result.ai_unsupported or result.ai_impact_direction not in DIRECTIONS:
        return "unknown"
    return result.ai_impact_direction


def overnight_news(
    db: Session, run: CandidateRun, checked_at: datetime
) -> dict[int, list[tuple[NewsItem, str | None]]]:
    """Per candidate instrument id, its overnight news with the AI direction, oldest first.

    ``checked_at`` is UTC-naive. A list computed after it has no window: nothing.
    """

    candidates = db.execute(
        select(DailyCandidate.instrument_id, Instrument.exchange, Instrument.symbol)
        .join(Instrument, Instrument.id == DailyCandidate.instrument_id)
        .where(DailyCandidate.candidate_run_id == run.id)
    ).all()
    out: dict[int, list[tuple[NewsItem, str | None]]] = {
        row.instrument_id: [] for row in candidates
    }
    if run.computed_at is None or run.computed_at >= checked_at:
        return out
    by_token: dict[str, list[int]] = {}
    for row in candidates:
        by_token.setdefault(row.symbol, []).append(row.instrument_id)
        by_token.setdefault(f"{row.exchange}:{row.symbol}", []).append(
            row.instrument_id
        )
    items = db.scalars(
        select(NewsItem)
        .where(
            # A unary + keeps SQLite off ix_news_items_status, which matches nearly every
            # row, so that it reads ix_news_items_collected_at (review 6889365957).
            literal_column("+news_items.status") == "active",
            or_(
                NewsItem.time_consistency.is_(None),
                NewsItem.time_consistency != "conflict",
            ),
            NewsItem.collected_at > run.computed_at,
            NewsItem.collected_at <= checked_at,
        )
        .order_by(NewsItem.display_time, NewsItem.id)
    ).all()
    items = [item for item in items if _in_window(item, run.trading_date, checked_at)]
    linked: list[tuple[NewsItem, set[int]]] = []
    for item in items:
        ids = {
            instrument_id
            for token in item.symbols_json or []
            for instrument_id in by_token.get(str(token), ())
        }
        if ids:
            linked.append((item, ids))
    version, done_results = _prompt()
    results = done_results(db, [item.id for item, _ in linked], version)
    # One story copied by several feeds counts once for a stock, as /api/news lists it:
    # the same canonical key, dedupe cluster or content hash as an earlier item of the
    # stock is skipped (review 6889365957).
    seen: dict[int, set[str]] = {instrument_id: set() for instrument_id in out}
    for item, ids in linked:
        direction = direction_of(results.get(item.id))
        keys = {
            value
            for value in (item.canonical_key, item.dedupe_cluster_id, item.content_hash)
            if value
        }
        for instrument_id in ids:
            if keys & seen[instrument_id]:
                continue
            seen[instrument_id] |= keys
            out[instrument_id].append((item, direction))
    return out


def check_rows(
    db: Session, run: CandidateRun, checked_at: datetime
) -> list[PreopenNewsCheck]:
    """The rows of one check of RUN at CHECKED_AT (UTC-naive), not yet added."""

    version, _ = _prompt()
    news = overnight_news(db, run, checked_at)
    rows = []
    for candidate in db.scalars(
        select(DailyCandidate)
        .where(DailyCandidate.candidate_run_id == run.id)
        .order_by(DailyCandidate.rank)
    ):
        entries = news.get(candidate.instrument_id, [])
        counts = {name: 0 for name in DIRECTIONS}
        unscored = 0
        for _, direction in entries:
            if direction is None:
                unscored += 1
            else:
                counts[direction] += 1
        rows.append(
            PreopenNewsCheck(
                list_date=run.trading_date,
                candidate_run_id=run.id,
                instrument_id=candidate.instrument_id,
                rank=candidate.rank,
                window_start=run.computed_at,
                checked_at=checked_at,
                news_count=len(entries),
                unscored=unscored,
                news_json=[
                    {"news_id": item.id, "direction": direction}
                    for item, direction in entries
                ],
                prompt_version=version,
                **counts,
            )
        )
    return rows


def stored_check(db: Session, list_date: date) -> list[PreopenNewsCheck]:
    return list(
        db.scalars(
            select(PreopenNewsCheck)
            .where(PreopenNewsCheck.list_date == list_date)
            .order_by(PreopenNewsCheck.rank)
        )
    )


def replace_check(db: Session, run: CandidateRun, rows: list[PreopenNewsCheck]) -> None:
    """Write ROWS as the list date's check, replacing a stored one (no commit)."""

    db.execute(
        delete(PreopenNewsCheck).where(PreopenNewsCheck.list_date == run.trading_date)
    )
    db.flush()
    db.add_all(rows)
    db.flush()


def _utc(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def list_view(
    db: Session, run: CandidateRun
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """``/api/candidates``' ``preopen_check`` and each item's ``preopen_news``.

    A check of another run of the date (the list recomputed after it) is not this
    list's: the list reads ``not_checked``, never an older list's result.
    """

    rows = [
        row
        for row in stored_check(db, run.trading_date)
        if row.candidate_run_id == run.id
    ]
    if not rows:
        return {
            "status": "not_checked",
            "definition": DEFINITION,
            "checked_at": None,
            "window_start": None,
            "instruments_with_news": 0,
        }, {}
    ids = {entry["news_id"] for row in rows for entry in row.news_json or []}
    items = (
        {
            item.id: item
            for item in db.scalars(select(NewsItem).where(NewsItem.id.in_(ids)))
        }
        if ids
        else {}
    )
    per: dict[int, dict[str, Any]] = {}
    for row in rows:
        news = []
        for entry in row.news_json or []:
            item = items.get(entry["news_id"])
            if item is None:
                continue
            news.append(
                {
                    "id": str(item.id),
                    "title": item.title,
                    "display_time": _utc(item.display_time)
                    if item.time_precision == "datetime"
                    else None,
                    "event_date": (
                        item.event_date
                        or (item.display_time.date() if item.display_time else None)
                    ).isoformat()
                    if item.time_precision == "date"
                    and (item.event_date or item.display_time)
                    else None,
                    "time_precision": item.time_precision,
                    "source_name": item.source_name,
                    "source_url": item.source_url,
                    "direction": entry.get("direction"),
                }
            )
        per[row.instrument_id] = {
            "count": row.news_count,
            "positive": row.positive,
            "negative": row.negative,
            "mixed": row.mixed,
            "unknown": row.unknown,
            "unscored": row.unscored,
            "items": news,
        }
    first = rows[0]
    return {
        "status": "checked",
        "definition": DEFINITION,
        "checked_at": _utc(first.checked_at),
        "window_start": _utc(first.window_start),
        "instruments_with_news": sum(1 for row in rows if row.news_count),
    }, per
