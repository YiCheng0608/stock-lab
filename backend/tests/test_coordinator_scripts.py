"""tools/ops/dispatch.sh, close_task.sh and patrol.sh with fake orca, gh and git (Issue #282).

The event monitor (monitor.sh, event_queue.py, #316) has its own tests in
test_event_monitor.py on the same harness.

Each test copies the scripts into a sandbox repository under tmp_path, puts a bin
directory holding fake ``orca``, ``gh`` and ``git`` scripts in front of PATH, points HOME
and STOCK_DATA_DIR into tmp_path and runs the copy through bash. The fakes record every
call in ``<fake>/<name>_calls.log`` and answer from JSON files the test writes into the
fake directory (a missing answer is an empty success). Nothing touches Orca, GitHub, the
repository's git state or the real data directory.

A fake ``docker`` is always first on PATH as well (#360): close_task.sh lists and deletes
Docker resources, and no test may reach the real daemon, its images or its volumes.

Every path a test hands to close_task.sh lies under tmp_path, including the "repository
root" and "home" it must refuse: with the refusal broken (a mutation run, or a bug) the
script can only delete sandbox files. A first version passed the real checkout as the
repo-root case and a mutation run deleted the worktree (#282).

The junction test creates a real NTFS junction on Windows (``_winapi.CreateJunction``)
and a symlink elsewhere, so close_task's unlink-before-delete is exercised on both.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "tools" / "ops"
SCRIPTS = (
    "coordinator_lib.sh",
    "coordinator_json.py",
    "dispatch.sh",
    "close_task.sh",
    "patrol.sh",
    "event_queue.py",
    "monitor.sh",
    "orca_wake.sh",
    "http_wake.sh",
    "http_orca.sh",
    "wake_listener.py",
    "wake_listener_start.sh",
    "gh_auth.sh",
    "compact_hook.sh",
    # #534: the commitments file, and the take-over run (test_take_over.py)
    "commitments.py",
    "commit.sh",
    "comment.sh",
    "take_over.sh",
)
REPO_ID = "repo-1"


def _unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


NO_LISTENER_PORT = _unused_port()
SHA = "a" * 40
MERGE_SHA = "b" * 40
# A long-lived integration branch the tests name themselves (#332, #428): close_task.sh in
# the sandbox gets it through Harness.integration_branches, so no test depends on the
# repository's own list (empty since feat/docker reached master, #331).
INTEGRATION = "feat/umbrella"
# The answer of gh run list --branch INTEGRATION (see FAKE_GH).
INTEGRATION_RUNS = "gh_run_list_" + INTEGRATION.replace("/", "_")
# The tip of origin/<INTEGRATION>.
INTEGRATION_SHA = "d" * 40
# 2026-10-25 12:00:00 UTC
NOW = int(datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc).timestamp())


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
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required")

# Answers come from <fake>/<name>_<sub1>_<sub2>.json (orca, gh) and the exit code is 1
# when the answer says "ok": false. Send texts are kept for asserts; worktree rm deletes
# the directory it names, as Orca does. worktree create starts the new worktree at its
# --base-branch (origin/master without one) as <fake>/refs.txt names it, unless a test
# wrote <fake>/worktree_head.txt first; git rev-parse HEAD answers from that file.
# A <fake>/orca_<sub1>_<sub2>.hook file is run (bash) before that call answers.
FAKE_ORCA = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/orca_calls.log"
key="orca_$1_$2"
[ -f "$d/$key.hook" ] && bash "$d/$key.hook"
if [ "$1 $2" = "worktree create" ] && [ ! -f "$d/worktree_head.txt" ]; then
  ref=origin/master prev=""
  for a in "$@"; do [ "$prev" = --base-branch ] && ref="$a"; prev="$a"; done
  sha="$(awk -v r="$ref" '$1 == r { print $2 }' "$d/refs.txt" 2>/dev/null)"
  echo "${sha:-$FAKE_SHA}" >"$d/worktree_head.txt"
fi
# With <fake>/run_terminal_command, terminal create runs its --command in bash, as Orca types
# it into the terminal's Git Bash; the fake bin directory (a test's fake claude) comes first.
# The terminal's shell does not inherit dispatch.sh's environment, so neither does this one's
# COMPOSE_PROJECT_NAME (#339 review S2).
if [ "$1 $2" = "terminal create" ] && [ -f "$d/run_terminal_command" ]; then
  prev=""
  for a in "$@"; do
    [ "$prev" = --command ] && env -u COMPOSE_PROJECT_NAME PATH="$FAKE_BIN:$PATH" bash -c "$a"
    prev="$a"
  done
fi
if [ "$1 $2" = "terminal send" ]; then
  while [ $# -gt 0 ]; do [ "$1" = --text ] && printf '%s' "$2" >"$d/sent_text.txt"; shift; done
fi
if [ "$1 $2" = "worktree rm" ]; then
  while [ $# -gt 0 ]; do
    if [ "$1" = --worktree ]; then
      case "${2#*::}" in "$SANDBOX"/*) rm -rf -- "${2#*::}" ;; esac
    fi
    shift
  done
fi
if [ -f "$d/$key.json" ]; then cat "$d/$key.json"; else echo '{"ok": true, "result": {}}'; fi
grep -q '"ok": *false' "$d/$key.json" 2>/dev/null && exit 1
exit 0
"""

# A <fake>/<key>.fail file makes that call exit 1 with the file's text on stderr (key
# gh_comments for the comments listing, else gh_<sub1>_<sub2>). <key>.sleep holding N
# makes it hang N seconds, <key>.stderr is written to stderr, <key>.hook is run (bash)
# first.
FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/gh_calls.log"
# With <fake>/gh_issue_close_sets_closed, issue close closes the Issue (issue view then
# answers CLOSED) even when the call itself fails.
if [ "$1 $2" = "issue close" ] && [ -f "$d/gh_issue_close_sets_closed" ]; then
  echo '{"state": "CLOSED"}' >"$d/gh_issue_view.json"
fi
case "$1 $2" in "api repos/"*) k=gh_comments ;; *) k="gh_$1_$2" ;; esac
[ -f "$d/$k.hook" ] && bash "$d/$k.hook"
[ -f "$d/$k.sleep" ] && sleep "$(cat "$d/$k.sleep")"
[ -f "$d/$k.stderr" ] && cat "$d/$k.stderr" >&2
[ -f "$d/$k.fail" ] && { cat "$d/$k.fail" >&2; exit 1; }
case "$1 $2" in
  "api graphql")
    case "$*" in
      *addProjectV2ItemById*) echo "ITEM-NEW" ;;
      *updateProjectV2ItemFieldValue*) cat "$d/board_item.txt" 2>/dev/null || echo "ITEM-1" ;;
      # patrol.sh's open Issues and PRs with their comments (#401)
      *OpenQuestions*) [ -f "$d/gh_questions_fails" ] && exit 1
        cat "$d/gh_questions.json" 2>/dev/null || echo '{}' ;;
      *) cat "$d/gh_board.json" ;;
    esac ;;
  "api repos/"*) cat "$d/gh_comments.json" 2>/dev/null || echo '[]' ;;
  # run list --branch B answers from gh_run_list_<B, / as _>.json when the test wrote
  # one, else from gh_run_list.json.
  "run list")
    b="" prev=""
    for a in "$@"; do [ "$prev" = --branch ] && b="$a"; prev="$a"; done
    f="$d/gh_run_list_$(printf '%s' "$b" | tr / _).json"
    [ -f "$f" ] || f="$d/gh_run_list.json"
    if [ -f "$f" ]; then cat "$f"; else echo '[]'; fi ;;
  # <fake>/gh_<sub1>_<sub2>_fails makes that call exit 1.
  *) key="gh_$1_$2"; [ -f "$d/${key}_fails" ] && exit 1
     [ -f "$d/$key.json" ] && cat "$d/$key.json" || echo '[]' ;;
esac
"""

# git -C <dir> <subcommand> ...: branches live in <fake>/branches.txt, one per line, and
# rev-parse answers from <fake>/refs.txt ("<ref> <sha>" lines; $FAKE_SHA when unlisted).
# branch -D fails when <fake>/git_branch_in_use exists (the branch stays), and when
# <fake>/git_branch_gone_at_delete exists it fails with the branch already gone: orca
# worktree rm deleted it after close_task's show-ref had seen it (#290). With
# <fake>/git_unreadable_after_delete, show-ref answers 128 (git could not read the repo)
# once branch -D has run.
FAKE_GIT = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/git_calls.log"
[ "$1" = -C ] && shift 2
touch "$d/branches.txt"
case "$1" in
  fetch) exit 0 ;;
  rev-parse)
    if [ "$2" = HEAD ] && [ -f "$d/worktree_head.txt" ]; then cat "$d/worktree_head.txt"; exit 0; fi
    sha="$(awk -v r="$2" '$1 == r { print $2 }' "$d/refs.txt" 2>/dev/null)"
    echo "${sha:-$FAKE_SHA}" ;;
  show-ref)
    [ -f "$d/git_unreadable_after_delete" ] && [ -f "$d/git_branch_D_ran" ] && exit 128
    grep -qxF "${4#refs/heads/}" "$d/branches.txt"; exit ;;
  for-each-ref) pat="${*: -1}"; pat="${pat#refs/heads/}"; grep -x "${pat%\*}.*" "$d/branches.txt" || true ;;
  branch)
    if [ "$2" = -m ]; then
      grep -vxF "$3" "$d/branches.txt" >"$d/b.tmp"; echo "$4" >>"$d/b.tmp"; mv "$d/b.tmp" "$d/branches.txt"
    elif [ "$2" = -D ]; then
      touch "$d/git_branch_D_ran"
      if [ -f "$d/git_branch_in_use" ]; then
        echo "error: cannot delete branch '$3' used by worktree at '$d'" >&2; exit 1
      fi
      grep -vxF "$3" "$d/branches.txt" >"$d/b.tmp"; mv "$d/b.tmp" "$d/branches.txt"
      if [ -f "$d/git_branch_gone_at_delete" ]; then
        echo "error: branch '$3' not found." >&2; exit 1
      fi
    fi ;;
  # merge-base --is-ancestor A B: exit code from <fake>/git_ancestor_exit_<A> when the test
  # wrote one (A a sha), else from <fake>/git_ancestor_exit (default 0).
  merge-base)
    [ -f "$d/git_ancestor_exit_$3" ] && exit "$(cat "$d/git_ancestor_exit_$3")"
    exit "$(cat "$d/git_ancestor_exit" 2>/dev/null || echo 0)" ;;
  rev-list) cat "$d/git_rev_list.txt" 2>/dev/null; exit 0 ;;
  status) cat "$d/git_status.txt" 2>/dev/null ;;
  worktree)
    [ "$2" = list ] && cat "$d/git_worktrees.txt" 2>/dev/null
    exit 0 ;;
esac
exit 0
"""


# docker: containers, images, volumes and networks live in <fake>/docker_<kind>.tsv
# ("NAME STATE IMAGE MOUNTS NETWORKS", "REPOSITORY TAG", "NAME", "NAME"; tab-separated), and
# the listings print them with the kind in front, as docker_listing's --format asks. rm, rmi,
# volume rm and network rm delete the line, and fail for a resource that is not there or is
# listed in <fake>/docker_fails.txt. <fake>/docker_missing answers 127 (no docker command),
# <fake>/docker_down 1 (no daemon), <fake>/docker_hangs never answers.
FAKE_DOCKER = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/docker_calls.log"
[ -f "$d/docker_missing" ] && exit 127
[ -f "$d/docker_hangs" ] && exec sleep 60
if [ -f "$d/docker_down" ]; then echo "Cannot connect to the Docker daemon" >&2; exit 1; fi
list() { [ ! -f "$d/docker_$2.tsv" ] || sed "s/^/$1\t/" "$d/docker_$2.tsv"; }
drop() {
  f="$d/docker_$1.tsv"
  if grep -qxF -- "$2" "$d/docker_fails.txt" 2>/dev/null; then echo "Error: $2 is in use" >&2; exit 1; fi
  awk -F '\t' -v k="$2" -v image="${3:-}" '(image ? $1 ":" $2 : $1) == k { found = 1; next } { print }
    END { exit !found }' "$f" >"$f.tmp" 2>/dev/null || { rm -f "$f.tmp"; echo "Error: no such $1: $2" >&2; exit 1; }
  mv "$f.tmp" "$f"
}
case "$1 ${2:-}" in
  "ps "*) list container containers ;;
  "images "*) list image images ;;
  "volume ls") list volume volumes ;;
  "network ls") list network networks ;;
  "rm "*) drop containers "$2" ;;
  "rmi "*) drop images "$2" 1 ;;
  "volume rm") drop volumes "$3" ;;
  "network rm") drop networks "$3" ;;
esac
exit 0
"""


def _ok(result: dict) -> dict:
    return {"ok": True, "result": result}


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.fake = root / "fake"
        self.data = root / "data"
        self.home = root / "home"
        # TEMP and TMP of every script run (#472): close_task.sh deletes Claude Code
        # scratchpads under $TEMP/claude, so no run may see the real Temp.
        self.temp = root / "temp"
        # The scripts run from a copy, so repo_root is this sandbox, not the checkout.
        self.repo = root / "repo"
        self.ops = self.repo / "tools" / "ops"
        for directory in (
            self.bin,
            self.fake,
            self.data / "logs" / "compactions",
            self.home,
            self.temp,
            self.ops,
            self.repo / ".git",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        for name in SCRIPTS:
            shutil.copyfile(OPS / name, self.ops / name)
        for name, body in (
            ("orca", FAKE_ORCA),
            ("gh", FAKE_GH),
            ("git", FAKE_GIT),
            ("docker", FAKE_DOCKER),
        ):
            path = self.bin / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        self.answer(
            "orca_repo_list",
            _ok(
                {
                    "repos": [
                        {
                            "id": REPO_ID,
                            "gitRemoteIdentity": {
                                "canonicalKey": "github.com/YiCheng0608/stock-lab"
                            },
                        }
                    ]
                }
            ),
        )
        self.answer("gh_board", _board(item="ITEM-1"))

    def integration_branches(self, *names: str) -> None:
        """Set integration_branches in the sandbox copy of close_task.sh (#428)."""
        path = self.ops / "close_task.sh"
        text, count = re.subn(
            r"^integration_branches=\(.*\)$",
            f"integration_branches=({' '.join(names)})",
            path.read_text(encoding="utf-8"),
            flags=re.M,
        )
        assert count == 1, "close_task.sh has no integration_branches=(...) line"
        path.write_text(text, encoding="utf-8", newline="\n")

    def answer(self, key: str, value) -> None:
        (self.fake / f"{key}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )

    def write(self, name: str, text: str) -> None:
        (self.fake / name).write_text(text, encoding="utf-8", newline="\n")

    def calls(self, name: str) -> list[str]:
        path = self.fake / f"{name}_calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def branches(self) -> list[str]:
        path = self.fake / "branches.txt"
        return path.read_text(encoding="utf-8").split() if path.exists() else []

    def run(self, script: str, *args: str, **env: str) -> subprocess.CompletedProcess:
        return self.run_bash(
            'exec bash "$@"', (self.ops / script).as_posix(), *args, **env
        )

    def run_bash(
        self, code: str, *args: str, **env: str
    ) -> subprocess.CompletedProcess:
        base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("STOCK_", "ORCA_", "CLAUDE_CODE_"))
        }
        base.update(
            PATH=str(self.bin) + os.pathsep + base.get("PATH", ""),
            FAKE_DIR=self.fake.as_posix(),
            FAKE_BIN=_bash_path(self.bin),
            FAKE_SHA=SHA,
            SANDBOX=self.root.as_posix(),
            HOME=self.home.as_posix(),
            TEMP=self.temp.as_posix(),
            TMP=self.temp.as_posix(),
            STOCK_DATA_DIR=self.data.as_posix(),
            STOCK_PYTHON=Path(sys.executable).as_posix(),
            PATROL_NOW=str(NOW),
            # A port nothing listens on: patrol.sh reports no wake listener, whatever
            # runs on this machine (test_wake_listener starts its own).
            WAKE_LISTENER_PORT=str(NO_LISTENER_PORT),
            # A listener started here talks to the fake orca, never to a real one.
            STOCK_WAKE_TEST="1",
            WAKE_LISTENER_ORCA=(self.bin / "orca").as_posix(),
        )
        base.update(env)
        # Git for Windows' bin/bash.exe puts /mingw64/bin (the real git) in front of PATH,
        # so the fake bin directory is put first again inside bash.
        return subprocess.run(
            [BASH, "-c", f'PATH="$FAKE_BIN:$PATH"; {code}', "bash", *args],
            env=base,
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )

    def close_task(self, *dirs: Path, **env: str) -> subprocess.CompletedProcess:
        args: list[str] = []
        for path in dirs:
            # Only sandbox paths ever reach close_task.sh (see the module docstring).
            assert path.resolve().is_relative_to(self.root.resolve()), path
            args += ["--extra-dir", path.as_posix()]
        return self.run("close_task.sh", "282", *args, **env)


def _board(item: str | None) -> dict:
    field = {
        "id": "FIELD-1",
        "options": [
            {"id": "OPT-TODO", "name": "待辦"},
            {"id": "OPT-DEV", "name": "開發中"},
            {"id": "OPT-DONE", "name": "完成"},
        ],
    }
    project = {"id": "PROJ-1", "number": 1, "field": field}
    nodes = [{"id": item, "project": project}] if item else []
    return {
        "data": {
            "repository": {
                "issue": {"id": "ISSUE-NODE", "projectItems": {"nodes": nodes}}
            },
            "user": {"projectV2": {"id": "PROJ-1", "field": field}},
        }
    }


