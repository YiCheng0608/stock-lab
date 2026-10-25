"""JSON helper for the coordinator scripts dispatch.sh, close_task.sh and patrol.sh (Issue #282).

Git Bash has no jq, so the scripts pipe orca and gh JSON through this file. Every
subcommand reads one JSON document on stdin and prints plain text; it exits 1 when the
value is missing or the condition is false, so a script can test the exit code.

  get PATH            value at a dotted path (a.b.0.c); objects and lists print as JSON
  ok                  exit 0 when the orca envelope has "ok": true
  satisfied           exit 0 when ok and a "satisfied": true sits anywhere under result
  stages              the send receipt's prompt stages, space separated
  repo-id KEY         id of the orca repo whose remote canonicalKey is KEY
  terminals PATH      "handle agent lastOutputAt" per terminal of the worktree at PATH
  worktrees PREFIX    "path<TAB>branch<TAB>id" per orca worktree on branch refs/heads/PREFIX*
  ci-state SHA        CI state of master: "<state of SHA> <state of the newest run>"
  board               "itemId projectId fieldId optionId=name,..." of project 1 from the
                      issue query (item "-" and the issue node id last when the issue is
                      not on the board)
  prs                 one line per open PR (CI rollup and mergeStateStatus)
  comments            one line per new Issue/PR comment
  utf8 FILE           exit 0 when FILE is non-empty valid UTF-8 (no stdin)
  within A B          "yes" when A is B or under B, else "no" (no stdin)
  guard PATH [--residual] [--home H] [--data D]... [--root R]...
                      why close_task.sh must not delete PATH, or nothing (no stdin)

Paths given to within and guard are native (on Windows, `cygpath -m` of what bash has).
Each is compared in two forms: as written (absolute, normalised) and as the file system
resolves it (os.path.realpath: junctions and symlinks followed, 8.3 short names
expanded), so neither a link in the middle of a path nor a short name hides a
protected directory (#283 review B1, B2).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import PurePosixPath


def _load():
    try:
        return json.load(sys.stdin)
    except ValueError:
        return None


def _walk(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)


def _norm(path: str) -> str:
    """Compare Windows and MSYS spellings of one path: c:\\a\\b, C:/a/b and /c/a/b."""
    p = path.replace("\\", "/").rstrip("/")
    if len(p) > 2 and p[0] == "/" and p[2:3] in ("/", "") and p[1].isalpha():
        p = p[1] + ":" + p[2:]
    return str(PurePosixPath(p)).lower()


def _forms(path: str) -> tuple[str, str]:
    """(as written, as resolved), both case-normalised."""
    written = os.path.normcase(os.path.abspath(path))
    return written, os.path.normcase(os.path.realpath(path))


def _inside(a: str, b: str) -> bool:
    """a is b or under b; both from _forms."""
    a, b = (p if p.endswith(os.sep) else p + os.sep for p in (a, b))
    return a.startswith(b)


def _overlaps(a: str, b: str) -> bool:
    return any(_inside(x, y) or _inside(y, x) for x in _forms(a) for y in _forms(b))


def _has_git_inside(top: str) -> bool:
    """A .git anywhere under top, without entering a junction or symlink."""
    stack = [top]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if entry.name == ".git":
                return True
            if entry.is_junction() or entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
    return False


def guard(
    path: str, residual: bool, home: list[str], data: list[str], roots: list[str]
):
    written, real = _forms(path)
    if written != real:
        return f"經過 junction／symlink 或用了短檔名（實際位置 {real}），請改用實際路徑"
    if "stock-lab-data" in written.replace("\\", "/").split("/"):
        return "在 stock-lab-data 之下"
    for d in data:
        if _overlaps(path, d):
            return f"是資料目錄或與它重疊（{d}）"
    if os.path.dirname(written) == written:
        return "是根目錄或磁碟根目錄"
    for h in home:
        if any(_inside(x, y) for x in _forms(h) for y in _forms(path)):
            return "是 $HOME 或它的上層"
    for r in roots:
        if _overlaps(path, r):
            return f"是 git checkout 或與它重疊（{r}）"
    if residual:
        return ""
    d = real
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return f"位於 git repo 之內（{d}）"
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    if os.path.isdir(real) and _has_git_inside(real):
        return "裡面有 .git"
    return ""


def _guard_args(args: list[str]) -> int:
    path, residual, lists = args[0], False, {"--home": [], "--data": [], "--root": []}
    rest = iter(args[1:])
    for flag in rest:
        if flag == "--residual":
            residual = True
        else:
            lists[flag].append(next(rest))
    print(guard(path, residual, lists["--home"], lists["--data"], lists["--root"]))
    return 0


def get(doc, path: str):
    node = doc
    for part in path.split("."):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _print_value(value) -> int:
    if value is None:
        return 1
    if isinstance(value, bool):
        print("true" if value else "false")
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False))
    else:
        print(value)
    return 0


def _one_line(text: str, width: int = 80) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= width else line[: width - 1] + "…"


def _check_state(rollup) -> str:
    states = [
        (c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
        for c in rollup or []
    ]
    if not states:
        return "none"
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT") for s in states):
        return "failure"
    if any(s in ("", "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED") for s in states):
        return "pending"
    return "success"


def _run_state(run) -> str:
    if run is None:
        return "missing"
    if run.get("status") != "completed":
        return "pending"
    return run.get("conclusion") or "unknown"


def _options(field) -> str:
    return ",".join(
        f"{o['id']}={o['name']}" for o in (field or {}).get("options") or []
    )


def main(argv: list[str]) -> int:
    # Bash reads the output with $(...): no CRLF from a Windows Python.
    sys.stdout.reconfigure(newline="\n")
    if not argv:
        print(__doc__, file=sys.stderr)
        return 64
    command, args = argv[0], argv[1:]
    if command == "utf8":
        try:
            with open(args[0], "rb") as handle:
                text = handle.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return 1
        return 0 if text.strip() else 1
    if command == "within":
        print(
            "yes"
            if any(_inside(a, b) for a in _forms(args[0]) for b in _forms(args[1]))
            else "no"
        )
        return 0
    if command == "guard":
        return _guard_args(args)
    doc = _load()
    if doc is None:
        return 1
    if command == "get":
        return _print_value(get(doc, args[0]))
    if command == "ok":
        return 0 if isinstance(doc, dict) and doc.get("ok") is True else 1
    if command == "satisfied":
        if not (isinstance(doc, dict) and doc.get("ok") is True):
            return 1
        return 0 if any(v is True for v in _walk(doc.get("result"), "satisfied")) else 1
    if command == "stages":
        stages = get(doc, "result.send.prompt.stages") or []
        print(" ".join(str(s) for s in stages))
        return 0
    if command == "repo-id":
        for repo in get(doc, "result.repos") or []:
            if (repo.get("gitRemoteIdentity") or {}).get("canonicalKey") == args[0]:
                print(repo["id"])
                return 0
        return 1
    if command == "terminals":
        want = _norm(args[0])
        for t in get(doc, "result.terminals") or []:
            if _norm(t.get("worktreePath") or "") == want:
                agent = t.get("agentIdentity") or "-"
                print(f"{t['handle']} {agent} {t.get('lastOutputAt') or 0}")
        return 0
    if command == "worktrees":
        prefix = "refs/heads/" + args[0]
        for w in get(doc, "result.worktrees") or []:
            if (w.get("branch") or "").startswith(prefix):
                branch = w["branch"][len("refs/heads/") :]
                print(f"{w['path']}\t{branch}\t{w.get('id', '')}")
        return 0
    if command == "ci-state":
        runs = [r for r in doc if isinstance(r, dict)] if isinstance(doc, list) else []
        mine = next((r for r in runs if r.get("headSha") == args[0]), None)
        newest = runs[0] if runs else None
        print(_run_state(mine), _run_state(newest))
        return 0
    if command == "board":
        issue = get(doc, "data.repository.issue") or {}
        for item in get(issue, "projectItems.nodes") or []:
            project = item.get("project") or {}
            if project.get("number") != 1:
                continue
            field = project.get("field") or {}
            print(item["id"], project["id"], field.get("id", ""), _options(field))
            return 0
        project = get(doc, "data.user.projectV2") or {}
        field = project.get("field") or {}
        print(
            "-",
            project.get("id", ""),
            field.get("id", ""),
            _options(field),
            issue.get("id", ""),
        )
        return 0
    if command == "prs":
        for pr in doc if isinstance(doc, list) else []:
            labels = ",".join(lb["name"] for lb in pr.get("labels") or [])
            draft = " draft" if pr.get("isDraft") else ""
            print(
                f"PR #{pr['number']} ci={_check_state(pr.get('statusCheckRollup'))}"
                f" merge={pr.get('mergeStateStatus') or '?'}{draft}"
                f" labels={labels or '-'} {_one_line(pr.get('title', ''), 50)}"
            )
        return 0
    if command == "comments":
        for c in doc if isinstance(doc, list) else []:
            number = (c.get("issue_url") or "").rsplit("/", 1)[-1]
            print(f"#{number} {c.get('created_at', '')} {_one_line(c.get('body', ''))}")
            print(f"  {c.get('html_url', '')}")
        return 0
    print(f"unknown command: {command}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
