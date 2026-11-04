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


@pytest.fixture
def master_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _listed(db, symbol, name):
    from app.models import Instrument

    db.add(Instrument(exchange="TWSE", symbol=symbol, name=name, status="active"))
    db.commit()


def test_listed_name_keys_are_cached_until_the_master_names_change(
    master_db, monkeypatch
):
    # #475: news_ai_map no longer recomputes every master name per request.
    import app.news_candidate_check as module
    from app.models import Instrument

    monkeypatch.setattr(module, "_listed_keys", (None, frozenset()))
    computed: list[str] = []
    original = module.name_variants

    def counting(name):
        computed.append(name)
        return original(name)

    monkeypatch.setattr(module, "name_variants", counting)
    _listed(master_db, "1605", "華新")
    _listed(master_db, "2492", "華新科")
    first = module.listed_name_keys(master_db)
    assert first == name_variants("華新") | name_variants("華新科")
    assert len(computed) == 2
    # Unchanged master: the cached keys, nothing recomputed.
    assert module.listed_name_keys(master_db) is first
    assert len(computed) == 2

    # A new listing is a change.
    _listed(master_db, "3711", "日月光投控")
    added = module.listed_name_keys(master_db)
    assert "日月光" in added and len(computed) == 5
    # A rename (another process's worker writes it) is a change.
    row = master_db.query(Instrument).filter_by(symbol="2492").one()
    row.name = "華新科技"
    master_db.commit()
    renamed = module.listed_name_keys(master_db)
    assert "華新科技" in renamed and "華新科" not in renamed
    # A removed row is a change.
    master_db.delete(row)
    master_db.commit()
    removed = module.listed_name_keys(master_db)
    assert "華新科技" not in removed and "華新" in removed
    calls = len(computed)
    assert module.listed_name_keys(master_db) is removed
    assert len(computed) == calls


def test_an_empty_master_has_no_keys(master_db, monkeypatch):
    import app.news_candidate_check as module

    monkeypatch.setattr(module, "_listed_keys", (None, frozenset()))
    assert module.listed_name_keys(master_db) == frozenset()
    _listed(master_db, "1605", "華新")
    assert "華新" in module.listed_name_keys(master_db)
