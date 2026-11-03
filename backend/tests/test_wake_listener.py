"""tools/ops/wake_listener.py and the container's clients http_wake.sh, http_orca.sh (#338).

The listener runs from the sandbox copy of tools/ops (test_coordinator_scripts.Harness) on
a free 127.0.0.1 port, with the harness's fake orca; the clients and monitor.sh call it
as the scheduler container does, with STOCK_WAKE_URL pointing at that port. The fake orca
is a bash script: the wake reaches it through bash (orca_wake.sh) anywhere, but /worktrees
runs it as a program, which Windows cannot; those tests run on Linux only (the CI
backend job; tools/ci/docker_suite.json does not list this file).
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

# /worktrees runs the fake orca, a bash script, as a program.
needs_exec_orca = pytest.mark.skipif(
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
                "-X",
                "utf8",
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
                (self.h.bin / "orca").as_posix(),
            ],
            env={
                **os.environ,
                "FAKE_DIR": self.h.fake.as_posix(),
                "STOCK_WAKE_TEST": "1",
            },
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
    tokens = (None, "", "wrong", TOKEN[:-1], TOKEN + "x")
    for token in tokens:
        assert listener.post("/wake", token=token) == (401, {"result": "unauthorized"})
        assert listener.post("/worktrees", token=token)[0] == 401
    # Past ten refusals a minute: 429, and no line each (review item 4).
    for _ in range(5):
        assert listener.post("/wake", token=TOKEN.upper()) == (
            429,
            {"result": "throttled"},
        )
    # The right token is still answered.
    assert listener.post("/wake") == (200, {"result": "sent"})
    assert len(_sends(h)) == 1
    assert listener.log().count("refused reason=token") == 10
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
    for length in ("-1", "x", "1e3", " "):
        assert _raw_post(listener, length) == 400, length
    assert h.calls("orca") == []


def test_what_the_caller_sends_never_reaches_the_terminal(h, listener) -> None:
    """The terminal is the heartbeat's, the text the template, the count the queue's."""
    _queue(h, 2)
    body = json.dumps({"terminal": "term_evil", "text": "rm -rf /", "n": 99}).encode()
    assert listener.post("/wake", body=body) == (200, {"result": "sent"})
    assert _sends(h) == [
        f"terminal send --terminal=term_coord --text {TEMPLATE.format(n=2)} --enter --json"
    ]
    assert (h.fake / "sent_text.txt").read_text(encoding="utf-8") == TEMPLATE.format(
        n=2
    )
    # The waker's own arguments are not sent either.
    h.run("http_wake.sh", "term_evil", "rm -rf /", **listener.env())
    assert "term_evil" not in "\n".join(h.calls("orca"))


@needs_exec_orca
def test_a_second_request_within_30_seconds_is_throttled(h, listener) -> None:
    _queue(h, 1)
    assert listener.post("/wake") == (200, {"result": "sent"})
    assert listener.post("/wake") == (429, {"result": "throttled"})
    assert listener.post("/worktrees")[0] == 200
    assert listener.post("/worktrees") == (429, {"result": "throttled"})
    assert len(_sends(h)) == 1
    result = h.run("http_wake.sh", "x", "y", **listener.env())
    assert result.returncode == 1 and "throttled" in result.stderr


@pytest.mark.parametrize(
    "handle", ["term_coord --text pwned", "--enter", "-x", "--terminal=x", "term\u00e9"]
)
def test_a_handle_that_is_not_a_handle_is_no_heartbeat(h, handle) -> None:
    """Review item 2: a handle orca would read as an option (or anything else than
    letters, digits, _ and -, not starting with -) is never woken."""
    _queue(h, 1)
    beat = h.data / "logs" / "coordinator-heartbeat.json"
    beat.write_text(
        json.dumps(
            {
                "session_id": "coord",
                "terminal_handle": handle,
                "written_at": "2026-10-25T11:55:00Z",
            }
        ),
        encoding="utf-8",
    )
    one = Listener(h)  # a listener of its own, so each handle gets a fresh throttle
    one.start()
    try:
        assert one.post("/wake") == (200, {"result": "no_heartbeat"})
    finally:
        one.stop()
    assert h.calls("orca") == []
    # The waker refuses it too, and passes a good one as --terminal=<handle>.
    refused = h.run("orca_wake.sh", handle, "x", ORCA_EXE=(h.bin / "orca").as_posix())
    assert refused.returncode == 64 and h.calls("orca") == []


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


@needs_exec_orca
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


def _fresh(h: Harness) -> Listener:
    """A listener on a port of its own: a fresh throttle (the port is held exclusively,
    so a restart on the same port could wait for its old connections)."""
    one = Listener(h)
    one.start()
    return one


@needs_exec_orca
def test_the_worktrees_are_the_task_branches_and_no_list_is_no_slot_event(
    h, listener
) -> None:
    _container_monitor(h, listener)
    slots = [e for e in _records(h, "event") if e["kind"] == "slots"]
    assert [s["summary"] for s in slots] == ["task worktree 1 個（上限 3）：task/338-a"]
    for expected in (
        (
            200,
            {
                "ok": True,
                "result": {"worktrees": [{"branch": "refs/heads/task/338-a"}]},
            },
        ),
        "fail",
    ):
        if expected == "fail":
            # orca failing on the host: an error, and the poll records no slot event (not
            # free slots), as when orca fails for the monitor on Windows.
            h.answer(
                "orca_worktree_list",
                {"ok": False, "error": {"code": "runtime_unavailable"}},
            )
            expected = (502, {"result": "orca_failed"})
        one = _fresh(h)
        try:
            assert one.post("/worktrees") == expected
        finally:
            one.stop()
    one = _fresh(h)
    try:
        result = _container_monitor(h, one, at=NOW + 60)
        shim = h.run("http_orca.sh", "terminal", "send", **one.env())
    finally:
        one.stop()
    assert "worktrees=failed" in result.stdout
    assert len([e for e in _records(h, "event") if e["kind"] == "slots"]) == 1
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
    result = _direct(h, one, "--orca", (h.bin / "orca").as_posix())
    assert result.returncode != 0 and "STOCK_WAKE_TOKEN" in result.stderr


def _direct(
    h: Harness, one: Listener, *args: str, env=None
) -> subprocess.CompletedProcess:
    """wake_listener.py run in the foreground: for the cases where it exits at once."""
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(h.ops / "wake_listener.py"),
            "--token-file",
            str(one.token_file),
            "--data-dir",
            str(h.data),
            "--port",
            str(one.port),
            *args,
        ],
        env={**os.environ, "STOCK_WAKE_TEST": "1", **(env or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_under_stock_wake_test_the_orca_must_be_named(h) -> None:
    """The reviewer's first run reached the real orca: in tests, --orca is required."""
    result = _direct(h, Listener(h))
    assert result.returncode != 0 and "STOCK_WAKE_TEST" in result.stderr


