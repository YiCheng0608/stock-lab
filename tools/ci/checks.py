"""Small, offline CI checks; do not import application configuration or data."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tokenize
import unicodedata
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=cwd)


def changed_paths(base: str, cwd: Path = ROOT, worktree: bool = False) -> list[str]:
    """Paths changed from base to HEAD, or to the working tree when worktree is set."""
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("base must be a full Git SHA")
    if base == "0" * 40:
        result = git("ls-files", "-z", cwd=cwd)
    else:
        tip = () if worktree else ("HEAD",)
        result = git("diff", "--name-only", "--no-renames", "-z", base, *tip, cwd=cwd)
    return [name.decode("utf-8") for name in result.split(b"\0") if name]


# Working-tree paths outside backend/ and tools/ that the backend job reads; a change must run it.
# Keep in step with backend/tests. test_database_readiness reads the Alembic head stated in
# docs/OPERATIONS.md; test_condition_copy_source reads the frontend condition table (#279);
# test_event_monitor reads 統籌 session and 無人值守運作 of docs/GITHUB_WORKFLOW.md (#316).
BACKEND_READ_DIRS: tuple[str, ...] = ()
BACKEND_READ_FILES: frozenset[str] = frozenset(
    {
        "docs/GITHUB_WORKFLOW.md",
        "docs/OPERATIONS.md",
        "frontend/src/stock/strategyBoard.ts",
    }
)
# Outside backend/ but part of the backend image build (backend/Dockerfile, #333): the docker
# job runs with the python flag, so a change to what the build context leaves out runs it.
BACKEND_IMAGE_FILES: frozenset[str] = frozenset({".dockerignore"})
# The compose files at the root (#335): the compose job runs with the python or the frontend
# flag, so a change to them alone sets python.
COMPOSE_FILES: frozenset[str] = frozenset(
    {"docker-compose.yml", "docker-compose.dev.yml"}
)


# Every Python file under backend/ and tools/, not only the changed ones, with the root ruff.toml.
LINT_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("ruff", "check", "--no-cache", "backend", "tools"),
    ("ruff", "format", "--check", "--no-cache", "backend", "tools"),
)


def change_flags(paths: list[str]) -> dict[str, bool]:
    shared = any(p.startswith((".github/workflows/", "tools/ci/")) for p in paths)
    # Markdown never reaches the product jobs unless a backend test reads it; the repository job checks it.
    product = [p for p in paths if not p.lower().endswith(".md")]
    return {
        "python": shared
        or any(
            p in BACKEND_READ_FILES or p in BACKEND_IMAGE_FILES or p in COMPOSE_FILES
            for p in paths
        )
        or any(
            p.startswith(("backend/", "tools/") + BACKEND_READ_DIRS)
            or p.endswith(".py")
            for p in product
        ),
        "frontend": shared
        or any(p.startswith(("frontend/", "tools/", "backend/")) for p in product),
    }


def markdown_prose(text: str) -> str:
    """Text without fenced code examples, which hold neither links nor headings."""
    return re.sub(
        r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[^\n]*$", "", text, flags=re.M | re.S
    )


def heading_slug(heading: str) -> str:
    """The anchor GitHub gives a heading: downcase, drop all but word characters, `-` and
    spaces, then spaces to `-`. Word characters are letters, marks, digits and `_`, so CJK
    stays and full-width punctuation such as 「」（）／ goes."""
    text = re.sub(r"<[^>]*>", "", heading)  # inline HTML renders no text
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("`", "")
    return "".join(
        c
        for c in text.strip().lower()
        if c in "- "
        or unicodedata.category(c)[0] in "LM"
        or unicodedata.category(c) in {"Nd", "Pc"}
    ).replace(" ", "-")


def anchors(text: str) -> set[str]:
    """Heading anchors (a repeated one gets -1, -2, ...) and HTML id/name attributes."""
    prose = markdown_prose(text)
    found: set[str] = set(re.findall(r"<a\s[^>]*\b(?:id|name)=\"([^\"]+)\"", prose))
    counts: dict[str, int] = {}
    for heading in re.findall(
        r"^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$", prose, flags=re.M
    ):
        slug = heading_slug(heading)
        found.add(f"{slug}-{counts[slug]}" if slug in counts else slug)
        counts[slug] = counts.get(slug, 0) + 1
    return found


# Absolute links into this repository's master are checked like relative ones.
REPO_LINK = re.compile(
    r"https://github\.com/YiCheng0608/stock-lab/(?:blob|tree)/master/"
)


def markdown_errors(path: str, text: str) -> list[str]:
    """Links whose file is missing, or whose anchor no heading of a Markdown file makes.

    Covers relative links and absolute links into master; other URLs are not fetched.
    Fenced code examples are ignored.
    """
    prose = markdown_prose(text)
    errors = []
    targets = re.findall(
        r"\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)", prose
    )
    targets += re.findall(
        r"^ {0,3}\[(?!\^)[^\]]+\]:\s*(<[^>]+>|\S+)", prose, flags=re.M
    )
    for raw in targets:
        link = raw.strip("<>")
        repo = REPO_LINK.match(link)
        parsed = urlsplit(link[repo.end() :] if repo else link)
        if not repo and (parsed.scheme or parsed.netloc or link.startswith("/")):
            continue
        if repo:
            target = ROOT / unquote(parsed.path)
        elif parsed.path:
            target = (ROOT / path).parent / unquote(parsed.path)
        else:
            target = ROOT / path
        if not target.exists():
            errors.append(f"{path}: missing relative link {link}")
        elif parsed.fragment and target.suffix.lower() == ".md":
            same = target.resolve() == (ROOT / path).resolve()
            made = anchors(text if same else target.read_text(encoding="utf-8"))
            if unquote(parsed.fragment) not in made:
                errors.append(f"{path}: no heading makes the anchor of {link}")
    return errors


# Each doc's first line names the concepts it is the one source for (#312).
OWNS = re.compile(r"<!-- owns: (.*) -->")


def owns_errors(docs: dict[str, str]) -> list[str]:
    """docs maps docs/**/*.md and AGENTS.md to their text; no concept is owned twice."""
    errors = []
    owner: dict[str, str] = {}
    for name, text in sorted(docs.items()):
        line = OWNS.fullmatch(text.split("\n", 1)[0].rstrip("\r"))
        if not line:
            errors.append(f"{name}: the first line is not <!-- owns: <concepts> -->")
            continue
        for concept in re.split(r"[、,，]", line.group(1)):
            key = concept.strip().casefold()
            if not key:
                errors.append(f"{name}: empty concept in the owns line")
            elif key in owner:
                errors.append(
                    f"{name}: concept '{concept.strip()}' already owned by {owner[key]}"
                )
            else:
                owner[key] = name
    return errors


def documentation_errors() -> list[str]:
    """Links and anchors of every Markdown file, and the owns lines, in the working tree.

    Every file, not only changed ones: moving a heading breaks links in files left alone.
    """
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "*.md")
    texts = {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in sorted({n.decode("utf-8") for n in listed.split(b"\0") if n})
        if (ROOT / name).is_file()
    }
    errors = [
        error for name, text in texts.items() for error in markdown_errors(name, text)
    ]
    docs = {
        name: text
        for name, text in texts.items()
        if name == "AGENTS.md" or (name.startswith("docs/") and name.endswith(".md"))
    }
    return errors + owns_errors(docs)


# The Windows execution layer left with Task Scheduler (#331, #333) and is not to come back
# (#341). RUNTIME_PATHS is what runs in the api and scheduler containers: the backend, the image
# and compose files, and the tools/ops scripts worker.serve runs. Agent tools that run on the
# Windows host keep their 8.3 name and junction handling (#331 審查結論 3) and are not scanned:
# close_task.sh, agent_guard.cjs, conftest.py, and on purpose also coordinator_lib.sh and
# coordinator_json.py, which run in the scheduler container too (monitor.sh, http_wake.sh and
# http_orca.sh source the first) but are shared with the host tools; there a Windows candidate
# such as .venv/Scripts/python.exe fails and the next one is tried (PR #370 review).
RUNTIME_PATHS: tuple[str, ...] = (
    "backend/app/",
    "backend/worker/",
    "backend/docker/",
    "backend/Dockerfile",
    "frontend/Dockerfile",
    "frontend/docker/nginx.conf.template",
    "docker-compose.yml",
    "docker-compose.dev.yml",
    "tools/ops/watchdog.sh",
    "tools/ops/watchdog_helper.py",
    "tools/ops/monitor.sh",
    "tools/ops/event_queue.py",
    "tools/ops/gh_auth.sh",
    "tools/ops/http_wake.sh",
    "tools/ops/http_orca.sh",
)
# Windows scripts anywhere in the repository; only the Task Scheduler registration the
# production schedule still runs on until the cutover (#342), which removes them and this list.
WINDOWS_SCRIPT = re.compile(r"\.(?:ps1|psm1|psd1|bat|cmd|vbs)$", re.I)
WINDOWS_SCRIPTS_LEFT: tuple[str, ...] = (
    "tools/Invoke-WorkerJob.ps1",
    "tools/Register-WorkerSchedule.ps1",
    "tools/ops/Register-Monitor.ps1",
    "tools/ops/Register-Watchdog.ps1",
)
# Windows APIs, WMI, Task Scheduler, windowless or native-.exe processes, PowerShell, cmd and a
# branch that names Windows (== / != against win32, nt or Windows; any `in` test of sys.platform,
# os.name or platform.system()), in code (comments and docstrings are left out: they tell the
# history). A refusal off POSIX or Linux (`os.name != "posix"`, `sys.platform.startswith("linux")`)
# names no Windows and is allowed: schedule_runs._pid_alive and worker.job.platform_problem.
WINDOWS_RUNTIME = re.compile(
    r"""windll|msvcrt|winreg|_winapi|\bwin32(?:api|con|process|job)\b|pywintypes|GlobalMemoryStatus
    |\bWin32_\w+|Get-CimInstance|Get-WmiObject|\bwmic?\b
    |schtasks|ScheduledTask|taskkill
    |pythonw|python\.exe|claude\.exe
    |CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW|DETACHED_PROCESS|creationflags|STARTUPINFO
    |CTRL_BREAK_EVENT|WINFUNCTYPE|os\.startfile
    |\bpowershell\b|\bpwsh\b|\.ps1\b|\bcmd\.exe\b|\bcmd\s+/
    |sys\.platform\s*[!=]=\s*["']win|sys\.platform\.startswith\(\s*["']win
    |os\.name\s*[!=]=\s*["']nt|platform\.system\(\)\s*[!=]=\s*["']Windows
    |(?:sys\.platform|os\.name|platform\.system\(\))\s+(?:not\s+)?in\b""",
    re.I | re.X,
)


def runtime_code(name: str, text: str) -> list[str]:
    """The lines of a file with comments (and Python docstrings) blanked, numbered as before."""
    lines = text.splitlines()
    if not name.endswith(".py"):
        # Shell, Dockerfile, YAML, nginx: `#` at the start of a line or after a space.
        return [re.sub(r"(^|\s)#.*", r"\1", line) for line in lines]
    skip: set[int] = set()
    for node in ast.walk(ast.parse(text, filename=name)):
        body = getattr(node, "body", None)
        if (
            isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and body
        ):
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    skip.update(range(first.lineno, first.end_lineno + 1))
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            row, col = token.start
            lines[row - 1] = lines[row - 1][:col]
    return ["" if number in skip else line for number, line in enumerate(lines, 1)]


def windows_runtime_errors(
    names: list[str] | None = None, root: Path = ROOT
) -> list[str]:
    """Windows scripts outside WINDOWS_SCRIPTS_LEFT and Windows logic in RUNTIME_PATHS.

    Every file of the working tree, not only changed ones, like documentation_errors. That each
    entry of WINDOWS_SCRIPTS_LEFT still exists is a test of tools/ci/test_checks.py.
    """
    if names is None:
        listed = git(
            "ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=root
        )
        names = sorted({n.decode("utf-8") for n in listed.split(b"\0") if n})
    names = [name for name in names if (root / name).is_file()]
    errors = [
        f"{name}: a Windows script; the schedule runs in the Linux containers (#331, #341)"
        for name in names
        if WINDOWS_SCRIPT.search(name) and name not in WINDOWS_SCRIPTS_LEFT
    ]
    for name in names:
        if not any(path_matches(name, pattern) for pattern in RUNTIME_PATHS):
            continue
        try:
            code = runtime_code(name, (root / name).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError, tokenize.TokenError) as exc:
            errors.append(f"{name}: not read for Windows logic: {exc}")
            continue
        for number, line in enumerate(code, 1):
            match = WINDOWS_RUNTIME.search(line)
            if match:
                errors.append(
                    f"{name}:{number}: Windows execution layer ({match.group(0)}); "
                    "what runs in the containers is Linux only (#331, #341)"
                )
    return errors


def repository_checks(paths: list[str], base: str) -> None:
    """Check the working tree against base, the same files the checks below read.

    In CI the working tree is HEAD. Locally it includes staged and unstaged edits, so an
    uncommitted `git merge --no-commit` result is what gets checked, not the pre-merge HEAD.
    """
    errors = []
    if base != "0" * 40:
        subprocess.run(["git", "diff", "--check", base], cwd=ROOT, check=True)
    for name in paths:
        path = ROOT / name
        if not path.is_file() or path.suffix.lower() not in {
            ".md",
            ".py",
            ".json",
            ".yaml",
            ".yml",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if "\ufffd" in text:
                errors.append(f"{name}: Unicode replacement character")
            if path.suffix == ".py":
                ast.parse(text, filename=name)
            elif path.suffix == ".json":
                json.loads(text)
            elif path.suffix in {".yaml", ".yml"}:
                import yaml

                yaml.load(text, Loader=yaml.BaseLoader)
        except (ValueError, SyntaxError, UnicodeError) as exc:
            errors.append(f"{name}: {exc}")
    errors.extend(documentation_errors())
    errors.extend(windows_runtime_errors())
    if errors:
        raise ValueError("\n".join(errors))
    print(
        f"Repository checks passed for {len(paths)} changed paths and the links of every "
        "Markdown file (external links not checked)."
    )


# PR gate (docs/GITHUB_WORKFLOW.md, 分流 and Review 與合併). HIGH_RISK_PATHS is the one list of
# paths that need an independent review; the handbook links here instead of repeating it.
# An entry ending in "/" is a directory prefix; one with "*" matches within a single directory.
HIGH_RISK_PATHS: tuple[str, ...] = (
    "backend/alembic/",
    "backend/app/migrations.py",
    "backend/app/migration_revisions.py",
    "backend/app/indicators.py",  # indicator formulas
    "backend/worker/",  # schedules, collectors, strategy formulas
    "tools/ops/",
    "tools/*.ps1",
)
INDEPENDENT_REVIEW_LABEL = "independent-review"
PRODUCT_PATHS: tuple[str, ...] = (
    "backend/app/",
    "backend/worker/",
    "backend/alembic/",
    "backend/data/",
    "frontend/src/",
)
CLOSES = re.compile(r"\bcloses\s+#\d+\b", re.I)
# What GitHub reads as closing an Issue; a commit carrying one closes it before the PR merges.
CLOSING_KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?[ \t]+#\d+", re.I
)
# The section label starts its line (after a list or checkbox marker), unlike prose naming it.
AC_SECTION = re.compile(
    r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?)?(?:#{1,6}\s+)?(?:\*\*)?AC 逐條結果"
)
AC_ITEM = re.compile(
    r"^(\s*)(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)?(?:\*\*|__)?AC-?(\d+)\b(.*)$"
)
# Punctuation that can follow an AC label without being a result.
AC_FILLER = re.compile(r"[\s*_~`:：/／|、,，.。()（）\-–—]+")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b|pr-assets", re.I)


def path_matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "*" in pattern:
        return path.count("/") == pattern.count("/") and fnmatch.fnmatchcase(
            path, pattern
        )
    return path == pattern


def high_risk(paths: list[str]) -> list[str]:
    return [p for p in paths if any(path_matches(p, h) for h in HIGH_RISK_PATHS)]


def frontend_source(paths: list[str]) -> list[str]:
    return [
        p
        for p in paths
        if p.startswith("frontend/src/") and not re.search(r"\.test\.[^/]+$", p)
    ]


def needs_issue(paths: list[str]) -> list[str]:
    """Rule a paths: product sources (frontend/src without tests) and high-risk paths."""
    product = [
        p
        for p in paths
        if p.startswith(PRODUCT_PATHS) and not p.startswith("frontend/src/")
    ]
    return sorted(set(product + frontend_source(paths) + high_risk(paths)))


def ac_results(body: str) -> dict[str, str] | None:
    """AC number -> result text in the 「AC 逐條結果」 section, or None without one."""
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if AC_SECTION.match(line)), None)
    if start is None:
        return None
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if re.match(r" {0,3}#{1,6}\s", lines[i])
        ),
        len(lines),
    )
    results: dict[str, str] = {}
    section = lines[start + 1 : end]
    for i, line in enumerate(section):
        item = AC_ITEM.match(line)
        if not item:
            continue
        indent = len(item.group(1))
        text = [item.group(3)]
        # A result can continue on lines indented under the item (nested lists, code).
        for follow in section[i + 1 :]:
            if follow.strip() and (
                len(follow) - len(follow.lstrip()) <= indent or AC_ITEM.match(follow)
            ):
                break
            text.append(follow)
        results[f"AC-{item.group(2)}"] = AC_FILLER.sub("", "\n".join(text))
    return results


def pr_errors(
    body: str, paths: list[str], labels: list[str], commits: dict[str, str]
) -> list[str]:
    """Rules a-e of the PR gate; commits maps each non-merge commit to its message."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)  # template guidance
    errors = []
    product = needs_issue(paths)
    if product and not CLOSES.search(body):
        errors.append(
            f"a: product or high-risk paths changed ({', '.join(product[:3])}...); "
            "the body needs 'Closes #<issue>'"
        )
    results = ac_results(body)
    if results is None:
        if product:
            errors.append("b: the body has no 「AC 逐條結果」 section")
    else:
        if product and not results:
            errors.append("b: the 「AC 逐條結果」 section lists no AC-<n>")
        errors.extend(
            f"b: {name} has no result (command and output, query, or link)"
            for name, text in results.items()
            if not text
        )
    front = frontend_source(paths)
    if front and not IMAGE.search(body):
        errors.append(
            f"c: frontend/src changed ({front[0]}...); the body needs a screenshot "
            "or a pr-assets link"
        )
    risky = high_risk(paths)
    if risky and INDEPENDENT_REVIEW_LABEL not in labels:
        errors.append(
            f"d: high-risk paths changed ({', '.join(risky[:3])}...); "
            f"the PR needs the '{INDEPENDENT_REVIEW_LABEL}' label"
        )
    for sha, message in commits.items():
        found = CLOSING_KEYWORD.search(message)
        if found:
            errors.append(
                f"e: commit {sha[:12]} message has closing keyword '{found.group()}'"
            )
    return errors


def pr_changes(base: str, cwd: Path = ROOT) -> tuple[str, list[str], dict[str, str]]:
    """The merge-base with the base branch tip, and the paths and commits since it.

    Pass the base branch tip as it is now: a pull_request.base.sha recorded before master
    moved is an ancestor of the merge ref, so it would count master's newer commits as the
    PR's. The merge-base leaves out master commits the branch lacks or already merged.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("base must be a full Git SHA")
    fork = git("merge-base", base, "HEAD", cwd=cwd).decode("ascii").strip()
    return fork, changed_paths(fork, cwd), commit_messages(fork, cwd)


def commit_messages(base: str, cwd: Path = ROOT) -> dict[str, str]:
    out = git("log", "--no-merges", "-z", "--format=%H%n%B", f"{base}..HEAD", cwd=cwd)
    commits = {}
    for entry in out.decode("utf-8").split("\0"):
        if entry.strip():
            sha, _, message = entry.strip("\n").partition("\n")
            commits[sha] = message
    return commits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("changes", "repository", "lint", "pr"))
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    if args.mode == "pr":
        fork, paths, commits = pr_changes(args.base)
        # CI passes the event fields through env: (never interpolated into run:).
        errors = pr_errors(
            os.environ["PR_BODY"], paths, json.loads(os.environ["PR_LABELS"]), commits
        )
        if errors:
            raise SystemExit("PR gate failed:\n" + "\n".join(errors))
        print(f"PR gate passed for {len(paths)} changed paths since {fork}.")
        return
    paths = changed_paths(args.base, worktree=args.mode == "repository")
    if args.mode == "changes":
        flags = change_flags(paths)
        print(json.dumps({"paths": paths, "required": flags}))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            for name, value in flags.items():
                print(f"{name}={str(value).lower()}", file=output)
    elif args.mode == "repository":
        repository_checks(paths, args.base)
    else:
        # Run both so one CI log shows lint and format failures together.
        failed = [
            command
            for command in LINT_COMMANDS
            if subprocess.run([sys.executable, "-m", *command], cwd=ROOT).returncode
        ]
        if failed:
            raise SystemExit(
                "Failed: " + "; ".join(" ".join(command) for command in failed)
            )


if __name__ == "__main__":
    main()
