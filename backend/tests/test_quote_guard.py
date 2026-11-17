"""tools/ops/quote_guard.py: the gatekeeper of Fugle quotes (#834).

AC-1: each kind of pattern (a filled-in template, a field of Fugle's answer, a message
record) has a case it catches; masked text and the rule levels pass; the patterns are bound
to backend/worker/intraday.py TEMPLATES. AC-3: the fixture day's ``--dry-run`` output is
refused as printed and passes once masked, its ``--- poll`` and ``--- event`` lines and
rule levels kept. The numbers are the fixture's (backend/tests/fixtures/fugle_intraday)
or plainly made up.
"""

from __future__ import annotations

import json
import string
import subprocess
import sys
from pathlib import Path

import pytest

from test_intraday import _listed, _quote, _run, _track, db, env  # noqa: F401 (fixtures)
from worker import intraday

OPS = Path(__file__).resolve().parents[2] / "tools" / "ops"
sys.path.insert(0, str(OPS))
try:
    import quote_guard
finally:
    sys.path.remove(str(OPS))

PATTERNS = json.loads((OPS / "quote_patterns.json").read_text(encoding="utf-8"))
CASES = json.loads((OPS / "quote_guard_cases.json").read_text(encoding="utf-8"))
# The TEMPLATES fields filled in from Fugle's answer, and the ones that are ours (the rule
# levels, the minute of the round, the names, the run's own counts). A new field must be
# put in one of the two: test_every_template_field_is_classified fails until it is.
QUOTE_FIELDS = {"time", "price", "open"}
OUR_FIELDS = {
    "head",
    "entry",
    "entry_word",
    "stop",
    "target_1",
    "target_2",
    "when",
    "minute",
    "trade",
    "sources",
    "bid",
    "ask",
    "slow",
    "code",
    "why",
    "total",
    "limit",
    "skipped_count",
    "skipped",
}
MASKED = {"time": quote_guard.MASKED_TIME, "price": quote_guard.MASKED_PRICE}


def kinds(text: str) -> set[str]:
    return {kind for _, kind in quote_guard.hits(text)}


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _fill(template: str, *, masked: bool) -> str:
    """TEMPLATE with the fixture's 2618 at 09:01: its levels, and its quote's values or
    their masks."""

    quote = _quote(1, "2618")
    track = _track("2618")
    values = {
        "time": f"{intraday._taipei(quote.last_time):%H:%M:%S}",
        "price": intraday._fmt(quote.last_price),
        "open": intraday._fmt(quote.open),
        "head": track.head,
        "entry": intraday._entry(track),
        "entry_word": "價",
        "stop": intraday._fmt(track.invalid),
        "target_1": intraday._fmt(track.target_1),
        "target_2": intraday._fmt(track.target_2),
        "minute": "09:01",
        "when": "09:01 前後；成交價取不到",
        "trade": "成交價取不到",
        "sources": "今日名單",
        "bid": "委買取不到",
        "ask": "委賣取不到",
        "slow": 5,
        "code": 429,
        "why": "超過呼叫上限",
        "total": 52,
        "limit": 50,
        "skipped_count": 2,
        "skipped": "2618、3374",
    }
    if masked:
        values.update(MASKED, open=quote_guard.MASKED_PRICE)
    return template.format(**values)


# --- AC-1: what is caught and what passes (the cases agent_guard.test.cjs runs too) ------


@pytest.mark.parametrize("case", CASES["hit"], ids=lambda case: case["kinds"][0])
def test_each_pattern_catches_its_case(case):
    assert kinds(case["text"]) == set(case["kinds"])


@pytest.mark.parametrize("text", CASES["pass"])
def test_masked_text_and_the_rule_levels_pass(text):
    assert quote_guard.hits(text) == []


def test_every_pattern_has_a_case():
    covered = {kind for case in CASES["hit"] for kind in case["kinds"]}
    assert covered == (
        {f"template:{key}" for key in PATTERNS["templates"]}
        | {f"field:{name}" for name in PATTERNS["fields"]}
        | {"message"}
    )


def test_a_message_record_is_caught_even_when_escaped():
    text = "2618 長榮航 觸及規則進場價 47.75（10:03 前後；10:02:41 成交 47.80）"
    record = {"key": "signal:2618", "event": "entry", "text": text}
    # ensure_ascii: the line itself shows no 成交, only the record's decoded text does.
    escaped = json.dumps(record)
    assert "成交" not in escaped
    assert kinds(escaped) == {"message"}
    assert kinds("--- message " + escaped) == {"message"}
    # A record whose text is masked passes.
    masked = dict(record, text=quote_guard.mask(text))
    assert kinds("--- message " + json.dumps(masked)) == set()


def test_hits_name_the_line_and_pattern_never_the_quote(capsys, tmp_path):
    body = tmp_path / "body.md"
    body.write_text("回報：\n\n委買 47.75\n", encoding="utf-8")
    assert quote_guard.main(["check", str(body)]) == 1
    err = capsys.readouterr().err
    assert f"{body}:3: template:bid" in err
    assert "47.75" not in err


# --- AC-1: bound to TEMPLATES ------------------------------------------------------------


