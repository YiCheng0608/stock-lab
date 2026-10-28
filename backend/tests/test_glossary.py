"""The API glossary is the source of the in-place terms (UI_COPY_SPEC §7, #270)."""

from __future__ import annotations

import re
from pathlib import Path

from app.glossary import glossary_terms

FRONTEND_GLOSSARY = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "glossary.ts"
)
# Terms the candidate cards, theme pages and the stock research tab open in place.
IN_PLACE = {
    "candidate_score": "候選總分",
    "entry_zone": "進場區",
    "support": "停損／條件失效價",
    "target": "目標價",
    "rr": "風險報酬比 RR",
    "percentile": "百分位",
    "heat_rank": "熱度分數與排名",
    "group_components": "五分項",
    "event_data_pending": "事件資料待補",
}
FIELDS = ("plain_definition", "use", "how_to_read", "limitations")


def _frontend_terms() -> dict[str, dict[str, str]]:
    text = FRONTEND_GLOSSARY.read_text(encoding="utf-8")
    terms: dict[str, dict[str, str]] = {}
    for block in re.findall(r"\{\s*term_id: '[^}]*\}", text):
        fields = dict(re.findall(r"(\w+): '([^']*)'", block))
        terms[fields["term_id"]] = fields
    return terms


def test_in_place_terms_are_in_the_api_glossary_with_all_fields():
    terms = {term["term_id"]: term for term in glossary_terms()}
    for term_id, name in IN_PLACE.items():
        assert terms[term_id]["name"] == name
        assert all(terms[term_id][field] for field in FIELDS), term_id
        assert "percentile" not in terms[term_id]["name"].casefold()


def test_the_frontend_copy_matches_the_api_for_in_place_terms():
    api = {term["term_id"]: term for term in glossary_terms()}
    local = _frontend_terms()
    assert set(local) <= set(api), sorted(set(local) - set(api))
    for term_id in IN_PLACE:
        for field in ("name", *FIELDS):
            assert local[term_id][field] == api[term_id][field], (term_id, field)


def test_search_finds_a_term_by_its_chinese_alias():
    assert [term["term_id"] for term in glossary_terms(q="條件失效")] == ["support"]
    assert "percentile" in [term["term_id"] for term in glossary_terms(q="同榜百分位")]
