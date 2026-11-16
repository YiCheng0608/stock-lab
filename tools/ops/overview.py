"""The coordinator's overview page, printed by `patrol.sh --overview` (#804).

A new coordinator reads this page instead of every open thread whole (docs/COORDINATOR.md
接手文). It is built by this script, no LLM, from the answer of patrol's one GraphQL call
(slots.QUERY: THREAD_FIELDS with title, body and milestone), the local task worktrees, the
commitments file and the engineer sessions' state files. It is an index, not the source:
before acting on a thread the coordinator reads that thread's body and the comments the
action touches (the 接手文 says which).

Two layers (#804 決定 6914347432):

- **the index** (`--overview`, read at takeover), per open Issue and PR: title,
  milestone, the count of open ACs, the 依賴的任務／資料 line with the open #n it waits
  for (slots.waited_refs), the slot verdict of slots.decide for an Issue with a task
  worktree (else 追蹤／待辦), the newest engineer session (<data>/logs/sessions/*.json,
  turn_hook.cjs) and the last comment on one line; in full the 提問 no 決定 links to
  (any open thread's) and the 統籌承諾 whose comment id is not in the commitments file;
  on one line the latest 等外部 declaration while it holds; the ids of the comments of no
  type; the sentences of the coordinator's 決定, 統籌承諾 and review (past the first line)
  that say it is to do something (由統籌, 統籌會, 統籌在, 我會). Then #1 and the
  commitments kept in the last 24 hours.
- **the full section** of the threads named (`--overview <n>...`, read before acting on
  one): every comment on one line (Taipei time, 統 for the coordinator mark or 工 for
  none, the comment id, the first line with its links cut to ids, the question a 決定
  answers, a correction or replacement in its body), the open ACs (60 characters of
  each), and in full as well the comments of no type and the 等外部 declaration that
  holds (one that no longer holds: its line says why). 回報：開工／收到 are counted.

A thread with more comments than the main query read (comments(last:100)) is read back
by one more query (backfill-query, #804 決定 6913246451): the oldest totalCount-100 (100
at most) of each such thread in one call with aliases, merged by url. What is still
missing (more than 200, or the call not made or failed) is printed as 未查完 with the
range of comments not read; it is never taken as complete. The comments read back are
for this page only: the questions and the slots are judged on the main answer.

#1 (range 2): its latest 10 comments by the first line; in full the ones that say
待使用者 on it or have no coordinator mark, unless #1's body (read at takeover) names
them. 部署： and 回報：統籌 session 更換 are counted only.

  backfill-query       stdin is the main answer; prints the query for the threads with
                       comments not read, or nothing when there is none. Exit 0.
  page NOW WORKTREES STATUS LOGS BACKFILL NOTE [N...]
                       stdin is the main answer, or nothing when GitHub was not read.
                       NOW is epoch seconds; WORKTREES and STATUS are the files slots.py
                       report reads ("" when git could not list); LOGS is <data>/logs;
                       BACKFILL the backfill answer's file ("" when no call was made);
                       NOTE why it was not made or failed ("" when it was not needed or
                       read); N the Issue or PR numbers whose full sections to print
                       instead of the index. Prints the page, its last line its size in
                       bytes. Exit 0; 64 bad arguments.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import commitments
import slots
from coordinator_json import (
    GOVERNANCE_ISSUE,
    PAGE,
    coordinator_comment,
    get,
    one_line,
    without_mark,
)

TAIPEI = timezone(timedelta(hours=8))
REPO_URL = "https://github.com/YiCheng0608/stock-lab"
AC_WIDTH = 60
LINE_WIDTH = 140
REPORT_WIDTH = 90
GOVERNANCE_RECENT = 10
DAY = 24 * 3600
BOM = chr(0xFEFF)

_TYPE = re.compile(r"\s*(?:提問|決定|回報|統籌承諾|部署|review)[：:（(]", re.IGNORECASE)
_QUESTION = re.compile(r"\s*提問[：:]")
_DECISION = re.compile(r"\s*決定[：:（(]")
_PROMISE = re.compile(r"\s*統籌承諾[：:]")
_COUNTED = re.compile(r"\s*回報[：:]\s*(?:開工|收到)")
_REPORT = re.compile(r"\s*回報[：:]")
_CORRECTS = re.compile(r"更正|取代|撤回")
_BARE_ID = re.compile(r"(?<![\d/-])(\d{10})(?!\d)")
_GOV_COUNTED = re.compile(r"\s*(?:部署[：:]|回報[：:]\s*統籌 ?session 更換)")
# What the coordinator is to do (#804 決定 6914347432): a limit (不可, 不要) is read
# before acting on the thread instead.
_KEYWORDS = ("由統籌", "統籌會", "統籌在", "我會")
_TODO_TYPES = re.compile(r"\s*(?:決定|統籌承諾|review)[：:（(]", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[。；;])")
_COMMENT_ID = re.compile(r"issuecomment-(\d+)")
_CLOSES = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")
_AC = re.compile(
    r"^\s*[-*] \[( |x|X)\] (?:\*\*)?(AC-\d+(?:（[^）\n]*）)?)(?:\*\*)?[：:]\s*(.*)"
)
# Lines of a comment that hold no sentence of the coordinator's own: tables, headings,
# quotes, code fences, HTML comments.
_NOT_PROSE = re.compile(r"\s*(?:\||#|>|```|<!--)")
_MD_LINK = re.compile(r"\[([^\]\n]*)\]\((https?://[^)\s]+)\)")
# A bare url ends at a space, a bracket or full-width punctuation (（42）、 ends a url
# in a Chinese sentence).
_URL = re.compile(r"https?://[^\s)>\]`（）「」，。；：、]+")
_GH_COMMENT = re.compile(
    re.escape(REPO_URL) + r"/(?:issues|pull)/(\d+)(?:/[\w/]*)?#issuecomment-(\d+)"
)
_GH_THREAD = re.compile(
    re.escape(REPO_URL) + r"/(?:issues|pull)/(\d+)(?:[/#?][^\s]*)?$"
)
_GH_RUN = re.compile(re.escape(REPO_URL) + r"/actions/runs/(\d+)")


# --- the backfill (#804 決定 6913246451) --------------------------------------------


def _threads(repo: dict):
    for kind in ("issues", "pullRequests"):
        for thread in (repo.get(kind) or {}).get("nodes") or []:
            if isinstance(thread, dict):
                yield kind, thread


def _short_of(thread: dict) -> int:
    """How many of the thread's oldest comments the main answer did not hold."""
    comments = thread.get("comments") or {}
    return max((comments.get("totalCount") or 0) - len(comments.get("nodes") or []), 0)


