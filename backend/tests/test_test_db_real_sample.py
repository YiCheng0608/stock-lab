"""Summary extract and guarded repeated reads of a ``real_sample`` (Issue #52).

Every bundle here is invented: fictional codes, prices and digests. The private original and any market value stay out
of this file. Cases that put files on disk land under the directory named by ``STOCK_TESTDB_ROOT`` and are skipped
without it, which does not count as disk acceptance; the byte-level cases need no disk at all.
"""

import ast
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # tools/ is a namespace package at the project root

from tools.test_db import DbEntry, DbEntryError, netguard  # noqa: E402
from tools.test_db.extract import (  # noqa: E402
    A1, BODY_NAME, CAPTURE_RECEIPT_NAME, HEADER, STORAGE_RECEIPT_NAME, Profile, build_tables, extract, parse_rows, verify_bundle,
)
from tools.test_db.paths import remove_tree_or_raise  # noqa: E402
from tools.test_db.sample import DB_NAME, META_NAME, REAL_SAMPLE_REQUIRED, is_unset, sha256_file  # noqa: E402

DAY = date(2026, 10, 6)
SYMBOLS = ("F001", "F002", "F003")
CAPTURED_AT = "2026-10-06T23:32:21.005311+00:00"
CAPTURE_POLICY = ("fictional-capture-policy.1", "sha256:" + "1" * 64)
STORAGE_POLICY = ("fictional-storage-policy.1", "sha256:" + "2" * 64)
# code, name, close, open, high, low, shares, amount: distinctive numbers so a leak into any report is detectable
ROWS = [
    ("F001", "Fictional One", "13.37", "13.01", "13.99", "12.88", "7654321", "98765432101"),
    ("F002", "Fictional Two", "444.50", "440.00", "450.25", "439.75", "1357911", "2468013579"),
    ("F003", "Fictional Three", "9.81", "9.80", "9.99", "9.70", "8642", "84217"),
    ("F900", "Unselected", "1.23", "1.20", "1.30", "1.10", "11", "13"),
]
LEAKY = ("13.37", "7654321", "98765432101", "444.50", "2468013579", "Fictional One")
NETWORK_MODULES = {
    "socket", "_socket", "ssl", "http", "urllib3", "requests", "httpx", "aiohttp", "asyncio", "ftplib", "smtplib",
    "poplib", "imaplib", "telnetlib", "xmlrpc", "websocket", "websockets",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def body_bytes(rows=ROWS, roc="1151006"):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    for code, name, close, open_, high, low, shares, amount in rows:
        writer.writerow([roc, code, name, close, "+0.10", open_, high, low, "10.20", shares, amount, "5", close, close, "100000", close, "11.00", "9.00"])
    return out.getvalue().encode("utf-8")


def make_bundle(rows=ROWS, mutate_capture=None, mutate_storage=None):
    """(files, profile): body, capture receipt and storage receipt bytes that agree with the returned profile."""

    body = body_bytes(rows)
    capture = {
        "body_sha256": sha(body), "body_bytes": len(body), "captured_at": CAPTURED_AT, "request_started_at": "2026-10-06T23:32:17.000000+00:00",
        "endpoint": "https://example.invalid/daily-close", "policy_version": CAPTURE_POLICY[0], "policy_digest": CAPTURE_POLICY[1],
        "row_count": len(rows), "selected_symbols": list(SYMBOLS), "source_id": "fictional_daily_csv", "source_version": "fictional/2026-10-06",
        "storage": "process_memory", "limitations": ["single_day_only"],
        "attribution": {"license": "Fictional-1.0", "license_url": "https://example.invalid/license", "owners": ["Owner A", "Owner B"],
                        "publication_time": "unknown", "first_available_time": "unknown"},
    }
    if mutate_capture:
        mutate_capture(capture)
    capture_raw = json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    storage = {
        "version": "fictional-storage-receipt/v1", "storage": "private_local", "as_of": DAY.isoformat(), "body_sha256": sha(body),
        "body_bytes": len(body), "capture_policy_version": CAPTURE_POLICY[0], "capture_policy_digest": CAPTURE_POLICY[1],
        "storage_policy_version": STORAGE_POLICY[0], "storage_policy_digest": STORAGE_POLICY[1], "capture_receipt_sha256": sha(capture_raw),
        "capture_receipt_bytes": len(capture_raw), "captured_at": CAPTURED_AT, "saved_at": "2026-10-06T23:32:45.000000+00:00",
        "selected_symbols": list(SYMBOLS), "source_id": "fictional_daily_csv", "source_version": "fictional/2026-10-06",
    }
    if mutate_storage:
        mutate_storage(storage)
    storage_raw = json.dumps(storage, ensure_ascii=False, sort_keys=True).encode("utf-8")
    profile = Profile(
        name="fictional-a", source_id="fictional_daily_csv", source_version="fictional/2026-10-06", data_date=DAY, symbols=SYMBOLS,
        body_sha256=sha(body_bytes()), capture_policy=CAPTURE_POLICY, storage_policy=STORAGE_POLICY, authorization="test authorization",
    )
    return (body, capture_raw, storage_raw), profile


def failed_checks(files, profile):
    with pytest.raises(DbEntryError) as error:
        verify_bundle(files, profile, Path("bundle"))
    assert error.value.code == "source_mismatch"
    return error.value


# ---- the pinned values are the registry's -------------------------------------------


def test_a1_profile_matches_source_registry():
    text = (REPO_ROOT / "docs" / "SOURCE_REGISTRY.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| `.5` |"))
    assert "／".join(A1.symbols) in row and A1.capture_policy[1] in row
    assert A1.capture_policy[0] == f"m2-stock-scope-tpex-11370-2026-10-06{row.split('|')[1].strip().strip('`')}"
    assert f"`expected_body_sha256`＝`{A1.body_sha256}`" in text
    storage = text.split("## 30. ")[1].split("## 31. ")[0]
    assert f"`{A1.storage_policy[0]}`" in storage and A1.storage_policy[1] in storage
    assert (A1.source_id, A1.source_version, A1.data_date) == ("tpex_11370_daily_close_csv", "tpex-11370/2026-10-06", date(2026, 10, 6))
    assert all(is_unset(value) is False for value in (A1.source_id, A1.source_version, A1.authorization))


