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
  "api graphql "*)
    # Page 1 is <fake>/closed.json, the page after cursor C <fake>/closed-C.json (#787);
    # <fake>/fail_graphql fails every call, <fake>/fail_closed-C that page's.
    page=closed all="$*"
    case "$all" in *" -f after="*) page="closed-${all##* -f after=}" ;; esac
    [ -f "$d/fail_graphql" ] && exit 1
    [ -f "$d/fail_$page" ] && exit 1
    if [ -f "$d/$page.json" ]; then cat "$d/$page.json"
    elif [ "$page" = closed ]; then echo '{"data":{"search":{"issueCount":0,"nodes":[]}}}'
    else echo "no page $page" >&2; exit 1; fi ;;
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
# The old coordinator terminal sat at its prompt before the take-over (#806): tui-idle is
# satisfied only by the turn the close step's send ends, never before it. With
# <fake>/wait_never the wait is not satisfied whatever was sent.
IDLE_AFTER_SEND = r"""d="$FAKE_DIR"
if [ -f "$d/sent_text.txt" ] && [ ! -f "$d/wait_never" ]; then
  echo '{"ok": true, "result": {"wait": {"condition": "tui-idle", "satisfied": true}}}'
else
  echo '{"ok": true, "result": {"wait": {"condition": "tui-idle", "satisfied": false}}}'
fi >"$d/orca_terminal_wait.json"
"""
SCREEN = ["● 已回報 #1。", "", "❯ "]
CLOSE_TEXT = "新統籌 term_new 已接手，要關閉這個 terminal。只回覆收到，不要呼叫工具。"
READ = "terminal read --terminal term_old --screen --limit 20 --json"
SEND = f"terminal send --terminal term_old --text {CLOSE_TEXT} --enter --json"
WAIT = "terminal wait --terminal term_old --for tui-idle --timeout-ms 60000 --json"
CLOSE = "terminal close --terminal term_old --json"


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
    # The old terminal (#806): its screen and an empty draft, a send it accepts; the wait
    # sees an idle only after the send (it sat at its prompt before the take-over).
    h.answer(
        "orca_terminal_read",
        _ok({"terminal": {"handle": "term_old", "tail": SCREEN, "draft": ""}}),
    )
    h.answer("orca_terminal_send", _ok({"send": {"accepted": True}}))
    h.write("orca_terminal_wait.hook", IDLE_AFTER_SEND)
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


