"""Run product code in child processes whose STOCK_* are set before any import.

``app.config``/``app.db`` bind ``STOCK_DB_PATH`` and create the data and raw
directories at import time, so the tool process never imports ``app``.  Each
child gets an environment rebuilt from scratch: every inherited ``STOCK_*``
variable is dropped (this also removes live-source opt-ins) and only the three
isolation variables of the target run are set, after being read back and
validated.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from .errors import DbEntryError
from .paths import REPO_ROOT, STOCK_VARS, forbidden_reason, inherited_protected_paths, is_within, remove_tree_or_raise

BACKEND_DIR = REPO_ROOT / "backend"
CHILD_SCRIPT = Path(__file__).with_name("_child.py")


def stock_env_for(data_dir: Path) -> dict[str, str]:
    data_dir = Path(data_dir)
    return {
        "STOCK_DATA_DIR": str(data_dir),
        "STOCK_DB_PATH": str(data_dir / "stock.db"),
        "STOCK_RAW_DIR": str(data_dir / "raw"),
    }


def validate_stock_env(
    env: Mapping[str, str],
    *,
    allowed_root: Path,
    forbidden: Iterable[Path] = (),
    protected: Iterable[Path] = (),
) -> dict[str, str]:
    """Read the three STOCK_* back and refuse anything outside ``allowed_root``.

    ``forbidden`` holds locations that must never be a writable target (the
    read-only sample library); ``protected`` holds locations such as an
    inherited daily-database path. Returns the resolved values that were read.
    """

    readback: dict[str, str] = {}
    for name in STOCK_VARS:
        raw = env.get(name)
        if not raw:
            raise DbEntryError("stock_env_invalid", f"{name} is not set; all of {STOCK_VARS} must be set before running")
        reason = forbidden_reason(raw, protected)
        if reason:
            raise DbEntryError("forbidden_target", f"{name}: {reason}", path=raw)
        resolved = Path(raw).resolve()
        for banned in forbidden:
            if is_within(resolved, banned):
                raise DbEntryError(
                    "forbidden_target", f"{name} points into the read-only sample library {banned}", path=resolved
                )
        if not is_within(resolved, allowed_root):
            raise DbEntryError(
                "forbidden_target", f"{name} is outside the isolated directory {Path(allowed_root).resolve()}", path=resolved
            )
        readback[name] = str(resolved)
    return readback


def build_child_env(
    stock_env: Mapping[str, str],
    tmp_dir: Path,
    *,
    python_path: Iterable[str] = (),
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = {key: value for key, value in (os.environ if base is None else base).items() if not key.startswith("STOCK_")}
    env.update(stock_env)
    env.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONSAFEPATH="1",  # never import from the script directory or the cwd by accident
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        TEMP=str(tmp_dir),
        TMP=str(tmp_dir),
        TMPDIR=str(tmp_dir),
    )
    paths = [str(item) for item in python_path]
    if paths:
        inherited = env.get("PYTHONPATH")
        env["PYTHONPATH"] = os.pathsep.join(paths + ([inherited] if inherited else []))
    return env


def default_deps() -> tuple[str, ...]:
    return tuple(item for item in os.environ.get("STOCK_TEST_DEPS", "").split(os.pathsep) if item)


@dataclass(frozen=True)
class ProductRunner:
    """Runs ``backend`` code for one tool root; scratch space lives under ``root/tmp``."""

    root: Path
    python: str = field(default_factory=lambda: sys.executable)
    deps: tuple[str, ...] = field(default_factory=default_deps)
    timeout: float = 180.0
    protected: tuple[Path, ...] = field(default_factory=inherited_protected_paths)

    def run(
        self,
        argv: list[str],
        *,
        stock_env: Mapping[str, str],
        tmp_dir: Path,
        allowed_root: Path,
        forbidden: Iterable[Path] = (),
    ) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
        readback = validate_stock_env(stock_env, allowed_root=allowed_root, forbidden=forbidden, protected=self.protected)
        Path(tmp_dir).mkdir(parents=True, exist_ok=True)
        env = build_child_env(stock_env, tmp_dir, python_path=[str(BACKEND_DIR), *self.deps])
        command = [self.python, "-B", "-X", "utf8", *argv]
        try:
            proc = subprocess.run(
                command, cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise DbEntryError(
                "product_timeout", f"child exceeded {self.timeout}s: {' '.join(argv)}", path=stock_env["STOCK_DB_PATH"]
            ) from exc
        if proc.returncode != 0:
            raise DbEntryError(
                "product_failed",
                f"child exit {proc.returncode}: {' '.join(argv)}: {proc.stderr.strip()[-600:]}",
                path=stock_env["STOCK_DB_PATH"],
                stdout_tail=proc.stdout[-600:],
            )
        return proc, readback

    def _json(self, proc: subprocess.CompletedProcess) -> dict:
        """The product CLI prints indented JSON; the probes print one line."""

        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        for candidate in (proc.stdout, lines[-1] if lines else ""):
            try:
                value = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
        raise DbEntryError("product_failed", f"child printed no JSON result: {proc.stdout[-300:]!r}")

    def init_db(self, data_dir: Path, tmp_dir: Path, allowed_root: Path) -> dict:
        """The product's own ``python -m worker.cli init-db`` against ``data_dir``."""

        proc, readback = self.run(
            ["-m", "worker.cli", "init-db"], stock_env=stock_env_for(data_dir), tmp_dir=tmp_dir, allowed_root=allowed_root
        )
        result = self._json(proc)
        if result.get("status") != "success":
            raise DbEntryError("product_failed", f"init-db reported {result}", path=readback["STOCK_DB_PATH"])
        return {"result": result, "stock_env": readback}

    def probe(self, action: str, args: list[str], *, data_dir: Path, tmp_dir: Path, allowed_root: Path) -> dict:
        proc, readback = self.run(
            [str(CHILD_SCRIPT), action, *args], stock_env=stock_env_for(data_dir), tmp_dir=tmp_dir, allowed_root=allowed_root
        )
        result = self._json(proc)
        result["stock_env_readback"] = readback
        return result

    def check_schema(self, db_path: Path) -> dict:
        """Run the product's read-only readiness check on ``db_path`` from a scratch directory.

        The scratch directory (not the checked file's directory) receives the
        data/raw directories that ``app.config`` creates at import.
        """

        scratch = self.root / "tmp" / f"scratch-{uuid.uuid4().hex[:8]}"
        (scratch / "data" / "raw").mkdir(parents=True)
        try:
            return self.probe(
                "check", ["--db", str(db_path)], data_dir=scratch / "data", tmp_dir=scratch / "tmp", allowed_root=scratch
            )
        finally:
            remove_tree_or_raise(scratch)