# ---- bundle verification: stop before any row is read ---------------------------------


def test_matching_bundle_passes_every_check_and_exposes_only_what_later_steps_need():
    files, profile = make_bundle()
    facts = verify_bundle(files, profile, Path("bundle"))
    assert set(facts["checks"].values()) == {"ok"} and len(facts["checks"]) >= 20
    assert facts["body_sha256"] == profile.body_sha256 and facts["capture_sha256"] == sha(files[1])


def test_changed_body_bytes_stop_at_the_body_hash_before_anything_else_is_judged():
    files, profile = make_bundle()
    body = bytearray(files[0])
    body[-5] ^= 1
    error = failed_checks((bytes(body), files[1], files[2]), profile)
    assert error.path.endswith(BODY_NAME) and error.details["expected_sha256"] == profile.body_sha256
    assert error.details["actual_sha256"] == sha(bytes(body)) and "failed" not in error.details


CAPTURE_FIELDS = [
    ("body_sha256", "0" * 64), ("body_bytes", 1), ("policy_version", "other.1"), ("policy_digest", "sha256:" + "9" * 64),
    ("selected_symbols", ["F002", "F001", "F003"]), ("source_id", "other"), ("source_version", "other/1"), ("storage", "private_local"),
]
STORAGE_FIELDS = [
    ("body_sha256", "0" * 64), ("body_bytes", 1), ("capture_policy_version", "other.1"), ("capture_policy_digest", "sha256:" + "9" * 64),
    ("storage_policy_version", "other.1"), ("storage_policy_digest", "sha256:" + "9" * 64), ("capture_receipt_sha256", "0" * 64),
    ("capture_receipt_bytes", 1), ("selected_symbols", ["F001"]), ("source_id", "other"), ("source_version", "other/1"),
    ("storage", "process_memory"), ("as_of", "2026-10-05"),
]


@pytest.mark.parametrize("field, bad", CAPTURE_FIELDS, ids=lambda value: str(value)[:24])
def test_each_capture_receipt_pin_is_enforced(field, bad):
    files, profile = make_bundle(mutate_capture=lambda receipt: receipt.update({field: bad}))
    assert failed_checks(files, profile).details["failed"] == [f"capture.{field}"]


@pytest.mark.parametrize("field, bad", STORAGE_FIELDS, ids=lambda value: str(value)[:24])
def test_each_storage_receipt_pin_is_enforced(field, bad):
    files, profile = make_bundle(mutate_storage=lambda receipt: receipt.update({field: bad}))
    assert failed_checks(files, profile).details["failed"] == [f"storage.{field}"]


