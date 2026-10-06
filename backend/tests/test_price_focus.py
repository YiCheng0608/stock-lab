"""M2 contract and actual router tests; only guarded standalone memory runner."""
from datetime import date
import unittest
from unittest.mock import patch
from test_tpex_price_api import MemoryAPIFixture
from test_tpex_price_capture import SyntheticPolicyScope, csv_body, fixture_rows


class PriceFocusTests(unittest.TestCase):
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
                        self.assertEqual(query, {"as_of": ["2026-10-05"], "from": ["price-lots"], "focus_as_of": ["2026-10-05"], "focus_min_lots": [minimum], "focus_day_move": ["all"]})
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
                    self.assertEqual((result["version"], result["status"], result["day_move"], result["count"]), ("price-lot-focus/m2-v2", "available", move, len(expected)))
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
                        self.assertEqual((item["day_move"], item["open_exact"], item["close_exact"], item["reasons"]), (expected_move, opening, closing, ["volume_at_least_min_lots", reason]))
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
                value["latest"]["source_fields"].update({"開盤": "1.0", "收盤": "1.000"})
                return value
            with patch.object(tpex_price, "build_tpex_price", flat):
                result = build_price_focus(good, date(2026,10,5), "10000", "flat")
                self.assertEqual((result["status"], result["count"]), ("available", 2))
                self.assertTrue(all(item["reasons"] == ["volume_at_least_min_lots", "close_equal_open"] for item in result["items"]))
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
