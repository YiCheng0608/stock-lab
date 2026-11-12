"""tools/ops commands used by the verify-stock-lab skill (Issue #227).

copy_db.py runs on temporary SQLite files; screenshot.cjs runs against a local
HTTP server and is skipped without node or a Chromium browser;
push_pr_assets.sh pushes to a temporary bare repository and is skipped without
bash. Nothing touches the real data directory or GitHub.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base
from app.domain import (
    CANDIDATE_SCORE_READ_VERSIONS,
    CANDIDATE_SCORE_VERSION,
    PLAN_OPEN_STATUSES,
)

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "tools" / "ops"
COPY_DB = OPS / "copy_db.py"
DB_FACTS = ROOT / ".claude" / "skills" / "verify-stock-lab" / "db_facts.py"
SCREENSHOT = OPS / "screenshot.cjs"
PUSH = OPS / "push_pr_assets.sh"


def _bash() -> str | None:
    if os.name == "nt":
        git_bash = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Git"
            / "bin"
            / "bash.exe"
        )
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


BASH = _bash()
NODE = shutil.which("node")


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", timeout=180, **kwargs
    )


# ---- copy_db.py ----


def _copy(src: Path, dest: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            "-B",
            str(COPY_DB),
            "--src",
            str(src),
            "--dest",
            str(dest),
            *extra,
        ]
    )


def _wal_source(path: Path) -> sqlite3.Connection:
    """A WAL database whose last commit is still only in the -wal file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE market_bars (trading_date TEXT)")
    conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
    conn.execute("INSERT INTO alembic_version VALUES ('0016_group_score_archive')")
    conn.execute("INSERT INTO market_bars VALUES ('2026-10-20')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("INSERT INTO market_bars VALUES ('2026-10-21')")
    conn.commit()
    return conn


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _db_facts():
    spec = importlib.util.spec_from_file_location("db_facts", DB_FACTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_copy_db_help() -> None:
    result = _run([sys.executable, "-B", str(COPY_DB), "--help"])
    assert result.returncode == 0
    assert "--src" in result.stdout and "--dest" in result.stdout


def test_copy_db_copies_wal_frames_without_writing_the_source(tmp_path: Path) -> None:
    src = tmp_path / "prod" / "stock.db"
    wal = Path(str(src) + "-wal")
    # The writer stays open during the copy, like a scheduled job would.
    writer = _wal_source(src)
    try:
        before = (_digest(src), _digest(wal))
        result = _copy(src, tmp_path / "verify")
        after = (_digest(src), _digest(wal))
    finally:
        writer.close()
    assert result.returncode == 0, result.stderr
    assert after == before
    out = json.loads(result.stdout)
    copy = tmp_path / "verify" / "stock.db"
    assert out["copy"] == copy.resolve().as_posix()
    assert out["source"] == src.resolve().as_posix()
    assert out["source_latest_trading_date"] == "2026-10-21"
    assert out["alembic_version"] == "0016_group_score_archive"
    assert not (tmp_path / "verify" / "stock.db.partial").exists()
    uri = copy.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert conn.execute("SELECT count(*) FROM market_bars").fetchone() == (2,)


def test_copy_db_leaves_a_writerless_wal_source_untouched(tmp_path: Path) -> None:
    """No connection is open on the source; only mode=ro keeps the close from
    checkpointing the -wal into the main file and deleting it."""
    live = tmp_path / "live" / "stock.db"
    writer = _wal_source(live)
    src = tmp_path / "prod" / "stock.db"
    src.parent.mkdir()
    try:
        # Snapshot the pair while the writer holds them, so the copies keep the -wal.
        shutil.copyfile(live, src)
        shutil.copyfile(Path(str(live) + "-wal"), Path(str(src) + "-wal"))
    finally:
        writer.close()
    wal = Path(str(src) + "-wal")
    before = (_digest(src), _digest(wal))
    result = _copy(src, tmp_path / "verify")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_latest_trading_date"] == "2026-10-21"
    assert wal.exists()
    assert (_digest(src), _digest(wal)) == before


@pytest.fixture
def read_only_dir(tmp_path: Path):
    """Make a directory and its files read-only like the `:ro` volume mount (#486): SQLite
    can neither create a -shm or -wal next to the database nor write the ones there.
    Skipped where 0o555 does not stop that (Windows, root); CI's backend job runs it as an
    ordinary user on Linux."""
    made: list[Path] = []

    def make(directory: Path) -> Path:
        for path in directory.iterdir():
            path.chmod(0o444)
        directory.chmod(0o555)
        made.append(directory)
        try:
            (directory / "probe").touch()
        except PermissionError:
            return directory
        (directory / "probe").unlink()
        pytest.skip("a 0o555 directory is still writable here (Windows or root)")

    yield make
    for directory in made:
        directory.chmod(0o755)
        for path in directory.iterdir():
            path.chmod(0o644)


def _snapshot(live: Path, src: Path, *sides: str) -> None:
    """Copy the database and the given side files while the writer holds them."""
    src.parent.mkdir(parents=True, exist_ok=True)
    for side in ("", *sides):
        shutil.copyfile(f"{live}{side}", f"{src}{side}")


def _source_state(src: Path) -> dict[str, str]:
    return {p.name: _digest(p) for p in sorted(src.parent.iterdir())}


def test_copy_db_reads_a_wal_db_with_no_side_files_on_a_read_only_mount(
    tmp_path: Path, read_only_dir
) -> None:
    """The v1.2.3 pre-deploy backup (#486): nothing has the DB open, so the volume holds
    only stock.db, and mode=ro cannot create the -shm it needs. The main file is the
    whole database, so it is read immutable."""
    src = tmp_path / "prod" / "stock.db"
    conn = _wal_source(src)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    assert sorted(p.name for p in src.parent.iterdir()) == ["stock.db"]
    with sqlite3.connect(src) as check:
        assert check.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    check.close()
    for side in ("-wal", "-shm"):
        Path(f"{src}{side}").unlink(missing_ok=True)
    read_only_dir(src.parent)
    before = _source_state(src)
    result = _copy(src, tmp_path / "verify")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["source_open"] == "immutable"
    assert out["quick_check"] == "ok"
    assert out["source_latest_trading_date"] == "2026-10-21"
    assert out["alembic_version"] == "0016_group_score_archive"
    assert _source_state(src) == before
    copy = tmp_path / "verify" / "stock.db"
    with closing(sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True)) as check:
        assert check.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert check.execute("SELECT count(*) FROM market_bars").fetchone() == (2,)


def test_copy_db_reads_the_wal_on_a_read_only_mount(
    tmp_path: Path, read_only_dir
) -> None:
    """A connection is open, so the -wal and -shm are there: mode=ro reads them, the last
    commit (only in the -wal) included, and immutable is not used."""
    live = tmp_path / "live" / "stock.db"
    writer = _wal_source(live)
    src = tmp_path / "prod" / "stock.db"
    try:
        _snapshot(live, src, "-wal", "-shm")
    finally:
        writer.close()
    read_only_dir(src.parent)
    before = _source_state(src)
    result = _copy(src, tmp_path / "verify")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["source_open"] == "ro"
    assert out["source_latest_trading_date"] == "2026-10-21"
    assert _source_state(src) == before


def _hot_journal_source(live: Path, src: Path) -> None:
    """A rollback-journal DB whose last transaction spilled pages into the main file and
    was cut off: the -journal is hot and the main file holds pages it has yet to undo."""
    live.parent.mkdir(parents=True)
    writer = sqlite3.connect(live, isolation_level=None)
    try:
        writer.execute("PRAGMA journal_mode=DELETE")
        writer.execute("PRAGMA cache_size=1")
        writer.execute("CREATE TABLE market_bars (trading_date TEXT)")
        writer.execute("INSERT INTO market_bars VALUES ('2026-10-20')")
        writer.execute("BEGIN")
        for _ in range(2000):
            writer.execute("INSERT INTO market_bars VALUES (?)", ("2026-10-21" * 50,))
        _snapshot(live, src, "-journal")
        writer.execute("ROLLBACK")
    finally:
        writer.close()
    assert Path(f"{src}-journal").stat().st_size > 0


@pytest.mark.parametrize("case", ["wal-without-shm", "hot-journal"])
def test_copy_db_refuses_side_files_it_cannot_read_on_a_read_only_mount(
    tmp_path: Path, read_only_dir, case: str
) -> None:
    """mode=ro cannot open these, and immutable would skip the -wal or read pages the hot
    -journal has yet to roll back, so nothing is copied (PR #477 review)."""
    live = tmp_path / "live" / "stock.db"
    src = tmp_path / "prod" / "stock.db"
    if case == "hot-journal":
        _hot_journal_source(live, src)
    else:
        writer = _wal_source(live)
        try:
            _snapshot(live, src, "-wal")
        finally:
            writer.close()
    read_only_dir(src.parent)
    before = _source_state(src)
    result = _copy(src, tmp_path / "verify")
    assert result.returncode == 1
    side = "-journal" if case == "hot-journal" else "-wal"
    assert f"{side} is next to it" in result.stderr
    assert "immutable" in result.stderr
    assert _source_state(src) == before
    assert not (tmp_path / "verify" / "stock.db").exists()
    assert not (tmp_path / "verify" / "stock.db.partial").exists()


def _copy_db_module():
    spec = importlib.util.spec_from_file_location("copy_db_under_test", COPY_DB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("writer", ["still-open", "closed"])
def test_copy_db_drops_an_immutable_copy_when_a_writer_opened_the_source(
    tmp_path: Path, monkeypatch, writer: str
) -> None:
    """immutable=1 takes no lock: a writer that opened the source during the copy may have
    changed the main file under it. Still open, its -wal is there; closed, the -wal is gone
    but the checkpoint moved the main file's mtime. Either way the copy is removed."""
    copy_db = _copy_db_module()
    src = tmp_path / "prod" / "stock.db"
    conn = _wal_source(src)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    for side in ("-wal", "-shm"):
        Path(f"{src}{side}").unlink(missing_ok=True)
    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if str(database).endswith("?mode=ro"):
            # What the read-only mount does to mode=ro without the -shm.
            raise sqlite3.OperationalError("unable to open database file")
        if str(database).endswith("&immutable=1"):
            # The api starts meanwhile.
            if writer == "still-open":
                Path(f"{src}-wal").write_bytes(b"")
            else:
                status = src.stat()
                os.utime(src, ns=(status.st_atime_ns, status.st_mtime_ns + 10**9))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(copy_db.sqlite3, "connect", connect)
    with pytest.raises(copy_db.CopyError, match="changed during the copy"):
        copy_db.copy_db(src, tmp_path / "verify")
    assert sorted(p.name for p in (tmp_path / "verify").iterdir()) == []


def test_copy_db_refuses_a_copy_that_fails_quick_check(tmp_path: Path) -> None:
    """The copy is the pre-migration backup (PR #505 review): a damaged page, which the
    backup API copies as it is, is caught before the rename and nothing is left."""
    src = tmp_path / "prod" / "stock.db"
    src.parent.mkdir()
    with closing(sqlite3.connect(src)) as conn:
        conn.execute("CREATE TABLE market_bars (trading_date TEXT)")
        conn.execute("INSERT INTO market_bars VALUES ('2026-10-21')")
        conn.execute("CREATE TABLE other (x TEXT)")
        conn.executemany(
            "INSERT INTO other VALUES (?)", [(f"v{i:05d}" * 20,) for i in range(2000)]
        )
        conn.commit()
        size = conn.execute("PRAGMA page_size").fetchone()[0]
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
    # Overwrite the cells of the last page (a leaf of `other`); its header stays.
    with open(src, "r+b") as file:
        file.seek((pages - 1) * size + 200)
        file.write(b"\xff" * (size - 400))
    result = _copy(src, tmp_path / "verify")
    assert result.returncode == 1
    assert "quick_check of the copy" in result.stderr
    assert "Traceback" not in result.stderr
    assert sorted(p.name for p in (tmp_path / "verify").iterdir()) == []


class _FailingBackup:
    """A source connection whose backup writes into the copy and then fails."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str):
        return self.conn.execute(sql)

    def backup(self, target: sqlite3.Connection, pages: int) -> None:
        target.execute("CREATE TABLE half_copied (x)")
        target.commit()
        raise sqlite3.OperationalError("disk I/O error")

    def close(self) -> None:
        self.conn.close()


def test_copy_db_removes_the_partial_when_the_backup_fails(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    copy_db = _copy_db_module()
    src = tmp_path / "prod" / "stock.db"
    _wal_source(src).close()

    def failing_source(path: Path):
        conn, immutable = copy_db.open_read_only(path)
        return _FailingBackup(conn), immutable

    monkeypatch.setattr(copy_db, "_open_source", failing_source)
    dest = tmp_path / "verify"
    assert copy_db.main(["--src", str(src), "--dest", str(dest)]) == 1
    assert capsys.readouterr().err == "copy_db: disk I/O error\n"
    assert sorted(p.name for p in dest.iterdir()) == []


def test_copy_db_reports_a_source_that_vanished_midway_without_a_traceback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The source is deleted or replaced while it is read immutable: the second stamp
    finds no file. That is a CopyError for main, and the .partial is removed."""
    copy_db = _copy_db_module()
    src = tmp_path / "prod" / "stock.db"
    conn = _wal_source(src)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    real_connect = sqlite3.connect
    real_stamp = copy_db._stamp
    stamps = []

    def connect(database, *args, **kwargs):
        if str(database).endswith("?mode=ro"):
            raise sqlite3.OperationalError("unable to open database file")
        return real_connect(database, *args, **kwargs)

    def stamp(path: Path):
        stamps.append(path)
        if len(stamps) == 2:
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_stamp(path)

    monkeypatch.setattr(copy_db.sqlite3, "connect", connect)
    monkeypatch.setattr(copy_db, "_stamp", stamp)
    dest = tmp_path / "verify"
    assert copy_db.main(["--src", str(src), "--dest", str(dest)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("copy_db: ") and "disappeared or was replaced" in err
    assert len(stamps) == 2
    assert sorted(p.name for p in dest.iterdir()) == []


def test_copy_db_and_db_revision_open_the_source_the_same_way() -> None:
    """One rule for opening the volume read-only (#486). copy_db.py is mounted alone into
    whichever image runs and db_revision.py is piped on stdin, so neither imports the
    other; the two copies of open_read_only must stay identical instead."""

    def function(path: Path) -> str:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "open_read_only"
        ]
        assert len(nodes) == 1, path
        return ast.dump(nodes[0])

    assert function(COPY_DB) == function(OPS / "db_revision.py")


def test_copy_db_refuses_a_destination_inside_the_source_directory(
    tmp_path: Path,
) -> None:
    src = tmp_path / "prod" / "stock.db"
    _wal_source(src).close()
    for dest in (tmp_path / "prod", tmp_path / "prod" / "verify"):
        result = _copy(src, dest)
        assert result.returncode == 1
        assert "inside the source directory" in result.stderr
    assert sorted(p.name for p in (tmp_path / "prod").iterdir()) == ["stock.db"]


def test_copy_db_replaces_an_older_copy_and_its_stale_side_files(
    tmp_path: Path,
) -> None:
    src = tmp_path / "prod" / "stock.db"
    _wal_source(src).close()
    dest = tmp_path / "verify"
    dest.mkdir()
    (dest / "stock.db").write_bytes(b"old")
    (dest / "stock.db-wal").write_bytes(b"stale")
    (dest / "stock.db-shm").write_bytes(b"stale")
    # Without --force an existing copy is refused and nothing there changes.
    result = _copy(src, dest)
    assert result.returncode == 1
    assert "pass --force" in result.stderr
    assert (dest / "stock.db").read_bytes() == b"old"
    assert (dest / "stock.db-wal").read_bytes() == b"stale"
    result = _copy(src, dest, "--force")
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in dest.iterdir()) == ["stock.db"]


def test_copy_db_reports_missing_tables_as_null(tmp_path: Path) -> None:
    src = tmp_path / "prod" / "stock.db"
    src.parent.mkdir()
    with sqlite3.connect(src) as conn:
        conn.execute("CREATE TABLE other (x)")
    result = _copy(src, tmp_path / "verify")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["source_latest_trading_date"] is None
    assert out["alembic_version"] is None


def test_copy_db_rejects_a_missing_source(tmp_path: Path) -> None:
    result = _copy(tmp_path / "nope.db", tmp_path / "verify")
    assert result.returncode == 1
    assert "not a file" in result.stderr
    assert not (tmp_path / "verify").exists()


def test_db_facts_reads_the_copy_without_writing(tmp_path: Path) -> None:
    db = tmp_path / "verify" / "stock.db"
    db.parent.mkdir()
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE instruments (id INTEGER PRIMARY KEY, exchange TEXT, symbol TEXT);
            CREATE TABLE market_bars (
                instrument_id INTEGER, trading_date TEXT, source TEXT);
            CREATE TABLE portfolio_positions (id INTEGER);
            INSERT INTO instruments VALUES (1, 'TWSE', '2330');
            INSERT INTO market_bars VALUES (1, '2026-10-20', 'twse'), (1, '2026-10-21', 'twse');
            """
        )
    conn.close()
    before = _digest(db)
    result = _run([sys.executable, "-B", str(DB_FACTS), str(db), "TWSE", "2330"])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["market_latest_trading_date"] == "2026-10-21"
    assert out["portfolio_positions"] == 0
    assert (
        out["news_items"] is None and out["candidate_run_latest_trading_date"] is None
    )
    assert out["market_summary_latest"] is None
    assert out["instrument"] == {
        "exchange": "TWSE",
        "symbol": "2330",
        "latest_trading_date": "2026-10-21",
        "source": "twse",
    }
    assert _digest(db) == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["stock.db"]
    assert _run([sys.executable, "-B", str(DB_FACTS)]).returncode == 2


def test_db_facts_market_summary_latest_is_each_exchanges_newest_row(
    tmp_path: Path,
) -> None:
    # T11 compares dashboard.market_overview with these values (#275).
    db = tmp_path / "stock.db"
    module = _db_facts()
    columns = ("exchange",) + module.MARKET_SUMMARY_FIELDS
    with sqlite3.connect(db) as conn:
        conn.execute(f"CREATE TABLE market_summaries ({', '.join(columns)})")
        for exchange, day, close in (
            ("TWSE", "2026-10-21", 46887.77),
            ("TWSE", "2026-10-22", 46041.43),
            ("TPEx", "2026-10-21", 395.42),
        ):
            values = dict.fromkeys(columns)
            values.update(exchange=exchange, trading_date=day, index_close=close)
            conn.execute(
                f"INSERT INTO market_summaries VALUES ({', '.join('?' * len(columns))})",
                [values[name] for name in columns],
            )
    conn.close()
    result = _run([sys.executable, "-B", str(DB_FACTS), str(db)])
    assert result.returncode == 0, result.stderr
    latest = json.loads(result.stdout)["market_summary_latest"]
    assert sorted(latest) == ["TPEx", "TWSE"]
    assert (latest["TWSE"]["trading_date"], latest["TWSE"]["index_close"]) == (
        "2026-10-22",
        46041.43,
    )
    assert latest["TPEx"]["trading_date"] == "2026-10-21"
    assert set(latest["TWSE"]) == set(module.MARKET_SUMMARY_FIELDS)


def test_db_facts_candidates_use_the_current_score_version(tmp_path: Path) -> None:
    # The API only serves CANDIDATE_SCORE_VERSION runs (candidate_view._run_for);
    # a newer run of another version must not become the fact T7 compares (#237).
    db = tmp_path / "stock.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE candidate_runs (id INTEGER PRIMARY KEY, trading_date TEXT,"
            " score_version TEXT, candidate_count INTEGER)"
        )
        conn.executemany(
            "INSERT INTO candidate_runs VALUES (?, ?, ?, ?)",
            [
                (1, "2026-10-20", CANDIDATE_SCORE_VERSION, 3),
                (2, "2026-10-21", CANDIDATE_SCORE_VERSION, 5),
                (3, "2026-10-22", "candidate_score_v0", 9),
            ],
        )
    conn.close()
    result = _run([sys.executable, "-B", str(DB_FACTS), str(db)])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["candidate_run_latest_trading_date"] == "2026-10-21"
    assert out["candidate_count_latest"] == 5

    # db_facts.py runs on the stdlib-only tool Python and keeps its own copy.
    assert _db_facts().CANDIDATE_SCORE_VERSION == CANDIDATE_SCORE_VERSION
    assert _db_facts().CANDIDATE_SCORE_READ_VERSIONS == CANDIDATE_SCORE_READ_VERSIONS
    assert set(_db_facts().PLAN_OPEN_STATUSES) == PLAN_OPEN_STATUSES


@pytest.mark.parametrize("previous", CANDIDATE_SCORE_READ_VERSIONS[1:])
def test_db_facts_falls_back_to_the_previous_version_run(
    tmp_path: Path, previous: str
) -> None:
    # #392, #413: a date without a current-version run shows its run of the
    # next read version, as the API does (app.candidate_runs); one date never
    # mixes two versions.
    current = CANDIDATE_SCORE_READ_VERSIONS[0]
    db = tmp_path / "stock.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE candidate_runs (id INTEGER PRIMARY KEY, trading_date TEXT,"
            " score_version TEXT, candidate_count INTEGER)"
        )
        conn.executemany(
            "INSERT INTO candidate_runs VALUES (?, ?, ?, ?)",
            [
                (1, "2026-10-29", previous, 7),
                (2, "2026-10-30", previous, 8),
                (3, "2026-10-30", current, 4),
            ],
        )
    conn.close()
    out = json.loads(_run([sys.executable, "-B", str(DB_FACTS), str(db)]).stdout)
    assert out["candidate_run_latest_trading_date"] == "2026-10-30"
    assert out["candidate_count_latest"] == 4
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM candidate_runs WHERE id = 3")
    conn.close()
    out = json.loads(_run([sys.executable, "-B", str(DB_FACTS), str(db)]).stdout)
    assert out["candidate_count_latest"] == 8


# The 2026-10-27 #306 copy: four candidate_score_v1 runs, none of the current version.
V1_RUNS = [
    (n, f"2026-10-{day}", "candidate_score_v1", count)
    for n, (day, count) in enumerate(
        (("16", 18), ("20", 20), ("21", 19), ("22", 20)), start=1
    )
]


@pytest.mark.parametrize("runs", [V1_RUNS, []], ids=["v1-only", "no-run"])
def test_db_facts_without_a_current_version_run_gives_null(
    tmp_path: Path, runs: list[tuple]
) -> None:
    # #307: facts() raised TypeError on fetchone()[0] and the #306 run stopped at T2.
    db = tmp_path / "stock.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE candidate_runs (id INTEGER PRIMARY KEY, trading_date TEXT,
                score_version TEXT, candidate_count INTEGER);
            CREATE TABLE market_bars (trading_date TEXT);
            CREATE TABLE portfolio_positions (id INTEGER);
            CREATE TABLE alembic_version (version_num TEXT);
            INSERT INTO market_bars VALUES ('2026-10-22');
            INSERT INTO alembic_version VALUES ('0020_trading_calendar');
            """
        )
        conn.executemany("INSERT INTO candidate_runs VALUES (?, ?, ?, ?)", runs)
    conn.close()
    assert _db_facts().facts(db) == {
        "market_latest_trading_date": "2026-10-22",
        "group_scores_latest_trading_date": None,
        "candidate_run_latest_trading_date": None,
        "candidate_count_latest": None,
        "news_items": None,
        "news_latest_published_at": None,
        "news_llm_done": None,
        "tracking_plans_open": None,
        "tracking_plans_closed": None,
        "portfolio_positions": 0,
        "alembic_version": "0020_trading_calendar",
        "market_summary_latest": None,
    }


def test_db_facts_every_query_on_an_empty_table(tmp_path: Path) -> None:
    # #307 AC-2: every table of the real schema exists and has no row.
    db = tmp_path / "stock.db"
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32))")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    conn.close()
    module = _db_facts()
    assert {table for table, _ in module.QUERIES.values()} <= tables
    out = module.facts(db, ("TWSE", "2330"))
    # A count of an empty table is the fact 0; every other query has no value.
    expected = {
        "market_latest_trading_date": None,
        "group_scores_latest_trading_date": None,
        "candidate_run_latest_trading_date": None,
        "candidate_count_latest": None,
        "news_items": 0,
        "news_latest_published_at": None,
        "news_llm_done": 0,
        "tracking_plans_open": 0,
        "tracking_plans_closed": 0,
        "portfolio_positions": 0,
        "alembic_version": None,
    }
    assert {key: out[key] for key in module.QUERIES} == expected
    assert out["market_summary_latest"] == {}
    assert out["instrument"] == {
        "exchange": "TWSE",
        "symbol": "2330",
        "latest_trading_date": None,
        "source": None,
    }


