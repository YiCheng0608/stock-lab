"""JSON helper for the coordinator scripts dispatch.sh, close_task.sh, patrol.sh and monitor.sh (#282, #316).

Git Bash has no jq, so the scripts pipe orca and gh JSON through this file; event_queue.py
imports the PR helpers (latest_checks, check_state, pr_line) and the coordinator's comment
mark (coordinator_comment, without_mark; #440). Every
subcommand reads one JSON document on stdin and prints plain text; it exits 1 when the
value is missing or the condition is false, so a script can test the exit code.

  get PATH            value at a dotted path (a.b.0.c); objects and lists print as JSON
  ok                  exit 0 when the orca envelope has "ok": true
  satisfied           exit 0 when ok and a "satisfied": true sits anywhere under result
  stages              the send receipt's prompt stages, space separated
  repo-id KEY         id of the orca repo whose remote canonicalKey is KEY
  terminals PATH      "handle agent lastOutputAt" per terminal of the worktree at PATH
  worktrees PREFIX    "path<TAB>branch<TAB>id" per orca worktree on branch refs/heads/PREFIX*
  ci-state SHA        CI state of the target branch: "<state of SHA> <state of the newest run>"
  commit-ci SHA       state of SHA's latest CI run: the highest databaseId, since runs
                      created together (a cancelled duplicate) list in any order (#314)
  board               "itemId projectId fieldId optionId=name,..." of project 1 from the
                      issue query (item "-" and the issue node id last when the issue is
                      not on the board)
  questions NOW       one line per unanswered question (#401) in the open Issues and PRs
                      of the QUESTIONS_QUERY answer, oldest first; NOW is epoch seconds.
                      Lines start with "#"; a line starting with "未查完" says what was
                      not read (more than a page of threads or comments); exit 1 when
                      the answer has no data.repository (a GraphQL error)
  questions-query     the GraphQL query whose answer questions reads (no stdin)
  utf8 FILE           exit 0 when FILE is non-empty valid UTF-8 (no stdin)
  comment-body FILE   {"body": FILE's text with COORDINATOR_MARK as its last line}, the
                      request comment.sh posts (#440; no stdin); exit 1 when the text is
                      empty without the mark
  start-sessions      the session ids (UUIDs) the 回報：開工 comments of the owner, members
                      and collaborators (author_association) name, one per line,
                      first seen first (#472); stdin is `gh api --paginate` of an Issue's
                      comments (pages of JSON arrays one after another); exit 1 when it
                      is not that
  coordinator-row ROW {"body": ...} of the Issue on stdin (gh api repos/<repo>/issues/1)
                      with the one list line under "## 現任統籌" replaced by ROW and
                      every other character as it was (take_over.sh, #534); exit 1 with
                      the reason on stderr when there is no such section, or it holds no
                      list line or more than one
  same-body FILE      exit 0 when the Issue on stdin has the body of FILE ({"body": ...},
                      what coordinator-row printed): the read-back of the edit
  within A B          "yes" when A is B or under B, else "no" (no stdin)
  plain PATH          "yes" when PATH as written is PATH as resolved: no junction, symlink
                      or 8.3 short name on the way (no stdin)
  guard PATH [--residual] [--home H] [--data D]... [--root R]...
                      why close_task.sh must not delete PATH, or nothing (no stdin)
  cbm-result          the answer of one codebase-memory CLI call (stdin: its whole output,
                      log lines and all) as JSON: structuredContent, else the text; exit 1
                      with the reason on stderr when there is no JSON or isError (#704)
  cbm-chunks PROJECT  check_index_coverage arguments, 128 paths a line (stdin: paths)
  cbm-verdict ROOT PROJECT
                      the index verdict of each path (index_verdict) under ROOT, one
                      "verdict<TAB>reason<TAB>freshness<TAB>path" line each; stdin is
                      NUL-terminated parts: the paths, query_graph's File list, then each
                      check_index_coverage answer (cbm-result output). Exit 0 none stale,
                      1 some stale, 2 an answer could not be read (reason on stderr)

Paths given to within and guard are native (on Windows, `cygpath -m` of what bash has).
Each is compared in two forms: as written (absolute, normalised) and as the file system
resolves it (os.path.realpath: junctions and symlinks followed, 8.3 short names
expanded), so neither a link in the middle of a path nor a short name hides a
protected directory (#283 review B1, B2).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import PurePosixPath


def _load():
    try:
        return json.load(sys.stdin)
    except ValueError:
        return None


def _walk(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)


def _norm(path: str) -> str:
    """Compare Windows and MSYS spellings of one path: c:\\a\\b, C:/a/b and /c/a/b."""
    p = path.replace("\\", "/").rstrip("/")
    if len(p) > 2 and p[0] == "/" and p[2:3] in ("/", "") and p[1].isalpha():
        p = p[1] + ":" + p[2:]
    return str(PurePosixPath(p)).lower()


def _forms(path: str) -> tuple[str, str]:
    """(as written, as resolved), both case-normalised."""
    written = os.path.normcase(os.path.abspath(path))
    return written, os.path.normcase(os.path.realpath(path))


def _inside(a: str, b: str) -> bool:
    """a is b or under b; both from _forms."""
    a, b = (p if p.endswith(os.sep) else p + os.sep for p in (a, b))
    return a.startswith(b)


def _overlaps(a: str, b: str) -> bool:
    return any(_inside(x, y) or _inside(y, x) for x in _forms(a) for y in _forms(b))


def _git_inside(top: str) -> str:
    """The first .git under top, without entering a junction or symlink, or ""."""
    stack = [top]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if entry.name == ".git":
                return entry.path
            if entry.is_junction() or entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
    return ""


def guard(
    path: str, residual: bool, home: list[str], data: list[str], roots: list[str]
):
    # Local and absolute only: no UNC or device path (\\server\share, //server/share,
    # \\?\…, \\.\…), nothing drive- or directory-relative (#283 review M1).
    local = (
        re.match(r"[A-Za-z]:[\\/]", path) if os.name == "nt" else path.startswith("/")
    )
    if not local or path.startswith(("\\", "//")):
        return "不是本機的絕對路徑（UNC、裝置路徑或相對路徑），請改用 C:/… 或 /… 的實際路徑"
    written, real = _forms(path)
    if written != real:
        return f"經過 junction／symlink 或用了短檔名（實際位置 {real}），請改用實際路徑"
    if "stock-lab-data" in written.replace("\\", "/").split("/"):
        return "在 stock-lab-data 之下"
    for d in data:
        if _overlaps(path, d):
            return f"是資料目錄或與它重疊（{d}）"
    if os.path.dirname(written) == written:
        return "是根目錄或磁碟根目錄"
    for h in home:
        if any(_inside(x, y) for x in _forms(h) for y in _forms(path)):
            return "是 $HOME 或它的上層"
    for r in roots:
        if _overlaps(path, r):
            return f"是 git checkout 或與它重疊（{r}）"
    if residual:
        return ""
    d = real
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return f"位於 git repo 之內（{d}）"
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    # The path names the repo to look at: a fake one a failed pytest run left in its
    # basetemp is cleared by the next green run on that basetemp (#290).
    found = _git_inside(real) if os.path.isdir(real) else ""
    if found:
        return f"裡面有 .git（{found}）"
    return ""


def _guard_args(args: list[str]) -> int:
    path, residual, lists = args[0], False, {"--home": [], "--data": [], "--root": []}
    rest = iter(args[1:])
    for flag in rest:
        if flag == "--residual":
            residual = True
        else:
            lists[flag].append(next(rest))
    print(guard(path, residual, lists["--home"], lists["--data"], lists["--root"]))
    return 0


def get(doc, path: str):
    node = doc
    for part in path.split("."):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _print_value(value) -> int:
    if value is None:
        return 1
    if isinstance(value, bool):
        print("true" if value else "false")
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False))
    else:
        print(value)
    return 0


def one_line(text: str, width: int = 80) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= width else line[: width - 1] + "…"


# The last line of every comment the coordinator posts (comment.sh, #440): an HTML comment,
# so GitHub does not show it. The event monitor queues such a comment without waking the
# coordinator. Every session uses the same GitHub account, so the author tells nothing; a
# comment without this line (an engineer's, the user's) wakes as before. It goes last
# because the comment type (提問：, 決定：, ...) is read from the first line.
COORDINATOR_MARK = "<!-- stock-lab:coordinator -->"


def coordinator_comment(body) -> bool:
    lines = (body or "").rstrip().splitlines()
    return bool(lines) and lines[-1].strip() == COORDINATOR_MARK


def without_mark(body) -> str:
    """The body as the reader sees it: the mark line taken off."""
    if not coordinator_comment(body):
        return body or ""
    return body.rstrip().rsplit(COORDINATOR_MARK, 1)[0].rstrip()


def marked_body(text: str) -> str:
    text = text.lstrip("\ufeff").rstrip()
    return text if coordinator_comment(text) else f"{text}\n\n{COORDINATOR_MARK}"


# The section of the governance Issue #1 that names the coordinator (docs/COORDINATOR.md):
# its heading and one list line under it, which take_over.sh replaces (#534).
COORDINATOR_HEADING = "## 現任統籌"


def replace_coordinator_row(body: str, row: str) -> str:
    """BODY with the one list line under COORDINATOR_HEADING replaced by ROW.

    Lines are split with their endings kept (CRLF, LF or none on the last one), so every
    other byte, the replaced line's own ending included, stays as it was. Raises
    ValueError with the reason when the section is missing, holds no list line or more
    than one (nothing is guessed).
    """
    if "\n" in row or "\r" in row or not row.startswith("- "):
        raise ValueError("新的一列要以 '- ' 開頭、只有一行")
    # Not str.splitlines: it also splits at form feed, NEL, LINE SEPARATOR (U+2028) and the like, which a
    # list line may hold.
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z", body)
    if "".join(lines) != body:
        raise ValueError("#1 本文分行後接不回原文")
    heads = [i for i, ln in enumerate(lines) if ln.rstrip() == COORDINATOR_HEADING]
    if len(heads) != 1:
        raise ValueError(
            f"#1 本文的「{COORDINATOR_HEADING}」標題有 {len(heads)} 個，要剛好 1 個"
        )
    rows = []
    for i in range(heads[0] + 1, len(lines)):
        if lines[i].startswith("#"):
            break
        if lines[i].startswith("- "):
            rows.append(i)
    if len(rows) != 1:
        raise ValueError(
            f"「{COORDINATOR_HEADING}」底下有 {len(rows)} 列清單，要剛好 1 列"
        )
    line = lines[rows[0]]
    content = line.rstrip("\r\n")
    lines[rows[0]] = row + line[len(content) :]
    return "".join(lines)


def latest_checks(rollup) -> list[dict]:
    """The newest run of each check in a statusCheckRollup."""
    # A newer run of the same check replaces the older one (a cancelled run or an
    # earlier failure of a re-run job must not decide the state, #286). A check
    # with no time yet is queued, so it counts as the newest; gh --json prints a
    # missing time as the zero time 0001-01-01T00:00:00Z, not null.
    latest: dict = {}
    for i, c in enumerate(rollup or []):
        key = (c.get("workflowName"), c.get("name") or c.get("context") or i)
        times = [c.get(k) for k in ("startedAt", "completedAt", "createdAt")]
        when = next((t for t in times if t and not t.startswith("0001-")), "~")
        if key not in latest or when >= latest[key][0]:
            latest[key] = (when, c)
    return [c for _, c in latest.values()]


def check_state(rollup) -> str:
    states = [
        (c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
        for c in latest_checks(rollup)
    ]
    if not states:
        return "none"
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT") for s in states):
        return "failure"
    if any(s in ("", "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED") for s in states):
        return "pending"
    return "success"


def pr_line(pr: dict) -> str:
    """One line per open PR: CI state of the newest runs, mergeStateStatus, labels."""
    labels = ",".join(lb["name"] for lb in pr.get("labels") or [])
    draft = " draft" if pr.get("isDraft") else ""
    return (
        f"PR #{pr['number']} ci={check_state(pr.get('statusCheckRollup'))}"
        f" merge={pr.get('mergeStateStatus') or '?'}{draft}"
        f" labels={labels or '-'} {one_line(pr.get('title', ''), 50)}"
    )


def _run_state(run) -> str:
    if run is None:
        return "missing"
    if run.get("status") != "completed":
        return "pending"
    return run.get("conclusion") or "unknown"


_THREAD = (
    "nodes{{number state comments(last:{n}){{totalCount nodes{{url createdAt body}}}}}}"
)
# One gh call reads every open Issue and PR with its latest comments (patrol.sh). Issues
# and PRs share the number space, so "#<number>" names either.
PAGE = 100
QUESTIONS_QUERY = (
    "query OpenQuestions($owner:String!,$name:String!){"
    "repository(owner:$owner,name:$name){"
    f"issues(states:OPEN,first:{PAGE}){{totalCount {_THREAD.format(n=PAGE)}}}"
    f"pullRequests(states:OPEN,first:{PAGE}){{totalCount {_THREAD.format(n=PAGE)}}}"
    "}}"
)
# docs/WORKFLOW.md 留言類型: the type is how the first line starts (blank lines,
# spaces and a BOM before it are fine; bold or a quote is not the type). A comment is
# known by the id in its url, the same #issuecomment-<id> a 決定 links to, so no
# GraphQL database id is read (GitHub deprecates databaseId for fullDatabaseId).
_QUESTION = re.compile(r"\s*提問[：:]")
_DECISION = re.compile(r"\s*決定[：:]")
_COMMENT_LINK = re.compile(r"issuecomment-(\d+)")
# The governance Issue keeps its own comment style (待使用者, decision records) and has
# more than a page of comments, so it is neither read nor reported as not read.
GOVERNANCE_ISSUE = 1


def _type(body: str, pattern: re.Pattern) -> bool:
    return bool(pattern.match((body or "").lstrip("\ufeff")))


def _epoch(stamp: str) -> int | None:
    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return int(when.replace(tzinfo=timezone.utc).timestamp())


def _elapsed(seconds: int) -> str:
    minutes = max(seconds, 0) // 60
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} 天 {hours} 小時"
    if hours:
        return f"{hours} 小時 {minutes} 分"
    return f"{minutes} 分"


def unanswered_questions(doc, now: int) -> list[str]:
    """Each 提問 comment with no 決定 comment linking to it (its #issuecomment-<id>).

    A 決定 on any open Issue or PR counts, so a question in the Issue may be answered in
    its PR. Closed Issues, closed or merged PRs and the governance Issue are left out.
    """
    repo = get(doc, "data.repository") or {}
    lines, notes, questions, answered = [], [], [], set()
    for kind, label in (("issues", "Issue"), ("pullRequests", "PR")):
        connection = repo.get(kind) or {}
        threads = connection.get("nodes") or []
        if (connection.get("totalCount") or 0) > len(threads):
            notes.append(
                f"未查完：open {label} {connection['totalCount']} 個，只讀了 {len(threads)} 個"
            )
        for thread in threads:
            if thread.get("state") != "OPEN" or (
                kind == "issues" and thread.get("number") == GOVERNANCE_ISSUE
            ):
                continue
            comments = thread.get("comments") or {}
            nodes = comments.get("nodes") or []
            if (comments.get("totalCount") or 0) > len(nodes):
                notes.append(
                    f"未查完：#{thread['number']} 有 {comments['totalCount']} 則留言，"
                    f"只讀了最新 {len(nodes)} 則"
                )
            for c in nodes:
                body = c.get("body") or ""
                if _type(body, _DECISION):
                    answered.update(_COMMENT_LINK.findall(body))
                elif _type(body, _QUESTION):
                    questions.append((thread["number"], c))
    for number, c in sorted(questions, key=lambda q: q[1].get("createdAt") or ""):
        if set(_COMMENT_LINK.findall(c.get("url") or "")) & answered:
            continue
        created = _epoch(c.get("createdAt"))
        age = _elapsed(now - created) if created is not None else "時間不明"
        lines.append(f"#{number} 經過 {age} {c.get('url', '')}")
    return lines + notes


# An engineer's 回報：開工 (docs/WORKFLOW.md 任務流程第 2 步) names the session on a line
# "- session：`<uuid>`", at times with the model after it ("`<uuid>`（claude-opus-5-5）");
# close_task.sh deletes that session's Claude Code scratchpad (#472). Only a whole UUID is
# taken: it becomes a directory name, so nothing else may reach a path.
_START = re.compile(r"\s*回報[：:]\s*開工")
_SESSION_LINE = re.compile(
    r"^\s*[-*]\s*session\s*[：:]\s*`?"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"(?![0-9A-Za-z-])",
    re.M,
)


def _pages(text: str) -> list | None:
    """The comments of `gh api --paginate`: one JSON array per page, back to back."""
    decoder, comments, at = json.JSONDecoder(), [], 0
    while True:
        while at < len(text) and text[at].isspace():
            at += 1
        if at == len(text):
            return comments
        try:
            page, at = decoder.raw_decode(text, at)
        except ValueError:
            return None
        if not isinstance(page, list):
            return None
        comments += page


# The repo is public: anyone can post a 回報：開工 naming another task's live session (the
# ids are public on every Issue). Every session posts as the repo owner, so only comments
# whose author is the owner or a member or collaborator count (PR #485 review).
_TRUSTED_AUTHORS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def start_sessions(comments: list) -> list[str]:
    seen: list[str] = []
    for c in comments:
        if (
            not isinstance(c, dict)
            or c.get("author_association") not in _TRUSTED_AUTHORS
        ):
            continue
        body = c.get("body") or ""
        if not _type(body, _START) or coordinator_comment(body):
            continue
        for sid in _SESSION_LINE.findall(body):
            if sid.lower() not in seen:
                seen.append(sid.lower())
    return seen


def _options(field) -> str:
    return ",".join(
        f"{o['id']}={o['name']}" for o in (field or {}).get("options") or []
    )


# --- codebase-memory master index (#704; coordinator_lib.sh cbm_*) -------------------
# The same-engine CLI prints the daemon's log lines (level=..., hint: ...) and then one
# JSON envelope {"content": [{"type": "text", "text": ...}], "structuredContent": ...,
# "isError": ...}; query_graph has no structuredContent, its text is a table.
CBM_CHUNK = 128  # check_index_coverage takes at most 128 paths a call


def cbm_envelope(raw: str) -> dict:
    """The CLI's JSON envelope in RAW; ValueError with the reason when there is none."""
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue  # level=..., hint: ..., launcher messages
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and "content" in doc:
            return doc
    tail = " ".join(
        x for x in raw.splitlines()[-3:] if x.strip() and not x.startswith("level=")
    )
    raise ValueError(f"輸出裡沒有 JSON：{tail[:300]}")


def cbm_result(raw: str):
    """One CLI call's answer: structuredContent, else the text (JSON when it parses)."""
    doc = cbm_envelope(raw)
    texts = [
        c.get("text", "")
        for c in doc.get("content") or []
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    if doc.get("isError") is True:
        raise ValueError(f"isError：{' '.join(texts)[:500]}")
    if isinstance(doc.get("structuredContent"), dict):
        return doc["structuredContent"]
    if not texts:
        raise ValueError("回答沒有內容")
    try:
        return json.loads(texts[0])
    except ValueError:
        return texts[0]


def cbm_table(text) -> list[str]:
    """The one column of a query_graph table ("rows: N  (cols: c)", "  value" lines,
    "total: N"); ValueError when the counts disagree or the table is empty."""
    if not isinstance(text, str):
        raise ValueError("query_graph 的回答不是表格文字")
    lines = text.splitlines()
    head = re.match(r"rows: (\d+)\b", lines[0]) if lines else None
    total = re.fullmatch(r"total: (\d+)", lines[-1].strip()) if lines else None
    if not head or not total:
        raise ValueError(f"query_graph 的表格讀不懂：{text[:200]}")
    values = [x[2:] if x.startswith("  ") else x for x in lines[1:-1] if x.strip()]
    values = [json.loads(v) if v.startswith('"') else v for v in values]
    if not values or not (len(values) == int(head.group(1)) == int(total.group(1))):
        raise ValueError(
            f"query_graph 的列數不一致或是空的：rows {head.group(1)}、"
            f"total {total.group(1)}、讀到 {len(values)}"
        )
    return values


def _suffix_key(path: str) -> str:
    """A file type as the engine takes it: the extension, or the whole name of a file
    without one (Dockerfile, .gitignore)."""
    name = PurePosixPath(path).name
    suffix = PurePosixPath(name).suffix
    return suffix.lower() if suffix else name


def _utc_epoch(stamp) -> int:
    if not isinstance(stamp, str) or not stamp:
        raise ValueError("回答沒有 indexed_at")
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"indexed_at 解析不出時間：{stamp}") from None
    if moment.tzinfo is None:
        raise ValueError(f"indexed_at 沒有時區：{stamp}")
    return int(moment.timestamp())


def index_verdict(
    path: str,
    entry: dict | None,
    tracked: set[str],
    tracked_types: set[str],
    indexed_at: int,
    root: str,
) -> tuple[str, str]:
    """(verdict, reason) of one path: stale, ok, or skip (left out). The rules (#704,
    decisions 6875002208, 6875031116; docs/WORKFLOW.md 程式索引):

    1. not a file in the checkout (deleted) -> skip deleted
    2. status "excluded" (.gitignore, .cbmignore, an ignored suffix) -> skip excluded
    3. freshness "missing" for a file that is there -> stale missing
    4. a file the engine records (a File node): mtime later than indexed_at -> stale
       mtime, else ok
    5. not recorded, and the engine records another file of its type -> stale not_tracked
    6. not recorded, and the engine records no file of its type -> skip unsupported

    freshness "metadata_changed" decides nothing: engine 0.10.8 on Windows answers it for
    unchanged files too. A path the answer leaves out is a ValueError, never "ok".
    """
    full = os.path.join(root, path)
    if not os.path.isfile(full):
        return "skip", "deleted"
    if not isinstance(entry, dict):
        raise ValueError(f"check_index_coverage 沒有回 {path}")
    if entry.get("status") == "excluded":
        return "skip", "excluded"
    if entry.get("freshness") == "missing":
        return "stale", "missing"
    if path in tracked:
        if int(os.stat(full).st_mtime) > indexed_at:
            return "stale", "mtime"
        return "ok", "tracked"
    if _suffix_key(path) in tracked_types:
        return "stale", "not_tracked"
    return "skip", "unsupported"


def cbm_verdict(parts: list[str], root: str, project: str) -> tuple[list[str], bool]:
    """PARTS: the paths (one per line), query_graph's File list, then each
    check_index_coverage answer (all cbm_result JSON but the first). The report lines
    ("verdict<TAB>reason<TAB>freshness<TAB>path") and whether a path is stale;
    ValueError when an answer cannot be read."""
    if len(parts) < 3:
        raise ValueError(
            "cbm-verdict 要路徑、File 清單與至少一個 check_index_coverage 回答"
        )
    paths = [p for p in parts[0].splitlines() if p]
    tracked = set(cbm_table(json.loads(parts[1])))
    tracked_types = {_suffix_key(p) for p in tracked}
    entries: dict[str, dict] = {}
    stamps = []
    for text in parts[2:]:
        answer = json.loads(text)
        if not isinstance(answer, dict) or answer.get("project") != project:
            raise ValueError(f"check_index_coverage 回的 project 不是 {project}")
        stamps.append(_utc_epoch(answer.get("indexed_at")))
        for entry in answer.get("paths") or []:
            if isinstance(entry, dict) and isinstance(entry.get("requested_path"), str):
                entries[entry["requested_path"]] = entry
    indexed_at = min(stamps)
    lines, stale = [], False
    for path in paths:
        entry = entries.get(path)
        verdict, reason = index_verdict(
            path, entry, tracked, tracked_types, indexed_at, root
        )
        stale = stale or verdict == "stale"
        freshness = (entry or {}).get("freshness") or "-"
        lines.append(f"{verdict}\t{reason}\t{freshness}\t{path}")
    return lines, stale


def main(argv: list[str]) -> int:
    # Bash reads the output with $(...): no CRLF from a Windows Python.
    sys.stdout.reconfigure(newline="\n")
    if not argv:
        print(__doc__, file=sys.stderr)
        return 64
    command, args = argv[0], argv[1:]
    if command == "utf8":
        try:
            with open(args[0], "rb") as handle:
                text = handle.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return 1
        return 0 if text.strip() else 1
    if command == "comment-body":
        with open(args[0], encoding="utf-8") as handle:
            text = handle.read()
        if not without_mark(text.lstrip("\ufeff")).strip():
            print("本文除了統籌標記之外是空的", file=sys.stderr)
            return 1
        # ASCII JSON: nothing on the way to gh depends on the console's code page.
        print(json.dumps({"body": marked_body(text)}))
        return 0
    if command == "within":
        print(
            "yes"
            if any(_inside(a, b) for a in _forms(args[0]) for b in _forms(args[1]))
            else "no"
        )
        return 0
    if command == "plain":
        written, real = _forms(args[0])
        print("yes" if written == real else "no")
        return 0
    if command == "guard":
        return _guard_args(args)
    if command == "start-sessions":
        comments = _pages(sys.stdin.read())
        if comments is None:
            return 1
        for sid in start_sessions(comments):
            print(sid)
        return 0
    if command == "cbm-result":
        try:
            print(json.dumps(cbm_result(sys.stdin.read()), ensure_ascii=False))
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        return 0
    if command == "cbm-chunks":
        paths = [p for p in sys.stdin.read().splitlines() if p]
        for i in range(0, len(paths), CBM_CHUNK):
            chunk = {"project": args[0], "paths": paths[i : i + CBM_CHUNK]}
            print(json.dumps(chunk))
        return 0
    if command == "cbm-verdict":
        try:
            lines, stale = cbm_verdict(sys.stdin.read().split("\0")[:-1], *args[:2])
        except (ValueError, OSError) as error:
            print(error, file=sys.stderr)
            return 2
        for line in lines:
            print(line)
        return 1 if stale else 0
    if command == "questions-query":
        print(QUESTIONS_QUERY)
        return 0
    doc = _load()
    if doc is None:
        return 1
    if command == "coordinator-row":
        body = doc.get("body") if isinstance(doc, dict) else None
        if not isinstance(body, str):
            print("Issue 的回答沒有 body", file=sys.stderr)
            return 1
        try:
            new = replace_coordinator_row(body, args[0])
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        # ASCII JSON: nothing on the way to gh depends on the console's code page.
        print(json.dumps({"body": new}))
        return 0
    if command == "same-body":
        with open(args[0], encoding="utf-8") as handle:
            want = json.load(handle).get("body")
        body = doc.get("body") if isinstance(doc, dict) else None
        return 0 if isinstance(want, str) and body == want else 1
    if command == "get":
        return _print_value(get(doc, args[0]))
    if command == "ok":
        return 0 if isinstance(doc, dict) and doc.get("ok") is True else 1
    if command == "satisfied":
        if not (isinstance(doc, dict) and doc.get("ok") is True):
            return 1
        return 0 if any(v is True for v in _walk(doc.get("result"), "satisfied")) else 1
    if command == "stages":
        stages = get(doc, "result.send.prompt.stages") or []
        print(" ".join(str(s) for s in stages))
        return 0
    if command == "repo-id":
        for repo in get(doc, "result.repos") or []:
            if (repo.get("gitRemoteIdentity") or {}).get("canonicalKey") == args[0]:
                print(repo["id"])
                return 0
        return 1
    if command == "terminals":
        want = _norm(args[0])
        for t in get(doc, "result.terminals") or []:
            if _norm(t.get("worktreePath") or "") == want:
                agent = t.get("agentIdentity") or "-"
                print(f"{t['handle']} {agent} {t.get('lastOutputAt') or 0}")
        return 0
    if command == "worktrees":
        prefix = "refs/heads/" + args[0]
        for w in get(doc, "result.worktrees") or []:
            if (w.get("branch") or "").startswith(prefix):
                branch = w["branch"][len("refs/heads/") :]
                print(f"{w['path']}\t{branch}\t{w.get('id', '')}")
        return 0
    if command == "ci-state":
        runs = [r for r in doc if isinstance(r, dict)] if isinstance(doc, list) else []
        mine = next((r for r in runs if r.get("headSha") == args[0]), None)
        newest = runs[0] if runs else None
        print(_run_state(mine), _run_state(newest))
        return 0
    if command == "commit-ci":
        runs = [
            r
            for r in (doc if isinstance(doc, list) else [])
            if isinstance(r, dict) and r.get("headSha") == args[0]
        ]
        print(
            _run_state(max(runs, key=lambda r: r.get("databaseId") or 0, default=None))
        )
        return 0
    if command == "board":
        issue = get(doc, "data.repository.issue") or {}
        for item in get(issue, "projectItems.nodes") or []:
            project = item.get("project") or {}
            if project.get("number") != 1:
                continue
            field = project.get("field") or {}
            print(item["id"], project["id"], field.get("id", ""), _options(field))
            return 0
        project = get(doc, "data.user.projectV2") or {}
        field = project.get("field") or {}
        print(
            "-",
            project.get("id", ""),
            field.get("id", ""),
            _options(field),
            issue.get("id", ""),
        )
        return 0
    if command == "questions":
        if get(doc, "data.repository") is None:
            return 1
        for line in unanswered_questions(doc, int(args[0])):
            print(line)
        return 0
    print(f"unknown command: {command}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
