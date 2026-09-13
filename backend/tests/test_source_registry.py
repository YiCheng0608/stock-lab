from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import worker.source_registry as registry


PROFILE = "fixture_public"


def _known(value, reason: str) -> dict[str, object]:
    return {"status": "known", "value": value, "reason": reason}


def _unknown(reason: str) -> dict[str, str]:
    return {"status": "unknown", "reason": reason}


def _fixture_manifest() -> dict[str, object]:
    source_id = "fixture_admitted"
    source = {
        "schema_version": registry.SCHEMA_VERSION,
        "registry_version": "fixture-registry-v1",
        "source_id": source_id,
        "dataset_id": "fixture-dataset",
        "source_version": "fixture-source-v1",
        "owner": {"name": "Synthetic Fixture", "type": "test_only"},
        "source_type": "synthetic_fixture",
        "exact_url": "https://fixture.example/data",
        "method": "GET",
        "evidence": [
            {
                "url": "https://fixture.example/docs",
                "checked_at": "2026-09-12",
                "claim": "Synthetic evidence used only by this test.",
            }
        ],
        "access": {
            "free_public": _known(True, "Synthetic fixture is free."),
            "auth": _known(False, "Synthetic fixture has no auth."),
            "documented_terms": _known("fixture-only", "Synthetic fixture terms."),
            "rate_limit": _unknown("Not relevant to a local fixture."),
            "latency": _unknown("Not relevant to a local fixture."),
        },
        "temporal": {
            "update_cadence": _known("fixed", "Synthetic fixture is fixed."),
            "publication": _unknown("Not a real source."),
            "first_availability": _unknown("Not a real source."),
            "historical_coverage": _unknown("Not a real source."),
            "revision_policy": _unknown("Not a real source."),
        },
        "retention": {
            "raw_store": _known(True, "Synthetic fixture may be retained in tests."),
            "summarize": _known(True, "Synthetic fixture may be summarized in tests."),
        },
        "enabled": {"status": "known", "value": True, "reason": "Fixture is active for this test."},
        "deprecation": {"status": "unknown", "reason": "Fixture has no external deprecation policy."},
        "versioning": _unknown("Synthetic fixture has no external versioning."),
        "purposes": {
            "local_fetch": {
                "status": "admitted",
                "reason": "Synthetic positive policy case.",
                "evidence": [
                    {
                        "url": "https://fixture.example/docs",
                        "checked_at": "2026-09-12",
                        "claim": "Synthetic local-fetch authorization.",
                    }
                ],
                "required_evidence": ["access.free_public", "access.auth", "access.documented_terms"],
                "conditions": ["fixture_only", "bounded_requests", "respect_endpoint_limits"],
            },
            "raw_store": {
                "status": "unknown",
                "reason": "Synthetic fixture intentionally has no raw-store authorization.",
                "evidence": [],
                "required_evidence": ["retention.raw_store"],
                "conditions": ["fixture_only", "attribute_source", "preserve_source_integrity"],
            },
            "summarize": {
                "status": "denied",
                "reason": "Synthetic fixture intentionally denies summaries.",
                "evidence": [],
                "required_evidence": ["retention.summarize"],
                "conditions": ["fixture_only", "attribute_source", "preserve_source_integrity", "retain_traceability"],
            },
            "historical_pit": {
                "status": "unknown",
                "unknown_decision": "unsupported",
                "reason": "Synthetic fixture has no PIT evidence.",
                "evidence": [],
                "required_evidence": ["temporal.first_availability", "temporal.historical_coverage", "temporal.revision_policy"],
                "conditions": ["fixture_only", "no_pit_claim", "reconstructable_snapshot", "revision_history", "first_availability"],
            },
        },
    }
    manifest: dict[str, object] = {
        "schema_version": registry.SCHEMA_VERSION,
        "policy_version": registry.POLICY_VERSION,
        "registry_version": "fixture-registry-v1",
        "profiles": {
            PROFILE: {
                "version": "1",
                "policy_version": registry.POLICY_VERSION,
                "source_versions": {source_id: "fixture-source-v1"},
            }
        },
        "sources": [source],
    }
    manifest["content_digest"] = registry.manifest_digest(manifest)
    return manifest


