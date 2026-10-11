"""Command line for the test-database entry (run from the project root).

    python -B -X utf8 -m tools.test_db --root <abs dir outside the repo> <command> ...

Every command prints one JSON object: ``{"ok": true, "result": ...}`` or
``{"ok": false, "error": {code, reason, path, size_bytes, details}}`` and exits
0 or 1. ``exec`` passes the child's own exit code through.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .entry import DbEntry
from .errors import DbEntryError
from .paths import DEFAULT_MAX_TOTAL_BYTES


def _emit(payload: dict, stream=None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), file=stream or sys.stdout)


def _meta(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DbEntryError("metadata_invalid", f"cannot read --meta file: {exc}", path=path) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.test_db", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=os.environ.get("STOCK_TESTDB_ROOT"),
                        help="absolute tool root outside the repo (or env STOCK_TESTDB_ROOT)")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES, help="total size limit under --root")
    parser.add_argument("--python", help="interpreter for product child processes (default: this one)")
    parser.add_argument("--deps", action="append", default=None,
                        help="extra PYTHONPATH entry for children (repeatable; default: env STOCK_TEST_DEPS)")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds allowed per product child")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build-sample", help="init-db + fixture rows -> immutable read-only sample version")
    build.add_argument("--version", required=True)
    build.add_argument("--fixture", required=True)
    build.add_argument("--kind", default="manual_fixture", choices=("manual_fixture", "real_sample"))
    build.add_argument("--meta", help="JSON with metadata fields (required for real_sample)")
    build.add_argument("--skip-product-check", action="store_true")

    freeze = commands.add_parser("freeze", help="publish an isolated run's database as a new sample version")
    freeze.add_argument("--run-id", required=True)
    freeze.add_argument("--version", required=True)
    freeze.add_argument("--kind", default="manual_fixture", choices=("manual_fixture", "real_sample"))
    freeze.add_argument("--meta")
    freeze.add_argument("--skip-product-check", action="store_true")

    commands.add_parser("list-samples")
    for name, helptext in (("verify", "hash, version, marker and product schema of a sample"),
                           ("select", "verify (no product check unless asked) and print the read-only location")):
        sub = commands.add_parser(name, help=helptext)
        sub.add_argument("--version", required=True)
        sub.add_argument("--expect-sha256", help="approved hash recorded elsewhere (e.g. on the issue)")
        if name == "verify":
            sub.add_argument("--skip-product-check", action="store_true")
        else:
            sub.add_argument("--check-product", action="store_true")

    isolate = commands.add_parser("isolate", help="fresh writable database at its own path")
    isolate.add_argument("--version", help="sample version to copy; omit for an empty product schema")
    isolate.add_argument("--run-id")
    isolate.add_argument("--check-product", action="store_true")
    isolate.add_argument("--expect-sha256")

    for name, helptext in (("reset", "restore a run to its pristine state"), ("cleanup", "remove a run")):
        commands.add_parser(name, help=helptext).add_argument("--run-id", required=True)

    commands.add_parser("usage", help="bytes used under --root against the limit")

    load = commands.add_parser("load-fixture", help="insert fixture rows into an isolated run")
    load.add_argument("--run-id", required=True)
    load.add_argument("--fixture", required=True)

    read = commands.add_parser("read-table", help="read rows back read-only (separate process readback)")
    target = read.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-id")
    target.add_argument("--version")
    read.add_argument("--table", required=True)
    read.add_argument("--limit", type=int, default=100)

    run = commands.add_parser("exec", help="run a command with isolated STOCK_*; the run is removed afterwards")
    run.add_argument("--version")
    run.add_argument("--check-product", action="store_true")
    run.add_argument("argv", nargs=argparse.REMAINDER, help="-- command [args...]")
    return parser


def _dispatch(args: argparse.Namespace, entry: DbEntry) -> dict:
    command = args.command
    if command == "build-sample":
        return entry.build_sample(args.version, args.fixture, kind=args.kind, meta=_meta(args.meta),
                                  check_product=not args.skip_product_check)
    if command == "freeze":
        return entry.freeze(args.run_id, args.version, kind=args.kind, meta=_meta(args.meta),
                            check_product=not args.skip_product_check)
    if command == "list-samples":
        return {"samples": entry.list_samples()}
    if command == "verify":
        return entry.verify(args.version, expect_sha256=args.expect_sha256, check_product=not args.skip_product_check)
    if command == "select":
        return entry.select(args.version, expect_sha256=args.expect_sha256, check_product=args.check_product)
    if command == "isolate":
        return entry.isolate(args.version, run_id=args.run_id, check_product=args.check_product,
                             expect_sha256=args.expect_sha256).to_dict()
    if command == "reset":
        return entry.reset(args.run_id).to_dict()
    if command == "cleanup":
        return entry.cleanup(args.run_id)
    if command == "usage":
        return entry.usage()
    if command == "load-fixture":
        return {"inserted": entry.load_into_run(args.run_id, args.fixture)}
    if command == "read-table":
        return {"rows": entry.read_table(args.table, run_id=args.run_id, version=args.version, limit=args.limit)}
    raise AssertionError(command)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.root:
        parser.error("--root (or env STOCK_TESTDB_ROOT) is required")
    try:
        entry = DbEntry(args.root, max_bytes=args.max_bytes, python=args.python, deps=args.deps, timeout=args.timeout)
        if args.command == "exec":
            command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            if not command:
                parser.error("exec needs a command after --")
            outcome = entry.run_command(
                command, sample_version=args.version, check_product=args.check_product,
                before_run=lambda readback: _emit({"event": "stock_env_readback", "stock_env": readback}, sys.stderr),
            )
            _emit({"ok": True, "result": outcome}, sys.stderr)
            return outcome["exit_code"]
        _emit({"ok": True, "result": _dispatch(args, entry)})
        return 0
    except DbEntryError as exc:
        _emit({"ok": False, "error": exc.to_dict()})
        return 1
