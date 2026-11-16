"""tools/ops/overview.py: the overview page `patrol.sh --overview` prints (#804).

#804 AC-1 names the fixtures: an ordinary thread, one with more than 100 comments, a 等外部
declaration that holds and one that no longer does, a comment of no type, a 統籌承諾 not
in the commitments file, a 追蹤 Issue with no worktree. The backfill follows decision
6913246451 (no cursor; the oldest totalCount-100 merged by url; 未查完 when not read).
patrol.sh's own run (the gh calls, --max-gh) is in test_coordinator_scripts.py.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "tools" / "ops"
sys.path.insert(0, str(OPS))
try:
    import overview
    import slots
finally:
    sys.path.remove(str(OPS))

MARK = "<!-- stock-lab:coordinator -->"
REPO = "https://github.com/YiCheng0608/stock-lab"
TAIPEI = timezone(timedelta(hours=8))
# 2026-11-16 18:00 台北
NOW = int(datetime(2026, 11, 16, 18, 0, tzinfo=TAIPEI).timestamp())
SHA = "a" * 40


def _url(number: int, cid: int) -> str:
    return f"{REPO}/issues/{number}#issuecomment-{cid}"


def _c(number: int, cid: int, body: str, coordinator=False, at="2026-11-16T01:00:00Z"):
    return {
        "url": _url(number, cid),
        "createdAt": at,
        "body": f"{body}\n\n{MARK}" if coordinator else body,
    }


def _issue(number, comments=(), title="[任務] 一張單", body="", total=None, **extra):
    return {
        "number": number,
        "state": "OPEN",
        "title": title,
        "body": body,
        "milestone": {"title": "流程與基礎建設"},
        "comments": {
            "totalCount": len(comments) if total is None else total,
            "nodes": list(comments),
        },
        **extra,
    }


def _answer(issues, prs=()) -> dict:
    return {
        "data": {
            "repository": {
                "issues": {"totalCount": len(issues), "nodes": list(issues)},
                "pullRequests": {"totalCount": len(prs), "nodes": list(prs)},
                "merged": {"nodes": []},
            }
        }
    }


def _tasks(*numbers: int) -> dict:
    return {
        n: [slots.Worktree(f"C:/wt/{n}", f"task/{n}-x", SHA, "clean")] for n in numbers
    }


@pytest.fixture
def logs(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


def _page(
    doc, logs: Path, tasks=None, backfill=None, note="", numbers=None
) -> list[str]:
    """The index, or with NUMBERS the full sections (patrol.sh --overview <n>)."""
    return overview.page(
        doc, tasks or {}, NOW, str(logs), backfill, note, numbers=numbers
    )


def _text(lines: list[str]) -> str:
    return "\n".join(lines)


BODY = (
    "## 驗收條件\n\n"
    "- [x] AC-1：已做的一條\n"
    "- [ ] AC-2：還沒做的一條，" + "很長" * 40 + "\n"
    "- [ ] AC-3（問答對照）：括號在冒號前也算\n\n"
    "依賴的任務／資料：#803（量測）合併後派；#794 可並行。\n"
)


def test_an_ordinary_thread(logs: Path) -> None:
    """Title, milestone, the open ACs (60 characters), the 依賴 line with the open #n it
    waits for, the slot verdict, and every comment on one line with its links cut."""
    comments = [
        _c(804, 11, "回報：開工\n\nsession x", at="2026-11-16T01:00:00Z"),
        _c(804, 12, "回報：收到", at="2026-11-16T01:05:00Z"),
        _c(
            804,
            13,
            f"提問：要不要 A？見 [#1 6910740125]({_url(1, 6910740125)}) 與 {REPO}/pull/810",
            at="2026-11-16T02:00:00Z",
        ),
        _c(
            804,
            14,
            f"決定：照 A（回覆 [13]({_url(804, 13)})）\n\n- 限定：只在 --overview。",
            coordinator=True,
            at="2026-11-16T02:10:00Z",
        ),
    ]
    doc = _answer([_issue(804, comments, body=BODY), _issue(803)])
    text = _text(_page(doc, logs, _tasks(804), numbers=[804, 803]))
    assert "## #804 [任務] 一張單（Issue；流程與基礎建設；留言 4 則）" in text
    assert "  依賴：#803（量測）合併後派；#794 可並行。［在等 #803］" in text
    assert "  名額：算：開發中（沒有 PR）" in text
    assert "  未勾 AC 2／3：" in text
    assert "    AC-2：還沒做的一條，" + ("很長" * 40)[: 60 - 7] + "…" in text
    assert "    AC-3（問答對照）：括號在冒號前也算" in text
    assert "  回報：開工／收到 2 則（最後 11-16 09:05 12）" in text
    # The question is answered (14 links 13): one line, no full text.
    assert (
        "    11-16 10:00 工 13 提問：要不要 A？見 #1 6910740125 與 #810"
        in text.splitlines()
    )
    assert "    11-16 10:10 統 14 決定：照 A（回覆 13） ↩ 13" in text.splitlines()
    assert "全文［" not in text
    assert "## #803 [任務] 一張單" in text
    assert "  名額：追蹤／待辦（沒有 task worktree）" in [
        ln for ln in text.splitlines() if ln.startswith("  名額")
    ]


def test_full_text_of_an_unanswered_question_and_a_comment_of_no_type(
    logs: Path,
) -> None:
    comments = [
        _c(804, 21, "提問：沒人回的\n\n細節第二行"),
        _c(804, 22, "**提問：** 加粗不算類型\n\n內文"),
    ]
    text = _text(_page(_answer([_issue(804, comments)]), logs, numbers=[804]))
    assert "工 21 提問：沒人回的 ［全文見下：未回覆的提問］" in text
    assert (
        "  全文［未回覆的提問］21：\n      > 提問：沒人回的\n      >\n      > 細節第二行"
        in text
    )
    assert "［全文見下：沒有類型的留言］" in text
    assert "  全文［沒有類型的留言］22：" in text


def test_a_promise_not_in_the_commitments_file_is_printed_in_full(logs: Path) -> None:
    (logs / "commitments.jsonl").write_text(
        json.dumps(
            {
                "type": "add",
                "id": "c1",
                "issue": 804,
                "due": None,
                "text": "已寫進的承諾",
                "url": _url(804, 31),
                "at": "2026-11-16T01:00:00Z",
                "session_id": "s",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    comments = [
        _c(804, 31, "統籌承諾：在承諾檔", coordinator=True),
        _c(804, 32, "統籌承諾：不在承諾檔\n\n合併後統籌會另開單。", coordinator=True),
    ]
    text = _text(_page(_answer([_issue(804, comments)]), logs, numbers=[804]))
    assert "統 31 統籌承諾：在承諾檔" in text
    assert "統 31 統籌承諾：在承諾檔 ［" not in text
    assert "統 32 統籌承諾：不在承諾檔 ［全文見下：不在承諾檔的統籌承諾］" in text
    assert "  全文［不在承諾檔的統籌承諾］32：" in text
    # The sentence that looks like a promise, from the body past the first line.
    assert "    32：合併後統籌會另開單。" in text


def _external(sha: str, due: str) -> str:
    return f"回報：等外部（head `{sha}`）：批 5 回補，預計 {due}（台北）\n\n細節"


def test_a_declaration_that_holds_is_printed_in_full(logs: Path) -> None:
    comments = [_c(702, 41, _external(SHA[:8], "2026-11-17 01:00"))]
    text = _text(
        _page(_answer([_issue(702, comments)]), logs, _tasks(702), numbers=[702])
    )
    assert "  名額：不算：等外部（預計 2026-11-17 01:00） 41" in text
    assert "［全文見下：等外部宣告（仍有效，等外部（預計 2026-11-17 01:00））］" in text
    assert "      > 細節" in text


def test_a_declaration_that_no_longer_holds_says_why(logs: Path) -> None:
    """Past its time: the first line and why, not the full text."""
    comments = [_c(702, 42, _external(SHA[:8], "2026-11-16 12:00"))]
    text = _text(
        _page(_answer([_issue(702, comments)]), logs, _tasks(702), numbers=[702])
    )
    assert "（等外部宣告已失效：等外部已過預計時點 2026-11-16 12:00（42））" in text
    assert "全文［" not in text
    assert "      > 細節" not in text


def test_a_tracking_issue_with_no_worktree(logs: Path) -> None:
    doc = _answer([_issue(699, [_c(699, 51, "回報：月報")], title="[追蹤] 月報")])
    text = _text(_page(doc, logs, _tasks(804)))
    assert "## #699 [追蹤] 月報（Issue；流程與基礎建設；留言 1 則）" in text
    assert "  名額：追蹤／待辦（沒有 task worktree）" in text


def test_a_pr_goes_under_the_issue_it_closes(logs: Path) -> None:
    pr = _issue(
        810,
        [_c(810, 61, "review：可合併，必修 0 項（head `abc1234`）", coordinator=True)],
        title="一個 PR",
        body="Closes #807\n",
    )
    doc = _answer([_issue(807), _issue(808)], [pr])
    lines = _page(doc, logs)
    heads = [ln for ln in lines if ln.startswith("## ")]
    assert heads[:3] == [
        "## #807 [任務] 一張單（Issue；流程與基礎建設；留言 0 則）",
        "## #810 一個 PR（PR；流程與基礎建設；留言 1 則；Closes #807）",
        "## #808 [任務] 一張單（Issue；流程與基礎建設；留言 0 則）",
    ]


def test_what_the_coordinator_is_to_do(logs: Path) -> None:
    """決定 6914347432: the sentences of the coordinator's 決定, 統籌承諾 and review that
    say it is to do something are in the index; a limit (不要, 不可) and tables, quotes
    and code are not, nor the coordinator's 回報 (drafts pasted on #794)."""
    body = (
        "決定：照 B\n\n"
        "- 不要自己重跑。\n"
        "| 1 | 由統籌合併 | 表格不算 |\n"
        "> 引用裡由統籌的不算\n"
        "```\n由統籌 這是程式碼\n```\n"
        "合併由統籌做；這句沒有。\n"
        "- 我會在批 5 跑完時再看。統籌在本單排代跑。\n"
        "#817 由統籌另開單。\n"
        "## 標題由統籌不算"
    )
    report = "回報：草稿\n\n- 新決策由統籌在 #1 留言寫下後同步。"
    # PR #815 review 6915587653 must-fix 2: a first line is read too, the index only
    # prints the last comment.
    first = "決定：照 A；合併後由統籌開單做範圍 6"
    doc = _answer(
        [
            _issue(
                804,
                [
                    _c(804, 70, first, coordinator=True),
                    _c(804, 71, body, coordinator=True),
                    _c(804, 72, report, coordinator=True),
                ],
            )
        ]
    )
    for numbers in (None, [804]):
        text = _text(_page(doc, logs, numbers=numbers))
        todo = [ln for ln in text.splitlines() if ln.startswith("    7")]
        assert todo == [
            "    70：合併後由統籌開單做範圍 6",
            "    71：合併由統籌做；",
            "    71：- 我會在批 5 跑完時再看。",
            "    71：統籌在本單排代跑。",
            "    71：#817 由統籌另開單。",
        ], numbers


