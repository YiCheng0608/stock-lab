"""The port checks of backend/docker/entrypoint.sh, compose's entrypoint (#335).

Run with sh, as the dev override does; the fixture seeding is left to tools/compose/smoke.sh.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker" / "entrypoint.sh"
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="needs sh")


def run(**ports: str) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("WEB_PORT", "API_PORT", "STOCK_SEED_FIXTURE")
    }
    env.update(ports)
    return subprocess.run(
        [SH, str(ENTRYPOINT), "echo", "started"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "ports",
    [
        {},
        {"WEB_PORT": "8080", "API_PORT": "8000"},
        {"WEB_PORT": "5174", "API_PORT": "8001"},
        {"API_PORT": "1"},
        {"API_PORT": "65535"},
        # Empty is unset: the scheduler reads both only from the env file (review S7).
        {"WEB_PORT": "", "API_PORT": ""},
        {"WEB_PORT": ""},
        {"API_PORT": ""},
    ],
)
def test_a_usable_port_or_none_runs_the_command(ports):
    result = run(**ports)
    assert (result.returncode, result.stdout.strip()) == (0, "started"), result.stderr


@pytest.mark.parametrize(
    "ports, message",
    [
        ({"WEB_PORT": "80"}, "WEB_PORT=80: a browser sends Host without a port"),
        ({"API_PORT": "80"}, "API_PORT=80: a browser sends Host without a port"),
        ({"WEB_PORT": "8000"}, "WEB_PORT=8000 is the api's own port"),
        (
            {"WEB_PORT": "8001", "API_PORT": "8001"},
            "WEB_PORT and API_PORT are both 8001",
        ),
        ({"API_PORT": "08000"}, "API_PORT=08000 is not a port"),
        ({"WEB_PORT": "0"}, "WEB_PORT=0 is not a port"),
        ({"WEB_PORT": "65536"}, "WEB_PORT=65536 is not a port"),
        ({"API_PORT": "abc"}, "API_PORT=abc is not a port"),
    ],
)
def test_a_port_the_write_gate_cannot_use_stops_with_64(ports, message):
    result = run(**ports)
    assert result.returncode == 64, result
    assert result.stdout == ""
    assert message in result.stderr
