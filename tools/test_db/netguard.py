"""Fail-closed network guard: evidence that a local read of the sample library makes no network call.

    python -B -X utf8 -m tools.test_db.netguard --log <file> [--] <arguments of tools.test_db>

Runs the test-database CLI with an audit hook that raises ``NetworkBlocked`` before any connection, name
resolution or datagram send, and appends one JSON line per process to ``--log``: ``armed`` when a process installed
the hook, ``blocked`` for every attempt. Child processes (product ``init-db``/schema checks, ``exec`` commands) get the
same hook through ``guard_site/sitecustomize.py`` on ``PYTHONPATH``; the log tells whether they were armed (a
``sitecustomize`` earlier on the path would silently prevent it). Stdlib only, no ``socket`` import, loadable by path.
The hook cannot be removed once installed, so run it in a process of its own, not inside a test runner.
"""

from __future__ import annotations

import json
import os
import sys

LOG_ENV = "TESTDB_NETGUARD_LOG"  # not STOCK_*: the product child environment keeps it
GUARD_SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_site")
BLOCKED_EVENTS = frozenset({
    "socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto",
    "socket.sendmsg", "urllib.Request", "http.client.connect", "http.client.send",
})


class NetworkBlocked(OSError):
    """A network call was attempted while the guard was armed."""


def _append(log: str, record: dict) -> None:
    record = {**record, "pid": os.getpid()}
    with open(log, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def install(log: str) -> None:
    """Arm this process; every blocked attempt is logged first, then raised."""

    def hook(event: str, args: tuple) -> None:
        if event in BLOCKED_EVENTS:
            _append(log, {"event": "blocked", "name": event, "args": repr(args[1:] if event == "socket.connect" else args)[:200]})
            raise NetworkBlocked(f"network call blocked by the test-db guard: {event}")

    sys.addaudithook(hook)
    _append(log, {"event": "armed", "argv0": os.path.basename(sys.argv[0] or "") if sys.argv else ""})


def read_log(log: str) -> list[dict]:
    if not os.path.isfile(log):
        return []
    with open(log, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] != "--log":
        print("usage: python -m tools.test_db.netguard --log <file> [--] <tools.test_db arguments>", file=sys.stderr)
        return 2
    log = os.path.abspath(args[1])
    args = args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    os.environ[LOG_ENV] = log
    inherited = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join([GUARD_SITE] + ([inherited] if inherited else []))
    install(log)
    from .cli import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
