"""Replay an events.jsonl under the wake tiers of #711 (AC-3); read only.

  wake_replay.py EVENTS [--since ISO]... [--out FILE]

EVENTS is a copy of the monitor's queue (never the live file: this only reads it, but
the copy is what the PR's numbers come from). Each stored event gets the tier the
monitor gives it now (event_queue.py), from what the line holds:

  - a quiet event stays quiet; a pr_gone written before #440 is quiet too;
  - a comment: comment_tier() on its summary (the body's start); the monitor's own #1
    comment by the URL of a stale line; deploy.sh's #1 comment is quiet
    (coordinator_comment: it goes through comment.sh since #711);
  - CI, merge state, new PR, slots, gh_auth: as event_queue.py records them;
  - job_end: daily by its exit; news: a failure is a repeat (batch) when the news run
    two hours before it (the job runs every two hours, 10 minutes of slack) failed too,
    else now. The log lines of the successes are not in the queue, so this stands in for
    "the end line before it";
  - engineer_failed: failed_tier() of the error in its summary;
  - engineer_waiting, engineer_ended: quiet when the PR whose title names the Issue
    (…（#N） or [N] …) had left the open list before it; batch otherwise.

Then a poll a minute from the first event to the last one plus BATCH_CAP decides with
event_queue.wake_due(), and also, on the events as stored, with the rule before #711 (a
new event that is not quiet, or a failed wake due again), for calibration. The coordinator terminal is taken as
busy in a minute where the real monitor recorded not_idle and idle otherwise. A --done
of the coordinator is left out: an event stays until a wake covers it, so the replay
counts no fewer wakes than the rule would give.

Prints, for each --since (default: the whole file), the real wakes, the replayed wakes
of the old and the new rule and how many fewer; the events by tier; and every urgent
event with its real and replayed wake times (the replay must not be later). --out
writes the same as Markdown.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import event_queue as eq  # noqa: E402

NEWS_EVERY = 2 * 3600
NEWS_SLACK = 600
DEPLOY = re.compile(r"^部署：tag `[^`]+` 的 image 已以 `docker compose up -d` 啟動")
TITLE_ISSUE = re.compile(r"[（(]#(\d+)[）)]|^\[(\d+)\]")
FAILED_ERROR = re.compile(r"回合因 API 錯誤中斷（([^：）]+)")


def load(path: Path) -> tuple[list[dict], list[dict], set[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    events = [r for r in rows if r.get("type") == "event"]
    wakes = [r for r in rows if r.get("type") == "wake"]
    stale_urls = {
        r["url"]
        for r in rows
        if r.get("type") == "stale" and isinstance(r.get("url"), str)
    }
    return events, wakes, stale_urls


def classify(events: list[dict], stale_urls: set[str]) -> list[dict]:
    """Copies of the events with quiet and tier as the monitor records them now."""
    t = lambda e: eq.epoch(e.get("detected_at")) or 0  # noqa: E731
    gone_at: dict[str, float] = {}
    issue_pr: dict[str, str] = {}
    for e in events:
        if e.get("kind") == "pr_gone":
            gone_at.setdefault(e.get("ref"), t(e))
        if e.get("kind") == "pr_opened":
            title = (e.get("summary") or "").removeprefix("open PR：")
            m = TITLE_ISSUE.search(title)
            if m:
                issue_pr.setdefault(f"#{m.group(1) or m.group(2)}", e.get("ref"))
    news_failed: list[float] = []
    out = []
    for e in events:
        e = {k: v for k, v in e.items() if k not in ("tier",)}
        kind, summary, ref = e.get("kind"), e.get("summary") or "", e.get("ref") or ""
        quiet, tier = e.get("quiet"), eq.NOW
        if quiet:
            pass
        elif kind == "pr_gone":
            quiet = "pr_gone"
        elif kind == "comment":
            if ref == "#1" and DEPLOY.match(summary):
                quiet = "coordinator_comment"
            else:
                tier, quiet = eq.comment_tier(
                    summary, ref.lstrip("#"), e.get("url") in stale_urls
                )
        elif kind == "ci":
            tier = eq.NOW if str(e.get("id")).endswith(":success") else eq.URGENT
        elif kind == "merge_state":
            tier = eq.URGENT if str(e.get("id")).endswith(":DIRTY") else eq.NOW
        elif kind in ("pr_opened", "slots"):
            tier = eq.BATCH
        elif kind == "gh_auth":
            tier = eq.URGENT
        elif kind == "job_end" and ref == "daily":
            tier = eq.BATCH if re.search(r"\bexit=0\b", summary) else eq.URGENT
        elif kind == "job_end":
            at = eq.epoch(e.get("at")) or t(e)
            repeated = any(0 < at - x <= NEWS_EVERY + NEWS_SLACK for x in news_failed)
            news_failed.append(at)
            tier = eq.BATCH if repeated else eq.NOW
        elif kind == "engineer_failed":
            m = FAILED_ERROR.search(summary)
            tier = eq.failed_tier(m.group(1) if m else "")
        elif kind in ("engineer_waiting", "engineer_ended"):
            tier = eq.BATCH
            pr = issue_pr.get(ref)
            if pr in gone_at and gone_at[pr] <= t(e):
                quiet = "task_pr_gone"
        if quiet:
            e["quiet"] = quiet
        else:
            e.pop("quiet", None)
            e["tier"] = tier
        out.append(e)
    return out


def simulate(events: list[dict], busy: set[int], new_rule: bool) -> tuple[int, dict]:
    """(wakes, minute of the wake that covered each seq) of a poll a minute."""
    by_minute = collections.defaultdict(list)
    for e in events:
        by_minute[int((eq.epoch(e.get("detected_at")) or 0) // 60)].append(e)
    if not by_minute:
        return 0, {}
    waiting: list[dict] = []
    last: tuple[int, bool] | None = None
    wakes, covered = 0, {}
    end = max(by_minute) + eq.BATCH_CAP // 60 + 2
    for minute in range(min(by_minute), end + 1):
        new = [e for e in by_minute.get(minute, []) if not e.get("quiet")]
        waiting += new
        if not waiting:
            continue
        now = minute * 60
        retry_due = last is None or last[1] or now - last[0] * 60 >= eq.WAKE_RETRY
        if new_rule:
            due = eq.wake_due(waiting, new, now, retry_due)
        else:
            due = bool(new) or retry_due
        if not due:
            continue
        if minute in busy:
            last = (minute, False)
            continue
        wakes += 1
        last = (minute, True)
        for e in waiting:
            covered[e.get("seq")] = now
        waiting = []
    return wakes, covered


def real_wake_times(events: list[dict], wakes: list[dict]) -> dict:
    sent = sorted(
        (eq.epoch(w.get("at")) or 0, w.get("upto") or 0) for w in wakes if w.get("ok")
    )
    out = {}
    for e in events:
        at = eq.epoch(e.get("detected_at")) or 0
        for when, upto in sent:
            if upto >= (e.get("seq") or 0) and when >= at - 1:
                out[e.get("seq")] = when
                break
    return out


def report(path: Path, sinces: list[str]) -> list[str]:
    events, wakes, stale_urls = load(path)
    classified = classify(events, stale_urls)
    busy = {
        int((eq.epoch(w.get("at")) or 0) // 60)
        for w in wakes
        if not w.get("ok") and w.get("detail") == "not_idle"
    }
    real = real_wake_times(events, wakes)
    lines = [
        f"# 喚醒分級重放（#711 AC-3）：`{path.name}`",
        "",
        f"事件 {len(events)} 個（{events[0].get('detected_at')}～"
        f"{events[-1].get('detected_at')}），喚醒紀錄 {len(wakes)} 筆；"
        f"上限 {eq.BATCH_CAP // 60} 分鐘。",
        "",
        "| 範圍 | 事件 | 實際喚醒 | 舊規則重放 | 新規則重放 | 比實際少 | 比舊規則重放少"
        " | 急件 | 晚於實際的急件 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    urgent_rows: list[str] = []
    tiers_lines: list[str] = []
    for since in sinces or [events[0].get("detected_at")]:
        part = [e for e in classified if (e.get("detected_at") or "") >= since]
        stored = [e for e in events if (e.get("detected_at") or "") >= since]
        actual = sum(1 for w in wakes if w.get("ok") and (w.get("at") or "") >= since)
        old, _ = simulate(stored, busy, new_rule=False)
        new, covered = simulate(part, busy, new_rule=True)
        urgent = [e for e in part if e.get("tier") == eq.URGENT]
        late = [
            e
            for e in urgent
            if e.get("seq") in real
            and covered.get(e.get("seq"), float("inf")) > real[e.get("seq")]
        ]
        lines.append(
            f"| {since} 起 | {len(part)} | {actual} | {old} | {new} | "
            f"{100 * (1 - new / actual):.1f}% | {100 * (1 - new / old):.1f}% | "
            f"{len(urgent)} | {len(late)} |"
        )
        if not urgent_rows:  # the widest range first: list every urgent event once
            counts = collections.Counter(
                f"quiet:{e['quiet']}" if e.get("quiet") else e["tier"] for e in part
            )
            tiers_lines = [f"- {k}：{n}" for k, n in sorted(counts.items())]
            for e in urgent:
                seq = e.get("seq")
                r, c = real.get(seq), covered.get(seq)
                diff = f"{c - r:+.0f}" if r is not None and c is not None else "—"
                urgent_rows.append(
                    f"| {seq} | {e.get('kind')} | {e.get('ref')} | "
                    f"{e.get('detected_at')} | {eq.iso(r) if r else '—'} | "
                    f"{eq.iso(c) if c else '—'} | {diff} |"
                )
    lines += ["", "## 事件分級（最寬的範圍）", "", *tiers_lines]
    lines += [
        "",
        "## 每個急件事件的喚醒時間（最寬的範圍；差 = 重放 − 實際，秒，負的是較早）",
        "",
        "| seq | kind | ref | 記錄 | 實際喚醒 | 重放喚醒 | 差 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *urgent_rows,
    ]
    return lines


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__.strip(), file=sys.stderr)
        return 64
    path, sinces, out = Path(argv[0]), [], None
    rest = argv[1:]
    while rest:
        if rest[0] in ("--since", "--out") and len(rest) >= 2:
            if rest[0] == "--since":
                sinces.append(rest[1])
            else:
                out = Path(rest[1])
            rest = rest[2:]
        else:
            print(f"未知參數：{rest[0]}", file=sys.stderr)
            return 64
    lines = report(path, sinces)
    text = "\n".join(lines) + "\n"
    if out:
        out.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(newline="\n")
    print("\n".join(lines[: 6 + max(1, len(sinces))]))  # the table of wakes
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
