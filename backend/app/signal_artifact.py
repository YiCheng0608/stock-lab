"""Pure contract for the opt-in, versioned signal-artifact store.

The legacy ``signals`` table is intentionally not imported here.  This module
only normalizes caller-provided research output into a deterministic contract;
the accompanying store is responsible for persistence, ownership, and
append-only revision rules.

The contract is deliberately conservative for this first B2 slice:

* confidence is always ``None`` and ``signal-confidence/v2`` is explicitly
  non-probabilistic;
* no point-in-time/session gate is claimed, so earliest execution is always
  ``None`` with a machine-readable reason;
* source and implementation declarations are caller-provided only; and
* all digests that can be calculated from an embedded manifest are recalculated
  before a payload can be written.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


SIGNAL_ARTIFACT_VERSION = "signal-artifact/v1"
SIGNAL_CONFIDENCE_SEMANTICS_VERSION = "signal-confidence/v2"
CALLER_PROVIDED_ONLY = "caller_provided_only"
EARLIEST_EXECUTION_UNAVAILABLE_REASON = (
    "execution_time_unavailable_without_pit_session_availability"
)
MARKET_TIMEZONE = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MISSING = object()


class SignalArtifactContractError(ValueError):
    """Raised when a signal artifact is incomplete or not canonicalizable."""


def _error(field_name: str, message: str) -> SignalArtifactContractError:
    return SignalArtifactContractError(f"{field_name}: {message}")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field_name, "is required")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


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
            raise _error(field_name, "must be an ISO timestamp with timezone") from exc
    else:
        raise _error(field_name, "must be a timezone-aware datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _error(field_name, "must not be naive or date-only")
    return parsed.astimezone(UTC).isoformat()


def _market_date(value: date | str | datetime, field_name: str = "market_date") -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise _error(field_name, "must not be a naive datetime")
        return value.astimezone(MARKET_TIMEZONE).date().isoformat()
    if isinstance(value, datetime):  # pragma: no cover - kept as a type guard
        raise _error(field_name, "must be a date")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError as exc:
            raise _error(field_name, "must be an ISO date") from exc
    raise _error(field_name, "must be a date, ISO date, or aware datetime")


def _canonical(value: Any, field_name: str = "value") -> Any:
    """Return JSON-compatible deterministic values and reject unsafe numbers."""

    if isinstance(value, datetime):
        return _timestamp(value, field_name)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise _error(field_name, "mapping keys must be strings")
            child_name = f"{field_name}.{key}"
            if key.endswith("_at") or key in {"decision_at", "generated_at"}:
                normalized[key] = None if child is None else _timestamp(child, child_name)
            else:
                normalized[key] = _canonical(child, child_name)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_canonical(child, f"{field_name}[]") for child in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(field_name, "must not be NaN or infinite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise _error(field_name, f"unsupported JSON value {type(value).__name__}")


def canonical_json(value: Any, *, field_name: str = "value") -> str:
    try:
        return json.dumps(
            _canonical(value, field_name),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SignalArtifactContractError):
            raise
        raise _error(field_name, "cannot be canonically encoded") from exc


def digest_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("digest input must be text")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_json(value: Any, *, field_name: str = "value") -> str:
    return digest_text(canonical_json(value, field_name=field_name))


def normalize_digest(value: Any, field_name: str) -> str:
    """Normalize accepted caller spelling to the strict persisted form.

    A bare 64-character SHA-256 is accepted as an input compatibility spelling
    and immediately normalized to ``sha256:<hex>``.  Stored values and all
    returned payloads use the prefixed form only.
    """

    text = _required_text(value, field_name).casefold()
    if len(text) == 64 and all(char in "0123456789abcdef" for char in text):
        text = "sha256:" + text
    if not _DIGEST_RE.fullmatch(text):
        raise _error(field_name, "must be sha256:<64 lowercase hexadecimal characters>")
    return text


def _mapping(value: Any, field_name: str, *, allow_empty: bool = False) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or (not allow_empty and not value):
        suffix = "an object" if allow_empty else "a non-empty object"
        raise _error(field_name, f"must be {suffix}")
    return value


def _sequence_text(value: Any, field_name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _error(field_name, "must be an array of strings")
    result = tuple(_required_text(item, f"{field_name}[]") for item in value)
    if len(set(result)) != len(result):
        raise _error(field_name, "must not contain duplicate values")
    if not allow_empty and not result:
        raise _error(field_name, "must not be empty")
    return tuple(sorted(result))


def _instrument(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        pieces = value.strip().split(":", 1)
        if len(pieces) != 2:
            raise _error("instrument", "must include exchange and symbol")
        exchange, symbol = pieces
    else:
        obj = _mapping(value, "instrument")
        exchange, symbol = obj.get("exchange"), obj.get("symbol")
    exchange = _required_text(exchange, "instrument.exchange").upper()
    symbol = _required_text(symbol, "instrument.symbol").upper()
    return {"exchange": exchange, "symbol": symbol}


def _semantics(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = {
            "version": value,
            "kind": "rule_only",
            "is_calibrated": False,
            "is_probability": False,
        }
    obj = dict(_mapping(value, "signal_output_semantics"))
    expected = {
        "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
        "kind": "rule_only",
        "is_calibrated": False,
        "is_probability": False,
    }
    if (
        set(obj) != set(expected)
        or obj.get("version") != expected["version"]
        or obj.get("kind") != expected["kind"]
        or type(obj.get("is_calibrated")) is not bool
        or obj.get("is_calibrated") is not False
        or type(obj.get("is_probability")) is not bool
        or obj.get("is_probability") is not False
    ):
        raise _error(
            "signal_output_semantics",
            "must be the exact non-probability rule-only signal-confidence/v2 contract",
        )
    return dict(expected)


def _confidence_semantics(value: Any) -> dict[str, Any]:
    if value is None:
        value = {
            "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
            "kind": "not_calibrated",
            "is_calibrated": False,
            "is_probability": False,
            "display_label_zh": "未校準；非預測勝率",
        }
    obj = dict(_mapping(value, "confidence_semantics"))
    expected = {
        "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
        "kind": "not_calibrated",
        "is_calibrated": False,
        "is_probability": False,
        "display_label_zh": "未校準；非預測勝率",
    }
    if (
        set(obj) != set(expected)
        or obj.get("version") != expected["version"]
        or obj.get("kind") != expected["kind"]
        or type(obj.get("is_calibrated")) is not bool
        or obj.get("is_calibrated") is not False
        or type(obj.get("is_probability")) is not bool
        or obj.get("is_probability") is not False
        or obj.get("display_label_zh") != expected["display_label_zh"]
    ):
        # Explicitly reject bool-as-number and caller-authored display claims;
        # the persisted semantic marker is a fixed project contract.
        raise _error("confidence_semantics", "must match the exact v2 non-probability contract")
    return dict(expected)


def _strict_basis_manifest(value: Any) -> dict[str, Any]:
    obj = dict(_mapping(value, "basis_manifest"))
    expected_keys = {"mode", "verification", "status", "value", "reason"}
    if set(obj) != expected_keys:
        raise _error("basis_manifest", "has an incomplete or unknown shape")
    if obj["mode"] != CALLER_PROVIDED_ONLY:
        raise _error("basis_manifest.mode", "must be caller_provided_only")
    if obj["verification"] != "not_officially_verified":
        raise _error("basis_manifest.verification", "must be not_officially_verified")
    status = _required_text(obj["status"], "basis_manifest.status").casefold()
    if status not in {"provided", "unknown", "unavailable"}:
        raise _error("basis_manifest.status", "must be provided, unknown, or unavailable")
    value_text = obj["value"]
    reason = obj["reason"]
    if value_text is not None and not isinstance(value_text, str):
        raise _error("basis_manifest.value", "must be a string or null")
    if reason is not None and not isinstance(reason, str):
        raise _error("basis_manifest.reason", "must be a string or null")
    if status == "provided":
        if not isinstance(value_text, str) or not value_text.strip() or reason is not None:
            raise _error("basis_manifest", "provided requires non-empty value and null reason")
    elif value_text is not None or not isinstance(reason, str) or not reason.strip():
        raise _error("basis_manifest", "unknown/unavailable requires null value and reason")
    return {
        "mode": CALLER_PROVIDED_ONLY,
        "verification": "not_officially_verified",
        "status": status,
        "value": None if value_text is None else value_text.strip(),
        "reason": None if reason is None else reason.strip(),
    }


def _strict_dependency_manifest(value: Any) -> dict[str, Any]:
    obj = dict(_mapping(value, "dependency_manifest"))
    expected_keys = {"mode", "verification", "references", "unknown_reasons"}
    if set(obj) != expected_keys:
        raise _error("dependency_manifest", "has an incomplete or unknown shape")
    if obj["mode"] != CALLER_PROVIDED_ONLY:
        raise _error("dependency_manifest.mode", "must be caller_provided_only")
    if obj["verification"] != "not_officially_verified":
        raise _error(
            "dependency_manifest.verification",
            "must be not_officially_verified",
        )
    references = _sequence_text(obj["references"], "dependency_manifest.references")
    unknown_reasons = _sequence_text(
        obj["unknown_reasons"], "dependency_manifest.unknown_reasons"
    )
    if not references and not unknown_reasons:
        raise _error(
            "dependency_manifest",
            "must include at least one reference or unknown reason",
        )
    return {
        "mode": CALLER_PROVIDED_ONLY,
        "verification": "not_officially_verified",
        "references": list(references),
        "unknown_reasons": list(unknown_reasons),
    }


def _strict_implementation_ref(value: Any, top_digest: str) -> dict[str, Any]:
    obj = dict(_mapping(value, "implementation_ref"))
    expected_keys = {"mode", "verification", "ref", "digest"}
    if set(obj) != expected_keys:
        raise _error("implementation_ref", "has an incomplete or unknown shape")
    if obj["mode"] != CALLER_PROVIDED_ONLY:
        raise _error("implementation_ref.mode", "must be caller_provided_only")
    if obj["verification"] != "not_officially_verified":
        raise _error(
            "implementation_ref.verification", "must be not_officially_verified"
        )
    ref = _required_text(obj["ref"], "implementation_ref.ref")
    digest = normalize_digest(obj["digest"], "implementation_ref.digest")
    if digest != top_digest:
        raise _error("implementation_ref.digest", "must match implementation_digest")
    return {
        "mode": CALLER_PROVIDED_ONLY,
        "verification": "not_officially_verified",
        "ref": ref,
        "digest": digest,
    }


@dataclass(frozen=True)
class SignalArtifact:
    """Caller-facing, detached signal artifact contract.

    ``generated_at`` is a candidate write timestamp.  It is stored only in the
    attempt relation; the first successful candidate becomes immutable store
    metadata and never enters the canonical research payload.
    """

    instrument: Mapping[str, Any] | str
    market_date: date | str | datetime
    strategy_name: str
    strategy_version: str
    signal_output_semantics: Mapping[str, Any] | str
    status: str
    rule_state: Mapping[str, Any] | str = field(default_factory=dict)
    feature_artifact_refs: Sequence[str] = field(default_factory=tuple)
    input_snapshot_id: str = ""
    input_snapshot_hash: str = ""
    ruleset_snapshot: Any = field(default_factory=dict)
    ruleset_digest: str | None = None
    implementation_digest: str = ""
    basis_manifest: Any = field(default_factory=dict)
    basis_digest: str | None = None
    dependency_manifest: Any = field(default_factory=dict)
    dependency_digest: str | None = None
    implementation_ref: Mapping[str, Any] | None = None
    rule_evidence: Any = field(default_factory=dict)
    data_quality: Any = field(default_factory=dict)
    missing_reasons: Sequence[str] = field(default_factory=tuple)
    decision_at: datetime | str = ""
    as_of_at: datetime | str | None = None
    confidence: None = None
    confidence_semantics: Mapping[str, Any] | None = None
    earliest_execution_at: None = None
    earliest_execution_reason: str = EARLIEST_EXECUTION_UNAVAILABLE_REASON
    lineage_subject: str = "signal"
    revision: int = 1
    supersedes_artifact_key: str | None = None
    legacy_reference: str | None = None
    generated_at: datetime | str | None = None
    first_generated_at: datetime | str | None = None
    source_mode: str = CALLER_PROVIDED_ONLY
    implementation_mode: str = CALLER_PROVIDED_ONLY
    artifact_key: str | None = None
    lifecycle_state: str = "active"
    lifecycle_reason: str | None = None
    lifecycle_at: datetime | str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SignalArtifact":
        normalized = normalize_signal_artifact(value, include_generated=True)
        strategy = normalized["strategy"]
        snapshot = normalized["input_snapshot"]
        return cls(
            instrument=normalized["instrument"],
            market_date=normalized["market_date"],
            strategy_name=strategy["name"],
            strategy_version=strategy["version"],
            signal_output_semantics=normalized["signal_output_semantics"],
            status=normalized["status"],
            rule_state=normalized["rule_state"],
            feature_artifact_refs=tuple(normalized["feature_artifact_refs"]),
            input_snapshot_id=snapshot["id"],
            input_snapshot_hash=snapshot["hash"],
            ruleset_snapshot=normalized["ruleset_snapshot"],
            ruleset_digest=normalized["ruleset_digest"],
            implementation_digest=normalized["implementation_digest"],
            basis_manifest=normalized["basis_manifest"],
            basis_digest=normalized["basis_digest"],
            dependency_manifest=normalized["dependency_manifest"],
            dependency_digest=normalized["dependency_digest"],
            implementation_ref=normalized["implementation_ref"],
            rule_evidence=normalized["rule_evidence"],
            data_quality=normalized["data_quality"],
            missing_reasons=tuple(normalized["missing_reasons"]),
            decision_at=normalized["decision_at"],
            as_of_at=normalized["as_of_at"],
            confidence=None,
            confidence_semantics=normalized["confidence_semantics"],
            earliest_execution_at=None,
            earliest_execution_reason=normalized["earliest_execution_reason"],
            lineage_subject=normalized["lineage_subject"],
            revision=normalized["revision"],
            supersedes_artifact_key=normalized["supersedes_artifact_key"],
            legacy_reference=normalized["legacy_reference"],
            generated_at=normalized.get("generated_at"),
            first_generated_at=normalized.get("generated_at"),
            source_mode=normalized["source_mode"],
            implementation_mode=normalized["implementation_mode"],
            artifact_key=normalized.get("artifact_key"),
            lifecycle_state=normalized["lifecycle_state"],
            lifecycle_reason=normalized["lifecycle_reason"],
            lifecycle_at=normalized["lifecycle_at"],
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a normalized mapping including write-only candidate metadata."""

        return normalize_signal_artifact(self, include_generated=True)

    def canonical_payload(self) -> str:
        return canonical_json(
            normalize_signal_artifact(self, include_generated=False),
            field_name="signal_artifact.payload",
        )


