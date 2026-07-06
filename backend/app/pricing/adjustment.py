"""除權息還原價計算。

本模組只做純數學計算，不讀寫資料庫、不打網路。呼叫端提供某一檔股票的
原始 OHLC 序列與除權息事件序列後，這裡依事件往前串接還原係數，回傳可回填
`daily_prices.*_adj` 的結果。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import date
from bisect import bisect_left
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_PRICE_QUANT = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class PriceBar:
    """單日原始價 OHLC。"""

    date: date
    open_raw: Decimal
    high_raw: Decimal
    low_raw: Decimal
    close_raw: Decimal

    @classmethod
    def from_obj(cls, value: Any) -> PriceBar:
        """從 ORM 物件、dataclass 或 mapping 轉成 `PriceBar`。"""
        return cls(
            date=_read_attr(value, "date"),
            open_raw=_to_decimal(_read_attr(value, "open_raw"), field="open_raw"),
            high_raw=_to_decimal(_read_attr(value, "high_raw"), field="high_raw"),
            low_raw=_to_decimal(_read_attr(value, "low_raw"), field="low_raw"),
            close_raw=_to_decimal(_read_attr(value, "close_raw"), field="close_raw"),
        )


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    """除權息事件；配股數以「每股配股數」表示。"""

    ex_rights_date: date
    cash_dividend_per_share: Decimal = ZERO
    stock_dividend_per_share: Decimal = ZERO

    @classmethod
    def from_obj(cls, value: Any) -> CorporateActionEvent:
        """從 ORM 物件、dataclass 或 mapping 轉成 `CorporateActionEvent`。"""
        return cls(
            ex_rights_date=_read_attr(value, "ex_rights_date"),
            cash_dividend_per_share=_to_decimal(
                _read_attr(value, "cash_dividend_per_share", None),
                field="cash_dividend_per_share",
                default=ZERO,
            ),
            stock_dividend_per_share=_to_decimal(
                _read_attr(value, "stock_dividend_per_share", None),
                field="stock_dividend_per_share",
                default=ZERO,
            ),
        )


@dataclass(frozen=True, slots=True)
class AdjustedPriceBar:
    """含還原係數與還原價的單日結果。"""

    date: date
    open_raw: Decimal
    high_raw: Decimal
    low_raw: Decimal
    close_raw: Decimal
    adjustment_factor: Decimal
    open_adj: Decimal
    high_adj: Decimal
    low_adj: Decimal
    close_adj: Decimal


def fill_adjusted_prices(
    prices: Iterable[PriceBar | Mapping[str, Any] | Any],
    actions: Iterable[CorporateActionEvent | Mapping[str, Any] | Any],
    *,
    price_quant: Decimal | str | None = DEFAULT_PRICE_QUANT,
) -> list[AdjustedPriceBar]:
    """計算完整原始價序列的還原係數與 OHLC 還原價。

    `prices` 應提供同一檔股票的歷史日價，順序不限；回傳會依日期由舊到新排序。
    `actions` 可包含除息、除權或兩者同日混合事件。沒有事件影響的日期係數為 1。
    """
    normalized_prices = _normalize_prices(prices)
    factors = calculate_adjustment_factors(normalized_prices, actions)
    quant = _optional_quant(price_quant)

    adjusted: list[AdjustedPriceBar] = []
    for bar in normalized_prices:
        factor = factors[bar.date]
        adjusted.append(
            AdjustedPriceBar(
                date=bar.date,
                open_raw=bar.open_raw,
                high_raw=bar.high_raw,
                low_raw=bar.low_raw,
                close_raw=bar.close_raw,
                adjustment_factor=factor,
                open_adj=_quantize(bar.open_raw * factor, quant),
                high_adj=_quantize(bar.high_raw * factor, quant),
                low_adj=_quantize(bar.low_raw * factor, quant),
                close_adj=_quantize(bar.close_raw * factor, quant),
            )
        )
    return adjusted


def calculate_adjustment_factors(
    prices: Iterable[PriceBar | Mapping[str, Any] | Any],
    actions: Iterable[CorporateActionEvent | Mapping[str, Any] | Any],
) -> dict[date, Decimal]:
    """回傳每個交易日的累積還原係數。

    單一事件的比例以除權息日前一個交易日收盤價為基準：
    `(prev_close - cash_dividend) / (prev_close * (1 + stock_dividend))`。
    該比例只套用於事件日前的交易日，事件日與之後維持當時已除權息後的原始價格。
    """
    normalized_prices = _normalize_prices(prices)
    if not normalized_prices:
        return {}

    factors = {bar.date: ONE for bar in normalized_prices}
    actions_by_date = _combine_actions(actions)
    if not actions_by_date:
        return factors

    previous_close_by_event_date = _previous_close_lookup(normalized_prices, actions_by_date)
    for ex_rights_date in sorted(actions_by_date):
        previous_close = previous_close_by_event_date.get(ex_rights_date)
        if previous_close is None:
            continue
        ratio = calculate_event_ratio(previous_close, actions_by_date[ex_rights_date])
        for bar in normalized_prices:
            if bar.date >= ex_rights_date:
                break
            factors[bar.date] *= ratio
    return factors


def calculate_event_ratio(
    previous_close: Decimal | int | str,
    event: CorporateActionEvent | Mapping[str, Any] | Any,
) -> Decimal:
    """計算單次除權息事件要套到歷史價格的還原比例。"""
    close = _to_decimal(previous_close, field="previous_close")
    action = _normalize_action(event)
    denominator = close * (ONE + action.stock_dividend_per_share)
    numerator = close - action.cash_dividend_per_share

    if close <= ZERO:
        raise ValueError("previous_close must be greater than zero")
    if denominator <= ZERO:
        raise ValueError("stock_dividend_per_share results in a non-positive denominator")
    if numerator <= ZERO:
        raise ValueError("cash_dividend_per_share must be less than previous_close")
    return numerator / denominator


def apply_adjustments_to_rows(
    rows: Iterable[MutableMapping[str, Any]],
    actions: Iterable[CorporateActionEvent | Mapping[str, Any] | Any],
    *,
    price_quant: Decimal | str | None = DEFAULT_PRICE_QUANT,
) -> list[MutableMapping[str, Any]]:
    """回填 mapping row 的 `*_adj` 欄位並回傳同一批 row。

    此 helper 讓 ingestion pipeline 能直接把正規化 daily price rows 餵進來；它只改
    呼叫端傳入的 mapping，不處理 ORM session 或資料庫 I/O。
    """
    rows_list = list(rows)
    adjusted = fill_adjusted_prices(rows_list, actions, price_quant=price_quant)
    adjusted_by_date = {bar.date: bar for bar in adjusted}

    for row in rows_list:
        adjusted_bar = adjusted_by_date[_read_attr(row, "date")]
        row["open_adj"] = adjusted_bar.open_adj
        row["high_adj"] = adjusted_bar.high_adj
        row["low_adj"] = adjusted_bar.low_adj
        row["close_adj"] = adjusted_bar.close_adj
    return rows_list


def _normalize_prices(prices: Iterable[PriceBar | Mapping[str, Any] | Any]) -> list[PriceBar]:
    normalized = [price if isinstance(price, PriceBar) else PriceBar.from_obj(price) for price in prices]
    normalized.sort(key=lambda bar: bar.date)
    return normalized


def _normalize_action(action: CorporateActionEvent | Mapping[str, Any] | Any) -> CorporateActionEvent:
    if isinstance(action, CorporateActionEvent):
        return action
    return CorporateActionEvent.from_obj(action)


def _combine_actions(
    actions: Iterable[CorporateActionEvent | Mapping[str, Any] | Any],
) -> dict[date, CorporateActionEvent]:
    combined: dict[date, CorporateActionEvent] = {}
    for raw_action in actions:
        action = _normalize_action(raw_action)
        if action.cash_dividend_per_share == ZERO and action.stock_dividend_per_share == ZERO:
            continue
        existing = combined.get(action.ex_rights_date)
        if existing is None:
            combined[action.ex_rights_date] = action
            continue
        combined[action.ex_rights_date] = CorporateActionEvent(
            ex_rights_date=action.ex_rights_date,
            cash_dividend_per_share=existing.cash_dividend_per_share
            + action.cash_dividend_per_share,
            stock_dividend_per_share=existing.stock_dividend_per_share
            + action.stock_dividend_per_share,
        )
    return combined


def _previous_close_lookup(
    prices: Sequence[PriceBar],
    actions_by_date: Mapping[date, CorporateActionEvent],
) -> dict[date, Decimal]:
    dates = [bar.date for bar in prices]
    lookup: dict[date, Decimal] = {}
    for action_date in actions_by_date:
        previous_index = bisect_left(dates, action_date) - 1
        if previous_index >= 0:
            lookup[action_date] = prices[previous_index].close_raw
    return lookup


def _read_attr(value: Any, name: str, default: Any = ...) -> Any:
    if isinstance(value, Mapping):
        if default is ...:
            return value[name]
        return value.get(name, default)
    if default is ...:
        return getattr(value, name)
    return getattr(value, name, default)


def _to_decimal(value: Any, *, field: str, default: Decimal | None = None) -> Decimal:
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"{field} is required")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be decimal-compatible") from exc


def _optional_quant(value: Decimal | str | None) -> Decimal | None:
    if value is None:
        return None
    return _to_decimal(value, field="price_quant")


def _quantize(value: Decimal, quant: Decimal | None) -> Decimal:
    if quant is None:
        return value
    return value.quantize(quant, rounding=ROUND_HALF_UP)
