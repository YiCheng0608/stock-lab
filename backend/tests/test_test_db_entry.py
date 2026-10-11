"""File-backed cases for tools/test_db: sample library, isolated databases, quota and cleanup.

Everything lands under the directory named by ``STOCK_TESTDB_ROOT`` (an absolute
path outside the repo that the running task authorizes) and is removed again.
Without that variable these cases are skipped, which does not count as disk
acceptance. Only hand-written fixtures are used: no daily database, no copied
private data, no external source. The cases deliberately avoid ``tmp_path``.
"""

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # tools/ is a namespace package at the project root

from tools.test_db import DbEntry, DbEntryError  # noqa: E402
from tools.test_db.errors import CleanupError, QuotaExceededError  # noqa: E402
from tools.test_db.paths import remove_tree_or_raise, tree_size  # noqa: E402
from tools.test_db.product import stock_env_for  # noqa: E402
from tools.test_db.sample import DB_NAME, META_NAME, load_fixture, open_readonly, read_fixture, sha256_file  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "test_db" / "sample_basic.json"
HEAD = "0008_portfolio_share_integer"
EXPECTED_COUNTS = {"group_memberships": 2, "instruments": 2, "market_bars": 4, "theme_groups": 1}
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows file locks and junctions")


# ---- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="module")
def module_root():
    value = os.environ.get("STOCK_TESTDB_ROOT")
    if not value:
        pytest.skip("STOCK_TESTDB_ROOT is not set: no authorized landing directory for file-backed test-db cases")
    base = Path(value) / f"m-{uuid.uuid4().hex[:6]}"
    yield base
    remove_tree_or_raise(base)  # CleanupError names path, size and reason


@pytest.fixture(scope="module")
def library(module_root):
    """One sample built once: init-db, hand-written rows, product schema check."""

    entry = DbEntry(module_root / "library")
    report = entry.build_sample("v1", FIXTURE)
    return entry, report


@pytest.fixture
def entry(module_root, library):
    """A tool root of its own per case, holding a byte-identical copy of sample ``v1``."""

    source, _ = library
    root = module_root / f"t-{uuid.uuid4().hex[:6]}"
    (root / "samples").mkdir(parents=True)
    shutil.copytree(source.samples_dir / "v1", root / "samples" / "v1")
    instance = DbEntry(root)
    yield instance
    remove_tree_or_raise(root)


def cli(entry, *args, check=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STOCK_")}
    env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", TEMP=str(entry.root / "tmp"), TMP=str(entry.root / "tmp"),
        PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")])),  # keep the dependency path
    )
    (entry.root / "tmp").mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "tools.test_db", "--root", str(entry.root), "--python", sys.executable, *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300, stdin=subprocess.DEVNULL,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
    return proc.returncode, payload, proc


def rows(db_path, sql):
    with closing(open_readonly(db_path)) as connection:
        return connection.execute(sql).fetchall()


def symbols(db_path):
    return sorted(row[0] for row in rows(db_path, "SELECT symbol FROM instruments"))


# ---- AC-1: shared entry --------------------------------------------------------


def test_built_sample_carries_contract_metadata_and_is_sealed(library):
    entry, report = library
    directory = entry.samples_dir / "v1"
    assert sorted(item.name for item in directory.iterdir()) == [META_NAME, DB_NAME]
    metadata = json.loads((directory / META_NAME).read_text(encoding="utf-8"))
    assert metadata == report["metadata"]
    assert metadata["sample_version"] == "v1" and metadata["kind"] == "manual_fixture"
    assert metadata["schema_version"] == HEAD
    assert metadata["row_counts"] == EXPECTED_COUNTS
    assert (metadata["sha256"], metadata["size_bytes"]) == sha256_file(directory / DB_NAME)
    assert metadata["source_rights"].startswith("not-applicable") and metadata["acquired_at"] == "not-applicable"
    assert metadata["data_dates"] == {"first": "2001-01-02", "last": "2001-01-04"}
    assert metadata["publication_time"] == "unknown"
    assert metadata["provenance"]["fixture"]["sha256"] == sha256_file(FIXTURE)[0]
    assert report["checks"] == {"files": "ok", "version": "ok", "hash": "ok", "marker": "ok", "product_schema": "ok"}
    assert report["os_readonly"] is True and not os.access(directory / DB_NAME, os.W_OK)
    assert report["loaded_rows"] == EXPECTED_COUNTS


