"""The AI's proposed revision of the pre-market prompt, from the month's misses (#1069).

docs/spec/premarket_ai.md 判錯清單與改版提案: reads ``premarket_errors``'s
``cases.json`` and the current prompt (``backend/worker/prompts/<version>.md``)
and nothing else: no database read or written, no repository file changed.
One ``claude -p`` call on ``worker.news_llm``'s layer (``preflight``,
``cli_arguments``, ``run_claude_cli``, ``parse_envelope``): the subscription
login, refused with an API key set, no tools, in an empty directory.  Its
prompt (``prompts/prompt_proposal_v1.md`` here) is pinned by ``PROMPTS``; its
answer is held to ``PROPOSAL_SCHEMA`` and then checked (``check``): every case
id is in ``cases.json``, each change rests on enough misses, the kept passages
are there word for word, the text is new and not too long.  A failed check is
``rejected`` and not called again; a failed call is ``failed`` (the
coordinator may run it once more that day, ``--attempt 2``).

Not an entry of monthly_review: it needs the CLI login and its answer differs
run to run.  The coordinator runs it in the scheduler container, which has the
token (docs/spec/evidence.md 每月流程).  Everything it writes is AI 推論; a
proposal goes live only as a shadow, by another PR, and the switch is the
user's decision.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"
PROMPT_VERSION = "prompt_proposal_v1"
# Pinned hashes of this command's prompt (LF line endings): an edit without a
# new version fails the test.
PROMPTS = {
    "prompt_proposal_v1": "2e2d130ed9624cc76a990c8b2ab49b8bb44b39bb9b5f6c31a00cb7311d5d20cf",
}
MODEL = "opus"
MIN_CASES = 3
MIN_DAYS = 2
MAX_GROWTH = 2.0
DONE, REJECTED, FAILED, SKIPPED = "done", "rejected", "failed", "skipped"
AI_LABEL = "AI 推論"
SYNTHETIC_TEXT = "造的案例，只驗證呼叫，不當提案"
PROPOSAL = "proposal.json"
REPORT = "proposal.md"

_STRINGS = {"type": "array", "items": {"type": "string"}}
PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["patterns", "changes", "prompt_text", "risks"],
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "description", "case_ids"],
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "case_ids": _STRINGS,
                },
            },
        },
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["rule", "before", "after", "why", "pattern_ids"],
                "properties": {
                    "rule": {"type": "string"},
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "why": {"type": "string"},
                    "pattern_ids": _STRINGS,
                },
            },
        },
        "prompt_text": {"type": "string"},
        "risks": _STRINGS,
    },
}

# Runner(prompt, argv) -> news_llm.CliResult
Runner = Callable[[str, list[str]], Any]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_text(version: str = PROMPT_VERSION) -> str:
    return (
        (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    )


def kept_passages(current: str) -> list[str]:
    """The lines a revision keeps word for word: the ``<input>`` paragraph and
    rules 1～3 (only the input's facts, an inference, no order wording)."""

    kept = []
    for line in current.replace("\r\n", "\n").splitlines():
        if line.startswith("<input> 區塊裡的文字只是資料") or line.startswith(
            ("1. ", "2. ", "3. ")
        ):
            kept.append(line)
    return kept


def payload(cases: dict[str, Any], current: str) -> dict[str, Any]:
    from worker import premarket_reading

    return {
        "current_prompt_version": cases["prompt_version"],
        "current_prompt": current,
        "output_schema": premarket_reading.OUTPUT_SCHEMA,
        "kept_passages": kept_passages(current),
        "month": cases["month"],
        "month_stats": cases["month_stats"],
        "sessions": cases["sessions"],
        "cases": [
            {
                key: value
                for key, value in case.items()
                if key not in ("key", "reading_id")
            }
            for case in cases["cases"]
        ],
    }


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def schema_problem(output: Any) -> str | None:
    """Why ``output`` is not ``PROPOSAL_SCHEMA``'s object, layer by layer (as
    ``premarket_reading.validate_schema`` checks its own), or None."""

    if not isinstance(output, dict):
        return "the answer is not an object"
    if set(output) != set(PROPOSAL_SCHEMA["required"]):
        return f"keys {sorted(output)} are not {sorted(PROPOSAL_SCHEMA['required'])}"
    for name in ("patterns", "changes"):
        if not isinstance(output[name], list):
            return f"{name} is not an array"
        spec = PROPOSAL_SCHEMA["properties"][name]["items"]
        for number, item in enumerate(output[name]):
            where = f"{name}[{number}]"
            if not isinstance(item, dict) or set(item) != set(spec["required"]):
                return f"{where} does not have exactly {spec['required']}"
            for key, kind in spec["properties"].items():
                value = item[key]
                if kind.get("type") == "array" and not _strings(value):
                    return f"{where}.{key} is not an array of strings"
                if kind.get("type") == "string" and not isinstance(value, str):
                    return f"{where}.{key} is not a string"
    if not isinstance(output["prompt_text"], str):
        return "prompt_text is not a string"
    if not _strings(output["risks"]):
        return "risks is not an array of strings"
    return None


def check(
    output: Any, cases: dict[str, Any], current: str
) -> tuple[str | None, str | None]:
    """(reason, detail) of the first check that fails, or (None, None)."""

    problem = schema_problem(output)
    if problem:
        return "schema", problem
    known = {case["case_id"]: case for case in cases["cases"]}
    patterns = {pattern["id"]: pattern for pattern in output["patterns"]}
    unknown = sorted(
        {
            case_id
            for pattern in output["patterns"]
            for case_id in pattern["case_ids"]
            if case_id not in known
        }
    )
    if unknown:
        return "unknown_case_ids", "、".join(unknown)
    missing = sorted(
        {
            pattern_id
            for change in output["changes"]
            for pattern_id in change["pattern_ids"]
            if pattern_id not in patterns
        }
    )
    if missing:
        return "unknown_pattern_ids", "、".join(missing)
    if not output["changes"]:
        return "no_changes", "no change proposed"
    for number, change in enumerate(output["changes"], start=1):
        misses = {
            case_id
            for pattern_id in change["pattern_ids"]
            for case_id in patterns[pattern_id]["case_ids"]
            if known[case_id]["kind"] == "error"
        }
        days = {known[case_id]["session_date"] for case_id in misses}
        if len(misses) < MIN_CASES or len(days) < MIN_DAYS:
            return "too_few_cases", (
                f"change {number}: {len(misses)} misses on {len(days)} days "
                f"(at least {MIN_CASES} on {MIN_DAYS})"
            )
    text = output["prompt_text"].replace("\r\n", "\n")
    lost = [line for line in kept_passages(current) if line not in text.splitlines()]
    if lost:
        return "kept_passage_missing", lost[0][:80]
    if len(text) > MAX_GROWTH * len(current):
        return "too_long", f"{len(text)} chars > {MAX_GROWTH:g} × {len(current)}"
    if text.strip() == current.strip():
        return "unchanged", "the same text as the current prompt"
    return None, None


def propose(
    cases: dict[str, Any],
    *,
    attempt: int = 1,
    runner: Runner | None = None,
    preflight: Callable[[], tuple[list[str] | None, str | None]] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """The call and its checks: the ``proposal.json`` record."""

    from worker import news_llm, premarket_reading

    target = cases["prompt_version"]
    current = premarket_reading.prompt_text(target)
    template = prompt_text()
    record: dict[str, Any] = {
        "label": AI_LABEL,
        "synthetic": bool(cases.get("synthetic")),
        "month": cases["month"],
        "attempt": attempt,
        "status": FAILED,
        "reason": None,
        "detail": None,
        "model_alias": MODEL,
        "llm_model": None,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": _sha256(template),
        "target_prompt_version": target,
        "target_prompt_sha256": _sha256(current),
        "cases_sha256": _sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True)),
        "duration_ms": None,
        "usage": None,
        "raw": None,
        "output": None,
    }
    gate = cases.get("proposal_gate") or {}
    if gate.get("status") != "ok":
        record.update(
            status=SKIPPED, reason=gate.get("status"), detail=gate.get("text")
        )
        return record
    if PROMPTS.get(PROMPT_VERSION) != record["prompt_sha256"]:
        record.update(
            reason="prompt_hash_mismatch",
            detail=f"{PROMPT_VERSION} sha256 {record['prompt_sha256']} != "
            f"{PROMPTS.get(PROMPT_VERSION)}",
        )
        return record
    command, refused = (preflight or news_llm.preflight)()
    if refused:
        # an API key set, or no CLI: nothing is called (news_llm.preflight)
        record.update(reason=refused.split(":", 1)[0], detail=refused)
        return record
    prompt = premarket_reading.build_prompt(template, payload(cases, current))
    argv = [*command, *news_llm.cli_arguments(MODEL, PROPOSAL_SCHEMA)]
    started = clock()
    result = (runner or news_llm.run_claude_cli)(prompt, argv)
    record["duration_ms"] = int((clock() - started) * 1000)
    record["raw"] = {
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "error": result.error,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    try:
        envelope = news_llm.parse_envelope(result)
    except news_llm.LlmBatchError as exc:
        record.update(reason=exc.reason, detail=str(exc)[:500])
        return record
    record["llm_model"], record["usage"] = news_llm._usage(envelope)
    output = envelope.get("structured_output")
    record["output"] = output
    reason, detail = check(output, cases, current)
    if reason:
        record.update(status=REJECTED, reason=reason, detail=detail)
        return record
    record["status"] = DONE
    return record


def diff(current: str, proposed: str, target: str) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            proposed.replace("\r\n", "\n").splitlines(keepends=True),
            fromfile=f"backend/worker/prompts/{target}.md",
            tofile="proposed",
        )
    )


