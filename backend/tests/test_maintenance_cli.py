"""``worker.cli maintenance on|off|status`` and the backfill and backtest guard (#468).

The CLI runs as a subprocess on a data directory under tmp_path. A running scheduler
is a process holding ``<data>/locks/serve.lock`` (worker.serve holds it for as long as
it runs), a running job one holding its job lock; both through ``worker.job lock``.
A refused command exits before it opens the database or the network; the guard is
asked directly for the cases that would start one.

fcntl locks: Linux only, like the scheduler (#333).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import worker.job as job

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="fcntl locks: Linux only (#333)"
)
REFUSED = 75


def cli(data: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("STOCK_DB_PATH", "STOCK_RAW_DIR")
    }
    env.update(STOCK_DATA_DIR=str(data), PYTHONPATH=str(ROOT / "backend"))
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "worker.cli", *argv],
        cwd=ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


class Holder:
    """A process holding the lock NAME of DATA (serve, daily or news) until closed."""

    def __init__(self, data: Path, name: str) -> None:
        self.path = job.lock_path(data, name)
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "worker.job",
                "lock",
                str(self.path),
                "--",
                sys.executable,
                "-c",
                "import time; time.sleep(120)",
            ],
            cwd=ROOT / "backend",
        )
        deadline = time.monotonic() + 30
        while not (self.path.exists() and job.lock_held(self.path)):
            assert time.monotonic() < deadline, f"{self.path} not held"
            time.sleep(0.05)

    def close(self) -> None:
        self.process.kill()
        self.process.wait(timeout=30)


@pytest.fixture
def data(tmp_path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def serve_running(data):
    holder = Holder(data, job.SERVE_LOCK)
    yield holder
    holder.close()


GUARDED = [
    ["backfill", "--start-date", "2026-11-03", "--end-date", "2026-11-04"],
    ["backtest", "--start-date", "2025-11-04", "--end-date", "2026-11-03"],
    ["events", "backfill", "--start-date", "2026-11-03", "--end-date", "2026-11-04"],
    ["instruments", "repair", "--apply"],
]


@pytest.mark.parametrize(
    "argv",
    GUARDED,
    ids=["backfill", "backtest", "events-backfill", "instruments-repair"],
)
def test_a_backfill_or_backtest_is_refused_while_the_scheduler_runs_without_maintenance(
    data, serve_running, argv
):
    """AC-3."""

    result = cli(data, *argv)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert (
        "the scheduler (worker.cli serve) is running and maintenance mode is off"
        in (result.stderr)
    )
    assert "python -m worker.cli maintenance on --reason" in result.stderr
    # Refused before anything was opened: no database, no run.
    assert not (data / "stock.db").exists()


def test_with_maintenance_on_the_guard_waits_for_a_job_still_running(
    data, serve_running
):
    assert cli(data, "maintenance", "on", "--reason", "回補").returncode == 0
    daily = Holder(data, "daily")
    try:
        result = cli(data, *GUARDED[0])
        assert result.returncode == REFUSED
        assert "a daily job started before it is still running" in result.stderr
    finally:
        daily.close()
    # Nothing running now: the backfill may start.
    assert job.maintenance_refusal(data, "backfill") is None


def test_the_guard_lets_a_backfill_start_with_maintenance_on_or_without_scheduler(
    data,
):
    assert job.maintenance_refusal(data, "backfill") is None  # no scheduler at all
    serve = Holder(data, job.SERVE_LOCK)
    try:
        assert job.maintenance_refusal(data, "backfill") is not None
        job.maintenance_on(data, "回補")
        assert job.maintenance_refusal(data, "backfill") is None
        job.maintenance_off(data, "回補完成")
        assert "maintenance mode is off" in job.maintenance_refusal(data, "backfill")
    finally:
        serve.close()


def test_a_dry_run_repair_is_not_guarded():
    from worker.cli import maintenance_guarded

    class Args:
        command, instruments_command, apply = "instruments", "repair", False

    assert maintenance_guarded(Args) is None


def test_maintenance_on_status_off_and_its_log(data, serve_running):
    assert cli(data, "maintenance", "on").returncode == 2  # --reason is required
    on = cli(data, "maintenance", "on", "--reason", "技術回測 2025-11～2026-11")
    assert on.returncode == 0, on.stderr
    state = json.loads(on.stdout)
    assert state["maintenance"] == "on" and state["already_on"] is False
    assert state["reason"] == "技術回測 2025-11～2026-11"
    assert state["serve_running"] is True and state["running_jobs"] == []
    marker = json.loads((data / "locks" / "maintenance").read_text(encoding="utf-8"))
    assert marker["reason"] == "技術回測 2025-11～2026-11"
    # A second on keeps the first since.
    again = json.loads(cli(data, "maintenance", "on", "--reason", "再一次").stdout)
    assert again["already_on"] is True and again["since"] == state["since"]
    status = json.loads(cli(data, "maintenance", "status").stdout)
    assert status["maintenance"] == "on" and status["reason"] == state["reason"]
    off = json.loads(cli(data, "maintenance", "off", "--reason", "回測完成").stdout)
    assert off["maintenance"] == "off" and off["was_on"] is True
    assert not (data / "locks" / "maintenance").exists()
    log = [
        json.loads(line)
        for line in (data / "logs" / "maintenance.log").read_text("utf-8").splitlines()
    ]
    assert [record["event"] for record in log] == ["on", "on_again", "off"]
    assert log[0]["reason"] == "技術回測 2025-11～2026-11"
    assert log[2]["reason"] == "回測完成" and log[2]["since"] == state["since"]
    assert isinstance(log[2]["hours"], float)
