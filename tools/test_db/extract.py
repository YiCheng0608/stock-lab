"""Summary extract of a private TPEx daily-close bundle into a fixture and metadata for ``build-sample``.

    python -B -X utf8 -m tools.test_db.extract --source <bundle dir> --out <dir outside the repo>

The bundle (``body.csv``, ``capture-receipt.json``, ``storage-receipt.json``) is only ever opened for reading and
nothing is written next to it. Before any row is read the body bytes and both receipts must agree with the pinned
:class:`Profile` (body SHA-256, policy versions and digests, symbols, dates, hashes between the files); any
difference ends in ``source_mismatch`` and no output is written. The outputs are ``<out>/<name>-fixture.json``
(``tables`` in the shape ``load-fixture`` takes: ``instruments`` and ``market_bars`` of the product schema) and
``<out>/<name>-metadata.json`` (for ``build-sample --kind real_sample --meta``). Both hold market values: keep them
in a scratch directory, never in the repository. The printed result carries hashes, counts and column names only.
Standard library only; the product is not imported and nothing touches the network.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .errors import DbEntryError
from .paths import assert_allowed_target, inherited_protected_paths, is_link_or_reparse, is_within
from .sample import sha256_file

BODY_NAME = "body.csv"
CAPTURE_RECEIPT_NAME = "capture-receipt.json"
STORAGE_RECEIPT_NAME = "storage-receipt.json"
HEADER = (
    "資料日期", "代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額", "成交筆數",
    "最後買價", "最後賣價", "發行股數", "次日參考價", "次日漲停價", "次日跌停價",
)
# Source column -> product column; every other source column is dropped (the product schema has no place for it).
COLUMN_MAP = {
    "代號": "instruments.symbol", "名稱": "instruments.name",
    "開盤": "market_bars.open", "最高": "market_bars.high", "最低": "market_bars.low", "收盤": "market_bars.close",
    "成交股數": "market_bars.volume", "成交金額": "market_bars.turnover",
}
PRICE_RE = re.compile(r"\d+(?:\.\d+)?")
COUNT_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class Profile:
    """What a bundle must be before it may be summarized: one source, one day, a fixed list of symbols."""

    name: str
    source_id: str
    source_version: str
    data_date: date
    symbols: tuple[str, ...]
    body_sha256: str
    capture_policy: tuple[str, str]  # (policy_version, policy_digest)
    storage_policy: tuple[str, str]
    authorization: str


# SOURCE_REGISTRY 29.1 (".5": seven symbols) and 30.1; the user's A1 decision on Issue #52 limits this to a summary.
A1 = Profile(
    name="tpex-11370-a1",
    source_id="tpex_11370_daily_close_csv",
    source_version="tpex-11370/2026-10-06",
    data_date=date(2026, 10, 6),
    symbols=("3105", "3293", "5274", "5347", "6488", "6510", "8069"),
    body_sha256="ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200",
    capture_policy=(
        "m2-stock-scope-tpex-11370-2026-10-06.5",
        "sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040",
    ),
    storage_policy=(
        "m1-price-save-tpex-11370-2026-10-06.1",
        "sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e",
    ),
    authorization=(
        "Issue #52 user decision A1 (comment 6108606518, 2026-10-11): read-only summary of the seven symbols for one "
        "day; no copy of the original, no change to it, no new external GET"
    ),
)


def _mismatch(reason: str, path: Path | str | None = None, **details: Any) -> DbEntryError:
    return DbEntryError("source_mismatch", reason, path=path, **details)


def _read_bytes(path: Path) -> bytes:
    try:
        with open(path, "rb") as handle:  # read-only, never any other mode
            return handle.read()
    except OSError as exc:
        raise DbEntryError("io_error", f"cannot read {path.name}: {type(exc).__name__}: {exc}", path=path) from exc


def _load_json(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise _mismatch(f"{path.name} is not UTF-8 JSON: {exc}", path) from exc
    if not isinstance(value, dict):
        raise _mismatch(f"{path.name} must be a JSON object", path)
    return value


def _utc_naive(stamp: str, path: Path) -> str:
    """An aware timestamp as the naive UTC text SQLAlchemy stores for DateTime columns."""

    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError) as exc:
        raise _mismatch(f"{path.name}: unreadable timestamp {stamp!r}", path) from exc
    if moment.tzinfo is None:
        raise _mismatch(f"{path.name}: timestamp {stamp!r} has no UTC offset", path)
    return moment.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")


def read_bundle(source: Path) -> tuple[bytes, bytes, bytes]:
    """The three bundle files as bytes (body, capture receipt, storage receipt); each is opened read-only."""

    return tuple(_read_bytes(source / name) for name in (BODY_NAME, CAPTURE_RECEIPT_NAME, STORAGE_RECEIPT_NAME))  # type: ignore[return-value]


def verify_bundle(files: tuple[bytes, bytes, bytes], profile: Profile, source: Path) -> dict[str, Any]:
    """Check body and receipts against ``profile``; return the facts later steps need. Raises ``source_mismatch``."""

    body, capture_raw, storage_raw = files
    body_path, capture_path, storage_path = (source / name for name in (BODY_NAME, CAPTURE_RECEIPT_NAME, STORAGE_RECEIPT_NAME))
    body_sha = hashlib.sha256(body).hexdigest()
    if body_sha != profile.body_sha256:
        raise _mismatch(
            f"{BODY_NAME} sha256 {body_sha} is not the registry value {profile.body_sha256}", body_path, size_bytes=len(body),
            actual_sha256=body_sha, expected_sha256=profile.body_sha256,
        )
    capture, storage = _load_json(capture_raw, capture_path), _load_json(storage_raw, storage_path)
    capture_sha = hashlib.sha256(capture_raw).hexdigest()
    symbols = list(profile.symbols)
    checks = {
        "capture.body_sha256": capture.get("body_sha256") == profile.body_sha256,
        "capture.body_bytes": capture.get("body_bytes") == len(body),
        "capture.policy_version": capture.get("policy_version") == profile.capture_policy[0],
        "capture.policy_digest": capture.get("policy_digest") == profile.capture_policy[1],
        "capture.selected_symbols": capture.get("selected_symbols") == symbols,
        "capture.source_id": capture.get("source_id") == profile.source_id,
        "capture.source_version": capture.get("source_version") == profile.source_version,
        "capture.storage": capture.get("storage") == "process_memory",
        "storage.body_sha256": storage.get("body_sha256") == profile.body_sha256,
        "storage.body_bytes": storage.get("body_bytes") == len(body),
        "storage.capture_policy_version": storage.get("capture_policy_version") == profile.capture_policy[0],
        "storage.capture_policy_digest": storage.get("capture_policy_digest") == profile.capture_policy[1],
        "storage.storage_policy_version": storage.get("storage_policy_version") == profile.storage_policy[0],
        "storage.storage_policy_digest": storage.get("storage_policy_digest") == profile.storage_policy[1],
        "storage.capture_receipt_sha256": storage.get("capture_receipt_sha256") == capture_sha,
        "storage.capture_receipt_bytes": storage.get("capture_receipt_bytes") == len(capture_raw),
        "storage.selected_symbols": storage.get("selected_symbols") == symbols,
        "storage.source_id": storage.get("source_id") == profile.source_id,
        "storage.source_version": storage.get("source_version") == profile.source_version,
        "storage.storage": storage.get("storage") == "private_local",
        "storage.as_of": storage.get("as_of") == profile.data_date.isoformat(),
        "captured_at": isinstance(capture.get("captured_at"), str) and capture.get("captured_at") == storage.get("captured_at"),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise _mismatch(f"receipts disagree with the registry pins on {failed}", source, failed=failed)
    return {
        "body": body, "body_sha256": body_sha, "capture": capture, "storage": storage, "capture_sha256": capture_sha,
        "capture_bytes": len(capture_raw), "storage_sha256": hashlib.sha256(storage_raw).hexdigest(),
        "storage_bytes": len(storage_raw), "checks": {name: "ok" for name in checks},
    }


def parse_rows(body: bytes, profile: Profile, expected_rows: Any, path: Path) -> list[dict[str, str]]:
    """The profile's symbols out of the body, one row each, after the whole file passed structural checks."""

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _mismatch(f"{BODY_NAME} is not UTF-8: {exc}", path) from exc
    records = list(csv.reader(io.StringIO(text, newline="")))
    if not records or tuple(records[0]) != HEADER:
        raise _mismatch(f"{BODY_NAME} header differs from the expected {len(HEADER)} columns", path)
    data = records[1:]
    if expected_rows != len(data):
        raise _mismatch(f"{BODY_NAME} has {len(data)} data rows but the receipt says {expected_rows}", path)
    roc = f"{profile.data_date.year - 1911}{profile.data_date.month:02d}{profile.data_date.day:02d}"
    codes: dict[str, dict[str, str]] = {}
    for number, record in enumerate(data, start=2):
        if len(record) != len(HEADER):
            raise _mismatch(f"{BODY_NAME} line {number} has {len(record)} columns, expected {len(HEADER)}", path)
        row = dict(zip(HEADER, record))
        if row["資料日期"] != roc:
            raise _mismatch(f"{BODY_NAME} line {number} is dated {row['資料日期']!r}, expected {roc!r}", path)
        if row["代號"] in codes:
            raise _mismatch(f"{BODY_NAME} line {number} repeats a code", path)
        codes[row["代號"]] = row
    absent = [symbol for symbol in profile.symbols if symbol not in codes]
    if absent:
        raise _mismatch(f"{BODY_NAME} has no row for {absent}", path)
    return [codes[symbol] for symbol in profile.symbols]


