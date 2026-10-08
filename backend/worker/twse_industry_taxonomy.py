"""Two complete TWSE code/name citations; no download or capture producer.

The pinned declaration is ROOT-attested parsed-document evidence. Its hash is
not a raw PDF, HTTP entity or capture receipt hash. Import has no I/O.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REGISTRY_VERSION = "twse-industry-citation-r1-2026-10-08.1"
REGISTRY_DIGEST = "sha256:75b7667f65a9da7397a72a1e9c494a35364f7563faedc4df2cda21f12e61b647"
EXCERPT_DIGEST = "sha256:dfba7e99fdb9343d71b34361afc04c0198a3ab1ebc31ff8a175fee588aa0fac8"
PROFILE = "twse_two_code_complete_name_local_citation"
VERSION = "twse-issuer-industry-trace/m1-v1"
POLICY_DIGEST = "sha256:e9815a28d0ec22d29cd82c5524b02612debff4fec0110465002f6016afbae9b8"
MANIFEST = Path(__file__).with_name("twse_industry_registry.json")
MAX_REGISTRY_BYTES = 65536
INPUT_PINS = {
    "issuer_registry_version": "twse-issuer-r1-2026-10-08.1",
    "issuer_registry_digest": "sha256:7488da20a3bdf94aaa548c896d19077628bf93529208226d49b2a02896972f89",
    "issuer_source_version": "twse-t187ap03-l-d18419-2026-10-08",
    "issuer_profile_version": "twse-issuer-event-profile/m1-v1",
    "issuer_profile_digest": "sha256:02bf2422129c46490516557bccd188f7d550d2516c4b5e49e9acc2faf5338244",
    "event_registry_version": "r1-a1-c009-2026-09-12.1",
    "event_registry_digest": "sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b",
    "event_source_version": "twse-twt48u-all-d011-2026-09-12",
    "event_consumer_version": "official-events/p3b-v1",
}
_POLICY = {
    "version": VERSION, "profile": PROFILE, "registry_version": REGISTRY_VERSION,
    "registry_digest": REGISTRY_DIGEST, "canonical_root_attested_excerpt_sha256": EXCERPT_DIGEST,
    "symbols": ["1449", "1463", "2614"], "exchange": "TWSE", "accepted_code_raw": ["04", "20"],
    "normalization": "none", "issuer_contract": INPUT_PINS["issuer_profile_version"],
    "event_contract": INPUT_PINS["event_consumer_version"], "input_pins": INPUT_PINS,
    "join": "exact_code_and_event_name_equals_issuer_full_or_short",
    "cutoff": "observed_taipei_date_inclusive", "storage": "memory_only", "runtime_taxonomy_gets": 0,
    "ordinary_security": "not_validated", "ranking": "unsupported", "group_membership": "unsupported",
    "historical_pit": "unsupported", "company_classification_effective_date": "unknown",
}


class IndustryCitationError(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise IndustryCitationError(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def consumer_policy() -> dict:
    require(digest(_POLICY) == POLICY_DIGEST, "industry_consumer_declaration_mismatch")
    return json.loads(canonical(_POLICY))


def load_citations(*, expected_registry_version: str, expected_digest: str, manifest: str | Path = MANIFEST) -> dict:
    require(expected_registry_version == REGISTRY_VERSION and expected_digest == REGISTRY_DIGEST,
            "industry_external_registry_pins_mismatch")
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "industry_duplicate_registry_key")
            result[key] = value
        return result
    def invalid(_):
        raise IndustryCitationError("industry_nonfinite_registry")
    try:
        with Path(manifest).open("rb") as handle:
            raw = handle.read(MAX_REGISTRY_BYTES + 1)
        require(len(raw) <= MAX_REGISTRY_BYTES, "industry_registry_body_limit")
        registry = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        require(type(registry) is dict, "industry_registry_schema_invalid")
        claimed = registry.get("content_digest")
        payload = {key: value for key, value in registry.items() if key != "content_digest"}
        require(claimed == REGISTRY_DIGEST and digest(payload) == REGISTRY_DIGEST,
                "industry_registry_declaration_mismatch")
        require(registry["registry_version"] == REGISTRY_VERSION and registry["profile"] == PROFILE
                and registry["canonical_root_attested_excerpt_sha256"] == EXCERPT_DIGEST
                and digest(registry["declaration"]) == EXCERPT_DIGEST, "industry_excerpt_declaration_mismatch")
        return registry
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        if isinstance(exc, IndustryCitationError):
            raise
        raise IndustryCitationError("industry_citation_evidence_invalid") from exc


def quote_name(registry: dict, exchange: str, code_raw: str) -> str:
    require(exchange == "TWSE" and type(code_raw) is str and code_raw in ("04", "20"),
            "industry_raw_code_not_supported")
    require(digest(registry["declaration"]) == EXCERPT_DIGEST, "industry_excerpt_declaration_mismatch")
    return next(row["name_zh"] for row in registry["declaration"]["entries"] if row["code_raw"] == code_raw)
