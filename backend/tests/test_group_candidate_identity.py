"""Candidate identity through the real producer and decision projection.

Run via unittest/runpy with -B and isolated STOCK_* paths. All database
fixtures use SQLite memory; do not invoke the disk-producing pytest conftest.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import date, timedelta
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import Base, enable_sqlite_foreign_keys
from app.decision import prioritized_instrument_ids
from app.models import (
    ChipSnapshot, Event, GroupDailyScore, GroupMembership, Instrument,
    MarketBar, PortfolioPosition, Signal, StrategyVersion, TechnicalFeature, ThemeGroup,
)
from worker import pipeline


class GroupCandidateIdentityTest(unittest.TestCase):
    @contextmanager
    def fixture(self, duplicate=True, reverse=False, both_selected=False, kind="stock", category=None):
        engine = create_engine("sqlite:///:memory:")
        enable_sqlite_foreign_keys(engine)
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                day = date(2026, 9, 4)
                dates = pipeline.business_days(day, 21)
                specs = [("TWSE", "SAME", 1), ("TPEX", "SAME" if duplicate else "OTHER", .9 if both_selected else -.5),
                         ("TWSE", "A", .8), ("TWSE", "B", .6), ("TWSE", "C", .4)]
                if reverse:
                    specs.reverse()
                benchmark = Instrument(exchange="TWSE", symbol="TAIEX", name="Index", instrument_type="index")
                db.add(benchmark)
                stocks = [(Instrument(exchange=e, symbol=s, name=s, instrument_type=kind, etf_category=category), slope)
                          for e, s, slope in specs]
                db.add_all([stock for stock, _ in stocks])
                db.flush()
                group = ThemeGroup(id="candidate-identity", name="Candidate identity",
                                   group_type="etf" if kind == "etf" else "official_industry")
                db.add(group)
                db.flush()
                for stock, slope in stocks:
                    db.add(GroupMembership(group_id=group.id, instrument_id=stock.id,
                                           valid_from=dates[0], source="memory-fixture"))
                    for index, trading_day in enumerate(dates):
                        close = 100 + slope * index
                        db.add(MarketBar(instrument_id=stock.id, trading_date=trading_day, open=close,
                                         high=close + 1, low=close - 1, close=close, adj_close=close,
                                         volume=1000, turnover=100000, turnover_status="available",
                                         source="memory-fixture"))
                        db.add(ChipSnapshot(instrument_id=stock.id, trading_date=trading_day,
                                            foreign_buy=100, trust_buy=20, dealer_buy=10,
                                            margin_balance=10000, margin_change=0, source="memory-fixture"))
                    db.add(TechnicalFeature(instrument_id=stock.id, trading_date=day,
                                            features_json={"prior_20_volumes": [1000] * 20, "volume": 1000},
                                            source="memory-fixture"))
                instruments = {stock.exchange + ":" + stock.symbol: stock for stock, _ in stocks}
                # Inside the catalyst window but outside decision's event bucket.
                db.add(Event(instrument_id=instruments["TWSE:SAME"].id, event_date=dates[2],
                             event_type="fixture", title="Memory catalyst", source="issuer_filing"))
                for trading_day in dates:
                    db.add(MarketBar(instrument_id=benchmark.id, trading_date=trading_day, open=100,
                                     high=101, low=99, close=100, adj_close=100, volume=0,
                                     turnover=0, source="memory-fixture"))
                db.flush()
                pipeline._calculate_group_scores(db, day)
                db.flush()
                db.expire_all()
                score = db.scalar(select(GroupDailyScore))
                self.assertEqual((score.eligible_members, score.data_quality, score.rank), (5, "complete", 1))
                yield db, group, score, instruments, day
        finally:
            engine.dispose()

    def decision(self, db, day):
        db.flush()
        db.expire_all()
        return prioritized_instrument_ids(db, day)

    def expected(self, stocks, *keys):
        return [stocks[key].id for key in keys]

    def legacy(self, score):
        details = deepcopy(score.details_json)
        details.pop("candidate_identity_version")
        details.pop("candidate_instruments")
        score.details_json = details

    def test_real_top_four_identity_and_existing_order(self):
        for duplicate in (False, True):
            for reverse in (False, True):
                with self.subTest(duplicate=duplicate, reverse=reverse), self.fixture(duplicate, reverse) as (db, group, score, stocks, day):
                    self.assertEqual(score.details_json["candidate_identity_version"], "instrument-id-v1")
                    self.assertEqual(score.details_json["candidate_symbols"], ["SAME", "A", "B", "C"])
                    candidates = score.details_json["candidate_instruments"]
                    self.assertEqual([row["instrument_id"] for row in candidates], self.expected(stocks, "TWSE:SAME", "TWSE:A", "TWSE:B", "TWSE:C"))
                    self.assertTrue(all(type(row["instrument_id"]) is int for row in candidates))
                    self.assertEqual(self.decision(db, day), self.expected(stocks, "TWSE:A", "TWSE:B", "TWSE:C", "TWSE:SAME"))

    def test_two_markets_in_top_four_keep_both_and_duplicate_display(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse), self.fixture(reverse=reverse, both_selected=True) as (db, group, score, stocks, day):
                self.assertEqual(score.details_json["candidate_symbols"], ["SAME", "SAME", "A", "B"])
                self.assertEqual(self.decision(db, day), self.expected(stocks, "TPEX:SAME", "TWSE:A", "TWSE:B", "TWSE:SAME"))

    def test_malformed_versioned_sources_fail_closed(self):
        mutations = [
            lambda d: None, lambda d: [], lambda d: "invalid",
            lambda d: dict(d, candidate_identity_version=None),
            lambda d: dict(d, candidate_identity_version="future-v2"),
            lambda d: dict(d, candidate_identity_version=True),
            lambda d: dict(d, candidate_instruments=None),
            lambda d: dict(d, candidate_instruments="SAME"),
            lambda d: dict(d, candidate_instruments=[None]),
            lambda d: dict(d, candidate_instruments=d["candidate_instruments"] * 2),
            lambda d: dict(d, candidate_symbols=None),
            lambda d: dict(d, candidate_symbols="SAME"),
            lambda d: dict(d, candidate_symbols=[True]),
            lambda d: dict(d, candidate_symbols=[" "]),
            lambda d: dict(d, candidate_symbols=list(reversed(d["candidate_symbols"]))),
            lambda d: {k: v for k, v in d.items() if k != "candidate_identity_version"},
            lambda d: {k: v for k, v in d.items() if k != "candidate_instruments"},
            lambda d: dict(d, candidate_instruments=d["candidate_instruments"][:1] * 2,
                           candidate_symbols=["SAME", "SAME"]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index), self.fixture() as (db, group, score, stocks, day):
                score.details_json = mutate(deepcopy(score.details_json))
                self.assertEqual(self.decision(db, day), [])

    def test_identity_types_and_conflicts_fail_whole_source(self):
        for field, values in {
            "instrument_id": [True, False, 0, -1, 2.0, "2", None, 999999],
            "exchange": [None, True, 1, "", " ", "TPEX"],
            "symbol": [None, True, 1, "", " ", "OTHER"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.fixture() as (db, group, score, stocks, day):
                    details = deepcopy(score.details_json)
                    details["candidate_instruments"][0][field] = value
                    score.details_json = details
                    # Python considers 2.0 == 2; force the JSON write so ORM
                    # dirty checking cannot erase the invalid numeric type.
                    flag_modified(score, "details_json")
                    self.assertEqual(self.decision(db, day), [])
        for duplicate in ("id", "pair"):
            with self.subTest(duplicate=duplicate), self.fixture() as (db, group, score, stocks, day):
                details = deepcopy(score.details_json)
                rows = details["candidate_instruments"]
                if duplicate == "id":
                    rows[1]["instrument_id"] = rows[0]["instrument_id"]
                else:
                    rows[1].update(exchange=rows[0]["exchange"], symbol=rows[0]["symbol"])
                    details["candidate_symbols"][1] = rows[0]["symbol"]
                score.details_json = details
                self.assertEqual(self.decision(db, day), [])

    def test_empty_versioned_candidates_do_not_fall_back(self):
        with self.fixture() as (db, group, score, stocks, day):
            details = deepcopy(score.details_json)
            details.update(candidate_instruments=[], candidate_symbols=[])
            score.details_json = details
            self.assertEqual(self.decision(db, day), [])

    def test_legacy_unique_ambiguous_repeated_and_malformed(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), self.fixture(duplicate=duplicate) as (db, group, score, stocks, day):
                self.legacy(score)
                expected = self.expected(stocks, "TWSE:A", "TWSE:B", "TWSE:C")
                if not duplicate:
                    expected += self.expected(stocks, "TWSE:SAME")
                self.assertEqual(self.decision(db, day), expected)
        for symbols in (["SAME", "SAME", "A"], ["SAME", None], "SAME", [""], [1], ["SAME"] * 5):
            with self.subTest(symbols=symbols), self.fixture(duplicate=False) as (db, group, score, stocks, day):
                self.legacy(score)
                details = deepcopy(score.details_json)
                details["candidate_symbols"] = symbols
                score.details_json = details
                expected = self.expected(stocks, "TWSE:A") if symbols == ["SAME", "SAME", "A"] else []
                self.assertEqual(self.decision(db, day), expected)

    def test_cross_date_never_rebinds_or_unlocks_ambiguity(self):
        for legacy in (False, True):
            for duplicate in (False, True):
                for exit_winner in (False, True):
                    with self.subTest(legacy=legacy, duplicate=duplicate, exit_winner=exit_winner), self.fixture(duplicate=duplicate) as (db, group, score, stocks, day):
                        if legacy:
                            self.legacy(score)
                        later = day + timedelta(days=3)
                        if exit_winner:
                            member = db.scalar(select(GroupMembership).where(GroupMembership.instrument_id == stocks["TWSE:SAME"].id))
                            member.valid_to = day
                        if not duplicate:
                            newcomer = Instrument(exchange="TPEX", symbol="SAME", name="Later entrant", instrument_type="stock")
                            db.add(newcomer)
                            db.flush()
                            db.add(GroupMembership(group_id=group.id, instrument_id=newcomer.id,
                                                   valid_from=later, source="memory-fixture"))
                        expected = self.expected(stocks, "TWSE:A", "TWSE:B", "TWSE:C")
                        if not exit_winner and not (legacy and duplicate):
                            expected += self.expected(stocks, "TWSE:SAME")
                        self.assertEqual(self.decision(db, later), expected)

    def test_source_day_membership_invalid_rejects_versioned_source(self):
        for mode in ("future", "expired", "other_group"):
            with self.subTest(mode=mode), self.fixture() as (db, group, score, stocks, day):
                member = db.scalar(select(GroupMembership).where(GroupMembership.instrument_id == stocks["TWSE:SAME"].id))
                if mode == "future":
                    member.valid_from = day + timedelta(days=1)
                elif mode == "expired":
                    member.valid_to = day - timedelta(days=1)
                else:
                    other = ThemeGroup(id="other", name="Other", group_type="official_industry")
                    db.add(other)
                    db.flush()
                    member.group_id = other.id
                self.assertEqual(self.decision(db, day + timedelta(days=3)), [])

    def test_period_boundaries_and_inactive_status(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), self.fixture(duplicate=False) as (db, group, score, stocks, day):
                if legacy:
                    self.legacy(score)
                member = db.scalar(select(GroupMembership).where(GroupMembership.instrument_id == stocks["TWSE:SAME"].id))
                member.valid_from = member.valid_to = day
                self.assertIn(stocks["TWSE:SAME"].id, self.decision(db, day))
                self.assertNotIn(stocks["TWSE:SAME"].id, self.decision(db, day + timedelta(days=1)))
        with self.fixture() as (db, group, score, stocks, day):
            stocks["TWSE:SAME"].status = "inactive"
            self.assertEqual(self.decision(db, day), self.expected(stocks, "TWSE:A", "TWSE:B", "TWSE:C"))
        with self.fixture() as (db, group, score, stocks, day):
            self.legacy(score)
            stocks["TPEX:SAME"].status = "inactive"
            self.assertEqual(self.decision(db, day), self.expected(stocks, "TWSE:A", "TWSE:B", "TWSE:C"))

    def test_type_category_gates_and_current_metadata_limit(self):
        for kind, category in (("ipo", None), ("etf", "bond"), ("etf", "sector")):
            with self.subTest(kind=kind, category=category), self.fixture(kind=kind, category=category) as (db, group, score, stocks, day):
                self.assertEqual(self.decision(db, day), self.expected(stocks, "TWSE:A", "TWSE:B", "TWSE:C", "TWSE:SAME"))
                if kind == "etf":
                    stocks["TWSE:SAME"].etf_category = "unknown"
                else:
                    stocks["TWSE:SAME"].instrument_type = "index"
                self.assertEqual(self.decision(db, day), [])

    def test_other_buckets_survive_candidate_rejection_and_keep_order(self):
        for bucket in ("held", "watch", "conditional", "observation", "event"):
            with self.subTest(bucket=bucket), self.fixture() as (db, group, score, stocks, day):
                excluded = stocks["TPEX:SAME"]
                if bucket == "held":
                    db.add(PortfolioPosition(instrument_id=excluded.id, shares=1))
                elif bucket == "watch":
                    excluded.is_watchlisted = True
                elif bucket == "event":
                    db.add(Event(instrument_id=excluded.id, event_date=day, event_type="fixture", title="Recent", source="issuer_filing"))
                else:
                    strategy = StrategyVersion(name="breakout_v1", version="v1", kind="breakout")
                    db.add(strategy)
                    db.flush()
                    db.add(Signal(instrument_id=excluded.id, signal_key=bucket, signal_date=day,
                                  strategy_version_id=strategy.id, status=bucket, data_quality="complete"))
                self.assertEqual(self.decision(db, day), [excluded.id] + self.expected(stocks, "TWSE:A", "TWSE:B", "TWSE:C", "TWSE:SAME"))
                score.details_json = {"benchmark": "TAIEX", "candidate_identity_version": "unsupported"}
                self.assertEqual(self.decision(db, day), [excluded.id])

    def test_unqualified_score_gates_and_unavailable_producer(self):
        for mode in ("partial", "rank", "members", "benchmark", "group", "future"):
            with self.subTest(mode=mode), self.fixture() as (db, group, score, stocks, day):
                if mode == "partial":
                    score.data_quality = "partial"
                elif mode == "rank":
                    score.rank = None
                elif mode == "members":
                    score.eligible_members = 2
                elif mode == "benchmark":
                    score.details_json = dict(score.details_json, benchmark="OTHER")
                elif mode == "group":
                    group.active = False
                else:
                    score.trading_date = day + timedelta(days=1)
                self.assertEqual(self.decision(db, day), [])
        with self.fixture() as (db, group, score, stocks, day):
            for key in ("TWSE:A", "TWSE:B", "TWSE:C"):
                stocks[key].instrument_type = "index"
            db.flush()
            pipeline._calculate_group_scores(db, day)
            db.flush()
            db.expire_all()
            self.assertIsNone(score.score)
            self.assertEqual(score.details_json["candidate_symbols"], [])
            self.assertEqual(score.details_json["candidate_instruments"], [])
            self.assertEqual(self.decision(db, day), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