def backfill_query(doc) -> str:
    repo = get(doc, "data.repository") or {}
    parts = []
    for _, thread in _threads(repo):
        number = thread.get("number")
        if number == GOVERNANCE_ISSUE or thread.get("state") not in (None, "OPEN"):
            continue
        short = _short_of(thread)
        if short <= 0 or not isinstance(number, int):
            continue
        comments = f"comments(first:{min(short, PAGE)}){{nodes{{url createdAt body}}}}"
        parts.append(
            f"t{number}:issueOrPullRequest(number:{number}){{"
            f"... on Issue{{{comments}}} ... on PullRequest{{{comments}}}}}"
        )
    if not parts:
        return ""
    return (
        "query OverviewBackfill($owner:String!,$name:String!){"
        "repository(owner:$owner,name:$name){" + " ".join(parts) + "}}"
    )


def merged_comments(thread: dict, backfill, note: str) -> tuple[list[dict], str]:
    """(the thread's comments, oldest first, backfilled ones merged by url; what is still
    not read, or "")."""
    comments = thread.get("comments") or {}
    main = [c for c in comments.get("nodes") or [] if isinstance(c, dict)]
    total = comments.get("totalCount") or len(main)
    if total <= len(main):
        return main, ""
    old = None
    if backfill is not None:
        old = get(backfill, f"data.repository.t{thread.get('number')}.comments.nodes")
    if not isinstance(old, list):
        why = note or "補查的回應沒有這張單"
        return main, f"未查完：共 {total} 則，缺第 1～{total - len(main)} 則（{why}）"
    seen, out = set(), []
    for c in [c for c in old if isinstance(c, dict)] + main:
        key = c.get("url") or id(c)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    out.sort(key=lambda c: c.get("createdAt") or "")
    first, last = len(old) + 1, total - len(main)
    if len(out) >= total or first > last:
        return out, ""
    return (
        out,
        f"未查完：共 {total} 則，缺第 {first}～{last} 則（只補得到最舊 {PAGE} 則）",
    )


