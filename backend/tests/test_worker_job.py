"""The scheduled job ``python -m worker.cli job daily|news`` (backend/worker/job.py, #313).

Most tests run the real job.py in a project tree of its own under tmp_path: a copy
of job.py next to a fake ``worker.cli`` whose ``job`` command runs that copy and
whose steps (daily, news, news-llm) are scripted through environment variables.
The job finds its checkout from its own location, so the git dir it inspects and
the PYTHONPATH it gives the worker are the tree's, never the real checkout's (the
lesson of #207). No worker, database, network or Claude call is involved there.

The fixture-database test runs the real worker on tools/verify/fixture_db.py with
the outside-facing steps faked (job_daily_child.py) and the job in this process.

Process trees: a job killed with SIGKILL must take its worker with it, so the
next run finds the run row's PID dead (schedule_runs._pid_alive) and the lock
free.

The job runs on Linux only (the backend image, #333): elsewhere every test but
the refusal is skipped; run them in the image (``docker run --rm <image> pytest
backend/tests``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import worker.job as job
from worker.schedule_runs import _pid_alive

ON_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(
    not ON_LINUX, reason="worker.job runs on Linux only (#333)"
)
ROOT = Path(__file__).resolve().parents[2]
JOB_SOURCE = ROOT / "backend" / "worker" / "job.py"
# wrapper_daily.txt, wrapper_news.txt: what the PowerShell wrapper before #313
# (tools/Invoke-WorkerJob.ps1 at 58dadca) wrote with the old fake python of
# test_worker_job_scripts.py (removed in #333): one daily run, three news runs with news-llm exit 1.
# Stored with LF and the data directory shortened; written back with CRLF.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "worker_job"

FAKE_CLI = r'''"""Fake worker.cli of tests/test_worker_job.py: `job` is the real job.py."""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["job"]:
        from worker import job

        with open(os.environ["FAKE_LOG"] + ".jobs", "a", encoding="utf-8") as jobs:
            jobs.write(f"{os.getpid()}\n")
        parser = argparse.ArgumentParser(prog="worker.cli")
        job.add_arguments(parser.add_subparsers(dest="command").add_parser("job"))
        args = parser.parse_args(argv)
        problem = job.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(job.run(args))
    step = argv[0]
    names = ("STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR", "STOCK_CLAUDE_CLI",
             "PYTHONPATH", "PYTHONIOENCODING", "STOCK_JOB_LOCK")
    record = {"step": step, "argv": argv, "pid": os.getpid(), "ppid": os.getppid(),
              "cwd": os.getcwd(), "utf8": sys.flags.utf8_mode,
              "env": {name: os.environ.get(name) for name in names}}
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")
    key = step.upper().replace("-", "_")
    release = os.environ.get(f"FAKE_{key}_UNTIL")
    deadline = time.monotonic() + float(os.environ.get(f"FAKE_{key}_SLEEP", "0"))
    while time.monotonic() < deadline and not (release and Path(release).exists()):
        time.sleep(0.05)
    print(json.dumps({"status": "success", "step": step, "note": "日誌"}, ensure_ascii=False))
    if step != "daily":
        print(f"{step}-stderr-line", file=sys.stderr)
    sys.exit(int(os.environ.get(f"FAKE_{key}_EXIT", "0")))


main()
'''

END_LINE = r"^===== (\S+) end exit=(\d+) seconds=\d+(?: news_llm_exit=(\S+))?\r?$"
SKIPPED_LINE = r"^===== skipped reason=(\w+) \((.*)\)\r?$"


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = root / "project"
        self.backend = self.project / "backend"
        worker = self.backend / "worker"
        worker.mkdir(parents=True)
        (worker / "__init__.py").write_text("", encoding="utf-8")
        shutil.copyfile(JOB_SOURCE, worker / "job.py")
        (worker / "cli.py").write_text(FAKE_CLI, encoding="utf-8")
        self.git_dir = self.project / ".git"
        self.git_dir.mkdir()
        self.data = root / "data"
        self.logs = self.data / "logs"
        self.calls_file = root / "calls.jsonl"

    def environment(self, extra_env=None, **fake) -> dict[str, str]:
        env = {**os.environ, "FAKE_LOG": str(self.calls_file)}
        for name in ("STOCK_CLAUDE_CLI", "PYTHONPATH", "STOCK_DATA_DIR"):
            env.pop(name, None)
        # Inherited from a job of the caller's, it must not reach the worker.
        env["STOCK_JOB_LOCK"] = "/inherited/daily.lock"
        env.update({f"FAKE_{key.upper()}": str(value) for key, value in fake.items()})
        env.update(extra_env or {})
        return env

    def command(self, name: str, *args: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "worker.cli",
            "job",
            name,
            "--data-dir",
            str(self.data),
            "--min-free-memory-gb",
            "0",
            *args,
        ]

    def start(self, name: str, *args: str, **fake) -> subprocess.Popen:
        return subprocess.Popen(
            self.command(name, *args),
            cwd=self.backend,
            env=self.environment(**fake),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )

    def run(self, name: str, *args: str, extra_env=None, **fake) -> SimpleNamespace:
        completed = subprocess.run(
            self.command(name, *args),
            cwd=self.backend,
            env=self.environment(extra_env, **fake),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
            check=False,
        )
        return SimpleNamespace(
            code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            log=self.log(name),
            calls=self.calls(),
        )

    def log(self, name: str) -> str:
        return "".join(
            path.read_bytes().decode("utf-8")
            for path in sorted(self.logs.glob(f"{name}-*.log"))
        )

    def calls(self) -> list[dict]:
        if not self.calls_file.exists():
            return []
        return [
            json.loads(line)
            for line in self.calls_file.read_text(encoding="utf-8").splitlines()
        ]

    def job_pids(self) -> list[int]:
        """The job processes (the interpreters running job.py), in start order."""

        path = Path(str(self.calls_file) + ".jobs")
        if not path.exists():
            return []
        return [int(line) for line in path.read_text(encoding="utf-8").split()]

    def steps(self) -> list[str]:
        return [call["step"] for call in self.calls()]

    def wait_for_call(self, count: int, timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            calls = self.calls()
            if len(calls) >= count:
                return calls[count - 1]
            time.sleep(0.05)
        raise AssertionError(f"no worker call #{count} within {timeout} s")


@pytest.fixture
def tree(tmp_path) -> Tree:
    if not ON_LINUX:
        pytest.skip("worker.job runs on Linux only (#333)")
    return Tree(tmp_path)


def end_line(log: str):
    return re.findall(END_LINE, log, re.MULTILINE)


def skipped_line(log: str):
    return re.search(SKIPPED_LINE, log, re.MULTILINE)


def force_kill(pid: int) -> None:
    os.kill(pid, signal.SIGKILL)


def wait_dead(pid: int, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


# Log layout and exit codes (OPERATIONS §6.3) ---------------------------------


def test_daily_log_layout(tree):
    result = tree.run("daily", "--trigger", "manual", "--date", "2026-10-16")
    assert result.code == 0, result.stderr
    assert tree.steps() == ["daily"]
    lines = result.log.splitlines()
    assert re.fullmatch(
        r"===== \S+\+08:00 start job=daily trigger=manual date=2026-10-16"
        r" force=False db=.+stock\.db free_mb=\d+",
        lines[0],
    )
    assert lines[1] == "--- stdout"
    assert '"note": "日誌"' in result.log
    assert "--- stderr" not in result.log and "news-llm" not in result.log
    assert [groups[1:] for groups in end_line(result.log)] == [("0", "")]
    assert result.stdout.startswith("daily exit=0 log=")
    call = tree.calls()[0]
    assert call["argv"] == ["daily", "--trigger", "manual", "--date", "2026-10-16"]
    assert call["utf8"] == 1 and call["cwd"] == str(tree.project)
    assert call["env"]["PYTHONPATH"] == str(tree.backend)
    assert call["env"]["STOCK_DATA_DIR"] == str(tree.data)
    assert call["env"]["STOCK_DB_PATH"] == str(tree.data / "stock.db")
    assert call["env"]["STOCK_RAW_DIR"] == str(tree.data / "raw")
    assert call["env"]["PYTHONIOENCODING"] == "utf-8"
    assert call["env"]["STOCK_CLAUDE_CLI"] is None


@pytest.mark.parametrize("code", [1, 2])
def test_the_daily_exit_code_is_the_worker_exit_code(tree, code):
    result = tree.run("daily", "--force", daily_exit=code)
    assert result.code == code
    assert "--force" in tree.calls()[0]["argv"]
    assert end_line(result.log)[0][1] == str(code)


def test_news_job_runs_news_llm_after_news_with_separate_sections(tree):
    result = tree.run("news", "--claude-cli", r"C:\tools\claude.exe", news_llm_exit=1)
    assert tree.steps() == ["news", "news-llm"]
    log = result.log
    positions = [
        log.index(marker)
        for marker in (
            "--- news stdout",
            "--- news stderr",
            "--- news end exit=0",
            "--- news-llm start claude_cli=C:\\tools\\claude.exe",
            "--- news-llm stdout",
            "--- news-llm stderr",
            "--- news-llm end exit=1",
        )
    ]
    assert positions == sorted(positions)
    assert log.index("news-stderr-line") < log.index("--- news-llm start")
    assert log.index("news-llm-stderr-line") > log.index("--- news-llm start")
    assert " news_llm=on" in log.splitlines()[0]
    # news-llm failing leaves the job's own exit code alone.
    assert result.code == 0
    assert [groups[1:] for groups in end_line(log)] == [("0", "1")]
    assert "news exit=0 news_llm_exit=1 log=" in result.stdout
    news_call, llm_call = tree.calls()
    assert news_call["env"]["STOCK_CLAUDE_CLI"] == r"C:\tools\claude.exe"
    assert llm_call["env"]["STOCK_CLAUDE_CLI"] == r"C:\tools\claude.exe"


def test_news_failure_still_runs_news_llm_and_keeps_the_job_exit_code(tree):
    result = tree.run("news", news_exit=1)
    assert tree.steps() == ["news", "news-llm"]
    assert result.code == 1
    assert "--- news end exit=1" in result.log
    assert "--- news-llm end exit=0" in result.log
    assert [groups[1:] for groups in end_line(result.log)] == [("1", "0")]


def test_news_llm_gets_no_date(tree):
    tree.run("news", "--date", "2026-10-16")
    news_call, llm_call = tree.calls()
    assert news_call["argv"] == ["news", "--date", "2026-10-16"]
    assert llm_call["argv"] == ["news-llm"]


def test_without_a_configured_path_the_worker_falls_back_to_path(tree):
    result = tree.run("news")
    assert tree.calls()[1]["env"]["STOCK_CLAUDE_CLI"] is None
    assert "--- news-llm start claude_cli=claude (PATH)" in result.log


def test_news_llm_can_be_switched_off(tree):
    result = tree.run("news", "--skip-news-llm")
    assert tree.steps() == ["news"]
    assert " news_llm=off" in result.log.splitlines()[0]
    assert "--- news-llm" not in result.log
    assert [groups[1:] for groups in end_line(result.log)] == [("0", "disabled")]


@pytest.mark.parametrize(
    "job_name, option, message",
    [
        ("daily", "--skip-news-llm", "--skip-news-llm applies only to the news job"),
        ("news", "--force", "--force applies only to the daily job"),
    ],
)
def test_options_of_the_other_job_are_refused(tree, job_name, option, message):
    result = tree.run(job_name, option)
    assert result.code == 2 and tree.steps() == []
    assert message in result.stderr
    assert not tree.logs.exists() or result.log == ""


# Checks before the run --------------------------------------------------------


def test_low_memory_skips_news_without_running_a_step(tree):
    result = tree.run("news", "--min-free-memory-gb", "1024")
    assert tree.steps() == [] and result.code == 0
    skipped = skipped_line(result.log)
    assert skipped.group(1) == "low_memory"
    assert "min_free_mb=1048576" in skipped.group(2)
    assert [groups[1:] for groups in end_line(result.log)] == [("0", "not_run")]


def test_low_memory_daily_runs_the_cli_to_record_the_skip(tree):
    result = tree.run("daily", "--min-free-memory-gb", "1024")
    assert result.code == 0
    assert tree.calls()[0]["argv"] == [
        "daily",
        "--trigger",
        "scheduler",
        "--skip-reason",
        "low_memory",
    ]


@pytest.mark.parametrize("linked", [False, True], ids=["git-dir", "linked-worktree"])
@pytest.mark.parametrize("marker", ["MERGE_HEAD", "index.lock"])
def test_a_git_operation_in_progress_skips_the_job(tree, marker, linked):
    target = tree.git_dir
    if linked:
        target = tree.root / "linked-git-dir"
        target.mkdir()
        shutil.rmtree(tree.git_dir)
        tree.git_dir.write_text(f"gitdir: {target.as_posix()}\n", encoding="utf-8")
    (target / marker).touch()
    result = tree.run("news")
    assert tree.steps() == [] and result.code == 0
    skipped = skipped_line(result.log)
    assert skipped.group(1) == "git_busy"
    # The marker that counted is the tree's own, not the real checkout's.
    assert Path(skipped.group(2).split("git_dir=", 1)[1]) == target
    daily = tree.run("daily")
    assert daily.calls[0]["argv"][-2:] == ["--skip-reason", "git_busy"]


def test_a_clean_git_dir_does_not_block_the_job(tree):
    result = tree.run("news")
    assert tree.steps() == ["news", "news-llm"]
    assert skipped_line(result.log) is None


def test_a_failed_git_pull_skips_the_job(tree):
    # GIT_DIR names a directory that does not exist, so git can neither pull nor
    # look upwards for another repository.
    missing = tree.root / "no-git-dir"
    result = tree.run("daily", "--git-pull", extra_env={"GIT_DIR": str(missing)})
    assert result.code == 0
    assert "--- git pull --ff-only" in result.log
    assert skipped_line(result.log).group(1) == "git_pull_failed"
    assert tree.calls()[0]["argv"][-2:] == ["--skip-reason", "git_pull_failed"]


# One job of each kind at a time (AC-3) ---------------------------------------


def test_a_second_daily_job_records_already_running(tree):
    release = tree.root / "release"
    first = tree.start("daily", daily_until=release, daily_sleep=90)
    try:
        tree.wait_for_call(1)
        second = tree.run("daily", daily_until=release, daily_sleep=90)
        assert second.code == 0, second.stderr
        assert tree.calls()[1]["argv"][-2:] == ["--skip-reason", "already_running"]
        # Only the worker of the job holding the lock is told its path (#336).
        lock = str(job.lock_path(tree.data, "daily"))
        assert [call["env"]["STOCK_JOB_LOCK"] for call in tree.calls()] == [lock, None]
        skipped = skipped_line(second.log)
        assert skipped.group(1) == "already_running"
        assert skipped.group(2) == f"lock={job.lock_path(tree.data, 'daily')}"
        # A news job has a lock of its own.
        news = tree.run("news", "--skip-news-llm")
        assert news.code == 0 and "already_running" not in news.log
    finally:
        release.touch()
        first.wait(timeout=60)
    assert first.returncode == 0
    assert len(end_line(tree.log("daily"))) == 2


def test_a_second_news_job_only_logs_the_skip(tree):
    release = tree.root / "release"
    first = tree.start("news", news_until=release, news_sleep=90)
    try:
        tree.wait_for_call(1)
        second = tree.run("news")
        assert second.code == 0 and tree.steps() == ["news"]
        assert "===== skipped reason=already_running" in second.log
        assert end_line(second.log)[-1][1:] == ("0", "not_run")
    finally:
        release.touch()
        first.wait(timeout=60)


def test_a_killed_job_takes_its_worker_along_and_leaves_no_lock(tree):
    first = tree.start("daily", daily_sleep=120)
    worker = tree.wait_for_call(1)
    # The interpreter running job.py: under a Windows venv, Popen's pid and the
    # worker's parent are launchers in front of the real interpreters.
    (job_pid,) = tree.job_pids()
    force_kill(job_pid)
    # Reap it first: on Linux job_pid is this test's own child (no launcher), a
    # zombie until waited for, and a zombie still answers os.kill(pid, 0).
    first.wait(timeout=30)
    assert wait_dead(job_pid)
    # The worker's parent was the job; once orphaned, init reaps it.
    assert wait_dead(worker["pid"]), "the worker outlived the killed job"
    started = time.monotonic()
    again = tree.run("daily")
    assert time.monotonic() - started < 60
    assert again.code == 0, again.stderr
    assert tree.calls()[1]["argv"] == ["daily", "--trigger", "scheduler"]
    assert "already_running" not in again.log
    # The killed run left a start line without an end line; the new one has both.
    assert again.log.count(" start job=daily") == 2
    assert len(end_line(again.log)) == 1


@linux_only
def test_the_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "locks" / "x.lock"
    first, second = job.FileLock(path), job.FileLock(path)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


@linux_only
def test_lock_runs_the_command_and_refuses_while_held(tmp_path):
    path = tmp_path / "locks" / "watchdog.lock"
    marker = tmp_path / "ran"
    command = [
        sys.executable,
        "-m",
        "worker.job",
        "lock",
        str(path),
        "--",
        sys.executable,
        "-c",
        f"open({str(marker)!r}, 'w').close(); print('child ran')",
    ]
    backend = ROOT / "backend"
    ran = subprocess.run(
        command, cwd=backend, capture_output=True, text=True, timeout=60
    )
    assert ran.returncode == 0 and ran.stdout.strip() == "child ran"
    assert marker.exists()
    marker.unlink()
    held = job.FileLock(path)
    assert held.acquire()
    try:
        refused = subprocess.run(
            command, cwd=backend, capture_output=True, text=True, timeout=60
        )
    finally:
        held.release()
    assert refused.returncode == job.LOCK_BUSY_EXIT
    assert "locked:" in refused.stderr and not marker.exists()


# Time limit -------------------------------------------------------------------


def test_daily_is_killed_at_the_time_limit(tree):
    started = time.monotonic()
    result = tree.run("daily", "--time-limit-minutes", "0.05", daily_sleep=120)
    assert time.monotonic() - started < 60
    assert result.code == job.TIMEOUT_EXIT
    assert "--- timeout: killed at the 0.05 minute limit of the daily job" in result.log
    assert end_line(result.log)[0][1] == str(job.TIMEOUT_EXIT)
    assert wait_dead(tree.calls()[0]["pid"])


def test_news_and_news_llm_share_the_time_limit(tree):
    result = tree.run("news", "--time-limit-minutes", "0.05", news_sleep=120)
    assert tree.steps() == ["news"]
    assert result.code == job.TIMEOUT_EXIT
    assert "--- news timeout: killed at the 0.05 minute limit" in result.log
    assert "--- news-llm timeout: not started" in result.log
    assert end_line(result.log)[0][1:] == (str(job.TIMEOUT_EXIT), "timeout")


# Log retention ----------------------------------------------------------------


def test_logs_older_than_the_retention_are_removed(tree):
    tree.logs.mkdir(parents=True)
    old = time.time() - 91 * 86400
    stale, kept, other = (
        tree.logs / "daily-20260101.log",
        tree.logs / "daily-20260720.log",
        tree.logs / "news-20260101.log",
    )
    for path in (stale, kept, other):
        path.write_text("x\n", encoding="utf-8")
    os.utime(stale, (old, old))
    os.utime(other, (old, old))
    os.utime(kept, (time.time() - 30 * 86400,) * 2)
    tree.run("daily")
    assert not stale.exists() and kept.exists() and other.exists()


# Memory without WMI (#246) ------------------------------------------------------


@linux_only
def test_free_memory_is_read_from_the_os():
    free = job.free_memory_mb()
    assert free is not None and free > 0


# What reaches into WMI from Python: the wmi package, the WMIC tool, CIM classes.
WMI_CALL = re.compile(r"\bwmi\b|wmic|Win32_\w+|\bCIM_\w+|psutil", re.IGNORECASE)


def test_the_job_source_has_no_wmi_call():
    # The memory check reads /proc/meminfo: busy machines cancel WMI calls
    # and the job would never start (#246).
    lines = JOB_SOURCE.read_text(encoding="utf-8").splitlines()
    found = [
        f"backend/worker/job.py:{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if WMI_CALL.search(line) and "#246" not in line
    ]
    assert not found, "WMI in the scheduled job (#246)\n" + "\n".join(found)


# Other systems ------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_job_and_lock_refuse_to_start_off_linux(
    tmp_path, monkeypatch, capsys, platform
):
    monkeypatch.setattr(job.sys, "platform", platform)
    marker = tmp_path / "ran"
    command = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]
    assert job.run_locked(tmp_path / "x.lock", command) == job.PLATFORM_EXIT
    parser = argparse.ArgumentParser()
    job.add_arguments(parser)
    args = parser.parse_args(["daily", "--data-dir", str(tmp_path / "job-data")])
    assert job.run(args) == job.PLATFORM_EXIT
    assert (
        capsys.readouterr().err.count(
            f"Linux only (the backend image, #333), not {platform}"
        )
        == 2
    )
    assert not marker.exists() and not (tmp_path / "job-data").exists()


# worker.cli job ------------------------------------------------------------------


def test_cli_job_sets_the_data_dir_before_app_config_is_imported(tmp_path):
    names = ("STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR")
    env = {key: value for key, value in os.environ.items() if key not in names}
    data = tmp_path / "chosen"
    probe = (
        "import sys; sys.argv = ['worker.cli', 'job', 'daily', '--data-dir', sys.argv[1]];"
        " import worker.cli, app.config; print(app.config.DATA_DIR)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(data)],
        cwd=ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert Path(completed.stdout.strip()) == data
    assert job.cli_environment(["job", "news", f"--data-dir={data}"]) == {
        "STOCK_DATA_DIR": str(data),
        "STOCK_DB_PATH": str(data / "stock.db"),
        "STOCK_RAW_DIR": str(data / "raw"),
    }
    assert job.cli_environment(["daily", "--date", "2026-10-16"]) == {}


@linux_only
def test_a_scheduled_daily_job_on_the_fixture_database_writes_one_run(
    tmp_path, monkeypatch
):
    """AC-4: the real job and worker on the verify fixture database, no network."""

    data = tmp_path / "data"
    built = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "verify" / "fixture_db.py"),
            "--dest",
            str(data),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert built.returncode == 0, built.stderr
    db = data / "stock.db"
    with sqlite3.connect(db) as conn:
        before = conn.execute("SELECT count(*) FROM schedule_runs").fetchone()[0]
    child = Path(__file__).with_name("job_daily_child.py")
    monkeypatch.setattr(
        job,
        "worker_command",
        lambda step_args: [sys.executable, "-X", "utf8", str(child), *step_args],
    )
    # The checkout's git state is not this test's subject (#207).
    monkeypatch.setattr(job, "git_dir", lambda root: None)
    parser = argparse.ArgumentParser()
    job.add_arguments(parser)
    args = parser.parse_args(
        [
            "daily",
            "--trigger",
            "scheduler",
            "--data-dir",
            str(data),
            "--min-free-memory-gb",
            "0",
            "--date",
            "2026-10-16",
            "--claude-cli",
            str(tmp_path / "no-claude"),
        ]
    )
    code = job.run(args)
    log = next((data / "logs").glob("daily-*.log")).read_text(encoding="utf-8")
    assert code == 0, log
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT target_date, trigger, status FROM schedule_runs ORDER BY id"
        ).fetchall()
    assert len(rows) == before + 1, log
    assert rows[-1] == ("2026-10-16", "scheduler", "success"), log
    assert [groups[1:] for groups in end_line(log)] == [("0", "")]


# Old logs and new logs mean the same to the watchdog (AC-2) ------------------------


def _bash() -> str | None:
    if os.name == "nt":
        git_bash = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Git"
            / "bin"
            / "bash.exe"
        )
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


STAMP = re.compile(r"^(===== )(\S+)( (?:start|end) )", re.MULTILINE)


def _restamp(text: str, first: float) -> str:
    """Move every start/end stamp to FIRST (epoch seconds), one minute apart."""

    count = iter(range(1000))

    def stamp(match):
        moment = datetime.fromtimestamp(first + 60 * next(count), job.TAIPEI)
        return match.group(1) + moment.isoformat() + match.group(3)

    return STAMP.sub(stamp, text)


def _watchdog(data: Path, now: int) -> list[str]:
    bash = _bash()
    if bash is None:
        pytest.skip("bash is required")
    script = ROOT / "tools" / "ops" / "watchdog.sh"
    env = {
        **os.environ,
        "STOCK_DATA_DIR": data.as_posix(),
        "STOCK_PYTHON": Path(sys.executable).as_posix(),
        "WATCHDOG_NOW": str(now),
    }
    completed = subprocess.run(
        [bash, script.as_posix(), "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.replace(data.as_posix(), "<data>").splitlines()


@pytest.mark.parametrize("daily_ended", [True, False], ids=["daily-ended", "daily-cut"])
def test_the_watchdog_reads_old_and_new_logs_alike(tree, tmp_path, daily_ended):
    # Monday 2026-10-19 22:00 Taipei; the logs were written from 21:00 on.
    now = int(datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc).timestamp())
    first = now - 3600
    day = "20261019"
    for _ in range(3):
        tree.run("news", "--claude-cli", "/usr/local/bin/claude", news_llm_exit=1)
    tree.run("daily")
    new = {"daily": tree.log("daily"), "news": tree.log("news")}
    old = {
        name: (FIXTURES / f"wrapper_{name}.txt")
        .read_text(encoding="utf-8")
        .replace("\n", "\r\n")  # as the Windows wrapper wrote it
        for name in ("daily", "news")
    }
    decisions = []
    for label, logs in (("old", old), ("new", new)):
        data = tmp_path / f"watch-{label}"
        (data / "logs").mkdir(parents=True)
        daily = _restamp(logs["daily"], first)
        if not daily_ended:
            daily = daily.splitlines(keepends=True)[0]
        (data / "logs" / f"daily-{day}.log").write_text(
            daily, encoding="utf-8", newline=""
        )
        news = data / "logs" / f"news-{day}.log"
        news.write_text(_restamp(logs["news"], first), encoding="utf-8", newline="")
        os.utime(news, (now - 600, now - 600))
        decisions.append(_watchdog(data, now))
    assert decisions[0] == decisions[1]
    keys = re.findall(r" anomaly_planned key=(\S+)", "\n".join(decisions[0]))
    assert keys == (
        ["news_llm_failed"] if daily_ended else ["daily_no_end", "news_llm_failed"]
    )
