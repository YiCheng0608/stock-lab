"""Test routing without running product services or writing fixtures."""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from checks import (
    HIGH_RISK_PATHS,
    LINT_COMMANDS,
    ROOT,
    ac_results,
    anchors,
    change_flags,
    changed_paths,
    documentation_errors,
    heading_slug,
    high_risk,
    markdown_errors,
    owns_errors,
    pr_changes,
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
                "# X\n[ok](docs/ROADMAP.md) [web](https://example.com) [anchor](#x)",
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
        # A fence indented under a list item is still a fence.
        self.assertEqual(
            markdown_errors(
                "README.md",
                "1. Step\n\n   ```text\n   [x](nonexistent-ci-link-target.md)\n   ```",
            ),
            [],
        )


class AnchorTests(unittest.TestCase):
    def test_slugs_of_headings_the_docs_link_to(self):
        # Each heading as written in docs/, and the anchor an existing link uses for it.
        for heading, anchor in [
            ("V1 範圍基線（2026-10-17 核定）", "v1-範圍基線2026-10-17-核定"),  # ROADMAP
            ("統籌 session", "統籌-session"),  # GITHUB_WORKFLOW
            ("Review 與合併", "review-與合併"),  # GITHUB_WORKFLOW
            (
                "6.2 daily／news 工作的註冊與管理",
                "62-dailynews-工作的註冊與管理",
            ),  # OPERATIONS
            (
                "2. 資料庫、migration 與 readiness",
                "2-資料庫migration-與-readiness",
            ),  # OPERATIONS
            ("8.1 今日／個股清單壓縮卡", "81-今日個股清單壓縮卡"),  # UI_COPY_SPEC
            ("8.4 數值表格、單位與空白", "84-數值表格單位與空白"),  # UI_COPY_SPEC
            ("價位、ETF 與生命週期", "價位etf-與生命週期"),  # V1_SPEC
            ("strategy_levels_v1", "strategy_levels_v1"),  # V1_SPEC
            ("策略框架與 registry", "策略框架與-registry"),  # V1_SPEC
        ]:
            self.assertEqual(heading_slug(heading), anchor, heading)

    def test_inline_markup_leaves_its_text(self):
        self.assertEqual(
            heading_slug("`breakout_v1` 與 [連結](x.md)"), "breakout_v1-與-連結"
        )
        self.assertEqual(heading_slug('<a id="x"></a>A／B'), "ab")

    def test_repeated_headings_html_ids_and_fences(self):
        text = '# 限制\n## 限制\n<a id="action-merge"></a>\n```md\n# 範例\n```\n'
        self.assertEqual(anchors(text), {"限制", "限制-1", "action-merge"})

    def test_anchors_into_markdown_files(self):
        roadmap = "docs/ROADMAP.md#v1-範圍基線2026-10-17-核定"
        self.assertEqual(
            markdown_errors(
                "README.md",
                f"[a]({roadmap}) [b](docs/GITHUB_WORKFLOW.md#%E7%B5%B1%E7%B1%8C-session) "
                "[c](tools/ci/checks.py#L1) [d](docs/PRODUCT_SPEC.md#action-merge)",
            ),
            [],
        )
        self.assertEqual(
            markdown_errors(
                "README.md", "[a](docs/ROADMAP.md#v1-範圍基線) [b](#nowhere)"
            ),
            [
                "README.md: no heading makes the anchor of docs/ROADMAP.md#v1-範圍基線",
                "README.md: no heading makes the anchor of #nowhere",
            ],
        )

    def test_absolute_links_into_master(self):
        repo = "https://github.com/YiCheng0608/stock-lab"
        self.assertEqual(
            markdown_errors(
                "docs/x.md",
                f"[a]({repo}/blob/master/docs/GITHUB_WORKFLOW.md#統籌-session) "
                f"[b]({repo}/tree/master/tools/ci) [c]({repo}/blob/pr-assets/gone.png) "
                f"[d]({repo}/issues/312)",
            ),
            [],
        )
        self.assertEqual(
            len(
                markdown_errors(
                    "docs/x.md",
                    f"[a]({repo}/blob/master/docs/GONE.md) "
                    f"[b]({repo}/blob/master/docs/ROADMAP.md#gone)",
                )
            ),
            2,
        )

    def test_every_document_link_and_owns_line_holds(self):
        self.assertEqual(documentation_errors(), [])


class OwnsTests(unittest.TestCase):
    def test_every_doc_has_an_owns_line(self):
        docs = sorted(p.name for p in (ROOT / "docs").glob("*.md"))
        self.assertTrue(docs)
        for name in [f"docs/{d}" for d in docs] + ["AGENTS.md"]:
            first = (ROOT / name).read_text(encoding="utf-8").split("\n", 1)[0]
            self.assertTrue(first.startswith("<!-- owns: "), name)

    def test_missing_empty_and_repeated_concepts(self):
        self.assertEqual(
            owns_errors(
                {
                    "AGENTS.md": "<!-- owns: 角色、流程變更 -->\n# A",
                    "docs/a.md": "# A\n<!-- owns: x -->",
                    "docs/b.md": "<!-- owns: 排程, Review -->\n",
                    "docs/c.md": "<!-- owns: review、、流程變更 -->\n",
                }
            ),
            [
                "docs/a.md: the first line is not <!-- owns: <concepts> -->",
                "docs/c.md: concept 'review' already owned by docs/b.md",
                "docs/c.md: empty concept in the owns line",
                "docs/c.md: concept '流程變更' already owned by AGENTS.md",
            ],
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

    def test_b_prose_naming_the_section_is_not_the_section(self):
        body = "## 做了什麼\n\n- b. 「AC 逐條結果」區每條要有內容\n\n" + GOOD_BODY
        self.assertEqual(ac_results(body).keys(), {"AC-1", "AC-2"})
        self.assertEqual(self.check(body, API), [])

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

    def test_e_reads_only_commits_since_the_merge_base(self):
        # git range in a temporary repository: master moved after the PR opened.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            sha = PrRange.build(repo)
            fork, paths, commits = pr_changes(sha["M"], repo)
            errors = pr_errors(GOOD_BODY, paths, [], commits)
            self.assertEqual((fork, errors), (sha["M"], []))
            _, paths, commits = pr_changes(sha["A"], repo)  # stale base
            self.assertEqual(
                rules(
                    pr_errors(GOOD_BODY.replace("Closes #12", ""), paths, [], commits)
                ),
                ["a", "d", "e"],
            )

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


class PrRange(unittest.TestCase):
    """pr_changes against the base branch tip, in a throwaway repository.

    A (master when the PR opened) -> P (PR: docs only); A -> M (master later: a worker
    file, a commit naming 'fixes #9'). CI checks out a merge ref with parents (M, P).
    """

    @staticmethod
    def git(repo: Path, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=repo,
            text=True,
        ).strip()

    @classmethod
    def build(cls, repo: Path) -> dict[str, str]:
        def git(*args: str) -> str:
            return cls.git(repo, *args)

        def commit(path: str, message: str) -> str:
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(message, encoding="utf-8")
            git("add", path)
            git("commit", "-q", "-m", message)
            return git("rev-parse", "HEAD")

        git("init", "-q", "-b", "master")
        sha = {"A": commit("README.md", "start")}
        git("checkout", "-q", "-b", "pr")
        sha["P"] = commit("docs/x.md", "[1] Docs")
        git("checkout", "-q", "master")
        sha["M"] = commit("backend/worker/x.py", "Worker change, fixes #9")
        git("checkout", "-q", "--detach", sha["M"])
        git("merge", "-q", "--no-ff", "-m", "Merge P into M", "pr")
        return sha

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.sha = self.build(self.repo)

    def test_merge_ref_with_current_tip_is_only_the_pr(self):
        fork, paths, commits = pr_changes(self.sha["M"], self.repo)
        self.assertEqual(fork, self.sha["M"])
        self.assertEqual(paths, ["docs/x.md"])
        self.assertEqual(list(commits), [self.sha["P"]])

    def test_stale_base_would_count_master_commits(self):
        # Why CI passes origin/<base ref>: the old base is an ancestor of the merge ref.
        _, paths, commits = pr_changes(self.sha["A"], self.repo)
        self.assertIn("backend/worker/x.py", paths)
        self.assertIn(self.sha["M"], commits)

    def test_base_ahead_of_the_branch_uses_the_merge_base(self):
        self.git(self.repo, "checkout", "-q", "pr")
        self.assertIn("backend/worker/x.py", changed_paths(self.sha["M"], self.repo))
        fork, paths, commits = pr_changes(self.sha["M"], self.repo)
        self.assertEqual(fork, self.sha["A"])
        self.assertEqual(paths, ["docs/x.md"])
        self.assertEqual(list(commits), [self.sha["P"]])

    def test_branch_that_merged_master_is_only_the_pr(self):
        def git(*args: str) -> str:
            return self.git(self.repo, *args)

        git("checkout", "-q", "pr")
        git("merge", "-q", "--no-ff", "-m", "Merge master into pr", "master")
        head = git("rev-parse", "HEAD")
        git("checkout", "-q", "--detach", self.sha["M"])
        git("merge", "-q", "--no-ff", "-m", "Merge pr into M", head)
        fork, paths, commits = pr_changes(self.sha["M"], self.repo)
        self.assertEqual((fork, paths), (self.sha["M"], ["docs/x.md"]))
        self.assertEqual(list(commits), [self.sha["P"]])

    def test_ci_passes_the_base_branch_tip_not_the_event_base_sha(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        (run,) = re.findall(r"run: (.*checks\.py pr .*)", workflow)
        self.assertIn('--base "$(git rev-parse "refs/remotes/origin/$BASE_REF")"', run)
        self.assertIn("BASE_REF: ${{ github.event.pull_request.base.ref }}", workflow)

    def test_base_must_be_a_full_sha(self):
        with self.assertRaises(ValueError):
            pr_changes("master", self.repo)


class RepositoryWorkingTree(unittest.TestCase):
    """`checks.py repository` on an uncommitted `git merge --no-commit` (#228).

    A -> P (branch: docs/x.md); A -> M (master: docs/m.md). The branch merges master
    without committing, so HEAD is still P; the check must judge the merge result.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)

        def git(*args: str) -> str:
            return PrRange.git(self.repo, *args)

        def commit(path: str, text: str) -> str:
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text, encoding="utf-8")
            git("add", path)
            git("commit", "-q", "-m", path)
            return git("rev-parse", "HEAD")

        git("init", "-q", "-b", "master")
        # The copy runs with its own ROOT, so it checks this repository.
        commit("tools/ci/checks.py", (ROOT / "tools/ci/checks.py").read_text("utf-8"))
        commit("README.md", "start\n")
        git("checkout", "-q", "-b", "pr")
        commit("docs/x.md", "<!-- owns: x -->\n# X\n")
        git("checkout", "-q", "master")
        # Unchanged against the base, yet its link into the branch's file is checked.
        self.master = commit("docs/m.md", "<!-- owns: m -->\n[x](x.md#x)\n")
        git("checkout", "-q", "pr")
        # Quiet: -q still prints "stopped before committing" to stderr.
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
            + ["merge", "-q", "--no-ff", "--no-commit", "master"],
            cwd=self.repo,
            capture_output=True,
            check=True,
        )
        self.git = git

    def run_check(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", "tools/ci/checks.py", "repository"]
            + ["--base", self.master],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def resolve(self, text: str) -> None:
        # README.md is the same on both sides; only the merge resolution touches it.
        (self.repo / "README.md").write_text(text, encoding="utf-8")
        self.git("add", "README.md")

    def edit(self, path: str, text: str) -> subprocess.CompletedProcess:
        (self.repo / path).write_text(text, encoding="utf-8")
        return self.run_check()

    def test_clean_merge_result_has_only_the_branch_change(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("passed for 1 changed paths", result.stdout)

    def test_whitespace_in_the_merge_result_fails(self):
        self.resolve("start \n")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("README.md:1: trailing whitespace", result.stdout)

    def test_file_only_the_merge_touched_is_read(self):
        self.resolve("start\n[gone](missing.md)\n")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("README.md: missing relative link missing.md", result.stderr)

    def test_a_renamed_heading_breaks_the_link_of_an_unchanged_file(self):
        result = self.edit("docs/x.md", "<!-- owns: x -->\n# Y\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("docs/m.md: no heading makes the anchor of x.md#x", result.stderr)

    def test_a_concept_owned_twice_fails(self):
        result = self.edit("docs/x.md", "<!-- owns: M -->\n# X\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "docs/x.md: concept 'M' already owned by docs/m.md", result.stderr
        )

    def test_a_doc_without_an_owns_line_fails(self):
        result = self.edit("docs/x.md", "# X\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("docs/x.md: the first line is not <!-- owns:", result.stderr)


class WorkflowTriggers(unittest.TestCase):
    """CI runs on PRs into and pushes to every long-lived branch (#288, #332).

    The integration branches come from close_task.sh, the one list of them.
    """

    def test_ci_runs_on_every_long_lived_branch(self):
        import yaml

        close_task = (ROOT / "tools/ops/close_task.sh").read_text(encoding="utf-8")
        (listed,) = re.findall(r"^integration_branches=\((.*)\)$", close_task, re.M)
        self.assertTrue(listed.split())
        long_lived = ["master", "release/**", *listed.split()]
        workflow = yaml.load(
            (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                self.assertEqual(workflow["on"][event]["branches"], long_lived)


class ExperimentJob(unittest.TestCase):
    """The backend-xdist experiment holds up neither a merge nor close_task.sh (#379).

    required does not need it. Its pytest step continues on error and stops before the
    job's time limit, so a hang is a step failure too, and its summary step continues on
    error: close_task.sh reads the run's conclusion and patrol.sh every check's, so a red
    or cancelled experiment would stop both.
    """

    def setUp(self):
        import yaml

        self.jobs = yaml.load(
            (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )["jobs"]
        self.job = self.jobs["backend-xdist"]
        self.pytest_steps = [
            s for s in self.job["steps"] if "-m pytest" in s.get("run", "")
        ]
        self.assertTrue(self.pytest_steps)

    def test_backend_xdist_cannot_turn_ci_red(self):
        self.assertNotIn("backend-xdist", self.jobs["required"]["needs"])
        self.assertNotIn("backend-xdist", json.dumps(self.jobs["required"]["steps"]))
        for step in self.pytest_steps:
            with self.subTest(step=step.get("name")):
                self.assertEqual(step.get("continue-on-error"), "true")

    def test_a_hung_pytest_stops_before_the_job_does(self):
        job_limit = int(self.job["timeout-minutes"])
        for step in self.pytest_steps:
            with self.subTest(step=step.get("name")):
                self.assertLess(int(step.get("timeout-minutes", job_limit)), job_limit)

    def test_the_summary_step_continues_on_error(self):
        (summary,) = [s for s in self.job["steps"] if s.get("name") == "Summary"]
        self.assertEqual(summary.get("if"), "always()")
        self.assertEqual(summary.get("continue-on-error"), "true")


if __name__ == "__main__":
    unittest.main()