def test_worktrees_not_listed_are_not_taken_for_none(logs: Path) -> None:
    """PR #815 review 6915587653 must-fix 3: without the task worktrees an Issue is not
    「沒有 task worktree」 and a declaration is not said to hold."""
    comments = [_c(702, 41, _external(SHA[:8], "2026-11-17 01:00"))]
    doc = _answer([_issue(702, comments)])
    for numbers in (None, [702]):
        lines = overview.page(doc, {}, NOW, str(logs), None, "", False, numbers)
        text = _text(lines)
        assert "沒有 task worktree" not in text, numbers
        assert "  名額：判定不了（讀不到 task worktree）" in lines, numbers
        assert "仍有效" not in text, numbers
        assert "worktree 未查，有效與否判定不了" in text, numbers
        assert lines[1].startswith("名額：判定不了（讀不到 task worktree")


def test_a_supplementary_decision_does_not_answer_a_question(logs: Path) -> None:
    """PR #815 review 6915587653 suggestion 1: what answers a question is patrol's own
    rule (coordinator_json), so the page and patrol's list agree."""
    comments = [
        _c(804, 81, "提問：要不要 A？"),
        _c(804, 82, f"決定（補充）：見 [81]({_url(804, 81)})", coordinator=True),
    ]
    text = _text(_page(_answer([_issue(804, comments)]), logs))
    assert "  全文［未回覆的提問］81：" in text


