"""tools/research/history_backfill.py: month by month, newest first, paused at the daily (#692)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    path = ROOT / "tools" / "research" / "history_backfill.py"
    spec = importlib.util.spec_from_file_location("history_backfill", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["history_backfill"] = module
    spec.loader.exec_module(module)
    return module


tool = _tool()


def _utc(taipei: str) -> datetime:
    local = datetime.fromisoformat(taipei).replace(tzinfo=tool.TAIPEI)
    return local.astimezone(timezone.utc)


def test_months_are_newest_first_and_cut_to_the_range():
    assert tool.months_newest_first(date(2012, 4, 25), date(2012, 6, 3)) == [
        (date(2012, 6, 1), date(2012, 6, 3)),
        (date(2012, 5, 1), date(2012, 5, 31)),
        (date(2012, 4, 25), date(2012, 4, 30)),
    ]


def test_a_month_waits_from_21_00_to_23_30_taipei():
    assert tool.pause_seconds(_utc("2026-11-16T20:59:59")) == 0
    assert tool.pause_seconds(_utc("2026-11-16T21:00:00")) == 2.5 * 3600
    assert tool.pause_seconds(_utc("2026-11-16T23:29:00")) == 60
    assert tool.pause_seconds(_utc("2026-11-16T23:30:00")) == 0


def test_a_rerun_skips_the_finished_months_and_pauses_at_the_daily(tmp_path):
    ran: list[tuple[date, date]] = []
    slept: list[float] = []
    clock = iter([_utc("2026-11-16T20:00:00")] * 3 + [_utc("2026-11-16T21:10:00")] * 10)

    def backfill(start, end):
        ran.append((start, end))
        return (1 if start.month == 4 else 0), "{}"

    counts = tool.run(
        date(2012, 4, 25),
        date(2012, 6, 3),
        data_dir=tmp_path,
        environ={},
        backfill=backfill,
        now=lambda: next(clock),
        sleep=slept.append,
    )
    assert counts == {"done_before": 0, "ok": 2, "failed": 1}
    assert [start.month for start, _ in ran] == [6, 5, 4]
    assert slept == [140 * 60, 140 * 60]  # the 5th and 4th months start at 21:10

    ran.clear()
    again = tool.run(
        date(2012, 4, 25),
        date(2012, 6, 3),
        data_dir=tmp_path,
        environ={},
        backfill=backfill,
        now=lambda: _utc("2026-11-17T10:00:00"),
        sleep=slept.append,
    )
    assert again == {"done_before": 2, "ok": 0, "failed": 1}
    assert ran == [(date(2012, 4, 25), date(2012, 4, 30))]
    lines = [
        json.loads(line)
        for line in (tmp_path / "logs" / tool.PROGRESS_NAME)
        .read_text("utf-8")
        .splitlines()
    ]
    assert {line["event"] for line in lines} == {"start", "pause", "month", "end"}


def test_it_refuses_without_a_research_start(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("STOCK_SESSION_BASIS_START", raising=False)
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path))
    assert tool.main(["--from", "2012-04-25", "--to", "2012-05-08"]) == 2
    assert "STOCK_SESSION_BASIS_START" in capsys.readouterr().out


def _research_env(monkeypatch, data_dir: Path) -> None:
    # The settings the runbook gives the container (docs/ops/RESEARCH_DB.md).
    monkeypatch.setenv("STOCK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("STOCK_SESSION_BASIS_START", "2004-02-11")
    monkeypatch.setenv("STOCK_INDEX_HISTORY_START", "2004-02-01")
    monkeypatch.setenv("STOCK_HISTORY_CREATE_UNMATCHED", "1")
    monkeypatch.delenv("STOCK_DB_PATH", raising=False)
    (data_dir / "stock.db").write_bytes(b"")


def test_main_with_the_runbook_settings_runs_the_backfill(tmp_path, monkeypatch):
    """#701 review: STOCK_DATA_DIR=/data with the DB in it must not be refused."""

    _research_env(monkeypatch, tmp_path)
    (tmp_path / tool.MARKER_NAME).write_text(
        json.dumps({"purpose": tool.MARKER_PURPOSE}), encoding="utf-8"
    )
    ran: list[tuple[date, date]] = []
    monkeypatch.setattr(tool, "pause_seconds", lambda _now: 0.0)

    def backfill(start, end):
        ran.append((start, end))
        return 0, "{}"

    assert (
        tool.main(["--from", "2012-06-01", "--to", "2012-06-30"], backfill=backfill)
        == 0
    )
    assert ran == [(date(2012, 6, 1), date(2012, 6, 30))]


