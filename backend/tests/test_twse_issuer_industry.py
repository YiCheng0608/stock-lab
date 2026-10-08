"""Targeted RAM-only industry citation boundaries and ROOT launch entry.

Install the existing zero-disk audit guard before importing pytest or this
module. Fixtures are synthetic boundary evidence, never current source truth.
industry_memory_app preserves external pins and starts with two empty stores;
it does not preload, fetch, add HTTP diagnostics or launch any process.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import official_events as events
from app import twse_issuer_profile as issuer
from app import twse_issuer_industry as industry
from worker import twse_industry_taxonomy as taxonomy
from test_official_events import source as event_source
from test_twse_issuer_profile import (DAY, ENABLED as ISSUER_ENABLED, EVENT_ROWS,
                                    fixed_day, issuer_memory_app, issuer_rows, transport)

ENABLED = {**ISSUER_ENABLED, industry.CAPTURE_ENV: "1", industry.REGISTRY_VERSION_ENV: taxonomy.REGISTRY_VERSION,
           industry.REGISTRY_DIGEST_ENV: taxonomy.REGISTRY_DIGEST, industry.CONSUMER_VERSION_ENV: taxonomy.VERSION,
           industry.CONSUMER_DIGEST_ENV: taxonomy.POLICY_DIGEST}


@contextmanager
def industry_memory_app(*, issuer_store=None, event_store=None, environment=None):
    """Same held ORIGINAL pairs via app.state.issuer_originals(), with no exports.

