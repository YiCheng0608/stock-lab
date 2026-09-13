"""Bounded, caller-provided pure-rule capture/replay; no historical attestation.

The trusted registry selects fixed local source bytes and CPython 3.12.14. Each
operation uses a fresh private module, never shared ``app.domain`` state. This
assumes a trusted host/interpreter/stdlib/registry; it is not code signing or an
adversarial-runtime sandbox. No database, worker, network or bytecode cache is used.

JSON limits: 1 MiB raw/canonical UTF-8, 16 nested containers (root=1), 10000
elements per history, native integers within +/- (2**53-1). Finite intermediate
float overflow and ordered rule reasons retain the pinned evaluator's behavior.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import types
import uuid


MAX_JSON_BYTES = 1048576
MAX_SOURCE_BYTES = 1048576
MAX_DEPTH = 16
MAX_HISTORY_LENGTH = 10000
MAX_INTEGER = 2**53 - 1

_SOURCE_PATH = Path(__file__).with_name("domain.py")
_SOURCE_SHA256 = "db626fa71311ce5e88c1644f0c3d2ce1d16a4541110fe15813ca9568330ef028"
_CONFIG_DIGESTS = {
    "breakout_v1": "sha256:a68f4f98f319e387e4de71c37e4fc16c225b4406c20a189f7bfdc1515e84b7cd",
    "pullback_v1": "sha256:03998a93820a3c132110d41e2496f5a94a8a7f556774cb80be23e549d4788eff",
}
_COMMON_ARGUMENTS = frozenset({
    "close", "volume", "prior_volumes", "group_excess_return_20d",
    "institutional_flow_to_turnover_ratio_5d", "margin_balance_change_ratio_5d",
})
_ARGUMENTS = {
    "breakout_v1": _COMMON_ARGUMENTS | {"prior_highs"},
    "pullback_v1": _COMMON_ARGUMENTS | {"bar_count", "ma20", "ma60"},
}
_BUNDLE_KEYS = frozenset({
    "schema_version", "evaluator", "strategy_version", "implementation",
    "config_snapshot", "config_digest", "arguments", "arguments_digest", "recorded_result", "bundle_digest",
})
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PRIVATE_PREFIX = "_rule_replay_private_"


class RuleReplayContractError(ValueError):
    """Malformed or unsupported caller data; ``code`` is a stable reason."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class RuleReplayBindingError(RuntimeError):
    """The supported local implementation/config/runtime cannot be verified."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class RuleReplayExecutionError(RuntimeError):
    """The verified evaluator failed; no rule state is fabricated."""

    def __init__(self, code: str, exception_type: str | None = None):
        self.code = code
        self.exception_type = exception_type
        super().__init__(code)


def _tree(value: object) -> None:
    """Iterative prewalk before serialization, without caller object protocols."""
    active: set[int] = set()
    stack = [(value, 0, False)]
    budget = 0
    while stack:
        item, parent_depth, leaving = stack.pop()
        if leaving:
            active.remove(id(item))
            continue
        kind = type(item)
        if kind in (dict, list):
            depth = parent_depth + 1
            if depth > MAX_DEPTH:
                raise RuleReplayContractError("json_depth_limit")
            if id(item) in active:
                raise RuleReplayContractError("json_cycle")
            # Every entry consumes at least one byte. Bound the work stack too.
            budget += 2 + max(0, (2 if kind is dict else 1) * len(item) - 1)
            if budget > MAX_JSON_BYTES:
                raise RuleReplayContractError("json_size_limit")
            active.add(id(item))
            stack.append((item, depth, True))
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise RuleReplayContractError("json_key_type")
                    stack.append((key, depth, False))
                    stack.append((child, depth, False))
            else:
                stack.extend((child, depth, False) for child in item)
        elif kind is str:
            if len(item) > MAX_JSON_BYTES:
                raise RuleReplayContractError("json_size_limit")
            try:
                budget += len(item.encode("utf-8")) + 2
            except UnicodeError as exc:
                raise RuleReplayContractError("invalid_unicode") from exc
        elif kind is int:
            if not -MAX_INTEGER <= item <= MAX_INTEGER:
                raise RuleReplayContractError("integer_out_of_range")
            budget += 1
        elif kind is float:
            if not math.isfinite(item):
                raise RuleReplayContractError("nonfinite_number")
            budget += 1
        elif item is None or kind is bool:
            budget += 1
        else:
            raise RuleReplayContractError("json_native_type_required")
        if budget > MAX_JSON_BYTES:
            raise RuleReplayContractError("json_size_limit")


def _canonical(value: object) -> str:
    _tree(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
            raise RuleReplayContractError("json_size_limit")
        return encoded
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, RuleReplayContractError):
            raise
        raise RuleReplayContractError("json_encoding_error") from exc


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuleReplayContractError("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_: str) -> None:
    raise RuleReplayContractError("nonfinite_number")


def _detached(value: object, *, accept_text: bool = False) -> dict:
    if accept_text and type(value) is str:
        try:
            if len(value) > MAX_JSON_BYTES:
                raise RuleReplayContractError("json_size_limit")
            if len(value.encode("utf-8")) > MAX_JSON_BYTES:
                raise RuleReplayContractError("json_size_limit")
            value = json.loads(value, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        except (ValueError, UnicodeError, RecursionError) as exc:
            if isinstance(exc, RuleReplayContractError):
                raise
            raise RuleReplayContractError("invalid_json") from exc
    if type(value) is not dict:
        raise RuleReplayContractError("native_dict_required")
    return json.loads(_canonical(value))


def _keys(value: object, keys: set | frozenset, code: str) -> None:
    if type(value) is not dict or set(value) != keys:
        raise RuleReplayContractError(code)


def _evaluator(value: object) -> str:
    if type(value) is not str or value not in _ARGUMENTS:
        raise RuleReplayContractError("unsupported_evaluator")
    return value


def _number_or_null(value: object) -> bool:
    return value is None or type(value) in (int, float)


def _arguments(evaluator: str, value: object) -> None:
    _keys(value, _ARGUMENTS[evaluator], "argument_keys")
    for key, item in value.items():
        if key in {"prior_highs", "prior_volumes"}:
            if item is None:
                continue
            if type(item) is not list:
                raise RuleReplayContractError("history_type")
            if len(item) > MAX_HISTORY_LENGTH:
                raise RuleReplayContractError("history_length_limit")
            if not all(_number_or_null(element) for element in item):
                raise RuleReplayContractError("history_element_type")
        elif key == "bar_count":
            if item is not None and type(item) is not int:
                raise RuleReplayContractError("bar_count_type")
        elif not _number_or_null(item):
            raise RuleReplayContractError("argument_number_type")


def _result(value: object) -> None:
    _keys(value, {"passed", "state", "reasons"}, "result_keys")
    if type(value["passed"]) is not bool:
        raise RuleReplayContractError("result_passed_type")
    state = value["state"]
    if type(state) is not str or state not in {"passed", "rejected", "data_incomplete"}:
        raise RuleReplayContractError("result_state")
    reasons = value["reasons"]
    if type(reasons) is not list or any(type(x) is not str or not x for x in reasons):
        raise RuleReplayContractError("result_reasons")
    if value["passed"] != (state == "passed") or bool(reasons) == value["passed"]:
        raise RuleReplayContractError("result_coherence")


def _implementation() -> dict:
    return {"id": "domain-rules/v1", "source_sha256": "sha256:" + _SOURCE_SHA256,
            "runtime": {"implementation": "cpython", "version": "3.12.14"}}


def _runtime() -> None:
    info = sys.float_info
    if (sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 14)
            or (info.radix, info.mant_dig, info.max_exp) != (2, 53, 1024)):
        raise RuleReplayBindingError("unsupported_local_runtime")


def _read_source() -> bytes:
    try:
        with _SOURCE_PATH.open("rb") as source_file:
            source = source_file.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise RuleReplayBindingError("local_source_unreadable") from exc
    if len(source) > MAX_SOURCE_BYTES:
        raise RuleReplayBindingError("local_source_size_limit")
    if hashlib.sha256(source).hexdigest() != _SOURCE_SHA256:
        raise RuleReplayBindingError("local_source_hash_mismatch")
    return source


@contextmanager
def _private_domain():
    _runtime()
    source = _read_source()
    name = _PRIVATE_PREFIX + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(_SOURCE_PATH)
    sys.modules[name] = module
    try:
        try:
            code = compile(source, str(_SOURCE_PATH), "exec", dont_inherit=True)
            exec(code, module.__dict__)
        except Exception as exc:
            raise RuleReplayExecutionError("implementation_execution_failed", type(exc).__name__) from exc
        try:
            for evaluator, expected in _CONFIG_DIGESTS.items():
                if _digest(module.STRATEGY_CONFIGS[evaluator]) != expected:
                    raise RuleReplayBindingError("local_config_digest_mismatch")
        except RuleReplayBindingError:
            raise
        except Exception as exc:
            raise RuleReplayBindingError("local_implementation_load_failed") from exc
        yield module
    finally:
        if sys.modules.get(name) is module:
            del sys.modules[name]


def _evaluate(module: types.ModuleType, evaluator: str, arguments: dict) -> dict:
    try:
        outcome = getattr(module, "evaluate_" + evaluator)(**arguments)
        result = {"passed": outcome.passed, "state": outcome.state,
                  "reasons": list(outcome.reasons)}
        _result(result)
        return _detached(result)
    except Exception as exc:
        raise RuleReplayExecutionError("evaluator_failed", type(exc).__name__) from exc


def _validate_bundle(value: dict | str) -> dict:
    bundle = _detached(value, accept_text=True)
    _keys(bundle, _BUNDLE_KEYS, "bundle_keys")
    if bundle["schema_version"] != "rule-replay-bundle/v1":
        raise RuleReplayContractError("unsupported_schema_version")
    evaluator = _evaluator(bundle["evaluator"])
    if bundle["strategy_version"] != "1.0.0":
        raise RuleReplayBindingError("unsupported_strategy_version")
    implementation = bundle["implementation"]
    _keys(implementation, {"id", "source_sha256", "runtime"}, "implementation_keys")
    _keys(implementation["runtime"], {"implementation", "version"}, "runtime_keys")
    if implementation != _implementation():
        raise RuleReplayBindingError("unsupported_implementation_binding")
    _arguments(evaluator, bundle["arguments"])
    _result(bundle["recorded_result"])
    for key in ("config_digest", "arguments_digest", "bundle_digest"):
        if type(bundle[key]) is not str or _DIGEST.fullmatch(bundle[key]) is None:
            raise RuleReplayContractError("invalid_digest")
    if type(bundle["config_snapshot"]) is not dict:
        raise RuleReplayContractError("config_snapshot_type")
    if _digest(bundle["config_snapshot"]) != bundle["config_digest"]:
        raise RuleReplayContractError("config_digest_mismatch")
    if bundle["config_digest"] != _CONFIG_DIGESTS[evaluator]:
        raise RuleReplayBindingError("unsupported_config_binding")
    if _digest({"evaluator": evaluator, "arguments": bundle["arguments"]}) != bundle["arguments_digest"]:
        raise RuleReplayContractError("arguments_digest_mismatch")
    if _digest({k: v for k, v in bundle.items() if k != "bundle_digest"}) != bundle["bundle_digest"]:
        raise RuleReplayContractError("bundle_digest_mismatch")
    return bundle


def capture_rule_inputs(*, evaluator: str, arguments: dict) -> dict:
    """Evaluate once and capture all admitted caller arguments in a sealed bundle."""
    evaluator = _evaluator(evaluator)
    arguments = _detached(arguments)
    _arguments(evaluator, arguments)
    with _private_domain() as module:
        bundle = {
            "schema_version": "rule-replay-bundle/v1", "evaluator": evaluator,
            "strategy_version": "1.0.0", "implementation": _implementation(),
            "config_snapshot": _detached(module.STRATEGY_CONFIGS[evaluator]),
            "config_digest": _CONFIG_DIGESTS[evaluator], "arguments": arguments,
            "arguments_digest": _digest({"evaluator": evaluator, "arguments": arguments}),
            "recorded_result": _evaluate(module, evaluator, arguments),
        }
        bundle["bundle_digest"] = _digest(bundle)
        return _detached(bundle)


def rule_replay_json(bundle: dict | str) -> str:
    """Strictly validate data and local binding, then serialize without evaluation."""
    validated = _validate_bundle(bundle)
    with _private_domain():
        return _canonical(validated)


def replay_rule_inputs(bundle: dict | str) -> dict:
    """Re-evaluate once; equality covers only passed/state/ordered reasons."""
    validated = _validate_bundle(bundle)
    with _private_domain() as module:
        replayed = _evaluate(module, validated["evaluator"], validated["arguments"])
        return _detached({
            "schema_version": "rule-replay-report/v1", "scope": "pure_rule_only",
            "input_source_mode": "caller_provided_only", "bundle_digest": validated["bundle_digest"],
            "arguments_digest": validated["arguments_digest"],
            "implementation": validated["implementation"], "config_digest": validated["config_digest"],
            "recorded_result": validated["recorded_result"], "replayed_result": replayed,
            "exact_match": validated["recorded_result"] == replayed,
            "local_source_binding_verified": True, "historical_inputs_verified": False,
            "subject_identity_present": False, "market_time_present": False,
            "availability_verified": False,
            "pit_verified": False, "signal_reconstructed": False,
        })


__all__ = [
    "capture_rule_inputs", "rule_replay_json", "replay_rule_inputs",
    "RuleReplayContractError", "RuleReplayBindingError", "RuleReplayExecutionError",
]
