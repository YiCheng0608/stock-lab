"""Immutable, explicit-path persistence for :mod:`signal_artifact`.

This store is a caller-provided foundation for B2.  It is deliberately not
registered with SQLAlchemy, Alembic, the legacy ``signals`` table, startup
initialization, or any environment-variable database path.

The database has its own ownership marker and schema.  A write consists of
one SQLite transaction containing the binding, artifact, feature references,
revision/lifecycle event, attempt, and optional run relation.  Canonical rows
are never updated in place; a later lifecycle state is an append-only revision
that must point to the previous row in the same research-core lineage.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .signal_artifact import (
    CALLER_PROVIDED_ONLY,
    SIGNAL_ARTIFACT_VERSION,
    SignalArtifact,
    SignalArtifactContractError,
    canonical_json,
    digest_json,
    digest_text,
    normalize_signal_artifact,
)


STORE_KIND = "taiwan-stock-research.signal-artifact"
SCHEMA_VERSION = 1
_META_TABLE = "signal_artifact_store_metadata"
_ARTIFACT_TABLE = "signal_artifacts"
_BINDING_TABLE = "signal_artifact_bindings"
_REF_TABLE = "signal_artifact_feature_refs"
_LIFECYCLE_TABLE = "signal_artifact_lifecycle"
_ATTEMPT_TABLE = "signal_artifact_attempts"
_RUN_TABLE = "signal_artifact_run_relations"
_OWNER_TOKEN = "signal-artifact-store-v1"
_KEY_PREFIX = "signal-artifact:v1:"
_LINEAGE_PREFIX = "signal-lineage:v1:"
_REQUIRED_TABLES = {
    _META_TABLE,
    _ARTIFACT_TABLE,
    _BINDING_TABLE,
    _REF_TABLE,
    _LIFECYCLE_TABLE,
    _ATTEMPT_TABLE,
    _RUN_TABLE,
}
_REQUIRED_TRIGGERS = {
    "signal_artifacts_immutable_update",
    "signal_artifacts_immutable_delete",
    "signal_artifacts_no_replace",
    "signal_artifact_bindings_immutable_update",
    "signal_artifact_bindings_immutable_delete",
    "signal_artifact_feature_refs_immutable_update",
    "signal_artifact_feature_refs_immutable_delete",
    "signal_artifact_feature_refs_no_replace",
    "signal_artifact_lifecycle_immutable_update",
    "signal_artifact_lifecycle_immutable_delete",
    "signal_artifact_lifecycle_no_replace",
    "signal_artifact_attempts_immutable_update",
    "signal_artifact_attempts_immutable_delete",
    "signal_artifact_attempts_no_replace",
    "signal_artifact_run_relations_immutable_update",
    "signal_artifact_run_relations_immutable_delete",
    "signal_artifact_run_relations_no_replace",
}
_REQUIRED_INDEXES = {
    "signal_artifacts_lineage_revision_unique",
    "signal_artifacts_supersedes_unique",
}


class SignalArtifactStoreError(RuntimeError):
    """Base signal-artifact persistence error."""


class ReadonlySnapshotError(SignalArtifactStoreError):
    """A stable external snapshot could not be safely read."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def snapshot_fingerprint(
    database_path: str | Path, *, expected_database_sha256: str | None = None,
) -> dict[str, Any]:
    """Preflight an existing external checkpoint without opening SQLite.

    This detects observed changes, not adversarial path races or active writers.
    All aliases (including unrelated hardlinks) are excluded in this finite API.
    """
    if expected_database_sha256 is not None and (
        not isinstance(expected_database_sha256, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", expected_database_sha256) is None
    ):
        raise ReadonlySnapshotError("invalid_expected_database_sha256")
    if not isinstance(database_path, (str, Path)):
        raise ReadonlySnapshotError("invalid_snapshot_path")
    text = str(database_path)
    path = Path(text)
    if not path.is_absolute() or text.casefold().startswith("file:") or ":memory:" in text:
        raise ReadonlySnapshotError("absolute_file_path_required")
    workspace = Path(__file__).resolve().parents[2]
    resolved = path.resolve()
    if (resolved.is_relative_to(workspace) or _path_has_protected_component(path)
            or _path_has_protected_component(resolved)):
        raise ReadonlySnapshotError("protected_snapshot_path")
    if _is_path_alias(path) or any(
        part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
        for part in (path, *path.parents)
    ):
        raise ReadonlySnapshotError("snapshot_path_alias")
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ReadonlySnapshotError("snapshot_regular_file_required")
        if before.st_nlink != 1:
            raise ReadonlySnapshotError("snapshot_path_alias")
        if any(os.path.lexists(text + suffix) for suffix in ("-wal", "-shm", "-journal")):
            raise ReadonlySnapshotError("snapshot_sidecar_present")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            header = source.read(100)
            # A checkpointed WAL file can create -wal/-shm on a nominally ro
            # open. Require rollback-mode headers as well as absent sidecars.
            if header.startswith(b"SQLite format 3\x00") and (header[18:19] == b"\x02" or header[19:20] == b"\x02"):
                raise ReadonlySnapshotError("snapshot_wal_header")
            digest.update(header)
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
    except OSError as exc:
        raise ReadonlySnapshotError("snapshot_unreadable") from exc
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ReadonlySnapshotError("snapshot_changed")
    actual = digest.hexdigest()
    if expected_database_sha256 is not None and actual != expected_database_sha256.lower():
        raise ReadonlySnapshotError("snapshot_hash_mismatch")
    return {"path": str(path), "sha256": actual, "size": after.st_size,
            "mtime_ns": after.st_mtime_ns, "sidecars": []}


def _readonly_authorizer(action: int, arg1: str | None, arg2: str | None,
                         database: str | None, source: str | None) -> int:
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() != "load_extension":
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_TRANSACTION and arg1 in {"BEGIN", "ROLLBACK", "COMMIT"}:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg1 in {
        "table_list", "table_xinfo", "index_list", "index_xinfo", "foreign_key_list",
    }:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


@contextmanager
def readonly_snapshot(database_path: str | Path, *, expected_database_sha256: str | None = None):
    """One read transaction plus file-change checks, never initialization."""
    before = snapshot_fingerprint(database_path, expected_database_sha256=expected_database_sha256)
    connection = None
    try:
        connection = sqlite3.connect(Path(database_path).as_uri() + "?mode=ro", uri=True,
                                     timeout=1.0, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_readonly_authorizer)
        connection.execute("BEGIN")
        yield connection, before
    finally:
        if connection is not None:
            connection.close()
        after = snapshot_fingerprint(database_path)
        if after != before:
            raise ReadonlySnapshotError("snapshot_changed")


class SignalArtifactStoreOwnershipError(SignalArtifactStoreError):
    """The explicit path is not an owned signal-artifact store."""


class SignalArtifactStoreProtectedPathError(SignalArtifactStoreOwnershipError):
    """The path is official, local application data, or an alias."""


class SignalArtifactStoreBusyError(SignalArtifactStoreError):
    """SQLite could not acquire the bounded writer transaction."""


class SignalArtifactCollisionError(SignalArtifactStoreError):
    """An immutable identity or attempt was reused with another payload."""


class SignalArtifactNotFoundError(SignalArtifactStoreError):
    """An exact reader matched no row."""


class SignalArtifactAmbiguousError(SignalArtifactStoreError):
    """An exact reader matched multiple rows."""


class SignalArtifactIntegrityError(SignalArtifactStoreError):
    """A stored row, relation, or seal failed strict revalidation."""


class SignalArtifactRevisionError(SignalArtifactStoreError):
    """A revision is missing, cross-lineage, cyclic, or an illegal branch."""


@dataclass(frozen=True)
class StoredSignalArtifact:
    artifact_key: str
    artifact: SignalArtifact
    identity_hash: str
    lineage_key: str
    payload_hash: str
    seal: str
    revision: int
    first_generated_at: str
    created_at: str
    outcome: str = "read"
    attempt_id: str | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return self.artifact.to_mapping()

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "identity_hash": self.identity_hash,
            "lineage_key": self.lineage_key,
            "payload_hash": self.payload_hash,
            "seal": self.seal,
            "revision": self.revision,
            "first_generated_at": self.first_generated_at,
            "created_at": self.created_at,
            "outcome": self.outcome,
            "attempt_id": self.attempt_id,
            "artifact": self.payload,
        }


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: datetime | str, field_name: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO timestamp with timezone") from exc
    else:
        raise TypeError(f"{field_name} must be a timezone-aware datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must not be naive")
    return parsed.astimezone(UTC).isoformat()


