"""Safe, user-facing labels for product read models.

Canonical evaluators and database rows intentionally keep their machine
states/reason codes for audit.  This module is the boundary used by the
product decision API: unknown machine values are never rendered as if their
meaning were known.
"""

from __future__ import annotations

from typing import Any


DISPLAY_ACTION_LABELS = {
    "conditional_entry": "符合條件後可研究進場",
    "wait_breakout": "等待突破條件",
    "wait_pullback": "等待回踩條件",
    "hold_observe": "持有觀察",
    "reduce_exit": "持倉風險：減碼／退場條件",
    "data_insufficient": "策略判斷資料待補",
    "no_condition": "暫無研究條件",
    "manual_review": "需人工判讀",
}


REASON_LABELS = {
    "passed": "此研究條件已符合",
    "rejected": "此研究條件尚未成立",
    "data_incomplete": "此研究條件資料待補",
    "observation": "條件尚未成立，持續觀察",
    "conditional": "符合條件後可研究進場",
    "invalid_levels": "研究價位無法驗證",
    "prior_20_highs_missing_or_invalid": "前 20 個交易日高點資料待補",
    "prior_20_volumes_missing_or_invalid": "前 20 個交易日成交量資料待補",
    "close_missing_or_non_finite": "最近收盤資料待補",
    "volume_missing_or_non_finite": "當日成交量資料待補",
    "ma20_missing_or_non_finite": "20 日均線資料待補",
    "ma60_missing_or_non_finite": "60 日均線資料待補",
    "group_relative_strength_not_positive": "所屬已核實群組未呈相對大盤正向",
    "group_excess_return_20d_missing_or_non_finite": "近 20 日相對大盤資料待補",
    "institutional_flow_to_turnover_ratio_5d_missing_or_non_finite": "近 5 日法人籌碼資料待補",
    "institutional_flow_5d_missing_or_incomplete": "近 5 日法人籌碼資料待補",
    "margin_balance_change_ratio_5d_missing_or_non_finite": "近 5 日融資變化資料待補",
    "margin_change_5d_missing_or_incomplete": "近 5 日融資變化資料待補",
    "effective_group_score_missing_or_under_minimum_members": "族群成員或相對大盤資料不足，無法取得有效群組脈絡",
    "close_or_volume_must_be_positive": "收盤或成交量資料無法用於計算",
    "bar_count_missing_or_invalid": "歷史交易日數資料待核實",
    "history_under_60_bars": "近 60 個交易日行情不足",
    "price_and_volume_inputs_must_be_positive": "價格、均線或成交量資料無法用於計算",
    "institutional_flow_materially_adverse": "法人籌碼未達規則要求",
    "margin_financing_increase_abnormal": "融資變化超過規則上限",
    "unsupported_instrument_type": "此商品類型暫不適用一般研究規則",
    "unsupported_or_missing_etf_category": "ETF 類別待核實，暫不產生一般研究動作",
    "etf_category_is_only_valid_for_etf": "ETF 分類資料待核實",
    "ipo_history_under_20_bars": "新上市標的歷史未滿 20 個交易日",
    "ipo_observation_only_under_60_bars": "新上市標的歷史未滿 60 個交易日，僅作觀察",
    "unsupported_entry_type": "研究進場類型無法驗證",
    "entry_price_must_be_finite_and_positive": "研究進場價無法驗證",
    "invalid_price_must_be_finite_and_positive": "研究失效價無法驗證",
    "invalid_price_must_be_below_entry": "研究失效價與進場價關係無法驗證",
    "target_1_must_be_finite_and_positive": "第一目標價無法驗證",
    "target_1_must_exceed_entry": "第一目標價與進場價關係無法驗證",
    "target_2_must_be_finite_and_positive_when_present": "第二目標價無法驗證",
    "target_2_must_exceed_target_1": "第二目標價與第一目標價關係無法驗證",
    "minimum_first_target_risk_reward_must_be_finite_and_positive": "風險報酬門檻設定待核實",
    "target_1_risk_reward_below_minimum": "第一目標的風險報酬未達規則門檻",
    "signal_day_suspended": "訊號日交易狀態不適合計算",
    "unsupported_current_status": "研究追蹤狀態無法驗證",
    "unsupported_next_status": "研究追蹤狀態無法驗證",
    "illegal_signal_status_transition": "研究追蹤狀態無法驗證",
}


def display_action_label(state: str | None) -> str:
    return DISPLAY_ACTION_LABELS.get(str(state or ""), "需人工判讀")


def display_reason(reason: Any, *, fallback: str = "研究條件需要人工核對") -> str:
    """Translate one reason without exposing an unknown machine token."""

    value = str(reason or "").strip()
    if not value:
        return fallback
    if value == "目前資料不足，不能把此標的包裝成可執行條件":
        return "策略判斷資料尚未齊備，暫時不能形成可執行條件"
    if value == "required inputs complete":
        return "必要研究資料已齊備"
    if value in REASON_LABELS:
        return REASON_LABELS[value]
    if ";" in value:
        parts = [display_reason(part, fallback="") for part in value.split(";")]
        return "；".join(part for part in parts if part) or fallback
    if ":" in value:
        base = value.split(":", 1)[0].strip()
        if base in REASON_LABELS:
            return REASON_LABELS[base]
    if "=" in value:
        key, raw_value = (part.strip() for part in value.split("=", 1))
        if key in {"breakout", "pullback"}:
            strategy = "突破研究條件" if key == "breakout" else "回踩研究條件"
            state, _, reasons = raw_value.partition(":")
            state_label = {
                "passed": "已成立",
                "conditional": "符合條件",
                "observation": "未成立、持續觀察",
                "rejected": "尚未成立",
                "data_incomplete": "資料待補",
            }.get(state, "狀態待核實")
            reason_labels = [display_reason(item, fallback="") for item in reasons.split(",") if item]
            suffix = "（" + "、".join(item for item in reason_labels if item) + "）" if any(reason_labels) else ""
            return f"{strategy}：{state_label}{suffix}"
        if key == "missing":
            labels = [display_reason(item, fallback="") for item in raw_value.split(",") if item]
            return "待補資料：" + "、".join(item for item in labels if item) if any(labels) else "必要研究資料尚未齊備"
        if key == "group":
            return "族群條件待補" if raw_value.casefold() == "missing" else "族群條件已核對"
    if "資料不足" in value:
        return value.replace("資料不足", "資料尚未齊備")
    # A machine-looking token that is not in the allowlist must not be
    # heuristically split or passed through to the product surface.
    if value.isascii() and any(char.isalpha() for char in value):
        return fallback
    return value


def primary_reason(
    *,
    action_state: str,
    reasons: list[Any],
    missing: list[Any],
    strategy: str | None = None,
) -> dict[str, str]:
    source = missing[0] if action_state == "data_insufficient" and missing else (reasons[0] if reasons else action_state)
    label = display_reason(source)
    scope = "breakout" if strategy == "breakout_v1" else "pullback" if strategy == "pullback_v1" else "research"
    return {"label": label, "scope": scope}
