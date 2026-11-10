"""tools/ops/turn_hook.cjs, the engineer sessions' Stop, UserPromptSubmit and SessionEnd
hook (Issue #595).

Each test runs the hook with node on a synthetic hook input: a project directory with
its own .git (the branch), a transcript JSONL in the shape Claude Code writes, and a data
directory in tmp_path (STOCK_DATA_DIR), so nothing reaches the real one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "tools" / "ops" / "turn_hook.cjs"
NODE = shutil.which("node")
NOW = 1793361600  # 2026-10-30T12:00:00Z
SID = "aaaaaaaa-1111-4111-8111-111111111111"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _prompt(text: str) -> dict:
    return {
        "type": "user",
        "origin": {"kind": "human"},
        "message": {"role": "user", "content": text},
    }


def _call(id_: str, command: str, text: str = "") -> dict:
    content = [
        {"type": "tool_use", "id": id_, "name": "Bash", "input": {"command": command}}
    ]
    if text:
        content.insert(0, {"type": "text", "text": text})
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _result(id_: str, error: bool = False, out: str = "ok") -> dict:
    return {
        "type": "user",
        "toolUseResult": {"stdout": out, "stderr": "", "interrupted": False},
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": id_,
                    "content": out,
                    "is_error": error,
                }
            ],
        },
    }


def _say(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


COMMENT = "gh issue comment 595 --repo YiCheng0608/stock-lab --body-file /c/t595/c.md"


class Hook:
    def __init__(
        self, root: Path, branch: str = "task/595-engineer-stop-events"
    ) -> None:
        self.root = root
        self.project = root / "wt"
        self.data = root / "data"
        (self.data / "logs").mkdir(parents=True)
        self.transcript = root / "transcript.jsonl"
        self.branch(branch)

    def branch(self, name: str, worktree: bool = False) -> None:
        git = self.project / ".git"
        if git.is_dir():
            shutil.rmtree(git)
        elif git.exists():
            git.unlink()
        self.project.mkdir(parents=True, exist_ok=True)
        if worktree:
            # A worktree: .git is a file pointing at the shared git directory.
            gitdir = self.root / "repo.git" / "worktrees" / "wt"
            gitdir.mkdir(parents=True, exist_ok=True)
            (gitdir / "HEAD").write_text(f"ref: refs/heads/{name}\n", encoding="utf-8")
            git.write_text(f"gitdir: {gitdir.as_posix()}\n", encoding="utf-8")
        else:
            git.mkdir()
            (git / "HEAD").write_text(f"ref: refs/heads/{name}\n", encoding="utf-8")

    def lines(self, *entries: dict) -> None:
        text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
        self.transcript.write_text(text, encoding="utf-8")

    def run(self, event: str = "Stop", at: int = NOW, env=None, **fields):
        payload = {
            "session_id": SID,
            "transcript_path": self.transcript.as_posix(),
            "cwd": self.project.as_posix(),
            "hook_event_name": event,
            **fields,
        }
        if event == "Stop":
            payload.setdefault("stop_hook_active", False)
        base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("STOCK_", "CLAUDE_", "TURN_HOOK"))
        }
        base.update(
            STOCK_DATA_DIR=self.data.as_posix(),
            CLAUDE_PROJECT_DIR=self.project.as_posix(),
            TURN_HOOK_NOW=str(at),
        )
        base.update(env or {})
        return subprocess.run(
            [NODE, HOOK.as_posix()],
            input=json.dumps(payload, ensure_ascii=False),
            env=base,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )

    @property
    def state_file(self) -> Path:
        return self.data / "logs" / "sessions" / f"{SID}.json"

    def state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))


def _blocked(result) -> bool:
    assert result.returncode == 0, result.stdout + result.stderr
    if not result.stdout.strip():
        return False
    out = json.loads(result.stdout)
    assert out == {"decision": "block", "reason": _reason()}
    return True


def _reason() -> str:
    return subprocess.run(
        [
            NODE,
            "-e",
            "process.stdout.write(require(process.argv[1]).REASON)",
            HOOK.as_posix(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def test_a_turn_that_commented_is_not_blocked(tmp_path) -> None:
    """AC-3 evidence 1: a turn with a successful gh issue comment stops; commented true."""
    h = Hook(tmp_path)
    h.lines(
        _prompt("請用 Read 工具讀取任務檔"),
        _call("t1", COMMENT, text="留開工"),
        _result(
            "t1",
            out="https://github.com/YiCheng0608/stock-lab/issues/595#issuecomment-1",
        ),
        _say("開工留言已貼。"),
    )
    result = h.run(last_assistant_message="開工留言已貼。")
    assert not _blocked(result)
    state = h.state()
    assert state == {
        "session_id": SID,
        "issue": 595,
        "branch": "task/595-engineer-stop-events",
        "cwd": h.project.as_posix(),
        "state": "stopped",
        "ended_at": "2026-10-30T12:00:00Z",
        "commented": True,
        "last_message": "開工留言已貼。",
        "background_tasks": 0,
    }


def test_a_turn_without_a_comment_is_blocked_once(tmp_path) -> None:
    """AC-3 evidence 1: no comment in the turn: blocked with the reason; the stop that
    follows (stop_hook_active) goes through, so the hook cannot loop."""
    h = Hook(tmp_path)
    h.lines(
        _prompt("開工"),
        _call("t1", COMMENT),
        _result("t1"),
        # A later prompt: the comment above belongs to the turn before.
        _prompt("背景 shell 被收掉了，接著呢？"),
        _call("t2", "docker compose -p task-595 run --rm api pytest -q"),
        _result("t2", error=True),
        _say("照規則我不會自己重開，要你決定"),
    )
    assert _blocked(h.run(last_assistant_message="照規則我不會自己重開，要你決定"))
    state = h.state()
    assert state["commented"] is False and state["state"] == "stopped"
    assert state["last_message"] == "照規則我不會自己重開，要你決定"
    assert not _blocked(h.run(stop_hook_active=True, at=NOW + 30))
    assert h.state()["ended_at"] == "2026-10-30T12:00:30Z"


@pytest.mark.parametrize(
    "command",
    [
        COMMENT,
        "gh pr comment 600 --body-file c.md",
        "gh pr create --base master --title x --body-file pr.md",
        "gh pr review 600 --comment --body-file r.md",
        "gh api repos/YiCheng0608/stock-lab/issues/595/comments -f body=@c.md",
        "gh api -X POST repos/YiCheng0608/stock-lab/issues/595/comments --input c.json",
        "cd /c/wt && gh api --method POST repos/o/r/issues/1/comments -F body=@c.md",
    ],
)
def test_each_way_of_commenting_counts(tmp_path, command: str) -> None:
    h = Hook(tmp_path)
    h.lines(_prompt("go"), _call("t1", command), _result("t1"), _say("done"))
    assert not _blocked(h.run())
    assert h.state()["commented"] is True


@pytest.mark.parametrize(
    "command",
    [
        "gh issue view 595 --comments",
        "gh api repos/YiCheng0608/stock-lab/issues/595/comments",
        "gh api 'repos/o/r/issues/comments?since=x' --jq '.[].body'",
        "gh api -X GET repos/o/r/issues/1/comments -f per_page=100",
        "gh pr view 600 --json comments",
    ],
)
def test_reading_comments_does_not_count(tmp_path, command: str) -> None:
    h = Hook(tmp_path)
    h.lines(_prompt("go"), _call("t1", command), _result("t1"), _say("done"))
    assert _blocked(h.run())
    assert h.state()["commented"] is False


def test_a_failed_comment_does_not_count(tmp_path) -> None:
    """A gh call that exited non-zero (is_error) posted nothing; a call without a result
    yet does not count either."""
    h = Hook(tmp_path)
    h.lines(
        _prompt("go"),
        _call("t1", COMMENT),
        _result("t1", error=True, out="HTTP 502"),
        _call("t2", COMMENT),
        _say("留言失敗"),
    )
    assert _blocked(h.run())


def test_only_task_branches_are_touched(tmp_path) -> None:
    """AC-3 evidence 1: master (the coordinator) and other branches: no output, nothing
    written; STOCK_TURN_HOOK=off also leaves a task branch alone."""
    h = Hook(tmp_path, branch="master")
    h.lines(_prompt("go"), _say("no comment"))
    for name in ("master", "feat/docker", "task/no-issue", "release/v1"):
        h.branch(name)
        for event in ("Stop", "UserPromptSubmit", "SessionEnd"):
            result = h.run(event)
            assert result.returncode == 0 and result.stdout == "", (name, event)
    h.branch("task/595-x")
    assert h.run(env={"STOCK_TURN_HOOK": "off"}).stdout == ""
    assert not (h.data / "logs" / "sessions").exists()


def test_a_worktree_branch_is_read_from_its_gitdir(tmp_path) -> None:
    h = Hook(tmp_path)
    h.branch("task/612-other", worktree=True)
    h.lines(_prompt("go"), _say("hi"))
    assert _blocked(h.run())
    assert h.state()["issue"] == 612 and h.state()["branch"] == "task/612-other"


def test_an_unreadable_transcript_never_blocks(tmp_path) -> None:
    """AC-3 evidence 1: the hook's own error exits 0 without blocking and is logged; the
    state says stopped with commented null (unknown, which the monitor counts as no
    comment)."""
    h = Hook(tmp_path)
    result = h.run(last_assistant_message="等你決定")
    assert not _blocked(result)
    log = (h.data / "logs" / "turn-hook.log").read_text(encoding="utf-8")
    assert "transcript unreadable" in log and SID in log
    state = h.state()
    assert state["state"] == "stopped" and state["commented"] is None
    assert state["last_message"] == "等你決定"


def test_no_data_directory_or_a_bad_input_never_blocks(tmp_path) -> None:
    h = Hook(tmp_path)
    h.lines(_prompt("go"), _say("hi"))
    missing = (tmp_path / "nowhere").as_posix()
    result = h.run(env={"STOCK_DATA_DIR": missing})
    assert result.returncode == 0 and result.stdout == ""
    assert "資料目錄不在" in result.stderr and not Path(missing).exists()
    bad = subprocess.run(
        [NODE, HOOK.as_posix()],
        input="not json",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "STOCK_DATA_DIR": h.data.as_posix()},
        timeout=60,
    )
    assert bad.returncode == 0 and bad.stdout == ""
    assert _blocked(h.run(session_id="../escape")) is False
    assert not (h.data / "logs" / "sessions" / "..").joinpath("escape.json").exists()


def test_prompt_and_session_end_update_the_state(tmp_path) -> None:
    """UserPromptSubmit: working, started_at, and no output (it would enter the context);
    SessionEnd: ended with the reason, the stop's fields kept."""
    h = Hook(tmp_path)
    h.lines(_prompt("go"), _say("x" * 700))
    _blocked(h.run(background_tasks=[{"id": "b1", "type": "shell"}]))
    stopped = h.state()
    assert len(stopped["last_message"]) == 500 and stopped["background_tasks"] == 1
    result = h.run("UserPromptSubmit", at=NOW + 60, prompt="繼續")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    working = h.state()
    assert (
        working["state"] == "working"
        and working["started_at"] == "2026-10-30T12:01:00Z"
    )
    result = h.run("SessionEnd", at=NOW + 120, reason="prompt_input_exit")
    assert result.returncode == 0 and result.stdout == ""
    ended = h.state()
    assert ended["state"] == "ended" and ended["ended_at"] == "2026-10-30T12:02:00Z"
    assert ended["end_reason"] == "prompt_input_exit"
    assert ended["issue"] == 595 and ended["last_message"] == "x" * 500


def test_settings_run_the_hook_on_its_three_events() -> None:
    settings = json.loads(
        (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    for event in ("Stop", "UserPromptSubmit", "SessionEnd"):
        (group,) = settings["hooks"][event]
        (hook,) = group["hooks"]
        assert hook["command"] == 'node "$CLAUDE_PROJECT_DIR/tools/ops/turn_hook.cjs"'
        # SessionEnd's default budget is 1.5 seconds; a timeout raises it.
        assert hook["timeout"] >= 10
