"""Which of the five main pages a change needs verified (Issue #245).

    python tools/verify/verify_plan.py --base <full SHA> [--output <file>]

Diffs the merge-base of ``--base`` and HEAD with HEAD and decides, per changed
file, which pages the CI ``verify`` job checks.  The rules are not in this file:
``.claude/skills/verify-stock-lab/features/README.md`` (驗證範圍) maps path
patterns to 全套／不驗／前端檔／API route, and each ``features/<page>.md``
(驗證範圍) lists the frontend files and the API routes of that page.

- A frontend file listed by pages goes to those pages; an unlisted one goes to
  the pages of every file that imports it, and to all pages when ``App.tsx`` or
  ``main.tsx`` imports it or nothing does (shared shell, styles and components).
- A change in ``backend/app/api.py`` goes to the pages of the routes it reaches:
  the route functions whose lines changed, or that use (directly or through
  other module-level names) a function, constant or import whose lines changed.

``--event schedule`` and ``--event workflow_dispatch`` (the nightly and manual
runs of master, Issue #251) verify all five pages whatever changed.

Prints the plan as Markdown and writes ``pages=<comma separated pages>`` (empty:
nothing to verify) to ``--output`` (``$GITHUB_OUTPUT`` in CI).  Exit 2 without a
plan when the tables and the code disagree: a route of api.py on no page and not
excluded, a row naming no route, a listed frontend file that is gone, or one
whose pages miss a page of a file importing it.  Standard library only, so CI
runs it before installing anything.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / ".claude" / "skills" / "verify-stock-lab" / "features"
API = "backend/app/api.py"
FRONTEND = "frontend/src/"
PAGES = ("today", "news", "themes", "stocks", "actions")
NAMES = {
    "today": "今日 `/`",
    "news": "新聞 `/news`",
    "themes": "族群 `/themes`",
    "stocks": "個股 `/stocks`",
    "actions": "行動 `/actions`",
}
# Frontend files every page goes through: a file only they import affects every page.
SHELL = ("frontend/src/App.tsx", "frontend/src/main.tsx")
ROUTE_METHODS = ("get", "post", "put", "patch", "delete")

ALL, NONE, FRONTEND_KIND, ROUTE_KIND = "全套", "不驗", "前端檔", "API route"
KINDS = (ALL, NONE, FRONTEND_KIND, ROUTE_KIND)
# GitHub events that verify every page: master's nightly run and a manual run.
FULL_EVENTS = {"schedule": "每晚定期全套", "workflow_dispatch": "手動觸發全套"}


# ---- features tables ----

ROW = re.compile(r"^\| `([^`]+)` \| ([^|]+?) \| ([^|]*?) \|$", re.M)
EXCLUDED_ROW = re.compile(r"^\| `([^`]+)` \| ([^|]*?) \|$", re.M)
PAGE_ROW = re.compile(r"^\| (前端檔|API route) \| `([^`]+)` \|", re.M)


def section(text: str, title: str) -> str:
    """The body of ``## <title>`` up to the next ``## `` heading."""

    parts = text.split(f"\n## {title}\n", 1)
    if len(parts) != 2:
        raise ValueError(f"no ## {title} section")
    return parts[1].split("\n## ", 1)[0]


@dataclass
class Rules:
    """The 驗證範圍 tables of features/README.md and features/<page>.md."""

    paths: list[tuple[str, str, str]]  # (pattern, kind, reason), first match wins
    excluded_routes: dict[str, str]  # route -> why no page uses it
    frontend: dict[str, set[str]] = field(default_factory=dict)  # file -> pages
    routes: dict[str, set[str]] = field(default_factory=dict)  # route -> pages


def load_rules(features: Path = FEATURES) -> Rules:
    readme = section((features / "README.md").read_text(encoding="utf-8"), "驗證範圍")
    paths_part, _, routes_part = readme.partition("\n### 不屬於五頁的 route\n")
    paths = [(p, k.strip(), r.strip()) for p, k, r in ROW.findall(paths_part)]
    bad = [
        f"{pattern} {kind}"
        for pattern, kind, _ in paths
        if kind not in KINDS or (kind == ROUTE_KIND) != (pattern == API)
    ]
    if bad or not paths:
        raise ValueError(
            f"README 驗證範圍: {bad}; kinds are {KINDS}, {ROUTE_KIND} only {API}"
        )
    rules = Rules(paths, {p: r.strip() for p, r in EXCLUDED_ROW.findall(routes_part)})
    for page in PAGES:
        text = (features / f"{page}.md").read_text(encoding="utf-8")
        for kind, target in PAGE_ROW.findall(section(text, "驗證範圍")):
            table = rules.frontend if kind == FRONTEND_KIND else rules.routes
            table.setdefault(target, set()).add(page)
    return rules


