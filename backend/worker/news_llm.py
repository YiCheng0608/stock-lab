"""News LLM batch: summaries, relation candidates and direction calls via ``claude -p``.

Active news items from the last three days without a ``done`` result for the
current prompt version are sent in batches to the local Claude Code CLI in
headless mode, logged in with the user's subscription (no API key).  Results
go to news_llm_results, one row per item and prompt version, so the rule
relations and source summary on news_items are never overwritten and older
prompt versions stay.  Older items are marked ``skipped_stale`` and not sent.

A failing batch (timeout, invalid JSON, schema mismatch) marks its items
``pending`` with the reason and the other batches still run; pending items
are retried on the next run.  A failure that every later call would repeat
(not logged in, rate limit, CLI not started) stops the run and the remaining
batches are skipped.  Every call stores its prompt and response as raw and
its token usage and duration on the ``news_llm`` ingestion run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import IngestionRun, NewsItem, NewsLlmResult

from . import sources
from .news_sources import TAIPEI
from .pipeline import _upsert_raw_payload

PROMPT_VERSION = "news_v1"
PROMPT_PATH = Path(__file__).with_name("prompts") / f"{PROMPT_VERSION}.md"
# Pinned hash of the prompt text (LF line endings).  Editing the prompt
# without a new PROMPT_VERSION fails the prompt version test.
PROMPT_SHA256 = "bbb3b265f48b992eda24a71b2b36db6144f2fa46b4dd49577ab85704455ccb63"
MODEL = "haiku"
BATCH_SIZE = 25
DEFAULT_LIMIT = 50
# Calls per Taipei day across all news_llm runs; the subscription quota is
# shared with the interactive sessions.
DAILY_CALL_LIMIT = 20
# Items whose published_at (else collected_at) is older are not sent.
STALE_AFTER = timedelta(days=3)
# The scheduled news task (news, then news-llm) is stopped after 90 minutes
# and never runs twice at once, so a news_llm run still marked running after
# that long lost its process; the next run records it as failed.
ABANDONED_AFTER = timedelta(minutes=90)
CALL_TIMEOUT_SECONDS = 300
SUMMARY_INPUT_CHARS = 600
SUMMARY_MAX_CHARS = 80
REASON_MAX_CHARS = 120
THEME_MAX_CHARS = 40
RATIONALE_MAX_CHARS = 120
CLI_ENV = "STOCK_CLAUDE_CLI"
# Removed from the child environment: session variables of a parent Claude
# Code process (the CLI refuses to start as a nested session) and any
# Anthropic API setting.  CLAUDE_CONFIG_DIR is kept so the login is found.
STRIPPED_ENV = frozenset({"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"})
STRIPPED_ENV_PREFIXES = ("CLAUDE_CODE_", "ANTHROPIC_")
# The batch uses the subscription login only; with these set it refuses to run.
API_KEY_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Failures every later call in the same run would repeat.
FATAL_REASONS = frozenset({"not_logged_in", "rate_limited", "cli_not_started"})
RAW_SOURCE = "news_llm"
RAW_ENDPOINT = f"claude -p --model {MODEL}"

DIRECTIONS = ("positive", "negative", "mixed", "unknown")
SCOPES = ("instrument", "theme", "market")
CONFIDENCES = ("high", "medium", "low")
SYMBOL_PATTERN = "^(TWSE|TPEx):[0-9A-Z]{4,6}$"
_SYMBOL = re.compile(SYMBOL_PATTERN)

_CANDIDATE_SYMBOL = {
    "type": "object",
    "additionalProperties": False,
    "required": ["symbol", "reason", "confidence"],
    "properties": {
        "symbol": {"type": "string", "pattern": SYMBOL_PATTERN},
        "reason": {"type": "string", "maxLength": REASON_MAX_CHARS},
        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
    },
}
_CANDIDATE_THEME = {
    "type": "object",
    "additionalProperties": False,
    "required": ["theme", "reason"],
    "properties": {
        "theme": {"type": "string", "maxLength": THEME_MAX_CHARS},
        "reason": {"type": "string", "maxLength": REASON_MAX_CHARS},
    },
}
_ITEM_FIELDS = (
    "id",
    "summary_zh",
    "symbol_candidates",
    "theme_candidates",
    "impact_direction",
    "impact_scope",
    "impact_rationale",
    "unsupported",
)
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(_ITEM_FIELDS),
                "properties": {
                    "id": {"type": "integer"},
                    "summary_zh": {"type": "string", "maxLength": SUMMARY_MAX_CHARS},
                    "symbol_candidates": {"type": "array", "items": _CANDIDATE_SYMBOL},
                    "theme_candidates": {"type": "array", "items": _CANDIDATE_THEME},
                    "impact_direction": {"type": "string", "enum": list(DIRECTIONS)},
                    "impact_scope": {"type": "string", "enum": list(SCOPES)},
                    "impact_rationale": {
                        "type": "string",
                        "maxLength": RATIONALE_MAX_CHARS,
                    },
                    "unsupported": {"type": "boolean"},
                },
            },
        }
    },
}


class LlmBatchError(RuntimeError):
    """A batch failed; ``reason`` is a short machine-readable cause."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class CliResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str | None = None


