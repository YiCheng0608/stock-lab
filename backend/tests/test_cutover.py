"""tools/ops/cutover.sh's checks and dry runs with a fake docker and a fake PowerShell (#342).

The full switch and rollback need Docker, Task Scheduler and a copy of the production
database; they are rehearsed on a test project, a test task folder and a copy (the PR of
#342). Here: a dry run lists every step and changes nothing (AC-1), and each refusal comes
before any change. The env file is a stand-in named ``envfile``; its values are never printed.
The release checkout is a git repository under tmp_path. tools/ops/cutover_db.py, which
the script runs on the host and pipes into the helper container, is tested directly.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_deploy import BASH, REAL_GIT, _bash_path, git

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = (
    "cutover.sh",
    "deploy.sh",
    "cutover_db.py",
    "copy_db.py",
    "coordinator_lib.sh",
    "coordinator_json.py",
)
PROJECT = "t342-test"
SECRET = "s3cr3t-value-never-printed"
KEYS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GH_TOKEN",
    "STOCK_WAKE_TOKEN",
    "STOCK_MONITOR",
    "STOCK_COORDINATION_DIR",
)
SWITCH_STEPS = [
    "pre-docker",
    "disable",
    "snapshot",
    "volume",
    "copy",
    "chown",
    "verify",
    "helper",
    "start",
    "readback",
]
ROLLBACK_STEPS = ["stop", "snapshot", "paths", "install", "checkout", "enable"]
pytestmark = pytest.mark.skipif(
    BASH is None or REAL_GIT is None, reason="bash and git are required"
)

# State under $FAKE_DIR: tasks (`<name> <State>` lines), writers (Get-Process lines).
FAKE_POWERSHELL = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
command="${@: -1}"
printf '%s\n' "$command" >>"$d/powershell_calls.log"
name="$(printf '%s' "$command" | sed -n "s/.*-TaskName '\([^']*\)'.*/\1/p")"
case "$command" in
  'exit 0') exit 0 ;;
  *Disable-ScheduledTask*) sed -i "s/^$name .*/$name Disabled/" "$d/tasks" ;;
  *Enable-ScheduledTask*) sed -i "s/^$name .*/$name Ready/" "$d/tasks" ;;
  *Get-ScheduledTaskInfo*) cat "$d/news_result" 2>/dev/null || echo 0 ;;
  *Start-ScheduledTask*) ;;
  *Get-ScheduledTask*) cat "$d/tasks" ;;
  *Get-Process*) cat "$d/writers" 2>/dev/null ;;
esac
exit 0
"""

# State under $FAKE_DIR/docker: volumes (`docker volume ls -q`), running (`ps -q`, also the
# project's containers other than one-offs), images (`ps -a --format {{.Image}}`; image inspect
# succeeds when the file exists), probe (what the read-only `run --rm` sees in the volume),
# volume.db (what `docker cp <project>-rollback:… <host>` copies out), fail (a call containing one of
# its lines exits 1). `compose -p P … run` creates P_stock-data, as compose does.
FAKE_DOCKER = r"""#!/usr/bin/env bash
d="$FAKE_DIR/docker"
printf '%s\n' "$*" >>"$FAKE_DIR/docker_calls.log"
if [ -f "$d/fail" ]; then
  while IFS= read -r pattern; do
    case "$*" in *"$pattern"*) echo "fake docker: failed ($pattern)" >&2; exit 1 ;; esac
  done <"$d/fail"
fi
# Compose v5.6.1 (the host's, rehearsal of #342): `run` has --build but no --no-build.
if [ "$1" = compose ]; then
  case " $* " in
    *" run "*" --no-build "*) echo "unknown flag: --no-build" >&2; exit 1 ;;
    *" run "*) [ "$2" = -p ] && echo "${3}_stock-data" >>"$d/volumes" ;;
  esac
fi
if [ "$1 $2" = "run --rm" ]; then cat "$d/probe" 2>/dev/null; exit 0; fi
if [ "$1" = cp ]; then
  case "$2" in *-rollback:/*) [ -f "$d/volume.db" ] && cp "$d/volume.db" "$3" ;; esac
  exit 0
fi
case "$1 $2" in
  "compose version") exit 0 ;;
  "volume ls") cat "$d/volumes" 2>/dev/null; exit 0 ;;
  "image inspect") [ -f "$d/images" ]; exit ;;
esac
if [ "$1" = ps ]; then
  case "$*" in
    *'{{.Image}}'*) cat "$d/images" 2>/dev/null ;;
    *) cat "$d/running" 2>/dev/null ;;
  esac
  exit 0
fi
exit 0
"""

