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
    "support": "停損",
    "target": "目標價",
    "rr": "風險報酬比 RR",
    "percentile": "百分位",
    "heat_rank": "熱度分數與排名",
    "group_components": "五分項",
    "event_data_pending": "事件資料待補",
    # The entry type badge on a candidate's first line (#491).
    "breakout_entry": "突破型",
    "pullback_entry": "回踩型",
    # The strategy behind 今日名單, named on the 策略說明 page and the 今日名單 head (#577).
    "trend_chips": "順勢籌碼型",
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
    # The screens say 停損; the old name still finds it (#581).
    assert [term["term_id"] for term in glossary_terms(q="條件失效價")] == ["support"]
    assert "percentile" in [term["term_id"] for term in glossary_terms(q="同榜百分位")]


def test_strategy_price_terms_do_not_promise_a_profit():
    # Issue 693: the rules behind 今日名單 have no evidence of an edge (docs/spec/evidence.md),
    # so the price terms describe the rule's prices, not a gain or an instruction to follow them.
    terms = {term["term_id"]: term for term in glossary_terms()}
    for term_id in ("rr", "target", "entry_zone", "breakout_entry", "pullback_entry"):
        text = "".join(terms[term_id][field] for field in FIELDS)
        for phrase in ("可能賺", "獲利", "可研究進場", "照停損與目標規劃"):
            assert phrase not in text, (term_id, phrase)
    assert "不是預期報酬" in terms["rr"]["limitations"]