def test_real_manifest_is_valid_and_keeps_four_exact_sources_separate_from_legacy():
    manifest = registry.load_manifest()
    assert registry.validate_manifest(manifest) == []
    assert registry.validation_report(manifest)["verification"] == "unverified"
    assert {source["source_id"] for source in manifest["sources"]} == {
        "twse_stock_day_all",
        "twse_holiday_schedule",
        "twse_twt48u_all",
        "tpex_spendi_history",
    }
    methods = {source["source_id"]: source["method"] for source in manifest["sources"]}
    assert methods == {
        "twse_stock_day_all": "GET",
        "twse_holiday_schedule": "GET",
        "twse_twt48u_all": "GET",
        "tpex_spendi_history": "GET",
    }


def test_real_endpoint_urls_are_exact_and_purpose_decisions_do_not_inherit():
    manifest = registry.load_manifest()
    expected = {
        "twse_stock_day_all": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        "twse_holiday_schedule": "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
        "twse_twt48u_all": "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL",
        "tpex_spendi_history": "https://www.tpex.org.tw/openapi/v1/tpex_spendi_history",
    }
    assert {source["source_id"]: source["exact_url"] for source in manifest["sources"]} == expected
    for source_id in expected:
        local = registry.decide_policy(manifest, source_id, "local_fetch", profile="free_public_local")
        raw = registry.decide_policy(manifest, source_id, "raw_store", profile="free_public_local")
        summary = registry.decide_policy(manifest, source_id, "summarize", profile="free_public_local")
        pit = registry.decide_policy(manifest, source_id, "historical_pit", profile="free_public_local")
        assert local.decision == "allow"
        assert raw.decision == "allow"
        assert summary.decision == "allow"
        assert pit.decision == "unsupported"
        assert "unknown_fail_closed:unsupported" in pit.reasons
        assert local.conditions == ("bounded_requests", "respect_endpoint_limits")
        assert "attribute_source" in raw.conditions
        assert "retain_traceability" in summary.conditions


def test_synthetic_admitted_policy_is_positive_fixture_only_and_unknown_is_not_denied():
    manifest = _fixture_manifest()
    assert registry.validate_manifest(manifest) == []
    assert registry.decide_policy(manifest, "fixture_admitted", "local_fetch", profile=PROFILE).decision == "allow"
    assert registry.decide_policy(manifest, "fixture_admitted", "raw_store", profile=PROFILE).decision == "restricted"
    assert registry.decide_policy(manifest, "fixture_admitted", "summarize", profile=PROFILE).decision == "unsupported"
    assert registry.decide_policy(manifest, "fixture_admitted", "historical_pit", profile=PROFILE).decision == "unsupported"


def test_unknown_required_evidence_downgrades_an_admitted_policy():
    manifest = _fixture_manifest()
    source = manifest["sources"][0]
    source["purposes"]["local_fetch"]["required_evidence"] = [
        "access.free_public",
        "access.auth",
        "access.documented_terms",
        "access.rate_limit",
    ]
    source["purposes"]["local_fetch"]["status"] = "admitted"
    manifest["content_digest"] = registry.manifest_digest(manifest)
    decision = registry.decide_policy(manifest, "fixture_admitted", "local_fetch", profile=PROFILE)
    assert decision.decision == "restricted"
    assert "unknown_required_evidence:access.rate_limit" in decision.reasons


def test_endpoint_and_profile_version_mismatch_fail_closed():
    manifest = _fixture_manifest()
    endpoint = registry.decide_policy(
        manifest,
        "fixture_admitted",
        "local_fetch",
        profile=PROFILE,
        endpoint="https://fixture.example/other",
    )
    assert endpoint.decision == "unsupported"
    assert "endpoint_mismatch" in endpoint.reasons
    manifest["profiles"][PROFILE]["source_versions"]["fixture_admitted"] = "fixture-source-v2"
    manifest["content_digest"] = registry.manifest_digest(manifest)
    version = registry.decide_policy(manifest, "fixture_admitted", "local_fetch", profile=PROFILE)
    assert version.decision == "unsupported"
    assert "source_version_conflict" in version.reasons


