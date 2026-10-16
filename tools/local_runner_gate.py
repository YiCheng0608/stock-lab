"""Cross-site and DNS-rebinding gate in front of a loopback-only local runner (pure ASGI, no framework import).

Same rules as the Issue 9 combos service (``browser_gate`` / ``json_content_type_gate`` in
``backend/app/institutional_dealer_direction_combos_scope7.py``), applied by the runner so ``backend/app`` stays untouched:
the runner never emits CORS headers, so a cross-origin preflight fails by itself; this additionally refuses the simple
requests a foreign page can still send, before the wrapped app touches any state, quota, source or private file.

* ``Host`` must be exactly ``127.0.0.1:<port>`` (a rebound name or a duplicated Host is refused).
* ``Sec-Fetch-Site`` (when sent) must be a single ``same-origin`` or ``none``.
* ``Origin`` (when sent) must be a single ``http://127.0.0.1:<port>``.
* Every POST must declare a single ``application/json`` (optional ``charset=utf-8``) Content-Type; a form or ``text/plain``
  simple request is refused. Other methods cannot be sent cross-site without a preflight, so they carry no Content-Type rule.

Limit: a browser without Fetch Metadata sends no ``Sec-Fetch-Site`` and no ``Origin`` on a GET, so a cross-site no-cors GET
from it still carries the exact Host and is admitted; its response is opaque, and every source-fetching call is a POST, which
the Content-Type rule stops (a saved-data GET that spends a read budget is the only residual, for browsers that old).
"""
from __future__ import annotations

import json
import re

JSON_MEDIA = re.compile(r"application/json(?:\s*;\s*charset=utf-8)?", re.I)
SAME_SITE_VALUES = ("same-origin", "none")


def _values(raw_headers, name):
    wanted = name.lower().encode("latin-1")
    return [bytes(v).decode("latin-1") for k, v in raw_headers if bytes(k).lower() == wanted]


def refusal(method, raw_headers, own_host):
    """(status, reason) to refuse a request, else None. Pure over ASGI ``(name, value)`` byte pairs."""
    if _values(raw_headers, "host") != [own_host]:
        return 403, "host_not_admitted"
    site = _values(raw_headers, "sec-fetch-site")
    if site and (len(site) != 1 or site[0].lower() not in SAME_SITE_VALUES):
        return 403, "cross_site_rejected"
    origin = _values(raw_headers, "origin")
    if origin and origin != ["http://" + own_host]:
        return 403, "origin_not_admitted"
    if method == "POST":
        types = _values(raw_headers, "content-type")
        if len(types) != 1 or JSON_MEDIA.fullmatch(types[0].strip()) is None:
            return 415, "content_type_json_required"
    return None


class BrowserGate:
    """ASGI front door: refuse before the wrapped app sees the request; lifespan passes through, websockets never do."""

    def __init__(self, app, *, port):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("local_port_required")
        self.app, self.own_host, self.refusals = app, "127.0.0.1:%d" % port, {}

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind == "lifespan":
            return await self.app(scope, receive, send)
        if kind == "websocket":
            await receive()
            return await send({"type": "websocket.close", "code": 1008})
        if kind != "http":
            return None
        refused = refusal(scope["method"], scope["headers"], self.own_host)
        if refused is None:
            return await self.app(scope, receive, send)
        status, reason = refused
        self.refusals[reason] = self.refusals.get(reason, 0) + 1
        body = json.dumps({"reason": reason}, separators=(",", ":")).encode("ascii")
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii")), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
        return None


def wrap(app, *, port):
    """The runner's one line: ``uvicorn.run(wrap(app, port=ARGS.port), ...)``; the wrapper's ``refusals`` feed shutdown receipts."""
    return BrowserGate(app, port=port)


def refusal_variants(method, port):
    """(label, headers, status, reason) a foreign page or a rebound name can produce for this method; headers include Host."""
    host, origin = "127.0.0.1:%d" % port, "http://127.0.0.1:%d" % port
    base = [("Host", host)] + ([("Content-Type", "application/json")] if method == "POST" else [])

    def replaced(name, value):
        return [(k, v) for k, v in base if k.lower() != name.lower()] + ([(name, value)] if value is not None else [])

    cases = []
    for bad in ("localhost:%d" % port, "127.0.0.1", "127.0.0.1:%d" % (port + 1), "127.0.0.1:%d.evil.example" % port, "evil.example",
                "evil.example:%d" % port, "[::1]:%d" % port, "127.0.0.1:0%d" % port, "127.0.0.2:%d" % port, ""):
        cases.append(("Host " + repr(bad), replaced("Host", bad), 403, "host_not_admitted"))
    cases.append(("duplicated Host", base + [("Host", "evil.example")], 403, "host_not_admitted"))
    for value in ("cross-site", "same-site", "Cross-Site", "", "same-origin, cross-site", "unknown"):
        cases.append(("Sec-Fetch-Site " + repr(value), base + [("Sec-Fetch-Site", value)], 403, "cross_site_rejected"))
    cases.append(("duplicated Sec-Fetch-Site", base + [("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")], 403, "cross_site_rejected"))
    for value in ("http://evil.example", "null", "http://localhost:%d" % port, "http://127.0.0.1:%d" % (port + 1), "https://127.0.0.1:%d" % port,
                  origin + "/", origin + ".evil.example", "", "http://evil.example, " + origin):
        cases.append(("Origin " + repr(value), base + [("Origin", value)], 403, "origin_not_admitted"))
    cases.append(("duplicated Origin", base + [("Origin", origin), ("Origin", "http://evil.example")], 403, "origin_not_admitted"))
    if method == "POST":
        for value in ("text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "application/json5",
                      "application/jsonx", "text/json", "application/json; charset=latin-1", "application/json; boundary=x", ""):
            cases.append(("Content-Type " + repr(value), replaced("Content-Type", value), 415, "content_type_json_required"))
        cases.append(("missing Content-Type", replaced("Content-Type", None), 415, "content_type_json_required"))
        cases.append(("duplicated Content-Type", base + [("Content-Type", "text/plain")], 415, "content_type_json_required"))
        # The classic CSRF shape: a no-cors text POST from a foreign page is refused on site, before the Content-Type rule.
        cases.append(("foreign no-cors text POST", replaced("Content-Type", "text/plain") + [("Origin", "http://evil.example"), ("Sec-Fetch-Site", "cross-site")],
                      403, "cross_site_rejected"))
    return cases


def admitted_variants(method, port):
    """(label, headers) the gate must let through: the preview proxy, an address-bar visit and a same-origin page fetch."""
    host, origin = "127.0.0.1:%d" % port, "http://127.0.0.1:%d" % port
    base = [("Host", host)] + ([("Content-Type", "application/json")] if method == "POST" else [])
    cases = [("exact Host", base), ("same-origin page", base + [("Origin", origin), ("Sec-Fetch-Site", "same-origin")]),
             ("address bar", base + [("Sec-Fetch-Site", "none")]), ("SAME-ORIGIN spelling", base + [("Sec-Fetch-Site", "SAME-ORIGIN")])]
    if method == "POST":
        cases.append(("JSON with charset", [("Host", host), ("Content-Type", "Application/JSON; charset=UTF-8"), ("Origin", origin)]))
    return cases