def _validate_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _hex_digest(text: str) -> str:
    return text.split(":", 1)[1]


def _path_has_protected_component(path: Path) -> bool:
    protected = {part.casefold() for part in path.parts}
    return "formal" in protected or ".local" in protected


def _is_path_alias(path: Path) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path)))
    resolved = Path(os.path.realpath(os.fspath(absolute)))
    return os.path.normcase(str(absolute)) != os.path.normcase(str(resolved))


def _input_identity(normalized: Mapping[str, Any]) -> dict[str, Any]:
    """Return only immutable inputs, never rule output or quality results.

    A changed status, level, evidence, or quality with the same inputs must
    hit the same identity and be rejected as a payload collision.  A changed
    snapshot/as-of/basis/dependency/config/implementation starts a distinct
    root lineage instead.
    """

    keys = (
        "contract",
        "lineage_subject",
        "instrument",
        "market_date",
        "strategy",
        "signal_output_semantics_version",
        "feature_artifact_refs",
        "input_snapshot",
        "ruleset_snapshot",
        "ruleset_digest",
        "implementation_digest",
        "implementation_ref",
        "basis_manifest",
        "basis_digest",
        "dependency_manifest",
        "dependency_digest",
        "decision_at",
        "as_of_at",
        "legacy_reference",
        "source_mode",
        "implementation_mode",
    )
    return {key: normalized[key] for key in keys}


def _identity_values(normalized: Mapping[str, Any]) -> tuple[
    dict[str, Any], str, str, str, str, str
]:
    core = _input_identity(normalized)
    lineage_material = {
        "contract": SIGNAL_ARTIFACT_VERSION,
        "research_core": core,
    }
    lineage_json = canonical_json(lineage_material, field_name="lineage")
    lineage_key = _LINEAGE_PREFIX + _hex_digest(digest_text(lineage_json))
    identity = {
        "contract": SIGNAL_ARTIFACT_VERSION,
        "research_core": core,
        "revision": normalized["revision"],
    }
    identity_json = canonical_json(identity, field_name="identity")
    identity_hash = digest_text(identity_json)
    artifact_key = _KEY_PREFIX + _hex_digest(identity_hash)
    return identity, identity_json, identity_hash, artifact_key, lineage_key, lineage_json


def _payload_and_seal(
    normalized: Mapping[str, Any],
    *,
    identity_hash: str,
    artifact_key: str,
) -> tuple[str, str, str, str, str]:
    research_payload = {
        key: value
        for key, value in normalized.items()
        if key not in {"revision", "supersedes_artifact_key", "lifecycle_state", "lifecycle_reason", "lifecycle_at"}
    }
    research_payload_json = canonical_json(
        research_payload, field_name="signal_artifact.research_payload"
    )
    research_payload_hash = digest_text(research_payload_json)
    payload_json = canonical_json(normalized, field_name="signal_artifact.payload")
    payload_hash = digest_text(payload_json)
    seal = digest_json(
        {
            "artifact_key": artifact_key,
            "identity_hash": identity_hash,
            "payload_hash": payload_hash,
        },
        field_name="signal_artifact.seal",
    )
    return payload_json, payload_hash, seal, research_payload_json, research_payload_hash


