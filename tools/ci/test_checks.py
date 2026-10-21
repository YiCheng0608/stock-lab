"""Test routing without running product services or writing fixtures."""

import json
import re
import unittest

from checks import (
    HIGH_RISK_PATHS,
    LINT_COMMANDS,
    ROOT,
    ac_results,
    change_flags,
    high_risk,
    markdown_errors,
    pr_errors,
)


class RoutingTests(unittest.TestCase):
    def test_docs_only_skips_product_jobs(self):
        self.assertEqual(
            change_flags(["docs/ROADMAP.md", "README.md"]),
            {"python": False, "frontend": False},
        )

    def test_frontend_change(self):
        self.assertEqual(
            change_flags(["frontend/scripts/ci-test.cjs"]),
            {"python": False, "frontend": True},
        )
        self.assertEqual(
            change_flags(["frontend/src/App.tsx"]), {"python": False, "frontend": True}
        )

    def test_backend_also_checks_frontend_contracts(self):
        self.assertEqual(
            change_flags(["backend/app/example.py"]), {"python": True, "frontend": True}
        )

    def test_shared_runner_and_workflow_require_both(self):
        for name in [
            "tools/ci/checks.py",
            ".github/workflows/ci.yml",
            "tools/deleted-runner.py",
        ]:
            self.assertTrue(all(change_flags([name]).values()))

    def test_product_markdown_skips_product_jobs(self):
        for name in [
            "frontend/README.md",
            "backend/README.md",
            "tools/README.md",
            "frontend/NOTES.MD",
        ]:
            self.assertEqual(
                change_flags([name]), {"python": False, "frontend": False}, name
            )

    def test_markdown_does_not_hide_product_code(self):
        self.assertEqual(
            change_flags(["frontend/README.md", "frontend/scripts/ci-test.cjs"]),
            {"python": False, "frontend": True},
        )
        self.assertEqual(
            change_flags(["frontend/README.md", "frontend/src/App.tsx"]),
            {"python": False, "frontend": True},
        )
        self.assertEqual(
            change_flags(["backend/README.md", "backend/app/example.py"]),
            {"python": True, "frontend": True},
        )

    def test_shared_markdown_still_requires_both(self):
        for name in ["tools/ci/README.md", ".github/workflows/README.md"]:
            self.assertEqual(
                change_flags([name]), {"python": True, "frontend": True}, name
            )

    def test_dependency_constraints_require_python(self):
        self.assertTrue(
            change_flags(["backend/validation-requirements.lock.txt"])["python"]
        )

    def test_unread_frontend_and_docs_paths_stay_out_of_python(self):
        for name in [
            "frontend/src/App.tsx",
            "frontend/src/api.ts",
            "frontend/package.json",
            "frontend/pnpm-lock.yaml",
            "frontend/vite.config.ts",
            "frontend/scripts/ci-test.cjs",
            "frontend/src/NOTES.md",
            "docs/ROADMAP.md",
            "docs/DATA_SOURCES.md",
            "docs/INDUSTRY_CLASSIFICATION.md",
        ]:
            self.assertFalse(change_flags([name])["python"], name)

    def test_frontend_files_literally_read_by_backend_tests_require_python(self):
        # Principle: whatever backend/tests reads from the working tree must run the backend job.
        # node_modules is installed from package.json and pnpm-lock.yaml, which are routed above.
        read = set()
        for path in sorted((ROOT / "backend/tests").glob("*.py")):
            read.update(
                re.findall(
                    r"frontend/(?!node_modules)[\w./-]+",
                    path.read_text(encoding="utf-8"),
                )
            )
        for name in sorted(read):
            self.assertTrue(change_flags([name])["python"], name)

    def test_docs_read_by_backend_tests_require_python(self):
        for path in sorted((ROOT / "backend/tests").glob("*.py")):
            for name in re.findall(
                r'"docs" / "([\w.-]+)"', path.read_text(encoding="utf-8")
            ):
                self.assertTrue(change_flags([f"docs/{name}"])["python"], name)
        self.assertTrue(change_flags(["docs/OPERATIONS.md"])["python"])

    def test_links(self):
        self.assertEqual(
            markdown_errors(
                "README.md",
                "[ok](docs/ROADMAP.md) [web](https://example.com) [anchor](#x)",
            ),
            [],
        )
        self.assertEqual(
            len(markdown_errors("README.md", "[bad](nonexistent-ci-link-target.md)")), 1
        )

    def test_missing_links_with_titles(self):
        for title in ['"title"', "'title'", "(title)"]:
            self.assertEqual(
                len(
                    markdown_errors(
                        "README.md", f"[bad](nonexistent-ci-link-target.md {title})"
                    )
                ),
                1,
            )

    def test_reference_links_and_footnotes(self):
        self.assertEqual(
            len(
                markdown_errors(
                    "README.md",
                    "[bad][missing]\n\n[missing]: nonexistent-ci-link-target.md 'title'",
                )
            ),
            1,
        )
        self.assertEqual(
            markdown_errors("README.md", "[^note]: This is prose, not a link."), []
        )

    def test_fenced_examples_are_not_links(self):
        self.assertEqual(
            markdown_errors(
                "README.md", "```md\n[example](nonexistent-ci-link-target.md)\n```"
            ),
            [],
        )


