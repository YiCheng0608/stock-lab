"""tools/ops/memory_check.py and its calls from close_task.sh and take_over.sh (Issue #705).

memory_check.py runs on a memory directory under tmp_path and, for the path check, a git
repository of its own under tmp_path (origin/master made with update-ref; every commit
passes its identity with -c, so no git config is written). The real memory directory and
the checkout's git are never read. The script runs are on the harness of
test_coordinator_scripts.py (fake gh, orca, git and the sandbox memory directory
STOCK_MEMORY_DIR), so they never reach Orca, GitHub or the real worktrees.
"""

# The fixtures h and close come from test_coordinator_scripts; pytest hands them over by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from test_coordinator_scripts import (  # noqa: F401  (h, close are fixtures)
    OPS,
    Harness,
    _json_line,
    close,
    h,
)
from test_take_over import COMMENT_URL, _last, _take_over, to  # noqa: F401

SCRIPT = OPS / "memory_check.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose origin/master has tools/a.py and docs/keep.md; docs/old.md was in
    the first commit only; web/.vite/ is ignored and not there."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    for name, text in (
        ("tools/a.py", "x = 1\n"),
        ("docs/old.md", "old\n"),
        ("docs/keep.md", "keep\n"),
        (".gitignore", "web/.vite/\n"),
        ("web/index.html", "<p></p>\n"),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    _git(root, "rm", "-q", "docs/old.md")
    _git(root, "commit", "-q", "-m", "second")
    _git(root, "update-ref", "refs/remotes/origin/master", "HEAD")
    return root


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    """A memory directory that passes every check: two memories linking each other."""
    root = tmp_path / "memory"
    root.mkdir()
    _write(
        root,
        "MEMORY.md",
        "- [A](a-memory.md) — the first\n- [B](b-memory.md) — the second\n",
    )
    _write(root, "a-memory.md", _memory("a-memory", "See [[b-memory]]."))
    _write(root, "b-memory.md", _memory("b-memory", "See [[a-memory]]."))
    return root


def _memory(name: str, body: str) -> str:
    return f"---\nname: {name}\ndescription: x\nmetadata:\n  type: project\n---\n\n{body}\n"


def _write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8", newline="\n")


def _run(*args: str, **env: str) -> subprocess.CompletedProcess:
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("STOCK_", "CLAUDE_CONFIG_DIR"))
    }
    base.update(env)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=base,
    )


def _check(memory: Path, repo: Path) -> subprocess.CompletedProcess:
    return _run("--memory-dir", str(memory), "--repo", str(repo))


def _failures(result: subprocess.CompletedProcess) -> list[str]:
    lines = result.stdout.splitlines()
    return [
        line.removeprefix("memory_check: ")
        for line in lines
        if not re.match(r"memory_check: (失敗 \d+ 項|通過)（", line)
    ]


def _with_body(memory: Path, body: str) -> None:
    _write(memory, "a-memory.md", _memory("a-memory", body))


# --- memory_check.py: each check red on a broken directory, green on a good one ---------