def _json_line(result: subprocess.CompletedProcess) -> dict:
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path)


# --- dispatch.sh -------------------------------------------------------------------


@pytest.fixture
def dispatch(h: Harness) -> Harness:
    wt = h.root / "wt" / "task-282-dryrun"
    wt.mkdir(parents=True)
    h.answer(
        "orca_worktree_create",
        _ok(
            {
                "worktree": {
                    "path": wt.as_posix(),
                    "branch": "refs/heads/YiCheng0608/task-282-dryrun",
                }
            }
        ),
    )
    h.answer("orca_terminal_create", _ok({"terminal": {"handle": "term_new"}}))
    h.answer(
        "orca_terminal_wait",
        _ok(
            {"wait": {"handle": "term_new", "condition": "tui-idle", "satisfied": True}}
        ),
    )
    h.answer(
        "orca_terminal_send",
        _ok(
            {
                "send": {
                    "accepted": True,
                    "prompt": {"stages": ["input_accepted", "turn_started"]},
                }
            }
        ),
    )
    h.answer("orca_terminal_read", _ok({"terminal": {"tail": ["❯ 你好"]}}))
    task = h.root / "task.md"
    # Over the old 30,000-byte limit, with quotes, $, backticks and CRLF line ends: none of
    # it reaches the terminal, only the path does (#315).
    task.write_bytes(
        (
            "你是 #282 的工程師。\r\n"
            + 'AC-1：引號 " 錢號 $HOME $(id) 反引號 `id` 不得展開。\r\n' * 600
            + "最後一行：只回覆「收到」。\r\n"
        ).encode()
    )
    assert task.stat().st_size > 30000
    h.task = task
    return h


def _dispatch(h: Harness, task: str | None = None) -> subprocess.CompletedProcess:
    return h.run(
        "dispatch.sh", "282", "dryrun", "--task-file", task or h.task.as_posix()
    )


def _notice(path: str) -> str:
    return (
        f"請用 Read 工具讀取任務檔 {path}（UTF-8），依其內容開工；"
        "開工留言回貼任務檔裡的 Issue 連結與 AC 數。"
    )


def test_dispatch_sends_only_after_tui_idle_is_satisfied(dispatch: Harness) -> None:
    result = _dispatch(dispatch)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["sent"] is True and line["turn_started"] is True
    assert line["branch"] == "task/282-dryrun" and line["head"] == SHA
    assert line["terminal"] == "term_new" and line["board"] == "開發中"
    orca = dispatch.calls("orca")
    create = next(c for c in orca if c.startswith("worktree create"))
    assert "--no-parent" in create and "--setup skip" in create
    assert f"--repo id:{REPO_ID}" in create
    wait = next(i for i, c in enumerate(orca) if c.startswith("terminal wait"))
    send = next(i for i, c in enumerate(orca) if c.startswith("terminal send"))
    assert wait < send
    assert "--for tui-idle --timeout-ms 60000" in orca[wait]
    assert "--timeout " not in orca[wait]
    sent = (dispatch.fake / "sent_text.txt").read_bytes().decode("utf-8")
    assert sent == _notice(dispatch.task.as_posix())
    assert line["task_file"] == dispatch.task.as_posix()
    terminal = next(c for c in orca if c.startswith("terminal create"))
    assert terminal.endswith(
        "--shell git-bash --command COMPOSE_PROJECT_NAME=task-282 claude"
        " --model claude-opus-5-5 --effort high"
        f' --add-dir "{dispatch.root.as_posix()}" --json'
    )
    assert "branch -m YiCheng0608/task-282-dryrun task/282-dryrun" in " ".join(
        dispatch.calls("git")
    )
    update = [c for c in dispatch.calls("gh") if "updateProjectV2ItemFieldValue" in c]
    assert len(update) == 1 and "o=OPT-DEV" in update[0] and "i=ITEM-1" in update[0]