class LintTests(unittest.TestCase):
    def test_lint_covers_whole_backend_and_tools_with_repository_settings(self):
        self.assertEqual(
            [command[:2] for command in LINT_COMMANDS],
            [("ruff", "check"), ("ruff", "format")],
        )
        self.assertIn("--check", LINT_COMMANDS[1])
        for command in LINT_COMMANDS:
            self.assertEqual(command[-2:], ("backend", "tools"))
            self.assertNotIn("--isolated", command)
            self.assertFalse(
                any(
                    arg.startswith(("--select", "--ignore", "--config"))
                    for arg in command
                ),
                command,
            )
        self.assertTrue((ROOT / "ruff.toml").is_file())


# Real merged PRs (body, changed paths, labels, non-merge commit messages) from the GitHub API.
SAMPLES = json.loads((ROOT / "tools/ci/pr_samples.json").read_text(encoding="utf-8"))
GOOD_BODY = """Closes #12

## 怎麼驗證

- [x] AC 逐條結果：
  - AC-1：`pytest tests/test_x.py`／3 passed／2026-10-16
  - AC-2：[留言](https://github.com/o/r/issues/12#issuecomment-1)

![desktop](https://example.com/a.png)
"""
API = ["backend/app/api.py"]


def rules(errors: list[str]) -> list[str]:
    return sorted({error.split(":", 1)[0] for error in errors})