def test_sample_rejects_writes_at_each_protection_layer(library):
    entry, _ = library
    db = entry.samples_dir / "v1" / DB_NAME
    insert = "INSERT INTO instruments (market, exchange, symbol, name, instrument_type, is_watchlisted, status, created_at) " \
             "VALUES ('TW', 'TWSE', 'NOPE', 'x', 'stock', 0, 'active', '2001-01-01 00:00:00')"
    with closing(open_readonly(db)) as connection:  # mode=ro + query_only=ON
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] == 2
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(insert)
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as connection:  # mode=ro alone
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(insert)
    with closing(sqlite3.connect(db)) as connection:  # a plain open still meets the read-only file attribute
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(insert)
    assert symbols(db) == ["FX0001", "FX0001"]


def test_open_readonly_blocks_writes_even_on_a_writable_file(entry):
    with entry.isolated("v1") as run:
        assert os.access(run.db_path, os.W_OK)  # nothing but the open mode protects this file
        insert = "DELETE FROM market_bars"
        with closing(open_readonly(run.db_path)) as connection:
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute(insert)
            connection.execute("PRAGMA query_only=OFF")  # lifting the pragma must not lift mode=ro
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute(insert)
        assert rows(run.db_path, "SELECT COUNT(*) FROM market_bars") == [(4,)]


def test_verify_select_and_list_report_the_selected_version(entry):
    verified = entry.verify("v1")
    assert verified["checks"]["product_schema"] == "ok" and verified["product"]["readiness"] == "ok"
    assert verified["product"]["revisions_head"] == HEAD == verified["product"]["alembic_head"]
    selected = entry.select("v1", expect_sha256=verified["sha256"].upper())
    assert selected["read_only_uri"].endswith("sample.db?mode=ro") and selected["checks"]["product_schema"] == "skipped"
    listing = entry.list_samples()
    assert [item["sample_version"] for item in listing] == ["v1"] and listing[0]["sha256"] == verified["sha256"]


def test_isolated_copy_is_independent_writable_and_leaves_the_sample_untouched(entry):
    sample = entry.verify("v1", check_product=False)
    with entry.isolated("v1") as run:
        assert run.db_path != Path(sample["db_path"]) and run.run_dir.parent == entry.runs_dir
        assert sha256_file(run.db_path)[0] == sample["sha256"]
        assert os.access(run.db_path, os.W_OK)
        for name, value in run.stock_env.items():  # all three STOCK_* sit inside the run, none in the sample library
            assert Path(value).is_relative_to(run.run_dir) and not Path(value).is_relative_to(entry.samples_dir), name
        with closing(sqlite3.connect(run.db_path)) as connection:
            connection.execute("DELETE FROM market_bars")
            connection.execute("UPDATE instruments SET name = 'changed'")
            connection.commit()
        assert sha256_file(run.db_path)[0] != sample["sha256"]
    assert entry.verify("v1", check_product=False)["sha256"] == sample["sha256"]  # sample untouched
    assert not run.run_dir.exists()  # removed after the block


def test_empty_isolated_database_uses_the_product_schema_from_init_db(entry):
    with entry.isolated() as run:
        assert run.origin == {"kind": "empty"}
        check = entry.runner.check_schema(run.db_path)
        assert check["readiness"] == "ok" and check["revisions_head"] == HEAD
        assert rows(run.db_path, "SELECT version_num FROM alembic_version") == [(HEAD,)]
        assert rows(run.db_path, "SELECT COUNT(*) FROM instruments") == [(0,)]
        assert run.raw_dir.is_dir()


def test_product_children_bind_to_the_isolated_paths_and_leave_daily_locations_alone(entry):
    watched = [REPO_ROOT / "data", REPO_ROOT / ".local"]
    before = [(path.exists(), path.stat().st_mtime_ns if path.exists() else None) for path in watched]
    with entry.isolated("v1") as run:
        probe = entry.runner.probe("config", [], data_dir=run.data_dir, tmp_dir=run.tmp_dir, allowed_root=run.run_dir)
        assert probe["config"] == probe["stock_env_readback"] == {k: str(Path(v).resolve()) for k, v in run.stock_env.items()}
        entry.runner.probe("insert-instrument", ["--symbol", "PROBE1"], data_dir=run.data_dir, tmp_dir=run.tmp_dir, allowed_root=run.run_dir)
        assert "PROBE1" in symbols(run.db_path)
    after = [(path.exists(), path.stat().st_mtime_ns if path.exists() else None) for path in watched]
    assert after == before


