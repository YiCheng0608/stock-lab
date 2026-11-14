"""tools/ops/take_over.sh with fake gh, orca and wake listener (Issue #534 AC-3).

On the harness of test_coordinator_scripts.py: the scripts run from a sandbox copy, gh and
orca are recording fakes on PATH, HOME and STOCK_DATA_DIR are under tmp_path. The real
#1, Orca terminals and the data directory are never reached. gh here is a fake of its own
that keeps #1's body in <fake>/issue1.json, so the edit and its read-back can be checked
byte for byte; the sandbox's wake_listener_start.sh is replaced by a fake that records
its calls.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess

import pytest

from test_coordinator_scripts import OPS, Harness, _ok

COMMENT_URL = "https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-900"
OLD_ROW = (
    "- terminal `term_old`（Desktop 管理 checkout `C:/x`），session `sess-old`；"
    "2026-11-06T00:10Z 接手（[1](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-1)）。"
)
# #1's body as the web editor leaves it: CRLF, a section after, a last line without an
# ending, and characters str.splitlines would split at (\x0c, \u2028) inside lines.
BODY = (
    "# 治理：現行決策索引\r\n"
    "\r\n"
    "本文只列**仍然有效**的決策\u2028與現任統籌。\r\n"
    "\r\n"
    "## 現任統籌\r\n"
    f"{OLD_ROW}\r\n"
    "\r\n"
    "## 現行決策（2026-10-17）\r\n"
    "- **備份只做手動**\x0c（[6635665869](https://x)）。\r\n"
    "- 尾端空白   \r\n"
    "最後一行沒有換行"
)

FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/gh_calls.log"
case "$*" in
  "api repos/YiCheng0608/stock-lab/issues/1/comments --method POST --input -")
    [ -f "$d/fail_comment" ] && exit 1
    cat >"$d/posted.json"
    echo '{"id": 900, "html_url": "https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-900"}' ;;
  "api repos/YiCheng0608/stock-lab/issues/1 --method PATCH --input "*)
    [ -f "$d/fail_patch" ] && exit 1
    cp "${*: -1}" "$d/patched.json"
    [ -f "$d/patch_ignored" ] || cp "${*: -1}" "$d/issue1.json"
    echo '{}' ;;
  "api repos/YiCheng0608/stock-lab/issues/1")
    [ -f "$d/fail_get" ] && exit 1
    cat "$d/issue1.json" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""

# A listener answers while <fake>/listener_up exists: --status exits 0 then, else 1; a
# start creates it (exit 0) unless <fake>/listener_start_fails exists (exit 1, none
# started) or <fake>/listener_start_dud exists (exit 0, none started).
FAKE_LISTENER = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "${1:-start}" >>"$d/listener_calls.log"
if [ "${1:-}" = --status ]; then [ -f "$d/listener_up" ]; exit; fi
[ -f "$d/listener_start_fails" ] && exit 1
[ -f "$d/listener_start_dud" ] || touch "$d/listener_up"
exit 0
"""
# Closing the old terminal ends the listener it started (docs/ops/MONITOR.md): the hook of
# orca terminal close, for the tests where one ran before the take-over.
CLOSE_ENDS_LISTENER = 'rm -f "$FAKE_DIR/listener_up"\n'


