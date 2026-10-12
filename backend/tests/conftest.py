"""Test-process isolation for filesystem-backed application configuration.

The application creates ``data/raw`` when ``app.config`` is imported.  Set
the environment before pytest imports any test module so an adapter fixture
can never write official payloads into the repository's production data
directory.  Individual tests may still monkeypatch ``worker.sources.RAW_DIR``
to their own ``tmp_path`` when they need to inspect a capture.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="taiwan-stock-research-tests-"))
_TEST_DATA_DIR = _TEST_ROOT / "data"
_TEST_RAW_DIR = _TEST_DATA_DIR / "raw"

# Modules written as standalone runners.  They install process-wide audit hooks,
# read argv or ``__main__`` while importing, or assert that conftest and ``app``
# were never imported, so pytest must not import them.  Run each one with its
# documented standalone command instead (docs/development-baseline/README.md).
STANDALONE_ONLY = {
    "test_share_quantity_storage.py": (
        "docs/development-baseline/README.md:290-292 (standalone, no conftest, disk cases only "
        "through the fixed root); tests/test_share_quantity_storage.py:24,148"
    ),
    "test_institutional_windows.py": (
        "docs/development-baseline/README.md:364 (--w8-only / --w8-api-only); "
        "tests/test_institutional_windows.py:30-32 read argv at import"
    ),
    "test_institutional_windows_1006.py": (
        "docs/development-baseline/README.md:374 (--worker-only / --api-only); "
        "tests/test_institutional_windows_1006.py:35 parse_args() at import, :77 audit hook"
    ),
    "test_conditional_plan_store.py": (
        "tests/test_conditional_plan_store.py:1 (standalone RAM self-tests), :42 audit hook, "
        ":80 asserts app was never imported; no README mention"
    ),
    "test_saved_price_chips_entry.py": (
        "tests/test_saved_price_chips_entry.py:39 uses __main__.ARGS; "
        "run by tools/tpex-price-api.py:504; no README filename mention"
    ),
    "test_saved_price_chips_focus.py": (
        "tests/test_saved_price_chips_focus.py:34 uses __main__.ARGS; "
        "run by tools/tpex-price-api.py:504; no README filename mention"
    ),
    "test_saved_price_chips_calendar_focus.py": (
        "tests/test_saved_price_chips_calendar_focus.py:30 uses __main__.ARGS; "
        "run by tools/tpex-price-api.py:504; no README filename mention"
    ),
    "test_saved_price_chips_scope7_focus.py": (
        "tests/test_saved_price_chips_scope7_focus.py:30 uses __main__.ARGS; "
        "run by tools/tpex-price-api.py:504; no README filename mention"
    ),
    "test_ordinary_close_source.py": (
        "tests/test_ordinary_close_source.py raises unless run with -B, installs sys.addaudithook (no sockets, "
        "no writes outside its own session directory) before importing the modules under test, reads a pinned "
        "git blob at import; run with python -I -B -X utf8 (docs/development-baseline/README.md)"
    ),
}

# Assign rather than setdefault: a developer shell may have production
# values inherited from a previous CLI/probe, and tests must override them.
os.environ["STOCK_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["STOCK_DB_PATH"] = str(_TEST_DATA_DIR / "stock.db")
os.environ["STOCK_RAW_DIR"] = str(_TEST_RAW_DIR)


class _StandaloneOnly(pytest.File):
    """A module pytest can name but never imports or runs."""

    def collect(self):
        return []


def pytest_pycollect_makemodule(module_path, parent):
    """Keep standalone runners out of pytest, including when named explicitly.

    ``collect_ignore`` and ``pytest_ignore_collect`` are bypassed for files
    given on the command line, which would import the module and let its
    import-time ``parse_args()``/assertions abort the whole collection.
    """

    if module_path.name in STANDALONE_ONLY and module_path.parent.resolve() == _TESTS_DIR:
        return _StandaloneOnly.from_parent(parent, path=module_path)
    return None


def pytest_report_header(config):
    return "standalone-only, not collected by pytest: " + ", ".join(sorted(STANDALONE_ONLY))


def pytest_configure(config):
    """Expose the session paths for diagnostics without importing app.config."""

    config._taiwan_stock_test_root = _TEST_ROOT


def pytest_unconfigure(config):
    """Remove the directory this process created; roots of other runs stay.

    A failed removal only prints a warning so it never changes the test result.
    """

    if not _TEST_ROOT.exists():
        return
    engine = getattr(sys.modules.get("app.db"), "engine", None)
    if engine is not None:
        engine.dispose()
    failures = []

    def remember(function, path, error):
        failures.append((path, error))

    shutil.rmtree(_TEST_ROOT, onexc=remember)
    for path, error in failures:
        sys.stderr.write(f"warning: could not remove {path}: {type(error).__name__}: {error}\n")


@pytest.fixture(autouse=True)
def isolate_runtime_paths(tmp_path, monkeypatch):
    """Give every test its own raw/data paths after module import as well."""

    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STOCK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("STOCK_DB_PATH", str(data_dir / "stock.db"))
    monkeypatch.setenv("STOCK_RAW_DIR", str(raw_dir))

    # ``sources.RAW_DIR`` is imported by value from app.config.  Patch both
    # modules so direct captures and any config-level consumers share the same
    # per-test directory, including tests that construct an adapter directly.
    from app import config as app_config
    import worker.sources as sources

    monkeypatch.setattr(app_config, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_config, "DB_PATH", data_dir / "stock.db")
    monkeypatch.setattr(app_config, "RAW_DIR", raw_dir)
    monkeypatch.setattr(sources, "RAW_DIR", raw_dir)
