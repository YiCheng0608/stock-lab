"""Wake listener of the event monitor (#338, B3): the host end of the container's waker.

The scheduler container's monitor cannot reach Orca, which runs on the Windows host. This
listener runs on the host, bound to 127.0.0.1 only (Docker Desktop forwards
host.docker.internal there), and answers two requests, each with
``Authorization: Bearer <token>``; a body, if any, is not read:

- ``POST /wake`` (tools/ops/http_wake.sh): wake the coordinator terminal with the local
  Orca CLI.
- ``POST /worktrees`` (tools/ops/http_orca.sh): the task worktrees' branches from the
  local ``orca worktree list``, in Orca's envelope, for the monitor's slot events. No
  list (orca failed) is an error (502), never an empty list.
- ``POST /terminals`` (tools/ops/http_orca.sh, #873): the engineer terminals of the task
  worktrees and whether each is at a permission or trust menu (``engineer_terminals``),
  for the monitor's engineer_prompt_blocked events; 502 when orca gives no list.
  ``wake_listener.py --terminals`` prints the same answer and exits: monitor.sh on the
  host (with the real orca) reads it that way.

Text sent into the coordinator terminal is an instruction to Claude, so the request
carries nothing that reaches the terminal: the terminal is the one the coordinator
heartbeat names, the count is read from the queue, and the text is this file's fixed
template. A request without the token, or with another, is refused (401). The token is
the value of the STOCK_WAKE_TOKEN= line of --token-file: the env file the user writes
for compose (#337), so the container and this listener read one value; at least 32
characters.

The wake itself is tools/ops/orca_wake.sh, the waker monitor.sh runs on the host: it
sends only once ``orca terminal wait --for tui-idle`` answers satisfied:true; a terminal
that ended answers that too, and then its send fails (send_failed); a coordinator at a
permission or trust menu is prompt_blocked (#720). Answers of /wake (JSON
{"result": ...}): sent, not_idle, prompt_blocked, send_failed, no_heartbeat (none, or a
handle that is not event_queue's HANDLE: never one starting with "-", which orca would
read as an option), nothing_pending. One request of each kind at a time, and none within
THROTTLE seconds of the last one answered (429 throttled). Requests refused for the
token are answered 401 and logged up to REFUSED_PER_MINUTE in the last 60 seconds, then
429, counted in the next 401's line (held_back=N); a Content-Length that is not a number
of bytes is 400. Each request
is a line in <logs>/wake-listener.log.

The port is held exclusively (no SO_REUSEADDR; SO_EXCLUSIVEADDRUSE on Windows): with
another program on it, the listener exits instead of sharing it.

``GET /health`` needs no token and answers only that this is the listener, so a start
can tell it from another program on the port. The coordinator session starts it with
tools/ops/wake_listener_start.sh (docs/ops/MONITOR.md), which does nothing while one
answers.

Usage: wake_listener.py --token-file F [--data-dir D] [--port P] [--bash B] [--orca O]
       wake_listener.py --terminals [--orca O]
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_queue import Queue, _heartbeat  # noqa: E402

HOST = "127.0.0.1"
PORT = 47338
TOKEN_KEY = "STOCK_WAKE_TOKEN"
MIN_TOKEN = 32
MAX_BODY = 1024
# Per kind of request: none answered within this many seconds of the last one.
THROTTLE = 30
# orca_wake.sh: a wait (15 s) and a send, each within its call timeout.
WAKE_TIMEOUT = 300
ORCA_TIMEOUT = 120
TEXT = "有 {n} 個事件，請處理佇列：bash tools/ops/patrol.sh（處理完以 --done 標記）"
RESULTS = {0: "sent", 3: "not_idle", 4: "prompt_blocked"}
KINDS = {"/wake": "wake", "/worktrees": "worktrees", "/terminals": "terminals"}
# engineer_terminals: each orca call within this many seconds, all of them within
# TERMINALS_BUDGET (listener_post gives a request 60 seconds).
TERMINAL_CALL_TIMEOUT = 15
TERMINALS_BUDGET = 40
# Rows of the rendered screen read for the menu's command.
MENU_ROWS = 60
# Box drawing, stripped from both ends of a screen row before it is read.
MENU_FRAME = "│┃║╭╮╰╯─━═┌┐└┘ \t"
# A row of only these is a rule inside the menu (the command sits between two).
MENU_RULE = set("╌┄┈─━═-")
# The heading Claude Code puts above the command of a permission menu: "Bash command",
# "PowerShell command"; the questions that end a permission or a trust menu.
MENU_HEADING = re.compile(r"^\S.* command$")
MENU_QUESTIONS = ("Do you want to", "Do you trust")
COMMAND_CHARS = 200
# Refused requests (no token, a wrong one) answered 401 and logged in any 60 seconds;
# past this, 429, counted in the next 401's line.
REFUSED_PER_MINUTE = 10
# GET /health: nothing but who answers (wake_listener_start.sh looks for it).
HEALTH = json.dumps({"result": "ok", "service": "stock-lab-wake"}).encode()


def read_token(path: Path) -> str:
    """The STOCK_WAKE_TOKEN= value of PATH; the rest of the file is not kept."""
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition("=")
        if key == TOKEN_KEY:
            token = value.strip().strip("\"'")
            if len(token) >= MIN_TOKEN and token.isascii() and token.isprintable():
                if " " not in token:
                    return token
            break
    raise SystemExit(f"{path}: 沒有 {TOKEN_KEY}=（至少 {MIN_TOKEN} 個字元、不含空白）")


def _orca_json(orca: str, *args: str, timeout: float):
    """The answer of `orca ARGS --json` when it says ok, else None."""
    try:
        done = subprocess.run(
            [orca, *args, "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=max(timeout, 1),
        )
        doc = json.loads(done.stdout.decode("utf-8"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or not isinstance(doc, dict) or doc.get("ok") is not True:
        return None
    return doc


def menu_command(rows) -> str:
    """The first line of the command a permission menu asks about, read off the rendered
    screen ROWS (#873): the line under the last "<Tool> command" heading before the
    menu's question; a trust menu, or a screen without the heading, gives the question
    itself; "" when no question is on the screen."""
    lines = [r.strip(MENU_FRAME) for r in rows if isinstance(r, str)]
    asked = [i for i, line in enumerate(lines) if line.startswith(MENU_QUESTIONS)]
    if not asked:
        return ""
    question = asked[-1]
    for at in range(question - 1, -1, -1):
        if MENU_HEADING.match(lines[at]):
            body = lines[at + 1 : question]
            # Claude Code 2.1.329 (read 2026-11-20): heading, a tip, the description,
            # then the command between two ╌ rules; without the rules, the first line.
            rules = [i for i, x in enumerate(body) if x and set(x) <= MENU_RULE]
            if rules:
                body = body[rules[0] + 1 :]
            command = next((x for x in body if x and not set(x) <= MENU_RULE), "")
            return command[:COMMAND_CHARS]
    return lines[question][:COMMAND_CHARS]


def engineer_terminals(orca: str) -> list[dict] | None:
    """The engineer terminals of the task worktrees (#873), each {"handle", "branch",
    "title", "agentWait", "command"}: the terminals `orca terminal list` puts on a
    refs/heads/task/* branch with an agentIdentity (Claude Code runs in it; the bare
    shell Orca opens in the same worktree has none). agentWait is `orca terminal show`'s,
    read as orca_wake.sh reads the coordinator's (#720): an object at a permission or
    trust menu, null at none, left out when Orca cannot tell or the show failed. At a
    menu, command is its first line (menu_command of `orca terminal read --screen`).
    None when the list cannot be read."""
    started = time.monotonic()

    def left() -> float:
        return min(
            TERMINAL_CALL_TIMEOUT, TERMINALS_BUDGET - (time.monotonic() - started)
        )

    doc = _orca_json(orca, "terminal", "list", timeout=left())
    rows = ((doc or {}).get("result") or {}).get("terminals")
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        handle, branch = row.get("handle"), row.get("branch")
        if not (isinstance(handle, str) and isinstance(branch, str)):
            continue
        if not branch.startswith("refs/heads/task/") or not row.get("agentIdentity"):
            continue
        entry = {"handle": handle, "branch": branch, "title": row.get("title") or ""}
        out.append(entry)
        if left() <= 0:
            continue  # out of time: Orca cannot tell, as with no agentWait
        shown = _orca_json(
            orca, "terminal", "show", f"--terminal={handle}", timeout=left()
        )
        terminal = ((shown or {}).get("result") or {}).get("terminal")
        if not isinstance(terminal, dict) or "agentWait" not in terminal:
            continue
        wait = terminal["agentWait"]
        entry["agentWait"] = wait
        if not isinstance(wait, dict):
            continue
        screen = _orca_json(
            orca,
            "terminal",
            "read",
            f"--terminal={handle}",
            "--screen",
            "--limit",
            str(MENU_ROWS),
            timeout=left(),
        )
        tail = (((screen or {}).get("result") or {}).get("terminal") or {}).get("tail")
        entry["command"] = menu_command(tail) if isinstance(tail, list) else ""
    return out


def terminals_answer(rows: list[dict]) -> str:
    """engineer_terminals' rows in Orca's envelope, as monitor.sh reads them."""
    return json.dumps({"ok": True, "result": {"terminals": rows}}, ensure_ascii=False)


class Waker:
    def __init__(self, logs: Path, bash: str, orca: str) -> None:
        self.logs = logs
        self.bash = bash
        self.orca = orca
        self.script = Path(__file__).resolve().parent / "orca_wake.sh"
        self._locks = {kind: threading.Lock() for kind in KINDS.values()}
        self._answered = {kind: -float(THROTTLE) for kind in KINDS.values()}
        self._refusals = threading.Lock()
        self._refused: deque[float] = deque()  # times of the 401s of the last minute
        self._held_back = 0  # 429s since the last 401

    def refuse(self) -> int:
        """The status of a request refused for its token: 401, or 429 past the limit
        of the last 60 seconds. The 429s are counted in the next 401's line."""
        with self._refusals:
            now = time.monotonic()
            while self._refused and now - self._refused[0] >= 60:
                self._refused.popleft()
            if len(self._refused) >= REFUSED_PER_MINUTE:
                self._held_back += 1
                return 429
            self._refused.append(now)
            held, self._held_back = self._held_back, 0
            self.log("refused reason=token" + (f" held_back={held}" if held else ""))
            return 401

    def answer(self, kind: str) -> tuple[int, str]:
        """(HTTP status, result) of a request of KIND: one at a time, throttled."""
        lock = self._locks[kind]
        if not lock.acquire(blocking=False):
            return 429, "throttled"
        try:
            if time.monotonic() - self._answered[kind] < THROTTLE:
                return 429, "throttled"
            status, result = {
                "wake": self.wake,
                "worktrees": self.worktrees,
                "terminals": self.terminals,
            }[kind]()
            self._answered[kind] = time.monotonic()
            return status, result
        finally:
            lock.release()

    def wake(self) -> tuple[int, str]:
        terminal, _, _ = _heartbeat(self.logs)  # "" unless event_queue's HANDLE
        if not terminal:
            return 200, "no_heartbeat"
        pending = len(Queue(self.logs).pending())
        if not pending:
            return 200, "nothing_pending"
        # Started windowless (pythonw.exe), its console twin reads the orca answers.
        python = Path(sys.executable)
        if python.stem.lower() == "pythonw":
            python = python.with_name("python" + python.suffix)
        env = {**os.environ, "ORCA_EXE": self.orca}
        env.setdefault("STOCK_PYTHON", python.as_posix())
        try:
            code = subprocess.run(
                [self.bash, str(self.script), terminal, TEXT.format(n=pending)],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=WAKE_TIMEOUT,
            ).returncode
        except (OSError, subprocess.TimeoutExpired):
            code = 1
        result = RESULTS.get(code, "send_failed")
        return 200, f"{result} terminal={terminal} pending={pending}"

    def worktrees(self) -> tuple[int, str]:
        try:
            done = subprocess.run(
                [self.orca, "worktree", "list", "--json"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=ORCA_TIMEOUT,
            )
            doc = json.loads(done.stdout.decode("utf-8"))
            rows = doc["result"]["worktrees"]
            if done.returncode != 0 or doc.get("ok") is not True:
                raise ValueError(doc.get("error"))
            branches = sorted(
                w["branch"]
                for w in rows
                if isinstance(w.get("branch"), str)
                and w["branch"].startswith("refs/heads/task/")
            )
        except Exception:  # no orca, a timeout, an answer that is not a list
            return 502, "orca_failed"
        worktrees = [{"branch": branch} for branch in branches]
        return 200, json.dumps({"ok": True, "result": {"worktrees": worktrees}})

    def terminals(self) -> tuple[int, str]:
        rows = engineer_terminals(self.orca)
        if rows is None:
            return 502, "orca_failed"
        return 200, terminals_answer(rows)

    def log(self, line: str) -> None:
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(self.logs / "wake-listener.log", "a", encoding="utf-8") as handle:
            handle.write(f"{at} {line}\n")


def handler(token: str, waker: Waker):
    expected = f"Bearer {token}".encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "stock-lab-wake"

        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _answer(self, status: int, result: str) -> None:
            self._send(status, json.dumps({"result": result}).encode())

        def do_POST(self) -> None:  # noqa: N802 (http.server's name)
            given = (self.headers.get("Authorization") or "").encode()
            if not hmac.compare_digest(given, expected):
                status = waker.refuse()
                result = "unauthorized" if status == 401 else "throttled"
                return self._answer(status, result)
            kind = KINDS.get(self.path)
            if kind is None:
                return self._answer(404, "not_found")
            text = self.headers.get("Content-Length")
            text = "0" if text is None else text.strip()
            if not (text.isascii() and text.isdigit()):  # empty, negative, not a number
                return self._answer(400, "bad_length")
            length = int(text)
            if length > MAX_BODY:
                return self._answer(413, "too_large")
            self.rfile.read(length)  # nothing in it is used
            status, result = waker.answer(kind)
            if kind in ("worktrees", "terminals") and status == 200:
                waker.log(f"{kind} count={result.count('refs/heads/')}")
                return self._send(200, result.encode())
            waker.log(f"{kind} result={result}")
            self._answer(status, result.split()[0])

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                return self._send(200, HEALTH)
            self._answer(405, "method_not_allowed")

        def do_PUT(self) -> None:  # noqa: N802
            self._answer(405, "method_not_allowed")

        do_DELETE = do_PATCH = do_PUT  # noqa: N815

        def log_message(self, *args) -> None:  # the wake log is enough
            pass

    return Handler


class ExclusiveServer(ThreadingHTTPServer):
    """The port to this listener alone: with a second listener, or another program
    on the port, the bind fails rather than share or take it."""

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--token-file", type=Path)
    parser.add_argument(
        "--terminals",
        action="store_true",
        help="印出 POST /terminals 的回答後結束（monitor.sh 在本機用真的 orca 時讀它，#873）",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            os.environ.get("STOCK_DATA_DIR") or Path.home() / "stock-lab-data"
        ),
        help="統籌的資料目錄；佇列與心跳在它的 logs/",
    )
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--bash", default=shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
    )
    parser.add_argument(
        "--orca",
        help="本機 Orca CLI（預設 PATH 上的 orca，再來是 Orca 的安裝目錄；"
        "設了 STOCK_WAKE_TEST 時必填，測試不碰真的 Orca）",
    )
    args = parser.parse_args(argv)
    if args.orca is None:
        if os.environ.get("STOCK_WAKE_TEST"):
            raise SystemExit("STOCK_WAKE_TEST：測試要以 --orca 指定假的 orca")
        args.orca = shutil.which("orca") or str(
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs/orca/resources/bin/orca.exe"
        )
    if args.terminals:
        # A command name (orca) as the program to run: orca.cmd on Windows.
        rows = engineer_terminals(shutil.which(args.orca) or args.orca)
        if rows is None:
            print("orca terminal list 讀不到", file=sys.stderr)
            return 1
        sys.stdout.reconfigure(encoding="utf-8")
        print(terminals_answer(rows))
        return 0
    if args.token_file is None:
        parser.error("--token-file 必填（--terminals 以外）")
    token = read_token(args.token_file)
    logs = args.data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    waker = Waker(logs, args.bash, args.orca)
    try:
        server = ExclusiveServer((HOST, args.port), handler(token, waker))
    except OSError as error:
        raise SystemExit(f"{HOST}:{args.port} 綁不到（已被占用？）：{error}")
    waker.log(f"start host={HOST} port={args.port} pid={os.getpid()}")
    print(f"wake listener on {HOST}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    waker.log("stop")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