def _out(result: subprocess.CompletedProcess) -> list[str]:
    return result.stdout.replace("\r", "").splitlines()


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
            "closed",
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
    # gh: the #1 comment, then the body read, edited and read back, then the one
    # GraphQL call of the closed step (#713).
    assert to.calls("gh")[0] == (
        "api repos/YiCheng0608/stock-lab/issues/1/comments --method POST --input -"
    )
    assert to.calls("gh")[-1].startswith(
        "api graphql -f q=repo:YiCheng0608/stock-lab is:closed "
        "closed:>=2026-10-23T12:00:00Z sort:created-asc -f query="
    )
    gets = to.calls("gh")[1:-1]
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
    # The old terminal: read, one short text sent, idle after it, then closed (#806); the
    # listener started before the comment and again after the close.
    assert _orca(to) == [READ, SEND, WAIT, CLOSE]
    assert (to.fake / "sent_text.txt").read_text(encoding="utf-8") == CLOSE_TEXT
    assert "  | ● 已回報 #1。" in _out(result)
    assert "舊 terminal term_old 的 draft：（空）" in _out(result)
    assert not [ln for ln in _out(result) if ln.startswith("提示：")]
    # No listener ran before: this run starts one in its own terminal and keeps it.
    assert _listener(to) == ["--status", "start", "--status", "start", "--status"]
    # The commitments, the closed check (#713), then the memory check (#705), are
    # printed last, before the JSON line.
    out = result.stdout.strip().splitlines()
    assert out[-7] == "未兌現的承諾：1 則（已到期 1 則）"
    assert out[-6].startswith("  [c1] [已到期]")
    assert out[-5].startswith("關閉單核對（2026-10-23T12:00:00Z 之後關閉的")
    assert out[-4].startswith("  其餘正常：")
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
    assert _last(again)["done"] == ["relisten", "commitments", "closed", "memory"]
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
        ("close", lambda h: h.write("wait_never", ""), 4, 3),
        (
            "close",
            lambda h: h.answer("orca_terminal_close", {"ok": False, "error": "x"}),
            4,
            4,
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
        "closed",
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
        "closed",
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
        "closed",
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
    to.write("wait_never", "")
    assert _take_over(to, "term_old").returncode == 1
    record = json.loads(
        (to.data / "logs" / "take-over-sess-new.json").read_text(encoding="utf-8")
    )
    assert record["old_handle"] == "term_old"
    (to.fake / "wait_never").unlink()
    resume = ("--from", "close", "--comment-url", COMMENT_URL)
    wrong = _take_over(to, "term_engineer", *resume)
    assert wrong.returncode == 64, wrong.stdout + wrong.stderr
    assert "terminal close" not in " ".join(_orca(to))
    result = _take_over(to, "term_old", *resume)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _orca(to)[-1] == "terminal close --terminal term_old --json"


# --- the close step on an old terminal already at its prompt (#806) --------------------


def test_close_sends_one_text_so_an_idle_terminal_closes(to: Harness) -> None:
    """AC-1: the old terminal sat at its prompt before the take-over, so no idle comes
    until something ends a turn (2026-11-14, 2026-11-16). The close step sends one short
    text first; the wait then sees the idle and the terminal is closed, with no step by
    hand. Red on the script before #806: it waited without sending and failed close."""
    result = _take_over(to, "term_old")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "close" in _last(result)["done"]
    assert _orca(to) == [READ, SEND, WAIT, CLOSE]
    assert "已關舊 terminal：term_old" in _out(result)


@pytest.mark.parametrize(
    ("setup", "calls", "words"),
    [
        # Gone (stale handle after a reboot, or closed by hand): read fails, so does all.
        (
            lambda h: [
                h.answer(f"orca_terminal_{sub}", {"ok": False, "error": "stale"})
                for sub in ("read", "send", "wait")
            ],
            [READ],
            "讀不了舊 terminal term_old",
        ),
        (
            lambda h: h.answer("orca_terminal_send", {"ok": False, "error": "x"}),
            [READ, SEND],
            "送短訊失敗",
        ),
        (
            lambda h: h.answer(
                "orca_terminal_send", _ok({"send": {"accepted": False}})
            ),
            [READ, SEND],
            "送短訊失敗",
        ),
    ],
    ids=["gone", "send-fails", "send-not-accepted"],
)
def test_close_fails_and_closes_nothing_when_the_old_terminal_cannot_take_the_text(
    to: Harness, setup, calls: list[str], words: str
) -> None:
    """AC-1: a terminal that is not there, or a text it does not take, fails close as
    before: nothing waited for after it, nothing closed, and --from close goes on."""
    setup(to)
    result = _take_over(to, "term_old")
    assert result.returncode == 1, result.stdout + result.stderr
    line = _last(result)
    assert line["failed"] == "close"
    assert line["done"] == ["heartbeat", "listener", "comment", "row"]
    assert words in line["reason"] and "未關" in line["reason"]
    assert _orca(to) == calls
    assert (
        f"bash tools/ops/take_over.sh term_old --from close --comment-url {COMMENT_URL}"
        in result.stderr
    )


def test_close_prints_the_old_screen_and_a_draft_with_a_hint(to: Harness) -> None:
    """AC-2: before the send takes it away, the old terminal's last screen and its draft
    (text in Orca's input box nobody sent) are printed, and a draft with text gets one
    line more pointing at 自動換手機制 4."""
    to.answer(
        "orca_terminal_read",
        _ok(
            {
                "terminal": {
                    "handle": "term_old",
                    "tail": SCREEN,
                    "draft": "明天記得停 daily\n第二行",
                }
            }
        ),
    )
    result = _take_over(to, "term_old")
    assert result.returncode == 0, result.stdout + result.stderr
    out = _out(result)
    start = out.index("舊 terminal term_old 的最後畫面：")
    assert out[start : start + 8] == [
        "舊 terminal term_old 的最後畫面：",
        "  | ● 已回報 #1。",
        "  | ",
        "  | ❯ ",
        "舊 terminal term_old 的 draft：",
        "  | 明天記得停 daily",
        "  | 第二行",
        "提示：舊 terminal 的輸入框有還沒送出的字（上面的 draft），可能是使用者留給舊統籌的話；"
        "關掉後讀不到，照 docs/COORDINATOR.md「自動換手機制」第 4 點處理",
    ]
    # Printed before the text is sent and the terminal closed.
    assert out.index("已關舊 terminal：term_old") > start + 7


# --- the closed step (#713) ------------------------------------------------------------


def _suite(
    conclusion, *, status="COMPLETED", event="push", workflow="CI", run=2
) -> dict:
    return {
        "status": status,
        "conclusion": conclusion,
        "workflowRun": {
            "databaseId": run,
            "event": event,
            "workflow": {"name": workflow},
        },
    }


# A GitHub app's suite with no workflow run sits beside the CI one on every merge commit.
APP_SUITE = {"status": "QUEUED", "conclusion": None, "workflowRun": None}


def _pr(
    number: int,
    head: str,
    *,
    merged=True,
    state=None,
    suites=None,
    base="master",
    total=None,
) -> dict:
    nodes = [APP_SUITE, _suite("SUCCESS")] if suites is None else suites
    return {
        "__typename": "PullRequest",
        "number": number,
        "state": state or ("MERGED" if merged else "CLOSED"),
        "merged": merged,
        "headRefName": head,
        "baseRefName": base,
        "mergeCommit": {
            "oid": f"{number:0>9}" + "f" * 31,
            "checkSuites": {
                "totalCount": len(nodes) if total is None else total,
                "nodes": nodes,
            },
        }
        if merged
        else None,
    }


def _issue(number: int, *prs: dict, reason: str = "COMPLETED") -> dict:
    links = [{k: v for k, v in p.items() if k != "__typename"} for p in prs]
    return {
        "__typename": "Issue",
        "number": number,
        "stateReason": reason,
        "closedByPullRequestsReferences": {"totalCount": len(links), "nodes": links},
    }


def _closed(
    h: Harness,
    *nodes: dict,
    total: int | None = None,
    page: str = "closed",
    next_cursor: str | None = None,
) -> None:
    """The search page PAGE (closed for page 1, closed-<cursor> for the next ones, #787);
    NEXT_CURSOR set says there is a page after it."""
    count = len(nodes) if total is None else total
    info = {"hasNextPage": next_cursor is not None, "endCursor": next_cursor or "end"}
    search = {"issueCount": count, "pageInfo": info, "nodes": list(nodes)}
    h.answer(page, {"data": {"search": search}})


def _all_fine() -> list[dict]:
    """A task Issue with its merged PR, a research Issue with none, one not planned, a
    docs PR no Issue links, an Issue whose second PR replaced a closed one, and one not
    planned whose PR was closed unmerged (review 4)."""
    return [
        _pr(901, "task/900-a"),
        _issue(900, _pr(901, "task/900-a")),
        _issue(899),
        _issue(898, reason="NOT_PLANNED"),
        _pr(897, "docs/x"),
        _issue(896, _pr(894, "task/896-old", merged=False), _pr(895, "task/896-b")),
        _issue(893, _pr(892, "task/893-a", merged=False), reason="NOT_PLANNED"),
    ]


MASTER_WORKTREE = "worktree /repo\nHEAD " + "a" * 40 + "\nbranch refs/heads/master\n"


def _closed_only(h: Harness, *args: str) -> subprocess.CompletedProcess:
    return h.run("take_over.sh", "--closed-only", *args, TMPDIR=h.temp.as_posix())


def _report(result: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in result.stdout.splitlines() if ln.strip()]


def test_closed_step_all_fine_is_one_line(to: Harness) -> None:
    """AC-1: nothing wrong prints the header and one line for the rest. One page (#787
    AC-1): one gh call, the report as it was before paging."""
    _closed(to, *_all_fine())
    to.write("git_worktrees.txt", MASTER_WORKTREE)
    to.write("branches.txt", "master\ntask/7130-other\n")
    result = _closed_only(to)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _report(result) == [
        "關閉單核對（2026-10-23T12:00:00Z 之後關閉的 Issue 5 張、PR 2 個）："
        "異常或未查完 0 張",
        "  其餘正常：Issue 5 張（連同它們的 PR）、沒有連到 Issue 的 PR 1 個；"
        "沒有 PR 的 Issue：#899、#898；不做（PR 都沒合併）的 Issue：#893",
    ]
    # One gh call, read only: no heartbeat, record, terminal or listener touched.
    assert len(to.calls("gh")) == 1
    assert _orca(to) == [] and _listener(to) == []
    heartbeat = (to.data / "logs" / "coordinator-heartbeat.json").read_text(
        encoding="utf-8"
    )
    assert "sess-old" in heartbeat
    assert not list((to.data / "logs").glob("take-over-*"))
    assert list(to.temp.iterdir()) == []


WT_900 = "worktree /wt/900\nHEAD " + "b" * 40 + "\nbranch refs/heads/task/900-a\n"
CI_LINE = "  #900 Issue：PR #901 的 merge commit 000000901（master）"


@pytest.mark.parametrize(
    ("nodes", "worktrees", "branches", "want"),
    [
        (
            [_issue(900, _pr(901, "task/900-a", merged=False))],
            "",
            "",
            "  #900 Issue：PR #901 關閉未合併",
        ),
        (
            [_issue(900, _pr(901, "task/900-a", merged=False, state="OPEN"))],
            "",
            "",
            "  #900 Issue：PR #901 還是 open",
        ),
        (
            [_issue(900, _pr(901, "task/900-a", suites=[_suite("FAILURE")]))],
            "",
            "",
            CI_LINE + "CI 是 failure",
        ),
        (
            # The newest run decides: a red one after a green one is not fine.
            [
                _issue(
                    900,
                    _pr(
                        901,
                        "task/900-a",
                        suites=[_suite("SUCCESS", run=1), _suite("CANCELLED", run=3)],
                    ),
                )
            ],
            "",
            "",
            CI_LINE + "CI 是 cancelled",
        ),
        (
            [
                _issue(
                    900,
                    _pr(901, "task/900-a", suites=[_suite(None, status="IN_PROGRESS")]),
                )
            ],
            "",
            "",
            CI_LINE + "CI 還沒跑完",
        ),
        (
            # Only the CI workflow's push run counts: a schedule run or another
            # workflow is no result.
            [
                _issue(
                    900,
                    _pr(
                        901,
                        "task/900-a",
                        suites=[
                            APP_SUITE,
                            _suite("SUCCESS", event="schedule"),
                            _suite("SUCCESS", workflow="Other"),
                        ],
                    ),
                )
            ],
            "",
            "",
            CI_LINE + "沒有 CI 結果",
        ),
        (
            [_issue(900, _pr(901, "task/900-a"))],
            WT_900,
            "",
            "  #900 Issue：worktree 還在（task/900-a：/wt/900）",
        ),
        (
            [_issue(900, _pr(901, "task/900-a"))],
            "",
            "task/900-a",
            "  #900 Issue：branch task/900-a 還在",
        ),
        (
            # No PR: only task/<n>-* is checked.
            [_issue(900)],
            "",
            "task/900-research",
            "  #900 Issue：branch task/900-research 還在",
        ),
        (
            # A PR no closed Issue links: merged, CI and branch on its own.
            [_pr(897, "docs/x", merged=False)],
            "",
            "docs/x",
            "  #897 PR：關閉未合併；branch docs/x 還在",
        ),
        (
            [_pr(897, "docs/x", suites=[_suite("FAILURE")])],
            "",
            "",
            "  #897 PR：PR #897 的 merge commit 000000897（master）CI 是 failure",
        ),
        (
            # Review 1: the CI run is not among the 20 suites read: not read, not
            # "no result".
            [
                _issue(
                    900,
                    _pr(901, "task/900-a", suites=[APP_SUITE] * 20, total=21),
                )
            ],
            "",
            "",
            CI_LINE + "CI 未查完（check suite 共 21 個，只讀了 20 個）",
        ),
        (
            # Review 5: a PR into another branch than master.
            [_issue(900, _pr(901, "task/900-a", suites=[APP_SUITE], base="feat/x"))],
            "",
            "",
            "  #900 Issue：PR #901 的 merge commit 000000901（feat/x）"
            "沒有 CI 結果（目標分支 feat/x 不是 master）",
        ),
        (
            # Review 2: a detached worktree has no branch line; its directory is the
            # task's (Orca names it task-<n>-<slug>).
            [_issue(900, _pr(901, "task/900-a"))],
            "worktree C:/w/task-900-a\nHEAD " + "c" * 40 + "\ndetached\n",
            "",
            "  #900 Issue：worktree 還在（detached：C:/w/task-900-a）",
        ),
        (
            [_issue(900)],
            "worktree /w/task-900-x\nHEAD "
            + "c" * 40
            + "\ndetached\nprunable gitdir file points to non-existent location\n",
            "",
            "  #900 Issue：worktree 還在（detached、prunable：/w/task-900-x）",
        ),
        (
            # Review 3: the head branch of a linked PR closed unmerged is checked too.
            [
                _issue(
                    900,
                    _pr(899, "task/900-old", merged=False),
                    _pr(901, "feature-x"),
                )
            ],
            "",
            "feature-x",
            "  #900 Issue：branch feature-x 還在",
        ),
    ],
    ids=[
        "not-merged",
        "pr-open",
        "ci-red",
        "ci-newest-red",
        "ci-pending",
        "ci-missing",
        "worktree-left",
        "branch-left",
        "no-pr-branch-left",
        "lone-pr-not-merged",
        "lone-pr-red",
        "ci-unread",
        "ci-not-master",
        "worktree-detached",
        "worktree-prunable",
        "unmerged-pr-branch-left",
    ],
)
def test_closed_step_prints_each_kind_of_problem(
    to: Harness, nodes: list, worktrees: str, branches: str, want: str
) -> None:
    """AC-1: each problem gets its own line, the fine ones are counted on one line."""
    fine = [n for n in _all_fine() if n.get("number") not in (900, 901, 897)]
    _closed(to, *fine, *nodes)
    to.write("git_worktrees.txt", MASTER_WORKTREE + "\n" + worktrees)
    to.write("branches.txt", "master\n" + branches + "\n")
    result = _closed_only(to)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = _report(result)
    assert lines[0].endswith("：異常或未查完 1 張"), lines
    assert lines[1:] == [want, lines[2]]
    assert lines[2].startswith("  其餘正常：Issue ")


def test_closed_step_says_what_it_could_not_read(to: Harness) -> None:
    """A failed gh call, an answer with no data, or more than a page: 未查完, and the
    take-over still goes on (the step never fails the run)."""
    to.write("fail_graphql", "")
    assert _report(_closed_only(to)) == [
        "關閉單核對：未查完（gh api graphql 失敗；gh 呼叫 1 次）"
    ]
    (to.fake / "fail_graphql").unlink()
    to.answer("closed", {"errors": [{"message": "x"}]})
    assert _report(_closed_only(to)) == [
        "關閉單核對：未查完（GraphQL 的回答沒有 data.search；gh 呼叫 1 次）"
    ]
    _closed(to, *_all_fine(), total=150)
    assert _report(_closed_only(to))[-1] == (
        "  未查完：關閉的 Issue／PR 共 150 張，只讀了 7 張"
    )
    # Review 6: closed-check failing otherwise (a Python error) says so, the traceback
    # on stderr.
    to.answer("closed", {"data": {"search": {"issueCount": "x", "nodes": []}}})
    broken = _closed_only(to)
    assert _report(broken) == [
        "關閉單核對：未查完（closed-check 失敗，exit 1；gh 呼叫 1 次）"
    ]
    assert "Traceback" in broken.stderr
    to.write("fail_graphql", "")
    result = _take_over(to, "term_old")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "closed" in _last(result)["done"]
    assert "關閉單核對：未查完（gh api graphql 失敗；gh 呼叫 1 次）" in result.stdout


ALL_FINE_REPORT = [
    "關閉單核對（2026-10-23T12:00:00Z 之後關閉的 Issue 5 張、PR 2 個）：異常或未查完 0 張",
    "  其餘正常：Issue 5 張（連同它們的 PR）、沒有連到 Issue 的 PR 1 個；"
    "沒有 PR 的 Issue：#899、#898；不做（PR 都沒合併）的 Issue：#893",
]


def _graphql_calls(h: Harness) -> list[str]:
    return [c for c in h.calls("gh") if c.startswith("api graphql ")]


# Every page asks the same search, sorted by creation time (PR #788 review): best match
# leaves ties in any order from one call to the next.
SORTED_SEARCH = (
    "api graphql -f q=repo:YiCheng0608/stock-lab is:closed "
    "closed:>=2026-10-23T12:00:00Z sort:created-asc -f query="
)


def _searches(calls: list[str]) -> list[str]:
    return [c.split(" -f query=", 1)[0] + " -f query=" for c in calls]


def test_closed_step_reads_the_next_page_by_its_cursor(to: Harness) -> None:
    """#787 AC-1: two pages read are one report, counted over both; an Issue the second
    page repeats (one closed in between moves the others along) is counted once. Red
    before paging: only the first page was read, and its issueCount said 未查完."""
    fine = _all_fine()
    _closed(to, *fine[:4], total=len(fine), next_cursor="c2")
    _closed(to, fine[3], *fine[4:], total=len(fine), page="closed-c2")
    to.write("git_worktrees.txt", MASTER_WORKTREE)
    to.write("branches.txt", "master\n")
    result = _closed_only(to)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _report(result) == ALL_FINE_REPORT
    calls = _graphql_calls(to)
    assert len(calls) == 2
    assert _searches(calls) == [SORTED_SEARCH] * 2
    assert " -f after=" not in calls[0]
    assert calls[1].endswith(" -f after=c2")
    assert list(to.temp.iterdir()) == []


def test_closed_step_stops_after_three_pages(to: Harness) -> None:
    """#787 AC-1: a third page that has a next one is 未查完（超過 300 張）; no fourth
    page is read."""
    fine = _all_fine()
    _closed(to, *fine[:2], total=350, next_cursor="c2")
    _closed(to, *fine[2:4], total=350, page="closed-c2", next_cursor="c3")
    _closed(to, *fine[4:], total=350, page="closed-c3", next_cursor="c4")
    to.write("git_worktrees.txt", MASTER_WORKTREE)
    to.write("branches.txt", "master\n")
    result = _closed_only(to)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _report(result) == ALL_FINE_REPORT + [
        "  未查完（超過 300 張）：關閉的 Issue／PR 共 350 張，只讀了 7 張"
    ]
    calls = _graphql_calls(to)
    assert [c.rsplit(" -f after=", 1)[-1] for c in calls[1:]] == ["c2", "c3"]
    assert _searches(calls) == [SORTED_SEARCH] * 3


@pytest.mark.parametrize(
    ("setup", "want"),
    [
        (
            lambda h: h.write("fail_closed-c2", ""),
            "關閉單核對：未查完（第 2 頁 gh api graphql 失敗；gh 呼叫 2 次）",
        ),
        (
            lambda h: h.answer("closed-c2", {"errors": [{"message": "x"}]}),
            "關閉單核對：未查完（第 2 頁 GraphQL 的回答沒有 data.search；gh 呼叫 2 次）",
        ),
        (
            lambda h: h.answer(
                "closed-c2",
                {
                    "data": {
                        "search": {
                            "issueCount": 7,
                            "pageInfo": {"hasNextPage": True, "endCursor": None},
                            "nodes": [],
                        }
                    }
                },
            ),
            "關閉單核對：未查完（第 2 頁 說有下一頁卻沒有游標；gh 呼叫 2 次）",
        ),
    ],
    ids=["gh-fails", "no-data", "no-cursor"],
)
def test_closed_step_a_page_it_cannot_read_leaves_all_unread(
    to: Harness, setup, want: str
) -> None:
    """#787 AC-1: a later page that cannot be read is 未查完 with its page and the gh
    calls made; the pages read before it are not reported as if complete."""
    fine = _all_fine()
    _closed(to, *fine[:4], total=len(fine), next_cursor="c2")
    setup(to)
    result = _closed_only(to)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _report(result) == [want]
    assert len(_graphql_calls(to)) == 2
    assert list(to.temp.iterdir()) == []


def test_closed_check_without_git_listings_says_so() -> None:
    doc = {"data": {"search": {"issueCount": 1, "nodes": [_issue(900)]}}}
    lines = _cj().closed_check(doc, None, None, "T")
    assert lines[-2:] == [
        "  未查完：讀不到 git worktree list，worktree 沒有核對",
        "  未查完：讀不到本地 branch，branch 沒有核對",
    ]
    links = _issue(900, *[_pr(n, f"task/900-{n}") for n in range(901, 911)])
    links["closedByPullRequestsReferences"]["totalCount"] = 12
    doc = {"data": {"search": {"issueCount": 1, "nodes": [links]}}}
    assert "  未查完：#900 連到 12 個 PR，只讀了 10 個" in _cj().closed_check(
        doc, "", "", "T"
    )


@pytest.mark.parametrize(
    "args",
    [
        ("term_old",),
        ("--no-old-terminal",),
        ("--from", "closed"),
        ("--from", "heartbeat"),
        ("--session-id", "sess-new"),
        ("--terminal", "term_new"),
        ("--data-dir", "/x"),
    ],
    ids=["handle", "no-old", "from", "from-default", "session", "terminal", "data"],
)
def test_closed_only_takes_no_take_over_arguments(to: Harness, args: tuple) -> None:
    result = _closed_only(to, *args)
    assert result.returncode == 64, result.stdout + result.stderr
    assert to.calls("gh") == []


def test_take_over_goes_on_from_the_closed_step(to: Harness) -> None:
    to.write("fail_patch", "")
    assert _take_over(to, "term_old").returncode == 1
    (to.fake / "fail_patch").unlink()
    result = _take_over(
        to, "term_old", "--from", "closed", "--comment-url", COMMENT_URL
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _last(result)["done"] == ["closed", "memory"]


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
    # #713: the closed Issues and PRs are checked by take_over.sh; only what it lists as
    # wrong or not read has its last comment read.
    assert "合併的 PR 的最後一則留言" not in handover
    assert "核對最近 48 小時內關閉的 Issue 與合併的 PR" in handover
    assert "列為異常或未查完的那幾張的最後一則留言" in handover
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
