"""Price wordings in a text (Issue #1058, docs/spec/premarket_ai.md 核對).

3a: a stock without usable rule levels gets no price in the pre-market AI's
reasons.  ``price_mentions`` is the one test of "this text writes a price",
shared by ``worker.premarket_reading.check`` and the verify check T30
(``tools/verify/page_checks.py`` loads this file by path, so it only uses the
standard library and imports nothing of ``worker``).

First the parts that are no price are taken out, then what is left is searched:

- **a price**: a number with two decimals (「收盤 85.30」「1,234.50」) or a
  number before 元 (「85 元附近」「85元」「85.5 元」).
- **no price**: a quoted news title (the whole text or the inside of 「」『』“”
  is part of one of TITLES), a date (2026-11-26, 2026/11/26, 2026.11.26, 11/26,
  11 月 26 日), a per-share figure (EPS／每股盈餘／每股純益／股利／配息／配股 at
  most 6 characters before the number: 「EPS 3.25 元」「現金股利 2.50 元」), a
  percent (3.25%, 3.25 ％, 0.50 個百分點), a ratio (1.85 倍), an amount or a
  count (12.34 億, 3.5 萬張, 1,234 張, 1,000 股) and index points (23,456.78 點).
  A bare 「11.26」 cannot be told from a price and counts as one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_NUM = r"[0-9][0-9,]*(?:\.[0-9]+)?"
_RANGE = rf"{_NUM}(?:\s*[～~]\s*{_NUM})?"
_QUOTE = re.compile(r"「([^「」]*)」|『([^『』]*)』|“([^“”]*)”")
_DATES = re.compile(
    r"(?<![0-9])(?:[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}"
    r"|[0-9]{1,2}/[0-9]{1,2}"
    r"|[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日)(?![0-9])"
)
PER_SHARE_WORDS = ("EPS", "每股盈餘", "每股純益", "股利", "配息", "配股")
PER_SHARE_LOOKBEHIND = 6
_PER_SHARE = re.compile(
    rf"(?:{'|'.join(PER_SHARE_WORDS)})[^0-9]{{0,{PER_SHARE_LOOKBEHIND}}}?"
    rf"{_RANGE}(?:\s*元)?",
    re.IGNORECASE,
)
_NOT_PRICE = re.compile(
    rf"[+-]?{_RANGE}\s*(?:%|％|個百分點|倍|點|(?:兆|億|萬|千)\s*(?:元|張|股)?|張|股)"
)
_PRICE = re.compile(
    r"(?<![0-9.,])(?:[0-9][0-9,]*\.[0-9]{2}(?![0-9])(?:\s*元)?"
    rf"|{_NUM}\s*元)"
)


def _no_titles(text: str, titles: list[str]) -> str:
    def quoted(match: re.Match[str]) -> str:
        inside = next(group for group in match.groups() if group is not None)
        if inside.strip() and any(inside.strip() in title for title in titles):
            return " "
        return match.group(0)

    return _QUOTE.sub(quoted, text)


def price_mentions(text: str, titles: Iterable[str] = ()) -> list[str]:
    """The price wordings of TEXT in order (「85.30」「85 元」); [] when it has none.

    TITLES are the news titles that may be quoted (the ones the reasons cite)."""

    titles = [title for title in titles if title]
    if text.strip() in titles:
        return []
    text = _no_titles(text, titles)
    for pattern in (_DATES, _PER_SHARE, _NOT_PRICE):
        text = pattern.sub(" ", text)
    return [match.group(0) for match in _PRICE.finditer(text)]
