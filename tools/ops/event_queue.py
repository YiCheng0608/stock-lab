"""Event queue of the coordinator's event monitor (Issue #316).

monitor.sh polls GitHub (open PRs, new comments) and Orca (task worktrees), and hands
the answers to ``record``, which also reads the job logs (and the watchdog's), turns
everything into events, drops the ones already queued and appends the rest. The
coordinator reads the queue through patrol.sh and marks what it handled with ``done``.
Nothing here calls gh, orca or an LLM: the shell scripts do, so the tests can fake them
on PATH.

Files, all in the queue directory LOGS (<data>/logs/, or in the scheduler container the
host directory at /coordination, #338), each with a single writer:

  events.jsonl            monitor.sh; one JSON object per line, appended:
    {"type": "event", "seq", "id", "kind", "detected_at", "at", "ref", "summary", "url"}
        a new event. ``id`` is the dedup key: one PR's CI run (head commit, workflow run
        id, conclusion of its required check), one comment id, one end line of a job
        log, one Taipei day of gh refused by GitHub (the watchdog's or the monitor's
        own call). ``seq`` counts up from 1. ``at`` is the source's own time (or null).
    {"type": "wake", "at", "ok", "terminal", "upto", "detail"}
        the coordinator terminal was sent "有 N 個事件…" (ok) or the send failed; a
        successful wake covers every event up to seq ``upto``.
    {"type": "stale", "at", "key", "url"}
        the #1 comment asking the user to open a coordinator; one per ``key``.
  events-done.jsonl       patrol.sh --done: {"type": "done", "at", "session_id", "ids"}
  monitor-state.json      monitor.sh: comment cursor, last poll, open PR snapshot, the
                          last line of each job log (patrol.sh prints them)
  monitor-heartbeat.json  monitor.sh, every poll: {"written_at", "pid", "mode", "gh_calls",
                          "gh_failed_polls", "gh_failed_since", "gh_error"}: polls in a
                          row with a failed gh call, since when, the last gh error

A line that cannot be read (a partial last line) is skipped; an append after one
starts on a new line, so only the partial line is lost. Times are UTC ISO
(2026-10-28T01:23:45Z); NOW is epoch seconds.

Subcommands (LOGS is <data>/logs):
  since LOGS NOW                  the comment cursor to poll with
  stale LOGS NOW [--record-only]  "KEY<TAB>BODY" when the #1 comment is due, else nothing
  record LOGS NOW [--prs F] [--comments F] [--worktrees F] [--job-logs DIR]
         [--gh-refused ERROR]     append the new events and print
                                  "new=N pending=P unnotified=U wake=0|1 terminal=H"
  note-wake LOGS NOW OK TERMINAL DETAIL     OK is 1 or 0
  note-stale LOGS NOW KEY URL     URL "-" in record-only mode: kept in the state only
  beat LOGS NOW MODE GH_CALLS PID GH_FAILED [GH_ERROR]   GH_FAILED is 1 or 0
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

from coordinator_json import one_line, pr_line

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
RUN_ID = re.compile(r"/actions/runs/(\d+)/")
# watchdog.sh's line for a gh call GitHub refused (#337): "<UTC> gh_auth_failed exit=…
# date=<Taipei day> | …"
GH_AUTH_LINE = re.compile(r"^(\S+) gh_auth_failed .*?\bdate=(\d{4}-\d{2}-\d{2})")
TAIPEI_OFFSET = 8 * 3600
# What the coordinator does about it; the token lives in the env file (OPERATIONS §6.7).
GH_AUTH_ACTION = "請用本機 gh 在 #1 留言，請使用者換 GH_TOKEN（OPERATIONS §6.7）"
# The merge gate: CI's required check (docs/GITHUB_WORKFLOW.md, 欄位與唯一來源).
GATE = "required"


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
    # A run killed in the middle of a write leaves a partial last line. Start on a new
    # line, or the first item joins it and is skipped with it (#316 review B2).
    try:
        with open(path, "rb") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                text = "\n" + text
    except OSError:  # no file yet, or an empty one
        pass
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


def ci_result(rollup) -> tuple[str, str] | None:
    """(run id, conclusion) of the PR's newest CI run once its required check finished.

    Only the newest run of the gate's workflow counts: a run cancelled by a newer one
    leaves a failed required job behind, and the newer run lists its required job only
    once the jobs it needs are done (seen on PR #328, 2026-10-28). So while the newest
    run has no finished required check there is no result yet."""
    runs = []
    for c in rollup or []:
        m = RUN_ID.search(c.get("detailsUrl") or "")
        if m:
            runs.append((int(m.group(1)), c))
    gates = [(r, c) for r, c in runs if c.get("name") == GATE]
    if not gates:
        return None
    workflow = max(gates, key=lambda g: g[0])[1].get("workflowName")
    newest = max(r for r, c in runs if c.get("workflowName") == workflow)
    gate = [c for r, c in gates if r == newest]
    if not gate or (gate[-1].get("status") or "").upper() != "COMPLETED":
        return None
    return str(newest), (gate[-1].get("conclusion") or "unknown").lower()


def pr_events(prs: list, previous: list) -> list[dict]:
    """Open, CI result, merge state, gone. CI is keyed by head commit, workflow run and
    conclusion: one run polled again is not new; a re-run that ends otherwise is."""
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
        out.append(_event(f"pr:{n}", "pr_opened", ref, f"open PR：{title}", url))
        result = ci_result(pr.get("statusCheckRollup"))
        if result:
            run, state = result
            out.append(
                _event(
                    f"ci:{n}:{sha}:{run}:{state}",
                    "ci",
                    ref,
                    f"CI {state}（{sha[:7]}，run {run}）：{title}",
                    url,
                )
            )
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


def gh_auth_events(
    job_logs: Path, origin: float, now: float, refused: str | None
) -> list[dict]:
    """GitHub refused gh's credentials: one event per Taipei day, whether the watchdog
    or the monitor's own call saw it first. The watchdog cannot comment then and neither
    can the monitor (one GH_TOKEN), so the coordinator, woken, comments with its own gh
    (#338, Issue comment 6477434381)."""
    out = []
    if refused is not None:
        day = datetime.fromtimestamp(int(now) + TAIPEI_OFFSET, tz=timezone.utc)
        out.append(
            _event(
                f"gh_auth:{day:%Y-%m-%d}",
                "gh_auth",
                "gh 認證",
                f"GitHub 拒絕 monitor 的 gh（{one_line(refused, 120)}）：{GH_AUTH_ACTION}",
                "",
                at=iso(now),
            )
        )
    try:
        text = (job_logs / "watchdog.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        m = GH_AUTH_LINE.match(line.strip())
        if not m or (epoch(m.group(1)) or 0) < origin:
            continue
        out.append(
            _event(
                f"gh_auth:{m.group(2)}",
                "gh_auth",
                "gh 認證",
                f"看門狗的 gh 被 GitHub 拒絕（{m.group(1)}），無法在 #1 留言：{GH_AUTH_ACTION}",
                "",
                at=m.group(1),
            )
        )
    return out


def job_tails(job_logs: Path) -> dict:
    """The end line of the newest daily and news log and the last watchdog line: what
    patrol.sh printed from the logs, which the coordinator no longer reads (in the
    container they are in the volume, #338)."""
    out = {}
    for job in ("daily", "news"):
        files = sorted(job_logs.glob(f"{job}-*.log"))
        if not files:
            out[job] = "沒有日誌"
            continue
        try:
            text = files[-1].read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        ends = [x.strip() for x in text.splitlines() if END_LINE.match(x.strip())]
        out[job] = f"{files[-1].name} " + (
            ends[-1] if ends else "（沒有結束列，可能執行中或中斷）"
        )
    try:
        text = (job_logs / "watchdog.log").read_text(encoding="utf-8", errors="replace")
        out["watchdog"] = (text.splitlines() or ["沒有日誌"])[-1].strip()
    except OSError:
        out["watchdog"] = "沒有日誌"
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


def record(
    logs: Path,
    now: float,
    prs,
    comments,
    worktrees,
    job_logs: Path | None = None,
    gh_refused: str | None = None,
) -> str:
    q = Queue(logs)
    job_logs = job_logs or logs
    origin = q.origin(now)
    found: list[dict] = []
    state: dict = {
        "origin": origin,
        "polled_at": iso(now),
        "jobs": job_tails(job_logs),
    }
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
    found += job_events(job_logs, epoch(origin) or 0)
    found += gh_auth_events(job_logs, epoch(origin) or 0, now, gh_refused)
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


def beat(
    logs: Path, now: float, mode: str, gh_calls: str, pid: str, failed: bool, error: str
) -> None:
    """The watchdog reads it: a stale beat is a stopped monitor, and gh_failed_polls a
    monitor that polls but gets nothing from GitHub (logged out, say)."""
    previous = _read_json(logs / BEAT)
    previous = previous if isinstance(previous, dict) else {}
    value = {
        "written_at": iso(now),
        "pid": pid,
        "mode": mode,
        "gh_calls": int(gh_calls),
    }
    count = previous.get("gh_failed_polls")
    count = count if isinstance(count, int) and count > 0 else 0
    if failed:
        value["gh_failed_polls"] = count + 1
        value["gh_failed_since"] = (count and previous.get("gh_failed_since")) or iso(
            now
        )
        value["gh_error"] = one_line(error, 200)
    else:
        value["gh_failed_polls"] = 0
    _write_json(logs / BEAT, value)


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
        failed = beat_doc.get("gh_failed_polls")
        if isinstance(failed, int) and failed > 0:
            late += f"，gh 連續 {failed} 輪失敗：{beat_doc.get('gh_error') or '?'}"
        out = [
            f"monitor：{beat_doc['written_at']}（{age} 秒前，mode={beat_doc.get('mode')}）{late}"
        ]
    state = Queue(logs).state
    if state.get("prs_at"):
        prs = state.get("prs") or []
        out.append(f"open PR（monitor {state['prs_at']}）：{len(prs)} 個")
        out += [f"  {line}" for line in prs]
    jobs = state.get("jobs") if isinstance(state.get("jobs"), dict) else {}
    for job, label in (
        ("daily", "排程 daily"),
        ("news", "排程 news"),
        ("watchdog", "看門狗"),
    ):
        line = jobs.get(job) or "沒有紀錄（monitor 還沒輪詢過）"
        out.append(f"{label}（monitor {state.get('polled_at') or '-'}）：{line}")
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
                Path(opts["--job-logs"]) if opts.get("--job-logs") else None,
                opts.get("--gh-refused"),
            )
        )
    elif command == "note-wake":
        note_wake(logs, now, rest[0] == "1", rest[1], rest[2])
    elif command == "note-stale":
        note_stale(logs, now, rest[0], rest[1])
    elif command == "beat":
        beat(logs, now, rest[0], rest[1], rest[2], rest[3] == "1", " ".join(rest[4:]))
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