def glob_regex(pattern: str) -> re.Pattern[str]:
    """``**/`` any directories, ``**`` anything, ``*`` and ``?`` within one path segment."""

    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def path_rule(rules: Rules, path: str) -> tuple[str, str, str]:
    """(pattern, kind, reason) of the first README row matching ``path``."""

    for pattern, kind, reason in rules.paths:
        if glob_regex(pattern).match(path):
            return pattern, kind, reason
    return "（未列）", ALL, "README 沒列到的路徑一律全套"


# ---- frontend imports ----

IMPORT = re.compile(r"""(?:\bfrom|\bimport)\s*\(?\s*['"](\.[^'"]+)['"]""")
SOURCE_SUFFIXES = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")


def frontend_importers(root: Path = ROOT) -> dict[str, set[str]]:
    """Repo path of a frontend/src file -> the frontend/src files that import it."""

    src = root / FRONTEND
    importers: dict[str, set[str]] = {}
    for file in sorted(src.rglob("*")):
        if file.suffix not in (".ts", ".tsx") or not file.is_file():
            continue
        name = file.relative_to(root).as_posix()
        for spec in IMPORT.findall(file.read_text(encoding="utf-8")):
            base = (file.parent / spec).resolve()
            for suffix in SOURCE_SUFFIXES:
                target = Path(str(base) + suffix)
                if target.is_file():
                    key = target.relative_to(root.resolve()).as_posix()
                    importers.setdefault(key, set()).add(name)
                    break
    return importers


def frontend_pages(
    path: str,
    rules: Rules,
    importers: dict[str, set[str]],
    seen: frozenset = frozenset(),
) -> tuple[set[str] | None, str]:
    """(pages, reason) for a frontend/src file; pages None means all of them."""

    if path in rules.frontend:
        return set(rules.frontend[path]), f"features 列 `{path}`"
    # Tests and fixtures import modules too, but never reach a page.
    users = {
        user
        for user in importers.get(path, set()) - seen
        if path_rule(rules, user)[1] != NONE
    }
    if path in SHELL or not users:
        why = "頁面外框" if path in SHELL else "沒有被其他檔 import（樣式或入口）"
        return None, f"`{path}` {why}，影響每一頁"
    pages: set[str] = set()
    for user in sorted(users):
        if user in SHELL:
            return None, f"`{path}` 由 `{user}` 直接 import，可能用在任何一頁"
        found, reason = frontend_pages(user, rules, importers, seen | {path})
        if found is None:
            return None, f"`{path}` 經 {reason}"
        pages |= found
    return pages, "import 它的 " + "、".join(f"`{u}`" for u in sorted(users))


# ---- api.py routes ----


def _route_of(node: ast.AST) -> str | None:
    """``GET /news`` for a function decorated ``@router.get("/news")``."""

    for decorator in getattr(node, "decorator_list", []):
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in ROUTE_METHODS
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
        ):
            return f"{decorator.func.attr.upper()} {decorator.args[0].value}"
    return None


@dataclass
class Statement:
    start: int
    end: int
    defines: set[str]
    uses: set[str]
    route: str | None