# ---- screenshot.cjs ----

needs_node = pytest.mark.skipif(NODE is None, reason="node is required")


def _node_eval(script: str) -> object:
    code = f"const m = require({json.dumps(str(SCREENSHOT))});\n{script}"
    result = _run([NODE, "-e", code])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@needs_node
def test_screenshot_help_and_usage_errors(tmp_path: Path) -> None:
    result = _run([NODE, str(SCREENSHOT), "--help"])
    assert result.returncode == 0
    assert "--url" in result.stdout and "scrollWidth" in result.stdout
    for args in (
        [],
        ["--url", "http://x/"],
        ["--url", "ftp://x/", "--out", str(tmp_path)],
        ["--url", "http://x/", "--out", str(tmp_path), "--widths", "100"],
        ["--url", "http://x/", "--out", str(tmp_path), "--bogus", "1"],
    ):
        result = _run([NODE, str(SCREENSHOT), *args])
        assert result.returncode == 2, args
        assert "usage:" in result.stderr


@needs_node
def test_screenshot_option_helpers() -> None:
    out = _node_eval(
        """
const names = ['http://h:1/', 'http://h:1/themes?board=theme', 'http://h:1/stocks/TWSE/2330']
  .map(m.defaultName)
const parsed = m.parseArgs(['--url', 'http://h:1/news', '--out', 'o', '--widths', '800, 375',
  '--click', '#a', '--click', '#b'])
console.log(JSON.stringify({
  names,
  parsed,
  phone: m.viewport(390),
  desktop: m.viewport(1280),
  linux: m.browserArgs('p', 'linux').includes('--no-sandbox'),
  win: m.browserArgs('p', 'win32').includes('--no-sandbox'),
  env: m.findBrowser({ SCREENSHOT_BROWSER: 'x' }, 'linux', () => false),
  none: m.findBrowser({}, 'linux', () => false),
}))
"""
    )
    assert out["names"] == ["today", "themes-board-theme", "stocks-TWSE-2330"]
    assert out["parsed"]["name"] == "news"
    assert out["parsed"]["widths"] == [800, 375]
    assert out["parsed"]["timeoutMs"] == 60000
    assert out["parsed"]["clicks"] == ["#a", "#b"]
    assert out["phone"]["mobile"] is True and out["desktop"]["mobile"] is False
    assert out["linux"] is True and out["win"] is False
    assert out["env"] == "x" and out["none"] is None


