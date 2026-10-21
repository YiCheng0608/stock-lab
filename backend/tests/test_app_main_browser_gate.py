"""Cross-site gate in front of ``app.main:app`` (Issue 125), RAM only.

No server, no fixed port, no source GET, no database file: the gate is driven as a raw ASGI app with a stub behind it, and the
real ``app.main`` app is driven through ``TestClient`` with a fake ``get_db`` and a socket guard. A refusal is proved to happen
before the wrapped app runs: it never calls ``receive`` (no body read), never starts a handler or dependency (``get_db`` is not
opened) and never reaches for the network. The same probes are positive on an admitted
request, so a silent probe cannot pass for a refusal.
"""

from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import app.api as api_module
from app import config
from app.browser_gate import BrowserGate, refusal
from app.main import app as product_app

PORT = 8000
HOST, LOCALHOST = "127.0.0.1:%d" % PORT, "localhost:%d" % PORT
OWN = "http://" + HOST
FRONTS = tuple(config.DEFAULT_CORS_ORIGINS)
JSON_BODY_METHODS = ("POST", "PUT", "PATCH")
GATED_METHODS = JSON_BODY_METHODS + ("DELETE",)
POSITION = b'{"symbol":"2330","shares":1000,"average_cost":10}'


def _raw(headers):
    return [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers]


def _base(method, host=HOST):
    return [("Host", host)] + (
        [("Content-Type", "application/json")] if method in JSON_BODY_METHODS else []
    )


def admitted_variants(method):
    """Headers the gate must let through: curl-style calls and the front end on each CORS origin (same-site or cross-site)."""
    base = _base(method)
    cases = [
        ("no Origin, 127.0.0.1", base),
        ("no Origin, localhost", _base(method, LOCALHOST)),
        ("address bar", base + [("Sec-Fetch-Site", "none")]),
        (
            "own-origin page",
            base + [("Origin", OWN), ("Sec-Fetch-Site", "same-origin")],
        ),
        (
            "SAME-ORIGIN spelling",
            base + [("Origin", OWN), ("Sec-Fetch-Site", "SAME-ORIGIN")],
        ),
        ("own origin without Fetch Metadata", base + [("Origin", OWN)]),
    ]
    for front in FRONTS:
        for site in ("same-site", "cross-site"):
            cases.append(
                (
                    "front end %s %s" % (front, site),
                    base + [("Origin", front), ("Sec-Fetch-Site", site)],
                )
            )
        cases.append(
            ("front end %s without Fetch Metadata" % front, base + [("Origin", front)])
        )
    if method in JSON_BODY_METHODS:
        cases.append(
            (
                "JSON with charset",
                [
                    ("Host", HOST),
                    ("Content-Type", "Application/JSON; charset=UTF-8"),
                    ("Origin", FRONTS[0]),
                    ("Sec-Fetch-Site", "same-site"),
                ],
            )
        )
    return cases


