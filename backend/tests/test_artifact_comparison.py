from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date

import pytest

from app.artifact_comparison import (
    ArtifactComparisonReader,
    ArtifactSelector,
    ComparisonAmbiguousError,
    ComparisonNotFoundError,
    LegacyFeatureSelector,
    LegacySnapshotMismatchError,
)
from app.artifact_provenance import ProvenanceContractError
from app.artifact_store import ArtifactStore
from strict_artifact_fixture import (
    DECISION_A,
    DECISION_B,
    INSTRUMENT,
    MARKET_DATE,
    SNAPSHOT_HASH,
    make_artifact,
    make_provenance,
)


def _legacy_database(path, *, duplicate_instrument: bool = False) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE instruments (
            id INTEGER PRIMARY KEY,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL
        );
        CREATE TABLE technical_features (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER NOT NULL,
            trading_date TEXT NOT NULL,
            features_json TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.execute("INSERT INTO instruments VALUES (1, 'TWSE', '2330')")
    if duplicate_instrument:
        connection.execute("INSERT INTO instruments VALUES (2, 'TWSE', '2330')")
    connection.execute(
        "INSERT INTO technical_features VALUES (1, 1, ?, ?, 'fixture', '2026-02-01T00:00:00+00:00')",
        (MARKET_DATE.isoformat(), json.dumps({"atr14": 4.0, "ma20": 100.0})),
    )
    connection.commit()
    connection.close()


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_artifacts(path):
    with ArtifactStore(path) as store:
        first = store.save_atr_artifact_strict(
            INSTRUMENT,
            MARKET_DATE,
            make_artifact(decision_at=DECISION_A),
            provenance=make_provenance(make_artifact(decision_at=DECISION_A)),
            attempt_id="a",
        )
        second_artifact = make_artifact(decision_at=DECISION_B)
        second = store.save_atr_artifact_strict(
            INSTRUMENT,
            MARKET_DATE,
            second_artifact,
            provenance=make_provenance(second_artifact),
            attempt_id="b",
        )
        return first.artifact_key, second.artifact_key


def test_compare_is_readonly_exact_and_reports_non_comparable_legacy(tmp_path) -> None:
    legacy_path = tmp_path / "legacy # snapshot.sqlite"
    artifact_path = tmp_path / "artifact # snapshot.sqlite"
    _legacy_database(legacy_path)
    key_a, key_b = _new_artifacts(artifact_path)
    before_legacy = (legacy_path.read_bytes(), legacy_path.stat().st_mtime_ns)
    before_artifact = (artifact_path.read_bytes(), artifact_path.stat().st_mtime_ns)

    with ArtifactComparisonReader(legacy_path, artifact_path) as reader:
        result = reader.compare(
            INSTRUMENT,
            MARKET_DATE,
            legacy=LegacyFeatureSelector(
                snapshot_id="legacy-fixture-v1",
                feature_version="legacy-wilder-v1",
                price_basis="raw_v1",
                snapshot_sha256=_sha256(legacy_path),
            ),
            asof_a=ArtifactSelector(artifact_key=key_a),
            asof_b=ArtifactSelector(artifact_key=key_b),
        )
        assert reader.legacy._connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert reader.artifacts._connection.execute("PRAGMA query_only").fetchone()[0] == 1

    assert result.legacy_atr.value == pytest.approx(4.0)
    assert [point.value for point in result.asof_observations] == pytest.approx([5.0, 5.0])
    assert result.differences == {
        "legacy_minus_asof_a": None,
        "legacy_minus_asof_b": None,
        "asof_a_minus_asof_b": pytest.approx(0.0),
    }
    assert result.diagnostic_differences["legacy_minus_asof_a"] == pytest.approx(-1.0)
    assert result.comparability["legacy_vs_asof_a"] is False
    assert result.comparability["asof_pair"] is True
    assert "legacy_provenance_caller_declared_only" in result.comparability["machine_reasons"]
    assert result.provenance["asof_a"]["provenance_contract"] == "atr-provenance/v2"
    assert (legacy_path.read_bytes(), legacy_path.stat().st_mtime_ns) == before_legacy
    assert (artifact_path.read_bytes(), artifact_path.stat().st_mtime_ns) == before_artifact
    assert not (legacy_path.parent / f"{legacy_path.name}-wal").exists()
    assert not (artifact_path.parent / f"{artifact_path.name}-wal").exists()


def test_compare_accepts_complete_version_snapshot_asof_selectors(tmp_path) -> None:
    legacy_path = tmp_path / "legacy.sqlite"
    artifact_path = tmp_path / "artifact.sqlite"
    _legacy_database(legacy_path)
    key_a, key_b = _new_artifacts(artifact_path)
    with ArtifactComparisonReader(legacy_path, artifact_path) as reader:
        result = reader.compare(
            INSTRUMENT,
            MARKET_DATE,
            legacy=LegacyFeatureSelector("legacy", "legacy-v1", snapshot_sha256=_sha256(legacy_path)),
            asof_a=ArtifactSelector(
                feature_name="atr14",
                feature_version="technical_v2_atr14_wilder",
                snapshot_id="bars-snapshot-1",
                snapshot_hash=SNAPSHOT_HASH,
                decision_at=DECISION_A,
            ),
            asof_b=ArtifactSelector(artifact_key=key_b),
        )
    assert result.asof_observations[0].provenance["artifact_key"] == key_a


def test_compare_rejects_missing_ambiguous_or_cross_identity_rows(tmp_path) -> None:
    legacy_path = tmp_path / "legacy.sqlite"
    artifact_path = tmp_path / "artifact.sqlite"
    _legacy_database(legacy_path, duplicate_instrument=True)
    key_a, key_b = _new_artifacts(artifact_path)
    with ArtifactComparisonReader(legacy_path, artifact_path) as reader:
        selector = LegacyFeatureSelector("legacy", "legacy-v1", snapshot_sha256=_sha256(legacy_path))
        with pytest.raises(ComparisonAmbiguousError):
            reader.compare(
                INSTRUMENT,
                MARKET_DATE,
                legacy=selector,
                asof_a=ArtifactSelector(artifact_key=key_a),
                asof_b=ArtifactSelector(artifact_key=key_b),
            )

    missing_day_path = tmp_path / "legacy-missing-day.sqlite"
    _legacy_database(missing_day_path)
    with ArtifactComparisonReader(missing_day_path, artifact_path) as reader:
        with pytest.raises(ComparisonNotFoundError):
            reader.legacy.read_exact(
                INSTRUMENT,
                date(2026, 1, 18),
                selector=LegacyFeatureSelector(
                    "legacy", "legacy-v1", snapshot_sha256=_sha256(missing_day_path)
                ),
            )


def test_legacy_snapshot_mismatch_and_artifact_strict_marker_fail_closed(tmp_path) -> None:
    legacy_path = tmp_path / "legacy.sqlite"
    artifact_path = tmp_path / "artifact.sqlite"
    _legacy_database(legacy_path)
    with ArtifactStore(artifact_path) as store:
        from test_artifact_store import _calculate, _save

        old = _save(store, _calculate())
    with ArtifactComparisonReader(legacy_path, artifact_path) as reader:
        with pytest.raises(LegacySnapshotMismatchError):
            reader.legacy.read_exact(
                INSTRUMENT,
                MARKET_DATE,
                selector=LegacyFeatureSelector("legacy", "legacy-v1", snapshot_sha256="0" * 64),
            )
        with pytest.raises(ProvenanceContractError):
            reader.artifacts.read_exact(
                INSTRUMENT,
                MARKET_DATE,
                selector=ArtifactSelector(artifact_key=old.artifact_key),
            )


def test_missing_database_is_rejected_without_creation(tmp_path) -> None:
    legacy_path = tmp_path / "does-not-exist.sqlite"
    artifact_path = tmp_path / "also-missing.sqlite"
    with pytest.raises(Exception):
        ArtifactComparisonReader(legacy_path, artifact_path)
    assert not legacy_path.exists()
    assert not artifact_path.exists()
