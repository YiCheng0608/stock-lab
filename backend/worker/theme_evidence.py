"""Check theme-table evidence against the live (or saved) evidence pages.

``themes sync`` validates structure and the DB; this module checks what the
evidence says.  A member passes only when all of these hold:

1. its instrument exists in the DB and is a stock (``stock``/``ipo``);
2. every evidence page can be fetched and its ``quote`` appears verbatim in
   the page text (whitespace and HTML markup ignored, NFKC-normalised);
3. every ``quote`` contains at least one of the theme's ``keywords``
   (case-insensitive);
4. for a MOPS 公司基本資料 (t05st03) URL, its ``co_id`` is the member's symbol
   and the ``quote`` is inside the 主要經營業務 cell.

Pages are fetched one at a time with a delay and cached per URL within a run.
``pages_dir`` reads previously saved pages instead of the network (offline
re-checks and tests); ``save_dir`` stores every fetched page in the same
layout: one file per page plus ``index.json`` mapping URL to file name and
SHA-256.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Instrument
from app.theme_table import (
    THEME_TABLE_PATH,
    ThemeTableError,
    load_theme_table,
    member_period,
    split_instrument,
)

from .themes import THEME_MEMBER_TYPES

USER_AGENT = "taiwan-stock-research/0.1"
FETCH_DELAY_SECONDS = 3.0
FETCH_TIMEOUT_SECONDS = 30.0
PAGES_INDEX = "index.json"
MOPS_MAIN_BUSINESS = "主要經營業務"
MOPS_NEXT_FIELD = "公司成立日期"

_DROP_BLOCKS = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_META_CHARSET = re.compile(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", re.I)


class EvidenceFetchError(RuntimeError):
    pass


def normalize_text(value: str) -> str:
    """Comparable form: NFKC, no whitespace."""

    return _SPACE.sub("", unicodedata.normalize("NFKC", value))


def page_text(body: bytes, content_type: str | None = None) -> str:
    """Visible text of an HTML page, decoded from its declared charset."""

    charset = None
    if content_type and "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";")[0].strip()
    if charset is None:
        match = _META_CHARSET.search(body[:4096])
        charset = match.group(1).decode("ascii") if match else "utf-8"
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    text = _DROP_BLOCKS.sub(" ", text)
    return html.unescape(_TAG.sub(" ", text))


def _page_file(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24] + ".html"


class PageStore:
    """Fetch evidence pages once per URL, from the network or a saved directory."""

    def __init__(
        self,
        *,
        pages_dir: Path | None = None,
        save_dir: Path | None = None,
        delay: float = FETCH_DELAY_SECONDS,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.pages_dir = pages_dir
        self.save_dir = save_dir
        self.delay = delay
        self.client = client
        self.sleep = sleep
        self._cache: dict[str, str] = {}
        self._fetched = 0
        self._index: dict[str, Any] = {}
        if pages_dir is not None:
            index_path = pages_dir / PAGES_INDEX
            try:
                self._index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise EvidenceFetchError(
                    f"{index_path}: cannot read saved pages index ({type(error).__name__})"
                ) from error

    def text(self, url: str) -> str:
        if url not in self._cache:
            body, content_type = (
                self._read_saved(url)
                if self.pages_dir is not None
                else self._fetch(url)
            )
            self._cache[url] = normalize_text(page_text(body, content_type))
        return self._cache[url]

    def _read_saved(self, url: str) -> tuple[bytes, str | None]:
        entry = self._index.get(url)
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise EvidenceFetchError("page not in saved pages")
        try:
            body = (self.pages_dir / entry["file"]).read_bytes()
        except OSError as error:
            raise EvidenceFetchError(
                f"cannot read saved page ({type(error).__name__})"
            ) from error
        return body, entry.get("content_type")

    def _fetch(self, url: str) -> tuple[bytes, str | None]:
        if self._fetched:
            self.sleep(self.delay)
        self._fetched += 1
        client = self.client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            raise EvidenceFetchError(
                f"fetch failed ({type(error).__name__})"
            ) from error
        finally:
            if self.client is None:
                client.close()
        if response.status_code != 200:
            raise EvidenceFetchError(f"HTTP {response.status_code}")
        content_type = response.headers.get("content-type")
        if self.save_dir is not None:
            self._save(url, response.content, content_type)
        return response.content, content_type

    def _save(self, url: str, body: bytes, content_type: str | None) -> None:
        self.save_dir.mkdir(parents=True, exist_ok=True)
        name = _page_file(url)
        (self.save_dir / name).write_bytes(body)
        index_path = self.save_dir / PAGES_INDEX
        index = (
            json.loads(index_path.read_text(encoding="utf-8"))
            if index_path.exists()
            else {}
        )
        index[url] = {
            "file": name,
            "content_type": content_type,
            "sha256": hashlib.sha256(body).hexdigest(),
            "fetched_on": date.today().isoformat(),
        }
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def check_member(
    theme: dict[str, Any],
    member: dict[str, Any],
    pages: PageStore,
    instrument_types: dict[tuple[str, str], str],
) -> list[str]:
    """Errors for one member; empty when it passes every check."""

    errors: list[str] = []
    instrument_type = instrument_types.get(split_instrument(member["instrument"]))
    if instrument_type is None:
        errors.append("unknown instrument")
    elif instrument_type not in THEME_MEMBER_TYPES:
        errors.append(f"instrument_type={instrument_type} is not a stock")
    symbol = split_instrument(member["instrument"])[1]
    keywords = [normalize_text(word).casefold() for word in theme.get("keywords") or []]
    for index, item in enumerate(member["evidence"]):
        location = f"evidence[{index}]"
        quote = normalize_text(item["quote"])
        if not any(word and word in quote.casefold() for word in keywords):
            errors.append(f"{location}.quote: no theme keyword")
        mops_co_id = _mops_profile_co_id(item["url"])
        if mops_co_id is not None and mops_co_id != symbol:
            errors.append(f"{location}.url: co_id={mops_co_id} is not {symbol}")
        try:
            text = pages.text(item["url"])
        except EvidenceFetchError as error:
            errors.append(f"{location}.url: {error}")
            continue
        if mops_co_id is not None:
            # A MOPS company profile: only the 主要經營業務 cell counts, so a
            # company name or another field cannot carry the theme word.
            cell = _mops_main_business(text)
            if cell is None:
                errors.append(f"{location}.url: no {MOPS_MAIN_BUSINESS} on page")
            elif quote not in cell:
                errors.append(f"{location}.quote: not found in {MOPS_MAIN_BUSINESS}")
        elif quote not in text:
            errors.append(f"{location}.quote: not found on page")
    return errors


def _mops_profile_co_id(url: str) -> str | None:
    """``co_id`` of a MOPS 公司基本資料 (t05st03) URL; None for other pages."""

    parts = urlsplit(url)
    if not parts.hostname or not parts.hostname.endswith("twse.com.tw"):
        return None
    if "t05st03" not in parts.path:
        return None
    return (parse_qs(parts.query).get("co_id") or [""])[0]


def _mops_main_business(text: str) -> str | None:
    """The normalised 主要經營業務 cell of a normalised MOPS profile page."""

    start = text.find(MOPS_MAIN_BUSINESS)
    end = text.find(MOPS_NEXT_FIELD, start)
    if start < 0 or end < 0:
        return None
    return text[start + len(MOPS_MAIN_BUSINESS) : end]


def verify_table(
    table: dict[str, Any],
    pages: PageStore,
    instrument_types: dict[tuple[str, str], str],
    *,
    theme_ids: list[str] | None = None,
    since: date | None = None,
) -> dict[str, Any]:
    """Check the selected members; ``status`` is ``failed`` if any member fails."""

    known = {theme["id"] for theme in table["themes"]}
    unknown = [theme_id for theme_id in theme_ids or [] if theme_id not in known]
    if unknown:
        return {"status": "failed", "errors": [f"unknown theme id: {unknown}"]}
    failures: list[dict[str, Any]] = []
    checked = 0
    for theme_index, theme in enumerate(table["themes"]):
        if theme_ids and theme["id"] not in theme_ids:
            continue
        location = f"themes[{theme_index}]({theme['id']})"
        members = [
            (index, member)
            for index, member in enumerate(theme["members"])
            if since is None or member_period(theme, member)[0] >= since
        ]
        if members and not theme.get("keywords"):
            failures.append(
                {"location": location, "errors": ["keywords required to verify"]}
            )
            continue
        for member_index, member in members:
            checked += 1
            errors = check_member(theme, member, pages, instrument_types)
            if errors:
                failures.append(
                    {
                        "location": f"{location}.members[{member_index}]({member['instrument']})",
                        "errors": errors,
                    }
                )
    return {
        "status": "failed" if failures else "success",
        "checked": checked,
        "passed": checked
        - sum(1 for item in failures if ".members[" in item["location"]),
        "failures": failures,
    }


def _instrument_types() -> dict[tuple[str, str], str]:
    with SessionLocal() as db:
        rows = db.execute(
            select(
                Instrument.exchange, Instrument.symbol, Instrument.instrument_type
            ).where(Instrument.exchange.in_(("TWSE", "TPEx")))
        ).all()
    return {(exchange, symbol): kind for exchange, symbol, kind in rows}


def verify_themes(
    path: Path | str | None = None,
    *,
    theme_ids: list[str] | None = None,
    since: date | None = None,
    pages_dir: Path | str | None = None,
    save_dir: Path | str | None = None,
) -> dict[str, Any]:
    """CLI entry: load the table, then check the selected members' evidence."""

    target = Path(path) if path is not None else THEME_TABLE_PATH
    try:
        table = load_theme_table(target)
        pages = PageStore(
            pages_dir=Path(pages_dir) if pages_dir else None,
            save_dir=Path(save_dir) if save_dir else None,
        )
    except (ThemeTableError, EvidenceFetchError) as error:
        errors = error.errors if isinstance(error, ThemeTableError) else [str(error)]
        return {"status": "failed", "file": str(target), "errors": errors}
    result = verify_table(
        table, pages, _instrument_types(), theme_ids=theme_ids, since=since
    )
    return {"file": str(target), **result}
