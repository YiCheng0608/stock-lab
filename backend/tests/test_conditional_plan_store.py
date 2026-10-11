"""Standalone RAM self-tests; no pytest/conftest/app imports or disk cases.

Run from repository root with Python -B -X utf8. An audit hook is installed
before source loading. Actual filesystem persistence, failure injection,
cross-process reads, path alias behavior and cleanup remain independent QA.
The sample records are controlled nonfinancial declarations, not valid Plans.
"""

import sys
import os

sys.dont_write_bytecode = True
GUARD = {"disk_mutation_attempts": 0, "network_attempts": 0, "subprocess_attempts": 0, "open_reads": 0, "path_io_calls": 0, "storage_entry_calls": 0}
_MUTATIONS = frozenset({"os.mkdir", "os.rmdir", "os.remove", "os.rename", "os.link", "os.symlink", "os.chmod", "os.chown", "os.truncate", "os.utime", "shutil.copyfile", "shutil.copymode", "shutil.copystat"})


def audit(event, args):
    if event == "open":
        mode = args[1]
        flags = args[2]
        write = (type(mode) is str and any(char in mode for char in "wax+")) or (type(flags) is int and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if write:
            GUARD["disk_mutation_attempts"] += 1
            raise RuntimeError("RAM self-test: disk mutation forbidden")
        GUARD["open_reads"] += 1
    elif event in _MUTATIONS:
        GUARD["disk_mutation_attempts"] += 1
        raise RuntimeError("RAM self-test: disk mutation forbidden")
    elif event.startswith("socket."):
        GUARD["network_attempts"] += 1
        raise RuntimeError("RAM self-test: network forbidden")
    elif event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn"):
        GUARD["subprocess_attempts"] += 1
        raise RuntimeError("RAM self-test: subprocess forbidden")


sys.addaudithook(audit)

import ast
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend" / "app" / "conditional_plan_store.py"
CLI_SOURCE = ROOT / "tools" / "conditional-plan-store.py"
SOURCE_RAW = SOURCE.read_bytes()
SOURCE_SHA256 = hashlib.sha256(SOURCE_RAW).hexdigest()
CLI_RAW = CLI_SOURCE.read_bytes()
CLI_SHA256 = hashlib.sha256(CLI_RAW).hexdigest()


def direct_load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


store = direct_load("conditional_plan_store_ram_selftest", SOURCE)
cli = direct_load("conditional_plan_store_cli_ram_selftest", CLI_SOURCE)
assert Path(store.__file__).resolve() == SOURCE
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
assert Path(cli.__file__).resolve() == CLI_SOURCE
assert hashlib.sha256(CLI_SOURCE.read_bytes()).hexdigest() == CLI_SHA256
assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
assert store.validate_record.__code__.co_filename == str(SOURCE)


def profile(frame, event, arg):
    if event == "call" and frame.f_code.co_filename == str(SOURCE):
        if frame.f_code.co_name in ("initialize_plan_store", "save_plan_record", "read_plan_record"):
            GUARD["storage_entry_calls"] += 1
            raise RuntimeError("RAM self-test: storage entry invocation forbidden")
        if frame.f_code.co_name in ("_path_guard", "_regular", "_read_file", "_create_new", "_verify_owner"):
            GUARD["path_io_calls"] += 1


sys.setprofile(profile)


def wire(raw):
    """Independent stdlib wire oracle, separate from the product codec."""
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


ABS_ROOT = str(ROOT / "issue35-controlled-selftest-not-created")
UTC = "2026-10-05T08:00:00.123456Z"
OWNER_WIRE = {
    "schema": "conditional-plan-store-ownership/v1", "store_version": "conditional-plan-store/v1",
    "issue": 35, "namespace": "issue35-conditional-plan-storage-two-cutoffs-v1/qa1",
    "actual_qa_session": "RAM-only-no-QA-claim", "root_id": "RAM-root-never-created",
    "absolute_root": ABS_ROOT, "plan_id": "controlled_3105", "allowed_revisions": [1, 2],
    "created_at": UTC,
}
OWNER = wire(OWNER_WIRE)


def controlled_record(revision=1, parent=None):
    payload = {"controlled": "nonfinancial", "quantum": {"$type": "decimal", "sign": 0, "digits": "100", "exponent": -2}, "instant": {"$type": "datetime", "utc": UTC}}
    original = {"controlled_input": "not_a_financial_plan", "unknown_source": True}
    config = {"controlled_config": revision, "label": "測試"}
    return {
        "record_version": "conditional-plan-record/v1", "plan_id": "controlled_3105", "revision": revision,
        "parent_record_sha256": parent,
        "identity": {"market": "TPEx", "instrument": "ordinary_stock", "symbol": "3105", "strategy_id": "breakout_v1"},
        "as_of": "2026-10-05" if revision == 1 else "2026-10-06",
        "generated_at": UTC, "decision_at": UTC,
        "declared_versions": {"payload_schema_id": "controlled-storage-oracle/v1", "payload_schema_sha256": "a" * 64, "plan_version": "controlled/v1", "strategy_version": "declared/v1", "rule_version": "declared/v" + str(revision), "rule_sha256": "b" * 64, "execution_version": "not-evaluated/v1", "config_version": "controlled/v" + str(revision)},
        "source_refs": [{"role": "controlled", "source_id": "unverified", "source_version": "declared", "snapshot_sha256": None, "revision_id": "cutoff-" + str(revision), "time_evidence_sha256": None}],
        "plan_payload": payload, "plan_payload_sha256": digest(wire(payload)),
        "original_inputs": original, "original_inputs_sha256": digest(wire(original)),
        "config_snapshot": config, "config_sha256": digest(wire(config)), "semantic_status": "not_asserted",
    }


BIND_FIELDS = (
    "record_version", "plan_id", "revision", "parent_record_sha256", "identity", "as_of",
    "generated_at", "decision_at", "declared_versions", "source_refs", "plan_payload_sha256",
    "original_inputs_sha256", "config_sha256", "semantic_status",
)


def binding(record):
    result = {key: record[key] for key in BIND_FIELDS}
    result.update(schema="conditional-plan-binding/v1", store_version="conditional-plan-store/v1", absolute_root=ABS_ROOT)
    return wire(result)


def expectations(record):
    return {"root": ABS_ROOT, "expected_ownership": OWNER, "expected_ownership_sha256": digest(OWNER), "expected_record_sha256": digest(wire(record)), "expected_binding": binding(record)}


class CodecTests(unittest.TestCase):
    def reject(self, operation, code=None):
        with self.assertRaises(store.PlanStoreError) as caught:
            operation()
        if code:
            self.assertEqual(caught.exception.code, code)

    def test_exact_golden_bytes_and_tuple(self):
        native = {"z": Decimal("-0.00"), "a": Decimal("1.00"), "t": datetime(2026, 10, 5, 16, 0, 0, 123456, tzinfo=timezone(timedelta(hours=8)))}
        golden = b'{"a":{"$type":"decimal","digits":"100","exponent":-2,"sign":0},"t":{"$type":"datetime","utc":"2026-10-05T08:00:00.123456Z"},"z":{"$type":"decimal","digits":"0","exponent":-2,"sign":1}}'
        encoded = store.canonical_encode(native)
        self.assertEqual(encoded, golden)
        self.assertEqual(store.sha256(encoded), digest(golden))
        decoded = store.canonical_decode(golden)
        self.assertEqual(decoded["a"].as_tuple(), (0, (1, 0, 0), -2))
        self.assertEqual(decoded["z"].as_tuple(), (1, (0,), -2))
        self.assertEqual(decoded["t"], native["t"])
        self.assertNotEqual(store.canonical_encode(Decimal("1.00")), store.canonical_encode(Decimal("1.0")))

    def test_revision2_derived_quantum_with_independent_arithmetic(self):
        with localcontext() as context:
            context.prec = 50
            derived = Decimal("2.00000000") * (1 - Decimal("0.00000001")) - Decimal("1.00000000") * (1 + Decimal("0.00000001"))
        self.assertEqual(derived.as_tuple(), (0, (9, 9, 9, 9, 9, 9, 9, 7, 0, 0, 0, 0, 0, 0, 0, 0), -16))
        golden = b'{"$type":"decimal","digits":"9999999700000000","exponent":-16,"sign":0}'
        self.assertEqual(store.canonical_encode(derived), golden)
        self.assertEqual(store.canonical_decode(golden).as_tuple(), derived.as_tuple())

    def test_decimal_representation_limits_and_context_independence(self):
        for exponent in (-1000000, 1000000):
            for sign in (0, 1):
                for digits in ((0,), (1,), (9,) * 50):
                    value = Decimal((sign, digits, exponent))
                    with localcontext() as context:
                        context.prec = 2
                        encoded = store.canonical_encode(value)
                        decoded = store.canonical_decode(encoded)
                    self.assertEqual(decoded.as_tuple(), value.as_tuple())
                    self.assertLess(len(encoded), 150)
        for value in (Decimal((0, (1,), -1000001)), Decimal((0, (1,), 1000001)), Decimal((0, (1,) * 51, 0)), Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")):
            self.reject(lambda value=value: store.canonical_encode(value))

    def test_tag_shapes_exact_int_and_reserved_collision(self):
        good = {"$type": "decimal", "digits": "100", "exponent": -2, "sign": 0}
        for key, value in (("sign", False), ("sign", True), ("sign", 2), ("exponent", False), ("exponent", True), ("exponent", -1000001), ("exponent", 1000001), ("digits", "00"), ("digits", "01"), ("digits", "١"), ("digits", "1" * 51)):
            tag = dict(good, **{key: value})
            self.reject(lambda tag=tag: store.canonical_decode(wire(tag)))
        self.reject(lambda: store.canonical_encode(good), "reserved_tag_collision")
        for tag in ({"$type": "unknown"}, dict(good, extra=1), {"$type": "datetime", "utc": UTC, "extra": 1}, {"$type": False}):
            self.reject(lambda tag=tag: store.canonical_decode(wire(tag)))

    def test_canonical_utf8_and_duplicate_keys(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":1,"\\u0061":2}', b'{ "a":1}', b'{"b":2,"a":1}', b'{"a":1}\n', b'\xef\xbb\xbf{}', b'{}{}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1.0}', b'{"x":1e0}', b'{"x":-0}', b'"\\ud800"', b'\xff'):
            self.reject(lambda raw=raw: store.canonical_decode(raw))
        self.assertEqual(store.canonical_encode({"字": "é"}), '{"字":"é"}'.encode("utf-8"))
        self.assertNotEqual(store.canonical_encode("é"), store.canonical_encode("e\u0301"))

    def test_datetime_invalid_or_naive(self):
        self.reject(lambda: store.canonical_encode(datetime(2026, 10, 5)), "aware_datetime_required")
        for value in ("2026-02-30T08:00:00.000000Z", "2026-10-05T08:00:00Z", "2026-10-05T08:00:00.000000+00:00", "2026-10-05T08:00:00.000000z", "0000-10-05T08:00:00.000000Z"):
            self.reject(lambda value=value: store.canonical_decode(wire({"$type": "datetime", "utc": value})))

    def test_tree_and_scalar_bounds_include_tag_members(self):
        value = None
        for _ in range(15):
            value = [value]
        self.assertEqual(store.canonical_decode(store.canonical_encode(value)), value)
        self.reject(lambda: store.canonical_encode([value]), "tree_limit")
        typed = Decimal("1.00")
        for _ in range(15):
            typed = [typed]
        self.reject(lambda: store.canonical_encode(typed), "tree_limit")
        self.reject(lambda: store.canonical_decode(b"[" * 1000 + b"0" + b"]" * 1000), "tree_limit")
        self.assertEqual(len(store.canonical_decode(store.canonical_encode([None] * 1024))), 1024)
        self.reject(lambda: store.canonical_encode([None] * 1025), "list_limit")
        self.reject(lambda: store.canonical_encode([[None] * 1024 for _ in range(8)]), "tree_limit")
        self.assertEqual(store.canonical_decode(store.canonical_encode({"x" * 128: "x" * 4096})), {"x" * 128: "x" * 4096})
        self.reject(lambda: store.canonical_encode({"x" * 129: 1}), "key_limit")
        self.reject(lambda: store.canonical_encode("x" * 4097), "string_limit")
        self.reject(lambda: store.canonical_encode("界" * 1366), "string_limit")
        self.reject(lambda: store.canonical_decode(b" " * 65537), "byte_limit")
        self.reject(lambda: store.canonical_encode(["x" * 4096] * 16), "byte_limit")

    def test_exact_byte_and_node_boundaries(self):
        for cap in (True, False, 0, -1, 65537):
            self.reject(lambda cap=cap: store.canonical_encode({}, max_bytes=cap), "byte_cap_required")
            self.reject(lambda cap=cap: store.canonical_decode(b"{}", max_bytes=cap), "byte_cap_required")
        # 16 string quotes + 15 commas + brackets contribute 49 bytes.
        exact_bytes = ["x" * 4093] * 15 + ["x" * 4092]
        oracle = wire(exact_bytes)
        self.assertEqual(len(oracle), 65536)
        self.assertEqual(store.canonical_encode(exact_bytes), oracle)
        self.assertEqual(store.canonical_decode(oracle), exact_bytes)
        self.reject(lambda: store.canonical_encode(["x" * 4093] * 16), "byte_limit")
        # root + 8 list nodes + (7*1024+1015) scalar values = 8192.
        exact_nodes = [[None] * 1024 for _ in range(7)] + [[None] * 1015]
        self.assertEqual(store.canonical_decode(store.canonical_encode(exact_nodes)), exact_nodes)
        self.reject(lambda: store.canonical_encode(exact_nodes[:-1] + [[None] * 1016]), "tree_limit")

    def test_unsupported_native_types(self):
        for value in (1.0, float("nan"), (1, 2), {1}, b"x", {1: "x"}, date_for_test()):
            self.reject(lambda value=value: store.canonical_encode(value))


def date_for_test():
    return datetime(2026, 10, 5).date()


class EnvelopeTests(unittest.TestCase):
    reject = CodecTests.reject
    def validate(self, record, **changes):
        args = expectations(record)
        args.update(changes)
        return store.validate_record(wire(record), **args)

    def test_controlled_full_envelope_external_oracle(self):
        record = controlled_record()
        self.assertEqual(store.canonical_encode(self.validate(record)), wire(record))
        self.assertEqual(self.validate(record)["plan_payload"]["quantum"].as_tuple(), (0, (1, 0, 0), -2))
        self.assertEqual(self.validate(record)["plan_payload"]["instant"], datetime(2026, 10, 5, 8, 0, 0, 123456, timezone.utc))
        self.assertIsNone(self.validate(record)["source_refs"][0]["snapshot_sha256"])

    def test_envelope_exactfields_and_typed_metadata(self):
        good = controlled_record()
        for key, value in (("revision", True), ("revision", 0), ("revision", 1000000), ("as_of", "2026-02-30"), ("as_of", "2026-2-03"), ("generated_at", "unknown"), ("decision_at", "2026-10-05T08:00:00Z"), ("parent_record_sha256", "a" * 64), ("plan_id", "../plan"), ("semantic_status", "valid"), ("record_version", "unknown")):
            record = dict(good, **{key: value})
            self.reject(lambda record=record: self.validate(record))
        unknown = dict(good, latest=True)
        self.reject(lambda: self.validate(unknown), "exact_fields_required")
        for key in good:
            record = {k: v for k, v in good.items() if k != key}
            external = expectations(good)
            external["expected_record_sha256"] = digest(wire(record))
            self.reject(lambda record=record, external=external: store.validate_record(wire(record), **external), "exact_fields_required")

    def test_seven_identity_enum_contract_only(self):
        for symbol in ("3105", "3293", "5274", "5347", "6488", "6510", "8069"):
            record = controlled_record()
            record["identity"] = dict(record["identity"], symbol=symbol)
            self.assertEqual(self.validate(record)["identity"]["symbol"], symbol)
        for key, value in (("symbol", "2330"), ("market", "TWSE"), ("instrument", "ETF"), ("strategy_id", "trailing_v1")):
            record = controlled_record()
            record["identity"] = dict(record["identity"], **{key: value})
            self.reject(lambda record=record: self.validate(record), "unsupported_identity")

    def test_refs_versions_and_subtree_hashes(self):
        good = controlled_record()
        for key in ("plan_payload_sha256", "original_inputs_sha256", "config_sha256"):
            record = dict(good, **{key: "c" * 64})
            self.reject(lambda record=record: self.validate(record), "subtree_sha256_mismatch")
        for refs in ([], good["source_refs"] * 2, good["source_refs"] * 33):
            record = dict(good, source_refs=refs)
            self.reject(lambda record=record: self.validate(record))
        for key, value in (("snapshot_sha256", "A" * 64), ("source_id", ""), ("role", "界" * 43), ("time_evidence_sha256", False)):
            record = dict(good, source_refs=[dict(good["source_refs"][0], **{key: value})])
            self.reject(lambda record=record: self.validate(record))
        for key, value in (("plan_version", "界"), ("rule_sha256", "x" * 64), ("config_version", "x" * 129)):
            record = dict(good, declared_versions=dict(good["declared_versions"], **{key: value}))
            self.reject(lambda record=record: self.validate(record))

    def test_full_record_chain_and_fixed_identity_schema(self):
        r1 = controlled_record()
        r2 = controlled_record(2, digest(wire(r1)))
        self.assertEqual(store.validate_revision_chain(wire(r2), wire(r1))["as_of"], "2026-10-06")
        self.reject(lambda: store.validate_revision_chain(wire(r2), None), "parent_required")
        self.reject(lambda: store.validate_revision_chain(wire(r1), wire(r2)), "unexpected_parent")
        wrong_parent = dict(r2, parent_record_sha256=r1["plan_payload_sha256"])
        self.reject(lambda: store.validate_revision_chain(wire(wrong_parent), wire(r1)), "parent_full_record_mismatch")
        for key, value in (("symbol", "3293"), ("strategy_id", "pullback_v1")):
            changed = dict(r2, identity=dict(r2["identity"], **{key: value}))
            self.reject(lambda changed=changed: store.validate_revision_chain(wire(changed), wire(r1)), "identity_or_schema_changed")
        for key, value in (("payload_schema_id", "controlled/v2"), ("payload_schema_sha256", "c" * 64)):
            changed = dict(r2, declared_versions=dict(r2["declared_versions"], **{key: value}))
            self.reject(lambda changed=changed: store.validate_revision_chain(wire(changed), wire(r1)), "identity_or_schema_changed")
        altered_r1 = dict(r1, generated_at="2026-10-05T08:00:00.000000Z")
        self.reject(lambda: store.validate_revision_chain(wire(r2), wire(altered_r1)), "parent_full_record_mismatch")

    def test_exact_external_binding_every_field_and_no_io(self):
        record = controlled_record()
        args = expectations(record)
        before = dict(GUARD)
        for key in json.loads(args["expected_binding"]):
            wrong = json.loads(args["expected_binding"])
            wrong.pop(key)
            self.reject(lambda wrong=wrong: self.validate(record, expected_binding=wire(wrong)))
        wrong = json.loads(args["expected_binding"])
        wrong["source_refs"][0]["source_version"] = "changed"
        self.reject(lambda: self.validate(record, expected_binding=wire(wrong)), "exact_binding_mismatch")
        self.reject(lambda: self.validate(record, expected_record_sha256="f" * 64), "record_sha256_mismatch")
        self.reject(lambda: self.validate(record, expected_binding=args["expected_binding"] + b"\n"), "noncanonical_bytes")
        self.reject(lambda: self.validate(record, expected_binding=b'{"schema":"x","schema":"y"}'), "duplicate_key")
        self.assertEqual(GUARD, before)

    def test_owner_bounds_exact_external_match_and_alias_syntax(self):
        self.assertEqual(store.validate_ownership(ABS_ROOT, OWNER, digest(OWNER)), OWNER_WIRE)
        for key, value in (("issue", True), ("store_version", "unknown"), ("schema", "unknown"), ("absolute_root", ABS_ROOT + "-other"), ("plan_id", "bad space"), ("allowed_revisions", [1, True]), ("allowed_revisions", [1, 1]), ("allowed_revisions", [2]), ("allowed_revisions", [1, 3]), ("allowed_revisions", [2, 1]), ("allowed_revisions", []), ("created_at", "unknown")):
            owner = wire(dict(OWNER_WIRE, **{key: value}))
            self.reject(lambda owner=owner: store.validate_ownership(ABS_ROOT, owner, digest(owner)))
        self.reject(lambda: store.validate_ownership(ABS_ROOT, OWNER, "f" * 64), "ownership_sha256_mismatch")
        self.reject(lambda: store.validate_ownership("relative", OWNER, digest(OWNER)), "normalized_absolute_root_required")
        self.reject(lambda: store.validate_ownership(ABS_ROOT + os.sep + ".." + os.sep + "alias", OWNER, digest(OWNER)), "normalized_absolute_root_required")
        big = wire(dict(OWNER_WIRE, namespace="x" * 2048))
        self.reject(lambda: store.validate_ownership(ABS_ROOT, big, digest(big)), "byte_limit")

    def test_pure_validators_reject_external_errors_without_path_io(self):
        record = controlled_record()
        args = expectations(record)
        before = dict(GUARD)
        wrong = dict(args, expected_record_sha256="f" * 64)
        self.reject(lambda: store.validate_record(wire(record), **wrong), "record_sha256_mismatch")
        wrong = dict(args, expected_binding=b"{}")
        self.reject(lambda: store.validate_record(wire(record), **wrong), "exact_fields_required")
        self.reject(lambda: store.validate_ownership(ABS_ROOT, OWNER, "f" * 64), "ownership_sha256_mismatch")
        self.assertEqual(GUARD, before)

    def test_root_lexical_characters_rejected_before_path_io(self):
        before = dict(GUARD)
        invalid_roots = [ABS_ROOT + chr(0) + "bad"]
        if os.name == "nt":
            invalid_roots += [ABS_ROOT + char + "bad" for char in '<>"|?*:']
            invalid_roots += [ABS_ROOT + chr(code) + "bad" for code in range(1, 32)]
        for root in invalid_roots:
            # Independent external owner bytes/hash, otherwise valid. This
            # reproduces the owner's NUL/?bad cases without storage entry.
            external = wire(dict(OWNER_WIRE, absolute_root=root))
            self.reject(lambda root=root, external=external: store.validate_ownership(root, external, digest(external)), "root_character_forbidden")
        for root in (ABS_ROOT, ABS_ROOT + "-legal_2026", ABS_ROOT + "-合法 root()@.v1"):
            external_owner = dict(OWNER_WIRE, absolute_root=root)
            external = wire(external_owner)
            self.assertEqual(store.validate_ownership(root, external, digest(external)), external_owner)
        self.assertEqual(GUARD, before)


class CompatibilityTests(unittest.TestCase):
    reject = CodecTests.reject
    def test_known_caller_input_fields_and_derived_quantum(self):
        # No calculator import or complete financial Plan is generated here.
        record = controlled_record()
        record["declared_versions"]["payload_schema_id"] = "caller-trade-plan/v1"
        record["declared_versions"]["plan_version"] = "caller-trade-plan/v1"
        record["declared_versions"]["execution_version"] = "caller-execution/v1"
        plan = {key: Decimal("1.00000000") for key in ("trigger_price", "confirmation_price", "entry_min", "entry_max", "no_chase_cap", "invalid_price", "target_1", "target_2", "tick_size", "minimum_turnover")}
        plan.update({key: Decimal("0.00000001") for key in ("entry_fee_rate", "exit_fee_rate", "exit_tax_rate")})
        plan.update(side="long", trigger_rule="high_at_or_above", confirmation_rule="close_at_or_above", entry_rule="caller_session_open", invalidation_rule="session_low_at_or_below", tick_rule="constant_tick", entry_slippage_ticks=0, exit_slippage_ticks=0, minimum_volume=1, invalidation_event_key="controlled")
        instant = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
        plan.update({key: instant for key in ("decision_at", "earliest_execution_at", "expires_at")})
        observation = {key: Decimal("1.00000000") for key in ("trigger_high", "confirmation_close", "session_open_reference_price", "session_high", "session_low", "turnover")}
        observation.update({key: instant for key in ("trigger_at", "confirmation_at", "session_started_at", "session_ended_at", "assessed_at")})
        observation.update(volume=1, halted=False, event_state="unknown", event_at=None)
        payload = {"trade_plan_version": "caller-trade-plan/v1", "execution_version": "caller-execution/v1", "evaluation_scope": "post_session_hypothetical", "point_in_time_status": "not_asserted", "fill_status": "not_asserted", "costs": {"hypothetical_target_1_cost_space_per_unit": Decimal("0.9999999700000000")}}
        native = store.canonical_decode(wire(record))
        native["original_inputs"] = {"plan": plan, "observation": observation}
        native["plan_payload"] = payload

        def encoded():
            native["original_inputs_sha256"] = digest(store.canonical_encode(native["original_inputs"]))
            native["plan_payload_sha256"] = digest(store.canonical_encode(native["plan_payload"]))
            raw = store.canonical_encode(native)
            external = json.loads(raw)
            return raw, expectations(external)

        raw, args = encoded()
        actual = store.validate_record(raw, **args)
        self.assertEqual(actual["plan_payload"]["costs"]["hypothetical_target_1_cost_space_per_unit"].as_tuple().exponent, -16)
        for key, value in (("trigger_price", "1.0"), ("trigger_price", True), ("trigger_price", Decimal("1E-9")), ("trigger_price", Decimal("1000000000001")), ("trigger_price", Decimal("0")), ("entry_fee_rate", Decimal("1")), ("entry_slippage_ticks", True), ("entry_slippage_ticks", 1000001), ("minimum_volume", 0)):
            old = plan[key]
            plan[key] = value
            raw, args = encoded()
            self.reject(lambda raw=raw, args=args: store.validate_record(raw, **args))
            plan[key] = old
        payload["fill_status"] = "accepted"
        raw, args = encoded()
        self.reject(lambda: store.validate_record(raw, **args), "caller_hypothetical_markers_required")
        payload["fill_status"] = "not_asserted"
        native["declared_versions"]["execution_version"] = "verified-execution/v1"
        raw, args = encoded()
        self.reject(lambda: store.validate_record(raw, **args), "caller_declared_version_mismatch")


class CliTests(unittest.TestCase):
    reject = CodecTests.reject
    def test_transport_bounds_and_exact_canonical_request(self):
        request = {"expected_ownership": OWNER.decode("utf-8"), "expected_ownership_sha256": digest(OWNER)}
        parsed = cli.parse_request(store, "init", wire(request))
        self.assertEqual(parsed["expected_ownership"], OWNER)
        for raw in (wire(request) + b"\n", b'{"expected_ownership":"x","expected_ownership":"y"}', b"[]", wire(dict(request, latest=True)), b" " * (cli.MAX_REQUEST_BYTES + 1)):
            self.reject(lambda raw=raw: cli.parse_request(store, "init", raw))
        self.reject(lambda: cli.parse_request(store, "latest", b"{}"), "unknown_command")

    def test_cli_help_and_invalid_request_without_disk(self):
        before = dict(GUARD)
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        # Source reloads are read-only and explicitly tracked; no stdin read
        # is needed for help, and malformed requests never reach path I/O.
        old_stdin = sys.stdin
        try:
            sys.stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["init", "--root", ABS_ROOT, "--request-stdin"]), 2)
        finally:
            sys.stdin = old_stdin
        for key in ("disk_mutation_attempts", "network_attempts", "subprocess_attempts", "path_io_calls", "storage_entry_calls"):
            self.assertEqual(GUARD[key], before[key])

    def test_source_imports_are_stdlib_and_no_package_entrypoint(self):
        forbidden = {"app", "main", "config", "db", "trade_plan", "conftest"}
        for source in (SOURCE_RAW, CLI_RAW):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name.split(".")[0] in forbidden for alias in node.names))
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse(node.level or node.module.split(".")[0] in forbidden)
        self.assertFalse(any(name == "app" or name.startswith("app.") for name in sys.modules))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.setprofile(None)
    print(json.dumps({"source": str(SOURCE), "source_sha256": SOURCE_SHA256, "cli_sha256": CLI_SHA256, "guard": GUARD, "artifact_bytes": 0, "disk_ac": "not_tested", "cases": result.testsRun}, sort_keys=True))
    if any(GUARD[key] for key in ("disk_mutation_attempts", "network_attempts", "subprocess_attempts", "path_io_calls", "storage_entry_calls")):
        raise SystemExit(3)
    raise SystemExit(0 if result.wasSuccessful() else 1)
