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
  *Get-ScheduledTaskInfo*) echo 0 ;;
  *Start-ScheduledTask*) ;;
  *Get-ScheduledTask*) cat "$d/tasks" ;;
  *Get-Process*) cat "$d/writers" 2>/dev/null ;;
esac
exit 0
"""

# State under $FAKE_DIR/docker: volumes (`docker volume ls -q`), running (`ps -q`), images
# (`ps -a --format {{.Image}}`; image inspect succeeds when the file exists).
FAKE_DOCKER = r"""#!/usr/bin/env bash
d="$FAKE_DIR/docker"
printf '%s\n' "$*" >>"$FAKE_DIR/docker_calls.log"
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
READ_ONLY_DOCKER = ("compose version", "volume ls ", "ps ", "image inspect ")


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

    def tasks(self, *lines: str) -> None:
        (self.fake / "tasks").write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8"
        )

    def keys(self, **values: str) -> None:
        self.env_file.write_text(
            "".join(f"{key}={value}\n" for key, value in values.items()),
            encoding="utf-8",
        )

    def docker(self, name: str, *lines: str) -> None:
        (self.fake / "docker" / name).write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8"
        )

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


def test_the_switch_needs_a_tag_or_a_rehearsal(harness):
    assert harness.run("--dry-run").code == 64
    assert harness.run("--dry-run", "--tag", "v1", "--no-deploy").code == 64


@pytest.mark.parametrize(
    "values, missing",
    [
        ({k: SECRET for k in KEYS if k != "GH_TOKEN"}, "GH_TOKEN"),
        ({**{k: SECRET for k in KEYS}, "STOCK_MONITOR": ""}, "STOCK_MONITOR"),
        ({**{k: SECRET for k in KEYS}, "GH_TOKEN": "  # later"}, "GH_TOKEN"),
    ],
    ids=["absent", "empty", "comment-only"],
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


def test_a_checkout_with_333_while_a_task_is_enabled_is_refused(harness):
    """Decision 9: the Windows jobs of a #333 checkout exit 69, the schedule stopped silently."""

    env = {"CUTOVER_PR333": harness.head}
    harness.tasks("daily Disabled", "news Ready", "watchdog Disabled")
    before = harness.state()
    result = harness.run("--dry-run", "--tag", "v1", extra_env=env)
    assert result.code == 1, result.out
    assert "#333" in result.result["reason"]
    assert harness.state() == before
    harness.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    assert harness.run("--dry-run", "--tag", "v1", extra_env=env).code == 0


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


def _ready_for_rollback(h: Harness) -> None:
    git(h.checkout, "branch", "pre-docker", h.head)
    git(h.checkout, "config", "branch.pre-docker.remote", ".")
    git(h.checkout, "config", "branch.pre-docker.merge", "refs/heads/pre-docker")
    h.tasks("daily Disabled", "news Disabled", "watchdog Disabled")
    h.docker("volumes", f"{PROJECT}_stock-data")
    h.docker("running", "c0ffee5c4ed01")
    h.docker("images", f"{PROJECT}-backend:v1.1.0")


def test_a_rollback_dry_run_lists_every_step_and_changes_nothing(harness):
    _ready_for_rollback(harness)
    before = harness.state()
    result = harness.run("rollback", "--dry-run", "--start-news")
    assert result.code == 0, result.out
    assert result.result["status"] == "dry-run"
    assert result.result["steps"] == ROLLBACK_STEPS
    assert (
        "git pull --ff-only" in result.out and "Start-ScheduledTask news" in result.out
    )
    assert f"{PROJECT}-backend:v1.1.0" in result.out
    assert harness.state() == before
    assert_read_only(harness)


def test_a_rollback_without_the_pre_docker_branch_is_refused(harness):
    _ready_for_rollback(harness)
    git(harness.checkout, "branch", "-D", "pre-docker")
    result = harness.run("rollback", "--dry-run")
    assert result.code == 1 and "pre-docker" in result.result["reason"], result.out


def test_a_rollback_whose_branch_tracks_a_remote_is_refused(harness):
    """`git pull --ff-only` would move it on to the merged master (review H1)."""

    _ready_for_rollback(harness)
    git(harness.checkout, "config", "branch.pre-docker.remote", "origin")
    result = harness.run("rollback", "--dry-run")
    assert result.code == 1 and "upstream" in result.result["reason"], result.out


def test_a_rollback_without_the_volume_is_refused(harness):
    _ready_for_rollback(harness)
    (harness.fake / "docker" / "volumes").unlink()
    result = harness.run("rollback", "--dry-run")
    assert result.code == 1 and "volume" in result.result["reason"], result.out


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
    assert same.returncode == 0 and same.stdout == ""
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