def test_an_ended_session_says_why(logs: Path) -> None:
    """Suggestion 4: turn_hook.cjs writes end_reason."""
    sessions = logs / "sessions"
    sessions.mkdir()
    (sessions / "s1234567-x.json").write_text(
        json.dumps(
            {
                "session_id": "s1234567-x",
                "issue": 804,
                "state": "ended",
                "started_at": "2026-11-16T09:00:00Z",
                "ended_at": "2026-11-16T09:30:00Z",
                "end_reason": "prompt_input_exit",
            }
        ),
        encoding="utf-8",
    )
    text = _text(_page(_answer([_issue(804)]), logs, _tasks(804)))
    assert "工程師 session：s1234567 ended（11-16 17:30）；prompt_input_exit" in text


# --- the index (決定 6914347432) -------------------------------------------------------


def test_the_index_holds_one_line_per_thread_and_what_needs_the_coordinator(
    logs: Path,
) -> None:
    """The index: title with the count of open ACs, 名額, the last comment, the open
    question in full, a holding declaration on one line, the comments of no type by id;
    every comment and the AC texts only with --overview <n>."""
    comments = [
        _c(702, 1, "回報：第一則", at="2026-11-16T00:00:00Z"),
        _c(702, 2, "提問：沒人回的\n\n細節", at="2026-11-16T00:10:00Z"),
        _c(702, 3, "沒有類型\n\n內文", at="2026-11-16T00:20:00Z"),
        _c(702, 4, _external(SHA[:8], "2026-11-17 01:00"), at="2026-11-16T00:30:00Z"),
    ]
    doc = _answer([_issue(702, comments, body=BODY)])
    index = _page(doc, logs, _tasks(702))
    text = _text(index)
    assert (
        "## #702 [任務] 一張單（Issue；流程與基礎建設；留言 4 則；未勾 AC 2／3）"
        in text
    )
    assert "    AC-2" not in text and "  留言：" not in text
    assert " 工 1 回報：第一則" not in text
    assert "  全文［未回覆的提問］2：" in text
    assert "  沒有類型的留言 1 則：3（全文：patrol.sh --overview 702）" in text
    assert "      > 內文" not in text
    assert any(
        ln.startswith("  等外部宣告（仍有效）：11-16 08:30 工 4 回報：等外部")
        for ln in index
    )
    assert "      > 細節" in text  # the question's, not the declaration's
    assert text.count("      > 細節") == 1
    detail = _text(_page(doc, logs, _tasks(702), numbers=[702]))
    assert "  留言：" in detail and " 工 1 回報：第一則" in detail
    assert "  全文［沒有類型的留言］3：" in detail
    assert "    AC-2：" in detail
    assert "## 最近 24 小時兌現的承諾" not in detail


