"""One HTTP attempt with a hard limit on its total time (Issue #539).

httpx's ``timeout`` bounds each connect, write and read on its own, so a
source that sends a few bytes just inside every read timeout keeps an attempt
going for as long as it likes: on 2026-11-06 a GET of a MOPS ``t21sc03`` page
got no answer for over 5 minutes (curl without a limit).  ``request`` runs the
attempt in a daemon thread and waits at most ``limit_seconds`` for it; past
that it raises ``AttemptTimeout``.

An abandoned attempt is closed before ``request`` returns (review of PR #541):
otherwise the retry a few seconds later would be a second connection to the
same host while the first still reads, which ``_throttle_official_host`` (it
spaces request starts) does not see, and MOPS answers clients that ask too
often with a block page.  The attempt's TCP socket is caught as it connects
(httpcore's ``trace`` extension) and shut down, which wakes the blocked read;
then ``request`` waits up to ``CLOSE_SECONDS`` for the thread to end.  A
thread still running after that (stuck before its socket exists, in DNS or
the TCP connect) makes ``AttemptStuck``, which is not retried.

DNS resolution is not covered by httpx's timeouts either; the wait here
covers it like the rest.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Callable

import httpx

from worker.sources import OfficialDataError

# How long an abandoned attempt may take to close.  The shut-down socket ends
# its read at once; this only bounds the wait.  attempt_limit keeps it inside
# the step's deadline.
CLOSE_SECONDS = 1.0


class AttemptTimeout(OfficialDataError):
    """The attempt did not finish within its limit; closed, may be retried."""

    retryable = True


class DeadlineReached(AttemptTimeout):
    """No time is left before the step's deadline; not retried."""

    retryable = False


class AttemptStuck(AttemptTimeout):
    """The abandoned attempt did not end within CLOSE_SECONDS; not retried."""

    retryable = False


def attempt_limit(url: str, attempt_seconds: float, deadline: float | None) -> float:
    """``attempt_seconds``, or what is left before ``deadline`` (``time.monotonic``)
    once the time to close an abandoned attempt is kept aside."""

    if deadline is None:
        return attempt_seconds
    left = deadline - time.monotonic() - CLOSE_SECONDS
    if left <= 0:
        raise DeadlineReached(f"official endpoint step deadline reached before {url}")
    return min(attempt_seconds, left)


def retry_wait(
    url: str,
    delay: float,
    deadline: float | None,
    cause: BaseException | None,
    sleep: Callable[[float], None],
) -> None:
    """Sleep ``delay`` before a retry, or raise when it would end past ``deadline``
    or ``cause`` is not to be retried."""

    if isinstance(cause, AttemptTimeout) and not cause.retryable:
        raise type(cause)(f"{cause} (not retried)") from cause
    if deadline is not None and time.monotonic() + delay >= deadline:
        raise DeadlineReached(
            f"official endpoint step deadline reached, no retry: {url}"
        ) from cause
    sleep(delay)


def _shut(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:  # already closed by the attempt
        pass


def request(
    method: str,
    url: str,
    *,
    limit_seconds: float,
    headers: dict[str, str] | None = None,
    data: Any = None,
) -> httpx.Response:
    """Send one request and read its whole body within ``limit_seconds``.

    Returns the response with its body read (``.content``, ``.text``), or
    raises ``AttemptTimeout`` (``AttemptStuck``) once the attempt is closed;
    transport errors are raised as httpx raised them.  The caller decides
    what to retry.
    """

    if limit_seconds <= 0:
        raise AttemptTimeout(f"official endpoint attempt has no time left: {url}")
    done = threading.Event()
    stop = threading.Event()
    box: dict[str, Any] = {}
    sockets: list[socket.socket] = []

    def trace(event: str, info: dict[str, Any]) -> None:
        if event != "connection.connect_tcp.complete":
            return
        sock = info["return_value"].get_extra_info("socket")
        if sock is None:
            return
        sockets.append(sock)
        if stop.is_set():  # abandoned while it was connecting
            _shut(sock)

    def attempt() -> None:
        try:
            with (
                httpx.Client(timeout=httpx.Timeout(limit_seconds)) as client,
                (
                    client.stream(
                        method,
                        url,
                        headers=headers,
                        data=data,
                        extensions={"trace": trace},
                    )
                ) as response,
            ):
                chunks: list[bytes] = []
                for chunk in response.iter_raw():
                    if stop.is_set():
                        return
                    chunks.append(chunk)
                # The raw bytes with the response's own headers: httpx decodes
                # them (content-encoding, charset) as it would have.
                box["response"] = httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=b"".join(chunks),
                    request=response.request,
                )
        except BaseException as exc:  # handed to the caller's thread
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=attempt, name="bounded-http", daemon=True)
    thread.start()
    if not done.wait(limit_seconds):
        stop.set()
        for sock in list(sockets):
            _shut(sock)
        thread.join(CLOSE_SECONDS)
        if thread.is_alive():
            raise AttemptStuck(
                f"official endpoint attempt over {limit_seconds:g} s did not close"
                f" within {CLOSE_SECONDS:g} s: {url}"
            )
        raise AttemptTimeout(
            f"official endpoint attempt over {limit_seconds:g} s: {url}"
        )
    if "error" in box:
        raise box["error"]
    return box["response"]
