"""tools/research/bar_exclusions.json (#839): the bars no research tool reads.

The list is docs/ops/RESEARCH_DB.md「研究工具的日線排除清單」: the three code
reuses of #702 (the old company and the new one's first 240 bars, decision
6915138263) and TPEx 2007-04-23～2007-11-30 (no corporate-action source, #821
decision 6917103976).  ``research_report.benchmark_universe`` and
``benchmark_bars`` are the one read of the stock／ipo bars of every panel tool
(``evidence_lib.load_panel``, ``portfolio_research.load_market``), so both
leave those bars out.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "research" / "research_report.py"
LIST = ROOT / "tools" / "research" / "bar_exclusions.json"

spec = importlib.util.spec_from_file_location("research_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
sys.modules.setdefault(spec.name, report)
spec.loader.exec_module(report)

REUSE = "https://github.com/YiCheng0608/stock-lab/issues/702#issuecomment-6915138263"
NO_ACTIONS = (
    "https://github.com/YiCheng0608/stock-lab/issues/821#issuecomment-6917103976"
)


def test_the_list_is_the_decisions():
    entries = json.loads(LIST.read_text(encoding="utf-8"))["entries"]
    assert [
        (e["exchange"], e["symbol"], e["first"], e["last"], e["reason"], e["decision"])
        for e in entries
    ] == [
        ("TWSE", "2432", None, "2024-05-28", "code_reuse", REUSE),
        ("TPEx", "6130", None, "2013-02-26", "code_reuse", REUSE),
        ("TPEx", "4415", None, "2016-05-19", "code_reuse", REUSE),
        ("TPEx", None, "2007-04-23", "2007-11-30", "no_corporate_actions", NO_ACTIONS),
    ]
    for entry in entries:
        if entry["reason"] != "code_reuse":
            continue
        # the old company, then the new one's first 240 bars (the longest lookback)
        assert entry["warmup_bars"] == 240
        assert entry["old_company_last"] < entry["new_company_first"] < entry["last"]
        assert set(entry["raw_payload_ids"]) == {
            "old_company_last",
            "new_company_first",
            "warmup_last",
        }
    assert len(report.load_exclusions()) == 4


def write_list(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "list.json"
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "entry",
    [
        {
            "exchange": "TWSE",
            "symbol": "1",
            "first": None,
            "last": "2020-01-01",
            "reason": "code_reuse",
        },
        {
            "exchange": "TWSE",
            "symbol": None,
            "first": None,
            "last": "2020-01-01",
            "reason": "other",
        },
        {
            "exchange": "TPEx",
            "symbol": None,
            "first": "2020-01-02",
            "last": "2020-01-01",
            "reason": "no_corporate_actions",
        },
    ],
)
def test_a_malformed_range_is_refused(tmp_path, entry):
    with pytest.raises(ValueError):
        report.load_exclusions(write_list(tmp_path, [entry]))


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


# (id, exchange, symbol): 1 is the reused TWSE code with its old company, 2 a
# TPEx stock across the 2007 range, 3 the reused TPEx code holding only the new
# company (a production copy: nothing old to keep out), 4 a TWSE stock, 5 a
# TPEx stock delisted inside the 2007 range.
INSTRUMENTS = (
    (1, "TWSE", "2432"),
    (2, "TPEx", "1234"),
    (3, "TPEx", "6130"),
    (4, "TWSE", "1101"),
    (5, "TPEx", "5678"),
)
DELISTED = {5}


@pytest.fixture
def db(tmp_path) -> Path:
    path = tmp_path / "stock.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    old = weekdays(date(2008, 8, 18), 6)  # the old 2432 ends 2008-08-25
    new = weekdays(date(2024, 5, 24), 6)  # its 240th new bar is 2024-05-28
    tpex = weekdays(date(2007, 11, 28), 4)  # 11-28, 11-29, 11-30, 12-03
    late_6130 = weekdays(date(2013, 2, 25), 3)  # 02-25, 02-26, 02-27
    ended = weekdays(date(2007, 4, 19), 4)  # 04-19, 04-20 | 04-23, 04-24
    days = {1: old + new, 2: tpex, 3: late_6130, 4: old + new, 5: ended}
    with Session(engine) as session:
        for instrument_id, exchange, symbol in INSTRUMENTS:
            session.add(
                Instrument(
                    id=instrument_id,
                    exchange=exchange,
                    symbol=symbol,
                    name=symbol,
                    instrument_type="stock",
                    status="delisted" if instrument_id in DELISTED else "active",
                )
            )
        for instrument_id, bars in days.items():
            for day in bars:
                session.add(
                    MarketBar(
                        instrument_id=instrument_id,
                        trading_date=day,
                        open=10.0,
                        high=10.0,
                        low=10.0,
                        close=10.0,
                        adj_close=10.0,
                        volume=1000,
                        source="test",
                    )
                )
        session.commit()
    engine.dispose()
    return path


EXPECTED = {
    # the old company and the new one up to its 240th bar are out
    1: [date(2024, 5, 29), date(2024, 5, 30), date(2024, 5, 31)],
    2: [date(2007, 12, 3)],
    # no old company in this database: the code_reuse range does not apply
    3: [date(2013, 2, 25), date(2013, 2, 26), date(2013, 2, 27)],
    4: [*weekdays(date(2008, 8, 18), 6), *weekdays(date(2024, 5, 24), 6)],
    5: [date(2007, 4, 19), date(2007, 4, 20)],
}


def test_benchmark_universe_leaves_the_excluded_bars_out(db):
    con = report.connect_read_only(db)
    try:
        instruments, listed = report.benchmark_universe(con, date(2004, 1, 1))
    finally:
        con.close()
    assert {
        instrument_id: [bar.trading_date for bar in item.bars]
        for instrument_id, item in instruments.items()
    } == EXPECTED
    assert 1 not in listed[date(2024, 5, 28)] and 4 in listed[date(2024, 5, 28)]
    assert listed[date(2007, 11, 30)] == []


def test_benchmark_bars_reads_what_benchmark_universe_reads(db):
    con = report.connect_read_only(db)
    try:
        streamed = {
            instrument_id: [bar.trading_date for bar in bars]
            for instrument_id, bars in report.benchmark_bars(con, date(2004, 1, 1))
        }
    finally:
        con.close()
    assert streamed == EXPECTED


def test_the_ranges_of_a_database(db):
    con = report.connect_read_only(db)
    try:
        ranges = report.excluded_ranges(con)
    finally:
        con.close()
    assert ranges == {
        1: [("", "2024-05-28")],
        2: [("2007-04-23", "2007-11-30")],
        3: [("2007-04-23", "2007-11-30")],
        5: [("2007-04-23", "2007-11-30")],
    }


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    tool_spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(tool_spec)
    sys.modules.setdefault(name, module)
    tool_spec.loader.exec_module(module)
    return module


def test_trade_research_counts_and_ends_only_the_bars_it_reads(db, tmp_path):
    """``bar_count`` (``bars_before`` + the panel position) and the ENDED day
    (``last_bar``) count only the bars outside the list, as the panel does."""

    ctx = _tool("trade_research").load(
        db, date(2024, 5, 29), date(2024, 5, 31), tmp_path / "raw"
    )
    # 2432: 6 old bars and the new company's first 3 here, all excluded
    assert ctx.bars_before.get(1, 0) == 0
    assert ctx.bars_before[4] == 9
    assert ctx.bars_before[5] == 2
    # 5's bars 2007-04-23 and 04-24 are excluded: it ends on 04-20
    assert ctx.last_bar == {5: date(2007, 4, 20)}


def test_explore_counts_a_delisting_on_the_last_bar_it_reads(db):
    explore = _tool("explore_research")
    assert explore.delisted_count(db, date(2007, 4, 1), date(2007, 4, 20)) == 1
    assert explore.delisted_count(db, date(2007, 4, 21), date(2007, 12, 31)) == 0
