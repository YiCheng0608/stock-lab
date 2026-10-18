"""News batch: fetch the registered feeds, dedupe, relate by rule, store NewsItem rows.

Each source gets its own ingestion run (run_type ``news``).  A failing feed
(HTTP error, rate limit, malformed XML) is recorded on that run and the other
feeds still write.  Existing items are never rewritten, so a rerun keeps the
first stored ``published_at``; the one exception is the non-market filter
(news_sources.exclusion_reason), which also moves matching ``active`` rows to
``excluded``.  Excluded items are stored, never deleted, and the reason is in
the run metadata.  ``impact_direction`` is always ``unknown``; LLM summaries
and direction calls are stored apart by worker.news_llm.

Every write (opening a run, storing one feed, closing a run) is one unit that
is redone after ``database is locked``: another job's long write transaction
can outlast the 30 s busy timeout.  Only after the retries does the feed (or
the source) count as failed.
"""

from __future__ import annotations

import hashlib
import json
import re
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable, TypeVar

from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import IngestionRun, Instrument, NewsItem, ThemeGroup
from app.news import is_verified_theme

from . import sources
from .news_sources import (
    FILTER_VERSION,
    MAX_ITEM_ID_LENGTH,
    NEWS_SOURCES,
    TAIPEI,
    FeedEntry,
    FeedResponse,
    Fetcher,
    HttpFeedFetcher,
    NewsSource,
    NewsSourceError,
    check_response,
    exclusion_reason,
    naive_offset_text,
    normalized_title,
    parse_rss,
    raw_feed_payload,
    title_hash,
)
from .pipeline import _upsert_raw_payload

RELATION_METHOD = "rule:exact-name-code/v1"
# A write unit that hits "database is locked" (after the 30 s busy timeout)
# is rolled back and redone this many more times, this many seconds apart.
LOCK_RETRIES = 3
LOCK_RETRY_DELAY_SECONDS = 60.0

T = TypeVar("T")
# A source time later than collection by more than this is a clock or time
# zone error; the item is kept but quarantined as a time conflict.
FUTURE_TOLERANCE = timedelta(minutes=15)

# Names of three or more characters match on their own except these, which
# are also common words or place names.
NAME_ONLY_STOPWORDS = frozenset(
    {"台灣大", "大台北", "新天地", "創業家", "雲嘉南", "新零售", "太空梭", "宅配通"}
)
# Longer phrases that contain a company name but mean something else; they
# take the span, so 中華電視 is not read as 中華電.
NAME_BLOCKERS = frozenset({"中華電視"})
# Theme names too generic to count as an industry mention (綜合 is also part of
# 綜合外電報導).
THEME_STOPWORDS = frozenset({"其他", "綜合"})
# An industry name counts only as an industry word: 半導體股, 金融類股,
# 光電族群, 航運產業, 電子業.  Bare 金融 in 國際金融市場 does not.
THEME_SUFFIXES = ("類股", "族群", "產業", "股", "業")

# Listing markers: -KY, -DR, -創, -KY創, with or without a trailing or leading
# ``*``.  The dash is required, so 群創 and 鈺創 keep their whole name.
_NAME_SUFFIX = re.compile(r"\*?(?:-(?:KY創|KY|DR|創))?\*?$")
_CJK = re.compile(r"[一-鿿]")
_CODE = re.compile(r"(?<![0-9A-Za-z])(\d{4,6})(?![0-9])")
_TICKER_SUFFIX = re.compile(r"[-.](TWO|TW)\b", re.I)
_CODE_PREFIX = re.compile(r"代號[\s:：（(]*$")


def _name_aliases(name: str) -> set[str]:
    base = _NAME_SUFFIX.sub("", name.strip()).strip()
    return {alias for alias in {name.strip().rstrip("*"), base} if len(alias) >= 2}


@dataclass(frozen=True)
class _Stock:
    exchange: str
    symbol: str
    aliases: frozenset[str]

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.symbol}"


