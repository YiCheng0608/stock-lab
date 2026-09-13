"""Test-process isolation for filesystem-backed application configuration.

The application creates ``data/raw`` when ``app.config`` is imported.  Set
the environment before pytest imports any test module so an adapter fixture
can never write official payloads into the repository's production data
directory.  Individual tests may still monkeypatch ``worker.sources.RAW_DIR``
to their own ``tmp_path`` when they need to inspect a capture.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="taiwan-stock-research-tests-"))
_TEST_DATA_DIR = _TEST_ROOT / "data"
_TEST_RAW_DIR = _TEST_DATA_DIR / "raw"

# Assign rather than setdefault: a developer shell may have production
# values inherited from a previous CLI/probe, and tests must override them.
os.environ["STOCK_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["STOCK_DB_PATH"] = str(_TEST_DATA_DIR / "stock.db")
os.environ["STOCK_RAW_DIR"] = str(_TEST_RAW_DIR)


def pytest_configure(config):
    """Expose the session paths for diagnostics without importing app.config."""

    config._taiwan_stock_test_root = _TEST_ROOT


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
