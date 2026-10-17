"""Boundaries of tools/test_db that need neither a database nor any file on disk.

Targets, STOCK_* values, names and metadata are judged from paths alone, so
nothing here may create, open or copy a database.
"""

import configparser
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # tools/ is a namespace package at the project root

from tools.test_db import DbEntry, DbEntryError, _child as child_module, cli as cli_module, paths as paths_module  # noqa: E402
from tools.test_db.entry import CHILD_TEMP_RESERVE, ROOT_PATH_RESERVE, ROOT_PATH_SUFFIXES  # noqa: E402
from tools.test_db.errors import CleanupError, PathTooLongError, QuotaExceededError  # noqa: E402
from tools.test_db.paths import DEFAULT_MAX_TOTAL_BYTES, WINDOWS_PATH_LIMIT, forbidden_reason, path_length  # noqa: E402
from tools.test_db.product import stock_env_for, validate_stock_env  # noqa: E402
from tools.test_db.sample import NAME_MAX, build_metadata, check_name, is_unset  # noqa: E402

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


REAL_COMPLETE = {
    "source_rights": "per SOURCE_REGISTRY policy X",
    "data_dates": {"first": "2026-01-02", "last": "2026-03-31"},
    "acquired_at": "2026-10-01T00:00:00Z",
    "sampling_rule": "60 trading days of 2330",
}
REAL_COMMON = dict(version="v9", kind="real_sample", schema_version="rev", sha256="0" * 64, size_bytes=1, counts={}, fixture=None)

# Spellings of "nothing stated": case, surrounding whitespace, separators, width and common synonyms.
PLACEHOLDER_STRINGS = [
    "", " ", "   ", "\t\r\n", "　", " ", "​",  # empty and blank (ASCII, ideographic, no-break, zero-width)
    "unknown", "Unknown", "UNKNOWN", "  unknown  ", "\tUnknown\n",
    "not-applicable", "Not-Applicable", "not applicable", "Not Applicable", "not_applicable", "NOT APPLICABLE",
    "N/A", "n/a", "N / A", "n.a.", "N-A", "na", "NA", "Ｎ／Ａ", "not available",
    "tbd", "TBD", " Tbd ", "TBA", "todo",
    "none", "None", "NONE", "null", "Null", "NULL", "nil", "undefined", "NaN",
    "-", "--", "?", "？", "...",
    "無", "未知", "不適用", "待補", "待定", "未定",
]
PLACEHOLDER_CONTAINERS = [
    [], {}, (), [None], [""], ["N/A"], [["unknown"]], [[]], [{}],
    {"first": "", "last": ""}, {"first": "2026-01-02", "last": "unknown"}, {"first": None, "last": "2026-03-31"},
    {"first": {"year": []}}, {"a": [{"b": "TBD"}]}, {"a": {"b": {"c": "n/a"}}},
]


@pytest.mark.parametrize("placeholder", [None, *PLACEHOLDER_STRINGS], ids=repr)
def test_real_sample_refuses_every_placeholder_spelling_for_each_required_field(placeholder):
    for key in REAL_COMPLETE:
        with pytest.raises(DbEntryError) as error:
            build_metadata(supplied={**REAL_COMPLETE, key: placeholder}, **REAL_COMMON)
        assert code_of(error) == "metadata_invalid" and key in error.value.reason
    with pytest.raises(DbEntryError) as error:  # a key that is not supplied at all is the same as an unset one
        build_metadata(supplied={k: v for k, v in REAL_COMPLETE.items() if k != "sampling_rule"}, **REAL_COMMON)
    assert code_of(error) == "metadata_invalid" and "sampling_rule" in error.value.reason


@pytest.mark.parametrize("placeholder", PLACEHOLDER_CONTAINERS, ids=repr)
def test_real_sample_refuses_empty_or_partly_unset_containers_at_any_depth(placeholder):
    for key in REAL_COMPLETE:
        with pytest.raises(DbEntryError) as error:
            build_metadata(supplied={**REAL_COMPLETE, key: placeholder}, **REAL_COMMON)
        assert code_of(error) == "metadata_invalid" and key in error.value.reason


def test_real_sample_names_every_unset_field_in_one_refusal():
    with pytest.raises(DbEntryError) as error:
        build_metadata(supplied={"source_rights": "N/A", "data_dates": {}, "acquired_at": "TBD", "sampling_rule": "x"}, **REAL_COMMON)
    for key in ("source_rights", "data_dates", "acquired_at"):
        assert key in error.value.reason
    assert "sampling_rule" not in error.value.reason


@pytest.mark.parametrize(
    "value",
    [
        "Tpex daily close, 7 symbols",
        "None of the rows are adjusted",  # starts with a placeholder word but says something
        "not-applicable: hand-written fixture",  # the manual_fixture wording is a statement, not a whole-value placeholder
        "2026-10-06T23:32:21+00:00",
        "OGL-1.0",
        "未提供官方發布時間，以 receipt 為準",
        ["2026-10-06"],
        {"first": "2026-10-06", "last": "2026-10-06"},
        {"dates": ["2026-10-06", "2026-10-07"], "note": {"calendar": "TWSE"}},
        0,
        False,
    ],
    ids=repr,
)
def test_real_sample_gate_judges_whole_values_only_and_not_numbers_or_meaning(value):
    for key in REAL_COMPLETE:
        metadata = build_metadata(supplied={**REAL_COMPLETE, key: value}, **REAL_COMMON)
        assert metadata[key] == value
        assert not is_unset(value)


