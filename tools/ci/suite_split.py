"""Split the backend suite between CI's backend and docker jobs, and check nothing is lost (#378).

The backend job runs the whole of backend/tests on the runner. The docker job runs, inside the
backend image, only what docker_suite.json lists: tests whose subject is the execution
environment the image provides. Collecting is no proof of coverage (the backend job collects
everything, so a union of collected ids is always the whole suite); what counts is that every
test of the whole suite *ran* (passed) in at least one of the two jobs.

Three roles, one file:

* a pytest plugin (`-p suite_split --suite-report FILE`) writing the ids a run collected and what
  each did, with ids relative to backend/ so both jobs name a test the same way;
* `args`: the docker list as pytest arguments;
* `verify`: the check that fails CI, from the two reports and a collect-only report of the whole
  suite made inside the image.

The CLI uses the standard library only (the suite job has no dependencies installed).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MANIFEST = Path(__file__).with_name("docker_suite.json")

PASSED, SKIPPED, FAILED = "passed", "skipped", "failed"


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
    if not target:
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


def problems(manifest: dict, backend: dict, docker: dict, image: dict) -> list[str]:
    """Why the two jobs together do not run the whole suite; an empty list means they do.

    `image` is a collect-only report of the whole suite made in the image, `backend` the backend
    job's run of the whole suite on the runner, `docker` the docker job's run of the list."""
    errors: list[str] = []
    for name, report, collect_only in (
        ("backend", backend, False),
        ("docker", docker, False),
        ("image collect-only", image, True),
    ):
        if bool(report.get("collect_only")) != collect_only:
            kind = "a collect-only report" if collect_only else "a run report"
            errors.append(f"the {name} report is not {kind}")
    if errors:
        return errors

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


def summary(manifest: dict, backend: dict, docker: dict, image: dict) -> list[str]:
    full = set(image["collected"])
    in_backend, in_docker = _executed(backend), _executed(docker)
    return [
        f"whole suite (collected in the image): {len(full)}",
        f"backend job: collected {len(backend['collected'])}, ran {len(in_backend)}",
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
    verify = commands.add_parser(
        "verify", parents=[common], help="check that the two jobs run the whole suite"
    )
    verify.add_argument("--backend", required=True, help="backend job's run report")
    verify.add_argument("--docker", required=True, help="docker job's run report")
    verify.add_argument(
        "--image", required=True, help="collect-only report made in the image"
    )
    options = parser.parse_args(argv)

    manifest = load_manifest(Path(options.manifest))
    if options.command == "args":
        for entry in manifest["docker"]:
            print(options.prefix + entry["select"])
        return 0
    backend, docker, image = (
        _read(options.backend),
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
