"""Maintenance mode held by the backfill and backtest commands (#468 AC-3, AC-5) and
``worker.cli maintenance on|off|status``.

The guarded commands run in this process through ``worker.cli.main`` with their work
replaced by a fake that records what it sees, on a data directory under tmp_path; the
refusals and ``maintenance`` run the real CLI as a subprocess. A running job is a
process holding its job lock through ``worker.job lock``. A SIGKILL is a real one, of a
child holding maintenance mode.

fcntl locks: Linux only, like the scheduler (#333).
"""

from __future__ import annotations

import json
import os
import signal
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


def marker(data: Path) -> dict | None:
    return job.maintenance_state(data)


def log(data: Path) -> list[dict]:
    path = data / "logs" / "maintenance.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


GUARDED = {
    "backfill": (
        ["backfill", "--start-date", "2026-11-03", "--end-date", "2026-11-04"],
        "chunked_backfill",
    ),
    "backtest": (
        ["backtest", "--start-date", "2025-11-04", "--end-date", "2026-11-03"],
        "backtest",
    ),
    "events backfill": (
        [
            "events",
            "backfill",
            "--start-date",
            "2026-11-03",
            "--end-date",
            "2026-11-04",
        ],
        "run_event_backfill",
    ),
    "instruments repair --apply": (
        ["instruments", "repair", "--apply"],
        "run_instrument_repair",
    ),
}


def run_held(monkeypatch, capsys, data: Path, command: str, work=None) -> dict:
    """worker.cli.main for COMMAND with its work faked; returns what the work saw."""

    import worker.cli as cli_module

    argv, name = GUARDED[command]
    seen: dict = {}

    def fake(*args, **kwargs):
        seen["marker"] = marker(data)
        seen["status"] = job.maintenance_status(data)
        if work:
            work(seen)
        return {"status": "success"}

    monkeypatch.setattr(cli_module, name, fake)
    monkeypatch.setattr(cli_module, "DATA_DIR", data)
    monkeypatch.setattr(sys, "argv", ["worker.cli", *argv])
    try:
        cli_module.main()
    except SystemExit as exc:
        seen["exit"] = exc.code
    seen["stderr"] = capsys.readouterr().err
    return seen


# AC-5: held by the command, released however it ends ----------------------------------


@pytest.mark.parametrize("command", list(GUARDED))
def test_a_backfill_or_backtest_holds_maintenance_and_releases_it_at_the_end(
    data, serve_running, monkeypatch, capsys, command
):
    seen = run_held(monkeypatch, capsys, data, command)
    held = seen["marker"]
    assert held["command"] == command and held["owner"] == "command"
    assert held["pid"] == os.getpid() and held["host"] and held["token"]
    assert held["heartbeat_epoch"] >= held["since_epoch"]
    assert seen["status"]["maintenance"] == "on" and seen["status"]["serve_running"]
    # The decision's hint (6646001167): a run across 21:30 should start after 23:30.
    assert "預估會跨過 21:30 時，請改在 23:30 後開始" in seen["stderr"]
    assert marker(data) is None
    events = log(data)
    assert [e["event"] for e in events] == ["held", "released"]
    assert events[1]["outcome"] == "success" and events[1]["owner"] == command


def test_the_holder_beats_while_it_runs(data, monkeypatch, capsys):
    monkeypatch.setattr(job, "MAINTENANCE_HEARTBEAT_SECONDS", 0.2)

    def work(seen):
        first = marker(data)["heartbeat_epoch"]
        deadline = time.monotonic() + 30
        while marker(data)["heartbeat_epoch"] == first:
            assert time.monotonic() < deadline, "no heartbeat"
            time.sleep(0.05)
        seen["beat"] = marker(data)["heartbeat_epoch"] - first

    seen = run_held(monkeypatch, capsys, data, "backtest", work)
    assert seen["beat"] > 0
    assert marker(data) is None


def test_an_exception_releases_maintenance_too(data, monkeypatch, capsys):
    def work(seen):
        raise RuntimeError("official source down")

    with pytest.raises(RuntimeError):
        run_held(monkeypatch, capsys, data, "backfill", work)
    assert marker(data) is None
    released = log(data)[-1]
    assert released["event"] == "released"
    assert released["outcome"] == "RuntimeError: official source down"


def _holder(data: Path, command: str) -> subprocess.Popen:
    """A child that holds maintenance mode for COMMAND until it is signalled."""

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path; import worker.job as job\n"
            "with job.MaintenanceHold(Path(sys.argv[1]), sys.argv[2]):\n"
            "    print('held', flush=True); time.sleep(120)",
            str(data),
            command,
        ],
        cwd=ROOT / "backend",
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout.readline().strip() == "held"
    return process


