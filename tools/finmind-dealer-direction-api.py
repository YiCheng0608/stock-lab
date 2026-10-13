"""Independent guarded Issue 9 chips-only API runner; --check is memory-only and never connects or serves.

The external policy (canonical bytes, SHA-256 pin and byte length) is supplied by parameters; nothing is
hard-coded here and the pin cannot be derived from the policy file. --check runs the in-memory regressions
under the same guards with every network name resolution and connection refused. --serve additionally needs a
reviewed explicit seal (--seal-file) and then lets ONE new source open exactly the seven policy URLs on
api.finmindtrade.com:443 (nothing else), once, inside the process; the originals stay in this process' RAM.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true")
parser.add_argument("--serve", action="store_true")
parser.add_argument("--chips-dealer-direction-combos-opt-in", action="store_true")
parser.add_argument("--policy-file")
parser.add_argument("--policy-sha256")
parser.add_argument("--policy-bytes", type=int)
parser.add_argument("--seal-file")
parser.add_argument("--port", type=int, default=8799)
parser.add_argument("--deps", default="C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.deps")
ARGS = parser.parse_args()
if ARGS.check == ARGS.serve or not 1024 <= ARGS.port <= 65535:
    parser.error("select exactly --check or --serve and a finite local port")
if not ARGS.chips_dealer_direction_combos_opt_in:
    parser.error("explicit chips-only source opt-in required")
if ARGS.serve and not (ARGS.policy_file and ARGS.policy_sha256 and ARGS.policy_bytes and ARGS.seal_file):
    parser.error("serve requires --policy-file, --policy-sha256, --policy-bytes and --seal-file")
if ARGS.check and ARGS.seal_file:
    parser.error("check never takes a seal")
if bool(ARGS.policy_file) != bool(ARGS.policy_sha256 and ARGS.policy_bytes):
    parser.error("policy file, SHA-256 and byte length are supplied together")
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests"), ARGS.deps]
HOST = "api.finmindtrade.com"
COUNTS = {"disk_writes": 0, "mutations": 0, "private_reads": 0, "databases": 0, "subprocesses": 0, "network_rejections": 0}
CONTEXT = threading.local()
original_resolver = socket.getaddrinfo
original_pair = socket.socketpair
ADDRESSES = set()
REQUESTS = 0


def deny(name, reason):
    COUNTS[name] += 1
    raise PermissionError(reason)


def audit(event, args):
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes, os.PathLike)):
            absolute = os.fsdecode(path).replace("\\", "/").lower()
            if "/appdata/local/taiwan-stock-research/" in absolute:
                deny("private_reads", "private read forbidden")
        if (isinstance(mode, str) and any(x in mode for x in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            deny("disk_writes", "disk writes forbidden")
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.chmod", "os.chown", "os.utime", "os.truncate", "tempfile.mkstemp", "tempfile.mkdtemp"}:
        deny("mutations", "filesystem mutation forbidden")
    if event == "subprocess.Popen":
        deny("subprocesses", "subprocess forbidden")
    if event == "sqlite3.connect" or event.startswith("sqlite3.connect"):
        deny("databases", "all database use forbidden")
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        address = args[1] if event in {"socket.connect", "socket.bind"} else args[0]
        pair = getattr(CONTEXT, "pair", False)
        local = isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
        allowed = pair and (local or address in {"127.0.0.1", "::1", "localhost"})
        if event == "socket.bind":
            allowed = allowed or (ARGS.serve and local and address[1] == ARGS.port)
        if event == "socket.getaddrinfo":
            allowed = allowed or (ARGS.serve and address == HOST and args[1] == 443)
        if event == "socket.connect":
            allowed = allowed or (ARGS.serve and isinstance(address, tuple) and (address[0], address[1]) in ADDRESSES)
        if not allowed:
            deny("network_rejections", "network outside the owned local scope and the single admitted upstream")


sys.addaudithook(audit)


def resolver(host, port, *args, **kwargs):
    answers = original_resolver(host, port, *args, **kwargs)
    if ARGS.serve and host == HOST and port == 443:
        ADDRESSES.update((answer[4][0], answer[4][1]) for answer in answers)
    return answers


def socketpair(*args, **kwargs):
    CONTEXT.pair = True
    try:
        return original_pair(*args, **kwargs)
    finally:
        CONTEXT.pair = False


socket.getaddrinfo = resolver
socket.socketpair = socketpair
from app import finmind_dealer_direction_source as src  # noqa: E402  (after the guards are installed)
from app.institutional_dealer_direction_combos_scope7 import create_app  # noqa: E402


def read_policy():
    """Read the supplied canonical policy once and verify it against the supplied external pin."""
    if not ARGS.policy_file:
        return None
    raw = Path(ARGS.policy_file).read_bytes()
    src.validate_policy(raw, ARGS.policy_sha256, ARGS.policy_bytes)
    return raw


def read_seal():
    """Build the sealed declarations from the reviewed seal file; this runner issues and authenticates nothing."""
    data = json.loads(Path(ARGS.seal_file).read_bytes().decode("utf-8"))
    if set(data) != {"start", "binding"}:
        raise ValueError("seal file keys")
    binding = src.ExecutionBinding(**data["binding"])
    start = dict(data["start"])
    start["coordinator_session_ids"] = tuple(start["coordinator_session_ids"])
    start["implementer_session_ids"] = tuple(start["implementer_session_ids"])
    return src.FinancialStart(**start, binding=binding), binding


class GuardedConnection:
    """Composition wrapper: only the policy's seven GETs, in order, with the fixed four headers."""

    def __init__(self, inner, policy):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_urls", tuple(policy["source"]["urls"]))

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        setattr(self._inner, name, value)

    def request(self, method, target, headers=None, **kwargs):
        global REQUESTS
        expected = self._urls[REQUESTS] if REQUESTS < len(self._urls) else None
        wanted = {"Accept-Encoding": "identity", "Connection": "close", "User-Agent": src.USER_AGENT, "Accept": src.ACCEPT}
        if method != "GET" or kwargs or expected is None or "https://" + HOST + target != expected or headers != wanted:
            raise PermissionError("finite exact source sequence required")
        REQUESTS += 1
        print(json.dumps({"source_request": REQUESTS}), flush=True)
        return self._inner.request(method, target, headers=headers)


