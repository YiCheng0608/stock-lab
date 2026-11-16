"""tools/ops/slots.py: the parallel task slots patrol.sh prints (#727, 決定 6882324819).

Each verdict has a test (#727 AC-2): 開發中, 有必修, 只等合併, 只等合併 then a new push,
等外部, 等外部 then a change, 判定不了; then the vacancy line and exit code, and the daily
window. The 2026-11-15 00:36 (台北) state is replayed from what GitHub still holds
(#727 AC-3): the coordinator counted 3／3, the rules count 2／3 with one free.

The answers are built here in the shape of slots.QUERY's answer; patrol.sh's own run (one
gh call, the last line, exit 11 after the handoff's 10) is in test_coordinator_scripts.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "tools" / "ops"
sys.path.insert(0, str(OPS))
try:
    import slots
finally:
    sys.path.remove(str(OPS))

MARK = "<!-- stock-lab:coordinator -->"
REPO = "https://github.com/YiCheng0608/stock-lab"
TAIPEI = timezone(timedelta(hours=8))
# 2026-11-15 10:00 台北: outside the daily window.
NOW = int(datetime(2026, 11, 15, 10, 0, tzinfo=TAIPEI).timestamp())
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_M = "c" * 40  # an update-branch merge commit


def _url(number: int, cid: int) -> str:
    return f"{REPO}/issues/{number}#issuecomment-{cid}"


def _comment(number: int, cid: int, body: str, coordinator: bool = False) -> dict:
    return {
        "url": _url(number, cid),
        "createdAt": "2026-11-15T01:00:00Z",
        "body": f"{body}\n\n{MARK}" if coordinator else body,
    }


def _commit(oid: str, merge: bool = False) -> dict:
    who = ("GitHub", "noreply@github.com") if merge else ("Eric Chen", "e@example.com")
    return {
        "commit": {
            "oid": oid,
            "committer": {"name": who[0], "email": who[1]},
            "parents": {"totalCount": 2 if merge else 1},
        }
    }


def _pr(
    number, branch, commits, comments=(), ci="SUCCESS", total=None, runs=None
) -> dict:
    # The head's check runs, as QUERY reads them: by default one `required` run with
    # the conclusion ci (None while it runs).
    if runs is None:
        runs = [("required", ci, "2026-11-15T01:00:00Z")]
    state = (
        "FAILURE" if any(c not in (None, "SUCCESS") for _, c, _ in runs) else "SUCCESS"
    )
    return {
        "number": number,
        "state": "OPEN",
        "url": f"{REPO}/pull/{number}",
        "headRefName": branch,
        "headRefOid": commits[-1]["commit"]["oid"],
        "comments": {"totalCount": len(comments), "nodes": list(comments)},
        "commits": {
            "totalCount": total or len(commits),
            "nodes": list(commits),
        },
        "tip": {
            "nodes": [
                {
                    "commit": {
                        "statusCheckRollup": {
                            "state": state,
                            "contexts": {
                                "totalCount": len(runs),
                                "nodes": [
                                    {
                                        "__typename": "CheckRun",
                                        "name": name,
                                        "conclusion": conclusion,
                                        "startedAt": at,
                                    }
                                    for name, conclusion, at in runs
                                ],
                            },
                        }
                    }
                }
            ]
        },
    }


def _issue(number: int, *comments: dict) -> dict:
    return {
        "number": number,
        "state": "OPEN",
        "comments": {"totalCount": len(comments), "nodes": list(comments)},
    }


def _todo(number, title="[任務] 下一張", body="", blocked=(), milestone="V1.1") -> dict:
    return {
        "content": {
            "__typename": "Issue",
            "number": number,
            "title": title,
            "state": "OPEN",
            "url": f"{REPO}/issues/{number}",
            "body": body,
            "milestone": {"title": milestone},
            "blockedBy": {
                "totalCount": len(blocked),
                "nodes": [{"number": n, "state": s} for n, s in blocked],
            },
        }
    }


def _answer(issues=(), prs=(), merged=(), board=()) -> dict:
    return {
        "data": {
            "repository": {
                "issues": {"totalCount": len(issues), "nodes": list(issues)},
                "pullRequests": {"totalCount": len(prs), "nodes": list(prs)},
                "merged": {"nodes": list(merged)},
            },
            "user": {
                "projectV2": {"items": {"totalCount": len(board), "nodes": list(board)}}
            },
        }
    }


def _tasks(*entries) -> dict:
    """entries: (issue, slug, head, state)."""
    porcelain = "worktree C:/repo\nHEAD " + "0" * 40 + "\nbranch refs/heads/master\n"
    status = {}
    for issue, slug, head, state in entries:
        path = f"C:/wt/task-{issue}-{slug}"
        porcelain += (
            f"\nworktree {path}\nHEAD {head}\nbranch refs/heads/task/{issue}-{slug}\n"
        )
        status[path] = state
    return slots.task_worktrees(porcelain, status)


def _one(answer, tasks, now=NOW) -> slots.Verdict:
    (verdict,) = slots.decide(answer, tasks, now)
    return verdict


def _review(number: int, cid: int, line: str) -> dict:
    return _comment(number, cid, f"{line}\n\n- 細節", coordinator=True)


OK_REVIEW = "review：PR #20 獨立 review（統籌 `abc`，非作者；head `aaaaaaa`）可合併，必修 0 項；CI 綠後由統籌合併"


# --- each verdict (AC-2) --------------------------------------------------------------


def test_no_pr_is_in_development() -> None:
    v = _one(_answer([_issue(10)]), _tasks((10, "x", SHA_A, "clean")))
    assert (v.counted, v.reason) == (True, "開發中（沒有 PR）")


def test_a_review_with_must_fixes_is_counted_with_its_link() -> None:
    review = _review(
        20, 5, "review：PR #20 獨立 review（head `aaaaaaa`）必修 2 項；修完再說"
    )
    answer = _answer([_issue(10)], [_pr(20, "task/10-x", [_commit(SHA_A)], [review])])
    v = _one(answer, _tasks((10, "x", SHA_A, "clean")))
    assert v.counted and v.reason.startswith("有必修 2 項")
    assert review["url"] in v.reason


def test_a_pr_without_a_review_is_in_review() -> None:
    answer = _answer([_issue(10)], [_pr(20, "task/10-x", [_commit(SHA_A)])])
    v = _one(answer, _tasks((10, "x", SHA_A, "clean")))
    assert (v.counted, v.reason) == (True, "review 中（PR #20）")


def test_merge_only_is_not_counted_and_names_the_review() -> None:
    review = _review(20, 5, OK_REVIEW)
    answer = _answer([_issue(10)], [_pr(20, "task/10-x", [_commit(SHA_A)], [review])])
    v = _one(answer, _tasks((10, "x", SHA_A, "clean")))
    assert (v.counted, v.reason, v.link) == (False, "只等合併（PR #20）", review["url"])


def test_an_update_branch_merge_after_the_review_keeps_merge_only() -> None:
    review = _review(20, 5, OK_REVIEW)
    commits = [_commit(SHA_A), _commit(SHA_M, merge=True)]
    answer = _answer([_issue(10)], [_pr(20, "task/10-x", commits, [review])])
    # The local branch is still at the reviewed head: update-branch is remote only.
    assert not _one(answer, _tasks((10, "x", SHA_A, "clean"))).counted


def test_a_push_after_the_merge_only_review_is_counted() -> None:
    review = _review(20, 5, OK_REVIEW)
    commits = [_commit(SHA_A), _commit(SHA_B)]
    answer = _answer([_issue(10)], [_pr(20, "task/10-x", commits, [review])])
    v = _one(answer, _tasks((10, "x", SHA_B, "clean")))
    assert v.counted and v.reason.startswith("review 後有新 commit bbbbbbb")


@pytest.mark.parametrize(
    ("head", "state", "why"),
    [
        (SHA_A, "dirty", "工作樹有沒 commit 的改動"),
        (SHA_B, "clean", "本機 HEAD bbbbbbb 不是判定的 head"),
        (SHA_A, "unknown", "判定不了（讀不了 task/10-x 的 git status）"),
    ],
)
def test_local_changes_end_merge_only(head: str, state: str, why: str) -> None:
    review = _review(20, 5, OK_REVIEW)
    answer = _answer([_issue(10)], [_pr(20, "task/10-x", [_commit(SHA_A)], [review])])
    v = _one(answer, _tasks((10, "x", head, state)))
    assert v.counted and v.reason.startswith(why)


def test_a_red_ci_is_counted() -> None:
    review = _review(20, 5, OK_REVIEW)
    pr = _pr(20, "task/10-x", [_commit(SHA_A)], [review], ci="FAILURE")
    v = _one(_answer([_issue(10)], [pr]), _tasks((10, "x", SHA_A, "clean")))
    assert (v.counted, v.reason) == (True, "CI 紅（PR #20）")


def test_a_merged_pr_waits_for_close_task() -> None:
    merged = {"number": 20, "url": f"{REPO}/pull/20", "headRefName": "task/10-x"}
    v = _one(_answer(merged=[merged]), _tasks((10, "x", SHA_A, "clean")))
    assert (v.counted, v.reason) == (False, "已合併，等結案（PR #20）")


EXTERNAL = "回報：等外部（head `aaaaaaa`）：批 1 回補，預計 2026-11-16 08:00（台北）"


def test_waiting_external_is_not_counted_and_names_the_declaration() -> None:
    declared = _comment(10, 7, EXTERNAL)
    v = _one(_answer([_issue(10, declared)]), _tasks((10, "x", SHA_A, "clean")))
    assert (v.counted, v.reason, v.link) == (
        False,
        "等外部（預計 2026-11-16 08:00）",
        declared["url"],
    )


@pytest.mark.parametrize(
    ("later", "head", "state", "now", "why"),
    [
        ((), SHA_B, "clean", NOW, "本機 HEAD bbbbbbb 不是判定的 head"),
        ((), SHA_A, "dirty", NOW, "工作樹有沒 commit 的改動"),
        (("提問：要不要改？",), SHA_A, "clean", NOW, "等外部宣告後又有提問"),
        (("回報：批 1 完成",), SHA_A, "clean", NOW, "等外部宣告後又有回報"),
        (
            (),
            SHA_A,
            "clean",
            int(datetime(2026, 11, 16, 8, 1, tzinfo=TAIPEI).timestamp()),
            "等外部已過預計時點 2026-11-16 08:00",
        ),
    ],
)
def test_a_change_after_waiting_external_counts_again(
    later, head, state, now, why
) -> None:
    comments = [_comment(10, 7, EXTERNAL)]
    comments += [_comment(10, 8 + i, body) for i, body in enumerate(later)]
    v = _one(_answer([_issue(10, *comments)]), _tasks((10, "x", head, state)), now)
    assert v.counted and v.reason.startswith(why), v.reason


def test_the_coordinators_report_after_the_declaration_keeps_it() -> None:
    comments = [
        _comment(10, 7, EXTERNAL),
        _comment(10, 8, "回報：統籌看過批 1 進度", coordinator=True),
    ]
    v = _one(_answer([_issue(10, *comments)]), _tasks((10, "x", SHA_A, "clean")))
    assert not v.counted


def test_a_declaration_out_of_format_is_counted() -> None:
    declared = _comment(10, 7, "回報：等外部：批 1 回補，明天早上")
    v = _one(_answer([_issue(10, declared)]), _tasks((10, "x", SHA_A, "clean")))
    assert v.counted and v.reason.startswith("等外部宣告的格式不對")


def test_github_not_read_counts_every_task_and_claims_no_vacancy() -> None:
    lines, code = slots.report(None, _tasks((10, "x", SHA_A, "clean")), NOW)
    assert code == 0
    assert lines[0].startswith("名額：已用 1／3（算：#10 判定不了")
    assert "未查完" in lines[0]
    assert not any(line.startswith("名額空缺") for line in lines)


def test_a_reviewed_head_beyond_the_commits_read_cannot_be_decided() -> None:
    review = _review(20, 5, OK_REVIEW)
    pr = _pr(20, "task/10-x", [_commit(SHA_B)], [review], total=150)
    v = _one(_answer([_issue(10)], [pr]), _tasks((10, "x", SHA_B, "clean")))
    assert v.counted and v.reason.startswith("判定不了（review 的 head 不在")


# --- the vacancy line and the daily window (AC-2) -------------------------------------

BOARD = [
    _todo(30, blocked=[(29, "OPEN")]),
    _todo(
        31, body="依賴的任務／資料：PR #40（#41）合併後派。#42 也改同一檔，注意衝突。"
    ),
    _todo(32, title="[功能] 母單"),
    _todo(33, body="依賴的任務／資料：#42 也改同一檔，注意衝突。#43 合併後派。"),
]


def test_a_free_slot_with_a_task_to_dispatch_fails_on_the_last_line() -> None:
    issues = [_issue(n) for n in (10, 29, 41, 42)]
    lines, code = slots.report(
        _answer(issues, board=BOARD), _tasks((10, "x", SHA_A, "clean")), NOW
    )
    assert code == slots.VACANCY_EXIT == 11
    assert lines[0] == "名額：已用 1／3（算：#10 開發中）"
    assert lines[-1] == "名額空缺 2 個，請派工：#33"
    text = "\n".join(lines)
    assert "#30 有依賴，等 #29（blocked-by）" in text
    # #40 is closed (not an open number): only #41 holds #31; #42's sentence has no 後.
    assert "#31 有依賴，等 #41（本文）［V1.1］" in text
    assert "#32" not in text
    assert "#33 可派" in text


def test_the_daily_window_prints_the_vacancy_only() -> None:
    at = int(datetime(2026, 11, 15, 22, 0, tzinfo=TAIPEI).timestamp())
    lines, code = slots.report(
        _answer([_issue(10)], board=[_todo(33)]), _tasks((10, "x", SHA_A, "clean")), at
    )
    assert code == 0
    assert lines[-1].startswith("名額空缺 2 個，請派工：#33（台北 21:30～23:30 daily")


@pytest.mark.parametrize(
    ("hour", "minute", "inside"),
    [(21, 29, False), (21, 30, True), (23, 29, True), (23, 30, False)],
)
def test_the_daily_window_edges(hour: int, minute: int, inside: bool) -> None:
    at = int(datetime(2026, 11, 15, hour, minute, tzinfo=TAIPEI).timestamp())
    assert slots.in_daily(at) is inside


def test_no_free_slot_prints_no_board() -> None:
    tasks = _tasks(*((n, "x", SHA_A, "clean") for n in (10, 11, 12)))
    issues = [_issue(n) for n in (10, 11, 12)]
    lines, code = slots.report(_answer(issues, board=[_todo(33)]), tasks, NOW)
    assert code == 0
    assert lines[0].startswith("名額：已用 3／3")
    assert not any("待辦" in line for line in lines)


def test_a_free_slot_with_nothing_to_dispatch_does_not_fail() -> None:
    lines, code = slots.report(
        _answer([_issue(29)], board=[_todo(30, blocked=[(29, "OPEN")])]), {}, NOW
    )
    assert code == 0
    assert lines[-1] == "名額空缺 3 個，待辦沒有可派的單"


def test_the_query_reads_the_questions_and_the_slots_in_one_call() -> None:
    assert slots.QUERY.startswith("query OpenQuestions(")
    for part in ("headRefOid", "merged:pullRequests", "blockedBy", "POSITION", "body"):
        assert part in slots.QUERY
    assert slots.QUERY.isascii()


# --- AC-3: 2026-11-15 00:36 (台北) as GitHub holds it ------------------------------------


def test_the_2026_11_15_state_counts_two_of_three() -> None:
    """#702 waits for its backfill, #705 (PR #723) only for the merge, #711 (PR #724) has
    a must-fix, #722 started without a PR. The coordinator that took over counted 3／3."""
    at = int(datetime(2026, 11, 14, 16, 36, tzinfo=timezone.utc).timestamp())
    pr723 = _pr(
        723,
        "task/705-memory-upkeep",
        [
            _commit("df25a005e110778c873084e3951d1b97acfca4a3"),
            _commit("13e5fa019ab9b838e1b351c84815716b4b2ed162"),
        ],
        [
            # 6880602626, first line as posted.
            {
                "url": f"{REPO}/pull/723#issuecomment-6880602626",
                "createdAt": "2026-11-14T16:24:28Z",
                "body": "review：PR #723 獨立 review（統籌 `4a691b72`，非作者；head "
                "`13e5fa0`）可合併，必修 0 項；CI 綠後**由統籌合併，你不要自己合併**"
                f"\n\n- 合併後統籌照新流程結案\n\n{MARK}",
            },
            {
                "url": f"{REPO}/pull/723#issuecomment-6880631139",
                "createdAt": "2026-11-14T16:26:22Z",
                "body": "回報：收到 review 6880602626（可合併、必修 0 項）；不改 head `13e5fa01`",
            },
        ],
    )
    pr724 = _pr(
        724,
        "task/711-wake-tiers",
        [
            _commit("276400d4c4c98e39da8d04dd2466db6643a24fc9"),
            _commit("a72faa520a7faf828ed893f401bdfb83b3f7f22e"),
        ],
        [
            {
                "url": f"{REPO}/pull/724#issuecomment-6880734119",
                "createdAt": "2026-11-14T16:33:22Z",
                "body": "review：PR #724 獨立 review（統籌 `03713e80`，非作者；head "
                "`a72faa52`）必修 1 項；修完、CI 綠後**由統籌合併，你不要自己合併**"
                f"\n\n{MARK}",
            },
        ],
        ci=None,  # the required run still going
    )
    # #702 had no declaration then (the format is #727's); the batch-1 state of 00:36
    # as one, at the head its worktree had (b370713, 2026-11-14 21:53 台北).
    i702 = _issue(
        702,
        _comment(
            702,
            6881000001,
            "回報：等外部（head `b370713`）：批 1 回補（研究 DB，2023-06 起逐月），"
            "預計 2026-11-16 12:00（台北）",
        ),
    )
    tasks = _tasks(
        (
            702,
            "history-backfill-run",
            "b370713932f728042abab360f64cd279b5c5b23f",
            "clean",
        ),
        (705, "memory-upkeep", "13e5fa019ab9b838e1b351c84815716b4b2ed162", "clean"),
        (711, "wake-tiers", "a72faa520a7faf828ed893f401bdfb83b3f7f22e", "clean"),
        (722, "backfill-startup", "b89aa60" + "0" * 33, "dirty"),
    )
    answer = _answer(
        [i702, _issue(705), _issue(711), _issue(722), _issue(720)],
        [pr723, pr724],
        board=[
            _todo(720, title="[任務] 統籌 terminal 停在確認框時要被發現並通知使用者")
        ],
    )
    lines, code = slots.report(answer, tasks, at)
    assert lines[0] == (
        "名額：已用 2／3（算：#711 有必修 1 項、#722 開發中；"
        "不算：#702 等外部、#705 只等合併）"
    )
    assert f"{REPO}/pull/723#issuecomment-6880602626" in lines[2]
    assert lines[-1] == "名額空缺 1 個，請派工：#720"
    assert code == 11