def test_overview_of_a_thread_not_open(logs: Path) -> None:
    lines = _page(_answer([_issue(804)]), logs, numbers=[999])
    assert "## #999：不是 open 的 Issue／PR（或這次沒讀到）" in lines


# --- more than 100 comments (decision 6913246451) -----------------------------------


def _many(number: int, first: int, last: int) -> list[dict]:
    return [
        _c(
            number,
            n,
            f"回報：第 {n} 則",
            at=f"2026-11-{1 + n // 1000:02d}T00:{n // 60 % 60:02d}:{n % 60:02d}Z",
        )
        for n in range(first, last + 1)
    ]


def test_the_backfill_query_reads_the_oldest_comments_of_each_long_thread() -> None:
    doc = _answer(
        [_issue(702, _many(702, 51, 150), total=150), _issue(804, _many(804, 1, 3))],
        [_issue(812, _many(812, 101, 200), total=250)],
    )
    query = overview.backfill_query(doc)
    assert query.startswith("query OverviewBackfill(")
    assert "t702:issueOrPullRequest(number:702)" in query
    assert "comments(first:50)" in query
    assert "t812:issueOrPullRequest(number:812)" in query
    assert "comments(first:100)" in query
    assert "t804:" not in query
    assert overview.backfill_query(_answer([_issue(804, _many(804, 1, 3))])) == ""
    # --overview <n> (review 6915587653 suggestion 3): only the threads printed.
    only = overview.backfill_query(doc, {812})
    assert "t812:" in only and "t702:" not in only
    assert overview.backfill_query(doc, {804}) == ""


def test_the_backfill_is_merged_by_url(logs: Path) -> None:
    """A comment posted between the two calls: the main answer read comments 51..150 of
    150; by the backfill there are 151, its oldest 50 are 1..50, nothing overlaps; one
    more comment that both hold (the race the other way) is listed once."""
    main = _many(702, 51, 150)
    old = _many(702, 1, 51)  # 51 overlaps with the main answer
    backfill = {"data": {"repository": {"t702": {"comments": {"nodes": old}}}}}
    lines = _page(
        _answer([_issue(702, main, total=150)]), logs, backfill=backfill, numbers=[702]
    )
    rows = [ln for ln in lines if " 工 " in ln and "回報：第" in ln]
    assert len(rows) == 150
    assert sum(" 工 51 " in ln for ln in rows) == 1
    assert not any(ln.startswith("  未查完") for ln in lines)


