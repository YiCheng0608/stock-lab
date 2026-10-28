"""Cross-site and DNS-rebinding gate in front of the product API ``app.main:app`` (pure ASGI, no framework import).

Same idea as ``tools/local_runner_gate.py``, widened to the front end that really calls this API: the UI runs on
``http://localhost:5173`` or ``http://127.0.0.1:5173`` and sends cross-origin ``fetch`` calls to port 8000, so a legitimate
request may carry ``Sec-Fetch-Site: same-site`` or ``cross-site``. CORS only hides responses and stops preflights; a form or
``text/plain`` simple request still reaches the handler, so this refuses it before the wrapped app reads the body or touches
any state, quota, source or private file.

Checked for every POST, PUT, PATCH and DELETE (decided on ``method.upper()``); any other method (GET, HEAD, OPTIONS) is not:

* ``Host`` must be a single ``127.0.0.1:<port>`` or ``localhost:<port>``, ``<port>`` being the one the server listens on
  (``scope["server"]``), or one of ``public_hosts`` (``config.public_hosts``: loopback names on another port, such as a proxy's
  or a mapped container port); a rebound name, a missing port or a duplicated Host is refused.
* ``Origin`` (when sent) must be single and either in the allow list (the origins ``configure_cors`` admits,
  ``config.allowed_origins``) or this server's own origin ``http://<Host>``.
* ``Sec-Fetch-Site`` (when sent) must be single: ``same-origin`` and ``none`` pass; ``same-site`` and ``cross-site`` pass only
  with an admitted Origin; anything else is refused.
* POST, PUT and PATCH must declare a single ``application/json`` (optional ``charset=utf-8``) Content-Type; DELETE carries none.

A request without Origin and Sec-Fetch-Site (curl, scripts) is a non-browser caller and passes the Host and Content-Type rules.

Limits: ``--host 0.0.0.0`` or LAN access, IPv6 ``[::1]`` and a Unix socket (no ``scope["server"]`` port) are refused; a front end
on an origin outside the allow list is refused; a GET is never checked, so a saved-data GET that spends a read budget stays exposed.
"""

from __future__ import annotations

import json
import re

JSON_MEDIA = re.compile(r"application/json(?:\s*;\s*charset=utf-8)?", re.I)
LOCAL_NAMES = ("127.0.0.1", "localhost")
GATED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
JSON_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
SAME_SITE_VALUES = ("same-origin", "none")
CROSS_SITE_VALUES = ("same-site", "cross-site")


def _values(raw_headers, name):
    wanted = name.lower().encode("latin-1")
    return [
        bytes(v).decode("latin-1") for k, v in raw_headers if bytes(k).lower() == wanted
    ]


def _listen_port(server):
    port = server[1] if isinstance(server, (tuple, list)) and len(server) == 2 else None
    return port if type(port) is int and 1 <= port <= 65535 else None


def refusal(method, raw_headers, server, allowed_origins, public_hosts=()):
    """(status, reason) to refuse a request, else None. Pure over ASGI ``(name, value)`` byte pairs and ``scope["server"]``."""
    method = method.upper()
    if method not in GATED_METHODS:
        return None
    port, host = _listen_port(server), _values(raw_headers, "host")
    if (
        port is None
        or len(host) != 1
        or (
            host[0] not in ("%s:%d" % (name, port) for name in LOCAL_NAMES)
            and host[0] not in public_hosts
        )
    ):
        return 403, "host_not_admitted"
    origins = _values(raw_headers, "origin")
    origin_ok = len(origins) == 1 and (
        origins[0] in allowed_origins or origins[0] == "http://" + host[0]
    )
    site = _values(raw_headers, "sec-fetch-site")
    if site:
        kind = site[0].lower() if len(site) == 1 else ""
        if kind not in SAME_SITE_VALUES and not (
            kind in CROSS_SITE_VALUES and origin_ok
        ):
            return 403, "cross_site_rejected"
    if origins and not origin_ok:
        return 403, "origin_not_admitted"
    if method in JSON_BODY_METHODS:
        types = _values(raw_headers, "content-type")
        if len(types) != 1 or JSON_MEDIA.fullmatch(types[0].strip()) is None:
            return 415, "content_type_json_required"
    return None


class BrowserGate:
    """ASGI middleware: refuse before the wrapped app sees the request; lifespan and websocket scopes pass through."""

    def __init__(self, app, *, allowed_origins, public_hosts=()):
        self.app, self.allowed_origins, self.public_hosts, self.refusals = (
            app,
            frozenset(allowed_origins),
            frozenset(public_hosts),
            {},
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        refused = refusal(
            scope["method"],
            scope["headers"],
            scope.get("server"),
            self.allowed_origins,
            self.public_hosts,
        )
        if refused is None:
            return await self.app(scope, receive, send)
        status, reason = refused
        self.refusals[reason] = self.refusals.get(reason, 0) + 1
        body = json.dumps({"reason": reason}, separators=(",", ":")).encode("ascii")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
        return None
