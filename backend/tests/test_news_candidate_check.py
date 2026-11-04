"""Rule check of the news LLM's symbol candidates (#465, NEWS_SPEC §5)."""

from __future__ import annotations

import pytest

from app.news_candidate_check import (
    MENTIONED,
    NOT_MENTIONED,
    check_candidate,
    name_variants,
    source_text,
)
from worker.news_llm import SUMMARY_INPUT_CHARS

NAMES = {
    key
    for name in ("鴻海", "華新", "華新科", "台積電", "日月光投控", "台南-KY", "群創")
    for key in name_variants(name)
}


def _check(title, symbol, name, summary=""):
    return check_candidate(source_text(title, summary), symbol, name, NAMES)


@pytest.mark.parametrize(
    "title,summary,symbol,name",
    [
        # Production 11/04 copy: rule relations missed these two-character names.
        (
            "台股大逃殺暴跌1612點！郭哲榮「6明牌全翻黑」",
            "鴻海、廣達領跌",
            "2317",
            "鴻海",
        ),
        ("華新攜產業夥伴成立「華新世紀核能」", "", "1605", "華新"),
        ("台股震盪現契機 00918兼具股利與成長雙優勢", "", "00918", "大華優利高填息30"),
        ("日月光擴產", "", "3711", "日月光投控"),  # holding-company ending
        ("台南營收創高", "", "5906", "台南-KY"),  # listing marker
        ("Ｔ　Ｓ　Ｍ", "全形與空白：台 積 電", "2330", "台積電"),  # NFKC, whitespace
    ],
)
def test_a_name_or_code_in_the_sent_text_is_mentioned(title, summary, symbol, name):
    assert _check(title, symbol, name, summary) == MENTIONED


@pytest.mark.parametrize(
    "title,summary,symbol,name",
    [
        # The model's inference: the text names a peer, not the candidate.
        ("友達(2409)擴產", "友達宣布擴產", "2330", "台積電"),
        # 華新 only inside 華新科 (2492) is not 1605.
        ("華新科營收創高", "", "1605", "華新"),
        # A code touching other digits or letters is not the code.
        ("加權指數下跌123172點", "", "2317", "鴻海"),
        ("ticker A2317B", "", "2317", "鴻海"),
        # PR 473 review: a number with a unit is an amount, not a code.
        ("台股暴跌1612點", "", "1612", "宏泰"),
        ("台積電營收2330億元", "", "2330", None),
        ("外資賣超2317萬張", "", "2317", None),
        ("股價漲2317%", "", "2317", None),
        ("2026年展望", "", "2026", None),
        # A code not in the master is checked by its code alone.
        ("記憶體報價走揚", "", "6392", None),
    ],
)
def test_a_candidate_absent_from_the_sent_text_is_not_mentioned(
    title, summary, symbol, name
):
    assert _check(title, symbol, name, summary) == NOT_MENTIONED


def test_only_the_summary_the_model_was_sent_counts():
    padding = "。" * SUMMARY_INPUT_CHARS
    assert _check("標題", "2317", "鴻海", summary="鴻海" + padding) == MENTIONED
    assert _check("標題", "2317", "鴻海", summary=padding + "鴻海") == NOT_MENTIONED


def test_a_name_outside_its_longer_neighbour_still_counts():
    # 華新科 covers one 華新; the second 華新 stands alone.
    assert _check("華新科、華新同步上漲", "1605", "華新") == MENTIONED
