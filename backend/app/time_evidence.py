"""Versioned, caller-provided time evidence.

This module deliberately has no database, HTTP, worker, or model dependency.
It provides the small contract used by the opt-in :mod:`time_evidence_store`
module.  The contract is intentionally conservative: a missing time is not
inferred, a naive datetime is not assigned a timezone, and a collection time
is never promoted to a historical availability time.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

UTC = timezone.utc
TIME_EVIDENCE_VERSION = "time-evidence/v1"

# These are the fields that every strict new record must mention.  An
# unavailable/unknown field is still explicit and must contain a reason.
TIMESTAMP_FIELDS = (
    "published_at",
    "first_available_at",
    "collected_at",
    "revision_available_at",
    "decision_at",
    "generated_at",
    "earliest_execution_at",
)
ANCHOR_FIELDS = ("market_date", "event_date", "instant", "event_at")
OPTIONAL_FIELDS = ANCHOR_FIELDS
ALL_TIME_FIELDS = ANCHOR_FIELDS + TIMESTAMP_FIELDS
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KNOWN_PRECISIONS = {
    "instant",
    "second",
    "minute",
    "hour",
    "date",
    "none",
}
_ROOT_KIND = "root"
_REVISION_KIND = "revision"


class TimeEvidenceError(ValueError):
    """Base error for malformed or unsafe time evidence."""


class TimeEvidenceContractError(TimeEvidenceError):
    """Raised when a caller does not satisfy the strict v1 contract."""


def _error(field: str, message: str) -> TimeEvidenceContractError:
    return TimeEvidenceContractError(f"{field}: {message}")


def _json_ready(value: Any, field: str = "value") -> Any:
    """Return a deterministic, detached JSON-compatible value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(field, "must not contain NaN or infinity")
        return value
    if isinstance(value, datetime):
        return _normalize_datetime(value, field)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item, f"{field}.{key}")
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item, f"{field}[]") for item in value]
    raise _error(field, f"unsupported JSON value type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize normalized JSON with a stable key order."""

    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_datetime(value: datetime, field: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise _error(field, "known datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def normalize_timestamp(value: datetime | str, field: str = "timestamp") -> str:
    """Normalize an aware datetime/ISO timestamp to UTC.

    Date-only values are intentionally not accepted here.  Use a date-valued
    field with ``precision='date'`` when the source has no wall-clock time.
    """

    if isinstance(value, datetime):
        return _normalize_datetime(value, field)
    if not isinstance(value, str):
        raise _error(field, "must be an aware datetime or ISO timestamp")
    text = value.strip()
    if not text:
        raise _error(field, "must not be empty")
    if _DATE_RE.fullmatch(text):
        raise _error(field, "date-only value must use precision='date'; midnight is not inferred")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise _error(field, "must be an ISO timestamp with timezone") from exc
    return _normalize_datetime(parsed, field)


def normalize_date(value: date | str, field: str = "date") -> str:
    if isinstance(value, datetime):
        raise _error(field, "datetime is not a date; do not drop its timezone or time")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value.strip()):
        raise _error(field, "must be an ISO calendar date YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise _error(field, "must be a valid ISO calendar date") from exc


def _part(obj: Mapping[str, Any], name: str, *aliases: str) -> Any:
    for key in (name, *aliases):
        if key in obj:
            return obj[key]
    return None


_MISSING = object()


def _alias_value(obj: Mapping[str, Any], names: tuple[str, ...], field: str, default: Any = _MISSING) -> Any:
    present = [name for name in names if name in obj]
    if not present:
        return default
    first = obj[present[0]]
    first_json = canonical_json(first)
    for name in present[1:]:
        if canonical_json(obj[name]) != first_json:
            raise _error(field, f"aliases conflict: {', '.join(present)}")
    return first


def _nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field, "must be a non-empty string")
    return value.strip()


def _identity(value: Any, field: str, *, default_id: str | None = None) -> dict[str, Any]:
    if value is None:
        if default_id is None:
            raise _error(field, "is required")
        value = {"id": default_id}
    if isinstance(value, str):
        value = {"id": _nonempty_text(value, field)}
    if not isinstance(value, Mapping):
        raise _error(field, "must be a string or mapping identity")
    result = _json_ready(value, field)
    if not result:
        raise _error(field, "must not be empty")
    if "id" in result:
        result["id"] = _nonempty_text(result["id"], f"{field}.id")
    return result


def normalize_identity(value: Mapping[str, Any] | str, field: str = "identity") -> dict[str, Any]:
    """Normalize an identity using the same rules as ``TimeEvidence``."""

    return _identity(value, field)


def _revision_identity(value: Any, supersedes: Any) -> dict[str, Any]:
    if value is None:
        raise _error("revision_identity", "is required; do not infer a root revision")
    elif isinstance(value, str):
        result = {"id": _nonempty_text(value, "revision_identity"), "kind": _ROOT_KIND}
    elif isinstance(value, Mapping):
        result = _json_ready(value, "revision_identity")
        result["id"] = _nonempty_text(result.get("id"), "revision_identity.id")
        result.setdefault("kind", _REVISION_KIND if supersedes is not None else _ROOT_KIND)
    else:
        raise _error("revision_identity", "must be a string or mapping identity")

    kind = _nonempty_text(result.get("kind"), "revision_identity.kind").casefold()
    if kind not in {_ROOT_KIND, _REVISION_KIND}:
        raise _error("revision_identity.kind", "must be root or revision")
    result["kind"] = kind

    embedded = result.get("supersedes")
    if supersedes is not None and embedded is not None and supersedes != embedded:
        raise _error("revision_identity.supersedes", "conflicts with top-level supersedes")
    parent = supersedes if supersedes is not None else embedded
    if parent is not None:
        if isinstance(parent, Mapping):
            parent = parent.get("id")
        result["supersedes"] = _nonempty_text(parent, "revision_identity.supersedes")
        if kind == _ROOT_KIND:
            raise _error("revision_identity.kind", "root revision cannot supersede another revision")
    elif kind == _ROOT_KIND:
        result.pop("supersedes", None)
    elif kind == _REVISION_KIND:
        raise _error("revision_identity.supersedes", "revision kind requires a predecessor")
    return result


def _status(value: Any, field: str) -> str:
    if value is None:
        raise _error(field, "status is required")
    normalized = _nonempty_text(value, f"{field}.status").casefold()
    if normalized == "available":
        normalized = "known"
    if normalized not in {"known", "unknown", "unavailable", "not_applicable"}:
        raise _error(field, "status must be known, unknown, unavailable, or not_applicable")
    return normalized


def _precision(value: Any, field: str, *, default: str) -> str:
    if value is None:
        del default
        raise _error(field, "precision is required")
    normalized = _nonempty_text(value, f"{field}.precision").casefold()
    aliases = {
        "datetime": "instant",
        "timestamp": "instant",
        "day": "date",
        "unknown": "none",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _KNOWN_PRECISIONS:
        raise _error(field, f"precision must be one of {sorted(_KNOWN_PRECISIONS)}")
    return normalized


def _raw_time_value(obj: Mapping[str, Any]) -> Any:
    return _alias_value(obj, ("value", "at", "utc", "date"), "time_value", None)


def _value_signature(value: Any) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return "date:" + value.isoformat()
    if isinstance(value, str) and _DATE_RE.fullmatch(value.strip()):
        try:
            return "date:" + normalize_date(value)
        except TimeEvidenceError:
            pass
    if isinstance(value, (datetime, str)):
        try:
            return "instant:" + normalize_timestamp(value)
        except TimeEvidenceError:
            pass
    return "raw:" + canonical_json(value)


def _metadata(
    obj: Mapping[str, Any],
    role: str,
    top_source: Any,
    *,
    status: str,
) -> tuple[Any, Any, Any]:
    del top_source
    if "source" not in obj and "source_id" not in obj:
        raise _error(role, "source provenance is required")
    if "evidence" not in obj and "source_evidence" not in obj:
        raise _error(role, "evidence provenance is required")
    if "ref" not in obj and "reference" not in obj and "source_ref_url" not in obj:
        raise _error(role, "evidence ref is required")
    source = _alias_value(obj, ("source", "source_id"), f"{role}.source")
    evidence = _alias_value(obj, ("evidence", "source_evidence"), f"{role}.evidence")
    ref = _alias_value(obj, ("ref", "reference", "source_ref_url"), f"{role}.ref")
    if not _nonempty_provenance(source, f"{role}.source"):
        raise _error(role, "source provenance is required")
    if not _nonempty_provenance(evidence, f"{role}.evidence"):
        raise _error(role, "evidence provenance is required")
    if status == "known" and (ref is None or not _nonempty_provenance(ref, f"{role}.ref")):
        raise _error(role, "known value requires a non-empty evidence ref")
    return (
        _json_ready(source, f"{role}.source"),
        _json_ready(evidence, f"{role}.evidence"),
        _json_ready(ref, f"{role}.ref"),
    )


def _nonempty_provenance(value: Any, field: str) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        if not value.strip():
            raise _error(field, "must not be empty")
        return True
    if not isinstance(value, (str, Mapping)):
        raise _error(field, "must be a non-empty string or mapping")
    if isinstance(value, Mapping) and not value:
        raise _error(field, "must not be an empty mapping")
    _json_ready(value, field)
    return True


def _time_field(role: str, value: Any, *, top_source: Any, date_role: bool = False) -> dict[str, Any]:
    field = role
    if not isinstance(value, Mapping):
        raise _error(field, "must be an object with explicit status, precision, and provenance")
    obj = dict(value)
    if "role" in obj and obj["role"] != role:
        raise _error(role, f"role field conflicts with canonical role {role}")
    if "status" not in obj:
        raise _error(field, "status is required")
    if "precision" not in obj:
        raise _error(field, "precision is required")
    status = _status(obj.get("status"), field)
    raw = _raw_time_value(obj)
    explicit_precision = obj.get("precision")

    if status in {"unknown", "unavailable", "not_applicable"}:
        reason = _alias_value(obj, ("reason", "unknown_reason"), f"{field}.reason", None)
        if reason is None or not isinstance(reason, str) or not reason.strip():
            raise _error(field, "unknown/unavailable status requires reason")
        if raw is not None:
            raise _error(field, "unknown/unavailable value must be null or omitted")
        precision = _precision(explicit_precision, field, default="none")
        if precision != "none":
            raise _error(field, "unknown/unavailable/not_applicable value must use precision='none'")
        source, evidence, ref = _metadata(obj, role, top_source, status=status)
        return {
            "role": role,
            "status": status,
            "precision": "none",
            "value": None,
            "source": source,
            "evidence": evidence,
            "ref": ref,
            "reason": reason.strip(),
        }

    if raw is None:
        raise _error(field, "known value is required")

    is_date = isinstance(raw, date) and not isinstance(raw, datetime)
    if isinstance(raw, str) and _DATE_RE.fullmatch(raw.strip()):
        is_date = True
    default_precision = "date" if is_date or date_role else "instant"
    precision = _precision(explicit_precision, field, default=default_precision)
    source, evidence, ref = _metadata(obj, role, top_source, status=status)
    if is_date or date_role:
        if precision != "date":
            raise _error(field, "date-only value must use precision='date'; midnight is not inferred")
        normalized = normalize_date(raw, field)
        return {
            "role": role,
            "status": "known",
            "precision": "date",
            "value": normalized,
            "date": normalized,
            "source": source,
            "evidence": evidence,
            "ref": ref,
        }

    if precision == "date":
        raise _error(field, "aware timestamp is required for precision other than 'date'")
    if precision == "none":
        raise _error(field, "known value cannot use precision='none'")
    normalized = normalize_timestamp(raw, field)
    return {
        "role": role,
        "status": "known",
        "precision": precision,
        "value": normalized,
        "utc": normalized,
        "source": source,
        "evidence": evidence,
        "ref": ref,
    }


def _collect_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for container_name in ("timestamps", "time_fields"):
        container = data.get(container_name)
        if container is None:
            continue
        if not isinstance(container, Mapping):
            raise _error(container_name, "must be a mapping")
        for role, value in container.items():
            if role not in ALL_TIME_FIELDS:
                raise _error(f"{container_name}.{role}", "unknown time role")
            if role in fields:
                raise _error(role, "provided more than once")
            fields[role] = value
    for role in ALL_TIME_FIELDS:
        if role in data:
            if role in fields:
                raise _error(role, "provided both directly and in timestamps")
            fields[role] = data[role]
    return fields


def _canonical_identity(data: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    subject_value = _coalesced(data, "subject_identity", "subject", "subject_identity")
    subject = _identity(subject_value, "subject_identity")
    source_value = _coalesced(data, "source_identity", "source", "source_identity")
    source = _identity(source_value, "source_identity")
    snapshot_value = _coalesced(data, "snapshot_identity", "snapshot", "snapshot_identity")
    if snapshot_value is None and "snapshot_id" in data:
        snapshot_value = {"id": data["snapshot_id"]}
    elif snapshot_value is not None and "snapshot_id" in data:
        snapshot_identity = _identity(snapshot_value, "snapshot_identity")
        if snapshot_identity.get("id") != data["snapshot_id"]:
            raise _error("snapshot_id", "conflicts with snapshot_identity.id")
    snapshot = _identity(snapshot_value, "snapshot_identity")
    supersedes = data.get("supersedes")
    revision_value = _coalesced(data, "revision_identity", "revision", "revision_identity")
    if revision_value is None and "revision_id" not in data:
        raise _error("revision_identity", "is required; do not infer a root revision")
    if revision_value is None:
        revision_value = {"id": data["revision_id"]}
    elif "revision_id" in data:
        revision_probe = _identity(revision_value, "revision_identity")
        if revision_probe.get("id") != data["revision_id"]:
            raise _error("revision_id", "conflicts with revision_identity.id")
    revision = _revision_identity(
        revision_value,
        supersedes,
    )
    return subject, source, snapshot, revision


def _coalesced(data: Mapping[str, Any], primary: str, alias: str, field: str) -> Any:
    has_primary = primary in data
    has_alias = alias in data
    if has_primary and has_alias:
        left = canonical_json(data[primary])
        right = canonical_json(data[alias])
        if left != right:
            raise _error(field, f"{primary} and {alias} conflict")
        return data[primary]
    if has_primary:
        return data[primary]
    if has_alias:
        return data[alias]
    return None


def _known_datetime(field: Mapping[str, Any]) -> datetime | None:
    if field.get("status") != "known" or field.get("precision") not in {"instant", "second", "minute", "hour"}:
        return None
    value = field.get("utc")
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value)


def _validate_order(fields: Mapping[str, Mapping[str, Any]]) -> None:
    decision = _known_datetime(fields.get("decision_at", {}))
    generated = _known_datetime(fields.get("generated_at", {}))
    earliest = _known_datetime(fields.get("earliest_execution_at", {}))
    if decision is not None and generated is not None and generated < decision:
        raise _error("generated_at", "must not be earlier than decision_at")
    if decision is not None and earliest is not None and earliest < decision:
        raise _error("earliest_execution_at", "must not be earlier than decision_at")
    # This is only a comparable-time sanity check.  It is deliberately not a
    # point-in-time gate: date-only and unknown availability remain unknown.
    for role in ("first_available_at", "collected_at", "revision_available_at"):
        available = _known_datetime(fields.get(role, {}))
        if earliest is not None and available is not None and earliest < available:
            raise _error("earliest_execution_at", f"must not be earlier than {role}")


def _validate_revision_timing(
    revision: Mapping[str, Any],
    fields: Mapping[str, Mapping[str, Any]],
) -> None:
    """Make root/revision timing policy explicit without becoming a PIT gate."""

    for role, value in fields.items():
        if value.get("status") == "not_applicable" and role != "revision_available_at":
            raise _error(role, "not_applicable is reserved for root revision_available_at")
    revision_time = fields["revision_available_at"]
    if revision.get("kind") == _ROOT_KIND:
        if revision_time.get("status") != "not_applicable":
            raise _error(
                "revision_available_at",
                "root revision must be not_applicable with an explicit reason",
            )
    elif revision_time.get("status") == "not_applicable":
        raise _error(
            "revision_available_at",
            "not_applicable revision timing is reserved for root rows",
        )


@dataclass(frozen=True)
class TimeEvidence:
    """Immutable-in-practice normalized time evidence value object.

    ``to_dict`` always returns a detached copy, so normalizing an input cannot
    mutate a legacy or caller-owned mapping.
    """

    subject_identity: dict[str, Any]
    source_identity: dict[str, Any]
    snapshot_identity: dict[str, Any]
    revision_identity: dict[str, Any]
    fields: dict[str, dict[str, Any]]
    version: str = TIME_EVIDENCE_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TimeEvidence":
        if not isinstance(value, Mapping):
            raise TimeEvidenceContractError("time evidence must be a mapping")
        data = copy.deepcopy(dict(value))
        if "version" not in data:
            raise _error("version", "is required")
        version = data["version"]
        if version != TIME_EVIDENCE_VERSION:
            raise _error("version", f"must be {TIME_EVIDENCE_VERSION}")
        subject, source, snapshot, revision = _canonical_identity(data)
        fields = _collect_fields(data)
        missing = [role for role in TIMESTAMP_FIELDS if role not in fields]
        if missing:
            raise _error("timestamps", f"missing required roles: {', '.join(missing)}")
        if not any(role in fields for role in ANCHOR_FIELDS):
            raise _error("time_anchor", "provide market_date, event_date, instant, or event_at")
        normalized = {
            role: _time_field(
                role,
                raw,
                top_source=source,
                date_role=role in {"market_date", "event_date"},
            )
            for role, raw in fields.items()
        }
        _validate_order(normalized)
        _validate_revision_timing(revision, normalized)
        return cls(
            subject_identity=subject,
            source_identity=source,
            snapshot_identity=snapshot,
            revision_identity=revision,
            fields=normalized,
        )

    @property
    def revision_id(self) -> str:
        return self.revision_identity["id"]

    @property
    def supersedes(self) -> str | None:
        value = self.revision_identity.get("supersedes")
        return None if value is None else str(value)

    @property
    def is_revision(self) -> bool:
        return self.revision_identity.get("kind") == _REVISION_KIND or self.supersedes is not None

    @property
    def timestamps(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self.fields)

    @property
    def date_fields(self) -> dict[str, dict[str, Any]]:
        return {role: copy.deepcopy(self.fields[role]) for role in ("market_date", "event_date") if role in self.fields}

    def field(self, role: str) -> dict[str, Any] | None:
        return None if role not in self.fields else copy.deepcopy(self.fields[role])

    def canonical_identity(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "subject_identity": copy.deepcopy(self.subject_identity),
            "source_identity": copy.deepcopy(self.source_identity),
            "snapshot_identity": copy.deepcopy(self.snapshot_identity),
            "revision_identity": copy.deepcopy(self.revision_identity),
        }

    def canonical_identity_hash(self) -> str:
        return sha256_json(self.canonical_identity())

    def stable_identity(self) -> dict[str, Any]:
        """Identity used for retry/collision detection.

        Snapshot identity is retained in the canonical identity, but a
        revision id remains the stable row identity.  A changed snapshot with
        the same revision id therefore collides and cannot silently create a
        second version.
        """

        return {
            "version": self.version,
            "subject_identity": copy.deepcopy(self.subject_identity),
            "source_identity": copy.deepcopy(self.source_identity),
            "revision_id": self.revision_id,
        }

    def stable_identity_hash(self) -> str:
        return sha256_json(self.stable_identity())

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "version": self.version,
            "subject_identity": copy.deepcopy(self.subject_identity),
            "source_identity": copy.deepcopy(self.source_identity),
            "snapshot_identity": copy.deepcopy(self.snapshot_identity),
            "revision_identity": copy.deepcopy(self.revision_identity),
            "revision_id": self.revision_id,
            "supersedes": self.supersedes,
            "caller_provided_only": True,
            "availability_truth": "not_asserted",
        }
        for role in ALL_TIME_FIELDS:
            if role in self.fields:
                result[role] = copy.deepcopy(self.fields[role])
        return result

    def canonical_payload(self) -> str:
        return canonical_json(self.to_dict())

    def legacy_safe(self) -> dict[str, Any]:
        return legacy_safe(self.to_dict())


def _legacy_unknown(role: str, reason: str) -> dict[str, Any]:
    return {
        "role": role,
        "status": "unknown",
        "precision": "none",
        "value": None,
        "source": "legacy-compatibility",
        "evidence": "not-persisted",
        "ref": None,
        "reason": reason,
    }


def legacy_safe(value: Mapping[str, Any]) -> dict[str, Any]:
    """Project legacy time fields without claiming historical availability.

    This helper is deliberately not a strict constructor.  It preserves the
    original input under ``legacy`` and only promotes an explicit calendar
    date to a date-valued market field.  In particular, ``data_cutoff`` and
    ``created_at`` are never parsed as historical ``published_at``,
    ``first_available_at``, ``decision_at``, or ``generated_at``.
    """

    if not isinstance(value, Mapping):
        raise TimeEvidenceContractError("legacy time evidence must be a mapping")
    original = _legacy_json_ready(dict(value))
    result: dict[str, Any] = {
        "version": TIME_EVIDENCE_VERSION,
        "caller_provided_only": True,
        "availability_truth": "not_asserted",
        "legacy": original,
    }
    signal_date = original.get("market_date", original.get("signal_date"))
    if signal_date is not None:
        try:
            normalized = normalize_date(signal_date, "legacy.signal_date")
        except TimeEvidenceError:
            result["market_date"] = _legacy_unknown("market_date", "legacy_market_date_invalid")
        else:
            result["market_date"] = {
                "role": "market_date",
                "status": "known",
                "precision": "date",
                "value": normalized,
                "date": normalized,
                "source": "legacy-compatibility",
                "evidence": "legacy.signal_date",
                "ref": "signal_date",
            }
    else:
        result["market_date"] = _legacy_unknown("market_date", "legacy_market_date_not_persisted")

    for role in TIMESTAMP_FIELDS:
        result[role] = _legacy_unknown(role, f"legacy_{role}_not_persisted")
    if "earliest_execution_date" in original:
        result["earliest_execution_at"]["reason"] = "legacy_earliest_execution_date_is_date_only"
    result["legacy_semantics"] = {
        "data_cutoff_preserved": "data_cutoff" in original,
        "availability_asserted": False,
        "historical_decision_time_asserted": False,
    }
    return result


def _legacy_json_ready(value: Any) -> Any:
    """Detach legacy values while preserving naive datetime text verbatim."""

    if isinstance(value, datetime):
        # Deliberately do not call _normalize_datetime: the absence of an
        # offset is part of the legacy limitation and must remain visible.
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _legacy_json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_legacy_json_ready(item) for item in value]
    return copy.deepcopy(value)


# Named aliases make the compatibility boundary easy for callers to discover
# without coupling them to a class method.
legacy_safe_time_evidence = legacy_safe
safe_legacy_time_evidence = legacy_safe


__all__ = [
    "ALL_TIME_FIELDS",
    "ANCHOR_FIELDS",
    "TIMESTAMP_FIELDS",
    "TIME_EVIDENCE_VERSION",
    "TimeEvidence",
    "TimeEvidenceContractError",
    "TimeEvidenceError",
    "canonical_json",
    "legacy_safe",
    "legacy_safe_time_evidence",
    "normalize_date",
    "normalize_identity",
    "normalize_timestamp",
    "safe_legacy_time_evidence",
    "sha256_json",
]