def test_the_port_is_the_listeners_alone(h) -> None:
    """Review item 1: the listener itself refuses a port another program holds (not only
    the start script's probe), and a second listener cannot share the first's."""
    first = Listener(h)
    holder = socket.socket()
    holder.bind(("127.0.0.1", first.port))
    holder.listen()
    try:
        result = _direct(h, first, "--orca", (h.bin / "orca").as_posix())
    finally:
        holder.close()
    assert result.returncode != 0
    assert f"127.0.0.1:{first.port} 綁不到" in result.stderr
    first.start()
    try:
        second = _direct(h, first, "--orca", (h.bin / "orca").as_posix())
        assert second.returncode != 0 and "綁不到" in second.stderr
        assert first.post("/wake") == (200, {"result": "nothing_pending"})
    finally:
        first.stop()


def _raw_post(listener: Listener, length: str) -> int:
    """The status of a POST /wake with the token and this Content-Length, sent raw."""
    with socket.create_connection(("127.0.0.1", listener.port), timeout=30) as raw:
        raw.sendall(
            (
                "POST /wake HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Authorization: Bearer {TOKEN}\r\nContent-Length: {length}\r\n\r\n"
            ).encode()
        )
        return int(raw.recv(1024).split()[1])


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


def test_a_shell_that_exported_msys_no_pathconv_still_starts_and_patrols(h) -> None:
    """The handbook's local checks export MSYS_NO_PATHCONV=1 (for docker -v); with it,
    Git Bash passed /c/... to python.exe, which read C:/c/..., so the listener never
    started and patrol.sh misread the heartbeat (#338 review run). coordinator_lib.sh
    unsets it. Only Windows converts paths, so only there this can fail."""
    one = Listener(h)
    try:
        started = h.run(
            "wake_listener_start.sh",
            WAKE_LISTENER_PORT=str(one.port),
            WAKE_LISTENER_TOKEN_FILE=str(one.token_file),
            MSYS_NO_PATHCONV="1",
        )
        assert started.returncode == 0, started.stdout + started.stderr
        patrol = h.run(
            "patrol.sh",
            "--session-id",
            "coord",
            "--terminal",
            "term_coord",
            WAKE_LISTENER_PORT=str(one.port),
            MSYS_NO_PATHCONV="1",
        )
        assert patrol.returncode == 0, patrol.stdout + patrol.stderr
        assert f"wake listener：執行中（127.0.0.1:{one.port}）" in patrol.stdout
    finally:
        _end(_listener_pids(h))
