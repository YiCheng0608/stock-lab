"""The common strategy list tables (Issue #1014): migration 0035 and the API.

AC-1: a 0034 database with H2 rows (floats that a 15-digit text would round,
a null value, a zero run, two versions) moves into ``strategy_list_runs`` /
``strategy_list_items`` with every field the same, back to 0034 unchanged, and
up again the same; the fallback entry moves them too.  AC-3:
``/api/strategy-lists/h2`` answers as ``/api/h2`` and an unknown strategy is a
404.  ``test_h2_api_unchanged`` is AC-2.

#1021: ``recent_picks`` of the last 60 sessions' stored lists, counted again
here from each day's ``/api/h2`` (AC-1); ``backfill`` and ``worker.cli
strategy-lists backfill`` write day by day and a rerun writes nothing again
(AC-3).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import migrations, strategy_lists
from app.db import enable_sqlite_foreign_keys
from app.migration_revisions import REVISIONS
from app.migrations import upgrade_database
from app.models import StrategyListItem, StrategyListRun
from app.main import app
from test_h2_list import (  # noqa: F401 - factory and golden_db are fixtures
    DAYS,
    T,
    _alembic_config,
    _check_0034,
    _check_head,
    _shape,
    factory,
    golden_db,
)
from test_h2_api_unchanged import QUERIES
from worker.h2_list import backfill_h2, run_h2_list

CONFIG = {"source": "explore_research", "window": 240, "missing": "last, kept"}
RUNS = [
    # id, trading_date, version, definitions_sha256, status, universe, items,
    # config_json, computed_at
    (3, "2026-11-12", "explore_research_v2_X2", "a" * 64, "computed", 812, 3)
    + (json.dumps(CONFIG), "2026-11-12 10:06:01.123456"),
    (5, "2026-11-13", "explore_research_v2_X2", "a" * 64, "zero", 0, 0)
    + (json.dumps({}), "2026-11-13 10:06:00.000000"),
    (8, "2026-11-13", "older_version", "b" * 64, "computed", 790, 2)
    + (json.dumps(CONFIG), "2026-11-13 10:07:00.000000"),
]
ITEMS = [
    # id, h2_run_id, trading_date, instrument_id, version, rank, high_gap_240, close
    (11, 3, "2026-11-12", 1, "explore_research_v2_X2", 1, -0.012345678901234567, 51.3),
    (12, 3, "2026-11-12", 2, "explore_research_v2_X2", 2, 0.1 + 0.2 - 0.3 - 0.4, 7.07),
    (13, 3, "2026-11-12", 3, "explore_research_v2_X2", 3, None, 1234.5),
    (20, 8, "2026-11-13", 1, "older_version", 1, -1e-17, 50.0),
    (21, 8, "2026-11-13", 3, "older_version", 2, -0.5, 1200.0),
]


def _rows(path, sql):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def _old_rows(path):
    return (
        _rows(path, "SELECT * FROM h2_runs ORDER BY id"),
        _rows(path, "SELECT * FROM h2_items ORDER BY id"),
    )


def _seed(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.executemany(
            "INSERT INTO instruments (id, market, exchange, symbol, name, "
            "instrument_type, is_watchlisted, status, created_at) "
            "VALUES (?, 'TW', 'TWSE', ?, ?, 'stock', 0, 'active', '2026-01-01')",
            [(i, f"S{i}", f"N{i}") for i in (1, 2, 3)],
        )
        connection.executemany(
            f"INSERT INTO h2_runs VALUES ({','.join('?' * 9)})", RUNS
        )
        connection.executemany(
            f"INSERT INTO h2_items VALUES ({','.join('?' * 8)})", ITEMS
        )
        connection.commit()


def _check_moved(path):
    """The strategy list rows are RUNS and ITEMS, as strategy h2."""

    runs = _rows(
        path,
        "SELECT id, trading_date, version, definitions_sha256, status, "
        "universe_count, item_count, config_json, computed_at, strategy "
        "FROM strategy_list_runs ORDER BY id",
    )
    assert runs == [run + ("h2",) for run in RUNS]
    items = _rows(
        path,
        "SELECT id, run_id, trading_date, instrument_id, version, rank, values_json, "
        "close, strategy FROM strategy_list_items ORDER BY id",
    )
    assert [row[:6] + (row[7],) for row in items] == [
        item[:6] + (item[7],) for item in ITEMS
    ]
    assert {row[8] for row in items} == {"h2"}
    # Exactly the same float (or null), not a rounded one.
    assert [json.loads(row[6]) for row in items] == [
        {"high_gap_240": item[6]} for item in ITEMS
    ]
    # The model reads them back as stored.
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.connect() as connection:
            values = connection.execute(
                select(StrategyListItem.values_json).order_by(StrategyListItem.id)
            ).scalars()
            assert [value["high_gap_240"] for value in values] == [
                item[6] for item in ITEMS
            ]
            config = connection.execute(
                select(StrategyListRun.config_json).where(StrategyListRun.id == 3)
            ).scalar_one()
            assert config == CONFIG
    finally:
        engine.dispose()
    return runs, items


def test_up_down_and_up_again_keep_every_h2_row(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command

    path = tmp_path / "move.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = _alembic_config(engine)
    try:
        command.upgrade(config, "0034_h2_lists")
        _seed(path)
        before = _old_rows(path)
        assert before == (RUNS, ITEMS)

        command.upgrade(config, "0035_strategy_lists")
        up = _shape(path)
        _check_head(up)
        assert up["alembic"] == [("0035_strategy_lists",)]
        first = _check_moved(path)

        command.downgrade(config, "0034_h2_lists")
        down = _shape(path)
        _check_0034(down)
        assert down["tables"] == {"h2_runs", "h2_items", "mainstream_runs"}
        assert down["alembic"] == [("0034_h2_lists",)]
        assert _old_rows(path) == before

        command.upgrade(config, "0035_strategy_lists")
        assert _check_moved(path) == first
        assert _rows(path, "PRAGMA foreign_key_check") == []
        if REVISIONS[-1] != "0035_strategy_lists":
            command.upgrade(config, "head")
            assert _check_moved(path) == first
    finally:
        engine.dispose()


def test_the_downgrade_keeps_only_h2(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command

    path = tmp_path / "other.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = _alembic_config(engine)
    try:
        command.upgrade(config, "0034_h2_lists")
        _seed(path)
        command.upgrade(config, "0035_strategy_lists")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "INSERT INTO strategy_list_runs VALUES (40, '2026-11-13', 'x4', 'x4_v1', "
                "'c', 'computed', 9, 1, '{}', '2026-11-13 10:08:00.000000')"
            )
            connection.execute(
                "INSERT INTO strategy_list_items VALUES (41, 40, '2026-11-13', 2, "
                "'x4', 'x4_v1', 1, 7.0, '{\"score\": 1.5}')"
            )
            connection.commit()
        command.downgrade(config, "0034_h2_lists")
        # 0034 has no place for another strategy's list: it goes with the tables.
        assert _old_rows(path) == (RUNS, ITEMS)
    finally:
        engine.dispose()


def test_the_fallback_moves_an_older_databases_rows(tmp_path, monkeypatch):
    pytest.importorskip("alembic")
    from alembic import command

    # 0034's DDL, as Alembic made it.
    ddl_path = tmp_path / "ddl.db"
    engine = create_engine(f"sqlite:///{ddl_path.as_posix()}")
    try:
        command.upgrade(_alembic_config(engine), "0034_h2_lists")
    finally:
        engine.dispose()
    old_ddl = [
        row[0]
        for row in _rows(
            ddl_path,
            "SELECT sql FROM sqlite_master WHERE tbl_name IN ('h2_runs', 'h2_items') "
            "AND sql IS NOT NULL ORDER BY type DESC, tbl_name DESC",
        )
    ]
    # The fallback entry cannot stop at 0034: upgrade, then put the two tables
    # back as 0034 made them and undo the 0035 marker.
    monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    path = tmp_path / "fallback.db"

    def upgrade():
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        enable_sqlite_foreign_keys(engine)
        try:
            upgrade_database(engine)
        finally:
            engine.dispose()

    upgrade()
    with closing(sqlite3.connect(path)) as connection:
        for sql in old_ddl:
            connection.execute(sql)
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = '0035_strategy_lists'"
        )
        connection.commit()
    _seed(path)
    upgrade()
    shape = _shape(path)
    _check_head(shape)
    assert shape["fallback"] == [("0034_h2_lists",), ("0035_strategy_lists",)]
    first = _check_moved(path)
    # Again: nothing left to move, nothing changes.
    upgrade()
    assert _check_moved(path) == first


# --- AC-3: the API ---------------------------------------------------------


def test_the_registry_has_h2():
    assert set(strategy_lists.strategies()) == {"h2", "x4"}
    h2 = strategy_lists.strategy("h2")
    assert h2.version == "explore_research_v2_X2"
    with pytest.raises(strategy_lists.UnknownStrategy):
        strategy_lists.strategy("x9")


def test_the_h2_strategy_list_is_api_h2(factory):  # noqa: F811
    client = TestClient(app)
    # No list yet: the missing response, the same on both.
    missing = client.get("/api/strategy-lists/h2").json()
    assert missing.pop("recent_picks") is None
    assert missing == client.get("/api/h2").json()
    for day in (DAYS[10], DAYS[245], T):
        run_h2_list(day)
    for query in QUERIES:
        response = client.get(f"/api/strategy-lists/h2{query}")
        assert response.status_code == 200
        assert _without_recent(response.json()) == client.get(
            f"/api/h2{query}"
        ).json(), query
    assert len(client.get("/api/strategy-lists/h2").json()["items"]) == 20


def test_an_unknown_strategy_is_404(factory):  # noqa: F811
    run_h2_list(T)
    client = TestClient(app)
    for path in (
        "/api/strategy-lists/x9",
        f"/api/strategy-lists/x9?date={T.isoformat()}",
        "/api/strategy-lists/H2",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "unknown strategy" in response.json()["detail"]


def test_strategies_do_not_mix(factory, monkeypatch):  # noqa: F811
    """A second strategy on the same date writes and reads its own run."""

    run_h2_list(T)
    h2 = strategy_lists.strategy("h2")

    def compute(db, day):
        return strategy_lists.Computed(
            universe_count=1,
            entries=[strategy_lists.Entry(1, 1, 10.0, {"score": 0.25})],
        )

    def present(db, run, items, day):
        return {
            "status": run.status if run else "missing",
            "items": [
                {"instrument": {"id": item.instrument_id}, "values": item.values_json}
                for item in items
            ],
        }

    other = strategy_lists.Strategy(
        key="demo",
        version="demo_v1",
        definitions_sha256="d" * 64,
        config={},
        compute=compute,
        present=present,
    )
    monkeypatch.setattr(strategy_lists, "strategies", lambda: {"h2": h2, "demo": other})
    before = TestClient(app).get("/api/h2").json()
    with factory() as db:
        strategy_lists.write_list(db, other, T)
        strategy_lists.write_list(db, other, T)  # a rerun replaces it
        assert strategy_lists.read_list(db, "demo", None, recent=False) == {
            "status": "computed",
            "items": [{"instrument": {"id": 1}, "values": {"score": 0.25}}],
        }
        demo = strategy_lists.read_list(db, "demo", None)["recent_picks"]
        assert (demo["days"], [row["count"] for row in demo["items"]]) == (1, [1])
        assert strategy_lists.read_list(db, "demo", date(2000, 1, 3), recent=False) == {
            "status": "missing",
            "items": [],
        }
        runs = db.scalars(
            select(StrategyListRun.strategy).order_by(StrategyListRun.strategy)
        ).all()
        assert runs == ["demo", "h2"]
    client = TestClient(app)
    assert client.get("/api/h2").json() == before
    assert client.get("/api/strategy-lists/demo").json()["status"] == "computed"


def _without_recent(response: dict) -> dict:
    response = dict(response)
    response.pop("recent_picks")
    response["items"] = [
        {key: value for key, value in item.items() if key != "recent_picks"}
        for item in response["items"]
    ]
    return response


def _by_hand(client, days) -> dict[int, list[str]]:
    """Each stock's days among ``days``' stored lists, read one day at a time."""

    picked: dict[int, list[str]] = {}
    for day in days:
        body = client.get(f"/api/h2?date={day.isoformat()}").json()
        for item in body["items"]:
            picked.setdefault(item["instrument"]["id"], []).append(day.isoformat())
    return picked


def test_recent_picks_count_the_last_60_sessions_lists(factory):  # noqa: F811
    # 60 sessions back from T is DAYS[-60]; DAYS[-61] is out of the window, and
    # DAYS[-30] has no list: 6 of the 60 sessions have one.
    listed = [DAYS[-61], DAYS[-60], DAYS[-45], DAYS[-3], DAYS[-2], T]
    for day in listed:
        assert run_h2_list(day)["status"] == "success"
    client = TestClient(app)
    body = client.get("/api/strategy-lists/h2").json()
    recent = body["recent_picks"]
    window = listed[1:]
    assert (recent["sessions"], recent["days"], recent["since"]) == (
        60,
        5,
        DAYS[-60].isoformat(),
    )
    hand = _by_hand(client, window)
    assert {row["instrument"]["id"] for row in recent["items"]} == set(hand)
    today = {item["instrument"]["id"]: item["rank"] for item in body["items"]}
    for row in recent["items"]:
        days = hand[row["instrument"]["id"]]
        assert row["count"] == len(days)
        assert (row["first_date"], row["last_date"]) == (min(days), max(days))
        assert row["today_rank"] == today.get(row["instrument"]["id"])
    # The most often first, then the latest, then the symbol.
    keys = [
        (-row["count"], -date.fromisoformat(row["last_date"]).toordinal())
        for row in recent["items"]
    ]
    assert keys == sorted(keys)
    # The fixture is not trivial: counts differ and some are not in T's list.
    assert len({row["count"] for row in recent["items"]}) > 1
    assert any(row["today_rank"] is None for row in recent["items"])
    for item in body["items"]:
        row = next(
            r for r in recent["items"] if r["instrument"]["id"] == item["instrument"]["id"]
        )
        assert item["recent_picks"] == {
            key: row[key] for key in ("count", "first_date", "last_date")
        }
    # An asked date ends the window there: DAYS[-3]'s window has 4 lists.
    asked = client.get(f"/api/strategy-lists/h2?date={DAYS[-3].isoformat()}").json()
    assert (asked["recent_picks"]["days"], asked["recent_picks"]["since"]) == (
        4,
        DAYS[-61].isoformat(),
    )
    assert sum(row["count"] for row in asked["recent_picks"]["items"]) == sum(
        len(days) for days in _by_hand(client, listed[:4]).values()
    )


def _counts(make) -> tuple[int, int, list[str]]:
    with make() as db:
        runs = db.scalars(
            select(StrategyListRun.trading_date).where(StrategyListRun.strategy == "h2")
        ).all()
        items = db.scalars(
            select(StrategyListItem.id).where(StrategyListItem.strategy == "h2")
        ).all()
        return len(runs), len(items), sorted(day.isoformat() for day in runs)


def test_backfill_writes_each_session_once(factory):  # noqa: F811
    assert run_h2_list(DAYS[-2])["status"] == "success"
    with factory() as db:
        computed_at = db.scalar(
            select(StrategyListRun.computed_at).where(
                StrategyListRun.trading_date == DAYS[-2]
            )
        )
    first = backfill_h2(T, 4)
    assert first["status"] == "success"
    assert (first["sessions"], first["written"], first["kept"]) == (4, 3, 1)
    assert (first["since"], first["until"]) == (DAYS[-4].isoformat(), T.isoformat())
    runs, items, days = _counts(factory)
    assert days == [day.isoformat() for day in DAYS[-4:]]
    # A rerun writes nothing: the stored days are kept as they are.
    again = backfill_h2(T, 4)
    assert (again["written"], again["kept"]) == (0, 4)
    assert _counts(factory) == (runs, items, days)
    with factory() as db:
        assert (
            db.scalar(
                select(StrategyListRun.computed_at).where(
                    StrategyListRun.trading_date == DAYS[-2]
                )
            )
            == computed_at
        )
    # --force recomputes every day and still one list a day.
    forced = backfill_h2(T, 4, force=True)
    assert (forced["written"], forced["kept"]) == (4, 0)
    assert _counts(factory) == (runs, items, days)
    # No date: the window ends at the latest session.
    assert backfill_h2(None, 1)["until"] == T.isoformat()


def test_backfill_reports_a_day_it_cannot_compute(factory, monkeypatch):  # noqa: F811
    h2 = strategy_lists.strategy("h2")

    def compute(db, day):
        if day == DAYS[-2]:
            raise ValueError("no bars")
        return h2.compute(db, day)

    broken = strategy_lists.Strategy(
        key=h2.key,
        version=h2.version,
        definitions_sha256=h2.definitions_sha256,
        config=h2.config,
        compute=compute,
        present=h2.present,
    )
    with factory() as db:
        result = strategy_lists.backfill(db, broken, T, 3)
    assert result["status"] == "failed"
    assert result["written"] == 2
    assert result["failed"] == [
        {"date": DAYS[-2].isoformat(), "error": "ValueError: no bars"}
    ]
    assert _counts(factory)[2] == [DAYS[-3].isoformat(), T.isoformat()]


def test_the_backfill_command(factory, monkeypatch, capsys):  # noqa: F811
    import worker.cli as cli

    calls = []
    for key in ("h2", "x4"):
        monkeypatch.setattr(
            cli,
            f"backfill_{key}",
            lambda until, sessions, force, key=key: calls.append(
                (key, until, sessions, force)
            )
            or {"status": "success", "strategy": key},
        )
    monkeypatch.setattr(cli, "maintenance_guarded", lambda args: None)
    monkeypatch.setattr(sys, "argv", ["worker.cli", "strategy-lists", "backfill"])
    cli.main()
    assert calls == [("h2", None, 60, False), ("x4", None, 60, False)]
    argv = ["--strategy", "x4", "--sessions", "5", "--until", T.isoformat(), "--force"]
    monkeypatch.setattr(sys, "argv", ["worker.cli", "strategy-lists", "backfill", *argv])
    cli.main()
    assert calls[-1] == ("x4", T, 5, True)
    capsys.readouterr()
    monkeypatch.setattr(
        cli, "backfill_h2", lambda until, sessions, force: {"status": "failed"}
    )
    monkeypatch.setattr(
        sys, "argv", ["worker.cli", "strategy-lists", "backfill", "--strategy", "h2"]
    )
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 1


def test_the_backfill_holds_maintenance_mode_outside_the_daily_hours():
    import argparse

    from worker.cli import DAILY_WINDOW_REFUSED, maintenance_guarded

    args = argparse.Namespace(command="strategy-lists", strategy_lists_command="backfill")
    assert maintenance_guarded(args) == "strategy-lists backfill"
    assert "strategy-lists backfill" in DAILY_WINDOW_REFUSED
