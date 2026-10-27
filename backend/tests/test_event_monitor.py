"""tools/ops/monitor.sh and event_queue.py with fake orca and gh (Issue #316).

The harness is test_coordinator_scripts.py's: the scripts run from a copy in a
sandbox under tmp_path, the fakes record every call, the data directory is in
tmp_path. Each test runs ``monitor.sh --once`` with MONITOR_NOW, so one run is one
poll by a freshly started monitor: two runs in a row are a restart (AC-1).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from test_coordinator_scripts import NOW, ROOT, Harness, _ok

CI_RUN = "https://github.com/YiCheng0608/stock-lab/actions/runs/{}/job/{}"


def _pr(run: int = 1, conclusion: str = "SUCCESS", merge: str = "BLOCKED") -> dict:
    return {
        "number": 324,
        "title": "排程 wrapper 吸進 Python worker",
        "url": "https://github.com/YiCheng0608/stock-lab/pull/324",
        "isDraft": False,
        "headRefOid": "c" * 40,
        "mergeStateStatus": merge,
        "statusCheckRollup": [
            {
                "name": "required",
                "workflowName": "CI",
                "startedAt": "2026-10-25T11:00:00Z",
                "status": "COMPLETED",
                "conclusion": conclusion,
                "detailsUrl": CI_RUN.format(run, run * 10),
            }
        ],
        "labels": [],
    }


def _comment(
    id_: int, created: str, updated: str | None = None, body: str = "提問"
) -> dict:
    return {
        "id": id_,
        "issue_url": "https://api.github.com/repos/YiCheng0608/stock-lab/issues/316",
        "html_url": f"https://github.com/YiCheng0608/stock-lab/issues/316#issuecomment-{id_}",
        "created_at": created,
        "updated_at": updated or created,
        "body": body,
    }


def _worktrees(*branches: str) -> dict:
    return _ok(
        {
            "worktrees": [
                {"path": f"C:/wt/{b}", "branch": f"refs/heads/{b}", "id": b}
                for b in ("master", *branches)
            ]
        }
    )


@pytest.fixture
def mon(tmp_path) -> Harness:
    h = Harness(tmp_path)
    h.answer("gh_pr_list", [_pr()])
    h.answer("gh_comments", [_comment(9, "2026-10-25T11:50:00Z")])
    h.answer("orca_worktree_list", _worktrees("task/316-a", "task/313-b", "task/315-c"))
    h.answer("orca_terminal_send", _ok({"send": {}}))
    _coordinator(h, "2026-10-25T11:55:00Z")
    return h


def _coordinator(h: Harness, written_at: str) -> None:
    (h.data / "logs" / "coordinator-heartbeat.json").write_text(
        json.dumps(
            {
                "session_id": "coord",
                "terminal_handle": "term_coord",
                "written_at": written_at,
            }
        ),
        encoding="utf-8",
    )


def _monitor(h: Harness, *args: str, at: int = NOW) -> subprocess.CompletedProcess:
    result = h.run("monitor.sh", "--once", *args, MONITOR_NOW=str(at))
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _records(h: Harness, kind: str | None = None) -> list[dict]:
    path = h.data / "logs" / "events.jsonl"
    rows = (
        [json.loads(x) for x in path.read_text("utf-8").splitlines()]
        if path.exists()
        else []
    )
    return [r for r in rows if kind is None or r["type"] == kind]


def _ids(h: Harness) -> list[str]:
    return [e["id"] for e in _records(h, "event")]


def _sends(h: Harness) -> list[str]:
    return [c for c in h.calls("orca") if c.startswith("terminal send")]


def _gh_per_poll(h: Harness) -> int:
    return len(h.calls("gh"))


def _done(h: Harness, *targets: str) -> None:
    result = h.run(
        "patrol.sh",
        "--session-id",
        "coord",
        "--terminal",
        "term_coord",
        *(x for t in targets for x in ("--done", t)),
        PATROL_NOW=str(NOW + 120),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_one_poll_records_each_event_once_and_wakes_once(mon: Harness) -> None:
    result = _monitor(mon)
    assert _ids(mon) == [
        "pr:324",
        f"ci:324:{'c' * 12}:1:success",
        "comment:9",
    ]
    assert len(_sends(mon)) == 1
    sent = (mon.fake / "sent_text.txt").read_text(encoding="utf-8")
    assert sent.startswith("有 3 個事件，請處理佇列：bash tools/ops/patrol.sh")
    assert "--terminal term_coord" in _sends(mon)[0]
    assert "wake=sent terminal=term_coord" in result.stdout
    # The same answers polled again by a restarted monitor: nothing new, no wake.
    for minute in (1, 2):
        _monitor(mon, at=NOW + 60 * minute)
    assert len(_ids(mon)) == 3 and len(_sends(mon)) == 1


def test_a_restarted_monitor_does_not_wake_for_handled_events(mon: Harness) -> None:
    """AC-1: what the coordinator marked done never comes back after a restart."""
    _monitor(mon)
    _done(mon, "3")
    (mon.data / "logs" / "monitor-state.json").unlink()  # even the cursor is lost
    _monitor(mon, at=NOW + 180)
    assert len(_ids(mon)) == 3 and len(_sends(mon)) == 1
    out = mon.run(
        "patrol.sh",
        "--session-id",
        "coord",
        "--terminal",
        "term_coord",
        PATROL_NOW=str(NOW + 240),
    ).stdout
    assert "未處理事件：0 個" in out


def test_a_new_ci_run_is_a_new_event_and_an_edited_comment_is_not(mon: Harness) -> None:
    _monitor(mon)
    _done(mon, "3")
    mon.answer("gh_pr_list", [_pr(run=2, conclusion="FAILURE", merge="DIRTY")])
    mon.answer(
        "gh_comments",
        [
            _comment(
                9, "2026-10-25T11:50:00Z", "2026-10-25T12:01:00Z", body="改過的提問"
            )
        ],
    )
    _monitor(mon, at=NOW + 60)
    new = _ids(mon)[3:]
    assert [i.split(":")[0] for i in new] == ["ci", "merge"], new
    assert new == [f"ci:324:{'c' * 12}:2:failure", f"merge:324:{'c' * 12}:DIRTY"]
    assert len(_sends(mon)) == 2
    # The same failed run polled again: no event, no wake.
    _monitor(mon, at=NOW + 120)
    assert len(_ids(mon)) == 5 and len(_sends(mon)) == 2


def _check(name: str, run: int, status: str, conclusion: str = "") -> dict:
    return {
        "name": name,
        "workflowName": "CI",
        "startedAt": f"2026-10-25T11:{run:02d}:00Z",
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": CI_RUN.format(run, run * 10 + len(name)),
    }


def test_a_run_cancelled_by_a_newer_one_is_no_ci_result(mon: Harness) -> None:
    """PR #328, 2026-10-28: the push's first run was cancelled by the run of the PR
    edit, leaving required=FAILURE; the newer run lists its required job only once
    backend is done. Before the fix every poll recorded another "CI failure"."""
    pr = _pr()
    pr["statusCheckRollup"] = [
        _check("backend", 40, "COMPLETED", "CANCELLED"),
        _check("required", 40, "COMPLETED", "FAILURE"),
        _check("changes", 47, "COMPLETED", "SUCCESS"),
        _check("backend", 47, "IN_PROGRESS"),
    ]
    mon.answer("gh_pr_list", [pr])
    _monitor(mon)
    pr["statusCheckRollup"].append(_check("frontend", 47, "COMPLETED", "SUCCESS"))
    mon.answer("gh_pr_list", [pr])
    _monitor(mon, at=NOW + 60)
    assert not [i for i in _ids(mon) if i.startswith("ci:")]
    pr["statusCheckRollup"][3] = _check("backend", 47, "COMPLETED", "SUCCESS")
    pr["statusCheckRollup"].append(_check("required", 47, "IN_PROGRESS"))
    mon.answer("gh_pr_list", [pr])
    _monitor(mon, at=NOW + 120)
    assert not [i for i in _ids(mon) if i.startswith("ci:")]
    pr["statusCheckRollup"][-1] = _check("required", 47, "COMPLETED", "SUCCESS")
    mon.answer("gh_pr_list", [pr])
    for minute in (3, 4):
        _monitor(mon, at=NOW + 60 * minute)
    assert [i for i in _ids(mon) if i.startswith("ci:")] == [
        f"ci:324:{'c' * 12}:47:success"
    ]


def test_the_comment_cursor_moves_only_with_what_was_read(mon: Harness) -> None:
    _monitor(mon)
    first = [c for c in mon.calls("gh") if c.startswith("api ")][0]
    assert "since=2026-10-25T11:00:00Z" in first  # first poll: one hour back
    mon.answer("gh_comments", [_comment(10, "2026-10-25T12:00:30Z")])
    (mon.fake / "gh_comments.fail").write_text("", encoding="utf-8")
    _monitor(mon, at=NOW + 60)
    (mon.fake / "gh_comments.fail").unlink()
    _monitor(mon, at=NOW + 120)
    since = [c for c in mon.calls("gh") if c.startswith("api ")]
    # Both later polls start one minute before the newest comment seen (11:50).
    assert all("since=2026-10-25T11:49:00Z" in c for c in since[1:]), since
    assert _ids(mon)[-1] == "comment:10"


def test_comments_older_than_the_first_poll_are_not_events(mon: Harness) -> None:
    mon.answer(
        "gh_comments",
        [_comment(8, "2026-10-20T00:00:00Z", "2026-10-25T11:58:00Z")],  # edited today
    )
    _monitor(mon)
    assert "comment:8" not in _ids(mon)


def test_a_poll_makes_at_most_two_gh_calls(mon: Harness) -> None:
    """The 5000/hour limit is shared: two gh calls a poll, polls 60 s apart."""
    before = 0
    for minute in range(3):
        _monitor(mon, at=NOW + 60 * minute)
        assert _gh_per_poll(mon) - before <= 2
        before = _gh_per_poll(mon)
    log = (mon.data / "logs" / "monitor.log").read_text(encoding="utf-8")
    assert log.count(" poll mode=wake gh_calls=2 ") == 3
    for interval in ("59", "0", "x"):
        result = mon.run("monitor.sh", "--once", "--interval", interval)
        assert result.returncode == 64 and not result.stdout


def test_record_only_never_wakes_or_comments(mon: Harness) -> None:
    (mon.data / "logs" / "coordinator-heartbeat.json").unlink()
    for minute in (0, 61, 62):
        result = _monitor(mon, "--record-only", at=NOW + 60 * minute)
    assert _sends(mon) == []
    assert not [c for c in mon.calls("gh") if c.startswith("issue ")]
    assert len(_ids(mon)) == 3
    assert not _records(mon, "wake") and not _records(mon, "stale")
    log = (mon.data / "logs" / "monitor.log").read_text(encoding="utf-8")
    assert log.count("wake=planned") == 1 and log.count("stale=planned") == 1
    assert "mode=record-only" in result.stdout + log


def test_no_heartbeat_for_an_hour_asks_the_user_once_on_1(mon: Harness) -> None:
    """The monitor comments "請開統籌" on #1; it never opens a session."""
    (mon.data / "logs" / "coordinator-heartbeat.json").unlink()
    mon.write(
        "gh_issue_comment.json", "https://github.com/x/issues/1#issuecomment-77\n"
    )
    _monitor(mon)
    assert _records(mon, "wake")[0]["ok"] is False and _sends(mon) == []
    _monitor(mon, at=NOW + 3540)  # 59 minutes: not yet
    assert not [c for c in mon.calls("gh") if c.startswith("issue ")]
    calls = _gh_per_poll(mon)
    _monitor(mon, at=NOW + 3600)
    comments = [c for c in mon.calls("gh") if c.startswith("issue comment 1 ")]
    assert len(comments) == 1 and _gh_per_poll(mon) - calls == 2  # PRs, the comment
    assert _records(mon, "stale") == [
        {
            "type": "stale",
            "at": "2026-10-25T13:00:00Z",
            "key": "heartbeat:none",
            "url": "https://github.com/x/issues/1#issuecomment-77",
        }
    ]
    _monitor(mon, at=NOW + 3660)
    assert len([c for c in mon.calls("gh") if c.startswith("issue ")]) == 1
    assert not [c for c in mon.calls("orca") if "create" in c]
    # A coordinator that patrols after the events arrived is alive: no comment.
    _coordinator(mon, "2026-10-25T13:05:00Z")
    _monitor(mon, at=NOW + 7200)
    assert len([c for c in mon.calls("gh") if c.startswith("issue ")]) == 1


