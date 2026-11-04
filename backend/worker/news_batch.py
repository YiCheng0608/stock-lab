"""News batch: fetch the registered feeds, dedupe, relate by rule, store NewsItem rows.

Each source gets its own ingestion run (run_type ``news``).  A failing feed
(HTTP error, rate limit, malformed XML) is recorded on that run and the other
feeds still write.  Existing items are never rewritten, so a rerun keeps the
first stored ``published_at``.  Two exceptions: the non-market filter
(news_sources.exclusion_reason) also moves matching ``active`` rows to
``excluded``, and recent ``active`` rows whose relations come from an older
rule version are related again (``_rerelate_recent``; the old values are kept
in a ``news_relations`` run).  Excluded items are stored, never deleted, and
the reason is in the run metadata.  ``impact_direction`` is always
``unknown``; LLM summaries and direction calls are stored apart by
worker.news_llm.

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
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.clock import utcnow
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

RELATION_METHOD = "rule:exact-name-code/v2"
# Every version of the rule shares this prefix; a stored item whose method has
# the prefix but is not RELATION_METHOD was related by an older version.
RELATION_METHOD_PREFIX = "rule:exact-name-code/"
# Stored items related by an older rule version are related again when their
# source time (or collection time) is this recent, like the LLM's stale window.
RELATION_RERUN_WINDOW = timedelta(days=3)
# The run that keeps the previous relations of rows related again.
RELATION_RUN_TYPE = "news_relations"
# Listed common stocks, including those in their first 60 days (``ipo``).
STOCK_TYPES = ("stock", "ipo")
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
# take the span, so 中華電視 is not read as 中華電, 大華銀投信 (UOB) not as
# 9905 大華 and 愛普生 (Epson) not as 6531 愛普.
NAME_BLOCKERS = frozenset({"中華電視", "大華銀", "愛普生"})
# Holding-company endings of an official short name; the name without them is
# the one the press uses (日月光投控 → 日月光).  It yields to another stock's
# official name: 中光電 stays the (delisted) 5371, not 3718 中光電投控.
HOLDING_SUFFIXES = ("投控", "控股")
# Two-character names that are also ordinary words, places, funds or other
# companies.  Chosen on the 2026-10-20～11-02 domestic news (3,863 items,
# Issue #451): a name is listed when at least half of its new matches there
# were wrong, or when it is a well-known homonym (三星 Samsung, 惠普 HP).  They
# still match next to their code.
TWO_CHAR_STOPWORDS = frozenset(
    {
        "三星",  # Samsung
        "惠普",  # HP
        "統一",  # 統一期貨, 統一投信 funds
        "全家",  # 全家國際餐飲 is 7708; also 全家人
        "全台",  # nationwide
        "材料",
        "冠軍",
        "新產",  # 新產能
        "國產",
        "世界",  # 世界大會
        "世紀",  # 世紀妖股
        "時報",  # 時報記者
        "數字",
        "鳳凰",  # 鳳凰城 Phoenix
        "再生",  # 再生能源
        "大地",  # 大地主
        "海灣",  # Gulf
        # Found in the #451 AC-2 check of the 2026-11-03～04 news:
        "南港",  # the district (台肥：南港廢土)
        "中華",  # 中華民國, 中華隊; a summary cut after 中華(電信)
        # Foreign companies, added by the #457 second review after the
        # pre-registered out-of-sample draw:
        "佳能",  # Canon
        "大宇",  # Daewoo
        "大塚",  # Otsuka
        "康普",  # CommScope
    }
)
# Two-character names that are ordinary words, places or institutions and so
# open title segments as words (新興市場, 全新iPhone, 大量資金, 信義區, 精英人才,
# 光明前景, 美食外送, 大同小異; #457 review).  They count only as a whole
# segment closed by punctuation, a space or the end: 「上詮、全新、前鼎」 and
# 「其中 全新(2455)」 count, 「全新iPhone」 and 「大量資金」 do not.
TWO_CHAR_COMMON_WORDS = frozenset(
    {
        "互動", "中天", "中台", "中工", "光明", "光環", "光譜", "全國", "全域",
        "全新", "典範", "動力", "卓越", "厚生", "地球", "大同", "大成", "大樹",
        "大量", "太子", "太極", "安心", "宏觀", "巨大", "幸福", "建國", "得力",
        "信義", "新建", "新興", "新華", "星雲", "春雨", "東洋", "東華", "正道",
        "海光", "神州", "秋雨", "立德", "精英", "精湛", "精確", "精華", "綠意",
        "綠茵", "綠電", "美食", "至上", "華夏", "華東", "茂林", "藍天", "農林",
        "辣椒", "進階", "遠見", "雙喜", "霹靂", "青雲",
        # Added by the #457 second review after the pre-registered draw:
        # 陽明山, 南亞 (South Asia), 博大精深, 無敵, 泰山 (the district).
        "陽明", "南亞", "博大", "無敵", "泰山",
    }
)  # fmt: skip
# A two-character name counts on its own only for a listed stock (``status``
# active or dormant), and only when no other listed stock has the same name:
# a delisted or moved row (6423 億而得 TWSE ``transferred``) does not make the
# listed one ambiguous.
LISTED_STATUSES = ("active", "dormant")
# Full names (公司名稱 without 股份有限公司) that start with another listed
# stock's two-character name, read as aliases of their own company: 聯華電子 is
# 2303, never 1229 聯華.  Built by tools/research/news_full_name_aliases.py.
FULL_NAME_ALIASES_FILE = (
    Path(__file__).resolve().parents[1] / "data" / "news" / "full_name_aliases.json"
)
# ETF names are matched on their own only from this length: 新台灣 (0060) and
# 富邦科技 (0052) are ordinary phrases.  ETFs need no two-character rule.
ETF_NAME_MIN_LENGTH = 5
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
# ETF codes with a letter class suffix (00981A, 00679B); plain 0050 is a _CODE.
_ETF_CODE = re.compile(r"(?<![0-9A-Za-z])(00\d{2,4}[A-Z])(?![0-9A-Za-z])")
_TICKER_SUFFIX = re.compile(r"[-.](TWO|TW)\b", re.I)
_CODE_PREFIX = re.compile(r"代號[\s:：（(]*$")
# 元大科技市值(原:元大電子): the former name in brackets is not part of the name.
_FORMER_NAME = re.compile(r"[(（]原[:：].*?[)）]$")


def _name_aliases(name: str) -> set[str]:
    base = _NAME_SUFFIX.sub("", name.strip()).strip()
    return {alias for alias in {name.strip().rstrip("*"), base} if len(alias) >= 2}


def _holding_alias(name: str) -> str | None:
    base = _NAME_SUFFIX.sub("", name.strip()).strip()
    for suffix in HOLDING_SUFFIXES:
        if base.endswith(suffix) and len(base) - len(suffix) >= 2:
            return base[: -len(suffix)]
    return None


def _etf_aliases(name: str) -> set[str]:
    current = _FORMER_NAME.sub("", name.strip()).strip()
    return {alias for alias in {name.strip(), current} if len(alias) >= 2}


def _is_two_char_name(alias: str) -> bool:
    return len(alias) == 2 and all(_CJK.match(char) for char in alias)


def _opens_segment(text: str, index: int) -> bool:
    """True at the start of ``text`` or after punctuation, a symbol or a space.

    A letter or digit does not open a segment: 12時報 (a time), 22日成 (a date).
    """

    return index < 0 or not text[index].isalnum()


def _closes_segment(text: str, index: int) -> bool:
    """True at the end of ``text`` or before any character that is not CJK."""

    return index >= len(text) or not _CJK.match(text[index])


def _ends_segment(text: str, index: int) -> bool:
    """True at the end of ``text`` or before punctuation or a symbol.

    Spaces are skipped first, so 「全新 iPhone」 and 「大量 資金」 do not end a
    segment while 「全新 、穩懋」 and a name at the very end do.
    """

    while index < len(text) and text[index].isspace():
        index += 1
    return index >= len(text) or not text[index].isalnum()


def load_full_name_aliases(
    path: Path = FULL_NAME_ALIASES_FILE,
) -> list[tuple[str, str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        (row["exchange"], row["symbol"], row["full_name"]) for row in data["aliases"]
    ]


@dataclass(frozen=True)
class _Stock:
    exchange: str
    symbol: str
    aliases: frozenset[str]
    listed: bool = True

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.symbol}"


class RelationMatcher:
    """Exact rule matching of listed stocks, ETFs and official industries.

    - A code counts only with context: the same stock's name in the text, a
      ticker suffix (``2330-TW``), or a preceding ``代號``.  A bare number never
      matches, and a code listed on both exchanges is not resolved by the code
      alone; only the name decides which exchange.
    - Stock names are the official short name, the name without listing
      markers, the name without a holding-company ending (日月光投控 →
      日月光) unless that is another stock's official name, and the full names
      in FULL_NAME_ALIASES_FILE.  ETF names are the official short name,
      without a bracketed former name.
    - A name counts on its own when it has three or more characters (ETF
      names: ETF_NAME_MIN_LENGTH), contains a CJK character, is not a
      stopword, and is not inside a longer matched name.
    - A two-character name of a listed stock counts on its own only when no
      other listed stock has the same name, it is not a stopword, it is not
      inside a longer name in the text, and it opens a title segment (title
      start, or after punctuation, a symbol or a space) or is a whole segment
      (opened that way and followed by a non-CJK character or the end) in the
      title or summary.  A common-word name (TWO_CHAR_COMMON_WORDS) counts only
      as a whole segment followed by punctuation, a space or the end.
    - An official industry display name adds its theme id when it is followed
      by 股／類股／族群／產業／業 and is not inside a company name.
    """

    def __init__(
        self,
        stocks: Iterable[tuple[str, ...]],
        themes: Iterable[tuple[str, str]],
        etfs: Iterable[tuple[str, str, str]] = (),
        full_names: Iterable[tuple[str, str, str]] = (),
    ):
        # (exchange, symbol, name) or (exchange, symbol, name, status); a row
        # without a status counts as listed.
        stock_rows = [
            (row[0], row[1], row[2], row[3] if len(row) > 3 else "active")
            for row in stocks
        ]
        official = {
            alias for _, _, name, _ in stock_rows for alias in _name_aliases(name)
        }
        extra: dict[tuple[str, str], set[str]] = {}
        for exchange, symbol, full_name in full_names:
            extra.setdefault((exchange, symbol), set()).add(full_name)
        self._stocks = []
        for exchange, symbol, name, status in stock_rows:
            aliases = _name_aliases(name) | extra.get((exchange, symbol), set())
            holding = _holding_alias(name)
            if holding and holding not in official:
                aliases.add(holding)
            self._stocks.append(
                _Stock(
                    exchange,
                    symbol,
                    frozenset(aliases),
                    listed=status in LISTED_STATUSES,
                )
            )
        etf_list = [
            _Stock(exchange, symbol, frozenset(_etf_aliases(name)))
            for exchange, symbol, name in etfs
        ]
        self._by_code: dict[str, list[_Stock]] = {}
        self._name_only: dict[str, list[_Stock]] = {}
        two_char: dict[str, list[_Stock]] = {}
        for stock in self._stocks:
            self._by_code.setdefault(stock.symbol, []).append(stock)
            for alias in stock.aliases:
                if (
                    len(alias) >= 3
                    and _CJK.search(alias)
                    and alias not in NAME_ONLY_STOPWORDS
                ):
                    self._name_only.setdefault(alias, []).append(stock)
                elif _is_two_char_name(alias) and stock.listed:
                    two_char.setdefault(alias, []).append(stock)
        for etf in etf_list:
            self._by_code.setdefault(etf.symbol, []).append(etf)
            for alias in etf.aliases:
                if len(alias) >= ETF_NAME_MIN_LENGTH and _CJK.search(alias):
                    self._name_only.setdefault(alias, []).append(etf)
        # Only a name no other stock shares; 台南 (1473 and 5906 台南-KY) needs
        # its code.
        self._two_char = {
            alias: owners[0]
            for alias, owners in two_char.items()
            if len(owners) == 1 and alias not in TWO_CHAR_STOPWORDS
        }
        self._all_aliases = {
            alias
            for stock in [*self._stocks, *etf_list]
            for alias in stock.aliases
            if len(alias) >= 2
        }
        self._longer_names = (
            {alias for alias in self._all_aliases if len(alias) > 2}
            | NAME_BLOCKERS
            | NAME_ONLY_STOPWORDS
        )
        self._themes: dict[str, list[str]] = {}
        for theme_id, name in themes:
            if name and name not in THEME_STOPWORDS:
                self._themes.setdefault(name, []).append(theme_id)

    @classmethod
    def from_db(cls, db: Session) -> "RelationMatcher":
        stocks = db.execute(
            select(
                Instrument.exchange,
                Instrument.symbol,
                Instrument.name,
                Instrument.status,
            ).where(
                Instrument.instrument_type.in_(STOCK_TYPES),
                Instrument.exchange.in_(("TWSE", "TPEx")),
            )
        ).all()
        etfs = db.execute(
            select(Instrument.exchange, Instrument.symbol, Instrument.name).where(
                Instrument.instrument_type == "etf",
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
        return cls(stocks, themes, etfs, load_full_name_aliases())

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

    def _two_char_keys(self, title: str, summary: str) -> set[str]:
        found: set[str] = set()
        for field, text in (("title", title), ("summary", summary)):
            present = [name for name in self._two_char if name in text]
            if not present:
                continue
            covering = [
                (match.start(), match.end())
                for name in self._longer_names
                if name in text
                for match in re.finditer(re.escape(name), text)
            ]
            for name in present:
                for match in re.finditer(re.escape(name), text):
                    start, end = match.start(), match.end()
                    if any(s <= start and end <= e for s, e in covering):
                        continue
                    if not _opens_segment(text, start - 1):
                        continue
                    if name in TWO_CHAR_COMMON_WORDS:
                        counts = _ends_segment(text, end)
                    else:
                        counts = field == "title" or _closes_segment(text, end)
                    if counts:
                        found.add(self._two_char[name].key)
                        break
        return found

    def symbols(self, title: str, summary: str | None = None) -> list[str]:
        summary = summary or ""
        text = f"{title}\n{summary}" if summary else title
        found = self._two_char_keys(title, summary)
        codes = [*_CODE.finditer(text), *_ETF_CODE.finditer(text)]
        for match in codes:
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

    def relate(
        self, title: str, summary: str | None, source_kind: str
    ) -> tuple[list[str], list[str], str]:
        """Symbols, theme ids and impact scope of one item (title + summary)."""

        symbols = self.symbols(title, summary)
        theme_ids = self.theme_ids(f"{title}\n{summary or ''}")
        return symbols, theme_ids, _impact_scope(source_kind, symbols, theme_ids)

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


def _impact_scope(source_kind: str, symbols: list[str], theme_ids: list[str]) -> str:
    if symbols:
        return "instrument"
    if theme_ids:
        return "theme"
    return "market" if source_kind == "macro_official" else "unknown"


def _rerelate_recent(
    db: Session, matcher: RelationMatcher, run_date: date, now: datetime
) -> dict[str, Any] | None:
    """Relate recent items again whose stored relations come from an older rule.

    Only ``active`` feed items whose source time (or collection time) is
    within RELATION_RERUN_WINDOW of ``now``; older items keep their version.
    The previous values are kept in the metadata of a ``news_relations`` run
    committed together with the rows: ``items`` holds the rows whose
    relations changed (old and new values), ``unchanged`` the ids of the rest
    by their previous method.  Returns None when nothing is due (no run is
    opened then).
    """

    since = now - RELATION_RERUN_WINDOW
    rows = db.scalars(
        select(NewsItem)
        .where(
            NewsItem.status == "active",
            NewsItem.impact_method.like(f"{RELATION_METHOD_PREFIX}%"),
            NewsItem.impact_method != RELATION_METHOD,
            func.coalesce(NewsItem.published_at, NewsItem.collected_at) >= since,
        )
        .order_by(NewsItem.id)
    ).all()
    if not rows:
        return None
    items: list[dict[str, Any]] = []
    unchanged: dict[str, list[int]] = {}
    for item in rows:
        symbols, theme_ids, scope = matcher.relate(
            item.title, item.summary, item.source_kind
        )
        previous = {
            "method": item.impact_method,
            "symbols": list(item.symbols_json or []),
            "theme_ids": list(item.theme_ids_json or []),
            "impact_scope": item.impact_scope,
        }
        if (symbols, theme_ids, scope) == (
            previous["symbols"],
            previous["theme_ids"],
            previous["impact_scope"],
        ):
            # Same relations: only the method moves, so the id is enough.
            unchanged.setdefault(item.impact_method, []).append(item.id)
        else:
            items.append(
                {
                    "news_item_id": item.id,
                    "previous": previous,
                    "symbols": symbols,
                    "theme_ids": theme_ids,
                    "impact_scope": scope,
                }
            )
        item.symbols_json = symbols
        item.theme_ids_json = theme_ids
        item.impact_scope = scope
        item.impact_method = RELATION_METHOD
    started = utcnow()
    run = IngestionRun(
        run_type=RELATION_RUN_TYPE,
        source="rule",
        run_date=run_date,
        status="success",
        records=len(rows),
        started_at=started,
        finished_at=started,
        data_as_of=now.isoformat(),
        metadata_json={
            "method": RELATION_METHOD,
            "window_days": RELATION_RERUN_WINDOW.days,
            "since": since.isoformat(),
            "rerelated": len(rows),
            "changed": len(items),
            "items": items,
            "unchanged": unchanged,
        },
    )
    db.add(run)
    db.commit()
    return {"run_id": run.id, "rerelated": len(rows), "changed": len(items)}


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
        temporal = _temporal(entry, collected_at)
        conflict = temporal["time_consistency"] == "conflict"
        reason = exclusion_reason(source, entry.title, entry.url)
        if reason:
            status = "excluded"
            excluded.append(_excluded_record(key, entry.title, entry.url, reason))
        else:
            status = "quarantined" if conflict else "active"
        if conflict:
            symbols, theme_ids = [], []
            scope = _impact_scope(source.source_kind, symbols, theme_ids)
        else:
            symbols, theme_ids, scope = matcher.relate(
                entry.title, entry.summary, source.source_kind
            )
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
            started_at=utcnow(),
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
        collected_at = utcnow()
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
        run.data_as_of = utcnow().isoformat()
        run.metadata_json = {**metadata, "feeds": feeds}
        run.finished_at = utcnow()
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
    try:
        relations = _write_unit(
            db, lambda: _rerelate_recent(db, matcher, label_date, utcnow())
        )
    except Exception as exc:  # noqa: BLE001 - the feeds must still be collected
        # The old relations stay; the next run tries again.
        db.rollback()
        relations = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
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
        "relations": relations,
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
