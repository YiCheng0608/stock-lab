"""Backfill candidate identity through real memory DB, plan, filter and API.

Run with unittest/runpy and -B after configuring STOCK_DB_PATH=:memory:.
Suppress config's mkdir only during import; do not load pytest conftest.
"""

from copy import deepcopy
from datetime import date, timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app import api
from app.db import Base, enable_sqlite_foreign_keys
from app.models import Event, GroupDailyScore, Instrument, PortfolioPosition, Signal, ThemeGroup
from worker import backfill
from worker.sources import InstrumentRecord, OfficialBatch


class BackfillCandidateIdentityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        enable_sqlite_foreign_keys(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.day = date(2026, 9, 4)
        specs = [("TWSE", "SAME"), ("TPEx", "SAME"), ("TWSE", "OTHER"),
                 ("TWSE", "123"), ("TWSE", "None"), ("TWSE", "HELD"),
                 ("TWSE", "WATCH"), ("TWSE", "EVENT"), ("TWSE", "SIGNAL")]
        self.stocks = [Instrument(exchange=e, symbol=s, name=s) for e, s in specs]
        # Deliberately inactive group, missing membership/rank/score and poor
        # quality: collecting missing coverage must not require eligibility.
        self.db.add_all(self.stocks + [ThemeGroup(id="g", name="g", active=False)])
        self.db.flush()
        self.score = GroupDailyScore(group_id="g", trading_date=self.day, data_quality="missing")
        self.db.add(self.score)

    def typed(self, *indices):
        items = [self.stocks[i] for i in indices]
        return {"candidate_identity_version": "instrument-id-v1",
                "candidate_symbols": [item.symbol for item in items],
                "candidate_instruments": [dict(instrument_id=item.id, exchange=item.exchange,
                                                symbol=item.symbol) for item in items]}

    def persist(self, details):
        expected = deepcopy(details)
        self.score.details_json = deepcopy(details)
        flag_modified(self.score, "details_json")
        self.db.flush()
        self.db.expire_all()
        self.assertEqual(self.score.details_json, expected)
        if isinstance(expected, dict) and isinstance(expected.get("candidate_instruments"), list):
            for actual, wanted in zip(self.score.details_json["candidate_instruments"], expected["candidate_instruments"]):
                if isinstance(wanted, dict) and "instrument_id" in wanted:
                    self.assertIs(type(actual["instrument_id"]), type(wanted["instrument_id"]))

    def check_path(self, expected, scope="candidates", check_api=False):
        self.db.flush()
        self.db.expire_all()
        expected = sorted(expected)
        info = backfill.resolve_backfill_scope(self.db, scope, self.day, self.day)
        self.assertEqual(info["target_instruments"], expected)
        self.assertEqual(info["target_count"], len(expected))
        plan = backfill._initial_metadata(info, self.day, self.day, [self.day])
        self.assertEqual(plan["target_instruments"], expected)
        self.assertEqual(len(plan["batch_plan"]), 13)
        self.assertTrue(all(item["requested_dates"] == [self.day.isoformat()]
                            for item in plan["batch_plan"]))
        records = [InstrumentRecord(symbol=item.symbol, exchange=item.exchange, name=item.name)
                   for item in self.stocks]
        records.append(InstrumentRecord(symbol="TAIEX", exchange="TWSE", name="Index"))

        class LocalAdapter:
            def fetch(delegate, start, end):
                return OfficialBatch(instruments=records)

        batch = backfill._ScopedOfficialAdapter(LocalAdapter(), info["filter_keys"]).fetch(self.day, self.day)
        self.assertEqual({item.exchange + ":" + item.symbol for item in batch.instruments},
                         set(expected) | {"TWSE:TAIEX"})
        if check_api:
            report = api.coverage(start_date=self.day, end_date=self.day, scope=scope,
                                  exchange=None, symbol=None, db=self.db)
            self.assertEqual(report["scope"], scope)
            self.assertEqual({item["exchange"] + ":" + item["symbol"]
                              for item in report["instrument_coverage"]}, set(expected))

    def test_typed_exact_markets_and_empty_through_api(self):
        for indices, expected in [((0,), ["TWSE:SAME"]), ((1,), ["TPEx:SAME"]),
                                  ((0, 1), ["TWSE:SAME", "TPEx:SAME"]), ((), [])]:
            with self.subTest(indices=indices):
                self.persist(self.typed(*indices))
                self.check_path(expected, check_api=True)

    def test_inactive_identity_never_rebinds_and_conflict_rejects_whole_score(self):
        self.stocks[0].status = "inactive"
        self.persist(self.typed(0, 2))
        self.check_path(["TWSE:OTHER"], check_api=True)
        bad = self.typed(0, 2)
        bad["candidate_instruments"][0]["exchange"] = "TPEx"
        self.persist(bad)
        self.check_path([])

    def test_persisted_invalid_ids_and_pairs_reject_whole_score(self):
        for value in [999, 1.0, True, "1", None, 0, -1]:
            with self.subTest(instrument_id=value, kind=type(value).__name__):
                bad = self.typed(0, 2)
                bad["candidate_instruments"][0]["instrument_id"] = value
                self.persist(bad)
                self.check_path([])

    def test_out_of_range_integer_ids_reject_whole_score(self):
        for value in [2**63 - 1, 2**63, 10**100]:
            with self.subTest(instrument_id=value):
                bad = self.typed(0, 2)
                bad["candidate_instruments"][1]["instrument_id"] = value
                self.persist(bad)
                self.check_path([])

    def test_second_invalid_identity_does_not_leak_first_valid_identity(self):
        for inactive in (False, True):
            self.stocks[2].status = "inactive" if inactive else "active"
            for field, value in [("instrument_id", 999), ("exchange", "TPEx")]:
                with self.subTest(inactive=inactive, field=field):
                    bad = self.typed(0, 2)
                    bad["candidate_instruments"][1][field] = value
                    self.persist(bad)
                    self.check_path([])
        for field, value in [("exchange", "TPEx"), ("symbol", "OTHER"),
                             ("exchange", ""), ("symbol", "  "),
                             ("exchange", 1), ("symbol", None)]:
            with self.subTest(field=field, value=value):
                bad = self.typed(0, 2)
                bad["candidate_instruments"][0][field] = value
                self.persist(bad)
                self.check_path([])

    def test_malformed_typed_envelopes_never_fall_back(self):
        valid = self.typed(0, 2)
        cases = []
        for field, value in [("candidate_identity_version", "v2"), ("candidate_identity_version", None),
                             ("candidate_instruments", None), ("candidate_instruments", {}),
                             ("candidate_instruments", [None]), ("candidate_symbols", None),
                             ("candidate_symbols", "SAME"), ("candidate_symbols", [123]),
                             ("candidate_symbols", [" "]), ("candidate_symbols", ["OTHER", "SAME"]),
                             ("candidate_symbols", ["SAME"])]:
            bad = deepcopy(valid); bad[field] = value; cases.append(bad)
        for field in valid:
            bad = deepcopy(valid); del bad[field]; cases.append(bad)
        cases += [self.typed(0, 0), self.typed(0, 1, 2, 3, 4)]
        cases.append({"candidate_identity_version": "instrument-id-v1", "candidate_instruments": []})
        pair_duplicate = self.typed(0, 1)
        pair_duplicate["candidate_instruments"][1]["exchange"] = "TWSE"
        cases.append(pair_duplicate)
        for index, bad in enumerate(cases):
            with self.subTest(case=index):
                self.persist(bad)
                self.check_path([])

    def test_legacy_coercion_duplicates_and_all_active_exchanges(self):
        for values, expected in [(["SAME", "SAME", " SAME ", "missing"], ["TWSE:SAME", "TPEx:SAME"]),
                                 (["OTHER"], ["TWSE:OTHER"]),
                                 ([123, None, ""], ["TWSE:123", "TWSE:None"]),
                                 ([], []), ("SAME", [])]:
            with self.subTest(values=values):
                self.persist({"candidate_symbols": values})
                self.check_path(expected, check_api=True)
        self.stocks[0].status = "inactive"
        self.persist({"candidate_symbols": ["SAME"]})
        self.check_path(["TPEx:SAME"])
        for details in [None, [], "bad", 42, {}]:
            self.persist(details)
            self.check_path([])

    def test_score_date_range_and_cross_score_union(self):
        self.persist(self.typed(0))
        for offset in [-1, 1]:
            self.score.trading_date = self.day + timedelta(days=offset)
            self.check_path([])
        self.score.trading_date = self.day
        self.db.add(ThemeGroup(id="g2", name="g2"))
        self.db.flush()
        self.db.add(GroupDailyScore(group_id="g2", trading_date=self.day,
                                   details_json={"candidate_symbols": ["OTHER"]}))
        self.check_path(["TWSE:SAME", "TWSE:OTHER"])
        bad = self.typed(0)
        bad["candidate_instruments"][0]["instrument_id"] = 999
        self.persist(bad)
        self.check_path(["TWSE:OTHER"])

    def test_signal_and_priority_sources_survive_invalid_candidate(self):
        self.db.add(Signal(signal_key="s", instrument_id=self.stocks[8].id,
                           signal_date=self.day, status="observation"))
        self.db.add(PortfolioPosition(instrument_id=self.stocks[5].id, shares=1))
        self.stocks[6].is_watchlisted = True
        self.db.add(Event(instrument_id=self.stocks[7].id, event_date=self.day,
                          event_type="fixture", title="fixture"))
        self.persist({"candidate_identity_version": "bad", "candidate_symbols": ["SAME"]})
        self.check_path(["TWSE:SIGNAL"], check_api=True)
        self.check_path(["TWSE:SIGNAL", "TWSE:HELD", "TWSE:WATCH", "TWSE:EVENT"],
                        scope="priority", check_api=True)

    def test_collection_does_not_require_decision_type_or_category(self):
        self.stocks[0].instrument_type = "etf"
        self.stocks[0].etf_category = "unknown"
        self.persist(self.typed(0))
        self.check_path(["TWSE:SAME"])

    def test_market_and_all_remain_unfiltered(self):
        self.persist({"candidate_identity_version": "bad"})
        expected = sorted(item.exchange + ":" + item.symbol for item in self.stocks)
        for scope in ("market", "all"):
            info = backfill.resolve_backfill_scope(self.db, scope, self.day, self.day)
            self.assertEqual(info["target_instruments"], expected)
            self.assertIsNone(info["filter_keys"])


if __name__ == "__main__":
    unittest.main()