environment=None preserves ROOT's externally supplied pins; it never enables
the consumer itself. The synthetic catalogue remains routing-only.
    """
    config = os.environ if environment is None else {**os.environ, **environment}
    required = ((industry.CAPTURE_ENV, "1"), (industry.REGISTRY_VERSION_ENV, taxonomy.REGISTRY_VERSION),
                (industry.REGISTRY_DIGEST_ENV, taxonomy.REGISTRY_DIGEST),
                (industry.CONSUMER_VERSION_ENV, taxonomy.VERSION), (industry.CONSUMER_DIGEST_ENV, taxonomy.POLICY_DIGEST))
    taxonomy.require(all(config.get(key) == expected for key, expected in required), "industry_external_policy_pins_mismatch")
    taxonomy.consumer_policy()
    taxonomy.load_citations(expected_registry_version=config[industry.REGISTRY_VERSION_ENV],
                            expected_digest=config[industry.REGISTRY_DIGEST_ENV])
    with issuer_memory_app(issuer_store=issuer_store, event_store=event_store, environment=environment) as app:
        original = app.state.issuer_originals()
        taxonomy.require(original["issuer_snapshot"] is None and original["event_snapshot"] is None
                         and not original["issuer_attempted"] and not original["event_attempted"]
                         and original["issuer_generation"] != original["event_generation"], "industry_new_empty_stores_required")
        yield app


def quoted_rows():
    rows = issuer_rows()
    rows[2]["產業別"] = "20"
    return rows


def captured(monkeypatch, *, rows=None, event_rows=None, status=200):
    event_body, event_calls = event_source(monkeypatch, EVENT_ROWS if event_rows is None else event_rows, captured_at="2026-10-07T22:00:01+00:00")
    event_store = events.OfficialEventMemory()
    event_value = events.capture_official_events("TWSE", "1449", DAY, environment=ENABLED, store=event_store)
    body, calls, adapter = transport(quoted_rows() if rows is None else rows, status=status)
    store = issuer.IssuerMemory(transport=adapter)
    profile = issuer.capture_issuer_profile("TWSE", "1449", DAY, events=event_value, environment=ENABLED, store=store)
    return store, event_store, profile, event_value, body, calls, event_body, event_calls


def project(profile, event_value, symbol="1449", cutoff=DAY, environment=ENABLED):
    return industry.build_issuer_industry("TWSE", symbol, cutoff, issuer_profile=profile, events=event_value, environment=environment)


def test_root_canonical_registry_and_policy_no_raw_metadata_receipts():
    registry = taxonomy.load_citations(expected_registry_version=taxonomy.REGISTRY_VERSION, expected_digest=taxonomy.REGISTRY_DIGEST)
    assert taxonomy.digest(registry["declaration"]) == taxonomy.EXCERPT_DIGEST
    assert taxonomy.digest(taxonomy.consumer_policy()) == taxonomy.POLICY_DIGEST
    assert registry["evidence_delivery"] == {"kind": "parsed_official_document", "attestation": "root_reviewed_bounded_citation",
                                             "original_body_sha256": None, "original_receipt_sha256": None}
    sources = registry["declaration"]["sources"]
    assert sources[0]["date_precision"] == "month" and sources[0]["implementation_month"] == "2020-03"
    assert sources[0]["locator"] == {"appendix": "3", "printed_page": 92, "zero_based_page": 100, "parsed_page_count": 104}
    assert sources[1]["patch_effective_date"] == "2023-07-03" and sources[2]["revision_date"] == "2025-06-09"
    assert registry["declaration"]["source_use"]["company_membership_effective_date"] == "unknown"


@pytest.mark.parametrize("code", ["4", " 04", "04 ", "00", "91", "80", "07", "99", "Other", "", None, 4])
def test_exact_raw_codes_and_special_fail_closed(code):
    registry = taxonomy.load_citations(expected_registry_version=taxonomy.REGISTRY_VERSION, expected_digest=taxonomy.REGISTRY_DIGEST)
    with pytest.raises(taxonomy.IndustryCitationError, match="industry_raw_code_not_supported"):
        taxonomy.quote_name(registry, "TWSE", code)
    with pytest.raises(taxonomy.IndustryCitationError):
        taxonomy.quote_name(registry, "TPEx", "20")


@pytest.mark.parametrize("change", ["name", "source_url", "month_precision", "patch_date", "rule_date", "raw_hash", "extra", "excerpt_hash"])
def test_registry_declaration_tampering_rejected_without_disk(change):
    registry = json.loads(taxonomy.MANIFEST.read_text(encoding="utf-8"))
    if change == "name": registry["declaration"]["entries"][0]["name_zh"] = "changed"
    elif change == "source_url": registry["declaration"]["sources"][0]["url"] = "https://invalid.example/"
    elif change == "month_precision": registry["declaration"]["sources"][0]["implementation_month"] = "2020-03-01"
    elif change == "patch_date": registry["declaration"]["sources"][1]["patch_effective_date"] = "2025-06-09"
    elif change == "rule_date": registry["declaration"]["sources"][2]["revision_date"] = "2023-07-03"
    elif change == "raw_hash": registry["evidence_delivery"]["original_body_sha256"] = "a" * 64
    elif change == "extra": registry["unadmitted"] = True
    else: registry["canonical_root_attested_excerpt_sha256"] = "sha256:" + "a" * 64
    with patch.object(Path, "open", lambda *args, **kwargs: io.BytesIO(taxonomy.canonical(registry))):
        with pytest.raises(taxonomy.IndustryCitationError):
            taxonomy.load_citations(expected_registry_version=taxonomy.REGISTRY_VERSION, expected_digest=taxonomy.REGISTRY_DIGEST)


def test_duplicate_registry_key_and_external_pins_rejected_before_read():
    raw = taxonomy.MANIFEST.read_bytes().replace(b'"schema_version":', b'"schema_version":"duplicate","schema_version":', 1)
    with patch.object(Path, "open", lambda *args, **kwargs: io.BytesIO(raw)):
        with pytest.raises(taxonomy.IndustryCitationError, match="industry_duplicate_registry_key"):
            taxonomy.load_citations(expected_registry_version=taxonomy.REGISTRY_VERSION, expected_digest=taxonomy.REGISTRY_DIGEST)
    with patch.object(Path, "open", side_effect=AssertionError("no file read before pins")):
        with pytest.raises(taxonomy.IndustryCitationError, match="industry_external_registry_pins_mismatch"):
            taxonomy.load_citations(expected_registry_version=taxonomy.REGISTRY_VERSION, expected_digest="bad")


def test_three_code_names_same_cutoff_originals_and_v1_immutable(monkeypatch):
    store, event_store, _, _, body, calls, event_body, event_calls = captured(monkeypatch)
    original_pair, original_events = store.snapshot, event_store.snapshot
    for symbol, code, name in (("1449", "04", "紡織纖維"), ("1463", "04", "紡織纖維"), ("2614", "20", "其他")):
        event_value = events.build_official_events("TWSE", symbol, DAY, environment=ENABLED, store=event_store)
        profile = issuer.build_issuer_profile("TWSE", symbol, DAY, events=event_value, environment=ENABLED, store=store)
        before = deepcopy(profile)
        result = project(profile, event_value, symbol)
        assert result["status"] == "available" and result["row"]["industry_code_raw"] == code and result["row"]["name_zh"] == name
        assert result["row"]["company_classification_effective_date"] == "unknown"
        assert result["provenance"]["issuer"] == profile["provenance"] and result["provenance"]["event"] == event_value["provenance"]
        assert profile == before and profile["classification"] == "unsupported"
    assert store.snapshot is original_pair and event_store.snapshot is original_events
    assert store.snapshot[0] == body and event_store.snapshot[0] == event_body
    assert len(calls) == len(event_calls) == 1


@pytest.mark.parametrize("mutation", ["issuer_hash", "event_hash", "issuer_pins", "event_pins", "event_name", "event_code", "event_date", "event_kind", "duplicate_ordinal", "raw_code", "ordinal", "metadata_cutoff"])
def test_mismatched_input_evidence_clears_name_trace(monkeypatch, mutation):
    _, _, profile, event_value, *_ = captured(monkeypatch)
    if mutation == "issuer_hash": profile["row"]["body_sha256"] = "a" * 64
    elif mutation == "event_hash": event_value["provenance"]["body_sha256"] = "invalid"
    elif mutation == "issuer_pins": profile["provenance"]["source_version"] = "changed"
    elif mutation == "event_pins": event_value["provenance"]["manifest_digest"] = "changed"
    elif mutation == "event_name": event_value["rows"][0]["company_name"] = "conflict"
    elif mutation == "event_code": event_value["rows"][0]["symbol"] = "2614"
    elif mutation == "event_date": event_value["rows"][0]["event_date"] = "2026-10-15"
    elif mutation == "event_kind": event_value["rows"][0]["kind"] = "ex_dividend"
    elif mutation == "duplicate_ordinal":
        event_value["rows"].append(deepcopy(event_value["rows"][0]))
        profile["row"]["event_names"].append(profile["row"]["event_names"][0])
    elif mutation == "raw_code": profile["row"]["industry_code_raw"] = "20"
    elif mutation == "ordinal": profile["row"]["row_ordinal"] = 0
    result = project(profile, event_value, cutoff=date(2026, 10, 7) if mutation == "metadata_cutoff" else DAY)
    assert result["status"] == "unavailable" and result["row"] is None and result["provenance"] is None


@pytest.mark.parametrize("bad_source", ["issuer_duplicate", "event_duplicate", "event_name_conflict"])
def test_original_feed_duplicate_or_conflict_never_promoted(monkeypatch, bad_source):
    rows, event_rows = quoted_rows(), deepcopy(EVENT_ROWS)
    if bad_source == "issuer_duplicate": rows.append(deepcopy(rows[0]))
    elif bad_source == "event_duplicate": event_rows.append(deepcopy(event_rows[0]))
    else: event_rows[0]["Name"] = "conflict"
    store, event_store, profile, event_value, _, calls, _, event_calls = captured(monkeypatch, rows=rows, event_rows=event_rows)
    result = project(profile, event_value)
    assert result["status"] == "unavailable" and result["row"] is None and result["provenance"] is None
    assert len(event_calls) == 1 and len(calls) <= 1


def test_missing_unsupported_disabled_and_pin_failure_no_fallback(monkeypatch):
    _, _, profile, event_value, *_ = captured(monkeypatch)
    for cutoff, symbol, environment in ((None, "1449", ENABLED), (DAY, "0056", ENABLED), (DAY, "1449", {}),
                                         (DAY, "1449", {**ENABLED, industry.CONSUMER_DIGEST_ENV: "bad"})):
        result = project(profile, event_value, symbol, cutoff, environment)
        assert result["status"] == "unavailable" and result["row"] is None and result["provenance"] is None
    result = project({**profile, "status": "unavailable", "row": None}, event_value)
    assert result["reasons"] == ["industry_issuer_unavailable"]


def test_first_failure_spent_and_cached_reads_no_additional_fetch(monkeypatch):
    store, event_store, profile, event_value, _, calls, _, event_calls = captured(monkeypatch, status=502)
    assert store.attempted and store.snapshot is None
    for _ in range(2):
        profile = issuer.capture_issuer_profile("TWSE", "1449", DAY, events=event_value, environment=ENABLED, store=store)
        result = project(profile, event_value)
        assert result["status"] == "unavailable" and result["row"] is None
    assert len(calls) == len(event_calls) == 1 and event_store.snapshot is not None


def test_new_empty_actual_router_and_additive_overview_no_preload(monkeypatch):
    event_body, event_calls = event_source(monkeypatch, EVENT_ROWS, captured_at="2026-10-07T22:00:01+00:00")
    body, calls, adapter = transport(quoted_rows())
    store = issuer.IssuerMemory(transport=adapter)
    with industry_memory_app(issuer_store=store, environment=ENABLED) as app:
        with TestClient(app) as client:
            initial = client.get("/api/stocks/TWSE/1449?as_of=2026-10-08").json()["overview"]
            assert initial["issuer_industry_trace"]["status"] == "unavailable" and len(calls) == len(event_calls) == 0
            assert client.post("/api/focus/official-events/capture?as_of=2026-10-08", json={}).status_code == 200
            assert client.post("/api/stocks/TWSE/1449/issuer-profile/capture?as_of=2026-10-08", json={}).json()["classification"] == "unsupported"
            for symbol in ("1449", "1463", "2614"):
                read = client.get(f"/api/stocks/TWSE/{symbol}?as_of=2026-10-08").json()["overview"]
                assert read["issuer_industry_trace"]["status"] == "available"
                assert read["issuer_profile"]["classification"] == "unsupported"
            assert client.post("/api/stocks/TWSE/1449/issuer-profile/capture?as_of=2026-10-08", json={}).json()["capture_action"] == "cached"
            for query in ("", "?as_of=2026-10-07"):
                read = client.get("/api/stocks/TWSE/1449" + query).json()["overview"]
                assert read["issuer_industry_trace"]["row"] is None
            assert client.get("/api/stocks/TWSE/0056?as_of=2026-10-08").json()["overview"]["issuer_industry_trace"]["row"] is None
            held = app.state.issuer_originals()
            assert held["issuer_snapshot"] is store.snapshot and held["event_snapshot"] is app.state.event_memory.snapshot
            assert held["issuer_snapshot"][0] == body and held["event_snapshot"][0] == event_body
            assert len(calls) == len(event_calls) == 1