def test_a_row_written_by_one_process_is_read_back_by_others(entry):
    with entry.isolated("v1") as run:
        entry.runner.probe(  # process A: the product's own engine
            "insert-instrument", ["--symbol", "XPROC1", "--name", "written by product child"],
            data_dir=run.data_dir, tmp_dir=run.tmp_dir, allowed_root=run.run_dir,
        )
        code, payload, _ = cli(entry, "read-table", "--run-id", run.run_id, "--table", "instruments")  # process B
        assert code == 0 and "XPROC1" in [row["symbol"] for row in payload["result"]["rows"]]
        assert "XPROC1" in symbols(run.db_path)  # process C: this one, read-only


def test_cli_round_trip_load_read_reset_and_cleanup(entry):
    code, payload, _ = cli(entry, "isolate", "--run-id", "cli1")
    assert code == 0 and payload["result"]["origin"] == {"kind": "empty"}
    code, payload, _ = cli(entry, "load-fixture", "--run-id", "cli1", "--fixture", str(FIXTURE))  # process A writes
    assert code == 0 and payload["result"]["inserted"] == EXPECTED_COUNTS
    code, payload, _ = cli(entry, "read-table", "--run-id", "cli1", "--table", "market_bars")  # process B reads
    assert code == 0 and len(payload["result"]["rows"]) == 4
    code, payload, _ = cli(entry, "reset", "--run-id", "cli1")
    assert code == 0
    assert rows(entry.runs_dir / "cli1" / "data" / "stock.db", "SELECT COUNT(*) FROM market_bars") == [(0,)]
    code, payload, _ = cli(entry, "usage")
    assert code == 0 and payload["result"]["total_bytes"] > 0 and payload["result"]["max_bytes"] == 50_000_000
    code, payload, _ = cli(entry, "cleanup", "--run-id", "cli1")
    assert code == 0 and payload["result"]["removed_bytes"] > 0 and not (entry.runs_dir / "cli1").exists()
    code, payload, _ = cli(entry, "verify", "--version", "v1", "--skip-product-check")
    assert code == 0 and payload["result"]["checks"]["hash"] == "ok"


def test_exec_runs_with_scrubbed_environment_and_removes_the_run(entry, monkeypatch):
    monkeypatch.setenv("STOCK_TWSE_EVENTS_MEMORY_CAPTURE", "1")  # a live-source opt-in must not reach the child
    seen = []
    code = (
        "import json, os, pathlib; "
        "p = pathlib.Path(os.environ['STOCK_RAW_DIR']) / 'probe.txt'; p.write_text('x'); "
        "print(json.dumps({k: v for k, v in os.environ.items() if k.startswith('STOCK_') or k in ('TEMP', 'TMP')}))"
    )
    outcome = entry.run_command([sys.executable, "-B", "-c", code], sample_version="v1", before_run=seen.append)
    assert outcome["exit_code"] == 0 and outcome["cleaned"] is True
    assert seen == [outcome["stock_env_readback"]]  # read back before the command started
    assert not (entry.runs_dir / outcome["run_id"]).exists()
    assert list(entry.runs_dir.iterdir()) == []

    failing = entry.run_command([sys.executable, "-B", "-c", "raise SystemExit(7)"])
    assert failing["exit_code"] == 7 and failing["cleaned"] is True and list(entry.runs_dir.iterdir()) == []


def test_exec_child_sees_only_the_three_isolation_variables(entry, monkeypatch, capfd):
    monkeypatch.setenv("STOCK_TWSE_EVENTS_MEMORY_CAPTURE", "1")
    monkeypatch.setenv("STOCK_TESTDB_ROOT", "inherited-must-not-leak")
    code = "import json, os; print(json.dumps(sorted(k for k in os.environ if k.startswith('STOCK_'))))"
    entry.run_command([sys.executable, "-B", "-c", code])
    names = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    assert names == ["STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR"]