def test_receipts_must_name_one_capture_time_and_may_not_lack_pins():
    files, profile = make_bundle(mutate_storage=lambda receipt: receipt.update(captured_at="2026-10-06T23:32:22.000000+00:00"))
    assert failed_checks(files, profile).details["failed"] == ["captured_at"]
    files, profile = make_bundle(mutate_capture=lambda receipt: receipt.pop("policy_digest"))
    assert failed_checks(files, profile).details["failed"] == ["capture.policy_digest"]
    files, profile = make_bundle()
    for broken in ((files[0], b"not json", files[2]), (files[0], files[1], b"[]")):
        assert failed_checks(broken, profile).code == "source_mismatch"


def test_the_registry_profile_refuses_any_other_bundle():
    files, _ = make_bundle()
    error = failed_checks(files, A1)
    assert error.details["expected_sha256"] == A1.body_sha256


# ---- reading the rows ---------------------------------------------------------------


def parse(rows=ROWS, **changes):
    files, profile = make_bundle(rows)
    body = changes.pop("body", files[0])
    expected = changes.pop("expected", len(rows))
    return parse_rows(body, profile, expected, Path("bundle") / BODY_NAME)


def test_selected_rows_come_back_in_profile_order_after_the_whole_file_is_checked():
    reordered = [ROWS[2], ROWS[3], ROWS[0], ROWS[1]]
    assert [row["代號"] for row in parse(reordered)] == list(SYMBOLS)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda files: body_bytes(ROWS[:2] + ROWS[3:]), "no row for"),
        (lambda files: body_bytes(ROWS, roc="1151005"), "dated"),
        (lambda files: body_bytes(ROWS + [ROWS[0]]), "repeats a code"),
        (lambda files: files.replace(b"1151006,F003,Fictional Three,9.81,+0.10,9.80", b"1151006,F003,Fictional Three,9.81,+0.10"), "columns"),
        (lambda files: files.replace("代號".encode("utf-8"), "代碼".encode("utf-8"), 1), "header"),
        (lambda files: files + b"\xff\xfe", "UTF-8"),
        (lambda files: files.replace(b",13.37,", b",13.3x,"), "plain non-negative number"),
        (lambda files: files.replace(b",7654321,", b",7,654,321,"), "columns"),
        (lambda files: files.replace(b",13.01,13.99,12.88,", b",13.01,12.00,12.88,"), "consistent positive price range"),
        (lambda files: files.replace(b",13.01,13.99,12.88,", b",13.01,13.99,0,"), "consistent positive price range"),
    ],
    ids=["missing-symbol", "wrong-date", "duplicate-code", "short-row", "header", "not-utf8", "price-text", "thousands", "high-below-open", "zero-low"],
)
def test_structural_and_value_problems_end_as_source_mismatch(mutate, fragment):
    files, profile = make_bundle()
    mutated = mutate(files[0])
    with pytest.raises(DbEntryError) as error:
        rows = parse_rows(mutated, profile, max(0, mutated.count(b"\r\n") - 1), Path("bundle") / BODY_NAME)
        build_tables(rows, "2026-10-06 23:32:21.005311", DAY, Path("bundle") / BODY_NAME)
    assert error.value.code == "source_mismatch" and fragment in error.value.reason
    assert not any(secret in error.value.reason for secret in LEAKY)


def test_row_count_must_equal_the_receipt():
    with pytest.raises(DbEntryError) as error:
        parse(expected=len(ROWS) + 1)
    assert error.value.code == "source_mismatch" and "receipt says" in error.value.reason


def test_tables_use_product_columns_with_adj_close_equal_close_and_exact_types():
    tables = {block["table"]: block["rows"] for block in build_tables(parse(), "2026-10-06 23:32:21.005311", DAY, Path("b"))}
    assert [row["id"] for row in tables["instruments"]] == [1, 2, 3]
    assert [row["symbol"] for row in tables["instruments"]] == list(SYMBOLS)
    first = tables["instruments"][0]
    assert (first["market"], first["exchange"], first["instrument_type"], first["status"], first["is_watchlisted"]) == ("TW", "TPEx", "stock", "active", 0)
    assert first["created_at"] == "2026-10-06 23:32:21.005311" and first["name"] == "Fictional One"
    bar = tables["market_bars"][0]
    assert bar == {
        "instrument_id": 1, "trading_date": "2026-10-06", "open": 13.01, "high": 13.99, "low": 12.88, "close": 13.37, "adj_close": 13.37,
        "volume": 7654321, "turnover": 98765432101.0, "turnover_status": "available", "source": "tpex",
        "data_as_of": "2026-10-06 00:00:00.000000", "collected_at": "2026-10-06 23:32:21.005311", "is_suspended": 0,
    }
    assert type(bar["volume"]) is int and type(bar["turnover"]) is float
    assert len(tables["market_bars"]) == 3  # the unselected row never appears