def test_same_version_drift_requires_external_pin_and_snapshot_compare():
    original = _fixture_manifest()
    drifted = copy.deepcopy(original)
    drifted["sources"][0]["dataset_id"] = "fixture-dataset-drifted"
    drifted["content_digest"] = registry.manifest_digest(drifted)
    comparison = registry.compare_snapshots(original, drifted)
    assert comparison["same_registry_version"] is True
    assert comparison["same_version_content_changed"] is True
    assert registry.validate_manifest(
        drifted,
        expected_registry_version="fixture-registry-v1",
        expected_digest=registry.manifest_digest(original),
    )
    assert registry.validation_report(drifted)["verification"] == "unverified"


def test_stale_self_digest_is_detected():
    manifest = _fixture_manifest()
    manifest["sources"][0]["owner"]["name"] = "Changed"
    errors = registry.validate_manifest(manifest)
    assert "content_digest: does not match canonical manifest content" in errors


def test_malformed_null_and_missing_known_value_are_reported_without_crashing():
    cases = []
    malformed_null = _fixture_manifest()
    malformed_null["sources"][0]["owner"]["name"] = None
    cases.append(malformed_null)
    malformed_id = _fixture_manifest()
    malformed_id["sources"][0]["source_id"] = ["not", "hashable"]
    cases.append(malformed_id)
    missing_value = _fixture_manifest()
    missing_value["sources"][0]["access"]["free_public"] = {"status": "known", "reason": "missing value"}
    cases.append(missing_value)
    for manifest in cases:
        manifest["content_digest"] = registry.manifest_digest(manifest)
        errors = registry.validate_manifest(manifest)
        assert errors
        decision = registry.decide_policy(manifest, "fixture_admitted", "local_fetch", profile=PROFILE)
        assert decision.decision == "unsupported"
        assert "manifest_invalid" in decision.reasons


def test_field_specific_known_values_are_required_for_admitted_purposes():
    cases = [
        ("access", "free_public", False),
        ("access", "auth", True),
        ("retention", "raw_store", False),
        ("retention", "summarize", False),
    ]
    for section, field, value in cases:
        manifest = _fixture_manifest()
        manifest["sources"][0][section][field] = {"status": "known", "value": value, "reason": "wrong fixture value"}
        manifest["content_digest"] = registry.manifest_digest(manifest)
        errors = registry.validate_manifest(manifest)
        assert not errors, (section, field, errors)
        purpose = {
            ("access", "free_public"): "local_fetch",
            ("access", "auth"): "local_fetch",
            ("retention", "raw_store"): "raw_store",
            ("retention", "summarize"): "summarize",
        }[(section, field)]
        if purpose != "local_fetch":
            policy = manifest["sources"][0]["purposes"][purpose]
            policy["status"] = "admitted"
            policy["evidence"] = [
                {
                    "url": "https://fixture.example/docs",
                    "checked_at": "2026-09-12",
                    "claim": "Synthetic positive evidence for this semantic gate test.",
                }
            ]
            manifest["content_digest"] = registry.manifest_digest(manifest)
        decision = registry.decide_policy(manifest, "fixture_admitted", purpose, profile=PROFILE)
        assert decision.decision == "unsupported"
        assert any(reason.startswith("evidence_mismatch:") for reason in decision.reasons)

    disabled = _fixture_manifest()
    disabled["sources"][0]["enabled"] = {"status": "known", "value": False, "reason": "fixture disabled"}
    disabled["content_digest"] = registry.manifest_digest(disabled)
    assert registry.decide_policy(disabled, "fixture_admitted", "local_fetch", profile=PROFILE).decision == "unsupported"