def _defines(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    targets: list[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}


def _uses(node: ast.stmt) -> set[str]:
    """Names a statement reads; a function's own locals and parameters are not module names."""

    loads = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return loads
    local = {
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
    } | {
        a.arg
        for n in ast.walk(node)
        if isinstance(n, ast.arguments)
        for a in (
            n.posonlyargs
            + n.args
            + n.kwonlyargs
            + [x for x in (n.vararg, n.kwarg) if x]
        )
    }
    declared = {
        name for n in ast.walk(node) if isinstance(n, ast.Global) for name in n.names
    }
    # Decorators and defaults run at module level, so their names always count.
    outer = {
        n.id
        for part in node.decorator_list + node.args.defaults + node.args.kw_defaults
        if part is not None
        for n in ast.walk(part)
        if isinstance(n, ast.Name)
    }
    return (loads - (local - declared)) | outer


def api_statements(source: str) -> list[Statement]:
    """Module-level statements of api.py with their lines (decorators included)."""

    statements = []
    for node in ast.parse(source).body:
        start = min(
            [node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]
        )
        uses = _uses(node)
        statements.append(
            Statement(start, node.end_lineno, _defines(node), uses, _route_of(node))
        )
    return statements


def api_routes(source: str) -> list[str]:
    return [s.route for s in api_statements(source) if s.route]


def route_problems(source: str, rules: Rules) -> list[str]:
    """Routes of api.py on no page and not excluded, and table rows naming no route."""

    routes = api_routes(source)
    problems = [
        f"route `{route}` 沒有列在任何 features 檔的驗證範圍，也不在 README 的「不屬於五頁的 route」"
        for route in routes
        if route not in rules.routes and route not in rules.excluded_routes
    ]
    problems += [
        f"route `{route}` 同時列在 features 檔與 README 的「不屬於五頁的 route」"
        for route in rules.routes
        if route in rules.excluded_routes
    ]
    problems += [
        f"驗證範圍列了 `{route}`，api.py 沒有這個 route"
        for route in [*rules.routes, *rules.excluded_routes]
        if route not in routes
    ]
    return problems


def frontend_problems(
    rules: Rules, importers: dict[str, set[str]], root: Path = ROOT
) -> list[str]:
    """Listed frontend files that are gone, or whose pages miss a page of a file importing them."""

    problems = [
        f"驗證範圍列了前端檔 `{path}`，檔案不存在"
        for path in rules.frontend
        if not (root / path).is_file()
    ]
    for path, pages in sorted(rules.frontend.items()):
        for user in sorted(importers.get(path, ())):
            if user in SHELL or path_rule(rules, user)[1] == NONE:
                continue
            found, _ = frontend_pages(user, rules, importers)
            wanted = set(PAGES) if found is None else found
            missing = [p for p in PAGES if p in wanted and p not in pages]
            if missing:
                problems.append(
                    f"前端檔 `{path}` 被 `{user}` import，驗證範圍少了 {'、'.join(missing)}"
                )
    return problems


def touched_routes(source: str, lines: set[int]) -> dict[str, set[str]]:
    """Route -> the changed module-level names it reaches (its own name when it changed)."""

    statements = api_statements(source)
    changed = {
        name
        for s in statements
        if any(s.start <= line <= s.end for line in lines)
        for name in s.defines
    }
    uses: dict[str, set[str]] = {}
    for s in statements:
        for name in s.defines:
            uses.setdefault(name, set()).update(s.uses)
    result = {}
    for s in statements:
        if not s.route:
            continue
        reached, todo = set(), list(s.defines)
        while todo:
            name = todo.pop()
            if name not in reached:
                reached.add(name)
                todo.extend(uses.get(name, ()))
        hits = reached & changed
        if hits:
            result[s.route] = hits
    return result


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)


def changed_lines(diff: str) -> set[int]:
    """New-file line numbers of a ``git diff -U0``; a deletion marks the lines around it."""

    lines: set[int] = set()
    for start, count in HUNK.findall(diff):
        first, n = int(start), 1 if count == "" else int(count)
        lines |= set(range(first, first + n)) if n else {first, first + 1}
    return lines


# ---- the plan ----


@dataclass
class Plan:
    # (path, scope, reason) per decision; page -> the files (and routes) that brought it in
    files: list[tuple[str, str, str]] = field(default_factory=list)
    reasons: dict[str, list[str]] = field(default_factory=dict)

    @property
    def pages(self) -> list[str]:
        return [page for page in PAGES if page in self.reasons]

    def add(
        self, path: str, pages: set[str] | None, reason: str, via: str = ""
    ) -> None:
        targets = PAGES if pages is None else [p for p in PAGES if p in pages]
        scope = (
            "全部五頁" if pages is None else "、".join(targets) if targets else "不驗"
        )
        self.files.append((path, scope, reason))
        cause = f"`{path}` {via}".strip()
        for page in targets:
            if cause not in self.reasons.setdefault(page, []):
                self.reasons[page].append(cause)


