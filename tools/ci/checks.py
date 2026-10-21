"""Small, offline CI checks; do not import application configuration or data."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def changed_paths(base: str) -> list[str]:
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("base must be a full Git SHA")
    if base == "0" * 40:
        result = git("ls-files", "-z")
    else:
        result = git("diff", "--name-only", "--no-renames", "-z", base, "HEAD")
    return [name.decode("utf-8") for name in result.split(b"\0") if name]


# Working-tree paths outside backend/ and tools/ that the backend job reads; a change must run it.
# Keep in step with backend/tests. No backend test reads frontend/ since #179 removed the App.tsx
# renderer check; test_database_readiness reads the Alembic head stated in docs/OPERATIONS.md.
BACKEND_READ_DIRS: tuple[str, ...] = ()
BACKEND_READ_FILES: frozenset[str] = frozenset({"docs/OPERATIONS.md"})


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
        or any(p in BACKEND_READ_FILES for p in paths)
        or any(
            p.startswith(("backend/", "tools/") + BACKEND_READ_DIRS)
            or p.endswith(".py")
            for p in product
        ),
        "frontend": shared
        or any(p.startswith(("frontend/", "tools/", "backend/")) for p in product),
    }


def markdown_errors(path: str, text: str) -> list[str]:
    # Only repository-relative file links; external URLs and heading anchors
    # remain the local reviewer's responsibility. Ignore fenced code examples.
    prose = re.sub(r"^(`{3,}|~{3,}).*?^\1[^\n]*$", "", text, flags=re.M | re.S)
    errors = []
    targets = re.findall(
        r"\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)", prose
    )
    targets += re.findall(
        r"^ {0,3}\[(?!\^)[^\]]+\]:\s*(<[^>]+>|\S+)", prose, flags=re.M
    )
    for raw in targets:
        link = raw.strip("<>")
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path or link.startswith("/"):
            continue
        target = (ROOT / path).parent / unquote(parsed.path)
        if not target.exists():
            errors.append(f"{path}: missing relative link {link}")
    return errors


def repository_checks(paths: list[str], base: str) -> None:
    errors = []
    if base != "0" * 40:
        subprocess.run(["git", "diff", "--check", base, "HEAD"], cwd=ROOT, check=True)
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
            elif path.suffix == ".md":
                errors.extend(markdown_errors(name, text))
        except (ValueError, SyntaxError, UnicodeError) as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    print(
        f"Repository checks passed for {len(paths)} changed paths (external links/anchors not checked)."
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


def commit_messages(base: str) -> dict[str, str]:
    out = git("log", "--no-merges", "-z", "--format=%H%n%B", f"{base}..HEAD")
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
    paths = changed_paths(args.base)
    if args.mode == "changes":
        flags = change_flags(paths)
        print(json.dumps({"paths": paths, "required": flags}))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            for name, value in flags.items():
                print(f"{name}={str(value).lower()}", file=output)
    elif args.mode == "repository":
        repository_checks(paths, args.base)
    elif args.mode == "pr":
        # CI passes the event fields through env: (never interpolated into run:).
        errors = pr_errors(
            os.environ["PR_BODY"],
            paths,
            json.loads(os.environ["PR_LABELS"]),
            commit_messages(args.base),
        )
        if errors:
            raise SystemExit("PR gate failed:\n" + "\n".join(errors))
        print(f"PR gate passed for {len(paths)} changed paths.")
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
