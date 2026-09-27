"""Pure cutoff check for caller-declared time-evidence/v1 inputs.

This checks only the supplied records and their declared times. The caller
alone declares which inputs are required; this module cannot verify that list
against the actual dependency set. It does not establish source truth,
point-in-time validity, or permission to trade.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .time_evidence import (
    TIME_EVIDENCE_VERSION,
    TimeEvidence,
    TimeEvidenceContractError,
    canonical_json,
    normalize_identity,
    normalize_timestamp,
)

AVAILABILITY_GATE_VERSION = "caller-availability-cutoff/v1"
_TYPES = frozenset({"live", "historical", "backfill"})
_IDENTITIES = (
    "subject_identity",
    "source_identity",
    "snapshot_identity",
    "revision_identity",
)
_REQUEST_KEYS = frozenset({"version", "type", "decision_at", "required_inputs", "evidence"})
_REQUIRED_KEYS = frozenset({"input_id", *_IDENTITIES})
_EVIDENCE_KEYS = frozenset({"input_id", "time_evidence"})


def _reason(reasons: list[dict[str, str]], code: str, detail: str | None = None) -> None:
    entry = {"code": code}
    if detail is not None:
        entry["detail"] = detail
    if entry not in reasons:
        reasons.append(entry)


def _fields_reason(reasons: list[dict[str, str]], actual: set[Any], expected: frozenset[str], code: str) -> None:
    missing = sorted(expected - actual)
    extra = sorted(str(key) for key in actual - expected)
    if missing or extra:
        _reason(reasons, code, f"missing={missing}; extra={extra}")


def _input_id(value: Any) -> str | None:
    return value if type(value) is str and value and value == value.strip() else None


def _revision_identity(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        revision = normalize_identity(value, "revision_identity")
        revision["kind"] = "root"
        return revision
    if not isinstance(value, Mapping):
        raise ValueError("revision_identity must be a string or mapping")
    revision = normalize_identity(value, "revision_identity")
    if _input_id(revision.get("id")) is None:
        raise ValueError("revision_identity.id is required")
    kind = revision.get("kind", "revision" if revision.get("supersedes") is not None else "root")
    if not isinstance(kind, str) or kind.casefold() not in {"root", "revision"}:
        raise ValueError("revision_identity.kind must be root or revision")
    revision["kind"] = kind.casefold()
    parent = revision.get("supersedes")
    if isinstance(parent, Mapping):
        parent = parent.get("id")
    if kind.casefold() == "root":
        if parent is not None:
            raise ValueError("root revision cannot supersede another revision")
        revision.pop("supersedes", None)
    else:
        if not isinstance(parent, str) or not parent.strip():
            raise ValueError("revision requires supersedes")
        revision["supersedes"] = parent.strip()
    return revision


def _required_identity(value: Mapping[str, Any], reasons: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in _IDENTITIES:
        if name not in value:
            continue
        try:
            result[name] = (
                _revision_identity(value[name])
                if name == "revision_identity"
                else normalize_identity(value[name], name)
            )
        except TimeEvidenceContractError as exc:
            _reason(reasons, "invalid_required_identity", f"{name}: {exc}")
        except (OverflowError, ValueError) as exc:
            _reason(reasons, "invalid_required_identity", f"{name}: {exc}")
    return result


def _cutoff_role(
    record: TimeEvidence,
    raw: Mapping[str, Any],
    role: str,
    decision: datetime,
    reasons: list[dict[str, str]],
) -> None:
    field = record.field(role)
    raw_field = _raw_role(raw, role)
    if field is None or field["status"] != "known" or raw_field.get("status") != "known":
        _reason(reasons, f"{role}_not_known")
    elif field["precision"] != "instant" or raw_field.get("precision") != "instant":
        _reason(reasons, f"{role}_not_instant")
    elif datetime.fromisoformat(field["utc"]) > decision:
        _reason(reasons, f"{role}_late")


def _raw_role(raw: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    for container in (raw, raw.get("timestamps"), raw.get("time_fields")):
        if isinstance(container, Mapping) and role in container:
            field = container[role]
            return field if isinstance(field, Mapping) else {}
    return {}


def _check_record(
    raw: Any,
    expected: Mapping[str, dict[str, Any]],
    decision: datetime,
    run_type: str,
    reasons: list[dict[str, str]],
) -> None:
    if not isinstance(raw, Mapping):
        _reason(reasons, "invalid_time_evidence_type")
        return
    if raw.get("version") != TIME_EVIDENCE_VERSION:
        _reason(reasons, "unsupported_time_evidence_version")
        return
    if "type" in raw:
        _reason(reasons, "unsupported_time_evidence_type")
        return
    try:
        record = TimeEvidence.from_mapping(raw)
    except TimeEvidenceContractError as exc:
        _reason(reasons, "invalid_time_evidence", str(exc))
        return
    except (OverflowError, ValueError) as exc:
        _reason(reasons, "invalid_time_evidence_datetime", str(exc))
        return

    actual = record.canonical_identity()
    for name in _IDENTITIES:
        if name in expected and canonical_json(expected[name]) != canonical_json(actual[name]):
            _reason(reasons, "identity_mismatch", name)

    record_decision = record.field("decision_at")
    raw_decision = _raw_role(raw, "decision_at")
    if record_decision is None or record_decision["status"] != "known" or raw_decision.get("status") != "known":
        _reason(reasons, "decision_at_not_known")
    elif record_decision["precision"] != "instant" or raw_decision.get("precision") != "instant":
        _reason(reasons, "decision_at_not_instant")
    elif datetime.fromisoformat(record_decision["utc"]) != decision:
        _reason(reasons, "decision_at_mismatch")

    _cutoff_role(record, raw, "first_available_at", decision, reasons)
    if record.is_revision:
        _cutoff_role(record, raw, "revision_available_at", decision, reasons)
    if run_type == "live":
        _cutoff_role(record, raw, "collected_at", decision, reasons)


def evaluate_availability(request: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate an exact required-input set against exact caller evidence.

    ``required_inputs`` contains one ``input_id`` and four identities per row.
    ``evidence`` contains one ``input_id`` and one time-evidence/v1 mapping per
    row. The caller alone declares the required set; this function does not
    verify that the set contains every real dependency. No record is selected,
    fetched, inferred, or substituted.
    """

    request_reasons: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "version": AVAILABILITY_GATE_VERSION,
        "evaluation_scope": "caller_declared_time_cutoff",
        "required_inputs_completeness": "caller_declared_only",
        "availability_truth": "not_asserted",
        "point_in_time_status": "not_asserted",
        "type": None,
        "decision_at_utc": None,
        "cutoff_satisfied": False,
        "request_reasons": request_reasons,
        "items": rows,
        "unexpected_evidence": unexpected,
    }
    if not isinstance(request, Mapping):
        _reason(request_reasons, "invalid_request_type")
        return result
    _fields_reason(request_reasons, set(request), _REQUEST_KEYS, "request_fields_mismatch")
    if request.get("version") != AVAILABILITY_GATE_VERSION:
        _reason(request_reasons, "unsupported_gate_version")
    run_type = request.get("type")
    if not isinstance(run_type, str) or run_type not in _TYPES:
        _reason(request_reasons, "unsupported_run_type")
    else:
        result["type"] = run_type
    decision: datetime | None = None
    try:
        normalized_decision = normalize_timestamp(request.get("decision_at"), "decision_at")
        decision = datetime.fromisoformat(normalized_decision)
        result["decision_at_utc"] = normalized_decision
    except TimeEvidenceContractError as exc:
        _reason(request_reasons, "invalid_decision_at", str(exc))
    except (OverflowError, ValueError) as exc:
        _reason(request_reasons, "invalid_decision_at", str(exc))

    required = request.get("required_inputs")
    if not isinstance(required, list):
        _reason(request_reasons, "invalid_required_inputs_type")
        required = []
    elif not required:
        _reason(request_reasons, "empty_required_inputs")
    evidence = request.get("evidence")
    if not isinstance(evidence, list):
        _reason(request_reasons, "invalid_evidence_type")
        evidence = []

    specs: list[dict[str, Any]] = []
    for index, raw in enumerate(required):
        reasons: list[dict[str, str]] = []
        identifier = _input_id(raw.get("input_id")) if isinstance(raw, Mapping) else None
        item = {"index": index, "input_id": identifier, "cutoff_satisfied": False, "reasons": reasons}
        rows.append(item)
        if not isinstance(raw, Mapping):
            _reason(reasons, "invalid_required_input_type")
            specs.append({"item": item, "identity": {}})
            continue
        _fields_reason(reasons, set(raw), _REQUIRED_KEYS, "required_input_fields_mismatch")
        if identifier is None:
            _reason(reasons, "invalid_input_id")
        identity = _required_identity(raw, reasons)
        specs.append({"item": item, "identity": identity})

    id_counts = Counter(spec["item"]["input_id"] for spec in specs if spec["item"]["input_id"] is not None)
    identity_counts = Counter(
        tuple(canonical_json(spec["identity"][name]) for name in _IDENTITIES)
        for spec in specs
        if len(spec["identity"]) == len(_IDENTITIES)
    )
    for spec in specs:
        item = spec["item"]
        identifier = item["input_id"]
        if identifier is not None and id_counts[identifier] > 1:
            _reason(item["reasons"], "duplicate_required_input")
        if len(spec["identity"]) == len(_IDENTITIES):
            signature = tuple(canonical_json(spec["identity"][name]) for name in _IDENTITIES)
            if identity_counts[signature] > 1:
                _reason(item["reasons"], "duplicate_required_identity")

    by_id: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    required_ids = set(id_counts)
    for index, raw in enumerate(evidence):
        identifier = _input_id(raw.get("input_id")) if isinstance(raw, Mapping) else None
        if identifier is None:
            unexpected.append({
                "index": index,
                "input_id": None,
                "reasons": [{"code": "invalid_evidence_entry"}],
            })
        elif identifier not in required_ids:
            unexpected.append({
                "index": index,
                "input_id": identifier,
                "reasons": [{"code": "extra_evidence"}],
            })
        else:
            by_id[identifier].append((index, raw))

    for spec in specs:
        item = spec["item"]
        reasons = item["reasons"]
        identifier = item["input_id"]
        matches = by_id.get(identifier, []) if identifier is not None else []
        if identifier is not None and not matches:
            _reason(reasons, "missing_evidence")
        elif len(matches) > 1:
            _reason(reasons, "duplicate_evidence")
        elif matches:
            raw = matches[0][1]
            _fields_reason(reasons, set(raw), _EVIDENCE_KEYS, "evidence_entry_fields_mismatch")
            if not request_reasons and decision is not None and isinstance(run_type, str) and len(spec["identity"]) == len(_IDENTITIES) and not reasons:
                _check_record(raw["time_evidence"], spec["identity"], decision, run_type, reasons)
        if unexpected:
            _reason(reasons, "evidence_set_not_exact")
        if request_reasons:
            _reason(reasons, "request_invalid")
        item["cutoff_satisfied"] = not reasons

    result["cutoff_satisfied"] = bool(rows) and not request_reasons and not unexpected and all(
        item["cutoff_satisfied"] for item in rows
    )
    return result


__all__ = ["AVAILABILITY_GATE_VERSION", "evaluate_availability"]
