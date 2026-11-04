"""tools/research news tools (#461): two-character hits by name, full-name aliases.

Each test builds a small stock.db file in its pytest temporary directory (the
tools read a file through ``mode=ro``) and checks the file is unchanged after.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Instrument, NewsItem, RawPayload

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hits_tool = _load("news_two_char_hits")
alias_tool = _load("news_full_name_aliases")

STOCKS = [
    ("TWSE", "2303", "聯電", "active"),
    ("TPEx", "4905", "台聯電", "active"),
    ("TWSE", "2317", "鴻海", "active"),
    ("TWSE", "1218", "泰山", "active"),
    ("TWSE", "2385", "群光", "active"),
    ("TWSE", "6412", "群電", "active"),
    ("TWSE", "2002", "中鋼", "active"),
    ("TWSE", "1723", "中碳", "active"),
    ("TWSE", "2013", "中鋼構", "active"),
    ("TWSE", "1229", "聯華", "active"),
    ("TWSE", "7001", "甲乙", "active"),
    ("TWSE", "7002", "甲乙丙", "active"),
    ("TWSE", "7003", "甲乙丁", "active"),
]


def _db(path: Path, news=(), raws=()) -> Path:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            Instrument(
                exchange=exchange,
                symbol=symbol,
                name=name,
                instrument_type="stock",
                status=status,
            )
            for exchange, symbol, name, status in STOCKS
        )
        for index, (title, summary, published, category, status) in enumerate(news):
            session.add(
                NewsItem(
                    canonical_key=f"k{index}",
                    category=category,
                    source_kind="media",
                    source_name="鉅亨網",
                    title=title,
                    summary=summary,
                    published_at=published,
                    collected_at=published,
                    display_time=published,
                    symbols_json=[],
                    theme_ids_json=[],
                    impact_scope="unknown",
                    impact_method="rule:exact-name-code/v2",
                    status=status,
                )
            )
        session.add_all(
            RawPayload(
                source="test",
                endpoint=endpoint,
                payload_path=str(payload),
                sha256="0" * 64,
                collected_at=datetime(2026, 11, 3),
            )
            for endpoint, payload in raws
        )
        session.commit()
    engine.dispose()
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Two-character hits ------------------------------------------------------------

# Stored instants are naive UTC: 2026-11-04 16:00 UTC is 11-05 00:00 in Taipei.
IN_PERIOD = datetime(2026, 11, 4, 16, 0)
NEWS = [
    ("鴻海營收創高", None, IN_PERIOD, "domestic", "active"),
    ("面板股法說", "鴻海、聯電，齊揚", IN_PERIOD, "domestic", "active"),
    # The code (with its name) and the longer name match without rule 4.
    ("鴻海(2317)董事會", None, IN_PERIOD, "domestic", "active"),
    ("台聯電公告", None, IN_PERIOD, "domestic", "active"),
    # A list item in the summary.
    ("建案推案", "將推桃園、中鋼、台南5案", IN_PERIOD, "domestic", "active"),
    # Outside the period (11-04 23:59 Taipei), another category, not active.
    ("聯電法說", None, datetime(2026, 11, 4, 15, 59), "domestic", "active"),
    ("聯電法說", None, IN_PERIOD, "international", "active"),
    ("聯電法說", None, IN_PERIOD, "domestic", "excluded"),
]


def test_two_char_hits_by_name_leave_out_code_and_longer_name_matches(tmp_path):
    db = _db(tmp_path / "stock.db", NEWS)
    before = _digest(db)

    data = hits_tool.measure(db, date(2026, 11, 5), date(2026, 11, 5), examples=1)

    assert _digest(db) == before
    assert (data["items"], data["items_with_hit"], data["hits"]) == (5, 3, 4)
    assert data["period"]["since"] == "2026-11-05"
    by_name = {row["name"]: row for row in data["names"]}
    assert [row["name"] for row in data["names"]] == ["鴻海", "中鋼", "聯電"]
    hon = by_name["鴻海"]
    assert (hon["symbol"], hon["instrument_name"], hon["items"]) == (
        "TWSE:2317",
        "鴻海",
        2,
    )
    assert hon["where"] == {"title_start": 1, "summary_segment": 1}
    assert hon["news_item_ids"] == [1, 2]
    assert hon["examples"] == [
        {
            "news_item_id": 1,
            "title": "鴻海營收創高",
            "field": "title",
            "context": "【鴻海】營收創高",
        }
    ]
    assert by_name["聯電"]["where"] == {"summary_segment": 1}
    assert by_name["中鋼"]["examples"][0]["context"] == "將推桃園、【中鋼】、台南5案"


def test_two_char_hits_cli_writes_json_and_prints_counts(tmp_path, capsys):
    db = _db(tmp_path / "stock.db", NEWS)
    out = tmp_path / "hits.json"

    assert (
        hits_tool.main(
            [
                "--db",
                str(db),
                "--since",
                "2026-11-04",
                "--until",
                "2026-11-05",
                "--category",
                "domestic",
                "--category",
                "international",
                "--out",
                str(out),
            ]
        )
        == 0
    )

    printed = json.loads(capsys.readouterr().out)
    written = json.loads(out.read_text(encoding="utf-8"))
    # 11-04 and the international item join the period.
    assert (printed["items"], printed["hits"], printed["names"]) == (7, 6, 3)
    assert written["categories"] == ["domestic", "international"]
    assert written["method"] == printed["method"]


def test_two_char_hits_cli_refuses_a_reversed_period(tmp_path):
    db = _db(tmp_path / "stock.db")
    with pytest.raises(SystemExit):
        hits_tool.main(
            [
                "--db",
                str(db),
                "--since",
                "2026-11-05",
                "--until",
                "2026-11-04",
                "--out",
                str(tmp_path / "x.json"),
            ]
        )


# Full-name aliases --------------------------------------------------------------


def test_name_forms_take_industry_words_off_the_end_while_three_characters_remain():
    assert alias_tool.name_forms("群光電能科技") == [
        ("群光電能科技", []),
        ("群光電能", ["科技"]),
    ]
    assert alias_tool.name_forms("中鋼碳素化學") == [
        ("中鋼碳素化學", []),
        ("中鋼碳素", ["化學"]),
    ]
    assert alias_tool.name_forms("聯華電子") == [("聯華電子", [])]


TWSE = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


def _twse(code, short, full):
    return {
        "公司代號": code,
        "公司簡稱": short,
        "公司名稱": full,
        "出表日期": "1151103",
    }


def test_full_name_aliases_include_the_names_without_industry_words(tmp_path):
    twse = tmp_path / "twse.json"
    twse.write_text(
        json.dumps(
            [
                _twse("6412", "群電", "群光電能科技股份有限公司"),
                _twse("1723", "中碳", "中鋼碳素化學股份有限公司"),
                _twse("2303", "聯電", "聯華電子股份有限公司"),
                # 中鋼結構 starts with 中鋼; 中鋼構 is its own short name.
                _twse("2013", "中鋼構", "中鋼結構股份有限公司"),
                # Both shorten to 甲乙丙丁…: neither keeps the shared name, and
                # 甲乙丙 itself is 7002's official name.
                _twse("7002", "甲乙丙", "甲乙丙丁科技股份有限公司"),
                _twse("7003", "甲乙丁", "甲乙丙丁工業股份有限公司"),
                # Not starting with a two-character name: no alias.
                _twse("2317", "鴻海", "鴻海精密工業股份有限公司"),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tpex = tmp_path / "tpex.json"
    tpex.write_text("[]", encoding="utf-8")
    db = _db(tmp_path / "stock.db", raws=[(TWSE, twse), (TPEX, tpex)])
    before = _digest(db)

    data = alias_tool.build(db, None)

    assert _digest(db) == before
    assert data["schema_version"] == "news-full-name-aliases/v2"
    rows = {(row["symbol"], row["alias"]): row for row in data["aliases"]}
    assert sorted(rows) == [
        ("1723", "中鋼碳素"),
        ("1723", "中鋼碳素化學"),
        ("2013", "中鋼結構"),
        ("2303", "聯華電子"),
        ("6412", "群光電能"),
        ("6412", "群光電能科技"),
        ("7002", "甲乙丙丁科技"),
        ("7003", "甲乙丙丁工業"),
    ]
    assert rows[("6412", "群光電能")]["stripped"] == ["科技"]
    assert rows[("6412", "群光電能")]["starts_with"] == ["TWSE:2385 群光"]
    assert data["left_out_shared"] == [
        {"alias": "甲乙丙丁", "stocks": ["TWSE:7002", "TWSE:7003"]}
    ]
    assert [source["raw_payload_id"] for source in data["sources"]] == [1, 2]


# Relation diff of two checkouts --------------------------------------------------

diff_tool = _load("news_relation_diff")

# A base checkout whose rule relates every item to 1229 聯華 and nothing else.
STUB_RULE = """
RELATION_METHOD = "rule:stub/v0"


