"""Sample-library file formats: hashing, metadata, read-only opening, fixtures.

Only the standard library is used here; nothing imports the product, so these
helpers are safe to run before any ``STOCK_*`` variable has been set.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DbEntryError

DB_NAME = "sample.db"
META_NAME = "metadata.json"
METADATA_SCHEMA = 1
KINDS = ("manual_fixture", "real_sample")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Whole-value placeholders, compared after ``_placeholder_key`` (NFKC, casefold, letters and digits only):
# "N/A", "n.a.", "Not Applicable", "not_applicable", "-", "？" and "　" all reduce to an entry here or to "".
PLACEHOLDERS = frozenset({
    "", "unknown", "notapplicable", "na", "notavailable", "nan", "none", "null", "nil", "undefined", "tbd", "tba", "todo",
    "無", "未知", "不適用", "待定", "待補", "未定",
})
# Fields every metadata file carries (contract: docs/development-baseline/README.md).
META_KEYS = (
    "metadata_schema", "sample_version", "kind", "source_rights", "data_dates", "acquired_at",
    "publication_time", "schema_version", "sampling_rule", "sha256", "size_bytes", "created_at",
    "row_counts", "provenance",
)
# A real sample must state rights, dates, acquisition time and sampling rule; unknowns are not invented.
REAL_SAMPLE_REQUIRED = ("source_rights", "data_dates", "acquired_at", "sampling_rule")


def check_name(value: str, what: str) -> str:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise DbEntryError(
            "invalid_argument",
            f"{what} {value!r} must match {VERSION_RE.pattern} (no path separators or '..')",
        )
    return value


def _placeholder_key(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def is_unset(value: Any) -> bool:
    """True when a stated ``real_sample`` value says nothing.

    Strings are judged as a whole after ``_placeholder_key``; a value that merely starts with a placeholder
    ("not-applicable: …") or any other text is accepted, because the tool does not judge meaning. Containers
    are unset when empty or when any nested value is unset. Numbers and booleans are not judged.
    """

    if value is None:
        return True
    if isinstance(value, str):
        return _placeholder_key(value) in PLACEHOLDERS
    if isinstance(value, dict):
        return not value or any(is_unset(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return not value or any(is_unset(item) for item in value)
    return False


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-only: URI ``mode=ro`` plus ``PRAGMA query_only=ON``."""

    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1.0)
    connection.execute("PRAGMA query_only=ON")
    return connection


