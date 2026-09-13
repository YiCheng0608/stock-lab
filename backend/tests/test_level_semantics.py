from app.level_semantics import build_level_semantics, build_stop_price_semantics


def test_known_v1_semantics_are_canonical_and_do_not_invent_history_times() -> None:
    semantics = build_level_semantics(
        strategy_name="breakout_v1",
        strategy_version="1.0.0",
        field_mapping={
            "trigger_price": "breakout_price",
            "invalid_price": "invalid_price",
            "target_1": "target_1",
            "target_2": "target_2",
        },
    )

    assert semantics["version"] == "signal-level-semantics/v1"
    assert semantics["kind"] == "rule_reference"
    assert semantics["reason"] == "canonical_v1_allowlist"
    assert semantics["strategy"] == {"name": "breakout_v1", "version": "1.0.0"}
    assert semantics["formula"]["version"] == "legacy-risk-levels/v1"
    assert semantics["fields"]["trigger_price"] == {
        "role": "rule_trigger",
        "label_zh": "規則觸發價",
        "source_field": "breakout_price",
    }
    assert semantics["fields"]["target_1"]["label_zh"] == "規則參考目標一"
    assert semantics["fields"]["target_2"]["label_zh"] == "規則參考目標二"
    assert semantics["price_basis"] == {"value": None, "reason": "legacy_price_basis_not_persisted"}
    assert semantics["cost_included"] == {"value": False, "reason": "legacy_level_formula_excludes_costs"}
    assert semantics["decision_at"]["value"] is None
    assert semantics["generated_at"]["value"] is None
    assert semantics["generated_at"]["reason"] == "legacy_generated_at_not_persisted_with_timezone"


def test_unknown_relation_cannot_be_upgraded_by_strategy_like_values() -> None:
    semantics = build_level_semantics(
        strategy_name="other_strategy",
        strategy_version="1.0.0",
        field_mapping={"trigger_price": "breakout_price"},
    )
    assert semantics["kind"] == "unknown"
    assert semantics["reason"] == "strategy_or_version_not_allowlisted"
    assert semantics["formula"]["version"] is None
    assert semantics["cost_included"]["value"] is None
    assert semantics["fields"]["trigger_price"]["role"] == "unknown"
    assert semantics["fields"]["trigger_price"]["label_zh"] == "價位（語意未確認）"


def test_stop_price_origin_keeps_user_position_risk_separate_from_rule_invalid() -> None:
    user_stop = build_stop_price_semantics(has_position_stop=True, has_rule_fallback=True)
    rule_stop = build_stop_price_semantics(has_position_stop=False, has_rule_fallback=True, rule_semantics_known=True)

    assert user_stop["kind"] == "user_position_risk_input"
    assert user_stop["origin"] == "portfolio_position.stop_price"
    assert user_stop["is_rule_reference"] is False
    assert rule_stop["kind"] == "rule_reference"
    assert rule_stop["origin"] == "signal.invalid_price"
    assert rule_stop["is_rule_reference"] is True
    unknown_stop = build_stop_price_semantics(has_position_stop=False, has_rule_fallback=False)
    assert unknown_stop["reason"] == "no_rule_or_position_stop"