def _number(row: dict[str, str], column: str, pattern: re.Pattern[str], path: Path) -> Decimal:
    value = row[column].strip()
    if not pattern.fullmatch(value):
        raise _mismatch(f"{row['代號']}: column {column} is not a plain non-negative number", path)
    return Decimal(value)


def build_tables(rows: list[dict[str, str]], captured_at: str, data_date: date, path: Path) -> list[dict[str, Any]]:
    stamp, as_of = captured_at, f"{data_date.isoformat()} 00:00:00.000000"
    instruments, bars = [], []
    for identity, row in enumerate(rows, start=1):
        o, h, l, c = (_number(row, column, PRICE_RE, path) for column in ("開盤", "最高", "最低", "收盤"))
        volume, turnover = _number(row, "成交股數", COUNT_RE, path), _number(row, "成交金額", PRICE_RE, path)
        if not (0 < l <= o <= h and l <= c <= h):
            raise _mismatch(f"{row['代號']}: open/high/low/close are not a consistent positive price range", path)
        instruments.append({
            "id": identity, "market": "TW", "exchange": "TPEx", "symbol": row["代號"], "name": row["名稱"],
            "instrument_type": "stock", "is_watchlisted": 0, "status": "active", "created_at": stamp,
        })
        bars.append({
            "instrument_id": identity, "trading_date": data_date.isoformat(), "open": float(o), "high": float(h),
            "low": float(l), "close": float(c), "adj_close": float(c),  # the product worker stores adj_close = close
            "volume": int(volume), "turnover": float(turnover), "turnover_status": "available", "source": "tpex",
            "data_as_of": as_of, "collected_at": stamp, "is_suspended": 0,
        })
    return [{"table": "instruments", "rows": instruments}, {"table": "market_bars", "rows": bars}]