READ_ONLY_POWERSHELL = ("exit 0", "Get-ScheduledTask", "Get-Process")
READ_ONLY_DOCKER = (
    "compose version",
    "version --format ",
    "volume ls ",
    "ps ",
    "image inspect ",
)
# The rollback reads the volume through a container that mounts it read-only and is removed.
VOLUME_PROBE = "run --rm -v "


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.fake = root / "fake"
        self.home = root / "home"
        self.data = root / "data"
        self.work = root / "work"
        self.checkout = root / "release"
        for directory in (self.bin, self.fake / "docker", self.home, self.checkout):
            directory.mkdir(parents=True)
        ops = root / "sandbox" / "tools" / "ops"
        ops.mkdir(parents=True)
        for name in SCRIPTS:
            shutil.copyfile(ROOT / "tools" / "ops" / name, ops / name)
        self.script = ops / "cutover.sh"
        for name, body in (("docker", FAKE_DOCKER), ("powershell", FAKE_POWERSHELL)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        (self.checkout / "README.md").write_text("pre-docker\n", encoding="utf-8")
        git(self.checkout, "init", "--quiet")
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "--quiet", "-m", "pre-docker")
        self.head = git(self.checkout, "rev-parse", "HEAD")
        self.tasks("daily Ready", "news Ready", "watchdog Ready")
        (self.data / "raw" / "twse").mkdir(parents=True)
        (self.data / "raw" / "twse" / "a.json").write_text("{}", encoding="utf-8")
        (self.data / "logs").mkdir()
        with sqlite3.connect(self.data / "stock.db") as conn:
            conn.execute("CREATE TABLE market_bars (trading_date TEXT)")
        conn.close()
        self.env_file = root / "envfile"
        self.keys(**{key: SECRET for key in KEYS})

    # Every file bash reads is written with LF: on Windows write_text writes CRLF, and a
    # pattern ending in \r never matches (PR #424 second review, required fix 1).
    def fake_file(self, name: str, *lines: str) -> None:
        (self.fake / name).write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n"
        )

    def tasks(self, *lines: str) -> None:
        self.fake_file("tasks", *lines)

    def keys(self, **values: str) -> None:
        self.env_file.write_text(
            "".join(f"{key}={value}\n" for key, value in values.items()),
            encoding="utf-8",
            newline="\n",
        )

    def docker(self, name: str, *lines: str) -> None:
        self.fake_file(f"docker/{name}", *lines)

    def docker_down(self) -> None:
        """Docker Desktop not answering: every docker call fails (an empty pattern matches all)."""

        self.docker("fail", "")

    def record(self) -> dict | None:
        path = self.work / "cutover-steps.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def calls(self, name: str) -> list[str]:
        path = self.fake / f"{name}_calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def state(self) -> tuple:
        """What a dry run must leave as it was."""
        return (
            (self.fake / "tasks").read_text(encoding="utf-8"),
            git(self.checkout, "branch", "--list"),
            git(self.checkout, "config", "--local", "--list"),
            git(self.checkout, "rev-parse", "HEAD"),
            sorted(str(p.relative_to(self.root)) for p in self.data.rglob("*")),
            sorted(str(p.relative_to(self.root)) for p in self.work.rglob("*"))
            if self.work.exists()
            else None,
        )

    def run(self, *args: str, extra_env: dict[str, str] | None = None):
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("STOCK_", "CUTOVER_", "GIT_", "COMPOSE_"))
        }
        env.update(
            PATH=str(self.bin) + os.pathsep + env.get("PATH", ""),
            FAKE_DIR=self.fake.as_posix(),
            FAKE_BIN=_bash_path(self.bin),
            HOME=self.home.as_posix(),
            STOCK_PYTHON=Path(sys.executable).as_posix(),
            COMPOSE_PROJECT_NAME="task-342",
        )
        env.update(extra_env or {})
        completed = subprocess.run(
            [
                BASH,
                "-c",
                'PATH="$FAKE_BIN:$PATH"; exec bash "$@"',
                "bash",
                self.script.as_posix(),
                *(args[:1] if args[:1] == ("rollback",) else ()),
                "--checkout",
                self.checkout.as_posix(),
                "--data-dir",
                self.data.as_posix(),
                "--work-dir",
                self.work.as_posix(),
                "--project",
                PROJECT,
                "--env-file",
                self.env_file.as_posix(),
                "--powershell",
                "powershell",
                # The test's own options last: they win over the ones above.
                *(args[1:] if args[:1] == ("rollback",) else args),
            ],
            env=env,
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
        return SimpleNamespace(
            code=completed.returncode,
            out=completed.stdout + completed.stderr,
            result=json.loads(lines[-1]) if lines else None,
        )


@pytest.fixture
def harness(tmp_path) -> Harness:
    return Harness(tmp_path)


def assert_read_only(h: Harness) -> None:
    for call in h.calls("powershell"):
        assert (
            call.startswith(READ_ONLY_POWERSHELL)
            or "Get-ScheduledTask -TaskPath" in call
        )
        assert not any(
            verb in call for verb in ("Disable-", "Enable-", "Start-", "Stop-")
        ), call
    for call in h.calls("docker"):
        if call.startswith(VOLUME_PROBE):
            assert f"-v {PROJECT}_stock-data:/data:ro " in call, call
            continue
        assert call.startswith(READ_ONLY_DOCKER), call


def test_a_dry_run_lists_every_step_and_changes_nothing(harness):
    """AC-1: every step is printed with its command; tasks, checkout, data and volumes stay."""

    before = harness.state()
    result = harness.run("--dry-run", "--tag", "v1.1.0")
    assert result.code == 0, result.out
    assert result.result["status"] == "dry-run"
    assert result.result["steps"] == SWITCH_STEPS
    for step in SWITCH_STEPS:
        assert f"cutover: [{step}] " in result.out
    assert "Disable-ScheduledTask -TaskPath '\\stock-lab\\'" in result.out
    assert "deploy.sh v1.1.0" in result.out
    assert harness.state() == before
    assert_read_only(harness)


def test_a_rehearsal_dry_run_starts_compose_instead_of_deploying(harness):
    result = harness.run("--dry-run", "--no-deploy")
    assert result.code == 0, result.out
    assert "（演練）docker compose" in result.out and "deploy.sh" not in result.out


def test_the_helper_is_started_with_flags_compose_run_takes(harness):
    """The rehearsal of #342 stopped at step 4: `compose run` has no --no-build.

    The fake docker answers nothing, so the switch stops later, at verify; it must get
    past the volume step and start the helper with `compose run -d`.
    """

    harness.docker("images", f"{PROJECT}-backend:cutover")
    result = harness.run("--no-deploy")
    assert result.code == 3, result.out
    assert "compose run 輔助容器失敗" not in result.out
    assert result.result["steps"][:6] == SWITCH_STEPS[:6]
    runs = [c for c in harness.calls("docker") if " run -d " in f" {c} "]
    assert len(runs) == 1, harness.calls("docker")
    assert f"--name {PROJECT}-cutover --user root --entrypoint sleep api" in runs[0]


def test_the_switch_needs_a_tag_or_a_rehearsal(harness):
    assert harness.run("--dry-run").code == 64
    assert harness.run("--dry-run", "--tag", "v1", "--no-deploy").code == 64


@pytest.mark.parametrize(
    "values, missing",
    [
        ({k: SECRET for k in KEYS if k != "GH_TOKEN"}, "GH_TOKEN"),
        ({**{k: SECRET for k in KEYS}, "STOCK_MONITOR": ""}, "STOCK_MONITOR"),
        ({**{k: SECRET for k in KEYS}, "GH_TOKEN": "  # later"}, "GH_TOKEN"),
        ({**{k: SECRET for k in KEYS}, "GH_TOKEN": '""'}, "GH_TOKEN"),
        ({**{k: SECRET for k in KEYS}, "STOCK_WAKE_TOKEN": "''"}, "STOCK_WAKE_TOKEN"),
    ],
    ids=[
        "absent",
        "empty",
        "comment-only",
        "empty-double-quotes",
        "empty-single-quotes",
    ],
)
def test_a_required_key_without_a_value_is_refused_and_no_value_printed(
    harness, values, missing
):
    harness.keys(**values)
    before = harness.state()
    result = harness.run("--dry-run", "--tag", "v1")
    assert result.code == 1, result.out
    assert result.result["status"] == "refused"
    assert missing in result.result["reason"]
    assert SECRET not in result.out
    assert harness.state() == before
    assert_read_only(harness)


@pytest.mark.parametrize("key", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_an_api_key_in_the_env_file_is_refused(harness, key):
    harness.keys(**{k: SECRET for k in KEYS}, **{key: SECRET})
    result = harness.run("--dry-run", "--tag", "v1")
    assert result.code == 1 and key in result.result["reason"], result.out
    assert SECRET not in result.out


def test_without_an_env_file_the_switch_is_refused(harness):
    harness.env_file.unlink()
    result = harness.run("--dry-run", "--tag", "v1")
    assert result.code == 1 and "env file" in result.result["reason"], result.out


def _pull_333(h: Harness) -> dict[str, str]:
    """The checkout as after a task pulled master with #333 (-GitPull): a later commit."""

    (h.checkout / "Dockerfile").write_text("FROM python", encoding="utf-8")
    git(h.checkout, "add", "-A")
    git(h.checkout, "commit", "--quiet", "-m", "333")
    return {"CUTOVER_PR333": git(h.checkout, "rev-parse", "HEAD")}


def test_a_checkout_with_333_while_a_task_is_enabled_is_refused(harness):
    """Decision 9: the Windows jobs of a #333 checkout exit 69, the schedule stopped silently."""

    env = _pull_333(harness)
    harness.tasks("daily Disabled", "news Ready", "watchdog Disabled")
    before = harness.state()
    result = harness.run("--dry-run", "--tag", "v1", extra_env=env)
    assert result.code == 1, result.out
    assert "#333" in result.result["reason"] and "啟用" in result.result["reason"]
    assert harness.state() == before


def test_pre_docker_never_holds_333(harness):
    """Review H1: a rollback to a #333 commit would leave Windows jobs that exit 69."""

    env = _pull_333(harness)
    harness.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    result = harness.run("--dry-run", "--tag", "v1", extra_env=env)
    assert result.code == 1 and "--pre-docker" in result.result["reason"], result.out
    result = harness.run(
        "--dry-run", "--tag", "v1", "--pre-docker", harness.head, extra_env=env
    )
    assert result.code == 0, result.out
    assert f"branch pre-docker {harness.head[:9]}" in result.out


def test_a_running_task_is_refused(harness):
    harness.tasks("daily Running", "news Ready", "watchdog Ready")
    result = harness.run("--dry-run", "--tag", "v1")
    assert result.code == 1 and "執行" in result.result["reason"], result.out


def test_an_existing_volume_is_refused(harness):
    """The switch writes only into the volume compose creates for it."""

    harness.docker("volumes", f"{PROJECT}_stock-data")
    result = harness.run("--dry-run", "--tag", "v1")
    assert result.code == 1 and "volume" in result.result["reason"], result.out


def test_uncommitted_changes_in_the_checkout_are_refused(harness):
    (harness.checkout / "README.md").write_text("changed\n", encoding="utf-8")
    result = harness.run("--dry-run", "--tag", "v1")
    assert result.code == 1 and "未 commit" in result.result["reason"], result.out


def test_a_pre_docker_branch_elsewhere_is_refused(harness):
    (harness.checkout / "b.md").write_text("b\n", encoding="utf-8")
    git(harness.checkout, "add", "-A")
    git(harness.checkout, "commit", "--quiet", "-m", "later")
    git(harness.checkout, "branch", "pre-docker", harness.head)
    result = harness.run("--dry-run", "--tag", "v1")
    assert result.code == 1 and "pre-docker" in result.result["reason"], result.out


def test_a_work_dir_inside_the_data_dir_is_refused(harness):
    result = harness.run(
        "--dry-run", "--tag", "v1", "--work-dir", harness.data.as_posix() + "/w"
    )
    assert result.code == 2, result.out


CUTOVER_TIME = "2026-11-01T00:00:00Z"
EARLY_STEPS = ["helper", "checkout", "enable"]
RESUME_STEPS = ["stop", "checkout", "enable"]


def _ready_for_rollback(h: Harness) -> None:
    """After a switch that got through verify: serve ran on the volume."""

    git(h.checkout, "branch", "pre-docker", h.head)
    git(h.checkout, "config", "branch.pre-docker.remote", ".")
    git(h.checkout, "config", "branch.pre-docker.merge", "refs/heads/pre-docker")
    h.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    h.docker("volumes", f"{PROJECT}_stock-data")
    h.docker("running", "c0ffee5c4ed01")
    h.docker("images", f"{PROJECT}-backend:v1.1.0")
    h.docker("probe", "db", "cutover", json.dumps({"time": CUTOVER_TIME}))
    h.work.mkdir()
    # The host database was last written before the switch.
    old = datetime(2026, 10, 31, 12, tzinfo=timezone.utc).timestamp()
    os.utime(h.data / "stock.db", (old, old))
    # What the container holds: the host's rows plus one capture it wrote.
    volume_db = _db(h.fake / "docker" / "volume.db", "/data/raw/twse/2026/11/03/a.json")
    with sqlite3.connect(volume_db) as conn:
        conn.execute("CREATE TABLE written (who TEXT)")
        conn.execute("INSERT INTO written VALUES ('serve')")
    conn.close()


def _host_rows(h: Harness) -> list[str]:
    with sqlite3.connect(h.data / "stock.db") as conn:
        rows = [
            row[0] for row in conn.execute("SELECT who FROM written ORDER BY rowid")
        ]
    conn.close()
    return rows


def _back_on_task_scheduler(h: Harness, result) -> None:
    """Where every rollback ends: pre-docker tracking itself, pulled, every task enabled."""

    assert result.code == 0, result.out
    assert result.result["status"] == "done"
    assert (h.fake / "tasks").read_text(encoding="utf-8").split() == [
        "daily",
        "Ready",
        "news",
        "Ready",
        "watchdog",
        "Ready",
    ]
    assert git(h.checkout, "rev-parse", "--abbrev-ref", "HEAD") == "pre-docker"
    assert git(h.checkout, "config", "branch.pre-docker.remote") == "."
    assert (
        git(h.checkout, "config", "branch.pre-docker.merge") == "refs/heads/pre-docker"
    )
    assert "git pull --ff-only exit 0" in result.out
    assert git(h.checkout, "pull", "--ff-only") == "Already up to date."


def test_a_rollback_dry_run_lists_every_step_and_changes_nothing(harness):
    _ready_for_rollback(harness)
    before = harness.state()
    result = harness.run("rollback", "--dry-run", "--start-news")
    assert result.code == 0, result.out
    assert result.result["status"] == "dry-run"
    assert result.result["steps"] == ROLLBACK_STEPS
    assert "回退方式 full" in result.out
    assert (
        "git pull --ff-only" in result.out and "Start-ScheduledTask news" in result.out
    )
    assert f"{PROJECT}-backend:v1.1.0" in result.out
    assert harness.state() == before
    assert_read_only(harness)


def test_a_rollback_whose_branch_tracks_a_remote_is_refused(harness):
    """`git pull --ff-only` would move it on to the merged master (review H1)."""

    _ready_for_rollback(harness)
    git(harness.checkout, "config", "branch.pre-docker.remote", "origin")
    result = harness.run("rollback", "--dry-run")
    assert result.code == 1 and "upstream" in result.result["reason"], result.out


def test_a_rollback_never_goes_back_to_a_commit_with_333(harness):
    env = _pull_333(harness)
    harness.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    result = harness.run("rollback", "--dry-run", extra_env=env)
    assert result.code == 1 and "--pre-docker" in result.result["reason"], result.out
    git(harness.checkout, "branch", "pre-docker", "HEAD")
    result = harness.run("rollback", "--dry-run", extra_env=env)
    assert result.code == 1 and "#333" in result.result["reason"], result.out


# A switch that stopped before verify ended (PR #424 review 6591459652, required fix 1): the
# tasks are disabled and no serve ever ran, so the rollback goes back to Task Scheduler and
# leaves the host database alone.
# Each failure is injected at its step and the switch must stop there (the reason says so):
# without the injection the fake docker stops the switch at verify, which the reason tells
# apart (PR #424 second review, required fix 1).
FAILURES = {
    "wait": (None, "停用後 1 秒內仍有工作或 venv 程序在跑", ["pre-docker", "disable"]),
    "copy_db": (None, "copy_db.py 失敗", ["pre-docker", "disable"]),
    "build": (" build api", f"build {PROJECT}-backend:cutover 失敗", SWITCH_STEPS[:3]),
    "compose run": (" run -d --no-deps", "compose run 輔助容器失敗", SWITCH_STEPS[:3]),
    "docker cp stock.db": (
        ":/data/stock.db",
        "docker cp stock.db 失敗",
        SWITCH_STEPS[:4],
    ),
}


def _fail_the_switch(h: Harness, failure: str):
    pattern, reason, steps = FAILURES[failure]
    args = ["--no-deploy"]
    if failure == "wait":
        h.fake_file("writers", "4242 C:\\stock-lab-release\\.venv\\python.exe")
        args += ["--wait-timeout", "1"]
    elif failure == "copy_db":
        (h.data / "stock.db").write_bytes(b"not a database, copy_db.py fails\n")
    if failure != "build":
        h.docker("images", f"{PROJECT}-backend:cutover")
    if pattern:
        h.docker("fail", pattern)
    switch = h.run(*args)
    assert switch.code == 3, switch.out
    assert switch.result["reason"] == reason, switch.out
    assert switch.result["steps"] == steps
    # The host-side record holds the same steps: a rollback reads it when Docker is down.
    assert h.record()["steps"] == steps and h.record()["project"] == PROJECT
    assert "Disabled" in (h.fake / "tasks").read_text(encoding="utf-8")
    for path in (h.fake / "docker" / "fail", h.fake / "writers"):
        path.unlink(missing_ok=True)
    return switch


@pytest.mark.parametrize("docker", ["docker answers", "docker down"])
@pytest.mark.parametrize("failure", list(FAILURES))
def test_a_switch_that_failed_before_serve_ran_rolls_back_to_task_scheduler(
    harness, failure, docker
):
    """Fix 1 of both reviews: back to Task Scheduler, also when Docker is what failed."""

    _fail_the_switch(harness, failure)
    host_db = (harness.data / "stock.db").read_bytes()  # the switch never writes it
    if docker == "docker down":
        harness.docker_down()
    result = harness.run("rollback")
    _back_on_task_scheduler(harness, result)
    if docker == "docker down":
        assert result.result["steps"] == ["checkout", "enable"]
        assert "回退方式 early（Docker 不能用）" in result.out
    else:
        assert result.result["steps"] == EARLY_STEPS
        assert "回退方式 early" in result.out
    assert (harness.data / "stock.db").read_bytes() == host_db
    assert not (harness.data / "backups").exists()


def test_without_docker_a_switch_that_got_through_verify_is_refused(harness):
    """serve may have written the volume: the rollback waits for Docker (full)."""

    _fail_the_switch(harness, "docker cp stock.db")
    record = harness.work / "cutover-steps.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["steps"] = SWITCH_STEPS[:7]
    record.write_text(json.dumps(data) + "\n", encoding="utf-8", newline="\n")
    harness.docker_down()
    before = harness.state()
    result = harness.run("rollback")
    assert result.code == 1, result.out
    assert "Docker" in result.result["reason"] and "verify" in result.result["reason"]
    assert harness.state() == before


def test_without_docker_and_without_the_record_the_rollback_is_refused(harness):
    harness.work.mkdir()
    harness.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    harness.docker_down()
    before = harness.state()
    result = harness.run("rollback")
    assert result.code == 1, result.out
    assert "cutover-steps.json" in result.result["reason"]
    assert harness.state() == before


def test_a_switch_needs_docker_to_answer(harness):
    harness.work.mkdir()
    harness.docker_down()
    before = harness.state()
    result = harness.run("--no-deploy")
    assert result.code == 2, result.out
    assert "docker" in result.out and harness.state() == before


def test_a_record_of_verify_without_cutover_json_in_the_volume_is_refused(harness):
    _fail_the_switch(harness, "docker cp stock.db")
    record = harness.work / "cutover-steps.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["steps"] = SWITCH_STEPS[:7]
    record.write_text(json.dumps(data) + "\n", encoding="utf-8", newline="\n")
    result = harness.run("rollback", "--dry-run")
    assert result.code == 1 and "cutover.json" in result.result["reason"], result.out


def test_a_cutover_json_in_the_host_logs_is_refused(harness):
    """It would go into the volume and read as a finished verify (second review, note 2)."""

    (harness.data / "logs" / "cutover.json").write_text("{}\n", encoding="utf-8")
    result = harness.run("--dry-run", "--no-deploy")
    assert result.code == 1 and "cutover.json" in result.result["reason"], result.out


def test_tasks_disabled_by_hand_before_any_switch_roll_back_without_a_branch(harness):
    """§6.9: the tasks were disabled ahead of the merge, then the switch was given up."""

    harness.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    host_db = (harness.data / "stock.db").read_bytes()
    dry = harness.run("rollback", "--dry-run")
    assert dry.code == 0, dry.out
    assert f"git branch pre-docker {harness.head[:9]}" in dry.out
    result = harness.run("rollback")
    _back_on_task_scheduler(harness, result)
    assert result.result["steps"] == EARLY_STEPS
    assert git(harness.checkout, "rev-parse", "pre-docker") == harness.head
    assert (harness.data / "stock.db").read_bytes() == host_db


def test_containers_without_a_finished_switch_are_refused(harness):
    harness.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    harness.docker("volumes", f"{PROJECT}_stock-data")
    harness.docker("images", f"{PROJECT}-backend:cutover")
    harness.docker("running", "c0ffee5c4ed01")
    result = harness.run("rollback", "--dry-run")
    assert result.code == 1 and "cutover.json" in result.result["reason"], result.out


# Required fix 2: the checks before the host database is replaced.
@pytest.mark.parametrize("state", ["Ready", "Running"])
def test_a_rollback_with_a_task_not_disabled_never_replaces_the_host_db(harness, state):
    _ready_for_rollback(harness)
    harness.tasks("daily Disabled", f"news {state}", "watchdog Disabled")
    before = harness.state()
    host_db = (harness.data / "stock.db").read_bytes()
    result = harness.run("rollback")
    assert result.code == 1, result.out
    assert "news" in result.result["reason"] and "Disabled" in result.result["reason"]
    assert harness.state() == before
    assert (harness.data / "stock.db").read_bytes() == host_db
    assert_read_only(harness)


def test_a_volume_without_stock_db_is_refused(harness):
    _ready_for_rollback(harness)
    harness.docker("probe", "cutover", json.dumps({"time": CUTOVER_TIME}))
    result = harness.run("rollback")
    assert result.code == 1 and "/data/stock.db" in result.result["reason"], result.out
    assert_read_only(harness)


@pytest.mark.parametrize("name", ["stock.db", "stock.db-wal"])
def test_a_host_db_written_after_the_switch_is_never_replaced(harness, name):
    _ready_for_rollback(harness)
    (harness.data / name).touch()  # now, after CUTOVER_TIME
    result = harness.run("rollback")
    assert result.code == 1 and name in result.result["reason"], result.out
    assert_read_only(harness)


def test_a_rerun_after_start_news_failed_keeps_what_windows_wrote(harness):
    """The rerun of review 6591446223 must-fix 2: news failed, Windows wrote, rollback again."""

    _ready_for_rollback(harness)
    harness.fake_file("news_result", "1")
    first = harness.run("rollback", "--start-news")
    assert first.code == 3 and "LastTaskResult" in first.result["reason"], first.out
    assert first.result["steps"] == ROLLBACK_STEPS[:-1]
    assert _host_rows(harness) == ["serve"]
    # The tasks are enabled: a Windows job writes the host database.
    with sqlite3.connect(harness.data / "stock.db") as conn:
        conn.execute("INSERT INTO written VALUES ('windows')")
    conn.close()
    harness.fake_file("news_result", "0")

    again = harness.run("rollback", "--start-news")
    _back_on_task_scheduler(harness, again)
    assert again.result["steps"] == RESUME_STEPS
    assert "回退方式 resume" in again.out
    assert _host_rows(harness) == ["serve", "windows"]
    assert len(list((harness.data / "backups").iterdir())) == 1


def _interrupt_after_install(h: Harness) -> None:
    """A full rollback that stopped after the copy was in place, before installed.json."""

    first = h.run("rollback")
    assert first.code == 0, first.out
    (h.work / "rollback" / "installed.json").unlink()
    assert (h.work / "rollback" / "installing.json").exists()
    h.tasks("daily Disabled", "news Disabled", "watchdog Disabled")


def test_a_rollback_interrupted_before_installed_json_resumes(harness):
    """Second review, required fix 3: not stuck on the mtime of the copy it installed."""

    _ready_for_rollback(harness)
    _interrupt_after_install(harness)
    installed = (harness.data / "stock.db").read_bytes()
    again = harness.run("rollback")
    _back_on_task_scheduler(harness, again)
    assert again.result["steps"] == RESUME_STEPS
    assert "寫 " in again.out and "前中斷" in again.out
    assert (harness.data / "stock.db").read_bytes() == installed
    assert len(list((harness.data / "backups").iterdir())) == 1
    record = json.loads(
        (harness.work / "rollback" / "installed.json").read_text(encoding="utf-8")
    )
    assert record["cutover"] == CUTOVER_TIME and record["backup"]


def test_an_interrupted_install_with_another_host_db_names_the_backup(harness):
    _ready_for_rollback(harness)
    _interrupt_after_install(harness)
    with sqlite3.connect(harness.data / "stock.db") as conn:
        conn.execute("INSERT INTO written VALUES ('someone')")
    conn.close()
    before = harness.state()
    result = harness.run("rollback")
    assert result.code == 1, result.out
    assert "install 中斷" in result.result["reason"]
    assert "pre-rollback-" in result.result["reason"]
    assert harness.state() == before


def test_a_full_rollback_brings_back_what_serve_wrote(harness):
    _ready_for_rollback(harness)
    result = harness.run("rollback")
    _back_on_task_scheduler(harness, result)
    assert result.result["steps"] == ROLLBACK_STEPS
    assert _host_rows(harness) == ["serve"]
    with sqlite3.connect(harness.data / "stock.db") as conn:
        paths = [
            row[0] for row in conn.execute("SELECT payload_path FROM raw_payloads")
        ]
    conn.close()
    assert [Path(p) for p in paths] == [
        harness.data / "raw" / "twse" / "2026" / "11" / "03" / "a.json"
    ]
    installed = json.loads(
        (harness.work / "rollback" / "installed.json").read_text(encoding="utf-8")
    )
    assert installed["cutover"] == CUTOVER_TIME


# tools/ops/cutover_db.py --------------------------------------------------------------


def _cutover_db(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ops" / "cutover_db.py"), *args],
        capture_output=True,
        text=True,
    )


def _db(path: Path, *paths: str) -> Path:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE raw_payloads (id INTEGER PRIMARY KEY, payload_path TEXT)"
        )
        conn.execute("CREATE TABLE market_bars (x)")
        conn.executemany(
            "INSERT INTO raw_payloads (payload_path) VALUES (?)", [(p,) for p in paths]
        )
    conn.close()
    return path


def test_counts_and_compare_report_integrity_and_every_table(tmp_path):
    a = _db(tmp_path / "a.db", "x")
    b = _db(tmp_path / "b.db", "x", "y")
    out = {}
    for name, db in (("a", a), ("b", b)):
        result = _cutover_db("counts", str(db))
        assert result.returncode == 0, result.stderr
        out[name] = json.loads(result.stdout)
        (tmp_path / f"{name}.json").write_text(result.stdout, encoding="utf-8")
    assert out["a"]["integrity_check"] == "ok"
    assert out["a"]["tables"] == {"market_bars": 0, "raw_payloads": 1}
    same = _cutover_db("compare", str(tmp_path / "a.json"), str(tmp_path / "a.json"))
    assert same.returncode == 0
    assert same.stdout.splitlines() == [
        "integrity_check ok; 2 tables, 1 rows, the same in both"
    ]
    differ = _cutover_db("compare", str(tmp_path / "a.json"), str(tmp_path / "b.json"))
    assert differ.returncode == 1 and "raw_payloads: 1 != 2" in differ.stdout


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "C:/Users/YiCheng/stock-lab-data/raw",
            r"C:\Users\YiCheng\stock-lab-data\raw\twse\2026\11\04\a.json",
        ),
        (
            "/home/u/stock-lab-data/raw/",
            "/home/u/stock-lab-data/raw/twse/2026/11/04/a.json",
        ),
    ],
)
def test_rollback_rewrites_only_the_paths_the_container_wrote(tmp_path, raw, expected):
    old = r"C:\Users\YiCheng\stock-lab-data\raw\twse\2026\10\30\b.json"
    db = _db(tmp_path / "c.db", "/data/raw/twse/2026/11/04/a.json", old)
    result = _cutover_db("rewrite-paths", str(db), raw)
    assert result.returncode == 0 and result.stdout.strip() == "1", result.stderr
    with sqlite3.connect(db) as conn:
        paths = [
            row[0]
            for row in conn.execute("SELECT payload_path FROM raw_payloads ORDER BY id")
        ]
    conn.close()
    assert paths == [expected, old]
