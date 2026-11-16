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


def _page(doc, logs: Path, tasks=None, backfill=None, note="") -> list[str]:
    return overview.page(doc, tasks or {}, NOW, str(logs), backfill, note)


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
    text = _text(_page(doc, logs, _tasks(804)))
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
    text = _text(_page(_answer([_issue(804, comments)]), logs))
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
    text = _text(_page(_answer([_issue(804, comments)]), logs))
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
    text = _text(_page(_answer([_issue(702, comments)]), logs, _tasks(702)))
    assert "  名額：不算：等外部（預計 2026-11-17 01:00） 41" in text
    assert "［全文見下：等外部宣告（仍有效，等外部（預計 2026-11-17 01:00））］" in text
    assert "      > 細節" in text


def test_a_declaration_that_no_longer_holds_says_why(logs: Path) -> None:
    """Past its time: the first line and why, not the full text."""
    comments = [_c(702, 42, _external(SHA[:8], "2026-11-16 12:00"))]
    text = _text(_page(_answer([_issue(702, comments)]), logs, _tasks(702)))
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


def test_limits_skip_tables_quotes_and_questions(logs: Path) -> None:
    body = (
        "決定：照 B\n\n"
        "- 不要自己重跑。\n"
        "| 1 | 由統籌合併 | 表格不算 |\n"
        "> 引用裡由統籌的不算\n"
        "```\n不要 這是程式碼\n```\n"
        "要不要另開單之後再說。\n"
        "合併由統籌做；這句沒有。"
    )
    text = _text(
        _page(_answer([_issue(804, [_c(804, 71, body, coordinator=True)])]), logs)
    )
    limits = [ln for ln in text.splitlines() if ln.startswith("    71：")]
    assert limits == ["    71：- 不要自己重跑。", "    71：合併由統籌做；"]


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


def test_the_backfill_is_merged_by_url(logs: Path) -> None:
    """A comment posted between the two calls: the main answer read comments 51..150 of
    150; by the backfill there are 151, its oldest 50 are 1..50, nothing overlaps; one
    more comment that both hold (the race the other way) is listed once."""
    main = _many(702, 51, 150)
    old = _many(702, 1, 51)  # 51 overlaps with the main answer
    backfill = {"data": {"repository": {"t702": {"comments": {"nodes": old}}}}}
    lines = _page(_answer([_issue(702, main, total=150)]), logs, backfill=backfill)
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
    """The latest 10: 決定, 統籌承諾, 待使用者 and no mark in full; 部署 and the session
    change counted; the rest by the first line."""
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
    issue = _issue(1, older + recent, title="治理")
    text = _text(_page(_answer([issue]), logs))
    assert "## #1 [任務]" not in text
    section = text.split("## #1 最近 10 則留言", 1)[1]
    assert "回報：舊的" not in section
    for full in ("限定條件", "承諾內文", "要你做的事", "第二行"):
        assert f"      > {full}" in section
    assert "統 105 回報：一般回報" in section
    assert "不印的內文" not in section
    assert "  只計數：session 更換 2 則、部署 2 則" in section


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
