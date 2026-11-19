"""The rules a new coordinator must read stay where it reads them (#828, #804 範圍 6).

docs/COORDINATOR.md keeps only what a take-over needs; the rest is in
docs/ops/COORDINATOR_REFERENCE.md behind a line that says when to read it. The rules below
have no moment that would send the coordinator there, so each must stay in the part it
reads at take-over (AGENTS.md, docs/COORDINATOR.md and, for the comment rules of PR #815,
docs/WORKFLOW.md 留言類型), in its own section. The handover text itself is in 開啟命令 of
the reference (#850 決定 7016472613): it is the new coordinator's first prompt, so its rules
are read at take-over without a second read of the handbook. One keyword each: a later move
or rewrite that takes one out turns its test red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# id: (file, the "## " section it is in, or "接手文" for the handover text, keyword)
REQUIRED: dict[str, tuple[str, str, str]] = {
    "comment-sh": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "留言一律用 `bash tools/ops/comment.sh",
    ),
    "review-first-line": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "一律以「review：可合併，必修 0 項（head `<sha>`…）」",
    ),
    "waiting-external": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "`回報：等外部（head `<sha>`）：<事件>，預計 <YYYY-MM-DD HH:MM>（台北）`",
    ),
    "memory-real-path": (
        "docs/COORDINATOR.md",
        "記憶",
        "統籌改記憶的 Edit／Write 一律寫實際位置",
    ),
    "blocked-by": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "也用 GitHub 的 blocked-by 設上",
    ),
    "daily-window": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "台北 21:30～23:30 是排程 `daily` 時段（21:30 正式一輪、23:00 保險一輪，#466）："
        "不派新工、不跑全套 pytest、不跑全市場 analyze，也不做吃記憶體的 `docker build`",
    ),
    "commit-sh-add": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "再以 `bash tools/ops/commit.sh add",
    ),
    "no-own-polling": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "不自己輪詢 GitHub",
    ),
    "needs-the-user": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "**需要使用者的事**（來源與付費、刪正式資料、外部帳戶、部署、對外操作、正式資料位置）",
    ),
    "handoff-conditions": (
        "docs/COORDINATOR.md",
        "無人值守運作",
        "觸發條件任一成立就換：同一 session 已自動壓縮兩次以上；"
        "最後一次呼叫的 context 超過門檻（預設 450K",
    ),
    "read-before-acting": (
        "docs/ops/COORDINATOR_REFERENCE.md",
        "接手文",
        "現況頁是索引，不是依據：對某張單留言、決定、review、合併、派工、勾 AC 或兌現承諾之前，"
        "先跑 bash tools/ops/patrol.sh --overview <單號>",
    ),
    "correction-first-line": (
        "docs/WORKFLOW.md",
        "留言類型",
        "第一行在類型之後寫「更正 <留言 id>」",
    ),
    "promise-own-comment": (
        "docs/WORKFLOW.md",
        "留言類型",
        "一律另留一則 `統籌承諾：` 並寫進承諾檔",
    ),
}


def _part(text: str, where: str) -> str:
    """The "## <where>" section of text, or the handover text in its 開啟命令; "" when there
    is none."""
    if where == "接手文":
        text = _part(text, "開啟命令")
        if "接手文固定如下" not in text:
            return ""
        rest = text.split("接手文固定如下", 1)[1]
        if "```text\n" not in rest:
            return ""
        return rest.split("```text\n", 1)[1].split("\n```", 1)[0]
    start = text.find(f"\n## {where}\n")
    if start < 0:
        return ""
    end = text.find("\n## ", start + 1)
    return text[start : end if end > 0 else None]


def missing(texts: dict[str, str]) -> list[str]:
    """The ids of REQUIRED whose keyword is not in its section; texts maps path to text."""
    return [
        rule
        for rule, (path, where, keyword) in REQUIRED.items()
        if keyword not in _part(texts[path], where)
    ]


def _texts() -> dict[str, str]:
    return {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in {path for path, _, _ in REQUIRED.values()}
    }


@pytest.mark.parametrize("rule", list(REQUIRED))
def test_a_rule_without_a_trigger_stays_in_the_required_part(rule: str) -> None:
    """AC-1: each rule's keyword is in the section the coordinator reads at take-over."""
    assert rule not in missing(_texts()), REQUIRED[rule]


@pytest.mark.parametrize("rule", list(REQUIRED))
def test_taking_a_keyword_out_is_caught(rule: str) -> None:
    """The check is not vacuous: the docs with one keyword taken out miss that rule only."""
    texts = _texts()
    path, _, keyword = REQUIRED[rule]
    texts[path] = texts[path].replace(keyword, "")
    assert missing(texts) == [rule]


def test_a_keyword_moved_to_the_reference_is_caught() -> None:
    """A rule moved out to the reference (or to another section) no longer counts."""
    texts = _texts()
    path, _, keyword = REQUIRED["no-own-polling"]
    texts[path] = texts[path].replace(keyword, "") + "\n## 附錄\n" + keyword + "\n"
    assert missing(texts) == ["no-own-polling"]


def test_the_handover_text_is_kept_once() -> None:
    """#850: the handbook keeps no copy of the handover text, which the new coordinator
    gets as its first prompt; a copy back in the handbook would be read twice again."""
    handbook = (ROOT / "docs/COORDINATOR.md").read_text(encoding="utf-8")
    reference = (ROOT / "docs/ops/COORDINATOR_REFERENCE.md").read_text(encoding="utf-8")
    assert "接手文固定如下" not in handbook
    assert reference.count("接手文固定如下") == 1
    assert _part(reference, "接手文").startswith("你是 stock-lab 的統籌。")