def plan_for(
    paths: list[str],
    rules: Rules,
    api_source: str | None = None,
    api_lines: set[int] = frozenset(),
    importers: dict[str, set[str]] | None = None,
) -> Plan:
    """The pages to verify for ``paths`` changed (``api_lines`` of api.py, new numbering)."""

    plan = Plan()
    for path in paths:
        pattern, kind, reason = path_rule(rules, path)
        if kind == ALL:
            plan.add(path, None, f"{reason}（`{pattern}`）")
        elif kind == NONE:
            plan.add(path, set(), f"{reason}（`{pattern}`）")
        elif kind == FRONTEND_KIND:
            found, why = frontend_pages(path, rules, importers or {})
            plan.add(path, found, why)
        elif api_source is None:
            plan.add(path, None, "檔案已刪除")
        else:
            routes = touched_routes(api_source, set(api_lines))
            if not routes:
                plan.add(path, set(), "改動沒有碰到任何 route 用到的程式")
                continue
            for route, names in sorted(routes.items()):
                if route in rules.excluded_routes:
                    why = f"不屬於五頁：{rules.excluded_routes[route]}"
                    plan.add(path, set(), f"route `{route}` {why}")
                elif route in rules.routes:
                    via = "、".join(sorted(names))
                    plan.add(
                        path,
                        rules.routes[route],
                        f"route `{route}`（改到 {via}）",
                        f"`{route}`",
                    )
                else:
                    plan.add(
                        path, None, f"route `{route}` 沒有對到任何頁", f"`{route}`"
                    )
    return plan


def plan_for_event(event: str) -> Plan | None:
    """All five pages for a nightly or manual run; None for any other event."""

    if event not in FULL_EVENTS:
        return None
    plan = Plan()
    plan.add(f"（{event}）", None, FULL_EVENTS[event])
    return plan


def markdown(plan: Plan, head: str) -> str:
    pages = plan.pages
    scope = (
        "不驗（job 以 success 結束）"
        if not pages
        else "全部五頁"
        if len(pages) == len(PAGES)
        else "、".join(NAMES[p] for p in pages)
    )
    lines = ["## verify plan", "", head, f"- 範圍：{scope}", ""]
    if pages:
        lines += ["| 頁 | 因為改到（理由見下表） |", "| --- | --- |"]
        for page in pages:
            causes = plan.reasons[page]
            shown = "、".join(causes[:5]) + (
                f" 等 {len(causes)} 項" if len(causes) > 5 else ""
            )
            lines.append(f"| {NAMES[page]} | {shown.replace('|', '/')} |")
        lines.append("")
    if plan.files:
        lines += ["| 檔案 | 範圍 | 理由 |", "| --- | --- | --- |"]
        lines += [
            f"| `{path}` | {pages} | {reason.replace('|', '/')} |"
            for path, pages, reason in plan.files
        ]
    return "\n".join(lines) + "\n"


# ---- git ----


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd).decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="full SHA of the base branch tip")
    parser.add_argument("--output", type=Path, help="append pages=<csv> to this file")
    parser.add_argument(
        "--event",
        default="",
        help="GitHub event; schedule and workflow_dispatch: all pages",
    )
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.base):
        parser.error("--base must be a full Git SHA")

    rules = load_rules()
    importers = frontend_importers()
    problems = route_problems(
        (ROOT / API).read_text(encoding="utf-8"), rules
    ) + frontend_problems(rules, importers)
    if problems:
        print("驗證範圍與程式不一致：\n" + "\n".join(problems), file=sys.stderr)
        return 2
    head = git("rev-parse", "HEAD").strip()
    plan = plan_for_event(args.event)
    if plan is not None:
        print(markdown(plan, f"- 觸發 `{args.event}`，HEAD `{head[:7]}`"))
    else:
        plan = diff_plan(args.base, head, rules, importers)
    if args.output:
        with args.output.open("a", encoding="utf-8") as out:
            out.write(f"pages={','.join(plan.pages)}\n")
    return 0


def diff_plan(
    base: str, head: str, rules: Rules, importers: dict[str, set[str]]
) -> Plan:
    """The plan for the files changed from the merge-base of ``base`` to HEAD, printed."""

    if base == "0" * 40:
        fork, paths = None, sorted(git("ls-files").splitlines())
    else:
        fork = git("merge-base", base, "HEAD").strip()
        paths = git("diff", "--name-only", "--no-renames", fork, "HEAD").splitlines()
    api_source, api_lines = None, set()
    if API in paths and (ROOT / API).is_file():
        api_source = (ROOT / API).read_text(encoding="utf-8")
        api_lines = (
            set(range(1, api_source.count("\n") + 2))
            if fork is None
            else changed_lines(
                git("diff", "-U0", "--no-renames", fork, "HEAD", "--", API)
            )
        )
    plan = plan_for(paths, rules, api_source, api_lines, importers)
    print(
        markdown(
            plan,
            f"- 比對 `{(fork or 'empty tree')[:7]}`（merge-base）→ HEAD `{head[:7]}`，"
            f"改動 {len(paths)} 檔",
        )
    )
    return plan


if __name__ == "__main__":
    sys.exit(main())
