"""Fake ``claude`` CLI for worker.candidate_notes tests.

Reads the prompt from stdin and prints a ``claude -p --output-format json``
envelope.  ``FAKE_CLAUDE_MODES`` is a comma list of modes, one per call
(the last repeats); ``FAKE_CLAUDE_LOG`` collects one JSON line per call with
the candidate inputs it received.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _inputs(prompt: str) -> list[dict]:
    # The prompt text itself mentions <candidates>; the data block is the last one.
    body = prompt.rsplit("<candidates>", 1)[1].split("</candidates>", 1)[0]
    return json.loads(body)


def _note(candidate_id: int) -> dict:
    return {
        "id": candidate_id,
        "selection": f"候選{candidate_id}因突破 20 日高點與法人買超入選",
        "levels": "規則的進場區 100.00，條件失效的停損 98.00，第一目標 103.20",
        "risks": "新聞情緒分項是推論；族群當日未排名",
    }


def _envelope(structured, *, is_error=False, result="") -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result,
        "structured_output": structured,
        "modelUsage": {
            "claude-sonnet-fake": {
                "inputTokens": 11,
                "outputTokens": 22,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 500,
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
    inputs = _inputs(prompt)
    ids = [item["id"] for item in inputs]
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "argv": sys.argv[1:],
                    "ids": ids,
                    "inputs": inputs,
                    "mode": mode,
                    "leaked_env": sorted(
                        key
                        for key in os.environ
                        if key in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")
                        or key.startswith(("CLAUDE_CODE_", "ANTHROPIC_"))
                    ),
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
    if mode == "invalid_json":
        _out("this is not json")
        return 0
    notes = [_note(candidate_id) for candidate_id in ids]
    if mode == "missing_field":
        del notes[0]["risks"]
    if mode == "long_text":
        notes[0]["selection"] = "理" * 121
    if mode == "wrong_id":
        notes[0]["id"] = 99999
    _out(json.dumps(_envelope({"items": notes}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