class PrGateTests(unittest.TestCase):
    def check(self, body=GOOD_BODY, paths=(), labels=(), commits=None):
        return pr_errors(body, list(paths), list(labels), commits or {"a" * 40: "x"})

    def sample(self, number, labels=None):
        sample = SAMPLES[number]
        return pr_errors(
            sample["body"],
            sample["paths"],
            sample["labels"] if labels is None else labels,
            sample["commits"],
        )

    def test_pr_209_passes_every_rule(self):
        self.assertEqual(self.sample("209"), [])

    def test_pr_223_fails_only_d(self):
        paths = SAMPLES["223"]["paths"]
        self.assertIn("backend/alembic/versions/0016_group_score_archive.py", paths)
        self.assertIn("backend/worker/pipeline.py", paths)
        errors = self.sample("223")
        self.assertEqual(rules(errors), ["d"], errors)
        self.assertEqual(self.sample("223", labels=["independent-review"]), [])

    def test_a_product_change_needs_closes(self):
        self.assertEqual(self.check(paths=API), [])
        body = GOOD_BODY.replace("Closes #12", "Part of #12")
        self.assertEqual(rules(self.check(body, API)), ["a"])
        # The template placeholder is not a closing reference.
        body = GOOD_BODY.replace("Closes #12", "Closes #<issue>")
        self.assertEqual(rules(self.check(body, API)), ["a"])

    def test_a_applies_to_product_and_high_risk_paths_only(self):
        body = GOOD_BODY.replace("Closes #12", "")
        for path in [
            "backend/app/api.py",
            "backend/worker/cli.py",
            "backend/alembic/env.py",
            "backend/data/x.json",
            "frontend/src/App.tsx",
            "tools/ops/watchdog.sh",
            "tools/Invoke-WorkerJob.ps1",
        ]:
            self.assertIn("a", rules(self.check(body, [path])), path)
        for path in [
            "docs/ROADMAP.md",
            "backend/tests/test_api.py",
            "frontend/src/search.test.ts",
            "frontend/src/news/news.test.tsx",
            "frontend/scripts/ci-test.cjs",
            "tools/ci/checks.py",
            ".github/workflows/ci.yml",
        ]:
            self.assertEqual(self.check(body, [path]), [], path)

    def test_b_every_ac_needs_a_result(self):
        body = GOOD_BODY.replace(
            "  - AC-2：[留言](https://github.com/o/r/issues/12#issuecomment-1)",
            "  - AC-2：\n  - **AC-3**： ／ ／",
        )
        errors = self.check(body, API)
        self.assertEqual(rules(errors), ["b"])
        self.assertEqual(
            [e for e in errors if "AC-2" in e or "AC-3" in e], errors, errors
        )
        self.assertEqual(len(errors), 2, errors)

    def test_b_result_may_be_nested_under_the_item(self):
        body = GOOD_BODY.replace(
            "  - AC-2：[留言](https://github.com/o/r/issues/12#issuecomment-1)",
            "  - **AC-2**：\n    - 副本讀回 820 列\n  - AC-3：\n\n    ```\n    ok\n    ```",
        )
        self.assertEqual(ac_results(body).keys(), {"AC-1", "AC-2", "AC-3"})
        self.assertEqual(self.check(body, API), [])

    def test_b_template_guidance_and_empty_template_lines_fail(self):
        body = (
            "Closes #12\n\n- AC 逐條結果：\n"
            "  <!-- 每條一行：AC-n：命令或查詢／輸出或連結／資料日期 -->\n"
            "  - AC-1：\n  - AC-2：\n"
        )
        self.assertEqual(rules(self.check(body, ["docs/x.md"])), ["b"])
        self.assertEqual(len(self.check(body, ["docs/x.md"])), 2)

    def test_b_section_required_only_when_a_applies(self):
        body = "Closes #12\n\n## 做了什麼\n"
        self.assertEqual(rules(self.check(body, API)), ["b"])
        self.assertEqual(self.check(body, ["docs/ROADMAP.md"]), [])
        listed_nothing = body + "\n- [x] AC 逐條結果：不適用\n"
        self.assertEqual(rules(self.check(listed_nothing, API)), ["b"])
        self.assertEqual(self.check(listed_nothing, ["docs/ROADMAP.md"]), [])

    def test_unfilled_template_fails_and_filled_template_passes(self):
        template = (ROOT / ".github/pull_request_template.md").read_text(
            encoding="utf-8"
        )
        errors = self.check(template, API)
        self.assertEqual(rules(errors), ["a", "b"], errors)
        self.assertEqual(len(errors), 4, errors)  # no Closes, AC-1..3 empty
        filled = template.replace("#<issue>", "#12")
        for n in (1, 2, 3):
            filled = filled.replace(
                f"  - AC-{n}：\n", f"  - AC-{n}：`pytest -k x`／1 passed／無\n"
            )
        self.assertEqual(self.check(filled, API), [])

    def test_b_section_ends_at_next_heading(self):
        body = GOOD_BODY + "\n## 未做\n\n- AC-9 之後再說\n"
        self.assertEqual(ac_results(body).keys(), {"AC-1", "AC-2"})

    def test_c_frontend_source_needs_screenshot(self):
        body = GOOD_BODY.replace("![desktop](https://example.com/a.png)", "")
        app = ["frontend/src/App.tsx"]
        self.assertEqual(rules(self.check(body, app)), ["c"])
        self.assertEqual(self.check(body, ["frontend/src/units.test.ts"]), [])
        for evidence in [
            "![m](https://example.com/m.png)",
            '<img width="390" src="https://example.com/m.png">',
            "[截圖](https://github.com/o/r/blob/pr-assets/12/m.png)",
        ]:
            self.assertEqual(self.check(body + evidence, app), [], evidence)

    def test_d_high_risk_paths_need_label(self):
        for path in [
            "backend/alembic/versions/0016_group_score_archive.py",
            "backend/app/migrations.py",
            "backend/app/migration_revisions.py",
            "backend/app/indicators.py",
            "backend/worker/pipeline.py",
            "tools/ops/agent_guard.cjs",
            "tools/Register-WorkerSchedule.ps1",
        ]:
            self.assertEqual(rules(self.check(paths=[path])), ["d"], path)
            labelled = self.check(paths=[path], labels=["independent-review"])
            self.assertEqual(labelled, [], path)
        for path in [
            "backend/app/api.py",
            "tools/ci/x.ps1",
            "tools/ci/checks.py",
            "x/tools/a.ps1",
        ]:
            self.assertEqual(high_risk([path]), [], path)

    def test_high_risk_entries_exist(self):
        for entry in HIGH_RISK_PATHS:
            self.assertTrue(list(ROOT.glob(entry.rstrip("/"))), entry)

    def test_e_commit_messages_without_closing_keywords(self):
        for message in [
            "Fix #12 typo",
            "[226] fixes #3",
            "closed #4",
            "Resolves: #5",
            "body\n\nCloses #6",
            "RESOLVE #7",
        ]:
            errors = self.check(paths=["docs/x.md"], commits={"b" * 40: message})
            self.assertEqual(rules(errors), ["e"], message)
        for message in [
            "[226] Gate PRs on Closes in the body",
            "prefix #12",
            "Refs #12",
            "fix the #12 regression later",
            "Close the gate (#12)",
        ]:
            errors = self.check(paths=["docs/x.md"], commits={"b" * 40: message})
            self.assertEqual(errors, [], message)


if __name__ == "__main__":
    unittest.main()