def test_runs_are_checked_before_a_child_starts(entry):
    repo_data_existed = (REPO_ROOT / "data").exists()
    with entry.isolated("v1") as run:
        for env, expected in (
            (stock_env_for(REPO_ROOT / "data"), "product checkout"),
            (stock_env_for(entry.samples_dir / "v1"), "read-only sample library"),
            ({**run.stock_env, "STOCK_DB_PATH": ""}, None),
        ):
            with pytest.raises(DbEntryError) as error:
                entry.runner.run(["-c", "print(1)"], stock_env=env, tmp_dir=run.tmp_dir, allowed_root=run.run_dir, forbidden=(entry.samples_dir,))
            assert error.value.code in ("forbidden_target", "stock_env_invalid")
            if expected:
                assert expected in error.value.reason
    assert (REPO_ROOT / "data").exists() == repo_data_existed  # refused before app.config could create it


def test_two_runs_have_separate_paths_and_state(entry):
    with ThreadPoolExecutor(max_workers=3) as pool:
        runs = list(pool.map(lambda _: entry.isolate("v1"), range(3)))
    try:
        assert len({run.run_dir for run in runs}) == len({run.db_path for run in runs}) == 3
        for run in runs:
            assert run.run_dir.parent == entry.runs_dir
        with ThreadPoolExecutor(max_workers=3) as pool:  # three product processes writing at the same time
            list(pool.map(
                lambda item: entry.runner.probe(
                    "insert-instrument", ["--symbol", f"PAR{item[0]}"],
                    data_dir=item[1].data_dir, tmp_dir=item[1].tmp_dir, allowed_root=item[1].run_dir,
                ),
                enumerate(runs),
            ))
        for index, run in enumerate(runs):
            assert symbols(run.db_path) == sorted(["FX0001", "FX0001", f"PAR{index}"])  # only its own write
        assert entry.verify("v1", check_product=False)["checks"]["hash"] == "ok"
    finally:
        for run in runs:
            entry.cleanup(run.run_id)
    with pytest.raises(DbEntryError) as error:
        first = entry.isolate("v1", run_id="fixed")
        try:
            entry.isolate("v1", run_id="fixed")
        finally:
            entry.cleanup(first.run_id)
    assert error.value.code == "run_exists" and error.value.path.endswith("fixed")


def test_reset_returns_a_run_to_the_verified_sample_copy(entry):
    run = entry.isolate("v1")
    sample = entry.verify("v1", check_product=False)
    with closing(sqlite3.connect(run.db_path)) as connection:
        connection.execute("DELETE FROM market_bars")
        connection.commit()
    (run.raw_dir / "leftover.bin").write_bytes(b"x" * 10)
    (run.tmp_dir / "scratch.bin").write_bytes(b"y")
    again = entry.reset(run.run_id)
    assert again.db_path == run.db_path
    assert sha256_file(run.db_path)[0] == sample["sha256"]
    assert list(run.raw_dir.iterdir()) == [] and list(run.tmp_dir.iterdir()) == []
    entry.cleanup(run.run_id)


# ---- AC-2: limits and cleanup reports ----------------------------------------------


def test_over_limit_isolate_names_the_path_size_and_reason_and_creates_nothing(entry):
    size = entry.verify("v1", check_product=False)["size_bytes"]
    tight = DbEntry(entry.root, max_bytes=tree_size(entry.root) + size - 1)
    with pytest.raises(QuotaExceededError) as error:
        tight.isolate("v1", run_id="over")
    failure = error.value
    assert failure.code == "quota_exceeded" and failure.path == str(tight.runs_dir / "over")
    assert failure.size_bytes == tree_size(entry.root) + size > tight.max_bytes
    assert failure.details["limit_bytes"] == tight.max_bytes and failure.details["incoming_bytes"] == size
    assert str(tight.root) in failure.reason and "exceeds" in failure.reason
    assert not (tight.runs_dir / "over").exists()


def test_growth_during_init_db_is_caught_and_the_partial_run_is_removed(entry):
    tight = DbEntry(entry.root, max_bytes=tree_size(entry.root) + 200_000)  # init-db writes ~426 KB
    with pytest.raises(QuotaExceededError) as error:
        tight.isolate(run_id="grow")
    assert error.value.path == str(tight.runs_dir / "grow") and error.value.size_bytes > tight.max_bytes
    assert not (tight.runs_dir / "grow").exists()
    assert tree_size(entry.root) == tree_size(entry.samples_dir)  # nothing left behind


