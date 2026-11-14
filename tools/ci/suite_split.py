"""Split the backend suite between CI's backend and docker jobs, and check nothing is lost (#378).

The backend job runs the whole of backend/tests on the runner, as two shards side by side
(BACKEND_SHARDS, #746) whose reports together must collect the whole suite with no test in
both. The docker job runs, inside the backend image, only what docker_suite.json lists: tests
whose subject is the execution environment the image provides. Collecting is no proof of
coverage (the backend shards collect everything, so a union of collected ids is always the
whole suite); what counts is that every test of the whole suite *ran* (passed) in at least one
job, and that every listed test passed in the docker job (a skip there means the image no
longer offers what it tests).

Three roles, one file:

* a pytest plugin (`-p suite_split --suite-report FILE`) writing the ids a run collected and what
  each did, with ids relative to backend/ so both jobs name a test the same way; the backend job
  runs it under pytest-xdist (#442), where the controller writes the report;
* `args`: the docker list as pytest arguments, and `shard`: one backend shard's;
* `verify`: the check that fails CI, from the jobs' reports and a collect-only report of the
  whole suite made inside the image.

The CLI uses the standard library only (the suite job has no dependencies installed).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MANIFEST = Path(__file__).with_name("docker_suite.json")

PASSED, SKIPPED, FAILED = "passed", "skipped", "failed"

# The backend job is a matrix of two shards side by side (#746): the whole suite on one runner
# took 13 to 20 minutes against its 20-minute step limit. "ops" runs the tests of the
# tools/ops shell scripts, which start a Python fake for every orca, gh or docker call (about
# half of the suite's time in run 43641113253); "rest" runs every other file, so a new test
# file lands there without being listed. The suite job checks that the two reports together
# collect the whole suite and that no test is in both.
BACKEND_SHARDS = ("ops", "rest")
OPS_SHARD = (
    "tests/test_coordinator_scripts.py",
    "tests/test_event_monitor.py",
    "tests/test_master_index.py",
    "tests/test_memory_check.py",
    "tests/test_take_over.py",
    "tests/test_wake_listener.py",
    "tests/test_watchdog.py",
)


def shard_args(shard: str) -> list[str]:
    """The pytest arguments, relative to backend/, of one backend shard."""
    if shard == "ops":
        return list(OPS_SHARD)
    if shard == "rest":
        return [f"--ignore={path}" for path in OPS_SHARD] + ["tests"]
    raise ValueError(f"unknown backend shard {shard!r}; one of {BACKEND_SHARDS}")


# ---- the pytest plugin ---------------------------------------------------------------------

_ids: dict[str, str] = {}
_report: dict = {"collect_only": False, "collected": [], "outcomes": {}}


def pytest_addoption(parser) -> None:
    group = parser.getgroup("suite_split")
    group.addoption(
        "--suite-report",
        metavar="FILE",
        default=None,
        help="write the collected test ids and their outcomes as JSON",
    )
    group.addoption(
        "--suite-root",
        metavar="DIR",
        default=str(BACKEND),
        help="ids are relative to this directory (default: backend/)",
    )


def node_id(item_path: Path, nodeid: str, root: Path) -> str:
    """`tests/test_x.py::Class::test[param]`: the item's file relative to root, then its own part."""
    relative = Path(item_path).resolve().relative_to(root.resolve()).as_posix()
    _, separator, tail = nodeid.partition("::")
    return relative + separator + tail


def pytest_collection_finish(session) -> None:
    config = session.config
    if not config.getoption("suite_report"):
        return
    root = Path(config.getoption("suite_root"))
    _ids.clear()
    for item in session.items:
        _ids[item.nodeid] = node_id(item.path, item.nodeid, root)
    _report["collect_only"] = bool(config.getoption("collectonly"))
    _report["collected"] = sorted(_ids.values())
    _report["outcomes"] = {}


class XdistController:
    """Under pytest-xdist the controller collects nothing (no pytest_collection_finish there):
    each worker sends it the node ids it collected, and the workers' reports reach the
    controller's pytest_runtest_logreport. A node id is its file relative to the rootdir, then
    its own part, so the file is the rootdir joined with that part."""

    def pytest_xdist_node_collection_finished(self, node, ids) -> None:
        config = node.config
        if not config.getoption("suite_report"):
            return
        root = Path(config.getoption("suite_root"))
        for nodeid in ids:
            path = Path(config.rootpath) / nodeid.partition("::")[0]
            _ids[nodeid] = node_id(path, nodeid, root)
        _report["collect_only"] = bool(config.getoption("collectonly"))
        _report["collected"] = sorted(set(_ids.values()))