class SignalArtifactStore:
    """An explicitly opted-in SQLite store with strict immutable readers."""

    @classmethod
    def open_readonly(cls, database_path: str | Path, *,
                      expected_database_sha256: str | None = None) -> "SignalArtifactStore":
        """Read an existing stable external checkpoint without a writable constructor."""
        return _ReadonlySignalArtifactStore(database_path,
                                           expected_database_sha256=expected_database_sha256)

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        if database_path is None:
            raise TypeError("database_path is required; SignalArtifactStore has no default path")
        if str(database_path) == ":memory:":
            raise SignalArtifactStoreProtectedPathError(
                "signal artifact store requires an explicit filesystem path"
            )
        self.database_path = str(Path(os.path.abspath(os.fspath(database_path))))
        self._path = Path(self.database_path)
        self._path_existed = self._path.exists()
        self._lock = threading.RLock()
        self._validate_path_before_open()
        if self._path_existed:
            self._validate_existing_database_readonly()
        if not self._path_existed:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(
                    self._path,
                    os.O_CREAT | os.O_EXCL | os.O_RDWR,
                )
            except FileExistsError:
                self._path_existed = True
            else:
                os.close(descriptor)
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=timeout,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        try:
            self._initialize_or_validate()
        except Exception:
            self._connection.close()
            raise

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def __enter__(self) -> "SignalArtifactStore":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _validate_path_before_open(self) -> None:
        path = self._path
        workspace_root = Path(__file__).resolve().parents[2]
        resolved = Path(os.path.realpath(os.fspath(path)))
        if _path_has_protected_component(path):
            raise SignalArtifactStoreProtectedPathError(
                "signal artifact store refuses formal and .local paths"
            )
        try:
            under_workspace = resolved.is_relative_to(workspace_root)
        except AttributeError:  # pragma: no cover - bundled Python is modern
            under_workspace = os.path.normcase(str(resolved)).startswith(
                os.path.normcase(str(workspace_root)) + os.sep
            )
        if under_workspace:
            raise SignalArtifactStoreProtectedPathError(
                "signal artifact store must live outside the project workspace"
            )
        if _path_has_protected_component(resolved):
            raise SignalArtifactStoreProtectedPathError(
                "signal artifact store refuses resolved formal and .local paths"
            )
        if _is_path_alias(path):
            raise SignalArtifactStoreProtectedPathError(
                "signal artifact store refuses symlink/junction aliases"
            )
        for parent in (path.parent, *path.parent.parents):
            if parent.exists() and os.path.islink(parent):
                raise SignalArtifactStoreProtectedPathError(
                    "signal artifact store refuses symlinked parent directories"
                )
        if path.exists():
            try:
                if path.is_symlink() or path.stat().st_nlink > 1:
                    raise SignalArtifactStoreProtectedPathError(
                        "signal artifact store refuses symlink and hard-link aliases"
                    )
            except OSError as exc:
                raise SignalArtifactStoreOwnershipError(
                    "unable to inspect explicit signal artifact path"
                ) from exc

    def _validate_existing_database_readonly(self) -> None:
        """Validate ownership before opening any write-capable connection."""

        uri_path = self._path.as_posix().replace("%", "%25").replace("#", "%23")
        uri = f"file:{uri_path}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        except sqlite3.DatabaseError as exc:
            raise SignalArtifactStoreOwnershipError(
                "explicit path is not a readable SQLite database"
            ) from exc
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                if not str(row[0]).startswith("sqlite_")
            }
            if not tables:
                # A second process can observe the explicitly-created empty
                # file while the first process is still committing its schema.
                # Re-read briefly before treating it as a foreign empty DB.
                for _ in range(20):
                    time.sleep(0.05)
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        ).fetchall()
                        if not str(row[0]).startswith("sqlite_")
                    }
                    if tables:
                        break
                if not tables:
                    raise SignalArtifactStoreOwnershipError(
                        "refusing an existing empty SQLite database without ownership marker"
                    )
            if _META_TABLE not in tables:
                raise SignalArtifactStoreOwnershipError(
                    "refusing existing database without signal-artifact ownership marker"
                )
            marker = connection.execute(
                f"SELECT store_kind, schema_version, owner_token FROM {_META_TABLE}"
            ).fetchall()
            if len(marker) != 1 or tuple(marker[0]) != (STORE_KIND, SCHEMA_VERSION, _OWNER_TOKEN):
                raise SignalArtifactStoreOwnershipError(
                    "signal-artifact ownership marker is invalid"
                )
            if tables != _REQUIRED_TABLES:
                raise SignalArtifactStoreOwnershipError(
                    "signal-artifact schema mismatch before write connection"
                )
            trigger_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ).fetchall()
            }
            if not _REQUIRED_TRIGGERS.issubset(trigger_names):
                raise SignalArtifactStoreOwnershipError(
                    "signal-artifact immutable triggers are missing"
                )
            index_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                ).fetchall()
            }
            if not _REQUIRED_INDEXES.issubset(index_names):
                raise SignalArtifactStoreOwnershipError(
                    "signal-artifact unique identity indexes are missing"
                )
        except sqlite3.DatabaseError as exc:
            if isinstance(exc, SignalArtifactStoreOwnershipError):
                raise
            raise SignalArtifactStoreOwnershipError(
                "existing signal-artifact database cannot be safely validated read-only"
            ) from exc
        finally:
            connection.close()

    def _initialize_or_validate(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                if not str(row[0]).startswith("sqlite_")
            }
            if not tables:
                if self._path_existed:
                    # A competing initializer may have created the file but
                    # not committed its DDL yet.  Do not hold our transaction
                    # while waiting; otherwise we could block that commit.
                    self._connection.execute("ROLLBACK")
                    for _ in range(20):
                        time.sleep(0.05)
                        self._connection.execute("BEGIN IMMEDIATE")
                        tables = {
                            row[0]
                            for row in self._connection.execute(
                                "SELECT name FROM sqlite_master WHERE type = 'table'"
                            ).fetchall()
                            if not str(row[0]).startswith("sqlite_")
                        }
                        if tables:
                            break
                        self._connection.execute("ROLLBACK")
                    if not tables:
                        raise SignalArtifactStoreOwnershipError(
                            "refusing an existing empty SQLite database without ownership marker"
                        )
                else:
                    self._create_schema()
                    self._connection.execute("COMMIT")
                    return
            if _META_TABLE not in tables:
                raise SignalArtifactStoreOwnershipError(
                    "refusing existing database without signal-artifact ownership marker"
                )
            marker = self._connection.execute(
                f"SELECT store_kind, schema_version, owner_token FROM {_META_TABLE}"
            ).fetchall()
            if len(marker) != 1 or tuple(marker[0]) != (STORE_KIND, SCHEMA_VERSION, _OWNER_TOKEN):
                raise SignalArtifactStoreOwnershipError(
                    "signal-artifact ownership marker is invalid"
                )
            if tables != _REQUIRED_TABLES:
                unknown = sorted(tables - _REQUIRED_TABLES)
                missing = sorted(_REQUIRED_TABLES - tables)
                raise SignalArtifactStoreOwnershipError(
                    f"signal-artifact schema mismatch (unknown={unknown}, missing={missing})"
                )
            trigger_names = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ).fetchall()
            }
            if not _REQUIRED_TRIGGERS.issubset(trigger_names):
                raise SignalArtifactStoreOwnershipError(
                    "signal-artifact immutable triggers are missing"
                )
            index_names = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                ).fetchall()
            }
            if not _REQUIRED_INDEXES.issubset(index_names):
                raise SignalArtifactStoreOwnershipError(
                    "signal-artifact unique identity indexes are missing"
                )
            self._connection.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            if "locked" in str(exc).casefold():
                raise SignalArtifactStoreBusyError(
                    "signal-artifact database is locked; retry"
                ) from exc
            if "not a database" in str(exc).casefold():
                raise SignalArtifactStoreOwnershipError(
                    "explicit path is not a SQLite database"
                ) from exc
            raise
        except SignalArtifactStoreError:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _create_schema(self) -> None:
        statements = [
            f"""
            CREATE TABLE {_META_TABLE} (
                store_kind TEXT PRIMARY KEY CHECK (store_kind = '{STORE_KIND}'),
                schema_version INTEGER NOT NULL CHECK (schema_version = {SCHEMA_VERSION}),
                owner_token TEXT NOT NULL CHECK (owner_token = '{_OWNER_TOKEN}'),
                created_at TEXT NOT NULL
            )
            """,
            f"""
            INSERT INTO {_META_TABLE}(store_kind, schema_version, owner_token, created_at)
            VALUES (?, ?, ?, ?)
            """,
            f"""
            CREATE TABLE {_BINDING_TABLE} (
                strategy_name TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                semantics_version TEXT NOT NULL,
                ruleset_digest TEXT NOT NULL,
                implementation_digest TEXT NOT NULL,
                binding_json TEXT NOT NULL CHECK (json_valid(binding_json)),
                created_at TEXT NOT NULL,
                PRIMARY KEY(strategy_name, strategy_version, semantics_version)
            )
            """,
            f"""
            CREATE TABLE {_ARTIFACT_TABLE} (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_key TEXT NOT NULL UNIQUE,
                identity_hash TEXT NOT NULL UNIQUE,
                identity_json TEXT NOT NULL CHECK (json_valid(identity_json)),
                lineage_key TEXT NOT NULL,
                lineage_subject TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                semantics_version TEXT NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market_date TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision > 0),
                supersedes_artifact_key TEXT,
                canonical_payload_json TEXT NOT NULL CHECK (json_valid(canonical_payload_json)),
                research_payload_json TEXT NOT NULL CHECK (json_valid(research_payload_json)),
                research_payload_hash TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                seal TEXT NOT NULL,
                first_generated_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(supersedes_artifact_key) REFERENCES { _ARTIFACT_TABLE }(artifact_key)
            )
            """,
            f"""
            CREATE TABLE {_REF_TABLE} (
                artifact_key TEXT NOT NULL,
                feature_artifact_key TEXT NOT NULL,
                PRIMARY KEY(artifact_key, feature_artifact_key),
                FOREIGN KEY(artifact_key) REFERENCES {_ARTIFACT_TABLE}(artifact_key)
            )
            """,
            f"""
            CREATE TABLE {_LIFECYCLE_TABLE} (
                artifact_key TEXT NOT NULL,
                event_index INTEGER NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('active', 'withdrawn')),
                reason TEXT,
                lifecycle_at TEXT,
                PRIMARY KEY(artifact_key, event_index),
                UNIQUE(artifact_key, state),
                FOREIGN KEY(artifact_key) REFERENCES {_ARTIFACT_TABLE}(artifact_key)
            )
            """,
            f"""
            CREATE TABLE {_ATTEMPT_TABLE} (
                attempt_id TEXT PRIMARY KEY,
                artifact_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                candidate_generated_at TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                outcome TEXT NOT NULL,
                FOREIGN KEY(artifact_key) REFERENCES {_ARTIFACT_TABLE}(artifact_key)
            )
            """,
            f"""
            CREATE TABLE {_RUN_TABLE} (
                relation_key TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                artifact_key TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                related_at TEXT NOT NULL,
                UNIQUE(run_id, artifact_key, attempt_id),
                UNIQUE(attempt_id),
                FOREIGN KEY(artifact_key) REFERENCES {_ARTIFACT_TABLE}(artifact_key),
                FOREIGN KEY(attempt_id) REFERENCES {_ATTEMPT_TABLE}(attempt_id)
            )
            """,
            f"CREATE INDEX signal_artifacts_lineage_order ON {_ARTIFACT_TABLE}(lineage_key, revision, artifact_key)",
            f"CREATE UNIQUE INDEX signal_artifacts_lineage_revision_unique ON {_ARTIFACT_TABLE}(lineage_key, revision)",
            f"CREATE UNIQUE INDEX signal_artifacts_supersedes_unique ON {_ARTIFACT_TABLE}(supersedes_artifact_key)",
            f"CREATE INDEX signal_artifact_attempts_artifact ON {_ATTEMPT_TABLE}(artifact_key, attempted_at, attempt_id)",
            f"CREATE INDEX signal_artifact_runs_artifact ON {_RUN_TABLE}(artifact_key, run_id)",
            f"""
            CREATE TRIGGER signal_artifacts_immutable_update
            BEFORE UPDATE ON {_ARTIFACT_TABLE}
            BEGIN SELECT RAISE(ABORT, 'signal artifacts are immutable'); END
            """,
            f"""
            CREATE TRIGGER signal_artifacts_immutable_delete
            BEFORE DELETE ON {_ARTIFACT_TABLE}
            BEGIN SELECT RAISE(ABORT, 'signal artifacts are immutable'); END
            """,
            f"""
            CREATE TRIGGER signal_artifacts_no_replace
            BEFORE INSERT ON {_ARTIFACT_TABLE}
            WHEN EXISTS (SELECT 1 FROM {_ARTIFACT_TABLE} WHERE rowid = NEW.rowid)
              OR EXISTS (SELECT 1 FROM {_ARTIFACT_TABLE} WHERE artifact_key = NEW.artifact_key)
              OR EXISTS (SELECT 1 FROM {_ARTIFACT_TABLE} WHERE identity_hash = NEW.identity_hash)
              OR EXISTS (SELECT 1 FROM {_ARTIFACT_TABLE} WHERE lineage_key = NEW.lineage_key AND revision = NEW.revision)
              OR (NEW.supersedes_artifact_key IS NOT NULL AND EXISTS (
                  SELECT 1 FROM {_ARTIFACT_TABLE}
                  WHERE supersedes_artifact_key = NEW.supersedes_artifact_key
              ))
            BEGIN SELECT RAISE(ABORT, 'signal artifact identity already exists'); END
            """,
        ]
        for index, statement in enumerate(statements):
            if index == 1:
                self._connection.execute(
                    statement,
                    (STORE_KIND, SCHEMA_VERSION, _OWNER_TOKEN, _now_utc()),
                )
            else:
                self._connection.execute(statement)
        immutable_specs = [
            (
                _BINDING_TABLE,
                "signal_artifact_bindings",
                [("strategy_name", "strategy_version", "semantics_version")],
            ),
            (
                _REF_TABLE,
                "signal_artifact_feature_refs",
                [("artifact_key", "feature_artifact_key")],
            ),
            (
                _LIFECYCLE_TABLE,
                "signal_artifact_lifecycle",
                [("artifact_key", "event_index"), ("artifact_key", "state")],
            ),
            (_ATTEMPT_TABLE, "signal_artifact_attempts", [("attempt_id",)]),
            (
                _RUN_TABLE,
                "signal_artifact_run_relations",
                [
                    ("relation_key",),
                    ("run_id", "artifact_key", "attempt_id"),
                    ("attempt_id",),
                ],
            ),
        ]
        for table, prefix, unique_keys in immutable_specs:
            self._connection.execute(
                f"""
                CREATE TRIGGER {prefix}_immutable_update
                BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, '{prefix} are immutable'); END
                """
            )
            self._connection.execute(
                f"""
                CREATE TRIGGER {prefix}_immutable_delete
                BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, '{prefix} are immutable'); END
                """
            )
            replace_conditions = " OR ".join(
                " AND ".join(f"{column} = NEW.{column}" for column in columns)
                for columns in unique_keys
            )
            replace_conditions = (
                f"({replace_conditions}) OR "
                f"EXISTS (SELECT 1 FROM {table} WHERE rowid = NEW.rowid)"
            )
            self._connection.execute(
                f"""
                CREATE TRIGGER {prefix}_no_replace
                BEFORE INSERT ON {table}
                WHEN EXISTS (SELECT 1 FROM {table} WHERE {replace_conditions})
                BEGIN SELECT RAISE(ABORT, '{prefix} cannot be replaced'); END
                """
            )

    def _normalized(self, value: SignalArtifact | Mapping[str, Any]) -> dict[str, Any]:
        try:
            return normalize_signal_artifact(value, include_generated=True)
        except (SignalArtifactContractError, TypeError, ValueError):
            raise

    @staticmethod
    def _stored_artifact_from_payload(payload: Mapping[str, Any]) -> SignalArtifact:
        try:
            return SignalArtifact.from_mapping(payload)
        except (SignalArtifactContractError, TypeError, ValueError) as exc:
            raise SignalArtifactIntegrityError(
                "stored signal-artifact payload fails contract validation"
            ) from exc

    def _binding_values(self, normalized: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        strategy = normalized["strategy"]
        binding = {
            "strategy_name": strategy["name"],
            "strategy_version": strategy["version"],
            "semantics_version": normalized["signal_output_semantics_version"],
            "ruleset_digest": normalized["ruleset_digest"],
            "implementation_digest": normalized["implementation_digest"],
            "source_mode": CALLER_PROVIDED_ONLY,
            "implementation_mode": CALLER_PROVIDED_ONLY,
        }
        return binding, digest_json(binding, field_name="strategy_binding")

    def _check_binding(self, normalized: Mapping[str, Any]) -> None:
        binding, _ = self._binding_values(normalized)
        row = self._connection.execute(
            f"""
            SELECT * FROM {_BINDING_TABLE}
            WHERE strategy_name = ? AND strategy_version = ? AND semantics_version = ?
            """,
            (
                binding["strategy_name"],
                binding["strategy_version"],
                binding["semantics_version"],
            ),
        ).fetchone()
        if row is not None:
            expected_json = canonical_json(binding, field_name="strategy_binding")
            if (
                row["ruleset_digest"] != binding["ruleset_digest"]
                or row["implementation_digest"] != binding["implementation_digest"]
                or row["binding_json"] != expected_json
            ):
                raise SignalArtifactCollisionError(
                    "strategy/version/semantics binding conflicts with an existing configuration"
                )
            return
        self._connection.execute(
            f"""
            INSERT INTO {_BINDING_TABLE}
                (strategy_name, strategy_version, semantics_version,
                 ruleset_digest, implementation_digest, binding_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding["strategy_name"],
                binding["strategy_version"],
                binding["semantics_version"],
                binding["ruleset_digest"],
                binding["implementation_digest"],
                canonical_json(binding, field_name="strategy_binding"),
                _now_utc(),
            ),
        )

    def _check_attempt_replay(
        self,
        *,
        attempt_id: str,
        artifact_key: str,
        payload_hash: str,
        run_id: str | None,
    ) -> sqlite3.Row | None:
        row = self._connection.execute(
            f"SELECT * FROM {_ATTEMPT_TABLE} WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            return None
        if (
            row["artifact_key"] != artifact_key
            or row["payload_hash"] != payload_hash
        ):
            raise SignalArtifactCollisionError(
                f"attempt_id already exists with a different artifact payload: {attempt_id}"
            )
        relation = self._connection.execute(
            f"SELECT run_id FROM {_RUN_TABLE} WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        existing_run = None if relation is None else relation[0]
        if existing_run != run_id:
            raise SignalArtifactCollisionError(
                f"attempt_id already exists with a different run relation: {attempt_id}"
            )
        return row

    def _record_attempt(
        self,
        *,
        attempt_id: str,
        artifact_key: str,
        payload_hash: str,
        candidate_generated_at: str,
        attempted_at: str,
        outcome: str,
        run_id: str | None,
    ) -> None:
        existing = self._check_attempt_replay(
            attempt_id=attempt_id,
            artifact_key=artifact_key,
            payload_hash=payload_hash,
            run_id=run_id,
        )
        if existing is None:
            self._connection.execute(
                f"""
                INSERT INTO {_ATTEMPT_TABLE}
                    (attempt_id, artifact_key, payload_hash, candidate_generated_at,
                     attempted_at, outcome)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    artifact_key,
                    payload_hash,
                    candidate_generated_at,
                    attempted_at,
                    outcome,
                ),
            )
        if run_id is None:
            return
        run_id = _validate_text(run_id, "run_id")
        relation_key = digest_text(
            canonical_json(
                {"run_id": run_id, "artifact_key": artifact_key, "attempt_id": attempt_id},
                field_name="run_relation",
            )
        )
        existing_relation = self._connection.execute(
            f"SELECT * FROM {_RUN_TABLE} WHERE run_id = ? AND artifact_key = ? AND attempt_id = ?",
            (run_id, artifact_key, attempt_id),
        ).fetchone()
        if existing_relation is not None:
            if (
                existing_relation["payload_hash"] != payload_hash
                or existing_relation["attempt_id"] != attempt_id
            ):
                raise SignalArtifactCollisionError(
                    "run relation already exists with a different payload or attempt"
                )
            return
        self._connection.execute(
            f"""
            INSERT INTO {_RUN_TABLE}
                (relation_key, run_id, artifact_key, attempt_id, payload_hash, related_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (relation_key, run_id, artifact_key, attempt_id, payload_hash, attempted_at),
        )

    def _validate_attempt_relations(
        self,
        *,
        artifact_key: str,
        payload_hash: str,
        attempt_id: str,
        run_id: str | None,
    ) -> None:
        attempt = self._connection.execute(
            f"SELECT * FROM {_ATTEMPT_TABLE} WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if (
            attempt is None
            or attempt["artifact_key"] != artifact_key
            or attempt["payload_hash"] != payload_hash
        ):
            raise SignalArtifactIntegrityError("attempt relation is missing or has a payload mismatch")
        relations = self._connection.execute(
            f"SELECT * FROM {_RUN_TABLE} WHERE artifact_key = ? ORDER BY relation_key",
            (artifact_key,),
        ).fetchall()
        seen_relation_attempts: set[str] = set()
        for relation in relations:
            if relation["payload_hash"] != payload_hash:
                raise SignalArtifactIntegrityError("run relation payload hash is tampered")
            expected_relation_key = digest_text(
                canonical_json(
                    {
                        "run_id": relation["run_id"],
                        "artifact_key": artifact_key,
                        "attempt_id": relation["attempt_id"],
                    },
                    field_name="run_relation",
                )
            )
            if relation["relation_key"] != expected_relation_key:
                raise SignalArtifactIntegrityError("run relation key is tampered")
            related_attempt = self._connection.execute(
                f"SELECT payload_hash FROM {_ATTEMPT_TABLE} WHERE attempt_id = ?",
                (relation["attempt_id"],),
            ).fetchone()
            if related_attempt is None or related_attempt[0] != payload_hash:
                raise SignalArtifactIntegrityError("run relation points to a mismatched attempt")
            if relation["attempt_id"] in seen_relation_attempts:
                raise SignalArtifactIntegrityError("an attempt is related to more than one run")
            seen_relation_attempts.add(str(relation["attempt_id"]))
            related_attempt_row = self._connection.execute(
                f"SELECT attempted_at FROM {_ATTEMPT_TABLE} WHERE attempt_id = ?",
                (relation["attempt_id"],),
            ).fetchone()
            if related_attempt_row is None or relation["related_at"] != related_attempt_row[0]:
                raise SignalArtifactIntegrityError("run relation time does not match its attempt")
        if run_id is not None and not any(
            relation["run_id"] == run_id and relation["attempt_id"] == attempt_id
            for relation in relations
        ):
            raise SignalArtifactIntegrityError("requested run relation was not saved atomically")

    def _assert_parent_for_new(
        self,
        normalized: Mapping[str, Any],
        *,
        artifact_key: str,
        lineage_key: str,
        candidate_generated_at: str,
        research_payload_hash: str,
    ) -> sqlite3.Row | None:
        revision = int(normalized["revision"])
        parent_key = normalized["supersedes_artifact_key"]
        if revision == 1:
            if parent_key is not None:
                raise SignalArtifactRevisionError("root revision must not supersede a parent")
            existing = self._connection.execute(
                f"SELECT artifact_key FROM {_ARTIFACT_TABLE} WHERE lineage_key = ? AND revision = 1",
                (lineage_key,),
            ).fetchone()
            if existing is not None:
                raise SignalArtifactRevisionError(
                    "research-core lineage already has a root; use a new research core"
                )
            if normalized["lifecycle_state"] != "active":
                raise SignalArtifactRevisionError("a new lineage must begin active")
            if candidate_generated_at < normalized["decision_at"]:
                raise SignalArtifactRevisionError(
                    "root first_generated_at must not precede decision_at"
                )
            return None
        if parent_key is None or parent_key == artifact_key:
            raise SignalArtifactRevisionError("revision must name a distinct predecessor")
        parent = self._connection.execute(
            f"SELECT * FROM {_ARTIFACT_TABLE} WHERE artifact_key = ?", (parent_key,)
        ).fetchone()
        if parent is None:
            raise SignalArtifactRevisionError(
                "supersedes predecessor does not exist in the same research lineage"
            )
        if parent["lineage_key"] != lineage_key or parent["revision"] != revision - 1:
            raise SignalArtifactRevisionError(
                "supersedes crosses research core or is not the immediately previous revision"
            )
        if parent["research_payload_hash"] != research_payload_hash:
            raise SignalArtifactRevisionError(
                "revision must preserve the exact research payload seal"
            )
        child = self._connection.execute(
            f"SELECT artifact_key FROM {_ARTIFACT_TABLE} WHERE supersedes_artifact_key = ?",
            (parent_key,),
        ).fetchone()
        if child is not None:
            raise SignalArtifactRevisionError(
                "lineage already has a child; branching revisions are not supported"
            )
        parent_stored = self._row_to_stored(parent, validate_ancestors=True)
        if parent_stored.artifact.lifecycle_state != "active":
            raise SignalArtifactRevisionError("withdrawn lifecycle is terminal")
        if normalized["lifecycle_state"] != "withdrawn":
            raise SignalArtifactRevisionError(
                "the only supported lifecycle revision is active to withdrawn"
            )
        lifecycle_at = normalized["lifecycle_at"]
        if lifecycle_at is None or candidate_generated_at < lifecycle_at:
            raise SignalArtifactRevisionError(
                "child first_generated_at must be at or after lifecycle_at"
            )
        return parent

    def save_artifact(
        self,
        artifact: SignalArtifact | Mapping[str, Any],
        *,
        attempt_id: str | None = None,
        run_id: str | None = None,
        attempted_at: datetime | str | None = None,
        generated_at: datetime | str | None = None,
        _pre_commit_validator: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> StoredSignalArtifact:
        """Atomically create or replay one signal artifact.

        ``generated_at`` is a candidate for the attempt relation only.  The
        first successful candidate is returned as immutable
        ``first_generated_at``; retries never modify it.
        """

        normalized = self._normalized(artifact)
        if generated_at is not None:
            normalized = dict(normalized)
            normalized["generated_at"] = _timestamp(generated_at, "generated_at")
        candidate_generated_at = normalized.get("generated_at") or _now_utc()
        attempted_at_value = _timestamp(attempted_at, "attempted_at") if attempted_at is not None else _now_utc()
        attempt_id_value = (
            _validate_text(attempt_id, "attempt_id") if attempt_id is not None else uuid.uuid4().hex
        )
        run_id_value = None if run_id is None else _validate_text(run_id, "run_id")
        payload_normalized = dict(normalized)
        payload_normalized.pop("generated_at", None)
        payload_normalized.pop("artifact_key", None)
        _, identity_json, identity_hash, artifact_key, lineage_key, _ = _identity_values(
            payload_normalized
        )
        supplied_key = normalized.get("artifact_key")
        if supplied_key is not None and supplied_key != artifact_key:
            raise SignalArtifactCollisionError("caller artifact_key does not match derived identity")
        (
            payload_json,
            payload_hash,
            seal,
            research_payload_json,
            research_payload_hash,
        ) = _payload_and_seal(
            payload_normalized,
            identity_hash=identity_hash,
            artifact_key=artifact_key,
        )
        strategy = payload_normalized["strategy"]
        semantics_version = payload_normalized["signal_output_semantics_version"]
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._check_binding(payload_normalized)
                existing = self._connection.execute(
                    f"SELECT * FROM {_ARTIFACT_TABLE} WHERE artifact_key = ?",
                    (artifact_key,),
                ).fetchone()
                if existing is not None:
                    stored = self._row_to_stored(existing, validate_ancestors=True)
                    if (
                        stored.payload_hash != payload_hash
                        or stored.artifact.canonical_payload() != payload_json
                    ):
                        raise SignalArtifactCollisionError(
                            "signal artifact identity already exists with a different canonical payload"
                        )
                    self._record_attempt(
                        attempt_id=attempt_id_value,
                        artifact_key=artifact_key,
                        payload_hash=payload_hash,
                        candidate_generated_at=candidate_generated_at,
                        attempted_at=attempted_at_value,
                        outcome="idempotent_replay",
                        run_id=run_id_value,
                    )
                    self._validate_attempt_relations(
                        artifact_key=artifact_key,
                        payload_hash=payload_hash,
                        attempt_id=attempt_id_value,
                        run_id=run_id_value,
                    )
                    if _pre_commit_validator is not None:
                        _pre_commit_validator(self._connection)
                    replay_row = self._connection.execute(
                        f"SELECT * FROM {_ARTIFACT_TABLE} WHERE artifact_key = ?",
                        (artifact_key,),
                    ).fetchone()
                    stored = self._row_to_stored(replay_row, validate_ancestors=True)
                    self._connection.execute("COMMIT")
                    return StoredSignalArtifact(
                        artifact_key=stored.artifact_key,
                        artifact=stored.artifact,
                        identity_hash=stored.identity_hash,
                        lineage_key=stored.lineage_key,
                        payload_hash=stored.payload_hash,
                        seal=stored.seal,
                        revision=stored.revision,
                        first_generated_at=stored.first_generated_at,
                        created_at=stored.created_at,
                        outcome="idempotent_replay",
                        attempt_id=attempt_id_value,
                    )

                same_identity = self._connection.execute(
                    f"SELECT artifact_key FROM {_ARTIFACT_TABLE} WHERE identity_hash = ?",
                    (identity_hash,),
                ).fetchone()
                if same_identity is not None:
                    raise SignalArtifactCollisionError(
                        "signal artifact identity hash is already occupied"
                    )
                self._assert_parent_for_new(
                    payload_normalized,
                    artifact_key=artifact_key,
                    lineage_key=lineage_key,
                    candidate_generated_at=candidate_generated_at,
                    research_payload_hash=research_payload_hash,
                )
                self._connection.execute(
                    f"""
                    INSERT INTO {_ARTIFACT_TABLE}
                        (artifact_key, identity_hash, identity_json, lineage_key,
                         lineage_subject, strategy_name, strategy_version,
                         semantics_version, exchange, symbol, market_date, revision,
                         supersedes_artifact_key, canonical_payload_json,
                         research_payload_json, research_payload_hash, payload_hash,
                         seal, first_generated_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_key,
                        identity_hash,
                        identity_json,
                        lineage_key,
                        payload_normalized["lineage_subject"],
                        strategy["name"],
                        strategy["version"],
                        semantics_version,
                        payload_normalized["instrument"]["exchange"],
                        payload_normalized["instrument"]["symbol"],
                        payload_normalized["market_date"],
                        payload_normalized["revision"],
                        payload_normalized["supersedes_artifact_key"],
                        payload_json,
                        research_payload_json,
                        research_payload_hash,
                        payload_hash,
                        seal,
                        candidate_generated_at,
                        _now_utc(),
                    ),
                )
                for ref in payload_normalized["feature_artifact_refs"]:
                    self._connection.execute(
                        f"INSERT INTO {_REF_TABLE}(artifact_key, feature_artifact_key) VALUES (?, ?)",
                        (artifact_key, ref),
                    )
                binding, _ = self._binding_values(payload_normalized)
                binding_row = self._connection.execute(
                    f"SELECT binding_json FROM {_BINDING_TABLE} WHERE strategy_name = ? AND strategy_version = ? AND semantics_version = ?",
                    (binding["strategy_name"], binding["strategy_version"], binding["semantics_version"]),
                ).fetchone()
                if binding_row is None or binding_row[0] != canonical_json(binding, field_name="strategy_binding"):
                    raise SignalArtifactIntegrityError("strategy binding was not saved atomically")
                self._connection.execute(
                    f"""
                    INSERT INTO {_LIFECYCLE_TABLE}
                        (artifact_key, event_index, state, reason, lifecycle_at)
                    VALUES (?, 0, ?, ?, ?)
                    """,
                    (
                        artifact_key,
                        payload_normalized["lifecycle_state"],
                        payload_normalized["lifecycle_reason"],
                        payload_normalized["lifecycle_at"],
                    ),
                )
                self._record_attempt(
                    attempt_id=attempt_id_value,
                    artifact_key=artifact_key,
                    payload_hash=payload_hash,
                    candidate_generated_at=candidate_generated_at,
                    attempted_at=attempted_at_value,
                    outcome="created",
                    run_id=run_id_value,
                )
                self._validate_attempt_relations(
                    artifact_key=artifact_key,
                    payload_hash=payload_hash,
                    attempt_id=attempt_id_value,
                    run_id=run_id_value,
                )
                if _pre_commit_validator is not None:
                    _pre_commit_validator(self._connection)
                row = self._connection.execute(
                    f"SELECT * FROM {_ARTIFACT_TABLE} WHERE artifact_key = ?", (artifact_key,)
                ).fetchone()
                stored = self._row_to_stored(row, validate_ancestors=True)
                self._connection.execute("COMMIT")
                return StoredSignalArtifact(
                    artifact_key=stored.artifact_key,
                    artifact=stored.artifact,
                    identity_hash=stored.identity_hash,
                    lineage_key=stored.lineage_key,
                    payload_hash=stored.payload_hash,
                    seal=stored.seal,
                    revision=stored.revision,
                    first_generated_at=stored.first_generated_at,
                    created_at=stored.created_at,
                    outcome="created",
                    attempt_id=attempt_id_value,
                )
            except (SignalArtifactStoreError, SignalArtifactContractError):
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as exc:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise SignalArtifactCollisionError(str(exc)) from exc
            except sqlite3.OperationalError as exc:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                if "locked" in str(exc).casefold():
                    raise SignalArtifactStoreBusyError(
                        "signal-artifact database is locked; retry"
                    ) from exc
                raise
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    save = save_artifact
    append = save_artifact

    def _validate_binding_row(self, normalized: Mapping[str, Any]) -> None:
        binding, _ = self._binding_values(normalized)
        row = self._connection.execute(
            f"SELECT * FROM {_BINDING_TABLE} WHERE strategy_name = ? AND strategy_version = ? AND semantics_version = ?",
            (binding["strategy_name"], binding["strategy_version"], binding["semantics_version"]),
        ).fetchone()
        expected_json = canonical_json(binding, field_name="strategy_binding")
        if row is None or row["binding_json"] != expected_json:
            raise SignalArtifactIntegrityError("signal artifact strategy binding is missing or tampered")
        if (
            row["ruleset_digest"] != binding["ruleset_digest"]
            or row["implementation_digest"] != binding["implementation_digest"]
        ):
            raise SignalArtifactIntegrityError("signal artifact strategy binding digest mismatch")

    def _validate_ancestor_chain(self, row: sqlite3.Row, *, seen: set[str]) -> None:
        key = str(row["artifact_key"])
        if key in seen:
            raise SignalArtifactIntegrityError("signal artifact revision graph contains a cycle")
        seen.add(key)
        parent_key = row["supersedes_artifact_key"]
        if parent_key is None:
            if int(row["revision"]) != 1:
                raise SignalArtifactIntegrityError("non-root artifact has no predecessor")
            return
        parent = self._connection.execute(
            f"SELECT * FROM {_ARTIFACT_TABLE} WHERE artifact_key = ?", (parent_key,)
        ).fetchone()
        if parent is None:
            raise SignalArtifactIntegrityError("supersedes predecessor is missing")
        if parent["lineage_key"] != row["lineage_key"] or int(parent["revision"]) != int(row["revision"]) - 1:
            raise SignalArtifactIntegrityError("stored supersedes relation crosses lineage or revision")
        parent_stored = self._row_to_stored(parent, validate_ancestors=False)
        if parent["research_payload_hash"] != row["research_payload_hash"]:
            raise SignalArtifactIntegrityError(
                "child revision research payload seal differs from its parent"
            )
        try:
            current_payload = normalize_signal_artifact(
                json.loads(row["canonical_payload_json"]), include_generated=False
            )
        except (json.JSONDecodeError, SignalArtifactContractError, TypeError, ValueError) as exc:
            raise SignalArtifactIntegrityError("child lifecycle payload cannot be revalidated") from exc
        lifecycle_at = current_payload["lifecycle_at"]
        if lifecycle_at is None or lifecycle_at < parent_stored.first_generated_at or lifecycle_at > row["first_generated_at"]:
            raise SignalArtifactIntegrityError(
                "withdraw lifecycle must fall between parent and child first generation"
            )
        self._validate_ancestor_chain(parent, seen=seen)

    def _row_to_stored(
        self,
        row: sqlite3.Row | None,
        *,
        outcome: str = "read",
        validate_ancestors: bool = True,
    ) -> StoredSignalArtifact:
        if row is None:
            raise SignalArtifactNotFoundError("signal-artifact exact reader matched zero rows")
        try:
            payload = json.loads(row["canonical_payload_json"])
            normalized = normalize_signal_artifact(payload, include_generated=False)
            artifact = SignalArtifact.from_mapping(payload)
            expected_payload = canonical_json(normalized, field_name="signal_artifact.payload")
        except (json.JSONDecodeError, SignalArtifactContractError, ValueError, TypeError) as exc:
            raise SignalArtifactIntegrityError(
                "stored signal-artifact payload fails strict revalidation"
            ) from exc
        _, expected_identity_json, expected_identity_hash, expected_key, expected_lineage, _ = _identity_values(normalized)
        expected_payload_hash = digest_text(expected_payload)
        _, _, expected_seal, expected_research_json, expected_research_hash = _payload_and_seal(
            normalized,
            identity_hash=expected_identity_hash,
            artifact_key=expected_key,
        )
        checks = {
            "payload_json": expected_payload == row["canonical_payload_json"],
            "research_payload_json": expected_research_json == row["research_payload_json"],
            "research_payload_hash": expected_research_hash == row["research_payload_hash"],
            "payload_hash": expected_payload_hash == row["payload_hash"],
            "identity_json": expected_identity_json == row["identity_json"],
            "identity_hash": expected_identity_hash == row["identity_hash"],
            "artifact_key": expected_key == row["artifact_key"],
            "lineage_key": expected_lineage == row["lineage_key"],
            "revision": normalized["revision"] == row["revision"],
            "supersedes": normalized["supersedes_artifact_key"] == row["supersedes_artifact_key"],
            "seal": expected_seal == row["seal"],
            "strategy_name": normalized["strategy"]["name"] == row["strategy_name"],
            "strategy_version": normalized["strategy"]["version"] == row["strategy_version"],
            "semantics_version": normalized["signal_output_semantics_version"] == row["semantics_version"],
            "exchange": normalized["instrument"]["exchange"] == row["exchange"],
            "symbol": normalized["instrument"]["symbol"] == row["symbol"],
            "market_date": normalized["market_date"] == row["market_date"],
        }
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            raise SignalArtifactIntegrityError(f"signal-artifact row seal mismatch: {failed}")
        try:
            first_generated = _timestamp(row["first_generated_at"], "first_generated_at")
            created_at = _timestamp(row["created_at"], "created_at")
        except (TypeError, ValueError) as exc:
            raise SignalArtifactIntegrityError("stored signal-artifact timestamps are invalid") from exc
        self._validate_binding_row(normalized)
        refs = [
            item[0]
            for item in self._connection.execute(
                f"SELECT feature_artifact_key FROM {_REF_TABLE} WHERE artifact_key = ? ORDER BY feature_artifact_key",
                (row["artifact_key"],),
            ).fetchall()
        ]
        if refs != normalized["feature_artifact_refs"]:
            raise SignalArtifactIntegrityError("stored feature artifact references are tampered")
        lifecycle = self._connection.execute(
            f"SELECT state, reason, lifecycle_at FROM {_LIFECYCLE_TABLE} WHERE artifact_key = ? ORDER BY event_index",
            (row["artifact_key"],),
        ).fetchall()
        expected_lifecycle = [
            (
                normalized["lifecycle_state"],
                normalized["lifecycle_reason"],
                normalized["lifecycle_at"],
            )
        ]
        if [tuple(item) for item in lifecycle] != expected_lifecycle:
            raise SignalArtifactIntegrityError("stored lifecycle relation is missing or tampered")
        attempts = self._connection.execute(
            f"SELECT * FROM {_ATTEMPT_TABLE} WHERE artifact_key = ? ORDER BY attempt_id",
            (row["artifact_key"],),
        ).fetchall()
        if not attempts:
            raise SignalArtifactIntegrityError("stored artifact has no attempt relation")
        for attempt in attempts:
            if attempt["payload_hash"] != row["payload_hash"]:
                raise SignalArtifactIntegrityError("stored attempt payload hash is tampered")
            try:
                _timestamp(attempt["candidate_generated_at"], "candidate_generated_at")
                _timestamp(attempt["attempted_at"], "attempted_at")
            except (TypeError, ValueError) as exc:
                raise SignalArtifactIntegrityError("stored attempt timestamp is invalid") from exc
        relations = self._connection.execute(
            f"SELECT * FROM {_RUN_TABLE} WHERE artifact_key = ? ORDER BY relation_key",
            (row["artifact_key"],),
        ).fetchall()
        seen_relation_attempts: set[str] = set()
        for relation in relations:
            if relation["payload_hash"] != row["payload_hash"]:
                raise SignalArtifactIntegrityError("stored run relation payload hash is tampered")
            expected_relation_key = digest_text(
                canonical_json(
                    {
                        "run_id": relation["run_id"],
                        "artifact_key": row["artifact_key"],
                        "attempt_id": relation["attempt_id"],
                    },
                    field_name="run_relation",
                )
            )
            if relation["relation_key"] != expected_relation_key:
                raise SignalArtifactIntegrityError("stored run relation key is tampered")
            if not any(attempt["attempt_id"] == relation["attempt_id"] for attempt in attempts):
                raise SignalArtifactIntegrityError("stored run relation points to a missing attempt")
            if relation["attempt_id"] in seen_relation_attempts:
                raise SignalArtifactIntegrityError("stored attempt is related to more than one run")
            seen_relation_attempts.add(str(relation["attempt_id"]))
            try:
                _timestamp(relation["related_at"], "related_at")
            except (TypeError, ValueError) as exc:
                raise SignalArtifactIntegrityError("stored run relation timestamp is invalid") from exc
            attempt_row = self._connection.execute(
                f"SELECT attempted_at FROM {_ATTEMPT_TABLE} WHERE attempt_id = ?",
                (relation["attempt_id"],),
            ).fetchone()
            if attempt_row is None or relation["related_at"] != attempt_row[0]:
                raise SignalArtifactIntegrityError("stored run relation time is tampered")
        if validate_ancestors:
            self._validate_ancestor_chain(row, seen=set())
        return StoredSignalArtifact(
            artifact_key=str(row["artifact_key"]),
            artifact=artifact,
            identity_hash=str(row["identity_hash"]),
            lineage_key=str(row["lineage_key"]),
            payload_hash=str(row["payload_hash"]),
            seal=str(row["seal"]),
            revision=int(row["revision"]),
            first_generated_at=first_generated,
            created_at=created_at,
            outcome=outcome,
        )

    def get_by_key(self, artifact_key: str) -> StoredSignalArtifact:
        artifact_key = _validate_text(artifact_key, "artifact_key")
        with self._lock:
            row = self._connection.execute(
                f"SELECT * FROM {_ARTIFACT_TABLE} WHERE artifact_key = ?", (artifact_key,)
            ).fetchone()
            return self._row_to_stored(row)

    read = get_by_key
    read_exact = get_by_key

    def get_exact(
        self,
        *,
        artifact_key: str | None = None,
        identity_hash: str | None = None,
        lineage_key: str | None = None,
        revision: int | None = None,
    ) -> StoredSignalArtifact:
        selectors = [artifact_key is not None, identity_hash is not None, lineage_key is not None]
        if not any(selectors):
            raise ValueError("an exact artifact_key, identity_hash, or lineage_key+revision is required")
        if lineage_key is not None and revision is None:
            raise ValueError("lineage_key selection requires an exact revision; latest is never implicit")
        clauses: list[str] = []
        values: list[Any] = []
        if artifact_key is not None:
            clauses.append("artifact_key = ?")
            values.append(_validate_text(artifact_key, "artifact_key"))
        if identity_hash is not None:
            clauses.append("identity_hash = ?")
            values.append(_validate_text(identity_hash, "identity_hash"))
        if lineage_key is not None:
            clauses.append("lineage_key = ?")
            values.append(_validate_text(lineage_key, "lineage_key"))
        if revision is not None:
            if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
                raise ValueError("revision must be a positive integer")
            clauses.append("revision = ?")
            values.append(revision)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM {_ARTIFACT_TABLE} WHERE {' AND '.join(clauses)} ORDER BY artifact_key",
                values,
            ).fetchall()
            if not rows:
                raise SignalArtifactNotFoundError("signal-artifact exact reader matched zero rows")
            if len(rows) != 1:
                raise SignalArtifactAmbiguousError("signal-artifact exact reader is ambiguous")
            return self._row_to_stored(rows[0])

    def list_artifacts(
        self,
        *,
        lineage_key: str | None = None,
        strategy_name: str | None = None,
        strategy_version: str | None = None,
        market_date: str | None = None,
        exchange: str | None = None,
        symbol: str | None = None,
        revision: int | None = None,
    ) -> list[StoredSignalArtifact]:
        clauses: list[str] = []
        values: list[Any] = []
        for column, value, field_name in (
            ("lineage_key", lineage_key, "lineage_key"),
            ("strategy_name", strategy_name, "strategy_name"),
            ("strategy_version", strategy_version, "strategy_version"),
            ("market_date", market_date, "market_date"),
            ("exchange", exchange, "exchange"),
            ("symbol", symbol, "symbol"),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(_validate_text(value, field_name))
        if revision is not None:
            if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
                raise ValueError("revision must be a positive integer")
            clauses.append("revision = ?")
            values.append(revision)
        if not any(
            value is not None
            for value in (lineage_key, strategy_name, market_date, exchange, symbol)
        ):
            raise ValueError(
                "list_artifacts requires an explicit lineage or subject filter; latest/all is never implicit"
            )
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM {_ARTIFACT_TABLE}{where} ORDER BY lineage_key, revision, artifact_key",
                values,
            ).fetchall()
            return [self._row_to_stored(row) for row in rows]

    def history(self, lineage_key: str) -> list[StoredSignalArtifact]:
        lineage_key = _validate_text(lineage_key, "lineage_key")
        rows = self.list_artifacts(lineage_key=lineage_key)
        if not rows:
            raise SignalArtifactNotFoundError("signal-artifact lineage matched zero rows")
        return rows

    list_history = history


class _ReadonlySignalArtifactStore(SignalArtifactStore):
    """Supported readonly construction, retaining the existing strict reader."""

    def __init__(self, database_path: str | Path, *,
                 expected_database_sha256: str | None = None) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._snapshot = readonly_snapshot(database_path, expected_database_sha256=expected_database_sha256)
        self._connection, self.fingerprint = self._snapshot.__enter__()
        self.database_path = self.fingerprint["path"]
        try:
            tables = {row[1]: row[2] for row in self._connection.execute("PRAGMA table_list")
                      if row[0] == "main" and not row[1].startswith("sqlite_")}
            if set(tables) != _REQUIRED_TABLES or any(kind != "table" for kind in tables.values()):
                raise SignalArtifactStoreOwnershipError("readonly store requires its exact plain-table ownership schema")
            marker = self._connection.execute(
                f"SELECT store_kind, schema_version, owner_token FROM {_META_TABLE}").fetchall()
            if len(marker) != 1 or tuple(marker[0]) != (STORE_KIND, SCHEMA_VERSION, _OWNER_TOKEN):
                raise SignalArtifactStoreOwnershipError("readonly store ownership marker is invalid")
            for table in sorted(_REQUIRED_TABLES):
                if any(row[6] != 0 for row in self._connection.execute(f'PRAGMA table_xinfo("{table}")')):
                    raise SignalArtifactStoreOwnershipError("readonly store refuses generated or hidden columns")
            triggers = {row[0] for row in self._connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            indexes = {row[0] for row in self._connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            if not _REQUIRED_TRIGGERS.issubset(triggers) or not _REQUIRED_INDEXES.issubset(indexes):
                raise SignalArtifactStoreOwnershipError("readonly store immutable descriptors are missing")
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._snapshot.__exit__(None, None, None)

    def save_artifact(self, *args: Any, **kwargs: Any) -> StoredSignalArtifact:
        raise ReadonlySnapshotError("readonly_store_write_forbidden")

    save = save_artifact
    append = save_artifact


__all__ = [
    "ReadonlySnapshotError",
    "snapshot_fingerprint",
    "readonly_snapshot",
    "SCHEMA_VERSION",
    "STORE_KIND",
    "SignalArtifactAmbiguousError",
    "SignalArtifactCollisionError",
    "SignalArtifactIntegrityError",
    "SignalArtifactNotFoundError",
    "SignalArtifactRevisionError",
    "SignalArtifactStore",
    "SignalArtifactStoreBusyError",
    "SignalArtifactStoreError",
    "SignalArtifactStoreOwnershipError",
    "SignalArtifactStoreProtectedPathError",
    "StoredSignalArtifact",
]