def test_dispatch_starts_claude_with_the_task_compose_project(
    dispatch: Harness,
) -> None:
    """AC-3 (#339): the terminal's claude runs with COMPOSE_PROJECT_NAME=task-<issue>, not
    the coordinator's."""
    claude = dispatch.bin / "claude"
    claude.write_text(
        '#!/usr/bin/env bash\nprintf "%s|%s" "$COMPOSE_PROJECT_NAME" "$*" >"$FAKE_DIR/claude.txt"\n',
        encoding="utf-8",
        newline="\n",
    )
    claude.chmod(0o755)
    dispatch.write("run_terminal_command", "")
    result = dispatch.run(
        "dispatch.sh",
        "282",
        "dryrun",
        "--task-file",
        dispatch.task.as_posix(),
        COMPOSE_PROJECT_NAME="stock-lab",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    ran = (dispatch.fake / "claude.txt").read_text(encoding="utf-8")
    assert ran == (
        "task-282|--model claude-opus-5-5 --effort high"
        f" --add-dir {dispatch.task.parent.as_posix()}"
    )
    # The prefix is POSIX syntax: the terminal's shell is Git Bash whatever Orca's default.
    (create,) = [c for c in dispatch.calls("orca") if c.startswith("terminal create")]
    assert " --shell git-bash " in create


def test_dispatch_sends_one_line_with_the_path_and_none_of_the_task_text(
    dispatch: Harness,
) -> None:
    """#315 AC-2: the terminal gets one sentence and the path, never the task text."""
    result = _dispatch(dispatch)
    assert result.returncode == 0, result.stdout + result.stderr
    sends = [c for c in dispatch.calls("orca") if c.startswith("terminal send")]
    assert len(sends) == 1
    sent = (dispatch.fake / "sent_text.txt").read_bytes().decode("utf-8")
    assert "\n" not in sent and "\r" not in sent
    body = dispatch.task.read_text(encoding="utf-8").splitlines()
    for line in body:
        assert line not in sent and line not in sends[0]
    assert sent.replace(dispatch.task.as_posix(), "<path>") == _notice("<path>")


def test_dispatch_sends_the_absolute_path_of_a_relative_task_file(
    dispatch: Harness,
) -> None:
    """The engineer session runs in the new worktree, so a relative path would miss."""
    result = _dispatch(dispatch, "task.md")  # the scripts run with cwd = sandbox root
    assert result.returncode == 0, result.stdout + result.stderr
    sent = (dispatch.fake / "sent_text.txt").read_bytes().decode("utf-8")
    assert sent == _notice(dispatch.task.as_posix())


def test_dispatch_lets_claude_read_a_task_file_under_spaces_and_cjk(
    dispatch: Harness,
) -> None:
    """#327 review A: the directory goes to --add-dir in double quotes."""
    folder = dispatch.root / "t282" / "任務 檔"
    folder.mkdir(parents=True)
    task = folder / "task.md"
    shutil.copyfile(dispatch.task, task)
    result = _dispatch(dispatch, task.as_posix())
    assert result.returncode == 0, result.stdout + result.stderr
    terminal = next(
        c for c in dispatch.calls("orca") if c.startswith("terminal create")
    )
    assert f'--add-dir "{folder.as_posix()}" --json' in terminal
    sent = (dispatch.fake / "sent_text.txt").read_bytes().decode("utf-8")
    assert sent == _notice(task.as_posix())


@pytest.mark.parametrize(
    "where, error",
    [
        ("a\nb.md", "任務檔路徑不能有換行"),
        ("a\rb.md", "任務檔路徑不能有換行"),
        ("a$b/task.md", "任務檔目錄不能含"),
        ("a%b/task.md", "任務檔目錄不能含"),
        ("a!b/task.md", "任務檔目錄不能含"),
        ("a`b/task.md", "任務檔目錄不能含"),
    ],
    ids=["lf", "cr", "dollar", "percent", "bang", "backtick"],
)
def test_dispatch_refuses_a_task_path_it_cannot_pass_on(
    dispatch: Harness, where: str, error: str
) -> None:
    """A newline would end the sent line; these characters expand in the shell that
    runs --command (cmd, PowerShell or bash). Refused before anything is created."""
    task = dispatch.root / where
    if "\n" not in where and "\r" not in where:  # Windows file names cannot hold either
        task.parent.mkdir(parents=True)
        shutil.copyfile(dispatch.task, task)
    # Through the environment: Windows splits a command-line argument at a newline.
    result = dispatch.run_bash(
        'exec bash "$1" 282 dryrun --task-file "$TASK"',
        (dispatch.ops / "dispatch.sh").as_posix(),
        TASK=task.as_posix(),
    )
    assert result.returncode == 64, result.stdout + result.stderr
    assert error in result.stderr
    assert not dispatch.calls("orca") and not dispatch.calls("git")


def test_dispatch_help_shows_the_line_it_sends(dispatch: Harness) -> None:
    """#315 AC-3: --help and WORKFLOW 任務流程第 2 步 quote the sent line. The doc is
    in BACKEND_READ_FILES (tools/ci/checks.py), so a change to it alone runs this test."""
    help_text = dispatch.run("dispatch.sh", "--help")
    assert help_text.returncode == 0, help_text.stderr
    assert _notice("<path>") in help_text.stdout
    assert "--add-dir" in help_text.stdout
    assert "30000" not in help_text.stdout
    workflow = (ROOT / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
    assert _notice("<path>") in workflow
    assert '--effort <effort> --add-dir "<任務檔目錄>"' in workflow


@pytest.mark.parametrize(
    "wait",
    [
        {"ok": False, "error": {"code": "timeout", "message": "timeout"}},
        {"ok": False, "error": {"code": "invalid_argument", "message": "Unknown flag"}},
        _ok({"wait": {"condition": "tui-idle", "satisfied": False}}),
    ],
    ids=["timeout", "bad-flag", "satisfied-false"],
)
def test_dispatch_does_not_send_when_the_terminal_is_not_ready(
    dispatch: Harness, wait: dict
) -> None:
    dispatch.answer("orca_terminal_wait", wait)
    result = _dispatch(dispatch)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _json_line(result)["sent"] is False
    assert not [c for c in dispatch.calls("orca") if c.startswith("terminal send")]
    assert not (dispatch.fake / "sent_text.txt").exists()
    assert not [c for c in dispatch.calls("gh") if "updateProjectV2" in c]


def test_dispatch_reports_a_send_without_turn_started(dispatch: Harness) -> None:
    dispatch.answer(
        "orca_terminal_send",
        _ok({"send": {"accepted": True, "prompt": {"stages": ["input_accepted"]}}}),
    )
    result = _dispatch(dispatch)
    assert result.returncode == 3, result.stdout + result.stderr
    line = _json_line(result)
    assert line["sent"] is True and line["turn_started"] is False
    assert (
        len([c for c in dispatch.calls("orca") if c.startswith("terminal send")]) == 1
    )


def test_dispatch_refuses_an_existing_branch_before_creating_anything(
    dispatch: Harness,
) -> None:
    dispatch.write("branches.txt", "task/282-dryrun\n")
    result = _dispatch(dispatch)
    assert result.returncode == 1, result.stdout + result.stderr
    assert not [c for c in dispatch.calls("orca") if c.startswith("worktree create")]


def test_dispatch_no_board_leaves_the_board_alone(dispatch: Harness) -> None:
    result = dispatch.run(
        "dispatch.sh",
        "282",
        "dryrun",
        "--task-file",
        dispatch.task.as_posix(),
        "--no-board",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _json_line(result)["board"] == "skipped"
    assert not dispatch.calls("gh")


def test_dispatch_adds_an_issue_missing_from_the_board(dispatch: Harness) -> None:
    dispatch.answer("gh_board", _board(item=None))
    dispatch.write("board_item.txt", "ITEM-NEW\n")
    result = _dispatch(dispatch)
    assert result.returncode == 0, result.stdout + result.stderr
    gh = dispatch.calls("gh")
    add = [c for c in gh if "addProjectV2ItemById" in c]
    assert len(add) == 1 and "c=ISSUE-NODE" in add[0]
    assert any("updateProjectV2" in c and "i=ITEM-NEW" in c for c in gh)


def _git_subcommands(h: Harness) -> list[str]:
    """The git calls without their leading ``-C <dir>``."""
    return [c.split(" ", 2)[2] if c.startswith("-C ") else c for c in h.calls("git")]


def _dispatch_from(h: Harness, base: str | None) -> subprocess.CompletedProcess:
    args = ["282", "dryrun", "--task-file", h.task.as_posix()]
    if base is not None:
        args += ["--base", base]
    return h.run("dispatch.sh", *args)


def test_dispatch_without_base_fetches_and_checks_origin_master(
    dispatch: Harness,
) -> None:
    """#332: no --base runs the commands dispatch.sh ran before --base existed."""
    dispatch.write(
        "refs.txt", f"origin/master {SHA}\norigin/{INTEGRATION} {INTEGRATION_SHA}\n"
    )
    result = _dispatch_from(dispatch, None)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["head"] == SHA and line["base"] == SHA
    assert _git_subcommands(dispatch) == [
        "show-ref --verify --quiet refs/heads/task/282-dryrun",
        "fetch --quiet origin master",
        "rev-parse origin/master",
        "rev-parse HEAD",
        "branch -m YiCheng0608/task-282-dryrun task/282-dryrun",
    ]
    create = [c for c in dispatch.calls("orca") if c.startswith("worktree create")]
    assert create == [
        f"worktree create --repo id:{REPO_ID} --name task-282-dryrun --no-parent "
        "--setup skip --json"
    ]


def test_dispatch_from_another_base_starts_the_worktree_at_its_tip(
    dispatch: Harness,
) -> None:
    """AC-1 (#332): --base origin/<branch> fetches it and the new HEAD is its tip."""
    dispatch.write(
        "refs.txt", f"origin/master {SHA}\norigin/{INTEGRATION} {INTEGRATION_SHA}\n"
    )
    result = _dispatch_from(dispatch, f"origin/{INTEGRATION}")
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["head"] == INTEGRATION_SHA and line["base"] == INTEGRATION_SHA
    assert line["sent"] is True and line["branch"] == "task/282-dryrun"
    git = _git_subcommands(dispatch)
    assert f"fetch --quiet origin {INTEGRATION}" in git
    assert f"rev-parse origin/{INTEGRATION}" in git
    assert not [c for c in git if "master" in c]
    (create,) = [c for c in dispatch.calls("orca") if c.startswith("worktree create")]
    assert create.endswith(f"--setup skip --base-branch origin/{INTEGRATION} --json")


@pytest.mark.parametrize(
    "base, worktree_head, named",
    [
        (None, INTEGRATION_SHA, "origin/master"),
        (f"origin/{INTEGRATION}", SHA, f"origin/{INTEGRATION}"),
    ],
    ids=["master-worktree-elsewhere", "integration-worktree-on-master"],
)
def test_dispatch_opens_no_terminal_when_the_worktree_is_not_at_the_base(
    dispatch: Harness, base: str | None, worktree_head: str, named: str
) -> None:
    """The HEAD check compares with the --base tip, not always origin/master (#332)."""
    dispatch.write(
        "refs.txt", f"origin/master {SHA}\norigin/{INTEGRATION} {INTEGRATION_SHA}\n"
    )
    # Orca started the worktree somewhere other than the base asked for.
    dispatch.write("worktree_head.txt", worktree_head + "\n")
    result = _dispatch_from(dispatch, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"HEAD 不是最新 {named}" in result.stderr
    line = _json_line(result)
    assert line["sent"] is False and line["head"] == worktree_head
    assert not [c for c in dispatch.calls("orca") if c.startswith("terminal")]
    assert not [c for c in dispatch.calls("gh") if "updateProjectV2" in c]


@pytest.mark.parametrize(
    "base",
    [
        INTEGRATION,
        "origin/",
        "origin/-x",
        "origin//x",
        "origin/x/",
        "origin/a..b",
        "origin/a b",
        "origin/a;b",
    ],
)
def test_dispatch_refuses_a_base_that_is_not_origin_branch(
    dispatch: Harness, base: str
) -> None:
    result = _dispatch_from(dispatch, base)
    assert result.returncode == 64, result.stdout + result.stderr
    assert "--base" in result.stderr
    assert not dispatch.calls("git") and not dispatch.calls("orca")


# --- close_task.sh -----------------------------------------------------------------


@pytest.fixture
def close(h: Harness):
    h.integration_branches(INTEGRATION)
    wt = h.root / "wt" / "task-282-dryrun"
    wt.mkdir(parents=True)
    (wt / "file.txt").write_text("x", encoding="utf-8")
    h.wt = wt
    h.answer(
        "orca_worktree_list",
        _ok(
            {
                "worktrees": [
                    {
                        "path": wt.as_posix(),
                        "branch": "refs/heads/task/282-dryrun",
                        "id": f"{REPO_ID}::{wt.as_posix()}",
                    },
                    {
                        "path": (h.root / "wt" / "task-2820-other").as_posix(),
                        "branch": "refs/heads/task/2820-other",
                        "id": "other",
                    },
                ]
            }
        ),
    )
    h.answer(
        "orca_terminal_list",
        _ok(
            {
                "terminals": [
                    {
                        "handle": "term_agent",
                        "worktreePath": str(wt),
                        "agentIdentity": "claude",
                        "lastOutputAt": 1,
                    },
                    {
                        "handle": "term_shell",
                        "worktreePath": wt.as_posix(),
                        "lastOutputAt": 1,
                    },
                    {
                        "handle": "term_elsewhere",
                        "worktreePath": "C:/x",
                        "lastOutputAt": 1,
                    },
                ]
            }
        ),
    )
    h.answer("orca_terminal_wait", _ok({"wait": {"satisfied": True}}))
    h.write("branches.txt", "master\ntask/282-dryrun\n")
    # Another task's worktree: --extra-dir must never reach it. (The task's own worktree
    # goes through orca worktree rm.)
    other = h.root / "wt" / "task-253-other"
    other.mkdir(parents=True)
    (other / "keep.txt").write_text("k", encoding="utf-8")
    h.other = other
    h.write(
        "git_worktrees.txt",
        f"worktree {h.repo.as_posix()}\nHEAD {SHA}\n\n"
        f"worktree {other.as_posix()}\nHEAD {SHA}\nbranch refs/heads/task/253-other\n\n"
        f"worktree {wt.as_posix()}\nHEAD {SHA}\nbranch refs/heads/task/282-dryrun\n\n",
    )
    h.answer(
        "gh_pr_list",
        [
            {
                "number": 290,
                "state": "MERGED",
                "mergeCommit": {"oid": MERGE_SHA},
                "headRefName": "task/282-dryrun",
                "baseRefName": "master",
            }
        ],
    )
    h.answer(
        "gh_run_list",
        [
            {"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"},
            {"headSha": "c" * 40, "status": "completed", "conclusion": "failure"},
        ],
    )
    extra = h.root / "t282"
    (extra / "deps").mkdir(parents=True)
    (extra / "deps" / "a.txt").write_text("a", encoding="utf-8")
    target = h.root / "shared-node-modules"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    _link(target, extra / "deps" / "node_modules")
    h.extra, h.target = extra, target
    yield h
    link = extra / "deps" / "node_modules"
    if link.is_symlink():
        link.unlink()
    elif link.is_junction():
        os.rmdir(link)


def _link(target: Path, link: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


DELETING = ("terminal close", "worktree rm")


def _assert_nothing_deleted(h: Harness) -> None:
    assert not [c for c in h.calls("orca") if c.startswith(DELETING)]
    assert not [c for c in h.calls("git") if " branch -D " in f" {c} " or "prune" in c]
    assert not [c for c in h.calls("gh") if "updateProjectV2" in c]
    assert not _issue_closes(h)
    assert not h.calls("docker")
    assert h.wt.is_dir() and (h.extra / "deps" / "a.txt").is_file()
    assert "task/282-dryrun" in h.branches()
    assert (h.target / "keep.txt").is_file()


def test_close_task_removes_everything_and_unlinks_junctions_first(
    close: Harness,
) -> None:
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["pr"] == 290 and line["merge_commit"] == MERGE_SHA
    assert line["board"] == "完成"
    orca = close.calls("orca")
    closed = [c for c in orca if c.startswith("terminal close")]
    assert [c.split()[3] for c in closed] == ["term_agent", "term_shell"]
    rm = next(i for i, c in enumerate(orca) if c.startswith("worktree rm"))
    assert all(orca.index(c) < rm for c in closed)
    assert f"--worktree {REPO_ID}::{close.wt.as_posix()} --force" in orca[rm]
    assert not close.wt.exists() and not close.extra.exists()
    assert "task/282-dryrun" not in close.branches()
    # The junction (symlink on Linux) was unlinked on its own before the tree went, and
    # what it pointed to is untouched.
    steps = line["steps"]
    unlinked = [i for i, s in enumerate(steps) if s.endswith("/deps/node_modules")]
    assert len(unlinked) == 1 and steps[unlinked[0]].startswith("unlinked:")
    assert unlinked[0] < steps.index(f"extra_removed:{close.extra.as_posix()}")
    assert (close.target / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert any("worktree prune" in c for c in close.calls("git"))
    assert any("updateProjectV2" in c and "o=OPT-DONE" in c for c in close.calls("gh"))


def test_close_task_needs_slug_when_the_issue_has_two_worktrees(close: Harness) -> None:
    second = close.root / "wt" / "task-282-coordinator-scripts"
    second.mkdir(parents=True)
    listing = json.loads((close.fake / "orca_worktree_list.json").read_text("utf-8"))
    listing["result"]["worktrees"].append(
        {
            "path": second.as_posix(),
            "branch": "refs/heads/task/282-coordinator-scripts",
            "id": f"{REPO_ID}::{second.as_posix()}",
        }
    )
    close.answer("orca_worktree_list", listing)
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "--slug" in result.stderr
    _assert_nothing_deleted(close)

    args = ("--slug", "dryrun", "--no-board", "--extra-dir", close.extra.as_posix())
    result = close.run("close_task.sh", "282", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _json_line(result)["board"] == "skipped"
    assert not close.wt.exists() and second.is_dir()
    assert not [c for c in close.calls("gh") if "updateProjectV2" in c]


@pytest.mark.parametrize(
    "pr_list",
    [
        [],
        [{"number": 290, "state": "OPEN", "mergeCommit": None, "headRefName": "x"}],
        [{"number": 290, "state": "CLOSED", "mergeCommit": None, "headRefName": "x"}],
        # A merge commit alone is not proof: only state MERGED is.
        [
            {
                "number": 290,
                "state": "OPEN",
                "mergeCommit": {"oid": MERGE_SHA},
                "headRefName": "x",
            }
        ],
    ],
    ids=["no-pr", "open", "closed-unmerged", "open-with-merge-commit"],
)
def test_close_task_deletes_nothing_when_the_pr_is_not_merged(
    close: Harness, pr_list: list
) -> None:
    close.answer("gh_pr_list", pr_list)
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "未刪除任何東西" in result.stderr
    _assert_nothing_deleted(close)


@pytest.mark.parametrize(
    "runs",
    [
        [],
        [{"headSha": MERGE_SHA, "status": "in_progress", "conclusion": ""}],
        [{"headSha": MERGE_SHA, "status": "completed", "conclusion": "failure"}],
        [
            {"headSha": "c" * 40, "status": "completed", "conclusion": "failure"},
            {"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"},
        ],
    ],
    ids=["no-run", "pending", "failure", "newer-master-run-red"],
)
def test_close_task_deletes_nothing_when_master_ci_is_not_green(
    close: Harness, runs: list
) -> None:
    close.answer("gh_run_list", runs)
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_nothing_deleted(close)


def _merged_into(h: Harness, base: str, state: str = "MERGED") -> None:
    h.answer(
        "gh_pr_list",
        [
            {
                "number": 290,
                "state": state,
                "mergeCommit": {"oid": MERGE_SHA},
                "headRefName": "task/282-dryrun",
                "baseRefName": base,
            }
        ],
    )


def _issue_closes(h: Harness) -> list[str]:
    return [c for c in h.calls("gh") if c.startswith("issue close")]


def _integration_green(h: Harness) -> None:
    """A PR into INTEGRATION whose merge commit's CI on INTEGRATION is green."""
    _merged_into(h, INTEGRATION)
    h.answer(
        INTEGRATION_RUNS,
        [{"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"}],
    )


def _run_branches(h: Harness) -> list[str]:
    """The --branch of every gh run list call."""
    return [
        c.split("--branch ", 1)[1].split()[0]
        for c in h.calls("gh")
        if c.startswith("run list")
    ]


def test_close_task_checks_ci_on_the_branch_the_pr_merged_into(close: Harness) -> None:
    """AC-2 (#332): a PR into an integration branch is judged by its CI and history."""
    _merged_into(close, INTEGRATION)
    # master has no run of the merge commit and its newest run is red: only INTEGRATION's
    # runs may decide.
    close.answer(
        "gh_run_list",
        [{"headSha": "c" * 40, "status": "completed", "conclusion": "failure"}],
    )
    close.answer(
        INTEGRATION_RUNS,
        [{"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"}],
    )
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["base"] == INTEGRATION and line["merge_commit"] == MERGE_SHA
    assert _run_branches(close) == [INTEGRATION]
    git = _git_subcommands(close)
    assert f"fetch --quiet origin {INTEGRATION}" in git
    assert (
        f"merge-base --is-ancestor refs/heads/task/282-dryrun origin/{INTEGRATION}"
        in git
    )
    assert not [
        c for c in git if c.startswith(("fetch", "merge-base")) and "master" in c
    ]
    assert not close.wt.exists() and not close.extra.exists()
    # AC-5: GitHub does not act on Closes #282 in a PR into a branch other than master.
    assert line["issue_close"] == "closed"
    assert _issue_closes(close) == [
        "issue close 282 --repo YiCheng0608/stock-lab --comment PR #290 已合併進 "
        f"{INTEGRATION}，merge commit bbbbbbbbb 的 CI 綠（close_task.sh）"
    ]


def test_close_task_checks_master_ci_for_a_pr_into_master(close: Harness) -> None:
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["base"] == "master" and line["issue_close"] == "not_needed"
    assert _run_branches(close) == ["master"]
    git = _git_subcommands(close)
    assert "fetch --quiet origin master" in git
    assert "merge-base --is-ancestor refs/heads/task/282-dryrun origin/master" in git
    # AC-5: merging into master closed the Issue already.
    assert not _issue_closes(close)


@pytest.mark.parametrize(
    "why", ["dirty-worktree", "busy-terminal", "protected-extra-dir"]
)
def test_close_task_leaves_the_issue_open_when_a_later_check_fails(
    close: Harness, why: str
) -> None:
    """AC-5 (#332): the integration branch's CI is green, yet a later check refuses."""
    _integration_green(close)
    dirs = [close.extra]
    if why == "dirty-worktree":
        close.write("git_status.txt", " M file.txt\n")
    elif why == "busy-terminal":
        close.answer("orca_terminal_wait", _ok({"wait": {"satisfied": False}}))
    else:
        dirs = [close.data]
    result = close.close_task(*dirs)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _json_line(result)["issue_close"] == ""
    _assert_nothing_deleted(close)


def test_close_task_deletes_nothing_when_the_issue_cannot_be_closed(
    close: Harness,
) -> None:
    _integration_green(close)
    close.write("gh_issue_close_fails", "")
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "gh issue close #282 失敗" in result.stderr
    assert "未刪除任何東西" in result.stderr
    assert _json_line(result)["issue_close"] == "failed"
    assert not [c for c in close.calls("orca") if c.startswith(DELETING)]
    assert close.wt.is_dir() and "task/282-dryrun" in close.branches()


def test_close_task_rerun_goes_on_when_the_issue_is_already_closed(
    close: Harness,
) -> None:
    """#332 review 3: a rerun after a failed delete step finds the Issue closed."""
    _integration_green(close)
    close.answer("gh_issue_view", {"state": "CLOSED"})
    # Were the close tried, it would fail: it must not be.
    close.write("gh_issue_close_fails", "")
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["issue_close"] == "already_closed" and line["board"] == "完成"
    assert not _issue_closes(close)
    assert not close.wt.exists() and not close.extra.exists()
    assert "task/282-dryrun" not in close.branches()


def test_close_task_takes_a_failed_close_of_an_issue_now_closed_as_closed(
    close: Harness,
) -> None:
    """The close errs, yet the Issue reads back closed: cleanup goes on."""
    _integration_green(close)
    close.answer("gh_issue_view", {"state": "OPEN"})
    close.write("gh_issue_close_fails", "")
    close.write("gh_issue_close_sets_closed", "")
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _json_line(result)["issue_close"] == "closed"
    assert len(_issue_closes(close)) == 1
    assert not close.wt.exists() and not close.extra.exists()


@pytest.mark.parametrize("base", ["release/v1", "task/999-other", "feat/other"])
def test_close_task_refuses_a_pr_into_a_branch_that_is_not_long_lived(
    close: Harness, base: str
) -> None:
    """#332 review 2: only master and the integration branches are cleanup targets."""
    _merged_into(close, base)
    close.answer(
        f"gh_run_list_{base.replace('/', '_')}",
        [{"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"}],
    )
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        f"目標分支 {base} 不是 master 或長期整合分支（{INTEGRATION}）" in result.stderr
    )
    assert not _run_branches(close)
    _assert_nothing_deleted(close)


def test_close_task_refuses_a_pr_into_feat_docker_now_that_it_reached_master(
    close: Harness,
) -> None:
    """AC-1 (#428): feat/docker reached master (PR #420) and is no longer an integration
    branch: the repository's own close_task.sh refuses a PR into it, deleting nothing.

    It reads the repository's list on purpose (#448): the line below copies the real
    script over the sandbox one, whose list the other tests rewrite to INTEGRATION. So
    the test fails if feat/docker, or any branch listed in the repository, is back in
    ``integration_branches``; it is not a test of the sandbox list.
    """
    shutil.copyfile(OPS / "close_task.sh", close.ops / "close_task.sh")
    _merged_into(close, "feat/docker")
    close.answer(
        "gh_run_list_feat_docker",
        [{"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"}],
    )
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "目標分支 feat/docker 不是 master 或長期整合分支" in result.stderr
    assert not _run_branches(close)
    _assert_nothing_deleted(close)


@pytest.mark.parametrize("base", ["master", INTEGRATION])
def test_close_task_without_integration_branches_takes_only_master(
    close: Harness, base: str
) -> None:
    """#428: an empty integration_branches=() is valid; a PR into master is closed as
    before, a PR into any other branch is refused and the message says there is none."""
    close.integration_branches()
    if base != "master":
        _integration_green(close)
    result = close.close_task(close.extra)
    if base == "master":
        assert result.returncode == 0, result.stdout + result.stderr
        line = _json_line(result)
        assert line["base"] == "master" and line["issue_close"] == "not_needed"
        assert _docker_steps(line) == [
            "docker_none",
            "docker_prune_skipped:no_task_resources",
        ]
        assert not close.wt.exists() and not close.extra.exists()
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert (
            f"目標分支 {INTEGRATION} 不是 master 或長期整合分支（目前沒有）"
            in result.stderr
        )
        assert not _run_branches(close)
        _assert_nothing_deleted(close)


def test_close_task_no_board_leaves_the_issue_open(close: Harness) -> None:
    _integration_green(close)
    result = close.run(
        "close_task.sh", "282", "--no-board", "--extra-dir", close.extra.as_posix()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _json_line(result)["issue_close"] == "skipped"
    assert not _issue_closes(close)


@pytest.mark.parametrize(
    "state, runs, error",
    [
        ("OPEN", None, "PR 尚未合併"),
        ("MERGED", [], f"{INTEGRATION} 上 merge commit bbbbbbbbb 的 CI 是 missing"),
        (
            "MERGED",
            [{"headSha": MERGE_SHA, "status": "in_progress", "conclusion": ""}],
            f"{INTEGRATION} 上 merge commit bbbbbbbbb 的 CI 是 pending",
        ),
        (
            "MERGED",
            [{"headSha": MERGE_SHA, "status": "completed", "conclusion": "failure"}],
            f"{INTEGRATION} 上 merge commit bbbbbbbbb 的 CI 是 failure",
        ),
        (
            "MERGED",
            [
                {"headSha": "c" * 40, "status": "completed", "conclusion": "failure"},
                {"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"},
            ],
            f"{INTEGRATION} 最新一次 CI 是 failure",
        ),
    ],
    ids=["not-merged", "no-run", "pending", "failure", "newer-run-red"],
)
def test_close_task_deletes_nothing_when_a_pr_into_an_integration_branch_is_not_done(
    close: Harness, state: str, runs: list | None, error: str
) -> None:
    """AC-2 (#332): master's CI is green for the merge commit, INTEGRATION's is not."""
    _merged_into(close, INTEGRATION, state)
    if runs is not None:
        close.answer(INTEGRATION_RUNS, runs)
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert error in result.stderr and "未刪除任何東西" in result.stderr
    assert _run_branches(close) == ([] if state == "OPEN" else [INTEGRATION])
    _assert_nothing_deleted(close)


def test_close_task_deletes_nothing_when_the_branch_is_not_in_the_integration_branch(
    close: Harness,
) -> None:
    _merged_into(close, INTEGRATION)
    close.answer(
        INTEGRATION_RUNS,
        [{"headSha": MERGE_SHA, "status": "completed", "conclusion": "success"}],
    )
    close.write("git_ancestor_exit", "1")
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"不在 origin/{INTEGRATION} 的 commit" in result.stderr
    _assert_nothing_deleted(close)


@pytest.mark.parametrize("base", [None, "", "-x", "a..b", "a b"])
def test_close_task_deletes_nothing_without_a_readable_target_branch(
    close: Harness, base: str | None
) -> None:
    pr = {
        "number": 290,
        "state": "MERGED",
        "mergeCommit": {"oid": MERGE_SHA},
        "headRefName": "task/282-dryrun",
    }
    if base is not None:
        pr["baseRefName"] = base
    close.answer("gh_pr_list", [pr])
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "目標分支" in result.stderr
    assert not _run_branches(close)
    _assert_nothing_deleted(close)


@pytest.mark.parametrize(
    "which",
    [
        "data-dir",
        "data-subdir",
        "named-stock-lab-data",
        "repo-root",
        "inside-repo",
        "other-worktree",
        "home",
    ],
)
def test_close_task_refuses_an_extra_dir_it_must_not_delete(
    close: Harness, which: str
) -> None:
    (close.data / "logs" / "keep.log").write_text("k", encoding="utf-8")
    named = close.root / "elsewhere" / "stock-lab-data" / "x"
    named.mkdir(parents=True)
    (close.repo / "keep.txt").write_text("k", encoding="utf-8")
    (close.home / "keep.txt").write_text("k", encoding="utf-8")
    path = {
        "data-dir": close.data,
        "data-subdir": close.data / "logs",
        "named-stock-lab-data": named,
        "repo-root": close.repo,
        "inside-repo": close.ops,
        "other-worktree": close.other,
        "home": close.home,
    }[which]
    result = close.close_task(close.extra, path)
    # The protected stand-ins first: with the first refusal removed, remove_tree's own
    # guard_dir must still keep them (the run then fails later with exit 3).
    assert (close.data / "logs" / "keep.log").is_file() and named.is_dir()
    assert (close.repo / "keep.txt").is_file() and (
        close.ops / "close_task.sh"
    ).is_file()
    assert (close.home / "keep.txt").is_file() and path.is_dir()
    assert (close.other / "keep.txt").is_file()
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_nothing_deleted(close)


def _guard(h: Harness, path: str, *mode: str) -> str:
    """guard_dir from the sandbox's coordinator_lib.sh: it only prints, never deletes."""
    result = h.run_bash(
        'script_dir="$1"; shift; . "$script_dir/coordinator_lib.sh"; guard_dir "$@"',
        h.ops.as_posix(),
        path,
        *mode,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_guard_dir_names_every_protected_path(h: Harness) -> None:
    other = h.root / "wt" / "task-253-other"
    closing = h.root / "wt" / "task-282-dryrun"
    for directory in (other, closing):
        directory.mkdir(parents=True)
        (directory / ".git").write_text("gitdir: x\n", encoding="utf-8")
    h.write(
        "git_worktrees.txt",
        f"worktree {h.repo.as_posix()}\n\nworktree {other.as_posix()}\n\n"
        f"worktree {closing.as_posix()}\n\n",
    )
    (h.home / "stock-lab-data" / "raw").mkdir(parents=True)
    protected = {
        "repo root": h.repo,
        "inside the repo": h.ops,
        "another worktree": other,
        "inside another worktree": other / "backend",
        "the worktree being closed": closing,
        "$HOME": h.home,
        "a parent of $HOME": h.root,
        "$STOCK_DATA_DIR": h.data,
        "under $STOCK_DATA_DIR": h.data / "logs",
        "$HOME/stock-lab-data": h.home / "stock-lab-data",
        "under a stock-lab-data": h.home / "stock-lab-data" / "raw",
        "a stock-lab-data elsewhere": h.root / "x" / "stock-lab-data",
    }
    for name, path in protected.items():
        assert path.resolve().is_relative_to(h.root.resolve()), name
        assert _guard(h, path.as_posix()), name
    # Roots cannot be sandbox stand-ins; guard_dir only reads them.
    assert _guard(h, "/")
    if os.name == "nt":
        assert _guard(h, "C:/") and _guard(h, "C:\\")
    allowed = h.root / "t282"
    allowed.mkdir()
    assert _guard(h, allowed.as_posix()) == ""
    # A worktree directory git no longer lists keeps its .git file until removed.
    gone = h.root / "wt" / "task-282-gone"
    gone.mkdir(parents=True)
    (gone / ".git").write_text("gitdir: x\n", encoding="utf-8")
    assert _guard(h, gone.as_posix())
    assert _guard(h, gone.as_posix(), "residual") == ""


# Run by _inner_pytest beside a copy of backend/tests/conftest.py: repositories in
# tmp_path as this file's Harness, test_worker_job and test_verify_tools build
# them (an empty .git directory, a .git file, a read-only git object file), one in a
# test that then skips; with INNER_KILL=1 a test exits the process before pytest's
# teardown, as a killed run does; with INNER_HOLD=<file> another keeps its repository
# until that file exists (#422).
INNER_TESTS = r"""
import os
import stat
import time

import pytest


def test_builds_repositories(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / ".git").write_text("gitdir: x\n")
    obj = tmp_path / "work" / ".git" / "objects" / "ab" / "cdef"
    obj.parent.mkdir(parents=True)
    obj.write_text("x")
    os.chmod(obj, stat.S_IREAD)
    (tmp_path / "work" / "debug.txt").write_text("kept")
    assert os.environ["INNER_FAIL"] == "0"


def test_skips_after_building_one(tmp_path):
    (tmp_path / "project" / ".git").mkdir(parents=True)
    pytest.skip("skipped with a .git in its tmp_path")


def test_killed_after_building_one(tmp_path):
    if os.environ["INNER_KILL"] != "1":
        pytest.skip("not killed")
    (tmp_path / "project" / ".git").mkdir(parents=True)
    os._exit(3)


def test_holds_one_until_released(tmp_path):
    hold = os.environ["INNER_HOLD"]
    if not hold:
        pytest.skip("not held")
    (tmp_path / "project" / ".git").mkdir(parents=True)
    open(hold + ".ready", "w").close()
    deadline = time.monotonic() + 100
    while not os.path.exists(hold) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert os.path.exists(hold)
"""


def _inner_run(
    h: Harness,
    fail: bool,
    basetemp: str = "b",
    kill: bool = False,
    hold: Path | None = None,
) -> tuple[Path, list[str], dict[str, str]]:
    """The command and environment of a pytest run with --basetemp in an engineer's temp
    directory outside the worktree, as #272 and #270 had it (C:/v270/pt/b): returns that
    directory too. Runs with another BASETEMP name go to the same directory, as #279's
    t279/b1, bf did. Every run records itself in <sandbox>/runs, never in the real
    home (#422)."""
    inner = h.root / "inner"
    inner.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("conftest.py"), inner / "conftest.py")
    (inner / "test_inner.py").write_text(INNER_TESTS, encoding="utf-8")
    temp = h.root / "t290"
    (temp / "tmp").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("STOCK_")}
    env.update(
        TMPDIR=str(temp / "tmp"),
        TEMP=str(temp / "tmp"),
        TMP=str(temp / "tmp"),
        PYTEST_RUNS_DIR=str(h.root / "runs"),
        # An OS error text in a warning is in the console's code page otherwise.
        PYTHONIOENCODING="utf-8",
        INNER_FAIL="1" if fail else "0",
        INNER_KILL="1" if kill else "0",
        INNER_HOLD=str(hold) if hold else "",
    )
    command = [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q"]
    command += ["--rootdir", str(inner), "--confcutdir", str(inner)]
    command += ["--basetemp", str(temp / basetemp), str(inner)]
    if hold:
        command += ["-k", "holds_one"]
    return temp, command, env


def _inner_pytest(
    h: Harness, fail: bool, basetemp: str = "b", kill: bool = False
) -> tuple[Path, subprocess.CompletedProcess]:
    temp, command, env = _inner_run(h, fail, basetemp, kill)
    # cwd backend: the copied conftest imports app and worker, as under CI.
    result = subprocess.run(
        command,
        cwd=ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return temp, result


def test_a_green_pytest_run_leaves_no_repository_in_its_basetemp(h: Harness) -> None:
    """#290: the repositories tests build in tmp_path made close_task.sh refuse an
    engineer's temp directory holding the --basetemp. conftest.py removes the basetemp
    of a green run, so the directory passes guard_dir as it is."""
    temp, result = _inner_pytest(h, fail=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 3 skipped" in result.stdout
    assert not (temp / "b").exists(), _repositories(temp)
    assert _guard(h, temp.as_posix()) == ""


def _repositories(top: Path) -> list[str]:
    return sorted(p.relative_to(top).as_posix() for p in top.rglob(".git"))


def test_a_failed_run_then_a_green_run_on_another_basetemp_leave_no_repository(
    h: Harness,
) -> None:
    """#304: a failed run kept its basetemp with the repositories in it, and the green
    run that followed took another basetemp and never cleared it (#278's s/b, #279's
    t279/bf). The failed run keeps its debug files but no .git, so the directory
    passes guard_dir as it is."""
    temp, failed = _inner_pytest(h, fail=True, basetemp="b1")
    assert failed.returncode == 1, failed.stdout + failed.stderr
    temp, green = _inner_pytest(h, fail=False, basetemp="b2")
    assert green.returncode == 0, green.stdout + green.stderr
    assert _repositories(temp) == []
    assert not (temp / "b2").exists()
    [debug] = (temp / "b1").rglob("debug.txt")
    assert debug.read_text(encoding="utf-8") == "kept"
    assert (debug.parent.parent / "repo").is_dir()
    assert _guard(h, temp.as_posix()) == ""


def test_a_killed_pytest_run_leaves_only_the_repository_of_the_test_it_was_in(
    h: Harness,
) -> None:
    """#304: a run killed before pytest_sessionfinish (a command timeout) has deleted the
    repositories of every test that finished; that of the test it was in stays, and
    guard_dir is not loosened for a basetemp: it refuses the directory and names it."""
    temp, result = _inner_pytest(h, fail=True, kill=True)
    assert result.returncode == 3, result.stdout + result.stderr
    [left] = _repositories(temp)
    assert left.startswith("b/test_killed_after_building_on"), left
    reason = _guard(h, temp.as_posix())
    assert reason.startswith("裡面有 .git（") and "test_killed" in reason, reason


def test_the_next_run_removes_the_repository_of_a_run_that_was_killed(
    h: Harness,
) -> None:
    """#422: a killed run keeps the repository of the test it was in, and the next run on
    another basetemp never visited it (#386, #394, #392: t<issue>/ was refused by
    close_task.sh each time). Every run now removes what the dead ones left when it
    starts, the other files of their basetemp stay for debugging."""
    temp, killed = _inner_pytest(h, fail=True, basetemp="full2", kill=True)
    assert killed.returncode == 3, killed.stdout + killed.stderr
    [left] = _repositories(temp)
    assert left.startswith("full2/test_killed_after_building_on"), left
    temp, green = _inner_pytest(h, fail=False, basetemp="full3")
    assert green.returncode == 0, green.stdout + green.stderr
    assert _repositories(temp) == []
    assert "removed 1 .git left in" in green.stderr, green.stderr
    assert (temp / "full2").is_dir() and not (temp / "full3").exists()
    assert not list((h.root / "runs").iterdir())
    assert _guard(h, temp.as_posix()) == ""


# What #386, #394 and #392 each found in t<issue>/ (#422): the basetemp of a run that was
# killed and the directory of the test it was in, with an empty repository.
KILLED_RUNS = (
    ("t386", "tmp/full2", "test_close_task_deletes_nothin0"),
    ("t394", "pf", "test_close_task_refuses_an_ext4"),
    ("t392", "tmp/full3", "test_close_task_takes_a_failed0"),
)


def test_the_next_run_removes_the_repositories_left_in_the_three_task_directories(
    h: Harness,
) -> None:
    """#422: the leftovers of t386, t394 and t392 as the sessions recorded them (a record
    in the runs directory, a marker nobody holds any more): one later run in a fourth
    directory removes all three, and every task directory passes guard_dir as it is."""
    runs = h.root / "runs"
    runs.mkdir()
    for number, (issue, basetemp, test_dir) in enumerate(KILLED_RUNS):
        top = h.root / issue / basetemp
        (top / test_dir / "repo" / ".git").mkdir(parents=True)
        (top / test_dir / "repo" / "debug.txt").write_text("kept", encoding="utf-8")
        token = f"{number:032x}"
        (top / f".pytest-run-{token}").write_text("", encoding="utf-8")
        (runs / f"{token}.json").write_text(
            json.dumps({"basetemp": str(top)}), encoding="utf-8"
        )
        assert _guard(h, (h.root / issue).as_posix()).startswith("裡面有 .git（")
    temp, green = _inner_pytest(h, fail=False, basetemp="b1")
    assert green.returncode == 0, green.stdout + green.stderr
    for issue, basetemp, test_dir in KILLED_RUNS:
        top = h.root / issue
        assert _repositories(top) == [], issue
        assert _guard(h, top.as_posix()) == "", issue
        assert (top / basetemp / test_dir / "repo" / "debug.txt").read_text(
            encoding="utf-8"
        ) == "kept"
    assert not list(runs.iterdir())


def test_a_run_that_is_still_going_keeps_its_repository_when_another_run_starts(
    h: Harness,
) -> None:
    """#422: the lock on the marker tells a run that died from one that is only slow. A
    second run starting while the first is in a test must leave its repository alone, and
    both clear their records when they end."""
    release = h.root / "release"
    temp, command, env = _inner_run(h, fail=False, basetemp="going", hold=release)
    going = subprocess.Popen(
        command,
        cwd=ROOT / "backend",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        ready = Path(f"{release}.ready")
        deadline = time.monotonic() + 100
        while not ready.exists() and going.poll() is None:
            assert time.monotonic() < deadline, "the first run never reached its test"
            time.sleep(0.1)
        assert ready.exists(), going.communicate()
        temp, other = _inner_pytest(h, fail=False, basetemp="other")
        assert other.returncode == 0, other.stdout + other.stderr
        assert "removed" not in other.stderr, other.stderr
        [kept] = _repositories(temp)
        assert kept.startswith("going/test_holds_one_until_releas"), kept
        assert len(list((h.root / "runs").glob("*.json"))) == 1
    finally:
        release.write_text("go", encoding="utf-8")
        try:
            out, err = going.communicate(timeout=100)
        except subprocess.TimeoutExpired:
            going.kill()
            out, err = going.communicate()
    assert going.returncode == 0, out + err
    assert _repositories(temp) == [] and not (temp / "going").exists()
    assert not list((h.root / "runs").iterdir())


def test_a_record_whose_basetemp_was_emptied_is_dropped_without_touching_it(
    h: Harness,
) -> None:
    """#422: nothing but the marker says a directory is still the basetemp of the
    session that was recorded. A directory that lost it (pytest emptied the basetemp for
    a new run, someone reused the path) keeps its repository; the record goes."""
    runs = h.root / "runs"
    runs.mkdir()
    reused = h.root / "t11" / "b"
    (reused / "work" / ".git").mkdir(parents=True)
    record = runs / f"{'a' * 32}.json"
    record.write_text(json.dumps({"basetemp": str(reused)}), encoding="utf-8")
    _, green = _inner_pytest(h, fail=False)
    assert green.returncode == 0, green.stdout + green.stderr
    assert (reused / "work" / ".git").is_dir()
    assert not record.exists()


def test_a_record_that_cannot_be_kept_does_not_change_the_result_of_the_run(
    h: Harness,
) -> None:
    """#422: the record is a convenience for the next run. With no directory to keep it
    in, the run only warns and ends as it would have, its own basetemp cleared."""
    (h.root / "runs").write_text(
        "a file where the directory should be", encoding="utf-8"
    )
    temp, green = _inner_pytest(h, fail=False)
    assert green.returncode == 0, green.stdout + green.stderr
    assert "this pytest run is not recorded" in green.stderr, green.stderr
    assert not (temp / "b").exists()


def test_a_failed_session_keeps_its_basetemp_without_a_repository(
    request, tmp_path: Path, capsys
) -> None:
    """#304: what no test's teardown reached (a module or session fixture's
    tmp_path_factory directory) loses its .git when the session ends unsuccessful;
    the rest of the basetemp stays for debugging."""
    basetemp = tmp_path / "basetemp"
    (basetemp / "fixture0" / "repo" / ".git").mkdir(parents=True)
    (basetemp / "fixture0" / "debug.txt").write_text("kept", encoding="utf-8")
    factory = SimpleNamespace(_basetemp=basetemp)
    session = SimpleNamespace(config=SimpleNamespace(_tmp_path_factory=factory))
    _conftest(request).pytest_sessionfinish(session, 1)
    assert _repositories(basetemp) == []
    assert (basetemp / "fixture0" / "repo").is_dir()
    assert (basetemp / "fixture0" / "debug.txt").read_text(encoding="utf-8") == "kept"
    assert "without its 1 .git (#304)" in capsys.readouterr().err


def test_dropping_repositories_does_not_follow_a_link(request, tmp_path: Path) -> None:
    """#304: the .git removal of a failed run does not enter a junction or symlink and
    deletes a .git that is a link as the link itself: what lies outside the basetemp
    stays as it was. Stand-ins under tmp_path only (#282)."""
    outside = tmp_path / "outside"
    (outside / ".git").mkdir(parents=True)
    (outside / "file.txt").write_text("k", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("k", encoding="utf-8")
    basetemp = tmp_path / "basetemp"
    (basetemp / "a" / ".git" / "objects").mkdir(parents=True)
    obj = basetemp / "a" / ".git" / "objects" / "cdef"
    obj.write_text("x", encoding="utf-8")
    obj.chmod(stat.S_IREAD)
    (basetemp / "b").mkdir()
    (basetemp / "b" / ".git").write_text("gitdir: x\n", encoding="utf-8")
    (basetemp / "c").mkdir()
    _link(outside, basetemp / "c" / "link")
    (basetemp / "d").mkdir()
    _link(target, basetemp / "d" / ".git")
    (basetemp / "a" / "debug.txt").write_text("kept", encoding="utf-8")

    failures: list = []
    assert _conftest(request)._drop_repositories(basetemp, failures) == 3
    assert failures == []
    # Path.rglob enters a junction, so the deleted paths are named one by one.
    for gone in ("a", "b", "d"):
        assert not os.path.lexists(basetemp / gone / ".git"), gone
    assert (basetemp / "a" / "debug.txt").read_text(encoding="utf-8") == "kept"
    assert (outside / ".git").is_dir() and (outside / "file.txt").is_file()
    assert (target / "file.txt").read_text(encoding="utf-8") == "k"
    link = basetemp / "c" / "link"
    assert (link / ".git").is_dir()
    if link.is_junction():
        os.rmdir(link)
    else:
        link.unlink()


def _conftest(request):
    """backend/tests/conftest.py as pytest loaded it for this run."""
    here = Path(__file__).with_name("conftest.py").resolve()
    return next(
        plugin
        for plugin in request.config.pluginmanager.get_plugins()
        if getattr(plugin, "__file__", None) and Path(plugin.__file__).resolve() == here
    )


def test_basetemp_cleanup_does_not_chmod_a_link(
    request, tmp_path: Path, monkeypatch
) -> None:
    """#290 review L2: the retry after a failed delete makes the path writable, but never
    through a link (a junction on Windows, a symlink elsewhere): chmod would reach its
    target outside the basetemp."""
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "basetemp" / "link"
    link.parent.mkdir()
    _link(target, link)
    chmods: list[str] = []
    monkeypatch.setattr(os, "chmod", lambda path, *a, **k: chmods.append(str(path)))

    def delete_fails(path):
        raise PermissionError(path)

    failures: list = []
    _conftest(request)._retry_writable(delete_fails, str(link), failures)
    assert chmods == [] and [str(p) for p, _ in failures] == [str(link)]
    monkeypatch.undo()
    if link.is_junction():
        os.rmdir(link)
    else:
        link.unlink()
    assert target.is_dir()


@pytest.mark.skipif(
    os.name == "nt",
    reason="os.chmod follows a symlink on POSIX; Windows' Python 3.12 does not, and an "
    "unprivileged Windows user cannot make the read-only directory below",
)
def test_a_green_run_leaves_a_symlink_target_outside_the_basetemp_as_it_was(
    request, tmp_path: Path
) -> None:
    """#290 review L2 on a real tree: the symlink in a directory rmtree cannot write to
    fails to unlink and goes to the retry, which must not chmod its target."""
    target = tmp_path / "outside.txt"
    target.write_text("k", encoding="utf-8")
    target.chmod(0o644)
    sub = tmp_path / "basetemp" / "sub"
    sub.mkdir(parents=True)
    (sub / "link").symlink_to(target)
    sub.chmod(0o500)
    factory = SimpleNamespace(_basetemp=sub.parent)
    session = SimpleNamespace(config=SimpleNamespace(_tmp_path_factory=factory))
    try:
        _conftest(request).pytest_sessionfinish(session, 0)
    finally:
        sub.chmod(0o700)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert target.read_text(encoding="utf-8") == "k"


@pytest.mark.parametrize(
    "state", ["dirty", "unmerged-commit", "busy-agent", "own-terminal"]
)
def test_close_task_deletes_nothing_when_the_worktree_is_in_use(
    close: Harness, state: str
) -> None:
    env = {}
    if state == "dirty":
        close.write("git_status.txt", " M backend/app/api.py\n")
    elif state == "unmerged-commit":
        close.write("git_ancestor_exit", "1")
    elif state == "busy-agent":
        close.answer("orca_terminal_wait", {"ok": False, "error": {"code": "timeout"}})
    else:
        env["ORCA_TERMINAL_HANDLE"] = "term_shell"
    result = close.close_task(close.extra, **env)
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_nothing_deleted(close)


def test_close_task_takes_a_branch_orca_already_deleted_as_done(close: Harness) -> None:
    """#290: show-ref saw the branch, orca worktree rm deleted it, branch -D said "not
    found": the branch is gone, so the extra dirs and the board still follow."""
    close.write("git_branch_gone_at_delete", "")
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    steps = line["steps"]
    assert "branch_already_gone" in steps and "branch_deleted" not in steps
    assert steps.index("branch_already_gone") < steps.index(
        f"extra_removed:{close.extra.as_posix()}"
    )
    assert "task/282-dryrun" not in close.branches() and not close.extra.exists()
    assert line["board"] == "完成"
    assert any("updateProjectV2" in c and "o=OPT-DONE" in c for c in close.calls("gh"))


@pytest.mark.parametrize("state", ["in-use", "unreadable"])
def test_close_task_stops_when_the_branch_cannot_be_deleted(
    close: Harness, state: str
) -> None:
    """#290: a branch that is still there after branch -D (checked out elsewhere) is a
    failed step: exit 3, the extra dirs stay and the board is not set to 完成. So is one
    show-ref then cannot read (128): only its 1 means the branch is gone (review L1)."""
    close.write("git_branch_in_use", "")
    if state == "unreadable":
        close.write("git_unreadable_after_delete", "")
    result = close.close_task(close.extra)
    assert result.returncode == 3, result.stdout + result.stderr
    line = _json_line(result)
    assert line["error"] == "刪本地 branch 失敗：task/282-dryrun"
    assert not [s for s in line["steps"] if s.startswith(("branch_", "extra_"))]
    assert line["board"] == ""
    assert not [c for c in close.calls("gh") if "updateProjectV2" in c]
    assert "task/282-dryrun" in close.branches()
    assert (close.extra / "deps" / "a.txt").is_file()


# --- close_task.sh: Docker resources (#360) ------------------------------------------

# The task's resources: compose's <project>-<service> images and <project>_<name> volumes and
# networks (projects t282-a, t282, task-282-x), images tagged t282/t282-*, a container named
# for the task and one made from its image under a random name.
OURS = {
    "containers": [
        (
            "t282-a-backend-1",
            "exited",
            "t282-a-backend",
            "t282-a_stock-data",
            "t282-a_default",
        ),
        ("task-282-run", "created", "alpine:3.20", "", "bridge"),
        ("elated_turing", "exited", "stock-lab-backend:t282", "", "bridge"),
    ],
    "images": [
        "stock-lab-backend:t282",
        "stock-lab-web:t282-a",
        "t282-a-backend:latest",
        "task-282-x-web:latest",
    ],
    "volumes": ["t282_stock-data", "t282-a_stock-data", "task-282_cache"],
    "networks": ["t282_default", "t282-a_default"],
}
# Everything else: base images, dangling ones, the user's other projects, and Issues 2820 and
# 28, whose names start with the same digits.
THEIRS = {
    "containers": [
        (
            "t2820-a-backend-1",
            "exited",
            "t2820-a-backend",
            "t2820_stock-data",
            "t2820_default",
        ),
        ("user-db", "exited", "postgres:16", "userdata", "bridge"),
    ],
    "images": [
        "python:3.12-slim",
        "node:22-alpine",
        "nginx:1.27-alpine",
        "alpine:3.20",
        "<none>:<none>",
        "postgres:16",
        "myproj-app:latest",
        "stock-lab-backend:latest",
        "stock-lab-backend:t2820",
        "t2820-backend:latest",
        "t28-backend:latest",
    ],
    "volumes": ["userdata", "t2820_stock-data", "t28_cache"],
    "networks": ["bridge", "host", "none", "t2820_default"],
}
KINDS = {
    "containers": "container",
    "images": "image",
    "volumes": "volume",
    "networks": "network",
}
DOCKER_DELETES = (
    "rm ",
    "rmi ",
    "volume rm ",
    "network rm ",
    "image prune",
    "builder prune",
)


def _docker_names(rows: list) -> list[str]:
    return [row[0] if isinstance(row, tuple) else row for row in rows]


def _set_docker(h: Harness, **kinds: list) -> None:
    for kind, rows in kinds.items():
        lines = []
        for row in rows:
            if kind == "images":
                row = tuple(row.rsplit(":", 1))
            lines.append("\t".join(row) if isinstance(row, tuple) else row)
        h.write(f"docker_{kind}.tsv", "".join(f"{line}\n" for line in lines))


def _docker_left(h: Harness, kind: str) -> list[str]:
    path = h.fake / f"docker_{kind}.tsv"
    rows = [line.split("\t") for line in path.read_text("utf-8").splitlines() if line]
    return [f"{r[0]}:{r[1]}" if kind == "images" else r[0] for r in rows]


def _docker_deletes(h: Harness) -> list[str]:
    return [c for c in h.calls("docker") if c.startswith(DOCKER_DELETES)]


def _docker_steps(line: dict) -> list[str]:
    return [s for s in line["steps"] if s.startswith("docker_")]


def _removed(kinds: dict) -> list[str]:
    return [
        f"docker_removed:{KINDS[kind]}:{name}"
        for kind in KINDS
        for name in _docker_names(kinds[kind])
    ]


@pytest.fixture
def docker(close: Harness) -> Harness:
    _set_docker(close, **{kind: OURS[kind] + THEIRS[kind] for kind in KINDS})
    return close


def _assert_theirs_left(h: Harness) -> None:
    for kind in KINDS:
        assert _docker_left(h, kind) == _docker_names(THEIRS[kind]), kind


def test_close_task_removes_the_docker_resources_named_for_the_task(
    docker: Harness,
) -> None:
    """AC-1 (#360): every kind of the task's resources goes, containers first, each by name
    (images as repository:tag, never -f); base images, dangling ones, other projects' and
    those of Issues 2820 and 28 stay. With no other Docker task, dangling images and build
    cache are pruned last."""
    result = docker.close_task(docker.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert _docker_steps(line) == _removed(OURS) + [
        "docker_pruned:images",
        "docker_pruned:build_cache",
    ]
    steps = line["steps"]
    assert steps.index(f"extra_removed:{docker.extra.as_posix()}") < steps.index(
        "docker_removed:container:t282-a-backend-1"
    )
    _assert_theirs_left(docker)
    assert _docker_deletes(docker) == [
        *(f"rm {name}" for name in _docker_names(OURS["containers"])),
        *(f"rmi {name}" for name in OURS["images"]),
        *(f"volume rm {name}" for name in OURS["volumes"]),
        *(f"network rm {name}" for name in OURS["networks"]),
        "image prune -f",
        "builder prune -f",
    ]
    assert line["board"] == "完成"


@pytest.mark.parametrize(
    "row",
    [
        ("t282-a-web-1", "running", "nginx:1.27-alpine", "", "bridge"),
        ("busy", "running", "stock-lab-web:t282-a", "", "bridge"),
        ("busy", "running", "alpine:3.20", "t282_stock-data", "bridge"),
        ("busy", "running", "alpine:3.20", "userdata", "bridge,t282-a_default"),
        ("t282-a-scheduler-1", "paused", "alpine:3.20", "", "bridge"),
    ],
    ids=["named", "image", "volume", "network", "paused"],
)
def test_close_task_keeps_the_docker_resources_while_one_runs(
    docker: Harness, row: tuple
) -> None:
    """AC-1 (#360): a running container named for the task or using one of its images,
    volumes or networks: none of the task's resources is deleted, the JSON says which
    container and what was kept, and nothing is pruned. The close itself goes on."""
    _set_docker(docker, containers=OURS["containers"] + THEIRS["containers"] + [row])
    result = docker.close_task(docker.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    kept = [
        f"docker_kept:{KINDS[kind]}:{name}"
        for kind in KINDS
        for name in _docker_names(OURS[kind])
    ]
    assert _docker_steps(line) == [
        f"docker_running:{row[0]}",
        *kept,
        "docker_prune_skipped:running_containers",
    ]
    assert not _docker_deletes(docker)
    assert _docker_left(docker, "images") == OURS["images"] + THEIRS["images"]
    assert line["board"] == "完成" and not docker.wt.exists()


@pytest.mark.parametrize(
    "why", ["volume", "image-tag", "subtask", "unknown", "running"]
)
def test_close_task_leaves_the_prune_to_the_last_docker_task(
    docker: Harness, why: str
) -> None:
    """AC-1 (#360): the task's own resources go, but dangling images and build cache stay
    while another Docker task is in progress: worktree task/253-other has resources named
    t253 (a volume, an image tag), or its HEAD holds INTEGRATION's first commit of its own
    (a Docker subtask), or git cannot tell (exit 128); or while any container runs."""
    first = "e" * 40
    reason = "docker_prune_skipped:other_docker_tasks:253"
    if why == "volume":
        _set_docker(
            docker, volumes=OURS["volumes"] + THEIRS["volumes"] + ["t253_stock-data"]
        )
    elif why == "image-tag":
        _set_docker(
            docker, images=OURS["images"] + THEIRS["images"] + ["stock-lab-api:t253"]
        )
    elif why in ("subtask", "unknown"):
        docker.write("git_rev_list.txt", f"{first}\n{'f' * 40}\n")
        docker.write(f"git_ancestor_exit_{first}", "0" if why == "subtask" else "128")
    else:
        row = ("user-web", "running", "nginx:1.27-alpine", "", "bridge")
        _set_docker(
            docker, containers=OURS["containers"] + THEIRS["containers"] + [row]
        )
        reason = "docker_prune_skipped:running_containers"
    result = docker.close_task(docker.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert _docker_steps(line) == _removed(OURS) + [reason]
    assert not [c for c in docker.calls("docker") if "prune" in c]
    if why == "subtask":
        assert f"merge-base --is-ancestor {first} {SHA}" in _git_subcommands(docker)


def test_close_task_prunes_when_no_other_worktree_is_a_docker_subtask(
    docker: Harness,
) -> None:
    """AC-1 (#360): INTEGRATION has commits of its own, but task/253-other's HEAD holds none
    of them (merge-base exit 1): it is no Docker task, so the prune runs."""
    first = "e" * 40
    docker.write("git_rev_list.txt", f"{first}\n")
    docker.write(f"git_ancestor_exit_{first}", "1")
    result = docker.close_task(docker.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _docker_steps(_json_line(result))[-2:] == [
        "docker_pruned:images",
        "docker_pruned:build_cache",
    ]
    assert any(
        c.startswith(
            f"rev-list --first-parent --reverse origin/master..origin/{INTEGRATION}"
        )
        for c in _git_subcommands(docker)
    )


@pytest.mark.parametrize("case", ["master", "integration", "no-board"])
def test_close_task_prunes_only_for_a_docker_task(close: Harness, case: str) -> None:
    """#360: a task with no Docker resources deletes nothing in Docker; it prunes only when
    it is a Docker subtask (its PR went into an integration branch). A dry run (--no-board)
    never prunes, even with resources of its own."""
    args = ["--extra-dir", close.extra.as_posix()]
    if case == "integration":
        _integration_green(close)
    elif case == "no-board":
        _set_docker(close, volumes=["t282_stock-data"])
        args.insert(0, "--no-board")
    result = close.run("close_task.sh", "282", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = {
        "master": ["docker_none", "docker_prune_skipped:no_task_resources"],
        "integration": [
            "docker_none",
            "docker_pruned:images",
            "docker_pruned:build_cache",
        ],
        "no-board": [
            "docker_removed:volume:t282_stock-data",
            "docker_prune_skipped:not_requested",
        ],
    }[case]
    assert _docker_steps(_json_line(result)) == expected
    assert bool([c for c in close.calls("docker") if "prune" in c]) == (
        case == "integration"
    )


@pytest.mark.parametrize("how", ["missing", "down", "hangs"])
def test_close_task_skips_docker_when_it_does_not_answer(
    docker: Harness, how: str
) -> None:
    """AC-1 (#360): no docker command, no daemon, or a daemon that does not answer within the
    time limit: one docker_skipped step, nothing in Docker deleted, and the close is done."""
    docker.write(f"docker_{how}", "")
    started = datetime.now()
    result = docker.close_task(docker.extra, CLOSE_TASK_DOCKER_TIMEOUT="2")
    elapsed = (datetime.now() - started).total_seconds()
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    reason = {"missing": "no_docker", "down": "daemon_unreachable", "hangs": "timeout"}[
        how
    ]
    assert _docker_steps(line) == [f"docker_skipped:{reason}"]
    assert len(docker.calls("docker")) == 1 and not _docker_deletes(docker)
    assert _docker_left(docker, "volumes") == OURS["volumes"] + THEIRS["volumes"]
    assert line["board"] == "完成" and "task/282-dryrun" not in docker.branches()
    # The fake would hang for 60 s: only the time limit ends it.
    assert elapsed < 40


def test_close_task_reports_a_docker_resource_it_could_not_delete(
    docker: Harness,
) -> None:
    """#360: a volume docker refuses to delete is a docker_failed step; the other resources
    and the prune still go, and the close does not fail."""
    docker.write("docker_fails.txt", "t282_stock-data\n")
    result = docker.close_task(docker.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    steps = _docker_steps(_json_line(result))
    expected = _removed(OURS)
    expected[expected.index("docker_removed:volume:t282_stock-data")] = (
        "docker_failed:volume:t282_stock-data"
    )
    assert steps == expected + ["docker_pruned:images", "docker_pruned:build_cache"]
    assert "t282_stock-data" in _docker_left(docker, "volumes")


# --- Claude Code scratchpads (#472) ---------------------------------------------------
# Every directory below lies under the sandbox's TEMP (Harness.temp): the refusals are
# tested on stand-ins only, never on the real Temp, a worktree or the data directory (#282).

S_ENG = "11111111-1111-4111-8111-111111111111"  # the engineer's 回報：開工
S_HANDOVER = "22222222-2222-4222-8222-222222222222"  # a second 回報：開工 (a handover)
S_SELF = "33333333-3333-4333-8333-333333333333"  # the session running close_task.sh
S_OTHER = "44444444-4444-4444-8444-444444444444"  # another task's session
S_QUESTION = "55555555-5555-4555-8555-555555555555"  # named in a 提問, not a 開工
S_LINK = "66666666-6666-4666-8666-666666666666"  # its directory is a junction/symlink
S_MISSING = "77777777-7777-4777-8777-777777777777"  # named, but no directory
S_OLD = "88888888-8888-4888-8888-888888888888"  # in the task's old-format directory


def _start(
    *sessions: str,
    first: str = "回報：開工",
    cid: int = 1,
    tail: str = "",
    author: str = "OWNER",
) -> dict:
    lines = [first, "", "- branch：`task/282-dryrun`"]
    lines += [f"- session：`{s}`{tail}" for s in sessions]
    body = "\n".join(lines + ["- HEAD：`" + SHA + "`"])
    return {
        "id": cid,
        "author_association": author,
        "body": body,
        "html_url": f"https://github.com/YiCheng0608/stock-lab/issues/282#issuecomment-{cid}",
    }


def _old_format(path: Path) -> str:
    """The old Claude Code project directory name of a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", path.as_posix())


def _session(top: Path, name: str, *files: str) -> Path:
    directory = top / name
    (directory / "scratchpad").mkdir(parents=True)
    for file in files or ("note.txt",):
        (directory / "scratchpad" / file).write_text(name, encoding="utf-8")
    return directory


def _scratch_steps(line: dict) -> list[str]:
    return [s for s in line["steps"] if s.startswith("scratchpad_")]


@pytest.fixture
def scratch(close: Harness):
    claude = close.temp / "claude"
    hashed, other = claude / "09e6f7bbfb126098", claude / "18fda106b57dcbd6"
    close.claude, close.hashed, close.other_project = claude, hashed, other
    eng = _session(hashed, S_ENG)
    # A junction (a symlink on Linux) inside the scratchpad, to a directory outside Temp.
    outside = close.root / "outside-node-modules"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    _link(outside, eng / "scratchpad" / "node_modules")
    close.outside = outside
    for name in (S_SELF, S_OTHER, S_QUESTION, "not-a-uuid"):
        _session(hashed, name)
    # Third level and first level, with an engineer's id as the name: not session
    # directories, so neither is deleted.
    _session(hashed / "deep", S_ENG)
    _session(claude, S_ENG)
    _session(other, S_HANDOVER)
    # The session directory itself is a junction/symlink to outside Temp: only the link goes.
    linked = close.root / "outside-session"
    _session(linked.parent, linked.name)
    _link(linked, other / S_LINK)
    close.linked = linked
    # The task's own old-format directory, and two that only look like it.
    old = claude / _old_format(close.wt)
    _session(old, S_OLD)
    close.old = old
    close.lookalikes = [
        claude / (_old_format(close.wt) + "-x"),
        claude / _old_format(close.root / "wt" / "task-2820-other"),
    ]
    for top in close.lookalikes:
        _session(top, S_OLD)
    close.answer(
        "gh_comments",
        [
            # As engineers write it: the model after the id.
            _start(S_ENG, cid=1, tail="（claude-opus-5-5）"),
            _start(S_QUESTION, first="提問：要不要換手？", cid=2),
            _start(S_HANDOVER, first="\n回報：開工（換手）", cid=3, author="MEMBER"),
            # The repo is public: an outside account names another task's live session.
            _start(S_OTHER, cid=5, author="NONE"),
            _start(S_OTHER, cid=6, author="CONTRIBUTOR"),
            # Not ids: a non-UUID, and S_OTHER with one more character.
            _start(
                S_LINK, S_SELF, S_MISSING, "not-a-uuid", S_OTHER + "0", S_ENG, cid=4
            ),
        ],
    )
    yield close
    for link in (eng / "scratchpad" / "node_modules", other / S_LINK):
        if link.is_symlink():
            link.unlink()
        elif link.is_junction():
            os.rmdir(link)


def test_close_task_removes_the_scratchpads_its_start_reports_name(
    scratch: Harness,
) -> None:
    """AC-1 (#472): the session directories every 回報：開工 names (a handover's too) and
    the task's old-format directory go; another session's (also when an outside account's
    回報：開工 names it, PR #485 review), this session's, a non-UUID name, a third-level and
    a first-level directory stay."""
    result = scratch.close_task(scratch.extra, CLAUDE_CODE_SESSION_ID=S_SELF)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    hashed, other, old = scratch.hashed, scratch.other_project, scratch.old
    assert _scratch_steps(line) == [
        f"scratchpad_removed:{(hashed / S_ENG).as_posix()}",
        f"scratchpad_removed:{(other / S_HANDOVER).as_posix()}",
        f"scratchpad_removed:{(other / S_LINK).as_posix()}",
        f"scratchpad_skipped:own_session:{(hashed / S_SELF).as_posix()}",
        f"scratchpad_skipped:not_found:{S_MISSING}",
        f"scratchpad_removed:{(old / S_OLD).as_posix()}",
        f"scratchpad_removed:{old.as_posix()}",
    ]
    assert line["board"] == "完成"
    assert not (hashed / S_ENG).exists() and not (other / S_HANDOVER).exists()
    assert not old.exists()
    for kept in (
        hashed / S_SELF,
        hashed / S_OTHER,
        hashed / S_QUESTION,
        hashed / "not-a-uuid",
        hashed / "deep" / S_ENG,
        scratch.claude / S_ENG,
        *(top / S_OLD for top in scratch.lookalikes),
    ):
        assert (kept / "scratchpad" / "note.txt").is_file(), kept


def test_close_task_only_unlinks_links_in_and_at_a_scratchpad(scratch: Harness) -> None:
    """AC-3 (#472): a junction/symlink inside a session directory, and a session directory
    that is one, point outside Temp: each link is unlinked first, never followed, and what
    it points to stays as it was."""
    result = scratch.close_task(scratch.extra, CLAUDE_CODE_SESSION_ID=S_SELF)
    assert result.returncode == 0, result.stdout + result.stderr
    steps = _json_line(result)["steps"]
    inner = (scratch.hashed / S_ENG / "scratchpad" / "node_modules").as_posix()
    at = (scratch.other_project / S_LINK).as_posix()
    assert steps.index(f"unlinked:{inner}") < steps.index(
        f"scratchpad_removed:{(scratch.hashed / S_ENG).as_posix()}"
    )
    assert steps.index(f"unlinked:{at}") < steps.index(f"scratchpad_removed:{at}")
    assert (scratch.outside / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (scratch.linked / "scratchpad" / "note.txt").read_text(
        encoding="utf-8"
    ) == "outside-session"
    assert not os.path.lexists(at)


def test_close_task_does_not_follow_a_scratchpad_project_that_is_a_link(
    scratch: Harness,
) -> None:
    """AC-3 (#472): Temp/claude/<project> is a junction/symlink to outside Temp: the session
    directory under it is reached through a link, so it is refused, and the target stays."""
    target = scratch.root / "outside-project"
    _session(target, S_MISSING)
    project = scratch.claude / "2cefcad9e5e0d6ff"
    _link(target, project)
    scratch.answer("gh_comments", [_start(S_MISSING)])
    try:
        result = scratch.close_task(scratch.extra, CLAUDE_CODE_SESSION_ID=S_SELF)
    finally:
        if project.is_symlink():
            project.unlink()
        elif project.is_junction():
            os.rmdir(project)
    assert result.returncode == 0, result.stdout + result.stderr
    steps = _scratch_steps(_json_line(result))
    refused = f"scratchpad_skipped:refused:{(project / S_MISSING).as_posix()}:"
    assert len(steps) == 3 and steps[0].startswith(refused), steps
    assert (target / S_MISSING / "scratchpad" / "note.txt").is_file()


@pytest.mark.parametrize(
    "case",
    ["no_start", "outside_author", "unreadable", "not_found", "no_temp", "no_own_id"],
)
def test_close_task_skips_the_scratchpads_it_cannot_find(
    scratch: Harness, case: str
) -> None:
    """AC-2 (#472): no session id in the comments (or only in an outside account's), comments
    gh cannot read, a session with no directory, no TEMP, no CLAUDE_CODE_SESSION_ID (a shell
    outside Claude cannot tell its own directory, PR #485 review): a scratchpad_skipped step,
    nothing in Temp deleted, and the close done as before (exit 0, board 完成)."""
    env = {"CLAUDE_CODE_SESSION_ID": S_SELF}
    expected = {
        "no_start": ["scratchpad_skipped:no_session_id"],
        "outside_author": ["scratchpad_skipped:no_session_id"],
        "unreadable": ["scratchpad_skipped:comments_unreadable"],
        "not_found": [f"scratchpad_skipped:not_found:{S_MISSING}"],
        "no_temp": ["scratchpad_skipped:no_temp"],
        "no_own_id": ["scratchpad_skipped:no_own_session_id"],
    }[case]
    if case == "no_start":
        scratch.answer("gh_comments", [_start(S_ENG, first="回報：PR 已開")])
    elif case == "outside_author":
        scratch.answer(
            "gh_comments",
            [_start(S_ENG, author=a, cid=i) for i, a in enumerate(("NONE", "", None))],
        )
    elif case == "no_own_id":
        del env["CLAUDE_CODE_SESSION_ID"]
    elif case == "unreadable":
        scratch.write("gh_comments.fail", "HTTP 502")
    elif case == "not_found":
        scratch.answer("gh_comments", [_start(S_MISSING)])
    shutil.rmtree(scratch.old)
    if case == "no_temp":
        # Unset inside bash: Git Bash turns an empty or relative TEMP it is started with
        # into a path under the working directory.
        result = scratch.run_bash(
            'unset TEMP; exec bash "$@"',
            (scratch.ops / "close_task.sh").as_posix(),
            "282",
            "--extra-dir",
            scratch.extra.as_posix(),
            **env,
        )
    else:
        result = scratch.close_task(scratch.extra, **env)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert _scratch_steps(line) == expected
    assert line["board"] == "完成" and "task/282-dryrun" not in scratch.branches()
    assert (scratch.hashed / S_ENG / "scratchpad" / "note.txt").is_file()


FAILING_RM = r"""#!/usr/bin/env bash
case "$*" in *"$FAIL_RM"*) echo "rm: cannot remove: Device or resource busy" >&2; exit 1 ;; esac
exec /usr/bin/rm "$@"
"""


@pytest.mark.parametrize("case", ["rm_fails", "holds_git"])
def test_close_task_goes_on_when_a_scratchpad_cannot_be_deleted(
    scratch: Harness, case: str
) -> None:
    """AC-2 (#472): rm fails on the engineer's session directory, or guard_dir refuses it (a
    .git inside): a scratchpad_skipped step, the other scratchpads still go, and the close
    is done (exit 0, board 完成)."""
    eng = scratch.hashed / S_ENG
    env = {"CLAUDE_CODE_SESSION_ID": S_SELF}
    if case == "rm_fails":
        rm = scratch.bin / "rm"
        rm.write_text(FAILING_RM, encoding="utf-8", newline="\n")
        rm.chmod(0o755)
        env["FAIL_RM"] = S_ENG
        reason = f"scratchpad_skipped:delete_failed:{eng.as_posix()}"
    else:
        (eng / "scratchpad" / "repo" / ".git").mkdir(parents=True)
        reason = f"scratchpad_skipped:refused:{eng.as_posix()}:裡面有 .git"
    result = scratch.close_task(scratch.extra, **env)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    steps = _scratch_steps(line)
    assert steps[0].startswith(reason), steps
    assert (
        f"scratchpad_removed:{(scratch.other_project / S_HANDOVER).as_posix()}" in steps
    )
    assert line["board"] == "完成"
    assert (eng / "scratchpad" / "note.txt").is_file()


def test_close_task_dry_run_leaves_the_scratchpads_alone(scratch: Harness) -> None:
    """#472: a dry run (--no-board) borrows a PR on a throwaway branch, and the Issue's
    engineer may still be at work: no scratchpad is read or deleted."""
    result = scratch.run(
        "close_task.sh", "282", "--no-board", "--extra-dir", scratch.extra.as_posix()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _scratch_steps(_json_line(result)) == ["scratchpad_skipped:no_board"]
    assert not [c for c in scratch.calls("gh") if "/comments" in c]
    assert (scratch.hashed / S_ENG / "scratchpad" / "note.txt").is_file()
    assert (scratch.old / S_OLD / "scratchpad" / "note.txt").is_file()


def test_close_task_refused_leaves_the_scratchpads_alone(scratch: Harness) -> None:
    """#472 (PR #485 review): a close refused on its checks (the PR is not merged) deletes
    no scratchpad and does not read the comments."""
    scratch.answer("gh_pr_list", [])
    result = scratch.close_task(scratch.extra, CLAUDE_CODE_SESSION_ID=S_SELF)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "未刪除任何東西" in result.stderr
    _assert_nothing_deleted(scratch)
    assert _scratch_steps(_json_line(result)) == []
    assert not [c for c in scratch.calls("gh") if "/comments" in c]
    for top in (scratch.hashed / S_ENG, scratch.other_project / S_HANDOVER):
        assert (top / "scratchpad" / "note.txt").is_file()
    assert (scratch.old / S_OLD / "scratchpad" / "note.txt").is_file()
    assert (scratch.outside / "keep.txt").is_file()


# --- patrol.sh ---------------------------------------------------------------------


def _patrol(h: Harness, *args: str) -> subprocess.CompletedProcess:
    return h.run(
        "patrol.sh", "--session-id", "sess-1", "--terminal", "term_coord", *args
    )


def _queue_event(seq: int, id_: str, kind: str = "comment", **extra) -> dict:
    return {
        "type": "event",
        "seq": seq,
        "id": id_,
        "kind": kind,
        "detected_at": "2026-10-25T11:50:00Z",
        "at": "2026-10-25T11:30:00Z",
        "ref": "#282",
        "summary": "提問： 要不要加旗標？",
        "url": "https://github.com/YiCheng0608/stock-lab/issues/282#issuecomment-9",
        **extra,
    }


@pytest.fixture
def patrol(h: Harness) -> Harness:
    # What patrol.sh asked gh before #316 is still answered by the fake: the tests
    # assert that patrol asks it nothing but the questions (#401).
    h.answer("gh_pr_list", [])
    logs = h.data / "logs"
    (logs / "events.jsonl").write_text(
        "".join(
            json.dumps(e, ensure_ascii=False) + "\n"
            for e in (
                _queue_event(1, "comment:9"),
                _queue_event(2, "ci:290:abc:success:1", "ci", ref="PR #290", url=""),
                _queue_event(3, "comment:10"),
            )
        ),
        encoding="utf-8",
    )
    (logs / "monitor-heartbeat.json").write_text(
        '{"written_at":"2026-10-25T11:59:00Z","pid":"1","mode":"wake","gh_calls":2}',
        encoding="utf-8",
    )
    (logs / "monitor-state.json").write_text(
        json.dumps(
            {
                "prs_at": "2026-10-25T11:59:00Z",
                "prs": [
                    "PR #290 ci=pending merge=BLOCKED labels=independent-review 統籌操作腳本"
                ],
                # The job log lines as the monitor read them (#338): in the container the
                # logs below are in the volume, and patrol prints these instead.
                "polled_at": "2026-10-25T11:59:00Z",
                "jobs": {
                    "daily": "daily-20261024.log ===== 2026-10-24T13:30:00Z end exit=0",
                    "news": "沒有日誌",
                    "watchdog": "2026-10-25T11:45:00Z schedules_ok | 排程無異常",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (logs / "daily-20261024.log").write_text(
        "===== 2026-10-24T13:30:00Z end exit=0\n", encoding="utf-8"
    )
    (logs / "news-20261025.log").write_text(
        "===== 2026-10-25T10:00:00Z end exit=0 news_llm_exit=0\n", encoding="utf-8"
    )
    (logs / "watchdog.log").write_text(
        "2026-10-25T11:45:00Z schedules_ok | 排程無異常\n", encoding="utf-8"
    )
    h.answer("gh_questions", _threads([]))
    return h


def _files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_patrol_writes_only_the_heartbeat_and_reads_the_queue(patrol: Harness) -> None:
    before = _files(patrol.data)
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    heartbeat = patrol.data / "logs" / "coordinator-heartbeat.json"
    assert json.loads(heartbeat.read_text(encoding="utf-8")) == {
        "session_id": "sess-1",
        "terminal_handle": "term_coord",
        "written_at": "2026-10-25T12:00:00Z",
    }
    after = _files(patrol.data)
    assert {k for k in after if after[k] != before.get(k)} == {
        "logs/coordinator-heartbeat.json"
    }
    out = result.stdout
    assert "monitor：2026-10-25T11:59:00Z（60 秒前，mode=wake）" in out
    assert "open PR（monitor 2026-10-25T11:59:00Z）：1 個" in out
    assert "PR #290 ci=pending merge=BLOCKED" in out
    assert "未處理事件：3 個（seq 1～3）" in out
    assert "[1] comment #282 2026-10-25T11:30:00Z 提問： 要不要加旗標？" in out
    assert (
        "排程 daily（monitor 2026-10-25T11:59:00Z）：daily-20261024.log"
        " ===== 2026-10-24T13:30:00Z end exit=0" in out
    )
    # From the state, not from news-20261025.log beside it.
    assert "排程 news（monitor 2026-10-25T11:59:00Z）：沒有日誌" in out
    assert (
        "看門狗（monitor 2026-10-25T11:59:00Z）：2026-10-25T11:45:00Z schedules_ok"
        in out
    )
    # #316 AC-2: the closing hint points at the queue, not at a monitor the session keeps.
    last = out.strip().splitlines()[-1]
    assert "--done" in last and "監看" not in last


def test_patrol_calls_gh_only_for_the_questions(patrol: Harness) -> None:
    """#316 AC-4, AC-5 and #401: PRs, CI and new comments come from the queue; the one gh
    call is the GraphQL query of the unanswered questions (#331 決定 6582924536)."""
    runs = ((), ("--done", "2"), ("--take-over",))
    for args in runs:
        result = _patrol(patrol, *args)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "open PR（monitor 2026-10-25T11:59:00Z）：1 個" in result.stdout
        assert "未回覆的提問：0 則" in result.stdout
    calls = patrol.calls("gh")
    assert len(calls) == len(runs)
    assert all(c.startswith("api graphql ") and "OpenQuestions" in c for c in calls)
    assert not [c for c in calls if "pr list" in c or "issues/comments" in c]
    # --max-gh 0 leaves the questions unread and asks gh nothing.
    result = _patrol(patrol, "--max-gh", "0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(patrol.calls("gh")) == len(runs)
    assert "未回覆的提問：未查完（gh 呼叫已達上限 0）" in result.stdout


def test_patrol_done_marks_up_to_a_seq_or_one_id(patrol: Harness) -> None:
    result = _patrol(patrol, "--done", "2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "標記已處理：2 個" in result.stdout
    assert "未處理事件：1 個（seq 3～3）" in result.stdout
    done_file = patrol.data / "logs" / "events-done.jsonl"
    assert [json.loads(line) for line in done_file.read_text("utf-8").splitlines()] == [
        {
            "type": "done",
            "at": "2026-10-25T12:00:00Z",
            "session_id": "sess-1",
            "ids": ["comment:9", "ci:290:abc:success:1"],
        }
    ]
    assert "未處理事件：0 個" in _patrol(patrol, "--done", "comment:10").stdout
    result = _patrol(patrol, "--done", "comment:404")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "沒有這個事件：comment:404" in result.stderr


@pytest.mark.parametrize("cap", [None, "1", "0"])
def test_patrol_stays_within_the_gh_call_cap(patrol: Harness, cap: str | None) -> None:
    result = _patrol(patrol, *(["--max-gh", cap] if cap else []))
    assert result.returncode == 0, result.stdout + result.stderr
    limit = int(cap) if cap else 1
    assert len(patrol.calls("gh")) <= limit
    assert f"gh 呼叫：{len(patrol.calls('gh'))}／上限 {limit}" in result.stdout
    # Past the cap the questions are reported as not read, and the rest still prints.
    if limit < 1:
        # One line only (PR #406 review).
        assert "略過 未回覆的提問" not in result.stdout
        assert [
            ln for ln in result.stdout.splitlines() if ln.startswith("未回覆的提問")
        ] == [f"未回覆的提問：未查完（gh 呼叫已達上限 {limit}）"]
    else:
        assert "未回覆的提問：0 則" in result.stdout
    assert "未處理事件：3 個（seq 1～3）" in result.stdout
    assert (
        "排程 daily（monitor 2026-10-25T11:59:00Z）：daily-20261024.log"
        in result.stdout
    )


# --- unanswered questions (#401) ---------------------------------------------------


def _comment(cid: int, body: str, number: int = 401, at: str = "09:00:00") -> dict:
    """A comment at 2026-10-25 <at> UTC, or at <at> itself when it holds a date.

    No database id: a comment is known by the #issuecomment-<id> in its url.
    """
    kind = "pull" if number >= 900 else "issues"
    return {
        "url": f"https://github.com/YiCheng0608/stock-lab/{kind}/{number}#issuecomment-{cid}",
        "createdAt": at if "T" in at else f"2026-10-25T{at}Z",
        "body": body,
    }


def _thread(number: int, *comments: dict, state: str = "OPEN") -> dict:
    return {
        "number": number,
        "state": state,
        "comments": {"totalCount": len(comments), "nodes": list(comments)},
    }


def _threads(
    issues: list[dict], prs: list[dict] = (), total: int | None = None
) -> dict:
    return {
        "data": {
            "repository": {
                "issues": {
                    "totalCount": len(issues) if total is None else total,
                    "nodes": issues,
                },
                "pullRequests": {"totalCount": len(prs), "nodes": list(prs)},
            }
        }
    }


QUESTION = _comment(11, "提問：要不要加旗標？\n\n選項：A／B；建議 A；卡住 AC-2。")
QUESTION_URL = QUESTION["url"]
OTHER_URL = "https://github.com/YiCheng0608/stock-lab/issues/401#issuecomment-99"


@pytest.mark.parametrize(
    ("answer", "listed"),
    [
        (_threads([_thread(401, QUESTION)]), True),
        (
            _threads(
                [
                    _thread(
                        401,
                        QUESTION,
                        _comment(
                            12, f"決定：回覆 {QUESTION_URL}\n\n選 A。", at="10:00:00"
                        ),
                    )
                ]
            ),
            False,
        ),
        (
            _threads(
                [
                    _thread(
                        401,
                        QUESTION,
                        _comment(
                            12, f"決定：回覆 {OTHER_URL}\n\n選 A。", at="10:00:00"
                        ),
                    )
                ]
            ),
            True,
        ),
        (_threads([_thread(401, QUESTION, state="CLOSED")]), False),
        # A 決定 in the PR answers the question in its Issue.
        (
            _threads(
                [_thread(401, QUESTION)],
                [_thread(901, _comment(13, f"決定：{QUESTION_URL} 選 A", number=901))],
            ),
            False,
        ),
        # Only the first line gives the type: a 決定 that quotes the link lower down in a
        # 回報 does not answer it, and 提問 later in a comment is not a question.
        (
            _threads(
                [
                    _thread(
                        401,
                        QUESTION,
                        _comment(
                            12, f"回報：收到\n\n決定：{QUESTION_URL}", at="10:00:00"
                        ),
                        _comment(14, "回報：進度\n\n提問：這不算", at="10:30:00"),
                    )
                ]
            ),
            True,
        ),
        # A 決定 has to carry the comment link: the bare id does not answer it.
        (
            _threads([_thread(401, QUESTION, _comment(12, "決定：回覆 11，選 A。"))]),
            True,
        ),
        # A bold first line is not a type.
        (
            _threads(
                [_thread(401, QUESTION, _comment(12, f"**決定：** {QUESTION_URL}"))]
            ),
            True,
        ),
    ],
    ids=[
        "a-no-decision",
        "b-decision-links-it",
        "c-decision-links-another",
        "d-issue-closed",
        "decision-in-the-pr",
        "type-is-the-first-line",
        "decision-with-only-the-id",
        "bold-decision",
    ],
)
def test_patrol_lists_unanswered_questions(
    patrol: Harness, answer: dict, listed: bool
) -> None:
    patrol.answer("gh_questions", answer)
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    line = f"#401 經過 3 小時 0 分 {QUESTION_URL}"
    if listed:
        assert "未回覆的提問：1 則\n" in result.stdout
        assert f"  {line}\n" in result.stdout
    else:
        assert "未回覆的提問：0 則\n" in result.stdout
        assert QUESTION_URL not in result.stdout.split("未回覆的提問")[1]
    # Closed Issues and PRs are not asked for, and the query carries the repository.
    query = next(c for c in patrol.calls("gh") if "OpenQuestions" in c)
    assert "issues(states:OPEN," in query and "pullRequests(states:OPEN," in query
    assert "owner=YiCheng0608" in query and "name=stock-lab" in query


@pytest.mark.parametrize("decided", [False, True])
def test_one_decision_answers_two_questions_and_a_bom_or_blank_lines_are_fine(
    patrol: Harness, decided: bool
) -> None:
    """A BOM, blank lines or spaces before the type keep it; a quote does not."""
    first = _comment(11, chr(0xFEFF) + "提問：BOM 開頭", at="09:00:00")
    second = _comment(15, "\n\n  提問：前面有空行與空白", at="09:10:00")
    quoted = _comment(16, "> 提問：引用不算", at="09:20:00")
    comments = [first, second, quoted]
    if decided:
        both = f"決定：回覆 {first['url']} 與 {second['url']}，都選 A。"
        comments.append(_comment(17, both, at="10:00:00"))
    patrol.answer("gh_questions", _threads([_thread(401, *comments)]))
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    section = result.stdout.split("未回覆的提問：")[1]
    if decided:
        assert section.startswith("0 則\n")
    else:
        assert section.startswith("2 則\n")
        assert [r.strip() for r in section.splitlines()[1:3]] == [
            f"#401 經過 3 小時 0 分 {first['url']}",
            f"#401 經過 2 小時 50 分 {second['url']}",
        ]
    assert quoted["url"] not in section


def test_patrol_lists_questions_oldest_first_with_their_age(patrol: Harness) -> None:
    patrol.answer(
        "gh_questions",
        _threads(
            [
                _thread(401, _comment(21, "提問：後問的", at="11:20:00")),
                _thread(386, _comment(22, "提問:半形冒號也算", number=386)),
            ],
            [
                _thread(
                    905,
                    _comment(23, "提問：兩天前", number=905, at="2026-10-23T09:00:00Z"),
                )
            ],
        ),
    )
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    section = result.stdout.split("未回覆的提問：")[1]
    assert section.startswith("3 則\n")
    rows = [r.strip() for r in section.splitlines()[1:4]]
    assert rows == [
        "#905 經過 2 天 3 小時 https://github.com/YiCheng0608/stock-lab/pull/905#issuecomment-23",
        "#386 經過 3 小時 0 分 https://github.com/YiCheng0608/stock-lab/issues/386#issuecomment-22",
        "#401 經過 40 分 https://github.com/YiCheng0608/stock-lab/issues/401#issuecomment-21",
    ]


@pytest.mark.parametrize("how", ["threads", "comments"])
def test_patrol_says_which_questions_it_could_not_read(
    patrol: Harness, how: str
) -> None:
    thread = _thread(401, QUESTION)
    if how == "comments":
        thread["comments"]["totalCount"] = 130
        answer = _threads([thread])
        note = "未查完：#401 有 130 則留言，只讀了最新 1 則"
    else:
        answer = _threads([thread], total=150)
        note = "未查完：open Issue 150 個，只讀了 1 個"
    patrol.answer("gh_questions", answer)
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "未回覆的提問：1 則（未查完）" in result.stdout
    assert f"  {note}\n" in result.stdout


def test_patrol_leaves_the_governance_issue_out(patrol: Harness) -> None:
    governance = _thread(1, _comment(31, "提問：#1 的留言不套類型", number=1))
    governance["comments"]["totalCount"] = 175
    patrol.answer("gh_questions", _threads([governance, _thread(401, QUESTION)]))
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "未回覆的提問：1 則\n" in result.stdout
    assert "#1 " not in result.stdout.split("未回覆的提問")[1]
    assert "未查完" not in result.stdout


def test_patrol_counts_no_question_when_it_only_has_a_note(patrol: Harness) -> None:
    patrol.answer("gh_questions", _threads([_thread(401)], total=150))
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "未回覆的提問：0 則（未查完）\n  未查完：open Issue 150 個" in result.stdout


@pytest.mark.parametrize("how", ["fails", "graphql-error"])
def test_patrol_goes_on_when_the_questions_cannot_be_read(
    patrol: Harness, how: str
) -> None:
    if how == "fails":
        patrol.write("gh_questions_fails", "")
    else:
        patrol.answer("gh_questions", {"errors": [{"message": "rate limited"}]})
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "未回覆的提問：未查完（gh api graphql 失敗）" in result.stdout
    assert "排程 news（monitor 2026-10-25T11:59:00Z）：沒有日誌" in result.stdout
    assert "gh 呼叫：1／上限 1" in result.stdout


def test_patrol_says_when_the_monitor_has_stopped(patrol: Harness) -> None:
    logs = patrol.data / "logs"
    (logs / "monitor-heartbeat.json").write_text(
        '{"written_at":"2026-10-25T11:40:00Z","pid":"1","mode":"wake","gh_calls":2}',
        encoding="utf-8",
    )
    assert "已停擺超過 10 分鐘" in _patrol(patrol).stdout
    (logs / "monitor-heartbeat.json").unlink()
    assert "monitor：沒有心跳" in _patrol(patrol).stdout


def test_patrol_reads_compactions_and_handoff(patrol: Harness) -> None:
    logs = patrol.data / "logs"
    (logs / "compactions" / "sess-1.count").write_text("2\n", encoding="utf-8")
    (logs / "handoff-sess-1.json").write_text("{}", encoding="utf-8")
    (logs / "coordinator-heartbeat.json").write_text(
        '{"session_id":"sess-1","terminal_handle":"term_coord",'
        '"written_at":"2026-10-25T11:40:00Z"}',
        encoding="utf-8",
    )
    result = _patrol(patrol)
    # #534: the handoff condition ends the run with exit 10 and a last line of its own.
    assert result.returncode == 10, result.stdout + result.stderr
    assert "壓縮 2 次：已達換手條件" in result.stdout
    assert "換手標記存在" in result.stdout
    assert "換手中" in result.stdout.strip().splitlines()[-1]


# --- #534: handoff condition as the last line, commitments ----------------------------


@pytest.mark.parametrize("count", ["0", "1", "2", "7"])
def test_patrol_ends_with_the_handoff_condition_and_exit_10(
    patrol: Harness, count: str
) -> None:
    """AC-2: at 2 compactions or more the last line says so and the exit code is 10;
    below that neither. The rest of the listing is printed as before."""
    if count != "0":
        (patrol.data / "logs" / "compactions" / "sess-1.count").write_text(
            count + "\n", encoding="utf-8"
        )
    result = _patrol(patrol)
    last = result.stdout.strip().splitlines()[-1]
    due = int(count) >= 2
    assert result.returncode == (10 if due else 0), result.stdout + result.stderr
    assert ("已達換手條件" in last) is due
    assert (f"已壓縮 {count} 次" in last) is due
    # Nothing else changed: the events, the commitments and the closing hint are there.
    assert "未處理事件：3 個（seq 1～3）" in result.stdout
    assert "未兌現的承諾：0 則" in result.stdout
    assert "其餘依手冊" in result.stdout
    # Through a pipe, | tail -1 shows it too, and the shell sees the code with pipefail.
    piped = patrol.run_bash(
        'set -o pipefail; bash "$1" --session-id sess-1 --terminal term_coord | tail -1',
        (patrol.ops / "patrol.sh").as_posix(),
    )
    assert piped.returncode == (10 if due else 0), piped.stdout + piped.stderr
    assert ("已達換手條件" in piped.stdout) is due
    assert piped.stdout.count("\n") == 1


def _commit(h: Harness, *args: str, session: str = "sess-old"):
    return h.run("commit.sh", *args, CLAUDE_CODE_SESSION_ID=session)


PROMISE = "https://github.com/YiCheng0608/stock-lab/issues/461#issuecomment-6672885313"


def test_commitments_outlive_the_session_until_done(patrol: Harness) -> None:
    """AC-1: what commit.sh add wrote in one session is listed by patrol.sh in another,
    past-due ones marked; after done it is no longer listed."""
    # NOW is 2026-10-25 12:00 UTC (20:00 Taipei).
    added = [
        (
            "2026-10-25T21:30+08:00",
            "21:30 daily 後查 emerging_issuers 有列、「興櫃」名稱",
        ),
        ("2026-10-25T09:00:00Z", "#461 AC-3：seed 20261107，30 筆"),
        ("none", "合併後才清 worktree"),
    ]
    for due, text in added:
        result = _commit(patrol, "add", "--due", due, "--url", PROMISE, "--text", text)
        assert result.returncode == 0, result.stdout + result.stderr
    assert [
        json.loads(line)["id"]
        for line in (patrol.data / "logs" / "commitments.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ] == ["c1", "c2", "c3"]
    first = json.loads(
        (patrol.data / "logs" / "commitments.jsonl").read_text("utf-8").splitlines()[0]
    )
    assert first == {
        "type": "add",
        "id": "c1",
        "issue": 461,
        "due": "2026-10-25T13:30:00Z",
        "text": added[0][1],
        "url": PROMISE,
        "at": "2026-10-25T12:00:00Z",
        "session_id": "sess-old",
    }

    # Another session's patrol (sess-1) lists all three: past due first, no time last.
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    head = lines.index("未兌現的承諾：3 則（已到期 1 則）")
    assert lines[head + 1 : head + 4] == [
        f"  [c2] [已到期] 2026-10-25 17:00（台北） #461 #461 AC-3：seed 20261107，30 筆 {PROMISE}",
        f"  [c1] 2026-10-25 21:30（台北） #461 {added[0][1]} {PROMISE}",
        f"  [c3] 無到期時間 #461 合併後才清 worktree {PROMISE}",
    ]

    done = _commit(patrol, "done", "c2", session="sess-1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "c2 已兌現" in done.stdout
    # Marking it again changes nothing.
    again = _commit(patrol, "done", "c2", session="sess-1")
    assert again.returncode == 0 and "已標記兌現" in again.stdout
    result = _patrol(patrol)
    assert "未兌現的承諾：2 則（已到期 0 則）" in result.stdout
    assert "[c2]" not in result.stdout
    assert "[c1]" in result.stdout and "[c3]" in result.stdout
    # commit.sh list prints the same lines.
    listed = _commit(patrol, "list")
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.splitlines()[0] == "未兌現的承諾：2 則（已到期 0 則）"


@pytest.mark.parametrize(
    "args",
    [
        ("add", "--due", "2026-10-25 21:30", "--url", PROMISE, "--text", "x"),
        ("add", "--due", "none", "--url", "https://example.com/1", "--text", "x"),
        ("add", "--due", "none", "--url", PROMISE, "--text", "  "),
        ("add", "--due", "none", "--url", PROMISE),
        ("add", "--due", "none", "--url", PROMISE, "--text", "x", "--extra", "y"),
        ("list", "extra"),
        ("forget", "c1"),
    ],
    ids=[
        "due-format",
        "url",
        "empty-text",
        "no-text",
        "unknown-flag",
        "list-arg",
        "verb",
    ],
)
def test_commit_refuses_bad_arguments_and_writes_nothing(
    patrol: Harness, args: tuple
) -> None:
    result = _commit(patrol, *args)
    assert result.returncode == 64, result.stdout + result.stderr
    assert not (patrol.data / "logs" / "commitments.jsonl").exists()


def test_commit_done_of_an_unknown_id_and_an_unreadable_line(patrol: Harness) -> None:
    result = _commit(patrol, "done", "c9")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "沒有這個承諾：c9" in result.stderr
    path = patrol.data / "logs" / "commitments.jsonl"
    # A partial last line (a crash mid-write) is reported and does not hide the rest.
    path.write_text('{"type": "add", "id": "c1"', encoding="utf-8")
    added = _commit(patrol, "add", "--due", "none", "--url", PROMISE, "--text", "y")
    assert added.returncode == 0, added.stderr
    assert added.stdout.strip() == "c1"
    out = _patrol(patrol).stdout
    assert "未兌現的承諾：1 則（已到期 0 則）" in out
    assert "  [c1] 無到期時間 #461 y" in out
    assert "承諾檔第 1 列讀不懂，略過" in out


# --- review of PR #283 -------------------------------------------------------------


def _short_name(path: Path) -> str:
    """The 8.3 short form of an existing Windows path (the long form when disabled)."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024):
        return str(path)
    return buffer.value


def test_close_task_refuses_an_extra_dir_reaching_the_data_dir_through_a_link(
    close: Harness,
) -> None:
    """B1: <x>/lnk/logs with lnk -> the data directory must not delete its logs."""
    keep = close.data / "logs" / "keep.log"
    keep.write_text("k", encoding="utf-8")
    hop = close.root / "hop"
    hop.mkdir()
    _link(close.data, hop / "lnk")
    try:
        result = close.close_task(close.extra, hop / "lnk" / "logs")
        assert keep.is_file()
        assert result.returncode == 1, result.stdout + result.stderr
        _assert_nothing_deleted(close)
    finally:
        link = hop / "lnk"
        if link.is_symlink():
            link.unlink()
        elif link.is_junction():
            os.rmdir(link)


@pytest.mark.skipif(os.name != "nt", reason="8.3 short names exist on Windows only")
def test_close_task_refuses_the_data_dir_by_its_short_name(close: Harness) -> None:
    """B2: C:/Users/YiCheng/STOCK-~3 is the real data directory's short name."""
    data = close.root / "stockdata-production"
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "keep.db").write_text("k", encoding="utf-8")
    short = _short_name(data)
    if Path(short).name.lower() == data.name.lower():
        pytest.skip("8.3 short names are disabled on this volume")
    result = close.run(
        "close_task.sh",
        "282",
        "--extra-dir",
        close.extra.as_posix(),
        "--extra-dir",
        short.replace("\\", "/") + "/raw",
        STOCK_DATA_DIR=data.as_posix(),
    )
    assert (data / "raw" / "keep.db").is_file()
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_nothing_deleted(close)


@pytest.mark.skipif(os.name != "nt", reason="the /tmp alias is Git Bash on Windows")
def test_guard_dir_sees_one_path_in_its_msys_and_windows_spellings(h: Harness) -> None:
    """M4: cygpath -u turned C:/…/AppData/Local/Temp/x into /tmp/x but left /c/… alone."""
    # Only the sandbox's own data directory, spelled through the /tmp mount: that needs
    # tmp_path under the mount (pytest's default basetemp in %TEMP% is).
    temp = subprocess.run(
        [BASH, "-c", "cygpath -m /tmp"], capture_output=True, text=True, check=True
    ).stdout.strip()
    data_windows = h.data.as_posix()
    if not data_windows.lower().startswith(temp.lower() + "/"):
        pytest.skip(f"tmp_path is not under the /tmp mount ({temp}): no /tmp spelling")
    data_msys = "/tmp" + data_windows[len(temp) :]
    data_drive = _bash_path(h.data)
    for data, extra in (
        (data_msys, data_windows + "/logs"),
        (data_windows, data_drive + "/logs"),
        (data_windows, data_msys + "/logs"),
        (data_drive, data_msys + "/logs"),
    ):
        reason = h.run_bash(
            'script_dir="$1"; shift; . "$script_dir/coordinator_lib.sh"; guard_dir "$@"',
            h.ops.as_posix(),
            extra,
            STOCK_DATA_DIR=data,
        ).stdout.strip()
        assert reason, (data, extra)


@pytest.mark.parametrize("listing", ["orca_terminal_list", "orca_worktree_list"])
def test_close_task_deletes_nothing_when_an_orca_listing_fails(
    close: Harness, listing: str
) -> None:
    """M3: an ok:false listing is not "no terminals" / "no worktree"."""
    close.answer(listing, {"ok": False, "error": {"code": "runtime_unavailable"}})
    result = close.close_task(close.extra)
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_nothing_deleted(close)


@pytest.mark.parametrize(
    "send",
    [
        {"ok": False, "error": {"code": "transport", "message": "lost"}},
        _ok({"send": {"accepted": False}}),
    ],
    ids=["send-failed", "not-accepted"],
)
def test_dispatch_treats_an_unconfirmed_send_as_maybe_sent(
    dispatch: Harness, send: dict
) -> None:
    """L5: the text may be in the terminal already, so not exit 1 (\"not sent\")."""
    dispatch.answer("orca_terminal_send", send)
    result = _dispatch(dispatch)
    assert result.returncode == 3, result.stdout + result.stderr
    assert _json_line(result)["sent"] is None
    assert (
        len([c for c in dispatch.calls("orca") if c.startswith("terminal send")]) == 1
    )


def test_close_task_refuses_a_pr_whose_head_is_another_branch(close: Harness) -> None:
    """L6: --pr pointing at another task's PR is refused unless explicitly allowed."""
    close.answer(
        "gh_pr_view",
        {
            "number": 271,
            "state": "MERGED",
            "mergeCommit": {"oid": MERGE_SHA},
            "headRefName": "task/264-news-candidate-exchange",
            "baseRefName": "master",
        },
    )
    result = close.run(
        "close_task.sh", "282", "--pr", "271", "--extra-dir", close.extra.as_posix()
    )
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_nothing_deleted(close)
    result = close.run(
        "close_task.sh",
        "282",
        "--pr",
        "271",
        "--allow-pr-head-mismatch",
        "--no-board",
        "--extra-dir",
        close.extra.as_posix(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not close.wt.exists()


def _heartbeat(h: Harness, session: str, written_at: str) -> Path:
    path = h.data / "logs" / "coordinator-heartbeat.json"
    path.write_text(
        json.dumps(
            {
                "session_id": session,
                "terminal_handle": "term_x",
                "written_at": written_at,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_patrol_does_not_overwrite_another_live_coordinators_heartbeat(
    patrol: Harness,
) -> None:
    """L7: a heartbeat of another session from 20 minutes ago stays as it is."""
    path = _heartbeat(patrol, "other", "2026-10-25T11:40:00Z")
    before = path.read_bytes()
    result = _patrol(patrol)
    assert result.returncode != 0, result.stdout + result.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize("how", ["handoff-marker", "take-over", "stale"])
def test_patrol_takes_over_a_heartbeat_when_allowed(patrol: Harness, how: str) -> None:
    written = "2026-10-25T10:30:00Z" if how == "stale" else "2026-10-25T11:40:00Z"
    path = _heartbeat(patrol, "other", written)
    args = []
    if how == "handoff-marker":
        (patrol.data / "logs" / "handoff-other.json").write_text("{}", encoding="utf-8")
    elif how == "take-over":
        args = ["--take-over"]
    result = _patrol(patrol, *args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == "sess-1"
    assert not list((patrol.data / "logs").glob("*.tmp*"))


def test_guard_dir_refuses_any_path_through_a_link(h: Harness) -> None:
    """A link on the way is refused whatever it points at, with or without the tail.

    cygpath -m resolves junctions itself, so a path converted with it no longer shows
    the link: <x>/lnk/sub came out as <target>/sub and was allowed (AC-2 rerun, #283).
    """
    target = h.root / "anywhere"
    (target / "exists").mkdir(parents=True)
    hop = h.root / "hop"
    hop.mkdir()
    _link(target, hop / "lnk")
    try:
        spellings = [(hop / "lnk").as_posix()]
        if os.name == "nt":
            spellings += [str(hop / "lnk"), _bash_path(hop / "lnk")]
        for base in spellings:
            for tail in ("", "/exists", "/missing", "/missing/deeper"):
                assert _guard(h, base + tail), base + tail
        assert _guard(h, target.as_posix() + "/exists") == ""
    finally:
        link = hop / "lnk"
        if link.is_symlink():
            link.unlink()
        elif link.is_junction():
            os.rmdir(link)


def test_close_task_never_takes_the_pr_head_as_the_branch_of_another_task(
    close: Harness,
) -> None:
    """With the worktree gone, --pr's head task/264-… is not this task's branch."""
    close.answer("orca_worktree_list", _ok({"worktrees": []}))
    close.write("branches.txt", "master\ntask/264-news-candidate-exchange\n")
    close.answer(
        "gh_pr_view",
        {
            "number": 271,
            "state": "MERGED",
            "mergeCommit": {"oid": MERGE_SHA},
            "headRefName": "task/264-news-candidate-exchange",
            "baseRefName": "master",
        },
    )
    args = ("--slug", "dryrun", "--pr", "271", "--allow-pr-head-mismatch", "--no-board")
    result = close.run("close_task.sh", "282", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "task/264-news-candidate-exchange" in close.branches()
    assert not [c for c in close.calls("git") if " branch -D " in f" {c} "]


# Built inside bash, from a file: passed from Python as an argument (argv or -c), MSYS
# rewrites the backslashes before the script sees them, so a UNC path could not be
# tested that way (#283 review M1). Only the sandbox's data directory is spelled.
NON_LOCAL_SPELLINGS = r"""
script_dir="$1"
. "$script_dir/coordinator_lib.sh"
spellings() {
  local d="$STOCK_DATA_DIR" w
  if command -v cygpath >/dev/null 2>&1; then
    w="$(cygpath -w "$d")"
    printf '%s\n' "\\\\localhost\\${w:0:1}\$${w:2}\\raw" \
      "//localhost/${w:0:1}\$/${d:3}/raw" \
      "\\\\?\\$w\\raw" \
      "\\\\.\\$w\\raw" \
      "//?/$d/raw" \
      "${w:0:2}raw" \
      "\\${w:3}\\raw"
  else
    printf '%s\n' "//localhost$d/raw" "\\\\localhost$d/raw" "//$d/raw"
  fi
  printf '%s\n' "raw" "data/raw" "./data/raw"
}
spellings | while IFS= read -r p; do printf '%s\t%s\n' "$p" "$(guard_dir "$p")"; done
"""

UNC_CLOSE_TASK = r"""
w="$(cygpath -w "$STOCK_DATA_DIR")"
unc="\\\\localhost\\${w:0:1}\$${w:2}\\raw"
printf 'extra=%s\n' "$unc" >&2
exec bash "$1" 282 --extra-dir "$2" --extra-dir "$unc"
"""


def _bash_file(
    h: Harness, name: str, body: str, *args: str
) -> subprocess.CompletedProcess:
    script = h.root / name
    script.write_text(body, encoding="utf-8", newline="\n")
    return h.run_bash('f="$1"; shift; . "$f"', script.as_posix(), *args)


def test_guard_dir_refuses_unc_device_and_relative_paths(h: Harness) -> None:
    """M1: \\\\localhost\\C$\\… reached the data directory past both guards."""
    result = _bash_file(h, "spellings.sh", NON_LOCAL_SPELLINGS, h.ops.as_posix())
    assert result.returncode == 0, result.stderr
    rows = [line.split("\t", 1) for line in result.stdout.splitlines()]
    assert len(rows) >= 6, result.stdout
    assert any(row[0].startswith("\\\\") for row in rows), result.stdout
    for row in rows:
        assert len(row) == 2 and row[1], row


@pytest.mark.skipif(os.name != "nt", reason="UNC paths are a Windows matter")
def test_close_task_refuses_a_unc_extra_dir_built_in_bash(close: Harness) -> None:
    keep = close.data / "raw" / "keep.db"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("k", encoding="utf-8")
    result = _bash_file(
        close,
        "close_unc.sh",
        UNC_CLOSE_TASK,
        (close.ops / "close_task.sh").as_posix(),
        close.extra.as_posix(),
    )
    assert "extra=\\\\localhost\\" in result.stderr, result.stderr
    assert keep.is_file()
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_nothing_deleted(close)


@pytest.mark.parametrize(
    "content",
    [
        '{"session_id":"other","terminal_handle":"t","written_at":"yesterday"}',
        '{"session_id":"sess-1","terminal_handle":"t","written_at":"bad"}',
        '{"terminal_handle":"t","written_at":"2026-10-25T11:40:00Z"}',
        "not json",
        "",
    ],
    ids=["bad-time", "own-session-bad-time", "no-session", "not-json", "empty"],
)
def test_patrol_keeps_a_heartbeat_it_cannot_read(patrol: Harness, content: str) -> None:
    """L3: a malformed heartbeat counts as another session's; --take-over replaces it."""
    path = patrol.data / "logs" / "coordinator-heartbeat.json"
    path.write_text(content, encoding="utf-8")
    before = path.read_bytes()
    result = _patrol(patrol)
    assert result.returncode == 3, result.stdout + result.stderr
    assert path.read_bytes() == before
    result = _patrol(patrol, "--take-over")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == "sess-1"


def _check(name: str, started: str, **state: str) -> dict:
    return {"name": name, "startedAt": f"2026-10-25T20:{started}Z", **state}


@pytest.mark.parametrize(
    ("rollup", "expected"),
    [
        (
            [
                _check("backend", "04:13", conclusion="CANCELLED"),
                _check("backend", "04:55", conclusion="SUCCESS"),
                _check("required", "04:41", conclusion="FAILURE"),
                _check("required", "13:23", conclusion="SUCCESS"),
            ],
            "success",
        ),
        (
            [
                _check("required", "04:41", conclusion="SUCCESS"),
                _check("required", "13:23", conclusion="FAILURE"),
            ],
            "failure",
        ),
        (
            [
                _check("required", "04:41", conclusion="FAILURE"),
                _check("required", "13:23", status="IN_PROGRESS"),
            ],
            "pending",
        ),
        (
            [
                _check("required", "04:41", conclusion="SUCCESS"),
                {
                    "name": "required",
                    "status": "QUEUED",
                    "conclusion": "",
                    "startedAt": "0001-01-01T00:00:00Z",
                    "completedAt": "0001-01-01T00:00:00Z",
                },
            ],
            "pending",
        ),
        (
            [
                {
                    **_check("required", "04:41", conclusion="FAILURE"),
                    "workflowName": "A",
                },
                {
                    **_check("required", "13:23", conclusion="SUCCESS"),
                    "workflowName": "B",
                },
            ],
            "failure",
        ),
    ],
    ids=[
        "superseded-failure",
        "latest-failure",
        "latest-running",
        "queued-zero-time",
        "same-name-other-workflow",
    ],
)
def test_patrol_reads_only_the_latest_run_of_each_check(
    patrol: Harness, rollup: list[dict], expected: str
) -> None:
    """#286: a run replaced by a newer one of the same check no longer decides ci=.
    Since #316 the PR line comes from the monitor's last poll."""
    patrol.answer(
        "gh_pr_list",
        [
            {
                "number": 285,
                "title": "策略框架",
                "isDraft": False,
                "mergeStateStatus": "CLEAN",
                "statusCheckRollup": rollup,
                "labels": [],
            }
        ],
    )
    polled = patrol.run("monitor.sh", "--once", "--record-only", MONITOR_NOW=str(NOW))
    assert polled.returncode == 0, polled.stdout + polled.stderr
    result = _patrol(patrol)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PR #285 ci={expected} merge=CLEAN" in result.stdout


@pytest.mark.parametrize("handle", ["-x", "--enter", "--terminal=x"])
def test_patrol_refuses_a_handle_orca_would_read_as_an_option(tmp_path, handle) -> None:
    """#338 review: the heartbeat's handle is what the wake listener wakes; one starting
    with "-" never gets there (patrol.sh exits 64 before writing the heartbeat)."""
    h = Harness(tmp_path)
    result = h.run("patrol.sh", "--session-id", "coord", "--terminal", handle)
    assert result.returncode == 64, result.stdout + result.stderr
    assert "不能以 - 開頭" in result.stderr
    assert not (h.data / "logs" / "coordinator-heartbeat.json").exists()
