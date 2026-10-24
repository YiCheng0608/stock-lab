"""tools/verify/verify_plan.py, which pages the CI verify job checks (Issue #245).

The rules live in the 驗證範圍 tables of the features files; these tests run
them on made-up change sets and keep the tables in step with backend/app/api.py
(every route mapped to a page or excluded with a reason) and frontend/src.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = (ROOT / "backend" / "app" / "api.py").read_text(encoding="utf-8")


def _load():
    spec = importlib.util.spec_from_file_location(
        "verify_plan", ROOT / "tools" / "verify" / "verify_plan.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_plan"] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


verify_plan = _load()
RULES = verify_plan.load_rules()
IMPORTERS = verify_plan.frontend_importers()
ALL = list(verify_plan.PAGES)


def plan(*paths: str, api_source: str = API_SOURCE, api_lines=()):
    return verify_plan.plan_for(
        list(paths), RULES, api_source, set(api_lines), IMPORTERS
    )


def route_lines(route: str, source: str = API_SOURCE) -> set[int]:
    """A line inside the function body of ``route`` (not its decorator)."""

    (statement,) = [s for s in verify_plan.api_statements(source) if s.route == route]
    return {statement.end}


# ---- AC-1: the page range of each kind of change ----


def test_single_frontend_page_verifies_only_that_page():
    result = plan("frontend/src/themes/ThemeSuggestionViews.tsx")
    assert result.pages == ["themes"]


def test_frontend_file_shared_by_some_pages_verifies_those_pages():
    assert plan("frontend/src/stock/StockBarsChart.tsx").pages == ["stocks", "actions"]
    assert plan("frontend/src/themes/ThemeViews.tsx").pages == ["today", "themes"]


def test_api_endpoint_verifies_the_pages_that_use_it():
    lines = route_lines("GET /candidates")
    assert plan("backend/app/api.py", api_lines=lines).pages == ["today"]
    lines = route_lines("GET /theme-suggestions")
    assert plan("backend/app/api.py", api_lines=lines).pages == ["themes"]
    lines = route_lines("GET /stocks/{exchange}/{symbol}/bars")
    assert plan("backend/app/api.py", api_lines=lines).pages == ["stocks", "actions"]


def test_api_route_not_on_a_page_is_not_verified():
    result = plan("backend/app/api.py", api_lines=route_lines("GET /coverage"))
    assert result.pages == []
    assert "不屬於五頁" in result.files[0][2]


SOURCE = '''"""A small api.py."""
from fastapi import APIRouter

router = APIRouter()
LIMIT = 10


def helper():
    return LIMIT


@router.get("/candidates")
def candidates():
    return helper()


@router.get("/stocks")
def stocks():
    return 1


@router.get("/health")
def health():
    return 1
'''


def line_of(text: str, source: str = SOURCE) -> int:
    return source.splitlines().index(text) + 1


def test_api_helper_change_reaches_the_routes_that_use_it():
    assert verify_plan.touched_routes(SOURCE, {line_of("LIMIT = 10")}) == {
        "GET /candidates": {"LIMIT"}
    }
    result = plan(
        "backend/app/api.py", api_source=SOURCE, api_lines=[line_of("    return LIMIT")]
    )
    assert result.pages == ["today"]


def test_api_router_change_reaches_every_route():
    touched = verify_plan.touched_routes(SOURCE, {line_of("router = APIRouter()")})
    assert set(touched) == {"GET /candidates", "GET /stocks", "GET /health"}


def test_api_change_outside_routes_is_not_verified():
    # The module docstring and the blank line after the import.
    result = plan("backend/app/api.py", api_source=SOURCE, api_lines=[1, 3])
    assert result.pages == []


def test_api_import_change_reaches_the_routes_through_the_router():
    result = plan("backend/app/api.py", api_source=SOURCE, api_lines=[2])
    assert result.pages == ["today", "stocks"]


def test_api_deletion_marks_the_lines_around_it():
    diff = "@@ -10,3 +9,0 @@\n-a\n-b\n-c\n@@ -20 +18,2 @@\n+x\n+y\n"
    assert verify_plan.changed_lines(diff) == {9, 10, 18, 19}


def test_style_and_shared_component_verify_every_page():
    for path in (
        "frontend/src/styles.css",
        "frontend/src/styles/tokens.css",
        "frontend/src/components/ui/Badge.tsx",
        "frontend/src/App.tsx",
        "frontend/src/types.ts",
    ):
        assert plan(path).pages == ALL, path


def test_worker_schema_and_unlisted_paths_verify_every_page():
    for path in (
        "backend/worker/cli.py",
        "backend/app/scoring.py",
        "backend/alembic/versions/0099_new.py",
        "frontend/package.json",
        "somewhere/new.txt",
    ):
        assert plan(path).pages == ALL, path


def test_verify_tools_verify_every_page():
    for path in (
        "tools/verify/page_checks.py",
        "tools/verify/verify_plan.py",
        ".claude/skills/verify-stock-lab/features/today.md",
        ".claude/skills/verify-stock-lab/db_facts.py",
        "tools/ops/screenshot.cjs",
        ".github/workflows/ci.yml",
    ):
        assert plan(path).pages == ALL, path


def test_docs_and_tests_only_are_not_verified():
    result = plan(
        "docs/GITHUB_WORKFLOW.md",
        "AGENTS.md",
        "backend/tests/test_api.py",
        "frontend/src/news/news.test.tsx",
        "frontend/src/news/news.fixtures.ts",
        "tools/ci/checks.py",
        ".github/pull_request_template.md",
    )
    assert result.pages == []
    assert {scope for _, scope, _ in result.files} == {"不驗"}


def test_plan_names_a_reason_for_each_page():
    result = plan(
        "frontend/src/themes/ThemeSuggestionViews.tsx",
        "backend/app/api.py",
        api_lines=route_lines("GET /candidates"),
    )
    assert result.pages == ["today", "themes"]
    text = verify_plan.markdown(result, "- head")
    assert "GET /candidates" in text and "ThemeSuggestionViews.tsx" in text
    assert "| 今日 `/` |" in text and "| 族群 `/themes` |" in text


def test_glob_patterns():
    match = lambda pattern, path: bool(verify_plan.glob_regex(pattern).match(path))  # noqa: E731
    assert match("**/*.md", "AGENTS.md") and match("**/*.md", "docs/a/b.md")
    assert match("frontend/src/**/*.test.ts", "frontend/src/a.test.ts")
    assert match("frontend/src/**/*.test.ts", "frontend/src/x/y/a.test.ts")
    assert not match("frontend/src/*.ts", "frontend/src/x/a.ts")
    assert not match("docs/**", "docsx/a.md")


# ---- the tables stay in step with the code ----


def test_every_api_route_is_on_a_page_or_excluded():
    problems = verify_plan.route_problems(API_SOURCE, RULES)
    assert problems == [], "\n".join(problems)


def test_route_problems_names_an_unmapped_route():
    source = (
        API_SOURCE + '\n\n@router.get("/new-thing")\ndef new_thing():\n    return 1\n'
    )
    assert verify_plan.route_problems(source, RULES) == [
        "route `GET /new-thing` 沒有列在任何 features 檔的驗證範圍，也不在 README 的「不屬於五頁的 route」"
    ]


def test_api_routes_match_the_router():
    """The decorators verify_plan reads are every route FastAPI serves."""

    from app.api import API_PREFIX, router

    served = {
        f"{method} {route.path.removeprefix(API_PREFIX)}"
        for route in router.routes
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert served == set(verify_plan.api_routes(API_SOURCE))


def test_listed_frontend_files_exist():
    missing = [path for path in RULES.frontend if not (ROOT / path).is_file()]
    assert missing == []


def test_listed_frontend_files_cover_the_pages_of_their_importers():
    """A listed file's pages include every page of a file that imports it."""

    problems = []
    for path, pages in RULES.frontend.items():
        for user in sorted(IMPORTERS.get(path, ())):
            kind = verify_plan.path_rule(RULES, user)[1]
            if user in verify_plan.SHELL or kind == verify_plan.NONE:
                continue
            found, _ = verify_plan.frontend_pages(user, RULES, IMPORTERS)
            missing = set(ALL if found is None else found) - pages
            if missing:
                problems.append(f"{path} 被 {user} import，少了 {sorted(missing)}")
    assert problems == []
