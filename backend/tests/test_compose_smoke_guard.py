"""tools/compose/smoke.sh and deploy_smoke.sh run only on a test project (#340, PR #369 review).

Both seed their project's stock-data volume and end with `docker compose down --volumes`, so
the production project (stock-lab, or STOCK_COMPOSE_PROJECT) and any name that is not a test
one are refused before anything runs. A fake docker in front of PATH records every call: a
refused run makes none.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _bash() -> str | None:
    if os.name == "nt":
        git_bash = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Git"
            / "bin"
            / "bash.exe"
        )
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


def _bash_path(path: Path) -> str:
    """PATH entry form inside bash: /c/x/y for C:\\x\\y on Windows."""
    if os.name == "nt" and path.drive:
        return "/" + path.drive[0].lower() + path.as_posix()[2:]
    return path.as_posix()


BASH = _bash()
ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "compose" / "test_project.sh"
SCRIPTS = {"smoke.sh": "SMOKE_PROJECT", "deploy_smoke.sh": "DEPLOY_SMOKE_PROJECT"}
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required")

FAKE_DOCKER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_DIR/docker_calls.log"
exit 1
"""


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("STOCK_", "SMOKE_"))
    }
    env.pop("DEPLOY_SMOKE_PROJECT", None)
    env.update(FAKE_DIR=tmp_path.as_posix(), FAKE_BIN=_bash_path(tmp_path / "bin"))
    env.update(extra)
    return env


def _problem(tmp_path: Path, name: str, **extra: str) -> str:
    completed = subprocess.run(
        [
            BASH,
            "-c",
            '. "$1"; test_project_problem "$2"',
            "bash",
            GUARD.as_posix(),
            name,
        ],
        env=_env(tmp_path, **extra),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


@pytest.mark.parametrize(
    "name",
    [
        "t340",
        "t340-deploy",
        "t340_x",
        "task-340",
        "task-340-a",
        "stock-lab-smoke",
        "stock-lab-deploy-smoke",
        "smoke",
    ],
)
def test_test_projects_are_allowed(tmp_path, name):
    assert _problem(tmp_path, name) == ""


@pytest.mark.parametrize(
    "name",
    ["stock-lab", "stock-lab-release", "t", "task-abc", "tx340", "smokey", "prod", ""],
)
def test_production_and_other_projects_are_refused(tmp_path, name):
    assert _problem(tmp_path, name) != ""


def test_the_production_project_of_deploy_sh_is_refused_even_with_a_test_name(tmp_path):
    assert "正式" in _problem(tmp_path, "t340", STOCK_COMPOSE_PROJECT="t340")
    assert _problem(tmp_path, "t341", STOCK_COMPOSE_PROJECT="t340") == ""


@pytest.mark.parametrize("script", sorted(SCRIPTS))
@pytest.mark.parametrize(
    "name,extra",
    [
        ("stock-lab", {}),
        ("stock-lab-release", {}),
        ("t340", {"STOCK_COMPOSE_PROJECT": "t340"}),
    ],
    ids=["stock-lab", "not-a-test-name", "deploy-project"],
)
def test_a_smoke_script_refuses_before_any_docker_call(tmp_path, script, name, extra):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8", newline="\n")
    docker.chmod(0o755)
    env = _env(tmp_path, **{SCRIPTS[script]: name}, **extra)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    completed = subprocess.run(
        [
            BASH,
            "-c",
            'PATH="$FAKE_BIN:$PATH"; exec bash "$@"',
            "bash",
            (ROOT / "tools" / "compose" / script).as_posix(),
        ],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "拒絕" in completed.stderr and "down --volumes" in completed.stderr
    assert not (tmp_path / "docker_calls.log").exists()