class RelationMatcher:
    """Exact rule matching of listed common stocks and official industries.

    - A code counts only with context: the same stock's name in the text, a
      ticker suffix (``2330-TW``), or a preceding ``代號``.  A bare number never
      matches, and a code listed on both exchanges is not resolved by the code
      alone; only the name decides which exchange.
    - A name counts on its own when it has three or more characters, contains
      a CJK character, is not a stopword, and is not inside a longer matched
      name.  Two-character names (often ordinary words) need their code.
    - An official industry display name adds its theme id when it is followed
      by 股／類股／族群／產業／業 and is not inside a company name.
    """

    def __init__(
        self, stocks: Iterable[tuple[str, str, str]], themes: Iterable[tuple[str, str]]
    ):
        self._stocks = [
            _Stock(exchange, symbol, frozenset(_name_aliases(name)))
            for exchange, symbol, name in stocks
        ]
        self._by_code: dict[str, list[_Stock]] = {}
        self._name_only: dict[str, list[_Stock]] = {}
        for stock in self._stocks:
            self._by_code.setdefault(stock.symbol, []).append(stock)
            for alias in stock.aliases:
                if (
                    len(alias) >= 3
                    and _CJK.search(alias)
                    and alias not in NAME_ONLY_STOPWORDS
                ):
                    self._name_only.setdefault(alias, []).append(stock)
        self._all_aliases = {
            alias
            for stock in self._stocks
            for alias in stock.aliases
            if len(alias) >= 2
        }
        self._themes: dict[str, list[str]] = {}
        for theme_id, name in themes:
            if name and name not in THEME_STOPWORDS:
                self._themes.setdefault(name, []).append(theme_id)

    @classmethod
    def from_db(cls, db: Session) -> "RelationMatcher":
        stocks = db.execute(
            select(Instrument.exchange, Instrument.symbol, Instrument.name).where(
                Instrument.instrument_type == "stock",
                Instrument.exchange.in_(("TWSE", "TPEx")),
            )
        ).all()
        themes = [
            (group.id, (group.display_name_zh or "").strip())
            for group in db.scalars(
                select(ThemeGroup).where(ThemeGroup.group_type == "official_industry")
            ).all()
            if is_verified_theme(group)
        ]
        return cls(stocks, themes)

    @staticmethod
    def _longest_spans(text: str, names: Iterable[str]) -> set[str]:
        spans = [
            (match.start(), match.start() + len(name), name)
            for name in names
            for match in re.finditer(re.escape(name), text)
        ]
        return {
            name
            for start, end, name in spans
            if not any(
                s <= start and end <= e and (e - s) > (end - start) for s, e, _ in spans
            )
        }

    def symbols(self, text: str) -> list[str]:
        found: set[str] = set()
        for match in _CODE.finditer(text):
            candidates = self._by_code.get(match.group(1), [])
            if not candidates:
                continue
            named = [
                stock
                for stock in candidates
                if any(alias in text for alias in stock.aliases)
            ]
            if named:
                found.update(stock.key for stock in named)
                continue
            context = _TICKER_SUFFIX.match(text, match.end()) or _CODE_PREFIX.search(
                text, 0, match.start()
            )
            if context and len(candidates) == 1:
                found.add(candidates[0].key)
        present = [name for name in self._name_only if name in text]
        present += [phrase for phrase in NAME_BLOCKERS if phrase in text]
        for name in self._longest_spans(text, present):
            stocks = self._name_only.get(name, [])
            if len(stocks) == 1:
                found.add(stocks[0].key)
        return sorted(found)

    def theme_ids(self, text: str) -> list[str]:
        # An industry name inside a company name (光電 in 台光電股) or inside a
        # longer industry name (電子 in 其他電子業) does not count.
        names = [name for name in self._themes if name in text]
        covering = [
            (match.start(), match.end())
            for phrase in [*names, *(a for a in self._all_aliases if a in text)]
            for match in re.finditer(re.escape(phrase), text)
        ]
        found: set[str] = set()
        for name in names:
            for suffix in THEME_SUFFIXES:
                for match in re.finditer(re.escape(name + suffix), text):
                    start, end = match.start(), match.start() + len(name)
                    if not any(
                        s <= start and end <= e and e - s > end - start
                        for s, e in covering
                    ):
                        found.update(self._themes[name])
        return sorted(found)


def _canonical_key(source: NewsSource, item_id: str) -> str:
    return f"news:{source.source_id}:{title_hash(item_id)}"


