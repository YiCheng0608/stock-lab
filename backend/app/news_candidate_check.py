"""Rule check of the news LLM's symbol candidates against the text it was sent (#465).

The rule relations (``worker.news_batch.RelationMatcher``) only count a name with
context, so a candidate the model names from the text can still be missing from
``symbols``: a two-character name in the middle of a sentence (鴻海, 華新), or a
name the strict rules skip.  This check asks a narrower question of each
candidate the model already proposed: does the stock's own name, or its code,
appear in the title or the summary the model was sent?

- ``mentioned``: yes.  The page shows it as rule-checked (原文提及); it is still
  not a rule relation, so ``symbols``, the candidate score and the news filters
  do not change.
- ``not_mentioned``: no, the model inferred it (a supplier, a peer, a sector
  leader).  The page shows it as 推論.

Comparison is on NFKC, casefolded text without whitespace.  A name counts only
outside a longer listed name that contains it (華新 inside 華新科 is 2492, not
1605).  A code counts only when no letter or digit touches it.  Names are the
master name and the same variants the rule matcher reads (listing markers,
former ETF names, holding-company endings).  A code not in the master has no
name to look for and is checked by its code alone.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from worker.news_batch import _etf_aliases, _holding_alias, _name_aliases
from worker.news_llm import SUMMARY_INPUT_CHARS

CANDIDATE_CHECK_VERSION = "ai-candidate-source/v1"
MENTIONED = "mentioned"
NOT_MENTIONED = "not_mentioned"

_WHITESPACE = re.compile(r"\s+")


def _key(text: str) -> str:
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", text or "")).casefold()


def name_variants(name: str | None) -> set[str]:
    """The keys of a master name: the name and the variants the rule matcher reads."""

    if not name or not name.strip():
        return set()
    variants = _name_aliases(name) | _etf_aliases(name)
    holding = _holding_alias(name)
    if holding:
        variants.add(holding)
    return {key for key in (_key(variant) for variant in variants) if len(key) >= 2}


def source_text(title: str | None, summary: str | None) -> str:
    """What the model was sent: the title and the first SUMMARY_INPUT_CHARS of the summary."""

    return _key(title or "") + "\n" + _key((summary or "")[:SUMMARY_INPUT_CHARS])


def _outside_longer(text: str, name: str, longer: Iterable[str]) -> bool:
    covered: set[int] = set()
    for other in longer:
        for match in re.finditer(re.escape(other), text):
            covered.update(range(match.start(), match.end()))
    return any(
        not set(range(match.start(), match.end())) <= covered
        for match in re.finditer(re.escape(name), text)
    )


def check_candidate(
    text: str, symbol: str, name: str | None, all_names: Iterable[str]
) -> str:
    """``mentioned`` or ``not_mentioned`` for one candidate (``text`` from ``source_text``).

    ``all_names`` are the keys of every listed name (``name_variants`` of the
    master), used to skip a name that only appears inside a longer one.
    """

    code = _key(symbol)
    if code and re.search(rf"(?<![0-9a-z]){re.escape(code)}(?![0-9a-z])", text):
        return MENTIONED
    names = list(all_names)
    for variant in name_variants(name):
        longer = [
            other for other in names if len(other) > len(variant) and variant in other
        ]
        if variant in text and _outside_longer(text, variant, longer):
            return MENTIONED
    return NOT_MENTIONED
