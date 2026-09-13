"""Finite rule replay contract tests; synthetic inputs never establish PIT."""

import builtins
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

from app import domain
from app import rule_replay as replay


def arguments(evaluator="breakout_v1"):
    common = {
        "close": 101.0, "volume": 120.0, "prior_volumes": [100.0] * 20,
        "group_excess_return_20d": .01,
        "institutional_flow_to_turnover_ratio_5d": -.003,
        "margin_balance_change_ratio_5d": .05,
    }
    if evaluator == "breakout_v1":
        return dict(common, prior_highs=[100.0] * 20)
    return dict(common, close=100.0, volume=60.0, ma20=100.0, ma60=90.0, bar_count=60)


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def seal(bundle):
    bundle["bundle_digest"] = digest({k: v for k, v in bundle.items() if k != "bundle_digest"})
    return bundle


def capture(evaluator="breakout_v1", **changes):
    return replay.capture_rule_inputs(evaluator=evaluator, arguments=dict(arguments(evaluator), **changes))


def private_names():
    return {name for name in sys.modules if name.startswith("_rule_replay_private_")}


@pytest.mark.parametrize("evaluator", ["breakout_v1", "pullback_v1"])
@pytest.mark.parametrize("state,changes", [
    ("passed", {}), ("rejected", {"group_excess_return_20d": 0}),
    ("data_incomplete", {"close": None}),
])
def test_complete_bundle_external_json_roundtrip(evaluator, state, changes, tmp_path):
    supplied = dict(arguments(evaluator), **changes)
    original = copy.deepcopy(supplied)
    expected = asdict(getattr(domain, "evaluate_" + evaluator)(**supplied))
    expected["reasons"] = list(expected["reasons"])
    bundle = replay.capture_rule_inputs(evaluator=evaluator, arguments=supplied)
    assert supplied == original
    assert bundle["recorded_result"] == expected
    assert expected["state"] == state
    text = replay.rule_replay_json(bundle)
    path = tmp_path / "bundle.json"
    path.write_text(text, encoding="utf-8")
    report = replay.replay_rule_inputs(path.read_text(encoding="utf-8"))
    assert report["replayed_result"] == expected
    assert report["exact_match"] is True
    assert bundle["arguments_digest"] == digest({"evaluator": evaluator, "arguments": supplied})
    assert bundle["config_digest"] == digest(bundle["config_snapshot"])
    assert bundle["bundle_digest"] == digest({k: v for k, v in bundle.items() if k != "bundle_digest"})
    assert replay.rule_replay_json(text) == text
    assert capture(evaluator, **changes) == bundle
    assert set(bundle) == {"schema_version", "evaluator", "strategy_version", "implementation",
                           "config_snapshot", "config_digest", "arguments", "arguments_digest",
                           "recorded_result", "bundle_digest"}
    assert set(report) == {"schema_version", "scope", "input_source_mode", "arguments_digest",
                           "bundle_digest", "implementation", "config_digest", "recorded_result",
                           "replayed_result", "exact_match", "local_source_binding_verified",
                           "subject_identity_present", "market_time_present", "historical_inputs_verified",
                           "availability_verified", "pit_verified", "signal_reconstructed"}
    assert report["scope"] == "pure_rule_only"
    assert report["input_source_mode"] == "caller_provided_only"
    assert report["local_source_binding_verified"] is True
    for key in ("subject_identity_present", "market_time_present", "historical_inputs_verified",
                "availability_verified", "pit_verified", "signal_reconstructed"):
        assert report[key] is False
    assert report["implementation"]["runtime"] == {"implementation": "cpython", "version": "3.12.14"}


@pytest.mark.parametrize("evaluator,key", [
    (name, key) for name in ("breakout_v1", "pullback_v1") for key in arguments(name)
])
def test_every_argument_required_but_explicit_null_evaluates(evaluator, key):
    supplied = arguments(evaluator)
    del supplied[key]
    with pytest.raises(replay.RuleReplayContractError, match="argument_keys"):
        replay.capture_rule_inputs(evaluator=evaluator, arguments=supplied)
    bundle = capture(evaluator, **{key: None})
    assert bundle["arguments"][key] is None
    assert bundle["recorded_result"]["state"] == "data_incomplete"
    assert replay.replay_rule_inputs(bundle)["exact_match"] is True


