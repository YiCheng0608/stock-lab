"""tools/ops/deploy.sh with a fake gh and a recording git (Issue #314).

Each test builds an "origin" repository and a clone of it, the release checkout, under
tmp_path, with tags on origin, and copies deploy.sh, its helpers and worker/job.py (the
job locks) into a sandbox. A bin directory in front of PATH holds a fake ``gh`` that
answers ``run list`` from a JSON file the test writes and a ``git`` that records every
call before running the real git, so the tests can assert that nothing is pulled.
HOME and the data directory are under tmp_path; nothing touches GitHub, the real
checkout or the real data directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import worker.job as job

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("deploy.sh", "coordinator_lib.sh", "coordinator_json.py")
LOCK_FILES = ("backend/requirements.txt", "backend/validation-requirements.lock.txt")


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


def _bash_path(path: Path) -> str:
    """PATH entry form inside bash: /c/x/y for C:\\x\\y on Windows."""
    if os.name == "nt" and path.drive:
        return "/" + path.drive[0].lower() + path.as_posix()[2:]
    return path.as_posix()


BASH = _bash()
REAL_GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(
    BASH is None or REAL_GIT is None, reason="bash and git are required"
)

FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/gh_calls.log"
case "$1 $2" in
  "run list") cat "$d/gh_run_list.json" 2>/dev/null || echo '[]' ;;
  "issue comment")
    while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$d/comment.md"; shift; done
    [ -f "$d/gh_comment_fails" ] && exit 1 ;;
esac
exit 0
"""

