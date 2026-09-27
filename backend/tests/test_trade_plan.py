"""In-memory contract tests for the detached caller-input trade-plan core."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, ROUND_DOWN, getcontext, localcontext

from app.trade_plan import (
    EXECUTION_VERSION,
    TRADE_PLAN_VERSION,
    TradePlanInputError,
    calculate_trade_plan,
)


TPE = timezone(timedelta(hours=8))


def d(value: str) -> Decimal:
    return Decimal(value)


def plan_inputs() -> dict[str, object]:
    return {
        "side": "long",
        "trigger_rule": "high_at_or_above",
        "trigger_price": d("100.01"),
        "confirmation_rule": "close_at_or_above",
        "confirmation_price": d("100.02"),
        "entry_rule": "caller_session_open",
        "entry_min": d("100.01"),
        "entry_max": d("101.09"),
        "no_chase_cap": d("100.89"),
        "invalidation_rule": "session_low_at_or_below",
        "invalid_price": d("95.09"),
        "target_1": d("103.09"),
        "target_2": d("108.09"),
        "tick_rule": "constant_tick",
        "tick_size": d("0.1"),
        "entry_fee_rate": d("0.001"),
        "exit_fee_rate": d("0.001"),
        "exit_tax_rate": d("0.003"),
        "entry_slippage_ticks": 1,
        "exit_slippage_ticks": 1,
        "minimum_volume": 500,
        "minimum_turnover": d("50000"),
        "decision_at": datetime(2026, 9, 24, 14, 0, tzinfo=TPE),
        "earliest_execution_at": datetime(2026, 9, 25, 9, 0, tzinfo=TPE),
        "expires_at": datetime(2026, 10, 1, 13, 30, tzinfo=TPE),
        "invalidation_event_key": "material_announcement",
    }


def observed_inputs() -> dict[str, object]:
    return {
        "trigger_high": d("100.2"),
        "trigger_at": datetime(2026, 9, 24, 13, 0, tzinfo=TPE),
        "confirmation_close": d("100.1"),
        "confirmation_at": datetime(2026, 9, 24, 13, 30, tzinfo=TPE),
        "session_open_reference_price": d("100.2"),
        "session_started_at": datetime(2026, 9, 25, 9, 0, tzinfo=TPE),
        "session_ended_at": datetime(2026, 9, 25, 13, 30, tzinfo=TPE),
        "assessed_at": datetime(2026, 9, 25, 14, 0, tzinfo=TPE),
        "session_high": d("102.0"),
        "session_low": d("99.0"),
        "volume": 1000,
        "turnover": d("100000"),
        "halted": False,
        "event_state": "clear",
        "event_at": None,
    }


class TradePlanTests(unittest.TestCase):
    def test_hypothetical_plan_has_independent_versions_and_conservative_levels(self) -> None:
        plan = plan_inputs()
        observed = observed_inputs()
        result = calculate_trade_plan(plan, observed)

        self.assertEqual(result["status"], "hypothetical_candidate_feasible")
        self.assertIsNone(result["reason"])
        self.assertEqual(result["evaluation_scope"], "post_session_hypothetical")
        self.assertEqual(result["point_in_time_status"], "not_asserted")
        self.assertEqual(result["fill_status"], "not_asserted")
        self.assertNotIn("execution_at", result)
        self.assertEqual(result["hypothetical_open_reference_at"], observed["session_started_at"])
        self.assertEqual(result["assessed_at"], observed["assessed_at"])
        self.assertEqual(result["candidate_feasibility"], "feasible")
        self.assertEqual(result["trade_plan_version"], TRADE_PLAN_VERSION)
        self.assertEqual(result["execution_version"], EXECUTION_VERSION)
        self.assertEqual(result["tick"], {"rule": "constant_tick", "size": d("0.1")})
        self.assertEqual(result["trigger"]["price"], d("100.1"))
        self.assertTrue(result["trigger"]["met"])
        self.assertEqual(result["confirmation"]["price"], d("100.1"))
        self.assertTrue(result["confirmation"]["met"])
        self.assertEqual(result["entry"]["min"], d("100.1"))
        self.assertEqual(result["entry"]["max"], d("101.0"))
        self.assertEqual(result["entry"]["no_chase_cap"], d("100.8"))
        self.assertEqual(result["entry"]["hypothetical_entry_after_slippage"], d("100.3"))
        self.assertEqual(result["invalidation"]["price"], d("95.0"))
        self.assertEqual(result["targets"], {"target_1": d("103.0"), "target_2": d("108.0")})
        self.assertTrue(
            result["invalidation"]["price"]
            < result["entry"]["hypothetical_entry_after_slippage"]
            < result["targets"]["target_1"]
            < result["targets"]["target_2"]
        )
        self.assertEqual(result["costs"]["hypothetical_target_1_cost_space_per_unit"], d("2.0881"))
        self.assertEqual(result["earliest_execution_at"], plan["earliest_execution_at"])
        self.assertEqual(result["post_session_touches"], {"classification": "no_level_touched", "invalidation_touched": False, "target_1_touched": False, "target_2_touched": False})
        self.assertEqual(plan, plan_inputs())
        self.assertEqual(observed, observed_inputs())

    def test_trigger_and_confirmation_are_both_required(self) -> None:
        observed = observed_inputs()
        observed["trigger_high"] = d("100.0")
        self.assertEqual(calculate_trade_plan(plan_inputs(), observed)["reason"], "trigger_not_met")
        observed["trigger_high"] = d("100.2")
        observed["confirmation_close"] = d("100.0")
        result = calculate_trade_plan(plan_inputs(), observed)
        self.assertEqual((result["status"], result["reason"]), ("pending", "confirmation_not_met"))

    def test_tick_rounding_collapse_rejects_even_with_raw_separation(self) -> None:
        plan = plan_inputs()
        plan["target_1"] = d("100.19")
        result = calculate_trade_plan(plan, observed_inputs())
        self.assertEqual((result["status"], result["reason"]), ("rejected", "rounded_levels_not_strictly_ordered"))
        plan = plan_inputs()
        plan["no_chase_cap"] = d("100.09")
        self.assertEqual(calculate_trade_plan(plan, observed_inputs())["reason"], "rounded_levels_not_strictly_ordered")

    def test_next_session_gap_and_slippage_over_cap_reject(self) -> None:
        observed = observed_inputs()
        observed["session_open_reference_price"] = d("101.0")
        result = calculate_trade_plan(plan_inputs(), observed)
        self.assertEqual((result["status"], result["reason"]), ("rejected_gap", "opening_plus_slippage_above_entry_cap"))
        observed["session_open_reference_price"] = d("100.8")
        result = calculate_trade_plan(plan_inputs(), observed)
        self.assertEqual(result["status"], "rejected_gap")
        self.assertEqual(result["entry"]["hypothetical_entry_after_slippage"], d("100.9"))
        observed["session_open_reference_price"] = d("100.0")
        result = calculate_trade_plan(plan_inputs(), observed)
        self.assertEqual((result["status"], result["reason"]), ("rejected_gap", "opening_below_entry_range"))

    def test_cost_space_and_nonpositive_net_target_reject(self) -> None:
        plan = plan_inputs()
        plan["entry_fee_rate"] = d("0.05")
        result = calculate_trade_plan(plan, observed_inputs())
        self.assertEqual((result["status"], result["reason"]), ("rejected", "target_1_cost_space_insufficient"))
        self.assertLessEqual(result["costs"]["hypothetical_target_1_cost_space_per_unit"], 0)

    def test_liquidity_halt_and_unknown_event_fail_closed(self) -> None:
        for field, value, reason in (
            ("volume", 499, "insufficient_liquidity"),
            ("turnover", d("49999"), "insufficient_liquidity"),
            ("halted", True, "halted"),
            ("event_state", "unknown", "event_state_unknown"),
        ):
            with self.subTest(field=field):
                observed = observed_inputs()
                observed[field] = value
                result = calculate_trade_plan(plan_inputs(), observed)
                self.assertEqual((result["status"], result["reason"]), ("rejected", reason))

    def test_expiry_event_and_earliest_execution(self) -> None:
        observed = observed_inputs()
        observed["event_state"] = "occurred"
        observed["event_at"] = datetime(2026, 9, 24, 17, 0, tzinfo=TPE)
        self.assertEqual(calculate_trade_plan(plan_inputs(), observed)["reason"], "invalidation_event_before_session")

        plan = plan_inputs()
        expired_observed = observed_inputs()
        expired_observed["session_started_at"] = datetime(2026, 9, 25, 9, 5, tzinfo=TPE)
        plan["expires_at"] = datetime(2026, 9, 25, 9, 1, tzinfo=TPE)
        self.assertEqual(calculate_trade_plan(plan, expired_observed)["reason"], "plan_expired_before_session")

        observed = observed_inputs()
        observed["session_started_at"] = datetime(2026, 9, 24, 15, 0, tzinfo=TPE)
        observed["session_ended_at"] = datetime(2026, 9, 24, 16, 0, tzinfo=TPE)
        observed["assessed_at"] = datetime(2026, 9, 24, 17, 0, tzinfo=TPE)
        result = calculate_trade_plan(plan_inputs(), observed)
        self.assertEqual((result["status"], result["reason"]), ("pending", "before_earliest_execution"))

    def test_same_session_stop_and_target_is_incomparable(self) -> None:
        observed = observed_inputs()
        observed["session_low"] = d("95.0")
        observed["session_high"] = d("108.0")
        result = calculate_trade_plan(plan_inputs(), observed)
        self.assertEqual((result["status"], result["reason"]), ("incomparable", "same_session_stop_target_order_unknown"))
        self.assertEqual(result["post_session_touches"], {"classification": "stop_target_order_unknown", "invalidation_touched": True, "target_1_touched": True, "target_2_touched": True})

    def test_target_touches_are_observations_not_exits(self) -> None:
        for high, classification, target_2_touched in (
            (d("103.0"), "target_1_touched", False),
            (d("108.0"), "target_1_and_2_touched", True),
        ):
            with self.subTest(high=high):
                observed = observed_inputs()
                observed["session_high"] = high
                result = calculate_trade_plan(plan_inputs(), observed)
                self.assertEqual(result["status"], "hypothetical_candidate_feasible")
                self.assertEqual(result["candidate_feasibility"], "feasible")
                self.assertEqual(result["post_session_touches"], {
                    "classification": classification,
                    "invalidation_touched": False,
                    "target_1_touched": True,
                    "target_2_touched": target_2_touched,
                })
                self.assertEqual(result["fill_status"], "not_asserted")

    def test_in_session_expiry_and_event_are_incomparable(self) -> None:
        for expires_at in (
            datetime(2026, 9, 25, 10, 0, tzinfo=TPE),
            datetime(2026, 9, 25, 13, 30, tzinfo=TPE),
        ):
            with self.subTest(expires_at=expires_at):
                plan = plan_inputs()
                plan["expires_at"] = expires_at
                result = calculate_trade_plan(plan, observed_inputs())
                self.assertEqual((result["status"], result["reason"]), ("incomparable", "expiry_within_session_order_unknown"))
                self.assertEqual(result["post_session_touches"]["classification"], "not_assessed")

        for event_at in (
            datetime(2026, 9, 25, 9, 0, tzinfo=TPE),
            datetime(2026, 9, 25, 10, 0, tzinfo=TPE),
            datetime(2026, 9, 25, 13, 30, tzinfo=TPE),
        ):
            with self.subTest(event_at=event_at):
                observed = observed_inputs()
                observed["event_state"] = "occurred"
                observed["event_at"] = event_at
                result = calculate_trade_plan(plan_inputs(), observed)
                self.assertEqual((result["status"], result["reason"]), ("incomparable", "invalidation_event_within_session_order_unknown"))
                self.assertEqual(result["post_session_touches"]["classification"], "not_assessed")

    def test_assessment_time_requires_complete_session(self) -> None:
        observed = observed_inputs()
        observed["assessed_at"] = observed["session_ended_at"]
        self.assertEqual(calculate_trade_plan(plan_inputs(), observed)["status"], "hypothetical_candidate_feasible")
        observed["assessed_at"] = datetime(2026, 9, 25, 13, 29, tzinfo=TPE)
        with self.assertRaisesRegex(TradePlanInputError, "session_time:invalid_order_or_incomplete"):
            calculate_trade_plan(plan_inputs(), observed)
        observed = observed_inputs()
        observed["session_ended_at"] = observed["session_started_at"]
        with self.assertRaisesRegex(TradePlanInputError, "session_time:invalid_order_or_incomplete"):
            calculate_trade_plan(plan_inputs(), observed)

    def test_fixed_decimal_context_and_bounded_numeric_inputs(self) -> None:
        baseline = calculate_trade_plan(plan_inputs(), observed_inputs())
        with localcontext() as ambient:
            ambient.prec = 6
            ambient.rounding = ROUND_DOWN
            ambient.Emin = -9
            ambient.Emax = 9
            ambient.traps[Inexact] = True
            self.assertEqual(getcontext().prec, 6)
            self.assertEqual(calculate_trade_plan(plan_inputs(), observed_inputs()), baseline)
            self.assertEqual(getcontext().prec, 6)

        for field, value in (
            ("entry_min", d("1E+13")),
            ("entry_min", d("0.000000001")),
            ("entry_slippage_ticks", 1_000_001),
        ):
            with self.subTest(field=field, value=value):
                plan = plan_inputs()
                plan[field] = value
                with self.assertRaises(TradePlanInputError):
                    calculate_trade_plan(plan, observed_inputs())

    def test_stop_without_target_invalidates(self) -> None:
        observed = observed_inputs()
        observed["session_low"] = d("95.0")
        result = calculate_trade_plan(plan_inputs(), observed)
        self.assertEqual((result["status"], result["reason"]), ("hypothetical_invalidation_touched", "invalidation_price_touched"))
        self.assertEqual(result["post_session_touches"], {"classification": "invalidation_touched", "invalidation_touched": True, "target_1_touched": False, "target_2_touched": False})

    def test_missing_unknown_unsupported_and_invalid_types_raise(self) -> None:
        cases: list[tuple[str, dict[str, object], dict[str, object]]] = []
        plan = plan_inputs()
        del plan["tick_size"]
        cases.append(("missing_tick", plan, observed_inputs()))
        plan = plan_inputs()
        del plan["entry_fee_rate"]
        cases.append(("missing_cost", plan, observed_inputs()))
        plan = plan_inputs()
        plan["mystery"] = d("1")
        cases.append(("unknown_plan_field", plan, observed_inputs()))
        plan = plan_inputs()
        plan["tick_rule"] = "official_default"
        cases.append(("unsupported_tick_rule", plan, observed_inputs()))
        plan = plan_inputs()
        plan["side"] = "short"
        cases.append(("unsupported_side", plan, observed_inputs()))
        plan = plan_inputs()
        plan["entry_min"] = True
        cases.append(("bool_price", plan, observed_inputs()))
        plan = plan_inputs()
        plan["target_1"] = d("NaN")
        cases.append(("nan", plan, observed_inputs()))
        plan = plan_inputs()
        plan["target_2"] = d("Infinity")
        cases.append(("infinity", plan, observed_inputs()))
        plan = plan_inputs()
        plan["entry_fee_rate"] = 0.001
        cases.append(("float_rate", plan, observed_inputs()))
        plan = plan_inputs()
        plan["minimum_volume"] = True
        cases.append(("bool_volume", plan, observed_inputs()))
        plan = plan_inputs()
        plan["decision_at"] = datetime(2026, 9, 24, 14, 0)
        cases.append(("naive_decision", plan, observed_inputs()))
        observed = observed_inputs()
        observed["halted"] = None
        cases.append(("unknown_halt", plan_inputs(), observed))
        observed = observed_inputs()
        observed["session_open_reference_price"] = d("100.25")
        cases.append(("off_tick_open", plan_inputs(), observed))
        observed = observed_inputs()
        observed["event_state"] = "occurred"
        cases.append(("missing_event_time", plan_inputs(), observed))
        observed = observed_inputs()
        del observed["volume"]
        cases.append(("missing_liquidity", plan_inputs(), observed))

        for label, plan, observed in cases:
            with self.subTest(label=label):
                with self.assertRaises(TradePlanInputError):
                    calculate_trade_plan(plan, observed)

    def test_invalid_time_order_and_observation_shape_raise(self) -> None:
        plan = plan_inputs()
        plan["earliest_execution_at"] = plan["decision_at"]
        with self.assertRaisesRegex(TradePlanInputError, "plan_time:invalid_order"):
            calculate_trade_plan(plan, observed_inputs())

        observed = observed_inputs()
        observed["session_high"] = d("100.0")
        with self.assertRaisesRegex(TradePlanInputError, "session:open_outside_high_low"):
            calculate_trade_plan(plan_inputs(), observed)

        observed = observed_inputs()
        observed["event_state"] = "occurred"
        observed["event_at"] = datetime(2026, 9, 25, 15, 0, tzinfo=TPE)
        with self.assertRaisesRegex(TradePlanInputError, "event_at:after_assessment"):
            calculate_trade_plan(plan_inputs(), observed)


if __name__ == "__main__":
    unittest.main()