def test_main_refuses_a_volume_without_the_research_marker(
    tmp_path, monkeypatch, capsys
):
    _research_env(monkeypatch, tmp_path)
    called = []
    assert (
        tool.main(
            ["--from", "2012-06-01", "--to", "2012-06-30"],
            backfill=lambda *a: called.append(a) or (0, ""),
        )
        == 2
    )
    assert called == []
    assert tool.MARKER_NAME in capsys.readouterr().out
    (tmp_path / tool.MARKER_NAME).write_text('{"purpose": "production"}', "utf-8")
    assert tool.main(["--from", "2012-06-01", "--to", "2012-06-30"]) == 2


def _progress_lines(data_dir: Path) -> list[dict]:
    path = data_dir / "logs" / tool.PROGRESS_NAME
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_the_batch_ends_with_one_whole_database_check(tmp_path, monkeypatch):
    """#722 review: the monthly backfills skip it at the head, the batch does not.

    It runs after the last month, also when a month failed, and a result other
    than ok exits 3.
    """

    _research_env(monkeypatch, tmp_path)
    (tmp_path / tool.MARKER_NAME).write_text(
        json.dumps({"purpose": tool.MARKER_PURPOSE}), encoding="utf-8"
    )
    monkeypatch.setattr(tool, "pause_seconds", lambda _now: 0.0)
    checked: list[Path] = []

    def check(db: Path) -> dict:
        checked.append(db)
        return {"ok": True, "integrity_check": ["ok"], "foreign_key_violations": []}

    argv = ["--from", "2012-05-01", "--to", "2012-06-30"]
    assert tool.main(argv, backfill=lambda *_: (0, "{}"), integrity=check) == 0
    assert checked == [tmp_path / "stock.db"]
    events = [line["event"] for line in _progress_lines(tmp_path)]
    assert events[-3:] == ["month", "integrity", "end"]
    assert _progress_lines(tmp_path)[-1]["integrity_ok"] == 1

    def broken(_db: Path) -> dict:
        return {"ok": False, "integrity_check": ["*** in database main ***"]}

    # A failed month still ends with the check; the damaged database wins: 3.
    (tmp_path / "logs" / tool.PROGRESS_NAME).unlink()
    assert (
        tool.main(
            argv, backfill=lambda start, _end: (start.month - 5, ""), integrity=broken
        )
        == tool.INTEGRITY_FAILED_EXIT
    )
    lines = _progress_lines(tmp_path)
    assert [line["event"] for line in lines][-2:] == ["integrity", "end"]
    assert lines[-2]["ok"] is False and lines[-1]["failed"] == 1


def test_check_database_fails_on_a_foreign_key_row_and_an_unreadable_file(tmp_path):
    import sqlite3

    db = tmp_path / "stock.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, "
            "parent_id INTEGER REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO parent VALUES (1)")
        connection.execute("INSERT INTO child VALUES (1, 1)")
    connection.close()
    good = tool.check_database(db)
    assert good["ok"] is True and good["integrity_check"] == ["ok"]

    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO child VALUES (2, 9)")  # FK enforcement off
    connection.close()
    bad = tool.check_database(db)
    assert bad["ok"] is False and bad["foreign_key_violations"]

    not_a_db = tmp_path / "garbage.db"
    not_a_db.write_bytes(b"not a database" * 100)
    assert tool.check_database(not_a_db)["ok"] is False
    assert tool.check_database(tmp_path / "missing.db")["ok"] is False


