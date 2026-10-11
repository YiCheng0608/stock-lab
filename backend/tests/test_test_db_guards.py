"""Boundaries of tools/test_db that need neither a database nor any file on disk.

Targets, STOCK_* values, names and metadata are judged from paths alone, so
nothing here may create, open or copy a database.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # tools/ is a namespace package at the project root

from tools.test_db import DbEntry, DbEntryError  # noqa: E402
from tools.test_db.errors import CleanupError, QuotaExceededError  # noqa: E402
from tools.test_db.paths import DEFAULT_MAX_TOTAL_BYTES, forbidden_reason  # noqa: E402
from tools.test_db.product import stock_env_for, validate_stock_env  # noqa: E402
from tools.test_db.sample import build_metadata, check_name  # noqa: E402

OUTSIDE = Path(Path.cwd().anchor) / "stock-lab-testdb-guard-demo"  # never created
RUN = OUTSIDE / "runs" / "r1"
SAMPLES = OUTSIDE / "samples"


def good_env():
    return stock_env_for(RUN / "data")


def code_of(excinfo):
    return excinfo.value.code


def test_valid_stock_env_is_read_back_resolved():
    readback = validate_stock_env(good_env(), allowed_root=RUN, forbidden=(SAMPLES,))
    assert readback == {name: str(Path(value).resolve()) for name, value in good_env().items()}


@pytest.mark.parametrize("missing", ["STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR"])
def test_each_stock_variable_must_be_set(missing):
    env = good_env()
    del env[missing]
    with pytest.raises(DbEntryError) as error:
        validate_stock_env(env, allowed_root=RUN)
    assert code_of(error) == "stock_env_invalid" and missing in error.value.reason
    env[missing] = ""
    with pytest.raises(DbEntryError) as error:
        validate_stock_env(env, allowed_root=RUN)
    assert code_of(error) == "stock_env_invalid"


@pytest.mark.parametrize(
    "target, expected",
    [
        (REPO_ROOT / "data" / "stock.db", "product checkout"),
        (REPO_ROOT / ".local" / "data" / "stock.db", "product checkout"),
        (Path(Path.cwd().anchor) / "elsewhere" / ".local" / "data" / "stock.db", ".local/data"),
        (Path("relative") / "stock.db", "absolute"),
        (RUN / "data" / ".." / ".." / "stock.db", "'..'"),
    ],
)
def test_daily_and_repo_locations_are_refused_for_the_database(target, expected):
    env = good_env()
    env["STOCK_DB_PATH"] = str(target)
    with pytest.raises(DbEntryError) as error:
        validate_stock_env(env, allowed_root=RUN)
    assert code_of(error) == "forbidden_target"
    assert expected in error.value.reason and "STOCK_DB_PATH" in error.value.reason


def test_inherited_stock_locations_are_protected():
    daily = Path(Path.cwd().anchor) / "daily-research" / "stock.db"
    env = {name: str(daily.parent / name) for name in ("STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR")}
    env["STOCK_DB_PATH"] = str(daily)
    with pytest.raises(DbEntryError) as error:
        validate_stock_env(env, allowed_root=daily.parent, protected=(daily,))
    assert code_of(error) == "forbidden_target" and "inherited STOCK_*" in error.value.reason


def test_sample_library_is_never_a_writable_target():
    env = {
        "STOCK_DATA_DIR": str(SAMPLES / "v1"),
        "STOCK_DB_PATH": str(SAMPLES / "v1" / "sample.db"),
        "STOCK_RAW_DIR": str(SAMPLES / "v1" / "raw"),
    }
    with pytest.raises(DbEntryError) as error:
        validate_stock_env(env, allowed_root=OUTSIDE, forbidden=(SAMPLES,))
    assert code_of(error) == "forbidden_target" and "read-only sample library" in error.value.reason
    assert error.value.path.endswith("v1")


def test_every_stock_variable_must_stay_inside_the_isolated_directory():
    env = good_env()
    env["STOCK_RAW_DIR"] = str(OUTSIDE / "runs" / "r2" / "data" / "raw")  # another run's raw directory
    with pytest.raises(DbEntryError) as error:
        validate_stock_env(env, allowed_root=RUN)
    assert code_of(error) == "forbidden_target" and "outside the isolated directory" in error.value.reason


@pytest.mark.parametrize(
    "root",
    [REPO_ROOT / "x", REPO_ROOT / ".local" / "data", Path("relative-root"), OUTSIDE / ".." / "x"],
)
def test_tool_root_inside_the_checkout_or_unsafe_is_refused_before_anything_is_created(root):
    before = (REPO_ROOT / "x").exists(), (REPO_ROOT / ".local").exists(), Path("relative-root").exists()
    with pytest.raises(DbEntryError) as error:
        DbEntry(root)
    assert code_of(error) == "forbidden_target" and error.value.path
    assert ((REPO_ROOT / "x").exists(), (REPO_ROOT / ".local").exists(), Path("relative-root").exists()) == before


def test_forbidden_reason_allows_a_dedicated_directory_outside_the_repo():
    assert forbidden_reason(OUTSIDE) is None


@pytest.mark.parametrize("bad", ["", "..", "../x", "a/b", "a\\b", ".hidden", "x" * 65, None, "v 1"])
def test_names_cannot_traverse_or_hide(bad):
    with pytest.raises(DbEntryError) as error:
        check_name(bad, "sample version")
    assert code_of(error) == "invalid_argument"


@pytest.mark.parametrize("good", ["v1", "2026-10-11.a", "sample_1", "A" * 64])
def test_ordinary_version_names_are_accepted(good):
    assert check_name(good, "sample version") == good


def test_real_sample_must_state_rights_dates_acquisition_and_sampling_rule():
    complete = {
        "source_rights": "per SOURCE_REGISTRY policy X",
        "data_dates": {"first": "2026-01-02", "last": "2026-03-31"},
        "acquired_at": "2026-10-01T00:00:00Z",
        "sampling_rule": "60 trading days of 2330",
    }
    common = dict(version="v9", kind="real_sample", schema_version="rev", sha256="0" * 64, size_bytes=1, counts={}, fixture=None)
    for key in complete:
        for placeholder in (None, "", "unknown", "not-applicable"):
            with pytest.raises(DbEntryError) as error:
                build_metadata(supplied={**complete, key: placeholder}, **common)
            assert code_of(error) == "metadata_invalid" and key in error.value.reason
    metadata = build_metadata(supplied=complete, **common)
    assert metadata["kind"] == "real_sample" and metadata["source_rights"] == complete["source_rights"]
    # Publication time and point-in-time status are never inferred.
    assert metadata["publication_time"] == "unknown"


def test_manual_fixture_metadata_is_marked_as_not_market_data():
    metadata = build_metadata(
        version="v1", kind="manual_fixture", schema_version="rev", sha256="0" * 64, size_bytes=1, counts={"t": 1},
        supplied={"source_rights": "ignored: a hand-written fixture cannot claim rights"},
        fixture={"data_dates": {"first": "2001-01-02", "last": "2001-01-04"}, "provenance": {"name": "f.json", "sha256": "1" * 64}},
    )
    assert metadata["source_rights"].startswith("not-applicable")
    assert metadata["acquired_at"] == "not-applicable"
    assert "not market data" in metadata["sampling_rule"]
    assert metadata["provenance"] == {"fixture": {"name": "f.json", "sha256": "1" * 64}}


def test_unknown_kind_is_rejected():
    with pytest.raises(DbEntryError) as error:
        build_metadata(version="v1", kind="scraped", schema_version="r", sha256="0" * 64, size_bytes=1, counts={}, supplied=None, fixture=None)
    assert code_of(error) == "invalid_argument"


def test_failures_name_code_path_size_and_reason():
    quota = QuotaExceededError("too big", path=RUN, size_bytes=51_000_000, limit_bytes=50_000_000)
    as_dict = quota.to_dict()
    assert as_dict["code"] == "quota_exceeded" and as_dict["size_bytes"] == 51_000_000
    assert as_dict["path"] == str(RUN) and as_dict["details"]["limit_bytes"] == 50_000_000
    assert str(RUN) in str(quota) and "51000000" in str(quota)

    cleanup = CleanupError(RUN, [{"path": str(RUN / "data" / "stock.db"), "size_bytes": 425984, "reason": "PermissionError: busy"}], 425984)
    assert cleanup.path.endswith("stock.db") and cleanup.size_bytes == 425984
    assert cleanup.details["remaining_bytes"] == 425984 and "busy" in cleanup.reason


def test_default_limit_is_the_smaller_decimal_reading_of_50_mb():
    assert DEFAULT_MAX_TOTAL_BYTES == 50_000_000
