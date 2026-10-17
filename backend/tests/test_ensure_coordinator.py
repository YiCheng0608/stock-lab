"""tools/ops/ensure_coordinator.sh with fake orca/gh executables (Issue #171).

Each test builds a data directory with a heartbeat file, prepends a bin
directory holding fake ``orca`` and ``gh`` scripts to PATH and runs the real
watchdog through bash. The fakes record every call; the watchdog's clock is
pinned with WATCHDOG_NOW. Nothing touches Orca, GitHub or the real data
directory.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ops" / "ensure_coordinator.sh"
MANUAL = ROOT / "docs" / "GITHUB_WORKFLOW.md"
OLD = "term_old-1"
NEW = "term_new-1"
MASTER_ID = "repo-1::C:/checkouts/master"
WAKE_TEXT = (
    "看門狗：心跳逾時，請先寫心跳檔並依手冊巡檢；若額度仍未重置就回一句『額度未重置』。"
)
# Monday 2026-10-19 11:00 Taipei; NIGHT is the same Monday at 22:00 Taipei.
NOW = int(datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc).timestamp())
NIGHT = int(datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc).timestamp())


def _bash() -> str | None:
    if os.name == "nt":
        git_bash = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Git"
            / "bin"
            / "bash.exe"
        )
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required")

FAKE_ORCA = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/orca_calls.log"
ok='{"ok":true,"result":{}}'
case "$1 $2" in
  "terminal list")
    if [ -f "$d/orca_down" ] && [ ! -f "$d/opened" ]; then echo 'connect ECONNREFUSED' >&2; exit 1; fi
    cat "$d/terminals.json" ;;
  "open --json")
    [ -f "$d/open_fails" ] && exit 1
    touch "$d/opened"; echo "$ok" ;;
  "worktree list") cat "$d/worktrees.json" ;;
  "terminal create") echo '{"ok":true,"result":{"terminal":{"handle":"term_new-1","title":"統籌"}}}' ;;
  "terminal wait")
    if [ -f "$d/wait_unsatisfied" ]; then s=false; else s=true; fi
    echo "{\"ok\":true,\"result\":{\"wait\":{\"satisfied\":$s}}}" ;;
  "terminal send")
    shift 2
    while [ $# -gt 0 ]; do [ "$1" = --text ] && printf '%s\n' "$2" >>"$d/sent.txt"; shift; done
    echo "$ok" ;;
  *) echo "$ok" ;;
esac
"""

FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/gh_calls.log"
while [ $# -gt 0 ]; do
  [ "$1" = --body-file ] && { cat "$2"; echo '-----'; } >>"$d/gh_bodies.txt"
  shift
done
echo "https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-1"
"""


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Watchdog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.fake = root / "fake"
        self.data = root / "data"
        self.logs = self.data / "logs"
        for directory in (self.bin, self.fake, self.logs):
            directory.mkdir(parents=True)
        for name, body in (("orca", FAKE_ORCA), ("gh", FAKE_GH)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        self.terminals({OLD: "alive"})
        worktrees = [
            {
                "id": "repo-1::C:/checkouts/feature",
                "path": "C:/checkouts/feature",
                "branch": "refs/heads/task/1-x",
            },
            {
                "id": MASTER_ID,
                "path": "C:/checkouts/master",
                "branch": "refs/heads/master",
            },
        ]
        (self.fake / "worktrees.json").write_text(
            json.dumps({"ok": True, "result": {"worktrees": worktrees}}),
            encoding="utf-8",
        )

    def terminals(self, states: dict[str, str]) -> None:
        rows = [
            {
                "handle": handle,
                "connected": state == "alive",
                "orphaned": state == "orphaned",
                "title": "◑ 統籌",
            }
            for handle, state in states.items()
        ]
        (self.fake / "terminals.json").write_text(
            json.dumps({"ok": True, "result": {"terminals": rows}}), encoding="utf-8"
        )

    def heartbeat(self, age_minutes: int, handle: str = OLD, now: int = NOW) -> None:
        payload = {
            "session_id": "s-1",
            "terminal_handle": handle,
            "written_at": _iso(now - age_minutes * 60),
        }
        (self.logs / "coordinator-heartbeat.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def read_heartbeat(self) -> dict:
        return json.loads(
            (self.logs / "coordinator-heartbeat.json").read_text(encoding="utf-8")
        )

    def flag(self, name: str) -> None:
        (self.fake / name).touch()

    def run(
        self, *args: str, now: int = NOW, without_orca: bool = False
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        path = env.get("PATH", "")
        if without_orca:
            (self.bin / "orca").unlink(missing_ok=True)
            entries = path.split(os.pathsep)
            path = os.pathsep.join(
                e
                for e in entries
                if not any(
                    (Path(e) / n).exists() for n in ("orca", "orca.exe", "orca.cmd")
                )
            )
            env.pop("LOCALAPPDATA", None)
        env.update(
            PATH=str(self.bin) + os.pathsep + path,
            FAKE_DIR=self.fake.as_posix(),
            STOCK_DATA_DIR=self.data.as_posix(),
            STOCK_PYTHON=Path(sys.executable).as_posix(),
            WATCHDOG_NOW=str(now),
            WATCHDOG_ORCA_WAIT_SECONDS="1",
            WATCHDOG_ORCA_RETRY_SECONDS="0",
        )
        env.pop("STOCK_COORDINATOR_WORKTREE", None)
        result = subprocess.run(
            [BASH, SCRIPT.as_posix(), *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    def text(self, name: str) -> str:
        path = self.fake / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def calls(self) -> list[str]:
        return self.text("orca_calls.log").splitlines()

    def actions(self) -> list[str]:
        return [
            " ".join(call.split()[:2])
            for call in self.calls()
            if not call.startswith(("terminal list", "worktree list"))
        ]

    def log(self) -> str:
        return (self.logs / "ensure_coordinator.log").read_text(encoding="utf-8")

    def events(self) -> list[str]:
        return [line.split()[1] for line in self.log().splitlines()]


@pytest.fixture
def wd(tmp_path) -> Watchdog:
    return Watchdog(tmp_path)


def _handoff(old_handle: str | None) -> str:
    sys.path.insert(0, str(ROOT / "tools" / "ops"))
    try:
        import watchdog_helper
    finally:
        sys.path.pop(0)
    return watchdog_helper.handoff_text(
        MANUAL.read_text(encoding="utf-8").replace("\r\n", "\n"), old_handle or ""
    )


# --- AC-1: the four decisions ------------------------------------------------


def test_fresh_heartbeat_only_logs(wd):
    wd.heartbeat(10)
    result = wd.run()
    assert wd.events() == ["coordinator_alive"]
    assert wd.actions() == []
    assert "心跳 10 分鐘前，統籌在線" in result.stdout


def test_stalled_coordinator_gets_one_wake_text_per_hour(wd):
    wd.heartbeat(61)
    wd.run()
    assert wd.actions() == ["terminal send"]
    assert wd.text("sent.txt").strip() == WAKE_TEXT
    assert f"--terminal {OLD}" in wd.calls()[-1]
    # 30 minutes later the heartbeat is 91 minutes old: still stalled, but rate limited.
    wd.run(now=NOW + 30 * 60)
    assert wd.events() == ["wake_sent", "wake_rate_limited"]
    assert wd.actions() == ["terminal send"]


def test_wake_text_allowed_again_after_sixty_minutes(wd):
    wd.heartbeat(90)
    (wd.logs / "ensure_coordinator.log").write_text(
        f"{_iso(NOW - 61 * 60)} wake_sent handle={OLD} | 已送喚醒文\n", encoding="utf-8"
    )
    wd.run()
    assert wd.events()[-1] == "wake_sent"
    assert wd.actions() == ["terminal send"]


def test_stale_heartbeat_opens_coordinator_and_updates_heartbeat(wd):
    wd.heartbeat(180)
    wd.run()
    assert wd.actions() == [
        "terminal create",
        "terminal wait",
        "terminal send",
        "terminal rename",
    ]
    create = next(call for call in wd.calls() if call.startswith("terminal create"))
    assert f"--worktree id:{MASTER_ID}" in create
    assert (
        "--command claude --model claude-opus-5-5 --effort medium --autocompact 400k"
        in create
    )
    sent = wd.text("sent.txt").strip()
    assert sent == _handoff(OLD)
    assert f"舊統籌 terminal 為 {OLD}，" in sent
    heartbeat = wd.read_heartbeat()
    assert heartbeat["terminal_handle"] == NEW
    assert heartbeat["written_at"] == _iso(NOW)
    assert wd.events() == ["coordinator_open_attempt", "coordinator_opened"]
    # The next run sees the new heartbeat and does not open another one.
    wd.run(now=NOW + 15 * 60)
    assert wd.events()[-1] == "coordinator_alive"
    assert wd.actions().count("terminal create") == 1


def test_missing_terminal_opens_coordinator_without_closing_sentence(wd):
    wd.heartbeat(90)
    wd.terminals({})
    wd.run()
    sent = wd.text("sent.txt").strip()
    assert sent == _handoff(None)
    assert "舊統籌 terminal" not in sent and sent.endswith("回覆使用者一律繁體中文。")


def test_orphaned_terminal_opens_coordinator_and_keeps_old_handle(wd):
    wd.heartbeat(90)
    wd.terminals({OLD: "orphaned"})
    wd.run()
    assert "terminal create" in wd.actions()
    assert f"舊統籌 terminal 為 {OLD}，" in wd.text("sent.txt")


def test_no_heartbeat_file_opens_coordinator(wd):
    wd.run()
    assert wd.actions()[0] == "terminal create"
    assert "沒有可讀的心跳檔" in wd.log()


def test_orca_not_running_is_opened_then_checked(wd):
    wd.heartbeat(5)
    wd.flag("orca_down")
    wd.run()
    assert wd.actions() == ["open --json"]
    assert wd.events() == ["orca_open", "coordinator_alive"]


def test_orca_still_down_after_open_only_logs(wd):
    wd.heartbeat(180)
    wd.flag("orca_down")
    wd.flag("open_fails")
    wd.run()
    assert wd.actions() == ["open --json"]
    assert wd.events() == ["orca_open", "orca_unavailable"]
    assert wd.read_heartbeat()["terminal_handle"] == OLD


def test_orca_cli_not_found_only_logs(wd):
    wd.heartbeat(180)
    wd.run(without_orca=True)
    assert wd.events() == ["orca_not_found"]
    assert wd.read_heartbeat()["terminal_handle"] == OLD


def test_recent_handoff_marker_only_logs(wd):
    wd.heartbeat(180)
    marker = wd.logs / "handoff-s-1.json"
    marker.write_text('{"old_handle":"term_old-1"}', encoding="utf-8")
    os.utime(marker, (NOW - 10 * 60, NOW - 10 * 60))
    wd.run()
    assert wd.events() == ["handoff_in_progress"]
    assert wd.actions() == []
    os.utime(marker, (NOW - 20 * 60, NOW - 20 * 60))
    wd.run()
    assert "terminal create" in wd.actions()


def test_failed_open_is_closed_and_rate_limited(wd):
    wd.heartbeat(180)
    wd.flag("wait_unsatisfied")
    wd.run()
    assert wd.actions() == [
        "terminal create",
        "terminal wait",
        "terminal wait",
        "terminal close",
    ]
    assert wd.read_heartbeat()["terminal_handle"] == OLD
    wd.run(now=NOW + 15 * 60)
    assert wd.events()[-1] == "open_rate_limited"
    assert wd.actions().count("terminal create") == 1
    wd.run(now=NOW + 121 * 60)
    assert wd.actions().count("terminal create") == 2


def test_dry_run_prints_actions_without_create_or_send(wd):
    wd.heartbeat(180)
    result = wd.run("--dry-run")
    assert "將開新統籌" in result.stdout
    assert _handoff(OLD) in result.stdout
    assert wd.actions() == []
    assert wd.read_heartbeat()["terminal_handle"] == OLD
    wd.heartbeat(90)
    result = wd.run("--dry-run")
    assert f"將送喚醒文：{WAKE_TEXT}" in result.stdout
    assert wd.actions() == []


def test_manual_matches_watchdog_command():
    manual = MANUAL.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    command = "claude --model claude-opus-5-5 --effort medium --autocompact 400k"
    assert f'--command "{command}"' in manual
    assert f"COORDINATOR_COMMAND='{command}'" in script
    assert "<舊 handle>" in manual and _handoff(OLD).startswith(
        "你是 stock-lab 的統籌。"
    )


# --- AC-4: lock and anomaly detection ---------------------------------------------


def test_lock_prevents_reentry_and_stale_lock_is_removed(wd):
    wd.heartbeat(180)
    lock = wd.logs / "ensure_coordinator.lock"
    lock.mkdir()
    wd.run()
    assert wd.events() == ["locked"]
    assert wd.calls() == []
    old = time.time() - 31 * 60
    os.utime(lock, (old, old))
    wd.run()
    assert wd.events()[1:3] == ["lock_stale_removed", "coordinator_open_attempt"]
    assert not lock.exists()


def _news_llm_db(path: Path, batches: list[list[str]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE ingestion_runs (id INTEGER PRIMARY KEY, run_type TEXT, metadata_json TEXT)"
        )
        conn.execute(
            "INSERT INTO ingestion_runs (run_type, metadata_json) VALUES ('news', '{}')"
        )
        for statuses in batches:
            metadata = {
                "batches": [
                    {"batch": n, "status": s} for n, s in enumerate(statuses, start=1)
                ]
            }
            conn.execute(
                "INSERT INTO ingestion_runs (run_type, metadata_json) VALUES ('news_llm', ?)",
                (json.dumps(metadata),),
            )
    conn.close()


def _anomaly_fixtures(wd: Watchdog) -> None:
    wd.heartbeat(5, now=NIGHT)
    (wd.logs / "daily-20261016.log").write_text(
        "===== x start\n===== y end exit=0 seconds=1\n", encoding="utf-8"
    )
    (wd.logs / "daily-20261019.log").write_text(
        "===== 2026-10-19T18:30:00+08:00 start job=daily\n", encoding="utf-8"
    )
    news = wd.logs / "news-20261019.log"
    news.write_text("===== start job=news\n", encoding="utf-8")
    os.utime(news, (NIGHT - 7 * 3600, NIGHT - 7 * 3600))
    _news_llm_db(wd.data / "stock.db", [["done", "pending"], ["pending"], ["pending"]])


def test_anomalies_dry_run_prints_comments(wd):
    _anomaly_fixtures(wd)
    db = wd.data / "stock.db"
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    result = wd.run("--dry-run", now=NIGHT)
    assert result.stdout.count("將在 #1 留言：") == 3
    assert (
        "待使用者：daily 排程：台北 20261019 已過 21:30" in result.stdout
        and "沒有結束列" in result.stdout
    )
    assert "待使用者：news 排程：最新日誌寫於" in result.stdout
    assert "待使用者：news_llm：最近連續 3 批判讀都是 pending" in result.stdout
    assert wd.text("gh_calls.log") == ""
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


def test_anomaly_comment_at_most_once_per_day(wd):
    _anomaly_fixtures(wd)
    wd.run(now=NIGHT)
    calls = wd.text("gh_calls.log").splitlines()
    assert len(calls) == 3 and all(
        call.startswith("issue comment 1 --repo YiCheng0608/stock-lab")
        for call in calls
    )
    assert wd.text("gh_bodies.txt").count("待使用者：") == 3
    wd.run(now=NIGHT + 15 * 60)
    assert len(wd.text("gh_calls.log").splitlines()) == 3
    assert wd.events().count("anomaly_already_commented") == 3


def test_no_anomaly_when_jobs_are_healthy_or_not_scheduled(wd):
    wd.heartbeat(5, now=NIGHT)
    _news_llm_db(wd.data / "stock.db", [["pending", "pending"], ["done"]])
    wd.run(now=NIGHT)  # no daily/news logs yet: jobs not scheduled, nothing to report
    (wd.logs / "daily-20261019.log").write_text(
        "===== s start\n===== e end exit=0 seconds=9\n", encoding="utf-8"
    )
    news = wd.logs / "news-20261019.log"
    news.write_text("===== start\n", encoding="utf-8")
    os.utime(news, (NIGHT - 3600, NIGHT - 3600))
    result = wd.run(now=NIGHT)
    assert "將在 #1 留言" not in result.stdout
    assert wd.text("gh_calls.log") == ""
    assert not [event for event in wd.events() if event.startswith("anomaly")]
