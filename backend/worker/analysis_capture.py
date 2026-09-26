"""Explicit external worker capture. No worker/config import until run preflight.

Trusted local snapshots only; seals detect corruption, not hostile rewriting.
Creation never adopts an existing file. Research writes use one SQLite transaction.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid

from app.rule_replay import capture_rule_inputs, rule_replay_json, replay_rule_inputs
from app.rule_replay import _canonical, _detached
from app.signal_artifact_store import readonly_snapshot, snapshot_fingerprint
from app.signal_artifact_store import _is_path_alias, _path_has_protected_component

KIND = "worker-analysis-capture/v1"
KIND_V2 = "worker-analysis-capture/v2"
INPUT_PROVENANCE_MODE = "selected-bar/v1"
SELECTED_BAR_SCHEMA = "worker-selected-bar-provenance/v1"
TABLES = {
    "worker_capture_owner": "CREATE TABLE worker_capture_owner (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, digest TEXT NOT NULL)",
    "worker_capture_attempts": "CREATE TABLE worker_capture_attempts (attempt_id TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)",
    "worker_capture_calls": "CREATE TABLE worker_capture_calls (attempt_id TEXT NOT NULL REFERENCES worker_capture_attempts(attempt_id) DEFERRABLE INITIALLY DEFERRED, ordinal INTEGER NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(attempt_id,ordinal))",
}
SCHEMA = dict(TABLES)
for _table in TABLES:
    for _event in ("UPDATE", "DELETE"):
        _name = _table + "_no_" + _event.lower()
        SCHEMA[_name] = f"CREATE TRIGGER {_name} BEFORE {_event} ON {_table} BEGIN SELECT RAISE(ABORT,'immutable capture'); END"
    _name = _table + "_no_replace"
    _condition = "id=NEW.id" if _table.endswith("owner") else "attempt_id=NEW.attempt_id"
    if _table.endswith("calls"):
        _condition += " AND ordinal=NEW.ordinal"
    SCHEMA[_name] = f"CREATE TRIGGER {_name} BEFORE INSERT ON {_table} WHEN EXISTS(SELECT 1 FROM {_table} WHERE {_condition}) BEGIN SELECT RAISE(ABORT,'immutable capture'); END"


class AnalysisCaptureError(RuntimeError):
    def __init__(self, code, *, outcome=None, detail=None):
        self.code, self.outcome, self.detail = code, outcome, detail
        super().__init__(code)


def _exact(left, right):
    """JSON identity preserves bool/int/float types instead of Python coercion."""
    return _canonical(left) == _canonical(right)


def _seal(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _path(value):
    if not isinstance(value, (str, Path)):
        raise AnalysisCaptureError("absolute_external_path_required")
    path = Path(value)
    if not path.is_absolute() or str(value).casefold().startswith("file:") or ":memory:" in str(value):
        raise AnalysisCaptureError("absolute_external_path_required")
    resolved = path.resolve()
    if (resolved.is_relative_to(Path(__file__).resolve().parents[2])
            or _path_has_protected_component(path) or _path_has_protected_component(resolved)):
        raise AnalysisCaptureError("protected_path")
    if _is_path_alias(path) or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise AnalysisCaptureError("path_alias")
    if path.exists() and path.stat().st_nlink != 1:
        raise AnalysisCaptureError("path_alias")
    return path


def _decode(row):
    try:
        payload = _detached(row["payload"], accept_text=True)
        if row["payload"] != _canonical(payload) or row["digest"] != _seal(payload):
            raise ValueError("seal")
        return payload
    except Exception as exc:
        raise AnalysisCaptureError("invalid_sealed_payload") from exc


def _timestamp(value):
    if type(value) is not str:
        raise AnalysisCaptureError("invalid_capture_timestamp")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise AnalysisCaptureError("invalid_capture_timestamp") from exc


def _positive_id(value):
    return type(value) is int and value > 0


def _market_date(value):
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise AnalysisCaptureError("invalid_market_date")


def _selected_bar_float(value):
    """Mirror the worker's numeric _safe_float conversion for selected bars."""
    if type(value) not in (int, float):
        raise AnalysisCaptureError("selected_bar_value_invalid")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise AnalysisCaptureError("selected_bar_value_invalid") from exc
    if not math.isfinite(converted):
        raise AnalysisCaptureError("selected_bar_value_invalid")
    return converted


