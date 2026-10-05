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
                for query in ("min_lots=1", "as_of=2026-02-30&min_lots=1", "as_of=2026-10-05", "as_of=2026-10-05&min_lots=-1", "as_of=2026-10-05&min_lots=1.0001"):
                    self.assertEqual(client.post("/api/focus/price-lots/capture?" + query).status_code, 422)
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
                        self.assertEqual(query, {"as_of": ["2026-10-05"], "from": ["price-lots"], "focus_as_of": ["2026-10-05"], "focus_min_lots": [minimum]})
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
