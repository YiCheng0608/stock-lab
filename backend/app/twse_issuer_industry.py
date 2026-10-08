"""Additive, pure-read issuer code/name citation trace; issuer v1 stays intact."""
from __future__ import annotations

from datetime import date, timedelta
import os
import re
from typing import Mapping

from worker import twse_industry_taxonomy as taxonomy
from worker import twse_issuer_capture as issuer_consumer

CAPTURE_ENV = "STOCK_TWSE_INDUSTRY_TRACE"
REGISTRY_VERSION_ENV = "STOCK_TWSE_INDUSTRY_REGISTRY_VERSION"
REGISTRY_DIGEST_ENV = "STOCK_TWSE_INDUSTRY_REGISTRY_DIGEST"
CONSUMER_VERSION_ENV = "STOCK_TWSE_INDUSTRY_CONSUMER_VERSION"
CONSUMER_DIGEST_ENV = "STOCK_TWSE_INDUSTRY_CONSUMER_DIGEST"


def _result(exchange: str, symbol: str, as_of: date | None) -> dict:
    return {
        "version": taxonomy.VERSION, "status": "unavailable", "reasons": [], "exchange": exchange, "symbol": symbol,
        "as_of": as_of.isoformat() if type(as_of) is date else None,
        "cutoff_basis": "observed_taipei_date_inclusive", "metadata_observed_date": None,
        "row": None, "provenance": None,
        "policy": {"version": taxonomy.VERSION, "digest": taxonomy.POLICY_DIGEST, "profile": taxonomy.PROFILE},
        "limitations": ["two_complete_code_name_citations_only", "parsed_documents_not_raw_capture_receipts",
                        "not_complete_current_taxonomy", "company_classification_effective_date_unknown",
                        "not_ordinary_or_etf_classification", "no_ranking_or_group_membership", "not_historical_pit"],
    }


