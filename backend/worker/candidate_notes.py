"""Candidate LLM notes: why each daily candidate was selected, how to read its
entry zone, stop and targets, and what to watch, via ``claude -p``.

Runs after ``candidates``.  The input of a candidate is only what is already
stored: the ``daily_candidates`` row (rank, score, components, rule reasons,
groups), its signal's levels and the news the row links to with their
summaries.  The output is inference kept in ``candidate_llm_notes``, one row
per candidate and prompt version; it never changes the score, rank or
selection.

Calls, environment and error handling follow ``worker.news_llm``: the local
Claude Code CLI in headless mode with the user's subscription login (no API
key).  A failing batch (timeout, invalid JSON, schema mismatch) marks its
candidates ``pending`` and the other batches still run; a failure every later
call would repeat (not logged in, rate limit, CLI not started) stops the run.
A done row is never sent again for the same prompt version; pending rows are
retried by the next run for that date.  Every call stores its prompt and
response as raw and its token usage and duration on the ``candidate_notes``
ingestion run.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import desc, inspect, select
from sqlalchemy.orm import Session

from app.candidate_view import COMPONENT_LABELS, NULL_EXPLANATIONS, _levels
from app.domain import CANDIDATE_NOTE_PROMPT_VERSION, CANDIDATE_SCORE_VERSION
from app.models import (
    CandidateLlmNote,
    CandidateRun,
    DailyCandidate,
    IngestionRun,
    Instrument,
    NewsItem,
    NewsLlmResult,
    Signal,
)
from app.strategies import REGISTRY

from . import pipeline, sources
from .candidates import _taipei_news_date
from .news_llm import (
    _USAGE_KEYS,
    FATAL_REASONS,
    LlmBatchError,
    Runner,
    _object,
    _string,
    _usage,
    cli_arguments,
    input_hash,
    cli_problem as news_cli_problem,
    parse_envelope,
    run_claude_cli,
)
from .news_sources import TAIPEI
from .pipeline import _upsert_raw_payload

PROMPT_VERSION = CANDIDATE_NOTE_PROMPT_VERSION
PROMPT_PATH = Path(__file__).with_name("prompts") / f"{PROMPT_VERSION}.md"
# Pinned hash of the prompt text (LF line endings).  Editing the prompt
# without a new PROMPT_VERSION fails the prompt version test.
PROMPT_SHA256 = "ff490fc15ba185d2edc300da9f615992dd2ec74ca98beb615b29027d371628ff"
MODEL = "sonnet"
BATCH_SIZE = 5
# Calls per Taipei day across all candidate_notes runs (a list has at most
# 20 candidates, 4 calls); the subscription quota is shared.
DAILY_CALL_LIMIT = 8
# The daily task is stopped after 2.5 hours and never runs twice at once, so
# a candidate_notes run still running after that long lost its process.
ABANDONED_AFTER = timedelta(hours=2, minutes=30)
NEWS_LIMIT = 5
NEWS_SUMMARY_CHARS = 200
SELECTION_MAX_CHARS = 120
LEVELS_MAX_CHARS = 160
RISKS_MAX_CHARS = 120
RUN_TYPE = "candidate_notes"
RAW_SOURCE = "candidate_notes"
RAW_ENDPOINT = f"claude -p --model {MODEL}"
BOARD_LABELS = {"industry": "產業", "theme": "題材"}
# Only the native claude.exe on Windows, like news-llm (news_llm.cli_problem).
IS_WINDOWS = sys.platform == "win32"


def cli_problem() -> tuple[list[str] | None, str | None]:
    """news_llm.cli_problem for this module's platform."""

    return news_cli_problem(windows=IS_WINDOWS)


_NOTE_FIELDS = ("id", "selection", "levels", "risks")
_NOTE_LIMITS = {
    "selection": SELECTION_MAX_CHARS,
    "levels": LEVELS_MAX_CHARS,
    "risks": RISKS_MAX_CHARS,
}
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
                "required": list(_NOTE_FIELDS),
                "properties": {
                    "id": {"type": "integer"},
                    **{
                        key: {"type": "string", "maxLength": limit}
                        for key, limit in _NOTE_LIMITS.items()
                    },
                },
            },
        }
    },
}


def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def prompt_sha256(text: str | None = None) -> str:
    return hashlib.sha256((text or prompt_text()).encode("utf-8")).hexdigest()


def _percent(value: Any) -> int | None:
    return round(value * 100) if isinstance(value, (int, float)) else None