def test_over_limit_publication_leaves_no_partial_sample(entry):
    size = entry.verify("v1", check_product=False)["size_bytes"]
    tight = DbEntry(entry.root, max_bytes=tree_size(entry.root) + size + 1_000)
    run = tight.isolate("v1", run_id="src")  # fits: one copy of the sample
    try:
        with pytest.raises(QuotaExceededError) as error:
            tight.freeze(run, "v2", check_product=False)
        assert "freeze" in error.value.reason and error.value.size_bytes > tight.max_bytes
    finally:
        tight.cleanup("src")
    assert sorted(item.name for item in tight.samples_dir.iterdir()) == ["v1"]


@windows_only
def test_cleanup_of_a_file_in_use_reports_path_size_and_reason_and_can_be_retried(entry):
    run = entry.isolate("v1")
    size = run.db_path.stat().st_size
    (run.raw_dir / "extra.bin").write_bytes(b"z" * 5)
    holder = open(run.db_path, "rb")  # a Windows handle without share-delete keeps the file from being removed
    try:
        with pytest.raises(CleanupError) as error:
            entry.cleanup(run.run_id)
    finally:
        holder.close()
    failure = error.value
    assert failure.code == "cleanup_failed" and failure.path == str(run.db_path) and failure.size_bytes == size
    assert "PermissionError" in failure.reason and failure.details["remaining_bytes"] >= size
    assert [item["path"] for item in failure.failures] == [str(run.db_path)]
    assert not (run.raw_dir / "extra.bin").exists()  # everything removable was removed
    assert entry.cleanup(run.run_id)["removed_bytes"] >= size  # marker survived, so the retry works
    assert not run.run_dir.exists()


@windows_only
def test_reset_of_a_run_in_use_reports_path_size_and_reason_and_keeps_the_database(entry):
    run = entry.isolate("v1")
    size = run.db_path.stat().st_size
    before = sha256_file(run.db_path)
    holder = open(run.db_path, "rb")
    try:
        with pytest.raises(CleanupError) as error:
            entry.reset(run.run_id)
    finally:
        holder.close()
    assert error.value.path == str(run.db_path) and error.value.size_bytes == size and "PermissionError" in error.value.reason
    assert sha256_file(run.db_path) == before  # the pristine copy was not half-replaced
    assert entry.reset(run.run_id).db_path == run.db_path  # and the reset works once the file is free
    entry.cleanup(run.run_id)


@windows_only
def test_cleanup_refuses_to_enter_or_remove_a_reparse_point(entry):
    run = entry.isolate("v1")
    outside = entry.root / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    link = run.raw_dir / "link"
    made = subprocess.run(  # cmd prints in the console code page; only the exit code matters here
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True, errors="replace"
    )
    assert made.returncode == 0, made.stderr
    try:
        with pytest.raises(CleanupError) as error:
            entry.cleanup(run.run_id)
        assert error.value.path == str(link) and "reparse point" in error.value.reason
        assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"  # never followed
        with pytest.raises(DbEntryError) as sizing:
            tree_size(run.run_dir)  # quota accounting refuses what it cannot see
        assert sizing.value.code == "reparse_point"
    finally:
        os.rmdir(link)  # removes the junction itself
    entry.cleanup(run.run_id)
    assert (outside / "keep.txt").exists() and not run.run_dir.exists()


def test_cleanup_only_touches_directories_it_created(entry):
    plain = entry.runs_dir / "plain"
    plain.mkdir(parents=True)
    (plain / "mine.txt").write_text("not a run", encoding="utf-8")
    with pytest.raises(DbEntryError) as error:
        entry.cleanup("plain")
    assert error.value.code == "not_a_run_dir" and error.value.path == str(plain)
    assert (plain / "mine.txt").exists()
    for marker in (  # a marker that is not this run's, or from another format, does not authorize removal either
        {"marker_schema": 1, "run_id": "someone-else", "origin": {"kind": "empty"}},
        {"marker_schema": 99, "run_id": "plain", "origin": {"kind": "empty"}},
        {"marker_schema": 1, "run_id": "plain"},
    ):
        (plain / ".testdb-run.json").write_text(json.dumps(marker), encoding="utf-8")
        with pytest.raises(DbEntryError) as error:
            entry.cleanup("plain")
        assert error.value.code == "not_a_run_dir" and (plain / "mine.txt").exists()
    for bad, code in (("absent", "run_not_found"), ("..", "invalid_argument"), ("a/b", "invalid_argument")):
        with pytest.raises(DbEntryError) as error:
            entry.cleanup(bad)
        assert error.value.code == code


# ---- AC-3: error boundaries with hand-written fixtures ----------------------------


