"""Price wordings in a text (Issue #1058, docs/spec/premarket_ai.md 核對).

3a: a stock without usable rule levels gets no price in the pre-market AI's
reasons.  ``price_mentions`` is the one test of "this text writes a price",
shared by ``worker.premarket_reading.check`` and the verify check T30
(``tools/verify/page_checks.py`` loads this file by path, so it only uses the
standard library and imports nothing of ``worker``).

First the parts that are no price are taken out, then what is left is searched:

- **a price**: a number with two decimals (「收盤 85.30」「1,234.50」) or a
  number before 元 (「85 元附近」「85元」「85.5 元」).
- **no price**: a quoted news title (the whole text, or the inside of 「」『』“”
  with a character that is no digit is part of one of TITLES), a stock's
  「<代號> <名稱>」 of NAMES (「8069 元太」), a date (2026-11-26, 2026/11/26,
  2026.11.26, 114/11/26, 11/26, 11 月 26 日; not inside a number:
  「85.30/86.00」 is two prices), a per-share figure (EPS／每股盈餘／每股純益／
  每股淨值／股利／配息／配股／除息 at most 6 characters before the number, none
  of them 價 or a punctuation mark: 「EPS 3.25 元」「除息 2.5 元」), a percent
  (3.25%, 3.25 ％, 0.50 個百分點, 2.35 百分點), a ratio (1.85 倍, 量比 1.85), an
  amount or a count (12.34 億, 12.34 百萬元, 3.5 萬張, 1,234 張, 1,000 股; a
  unit that starts another word is none: 「85.30 萬一」「85.30 股價」) and index
  points (23,456.78 點).  A bare 「11.26」 cannot be told from a price and counts
  as one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_NUM = r"[0-9][0-9,]*(?:\.[0-9]+)?"
_RANGE = rf"{_NUM}(?:\s*[～~]\s*{_NUM})?"
_QUOTE = re.compile(r"「([^「」]*)」|『([^『』]*)』|“([^“”]*)”")
# A quote of digits alone (「85.30」) is no title quote even when a title has it.
_WORDY = re.compile(r"[^\s0-9.,%％～~+\-/]")
# Dates: not inside a number either side (「85.30/86.00」 is two prices, #1060 review 2).
_DATES = re.compile(
    r"(?<![0-9.,])(?:[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}"
    r"|[0-9]{2,3}/[0-9]{1,2}/[0-9]{1,2}"
    r"|[0-9]{1,2}/[0-9]{1,2}"
    r"|[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日)(?![0-9]|[.,][0-9])"
)
PER_SHARE_WORDS = (
    "EPS",
    "每股盈餘",
    "每股純益",
    "每股淨值",
    "股利",
    "配息",
    "配股",
    "除息",
)
PER_SHARE_LOOKBEHIND = 6
# At most 6 characters between the word and the number, none of them 價 or a
# punctuation mark: 「配息後股價 85.30 元」 is a price (#1060 review suggestion 1).
_PER_SHARE = re.compile(
    rf"(?:{'|'.join(PER_SHARE_WORDS)})[^0-9價，、；。,;]{{0,{PER_SHARE_LOOKBEHIND}}}?"
    rf"{_RANGE}(?:\s*元)?",
    re.IGNORECASE,
)
# 量比 as the input's volume_ratio_20d, written without 倍.
_RATIO_WORD = re.compile(rf"量比\s*{_RANGE}")
# A unit is no unit when it starts another word: 「85.30 萬一跌破」「85.30 股價」
# (#1060 review suggestion 2).
_UNITS = r"兆|億|百萬|千萬(?=\s*(?:元|張|股))|萬(?!一)|千(?!萬)|仟"
_NOT_PRICE = re.compile(
    rf"[+-]?{_RANGE}\s*(?:%|％|個?百分點|倍|點"
    rf"|(?:{_UNITS})\s*(?:元|張|股(?!價))?|張|股(?!價))"
)
_PRICE = re.compile(
    r"(?<![0-9.,])(?:[0-9][0-9,]*\.[0-9]{2}(?![0-9])(?:\s*元)?"
    rf"|{_NUM}\s*元)"
)


def _no_titles(text: str, titles: list[str]) -> str:
    def quoted(match: re.Match[str]) -> str:
        inside = next(group for group in match.groups() if group is not None).strip()
        if _WORDY.search(inside) and any(inside in title for title in titles):
            return " "
        return match.group(0)

    return _QUOTE.sub(quoted, text)


def _no_names(text: str, names: list[tuple[str, str]]) -> str:
    """Take out 「<代號> <名稱>」: 「8069 元太」 is no 「8069 元」 (#1060 review 1)."""

    for symbol, name in names:
        if symbol and name:
            text = re.sub(
                rf"(?<![0-9A-Za-z]){re.escape(symbol)}\s*{re.escape(name)}", " ", text
            )
    return text


def price_mentions(
    text: str,
    titles: Iterable[str] = (),
    names: Iterable[tuple[str, str]] = (),
) -> list[str]:
    """The price wordings of TEXT in order (「85.30」「85 元」); [] when it has none.

    TITLES are the news titles that may be quoted (the ones the reasons cite);
    NAMES the (symbol, name) pairs of the stocks the text may name."""

    titles = [title for title in titles if title]
    if text.strip() in titles:
        return []
    text = _no_titles(text, titles)
    text = _no_names(text, [(s or "", n or "") for s, n in names])
    for pattern in (_DATES, _PER_SHARE, _RATIO_WORD, _NOT_PRICE):
        text = pattern.sub(" ", text)
    return [match.group(0) for match in _PRICE.finditer(text)]