# --- PR #737 review 6882741345 ----------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "waited"),
    [
        # #726 and #728 as they are on the board: #721 is named for reference, and
        # 「標示後的版本」 is no wait.
        ("#725（登記）合併後派；#721（規格改版）。", [725]),
        (
            "#681 的 `overnight_us`、今日名單頁的用詞（#729 拿掉研究狀態標示後的版本）；"
            "使用者要先建 bot 並寫好認證檔，第一則才送得出去。",
            [],
        ),
        (
            "PR #724（#711）合併後派。#713 也改 `docs/COORDINATOR.md`，注意衝突。",
            [724, 711],
        ),
        ("#702 批 1 驗收後再派; #690 結案後", [702, 690]),
        ("#700 完成之前不派", []),
    ],
)
def test_the_dependency_line_waits_only_for_a_merge_or_finish(line, waited) -> None:
    assert slots.waited_refs(line) == waited


def test_the_real_726_and_728_lines_leave_the_reference_open_issues_out() -> None:
    issues = [_issue(n) for n in (721, 725, 729)]
    board = [
        _todo(726, body="依賴的任務／資料：#725（登記）合併後派；#721（規格改版）。"),
        _todo(
            728,
            body="依賴的任務／資料：#681 的 `overnight_us`、今日名單頁的用詞"
            "（#729 拿掉研究狀態標示後的版本）；使用者要先建 bot。",
        ),
    ]
    lines, code = slots.report(_answer(issues, board=board), {}, NOW)
    text = "\n".join(lines)
    assert "#726 有依賴，等 #725（本文）［" in text
    assert "#728 可派" in text
    assert (lines[-1], code) == ("名額空缺 3 個，請派工：#728", 11)


