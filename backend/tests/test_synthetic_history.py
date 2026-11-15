"""tools/research/synthetic_history.py: the synthetic long history for timing (#752).

A small copy (ten sessions from 2024-09-30, two stocks, TAIEX) is tiled back
to 2024-06-03; the refusals (a research database's directory, a production
source) are checked first, before anything is written.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.models import Base

ROOT = Path(__file__).resolve().parents[1].parent


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
pr = _tool("portfolio_research")
tool = _tool("synthetic_history")

NOW = "2026-11-13 10:00:00"
BLOCK = [
    day
    for day in (date(2024, 9, 30) + timedelta(days=k) for k in range(14))
    if day.weekday() < 5
]  # ten sessions: 2024-09-30 … 2024-10-11
START = date(2024, 6, 3)


def _source(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    con = sqlite3.connect(path)
    rows = [
        (1, "TW", "TWSE", "2330", "台積電", "stock", "active"),
        (2, "TW", "TPEx", "6488", "環球晶", "stock", "active"),
        (3, "TW", "TWSE", "TAIEX", "TAIEX", "index", "active"),
    ]
    con.executemany(
        "insert into instruments (id, market, exchange, symbol, name, instrument_type, "
        "status, is_watchlisted, created_at) values (?, ?, ?, ?, ?, ?, ?, 0, ?)",
        [(*row, NOW) for row in rows],
    )
    for k, day in enumerate(BLOCK):
        for instrument_id in (1, 2, 3):
            price = 100.0 * instrument_id + k
            con.execute(
                "insert into market_bars (instrument_id, trading_date, open, high, low, "
                "close, adj_close, volume, turnover, turnover_status, source, collected_at, "
                "is_suspended) values (?, ?, ?, ?, ?, ?, ?, 1000000, 1e8, 'available', "
                "'twse', ?, 0)",
                (
                    instrument_id,
                    day.isoformat(),
                    price,
                    price + 1,
                    price - 1,
                    price,
                    price,
                    NOW,
                ),
            )
        for instrument_id in (1, 2):
            con.execute(
                "insert into chip_snapshots (instrument_id, trading_date, trust_buy, "
                "source, collected_at) values (?, ?, ?, 'twse', ?)",
                (instrument_id, day.isoformat(), float(k), NOW),
            )
        for exchange in ("TWSE", "TPEx"):
            con.execute(
                "insert into margin_lists (exchange, trading_date, source, endpoint, "
                "data_as_of, collected_at, raw_payload_id, member_count, members_json) "
                "values (?, ?, 'm', 'e', ?, ?, 1, 0, '{}')",
                (exchange, day.isoformat(), day.isoformat(), NOW),
            )
    # A real bar before the block is dropped (its day is tiled over).
    con.execute(
        "insert into market_bars (instrument_id, trading_date, close, adj_close, turnover, "
        "source, collected_at) values (3, '2024-09-27', 1, 1, 0, 'twse', ?)",
        (NOW,),
    )
    con.execute(
        "insert into corporate_actions (instrument_id, action_date, action_type, "
        "cash_dividend, details_json, source, collected_at) "
        "values (1, '2024-10-03', 'dividend', 1.0, '{}', 'twse', ?)",
        (NOW,),
    )
    for month, announced in (
        ("2024-08-01", "2024-10-05"),  # a late filing: dropped
        ("2024-09-01", "2024-10-09"),
        ("2024-10-01", "2024-11-08"),
    ):
        con.execute(
            "insert into monthly_revenues (instrument_id, revenue_month, revenue, "
            "prior_year_revenue, announcement_date, source, raw_payload_id, data_json, "
            "data_as_of, collected_at) values (1, ?, 10, 9, ?, 'mops', 1, '{}', 'x', ?)",
            (month, announced, NOW),
        )
    con.execute(
        "insert into fundamental_snapshots (instrument_id, period_end, fiscal_period, "
        "announcement_date, eps, data_json, source, collected_at) "
        "values (1, '2024-09-30', '2024Q3', '2024-11-14', 3.0, '{}', 'mops', ?)",
        (NOW,),
    )
    for day, title in (("2024-10-01", "董事會決議買回"), ("2024-10-06", "其他")):
        con.execute(
            "insert into events (instrument_id, event_date, event_type, title, "
            "details_json, source, collected_at) values "
            "(1, ?, 'material_information', ?, '{}', 'mops_material_information', ?)",
            (day, title, NOW),
        )
    con.commit()
    con.close()
    return path


@pytest.fixture
def source(tmp_path):
    (tmp_path / "copy").mkdir()
    return _source(tmp_path / "copy" / "stock.db")


def _rows(db: Path, sql: str, params=()):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


# --- the refusals (AC-1 decision 4) ------------------------------------------------


def test_it_refuses_a_directory_holding_the_research_marker(tmp_path, source, capsys):
    out = tmp_path / "research"
    out.mkdir()
    (out / "research-db.json").write_text('{"purpose": "research_history"}\n')
    code = tool.main(["--src", str(source), "--out", str(out), "--start", "2024-06-03"])
    assert code == 2
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert any("research-db.json" in problem for problem in refused)
    assert not (out / "stock.db").exists()
    assert not (out / "stock.db.partial").exists()


def test_it_refuses_a_production_source(tmp_path, source, monkeypatch, capsys):
    data = tmp_path / "prod"
    data.mkdir()
    (data / "stock.db").write_bytes(source.read_bytes())
    monkeypatch.setenv("STOCK_DATA_DIR", str(data))
    out = tmp_path / "synth"
    code = tool.main(["--src", str(data / "stock.db"), "--out", str(out)])
    assert code == 2
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert any(problem.startswith("source:") for problem in refused)
    assert not (out / "stock.db").exists()
    # The production directory by name, and a hard link to the production file.
    named = tmp_path / "stock-lab-data"
    named.mkdir()
    (named / "stock.db").write_bytes(source.read_bytes())
    assert tool.refusals(named / "stock.db", out, {})[0].startswith("source:")
    link = tmp_path / "link.db"
    link.hardlink_to(data / "stock.db")
    assert tool.refusals(link, out, {"STOCK_DATA_DIR": str(data)})[0].startswith(
        "source:"
    )
    assert tool.refusals(source, out, {"STOCK_DATA_DIR": str(data)}) == []


def test_it_refuses_an_existing_database_and_a_production_output(tmp_path, source):
    out = tmp_path / "synth"
    out.mkdir()
    (out / "stock.db").write_bytes(b"")
    assert any("already exists" in p for p in tool.refusals(source, out, {}))
    data = tmp_path / "prod"
    assert any(
        p.startswith("output:")
        for p in tool.refusals(source, data, {"STOCK_DATA_DIR": str(data)})
    )


# --- the tiles --------------------------------------------------------------------


def test_the_date_map_counts_back_from_both_ends():
    calendar = tool.weekdays(START, tool.LAST)
    assert calendar[-1] == date(2024, 9, 27) and calendar[0] == START
    pairs = tool.date_map(BLOCK, calendar)
    assert len(pairs) == len(calendar)
    mapped = {syn: src for src, syn in pairs}
    assert mapped["2024-09-27"] == "2024-10-11"
    assert mapped["2024-09-16"] == "2024-09-30"  # ten sessions back
    assert mapped["2024-09-13"] == "2024-10-11"  # the next tile


def test_the_synthetic_history(tmp_path, source, monkeypatch):
    monkeypatch.setattr(tool, "MIN_SPAN", 20)
    monkeypatch.setattr(tool, "MAX_SPAN", 40)
    out = tmp_path / "synth"
    line = tool.build(source, out, START, delisted=3)
    db = out / "stock.db"
    marker = json.loads((out / "synthetic-db.json").read_text(encoding="utf-8"))
    assert marker["purpose"] == "synthetic_scale"
    assert not (out / "research-db.json").exists()
    assert line["delisted_clones"] == 3 and line["block_sessions"] == 10
    calendar = tool.weekdays(START, tool.LAST)
    assert marker["synthetic_sessions"] == len(calendar)

    # Every synthetic weekday plus the copy's own sessions, once per instrument.
    days = [
        d
        for (d,) in _rows(
            db,
            "select trading_date from market_bars where instrument_id = 1 order by 1",
        )
    ]
    assert days == [d.isoformat() for d in calendar + BLOCK]
    mapped = {syn: src for src, syn in tool.date_map(BLOCK, calendar)}
    closes = dict(
        _rows(db, "select trading_date, close from market_bars where instrument_id = 2")
    )
    for syn, src in mapped.items():
        assert closes[syn] == 200.0 + BLOCK.index(date.fromisoformat(src))
    assert _rows(
        db,
        "select close from market_bars where instrument_id = 3 "
        "and trading_date = '2024-09-27'",
    ) == [(309.0,)]  # tiled, not the old row
    assert _rows(db, "select count(*) from chip_snapshots where instrument_id = 1")[0][
        0
    ] == len(days)
    assert _rows(db, "select count(*) from margin_lists")[0][0] == 2 * len(days)
    actions = [
        d
        for (d,) in _rows(
            db,
            "select action_date from corporate_actions "
            "where instrument_id = 1 order by 1",
        )
    ]
    assert actions[-1] == "2024-10-03" and len(actions) == 1 + sum(
        1 for src in mapped.values() if src == "2024-10-03"
    )

    # Revenues: blocks of two months; the late filing for 2024-08 is not copied.
    months = _rows(
        db,
        "select revenue_month, announcement_date from monthly_revenues "
        "where instrument_id = 1 order by 1",
    )
    assert months[-2:] == [("2024-09-01", "2024-10-09"), ("2024-10-01", "2024-11-08")]
    assert ("2024-08-01", "2024-09-08") in months and (
        "2024-07-01",
        "2024-08-09",
    ) in months
    assert months[0][0] >= START.isoformat()
    # Quarters: whole years, so the quarter of the year stays.
    quarters = _rows(
        db,
        "select period_end, announcement_date from fundamental_snapshots "
        "where instrument_id = 1 order by 1",
    )
    assert quarters == [("2024-09-30", "2024-11-14")]  # 2023-09-30 is before START
    # MOPS: the six calendar days 2024-10-01 … 10-06 laid back from 2024-09-29.
    events = [
        d
        for (d,) in _rows(
            db,
            "select event_date from events where instrument_id = 1 "
            "and title = '其他' order by 1",
        )
    ]
    assert (
        events[-1] == "2024-10-06" and "2024-09-29" in events and "2024-09-23" in events
    )

    # The delisted clones: a slice of their source's rows, ended by 2024-09-27.
    clones = _rows(
        db,
        "select id, symbol, status, exchange from instruments where id > 3 order by id",
    )
    assert [row[1] for row in clones] == ["X0001", "X0002", "X0003"]
    assert {row[2] for row in clones} <= {"delisted", "transferred"}
    for new_id, *_rest in clones:
        span = _rows(
            db,
            "select min(trading_date), max(trading_date), count(*) "
            "from market_bars where instrument_id = ?",
            (new_id,),
        )[0]
        assert span[1] <= "2024-09-27" and 20 <= span[2] <= 40
        assert (
            _rows(
                db,
                "select count(*) from chip_snapshots where instrument_id = ?",
                (new_id,),
            )[0][0]
            == span[2]
        )

    # The research tools read it as a copy: the panel has every session.
    market = pr.load_market(db, date(1990, 1, 1), tmp_path / "raw", fundamentals=True)
    assert market.panel.sessions == calendar + BLOCK
    assert len(market.panel.series) == 2 + 3


def test_the_clones_are_deterministic():
    calendar = tool.weekdays(date(2004, 2, 11), tool.LAST)
    first = tool.clones([1, 2, 3], 50, calendar, 100)
    assert first == tool.clones([1, 2, 3], 50, calendar, 100)
    for new_id, source, start, end in first:
        assert source in (1, 2, 3) and start <= end <= "2024-09-27"
        span = sum(1 for d in calendar if start <= d.isoformat() <= end)
        assert tool.MIN_SPAN <= span <= tool.MAX_SPAN