def _validate_selected_bar_provenance(value, arguments, *, subject=None, market_date=None):
    """Validate a sealed local row relation without rereading mutable source rows."""
    if (type(value) is not dict or set(value) != {
            "schema", "coverage", "bar", "raw_payload", "raw_status", "raw_reason",
            "raw_bytes_verification",
    } or value["schema"] != SELECTED_BAR_SCHEMA
            or value["coverage"] != ["close", "volume"]
            or value["raw_bytes_verification"] != "bytes_unverified"):
        raise AnalysisCaptureError("selected_bar_provenance_shape_invalid")
    bar = value["bar"]
    if type(bar) is not dict or set(bar) != {
            "id", "instrument_id", "trading_date", "close", "volume", "source",
            "raw_payload_id", "data_as_of", "collected_at",
    }:
        raise AnalysisCaptureError("selected_bar_shape_invalid")
    try:
        _market_date(bar["trading_date"])
    except (ValueError, TypeError) as exc:
        raise AnalysisCaptureError("selected_bar_date_invalid") from exc
    if (not _positive_id(bar["id"]) or not _positive_id(bar["instrument_id"])
            or type(bar["volume"]) is not int or bar["volume"] < 0
            or type(bar["source"]) is not str or not bar["source"].strip()
            or any(item is not None and type(item) is not str
                   for item in (bar["data_as_of"], bar["collected_at"]))
            or (bar["raw_payload_id"] is not None and not _positive_id(bar["raw_payload_id"]))):
        raise AnalysisCaptureError("selected_bar_value_invalid")
    if (type(arguments) is not dict or "close" not in arguments or "volume" not in arguments
            or not _exact(arguments["close"], _selected_bar_float(bar["close"]))
            or not _exact(arguments["volume"], _selected_bar_float(bar["volume"]))):
        raise AnalysisCaptureError("selected_bar_arguments_mismatch")
    if ((subject is not None and bar["instrument_id"] != subject["instrument_id"])
            or (market_date is not None and bar["trading_date"] != market_date)):
        raise AnalysisCaptureError("selected_bar_subject_date_mismatch")
    raw = value["raw_payload"]
    if bar["raw_payload_id"] is None:
        if (raw is not None or value["raw_status"] != "unknown"
                or value["raw_reason"] != "raw_payload_id_missing"):
            raise AnalysisCaptureError("selected_bar_raw_relation_invalid")
        return
    if (type(raw) is not dict or set(raw) != {
            "id", "source", "endpoint", "payload_path", "sha256", "ingestion_run_id",
            "data_as_of", "collected_at",
    } or not _positive_id(raw["id"]) or raw["id"] != bar["raw_payload_id"]
            or value["raw_status"] != "linked_metadata" or value["raw_reason"] is not None
            or type(raw["source"]) is not str or raw["source"] != bar["source"]
            or type(raw["endpoint"]) is not str or not raw["endpoint"].strip()
            or any(item is not None and type(item) is not str
                   for item in (raw["payload_path"], raw["data_as_of"], raw["collected_at"]))
            or (raw["ingestion_run_id"] is not None and not _positive_id(raw["ingestion_run_id"]))):
        raise AnalysisCaptureError("selected_bar_raw_relation_invalid")
    declared_sha = raw["sha256"]
    if (declared_sha is not None and (type(declared_sha) is not str
            or re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha) is None)):
        raise AnalysisCaptureError("selected_bar_raw_digest_invalid")


