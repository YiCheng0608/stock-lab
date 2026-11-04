"""Fake ``claude`` CLI for worker.news_llm tests.

Reads the prompt from stdin and prints a ``claude -p --output-format json``
envelope.  ``FAKE_CLAUDE_MODES`` is a comma list of modes, one per call
(the last repeats); ``FAKE_CLAUDE_LOG`` collects one JSON line per call.
``drop_first``, ``drop_id``, ``duplicate_and_extra``, ``empty_items``,
``string_ids`` and ``items_not_list`` answer with ids left out, repeated or not sent (#450).
Mode ``theme_cases`` answers with the outputs of ``theme_cases.json`` matched
by title, keeping only the theme candidate keys the sent ``--json-schema``
allows (``evidence`` is new in news_v3).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

THEME_CASES = Path(__file__).with_name("theme_cases.json")


def _news(prompt: str) -> list[dict]:
    # The prompt text itself mentions <news>; the data block is the last one.
    body = prompt.rsplit("<news>", 1)[1].split("</news>", 1)[0]
    return json.loads(body)


def _theme_keys(argv: list[str]) -> set[str]:
    """Keys of a theme candidate in the sent --json-schema."""

    schema = json.loads(argv[argv.index("--json-schema") + 1])
    item_schema = schema["properties"]["items"]["items"]["properties"]
    return set(item_schema["theme_candidates"]["items"]["properties"])


def _only(theme: dict, allowed: set[str]) -> dict:
    return {key: value for key, value in theme.items() if key in allowed}


def _item(news: dict, allowed: set[str]) -> dict:
    # Built from the sent title only, so the summary check passes.  The theme
    # and its evidence are in the default summary of test_news_llm._add_news.
    theme = {"theme": "半導體", "reason": "晶圓代工", "evidence": "晶圓代工"}
    return {
        "id": news["id"],
        "summary_zh": f"摘要：{news['title']}",
        "symbol_candidates": [
            {
                "symbol": "TWSE:2330",
                "reason": "新聞提到晶圓代工需求",
                "confidence": "medium",
            }
        ],
        "theme_candidates": [_only(theme, allowed)],
        "impact_direction": "positive",
        "impact_scope": "instrument",
        "impact_rationale": "需求增加",
        "unsupported": False,
    }


def _theme_case_items(news: list[dict], allowed: set[str]) -> list[dict]:
    cases = json.loads(THEME_CASES.read_text(encoding="utf-8"))["items"]
    by_title = {case["title"]: case["output"] for case in cases}
    items = []
    for entry in news:
        output = json.loads(json.dumps(by_title[entry["title"]]))
        output["theme_candidates"] = [
            _only(theme, allowed) for theme in output["theme_candidates"]
        ]
        items.append({"id": entry["id"], **output})
    return items


def _envelope(structured, *, is_error=False, result="") -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result,
        "structured_output": structured,
        "modelUsage": {
            "claude-sonnet-fake": {
                "inputTokens": 10,
                "outputTokens": 20,
                "cacheReadInputTokens": 300,
                "cacheCreationInputTokens": 4000,
            }
        },
    }


def _out(text: str) -> None:
    # UTF-8 like the real CLI, whatever the console code page is.
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    prompt = sys.stdin.buffer.read().decode("utf-8")
    log = os.environ["FAKE_CLAUDE_LOG"]
    with (
        open(log, encoding="utf-8")
        if os.path.exists(log)
        else open(os.devnull) as handle
    ):
        calls = sum(1 for _ in handle)
    modes = os.environ.get("FAKE_CLAUDE_MODES", "ok").split(",")
    mode = modes[min(calls, len(modes) - 1)]
    news = _news(prompt)
    allowed = _theme_keys(sys.argv[1:])
    ids = [item["id"] for item in news]
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "argv": sys.argv[1:],
                    "ids": ids,
                    "mode": mode,
                    "leaked_env": sorted(
                        key
                        for key in os.environ
                        if key in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")
                        or key.startswith(("CLAUDE_CODE_", "ANTHROPIC_"))
                    ),
                    "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"),
                    "cwd_entries": os.listdir(os.getcwd()),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    if mode == "sleep":
        time.sleep(30)
        return 0
    if mode == "not_logged_in":
        _out(
            json.dumps(
                _envelope(
                    None, is_error=True, result="Not logged in · Please run /login"
                )
            )
        )
        return 1
    if mode == "token_expired":
        # An expired CLAUDE_CODE_OAUTH_TOKEN in -p (code.claude.com/docs/en/errors).
        envelope = _envelope(
            None,
            is_error=True,
            result="Failed to authenticate. API Error: 401 OAuth token has expired",
        )
        _out(json.dumps({**envelope, "api_error_status": 401}))
        return 1
    if mode == "rate_limited":
        _out(
            json.dumps(
                _envelope(None, is_error=True, result="Claude AI usage limit reached")
            )
        )
        return 1
    if mode == "invalid_json":
        _out("this is not json")
        return 0
    if mode == "theme_cases":
        items = _theme_case_items(news, allowed)
        _out(json.dumps(_envelope({"items": items}), ensure_ascii=False))
        return 0
    items = [_item(item, allowed) for item in news]
    if mode == "missing_field":
        del items[0]["impact_direction"]
    if mode == "extra_key":
        items[0]["buy_signal"] = True
    if mode == "long_reason":
        items[0]["symbol_candidates"][0]["reason"] = "理" * 121
    if mode == "rounded_number":
        # A number the source writes as 44.28.
        items[0]["summary_zh"] = "營收年增44%"
    # #450: answers that leave out, repeat or add ids.
    if mode == "drop_first":
        del items[0]
    if mode == "drop_id":
        # FAKE_CLAUDE_DROP_ID is left out whenever it is sent.
        dropped = int(os.environ["FAKE_CLAUDE_DROP_ID"])
        items = [item for item in items if item["id"] != dropped]
    if mode == "duplicate_and_extra":
        # The first id twice (two different answers) and an id that was not sent.
        items.append({**items[0], "summary_zh": "重複的另一份答案"})
        items.append({**items[1], "id": int(os.environ["FAKE_CLAUDE_EXTRA_ID"])})
    if mode == "empty_items":
        items = []
    if mode == "string_ids":
        # As if a CLI or model change sent every id back as a string.
        for item in items:
            item["id"] = str(item["id"])
    if mode == "items_not_list":
        items = "none"
    _out(json.dumps(_envelope({"items": items}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