def test_a_sigkilled_holder_leaves_its_marker_which_expires_after_10_minutes(data):
    """SIGKILL skips the finally: the marker stays, its heartbeat stops, and once it is
    MAINTENANCE_STALE_SECONDS old the marker is removed (serve calls this every minute)."""

    holder = _holder(data, "backtest")
    os.kill(holder.pid, signal.SIGKILL)
    holder.wait(timeout=30)
    left = marker(data)
    assert left and left["pid"] == holder.pid
    beat = left["heartbeat_epoch"]
    assert job.expire_stale_maintenance(data, now=beat + 9 * 60) is None
    assert marker(data) is not None
    expired = job.expire_stale_maintenance(data, now=beat + 10 * 60 + 1)
    assert expired["event"] == "expired" and expired["owner"] == "backtest"
    assert expired["pid"] == holder.pid
    assert marker(data) is None
    assert log(data)[-1] == expired
    # Daily and news run again: the job reads no marker.
    assert job.maintenance_status(data)["maintenance"] == "off"


def test_a_sigterm_releases_maintenance(data):
    """docker stop of the command: SIGTERM becomes SystemExit, the finally runs."""

    holder = _holder(data, "backfill")
    holder.send_signal(signal.SIGTERM)
    assert holder.wait(timeout=30) == 128 + signal.SIGTERM
    assert marker(data) is None
    assert log(data)[-1]["outcome"] == f"exit {128 + signal.SIGTERM}"


def test_a_command_is_refused_under_a_maintenance_turned_on_by_hand(
    data, serve_running
):
    """Review 6647096392 must 3: by hand is a deploy's init-db; deploy.sh turns it off
    with the command still running underneath, so the command does not start."""

    job.maintenance_on(data, "v1.3.0")
    result = cli(data, *GUARDED["backtest"][0])
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "目前是手動維護（部署中，原因：v1.3.0" in result.stderr
    assert "請等部署完成" in result.stderr
    assert marker(data)["owner"] == "manual"
    assert [e["event"] for e in log(data)] == ["on"]
    assert not (data / "stock.db").exists()


def _lose_by(data: Path, how: str):
    """What takes maintenance mode from a running holder."""

    def work(seen):
        if how == "removed":
            job.maintenance_path(data).unlink()
        elif how == "taken":
            job._write_marker(
                job.maintenance_path(data), {**marker(data), "token": "other:1:2"}
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(0.05)
        seen["carried_on"] = True

    return work


@pytest.mark.parametrize("how", ["removed", "taken", "beat_fails"])
def test_a_holder_that_loses_maintenance_stops_within_a_heartbeat(
    data, monkeypatch, capsys, how
):
    """Review 6647096392 must 1: expired after a pause (removed), someone else's marker
    (taken), or a beat that cannot write: the command stops with 70, not carries on."""

    monkeypatch.setattr(job, "MAINTENANCE_HEARTBEAT_SECONDS", 0.2)
    if how == "beat_fails":
        write = job._write_marker
        calls = []

        def failing(path, content):
            calls.append(path)
            if len(calls) > 1:  # the first is taking it
                raise OSError(28, "No space left on device")
            write(path, content)

        monkeypatch.setattr(job, "_write_marker", failing)
    started = time.monotonic()
    seen = run_held(monkeypatch, capsys, data, "backfill", _lose_by(data, how))
    assert seen["exit"] == job.MAINTENANCE_LOST_EXIT == 70
    assert "carried_on" not in seen
    assert time.monotonic() - started < 10
    assert "stopped, maintenance mode was lost" in seen["stderr"]
    events = [e["event"] for e in log(data)]
    assert events[:2] == ["held", "lost"]
    if how == "beat_fails":
        # Still its own marker: released on the way out, with the reason.
        assert events[-1] == "released" and "lost:" in log(data)[-1]["outcome"]
        assert "No space left on device" in log(data)[-1]["outcome"]
        assert marker(data) is None
    elif how == "taken":
        assert marker(data)["token"] == "other:1:2"  # not ours to remove


def test_two_commands_starting_at_once_take_it_one_only(data):
    """Review 6647096392 must 2: taking it is atomic (the marker lock)."""

    for attempt in range(5):
        go = data.parent / f"go{attempt}"
        script = (
            "import sys, time; from pathlib import Path; import worker.job as job\n"
            "go = Path(sys.argv[2])\n"
            "while not go.exists(): time.sleep(0.001)\n"
            "try:\n"
            "    with job.MaintenanceHold(Path(sys.argv[1]), sys.argv[3]):\n"
            "        print('held', flush=True); time.sleep(2)\n"
            "except job.MaintenanceRefused as exc:\n"
            "    print('refused', exc, flush=True); sys.exit(75)\n"
        )
        children = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(data), str(go), name],
                cwd=ROOT / "backend",
                stdout=subprocess.PIPE,
                text=True,
            )
            for name in ("backfill", "backtest")
        ]
        time.sleep(0.5)
        go.touch()
        outcomes = sorted(
            child.communicate(timeout=60)[0].split()[0] for child in children
        )
        assert outcomes == ["held", "refused"], attempt
        assert sorted(child.returncode for child in children) == [0, 75]
        assert marker(data) is None


