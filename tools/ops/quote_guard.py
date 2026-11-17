"""The gatekeeper of Fugle quotes (#834; docs/DATA_SOURCES.md 盤中報價).

Fugle's terms forbid passing its quotes on (the TWSE rules it cites, 第二十七條), so no
text with an unmasked one may reach GitHub. Every way out runs this check first and refuses
the text on a hit: tools/ops/comment.sh, the PreToolUse hook tools/ops/agent_guard.cjs (gh
issue／pr comment, create, edit, review; gh api to issues, pulls, comments and graphql; a
push to pr-assets) and the CI PR gate (tools/ci/checks.py rule g). The patterns are the one
file quote_patterns.json, which the hook reads too (its note says what each one means);
backend/tests/test_quote_guard.py binds them to backend/worker/intraday.py TEMPLATES.

A hit names the line and the pattern, never the quote. What counts:

- ``template:<key>``: a piece of TEMPLATES filled in with a Fugle value (成交, 開盤, 委買,
  委賣 followed by a number). ``<價>`` and ``<時間>`` pass, and so do the rule levels
  (觸及規則進場價 X, 停損 X, 目標一 X), which are ours.
- ``field:<name>``: a field of Fugle's answer whose value is a number, or a [..], {..} or
  (..) with any digit inside (pretty-printed JSON included).
- ``repr:Quote``: a ``fugle.Quote`` as Python prints it, with any ``key=number``.
- ``message``: an intraday message record (the ``--- message`` line of ``--dry-run`` or a
  line of the day's jsonl) whose decoded text has a template hit, or a ``--- message`` line
  that is no record.
- ``levels``: a record of the round's levels whose entries have a numeric high, low or last.

``mask`` writes the same text with each hit's values replaced (``<時間>``, ``<價>``, and
``<值>`` inside a field's value or a Quote); every other line, ``--- poll`` and ``--- event``
among them, and the rule levels stay as they are. A bracket that never closes is masked to
the end of its line only. Its output passes ``check``.

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
NUMBER = re.compile(r"-?[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")
# A datetime of a Quote; one cut off at the end of the span has no ")".
DATETIME = re.compile(r"datetime\.datetime\([^)]*\)?")
MASKED_TIME = "<時間>"
MASKED_PRICE = "<價>"
MASKED_VALUE = "<值>"
OPENERS = {"[": "]", "{": "}", "(": ")"}


@lru_cache(maxsize=None)
def patterns(path: Path = PATTERNS_FILE) -> dict[str, Any]:
    """The compiled patterns of PATH (quote_patterns.json's note)."""

    data = json.loads(path.read_text(encoding="utf-8"))
    names = "|".join(re.escape(name) for name in data["fields"])
    return {
        "templates": {key: re.compile(rx) for key, rx in data["templates"].items()},
        "fields": re.compile(rf"(?<![A-Za-z0-9_])({names}){data['field_head']}"),
        "scalar": re.compile(data["scalar"]),
        "repr_open": re.compile(data["repr"]["open"]),
        "repr_value": re.compile(data["repr"]["value"]),
        "record": re.compile(data["record"]),
        "levels": data["levels"],
    }


def value_end(text: str, start: int) -> int:
    """The end of the bracket opening at START: its balanced close (across lines, quotes
    skipped), or the end of START's line when it never closes."""

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
    line_end = text.find("\n", start)
    return len(text) if line_end < 0 else line_end


def _field_value(text: str, match: re.Match[str], c: dict[str, Any]) -> int | None:
    """The end of the hit value after the field head MATCH, or None when it holds none."""

    at = match.end()
    if at < len(text) and text[at] in OPENERS:
        end = value_end(text, at)
        return end if re.search("[0-9]", text[at:end]) else None
    scalar = c["scalar"].match(text, at)
    if not scalar:
        return None
    number = NUMBER.match(text, at)
    return number.end() if number else scalar.end()


def _repr_span(text: str, match: re.Match[str], c: dict[str, Any]) -> int | None:
    end = value_end(text, match.end() - 1)
    return end if c["repr_value"].search(text, match.end(), end) else None


def _template_hits(text: str, c: dict[str, Any]) -> list[str]:
    return [f"template:{key}" for key, rx in c["templates"].items() if rx.search(text)]


def _record(line: str, c: dict[str, Any]) -> tuple[re.Match[str] | None, Any]:
    """LINE's JSON record (the match and the decoded object), the object None when the
    line is no record."""

    found = c["record"].match(line)
    if not found:
        return None, None
    try:
        record = json.loads(found.group(1))
    except ValueError:
        return found, None
    return found, record if isinstance(record, dict) else None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _level_quotes(record: dict[str, Any], c: dict[str, Any]) -> bool:
    levels = record.get(c["levels"]["key"])
    if not isinstance(levels, dict):
        return False
    return any(
        isinstance(entry, dict) and _is_number(entry.get(name))
        for entry in levels.values()
        for name in c["levels"]["quotes"]
    )


def _line_hits(line: str, c: dict[str, Any]) -> list[str]:
    kinds = _template_hits(line, c)
    _, record = _record(line, c)
    if record is not None and isinstance(record.get("text"), str):
        if _template_hits(record["text"], c):
            kinds.append("message")
    elif line.startswith("--- message "):
        kinds.append("message")
    if record is not None and _level_quotes(record, c):
        kinds.append("levels")
    return kinds


def hits(text: str, compiled: dict[str, Any] | None = None) -> list[tuple[int, str]]:
    """Every hit of TEXT as (line number, kind), in order."""

    c = compiled or patterns()
    found: set[tuple[int, str]] = set()
    for number, line in enumerate(text.split("\n"), 1):
        found.update((number, kind) for kind in _line_hits(line, c))

    def line_of(at: int) -> int:
        return text.count("\n", 0, at) + 1

    for match in c["fields"].finditer(text):
        if _field_value(text, match, c) is not None:
            found.add((line_of(match.start()), f"field:{match[1]}"))
    for match in c["repr_open"].finditer(text):
        if _repr_span(text, match, c) is not None:
            found.add((line_of(match.start()), "repr:Quote"))
    return sorted(found)


def _mask_templates(text: str, c: dict[str, Any]) -> str:
    def values(match: re.Match[str]) -> str:
        return NUMBER.sub(MASKED_PRICE, TIME.sub(MASKED_TIME, match.group()))

    for regex in c["templates"].values():
        text = regex.sub(values, text)
    return text


def _mask_record(line: str, c: dict[str, Any]) -> str:
    found, record = _record(line, c)
    if record is None:
        return line
    if isinstance(record.get("text"), str):
        record = dict(record, text=_mask_templates(record["text"], c))
    levels = record.get(c["levels"]["key"])
    if isinstance(levels, dict):
        record = dict(record)
        record[c["levels"]["key"]] = {
            key: {
                name: MASKED_PRICE
                if name in c["levels"]["quotes"] and _is_number(value)
                else value
                for name, value in entry.items()
            }
            if isinstance(entry, dict)
            else entry
            for key, entry in levels.items()
        }
    body = json.dumps(record, ensure_ascii=False)
    return line[: found.start(1)] + body + line[found.end(1) :]


def _mask_spans(text: str, c: dict[str, Any]) -> str:
    """Mask the values of the field and Quote hits, one at a time until none is left."""

    while True:
        for match in c["fields"].finditer(text):
            end = _field_value(text, match, c)
            if end is not None:
                start = match.end()
                masked = NUMBER.sub(MASKED_VALUE, text[start:end])
                text = text[:start] + masked + text[end:]
                break
        else:
            for match in c["repr_open"].finditer(text):
                end = _repr_span(text, match, c)
                if end is not None:
                    span = re.sub(
                        "=" + NUMBER.pattern,
                        "=" + MASKED_VALUE,
                        text[match.end() : end],
                    )
                    span = DATETIME.sub(
                        lambda m: NUMBER.sub(MASKED_VALUE, m.group()), span
                    )
                    text = text[: match.end()] + span + text[end:]
                    break
            else:
                return text


def mask(text: str, compiled: dict[str, Any] | None = None) -> str:
    """TEXT with every hit's values masked; the other lines as they are."""

    c = compiled or patterns()
    lines = [_mask_templates(_mask_record(line, c), c) for line in text.split("\n")]
    return _mask_spans("\n".join(lines), c)


def describe(label: str, found: list[tuple[int, str]]) -> list[str]:
    return [f"{label}:{number}: {kind}" for number, kind in found]


def _read(name: str) -> str:
    if name == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    return Path(name).read_bytes().decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("check", "mask"):
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
