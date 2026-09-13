"""Opt-in, append-only SQLite storage for ``time-evidence/v1`` records.

The store is intentionally separate from the application's legacy database
and from the C004 artifact-store schema.  It has no default path, no latest
reader, and no point-in-time gate.  It validates the complete canonical
payload again when reading so a damaged database cannot silently produce a
different time interpretation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from app.time_evidence import (
    TIME_EVIDENCE_VERSION,
    TimeEvidence,
    TimeEvidenceContractError,
    canonical_json,
    normalize_identity,
    sha256_json,
)

STORE_KIND = "time-evidence-store"
SCHEMA_VERSION = 1
_META_TABLE = "time_evidence_store_meta"
_ROW_TABLE = "time_evidence_rows"
_REQUIRED_TABLES = {_META_TABLE, _ROW_TABLE}
_REQUIRED_TRIGGERS = {
    "time_evidence_rows_immutable_update",
    "time_evidence_rows_immutable_delete",
    "time_evidence_rows_no_replace",
    "time_evidence_rows_no_identity_replace",
    "time_evidence_rows_no_rowid_replace",
    "time_evidence_rows_one_root",
}


class TimeEvidenceStoreError(RuntimeError):
    """Base storage error."""


class TimeEvidenceStoreOwnershipError(TimeEvidenceStoreError):
    """Raised when a path is not an owned v1 time-evidence store."""


class TimeEvidenceStoreProtectedPathError(TimeEvidenceStoreOwnershipError):
    """Raised for the official or application-local database paths."""


class TimeEvidenceStoreBusyError(TimeEvidenceStoreError):
    """Raised when SQLite cannot acquire the store transaction."""


class TimeEvidenceConflictError(TimeEvidenceStoreError):
    """Raised when a stable revision identity is reused with new content."""


class TimeEvidenceNotFoundError(TimeEvidenceStoreError):
    """Raised by an exact reader when its selector has zero rows."""


class TimeEvidenceIntegrityError(TimeEvidenceStoreError):
    """Raised when a stored row or its revision relation fails revalidation."""


class TimeEvidenceRevisionError(TimeEvidenceStoreError):
    """Raised for an invalid or cross-lineage supersedes relation."""


@dataclass(frozen=True)
class StoredTimeEvidence:
    evidence_key: str
    evidence: TimeEvidence
    payload_hash: str
    canonical_identity_hash: str
    row_id: int
    stored_at: str
    outcome: str = "read"

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_key": self.evidence_key,
            "payload_hash": self.payload_hash,
            "canonical_identity_hash": self.canonical_identity_hash,
            "row_id": self.row_id,
            "stored_at": self.stored_at,
            "outcome": self.outcome,
            "evidence": self.evidence.to_dict(),
        }

    @property
    def revision_id(self) -> str:
        return self.evidence.revision_id


def _digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identity_key(value: Mapping[str, Any] | str, field: str) -> tuple[dict[str, Any], str]:
    normalized = normalize_identity(value, field)
    return normalized, sha256_json(normalized)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


class TimeEvidenceStore:
    """Explicit-path SQLite store with immutable revision rows."""

    def __init__(self, database_path: str | Path | None = None, *, timeout: float = 5.0) -> None:
        if database_path is None:
            raise TypeError("database_path is required; TimeEvidenceStore has no default database")
        self.database_path = str(database_path)
        self._path_existed = False
        self._lock = threading.RLock()
        self._validate_path()
        if self.database_path != ":memory:":
            path = Path(self.database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                self._path_existed = True
            else:
                try:
                    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
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

    def _validate_path(self) -> None:
        if self.database_path == ":memory:":
            return
        root = Path(__file__).resolve().parents[2]
        resolved = Path(self.database_path).resolve()
        protected = {
            (root / "data" / "stock.db").resolve(),
            (root / ".local" / "data" / "stock.db").resolve(),
        }
        try:
            under_root = resolved.is_relative_to(root)
        except AttributeError:  # pragma: no cover - bundled Python is modern
            under_root = str(resolved).lower().startswith(str(root).lower() + os.sep)
        if resolved in protected or (under_root and ".local" in resolved.parts):
            raise TimeEvidenceStoreProtectedPathError(
                "time-evidence store refuses official data/stock.db and project .local paths"
            )

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def __enter__(self) -> "TimeEvidenceStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize_or_validate(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                if not row[0].startswith("sqlite_")
            }
            if not tables:
                if self._path_existed:
                    raise TimeEvidenceStoreOwnershipError(
                        "refusing an existing empty database without time-evidence ownership"
                    )
                self._create_schema()
                self._connection.execute("COMMIT")
                return
            if _META_TABLE not in tables:
                raise TimeEvidenceStoreOwnershipError(
                    "refusing existing database without time-evidence ownership marker"
                )
            marker_rows = self._connection.execute(
                f"SELECT store_kind, schema_version FROM {_META_TABLE}"
            ).fetchall()
            if len(marker_rows) != 1 or marker_rows[0][0] != STORE_KIND:
                raise TimeEvidenceStoreOwnershipError("time-evidence ownership marker is invalid")
            if marker_rows[0][1] != SCHEMA_VERSION:
                raise TimeEvidenceStoreOwnershipError(
                    f"unsupported time-evidence schema version: {marker_rows[0][1]}"
                )
            unknown = tables - _REQUIRED_TABLES
            missing = _REQUIRED_TABLES - tables
            if unknown or missing:
                raise TimeEvidenceStoreOwnershipError(
                    f"time-evidence schema mismatch (unknown={sorted(unknown)}, missing={sorted(missing)})"
                )
            trigger_names = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ).fetchall()
            }
            if not _REQUIRED_TRIGGERS.issubset(trigger_names):
                raise TimeEvidenceStoreOwnershipError("time-evidence immutable triggers are missing")
            self._connection.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            if "locked" in str(exc).lower():
                raise TimeEvidenceStoreBusyError("time-evidence database is locked; retry") from exc
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
                created_at TEXT NOT NULL
            )
            """,
            f"""
            INSERT INTO {_META_TABLE}(store_kind, schema_version, created_at)
            VALUES (?, ?, ?)
            """,
            f"""
            CREATE TABLE {_ROW_TABLE} (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_key TEXT NOT NULL UNIQUE,
                version TEXT NOT NULL CHECK (version = '{TIME_EVIDENCE_VERSION}'),
                subject_key TEXT NOT NULL,
                source_key TEXT NOT NULL,
                snapshot_key TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                revision_kind TEXT NOT NULL CHECK (revision_kind IN ('root', 'revision')),
                supersedes_key TEXT,
                canonical_identity_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                payload_hash TEXT NOT NULL,
                stored_at TEXT NOT NULL,
                UNIQUE (version, subject_key, source_key, revision_id)
            )
            """,
            f"""
            CREATE TRIGGER time_evidence_rows_immutable_update
            BEFORE UPDATE ON {_ROW_TABLE}
            BEGIN SELECT RAISE(ABORT, 'time-evidence rows are immutable'); END;
            """,
            f"""
            CREATE TRIGGER time_evidence_rows_immutable_delete
            BEFORE DELETE ON {_ROW_TABLE}
            BEGIN SELECT RAISE(ABORT, 'time-evidence rows are immutable'); END;
            """,
            f"""
            CREATE TRIGGER time_evidence_rows_no_replace
            BEFORE INSERT ON {_ROW_TABLE}
            WHEN EXISTS (SELECT 1 FROM {_ROW_TABLE} WHERE evidence_key = NEW.evidence_key)
            BEGIN SELECT RAISE(ABORT, 'time-evidence key already exists; use TimeEvidenceStore'); END;
            """,
            f"""
            CREATE TRIGGER time_evidence_rows_no_identity_replace
            BEFORE INSERT ON {_ROW_TABLE}
            WHEN EXISTS (
                SELECT 1 FROM {_ROW_TABLE}
                WHERE version = NEW.version
                  AND subject_key = NEW.subject_key
                  AND source_key = NEW.source_key
                  AND revision_id = NEW.revision_id
            )
            BEGIN SELECT RAISE(ABORT, 'time-evidence revision identity already exists'); END;
            """,
            f"""
            CREATE TRIGGER time_evidence_rows_no_rowid_replace
            BEFORE INSERT ON {_ROW_TABLE}
            WHEN EXISTS (SELECT 1 FROM {_ROW_TABLE} WHERE row_id = NEW.row_id)
            BEGIN SELECT RAISE(ABORT, 'time-evidence row id already exists'); END;
            """,
            f"""
            CREATE TRIGGER time_evidence_rows_one_root
            BEFORE INSERT ON {_ROW_TABLE}
            WHEN NEW.revision_kind = 'root'
              AND EXISTS (
                SELECT 1 FROM {_ROW_TABLE}
                WHERE version = NEW.version
                  AND subject_key = NEW.subject_key
                  AND source_key = NEW.source_key
                  AND revision_kind = 'root'
            )
            BEGIN SELECT RAISE(ABORT, 'time-evidence lineage already has a root revision'); END;
            """,
        ]
        for index, statement in enumerate(statements):
            if index == 1:
                self._connection.execute(statement, (STORE_KIND, SCHEMA_VERSION, _now_utc()))
            else:
                self._connection.execute(statement)

    def _normalized(self, evidence: TimeEvidence | Mapping[str, Any]) -> TimeEvidence:
        if isinstance(evidence, TimeEvidence):
            # Reparse the detached canonical form.  This keeps store writes
            # strict even when a caller constructed a mutable nested dict.
            return TimeEvidence.from_mapping(evidence.to_dict())
        return TimeEvidence.from_mapping(evidence)

    @staticmethod
    def _row_key(evidence: TimeEvidence) -> tuple[str, str, str, str, str, str]:
        subject_key = sha256_json(evidence.subject_identity)
        source_key = sha256_json(evidence.source_identity)
        snapshot_key = sha256_json(evidence.snapshot_identity)
        evidence_key = evidence.stable_identity_hash()
        return (
            evidence_key,
            subject_key,
            source_key,
            snapshot_key,
            evidence.revision_id,
            evidence.revision_identity.get("kind", "root"),
        )

    def append(self, evidence: TimeEvidence | Mapping[str, Any]) -> StoredTimeEvidence:
        """Append one root/revision, or return an identical retry.

        A revision's predecessor is resolved by its explicit revision id under
        the same version, subject, and source identity.  No implicit latest
        or as-of selection occurs here.
        """

        normalized = self._normalized(evidence)
        payload_json = normalized.canonical_payload()
        payload_hash = _digest_text(payload_json)
        (
            evidence_key,
            subject_key,
            source_key,
            snapshot_key,
            revision_id,
            revision_kind,
        ) = self._row_key(normalized)
        canonical_identity_hash = normalized.canonical_identity_hash()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._connection.execute(
                    f"SELECT * FROM {_ROW_TABLE} WHERE evidence_key = ?",
                    (evidence_key,),
                ).fetchone()
                if existing is not None:
                    stored = self._row_to_stored(existing)
                    if stored.payload_hash != payload_hash or stored.evidence.canonical_payload() != payload_json:
                        raise TimeEvidenceConflictError(
                            f"revision identity already exists with different payload: {revision_id}"
                        )
                    self._connection.execute("COMMIT")
                    return StoredTimeEvidence(
                        evidence_key=stored.evidence_key,
                        evidence=stored.evidence,
                        payload_hash=stored.payload_hash,
                        canonical_identity_hash=stored.canonical_identity_hash,
                        row_id=stored.row_id,
                        stored_at=stored.stored_at,
                        outcome="idempotent_replay",
                    )

                supersedes_key = self._validate_parent(
                    normalized,
                    subject_key=subject_key,
                    source_key=source_key,
                    evidence_key=evidence_key,
                )
                stored_at = _now_utc()
                self._connection.execute(
                    f"""
                    INSERT INTO {_ROW_TABLE}
                        (evidence_key, version, subject_key, source_key, snapshot_key,
                         revision_id, revision_kind, supersedes_key,
                         canonical_identity_hash, payload_json, payload_hash, stored_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_key,
                        normalized.version,
                        subject_key,
                        source_key,
                        snapshot_key,
                        revision_id,
                        revision_kind,
                        supersedes_key,
                        canonical_identity_hash,
                        payload_json,
                        payload_hash,
                        stored_at,
                    ),
                )
                row = self._connection.execute(
                    f"SELECT * FROM {_ROW_TABLE} WHERE evidence_key = ?",
                    (evidence_key,),
                ).fetchone()
                stored = self._row_to_stored(row, outcome="created")
                self._connection.execute("COMMIT")
                return stored
            except TimeEvidenceStoreError:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as exc:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise TimeEvidenceConflictError(str(exc)) from exc
            except sqlite3.OperationalError as exc:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                if "locked" in str(exc).lower():
                    raise TimeEvidenceStoreBusyError("time-evidence database is locked; retry") from exc
                raise
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def _validate_parent(
        self,
        evidence: TimeEvidence,
        *,
        subject_key: str,
        source_key: str,
        evidence_key: str,
    ) -> str | None:
        parent_id = evidence.supersedes
        if parent_id is None:
            if evidence.is_revision:
                raise TimeEvidenceRevisionError("revision must name a supersedes predecessor")
            existing_root = self._connection.execute(
                f"""
                SELECT 1 FROM {_ROW_TABLE}
                WHERE version = ? AND subject_key = ? AND source_key = ? AND revision_kind = 'root'
                LIMIT 1
                """,
                (evidence.version, subject_key, source_key),
            ).fetchone()
            if existing_root is not None:
                raise TimeEvidenceRevisionError("time-evidence lineage already has a root revision")
            return None
        if parent_id == evidence.revision_id:
            raise TimeEvidenceRevisionError("revision cannot supersede itself")
        parent = self._connection.execute(
            f"""
            SELECT * FROM {_ROW_TABLE}
            WHERE version = ? AND subject_key = ? AND source_key = ? AND revision_id = ?
            """,
            (evidence.version, subject_key, source_key, parent_id),
        ).fetchone()
        if parent is None:
            raise TimeEvidenceRevisionError(
                f"supersedes predecessor does not exist in the same source lineage: {parent_id}"
            )
        if parent["version"] != evidence.version or parent["subject_key"] != subject_key or parent["source_key"] != source_key:
            raise TimeEvidenceRevisionError("supersedes crosses version, subject, or source identity")
        if parent["evidence_key"] == evidence_key:
            raise TimeEvidenceRevisionError("revision cannot supersede itself")
        self._assert_no_cycle(parent["evidence_key"], evidence_key)
        # Strictly revalidate the predecessor while it is part of the same
        # transaction; a corrupt parent cannot become a new child.
        self._row_to_stored(parent)
        return str(parent["evidence_key"])

    def _assert_no_cycle(self, parent_key: str, new_key: str) -> None:
        seen: set[str] = set()
        current: str | None = parent_key
        while current is not None:
            if current == new_key:
                raise TimeEvidenceRevisionError("supersedes relation would create a cycle")
            if current in seen:
                raise TimeEvidenceIntegrityError("existing supersedes graph contains a cycle")
            seen.add(current)
            row = self._connection.execute(
                f"SELECT * FROM {_ROW_TABLE} WHERE evidence_key = ?",
                (current,),
            ).fetchone()
            if row is None:
                raise TimeEvidenceIntegrityError(
                    f"supersedes ancestor is missing from the store: {current}"
                )
            # Validate every ancestor's own payload and immediate relation.
            # Disable recursive ancestry here; this loop performs that walk
            # iteratively and can therefore detect a missing grandparent.
            self._row_to_stored(row, validate_ancestors=False)
            current = row["supersedes_key"]

    def _row_to_stored(
        self,
        row: sqlite3.Row,
        *,
        outcome: str = "read",
        validate_ancestors: bool = True,
    ) -> StoredTimeEvidence:
        if row is None:
            raise TimeEvidenceNotFoundError("time-evidence exact reader matched zero rows")
        try:
            payload = json.loads(row["payload_json"])
            evidence = TimeEvidence.from_mapping(payload)
        except (json.JSONDecodeError, TimeEvidenceContractError, ValueError, TypeError) as exc:
            raise TimeEvidenceIntegrityError("stored time-evidence payload fails v1 validation") from exc
        expected_payload = evidence.canonical_payload()
        expected_payload_hash = _digest_text(expected_payload)
        expected_key, expected_subject, expected_source, expected_snapshot, expected_revision, expected_kind = self._row_key(evidence)
        checks = {
            "payload_json": expected_payload == row["payload_json"],
            "payload_hash": expected_payload_hash == row["payload_hash"],
            "evidence_key": expected_key == row["evidence_key"],
            "subject_key": expected_subject == row["subject_key"],
            "source_key": expected_source == row["source_key"],
            "snapshot_key": expected_snapshot == row["snapshot_key"],
            "revision_id": expected_revision == row["revision_id"],
            "revision_kind": expected_kind == row["revision_kind"],
            "canonical_identity_hash": evidence.canonical_identity_hash() == row["canonical_identity_hash"],
        }
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            raise TimeEvidenceIntegrityError(f"stored time-evidence row seal mismatch: {failed}")
        parent_key = row["supersedes_key"]
        if evidence.supersedes is None:
            if parent_key is not None:
                raise TimeEvidenceIntegrityError("root row has an unexpected supersedes relation")
        else:
            if parent_key is None:
                raise TimeEvidenceIntegrityError("revision row has no supersedes relation")
            parent = self._connection.execute(
                f"""
                SELECT * FROM {_ROW_TABLE}
                WHERE version = ? AND subject_key = ? AND source_key = ? AND revision_id = ?
                """,
                (row["version"], row["subject_key"], row["source_key"], evidence.supersedes),
            ).fetchone()
            if parent is None or parent["evidence_key"] != parent_key:
                raise TimeEvidenceIntegrityError("stored supersedes relation is missing or crosses lineage")
            if validate_ancestors:
                self._assert_no_cycle(str(parent_key), str(row["evidence_key"]))
        return StoredTimeEvidence(
            evidence_key=str(row["evidence_key"]),
            evidence=evidence,
            payload_hash=str(row["payload_hash"]),
            canonical_identity_hash=str(row["canonical_identity_hash"]),
            row_id=int(row["row_id"]),
            stored_at=str(row["stored_at"]),
            outcome=outcome,
        )

    def read(self, evidence_key: str) -> StoredTimeEvidence:
        if not isinstance(evidence_key, str) or not evidence_key.strip():
            raise ValueError("evidence_key must be a non-empty string")
        with self._lock:
            row = self._connection.execute(
                f"SELECT * FROM {_ROW_TABLE} WHERE evidence_key = ?",
                (evidence_key.strip(),),
            ).fetchone()
            return self._row_to_stored(row)

    read_exact = read

    def read_revision(
        self,
        subject_identity: Mapping[str, Any] | str,
        source_identity: Mapping[str, Any] | str,
        revision_id: str,
        *,
        version: str = TIME_EVIDENCE_VERSION,
        snapshot_identity: Mapping[str, Any] | str | None = None,
    ) -> StoredTimeEvidence:
        if version != TIME_EVIDENCE_VERSION:
            raise ValueError(f"version must be {TIME_EVIDENCE_VERSION}")
        _, subject_key = _identity_key(subject_identity, "subject_identity")
        _, source_key = _identity_key(source_identity, "source_identity")
        if not isinstance(revision_id, str) or not revision_id.strip():
            raise ValueError("revision_id must be a non-empty string")
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM {_ROW_TABLE}
                WHERE version = ? AND subject_key = ? AND source_key = ? AND revision_id = ?
                """,
                (version, subject_key, source_key, revision_id.strip()),
            ).fetchall()
            if snapshot_identity is not None:
                _, snapshot_key = _identity_key(snapshot_identity, "snapshot_identity")
                rows = [row for row in rows if row["snapshot_key"] == snapshot_key]
            if len(rows) == 0:
                raise TimeEvidenceNotFoundError("time-evidence revision reader matched zero rows")
            if len(rows) != 1:
                raise TimeEvidenceIntegrityError("explicit revision reader is ambiguous")
            return self._row_to_stored(rows[0])

    def history(
        self,
        subject_identity: Mapping[str, Any] | str,
        source_identity: Mapping[str, Any] | str,
        *,
        version: str = TIME_EVIDENCE_VERSION,
        snapshot_identity: Mapping[str, Any] | str | None = None,
    ) -> tuple[StoredTimeEvidence, ...]:
        """Read an explicit lineage in stable append order, never ``latest``."""

        if version != TIME_EVIDENCE_VERSION:
            raise ValueError(f"version must be {TIME_EVIDENCE_VERSION}")
        _, subject_key = _identity_key(subject_identity, "subject_identity")
        _, source_key = _identity_key(source_identity, "source_identity")
        with self._lock:
            params: list[Any] = [version, subject_key, source_key]
            query = f"""
                SELECT * FROM {_ROW_TABLE}
                WHERE version = ? AND subject_key = ? AND source_key = ?
            """
            if snapshot_identity is not None:
                _, snapshot_key = _identity_key(snapshot_identity, "snapshot_identity")
                query += " AND snapshot_key = ?"
                params.append(snapshot_key)
            query += " ORDER BY row_id ASC"
            rows = self._connection.execute(query, params).fetchall()
            if not rows:
                raise TimeEvidenceNotFoundError("time-evidence history reader matched zero rows")
            return tuple(self._row_to_stored(row) for row in rows)

    def export_json(
        self,
        output_path: str | Path,
        subject_identity: Mapping[str, Any] | str,
        source_identity: Mapping[str, Any] | str,
        *,
        version: str = TIME_EVIDENCE_VERSION,
        snapshot_identity: Mapping[str, Any] | str | None = None,
    ) -> Path:
        """Publish an explicit lineage with atomic, no-clobber local output."""

        target = Path(output_path)
        if target.name in {"", ".", ".."}:
            raise ValueError("output_path must name a file")
        resolved_target = target.resolve()
        root = Path(__file__).resolve().parents[2]
        protected = {
            (root / "data" / "stock.db").resolve(),
            (root / ".local" / "data" / "stock.db").resolve(),
        }
        if self.database_path != ":memory:" and resolved_target == Path(self.database_path).resolve():
            raise TimeEvidenceStoreProtectedPathError("JSON export cannot target the active SQLite store")
        try:
            under_root = resolved_target.is_relative_to(root)
        except AttributeError:  # pragma: no cover - bundled Python is modern
            under_root = str(resolved_target).lower().startswith(str(root).lower() + os.sep)
        if resolved_target in protected or (under_root and ".local" in resolved_target.parts):
            raise TimeEvidenceStoreProtectedPathError("JSON export refuses official data and project .local paths")
        if target.exists():
            raise FileExistsError(f"refusing to overwrite existing JSON export: {target}")
        records = self.history(
            subject_identity,
            source_identity,
            version=version,
            snapshot_identity=snapshot_identity,
        )
        subject, _ = _identity_key(subject_identity, "subject_identity")
        source, _ = _identity_key(source_identity, "source_identity")
        payload = {
            "version": version,
            "selector": {
                "subject_identity": subject,
                "source_identity": source,
                "snapshot_identity": None
                if snapshot_identity is None
                else _identity_key(snapshot_identity, "snapshot_identity")[0],
            },
            "caller_provided_only": True,
            "availability_truth": "not_asserted",
            "records": [record.to_dict() for record in records],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(payload))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            # A same-directory hard-link is an atomic no-clobber publication:
            # it fails if a target appeared after the initial existence check.
            # The temporary name is then removed, leaving only the published
            # target.  This avoids os.replace(), which could destroy a file in
            # a TOCTOU race.
            os.link(temporary_name, target)
            os.unlink(temporary_name)
            temporary_name = ""
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return target


__all__ = [
    "SCHEMA_VERSION",
    "STORE_KIND",
    "StoredTimeEvidence",
    "TimeEvidenceConflictError",
    "TimeEvidenceIntegrityError",
    "TimeEvidenceNotFoundError",
    "TimeEvidenceRevisionError",
    "TimeEvidenceStore",
    "TimeEvidenceStoreBusyError",
    "TimeEvidenceStoreError",
    "TimeEvidenceStoreOwnershipError",
    "TimeEvidenceStoreProtectedPathError",
]