def tampered_clone(entry, name, mutate):
    """Copy ``v1`` under ``name`` with consistent metadata, then apply one defect."""

    target = entry.samples_dir / name
    shutil.copytree(entry.samples_dir / "v1", target)
    for item in target.iterdir():
        os.chmod(item, stat.S_IWRITE)
    meta = json.loads((target / META_NAME).read_text(encoding="utf-8"))
    meta["sample_version"] = name
    (target / META_NAME).write_text(json.dumps(meta), encoding="utf-8")
    mutate(target)
    return target


def test_hash_mismatch_names_the_file_its_size_and_both_hashes(entry):
    def flip(target):
        data = bytearray((target / DB_NAME).read_bytes())
        data[len(data) // 2] ^= 0xFF  # same size, different content
        (target / DB_NAME).write_bytes(bytes(data))

    original = entry.verify("v1", check_product=False)
    changed = tampered_clone(entry, "v3", flip)
    with pytest.raises(DbEntryError) as error:
        entry.verify("v3", check_product=False)
    failure = error.value
    assert failure.code == "hash_mismatch" and failure.path == str(changed / DB_NAME)
    assert failure.size_bytes == original["size_bytes"] == (changed / DB_NAME).stat().st_size
    assert failure.details["recorded_sha256"] == original["sha256"] != failure.details["actual_sha256"]
    with pytest.raises(DbEntryError) as refused:  # an isolated copy is never made from a tampered sample
        entry.isolate("v3", run_id="never")
    assert refused.value.code == "hash_mismatch" and not (entry.runs_dir / "never").exists()


def test_approved_hash_pin_must_match(entry):
    sha = entry.verify("v1", check_product=False)["sha256"]
    with pytest.raises(DbEntryError) as error:
        entry.verify("v1", expect_sha256="0" * 64, check_product=False)
    assert error.value.code == "hash_mismatch" and error.value.details["approved_sha256"] == "0" * 64
    assert error.value.details["actual_sha256"] == sha and error.value.path.endswith(DB_NAME)
    with pytest.raises(DbEntryError):
        entry.select("v1", expect_sha256="f" * 64)
    with pytest.raises(DbEntryError) as refused:
        entry.isolate("v1", expect_sha256="f" * 64, run_id="pinned")
    assert refused.value.code == "hash_mismatch" and not (entry.runs_dir / "pinned").exists()


def test_missing_version_lists_what_exists_and_bad_names_never_reach_the_filesystem(entry):
    for call in (entry.verify, entry.select, entry.isolate):
        with pytest.raises(DbEntryError) as error:
            call("v404")
        assert error.value.code == "version_missing" and "['v1']" in error.value.reason
        assert error.value.path == str(entry.samples_dir / "v404")
    for bad in ("..", "../v1", "v1/..", "", ".partial-x"):
        with pytest.raises(DbEntryError) as error:
            entry.verify(bad)
        assert error.value.code == "invalid_argument"
    code, payload, _ = cli(entry, "verify", "--version", "v404")
    assert code == 1 and payload["ok"] is False and payload["error"]["code"] == "version_missing"


def test_sample_directories_must_match_their_metadata(entry):
    renamed = entry.samples_dir / "v2"
    shutil.copytree(entry.samples_dir / "v1", renamed)  # metadata still says v1
    with pytest.raises(DbEntryError) as error:
        entry.verify("v2", check_product=False)
    assert error.value.code == "version_mismatch" and error.value.path == str(renamed)

    def add_file(target):
        (target / "stock.db-journal").write_bytes(b"hot journal")

    tampered_clone(entry, "v4", add_file)
    with pytest.raises(DbEntryError) as error:
        entry.verify("v4", check_product=False)
    assert error.value.code == "sample_corrupt" and "stock.db-journal" in error.value.reason

    tampered_clone(entry, "v5", lambda target: (target / META_NAME).unlink())
    with pytest.raises(DbEntryError) as error:
        entry.verify("v5", check_product=False)
    assert error.value.code == "sample_corrupt"


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda meta: "{not json", "cannot read metadata"),
        (lambda meta: {k: v for k, v in meta.items() if k != "source_rights"}, "source_rights"),
        (lambda meta: {**meta, "metadata_schema": 99}, "unsupported metadata_schema"),
        (lambda meta: {**meta, "kind": "scraped"}, "unknown kind"),
    ],
)
def test_invalid_metadata_is_rejected(entry, mutate, fragment):
    def rewrite(target):
        meta = json.loads((target / META_NAME).read_text(encoding="utf-8"))
        meta["sample_version"] = "m1"
        changed = mutate(meta)
        (target / META_NAME).write_text(changed if isinstance(changed, str) else json.dumps(changed), encoding="utf-8")

    tampered_clone(entry, "m1", rewrite)
    with pytest.raises(DbEntryError) as error:
        entry.verify("m1", check_product=False)
    assert error.value.code == "metadata_invalid" and fragment in error.value.reason
    assert error.value.path.endswith(META_NAME)