def _input_evidence(issuer: dict, events: dict, exchange: str, symbol: str, cutoff: str) -> tuple[dict, dict, dict]:
    pins = taxonomy.INPUT_PINS
    taxonomy.require(type(issuer) is dict and issuer.get("status") == "available"
                     and issuer.get("version") == pins["issuer_profile_version"]
                     and issuer.get("exchange") == exchange and issuer.get("symbol") == symbol
                     and issuer.get("as_of") == cutoff and issuer.get("classification") == "unsupported"
                     and issuer.get("historical_pit") == "unsupported" and issuer.get("storage") == "memory_only"
                     and issuer.get("policy") == {"version": pins["issuer_profile_version"],
                                                  "digest": pins["issuer_profile_digest"], "profile": issuer_consumer.PROFILE},
                     "industry_issuer_unavailable")
    taxonomy.require(type(events) is dict and events.get("status") == "available"
                     and events.get("version") == pins["event_consumer_version"] and events.get("as_of") == cutoff
                     and events.get("historical_pit") == "unsupported" and events.get("storage") == "memory_only",
                     "industry_same_cutoff_event_unavailable")
    row, ip, ep = issuer.get("row"), issuer.get("provenance"), events.get("provenance")
    taxonomy.require(type(row) is dict and type(ip) is dict and type(ep) is dict, "industry_source_evidence_invalid")
    raw = row.get("source_row")
    taxonomy.require(type(raw) is dict and set(raw) == set(issuer_consumer.FIELDS)
                     and all(type(value) is str for value in raw.values()) and raw["公司代號"] == symbol
                     and row.get("exchange") == exchange and row.get("symbol") == symbol
                     and row.get("full_name") == raw["公司名稱"] and row.get("short_name") == raw["公司簡稱"]
                     and row.get("industry_code_raw") == raw["產業別"], "industry_issuer_raw_mapping_invalid")
    expected_ip = {"source_id": issuer_consumer.SOURCE_ID, "source_version": pins["issuer_source_version"],
                   "endpoint": issuer_consumer.ENDPOINT, "profile": issuer_consumer.PROFILE,
                   "registry_version": pins["issuer_registry_version"], "manifest_digest": pins["issuer_registry_digest"]}
    expected_ep = {"source_id": "twse_twt48u_all", "source_version": pins["event_source_version"],
                   "endpoint": "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL",
                   "registry_version": pins["event_registry_version"], "manifest_digest": pins["event_registry_digest"]}
    for evidence, expected, observed in ((ip, expected_ip, issuer.get("observed_date")),
                                        (ep, expected_ep, events.get("observed_date"))):
        taxonomy.require(all(evidence.get(key) == value for key, value in expected.items()), "industry_input_pins_mismatch")
        taxonomy.require(all(type(evidence.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", evidence[key])
                             for key in ("body_sha256", "receipt_sha256")), "industry_original_hash_invalid")
        started = issuer_consumer.timestamp(evidence.get("request_started_at"))
        captured = issuer_consumer.timestamp(evidence.get("captured_at"))
        taxonomy.require(started <= captured and observed == (captured + timedelta(hours=8)).date().isoformat()
                         and type(observed) is str and observed <= cutoff, "industry_observation_after_cutoff")
    taxonomy.require(row.get("body_sha256") == ip["body_sha256"] and row.get("receipt_sha256") == ip["receipt_sha256"]
                     and type(row.get("row_ordinal")) is int and 1 <= row["row_ordinal"] <= issuer.get("candidate_count", 0),
                     "industry_original_trace_mismatch")
    selected = events.get("rows")
    taxonomy.require(type(selected) is list and bool(selected)
                     and all(type(event) is dict and event.get("exchange") == exchange and event.get("symbol") == symbol
                             and event.get("company_name") in (row["full_name"], row["short_name"])
                             and type(event.get("row_ordinal")) is int and event["row_ordinal"] > 0 for event in selected)
                     and row.get("event_names") == [event["company_name"] for event in selected],
                     "industry_event_name_conflict")
    kinds = {"息": ("ex_dividend", "除息"), "權": ("ex_right", "除權"), "權息": ("ex_right_and_dividend", "除權息")}
    taxonomy.require(len({event["row_ordinal"] for event in selected}) == len(selected), "industry_duplicate_event_ordinal")
    for event in selected:
        taxonomy.require(event.get("source_classification") in kinds
                         and (event.get("kind"), event.get("label")) == kinds[event["source_classification"]]
                         and event.get("event_date") == issuer_consumer.source_date(event.get("source_date"), report=True)
                         and event.get("event_date_role") == "effective_date" and event.get("event_date_precision") == "date"
                         and all(event.get(key) is None for key in ("published_at", "first_available_at", "revision_available_at"))
                         and event.get("availability") == "unknown", "industry_event_raw_mapping_invalid")
    return row, ip, ep


def build_issuer_industry(exchange: str, symbol: str, as_of: date | None, *, issuer_profile: dict | None,
                          events: dict | None, environment: Mapping[str, str] | None = None) -> dict:
    result = _result(exchange, symbol, as_of)
    config = os.environ if environment is None else environment
    try:
        taxonomy.require(config.get(CAPTURE_ENV) == "1", "industry_trace_not_enabled")
        taxonomy.require(exchange == "TWSE" and symbol in issuer_consumer.SYMBOLS, "industry_symbol_not_supported")
        taxonomy.require(type(as_of) is date, "industry_shared_cutoff_missing")
        expected = ((REGISTRY_VERSION_ENV, taxonomy.REGISTRY_VERSION), (REGISTRY_DIGEST_ENV, taxonomy.REGISTRY_DIGEST),
                    (CONSUMER_VERSION_ENV, taxonomy.VERSION), (CONSUMER_DIGEST_ENV, taxonomy.POLICY_DIGEST))
        taxonomy.require(all(config.get(key) == value for key, value in expected), "industry_external_policy_pins_mismatch")
        taxonomy.consumer_policy()
        registry = taxonomy.load_citations(expected_registry_version=config[REGISTRY_VERSION_ENV],
                                          expected_digest=config[REGISTRY_DIGEST_ENV])
        metadata_date = registry["declaration"]["metadata_observed_date"]
        result["metadata_observed_date"] = metadata_date
        taxonomy.require(metadata_date <= result["as_of"], "industry_metadata_observed_after_cutoff")
        row, ip, ep = _input_evidence(issuer_profile, events, exchange, symbol, result["as_of"])
        name = taxonomy.quote_name(registry, exchange, row["industry_code_raw"])
        result.update(status="available", row={"industry_code_raw": row["industry_code_raw"], "name_zh": name,
                      "issuer_row_ordinal": row["row_ordinal"], "event_row_ordinals": [event["row_ordinal"] for event in events["rows"]],
                      "company_classification_effective_date": "unknown"},
                      provenance={"issuer": dict(ip), "event": dict(ep), "taxonomy_citation": registry})
    except (ValueError, OSError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        reason = str(exc) if isinstance(exc, taxonomy.IndustryCitationError) else "industry_source_evidence_invalid"
        result["reasons"] = [reason]
    return result