def read_alembic_markers(path: Path) -> list[str]:
    with closing(open_readonly(path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        if "alembic_version" not in tables:
            return []
        return sorted(row[0] for row in connection.execute("SELECT version_num FROM alembic_version"))


def row_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with closing(open_readonly(path)) as connection:
        names = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'alembic_version' ORDER BY name"
            )
        ]
        for name in names:
            count = connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            if count:
                counts[name] = count
    return counts


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_metadata(
    *, version: str, kind: str, schema_version: str, sha256: str, size_bytes: int,
    counts: dict[str, int], supplied: dict[str, Any] | None, fixture: dict[str, Any] | None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise DbEntryError("invalid_argument", f"kind {kind!r} must be one of {KINDS}")
    supplied = dict(supplied or {})
    if kind == "real_sample":
        missing = [key for key in REAL_SAMPLE_REQUIRED if is_unset(supplied.get(key))]
        if missing:
            raise DbEntryError(
                "metadata_invalid",
                f"real_sample metadata must state {missing}; unknown values are not invented",
            )
        stated = {key: supplied[key] for key in REAL_SAMPLE_REQUIRED}
        provenance = supplied.get("provenance", "unknown")
    else:
        stated = {
            "source_rights": "not-applicable: hand-written fixture, no external source",
            "data_dates": (fixture or {}).get("data_dates", "unknown"),
            "acquired_at": "not-applicable",
            "sampling_rule": "hand-written rows chosen to exercise the product schema; not market data",
        }
        provenance = {"fixture": (fixture or {}).get("provenance")}
    return {
        "metadata_schema": METADATA_SCHEMA,
        "sample_version": version,
        "kind": kind,
        **stated,
        # Publication time / point-in-time status stays unknown unless stated; never inferred.
        "publication_time": supplied.get("publication_time", "unknown"),
        "schema_version": schema_version,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "created_at": utc_now(),
        "row_counts": counts,
        "provenance": provenance,
    }


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def read_metadata(path: Path) -> dict[str, Any]:
    try:
        metadata = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DbEntryError("metadata_invalid", f"cannot read metadata: {exc}", path=path) from exc
    if not isinstance(metadata, dict):
        raise DbEntryError("metadata_invalid", "metadata must be a JSON object", path=path)
    missing = [key for key in META_KEYS if key not in metadata]
    if missing:
        raise DbEntryError("metadata_invalid", f"metadata lacks keys {missing}", path=path)
    if metadata["metadata_schema"] != METADATA_SCHEMA:
        raise DbEntryError(
            "metadata_invalid",
            f"unsupported metadata_schema {metadata['metadata_schema']!r}; this tool reads {METADATA_SCHEMA}",
            path=path,
        )
    if metadata["kind"] not in KINDS:
        raise DbEntryError("metadata_invalid", f"unknown kind {metadata['kind']!r}", path=path)
    return metadata


def read_fixture(path: Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        fixture = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise DbEntryError("fixture_invalid", f"cannot read fixture: {exc}", path=path) from exc
    if not isinstance(fixture, dict) or not isinstance(fixture.get("tables"), list):
        raise DbEntryError("fixture_invalid", "fixture must be an object with a 'tables' list", path=path)
    fixture["provenance"] = {"name": Path(path).name, "sha256": hashlib.sha256(raw).hexdigest()}
    return fixture


def load_fixture(db_path: Path, fixture: dict[str, Any]) -> dict[str, int]:
    """Insert hand-written rows in one transaction with foreign keys enforced.

    Table and column names must exist in the database; any problem rolls the
    whole fixture back.
    """

    inserted: dict[str, int] = {}
    if not Path(db_path).is_file():
        raise DbEntryError("not_found", "database file does not exist; fixtures never create one", path=db_path)
    # mode=rw never creates a missing file.
    connection = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=rw", uri=True, timeout=5.0, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        try:
            for position, block in enumerate(fixture["tables"]):
                table = block.get("table") if isinstance(block, dict) else None
                rows = block.get("rows") if isinstance(block, dict) else None
                if not isinstance(table, str) or not isinstance(rows, list):
                    raise DbEntryError("fixture_invalid", f"tables[{position}] needs 'table' and a 'rows' list", path=db_path)
                if not IDENTIFIER_RE.fullmatch(table) or table.startswith("sqlite_"):
                    raise DbEntryError("fixture_invalid", f"unusable table name {table!r}", path=db_path, table=table)
                columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
                if not columns:
                    raise DbEntryError("fixture_invalid", f"unknown table {table!r}", path=db_path, table=table)
                for index, row in enumerate(rows):
                    if not isinstance(row, dict) or not row:
                        raise DbEntryError("fixture_invalid", f"{table}[{index}] must be a non-empty object", path=db_path, table=table)
                    unknown = sorted(set(row) - set(columns))
                    if unknown:
                        raise DbEntryError("fixture_invalid", f"{table}[{index}] has unknown columns {unknown}", path=db_path, table=table)
                    names = ", ".join(f'"{name}"' for name in row)
                    marks = ", ".join("?" for _ in row)
                    connection.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', list(row.values()))
                inserted[table] = inserted.get(table, 0) + len(rows)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise DbEntryError("fixture_invalid", f"foreign key violations: {violations[:3]}", path=db_path)
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
    except sqlite3.Error as exc:
        raise DbEntryError("fixture_invalid", f"rejected by SQLite: {exc}", path=db_path) from exc
    finally:
        connection.close()
    return inserted