def test_publication_time_and_provenance_stay_unknown_when_unstated_and_are_not_gated():
    metadata = build_metadata(supplied=REAL_COMPLETE, **REAL_COMMON)
    assert metadata["publication_time"] == "unknown" and metadata["provenance"] == "unknown"
    supplied = {**REAL_COMPLETE, "publication_time": "unknown", "provenance": "unknown"}
    metadata = build_metadata(supplied=supplied, **REAL_COMMON)  # unknown is a legitimate answer for these two
    assert metadata["publication_time"] == "unknown" and metadata["provenance"] == "unknown"


def test_manual_fixture_defaults_are_not_subject_to_the_real_sample_gate():
    common = dict(version="v1", kind="manual_fixture", schema_version="rev", sha256="0" * 64, size_bytes=1, counts={}, fixture=None)
    defaults = build_metadata(supplied=None, **common)
    assert defaults["acquired_at"] == "not-applicable" and defaults["data_dates"] == "unknown"
    assert is_unset(defaults["acquired_at"]) and is_unset(defaults["data_dates"])  # would fail the gate; manual_fixture never meets it
    for placeholder in ("N/A", "", None, [], {}):
        again = build_metadata(supplied={key: placeholder for key in REAL_COMPLETE}, **common)
        assert again["source_rights"] == defaults["source_rights"] and again["acquired_at"] == "not-applicable"
        assert again["sampling_rule"] == defaults["sampling_rule"]


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


# ---- #79 AC-2: supplied metadata that is not a JSON object -------------------------------

COMMON = dict(version="v1", schema_version="rev", sha256="0" * 64, size_bytes=1, counts={}, fixture=None)
# Falsy values (0, "", [], False) are included on purpose: they must not be read as "no metadata".
NOT_AN_OBJECT = ["text", "", 7, 0, 3.5, True, False, [1], ["a"], [], (1,), {1, 2}]


@pytest.mark.parametrize("kind", ["manual_fixture", "real_sample"])
@pytest.mark.parametrize("value", NOT_AN_OBJECT, ids=repr)
def test_supplied_metadata_that_is_not_an_object_is_refused_whatever_its_truthiness(kind, value):
    with pytest.raises(DbEntryError) as error:
        build_metadata(kind=kind, supplied=value, **COMMON)
    assert code_of(error) == "metadata_invalid" and "JSON object" in error.value.reason
    assert type(value).__name__ in error.value.reason


def test_absent_or_empty_object_metadata_behaves_as_before():
    for supplied in (None, {}):
        metadata = build_metadata(kind="manual_fixture", supplied=supplied, **COMMON)
        assert metadata["kind"] == "manual_fixture" and metadata["source_rights"].startswith("not-applicable")
    with pytest.raises(DbEntryError) as error:  # an empty object still lacks what a real_sample must state
        build_metadata(kind="real_sample", supplied={}, **COMMON)
    assert code_of(error) == "metadata_invalid" and "source_rights" in error.value.reason


# ---- #79 AC-3: a root too deep for Windows MAX_PATH ------------------------------------------
#
# The platform judgement is monkeypatched, so every case runs on any OS. Roots are paths that are never created;
# ``Path.mkdir`` is replaced by a recorder so "nothing was created" is an observation, not an assumption.

MAX_ROOT_LENGTH = WINDOWS_PATH_LIMIT - ROOT_PATH_RESERVE


def root_of_length(length):
    """An absolute path of exactly ``length`` characters, in components short enough for any file system."""

    text = Path.cwd().anchor
    while len(text) < length:
        need = length - len(text)
        text += "r" * (need if need <= 100 else min(100, need - 2))
        if len(text) < length:
            text += os.sep
    assert len(str(Path(text))) == length
    return Path(text)


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(paths_module, "_is_windows", lambda: True)


@pytest.fixture
def made_dirs(monkeypatch):
    calls = []
    monkeypatch.setattr(Path, "mkdir", lambda self, *args, **kwargs: calls.append(self))
    return calls


def test_path_budget_constants_are_pinned():
    assert WINDOWS_PATH_LIMIT == 259  # MAX_PATH 260 counts the terminating NUL
    assert NAME_MAX == 64 and check_name("A" * NAME_MAX, "x") and CHILD_TEMP_RESERVE == 48
    lengths = {name: sum(len(part) + 1 for part in parts) for name, parts in ROOT_PATH_SUFFIXES.items()}
    assert lengths == {
        "run marker": 87,  # \runs\<64>\.testdb-run.json
        "run database journal": 92,  # \runs\<64>\data\stock.db-journal
        "run child temp file": 123,  # \runs\<64>\tmp\<48>
        "sample database journal": 91,  # \samples\<64>\sample.db-journal
        "sample metadata": 87,  # \samples\<64>\metadata.json
        "publish staging": 40,  # \samples\.partial-<8>\metadata.json
        "schema check journal": 43,  # \tmp\scratch-<8>\data\stock.db-journal
        "schema check temp file": 74,  # \tmp\scratch-<8>\tmp\<48>
    }
    assert ROOT_PATH_RESERVE == max(lengths.values()) == 123 and MAX_ROOT_LENGTH == 136


