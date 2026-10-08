"""Independent guarded chips-only API; --check is memory-only and never serves."""
from __future__ import annotations
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "m1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1"
EXPECTED_DIGEST = "sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true")
parser.add_argument("--serve", action="store_true")
parser.add_argument("--chips-series-stock-scope-7-opt-in", action="store_true")
parser.add_argument("--chips-gross-stock-scope-7-opt-in", action="store_true")
parser.add_argument("--policy-version")
parser.add_argument("--policy-digest")
parser.add_argument("--port", type=int, default=8799)
parser.add_argument("--deps", default="C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.deps")
ARGS = parser.parse_args()
if ARGS.check == ARGS.serve or not 1024 <= ARGS.port <= 65535:
    parser.error("select exactly --check or --serve and a finite local port")
if ARGS.chips_series_stock_scope_7_opt_in and ARGS.chips_gross_stock_scope_7_opt_in:
    parser.error("gross and daily-net profiles cannot be enabled together")
if ARGS.chips_gross_stock_scope_7_opt_in:
    EXPECTED_VERSION = "m1-chips-gross-trade-stock-scope-7-tpex-2026-10-06.1"
    EXPECTED_DIGEST = "sha256:ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144"
ARGS.policy_version = ARGS.policy_version or EXPECTED_VERSION
ARGS.policy_digest = ARGS.policy_digest or EXPECTED_DIGEST
if ARGS.serve and not (ARGS.chips_series_stock_scope_7_opt_in or ARGS.chips_gross_stock_scope_7_opt_in):
    parser.error("serve requires explicit chips-only source opt-in")
if (ARGS.policy_version, ARGS.policy_digest) != (EXPECTED_VERSION, EXPECTED_DIGEST):
    parser.error("independent external policy pins mismatch")
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests"), ARGS.deps]
COUNTS = {"disk_writes": 0, "mutations": 0, "private_reads": 0, "databases": 0, "subprocesses": 0, "network_rejections": 0}
CONTEXT = threading.local()
original_resolver = socket.getaddrinfo
original_pair = socket.socketpair


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
        active = getattr(CONTEXT, "active", False)
        local = isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
        allowed = pair and (local or address in {"127.0.0.1", "::1", "localhost"})
        if event == "socket.bind":
            allowed = allowed or (ARGS.serve and local and address[1] == ARGS.port)
        if event == "socket.getaddrinfo":
            allowed = allowed or (active and address == "www.tpex.org.tw" and args[1] == 443)
        if event == "socket.connect":
            allowed = allowed or (active and isinstance(address, tuple) and (address[0], address[1]) in getattr(CONTEXT, "addresses", set()))
        if not allowed:
            deny("network_rejections", "network outside request-local owned scope")


sys.addaudithook(audit)


def resolver(host, port, *args, **kwargs):
    answers = original_resolver(host, port, *args, **kwargs)
    if getattr(CONTEXT, "active", False) and host == "www.tpex.org.tw" and port == 443:
        CONTEXT.addresses.update((answer[4][0], answer[4][1]) for answer in answers)
    return answers


def socketpair(*args, **kwargs):
    CONTEXT.pair = True
    try:
        return original_pair(*args, **kwargs)
    finally:
        CONTEXT.pair = False


socket.getaddrinfo = resolver
socket.socketpair = socketpair
if ARGS.chips_gross_stock_scope_7_opt_in:
    from worker import tpex_institutional_gross_scope7 as series
    from app.institutional_gross_scope7 import create_app
else:
    from worker import tpex_institutional_series_scope7 as series
    from app.institutional_series_scope7 import create_app
series.check_policy(series.policy(), ARGS.policy_version, ARGS.policy_digest)
REQUESTS = 0


