"""M2 contract and actual router tests; only guarded standalone memory runner."""
from datetime import date
import unittest
from unittest.mock import patch
from test_tpex_price_api import MemoryAPIFixture
from test_tpex_price_capture import SyntheticPolicyScope, csv_body, fixture_rows


class PriceFocusTests(unittest.TestCase):
    def test_three_stock_router_exact_boundaries_complete_reads_and_five_strings(self):
        from fastapi.testclient import TestClient
        from urllib.parse import parse_qs, urlsplit, urlencode
        from worker import tpex_price_capture as worker
        import json, sys
        fixture = MemoryAPIFixture(cutoff=worker.NEW_CUTOFF, policy_version=worker.SCOPE_POLICY_VERSION)
        try:
            with TestClient(fixture.app) as client:
                client.post("/api/focus/price-lots/capture?as_of=2026-10-06&min_lots=0")
                cases = (("0", "all", "0", "0", ["3105", "5347", "6488"]),
                         ("20000.000", "up", "0", "5.691", ["5347"]), ("20000.000", "up", "0", "5.692", []),
                         ("34637.793", "up", "0", "0", ["5347"]), ("34637.794", "up", "0", "0", []),
                         ("20000", "up", "6615109776", "0", ["5347"]), ("20000", "up", "6615109777", "0", []),
                         ("35000", "all", "0", "0", []))
                for lots, move, amount, minimum_range, expected in cases:
                    conditions = dict(as_of="2026-10-06", min_lots=lots, day_move=move, min_turnover=amount, min_range_pct=minimum_range)
                    query = urlencode(conditions)
                    data = client.get("/api/focus/price-lots?" + query).json()
                    self.assertEqual((data["version"], data["status"], data["count"]), ("price-lot-focus/m2-v5", "available", len(expected)))
                    self.assertEqual([item["symbol"] for item in data["items"]], expected)
                    self.assertEqual([read["instrument"]["symbol"] for read in data["reads"]], ["3105", "5347", "6488"])
                    self.assertTrue(all(read["price_memory"]["provenance"] == data["reads"][0]["price_memory"]["provenance"] for read in data["reads"]))
                    for item in data["items"]:
                        self.assertEqual(len(item["reasons"]), len(set(item["reasons"])))
                        self.assertEqual(len(item["reasons"]), 4)
                        state = parse_qs(urlsplit(item["detail_url"]).query)
                        self.assertEqual(state, {"as_of": [conditions["as_of"]], "from": ["price-lots"], **{"focus_" + key: [value] for key, value in conditions.items()}})
                        if item["symbol"] == "5347":
                            self.assertEqual((item["volume_lots"], item["turnover_exact"], item["open_exact"], item["high_exact"], item["low_exact"], item["close_exact"]),
                                             ("34637.793", "6615109776", "184.50", "195.00", "184.50", "191.00"))
                            overview = client.get(item["detail_url"].replace("/stocks/", "/api/stocks/", 1)).json()["overview"]
                            self.assertEqual((overview["as_of"], overview["price_memory"]["latest"]["symbol"]), ("2026-10-06", "5347"))
                    self.assertEqual(client.post("/api/focus/price-lots/capture?" + query).json()["count"], len(expected))
                objects = (data, fixture.before, fixture.snapshot(), fixture.fixture.body)
                serialized = len(json.dumps(objects[:3], ensure_ascii=False).encode("utf-8")) + len(fixture.fixture.body)
                seen = set()
                def size(value):
                    if id(value) in seen: return 0
                    seen.add(id(value)); total = sys.getsizeof(value)
                    if isinstance(value, dict): total += sum(size(k) + size(v) for k, v in value.items())
                    elif isinstance(value, (tuple, list)): total += sum(size(v) for v in value)
                    return total
                footprint = size(objects)
                self.assertLessEqual(serialized, 256 * 1024); self.assertLessEqual(footprint, 8 * 1024 * 1024)
                print(json.dumps({"three_stock_fixture_serialized_bytes": serialized, "fixture_object_bytes": footprint, "max_csv_rows": 3}), flush=True)
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_three_stock_bad_catalogue_and_filtered_out_read_still_block(self):
        from app import tpex_price
        from app.price_focus import build_price_focus
        from worker import tpex_price_capture as worker
        from copy import deepcopy
        from types import SimpleNamespace
        fixture = MemoryAPIFixture(cutoff=worker.NEW_CUTOFF, policy_version=worker.SCOPE_POLICY_VERSION)
        try:
            good = [SimpleNamespace(market="TW", exchange="TPEx", symbol=s, name=n, instrument_type="stock", etf_category=None, currency="TWD")
                    for s, n in (("3105", "穩懋"), ("5347", "世界"), ("6488", "環球晶"))]
            for key, value in (("name", "unknown"), ("market", "US"), ("exchange", "TWSE"), ("instrument_type", "etf"), ("etf_category", "mixed"), ("currency", "unknown")):
                bad = deepcopy(good); setattr(bad[1], key, value)
                self.assertEqual(build_price_focus(bad, worker.NEW_CUTOFF, "35000", capture=True)["reasons"], ["price_focus_catalogue_not_supported"])
            for bad in (good[:1] + good[2:], good + good[1:2]):
                self.assertIsNone(build_price_focus(bad, worker.NEW_CUTOFF, "35000", capture=True)["count"])
            self.assertEqual(fixture.fixture.opener.calls, [])
            tpex_price.capture_tpex_price(good[0], worker.NEW_CUTOFF)
            real = tpex_price.build_tpex_price
            for symbol, failure in (("5347", "missing"), ("5347", "turnover"), ("5347", "range"), ("5347", "provenance"), ("6488", "provenance")):
                def polluted(item, cutoff):
                    value = deepcopy(real(item, cutoff))
                    if item.symbol == symbol:
                        if failure == "missing": value.update(status="unavailable", latest=None, reasons=["price_memory_capture_missing"])
                        elif failure == "turnover": value["latest"]["source_fields"]["成交金額"] = ""
                        elif failure == "range": value["latest"]["source_fields"]["最高"] = "0"
                        else: value["provenance"]["receipt_sha256"] = "b" * 64
                    return value
                with patch.object(tpex_price, "build_tpex_price", polluted):
                    data = build_price_focus(good, worker.NEW_CUTOFF, "35000")
                self.assertEqual((data["status"], data["count"], data["items"]), ("unavailable", None, []))
                if failure == "provenance": self.assertEqual(data["reasons"], ["price_focus_source_mismatch"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_range_contract_and_independent_exact_boundaries(self):
        from app.price_focus import exact_day_range, parse_min_range_pct, range_meets_minimum
        for raw, scaled in (("0", "0"), ("0.000", "0"), ("4.500", "4500"), ("9223372036854775.807", "9223372036854775807")):
            self.assertEqual(parse_min_range_pct(raw), scaled)
        for value in (None, True, 1, "", "01", "-1", "+1", "1e0", "1.0001", "1.", ".1", " 1", "1\n", "1,000", "１", "9223372036854775.808"):
            with self.subTest(value=value), self.assertRaises(ValueError): parse_min_range_pct(value)
        precise = "1.000000000000000000000000000001"
        for opening, high, low, minimum, expected in (
            ("100", "104", "100", "4", True), ("100.00", "104.000", "100.0", "4.001", False),
            ("3", "3.0001", "3.0", "0.003", True), ("3.00", "3.0001", "3", "0.004", False),
            (precise, "1.040000000000000000000000000001", precise, "4", False),
            (precise, "1.040000000000000000000000000001", precise, "3.999", True),
            ("1", "92233720368548.75807", "1", "9223372036854775.807", True),
            ("1", "92233720368548.75806", "1", "9223372036854775.807", False),
            ("1.0", "1.000", "1", "0.000", True), ("1", "1", "1", "0.001", False)):
            prices = exact_day_range({"source_fields": {"開盤": opening, "最高": high, "最低": low}})
            self.assertIsNotNone(prices)
            self.assertEqual(range_meets_minimum(prices, parse_min_range_pct(minimum)), expected)
        for key in ("開盤", "最高", "最低"):
            for bad in (None, 1, "", "0", "-1", "01", "1e0", "1\n", "1" * 65):
                fields = {"開盤": "1", "最高": "1", "最低": "1"}; fields[key] = bad
                self.assertIsNone(exact_day_range({"source_fields": fields}))
        self.assertIsNone(exact_day_range({"source_fields": {"開盤": "2", "最高": "1", "最低": "1"}}))

    def test_range_invalid_both_routes_before_lookup_and_capture(self):
        from fastapi.testclient import TestClient
        from urllib.parse import urlencode
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client, patch("sqlalchemy.orm.Session.scalars") as lookup, patch.object(fixture.api, "build_price_focus") as build:
                bad = ("", "01", "-1", "+1", "1e0", "1.0001", "1.", ".1", " 1", "1\n", "1,000", "１", "9223372036854775.808")
                queries = [urlencode({"as_of": "2026-10-05", "min_lots": "0", "min_range_pct": value}) for value in bad]
                queries += ["as_of=2026-10-05&min_lots=0&min_range_pct=0&min_range_pct=1", "as_of=2026-10-05&min_lots=0&q=3105"]
                for query in queries:
                    for path, method in (("/api/focus/price-lots", client.get), ("/api/focus/price-lots/capture", client.post)):
                        self.assertEqual(method(path + "?" + query).status_code, 422)
                lookup.assert_not_called(); build.assert_not_called()
            self.assertEqual(fixture.fixture.opener.calls, [])
        finally: fixture.close()

    def test_new_day_four_reasons_five_params_exact_expected_sets_and_shared_m1(self):
        from fastapi.testclient import TestClient
        from urllib.parse import parse_qs, urlsplit
        from worker.tpex_price_capture import NEW_CUTOFF
        fixture = MemoryAPIFixture(cutoff=NEW_CUTOFF)
        try:
            with TestClient(fixture.app) as client:
                client.post("/api/focus/price-lots/capture?as_of=2026-10-06&min_lots=10000.000&min_range_pct=4")
                for minimum, move, expected in (("0", "all", ["3105", "6488"]), ("4", "all", ["3105", "6488"]),
                                                 ("6.000", "all", ["6488"]), ("10", "all", []), ("6", "down", []), ("6", "up", ["6488"]),
                                                 ("5.691", "all", ["3105", "6488"]), ("5.692", "all", ["6488"]),
                                                 ("9.787", "all", ["6488"]), ("9.788", "all", [])):
                    query = f"as_of=2026-10-06&min_lots=10000.000&day_move={move}&min_turnover=0&min_range_pct={minimum}"
                    data = client.get("/api/focus/price-lots?" + query).json()
                    self.assertEqual((data["status"], data["count"], data["min_range_pct"]), ("available", len(expected), minimum))
                    self.assertEqual([item["symbol"] for item in data["items"]], expected)
                    for item in data["items"]:
                        self.assertEqual(item["reasons"][-1], "range_at_least_min_range_pct")
                        self.assertEqual(len(item["reasons"]), 4)
                        self.assertEqual((item["high_exact"], item["low_exact"]), ("623.00", "588.00") if item["symbol"] == "3105" else ("1260.00", "1145.00"))
                        self.assertEqual(parse_qs(urlsplit(item["detail_url"]).query), {"as_of": ["2026-10-06"], "from": ["price-lots"], "focus_as_of": ["2026-10-06"], "focus_min_lots": ["10000.000"], "focus_day_move": [move], "focus_min_turnover": ["0"], "focus_min_range_pct": [minimum]})
                    client.post("/api/focus/price-lots/capture?" + query)
                self.assertEqual(client.get("/api/focus/price-lots?as_of=2026-10-06&min_lots=10000").json()["min_range_pct"], "0")
                self.assertEqual(client.get("/api/stocks/TPEx/6488?as_of=2026-10-06").json()["overview"]["price_memory"]["latest"]["volume_exact"], "13913614")
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_range_zero_vs_missing_even_with_zero_or_empty_candidate_filter(self):
        from app import tpex_price
        from app.price_focus import build_price_focus
        from copy import deepcopy
        from types import SimpleNamespace
        fixture = MemoryAPIFixture()
        try:
            instruments = [SimpleNamespace(market="TW", exchange="TPEx", symbol=s, name=n, instrument_type="stock", etf_category=None) for s, n in (("3105", "穩懋"), ("6488", "環球晶"))]
            tpex_price.capture_tpex_price(instruments[0], date(2026, 10, 5))
            real = tpex_price.build_tpex_price
            def zero(item, cutoff):
                value = deepcopy(real(item, cutoff)); value["latest"]["source_fields"].update({"開盤": "1.0", "最高": "1.000", "最低": "1", "收盤": "1"}); return value
            with patch.object(tpex_price, "build_tpex_price", zero):
                self.assertEqual(build_price_focus(instruments, date(2026, 10, 5), "0", min_range_pct="0.000")["count"], 2)
                self.assertEqual(build_price_focus(instruments, date(2026, 10, 5), "0", min_range_pct="0.001")["count"], 0)
            for key in ("最高", "最低"):
                for bad in (None, "", "0", "01", "-1"):
                    def missing(item, cutoff):
                        value = deepcopy(real(item, cutoff)); value["latest"]["source_fields"][key] = bad; return value
                    with patch.object(tpex_price, "build_tpex_price", missing):
                        data = build_price_focus(instruments, date(2026, 10, 5), "50000", min_range_pct="0")
                        self.assertEqual((data["status"], data["count"], data["reasons"]), ("unavailable", None, ["price_focus_range_unavailable"]))
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_decimal_contract_exact_int64_and_rejections(self):
        from app.price_focus import parse_min_lots, lots_text
        for raw, shares in (("0", "0"), ("0.000", "0"), ("0.001", "1"), ("20000", "20000000"),
                            ("48127.911", "48127911"), ("9007199254740.993", "9007199254740993"),
                            ("9223372036854775.807", "9223372036854775807")):
            self.assertEqual(parse_min_lots(raw), shares)
        self.assertEqual(lots_text("1"), "0.001")
        self.assertEqual(lots_text("9223372036854775807"), "9223372036854775.807")
        for bad in (None, 20000, 0.001, True, "", "01", "-1", "+1", ".1", "1.", "1.0001", "1e3", "NaN", "20,000", " 1", "1\n", "１", "9223372036854775.808"):
            with self.subTest(bad=bad), self.assertRaises(ValueError): parse_min_lots(bad)

    def test_router_unloaded_invalid_and_unsupported_never_take_source(self):
        from fastapi.testclient import TestClient
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client:
                response = client.get("/api/focus/price-lots?as_of=2026-10-05&min_lots=50000")
                self.assertEqual(response.status_code, 200)
                self.assertEqual((response.json()["status"], response.json()["count"], response.json()["items"]), ("unavailable", None, []))
                self.assertTrue(response.json()["can_capture"])
                valid = "as_of=2026-10-05&min_lots=1"
                for query in ("min_lots=1", "as_of=2026-02-30&min_lots=1", "as_of=2026-10-05", "as_of=2026-10-05&min_lots=-1", "as_of=2026-10-05&min_lots=1.0001",
                              valid + "&day_move=unknown", valid + "&day_move=", valid + "&day_move=UP", valid + "&day_move=all&day_move=up",
                              valid + "&as_of=2026-10-02", valid + "&min_lots=0"):
                    for method in (client.get, client.post):
                        path = "/api/focus/price-lots" + ("/capture" if method == client.post else "")
                        self.assertEqual(method(path + "?" + query).status_code, 422)
                self.assertEqual(client.post("/api/focus/price-lots/capture?as_of=2026-10-02&min_lots=0").json()["status"], "unavailable")
            self.assertEqual(fixture.fixture.opener.calls, [])
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_three_thresholds_dedupe_order_same_cutoff_and_readonly_shared_m1(self):
        from fastapi.testclient import TestClient
        from urllib.parse import urlsplit, parse_qs
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client:
                first = client.post("/api/focus/price-lots/capture?as_of=2026-10-05&min_lots=20000").json()
                self.assertEqual([item["symbol"] for item in first["items"]], ["3105"])
                self.assertEqual(first["items"][0]["volume_lots"], "48127.911")
                for minimum, expected in (("10000", ["3105", "6488"]), ("50000", []), ("48127.911", ["3105"]), ("48127.912", []), ("0.000", ["3105", "6488"])):
                    result = client.get("/api/focus/price-lots?as_of=2026-10-05&min_lots=" + minimum).json()
                    self.assertEqual((result["status"], result["count"]), ("available", len(expected)))
                    self.assertEqual([item["symbol"] for item in result["items"]], expected)
                    for item in result["items"]:
                        query = parse_qs(urlsplit(item["detail_url"]).query)
                        self.assertEqual(query, {"as_of": ["2026-10-05"], "from": ["price-lots"], "focus_as_of": ["2026-10-05"], "focus_min_lots": [minimum], "focus_day_move": ["all"], "focus_min_turnover": ["0"], "focus_min_range_pct": ["0"]})
                m1 = client.get("/api/stocks/TPEx/6488?as_of=2026-10-05").json()["overview"]["price_memory"]
                self.assertEqual(m1["latest"]["volume_exact"], "18982607")
                self.assertEqual(m1["latest"]["close"], 1180)
                client.post("/api/stocks/TPEx/6488/prices/capture?as_of=2026-10-05")
                client.post("/api/focus/price-lots/capture?as_of=2026-10-05&min_lots=50000")
                default = client.get("/api/stocks/TPEx/3105").json()["overview"]
                self.assertEqual(default["as_of"], "2026-10-02")
                self.assertIsNone(default["price_memory"]["latest"])
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_four_directions_two_reasons_dedupe_same_cutoff_and_cache(self):
        from fastapi.testclient import TestClient
        from urllib.parse import urlsplit, parse_qs
        import json
        import sys
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client:
                client.post("/api/focus/price-lots/capture?as_of=2026-10-05&min_lots=10000.000&day_move=up")
                for move, expected in (("all", ["3105", "6488"]), ("up", ["3105"]), ("down", ["6488"]), ("flat", [])):
                    query = "as_of=2026-10-05&min_lots=10000.000&day_move=" + move
                    result = client.get("/api/focus/price-lots?" + query).json()
                    self.assertEqual((result["version"], result["status"], result["day_move"], result["count"]), ("price-lot-focus/m2-v5", "available", move, len(expected)))
                    self.assertEqual([item["symbol"] for item in result["items"]], expected)
                    if move == "all":
                        sample = {"api": result, "before": fixture.before, "after": fixture.snapshot(), "csv": fixture.fixture.body}
                        serialized = sum(len(json.dumps(value, ensure_ascii=False).encode("utf-8")) for key, value in sample.items() if key != "csv") + len(sample["csv"])
                        seen = set()
                        def memory_size(value):
                            if id(value) in seen: return 0
                            seen.add(id(value))
                            if isinstance(value, dict):
                                return sys.getsizeof(value) + sum(memory_size(key) + memory_size(child) for key, child in value.items())
                            children = value if isinstance(value, (list, tuple)) else ()
                            return sys.getsizeof(value) + sum(memory_size(child) for child in children)
                        footprint = memory_size(sample)
                        self.assertLessEqual(serialized, 256 * 1024)
                        self.assertLessEqual(footprint, 8 * 1024 * 1024)
                        print(json.dumps({"synthetic_fixture_serialized_bytes": serialized, "fixture_object_bytes": footprint, "scope": "one complete focus response plus before/after memory DB snapshots and synthetic CSV"}), flush=True)
                    for item in result["items"]:
                        expected_move, opening, closing, reason = ("up", "614.00", "615.00", "close_above_open") if item["symbol"] == "3105" else ("down", "1220.00", "1180.00", "close_below_open")
                        self.assertEqual((item["day_move"], item["open_exact"], item["close_exact"], item["reasons"]), (expected_move, opening, closing, ["volume_at_least_min_lots", "turnover_at_least_min_turnover", reason, "range_at_least_min_range_pct"]))
                        state = parse_qs(urlsplit(item["detail_url"]).query)
                        self.assertEqual((state["as_of"], state["focus_as_of"], state["focus_min_lots"], state["focus_day_move"]), (["2026-10-05"], ["2026-10-05"], ["10000.000"], [move]))
                    client.post("/api/focus/price-lots/capture?" + query)
                unsupported = client.get("/api/focus/price-lots?as_of=2026-10-02&min_lots=10000&day_move=flat").json()
                self.assertEqual((unsupported["status"], unsupported["count"]), ("unavailable", None))
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_exact_prices_same_float_and_flat_trailing_decimals(self):
        from app.price_focus import exact_day_move, parse_day_move
        for opening, closing, expected in (("614.00", "615.00", "up"), ("1.000000000000000001", "1.000000000000000002", "up"),
                                           ("1.000000000000000002", "1.000000000000000001", "down"), ("1", "1.000", "flat"),
                                           ("0.0010", "0.001", "flat"), ("0.0001", "0.001", "up"), ("9.9", "10.0", "up")):
            self.assertEqual(exact_day_move({"source_fields": {"開盤": opening, "收盤": closing}}), (expected, opening, closing))
        self.assertEqual(float("1.000000000000000001"), float("1.000000000000000002"))
        for bad in (None, 0, "", "0", "0.000", "-1", "NaN", "Infinity", "1e0", "01", "1.", "１", " 1", "1\n", "1" * 65):
            for key in ("開盤", "收盤"):
                fields = {"開盤": "1", "收盤": "1"}; fields[key] = bad
                self.assertIsNone(exact_day_move({"source_fields": fields}))
        self.assertIsNone(exact_day_move({}))
        for bad in (None, True, "UP", "unknown", "", "all\n"):
            with self.assertRaises(ValueError): parse_day_move(bad)

    def test_direction_missing_is_unknown_even_for_all_or_empty_threshold(self):
        from app import tpex_price
        from app.price_focus import build_price_focus
        from copy import deepcopy
        from types import SimpleNamespace
        fixture = MemoryAPIFixture()
        try:
            good = [SimpleNamespace(market="TW", exchange="TPEx", symbol=s, name=n, instrument_type="stock", etf_category=None) for s,n in (("3105", "穩懋"), ("6488", "環球晶"))]
            tpex_price.capture_tpex_price(good[0], date(2026,10,5))
            real = tpex_price.build_tpex_price
            def missing(item, cutoff):
                value = deepcopy(real(item, cutoff))
                if item.symbol == "6488": value["latest"]["source_fields"].pop("開盤")
                return value
            with patch.object(tpex_price, "build_tpex_price", missing):
                for move in ("all", "up", "down", "flat"):
                    result = build_price_focus(good, date(2026,10,5), "50000", move)
                    self.assertEqual((result["status"], result["count"], result["items"], result["reasons"]), ("unavailable", None, [], ["price_focus_direction_unavailable"]))
            def flat(item, cutoff):
                value = deepcopy(real(item, cutoff))
                value["latest"]["source_fields"].update({"開盤": "1.0", "收盤": "1.000", "最高": "2", "最低": "1"})
                return value
            with patch.object(tpex_price, "build_tpex_price", flat):
                result = build_price_focus(good, date(2026,10,5), "10000", "flat")
                self.assertEqual((result["status"], result["count"]), ("available", 2))
                self.assertTrue(all(item["reasons"] == ["volume_at_least_min_lots", "turnover_at_least_min_turnover", "close_equal_open", "range_at_least_min_range_pct"] for item in result["items"]))
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_zero_one_share_above_js_safe_and_int64_boundary(self):
        from app import tpex_price
        from app.price_focus import build_price_focus
        from sqlalchemy.orm import Session
        from app.models import Instrument
        from sqlalchemy import select
        fixture = MemoryAPIFixture()
        try:
            with Session(fixture.engine) as db:
                instruments = list(db.scalars(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol.in_(("3105", "6488")))))
                for volume, minimum, count in (("0", "0", 2), ("0", "0.001", 0), ("1", "0.001", 2),
                                               ("1", "0.002", 0), ("9007199254740993", "9007199254740.993", 2),
                                               ("9007199254740993", "9007199254740.994", 0), ("9223372036854775807", "9223372036854775.807", 2)):
                    rows = fixture_rows()
                    for row in rows[:2]: row[9] = volume
                    with SyntheticPolicyScope(csv_body(rows)) as source:
                        with patch.object(tpex_price, "STORE", tpex_price.TpexPriceStore(loader=source.loader)), patch.dict("os.environ", source.env):
                            result = build_price_focus(instruments, date(2026, 10, 5), minimum, capture=True)
                    self.assertEqual((result["status"], result["count"]), ("available", count))
                    if int(volume) > 9007199254740991:
                        self.assertIsNone(result["reads"][0]["price_memory"]["latest"]["volume"])
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_turnover_contract_and_invalid_router_before_catalogue_or_capture(self):
        from app.price_focus import exact_turnover, parse_min_turnover
        from fastapi.testclient import TestClient
        from urllib.parse import urlencode
        for value in ("0", "1", "29694939981", "9007199254740993", "9223372036854775807"):
            self.assertEqual(parse_min_turnover(value), value)
        bad = (None, True, 1, "", "00", "01", "-1", "+1", "1.0", "1e3", "1,000", " 1", "1\n", "１", "9223372036854775808")
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError): parse_min_turnover(value)
        complete = {"currency": "TWD", "turnover_exact": "0", "source_fields": {"成交金額": "0"}, "turnover_status": "available", "turnover_reason": None}
        self.assertEqual(exact_turnover(complete), "0")
        del complete["turnover_reason"]
        self.assertIsNone(exact_turnover(complete))
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client, patch("sqlalchemy.orm.Session.scalars") as lookup, patch.object(fixture.api, "build_price_focus") as build:
                queries = [urlencode({"as_of": "2026-10-05", "min_lots": "10000", "min_turnover": value}) for value in bad if type(value) is str]
                queries += ["as_of=2026-10-05&min_lots=10000&min_turnover=0&min_turnover=1",
                            "as_of=2026-10-05&min_lots=10000&next=https://foreign.example",
                            "as_of=2026-10-05&min_lots=-1&min_turnover=0"]
                for query in queries:
                    for path, method in (("/api/focus/price-lots", client.get), ("/api/focus/price-lots/capture", client.post)):
                        self.assertEqual(method(path + "?" + query).status_code, 422)
                lookup.assert_not_called()
                build.assert_not_called()
            self.assertEqual(fixture.fixture.opener.calls, [])
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_turnover_three_reasons_exact_selected_values_and_complete_links(self):
        from fastapi.testclient import TestClient
        from urllib.parse import parse_qs, urlsplit
        fixture = MemoryAPIFixture()
        try:
            with TestClient(fixture.app) as client:
                client.post("/api/focus/price-lots/capture?as_of=2026-10-05&min_lots=10000.000&min_turnover=25000000000")
                for amount, move, expected in (("25000000000", "all", ["3105"]), ("20000000000", "all", ["3105", "6488"]),
                                              ("25000000000", "down", []), ("29694939981", "all", ["3105"]),
                                              ("29694939982", "all", []), ("22887612060", "down", ["6488"]),
                                              ("22887612061", "down", []), ("0", "all", ["3105", "6488"])):
                    query = "as_of=2026-10-05&min_lots=10000.000&day_move=" + move + "&min_turnover=" + amount
                    data = client.get("/api/focus/price-lots?" + query).json()
                    self.assertEqual((data["status"], data["count"], data["min_turnover"]), ("available", len(expected), amount))
                    self.assertEqual([item["symbol"] for item in data["items"]], expected)
                    self.assertEqual(len(data["reads"]), 2)
                    for item in data["items"]:
                        actual = "29694939981" if item["symbol"] == "3105" else "22887612060"
                        reason = "close_above_open" if item["symbol"] == "3105" else "close_below_open"
                        self.assertEqual((item["turnover_exact"], item["min_turnover"], item["reasons"]),
                                         (actual, amount, ["volume_at_least_min_lots", "turnover_at_least_min_turnover", reason, "range_at_least_min_range_pct"]))
                        self.assertEqual(parse_qs(urlsplit(item["detail_url"]).query), {"as_of": ["2026-10-05"], "from": ["price-lots"],
                                         "focus_as_of": ["2026-10-05"], "focus_min_lots": ["10000.000"], "focus_day_move": [move], "focus_min_turnover": [amount], "focus_min_range_pct": ["0"]})
                    client.post("/api/focus/price-lots/capture?" + query)
                self.assertEqual(client.get("/api/focus/price-lots?as_of=2026-10-05&min_lots=10000").json()["min_turnover"], "0")
                unknown = client.get("/api/focus/price-lots?as_of=2026-10-02&min_lots=0&min_turnover=0").json()
                self.assertEqual((unknown["status"], unknown["count"]), ("unavailable", None))
            self.assertEqual(len(fixture.fixture.opener.calls), 1)
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_turnover_zero_one_unsafe_and_int64_boundaries(self):
        from app import tpex_price
        from app.price_focus import build_price_focus
        from app.models import Instrument
        from sqlalchemy.orm import Session
        from sqlalchemy import select
        fixture = MemoryAPIFixture()
        try:
            with Session(fixture.engine) as db:
                instruments = list(db.scalars(select(Instrument).where(Instrument.exchange == "TPEx", Instrument.symbol.in_(("3105", "6488")))))
                for amount, minimum, count in (("0", "0", 2), ("0", "1", 0), ("1", "1", 2), ("1", "2", 0),
                                               ("9007199254740993", "9007199254740993", 2), ("9007199254740993", "9007199254740994", 0),
                                               ("9223372036854775807", "9223372036854775807", 2)):
                    rows = fixture_rows()
                    for row in rows[:2]: row[10] = amount
                    with SyntheticPolicyScope(csv_body(rows)) as source:
                        with patch.object(tpex_price, "STORE", tpex_price.TpexPriceStore(loader=source.loader)), patch.dict("os.environ", source.env):
                            data = build_price_focus(instruments, date(2026, 10, 5), "10000", "all", minimum, capture=True)
                    self.assertEqual((data["status"], data["count"]), ("available", count))
                    if int(amount) > 9007199254740991:
                        self.assertIsNone(data["reads"][0]["price_memory"]["latest"]["turnover"])
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_turnover_missing_or_conflicting_is_unknown_before_filter(self):
        from app import tpex_price
        from app.price_focus import build_price_focus
        from copy import deepcopy
        from types import SimpleNamespace
        fixture = MemoryAPIFixture()
        try:
            instruments = [SimpleNamespace(market="TW", exchange="TPEx", symbol=s, name=n, instrument_type="stock", etf_category=None) for s, n in (("3105", "穩懋"), ("6488", "環球晶"))]
            rows = fixture_rows(); rows[1][10] = ""
            with SyntheticPolicyScope(csv_body(rows)) as source:
                with patch.object(tpex_price, "STORE", tpex_price.TpexPriceStore(loader=source.loader)), patch.dict("os.environ", source.env):
                    missing = build_price_focus(instruments, date(2026, 10, 5), "50000", "flat", "0", capture=True)
            self.assertEqual((missing["status"], missing["count"], missing["reasons"]), ("unavailable", None, ["price_focus_turnover_unavailable"]))
            tpex_price.capture_tpex_price(instruments[0], date(2026, 10, 5))
            real = tpex_price.build_tpex_price
            for change in ({"turnover_exact": "-1"}, {"turnover_exact": "01"}, {"turnover_exact": "9223372036854775808"},
                           {"turnover_status": "unavailable"}, {"turnover_reason": "missing"}, {"currency": "USD"}, {"currency": "mixed"}, {"currency": "unknown"}):
                def invalid(item, cutoff):
                    value = deepcopy(real(item, cutoff))
                    if item.symbol == "6488": value["latest"].update(change)
                    return value
                with patch.object(tpex_price, "build_tpex_price", invalid):
                    data = build_price_focus(instruments, date(2026, 10, 5), "50000", "flat", "0")
                    self.assertEqual((data["status"], data["count"], data["reasons"]), ("unavailable", None, ["price_focus_turnover_unavailable"]))
            def mismatch(item, cutoff):
                value = deepcopy(real(item, cutoff))
                if item.symbol == "6488": value["latest"]["source_fields"]["成交金額"] = "0"
                return value
            with patch.object(tpex_price, "build_tpex_price", mismatch):
                self.assertEqual(build_price_focus(instruments, date(2026, 10, 5), "50000")["reasons"], ["price_focus_turnover_unavailable"])
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()

    def test_all_catalogue_identities_required_before_capture(self):
        from app.price_focus import build_price_focus
        from types import SimpleNamespace
        fixture = MemoryAPIFixture()
        try:
            good = [SimpleNamespace(market="TW", exchange="TPEx", symbol=s, name=n, instrument_type="stock", etf_category=None, currency="TWD") for s,n in (("3105", "穩懋"), ("6488", "環球晶"))]
            for key, value in (("name", "unknown"), ("market", "US"), ("instrument_type", "etf"), ("etf_category", "mixed"), ("currency", "unknown"), ("exchange", "TWSE")):
                invalid = [SimpleNamespace(**vars(item)) for item in good]; setattr(invalid[1], key, value)
                self.assertEqual(build_price_focus(invalid, date(2026,10,5), "0", capture=True)["reasons"], ["price_focus_catalogue_not_supported"])
            for scope in (good[:1], good + good[:1]):
                self.assertIsNone(build_price_focus(scope, date(2026,10,5), "0", capture=True)["count"])
            self.assertEqual(fixture.fixture.opener.calls, [])
        finally: fixture.close()

    def test_partial_or_invalid_read_is_unavailable_not_empty_success(self):
        from app import tpex_price
        from app.price_focus import build_price_focus
        from types import SimpleNamespace
        fixture = MemoryAPIFixture()
        try:
            good = [SimpleNamespace(market="TW", exchange="TPEx", symbol=s, name=n, instrument_type="stock", etf_category=None) for s,n in (("3105", "穩懋"), ("6488", "環球晶"))]
            tpex_price.capture_tpex_price(good[0], date(2026,10,5))
            real = tpex_price.build_tpex_price
            def partial(item, cutoff):
                value = real(item, cutoff)
                if item.symbol == "6488": value.update(status="unavailable", latest=None, reasons=["price_memory_capture_missing"])
                return value
            with patch.object(tpex_price, "build_tpex_price", partial):
                result = build_price_focus(good, date(2026,10,5), "50000")
            self.assertEqual((result["status"], result["count"], result["items"]), ("unavailable", None, []))
            with patch.object(tpex_price, "build_tpex_price", side_effect=KeyError("missing")):
                self.assertEqual(build_price_focus(good, date(2026,10,5), "0")["reasons"], ["price_focus_read_invalid"])
        finally: fixture.close()

    def test_failed_capture_cached_and_busy_never_retry(self):
        from fastapi.testclient import TestClient
        from worker.tpex_price_capture import PriceCaptureError
        fixture = MemoryAPIFixture()
        calls = []
        def failure(**kwargs): calls.append(1); kwargs["on_request"](); raise PriceCaptureError("price_body_version_mismatch")
        fixture.store._loader = failure
        try:
            with TestClient(fixture.app) as client:
                fixture.store._lock.acquire()
                try: self.assertIsNone(client.post("/api/focus/price-lots/capture?as_of=2026-10-05&min_lots=0").json()["count"])
                finally: fixture.store._lock.release()
                for _ in range(2):
                    result = client.post("/api/focus/price-lots/capture?as_of=2026-10-05&min_lots=0").json()
                    self.assertEqual((result["status"], result["count"]), ("unavailable", None))
                    self.assertFalse(result["can_capture"])
            self.assertEqual(calls, [1])
            self.assertEqual(fixture.before, fixture.snapshot())
        finally: fixture.close()
