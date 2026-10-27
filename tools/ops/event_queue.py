"""Event queue of the coordinator's event monitor (Issue #316).

monitor.sh polls GitHub (open PRs, new comments) and Orca (task worktrees), and hands
the answers to ``record``, which also reads the job logs, turns everything into events,
drops the ones already queued and appends the rest. The coordinator reads the queue
through patrol.sh and marks what it handled with ``done``. Nothing here calls gh, orca
or an LLM: the shell scripts do, so the tests can fake them on PATH.

Files, all in <data>/logs/, each with a single writer:

  events.jsonl            monitor.sh; one JSON object per line, appended:
    {"type": "event", "seq", "id", "kind", "detected_at", "at", "ref", "summary", "url"}
        a new event. ``id`` is the dedup key: one PR's CI result on one head commit and
        one set of check jobs, one comment id, one end line of a job log. ``seq`` counts
        up from 1. ``at`` is the source's own time (or null).
    {"type": "wake", "at", "ok", "terminal", "upto", "detail"}
        the coordinator terminal was sent "有 N 個事件…" (ok) or the send failed; a
        successful wake covers every event up to seq ``upto``.
    {"type": "stale", "at", "key", "url"}
        the #1 comment asking the user to open a coordinator; one per ``key``.
  events-done.jsonl       patrol.sh --done: {"type": "done", "at", "session_id", "ids"}
  monitor-state.json      monitor.sh: comment cursor, last poll, open PR snapshot
  monitor-heartbeat.json  monitor.sh, every poll: {"written_at", "pid", "mode", "gh_calls"}

A line that cannot be read (a partial last line) is skipped. Times are UTC ISO
(2026-10-28T01:23:45Z); NOW is epoch seconds.

Subcommands (LOGS is <data>/logs):
  since LOGS NOW                  the comment cursor to poll with
  stale LOGS NOW [--record-only]  "KEY<TAB>BODY" when the #1 comment is due, else nothing
  record LOGS NOW [--prs F] [--comments F] [--worktrees F]
                                  append the new events and print
                                  "new=N pending=P unnotified=U wake=0|1 terminal=H"
  note-wake LOGS NOW OK TERMINAL DETAIL     OK is 1 or 0
  note-stale LOGS NOW KEY URL     URL "-" in record-only mode: kept in the state only
  beat LOGS NOW MODE GH_CALLS PID
  pending LOGS                    the events not done yet
  status LOGS NOW                 the monitor's heartbeat and its last open PR snapshot
  done LOGS NOW SESSION X...      mark done; X is an event id, or a seq for every pending
                                  event up to it
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from coordinator_json import check_state, latest_checks, one_line, pr_line

EVENTS = "events.jsonl"
DONE = "events-done.jsonl"
STATE = "monitor-state.json"
BEAT = "monitor-heartbeat.json"
COORDINATOR_HEARTBEAT = "coordinator-heartbeat.json"

# The first poll looks this far back; later polls start from the cursor.
FIRST_LOOK_BACK = 3600
# GitHub's since= is on updated_at; the overlap catches a comment indexed late.
CURSOR_OVERLAP = 60
# A failed wake is tried again after this long, not on every poll.
WAKE_RETRY = 600
# No coordinator heartbeat since an event arrived this long ago: ask the user on #1
# (the handbook's 60-minute liveness window; the monitor never opens a session).
STALE_AFTER = 3600
SLOTS = 3
MERGE_STATES = ("CLEAN", "DIRTY", "BEHIND", "UNSTABLE")
JOB_FILES = 2  # newest log files read per job
END_LINE = re.compile(r"^===== (\S+) end (.*)$")


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def epoch(text) -> float | None:
    """Seconds of an ISO time: Z or an offset, up to 7 fraction digits (PowerShell)."""
    if not isinstance(text, str):
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", text.strip()).replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _lines(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _append(path: Path, items: list[dict]) -> None:
    if not items:
        return
    text = "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, value) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Queue:
    def __init__(self, logs: Path) -> None:
        self.logs = logs
        records = _lines(logs / EVENTS)
        self.events = [r for r in records if r.get("type") == "event"]
        self.wakes = [r for r in records if r.get("type") == "wake"]
        self.stales = {r.get("key") for r in records if r.get("type") == "stale"}
        self.ids = {e.get("id") for e in self.events}
        self.done = {
            i
            for r in _lines(logs / DONE)
            if r.get("type") == "done"
            for i in r.get("ids") or []
        }
        state = _read_json(logs / STATE)
        self.state = state if isinstance(state, dict) else {}

    @property
    def seq(self) -> int:
        return max((e.get("seq") or 0 for e in self.events), default=0)

    def pending(self) -> list[dict]:
        return [e for e in self.events if e.get("id") not in self.done]

    def notified_upto(self) -> int:
        return max((w.get("upto") or 0 for w in self.wakes if w.get("ok")), default=0)

    def origin(self, now: float) -> str:
        return self.state.get("origin") or iso(now - FIRST_LOOK_BACK)

    def save_state(self, **changes) -> None:
        self.state.update(changes)
        _write_json(self.logs / STATE, self.state)


def _heartbeat(logs: Path) -> tuple[str, float | None, str]:
    """(terminal handle, written_at seconds, written_at text) of the coordinator."""
    beat = _read_json(logs / COORDINATOR_HEARTBEAT)
    if not isinstance(beat, dict):
        return "", None, ""
    handle = beat.get("terminal_handle")
    handle = (
        handle if isinstance(handle, str) and re.fullmatch(r"[\w-]+", handle) else ""
    )
    at = beat.get("written_at") if isinstance(beat.get("written_at"), str) else ""
    return handle, epoch(at), at


def _short(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


# --- events from each source -------------------------------------------------------


def pr_events(prs: list, previous: list) -> list[dict]:
    """Opened, CI result, merge state, gone. CI is keyed by head commit and check jobs:
    a re-run is a new job, so it is a new event; the same run polled again is not."""
    out = []
    seen = set()
    for pr in prs:
        if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
            continue
        n = pr["number"]
        seen.add(n)
        ref, url = f"PR #{n}", pr.get("url") or ""
        sha = (pr.get("headRefOid") or "")[:12] or "-"
        title = one_line(pr.get("title") or "", 50)
        out.append(_event(f"pr:{n}", "pr_opened", ref, f"新 PR：{title}", url))
        state = check_state(pr.get("statusCheckRollup"))
        if state in ("success", "failure"):
            jobs = sorted(
                c.get("detailsUrl") or f"{c.get('name')}={c.get('conclusion')}"
                for c in latest_checks(pr.get("statusCheckRollup"))
            )
            key = f"ci:{n}:{sha}:{state}:{_short(' '.join(jobs))}"
            out.append(_event(key, "ci", ref, f"CI {state}（{sha[:7]}）：{title}", url))
        merge = pr.get("mergeStateStatus") or ""
        if merge in MERGE_STATES:
            out.append(
                _event(
                    f"merge:{n}:{sha}:{merge}",
                    "merge_state",
                    ref,
                    f"mergeStateStatus={merge}（{sha[:7]}）：{title}",
                    url,
                )
            )
    for n in previous:
        if isinstance(n, int) and n not in seen:
            out.append(
                _event(
                    f"pr_gone:{n}",
                    "pr_gone",
                    f"PR #{n}",
                    "已不在 open PR（合併或關閉）",
                    "",
                )
            )
    return out


def comment_events(comments: list, origin: float) -> list[dict]:
    out = []
    for c in comments:
        if not isinstance(c, dict) or c.get("id") is None:
            continue
        created = c.get("created_at")
        # An old comment edited after the monitor started is not new.
        if (epoch(created) or 0) < origin:
            continue
        number = (c.get("issue_url") or "").rsplit("/", 1)[-1]
        out.append(
            _event(
                f"comment:{c['id']}",
                "comment",
                f"#{number}",
                one_line(c.get("body") or ""),
                c.get("html_url") or "",
                at=created,
            )
        )
    return out


def _fields(rest: str) -> dict:
    return dict(p.split("=", 1) for p in rest.split() if "=" in p)


def job_events(logs: Path, origin: float) -> list[dict]:
    """daily: every end line. news: an end line whose news or news-llm part failed."""
    out = []
    for job in ("daily", "news"):
        for path in sorted(logs.glob(f"{job}-*.log"))[-JOB_FILES:]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                m = END_LINE.match(line.strip())
                if not m or (epoch(m.group(1)) or 0) < origin:
                    continue
                fields = _fields(m.group(2))
                failed = fields.get("exit") != "0" or fields.get("news_llm_exit") in (
                    "1",
                    "wrapper_error",
                )
                if job == "news" and not failed:
                    continue
                out.append(
                    _event(
                        f"job:{path.name}:{m.group(1)}",
                        "job_end",
                        job,
                        f"{path.name} 結束 {m.group(2)}",
                        "",
                        at=m.group(1),
                    )
                )
    return out


def slot_events(worktrees: dict) -> list[dict]:
    branches = sorted(
        (w.get("branch") or "")[len("refs/heads/") :]
        for w in ((worktrees.get("result") or {}).get("worktrees") or [])
        if isinstance(w, dict)
        and (w.get("branch") or "").startswith("refs/heads/task/")
    )
    if len(branches) >= SLOTS:
        return []
    names = "、".join(branches) or "無"
    return [
        _event(
            f"slots:{_short(' '.join(branches))}",
            "slots",
            "並行名額",
            f"task worktree {len(branches)} 個（上限 {SLOTS}）：{names}",
            "",
        )
    ]


def _event(id_: str, kind: str, ref: str, summary: str, url: str, at=None) -> dict:
    return {
        "id": id_,
        "kind": kind,
        "ref": ref,
        "summary": summary,
        "url": url,
        "at": at,
    }


# --- subcommands -------------------------------------------------------------------


def _load(path: str | None):
    if not path:
        return None
    return _read_json(Path(path))


def record(logs: Path, now: float, prs, comments, worktrees) -> str:
    q = Queue(logs)
    origin = q.origin(now)
    found: list[dict] = []
    state: dict = {"origin": origin, "polled_at": iso(now)}
    if isinstance(prs, list):
        found += pr_events(prs, q.state.get("pr_numbers") or [])
        state["pr_numbers"] = [
            p["number"]
            for p in prs
            if isinstance(p, dict) and isinstance(p.get("number"), int)
        ]
        state["prs"] = [
            pr_line(p)
            for p in prs
            if isinstance(p, dict) and isinstance(p.get("number"), int)
        ]
        state["prs_at"] = iso(now)
    if isinstance(comments, list):
        found += comment_events(comments, epoch(origin) or 0)
        newest = max(
            (epoch(c.get("updated_at")) or 0 for c in comments if isinstance(c, dict)),
            default=0,
        )
        since = epoch(q.state.get("comments_since") or origin) or 0
        state["comments_since"] = iso(max(since, newest - CURSOR_OVERLAP))
    found += job_events(logs, epoch(origin) or 0)
    if isinstance(worktrees, dict) and worktrees.get("ok") is True:
        found += slot_events(worktrees)
    new = []
    seq = q.seq
    for item in found:
        if item["id"] in q.ids:
            continue
        q.ids.add(item["id"])
        seq += 1
        new.append({"type": "event", "seq": seq, "detected_at": iso(now), **item})
    _append(logs / EVENTS, new)
    q.events += new
    q.save_state(**state)
    pending = q.pending()
    upto = q.notified_upto()
    unnotified = [e for e in pending if (e.get("seq") or 0) > upto]
    last = q.wakes[-1] if q.wakes else None
    retry_due = (
        last is None
        or last.get("ok")
        or now - (epoch(last.get("at")) or 0) >= WAKE_RETRY
    )
    wake = bool(unnotified) and (bool(new) or retry_due)
    handle, _, _ = _heartbeat(logs)
    for item in new:
        print(f"event [{item['seq']}] {item['id']} {item['ref']} {item['summary']}")
    return (
        f"new={len(new)} pending={len(pending)} unnotified={len(unnotified)}"
        f" wake={int(wake)} terminal={handle or '-'}"
    )


def stale(logs: Path, now: float, record_only: bool) -> str:
    q = Queue(logs)
    pending = q.pending()
    if not pending:
        return ""
    first = min(epoch(e.get("detected_at")) or now for e in pending)
    handle, beat_at, beat_text = _heartbeat(logs)
    if now - first < STALE_AFTER or (beat_at is not None and beat_at >= first):
        return ""
    key = f"heartbeat:{beat_text or 'none'}"
    planned = q.state.get("stale_planned") or []
    if key in q.stales or (record_only and key in planned):
        return ""
    beat = (
        f"心跳最後寫於 {beat_text}（terminal {handle or '無'}）"
        if beat_text
        else "沒有心跳檔"
    )
    body = (
        f"待使用者：請開統籌。事件佇列有 {len(pending)} 個未處理事件，最早的在 {iso(first)}"
        f" 記錄（{int((now - first) // 60)} 分鐘前），統籌{beat}，之後沒有處理佇列。"
        f"開統籌照[工作手冊「統籌 session」](https://github.com/YiCheng0608/stock-lab/blob/master/docs/GITHUB_WORKFLOW.md#統籌-session)。"
        f"\n\n（事件 monitor `tools/ops/monitor.sh` 自動留言，同一心跳只留一則；佇列 `{(logs / EVENTS).as_posix()}`。）"
    )
    return f"{key}\t{body}"


def note_wake(logs: Path, now: float, ok: bool, terminal: str, detail: str) -> None:
    q = Queue(logs)
    _append(
        logs / EVENTS,
        [
            {
                "type": "wake",
                "at": iso(now),
                "ok": ok,
                "terminal": terminal,
                "upto": q.seq if ok else q.notified_upto(),
                "detail": detail,
            }
        ],
    )


def note_stale(logs: Path, now: float, key: str, url: str) -> None:
    if url == "-":
        q = Queue(logs)
        q.save_state(stale_planned=[*(q.state.get("stale_planned") or []), key][-20:])
        return
    _append(logs / EVENTS, [{"type": "stale", "at": iso(now), "key": key, "url": url}])


def beat(logs: Path, now: float, mode: str, gh_calls: str, pid: str) -> None:
    _write_json(
        logs / BEAT,
        {"written_at": iso(now), "pid": pid, "mode": mode, "gh_calls": int(gh_calls)},
    )


def pending_lines(logs: Path) -> list[str]:
    events = Queue(logs).pending()
    if not events:
        return ["未處理事件：0 個"]
    seqs = [e.get("seq") for e in events]
    out = [f"未處理事件：{len(events)} 個（seq {min(seqs)}～{max(seqs)}）"]
    for e in events:
        at = e.get("at") or e.get("detected_at") or ""
        out.append(
            f"  [{e.get('seq')}] {e.get('kind')} {e.get('ref')} {at} {e.get('summary')}"
        )
        if e.get("url"):
            out.append(f"      {e['url']}")
    return out


def status_lines(logs: Path, now: float) -> list[str]:
    beat_doc = _read_json(logs / BEAT)
    at = epoch(beat_doc.get("written_at")) if isinstance(beat_doc, dict) else None
    if at is None:
        out = ["monitor：沒有心跳（monitor 未啟動，佇列不會更新）"]
    else:
        age = int(now - at)
        late = "，已停擺超過 10 分鐘" if age > 600 else ""
        out = [
            f"monitor：{beat_doc['written_at']}（{age} 秒前，mode={beat_doc.get('mode')}）{late}"
        ]
    state = Queue(logs).state
    if state.get("prs_at"):
        prs = state.get("prs") or []
        out.append(f"open PR（monitor {state['prs_at']}）：{len(prs)} 個")
        out += [f"  {line}" for line in prs]
    return out


def done(logs: Path, now: float, session: str, targets: list[str]) -> list[str]:
    q = Queue(logs)
    pending = q.pending()
    ids: list[str] = []
    for t in targets:
        if t.isdigit():
            ids += [e["id"] for e in pending if (e.get("seq") or 0) <= int(t)]
        elif t in q.ids:
            ids.append(t)
        else:
            raise SystemExit(f"沒有這個事件：{t}")
    ids = list(dict.fromkeys(i for i in ids if i not in q.done))
    if ids:
        _append(
            logs / DONE,
            [{"type": "done", "at": iso(now), "session_id": session, "ids": ids}],
        )
    return [f"標記已處理：{len(ids)} 個"]


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 64
    command, logs, rest = argv[0], Path(argv[1]), argv[2:]
    if command == "pending":
        print("\n".join(pending_lines(logs)))
        return 0
    now = float(rest.pop(0))
    if command == "since":
        q = Queue(logs)
        print(q.state.get("comments_since") or q.origin(now))
    elif command == "stale":
        out = stale(logs, now, "--record-only" in rest)
        if out:
            print(out)
    elif command == "record":
        opts = dict(zip(rest[::2], rest[1::2]))
        print(
            record(
                logs,
                now,
                _load(opts.get("--prs")),
                _load(opts.get("--comments")),
                _load(opts.get("--worktrees")),
            )
        )
    elif command == "note-wake":
        note_wake(logs, now, rest[0] == "1", rest[1], rest[2])
    elif command == "note-stale":
        note_stale(logs, now, rest[0], rest[1])
    elif command == "beat":
        beat(logs, now, *rest[:3])
    elif command == "status":
        print("\n".join(status_lines(logs, now)))
    elif command == "done":
        print("\n".join(done(logs, now, rest[0], rest[1:])))
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        return 64
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
