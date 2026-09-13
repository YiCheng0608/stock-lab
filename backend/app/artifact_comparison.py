"""Offline, read-only comparison of legacy technical features and ATR v2.

This module deliberately does not import the application's database/session
startup helpers.  Both databases are opened with SQLite ``mode=ro`` and
``query_only`` and every selector is explicit.  The comparison is descriptive:
it reports values, differences, provenance and reasons for incomparability; it
does not rank one calculation as a strategy improvement.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .artifact_provenance import (
    PROVENANCE_CONTRACT_ID,
    ProvenanceContractError,
    validate_stored_atr_provenance,
)
from .atr import ATRArtifact, ATRObservation


UTC = timezone.utc
MARKET_TIMEZONE = ZoneInfo("Asia/Taipei")


class ComparisonError(RuntimeError):
    """Base error for an explicit offline comparison."""


class ComparisonSelectorError(ComparisonError):
    """A required selector is absent or only partially specified."""


class ComparisonNotFoundError(ComparisonError):
    """An explicit selector matched no row."""


class ComparisonAmbiguousError(ComparisonError):
    """An explicit selector matched more than one row or identity."""


class LegacyReaderOwnershipError(ComparisonError):
    """The supplied legacy path is not a readable technical-feature database."""


class LegacySnapshotMismatchError(ComparisonError):
    """The caller's expected legacy file fingerprint is not the opened file."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ComparisonSelectorError(f"{field} is required")
    return value.strip()


def _identity(instrument: Mapping[str, Any] | str) -> tuple[str, str]:
    if isinstance(instrument, str):
        parts = instrument.strip().split(":", 1)
        if len(parts) != 2:
            raise ComparisonSelectorError("instrument must include exchange:symbol")
        exchange, symbol = parts
    elif isinstance(instrument, Mapping):
        exchange, symbol = instrument.get("exchange"), instrument.get("symbol")
    else:
        raise ComparisonSelectorError("instrument must be an exchange:symbol string or object")
    return _text(exchange, "instrument.exchange").upper(), _text(symbol, "instrument.symbol").upper()


def _market_date(value: date | str | datetime) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ComparisonSelectorError("market_date datetime must not be naive")
        return value.astimezone(MARKET_TIMEZONE).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ComparisonSelectorError("market_date must be an ISO date") from exc
    raise ComparisonSelectorError("market_date must be a date, ISO date, or aware datetime")


