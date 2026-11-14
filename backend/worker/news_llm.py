"""News LLM batch: summaries, relation candidates and direction calls via ``claude -p``.

Active news items from the last three days without a ``done`` result for the
current prompt version are sent in batches to the local Claude Code CLI in
headless mode, logged in with the user's subscription (no API key).  Each run
takes the newest arrivals with half its limit and the oldest unsettled items
of the window with the rest, so new items cannot keep older ones out (#450).
Results go to news_llm_results, one row per item and prompt version, so the rule
relations and source summary on news_items are never overwritten and older
prompt versions stay.  Older items are marked ``skipped_stale`` and not sent.
An item whose summary writes a number its Chinese source does not is stored
``rejected`` without AI fields and is not sent again.  Since news_v4 (#676)
the prompt asks for no theme candidates; a news_v3 result counts as one of the
current prompt (``EQUIVALENT_PROMPT_VERSIONS``), so it is not sent again.

A failing batch (timeout, invalid JSON, an answer whose shape is wrong) marks
its items ``pending`` with the reason and the other batches still run; pending
items are retried on the next run.  An item the answer leaves out, repeats or
gets wrong is ``pending`` on its own and the rest of the batch is written; after
MAX_ITEM_ATTEMPTS such failures it is ``rejected`` and not sent again.  A
failure that every later call would repeat (not logged in, rate limit, CLI not
started) stops the run and the remaining batches are skipped.  Every call
stores its prompt and response as raw and its token usage and duration on the
``news_llm`` ingestion run; a run that ends failed or partial always records
its reason in ``error`` and ``metadata_json.reason``.
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
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    IngestionRun,
    NewsItem,
    NewsLlmResult,
)

from . import sources
from .news_sources import TAIPEI
from .pipeline import _upsert_raw_payload

PROMPT_VERSION = "news_v4"
# Prompt versions whose results stand for the current one (#676).  news_v4 is
# news_v3 without the theme candidates section, the rest word for word (a test
# compares the two files), so a news_v3 result has the same summary, symbol
# candidates and direction: it is not sent again, the API shows it when the
# item has no news_v4 result, and the candidate score reads its direction.
# Newest first.  A prompt that changes anything else is a new version that
# starts its own tuple.
EQUIVALENT_PROMPT_VERSIONS = ("news_v4", "news_v3")
PROMPT_PATH = Path(__file__).with_name("prompts") / f"{PROMPT_VERSION}.md"
# Pinned hash of the prompt text (LF line endings).  Editing the prompt
# without a new PROMPT_VERSION fails the prompt version test.
PROMPT_SHA256 = "9d5ba61e1efc0e2493e6043b8d2bfb2e55226602625c34e600a1372c66469159"
# sonnet since #262: with news_v2, haiku summaries still wrote facts the
# source does not (AC-3 rounds 1 and 2); sonnet had none on the same items.
MODEL = "sonnet"
BATCH_SIZE = 25
# Items per run (#450: 50 -> 100).  A weekday collects 450-600 items; the news
# job runs every 2 hours, so 12 runs of 100 cover a day and leave room for the
# backlog of a prompt upgrade or an outage.
DEFAULT_LIMIT = 100
# Calls per Taipei day across all news_llm runs (#450: 20 -> 48, 12 runs of 4);
# the subscription quota is shared with the interactive sessions.  A run calls
# only for the batches it has, so a quiet day uses far fewer.
DAILY_CALL_LIMIT = 48
# Items whose published_at (else collected_at) is older are not sent.
STALE_AFTER = timedelta(days=3)
# Collected within one news interval: the arrivals since the last run, which a
# run sends first with up to half its limit (#450).
FRESH_WINDOW = timedelta(hours=2)
# Sends of an item the answer left out, repeated or got wrong while other items
# of the answer were valid (the first and two retries); then it is rejected.  An
# answer with no valid item fails the whole batch and counts for no item.  The
# count is kept in llm_error (ITEM_FAILED).
MAX_ITEM_ATTEMPTS = 3
ITEM_FAILED = "item_failed"
_ITEM_FAILURES = re.compile(rf"^{ITEM_FAILED} (\d+)/\d+")
# The scheduled news task (news, then news-llm) is stopped after 90 minutes
# and never runs twice at once, so a news_llm run still marked running after
# that long lost its process; the next run records it as failed.
ABANDONED_AFTER = timedelta(minutes=90)
CALL_TIMEOUT_SECONDS = 300
SUMMARY_INPUT_CHARS = 600
SUMMARY_MAX_CHARS = 80
REASON_MAX_CHARS = 120
RATIONALE_MAX_CHARS = 120
CLI_ENV = "STOCK_CLAUDE_CLI"
# Removed from the child environment: session variables of a parent Claude
# Code process (the CLI refuses to start as a nested session) and any
# Anthropic API setting.  CLAUDE_CONFIG_DIR is kept so the login is found.
STRIPPED_ENV = frozenset({"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"})
STRIPPED_ENV_PREFIXES = ("CLAUDE_CODE_", "ANTHROPIC_")
# Kept although it has a stripped prefix: the one-year subscription token of
# ``claude setup-token``, which the scheduler container gets from .env (#337).
OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
# The batch uses the subscription login only; with these set it refuses to run.
API_KEY_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# A failed call is an authentication failure (not_logged_in: no login, or a
# login or CLAUDE_CODE_OAUTH_TOKEN that expired or was revoked) when its
# api_error_status is 401, or its stderr or error result (is_error) has one of
# these.  The -p messages of code.claude.com/docs/en/errors (read 2026-10-29,
# #337): "Not logged in · Please run /login", "Failed to authenticate. API
# Error: 401 OAuth token has expired", "Failed to authenticate: OAuth token
# revoked. Please log in again", "Failed to authenticate: OAuth session
# expired and could not be refreshed", "API Error: 401 Invalid authentication
# credentials"; the structured error code is authentication_failed.  A bare
# 401 is not enough: a stack trace line or model text can have one.
AUTH_ERROR_TEXT = (
    "not logged in",
    "/login",
    "please log in",
    "failed to authenticate",
    "authentication_failed",
    "oauth token",
    "invalid authentication credentials",
    "api error: 401",
)
# Failures every later call in the same run would repeat.
FATAL_REASONS = frozenset({"not_logged_in", "rate_limited", "cli_not_started"})
# A rejected item failed the summary check; like done and skipped_stale it is
# not sent again for this prompt version.
SETTLED_STATUSES = ("done", "skipped_stale", "rejected")
RAW_SOURCE = "news_llm"
RAW_ENDPOINT = f"claude -p --model {MODEL}"

DIRECTIONS = ("positive", "negative", "mixed", "unknown")
SCOPES = ("instrument", "theme", "market")
CONFIDENCES = ("high", "medium", "low")
SYMBOL_PATTERN = "^(TWSE|TPEx):[0-9A-Z]{4,6}$"
_SYMBOL = re.compile(SYMBOL_PATTERN)
# Summary check (news_v2): every number in the summary of a Chinese source
# must appear in its title or summary as written.  English sources are not
# checked, since the prompt lets their amounts be translated (million -> 萬).
_HAN = re.compile(r"[\u4e00-\u9fff]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

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
_ITEM_FIELDS = (
    "id",
    "summary_zh",
    "symbol_candidates",
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


def read_versions(version: str | None) -> tuple[str, ...]:
    """The prompt versions whose results stand for ``version``, newest first.

    news_v3 and news_v4 stand for each other (``EQUIVALENT_PROMPT_VERSIONS``),
    so a score config that names news_v3 also reads news_v4 (#676); any other
    version reads only itself.
    """

    if version in EQUIVALENT_PROMPT_VERSIONS:
        return EQUIVALENT_PROMPT_VERSIONS
    return (version,) if version else ()


def done_results(
    db: Session, news_ids: Sequence[int], version: str | None
) -> dict[int, NewsLlmResult]:
    """The ``done`` result per item of ``version`` or a version standing for it.

    When an item has more than one, the newest version in ``read_versions``
    wins.
    """

    versions = read_versions(version)
    if not news_ids or not versions:
        return {}
    rank = {name: position for position, name in enumerate(versions)}
    results: dict[int, NewsLlmResult] = {}
    for row in db.scalars(
        select(NewsLlmResult).where(
            NewsLlmResult.news_item_id.in_(news_ids),
            NewsLlmResult.prompt_version.in_(versions),
            NewsLlmResult.llm_status == "done",
        )
    ):
        kept = results.get(row.news_item_id)
        if kept is None or rank[row.prompt_version] < rank[kept.prompt_version]:
            results[row.news_item_id] = row
    return results


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


def cli_arguments(
    model: str = MODEL, schema: dict[str, Any] = OUTPUT_SCHEMA
) -> list[str]:
    return [
        "-p",
        "--no-session-persistence",
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
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
        if key == OAUTH_TOKEN_ENV
        or (key not in STRIPPED_ENV and not key.startswith(STRIPPED_ENV_PREFIXES))
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


def _numbers(text: str) -> list[str]:
    normalized = _THOUSANDS_COMMA.sub("", unicodedata.normalize("NFKC", text))
    return _NUMBER.findall(normalized)


def summary_numbers_missing(payload: dict[str, Any], summary: str) -> list[str]:
    """Numbers of ``summary`` not written in the item's sent title or summary.

    Whole numbers are compared (``3`` does not match ``30``) after NFKC and
    removing thousands separators.  Sources without Chinese text are not
    checked and give ``[]``.
    """

    source = f"{payload.get('title') or ''}\n{payload.get('summary') or ''}"
    if not _HAN.search(source):
        return []
    written = set(_numbers(source))
    return list(dict.fromkeys(n for n in _numbers(summary) if n not in written))


def _candidates_query(db: Session, on_date: date | None):
    """Active items without a settled result for the current prompt.

    A settled result of an equivalent version (news_v3) counts, so the switch
    to news_v4 sends no item again (#676).
    """

    settled = select(NewsLlmResult.news_item_id).where(
        NewsLlmResult.prompt_version.in_(read_versions(PROMPT_VERSION)),
        NewsLlmResult.llm_status.in_(SETTLED_STATUSES),
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
    """Unsettled items of the last STALE_AFTER: new arrivals first, then the oldest.

    Up to half of ``limit`` goes to the items collected within FRESH_WINDOW,
    newest first; the rest goes to the other unsettled items of the window,
    oldest first, so a day of new items never keeps older ones out until they
    turn stale (#450).
    """

    current = now or utcnow()
    window = _candidates_query(db, on_date).where(_item_time() >= current - STALE_AFTER)
    fresh = list(
        db.scalars(
            window.where(NewsItem.collected_at >= current - FRESH_WINDOW)
            .order_by(
                NewsItem.display_time.is_(None),
                NewsItem.display_time.desc(),
                NewsItem.id.desc(),
            )
            .limit(limit // 2)
        ).all()
    )
    older = db.scalars(
        window.where(NewsItem.id.not_in([item.id for item in fresh]))
        .order_by(_item_time().asc(), NewsItem.id.asc())
        .limit(limit - len(fresh))
    ).all()
    return [*fresh, *older]


def stale_items(
    db: Session, *, on_date: date | None = None, now: datetime | None = None
) -> list[NewsItem]:
    cutoff = (now or utcnow()) - STALE_AFTER
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
    envelope = envelope or {}
    status = envelope.get("api_error_status")
    # The result is the CLI's error message only when is_error is set; else it
    # is model text.
    text = " ".join(
        str(part)
        for part in (
            envelope.get("result") if envelope.get("is_error") else None,
            status,
            result.stderr,
        )
        if part
    ).lower()
    if str(status) == "401" or any(part in text for part in AUTH_ERROR_TEXT):
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
    unsupported = raw["unsupported"]
    return {
        "id": item_id,
        "summary": summary,
        "symbol_candidates": symbols,
        # No positive or negative call without enough source information.
        "impact_direction": "unknown" if unsupported else raw["impact_direction"],
        "impact_scope": raw["impact_scope"],
        "impact_rationale": _string(
            raw["impact_rationale"], f"{where} impact_rationale", RATIONALE_MAX_CHARS
        ),
        "unsupported": unsupported,
    }


@dataclass(frozen=True)
class Validated:
    """A checked answer: ``outputs`` per sent id, the ids that failed and why,
    and the ids answered that were not sent (never written)."""

    outputs: dict[int, dict[str, Any]]
    failures: dict[int, str]
    extra_ids: list[Any]


def _answer_id(raw: Any) -> int | None:
    value = raw.get("id") if isinstance(raw, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def validate_output(structured: Any, expected_ids: Sequence[int]) -> Validated:
    """Check the answer item by item (#450).

    An answer whose shape is wrong (not ``{"items": [...]}``) raises
    LlmBatchError and fails the whole batch.  Otherwise each sent id is checked
    on its own: left out, answered more than once, or not matching the schema,
    it goes to ``failures``; an answered id that was not sent is ignored.
    """

    structured = _object(structured, ("items",), "structured_output")
    if not isinstance(structured["items"], list):
        raise LlmBatchError("schema_mismatch", "structured_output.items must be a list")
    expected = set(expected_ids)
    answers: dict[int, list[Any]] = {}
    extra: list[Any] = []
    for index, raw in enumerate(structured["items"]):
        answer_id = _answer_id(raw)
        if answer_id is None or answer_id not in expected:
            extra.append(f"items[{index}]" if answer_id is None else answer_id)
            continue
        answers.setdefault(answer_id, []).append(raw)
    outputs: dict[int, dict[str, Any]] = {}
    failures: dict[int, str] = {}
    for news_id in expected_ids:
        found = answers.get(news_id, [])
        if not found:
            failures[news_id] = "missing from the answer"
        elif len(found) > 1:
            # Two answers for one item: neither is written.
            failures[news_id] = f"duplicate id: answered {len(found)} times"
        else:
            try:
                outputs[news_id] = _validate_item(found[0])
            except LlmBatchError as exc:
                failures[news_id] = str(exc)
    return Validated(outputs, failures, extra)


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
    model: str | None = None,
    keep_count: bool = True,
) -> None:
    # Only status, reason and audit links change; no ai_* field is written.
    row = _result_row(db, item.id) or _new_row(item)
    failures = item_failures(row) if keep_count else 0
    if status == "pending" and failures:
        # A whole-batch failure is not the item's: keep its count.
        error = f"{ITEM_FAILED} {failures}/{MAX_ITEM_ATTEMPTS} earlier; {error}"
    row.llm_model = model or row.llm_model or MODEL
    row.llm_input_hash = input_hash(item_input(item))
    row.llm_run_at = run_at
    row.llm_status = status
    row.llm_error = error[:500]
    row.ingestion_run_id = run.id
    row.raw_payload_id = raw_payload_id
    db.add(row)


def item_failures(row: NewsLlmResult | None) -> int:
    """Failures of this item alone so far, as ``llm_error`` records them."""

    if row is None or row.llm_status != "pending" or not row.llm_error:
        return 0
    match = _ITEM_FAILURES.match(row.llm_error)
    return int(match.group(1)) if match else 0


def _store_item_failure(
    db: Session,
    item: NewsItem,
    detail: str,
    *,
    run: IngestionRun,
    raw_payload_id: int,
    run_at: datetime,
    model: str | None,
) -> bool:
    """Record one more failure of this item; True when it is now rejected."""

    count = item_failures(_result_row(db, item.id)) + 1
    error = f"{ITEM_FAILED} {count}/{MAX_ITEM_ATTEMPTS}: {detail}"
    given_up = count >= MAX_ITEM_ATTEMPTS
    if given_up:
        error = f"{error[:450]}; not sent again"
    _store_status(
        db,
        item,
        "rejected" if given_up else "pending",
        error,
        run=run,
        raw_payload_id=raw_payload_id,
        run_at=run_at,
        model=model,
        keep_count=False,
    )
    return given_up


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
    run_at = utcnow()
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
        checked = validate_output(
            envelope.get("structured_output"), summary["news_ids"]
        )
        if not checked.outputs:
            # Nothing usable (``{"items": []}``, ids of another type): a fault of
            # the answer, not of each item, so no item's count goes up and none
            # is rejected for it; only a partly valid answer counts per item.
            news_id, detail = next(iter(checked.failures.items()))
            raise LlmBatchError(
                "schema_mismatch",
                f"no valid item in the answer ({len(checked.failures)} sent; "
                f"id {news_id}: {detail}; not sent back {checked.extra_ids[:5]})",
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
    rejected: list[int] = []
    item_failed: list[dict[str, Any]] = []
    given_up: list[int] = []
    for item, payload in zip(items, inputs):
        if item.id in checked.failures:
            # Only this item waits for the next run; the rest are written (#450).
            detail = checked.failures[item.id]
            item_failed.append({"news_id": item.id, "error": detail[:300]})
            if _store_item_failure(
                db,
                item,
                detail,
                run=run,
                raw_payload_id=raw_row.id,
                run_at=run_at,
                model=model,
            ):
                given_up.append(item.id)
            continue
        output = checked.outputs[item.id]
        missing = summary_numbers_missing(payload, output["summary"])
        if missing:
            # Only this item; its output stays in the raw payload.
            rejected.append(item.id)
            _store_status(
                db,
                item,
                "rejected",
                f"summary_check: numbers {', '.join(missing)} not in the source",
                run=run,
                raw_payload_id=raw_row.id,
                run_at=run_at,
                model=model,
            )
            continue
        _store_done(
            db,
            item,
            output,
            model=model,
            run=run,
            raw_payload_id=raw_row.id,
            run_at=run_at,
        )
    summary.update(
        status="done",
        model=model,
        usage=usage,
        rejected_ids=rejected,
        item_failed=item_failed,
        item_rejected_ids=given_up,
        extra_ids=checked.extra_ids,
    )
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

    current = now or utcnow()
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
        row.metadata_json = {**(row.metadata_json or {}), "reason": "abandoned"}
        row.finished_at = current
    if rows:
        db.commit()
    return [row.id for row in rows]


def _failed_run(db: Session, label_date: date, reason: str) -> IngestionRun:
    now = utcnow()
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
        started_at=utcnow(),
        metadata_json={},
    )
    db.add(run)
    db.commit()
    active = runner or run_claude_cli
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def metadata() -> dict[str, Any]:
        return _metadata(
            template, limit, base["date_filter"], results, skipped, len(stale)
        )

    try:
        _mark_stale(db, run, stale)
        _send_batches(
            db,
            run,
            batches,
            template,
            command,
            active,
            allowed,
            results,
            skipped,
            metadata,
        )
        return {**base, **_close_run(db, run, batches, results, skipped, metadata)}
    except Exception as exc:  # noqa: BLE001 - the run must not be left running
        # A write failed (database locked, constraint) or a bug: close the run as
        # failed with its reason and the calls already made, instead of leaving
        # it running until the next run calls it abandoned (#450).
        db.rollback()
        error = f"run_error: {type(exc).__name__}: {exc}"[:500]
        failed_run = db.get(IngestionRun, run.id)
        failed_run.status = "failed"
        failed_run.error = error
        failed_run.data_as_of = utcnow().isoformat()
        failed_run.finished_at = utcnow()
        failed_run.metadata_json = {
            **(failed_run.metadata_json or {}),
            "calls": len(results),
            "reason": "run_error",
        }
        db.commit()
        return {
            **base,
            "status": "failed",
            "reason": "run_error",
            "error": error,
            "run_id": run.id,
            "calls": len(results),
        }


def _mark_stale(db: Session, run: IngestionRun, stale: list[NewsItem]) -> None:
    stale_at = utcnow()
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


def _send_batches(
    db: Session,
    run: IngestionRun,
    batches: list[list[NewsItem]],
    template: str,
    command: list[str],
    runner: Runner,
    allowed: int,
    results: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    metadata: Callable[[], dict[str, Any]],
) -> None:
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
            outcome = _run_batch(db, run, number, batch, template, command, runner)
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
                    run_at=utcnow(),
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
        run.metadata_json = metadata()
        db.commit()


def _batch_counts(batch: dict[str, Any]) -> tuple[int, int, int]:
    """Items of one sent batch that are (done, pending, rejected)."""

    failed = len(batch.get("item_failed", []))
    given_up = len(batch.get("item_rejected_ids", []))
    checked = len(batch.get("rejected_ids", []))
    if batch["status"] != "done":
        return 0, len(batch["news_ids"]) - given_up, given_up
    done = len(batch["news_ids"]) - failed - checked
    return done, failed - given_up, checked + given_up


def _close_run(
    db: Session,
    run: IngestionRun,
    batches: list[list[NewsItem]],
    results: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    metadata: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    done_batches = [item for item in results if item["status"] == "done"]
    clean = [item for item in done_batches if not item.get("item_failed")]
    if not batches:
        status = "success"
    elif not results:
        status = "skipped"
    elif len(clean) == len(batches):
        status = "success"
    elif done_batches:
        status = "partial"
    else:
        status = "failed"
    errors: list[str] = []
    reasons: list[str] = []
    for item in results:
        if item["status"] != "done":
            errors.append(f"batch {item['batch']}: {item.get('error', item['reason'])}")
            reasons.append(item["reason"])
        elif item.get("item_failed"):
            ids = [entry["news_id"] for entry in item["item_failed"]]
            errors.append(f"batch {item['batch']}: {ITEM_FAILED} {ids}")
            reasons.append(ITEM_FAILED)
    for reason in sorted({item["reason"] for item in skipped}):
        count = sum(1 for item in skipped if item["reason"] == reason)
        errors.append(f"{reason}: {count} batch(es) skipped")
        reasons.append(reason)
    if status in ("failed", "partial") and not errors:
        # Never a failed or partial run without a reason (#450).
        errors.append(f"{status}: no failing batch was recorded")
        reasons.append("unknown")
    counts = [_batch_counts(item) for item in results]
    run.status = status
    run.records = sum(done for done, _pending, _rejected in counts)
    run.error = "; ".join(errors) or None
    run.data_as_of = utcnow().isoformat()
    run.metadata_json = metadata()
    if reasons:
        run.metadata_json = {
            **run.metadata_json,
            "reason": ",".join(dict.fromkeys(reasons)),
        }
    run.finished_at = utcnow()
    db.commit()
    return {
        "status": status,
        "run_id": run.id,
        "done": run.records,
        "rejected": sum(rejected for _done, _pending, rejected in counts),
        "pending": sum(pending for _done, pending, _rejected in counts),
        "item_failed": sum(len(item.get("item_failed", [])) for item in results),
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