# ---- the extract on disk ----------------------------------------------------------------


@pytest.fixture(scope="module")
def module_root():
    value = os.environ.get("STOCK_TESTDB_ROOT")
    if not value:
        pytest.skip("STOCK_TESTDB_ROOT is not set: no authorized landing directory for file-backed test-db cases")
    base = Path(value) / f"rs-{uuid.uuid4().hex[:6]}"
    yield base
    remove_tree_or_raise(base)


def write_bundle(base, files=None, name="bundle"):
    files = files or make_bundle()[0]
    bundle = base / name
    bundle.mkdir(parents=True)
    for file_name, raw in zip((BODY_NAME, CAPTURE_RECEIPT_NAME, STORAGE_RECEIPT_NAME), files):
        (bundle / file_name).write_bytes(raw)
        os.chmod(bundle / file_name, 0o444)  # like the private original: nothing in the extract may rewrite it
    return bundle


def snapshot(directory):
    return {item.name: (item.stat().st_size, item.stat().st_mtime_ns, sha256_file(item)[0]) for item in sorted(directory.iterdir())}


@pytest.fixture
def work(module_root):
    base = module_root / f"w-{uuid.uuid4().hex[:6]}"
    base.mkdir(parents=True)
    yield base
    remove_tree_or_raise(base)


def test_extract_writes_two_files_elsewhere_and_leaves_the_bundle_untouched(work):
    files, profile = make_bundle()
    bundle = write_bundle(work)
    before = snapshot(bundle)
    result = extract(bundle, work / "out", profile)
    assert snapshot(bundle) == before and sorted(before) == sorted((BODY_NAME, CAPTURE_RECEIPT_NAME, STORAGE_RECEIPT_NAME))
    assert sorted(item.name for item in (work / "out").iterdir()) == ["fictional-a-fixture.json", "fictional-a-metadata.json"]
    assert result["body"] == {"sha256": profile.body_sha256, "bytes": len(files[0]), "matches_registry": True}
    assert result["rows"] == {"source_data_rows": 4, "selected": 3, "tables": {"instruments": 3, "market_bars": 3}}
    assert result["fixture"]["sha256"] == sha256_file(work / "out" / "fictional-a-fixture.json")[0]
    dumped = json.dumps(result, ensure_ascii=False)
    assert not any(secret in dumped for secret in LEAKY)  # hashes, counts and column names only
    assert "代號" in dumped and "成交股數" in dumped


def test_extract_metadata_states_everything_a_real_sample_needs(work):
    files, profile = make_bundle()
    extract(write_bundle(work), work / "out", profile)
    meta = json.loads((work / "out" / "fictional-a-metadata.json").read_text(encoding="utf-8"))
    for key in REAL_SAMPLE_REQUIRED:
        assert not is_unset(meta[key])
    assert meta["data_dates"] == {"first": "2026-10-06", "last": "2026-10-06"} and meta["acquired_at"] == CAPTURED_AT
    assert meta["publication_time"] == "unknown"
    prov = meta["provenance"]
    assert (prov["source_id"], prov["source_version"], prov["data_date"], prov["captured_at"]) == (
        "fictional_daily_csv", "fictional/2026-10-06", "2026-10-06", CAPTURED_AT)
    assert prov["capture_policy"] == {"version": CAPTURE_POLICY[0], "digest": CAPTURE_POLICY[1]}
    assert prov["storage_policy"] == {"version": STORAGE_POLICY[0], "digest": STORAGE_POLICY[1]}
    assert prov["body"]["sha256"] == sha(files[0]) and prov["capture_receipt"]["sha256"] == sha(files[1])
    assert prov["storage_receipt"]["sha256"] == sha(files[2]) and prov["selected_symbols"] == list(SYMBOLS)
    assert prov["fixture"] == {"file": "fictional-a-fixture.json", "sha256": sha256_file(work / "out" / "fictional-a-fixture.json")[0]}
    assert set(prov["column_map"].values()) <= {f"{t}.{c}" for t in ("instruments", "market_bars") for c in
                                                 ("symbol", "name", "open", "high", "low", "close", "volume", "turnover")}
    assert "漲跌" in prov["columns_not_stored"] and "資料日期" not in prov["columns_not_stored"]
    assert "adj_close=close" in meta["sampling_rule"] and "Single day only" in meta["sampling_rule"]
    assert not any(secret in json.dumps(meta, ensure_ascii=False) for secret in LEAKY)


