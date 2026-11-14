"""The codebase-memory master index in close_task.sh and dispatch.sh (Issue #704).

close_task.sh fast-forwards the management checkout after a merge, rebuilds its index with
the same-engine CLI and verifies the files the merge changed; dispatch.sh verifies the files
of the newest merges before it creates anything, rebuilding once when stale. The judgement
is index_verdict in coordinator_json.py; the rules (decisions 6875002208, 6875024190 and
6875031116 on the Issue) are tested one each below, then the two scripts end to end with
the fake CLI of test_coordinator_scripts (FAKE_CBM_PY), which never reaches the real
engine or its cache.
"""

# The fixtures h, close and dispatch come from test_coordinator_scripts; pytest hands them
# over by parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
from test_coordinator_scripts import (  # noqa: F401  (h, close, dispatch are fixtures)
    BASH,
    OPS,
    Harness,
    _dispatch,
    _json_line,
    close,
    dispatch,
    h,
)

_spec = importlib.util.spec_from_file_location(
    "coordinator_json", OPS / "coordinator_json.py"
)
cj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cj)

PROJECT = "C-Users-YiCheng-Desktop-taiwan-stock-research"
INDEXED = "2026-11-14T08:51:43Z"
INDEXED_EPOCH = 1794646303  # INDEXED in epoch seconds


# --- the rules, one each (index_verdict) ---------------------------------------------


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name in ("a.py", "b.py", "notes.txt", "gen/g.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")
        os.utime(path, (INDEXED_EPOCH - 60, INDEXED_EPOCH - 60))
    return tmp_path


def _verdict(
    root: Path, path: str, freshness: str, status="no_recorded_issue", tracked=("a.py",)
):
    entry = {"requested_path": path, "status": status, "freshness": freshness}
    types = {cj._suffix_key(p) for p in tracked}
    return cj.index_verdict(path, entry, set(tracked), types, INDEXED_EPOCH, str(root))


def test_rule_1_a_deleted_file_is_left_out(root: Path) -> None:
    assert _verdict(root, "gone.py", "missing") == ("skip", "deleted")


def test_rule_2_an_excluded_path_is_left_out(root: Path) -> None:
    assert _verdict(root, "gen/g.py", "not_tracked", status="excluded") == (
        "skip",
        "excluded",
    )


def test_rule_3_missing_for_a_file_that_is_there_is_stale(root: Path) -> None:
    assert _verdict(root, "a.py", "missing") == ("stale", "missing")


def test_rule_4_a_recorded_file_older_than_the_index_is_fresh(root: Path) -> None:
    # metadata_changed decides nothing: engine 0.10.8 answers it for unchanged files.
    assert _verdict(root, "a.py", "metadata_changed") == ("ok", "tracked")


def test_rule_4_a_changed_file_still_answered_metadata_changed_is_stale(
    root: Path,
) -> None:
    # Decision 6875002208 point 2: the content changed, the engine still answers
    # metadata_changed, the mtime is later than indexed_at.
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    os.utime(root / "a.py", (INDEXED_EPOCH + 5, INDEXED_EPOCH + 5))
    assert _verdict(root, "a.py", "metadata_changed") == ("stale", "mtime")


def test_rule_5_an_unrecorded_file_of_a_recorded_type_is_stale(root: Path) -> None:
    assert _verdict(root, "b.py", "not_tracked") == ("stale", "not_tracked")


def test_rule_6_an_unrecorded_file_of_a_type_never_recorded_is_left_out(
    root: Path,
) -> None:
    os.utime(root / "notes.txt", (INDEXED_EPOCH + 5, INDEXED_EPOCH + 5))
    assert _verdict(root, "notes.txt", "not_tracked") == ("skip", "unsupported")


def test_a_path_the_answer_leaves_out_is_an_error_not_fresh(root: Path) -> None:
    with pytest.raises(ValueError, match="沒有回 a.py"):
        cj.index_verdict("a.py", None, {"a.py"}, {".py"}, INDEXED_EPOCH, str(root))


def test_suffix_key_takes_the_name_of_a_file_without_an_extension() -> None:
    assert cj._suffix_key("backend/Dockerfile") == "Dockerfile"
    assert cj._suffix_key(".gitignore") == ".gitignore"
    assert cj._suffix_key("docs/A.MD") == ".md"


