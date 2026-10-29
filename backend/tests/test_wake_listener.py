"""tools/ops/wake_listener.py and the container's clients http_wake.sh, http_orca.sh (#338).

The listener runs from the sandbox copy of tools/ops (test_coordinator_scripts.Harness) on
a free 127.0.0.1 port, with the harness's fake orca; the clients and monitor.sh call it
as the scheduler container does, with STOCK_WAKE_URL pointing at that port. The fake orca
is a bash script the listener runs directly, so these run where bash scripts run as
programs: in the image (CI backend, docker jobs), not on Windows.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from test_coordinator_scripts import BASH, NOW, Harness, _ok
from test_event_monitor import _comment, _coordinator, _pr, _records, _sends

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the fake orca is a bash script run as a program"
)

TOKEN = "t" * 40
TEMPLATE = "有 {n} 個事件，請處理佇列：bash tools/ops/patrol.sh（處理完以 --done 標記）"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Listener:
    def __init__(self, h: Harness) -> None:
        self.h = h
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.token_file = h.root / "auth.env"
        self.token_file.write_text(
            f"GH_TOKEN=x\nSTOCK_WAKE_TOKEN={TOKEN}\n", encoding="utf-8"
        )
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(self.h.ops / "wake_listener.py"),
                "--token-file",
                str(self.token_file),
                "--data-dir",
                str(self.h.data),
                "--port",
                str(self.port),
                "--bash",
                BASH,
                "--orca",
                str(self.h.bin / "orca"),
            ],
            env={**os.environ, "FAKE_DIR": self.h.fake.as_posix()},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        line = self.process.stdout.readline()
        assert "wake listener on 127.0.0.1" in line, line

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=30)
            self.process = None

    def post(self, path: str, body: bytes = b"", token: str | None = TOKEN):
        request = urllib.request.Request(self.url + path, data=body, method="POST")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        return self._open(request)

    def call(self, method: str, path: str):
        request = urllib.request.Request(self.url + path, method=method)
        request.add_header("Authorization", f"Bearer {TOKEN}")
        return self._open(request)

    @staticmethod
    def _open(request) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(request, timeout=60) as answer:
                return answer.status, json.loads(answer.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def log(self) -> str:
        path = self.h.data / "logs" / "wake-listener.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def env(self) -> dict[str, str]:
        return {"STOCK_WAKE_TOKEN": TOKEN, "STOCK_WAKE_URL": f"{self.url}/wake"}


@pytest.fixture
def h(tmp_path) -> Harness:
    h = Harness(tmp_path)
    h.answer("gh_pr_list", [_pr()])
    h.answer("gh_comments", [_comment(9, "2026-10-25T11:50:00Z")])
    h.answer("orca_terminal_wait", _ok({"wait": {"satisfied": True}}))
    h.answer("orca_terminal_send", _ok({"send": {}}))
    h.answer(
        "orca_worktree_list",
        _ok(
            {
                "worktrees": [
                    {"path": "C:/r", "branch": "refs/heads/master"},
                    {"path": "C:/a", "branch": "refs/heads/task/338-a"},
                    {"path": "C:/b", "branch": "refs/heads/feat/docker"},
                ]
            }
        ),
    )
    _coordinator(h, "2026-10-25T11:55:00Z")
    return h


@pytest.fixture
def listener(h):
    one = Listener(h)
    one.start()
    yield one
    one.stop()


def _queue(h: Harness, n: int) -> None:
    (h.data / "logs" / "events.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "type": "event",
                    "seq": i,
                    "id": f"comment:{i}",
                    "kind": "comment",
                    "detected_at": "2026-10-25T12:00:00Z",
                    "at": None,
                    "ref": "#338",
                    "summary": "x",
                    "url": "",
                }
            )
            + "\n"
            for i in range(1, n + 1)
        ),
        encoding="utf-8",
    )


def _container_monitor(h: Harness, listener: Listener, at: int = NOW):
    """monitor.sh as serve runs it in the container: the HTTP waker and orca shim."""
    result = h.run(
        "monitor.sh",
        "--once",
        "--waker",
        (h.ops / "http_wake.sh").as_posix(),
        "--orca",
        (h.ops / "http_orca.sh").as_posix(),
        MONITOR_NOW=str(at),
        **listener.env(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_a_request_without_the_right_token_wakes_nothing(h, listener) -> None:
    _queue(h, 2)
    for token in (None, "", "wrong", TOKEN[:-1], TOKEN + "x", TOKEN.upper()):
        assert listener.post("/wake", token=token) == (401, {"result": "unauthorized"})
        assert listener.post("/worktrees", token=token)[0] == 401
    assert h.calls("orca") == []
    assert listener.log().count("refused reason=token") == 12
    # The client: an empty token never leaves the container.
    result = h.run(
        "http_wake.sh", "x", "y", STOCK_WAKE_TOKEN="", STOCK_WAKE_URL=listener.url
    )
    assert result.returncode == 1 and "STOCK_WAKE_TOKEN is empty" in result.stderr


def test_only_post_to_wake_and_worktrees_is_answered(h, listener) -> None:
    _queue(h, 1)
    for method in ("GET", "PUT", "DELETE"):
        assert listener.call(method, "/wake") == (405, {"result": "method_not_allowed"})
    assert listener.post("/terminal/send") == (404, {"result": "not_found"})
    assert listener.post("/wake", body=b"x" * 2000) == (413, {"result": "too_large"})
    assert h.calls("orca") == []


def test_what_the_caller_sends_never_reaches_the_terminal(h, listener) -> None:
    """The terminal is the heartbeat's, the text the template, the count the queue's."""
    _queue(h, 2)
    body = json.dumps({"terminal": "term_evil", "text": "rm -rf /", "n": 99}).encode()
    assert listener.post("/wake", body=body) == (200, {"result": "sent"})
    assert _sends(h) == [
        f"terminal send --terminal term_coord --text {TEMPLATE.format(n=2)} --enter --json"
    ]
    assert (h.fake / "sent_text.txt").read_text(encoding="utf-8") == TEMPLATE.format(
        n=2
    )
    # The waker's own arguments are not sent either.
    h.run("http_wake.sh", "term_evil", "rm -rf /", **listener.env())
    assert "term_evil" not in "\n".join(h.calls("orca"))


def test_a_second_request_within_30_seconds_is_throttled(h, listener) -> None:
    _queue(h, 1)
    assert listener.post("/wake") == (200, {"result": "sent"})
    assert listener.post("/wake") == (429, {"result": "throttled"})
    assert listener.post("/worktrees")[0] == 200
    assert listener.post("/worktrees") == (429, {"result": "throttled"})
    assert len(_sends(h)) == 1
    result = h.run("http_wake.sh", "x", "y", **listener.env())
    assert result.returncode == 1 and "throttled" in result.stderr


def test_a_handle_that_is_not_a_handle_is_no_heartbeat(h, listener) -> None:
    _queue(h, 1)
    beat = h.data / "logs" / "coordinator-heartbeat.json"
    beat.write_text(
        json.dumps(
            {
                "session_id": "coord",
                "terminal_handle": "term_coord --text pwned",
                "written_at": "2026-10-25T11:55:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert listener.post("/wake") == (200, {"result": "no_heartbeat"})
    assert h.calls("orca") == []


def test_nothing_pending_sends_nothing(h, listener) -> None:
    assert listener.post("/wake") == (200, {"result": "nothing_pending"})
    assert h.calls("orca") == []


def test_an_ended_terminal_is_a_failed_wake_not_a_sent_one(h, listener) -> None:
    """orca answers tui-idle satisfied:true for a terminal that ended, then its send
    fails (seen 2026-10-29): send_failed, and the monitor records no wake done."""
    h.answer(
        "orca_terminal_send", {"ok": False, "error": {"code": "terminal_not_found"}}
    )
    result = _container_monitor(h, listener)
    assert "wake=failed terminal=term_coord" in result.stdout
    assert [(w["ok"], w["detail"]) for w in _records(h, "wake")] == [
        (False, "send_failed")
    ]
    assert "wake result=send_failed terminal=term_coord" in listener.log()


def test_a_missing_listener_is_a_failed_wake_tried_again_after_ten_minutes(h) -> None:
    down = Listener(h)  # not started
    result = _container_monitor(h, down)
    assert "wake=failed terminal=term_coord" in result.stdout
    assert "worktrees=failed" in result.stdout
    assert [(w["ok"], w["detail"]) for w in _records(h, "wake")] == [
        (False, "send_failed")
    ]
    events = [e["id"] for e in _records(h, "event")]
    assert events == ["pr:324", f"ci:324:{'c' * 12}:1:success", "comment:9"]
    _container_monitor(h, down, at=NOW + 60)  # not before ten minutes
    assert len(_records(h, "wake")) == 1
    down.start()
    try:
        _container_monitor(h, down, at=NOW + 600)
    finally:
        down.stop()
    # The listener back, the worktrees answer too: a slot event, woken with the rest.
    assert _records(h, "event")[-1]["kind"] == "slots"
    assert [(w["ok"], w["upto"]) for w in _records(h, "wake")] == [
        (False, 0),
        (True, 4),
    ]
    assert len(_sends(h)) == 1


def test_the_worktrees_are_the_task_branches_and_no_list_is_no_slot_event(
    h, listener
) -> None:
    _container_monitor(h, listener)
    slots = [e for e in _records(h, "event") if e["kind"] == "slots"]
    assert [s["summary"] for s in slots] == ["task worktree 1 個（上限 3）：task/338-a"]
    listener.stop()
    listener.start()  # a fresh throttle, for each request below
    assert listener.post("/worktrees") == (
        200,
        {"ok": True, "result": {"worktrees": [{"branch": "refs/heads/task/338-a"}]}},
    )
    # orca failing on the host: an error, and the poll records no slot event (not free
    # slots), as when orca fails for the monitor on Windows.
    h.answer(
        "orca_worktree_list", {"ok": False, "error": {"code": "runtime_unavailable"}}
    )
    listener.stop()
    listener.start()
    assert listener.post("/worktrees") == (502, {"result": "orca_failed"})
    listener.stop()
    listener.start()
    result = _container_monitor(h, listener, at=NOW + 60)
    assert "worktrees=failed" in result.stdout
    assert len([e for e in _records(h, "event") if e["kind"] == "slots"]) == 1
    shim = h.run("http_orca.sh", "terminal", "send", **listener.env())
    assert shim.returncode == 64


@pytest.mark.parametrize(
    "text",
    [
        "",
        "GH_TOKEN=x\n",
        "STOCK_WAKE_TOKEN=short\n",
        f"STOCK_WAKE_TOKEN={'a b' * 20}\n",
    ],
    ids=["empty", "no-key", "short", "space"],
)
def test_the_listener_refuses_to_start_without_a_token(h, text) -> None:
    one = Listener(h)
    one.token_file.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(h.ops / "wake_listener.py"),
            "--token-file",
            str(one.token_file),
            "--data-dir",
            str(h.data),
            "--port",
            str(one.port),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0 and "STOCK_WAKE_TOKEN" in result.stderr


# Started by the coordinator session (the user's decision, #338) ----------------------


def _start(h: Harness, port: int, *args: str, token_file=None):
    return h.run(
        "wake_listener_start.sh",
        *args,
        WAKE_LISTENER_PORT=str(port),
        WAKE_LISTENER_TOKEN_FILE=str(token_file or (h.root / "auth.env")),
    )


def _listener_pids(h: Harness) -> list[int]:
    path = h.data / "logs" / "wake-listener.log"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [
        int(pid)
        for pid in re.findall(r" start host=127\.0\.0\.1 port=\d+ pid=(\d+)", text)
    ]


def _end(pids: list[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def test_the_start_script_starts_one_listener_and_keeps_it(h) -> None:
    """The coordinator runs it at every take-over and patrol: a listener that answers is
    kept (it reads the heartbeat before each wake), so a second one never starts."""
    one = Listener(h)  # its port and token file; started by the script, not by start()
    try:
        first = _start(h, one.port)
        assert first.returncode == 0, first.stdout + first.stderr
        assert f"wake listener：已啟動（127.0.0.1:{one.port}" in first.stdout
        for _ in range(2):
            again = _start(h, one.port)
            assert again.returncode == 0
            assert (
                again.stdout.strip() == f"wake listener：執行中（127.0.0.1:{one.port}）"
            )
        assert len(_listener_pids(h)) == 1
        status = _start(h, one.port, "--status")
        assert (status.returncode, status.stdout.strip()) == (
            0,
            f"wake listener：執行中（127.0.0.1:{one.port}）",
        )
        # /health needs no token and tells nothing but who answers.
        with urllib.request.urlopen(f"{one.url}/health", timeout=10) as answer:
            assert json.loads(answer.read()) == {
                "result": "ok",
                "service": "stock-lab-wake",
            }
        _queue(h, 1)
        assert one.post("/wake") == (200, {"result": "sent"})
        patrol = h.run(
            "patrol.sh",
            "--session-id",
            "coord",
            "--terminal",
            "term_coord",
            WAKE_LISTENER_PORT=str(one.port),
        )
        assert f"wake listener：執行中（127.0.0.1:{one.port}）" in patrol.stdout
    finally:
        _end(_listener_pids(h))


def test_a_port_another_program_holds_is_reported(h) -> None:
    port = Listener(h).port
    other = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=h.root,
    )
    try:
        deadline = time.monotonic() + 30
        while _start(h, port, "--status").returncode == 1:  # not listening yet
            assert time.monotonic() < deadline
            time.sleep(0.2)
        result = _start(h, port)
        assert result.returncode == 2
        assert f"127.0.0.1:{port} 被別的程序占用" in result.stderr
        assert _listener_pids(h) == []
        patrol = h.run(
            "patrol.sh",
            "--session-id",
            "coord",
            "--terminal",
            "term_coord",
            WAKE_LISTENER_PORT=str(port),
        )
        assert patrol.returncode == 0 and "被別的程序占用" in patrol.stdout
    finally:
        other.terminate()
        other.wait(timeout=30)


def test_no_listener_is_reported_and_a_start_that_fails_says_why(h) -> None:
    port = Listener(h).port
    status = _start(h, port, "--status")
    assert status.returncode == 1 and "wake listener：沒在跑" in status.stdout
    assert _listener_pids(h) == []  # --status starts nothing
    result = _start(h, port, token_file=h.root / "missing.env")
    assert result.returncode == 1 and "wake listener：啟動失敗" in result.stderr
    bad = h.root / "short.env"
    bad.write_text("STOCK_WAKE_TOKEN=short\n", encoding="utf-8")
    result = _start(h, port, token_file=bad)
    assert result.returncode == 1 and "STOCK_WAKE_TOKEN" in result.stderr
    assert _start(h, port, "--status").returncode == 1
