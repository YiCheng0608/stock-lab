"""Context and token cost of a Claude Code session, read from its transcript (#710, #708).

Four subcommands, all read-only:

  context (--session-id ID | --transcript PATH)
      The context of the session's last model call (input + cache read + cache write
      tokens of the last assistant row that is not a sidechain, not <synthetic> and has a
      usage), for patrol.sh's handoff condition (docs/COORDINATOR.md 自動換手機制).
      Prints one line "<tokens> <path>" and exits 0; when the context cannot be read,
      one line with the reason and exits 3 (no transcript found) or 4 (no usable row,
      or the file cannot be read).

  compactions (--session-id ID | --transcript PATH)
      The compactions of the session's main conversation (#811): the compact_boundary
      rows of its transcript that are not a sidechain. A subagent's compactions are in
      <session id>/subagents/, not read (the PreCompact hook gets the parent's session
      id for them, so its count has them too). Prints "<count> <path>" and exits 0;
      exits 3 (no transcript found) or 4 (the file cannot be read, or no line of it is
      a JSON object) with one line saying why, as context does.

  report ID_OR_PATH...
      For each session (a session id, an id prefix of 8 or more characters, or a
      transcript path): total cost units (input 1, cache read 0.1, cache write 2,
      output 5), the patrol wakes and their average cost, the wakes with no outward
      action, the first and the largest context, the compactions; the outward actions
      (ACTION matches, each match in a command counted) and the cost per action, the
      average cost and context per call, and the context of the first call after each
      compaction (#711 AC-6). #708's sub-tasks use it to show the numbers before and
      after a change.

  takeover ID_OR_PATH...
      For each coordinator session (#803): the context of the first call, of the call
      after the take_over.sh result that printed "ok":true (a failed run continued with
      --from is the 2nd or a later run; --closed-only runs are not counted), and of the
      call after the first patrol.sh result after that (not --heartbeat-only; one in the
      same command or batch of results as that run makes the 3rd point the 2nd).
      From the first call to the 3rd point, the tool results by group (each repo file
      read, #1, other Issues and PRs, take_over.sh, patrol.sh, other commands; a file
      a command wrote or Claude Code
      saved a long output to counts as that command's) with their bytes and the context
      they added, the coordinator's own output, and bytes per token. What a call adds is
      the next call's context minus its own: its output tokens (at most that) are its
      own output, the rest is shared by the tool results in between in proportion to
      their bytes. A point not found: one line saying which, no numbers, exit 5.

report and takeover read a transcript still being written with undecodable bytes
replaced (a line cut inside a character is then not JSON and skipped).

A transcript is found under $CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl first, then
$HOME/.claude/projects/*/<id>.jsonl; several files for one id: the last modified one.
STOCK_TRANSCRIPT, like --transcript, names the file directly (context and compactions).
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


def transcript_of(args: list[str]) -> tuple[Path | None, int]:
    """The transcript --session-id or --transcript (or STOCK_TRANSCRIPT) names, for
    context and compactions; None and the exit code after printing why."""
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
            return None, 64
    path = path or os.environ.get("STOCK_TRANSCRIPT") or None
    if path:
        transcript = Path(path)
        if not transcript.is_file():
            print(f"找不到紀錄檔（{transcript.as_posix()}）")
            return None, 3
        return transcript, 0
    if session:
        found, looked = find(session)
        if found is None:
            where = "、".join(f"{r.as_posix()}/*/{session}.jsonl" for r in looked)
            print(f"找不到紀錄檔（找過 {where}）")
            return None, 3
        return found, 0
    print("要給 --session-id 或 --transcript")
    return None, 64


def cmd_context(args: list[str]) -> int:
    transcript, code = transcript_of(args)
    if transcript is None:
        return code
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


def main_compactions(path: Path) -> int | None:
    """The compact_boundary rows not a sidechain; None when no line is a JSON object
    (not a transcript). Only the lines naming compact_boundary are parsed."""
    count = 0
    understood = False
    with open(path, "rb") as f:
        for raw in f:
            if not understood or b"compact_boundary" in raw:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                understood = True
                if (
                    row.get("type") == "system"
                    and row.get("subtype") == "compact_boundary"
                    and not row.get("isSidechain")
                ):
                    count += 1
    return count if understood else None


def cmd_compactions(args: list[str]) -> int:
    transcript, code = transcript_of(args)
    if transcript is None:
        return code
    try:
        n = main_compactions(transcript)
    except OSError as e:
        print(f"讀檔失敗（{transcript.as_posix()}：{e.strerror or e}）")
        return 4
    if n is None:
        print(f"沒有 JSON 列（{transcript.as_posix()}）")
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
    n_calls = 0
    with open(path, encoding="utf-8", errors="replace") as f:
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
                    {
                        "at": row.get("timestamp"),
                        "pre": meta.get("preTokens"),
                        "after": n_calls,  # index of the first call after it
                    }
                )
            # A scheduled task (/loop, cron) starts a turn of its own, not a wake's.
            if kind == "system" and row.get("subtype") == "scheduled_task_fire":
                cur = {"wake": False, "calls": [], "commands": []}
                turns.append(cur)
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
                        n_calls += 1
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
    actions = sum(len(ACTION.findall(c)) for t in turns for c in t["commands"])
    after = [
        f"{ctx[c['after']]:,}" if c["after"] < len(calls) else "（還沒有呼叫）"
        for c in compactions
    ]

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
        f"每次呼叫：平均成本 {total / len(calls):,.0f}、平均 context "
        f"{sum(ctx) / len(calls):,.0f}",
        f"對外動作：{actions} 個、每個動作成本 "
        + (f"{total / actions:,.0f}" if actions else "—"),
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
    if compactions:
        lines.append("壓縮後第 1 次呼叫 context：" + "、".join(after))
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


# takeover (#803). A run of an ops script: "bash <path>/take_over.sh", or the path at
# the start of a command; not a grep or sed that names the file.
RUNS = (
    r"(?:(?:^|[;&|(\n])\s*|(?<![^\s;&|(])(?:bash|sh)\s+)"
    r"(?:[\w.:/-]*/)?{}(?=\s|$|[;&|)])"
)
TAKE_OVER = re.compile(RUNS.format(r"take_over\.sh"))
PATROL = re.compile(RUNS.format(r"patrol\.sh"))
TAKE_OVER_OK = re.compile(r'\{"ok":\s*true\b')
ISSUE_1 = re.compile(
    r"gh issue view\s+(?:-R\s+\S+\s+)?#?1\b(?!\d)|issue\(number:\s*1\)|/issues/1(?:/|\b)(?!\d)"
)
GITHUB = re.compile(r"\bgh\s+(?:issue|pr|api|search)\b")
SHOW = re.compile(r"^(?:cat|head|tail|sed|nl|less)\b")
SAVED = re.compile(r"Full output saved to: (.+?)\s*$", re.M)
WRITES = re.compile(r"""(?:>>?|\btee(?:\s+-a)?)\s+("[^"]+"|'[^']+'|[^\s;&|<>]+)""")
CD = re.compile(r"""^cd\s+("[^"]+"|'[^']+'|\S+)\s*&&\s*""")
OWN = "統籌自己的輸出"
OTHER = "其他（提示、附件）"


