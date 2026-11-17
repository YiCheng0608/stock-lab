"""The gatekeeper of Fugle quotes (#834; docs/DATA_SOURCES.md 盤中報價).

Fugle's terms forbid passing its quotes on (the TWSE rules it cites, 第二十七條), so no
text with an unmasked one may reach GitHub. Every way out runs this check first and refuses
the text on a hit: tools/ops/comment.sh, the PreToolUse hook tools/ops/agent_guard.cjs (gh
issue／pr comment, create, edit, review; gh api to issues, pulls and comments; a push to
pr-assets) and the CI PR gate (tools/ci/checks.py rule g). The patterns are the one file
quote_patterns.json, which the hook reads too; backend/tests/test_quote_guard.py binds
them to backend/worker/intraday.py TEMPLATES.

A hit names the line and the pattern, never the quote. What counts:

- ``template:<key>``: a piece of TEMPLATES filled in with a Fugle value (``09:03:12 成交
  47.8``, ``開盤 200``, ``委買 47.75``, ``委賣 47.8``). ``<價>`` and ``<時間>`` pass, and so
  do the rule levels (觸及規則進場價 X, 停損 X, 目標一 X), which are ours.
- ``field:<name>``: a field of Fugle's answer with a number (``"lastPrice": 47.8``,
  ``"bids": [{"price": 47.75``), pretty-printed JSON included.
- ``message``: an intraday message record, the ``--- message`` line of ``--dry-run`` or a
  line of the day's jsonl, whose decoded text has a template hit (``\\u`` escapes too), or
  a ``--- message`` line that is no JSON.

``mask`` writes the same text with each hit's values replaced (``<時間>``, ``<價>``, and
``<值>`` inside a field's value); every other line, ``--- poll`` and ``--- event`` among
them, and the rule levels stay as they are. Its output passes ``check``.

Not caught: images, text typed on GitHub's web pages, and calls that go around the hook.

Usage:
  quote_guard.py check [FILE ...]   FILE or - (stdin, the default); exit 0 clean, 1 on a
                                    hit (one line each on stderr: FILE:LINE: KIND), 2 when a
                                    file cannot be read as UTF-8
  quote_guard.py mask [FILE]        the masked text on stdout; exit 1 (nothing printed) if
                                    the result would still hit, 2 when unreadable

Only the standard library: CI's PR gate imports it without the backend's dependencies.
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

PATTERNS_FILE = Path(__file__).with_name("quote_patterns.json")
TIME = re.compile(r"[0-9]{1,2}:[0-9]{2}:[0-9]{2}")
NUMBER = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")
MASKED_TIME = "<時間>"
MASKED_PRICE = "<價>"
MASKED_VALUE = "<值>"
OPENERS = {"[": "]", "{": "}", "(": ")"}


@lru_cache(maxsize=None)
def patterns(path: Path = PATTERNS_FILE) -> dict[str, Any]:
    """The compiled patterns of PATH: templates (key -> regex), fields (one regex whose
    group 1 is the field name) and message (a line regex, group 1 the JSON)."""

    data = json.loads(path.read_text(encoding="utf-8"))
    names = "|".join(re.escape(name) for name in data["fields"])
    return {
        "templates": {key: re.compile(rx) for key, rx in data["templates"].items()},
        "fields": re.compile(rf"(?<![A-Za-z0-9_])({names}){data['field_value']}"),
        "message": re.compile(data["message"]),
    }


def _template_hits(text: str, compiled: dict[str, Any]) -> list[str]:
    return [
        f"template:{key}"
        for key, regex in compiled["templates"].items()
        if regex.search(text)
    ]


def _record(
    line: str, compiled: dict[str, Any]
) -> tuple[re.Match[str] | None, Any] | None:
    """LINE's message record (the match and the decoded JSON), or None when it is none;
    the JSON is None when a --- message line holds none."""

    found = compiled["message"].match(line)
    if not found:
        return (None, None) if line.startswith("--- message ") else None
    try:
        record = json.loads(found.group(1))
    except ValueError:
        record = None
    if isinstance(record, dict) and isinstance(record.get("text"), str):
        return found, record
    return (found, None) if line.startswith("--- message ") else None


def hits(text: str, compiled: dict[str, Any] | None = None) -> list[tuple[int, str]]:
    """Every hit of TEXT as (line number, kind), in order."""

    compiled = compiled or patterns()
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.split("\n"), 1):
        found.extend((number, kind) for kind in _template_hits(line, compiled))
        record = _record(line, compiled)
        if record and (
            record[1] is None or _template_hits(record[1]["text"], compiled)
        ):
            found.append((number, "message"))
    for match in compiled["fields"].finditer(text):
        found.append((text.count("\n", 0, match.start()) + 1, f"field:{match[1]}"))
    return sorted(set(found))


def _mask_templates(text: str, compiled: dict[str, Any]) -> str:
    def values(match: re.Match[str]) -> str:
        return NUMBER.sub(MASKED_PRICE, TIME.sub(MASKED_TIME, match.group()))

    for regex in compiled["templates"].values():
        text = regex.sub(values, text)
    return text


def _value_end(text: str, start: int) -> int:
    """The end of the value at START: a balanced [..], {..} or (..) (quotes skipped), or
    the number there."""

    if text[start] not in OPENERS:
        number = NUMBER.match(text, start)
        return number.end() if number else start
    stack, quote, i = [], "", start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in OPENERS:
            stack.append(OPENERS[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                return i + 1
        i += 1
    return len(text)


def _mask_fields(text: str, compiled: dict[str, Any]) -> str:
    regex = compiled["fields"]
    while True:
        match = regex.search(text)
        if not match:
            return text
        # The value starts after the field's separator and blanks.
        start = re.compile(r"[\"']?\s*[:=]\s*").match(text, match.end(1)).end()
        # The match ends at the value's first digit: through the whole number at least.
        end = max(_value_end(text, start), NUMBER.match(text, match.end() - 1).end())
        text = text[:start] + NUMBER.sub(MASKED_VALUE, text[start:end]) + text[end:]


def mask(text: str, compiled: dict[str, Any] | None = None) -> str:
    """TEXT with every hit's values masked; the other lines as they are."""

    compiled = compiled or patterns()
    lines = []
    for line in text.split("\n"):
        record = _record(line, compiled)
        if record and record[1] is not None:
            found, value = record
            value = dict(value, text=_mask_templates(value["text"], compiled))
            body = json.dumps(value, ensure_ascii=False)
            line = line[: found.start(1)] + body + line[found.end(1) :]
        lines.append(_mask_templates(line, compiled))
    return _mask_fields("\n".join(lines), compiled)