def _checked_owner(connection):
    actual = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'worker_capture_%' OR tbl_name LIKE 'worker_capture_%'"))
    expected = {**SCHEMA, "sqlite_autoindex_worker_capture_attempts_1": None, "sqlite_autoindex_worker_capture_calls_1": None}
    if actual != expected:
        raise AnalysisCaptureError("capture_schema_mismatch")
    rows = connection.execute("SELECT * FROM worker_capture_owner").fetchall()
    if len(rows) != 1 or rows[0]["id"] != 1:
        raise AnalysisCaptureError("ownership_missing")
    owner = _decode(rows[0])
    if (set(owner) != {"kind", "database_id", "created_at", "source_snapshot"}
            or owner["kind"] != KIND or not re.fullmatch(r"[0-9a-f]{32}", owner["database_id"])
            or set(owner["source_snapshot"]) != {"path", "sha256", "size", "mtime_ns", "sidecars"}):
        raise AnalysisCaptureError("ownership_invalid")
    _timestamp(owner["created_at"])
    fingerprint = owner["source_snapshot"]
    _path(fingerprint["path"])
    if (type(fingerprint["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", fingerprint["sha256"]) is None
            or type(fingerprint["size"]) is not int or fingerprint["size"] <= 0
            or type(fingerprint["mtime_ns"]) is not str or re.fullmatch(r"[0-9]+", fingerprint["mtime_ns"]) is None
            or fingerprint["sidecars"] != []):
        raise AnalysisCaptureError("source_fingerprint_invalid")
    return owner


def _owner(connection):
    try:
        return _checked_owner(connection)
    except AnalysisCaptureError:
        raise
    except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        raise AnalysisCaptureError("ownership_invalid", detail=type(exc).__name__) from exc


def _source_schema(connection, names):
    """Finite migration marker/analysis column check without config imports."""
    markers = set()
    if "alembic_version" in names:
        markers.update(r[0] for r in connection.execute("SELECT version_num FROM alembic_version"))
    if "schema_migrations" in names:
        markers.update(r[0] for r in connection.execute("SELECT version FROM schema_migrations"))
    if "0006_news_json_defaults" not in markers:
        raise AnalysisCaptureError("source_migration_not_ready")
    required = {
        "instruments": {"id", "market", "exchange", "symbol", "instrument_type", "etf_category", "status"},
        "signals": {"id", "signal_key", "signal_date", "instrument_id", "strategy_version_id", "rule_evidence_json"},
        "technical_features": {"instrument_id", "trading_date", "features_json"},
        "ingestion_runs": {"id", "run_type", "source", "status", "data_as_of", "updated_at"},
    }
    for table, columns in required.items():
        if table not in names or not columns <= {r[1] for r in connection.execute(f"PRAGMA table_xinfo({table})")}:
            raise AnalysisCaptureError("source_analysis_schema_missing")


def _create_research_database(*, source_snapshot_path, expected_source_sha256, research_database_path):
    """Copy a stable explicit source into a new, exclusively created owned DB."""
    if not isinstance(expected_source_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_source_sha256):
        raise AnalysisCaptureError("expected_source_sha256_required")
    target = _path(research_database_path)
    if os.path.lexists(target) or any(os.path.lexists(str(target)+s) for s in ("-wal", "-shm", "-journal")):
        raise AnalysisCaptureError("target_exists")
    with readonly_snapshot(source_snapshot_path, expected_database_sha256=expected_source_sha256) as (source, fingerprint):
        names = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"signals", "instruments", "market_bars", "ingestion_runs", "strategy_versions"} <= names:
            raise AnalysisCaptureError("source_analysis_schema_missing")
        _source_schema(source, names)
        if any(n.startswith("worker_capture_") for n in names):
            raise AnalysisCaptureError("source_already_owned")
        # Existing parents only; no creation before source preflight succeeds.
        with target.open("xb") as output, Path(source_snapshot_path).open("rb") as input_file:
            digest = hashlib.sha256()
            for block in iter(lambda: input_file.read(1024*1024), b""):
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected_source_sha256.lower():
            raise AnalysisCaptureError("copied_source_hash_mismatch")
    # Marker is only added after complete source postflight and copy verification.
    owner = {"kind": KIND, "database_id": uuid.uuid4().hex, "created_at": _now(), "source_snapshot": {**fingerprint, "mtime_ns": str(fingerprint["mtime_ns"])}}
    with sqlite3.connect(target) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for sql in SCHEMA.values():
            connection.execute(sql)
        connection.execute("INSERT INTO worker_capture_owner VALUES (1,?,?)", (_canonical(owner), _seal(owner)))
    with readonly_snapshot(target) as (connection, _):
        _source_schema(connection, {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")})
        if not _exact(_owner(connection), owner):
            raise AnalysisCaptureError("creation_readback_mismatch")
    return owner


def create_research_database(*, source_snapshot_path, expected_source_sha256, research_database_path):
    """Create only a new file; on failure a target may remain, even fully owned.

    No automatic deletion/adoption/retry is performed. A failure after exclusive
    creation is outcome-unknown, including a failed post-commit readback.
    """
    _path(research_database_path)
    existed = os.path.lexists(research_database_path)
    try:
        return _create_research_database(source_snapshot_path=source_snapshot_path,
            expected_source_sha256=expected_source_sha256, research_database_path=research_database_path)
    except Exception as exc:
        if not existed and os.path.lexists(research_database_path):
            raise AnalysisCaptureError("creation_failed", outcome="creation_outcome_unknown",
                detail=getattr(exc, "code", type(exc).__name__)) from exc
        raise


def _attempt_id(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None:
        raise AnalysisCaptureError("invalid_attempt_id")
    return value


def _read_analysis_attempt(*, research_database_path, attempt_id, _connection=None):
    """Read an exact sealed committed attempt, without importing the worker."""
    _attempt_id(attempt_id)
    # A caller that already holds a guarded read transaction can reuse this
    # entire strict reader before selecting one of its calls on that snapshot.
    snapshot = (readonly_snapshot(research_database_path) if _connection is None
                else nullcontext((_connection, None)))
    with snapshot as (connection, _):
        owner = _owner(connection)
        row = connection.execute("SELECT * FROM worker_capture_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None:
            raise AnalysisCaptureError("attempt_not_found")
        receipt = _decode(row)
        calls = connection.execute("SELECT * FROM worker_capture_calls WHERE attempt_id=? ORDER BY ordinal", (attempt_id,)).fetchall()
        if (set(receipt) != {"kind", "attempt_id", "database_id", "source_snapshot", "captured_at", "analysis", "source_collection_run_id", "call_digests", "signal_count"}
                or receipt["kind"] not in (KIND, KIND_V2) or receipt["attempt_id"] != attempt_id
                or receipt["database_id"] != owner["database_id"] or not _exact(receipt["source_snapshot"], owner["source_snapshot"])
                or len(calls) != len(receipt["call_digests"]) or len(calls) != receipt["signal_count"]*2):
            raise AnalysisCaptureError("attempt_manifest_mismatch")
        if (type(receipt["call_digests"]) is not list or any(type(d) is not str or re.fullmatch(r"[0-9a-f]{64}", d) is None for d in receipt["call_digests"])
                or type(receipt["signal_count"]) is not int or receipt["signal_count"] < 0
                or receipt["analysis"].get("status") != "success"
                or receipt["analysis"].get("signals_upserted") * 2 != receipt["signal_count"]):
            raise AnalysisCaptureError("attempt_count_mismatch")
        if (set(receipt["analysis"]) != {"status", "date", "signals_upserted"}
                or type(receipt["analysis"]["signals_upserted"]) is not int
                or receipt["analysis"]["signals_upserted"] < 0
                or not _positive_id(receipt["source_collection_run_id"])):
            raise AnalysisCaptureError("attempt_metadata_invalid")
        _timestamp(receipt["captured_at"])
        _market_date(receipt["analysis"]["date"])
        decoded = []
        for ordinal, call in enumerate(calls):
            payload = _decode(call)
            if (call["ordinal"] != ordinal or call["digest"] != receipt["call_digests"][ordinal]
                    or payload["attempt_id"] != attempt_id or payload["database_id"] != owner["database_id"]
                    or payload["ordinal"] != ordinal or payload["observed_market_date"] != receipt["analysis"]["date"]):
                raise AnalysisCaptureError("capture_relation_mismatch")
            expected_keys = {"attempt_id", "database_id", "ordinal", "evaluator", "selected_strategy", "namespace", "subject", "observed_market_date", "signal_snapshot", "arguments", "captured_at", "actual_result", "bundle"}
            if receipt["kind"] == KIND_V2:
                expected_keys.add("input_provenance")
            if set(payload) != expected_keys:
                raise AnalysisCaptureError("capture_keys_mismatch")
            _timestamp(payload["captured_at"])
            _market_date(payload["observed_market_date"])
            if type(payload["ordinal"]) is not int or payload["namespace"] != "analysis":
                raise AnalysisCaptureError("capture_occurrence_invalid")
            bundle = json.loads(rule_replay_json(payload["bundle"]))
            if not replay_rule_inputs(bundle)["exact_match"]:
                raise AnalysisCaptureError("capture_replay_mismatch")
            subject, strategy, signal = payload["subject"], payload["selected_strategy"], payload["signal_snapshot"]
            if (set(subject) != {"instrument_id", "market", "exchange", "symbol"}
                    or set(strategy) != {"id", "name", "version", "config"}
                    or strategy["name"] not in {"breakout_v1", "pullback_v1"}
                    or strategy["version"] != "1.0.0"
                    or signal["instrument_id"] != subject["instrument_id"]
                    or signal["strategy_version_id"] != strategy["id"]
                    or signal["signal_date"] != payload["observed_market_date"]
                    or signal["signal_key"] != f"{payload['namespace']}-{subject['exchange']}-{subject['symbol']}-{payload['observed_market_date']}-{strategy['name']}-{strategy['version']}"):
                raise AnalysisCaptureError("capture_signal_link_mismatch")
            signal_keys = {"id", "signal_key", "signal_date", "instrument_id", "strategy_version_id", "status", "entry_type", "reference_entry", "pullback_low", "pullback_high", "breakout_price", "invalid_price", "target_1", "target_2", "confidence", "rationale", "data_cutoff", "source_report", "earliest_execution_date", "execution_date", "execution_price", "data_quality", "rule_evidence_json", "created_at"}
            if (set(signal) != signal_keys or not _positive_id(subject["instrument_id"])
                    or not _positive_id(strategy["id"]) or not _positive_id(signal["id"])
                    or type(signal["instrument_id"]) is not int or type(signal["strategy_version_id"]) is not int
                    or any(type(subject[k]) is not str or not subject[k].strip() for k in ("market", "exchange", "symbol"))
                    or type(signal["rule_evidence_json"]) is not dict):
                raise AnalysisCaptureError("capture_snapshot_shape_invalid")
            numeric = {"reference_entry", "pullback_low", "pullback_high", "breakout_price", "invalid_price", "target_1", "target_2", "confidence", "execution_price"}
            if (any(signal[k] is not None and type(signal[k]) not in (int, float) for k in numeric)
                    or any(type(signal[k]) is not str for k in ("status", "entry_type", "data_quality", "created_at"))
                    or any(signal[k] is not None and type(signal[k]) is not str for k in ("rationale", "data_cutoff", "source_report"))):
                raise AnalysisCaptureError("capture_snapshot_type_invalid")
            datetime.fromisoformat(signal["created_at"])
            for key in ("earliest_execution_date", "execution_date"):
                if signal[key] is not None:
                    _market_date(signal[key])
            evidence = signal["rule_evidence_json"]
            observed = evidence.get(payload["evaluator"].removesuffix("_v1"))
            if (evidence.get("strategy") != strategy["name"] or evidence.get("strategy_version") != strategy["version"]
                    or not _exact(observed, {"state": payload["actual_result"]["state"], "reasons": payload["actual_result"]["reasons"]})):
                raise AnalysisCaptureError("capture_signal_evidence_mismatch")
            if payload["evaluator"] == strategy["name"] and not _exact(strategy["config"], bundle["config_snapshot"]):
                raise AnalysisCaptureError("capture_strategy_link_mismatch")
            if (not _exact(payload["actual_result"], bundle["recorded_result"])
                    or not _exact(payload["arguments"], bundle["arguments"])
                    or payload["evaluator"] != bundle["evaluator"]):
                raise AnalysisCaptureError("capture_result_mismatch")
            if receipt["kind"] == KIND_V2:
                _validate_selected_bar_provenance(
                    payload["input_provenance"], payload["arguments"],
                    subject=subject, market_date=payload["observed_market_date"],
                )
            decoded.append(payload)
        for pos in range(0, len(decoded), 2):
            a, b = decoded[pos:pos+2]
            if (a["evaluator"], b["evaluator"]) != ("breakout_v1", "pullback_v1") or any(not _exact(a[k], b[k]) for k in ("subject", "signal_snapshot", "selected_strategy", "namespace")):
                raise AnalysisCaptureError("capture_pair_mismatch")
            if receipt["kind"] == KIND_V2 and not _exact(a["input_provenance"], b["input_provenance"]):
                raise AnalysisCaptureError("capture_pair_provenance_mismatch")
        occurrences = {(r["subject"]["instrument_id"], r["selected_strategy"]["name"]) for r in decoded}
        subjects = {r["subject"]["instrument_id"] for r in decoded}
        if (len(occurrences)*2 != len(decoded) or len(subjects)*4 != len(decoded)
                or len({_canonical(r["subject"]) for r in decoded}) != len(subjects)
                or len({r["signal_snapshot"]["id"] for r in decoded})*2 != len(decoded)):
            raise AnalysisCaptureError("capture_occurrence_mismatch")
        return {"receipt": receipt, "captures": decoded, "outcome": "committed_verified", "idempotent_reuse": False,
                "scope": "worker_evaluation_capture", "pit_verified": False, "availability_verified": False, "historical_inputs_verified": False}


def read_analysis_attempt(*, research_database_path, attempt_id):
    """Strict exact readback; malformed records never become a partial success."""
    try:
        return _read_analysis_attempt(research_database_path=research_database_path, attempt_id=attempt_id)
    except AnalysisCaptureError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, sqlite3.Error) as exc:
        raise AnalysisCaptureError("capture_integrity_error", detail=type(exc).__name__) from exc


def _environment(owner, research_path):
    paths = []
    for key in ("STOCK_DATA_DIR", "STOCK_RAW_DIR", "STOCK_DB_PATH"):
        if not os.environ.get(key):
            raise AnalysisCaptureError("isolated_stock_environment_required")
        paths.append(_path(os.environ[key]))
    for directory in paths[:2]:
        if any(p.exists() and not p.is_dir() for p in (directory, *directory.parents)):
            raise AnalysisCaptureError("stock_directory_required")
    if any(p.exists() and not p.is_dir() for p in paths[2].parents):
        raise AnalysisCaptureError("stock_database_parent_invalid")
    if os.path.lexists(paths[2]) or any(os.path.lexists(str(paths[2])+suffix) for suffix in ("-wal", "-shm", "-journal")) or paths[2].resolve() in (Path(research_path).resolve(), Path(owner["source_snapshot"]["path"]).resolve()):
        raise AnalysisCaptureError("stock_database_must_be_unused")


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class _Collector:
    def __init__(self, owner, attempt_id, input_provenance=None):
        self.owner, self.attempt_id, self.input_provenance = owner, attempt_id, input_provenance
        self.pending, self.digests = {}, []
        self.occurrences = set()

    def selected_bar_provenance(self, db, *, bar, instrument, signal_date, close, volume):
        """Freeze the bar used by the evaluator; raw metadata is only a DB claim."""
        if self.input_provenance != INPUT_PROVENANCE_MODE:
            raise AnalysisCaptureError("input_provenance_not_enabled")
        from sqlalchemy import text
        stored_bar = db.execute(text(
            "SELECT id,instrument_id,trading_date,close,volume,source,raw_payload_id,"
            "data_as_of,collected_at FROM market_bars WHERE id=:id"
        ), {"id": bar.id}).mappings().one_or_none()
        expected_bar = {
            "id": bar.id, "instrument_id": bar.instrument_id,
            "trading_date": _json_value(bar.trading_date), "close": bar.close,
            "volume": bar.volume, "source": bar.source,
            "raw_payload_id": bar.raw_payload_id,
        }
        if stored_bar is None or any(
            not _exact(stored_bar[key], expected) for key, expected in expected_bar.items()
        ):
            raise AnalysisCaptureError("selected_bar_read_relation_invalid")
        raw_id = bar.raw_payload_id
        if raw_id is not None and not _positive_id(raw_id):
            raise AnalysisCaptureError("selected_bar_raw_relation_invalid")
        raw = (db.execute(text(
            "SELECT id,source,endpoint,payload_path,sha256,ingestion_run_id,data_as_of,"
            "collected_at FROM raw_payloads WHERE id=:id"
        ), {"id": raw_id}).mappings().one_or_none() if raw_id is not None else None)
        if raw_id is not None and raw is None:
            raise AnalysisCaptureError("selected_bar_raw_relation_invalid")
        if raw is not None and raw["ingestion_run_id"] is not None:
            if (not _positive_id(raw["ingestion_run_id"])
                    or db.execute(text("SELECT id FROM ingestion_runs WHERE id=:id"),
                                  {"id": raw["ingestion_run_id"]}).scalar_one_or_none() is None):
                raise AnalysisCaptureError("selected_bar_raw_relation_invalid")
        evidence = {
            "schema": SELECTED_BAR_SCHEMA,
            "coverage": ["close", "volume"],
            "bar": {
                "id": bar.id, "instrument_id": bar.instrument_id,
                "trading_date": stored_bar["trading_date"],
                "close": bar.close, "volume": bar.volume, "source": bar.source,
                "raw_payload_id": raw_id,
                "data_as_of": stored_bar["data_as_of"],
                "collected_at": stored_bar["collected_at"],
            },
            "raw_payload": ({
                "id": raw["id"], "source": raw["source"], "endpoint": raw["endpoint"],
                "payload_path": raw["payload_path"], "sha256": raw["sha256"],
                "ingestion_run_id": raw["ingestion_run_id"],
                "data_as_of": raw["data_as_of"],
                "collected_at": raw["collected_at"],
            } if raw is not None else None),
            "raw_status": "linked_metadata" if raw is not None else "unknown",
            "raw_reason": None if raw is not None else "raw_payload_id_missing",
            "raw_bytes_verification": "bytes_unverified",
        }
        _validate_selected_bar_provenance(
            evidence, {"close": close, "volume": volume},
            subject={"instrument_id": instrument.id}, market_date=signal_date.isoformat(),
        )
        return evidence

    def before(self, evaluator, arguments, *, input_provenance=None):
        # Native validation/detachment before calling shared runtime. Do not coerce.
        pending = {"arguments": _detached(arguments), "captured_at": _now()}
        if self.input_provenance == INPUT_PROVENANCE_MODE:
            if input_provenance is None:
                raise AnalysisCaptureError("selected_bar_provenance_required")
            evidence = _detached(input_provenance)
            _validate_selected_bar_provenance(evidence, pending["arguments"])
            pending["input_provenance"] = evidence
        elif input_provenance is not None:
            raise AnalysisCaptureError("input_provenance_not_enabled")
        self.pending[evaluator] = pending

    def after(self, evaluator, actual):
        item = self.pending[evaluator]
        result = _detached({"passed": actual.passed, "state": actual.state, "reasons": list(actual.reasons)})
        bundle = capture_rule_inputs(evaluator=evaluator, arguments=item["arguments"])
        if not _exact(result, bundle["recorded_result"]):
            raise AnalysisCaptureError("worker_private_result_mismatch")
        item.update(actual_result=result, bundle=bundle)

    def persist(self, db, *, signal, instrument, strategy, strategy_key, namespace):
        from sqlalchemy import text
        occurrence = (instrument.id, strategy_key)
        if occurrence in self.occurrences or set(self.pending) != {"breakout_v1", "pullback_v1"}:
            raise AnalysisCaptureError("duplicate_or_missing_occurrence")
        self.occurrences.add(occurrence)
        selected = self.pending[strategy_key]["bundle"]
        if (strategy.name != strategy_key or strategy.version != selected["strategy_version"]
                or not _exact(strategy.canonical_config_snapshot, selected["config_snapshot"])
                or not _exact(strategy.config_json, selected["config_snapshot"])):
            raise AnalysisCaptureError("worker_strategy_binding_mismatch")
        # Flush supplies INSERT defaults/ids and links the exact stored signal.
        db.flush()
        db.refresh(signal)
        snapshot = {column.name: _json_value(getattr(signal, column.name)) for column in signal.__table__.columns}
        snapshot = _detached(snapshot)
        subject = {"instrument_id": instrument.id, "market": instrument.market, "exchange": instrument.exchange, "symbol": instrument.symbol}
        if self.input_provenance == INPUT_PROVENANCE_MODE:
            if not _exact(self.pending["breakout_v1"]["input_provenance"], self.pending["pullback_v1"]["input_provenance"]):
                raise AnalysisCaptureError("capture_pair_provenance_mismatch")
            for item in self.pending.values():
                _validate_selected_bar_provenance(
                    item["input_provenance"], item["arguments"],
                    subject=subject, market_date=signal.signal_date.isoformat(),
                )
        for evaluator in ("breakout_v1", "pullback_v1"):
            item = self.pending[evaluator]
            payload = _detached({"attempt_id": self.attempt_id, "database_id": self.owner["database_id"], "ordinal": len(self.digests),
                "evaluator": evaluator, "selected_strategy": {"id": strategy.id, "name": strategy.name, "version": strategy.version, "config": strategy.canonical_config_snapshot},
                "namespace": namespace, "subject": subject, "observed_market_date": signal.signal_date.isoformat(),
                "signal_snapshot": snapshot, **item})
            digest = _seal(payload)
            db.execute(text("INSERT INTO worker_capture_calls VALUES (:attempt,:ordinal,:payload,:digest)"),
                       {"attempt": self.attempt_id, "ordinal": len(self.digests), "payload": _canonical(payload), "digest": digest})
            self.digests.append(digest)
        self.pending.clear()


def execute_analysis_attempt(*, research_database_path, attempt_id, input_provenance=None):
    """Analyze only the owned database. No SessionLocal/default initialization."""
    _attempt_id(attempt_id)
    if input_provenance is not None and (type(input_provenance) is not str
            or input_provenance != INPUT_PROVENANCE_MODE):
        raise AnalysisCaptureError("invalid_input_provenance")
    with readonly_snapshot(research_database_path) as (connection, _):
        owner = _owner(connection)
    try:
        old = read_analysis_attempt(research_database_path=research_database_path, attempt_id=attempt_id)
    except AnalysisCaptureError as exc:
        if exc.code != "attempt_not_found":
            raise
    else:
        expected_kind = KIND_V2 if input_provenance == INPUT_PROVENANCE_MODE else KIND
        if old["receipt"]["kind"] != expected_kind:
            raise AnalysisCaptureError("attempt_mode_conflict")
        old["idempotent_reuse"] = True
        return old
    _environment(owner, research_database_path)
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.database_readiness import check_database_readiness
    from worker.pipeline import _analyze_session
    check_database_readiness(research_database_path)
    engine = create_engine("sqlite:///" + Path(research_database_path).as_posix())
    collector = _Collector(owner, attempt_id, input_provenance=input_provenance)
    committed_error = None
    try:
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            db.execute(text("PRAGMA foreign_keys=ON"))
            db.execute(text("BEGIN IMMEDIATE"))
            try:
                result = _analyze_session(db, capture=collector)
                if result["status"] != "success":
                    db.rollback()
                    return {"analysis": result, "outcome": "not_committed", "attempt_id": attempt_id}
                subjects = {subject for subject, _ in collector.occurrences}
                if (collector.pending or len(collector.digests) != result["signals_upserted"] * 4
                        or len(collector.occurrences)*2 != len(collector.digests)
                        or collector.occurrences != {(subject, key) for subject in subjects for key in ("breakout_v1", "pullback_v1")}):
                    raise AnalysisCaptureError("worker_capture_count_mismatch")
                source_run = db.execute(text("SELECT id FROM ingestion_runs WHERE run_type='collect' AND source='official' ORDER BY updated_at DESC,id DESC LIMIT 1")).scalar_one()
                receipt = {"kind": KIND_V2 if input_provenance == INPUT_PROVENANCE_MODE else KIND,
                    "attempt_id": attempt_id, "database_id": owner["database_id"], "source_snapshot": owner["source_snapshot"],
                    "captured_at": _now(), "analysis": result, "source_collection_run_id": source_run,
                    "call_digests": collector.digests, "signal_count": len(collector.digests)//2}
                db.execute(text("INSERT INTO worker_capture_attempts VALUES (:attempt,:payload,:digest)"),
                    {"attempt": attempt_id, "payload": _canonical(receipt), "digest": _seal(receipt)})
                db.flush()
            except Exception as exc:
                try:
                    db.rollback()
                except Exception as rollback_exc:
                    raise AnalysisCaptureError("analysis_failed", outcome="commit_outcome_unknown", detail=type(rollback_exc).__name__) from exc
                raise AnalysisCaptureError("analysis_failed", outcome="rollback_confirmed", detail=getattr(exc, "code", type(exc).__name__)) from exc
            try:
                db.commit()
            except Exception as exc:
                committed_error = type(exc).__name__
    finally:
        engine.dispose()
    try:
        verified = read_analysis_attempt(research_database_path=research_database_path, attempt_id=attempt_id)
    except Exception as exc:
        outcome = "not_committed_verified" if committed_error and isinstance(exc, AnalysisCaptureError) and exc.code == "attempt_not_found" else "commit_outcome_unknown"
        raise AnalysisCaptureError("commit_readback_failed", outcome=outcome, detail=getattr(exc, "code", committed_error or type(exc).__name__)) from exc
    if committed_error:
        verified["outcome"] = "committed_verified_after_error"
        verified["commit_error"] = committed_error
    return verified


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--source-snapshot-path", required=True)
    create.add_argument("--expected-source-sha256", required=True)
    create.add_argument("--research-database-path", required=True)
    for name in ("run", "read"):
        command = sub.add_parser(name)
        command.add_argument("--research-database-path", required=True)
        command.add_argument("--attempt-id", required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        result = {"create": create_research_database, "run": execute_analysis_attempt, "read": read_analysis_attempt}[command](**args)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": getattr(exc, "code", type(exc).__name__), "outcome": getattr(exc, "outcome", None), "detail": getattr(exc, "detail", None)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
