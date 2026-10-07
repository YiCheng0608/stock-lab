import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import httpx
from app.institutional_series_scope7 import API_PATH, create_app
from worker import tpex_institutional_series_scope7 as w
from test_tpex_institutional_series_scope7 import fixtures, producer


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p, self.seen = producer(fixtures())
        self.app = create_app(self.p)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("127.0.0.1", 12345)), base_url="http://owned")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_exact_query_body_and_method_gate_before_state(self):
        for query in ("", "as_of=2026-02-30", "as_of=2026-10-06&as_of=2026-10-06", "as_of=2026-10-06&x=1", "as_of=2026-10-6"):
            self.assertEqual((await self.client.get(API_PATH + "?" + query)).status_code, 422)
        self.assertEqual((await self.client.request("GET", API_PATH + "?as_of=" + w.CUTOFF, content=b"{}")).status_code, 422)
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, content=b"x" * 4097)).status_code, 413)
        for body in (b"", b"[]", b'{"x":1}', b"null"):
            self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, content=body)).status_code, 422)
        for path in ("/api/stocks/TPEx/3105", "/api/price/saved", "/private"):
            self.assertEqual((await self.client.get(path)).status_code, 404)
        self.assertEqual((await self.client.post(API_PATH + "?as_of=" + w.CUTOFF, json={})).status_code, 405)
        self.assertFalse(self.p.attempted); self.assertEqual(self.p.request_count, 0); self.assertEqual(self.seen, [])

    async def test_unsupported_valid_cutoff_does_not_read_state(self):
        with patch.object(self.p, "read", side_effect=AssertionError("state accessed")), patch.object(self.p, "capture", side_effect=AssertionError("state accessed")):
            for day in ("2026-10-05", "2026-10-07"):
                for method, suffix in (("GET", ""), ("POST", "/capture")):
                    response = await self.client.request(method, API_PATH + suffix + "?as_of=" + day, content=b"{}" if method == "POST" else b"")
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(response.json()["available"]); self.assertIsNone(response.json()["count"])

    async def test_first_read409_capture22_once_and_original_diagnostic(self):
        self.assertEqual((await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).status_code, 409)
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 7, tzinfo=timezone.utc)):
            response = await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.seen), 22)
        self.assertTrue((await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).json()["available"])
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})).status_code, 409)
        diagnostic = (await self.client.get("/__series_root_receipt")).json()
        self.assertEqual(len(diagnostic["captures"]), 22)
        self.assertEqual(len(self.seen), 22)

    async def test_failed_source_masks_all_and_never_retries(self):
        self.p.fetch = lambda *args: (_ for _ in ()).throw(ValueError("synthetic_missing_source"))
        with patch.object(w, "utcnow", return_value=datetime(2026, 10, 7, tzinfo=timezone.utc)):
            response = await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})
        self.assertEqual(response.status_code, 502)
        read = (await self.client.get(API_PATH + "?as_of=" + w.CUTOFF)).json()
        self.assertFalse(read["available"]); self.assertIsNone(read["count"])
        self.assertEqual(read["stocks"], []); self.assertIsNone(read["calendar"]); self.assertEqual(read["receipts"], [])
        self.assertEqual((await self.client.post(API_PATH + "/capture?as_of=" + w.CUTOFF, json={})).status_code, 409)
        self.assertEqual(self.p.request_count, 1)


if __name__ == "__main__":
    unittest.main()
