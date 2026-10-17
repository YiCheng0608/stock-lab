"""The shared entry: sample library, isolated test databases, quota and cleanup.

Layout under one explicit root (always outside the product checkout)::

    <root>/samples/<version>/{sample.db, metadata.json}   read-only, immutable per version
    <root>/runs/<run-id>/{.testdb-run.json, data/stock.db, data/raw/, tmp/}
    <root>/tmp/                                           scratch for schema checks
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .errors import CleanupError, DbEntryError, QuotaExceededError
from .paths import (
    DEFAULT_MAX_TOTAL_BYTES, assert_allowed_target, assert_path_budget, inherited_protected_paths, is_link_or_reparse,
    remove_tree, remove_tree_or_raise, tree_size,
)
from .product import ProductRunner, build_child_env, default_deps, stock_env_for, validate_stock_env
from .sample import (
    DB_NAME, IDENTIFIER_RE, KINDS, META_NAME, NAME_MAX, build_metadata, check_name, load_fixture, open_readonly,
    read_alembic_markers, read_fixture, read_metadata, row_counts, sha256_file, write_metadata,
)

RUN_MARKER = ".testdb-run.json"
RUN_MARKER_SCHEMA = 1
RUN_DB_NAME = "stock.db"
# A child's TEMP is the run's tmp/. One tempfile directory (``tmp`` + 8 characters = 11) holding one SQLite temporary
# file (``etilqs_`` + 16 = 23) is 35 characters with its separator; this rounds up.
CHILD_TEMP_RESERVE = 48
_LONGEST_NAME = "n" * NAME_MAX  # a run id or sample version at its longest
_SCRATCH_NAME = "scratch-" + "x" * 8  # product.ProductRunner.check_schema: <root>/tmp/scratch-<8 hex>
# The longest paths the entry builds below a root, as the components after it; ROOT_PATH_RESERVE is the longest of them
# counting one separator per component. ``DbEntry`` refuses a root that leaves less than this room under Windows MAX_PATH.
ROOT_PATH_SUFFIXES: dict[str, tuple[str, ...]] = {
    "run marker": ("runs", _LONGEST_NAME, RUN_MARKER),
    "run database journal": ("runs", _LONGEST_NAME, "data", RUN_DB_NAME + "-journal"),
    "run child temp file": ("runs", _LONGEST_NAME, "tmp", "t" * CHILD_TEMP_RESERVE),
    "sample database journal": ("samples", _LONGEST_NAME, DB_NAME + "-journal"),
    "sample metadata": ("samples", _LONGEST_NAME, META_NAME),
    "publish staging": ("samples", ".partial-" + "x" * 8, META_NAME),
    "schema check journal": ("tmp", _SCRATCH_NAME, "data", RUN_DB_NAME + "-journal"),
    "schema check temp file": ("tmp", _SCRATCH_NAME, "tmp", "t" * CHILD_TEMP_RESERVE),
}
ROOT_PATH_RESERVE = max(sum(len(part) + 1 for part in parts) for parts in ROOT_PATH_SUFFIXES.values())


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    run_dir: Path
    data_dir: Path
    db_path: Path
    raw_dir: Path
    tmp_dir: Path
    stock_env: dict[str, str]
    origin: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "run_dir": str(self.run_dir), "db_path": str(self.db_path),
            "raw_dir": str(self.raw_dir), "tmp_dir": str(self.tmp_dir), "origin": self.origin,
            "stock_env": self.stock_env,
        }


def _check_metadata(version: str, kind: str, meta: Any, fixture: dict[str, Any] | None) -> None:
    """Judge the supplied metadata with placeholder measurements, so unusable metadata fails before any disk work."""

    build_metadata(version=version, kind=kind, schema_version="-", sha256="-", size_bytes=0, counts={}, supplied=meta, fixture=fixture)


def _io_error(action: str, path: Path, exc: OSError) -> DbEntryError:
    code = "in_use" if isinstance(exc, PermissionError) else "io_error"
    try:
        size = path.stat().st_size if path.is_file() else None
    except OSError:
        size = None
    return DbEntryError(code, f"{action}: {type(exc).__name__}: {exc}", path=path, size_bytes=size)


class DbEntry:
    def __init__(
        self,
        root: Path | str,
        *,
        max_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        python: str | None = None,
        deps: tuple[str, ...] | None = None,
        timeout: float = 180.0,
    ) -> None:
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise DbEntryError("invalid_argument", f"max_bytes must be a positive integer, got {max_bytes!r}")
        self.protected = inherited_protected_paths()
        resolved = assert_allowed_target(root, role="tool root", protected=self.protected)
        assert_path_budget(resolved, reserved=ROOT_PATH_RESERVE)
        if os.path.lexists(resolved) and is_link_or_reparse(Path(root)):
            raise DbEntryError("reparse_point", "tool root must not be a link or reparse point", path=root)
        resolved.mkdir(parents=True, exist_ok=True)
        self.root = resolved
        self.max_bytes = max_bytes
        self.samples_dir = resolved / "samples"
        self.runs_dir = resolved / "runs"
        self.runner = ProductRunner(
            root=resolved, python=python or sys.executable,
            deps=default_deps() if deps is None else tuple(deps), timeout=timeout, protected=self.protected,
        )

    # ---- quota -------------------------------------------------------------

    def usage(self) -> dict[str, Any]:
        total = tree_size(self.root)
        parts = {}
        for child in sorted(self.root.iterdir()):
            parts[child.name] = tree_size(child)
        return {
            "root": str(self.root), "max_bytes": self.max_bytes, "total_bytes": total,
            "remaining_bytes": self.max_bytes - total, "by_entry": parts,
        }

    def _enforce(self, subject: Path, *, incoming: int = 0, action: str) -> None:
        current = tree_size(self.root)
        projected = current + incoming
        if projected > self.max_bytes:
            raise QuotaExceededError(
                f"{action}: projected total {projected} bytes (current {current} + incoming {incoming}) "
                f"exceeds the {self.max_bytes}-byte limit for {self.root}",
                path=subject, size_bytes=projected,
                current_bytes=current, incoming_bytes=incoming, limit_bytes=self.max_bytes,
            )

    # ---- sample library ------------------------------------------------------

    def sample_dir(self, version: str) -> Path:
        return self.samples_dir / check_name(version, "sample version")

    def _versions(self) -> list[str]:
        if not self.samples_dir.is_dir():
            return []
        return sorted(item.name for item in self.samples_dir.iterdir() if item.is_dir() and not item.name.startswith("."))

    def list_samples(self) -> list[dict[str, Any]]:
        listing = []
        for version in self._versions():
            try:
                meta = read_metadata(self.samples_dir / version / META_NAME)
                listing.append({k: meta[k] for k in ("sample_version", "kind", "schema_version", "sha256", "size_bytes", "created_at")})
            except DbEntryError as exc:
                listing.append({"sample_version": version, "error": exc.to_dict()})
        return listing

    def verify(self, version: str, *, expect_sha256: str | None = None, check_product: bool = True) -> dict[str, Any]:
        directory = self.sample_dir(version)
        if not directory.is_dir():
            raise DbEntryError(
                "version_missing", f"sample version {version!r} not found; available: {self._versions()}", path=directory
            )
        return self._verify_dir(directory, version, expect_sha256=expect_sha256, check_product=check_product)

    def _verify_dir(
        self, directory: Path, version: str, *, expect_sha256: str | None, check_product: bool
    ) -> dict[str, Any]:
        names = sorted(item.name for item in directory.iterdir())
        if names != sorted((DB_NAME, META_NAME)):
            raise DbEntryError(
                "sample_corrupt", f"expected exactly {[DB_NAME, META_NAME]} but found {names}", path=directory
            )
        db_path = directory / DB_NAME
        metadata = read_metadata(directory / META_NAME)
        if metadata["sample_version"] != version:
            raise DbEntryError(
                "version_mismatch",
                f"metadata says version {metadata['sample_version']!r} but the directory is {version!r}",
                path=directory,
            )
        actual, size = sha256_file(db_path)
        if actual != metadata["sha256"] or size != metadata["size_bytes"]:
            raise DbEntryError(
                "hash_mismatch",
                f"sample.db sha256 {actual} ({size} bytes) differs from recorded {metadata['sha256']} "
                f"({metadata['size_bytes']} bytes)",
                path=db_path, size_bytes=size, actual_sha256=actual, recorded_sha256=metadata["sha256"],
            )
        if expect_sha256 is not None and actual != expect_sha256.lower():
            raise DbEntryError(
                "hash_mismatch", f"sample.db sha256 {actual} is not the approved hash {expect_sha256.lower()}",
                path=db_path, size_bytes=size, actual_sha256=actual, approved_sha256=expect_sha256.lower(),
            )
        try:
            markers = read_alembic_markers(db_path)
        except sqlite3.DatabaseError as exc:
            raise DbEntryError("sample_corrupt", f"cannot open sample.db read-only: {exc}", path=db_path, size_bytes=size) from exc
        if markers != [metadata["schema_version"]]:
            raise DbEntryError(
                "schema_mismatch",
                f"database revision marker {markers} differs from recorded schema_version {metadata['schema_version']!r}",
                path=db_path, size_bytes=size,
            )
        product = None
        if check_product:
            product = self.runner.check_schema(db_path)
            if product["alembic_head"] not in (None, product["revisions_head"]):
                raise DbEntryError(
                    "schema_mismatch",
                    f"product revisions {product['revisions_head']} disagree with Alembic head {product['alembic_head']}",
                    path=db_path, size_bytes=size,
                )
            # Stale first: it is the actionable cause, and the readiness check would also reject it, less clearly.
            if metadata["schema_version"] != product["revisions_head"]:
                raise DbEntryError(
                    "schema_mismatch",
                    f"sample schema {metadata['schema_version']} is not the product head {product['revisions_head']}; "
                    "publish a new sample version",
                    path=db_path, size_bytes=size,
                )
            if product["readiness"] != "ok":
                raise DbEntryError(
                    "schema_mismatch", f"product readiness check failed: {product['readiness']}", path=db_path, size_bytes=size
                )
        return {
            "version": version, "kind": metadata["kind"], "sample_dir": str(directory), "db_path": str(db_path),
            "size_bytes": size, "sha256": actual, "schema_version": metadata["schema_version"],
            "os_readonly": not os.access(db_path, os.W_OK),
            "checks": {"files": "ok", "version": "ok", "hash": "ok", "marker": "ok",
                       "product_schema": "ok" if product else "skipped"},
            "product": product, "metadata": metadata,
        }

    def select(self, version: str, *, expect_sha256: str | None = None, check_product: bool = False) -> dict[str, Any]:
        report = self.verify(version, expect_sha256=expect_sha256, check_product=check_product)
        report["read_only_uri"] = Path(report["db_path"]).as_uri() + "?mode=ro"
        return report

    @staticmethod
    def _make_dir(directory: Path) -> bool:
        """Create ``directory`` and its parents; True only when this call made the directory itself."""

        try:
            directory.mkdir(parents=True)
        except FileExistsError:
            return False
        return True

    def freeze(
        self, run: RunInfo | str, version: str, *, kind: str = "manual_fixture", meta: dict[str, Any] | None = None,
        fixture: dict[str, Any] | None = None, check_product: bool = True,
    ) -> dict[str, Any]:
        """Publish an isolated run's database as an immutable, read-only sample version."""

        final = self.sample_dir(version)
        if kind not in KINDS:
            raise DbEntryError("invalid_argument", f"kind {kind!r} must be one of {KINDS}")
        if final.exists():
            raise DbEntryError("version_exists", "a sample version is immutable; publish a new version name", path=final)
        info = run if isinstance(run, RunInfo) else self._load_run(run)
        if not info.db_path.is_file():
            raise DbEntryError("not_found", "run has no database to freeze", path=info.db_path)
        stray = sorted(item.name for item in info.data_dir.glob("stock.db-*"))
        if stray:
            raise DbEntryError("sample_corrupt", f"journal/wal files {stray} present; the database is in use", path=info.db_path)
        markers = read_alembic_markers(info.db_path)
        if len(markers) != 1:
            raise DbEntryError(
                "schema_mismatch", f"database must carry exactly one Alembic revision marker, found {markers}", path=info.db_path
            )
        _check_metadata(version, kind, meta, fixture)  # before the quota: unusable metadata is the cause to report
        sha256, size = sha256_file(info.db_path)
        partial = self.samples_dir / f".partial-{uuid.uuid4().hex[:8]}"
        self._enforce(partial, incoming=size + 64 * 1024, action="freeze")  # the copy plus metadata; nothing is created yet
        created_samples = self._make_dir(self.samples_dir)
        scratch_root = self.root / "tmp"  # ProductRunner.check_schema creates it; a refusal must not leave it behind
        had_scratch_root = os.path.lexists(scratch_root)
        try:
            try:
                partial.mkdir()
            except FileNotFoundError:  # a concurrent freeze took away the empty samples/ it had made
                created_samples = self._make_dir(self.samples_dir) or created_samples
                partial.mkdir()
            try:
                shutil.copyfile(info.db_path, partial / DB_NAME)
            except OSError as exc:
                raise _io_error("copy into sample library", info.db_path, exc) from exc
            if sha256_file(partial / DB_NAME) != (sha256, size):
                raise DbEntryError("hash_mismatch", "copy differs from the source database", path=partial / DB_NAME, size_bytes=size)
            metadata = build_metadata(
                version=version, kind=kind, schema_version=markers[0], sha256=sha256, size_bytes=size,
                counts=row_counts(partial / DB_NAME), supplied=meta, fixture=fixture,
            )
            write_metadata(partial / META_NAME, metadata)
            report = self._verify_dir(partial, version, expect_sha256=None, check_product=check_product)
            for item in partial.iterdir():
                os.chmod(item, stat.S_IREAD)
            self._enforce(final, action="freeze (after copy)")
            try:
                os.replace(partial, final)
            except OSError as exc:
                raise _io_error("publish sample directory", partial, exc) from exc
        except BaseException as exc:
            failures = remove_tree(partial)
            for made, directory in ((created_samples, self.samples_dir), (not had_scratch_root, scratch_root)):
                if made:
                    try:
                        directory.rmdir()  # only a directory this call made, and only while it is still empty
                    except OSError:
                        pass
            if failures and isinstance(exc, DbEntryError):
                exc.details["cleanup_failures"] = failures
            raise
        report.update(
            sample_dir=str(final), db_path=str(final / DB_NAME), os_readonly=not os.access(final / DB_NAME, os.W_OK)
        )
        return report

    def build_sample(
        self, version: str, fixture_path: Path | str, *, kind: str = "manual_fixture",
        meta: dict[str, Any] | None = None, check_product: bool = True,
    ) -> dict[str, Any]:
        """Product schema via ``init-db``, hand-written fixture rows, then an immutable sample version."""

        if self.sample_dir(version).exists():
            raise DbEntryError("version_exists", "a sample version is immutable; publish a new version name", path=self.sample_dir(version))
        fixture = read_fixture(Path(fixture_path))
        _check_metadata(version, kind, meta, fixture)
        with self.isolated(None) as info:
            counts = load_fixture(info.db_path, fixture)
            report = self.freeze(info, version, kind=kind, meta=meta, fixture=fixture, check_product=check_product)
        report["loaded_rows"] = counts
        return report

    # ---- isolated test databases ---------------------------------------------

    @staticmethod
    def _new_run_id() -> str:
        return f"r{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{os.getpid()}-{uuid.uuid4().hex[:6]}"

    def _paths(self, run_id: str, origin: dict[str, Any]) -> RunInfo:
        run_dir = self.runs_dir / run_id
        data_dir = run_dir / "data"
        return RunInfo(
            run_id=run_id, run_dir=run_dir, data_dir=data_dir, db_path=data_dir / "stock.db", raw_dir=data_dir / "raw",
            tmp_dir=run_dir / "tmp", stock_env=stock_env_for(data_dir), origin=origin,
        )

    def _populate(self, info: RunInfo) -> None:
        info.raw_dir.mkdir(parents=True, exist_ok=True)
        info.tmp_dir.mkdir(parents=True, exist_ok=True)
        origin = info.origin
        if origin["kind"] == "sample":
            source = self.sample_dir(origin["version"]) / DB_NAME
            try:
                shutil.copyfile(source, info.db_path)  # copyfile: the copy is writable, not read-only like the sample
            except OSError as exc:
                raise _io_error("copy sample into isolated run", source, exc) from exc
            copied = sha256_file(info.db_path)
            if copied[0] != origin["sha256"]:
                raise DbEntryError(
                    "hash_mismatch", f"isolated copy sha256 {copied[0]} differs from sample {origin['sha256']}",
                    path=info.db_path, size_bytes=copied[1],
                )
        else:
            self.runner.init_db(info.data_dir, info.tmp_dir, info.run_dir)
            if not info.db_path.is_file():
                raise DbEntryError("product_failed", "init-db reported success but created no database", path=info.db_path)
        self._enforce(info.run_dir, action="populate isolated run")

    def isolate(
        self, sample_version: str | None = None, *, run_id: str | None = None,
        check_product: bool = False, expect_sha256: str | None = None,
    ) -> RunInfo:
        """A fresh, writable database at its own path, copied from a verified sample or built by ``init-db``."""

        run_id = check_name(run_id, "run id") if run_id else self._new_run_id()
        origin: dict[str, Any] = {"kind": "empty"}
        if sample_version is not None:
            report = self.verify(sample_version, expect_sha256=expect_sha256, check_product=check_product)
            origin = {"kind": "sample", "version": sample_version, "sha256": report["sha256"]}
            self._enforce(self.runs_dir / run_id, incoming=report["size_bytes"], action="isolate")
        info = self._paths(run_id, origin)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        try:
            info.run_dir.mkdir()
        except FileExistsError as exc:
            raise DbEntryError("run_exists", f"run {run_id!r} already exists; run ids are never reused", path=info.run_dir) from exc
        try:
            marker = {"marker_schema": RUN_MARKER_SCHEMA, "run_id": run_id, "origin": origin, "root": str(self.root)}
            (info.run_dir / RUN_MARKER).write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
            self._populate(info)
            validate_stock_env(info.stock_env, allowed_root=info.run_dir, forbidden=(self.samples_dir,), protected=self.protected)
        except BaseException as exc:
            failures = remove_tree(info.run_dir)
            if failures and isinstance(exc, DbEntryError):
                exc.details["cleanup_failures"] = failures
            raise
        return info

    def _load_run(self, run_id: str) -> RunInfo:
        run_dir = self.runs_dir / check_name(run_id, "run id")
        if not run_dir.is_dir():
            raise DbEntryError("run_not_found", f"no run {run_id!r} under {self.runs_dir}", path=run_dir)
        if is_link_or_reparse(run_dir):
            raise DbEntryError("reparse_point", "run directory is a link or reparse point", path=run_dir)
        try:
            marker = json.loads((run_dir / RUN_MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DbEntryError("not_a_run_dir", f"missing or unreadable {RUN_MARKER}; refusing to treat it as a run", path=run_dir) from exc
        if marker.get("run_id") != run_id or marker.get("marker_schema") != RUN_MARKER_SCHEMA or "origin" not in marker:
            raise DbEntryError("not_a_run_dir", f"{RUN_MARKER} does not describe run {run_id!r}", path=run_dir)
        return self._paths(run_id, marker["origin"])

    def reset(self, run_id: str) -> RunInfo:
        """Return a run to its pristine state (verified sample copy or fresh ``init-db``) at the same path."""

        info = self._load_run(run_id)
        if info.origin["kind"] == "sample":
            self.verify(info.origin["version"], expect_sha256=info.origin["sha256"], check_product=False)
        remove_tree_or_raise(info.data_dir)
        remove_tree_or_raise(info.tmp_dir)
        self._populate(info)
        return info

    def cleanup(self, run_id: str) -> dict[str, Any]:
        """Remove a run. The marker goes last, so a failed cleanup can be retried by run id."""

        info = self._load_run(run_id)
        size = tree_size(info.run_dir, strict=False)
        failures = []
        try:
            children = sorted(info.run_dir.iterdir())
        except FileNotFoundError as exc:  # another process finished removing it first
            raise DbEntryError("run_not_found", f"run {run_id!r} was removed while cleaning up", path=info.run_dir) from exc
        for child in children:
            if child.name != RUN_MARKER:
                failures += remove_tree(child)
        if not failures:
            failures = remove_tree(info.run_dir)
        if failures:
            raise CleanupError(info.run_dir, failures, tree_size(info.run_dir, strict=False))
        return {"path": str(info.run_dir), "removed_bytes": size}

    @contextmanager
    def isolated(self, sample_version: str | None = None, **kwargs: Any) -> Iterator[RunInfo]:
        """``isolate`` for the duration of the block; the run is removed on success and failure alike."""

        info = self.isolate(sample_version, **kwargs)
        try:
            yield info
        except BaseException as exc:
            if info.run_dir.exists():
                try:
                    self.cleanup(info.run_id)
                except CleanupError as cleanup_error:
                    exc.add_note(f"cleanup also failed: {cleanup_error}")
            raise
        else:
            if info.run_dir.exists():
                self.cleanup(info.run_id)

    # ---- readback, fixtures, commands ------------------------------------------

    def load_into_run(self, run_id: str, fixture_path: Path | str) -> dict[str, int]:
        return load_fixture(self._load_run(run_id).db_path, read_fixture(Path(fixture_path)))

    def read_table(self, table: str, *, run_id: str | None = None, version: str | None = None, limit: int = 100) -> list[dict]:
        if (run_id is None) == (version is None):
            raise DbEntryError("invalid_argument", "give exactly one of run_id or version")
        if not IDENTIFIER_RE.fullmatch(table):
            raise DbEntryError("invalid_argument", f"unusable table name {table!r}")
        db_path = self._load_run(run_id).db_path if run_id else self.sample_dir(version) / DB_NAME
        if not db_path.is_file():
            raise DbEntryError("version_missing" if version else "not_found", "database file not found", path=db_path)
        connection = open_readonly(db_path)
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid LIMIT ?', (int(limit),))
            return [dict(row) for row in cursor]
        except sqlite3.Error as exc:
            raise DbEntryError("invalid_argument", f"cannot read {table!r}: {exc}", path=db_path) from exc
        finally:
            connection.close()

    def run_command(
        self, argv: list[str], *, sample_version: str | None = None, check_product: bool = False,
        cwd: Path | str | None = None, before_run: Callable[[dict[str, str]], None] | None = None,
    ) -> dict[str, Any]:
        """Run ``argv`` with the three STOCK_* of a fresh isolated run; the run is removed afterwards."""

        outcome: dict[str, Any] = {}
        try:
            with self.isolated(sample_version, check_product=check_product) as info:
                readback = validate_stock_env(
                    info.stock_env, allowed_root=info.run_dir, forbidden=(self.samples_dir,), protected=self.protected
                )
                if before_run:
                    before_run(readback)
                env = build_child_env(info.stock_env, info.tmp_dir)
                try:
                    proc = subprocess.run(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
                except OSError as exc:  # the operating system's message does not always name the program
                    raise DbEntryError(
                        "io_error", f"cannot start {argv[0]!r}: {type(exc).__name__}: {exc}", path=argv[0]
                    ) from exc
                outcome = {"exit_code": proc.returncode, "run_id": info.run_id, "stock_env_readback": readback}
        except CleanupError as exc:
            exc.details["command_exit_code"] = outcome.get("exit_code")
            raise
        outcome["cleaned"] = True
        return outcome
