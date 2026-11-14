"""The backend/docker job split of CI (#378): suite_split.py and import_modules.py."""

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import unittest.mock

import import_modules
import suite_split
from suite_split import FAILED, PASSED, SKIPPED, problems

ROOT = suite_split.ROOT

ENV = "tests/test_env.py::test_in_the_image"
WIN = "tests/test_win.py::test_nt_only"
ONE = "tests/test_a.py::test_one"
PARAM_X = "tests/test_a.py::test_two[x]"
PARAM_Y = "tests/test_a.py::test_two[y]"
FULL = [ENV, WIN, ONE, PARAM_X, PARAM_Y]

MANIFEST = {
    "docker": [{"select": "tests/test_env.py", "reason": "r"}],
    "skipped_everywhere": [{"id": WIN, "reason": "Windows"}],
}


def run(outcomes: dict[str, str]) -> dict:
    return {"collect_only": False, "collected": sorted(outcomes), "outcomes": outcomes}


def reports() -> tuple[dict, dict, dict]:
    """A healthy split: the image skips nothing it should run; the runner skips ENV and WIN."""
    backend = run(
        {ONE: PASSED, PARAM_X: PASSED, PARAM_Y: PASSED, ENV: SKIPPED, WIN: SKIPPED}
    )
    docker = run({ENV: PASSED})
    image = {"collect_only": True, "collected": sorted(FULL), "outcomes": {}}
    return backend, docker, image


