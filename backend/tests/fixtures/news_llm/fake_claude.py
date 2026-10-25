"""Fake ``claude`` CLI for worker.news_llm tests.

Reads the prompt from stdin and prints a ``claude -p --output-format json``
envelope.  ``FAKE_CLAUDE_MODES`` is a comma list of modes, one per call
(the last repeats); ``FAKE_CLAUDE_LOG`` collects one JSON line per call.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _news(prompt: str) -> list[dict]:
    # The prompt text itself mentions <news>; the data block is the last one.
    body = prompt.rsplit("<news>", 1)[1].split("</news>", 1)[0]
    return json.loads(body)


def _item(news: dict) -> dict:
    # Built from the sent title only, so the summary check passes.
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
        "theme_candidates": [{"theme": "半導體", "reason": "晶圓代工"}],
        "impact_direction": "positive",
        "impact_scope": "instrument",
        "impact_rationale": "需求增加",
        "unsupported": False,
    }


def _envelope(structured, *, is_error=False, result="") -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result,
        "structured_output": structured,
        "modelUsage": {
            "claude-haiku-fake": {
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
    items = [_item(item) for item in news]
    if mode == "missing_field":
        del items[0]["impact_direction"]
    if mode == "extra_key":
        items[0]["buy_signal"] = True
    if mode == "long_reason":
        items[0]["symbol_candidates"][0]["reason"] = "理" * 121
    if mode == "rounded_number":
        # A number the source writes as 44.28.
        items[0]["summary_zh"] = "營收年增44%"
    _out(json.dumps(_envelope({"items": items}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