def test_database_marker_must_match_the_recorded_schema_version(entry):
    def claim_older_schema(target):
        meta = json.loads((target / META_NAME).read_text(encoding="utf-8"))
        meta.update(sample_version="s1", schema_version="0007_turnover_availability")
        (target / META_NAME).write_text(json.dumps(meta), encoding="utf-8")

    tampered_clone(entry, "s1", claim_older_schema)
    with pytest.raises(DbEntryError) as error:
        entry.verify("s1", check_product=False)
    assert error.value.code == "schema_mismatch" and "0007_turnover_availability" in error.value.reason
    assert error.value.path.endswith(DB_NAME)


def test_stale_and_damaged_schemas_are_not_published_and_are_caught_when_verified(entry):
    with entry.isolated("v1") as run:  # revision marker one step behind the product head
        with closing(sqlite3.connect(run.db_path)) as connection:
            connection.execute("UPDATE alembic_version SET version_num = '0007_turnover_availability'")
            connection.commit()
        with pytest.raises(DbEntryError) as error:  # refused at publication, nothing left behind
            entry.freeze(run, "stale")
        stale = error.value
        assert stale.code == "schema_mismatch" and f"is not the product head {HEAD}" in stale.reason
        assert "0007_turnover_availability" in stale.reason and "publish a new sample version" in stale.reason
        assert sorted(item.name for item in entry.samples_dir.iterdir()) == ["v1"]
        published = entry.freeze(run, "stale", check_product=False)  # marker and metadata agree, so file checks pass
        assert published["checks"]["product_schema"] == "skipped"
        with pytest.raises(DbEntryError) as error:  # but the product check still sees it
            entry.verify("stale")
        assert error.value.code == "schema_mismatch" and f"is not the product head {HEAD}" in error.value.reason

    with entry.isolated("v1") as run:  # a missing product table
        with closing(sqlite3.connect(run.db_path)) as connection:
            connection.execute("DROP TABLE news_items")
            connection.commit()
        with pytest.raises(DbEntryError) as error:
            entry.freeze(run, "damaged")
        assert error.value.code == "schema_mismatch" and "news_items is missing" in error.value.reason
        entry.freeze(run, "damaged", check_product=False)
        with pytest.raises(DbEntryError) as error:
            entry.verify("damaged")
        assert error.value.code == "schema_mismatch" and "news_items is missing" in error.value.reason
        assert entry.verify("damaged", check_product=False)["checks"]["hash"] == "ok"  # file-level checks alone cannot see it


def test_a_published_version_is_never_replaced(entry):
    with pytest.raises(DbEntryError) as error:
        entry.build_sample("v1", FIXTURE)
    assert error.value.code == "version_exists" and error.value.path == str(entry.samples_dir / "v1")
    with entry.isolated("v1") as run:
        with pytest.raises(DbEntryError) as error:
            entry.freeze(run, "v1")
        assert error.value.code == "version_exists"


def tiny_database(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            "CREATE TABLE parent (id INTEGER PRIMARY KEY, label TEXT NOT NULL);"
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES parent(id));"
        )