def refused_variants(method):
    """(label, headers, status, reason) a foreign page, a rebound name or a form post can produce."""
    base = _base(method)

    def replaced(name, value):
        return [(k, v) for k, v in base if k.lower() != name.lower()] + (
            [(name, value)] if value is not None else []
        )

    cases = []
    for bad in (
        "testserver",
        "localhost",
        "127.0.0.1",
        "127.0.0.1:%d" % (PORT + 1),
        "127.0.0.1:%d.evil.example" % PORT,
        "evil.example",
        "evil.example:%d" % PORT,
        "[::1]:%d" % PORT,
        "127.0.0.1:0%d" % PORT,
        "127.0.0.2:%d" % PORT,
        "localhost:%d.evil.example" % PORT,
        "",
    ):
        cases.append(("Host %r" % bad, replaced("Host", bad), 403, "host_not_admitted"))
    cases.append(("missing Host", replaced("Host", None), 403, "host_not_admitted"))
    cases.append(
        (
            "duplicated Host",
            base + [("Host", "evil.example:%d" % PORT)],
            403,
            "host_not_admitted",
        )
    )
    cases.append(
        (
            "DNS-rebound page",
            replaced("Host", "evil.example:%d" % PORT)
            + [
                ("Origin", "http://evil.example:%d" % PORT),
                ("Sec-Fetch-Site", "same-origin"),
            ],
            403,
            "host_not_admitted",
        )
    )
    for value in (
        "cross-site",
        "same-site",
        "Cross-Site",
        "",
        "same-origin, cross-site",
        "unknown",
    ):
        cases.append(
            (
                "Sec-Fetch-Site %r without Origin" % value,
                base + [("Sec-Fetch-Site", value)],
                403,
                "cross_site_rejected",
            )
        )
    for site in ("cross-site", "same-site"):
        cases.append(
            (
                "foreign Origin with Sec-Fetch-Site " + site,
                base + [("Origin", "http://evil.example"), ("Sec-Fetch-Site", site)],
                403,
                "cross_site_rejected",
            )
        )
    cases.append(
        (
            "duplicated Sec-Fetch-Site",
            base
            + [
                ("Origin", FRONTS[0]),
                ("Sec-Fetch-Site", "same-site"),
                ("Sec-Fetch-Site", "cross-site"),
            ],
            403,
            "cross_site_rejected",
        )
    )
    for value in (
        "http://evil.example",
        "null",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "https://127.0.0.1:5173",
        FRONTS[0] + "/",
        FRONTS[0] + ".evil.example",
        "http://127.0.0.1:%d" % (PORT + 1),
        "http://localhost:%d" % PORT,
        "",
        "http://evil.example, " + FRONTS[0],
    ):
        cases.append(
            (
                "Origin %r" % value,
                base + [("Origin", value)],
                403,
                "origin_not_admitted",
            )
        )
    cases.append(
        (
            "duplicated Origin",
            base + [("Origin", FRONTS[0]), ("Origin", "http://evil.example")],
            403,
            "origin_not_admitted",
        )
    )
    cases.append(
        (
            "same-origin value with a foreign Origin",
            base
            + [("Origin", "http://evil.example"), ("Sec-Fetch-Site", "same-origin")],
            403,
            "origin_not_admitted",
        )
    )
    # The classic CSRF shapes: a foreign page's no-cors form or text POST, refused on site before the Content-Type rule.
    if method in JSON_BODY_METHODS:
        cases.append(
            (
                "foreign no-cors text",
                replaced("Content-Type", "text/plain")
                + [("Origin", "http://evil.example"), ("Sec-Fetch-Site", "cross-site")],
                403,
                "cross_site_rejected",
            )
        )
        cases.append(
            (
                "foreign form",
                replaced("Content-Type", "application/x-www-form-urlencoded")
                + [("Origin", "null"), ("Sec-Fetch-Site", "cross-site")],
                403,
                "cross_site_rejected",
            )
        )
        for value in (
            "text/plain",
            "text/plain;charset=UTF-8",
            "application/x-www-form-urlencoded",
            "multipart/form-data; boundary=x",
            "application/json5",
            "application/jsonx",
            "text/json",
            "application/json; charset=latin-1",
            "application/json; boundary=x",
            "",
        ):
            cases.append(
                (
                    "Content-Type %r" % value,
                    replaced("Content-Type", value),
                    415,
                    "content_type_json_required",
                )
            )
            cases.append(
                (
                    "front end with Content-Type %r" % value,
                    replaced("Content-Type", value)
                    + [("Origin", FRONTS[0]), ("Sec-Fetch-Site", "same-site")],
                    415,
                    "content_type_json_required",
                )
            )
        cases.append(
            (
                "missing Content-Type",
                replaced("Content-Type", None),
                415,
                "content_type_json_required",
            )
        )
        cases.append(
            (
                "duplicated Content-Type",
                base + [("Content-Type", "text/plain")],
                415,
                "content_type_json_required",
            )
        )
    return cases