def test_source_policy_minimum_evidence_and_conditions_cannot_be_removed():
    missing_evidence = _fixture_manifest()
    missing_evidence["sources"][0]["purposes"]["local_fetch"]["required_evidence"] = []
    missing_evidence["content_digest"] = registry.manifest_digest(missing_evidence)
    assert any("minimum evidence" in error for error in registry.validate_manifest(missing_evidence))
    assert registry.decide_policy(missing_evidence, "fixture_admitted", "local_fetch", profile=PROFILE).decision == "unsupported"

    missing_conditions = _fixture_manifest()
    raw_policy = missing_conditions["sources"][0]["purposes"]["raw_store"]
    raw_policy["status"] = "admitted"
    raw_policy["evidence"] = [
        {
            "url": "https://fixture.example/docs",
            "checked_at": "2026-09-12",
            "claim": "Synthetic raw-store evidence.",
        }
    ]
    raw_policy["conditions"] = []
    missing_conditions["content_digest"] = registry.manifest_digest(missing_conditions)
    assert any("minimum conditions" in error for error in registry.validate_manifest(missing_conditions))
    assert registry.decide_policy(missing_conditions, "fixture_admitted", "raw_store", profile=PROFILE).decision == "unsupported"


def test_known_null_wrong_type_and_malformed_status_are_rejected():
    mutations = []
    known_null = _fixture_manifest()
    known_null["sources"][0]["temporal"]["update_cadence"] = {"status": "known", "value": None, "reason": "bad"}
    mutations.append(known_null)
    wrong_bool = _fixture_manifest()
    wrong_bool["sources"][0]["access"]["free_public"] = {"status": "known", "value": "true", "reason": "bad"}
    mutations.append(wrong_bool)
    bad_status = _fixture_manifest()
    bad_status["sources"][0]["purposes"]["local_fetch"]["status"] = ["admitted"]
    mutations.append(bad_status)
    bad_profile = _fixture_manifest()
    bad_profile["profiles"][PROFILE]["version"] = None
    mutations.append(bad_profile)
    bad_url = _fixture_manifest()
    bad_url["sources"][0]["evidence"][0]["url"] = "https://[broken"
    mutations.append(bad_url)
    for manifest in mutations:
        manifest["content_digest"] = registry.manifest_digest(manifest)
        assert registry.validate_manifest(manifest)
        assert registry.decide_policy(manifest, "fixture_admitted", "local_fetch", profile=PROFILE).decision == "unsupported"


def test_version_only_pin_is_not_reported_as_content_pinned():
    manifest = registry.load_manifest()
    report = registry.validation_report(
        manifest,
        expected_registry_version=manifest["registry_version"],
    )
    assert report["valid"] is True
    assert report["verification"] == "version_only_unverified"


def test_import_has_no_app_or_http_side_effects(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import worker.source_registry; print('app.config' in sys.modules)"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_readonly_cli_requires_explicit_profile_and_reports_unverified_without_external_pin():
    backend = Path(__file__).parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "worker.source_registry",
            "inspect",
            "--manifest",
            str(backend / "worker" / "source_registry.json"),
            "--profile",
            "free_public_local",
            "--purpose",
            "historical_pit",
        ],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["manifest"]["verification"] == "unverified"
    assert all(item["decision"] == "unsupported" for item in output["decisions"])


def test_validate_cli_external_pin_is_required_for_pinned_claim():
    backend = Path(__file__).parents[1]
    manifest = registry.load_manifest()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "worker.source_registry",
            "validate",
            "--manifest",
            str(backend / "worker" / "source_registry.json"),
            "--expected-registry-version",
            manifest["registry_version"],
            "--expected-digest",
            registry.manifest_digest(manifest),
        ],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["valid"] is True
    assert output["verification"] == "pinned"


def test_cli_requires_an_explicit_manifest_path():
    backend = Path(__file__).parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend)
    result = subprocess.run(
        [sys.executable, "-m", "worker.source_registry", "validate"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