def _news_inputs(
    db: Session, row: DailyCandidate, run: CandidateRun
) -> list[dict[str, Any]]:
    """The row's linked news (stored at scoring time), newest first."""

    news = (row.components_json or {}).get("news_sentiment") or {}
    ids = [item for item in news.get("news_ids") or [] if isinstance(item, int)]
    if not ids:
        return []
    prompt_version = (
        (run.config_json or {})
        .get("components", {})
        .get("news_sentiment", {})
        .get("llm_prompt_version")
    )
    results = {
        result.news_item_id: result
        for result in db.scalars(
            select(NewsLlmResult).where(
                NewsLlmResult.news_item_id.in_(ids),
                NewsLlmResult.prompt_version == prompt_version,
                NewsLlmResult.llm_status == "done",
            )
        )
    }
    items = db.scalars(
        select(NewsItem)
        .where(NewsItem.id.in_(ids))
        .order_by(desc(NewsItem.display_time), desc(NewsItem.id))
        .limit(NEWS_LIMIT)
    ).all()
    entries = []
    for item in items:
        result = results.get(item.id)
        day = _taipei_news_date(item)
        ai_summary = result.ai_summary if result is not None else None
        entries.append(
            {
                "date": day.isoformat() if day else None,
                "title": item.title,
                "summary": ai_summary or (item.summary or "")[:NEWS_SUMMARY_CHARS],
                "summary_is_ai": bool(ai_summary),
                "ai_direction": result.ai_impact_direction if result else None,
            }
        )
    return entries


def candidate_input(
    db: Session, row: DailyCandidate, run: CandidateRun
) -> dict[str, Any]:
    """The stored facts of one candidate sent to the LLM (and hashed)."""

    instrument = db.get(Instrument, row.instrument_id)
    levels = _levels(db.get(Signal, row.signal_id))
    stored = row.components_json or {}
    components = {}
    for key, label in COMPONENT_LABELS.items():
        component = stored.get(key) or {}
        reason = component.get("null_reason")
        components[label] = {
            "score": _percent(component.get("score")),
            "null_explanation": NULL_EXPLANATIONS.get(reason, reason)
            if reason
            else None,
        }
    return {
        "id": row.id,
        "rank": row.rank,
        "symbol": f"{instrument.exchange}:{instrument.symbol}",
        "name": instrument.name,
        "strategy": REGISTRY[row.strategy].label_zh
        if row.strategy in REGISTRY
        else row.strategy,
        "trading_date": row.trading_date.isoformat(),
        "levels": {
            "entry_zone": levels["entry_zone"],
            "stop": levels["invalid_price"],
            "target_1": levels["target_1"],
            "target_2": levels["target_2"],
            "risk_reward": levels["risk_reward"],
            "earliest_execution_date": levels["earliest_execution_date"],
        },
        "total_score": _percent(row.total_score),
        "weight_coverage": _percent(row.weight_coverage),
        "components": components,
        "reasons": [
            {"text": reason.get("text"), "inference": bool(reason.get("inference"))}
            for reason in row.reasons_json or []
        ],
        "groups": [
            {
                "name": group.get("name"),
                "board": BOARD_LABELS.get(group.get("board"), group.get("board")),
                "rank": group.get("rank") if group.get("qualified") else None,
                "board_size": group.get("board_size")
                if group.get("qualified")
                else None,
            }
            for group in row.groups_json or []
        ],
        "news": _news_inputs(db, row, run),
    }


