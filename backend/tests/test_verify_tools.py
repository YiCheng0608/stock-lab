"""tools/ops commands used by the verify-stock-lab skill (Issue #227).

copy_db.py runs on temporary SQLite files; screenshot.cjs runs against a local
HTTP server and is skipped without node or a Chromium browser;
push_pr_assets.sh pushes to a temporary bare repository and is skipped without
bash. Nothing touches the real data directory or GitHub.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

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
    assert out["instrument"] == {
        "exchange": "TWSE",
        "symbol": "2330",
        "latest_trading_date": "2026-10-21",
        "source": "twse",
    }
    assert _digest(db) == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["stock.db"]
    assert _run([sys.executable, "-B", str(DB_FACTS)]).returncode == 2


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


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><div class="skeleton">loading</div>
<details><summary>more</summary><p>hidden detail</p></details>
<div style="width:600px">wide row</div>
<button id="tab" onclick="fetch('/slow').then(() => document.body.insertAdjacentHTML('beforeend', '<p>tab opened</p>'))">tab</button>
<script>
fetch('/slow').then((r) => r.text()).then((text) => {
  document.querySelector('.skeleton').remove()
  document.body.insertAdjacentHTML('beforeend', '<p id="done">' + text + '</p>')
})
console.error('boom')
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
        assert "loading" not in text
        assert line["consoleErrors"] == ["boom"]
        assert line["httpErrors"] == []
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
