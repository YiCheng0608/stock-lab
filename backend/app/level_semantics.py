"""Canonical presentation metadata for legacy rule-derived price levels.

The v1 worker stores numeric levels without a durable presentation contract.
This module is intentionally read-only: it labels values at the API boundary
without changing the values, the strategy gates, or the calculation formula.
Only the strategy/version pair that is proven by the current source is allowed
to claim the v1 formula.  Caller-provided evidence is never used to upgrade an
unknown strategy or version.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


LEVEL_SEMANTICS_VERSION = "signal-level-semantics/v1"
KNOWN_RULE_STRATEGIES = frozenset({"breakout_v1", "pullback_v1"})
KNOWN_RULE_STRATEGY_VERSION = "1.0.0"
KNOWN_FORMULA_VERSION = "legacy-risk-levels/v1"
KNOWN_FORMULA_SOURCE = "backend.worker.pipeline._risk_levels"

SIGNAL_FIELD_DEFINITIONS: dict[str, dict[str, str]] = {
    "breakout_price": {"role": "rule_trigger", "label_zh": "規則觸發價", "source_field": "breakout_price"},
    "pullback_low": {"role": "rule_observation_zone", "label_zh": "規則回踩觀察區下緣", "source_field": "pullback_low"},
    "pullback_high": {"role": "rule_observation_zone", "label_zh": "規則回踩觀察區上緣", "source_field": "pullback_high"},
    "reference_entry": {"role": "rule_calculation_reference", "label_zh": "規則計算參考價", "source_field": "reference_entry"},
    "invalid_price": {"role": "rule_invalidation_reference", "label_zh": "規則失效參考價", "source_field": "invalid_price"},
    "target_1": {"role": "rule_reference_target", "label_zh": "規則參考目標一", "source_field": "target_1"},
    "target_2": {"role": "rule_reference_target", "label_zh": "規則參考目標二", "source_field": "target_2"},
}
UNKNOWN_LEVEL_LABEL = "價位（語意未確認）"


def utc_now_iso() -> str:
    """Return an aware timestamp for the current API response assembly."""

    return datetime.now(timezone.utc).isoformat()


def _known_strategy(strategy_name: object, strategy_version: object) -> bool:
    return (
        isinstance(strategy_name, str)
        and strategy_name in KNOWN_RULE_STRATEGIES
        and isinstance(strategy_version, str)
        and strategy_version == KNOWN_RULE_STRATEGY_VERSION
    )


def _strategy_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def build_level_semantics(
    *,
    strategy_name: object,
    strategy_version: object,
    field_mapping: Mapping[str, str] | None = None,
    response_generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the shared read-time ``level_semantics`` contract.

    ``strategy_name`` and ``strategy_version`` must come from persisted
    ``StrategyVersion`` rows.  Evidence markers are deliberately not accepted
    as an input to identity or formula selection.  ``field_mapping`` maps
    projected output fields to their persisted signal source fields.
    """

    name = _strategy_value(strategy_name)
    version = _strategy_value(strategy_version)
    known = _known_strategy(name, version)
    mapping = dict(field_mapping or {key: key for key in SIGNAL_FIELD_DEFINITIONS})
    if known:
        fields = {
            output_field: {
                **SIGNAL_FIELD_DEFINITIONS.get(source_field, {
                    "role": "unknown",
                    "label_zh": UNKNOWN_LEVEL_LABEL,
                    "source_field": source_field,
                }),
                "source_field": source_field,
            }
            for output_field, source_field in mapping.items()
        }
        price_basis = {"value": None, "reason": "legacy_price_basis_not_persisted"}
        formula = {
            "version": KNOWN_FORMULA_VERSION,
            "source": KNOWN_FORMULA_SOURCE,
            "reason": None,
            "expression": "risk=max(atr if truthy else entry*0.02, entry*0.01); invalid=max(0.01, entry-risk); target_1=entry+1.6*risk; target_2=entry+3*risk",
            "rounding": "round each returned level to 2 decimal places",
        }
        cost_included: dict[str, Any] = {"value": False, "reason": "legacy_level_formula_excludes_costs"}
        decision_at: dict[str, Any] = {"value": None, "reason": "legacy_decision_at_not_persisted"}
        generated_at: dict[str, Any] = {"value": None, "reason": "legacy_generated_at_not_persisted_with_timezone"}
        reason = "canonical_v1_allowlist"
        kind = "rule_reference"
    else:
        fields = {
            output_field: {
                "role": "unknown",
                "label_zh": UNKNOWN_LEVEL_LABEL,
                "source_field": source_field,
                "reason": "strategy_or_version_not_allowlisted",
            }
            for output_field, source_field in mapping.items()
        }
        unknown_reason = "strategy_or_version_not_allowlisted"
        price_basis = {"value": None, "reason": unknown_reason}
        formula = {"version": None, "source": None, "reason": unknown_reason}
        cost_included = {"value": None, "reason": unknown_reason}
        decision_at = {"value": None, "reason": unknown_reason}
        generated_at = {"value": None, "reason": unknown_reason}
        reason = unknown_reason
        kind = "unknown"
    return {
        "version": LEVEL_SEMANTICS_VERSION,
        "kind": kind,
        "reason": reason,
        "strategy": {"name": name, "version": version},
        "formula": formula,
        "fields": fields,
        "price_basis": price_basis,
        "cost_included": cost_included,
        "decision_at": {"value": None, "reason": decision_at["reason"]},
        "generated_at": {"value": None, "reason": generated_at["reason"]},
        "response_generated_at": response_generated_at or utc_now_iso(),
    }


def build_stop_price_semantics(
    *,
    has_position_stop: bool,
    has_rule_fallback: bool,
    rule_semantics_known: bool = False,
) -> dict[str, Any]:
    """Describe the action-card stop/risk price without relabelling ownership."""

    if has_position_stop:
        return {
            "kind": "user_position_risk_input",
            "label": "持倉設定風險價",
            "origin": "portfolio_position.stop_price",
            "source_field": "stop_price",
            "is_rule_reference": False,
            "reason": None,
        }
    if has_rule_fallback and rule_semantics_known:
        return {
            "kind": "rule_reference",
            "label": SIGNAL_FIELD_DEFINITIONS["invalid_price"]["label_zh"],
            "origin": "signal.invalid_price",
            "source_field": "invalid_price",
            "is_rule_reference": True,
            "reason": None,
        }
    if has_rule_fallback:
        return {
            "kind": "unknown",
            "label": UNKNOWN_LEVEL_LABEL,
            "origin": "signal.invalid_price",
            "source_field": "invalid_price",
            "is_rule_reference": False,
            "reason": "strategy_or_version_not_allowlisted",
        }
    return {
        "kind": "unknown",
        "label": UNKNOWN_LEVEL_LABEL,
        "origin": None,
        "source_field": None,
        "is_rule_reference": False,
        "reason": "no_rule_or_position_stop",
    }


def canonical_evidence(
    evidence: Mapping[str, Any] | None,
    semantics: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy legacy evidence and attach canonical semantics without mutating it."""

    result = dict(evidence) if isinstance(evidence, Mapping) else {}
    result["level_semantics"] = dict(semantics)
    return result
