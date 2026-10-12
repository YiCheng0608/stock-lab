"""Path guards, tree sizes and bounded removal for the test-database entry."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import Iterable

from .errors import CleanupError, DbEntryError

REPO_ROOT = Path(__file__).resolve().parents[2]
# "50 MB" is authorized per task; the decimal reading is the smaller one.
DEFAULT_MAX_TOTAL_BYTES = 50 * 1000 * 1000
STOCK_VARS = ("STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_VANISHED = (FileNotFoundError, NotADirectoryError)
# Windows reports an entry that another process is deleting as "access denied". Give it a short, bounded
# moment to disappear or become readable before the denial is treated as real.
_TRANSIENT_RETRIES = 20
_TRANSIENT_DELAY = 0.01


def is_within(child: Path | str, parent: Path | str) -> bool:
    c = os.path.normcase(str(Path(child).resolve()))
    p = os.path.normcase(str(Path(parent).resolve()))
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives
        return False


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def is_link_or_reparse(path: Path | str) -> bool:
    try:
        return _is_link(os.lstat(path))
    except OSError:
        return False


def _list_dir(path: Path) -> list[Path]:
    with os.scandir(path) as entries:
        return [Path(entry.path) for entry in entries]


def _observe(operation, path: Path):
    """Run ``operation(path)`` on an entry that other processes may be deleting.

    Returns ``(True, result)``, or ``(False, None)`` once the entry is gone. A
    denial that outlasts the retry window is a real error, raised as io_error
    with the path; every other error propagates unchanged.
    """

    for attempt in range(_TRANSIENT_RETRIES + 1):
        try:
            return True, operation(path)
        except _VANISHED:
            return False, None
        except PermissionError as exc:
            if attempt == _TRANSIENT_RETRIES:
                raise DbEntryError(
                    "io_error",
                    f"{type(exc).__name__}: {exc} (still denied after {_TRANSIENT_RETRIES} retries of {_TRANSIENT_DELAY}s)",
                    path=path,
                ) from exc
            time.sleep(_TRANSIENT_DELAY)


def product_checkout_of(path: Path | str) -> Path | None:
    """Return the product checkout containing ``path`` (a dir with backend/app/config.py)."""

    current = Path(path).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "backend" / "app" / "config.py").is_file():
            return candidate
    return None


def inherited_protected_paths(environ: dict[str, str] | None = None) -> tuple[Path, ...]:
    """The STOCK_* locations this process inherited: possibly the daily database."""

    environ = os.environ if environ is None else environ
    found = []
    for name in STOCK_VARS:
        value = environ.get(name)
        if value and Path(value).is_absolute():
            found.append(Path(value).resolve())
    return tuple(found)


def forbidden_reason(path: Path | str, protected: Iterable[Path | str] = ()) -> str | None:
    """Why ``path`` must never be a test-database location, or None when it may be."""

    given = Path(path)
    if not given.is_absolute():
        return "path must be absolute"
    if ".." in given.parts:
        return "path must not contain '..'"
    resolved = given.resolve()
    checkout = product_checkout_of(resolved)
    if checkout is not None:
        return f"inside the product checkout {checkout} (repo data/.local and the daily database live there)"
    lowered = [os.path.normcase(part) for part in resolved.parts]
    if any(a == ".local" and b == "data" for a, b in zip(lowered, lowered[1:])):
        return "inside a .local/data directory (daily database location)"
    for guarded in protected:
        if is_within(resolved, guarded):
            return f"equals or is inside the inherited STOCK_* location {Path(guarded)}"
    return None


def assert_allowed_target(path: Path | str, *, role: str, protected: Iterable[Path | str] = ()) -> Path:
    reason = forbidden_reason(path, protected)
    if reason:
        raise DbEntryError("forbidden_target", f"{role}: {reason}", path=path)
    return Path(path).resolve()


def tree_size(path: Path | str, *, strict: bool = True) -> int:
    """Sum of file sizes under ``path``; links are never followed.

    ``strict`` refuses a link or reparse point (quota accounting cannot trust
    what it cannot see); otherwise such entries count as 0 bytes. An entry that
    another process removes while it is being measured counts as already gone,
    so concurrent cleanup never interrupts accounting.
    """

    total = 0
    stack = [Path(path)]
    while stack:
        current = stack.pop()
        found, info = _observe(os.lstat, current)
        if not found:
            continue
        if _is_link(info):
            if strict:
                raise DbEntryError("reparse_point", "link or reparse point found while sizing", path=current)
            continue
        if stat.S_ISDIR(info.st_mode):
            found, children = _observe(_list_dir, current)
            if found:
                stack.extend(children)
        else:
            total += info.st_size
    return total


def remove_tree(path: Path | str) -> list[dict]:
    """Remove ``path`` bottom-up without following links; return every failure.

    Read-only files (the sample library) are made writable first. A reparse
    point is never entered or removed. Nothing is retried, and an entry that
    another process already removed counts as removed.
    """

    failures: list[dict] = []

    def fail(item: Path, exc: BaseException | str) -> None:
        try:
            size = tree_size(item, strict=False)
        except (OSError, DbEntryError):
            size = 0
        reason = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
        failures.append({"path": str(item), "size_bytes": size, "reason": reason})

    def remove(item: Path) -> None:
        if not os.path.lexists(item):
            return
        if is_link_or_reparse(item):
            fail(item, "refused to remove a link or reparse point")
            return
        if item.is_dir():
            before = len(failures)
            try:
                children = _list_dir(item)
            except _VANISHED:
                return
            except OSError as exc:
                fail(item, exc)
                return
            for child in children:
                remove(child)
            if len(failures) == before:
                try:
                    os.rmdir(item)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    fail(item, exc)
            return
        try:
            try:
                os.remove(item)
            except PermissionError:
                os.chmod(item, stat.S_IWRITE)
                os.remove(item)
        except FileNotFoundError:
            pass
        except OSError as exc:
            fail(item, exc)

    remove(Path(path))
    return failures


def remove_tree_or_raise(path: Path | str) -> None:
    failures = remove_tree(path)
    if failures:
        raise CleanupError(path, failures, tree_size(path, strict=False))
