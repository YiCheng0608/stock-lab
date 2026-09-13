"""Versioned, read-only source policy registry.

This module is deliberately independent from the legacy collector.  It uses
only the standard library so importing it cannot create an application data
directory, open a database, or make an HTTP request.

The registry distinguishes two layers of state:

* source facts use ``admitted``, ``denied``, and ``unknown``;
* callers receive the fail-closed decisions ``allow``, ``restricted``, and
  ``unsupported``.

An ``unknown`` fact is not a prohibition, but it is never sufficient to
produce ``allow``.  The bundled manifest is a pinned snapshot, not a claim
that the official sources are permanently available, historically complete,
or licensed for every downstream use.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


REGISTRY_PATH = Path(__file__).with_name("source_registry.json")
SCHEMA_VERSION = "source-registry/v1"
POLICY_VERSION = "source-policy/v1"
PURPOSES = ("local_fetch", "raw_store", "summarize", "historical_pit")
FACT_STATUSES = ("admitted", "denied", "unknown")
DECISIONS = ("allow", "restricted", "unsupported")
EVIDENCE_STATUSES = ("known", "unknown", "explicitly_prohibited")
MIN_REQUIRED_EVIDENCE = {
    "local_fetch": frozenset(("access.free_public", "access.auth", "access.documented_terms")),
    "raw_store": frozenset(("retention.raw_store",)),
    "summarize": frozenset(("retention.summarize",)),
    "historical_pit": frozenset(("temporal.first_availability", "temporal.historical_coverage", "temporal.revision_policy")),
}
MIN_CONDITIONS = {
    "local_fetch": frozenset(("bounded_requests", "respect_endpoint_limits")),
    "raw_store": frozenset(("attribute_source", "preserve_source_integrity")),
    "summarize": frozenset(("attribute_source", "preserve_source_integrity", "retain_traceability")),
    "historical_pit": frozenset(("reconstructable_snapshot", "revision_history", "first_availability")),
}


class RegistryError(ValueError):
    """Raised when a registry cannot be safely loaded or evaluated."""


class ManifestValidationError(RegistryError):
    """Raised when a manifest fails structural or pin validation."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class PolicyDecision:
    """Machine-readable result for one source and one purpose."""

    source_id: str
    purpose: str
    profile: str | None
    decision: str
    reasons: tuple[str, ...]
    source_version: str | None = None
    conditions: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        result["conditions"] = list(self.conditions)
        result["allowed"] = self.allowed
        return result


def _canonical_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(manifest))
    # The digest describes the payload, not itself.  This also makes a
    # manifest with a stale self-declared digest detectable.
    payload.pop("content_digest", None)
    return payload


