"""Bounded synthetic disk phases; invoke only the private-save guarded entrypoint."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from test_tpex_price_api import MemoryAPIFixture
from worker import tpex_price_capture as capture_worker
from worker import tpex_price_storage as storage


@contextmanager
def synthetic_private(root):
    from app import tpex_price, tpex_price_saved
    fixture = MemoryAPIFixture(cutoff=capture_worker.NEW_CUTOFF, policy_version=capture_worker.SEVENTH_SCOPE_POLICY_VERSION)
    with ExitStack() as stack:
        stack.callback(fixture.close)
        policy = storage.storage_policy()
        policy["capture_policy_digest"] = fixture.fixture.env[tpex_price.POLICY_DIGEST_ENV]
        policy["validation"]["expected_body_sha256"] = hashlib.sha256(fixture.fixture.body).hexdigest()
        pin = storage.digest(policy)
        stack.enter_context(patch.object(storage, "_STORAGE_POLICY", policy))
        stack.enter_context(patch.object(storage, "STORAGE_POLICY_DIGEST", pin))
        stack.enter_context(patch.object(tpex_price_saved, "STORAGE_POLICY_DIGEST", pin))
        stack.enter_context(patch.object(tpex_price_saved, "CAPTURE_POLICY_DIGEST", policy["capture_policy_digest"]))
        env = {**fixture.fixture.env, tpex_price_saved.ENABLE_ENV: "1", tpex_price_saved.ROOT_ENV: str(root),
            tpex_price_saved.VERSION_ENV: storage.STORAGE_POLICY_VERSION, tpex_price_saved.DIGEST_ENV: pin}
        stack.enter_context(patch.dict(os.environ, env))
        yield fixture, policy, pin, env


def options(root, policy, pin):
    return {"root": root, "policy": policy, "expected_policy_version": storage.STORAGE_POLICY_VERSION, "expected_policy_digest": pin}


class PrivateGateTests(unittest.TestCase):
    def test_independent_policy_and_all_pre_io_gates(self):
        from app import tpex_price, tpex_price_saved as app
        root = Path(os.environ["LOCALAPPDATA"]) / "taiwan-stock-research/price-save-tests-01a11367"
        original = capture_worker.canonical_bytes(storage.storage_policy())
        self.assertEqual(len(original), 2437)
        self.assertEqual(storage.digest(storage.storage_policy()), storage.STORAGE_POLICY_DIGEST)
        self.assertEqual(capture_worker.price_policy(capture_worker.NEW_CUTOFF)["storage"], "process_memory")
        with synthetic_private(root) as (fixture, policy, pin, env):
            with fixture.engine.connect() as db:
                # Existing schema and catalogue only; no on-disk database.
                row = db.exec_driver_sql("SELECT symbol FROM instruments WHERE symbol='6510'").first()
                self.assertEqual(row[0], "6510")
            from app.models import Instrument
            instrument = Instrument(exchange="TPEx", symbol="6510", name="精測", market="TW", instrument_type="stock")
            variants = [({app.ENABLE_ENV: "0"}, "price_private_store_not_enabled"),
                ({app.ENABLE_ENV: "bad"}, "price_private_configuration_invalid"),
                ({app.VERSION_ENV: "bad"}, "price_storage_policy_pins_mismatch"),
                ({app.DIGEST_ENV: "sha256:" + "0" * 64}, "price_storage_policy_pins_mismatch"),
                ({tpex_price.POLICY_VERSION_ENV: "m1-price-tpex-11370-2026-10-06.1"}, "price_storage_source_pins_mismatch"),
                ({tpex_price.POLICY_DIGEST_ENV: "bad"}, "price_storage_source_pins_mismatch"),
                ({app.ROOT_ENV: ""}, "price_storage_root_invalid")]
            with patch.object(app, "reopen_capture", side_effect=AssertionError("pre-IO gate failed")), patch.object(app, "save_capture", side_effect=AssertionError("pre-IO gate failed")):
                for changes, reason in variants:
                    for save in (False, True):
                        result = app.private_price(instrument, capture_worker.NEW_CUTOFF, save=save, environment={**env, **changes})
                        self.assertEqual(result["reasons"], [reason])
                for day in (None, date(2026, 10, 5), date(2026, 10, 7)):
                    self.assertEqual(app.private_price(instrument, day, environment=env)["reasons"], ["price_saved_cutoff_not_supported"])
                for field, value in (("exchange", "TWSE"), ("name", "wrong"), ("instrument_type", "etf"), ("market", "US"), ("etf_category", "domestic")):
                    with patch.object(instrument, field, value):
                        self.assertEqual(app.private_price(instrument, capture_worker.NEW_CUTOFF, environment=env)["reasons"], ["price_saved_instrument_not_supported"])
                self.assertEqual(app.private_price(instrument, capture_worker.NEW_CUTOFF, save=True, environment=env)["reasons"], ["price_saved_memory_capture_missing"])
            self.assertEqual(fixture.store._request_count, 0)
            self.assertEqual(fixture.before, fixture.snapshot())
        self.assertEqual(capture_worker.canonical_bytes(storage.storage_policy()), original)


def _cleanup(root: Path) -> dict:
    failures = []
    if root.exists():
        try:
            storage._plain(root, directory=True)
            if {p.name for p in root.iterdir()} - {storage.DIRECTORY, storage.STAGING}:
                raise ValueError("unexpected root entries")
            for folder in (root / storage.STAGING, root / storage.DIRECTORY):
                if not folder.exists():
                    continue
                storage._plain(folder, directory=True)
                files = list(folder.iterdir())
                if {p.name for p in files} - (set(storage.FILES) | {"probe.json"}):
                    raise ValueError("unexpected child entries")
                for file in files:
                    # A known synthetic hardlink probe may be removed after its rejection.
                    info = file.lstat()
                    if getattr(info, "st_file_attributes", 0) & 1024 or not file.is_file() or file.is_symlink():
                        raise ValueError("unsafe cleanup entry")
                    file.unlink()
                folder.rmdir()
            root.rmdir()
        except (OSError, ValueError) as exc:
            failures.append({"path": str(root), "reason": str(exc)})
    return {"passed": not failures, "test_root_absent": not root.exists(), "cleanup_failures": failures,
        "common_parent_present": root.parent.exists(), "common_parent_cleanup": "coordinator owns shared parent after both roots"}


def run_phase(phase: str, root: Path) -> dict:
    if phase == "cleanup":
        return _cleanup(root)
    if phase == "check":
        run = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PrivateGateTests))
        return {"passed": run.wasSuccessful(), "tests": run.testsRun, "failures": len(run.failures), "errors": len(run.errors), "disk": "not run"}
    count = 0
    def check(condition, message):
        nonlocal count
        count += 1
        if not condition:
            raise AssertionError(message)
    with synthetic_private(root) as (fixture, policy, pin, env):
        from app import tpex_price, tpex_price_saved as app
        from fastapi.testclient import TestClient
        kwargs = options(root, policy, pin)
        check(len(fixture.fixture.body) <= 80 * 1024 and len(capture_worker.policy_symbols(capture_worker.NEW_CUTOFF)) == 7, "bounded seven-row synthetic fixture")
        client = TestClient(fixture.app)
        if phase == "write":
            check(not root.exists(), "single owned case root must be absent before creation")
            fixture.store.capture("TPEx", "6510", capture_worker.NEW_CUTOFF, instrument_type="stock", currency="TWD")
            original = fixture.store.raw_capture
            result = client.post("/api/stocks/TPEx/6510/prices/save?as_of=2026-10-06").json()
            check(result["status"] == "available" and result["storage_state"]["action"] == "saved", "actual router saves synthetic source")
            folder = root / storage.DIRECTORY
            check((folder / storage.FILES[0]).read_bytes() == original.body, "full raw exact bytes")
            check((folder / storage.FILES[1]).read_bytes() == original.receipt_bytes, "canonical original receipt exact bytes")
            check(result["provenance"]["storage"] == "process_memory" and result["origin"] == "private_local", "distinct observation/storage facts")
            second = client.post("/api/stocks/TPEx/3105/prices/save?as_of=2026-10-06").json()
            check(second["storage_state"]["action"] == "already_saved", "idempotent second stock save")
            check(second["storage_provenance"] == result["storage_provenance"], "idempotence preserves save time/hash")
            check(fixture.store._request_count == 1, "save adds no source request")
        elif phase == "read":
            check(fixture.store.raw_capture is None and not fixture.store._attempted, "NEW process starts with empty Store")
            fixture.store._loader = lambda **kwargs: (_ for _ in ()).throw(AssertionError("reopen called source loader"))
            with patch.dict(os.environ, {tpex_price.ENABLE_ENV: "0"}):
                for symbol in capture_worker.policy_symbols(capture_worker.NEW_CUTOFF):
                    result = client.get(f"/api/stocks/TPEx/{symbol}/prices/saved?as_of=2026-10-06").json()
                    check(result["status"] == "available" and result["storage_state"]["action"] == "reopened", "new process independent saved API")
                    expected = capture_worker.parse_price_csv(fixture.fixture.body, cutoff=capture_worker.NEW_CUTOFF)["selected"][symbol]
                    check(result["latest"]["source_fields"] == expected["source_fields"], "all eighteen source fields reprojected")
                    for field in ("open", "high", "low", "close", "volume_exact", "turnover_exact"):
                        check(result["latest"][field] == expected[field], "selected financial field reprojected")
                    check(str(root) not in json.dumps(result), "API exposes no private root")
                check(client.post("/api/stocks/TPEx/6510/prices/save?as_of=2026-10-06").json()["reasons"] == ["price_saved_memory_capture_missing"], "no implicit hydrate/fetch on save")
                for suffix in ("", "?as_of=2026-10-05", "?as_of=2026-10-07"):
                    check(client.get("/api/stocks/TPEx/6510/prices/saved" + suffix).json()["status"] == "unavailable", "explicit supported day only")
            check(fixture.store._request_count == 0 and fixture.store.raw_capture is None, "no loader/hydration/source requests")
        elif phase == "faults":
            folder = root / storage.DIRECTORY
            original = {name: (folder / name).read_bytes() for name in storage.FILES}
            def rejects():
                try:
                    storage.reopen_capture(**kwargs)
                except storage.PriceStorageError:
                    return True
                return False
            cases = [(storage.FILES[0], original[storage.FILES[0]] + b" "),
                (storage.FILES[1], original[storage.FILES[1]] + b"\n")]
            for name, key, value in ((storage.FILES[1], "body_sha256", "0" * 64),
                    (storage.FILES[1], "storage", "private_local"), (storage.FILES[1], "extra", True),
                    (storage.FILES[2], "version", "wrong"), (storage.FILES[2], "storage_policy_digest", "bad"),
                    (storage.FILES[2], "capture_receipt_sha256", "0" * 64), (storage.FILES[2], "extra", True),
                    (storage.FILES[2], "body_bytes", True), (storage.FILES[2], "saved_at", "2026-10-04T00:00:00Z")):
                altered = json.loads(original[name]); altered[key] = value
                cases.append((name, capture_worker.canonical_bytes(altered)))
            for name, altered in cases:
                try:
                    (folder / name).write_bytes(altered)
                    check(rejects(), "corruption/canonical/schema/time/type rejected")
                finally:
                    (folder / name).write_bytes(original[name])
            probe = folder / "probe.json"
            try:
                os.link(folder / storage.FILES[0], probe)
                with unittest.TestCase().assertRaises(storage.PriceStorageError):
                    storage._read(folder / storage.FILES[0], 3145728)
                check(rejects(), "unexpected file/hardlink rejected")
            finally:
                if probe.exists(): probe.unlink()
            pending = root / storage.STAGING
            try:
                pending.mkdir()
                check(rejects(), "interrupted staging never admitted")
            finally:
                pending.rmdir()
            with unittest.TestCase().assertRaises(storage.PriceStorageError):
                storage.reopen_capture(**{**kwargs, "root": root.parent / ".." / root.name})
            check(all((folder / name).read_bytes() == data for name, data in original.items()), "fault probes restore exact valid files")
            good = storage.reopen_capture(**kwargs)[0]
            for name in storage.FILES: (folder / name).unlink()
            folder.rmdir()
            with patch.object(storage.os, "rename", side_effect=OSError("injected publish failure")):
                with unittest.TestCase().assertRaises(OSError): storage.save_capture(good, **kwargs)
            check(not list(root.iterdir()), "failed atomic publish leaves no partial admitted or staged files")
            storage.save_capture(good, **kwargs)
            check(storage.reopen_capture(**kwargs)[0].receipt_bytes == good.receipt_bytes, "valid save after owned failure cleanup")
        else:
            raise ValueError("unknown disk phase")
        check(fixture.before == fixture.snapshot(), "every database table preserved")
        capture, receipt, sha = storage.reopen_capture(**kwargs)
        summary = {"passed": True, "checks": count, "pid": os.getpid(), "fixture": "synthetic seven-row CSV; not official raw",
            "fixture_bytes": len(fixture.fixture.body), "raw_sha256": hashlib.sha256(capture.body).hexdigest(),
            "capture_receipt_sha256": receipt["capture_receipt_sha256"], "storage_receipt_sha256": sha,
            "source_requests": fixture.store._request_count if phase == "write" else 0,
            "retention": "three owned synthetic files only until NEW-process read/faults; caller finally runs cleanup"}
        client.close()
        return summary