def pytest_configure(config) -> None:
    # The xdist hook is known only with xdist loaded; the docker job runs without it.
    if config.pluginmanager.hasplugin("xdist"):
        config.pluginmanager.register(XdistController(), "suite_split_xdist")


def _is_xdist_worker(config) -> bool:
    return hasattr(config, "workerinput")


def pytest_runtest_setup(item) -> None:
    # Each test's xdist worker as a property in the junit report the backend job uploads
    # (#746), to measure how evenly the workers are loaded without a verbose log.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker and item.config.getoption("suite_report"):
        item.user_properties.append(("xdist_worker", worker))


def pytest_runtest_logreport(report) -> None:
    key = _ids.get(report.nodeid)
    if key is None:
        return
    if report.failed:
        outcome = FAILED
    elif report.skipped:
        outcome = SKIPPED
    elif report.when == "call":
        outcome = PASSED
    else:
        return
    if _report["outcomes"].get(key) != FAILED:
        _report["outcomes"][key] = outcome


def pytest_sessionfinish(session) -> None:
    target = session.config.getoption("suite_report")
    # A worker saw only its own share of the outcomes; the controller writes the report.
    if not target or _is_xdist_worker(session.config):
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_report, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---- the docker list -----------------------------------------------------------------------


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def selects(selector: str, test_id: str) -> bool:
    """Whether a pytest selector (a file, `file::test`, `file::Class`) picks the test id.

    `file::test` also picks every parametrization `file::test[...]`, as pytest does."""
    return (
        test_id == selector
        or test_id.startswith(selector + "::")
        or test_id.startswith(selector + "[")
    )


def docker_ids(manifest: dict, collected: list[str]) -> set[str]:
    selectors = [entry["select"] for entry in manifest["docker"]]
    return {t for t in collected if any(selects(s, t) for s in selectors)}


# ---- the check -----------------------------------------------------------------------------


def _executed(report: dict) -> set[str]:
    return {t for t, outcome in report["outcomes"].items() if outcome == PASSED}


def _listed(heading: str, ids) -> list[str]:
    ids = sorted(ids)
    shown = ids[:10] + ([f"... and {len(ids) - 10} more"] if len(ids) > 10 else [])
    return [heading] + [f"  {t}" for t in shown]


def merge_backend(shards: list[dict]) -> tuple[dict, list[str]]:
    """The backend shards' reports as one run of the suite, and the tests two shards collected.

    A test in two shards would run twice; the merged outcome of such a test is the failed one
    if either failed."""
    collected: set[str] = set()
    twice: set[str] = set()
    outcomes: dict[str, str] = {}
    for report in shards:
        ids = set(report["collected"])
        twice |= collected & ids
        collected |= ids
        for test, outcome in report["outcomes"].items():
            if outcomes.get(test) != FAILED:
                outcomes[test] = outcome
    errors = (
        _listed("tests collected by more than one backend shard:", twice)
        if twice
        else []
    )
    return {
        "collect_only": False,
        "collected": sorted(collected),
        "outcomes": outcomes,
    }, errors