def test_a_failed_wake_is_retried_after_ten_minutes(mon: Harness) -> None:
    mon.answer("orca_terminal_send", {"ok": False, "error": "terminal busy"})
    _monitor(mon)
    _monitor(mon, at=NOW + 60)
    assert len(_sends(mon)) == 1
    mon.answer("orca_terminal_send", _ok({"send": {}}))
    _monitor(mon, at=NOW + 600)
    _monitor(mon, at=NOW + 660)
    assert len(_sends(mon)) == 2
    assert [(w["ok"], w["upto"]) for w in _records(mon, "wake")] == [
        (False, 0),
        (True, 3),
    ]


def test_slots_and_job_logs_become_events(mon: Harness) -> None:
    logs = mon.data / "logs"
    mon.answer("orca_worktree_list", _worktrees("task/316-a"))
    (logs / "daily-20261025.log").write_text(
        "===== 2026-10-25T19:45:00.1234567+08:00 end exit=0 seconds=900\n"
        "===== 2026-10-24T13:30:00Z end exit=0\n",  # before the first poll's look-back
        encoding="utf-8",
    )
    (logs / "news-20261025.log").write_text(
        "===== 2026-10-25T11:10:00Z end exit=0 news_llm_exit=0\n"
        "===== 2026-10-25T11:40:00Z end exit=0 news_llm_exit=1\n",
        encoding="utf-8",
    )
    _monitor(mon)
    events = {e["id"]: e for e in _records(mon, "event")}
    assert "job:daily-20261025.log:2026-10-25T19:45:00.1234567+08:00" in events
    assert "job:news-20261025.log:2026-10-25T11:40:00Z" in events
    assert not [i for i in events if "2026-10-24" in i or "11:10" in i]
    slots = [e for e in events.values() if e["kind"] == "slots"]
    assert [s["summary"] for s in slots] == ["task worktree 1 個（上限 3）：task/316-a"]
    # The same set of worktrees is not a new event; one more is.
    _monitor(mon, at=NOW + 60)
    mon.answer("orca_worktree_list", _worktrees("task/316-a", "task/317-d"))
    _monitor(mon, at=NOW + 120)
    assert len([e for e in _records(mon, "event") if e["kind"] == "slots"]) == 2