def canonical_snapshot(manifest: Mapping[str, Any]) -> str:
    """Return the deterministic JSON snapshot used for digesting."""

    return json.dumps(
        _canonical_payload(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Return a content digest independent of JSON whitespace/key order."""

    digest = hashlib.sha256(canonical_snapshot(manifest).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compare_snapshots(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare two snapshots, including same-version content drift."""

    left_version = left.get("registry_version")
    right_version = right.get("registry_version")
    left_digest = manifest_digest(left)
    right_digest = manifest_digest(right)
    same_version = left_version == right_version
    return {
        "same_registry_version": same_version,
        "same_content": left_digest == right_digest,
        "same_version_content_changed": same_version and left_digest != right_digest,
        "left_registry_version": left_version,
        "right_registry_version": right_version,
        "left_digest": left_digest,
        "right_digest": right_digest,
    }


def _is_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _status_object(
    value: Any,
    path: str,
    errors: list[str],
    *,
    statuses: Sequence[str] = EVIDENCE_STATUSES,
) -> None:
    if not isinstance(value, Mapping):
        errors.append(f"{path}: expected an object with status and reason")
        return
    status = value.get("status")
    if status not in statuses:
        errors.append(f"{path}.status: expected one of {tuple(statuses)!r}")
    if status == "known" and ("value" not in value or value.get("value") is None):
        errors.append(f"{path}: known requires value")
    if status == "unknown" and not _nonempty_text(value.get("reason")):
        errors.append(f"{path}: unknown requires a non-empty reason")
    if status == "explicitly_prohibited" and not _nonempty_text(value.get("reason")):
        errors.append(f"{path}: explicitly_prohibited requires a non-empty reason")


def _known_value_type(
    value: Mapping[str, Any],
    path: str,
    errors: list[str],
    expected: str,
) -> None:
    if value.get("status") != "known":
        return
    actual = value.get("value")
    if expected == "bool" and type(actual) is not bool:
        errors.append(f"{path}.value: expected boolean")
    elif expected == "text" and not _nonempty_text(actual):
        errors.append(f"{path}.value: expected non-empty text")


def _required_mapping(value: Any, path: str, errors: list[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{path}: expected an object")
        return None
    return value


def _validate_evidence_list(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: expected a list")
        return
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{item_path}: expected an object")
            continue
        if not _is_url(item.get("url")):
            errors.append(f"{item_path}.url: expected an http(s) URL")
        if not _nonempty_text(item.get("checked_at")):
            errors.append(f"{item_path}.checked_at: required")
        if not _nonempty_text(item.get("claim")):
            errors.append(f"{item_path}.claim: required")


def _validate_source(
    source: Any,
    index: int,
    errors: list[str],
    *,
    manifest: Mapping[str, Any],
) -> None:
    path = f"sources[{index}]"
    item = _required_mapping(source, path, errors)
    if item is None:
        return
    for field in (
        "schema_version",
        "registry_version",
        "source_id",
        "dataset_id",
        "source_version",
        "method",
    ):
        if not _nonempty_text(item.get(field)):
            errors.append(f"{path}.{field}: required")
    if not _is_url(item.get("exact_url")):
        errors.append(f"{path}.exact_url: expected an http(s) URL")
    if not isinstance(item.get("method"), str) or item["method"].upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        errors.append(f"{path}.method: unsupported HTTP method")
    if item.get("schema_version") != manifest.get("schema_version"):
        errors.append(f"{path}.schema_version: conflicts with manifest")
    if item.get("registry_version") != manifest.get("registry_version"):
        errors.append(f"{path}.registry_version: conflicts with manifest")
    owner = _required_mapping(item.get("owner"), f"{path}.owner", errors)
    if owner is not None:
        if not _nonempty_text(owner.get("name")):
            errors.append(f"{path}.owner.name: required")
        if not _nonempty_text(owner.get("type")):
            errors.append(f"{path}.owner.type: required")
    if not _nonempty_text(item.get("source_type")):
        errors.append(f"{path}.source_type: required")
    _validate_evidence_list(item.get("evidence"), f"{path}.evidence", errors)

    access = _required_mapping(item.get("access"), f"{path}.access", errors)
    if access is not None:
        for field in ("free_public", "auth", "documented_terms", "rate_limit", "latency"):
            _status_object(access.get(field), f"{path}.access.{field}", errors)
        if isinstance(access.get("free_public"), Mapping):
            _known_value_type(access["free_public"], f"{path}.access.free_public", errors, "bool")
        if isinstance(access.get("auth"), Mapping):
            _known_value_type(access["auth"], f"{path}.access.auth", errors, "bool")
        if isinstance(access.get("documented_terms"), Mapping):
            _known_value_type(access["documented_terms"], f"{path}.access.documented_terms", errors, "text")

    temporal = _required_mapping(item.get("temporal"), f"{path}.temporal", errors)
    if temporal is not None:
        for field in (
            "update_cadence",
            "publication",
            "first_availability",
            "historical_coverage",
            "revision_policy",
        ):
            _status_object(temporal.get(field), f"{path}.temporal.{field}", errors)

    retention = _required_mapping(item.get("retention"), f"{path}.retention", errors)
    if retention is not None:
        for field in ("raw_store", "summarize"):
            _status_object(retention.get(field), f"{path}.retention.{field}", errors)
            if isinstance(retention.get(field), Mapping):
                _known_value_type(retention[field], f"{path}.retention.{field}", errors, "bool")

    deprecation = _required_mapping(item.get("deprecation"), f"{path}.deprecation", errors)
    if deprecation is not None:
        _status_object(
            deprecation,
            f"{path}.deprecation",
            errors,
            statuses=("active", "disabled", "unknown"),
        )
        if deprecation.get("status") == "unknown" and not _nonempty_text(deprecation.get("reason")):
            errors.append(f"{path}.deprecation: unknown requires a non-empty reason")
    enabled = item.get("enabled")
    _status_object(enabled, f"{path}.enabled", errors)
    if isinstance(enabled, Mapping):
        _known_value_type(enabled, f"{path}.enabled", errors, "bool")
    versioning = item.get("versioning")
    _status_object(versioning, f"{path}.versioning", errors)

    purposes = _required_mapping(item.get("purposes"), f"{path}.purposes", errors)
    if purposes is not None:
        missing = set(PURPOSES) - set(purposes)
        for purpose in sorted(missing):
            errors.append(f"{path}.purposes.{purpose}: required")
        for purpose in PURPOSES:
            if purpose not in purposes:
                continue
            purpose_path = f"{path}.purposes.{purpose}"
            policy = _required_mapping(purposes[purpose], purpose_path, errors)
            if policy is None:
                continue
            status = policy.get("status")
            if not isinstance(status, str) or status not in FACT_STATUSES:
                errors.append(f"{purpose_path}.status: expected one of {FACT_STATUSES!r}")
            if isinstance(status, str) and status in {"unknown", "denied"} and not _nonempty_text(policy.get("reason")):
                errors.append(f"{purpose_path}: {status} requires a non-empty reason")
            evidence = policy.get("evidence", [])
            _validate_evidence_list(evidence, f"{purpose_path}.evidence", errors)
            if status == "admitted" and not evidence:
                errors.append(f"{purpose_path}: admitted requires evidence")
            required = policy.get("required_evidence", [])
            if not isinstance(required, list) or any(not isinstance(value, str) or not value for value in required):
                errors.append(f"{purpose_path}.required_evidence: expected a list of paths")
            elif not MIN_REQUIRED_EVIDENCE[purpose].issubset(required):
                errors.append(f"{purpose_path}.required_evidence: missing source-policy/v1 minimum evidence")
            conditions = policy.get("conditions")
            if not isinstance(conditions, list) or any(not isinstance(value, str) or not value for value in conditions):
                errors.append(f"{purpose_path}.conditions: expected a list of non-empty condition codes")
            elif not MIN_CONDITIONS[purpose].issubset(conditions):
                errors.append(f"{purpose_path}.conditions: missing source-policy/v1 minimum conditions")
            unknown_decision = policy.get("unknown_decision", "restricted")
            if not isinstance(unknown_decision, str) or unknown_decision not in {"restricted", "unsupported"}:
                errors.append(f"{purpose_path}.unknown_decision: expected restricted or unsupported")


def validation_report(
    manifest: Mapping[str, Any],
    *,
    expected_registry_version: str | None = None,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    """Return validation details without making network or application calls."""

    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        return {
            "valid": False,
            "errors": ["manifest: expected an object"],
            "verification": "failed",
        }
    for field, expected in (
        ("schema_version", SCHEMA_VERSION),
        ("policy_version", POLICY_VERSION),
        ("registry_version", None),
    ):
        value = manifest.get(field)
        if not str(value or "").strip():
            errors.append(f"{field}: required")
        elif expected is not None and value != expected:
            errors.append(f"{field}: expected {expected!r}")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources: expected a non-empty list")
        sources = []
    seen: set[str] = set()
    for index, source in enumerate(sources):
        _validate_source(source, index, errors, manifest=manifest)
        if isinstance(source, Mapping):
            source_id = source.get("source_id")
            if isinstance(source_id, str) and source_id in seen:
                errors.append(f"sources[{index}].source_id: duplicate {source_id!r}")
            if isinstance(source_id, str):
                seen.add(source_id)

    profiles = manifest.get("profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        errors.append("profiles: expected a non-empty object")
        profiles = {}
    for profile_name, profile in profiles.items():
        profile_path = f"profiles.{profile_name}"
        if not isinstance(profile, Mapping):
            errors.append(f"{profile_path}: expected an object")
            continue
        if not _nonempty_text(profile.get("version")):
            errors.append(f"{profile_path}.version: required")
        if profile.get("policy_version") != manifest.get("policy_version"):
            errors.append(f"{profile_path}.policy_version: conflicts with manifest")
        source_versions = profile.get("source_versions")
        if not isinstance(source_versions, Mapping):
            errors.append(f"{profile_path}.source_versions: expected an object")
        elif any(not isinstance(value, str) or not value for value in source_versions.values()):
            errors.append(f"{profile_path}.source_versions: values must be non-empty strings")

    declared_digest = manifest.get("content_digest")
    try:
        computed_digest = manifest_digest(manifest)
    except (TypeError, ValueError):
        computed_digest = None
        errors.append("manifest: content is not canonical JSON serializable")
    if not isinstance(declared_digest, str) or not declared_digest:
        errors.append("content_digest: required")
    elif computed_digest is not None and declared_digest != computed_digest:
        errors.append("content_digest: does not match canonical manifest content")

    if expected_registry_version is not None and manifest.get("registry_version") != expected_registry_version:
        errors.append("registry_version: does not match expected pin")
    if expected_digest is not None and computed_digest != expected_digest:
        errors.append("content_digest: does not match expected pin")

    if expected_registry_version is None and expected_digest is None:
        verification = "unverified"
    elif expected_registry_version is not None and expected_digest is None and not errors:
        verification = "version_only_unverified"
    elif errors:
        verification = "failed"
    elif expected_registry_version is not None and expected_digest is not None:
        verification = "pinned"
    else:
        verification = "digest_only_unverified"
    return {
        "valid": not errors,
        "errors": errors,
        "verification": verification,
        "registry_version": manifest.get("registry_version"),
        "computed_digest": computed_digest,
        "declared_digest": declared_digest,
        "source_count": len(sources),
    }


def validate_manifest(
    manifest_or_path: Mapping[str, Any] | str | Path,
    *,
    expected_registry_version: str | None = None,
    expected_digest: str | None = None,
) -> list[str]:
    """Return validation errors; an empty list means structurally valid.

    ``expected_registry_version`` and ``expected_digest`` are external pins.
    The manifest's own digest is useful for corruption detection, but it is
    not treated as historical proof unless an external pin is supplied.
    """

    manifest = _read_manifest(manifest_or_path) if isinstance(manifest_or_path, (str, Path)) else manifest_or_path
    return list(
        validation_report(
            manifest,
            expected_registry_version=expected_registry_version,
            expected_digest=expected_digest,
        )["errors"]
    )


def _read_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read manifest {manifest_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"manifest {manifest_path} must contain a JSON object")
    return value


def load_manifest(
    path: str | Path | None = None,
    *,
    expected_registry_version: str | None = None,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    """Load one explicitly selected manifest and fail closed on errors.

    With no path this reads the one bundled manifest at ``REGISTRY_PATH``;
    it never scans for or guesses a "latest" version.
    """

    manifest = _read_manifest(REGISTRY_PATH if path is None else path)
    errors = validate_manifest(
        manifest,
        expected_registry_version=expected_registry_version,
        expected_digest=expected_digest,
    )
    if errors:
        raise ManifestValidationError(errors)
    return manifest


def _get_path(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _decision_for_status(status: str) -> str:
    return {"admitted": "allow", "unknown": "restricted", "denied": "unsupported"}[status]


def decide_policy(
    manifest: Mapping[str, Any] | str | Path,
    source_id: str,
    purpose: str,
    *,
    profile: str,
    endpoint: str | None = None,
    method: str | None = None,
) -> PolicyDecision:
    """Evaluate one purpose without inheriting permission from another."""

    try:
        selected_manifest = (
            load_manifest(manifest)
            if isinstance(manifest, (str, Path))
            else manifest
        )
        manifest_errors = validate_manifest(selected_manifest)
    except RegistryError as exc:
        return PolicyDecision(
            source_id,
            purpose,
            profile,
            "unsupported",
            tuple(["manifest_invalid", *getattr(exc, "errors", (str(exc),))]),
        )
    if manifest_errors:
        return PolicyDecision(
            source_id,
            purpose,
            profile,
            "unsupported",
            tuple(["manifest_invalid", *manifest_errors]),
        )
    manifest = selected_manifest
    reasons: list[str] = []
    if not isinstance(purpose, str) or purpose not in PURPOSES:
        return PolicyDecision(source_id, purpose, profile, "unsupported", ("unknown_purpose",))
    profiles = manifest.get("profiles")
    profile_data = profiles.get(profile) if isinstance(profiles, Mapping) and isinstance(profile, str) else None
    if not isinstance(profile_data, Mapping):
        return PolicyDecision(source_id, purpose, profile, "unsupported", ("unknown_profile",))
    if profile_data.get("policy_version") != manifest.get("policy_version"):
        return PolicyDecision(source_id, purpose, profile, "unsupported", ("policy_version_conflict",))

    source = next(
        (item for item in manifest.get("sources", []) if isinstance(item, Mapping) and item.get("source_id") == source_id),
        None,
    )
    if source is None:
        return PolicyDecision(source_id, purpose, profile, "unsupported", ("unknown_source",))
    source_version = source.get("source_version")
    pinned_versions = profile_data.get("source_versions", {})
    if not isinstance(pinned_versions, Mapping) or pinned_versions.get(source_id) != source_version:
        reasons.append("source_version_conflict")
    if endpoint is not None and endpoint != source.get("exact_url"):
        reasons.append("endpoint_mismatch")
    if method is not None and str(method).upper() != str(source.get("method", "")).upper():
        reasons.append("method_mismatch")

    enabled = source.get("enabled", {})
    if isinstance(enabled, Mapping) and enabled.get("status") == "known":
        if enabled.get("value") is False:
            reasons.append("source_disabled")
    else:
        reasons.append("source_enabled_status_unknown")
    deprecation = source.get("deprecation", {})
    if isinstance(deprecation, Mapping) and deprecation.get("status") == "unknown":
        # A missing endpoint-specific retirement notice is a limitation, not
        # proof that a currently catalogued endpoint is disabled.
        reasons.append("deprecation_notice_policy_unknown")
    elif not isinstance(deprecation, Mapping):
        reasons.append("deprecation_notice_policy_unknown")

    purposes = source.get("purposes", {})
    purpose_policy = purposes.get(purpose) if isinstance(purposes, Mapping) else None
    if not isinstance(purpose_policy, Mapping):
        reasons.append("purpose_policy_missing")
        return PolicyDecision(source_id, purpose, profile, "unsupported", tuple(dict.fromkeys(reasons)))
    status = purpose_policy.get("status")
    if not isinstance(status, str) or status not in FACT_STATUSES:
        reasons.append("purpose_status_invalid")
        return PolicyDecision(source_id, purpose, profile, "unsupported", tuple(dict.fromkeys(reasons)))
    if purpose_policy.get("reason"):
        reasons.append(str(purpose_policy["reason"]))
    for reason in purpose_policy.get("reason_codes", []):
        if isinstance(reason, str) and reason:
            reasons.append(reason)

    decision = _decision_for_status(status)
    if status == "admitted":
        for required_path in purpose_policy.get("required_evidence", []):
            evidence = _get_path(source, required_path)
            if not isinstance(evidence, Mapping):
                reasons.append(f"unknown_required_evidence:{required_path}")
                continue
            evidence_status = evidence.get("status")
            if evidence_status == "unknown":
                reasons.append(f"unknown_required_evidence:{required_path}")
            elif evidence_status == "explicitly_prohibited":
                reasons.append(f"evidence_prohibits:{required_path}")
            elif evidence_status == "known":
                expected: Any = None
                if purpose == "local_fetch" and required_path == "access.free_public":
                    expected = True
                elif purpose == "local_fetch" and required_path == "access.auth":
                    expected = False
                elif purpose == "local_fetch" and required_path == "access.documented_terms":
                    expected = "nonempty_text"
                elif purpose == "raw_store" and required_path == "retention.raw_store":
                    expected = True
                elif purpose == "summarize" and required_path == "retention.summarize":
                    expected = True
                if expected is True or expected is False:
                    if type(evidence.get("value")) is not bool or evidence.get("value") is not expected:
                        reasons.append(f"evidence_mismatch:{required_path}")
                elif expected == "nonempty_text" and not _nonempty_text(evidence.get("value")):
                    reasons.append(f"evidence_mismatch:{required_path}")
            else:
                reasons.append(f"invalid_required_evidence:{required_path}")
        if any(reason.startswith("evidence_prohibits:") for reason in reasons):
            decision = "unsupported"
        elif any(reason.startswith("evidence_mismatch:") for reason in reasons):
            decision = "unsupported"
        elif any(reason.startswith("invalid_required_evidence:") for reason in reasons):
            decision = "unsupported"
        elif any(reason.startswith("unknown_required_evidence:") for reason in reasons):
            decision = "restricted"
    elif status == "unknown":
        decision = purpose_policy.get("unknown_decision", "restricted")
        reasons.append(f"unknown_fail_closed:{decision}")

    if any(
        reason in {"source_version_conflict", "endpoint_mismatch", "method_mismatch", "source_disabled", "source_enabled_status_unknown", "purpose_policy_missing", "policy_version_conflict"}
        for reason in reasons
    ):
        decision = "unsupported"
    return PolicyDecision(
        source_id,
        purpose,
        profile,
        decision,
        tuple(dict.fromkeys(reasons)),
        str(source_version) if source_version is not None else None,
        tuple(purpose_policy.get("conditions", [])),
    )


def decide(
    source_id: str,
    purpose: str,
    *,
    profile: str,
    manifest: Mapping[str, Any] | str | Path | None = None,
    endpoint: str | None = None,
    method: str | None = None,
) -> PolicyDecision:
    """Evaluate an explicitly supplied manifest; no latest version is guessed."""

    if manifest is None:
        return PolicyDecision(source_id, purpose, profile, "unsupported", ("manifest_required",))
    selected = manifest
    return decide_policy(
        selected,
        source_id,
        purpose,
        profile=profile,
        endpoint=endpoint,
        method=method,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or validate the read-only source registry.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "validate"):
        child = subparsers.add_parser(command)
        child.add_argument("--manifest", required=True, help="explicit manifest JSON path")
        child.add_argument("--profile", help="explicit policy profile")
        child.add_argument("--purpose", choices=PURPOSES, help="explicit source purpose")
        child.add_argument("--source", dest="source_id", help="source id for inspect")
        child.add_argument("--expected-registry-version")
        child.add_argument("--expected-digest")
    return parser


def _cli(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(
            args.manifest,
            expected_registry_version=args.expected_registry_version,
            expected_digest=args.expected_digest,
        )
    except RegistryError as exc:
        report = {"valid": False, "verification": "failed", "errors": list(getattr(exc, "errors", (str(exc),)))}
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 2

    report = validation_report(
        manifest,
        expected_registry_version=args.expected_registry_version,
        expected_digest=args.expected_digest,
    )
    if args.command == "validate":
        if (args.profile is None) != (args.purpose is None):
            report["valid"] = False
            report["errors"].append("profile and purpose must be selected together")
        elif args.profile and args.purpose:
            decisions = [
                decide_policy(manifest, source["source_id"], args.purpose, profile=args.profile).to_dict()
                for source in manifest["sources"]
            ]
            report["decisions"] = decisions
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["valid"] else 2

    if not args.profile or not args.purpose:
        print(
            json.dumps(
                {"valid": False, "errors": ["inspect requires --profile and --purpose"]},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    source_ids = [args.source_id] if args.source_id else [source["source_id"] for source in manifest["sources"]]
    decisions = [
        decide_policy(manifest, source_id, args.purpose, profile=args.profile).to_dict()
        for source_id in source_ids
    ]
    print(
        json.dumps(
            {"manifest": report, "profile": args.profile, "purpose": args.purpose, "decisions": decisions},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["valid"] else 2


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess CLI tests
    sys.exit(_cli())
