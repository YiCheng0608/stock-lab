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
