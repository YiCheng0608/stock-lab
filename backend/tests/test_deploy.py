"""tools/ops/deploy.sh with a fake gh, a fake docker and a recording git (#314, #340).

Each test builds an "origin" repository and a clone of it, the release checkout, under
tmp_path, with tags on origin, and copies deploy.sh and its helpers into a sandbox. A bin
directory in front of PATH holds a fake ``gh`` that answers ``run list`` from a JSON file
the test writes, a fake ``docker`` that keeps the images, the running containers and the
volume's deploy.json as files and records every call, and a ``git`` that records every call
before running the real git, so the tests can assert that nothing is pulled and that a
refused deploy changes no image, container or volume. HOME is under tmp_path; nothing
touches GitHub, Docker, the real checkout or the real data. The lock the deploy takes in the
scheduler container is worker.job's own (the Linux test at the end).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import worker.job as job

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("deploy.sh", "coordinator_lib.sh", "coordinator_json.py")
PROJECT = "stock-lab"
# docker-compose.yml before and after #340: only the second tags the images.
COMPOSE_BEFORE = "x-backend: &backend\n  image: ${COMPOSE_PROJECT_NAME}-backend\n"
COMPOSE = (
    "x-backend: &backend\n"
    "  image: ${COMPOSE_PROJECT_NAME}-backend:${STOCK_RELEASE_TAG:-latest}\n"
)


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
REAL_GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(
    BASH is None or REAL_GIT is None, reason="bash and git are required"
)

FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/gh_calls.log"
case "$1 $2" in
  "run list") cat "$d/gh_run_list.json" 2>/dev/null || echo '[]' ;;
  "issue comment")
    while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$d/comment.md"; shift; done
    [ -f "$d/gh_comment_fails" ] && exit 1 ;;
esac
exit 0
"""

FAKE_GIT = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_DIR/git_calls.log"
exec "$REAL_GIT" "$@"
"""

# The fake docker's state, under $FAKE_DIR/docker: images (one ref per line), running (the tag
# the project's containers run), containers (`docker ps` lines: id and service; none without
# the file), volume/deploy.json, locks_held (a job holds a lock: the lock exec exits 75),
# old_image (the holder's worker.job knows no --keep-stdin: exit 2), lock_hangs (the holder
# never answers). Every call goes to docker_calls.log, the lock holder's end too ("lock
# released"), so the order of the steps can be read back. on_lock, when it exists, runs as the
# lock is taken. build/run/up/readback_fails make that step fail; readback holds what the new
# scheduler's check prints.
FAKE_DOCKER = r"""#!/usr/bin/env bash
d="$FAKE_DIR/docker"
log="$FAKE_DIR/docker_calls.log"
printf '%s\n' "$*" >>"$log"
running() { cat "$d/running" 2>/dev/null; }
if [ "$1" = compose ]; then
  shift
  while [ $# -gt 0 ]; do case "$1" in -p | -f) shift 2 ;; *) break ;; esac; done
  sub="$1"
  shift
  case "$sub" in
    version) exit 0 ;;
    build)
      printf 'build project=%s tag=%s head=%s web=%s api=%s env_file=%s monitor=%s coordination=%s\n' \
        "$COMPOSE_PROJECT_NAME" "$STOCK_RELEASE_TAG" "$STOCK_GIT_HEAD" "${WEB_PORT-}" \
        "${API_PORT-}" "${STOCK_ENV_FILE-}" "${STOCK_MONITOR-}" "${STOCK_COORDINATION_DIR-}" >>"$log"
      [ -f "$d/build_fails" ] && exit 1
      printf '%s\n' "$COMPOSE_PROJECT_NAME-backend:$STOCK_RELEASE_TAG" \
        "$COMPOSE_PROJECT_NAME-web:$STOCK_RELEASE_TAG" >>"$d/images"
      exit 0 ;;
    run)
      [ -f "$d/run_fails" ] && exit 1
      mkdir -p "$d/volume"
      cat >"$d/volume/deploy.json"
      exit 0 ;;
    up)
      [ -f "$d/up_fails" ] && exit 1
      printf '%s\n' "$STOCK_RELEASE_TAG" >"$d/running"
      printf 'c0ffee5c4ed01e7 scheduler\nfeedface0001 api\n' >"$d/containers"
      exit 0 ;;
    ps)
      t="$(running)"
      printf 'api %s\nscheduler %s\nweb %s\n' "$COMPOSE_PROJECT_NAME-backend:$t" \
        "$COMPOSE_PROJECT_NAME-backend:$t" "$COMPOSE_PROJECT_NAME-web:$t"
      exit 0 ;;
    exec)
      [ -f "$d/readback_fails" ] && exit 1
      cat "$d/readback" 2>/dev/null || echo "deploy_image ok image=fake"
      exit 0 ;;
  esac
  exit 0