@pytest.mark.parametrize("value", ["100%", "%(here)s", "a%%b", "x%(missing)s", "C:/plain/path", ""], ids=repr)
def test_child_escapes_script_location_so_configparser_reads_it_back_verbatim(value):
    # AC-5: Alembic's set_main_option goes through ConfigParser, which rejects a bare % and expands %(name)s.
    parser = configparser.ConfigParser()
    parser.add_section("alembic")
    parser.set("alembic", "script_location", child_module._escape_config_value(value))
    assert parser.get("alembic", "script_location") == value


def test_an_unescaped_percent_is_what_configparser_rejects_or_expands():
    parser = configparser.ConfigParser({"here": "elsewhere"})
    parser.add_section("alembic")
    with pytest.raises(ValueError):
        parser.set("alembic", "script_location", "100%")
    parser.set("alembic", "script_location", "/checkout/%(here)s/alembic")
    assert parser.get("alembic", "script_location") == "/checkout/elsewhere/alembic"  # silently a different path


def test_the_platform_judgement_is_the_operating_system_name():
    assert paths_module._is_windows() == (os.name == "nt")


def test_a_root_that_just_fits_is_accepted_and_one_character_more_is_refused_before_anything_is_created(windows, made_dirs):
    fits = DbEntry(root_of_length(MAX_ROOT_LENGTH))
    assert made_dirs == [fits.root]  # the root itself, as before; the check ran first
    made_dirs.clear()
    too_long = root_of_length(MAX_ROOT_LENGTH + 1)
    with pytest.raises(PathTooLongError) as error:
        DbEntry(too_long)
    failure = error.value
    assert failure.code == "path_too_long" and failure.path == str(too_long)
    assert failure.details == {
        "root_length": MAX_ROOT_LENGTH + 1, "reserved_length": ROOT_PATH_RESERVE, "limit": WINDOWS_PATH_LIMIT,
        "max_root_length": MAX_ROOT_LENGTH,
    }
    assert str(MAX_ROOT_LENGTH) in failure.reason and str(MAX_ROOT_LENGTH + 1) in failure.reason
    assert made_dirs == []


def test_roots_below_the_boundary_fit_and_everything_above_it_is_refused(windows, made_dirs):
    for length in (MAX_ROOT_LENGTH - 30, MAX_ROOT_LENGTH):
        DbEntry(root_of_length(length))
    for length in (MAX_ROOT_LENGTH + 1, MAX_ROOT_LENGTH + 40, 3 * WINDOWS_PATH_LIMIT):
        with pytest.raises(DbEntryError) as error:
            DbEntry(root_of_length(length))
        assert error.value.code == "path_too_long" and error.value.details["root_length"] == length
    assert len(made_dirs) == 2  # only the two accepted roots


def test_length_is_counted_in_utf16_units_like_max_path(windows, made_dirs):
    astral = chr(0x1F600)
    assert path_length(astral) == 2 and path_length("é") == 1
    plain = str(root_of_length(MAX_ROOT_LENGTH - 1))
    DbEntry(plain + "r")  # MAX_ROOT_LENGTH characters, as many units: fits
    with pytest.raises(DbEntryError) as error:
        DbEntry(plain + astral)  # the same number of characters, one unit more
    assert error.value.code == "path_too_long" and error.value.details["root_length"] == MAX_ROOT_LENGTH + 1


def test_other_platforms_are_not_limited_because_they_are_unverified(monkeypatch, made_dirs):
    monkeypatch.setattr(paths_module, "_is_windows", lambda: False)
    deep = DbEntry(root_of_length(3 * WINDOWS_PATH_LIMIT))
    assert made_dirs == [deep.root]


def test_a_forbidden_root_is_reported_as_forbidden_even_when_it_is_also_too_long(windows, made_dirs):
    inside_checkout = REPO_ROOT / ("x" * 100) / ("y" * 100) / ("z" * 100)
    with pytest.raises(DbEntryError) as error:
        DbEntry(inside_checkout)
    assert error.value.code == "forbidden_target" and made_dirs == []


def test_cli_reports_a_too_long_root_as_one_json_object_and_creates_nothing(windows, made_dirs, capsys):
    too_long = root_of_length(MAX_ROOT_LENGTH + 1)
    assert cli_module.main(["--root", str(too_long), "usage"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and payload["error"]["code"] == "path_too_long" and payload["error"]["path"] == str(too_long)
    assert payload["error"]["details"]["max_root_length"] == MAX_ROOT_LENGTH
    assert made_dirs == []
