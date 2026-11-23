"""Theme evidence checker (``themes verify``), offline.

``fixtures/theme_evidence/mops_t05st03_2327.html`` is a trimmed copy of the
MOPS 公司基本資料 page of 2327 國巨 fetched 2026-11-24 (rows other than 股票代號,
主要經營業務, 公司成立日期 and 英文簡稱 removed; the script line is added to check that
scripts are not page text).
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import worker.theme_evidence as evidence_module
from app.migrations import upgrade_database
from app.models import Instrument
from app.theme_table import validate_theme_table
from worker.theme_evidence import (
    PAGES_INDEX,
    EvidenceFetchError,
    PageStore,
    check_member,
    normalize_text,
    page_text,
    verify_table,
)

PAGES = Path(__file__).parent / "fixtures" / "theme_evidence"
URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st03?co_id=2327"
# The same saved page under a non-MOPS URL: whole-page matching, no co_id check.
OTHER_URL = "https://www.example.com/yageo-profile"
TYPES = {("TWSE", "2327"): "stock", ("TWSE", "0050"): "etf"}


def _table(url=URL):
    return {
        "schema_version": "theme-table/v1",
        "table": "themes_v1",
        "version": "2026.11.24",
        "themes": [
            {
                "id": "passive",
                "name": "被動元件",
                "description": "電容、電阻、電感",
                "keywords": ["被動元件", "電阻", "MLCC"],
                "valid_from": "2026-11-24",
                "members": [
                    {
                        "instrument": "TWSE:2327",
                        "name": "國巨",
                        "relation": "core_business",
                        "relevance": "high",
                        "evidence": [
                            {
                                "url": url,
                                "title": "公開資訊觀測站 公司基本資料：國巨",
                                "quote": "被動元件、電阻原料半成品 天線、主動元件",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _member(table):
    return table["themes"][0]["members"][0]


@pytest.fixture
def pages():
    return PageStore(pages_dir=PAGES)


def test_matching_member_passes(pages):
    table = _table()
    assert validate_theme_table(table) == []
    result = verify_table(table, pages, TYPES)
    assert result == {"status": "success", "checked": 1, "passed": 1, "failures": []}


# AC-2: the three failures


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (OTHER_URL, "evidence[0].quote: not found on page"),
        (URL, "evidence[0].quote: not found in 主要經營業務"),
    ],
)
def test_quote_not_on_page_fails(pages, url, expected):
    table = _table(url)
    _member(table)["evidence"][0]["quote"] = "被動元件、積層陶瓷電容"
    result = verify_table(table, pages, TYPES)
    assert result["status"] == "failed"
    assert result["failures"] == [
        {
            "location": "themes[0](passive).members[0](TWSE:2327)",
            "errors": [expected],
        }
    ]


def test_mops_quote_from_another_field_fails(pages):
    table = _table()
    table["themes"][0]["keywords"].append("國巨")
    _member(table)["evidence"][0]["quote"] = "國巨*"
    assert check_member(table["themes"][0], _member(table), pages, TYPES) == [
        "evidence[0].quote: not found in 主要經營業務"
    ]
    # The same text passes as a whole-page quote on a non-MOPS page.
    _member(table)["evidence"][0]["url"] = OTHER_URL
    assert check_member(table["themes"][0], _member(table), pages, TYPES) == []


def test_mops_co_id_must_be_the_member_symbol(pages):
    table = _table()
    _member(table)["instrument"] = "TWSE:2492"
    errors = check_member(
        table["themes"][0], _member(table), pages, {("TWSE", "2492"): "stock"}
    )
    assert errors == ["evidence[0].url: co_id=2327 is not 2492"]


def test_keywords_match_case_insensitively(pages):
    table = _table(OTHER_URL)
    table["themes"][0]["keywords"] = ["yageo"]
    _member(table)["evidence"][0]["quote"] = "國巨*"
    assert check_member(table["themes"][0], _member(table), pages, TYPES) == [
        "evidence[0].quote: no theme keyword"
    ]
    _member(table)["evidence"][0]["quote"] = "YAGEO"
    assert check_member(table["themes"][0], _member(table), pages, TYPES) == []


def test_quote_from_script_is_not_page_text(pages):
    table = _table(OTHER_URL)
    table["themes"][0]["keywords"].append("積層陶瓷電容")
    _member(table)["evidence"][0]["quote"] = "積層陶瓷電容龍頭"
    assert check_member(table["themes"][0], _member(table), pages, TYPES) == [
        "evidence[0].quote: not found on page"
    ]


def test_quote_without_theme_keyword_fails(pages):
    table = _table()
    _member(table)["evidence"][0]["quote"] = "機器設備、零件製造及銷售。"
    result = verify_table(table, pages, TYPES)
    assert result["status"] == "failed"
    assert result["failures"][0]["errors"] == ["evidence[0].quote: no theme keyword"]


@pytest.mark.parametrize(
    ("instrument", "expected"),
    [
        ("TWSE:0050", "instrument_type=etf is not a stock"),
        ("TPEx:9999", "unknown instrument"),
    ],
)
def test_instrument_that_is_not_a_stock_fails(pages, instrument, expected):
    table = _table(OTHER_URL)
    _member(table)["instrument"] = instrument
    result = verify_table(table, pages, TYPES)
    assert result["status"] == "failed"
    assert result["failures"][0]["errors"] == [expected]


# Selection, missing pages and keywords


def test_page_missing_from_saved_pages_fails(pages):
    table = _table()
    _member(table)["evidence"][0]["url"] = OTHER_URL + "-missing"
    assert check_member(table["themes"][0], _member(table), pages, TYPES) == [
        "evidence[0].url: page not in saved pages"
    ]


def test_theme_without_keywords_cannot_be_verified(pages):
    table = _table()
    del table["themes"][0]["keywords"]
    result = verify_table(table, pages, TYPES)
    assert result["failures"] == [
        {"location": "themes[0](passive)", "errors": ["keywords required to verify"]}
    ]


def test_since_and_theme_filters_select_members(pages):
    table = _table()
    broken = copy.deepcopy(table["themes"][0])
    broken.update(id="old", valid_from="2026-01-01")
    broken.pop("keywords")
    table["themes"].append(broken)
    assert verify_table(table, pages, TYPES, since=date(2026, 11, 24))["status"] == (
        "success"
    )
    assert verify_table(table, pages, TYPES, theme_ids=["passive"])["checked"] == 1
    assert verify_table(table, pages, TYPES, theme_ids=["nope"])["errors"] == [
        "unknown theme id: ['nope']"
    ]


def test_keywords_schema_rejects_empty_words():
    table = _table()
    table["themes"][0]["keywords"] = ["被動元件", " "]
    assert validate_theme_table(table) == [
        "themes[0](passive).keywords: non-empty list of words required"
    ]


def test_normalize_ignores_whitespace_markup_and_width():
    text = normalize_text(page_text("<p>ＡＢＦ&nbsp;載板<br>製造</p>".encode()))
    assert normalize_text("ABF 載板製造") in text


def test_page_text_uses_declared_charset():
    body = "<meta charset='big5'>被動元件".encode("big5")
    assert "被動元件" in page_text(body)


def test_fetch_saves_pages_and_offline_reread_matches(tmp_path):
    body = (PAGES / "mops_t05st03_2327.html").read_bytes()
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "2327" in str(request.url):
            return httpx.Response(
                200, content=body, headers={"content-type": "text/html; charset=UTF-8"}
            )
        return httpx.Response(403)

    sleeps = []
    store = PageStore(
        save_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )
    table = _table()
    assert verify_table(table, store, TYPES)["status"] == "success"
    with pytest.raises(EvidenceFetchError, match="HTTP 403"):
        store.text(URL.replace("2327", "2492"))
    store.text(URL)  # cached: no third request
    assert len(calls) == 2 and sleeps == [evidence_module.FETCH_DELAY_SECONDS]
    index = json.loads((tmp_path / PAGES_INDEX).read_text(encoding="utf-8"))
    assert list(index) == [URL]
    assert verify_table(table, PageStore(pages_dir=tmp_path), TYPES)["passed"] == 1


def test_cli_verify_exits_1_on_failure(tmp_path, monkeypatch, capsys):
    import worker.cli as cli

    table = _table()
    _member(table)["evidence"][0]["quote"] = "被動元件、不存在的字"
    path = tmp_path / "themes.json"
    path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(evidence_module, "_instrument_types", lambda: TYPES)
    monkeypatch.setattr(
        "sys.argv",
        [
            "worker.cli",
            "themes",
            "verify",
            "--file",
            str(path),
            "--pages-dir",
            str(PAGES),
        ],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert "not found in 主要經營業務" in capsys.readouterr().out


def test_cli_verify_rejects_bad_since(monkeypatch, capsys):
    import worker.cli as cli

    monkeypatch.setattr(
        "sys.argv", ["worker.cli", "themes", "verify", "--since", "11/24"]
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "--since must be YYYY-MM-DD" in capsys.readouterr().err


def test_instrument_types_read_twse_and_tpex_from_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'types.db'}")
    upgrade_database(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for exchange, symbol, kind in [
            ("TWSE", "2327", "stock"),
            ("TPEx", "6488", "stock"),
            ("TWSE", "0050", "etf"),
            ("TAIFEX", "TX", "futures"),
        ]:
            db.add(
                Instrument(
                    market="TW",
                    exchange=exchange,
                    symbol=symbol,
                    name=symbol,
                    instrument_type=kind,
                    status="active",
                )
            )
        db.commit()
    monkeypatch.setattr(evidence_module, "SessionLocal", factory)
    assert evidence_module._instrument_types() == {
        ("TWSE", "2327"): "stock",
        ("TPEx", "6488"): "stock",
        ("TWSE", "0050"): "etf",
    }
    engine.dispose()