def test_every_open_pr_of_the_task_must_only_wait_for_its_merge() -> None:
    ok = _pr(20, "task/10-x", [_commit(SHA_A)], [_review(20, 5, OK_REVIEW)])
    other = _pr(21, "task/10-y", [_commit(SHA_B)])
    tasks = _tasks((10, "x", SHA_A, "clean"), (10, "y", SHA_B, "clean"))
    v = _one(_answer([_issue(10)], [ok, other]), tasks)
    assert (v.counted, v.reason) == (True, "review 中（PR #21）")


def test_more_open_issues_than_read_keeps_the_reason_found() -> None:
    review = _review(20, 5, "review：PR #20（head `aaaaaaa`）必修 1 項")
    answer = _answer([], [_pr(20, "task/10-x", [_commit(SHA_A)], [review])])
    answer["data"]["repository"]["issues"]["totalCount"] = 150
    v = _one(answer, _tasks((10, "x", SHA_A, "clean")))
    assert v.counted
    assert v.reason.startswith("有必修 1 項（PR #20；")
    assert "判定不了（open Issue 超過 100 個" in v.reason


def test_a_partial_answer_claims_no_dispatchable_task() -> None:
    """gh exits 1 with data and errors (a project it cannot read): the tasks are judged
    from the data, no task is called dispatchable."""
    answer = _answer([_issue(10)], board=[_todo(33)])
    answer["data"]["user"] = {"projectV2": None}
    answer["errors"] = [{"type": "NOT_FOUND", "path": ["user", "projectV2"]}]
    lines, code = slots.report(answer, _tasks((10, "x", SHA_A, "clean")), NOW)
    assert lines[0] == "名額：已用 1／3（算：#10 開發中）"
    assert (
        lines[-1] == "名額空缺 2 個；待辦：未查完（GitHub 回部分錯誤：user.projectV2）"
    )
    assert code == 0