def test_more_than_200_comments_says_what_is_missing(logs: Path) -> None:
    backfill = {
        "data": {"repository": {"t702": {"comments": {"nodes": _many(702, 1, 100)}}}}
    }
    lines = _page(
        _answer([_issue(702, _many(702, 151, 250), total=250)]), logs, backfill=backfill
    )
    assert "  未查完：共 250 則，缺第 101～150 則（只補得到最舊 100 則）" in lines


def test_no_backfill_is_not_taken_as_complete(logs: Path) -> None:
    lines = _page(
        _answer([_issue(702, _many(702, 51, 150), total=150)]),
        logs,
        note="gh 呼叫已達上限 1，沒有補查",
    )
    assert "  未查完：共 150 則，缺第 1～50 則（gh 呼叫已達上限 1，沒有補查）" in lines


# --- #1, the kept commitments, the sessions ----------------------------------------


def test_the_governance_comments(logs: Path) -> None:
    """The latest 10 (決定 6914347432 A-2): 待使用者 and no mark in full unless #1's body
    names them (read at takeover); 決定 and 統籌承諾 by the first line (exit 12 keeps
    them in the body); 部署 and the session change counted."""
    older = [_c(1, n, f"回報：舊的 {n}", coordinator=True) for n in range(1, 6)]
    recent = [
        _c(1, 101, "決定：A\n\n限定條件", coordinator=True),
        _c(1, 102, "統籌承諾：B\n\n承諾內文", coordinator=True),
        _c(1, 103, "待使用者：C\n\n要你做的事", coordinator=True),
        _c(1, 104, "使用者在雲端 session 的決定\n\n第二行"),
        _c(1, 105, "回報：一般回報\n\n不印的內文", coordinator=True),
        _c(1, 106, "部署：v1.2.63\n\n內文", coordinator=True),
        _c(1, 107, "回報：統籌 session 更換：term／s\n\n內文", coordinator=True),
        _c(1, 108, "回報：統籌 session 更換：term／t", coordinator=True),
        _c(1, 109, "回報：進度", coordinator=True),
        _c(1, 110, "部署：v1.2.64"),
    ]
    recent.append(_c(1, 6912550851, "待使用者：本文已列\n\n已在本文的全文", True))
    issue = _issue(1, older + recent[1:], title="治理")
    doc = _answer([issue])
    doc["data"]["repository"]["governance"] = {"body": "- 待使用者 [6912550851](x)\n"}
    text = _text(_page(doc, logs))
    assert "## #1 [任務]" not in text
    section = text.split("## #1 最近 10 則留言", 1)[1]
    assert "回報：舊的" not in section
    # 102 is a 統籌承諾 the (empty) commitments file lacks: in full (review 6915587653).
    for full in ("要你做的事", "第二行", "承諾內文"):
        assert f"      > {full}" in section
    for line in (
        "統 102（全文；不在承諾檔的統籌承諾）：",
        "統 105 回報：一般回報",
        "統 6912550851 待使用者：本文已列",
    ):
        assert line in section
    for hidden in ("不印的內文", "已在本文的全文"):
        assert hidden not in section
    assert "  只計數：session 更換 2 則、部署 2 則" in section


