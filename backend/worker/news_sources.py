"""Free public news feeds: source registry, fetch, and RSS parsing.

Only the title, the source-provided summary/description, the time, and the
item link are kept.  Article bodies are never fetched, and body excerpts a feed
embeds (``content:encoded``) are dropped before the raw capture is written.
Usage conditions and the excluded candidates are listed in docs/DATA_SOURCES.md.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.parsers import expat

import httpx

USER_AGENT = "stock-lab-news/0.1 (+https://github.com/YiCheng0608/stock-lab)"
REQUEST_INTERVAL_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
# Column lengths of news_items (SQLite does not enforce them; other engines do).
MAX_TITLE_LENGTH = 300
MAX_ITEM_ID_LENGTH = 180
MAX_URL_LENGTH = 800
TAIPEI = timezone(timedelta(hours=8))

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"


class NewsSourceError(RuntimeError):
    """A feed could not provide a trustworthy payload (HTTP, rate limit, format)."""


@dataclass(frozen=True)
class NewsFeed:
    key: str
    label: str
    url: str


@dataclass(frozen=True)
class NewsSource:
    source_id: str
    source_name: str
    owner: str
    source_kind: str  # media | macro_official
    category: str  # domestic | international
    language: str
    feeds: tuple[NewsFeed, ...]
    item_url_rule: str
    terms: str
    # Offset applied when a feed time has no zone (Taiwan has no DST, so a
    # fixed +08:00 is exact for Taiwan publishers).  None keeps such a time
    # unknown instead of guessing.
    naive_offset: timezone | None = None


def _cnbc(feed_id: str, key: str, label: str) -> NewsFeed:
    return NewsFeed(
        key, label, f"https://www.cnbc.com/id/{feed_id}/device/rss/rss.html"
    )


NEWS_SOURCES: tuple[NewsSource, ...] = (
    NewsSource(
        source_id="cna",
        source_name="中央社",
        owner="中央通訊社",
        source_kind="media",
        category="domestic",
        language="zh-Hant",
        feeds=(
            NewsFeed(
                "finance", "產經證券", "https://feeds.feedburner.com/rsscna/finance"
            ),
        ),
        item_url_rule="https://www.cna.com.tw/news/<分類>/<編號>.aspx；guid 為 CNA/<日期>/<編號>",
        terms="個人、非營利組織之非商業用途；標示「中央通訊社」；不得引用全文",
    ),
    NewsSource(
        source_id="cnyes",
        source_name="鉅亨網",
        owner="鉅亨網（Anue）",
        source_kind="media",
        category="domestic",
        language="zh-Hant",
        feeds=(
            NewsFeed(
                "tw_stock",
                "台股新聞",
                "https://news.cnyes.com/rss/v1/news/category/tw_stock",
            ),
        ),
        item_url_rule="https://news.cnyes.com/news/id/<編號>；guid 即單篇 URL",
        terms="未公布 RSS 專屬條款；robots.txt 未禁止 feed 路徑；content:encoded 正文節錄不保存",
    ),
    NewsSource(
        source_id="ctee",
        source_name="工商時報",
        owner="工商時報",
        source_kind="media",
        category="domestic",
        language="zh-Hant",
        feeds=(
            NewsFeed("stock", "證券", "https://www.ctee.com.tw/rss_web/livenews/stock"),
        ),
        item_url_rule="https://www.ctee.com.tw/news/<編號>-<頻道>；guid 為編號",
        terms="未公布 RSS 專屬條款；robots.txt 對一般 user-agent 無限制",
        naive_offset=TAIPEI,
    ),
    NewsSource(
        source_id="yahoo_tw",
        source_name="Yahoo奇摩股市",
        owner="Yahoo股市",
        source_kind="media",
        category="domestic",
        language="zh-Hant",
        feeds=(
            NewsFeed(
                "tw_market",
                "台股盤勢",
                "https://tw.stock.yahoo.com/rss?category=tw-market",
            ),
        ),
        item_url_rule="tw.stock.yahoo.com／tw.news.yahoo.com 單篇 URL；guid 為空，以 canonical URL 識別",
        terms="個人與非營利組織之非商業用途；標示「Yahoo股市」；標題中的來源不得修改",
    ),
    NewsSource(
        source_id="cnbc",
        source_name="CNBC",
        owner="CNBC LLC（NBCUniversal）",
        source_kind="media",
        category="international",
        language="en",
        feeds=(
            _cnbc("100003114", "top_news", "Top News"),
            _cnbc("20409666", "market_insider", "Market Insider"),
            _cnbc("19854910", "technology", "Technology"),
        ),
        item_url_rule="https://www.cnbc.com/<日期>/<slug>.html；guid 為數字 ID，三個 feed 共用",
        terms="CNBC RSS 頁公開提供訂閱；www.cnbc.com robots.txt 未禁止 /id/；sponsored 項不收",
    ),
    NewsSource(
        source_id="marketwatch",
        source_name="MarketWatch",
        owner="Dow Jones & Company",
        source_kind="media",
        category="international",
        language="en",
        feeds=(
            NewsFeed(
                "top_stories",
                "Top Stories",
                "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            ),
        ),
        item_url_rule="https://www.marketwatch.com/story/<slug>；guid 為 WP-MKTW-<編號>，URL 去除 mod 參數",
        terms="Dow Jones 服務條款：個人、非商業用途",
    ),
    NewsSource(
        source_id="fed",
        source_name="Federal Reserve",
        owner="Board of Governors of the Federal Reserve System",
        source_kind="macro_official",
        category="international",
        language="en",
        feeds=(
            NewsFeed(
                "press_all",
                "Press Releases",
                "https://www.federalreserve.gov/feeds/press_all.xml",
            ),
        ),
        item_url_rule="https://www.federalreserve.gov/newsevents/pressreleases/<名稱>.htm；guid 即單篇 URL",
        terms="公有領域，可複製散布，需標示來源",
    ),
)

SOURCES_BY_ID = {source.source_id: source for source in NEWS_SOURCES}


@dataclass(frozen=True)
class FeedResponse:
    status_code: int
    content_type: str | None
    content: bytes
    text: str


Fetcher = Callable[[str], FeedResponse]


class HttpFeedFetcher:
    """One shared client with a fixed User-Agent and a fixed request interval.

    Bodies are streamed and capped at MAX_RESPONSE_BYTES, and a redirect is
    followed only within the host of the registered feed URL.
    """

    def __init__(
        self,
        *,
        interval: float = REQUEST_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        client: httpx.Client | None = None,
    ) -> None:
        self._interval = interval
        self._sleep = sleep
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
        self._requested = False

    def __call__(self, url: str) -> FeedResponse:
        if self._requested:
            self._sleep(self._interval)
        self._requested = True
        host = urlsplit(url).hostname
        target = url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                with self._client.stream(
                    "GET",
                    target,
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=False,
                ) as response:
                    if response.is_redirect:
                        target = urljoin(target, response.headers.get("location", ""))
                        if urlsplit(target).hostname != host:
                            raise NewsSourceError(
                                f"redirect to another host refused: {target}"
                            )
                        continue
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE_BYTES:
                            raise NewsSourceError(
                                f"response exceeds {MAX_RESPONSE_BYTES} bytes"
                            )
                    body = bytes(content)
                    return FeedResponse(
                        response.status_code,
                        response.headers.get("content-type"),
                        body,
                        body.decode(
                            response.charset_encoding or "utf-8", errors="replace"
                        ),
                    )
        except httpx.HTTPError as exc:
            raise NewsSourceError(
                f"request failed: {type(exc).__name__}: {exc}"
            ) from exc
        raise NewsSourceError(f"more than {MAX_REDIRECTS} redirects")

    def close(self) -> None:
        self._client.close()


def check_response(response: FeedResponse) -> None:
    if response.status_code == 429:
        raise NewsSourceError("rate limited (HTTP 429)")
    if response.status_code >= 400:
        raise NewsSourceError(f"HTTP {response.status_code}")


_CONTENT_ENCODED = re.compile(
    r"<content:encoded\b.*?</content:encoded>|<content:encoded\b[^>]*/>", re.S
)


def naive_offset_text(offset: timezone | None) -> str | None:
    if offset is None:
        return None
    minutes = int(offset.utcoffset(None).total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def raw_feed_payload(
    source: NewsSource, feed: NewsFeed, response: FeedResponse
) -> dict[str, object]:
    """JSON payload for persist_raw_payload, without embedded article bodies.

    ``naive_time_offset`` records the offset assumed for zone-less feed times
    (null when such times are left unknown), so stored instants can be traced
    back to that assumption.
    """

    body, removed = _CONTENT_ENCODED.subn("", response.text)
    return {
        "format": "rss",
        "feed": feed.key,
        "http_status": response.status_code,
        "content_type": response.content_type,
        "naive_time_offset": naive_offset_text(source.naive_offset),
        "removed_elements": {"content:encoded": removed} if removed else {},
        "body": body,
    }


@dataclass(frozen=True)
class FeedEntry:
    source_item_id: str | None  # the feed guid; None when the feed has none
    url: str
    title: str
    summary: str | None
    published_at: datetime | None  # naive UTC
    event_date: date | None
    raw_time: str | None


# Query parameters that only track the referral; dropping them makes the same
# article reached from two feeds (or two campaigns) one canonical URL.
_TRACKING_KEYS = {
    "mod",
    "tsrc",
    ".tsrc",
    "cmpid",
    "fbclid",
    "gclid",
    "ocid",
    "ncid",
    "guccounter",
    "guce_referrer",
    "guce_referrer_sig",
    "soc_src",
    "soc_trk",
}


def canonical_url(url: str) -> str:
    """https, lower-case host, no tracking query, fragment or trailing slash."""

    parts = urlsplit(url.strip())
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_KEYS
        and not key.casefold().startswith("utm_")
    )
    scheme = parts.scheme.lower()
    if scheme == "http":
        scheme = "https"
    path = parts.path.rstrip("/") if len(parts.path) > 1 else parts.path
    return urlunsplit((scheme, parts.netloc.lower(), path, urlencode(query), ""))


def normalized_title(title: str) -> str:
    """Title key for cross-source clustering: NFKC, casefold, no space/punctuation."""

    text = unicodedata.normalize("NFKC", title).casefold()
    return "".join(
        ch
        for ch in text
        if not ch.isspace() and unicodedata.category(ch)[0] not in {"P", "S"}
    )


def title_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_TAG = re.compile(r"<[^>]+>")
_DATE_ONLY = re.compile(r"\d{4}-?\d{2}-?\d{2}")
_ISO_WITH_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_ASCII_SPACE = re.compile(r"[ \t\r\n]+")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    # Unescape before removing tags so escaped markup (``&lt;b&gt;``, or a
    # double-escaped ``&amp;lt;b&amp;gt;`` inside CDATA) is removed, not stored.
    text = value
    for _ in range(3):
        cleaned = _TAG.sub(" ", html.unescape(text))
        if cleaned == text:
            break
        text = cleaned
    # Collapse ASCII whitespace only; a full-width space is part of the source title.
    text = _ASCII_SPACE.sub(" ", text).strip()
    return text or None


def _parse_time(
    value: str | None, naive_offset: timezone | None
) -> tuple[datetime | None, date | None]:
    """Return (naive UTC instant, date) — only one of them is set, or neither.

    A value without a time of day is a date and never gets a clock time.  An
    RFC 2822 time with ``-0000`` (zone explicitly unknown) stays unknown;
    ``naive_offset`` applies only to ISO times that carry no zone at all.
    Invalid values are unknown, never an error.
    """

    text = (value or "").strip()
    if not text:
        return None, None
    if _DATE_ONLY.fullmatch(text):
        try:
            return None, date.fromisoformat(text)
        except ValueError:
            return None, None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:  # -0000
            return None, None
        return parsed.astimezone(timezone.utc).replace(tzinfo=None), None
    if not _ISO_WITH_TIME.match(text):
        return None, None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        if naive_offset is None:
            return None, None
        parsed = parsed.replace(tzinfo=naive_offset)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None), None


def _text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


class _DoctypeFound(Exception):
    pass


def _refuse(*_args: object) -> None:
    raise _DoctypeFound


def _reject_doctype(content: bytes) -> None:
    """Refuse any DOCTYPE or entity declaration, wherever it is in the document."""

    checker = expat.ParserCreate()
    checker.StartDoctypeDeclHandler = _refuse
    checker.EntityDeclHandler = _refuse
    try:
        checker.Parse(content, True)
    except _DoctypeFound:
        raise NewsSourceError(
            "format error: DTD/entity declarations are not accepted"
        ) from None
    except expat.ExpatError as exc:
        raise NewsSourceError(f"format error: {exc}") from exc


def parse_rss(content: bytes, source: NewsSource) -> tuple[list[FeedEntry], int]:
    """Parse an RSS 2.0 document into entries; return (entries, skipped item count).

    Raises NewsSourceError when the document is not RSS.  Items without a title
    or an absolute link, links longer than the URL column, and sponsored CNBC
    items are skipped and counted.  Titles and guids are cut to their column
    lengths.
    """

    _reject_doctype(content)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise NewsSourceError(f"format error: {exc}") from exc
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise NewsSourceError(
            f"format error: expected <rss><channel>, got <{root.tag}>"
        )
    entries: list[FeedEntry] = []
    skipped = 0
    for item in channel.findall("item"):
        title = _clean_text(_text(item, "title"))
        link = _text(item, "link")
        sponsored = (
            _text(
                item,
                "{http://search.cnbc.com/rss/2.0/modules/siteContentMetadata}sponsored",
            )
            or ""
        ).casefold()
        if (
            not title
            or not link
            or not link.startswith(("https://", "http://"))
            or sponsored == "true"
        ):
            skipped += 1
            continue
        url = canonical_url(link)
        if len(url) > MAX_URL_LENGTH:
            skipped += 1
            continue
        guid = _text(item, "guid")
        raw_time = _text(item, "pubDate")
        published_at, event_date = _parse_time(raw_time, source.naive_offset)
        entries.append(
            FeedEntry(
                source_item_id=guid,
                url=url,
                title=title[:MAX_TITLE_LENGTH],
                summary=_clean_text(_text(item, "description")),
                published_at=published_at,
                event_date=event_date,
                raw_time=raw_time,
            )
        )
    return entries, skipped