@pytest.mark.parametrize(
    "tables, fragment",
    [
        ([{"table": "nope", "rows": [{"id": 1}]}], "unknown table"),
        ([{"table": "parent", "rows": [{"id": 1, "label": "a", "bogus": 1}]}], "unknown columns ['bogus']"),
        ([{"table": "parent", "rows": [{"id": 1, "label": "a"}, {"id": 1, "label": "dup"}]}], "rejected by SQLite"),
        ([{"table": "parent", "rows": [{"id": 1}]}], "rejected by SQLite"),  # NOT NULL label
        ([{"table": "parent", "rows": [{"id": 1, "label": "a"}]}, {"table": "child", "rows": [{"id": 1, "parent_id": 99}]}], "rejected by SQLite"),
        ([{"table": 'parent"; DROP TABLE parent; --', "rows": [{"id": 1}]}], "unusable table name"),
        ([{"table": "sqlite_master", "rows": [{"name": "x"}]}], "unusable table name"),
        ([{"table": "parent", "rows": [[1, "a"]]}], "non-empty object"),
        ([{"table": "parent", "rows": "nope"}], "'rows' list"),
        (["parent"], "'rows' list"),
    ],
)
def test_bad_fixture_rows_are_rejected_and_nothing_stays_written(module_root, tables, fragment):
    root = module_root / f"f-{uuid.uuid4().hex[:6]}"
    root.mkdir(parents=True)
    try:
        db = root / "tiny.db"
        tiny_database(db)
        with pytest.raises(DbEntryError) as error:
            load_fixture(db, {"tables": tables})
        assert error.value.code == "fixture_invalid" and fragment in error.value.reason
        assert error.value.path == str(db)
        with closing(sqlite3.connect(db)) as connection:  # the whole fixture was rolled back
            assert connection.execute("SELECT COUNT(*) FROM parent").fetchone() == (0,)
            assert connection.execute("SELECT COUNT(*) FROM child").fetchone() == (0,)
    finally:
        remove_tree_or_raise(root)


def test_fixture_files_and_targets_are_validated(module_root):
    root = module_root / f"f-{uuid.uuid4().hex[:6]}"
    root.mkdir(parents=True)
    try:
        for name, content, fragment in (
            ("bad.json", "{not json", "cannot read fixture"),
            ("flat.json", json.dumps({"tables": "x"}), "'tables' list"),
            ("list.json", json.dumps([1]), "'tables' list"),
        ):
            (root / name).write_text(content, encoding="utf-8")
            with pytest.raises(DbEntryError) as error:
                read_fixture(root / name)
            assert error.value.code == "fixture_invalid" and fragment in error.value.reason
        with pytest.raises(DbEntryError) as error:
            read_fixture(root / "absent.json")
        assert error.value.code == "fixture_invalid"
        with pytest.raises(DbEntryError) as error:  # loading never creates a database
            load_fixture(root / "absent.db", {"tables": []})
        assert error.value.code == "not_found" and not (root / "absent.db").exists()
    finally:
        remove_tree_or_raise(root)


def test_an_unusable_fixture_publishes_nothing_and_removes_its_build_run(entry):
    bad = entry.root / "bad_fixture.json"
    bad.write_text(json.dumps({"tables": [{"table": "instruments", "rows": [{"id": 1, "bogus": 2}]}]}), encoding="utf-8")
    with pytest.raises(DbEntryError) as error:
        entry.build_sample("v9", bad)
    assert error.value.code == "fixture_invalid" and "unknown columns" in error.value.reason
    assert sorted(item.name for item in entry.samples_dir.iterdir()) == ["v1"]
    assert list(entry.runs_dir.iterdir()) == []


def test_real_sample_without_stated_rights_is_refused_end_to_end(entry):
    with pytest.raises(DbEntryError) as error:
        entry.build_sample("real1", FIXTURE, kind="real_sample", meta={"sampling_rule": "x"})
    assert error.value.code == "metadata_invalid" and "source_rights" in error.value.reason
    assert sorted(item.name for item in entry.samples_dir.iterdir()) == ["v1"]
    assert not entry.runs_dir.exists()  # refused before any run (and its init-db) was started


def test_tool_root_inside_another_checkout_is_refused(module_root):
    fake = module_root / f"checkout-{uuid.uuid4().hex[:6]}"
    (fake / "backend" / "app").mkdir(parents=True)
    (fake / "backend" / "app" / "config.py").write_text("DB_PATH = None\n", encoding="utf-8")
    try:
        with pytest.raises(DbEntryError) as error:
            DbEntry(fake / "testdb")
        assert error.value.code == "forbidden_target" and "product checkout" in error.value.reason
        assert not (fake / "testdb").exists()
    finally:
        remove_tree_or_raise(fake)


def test_concurrent_isolation_requests_never_share_a_name(entry):
    names = []
    lock = threading.Lock()

    def make(_):
        info = entry.isolate("v1")
        with lock:
            names.append(info.run_id)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(make, range(4)))
    assert len(set(names)) == 4
    for name in names:
        entry.cleanup(name)