# --- reading the CLI's answers --------------------------------------------------------


def _envelope(obj, error: bool = False) -> str:
    text = json.dumps(obj)
    return json.dumps(
        {
            "content": [{"type": "text", "text": text}],
            "structuredContent": obj,
            "isError": error,
        }
    )


def _table(*paths: str) -> str:
    rows = "".join(f"  {p}\n" for p in paths)
    return f"rows: {len(paths)}  (cols: f.file_path)\n{rows}total: {len(paths)}\n"


def _coverage(*entries: tuple[str, str], indexed_at=INDEXED, project=PROJECT) -> str:
    answer = {
        "project": project,
        "paths": [
            {"requested_path": p, "status": "no_recorded_issue", "freshness": f}
            for p, f in entries
        ],
    }
    if indexed_at is not None:
        answer["indexed_at"] = indexed_at
    return json.dumps(answer)


def test_cbm_result_drops_the_daemon_lines() -> None:
    raw = "level=info msg=mem.init\nhint: x\n" + _envelope({"status": "indexed"}) + "\n"
    assert cj.cbm_result(raw) == {"status": "indexed"}


@pytest.mark.parametrize(
    "raw, message",
    [
        ("level=info msg=mem.init\nhint: x\n", "沒有 JSON"),
        ("level=info\n{not json\n", "沒有 JSON"),
        (_envelope({"error": "project not found"}, error=True), "project not found"),
    ],
)
def test_cbm_result_refuses_what_is_not_an_answer(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        cj.cbm_result(raw)


@pytest.mark.parametrize(
    "text",
    [
        "rows: 0  (cols: f.file_path)\ntotal: 0\n",
        "rows: 3  (cols: f.file_path)\n  a.py\ntotal: 3\n",
        "an error page",
    ],
)
def test_cbm_table_refuses_an_empty_or_inconsistent_file_list(text: str) -> None:
    with pytest.raises(ValueError):
        cj.cbm_table(text)


def _parts(root: Path, coverage: str) -> tuple[list[str], str, str]:
    return ["a.py", json.dumps(_table("a.py")), coverage], str(root), PROJECT


def test_verdict_without_indexed_at_fails(root: Path) -> None:
    # Decision 6875002208 point 1: no indexed_at is never "not stale".
    with pytest.raises(ValueError, match="沒有 indexed_at"):
        cj.cbm_verdict(
            *_parts(root, _coverage(("a.py", "metadata_changed"), indexed_at=None))
        )


def test_verdict_with_an_unreadable_indexed_at_fails(root: Path) -> None:
    with pytest.raises(ValueError, match="解析不出時間"):
        cj.cbm_verdict(
            *_parts(
                root, _coverage(("a.py", "metadata_changed"), indexed_at="yesterday")
            )
        )


def test_verdict_of_another_project_fails(root: Path) -> None:
    with pytest.raises(ValueError, match="project"):
        cj.cbm_verdict(
            *_parts(root, _coverage(("a.py", "metadata_changed"), project="other"))
        )


def test_verdict_reports_each_path(root: Path) -> None:
    lines, stale = cj.cbm_verdict(
        *_parts(root, _coverage(("a.py", "metadata_changed")))
    )
    assert (lines, stale) == (["ok\ttracked\tmetadata_changed\ta.py"], False)


# --- close_task.sh (AC-1) --------------------------------------------------------------

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required")


def _cbm_calls(h: Harness) -> list[dict]:
    path = h.fake / "cbm_calls.log"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def _tools(h: Harness) -> list[str]:
    return [c["tool"] for c in _cbm_calls(h)]


def _board_set(h: Harness) -> bool:
    return any("updateProjectV2" in c for c in h.calls("gh"))


def _repo_file(h: Harness, name: str, mtime: int | None = None) -> Path:
    path = h.repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_close_task_updates_the_checkout_rebuilds_and_verifies_after_the_cleanup(
    close: Harness,
) -> None:
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    steps = line["steps"]
    index_steps = [s for s in steps if s.startswith(("checkout_", "index_"))]
    assert index_steps == [
        "checkout_updated:" + "a" * 40,
        "index_rebuilt",
        "index_fresh:1",
    ]
    # After every cleanup step, before the board.
    assert steps.index("worktree_removed") < steps.index(index_steps[0])
    assert any("merge --ff-only --quiet origin/master" in c for c in close.calls("git"))
    assert _tools(close) == [
        "index_status",
        "index_repository",
        "query_graph",
        "check_index_coverage",
    ]
    calls = _cbm_calls(close)
    assert calls[1]["args"] == {
        "repo_path": close.repo.as_posix(),
        "name": PROJECT,
    }
    assert calls[3]["args"] == {
        "project": PROJECT,
        "paths": ["tools/ops/close_task.sh"],
    }
    assert line["board"] == "完成"


def _assert_index_failure(h: Harness, result, message: str) -> dict:
    assert result.returncode == 3, result.stdout + result.stderr
    line = _json_line(result)
    assert line["error"].startswith(message), line["error"]
    # The cleanup ran and is listed; the board stays as it was.
    assert "worktree_removed" in line["steps"]
    assert not _board_set(h)
    return line


def test_close_task_fails_when_the_rebuild_fails(close: Harness) -> None:
    close.write("cbm_index_fails", "")
    line = _assert_index_failure(close, close.close_task(close.extra), "索引步驟：")
    assert "disk full" in line["error"]
    assert "index_rebuilt" not in line["steps"]


def test_close_task_fails_when_the_index_is_still_stale_after_the_rebuild(
    close: Harness,
) -> None:
    _repo_file(close, "backend/app/new_module.py")
    close.write("git_diff.txt", "backend/app/new_module.py\n")
    close.write("cbm_not_tracked.txt", "backend/app/new_module.py\n")
    close.write("cbm_not_tracked_stays", "")
    line = _assert_index_failure(
        close, close.close_task(close.extra), "索引步驟：索引過期"
    )
    assert "backend/app/new_module.py（not_tracked）" in line["error"]
    assert "index_rebuilt" in line["steps"]
    # not_tracked is not what a forced rebuild clears.
    assert "delete_project" not in _tools(close)


def test_close_task_fails_without_the_cli(close: Harness) -> None:
    result = close.close_task(
        close.extra, STOCK_CBM_CLI=(close.root / "no-cli.cmd").as_posix()
    )
    line = _assert_index_failure(close, result, "索引步驟：找不到 codebase-memory CLI")
    assert "STOCK_CBM_CLI" in line["error"]


def test_close_task_fails_when_the_cli_times_out(close: Harness) -> None:
    close.write("cbm_index_repository.sleep", "10")
    result = close.close_task(close.extra, STOCK_CBM_TIMEOUT="1")
    _assert_index_failure(
        close, result, "索引步驟：codebase-memory CLI index_repository 逾時"
    )


def test_close_task_fails_when_the_cli_prints_no_json(close: Harness) -> None:
    close.write("cbm_check_index_coverage.raw", "level=info msg=x\nhint: y\nsegfault\n")
    line = _assert_index_failure(close, close.close_task(close.extra), "索引步驟：")
    assert "沒有 JSON" in line["error"]


def test_close_task_rebuilds_nothing_from_a_checkout_that_is_not_the_projects(
    close: Harness,
) -> None:
    close.write("cbm_root.txt", "C:/somewhere/else")
    line = _assert_index_failure(close, close.close_task(close.extra), "索引步驟：")
    assert "不是這個 checkout" in line["error"]
    assert "index_repository" not in _tools(close)


def test_close_task_does_not_touch_a_checkout_off_master(close: Harness) -> None:
    close.write("git_head_branch.txt", "task/9-x\n")
    _assert_index_failure(close, close.close_task(close.extra), "管理 checkout 更新：")
    assert not any(c.split()[2:3] == ["merge"] for c in close.calls("git"))
    assert not _tools(close)


def test_close_task_leaves_out_a_file_type_the_engine_never_records(
    close: Harness,
) -> None:
    # Decision 6875024190: a merge that only changed a .txt (requirements) passes, though
    # the engine answers not_tracked and keeps its indexed_at.
    _repo_file(close, "backend/requirements.txt")
    close.write("git_diff.txt", "backend/requirements.txt\n")
    close.write("cbm_unsupported.txt", ".txt\n")
    close.write("cbm_indexed_at.txt", "2000-01-01T00:00:00Z")
    close.write("cbm_index_no_bump", "")
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "index_fresh:1" in _json_line(result)["steps"]
    assert "delete_project" not in _tools(close)


def test_close_task_forces_a_rebuild_when_only_mtimes_changed(close: Harness) -> None:
    # Decision 6875031116: a file the engine records was touched, its content the same;
    # the engine keeps indexed_at on a rebuild, so one forced rebuild clears it.
    close.write("cbm_indexed_at.txt", "2000-01-01T00:00:00Z")
    close.write("cbm_index_no_bump", "")
    result = close.close_task(close.extra)
    assert result.returncode == 0, result.stdout + result.stderr
    steps = _json_line(result)["steps"]
    assert [s for s in steps if s.startswith("index_")] == [
        "index_rebuilt",
        "index_forced",
        "index_fresh:1",
    ]
    assert _tools(close) == [
        "index_status",
        "index_repository",
        "query_graph",
        "check_index_coverage",
        "index_status",
        "delete_project",
        "index_repository",
        "query_graph",
        "check_index_coverage",
    ]


def test_close_task_dry_run_leaves_the_checkout_and_the_index_alone(
    close: Harness,
) -> None:
    result = close.run("close_task.sh", "282", "--no-board")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "index_skipped:no_board" in _json_line(result)["steps"]
    assert not _tools(close)
    assert not any(c.split()[2:3] == ["merge"] for c in close.calls("git"))


# --- dispatch.sh (AC-2) ----------------------------------------------------------------


def _created(h: Harness) -> bool:
    return any(c.startswith("worktree create") for c in h.calls("orca"))


def test_dispatch_checks_the_index_and_goes_on_when_it_is_fresh(
    dispatch: Harness,
) -> None:
    result = _dispatch(dispatch)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["index"] == "index_fresh:1" and line["sent"] is True
    assert _tools(dispatch) == ["query_graph", "check_index_coverage"]
    assert any(
        c.split()[2:4] == ["rev-list", "--first-parent"] and "--merges" in c
        for c in dispatch.calls("git")
    )


def test_dispatch_rebuilds_a_stale_index_and_goes_on(dispatch: Harness) -> None:
    _repo_file(dispatch, "backend/app/new_module.py")
    dispatch.write("git_diff.txt", "backend/app/new_module.py\n")
    dispatch.write("cbm_not_tracked.txt", "backend/app/new_module.py\n")
    result = _dispatch(dispatch)
    assert result.returncode == 0, result.stdout + result.stderr
    line = _json_line(result)
    assert line["index"] == "index_stale,index_rebuilt,index_fresh:1"
    assert line["sent"] is True and _created(dispatch)
    tools = _tools(dispatch)
    assert tools.index("index_repository") < len(tools) - 1


def test_dispatch_creates_nothing_when_the_index_is_still_stale(
    dispatch: Harness,
) -> None:
    _repo_file(dispatch, "backend/app/new_module.py")
    dispatch.write("git_diff.txt", "backend/app/new_module.py\n")
    dispatch.write("cbm_not_tracked.txt", "backend/app/new_module.py\n")
    dispatch.write("cbm_not_tracked_stays", "")
    result = _dispatch(dispatch)
    assert result.returncode == 1, result.stdout + result.stderr
    line = _json_line(result)
    assert line["index"] == "failed" and line["sent"] is False
    assert line["error"].startswith("索引驗證：索引過期")
    assert "index_repository" in _tools(dispatch)
    assert not _created(dispatch)
    assert not [c for c in dispatch.calls("orca") if c.startswith("terminal")]


def test_dispatch_creates_nothing_without_the_cli(dispatch: Harness) -> None:
    result = dispatch.run(
        "dispatch.sh",
        "282",
        "dryrun",
        "--task-file",
        dispatch.task.as_posix(),
        STOCK_CBM_CLI=(dispatch.root / "no-cli.cmd").as_posix(),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert _json_line(result)["error"].startswith(
        "索引驗證：找不到 codebase-memory CLI"
    )
    assert not _created(dispatch)
