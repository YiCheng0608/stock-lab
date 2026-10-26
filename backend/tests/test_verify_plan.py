"""tools/verify/verify_plan.py, which pages the CI verify job checks (Issue #245).

The rules live in the 驗證範圍 tables of the features files; these tests run
them on made-up change sets and keep the route table in step with
backend/app/api.py (every route mapped to a page or excluded with a reason).

Frontend cases run on a small frontend tree written to tmp_path, not on the
repository's frontend: the backend job does not run for frontend changes.  The
repository's frontend tables are checked by verify_plan.py itself, which the CI
verify job runs on every change.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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
ALL = list(verify_plan.PAGES)
FE = verify_plan.FRONTEND  # the frontend source directory, relative to the repository

# A frontend tree shaped like the real one: App.tsx and main.tsx are the shell;
# the view modules are the files the features tables list.
TREE = {
    "main.tsx": "import App from './App'\nimport './styles.css'\n",
    "App.tsx": (
        "import { Card } from './components/ui'\n"
        "import { ThemeSuggestionsSection } from './themes/ThemeSuggestionViews'\n"
        "import { HotGroupsSection } from './themes/ThemeViews'\n"
        "import { StockBarsChart } from './stock/StockBarsChart'\n"
        "import { NewsCard } from './news/NewsViews'\n"
        "import { TodayHeader } from './today/TodayViews'\n"
    ),
    "styles.css": "body {}\n",
    "components/ui/index.ts": "export { Card } from './Card'\n",
    "components/ui/Card.tsx": "export const Card = 1\n",
    "themes/ThemeSuggestionViews.tsx": (
        "import { AiBadge } from '../news/NewsViews'\n"
        "import { Card } from '../components/ui'\n"
    ),
    "themes/ThemeViews.tsx": "import { readChartTheme } from '../stock/stockBars'\n",
    "themes/themeSuggestions.test.tsx": "import { X } from './ThemeSuggestionViews'\n",
    "stock/StockBarsChart.tsx": "import { bars } from './stockBars'\n",
    "stock/StockHeader.tsx": "import { quote } from './stockBars'\n",
    "stock/stockBars.ts": "export const bars = 1\n",
    "stock/StrategyBoardPanel.tsx": (
        "import { ScoreDetails } from '../candidates/CandidateViews'\n"
        "import { unmetText } from './strategyBoard'\n"
    ),
    "stock/strategyBoard.ts": "export const unmetText = 1\n",
    "news/NewsViews.tsx": "export const AiBadge = 1\n",
    "candidates/CandidateViews.tsx": "import { AiBadge } from '../news/NewsViews'\n",
    "today/TodayViews.tsx": "import { Card } from '../components/ui'\n",
    "actions/ActionViews.tsx": "import { actionKey } from './actionTiers'\n",
    "actions/actionTiers.ts": "export const actionKey = 1\n",
    "stock/stockTabs.ts": "export const STOCK_TABS = 1\n",
}


@pytest.fixture
def importers(tmp_path: Path) -> dict[str, set[str]]:
    for name, text in TREE.items():
        path = tmp_path / FE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return verify_plan.frontend_importers(tmp_path)


def plan(
    *paths: str, importers=None, api_source: str | None = API_SOURCE, api_lines=()
):
    return verify_plan.plan_for(
        list(paths), RULES, api_source, set(api_lines), importers or {}
    )


def route_lines(route: str, source: str = API_SOURCE) -> set[int]:
    """A line inside the function body of ``route`` (not its decorator)."""

    (statement,) = [s for s in verify_plan.api_statements(source) if s.route == route]
    return {statement.end}


# ---- AC-1: the page range of each kind of change ----


def test_single_frontend_page_verifies_only_that_page(importers):
    result = plan(FE + "themes/ThemeSuggestionViews.tsx", importers=importers)
    assert result.pages == ["themes"]


def test_frontend_file_shared_by_some_pages_verifies_those_pages(importers):
    result = plan(FE + "stock/StockBarsChart.tsx", importers=importers)
    assert result.pages == ["stocks", "actions"]
    # Not listed: the pages of the listed files importing it.
    result = plan(FE + "stock/stockBars.ts", importers=importers)
    assert result.pages == ["today", "themes", "stocks", "actions"]


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
    candidates = 1  # a local named like another route is not that route
    return candidates


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
    lines = [line_of("    return LIMIT")]
    assert plan("backend/app/api.py", api_source=SOURCE, api_lines=lines).pages == [
        "today"
    ]


def test_api_route_change_does_not_reach_a_local_of_the_same_name():
    lines = {line_of("    return helper()")}
    assert set(verify_plan.touched_routes(SOURCE, lines)) == {"GET /candidates"}


def test_api_router_change_reaches_every_route():
    touched = verify_plan.touched_routes(SOURCE, {line_of("router = APIRouter()")})
    assert set(touched) == {"GET /candidates", "GET /stocks", "GET /health"}


def test_api_import_change_reaches_the_routes_through_the_router():
    result = plan("backend/app/api.py", api_source=SOURCE, api_lines=[2])
    assert result.pages == ["today", "stocks"]


def test_api_change_outside_routes_is_not_verified():
    # The module docstring and the blank line after the import.
    result = plan("backend/app/api.py", api_source=SOURCE, api_lines=[1, 3])
    assert result.pages == []


def test_api_deletion_marks_the_lines_around_it():
    diff = "@@ -10,3 +9,0 @@\n-a\n-b\n-c\n@@ -20 +18,2 @@\n+x\n+y\n"
    assert verify_plan.changed_lines(diff) == {9, 10, 18, 19}


def test_api_deleted_verifies_every_page():
    assert plan("backend/app/api.py", api_source=None).pages == ALL


def test_style_and_shared_component_verify_every_page(importers):
    for name in (
        "styles.css",
        "components/ui/Card.tsx",
        "components/ui/index.ts",
        "App.tsx",
        "main.tsx",
    ):
        assert plan(FE + name, importers=importers).pages == ALL, name


def test_frontend_file_nothing_imports_verifies_every_page(importers):
    assert plan(FE + "styles/tokens.css", importers=importers).pages == ALL


def test_worker_schema_and_unlisted_paths_verify_every_page():
    for path in (
        "backend/worker/cli.py",
        "backend/app/scoring.py",
        "backend/alembic/versions/0099_new.py",
        "backend/requirements.txt",
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


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_nightly_and_manual_runs_verify_every_page(event, tmp_path):
    # #251: master's nightly run checks all five pages whatever its last push changed.
    assert verify_plan.plan_for_event(event).pages == ALL
    output = tmp_path / "output"
    assert (
        verify_plan.main(
            ["--base", "0" * 40, "--event", event, "--output", str(output)]
        )
        == 0
    )
    assert output.read_text(encoding="utf-8") == f"pages={','.join(ALL)}\n"


def test_pull_requests_and_pushes_follow_the_diff():
    for event in ("pull_request", "push", ""):
        assert verify_plan.plan_for_event(event) is None


def test_docs_and_tests_only_are_not_verified(importers):
    result = plan(
        "docs/GITHUB_WORKFLOW.md",
        "AGENTS.md",
        "backend/tests/test_api.py",
        FE + "themes/themeSuggestions.test.tsx",
        FE + "news/news.fixtures.ts",
        "tools/ci/checks.py",
        ".github/pull_request_template.md",
        importers=importers,
    )
    assert result.pages == []
    assert {scope for _, scope, _ in result.files} == {"不驗"}


def test_plan_names_a_reason_for_each_page(importers):
    result = plan(
        FE + "themes/ThemeSuggestionViews.tsx",
        "backend/app/api.py",
        importers=importers,
        api_lines=route_lines("GET /candidates"),
    )
    assert result.pages == ["today", "themes"]
    text = verify_plan.markdown(result, "- head")
    assert "| 今日 `/` | `backend/app/api.py` `GET /candidates` |" in text
    assert "| 族群 `/themes` | `" + FE + "themes/ThemeSuggestionViews.tsx` |" in text
    assert "- 範圍：不驗" in verify_plan.markdown(plan("docs/a.md"), "- head")


def test_glob_patterns():
    def match(pattern: str, path: str) -> bool:
        return bool(verify_plan.glob_regex(pattern).match(path))

    assert match("**/*.md", "AGENTS.md") and match("**/*.md", "docs/a/b.md")
    assert match("src/**/*.test.ts", "src/a.test.ts")
    assert match("src/**/*.test.ts", "src/x/y/a.test.ts")
    assert not match("src/*.ts", "src/x/a.ts")
    assert not match("docs/**", "docsx/a.md")


# ---- the tables stay in step with the code ----


def test_every_api_route_is_on_a_page_or_excluded():
    problems = verify_plan.route_problems(API_SOURCE, RULES)
    assert problems == [], "\n".join(problems)


def test_route_problems_names_an_unmapped_route():
    source = (
        API_SOURCE + '\n\n@router.get("/new-thing")\ndef new_thing():\n    return 1\n'
    )
    assert (
        "route `GET /new-thing` 沒有列在任何 features 檔的驗證範圍，"
        "也不在 README 的「不屬於五頁的 route」"
    ) in verify_plan.route_problems(source, RULES)


def test_api_routes_match_the_router():
    """The decorators verify_plan reads are every route FastAPI serves."""

    from app.api import API_PREFIX, router

    served = {
        f"{method} {route.path.removeprefix(API_PREFIX)}"
        for route in router.routes
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert served == set(verify_plan.api_routes(API_SOURCE))


def test_frontend_tables_match_the_tree(importers, tmp_path):
    assert verify_plan.frontend_problems(RULES, importers, tmp_path) == []


def test_frontend_problems_name_a_missing_page_and_a_missing_file(importers, tmp_path):
    rules = verify_plan.load_rules()
    rules.frontend[FE + "news/NewsViews.tsx"] = {"news"}
    rules.frontend[FE + "gone.tsx"] = {"news"}
    problems = verify_plan.frontend_problems(rules, importers, tmp_path)
    assert f"驗證範圍列了前端檔 `{FE}gone.tsx`，檔案不存在" in problems
    assert (
        f"前端檔 `{FE}news/NewsViews.tsx` 被 `{FE}themes/ThemeSuggestionViews.tsx` "
        "import，驗證範圍少了 themes"
    ) in problems