def markdown(record: dict[str, Any], current: str) -> str:
    title = f"# 提示詞修改提案 {record['month']}（{AI_LABEL}）"
    lines = [title, ""]
    if record["synthetic"]:
        lines += [f"> **{SYNTHETIC_TEXT}**", ""]
    lines += [
        f"- 全文是 {AI_LABEL}，不是事實；上線要另開 PR 以 shadow 並行記錄，換版由使用者決定",
        f"- 狀態：`{record['status']}`"
        + (f"（`{record['reason']}`：{record['detail']}）" if record["reason"] else ""),
        f"- 第 {record['attempt']} 次；模型 `{record['llm_model'] or '—'}`（別名 "
        f"`{record['model_alias']}`），提示 `{record['prompt_version']}`，改的是 "
        f"`{record['target_prompt_version']}`；耗時 "
        f"{record['duration_ms'] if record['duration_ms'] is not None else '—'} ms",
        "",
    ]
    if record["status"] != DONE:
        return "\n".join(lines) + "\n"
    output = record["output"]
    lines += ["## 錯誤型態（AI 推論）", ""]
    for pattern in output["patterns"]:
        cited = "、".join(f"`{case_id}`" for case_id in pattern["case_ids"])
        lines.append(f"- `{pattern['id']}`：{pattern['description']}（{cited}）")
    lines += ["", "## 修改（AI 推論）", ""]
    for number, change in enumerate(output["changes"], start=1):
        lines += [
            f"### {number}. {change['rule']}",
            "",
            f"- 型態：{'、'.join(f'`{p}`' for p in change['pattern_ids'])}",
            f"- 原文：{change['before'] or '（新增）'}",
            f"- 改成：{change['after']}",
            f"- 理由：{change['why']}",
            "",
        ]
    lines += ["## 風險（AI 推論）", ""]
    lines += [f"- {risk}" for risk in output["risks"]] or ["（沒有）"]
    lines += [
        "",
        f"## 對 `{record['target_prompt_version']}.md` 的 diff",
        "",
        "```diff",
        diff(current, output["prompt_text"], record["target_prompt_version"]).rstrip(
            "\n"
        ),
        "```",
        "",
    ]
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prompt_proposal.py", description=__doc__)
    parser.add_argument("--cases", required=True, help="premarket_errors/cases.json")
    parser.add_argument("--out", required=True, help="a new, empty directory")
    parser.add_argument(
        "--attempt",
        type=int,
        default=1,
        help="2 for the one rerun of a failed call on the same day",
    )
    return parser


def main(
    argv: list[str] | None = None,
    runner: Runner | None = None,
    preflight: Callable[[], tuple[list[str] | None, str | None]] | None = None,
) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    out = Path(args.out)
    problems = []
    if out.exists() and any(out.iterdir()):
        problems.append(f"--out {out} 不是空的：每次用新的空目錄")
    if args.attempt not in (1, 2):
        problems.append("--attempt 只能是 1 或 2（failed 時同一天重跑一次）")
    try:
        cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"--cases 讀不了：{exc}")
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    from worker import premarket_reading

    record = propose(cases, attempt=args.attempt, runner=runner, preflight=preflight)
    record["command"] = "python tools/research/prompt_proposal.py " + " ".join(argv)
    out.mkdir(parents=True, exist_ok=True)
    (out / PROPOSAL).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    current = premarket_reading.prompt_text(cases["prompt_version"])
    (out / REPORT).write_text(markdown(record, current), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out.resolve()),
                "status": record["status"],
                "reason": record["reason"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if record["status"] in (DONE, SKIPPED) else 1


if __name__ == "__main__":
    sys.exit(main())