def fetch(url, cap, deadline):
    global REQUESTS
    if not ARGS.serve or not (ARGS.chips_series_stock_scope_7_opt_in or ARGS.chips_gross_stock_scope_7_opt_in) or REQUESTS >= 22 or url != series.URLS[REQUESTS]:
        raise PermissionError("finite exact source sequence required")
    parsed = urlsplit(url)
    assert parsed.scheme == "https" and parsed.hostname == "www.tpex.org.tw" and parsed.port is None and not parsed.fragment
    CONTEXT.active, CONTEXT.addresses = True, set()
    connection = None
    REQUESTS += 1
    request_deadline = min(deadline, time.monotonic() + 15)
    def remaining():
        budget = request_deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError("cooperative request deadline")
        return budget
    try:
        connection = http.client.HTTPSConnection("www.tpex.org.tw", 443, timeout=remaining(), context=ssl.create_default_context())
        connection.connect()
        connection.sock.settimeout(remaining())
        connection.request("GET", parsed.path + "?" + parsed.query, body=None, headers={"Accept": "text/csv,application/csv", "Accept-Encoding": "identity", "User-Agent": "taiwan-stock-research/chips-series-local"})
        connection.sock.settimeout(remaining())
        response = connection.getresponse()
        headers = response.getheaders()
        header_size = sum(len(k.encode("latin1")) + len(v.encode("latin1")) + 4 for k, v in headers)
        remaining()
        if header_size > 16384 or response.status != 200:
            raise ValueError("response status/header/deadline gate")
        content_type = response.getheader("Content-Type", "")
        encoding = response.getheader("Content-Encoding", "identity")
        if encoding.lower() != "identity":
            raise ValueError("compressed response forbidden")
        media = content_type.lower().replace(" ", "")
        if media.split(";")[0] not in ("text/csv", "application/csv") or ("charset=" in media and "charset=utf-8" not in media):
            raise ValueError("CSV content type required")
        parts, size = [], 0
        while True:
            remaining()
            response_socket = connection.sock or getattr(getattr(response.fp, "raw", None), "_sock", None)
            if response_socket is not None:
                response_socket.settimeout(remaining())
            part = response.read1(min(65536, cap + 1 - size))
            remaining()
            if not part:
                break
            parts.append(part); size += len(part)
            if size > cap:
                raise ValueError("source body cap")
        print(json.dumps({"source_request": REQUESTS, "status": response.status, "received_header_bytes_postcheck": header_size, "body_bytes": size}), flush=True)
        return {"body": b"".join(parts), "status": response.status, "content_type": content_type, "content_encoding": encoding}
    finally:
        if connection is not None:
            connection.close()
        CONTEXT.active, CONTEXT.addresses = False, set()


def main():
    print(json.dumps({"python": sys.version.split()[0], "policy_version": EXPECTED_VERSION, "policy_digest": EXPECTED_DIGEST, "seed_count": 0, "preloaded": False, "guards": COUNTS}), flush=True)
    if ARGS.check:
        import unittest
        names = ["test_institutional_gross_scope7"] if ARGS.chips_gross_stock_scope_7_opt_in else ["test_tpex_institutional_series_scope7", "test_institutional_series_scope7"]
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        import fastapi
        import httpx
        import uvicorn
        print(json.dumps({"check": result.wasSuccessful(), "versions": {"python": sys.version.split()[0], "fastapi": fastapi.__version__, "httpx": httpx.__version__, "uvicorn": uvicorn.__version__}, "source_requests": REQUESTS, "guards": COUNTS}), flush=True)
        return 0 if result.wasSuccessful() else 1
    import fastapi
    import uvicorn
    producer = series.Producer(fetch, version=ARGS.policy_version, pin=ARGS.policy_digest)
    print(json.dumps({"fastapi": fastapi.__version__, "uvicorn": uvicorn.__version__, "pid": os.getpid(), "owned_host": "127.0.0.1", "port": ARGS.port, "source_requests": 0}), flush=True)
    try:
        uvicorn.run(create_app(producer), host="127.0.0.1", port=ARGS.port, access_log=False, log_config=None, lifespan="off", loop="asyncio")
    finally:
        print(json.dumps({"shutdown": True, "source_requests": REQUESTS, "producer_requests": producer.request_count, "guards": COUNTS}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
