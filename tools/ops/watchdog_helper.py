"""Parsing helpers for tools/ops/ensure_coordinator.sh.

Git Bash on the scheduler host has no jq or sqlite3, so the watchdog calls
this module to read JSON, the handoff text and the database; every decision
stays in the shell script. Results go to stdout without a trailing newline.

  ok <json>                        exit 0 when the orca result has "ok": true
  field <json> <key>               a top-level string field ("" when absent)
  find <json> <key>                the first value of <key> anywhere in the tree
  terminal-state <json> <handle>   alive | orphaned | disconnected | missing
  master-worktree <json> <exclude> the id of the master worktree not at <exclude>
  handoff-text <md> [<old handle>] the coordinator handoff text from the manual
  news-llm-pending <db> <n>        how many of the last <n> news_llm batches are
                                   pending in a row, or "skip" without the table
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

HANDOFF_START = "你是 stock-lab 的統籌。"
OLD_HANDLE = "<舊 handle>"


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _find(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        children = list(node.values())
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = _find(child, key)
        if found is not None:
            return found
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path.replace("\\", "/"))).rstrip("\\/")


def terminal_state(data: dict[str, Any], handle: str) -> str:
    for terminal in (data.get("result") or {}).get("terminals") or []:
        if terminal.get("handle") != handle:
            continue
        if terminal.get("orphaned"):
            return "orphaned"
        return "alive" if terminal.get("connected") else "disconnected"
    return "missing"


def master_worktree(data: dict[str, Any], exclude: str) -> str:
    excluded = _norm(exclude)
    for worktree in (data.get("result") or {}).get("worktrees") or []:
        if worktree.get("branch") not in ("refs/heads/master", "master"):
            continue
        if worktree.get("isArchived") or _norm(worktree.get("path") or "") == excluded:
            continue
        return worktree.get("id") or ""
    return ""


def handoff_text(markdown: str, old_handle: str) -> str:
    for block in re.findall(r"^```text\n(.*?)^```", markdown, flags=re.M | re.S):
        text = block.strip()
        if not text.startswith(HANDOFF_START):
            continue
        if old_handle:
            return text.replace(OLD_HANDLE, old_handle)
        # The old terminal is gone: drop the last sentence (closing it).
        body = text[:-1] if text.endswith("。") else text
        return body[: body.rfind("。") + 1]
    raise SystemExit("handoff text not found")


def news_llm_pending(db: str, limit: int) -> str:
    uri = Path(db).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ingestion_runs'"
        ).fetchone():
            return "skip"
        rows = conn.execute(
            "SELECT metadata_json FROM ingestion_runs WHERE run_type='news_llm' ORDER BY id DESC LIMIT 50"
        ).fetchall()
    statuses: list[str] = []
    for (raw,) in rows:
        try:
            metadata = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        batches = (metadata or {}).get("batches") or []
        statuses.extend(str(batch.get("status")) for batch in reversed(batches))
        if len(statuses) >= limit:
            break
    streak = 0
    for status in statuses[:limit]:
        if status != "pending":
            break
        streak += 1
    return str(streak)


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    command, args = argv[0], argv[1:]
    if command == "ok":
        return 0 if _load(args[0]).get("ok") is True else 1
    if command == "field":
        value = _load(args[0]).get(args[1])
        out = value if isinstance(value, str) else ""
    elif command == "find":
        out = _text(_find(_load(args[0]), args[1]))
    elif command == "terminal-state":
        out = terminal_state(_load(args[0]), args[1])
    elif command == "master-worktree":
        out = master_worktree(_load(args[0]), args[1])
    elif command == "handoff-text":
        markdown = Path(args[0]).read_text(encoding="utf-8").replace("\r\n", "\n")
        out = handoff_text(markdown, args[1] if len(args) > 1 else "")
    elif command == "news-llm-pending":
        out = news_llm_pending(args[0], int(args[1]))
    else:
        raise SystemExit(f"unknown command: {command}")
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        AttributeError,
        sqlite3.Error,
    ) as exc:
        print(f"watchdog_helper: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
