"""Host and Origin values the browser gate admits from settings (Issue 343), RAM only except the two app.main subprocesses.

``STOCK_API_PUBLIC_HOSTS`` and ``STOCK_API_ALLOWED_ORIGINS`` let the API admit a proxy's Host (nginx in front of ``/api``) and a
dev front end on another port. Unset, the gate must decide exactly as before: ``refusal_before_343`` is the gate as it was at
``ef5929f``, kept verbatim and compared over a header matrix. Set, the lists only ever hold loopback names with a port.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app import config
from app.browser_gate import BrowserGate, refusal

from test_app_main_browser_gate import Inner, _raw, drive

BACKEND = Path(__file__).resolve().parents[1]
PORT = 8000
CONTAINER = (
    "172.18.0.3",
    PORT,
)  # uvicorn --host 0.0.0.0 in a container: scope["server"] is the container address


# ---- the gate as it was before Issue 343 (browser_gate.py at ef5929f), the reference for "unset changes nothing" -----------

_JSON_MEDIA = re.compile(r"application/json(?:\s*;\s*charset=utf-8)?", re.I)


def _values_before(raw_headers, name):
    wanted = name.lower().encode("latin-1")
    return [
        bytes(v).decode("latin-1") for k, v in raw_headers if bytes(k).lower() == wanted
    ]


def _listen_port_before(server):
    port = server[1] if isinstance(server, (tuple, list)) and len(server) == 2 else None
    return port if type(port) is int and 1 <= port <= 65535 else None


def refusal_before_343(method, raw_headers, server, allowed_origins):
    method = method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    port, host = _listen_port_before(server), _values_before(raw_headers, "host")
    if (
        port is None
        or len(host) != 1
        or host[0]
        not in ("%s:%d" % (name, port) for name in ("127.0.0.1", "localhost"))
    ):
        return 403, "host_not_admitted"
    origins = _values_before(raw_headers, "origin")
    origin_ok = len(origins) == 1 and (
        origins[0] in allowed_origins or origins[0] == "http://" + host[0]
    )
    site = _values_before(raw_headers, "sec-fetch-site")
    if site:
        kind = site[0].lower() if len(site) == 1 else ""
        if kind not in ("same-origin", "none") and not (
            kind in ("same-site", "cross-site") and origin_ok
        ):
            return 403, "cross_site_rejected"
    if origins and not origin_ok:
        return 403, "origin_not_admitted"
    if method in {"POST", "PUT", "PATCH"}:
        types = _values_before(raw_headers, "content-type")
        if len(types) != 1 or _JSON_MEDIA.fullmatch(types[0].strip()) is None:
            return 415, "content_type_json_required"
    return None


def _one(name, values):
    """Header variants for one name: absent, each value once, and the first two values duplicated."""
    return (
        [[]] + [[(name, v)] for v in values] + [[(name, values[0]), (name, values[1])]]
    )


MATRIX_HOSTS = [
    "127.0.0.1:8000",
    "localhost:8000",
    "localhost:8080",
    "127.0.0.1:8080",
    "localhost:5174",
    "api:8000",
    "localhost:9999",
    "LOCALHOST:8000",
    "localhost",
    "*",
    "",
    "evil.example:8000",
    "user@localhost:8000",
    "localhost:8000/api",
]
MATRIX_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://localhost:8080",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://evil.example",
    "null",
    "*",
    "",
    "http://localhost:5173/",
    "http://user@localhost:5173",
]
MATRIX_SITES = ["same-origin", "none", "same-site", "cross-site", "SAME-ORIGIN", ""]
MATRIX_TYPES = ["application/json", "application/json; charset=utf-8", "text/plain"]
MATRIX_SERVERS = [("127.0.0.1", PORT), CONTAINER, ("127.0.0.1", 8080), None]


def matrix():
    for method, server in itertools.product(
        ("GET", "POST", "PUT", "PATCH", "DELETE", "post"), MATRIX_SERVERS
    ):
        for host, origin, site, ctype in itertools.product(
            _one("Host", MATRIX_HOSTS),
            _one("Origin", MATRIX_ORIGINS),
            _one("Sec-Fetch-Site", MATRIX_SITES),
            _one("Content-Type", MATRIX_TYPES),
        ):
            yield method, _raw(host + origin + site + ctype), server


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {config.PUBLIC_HOSTS_ENV: "", config.ALLOWED_ORIGINS_ENV: ""},
        {config.PUBLIC_HOSTS_ENV: "  ", config.ALLOWED_ORIGINS_ENV: " "},
    ],
    ids=["unset", "empty", "blank"],
)
def test_unset_or_blank_settings_keep_the_defaults(environ):
    assert config.allowed_origins(environ) is config.DEFAULT_CORS_ORIGINS
    assert config.public_hosts(environ) == ()


def test_without_settings_the_gate_decides_exactly_as_before_issue_343():
    origins, hosts = config.allowed_origins({}), config.public_hosts({})
    outcomes, total = {}, 0
    for method, headers, server in matrix():
        before = refusal_before_343(
            method, headers, server, config.DEFAULT_CORS_ORIGINS
        )
        assert refusal(method, headers, server, origins, hosts) == before, (
            method,
            headers,
            server,
        )
        assert refusal(method, headers, server, origins) == before
        outcomes[before] = outcomes.get(before, 0) + 1
        total += 1
    # The matrix reaches every decision, so agreement is not agreement on one branch.
    assert set(outcomes) == {
        None,
        (403, "host_not_admitted"),
        (403, "cross_site_rejected"),
        (403, "origin_not_admitted"),
        (415, "content_type_json_required"),
    }, outcomes
    assert total > 100000


def test_a_gate_built_without_public_hosts_is_the_gate_before_issue_343():
    sample = list(itertools.islice(matrix(), 0, None, 97))
    for method, headers, server in sample:
        inner = Inner()
        gate = BrowserGate(inner, allowed_origins=config.DEFAULT_CORS_ORIGINS)
        scope_headers = [
            (bytes(k).decode("latin-1"), bytes(v).decode("latin-1")) for k, v in headers
        ]
        sent, _ = drive(gate, method, scope_headers, server=server)
        before = refusal_before_343(
            method, headers, server, config.DEFAULT_CORS_ORIGINS
        )
        assert sent[0]["status"] == (204 if before is None else before[0])


# ---- set values -------------------------------------------------------------------------------------------------------------


def gate_for(environ):
    inner = Inner()
    gate = BrowserGate(
        inner,
        allowed_origins=config.allowed_origins(environ),
        public_hosts=config.public_hosts(environ),
    )
    return gate, inner


def outcome(gate, inner, headers, server=CONTAINER, method="POST"):
    if method != "DELETE":
        headers = headers + [("Content-Type", "application/json")]
    calls = inner.calls
    sent, receives = drive(gate, method, headers, server=server)
    if inner.calls > calls:
        assert (sent[0]["status"], receives) == (204, 1)
        return "admitted"
    assert receives == 0
    return json.loads(sent[1]["body"])["reason"]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_set_public_host_admits_that_host_only(method):
    gate, inner = gate_for({config.PUBLIC_HOSTS_ENV: "localhost:8080"})
    proxied = [
        ("Host", "localhost:8080"),
        ("Origin", "http://localhost:8080"),
        ("Sec-Fetch-Site", "same-origin"),
    ]
    assert outcome(gate, inner, proxied, method=method) == "admitted"
    assert (
        outcome(gate, inner, [("Host", "localhost:8080")], method=method) == "admitted"
    )
    for host in (
        "api:8000",
        "localhost:9999",
        "127.0.0.1:8080",
        "LOCALHOST:8080",
        "*",
        "",
    ):
        refused = [
            ("Host", host),
            ("Origin", "http://%s" % host),
            ("Sec-Fetch-Site", "same-origin"),
        ]
        assert outcome(gate, inner, refused, method=method) == "host_not_admitted", host
    # The listening port's own names still pass; a foreign page through the proxy still does not.
    assert (
        outcome(gate, inner, [("Host", "127.0.0.1:8000")], method=method) == "admitted"
    )
    foreign = [("Host", "localhost:8080"), ("Origin", "http://evil.example")]
    assert outcome(gate, inner, foreign, method=method) == "origin_not_admitted"
    cross = foreign + [("Sec-Fetch-Site", "cross-site")]
    assert outcome(gate, inner, cross, method=method) == "cross_site_rejected"
    # A public host is not an allowed Origin: a page on it calling the listening port directly is cross-site.
    direct = [
        ("Host", "localhost:8000"),
        ("Origin", "http://localhost:8080"),
        ("Sec-Fetch-Site", "same-site"),
    ]
    assert outcome(gate, inner, direct, method=method) == "cross_site_rejected"
    duplicated = [("Host", "localhost:8080"), ("Host", "localhost:8080")]
    assert outcome(gate, inner, duplicated, method=method) == "host_not_admitted"
    # A public host does not lift the rule that the server must listen on a TCP port.
    assert (
        outcome(gate, inner, [("Host", "localhost:8080")], server=None, method=method)
        == "host_not_admitted"
    )
    assert gate.refusals["host_not_admitted"] == 8


def test_a_set_public_host_still_needs_json():
    gate, inner = gate_for({config.PUBLIC_HOSTS_ENV: "localhost:8080"})
    sent, receives = drive(
        gate,
        "POST",
        [("Host", "localhost:8080"), ("Content-Type", "text/plain")],
        server=CONTAINER,
    )
    assert (sent[0]["status"], receives, inner.calls) == (415, 0, 0)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_set_origin_is_admitted_and_others_are_not(method):
    gate, inner = gate_for({config.ALLOWED_ORIGINS_ENV: "http://localhost:5174"})
    for site in (
        [],
        [("Sec-Fetch-Site", "same-site")],
        [("Sec-Fetch-Site", "cross-site")],
    ):
        front = [("Host", "localhost:8000"), ("Origin", "http://localhost:5174")] + site
        assert outcome(gate, inner, front, method=method) == "admitted", site
    for default in config.DEFAULT_CORS_ORIGINS:
        front = [
            ("Host", "127.0.0.1:8000"),
            ("Origin", default),
            ("Sec-Fetch-Site", "same-site"),
        ]
        assert outcome(gate, inner, front, method=method) == "admitted", default
    for origin in (
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "https://localhost:5174",
        "http://localhost:5174/",
        "http://user@localhost:5174",
        "http://evil.example",
        "*",
        "",
        "null",
    ):
        front = [("Host", "localhost:8000"), ("Origin", origin)]
        assert outcome(gate, inner, front, method=method) == "origin_not_admitted", (
            origin
        )
        crossed = front + [("Sec-Fetch-Site", "cross-site")]
        assert outcome(gate, inner, crossed, method=method) == "cross_site_rejected", (
            origin
        )
    # An allowed origin is not an allowed Host.
    assert (
        outcome(gate, inner, [("Host", "localhost:5174")], method=method)
        == "host_not_admitted"
    )


def test_several_values_are_comma_separated_and_kept_in_order():
    environ = {
        config.PUBLIC_HOSTS_ENV: " localhost:8080 ,127.0.0.1:8080,localhost:8080",
        config.ALLOWED_ORIGINS_ENV: "http://localhost:5174, http://127.0.0.1:5174,http://localhost:5173",
    }
    assert config.public_hosts(environ) == ("localhost:8080", "127.0.0.1:8080")
    assert config.allowed_origins(environ) == config.DEFAULT_CORS_ORIGINS + [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    assert config.allowed_origins(environ) is not config.DEFAULT_CORS_ORIGINS
    assert config.DEFAULT_CORS_ORIGINS == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


BAD_HOSTS = [
    "*",
    "*:8080",
    "localhost:*",
    "*.localhost:8080",
    "localhost",
    "localhost:",
    ":8080",
    "localhost:0",
    "localhost:65536",
    "localhost:08080",
    "localhost:8080a",
    "LOCALHOST:8080",
    "api:8000",
    "evil.example:8080",
    "localhost.evil.example:8080",
    "0.0.0.0:8080",
    "127.0.0.2:8080",
    "[::1]:8080",
    "localhost:8080/api",
    "localhost:8080/",
    "localhost:8080?x",
    "user@localhost:8080",
    "user:pw@localhost:8080",
    "http://localhost:8080",
    "localhost:8080,",
    ",localhost:8080",
    "localhost:8080,,127.0.0.1:8081",
    "localhost:8080 127.0.0.1:8081",
    "localhost:8080;127.0.0.1:8081",
]
BAD_ORIGINS = [
    "*",
    "http://*",
    "http://*:5174",
    "http://localhost:*",
    "null",
    "http://localhost",
    "http://localhost:",
    "localhost:5174",
    "//localhost:5174",
    "https://localhost:5174",
    "HTTP://localhost:5174",
    "http://LOCALHOST:5174",
    "http://localhost:05174",
    "http://localhost:65536",
    "http://localhost:5174/",
    "http://localhost:5174/api",
    "http://localhost:5174?x",
    "http://localhost:5174#x",
    "http://user@localhost:5174",
    "http://user:pw@localhost:5174",
    "http://evil.example:5174",
    "http://localhost.evil.example:5174",
    "http://localhost:5174.evil.example",
    "http://[::1]:5174",
    "http://localhost:5174,",
    "http://localhost:5174,,http://127.0.0.1:5174",
    "http://localhost:5174 http://127.0.0.1:5174",
]


@pytest.mark.parametrize(
    ("name", "value"),
    [(config.PUBLIC_HOSTS_ENV, v) for v in BAD_HOSTS]
    + [(config.ALLOWED_ORIGINS_ENV, v) for v in BAD_ORIGINS],
)
def test_a_malformed_setting_is_refused_naming_the_variable(name, value):
    read = (
        config.public_hosts
        if name == config.PUBLIC_HOSTS_ENV
        else config.allowed_origins
    )
    with pytest.raises(ValueError) as error:
        read({name: value})
    assert str(error.value).startswith(name + ": ")


def _app_main(tmp_path, args, **settings):
    data = tmp_path / "data"
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in (config.PUBLIC_HOSTS_ENV, config.ALLOWED_ORIGINS_ENV)
    }
    env.update(
        STOCK_DATA_DIR=str(data),
        STOCK_DB_PATH=str(data / "stock.db"),
        STOCK_RAW_DIR=str(data / "raw"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join([str(BACKEND), *sys.path]),
        **settings,
    )
    return subprocess.run(
        [sys.executable, *args],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    "settings",
    [
        {config.PUBLIC_HOSTS_ENV: "api:8000"},
        {config.PUBLIC_HOSTS_ENV: "localhost:8080,*"},
        {config.ALLOWED_ORIGINS_ENV: "http://localhost:5174/"},
    ],
    ids=["foreign name", "wildcard", "origin with path"],
)
def test_the_api_does_not_start_with_a_malformed_setting(tmp_path, settings):
    result = _app_main(
        tmp_path, ["-m", "uvicorn", "app.main:app", "--port", "0"], **settings
    )
    ((name, value),) = settings.items()
    assert result.returncode != 0, result.stdout + result.stderr
    assert "ValueError: %s: " % name in result.stderr, result.stderr
    bad = [v for v in value.split(",") if v not in ("localhost:8080",)][0]
    assert repr(bad) in result.stderr, result.stderr
    assert "Uvicorn running" not in result.stderr


def test_a_malformed_setting_stops_only_the_api_not_the_worker(tmp_path):
    settings = {
        config.PUBLIC_HOSTS_ENV: "localhost:8080,evil.example:8080",
        config.ALLOWED_ORIGINS_ENV: "http://*",
    }
    worker = _app_main(tmp_path, ["-c", "import worker.cli"], **settings)
    assert worker.returncode == 0, worker.stdout + worker.stderr
    api = _app_main(tmp_path, ["-c", "import app.main"], **settings)
    assert api.returncode != 0 and "ValueError: STOCK_API_" in api.stderr, api.stderr


def test_the_product_app_gives_the_set_values_to_both_gate_and_cors(tmp_path):
    code = textwrap.dedent(
        """
        import json
        from fastapi.middleware.cors import CORSMiddleware
        from app.browser_gate import BrowserGate
        from app.main import app
        mounted = {m.cls: m.kwargs for m in app.user_middleware}
        print(json.dumps({
            "gate_origins": list(mounted[BrowserGate]["allowed_origins"]),
            "gate_hosts": list(mounted[BrowserGate]["public_hosts"]),
            "cors_origins": list(mounted[CORSMiddleware]["allow_origins"]),
            "same_list": mounted[BrowserGate]["allowed_origins"] is mounted[CORSMiddleware]["allow_origins"],
        }))
        """
    )
    result = _app_main(
        tmp_path,
        ["-c", code],
        STOCK_API_PUBLIC_HOSTS="localhost:8080",
        STOCK_API_ALLOWED_ORIGINS="http://localhost:5174",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    origins = config.DEFAULT_CORS_ORIGINS + ["http://localhost:5174"]
    assert json.loads(result.stdout) == {
        "gate_origins": origins,
        "gate_hosts": ["localhost:8080"],
        "cors_origins": origins,
        "same_list": True,
    }
