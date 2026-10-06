"""Store gates/capture ownership/concurrency without network or disk."""
from copy import deepcopy
from datetime import date
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import tpex_price as store
from worker import tpex_price_capture as worker
from test_tpex_price_capture import SyntheticPolicyScope


class PriceStoreTests(unittest.TestCase):
    def test_new_date_pins_same_capture_and_other_date_unknown_without_retry(self):
        with SyntheticPolicyScope() as old, SyntheticPolicyScope(cutoff=worker.NEW_CUTOFF) as new:
            cache = store.TpexPriceStore(loader=new.loader)
            scope = dict(instrument_type="stock", currency="TWD")
            crossed = cache.capture("TPEx", "3105", worker.NEW_CUTOFF, environment=old.env, **scope)
            self.assertEqual(crossed["reasons"], ["price_external_policy_pins_mismatch"])
            self.assertFalse(cache._attempted)
            result = cache.capture("TPEx", "3105", worker.NEW_CUTOFF, environment=new.env, **scope)
            self.assertEqual((result["latest"]["date"], result["latest"]["close"], result["supported_scope"]["cutoff"]), ("2026-10-06", 592, "2026-10-06"))
            for method in (cache.read, cache.capture):
                other = method("TPEx", "6488", worker.CUTOFF, environment=old.env, **scope)
                self.assertEqual((other["status"], other["latest"], other["reasons"]), ("unavailable", None, ["price_memory_capture_date_mismatch"]))
                self.assertFalse(other["capture_state"]["can_capture"])
                self.assertEqual(method("TPEx", "6488", worker.NEW_CUTOFF, environment=new.env, **scope)["latest"]["close"], 1205)
            self.assertEqual(len(new.opener.calls), 1)
            raw = cache.raw_capture
            with self.assertRaises(worker.PriceCaptureError): store.TpexPriceStore._validated_capture(raw, worker.CUTOFF)
            for key, bad in (("worker_version", worker.VERSION), ("source_version", "tpex-11370/2026-10-05"),
                             ("policy_version", store.POLICY_VERSION), ("policy_digest", store.POLICY_DIGEST)):
                receipt = raw.receipt; receipt[key] = bad
                with self.assertRaises(worker.PriceCaptureError): store.TpexPriceStore._validated_capture(worker.PriceCapture(raw.body, worker.canonical_bytes(receipt), raw.parsed))

    def test_reads_gates_env_pins_and_default_make_zero_requests(self):
        with SyntheticPolicyScope() as f:
            cache = store.TpexPriceStore(loader=f.loader)
            for exchange, symbol, cutoff, kind, currency, env in (
                ("TPEx", "3105", worker.CUTOFF, "stock", "TWD", {}),
                ("TPEx", "3105", None, "stock", "TWD", f.env),
                ("TPEx", "3105", date(2026, 10, 2), "stock", "TWD", f.env),
                ("TWSE", "3105", worker.CUTOFF, "stock", "TWD", f.env),
                ("TPEx", "9999", worker.CUTOFF, "stock", "TWD", f.env),
                ("TPEx", "3105", worker.CUTOFF, "etf", "TWD", f.env),
                ("TPEx", "3105", worker.CUTOFF, "stock", "USD", f.env),
                ("TPEx", "3105", worker.CUTOFF, "stock", "TWD", {**f.env, store.POLICY_DIGEST_ENV: "wrong"}),
                ("TPEx", "3105", worker.CUTOFF, "stock", "TWD", {**f.env, store.ENABLE_ENV: "yes"}),
            ):
                for method in (cache.read, cache.capture):
                    result = method(exchange, symbol, cutoff, instrument_type=kind, currency=currency, environment=env)
                    self.assertEqual(result["status"], "unavailable")
                    self.assertIsNone(result["latest"])
            ready = cache.read("TPEx", "3105", worker.CUTOFF, instrument_type="stock", currency="TWD", environment=f.env)
            self.assertTrue(ready["capture_state"]["can_capture"])
            self.assertEqual(f.opener.calls, [])

    def test_two_stocks_repeat_read_and_ownership_single_capture(self):
        with SyntheticPolicyScope() as f:
            cache = store.TpexPriceStore(loader=f.loader)
            snapshots = [cache.capture("TPEx", symbol, worker.CUTOFF, instrument_type="stock", currency="TWD", environment=f.env)
                         for symbol in ("3105", "6488", "3105")]
            self.assertEqual(len(f.opener.calls), 1)
            self.assertEqual([result["latest"]["close"] for result in snapshots], [615, 1180, 615])
            self.assertEqual(snapshots[1]["provenance"]["body_sha256"], snapshots[0]["provenance"]["body_sha256"])
            self.assertIsNone(snapshots[0]["latest"]["id"])
            self.assertIsNone(snapshots[0]["provenance"]["raw_payload_id"])
            self.assertIsNone(snapshots[0]["provenance"]["ingestion_run_id"])
            snapshots[0]["latest"]["close"] = -10
            snapshots[0]["provenance"]["endpoint"] = "wrong"
            diagnostic = cache.raw_capture
            diagnostic.parsed["selected"]["3105"]["close"] = -1
            self.assertEqual(cache.read("TPEx", "3105", worker.CUTOFF, instrument_type="stock", currency="TWD", environment=f.env)["latest"]["close"], 615)
            for cutoff, env in ((date(2026, 10, 2), f.env), (None, f.env), (worker.CUTOFF, {})):
                result = cache.read("TPEx", "3105", cutoff, instrument_type="stock", currency="TWD", environment=env)
                self.assertIsNone(result["latest"])
            self.assertEqual(len(f.opener.calls), 1)

    def test_failed_attempt_is_cached_and_never_retried(self):
        with SyntheticPolicyScope() as f:
            def failing(**kwargs):
                kwargs["on_request"]()
                raise worker.PriceCaptureError("price_feed_date_mismatch")
            cache = store.TpexPriceStore(loader=failing)
            for symbol in ("3105", "6488", "3105"):
                result = cache.capture("TPEx", symbol, worker.CUTOFF, instrument_type="stock", currency="TWD", environment=f.env)
                self.assertEqual(result["reasons"], ["price_feed_date_mismatch"])
                self.assertEqual(result["capture_state"]["request_count"], 1)
                self.assertFalse(result["capture_state"]["can_capture"])
            self.assertIsNone(cache.raw_capture)

    def test_concurrent_capture_only_one_request(self):
        with SyntheticPolicyScope() as f:
            entered, release = Event(), Event()
            def slow(**kwargs):
                entered.set()
                if not release.wait(5): raise AssertionError("test synchronization timeout")
                return f.loader(**kwargs)
            cache = store.TpexPriceStore(loader=slow)
            output = []
            thread = Thread(target=lambda: output.append(cache.capture("TPEx", "3105", worker.CUTOFF, instrument_type="stock", currency="TWD", environment=f.env)))
            thread.start()
            self.assertTrue(entered.wait(5))
            busy = cache.capture("TPEx", "6488", worker.CUTOFF, instrument_type="stock", currency="TWD", environment=f.env)
            self.assertEqual(busy["capture_state"]["action"], "busy")
            release.set(); thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(f.opener.calls), 1)
            self.assertEqual(output[0]["status"], "available")

    def test_receipt_parsed_body_policy_pollution_rejected(self):
        with SyntheticPolicyScope() as f:
            value = f.loader(policy=worker.price_policy(), expected_policy_version=store.POLICY_VERSION, expected_policy_digest=store.POLICY_DIGEST)
            for field, bad in (("endpoint", "https://example.com"), ("policy_digest", "wrong"), ("source_id", "tpex"),
                               ("storage", "disk"), ("captured_at", "2026-10-05T14:02:03+00:00"), ("attribution", {})):
                receipt = value.receipt; receipt[field] = bad
                altered = worker.PriceCapture(value.body, worker.canonical_bytes(receipt), value.parsed)
                with self.subTest(field=field), self.assertRaises(worker.PriceCaptureError): cache_value = store.TpexPriceStore._validated_capture(altered)
            parsed = deepcopy(value.parsed); parsed["selected"]["3105"]["volume_exact"] = "1"
            with self.assertRaises(worker.PriceCaptureError): store.TpexPriceStore._validated_capture(worker.PriceCapture(value.body, value.receipt_bytes, parsed))

    def test_catalog_name_market_type_etf_currency_positive_gate(self):
        with SyntheticPolicyScope() as f:
            cache = store.TpexPriceStore(loader=f.loader)
            base = dict(market="TW", exchange="TPEx", symbol="3105", name="穩懋", instrument_type="stock", etf_category=None)
            with patch.object(store, "STORE", cache), patch.dict("os.environ", f.env):
                for key, value in (("market", "US"), ("name", "unknown"), ("instrument_type", "etf"), ("etf_category", "domestic"), ("currency", "USD")):
                    result = store.capture_tpex_price(SimpleNamespace(**{**base, key: value}), worker.CUTOFF)
                    self.assertEqual(result["reasons"], ["price_instrument_not_supported"])
                self.assertEqual(f.opener.calls, [])
                self.assertEqual(store.capture_tpex_price(SimpleNamespace(**base), worker.CUTOFF)["status"], "available")
