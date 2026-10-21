"""#61 regression: migrations and ``init-db`` on DB paths with ConfigParser-special characters.

Alembic's ``Config.set_main_option`` passes values to ``ConfigParser.set``,
which rejects a bare ``%`` (``ValueError: invalid interpolation syntax``) and
expands ``%(name)s`` tokens.  Every case below builds a schema-only database
in a ``tempfile`` directory whose name carries such characters, then compares
its ``sqlite_master`` objects and Alembic revision with an ordinary-path
database.  Nothing is fetched, no fixture rows are loaded, and neither the
daily database nor the repository ``data`` directory is opened.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator

import pytest
from alembic import command as alembic_command
from sqlalchemy import Engine, create_engine

from app import migrations
from app.db import enable_sqlite_foreign_keys


BACKEND_ROOT = Path(__file__).resolve().parents[1]

# One path component per case, used for both the directory and the DB file stem.
SPECIAL_NAMES: dict[str, str] = {
    "percent": "pct%dir",
    "double_percent": "a%%b",
    "interpolation_token": "x%(here)s%(missing)s",
    "dollar": "dol$lar${x}",
    "semicolon_hash": "semi;colon#hash",
    "equals_brackets": "k=v[section]",
    "space": "with space",
    "non_ascii": "資料庫é",
    "combined": "p%(x)s%d$;#=[z] 資",
}
if os.name != "nt":  # ':' cannot appear in a Windows path component
    SPECIAL_NAMES["colon"] = "k:v%"

special_names = pytest.mark.parametrize(
    "name", list(SPECIAL_NAMES.values()), ids=list(SPECIAL_NAMES)
)


def _open_engine(db_path: Path) -> Engine:
    """Build an engine the way ``app.db`` does, for an isolated path."""

    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False}
    )
    enable_sqlite_foreign_keys(engine)
    return engine


def _migrate(db_path: Path, *, use_fallback: bool = False) -> None:
    engine = _open_engine(db_path)
    try:
        if use_fallback:
            # A missing alembic.ini routes upgrade_database to its local fallback.
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(
                    migrations, "ALEMBIC_CONFIG_PATH", db_path.parent / "absent.ini"
                )
                migrations.upgrade_database(engine)
        else:
            migrations.upgrade_database(engine)
    finally:
        engine.dispose()


def _schema_snapshot(db_path: Path) -> dict[str, Any]:
    assert db_path.is_file(), f"migration did not create {db_path}"
    with closing(sqlite3.connect(str(db_path))) as connection:
        objects = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        has_version_table = any(row[1] == "alembic_version" for row in objects)
        versions = (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if has_version_table
            else None
        )
    tables = {name for kind, name, _tbl, _sql in objects if kind == "table"}
    assert {"instruments", "market_bars"} <= tables, "snapshot lacks the product schema"
    return {"objects": objects, "versions": versions}


def _special_db(root: Path, name: str) -> Path:
    directory = root / name
    db_path = directory / f"{name}.db"
    # Past MAX_PATH sqlite3 reports only "unable to open database file".
    assert len(str(db_path)) < 240, f"temporary root is too long for this test: {root}"
    directory.mkdir()
    return db_path


@pytest.fixture()
def isolated_root() -> Iterator[Path]:
    # Explicit tempfile directory: removed when the test ends, engines are
    # disposed first so Windows can delete the SQLite files.
    with tempfile.TemporaryDirectory(prefix="stock-init-db-special-") as directory:
        yield Path(directory)


@pytest.fixture(scope="module")
def plain_schema() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stock-init-db-plain-") as directory:
        db_path = Path(directory) / "plain.db"
        _migrate(db_path)
        snapshot = _schema_snapshot(db_path)
    assert snapshot["versions"] and len(snapshot["versions"]) == 1
    return snapshot


@pytest.fixture(scope="module")
def plain_fallback_schema() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="stock-init-db-plain-fallback-"
    ) as directory:
        db_path = Path(directory) / "plain.db"
        _migrate(db_path, use_fallback=True)
        snapshot = _schema_snapshot(db_path)
    assert snapshot["versions"] is None, "fallback baseline unexpectedly ran Alembic"
    return snapshot


class _UpgradeSpy:
    """Capture the Config ``upgrade_database`` builds; optionally drop its shared engine."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *, drop_connection: bool = False
    ) -> None:
        self.config: Any = None
        real_upgrade = alembic_command.upgrade

        def spy(config: Any, revision: str, **kwargs: Any) -> None:
            self.config = config
            if drop_connection:
                # Force env.py onto engine_from_config(), which reads sqlalchemy.url.
                config.attributes.pop("connection")
            return real_upgrade(config, revision, **kwargs)

        monkeypatch.setattr(alembic_command, "upgrade", spy)


@special_names
def test_upgrade_database_special_path_matches_plain_schema(
    name: str, isolated_root: Path, plain_schema: dict[str, Any]
) -> None:
    db_path = _special_db(isolated_root, name)

    _migrate(db_path)

    assert _schema_snapshot(db_path) == plain_schema


@special_names
def test_upgrade_database_fallback_special_path_matches_plain_schema(
    name: str, isolated_root: Path, plain_fallback_schema: dict[str, Any]
) -> None:
    db_path = _special_db(isolated_root, name)

    _migrate(db_path, use_fallback=True)

    assert _schema_snapshot(db_path) == plain_fallback_schema


@special_names
def test_config_options_read_back_verbatim(
    name: str, isolated_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _special_db(isolated_root, name)
    spy = _UpgradeSpy(monkeypatch)

    _migrate(db_path)

    expected_url = f"sqlite:///{db_path.as_posix()}"
    expected_location = str(migrations.ALEMBIC_CONFIG_PATH.parent / "alembic")
    config = spy.config
    # env.py reads the URL with get_main_option (offline) and get_section
    # (engine_from_config); both must return the path, not an interpolated one.
    assert config.get_main_option("sqlalchemy.url") == expected_url
    assert (
        config.get_section(config.config_ini_section)["sqlalchemy.url"] == expected_url
    )
    assert config.get_main_option("script_location") == expected_location


@special_names
def test_upgrade_through_config_url_special_path_matches_plain_schema(
    name: str,
    isolated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    plain_schema: dict[str, Any],
) -> None:
    db_path = _special_db(isolated_root, name)
    spy = _UpgradeSpy(monkeypatch, drop_connection=True)

    _migrate(db_path)

    assert spy.config is not None
    assert "connection" not in spy.config.attributes
    assert _schema_snapshot(db_path) == plain_schema


@special_names
def test_cli_init_db_special_path_matches_plain_schema(
    name: str, isolated_root: Path, plain_schema: dict[str, Any]
) -> None:
    db_path = _special_db(isolated_root, name)
    raw_dir = db_path.parent / "raw"
    # Every STOCK_* location points into the temporary directory so the
    # subprocess cannot fall back to the repository or daily data paths.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("STOCK_")
    }
    env.update(
        STOCK_DATA_DIR=str(db_path.parent),
        STOCK_RAW_DIR=str(raw_dir),
        STOCK_DB_PATH=str(db_path),
        PYTHONDONTWRITEBYTECODE="1",
    )

    completed = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "worker.cli", "init-db"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert json.loads(completed.stdout) == {"status": "success"}
    assert _schema_snapshot(db_path) == plain_schema
