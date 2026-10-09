"""Test routing without running product services or writing fixtures."""
import unittest

from checks import change_flags, markdown_errors


class RoutingTests(unittest.TestCase):
    def test_docs_only_skips_product_jobs(self):
        self.assertEqual(change_flags(["docs/ROADMAP.md", "README.md"]), {"python": False, "frontend": False})

    def test_frontend_change(self):
        self.assertEqual(change_flags(["frontend/src/App.tsx"]), {"python": False, "frontend": True})

    def test_backend_also_checks_frontend_contracts(self):
        self.assertEqual(change_flags(["backend/app/example.py"]), {"python": True, "frontend": True})

    def test_shared_runner_and_workflow_require_both(self):
        for name in ["tools/ci/checks.py", ".github/workflows/ci.yml", "tools/deleted-runner.py"]:
            self.assertTrue(all(change_flags([name]).values()))

    def test_dependency_constraints_require_python(self):
        self.assertTrue(change_flags(["docs/development-baseline/validation-requirements.lock.txt"])["python"])

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