def problems(
    manifest: dict, backend: list[dict], docker: dict, image: dict
) -> list[str]:
    """Why the jobs together do not run the whole suite; an empty list means they do.

    `image` is a collect-only report of the whole suite made in the image, `backend` the
    reports of the backend shards (BACKEND_SHARDS), which together run the whole suite on the
    runner, `docker` the docker job's run of the list."""
    errors: list[str] = []
    if not backend:
        return ["no backend report"]
    for name, report, collect_only in (
        *(("backend", shard, False) for shard in backend),
        ("docker", docker, False),
        ("image collect-only", image, True),
    ):
        if bool(report.get("collect_only")) != collect_only:
            kind = "a collect-only report" if collect_only else "a run report"
            errors.append(f"the {name} report is not {kind}")
    if errors:
        return errors
    backend, errors = merge_backend(backend)

    full = set(image["collected"])
    if not full:
        return ["the image collected no test"]
    if set(backend["collected"]) != full:
        errors += _listed(
            "backend collected fewer tests than the image:",
            full - set(backend["collected"]),
        )
        errors += _listed(
            "backend collected tests the image did not:",
            set(backend["collected"]) - full,
        )

    for entry in manifest["docker"]:
        if not any(selects(entry["select"], t) for t in full):
            errors.append(f"docker_suite.json: {entry['select']} selects no test")
    expected = docker_ids(manifest, sorted(full))
    if not expected:
        errors.append("docker_suite.json selects no test")
    if set(docker["collected"]) != expected:
        errors += _listed(
            "the docker job did not run what docker_suite.json lists:",
            expected ^ set(docker["collected"]),
        )

    for name, report in (("backend", backend), ("docker", docker)):
        failed = {t for t, outcome in report["outcomes"].items() if outcome == FAILED}
        if failed:
            errors += _listed(f"{name} tests that failed:", failed)
        unfinished = set(report["collected"]) - set(report["outcomes"])
        if unfinished:
            errors += _listed(
                f"{name} tests collected but with no outcome (the run ended early):",
                unfinished,
            )
    # A listed test is there to be checked in the image. It passes on the runner too, so
    # "ran in one of the two jobs" would stay true when the image skips it (a missing tool,
    # a changed user).
    skipped_in_image = {t for t in expected if docker["outcomes"].get(t) == SKIPPED}
    if skipped_in_image:
        errors += _listed(
            "tests of the docker list that were skipped in the image "
            "(a listed test has to pass there):",
            skipped_in_image,
        )

    ran = _executed(backend) | _executed(docker)
    nowhere = {entry["id"] for entry in manifest["skipped_everywhere"]}
    for t in sorted(nowhere):
        if t not in full:
            errors.append(f"skipped_everywhere: {t} is not a test of the suite")
        elif t in ran:
            errors.append(
                f"skipped_everywhere: {t} ran; remove it from the list so it stays checked"
            )
    never = full - ran - nowhere
    if never:
        errors += _listed(
            "tests that ran in neither job (skipped in the backend job and not in "
            "docker_suite.json; add the test, or its file, to the docker list):",
            never,
        )
    return errors


def summary(
    manifest: dict, backend: list[dict], docker: dict, image: dict
) -> list[str]:
    full = set(image["collected"])
    merged, _ = merge_backend(backend)
    in_backend, in_docker = _executed(merged), _executed(docker)
    shards = [
        f"backend shard {n}: collected {len(r['collected'])}, ran {len(_executed(r))}"
        for n, r in enumerate(backend, 1)
    ]
    return [
        f"whole suite (collected in the image): {len(full)}",
        *shards,
        f"backend job: collected {len(merged['collected'])}, ran {len(in_backend)}",
        f"docker job: collected {len(docker['collected'])}, ran {len(in_docker)}",
        f"ran only in docker: {len(in_docker - in_backend)}",
        f"ran in neither (skipped_everywhere): {len(full - in_backend - in_docker)} of "
        f"{len(manifest['skipped_everywhere'])} listed",
    ]


# ---- command line --------------------------------------------------------------------------


def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--manifest", default=str(MANIFEST))
    commands = parser.add_subparsers(dest="command", required=True)
    args_command = commands.add_parser(
        "args", parents=[common], help="print the docker list as pytest arguments"
    )
    args_command.add_argument("--prefix", default="", help="put before every selector")
    shard_command = commands.add_parser(
        "shard", help="print one backend shard's pytest arguments, one a line"
    )
    shard_command.add_argument("shard", choices=BACKEND_SHARDS)
    verify = commands.add_parser(
        "verify", parents=[common], help="check that the jobs run the whole suite"
    )
    verify.add_argument(
        "--backend",
        required=True,
        action="append",
        help="a backend shard's run report; once for each shard",
    )
    verify.add_argument("--docker", required=True, help="docker job's run report")
    verify.add_argument(
        "--image", required=True, help="collect-only report made in the image"
    )
    options = parser.parse_args(argv)

    if options.command == "shard":
        for arg in shard_args(options.shard):
            print(arg)
        return 0
    manifest = load_manifest(Path(options.manifest))
    if options.command == "args":
        for entry in manifest["docker"]:
            print(options.prefix + entry["select"])
        return 0
    backend, docker, image = (
        [_read(path) for path in options.backend],
        _read(options.docker),
        _read(options.image),
    )
    errors = problems(manifest, backend, docker, image)
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        print(f"suite split: {len(errors)} problem line(s)", file=sys.stderr)
        return 1
    for line in summary(manifest, backend, docker, image):
        print(line)
    print("suite split: every test of the suite ran in at least one job")
    return 0


if __name__ == "__main__":
    sys.exit(main())
