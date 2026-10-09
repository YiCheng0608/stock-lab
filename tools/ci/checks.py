"""Small, offline CI checks; do not import application configuration or data."""
from __future__ import annotations

import argparse
import ast
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


def change_flags(paths: list[str]) -> dict[str, bool]:
    shared = any(p.startswith((".github/workflows/", "tools/ci/")) for p in paths)
    return {
        "python": shared or any(p.startswith(("backend/", "tools/")) or p.endswith(".py") or p == "docs/development-baseline/validation-requirements.lock.txt" for p in paths),
        "frontend": shared or any(p.startswith(("frontend/", "tools/", "backend/")) for p in paths),
    }


def markdown_errors(path: str, text: str) -> list[str]:
    # Only repository-relative file links; external URLs and heading anchors
    # remain the local reviewer's responsibility. Ignore fenced code examples.
    prose = re.sub(r"^(`{3,}|~{3,}).*?^\1[^\n]*$", "", text, flags=re.M | re.S)
    errors = []
    targets = re.findall(r"\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)", prose)
    targets += re.findall(r"^ {0,3}\[(?!\^)[^\]]+\]:\s*(<[^>]+>|\S+)", prose, flags=re.M)
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
        if not path.is_file() or path.suffix.lower() not in {".md", ".py", ".json", ".yaml", ".yml"}:
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
    print(f"Repository checks passed for {len(paths)} changed paths (external links/anchors not checked).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("changes", "repository", "lint"))
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
    else:
        files = [p for p in paths if p.endswith(".py") and (ROOT / p).is_file()]
        if files:
            subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "--isolated", "--select", "E9,F63,F7,F82", "--", *files], cwd=ROOT, check=True)
        else:
            print("No changed Python files to lint.")


if __name__ == "__main__":
    main()
