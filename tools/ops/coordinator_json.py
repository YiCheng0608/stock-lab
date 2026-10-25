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
"""

from __future__ import annotations

import json
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