def test_a_promise_on_1_not_in_the_commitments_file(logs: Path) -> None:
    """PR #815 review 6915587653 must-fix 1: a 統籌承諾 on #1 the commitments file lacks
    is printed in full, also when it is older than the latest 10; one in the file is
    not."""
    (logs / "commitments.jsonl").write_text(
        json.dumps(
            {
                "type": "add",
                "id": "c1",
                "issue": 1,
                "due": None,
                "text": "已寫進",
                "url": _url(1, 2),
                "at": "2026-11-16T01:00:00Z",
                "session_id": "s",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    comments = [
        _c(1, 1, "統籌承諾：明天 10:00 讀回 X\n\n沒寫進承諾檔的內文", True),
        _c(1, 2, "統籌承諾：已在承諾檔\n\n寫進了的內文", True),
    ] + [_c(1, n, f"回報：其他 {n}", True) for n in range(10, 20)]
    text = _text(_page(_answer([_issue(1, comments, title="治理")]), logs))
    section = text.split("## #1 最近 10 則留言", 1)[1]
    assert "  最近 10 則以前、不在承諾檔的統籌承諾 1 則：" in section
    assert "      > 沒寫進承諾檔的內文" in section
    assert "寫進了的內文" not in section
    # Among the latest 10 it is marked where it stands.
    recent = _text(
        _page(_answer([_issue(1, comments[:1] + comments[3:], title="治理")]), logs)
    )
    assert "統 1（全文；不在承諾檔的統籌承諾）：" in recent


def test_commitments_kept_in_the_last_24_hours(logs: Path) -> None:
    rows = [
        {
            "type": "add",
            "id": "c1",
            "issue": 702,
            "due": None,
            "text": "代跑批 6",
            "url": _url(702, 81),
            "at": "2026-11-15T01:00:00Z",
            "session_id": "s",
        },
        {
            "type": "add",
            "id": "c2",
            "issue": 786,
            "due": None,
            "text": "太早兌現的",
            "url": _url(786, 82),
            "at": "2026-11-14T01:00:00Z",
            "session_id": "s",
        },
        {
            "type": "done",
            "id": "c1",
            "at": "2026-11-16T08:00:00Z",
            "session_id": "s",
            "url": _url(702, 83),
        },
        {
            "type": "done",
            "id": "c2",
            "at": "2026-11-15T08:00:00Z",
            "session_id": "s",
            "url": None,
        },
    ]
    (logs / "commitments.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    lines = _page(_answer([]), logs)
    assert "## 最近 24 小時兌現的承諾：1 則" in lines
    assert "    [c1] 11-16 16:00 #702 代跑批 6（承諾 #702 81；兌現 #702 83）" in lines


def test_the_newest_engineer_session_of_the_issue(logs: Path) -> None:
    sessions = logs / "sessions"
    sessions.mkdir()
    for sid, state, at in (
        ("old11111-x", "ended", "2026-11-15T01:00:00Z"),
        ("new22222-y", "stopped", "2026-11-16T09:00:00Z"),
    ):
        (sessions / f"{sid}.json").write_text(
            json.dumps(
                {
                    "session_id": sid,
                    "issue": 804,
                    "state": state,
                    "started_at": at,
                    "ended_at": at,
                    "commented": False,
                    "last_message": "在等統籌",
                }
            ),
            encoding="utf-8",
        )
    text = _text(_page(_answer([_issue(804)]), logs, _tasks(804)))
    assert (
        "  工程師 session：new22222 stopped（11-16 17:00）；這回合沒有留言；最後：在等統籌"
        in text
    )
    assert "old11111" not in text


def test_github_not_read_prints_the_local_part(logs: Path) -> None:
    lines = _page(None, logs)
    assert "現況頁：未查完（GitHub 沒讀到），只印本機的部分" in lines
    assert lines[-1].startswith("=== 現況頁結束：")


def test_the_size_line_counts_the_page(logs: Path) -> None:
    lines = _page(_answer([_issue(804, [_c(804, 1, "回報：中文")])]), logs)
    size = len(("\n".join(lines[:-1]) + "\n").encode("utf-8"))
    assert lines[-1] == f"=== 現況頁結束：{size:,} 位元組（不含本行）==="


def test_the_main_query_reads_title_body_and_milestone() -> None:
    """#804: the page's fields come with patrol's one call (THREAD_FIELDS)."""
    import coordinator_json

    for field in ("title", "body", "milestone{title}"):
        assert field in coordinator_json.THREAD_FIELDS.format(n=1)
    assert slots.QUERY.count("milestone{title}") >= 2


def test_a_correction_in_the_body_is_marked(logs: Path) -> None:
    """#804 AC-3 round 1: #702 6900881313 corrected 6893948126 in its body only; the
    new-flow reader did not open it. Its line now says so."""
    body = (
        "決定：照 A，AC-2 現在就勾（回覆 [91](" + _url(702, 91) + ")）\n\n"
        "- 我在 [6893948126]("
        + _url(702, 6893948126)
        + ") 寫的「0 個壞檔」更正成同一句。\n"
        "- 舊的做法取代掉了，不再列 id。"
    )
    text = _text(
        _page(
            _answer([_issue(702, [_c(702, 92, body, coordinator=True)])]),
            logs,
            numbers=[702],
        )
    )
    line = next(ln for ln in text.splitlines() if " 統 92 " in ln)
    assert line.endswith("［內文更正或取代：6893948126、?］")
