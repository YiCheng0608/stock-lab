"""One HTTP attempt with a hard limit on its total time (Issue #539).

httpx's ``timeout`` bounds each connect, write and read on its own, so a
source that sends a few bytes just inside every read timeout keeps an attempt
going for as long as it likes: on 2026-11-06 a GET of a MOPS ``t21sc03`` page
got no answer for over 5 minutes (curl without a limit).  ``request`` runs the
attempt in a daemon thread and waits at most ``limit_seconds`` for it; past
that it raises ``AttemptTimeout`` and the thread is told to stop.  The thread
checks between chunks, and each read waits at most ``limit_seconds``, so an
abandoned attempt ends within one more read; it only holds the response
bytes, never the database.

DNS resolution is not covered by httpx's timeouts either; the wait here
covers it like the rest.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import httpx

from worker.sources import OfficialDataError


class AttemptTimeout(OfficialDataError):
    """The attempt did not finish within its limit."""


class DeadlineReached(AttemptTimeout):
    """No time is left before the step's deadline; not retried."""


def attempt_limit(url: str, attempt_seconds: float, deadline: float | None) -> float:
    """``attempt_seconds``, or what is left before ``deadline`` (``time.monotonic``)."""

    if deadline is None:
        return attempt_seconds
    left = deadline - time.monotonic()
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
    """Sleep ``delay`` before a retry, or raise when it would end past ``deadline``."""

    if isinstance(cause, DeadlineReached) or (
        deadline is not None and time.monotonic() + delay >= deadline
    ):
        raise DeadlineReached(
            f"official endpoint step deadline reached, no retry: {url}"
        ) from cause
    sleep(delay)


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
    raises ``AttemptTimeout``; transport errors are raised as httpx raised
    them.  The caller decides what to retry.
    """

    if limit_seconds <= 0:
        raise AttemptTimeout(f"official endpoint attempt has no time left: {url}")
    done = threading.Event()
    stop = threading.Event()
    box: dict[str, Any] = {}

    def attempt() -> None:
        try:
            with httpx.stream(
                method,
                url,
                headers=headers,
                data=data,
                timeout=httpx.Timeout(limit_seconds),
            ) as response:
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

    threading.Thread(target=attempt, name="bounded-http", daemon=True).start()
    if not done.wait(limit_seconds):
        stop.set()
        raise AttemptTimeout(
            f"official endpoint attempt over {limit_seconds:g} s: {url}"
        )
    if "error" in box:
        raise box["error"]
    return box["response"]