Runner = Callable[[str, Sequence[str]], CliResult]


def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def prompt_sha256(text: str | None = None) -> str:
    return hashlib.sha256((text or prompt_text()).encode("utf-8")).hexdigest()


def cli_prefix() -> list[str]:
    """The CLI command: ``STOCK_CLAUDE_CLI`` as a path or a JSON list, else ``claude``."""

    value = os.environ.get(CLI_ENV, "").strip()
    if not value:
        return ["claude"]
    if value.startswith("["):
        parsed = json.loads(value)
        if not (
            isinstance(parsed, list)
            and parsed
            and all(isinstance(part, str) and part for part in parsed)
        ):
            raise ValueError(f"{CLI_ENV} must be a path or a JSON list of strings")
        return parsed
    return [value]


def preflight() -> tuple[list[str] | None, str | None]:
    """Resolve the CLI command before any run row is written.

    Returns ``(command, None)`` or ``(None, reason)``.
    """

    if any(os.environ.get(name) for name in API_KEY_ENV):
        return None, "api_key_env_refused"
    try:
        prefix = cli_prefix()
    except ValueError as exc:
        return None, f"cli_config_invalid: {exc}"
    executable = prefix[0]
    if os.sep in executable or "/" in executable:
        found = executable if Path(executable).is_file() else None
    else:
        found = shutil.which(executable)
    if found is None:
        return None, f"cli_not_found: {executable}"
    return [found, *prefix[1:]], None


def cli_arguments() -> list[str]:
    return [
        "-p",
        "--no-session-persistence",
        "--model",
        MODEL,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, separators=(",", ":")),
        # No built-in tools, no MCP servers and no user/project/local
        # settings (hooks, CLAUDE.md): news text is data only.
        "--tools",
        "",
        "--setting-sources",
        "",
        "--strict-mcp-config",
    ]


def child_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in STRIPPED_ENV and not key.startswith(STRIPPED_ENV_PREFIXES)
    }


def run_claude_cli(prompt: str, argv: Sequence[str]) -> CliResult:
    """Run the CLI with the prompt on stdin, in an empty directory."""

    with tempfile.TemporaryDirectory(prefix="news-llm-") as cwd:
        try:
            completed = subprocess.run(
                list(argv),
                input=prompt.encode("utf-8"),
                capture_output=True,
                cwd=cwd,
                env=child_env(),
                timeout=CALL_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CliResult(
                None, _decode(exc.stdout), _decode(exc.stderr), timed_out=True
            )
        except OSError as exc:
            return CliResult(None, "", "", error=f"{type(exc).__name__}: {exc}")
    return CliResult(
        completed.returncode, _decode(completed.stdout), _decode(completed.stderr)
    )


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def _taipei_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).astimezone(TAIPEI).isoformat()