@needs_node
def test_screenshot_candidate_rows_probe_returns_null_when_it_throws() -> None:
    # Issue 609: a probe that throws must not fail the whole capture; T17 judges null.
    out = _node_eval(
        """
const run = (document) => { globalThis.document = document; return eval(m.CANDIDATE_ROWS_PROBE) }
console.log(JSON.stringify({
  thrown: run({ querySelectorAll() { throw new Error('probe broke') } }),
  empty: run({ querySelectorAll() { return [] } }),
}))
"""
    )
    assert out == {"thrown": None, "empty": []}


@needs_node
def test_screenshot_reports_a_browser_that_exits_before_listening(
    tmp_path: Path,
) -> None:
    # node rejects --headless=new and exits at once, like a browser that cannot start.
    started = time.monotonic()
    result = _run(
        [
            NODE,
            str(SCREENSHOT),
            "--url",
            "http://127.0.0.1:9/",
            "--out",
            str(tmp_path / "shots"),
            "--browser",
            NODE,
        ]
    )
    assert result.returncode == 1
    assert "browser exited" in result.stderr and "headless" in result.stderr
    assert time.monotonic() - started < 30
    assert list((tmp_path / "shots").iterdir()) == []


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><div class="skeleton">loading</div>
<details><summary>more</summary><p>hidden detail</p></details>
<div style="width:600px">wide row</div>
<ol style="overflow:hidden;width:300px;margin:0;padding:0;list-style:none">
<li class="candidate-row" data-candidate-rank="1" style="display:flex;width:300px">
<dl class="candidate-row-nums" style="display:flex;width:200px;margin:0"><div><dt>收盤</dt><dd style="margin:0">10</dd></div><div><dt>總分</dt><dd style="margin:0">70</dd></div></dl>
<button class="candidate-ai-toggle">AI</button></li>
<li class="candidate-row" data-candidate-rank="2" style="position:relative;width:300px">
<dl class="candidate-row-nums" style="display:flex;width:200px;margin:0"><div style="flex:none;width:150px"><dt>收盤</dt><dd style="margin:0">10</dd></div><div style="flex:none;width:200px"><dt>總分（0–100）</dt><dd style="margin:0">70</dd></div></dl>
<button class="candidate-ai-toggle" style="position:absolute;left:160px;top:0;width:120px;height:60px">AI</button></li>
<li class="candidate-row" data-candidate-rank="3" hidden><dl class="candidate-row-nums"></dl></li>
</ol>
<style>:root{--color-up:rgb(239, 68, 68);--color-down:rgb(34, 197, 94)}
.strength-chip{position:relative}.strength-chip::before{content:"";position:absolute;inset:0;background:var(--color-down);opacity:.3}</style>
<details><summary>bars</summary><span class="score-bar" aria-label="技術 75（0–100）" data-score="75"><span class="score-bar-track" style="display:inline-block;position:relative;width:200px;height:6px"><span class="score-bar-fill" style="position:absolute;left:0;top:0;bottom:0;width:75%"></span></span></span>
<span class="score-bar score-bar-empty" aria-label="族群 無資料" data-score="none"><span class="score-bar-track" style="display:inline-block;width:200px;height:6px"></span></span></details>
<b class="strength-chip strength-down strength-l2" aria-label="1 日相對加權指數 -1.20%" data-strength="down-2">-1.20%</b>
<button id="tab" onclick="fetch('/slow').then(() => document.body.insertAdjacentHTML('beforeend', '<p>tab opened</p>'))">tab</button>
<script>
fetch('/slow').then((r) => r.text()).then((text) => {
  document.querySelector('.skeleton').remove()
  document.body.insertAdjacentHTML('beforeend', '<p id="done">' + text + '</p>')
})
console.error('boom')
// A client-side redirect, as the app's /actions -> /watch (#493): finalUrl reports where the page landed.
history.replaceState(null, '', '/landed?from=old#plan-7')
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/slow":
            time.sleep(1.0)
            body, status = b"data 2026-10-21", 200
        elif self.path == "/":
            body, status = PAGE.encode(), 200
        else:
            body, status = b"missing", 404
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def _browser() -> str | None:
    if not NODE:
        return None
    result = _run(
        [
            NODE,
            "-e",
            f"console.log(require({json.dumps(str(SCREENSHOT))}).findBrowser() ?? '')",
        ]
    )
    return result.stdout.strip() or None