def test_a_mismatching_bundle_writes_nothing(work):
    files, profile = make_bundle()
    broken = (files[0], files[1], files[2].replace(b'"private_local"', b'"somewhere"'))
    bundle = write_bundle(work, broken)
    with pytest.raises(DbEntryError) as error:
        extract(bundle, work / "out", profile)
    assert error.value.code == "source_mismatch" and not (work / "out").exists()
    with pytest.raises(DbEntryError) as error:
        extract(write_bundle(work, name="other"), work / "out2")  # default profile = the registry's A1 values
    assert error.value.code == "source_mismatch" and not (work / "out2").exists()


def test_outputs_may_not_overlap_the_bundle_or_the_checkout_and_never_replace_files(work):
    _, profile = make_bundle()
    bundle = write_bundle(work)
    before = snapshot(bundle)
    for target, code in ((bundle / "out", "forbidden_target"), (work, "forbidden_target"), (REPO_ROOT / "extract-out", "forbidden_target"),
                         (Path("relative-out"), "forbidden_target")):
        with pytest.raises(DbEntryError) as error:
            extract(bundle, target, profile)
        assert error.value.code == code
    assert not (bundle / "out").exists() and not (REPO_ROOT / "extract-out").exists() and not Path("relative-out").exists()
    extract(bundle, work / "out", profile)
    first = snapshot(work / "out")
    with pytest.raises(DbEntryError) as error:
        extract(bundle, work / "out", profile)
    assert error.value.code == "io_error" and "already exists" in error.value.reason
    assert snapshot(work / "out") == first and snapshot(bundle) == before
    with pytest.raises(DbEntryError) as error:
        extract(work / "absent", work / "out3", profile)
    assert error.value.code == "not_found"


def test_command_line_prints_one_json_object_and_refuses_a_bundle_the_registry_does_not_pin(work):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STOCK_")}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")]))
    bundle = write_bundle(work)
    proc = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "tools.test_db.extract", "--source", str(bundle), "--out", str(work / "cli-out")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=120,
    )
    payload = json.loads(proc.stdout)  # the default profile is the registry's: a fictional bundle cannot pass
    assert proc.returncode == 1 and payload["ok"] is False and payload["error"]["code"] == "source_mismatch"
    assert not (work / "cli-out").exists() and "Traceback" not in proc.stderr


# ---- publish and read the extract as a real_sample (AC-1 / AC-2 on invented data) ----------


@pytest.fixture(scope="module")
def published(module_root):
    """One fictional real_sample version, built from an extract through the shared entry (init-db, fixture, product check)."""

    base = module_root / "pub"
    files, profile = make_bundle()
    bundle = write_bundle(base, files)
    extract(bundle, base / "out", profile)
    entry = DbEntry(base / "library")
    meta = json.loads((base / "out" / "fictional-a-metadata.json").read_text(encoding="utf-8"))
    report = entry.build_sample("fict-a1-v1", base / "out" / "fictional-a-fixture.json", kind="real_sample", meta=meta)
    return entry, report, files, profile


def test_extract_publishes_an_immutable_real_sample_with_its_metadata(published):
    entry, report, files, _ = published
    directory = entry.samples_dir / "fict-a1-v1"
    assert sorted(item.name for item in directory.iterdir()) == [META_NAME, DB_NAME]
    metadata = json.loads((directory / META_NAME).read_text(encoding="utf-8"))
    assert metadata == report["metadata"] and metadata["kind"] == "real_sample" and metadata["sample_version"] == "fict-a1-v1"
    assert metadata["row_counts"] == {"instruments": 3, "market_bars": 3}
    assert (metadata["sha256"], metadata["size_bytes"]) == sha256_file(directory / DB_NAME)
    assert metadata["provenance"]["body"]["sha256"] == sha(files[0]) and metadata["publication_time"] == "unknown"
    assert report["checks"]["product_schema"] == "ok" and report["os_readonly"] is True
    with pytest.raises(DbEntryError) as error:
        entry.build_sample("fict-a1-v1", REPO_ROOT / "backend" / "tests" / "fixtures" / "test_db" / "sample_basic.json")
    assert error.value.code == "version_exists"