@pytest.fixture
def to(tmp_path) -> Harness:
    h = Harness(tmp_path)
    for path, body in (
        (h.bin / "gh", FAKE_GH),
        (h.ops / "wake_listener_start.sh", FAKE_LISTENER),
    ):
        path.write_text(body, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    (h.fake / "issue1.json").write_bytes(
        json.dumps({"number": 1, "title": "治理", "body": BODY}).encode()
    )
    h.answer("orca_terminal_wait", _ok({"satisfied": True}))
    h.answer("orca_terminal_close", _ok({"closed": True}))
    # The old coordinator's heartbeat, 5 minutes old and without a handoff marker.
    (h.data / "logs" / "coordinator-heartbeat.json").write_text(
        '{"session_id":"sess-old","terminal_handle":"term_old",'
        '"written_at":"2026-10-25T11:55:00Z"}',
        encoding="utf-8",
    )
    (h.data / "logs" / "commitments.jsonl").write_text(
        json.dumps(
            {
                "type": "add",
                "id": "c1",
                "issue": 461,
                "due": "2026-10-25T09:00:00Z",
                "text": "#461 AC-3：seed 20261107",
                "url": "https://github.com/YiCheng0608/stock-lab/issues/461#issuecomment-5",
                "at": "2026-10-24T00:00:00Z",
                "session_id": "sess-old",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return h


def _take_over(h: Harness, *args: str) -> subprocess.CompletedProcess:
    return h.run(
        "take_over.sh",
        *args,
        CLAUDE_CODE_SESSION_ID="sess-new",
        ORCA_TERMINAL_HANDLE="term_new",
        TMPDIR=h.temp.as_posix(),
        TAKE_OVER_LISTENER_WAIT="0",
    )


def _last(result: subprocess.CompletedProcess) -> dict:
    return json.loads(result.stdout.strip().splitlines()[-1])


def _body(h: Harness) -> str:
    return json.loads((h.fake / "issue1.json").read_bytes())["body"]


def _orca(h: Harness) -> list[str]:
    return [c for c in h.calls("orca") if c.startswith("terminal ")]


def _listener(h: Harness) -> list[str]:
    path = h.fake / "listener_calls.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_take_over_runs_every_step_in_order_and_reads_each_back(to: Harness) -> None:
    result = _take_over(to, "term_old")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _last(result) == {
        "ok": True,
        "done": [
            "heartbeat",
            "listener",
            "comment",
            "row",
            "close",
            "relisten",
            "commitments",
            "memory",
        ],
        "failed": None,
        "reason": None,
        "comment_url": COMMENT_URL,
    }
    # heartbeat: the old one is taken over without its handoff marker.
    heartbeat = json.loads(
        (to.data / "logs" / "coordinator-heartbeat.json").read_text(encoding="utf-8")
    )
    assert heartbeat == {
        "session_id": "sess-new",
        "terminal_handle": "term_new",
        "written_at": "2026-10-25T12:00:00Z",
    }
    # gh: the #1 comment, then the body read, edited and read back.
    assert to.calls("gh")[0] == (
        "api repos/YiCheng0608/stock-lab/issues/1/comments --method POST --input -"
    )
    gets = to.calls("gh")[1:]
    assert len(gets) == 3
    assert gets[0] == gets[2] == "api repos/YiCheng0608/stock-lab/issues/1"
    assert gets[1].startswith(
        "api repos/YiCheng0608/stock-lab/issues/1 --method PATCH --input "
    )
    posted = json.loads((to.fake / "posted.json").read_text(encoding="utf-8"))["body"]
    lines = posted.splitlines()
    assert lines[0] == "回報：統籌 session 更換：term_new／sess-new"
    assert "- 2026-10-25 20:00（台北）接手；前任 terminal `term_old`。" in lines
    assert "- 未兌現的承諾：1 則（已到期 1 則）" in lines
    assert any(ln.startswith("  [c1] [已到期]") for ln in lines)
    assert lines[-1] == "<!-- stock-lab:coordinator -->"
    # #1's body: only the coordinator row changed, every other byte as it was.
    new = _body(to)
    before, after = BODY.split(OLD_ROW)
    assert new.startswith(before) and new.endswith(after)
    row = new[len(before) : len(new) - len(after)]
    assert "\r" not in row and "\n" not in row
    assert row.startswith("- terminal `term_new`（管理 checkout `")
    assert row.endswith(
        f"`），session `sess-new`；2026-10-25T12:00Z 接手（[900]({COMMENT_URL})）。"
    )
    assert new.encode("utf-8").replace(row.encode(), OLD_ROW.encode()) == BODY.encode()
    # The old terminal: idle first, then closed; the listener started before the comment
    # and again after the close.
    assert _orca(to) == [
        "terminal wait --terminal term_old --for tui-idle --timeout-ms 60000 --json",
        "terminal close --terminal term_old --json",
    ]
    # No listener ran before: this run starts one in its own terminal and keeps it.
    assert _listener(to) == ["--status", "start", "--status", "start", "--status"]
    # The commitments, then the memory check (#705), are printed last, before the JSON
    # line.
    out = result.stdout.strip().splitlines()
    assert out[-5] == "未兌現的承諾：1 則（已到期 1 則）"
    assert out[-4].startswith("  [c1] [已到期]")
    assert out[-3].startswith("memory_check: 通過（1 則記憶")
    assert out[-2].startswith("take_over：全部完成：")
    assert list(to.temp.iterdir()) == []
    # The run's record goes once every step is done.
    assert not (to.data / "logs" / "take-over-sess-new.json").exists()


def test_take_over_waits_for_the_old_terminals_listener_to_end(to: Harness) -> None:
    """Review 3: a listener that ran before the take-over ends with the old terminal; a new
    one is started after it stopped answering, and checked."""
    to.write("listener_up", "")
    to.write("orca_terminal_close.hook", CLOSE_ENDS_LISTENER)
    result = _take_over(to, "term_old")
    assert result.returncode == 0, result.stdout + result.stderr
    # listener: it runs, so the start keeps it; relisten: it is gone after the close,
    # then started again and answering.
    assert _listener(to) == [
        "--status",
        "start",
        "--status",
        "--status",
        "start",
        "--status",
    ]
    assert (to.fake / "listener_up").exists()


def test_take_over_stops_when_the_old_listener_still_answers(to: Harness) -> None:
    """Review 3: a listener that ran before and still answers after the close may not be
    the old terminal's, or may end later and leave none: relisten fails, and a run going
    on --from relisten does not wait again."""
    to.write("listener_up", "")
    result = _take_over(to, "term_old")
    assert result.returncode == 1, result.stdout + result.stderr
    line = _last(result)
    assert line["failed"] == "relisten"
    assert line["done"] == ["heartbeat", "listener", "comment", "row", "close"]
    assert "仍在回應" in line["reason"]
    assert (
        f"bash tools/ops/take_over.sh term_old --from relisten --comment-url {COMMENT_URL}"
        in result.stderr
    )
    record = to.data / "logs" / "take-over-sess-new.json"
    assert json.loads(record.read_text(encoding="utf-8"))["listener"] == "running"
    again = _take_over(
        to, "term_old", "--from", "relisten", "--comment-url", COMMENT_URL
    )
    assert again.returncode == 0, again.stdout + again.stderr
    assert _last(again)["done"] == ["relisten", "commitments", "memory"]
    assert not record.exists()


def test_take_over_checks_the_listener_it_started(to: Harness) -> None:
    """A start that exits 0 but leaves no listener answering is a failure."""
    to.write("listener_start_dud", "")
    result = _take_over(to, "term_old")
    assert result.returncode == 1, result.stdout + result.stderr
    assert _last(result)["failed"] == "listener"
    assert to.calls("gh") == [] and _orca(to) == []


@pytest.mark.parametrize(
    ("step", "setup", "gh_calls", "orca_calls"),
    [
        ("listener", lambda h: h.write("listener_start_fails", ""), 0, 0),
        ("comment", lambda h: h.write("fail_comment", ""), 1, 0),
        ("row", lambda h: h.write("fail_get", ""), 2, 0),
        ("row", lambda h: h.write("fail_patch", ""), 3, 0),
        # The fake drops the edit: the read-back differs.
        ("row", lambda h: h.write("patch_ignored", ""), 4, 0),
        (
            "close",
            lambda h: h.answer("orca_terminal_wait", _ok({"satisfied": False})),
            4,
            1,
        ),
        (
            "close",
            lambda h: h.answer("orca_terminal_close", {"ok": False, "error": "x"}),
            4,
            2,
        ),
    ],
    ids=["listener", "comment", "get", "patch", "readback", "busy", "close"],
)
def test_take_over_stops_at_the_failed_step_and_says_what_was_done(
    to: Harness, step: str, setup, gh_calls: int, orca_calls: int
) -> None:
    setup(to)
    result = _take_over(to, "term_old")
    assert result.returncode == 1, result.stdout + result.stderr
    line = _last(result)
    order = [
        "heartbeat",
        "listener",
        "comment",
        "row",
        "close",
        "relisten",
        "commitments",
        "memory",
    ]
    assert line["ok"] is False
    assert line["failed"] == step
    assert line["done"] == order[: order.index(step)]
    assert line["reason"]
    assert len(to.calls("gh")) == gh_calls
    assert len(_orca(to)) == orca_calls
    # Nothing after the failed step: the body is as it was until the row step succeeds
    # (the fake's PATCH failed or was dropped in the row cases).
    assert (_body(to) == BODY) is (step != "close")
    again = f"bash tools/ops/take_over.sh term_old --from {step}"
    if order.index(step) > order.index("comment"):
        again += f" --comment-url {COMMENT_URL}"
    assert again in result.stderr
    assert (
        f"已完成：{' '.join(line['done']) or '（無）'}；失敗：{step}" in result.stderr
    )


@pytest.mark.parametrize(
    "body",
    [
        BODY.replace("## 現任統籌\r\n", "## 統籌\r\n"),
        BODY.replace(f"{OLD_ROW}\r\n", f"{OLD_ROW}\r\n- 第二列\r\n"),
        BODY.replace(f"{OLD_ROW}\r\n", ""),
        BODY + "\r\n## 現任統籌\r\n- x\r\n",
    ],
    ids=["no-heading", "two-rows", "no-row", "two-headings"],
)
def test_take_over_leaves_a_body_it_cannot_read_as_it_was(
    to: Harness, body: str
) -> None:
    (to.fake / "issue1.json").write_bytes(json.dumps({"body": body}).encode())
    result = _take_over(to, "term_old")
    assert result.returncode == 1, result.stdout + result.stderr
    assert _last(result)["failed"] == "row"
    assert "#1 本文未修改" in result.stderr
    assert not [c for c in to.calls("gh") if "PATCH" in c]
    assert _body(to) == body
    assert _orca(to) == []


def test_take_over_goes_on_from_the_failed_step(to: Harness) -> None:
    to.write("fail_patch", "")
    assert _take_over(to, "term_old").returncode == 1
    (to.fake / "fail_patch").unlink()
    calls = len(to.calls("gh"))
    result = _take_over(to, "term_old", "--from", "row", "--comment-url", COMMENT_URL)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _last(result)["done"] == [
        "row",
        "close",
        "relisten",
        "commitments",
        "memory",
    ]
    # No second comment on #1.
    assert not [c for c in to.calls("gh")[calls:] if "comments" in c]
    assert f"（[900]({COMMENT_URL})）。" in _body(to)


def test_take_over_without_an_old_terminal_touches_no_terminal(to: Harness) -> None:
    result = _take_over(to, "--no-old-terminal")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _last(result)["done"] == [
        "heartbeat",
        "listener",
        "comment",
        "row",
        "close:skipped",
        "relisten:skipped",
        "commitments",
        "memory",
    ]
    assert _orca(to) == []
    assert _listener(to) == ["--status", "start", "--status"]
    posted = json.loads((to.fake / "posted.json").read_text(encoding="utf-8"))["body"]
    assert "前任 terminal 已不存在。" in posted


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("",),
        ("term_new",),
        ("term_old", "term_other"),
        ("-x",),
        ("term_old", "--from", "row"),
        ("term_old", "--from", "nope"),
        ("term_old", "--comment-url", COMMENT_URL),
        ("term_old", "--from", "close", "--comment-url", "https://example.com/1"),
        # Review 2: a handle the heartbeat does not name (an engineer's terminal).
        ("term_engineer",),
        # Going on without the record of an earlier run: what the heartbeat named is gone.
        ("term_old", "--from", "close", "--comment-url", COMMENT_URL),
    ],
    ids=[
        "none",
        "empty",
        "own",
        "two",
        "flag",
        "no-url",
        "step",
        "url-early",
        "bad-url",
        "not-the-heartbeats",
        "no-record",
    ],
)
def test_take_over_refuses_bad_arguments_before_any_step(
    to: Harness, args: tuple
) -> None:
    before = (to.data / "logs" / "coordinator-heartbeat.json").read_bytes()
    result = _take_over(to, *args)
    assert result.returncode == 64, result.stdout + result.stderr
    assert (to.data / "logs" / "coordinator-heartbeat.json").read_bytes() == before
    assert to.calls("gh") == [] and _orca(to) == [] and _listener(to) == []
    assert not (to.data / "logs" / "take-over-sess-new.json").exists()


@pytest.mark.parametrize("heartbeat", ["mine", "none", "unreadable"])
def test_take_over_refuses_a_handle_without_a_heartbeat_naming_it(
    to: Harness, heartbeat: str
) -> None:
    """Review 2: with no other session's heartbeat there is nothing to check the handle
    against, so it is refused; --no-old-terminal still works."""
    path = to.data / "logs" / "coordinator-heartbeat.json"
    if heartbeat == "mine":
        path.write_text(
            '{"session_id":"sess-new","terminal_handle":"term_old",'
            '"written_at":"2026-10-25T11:55:00Z"}',
            encoding="utf-8",
        )
    elif heartbeat == "none":
        path.unlink()
    else:
        path.write_text("{", encoding="utf-8")
    result = _take_over(to, "term_old")
    assert result.returncode == 64, result.stdout + result.stderr
    assert "不是心跳記的舊統籌 terminal" in result.stderr
    assert to.calls("gh") == [] and _orca(to) == []
    assert _take_over(to, "--no-old-terminal").returncode == 0


def test_take_over_going_on_checks_the_handle_against_its_record(to: Harness) -> None:
    """Review 2: after the heartbeat step the heartbeat names this session; a run going on
    with --from checks the handle against what the first run recorded."""
    to.answer("orca_terminal_wait", _ok({"satisfied": False}))
    assert _take_over(to, "term_old").returncode == 1
    record = json.loads(
        (to.data / "logs" / "take-over-sess-new.json").read_text(encoding="utf-8")
    )
    assert record["old_handle"] == "term_old"
    to.answer("orca_terminal_wait", _ok({"satisfied": True}))
    resume = ("--from", "close", "--comment-url", COMMENT_URL)
    wrong = _take_over(to, "term_engineer", *resume)
    assert wrong.returncode == 64, wrong.stdout + wrong.stderr
    assert "terminal close" not in " ".join(_orca(to))
    result = _take_over(to, "term_old", *resume)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _orca(to)[-1] == "terminal close --terminal term_old --json"


def test_the_handover_text_runs_take_over() -> None:
    """AC-4: the handover text hands the mechanical steps to take_over.sh instead of
    listing them, and 統籌承諾 writes the commitments file as well as the comment."""
    text = (OPS.parents[1] / "docs" / "COORDINATOR.md").read_text(encoding="utf-8")
    handover = (
        text.split("接手文固定如下", 1)[1].split("```text\n", 1)[1].split("\n```", 1)[0]
    )
    assert "bash tools/ops/take_over.sh <舊 handle>" in handover
    assert "bash tools/ops/patrol.sh" in handover
    # The steps take_over.sh does are not left in the text to be done by hand.
    for manual in (
        "wake_listener_start.sh",
        "orca terminal close",
        "orca terminal wait",
    ):
        assert manual not in handover, manual
    promise = next(ln for ln in text.splitlines() if ln.startswith("- **統籌承諾**"))
    assert "commit.sh add" in promise and "commitments.jsonl" in promise


# --- coordinator_json.replace_coordinator_row ---------------------------------------


def _cj():
    spec = importlib.util.spec_from_file_location(
        "coordinator_json", OPS / "coordinator_json.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("body", "want"),
    [
        ("## 現任統籌\n- old\n", "## 現任統籌\n- NEW\n"),
        ("## 現任統籌\r\n- old", "## 現任統籌\r\n- NEW"),
        (
            "a\r\r## 現任統籌  \r- old\r\r## b\r- c",
            "a\r\r## 現任統籌  \r- NEW\r\r## b\r- c",
        ),
        (
            "## 現任統籌\n說明\n\n- old\u2028x\n## 下一節\n- y\n",
            "## 現任統籌\n說明\n\n- NEW\n## 下一節\n- y\n",
        ),
    ],
    ids=["lf", "crlf-last", "cr", "ls-in-row"],
)
def test_replace_coordinator_row_keeps_every_other_character(
    body: str, want: str
) -> None:
    assert _cj().replace_coordinator_row(body, "- NEW") == want


def test_replace_coordinator_row_takes_one_line_only() -> None:
    with pytest.raises(ValueError):
        _cj().replace_coordinator_row("## 現任統籌\n- old\n", "- a\n- b")
    with pytest.raises(ValueError):
        _cj().replace_coordinator_row("## 現任統籌\n- old\n", "no dash")