def _timestamp(value: datetime | str, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ComparisonSelectorError(f"{field} must be an ISO timestamp with timezone") from exc
    else:
        raise ComparisonSelectorError(f"{field} must be a timezone-aware datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ComparisonSelectorError(f"{field} must not be naive")
    return parsed.astimezone(UTC).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_no_sidecars(path: Path, *, role: str) -> None:
    sidecars = [Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")]
    present_sidecars = [str(sidecar) for sidecar in sidecars if sidecar.exists()]
    if present_sidecars:
        raise ComparisonError(
            f"{role} database has live SQLite sidecars; snapshot must be a stable checkpoint: {present_sidecars}"
        )


def _open_readonly(path_value: str | Path, *, role: str) -> tuple[sqlite3.Connection, Path, str]:
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        raise ComparisonError(f"{role} database path must exist and be a regular file: {path}")
    _assert_no_sidecars(path, role=role)
    try:
        fingerprint = _file_sha256(path)
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
    except (OSError, sqlite3.DatabaseError) as exc:
        raise ComparisonError(f"cannot open {role} database read-only: {path}") from exc
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ComparisonError(f"{role} database did not enable query_only")
    except Exception:
        connection.close()
        raise
    return connection, path, fingerprint


@dataclass(frozen=True)
class LegacyFeatureSelector:
    """Caller declaration for a legacy feature snapshot/version.

    Legacy ``technical_features`` does not contain these versioned fields, so
    they are never presented as database-verified.  ``snapshot_sha256`` is an
    optional expected hash of the opened legacy SQLite file; omission keeps the
    value readable but makes the comparison explicitly incomparable.
    """

    snapshot_id: str
    feature_version: str
    price_basis: str | None = None
    snapshot_sha256: str | None = None
    row_id: int | None = None

    def validate(self) -> None:
        _text(self.snapshot_id, "legacy_snapshot_id")
        _text(self.feature_version, "legacy_feature_version")
        if self.price_basis is not None:
            _text(self.price_basis, "legacy_price_basis")
        if self.snapshot_sha256 is not None:
            expected = _text(self.snapshot_sha256, "legacy_snapshot_sha256").casefold()
            if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
                raise ComparisonSelectorError("legacy_snapshot_sha256 must be a SHA-256 hex digest")
        if self.row_id is not None and (isinstance(self.row_id, bool) or not isinstance(self.row_id, int)):
            raise ComparisonSelectorError("legacy row_id must be an integer")


@dataclass(frozen=True)
class ArtifactSelector:
    """Either an exact artifact key or a complete version/snapshot/as-of key."""

    artifact_key: str | None = None
    feature_name: str | None = None
    feature_version: str | None = None
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    decision_at: datetime | str | None = None

    def validate(self, field: str) -> None:
        if self.artifact_key is not None:
            _text(self.artifact_key, f"{field}.artifact_key")
            return
        fields = {
            "feature_name": self.feature_name,
            "feature_version": self.feature_version,
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "decision_at": self.decision_at,
        }
        missing = [name for name, value in fields.items() if value is None]
        if missing:
            raise ComparisonSelectorError(
                f"{field} requires artifact_key or complete selector: {', '.join(missing)}"
            )
        for name, value in fields.items():
            if name == "decision_at":
                _timestamp(value, f"{field}.{name}")
            else:
                _text(value, f"{field}.{name}")


@dataclass(frozen=True)
class LegacyFeatureObservation:
    value: float | None
    reason: str | None
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "reason": self.reason, "provenance": self.provenance}


@dataclass(frozen=True)
class ComparisonPoint:
    label: str
    value: float | None
    reason: str | None
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "reason": self.reason,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class ATRComparisonResult:
    instrument: dict[str, str]
    market_date: date
    legacy_atr: ComparisonPoint
    asof_observations: tuple[ComparisonPoint, ComparisonPoint]
    differences: dict[str, float | None]
    diagnostic_differences: dict[str, float | None]
    comparability: dict[str, Any]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": dict(self.instrument),
            "market_date": self.market_date.isoformat(),
            "legacy_atr": self.legacy_atr.to_dict(),
            "asof_observations": [point.to_dict() for point in self.asof_observations],
            "differences": dict(self.differences),
            "diagnostic_differences": dict(self.diagnostic_differences),
            "comparability": dict(self.comparability),
            "provenance": dict(self.provenance),
        }


class LegacyTechnicalFeaturesReader:
    """Read one legacy ``technical_features`` row without opening the app DB."""

    def __init__(self, database_path: str | Path) -> None:
        self._connection, self.database_path, self.file_sha256 = _open_readonly(
            database_path, role="legacy"
        )
        self._validate_schema()

    def _validate_schema(self) -> None:
        tables = {
            row[0]
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not {"technical_features", "instruments"}.issubset(tables):
            self.close()
            raise LegacyReaderOwnershipError(
                "legacy database must contain instruments and technical_features"
            )
        columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(technical_features)").fetchall()
        }
        required = {"id", "instrument_id", "trading_date", "features_json", "source", "created_at"}
        if not required.issubset(columns):
            self.close()
            raise LegacyReaderOwnershipError("technical_features schema is missing required columns")
        instrument_columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(instruments)").fetchall()
        }
        if not {"id", "exchange", "symbol"}.issubset(instrument_columns):
            self.close()
            raise LegacyReaderOwnershipError("instruments schema is missing exchange/symbol identity")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "LegacyTechnicalFeaturesReader":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def read_exact(
        self,
        instrument: Mapping[str, Any] | str,
        market_date: date | str | datetime,
        *,
        selector: LegacyFeatureSelector,
    ) -> LegacyFeatureObservation:
        selector.validate()
        exchange, symbol = _identity(instrument)
        day = _market_date(market_date).isoformat()
        if selector.snapshot_sha256 is not None and selector.snapshot_sha256.casefold() != self.file_sha256.casefold():
            raise LegacySnapshotMismatchError(
                "legacy_snapshot_sha256 does not match the opened legacy file"
            )
        self._connection.execute("BEGIN")
        try:
            instrument_rows = self._connection.execute(
                """
                SELECT id, exchange, symbol FROM instruments
                WHERE upper(trim(exchange)) = ? AND upper(trim(symbol)) = ?
                ORDER BY id
                """,
                (exchange, symbol),
            ).fetchall()
            if not instrument_rows:
                raise ComparisonNotFoundError(
                    f"no legacy instrument mapping for {exchange}:{symbol}"
                )
            if len(instrument_rows) > 1:
                raise ComparisonAmbiguousError(
                    "legacy exchange+symbol maps to multiple instrument ids"
                )
            instrument_id = instrument_rows[0]["id"]
            clauses = [
                "tf.instrument_id = ?",
                "tf.trading_date = ?",
            ]
            params: list[Any] = [instrument_id, day]
            if selector.row_id is not None:
                clauses.append("tf.id = ?")
                params.append(selector.row_id)
            rows = self._connection.execute(
                f"""
                SELECT tf.id, tf.instrument_id, tf.trading_date, tf.features_json,
                       tf.source, tf.created_at, i.exchange, i.symbol
                FROM technical_features AS tf
                JOIN instruments AS i ON i.id = tf.instrument_id
                WHERE {' AND '.join(clauses)}
                ORDER BY tf.id
                """,
                params,
            ).fetchall()
            if not rows:
                raise ComparisonNotFoundError(
                    f"no legacy technical_features row for {exchange}:{symbol} on {day}"
                )
            if len(rows) > 1:
                raise ComparisonAmbiguousError(
                    "legacy selector matched multiple rows; unique exchange+symbol+market_date is required"
                )
            row = rows[0]
            if str(row["exchange"]).strip().upper() != exchange or str(row["symbol"]).strip().upper() != symbol:
                raise ComparisonAmbiguousError("legacy instrument identity did not round-trip")
            try:
                features = row["features_json"]
                if isinstance(features, str):
                    features = json.loads(features)
                if not isinstance(features, Mapping):
                    raise TypeError
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ComparisonError("legacy features_json is not a JSON object") from exc
            value = features.get("atr14")
            reason: str | None = None
            if "atr14" not in features:
                reason = "legacy_atr_missing"
            elif value is None:
                reason = "legacy_atr_null"
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                value = None
                reason = "legacy_atr_invalid"
            elif value != value or value in (float("inf"), float("-inf")):
                value = None
                reason = "legacy_atr_invalid"
            else:
                value = float(value)
            row_fingerprint = hashlib.sha256(
                _canonical_json(
                    {
                        "id": row["id"],
                        "instrument_id": row["instrument_id"],
                        "exchange": exchange,
                        "symbol": symbol,
                        "trading_date": row["trading_date"],
                        "features_json": features,
                        "source": row["source"],
                        "created_at": row["created_at"],
                    }
                ).encode("utf-8")
            ).hexdigest()
            return LegacyFeatureObservation(
                value=value,
                reason=reason,
                provenance={
                    "validation_status": "caller_supplied_only",
                    "database_role": "legacy_technical_features",
                    "row_id": row["id"],
                    "instrument_id": row["instrument_id"],
                    "instrument": {"exchange": exchange, "symbol": symbol},
                    "market_date": day,
                    "legacy_snapshot_id": selector.snapshot_id,
                    "legacy_feature_version": selector.feature_version,
                    "legacy_price_basis": selector.price_basis,
                    "legacy_snapshot_sha256": self.file_sha256,
                    "legacy_row_fingerprint": row_fingerprint,
                    "source": row["source"],
                    "created_at": row["created_at"],
                },
            )
        finally:
            try:
                _assert_no_sidecars(self.database_path, role="legacy")
                after = _file_sha256(self.database_path)
                if after != self.file_sha256:
                    raise LegacySnapshotMismatchError(
                        "legacy SQLite file changed while the read transaction was open"
                    )
            finally:
                self._connection.execute("ROLLBACK")


