"""Pure, point-in-time aware ATR14 Wilder calculation.

This module deliberately has no database, network, or filesystem dependency.
Callers must provide already-normalized OHLC prices and the evidence that makes
their price basis and corporate-action treatment auditable.  It does not
calculate adjustment factors and it does not claim that a source is official.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


FEATURE_VERSION = "technical_v2_atr14_wilder"
ALGORITHM = "wilder"
PERIOD = 14
MARKET_TIMEZONE = ZoneInfo("Asia/Taipei")

# A basis is intentionally a small, explicit vocabulary.  The versioned
# values are useful when an upstream feed changes its adjustment convention;
# an arbitrary string must not silently become a comparable price basis.
KNOWN_PRICE_BASES = frozenset(
    {
        "raw",
        "raw_v1",
        "raw_ohlc",
        "raw_ohlc_v1",
        "adjusted",
        "adjusted_v1",
        "adjusted_ohlc",
        "adjusted_ohlc_v1",
        "split_adjusted",
        "split_adjusted_v1",
        "dividend_adjusted",
        "dividend_adjusted_v1",
        "total_return",
        "total_return_v1",
    }
)


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must not be a naive datetime")
        return value.astimezone(MARKET_TIMEZONE).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date") from exc
    raise ValueError(f"{field} must be a date or ISO date")


def _parse_timestamp(value: Any, field: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required for point-in-time validation")
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO timestamp with timezone") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field} must be a timezone-aware datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must not be naive")
    return parsed.astimezone(timezone.utc)


def _basis_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized if normalized in KNOWN_PRICE_BASES else None


def _finite_positive(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _mapping_value(mapping: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


@dataclass(frozen=True)
class OHLCBar:
    """One source bar supplied to the pure ATR calculator.

    ``previous_close`` is optional because the first row of a window may use
    the calculator-level previous close or an explicitly proven sequence
    start.  When a row follows a missing session, supplying its own
    ``previous_close`` is the explicit way to reconnect continuity.
    """

    trading_date: date | str | datetime
    open: Any
    high: Any
    low: Any
    close: Any
    price_basis: str | None = None
    previous_close: Any = None
    previous_close_basis: str | None = None
    previous_close_source_ref: str | None = None
    previous_close_available_at: datetime | str | None = None
    data_available_at: datetime | str | None = None
    is_suspended: bool = False
    source_ref: str | None = None


@dataclass(frozen=True)
class CorporateActionEvidence:
    """Caller-supplied corporate-action evidence.

    The calculator only validates this metadata.  It never derives or applies
    a factor.  OHLC values must already be in the declared ``price_basis``.
    """

    action_date: date | str | datetime
    action_type: str
    price_basis: str | None
    coverage: str = "complete"
    source_ref: str | None = None
    available_at: datetime | str | None = None


@dataclass(frozen=True)
class ATRObservation:
    trading_date: date
    true_range: float | None
    atr: float | None
    null_reason: str | None
    valid_tr_count: int
    bar_present: bool
    is_suspended: bool
    data_available_at: datetime | None

    @property
    def tr(self) -> float | None:
        """Short alias for consumers that refer to true range as ``TR``."""

        return self.true_range

    def to_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.trading_date.isoformat(),
            "tr": self.true_range,
            "true_range": self.true_range,
            "atr": self.atr,
            "null_reason": self.null_reason,
            "valid_tr_count": self.valid_tr_count,
            "bar_present": self.bar_present,
            "is_suspended": self.is_suspended,
            "data_available_at": self.data_available_at.isoformat() if self.data_available_at else None,
        }


@dataclass(frozen=True)
class ATRArtifact:
    feature_version: str
    algorithm: str
    period: int
    input_snapshot_ref: str
    price_basis: str
    decision_at: datetime | None
    observations: tuple[ATRObservation, ...]
    corporate_actions: tuple[dict[str, Any], ...]
    corporate_action_coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_version": self.feature_version,
            "algorithm": self.algorithm,
            "period": self.period,
            "input_snapshot_ref": self.input_snapshot_ref,
            "price_basis": self.price_basis,
            "decision_at": self.decision_at.isoformat() if self.decision_at else None,
            "provenance_validation": "caller_supplied_only",
            "observations": [observation.to_dict() for observation in self.observations],
            "corporate_actions": [dict(action) for action in self.corporate_actions],
            "corporate_action_coverage": dict(self.corporate_action_coverage),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)


def _normalize_bar(value: OHLCBar | Mapping[str, Any]) -> OHLCBar:
    if isinstance(value, Mapping):
        trading_date = _mapping_value(value, "trading_date", "date")
        if trading_date is None:
            raise ValueError("each bar requires trading_date")
        value = OHLCBar(
            trading_date=trading_date,
            open=_mapping_value(value, "open"),
            high=_mapping_value(value, "high"),
            low=_mapping_value(value, "low"),
            close=_mapping_value(value, "close"),
            price_basis=_mapping_value(value, "price_basis"),
            previous_close=_mapping_value(value, "previous_close", "prev_close"),
            previous_close_basis=_mapping_value(value, "previous_close_basis", "prev_close_basis"),
            previous_close_source_ref=_mapping_value(
                value,
                "previous_close_source_ref",
                "prev_close_source_ref",
            ),
            previous_close_available_at=_mapping_value(
                value,
                "previous_close_available_at",
                "prev_close_available_at",
            ),
            data_available_at=_mapping_value(
                value,
                "data_available_at",
                "available_at",
                "availability_at",
            ),
            is_suspended=_mapping_value(value, "is_suspended", "suspended", default=False),
            source_ref=_mapping_value(value, "source_ref", "input_ref"),
        )
    if not isinstance(value, OHLCBar):
        raise TypeError("bars must contain OHLCBar or mapping values")
    if not isinstance(value.is_suspended, bool):
        raise ValueError("is_suspended must be a bool")
    return OHLCBar(
        trading_date=_parse_date(value.trading_date, "bar.trading_date"),
        open=value.open,
        high=value.high,
        low=value.low,
        close=value.close,
        price_basis=value.price_basis,
        previous_close=value.previous_close,
        previous_close_basis=value.previous_close_basis,
        previous_close_source_ref=value.previous_close_source_ref,
        previous_close_available_at=_parse_timestamp(
            value.previous_close_available_at,
            "bar.previous_close_available_at",
        ),
        data_available_at=_parse_timestamp(value.data_available_at, "bar.data_available_at"),
        is_suspended=value.is_suspended,
        source_ref=value.source_ref,
    )


def _normalize_action(value: CorporateActionEvidence | Mapping[str, Any]) -> CorporateActionEvidence:
    if isinstance(value, Mapping):
        action_date = _mapping_value(value, "action_date", "date", "effective_date")
        if action_date is None:
            raise ValueError("each corporate action requires action_date")
        value = CorporateActionEvidence(
            action_date=action_date,
            action_type=_mapping_value(value, "action_type", "type", default=""),
            price_basis=_mapping_value(value, "price_basis"),
            coverage=_mapping_value(value, "coverage", default=""),
            source_ref=_mapping_value(value, "source_ref", "provenance_ref", "input_ref"),
            available_at=_mapping_value(value, "available_at", "data_available_at", "availability_at"),
        )
    if not isinstance(value, CorporateActionEvidence):
        raise TypeError("corporate_actions must contain CorporateActionEvidence or mapping values")
    return CorporateActionEvidence(
        action_date=_parse_date(value.action_date, "corporate_action.action_date"),
        action_type=value.action_type,
        price_basis=value.price_basis,
        coverage=value.coverage,
        source_ref=value.source_ref,
        available_at=_parse_timestamp(value.available_at, "corporate_action.available_at"),
    )


def _validate_strictly_increasing(values: list[date], field: str) -> None:
    for previous, current in zip(values, values[1:]):
        if current <= previous:
            raise ValueError(f"{field} must be strictly increasing without duplicates")


def _action_issue(
    action: CorporateActionEvidence,
    *,
    declared_basis: str,
    decision_at: datetime | None,
) -> str | None:
    if not isinstance(action.action_type, str) or not action.action_type.strip():
        return "corporate_action_metadata_incomplete"
    if str(action.coverage).casefold() != "complete":
        return "corporate_action_coverage_incomplete"
    if not action.source_ref or not isinstance(action.source_ref, str) or not action.source_ref.strip():
        return "corporate_action_provenance_missing"
    if action.available_at is None:
        return "corporate_action_availability_unknown"
    if decision_at is not None and action.available_at > decision_at:
        return "corporate_action_not_available_at_decision"
    action_basis = _basis_key(action.price_basis)
    if action_basis is None or action_basis != _basis_key(declared_basis):
        return "corporate_action_basis_unverified"
    return None


def _previous_close_issue(
    value: Any,
    *,
    basis: str | None,
    source_ref: str | None,
    available_at: datetime | None,
    declared_basis: str,
    decision_at: datetime,
) -> str | None:
    if _finite_positive(value) is None:
        return "invalid_previous_close"
    if _basis_key(basis) is None or _basis_key(basis) != _basis_key(declared_basis):
        return "inconsistent_previous_close_basis"
    if not isinstance(source_ref, str) or not source_ref.strip():
        return "previous_close_provenance_missing"
    if available_at is None:
        return "previous_close_availability_unknown"
    if available_at > decision_at:
        return "previous_close_not_available_at_decision"
    return None


def _corporate_action_coverage_issue(
    *,
    coverage: str,
    source_ref: str,
    available_at: datetime,
    decision_at: datetime,
) -> str | None:
    if coverage.casefold() != "complete":
        return "corporate_action_coverage_incomplete"
    if available_at > decision_at:
        return "corporate_action_not_available_at_decision"
    return None


def _invalid_ohlc(bar: OHLCBar) -> bool:
    values = {
        "open": _finite_positive(bar.open),
        "high": _finite_positive(bar.high),
        "low": _finite_positive(bar.low),
        "close": _finite_positive(bar.close),
    }
    if any(value is None for value in values.values()):
        return True
    assert all(value is not None for value in values.values())
    return not (
        values["high"] >= values["low"]
        and values["low"] <= values["open"] <= values["high"]
        and values["low"] <= values["close"] <= values["high"]
    )


def _observation(
    *,
    trading_date: date,
    true_range: float | None,
    atr: float | None,
    null_reason: str | None,
    valid_tr_count: int,
    bar: OHLCBar | None,
    suspended: bool,
) -> ATRObservation:
    return ATRObservation(
        trading_date=trading_date,
        true_range=true_range,
        atr=atr,
        null_reason=null_reason,
        valid_tr_count=valid_tr_count,
        bar_present=bar is not None,
        is_suspended=suspended,
        data_available_at=bar.data_available_at if bar else None,
    )


def calculate_atr14(
    bars: Iterable[OHLCBar | Mapping[str, Any]],
    *,
    price_basis: str,
    input_snapshot_ref: str,
    expected_sessions: Iterable[date | str | datetime] | None = None,
    decision_at: datetime | str | None = None,
    previous_close: Any = None,
    previous_close_basis: str | None = None,
    previous_close_source_ref: str | None = None,
    previous_close_available_at: datetime | str | None = None,
    true_sequence_start: bool = False,
    suspended_sessions: Iterable[date | str | datetime] | None = None,
    corporate_actions: Iterable[CorporateActionEvidence | Mapping[str, Any]] = (),
    corporate_action_coverage: str | None = None,
    corporate_action_source_ref: str | None = None,
    corporate_action_available_at: datetime | str | None = None,
) -> ATRArtifact:
    """Calculate an independent ATR14 Wilder artifact.

    ``expected_sessions`` is authoritative and required:
    a missing expected date is emitted as an explicit null observation and
    resets warm-up.  Confirmed dates in ``suspended_sessions`` preserve the
    last real close and ATR state without creating a zero-range bar.

    The first bar uses ``previous_close`` when supplied.  Without it, only an
    explicitly proven ``true_sequence_start`` may use ``high - low``.  After a
    gap, a row-level ``previous_close`` is required to reconnect continuity;
    the current close of an otherwise valid bar may become the next bar's
    previous close even when the current row's TR is null.
    """

    if not isinstance(input_snapshot_ref, str) or not input_snapshot_ref.strip():
        raise ValueError("input_snapshot_ref is required")
    if not isinstance(price_basis, str) or not price_basis.strip():
        raise ValueError("price_basis is required")
    if not isinstance(true_sequence_start, bool):
        raise ValueError("true_sequence_start must be a bool")

    if expected_sessions is None:
        raise ValueError("expected_sessions is required for session coverage validation")
    if decision_at is None:
        raise ValueError("decision_at is required for point-in-time validation")
    if not isinstance(corporate_action_coverage, str) or not corporate_action_coverage.strip():
        raise ValueError("corporate_action_coverage is required; do not assume no actions")
    if not isinstance(corporate_action_source_ref, str) or not corporate_action_source_ref.strip():
        raise ValueError("corporate_action_source_ref is required")

    declared_basis = price_basis.strip()
    declared_basis_key = _basis_key(declared_basis)
    decision_timestamp = _parse_timestamp(decision_at, "decision_at")
    assert decision_timestamp is not None
    decision_market_date = decision_timestamp.astimezone(MARKET_TIMEZONE).date()
    corporate_action_timestamp = _parse_timestamp(
        corporate_action_available_at,
        "corporate_action_available_at",
        required=True,
    )
    assert corporate_action_timestamp is not None
    global_action_issue = _corporate_action_coverage_issue(
        coverage=corporate_action_coverage.strip(),
        source_ref=corporate_action_source_ref,
        available_at=corporate_action_timestamp,
        decision_at=decision_timestamp,
    )
    initial_previous_close_timestamp = _parse_timestamp(
        previous_close_available_at,
        "previous_close_available_at",
    )

    normalized_bars = [_normalize_bar(bar) for bar in bars]
    bar_dates = [bar.trading_date for bar in normalized_bars]
    _validate_strictly_increasing(bar_dates, "bars")
    bars_by_date = {bar.trading_date: bar for bar in normalized_bars}

    session_dates = [_parse_date(value, "expected_sessions item") for value in expected_sessions]
    _validate_strictly_increasing(session_dates, "expected_sessions")
    expected_set = set(session_dates)
    extras = [trading_date for trading_date in bar_dates if trading_date not in expected_set]
    if extras:
        raise ValueError("bars cannot be paired with expected_sessions")
    output_dates = session_dates

    suspended_dates = {
        _parse_date(value, "suspended_sessions item")
        for value in (suspended_sessions or ())
    }
    if not suspended_dates.issubset(set(session_dates)):
        raise ValueError("suspended_sessions must be expected sessions")

    normalized_actions = [_normalize_action(action) for action in corporate_actions]
    for previous_action, current_action in zip(normalized_actions, normalized_actions[1:]):
        if current_action.action_date < previous_action.action_date:
            raise ValueError("corporate_actions must be ordered by action_date")
        if (
            current_action.action_date == previous_action.action_date
            and current_action.action_type == previous_action.action_type
        ):
            raise ValueError("corporate_actions must not contain duplicate action dates and types")
    action_artifacts = tuple(
        {
            "action_date": action.action_date.isoformat(),
            "action_type": action.action_type,
            "coverage": action.coverage,
            "price_basis": action.price_basis,
            "source_ref": action.source_ref,
            "available_at": action.available_at.isoformat() if action.available_at else None,
            "validation_issue": _action_issue(
                action,
                declared_basis=declared_basis,
                decision_at=decision_timestamp,
            ),
        }
        for action in normalized_actions
    )
    basis_action_issue = next(
        (
            action["validation_issue"]
            for action in action_artifacts
            if action["validation_issue"] is not None
        ),
        None,
    )
    action_coverage_artifact = {
        "coverage": corporate_action_coverage.strip(),
        "source_ref": corporate_action_source_ref.strip(),
        "available_at": corporate_action_timestamp.isoformat(),
        "validation_issue": global_action_issue,
    }

    observations: list[ATRObservation] = []
    valid_trs: list[float] = []
    running_atr: float | None = None
    state_previous_close: float | None = None
    continuity_broken = False
    has_seen_actual_bar = False

    initial_previous_close = _finite_positive(previous_close)
    initial_previous_close_issue = None
    if previous_close is not None:
        initial_previous_close_issue = _previous_close_issue(
            previous_close,
            basis=previous_close_basis,
            source_ref=previous_close_source_ref,
            available_at=initial_previous_close_timestamp,
            declared_basis=declared_basis,
            decision_at=decision_timestamp,
        )

    for index, trading_date in enumerate(output_dates):
        bar = bars_by_date.get(trading_date)
        explicitly_suspended = trading_date in suspended_dates
        is_suspended = explicitly_suspended or bool(bar and bar.is_suspended)

        if bar is None:
            if is_suspended:
                observations.append(
                    _observation(
                        trading_date=trading_date,
                        true_range=None,
                        atr=None,
                        null_reason="session_suspended",
                        valid_tr_count=min(len(valid_trs), PERIOD),
                        bar=None,
                        suspended=True,
                    )
                )
                continue
            valid_trs = []
            running_atr = None
            state_previous_close = None
            continuity_broken = True
            observations.append(
                _observation(
                    trading_date=trading_date,
                    true_range=None,
                    atr=None,
                    null_reason="missing_expected_session",
                    valid_tr_count=0,
                    bar=None,
                    suspended=False,
                )
            )
            continue

        if is_suspended:
            has_price_placeholder = bar is not None and any(
                value is not None for value in (bar.open, bar.high, bar.low, bar.close)
            )
            if has_price_placeholder:
                valid_trs = []
                running_atr = None
                state_previous_close = None
                continuity_broken = True
                observations.append(
                    _observation(
                        trading_date=trading_date,
                        true_range=None,
                        atr=None,
                        null_reason="suspension_price_conflict",
                        valid_tr_count=0,
                        bar=bar,
                        suspended=True,
                    )
                )
                continue
            observations.append(
                _observation(
                    trading_date=trading_date,
                    true_range=None,
                    atr=None,
                    null_reason="session_suspended",
                    valid_tr_count=min(len(valid_trs), PERIOD),
                    bar=bar,
                    suspended=True,
                )
            )
            continue

        first_actual_bar = not has_seen_actual_bar
        has_seen_actual_bar = True
        reason: str | None = None
        if declared_basis_key is None:
            reason = "unknown_price_basis"
        elif bar.price_basis is None or _basis_key(bar.price_basis) is None:
            reason = "unknown_price_basis"
        elif _basis_key(bar.price_basis) != declared_basis_key:
            reason = "inconsistent_price_basis"
        elif global_action_issue is not None:
            reason = global_action_issue
        elif basis_action_issue is not None:
            reason = basis_action_issue
        elif trading_date > decision_market_date:
            reason = "bar_after_decision_date"
        elif bar.data_available_at is None and decision_timestamp is not None:
            reason = "data_availability_unknown"
        elif (
            bar.data_available_at is not None
            and bar.data_available_at.astimezone(MARKET_TIMEZONE).date() < trading_date
        ):
            reason = "data_availability_before_session"
        elif (
            decision_timestamp is not None
            and bar.data_available_at is not None
            and bar.data_available_at > decision_timestamp
        ):
            reason = "data_not_available_at_decision"
        elif _invalid_ohlc(bar):
            reason = "invalid_ohlc"
        else:
            # The declared action set is the common basis evidence for the
            # whole artifact.  A late, partial, or mismatched action cannot
            # safely be applied only after its effective date because the
            # preceding seed may also depend on that same basis.
            reason = global_action_issue or basis_action_issue

        current_close = _finite_positive(bar.close)
        if reason is not None:
            valid_trs = []
            running_atr = None
            state_previous_close = None
            continuity_broken = True
            observations.append(
                _observation(
                    trading_date=trading_date,
                    true_range=None,
                    atr=None,
                    null_reason=reason,
                    valid_tr_count=0,
                    bar=bar,
                    suspended=False,
                )
            )
            continue

        # A valid current close is useful to the next row even when this row
        # cannot compute TR because its preceding close is unavailable.
        assert current_close is not None
        prior_close = state_previous_close
        used_sequence_start = False
        if prior_close is None and reason is None:
            if not continuity_broken and first_actual_bar and previous_close is not None:
                if initial_previous_close_issue is not None:
                    reason = initial_previous_close_issue
                else:
                    assert initial_previous_close is not None
                    prior_close = initial_previous_close
            elif bar.previous_close is not None:
                row_previous_close = _finite_positive(bar.previous_close)
                row_previous_close_issue = _previous_close_issue(
                    bar.previous_close,
                    basis=bar.previous_close_basis,
                    source_ref=bar.previous_close_source_ref,
                    available_at=bar.previous_close_available_at,
                    declared_basis=declared_basis,
                    decision_at=decision_timestamp,
                )
                if row_previous_close_issue is not None:
                    reason = row_previous_close_issue
                else:
                    assert row_previous_close is not None
                    prior_close = row_previous_close
            elif not continuity_broken and first_actual_bar and true_sequence_start:
                used_sequence_start = True
            else:
                reason = "missing_previous_close"

        true_range: float | None = None
        atr: float | None = None
        if reason is None:
            high = _finite_positive(bar.high)
            low = _finite_positive(bar.low)
            if prior_close is None:
                true_range = high - low
            else:
                true_range = max(high - low, abs(high - prior_close), abs(low - prior_close))
            valid_trs.append(true_range)
            if len(valid_trs) == PERIOD:
                # Divide before fsum so a legal set of large finite TR values
                # cannot overflow merely while forming the arithmetic mean.
                running_atr = math.fsum(value / PERIOD for value in valid_trs)
                atr = running_atr
            elif len(valid_trs) > PERIOD:
                assert running_atr is not None
                running_atr = running_atr + (true_range - running_atr) / PERIOD
                atr = running_atr
            else:
                atr = None
        else:
            valid_trs = []
            running_atr = None
            continuity_broken = True

        # Preserve a valid close for the next row when only the prior-close
        # requirement prevented this row from contributing a TR.
        state_previous_close = current_close
        if reason is None and atr is None:
            reason = "warmup_incomplete"
        observations.append(
            _observation(
                trading_date=trading_date,
                true_range=true_range,
                atr=atr,
                null_reason=reason,
                valid_tr_count=min(len(valid_trs), PERIOD),
                bar=bar,
                suspended=False,
            )
        )

    return ATRArtifact(
        feature_version=FEATURE_VERSION,
        algorithm=ALGORITHM,
        period=PERIOD,
        input_snapshot_ref=input_snapshot_ref.strip(),
        price_basis=declared_basis,
        decision_at=decision_timestamp,
        observations=tuple(observations),
        corporate_actions=action_artifacts,
        corporate_action_coverage=action_coverage_artifact,
    )


compute_atr14 = calculate_atr14
calculate_atr = calculate_atr14

__all__ = [
    "ALGORITHM",
    "FEATURE_VERSION",
    "KNOWN_PRICE_BASES",
    "PERIOD",
    "ATRArtifact",
    "ATRObservation",
    "CorporateActionEvidence",
    "OHLCBar",
    "calculate_atr",
    "calculate_atr14",
    "compute_atr14",
]