@pytest.mark.parametrize("value", [True, False, "100", {}, [], float("nan"), float("inf"),
                                  -float("inf"), 2**53, -(2**53)])
@pytest.mark.parametrize("evaluator", ["breakout_v1", "pullback_v1"])
def test_invalid_scalar_domain_rejected_before_execution(evaluator, value, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid inputs reached evaluator")
    monkeypatch.setattr(replay, "_evaluate", forbidden)
    with pytest.raises(replay.RuleReplayContractError):
        capture(evaluator, close=value)


@pytest.mark.parametrize("value", [60.0, True, "60", {}, []])
def test_bar_count_native_integer_only(value):
    with pytest.raises(replay.RuleReplayContractError):
        capture("pullback_v1", bar_count=value)


@pytest.mark.parametrize("value", [-(2**53 - 1), 2**53 - 1, 0])
def test_integer_domain_boundaries_are_admitted(value):
    bundle = capture("pullback_v1", bar_count=value)
    assert bundle["arguments"]["bar_count"] == value
    assert replay.replay_rule_inputs(bundle)["exact_match"]


@pytest.mark.parametrize("history", [tuple([100] * 20), {i: None for i in range(20)}, "1" * 20,
                                     [True] + [100] * 20, ["bad"] + [100] * 20])
def test_history_accepts_only_native_numeric_arrays_even_ignored_prefix(history):
    with pytest.raises(replay.RuleReplayContractError):
        capture(prior_highs=history)


@pytest.mark.parametrize("length,state", [(0, "data_incomplete"), (19, "data_incomplete"),
                                         (20, "passed"), (21, "passed"), (10000, "passed")])
def test_whole_history_length_is_preserved(length, state):
    bundle = capture(prior_highs=[100.0] * length)
    assert len(bundle["arguments"]["prior_highs"]) == length
    assert bundle["recorded_result"]["state"] == state
    assert replay.replay_rule_inputs(bundle)["exact_match"]


def test_history_limit_and_nonpositive_trailing_values():
    with pytest.raises(replay.RuleReplayContractError, match="history_length_limit"):
        capture(prior_highs=[100] * 10001)
    for value in [None, 0, -1]:
        bundle = capture(prior_volumes=[100.] * 19 + [value])
        assert bundle["recorded_result"] == {"passed": False, "state": "data_incomplete",
                                             "reasons": ["prior_20_volumes_missing_or_invalid"]}


def test_ignored_prefix_changes_argument_identity_not_result():
    left = capture(prior_highs=[None] + [100.] * 20)
    right = capture(prior_highs=[999.] + [100.] * 20)
    assert left["recorded_result"] == right["recorded_result"]
    assert left["arguments_digest"] != right["arguments_digest"]
    assert left["bundle_digest"] != right["bundle_digest"]
    assert left["arguments"]["prior_highs"][0] is None
    assert replay.replay_rule_inputs(left)["exact_match"]


def test_history_order_and_float_representation_are_not_normalized():
    values = [100.] * 20 + [102.]
    assert capture(prior_highs=values)["recorded_result"]["state"] == "rejected"
    assert capture(prior_highs=list(reversed(values)))["recorded_result"]["state"] == "passed"
    integer = capture(margin_balance_change_ratio_5d=0)
    floating = capture(margin_balance_change_ratio_5d=0.0)
    negative = capture(margin_balance_change_ratio_5d=-0.0)
    assert len({x["arguments_digest"] for x in [integer, floating, negative]}) == 3
    assert '"margin_balance_change_ratio_5d":-0.0' in replay.rule_replay_json(negative)


@pytest.mark.parametrize("evaluator", ["breakout_v1", "pullback_v1"])
@pytest.mark.parametrize("key,boundary,reason,equal_passes", [
    ("group_excess_return_20d", 0.0, "group_relative_strength_not_positive", False),
    ("institutional_flow_to_turnover_ratio_5d", -.003, "institutional_flow_materially_adverse", True),
    ("margin_balance_change_ratio_5d", .05, "margin_financing_increase_abnormal", True),
])
def test_confirmation_float_neighbors(evaluator, key, boundary, reason, equal_passes):
    for direction in (-math.inf, None, math.inf):
        value = boundary if direction is None else math.nextafter(boundary, direction)
        passed = equal_passes if direction is None else direction == (
            -math.inf if key == "margin_balance_change_ratio_5d" else math.inf)
        result = capture(evaluator, **{key: value})["recorded_result"]
        assert result == {"passed": passed, "state": "passed" if passed else "rejected",
                          "reasons": [] if passed else [reason]}


@pytest.mark.parametrize("evaluator,changes,state,reasons", [
    ("breakout_v1", {"close": 100.}, "rejected", ["close_not_above_prior_20_day_high"]),
    ("breakout_v1", {"close": math.nextafter(100., math.inf)}, "passed", []),
    ("breakout_v1", {"volume": math.nextafter(120., -math.inf)}, "passed", []),
    ("breakout_v1", {"volume": 119.99}, "rejected", ["volume_ratio_below_1_20"]),
    ("pullback_v1", {"close": 97.}, "passed", []),
    ("pullback_v1", {"close": 102.}, "passed", []),
    ("pullback_v1", {"close": 96.99}, "rejected", ["close_outside_ma20_support_zone"]),
    ("pullback_v1", {"close": 102.01}, "rejected", ["close_outside_ma20_support_zone"]),
    ("pullback_v1", {"volume": 120.}, "passed", []),
    ("pullback_v1", {"volume": 59.99}, "rejected", ["pullback_volume_ratio_outside_range"]),
    ("pullback_v1", {"volume": 120.01}, "rejected", ["pullback_volume_ratio_outside_range"]),
    ("pullback_v1", {"ma60": 100.}, "rejected", ["ma20_not_above_ma60"]),
    ("pullback_v1", {"bar_count": 59}, "data_incomplete", ["history_under_60_bars"]),
    ("breakout_v1", {"prior_volumes": [1e308] * 20}, "rejected", ["volume_ratio_below_1_20"]),
    ("pullback_v1", {"prior_volumes": [1e308] * 20}, "rejected", ["pullback_volume_ratio_outside_range"]),
    ("breakout_v1", {"volume": 1e308, "prior_volumes": [5e-324] * 20}, "passed", []),
    ("pullback_v1", {"volume": 1e308, "prior_volumes": [5e-324] * 20}, "rejected", ["pullback_volume_ratio_outside_range"]),
])
def test_hand_checked_thresholds_and_finite_overflow(evaluator, changes, state, reasons):
    bundle = capture(evaluator, **changes)
    expected = {"passed": state == "passed", "state": state, "reasons": reasons}
    assert bundle["recorded_result"] == expected
    assert replay.replay_rule_inputs(bundle)["replayed_result"] == expected


def test_ordered_reasons_and_pullback_early_return():
    supplied = {key: None for key in arguments()}
    bundle = replay.capture_rule_inputs(evaluator="breakout_v1", arguments=supplied)
    assert bundle["recorded_result"]["reasons"] == [
        "prior_20_highs_missing_or_invalid", "prior_20_volumes_missing_or_invalid",
        "close_missing_or_non_finite", "volume_missing_or_non_finite",
        "group_excess_return_20d_missing_or_non_finite",
        "institutional_flow_to_turnover_ratio_5d_missing_or_non_finite",
        "margin_balance_change_ratio_5d_missing_or_non_finite",
    ]
    pullback = replay.capture_rule_inputs(evaluator="pullback_v1", arguments={k: None for k in arguments("pullback_v1")})
    assert pullback["recorded_result"]["reasons"] == ["bar_count_missing_or_invalid"]
    bundle["recorded_result"]["reasons"].reverse()
    report = replay.replay_rule_inputs(seal(bundle))
    assert report["exact_match"] is False


def test_resealed_result_is_only_a_claim_and_does_not_change_argument_identity():
    bundle = capture()
    original_digest = bundle["arguments_digest"]
    old_bundle_digest = bundle["bundle_digest"]
    bundle["recorded_result"] = {"passed": False, "state": "rejected", "reasons": ["caller_claim"]}
    with pytest.raises(replay.RuleReplayContractError, match="bundle_digest_mismatch"):
        replay.replay_rule_inputs(bundle)
    report = replay.replay_rule_inputs(seal(bundle))
    assert report["exact_match"] is False
    assert report["replayed_result"] == {"passed": True, "state": "passed", "reasons": []}
    assert report["arguments_digest"] == original_digest
    assert report["bundle_digest"] != old_bundle_digest


@pytest.mark.parametrize("result", [
    {"passed": 1, "state": "passed", "reasons": []},
    {"passed": True, "state": "rejected", "reasons": ["x"]},
    {"passed": True, "state": "passed", "reasons": ["x"]},
    {"passed": False, "state": "rejected", "reasons": []},
    {"passed": False, "state": "rejected", "reasons": [""]},
    {"passed": False, "state": "unknown", "reasons": ["x"]},
    {"passed": False, "state": "rejected", "reasons": [1]},
])
def test_recorded_result_shape_and_coherence(result):
    bundle = capture()
    bundle["recorded_result"] = result
    with pytest.raises(replay.RuleReplayContractError):
        replay.replay_rule_inputs(seal(bundle))


@pytest.mark.parametrize("path,value,error", [
    (("schema_version",), "v999", replay.RuleReplayContractError),
    (("evaluator",), "other", replay.RuleReplayContractError),
    (("strategy_version",), "1.0", replay.RuleReplayBindingError),
    (("implementation", "id"), "other", replay.RuleReplayBindingError),
    (("implementation", "source_sha256"), "sha256:" + "0" * 64, replay.RuleReplayBindingError),
    (("implementation", "runtime", "version"), "3.12.13", replay.RuleReplayBindingError),
    (("implementation", "runtime", "implementation"), "CPython", replay.RuleReplayBindingError),
    (("config_digest",), "sha256:" + "0" * 64, replay.RuleReplayContractError),
    (("arguments_digest",), "sha256:" + "0" * 64, replay.RuleReplayContractError),
    (("bundle_digest",), "sha256:" + "0" * 64, replay.RuleReplayContractError),
])
def test_invalid_binding_and_seals_never_reach_evaluator(path, value, error, monkeypatch):
    bundle = capture()
    target = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    monkeypatch.setattr(replay, "_evaluate", lambda *a, **k: pytest.fail("invalid bundle evaluated"))
    for api in [replay.rule_replay_json, replay.replay_rule_inputs]:
        with pytest.raises(error):
            api(bundle)


def test_caller_cannot_select_resealed_config():
    bundle = capture()
    bundle["config_snapshot"]["volume"]["minimum_signal_to_average_ratio"] = 1.21
    bundle["config_digest"] = digest(bundle["config_snapshot"])
    with pytest.raises(replay.RuleReplayBindingError, match="unsupported_config_binding"):
        replay.replay_rule_inputs(seal(bundle))


@pytest.mark.parametrize("path", [(), ("implementation",), ("implementation", "runtime"),
                                  ("arguments",), ("recorded_result",)])
def test_unknown_nested_structural_fields(path):
    bundle = capture()
    target = bundle
    for key in path:
        target = target[key]
    target["source_path"] = "C:/untrusted/evaluator.py"
    with pytest.raises(replay.RuleReplayContractError):
        replay.replay_rule_inputs(seal(bundle))


@pytest.mark.parametrize("text", [
    '{"x":1,"x":2}', '{"a":{"x":1,"x":2}}', '{"a":[{"x":1,"x":2}]}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e400}',
    '{"x":"\\ud800"}', '{', '[]', 'null', '{"x":' + '9' * 5000 + '}',
    '{"x":' + '[' * 1100 + '0' + ']' * 1100 + '}',
])
def test_strict_json_rejects_duplicates_nonfinite_unicode_and_depth(text):
    with pytest.raises(replay.RuleReplayContractError):
        replay.rule_replay_json(text)


def test_native_dict_and_scalar_subclasses_rejected_without_protocols():
    class Hostile(dict):
        def items(self):
            pytest.fail("caller mapping protocol invoked")
    class CustomFloat(float):
        def __float__(self):
            pytest.fail("caller float protocol invoked")
    with pytest.raises(replay.RuleReplayContractError):
        replay.capture_rule_inputs(evaluator="breakout_v1", arguments=Hostile(arguments()))
    with pytest.raises(replay.RuleReplayContractError):
        capture(close=CustomFloat(101))
    with pytest.raises(replay.RuleReplayContractError):
        capture(prior_highs=(x for x in [100] * 20))


def test_cycles_depth_and_raw_canonical_size_limits():
    cyclic = {}; cyclic["x"] = cyclic
    with pytest.raises(replay.RuleReplayContractError, match="json_cycle"):
        replay.replay_rule_inputs(cyclic)
    tree = {}
    for _ in range(16):
        tree = {"x": tree}
    with pytest.raises(replay.RuleReplayContractError, match="json_depth_limit"):
        replay.replay_rule_inputs(tree)
    for value in [" " * (1048576 + 1), {"x": "x" * 1048576}, {"x": "\x00" * 200000}]:
        with pytest.raises(replay.RuleReplayContractError, match="json_size_limit"):
            replay.replay_rule_inputs(value)


def test_detached_inputs_outputs_reports_and_shared_config_mutation(monkeypatch):
    supplied = arguments()
    first = replay.capture_rule_inputs(evaluator="breakout_v1", arguments=supplied)
    saved = copy.deepcopy(first)
    supplied["prior_highs"][0] = 9000
    assert first == saved
    report = replay.replay_rule_inputs(first)
    report["recorded_result"]["reasons"].append("x")
    report["implementation"]["runtime"]["version"] = "other"
    assert first == saved
    monkeypatch.setitem(domain.STRATEGY_CONFIGS["breakout_v1"]["volume"], "minimum_signal_to_average_ratio", 999)
    monkeypatch.setattr(domain, "evaluate_breakout_v1", lambda **kwargs: pytest.fail("shared function used"))
    assert capture() == saved
    first["config_snapshot"]["volume"]["minimum_signal_to_average_ratio"] = 999
    first["arguments"]["prior_highs"][0] = 9000
    assert capture() == saved


def test_each_capture_replay_evaluates_once_serializer_never(monkeypatch):
    count = []
    actual = replay._evaluate
    def counted(*args):
        count.append(args[1])
        return actual(*args)
    monkeypatch.setattr(replay, "_evaluate", counted)
    bundle = capture()
    assert count == ["breakout_v1"]
    text = replay.rule_replay_json(bundle)
    assert count == ["breakout_v1"]
    replay.replay_rule_inputs(text)
    assert count == ["breakout_v1", "breakout_v1"]


@pytest.mark.parametrize("stage", ["compile", "exec", "evaluate", "config"])
def test_private_registration_cleanup_on_fault(stage, monkeypatch):
    before = private_names()
    if stage == "compile":
        def fail(*args, **kwargs):
            assert private_names() - before
            raise SyntaxError("injected compile failure")
        monkeypatch.setattr(replay, "compile", fail, raising=False)
    else:
        original = builtins.exec
        def fault(code, namespace):
            assert private_names() - before
            if stage == "exec":
                raise RuntimeError("injected exec failure")
            original(code, namespace)
            if stage == "config":
                namespace["STRATEGY_CONFIGS"]["breakout_v1"]["volume"]["minimum_signal_to_average_ratio"] = 999
            else:
                def broken(**kwargs):
                    raise OverflowError("injected evaluator failure")
                namespace["evaluate_breakout_v1"] = broken
        monkeypatch.setattr(replay, "exec", fault, raising=False)
    expected = replay.RuleReplayBindingError if stage == "config" else replay.RuleReplayExecutionError
    with pytest.raises(expected) as failure:
        capture()
    assert failure.value.code in {"local_config_digest_mismatch", "implementation_execution_failed", "evaluator_failed"}
    assert private_names() == before


def test_private_names_cleaned_on_success_and_ordinary_concurrent_calls():
    before = private_names()
    with ThreadPoolExecutor(max_workers=4) as pool:
        bundles = list(pool.map(lambda i: capture("breakout_v1" if i % 2 else "pullback_v1"), range(12)))
    assert all(x["recorded_result"]["passed"] for x in bundles)
    assert private_names() == before
    assert bundles[1] == bundles[3]


@pytest.mark.parametrize("mode,code", [("changed", "local_source_hash_mismatch"),
                                      ("oversize", "local_source_size_limit"),
                                      ("missing", "local_source_unreadable")])
def test_fixed_source_read_rejects_bad_bytes_before_compile(mode, code, monkeypatch, tmp_path):
    # Fault injection replaces only the fixed registry path, never a caller API.
    path = tmp_path / "domain.py"
    if mode != "missing":
        path.write_bytes(b"x" * (1048577 if mode == "oversize" else 10))
    monkeypatch.setattr(replay, "_SOURCE_PATH", path)
    monkeypatch.setattr(replay, "compile", lambda *a, **k: pytest.fail("bad bytes compiled"), raising=False)
    with pytest.raises(replay.RuleReplayBindingError, match=code):
        capture()


def test_hash_verified_bytes_are_the_same_bytes_compiled(monkeypatch):
    original_compile = builtins.compile
    observed = []
    def checked(source, filename, mode, **kwargs):
        assert type(source) is bytes
        assert hashlib.sha256(source).hexdigest() == "db626fa71311ce5e88c1644f0c3d2ce1d16a4541110fe15813ca9568330ef028"
        assert kwargs["dont_inherit"] is True
        observed.append(source)
        return original_compile(source, filename, mode, **kwargs)
    monkeypatch.setattr(replay, "compile", checked, raising=False)
    capture()
    assert len(observed) == 1


@pytest.mark.parametrize("attribute,value", [
    ("version_info", (3, 12, 13)),
    ("implementation", types.SimpleNamespace(name="pypy")),
    ("float_info", types.SimpleNamespace(radix=2, mant_dig=24, max_exp=128)),
])
def test_actual_runtime_mismatch_is_binding_error(attribute, value, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(replay.sys, attribute, value)
        with pytest.raises(replay.RuleReplayBindingError, match="unsupported_local_runtime"):
            capture()


def test_fresh_process_import_and_replay_have_no_database_worker_network_or_writes():
    script = '''
import builtins,json,sys
events=[]
def audit(event,args):
    if event in ('sqlite3.connect','socket.connect','socket.bind'):
        raise AssertionError(event)
    if event=='open':
        path,mode,flags=args
        if isinstance(mode,str) and any(x in mode for x in ('w','a','+')):
            raise AssertionError(('write',path))
        if isinstance(path,str) and path.lower().endswith(('.db','.sqlite','.sqlite3')):
            raise AssertionError(('database',path))
sys.addaudithook(audit)
from app.rule_replay import capture_rule_inputs,replay_rule_inputs,rule_replay_json
a=json.loads(sys.argv[1])
b=capture_rule_inputs(evaluator='breakout_v1',arguments=a)
assert replay_rule_inputs(rule_replay_json(b))['exact_match']
assert not any(x in sys.modules for x in ('app.db','app.models','app.config','app.domain','worker','worker.pipeline','sqlite3'))
assert not any(x.startswith('_rule_replay_private_') for x in sys.modules)
print('isolated import/replay passed')
'''
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-Xutf8", "-c", script, json.dumps(arguments())],
                            cwd=Path(__file__).resolve().parents[2], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.strip() == "isolated import/replay passed"