def test_published_rows_read_back_with_types_and_without_the_unselected_row(published):
    entry, _, _, _ = published
    instruments = entry.read_table("instruments", version="fict-a1-v1")
    bars = entry.read_table("market_bars", version="fict-a1-v1")
    assert [row["symbol"] for row in instruments] == list(SYMBOLS) and {row["exchange"] for row in instruments} == {"TPEx"}
    assert [row["close"] for row in bars] == [13.37, 444.5, 9.81] and [row["adj_close"] for row in bars] == [13.37, 444.5, 9.81]
    assert [row["volume"] for row in bars] == [7654321, 1357911, 8642] and {row["trading_date"] for row in bars} == {"2026-10-06"}
    assert {row["turnover_status"] for row in bars} == {"available"} and {row["source"] for row in bars} == {"tpex"}
    assert "F900" not in json.dumps(instruments)


# AC-2: the same version, read again and again, never reaches the network.


def guarded(entry, log, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STOCK_")}
    env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", TEMP=str(entry.root / "tmp"), TMP=str(entry.root / "tmp"),
        PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")])),
    )
    (entry.root / "tmp").mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "tools.test_db.netguard", "--log", str(log), "--",
         "--root", str(entry.root), "--python", sys.executable, *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300, stdin=subprocess.DEVNULL,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
    return proc.returncode, payload, proc


def without_scratch_paths(result):
    """The answer minus the per-call scratch directory that the product schema check reports."""

    result = dict(result)
    product = result.pop("product", None)
    if product:
        result["product"] = {key: product[key] for key in ("revisions_head", "alembic_head", "readiness")}
    return result


@pytest.fixture
def reader(module_root, published):
    """A tool root of its own holding a byte-identical copy of the published version."""

    source, _, _, _ = published
    root = module_root / f"r-{uuid.uuid4().hex[:6]}"
    (root / "samples").mkdir(parents=True)
    shutil.copytree(source.samples_dir / "fict-a1-v1", root / "samples" / "fict-a1-v1")
    instance = DbEntry(root)
    yield instance
    remove_tree_or_raise(root)


def test_same_version_is_verified_selected_and_read_repeatedly_with_no_network_attempt(reader):
    log = reader.root / "netguard.log"
    version_dir = reader.samples_dir / "fict-a1-v1"
    before = snapshot(version_dir)
    approved = before[DB_NAME][2]
    outputs = []
    for _ in range(3):
        round_outputs = []
        for args in (
            ("verify", "--version", "fict-a1-v1", "--expect-sha256", approved),
            ("select", "--version", "fict-a1-v1", "--expect-sha256", approved),
            ("read-table", "--version", "fict-a1-v1", "--table", "instruments"),
            ("read-table", "--version", "fict-a1-v1", "--table", "market_bars"),
            ("list-samples",),
        ):
            code, payload, proc = guarded(reader, log, *args)
            assert code == 0 and payload["ok"] is True, proc.stdout + proc.stderr
            round_outputs.append(without_scratch_paths(payload["result"]))
        outputs.append(round_outputs)
    assert outputs[0] == outputs[1] == outputs[2]  # the same bytes answer every time
    assert outputs[0][0]["checks"]["product_schema"] == "ok" and outputs[0][1]["checks"]["product_schema"] == "skipped"
    assert [len(outputs[0][2]["rows"]), len(outputs[0][3]["rows"])] == [3, 3]
    assert snapshot(version_dir) == before  # still exactly the two sealed files, same bytes and times
    events = netguard.read_log(str(log))
    assert [event for event in events if event["event"] == "blocked"] == []
    armed = [event for event in events if event["event"] == "armed"]
    assert sum(event["argv0"] == "netguard.py" for event in armed) == 15  # every tool process was armed
    assert sum(event["argv0"] == "_child.py" for event in armed) == 3  # and so was each product schema check (verify)