def normalize_signal_artifact(
    value: SignalArtifact | Mapping[str, Any], *, include_generated: bool = False
) -> dict[str, Any]:
    """Normalize and validate a mapping without consulting SQLite."""

    if isinstance(value, SignalArtifact):
        source: Mapping[str, Any] = {
            name: getattr(value, name)
            for name in value.__dataclass_fields__
        }
    elif isinstance(value, Mapping):
        source = value
    else:
        raise _error("artifact", "must be a SignalArtifact or mapping")

    allowed_top_level = {
        "contract",
        "artifact_key",
        "instrument",
        "market_date",
        "strategy",
        "strategy_name",
        "strategy_version",
        "signal_output_semantics",
        "signal_output_semantics_version",
        "semantics",
        "status",
        "rule_state",
        "feature_artifact_refs",
        "feature_refs",
        "input_snapshot",
        "input_snapshot_id",
        "input_snapshot_hash",
        "ruleset_snapshot",
        "settings_snapshot",
        "ruleset_digest",
        "implementation_digest",
        "implementation_ref",
        "basis_manifest",
        "price_basis",
        "basis_digest",
        "dependency_manifest",
        "dependency_digest",
        "rule_evidence",
        "data_quality",
        "missing_reasons",
        "decision_at",
        "as_of_at",
        "asof_at",
        "confidence",
        "confidence_semantics",
        "earliest_execution_at",
        "earliest_execution_reason",
        "lineage_subject",
        "revision",
        "supersedes_artifact_key",
        "supersedes",
        "legacy_reference",
        "legacy_readonly_reference",
        "source_mode",
        "implementation_mode",
        "lifecycle_state",
        "lifecycle_reason",
        "lifecycle_at",
        "generated_at",
        "first_generated_at",
    }
    unknown_top_level = sorted(set(source) - allowed_top_level)
    if unknown_top_level:
        raise _error("artifact", f"unknown top-level fields: {unknown_top_level}")
    supplied_contract = source.get("contract")
    if supplied_contract is not None and supplied_contract != SIGNAL_ARTIFACT_VERSION:
        raise _error("contract", f"must be {SIGNAL_ARTIFACT_VERSION}")

    strategy = source.get("strategy")
    strategy_name = source.get("strategy_name")
    strategy_version = source.get("strategy_version")
    if isinstance(strategy, Mapping):
        nested_name = strategy.get("name")
        nested_version = strategy.get("version")
        if strategy_name is not None and nested_name != strategy_name:
            raise _error("strategy", "nested name conflicts with strategy_name")
        if strategy_version is not None and nested_version != strategy_version:
            raise _error("strategy", "nested version conflicts with strategy_version")
        strategy_name = nested_name if nested_name is not None else strategy_name
        strategy_version = nested_version if nested_version is not None else strategy_version
    elif strategy is not None:
        raise _error("strategy", "must be an object")
    strategy_name = _required_text(strategy_name, "strategy.name")
    strategy_version = _required_text(strategy_version, "strategy.version")

    semantics = source.get("signal_output_semantics", _MISSING)
    semantics_alias = source.get("semantics", _MISSING)
    if semantics is not _MISSING and semantics_alias is not _MISSING:
        if _semantics(semantics) != _semantics(semantics_alias):
            raise _error("signal_output_semantics", "conflicts with semantics")
    if semantics is _MISSING:
        semantics = semantics_alias
    if semantics is _MISSING:
        raise _error("signal_output_semantics", "is required")
    semantics = _semantics(semantics)
    if (
        source.get("signal_output_semantics_version") is not None
        and source["signal_output_semantics_version"] != semantics["version"]
    ):
        raise _error(
            "signal_output_semantics_version",
            "conflicts with signal_output_semantics.version",
        )
    instrument = _instrument(source.get("instrument", _MISSING))
    market_date = _market_date(source.get("market_date", _MISSING))
    status = _required_text(source.get("status"), "status")
    rule_state = source.get("rule_state", {})
    if isinstance(rule_state, str):
        rule_state = {"value": _required_text(rule_state, "rule_state")}
    else:
        rule_state = dict(_mapping(rule_state, "rule_state", allow_empty=True))
    refs = source.get("feature_artifact_refs", _MISSING)
    refs_alias = source.get("feature_refs", _MISSING)
    if refs is not _MISSING and refs_alias is not _MISSING:
        if _sequence_text(refs, "feature_artifact_refs") != _sequence_text(
            refs_alias, "feature_refs"
        ):
            raise _error("feature_artifact_refs", "conflicts with feature_refs")
    if refs is _MISSING:
        refs = () if refs_alias is _MISSING else refs_alias
    refs = _sequence_text(refs, "feature_artifact_refs")

    snapshot = source.get("input_snapshot")
    snapshot_id = source.get("input_snapshot_id")
    snapshot_hash = source.get("input_snapshot_hash")
    if snapshot is not None:
        snapshot_obj = _mapping(snapshot, "input_snapshot")
        nested_id = snapshot_obj.get("id")
        nested_hash = snapshot_obj.get("hash")
        if snapshot_id is not None and nested_id != snapshot_id:
            raise _error("input_snapshot", "nested id conflicts with input_snapshot_id")
        if snapshot_hash is not None and nested_hash != snapshot_hash:
            raise _error("input_snapshot", "nested hash conflicts with input_snapshot_hash")
        snapshot_id = nested_id if nested_id is not None else snapshot_id
        snapshot_hash = nested_hash if nested_hash is not None else snapshot_hash
    snapshot_id = _required_text(snapshot_id, "input_snapshot.id")
    snapshot_hash = normalize_digest(snapshot_hash, "input_snapshot.hash")

    ruleset_snapshot = source.get("ruleset_snapshot", _MISSING)
    settings_snapshot = source.get("settings_snapshot", _MISSING)
    if ruleset_snapshot is not _MISSING and settings_snapshot is not _MISSING:
        if canonical_json(ruleset_snapshot, field_name="ruleset_snapshot") != canonical_json(
            settings_snapshot, field_name="settings_snapshot"
        ):
            raise _error("ruleset_snapshot", "conflicts with settings_snapshot")
    if ruleset_snapshot is _MISSING:
        ruleset_snapshot = settings_snapshot
    if ruleset_snapshot is _MISSING:
        raise _error("ruleset_snapshot", "is required")
    ruleset_snapshot = _canonical(
        _mapping(ruleset_snapshot, "ruleset_snapshot"), "ruleset_snapshot"
    )
    expected_ruleset_digest = digest_json(ruleset_snapshot, field_name="ruleset_snapshot")
    ruleset_digest_value = source.get("ruleset_digest")
    ruleset_digest = normalize_digest(
        expected_ruleset_digest if ruleset_digest_value is None else ruleset_digest_value,
        "ruleset_digest",
    )
    if ruleset_digest != expected_ruleset_digest:
        raise _error("ruleset_digest", "does not match ruleset_snapshot")

    implementation_digest = normalize_digest(
        source.get("implementation_digest"), "implementation_digest"
    )
    implementation_ref = _strict_implementation_ref(
        source.get("implementation_ref"), implementation_digest
    )

    basis_manifest = source.get("basis_manifest", _MISSING)
    price_basis = source.get("price_basis", _MISSING)
    if basis_manifest is not _MISSING and price_basis is not _MISSING:
        if canonical_json(basis_manifest, field_name="basis_manifest") != canonical_json(
            price_basis, field_name="price_basis"
        ):
            raise _error("basis_manifest", "conflicts with price_basis")
    if basis_manifest is _MISSING:
        basis_manifest = price_basis
    if basis_manifest is _MISSING:
        raise _error("basis_manifest", "is required")
    basis_manifest = _strict_basis_manifest(basis_manifest)
    expected_basis_digest = digest_json(basis_manifest, field_name="basis_manifest")
    basis_digest_value = source.get("basis_digest")
    basis_digest = normalize_digest(
        expected_basis_digest if basis_digest_value is None else basis_digest_value,
        "basis_digest",
    )
    if basis_digest != expected_basis_digest:
        raise _error("basis_digest", "does not match basis_manifest")

    dependency_manifest = source.get("dependency_manifest", _MISSING)
    if dependency_manifest is _MISSING:
        raise _error("dependency_manifest", "is required")
    dependency_manifest = _strict_dependency_manifest(dependency_manifest)
    expected_dependency_digest = digest_json(
        dependency_manifest, field_name="dependency_manifest"
    )
    dependency_digest_value = source.get("dependency_digest")
    dependency_digest = normalize_digest(
        expected_dependency_digest
        if dependency_digest_value is None
        else dependency_digest_value,
        "dependency_digest",
    )
    if dependency_digest != expected_dependency_digest:
        raise _error("dependency_digest", "does not match dependency_manifest")

    rule_evidence = _canonical(
        _mapping(source.get("rule_evidence", {}), "rule_evidence", allow_empty=True),
        "rule_evidence",
    )
    data_quality = _canonical(
        _mapping(source.get("data_quality", {}), "data_quality", allow_empty=True),
        "data_quality",
    )
    missing_reasons = _sequence_text(source.get("missing_reasons", ()), "missing_reasons")
    decision_at = _timestamp(source.get("decision_at"), "decision_at")
    as_of_raw = source.get("as_of_at", _MISSING)
    as_of_alias = source.get("asof_at", _MISSING)
    if as_of_raw is not _MISSING and as_of_alias is not _MISSING:
        if _timestamp(as_of_raw, "as_of_at") != _timestamp(as_of_alias, "asof_at"):
            raise _error("as_of_at", "conflicts with asof_at")
    if as_of_raw is _MISSING:
        as_of_raw = None if as_of_alias is _MISSING else as_of_alias
    as_of_at = None if as_of_raw is None else _timestamp(as_of_raw, "as_of_at")

    if source.get("confidence") is not None:
        raise _error("confidence", "must be null for rule-only signal artifacts")
    confidence_semantics = _confidence_semantics(source.get("confidence_semantics"))
    if source.get("earliest_execution_at") is not None:
        raise _error(
            "earliest_execution_at",
            "must be null until PIT/session/availability gates are implemented",
        )
    earliest_reason = _required_text(
        source.get("earliest_execution_reason"), "earliest_execution_reason"
    )
    if earliest_reason != EARLIEST_EXECUTION_UNAVAILABLE_REASON:
        raise _error(
            "earliest_execution_reason",
            f"must be {EARLIEST_EXECUTION_UNAVAILABLE_REASON}",
        )

    lineage_subject = _required_text(
        source.get("lineage_subject", "signal"), "lineage_subject"
    )
    if lineage_subject != "signal":
        raise _error("lineage_subject", "must be signal in this foundation slice")
    revision = source.get("revision", 1)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
        raise _error("revision", "must be a positive integer")
    supersedes = _optional_text(
        source.get("supersedes_artifact_key", source.get("supersedes")),
        "supersedes_artifact_key",
    )
    if source.get("supersedes_artifact_key") is not None and source.get("supersedes") is not None:
        if source["supersedes_artifact_key"] != source["supersedes"]:
            raise _error("supersedes", "conflicts with supersedes_artifact_key")
    if revision == 1 and supersedes is not None:
        raise _error("supersedes_artifact_key", "root revision must not supersede a parent")
    if revision > 1 and supersedes is None:
        raise _error("supersedes_artifact_key", "revision must name its predecessor")
    legacy_reference = _optional_text(
        source.get("legacy_reference", source.get("legacy_readonly_reference")),
        "legacy_reference",
    )
    if (
        source.get("legacy_reference") is not None
        and source.get("legacy_readonly_reference") is not None
        and source["legacy_reference"] != source["legacy_readonly_reference"]
    ):
        raise _error("legacy_reference", "conflicts with legacy_readonly_reference")

    source_mode = _required_text(source.get("source_mode", CALLER_PROVIDED_ONLY), "source_mode")
    implementation_mode = _required_text(
        source.get("implementation_mode", CALLER_PROVIDED_ONLY), "implementation_mode"
    )
    if source_mode != CALLER_PROVIDED_ONLY:
        raise _error("source_mode", "must be caller_provided_only")
    if implementation_mode != CALLER_PROVIDED_ONLY:
        raise _error("implementation_mode", "must be caller_provided_only")

    lifecycle_state = _required_text(
        source.get("lifecycle_state", "active"), "lifecycle_state"
    ).casefold()
    if lifecycle_state not in {"active", "withdrawn"}:
        raise _error("lifecycle_state", "must be active or withdrawn")
    if revision == 1 and lifecycle_state != "active":
        raise _error("lifecycle_state", "a root must be active")
    if revision > 1 and lifecycle_state != "withdrawn":
        raise _error("lifecycle_state", "a child must be withdrawn in this foundation slice")
    lifecycle_reason = _optional_text(source.get("lifecycle_reason"), "lifecycle_reason")
    lifecycle_at_raw = source.get("lifecycle_at")
    lifecycle_at = (
        None if lifecycle_at_raw is None else _timestamp(lifecycle_at_raw, "lifecycle_at")
    )
    if lifecycle_state == "withdrawn":
        if lifecycle_reason is None or lifecycle_at is None:
            raise _error(
                "lifecycle",
                "withdrawn requires lifecycle_reason and aware lifecycle_at",
            )
        if lifecycle_at < decision_at:
            raise _error("lifecycle_at", "must not precede decision_at")
    elif lifecycle_reason is not None or lifecycle_at is not None:
        raise _error("lifecycle", "active must not carry withdrawal metadata")

    normalized: dict[str, Any] = {
        "contract": SIGNAL_ARTIFACT_VERSION,
        "lineage_subject": lineage_subject,
        "instrument": instrument,
        "market_date": market_date,
        "strategy": {"name": strategy_name, "version": strategy_version},
        "signal_output_semantics": semantics,
        "signal_output_semantics_version": semantics["version"],
        "status": status,
        "rule_state": rule_state,
        "confidence": None,
        "confidence_semantics": confidence_semantics,
        "feature_artifact_refs": list(refs),
        "input_snapshot": {"id": snapshot_id, "hash": snapshot_hash},
        "ruleset_snapshot": ruleset_snapshot,
        "ruleset_digest": ruleset_digest,
        "implementation_digest": implementation_digest,
        "implementation_ref": implementation_ref,
        "basis_manifest": basis_manifest,
        "basis_digest": basis_digest,
        "dependency_manifest": dependency_manifest,
        "dependency_digest": dependency_digest,
        "rule_evidence": rule_evidence,
        "data_quality": data_quality,
        "missing_reasons": list(missing_reasons),
        "decision_at": decision_at,
        "as_of_at": as_of_at,
        "earliest_execution_at": None,
        "earliest_execution_reason": earliest_reason,
        "revision": revision,
        "supersedes_artifact_key": supersedes,
        "legacy_reference": legacy_reference,
        "source_mode": source_mode,
        "implementation_mode": implementation_mode,
        "lifecycle_state": lifecycle_state,
        "lifecycle_reason": lifecycle_reason,
        "lifecycle_at": lifecycle_at,
    }
    candidate_generated = source.get("generated_at", _MISSING)
    candidate_first_generated = source.get("first_generated_at", _MISSING)
    if candidate_generated is not _MISSING and candidate_first_generated is not _MISSING:
        if candidate_generated is None and candidate_first_generated is None:
            pass
        elif candidate_generated is None or candidate_first_generated is None:
            raise _error("generated_at", "conflicts with first_generated_at")
        elif _timestamp(candidate_generated, "generated_at") != _timestamp(
            candidate_first_generated, "first_generated_at"
        ):
            raise _error("generated_at", "conflicts with first_generated_at")
    if candidate_generated is _MISSING:
        candidate_generated = (
            None if candidate_first_generated is _MISSING else candidate_first_generated
        )
    if include_generated:
        normalized["generated_at"] = (
            None if candidate_generated is None else _timestamp(candidate_generated, "generated_at")
        )
    supplied_key = source.get("artifact_key")
    if supplied_key is not None:
        normalized["artifact_key"] = _required_text(supplied_key, "artifact_key")
    return _canonical(normalized, "signal_artifact")


__all__ = [
    "CALLER_PROVIDED_ONLY",
    "EARLIEST_EXECUTION_UNAVAILABLE_REASON",
    "SIGNAL_ARTIFACT_VERSION",
    "SIGNAL_CONFIDENCE_SEMANTICS_VERSION",
    "SignalArtifact",
    "SignalArtifactContractError",
    "canonical_json",
    "digest_json",
    "digest_text",
    "normalize_digest",
    "normalize_signal_artifact",
]