class Inner:
    """Stand-in for the wrapped app: answers 204 after reading the body the way a handler does."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await receive()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def drive(gate, method, headers, *, server=("127.0.0.1", PORT), kind="http"):
    sent, receives = [], []

    async def receive():
        receives.append(1)
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": kind,
        "method": method,
        "path": "/api/portfolio",
        "headers": _raw(headers),
        "server": server,
    }
    asyncio.run(gate(scope, receive, send))
    return sent, len(receives)


def cases_for(variants, methods):
    return [
        pytest.param(m, label, headers, *rest, id="%s %s" % (m, label))
        for m in methods
        for label, headers, *rest in variants(m)
    ]


@pytest.mark.parametrize(
    ("method", "label", "headers", "status", "reason"),
    cases_for(refused_variants, GATED_METHODS),
)
def test_refusal_happens_before_the_wrapped_app_reads_anything(
    method, label, headers, status, reason
):
    inner = Inner()
    gate = BrowserGate(inner, allowed_origins=config.DEFAULT_CORS_ORIGINS)
    sent, receives = drive(gate, method, headers)
    assert (inner.calls, receives) == (0, 0), label
    assert sent[0]["status"] == status and sent[1]["body"] == (
        '{"reason":"%s"}' % reason
    ).encode("ascii"), label
    assert (dict(sent[0]["headers"])[b"cache-control"], gate.refusals) == (
        b"no-store",
        {reason: 1},
    )


@pytest.mark.parametrize(
    ("method", "label", "headers"), cases_for(admitted_variants, GATED_METHODS)
)
def test_normal_front_end_and_headerless_local_callers_pass(method, label, headers):
    inner = Inner()
    gate = BrowserGate(inner, allowed_origins=config.DEFAULT_CORS_ORIGINS)
    sent, receives = drive(gate, method, headers)
    assert (inner.calls, receives, sent[0]["status"], gate.refusals) == (
        1,
        1,
        204,
        {},
    ), label


@pytest.mark.parametrize("method", ["post", "Put", "patch", "delete"])
def test_method_is_compared_upper_cased(method):
    assert refusal(
        method, _raw([("Host", "evil.example")]), ("127.0.0.1", PORT), FRONTS
    ) == (403, "host_not_admitted")
    assert refusal(
        method, _raw(_base(method.upper())[:1]), ("127.0.0.1", PORT), FRONTS
    ) == (
        (415, "content_type_json_required")
        if method.upper() in JSON_BODY_METHODS
        else None
    )


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_are_not_checked(method):
    inner = Inner()
    sent, _ = drive(
        BrowserGate(inner, allowed_origins=FRONTS),
        method,
        [("Host", "evil.example"), ("Origin", "http://evil.example")],
    )
    assert (inner.calls, sent[0]["status"]) == (1, 204)


@pytest.mark.parametrize(
    ("server", "admitted"),
    [
        (("127.0.0.1", PORT), True),
        (["127.0.0.1", PORT], True),
        (None, False),
        (("/run/api.sock", None), False),
        (("127.0.0.1", 0), False),
        (("127.0.0.1", True), False),
        (("127.0.0.1", "8000"), False),
        (("127.0.0.1",), False),
    ],
)
def test_port_comes_from_the_listening_socket(server, admitted):
    result = refusal("POST", _raw(_base("POST")), server, FRONTS)
    assert result == (None if admitted else (403, "host_not_admitted"))


def test_lifespan_and_websocket_scopes_pass_through():
    for kind in ("lifespan", "websocket"):
        inner = Inner()
        drive(
            BrowserGate(inner, allowed_origins=FRONTS),
            "POST",
            [("Host", "evil.example")],
            kind=kind,
        )
        assert inner.calls == 1, kind


# ---- the real product app -------------------------------------------------------------------------------------------------

ENDPOINTS = [
    ("POST", "/api/portfolio", POSITION, True),
    ("DELETE", "/api/portfolio/1", b"", True),
]
# The last column marks endpoints whose handler answers 404 from a fake db, so an admitted request is safe to run.
ENDPOINT_PARAMS = [
    pytest.param(m, path, body, handler_404, id="%s %s" % (m, path.split("?")[0]))
    for m, path, body, handler_404 in ENDPOINTS
]
# (label, base_url, headers, status, also refused for DELETE): DELETE carries no Content-Type rule.
FOREIGN = [
    (
        "testserver Host (TestClient default)",
        "http://testserver",
        {"Content-Type": "application/json"},
        403,
        True,
    ),
    (
        "foreign no-cors text",
        "http://" + HOST,
        {
            "Content-Type": "text/plain",
            "Origin": "http://evil.example",
            "Sec-Fetch-Site": "cross-site",
        },
        403,
        True,
    ),
    (
        "foreign JSON",
        "http://" + HOST,
        {
            "Content-Type": "application/json",
            "Origin": "http://evil.example",
            "Sec-Fetch-Site": "cross-site",
        },
        403,
        True,
    ),
    (
        "front end with form Content-Type",
        "http://" + HOST,
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": FRONTS[0],
            "Sec-Fetch-Site": "same-site",
        },
        415,
        False,
    ),
]


class Probe:
    """Counts what the wrapped app asks of the client: ``receive`` calls are body reads."""

    def __init__(self, wrapped):
        self.wrapped, self.receives = wrapped, 0

    async def __call__(self, scope, receive, send):
        async def counted():
            self.receives += 1
            return await receive()

        await self.wrapped(scope, counted, send)


@pytest.fixture
def probe(monkeypatch):
    state = SimpleNamespace(db_opened=0, network=[])

    class NoRows:
        def scalar(self, *args, **kwargs):
            return None

        def get(self, *args, **kwargs):
            return None

    def fake_db():
        state.db_opened += 1
        yield NoRows()

    def loopback(host):
        return host in ("127.0.0.1", "::1", "localhost") or str(host).startswith("127.")

    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def guarded_connect(sock, address, *args):
        if isinstance(address, tuple) and not loopback(address[0]):
            state.network.append(address)
            raise AssertionError("network access: %r" % (address,))
        return real_connect(sock, address, *args)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and not loopback(host):
            state.network.append(host)
            raise AssertionError("name lookup: %r" % (host,))
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    product_app.dependency_overrides[api_module.get_db] = fake_db
    yield state
    product_app.dependency_overrides.pop(api_module.get_db, None)


def client_for(base_url="http://" + HOST):
    wrapped = Probe(product_app)
    return TestClient(wrapped, base_url=base_url), wrapped


def test_gate_is_mounted_with_the_cors_origin_source_and_cors_stays_outermost():
    mounted = {m.cls: m.kwargs for m in product_app.user_middleware}
    assert mounted[BrowserGate]["allowed_origins"] is config.DEFAULT_CORS_ORIGINS
    assert mounted[CORSMiddleware]["allow_origins"] is config.DEFAULT_CORS_ORIGINS
    order = [m.cls for m in product_app.user_middleware]
    assert order.index(CORSMiddleware) < order.index(BrowserGate)


@pytest.mark.parametrize(("method", "path", "body", "handler_404"), ENDPOINT_PARAMS)
def test_every_write_endpoint_refuses_before_handler_body_db_and_source(
    probe, method, path, body, handler_404
):
    for label, base_url, headers, status, on_delete in FOREIGN:
        if method == "DELETE" and not on_delete:
            continue
        client, wrapped = client_for(base_url)
        response = client.request(method, path, headers=headers, content=body)
        assert response.status_code == status, (label, response.text)
        assert (wrapped.receives, probe.db_opened, probe.network) == (0, 0, []), label
    if handler_404:
        # Control: the same probes see an admitted front-end request, so the zeros above are not a silent probe.
        client, wrapped = client_for()
        headers = {"Origin": FRONTS[1], "Sec-Fetch-Site": "cross-site"}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        response = client.request(method, path, headers=headers, content=body)
        assert response.status_code == 404, response.text
        assert (probe.db_opened, probe.network) == (1, [])
        if path.startswith("/api/portfolio") and method == "POST":
            assert wrapped.receives >= 1


def test_refused_request_from_an_allowed_origin_is_still_readable_by_the_front_end(
    probe,
):
    client, _ = client_for()
    response = client.post(
        "/api/portfolio",
        content=POSITION,
        headers={
            "Content-Type": "text/plain",
            "Origin": FRONTS[0],
            "Sec-Fetch-Site": "same-site",
        },
    )
    assert (response.status_code, response.json()) == (
        415,
        {"reason": "content_type_json_required"},
    )
    assert response.headers["access-control-allow-origin"] == FRONTS[0]
    foreign = client.post(
        "/api/portfolio",
        content=POSITION,
        headers={
            "Content-Type": "text/plain",
            "Origin": "http://evil.example",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert (
        foreign.status_code == 403
        and "access-control-allow-origin" not in foreign.headers
    )
    assert (probe.db_opened, probe.network) == (0, [])


def test_preflight_and_reads_are_left_to_cors_and_the_router(probe):
    client, wrapped = client_for("http://testserver")
    preflight = client.options(
        "/api/portfolio",
        headers={
            "Origin": FRONTS[0],
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert (
        preflight.status_code,
        preflight.headers["access-control-allow-origin"],
    ) == (200, FRONTS[0])
    assert client.get("/api/health").json()["status"] == "ok"
    assert (wrapped.receives, probe.db_opened, probe.network) == (0, 0, [])