fi
case "$1" in
  ps) cat "$d/containers" 2>/dev/null; exit 0 ;;
  inspect) echo "stock-lab-backend:$(running)"; exit 0 ;;
  image)
    shift 2
    for ref in "$@"; do grep -qxF "$ref" "$d/images" 2>/dev/null || exit 1; done
    exit 0 ;;
  exec)
    [ -f "$d/on_lock" ] && bash "$d/on_lock"
    if [ -f "$d/locks_held" ]; then echo "locked: /data/locks/daily.lock" >&2; exit 75; fi
    if [ -f "$d/old_image" ]; then echo "error: unrecognized arguments: --keep-stdin" >&2; exit 2; fi
    [ -f "$d/lock_hangs" ] && exec sleep 60
    echo held
    cat >/dev/null
    echo "lock released" >>"$log"
    exit 0 ;;
esac
exit 0
"""


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            REAL_GIT,
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "init.defaultBranch=master",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.fake = root / "fake"
        self.docker = self.fake / "docker"
        self.home = root / "home"
        self.sandbox = root / "sandbox"
        self.origin = root / "origin"
        self.checkout = root / "release"
        for directory in (self.bin, self.docker, self.home, self.origin):
            directory.mkdir(parents=True)
        ops = self.sandbox / "tools" / "ops"
        ops.mkdir(parents=True)
        for name in SCRIPTS:
            shutil.copyfile(ROOT / "tools" / "ops" / name, ops / name)
        self.script = ops / "deploy.sh"
        for name, body in (("gh", FAKE_GH), ("git", FAKE_GIT), ("docker", FAKE_DOCKER)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)

        # origin: v0 predates #340 (its compose file tags no image), v1 is a lightweight tag
        # on the next commit, v2 an annotated tag on the one after.
        self.commit({"README.md": "v0\n", "docker-compose.yml": COMPOSE_BEFORE})
        git(self.origin, "tag", "v0")
        self.commit({"README.md": "v1\n", "docker-compose.yml": COMPOSE})
        git(self.origin, "tag", "v1")
        self.commit({"README.md": "v2\n"})
        git(self.origin, "tag", "-a", "v2", "-m", "v2")
        self.sha = {
            t: git(self.origin, "rev-parse", f"{t}^{{commit}}")
            for t in ("v0", "v1", "v2")
        }
        git(
            self.root,
            "clone",
            "--quiet",
            "--no-tags",
            str(self.origin),
            str(self.checkout),
        )
        git(self.checkout, "checkout", "--quiet", "--detach", self.sha["v0"])
        self.ci("success")
        # The project runs v0 with its scheduler, as after an earlier deploy.
        self.images(f"{PROJECT}-backend:v0", f"{PROJECT}-web:v0")
        (self.docker / "running").write_text("v0\n", encoding="utf-8")
        self.containers("c0ffee5c4ed01e7 scheduler", "feedface0001 api")

    def commit(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            path = self.origin / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        if not (self.origin / ".git").exists():
            git(self.origin, "init", "--quiet")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "--quiet", "-m", "commit")

    def ci(self, *conclusions: str, status: str = "completed") -> None:
        """CI runs of every tagged commit, newest (highest run id) first."""
        runs = [
            {
                "databaseId": 1000 - n,
                "headSha": sha,
                "status": status,
                "conclusion": conclusion,
            }
            for n, conclusion in enumerate(conclusions)
            for sha in self.sha.values()
        ]
        (self.fake / "gh_run_list.json").write_text(json.dumps(runs), encoding="utf-8")

    def containers(self, *lines: str) -> None:
        """The project's running api and scheduler containers: `<id> <service>`."""
        (self.docker / "containers").write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8"
        )

    def images(self, *refs: str) -> None:
        (self.docker / "images").write_text(
            "".join(f"{ref}\n" for ref in refs), encoding="utf-8"
        )

    def calls(self, name: str) -> list[str]:
        path = self.fake / f"{name}_calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def head(self) -> str:
        return git(self.checkout, "rev-parse", "HEAD")

    def docker_state(self) -> dict[str, str | None]:
        """The images, what runs and the volume's record, as the fake docker keeps them."""
        state = {}
        for name in ("images", "running", "containers", "volume/deploy.json"):
            path = self.docker / name
            state[name] = path.read_text(encoding="utf-8") if path.exists() else None
        return state

    def state(self) -> tuple:
        """What a refused deploy must leave as it was."""
        return (
            self.head(),
            git(self.checkout, "status", "--porcelain"),
            git(self.checkout, "tag", "--list"),
            self.docker_state(),
        )

    def mutations(self) -> list[str]:
        """docker calls that change an image, a container or a volume."""
        changing = ("build", "run", "up", "down", "create", "rm", "tag", "volume")
        return [
            call
            for call in self.calls("docker")
            if set(call.split()) & set(changing) and not call.startswith("ps ")
        ]

    @property
    def record(self) -> dict | None:
        path = self.docker / "volume" / "deploy.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def deploy(
        self, tag: str, *args: str, extra_env: dict[str, str] | None = None
    ) -> SimpleNamespace:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("STOCK_", "DEPLOY_", "GIT_", "COMPOSE_"))
        }
        env.update(
            PATH=str(self.bin) + os.pathsep + env.get("PATH", ""),
            FAKE_DIR=self.fake.as_posix(),
            FAKE_BIN=_bash_path(self.bin),
            REAL_GIT=Path(REAL_GIT).as_posix(),
            HOME=self.home.as_posix(),
            STOCK_PYTHON=Path(sys.executable).as_posix(),
            # A task session's project (tools/ops/dispatch.sh): never the one deployed.
            COMPOSE_PROJECT_NAME="task-340",
        )
        env.update(extra_env or {})
        # Git for Windows' bin/bash.exe puts /mingw64/bin (the real git) in front of
        # PATH, so the fake bin directory is put first again inside bash.
        completed = subprocess.run(
            [
                BASH,
                "-c",
                'PATH="$FAKE_BIN:$PATH"; exec bash "$@"',
                "bash",
                self.script.as_posix(),
                tag,
                "--checkout",
                self.checkout.as_posix(),
                "--operator",
                "測試者",
                *args,
            ],
            env=env,
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
        return SimpleNamespace(
            code=completed.returncode,
            out=completed.stdout + completed.stderr,
            result=json.loads(lines[-1]) if lines else None,
        )


@pytest.fixture
def harness(tmp_path) -> Harness:
    return Harness(tmp_path)


def assert_no_pull(h: Harness) -> None:
    assert not [call for call in h.calls("git") if " pull" in f" {call}"]


# Deploying (AC-1) --------------------------------------------------------------------


def test_a_green_tag_is_built_tagged_started_and_recorded(harness):
    result = harness.deploy("v1")
    assert result.code == 0, result.out
    sha = harness.sha["v1"]
    assert harness.head() == sha
    # Images of the tag, built from the checked-out tag with its commit.
    calls = harness.calls("docker")
    assert (
        f"build project={PROJECT} tag=v1 head={sha} web= api= env_file= monitor= coordination="
        in calls
    )
    assert (
        f"{PROJECT}-backend:v1\n{PROJECT}-web:v1\n" in harness.docker_state()["images"]
    )
    assert harness.docker_state()["running"] == "v1\n"
    record = harness.record
    assert record == {
        "tag": "v1",
        "HEAD": sha,
        "image": f"{PROJECT}-backend:v1",
        "web_image": f"{PROJECT}-web:v1",
        "previous_image": f"{PROJECT}-backend:v0",
        "deployed_at": record["deployed_at"],
        "operator": "測試者",
        "project": PROJECT,
        "checkout": record["checkout"],
    }
    assert record["deployed_at"].endswith("Z")
    assert record["checkout"].endswith("/release")
    assert result.result == {
        "deployed": True,
        "tag": "v1",
        "HEAD": sha,
        "image": f"{PROJECT}-backend:v1",
        "web_image": f"{PROJECT}-web:v1",
        "previous_image": f"{PROJECT}-backend:v0",
        "locks": "held",
        "commented": True,
    }
    assert any(f"--commit {sha}" in c for c in harness.calls("gh"))
    assert_no_pull(harness)


def test_the_steps_run_in_order_while_the_locks_are_held(harness):
    assert harness.deploy("v1", "--no-comment").code == 0
    calls = harness.calls("docker")

    def at(text: str) -> int:
        return next(n for n, call in enumerate(calls) if text in call)

    lock = at("exec -i c0ffee5c4ed01e7 python -X utf8 -m worker.job lock")
    steps = [
        lock,
        at("build project="),
        at("image inspect stock-lab-backend:v1 stock-lab-web:v1"),
        at(" run --rm --no-deps -T --entrypoint sh scheduler -c "),
        at(" up -d --no-build --wait --wait-timeout 300"),
        at(" ps --format "),
        at(" exec -T scheduler "),
        at("lock released"),
    ]
    # The record is in the volume before the new containers start; the locks go last.
    assert steps == sorted(steps), calls
    # Each lock wraps the next, the innermost holds until stdin closes.
    for name in ("daily", "news", "watchdog"):
        assert f"lock --keep-stdin /data/locks/{name}.lock --" in calls[lock]
    assert calls[lock].endswith("sh -c echo held; exec cat >/dev/null")
    assert "watchdog_helper.py deploy-image /data/logs/deploy.json" in calls[steps[6]]


def test_compose_gets_the_project_and_file_and_never_the_session_project(harness):
    harness.deploy("v1", "--no-comment", "--project", "t340-other")
    compose = [c for c in harness.calls("docker") if c.startswith("compose ")]
    checkout = harness.record["checkout"]
    assert compose[0] == "compose version"
    for call in compose[1:]:
        assert call.startswith(
            f"compose -p t340-other -f {checkout}/docker-compose.yml "
        )
    assert harness.record["image"] == "t340-other-backend:v1"


def test_with_no_api_or_scheduler_running_no_lock_is_taken(harness):
    (harness.docker / "running").unlink()
    (harness.docker / "containers").unlink()
    result = harness.deploy("v1", "--no-comment")
    assert result.code == 0, result.out
    assert result.result["locks"] == "none"
    assert result.result["previous_image"] is None
    assert harness.record["previous_image"] is None
    assert not [c for c in harness.calls("docker") if c.startswith("exec ")]


def test_without_a_scheduler_the_locks_are_taken_in_the_api(harness):
    # The api, or a one-off `compose run` (its label is the service's): a job run by hand.
    harness.containers("feedface0001 api")
    result = harness.deploy("v1", "--no-comment")
    assert result.code == 0, result.out
    assert result.result["locks"] == "held"
    assert result.result["previous_image"] is None
    (lock,) = [c for c in harness.calls("docker") if c.startswith("exec -i ")]
    assert lock.startswith("exec -i feedface0001 python -X utf8 -m worker.job lock ")


def test_a_job_run_by_hand_without_a_scheduler_refuses_the_deploy(harness):
    harness.containers("0ff1ce000001 api")
    (harness.docker / "locks_held").touch()
    before = harness.state()
    result = harness.deploy("v1")
    assert_refused_unchanged(harness, before, result, "排程執行中")


def test_inherited_ports_and_env_file_never_reach_compose(harness):
    # A shell left with a smoke test's (tools/compose/deploy_smoke.sh) cannot move production.
    left = {"WEB_PORT": "18180", "API_PORT": "18100", "STOCK_ENV_FILE": "/smoke/env"}
    assert harness.deploy("v1", "--no-comment", extra_env=left).code == 0
    assert any(
        c.startswith("build project=stock-lab tag=v1 ")
        and c.endswith(" web= api= env_file= monitor= coordination=")
        for c in harness.calls("docker")
    )
    options = (
        "--web-port",
        "18180",
        "--api-port",
        "18100",
        "--env-file",
        "/rehearsal/env",
    )
    assert harness.deploy("v2", "--no-comment", *options).code == 0
    assert any(
        c.startswith("build project=stock-lab tag=v2 ")
        and c.endswith(
            " web=18180 api=18100 env_file=/rehearsal/env monitor= coordination="
        )
        for c in harness.calls("docker")
    )


def test_inherited_monitor_settings_never_reach_compose(harness):
    """#338: production's event monitor takes STOCK_MONITOR and STOCK_COORDINATION_DIR from
    the release checkout's env file only; a shell left with a sandbox's cannot point the
    production queue elsewhere, or switch the monitor on or off."""
    left = {"STOCK_MONITOR": "on", "STOCK_COORDINATION_DIR": "C:/sandbox/e2e/logs"}
    assert harness.deploy("v1", "--no-comment", extra_env=left).code == 0
    builds = [c for c in harness.calls("docker") if c.startswith("build ")]
    assert builds and all(c.endswith(" monitor= coordination=") for c in builds), builds


def test_redeploying_the_running_tag_still_releases_the_locks(harness):
    assert harness.deploy("v1", "--no-comment").code == 0
    result = harness.deploy("v1", "--no-comment")
    assert result.code == 0, result.out
    assert result.result["previous_image"] == f"{PROJECT}-backend:v1"
    assert harness.calls("docker").count("lock released") == 2


# The #1 comment (AC-3) ---------------------------------------------------------------


def test_the_comment_on_1_names_the_tag_head_images_and_record(harness):
    result = harness.deploy("v2")
    assert result.code == 0, result.out
    record = harness.record
    sha = harness.sha["v2"]
    (call,) = [c for c in harness.calls("gh") if c.startswith("issue comment")]
    assert call.startswith("issue comment 1 --repo YiCheng0608/stock-lab --body-file ")
    comment = (harness.fake / "comment.md").read_text(encoding="utf-8")
    assert comment == (
        "部署：tag `v2` 的 image 已以 `docker compose up -d` 啟動\n"
        "\n"
        f"- HEAD：`{sha}`\n"
        "- image：`stock-lab-backend:v2`（api、scheduler）、`stock-lab-web:v2`（web）；"
        "前一版 `stock-lab-backend:v0`\n"
        f"- compose project：`stock-lab`；發佈 checkout：`{record['checkout']}`\n"
        f"- 操作者：測試者；時間：{record['deployed_at']}（UTC）\n"
        "\n"
        "（`tools/ops/deploy.sh` 自動留言；部署記錄在 volume 的 `/data/logs/deploy.json`，"
        "看門狗以它核對 scheduler 跑的 image。）\n"
    )


def test_the_first_deploy_comments_that_there_was_no_previous_image(harness):
    (harness.docker / "running").unlink()
    (harness.docker / "containers").unlink()
    assert harness.deploy("v1").code == 0
    comment = (harness.fake / "comment.md").read_text(encoding="utf-8")
    assert "；前一版 無（scheduler 沒有在執行）\n" in comment


def test_no_comment_leaves_1_alone(harness):
    result = harness.deploy("v1", "--no-comment")
    assert result.code == 0 and result.result["commented"] is False
    assert not [c for c in harness.calls("gh") if c.startswith("issue")]


def test_a_failed_comment_exits_4_after_deploying(harness):
    (harness.fake / "gh_comment_fails").touch()
    result = harness.deploy("v1")
    assert result.code == 4, result.out
    assert harness.docker_state()["running"] == "v1\n" and harness.record
    assert result.result == {
        "deployed": True,
        "tag": "v1",
        "HEAD": harness.sha["v1"],
        "image": f"{PROJECT}-backend:v1",
        "commented": False,
    }


# Refusing (AC-2): the checkout, images, containers and volume stay as they were ---------


def assert_refused_unchanged(h: Harness, before: tuple, result, text: str) -> None:
    assert result.code == 1, result.out
    assert text in result.out
    assert result.result["deployed"] is False
    assert h.state() == before
    assert h.mutations() == []
    assert not [c for c in h.calls("gh") if c.startswith("issue")]
    assert_no_pull(h)


@pytest.mark.parametrize(
    "conclusions,status,shown",
    [
        (("failure",), "completed", "failure"),
        (("failure", "success"), "completed", "failure"),
        (("success",), "in_progress", "pending"),
        ((), "completed", "missing"),
    ],
    ids=["red", "red-after-green", "running", "no-run"],
)
def test_a_tag_whose_ci_is_not_green_is_refused_and_changes_nothing(
    harness, conclusions, status, shown
):
    harness.ci(*conclusions, status=status)
    before = harness.state()
    result = harness.deploy("v1")
    assert_refused_unchanged(harness, before, result, f"CI 是 {shown}")
    assert not [c for c in harness.calls("git") if c.split()[2:3] == ["fetch"]]
    # Refused before the locks: no docker call at all but the version check.
    assert harness.calls("docker") == ["compose version"]


@pytest.mark.parametrize("cancelled_id,code", [(1, 0), (3, 1)], ids=["older", "newer"])
def test_the_latest_run_is_the_highest_run_id_not_the_first_listed(
    harness, cancelled_id, code
):
    # Two runs created at the same second: gh lists them in any order, and the
    # concurrency group cancels the older one (PR #330's own CI).
    sha = harness.sha["v1"]
    runs = [
        {
            "databaseId": cancelled_id,
            "headSha": sha,
            "status": "completed",
            "conclusion": "cancelled",
        },
        {
            "databaseId": 2,
            "headSha": sha,
            "status": "completed",
            "conclusion": "success",
        },
    ]
    (harness.fake / "gh_run_list.json").write_text(json.dumps(runs), encoding="utf-8")
    result = harness.deploy("v1", "--no-comment")
    assert result.code == code, result.out
    assert (harness.head() == sha) is (code == 0)
    if code:
        assert "CI 是 cancelled" in result.out


def test_a_tag_before_340_is_refused_and_changes_nothing(harness):
    git(harness.checkout, "checkout", "--quiet", "--detach", harness.sha["v1"])
    before = harness.state()
    result = harness.deploy("v0")
    assert_refused_unchanged(harness, before, result, "早於 #340")
    # Refused after the fetch: the tag ref the fetch created is deleted again.
    assert any(c.split()[2:3] == ["fetch"] for c in harness.calls("git"))
    assert harness.calls("docker")[-1] == "lock released"


def test_a_refusal_after_the_fetch_keeps_a_tag_that_was_there(harness):
    git(harness.checkout, "fetch", "--quiet", "origin", "refs/tags/v0:refs/tags/v0")
    before = harness.state()
    assert "v0" in before[2]
    result = harness.deploy("v0")
    assert_refused_unchanged(harness, before, result, "早於 #340")


def test_a_running_job_refuses_the_deploy_and_changes_nothing(harness):
    (harness.docker / "locks_held").touch()
    before = harness.state()
    result = harness.deploy("v1")
    assert_refused_unchanged(harness, before, result, "排程執行中")
    assert not [c for c in harness.calls("git") if c.split()[2:3] == ["fetch"]]


def test_a_tag_that_moved_after_the_ci_check_is_refused(harness):
    # origin's tag moves to another commit between the CI check and the fetch.
    (harness.docker / "on_lock").write_text(
        f'"$REAL_GIT" -C "{harness.origin.as_posix()}" tag -f v1 {harness.sha["v2"]}'
        " >/dev/null\n",
        encoding="utf-8",
    )
    before = harness.state()
    result = harness.deploy("v1")
    assert_refused_unchanged(harness, before, result, "不是 CI 核對過的")


@pytest.mark.parametrize("change", ["modified", "untracked", "index.lock"])
def test_uncommitted_changes_refuse_the_deploy(harness, change):
    if change == "modified":
        (harness.checkout / "README.md").write_text("local\n", encoding="utf-8")
    elif change == "untracked":
        (harness.checkout / "notes.txt").write_text("x\n", encoding="utf-8")
    else:
        (harness.checkout / ".git" / "index.lock").touch()
    before = harness.state()
    result = harness.deploy("v1")
    text = "進行中的 git 操作" if change == "index.lock" else "未 commit 的改動"
    assert_refused_unchanged(harness, before, result, text)
    assert harness.calls("gh") == []


def test_a_tag_missing_on_origin_is_refused(harness):
    before = harness.state()
    result = harness.deploy("v9")
    assert_refused_unchanged(harness, before, result, "origin 沒有 tag v9")


def test_a_deploy_from_inside_the_checkout_is_refused(harness):
    ops = harness.checkout / "tools" / "ops"
    ops.mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copyfile(harness.script.parent / name, ops / name)
    harness.script = ops / "deploy.sh"
    before = harness.head()
    result = harness.deploy("v1")
    assert result.code == 1 and "這支腳本在發佈 checkout 裡" in result.out, result.out
    assert harness.head() == before and harness.mutations() == []


# A step failing after the checkout started (exit 3) ------------------------------------


def test_a_failed_build_keeps_the_running_containers_and_the_record(harness):
    assert harness.deploy("v1", "--no-comment").code == 0
    record = harness.record
    (harness.docker / "build_fails").touch()
    result = harness.deploy("v2")
    assert result.code == 3, result.out
    assert "docker compose build 失敗" in result.out
    assert harness.docker_state()["running"] == "v1\n" and harness.record == record
    assert not [c for c in harness.calls("gh") if c.startswith("issue")]
    assert harness.calls("docker")[-1] == "lock released"


def test_a_failed_up_leaves_the_new_record_for_the_watchdog(harness):
    (harness.docker / "up_fails").touch()
    result = harness.deploy("v1")
    assert result.code == 3, result.out
    assert "看門狗會回報" in result.out
    assert harness.record["image"] == f"{PROJECT}-backend:v1"
    assert harness.docker_state()["running"] == "v0\n"
    assert not [c for c in harness.calls("gh") if c.startswith("issue")]


def test_a_new_scheduler_whose_check_is_not_ok_fails_the_deploy(harness):
    (harness.docker / "readback").write_text(
        "deploy_image violation image=unknown recorded=stock-lab-backend:v1",
        encoding="utf-8",
    )
    result = harness.deploy("v1")
    assert result.code == 3, result.out
    assert "版本核對不是 ok" in result.out


def test_a_scheduler_of_an_image_before_340_exits_2_and_says_to_stop_it(harness):
    (harness.docker / "old_image").touch()
    before = harness.state()
    result = harness.deploy("v1")
    assert result.code == 2, result.out
    assert (
        "image 早於 #340" in result.out
        and "docker compose -p stock-lab stop" in result.out
    )
    assert harness.state() == before and harness.mutations() == []


def test_a_lock_holder_that_never_answers_exits_2_in_time(harness):
    (harness.docker / "lock_hangs").touch()
    before = harness.state()
    started = time.monotonic()
    result = harness.deploy("v1", extra_env={"DEPLOY_LOCK_WAIT": "2"})
    assert result.code == 2, result.out
    assert "2 秒內沒有回應排程鎖" in result.out
    # The holder is killed, not waited for (it would sleep 60 s).
    assert time.monotonic() - started < 45
    assert harness.state() == before and harness.mutations() == []


def test_bad_arguments_exit_64(harness):
    for args in (
        ["v1", "--project", "Bad Name"],
        ["v1", "--wait-timeout", "0"],
        ["v1", "--web-port", "port"],
    ):
        assert harness.deploy(*args).code == 64
    assert harness.deploy("bad:tag").code == 64
    assert harness.calls("docker") == []


# The lock the deploy holds in the scheduler container -------------------------------


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="worker.job runs on Linux only (#333)"
)
def test_a_lock_with_keep_stdin_is_held_until_its_stdin_closes(tmp_path):
    path = tmp_path / "locks" / "daily.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "worker.job",
            "lock",
            "--keep-stdin",
            str(path),
            "--",
            "sh",
            "-c",
            "echo held; exec cat >/dev/null",
        ],
        cwd=ROOT / "backend",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline() == "held\n"
        lock = job.FileLock(path)
        assert not lock.acquire()
        holder.stdin.close()
        assert holder.wait(timeout=30) == 0
        assert lock.acquire()
        lock.release()
    finally:
        if holder.poll() is None:
            holder.kill()
    # Without --keep-stdin the command reads nothing: the same cat ends at once.
    started = time.monotonic()
    code = job.main(["lock", str(path), "--", "sh", "-c", "exec cat >/dev/null"])
    assert code == 0 and time.monotonic() - started < 30