@needs_node
@pytest.mark.skipif(_browser() is None, reason="Edge or Chrome is required")
def test_screenshot_waits_for_data_and_reports_overflow(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = tmp_path / "shots"
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        result = _run(
            [
                NODE,
                str(SCREENSHOT),
                "--url",
                url,
                "--out",
                str(out),
                "--wait-for",
                "#done",
                "--click",
                "#tab",
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert [line["width"] for line in lines] == [1280, 390]
    for line in lines:
        assert line["ready"] is True
        assert Path(line["png"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        text = Path(line["txt"]).read_text(encoding="utf-8")
        assert "data 2026-10-21" in text and "hidden detail" in text
        assert "tab opened" in text
        assert line["missingClicks"] == []
        assert line["url"] == url and line["finalUrl"] == url + "landed?from=old#plan-7"
        assert "loading" not in text
        assert line["consoleErrors"] == ["boom"]
        assert line["httpErrors"] == [] and line["httpErrorCount"] == 0
        # Issue 608: the shown today-list rows; #2's total runs under the button and past the row.
        total = ["dt 總分（0–100）", "dd 70"]
        assert line["candidateRows"] == [
            {
                "rank": 1,
                "numsScrollWidth": 200,
                "numsClientWidth": 200,
                "covered": [],
                "clipped": [],
            },
            {
                "rank": 2,
                "numsScrollWidth": 350,
                "numsClientWidth": 200,
                "covered": total,
                "clipped": total,
            },
        ]
        # Issue 654: the bars inside the opened <details> and the block, with the resolved tokens.
        assert line["graphics"] == {
            "tokens": {"up": "rgb(239, 68, 68)", "down": "rgb(34, 197, 94)"},
            "items": [
                {
                    "kind": "bar",
                    "label": "技術 75（0–100）",
                    "score": "75",
                    "fill": 0.75,
                    "hasFill": True,
                    "trackWidth": 200,
                },
                {
                    "kind": "bar",
                    "label": "族群 無資料",
                    "score": "none",
                    "fill": None,
                    "hasFill": False,
                    "trackWidth": 200,
                },
                {
                    "kind": "chip",
                    "label": "1 日相對加權指數 -1.20%",
                    "strength": "down-2",
                    "text": "-1.20%",
                    "background": "rgb(34, 197, 94)",
                    "opacity": 0.3,
                },
            ],
        }
    assert [line["overflow"] for line in lines] == [False, True]
    assert lines[1]["scrollWidth"] > lines[1]["clientWidth"] == 390
    assert sorted(p.name for p in out.iterdir()) == [
        "today-1280.png",
        "today-1280.txt",
        "today-390.png",
        "today-390.txt",
    ]


# ---- push_pr_assets.sh ----

needs_bash = pytest.mark.skipif(BASH is None, reason="bash is required")
WEB = "https://github.com/owner/repo"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
    }.items():
        monkeypatch.setenv(key, value)
    bare = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(tmp_path, "init", "-q", str(work))
    (work / "README").write_text("x\n")
    # Same eol rule as this repository; evidence must still keep its own bytes.
    (work / ".gitattributes").write_text("* text=auto eol=lf\n")
    _git(work, "add", "README", ".gitattributes")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "remote", "add", "origin", bare.as_posix())
    return work


def _push(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run([BASH, PUSH.as_posix(), *args], cwd=cwd)


def _evidence(root: Path, name: str, files: dict[str, bytes]) -> Path:
    folder = root / name
    for rel, data in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    return folder


@needs_bash
def test_push_pr_assets_help_and_usage_errors(repo: Path) -> None:
    assert _push(repo, "--help").returncode == 0
    empty = repo.parent / "empty"
    empty.mkdir()
    for args in (
        ["--issue", "x1", "--dir", "."],
        ["--issue", "1"],
        ["--issue", "1", "--dir", "nope"],
        ["--issue", "1", "--dir", empty.as_posix(), "--web", WEB],
        ["--issue", "1", "--dir", ".", "--prefix", "../x", "--web", WEB],
        ["--issue", "1", "--dir", ".", "--bogus"],
    ):
        result = _push(repo, *args)
        assert result.returncode == 2, (args, result.stderr)
    assert _git(repo.parent / "remote.git", "branch", "--list") == ""


@needs_bash
def test_push_pr_assets_orphan_then_child_commit(repo: Path) -> None:
    bare = repo.parent / "remote.git"
    first = _evidence(
        repo.parent,
        "run1",
        {"today-390.png": b"png", "api/health.json": b"{}\r\n", ".hidden": b"x"},
    )
    result = _push(repo, "--issue", "227", "--dir", first.as_posix(), "--web", WEB)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[1] == f"{WEB}/tree/pr-assets/227/run1"
    assert lines[2:] == [
        f"[api/health.json]({WEB}/blob/pr-assets/227/run1/api/health.json)",
        f"![today-390.png]({WEB}/blob/pr-assets/227/run1/today-390.png?raw=true)",
    ]
    head = _git(bare, "rev-parse", "pr-assets/227")
    assert _git(bare, "rev-list", "--parents", "-n", "1", head) == head
    assert _git(bare, "ls-tree", "-r", "--name-only", head).splitlines() == [
        "run1/api/health.json",
        "run1/today-390.png",
    ]
    raw = subprocess.run(
        ["git", "cat-file", "blob", f"{head}:run1/api/health.json"],
        cwd=bare,
        check=True,
        capture_output=True,
    ).stdout
    assert raw == b"{}\r\n"

    second = _evidence(repo.parent, "run2", {"today-390.png": b"png2"})
    result = _push(
        repo, "--issue", "227", "--dir", second.as_posix(), "--prefix", "after/fix"
    )
    assert result.returncode != 0
    assert "not on github.com" in result.stderr
    result = _push(
        repo,
        "--issue",
        "227",
        "--dir",
        second.as_posix(),
        "--prefix",
        "after/fix",
        "--web",
        WEB,
    )
    assert result.returncode == 0, result.stderr
    child = _git(bare, "rev-parse", "pr-assets/227")
    assert _git(bare, "rev-parse", f"{child}^") == head
    assert _git(bare, "ls-tree", "-r", "--name-only", child).splitlines() == [
        "after/fix/today-390.png",
        "run1/api/health.json",
        "run1/today-390.png",
    ]
    assert _git(repo, "status", "--porcelain") == ""


@needs_bash
def test_push_pr_assets_dry_run_pushes_nothing(repo: Path) -> None:
    folder = _evidence(repo.parent, "run1", {"a.txt": b"a"})
    result = _push(
        repo, "--issue", "5", "--dir", folder.as_posix(), "--web", WEB, "--dry-run"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("dry run:")
    assert _git(repo.parent / "remote.git", "branch", "--list") == ""