# --weekend-sessions (Issue #790): one single-day backfill per listed weekend.
SESSIONS = [date(2012, 12, 22), date(2013, 2, 23), date(2013, 9, 14)]


def test_weekend_mode_runs_one_day_per_listed_session_in_the_range(tmp_path):
    ran: list[tuple[date, date]] = []
    slept: list[float] = []
    clock = iter([_utc("2026-11-16T20:00:00")] * 3 + [_utc("2026-11-16T21:10:00")] * 10)

    def backfill(start, end):
        ran.append((start, end))
        return 0, "{}"

    counts = tool.run(
        date(2012, 12, 1),
        date(2013, 3, 31),
        data_dir=tmp_path,
        environ={},
        backfill=backfill,
        now=lambda: next(clock),
        sleep=slept.append,
        weekend_sessions=SESSIONS,
    )
    assert counts == {"done_before": 0, "ok": 2, "failed": 0}
    assert ran == [
        (date(2013, 2, 23), date(2013, 2, 23)),
        (date(2012, 12, 22), date(2012, 12, 22)),
    ]
    assert slept == [140 * 60]  # the second day starts at 21:10
    lines = _progress_lines(tmp_path)
    assert lines[0]["mode"] == "weekend_sessions"
    assert [line["event"] for line in lines if "exit" in line] == ["weekend"] * 2


def test_weekend_and_month_progress_lines_do_not_mark_each_other_done(tmp_path):
    ran: list[tuple[date, date]] = []

    def backfill(start, end):
        ran.append((start, end))
        return 0, "{}"

    def go(first, last, sessions=None):
        ran.clear()
        return tool.run(
            first,
            last,
            data_dir=tmp_path,
            environ={},
            backfill=backfill,
            now=lambda: _utc("2026-11-17T10:00:00"),
            sleep=lambda _s: None,
            weekend_sessions=sessions,
        )

    # A finished month does not hide its weekend session from weekend mode.
    go(date(2012, 12, 1), date(2012, 12, 31))
    assert ran == [(date(2012, 12, 1), date(2012, 12, 31))]
    assert go(date(2012, 12, 1), date(2012, 12, 31), SESSIONS)["done_before"] == 0
    assert ran == [(date(2012, 12, 22), date(2012, 12, 22))]
    # A finished weekend day does not count as a finished one-day month.
    assert go(date(2012, 12, 22), date(2012, 12, 22))["done_before"] == 0
    assert ran == [(date(2012, 12, 22), date(2012, 12, 22))]
    # Each mode skips its own finished pieces on a rerun.
    assert go(date(2012, 12, 1), date(2012, 12, 31), SESSIONS)["done_before"] == 1
    assert go(date(2012, 12, 1), date(2012, 12, 31))["done_before"] == 1
    assert ran == []


def test_main_weekend_mode_uses_the_official_list(tmp_path, monkeypatch):
    import worker.sources as sources

    _research_env(monkeypatch, tmp_path)
    (tmp_path / tool.MARKER_NAME).write_text(
        json.dumps({"purpose": tool.MARKER_PURPOSE}), encoding="utf-8"
    )
    monkeypatch.setattr(tool, "pause_seconds", lambda _now: 0.0)
    ran: list[tuple[date, date]] = []

    def backfill(start, end):
        ran.append((start, end))
        return 0, "{}"

    argv = ["--from", "2012-12-01", "--to", "2018-12-31", "--weekend-sessions"]
    assert tool.main(argv, backfill=backfill, integrity=lambda _db: {"ok": True}) == 0
    expected = sorted(
        (
            day
            for day in sources.OFFICIAL_WEEKEND_SESSIONS
            if date(2012, 12, 1) <= day <= date(2018, 12, 31)
        ),
        reverse=True,
    )
    assert ran == [(day, day) for day in expected]
    assert len(ran) == 12
    assert all(start.weekday() >= 5 for start, _ in ran)