def test_the_query_holds_every_field_the_questions_read() -> None:
    """The thread fields come from coordinator_json, so a field unanswered_questions
    starts to read reaches the query patrol.sh sends."""
    import coordinator_json

    fields = coordinator_json.THREAD_FIELDS.format(n=coordinator_json.PAGE)
    assert coordinator_json.QUESTIONS_QUERY.count(fields) == 2
    assert slots.QUERY.count(fields) == 2
    # #1's body (#807), in either query patrol.sh may send.
    governance = coordinator_json.GOVERNANCE_FIELDS
    assert coordinator_json.QUESTIONS_QUERY.count(governance) == 1
    assert slots.QUERY.count(governance) == 1


def test_a_cancelled_duplicate_run_is_not_a_red_ci() -> None:
    """Found on the live run of 2026-11-14T19:15Z: PR #737's rollup said FAILURE because
    a run of the same head was cancelled by a newer one; its `required` was a success and
    the newer run was still going. The newest `required` decides."""
    review = _review(20, 5, OK_REVIEW)
    runs = [
        ("suite", "CANCELLED", "2026-11-14T19:03:05Z"),
        ("required", "SUCCESS", "2026-11-14T19:03:08Z"),
        ("backend", None, "2026-11-14T19:03:34Z"),
    ]
    pr = _pr(20, "task/10-x", [_commit(SHA_A)], [review], runs=runs)
    assert pr["tip"]["nodes"][0]["commit"]["statusCheckRollup"]["state"] == "FAILURE"
    assert not _one(
        _answer([_issue(10)], [pr]), _tasks((10, "x", SHA_A, "clean"))
    ).counted
    runs.append(("required", "FAILURE", "2026-11-14T19:20:00Z"))
    pr = _pr(20, "task/10-x", [_commit(SHA_A)], [review], runs=runs)
    v = _one(_answer([_issue(10)], [pr]), _tasks((10, "x", SHA_A, "clean")))
    assert (v.counted, v.reason) == (True, "CI 紅（PR #20）")