def test_a_command_takes_over_the_marker_of_a_dead_holder(data, monkeypatch, capsys):
    holder = _holder(data, "backtest")
    os.kill(holder.pid, signal.SIGKILL)
    holder.wait(timeout=30)
    stale = {**marker(data), "heartbeat_epoch": time.time() - 11 * 60}
    job._write_marker(job.maintenance_path(data), stale)
    seen = run_held(monkeypatch, capsys, data, "backfill")
    assert seen["marker"]["command"] == "backfill"
    assert log(data)[-2]["took_over_from"] == "backtest"
    assert marker(data) is None


# AC-3 (decision 6646032625, option A): refused only for a running job or a live holder --


def test_with_the_scheduler_running_and_maintenance_off_the_command_turns_it_on(
    data, serve_running, monkeypatch, capsys
):
    assert job.maintenance_status(data)["maintenance"] == "off"
    seen = run_held(monkeypatch, capsys, data, "backfill")
    assert "exit" not in seen and seen["marker"]["command"] == "backfill"


def test_a_command_is_refused_while_a_daily_job_still_runs(data, serve_running):
    """AC-3: the daily started before maintenance; the command must not write alongside."""

    daily = Holder(data, "daily")
    try:
        result = cli(data, *GUARDED["backfill"][0])
    finally:
        daily.close()
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "a daily job that started before maintenance mode is still running" in (
        result.stderr
    )
    # Refused before any work: no database, and its marker taken back.
    assert not (data / "stock.db").exists()
    assert marker(data) is None
    assert [e["event"] for e in log(data)] == ["held", "released"]
    assert log(data)[1]["outcome"] == "refused: daily still running"


def test_a_command_is_refused_while_another_one_holds_maintenance(data, serve_running):
    """AC-3: one backfill or backtest at a time; the holder's marker is left alone."""

    holder = _holder(data, "backtest")
    try:
        held = marker(data)
        result = cli(data, *GUARDED["backfill"][0])
        assert result.returncode == REFUSED, result.stdout + result.stderr
        assert "maintenance mode is held by backtest" in result.stderr
        assert marker(data)["token"] == held["token"]
    finally:
        holder.send_signal(signal.SIGTERM)
        holder.wait(timeout=30)
    assert not (data / "stock.db").exists()


def test_a_dry_run_repair_is_not_guarded():
    from worker.cli import maintenance_guarded

    class Args:
        command, instruments_command, apply = "instruments", "repair", False

    assert maintenance_guarded(Args) is None


# maintenance on|off|status by hand, and off --only-manual for deploy.sh ----------------


def test_maintenance_on_status_off_and_its_log(data, serve_running):
    assert cli(data, "maintenance", "on").returncode == 2  # --reason is required
    on = cli(data, "maintenance", "on", "--reason", "init-db v1.3.0")
    assert on.returncode == 0, on.stderr
    state = json.loads(on.stdout)
    assert state["maintenance"] == "on" and state["already_on"] is False
    assert state["reason"] == "init-db v1.3.0" and state["owner"] == "manual"
    assert state["heartbeat_age_seconds"] is None  # by hand: never expires
    assert state["serve_running"] is True and state["running_jobs"] == []
    again = json.loads(cli(data, "maintenance", "on", "--reason", "再一次").stdout)
    assert again["already_on"] is True and again["since"] == state["since"]
    status = json.loads(cli(data, "maintenance", "status").stdout)
    assert status["maintenance"] == "on" and status["reason"] == state["reason"]
    off = json.loads(cli(data, "maintenance", "off", "--reason", "deployed").stdout)
    assert off["maintenance"] == "off" and off["was_on"] is True
    assert marker(data) is None
    events = log(data)
    assert [e["event"] for e in events] == ["on", "on_again", "off"]
    assert events[2]["since"] == state["since"] and isinstance(
        events[2]["hours"], float
    )


def test_off_only_manual_turns_off_by_hand_and_leaves_a_command_alone(data):
    def off_only_manual() -> dict:
        result = cli(
            data, "maintenance", "off", "--only-manual", "--reason", "deployed"
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    assert off_only_manual()["deploy_maintenance"] == "none"
    job.maintenance_on(data, "init-db v1.3.0")
    assert off_only_manual()["deploy_maintenance"] == "turned_off"
    assert marker(data) is None
    holder = _holder(data, "backtest")
    try:
        assert off_only_manual()["deploy_maintenance"] == "kept_command_held"
        assert marker(data)["command"] == "backtest"
    finally:
        holder.send_signal(signal.SIGTERM)
        holder.wait(timeout=30)
    refused = cli(data, "maintenance", "on", "--only-manual", "--reason", "x")
    assert refused.returncode == 2