def norm(path: str) -> str:
    """A path as a key: quotes off, / separators, MSYS /c/ as C:/, lower case."""
    p = path.strip().strip("\"'").replace("\\", "/")
    if m := re.match(r"^/([a-zA-Z])/", p):
        p = f"{m.group(1)}:/{p[3:]}"
    return p.lower()


def result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else ""
        for b in content or []
    )


def file_group(path: str, cwd: str, saved: dict[str, str]) -> str:
    key = norm(path)
    if key in saved:
        return saved[key]
    shown = path.strip().strip("\"'").replace("\\", "/")
    root = norm(cwd).rstrip("/") + "/" if cwd else ""
    if root and key.startswith(root):
        return "讀檔：" + shown[len(root) :]
    # A relative path is the repo's (the session's cwd).
    if not re.match(r"^(?:[a-z]:)?/|^~", key):
        return "讀檔：" + re.sub(r"^\./", "", shown)
    return "讀 repo 外的檔：" + shown.split("/")[-1]


def command_group(command: str, cwd: str, saved: dict[str, str]) -> str:
    if TAKE_OVER.search(command):
        return "take_over.sh 輸出"
    if PATROL.search(command):
        return "patrol.sh 輸出"
    if ISSUE_1.search(command):
        return "讀 #1"
    if GITHUB.search(command):
        return "讀其他 Issue／PR"
    # A command that only shows one file (cat, sed -n, head ...; cd, echo, wc beside).
    shown = set()
    for part in re.split(r"&&|\|\|?|;|\n", command):
        part = CD.sub("", part.strip())
        if not part or re.match(r"^(?:cd|echo|wc|date)\b", part):
            continue
        if not SHOW.match(part):
            return "其他命令"
        args = [a for a in part.split()[1:] if not a.startswith("-")]
        if part.startswith("sed") and args:
            args = args[1:]  # the sed script
        shown.update(a for a in args if not re.fullmatch(r"\d+", a))
    if len(shown) == 1:
        return file_group(shown.pop(), cwd, saved)
    return "其他命令"


