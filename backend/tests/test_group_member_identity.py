"""Canonical group-member return lookup and strict legacy compatibility.
Run directly with unittest/runpy and explicit isolated STOCK_* paths; this
avoids the repository pytest conftest's additional disk fixtures.
"""

from datetime import date, timedelta
from copy import deepcopy
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import MIN_GROUP_MEMBERS
from app.db import Base, enable_sqlite_foreign_keys
from app.models import (
    ChipSnapshot, GroupDailyScore, GroupMembership, Instrument, MarketBar,
    Signal, TechnicalFeature, ThemeGroup,
)
from worker import pipeline


class EvaluationObserver:
    """Observe the actual evaluator calls without replacing any calculation."""

    def __init__(self):
        self.inputs = {}
        self.results = {}

    def before(self, key, arguments):
        self.inputs[key] = dict(arguments)

    def after(self, key, result):
        self.results[key] = result

    def persist(self, db, **kwargs):
        pass


class GroupMemberIdentityTest(unittest.TestCase):
    def run_case(self, exchanges, duplicate_symbol=True, legacy=False, mutate=None,
                 rejected=False, before_calculation=None, extra_member=False, group_available=True):
        engine = create_engine("sqlite:///:memory:")
        enable_sqlite_foreign_keys(engine)
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                score_date = date(2026, 9, 4)
                dates = pipeline.business_days(score_date, 21)
                benchmark = Instrument(exchange="TWSE", symbol="TAIEX", name="TAIEX", instrument_type="index")
                stocks = [Instrument(exchange=exchange, symbol="SAME" if duplicate_symbol else exchange,
                                     name=exchange, instrument_type="stock") for exchange in exchanges]
                stocks.append(Instrument(exchange="TWSE", symbol="THIRD", name="Third", instrument_type="stock"))
                if extra_member:
                    stocks.append(Instrument(exchange="TWSE", symbol="FOURTH", name="Fourth", instrument_type="stock"))
                db.add_all([benchmark, *stocks])
                db.flush()
                group = ThemeGroup(id="identity-diagnostic", name="Identity diagnostic", group_type="official_industry")
                db.add(group)
                db.flush()
                for stock in stocks:
                    db.add(GroupMembership(group_id=group.id, instrument_id=stock.id, valid_from=dates[0], source="memory-fixture"))
                slopes = {"TWSE": 1.0, "TPEX": -0.5}
                expected = {}
                for stock in stocks:
                    slope = 0.25 if stock.symbol in {"THIRD", "FOURTH"} else slopes[stock.exchange]
                    expected[stock.id] = slope * 20 / 100
                    for index, day in enumerate(dates):
                        close = 100 + slope * index
                        db.add(MarketBar(instrument_id=stock.id, trading_date=day, open=close,
                                         high=close + 1, low=close - 1, close=close, adj_close=close,
                                         volume=1000, turnover=100000, source="memory-fixture"))
                        db.add(ChipSnapshot(instrument_id=stock.id, trading_date=day,
                                            foreign_buy=100, trust_buy=20, dealer_buy=10,
                                            margin_balance=10000, margin_change=0, source="memory-fixture"))
                    db.add(TechnicalFeature(instrument_id=stock.id, trading_date=score_date,
                                            features_json={"prior_20_volumes": [1000] * 20,
                                                           "prior_20_highs": [99] * 20,
                                                           "volume": 1000, "bar_count_60d": 60,
                                                           "ma20": 95, "ma60": 90, "atr14": 2}, source="memory-fixture"))
                for day in dates:
                    db.add(MarketBar(instrument_id=benchmark.id, trading_date=day, open=100,
                                     high=101, low=99, close=100, adj_close=100, volume=0,
                                     turnover=0, source="memory-fixture"))
                db.flush()
                if before_calculation:
                    before_calculation(db, stocks, group, score_date)
                    db.flush()
                pipeline._calculate_group_scores(db, score_date)
                db.flush()
                db.expire_all()  # Read the JSON back through SQLAlchemy, not the Python list.
                score = db.scalar(select(GroupDailyScore))
                self.assertGreaterEqual(score.eligible_members, MIN_GROUP_MEMBERS)
                rows = score.details_json["member_returns"]
                self.assertGreaterEqual(len(rows), 3)
                self.assertEqual(score.details_json["member_return_identity_version"], "instrument-id-v1")
                self.assertTrue(all(type(row["instrument_id"]) is int and row["exchange"] for row in rows))
                if legacy:
                    details = deepcopy(score.details_json)
                    details.pop("member_return_identity_version")
                    for row in details["member_returns"]:
                        row.pop("instrument_id")
                        row.pop("exchange")
                    score.details_json = details
                if mutate:
                    mutate(db, score, stocks, group, score_date)
                db.flush()
                strategies = pipeline._ensure_strategies(db)
                db.flush()
                actual = {}
                for stock in (stocks[:1] if mutate or before_calculation else stocks):
                    selected_group = pipeline._best_group_for_signal(db, stock.id, score_date)
                    if group_available:
                        self.assertEqual(selected_group.group_id, group.id)
                    else:
                        self.assertIsNone(selected_group)
                    observer = EvaluationObserver()
                    self.assertTrue(pipeline._upsert_signal_for_strategy(
                        db, instrument=stock, signal_date=score_date, strategies=strategies,
                        strategy_key="breakout_v1", capture=observer))
                    db.flush()
                    actual[stock.id] = observer.inputs["breakout_v1"]["group_excess_return_20d"]
                    self.assertEqual(actual[stock.id], observer.inputs["pullback_v1"]["group_excess_return_20d"])
                    self.assertEqual(set(observer.results), {"breakout_v1", "pullback_v1"})
                    signal = db.scalar(select(Signal).where(Signal.instrument_id == stock.id))
                    self.assertEqual(signal.rule_evidence_json["inputs"]["group_excess_return_20d"], actual[stock.id])
                    audit = signal.rule_evidence_json["group_member_return_lookup"]
                    self.assertEqual(audit["version"], "group-member-return-lookup/v1")
                    self.assertEqual(audit["group_id"], group.id if group_available else None)
                    self.assertEqual(audit["group_score_date"], score_date.isoformat() if group_available else None)
                    self.assertEqual(audit["requested"], {"instrument_id": stock.id, "exchange": stock.exchange, "symbol": stock.symbol})
                    if rejected:
                        self.assertIsNone(actual[stock.id])
                        self.assertIsNone(audit["matched"])
                        self.assertEqual(audit["mode"], "rejected")
                        self.assertEqual(signal.status, "data_incomplete")
                        self.assertIn("group_excess_return_20d_missing_or_non_finite", signal.rationale)
                    else:
                        self.assertAlmostEqual(actual[stock.id], expected[stock.id])
                        self.assertEqual(audit["matched"], audit["requested"])
                        self.assertEqual(audit["mode"], "legacy_symbol_unique" if legacy else "instrument_id")
                        self.assertEqual(audit["reason"], "matched")
                if not mutate and not before_calculation:
                    print({"order": exchanges, "duplicate_symbol": duplicate_symbol,
                       "eligible_members": score.eligible_members,
                       "expected": {s.exchange + ":" + s.symbol: expected[s.id] for s in stocks},
                       "actual": {s.exchange + ":" + s.symbol: actual[s.id] for s in stocks if s.id in actual},
                       "candidate_symbols": score.details_json["candidate_symbols"]})
        finally:
            engine.dispose()

    def test_duplicate_symbol_twse_first(self):
        self.run_case(["TWSE", "TPEX"])

    def test_duplicate_symbol_tpex_first(self):
        self.run_case(["TPEX", "TWSE"])

    def test_unique_legacy_symbols_remain_resolvable(self):
        self.run_case(["TWSE", "TPEX"], duplicate_symbol=False, legacy=True)

    def test_legacy_duplicate_symbol_rejected(self):
        self.run_case(["TWSE", "TPEX"], legacy=True, rejected=True,
                      mutate=lambda *args: None)

    def test_technical_exclusion_does_not_make_legacy_identity_unique(self):
        def exclude(db, stocks, group, day):
            feature = db.scalar(select(TechnicalFeature).where(
                TechnicalFeature.instrument_id == stocks[1].id))
            feature.features_json = {}
        self.run_case(["TWSE", "TPEX"], legacy=True, rejected=True,
                      before_calculation=exclude, extra_member=True)

    def test_canonical_malformed_evidence_rejected(self):
        def edit(change):
            def mutate(db, score, stocks, group, day):
                details = deepcopy(score.details_json)
                change(details, stocks)
                score.details_json = details
            return mutate
        changes = {
            "missing_id": lambda d, s: d["member_returns"][0].pop("instrument_id"),
            "bool_id": lambda d, s: d["member_returns"][0].update(instrument_id=True),
            "string_id": lambda d, s: d["member_returns"][0].update(instrument_id=str(s[0].id)),
            "float_id": lambda d, s: d["member_returns"][0].update(instrument_id=float(s[0].id)),
            "zero_id": lambda d, s: d["member_returns"][0].update(instrument_id=0),
            "duplicate": lambda d, s: d["member_returns"].append(dict(d["member_returns"][0])),
            "exchange_conflict": lambda d, s: d["member_returns"][0].update(exchange="OTHER"),
            "symbol_conflict": lambda d, s: d["member_returns"][0].update(symbol="OTHER"),
            "unknown_version": lambda d, s: d.update(member_return_identity_version="future"),
            "null_version": lambda d, s: d.update(member_return_identity_version=None),
            "unversioned": lambda d, s: d.pop("member_return_identity_version"),
            "mixed": lambda d, s: d["member_returns"][1].pop("exchange"),
            "missing_target": lambda d, s: d["member_returns"].pop(0),
            "invalid_rows": lambda d, s: d.update(member_returns={}),
            "invalid_row": lambda d, s: d["member_returns"].append(None),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                self.run_case(["TWSE", "TPEX"], mutate=edit(change), rejected=True)

    def test_technically_excluded_target_never_borrows_other_exchange_return(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                def exclude_target(db, stocks, group, day):
                    feature = db.scalar(select(TechnicalFeature).where(
                        TechnicalFeature.instrument_id == stocks[0].id))
                    feature.features_json = {}
                self.run_case(["TWSE", "TPEX"], legacy=legacy, rejected=True,
                              before_calculation=exclude_target, extra_member=True)

    def test_return_types_and_finiteness(self):
        for legacy in (False, True):
            for value in (True, "0.2", None, float("nan"), float("inf"), -float("inf")):
                with self.subTest(legacy=legacy, value=value):
                    def mutate(db, score, stocks, group, day):
                        details = deepcopy(score.details_json)
                        details["member_returns"][0]["excess_return_20d"] = value
                        score.details_json = details
                    self.run_case(["TWSE", "TPEX"], duplicate_symbol=False,
                                  legacy=legacy, mutate=mutate, rejected=True)

    def test_legacy_effective_membership_boundaries(self):
        for boundary, ambiguous in (("starts_today", True), ("ends_today", True),
                                    ("starts_tomorrow", False), ("ended_yesterday", False)):
            with self.subTest(boundary=boundary):
                def membership(db, stocks, group, day):
                    member = db.scalar(select(GroupMembership).where(
                        GroupMembership.instrument_id == stocks[1].id))
                    if boundary == "starts_today":
                        member.valid_from = day
                    elif boundary == "ends_today":
                        member.valid_to = day
                    elif boundary == "starts_tomorrow":
                        member.valid_from = day + timedelta(days=1)
                    else:
                        member.valid_to = day - timedelta(days=1)
                self.run_case(["TWSE", "TPEX"], legacy=True, rejected=ambiguous,
                              before_calculation=membership, extra_member=True)

    def test_legacy_duplicate_return_and_wrong_group_rejected(self):
        for wrong_group in (False, True):
            def mutate(db, score, stocks, group, day):
                if wrong_group:
                    other = ThemeGroup(id="other", name="Other", group_type="official_industry")
                    db.add(other)
                    db.flush()
                    # Resolver must check the score's own group, never a global symbol match.
                    copied = GroupDailyScore(group_id=other.id, trading_date=day,
                                             details_json=score.details_json)
                    value, audit = pipeline._resolve_group_member_return(db, copied, stocks[0], day)
                    self.assertIsNone(value)
                    self.assertEqual(audit["reason"], "legacy_membership_ambiguous_or_missing")
                else:
                    details = deepcopy(score.details_json)
                    details["member_returns"].append(dict(details["member_returns"][0]))
                    score.details_json = details
            self.run_case(["TWSE", "TPEX"], duplicate_symbol=False, legacy=True,
                          mutate=mutate, rejected=not wrong_group)

    def test_nonmember_and_wrong_date_do_not_use_group_evidence(self):
        for condition in ("nonmember", "future_membership", "inactive_group", "wrong_date"):
            with self.subTest(condition=condition):
                def mutate(db, score, stocks, group, day):
                    if condition in ("nonmember", "future_membership"):
                        member = db.scalar(select(GroupMembership).where(
                            GroupMembership.instrument_id == stocks[0].id))
                        if condition == "nonmember":
                            db.delete(member)
                        else:
                            member.valid_from = day + timedelta(days=1)
                    elif condition == "inactive_group":
                        group.active = False
                    else:
                        score.trading_date = day - timedelta(days=1)
                self.run_case(["TWSE", "TPEX"], mutate=mutate, rejected=True, group_available=False)

    def test_legacy_partial_identity_and_disallowed_member_rejected(self):
        for condition in ("partial_id", "partial_exchange", "disallowed_type"):
            with self.subTest(condition=condition):
                def mutate(db, score, stocks, group, day):
                    if condition == "disallowed_type":
                        stocks[0].instrument_type = "index"
                    else:
                        details = deepcopy(score.details_json)
                        details["member_returns"][0].update(
                            {"instrument_id": stocks[0].id} if condition == "partial_id" else {"exchange": "TWSE"})
                        score.details_json = details
                self.run_case(["TWSE", "TPEX"], duplicate_symbol=False, legacy=True,
                              mutate=mutate, rejected=True)

    def test_finite_integer_return_is_accepted(self):
        def mutate(db, score, stocks, group, day):
            details = deepcopy(score.details_json)
            details["member_returns"][0]["excess_return_20d"] = 0
            score.details_json = details
            value, audit = pipeline._resolve_group_member_return(db, score, stocks[0], day)
            self.assertEqual(value, 0)
            self.assertEqual(audit["reason"], "matched")
            details["member_returns"][0]["excess_return_20d"] = 0.2
        self.run_case(["TWSE", "TPEX"], mutate=mutate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