def test_a_good_memory_directory_passes(memory: Path, repo: Path) -> None:
    result = _check(memory, repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _failures(result) == []
    assert "通過（2 則記憶" in result.stdout


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (
            "- [A](a-memory.md) — x\n- [B](b-memory.md) — x\n- [C](gone.md) — x\n",
            "MEMORY.md:3: index: gone.md 不存在",
        ),
        (
            "- [A](a-memory.md) — x\n- [B](b-memory.md) — x\n- [A again](a-memory.md)\n",
            "MEMORY.md:3: index: a-memory.md 在第 1 列已列過",
        ),
        (
            "- [A](a-memory.md) — x\n- [B](b-memory.md) — x\n- no link at all\n",
            "MEMORY.md:3: index: 一列要剛好連到一個記憶檔，這列有 0 個連結",
        ),
        (
            "- [A](a-memory.md) — x\n- [B](b-memory.md) — x\n- [D](../d.md)\n",
            "MEMORY.md:3: index: 連結 ../d.md 不是記憶目錄裡的 .md 檔名",
        ),
    ],
    ids=["missing-file", "listed-twice", "no-link", "outside"],
)
def test_index_fails_on_a_line_that_names_no_single_existing_file(
    memory: Path, repo: Path, index: str, expected: str
) -> None:
    _write(memory, "MEMORY.md", index)
    result = _check(memory, repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _failures(result) == [expected]


def test_index_fails_without_memory_md(memory: Path, repo: Path) -> None:
    (memory / "MEMORY.md").unlink()
    result = _check(memory, repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _failures(result)[0].startswith("MEMORY.md: index: 記憶目錄")


@pytest.mark.parametrize("name", ["c-memory.md", "notes.txt", "subdir"])
def test_orphan_fails_on_an_entry_the_index_does_not_list(
    memory: Path, repo: Path, name: str
) -> None:
    if name == "subdir":
        (memory / name).mkdir()
    else:
        _write(memory, name, _memory("c-memory", "x"))
    result = _check(memory, repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _failures(result) == [f"{name}: orphan: 不在 MEMORY.md 的索引裡"]


def test_link_fails_on_a_name_no_memory_has(memory: Path, repo: Path) -> None:
    _with_body(memory, "See [[b-memory]] and [[renamed-memory]].")
    result = _check(memory, repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _failures(result) == ["a-memory.md: link: [[renamed-memory]] 沒有這則記憶"]


def test_link_takes_the_frontmatter_name_or_the_file_name(
    memory: Path, repo: Path
) -> None:
    _write(memory, "b-memory.md", _memory("b-slug", "x"))
    _with_body(memory, "See [[b-memory]] and [[b-slug]].")
    result = _check(memory, repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_link_in_code_is_not_a_link(memory: Path, repo: Path) -> None:
    # As in memory-upkeep-rule (`[[舊名稱]]`) and a JSON sample in a code span or block.
    _with_body(memory, 'Search `[[舊名稱]]`; `[[a,{"b":1}]]`.\n\n```\n[[nope]]\n```')
    result = _check(memory, repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_path_fails_on_a_repo_path_not_on_origin_master(
    memory: Path, repo: Path
) -> None:
    _with_body(memory, "Read `tools/a.py` and `docs/old.md`, then `tools/gone.py:12`.")
    result = _check(memory, repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert [f.split("（")[0] for f in _failures(result)] == [
        "a-memory.md: path: `docs/old.md` 不在 origin/master",
        "a-memory.md: path: `tools/gone.py` 不在 origin/master",
    ]


def test_path_passes_what_is_on_origin_master_ignored_or_no_repo_path(
    memory: Path, repo: Path
) -> None:
    body = " ".join(
        f"`{text}`"
        for text in (
            "tools/a.py",
            "tools/",
            "./tools/a.py",
            "tools/a.py:3-9",
            "tools/a.py::test_x[1]",
            "docs#anchor",
            "web/.vite/",  # ignored by .gitignore, not there
            "web/...",  # placeholders, commands, globs
            "tools/<name>.py",
            "tools/*.py",
            "git diff tools/gone.py",
            "C:/Users/x/gone.py",  # not under a top-level entry of the repo
            "/tmp/gone",
            "app/gone.py",
            "gone.py",  # no "/": a bare file name is not checked
        )
    )
    _with_body(memory, body + "\n\n```bash\ncat tools/gone.py `tools/gone.py`\n```")
    result = _check(memory, repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_path_at_a_commit_is_checked_on_that_commit(memory: Path, repo: Path) -> None:
    old = _git(repo, "rev-parse", "HEAD~1")
    _with_body(memory, f"Was `docs/old.md@{old[:8]}`.")
    assert _check(memory, repo).returncode == 0
    head = _git(repo, "rev-parse", "HEAD")
    _with_body(memory, f"Was `docs/old.md@{head[:8]}`.")
    result = _check(memory, repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _failures(result) == [
        f"a-memory.md: path: `docs/old.md@{head[:8]}` 不在 {head[:8]}"
    ]


def test_every_failure_is_listed_with_its_memory_and_check(
    memory: Path, repo: Path
) -> None:
    _write(memory, "stray.md", "x")
    _with_body(memory, "[[gone]] `tools/gone.py`")
    result = _check(memory, repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert [f.split(": ")[:2] for f in _failures(result)] == [
        ["stray.md", "orphan"],
        ["a-memory.md", "link"],
        ["a-memory.md", "path"],
    ]
    assert result.stdout.splitlines()[-1].startswith("memory_check: 失敗 3 項（")


# --- where the directory is --------------------------------------------------------------


def test_a_missing_directory_fails_and_says_so(tmp_path: Path, repo: Path) -> None:
    gone = tmp_path / "no-memory"
    result = _check(gone, repo)
    assert result.returncode == 2, result.stdout + result.stderr
    assert f"找不到記憶目錄：{gone}" in result.stderr


def test_stock_memory_dir_names_the_directory(
    tmp_path: Path, memory: Path, repo: Path
) -> None:
    result = _run("--repo", str(repo), STOCK_MEMORY_DIR=str(memory))
    assert result.returncode == 0, result.stdout + result.stderr
    result = _run("--repo", str(repo), STOCK_MEMORY_DIR=str(tmp_path / "elsewhere"))
    assert result.returncode == 2, result.stdout + result.stderr


def test_the_default_is_claude_codes_directory_for_the_main_checkout(
    tmp_path: Path, memory: Path, repo: Path
) -> None:
    """From a worktree too: Claude Code keeps one memory per main checkout."""
    config = tmp_path / "config"
    main = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    slug = re.sub(r"[^A-Za-z0-9]", "-", main.parent.as_posix())
    target = config / "projects" / slug / "memory"
    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    for where in (repo, worktree):
        result = _run("--repo", str(where), CLAUDE_CONFIG_DIR=str(config))
        assert result.returncode == 2, result.stdout + result.stderr
        assert f"找不到記憶目錄：{target}" in result.stderr
    target.parent.mkdir(parents=True)
    memory.rename(target)
    result = _run("--repo", str(worktree), CLAUDE_CONFIG_DIR=str(config))
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_ref_git_cannot_read_fails_instead_of_passing(
    memory: Path, repo: Path
) -> None:
    _with_body(memory, "`tools/a.py`")
    result = _run("--memory-dir", str(memory), "--repo", str(repo), "--ref", "nope")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "讀不到" in result.stderr and "nope" in result.stderr


# --- close_task.sh (AC-4) ----------------------------------------------------------------


def _break(h: Harness) -> None:
    """A memory of the sandbox directory links one that is gone."""
    path = h.memory / "sandbox-memory.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("[[sandbox-memory]]", "[[gone]]"),
        encoding="utf-8",
    )


def _board_set(h: Harness) -> bool:
    return any("updateProjectV2" in c for c in h.calls("gh"))


def test_close_task_checks_the_memory_last_before_the_board(close: Harness) -> None:
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    steps = _json_line(result)["steps"]
    assert steps[-1] == "memory_ok"
    assert steps.index("index_fresh:1") < steps.index("memory_ok")


def test_close_task_fails_on_a_broken_memory_after_the_cleanup(close: Harness) -> None:
    _break(close)
    result = close.close_task(close.extra)
    assert result.returncode == 3, result.stdout + result.stderr
    line = _json_line(result)
    assert line["error"] == (
        "記憶檢查失敗：sandbox-memory.md: link: [[gone]] 沒有這則記憶；"
        "改好記憶後續跑 bash tools/ops/close_task.sh 282 --pr 290"
    )
    # The cleanup and the index ran and are listed; the board stays as it was.
    assert "worktree_removed" in line["steps"] and "index_fresh:1" in line["steps"]
    assert "memory_ok" not in line["steps"]
    assert not _board_set(close)
    assert "memory_check: sandbox-memory.md: link:" in result.stderr

    # The coordinator fixes the memory and reruns with --pr: it finishes.
    (close.memory / "sandbox-memory.md").write_text("no links\n", encoding="utf-8")
    close.answer("orca_worktree_list", {"ok": True, "result": {"worktrees": []}})
    close.answer(
        "gh_pr_view",
        {
            "number": 290,
            "state": "MERGED",
            "mergeCommit": {"oid": "b" * 40},
            "headRefName": "task/282-dryrun",
            "baseRefName": "master",
        },
    )
    again = close.run("close_task.sh", "282", "--pr", "290")
    assert again.returncode == 0, again.stdout + again.stderr
    line = _json_line(again)
    assert line["steps"][-1] == "memory_ok" and line["board"] == "完成"


def test_close_task_fails_without_the_memory_directory(close: Harness) -> None:
    result = close.close_task(
        close.extra, STOCK_MEMORY_DIR=(close.root / "x").as_posix()
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "找不到記憶目錄" in _json_line(result)["error"]
    assert not _board_set(close)


# --- take_over.sh (AC-4) -----------------------------------------------------------------


def test_take_over_checks_the_memory_last(to: Harness) -> None:
    result = _take_over(to, "term_old")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _last(result)["done"][-2:] == ["commitments", "memory"]
    assert "memory_check: 通過（1 則記憶" in result.stdout


def test_take_over_stops_at_a_broken_memory_and_goes_on_from_it(to: Harness) -> None:
    _break(to)
    result = _take_over(to, "term_old")
    assert result.returncode == 1, result.stdout + result.stderr
    line = _last(result)
    assert line["failed"] == "memory"
    assert line["done"] == [
        "heartbeat",
        "listener",
        "comment",
        "row",
        "close",
        "relisten",
        "commitments",
    ]
    assert "sandbox-memory.md: link: [[gone]] 沒有這則記憶" in line["reason"]
    again = f"bash tools/ops/take_over.sh term_old --from memory --comment-url {COMMENT_URL}"
    assert again in result.stderr
    record = to.data / "logs" / "take-over-sess-new.json"
    assert record.exists()

    (to.memory / "sandbox-memory.md").write_text("no links\n", encoding="utf-8")
    calls = len(to.calls("gh"))
    again = _take_over(to, "term_old", "--from", "memory", "--comment-url", COMMENT_URL)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _last(again)["done"] == ["memory"]
    assert to.calls("gh")[calls:] == []
    assert not record.exists()


def test_take_over_fails_without_the_memory_directory(to: Harness) -> None:
    result = to.run(
        "take_over.sh",
        "--no-old-terminal",
        CLAUDE_CODE_SESSION_ID="sess-new",
        ORCA_TERMINAL_HANDLE="term_new",
        TMPDIR=to.temp.as_posix(),
        TAKE_OVER_LISTENER_WAIT="0",
        STOCK_MEMORY_DIR=(to.root / "x").as_posix(),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    line = _last(result)
    assert line["failed"] == "memory" and "找不到記憶目錄" in line["reason"]