def item_input(item: NewsItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source_name,
        "category": item.category,
        "title": item.title,
        "summary": (item.summary or "")[:SUMMARY_INPUT_CHARS],
        "published_at": _taipei_text(item.published_at),
    }


def input_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_prompt(template: str, inputs: list[dict[str, Any]]) -> str:
    # Escape angle brackets so news text cannot close or forge the <news> block.
    news = (
        json.dumps(inputs, ensure_ascii=False, indent=1)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return f"{template.rstrip()}\n\n<news>\n{news}\n</news>\n"


def _candidates_query(db: Session, on_date: date | None):
    """Active items without a done or skipped_stale result for the current prompt."""

    settled = select(NewsLlmResult.news_item_id).where(
        NewsLlmResult.prompt_version == PROMPT_VERSION,
        NewsLlmResult.llm_status.in_(("done", "skipped_stale")),
    )
    query = select(NewsItem).where(
        NewsItem.status == "active", NewsItem.id.not_in(settled)
    )
    if on_date is not None:
        # collected_at is UTC-naive; the filter is the Taipei calendar day.
        start = datetime(on_date.year, on_date.month, on_date.day) - timedelta(hours=8)
        query = query.where(
            NewsItem.collected_at >= start,
            NewsItem.collected_at < start + timedelta(days=1),
        )
    return query


def _item_time():
    return func.coalesce(NewsItem.published_at, NewsItem.collected_at)


def select_items(
    db: Session,
    *,
    on_date: date | None = None,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Unsettled items of the last STALE_AFTER, newest first."""

    cutoff = (now or datetime.utcnow()) - STALE_AFTER
    query = (
        _candidates_query(db, on_date)
        .where(_item_time() >= cutoff)
        .order_by(
            NewsItem.display_time.is_(None),
            NewsItem.display_time.desc(),
            NewsItem.id.desc(),
        )
        .limit(limit)
    )
    return list(db.scalars(query).all())


def stale_items(
    db: Session, *, on_date: date | None = None, now: datetime | None = None
) -> list[NewsItem]:
    cutoff = (now or datetime.utcnow()) - STALE_AFTER
    query = _candidates_query(db, on_date).where(_item_time() < cutoff)
    return list(db.scalars(query).all())


def _calls_today(db: Session, run_date: date) -> int:
    runs = db.scalars(
        select(IngestionRun).where(
            IngestionRun.run_type == "news_llm", IngestionRun.run_date == run_date
        )
    ).all()
    return sum(int((run.metadata_json or {}).get("calls", 0)) for run in runs)


def _failure_reason(result: CliResult, envelope: dict[str, Any] | None) -> str:
    text = " ".join(
        str(part)
        for part in (
            (envelope or {}).get("result"),
            (envelope or {}).get("api_error_status"),
            result.stderr,
        )
        if part
    ).lower()
    if "not logged in" in text or "/login" in text or "please log in" in text:
        return "not_logged_in"
    if (
        "429" in text
        or "rate limit" in text
        or "usage limit" in text
        or "limit reached" in text
    ):
        return "rate_limited"
    return "cli_error"


def parse_envelope(result: CliResult) -> dict[str, Any]:
    """Return the CLI JSON envelope or raise LlmBatchError with the cause."""

    if result.error:
        raise LlmBatchError("cli_not_started", result.error)
    if result.timed_out:
        raise LlmBatchError("timeout", f"no result within {CALL_TIMEOUT_SECONDS}s")
    try:
        envelope = json.loads(result.stdout)
    except ValueError:
        envelope = None
    if not isinstance(envelope, dict):
        if result.returncode not in (0, None):
            raise LlmBatchError(
                _failure_reason(result, None), (result.stderr or result.stdout)[:300]
            )
        raise LlmBatchError("invalid_json", result.stdout[:300])
    if envelope.get("is_error") or result.returncode not in (0, None):
        raise LlmBatchError(
            _failure_reason(result, envelope), str(envelope.get("result") or "")[:300]
        )
    return envelope


def _object(value: Any, keys: Sequence[str], where: str) -> dict[str, Any]:
    """An object with exactly ``keys``, as additionalProperties=false requires."""

    if not isinstance(value, dict):
        raise LlmBatchError("schema_mismatch", f"{where} must be an object")
    missing = [key for key in keys if key not in value]
    extra = sorted(set(value) - set(keys))
    if missing or extra:
        raise LlmBatchError(
            "schema_mismatch", f"{where} missing {missing} extra {extra}"
        )
    return value


def _string(value: Any, where: str, max_chars: int | None = None) -> str:
    if not isinstance(value, str):
        raise LlmBatchError("schema_mismatch", f"{where} must be a string")
    text = value.strip()
    if max_chars is not None and len(text) > max_chars:
        raise LlmBatchError("schema_mismatch", f"{where} over {max_chars} chars")
    return text


def _validate_item(raw: Any) -> dict[str, Any]:
    raw = _object(raw, _ITEM_FIELDS, "item")
    item_id = raw["id"]
    if not isinstance(item_id, int) or isinstance(item_id, bool):
        raise LlmBatchError("schema_mismatch", "id must be an integer")
    where = f"item {item_id}"
    summary = _string(raw["summary_zh"], f"{where} summary_zh", SUMMARY_MAX_CHARS)
    if raw["impact_direction"] not in DIRECTIONS:
        raise LlmBatchError("schema_mismatch", f"{where} impact_direction")
    if raw["impact_scope"] not in SCOPES:
        raise LlmBatchError("schema_mismatch", f"{where} impact_scope")
    if not isinstance(raw["unsupported"], bool):
        raise LlmBatchError("schema_mismatch", f"{where} unsupported")
    if not isinstance(raw["symbol_candidates"], list):
        raise LlmBatchError("schema_mismatch", f"{where} symbol_candidates")
    if not isinstance(raw["theme_candidates"], list):
        raise LlmBatchError("schema_mismatch", f"{where} theme_candidates")
    symbols = []
    for candidate in raw["symbol_candidates"]:
        candidate = _object(
            candidate, ("symbol", "reason", "confidence"), f"{where} symbol candidate"
        )
        symbol = candidate["symbol"]
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            raise LlmBatchError("schema_mismatch", f"{where} symbol {symbol!r}")
        if candidate["confidence"] not in CONFIDENCES:
            raise LlmBatchError("schema_mismatch", f"{where} confidence")
        symbols.append(
            {
                "symbol": symbol,
                "reason": _string(
                    candidate["reason"], f"{where} reason", REASON_MAX_CHARS
                ),
                "confidence": candidate["confidence"],
            }
        )
    themes = []
    for candidate in raw["theme_candidates"]:
        candidate = _object(candidate, ("theme", "reason"), f"{where} theme candidate")
        themes.append(
            {
                "theme": _string(candidate["theme"], f"{where} theme", THEME_MAX_CHARS),
                "reason": _string(
                    candidate["reason"], f"{where} reason", REASON_MAX_CHARS
                ),
            }
        )
    unsupported = raw["unsupported"]
    return {
        "id": item_id,
        "summary": summary,
        "symbol_candidates": symbols,
        "theme_candidates": themes,
        # No positive or negative call without enough source information.
        "impact_direction": "unknown" if unsupported else raw["impact_direction"],
        "impact_scope": raw["impact_scope"],
        "impact_rationale": _string(
            raw["impact_rationale"], f"{where} impact_rationale", RATIONALE_MAX_CHARS
        ),
        "unsupported": unsupported,
    }


def validate_output(
    structured: Any, expected_ids: Sequence[int]
) -> dict[int, dict[str, Any]]:
    """Validate the whole response; any problem fails the whole batch."""

    structured = _object(structured, ("items",), "structured_output")
    if not isinstance(structured["items"], list):
        raise LlmBatchError("schema_mismatch", "structured_output.items must be a list")
    results: dict[int, dict[str, Any]] = {}
    for raw in structured["items"]:
        item = _validate_item(raw)
        if item["id"] in results:
            raise LlmBatchError("schema_mismatch", f"duplicate id {item['id']}")
        results[item["id"]] = item
    expected = set(expected_ids)
    if set(results) != expected:
        missing = sorted(expected - set(results))
        extra = sorted(set(results) - expected)
        raise LlmBatchError("schema_mismatch", f"ids missing {missing} extra {extra}")
    return results


_USAGE_KEYS = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
}


def _usage(envelope: dict[str, Any]) -> tuple[str | None, dict[str, int]]:
    model_usage = envelope.get("modelUsage") or {}
    totals = dict.fromkeys(_USAGE_KEYS, 0)
    if not isinstance(model_usage, dict):
        return None, totals
    for usage in model_usage.values():
        if isinstance(usage, dict):
            for total, key in _USAGE_KEYS.items():
                value = usage.get(key)
                if isinstance(value, int):
                    totals[total] += value
    return (",".join(sorted(model_usage)) or None), totals


def _result_row(db: Session, news_item_id: int) -> NewsLlmResult | None:
    return db.scalar(
        select(NewsLlmResult).where(
            NewsLlmResult.news_item_id == news_item_id,
            NewsLlmResult.prompt_version == PROMPT_VERSION,
        )
    )


def _new_row(item: NewsItem) -> NewsLlmResult:
    return NewsLlmResult(
        news_item_id=item.id,
        prompt_version=PROMPT_VERSION,
        ai_symbol_candidates_json=[],
        ai_theme_candidates_json=[],
    )


def _store_done(
    db: Session,
    item: NewsItem,
    output: dict[str, Any],
    *,
    model: str | None,
    run: IngestionRun,
    raw_payload_id: int,
    run_at: datetime,
) -> None:
    row = _result_row(db, item.id) or _new_row(item)
    row.llm_model = model or MODEL
    row.llm_input_hash = input_hash(item_input(item))
    row.llm_run_at = run_at
    row.llm_status = "done"
    row.llm_error = None
    row.ai_summary = output["summary"]
    row.ai_symbol_candidates_json = output["symbol_candidates"]
    row.ai_theme_candidates_json = output["theme_candidates"]
    row.ai_impact_direction = output["impact_direction"]
    row.ai_impact_scope = output["impact_scope"]
    row.ai_impact_rationale = output["impact_rationale"]
    row.ai_unsupported = output["unsupported"]
    row.ingestion_run_id = run.id
    row.raw_payload_id = raw_payload_id
    db.add(row)


def _store_status(
    db: Session,
    item: NewsItem,
    status: str,
    error: str,
    *,
    run: IngestionRun,
    raw_payload_id: int | None,
    run_at: datetime,
) -> None:
    # Only status, reason and audit links change; no ai_* field is written.
    row = _result_row(db, item.id) or _new_row(item)
    row.llm_model = row.llm_model or MODEL
    row.llm_input_hash = input_hash(item_input(item))
    row.llm_run_at = run_at
    row.llm_status = status
    row.llm_error = error[:500]
    row.ingestion_run_id = run.id
    row.raw_payload_id = raw_payload_id
    db.add(row)


def _run_batch(
    db: Session,
    run: IngestionRun,
    number: int,
    items: list[NewsItem],
    template: str,
    command: list[str],
    runner: Runner,
) -> dict[str, Any]:
    inputs = [item_input(item) for item in items]
    prompt = build_prompt(template, inputs)
    argv = [*command, *cli_arguments()]
    started = time.monotonic()
    result = runner(prompt, argv)
    duration_ms = int((time.monotonic() - started) * 1000)
    run_at = datetime.utcnow()
    summary: dict[str, Any] = {
        "batch": number,
        "news_ids": [item.id for item in items],
        "duration_ms": duration_ms,
    }
    raw = sources.capture_payload(
        RAW_SOURCE,
        RAW_ENDPOINT,
        {
            "prompt_version": PROMPT_VERSION,
            "argv": argv,
            "prompt": prompt,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "error": result.error,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": duration_ms,
        },
        run_at.isoformat(),
        collected_at=run_at,
    )
    raw_row = _upsert_raw_payload(db, run, raw)
    summary["raw_payload_id"] = raw_row.id
    envelope: dict[str, Any] | None = None
    try:
        envelope = parse_envelope(result)
        outputs = validate_output(
            envelope.get("structured_output"), summary["news_ids"]
        )
    except LlmBatchError as exc:
        if envelope is not None:
            summary["model"], summary["usage"] = _usage(envelope)
        for item in items:
            _store_status(
                db,
                item,
                "pending",
                str(exc),
                run=run,
                raw_payload_id=raw_row.id,
                run_at=run_at,
            )
        summary.update(status="pending", reason=exc.reason, error=str(exc)[:500])
        return summary
    model, usage = _usage(envelope)
    for item in items:
        _store_done(
            db,
            item,
            outputs[item.id],
            model=model,
            run=run,
            raw_payload_id=raw_row.id,
            run_at=run_at,
        )
    summary.update(status="done", model=model, usage=usage)
    return summary


def _usage_total(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        key: sum(int(item.get("usage", {}).get(key, 0)) for item in results)
        for key in _USAGE_KEYS
    }


def _metadata(
    template: str,
    limit: int,
    date_filter: str | None,
    results: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    stale: int,
) -> dict[str, Any]:
    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(template),
        "model": MODEL,
        "batch_size": BATCH_SIZE,
        "limit": limit,
        "date_filter": date_filter,
        "calls": len(results),
        "daily_call_limit": DAILY_CALL_LIMIT,
        "stale_skipped": stale,
        "skipped_batches": skipped,
        "usage_total": _usage_total(results),
        "duration_ms_total": sum(int(item.get("duration_ms", 0)) for item in results),
        "batches": results,
    }


def close_abandoned_runs(db: Session, now: datetime | None = None) -> list[int]:
    """Mark news_llm runs left running past ABANDONED_AFTER as failed."""

    current = now or datetime.utcnow()
    rows = db.scalars(
        select(IngestionRun).where(
            IngestionRun.run_type == "news_llm",
            IngestionRun.status == "running",
            IngestionRun.started_at < current - ABANDONED_AFTER,
        )
    ).all()
    for row in rows:
        row.status = "failed"
        row.error = f"abandoned: no finish was recorded within {ABANDONED_AFTER}"
        row.finished_at = current
    if rows:
        db.commit()
    return [row.id for row in rows]


def _failed_run(db: Session, label_date: date, reason: str) -> IngestionRun:
    now = datetime.utcnow()
    run = IngestionRun(
        run_type="news_llm",
        source="claude-cli",
        run_date=label_date,
        status="failed",
        records=0,
        error=reason,
        started_at=now,
        finished_at=now,
        data_as_of=now.isoformat(),
        metadata_json={"prompt_version": PROMPT_VERSION, "calls": 0, "reason": reason},
    )
    db.add(run)
    db.commit()
    return run


def run_news_llm(
    db: Session,
    *,
    on_date: date | None = None,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    runner: Runner | None = None,
    run_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    label_date = run_date or datetime.now(TAIPEI).date()
    template = prompt_text()
    base: dict[str, Any] = {
        "run_date": label_date.isoformat(),
        "prompt_version": PROMPT_VERSION,
        "date_filter": on_date.isoformat() if on_date else None,
    }
    if not dry_run:
        abandoned = close_abandoned_runs(db)
        if abandoned:
            base["abandoned_runs"] = abandoned
    command, problem = preflight()
    if problem is not None:
        # A configuration error writes no pending rows.
        if dry_run:
            return {**base, "status": "failed", "reason": problem}
        run = _failed_run(db, label_date, problem)
        return {**base, "status": "failed", "reason": problem, "run_id": run.id}
    assert command is not None
    stale = stale_items(db, on_date=on_date, now=now)
    items = select_items(db, on_date=on_date, limit=limit, now=now)
    batches = [
        items[start : start + BATCH_SIZE] for start in range(0, len(items), BATCH_SIZE)
    ]
    base.update(selected=len(items), stale=len(stale))
    used = _calls_today(db, label_date)
    allowed = max(DAILY_CALL_LIMIT - used, 0)
    if dry_run:
        return {
            **base,
            "status": "dry_run",
            "calls_used_today": used,
            "batches": [[item.id for item in batch] for batch in batches],
            "would_call": min(len(batches), allowed),
        }
    run = IngestionRun(
        run_type="news_llm",
        source="claude-cli",
        run_date=label_date,
        status="running",
        records=0,
        started_at=datetime.utcnow(),
        metadata_json={},
    )
    db.add(run)
    db.commit()
    stale_at = datetime.utcnow()
    for item in stale:
        _store_status(
            db,
            item,
            "skipped_stale",
            f"older than {STALE_AFTER.days} days; not sent",
            run=run,
            raw_payload_id=None,
            run_at=stale_at,
        )
    db.commit()
    active = runner or run_claude_cli
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    stop_reason: str | None = None
    for number, batch in enumerate(batches, start=1):
        ids = [item.id for item in batch]
        if stop_reason is not None:
            skipped.append({"batch": number, "news_ids": ids, "reason": stop_reason})
            continue
        if len(results) >= allowed:
            skipped.append(
                {"batch": number, "news_ids": ids, "reason": "daily_call_limit"}
            )
            continue
        try:
            outcome = _run_batch(db, run, number, batch, template, command, active)
        except Exception as exc:  # noqa: BLE001 - one batch must not stop the others
            db.rollback()
            error = f"batch_error: {type(exc).__name__}: {exc}"[:500]
            for item in batch:
                _store_status(
                    db,
                    item,
                    "pending",
                    error,
                    run=run,
                    raw_payload_id=None,
                    run_at=datetime.utcnow(),
                )
            outcome = {
                "batch": number,
                "news_ids": ids,
                "status": "pending",
                "reason": "batch_error",
                "error": error,
            }
        results.append(outcome)
        if outcome.get("reason") in FATAL_REASONS:
            stop_reason = f"stopped_after_{outcome['reason']}"
        # Count the call as soon as it is made, so a crash later in this run
        # still counts toward the daily limit.
        run.metadata_json = _metadata(
            template, limit, base["date_filter"], results, skipped, len(stale)
        )
        db.commit()
    done = [item for item in results if item["status"] == "done"]
    if not batches:
        status = "success"
    elif not results:
        status = "skipped"
    elif len(done) == len(batches):
        status = "success"
    elif done:
        status = "partial"
    else:
        status = "failed"
    failed = [item for item in results if item["status"] != "done"]
    errors = [
        f"batch {item['batch']}: {item.get('error', item.get('reason'))}"
        for item in failed
    ]
    for reason in sorted({item["reason"] for item in skipped}):
        count = sum(1 for item in skipped if item["reason"] == reason)
        errors.append(f"{reason}: {count} batch(es) skipped")
    run.status = status
    run.records = sum(len(item["news_ids"]) for item in done)
    run.error = "; ".join(errors) or None
    run.data_as_of = datetime.utcnow().isoformat()
    run.metadata_json = _metadata(
        template, limit, base["date_filter"], results, skipped, len(stale)
    )
    run.finished_at = datetime.utcnow()
    db.commit()
    return {
        **base,
        "status": status,
        "run_id": run.id,
        "done": run.records,
        "pending": sum(len(item["news_ids"]) for item in failed),
        "skipped": sum(len(item["news_ids"]) for item in skipped),
        "calls": len(results),
        "usage_total": _usage_total(results),
        "batches": results,
        "skipped_batches": skipped,
    }


def run_news_llm_batch(
    on_date: date | None = None, *, limit: int = DEFAULT_LIMIT, dry_run: bool = False
) -> dict[str, Any]:
    # Like the news batch, no init_db here; run init-db first on a new DB.
    with SessionLocal() as db:
        if not inspect(db.get_bind()).has_table(NewsLlmResult.__tablename__):
            return {
                "status": "failed",
                "reason": "news_llm_results_table_missing_run_init_db",
            }
        return run_news_llm(db, on_date=on_date, limit=limit, dry_run=dry_run)