def test_every_template_field_is_classified():
    """A TEMPLATES field nobody classified: is it a Fugle value? Add it to QUOTE_FIELDS
    (and a pattern to quote_patterns.json) or to OUR_FIELDS."""

    for key, template in intraday.TEMPLATES.items():
        assert _fields(template) <= QUOTE_FIELDS | OUR_FIELDS, key


def test_every_template_with_a_fugle_value_is_caught_and_passes_masked():
    caught: set[str] = set()
    quoted = [
        key
        for key, template in intraday.TEMPLATES.items()
        if _fields(template) & QUOTE_FIELDS
    ]
    assert {"trade", "bid", "ask", intraday.GAP_ABOVE_TARGET} <= set(quoted)
    for key in quoted:
        template = intraday.TEMPLATES[key]
        found = kinds(_fill(template, masked=False))
        assert found, key
        caught |= found
        assert quote_guard.hits(_fill(template, masked=True)) == [], key
    # Every template pattern is the one of some template: none is left over.
    assert caught == {f"template:{key}" for key in PATTERNS["templates"]}


def test_every_message_of_the_fixture_is_caught_and_passes_masked():
    """intraday.message as the run writes it, each event and a locked quote: caught;
    masked, it passes and keeps the rule levels."""

    events = [
        ("2618", intraday.ENTRY, 1),
        ("2618", intraday.STOP, 1),
        ("2618", intraday.TARGET_1, 1),
        ("2618", intraday.TARGET_2, 1),
        ("3374", intraday.STOP_BEFORE_ENTRY, 2),
        ("8099", intraday.GAP_ABOVE_TARGET, 1),
        ("8099", intraday.GAP_BELOW_INVALID, 1),
        ("2618", intraday.STOP_AND_TARGET, 1),
        ("3162", intraday.ENTRY_AND_STOP, 1),
    ]
    for symbol, event, poll in events:
        track = _track(symbol)
        quote = _quote(poll, symbol)
        text = intraday.message(track, event, quote, quote.last_updated)
        assert quote_guard.hits(text), (symbol, event)
        masked = quote_guard.mask(text)
        assert quote_guard.hits(masked) == [], (symbol, event)
        levels = [
            intraday._entry(track),
            intraday._fmt(track.invalid),
            intraday._fmt(track.target_1),
            intraday._fmt(track.target_2),
        ]
        kept = [level for level in levels if level in text]
        assert kept and all(level in masked for level in kept), (symbol, event)
    # 8099 opens locked at the limit up: the open, the trade and the bid.
    quote = _quote(1, "8099")
    locked = intraday.message(
        _track("8099"), intraday.GAP_ABOVE_TARGET, quote, quote.last_updated
    )
    assert {"template:bid", "template:open", "template:trade"} <= kinds(locked)


# --- the mask command ----------------------------------------------------------------------


def test_mask_masks_a_fields_whole_value():
    raw = json.dumps(
        {
            "lastTrade": {"bid": 47.75, "price": 47.8, "time": 1794790830000000},
            "bids": [{"price": 47.75, "size": 3}, {"price": 47.7, "size": 9}],
        },
        indent=2,
    )
    masked = quote_guard.mask(raw)
    assert quote_guard.hits(masked) == []
    assert not any(value in masked for value in ("47.75", "47.8", "47.7", "1794790830"))


def test_the_command_line(tmp_path):
    def run(*args, stdin=""):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(OPS / "quote_guard.py"), *args],
            input=stdin.encode(),
            capture_output=True,
        )

    raw = tmp_path / "raw.txt"
    raw.write_text("10:02:41 成交 47.80\n--- poll at=10:03:00\n", encoding="utf-8")
    assert run("check", str(raw)).returncode == 1
    masked = run("mask", str(raw))
    assert masked.returncode == 0
    assert masked.stdout.decode() == "<時間> 成交 <價>\n--- poll at=10:03:00\n"
    assert run("check", stdin=masked.stdout.decode()).returncode == 0
    assert run("check", str(tmp_path / "missing.txt")).returncode == 2
    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe")
    assert run("check", str(tmp_path / "bad.txt")).returncode == 2
    assert run().returncode == 64


# --- AC-3: the fixture day's --dry-run ------------------------------------------------------


def test_the_fixture_dry_run_is_refused_and_passes_masked(env):  # noqa: F811 (fixture)
    _listed(env.db)
    result = _run(env, start="10:02:30", mode="--dry-run", extra=("--minutes", "2"))
    out = result.out
    found = quote_guard.hits(out)
    assert {kind for _, kind in found} >= {"message", "template:trade"}
    masked = quote_guard.mask(out)
    assert quote_guard.hits(masked) == []
    # Only the message lines change; --- poll and --- event lines stay as printed.
    before, after = out.split("\n"), masked.split("\n")
    assert len(before) == len(after)
    for old, new in zip(before, after):
        if not old.startswith("--- message "):
            assert new == old
    assert sum(line.startswith("--- poll ") for line in after) == 2
    assert sum(line.startswith("--- event ") for line in after) == 5
    # The rule levels are still in the messages.
    texts = [
        json.loads(line[len("--- message ") :])["text"]
        for line in after
        if line.startswith("--- message ")
    ]
    assert len(texts) == 5
    for level in ("47.75", "480.18", "182.00", "198.63", "72.89～76.94", "70.86"):
        assert any(level in text for text in texts), level
