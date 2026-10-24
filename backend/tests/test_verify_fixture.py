"""The verify-stock-lab fixture database (Issue #241).

tools/verify/fixture_db.py builds the database in a temporary directory in a
separate process (it points STOCK_* at that directory before importing app).
The schema checks compare tools/verify/fixture_data.py with the Alembic head;
the API checks call the five main pages' endpoints on the built database and
compare with fixture_data.EXPECTED.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.database_readiness import check_database_readiness
from app.db import enable_sqlite_foreign_keys
from app.migration_revisions import REVISIONS
from app.migrations import upgrade_database

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "tools" / "verify"
FEATURES = ROOT / ".claude" / "skills" / "verify-stock-lab" / "features"
PAGES = ("today", "news", "themes", "stocks", "actions")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, VERIFY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture_data = _load("fixture_data")
fixture_db = _load("fixture_db")


def _build(dest: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-B", str(VERIFY / "fixture_db.py"), "--dest", str(dest)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    dest = tmp_path_factory.mktemp("fixture")
    return dest / fixture_db.DB_NAME, _build(dest)


# ---- schema sync ----


def _head_columns(path: Path, extra_sql: str | None = None) -> dict[str, list[str]]:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    with engine.begin() as connection:
        if extra_sql:
            connection.exec_driver_sql(extra_sql)
        tables = [
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        head = {
            table: [
                row[1]
                for row in connection.exec_driver_sql(f'PRAGMA table_info("{table}")')
            ]
            for table in tables
        }
    engine.dispose()
    return head


def schema_problems(
    head: dict[str, list[str]],
    tables: dict[str, list[dict]],
    empty: dict[str, dict[str, str]],
    omitted: dict[str, str],
) -> list[str]:
    """Every way the fixture definition can drift from the head schema."""

    problems = []
    for table in sorted(set(tables) | set(empty) | set(omitted)):
        if table not in head:
            problems.append(f"{table}: table is not in the head schema")
    for table, columns in sorted(head.items()):
        rows = tables.get(table) or []
        if not rows:
            if table not in omitted:
                problems.append(
                    f"{table}: head table has no fixture rows and is not in OMITTED_TABLES"
                )
            continue
        if table in omitted:
            problems.append(f"{table}: in OMITTED_TABLES but has fixture rows")
        left_empty = empty.get(table, {})
        for column in sorted(set(left_empty) - set(columns)):
            problems.append(
                f"{table}.{column}: in INTENTIONALLY_EMPTY but not in the head schema"
            )
        written = set().union(*(row.keys() for row in rows))
        for column in sorted(written - set(columns)):
            problems.append(
                f"{table}.{column}: fixture writes a column the head schema does not have"
            )
        for column in columns:
            if column in left_empty:
                if column in written:
                    problems.append(
                        f"{table}.{column}: in INTENTIONALLY_EMPTY but a fixture row writes it"
                    )
                continue
            missing = sum(column not in row for row in rows)
            if missing:
                problems.append(
                    f"{table}.{column}: head column missing from {missing} fixture row(s) "
                    "and not in INTENTIONALLY_EMPTY"
                )
            elif all(row[column] is None for row in rows):
                problems.append(
                    f"{table}.{column}: every fixture row writes null; list it in INTENTIONALLY_EMPTY"
                )
    return problems


def _problems(head, tables=None):
    return schema_problems(
        head,
        fixture_data.TABLES if tables is None else tables,
        fixture_data.INTENTIONALLY_EMPTY,
        fixture_data.OMITTED_TABLES,
    )


def test_fixture_definition_matches_the_head_schema(tmp_path):
    assert _problems(_head_columns(tmp_path / "head.db")) == []


def test_a_head_column_the_fixture_does_not_write_fails(tmp_path):
    head = _head_columns(
        tmp_path / "head.db", "ALTER TABLE instruments ADD COLUMN isin VARCHAR(12)"
    )
    assert _problems(head) == [
        "instruments.isin: head column missing from 9 fixture row(s) "
        "and not in INTENTIONALLY_EMPTY"
    ]


def test_a_column_removed_from_the_fixture_fails(tmp_path):
    tables = copy.deepcopy(fixture_data.TABLES)
    for row in tables["news_items"]:
        del row["source_name"]
    assert _problems(_head_columns(tmp_path / "head.db"), tables) == [
        "news_items.source_name: head column missing from 6 fixture row(s) "
        "and not in INTENTIONALLY_EMPTY"
    ]


def test_a_column_the_head_does_not_have_fails(tmp_path):
    tables = copy.deepcopy(fixture_data.TABLES)
    tables["signals"][0]["win_rate"] = 0.6
    assert _problems(_head_columns(tmp_path / "head.db"), tables) == [
        "signals.win_rate: fixture writes a column the head schema does not have"
    ]


def test_a_head_table_without_rows_or_reason_fails(tmp_path):
    head = _head_columns(
        tmp_path / "head.db", "CREATE TABLE broker_branches (id INTEGER PRIMARY KEY)"
    )
    assert _problems(head) == [
        "broker_branches: head table has no fixture rows and is not in OMITTED_TABLES"
    ]


# ---- build ----


def test_build_reaches_the_head_and_writes_every_defined_row(built):
    _path, summary = built
    assert summary["alembic_version"] == REVISIONS[-1]
    for table, rows in fixture_data.TABLES.items():
        assert summary["tables"][table] == len(rows), table
    for table in fixture_data.OMITTED_TABLES:
        assert summary["tables"][table] == (1 if table == "alembic_version" else 0)


def test_two_builds_are_identical(built, tmp_path):
    _path, summary = built
    assert _build(tmp_path / "again") == summary


def test_frozen_candidates_match_the_current_scorer(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(VERIFY / "freeze_candidates.py"),
            "--check",
            "--work",
            str(tmp_path / "work"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_build_refuses_a_directory_that_already_has_a_database(built):
    path, _summary = built
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(VERIFY / "fixture_db.py"),
            "--dest",
            str(path.parent),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode != 0
    assert "already exists" in result.stderr


# ---- API expectations ----


@pytest.fixture
def client(built, monkeypatch):
    path, _summary = built
    data_dir = path.parent
    monkeypatch.setenv("STOCK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("STOCK_DB_PATH", str(path))
    monkeypatch.setenv("STOCK_RAW_DIR", str(data_dir / "raw"))
    # Startup readiness runs on the fixture instead of app.db's database.
    monkeypatch.setattr(
        main_module, "check_database_readiness", lambda: check_database_readiness(path)
    )
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with factory() as db:
            yield db

    main_module.app.dependency_overrides[api_module.get_db] = override_get_db
    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        main_module.app.dependency_overrides.pop(api_module.get_db, None)
        engine.dispose()


def _mismatches(client, checks) -> list[str]:
    payloads: dict[str, object] = {}
    problems = []
    for path, json_path, expected in checks:
        if path not in payloads:
            response = client.get(f"/api/{path}")
            if response.status_code != 200:
                problems.append(f"/api/{path}: HTTP {response.status_code}")
            payloads[path] = response.json() if response.status_code == 200 else None
        if payloads[path] is None:
            continue
        actual = fixture_data.actual_for(payloads[path], json_path, expected)
        if actual != expected:
            problems.append(
                f"/api/{path} {json_path}: expected {expected!r}, got {actual!r}"
            )
    return problems


@pytest.mark.parametrize("page", PAGES)
def test_page_apis_return_the_expected_counts(client, page):
    assert _mismatches(client, fixture_data.EXPECTED[page]) == []


def test_api_reads_leave_the_fixture_unchanged(built, client):
    path, summary = built
    for page in PAGES:
        _mismatches(client, fixture_data.EXPECTED[page])
    assert fixture_db.summarize(path) == summary


def _feature_endpoints(page_file: str) -> list[str]:
    text = (FEATURES / page_file).read_text(encoding="utf-8")
    section = text.split("## API", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `[^`]+` \| `(/[^`]+)`", section, flags=re.M)


@pytest.mark.parametrize(
    ("page", "page_file"),
    [
        ("today", "today.md"),
        ("news", "news.md"),
        ("themes", "themes.md"),
        ("stocks", "stocks.md"),
        ("actions", "actions.md"),
    ],
)
def test_expectations_cover_every_endpoint_of_the_page(page, page_file):
    endpoints = _feature_endpoints(page_file)
    assert endpoints, page_file
    checked = {
        f"/{path}" for path, _json_path, _expected in fixture_data.EXPECTED[page]
    }
    uncovered = []
    for template in endpoints:
        pattern = "".join(
            "[^/?&]+" if part.startswith("<") else re.escape(part)
            for part in re.split(r"(<[^>]+>)", template)
        )
        if not any(re.fullmatch(pattern, path) for path in checked):
            uncovered.append(template)
    assert uncovered == []


def test_expected_pages_are_the_five_main_pages():
    assert tuple(fixture_data.EXPECTED) == PAGES