def dedupe_cluster_id(entry: FeedEntry, fallback: str) -> str:
    """Same normalised title on the same Taipei calendar day → same cluster."""

    if entry.published_at is not None:
        day = entry.published_at.replace(tzinfo=timezone.utc).astimezone(TAIPEI).date()
    elif entry.event_date is not None:
        day = entry.event_date
    else:
        return fallback
    key = normalized_title(entry.title)
    if not key:
        return fallback
    return f"news-title:{title_hash(f'{day.isoformat()}|{key}')[:32]}"


def _content_hash(source: NewsSource, entry: FeedEntry) -> str:
    payload = {
        "source": source.source_id,
        "item_id": entry.source_item_id,
        "url": entry.url,
        "title": entry.title,
        "summary": entry.summary,
        "time": entry.raw_time,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _temporal(entry: FeedEntry, collected_at: datetime) -> dict[str, Any]:
    if entry.published_at is not None:
        conflict = entry.published_at > collected_at + FUTURE_TOLERANCE
        return {
            "published_at": entry.published_at,
            "event_date": None,
            "display_time": entry.published_at,
            "time_basis": "published",
            "time_precision": "datetime",
            "time_consistency": "conflict" if conflict else "verified",
        }
    if entry.event_date is not None:
        return {
            "published_at": None,
            "event_date": entry.event_date,
            "display_time": datetime.combine(entry.event_date, time.min),
            "time_basis": "event_date",
            "time_precision": "date",
            "time_consistency": "verified",
        }
    return {
        "published_at": None,
        "event_date": None,
        "display_time": None,
        "time_basis": "unverified",
        "time_precision": "none",
        "time_consistency": "unverified",
    }


class _SourceIndex:
    """Existing and in-batch identities of one source (guid key and canonical URL)."""

    def __init__(self, db: Session, source: NewsSource):
        rows = db.execute(
            select(NewsItem.canonical_key, NewsItem.source_url).where(
                NewsItem.canonical_key.like(f"news:{source.source_id}:%")
            )
        ).all()
        self.keys = {key for key, _url in rows}
        self.urls = {url for _key, url in rows if url}

    def seen(self, key: str, url: str) -> bool:
        return key in self.keys or url in self.urls

    def add(self, key: str, url: str) -> None:
        self.keys.add(key)
        self.urls.add(url)


def _store_entries(
    db: Session,
    source: NewsSource,
    entries: list[FeedEntry],
    index: _SourceIndex,
    matcher: RelationMatcher,
    raw_payload_id: int,
    collected_at: datetime,
) -> dict[str, Any]:
    inserted = existing = 0
    excluded: list[dict[str, str]] = []
    for entry in entries:
        key = _canonical_key(source, entry.source_item_id or entry.url)
        if index.seen(key, entry.url):
            existing += 1
            continue
        index.add(key, entry.url)
        text = f"{entry.title}\n{entry.summary or ''}"
        temporal = _temporal(entry, collected_at)
        conflict = temporal["time_consistency"] == "conflict"
        reason = exclusion_reason(source, entry.title, entry.url)
        if reason:
            status = "excluded"
            excluded.append(_excluded_record(key, entry.title, entry.url, reason))
        else:
            status = "quarantined" if conflict else "active"
        symbols = [] if conflict else matcher.symbols(text)
        theme_ids = [] if conflict else matcher.theme_ids(text)
        if symbols:
            scope = "instrument"
        elif theme_ids:
            scope = "theme"
        else:
            scope = "market" if source.source_kind == "macro_official" else "unknown"
        db.add(
            NewsItem(
                canonical_key=key,
                dedupe_cluster_id=dedupe_cluster_id(entry, key),
                category=source.category,
                source_kind=source.source_kind,
                source_name=source.source_name,
                source_url=entry.url,
                source_url_kind="item",
                source_item_id=(entry.source_item_id or "")[:MAX_ITEM_ID_LENGTH]
                or None,
                title=entry.title,
                summary=entry.summary,
                language=source.language,
                event_at=None,
                collected_at=collected_at,
                symbols_json=symbols,
                theme_ids_json=theme_ids,
                impact_scope=scope,
                impact_direction="unknown",
                impact_rationale=None,
                impact_method="time_consistency_conflict"
                if conflict
                else RELATION_METHOD,
                confidence="unknown",
                raw_payload_id=raw_payload_id,
                event_id=None,
                content_hash=_content_hash(source, entry),
                status=status,
                **temporal,
            )
        )
        inserted += 1
    db.flush()
    return {
        "inserted": inserted,
        "existing": existing,
        "excluded": len(excluded),
        "excluded_items": excluded,
    }


def _excluded_record(key: str, title: str, url: str, reason: str) -> dict[str, str]:
    return {"canonical_key": key, "title": title, "url": url, "reason": reason}


def _exclude_existing(db: Session, source: NewsSource) -> list[dict[str, str]]:
    """Move stored ``active`` items of the source that the filter now excludes.

    Not committed here: the caller commits the status change together with the
    list in the run metadata, so a crash cannot leave moved rows unrecorded.
    """

    rows = db.scalars(
        select(NewsItem).where(
            NewsItem.canonical_key.like(f"news:{source.source_id}:%"),
            NewsItem.status == "active",
        )
    ).all()
    moved: list[dict[str, str]] = []
    for item in rows:
        url = item.source_url or ""
        reason = exclusion_reason(source, item.title, url)
        if reason:
            item.status = "excluded"
            moved.append(_excluded_record(item.canonical_key, item.title, url, reason))
    return moved


def _is_locked(exc: BaseException) -> bool:
    return (
        isinstance(exc, OperationalError) and "database is locked" in str(exc).lower()
    )


def _sleep(seconds: float) -> None:
    _time.sleep(seconds)


def _write_unit(
    db: Session, unit: Callable[[], T], on_retry: Callable[[], None] | None = None
) -> T:
    """Run ``unit`` (which ends in a commit); redo it after ``database is locked``.

    The rollback discards the unit's pending changes, so ``unit`` must redo all
    of them; ``on_retry`` rebuilds any in-memory state they touched.
    """

    for attempt in range(LOCK_RETRIES + 1):
        try:
            return unit()
        except OperationalError as exc:
            if not _is_locked(exc) or attempt == LOCK_RETRIES:
                raise
            db.rollback()
            _sleep(LOCK_RETRY_DELAY_SECONDS)
            if on_retry is not None:
                on_retry()
    raise AssertionError("unreachable")


def _collect_source(
    db: Session,
    source: NewsSource,
    fetch: Fetcher,
    matcher: RelationMatcher,
    run_date: date,
) -> dict[str, Any]:
    def open_run() -> IngestionRun:
        row = IngestionRun(
            run_type="news",
            source=source.source_id,
            run_date=run_date,
            status="running",
            records=0,
            started_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        return row

    try:
        run = _write_unit(db, open_run)
    except OperationalError as exc:
        # Nothing could be written for this source; the CLI output and the
        # job log still carry the failure.
        db.rollback()
        return {
            "source": source.source_id,
            "run_id": None,
            "status": "failed",
            "error": f"run not recorded: {type(exc).__name__}: {exc}",
            "existing_excluded": [],
            "feeds": [],
        }
    metadata: dict[str, Any] = {
        "source_name": source.source_name,
        "category": source.category,
        "source_kind": source.source_kind,
        "naive_time_offset": naive_offset_text(source.naive_offset),
    }

    def exclude_existing() -> list[dict[str, str]]:
        moved = _exclude_existing(db, source)
        # The moved rows and their list land in one commit.
        run.metadata_json = {
            **metadata,
            "filter": {"version": FILTER_VERSION, "existing_excluded": moved},
        }
        db.commit()
        return moved

    try:
        existing_excluded = _write_unit(db, exclude_existing)
    except OperationalError as exc:
        db.rollback()
        existing_excluded = []
        metadata["filter_error"] = f"{type(exc).__name__}: {exc}"
    metadata["filter"] = {
        "version": FILTER_VERSION,
        "existing_excluded": existing_excluded,
    }
    index = _SourceIndex(db, source)

    def reset_index() -> None:
        nonlocal index
        index = _SourceIndex(db, source)

    feeds: list[dict[str, Any]] = []
    for feed in source.feeds:
        result: dict[str, Any] = {"feed": feed.key, "endpoint": feed.url}
        collected_at = datetime.utcnow()
        try:
            response: FeedResponse = fetch(feed.url)
            check_response(response)
            raw = sources.capture_payload(
                f"news_{source.source_id}",
                feed.url,
                raw_feed_payload(source, feed, response),
                collected_at.isoformat(),
                collected_at=collected_at,
            )

            def store_raw() -> int:
                raw_id = _upsert_raw_payload(db, run, raw).id
                db.commit()
                return raw_id

            # The capture is kept even when the payload does not parse.
            raw_id = _write_unit(db, store_raw)
            entries, skipped = parse_rss(response.content, source)

            def store_entries() -> dict[str, Any]:
                with db.begin_nested():
                    counts = _store_entries(
                        db, source, entries, index, matcher, raw_id, collected_at
                    )
                db.commit()
                return counts

            counts = _write_unit(db, store_entries, on_retry=reset_index)
            result.update(
                status="success", items=len(entries), skipped=skipped, **counts
            )
        except NewsSourceError as exc:
            db.rollback()
            reset_index()
            result.update(status="failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - one feed must not stop the other sources
            db.rollback()
            reset_index()
            result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        feeds.append(result)
    failed = [item for item in feeds if item["status"] == "failed"]
    status = (
        "failed" if len(failed) == len(feeds) else ("partial" if failed else "success")
    )

    def close_run() -> None:
        run.status = status
        run.records = sum(int(item.get("inserted", 0)) for item in feeds)
        run.error = (
            "; ".join(f"{item['feed']}: {item['error']}" for item in failed) or None
        )
        run.data_as_of = datetime.utcnow().isoformat()
        run.metadata_json = {**metadata, "feeds": feeds}
        run.finished_at = datetime.utcnow()
        db.commit()

    error = None
    try:
        _write_unit(db, close_run)
    except OperationalError as exc:
        # The stored news stays; the run row is left running and the result
        # reports the source as failed.
        db.rollback()
        status = "failed"
        error = f"run result not recorded: {type(exc).__name__}: {exc}"
    result = {
        "source": source.source_id,
        "run_id": run.id,
        "status": status,
        "existing_excluded": existing_excluded,
        "feeds": feeds,
    }
    if error:
        result["error"] = error
    return result


def collect_news(
    db: Session,
    *,
    run_date: date | None = None,
    fetch: Fetcher | None = None,
    news_sources: Iterable[NewsSource] = NEWS_SOURCES,
) -> dict[str, Any]:
    label_date = run_date or datetime.now(TAIPEI).date()
    matcher = RelationMatcher.from_db(db)
    own_fetcher = HttpFeedFetcher() if fetch is None else None
    active_fetch = fetch or own_fetcher
    assert active_fetch is not None
    try:
        results = [
            _collect_source(db, source, active_fetch, matcher, label_date)
            for source in news_sources
        ]
    finally:
        if own_fetcher is not None:
            own_fetcher.close()
    statuses = {item["status"] for item in results}
    if statuses == {"success"}:
        status = "success"
    elif statuses == {"failed"}:
        status = "failed"
    else:
        status = "partial"
    feeds = [feed for item in results for feed in item["feeds"]]
    return {
        "status": status,
        "run_date": label_date.isoformat(),
        "inserted": sum(int(feed.get("inserted", 0)) for feed in feeds),
        "existing": sum(int(feed.get("existing", 0)) for feed in feeds),
        "excluded": sum(int(feed.get("excluded", 0)) for feed in feeds),
        "existing_excluded": sum(len(item["existing_excluded"]) for item in results),
        "failed_feeds": [
            f"{item['source']}/{feed['feed']}"
            for item in results
            for feed in item["feeds"]
            if feed["status"] == "failed"
        ],
        "sources": results,
    }


def run_news_batch(run_date: date | None = None) -> dict[str, Any]:
    # Like the indicator batch, no init_db here; run init-db first on a new DB.
    with SessionLocal() as db:
        if not inspect(db.get_bind()).has_table(NewsItem.__tablename__):
            return {
                "status": "failed",
                "reason": "news_items_table_missing_run_init_db",
            }
        return collect_news(db, run_date=run_date)