def describe(label: str, found: list[tuple[int, str]]) -> list[str]:
    return [f"{label}:{number}: {kind}" for number, kind in found]


def _read(name: str) -> str:
    if name == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    return Path(name).read_bytes().decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("check", "mask") or argv[0] == "-h":
        print(__doc__.split("Usage:", 1)[1].rstrip(), file=sys.stderr)
        return 64
    command, names = argv[0], argv[1:] or ["-"]
    if command == "mask" and len(names) != 1:
        print("quote_guard: mask takes one FILE (or -)", file=sys.stderr)
        return 64
    try:
        texts = [(name, _read(name)) for name in names]
    except (OSError, UnicodeDecodeError) as exc:
        print(f"quote_guard: cannot read: {exc}", file=sys.stderr)
        return 2
    if command == "mask":
        masked = mask(texts[0][1])
        left = hits(masked)
        if left:
            print("\n".join(describe("masked", left)), file=sys.stderr)
            return 1
        sys.stdout.buffer.write(masked.encode("utf-8"))
        return 0
    found = [line for name, text in texts for line in describe(name, hits(text))]
    if found:
        print("\n".join(found), file=sys.stderr)
        print(
            "quote_guard: 有沒遮的富果報價；先跑 quote_guard.py mask 再貼"
            "（docs/DATA_SOURCES.md 盤中報價）",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
