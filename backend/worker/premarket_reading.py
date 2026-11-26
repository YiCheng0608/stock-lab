"""The pre-market AI reading: prompt, ``claude -p``, checks and the stored rows (Issue #1041).

The call layer is ``worker.news_llm``'s (``preflight``, ``cli_arguments``,
``run_claude_cli``, ``parse_envelope``): the local Claude Code CLI in
headless mode with the user's subscription login, no API key, no tools, the
prompt on stdin in an empty directory.  The model is ``sonnet`` (#1002
decision 7118246729, 5).

- **Prompt**: ``prompts/<version>.md`` with the input snapshot after it in an
  ``<input>`` block.  Each version's text is pinned by its SHA-256
  (``PROMPTS``) and so is the output schema (``SCHEMA_SHA256``): changing
  either needs a new version.  ``SHADOW_PROMPT_VERSION``, when set, is read
  on the same input and stored as ``role=shadow`` (#1002 AC-3 D).
- **Checks** (``check``): an output with ``additions`` (#1 decision
  7187528140), the schema, each input stock exactly once and no other, every
  ``news:<id>`` in the input, and no order wording (``directive_words``:
  rating quotes and nouns such as 進場區 are not orders, #1002 AC-2 2/2
  observation 2).  A failed check is ``rejected``.  Kept in ``checks_json``
  without a rejection: a price in the reasons of a stock without usable rule
  levels (``prices_without_levels``, 3a, #1058; the view hides those texts).
- **Retries**: a timeout, an answer that is not the CLI's JSON, a CLI error
  or a schema mismatch is called once more; ``rate_limited``,
  ``not_logged_in`` and ``cli_not_started`` are not (``news_llm.FATAL_REASONS``),
  nor a failed content check.  Out of time (``deadline``) no new call starts.
- **Rows**: ``premarket_ai_readings`` gets one row per run with the input,
  every attempt (duration, usage, reason, raw capture) and the outcome;
  a done one also gets a ``premarket_ai_stocks`` row per stock.  Both only
  added (``store``).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import IngestionRun, PremarketAiReading, PremarketAiStock
from app.premarket_ai import (
    CHAMPION,
    DONE,
    FAILED,
    REJECTED,
    next_sequence,
)

from . import sources
from .news_llm import (
    CALL_TIMEOUT_SECONDS,
    FATAL_REASONS,
    LlmBatchError,
    Runner,
    _object,
    _usage,
    cli_arguments,
    parse_envelope,
)
from .pipeline import _upsert_raw_payload
from .premarket_input import Snapshot, StockMeta
from .price_mentions import price_mentions

PROMPT_VERSION = "premarket_v1"
PROMPT_DIR = Path(__file__).with_name("prompts")
# Pinned hashes of the prompt texts (LF line endings).  Editing a prompt
# without a new version fails the prompt version test.
PROMPTS = {
    "premarket_v1": "49ba5b94df3ea63cc5ed15d838676a20afda28f0f22d404039a3428460c33a4c",
}
# A new version read beside the champion on the same input (#1002 AC-3 D);
# at most one, None when there is none.
SHADOW_PROMPT_VERSION: str | None = None
MODEL = "sonnet"
MAX_ATTEMPTS = 2
RETRY_REASONS = frozenset({"timeout", "invalid_json", "cli_error", "schema"})
RUN_TYPE = "premarket_ai"
RAW_SOURCE = "premarket_ai"
RAW_ENDPOINT = f"claude -p --model {MODEL}"
REASON_MAX_CHARS = 120
ACTIONS = ("keep", "reprice", "defer")
STANCES = ("bullish", "bearish", "neutral")
CONFIDENCES = ("high", "medium", "low")
DIRECTIONS = ("positive", "negative", "mixed")
OUTPUT_KEYS = ("market", "sectors", "candidates", "data_gaps")
REPRICE_KEYS = ("max_gap_pct", "max_gap_down_pct", "min_risk_reward")

_REASON = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "refs"],
    "properties": {
        "text": {"type": "string"},
        "refs": {"type": "array", "items": {"type": "string"}},
    },
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(OUTPUT_KEYS),
    "properties": {
        "market": {
            "type": "object",
            "additionalProperties": False,
            "required": ["stance", "confidence", "reasons"],
            "properties": {
                "stance": {"enum": list(STANCES)},
                "confidence": {"enum": list(CONFIDENCES)},
                "reasons": {"type": "array", "items": {"$ref": "#/$defs/reason"}},
            },
        },
        "sectors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["group_id", "name", "direction", "reasons"],
                "properties": {
                    "group_id": {"type": "string"},
                    "name": {"type": "string"},
                    "direction": {"enum": list(DIRECTIONS)},
                    "reasons": {"type": "array", "items": {"$ref": "#/$defs/reason"}},
                },
            },
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                # reprice_rule is required on every stock, null unless reprice: an
                # optional one was left out of every reprice (#1041 AC-4 run).
                "required": ["symbol", "action", "reprice_rule", "reasons"],
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {"enum": list(ACTIONS)},
                    "reprice_rule": {
                        "anyOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": list(REPRICE_KEYS),
                                "properties": {
                                    key: {"type": "number"} for key in REPRICE_KEYS
                                },
                            },
                        ]
                    },
                    "reasons": {"type": "array", "items": {"$ref": "#/$defs/reason"}},
                },
            },
        },
        "data_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "$defs": {"reason": _REASON},
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SCHEMA_SHA256 = _sha256(
    json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
)


def prompt_text(version: str) -> str:
    return (
        (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    )


def build_prompt(template: str, payload: dict[str, Any]) -> str:
    # Escape angle brackets so news text cannot close or forge the <input> block.
    text = (
        json.dumps(payload, ensure_ascii=False, indent=1)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return f"{template.rstrip()}\n\n<input>\n{text}\n</input>\n"


# --- checks -----------------------------------------------------------------

_ORDER_VERBS = "買進|買入|賣出|進場|出場"
# A verb with one of these right before it is an order (#1002 AC-2 2/2, 2).
_ORDER_PREFIXES = (
    r"(?:建議|可以|可|宜|應該|應|請|今日|今天|明日|明天|立即|馬上|逢低|逢高|開盤|分批"
    r"|擇機|伺機|考慮|適合|不宜|暫不|不要|別|先行|先|直接|積極|準備)"
)
_DIRECTIVE = re.compile(rf"{_ORDER_PREFIXES}\s*(?:{_ORDER_VERBS})")
# An order prefix right before a compound word: 建議優先買進 is still an order
# (#1051 review 7195500836, 1).
_PREFIX_BEFORE_COMPOUND = re.compile(rf"{_ORDER_PREFIXES}\s*$")
_ALWAYS = re.compile(r"下單|掛單")
# Not an order: a rating quote (a broker's 買進 rating) ...
_RATING_BEFORE = re.compile(
    r"(?:評等|評級|初評|首評|調升|調降|升至|降至|重申|給予|券商|投顧|分析師|目標價|報告)"
)
_RATING_AFTER = re.compile(r"^\s*(?:評等|評級)")
# ... or a noun (進場區, 進場價).
_NOUN_AFTER = re.compile(r"^(?:區|價|點)")
RATING_LOOKBEHIND = 8
# A one-character prefix that is the end of a word is no order (#1051 review
# 7194545794, 3): 外資率先買進, 首先賣出, 市場反應賣出壓力.
COMPOUND_PREFIXES = frozenset(
    {
        "率先",
        "首先",
        "搶先",
        "優先",
        "事先",
        "預先",
        "原先",
        "特別",
        "分別",
        "區別",
        "反應",
        "回應",
        "因應",
        "相應",
        "對應",
        "響應",
        "供應",
        "效應",
        "便宜",
        "認可",
        "許可",
        "申請",
    }
)


def directive_words(texts: Sequence[str]) -> list[str]:
    """The order wordings in TEXTS, each with a little context."""

    found: list[str] = []
    for text in texts:
        for match in _ALWAYS.finditer(text):
            found.append(text[max(0, match.start() - 6) : match.end() + 6])
        for match in _DIRECTIVE.finditer(text):
            before = text[max(0, match.start() - RATING_LOOKBEHIND) : match.start()]
            after = text[match.end() :]
            if _RATING_BEFORE.search(before) or _RATING_AFTER.match(after):
                continue
            if _NOUN_AFTER.match(after):
                continue
            if (
                match.start() > 0
                and text[match.start() - 1 : match.start() + 1] in COMPOUND_PREFIXES
                and not _PREFIX_BEFORE_COMPOUND.search(text[: match.start() - 1])
            ):
                continue
            found.append(text[max(0, match.start() - 6) : match.end() + 6])
    return found


def _reasons(value: Any, where: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise LlmBatchError("schema_mismatch", f"{where} must be an array")
    out = []
    for index, reason in enumerate(value):
        reason = _object(reason, ("text", "refs"), f"{where}[{index}]")
        if not isinstance(reason["text"], str):
            raise LlmBatchError("schema_mismatch", f"{where}[{index}].text")
        refs = reason["refs"]
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise LlmBatchError("schema_mismatch", f"{where}[{index}].refs")
        out.append(reason)
    return out


def _enum(value: Any, allowed: Sequence[str], where: str) -> None:
    if value not in allowed:
        raise LlmBatchError("schema_mismatch", f"{where} not one of {list(allowed)}")


def validate_schema(output: Any) -> None:
    """Raise LlmBatchError(schema_mismatch) unless OUTPUT matches OUTPUT_SCHEMA."""

    output = _object(output, OUTPUT_KEYS, "output")
    market = _object(output["market"], ("stance", "confidence", "reasons"), "market")
    _enum(market["stance"], STANCES, "market.stance")
    _enum(market["confidence"], CONFIDENCES, "market.confidence")
    _reasons(market["reasons"], "market.reasons")
    if not isinstance(output["sectors"], list):
        raise LlmBatchError("schema_mismatch", "sectors must be an array")
    for index, sector in enumerate(output["sectors"]):
        where = f"sectors[{index}]"
        sector = _object(sector, ("group_id", "name", "direction", "reasons"), where)
        if not isinstance(sector["group_id"], str) or not isinstance(
            sector["name"], str
        ):
            raise LlmBatchError("schema_mismatch", f"{where} group_id/name")
        _enum(sector["direction"], DIRECTIONS, f"{where}.direction")
        _reasons(sector["reasons"], f"{where}.reasons")
    if not isinstance(output["candidates"], list):
        raise LlmBatchError("schema_mismatch", "candidates must be an array")
    for index, item in enumerate(output["candidates"]):
        where = f"candidates[{index}]"
        item = _object(item, ("symbol", "action", "reprice_rule", "reasons"), where)
        if not isinstance(item["symbol"], str):
            raise LlmBatchError("schema_mismatch", f"{where}.symbol")
        _enum(item["action"], ACTIONS, f"{where}.action")
        _reasons(item["reasons"], f"{where}.reasons")
        if (item["action"] == "reprice") != (item["reprice_rule"] is not None):
            raise LlmBatchError(
                "schema_mismatch",
                f"{where} reprice_rule must be an object for reprice and null otherwise",
            )
        if item["reprice_rule"] is not None:
            rule = _object(item["reprice_rule"], REPRICE_KEYS, f"{where}.reprice_rule")
            for key in REPRICE_KEYS:
                value = rule[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise LlmBatchError(
                        "schema_mismatch", f"{where}.reprice_rule.{key}"
                    )
    gaps = output["data_gaps"]
    if not isinstance(gaps, list) or not all(isinstance(gap, str) for gap in gaps):
        raise LlmBatchError("schema_mismatch", "data_gaps must be an array of strings")


def payload_news_ids(payload: dict[str, Any]) -> set[int]:
    ids = {item["id"] for item in payload.get("market_news", [])}
    for stock in payload.get("candidates", []):
        ids |= {item["id"] for item in stock.get("news", [])}
    return ids


_NEWS_REF = re.compile(r"^news:(\d+)$")


def _all_reasons(output: dict[str, Any]) -> list[dict[str, Any]]:
    reasons = list(output["market"]["reasons"])
    for sector in output["sectors"]:
        reasons += sector["reasons"]
    for item in output["candidates"]:
        reasons += item["reasons"]
    return reasons


def cited_titles(output: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """The input titles of the news any reason of OUTPUT cites: the ones a reason may
    quote (the same set T30 has on the page, #1058)."""

    titles: dict[int, str] = {}
    for item in list(payload.get("market_news", [])) + [
        news
        for stock in payload.get("candidates", [])
        for news in stock.get("news", [])
    ]:
        if isinstance(item.get("id"), int) and item.get("title"):
            titles.setdefault(item["id"], item["title"])
    cited = {
        int(match.group(1))
        for reason in _all_reasons(output)
        for ref in reason["refs"]
        if (match := _NEWS_REF.match(ref))
    }
    return [titles[news_id] for news_id in sorted(cited) if news_id in titles]


def prices_without_levels(
    output: dict[str, Any], payload: dict[str, Any], with_levels: set[str]
) -> list[dict[str, Any]]:
    """3a (#1058): the price wordings (``price_mentions``) in the reasons of a stock
    without usable rule levels, and in the data gaps that name such a stock.  Not a
    rejection: ``app.premarket_ai.view`` shows those texts as one fixed line."""

    titles = cited_titles(output, payload)
    # Every input stock's 「<代號> <名稱>」 is no 「<代號> 元」 (#1060 review 1).
    pairs = [
        (stock["symbol"], stock.get("name") or "") for stock in payload["candidates"]
    ]
    found: list[dict[str, Any]] = []
    for item in output["candidates"]:
        if item["symbol"] in with_levels:
            continue
        for index, reason in enumerate(item["reasons"]):
            prices = price_mentions(reason["text"], titles, pairs)
            if prices:
                found.append(
                    {
                        "symbol": item["symbol"],
                        "where": f"reasons[{index}]",
                        "prices": prices,
                    }
                )
    names = [
        (stock["symbol"], stock.get("name") or "")
        for stock in payload["candidates"]
        if stock["symbol"] not in with_levels
    ]
    for index, gap in enumerate(output["data_gaps"]):
        for symbol, name in names:
            named = re.search(
                rf"(?<![0-9A-Za-z]){re.escape(symbol)}(?![0-9A-Za-z])", gap
            )
            if named or (name and name in gap):
                prices = price_mentions(gap, titles, pairs)
                if prices:
                    found.append(
                        {
                            "symbol": symbol,
                            "where": f"data_gaps[{index}]",
                            "prices": prices,
                        }
                    )
                break
    return found


@dataclass
class Checked:
    reason: str | None
    detail: str
    checks: dict[str, Any]


def check(output: Any, payload: dict[str, Any]) -> Checked:
    """The checks of one answer, in order; the first failure is the reason."""

    checks: dict[str, Any] = {}
    if isinstance(output, dict) and "additions" in output:
        checks["additions"] = "present"
        return Checked("additions_present", "the output has additions", checks)
    checks["additions"] = "absent"
    try:
        validate_schema(output)
    except LlmBatchError as exc:
        checks["schema"] = exc.detail
        return Checked("schema", exc.detail, checks)
    checks["schema"] = "pass"
    expected = [item["symbol"] for item in payload["candidates"]]
    got = [item["symbol"] for item in output["candidates"]]
    seen: set[str] = set()
    duplicate = sorted({symbol for symbol in got if symbol in seen or seen.add(symbol)})
    coverage = {
        "missing": sorted(set(expected) - set(got)),
        "extra": sorted(set(got) - set(expected)),
        "duplicate": duplicate,
    }
    checks["coverage"] = coverage
    # A today-list stock without a signal has strategy_levels={"status":
    # "no_levels"}: nothing to reprice either (review 7194545794, suggestion 3).
    with_levels = {
        item["symbol"]
        for item in payload["candidates"]
        if "strategy_levels" in item
        and item["strategy_levels"].get("status") != "no_levels"
    }
    without = sorted(
        item["symbol"]
        for item in output["candidates"]
        if item["action"] == "reprice" and item["symbol"] not in with_levels
    )
    checks["reprice_without_levels"] = without
    ids = payload_news_ids(payload)
    unknown = sorted(
        {
            ref
            for reason in _all_reasons(output)
            for ref in reason["refs"]
            if ref.startswith("news")
            and (
                (match := _NEWS_REF.match(ref)) is None
                or int(match.group(1)) not in ids
            )
        }
    )
    checks["unknown_news_refs"] = unknown
    texts = [reason["text"] for reason in _all_reasons(output)] + list(
        output["data_gaps"]
    )
    words = directive_words(texts)
    checks["directive_words"] = words
    groups = set(payload.get("groups", {}))
    checks["unknown_group_ids"] = sorted(
        {sector["group_id"] for sector in output["sectors"]} - groups
    )
    checks["long_reasons"] = sum(
        1 for reason in _all_reasons(output) if len(reason["text"]) > REASON_MAX_CHARS
    )
    checks["prices_without_levels"] = prices_without_levels(
        output, payload, with_levels
    )
    if any(coverage.values()):
        return Checked("coverage", json.dumps(coverage, ensure_ascii=False), checks)
    if without:
        return Checked("reprice_without_levels", ",".join(without), checks)
    if unknown:
        return Checked("unknown_news_ref", ",".join(unknown), checks)
    if words:
        return Checked("directive_words", " | ".join(words)[:300], checks)
    return Checked(None, "", checks)


# --- calls ------------------------------------------------------------------


@dataclass
class Outcome:
    role: str
    prompt_version: str
    prompt_sha256: str
    status: str
    reason: str | None
    error: str | None
    output: dict[str, Any] | None
    checks: dict[str, Any]
    attempts: list[dict[str, Any]] = field(default_factory=list)
    llm_model: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_ms(self) -> int:
        return sum(int(item.get("duration_ms", 0)) for item in self.attempts)

    @property
    def usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for attempt in self.attempts:
            for key, value in (attempt.get("usage") or {}).items():
                total[key] = total.get(key, 0) + int(value)
        return total


def _status_of(reason: str) -> str:
    """A content or schema failure is rejected; a call that gave no answer failed."""

    if reason in ("schema",) or reason in (
        "additions_present",
        "coverage",
        "reprice_without_levels",
        "unknown_news_ref",
        "directive_words",
    ):
        return REJECTED
    return FAILED


def read(
    snapshot: Snapshot,
    version: str,
    role: str,
    command: list[str],
    runner: Runner,
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    capture: Callable[[dict[str, Any], datetime, dict[str, Any]], None] | None = None,
) -> Outcome:
    """Call the CLI on SNAPSHOT with VERSION's prompt, at most MAX_ATTEMPTS times.

    ``deadline`` (on ``clock``): no call starts when fewer than
    CALL_TIMEOUT_SECONDS are left before it.  ``capture`` keeps an attempt's
    prompt and response as raw (``RawCapture``) for the rows written at the end.
    """

    template = prompt_text(version)
    prompt = build_prompt(template, snapshot.payload)
    argv = [*command, *cli_arguments(MODEL, OUTPUT_SCHEMA)]
    outcome = Outcome(
        role=role,
        prompt_version=version,
        prompt_sha256=_sha256(template),
        status=FAILED,
        reason="not_called",
        error=None,
        output=None,
        checks={},
        started_at=utcnow(),
    )
    if PROMPTS.get(version) != outcome.prompt_sha256:
        # An edited prompt is a new version (#1002 AC-3 D): nothing is called.
        outcome.reason = "prompt_hash_mismatch"
        outcome.error = (
            f"{version} sha256 {outcome.prompt_sha256} != {PROMPTS.get(version)}"
        )
        outcome.finished_at = utcnow()
        return outcome
    for number in range(1, MAX_ATTEMPTS + 1):
        if deadline is not None and deadline - clock() < CALL_TIMEOUT_SECONDS:
            # Past the job's limit before a call could end: the first is not made
            # (no_time), a retry is left out and the first answer's outcome stays.
            if number == 1:
                outcome.reason = "no_time"
            else:
                outcome.checks["retry_skipped"] = "no_time"
            break
        started = clock()
        result = runner(prompt, argv)
        duration_ms = int((clock() - started) * 1000)
        run_at = utcnow()
        attempt: dict[str, Any] = {"number": number, "duration_ms": duration_ms}
        if capture is not None:
            capture(
                {
                    "prompt_version": version,
                    "role": role,
                    "attempt": number,
                    "argv": argv,
                    "prompt": prompt,
                    "returncode": result.returncode,
                    "timed_out": result.timed_out,
                    "error": result.error,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_ms": duration_ms,
                },
                run_at,
                attempt,
            )
        outcome.attempts.append(attempt)
        try:
            envelope = parse_envelope(result)
        except LlmBatchError as exc:
            attempt["reason"] = exc.reason
            outcome.status, outcome.reason = FAILED, exc.reason
            outcome.error = str(exc)[:500]
            if exc.reason in FATAL_REASONS or exc.reason not in RETRY_REASONS:
                break
            continue
        model, usage = _usage(envelope)
        attempt["model"], attempt["usage"] = model, usage
        outcome.llm_model = model or outcome.llm_model
        output = envelope.get("structured_output")
        checked = check(output, snapshot.payload)
        outcome.checks = checked.checks
        outcome.output = output if isinstance(output, dict) else None
        if checked.reason is None:
            attempt["reason"] = None
            outcome.status, outcome.reason, outcome.error = DONE, None, None
            break
        attempt["reason"] = checked.reason
        outcome.status = _status_of(checked.reason)
        outcome.reason = checked.reason
        outcome.error = checked.detail[:500]
        if checked.reason not in RETRY_REASONS:
            break
    outcome.finished_at = utcnow()
    return outcome


# --- rows -------------------------------------------------------------------


class RawCapture:
    """``capture`` for ``read``: writes each attempt's raw file at once and keeps it
    in memory; ``store_rows`` adds the ``raw_payloads`` rows later.

    Nothing is written to the database during the calls (#1051 review 7194545794,
    1 and 2): a flush there would hold SQLite's write lock through the next call
    (up to 300 seconds; the other writers give up after 30), and maintenance may
    start meanwhile.
    """

    def __init__(self) -> None:
        self.pending: list[tuple[Any, dict[str, Any]]] = []

    def __call__(
        self, payload: dict[str, Any], run_at: datetime, attempt: dict[str, Any]
    ) -> None:
        raw = sources.capture_payload(
            RAW_SOURCE, RAW_ENDPOINT, payload, run_at.isoformat(), collected_at=run_at
        )
        self.pending.append((raw, attempt))

    def store_rows(self, db: Session, run: IngestionRun) -> None:
        """Add the raw rows of RUN and put their ids on the attempts."""

        for raw, attempt in self.pending:
            attempt["raw_payload_id"] = _upsert_raw_payload(db, run, raw).id
        self.pending = []


def _stock_row(
    reading: PremarketAiReading, meta: StockMeta, item: dict[str, Any]
) -> PremarketAiStock:
    return PremarketAiStock(
        reading_id=reading.id,
        session_date=reading.session_date,
        prompt_version=reading.prompt_version,
        role=reading.role,
        instrument_id=meta.instrument_id,
        symbol=meta.symbol,
        position=meta.position,
        on_today_list=meta.on_today_list,
        daily_candidate_id=meta.daily_candidate_id,
        pool_item_id=meta.pool_item_id,
        pool_sources_json=meta.pool_sources,
        levels_json=meta.levels,
        action=item["action"],
        reprice_rule_json=item["reprice_rule"],
        reasons_json=item["reasons"],
    )


def store(
    db: Session,
    snapshot: Snapshot,
    outcome: Outcome,
    *,
    trigger: str,
    ingestion_run_id: int | None,
) -> PremarketAiReading:
    """Add the run's row (and a done one's stock rows); nothing stored is changed."""

    reading = PremarketAiReading(
        session_date=snapshot.session_date,
        list_date=snapshot.list_date,
        role=outcome.role,
        sequence=next_sequence(
            db, snapshot.session_date, outcome.prompt_version, outcome.role
        ),
        trigger=trigger,
        prompt_version=outcome.prompt_version,
        prompt_sha256=outcome.prompt_sha256,
        schema_sha256=SCHEMA_SHA256,
        model_alias=MODEL,
        llm_model=outcome.llm_model,
        pool_phase=snapshot.pool_phase,
        cutoff_at=snapshot.cutoff_at,
        input_hash=snapshot.hash,
        input_json=snapshot.payload,
        status=outcome.status,
        reason=outcome.reason,
        error=outcome.error,
        output_json=outcome.output,
        checks_json=outcome.checks,
        attempts=len(outcome.attempts),
        attempts_json=outcome.attempts,
        duration_ms=outcome.duration_ms,
        usage_json=outcome.usage,
        ingestion_run_id=ingestion_run_id,
        started_at=outcome.started_at or utcnow(),
        finished_at=outcome.finished_at or utcnow(),
    )
    db.add(reading)
    db.flush()
    if outcome.status == DONE and outcome.output is not None:
        by_symbol = {item["symbol"]: item for item in outcome.output["candidates"]}
        for meta in snapshot.stocks:
            db.add(_stock_row(reading, meta, by_symbol[meta.symbol]))
        db.flush()
    return reading


def snapshot_of(db: Session, reading: PremarketAiReading) -> Snapshot:
    """The stored input of READING as a snapshot (a shadow reads the champion's input)."""

    from app.premarket_ai import stocks

    rows = stocks(db, reading.id)
    by_symbol = {row.symbol: row for row in rows}
    metas = []
    for position, item in enumerate(reading.input_json["candidates"], start=1):
        row = by_symbol[item["symbol"]]
        metas.append(
            StockMeta(
                instrument_id=row.instrument_id,
                symbol=row.symbol,
                position=position,
                on_today_list=row.on_today_list,
                daily_candidate_id=row.daily_candidate_id,
                pool_item_id=row.pool_item_id,
                pool_sources=list(row.pool_sources_json),
                levels=row.levels_json,
            )
        )
    return Snapshot(
        session_date=reading.session_date,
        list_date=reading.list_date,
        cutoff_at=reading.cutoff_at,
        pool_phase=reading.pool_phase,
        payload=reading.input_json,
        stocks=metas,
        news_ids=payload_news_ids(reading.input_json),
    )


def roles() -> list[tuple[str, str]]:
    """(version, role) of each reading a run makes: the champion, then the shadow."""

    out = [(PROMPT_VERSION, CHAMPION)]
    if SHADOW_PROMPT_VERSION:
        from app.premarket_ai import SHADOW

        out.append((SHADOW_PROMPT_VERSION, SHADOW))
    return out
