"""Import every module of the app and worker packages (#378).

CI's docker job runs this in the backend image, whose test run no longer covers the whole
suite: a dependency missing from the image must still fail there. `import app, worker` alone
imports two docstring-only `__init__.py`; a dependency only a submodule needs (httpx in
worker.sources) goes unseen until a test happens to import that submodule. An import done
inside a function (apscheduler in worker.serve, alembic in app.migrations) is not reached
here; the tests that run those functions cover it.

    python -B tools/ci/import_modules.py [--root backend] [--package app --package worker]

Exits 1 and lists each module that fails to import with its error.
"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]


def module_names(root: Path, package: str) -> list[str]:
    """Dotted names of the package and of every .py file under it (no __main__)."""
    names = []
    for path in sorted((root / package).rglob("*.py")):
        parts = path.relative_to(root).with_suffix("").parts
        if parts[-1] == "__main__":
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return names


def import_all(names: list[str]) -> dict[str, str]:
    """Import each name; the failures as {name: last line of the traceback}."""
    failures = {}
    for name in names:
        try:
            importlib.import_module(name)
        except BaseException as error:  # noqa: BLE001 - SystemExit at import time counts too
            if isinstance(error, KeyboardInterrupt):
                raise
            failures[name] = traceback.format_exception_only(type(error), error)[
                -1
            ].strip()
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=str(ROOT / "backend"))
    parser.add_argument("--package", action="append", dest="packages")
    options = parser.parse_args(argv)
    root = Path(options.root).resolve()
    sys.path.insert(0, str(root))
    names = [
        name
        for package in options.packages or ["app", "worker"]
        for name in module_names(root, package)
    ]
    if not names:
        print("no module found under", root, file=sys.stderr)
        return 1
    failures = import_all(names)
    for name, error in failures.items():
        print(f"{name}: {error}", file=sys.stderr)
    if failures:
        print(
            f"{len(failures)} of {len(names)} modules failed to import", file=sys.stderr
        )
        return 1
    print(f"imported {len(names)} modules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
