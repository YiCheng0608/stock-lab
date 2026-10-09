"""Explicit conditional-plan store CLI; stdin requests are canonical UTF-8.

Every operation needs --root and --request-stdin. The request's exact keys:
init: expected_ownership (canonical UTF-8 JSON string),
      expected_ownership_sha256 (external lowercase full SHA256).
read: init keys + expected_record_sha256 + expected_binding (canonical JSON
      string containing schema/store_version/absolute_root and record metadata).
save: read keys + record_bytes (canonical UTF-8 JSON string).

Supply expectations from an independent caller/oracle. This tool does not
derive expected hashes/bindings from the record. No request files, defaults,
latest lookup, auto timestamps, source I/O, or financial evaluation exist.
The outer request itself is canonical JSON, with no LF, BOM or extra bytes.
The whole request is capped at 65536 bytes; quoting/ownership/binding overhead
means CLI records have less available space than the module's 65536-byte cap.
The controlled caller compatibility shape is documented in the module.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
MAX_REQUEST_BYTES = 65536


def load_store():
    """Direct source load, bypassing app/__init__, main, config and DB."""
    source = Path(__file__).resolve().parents[1] / "backend" / "app" / "conditional_plan_store.py"
    spec = importlib.util.spec_from_file_location("conditional_plan_store_standalone", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_request(store, command: str, raw: bytes) -> dict:
    """RAM-only bounded request parse. Canonical strings carry inner bytes."""
    expected = {"expected_ownership", "expected_ownership_sha256"}
    if command in ("save", "read"):
        expected |= {"expected_record_sha256", "expected_binding"}
    if command == "save":
        expected.add("record_bytes")
    if command not in ("init", "save", "read"):
        raise store.PlanStoreError("unknown_command", "request")
    # Inner record JSON is transported as a string and can exceed the generic
    # codec's scalar-string bound. Validate the outer transport separately.
    if type(raw) is not bytes or len(raw) > MAX_REQUEST_BYTES:
        raise store.PlanStoreError("request_byte_limit", "request")
    try:
        text = raw.decode("utf-8", "strict")
        store._lexical_depth(text)
        value = json.loads(text, object_pairs_hook=store._no_duplicate, parse_float=store._reject_number, parse_constant=store._reject_number)
        if type(value) is not dict or set(value) != expected or any(type(item) is not str for item in value.values()):
            raise store.PlanStoreError("exact_request_fields_required", "request")
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8", "strict")
        if canonical != raw:
            raise store.PlanStoreError("noncanonical_request", "request")
        result = dict(value)
        for key in ("expected_ownership", "expected_binding", "record_bytes"):
            if key in result:
                result[key] = result[key].encode("utf-8", "strict")
        return result
    except store.PlanStoreError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise store.PlanStoreError("invalid_request_json", "request") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "save", "read"):
        child = subparsers.add_parser(command)
        child.add_argument("--root", required=True, help="native normalized absolute path, externally owned")
        child.add_argument("--request-stdin", required=True, action="store_true", help="read one bounded canonical UTF-8 request, without prompting")
    args = parser.parse_args(argv)
    store = load_store()
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        request = parse_request(store, args.command, raw)
        operation = {"init": store.initialize_plan_store, "save": store.save_plan_record, "read": store.read_plan_record}[args.command]
        receipt = operation(root=args.root, **request)
        if "canonical_bytes" in receipt:
            receipt["canonical_utf8"] = receipt.pop("canonical_bytes").decode("utf-8")
            # CLI wire output uses canonical UTF-8 record text, not native
            # Decimal/datetime serialization or implementation repr strings.
            receipt.pop("record")
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except store.PlanStoreError as exc:
        print(json.dumps({"error": exc.receipt()}, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