def takeover(path: Path) -> tuple[list[str], bool]:
    """The context at the 3 points of a coordinator's take over, and what the tool
    results between the first call and the 3rd point added (#803)."""
    calls: list[dict] = []  # each model call: its context, output and what it added
    by_id: dict[str, dict] = {}
    uses: dict[str, tuple[str, str]] = {}  # tool_use id -> (group, kind)
    saved: dict[str, str] = {}  # file written by a command (or a saved output) -> group
    runs: list[dict] = []  # take_over.sh results
    point2 = point3 = None  # index of the call right after that tool result
    pending: list[tuple[str, int]] = []  # tool results since the last call
    waiting2 = waiting3 = False
    with open(path, encoding="utf-8", errors="replace") as f:
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
            cwd = row.get("cwd") or ""
            if kind == "assistant":
                mid = message.get("id")
                n = usage_context(row)
                call = by_id.get(mid) if mid else None
                if call is None and n is not None:
                    usage = message["usage"]
                    call = {
                        "ctx": n,
                        "out": usage.get("output_tokens") or 0,
                        "own": 0,
                        "added": pending,
                        "at": row.get("timestamp"),
                    }
                    pending = []
                    calls.append(call)
                    if mid:
                        by_id[mid] = call
                    if waiting2:
                        point2, waiting2 = len(calls) - 1, False
                    if waiting3:
                        point3, waiting3 = len(calls) - 1, False
                elif call is not None and n is not None:
                    call["out"] = message["usage"].get("output_tokens") or 0
                for b in content or []:
                    if not isinstance(b, dict):
                        continue
                    if call is not None:
                        text = b.get("text") or b.get("thinking") or ""
                        if b.get("type") == "tool_use":
                            text = json.dumps(b.get("input"), ensure_ascii=False)
                        call["own"] += len(text.encode())
                    if b.get("type") != "tool_use":
                        continue
                    i = b.get("input") or {}
                    command = i.get("command")
                    if isinstance(command, str):
                        group = command_group(command, cwd, saved)
                        for target in WRITES.findall(command):
                            if norm(target) not in ("/dev/null", "&1", "&2"):
                                saved[norm(target)] = group
                    elif b.get("name") == "Read" and i.get("file_path"):
                        group = file_group(str(i["file_path"]), cwd, saved)
                    else:
                        group = f"其他工具：{b.get('name')}"
                    uses[b.get("id")] = (
                        group,
                        command if isinstance(command, str) else "",
                    )
            elif kind == "user" and isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    text = result_text(b.get("content"))
                    group, command = uses.get(b.get("tool_use_id"), ("其他工具：?", ""))
                    for target in SAVED.findall(text):
                        saved[norm(target)] = group
                    pending.append((group, len(text.encode())))
                    if point2 is None and not waiting2 and TAKE_OVER.search(command):
                        if "--closed-only" not in command:
                            runs.append({"ok": bool(TAKE_OVER_OK.search(text))})
                            waiting2 = runs[-1]["ok"]
                    # A patrol.sh in the same command as the ok run, or in the same
                    # batch of results before the next call: the 3rd point is the 2nd.
                    if (
                        (point2 is not None or waiting2)
                        and point3 is None
                        and not waiting3
                        and PATROL.search(command)
                        and "--heartbeat-only" not in command
                    ):
                        waiting3 = True
    head = f"== {path.stem[:8]}（{path.as_posix()}）"
    if not calls:
        return [head, "沒有 usage 列"], False
    missing = []
    if not runs:
        missing.append("找不到 take_over.sh 的工具結果")
    elif point2 is None and not waiting2:
        missing.append(f'take_over.sh 執行 {len(runs)} 次，沒有一次印出 "ok":true')
    elif point2 is None:
        missing.append("take_over.sh 之後還沒有呼叫")
    elif point3 is None and not waiting3:
        missing.append("找不到 take_over.sh 之後的 patrol.sh 工具結果")
    elif point3 is None:
        missing.append("patrol.sh 之後還沒有呼叫")
    if missing:
        return [head, *missing], False
    ctx = [c["ctx"] for c in calls]
    nth = next(i for i, r in enumerate(runs) if r["ok"]) + 1
    lines = [
        head,
        f"接手時間：{calls[0]['at']}（第 1 次呼叫）",
        f"context：第 1 次呼叫 {ctx[0]:,}、take_over.sh 之後 {ctx[point2]:,}"
        f'（第 {nth} 次執行、印出 "ok":true；共執行 {len(runs)} 次）、'
        f"patrol.sh 之後 {ctx[point3]:,}",
        f"增量：第 1 次呼叫 → take_over.sh {ctx[point2] - ctx[0]:,}、"
        f"take_over.sh → patrol.sh {ctx[point3] - ctx[point2]:,}、"
        f"合計 {ctx[point3] - ctx[0]:,}",
    ]
    # What each call added: its own output (its output tokens, at most the increment),
    # the rest shared by the tool results before the next call in proportion to their
    # bytes; with no tool result, it is the prompts and attachments.
    groups: dict[str, list[float]] = {}

    def add(group: str, size: int, tokens: float) -> None:
        g = groups.setdefault(group, [0, 0.0])
        g[0] += size
        g[1] += tokens

    for k in range(point3):
        delta = max(0, ctx[k + 1] - ctx[k])
        own = min(calls[k]["out"], delta)
        add(OWN, calls[k]["own"], own)
        added = calls[k + 1]["added"]
        total = sum(size for _, size in added)
        if total:
            for group, size in added:
                add(group, size, (delta - own) * size / total)
        else:
            add(OTHER, 0, delta - own)

    def ratio(size: float, tokens: float) -> str:
        return f"{size / tokens:.2f}" if size and tokens >= 1 else "—"

    lines.append(
        "分組（第 1 次呼叫到 patrol.sh 之後；位元組、context 增量、位元組／token）："
    )
    order = sorted(groups, key=lambda g: (g in (OWN, OTHER), -groups[g][1]))
    for group in order:
        size, tokens = groups[group]
        lines.append(f"  {group}：{size:,} B、{tokens:,.0f}、{ratio(size, tokens)}")
    tool = [groups[g] for g in groups if g not in (OWN, OTHER)]
    size = sum(g[0] for g in tool)
    tokens = sum(g[1] for g in tool)
    repo = [groups[g] for g in groups if g.startswith("讀檔：")]
    lines.append(
        f"位元組／token：工具結果 {size:,} B ÷ {tokens:,.0f} = {ratio(size, tokens)}"
        + (
            f"；其中讀 repo 檔案 {ratio(sum(g[0] for g in repo), sum(g[1] for g in repo))}"
            if repo
            else ""
        )
    )
    return lines, True


def cmd_takeover(args: list[str]) -> int:
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
            lines, ok = takeover(path)
        except OSError as e:
            print(f"{arg}：讀檔失敗（{e}）")
            code = 4
            continue
        print("\n".join(lines))
        if not ok:
            code = code or 5
    return code


def main(argv: list[str]) -> int:
    commands = {
        "context": cmd_context,
        "compactions": cmd_compactions,
        "report": cmd_report,
        "takeover": cmd_takeover,
    }
    if not argv or argv[0] not in commands:
        print(__doc__.strip())
        return 64
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