def test_a_closed_pr_is_an_event(mon: Harness) -> None:
    _monitor(mon)
    mon.answer("gh_pr_list", [])
    _monitor(mon, at=NOW + 60)
    assert _ids(mon)[-1] == "pr_gone:324"


def test_the_queue_format(mon: Harness) -> None:
    """AC-5: every line patrol.sh reads has the fields event_queue.py documents."""
    mon.answer("orca_worktree_list", _worktrees())
    _monitor(mon)
    _done(mon, "2")
    fields = {
        "event": {
            "type",
            "seq",
            "id",
            "kind",
            "detected_at",
            "at",
            "ref",
            "summary",
            "url",
        },
        "wake": {"type", "at", "ok", "terminal", "upto", "detail"},
    }
    rows = _records(mon)
    for row in rows:
        assert set(row) == fields[row["type"]], row
    events = _records(mon, "event")
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert len({e["id"] for e in events}) == len(events)
    assert {e["kind"] for e in events} == {"pr_opened", "ci", "comment", "slots"}
    assert all(e["detected_at"] == "2026-10-25T12:00:00Z" for e in events)
    done = [
        json.loads(x)
        for x in (mon.data / "logs" / "events-done.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    assert [set(d) for d in done] == [{"type", "at", "session_id", "ids"}]
    assert done[0]["ids"] == [e["id"] for e in events[:2]]
    beat = json.loads((mon.data / "logs" / "monitor-heartbeat.json").read_text("utf-8"))
    assert beat["written_at"] == "2026-10-25T12:00:00Z" and beat["gh_calls"] == 2
    # A partial last line (a monitor killed mid-write) does not stop the readers.
    with open(mon.data / "logs" / "events.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"type": "event", "seq": 9')
    _monitor(mon, at=NOW + 60)
    assert (
        mon.run(
            "patrol.sh",
            "--session-id",
            "coord",
            "--terminal",
            "term_coord",
            PATROL_NOW=str(NOW + 120),
        ).returncode
        == 0
    )


def test_one_monitor_at_a_time(mon: Harness) -> None:
    logs = mon.data / "logs"
    # A live owner (the outer bash) with a fresh heartbeat keeps the lock.
    fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (logs / "monitor-heartbeat.json").write_text(json.dumps({"written_at": fresh}))
    result = mon.run_bash(
        'mkdir -p "$1/monitor.lock" && echo $$ >"$1/monitor.lock/pid" && bash "$2" --once',
        logs.as_posix(),
        (mon.ops / "monitor.sh").as_posix(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "monitor 已在執行" in result.stdout and mon.calls("gh") == []
    # A dead owner's lock is taken over, and the lock is gone after the run.
    (logs / "monitor.lock" / "pid").write_text("999999\n", encoding="utf-8")
    _monitor(mon)
    assert "lock_stale_removed" in (logs / "monitor.log").read_text(encoding="utf-8")
    assert not (logs / "monitor.lock").exists()


def test_compaction_hook_logs_each_compaction_time(tmp_path) -> None:
    """AC-4: <session>.log keeps one time per compaction next to the count."""
    h = Harness(tmp_path)
    hook = (h.ops / "compact_hook.sh").as_posix()
    for at, trigger in ((NOW, "auto"), (NOW + 90, "manual")):
        result = h.run_bash(
            f'printf \'%s\' \'{{"session_id":"sess-9","trigger":"{trigger}"}}\' | bash "$1"',
            hook,
            COMPACT_HOOK_NOW=str(at),
        )
        assert result.returncode == 0, result.stdout + result.stderr
    folder = h.data / "logs" / "compactions"
    assert (folder / "sess-9.count").read_text(encoding="utf-8") == "2\n"
    assert (folder / "sess-9.log").read_text(encoding="utf-8") == (
        "2026-10-25T12:00:00Z trigger=auto\n2026-10-25T12:01:30Z trigger=manual\n"
    )


def test_a_stop_file_ends_the_loop_after_its_poll(mon: Harness) -> None:
    logs = mon.data / "logs"
    stop = logs / "monitor.stop"
    stop.write_text("", encoding="utf-8")  # left for an earlier monitor: removed
    # The fake sleep asks the monitor to stop while it waits for the next poll.
    fake_sleep = mon.bin / "sleep"
    fake_sleep.write_text(
        f'#!/usr/bin/env bash\ntouch "{stop.as_posix()}"\n',
        encoding="utf-8",
        newline="\n",
    )
    fake_sleep.chmod(0o755)
    result = mon.run("monitor.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    log = (logs / "monitor.log").read_text(encoding="utf-8")
    assert [line.split()[1] for line in log.splitlines()] == [
        "stop_file_removed",
        "start",
        "poll",
        "stopped",
    ]
    assert not stop.exists() and not (logs / "monitor.lock").exists()


def _section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end > 0 else None]


def test_the_coordinator_keeps_no_polling_of_its_own() -> None:
    """AC-2: the handbook's 統籌 session (with the handoff text) and 無人值守運作 no
    longer tell the coordinator to keep a GitHub watch or a patrol cron."""
    text = (ROOT / "docs" / "GITHUB_WORKFLOW.md").read_text(encoding="utf-8")
    for heading in ("統籌 session", "無人值守運作"):
        section = _section(text, heading)
        for word in ("監看", "巡檢 cron", "定時巡檢", "cron"):
            assert word not in section, (heading, word)
        assert "patrol.sh" in section


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (None, "none"),
        ('{"written_at": "2026-10-25T11:50:00Z"}', "ok 600"),
        ('{"written_at": "2026-10-25T11:49:59Z"}', "stale 601 2026-10-25T11:49:59Z"),
        ('{"written_at": "2026-10-25T19:51:00+08:00"}', "ok 540"),
        ("{", "unreadable"),
        ('{"pid": 1}', "unreadable"),
    ],
    ids=[
        "no-monitor",
        "ten-minutes",
        "past-ten-minutes",
        "offset",
        "partial",
        "no-time",
    ],
)
def test_the_watchdog_reads_the_monitor_heartbeat(tmp_path, content, expected) -> None:
    """AC-3: more than 10 minutes without a poll is a stop; no file is no monitor yet."""
    path = tmp_path / "monitor-heartbeat.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "ops" / "watchdog_helper.py"),
            "monitor-beat",
            str(path),
            str(NOW),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected
