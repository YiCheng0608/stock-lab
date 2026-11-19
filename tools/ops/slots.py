"""The parallel task slots, counted by patrol.sh (#727; AGENTS.md 任務生命週期).

The rules are the 決定 on #727 (6882324819); docs/COORDINATOR.md 處理佇列 names them:

- A task is an Issue with a local `task/<n>-*` worktree (`git worktree list`); several
  worktrees of one Issue are one task.
- 只等合併 (not counted): an open PR from the task's branch whose latest `review：`
  comment (with the coordinator mark) says on its first line 可合併，必修 0 項 and names a
  head `<sha>`; after that commit the PR holds only update-branch merge commits (two
  parents, committed by GitHub); the CI of the PR's head is not red; every worktree of the
  task is clean and its HEAD is one of the PR's commits. A PR merged with the worktree not
  closed yet is not counted either (已合併，等結案), nor a closed Issue with no open PR.
- 等外部 (not counted): the Issue's latest comment whose first line is
  `回報：等外部（head `<sha>`）：<事件>，預計 <YYYY-MM-DD HH:MM>（台北）`, while every
  worktree of the task is clean at that HEAD, no 提問 and no 回報 without the coordinator
  mark came after it, and the time it names has not passed.
- Everything else is counted, with its reason: 開發中 (no PR), review 中 (no review yet),
  有必修, CI 紅, and 判定不了 (why) when something could not be read.

Candidates, when a slot is free: the board's 待辦 items in board order (project 1,
POSITION), open `[任務]` Issues with no task worktree. One waits (有依賴) while GitHub's
blocked-by holds an open Issue, or the body's 依賴的任務／資料 line waits for an open
Issue or PR: a #n before a 後 in the same sentence (cut at 。；;) with 合併, 完成, 結案
or 驗收 between them (waited_refs).

One GraphQL call reads all of it, and the unanswered questions as well (QUERY keeps the
OpenQuestions name and every field coordinator_json.unanswered_questions reads, and #1's
body for governance_check, #807).

  query                      the GraphQL query (no stdin)
  report NOW WORKTREES STATUS
                             stdin is the answer, or nothing when GitHub was not read; NOW
                             is epoch seconds, WORKTREES a file with `git worktree list
                             --porcelain` ("" when git could not list it), STATUS a file
                             with "clean|dirty|unknown<TAB>path" per task worktree. Prints
                             the 名額 line, one line per task with the comment it was
                             decided on, and the 待辦 when a slot is free. When a slot is
                             free and a candidate can be dispatched, the last line is
                             "名額空缺 M 個，請派工：#n" and the exit is 11, or 0 in the
                             daily window (台北 21:30～23:30), the line saying so. Exit 0
                             otherwise; 64 bad arguments.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from coordinator_json import (
    GATE,
    GOVERNANCE_FIELDS,
    PAGE,
    THREAD_FIELDS,
    cancelled_run,
    coordinator_comment,
    get,
    latest_checks,
    newest_ci_run,
    one_line,
    run_id,
)
from event_queue import SLOTS

TAIPEI = timezone(timedelta(hours=8))
VACANCY_EXIT = 11
# Commits of a PR read: the reviewed head is looked for among them.
COMMITS = 100
# Check runs of the head read: two runs of every job of ci.yml fit (a cancelled duplicate).
CONTEXTS = 60
# 待辦 items read and shown.
BOARD_PAGE = 20
SHOWN = 3
# Merged PRs read, newest first: a task's worktree is closed within about an hour of its
# merge (close_task.sh), and fewer than 30 PRs merge in that time. An older one falls to
# whether its Issue is closed (Issue 已關，等結案).
MERGED_PAGE = 30
# The thread fields are coordinator_json's (unanswered_questions reads them from the same
# answer), so the two queries cannot drift apart.
_THREAD = THREAD_FIELDS.format(n=PAGE)
QUERY = (
    "query OpenQuestions($owner:String!,$name:String!){"
    "repository(owner:$owner,name:$name){"
    f"{GOVERNANCE_FIELDS} "
    f"issues(states:OPEN,first:{PAGE}){{totalCount nodes{{{_THREAD}}}}}"
    f"pullRequests(states:OPEN,first:{PAGE}){{totalCount nodes{{{_THREAD} url "
    "headRefName headRefOid "
    f"commits(last:{COMMITS}){{totalCount nodes{{commit{{oid committer{{name email}} "
    "parents{totalCount}}}}"
    # The head's check runs, read once (not for every commit): CI 紅 is the `required`
    # run of the newest workflow run (ci_red); detailsUrl and the workflow name are what
    # newest_ci_run reads to tell the runs apart (#817).
    f"tip:commits(last:1){{nodes{{commit{{statusCheckRollup{{state contexts(first:{CONTEXTS})"
    "{totalCount nodes{__typename ... on CheckRun{name conclusion startedAt detailsUrl "
    "checkSuite{workflowRun{workflow{name}}}}}}}}}}}}"
    f"merged:pullRequests(states:MERGED,first:{MERGED_PAGE},"
    "orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number url headRefName}}}"
    # status:待辦 as GraphQL escapes: the query stays ASCII on any console code page.
    "user(login:$owner){projectV2(number:1){"
    f'items(first:{BOARD_PAGE},query:"is:open status:\\u5f85\\u8fa6",'
    "orderBy:{field:POSITION,direction:ASC}){totalCount nodes{content{__typename "
    "... on Issue{number title state url body milestone{title} "
    "blockedBy(first:10){totalCount nodes{number state}}}}}}}}"
    "}"
)

_TASK_BRANCH = re.compile(r"task/(\d+)-")
_REVIEW = re.compile(r"\s*review[：:]")
_MERGEABLE = re.compile(r"可合併，必修 0 項")
_MUST_FIX = re.compile(r"必修 ([1-9]\d*) 項")
_HEAD = re.compile(r"head `([0-9a-f]{7,40})`")
_QUESTION = re.compile(r"\s*提問[：:]")
_REPORT = re.compile(r"\s*回報[：:]")
_EXTERNAL = re.compile(r"\s*回報[：:]等外部")
_EXTERNAL_FULL = re.compile(
    r"\s*回報[：:]等外部（head `([0-9a-f]{7,40})`）[：:].*預計 "
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})"
)
_DEPENDS = re.compile(r"依賴的任務／資料[：:](.*)")
_REF = re.compile(r"#(\d+)")
_SENTENCE = re.compile(r"[。；;]")
_WAIT_WORDS = ("合併", "完成", "結案", "驗收")
_GITHUB = ("GitHub", "noreply@github.com")


@dataclass
class Worktree:
    path: str
    branch: str
    head: str
    state: str = "unknown"  # clean, dirty or unknown (git status could not run)


@dataclass
class Verdict:
    issue: int
    counted: bool
    reason: str
    link: str = ""
    worktrees: list = field(default_factory=list)


def task_worktrees(porcelain: str, status: dict[str, str]) -> dict[int, list[Worktree]]:
    tasks: dict[int, list[Worktree]] = {}
    for block in porcelain.replace("\r", "").split("\n\n"):
        path = head = branch = ""
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                head = line[len("HEAD ") :]
            elif line.startswith("branch refs/heads/"):
                branch = line[len("branch refs/heads/") :]
        match = _TASK_BRANCH.match(branch)
        if path and match:
            tasks.setdefault(int(match.group(1)), []).append(
                Worktree(path, branch, head, status.get(path, "unknown"))
            )
    return tasks


def _first_line(body: str) -> str:
    return ((body or "").lstrip("﻿").strip().splitlines() or [""])[0]


def _local_problem(worktrees: list[Worktree], heads) -> str:
    """Why the task's worktrees are not as the verdict needs, or ""; heads(sha) says
    whether a worktree's HEAD is allowed."""
    for w in worktrees:
        if w.state == "unknown":
            return f"判定不了（讀不了 {w.branch} 的 git status）"
        if w.state == "dirty":
            return f"工作樹有沒 commit 的改動（{w.branch}）"
        if not heads(w.head):
            return f"本機 HEAD {w.head[:7]} 不是判定的 head（{w.branch}）"
    return ""


_RED = frozenset(
    {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
)


def _check(node: dict) -> dict:
    """A CheckRun of QUERY in the shape of gh --json statusCheckRollup, which
    newest_ci_run reads."""
    return {
        "name": node.get("name"),
        "conclusion": node.get("conclusion"),
        "startedAt": node.get("startedAt"),
        "detailsUrl": node.get("detailsUrl"),
        "workflowName": get(node, "checkSuite.workflowRun.workflow.name"),
    }


def ci_red(pr: dict) -> bool:
    """The `required` check run of the newest CI run of the PR's head failed. The
    rollup's own state is not used: a run cancelled by a newer one of the same head
    (concurrency) makes it FAILURE while `required` decides (docs/GUARDRAILS.md, PR
    #432). The newest run is newest_ci_run's, the run patrol's ci= (check_state) reads:
    while it has no `required` yet, or its `required` is still going, the CI is going,
    not red, even if the cancelled run's `required` failed (PR #816, 2026-11-16, #817).
    Of that run's `required` checks the newest is latest_checks's, as for ci= (a queued
    re-run with no time yet is the newest). Checks with no run id (no detailsUrl) are
    all taken. With no `required` among the runs read and more left, the rollup state
    decides (判定不了 is counted, PR #829 review 6926278317); with all read, not red.
    newest_ci_run skips a run concurrency cancelled (PR #842, #843); when every run was
    cancelled, the newest one is red whatever its `required` says, as ci= is failure."""
    tip = get(pr, "tip.nodes") or []
    rollup = (get(tip[0], "commit.statusCheckRollup") or {}) if tip else {}
    contexts = rollup.get("contexts") or {}
    nodes = contexts.get("nodes") or []
    checks = [_check(n) for n in nodes if n.get("name")]
    runs = [c for c in checks if c["name"] == GATE]
    newest = newest_ci_run(checks)
    if newest is not None and cancelled_run(checks, newest[1]):
        return True
    if newest is not None:
        # A run id is unique in the repository (event_queue.ci_result compares it alone).
        runs = [c for c in runs if run_id(c) == newest[1]]
    if runs:
        return any(
            (c.get("conclusion") or "").upper() in _RED for c in latest_checks(runs)
        )
    if (contexts.get("totalCount") or 0) > len(nodes):
        return (rollup.get("state") or "").upper() in ("FAILURE", "ERROR")
    return False


def merge_only(pr: dict, worktrees: list[Worktree]) -> Verdict | str:
    """A not counted Verdict when the PR only waits to be merged, else the reason it is
    counted."""
    number = pr.get("number")
    if ci_red(pr):
        return f"CI 紅（PR #{number}）"
    comments = pr.get("comments") or {}
    reviews = [
        c
        for c in comments.get("nodes") or []
        if _REVIEW.match((c.get("body") or "").lstrip("﻿"))
        and coordinator_comment(c.get("body"))
    ]
    if not reviews:
        if (comments.get("totalCount") or 0) > len(comments.get("nodes") or []):
            return f"判定不了（PR #{number} 的留言超過 {PAGE} 則，沒讀到 review）"
        return f"review 中（PR #{number}）"
    review = reviews[-1]
    line, url = _first_line(review.get("body")), review.get("url") or ""
    must = _MUST_FIX.search(line)
    head = _HEAD.search(line)
    if not _MERGEABLE.search(line):
        why = (
            f"有必修 {must.group(1)} 項"
            if must
            else "最新 review 不是「可合併，必修 0 項」"
        )
        return f"{why}（PR #{number}；{url}）"
    if not head:
        return f"判定不了（review 第一行沒有 head：{url}）"
    commits = get(pr, "commits") or {}
    nodes = [n.get("commit") or {} for n in commits.get("nodes") or []]
    at = next(
        (
            i
            for i, c in enumerate(nodes)
            if (c.get("oid") or "").startswith(head.group(1))
        ),
        None,
    )
    if at is None:
        if (commits.get("totalCount") or 0) > len(nodes):
            return f"判定不了（review 的 head 不在 PR #{number} 最新 {COMMITS} 個 commit 裡）"
        return f"review 的 head {head.group(1)[:7]} 不在 PR #{number} 上（{url}）"
    for c in nodes[at + 1 :]:
        committer = c.get("committer") or {}
        if not (
            (get(c, "parents.totalCount") or 0) == 2
            and (committer.get("name"), committer.get("email")) == _GITHUB
        ):
            return f"review 後有新 commit {(c.get('oid') or '')[:7]}（PR #{number}；{url}）"
    oids = {c.get("oid") for c in nodes}
    problem = _local_problem(worktrees, lambda sha: sha in oids)
    if problem:
        return f"{problem}（PR #{number}；{url}）"
    return Verdict(0, False, f"只等合併（PR #{number}）", url)


def waits_external(thread: dict | None, worktrees: list[Worktree], now: int):
    """A not counted Verdict, the reason a declaration no longer holds, or None when
    the Issue has none."""
    if thread is None:
        return None
    nodes = get(thread, "comments.nodes") or []
    at = None
    for i, c in enumerate(nodes):
        if _EXTERNAL.match((c.get("body") or "").lstrip("﻿")):
            at = i
    if at is None:
        return None
    declared = nodes[at]
    url = declared.get("url") or ""
    match = _EXTERNAL_FULL.match(_first_line(declared.get("body")))
    if not match:
        return f"等外部宣告的格式不對（{url}）"
    for c in nodes[at + 1 :]:
        body = (c.get("body") or "").lstrip("﻿")
        if _QUESTION.match(body) or (
            _REPORT.match(body) and not coordinator_comment(body)
        ):
            return f"等外部宣告後又有{_first_line(body)[:3]}（{c.get('url') or ''}）"
    try:
        due = datetime.strptime(match.group(2), "%Y-%m-%d %H:%M").replace(tzinfo=TAIPEI)
    except ValueError:
        return f"等外部宣告的預計時點讀不懂（{url}）"
    if now > due.timestamp():
        return f"等外部已過預計時點 {match.group(2)}（{url}）"
    sha = match.group(1)
    problem = _local_problem(worktrees, lambda head: head.startswith(sha))
    if problem:
        return f"{problem}（等外部 {url}）"
    return Verdict(0, False, f"等外部（預計 {match.group(2)}）", url)


def decide(doc, tasks: dict[int, list[Worktree]], now: int) -> list[Verdict]:
    repo = get(doc, "data.repository") if doc is not None else None
    verdicts = []
    for issue in sorted(tasks):
        worktrees = tasks[issue]
        verdict = _decide_one(repo, issue, worktrees, now)
        verdict.issue, verdict.worktrees = issue, worktrees
        verdicts.append(verdict)
    return verdicts


def _decide_one(repo, issue: int, worktrees: list[Worktree], now: int) -> Verdict:
    if not repo:
        return Verdict(issue, True, "判定不了（GitHub 未查完）")
    branches = {w.branch for w in worktrees}
    prs = repo.get("pullRequests") or {}
    issues = repo.get("issues") or {}
    open_prs = [p for p in prs.get("nodes") or [] if p.get("headRefName") in branches]
    thread = next(
        (t for t in issues.get("nodes") or [] if t.get("number") == issue), None
    )
    issues_complete = (issues.get("totalCount") or 0) <= len(issues.get("nodes") or [])
    reason = ""
    if open_prs:
        # Every open PR of the task must only wait for its merge, each checked against
        # the worktrees of its own branch; the first that does not gives the reason.
        results = [
            merge_only(pr, [w for w in worktrees if w.branch == pr.get("headRefName")])
            for pr in open_prs
        ]
        reason = next((r for r in results if not isinstance(r, Verdict)), "")
        if not reason:
            return results[0]
    elif (prs.get("totalCount") or 0) > len(prs.get("nodes") or []):
        return Verdict(issue, True, f"判定不了（open PR 超過 {PAGE} 個）")
    else:
        merged = next(
            (
                p
                for p in get(repo, "merged.nodes") or []
                if p.get("headRefName") in branches
            ),
            None,
        )
        if merged:
            return Verdict(
                issue,
                False,
                f"已合併，等結案（PR #{merged['number']}）",
                merged.get("url") or "",
            )
        if thread is None and issues_complete:
            return Verdict(issue, False, "Issue 已關，等結案")
    if thread is None and not issues_complete:
        unread = f"判定不了（open Issue 超過 {PAGE} 個，沒讀到等外部宣告）"
        return Verdict(issue, True, f"{reason}；{unread}" if reason else unread)
    external = waits_external(thread, worktrees, now)
    if isinstance(external, Verdict):
        return external
    if external:
        return Verdict(issue, True, external)
    return Verdict(issue, True, reason or "開發中（沒有 PR）")


def dependencies(item: dict, open_numbers: set[int] | None) -> list[str]:
    """What the 待辦 Issue waits for: "#n（blocked-by）" or "#n（本文）"."""
    waits = []
    blocked = item.get("blockedBy") or {}
    for node in blocked.get("nodes") or []:
        if node.get("state") == "OPEN":
            waits.append(f"#{node.get('number')}（blocked-by）")
    if (blocked.get("totalCount") or 0) > len(blocked.get("nodes") or []):
        waits.append("blocked-by 未讀完")
    for line in (item.get("body") or "").splitlines():
        match = _DEPENDS.search(line)
        if not match:
            continue
        for n in waited_refs(match.group(1)):
            if open_numbers is None:
                waits.append(f"#{n}（本文，open 與否未查完）")
            elif n in open_numbers and n != item.get("number"):
                waits.append(f"#{n}（本文）")
    return list(dict.fromkeys(waits))


def waited_refs(text: str) -> list[int]:
    """The #n the 依賴 line waits for (PR #737 review 6882741345): in a sentence (cut at
    。, ；, ;), a #n before a 後 with 合併, 完成, 結案 or 驗收 between the two, as in
    「#725（登記）合併後派」 or 「#702 批 1 驗收後」. A #n named for reference (「#721
    （規格改版）」) or a 後 that is no wait (「#729 拿掉研究狀態標示後的版本」) is not."""
    refs = []
    for sentence in _SENTENCE.split(text):
        afters = [i for i, ch in enumerate(sentence) if ch == "後"]
        for ref in _REF.finditer(sentence):
            if any(
                any(word in sentence[ref.end() : at] for word in _WAIT_WORDS)
                for at in afters
                if at >= ref.end()
            ):
                refs.append(int(ref.group(1)))
    return refs


def in_daily(now: int) -> bool:
    t = datetime.fromtimestamp(now, TAIPEI)
    minutes = t.hour * 60 + t.minute
    return 21 * 60 + 30 <= minutes < 23 * 60 + 30


def report(doc, tasks: dict[int, list[Worktree]], now: int) -> tuple[list[str], int]:
    verdicts = decide(doc, tasks, now)
    counted = [v for v in verdicts if v.counted]
    free = max(SLOTS - len(counted), 0)
    unread = doc is None or get(doc, "data.repository") is None
    parts = []
    if counted:
        parts.append(
            "算：" + "、".join(f"#{v.issue} {_short(v.reason)}" for v in counted)
        )
    others = [v for v in verdicts if not v.counted]
    if others:
        parts.append(
            "不算：" + "、".join(f"#{v.issue} {_short(v.reason)}" for v in others)
        )
    head = f"名額：已用 {len(counted)}／{SLOTS}" + (
        f"（{'；'.join(parts)}）" if parts else ""
    )
    if unread:
        head += "（未查完：GitHub 沒讀到，不判定空額）"
    lines = [head]
    for v in verdicts:
        where = "、".join(w.branch for w in v.worktrees)
        link = f" {v.link}" if v.link else ""
        lines.append(
            f"  #{v.issue} {'算' if v.counted else '不算'}：{v.reason}{link}（{where}）"
        )
    if unread or free == 0:
        return lines, 0
    board = get(doc, "data.user.projectV2.items")
    if doc.get("errors"):
        # A partial answer (gh exits 1 with data and errors): which part is missing is
        # not checked field by field, so no task is claimed dispatchable.
        paths = "、".join(
            ".".join(str(p) for p in e.get("path") or []) or "?"
            for e in doc["errors"]
            if isinstance(e, dict)
        )
        lines.append(f"名額空缺 {free} 個；待辦：未查完（GitHub 回部分錯誤：{paths}）")
        return lines, 0
    if board is None:
        lines.append(f"名額空缺 {free} 個；待辦：未查完（看板沒讀到）")
        return lines, 0
    repo = get(doc, "data.repository") or {}
    open_numbers = None
    if all(
        (repo.get(k) or {}).get("totalCount", 0)
        <= len((repo.get(k) or {}).get("nodes") or [])
        for k in ("issues", "pullRequests")
    ):
        open_numbers = {
            t.get("number")
            for k in ("issues", "pullRequests")
            for t in (repo.get(k) or {}).get("nodes") or []
        }
    ready, shown = [], []
    for node in board.get("nodes") or []:
        item = node.get("content") or {}
        title = item.get("title") or ""
        if (
            item.get("__typename") != "Issue"
            or item.get("state") != "OPEN"
            or not title.startswith("[任務]")
            or item.get("number") in tasks
        ):
            continue
        waits = dependencies(item, open_numbers)
        milestone = get(item, "milestone.title") or "無 milestone"
        status = f"有依賴，等 {'、'.join(waits)}" if waits else "可派"
        if not waits:
            ready.append(item["number"])
        if len(shown) < SHOWN or not waits and len(ready) <= free:
            shown.append(
                f"  #{item['number']} {status}［{milestone}］{one_line(title, 50)}"
            )
    more = (board.get("totalCount") or 0) - len(board.get("nodes") or [])
    lines.append(
        f"待辦（看板順序，前 {len(board.get('nodes') or [])} 張"
        + (f"，另有 {more} 張未讀" if more > 0 else "")
        + "）："
    )
    lines += shown or ["  （沒有可派的 [任務]）"]
    if not ready:
        lines.append(f"名額空缺 {free} 個，待辦沒有可派的單")
        return lines, 0
    picks = "、".join(f"#{n}" for n in ready[:free])
    if in_daily(now):
        lines.append(
            f"名額空缺 {free} 個，請派工：{picks}（台北 21:30～23:30 daily 時段不派新工，只印出）"
        )
        return lines, 0
    lines.append(f"名額空缺 {free} 個，請派工：{picks}")
    return lines, VACANCY_EXIT


def _short(reason: str) -> str:
    return reason.split("（", 1)[0]


def _status(text: str) -> dict[str, str]:
    out = {}
    for line in text.replace("\r", "").splitlines():
        state, _, path = line.partition("\t")
        if path:
            out[path] = state
    return out


def _read(path: str) -> str | None:
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")
    if argv[:1] == ["query"]:
        print(QUERY)
        return 0
    if len(argv) != 4 or argv[0] != "report" or not argv[1].isdigit():
        print(__doc__, file=sys.stderr)
        return 64
    now = int(argv[1])
    porcelain, status = _read(argv[2]), _read(argv[3]) or ""
    if porcelain is None:
        print("名額：判定不了（git worktree list 失敗，讀不到 task worktree）")
        return 0
    text = sys.stdin.read()
    try:
        doc = json.loads(text) if text.strip() else None
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or get(doc, "data.repository") is None:
        doc = None
    lines, code = report(doc, task_worktrees(porcelain, _status(status)), now)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
