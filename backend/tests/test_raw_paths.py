"""Reading a stored capture by its ``payload_path`` after the Docker cutover (app.raw_paths, #342).

The cutover copies the Windows data directory's ``raw/`` into the volume and leaves the
database unchanged (decision 1 of #342), so every reader maps an old Windows path that does
not exist to the same relative path under ``STOCK_RAW_DIR``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

import worker.pipeline as pipeline
import worker.sources as sources
from app import config, raw_paths
from app.models import RawPayload
from app.raw_paths import payload_file
from test_instrument_lifecycle import _dormancy_market, pipeline_env  # noqa: F401
from worker import instrument_repair

ROOT = Path(__file__).resolve().parents[2]
LEGACY = r"C:\Users\YiCheng\stock-lab-data\raw"


def _legacy(path: Path, *, slash: str = "\\", prefix: str = LEGACY) -> str:
    """PATH, a file under the test's raw directory, written as the old Windows path."""

    relative = path.relative_to(config.RAW_DIR).parts
    return prefix.replace("\\", slash) + slash + slash.join(relative)


def _file(relative: str, content: bytes = b"{}") -> Path:
    path = Path(config.RAW_DIR, *relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_a_path_that_exists_is_read_as_it_is(tmp_path):
    here = tmp_path / "x.json"
    here.write_text("{}", encoding="utf-8")
    assert payload_file(str(here)) == here
    assert payload_file(here) == here


@pytest.mark.parametrize(
    "spelling",
    [
        {"slash": "\\"},
        {"slash": "/"},
        {"slash": "\\", "prefix": LEGACY.lower()},
        {"slash": "/", "prefix": LEGACY.upper()},
    ],
    ids=["backslash", "forward-slash", "lower-case", "upper-case"],
)
def test_an_old_windows_raw_path_is_read_under_stock_raw_dir(spelling):
    target = _file("tpex/2026/10/16/abc.json")
    stored = _legacy(target, **spelling)
    if sys.platform == "win32" and Path(stored).exists():
        pytest.skip("this machine has the old data directory itself")
    assert payload_file(stored) == target


def test_stock_stored_raw_dir_comes_before_stock_raw_dir(tmp_path, monkeypatch):
    stored = tmp_path / "real-raw"
    monkeypatch.setenv(raw_paths.STORED_RAW_DIR_ENV, str(stored))
    assert payload_file(LEGACY + r"\twse\a.json") == stored / "twse" / "a.json"


@pytest.mark.parametrize(
    "value",
    [
        "/elsewhere/raw/twse/a.json",
        LEGACY + r"x\twse\a.json",
        LEGACY + r"\..\stock.db",
        LEGACY + r"\twse\.\a.json",
        LEGACY + "\\",
        r"D:\Users\YiCheng\stock-lab-data\raw\twse\a.json",
    ],
)
def test_other_missing_paths_are_left_as_they_are(value):
    assert payload_file(value) == Path(value)


def test_an_empty_path_stays_one_no_reader_can_open():
    assert payload_file(None) == Path("")
    assert payload_file("") == Path("")


# Every reader of a stored capture's file goes through payload_file: the code under
# backend/app, backend/worker and tools/ never opens payload_path itself.
DIRECT = re.compile(r"(?:Path|open)\(\s*[\w.]*payload_path")


def _readers() -> list[Path]:
    roots = [ROOT / "backend" / "app", ROOT / "backend" / "worker", ROOT / "tools"]
    return sorted(p for root in roots for p in root.rglob("*.py"))


def test_no_reader_opens_payload_path_directly():
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}"
        for path in _readers()
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if DIRECT.search(line)
    ]
    assert found == []


def test_the_scan_catches_a_direct_read():
    for line in (
        "payload = json.loads(Path(raw.payload_path).read_bytes())",
        'content = Path(capture.payload_path or "").read_bytes()',
        "with open(raw.payload_path, 'rb') as f:",
    ):
        assert DIRECT.search(line), line
    assert not DIRECT.search("payload_file(raw.payload_path).read_bytes()")
    assert not DIRECT.search("payload_path=str(payload.payload_path),")