def build_prompt(template: str, inputs: list[dict[str, Any]]) -> str:
    # Escape angle brackets so stored text cannot close or forge the block.
    data = (
        json.dumps(inputs, ensure_ascii=False, indent=1)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return f"{template.rstrip()}\n\n<candidates>\n{data}\n</candidates>\n"


def validate_output(
    structured: Any, expected_ids: Sequence[int]
) -> dict[int, dict[str, str]]:
    """Validate the whole response; any problem fails the whole batch."""

    structured = _object(structured, ("items",), "structured_output")
    if not isinstance(structured["items"], list):
        raise LlmBatchError("schema_mismatch", "structured_output.items must be a list")
    results: dict[int, dict[str, str]] = {}
    for raw in structured["items"]:
        raw = _object(raw, _NOTE_FIELDS, "item")
        item_id = raw["id"]
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            raise LlmBatchError("schema_mismatch", "id must be an integer")
        if item_id in results:
            raise LlmBatchError("schema_mismatch", f"duplicate id {item_id}")
        note = {}
        for key, limit in _NOTE_LIMITS.items():
            text = _string(raw[key], f"item {item_id} {key}", limit)
            if not text:
                raise LlmBatchError("schema_mismatch", f"item {item_id} {key} empty")
            note[key] = text
        results[item_id] = note
    expected = set(expected_ids)
    if set(results) != expected:
        missing = sorted(expected - set(results))
        extra = sorted(set(results) - expected)
        raise LlmBatchError("schema_mismatch", f"ids missing {missing} extra {extra}")
    return results


def _note_row(db: Session, row: DailyCandidate) -> CandidateLlmNote:
    note = db.scalar(
        select(CandidateLlmNote).where(
            CandidateLlmNote.daily_candidate_id == row.id,
            CandidateLlmNote.prompt_version == PROMPT_VERSION,
        )
    )
    if note is None:
        note = CandidateLlmNote(
            daily_candidate_id=row.id,
            candidate_run_id=row.candidate_run_id,
            trading_date=row.trading_date,
            prompt_version=PROMPT_VERSION,
        )
    return note


def _store(
    db: Session,
    row: DailyCandidate,
    payload: dict[str, Any],
    *,
    run: IngestionRun,
    raw_payload_id: int | None,
    run_at: datetime,
    note: dict[str, str] | None = None,
    model: str | None = None,
    error: str | None = None,
) -> None:
    stored = _note_row(db, row)
    if stored.llm_status == "done":
        # Written meanwhile by another run for this prompt version: kept as is.
        return
    stored.llm_input_hash = input_hash(payload)
    stored.llm_run_at = run_at
    stored.ingestion_run_id = run.id
    stored.raw_payload_id = raw_payload_id
    if note is None:
        # Only status, reason and audit links change; no model or ai_* field
        # is written, since nothing was generated.
        stored.llm_status = "pending"
        stored.llm_error = (error or "")[:500]
    else:
        stored.llm_model = model or MODEL
        stored.llm_status = "done"
        stored.llm_error = None
        stored.ai_selection = note["selection"]
        stored.ai_levels = note["levels"]
        stored.ai_risks = note["risks"]
    db.add(stored)


def _run_batch(
    db: Session,
    run: IngestionRun,
    number: int,
    batch: list[tuple[DailyCandidate, dict[str, Any]]],
    template: str,
    command: list[str],
    runner: Runner,
) -> dict[str, Any]:
    inputs = [payload for _row, payload in batch]
    prompt = build_prompt(template, inputs)
    argv = [*command, *cli_arguments(MODEL, OUTPUT_SCHEMA)]
    started = time.monotonic()
    result = runner(prompt, argv)
    duration_ms = int((time.monotonic() - started) * 1000)
    run_at = datetime.utcnow()
    ids = [row.id for row, _payload in batch]
    summary: dict[str, Any] = {
        "batch": number,
        "candidate_ids": ids,
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
        notes = validate_output(envelope.get("structured_output"), ids)
    except LlmBatchError as exc:
        if envelope is not None:
            summary["model"], summary["usage"] = _usage(envelope)
        for row, payload in batch:
            _store(
                db,
                row,
                payload,
                run=run,
                raw_payload_id=raw_row.id,
                run_at=run_at,
                error=str(exc),
            )
        summary.update(status="pending", reason=exc.reason, error=str(exc)[:500])
        return summary
    model, usage = _usage(envelope)
    for row, payload in batch:
        _store(
            db,
            row,
            payload,
            run=run,
            raw_payload_id=raw_row.id,
            run_at=run_at,
            note=notes[row.id],
            model=model,
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
    trading_date: date,
    candidate_run_id: int,
    results: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    calls: int,
) -> dict[str, Any]:
    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(template),
        "model": MODEL,
        "batch_size": BATCH_SIZE,
        "trading_date": trading_date.isoformat(),
        "candidate_run_id": candidate_run_id,
        "calls": calls,
        "daily_call_limit": DAILY_CALL_LIMIT,
        "skipped_batches": skipped,
        "usage_total": _usage_total(results),
        "duration_ms_total": sum(int(item.get("duration_ms", 0)) for item in results),
        "batches": results,
    }


def close_abandoned_runs(db: Session, now: datetime | None = None) -> list[int]:
    """Mark candidate_notes runs left running past ABANDONED_AFTER as failed."""

    current = now or datetime.utcnow()
    rows = db.scalars(
        select(IngestionRun).where(
            IngestionRun.run_type == RUN_TYPE,
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


def _calls_today(db: Session, run_date: date) -> int:
    runs = db.scalars(
        select(IngestionRun).where(
            IngestionRun.run_type == RUN_TYPE, IngestionRun.run_date == run_date
        )
    ).all()
    return sum(int((run.metadata_json or {}).get("calls", 0)) for run in runs)


def _failed_run(db: Session, label_date: date, reason: str) -> IngestionRun:
    now = datetime.utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
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


def _candidate_run(db: Session, trading_date: date | None) -> CandidateRun | None:
    query = select(CandidateRun).where(
        CandidateRun.score_version == CANDIDATE_SCORE_VERSION
    )
    if trading_date is not None:
        query = query.where(CandidateRun.trading_date == trading_date)
    return db.scalar(query.order_by(desc(CandidateRun.trading_date)).limit(1))


def run_candidate_notes(
    db: Session,
    trading_date: date | None = None,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    runner: Runner | None = None,
    run_date: date | None = None,
) -> dict[str, Any]:
    """Write the notes of one candidate run (default: the latest)."""

    label_date = run_date or datetime.now(TAIPEI).date()
    base: dict[str, Any] = {
        "run_date": label_date.isoformat(),
        "prompt_version": PROMPT_VERSION,
        "records": 0,
    }
    if not dry_run:
        abandoned = close_abandoned_runs(db)
        if abandoned:
            base["abandoned_runs"] = abandoned
    candidate_run = _candidate_run(db, trading_date)
    if candidate_run is None:
        return {
            **base,
            "status": "no_data",
            "reason": "no_candidate_run",
            "trading_date": trading_date.isoformat() if trading_date else None,
        }
    base.update(
        trading_date=candidate_run.trading_date.isoformat(),
        candidate_run_id=candidate_run.id,
    )
    rows = db.scalars(
        select(DailyCandidate)
        .where(DailyCandidate.candidate_run_id == candidate_run.id)
        .order_by(DailyCandidate.rank)
    ).all()
    if not rows:
        return {**base, "status": "no_data", "reason": "no_candidates"}
    done = set(
        db.scalars(
            select(CandidateLlmNote.daily_candidate_id).where(
                CandidateLlmNote.candidate_run_id == candidate_run.id,
                CandidateLlmNote.prompt_version == PROMPT_VERSION,
                CandidateLlmNote.llm_status == "done",
            )
        )
    )
    todo = [row for row in rows if row.id not in done]
    base.update(candidates=len(rows), already_done=len(done))
    if limit is not None:
        # The best ranked candidates still without a note; the rest wait.
        base["not_selected"] = max(len(todo) - limit, 0)
        todo = todo[:limit]
    if not todo:
        # Same date and prompt version: nothing is sent or rewritten.
        return {**base, "status": "success", "already_complete": True}
    command, problem = cli_problem()
    if problem is not None:
        # A configuration error writes no note rows.
        if dry_run:
            return {**base, "status": "failed", "reason": problem}
        run = _failed_run(db, label_date, problem)
        return {**base, "status": "failed", "reason": problem, "run_id": run.id}
    assert command is not None
    batches = [
        todo[start : start + BATCH_SIZE] for start in range(0, len(todo), BATCH_SIZE)
    ]
    used = _calls_today(db, label_date)
    allowed = max(DAILY_CALL_LIMIT - used, 0)
    if dry_run:
        return {
            **base,
            "status": "dry_run",
            "calls_used_today": used,
            "batches": [[row.id for row in batch] for batch in batches],
            "would_call": min(len(batches), allowed),
        }
    template = prompt_text()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="claude-cli",
        run_date=label_date,
        status="running",
        records=0,
        started_at=datetime.utcnow(),
        metadata_json={},
    )
    db.add(run)
    db.commit()
    active = runner or run_claude_cli
    calls = 0

    def counted(prompt: str, argv: Sequence[str]):
        # Only real CLI invocations count toward the daily limit.
        nonlocal calls
        calls += 1
        return active(prompt, argv)

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    unbuilt: list[dict[str, Any]] = []
    stop_reason: str | None = None
    try:
        for number, batch in enumerate(batches, start=1):
            ids = [row.id for row in batch]
            if stop_reason is not None:
                skipped.append(
                    {"batch": number, "candidate_ids": ids, "reason": stop_reason}
                )
                continue
            if calls >= allowed:
                skipped.append(
                    {
                        "batch": number,
                        "candidate_ids": ids,
                        "reason": "daily_call_limit",
                    }
                )
                continue
            # A candidate whose input cannot be built stays pending on its own;
            # the rest of its batch is still sent.
            payloads: list[tuple[DailyCandidate, dict[str, Any]]] = []
            failed_inputs: list[tuple[DailyCandidate, str]] = []
            for row in batch:
                try:
                    payloads.append((row, candidate_input(db, row, candidate_run)))
                except Exception as exc:  # noqa: BLE001 - one row must not stop its batch
                    failed_inputs.append(
                        (row, f"input_error: {type(exc).__name__}: {exc}"[:500])
                    )
            outcome = None
            if payloads:
                try:
                    outcome = _run_batch(
                        db, run, number, payloads, template, command, counted
                    )
                except Exception as exc:  # noqa: BLE001 - one batch must not stop the others
                    db.rollback()
                    error = f"batch_error: {type(exc).__name__}: {exc}"[:500]
                    for row, payload in payloads:
                        _store(
                            db,
                            row,
                            payload,
                            run=run,
                            raw_payload_id=None,
                            run_at=datetime.utcnow(),
                            error=error,
                        )
                    outcome = {
                        "batch": number,
                        "candidate_ids": [row.id for row, _payload in payloads],
                        "status": "pending",
                        "reason": "batch_error",
                        "error": error,
                    }
                results.append(outcome)
            for row, error in failed_inputs:
                # Hashed by the id alone: there is no input to hash.
                _store(
                    db,
                    row,
                    {"id": row.id},
                    run=run,
                    raw_payload_id=None,
                    run_at=datetime.utcnow(),
                    error=error,
                )
                unbuilt.append(
                    {"batch": number, "candidate_id": row.id, "error": error}
                )
            if outcome is not None and outcome.get("reason") in FATAL_REASONS:
                stop_reason = f"stopped_after_{outcome['reason']}"
            # Count the call as soon as it is made, so a crash later in this run
            # still counts toward the daily limit.
            run.metadata_json = {
                **_metadata(
                    template,
                    candidate_run.trading_date,
                    candidate_run.id,
                    results,
                    skipped,
                    calls,
                ),
                "input_errors": unbuilt,
            }
            db.commit()
        finished = [item for item in results if item["status"] == "done"]
        failed = [item for item in results if item["status"] != "done"]
        done_count = sum(len(item["candidate_ids"]) for item in finished)
        pending_count = sum(len(item["candidate_ids"]) for item in failed) + len(
            unbuilt
        )
        if not done_count and not pending_count:
            status = "skipped"
        elif not pending_count and not skipped:
            status = "success"
        elif done_count:
            status = "partial"
        else:
            status = "failed"
        errors = [
            f"batch {item['batch']}: {item.get('error', item.get('reason'))}"
            for item in failed
        ]
        errors += [
            f"candidate {item['candidate_id']}: {item['error']}" for item in unbuilt
        ]
        for reason in sorted({item["reason"] for item in skipped}):
            count = sum(1 for item in skipped if item["reason"] == reason)
            errors.append(f"{reason}: {count} batch(es) skipped")
        run.status = status
        run.records = done_count
        run.error = "; ".join(errors) or None
        run.data_as_of = datetime.utcnow().isoformat()
        run.metadata_json = {
            **_metadata(
                template,
                candidate_run.trading_date,
                candidate_run.id,
                results,
                skipped,
                calls,
            ),
            "input_errors": unbuilt,
        }
        run.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        # A write failed (database locked, constraint): close the run as failed
        # with the calls already made, instead of leaving it running.
        db.rollback()
        error = f"run_error: {type(exc).__name__}: {exc}"[:500]
        failed_run = db.get(IngestionRun, run.id)
        failed_run.status = "failed"
        failed_run.error = error
        failed_run.finished_at = datetime.utcnow()
        failed_run.metadata_json = {
            **(failed_run.metadata_json or {}),
            "calls": calls,
            "reason": "run_error",
        }
        db.commit()
        return {
            **base,
            "status": "failed",
            "reason": "run_error",
            "error": error,
            "run_id": run.id,
            "calls": calls,
        }
    return {
        **base,
        "status": status,
        "run_id": run.id,
        "records": run.records,
        "error": run.error,
        "pending": pending_count,
        "skipped": sum(len(item["candidate_ids"]) for item in skipped),
        "calls": calls,
        "usage_total": _usage_total(results),
        "duration_ms_total": sum(int(item.get("duration_ms", 0)) for item in results),
        "batches": results,
        "skipped_batches": skipped,
        "input_errors": unbuilt,
    }


def run_candidate_notes_batch(
    trading_date: date | None = None,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    # pipeline.SessionLocal, like the other daily steps (and their test patches).
    with pipeline.SessionLocal() as db:
        if not inspect(db.get_bind()).has_table(CandidateLlmNote.__tablename__):
            return {
                "status": "failed",
                "reason": "candidate_llm_notes_table_missing_run_init_db",
            }
        return run_candidate_notes(db, trading_date, dry_run=dry_run, limit=limit)
