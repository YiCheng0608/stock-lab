"""Check the Claude Code project memory directory (Issue #705); fails, does not report.

The memory directory (MEMORY.md, the index every coordinator and engineer session loads,
and one file per memory) lives outside the repo, under the Claude Code profile, so CI
cannot see it; take_over.sh and close_task.sh run this instead. Four checks:

  index   every list line of MEMORY.md links one existing file of the directory, once;
  orphan  every other entry of the directory is linked from MEMORY.md;
  link    every [[name]] names an existing memory (its frontmatter name, or its file
          name without .md); one in a code span or fenced block is not a link;
  path    a `backticked` string that looks like a repo path exists on <ref> of --repo
          (default origin/master of the management checkout). It looks like one when it
          has a "/" and its first part is a top-level entry of <ref>; strings with spaces,
          < > * { } $ |, "..." or "…" are commands or placeholders and are skipped, and a
          trailing ::<test>, :<line>[-<line>], #<anchor> or "/" (a leading "./") is
          dropped first. A path git ignores (a build output such as frontend/.vite/)
          passes. `<path>@<commit>` (any path with a "/") is checked on that commit
          instead: the way to name a path that has since been removed or renamed. Fenced
          code blocks are skipped. A bare file name (no "/") is not checked: in the
          memories of 2026-11-14 all 5 such names missing from the repo were scratch
          files, MEMORY.md itself or a file named as history (Issue #705).

Where the directory is: --memory-dir, else $STOCK_MEMORY_DIR, else
<$CLAUDE_CONFIG_DIR or ~/.claude>/projects/<slug>/memory, the slug being the main
checkout's path (the parent of --repo's git common dir) with every character other than
A-Z a-z 0-9 turned into "-", as Claude Code names it. A directory that is not there fails.

Usage: memory_check.py [--memory-dir DIR] [--repo DIR] [--ref REF]
Prints one line per failure, "<file>: <check>: <what>", then a summary. Exit 0 all
passed; 1 a check failed; 2 no memory directory, or git could not read --repo.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

INDEX = "MEMORY.md"
INDEX_LINK = re.compile(r"\]\(([^)\s]+)\)")
WIKI_LINK = re.compile(r"\[\[([^\]\n]+)\]\]")
FENCE = re.compile(r"^ {0,3}(```|~~~).*?^ {0,3}\1[^\n]*$", re.M | re.S)
TICK = re.compile(r"`([^`\n]+)`")
NOT_A_PATH = re.compile(r"[\s<>*{}$|]|\.\.\.|…")
TRAILER = re.compile(r"(::.*|:\d+(-\d+)?|#[^/]*)$")
AT_COMMIT = re.compile(r"^(.+)@([0-9a-f]{7,40})$")


class SetupError(Exception):
    """No memory directory, or git cannot answer: nothing was checked."""


def git(
    repo: Path, *args: str, stdin: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotepath=false", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def default_memory_dir(repo: Path) -> Path:
    out = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if out.returncode != 0 or not out.stdout.strip():
        raise SetupError(
            f"讀不到 {repo} 的 git common dir，算不出記憶目錄；用 --memory-dir 或 "
            f"STOCK_MEMORY_DIR 指定（{out.stderr.strip()}）"
        )
    main = Path(out.stdout.strip()).parent.as_posix()
    slug = re.sub(r"[^A-Za-z0-9]", "-", main)
    config = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(config) / "projects" / slug / "memory"


def frontmatter_name(text: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        key, _, value = line.partition(":")
        if key.strip() == "name":
            return value.strip().strip("\"'") or None
    return None


class RepoTree:
    """The files and directories of <ref>, read once, on the first path asked about."""

    def __init__(self, repo: Path, ref: str) -> None:
        self.repo, self.ref = repo, ref
        self.entries: set[str] | None = None
        self.top: set[str] = set()

    def load(self) -> None:
        if self.entries is not None:
            return
        out = git(self.repo, "ls-tree", "-r", "-z", "--name-only", self.ref)
        if out.returncode != 0:
            raise SetupError(
                f"讀不到 {self.repo} 的 {self.ref}（git ls-tree：{out.stderr.strip()}）"
            )
        self.entries = set()
        for name in filter(None, out.stdout.split("\0")):
            parts = name.split("/")
            for i in range(1, len(parts) + 1):
                self.entries.add("/".join(parts[:i]))
            self.top.add(parts[0])

    def looks_like_path(self, path: str) -> bool:
        if "/" not in path:
            return False
        self.load()
        return path.split("/")[0] in self.top

    def missing(self, paths: list[str]) -> set[str]:
        """The paths not on <ref> and not ignored by git."""
        self.load()
        assert self.entries is not None
        absent = sorted({p for p in paths if p not in self.entries})
        if not absent:
            return set()
        # Asked with and without a trailing "/": a pattern such as frontend/.vite/ matches
        # only a directory, and an ignored directory need not exist here.
        asked = [form for p in absent for form in (p, p + "/")]
        out = git(
            self.repo, "check-ignore", "--stdin", "-z", stdin="\0".join(asked) + "\0"
        )
        if out.returncode not in (0, 1):
            raise SetupError(f"git check-ignore 失敗：{out.stderr.strip()}")
        ignored = {form.rstrip("/") for form in out.stdout.split("\0") if form}
        return set(absent) - ignored

    def on_commit(self, path: str, commit: str) -> bool:
        return git(self.repo, "cat-file", "-e", f"{commit}:{path}").returncode == 0


def path_candidate(text: str) -> str | None:
    """The repo-relative path a backticked string names, or None when it names none."""
    text = text.strip()
    if NOT_A_PATH.search(text):
        return None
    path = TRAILER.sub("", text).rstrip("/")
    if path.startswith("./"):
        path = path[2:]
    return path or None


def check(memory: Path, repo: Path, ref: str) -> tuple[list[str], int]:
    """Failures as "<file>: <check>: <what>", and the number of memories."""
    if not memory.is_dir():
        raise SetupError(
            f"找不到記憶目錄：{memory.as_posix()}（--memory-dir 或 STOCK_MEMORY_DIR）"
        )
    failures: list[str] = []
    index_path = memory / INDEX
    if not index_path.is_file():
        return [f"{INDEX}: index: 記憶目錄 {memory.as_posix()} 沒有 {INDEX}"], 0
    index_text = index_path.read_text(encoding="utf-8")

    indexed: dict[str, int] = {}
    for number, line in enumerate(index_text.splitlines(), 1):
        if not line.lstrip().startswith(("- ", "* ")):
            continue
        targets = INDEX_LINK.findall(line)
        where = f"{INDEX}:{number}: index"
        if len(targets) != 1:
            failures.append(
                f"{where}: 一列要剛好連到一個記憶檔，這列有 {len(targets)} 個連結"
            )
            continue
        target = targets[0]
        if (
            "/" in target
            or "\\" in target
            or not target.endswith(".md")
            or target == INDEX
        ):
            failures.append(f"{where}: 連結 {target} 不是記憶目錄裡的 .md 檔名")
        elif not (memory / target).is_file():
            failures.append(f"{where}: {target} 不存在")
        elif target in indexed:
            failures.append(f"{where}: {target} 在第 {indexed[target]} 列已列過")
        else:
            indexed[target] = number

    for entry in sorted(memory.iterdir(), key=lambda p: p.name):
        if entry.name != INDEX and entry.name not in indexed:
            failures.append(f"{entry.name}: orphan: 不在 {INDEX} 的索引裡")

    files = sorted(p for p in memory.glob("*.md") if p.is_file())
    texts = {p.name: p.read_text(encoding="utf-8") for p in files}
    names = {p.name[:-3] for p in files if p.name != INDEX}
    names |= {
        n for name, t in texts.items() if name != INDEX and (n := frontmatter_name(t))
    }

    tree = RepoTree(repo, ref)
    for name, text in texts.items():
        text = FENCE.sub("", text)
        # A [[name]] inside a code span is an example or data, not a link.
        for target in WIKI_LINK.findall(TICK.sub("", text)):
            if target.strip() not in names:
                failures.append(f"{name}: link: [[{target}]] 沒有這則記憶")
        plain: list[str] = []
        dated: list[tuple[str, str]] = []
        for raw in TICK.findall(text):
            path = path_candidate(raw)
            if path is None:
                continue
            at = AT_COMMIT.match(path)
            if at:
                # Named as a path of that commit: its top-level directory may be gone.
                if "/" in at.group(1):
                    dated.append((at.group(1), at.group(2)))
            elif tree.looks_like_path(path):
                plain.append(path)
        failures.extend(
            f"{name}: path: `{path}` 不在 {ref}（已刪或改名就改成現行路徑，"
            f"要留歷史就寫 `{path}@<commit>`）"
            for path in sorted(tree.missing(plain))
        )
        failures.extend(
            f"{name}: path: `{path}@{commit}` 不在 {commit}"
            for path, commit in sorted(set(dated))
            if not tree.on_commit(path, commit)
        )
    return failures, len(files) - (INDEX in texts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--memory-dir")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--ref", default="origin/master")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    try:
        given = args.memory_dir or os.environ.get("STOCK_MEMORY_DIR")
        memory = Path(given) if given else default_memory_dir(repo)
        failures, count = check(memory, repo, args.ref)
    except SetupError as error:
        print(f"memory_check: {error}", file=sys.stderr)
        return 2
    for failure in failures:
        print(f"memory_check: {failure}")
    if failures:
        print(f"memory_check: 失敗 {len(failures)} 項（{memory.as_posix()}）")
        return 1
    print(f"memory_check: 通過（{count} 則記憶，{memory.as_posix()}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
