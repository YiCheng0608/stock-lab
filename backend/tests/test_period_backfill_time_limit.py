"""The period_backfill step's hard time limit against a dripping source (Issue #539 AC-1).

A local HTTP server answers 200 and then sends its body one byte at a time,
each byte well inside any read timeout.  httpx's ``timeout`` bounds each read,
so on its own it waits for the whole body; ``bounded_http`` ends the attempt
at its limit, and the step stops at its budget.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from test_period_backfill import factory  # noqa: F401  (fixture)
from worker import bounded_http, monthly_revenue, quarterly_fundamentals, sources
from worker import period_backfill as pb

# One byte every BYTE_SECONDS; a body of n bytes takes n × BYTE_SECONDS.
BYTE_SECONDS = 0.05
# What a loaded runner adds to a timed wait before the waiting thread runs
# again (#995).  The checks hold the code to its own bounds (the attempt's
# limit, CLOSE_SECONDS, the deadline) plus this, never to how fast the
# runner is: with 8 workers on 2 cores an abandoned attempt took up to
# 0.45 s of CLOSE_SECONDS to close and the step's DB writes up to 2.8 s,
# while no attempt ended later than 0.55 s before the deadline.
SLACK = 0.3
NOW = datetime(2026, 11, 6, 4, 0)  # inside 2026Q3's and 2026-10's windows


class Drip(BaseHTTPRequestHandler):
    body_bytes = 200  # 10 s: longer than any limit here, unless a test sets it
    stop = threading.Event()

    def _drip(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(self.body_bytes))
        self.end_headers()
        try:
            for _ in range(self.body_bytes):
                if self.stop.is_set():
                    return
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(BYTE_SECONDS)
        except OSError:  # the client gave up
            return

    do_GET = _drip
    do_POST = _drip

    def log_message(self, *_args) -> None:
        pass


@pytest.fixture
def drip():
    Drip.stop = threading.Event()
    Drip.body_bytes = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), Drip)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        Drip.stop.set()
        server.shutdown()
        server.server_close()


@pytest.fixture
def timed(monkeypatch):
    """Every bounded attempt: its URL, limit, start and end (``time.monotonic``)."""

    attempts: list[tuple[str, float, float, float]] = []
    real = bounded_http.request

    def spy(method, url, *, limit_seconds, **kwargs):
        began = time.monotonic()
        try:
            return real(method, url, limit_seconds=limit_seconds, **kwargs)
        finally:
            attempts.append((url, limit_seconds, began, time.monotonic()))

    monkeypatch.setattr(bounded_http, "request", spy)
    return attempts


@pytest.fixture
def waits(monkeypatch):
    """Every retry wait taken: when it began (``time.monotonic``) and how long."""

    taken: list[tuple[float, float]] = []
    real = bounded_http.retry_wait

    def spy(url, delay, deadline, cause, sleep):
        def timed_sleep(seconds):
            taken.append((time.monotonic(), seconds))
            sleep(seconds)

        return real(url, delay, deadline, cause, timed_sleep)

    monkeypatch.setattr(bounded_http, "retry_wait", spy)
    return taken


def test_a_dripping_body_outlasts_httpx_timeouts_but_not_the_attempt_limit(drip):
    Drip.body_bytes = 30  # 1.5 s in all, 0.05 s between bytes
    began = time.monotonic()
    response = httpx.get(f"{drip}/page", timeout=0.5)
    # Each read came within 0.5 s, so httpx waited for the whole body.
    assert response.content == b"x" * 30
    assert time.monotonic() - began >= 1.4

    began = time.monotonic()
    with pytest.raises(bounded_http.AttemptTimeout, match="attempt over 0.5 s"):
        bounded_http.request("GET", f"{drip}/page", limit_seconds=0.5)
    # The limit, then at most the wait for the abandoned attempt to close.
    assert time.monotonic() - began < 0.5 + bounded_http.CLOSE_SECONDS + SLACK


def test_a_bounded_attempt_returns_the_body_it_read_in_time(drip):
    Drip.body_bytes = 4
    response = bounded_http.request(
        "POST", f"{drip}/form", limit_seconds=2.0, data={"a": "1"}
    )
    assert (response.status_code, response.text) == (200, "xxxx")


def test_no_time_left_sends_nothing_and_is_not_retried(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("no request after the deadline")

    monkeypatch.setattr(bounded_http.httpx, "Client", refuse)
    monkeypatch.setattr(monthly_revenue, "_throttle_official_host", lambda url: None)
    slept: list[float] = []
    monkeypatch.setattr(monthly_revenue.time, "sleep", slept.append)
    with pytest.raises(bounded_http.DeadlineReached, match="deadline reached"):
        monthly_revenue.fetch_page(
            "http://127.0.0.1:9/x.html",
            attempt_seconds=30.0,
            deadline=time.monotonic() - 1,
        )
    assert slept == []


def test_an_abandoned_attempt_is_closed_before_the_next_one_starts(drip, monkeypatch):
    # Review of PR #541: a retry must not be a second connection to the host
    # while the abandoned one still reads (MOPS blocks clients that ask too
    # often).  Every attempt times out; when each next one starts, the
    # previous one's thread has ended and its socket is closed.
    shut: list = []
    real_shut = bounded_http._shut

    def record(sock):
        shut.append(sock)
        real_shut(sock)

    monkeypatch.setattr(bounded_http, "_shut", record)
    starts: list[tuple[int, list[int]]] = []
    real = bounded_http.request

    def spy(*args, **kwargs):
        alive = [t for t in threading.enumerate() if t.name == "bounded-http"]
        starts.append((len(alive), [sock.fileno() for sock in shut]))
        return real(*args, **kwargs)

    monkeypatch.setattr(bounded_http, "request", spy)
    monkeypatch.setattr(
        quarterly_fundamentals, "_throttle_official_host", lambda u: None
    )

    with pytest.raises(sources.OfficialDataError, match="transport retry exhausted"):
        quarterly_fundamentals.fetch_html(
            f"{drip}/ajax_t163sb04", {"a": "1"}, attempt_seconds=0.3
        )

    # Three attempts (0.25 s and 0.5 s apart); each abandoned one's socket was
    # shut down, and none was open or reading when the next began.
    assert [alive for alive, _fds in starts] == [0, 0, 0]
    assert [fds for _alive, fds in starts] == [[], [-1], [-1, -1]]
    assert len(shut) == 3
    assert not [t for t in threading.enumerate() if t.name == "bounded-http"]


def test_an_attempt_that_cannot_be_closed_is_not_retried(monkeypatch):
    # Stuck before its socket exists (DNS, the TCP connect): nothing to shut
    # down, so the attempt is not retried rather than opening a second one.
    release = threading.Event()

    class Hanging:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            release.wait(10)
            raise httpx.ConnectError("released")

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(bounded_http.httpx, "Client", Hanging)
    monkeypatch.setattr(bounded_http, "CLOSE_SECONDS", 0.2)
    monkeypatch.setattr(
        quarterly_fundamentals, "_throttle_official_host", lambda u: None
    )
    calls: list[float] = []
    real = bounded_http.request

    def spy(*args, limit_seconds, **kwargs):
        calls.append(limit_seconds)
        return real(*args, limit_seconds=limit_seconds, **kwargs)

    monkeypatch.setattr(bounded_http, "request", spy)
    began = time.monotonic()
    try:
        with pytest.raises(bounded_http.AttemptStuck, match="not retried"):
            quarterly_fundamentals.fetch_html(
                "http://127.0.0.1:9/x", {}, attempt_seconds=0.3
            )
    finally:
        release.set()
    assert calls == [0.3]
    assert time.monotonic() - began < 0.3 + 0.2 + 0.4


def test_a_retry_wait_past_the_deadline_is_not_taken():
    slept: list[float] = []
    with pytest.raises(bounded_http.DeadlineReached, match="no retry"):
        bounded_http.retry_wait("u", 20.0, time.monotonic() + 5, None, slept.append)
    bounded_http.retry_wait("u", 1.0, time.monotonic() + 5, None, slept.append)
    bounded_http.retry_wait("u", 20.0, None, None, slept.append)
    assert slept == [1.0, 20.0]


def test_the_step_stays_within_its_budget_on_a_dripping_source(
    drip,
    timed,
    waits,
    factory,  # noqa: F811  (the fixture imported above)
    monkeypatch,
    frozen_utcnow,
    tmp_path,
):
    frozen_utcnow.at = NOW
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(quarterly_fundamentals, "ENDPOINT", f"{drip}/ajax_t163sb04")
    monkeypatch.setattr(
        monthly_revenue,
        "PAGE_URL",
        drip + "/{market}/t21sc03_{year}_{month}_{page}.html",
    )
    budget, attempt = 2.0, 0.5
    close = bounded_http.CLOSE_SECONDS
    began = time.monotonic()
    result = pb.run_period_backfill(
        today=date(2026, 11, 6),
        sleep=lambda _seconds: None,
        budget_seconds=budget,
        attempt_seconds=attempt,
    )

    # The documented limit (SCHEDULING): no HTTP after the deadline, the
    # step's budget after it began.  The DB writes after the last page are
    # not bounded (on a loaded runner they took up to 2.8 s, #995).
    assert timed, "the real fetchers were used"
    # The step began before its first request, so its deadline is no later.
    first_request = min(start for _url, _limit, start, _end in timed)
    deadline = first_request + budget
    for url, limit, start, end in timed:
        assert "/ajax_t163sb04" in url, url  # the revenue sends nothing (below)
        assert limit <= attempt
        # Each attempt started with its limit and the time to close it
        # before the deadline, and ended within them.
        assert start + limit + close <= deadline + SLACK, (start, limit, deadline)
        assert end - start <= limit + close + SLACK, (limit, end - start)
    # Every retry wait taken was to end before the deadline.
    for at, seconds in waits:
        assert at + seconds <= deadline + SLACK, (at, seconds, deadline)
    assert result["status"] == "partial"
    assert result["fundamentals"]["status"] == "partial"
    # The first market-quarter's tries ran into the budget.
    assert re.search(
        "retry exhausted|deadline reached", result["fundamentals"]["warnings"][0]
    )
    # What was left of the step's budget when the fundamentals began: at most
    # the budget (2 itself on a coarse clock: Windows, about 15.6 ms; review
    # of PR #541), less at most the time to their first request (0.001 for
    # the 6 digits of ``:g``).
    left = re.fullmatch(
        r"time budget ([0-9.]+) s used up before 2026Q2:otc",
        result["fundamentals"]["aborted"],
    )
    assert left, result["fundamentals"]["aborted"]
    assert budget - (first_request - began) - 0.001 <= float(left.group(1)) <= budget
    # The revenue gets what the fundamentals left, under the second kept for
    # closing an attempt, so it sends nothing: its first page reaches the
    # deadline and the next one is over budget.  On a loaded runner the
    # fundamentals' writes can use it all (#995), and then the first one is.
    revenue = re.fullmatch(
        r"time budget ([0-9.e-]+) s used up before 2026-09:sii:([01])",
        result["revenue"]["aborted"],
    )
    assert revenue, result["revenue"]["aborted"]
    assert float(revenue.group(1)) < close
    warnings = result["revenue"].get("warnings", [])
    if revenue.group(2) == "1":
        assert len(warnings) == 1 and "deadline reached" in warnings[0], warnings
    else:
        assert warnings == []
