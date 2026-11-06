"""The coordinator's commitments file (Issue #534; docs/COORDINATOR.md 無人值守運作).

A 統籌承諾 (a promise to do something later: a check at a set time, a cleanup held back)
used to live in the comment and in a one-off timer of the session that made it; the timer
dies with the session, and a handover comment that forgot one lost it (#1 6672885313).
The file keeps it across sessions: commit.sh writes it, patrol.sh lists what is not kept
yet, and take_over.sh prints the same list to the new coordinator.

File: LOGS/commitments.jsonl (LOGS is <data>/logs), appended, one JSON object per line:
  {"type": "add", "id": "c<N>", "issue", "due", "text", "url", "at", "session_id"}
      a commitment. ``due`` is UTC ISO (2026-11-07T01:23:00Z) or null (no set time: kept
      when something happens, such as a merge). ``url`` is the 統籌承諾 comment on the
      Issue ``issue`` (taken from the url). ``id`` counts up from c1.
  {"type": "done", "id", "at", "session_id", "url"}
      kept; ``url`` (or null) is the comment that says so.
A line that cannot be read is reported by ``list`` and skipped; it never hides the rest.
Times are UTC ISO; NOW is epoch seconds.

Subcommands:
  add LOGS NOW SESSION --due DUE --url URL --text TEXT
      DUE is none or YYYY-MM-DDTHH:MM[:SS] followed by Z or +HH:MM/-HH:MM; URL is
      https://github.com/YiCheng0608/stock-lab/(issues|pull)/<n>#issuecomment-<id>.
      Prints the new id. Exit 64 on a bad argument (nothing written).
  done LOGS NOW SESSION ID [--url URL]
      Exit 3 when ID was never added; an ID already kept is reported and exits 0.
  list LOGS NOW
      "未兌現的承諾：N 則（已到期 M 則）", then one line per commitment not kept, the
      ones due first, by due time; those without a time last.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

FILE = "commitments.jsonl"
TAIPEI = timezone(timedelta(hours=8))
URL_RE = re.compile(
    r"^https://github\.com/YiCheng0608/stock-lab/(?:issues|pull)/(\d+)#issuecomment-\d+$"
)
DUE_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})$"
)
ID_RE = re.compile(r"^c([1-9]\d*)$")


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_due(text: str) -> str | None:
    """UTC ISO of DUE; raises ValueError when it is not one of the accepted forms."""
    m = DUE_RE.match(text)
    if not m:
        raise ValueError(text)
    y, mo, d, h, mi, s, zone = m.groups()
    if zone == "Z":
        tz = timezone.utc
    else:
        sign = 1 if zone[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6])))
    when = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0), tzinfo=tz)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(stamp: str) -> int:
    return int(
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def read(logs: str) -> tuple[list[dict], list[int]]:
    """The records in order, and the line numbers that could not be read."""
    path = os.path.join(logs, FILE)
    records: list[dict] = []
    bad: list[int] = []
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return records, bad
    for number, line in enumerate(raw.split(b"\n"), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            bad.append(number)
            continue
        ok = isinstance(record, dict) and isinstance(record.get("id"), str)
        if ok and record.get("type") == "add":
            ok = isinstance(record.get("text"), str) and (
                record.get("due") is None
                or (isinstance(record["due"], str) and _valid_iso(record["due"]))
            )
        elif ok:
            ok = record.get("type") == "done"
        if ok:
            records.append(record)
        else:
            bad.append(number)
    return records, bad


def _valid_iso(stamp: str) -> bool:
    try:
        _epoch(stamp)
    except ValueError:
        return False
    return True


def state(records: list[dict]) -> tuple[dict[str, dict], set[str]]:
    added: dict[str, dict] = {}
    kept: set[str] = set()
    for record in records:
        if record["type"] == "add":
            added.setdefault(record["id"], record)
        else:
            kept.add(record["id"])
    return added, kept


def append(logs: str, record: dict) -> None:
    """One write with O_APPEND; a partial last line left by a crash starts a new line."""
    path = os.path.join(logs, FILE)
    line = json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell():
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    line = b"\n" + line
    except FileNotFoundError:
        pass
    fd = os.open(
        path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644
    )
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def taipei(stamp: str) -> str:
    return (
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=timezone.utc)
        .astimezone(TAIPEI)
        .strftime("%Y-%m-%d %H:%M")
    )


def one_line(text: str) -> str:
    return " ".join(text.split())


def listing(logs: str, now: int) -> list[str]:
    records, bad = read(logs)
    added, kept = state(records)
    open_ = [c for cid, c in added.items() if cid not in kept]
    due = [c for c in open_ if c.get("due") and _epoch(c["due"]) <= now]

    def key(c: dict):
        return (c.get("due") is None, c.get("due") or "", _number(c["id"]))

    lines = [f"未兌現的承諾：{len(open_)} 則（已到期 {len(due)} 則）"]
    for c in sorted(open_, key=key):
        if c.get("due") is None:
            when = "無到期時間"
        else:
            when = f"{taipei(c['due'])}（台北）"
            if _epoch(c["due"]) <= now:
                when = f"[已到期] {when}"
        issue = f"#{c['issue']}" if c.get("issue") else "#?"
        lines.append(
            f"  [{c['id']}] {when} {issue} {one_line(c['text'])} {c.get('url') or ''}".rstrip()
        )
    for number in bad:
        lines.append(
            f"  承諾檔第 {number} 列讀不懂，略過（{os.path.join(logs, FILE)}）"
        )
    return lines


def _number(cid: str) -> int:
    m = ID_RE.match(cid)
    return int(m.group(1)) if m else 0


def _options(args: list[str], allowed: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    it = iter(args)
    for flag in it:
        if flag not in allowed:
            raise ValueError(f"unknown argument: {flag}")
        try:
            out[flag] = next(it)
        except StopIteration:
            raise ValueError(f"{flag} needs a value") from None
    return out


def add(logs: str, now: int, session: str, args: list[str]) -> int:
    try:
        opts = _options(args, {"--due", "--url", "--text"})
    except ValueError as error:
        print(error, file=sys.stderr)
        return 64
    missing = [f for f in ("--due", "--url", "--text") if f not in opts]
    if missing:
        print(f"必填：{'、'.join(missing)}", file=sys.stderr)
        return 64
    text = opts["--text"].strip()
    if not text:
        print("--text 是空的", file=sys.stderr)
        return 64
    m = URL_RE.match(opts["--url"])
    if not m:
        print(
            "--url 要是承諾留言的連結：https://github.com/YiCheng0608/stock-lab/issues/<n>#issuecomment-<id>",
            file=sys.stderr,
        )
        return 64
    if opts["--due"] == "none":
        due = None
    else:
        try:
            due = parse_due(opts["--due"])
        except ValueError:
            print(
                "--due 要是 none 或 2026-11-07T09:23+08:00／2026-11-07T01:23:00Z 這種寫法",
                file=sys.stderr,
            )
            return 64
    records, _ = read(logs)
    added, _ = state(records)
    cid = f"c{max((_number(i) for i in added), default=0) + 1}"
    append(
        logs,
        {
            "type": "add",
            "id": cid,
            "issue": int(m.group(1)),
            "due": due,
            "text": text,
            "url": opts["--url"],
            "at": iso(now),
            "session_id": session or None,
        },
    )
    print(cid)
    return 0


def done(logs: str, now: int, session: str, args: list[str]) -> int:
    if not args:
        print("要給承諾 id（c<N>）", file=sys.stderr)
        return 64
    cid, rest = args[0], args[1:]
    try:
        opts = _options(rest, {"--url"})
    except ValueError as error:
        print(error, file=sys.stderr)
        return 64
    url = opts.get("--url")
    if url is not None and not URL_RE.match(url):
        print("--url 要是兌現留言的連結（…#issuecomment-<id>）", file=sys.stderr)
        return 64
    records, _ = read(logs)
    added, kept = state(records)
    if cid not in added:
        print(f"沒有這個承諾：{cid}", file=sys.stderr)
        return 3
    if cid in kept:
        print(f"{cid} 已標記兌現")
        return 0
    append(
        logs,
        {
            "type": "done",
            "id": cid,
            "at": iso(now),
            "session_id": session or None,
            "url": url,
        },
    )
    print(f"{cid} 已兌現：{one_line(added[cid]['text'])}")
    return 0


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 64
    command, logs = argv[0], argv[1]
    try:
        now = int(argv[2])
    except ValueError:
        print("NOW 要是 epoch 秒數", file=sys.stderr)
        return 64
    if command == "list":
        for line in listing(logs, now):
            print(line)
        return 0
    if len(argv) < 4:
        print(__doc__, file=sys.stderr)
        return 64
    session, rest = argv[3], argv[4:]
    if command == "add":
        return add(logs, now, session, rest)
    if command == "done":
        return done(logs, now, session, rest)
    print(f"unknown command: {command}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