FAKE_GIT = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_DIR/git_calls.log"
exec "$REAL_GIT" "$@"
"""

# The venv's python: records its arguments, fails when <fake>/pip_fails exists.
FAKE_VENV_PYTHON = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_DIR/venv_calls.log"
[ -f "$FAKE_DIR/pip_fails" ] && exit 1
exit 0
"""


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            REAL_GIT,
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "init.defaultBranch=master",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.fake = root / "fake"
        self.data = root / "data"
        self.home = root / "home"
        self.sandbox = root / "sandbox"
        self.origin = root / "origin"
        self.checkout = root / "release"
        for directory in (self.bin, self.fake, self.home, self.origin):
            directory.mkdir(parents=True)
        ops = self.sandbox / "tools" / "ops"
        ops.mkdir(parents=True)
        for name in SCRIPTS:
            shutil.copyfile(ROOT / "tools" / "ops" / name, ops / name)
        worker = self.sandbox / "backend" / "worker"
        worker.mkdir(parents=True)
        (worker / "__init__.py").write_text("", encoding="utf-8")
        shutil.copyfile(ROOT / "backend" / "worker" / "job.py", worker / "job.py")
        self.script = ops / "deploy.sh"
        for name, body in (("gh", FAKE_GH), ("git", FAKE_GIT)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)

        # origin: v0 predates #314 (no tools/ops/deploy.sh), v1 is a lightweight tag
        # on the next commit, v2 an annotated tag that also changes the lock file.
        self.commit({"README.md": "v0\n", **dict.fromkeys(LOCK_FILES, "a==1\n")})
        git(self.origin, "tag", "v0")
        self.commit({"README.md": "v1\n", "tools/ops/deploy.sh": "#!/bin/sh\n"})
        git(self.origin, "tag", "v1")
        self.commit({"README.md": "v2\n", LOCK_FILES[1]: "a==2\n"})
        git(self.origin, "tag", "-a", "v2", "-m", "v2")
        self.sha = {
            t: git(self.origin, "rev-parse", f"{t}^{{commit}}")
            for t in ("v0", "v1", "v2")
        }
        git(
            self.root,
            "clone",
            "--quiet",
            "--no-tags",
            str(self.origin),
            str(self.checkout),
        )
        git(self.checkout, "checkout", "--quiet", "--detach", self.sha["v0"])
        venv = self.checkout / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text(FAKE_VENV_PYTHON, encoding="utf-8", newline="\n")
        (venv / "python").chmod(0o755)
        self.ci("success")

    def commit(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            path = self.origin / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        (self.origin / ".gitignore").write_text(".venv/\n", encoding="utf-8")
        if not (self.origin / ".git").exists():
            git(self.origin, "init", "--quiet")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "--quiet", "-m", "commit")

    def ci(self, *conclusions: str, status: str = "completed") -> None:
        """CI runs of every tagged commit, newest (highest run id) first."""
        runs = [
            {
                "databaseId": 1000 - n,
                "headSha": sha,
                "status": status,
                "conclusion": conclusion,
            }
            for n, conclusion in enumerate(conclusions)
            for sha in self.sha.values()
        ]
        (self.fake / "gh_run_list.json").write_text(json.dumps(runs), encoding="utf-8")

    def calls(self, name: str) -> list[str]:
        path = self.fake / f"{name}_calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def head(self) -> str:
        return git(self.checkout, "rev-parse", "HEAD")

    def state(self) -> tuple:
        """What a refused deploy must leave as it was."""
        return (
            self.head(),
            git(self.checkout, "status", "--porcelain"),
            git(self.checkout, "tag", "--list"),
            self.record.exists(),
        )

    @property
    def record(self) -> Path:
        return self.data / "logs" / "deploy.json"

    def deploy(
        self, tag: str, *args: str, extra_env: dict[str, str] | None = None
    ) -> SimpleNamespace:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("STOCK_", "DEPLOY_", "GIT_"))
        }
        env.update(
            PATH=str(self.bin) + os.pathsep + env.get("PATH", ""),
            FAKE_DIR=self.fake.as_posix(),
            FAKE_BIN=_bash_path(self.bin),
            REAL_GIT=Path(REAL_GIT).as_posix(),
            HOME=self.home.as_posix(),
            STOCK_DATA_DIR=self.data.as_posix(),
            STOCK_PYTHON=Path(sys.executable).as_posix(),
        )
        env.update(extra_env or {})
        # Git for Windows' bin/bash.exe puts /mingw64/bin (the real git) in front of
        # PATH, so the fake bin directory is put first again inside bash.
        completed = subprocess.run(
            [
                BASH,
                "-c",
                'PATH="$FAKE_BIN:$PATH"; exec bash "$@"',
                "bash",
                self.script.as_posix(),
                tag,
                "--checkout",
                self.checkout.as_posix(),
                "--operator",
                "測試者",
                *args,
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


def assert_no_pull(h: Harness) -> None:
    assert not [call for call in h.calls("git") if " pull" in f" {call}"]


# Deploying -------------------------------------------------------------------------


def test_a_green_tag_is_checked_out_recorded_and_commented(harness):
    result = harness.deploy("v1")
    assert result.code == 0, result.out
    assert harness.head() == harness.sha["v1"]
    record = json.loads(harness.record.read_text(encoding="utf-8"))
    assert record["tag"] == "v1" and record["HEAD"] == harness.sha["v1"]
    assert record["previous_HEAD"] == harness.sha["v0"]
    assert record["operator"] == "測試者" and record["venv_reinstalled"] is False
    assert record["deployed_at"].endswith("Z")
    assert result.result["deployed"] is True and result.result["commented"] is True
    comment = (harness.fake / "comment.md").read_text(encoding="utf-8")
    assert "`v1`" in comment and harness.sha["v1"] in comment
    assert any(c.startswith("issue comment 1 ") for c in harness.calls("gh"))
    assert any(f"--commit {harness.sha['v1']}" in c for c in harness.calls("gh"))
    # The lock files did not change between v0 and v1.
    assert harness.calls("venv") == []
    assert_no_pull(harness)
    # The job reads what was deployed: HEAD and its tag.
    assert job.checkout_version(harness.checkout) == (harness.sha["v1"], "v1")


def test_changed_lock_files_reinstall_the_venv(harness):
    assert harness.deploy("v1", "--no-comment").code == 0
    result = harness.deploy("v2", "--no-comment")
    assert result.code == 0, result.out
    assert harness.head() == harness.sha["v2"]
    (call,) = harness.calls("venv")
    assert call.startswith("-m pip install --disable-pip-version-check -r ")
    assert call.endswith("/release/" + LOCK_FILES[1])
    record = json.loads(harness.record.read_text(encoding="utf-8"))
    assert (
        record["venv_reinstalled"] is True
        and record["previous_HEAD"] == harness.sha["v1"]
    )
    assert not (harness.fake / "comment.md").exists()
    assert not [c for c in harness.calls("gh") if c.startswith("issue")]
    assert_no_pull(harness)


def test_reinstall_forces_the_venv_install(harness):
    assert harness.deploy("v1", "--no-comment", "--reinstall").code == 0
    assert len(harness.calls("venv")) == 1


def test_a_failed_venv_install_writes_no_record(harness):
    (harness.fake / "pip_fails").touch()
    result = harness.deploy("v1", "--no-comment", "--reinstall")
    assert result.code == 3, result.out
    assert "venv 重裝失敗" in result.out
    assert not harness.record.exists()


def test_a_failed_comment_exits_4_after_deploying(harness):
    (harness.fake / "gh_comment_fails").touch()
    result = harness.deploy("v1")
    assert result.code == 4, result.out
    assert harness.head() == harness.sha["v1"] and harness.record.exists()
    assert result.result == {
        "deployed": True,
        "tag": "v1",
        "HEAD": harness.sha["v1"],
        "commented": False,
    }


# Refusing (AC-1): the checkout stays as it was -------------------------------------


@pytest.mark.parametrize(
    "conclusions,status,shown",
    [
        (("failure",), "completed", "failure"),
        (("failure", "success"), "completed", "failure"),
        (("success",), "in_progress", "pending"),
        ((), "completed", "missing"),
    ],
    ids=["red", "red-after-green", "running", "no-run"],
)
def test_a_tag_whose_ci_is_not_green_is_refused(harness, conclusions, status, shown):
    harness.ci(*conclusions, status=status)
    before = harness.state()
    result = harness.deploy("v1")
    assert result.code == 1, result.out
    assert f"CI 是 {shown}" in result.out
    assert harness.state() == before
    assert not [c for c in harness.calls("git") if c.split()[2:3] == ["fetch"]]
    assert not [c for c in harness.calls("gh") if c.startswith("issue")]


@pytest.mark.parametrize("cancelled_id,code", [(1, 0), (3, 1)], ids=["older", "newer"])
def test_the_latest_run_is_the_highest_run_id_not_the_first_listed(
    harness, cancelled_id, code
):
    # Two runs created at the same second: gh lists them in any order, and the
    # concurrency group cancels the older one (PR #330's own CI).
    sha = harness.sha["v1"]
    runs = [
        {
            "databaseId": cancelled_id,
            "headSha": sha,
            "status": "completed",
            "conclusion": "cancelled",
        },
        {
            "databaseId": 2,
            "headSha": sha,
            "status": "completed",
            "conclusion": "success",
        },
    ]
    (harness.fake / "gh_run_list.json").write_text(json.dumps(runs), encoding="utf-8")
    result = harness.deploy("v1", "--no-comment")
    assert result.code == code, result.out
    assert (harness.head() == sha) is (code == 0)
    if code:
        assert "CI 是 cancelled" in result.out


@pytest.mark.parametrize("held", ["daily", "news", "watchdog"])
def test_a_running_job_refuses_the_deploy(harness, held):
    lock = job.FileLock(job.lock_path(harness.data, held))
    assert lock.acquire()
    try:
        before = harness.state()
        result = harness.deploy("v1")
    finally:
        lock.release()
    assert result.code == 1, result.out
    assert "排程執行中" in result.out
    assert harness.state() == before
    assert_no_pull(harness)


def test_the_locks_are_released_after_the_deploy(harness):
    assert harness.deploy("v1", "--no-comment").code == 0
    for name in ("daily", "news", "watchdog"):
        lock = job.FileLock(job.lock_path(harness.data, name))
        assert lock.acquire(), name
        lock.release()


@pytest.mark.parametrize("change", ["modified", "untracked", "index.lock"])
def test_uncommitted_changes_refuse_the_deploy(harness, change):
    if change == "modified":
        (harness.checkout / "README.md").write_text("local\n", encoding="utf-8")
    elif change == "untracked":
        (harness.checkout / "notes.txt").write_text("x\n", encoding="utf-8")
    else:
        (harness.checkout / ".git" / "index.lock").touch()
    before = harness.state()
    result = harness.deploy("v1")
    assert result.code == 1, result.out
    assert (
        "進行中的 git 操作" if change == "index.lock" else "未 commit 的改動"
    ) in result.out
    assert harness.state() == before
    assert harness.calls("gh") == []


def test_a_tag_missing_on_origin_is_refused(harness):
    before = harness.state()
    result = harness.deploy("v9")
    assert result.code == 1 and "origin 沒有 tag v9" in result.out, result.out
    assert harness.state() == before


def test_a_tag_before_314_is_refused(harness):
    git(harness.checkout, "checkout", "--quiet", "--detach", harness.sha["v1"])
    before = harness.state()
    result = harness.deploy("v0")
    assert result.code == 1 and "早於 #314" in result.out, result.out
    # Refused after the fetch: the tag ref the fetch created is deleted again.
    assert harness.state() == before
    assert any(c.split()[2:3] == ["fetch"] for c in harness.calls("git"))


def test_a_refusal_after_the_fetch_keeps_a_tag_that_was_there(harness):
    git(harness.checkout, "fetch", "--quiet", "origin", "refs/tags/v0:refs/tags/v0")
    before = harness.state()
    assert "v0" in before[2]
    result = harness.deploy("v0")
    assert result.code == 1 and "早於 #314" in result.out, result.out
    assert harness.state() == before


def test_a_tag_that_moved_after_the_ci_check_is_refused(harness):
    # The locked phase gets the SHA the CI check passed; origin's tag now points
    # elsewhere (moved between ls-remote and fetch).
    before = harness.state()
    result = harness.deploy(
        "v1", extra_env={"DEPLOY_LOCKS_HELD": "1", "DEPLOY_SHA": harness.sha["v2"]}
    )
    assert result.code == 1 and "不是 CI 核對過的" in result.out, result.out
    assert harness.state() == before


def test_a_deploy_from_inside_the_checkout_is_refused(harness):
    ops = harness.checkout / "tools" / "ops"
    ops.mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copyfile(harness.script.parent / name, ops / name)
    harness.script = ops / "deploy.sh"
    before = harness.head()
    result = harness.deploy("v1")
    assert result.code == 1 and "這支腳本在發佈 checkout 裡" in result.out, result.out
    assert harness.head() == before