def build_metadata(profile: Profile, facts: dict[str, Any], fixture_name: str, fixture_sha256: str) -> dict[str, Any]:
    capture, storage = facts["capture"], facts["storage"]
    attribution = capture.get("attribution") if isinstance(capture.get("attribution"), dict) else {}
    day = profile.data_date.isoformat()
    dropped = [column for column in HEADER if column not in COLUMN_MAP and column != "資料日期"]
    owners = attribution.get("owners")
    return {
        "source_rights": (
            f"{attribution.get('license', 'unknown')} ({attribution.get('license_url', 'unknown')}); owners "
            f"{', '.join(owners) if isinstance(owners, list) else 'unknown'}; private local summary under SOURCE_REGISTRY policies "
            f"{profile.capture_policy[0]} and {profile.storage_policy[0]}; {profile.authorization}"
        ),
        "data_dates": {"first": day, "last": day},
        "acquired_at": capture["captured_at"],
        "publication_time": attribution.get("publication_time", "unknown"),
        "sampling_rule": (
            f"Summary of one daily-close CSV ({profile.source_id}, data date {day}): only the rows whose 代號 is one of "
            f"{', '.join(profile.symbols)}, one row per symbol, {len(profile.symbols)} rows of "
            f"{capture.get('row_count', 'unknown')}; no other row and no other day. "
            "instruments: id in code order, market=TW, exchange=TPEx, symbol, name, instrument_type=stock, status=active, "
            "is_watchlisted=0, created_at=receipt captured_at (not a creation time). "
            "market_bars: open, high, low, close, volume=成交股數, turnover=成交金額 (turnover_status=available), source=tpex, "
            "data_as_of=data date 00:00, collected_at=receipt captured_at, is_suspended=0, "
            "adj_close=close as the product worker stores it (not an adjusted price), raw_payload_id=NULL. "
            f"Source columns not stored: {', '.join(dropped)}. Single day only: no history, MA60 or corporate-action case."
        ),
        "provenance": {
            "extractor": f"tools.test_db.extract/{profile.name}",
            "authorization": profile.authorization,
            "source_id": profile.source_id,
            "source_version": profile.source_version,
            "endpoint": capture.get("endpoint", "unknown"),
            "data_date": day,
            "captured_at": capture["captured_at"],
            "request_started_at": capture.get("request_started_at", "unknown"),
            "saved_at": storage.get("saved_at", "unknown"),
            "capture_policy": {"version": profile.capture_policy[0], "digest": profile.capture_policy[1]},
            "storage_policy": {"version": profile.storage_policy[0], "digest": profile.storage_policy[1]},
            "body": {"file": BODY_NAME, "sha256": facts["body_sha256"], "bytes": len(facts["body"]), "rows": capture.get("row_count")},
            "capture_receipt": {"file": CAPTURE_RECEIPT_NAME, "sha256": facts["capture_sha256"], "bytes": facts["capture_bytes"]},
            "storage_receipt": {"file": STORAGE_RECEIPT_NAME, "sha256": facts["storage_sha256"], "bytes": facts["storage_bytes"]},
            "selected_symbols": list(profile.symbols),
            "attribution": attribution,
            "limitations": capture.get("limitations", "unknown"),
            "column_map": COLUMN_MAP,
            "columns_not_stored": dropped,
            "fixture": {"file": fixture_name, "sha256": fixture_sha256},
        },
    }