def _decode_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ComparisonError(f"stored {field} is not a timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ComparisonError(f"stored {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ComparisonError(f"stored {field} is naive")
    return parsed.astimezone(UTC)


def _decode_artifact(value: Mapping[str, Any]) -> ATRArtifact:
    try:
        observations = tuple(
            ATRObservation(
                trading_date=date.fromisoformat(str(item["trading_date"])),
                true_range=item.get("true_range", item.get("tr")),
                atr=item.get("atr"),
                null_reason=item.get("null_reason"),
                valid_tr_count=int(item["valid_tr_count"]),
                bar_present=bool(item["bar_present"]),
                is_suspended=bool(item["is_suspended"]),
                data_available_at=(
                    _decode_timestamp(item["data_available_at"], "observation.data_available_at")
                    if item.get("data_available_at") is not None
                    else None
                ),
            )
            for item in value["observations"]
        )
        decision_at = value.get("decision_at")
        return ATRArtifact(
            feature_version=str(value["feature_version"]),
            algorithm=str(value["algorithm"]),
            period=int(value["period"]),
            input_snapshot_ref=str(value["input_snapshot_ref"]),
            price_basis=str(value["price_basis"]),
            decision_at=(None if decision_at is None else _decode_timestamp(decision_at, "artifact.decision_at")),
            observations=observations,
            corporate_actions=tuple(dict(item) for item in value.get("corporate_actions", [])),
            corporate_action_coverage=dict(value.get("corporate_action_coverage", {})),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ComparisonError("stored ATR payload is malformed") from exc


class ReadonlyArtifactReader:
    """Read strict v2 artifacts from a separately supplied artifact database."""

    def __init__(self, database_path: str | Path) -> None:
        self._connection, self.database_path, self.file_sha256 = _open_readonly(
            database_path, role="artifact"
        )
        self._validate_schema()

    def _validate_schema(self) -> None:
        tables = {
            row[0]
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {
            "artifact_store_metadata",
            "feature_artifacts",
            "artifact_observations",
            "artifact_dependencies",
            "artifact_attempts",
        }
        if not required.issubset(tables):
            self.close()
            raise ComparisonError("artifact database is missing schema-1 artifact tables")
        marker = self._connection.execute(
            "SELECT store_kind, schema_version FROM artifact_store_metadata"
        ).fetchall()
        if len(marker) != 1 or marker[0][0] != "taiwan-stock-research.feature-artifact" or marker[0][1] != 1:
            self.close()
            raise ComparisonError("artifact database ownership or schema version is unsupported")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "ReadonlyArtifactReader":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def _decode_row(
        self,
        row: sqlite3.Row,
        *,
        exchange: str,
        symbol: str,
        day: str,
    ) -> tuple[ATRArtifact, dict[str, Any]]:
        payload_text = row["research_payload_json"]
        try:
            if hashlib.sha256(payload_text.encode("utf-8")).hexdigest() != row["research_payload_hash"]:
                raise ComparisonError("stored research payload hash does not match payload")
            payload = json.loads(payload_text)
            artifact = _decode_artifact(payload["atr_artifact"])
            dependency_evidence = payload["dependency_evidence"]
            manifest = dependency_evidence["manifest"]
            normalized = validate_stored_atr_provenance(
                manifest,
                artifact=artifact,
                instrument={"exchange": exchange, "symbol": symbol},
                market_date=day,
            )
        except ProvenanceContractError as exc:
            raise ProvenanceContractError(
                f"artifact {row['artifact_key']} does not satisfy strict v2 provenance: {exc}"
            ) from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ComparisonError("stored strict artifact payload is malformed") from exc
        if normalized["source"]["snapshot_id"] != row["snapshot_id"]:
            raise ComparisonError("strict source snapshot id does not match artifact row")
        if normalized["source"]["snapshot_hash"] != row["snapshot_hash"]:
            raise ComparisonError("strict source snapshot hash does not match artifact row")
        if normalized["algorithm"]["implementation"]["digest"] != row["implementation_digest"]:
            raise ComparisonError("strict implementation digest does not match artifact row")
        if normalized["algorithm"]["config_digest"] != row["settings_digest"]:
            raise ComparisonError("strict config digest does not match artifact row")
        if _canonical_json(normalized["algorithm"]["config"]) != row["calculation_config_json"]:
            raise ComparisonError("strict config does not match artifact row")
        if _canonical_json(dependency_evidence["manifest"]) != row["dependency_manifest_json"]:
            raise ComparisonError("strict manifest does not match artifact row")
        if hashlib.sha256(_canonical_json(dependency_evidence).encode("utf-8")).hexdigest() != row[
            "dependency_digest"
        ]:
            raise ComparisonError("strict dependency digest does not match artifact row")
        normalized_kinds = {
            "instrument": "instrument",
            "source": "source",
            "calendar": "calendar",
            "halt": "halts",
            "previous_close": "previous_close",
        }
        for kind, normalized_kind in normalized_kinds.items():
            if _canonical_json(dependency_evidence[kind]) != _canonical_json(normalized[normalized_kind]):
                raise ComparisonError(f"strict {kind} evidence projection does not match manifest")
        if artifact.feature_version != row["feature_version"] or artifact.price_basis != row["price_basis"]:
            raise ComparisonError("stored ATR payload does not match artifact row identity")
        if _timestamp(artifact.decision_at, "artifact.decision_at") != row["decision_at"]:
            raise ComparisonError("stored ATR payload decision_at does not match artifact row")
        return artifact, normalized

    def read_exact(
        self,
        instrument: Mapping[str, Any] | str,
        market_date: date | str | datetime,
        *,
        selector: ArtifactSelector,
    ) -> tuple[ATRArtifact, dict[str, Any], str]:
        selector.validate("artifact")
        exchange, symbol = _identity(instrument)
        day = _market_date(market_date).isoformat()
        self._connection.execute("BEGIN")
        try:
            if selector.artifact_key is not None:
                rows = self._connection.execute(
                    "SELECT * FROM feature_artifacts WHERE artifact_key = ?",
                    (selector.artifact_key.strip(),),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """
                    SELECT * FROM feature_artifacts
                    WHERE upper(trim(exchange)) = ? AND upper(trim(symbol)) = ?
                      AND market_date = ? AND feature_name = ?
                      AND feature_version = ? AND snapshot_id = ?
                      AND snapshot_hash = ? AND decision_at = ?
                    ORDER BY artifact_key
                    """,
                    (
                        exchange,
                        symbol,
                        day,
                        selector.feature_name,
                        selector.feature_version,
                        selector.snapshot_id,
                        selector.snapshot_hash,
                        _timestamp(selector.decision_at, "artifact.decision_at"),
                    ),
                ).fetchall()
            if not rows:
                raise ComparisonNotFoundError("explicit artifact selector matched no row")
            if len(rows) > 1:
                raise ComparisonAmbiguousError("explicit artifact selector matched multiple rows")
            row = rows[0]
            if str(row["exchange"]).strip().upper() != exchange or str(row["symbol"]).strip().upper() != symbol:
                raise ComparisonAmbiguousError("artifact selector key crossed exchange+symbol identity")
            if row["market_date"] != day:
                raise ComparisonSelectorError("artifact selector key does not match requested market_date")
            if selector.artifact_key is not None:
                optional_checks = {
                    "feature_name": selector.feature_name,
                    "feature_version": selector.feature_version,
                    "snapshot_id": selector.snapshot_id,
                    "snapshot_hash": selector.snapshot_hash,
                }
                for field, expected in optional_checks.items():
                    if expected is not None and row[field] != expected:
                        raise ComparisonSelectorError(f"artifact key does not match optional {field}")
                if selector.decision_at is not None and row["decision_at"] != _timestamp(
                    selector.decision_at, "artifact.decision_at"
                ):
                    raise ComparisonSelectorError("artifact key does not match optional decision_at")
            artifact, provenance = self._decode_row(
                row, exchange=exchange, symbol=symbol, day=day
            )
            observation = next(
                (item for item in artifact.observations if item.trading_date.isoformat() == day),
                None,
            )
            if observation is None:
                raise ComparisonError("strict artifact has no observation for requested market_date")
            point_provenance = {
                "validation_status": "strict_v2_revalidated",
                "artifact_key": row["artifact_key"],
                "feature_name": row["feature_name"],
                "feature_version": row["feature_version"],
                "snapshot_id": row["snapshot_id"],
                "snapshot_hash": row["snapshot_hash"],
                "decision_at": row["decision_at"],
                "generated_at": row["generated_at"],
                "price_basis": row["price_basis"],
                "settings_digest": row["settings_digest"],
                "implementation_digest": row["implementation_digest"],
                "dependency_digest": row["dependency_digest"],
                "provenance_contract": PROVENANCE_CONTRACT_ID,
                "provenance": provenance,
                "observation": {
                    "trading_date": day,
                    "null_reason": observation.null_reason,
                    "valid_tr_count": observation.valid_tr_count,
                },
            }
            return artifact, point_provenance, row["artifact_key"]
        finally:
            try:
                _assert_no_sidecars(self.database_path, role="artifact")
                after = _file_sha256(self.database_path)
                if after != self.file_sha256:
                    raise ComparisonError("artifact SQLite file changed during read transaction")
            finally:
                self._connection.execute("ROLLBACK")


def _point_from_artifact(
    label: str,
    artifact: ATRArtifact,
    provenance: dict[str, Any],
    day: date,
) -> ComparisonPoint:
    observation = next(item for item in artifact.observations if item.trading_date == day)
    return ComparisonPoint(
        label=label,
        value=None if observation.atr is None else float(observation.atr),
        reason=observation.null_reason if observation.atr is None else None,
        provenance=provenance,
    )


def _new_comparability_signature(point: ComparisonPoint) -> dict[str, Any]:
    """Return fields that must agree for two strict observations to be comparable."""

    provenance = point.provenance["provenance"]
    source = provenance["source"]
    algorithm = provenance["algorithm"]
    implementation = algorithm["implementation"]
    basis = provenance["basis"]
    return {
        "instrument": provenance["instrument"].get("exchange"),
        "symbol": provenance["instrument"].get("symbol"),
        "feature": provenance["feature"],
        "price_basis": basis["price_basis"],
        "basis_digest": basis["digest"],
        "source_version": source["version"],
        "source_snapshot": (source["snapshot_id"], source["snapshot_hash"]),
        "algorithm": (algorithm["name"], algorithm["version"], algorithm["period"]),
        "config_digest": algorithm["config_digest"],
        "implementation": (
            implementation["name"],
            implementation["version"],
            implementation["digest"],
        ),
        "calendar": (
            provenance["calendar"]["version"],
            provenance["calendar"]["snapshot_id"],
            provenance["calendar"]["snapshot_hash"],
        ),
        "sessions": (
            provenance["sessions"]["version"],
            provenance["sessions"]["snapshot_id"],
            provenance["sessions"]["snapshot_hash"],
            tuple(item["session_date"] for item in provenance["sessions"]["ordered_sessions"]),
        ),
        "halts": (
            provenance["halts"]["version"],
            provenance["halts"]["snapshot_id"],
            provenance["halts"]["snapshot_hash"],
            tuple(
                (item["session_date"], item["status"])
                for item in provenance["halts"]["session_statuses"]
            ),
        ),
        "previous_close": provenance["previous_close"],
        "company_actions": provenance["company_actions"]["digest"],
        "settings_digest": point.provenance["settings_digest"],
        "dependency_digest": point.provenance["dependency_digest"],
    }


def _signature_reasons(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    reason_by_field = {
        "instrument": "asof_instrument_mismatch",
        "symbol": "asof_instrument_mismatch",
        "feature": "asof_feature_version_mismatch",
        "price_basis": "asof_basis_mismatch",
        "basis_digest": "asof_basis_evidence_mismatch",
        "source_version": "asof_source_version_mismatch",
        "source_snapshot": "asof_snapshot_mismatch",
        "algorithm": "asof_algorithm_mismatch",
        "config_digest": "asof_config_mismatch",
        "implementation": "asof_implementation_mismatch",
        "calendar": "asof_calendar_mismatch",
        "sessions": "asof_sessions_mismatch",
        "halts": "asof_halts_mismatch",
        "previous_close": "asof_previous_close_mismatch",
        "company_actions": "asof_company_actions_mismatch",
        "settings_digest": "asof_settings_digest_mismatch",
        "dependency_digest": "asof_dependency_digest_mismatch",
    }
    return [
        reason_by_field[field]
        for field in reason_by_field
        if left.get(field) != right.get(field)
    ]


class ArtifactComparisonReader:
    """Compare one legacy row with two explicitly selected strict v2 as-of rows."""

    def __init__(
        self,
        legacy_database_path: str | Path,
        artifact_database_path: str | Path,
    ) -> None:
        self.legacy = LegacyTechnicalFeaturesReader(legacy_database_path)
        try:
            self.artifacts = ReadonlyArtifactReader(artifact_database_path)
        except Exception:
            self.legacy.close()
            raise

    def close(self) -> None:
        self.legacy.close()
        self.artifacts.close()

    def __enter__(self) -> "ArtifactComparisonReader":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def compare(
        self,
        instrument: Mapping[str, Any] | str,
        market_date: date | str | datetime,
        *,
        legacy: LegacyFeatureSelector,
        asof_a: ArtifactSelector,
        asof_b: ArtifactSelector,
    ) -> ATRComparisonResult:
        legacy.validate()
        asof_a.validate("asof_a")
        asof_b.validate("asof_b")
        exchange, symbol = _identity(instrument)
        day = _market_date(market_date)
        legacy_observation = self.legacy.read_exact(instrument, day, selector=legacy)
        artifact_a, provenance_a, key_a = self.artifacts.read_exact(
            instrument, day, selector=asof_a
        )
        artifact_b, provenance_b, key_b = self.artifacts.read_exact(
            instrument, day, selector=asof_b
        )
        legacy_point = ComparisonPoint(
            label="legacy",
            value=legacy_observation.value,
            reason=legacy_observation.reason,
            provenance=legacy_observation.provenance,
        )
        point_a = _point_from_artifact("asof_a", artifact_a, provenance_a, day)
        point_b = _point_from_artifact("asof_b", artifact_b, provenance_b, day)

        diagnostic_differences: dict[str, float | None] = {}
        if legacy_point.value is not None and point_a.value is not None:
            diagnostic_differences["legacy_minus_asof_a"] = legacy_point.value - point_a.value
        else:
            diagnostic_differences["legacy_minus_asof_a"] = None
        if legacy_point.value is not None and point_b.value is not None:
            diagnostic_differences["legacy_minus_asof_b"] = legacy_point.value - point_b.value
        else:
            diagnostic_differences["legacy_minus_asof_b"] = None
        if point_a.value is not None and point_b.value is not None:
            diagnostic_differences["asof_a_minus_asof_b"] = point_a.value - point_b.value
        else:
            diagnostic_differences["asof_a_minus_asof_b"] = None

        legacy_reasons: list[str] = ["legacy_provenance_caller_declared_only"]
        legacy_snapshot_verified = (
            legacy.snapshot_sha256 is not None
            and legacy.snapshot_sha256.casefold() == self.legacy.file_sha256.casefold()
        )
        if legacy.snapshot_sha256 is not None and not legacy_snapshot_verified:
            raise LegacySnapshotMismatchError(
                "legacy_snapshot_sha256 does not match the opened legacy file"
            )
        if not legacy_snapshot_verified:
            legacy_reasons.append("legacy_snapshot_unverified")
        legacy_basis = legacy.price_basis
        if legacy_basis is None:
            legacy_reasons.append("legacy_price_basis_unknown")
        new_points = (point_a, point_b)
        new_bases = tuple(point.provenance["price_basis"] for point in new_points)
        if legacy_basis is not None:
            for index, basis in enumerate(new_bases):
                if basis != legacy_basis:
                    legacy_reasons.append(f"legacy_vs_asof_{'a' if index == 0 else 'b'}_basis_mismatch")
        if legacy_point.value is None:
            legacy_reasons.append("legacy_missing_or_null_observation")

        pair_reasons = _signature_reasons(
            _new_comparability_signature(point_a),
            _new_comparability_signature(point_b),
        )
        if point_a.value is None:
            pair_reasons.append("asof_a_missing_or_null_observation")
        if point_b.value is None:
            pair_reasons.append("asof_b_missing_or_null_observation")
        pair_reasons = list(dict.fromkeys(pair_reasons))
        pair_comparable = not pair_reasons
        # Legacy technical_features contains no persisted method/basis/as-of
        # identity.  Its caller declarations and actual file fingerprint are
        # retained, but never upgraded into comparable evidence.
        legacy_comparable = False
        differences = {
            "legacy_minus_asof_a": None,
            "legacy_minus_asof_b": None,
            "asof_a_minus_asof_b": (
                diagnostic_differences["asof_a_minus_asof_b"] if pair_comparable else None
            ),
        }
        all_reasons = list(dict.fromkeys([*legacy_reasons, *pair_reasons]))
        comparability = {
            "overall": False,
            "legacy_vs_asof_a": False,
            "legacy_vs_asof_b": False,
            "asof_pair": pair_comparable,
            "reasons": {
                "legacy": tuple(dict.fromkeys(legacy_reasons)),
                "asof_pair": tuple(pair_reasons),
            },
            "machine_reasons": tuple(all_reasons),
            "interpretation": "descriptive_values_only; no_strategy_preference",
        }
        return ATRComparisonResult(
            instrument={"exchange": exchange, "symbol": symbol},
            market_date=day,
            legacy_atr=legacy_point,
            asof_observations=(point_a, point_b),
            differences=differences,
            diagnostic_differences=diagnostic_differences,
            comparability=comparability,
            provenance={
                "legacy": legacy_observation.provenance,
                "asof_a": {"artifact_key": key_a, **provenance_a},
                "asof_b": {"artifact_key": key_b, **provenance_b},
            },
        )

    compare_atr = compare


__all__ = [
    "ATRComparisonResult",
    "ArtifactComparisonReader",
    "ArtifactSelector",
    "ComparisonAmbiguousError",
    "ComparisonError",
    "ComparisonNotFoundError",
    "ComparisonSelectorError",
    "LegacyFeatureObservation",
    "LegacyFeatureSelector",
    "LegacyReaderOwnershipError",
    "LegacySnapshotMismatchError",
    "LegacyTechnicalFeaturesReader",
    "ReadonlyArtifactReader",
]