def check_main():
    import unittest
    raw = read_policy()
    suite = unittest.defaultTestLoader.loadTestsFromNames(["test_institutional_dealer_direction_combos_scope7"])  # the source runner is standalone (own guards)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    import fastapi
    import httpx
    versions = {"python": sys.version.split()[0], "fastapi": fastapi.__version__, "httpx": httpx.__version__}
    try:
        import uvicorn
        versions["uvicorn"] = uvicorn.__version__
    except ImportError:
        versions["uvicorn"] = None
    print(json.dumps({"check": result.wasSuccessful(), "tests_run": result.testsRun, "policy_checked": raw is not None,
                      "versions": versions, "source_requests": REQUESTS, "guards": COUNTS}), flush=True)
    return 0 if result.wasSuccessful() else 1


def serve_main():
    import fastapi
    import uvicorn
    raw = read_policy()
    import json as _json
    policy = _json.loads(raw)
    start, binding = read_seal()
    factory = lambda host, timeout: GuardedConnection(src.native_connection(host, timeout), policy)  # noqa: E731
    source = src.DealerDirectionSource(policy_canonical=raw, expected_policy_sha256=ARGS.policy_sha256, expected_policy_bytes=ARGS.policy_bytes,
                                       financial_start=start, execution_binding=binding, connection_factory=factory)
    print(json.dumps({"fastapi": fastapi.__version__, "uvicorn": uvicorn.__version__, "pid": os.getpid(), "owned_host": "127.0.0.1",
                      "port": ARGS.port, "source_requests": 0, "state": source.state, "policy_sha256": ARGS.policy_sha256}), flush=True)
    try:
        uvicorn.run(create_app(source, port=ARGS.port), host="127.0.0.1", port=ARGS.port, access_log=False, log_config=None, lifespan="off", loop="asyncio")
    finally:
        state = source.state
        source.release()
        print(json.dumps({"shutdown": True, "pid": os.getpid(), "state_before_release": state, "state": source.state, "source_requests": REQUESTS,
                          "attempted": list(source.ledger.attempted) if source.ledger is not None else [], "guards": COUNTS}), flush=True)
    return 0


def main():
    print(json.dumps({"python": sys.version.split()[0], "mode": "check" if ARGS.check else "serve", "seed_count": 0, "preloaded": False, "guards": COUNTS}), flush=True)
    return check_main() if ARGS.check else serve_main()


if __name__ == "__main__":
    raise SystemExit(main())
