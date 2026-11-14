"""Context and token cost of a Claude Code session, read from its transcript (#710, #708).

Two subcommands, both read-only:

  context (--session-id ID | --transcript PATH)
      The context of the session's last model call (input + cache read + cache write
      tokens of the last assistant row that is not a sidechain, not <synthetic> and has a
      usage), for patrol.sh's handoff condition (docs/COORDINATOR.md 自動換手機制).
      Prints one line "<tokens> <path>" and exits 0; when the context cannot be read,
      one line with the reason and exits 3 (no transcript found) or 4 (no usable row,
      or the file cannot be read).

  report ID_OR_PATH...
      For each session (a session id, an id prefix of 8 or more characters, or a
      transcript path): total cost units (input 1, cache read 0.1, cache write 2,
      output 5), the patrol wakes and their average cost, the wakes with no outward
      action, the first and the largest context, the compactions. #708's sub-tasks use
      it to show the numbers before and after a change.

A transcript is found under $CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl first, then
$HOME/.claude/projects/*/<id>.jsonl; several files for one id: the last modified one.
STOCK_TRANSCRIPT, like --transcript, names the file directly (context only).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

UNIT = {"in": 1.0, "cr": 0.1, "cw": 2.0, "out": 5.0}
# A patrol wake: the text monitor.sh and wake_listener.py send (有 N 個事件，請處理佇列…).
WAKE = "個事件，請處理佇列"
# Commands that act outside the session: GitHub, Orca terminals, the ops scripts that
# write, git push, docker (t708 review classify.py, the one #708's numbers come from).
ACTION = re.compile(
    r"gh pr merge|dispatch\.sh|comment\.sh|close_task\.sh|deploy\.sh|commit\.sh (?:add|done)"
    r"|orca terminal (?:send|create|close)|update-branch"
    r"|gh issue (?:create|close|edit|comment)|gh pr (?:comment|review|close|edit|create)"
    r"|git push|git tag|gh run rerun|docker (?:compose|start|stop|restart|rm)"
)


def roots() -> list[Path]:
    out = []
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    if config:
        out.append(Path(config) / "projects")
    home = os.environ.get("HOME") or str(Path.home())
    out.append(Path(home) / ".claude" / "projects")
    return out


def find(session: str, prefix: bool = False) -> tuple[Path | None, list[Path]]:
    """The transcript of a session id (an id prefix with prefix=True), and the
    directories looked in. Several files: the last modified one; on a tie, the one in
    the directory looked in first."""
    looked = roots()
    hits = []
    for rank, root in enumerate(looked):
        if root.is_dir():
            pattern = f"*/{session}*.jsonl" if prefix else f"*/{session}.jsonl"
            hits += [
                (p.stat().st_mtime, -rank, p) for p in root.glob(pattern) if p.is_file()
            ]
    return (max(hits)[2] if hits else None), looked


def usage_context(row: dict) -> int | None:
    if row.get("type") != "assistant" or row.get("isSidechain"):
        return None
    message = row.get("message") or {}
    usage = message.get("usage")
    if not isinstance(usage, dict) or message.get("model") == "<synthetic>":
        return None
    try:
        return int(
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
    except (TypeError, ValueError):
        return None


def last_context(path: Path) -> int | None:
    """The context of the last usable row, reading the file from its end: a line being
    written (no newline yet, not JSON) is skipped."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        size = 1 << 20
        while True:
            start = max(0, end - size)
            f.seek(start)
            lines = f.read(end - start).split(b"\n")
            if start > 0:
                lines = lines[1:]  # cut at an arbitrary byte: the first line is partial
            for raw in reversed(lines):
                if b'"assistant"' not in raw:
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(row, dict) and (n := usage_context(row)) is not None:
                    return n
            if start == 0:
                return None
            size *= 4


def cmd_context(args: list[str]) -> int:
    session = path = None
    while args:
        if args[0] in ("--session-id", "--transcript") and len(args) >= 2:
            if args[0] == "--session-id":
                session = args[1]
            else:
                path = args[1]
            args = args[2:]
        else:
            print(f"未知參數：{args[0]}")
            return 64
    path = path or os.environ.get("STOCK_TRANSCRIPT") or None
    if path:
        transcript = Path(path)
        if not transcript.is_file():
            print(f"找不到紀錄檔（{transcript.as_posix()}）")
            return 3
    elif session:
        found, looked = find(session)
        if found is None:
            where = "、".join(f"{r.as_posix()}/*/{session}.jsonl" for r in looked)
            print(f"找不到紀錄檔（找過 {where}）")
            return 3
        transcript = found
    else:
        print("要給 --session-id 或 --transcript")
        return 64
    try:
        n = last_context(transcript)
    except OSError as e:
        print(f"讀檔失敗（{transcript.as_posix()}：{e.strerror or e}）")
        return 4
    if n is None:
        print(f"沒有 usage 列（{transcript.as_posix()}）")
        return 4
    print(n, transcript.as_posix())
    return 0


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "")
        for b in content or []
        if isinstance(b, dict) and b.get("type") == "text"
    )


