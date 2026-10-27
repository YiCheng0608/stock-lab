"""tools/ops/dispatch.sh, close_task.sh and patrol.sh with fake orca, gh and git (Issue #282).

The event monitor (monitor.sh, event_queue.py, #316) has its own tests in
test_event_monitor.py on the same harness.

Each test copies the scripts into a sandbox repository under tmp_path, puts a bin
directory holding fake ``orca``, ``gh`` and ``git`` scripts in front of PATH, points HOME
and STOCK_DATA_DIR into tmp_path and runs the copy through bash. The fakes record every
call in ``<fake>/<name>_calls.log`` and answer from JSON files the test writes into the
fake directory (a missing answer is an empty success). Nothing touches Orca, GitHub, the
repository's git state or the real data directory.

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
import shutil
import stat
import subprocess
import sys
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
    "compact_hook.sh",
)
REPO_ID = "repo-1"
SHA = "a" * 40
MERGE_SHA = "b" * 40
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
# the directory it names, as Orca does.
FAKE_ORCA = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/orca_calls.log"
key="orca_$1_$2"
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

# A <fake>/<key>.fail file makes that call exit 1 (key gh_comments for the comments
# listing, else gh_<sub1>_<sub2>).
FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/gh_calls.log"
case "$1 $2" in "api repos/"*) k=gh_comments ;; *) k="gh_$1_$2" ;; esac
[ -f "$d/$k.fail" ] && exit 1
case "$1 $2" in
  "api graphql")
    case "$*" in
      *addProjectV2ItemById*) echo "ITEM-NEW" ;;
      *updateProjectV2ItemFieldValue*) cat "$d/board_item.txt" 2>/dev/null || echo "ITEM-1" ;;
      *) cat "$d/gh_board.json" ;;
    esac ;;
  "api repos/"*) cat "$d/gh_comments.json" 2>/dev/null || echo '[]' ;;
  *) key="gh_$1_$2"; [ -f "$d/$key.json" ] && cat "$d/$key.json" || echo '[]' ;;
esac
"""

# git -C <dir> <subcommand> ...: branches live in <fake>/branches.txt, one per line.
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
  rev-parse) echo "${FAKE_SHA}" ;;
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
  merge-base) exit "$(cat "$d/git_ancestor_exit" 2>/dev/null || echo 0)" ;;
  status) cat "$d/git_status.txt" 2>/dev/null ;;
  worktree)
    [ "$2" = list ] && cat "$d/git_worktrees.txt" 2>/dev/null
    exit 0 ;;
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
        # The scripts run from a copy, so repo_root is this sandbox, not the checkout.
        self.repo = root / "repo"
        self.ops = self.repo / "tools" / "ops"
        for directory in (
            self.bin,
            self.fake,
            self.data / "logs" / "compactions",
            self.home,
            self.ops,
            self.repo / ".git",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        for name in SCRIPTS:
            shutil.copyfile(OPS / name, self.ops / name)
        for name, body in (("orca", FAKE_ORCA), ("gh", FAKE_GH), ("git", FAKE_GIT)):
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
            STOCK_DATA_DIR=self.data.as_posix(),
            STOCK_PYTHON=Path(sys.executable).as_posix(),
            PATROL_NOW=str(NOW),
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
    # CRLF as an editor on Windows saves it; the text sent must not carry the CR.
    task.write_bytes("你是 #282 的工程師。\r\n第二行：只回覆「收到」。\r\n".encode())
    h.task = task
    return h


def _dispatch(h: Harness) -> subprocess.CompletedProcess:
    return h.run("dispatch.sh", "282", "dryrun", "--task-file", h.task.as_posix())


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
    assert sent == "你是 #282 的工程師。\n第二行：只回覆「收到」。"
    assert "branch -m YiCheng0608/task-282-dryrun task/282-dryrun" in " ".join(
        dispatch.calls("git")
    )
    update = [c for c in dispatch.calls("gh") if "updateProjectV2ItemFieldValue" in c]
    assert len(update) == 1 and "o=OPT-DEV" in update[0] and "i=ITEM-1" in update[0]


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


# --- close_task.sh -----------------------------------------------------------------


@pytest.fixture
def close(h: Harness):
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
# tmp_path as this file's Harness, test_worker_job_scripts and test_verify_tools build
# them (an empty .git directory, a .git file, a read-only git object file), one in a
# test that then skips; with INNER_KILL=1 the last test exits the process before
# pytest's teardown, as a killed run does.
INNER_TESTS = r"""
import os
import stat

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
"""


def _inner_pytest(
    h: Harness, fail: bool, basetemp: str = "b", kill: bool = False
) -> tuple[Path, subprocess.CompletedProcess]:
    """A pytest run with --basetemp in an engineer's temp directory outside the worktree,
    as #272 and #270 had it (C:/v270/pt/b): returns that directory and the run. Runs
    with another BASETEMP name go to the same directory, as #279's t279/b1, bf did."""
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
        INNER_FAIL="1" if fail else "0",
        INNER_KILL="1" if kill else "0",
    )
    command = [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q"]
    command += ["--rootdir", str(inner), "--confcutdir", str(inner)]
    command += ["--basetemp", str(temp / basetemp), str(inner)]
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
    assert "1 passed, 2 skipped" in result.stdout
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
    # assert that patrol asks nothing.
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
    assert "daily-20261024.log ===== 2026-10-24T13:30:00Z end exit=0" in out
    assert "schedules_ok" in out
    # #316 AC-2: the closing hint points at the queue, not at a monitor the session keeps.
    last = out.strip().splitlines()[-1]
    assert "--done" in last and "監看" not in last


def test_patrol_makes_no_gh_call(patrol: Harness) -> None:
    """#316 AC-4, AC-5: GitHub is the monitor's; patrol reads the queue only."""
    for args in ((), ("--done", "2"), ("--take-over",)):
        result = _patrol(patrol, *args)
        assert result.returncode == 0, result.stdout + result.stderr
    assert patrol.calls("gh") == []


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
    assert result.returncode == 0, result.stdout + result.stderr
    assert "壓縮 2 次：已達換手條件" in result.stdout
    assert "換手標記存在" in result.stdout


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