def test_isolated_copies_and_exec_children_are_covered_by_the_guard_too(reader):
    log = reader.root / "netguard.log"
    code, payload, proc = guarded(reader, log, "isolate", "--version", "fict-a1-v1", "--run-id", "g1")
    assert code == 0, proc.stdout + proc.stderr
    code, payload, proc = guarded(reader, log, "read-table", "--run-id", "g1", "--table", "market_bars")
    assert code == 0 and len(payload["result"]["rows"]) == 3
    code, payload, proc = guarded(reader, log, "cleanup", "--run-id", "g1")
    assert code == 0 and not (reader.runs_dir / "g1").exists()
    code, _, proc = guarded(reader, log, "exec", "--version", "fict-a1-v1", "--", sys.executable, "-c", "print('child ran')")
    assert code == 0 and "child ran" in proc.stdout
    events = netguard.read_log(str(log))
    assert not [event for event in events if event["event"] == "blocked"]
    assert [event["argv0"] for event in events if event["event"] == "armed"].count("-c") == 1  # the exec'd command was armed


ATTEMPTS = (
    "import socket\n"
    "for call in (lambda: socket.getaddrinfo('example.invalid', 80), lambda: socket.create_connection(('127.0.0.1', 9), timeout=0.2),\n"
    "             lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('127.0.0.1', 9)),\n"
    "             lambda: socket.gethostbyname('example.invalid')):\n"
    "    try:\n"
    "        call()\n"
    "    except OSError as exc:\n"
    "        print(type(exc).__name__)\n"
    "    else:\n"
    "        print('NOT-BLOCKED')\n"
    "import urllib.request\n"
    "try:\n"
    "    urllib.request.urlopen('http://example.invalid/', timeout=0.2)\n"
    "except OSError as exc:\n"
    "    print(type(exc).__name__)\n"
    "else:\n"
    "    print('NOT-BLOCKED')\n"
)


def test_the_guard_really_blocks_connections_names_and_urllib_in_tool_and_exec_processes(reader):
    log = reader.root / "control.log"
    code, _, proc = guarded(reader, log, "exec", "--version", "fict-a1-v1", "--", sys.executable, "-c", ATTEMPTS)
    assert code == 0, proc.stdout + proc.stderr
    printed = proc.stdout.split()
    assert "NOT-BLOCKED" not in printed and printed.count("NetworkBlocked") >= 4 and len(printed) == 5
    blocked = [event for event in netguard.read_log(str(log)) if event["event"] == "blocked"]
    assert {event["name"] for event in blocked} >= {"socket.getaddrinfo", "socket.connect", "socket.gethostbyname"}
    assert len({event["pid"] for event in blocked}) == 1  # raised in the exec'd child, which the sitecustomize armed


def test_guard_without_a_log_or_with_a_missing_command_refuses_to_run(reader):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STOCK_")}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")]))
    proc = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "tools.test_db.netguard", "--root", str(reader.root), "usage"],
                          cwd=REPO_ROOT, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert proc.returncode == 2 and "usage" in proc.stderr


# Structural evidence that no network path exists in the entry.


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def test_no_module_of_the_entry_imports_a_network_library():
    for path in sorted((REPO_ROOT / "tools" / "test_db").rglob("*.py")):
        banned = {name for name in imported_modules(path) if name.split(".")[0] in NETWORK_MODULES or name == "urllib.request"}
        assert not banned, f"{path.name} imports {sorted(banned)}"


def test_a_full_local_read_cycle_never_imports_a_network_module(reader):
    script = (
        "import json, sys\n"
        "from tools.test_db import DbEntry\n"
        f"entry = DbEntry({str(reader.root)!r}, python=sys.executable)\n"
        "entry.verify('fict-a1-v1'); entry.select('fict-a1-v1'); entry.list_samples(); entry.usage()\n"
        "entry.read_table('instruments', version='fict-a1-v1'); entry.read_table('market_bars', version='fict-a1-v1')\n"
        "with entry.isolated('fict-a1-v1') as run:\n"
        "    entry.read_table('market_bars', run_id=run.run_id)\n"
        f"banned = {sorted(NETWORK_MODULES)!r}\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in banned or m == 'urllib.request')))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("STOCK_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")])),
               TEMP=str(reader.root / "tmp"), TMP=str(reader.root / "tmp"))
    (reader.root / "tmp").mkdir(exist_ok=True)
    proc = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script], cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", stdin=subprocess.DEVNULL, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []
