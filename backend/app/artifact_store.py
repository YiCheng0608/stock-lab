"""Versioned, immutable persistence for calculated feature artifacts.

This module is deliberately separate from the application's SQLAlchemy models
and startup path.  A caller must opt in by supplying a database path.  The
database is owned by this module only; an existing database without the
artifact-store marker is rejected before any write is attempted.

The store persists the existing :class:`app.atr.ATRArtifact` representation,
not a second ATR implementation.  ``research_payload_json`` intentionally
excludes ``generated_at`` and attempt/run usage.  Those values describe the
write attempt, while the research payload describes the calculation itself.

SQLite triggers make the artifact and its observations/dependencies
append-only through ordinary SQL operations, including ``INSERT OR REPLACE``
on the parent table.  This is not a protection against a caller who directly
changes the SQLite schema or disables/replaces triggers.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .atr import ATRArtifact, ATRObservation
from .artifact_provenance import (
    ProvenanceContractError,
    normalize_atr_provenance,
    validate_stored_atr_provenance,
)


STORE_KIND = "taiwan-stock-research.feature-artifact"
SCHEMA_VERSION = 1
FEATURE_NAME = "atr14"
UTC = timezone.utc
MARKET_TIMEZONE = ZoneInfo("Asia/Taipei")

_MISSING = object()
_META_TABLE = "artifact_store_metadata"
_REQUIRED_TABLES = frozenset(
    {
        _META_TABLE,
        "feature_artifacts",
        "artifact_observations",
        "artifact_dependencies",
        "artifact_attempts",
    }
)
_REQUIRED_TRIGGERS = frozenset(
    {
        "feature_artifacts_immutable_update",
        "feature_artifacts_immutable_delete",
        "feature_artifacts_no_replace",
        "feature_artifacts_no_unique_replace",
        "artifact_observations_immutable_update",
        "artifact_observations_immutable_delete",
        "artifact_observations_no_replace",
        "artifact_observations_match_parent",
        "artifact_dependencies_immutable_update",
        "artifact_dependencies_immutable_delete",
        "artifact_dependencies_no_replace",
        "artifact_dependencies_match_parent",
        "artifact_attempts_no_replace",
        "artifact_attempts_immutable_update",
        "artifact_attempts_immutable_delete",
    }
)


class ArtifactStoreError(RuntimeError):
    """Base exception for artifact-store failures."""


class ArtifactStoreOwnershipError(ArtifactStoreError):
    """The supplied path is not an artifact-store database."""


class ArtifactCollisionError(ArtifactStoreError):
    """An identity already exists with a different research payload."""


class ArtifactAmbiguousError(ArtifactStoreError):
    """An explicit reader key still matches more than one artifact."""


class ArtifactStoreBusyError(ArtifactStoreError):
    """SQLite remained locked after the bounded connection timeout."""


def _timestamp(value: datetime | str, field: str) -> str:
    """Return a canonical UTC timestamp and reject naive timestamps."""

    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO timestamp with timezone") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(f"{field} must be a timezone-aware datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must not be naive")
    return parsed.astimezone(UTC).isoformat()


def _optional_timestamp(value: datetime | str | None, field: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value, field)


def _stored_timestamp(value: str, field: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactStoreError(f"stored {field} is not timezone-aware")
    return parsed.astimezone(UTC)


def _canonicalize(value: Any, *, field: str = "value") -> Any:
    """Normalize JSON-compatible values with deterministic timestamp handling."""

    if isinstance(value, datetime):
        return _timestamp(value, field)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field} mapping keys must be strings")
            child_field = f"{field}.{key}"
            if key.endswith("_at") or key in {"decision_at", "generated_at"}:
                if item is not None:
                    normalized[key] = _timestamp(item, child_field)
                else:
                    normalized[key] = None
            else:
                normalized[key] = _canonicalize(item, field=child_field)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item, field=f"{field}[]") for item in value]
    if isinstance(value, float):
        # json.dumps(..., allow_nan=False) is retained as a second guard.
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{field} must not be NaN or infinite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"{field} is not JSON-compatible: {type(value).__name__}")


def canonical_json(value: Any, *, field: str = "value") -> str:
    """Encode JSON with stable ordering and strict finite-number semantics."""

    normalized = _canonicalize(value, field=field)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be canonically encoded") from exc


def _digest(canonical_value: str) -> str:
    return hashlib.sha256(canonical_value.encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _market_date(value: date | str | datetime) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("market_date must not be a naive datetime")
        return value.astimezone(MARKET_TIMEZONE).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError("market_date must be an ISO date") from exc
    raise TypeError("market_date must be a date, ISO date, or aware datetime")


@dataclass(frozen=True)
class _Instrument:
    exchange: str
    symbol: str
    identity_json: str
    instrument_key: str
    legacy_reference: str | None


def _instrument(value: str | Mapping[str, Any]) -> _Instrument:
    """Normalize the required exchange+symbol identity.

    ``legacy_reference`` is stored as caller-supplied evidence only.  It is
    intentionally not a foreign key into the legacy research database.
    """

    legacy_reference: str | None = None
    if isinstance(value, str):
        parts = value.strip().split(":", 1)
        if len(parts) != 2:
            raise ValueError("instrument must include exchange and symbol, e.g. TWSE:2330")
        exchange, symbol = parts
    elif isinstance(value, Mapping):
        exchange = value.get("exchange")
        symbol = value.get("symbol")
        legacy_reference_value = value.get("legacy_reference")
        if legacy_reference_value is not None:
            legacy_reference = _text(legacy_reference_value, "instrument.legacy_reference")
    else:
        raise TypeError("instrument must be an exchange:symbol string or mapping")
    exchange = _text(exchange, "instrument.exchange").upper()
    symbol = _text(symbol, "instrument.symbol").upper()
    identity_json = canonical_json({"exchange": exchange, "symbol": symbol}, field="instrument")
    return _Instrument(
        exchange=exchange,
        symbol=symbol,
        identity_json=identity_json,
        instrument_key=_digest(identity_json),
        legacy_reference=legacy_reference,
    )


def _finite_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a finite number or null")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must not be NaN or infinite")
    return number


@dataclass(frozen=True)
class ArtifactAttempt:
    attempt_id: str
    artifact_key: str
    run_id: str | None
    attempted_at: datetime
    outcome: str


@dataclass(frozen=True)
class StoredATRArtifact:
    """A decoded artifact row returned by an explicit reader."""

    artifact_key: str
    exchange: str
    symbol: str
    legacy_reference: str | None
    market_date: date
    feature_name: str
    feature_version: str
    snapshot_id: str
    snapshot_hash: str
    decision_at: datetime
    generated_at: datetime
    price_basis: str
    calculation_config: Any
    settings_digest: str
    implementation_digest: str
    dependency_manifest: Any
    instrument_evidence: Any
    source_evidence: Any
    calendar_evidence: Any
    halt_evidence: Any
    previous_close_evidence: Any
    dependency_digest: str
    research_payload_hash: str
    artifact: ATRArtifact

    @property
    def instrument(self) -> dict[str, str]:
        return {"exchange": self.exchange, "symbol": self.symbol}

    @property
    def observations(self) -> tuple[ATRObservation, ...]:
        return self.artifact.observations


class ArtifactStore:
    """Explicitly opted-in SQLite store for immutable ATR artifacts."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            raise TypeError("database_path is required; ArtifactStore has no default database")
        self.database_path = str(database_path)
        self._path_existed = False
        if self.database_path != ":memory:":
            path = Path(self.database_path)
            if path.exists():
                self._path_existed = True
            else:
                # Claim a genuinely new path before connecting.  This avoids
                # two first openers both observing an empty sqlite_master and
                # attempting schema creation concurrently.
                try:
                    descriptor = os.open(
                        path,
                        os.O_CREAT | os.O_EXCL | os.O_RDWR,
                    )
                except FileExistsError:
                    self._path_existed = True
                else:
                    os.close(descriptor)
        self._lock = threading.RLock()
        self._connection = self._open_connection(self.database_path)
        try:
            self._initialize_or_validate()
        except Exception:
            self._connection.close()
            raise

    @staticmethod
    def _open_connection(database_path: str) -> sqlite3.Connection:
        if database_path == ":memory:":
            connection = sqlite3.connect(database_path, timeout=5.0, isolation_level=None)
        else:
            path = Path(database_path)
            if path.exists():
                # mode=rw ensures opening an existing path can never silently
                # create/replace it while validating ownership.
                uri = f"{path.resolve().as_uri()}?mode=rw"
                try:
                    connection = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
                except sqlite3.DatabaseError as exc:
                    raise ArtifactStoreOwnershipError(
                        f"existing path is not a readable SQLite artifact store: {path}"
                    ) from exc
            else:
                connection = sqlite3.connect(database_path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_or_validate(self) -> None:
        try:
            # Serialize first-time schema creation across two processes.  The
            # second initializer sees the committed marker after the lock is
            # released and validates instead of racing CREATE TABLE calls.
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
                    raise ArtifactStoreOwnershipError(
                        "refusing existing empty database without the artifact-store ownership marker"
                    )
                self._create_schema()
                self._connection.execute("COMMIT")
                return
            if _META_TABLE not in tables:
                raise ArtifactStoreOwnershipError(
                    "refusing existing database without the artifact-store ownership marker"
                )
            marker_rows = self._connection.execute(
                f"SELECT store_kind, schema_version FROM {_META_TABLE}"
            ).fetchall()
            if len(marker_rows) != 1 or marker_rows[0][0] != STORE_KIND:
                raise ArtifactStoreOwnershipError("artifact-store ownership marker is invalid")
            if marker_rows[0][1] != SCHEMA_VERSION:
                raise ArtifactStoreOwnershipError(
                    f"unsupported artifact-store schema version: {marker_rows[0][1]}"
                )
            unknown = tables - _REQUIRED_TABLES
            missing = _REQUIRED_TABLES - tables
            if unknown or missing:
                raise ArtifactStoreOwnershipError(
                    f"artifact-store schema mismatch (unknown={sorted(unknown)}, missing={sorted(missing)})"
                )
            trigger_names = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ).fetchall()
            }
            if not _REQUIRED_TRIGGERS.issubset(trigger_names):
                raise ArtifactStoreOwnershipError("artifact-store immutable triggers are missing")
            self._connection.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            if "locked" in str(exc).lower():
                raise ArtifactStoreBusyError(
                    "artifact database is locked while initializing; retry"
                ) from exc
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

            """
            CREATE TABLE feature_artifacts (
                artifact_key TEXT PRIMARY KEY,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                instrument_key TEXT NOT NULL,
                instrument_identity_json TEXT NOT NULL CHECK (json_valid(instrument_identity_json)),
                legacy_reference TEXT,
                market_date TEXT NOT NULL,
                feature_name TEXT NOT NULL,
                feature_version TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                decision_at TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                price_basis TEXT NOT NULL,
                calculation_config_json TEXT NOT NULL CHECK (json_valid(calculation_config_json)),
                settings_digest TEXT NOT NULL,
                implementation_digest TEXT NOT NULL,
                dependency_manifest_json TEXT NOT NULL CHECK (json_valid(dependency_manifest_json)),
                dependency_digest TEXT NOT NULL,
                research_payload_json TEXT NOT NULL CHECK (json_valid(research_payload_json)),
                research_payload_hash TEXT NOT NULL,
                UNIQUE (
                    instrument_key, market_date, feature_name, feature_version,
                    snapshot_id, snapshot_hash, decision_at, price_basis,
                    settings_digest, implementation_digest, dependency_digest
                )
            )
            """,

            """
            CREATE TABLE artifact_observations (
                artifact_key TEXT NOT NULL,
                observation_index INTEGER NOT NULL CHECK (observation_index >= 0),
                trading_date TEXT NOT NULL,
                true_range REAL,
                atr REAL,
                null_reason TEXT,
                valid_tr_count INTEGER NOT NULL CHECK (valid_tr_count >= 0),
                bar_present INTEGER NOT NULL CHECK (bar_present IN (0, 1)),
                is_suspended INTEGER NOT NULL CHECK (is_suspended IN (0, 1)),
                data_available_at TEXT,
                PRIMARY KEY (artifact_key, observation_index),
                UNIQUE (artifact_key, trading_date),
                FOREIGN KEY (artifact_key) REFERENCES feature_artifacts(artifact_key)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            )
            """,

            """
            CREATE TABLE artifact_dependencies (
                artifact_key TEXT NOT NULL,
                dependency_kind TEXT NOT NULL,
                evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
                evidence_digest TEXT NOT NULL,
                PRIMARY KEY (artifact_key, dependency_kind),
                FOREIGN KEY (artifact_key) REFERENCES feature_artifacts(artifact_key)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            )
            """,

            """
            CREATE TABLE artifact_attempts (
                attempt_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_key TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                run_id TEXT,
                attempted_at TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('created', 'idempotent_replay')),
                UNIQUE (artifact_key, attempt_id),
                FOREIGN KEY (artifact_key) REFERENCES feature_artifacts(artifact_key)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            )
            """,

            """
            CREATE TRIGGER feature_artifacts_immutable_update
            BEFORE UPDATE ON feature_artifacts
            BEGIN SELECT RAISE(ABORT, 'feature artifacts are immutable'); END;
            """,
            """
            CREATE TRIGGER feature_artifacts_immutable_delete
            BEFORE DELETE ON feature_artifacts
            BEGIN SELECT RAISE(ABORT, 'feature artifacts are immutable'); END;
            """,
            """
            CREATE TRIGGER feature_artifacts_no_replace
            BEFORE INSERT ON feature_artifacts
            WHEN EXISTS (SELECT 1 FROM feature_artifacts WHERE artifact_key = NEW.artifact_key)
            BEGIN SELECT RAISE(ABORT, 'artifact key already exists; use ArtifactStore'); END;
            """,
            """
            CREATE TRIGGER feature_artifacts_no_unique_replace
            BEFORE INSERT ON feature_artifacts
            WHEN EXISTS (
                SELECT 1 FROM feature_artifacts
                WHERE instrument_key = NEW.instrument_key
                  AND market_date = NEW.market_date
                  AND feature_name = NEW.feature_name
                  AND feature_version = NEW.feature_version
                  AND snapshot_id = NEW.snapshot_id
                  AND snapshot_hash = NEW.snapshot_hash
                  AND decision_at = NEW.decision_at
                  AND price_basis = NEW.price_basis
                  AND settings_digest = NEW.settings_digest
                  AND implementation_digest = NEW.implementation_digest
                  AND dependency_digest = NEW.dependency_digest
            )
            BEGIN SELECT RAISE(ABORT, 'artifact identity already exists; use ArtifactStore'); END;
            """,
            """
            CREATE TRIGGER artifact_observations_no_replace
            BEFORE INSERT ON artifact_observations
            WHEN EXISTS (
                SELECT 1 FROM artifact_observations
                WHERE artifact_key = NEW.artifact_key
                  AND (observation_index = NEW.observation_index OR trading_date = NEW.trading_date)
            )
            BEGIN SELECT RAISE(ABORT, 'artifact observation already exists'); END;
            """,
            """
            CREATE TRIGGER artifact_observations_match_parent
            BEFORE INSERT ON artifact_observations
            WHEN NOT EXISTS (
                SELECT 1
                FROM feature_artifacts AS a,
                     json_each(json_extract(a.research_payload_json, '$.atr_artifact.observations')) AS item
                WHERE a.artifact_key = NEW.artifact_key
                  AND CAST(item.key AS INTEGER) = NEW.observation_index
                  AND json_extract(item.value, '$.trading_date') = NEW.trading_date
                  AND json_extract(item.value, '$.true_range') IS NEW.true_range
                  AND json_extract(item.value, '$.atr') IS NEW.atr
                  AND json_extract(item.value, '$.null_reason') IS NEW.null_reason
                  AND json_extract(item.value, '$.valid_tr_count') IS NEW.valid_tr_count
                  AND json_extract(item.value, '$.bar_present') IS NEW.bar_present
                  AND json_extract(item.value, '$.is_suspended') IS NEW.is_suspended
                  AND json_extract(item.value, '$.data_available_at') IS NEW.data_available_at
            )
            BEGIN SELECT RAISE(ABORT, 'artifact observation does not match canonical payload'); END;
            """,
            """
            CREATE TRIGGER artifact_dependencies_no_replace
            BEFORE INSERT ON artifact_dependencies
            WHEN EXISTS (
                SELECT 1 FROM artifact_dependencies
                WHERE artifact_key = NEW.artifact_key AND dependency_kind = NEW.dependency_kind
            )
            BEGIN SELECT RAISE(ABORT, 'artifact dependency already exists'); END;
            """,
            """
            CREATE TRIGGER artifact_dependencies_match_parent
            BEFORE INSERT ON artifact_dependencies
            WHEN NEW.dependency_kind NOT IN ('manifest', 'instrument', 'source', 'calendar', 'halt', 'previous_close')
              OR NOT EXISTS (
                SELECT 1 FROM feature_artifacts AS a
                WHERE a.artifact_key = NEW.artifact_key
                  AND json_extract(a.research_payload_json,
                                   '$.dependency_evidence.' || NEW.dependency_kind) = json(NEW.evidence_json)
            )
            BEGIN SELECT RAISE(ABORT, 'artifact dependency does not match canonical payload'); END;
            """,
            """
            CREATE TRIGGER artifact_attempts_no_replace
            BEFORE INSERT ON artifact_attempts
            WHEN EXISTS (
                SELECT 1 FROM artifact_attempts
                WHERE artifact_key = NEW.artifact_key AND attempt_id = NEW.attempt_id
            )
            BEGIN SELECT RAISE(ABORT, 'artifact attempt already exists'); END;
            """,
            """
            CREATE TRIGGER artifact_attempts_immutable_update
            BEFORE UPDATE ON artifact_attempts
            BEGIN SELECT RAISE(ABORT, 'artifact attempts are immutable'); END;
            """,
            """
            CREATE TRIGGER artifact_attempts_immutable_delete
            BEFORE DELETE ON artifact_attempts
            BEGIN SELECT RAISE(ABORT, 'artifact attempts are immutable'); END;
            """,
            """
            CREATE TRIGGER artifact_observations_immutable_update
            BEFORE UPDATE ON artifact_observations
            BEGIN SELECT RAISE(ABORT, 'artifact observations are immutable'); END;
            """,
            """
            CREATE TRIGGER artifact_observations_immutable_delete
            BEFORE DELETE ON artifact_observations
            BEGIN SELECT RAISE(ABORT, 'artifact observations are immutable'); END;
            """,
            """
            CREATE TRIGGER artifact_dependencies_immutable_update
            BEFORE UPDATE ON artifact_dependencies
            BEGIN SELECT RAISE(ABORT, 'artifact dependencies are immutable'); END;
            """,
            """
            CREATE TRIGGER artifact_dependencies_immutable_delete
            BEFORE DELETE ON artifact_dependencies
            BEGIN SELECT RAISE(ABORT, 'artifact dependencies are immutable'); END;
            """,
        ]
        for index, statement in enumerate(statements):
            if index == 1:
                self._connection.execute(
                    statement,
                    (STORE_KIND, SCHEMA_VERSION, datetime.now(UTC).isoformat()),
                )
            else:
                self._connection.execute(statement)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "ArtifactStore":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the connection for diagnostics/tests; callers should not mutate schema."""

        return self._connection

    @staticmethod
    def _configuration(
        calculation_config: Any,
        config_snapshot: Any,
        artifact: ATRArtifact,
    ) -> tuple[Any, str]:
        if calculation_config is not _MISSING and config_snapshot is not _MISSING:
            raise ValueError("provide only one of calculation_config and config_snapshot")
        value = calculation_config if calculation_config is not _MISSING else config_snapshot
        if value is _MISSING or value is None or not isinstance(value, Mapping) or not value:
            raise ValueError("calculation_config must be a non-empty object")
        encoded = canonical_json(value, field="calculation_config")
        normalized = json.loads(encoded)
        required = ("algorithm", "period", "smoothing", "seed")
        missing = [key for key in required if key not in normalized]
        if "precision" not in normalized and "precision_policy" not in normalized:
            missing.append("precision")
        if missing:
            raise ValueError(f"calculation_config missing required fields: {', '.join(missing)}")
        if normalized["algorithm"] != artifact.algorithm:
            raise ValueError("calculation_config.algorithm must match ATRArtifact.algorithm")
        if not isinstance(normalized["period"], int) or isinstance(normalized["period"], bool):
            raise ValueError("calculation_config.period must be an integer")
        if normalized["period"] != artifact.period:
            raise ValueError("calculation_config.period must match ATRArtifact.period")
        for key in ("algorithm", "smoothing", "seed", "precision", "precision_policy"):
            if key in normalized and (
                normalized[key] is None
                or (isinstance(normalized[key], str) and not normalized[key].strip())
            ):
                raise ValueError(f"calculation_config.{key} must be explicit")
        for key in ("algorithm", "smoothing", "seed", "precision", "precision_policy"):
            if key in normalized and not isinstance(normalized[key], str):
                raise ValueError(f"calculation_config.{key} must be a string")
        return normalized, _digest(encoded)

    @staticmethod
    def _dependency_values(
        dependency_manifest: Any,
        instrument_evidence: Any,
        source_evidence: Any,
        calendar_evidence: Any,
        halt_evidence: Any,
        previous_close_evidence: Any,
    ) -> tuple[dict[str, Any], str, dict[str, str]]:
        if dependency_manifest is _MISSING:
            raise ValueError("dependency_manifest is required")
        if (
            dependency_manifest is None
            or not isinstance(dependency_manifest, (Mapping, list, tuple))
            or not dependency_manifest
        ):
            raise ValueError("dependency_manifest must be a non-empty object or list")
        if instrument_evidence is _MISSING:
            raise ValueError("instrument_evidence is required")
        if not isinstance(instrument_evidence, Mapping):
            raise TypeError("instrument_evidence must be an object")
        for field in ("source_ref", "snapshot_id", "snapshot_hash"):
            _text(instrument_evidence.get(field), f"instrument_evidence.{field}")
        if instrument_evidence.get("validation_status") != "caller_supplied_only":
            raise ValueError(
                "instrument_evidence.validation_status must be caller_supplied_only"
            )
        evidence_requirements = {
            "source": ("source_ref",),
            "calendar": ("calendar_ref", "source_ref"),
            "halt": ("source_ref",),
            "previous_close": ("source_ref",),
        }
        evidence_input = {
            "source": source_evidence,
            "calendar": calendar_evidence,
            "halt": halt_evidence,
            "previous_close": previous_close_evidence,
        }
        for kind, value in evidence_input.items():
            if value is _MISSING or not isinstance(value, Mapping) or not value:
                raise ValueError(f"{kind}_evidence must be a non-empty object")
            status = str(value.get("status", value.get("validation_status", ""))).casefold()
            reason = value.get("reason", value.get("reason_code"))
            if status in {
                "unknown",
                "unavailable",
                "not_available",
                "not_used",
                "unsupported",
            }:
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError(f"{kind}_evidence unknown status requires reason")
            elif not any(
                isinstance(value.get(field), str) and value[field].strip()
                for field in evidence_requirements[kind]
            ):
                raise ValueError(f"{kind}_evidence requires a source reference")
        values = {
            "manifest": dependency_manifest,
            "instrument": instrument_evidence,
            "source": source_evidence,
            "calendar": calendar_evidence,
            "halt": halt_evidence,
            "previous_close": previous_close_evidence,
        }
        normalized = json.loads(canonical_json(values, field="dependency_evidence"))
        digest = _digest(canonical_json(normalized, field="dependency_evidence"))
        row_json = {
            kind: canonical_json(normalized[kind], field=f"{kind}_evidence")
            for kind in ("manifest", "instrument", "source", "calendar", "halt", "previous_close")
        }
        return normalized, digest, row_json

    @staticmethod
    def _research_payload(
        *,
        instrument: _Instrument,
        market_date: date,
        feature_name: str,
        artifact: ATRArtifact,
        snapshot_id: str,
        snapshot_hash: str,
        decision_at: str,
        calculation_config: Any,
        settings_digest: str,
        implementation_digest: str,
        dependency_values: dict[str, Any],
        dependency_digest: str,
    ) -> tuple[str, str]:
        payload = {
            "instrument": {"exchange": instrument.exchange, "symbol": instrument.symbol},
            "instrument_legacy_reference": instrument.legacy_reference,
            "market_date": market_date.isoformat(),
            "feature_name": feature_name,
            "feature_version": artifact.feature_version,
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "decision_at": decision_at,
            "price_basis": artifact.price_basis,
            "calculation_config": calculation_config,
            "settings_digest": settings_digest,
            "implementation_digest": implementation_digest,
            "dependency_manifest": dependency_values["manifest"],
            "dependency_evidence": dependency_values,
            "dependency_digest": dependency_digest,
            "atr_artifact": artifact.to_dict(),
        }
        encoded = canonical_json(payload, field="research_payload")
        return encoded, _digest(encoded)

    @staticmethod
    def _validate_artifact(
        artifact: ATRArtifact,
        *,
        feature_name: str,
        snapshot_id: str,
    ) -> str:
        if not isinstance(artifact, ATRArtifact):
            raise TypeError("artifact must be an ATRArtifact")
        _text(feature_name, "feature_name")
        _text(artifact.feature_version, "artifact.feature_version")
        _text(artifact.algorithm, "artifact.algorithm")
        _text(artifact.price_basis, "artifact.price_basis")
        if not isinstance(artifact.period, int) or isinstance(artifact.period, bool) or artifact.period <= 0:
            raise ValueError("artifact.period must be a positive integer")
        if not isinstance(artifact.input_snapshot_ref, str) or artifact.input_snapshot_ref.strip() != snapshot_id:
            raise ValueError("snapshot_id must match ATRArtifact.input_snapshot_ref")
        if artifact.decision_at is None:
            raise ValueError("ATRArtifact.decision_at is required")
        return _timestamp(artifact.decision_at, "artifact.decision_at")

    @staticmethod
    def _validate_observation(observation: ATRObservation, index: int) -> tuple[Any, ...]:
        if not isinstance(observation.trading_date, date) or isinstance(observation.trading_date, datetime):
            raise TypeError(f"observations[{index}].trading_date must be a date")
        if not isinstance(observation.valid_tr_count, int) or isinstance(observation.valid_tr_count, bool):
            raise TypeError(f"observations[{index}].valid_tr_count must be an integer")
        if observation.valid_tr_count < 0:
            raise ValueError(f"observations[{index}].valid_tr_count must not be negative")
        if not isinstance(observation.bar_present, bool) or not isinstance(observation.is_suspended, bool):
            raise TypeError(f"observations[{index}] flags must be bools")
        if observation.null_reason is not None and not isinstance(observation.null_reason, str):
            raise TypeError(f"observations[{index}].null_reason must be a string or null")
        true_range = _finite_number(observation.true_range, f"observations[{index}].true_range")
        atr = _finite_number(observation.atr, f"observations[{index}].atr")
        if true_range is not None and true_range < 0:
            raise ValueError(f"observations[{index}].true_range must not be negative")
        if atr is not None and atr < 0:
            raise ValueError(f"observations[{index}].atr must not be negative")
        if atr is None and (
            not isinstance(observation.null_reason, str) or not observation.null_reason.strip()
        ):
            raise ValueError(
                f"observations[{index}].null_reason is required when atr is null"
            )
        available_at = _optional_timestamp(observation.data_available_at, f"observations[{index}].data_available_at")
        return (
            index,
            observation.trading_date.isoformat(),
            true_range,
            atr,
            observation.null_reason,
            observation.valid_tr_count,
            int(observation.bar_present),
            int(observation.is_suspended),
            available_at,
        )

    def _record_attempt(
        self,
        *,
        artifact_key: str,
        attempt_id: str | None,
        run_id: str | None,
        attempted_at: datetime | str | None,
        outcome: str,
    ) -> None:
        resolved_attempt_id = _text(attempt_id, "attempt_id") if attempt_id is not None else uuid.uuid4().hex
        resolved_run_id = None if run_id is None else _text(run_id, "run_id")
        existing = None
        if attempt_id is not None:
            existing = self._connection.execute(
                """
                SELECT run_id, attempted_at, outcome FROM artifact_attempts
                WHERE artifact_key = ? AND attempt_id = ?
                """,
                (artifact_key, resolved_attempt_id),
            ).fetchone()
        if existing is not None:
            requested_at = (
                _timestamp(attempted_at, "attempted_at") if attempted_at is not None else existing[1]
            )
            if (
                existing[0] != resolved_run_id
                or existing[1] != requested_at
            ):
                raise ArtifactStoreError(
                    f"attempt_id already exists with different run usage: {resolved_attempt_id}"
                )
            return
        resolved_attempted_at = (
            _timestamp(attempted_at, "attempted_at")
            if attempted_at is not None
            else datetime.now(UTC).isoformat()
        )
        self._connection.execute(
            """
            INSERT INTO artifact_attempts
                (artifact_key, attempt_id, run_id, attempted_at, outcome)
            VALUES (?, ?, ?, ?, ?)
            """,
            (artifact_key, resolved_attempt_id, resolved_run_id, resolved_attempted_at, outcome),
        )

    def save_atr_artifact(
        self,
        instrument: str | Mapping[str, Any],
        market_date: date | str | datetime,
        artifact: ATRArtifact,
        *,
        snapshot_hash: str,
        implementation_digest: str,
        dependency_manifest: Any = _MISSING,
        instrument_evidence: Any = _MISSING,
        source_evidence: Any = _MISSING,
        calendar_evidence: Any = _MISSING,
        halt_evidence: Any = _MISSING,
        previous_close_evidence: Any = _MISSING,
        calculation_config: Any = _MISSING,
        config_snapshot: Any = _MISSING,
        feature_name: str = FEATURE_NAME,
        snapshot_id: str | None = None,
        generated_at: datetime | str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        attempted_at: datetime | str | None = None,
        legacy_reference: str | None = None,
        _pre_commit_validator: Any = None,
    ) -> StoredATRArtifact:
        """Persist or idempotently replay one ATR artifact.

        All values which define the calculation identity are included in the
        identity digest.  ``generated_at``, ``attempt_id``, ``run_id`` and
        ``attempted_at`` are write-usage metadata and never enter that digest.
        ``market_date`` is explicitly the terminal date in the ATR observation
        sequence, so an artifact cannot be relabeled to an unrelated date.
        """

        normalized_instrument = _instrument(instrument)
        if legacy_reference is not None:
            normalized_instrument = _Instrument(
                normalized_instrument.exchange,
                normalized_instrument.symbol,
                normalized_instrument.identity_json,
                normalized_instrument.instrument_key,
                _text(legacy_reference, "legacy_reference"),
            )
        normalized_market_date = _market_date(market_date)
        normalized_feature_name = _text(feature_name, "feature_name")
        normalized_snapshot_id = _text(
            artifact.input_snapshot_ref if snapshot_id is None else snapshot_id,
            "snapshot_id",
        )
        normalized_snapshot_hash = _text(snapshot_hash, "snapshot_hash")
        normalized_implementation_digest = _text(implementation_digest, "implementation_digest")
        decision_at = self._validate_artifact(
            artifact,
            feature_name=normalized_feature_name,
            snapshot_id=normalized_snapshot_id,
        )
        if not artifact.observations:
            raise ValueError("ATRArtifact must contain at least one observation")
        observation_dates = [observation.trading_date for observation in artifact.observations]
        if any(current <= previous for previous, current in zip(observation_dates, observation_dates[1:])):
            raise ValueError("ATRArtifact observations must be strictly increasing")
        if normalized_market_date != observation_dates[-1]:
            raise ValueError(
                "market_date is the terminal ATR observation date and must match the final observation"
            )
        config, settings_digest = self._configuration(calculation_config, config_snapshot, artifact)
        dependency_values, dependency_digest, dependency_row_json = self._dependency_values(
            dependency_manifest,
            instrument_evidence,
            source_evidence,
            calendar_evidence,
            halt_evidence,
            previous_close_evidence,
        )
        payload_json, payload_hash = self._research_payload(
            instrument=normalized_instrument,
            market_date=normalized_market_date,
            feature_name=normalized_feature_name,
            artifact=artifact,
            snapshot_id=normalized_snapshot_id,
            snapshot_hash=normalized_snapshot_hash,
            decision_at=decision_at,
            calculation_config=config,
            settings_digest=settings_digest,
            implementation_digest=normalized_implementation_digest,
            dependency_values=dependency_values,
            dependency_digest=dependency_digest,
        )
        identity = {
            "schema_version": SCHEMA_VERSION,
            "instrument": {"exchange": normalized_instrument.exchange, "symbol": normalized_instrument.symbol},
            "market_date": normalized_market_date.isoformat(),
            "feature_name": normalized_feature_name,
            "feature_version": artifact.feature_version,
            "snapshot_id": normalized_snapshot_id,
            "snapshot_hash": normalized_snapshot_hash,
            "decision_at": decision_at,
            "price_basis": artifact.price_basis,
            "settings_digest": settings_digest,
            "implementation_digest": normalized_implementation_digest,
            "dependency_digest": dependency_digest,
        }
        artifact_key = _digest(canonical_json(identity, field="artifact_identity"))
        first_generated_at = _timestamp(generated_at, "generated_at") if generated_at is not None else datetime.now(UTC).isoformat()
        observation_rows = [
            self._validate_observation(observation, index)
            for index, observation in enumerate(artifact.observations)
        ]
        dependency_rows = [
            (kind, encoded, _digest(encoded))
            for kind, encoded in dependency_row_json.items()
        ]

        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._connection.execute(
                    "SELECT research_payload_json, research_payload_hash FROM feature_artifacts WHERE artifact_key = ?",
                    (artifact_key,),
                ).fetchone()
                if existing is not None:
                    if existing[1] != payload_hash or existing[0] != payload_json:
                        raise ArtifactCollisionError(
                            f"artifact identity collision for {artifact_key}; existing payload was preserved"
                        )
                    self._record_attempt(
                        artifact_key=artifact_key,
                        attempt_id=attempt_id,
                        run_id=run_id,
                        attempted_at=attempted_at,
                        outcome="idempotent_replay",
                    )
                    if _pre_commit_validator is not None:
                        _pre_commit_validator(artifact_key)
                    self._connection.execute("COMMIT")
                    return self.get_by_key(artifact_key)  # type: ignore[return-value]

                self._connection.execute(
                    """
                    INSERT INTO feature_artifacts (
                        artifact_key, exchange, symbol, instrument_key,
                        instrument_identity_json, legacy_reference, market_date,
                        feature_name, feature_version, snapshot_id, snapshot_hash,
                        decision_at, generated_at, price_basis,
                        calculation_config_json, settings_digest, implementation_digest,
                        dependency_manifest_json, dependency_digest,
                        research_payload_json, research_payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_key,
                        normalized_instrument.exchange,
                        normalized_instrument.symbol,
                        normalized_instrument.instrument_key,
                        normalized_instrument.identity_json,
                        normalized_instrument.legacy_reference,
                        normalized_market_date.isoformat(),
                        normalized_feature_name,
                        artifact.feature_version,
                        normalized_snapshot_id,
                        normalized_snapshot_hash,
                        decision_at,
                        first_generated_at,
                        artifact.price_basis,
                        canonical_json(config, field="calculation_config"),
                        settings_digest,
                        normalized_implementation_digest,
                        canonical_json(dependency_values["manifest"], field="dependency_manifest"),
                        dependency_digest,
                        payload_json,
                        payload_hash,
                    ),
                )
                self._connection.executemany(
                    """
                    INSERT INTO artifact_observations (
                        artifact_key, observation_index, trading_date, true_range, atr,
                        null_reason, valid_tr_count, bar_present, is_suspended,
                        data_available_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [(artifact_key, *row) for row in observation_rows],
                )
                self._connection.executemany(
                    """
                    INSERT INTO artifact_dependencies
                        (artifact_key, dependency_kind, evidence_json, evidence_digest)
                    VALUES (?, ?, ?, ?)
                    """,
                    [(artifact_key, *row) for row in dependency_rows],
                )
                self._record_attempt(
                    artifact_key=artifact_key,
                    attempt_id=attempt_id,
                    run_id=run_id,
                    attempted_at=attempted_at,
                    outcome="created",
                )
                if _pre_commit_validator is not None:
                    _pre_commit_validator(artifact_key)
                self._connection.execute("COMMIT")
            except ArtifactCollisionError:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
            except sqlite3.OperationalError as exc:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                if "locked" in str(exc).lower():
                    raise ArtifactStoreBusyError(
                        "artifact database is locked; retry the same save operation"
                    ) from exc
                raise
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return self.get_by_key(artifact_key)  # type: ignore[return-value]

    def save_atr_artifact_strict(
        self,
        instrument: str | Mapping[str, Any],
        market_date: date | str | datetime,
        artifact: ATRArtifact,
        *,
        provenance: Mapping[str, Any],
        feature_name: str = FEATURE_NAME,
        generated_at: datetime | str | None = None,
        attempt_id: str | None = None,
        run_id: str | None = None,
        attempted_at: datetime | str | None = None,
    ) -> StoredATRArtifact:
        """Persist an explicitly validated ``atr-provenance/v2`` artifact.

        This is intentionally a separate writer.  The existing schema-1
        ``save_atr_artifact`` remains the compatibility writer for historical
        minimal rows; it neither upgrades those rows nor silently opts them in
        to this contract.  All identity inputs for this method come from the
        caller-provided provenance object and are cross-checked against the
        ATR artifact before the ordinary immutable transaction is entered.
        """

        normalized = normalize_atr_provenance(
            provenance,
            artifact=artifact,
            instrument=instrument,
            market_date=market_date,
        )
        if normalized["feature"]["name"] != _text(feature_name, "feature_name"):
            raise ProvenanceContractError(
                "feature.name: does not match the explicit writer feature_name"
            )
        algorithm = normalized["algorithm"]
        implementation = algorithm["implementation"]
        source = normalized["source"]
        instrument_evidence = normalized["instrument"]
        saved = self.save_atr_artifact(
            instrument,
            market_date,
            artifact,
            snapshot_hash=source["snapshot_hash"],
            implementation_digest=implementation["digest"],
            dependency_manifest=normalized,
            instrument_evidence=instrument_evidence,
            source_evidence=source,
            calendar_evidence=normalized["calendar"],
            halt_evidence=normalized["halts"],
            previous_close_evidence=normalized["previous_close"],
            calculation_config=algorithm["config"],
            feature_name=feature_name,
            snapshot_id=source["snapshot_id"],
            generated_at=generated_at,
            attempt_id=attempt_id,
            run_id=run_id,
            attempted_at=attempted_at,
            legacy_reference=instrument_evidence.get("legacy_reference"),
            _pre_commit_validator=self.get_strict_by_key,
        )
        # Re-read through the strict path so the public result cannot claim v2
        # unless the persisted marker and all persisted structure still pass
        # validation.  This also makes malformed direct SQL changes visible to
        # callers that use the strict API.
        return self.get_strict_by_key(saved.artifact_key)  # type: ignore[return-value]

    # Short aliases keep the public operation discoverable without creating a
    # second storage path or a different payload contract.
    save = save_atr_artifact
    put = save_atr_artifact

    @staticmethod
    def _artifact_from_dict(value: Mapping[str, Any]) -> ATRArtifact:
        observations: list[ATRObservation] = []
        for index, row in enumerate(value.get("observations", [])):
            if not isinstance(row, Mapping):
                raise ArtifactStoreError(f"stored observations[{index}] is not an object")
            available_at = row.get("data_available_at")
            observations.append(
                ATRObservation(
                    trading_date=date.fromisoformat(str(row["trading_date"])),
                    true_range=row.get("true_range", row.get("tr")),
                    atr=row.get("atr"),
                    null_reason=row.get("null_reason"),
                    valid_tr_count=int(row["valid_tr_count"]),
                    bar_present=bool(row["bar_present"]),
                    is_suspended=bool(row["is_suspended"]),
                    data_available_at=(
                        _stored_timestamp(str(available_at), f"observations[{index}].data_available_at")
                        if available_at is not None
                        else None
                    ),
                )
            )
        decision_at = value.get("decision_at")
        return ATRArtifact(
            feature_version=str(value["feature_version"]),
            algorithm=str(value["algorithm"]),
            period=int(value["period"]),
            input_snapshot_ref=str(value["input_snapshot_ref"]),
            price_basis=str(value["price_basis"]),
            decision_at=(
                _stored_timestamp(str(decision_at), "artifact.decision_at")
                if decision_at is not None
                else None
            ),
            observations=tuple(observations),
            corporate_actions=tuple(dict(action) for action in value.get("corporate_actions", [])),
            corporate_action_coverage=dict(value.get("corporate_action_coverage", {})),
        )

    def _row_to_stored(self, row: sqlite3.Row) -> StoredATRArtifact:
        payload = json.loads(row["research_payload_json"])
        dependency_values = payload["dependency_evidence"]
        return StoredATRArtifact(
            artifact_key=row["artifact_key"],
            exchange=row["exchange"],
            symbol=row["symbol"],
            legacy_reference=row["legacy_reference"],
            market_date=date.fromisoformat(row["market_date"]),
            feature_name=row["feature_name"],
            feature_version=row["feature_version"],
            snapshot_id=row["snapshot_id"],
            snapshot_hash=row["snapshot_hash"],
            decision_at=_stored_timestamp(row["decision_at"], "decision_at"),
            generated_at=_stored_timestamp(row["generated_at"], "generated_at"),
            price_basis=row["price_basis"],
            calculation_config=json.loads(row["calculation_config_json"]),
            settings_digest=row["settings_digest"],
            implementation_digest=row["implementation_digest"],
            dependency_manifest=dependency_values["manifest"],
            instrument_evidence=dependency_values["instrument"],
            source_evidence=dependency_values["source"],
            calendar_evidence=dependency_values["calendar"],
            halt_evidence=dependency_values["halt"],
            previous_close_evidence=dependency_values["previous_close"],
            dependency_digest=row["dependency_digest"],
            research_payload_hash=row["research_payload_hash"],
            artifact=self._artifact_from_dict(payload["atr_artifact"]),
        )

    def get_by_key(self, artifact_key: str) -> StoredATRArtifact | None:
        """Read exactly one artifact by its stable key; never selects latest."""

        key = _text(artifact_key, "artifact_key")
        row = self._connection.execute(
            "SELECT * FROM feature_artifacts WHERE artifact_key = ?", (key,)
        ).fetchone()
        return None if row is None else self._row_to_stored(row)

    def get_strict_by_key(self, artifact_key: str) -> StoredATRArtifact | None:
        """Read exactly one artifact and require a fully valid v2 contract.

        Schema-1 rows written by the compatibility writer deliberately fail
        here; this method never upgrades or fills their missing evidence.
        """

        key = _text(artifact_key, "artifact_key")
        row = self._connection.execute(
            "SELECT * FROM feature_artifacts WHERE artifact_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["research_payload_json"])
        artifact = self._artifact_from_dict(payload["atr_artifact"])
        dependency_manifest = payload.get("dependency_evidence", {}).get("manifest")
        normalized = validate_stored_atr_provenance(
            dependency_manifest,
            artifact=artifact,
            instrument={"exchange": row["exchange"], "symbol": row["symbol"]},
            market_date=row["market_date"],
        )
        if normalized["feature"]["name"] != row["feature_name"]:
            raise ProvenanceContractError("stored.provenance.feature.name: does not match artifact row")
        if normalized["feature"]["version"] != row["feature_version"]:
            raise ProvenanceContractError("stored.provenance.feature.version: does not match artifact row")
        if normalized["source"]["snapshot_hash"] != row["snapshot_hash"]:
            raise ProvenanceContractError(
                "stored.provenance.source.snapshot.hash: does not match artifact row snapshot_hash"
            )
        if normalized["algorithm"]["config_digest"] != row["settings_digest"]:
            raise ProvenanceContractError(
                "stored.provenance.algorithm.config_digest: does not match artifact row settings_digest"
            )
        if normalized["algorithm"]["implementation"]["digest"] != row["implementation_digest"]:
            raise ProvenanceContractError(
                "stored.provenance.algorithm.implementation.digest: does not match artifact row"
            )
        if canonical_json(normalized["algorithm"]["config"], field="calculation_config") != row[
            "calculation_config_json"
        ]:
            raise ProvenanceContractError(
                "stored.provenance.algorithm.config: does not match artifact row"
            )
        if canonical_json(payload["dependency_evidence"]["manifest"], field="dependency_manifest") != row[
            "dependency_manifest_json"
        ] and normalized["contract"]["id"] == "atr-provenance/v2":
            raise ProvenanceContractError(
                "stored.provenance.dependency evidence does not match dependency manifest row"
            )
        normalized_kinds = {
            "instrument": "instrument",
            "source": "source",
            "calendar": "calendar",
            "halt": "halts",
            "previous_close": "previous_close",
        }
        for kind, normalized_kind in normalized_kinds.items():
            if canonical_json(payload["dependency_evidence"][kind], field=f"{kind}_evidence") != canonical_json(
                normalized[normalized_kind], field=f"{kind}_evidence"
            ):
                raise ProvenanceContractError(
                    f"stored.provenance.{kind}: does not match its persisted evidence projection"
                )
        if _digest(canonical_json(payload["dependency_evidence"], field="dependency_evidence")) != row[
            "dependency_digest"
        ]:
            raise ProvenanceContractError("stored.provenance dependency digest does not match artifact row")
        expected_identity_json = canonical_json(
            {"exchange": row["exchange"], "symbol": row["symbol"]},
            field="instrument",
        )
        if row["instrument_identity_json"] != expected_identity_json or row["instrument_key"] != _digest(
            expected_identity_json
        ):
            raise ProvenanceContractError("stored instrument identity does not match artifact row")
        return self._row_to_stored(row)

    read_strict = get_strict_by_key

    get = get_by_key
    read = get_by_key

    def get_atr(
        self,
        instrument: str | Mapping[str, Any],
        market_date: date | str | datetime,
        *,
        feature_version: str,
        snapshot_id: str,
        snapshot_hash: str,
        decision_at: datetime | str,
        feature_name: str = FEATURE_NAME,
    ) -> StoredATRArtifact | None:
        """Read by an explicit version, snapshot and as-of identity.

        If a caller creates multiple identities that differ by basis/config/
        dependency while keeping these reader fields equal, this method raises
        rather than guessing which one is "latest".  ``get_by_key`` remains
        the unambiguous exact-key reader.
        """

        normalized_instrument = _instrument(instrument)
        normalized_market_date = _market_date(market_date).isoformat()
        normalized_feature_name = _text(feature_name, "feature_name")
        normalized_feature_version = _text(feature_version, "feature_version")
        normalized_snapshot_id = _text(snapshot_id, "snapshot_id")
        normalized_snapshot_hash = _text(snapshot_hash, "snapshot_hash")
        normalized_decision_at = _timestamp(decision_at, "decision_at")
        rows = self._connection.execute(
            """
            SELECT * FROM feature_artifacts
            WHERE instrument_key = ? AND market_date = ? AND feature_name = ?
              AND feature_version = ? AND snapshot_id = ? AND snapshot_hash = ?
              AND decision_at = ?
            ORDER BY artifact_key
            """,
            (
                normalized_instrument.instrument_key,
                normalized_market_date,
                normalized_feature_name,
                normalized_feature_version,
                normalized_snapshot_id,
                normalized_snapshot_hash,
                normalized_decision_at,
            ),
        ).fetchall()
        if len(rows) > 1:
            raise ArtifactAmbiguousError(
                "explicit version/snapshot/as-of still matches multiple artifacts; use get_by_key"
            )
        return None if not rows else self._row_to_stored(rows[0])

    def get_strict_atr(
        self,
        instrument: str | Mapping[str, Any],
        market_date: date | str | datetime,
        *,
        feature_version: str,
        snapshot_id: str,
        snapshot_hash: str,
        decision_at: datetime | str,
        feature_name: str = FEATURE_NAME,
    ) -> StoredATRArtifact | None:
        """Explicit selector equivalent of :meth:`get_atr` with v2 validation."""

        stored = self.get_atr(
            instrument,
            market_date,
            feature_version=feature_version,
            snapshot_id=snapshot_id,
            snapshot_hash=snapshot_hash,
            decision_at=decision_at,
            feature_name=feature_name,
        )
        if stored is None:
            return None
        return self.get_strict_by_key(stored.artifact_key)

    def attempts_for(self, artifact_key: str) -> tuple[ArtifactAttempt, ...]:
        key = _text(artifact_key, "artifact_key")
        rows = self._connection.execute(
            """
            SELECT attempt_id, artifact_key, run_id, attempted_at, outcome
            FROM artifact_attempts WHERE artifact_key = ? ORDER BY attempt_row_id
            """,
            (key,),
        ).fetchall()
        return tuple(
            ArtifactAttempt(
                attempt_id=row["attempt_id"],
                artifact_key=row["artifact_key"],
                run_id=row["run_id"],
                attempted_at=_stored_timestamp(row["attempted_at"], "attempted_at"),
                outcome=row["outcome"],
            )
            for row in rows
        )


__all__ = [
    "ArtifactAmbiguousError",
    "ArtifactAttempt",
    "ArtifactCollisionError",
    "ArtifactStore",
    "ArtifactStoreBusyError",
    "ArtifactStoreError",
    "ArtifactStoreOwnershipError",
    "FEATURE_NAME",
    "ProvenanceContractError",
    "SCHEMA_VERSION",
    "STORE_KIND",
    "StoredATRArtifact",
    "canonical_json",
]