class RelationMatcher:
    @classmethod
    def from_db(cls, session):
        return cls()

    def symbols(self, title, summary=None):
        return ["TWSE:1229"]
"""


def _stub_checkout(path: Path) -> Path:
    worker = path / "backend" / "worker"
    worker.mkdir(parents=True)
    (worker / "__init__.py").write_text("", encoding="utf-8")
    (worker / "news_batch.py").write_text(STUB_RULE, encoding="utf-8")
    return path


def test_relation_diff_of_the_same_checkout_is_empty(tmp_path):
    db = _db(tmp_path / "stock.db", NEWS)

    data = diff_tool.diff(db, date(2026, 11, 5), date(2026, 11, 5), ROOT)

    assert (data["added"], data["removed"]) == ([], [])
    assert data["base_method"] == data["method"]
    assert data["items"] == 5
    assert data["items_with_symbols"]["base"] == data["items_with_symbols"]["head"]


def test_relation_diff_lists_added_and_removed_pairs_and_draws_once(tmp_path):
    db = _db(tmp_path / "stock.db", NEWS)
    before = _digest(db)
    base = _stub_checkout(tmp_path / "base")

    data = diff_tool.diff(
        db, date(2026, 11, 5), date(2026, 11, 5), base, sample=6, seed=7
    )

    assert _digest(db) == before
    assert data["base_method"] == "rule:stub/v0"
    removed = [(row["news_item_id"], row["symbol"]) for row in data["removed"]]
    assert removed == [(item, "TWSE:1229") for item in range(1, 6)]
    added = [(row["news_item_id"], row["symbol"]) for row in data["added"]]
    assert added == [
        (1, "TWSE:2317"),
        (2, "TWSE:2303"),
        (2, "TWSE:2317"),
        (3, "TWSE:2317"),
        (4, "TPEx:4905"),
        (5, "TWSE:2002"),
    ]
    assert data["added"][0]["title"] == "鴻海營收創高"
    # Six added pairs fill a sample of six; the same seed draws the same.
    drawn = data["sample"]["drawn"]
    assert {(row["news_item_id"], row["symbol"]) for row in drawn} == set(added)
    assert {row["from"] for row in drawn} == {"added"}
    again = diff_tool.diff(
        db, date(2026, 11, 5), date(2026, 11, 5), base, sample=6, seed=7
    )
    assert again["sample"] == data["sample"]


def test_relation_diff_fills_a_short_sample_from_two_character_hits(tmp_path):
    db = _db(tmp_path / "stock.db", NEWS)

    # The same rule adds nothing, so the sample comes from the four
    # two-character-only pairs.
    data = diff_tool.diff(
        db, date(2026, 11, 5), date(2026, 11, 5), ROOT, sample=3, seed=7
    )

    drawn = data["sample"]["drawn"]
    assert len(drawn) == 3
    assert {row["from"] for row in drawn} == {"two_char_only"}
    assert {(row["news_item_id"], row["symbol"]) for row in drawn} <= {
        (1, "TWSE:2317"),
        (2, "TWSE:2303"),
        (2, "TWSE:2317"),
        (5, "TWSE:2002"),
    }


def test_relation_diff_cli_needs_a_seed_to_sample(tmp_path):
    db = _db(tmp_path / "stock.db")
    with pytest.raises(SystemExit):
        diff_tool.main(
            [
                "--db",
                str(db),
                "--since",
                "2026-11-05",
                "--until",
                "2026-11-05",
                "--base-root",
                str(ROOT),
                "--sample",
                "3",
                "--out",
                str(tmp_path / "x.json"),
            ]
        )