class Verify(unittest.TestCase):
    def check(self, manifest=MANIFEST, mutate=lambda b, d, i: None):
        backend, docker, image = reports()
        mutate(backend, docker, image)
        return problems(manifest, [backend], docker, image)

    def test_a_healthy_split_has_no_problem(self):
        self.assertEqual(self.check(), [])

    @staticmethod
    def shards(backend: dict, *firsts: set[str]) -> list[dict]:
        """The backend report cut in two: each first shard takes the given ids, the last the
        rest (an id in two shards when the sets overlap)."""
        taken = set().union(*firsts)
        rest = set(backend["collected"]) - taken
        return [
            run({t: backend["outcomes"][t] for t in ids}) for ids in (*firsts, rest)
        ]

    def test_two_shards_that_together_run_the_suite_have_no_problem(self):
        backend, docker, image = reports()
        shards = self.shards(backend, {ONE, PARAM_X})
        self.assertEqual(problems(MANIFEST, shards, docker, image), [])
        summary = suite_split.summary(MANIFEST, shards, docker, image)
        self.assertIn("backend shard 1: collected 2, ran 2", summary)
        self.assertIn("backend shard 2: collected 3, ran 1", summary)
        self.assertIn("backend job: collected 5, ran 3", summary)

    def test_a_test_in_both_shards_fails(self):
        """#746: the shards split the suite; a test in both runs twice."""
        backend, docker, image = reports()
        ops, rest = self.shards(backend, {ONE, PARAM_X})
        rest["collected"] = sorted({*rest["collected"], PARAM_X})
        rest["outcomes"][PARAM_X] = PASSED
        errors = problems(MANIFEST, [ops, rest], docker, image)
        self.assertEqual(
            errors, ["tests collected by more than one backend shard:", f"  {PARAM_X}"]
        )

    def test_a_test_in_neither_shard_fails(self):
        """#746: a file both shards leave out (the rest shard ignoring a file that is not in
        the ops shard) is a test the image collected and no backend shard did."""
        backend, docker, image = reports()
        ops, rest = self.shards(backend, {ONE, PARAM_X})
        rest["collected"].remove(PARAM_Y)
        del rest["outcomes"][PARAM_Y]
        errors = problems(MANIFEST, [ops, rest], docker, image)
        self.assertEqual(
            errors[:2],
            ["backend collected fewer tests than the image:", f"  {PARAM_Y}"],
        )

    def test_a_failure_in_one_shard_fails_whatever_the_other(self):
        backend, docker, image = reports()
        ops, rest = self.shards(backend, {ONE, PARAM_X})
        ops["outcomes"][ONE] = FAILED
        errors = problems(MANIFEST, [ops, rest], docker, image)
        self.assertEqual(errors[:2], ["backend tests that failed:", f"  {ONE}"])
        merged, _ = suite_split.merge_backend([ops, run({ONE: PASSED})])
        self.assertEqual(merged["outcomes"][ONE], FAILED)

    def test_no_backend_report_fails(self):
        _, docker, image = reports()
        self.assertEqual(problems(MANIFEST, [], docker, image), ["no backend report"])

    def test_a_test_only_the_image_runs_must_stay_in_the_docker_list(self):
        """The mutation of AC-2: ENV is skipped on the runner and dropped from the list."""
        manifest = copy.deepcopy(MANIFEST)
        manifest["docker"] = [{"select": "tests/test_a.py", "reason": "r"}]

        def docker_runs_test_a(backend, docker, image):
            docker.update(run({ONE: PASSED, PARAM_X: PASSED, PARAM_Y: PASSED}))

        errors = self.check(manifest, docker_runs_test_a)
        self.assertIn(f"  {ENV}", errors)
        self.assertTrue(
            any(line.startswith("tests that ran in neither job") for line in errors)
        )
        self.assertNotIn(f"  {WIN}", errors)

    def test_a_listed_test_skipped_in_the_image_fails_though_the_runner_passed_it(self):
        """The hole of the first version: ENV passes on the runner, so every test still ran
        somewhere, yet the image no longer runs what the list is there to check."""

        def image_skips_it(backend, docker, image):
            backend["outcomes"][ENV] = PASSED
            docker["outcomes"][ENV] = SKIPPED

        errors = self.check(mutate=image_skips_it)
        self.assertEqual(
            errors,
            [
                "tests of the docker list that were skipped in the image "
                "(a listed test has to pass there):",
                f"  {ENV}",
            ],
        )

    def test_a_listed_test_that_passes_in_the_image_and_the_runner_is_fine(self):
        self.assertEqual(
            self.check(mutate=lambda b, d, i: b["outcomes"].update({ENV: PASSED})), []
        )

    def test_the_backend_job_collecting_less_than_the_image_fails(self):
        def narrowed(backend, docker, image):
            del backend["outcomes"][PARAM_Y]
            backend["collected"].remove(PARAM_Y)

        errors = self.check(mutate=narrowed)
        self.assertEqual(errors[0], "backend collected fewer tests than the image:")
        self.assertIn(f"  {PARAM_Y}", errors)

    def test_the_backend_job_collecting_more_than_the_image_fails(self):
        def wider(backend, docker, image):
            extra = "tests/test_extra.py::test_only_on_the_runner"
            backend["collected"].append(extra)
            backend["outcomes"][extra] = PASSED

        errors = self.check(mutate=wider)
        self.assertIn("backend collected tests the image did not:", errors)

    def test_a_docker_job_that_ran_something_else_than_the_list_fails(self):
        def ran_all(backend, docker, image):
            docker.update(run({ENV: PASSED, ONE: PASSED}))

        errors = self.check(mutate=ran_all)
        self.assertIn(
            "the docker job did not run what docker_suite.json lists:", errors
        )
        self.assertIn(f"  {ONE}", errors)

    def test_a_docker_job_that_ran_nothing_fails(self):
        errors = self.check(mutate=lambda b, d, i: d.update(run({})))
        self.assertIn(
            "the docker job did not run what docker_suite.json lists:", errors
        )
        self.assertIn(f"  {ENV}", errors)

    def test_a_selector_that_selects_nothing_fails(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["docker"].append({"select": "tests/test_renamed.py", "reason": "r"})
        self.assertIn(
            "docker_suite.json: tests/test_renamed.py selects no test",
            self.check(manifest),
        )

    def test_a_list_that_selects_no_test_fails(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["docker"] = []
        self.assertIn("docker_suite.json selects no test", self.check(manifest))

    def test_a_test_skipped_everywhere_must_be_listed(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["skipped_everywhere"] = []
        errors = self.check(manifest)
        self.assertIn(f"  {WIN}", errors)

    def test_a_stale_skipped_everywhere_entry_fails(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["skipped_everywhere"].append({"id": ONE, "reason": "stale"})
        manifest["skipped_everywhere"].append(
            {"id": "tests/gone.py::t", "reason": "gone"}
        )
        errors = self.check(manifest)
        self.assertTrue(any(f"{ONE} ran;" in line for line in errors), errors)
        self.assertIn(
            "skipped_everywhere: tests/gone.py::t is not a test of the suite", errors
        )

    def test_a_failed_test_fails_whichever_job_ran_it(self):
        errors = self.check(mutate=lambda b, d, i: b["outcomes"].update({ONE: FAILED}))
        self.assertIn("backend tests that failed:", errors)
        errors = self.check(mutate=lambda b, d, i: d["outcomes"].update({ENV: FAILED}))
        self.assertIn("docker tests that failed:", errors)

    def test_a_test_with_no_outcome_fails(self):
        def cut_short(backend, docker, image):
            del backend["outcomes"][PARAM_Y]

        errors = self.check(mutate=cut_short)
        self.assertIn(
            "backend tests collected but with no outcome (the run ended early):", errors
        )

    def test_a_report_of_the_wrong_kind_fails(self):
        errors = self.check(mutate=lambda b, d, i: i.update(collect_only=False))
        self.assertEqual(
            errors, ["the image collect-only report is not a collect-only report"]
        )
        errors = self.check(mutate=lambda b, d, i: b.update(collect_only=True))
        self.assertEqual(errors, ["the backend report is not a run report"])

    def test_an_empty_image_collection_fails(self):
        errors = self.check(mutate=lambda b, d, i: i.update(collected=[]))
        self.assertEqual(errors, ["the image collected no test"])

    def test_a_long_list_is_cut(self):
        shown = suite_split._listed("h", [f"t{n:02}" for n in range(14)])
        self.assertEqual(len(shown), 12)
        self.assertEqual(shown[-1], "  ... and 4 more")


class Selectors(unittest.TestCase):
    def test_what_a_selector_picks(self):
        self.assertTrue(suite_split.selects("tests/test_a.py", PARAM_X))
        self.assertTrue(suite_split.selects("tests/test_a.py::test_two", PARAM_X))
        self.assertTrue(
            suite_split.selects("tests/test_a.py::Cls", "tests/test_a.py::Cls::t")
        )
        self.assertTrue(suite_split.selects(ONE, ONE))
        self.assertFalse(suite_split.selects("tests/test_a.py::test_on", ONE))
        self.assertFalse(suite_split.selects("tests/test_a.py", "tests/test_ab.py::t"))
        self.assertFalse(suite_split.selects("tests/test_a", ONE))

    def test_args_prints_the_list_with_a_prefix(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(suite_split.main(["args", "--prefix", "backend/"]), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(
            lines,
            ["backend/" + e["select"] for e in suite_split.load_manifest()["docker"]],
        )


class TheListInTheRepository(unittest.TestCase):
    """docker_suite.json names tests that exist (the check in CI compares with a real collect)."""

    def test_every_entry_has_a_reason_and_names_an_existing_test(self):
        manifest = suite_split.load_manifest()
        entries = [(e["select"], e) for e in manifest["docker"]] + [
            (e["id"], e) for e in manifest["skipped_everywhere"]
        ]
        self.assertTrue(manifest["docker"])
        self.assertEqual(len({name for name, _ in entries}), len(entries), "duplicates")
        for name, entry in entries:
            with self.subTest(name):
                self.assertTrue(entry["reason"].strip())
                file, _, test = name.partition("::")
                path = suite_split.BACKEND / file
                self.assertTrue(path.is_file(), path)
                if test:
                    function = test.split("[")[0].split("::")[-1]
                    self.assertRegex(
                        path.read_text(encoding="utf-8"),
                        rf"(?m)^(?:async )?def {re.escape(function)}\(",
                    )

    def test_the_workflow_runs_the_split(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("tools/ci/suite_split.py verify", workflow)
        self.assertIn("tools/ci/suite_split.py args", workflow)
        self.assertIn("tools/ci/import_modules.py", workflow)
        # backend run, docker run, docker collect-only
        self.assertEqual(workflow.count("--suite-report"), 3)
        # required waits for the suite job and holds it to the python flag like backend and docker
        self.assertRegex(workflow, r"needs: \[[^\]]*\bsuite\b[^\]]*\]")
        self.assertIn("('suite', 'python')", workflow)

    def test_a_job_that_succeeds_has_uploaded_a_new_report(self):
        """Re-running one job uploads its report again under the same name (the run then holds
        two) and download-artifact takes the newest of a name (run 41070847498, attempt 2). That
        holds only if a successful job always uploads: a missing file must fail the step."""
        import yaml

        workflow = yaml.load(
            (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        uploads = {
            step["with"]["name"]: step["with"]
            for job in ("backend", "docker")
            for step in workflow["jobs"][job]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@")
            and step["with"]["name"].startswith("suite-")
        }
        self.assertEqual(
            sorted(uploads), ["suite-backend-${{ matrix.shard }}", "suite-docker"]
        )
        for name, options in uploads.items():
            with self.subTest(name):
                self.assertEqual(options["if-no-files-found"], "error")
        downloads = [
            step["with"]
            for step in workflow["jobs"]["suite"]["steps"]
            if step.get("uses", "").startswith("actions/download-artifact@")
        ]
        self.assertEqual([d["pattern"] for d in downloads], ["suite-*"])


def shard_files(shard: str, files: list[str]) -> set[str]:
    """The test files (relative to backend/) a shard's pytest arguments select."""
    args = suite_split.shard_args(shard)
    ignored = {a.removeprefix("--ignore=") for a in args if a.startswith("--ignore=")}
    selected = [a for a in args if not a.startswith("--")]
    return {
        f
        for f in files
        if f not in ignored and any(f == s or f.startswith(s + "/") for s in selected)
    }


class Shards(unittest.TestCase):
    """The two backend shards (#746): the list is in suite_split.py only."""

    def test_every_file_of_the_ops_shard_exists(self):
        """A renamed test file left in the list would select nothing (and ignore nothing)."""
        self.assertTrue(suite_split.OPS_SHARD)
        self.assertEqual(len(set(suite_split.OPS_SHARD)), len(suite_split.OPS_SHARD))
        for path in suite_split.OPS_SHARD:
            with self.subTest(path):
                self.assertRegex(path, r"^tests/test_[^/]+\.py$")
                self.assertTrue((suite_split.BACKEND / path).is_file(), path)

    def test_every_test_file_is_in_exactly_one_shard(self):
        files = sorted(
            p.relative_to(suite_split.BACKEND).as_posix()
            for p in (suite_split.BACKEND / "tests").rglob("test_*.py")
        )
        self.assertTrue(files)
        picked = {s: shard_files(s, files) for s in suite_split.BACKEND_SHARDS}
        self.assertEqual(picked["ops"], set(suite_split.OPS_SHARD))
        for f in files:
            with self.subTest(f):
                self.assertEqual(
                    len([s for s in suite_split.BACKEND_SHARDS if f in picked[s]]), 1
                )

    def test_shard_prints_the_arguments_one_a_line(self):
        for shard in suite_split.BACKEND_SHARDS:
            with self.subTest(shard):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(suite_split.main(["shard", shard]), 0)
                self.assertEqual(
                    out.getvalue().splitlines(), suite_split.shard_args(shard)
                )
        self.assertEqual(suite_split.shard_args("rest")[-1], "tests")
        with self.assertRaises(ValueError):
            suite_split.shard_args("all")

    def test_the_workflow_runs_each_shard_and_verifies_both(self):
        import yaml

        workflow_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        jobs = yaml.load(workflow_text, Loader=yaml.BaseLoader)["jobs"]
        strategy = jobs["backend"]["strategy"]
        self.assertEqual(strategy["matrix"]["shard"], list(suite_split.BACKEND_SHARDS))
        # A red shard must not cancel the other: both report what they ran.
        self.assertEqual(strategy["fail-fast"], "false")
        self.assertEqual(jobs["backend"]["env"]["SHARD"], "${{ matrix.shard }}")
        (pytest,) = [
            s for s in jobs["backend"]["steps"] if "-m pytest" in s.get("run", "")
        ]
        self.assertIn('suite_split.py shard "$SHARD"', pytest["run"])
        self.assertIn(
            '--suite-report "$RUNNER_TEMP/suite/backend-$SHARD.json"', pytest["run"]
        )
        (verify,) = [
            s
            for s in jobs["suite"]["steps"]
            if "suite_split.py verify" in s.get("run", "")
        ]
        self.assertEqual(
            re.findall(
                r'--backend "\$RUNNER_TEMP/suite/backend-(\w+)\.json"', verify["run"]
            ),
            list(suite_split.BACKEND_SHARDS),
        )
        uploads = {
            s["with"]["name"]: s["with"]
            for s in jobs["backend"]["steps"]
            if s.get("uses", "").startswith("actions/upload-artifact@")
        }
        self.assertEqual(
            uploads["suite-backend-${{ matrix.shard }}"]["path"],
            "${{ runner.temp }}/suite/backend-${{ matrix.shard }}.json",
        )
        # Every test's time stays for measuring (#746).
        junit = uploads["junit-backend-${{ matrix.shard }}"]
        self.assertEqual(junit["path"], "${{ runner.temp }}/pytest.xml")
        self.assertEqual(junit["retention-days"], "14")
        self.assertIn('--junitxml "$RUNNER_TEMP/pytest.xml"', pytest["run"])
        self.assertIn("--durations=30", pytest["run"])


class Plugin(unittest.TestCase):
    """The hooks, called the way pytest calls them, without pytest."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.root = self.dir / "backend"
        suite_split._ids.clear()
        suite_split._report.update(collect_only=False, collected=[], outcomes={})
        self.addCleanup(suite_split._ids.clear)

    def config(self, collect_only=False):
        options = {
            "suite_report": str(self.dir / "out" / "report.json"),
            "suite_root": str(self.root),
            "collectonly": collect_only,
        }
        return SimpleNamespace(getoption=options.__getitem__)

    def collect(self, config, *names):
        items = [
            SimpleNamespace(
                path=self.root / "tests" / "t.py", nodeid=f"backend/tests/t.py::{n}"
            )
            for n in names
        ]
        suite_split.pytest_collection_finish(
            SimpleNamespace(config=config, items=items)
        )

    @staticmethod
    def log(name, when, outcome):
        suite_split.pytest_runtest_logreport(
            SimpleNamespace(
                nodeid=f"backend/tests/t.py::{name}",
                when=when,
                failed=outcome == "failed",
                skipped=outcome == "skipped",
            )
        )

    def test_node_id_is_relative_to_the_root_whatever_the_rootdir(self):
        self.assertEqual(
            suite_split.node_id(
                self.root / "tests" / "t.py",
                "backend/tests/t.py::C::t[a::b]",
                self.root,
            ),
            "tests/t.py::C::t[a::b]",
        )
        self.assertEqual(
            suite_split.node_id(self.root / "tests" / "t.py", "tests/t.py", self.root),
            "tests/t.py",
        )

    def test_outcomes_of_the_phases(self):
        config = self.config()
        self.collect(
            config, "ok", "skip_in_setup", "skip_in_call", "bad", "bad_teardown"
        )
        for when in ("setup", "call", "teardown"):
            self.log("ok", when, "passed")
        self.log("skip_in_setup", "setup", "skipped")
        self.log("skip_in_setup", "teardown", "passed")
        self.log("skip_in_call", "setup", "passed")
        self.log("skip_in_call", "call", "skipped")
        self.log("skip_in_call", "teardown", "passed")
        self.log("bad", "setup", "passed")
        self.log("bad", "call", "failed")
        self.log("bad", "teardown", "passed")
        self.log("bad_teardown", "setup", "passed")
        self.log("bad_teardown", "call", "passed")
        self.log("bad_teardown", "teardown", "failed")
        self.log("not_collected", "call", "passed")
        suite_split.pytest_sessionfinish(SimpleNamespace(config=config))
        report = json.loads(
            (self.dir / "out" / "report.json").read_text(encoding="utf-8")
        )
        self.assertFalse(report["collect_only"])
        self.assertEqual(
            report["outcomes"],
            {
                "tests/t.py::ok": PASSED,
                "tests/t.py::skip_in_setup": SKIPPED,
                "tests/t.py::skip_in_call": SKIPPED,
                "tests/t.py::bad": FAILED,
                "tests/t.py::bad_teardown": FAILED,
            },
        )
        self.assertEqual(len(report["collected"]), 5)

    def test_under_xdist_the_controller_writes_what_the_workers_collected(self):
        """The backend job runs under pytest-xdist (#442): the controller collects nothing,
        each worker sends it the ids, and every worker collects the same ones."""
        config = self.config()
        config.rootpath = self.dir  # the rootdir is the parent of backend/ here
        controller = suite_split.XdistController()
        ids = ["backend/tests/t.py::ok", "backend/tests/t.py::bad"]
        for _worker in range(2):
            controller.pytest_xdist_node_collection_finished(
                SimpleNamespace(config=config), ids
            )
        for when in ("setup", "call", "teardown"):
            self.log("ok", when, "passed")
        self.log("bad", "setup", "passed")
        self.log("bad", "call", "failed")
        suite_split.pytest_sessionfinish(SimpleNamespace(config=config))
        report = json.loads(
            (self.dir / "out" / "report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["collected"], ["tests/t.py::bad", "tests/t.py::ok"])
        self.assertEqual(
            report["outcomes"], {"tests/t.py::ok": PASSED, "tests/t.py::bad": FAILED}
        )

    def test_an_xdist_worker_writes_no_report(self):
        """A worker saw only its share of the tests; writing would race the controller."""
        config = self.config()
        config.workerinput = {"workerid": "gw0"}
        self.collect(config, "ok")
        self.log("ok", "call", "passed")
        suite_split.pytest_sessionfinish(SimpleNamespace(config=config))
        self.assertFalse((self.dir / "out").exists())

    def test_the_xdist_hook_is_registered_only_with_xdist(self):
        """An unknown hook fails pytest's plugin validation; the docker job has no xdist."""
        for loaded in (False, True):
            with self.subTest(xdist=loaded):
                registered = []
                manager = SimpleNamespace(
                    hasplugin=lambda name: loaded and name == "xdist",
                    register=lambda plugin, name: registered.append(name),
                )
                suite_split.pytest_configure(SimpleNamespace(pluginmanager=manager))
                self.assertEqual(registered, ["suite_split_xdist"] if loaded else [])

    def test_an_xdist_worker_names_itself_in_each_tests_properties(self):
        """The junit report the backend job uploads then holds each test's worker (#746)."""
        for worker, report, expected in (
            ("gw3", "r.json", [("xdist_worker", "gw3")]),
            (None, "r.json", []),
            ("gw3", None, []),
        ):
            with self.subTest(worker=worker, report=report):
                options = {"suite_report": report}
                item = SimpleNamespace(
                    config=SimpleNamespace(getoption=options.__getitem__),
                    user_properties=[],
                )
                env = {
                    k: v for k, v in os.environ.items() if k != "PYTEST_XDIST_WORKER"
                }
                if worker:
                    env["PYTEST_XDIST_WORKER"] = worker
                with unittest.mock.patch.dict(os.environ, env, clear=True):
                    suite_split.pytest_runtest_setup(item)
                self.assertEqual(item.user_properties, expected)

    def test_without_the_option_nothing_is_written(self):
        options = {"suite_report": None}
        config = SimpleNamespace(getoption=options.__getitem__)
        suite_split.pytest_collection_finish(SimpleNamespace(config=config, items=[]))
        suite_split.pytest_sessionfinish(SimpleNamespace(config=config))
        self.assertEqual(list(self.dir.iterdir()), [])

    @unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest is not installed")
    def test_a_real_pytest_run_and_a_collect_only_run(self):
        """With xdist installed it also runs `-n 2`. CI never does: neither the repository
        job nor the image installs xdist, so there the parallel path is held end to end by
        the suite job, which compares the backend job's report (written by xdist's
        controller) with the image's collect-only report."""
        tests = self.root / "tests"
        tests.mkdir(parents=True)
        (tests / "test_m.py").write_text(
            "import pytest\n\n"
            "def test_pass(): pass\n\n"
            "@pytest.mark.skipif(True, reason='x')\n"
            "def test_skip(): pass\n\n"
            "@pytest.mark.parametrize('n', [1, 2])\n"
            "def test_param(n): assert n\n",
            encoding="utf-8",
        )

        def pytest_run(*extra: str) -> dict:
            out = self.dir / "r.json"
            subprocess.run(
                [
                    sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q",
                    "-p", "suite_split", "--suite-report", str(out),
                    "--suite-root", str(self.root), *extra, "tests",
                ],
                cwd=self.root,
                # Kept: the path where this process found xdist, when it did.
                env={
                    **os.environ,
                    "PYTHONPATH": os.pathsep.join(
                        filter(None, [str(Path(__file__).parent), os.environ.get("PYTHONPATH")])
                    ),
                },
                check=True,
                capture_output=True,
            )  # fmt: skip
            return json.loads(out.read_text(encoding="utf-8"))

        ran = pytest_run()
        self.assertFalse(ran["collect_only"])
        self.assertEqual(
            ran["outcomes"],
            {
                "tests/test_m.py::test_pass": PASSED,
                "tests/test_m.py::test_skip": SKIPPED,
                "tests/test_m.py::test_param[1]": PASSED,
                "tests/test_m.py::test_param[2]": PASSED,
            },
        )
        collected = pytest_run("--collect-only")
        self.assertTrue(collected["collect_only"])
        self.assertEqual(collected["outcomes"], {})
        self.assertEqual(collected["collected"], ran["collected"])
        subset = pytest_run("-k", "param")
        self.assertEqual(len(subset["collected"]), 2)
        if importlib.util.find_spec("xdist"):
            parallel = pytest_run("-n", "2")
            self.assertEqual(parallel["collected"], ran["collected"])
            self.assertEqual(parallel["outcomes"], ran["outcomes"])


class ImportModules(unittest.TestCase):
    def tree(self, **files: str) -> tuple[Path, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        package = "impmod_" + next(iter(files)).split("/")[0]
        for relative, text in files.items():
            path = root / package / relative.split("/", 1)[1]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.addCleanup(self.forget, package, root)
        return root, package

    @staticmethod
    def forget(package: str, root: Path) -> None:
        """Undo what importing the temporary package left: its modules and the sys.path entry."""
        for name in [
            n for n in sys.modules if n == package or n.startswith(package + ".")
        ]:
            del sys.modules[name]
        while str(root.resolve()) in sys.path:
            sys.path.remove(str(root.resolve()))

    def run_main(self, root: Path, package: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = import_modules.main(["--root", str(root), "--package", package])
        return code, out.getvalue(), err.getvalue()

    def test_a_missing_dependency_in_a_submodule_fails_the_step(self):
        root, package = self.tree(
            **{
                "a/__init__.py": "",
                "a/fine.py": "import json\n",
                "a/sub/__init__.py": "",
                "a/sub/needs_it.py": "import a_dependency_the_image_lacks\n",
                "a/__main__.py": "raise SystemExit(7)\n",
            }
        )
        code, out, err = self.run_main(root, package)
        self.assertEqual(code, 1)
        self.assertIn(f"{package}.sub.needs_it: ModuleNotFoundError", err)
        self.assertIn("a_dependency_the_image_lacks", err)
        self.assertIn("1 of 4 modules failed to import", err)
        self.assertNotIn(".fine", err)

    def test_a_module_that_exits_at_import_time_fails_the_step(self):
        root, package = self.tree(
            **{"b/__init__.py": "", "b/quits.py": "raise SystemExit(3)\n"}
        )
        code, _, err = self.run_main(root, package)
        self.assertEqual(code, 1)
        self.assertIn(f"{package}.quits: SystemExit", err)

    def test_every_module_importing_passes(self):
        root, package = self.tree(**{"c/__init__.py": "", "c/x.py": "X = 1\n"})
        code, out, err = self.run_main(root, package)
        self.assertEqual((code, out, err), (0, "imported 2 modules\n", ""))

    def test_a_package_without_modules_fails(self):
        root, package = self.tree(**{"d/data.txt": "x"})
        self.assertEqual(self.run_main(root, package)[0], 1)

    def test_the_names_are_the_packages_and_every_module_of_the_repository(self):
        names = [
            n
            for p in ("app", "worker")
            for n in import_modules.module_names(ROOT / "backend", p)
        ]
        for expected in (
            "app",
            "worker",
            "worker.serve",
            "worker.sources",
            "app.strategies",
            "app.strategies.base",
        ):
            self.assertIn(expected, names)
        files = sum(
            len(list((ROOT / "backend" / p).rglob("*.py"))) for p in ("app", "worker")
        )
        self.assertEqual(len(names), files)
        self.assertFalse(
            [n for n in names if n.endswith("__main__") or "__init__" in n]
        )


if __name__ == "__main__":
    unittest.main()