# --- text -----------------------------------------------------------------------------


def _ref(url: str, number) -> str | None:
    """A stock-lab URL as the header's rule writes it, or None for another URL."""
    m = _GH_COMMENT.match(url)
    if m:
        n, cid = int(m.group(1)), m.group(2)
        return cid if n == number else f"#{n} {cid}"
    m = _GH_RUN.match(url)
    if m:
        return f"run {m.group(1)}"
    m = _GH_THREAD.match(url)
    if m:
        return f"#{m.group(1)}"
    return None


def short_links(text: str, number) -> str:
    """Links cut to ids: [label](url) is the label, with the url's id when the label
    lacks it; a bare stock-lab url is its id (#n <id> for another thread's comment)."""

    def md(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        ref = _ref(url, number)
        if ref is None:
            return label
        tail = ref.split()[-1]
        return label if tail in label else f"{label} {ref}".strip()

    def bare(m: re.Match) -> str:
        url = m.group(0)
        return _ref(url, number) or url

    return _URL.sub(bare, _MD_LINK.sub(md, text or ""))


def _first_line(body: str) -> str:
    return next(
        (ln for ln in without_mark(body).lstrip(BOM).splitlines() if ln.strip()),
        "",
    )


def _cid(comment: dict) -> str:
    return (_COMMENT_ID.findall(comment.get("url") or "") or ["?"])[0]


def _when(stamp: str) -> str:
    try:
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return "時間不明"
    return at.astimezone(TAIPEI).strftime("%m-%d %H:%M")


def _who(body: str) -> str:
    return "統" if coordinator_comment(body) else "工"


def _full(body: str, number) -> list[str]:
    text = short_links(without_mark(body).lstrip(BOM).strip(), number)
    return ["      > " + ln if ln.strip() else "      >" for ln in text.splitlines()]


def _todo(body: str, number) -> list[str]:
    """The sentences past the first line that say the coordinator is to do something."""
    lines = without_mark(body).lstrip(BOM).strip().splitlines()[1:]
    out, fenced = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or _NOT_PROSE.match(line):
            continue
        for sentence in _SENTENCE.split(line):
            if any(k in sentence for k in _KEYWORDS):
                out.append(one_line(short_links(sentence, number), LINE_WIDTH))
    return out


def _corrections(body: str, cid: str) -> list[str]:
    """The comment ids a line past the first one corrects or replaces (#804 AC-3: #702
    6900881313 corrected 6893948126 in its body only), or ["?"] when such a line names
    none. The first line's own 更正 <id> is read there already."""
    out = []
    for line in without_mark(body).lstrip(BOM).strip().splitlines()[1:]:
        if not _CORRECTS.search(line):
            continue
        ids = [
            x for x in _COMMENT_ID.findall(line) + _BARE_ID.findall(line) if x != cid
        ]
        out += ids or ["?"]
    return list(dict.fromkeys(out))


# --- the page -------------------------------------------------------------------------


def _sessions(logs: str) -> dict[int, dict]:
    """The newest session state of each issue (turn_hook.cjs)."""
    folder = os.path.join(logs, "sessions")
    newest: dict[int, dict] = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return newest
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            continue
        issue = state.get("issue") if isinstance(state, dict) else None
        if not isinstance(issue, int):
            continue
        at = max(str(state.get("ended_at") or ""), str(state.get("started_at") or ""))
        state["_at"] = at
        if issue not in newest or at > newest[issue]["_at"]:
            newest[issue] = state
    return newest


def _session_line(state: dict) -> str:
    sid = str(state.get("session_id") or "?")[:8]
    what = state.get("state") or "?"
    parts = [f"工程師 session：{sid} {what}（{_when(state['_at'])}）"]
    if what == "stopped":
        parts.append("有留言" if state.get("commented") else "這回合沒有留言")
        if state.get("background_tasks"):
            parts.append(f"背景工作 {state['background_tasks']}")
        if state.get("last_message"):
            parts.append("最後：" + one_line(state["last_message"], 80))
    elif what in ("failed", "ended"):
        detail = state.get("error") or state.get("reason") or state.get("detail")
        if detail:
            parts.append(one_line(str(detail), 80))
    return "；".join(parts)


def _acs(body: str) -> tuple[list[str], int]:
    open_, total = [], 0
    for line in (body or "").splitlines():
        m = _AC.match(line)
        if not m:
            continue
        total += 1
        if m.group(1) == " ":
            text = " ".join(m.group(3).split())
            cut = text if len(text) <= AC_WIDTH else text[:AC_WIDTH] + "…"
            open_.append(f"{m.group(2)}：{cut}")
    return open_, total


def _depends(body: str, number, open_numbers: set[int] | None) -> list[str]:
    out = []
    for line in (body or "").splitlines():
        m = slots._DEPENDS.search(line)
        if not m:
            continue
        text = one_line(short_links(m.group(1), number), 120)
        if not text:
            continue
        waits = [
            n
            for n in slots.waited_refs(m.group(1))
            if n != number and (open_numbers is None or n in open_numbers)
        ]
        mark = ""
        if waits:
            known = "" if open_numbers is not None else "（open 與否未查完）"
            mark = f"［在等 {'、'.join(f'#{n}' for n in waits)}{known}］"
        out.append(f"  依賴：{text}{mark}")
    return out


def _linked_issue(pr: dict) -> int | None:
    m = _CLOSES.search(pr.get("body") or "")
    if m:
        return int(m.group(1))
    m = slots._TASK_BRANCH.match(pr.get("headRefName") or "")
    return int(m.group(1)) if m else None


class Page:
    """The index (numbers None: what a new coordinator reads) or the full sections of the
    threads NUMBERS (read before acting on one; #804 決定 6914347432)."""

    def __init__(
        self, doc, tasks, now: int, logs: str, backfill, note: str, numbers=None
    ):
        self.doc, self.tasks, self.now, self.logs = doc, tasks, now, logs
        self.backfill, self.note, self.numbers = backfill, note, numbers
        self.repo = get(doc, "data.repository") if doc is not None else None
        records, _ = commitments.read(logs)
        self.records = records
        self.promised = {
            cid
            for r in records
            if r["type"] == "add"
            for cid in _COMMENT_ID.findall(r.get("url") or "")
        }
        self.sessions = _sessions(logs)
        self.verdicts = {v.issue: v for v in slots.decide(doc, tasks, now)}
        self.lines: list[str] = []
        self.threads: dict[int, tuple[str, dict, list[dict], str]] = {}
        self.answered: set[str] = set()
        if self.repo:
            for kind, thread in _threads(self.repo):
                if thread.get("state") not in (None, "OPEN"):
                    continue
                comments, unread = merged_comments(thread, backfill, note)
                self.threads[thread.get("number")] = (kind, thread, comments, unread)
                if thread.get("number") == GOVERNANCE_ISSUE:
                    continue
                for c in comments:
                    body = c.get("body") or ""
                    if _DECISION.match(body.lstrip(BOM)):
                        self.answered.update(_COMMENT_ID.findall(body))

    def build(self) -> list[str]:
        out = self.lines
        stamp = datetime.fromtimestamp(self.now, TAIPEI).strftime("%Y-%m-%d %H:%M")
        if self.numbers is None:
            out.append(
                f"=== 現況頁：索引（{stamp} 台北；patrol.sh --overview，#804）==="
            )
            out.append(
                "本頁是索引，不是依據：對某張單動作前，先跑 patrol.sh --overview <單號> 看那張單的"
                "完整段落（每則留言一行、未勾 AC、內文更正），再照接手文讀原文"
                "（docs/COORDINATOR.md）。"
            )
        else:
            shown = " ".join(f"#{n}" for n in self.numbers)
            out.append(f"=== 現況頁：{shown} 的完整段落（{stamp} 台北；#804）===")
            out.append(
                "動作前照接手文讀那張單的本文與每一則 決定／統籌承諾／review 全文；"
                "本段只是索引。"
            )
        out.append(
            f"網址規則：留言 id <id> 是 {REPO_URL}/issues/<這張單>#issuecomment-<id>，"
            "「#n <id>」是 #n 的留言；#n 是 Issue 或 PR（/issues/<n> 兩者都開得到）；"
            f"run <id> 是 {REPO_URL}/actions/runs/<id>。"
        )
        out.append(
            "統＝帶統籌標記；工＝沒有標記（工程師、使用者或獨立 review）。"
            "「↩ id」是 決定 回覆的提問。"
        )
        if not self.repo:
            out.append("現況頁：未查完（GitHub 沒讀到），只印本機的部分")
        else:
            for kind, label in (("issues", "Issue"), ("pullRequests", "PR")):
                conn = self.repo.get(kind) or {}
                nodes = conn.get("nodes") or []
                if (conn.get("totalCount") or 0) > len(nodes):
                    out.append(
                        f"未查完：open {label} {conn['totalCount']} 個，只讀了 {len(nodes)} 個"
                    )
            if self.numbers is None:
                self._threads_section()
                self._governance()
            else:
                open_numbers = self._open_numbers()
                for n in self.numbers:
                    if n == GOVERNANCE_ISSUE and n in self.threads:
                        self._governance()
                    elif n in self.threads:
                        self._thread(n, open_numbers, detail=True)
                    else:
                        out += ["", f"## #{n}：不是 open 的 Issue／PR（或這次沒讀到）"]
        if self.numbers is None:
            self._kept()
        return out

    def _open_numbers(self) -> set[int] | None:
        repo = self.repo or {}
        if any(
            (repo.get(k) or {}).get("totalCount", 0)
            > len((repo.get(k) or {}).get("nodes") or [])
            for k in ("issues", "pullRequests")
        ):
            return None
        return set(self.threads)

    def _threads_section(self) -> None:
        issues = sorted(
            n
            for n, t in self.threads.items()
            if t[0] == "issues" and n != GOVERNANCE_ISSUE
        )
        prs = sorted(n for n, t in self.threads.items() if t[0] == "pullRequests")
        by_issue: dict[int, list[int]] = {}
        loose = []
        for n in prs:
            linked = _linked_issue(self.threads[n][1])
            if linked in issues:
                by_issue.setdefault(linked, []).append(n)
            else:
                loose.append(n)
        open_numbers = self._open_numbers()
        for n in issues:
            self._thread(n, open_numbers)
            for p in by_issue.get(n, []):
                self._thread(p, open_numbers)
        for p in loose:
            self._thread(p, open_numbers)

    def _thread(self, number: int, open_numbers, detail: bool = False) -> None:
        kind, thread, comments, unread = self.threads[number]
        out = self.lines
        is_pr = kind == "pullRequests"
        milestone = get(thread, "milestone.title") or "無 milestone"
        label = "PR" if is_pr else "Issue"
        extra = ""
        if is_pr:
            linked = _linked_issue(thread)
            extra = f"；Closes #{linked}" if linked else "；沒連到 Issue"
        body = thread.get("body") or ""
        acs, ac_total = _acs(body) if not is_pr else ([], 0)
        if ac_total and not detail:
            extra += f"；未勾 AC {len(acs)}／{ac_total}"
        total = (thread.get("comments") or {}).get("totalCount") or len(comments)
        out.append("")
        out.append(
            f"## #{number} {one_line(thread.get('title') or '（沒讀到標題）', 70)}"
            f"（{label}；{milestone}；留言 {total} 則{extra}）"
        )
        if not is_pr:
            out.extend(_depends(body, number, open_numbers))
            verdict = self.verdicts.get(number)
            if verdict is None:
                out.append("  名額：追蹤／待辦（沒有 task worktree）")
            else:
                link = f" {short_links(verdict.link, number)}" if verdict.link else ""
                out.append(
                    f"  名額：{'算' if verdict.counted else '不算'}：{short_links(verdict.reason, number)}{link}"
                )
            if number in self.sessions:
                out.append("  " + _session_line(self.sessions[number]))
            if ac_total and detail:
                out.append(f"  未勾 AC {len(acs)}／{ac_total}：")
                out.extend(f"    {a}" for a in acs)
        if unread:
            out.append(f"  {unread}")
        self._comments(number, comments, detail)

    def _external(self, number: int, comments: list[dict]):
        """(index of the latest 等外部 declaration or None, Verdict or why it fails)."""
        at = None
        for i, c in enumerate(comments):
            if slots._EXTERNAL.match((c.get("body") or "").lstrip(BOM)):
                at = i
        if at is None:
            return None, None
        worktrees = (self.tasks or {}).get(number, [])
        verdict = slots.waits_external(
            {"comments": {"nodes": comments}}, worktrees, self.now
        )
        return at, verdict

    def _comments(self, number: int, comments: list[dict], detail: bool) -> None:
        out = self.lines
        ext_at, ext = self._external(number, comments)
        full, todo, untyped, external = [], [], [], ""
        counted, counted_last = 0, ""
        lines = []
        for i, c in enumerate(comments):
            body = (c.get("body") or "").lstrip(BOM)
            cid = _cid(c)
            first = _first_line(body)
            if _COUNTED.match(body):
                counted += 1
                counted_last = f"{_when(c.get('createdAt'))} {cid}"
                continue
            # A 回報 (progress, done, PR opened) needs no action: a shorter line.
            width = REPORT_WIDTH if _REPORT.match(body) else LINE_WIDTH
            line = (
                f"    {_when(c.get('createdAt'))} {_who(body)} {cid} "
                f"{one_line(short_links(first, number), width)}"
            )
            if _DECISION.match(body):
                answers = [
                    x for x in dict.fromkeys(_COMMENT_ID.findall(body)) if x != cid
                ][:3]
                if answers:
                    line += " ↩ " + "、".join(answers)
            corrected = _corrections(body, cid)
            if corrected:
                line += f" ［內文更正或取代：{'、'.join(corrected)}］"
            why = ""
            if _QUESTION.match(body) and cid not in self.answered:
                why = "未回覆的提問"
            elif not _TYPE.match(body):
                why = "沒有類型的留言"
                untyped.append(cid)
            elif _PROMISE.match(body) and cid not in self.promised:
                why = "不在承諾檔的統籌承諾"
            if i == ext_at:
                if isinstance(ext, slots.Verdict):
                    if detail:
                        why = why or f"等外部宣告（仍有效，{ext.reason}）"
                    else:
                        # The index: the declaration on one line (its first line names
                        # the event and the time); in full with --overview <n>.
                        external = f"  等外部宣告（仍有效）：{line.strip()}"
                else:
                    line += f"（等外部宣告已失效：{short_links(str(ext), number)}）"
            if why and (detail or why != "沒有類型的留言"):
                line += f" ［全文見下：{why}］"
                full.append((why, cid, body))
            lines.append(line)
            # A 回報 of the coordinator often pastes drafts and answers (#794): only the
            # decisions, promises and reviews say what the coordinator is to do.
            if coordinator_comment(body) and _TODO_TYPES.match(body):
                todo += [f"    {cid}：{s}" for s in _todo(body, number)]
        if counted:
            out.append(f"  回報：開工／收到 {counted} 則（最後 {counted_last}）")
        if detail:
            if lines:
                out.append("  留言：")
                out.extend(lines)
        elif lines:
            if external and external.endswith(lines[-1].strip()):
                out.append(external)
            else:
                out.append("  最後一則：" + lines[-1].strip())
                if external:
                    out.append(external)
            if untyped:
                out.append(
                    f"  沒有類型的留言 {len(untyped)} 則：{'、'.join(untyped)}"
                    f"（全文：patrol.sh --overview {number}）"
                )
        for why, cid, body in full:
            out.append(f"  全文［{why}］{cid}：")
            out.extend(_full(body, number))
        if todo:
            out.append("  統籌要做的事（統籌留言內文，逐句，對照承諾檔）：")
            out.extend(todo)

    def _governance(self) -> None:
        """#1's latest 10 by the first line; in full the 待使用者 ones and those without
        the mark. Its 決定 are kept in the body (patrol exit 12), read at takeover."""
        out = self.lines
        out.append("")
        entry = self.threads.get(GOVERNANCE_ISSUE)
        if entry is None:
            out.append("## #1 最近留言：未查完（沒讀到 #1）")
            return
        _, _, comments, _ = entry
        recent = comments[-GOVERNANCE_RECENT:]
        out.append(
            f"## #1 最近 {len(recent)} 則留言（id 已在 #1 本文的只印第一行：接手時讀本文）"
        )
        # #1's body, read at takeover (the handover text): a comment it already names is
        # not printed again in full.
        in_body = set(
            _BARE_ID.findall((self.repo.get("governance") or {}).get("body") or "")
        )
        skipped: dict[str, int] = {}
        for c in recent:
            body = (c.get("body") or "").lstrip(BOM)
            cid = _cid(c)
            first = _first_line(body)
            if _GOV_COUNTED.match(body):
                key = "部署" if body.lstrip().startswith("部署") else "session 更換"
                skipped[key] = skipped.get(key, 0) + 1
                continue
            head = f"    {_when(c.get('createdAt'))} {_who(body)} {cid}"
            if cid not in in_body and (
                "待使用者" in first or not coordinator_comment(body)
            ):
                # The full text holds the first line.
                out.append(f"{head}（全文）：")
                out.extend(_full(body, GOVERNANCE_ISSUE))
            else:
                out.append(
                    f"{head} {one_line(short_links(first, GOVERNANCE_ISSUE), LINE_WIDTH)}"
                )
        if skipped:
            out.append(
                "  只計數："
                + "、".join(f"{k} {v} 則" for k, v in sorted(skipped.items()))
            )

    def _kept(self) -> None:
        out = self.lines
        added: dict[str, dict] = {}
        for r in self.records:
            if r["type"] == "add":
                added.setdefault(r["id"], r)
        done = []
        for r in self.records:
            if r["type"] != "done":
                continue
            try:
                at = commitments._epoch(r.get("at") or "")
            except ValueError:
                continue
            if self.now - at <= DAY:
                done.append((r.get("at"), r))
        out.append("")
        out.append(f"## 最近 24 小時兌現的承諾：{len(done)} 則")
        for at, r in sorted(done, key=lambda x: x[0]):
            a = added.get(r["id"]) or {}
            promise = short_links(a.get("url") or "", None) or "?"
            kept = short_links(r.get("url") or "", None) or "沒有留言"
            issue = f"#{a['issue']}" if a.get("issue") else "#?"
            out.append(
                f"    [{r['id']}] {_when(at)} {issue} {one_line(a.get('text') or '（承諾檔沒有這筆 add）', 60)}"
                f"（承諾 {promise}；兌現 {kept}）"
            )


def page(
    doc,
    tasks,
    now: int,
    logs: str,
    backfill,
    note: str,
    listed: bool = True,
    numbers=None,
) -> list[str]:
    lines = Page(doc, tasks, now, logs, backfill, note, numbers).build()
    if not listed:
        lines.insert(
            1, "名額：判定不了（git worktree list 失敗，讀不到 task worktree）"
        )
    text = "\n".join(lines) + "\n"
    size = len(text.encode("utf-8"))
    tail = f"=== 現況頁結束：{size:,} 位元組（不含本行）==="
    return lines + [tail]


def _json(text: str | None):
    if not text or not text.strip():
        return None
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")
    if argv[:1] == ["backfill-query"] and len(argv) == 1:
        query = backfill_query(_json(sys.stdin.read()))
        if query:
            print(query)
        return 0
    numbers = [a.lstrip("#") for a in argv[7:]]
    if (
        len(argv) < 7
        or argv[0] != "page"
        or not argv[1].isdigit()
        or not all(n.isdigit() for n in numbers)
    ):
        print(__doc__, file=sys.stderr)
        return 64
    now, wt_path, status_path, logs, backfill_path, note = (
        int(argv[1]),
        argv[2],
        argv[3],
        argv[4],
        argv[5],
        argv[6],
    )
    doc = _json(sys.stdin.read())
    if doc is not None and get(doc, "data.repository") is None:
        doc = None
    porcelain = slots._read(wt_path) if wt_path else None
    status = (slots._read(status_path) if status_path else None) or ""
    tasks = slots.task_worktrees(porcelain or "", slots._status(status))
    backfill = None
    if backfill_path:
        try:
            backfill = _json(slots._read(backfill_path))
        except OSError:
            backfill = None
        if backfill is None and not note:
            note = "補查的回應讀不懂"
    lines = page(
        doc,
        tasks,
        now,
        logs,
        backfill,
        note,
        porcelain is not None,
        [int(n) for n in dict.fromkeys(numbers)] or None,
    )
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