def turns_of(path: Path) -> tuple[list[dict], list[dict]]:
    """The session's turns (a prompt and the model calls up to the next one) and its
    compactions. One API message can be written as several rows: the last row's usage
    counts, once."""
    turns: list[dict] = []
    compactions: list[dict] = []
    by_id: dict[str, dict] = {}
    cur = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("isSidechain"):
                continue
            kind = row.get("type")
            message = row.get("message") or {}
            content = message.get("content")
            if kind == "system" and row.get("subtype") == "compact_boundary":
                meta = row.get("compactMetadata") or {}
                compactions.append(
                    {"at": row.get("timestamp"), "pre": meta.get("preTokens")}
                )
            if kind == "user":
                results = isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
                text = text_of(content)
                if not results and text.strip() and not row.get("isMeta"):
                    cur = {
                        "wake": WAKE in text[:60],
                        "calls": [],
                        "commands": [],
                    }
                    turns.append(cur)
            if kind == "assistant" and cur is not None:
                for b in content or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        i = b.get("input") or {}
                        cur["commands"].append(
                            str(i.get("command") or json.dumps(i, ensure_ascii=False))
                        )
                usage = message.get("usage")
                if isinstance(usage, dict) and message.get("model") != "<synthetic>":
                    rec = {
                        "in": usage.get("input_tokens") or 0,
                        "cr": usage.get("cache_read_input_tokens") or 0,
                        "cw": usage.get("cache_creation_input_tokens") or 0,
                        "out": usage.get("output_tokens") or 0,
                    }
                    mid = message.get("id")
                    if mid and mid in by_id:
                        by_id[mid].update(rec)
                    else:
                        cur["calls"].append(rec)
                        if mid:
                            by_id[mid] = rec
    return turns, compactions


def cost(call: dict) -> float:
    return sum(UNIT[k] * call[k] for k in UNIT)


def report(path: Path) -> list[str]:
    turns, compactions = turns_of(path)
    calls = [c for t in turns for c in t["calls"]]
    if not calls:
        return [f"{path.stem[:8]}：沒有 usage 列（{path.as_posix()}）"]
    total = sum(cost(c) for c in calls)
    ctx = [c["in"] + c["cr"] + c["cw"] for c in calls]
    wakes = [t for t in turns if t["wake"]]
    quiet = [t for t in wakes if not any(ACTION.search(c) for c in t["commands"])]
    wake_cost = sum(cost(c) for t in wakes for c in t["calls"])
    quiet_cost = sum(cost(c) for t in quiet for c in t["calls"])
    tokens = {k: sum(c[k] for c in calls) for k in UNIT}

    def pct(x: float, y: float) -> str:
        return f"{100 * x / y:.1f}%" if y else "—"

    lines = [
        f"== {path.stem[:8]}（{path.as_posix()}）",
        f"總成本單位：{total:,.0f}（呼叫 {len(calls)} 次；input {tokens['in']:,}、"
        f"cache 讀 {tokens['cr']:,}（{pct(UNIT['cr'] * tokens['cr'], total)}）、"
        f"cache 寫 {tokens['cw']:,}（{pct(UNIT['cw'] * tokens['cw'], total)}）、"
        f"輸出 {tokens['out']:,}（{pct(UNIT['out'] * tokens['out'], total)}））",
        f"context：第 1 次呼叫 {ctx[0]:,}、最大 {max(ctx):,}、最後 {ctx[-1]:,}；"
        f"400K 以上的呼叫 {sum(1 for x in ctx if x >= 400_000)} 次、成本 "
        f"{pct(sum(cost(c) for c, x in zip(calls, ctx) if x >= 400_000), total)}",
    ]
    if wakes:
        n_calls = sum(len(t["calls"]) for t in wakes)
        lines += [
            f"喚醒：{len(wakes)} 次、平均成本 {wake_cost / len(wakes):,.0f}／次、"
            f"平均呼叫 {n_calls / len(wakes):.1f} 次、佔總成本 {pct(wake_cost, total)}",
            f"沒有對外動作的喚醒：{len(quiet)}／{len(wakes)}（{pct(len(quiet), len(wakes))}）、"
            f"佔總成本 {pct(quiet_cost, total)}",
        ]
    else:
        lines.append("喚醒：0 次")
    lines.append(
        f"壓縮：{len(compactions)} 次"
        + "".join(
            f"；{c['at']} 壓縮前 {c['pre']:,}"
            for c in compactions
            if isinstance(c.get("pre"), int)
        )
    )
    return lines


def cmd_report(args: list[str]) -> int:
    if not args:
        print("要給 session id 或紀錄檔路徑")
        return 64
    code = 0
    for arg in args:
        path = Path(arg)
        if not path.is_file():
            found, _ = (
                find(arg, prefix=True)
                if re.fullmatch(r"[A-Za-z0-9_-]{8,}", arg)
                else (None, [])
            )
            if found is None:
                print(f"{arg}：找不到紀錄檔")
                code = 3
                continue
            path = found
        try:
            print("\n".join(report(path)))
        except OSError as e:
            print(f"{arg}：讀檔失敗（{e}）")
            code = 4
    return code


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("context", "report"):
        print(__doc__.strip())
        return 64
    return (cmd_context if argv[0] == "context" else cmd_report)(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