def _dump(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_new(path: Path, payload: bytes) -> None:
    try:
        with open(path, "xb") as handle:  # exclusive: an existing file is never replaced
            handle.write(payload)
    except FileExistsError as exc:
        raise DbEntryError("io_error", f"{path.name} already exists; remove it or choose another --out", path=path) from exc
    except OSError as exc:
        raise DbEntryError("io_error", f"cannot write {path.name}: {type(exc).__name__}: {exc}", path=path) from exc


def extract(source: Path | str, out: Path | str, profile: Profile = A1) -> dict[str, Any]:
    source_dir = Path(source)
    if not source_dir.is_dir() or is_link_or_reparse(source_dir):
        raise DbEntryError("not_found", "source must be an existing directory and not a link", path=source_dir)
    out_dir = assert_allowed_target(out, role="extract output", protected=inherited_protected_paths())
    if is_within(out_dir, source_dir) or is_within(source_dir, out_dir):
        raise DbEntryError("forbidden_target", "output and source directories must not contain one another", path=out_dir)
    facts = verify_bundle(read_bundle(source_dir), profile, source_dir)
    capture = facts["capture"]
    rows = parse_rows(facts["body"], profile, capture.get("row_count"), source_dir / BODY_NAME)
    captured = _utc_naive(capture["captured_at"], source_dir / CAPTURE_RECEIPT_NAME)
    tables = build_tables(rows, captured, profile.data_date, source_dir / BODY_NAME)
    day = profile.data_date.isoformat()
    fixture = {
        "fixture_format": 1, "name": f"{profile.name}-summary",
        "description": f"Summary rows of {profile.source_id} for {day}; real market data, keep out of the repository.",
        "data_dates": {"first": day, "last": day}, "tables": tables,
    }
    fixture_bytes = _dump(fixture)
    fixture_name, meta_name = f"{profile.name}-fixture.json", f"{profile.name}-metadata.json"
    metadata_bytes = _dump(build_metadata(profile, facts, fixture_name, hashlib.sha256(fixture_bytes).hexdigest()))
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_path, meta_path = out_dir / fixture_name, out_dir / meta_name
    _write_new(fixture_path, fixture_bytes)
    try:
        _write_new(meta_path, metadata_bytes)
    except DbEntryError:
        fixture_path.unlink(missing_ok=True)  # never leave a fixture without its metadata
        raise
    return {
        "profile": profile.name, "source_dir": str(source_dir.resolve()), "checks": facts["checks"],
        "body": {"sha256": facts["body_sha256"], "bytes": len(facts["body"]), "matches_registry": True},
        "capture_receipt": {"sha256": facts["capture_sha256"], "bytes": facts["capture_bytes"]},
        "storage_receipt": {"sha256": facts["storage_sha256"], "bytes": facts["storage_bytes"]},
        "rows": {"source_data_rows": capture.get("row_count"), "selected": len(rows),
                 "tables": {block["table"]: len(block["rows"]) for block in tables}},
        "columns": {"read": list(HEADER), "stored": COLUMN_MAP},
        "fixture": {"path": str(fixture_path), **dict(zip(("sha256", "size_bytes"), sha256_file(fixture_path)))},
        "metadata": {"path": str(meta_path), **dict(zip(("sha256", "size_bytes"), sha256_file(meta_path)))},
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m tools.test_db.extract", description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", required=True, help="private bundle directory (opened read-only)")
    parser.add_argument("--out", required=True, help="absolute output directory outside the repo (scratch, not the sample library)")
    args = parser.parse_args(argv)
    try:
        payload = {"ok": True, "result": extract(args.source, args.out)}
        code = 0
    except DbEntryError as exc:
        payload, code = {"ok": False, "error": exc.to_dict()}, 1
    except OSError as exc:
        payload, code = {"ok": False, "error": DbEntryError("io_error", f"{type(exc).__name__}: {exc}", path=exc.filename).to_dict()}, 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
