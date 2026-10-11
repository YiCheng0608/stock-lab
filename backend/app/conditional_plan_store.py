"""Bounded, typed, immutable conditional-plan records (stdlib only).

This layer checks storage integrity and caller declarations. It does not
generate a plan, verify a source, or assert financial/PIT/fill validity.
Load this file directly: importing the app package is unnecessary.

External expectations are required, never inferred from a stored record.
Root spelling is the native normalized absolute path (on Windows use the
drive's canonical spelling and backslashes). No root or parent aliases,
symlinks, junctions, or reparse points are supported.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat

RECORD_VERSION = "conditional-plan-record/v1"
STORE_VERSION = "conditional-plan-store/v1"
OWNERSHIP_SCHEMA = "conditional-plan-store-ownership/v1"
BINDING_SCHEMA = "conditional-plan-binding/v1"
MAX_RECORD_BYTES = 65536
MAX_OWNERSHIP_BYTES = 2048
MAX_DEPTH = 16
MAX_NODES = 8192
MAX_LIST = 1024
MAX_KEY_BYTES = 128
MAX_STRING_BYTES = 4096
DECIMAL_MIN_EXPONENT = -1000000
DECIMAL_MAX_EXPONENT = 1000000
OWNERSHIP_FILE = "ownership.json"
STAGING_FILE = "record-staging.tmp"
SYMBOLS = frozenset({"3105", "3293", "5274", "5347", "6488", "6510", "8069"})
STRATEGIES = frozenset({"breakout_v1", "pullback_v1"})
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_PLAN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z", re.ASCII)
_DECIMAL_DIGITS = re.compile(r"(?:0|[1-9][0-9]{0,49})\Z", re.ASCII)
_RECORD_KEYS = frozenset({
    "record_version", "plan_id", "revision", "parent_record_sha256", "identity",
    "as_of", "generated_at", "decision_at", "declared_versions", "source_refs",
    "plan_payload", "plan_payload_sha256", "original_inputs",
    "original_inputs_sha256", "config_snapshot", "config_sha256", "semantic_status",
})
_VERSION_KEYS = frozenset({
    "payload_schema_id", "payload_schema_sha256", "plan_version", "strategy_version",
    "rule_version", "rule_sha256", "execution_version", "config_version",
})
_REF_KEYS = frozenset({"role", "source_id", "source_version", "snapshot_sha256", "revision_id", "time_evidence_sha256"})
_OWNER_KEYS = frozenset({
    "schema", "store_version", "issue", "namespace", "actual_qa_session", "root_id",
    "absolute_root", "plan_id", "allowed_revisions", "created_at",
})
_BIND_RECORD_KEYS = _RECORD_KEYS - {"plan_payload", "original_inputs", "config_snapshot"}
_BIND_KEYS = _BIND_RECORD_KEYS | {"schema", "store_version", "absolute_root"}


class PlanStoreError(ValueError):
    """A bounded first error with separately retained cleanup failures.

    ``code`` and ``stage`` are stable ASCII values, never OS exception text.
    ``secondary`` consists of bounded {code, stage} facts. No error receipt
    claims acceptance; even a cleanup error after publishing is a failure.
    """

    def __init__(self, code: str, stage: str, secondary: tuple[dict, ...] = ()) -> None:
        self.code = code[:64]
        self.stage = stage[:64]
        self.secondary = secondary
        super().__init__(self.code + ":" + self.stage)

    def receipt(self) -> dict:
        return {"code": self.code, "stage": self.stage, "secondary": list(self.secondary)}


def _fail(code: str, stage: str = "input") -> None:
    raise PlanStoreError(code, stage)


def _exact(value: object, keys: frozenset, stage: str) -> dict:
    if type(value) is not dict or any(type(k) is not str for k in value) or set(value) != keys:
        _fail("exact_fields_required", stage)
    return value


def _text(value: object, cap: int, stage: str, *, ascii_only: bool = False) -> str:
    if type(value) is not str or not value:
        _fail("nonempty_string_required", stage)
    try:
        encoded = value.encode("ascii" if ascii_only else "utf-8", "strict")
    except UnicodeError:
        _fail("invalid_string_encoding", stage)
    if len(encoded) > cap:
        _fail("string_limit", stage)
    return value


def _hash(value: object, stage: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("sha256_required", stage)
    return value


def _revision(value: object, stage: str) -> int:
    if type(value) is not int or not 1 <= value <= 999999:
        _fail("revision_required", stage)
    return value


def _utc_text(value: object, stage: str) -> str:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        _fail("canonical_utc_required", stage)
    try:
        instant = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("invalid_instant", stage)
    if instant.isoformat(timespec="microseconds")[:-6] + "Z" != value:
        _fail("canonical_utc_required", stage)
    return value


def _native_utc(value: datetime) -> str:
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            _fail("aware_datetime_required", "codec")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")[:-6] + "Z"
    except PlanStoreError:
        raise
    except (ValueError, OverflowError, TypeError):
        _fail("invalid_instant", "codec")


def _decimal_tag(value: Decimal) -> dict:
    if not value.is_finite():
        _fail("finite_decimal_required", "codec")
    item = value.as_tuple()
    digits = "".join(str(d) for d in item.digits)
    tag = {"$type": "decimal", "sign": item.sign, "digits": digits, "exponent": item.exponent}
    _check_tag(tag)
    return tag


def _check_tag(value: dict) -> None:
    kind = value.get("$type")
    if kind == "decimal":
        _exact(value, frozenset({"$type", "sign", "digits", "exponent"}), "codec")
        if type(value["sign"]) is not int or value["sign"] not in (0, 1):
            _fail("decimal_sign_required", "codec")
        if type(value["digits"]) is not str or _DECIMAL_DIGITS.fullmatch(value["digits"]) is None:
            _fail("decimal_digits_required", "codec")
        if type(value["exponent"]) is not int or not DECIMAL_MIN_EXPONENT <= value["exponent"] <= DECIMAL_MAX_EXPONENT:
            _fail("decimal_exponent_required", "codec")
    elif kind == "datetime":
        _exact(value, frozenset({"$type", "utc"}), "codec")
        _utc_text(value["utc"], "codec")
    else:
        _fail("unknown_reserved_tag", "codec")


def _walk(value: object, depth: int, budget: list[int]) -> object:
    """Count every wire value (including tag members), with root depth=1."""
    budget[0] += 1
    if depth > MAX_DEPTH or budget[0] > MAX_NODES:
        _fail("tree_limit", "codec")
    kind = type(value)
    if value is None or kind in (bool, int):
        return value
    if kind is str:
        try:
            if len(value.encode("utf-8", "strict")) > MAX_STRING_BYTES:
                _fail("string_limit", "codec")
        except UnicodeError:
            _fail("invalid_string_encoding", "codec")
        return value
    if kind is list:
        if len(value) > MAX_LIST:
            _fail("list_limit", "codec")
        return [_walk(item, depth + 1, budget) for item in value]
    if kind is dict:
        if "$type" in value:
            _check_tag(value)
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                _fail("string_key_required", "codec")
            try:
                if len(key.encode("utf-8", "strict")) > MAX_KEY_BYTES:
                    _fail("key_limit", "codec")
            except UnicodeError:
                _fail("invalid_string_encoding", "codec")
            result[key] = _walk(item, depth + 1, budget)
        return result
    _fail("unsupported_native_type", "codec")


def _encode_native(value: object, depth: int = 1, budget: list[int] | None = None) -> object:
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > MAX_DEPTH or budget[0] > MAX_NODES:
        _fail("tree_limit", "codec")
    if type(value) is Decimal:
        return _decimal_tag(value)
    if type(value) is datetime:
        return {"$type": "datetime", "utc": _native_utc(value)}
    if type(value) is dict:
        if "$type" in value:
            _fail("reserved_tag_collision", "codec")
        return {key: _encode_native(item, depth + 1, budget) for key, item in value.items()}
    if type(value) is list:
        if len(value) > MAX_LIST:
            _fail("list_limit", "codec")
        return [_encode_native(item, depth + 1, budget) for item in value]
    return value


def canonical_encode(value: object, *, max_bytes: int = MAX_RECORD_BYTES) -> bytes:
    """Encode native dict/list/scalars, Decimal tuples and aware datetimes.

    Wire tags cannot be passed as ordinary native dictionaries. Parse wire
    bytes with canonical_decode first. No normalization or arithmetic occurs.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_RECORD_BYTES:
        _fail("byte_cap_required", "codec")
    wire = _encode_native(value)
    _walk(wire, 1, [0])
    try:
        raw = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8", "strict")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("unsupported_native_type", "codec")
    if len(raw) > max_bytes:
        _fail("byte_limit", "codec")
    return raw