def _move_to_legacy_paths(db, monkeypatch) -> list[RawPayload]:
    # pipeline_env captures into its own raw directory; that is STOCK_RAW_DIR here.
    monkeypatch.setattr(config, "RAW_DIR", sources.RAW_DIR)
    rows = db.query(RawPayload).all()
    for row in rows:
        row.payload_path = _legacy(Path(row.payload_path))
    db.flush()
    return rows


def test_dormancy_is_judged_from_quote_tables_stored_under_the_old_path(
    pipeline_env,  # noqa: F811
    monkeypatch,
):
    """review H2 (b): before #342 every table under an old path was unreadable, so 60
    sessions of dormancy were `unverifiable` for about three months."""

    with pipeline_env() as db:
        sessions, ids, records, evidence = _dormancy_market(db)
        rows = _move_to_legacy_paths(db, monkeypatch)
        assert rows and all(not Path(row.payload_path).exists() for row in rows)
        plan = pipeline.plan_instrument_status(db, records, evidence)
        tpex = plan["exchanges"]["TPEx"]
        assert tpex["dormancy"]["status"] == "checked"
        assert tpex["dormant_symbols"] == ["4804"]
        assert tpex["unreadable_quote_tables"] == 0


def test_an_unreadable_quote_table_is_counted_in_the_summary(
    pipeline_env,  # noqa: F811
):
    with pipeline_env() as db:
        sessions, ids, records, evidence = _dormancy_market(db)
        gone = db.query(RawPayload).filter(
            RawPayload.data_as_of == sessions[10].isoformat()
        ).one()
        Path(gone.payload_path).unlink()
        plan = pipeline.plan_instrument_status(db, records, evidence)
        tpex = plan["exchanges"]["TPEx"]
        assert plan["changes"] == []
        assert tpex["dormancy"] == {
            "status": "unverifiable",
            "reason": "unreadable quote table",
        }
        assert tpex["unreadable_quote_tables"] == 1
        assert tpex["unreadable_raw_payload_ids"] == [gone.id]


def test_the_collector_reads_back_a_capture_stored_under_the_old_path():
    """What data-check reads (tools/ops/data_check.py goes through instrument_repair._load)."""

    import hashlib

    content = b'{"stat": "ok"}'
    target = _file("twse/2026/10/30/x.json", content)
    raw = RawPayload(
        id=7,
        source="twse",
        endpoint="x",
        payload_path=_legacy(target),
        sha256=hashlib.sha256(content).hexdigest(),
        data_as_of="2026-10-30",
    )
    assert instrument_repair._load(raw) == {"stat": "ok"}


def test_data_check_maps_old_paths_to_the_real_raw_dir_not_its_scratch(tmp_path):
    """data_check points STOCK_RAW_DIR at its scratch directory (nothing it fetches may land in
    the watchdog's data directory); the captures it reads are still the real ones."""

    real = tmp_path / "data" / "raw"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    code = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]);"
        "import data_check; data_check._prepare(Path(sys.argv[2]));"
        "from app import config, raw_paths;"
        "print(config.RAW_DIR); print(raw_paths.payload_file(sys.argv[3]))"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("STOCK_") and k != "PYTHONPATH"
    }
    env.update(STOCK_DATA_DIR=str(tmp_path / "data"), STOCK_RAW_DIR=str(real))
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(ROOT / "tools" / "ops"),
            str(scratch),
            LEGACY + r"\twse\2026\a.json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert Path(out[0]) == scratch / "raw"
    assert Path(out[1]) == real / "twse" / "2026" / "a.json"


def test_stored_raw_dir_follows_the_config_defaults():
    from test_data_check import data_check

    stored_raw_dir = data_check.stored_raw_dir
    assert stored_raw_dir({"STOCK_RAW_DIR": "/r"}) == "/r"
    assert Path(stored_raw_dir({"STOCK_DATA_DIR": "/d"})) == Path("/d") / "raw"
    assert Path(stored_raw_dir({})) == ROOT / "data" / "raw"


def test_windows_paths_keep_their_parts():
    assert raw_paths.legacy_relative(LEGACY + r"\twse\2026\a.json").parts == (
        "twse",
        "2026",
        "a.json",
    )
    assert PureWindowsPath(LEGACY).name == "raw"
