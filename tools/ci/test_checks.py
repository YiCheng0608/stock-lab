"""Test routing without running product services or writing fixtures."""
import re
import unittest

from checks import ROOT, change_flags, markdown_errors


class RoutingTests(unittest.TestCase):
    def test_docs_only_skips_product_jobs(self):
        self.assertEqual(change_flags(["docs/ROADMAP.md", "README.md"]), {"python": False, "frontend": False})

    def test_frontend_change(self):
        self.assertEqual(change_flags(["frontend/scripts/ci-test.cjs"]), {"python": False, "frontend": True})
        self.assertEqual(change_flags(["frontend/src/App.tsx"]), {"python": False, "frontend": True})

    def test_backend_also_checks_frontend_contracts(self):
        self.assertEqual(change_flags(["backend/app/example.py"]), {"python": True, "frontend": True})

    def test_shared_runner_and_workflow_require_both(self):
        for name in ["tools/ci/checks.py", ".github/workflows/ci.yml", "tools/deleted-runner.py"]:
            self.assertTrue(all(change_flags([name]).values()))

    def test_product_markdown_skips_product_jobs(self):
        for name in ["frontend/README.md", "backend/README.md", "tools/README.md", "frontend/NOTES.MD"]:
            self.assertEqual(change_flags([name]), {"python": False, "frontend": False}, name)

    def test_markdown_does_not_hide_product_code(self):
        self.assertEqual(change_flags(["frontend/README.md", "frontend/scripts/ci-test.cjs"]), {"python": False, "frontend": True})
        self.assertEqual(change_flags(["frontend/README.md", "frontend/src/App.tsx"]), {"python": False, "frontend": True})
        self.assertEqual(change_flags(["backend/README.md", "backend/app/example.py"]), {"python": True, "frontend": True})

    def test_shared_markdown_still_requires_both(self):
        for name in ["tools/ci/README.md", ".github/workflows/README.md"]:
            self.assertEqual(change_flags([name]), {"python": True, "frontend": True}, name)

    def test_dependency_constraints_require_python(self):
        self.assertTrue(change_flags(["backend/validation-requirements.lock.txt"])["python"])

    def test_unread_frontend_and_docs_paths_stay_out_of_python(self):
        for name in ["frontend/src/App.tsx", "frontend/src/api.ts", "frontend/package.json", "frontend/pnpm-lock.yaml",
                     "frontend/vite.config.ts", "frontend/scripts/ci-test.cjs", "frontend/src/NOTES.md", "docs/ROADMAP.md",
                     "docs/DATA_SOURCES.md", "docs/INDUSTRY_CLASSIFICATION.md"]:
            self.assertFalse(change_flags([name])["python"], name)

    def test_frontend_files_literally_read_by_backend_tests_require_python(self):
        # Principle: whatever backend/tests reads from the working tree must run the backend job.
        # node_modules is installed from package.json and pnpm-lock.yaml, which are routed above.
        read = set()
        for path in sorted((ROOT / "backend/tests").glob("*.py")):
            read.update(re.findall(r"frontend/(?!node_modules)[\w./-]+", path.read_text(encoding="utf-8")))
        for name in sorted(read):
            self.assertTrue(change_flags([name])["python"], name)

    def test_links(self):
        self.assertEqual(markdown_errors("README.md", "[ok](docs/ROADMAP.md) [web](https://example.com) [anchor](#x)"), [])
        self.assertEqual(len(markdown_errors("README.md", "[bad](nonexistent-ci-link-target.md)")), 1)

    def test_missing_links_with_titles(self):
        for title in ['"title"', "'title'", '(title)']:
            self.assertEqual(len(markdown_errors("README.md", f"[bad](nonexistent-ci-link-target.md {title})")), 1)

    def test_reference_links_and_footnotes(self):
        self.assertEqual(len(markdown_errors("README.md", "[bad][missing]\n\n[missing]: nonexistent-ci-link-target.md 'title'")), 1)
        self.assertEqual(markdown_errors("README.md", "[^note]: This is prose, not a link."), [])

    def test_fenced_examples_are_not_links(self):
        self.assertEqual(markdown_errors("README.md", "```md\n[example](nonexistent-ci-link-target.md)\n```"), [])


if __name__ == "__main__":
    unittest.main()