def _no_duplicate(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key", "codec")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    _fail("float_or_nonfinite_forbidden", "codec")


def _lexical_depth(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                _fail("tree_limit", "codec")
        elif char in "]}":
            depth -= 1


def _decode_wire(value: object) -> object:
    if type(value) is dict:
        if value.get("$type") == "decimal":
            return Decimal((value["sign"], tuple(int(d) for d in value["digits"]), value["exponent"]))
        if value.get("$type") == "datetime":
            return datetime.fromisoformat(value["utc"][:-1] + "+00:00")
        return {key: _decode_wire(item) for key, item in value.items()}
    if type(value) is list:
        return [_decode_wire(item) for item in value]
    return value


def canonical_decode(raw: bytes, *, max_bytes: int = MAX_RECORD_BYTES) -> object:
    """Reject noncanonical bytes and return exact native typed values."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_RECORD_BYTES:
        _fail("byte_cap_required", "codec")
    if type(raw) is not bytes:
        _fail("bytes_required", "codec")
    if len(raw) > max_bytes:
        _fail("byte_limit", "codec")
    try:
        text = raw.decode("utf-8", "strict")
        _lexical_depth(text)
        wire = json.loads(text, object_pairs_hook=_no_duplicate, parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, PlanStoreError):
            raise
        _fail("invalid_json", "codec")
    _walk(wire, 1, [0])
    native = _decode_wire(wire)
    if canonical_encode(native, max_bytes=max_bytes) != raw:
        _fail("noncanonical_bytes", "codec")
    return native


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(value: object) -> dict:
    obj = _exact(value, frozenset({"market", "instrument", "symbol", "strategy_id"}), "identity")
    if obj["market"] != "TPEx" or obj["instrument"] != "ordinary_stock" or type(obj["symbol"]) is not str or obj["symbol"] not in SYMBOLS or type(obj["strategy_id"]) is not str or obj["strategy_id"] not in STRATEGIES:
        _fail("unsupported_identity", "identity")
    return obj


def _metadata(record: dict) -> None:
    if record["record_version"] != RECORD_VERSION or record["semantic_status"] != "not_asserted":
        _fail("unsupported_record_version_or_semantics", "record")
    if type(record["plan_id"]) is not str or _PLAN_ID.fullmatch(record["plan_id"]) is None:
        _fail("plan_id_required", "record")
    rev = _revision(record["revision"], "record")
    if rev == 1:
        if record["parent_record_sha256"] is not None:
            _fail("first_parent_must_be_null", "record")
    else:
        _hash(record["parent_record_sha256"], "record")
    _identity(record["identity"])
    if type(record["as_of"]) is not str or _DATE.fullmatch(record["as_of"]) is None:
        _fail("iso_date_required", "record")
    try:
        date.fromisoformat(record["as_of"])
    except ValueError:
        _fail("invalid_date", "record")
    _utc_text(record["generated_at"], "record")
    _utc_text(record["decision_at"], "record")
    versions = _exact(record["declared_versions"], _VERSION_KEYS, "versions")
    for key, value in versions.items():
        if key.endswith("sha256"):
            _hash(value, "versions")
        else:
            _text(value, 128, "versions", ascii_only=True)
    refs = record["source_refs"]
    if type(refs) is not list or not 1 <= len(refs) <= 32:
        _fail("source_refs_required", "refs")
    roles = set()
    for ref in refs:
        _exact(ref, _REF_KEYS, "refs")
        for key in ("role", "source_id", "source_version", "revision_id"):
            _text(ref[key], 128, "refs")
        if ref["role"] in roles:
            _fail("duplicate_source_role", "refs")
        roles.add(ref["role"])
        for key in ("snapshot_sha256", "time_evidence_sha256"):
            if ref[key] is not None:
                _hash(ref[key], "refs")
    for key in ("plan_payload_sha256", "original_inputs_sha256", "config_sha256"):
        _hash(record[key], "record")


_CALLER_PLAN_FIELDS = frozenset({
    "side", "trigger_rule", "trigger_price", "confirmation_rule", "confirmation_price",
    "entry_rule", "entry_min", "entry_max", "no_chase_cap", "invalidation_rule",
    "invalid_price", "target_1", "target_2", "tick_rule", "tick_size", "entry_fee_rate",
    "exit_fee_rate", "exit_tax_rate", "entry_slippage_ticks", "exit_slippage_ticks",
    "minimum_volume", "minimum_turnover", "decision_at", "earliest_execution_at",
    "expires_at", "invalidation_event_key",
})
_CALLER_OBSERVATION_FIELDS = frozenset({
    "trigger_high", "trigger_at", "confirmation_close", "confirmation_at",
    "session_open_reference_price", "session_started_at", "session_ended_at", "assessed_at",
    "session_high", "session_low", "volume", "turnover", "halted", "event_state", "event_at",
})


def _caller_decimal(value: object, *, positive: bool, rate: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite():
        _fail("caller_decimal_required", "caller_input")
    if not -8 <= value.as_tuple().exponent <= 12 or value < 0 or value > Decimal("1000000000000") or (positive and value == 0) or (rate and value >= 1):
        _fail("caller_decimal_range", "caller_input")


def _caller_count(value: object, *, positive: bool = False, maximum: int = 1000000000000) -> None:
    if type(value) is not int or not 0 <= value <= maximum or (positive and value == 0):
        _fail("caller_count_range", "caller_input")


def _caller_compatibility(record: dict) -> None:
    """Controlled compatibility shape, not a complete financial Plan schema.

    For declared payload_schema_id=caller-trade-plan/v1, original_inputs is
    exactly {plan, observation} using formal caller input field names. Only
    input types/bounds and declaration markers are checked; no financial
    computation, cross-field strategy evaluation, source or PIT validation.
    All other declared payload schemas remain opaque bounded objects.
    """
    if record["declared_versions"]["payload_schema_id"] != "caller-trade-plan/v1":
        return
    if record["declared_versions"]["plan_version"] != "caller-trade-plan/v1" or record["declared_versions"]["execution_version"] != "caller-execution/v1":
        _fail("caller_declared_version_mismatch", "caller_input")
    inputs = _exact(record["original_inputs"], frozenset({"plan", "observation"}), "caller_input")
    plan = _exact(inputs["plan"], _CALLER_PLAN_FIELDS, "caller_input")
    obs = _exact(inputs["observation"], _CALLER_OBSERVATION_FIELDS, "caller_input")
    for key in ("trigger_price", "confirmation_price", "entry_min", "entry_max", "no_chase_cap", "invalid_price", "target_1", "target_2", "tick_size", "minimum_turnover"):
        _caller_decimal(plan[key], positive=True)
    for key in ("entry_fee_rate", "exit_fee_rate", "exit_tax_rate"):
        _caller_decimal(plan[key], positive=False, rate=True)
    for key in ("trigger_high", "confirmation_close", "session_open_reference_price", "session_high", "session_low"):
        _caller_decimal(obs[key], positive=True)
    _caller_decimal(obs["turnover"], positive=False)
    _caller_count(plan["entry_slippage_ticks"], maximum=1000000)
    _caller_count(plan["exit_slippage_ticks"], maximum=1000000)
    _caller_count(plan["minimum_volume"], positive=True)
    _caller_count(obs["volume"])
    for obj, names in ((plan, ("decision_at", "earliest_execution_at", "expires_at")), (obs, ("trigger_at", "confirmation_at", "session_started_at", "session_ended_at", "assessed_at"))):
        for key in names:
            if type(obj[key]) is not datetime:
                _fail("caller_datetime_required", "caller_input")
            _native_utc(obj[key])
    if obs["event_at"] is not None:
        if type(obs["event_at"]) is not datetime:
            _fail("caller_datetime_required", "caller_input")
        _native_utc(obs["event_at"])
    if type(obs["halted"]) is not bool:
        _fail("caller_bool_required", "caller_input")
    choices = {"side": "long", "trigger_rule": "high_at_or_above", "confirmation_rule": "close_at_or_above", "entry_rule": "caller_session_open", "invalidation_rule": "session_low_at_or_below", "tick_rule": "constant_tick"}
    for key, expected in choices.items():
        if plan[key] != expected:
            _fail("caller_choice_required", "caller_input")
    if obs["event_state"] not in ("clear", "occurred", "unknown"):
        _fail("caller_choice_required", "caller_input")
    if type(plan["invalidation_event_key"]) is not str or not plan["invalidation_event_key"].strip():
        _fail("caller_event_key_required", "caller_input")
    payload = record["plan_payload"]
    markers = {"trade_plan_version": "caller-trade-plan/v1", "execution_version": "caller-execution/v1", "evaluation_scope": "post_session_hypothetical", "point_in_time_status": "not_asserted", "fill_status": "not_asserted"}
    for key, value in markers.items():
        if payload.get(key) != value:
            _fail("caller_hypothetical_markers_required", "caller_payload")
    # Check typed representations of known output fields if supplied. Output
    # decimals keep their full tuple: input quantum/magnitude guards do not
    # apply to derived results. These checks do not establish completeness.
    for section, keys in {
        "tick": ("size",), "trigger": ("price", "observed_high"),
        "confirmation": ("price", "observed_close"),
        "entry": ("min", "max", "no_chase_cap", "session_open_reference_price", "hypothetical_entry_after_slippage"),
        "invalidation": ("price",), "targets": ("target_1", "target_2"),
        "costs": ("entry_fee_rate", "exit_fee_rate", "exit_tax_rate", "hypothetical_target_1_cost_space_per_unit"),
        "liquidity": ("minimum_turnover", "turnover"),
    }.items():
        if section not in payload:
            continue
        part = payload[section]
        if type(part) is not dict:
            _fail("caller_output_object_required", "caller_payload")
        for key in keys:
            if key in part and not (section == "costs" and key == "hypothetical_target_1_cost_space_per_unit" and part[key] is None) and type(part[key]) is not Decimal:
                _fail("caller_output_decimal_required", "caller_payload")
    for section, keys in {"costs": ("entry_slippage_ticks", "exit_slippage_ticks"), "liquidity": ("minimum_volume", "volume")}.items():
        if section in payload:
            for key in keys:
                if key in payload[section]:
                    _caller_count(payload[section][key], positive=key == "minimum_volume", maximum=1000000 if key.endswith("slippage_ticks") else 1000000000000)
    for key in ("decision_at", "earliest_execution_at", "expires_at", "session_started_at", "session_ended_at", "assessed_at", "hypothetical_open_reference_at"):
        if key in payload and type(payload[key]) is not datetime:
            _fail("caller_output_datetime_required", "caller_payload")
    for section, key in (("trigger", "at"), ("confirmation", "at"), ("invalidation", "event_at")):
        if section in payload and key in payload[section] and not (section == "invalidation" and payload[section][key] is None) and type(payload[section][key]) is not datetime:
            _fail("caller_output_datetime_required", "caller_payload")


def _record(raw: bytes) -> dict:
    record = _exact(canonical_decode(raw), _RECORD_KEYS, "record")
    _metadata(record)
    for subtree, digest in (("plan_payload", "plan_payload_sha256"), ("original_inputs", "original_inputs_sha256"), ("config_snapshot", "config_sha256")):
        if type(record[subtree]) is not dict:
            _fail("subtree_object_required", "record")
        if sha256(canonical_encode(record[subtree])) != record[digest]:
            _fail("subtree_sha256_mismatch", "record")
    _caller_compatibility(record)
    return record


def _root_string(root: object) -> str:
    if type(root) is not str:
        _fail("normalized_absolute_root_required", "root")
    # Reject lexical invalidity before even native path normalization. NUL
    # cannot be a path character on either supported platform. Windows also
    # excludes ASCII controls and reserved literal component characters;
    # the drive's one colon is permitted, component colons are not.
    if "\x00" in root or (os.name == "nt" and (any(ord(char) < 32 or char in '<>"|?*' for char in root) or ":" in root[2:])):
        _fail("root_character_forbidden", "root")
    if not os.path.isabs(root) or os.path.normpath(root) != root or os.path.abspath(root) != root or Path(root).parent == Path(root):
        _fail("normalized_absolute_root_required", "root")
    if os.name == "nt":
        drive, _ = os.path.splitdrive(root)
        if re.fullmatch(r"[A-Za-z]:", drive, re.ASCII) is None:
            _fail("local_drive_root_required", "root")
        for part in Path(root).parts[1:]:
            stem = part.split(".", 1)[0].upper()
            if part.endswith((".", " ")) or ":" in part or stem in {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}:
                _fail("root_alias_forbidden", "root")
    return root


def validate_ownership(root: str, expected_ownership: bytes, expected_ownership_sha256: str) -> dict:
    """RAM-only external owner validation. No stat/open/path resolution."""
    _root_string(root)
    _hash(expected_ownership_sha256, "ownership")
    owner = _exact(canonical_decode(expected_ownership, max_bytes=MAX_OWNERSHIP_BYTES), _OWNER_KEYS, "ownership")
    if sha256(expected_ownership) != expected_ownership_sha256:
        _fail("ownership_sha256_mismatch", "ownership")
    if owner["schema"] != OWNERSHIP_SCHEMA or owner["store_version"] != STORE_VERSION or type(owner["issue"]) is not int or owner["issue"] != 35 or owner["absolute_root"] != root:
        _fail("ownership_binding_mismatch", "ownership")
    for key in ("namespace", "actual_qa_session", "root_id"):
        _text(owner[key], 128, "ownership", ascii_only=True)
    if type(owner["plan_id"]) is not str or _PLAN_ID.fullmatch(owner["plan_id"]) is None:
        _fail("plan_id_required", "ownership")
    _utc_text(owner["created_at"], "ownership")
    allowed = owner["allowed_revisions"]
    if type(allowed) is not list or not 1 <= len(allowed) <= 128:
        _fail("revision_allowlist_required", "ownership")
    for rev in allowed:
        _revision(rev, "ownership")
    if allowed != sorted(set(allowed)) or any(rev > 1 and rev - 1 not in allowed for rev in allowed):
        _fail("revision_allowlist_or_parent_invalid", "ownership")
    return owner


def _allow(owner: dict, record: dict) -> None:
    if record["plan_id"] != owner["plan_id"] or record["revision"] not in owner["allowed_revisions"]:
        _fail("record_not_owned_or_allowed", "ownership")


def _binding(root: str, raw: bytes) -> dict:
    binding = _exact(canonical_decode(raw), _BIND_KEYS, "binding")
    if binding["schema"] != BINDING_SCHEMA or binding["store_version"] != STORE_VERSION or binding["absolute_root"] != root:
        _fail("binding_store_or_root_mismatch", "binding")
    _metadata(binding)
    return binding


def validate_record(record_bytes: bytes, *, root: str, expected_ownership: bytes, expected_ownership_sha256: str, expected_record_sha256: str, expected_binding: bytes) -> dict:
    """Validate full record, owner and exact external binding before any I/O."""
    owner = validate_ownership(root, expected_ownership, expected_ownership_sha256)
    _hash(expected_record_sha256, "record")
    binding = _binding(root, expected_binding)
    record = _record(record_bytes)
    if sha256(record_bytes) != expected_record_sha256:
        _fail("record_sha256_mismatch", "record")
    _allow(owner, record)
    actual = {key: record[key] for key in _BIND_RECORD_KEYS}
    actual.update(schema=BINDING_SCHEMA, store_version=STORE_VERSION, absolute_root=root)
    if canonical_encode(actual) != expected_binding:
        _fail("exact_binding_mismatch", "binding")
    # binding metadata validation above is deliberately independent of record.
    if binding["revision"] != record["revision"]:
        _fail("exact_binding_mismatch", "binding")
    return record


def validate_revision_chain(record_bytes: bytes, parent_bytes: bytes | None) -> dict:
    """RAM-only full-record parent check; real store operations read ancestors."""
    current = _record(record_bytes)
    if current["revision"] == 1:
        if parent_bytes is not None:
            _fail("unexpected_parent", "chain")
        return current
    if parent_bytes is None:
        _fail("parent_required", "chain")
    parent = _record(parent_bytes)
    if parent["plan_id"] != current["plan_id"] or parent["revision"] != current["revision"] - 1 or sha256(parent_bytes) != current["parent_record_sha256"]:
        _fail("parent_full_record_mismatch", "chain")
    if canonical_encode(parent["identity"]) != canonical_encode(current["identity"]) or any(parent["declared_versions"][key] != current["declared_versions"][key] for key in ("payload_schema_id", "payload_schema_sha256")):
        _fail("identity_or_schema_changed", "chain")
    return current


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _path_guard(root: str, *, initial: bool = False) -> Path:
    path = Path(root)
    # Inspect exact ancestors, never enumerate a directory or other resources.
    for ancestor in reversed((path, *path.parents)):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            if initial and ancestor == path:
                continue
            _fail("root_or_parent_missing", "path")
        if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
            _fail("root_or_parent_alias_forbidden", "path")
        if initial and ancestor == path:
            _fail("initial_root_already_exists", "path")
    if os.path.realpath(root) != root:
        _fail("root_alias_forbidden", "path")
    return path


def _regular(path: Path) -> os.stat_result:
    info = path.lstat()
    if _is_reparse(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("file_alias_or_type_forbidden", "path")
    return info


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _io_error(exc: BaseException, stage: str) -> PlanStoreError:
    if isinstance(exc, PlanStoreError):
        return exc
    if isinstance(exc, FileExistsError):
        return PlanStoreError("already_exists", stage)
    if isinstance(exc, FileNotFoundError):
        return PlanStoreError("missing_file", stage)
    return PlanStoreError("storage_io_error", stage)


def _with_secondary(first: PlanStoreError, secondary: list[dict]) -> PlanStoreError:
    return PlanStoreError(first.code, first.stage, first.secondary + tuple(secondary))


def _read_file(path: Path, cap: int, stage: str) -> bytes:
    fd = None
    first = None
    secondary = []
    result = b""
    try:
        _path_guard(str(path.parent))
        before = _regular(path)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        if not _same_file(before, opened) or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > cap:
            _fail("file_changed_or_limit", stage)
        chunks = []
        remaining = cap + 1
        while remaining:
            piece = os.read(fd, min(8192, remaining))
            if not piece:
                break
            chunks.append(piece)
            remaining -= len(piece)
        result = b"".join(chunks)
        after = os.fstat(fd)
        if len(result) > cap or len(result) != opened.st_size or after.st_size != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns or not _same_file(opened, _regular(path)):
            _fail("file_changed_or_limit", stage)
    except Exception as exc:
        first = _io_error(exc, stage)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception as exc:
                close = _io_error(exc, stage + "_close")
                if first is None:
                    first = close
                else:
                    secondary.append(close.receipt())
    if first is not None:
        raise _with_secondary(first, secondary)
    return result


def _verify_owner(root: str, expected: bytes) -> Path:
    path = _path_guard(root)
    if _read_file(path / OWNERSHIP_FILE, MAX_OWNERSHIP_BYTES, "ownership_read") != expected:
        _fail("stored_ownership_mismatch", "ownership_read")
    return path


def _filename(revision: int) -> str:
    return "revision-" + str(revision).zfill(6) + ".json"


def _stored_chain(path: Path, owner: dict, current: bytes) -> None:
    record = _record(current)
    _allow(owner, record)
    while record["revision"] > 1:
        parent = _read_file(path / _filename(record["revision"] - 1), MAX_RECORD_BYTES, "parent_read")
        validate_revision_chain(current, parent)
        record = _record(parent)
        _allow(owner, record)
        current = parent


def initialize_plan_store(*, root: str, expected_ownership: bytes, expected_ownership_sha256: str) -> dict:
    """Create a new root and exact external marker; existing roots are refused.

    Requires separately authorized disk use. Failure cleanup only attempts
    the newly created marker and empty root owned by this invocation.
    """
    validate_ownership(root, expected_ownership, expected_ownership_sha256)
    path = None
    created_root = False
    root_identity = None
    marker_identity = None
    first = None
    secondary = []
    try:
        path = _path_guard(root, initial=True)
        path.mkdir(mode=0o700)
        created_root = True
        _path_guard(root)
        root_identity = path.lstat()
        # Record marker identity immediately after its exclusive creation.
        marker_identity = _create_new(path / OWNERSHIP_FILE, expected_ownership, "ownership_write")
        if _read_file(path / OWNERSHIP_FILE, MAX_OWNERSHIP_BYTES, "ownership_verify") != expected_ownership:
            _fail("ownership_verify_mismatch", "ownership_verify")
        if not _same_file(root_identity, path.lstat()):
            _fail("root_changed", "ownership_verify")
    except Exception as exc:
        first = _io_error(exc, "initialize")
        if isinstance(exc, _OwnedWriteError):
            marker_identity = exc.identity
    if first is not None and created_root:
        if marker_identity is not None:
            try:
                if not _same_file(marker_identity, _regular(path / OWNERSHIP_FILE)):
                    _fail("cleanup_ownership_changed", "ownership_cleanup")
                (path / OWNERSHIP_FILE).unlink()
            except Exception as exc:
                secondary.append(_io_error(exc, "ownership_cleanup").receipt())
        try:
            _path_guard(root)
            if root_identity is None or not _same_file(root_identity, path.lstat()):
                _fail("cleanup_root_changed", "root_cleanup")
            path.rmdir()
        except Exception as exc:
            secondary.append(_io_error(exc, "root_cleanup").receipt())
    if first is not None:
        raise _with_secondary(first, secondary)
    return {"store_version": STORE_VERSION, "absolute_root": root, "ownership_sha256": expected_ownership_sha256, "storage_integrity": "ownership_initialized", "semantic_status": "not_asserted"}


def save_plan_record(*, root: str, record_bytes: bytes, expected_ownership: bytes, expected_ownership_sha256: str, expected_record_sha256: str, expected_binding: bytes) -> dict:
    """Save canonical bytes using a fixed exclusive stage and no-replace publish.

    Windows os.rename fails when the target exists. On POSIX a hard-link
    publication is same-filesystem and exclusive; only the owned stage link
    is subsequently removed. Neither route uses replace semantics. Directory
    fsync durability across power loss is not asserted. Exact repeated bytes
    produce idempotence.
    """
    record = validate_record(record_bytes, root=root, expected_ownership=expected_ownership, expected_ownership_sha256=expected_ownership_sha256, expected_record_sha256=expected_record_sha256, expected_binding=expected_binding)
    owner = validate_ownership(root, expected_ownership, expected_ownership_sha256)
    stage_identity = None
    first = None
    secondary = []
    receipt = None
    path = None
    try:
        path = _verify_owner(root, expected_ownership)
        _stored_chain(path, owner, record_bytes)
        target = path / _filename(record["revision"])
        try:
            old = _read_file(target, MAX_RECORD_BYTES, "revision_read")
        except PlanStoreError as exc:
            if exc.code != "missing_file":
                raise
        else:
            if old != record_bytes:
                _fail("revision_conflict", "save")
            return _record_receipt(root, record_bytes, record, "idempotent")
        staging = path / STAGING_FILE
        # The stage is owned only if this call's exclusive open succeeded.
        stage_identity = _create_new(staging, record_bytes, "stage_write")
        if _read_file(staging, MAX_RECORD_BYTES, "stage_verify") != record_bytes:
            _fail("stage_verify_mismatch", "stage_verify")
        _verify_owner(root, expected_ownership)
        _stored_chain(path, owner, record_bytes)
        if not _same_file(stage_identity, _regular(staging)):
            _fail("stage_changed", "publish")
        try:
            if os.name == "nt":
                # Windows rename is no-replace; os.link's no-follow option
                # is not supported by the current Windows Python runtime.
                os.rename(staging, target)
                stage_identity = None  # The stage path was consumed.
            else:
                if os.link not in os.supports_follow_symlinks:
                    _fail("no_replace_publish_unsupported", "publish")
                os.link(staging, target, follow_symlinks=False)
        except FileExistsError:
            old = _read_file(target, MAX_RECORD_BYTES, "publish_race_read")
            if old != record_bytes:
                _fail("revision_conflict", "publish")
            receipt = _record_receipt(root, record_bytes, record, "idempotent")
        else:
            receipt = _record_receipt(root, record_bytes, record, "saved")
    except Exception as exc:
        first = _io_error(exc, "save")
        if isinstance(exc, _OwnedWriteError):
            stage_identity = exc.identity
    finally:
        if stage_identity is not None:
            try:
                _path_guard(root)
                staging = path / STAGING_FILE
                info = staging.lstat()
                if _is_reparse(info) or not stat.S_ISREG(info.st_mode) or not _same_file(stage_identity, info):
                    _fail("cleanup_stage_changed", "stage_cleanup")
                staging.unlink()
            except Exception as exc:
                cleanup = _io_error(exc, "stage_cleanup")
                if first is None:
                    first = cleanup
                else:
                    secondary.append(cleanup.receipt())
    if first is not None:
        raise _with_secondary(first, secondary)
    try:
        if _read_file(path / _filename(record["revision"]), MAX_RECORD_BYTES, "published_verify") != record_bytes:
            _fail("published_verify_mismatch", "published_verify")
        _verify_owner(root, expected_ownership)
    except Exception as exc:
        raise _io_error(exc, "published_verify") from exc
    return receipt


class _OwnedWriteError(PlanStoreError):
    def __init__(self, first: PlanStoreError, identity: os.stat_result | None) -> None:
        super().__init__(first.code, first.stage, first.secondary)
        self.identity = identity


def _create_new(path: Path, raw: bytes, stage: str) -> os.stat_result:
    fd = None
    identity = None
    first = None
    secondary = []
    try:
        _path_guard(str(path.parent))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
        identity = os.fstat(fd)
        if _is_reparse(identity) or not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1 or not _same_file(identity, _regular(path)):
            _fail("created_file_changed_or_alias", stage)
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            if count <= 0:
                _fail("incomplete_write", stage)
            offset += count
        os.fsync(fd)
    except Exception as exc:
        first = _io_error(exc, stage)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception as exc:
                close = _io_error(exc, stage + "_close")
                if first is None:
                    first = close
                else:
                    secondary.append(close.receipt())
    if first is not None:
        if fd is not None and identity is None:
            # Exclusive creation succeeded, but without a physical identity
            # it is unsafe to unlink a potentially changed path. Report the
            # unresolved cleanup separately rather than deleting by name.
            secondary.append({"code": "cleanup_identity_unavailable", "stage": "file_cleanup"})
        raise _OwnedWriteError(_with_secondary(first, secondary), identity)
    return identity


def _record_receipt(root: str, raw: bytes, record: dict, operation: str) -> dict:
    return {"store_version": STORE_VERSION, "absolute_root": root, "plan_id": record["plan_id"], "revision": record["revision"], "record_sha256": sha256(raw), "canonical_bytes": raw, "record": record, "storage_integrity": operation, "semantic_status": "not_asserted"}


def read_plan_record(*, root: str, expected_ownership: bytes, expected_ownership_sha256: str, expected_record_sha256: str, expected_binding: bytes) -> dict:
    """Read one exact revision with external expectations; performs no writes."""
    owner = validate_ownership(root, expected_ownership, expected_ownership_sha256)
    _hash(expected_record_sha256, "record")
    binding = _binding(root, expected_binding)
    _allow(owner, binding)
    try:
        path = _verify_owner(root, expected_ownership)
        raw = _read_file(path / _filename(binding["revision"]), MAX_RECORD_BYTES, "revision_read")
        record = validate_record(raw, root=root, expected_ownership=expected_ownership, expected_ownership_sha256=expected_ownership_sha256, expected_record_sha256=expected_record_sha256, expected_binding=expected_binding)
        _stored_chain(path, owner, raw)
        _verify_owner(root, expected_ownership)
    except Exception as exc:
        raise _io_error(exc, "read") from exc
    return _record_receipt(root, raw, record, "read_verified")
