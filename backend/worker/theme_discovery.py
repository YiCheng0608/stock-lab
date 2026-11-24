"""新題材發現 (Issue #1018): cluster, ask the LLM to name, verify, write.

The daily's ``theme_discovery`` step and ``worker.cli theme-discovery`` call
``run_theme_discovery``:

1. **Cluster**: ``app.theme_clusters.store_clusters`` computes and commits the
   date's 量價共振分群 (a rerun replaces it).
2. **Select**: a cluster goes to the LLM when it has at least
   ``ClusterConfig.min_cluster_size`` stocks and neither one existing theme
   (an active ``theme`` group) nor one existing theme candidate holds more
   than ``MAX_KNOWN_SHARE`` of its members (#1003 AC-2 §2: 大部分成員不在同
   一個現有題材裡).  Clusters are taken in cluster order, at most
   ``DAILY_CALL_LIMIT`` calls per Taipei day across runs.
3. **Input**: per member (at most ``MAX_MEMBERS``, the most correlated
   first) its name, official industry, 20-day excess return, the 主要經營業務
   cell of its MOPS 公司基本資料 page (fetched with
   ``worker.theme_evidence.PageStore``) and the titles of the news of the last
   7 days that name it; plus the existing theme names.
4. **Call**: the local ``claude -p`` (``worker.news_llm``: the user's
   subscription login, no API key, no tools), model ``MODEL``, prompt
   ``prompts/theme_discovery_v1.md``.  The prompt and response are kept as
   raw; the model, prompt version and SHA-256, calls and usage on the
   ``theme_discovery`` ingestion run.
5. **Verify**: every proposed member is checked with
   ``worker.theme_evidence.check_member`` against its MOPS page (the
   ``quote`` verbatim in 主要經營業務, a theme keyword in the quote, the
   instrument a stock); a member that fails is not written.  A proposal with
   fewer than ``MIN_VERIFIED_MEMBERS`` passing members, an id or name of an
   existing theme, or an invalid answer writes nothing.
6. **Write**: ``app.theme_table.write_theme_candidate``: an inactive
   ``theme_candidate`` group (``name_status="pending_verification"``), members
   ``role="candidate"`` from the trading date (never earlier).  Theme
   candidates are never scored, ranked or read as a theme by the candidate
   lists; the coordinator reviews them weekly and moves accepted ones into
   the theme table (docs/INDUSTRY_CLASSIFICATION.md §7).

``ai=False`` (the replay's ``--no-ai``) stops after step 1.  The step never
raises: a failure is one ``warning:`` line on stderr and a ``failed`` result
the daily keeps on its step row (``schedule_runs.NON_BLOCKING_STEPS``).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import (
    GroupMembership,
    IngestionRun,
    Instrument,
    NewsItem,
    ThemeClusterRun,
    ThemeGroup,
)
from app.theme_clusters import (
    DEFAULT_CONFIG,
    THEME_CLUSTER_VERSION,
    Cluster,
    ClusterConfig,
    store_clusters,
    stored_clusters,
)
from app.theme_table import (
    RELATIONS,
    RELEVANCE_LEVELS,
    THEME_CANDIDATE_GROUP_TYPE,
    THEME_CANDIDATE_ROLE,
    THEME_GROUP_TYPE,
    ThemeTableError,
    write_theme_candidate,
)

from . import pipeline, sources
from .news_llm import (
    _USAGE_KEYS,
    LlmBatchError,
    Runner,
    _object,
    _string,
    _usage,
    cli_arguments,
    parse_envelope,
    preflight,
    run_claude_cli,
)
from .news_sources import TAIPEI
from .pipeline import _upsert_raw_payload
from .theme_evidence import (
    EvidenceFetchError,
    PageStore,
    _mops_main_business,
    check_member,
)
from .themes import THEME_MEMBER_TYPES

PROMPT_VERSION = "theme_discovery_v1"
PROMPT_PATH = Path(__file__).with_name("prompts") / f"{PROMPT_VERSION}.md"
# Pinned hash of the prompt text (LF line endings).  Editing the prompt
# without a new PROMPT_VERSION fails the prompt version test.
PROMPT_SHA256 = "0a2971cb33c92e86621edc1150f0d474c14dabadc510a6d896f6beab0f3da0d8"
MODEL = "sonnet"
RUN_TYPE = "theme_discovery"
RAW_SOURCE = "theme_discovery"
RAW_ENDPOINT = f"claude -p --model {MODEL}"
# One call per cluster; the subscription quota is shared with the news and
# candidate notes, so a night sends at most this many clusters.
DAILY_CALL_LIMIT = 3
MAX_KNOWN_SHARE = 0.5
MAX_MEMBERS = 20
MIN_VERIFIED_MEMBERS = 3
NEWS_DAYS = 7
NEWS_PER_MEMBER = 3
MOPS_PROFILE_URL = (
    "https://mopsov.twse.com.tw/mops/web/ajax_t05st03?encodeURIComponent=1"
    "&step=1&firstin=1&off=1&keyword4=&code1=&TYPEK2=&checkbtn="
    "&queryName=co_id&inpuType=co_id&TYPEK=all&co_id={symbol}"
)
MOPS_PROFILE_TITLE = "公開資訊觀測站 公司基本資料 主要經營業務"
MAIN_BUSINESS_MAX_CHARS = 600
ID_MAX_CHARS = 40
NAME_MAX_CHARS = 12
DESCRIPTION_MAX_CHARS = 80
KEYWORD_MAX_CHARS = 10
MAX_KEYWORDS = 8
QUOTE_MAX_CHARS = 60
REASON_MAX_CHARS = 200
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FIELDS = (
    "is_theme",
    "reason",
    "id",
    "name",
    "description",
    "keywords",
    "members",
)
_MEMBER_FIELDS = ("symbol", "relation", "relevance", "quote")
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_FIELDS),
    "properties": {
        "is_theme": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": REASON_MAX_CHARS},
        "id": {"type": "string", "maxLength": ID_MAX_CHARS},
        "name": {"type": "string", "maxLength": NAME_MAX_CHARS},
        "description": {"type": "string", "maxLength": DESCRIPTION_MAX_CHARS},
        "keywords": {
            "type": "array",
            "maxItems": MAX_KEYWORDS,
            "items": {"type": "string", "maxLength": KEYWORD_MAX_CHARS},
        },
        "members": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(_MEMBER_FIELDS),
                "properties": {
                    "symbol": {"type": "string"},
                    "relation": {"type": "string", "enum": sorted(RELATIONS)},
                    "relevance": {"type": "string", "enum": sorted(RELEVANCE_LEVELS)},
                    "quote": {"type": "string", "maxLength": QUOTE_MAX_CHARS},
                },
            },
        },
    },
}


def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def prompt_sha256(text: str | None = None) -> str:
    return hashlib.sha256((text or prompt_text()).encode("utf-8")).hexdigest()


def mops_profile_url(symbol: str) -> str:
    return MOPS_PROFILE_URL.format(symbol=symbol)


# --- selection --------------------------------------------------------------


def _open_groups(db: Session, day: date) -> dict[int, set[str]]:
    """Each stock's active themes and open theme candidates on ``day``."""

    rows = db.execute(
        select(GroupMembership.instrument_id, ThemeGroup.id)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(
            (
                (ThemeGroup.group_type == THEME_GROUP_TYPE)
                & ThemeGroup.active.is_(True)
                & (GroupMembership.role == "member")
            )
            | (
                (ThemeGroup.group_type == THEME_CANDIDATE_GROUP_TYPE)
                & (GroupMembership.role == THEME_CANDIDATE_ROLE)
            ),
            GroupMembership.valid_from <= day,
            (GroupMembership.valid_to.is_(None)) | (GroupMembership.valid_to >= day),
        )
    ).all()
    groups: dict[int, set[str]] = {}
    for instrument_id, group_id in rows:
        groups.setdefault(instrument_id, set()).add(group_id)
    return groups


def known_share(
    item: Cluster, groups: dict[int, set[str]]
) -> tuple[str | None, float]:
    """The theme or candidate holding most of the cluster, and its share."""

    counts = Counter(
        group_id
        for instrument_id in item.instrument_ids
        for group_id in groups.get(instrument_id, ())
    )
    if not counts:
        return None, 0.0
    group_id, count = min(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return group_id, count / len(item.members)


def select_clusters(
    db: Session, day: date, clusters: list[Cluster], config: ClusterConfig
) -> list[dict[str, Any]]:
    """Every cluster with whether it goes to the LLM and why."""

    groups = _open_groups(db, day)
    decisions = []
    for item in clusters:
        group_id, share = known_share(item, groups)
        if len(item.members) < config.min_cluster_size:
            reason = "too_small"
        elif share > MAX_KNOWN_SHARE:
            reason = "known_theme"
        else:
            reason = None
        decisions.append(
            {
                "cluster_no": item.cluster_no,
                "size": len(item.members),
                "known_group": group_id,
                "known_share": round(share, 4),
                "selected": reason is None,
                "reason": reason,
            }
        )
    return decisions


# --- input --------------------------------------------------------------------


def _news_titles(
    db: Session, day: date, instruments: dict[int, Instrument]
) -> dict[int, list[str]]:
    """Titles of the news of the last NEWS_DAYS days naming each stock."""

    start = datetime.combine(day - timedelta(days=NEWS_DAYS - 1), datetime.min.time())
    end = datetime.combine(day + timedelta(days=1), datetime.min.time())
    keys: dict[str, int] = {}
    for instrument_id, instrument in instruments.items():
        keys[f"{instrument.exchange}:{instrument.symbol}"] = instrument_id
        keys[instrument.symbol] = instrument_id
    titles: dict[int, list[str]] = {}
    rows = db.execute(
        select(NewsItem.title, NewsItem.symbols_json)
        .where(
            NewsItem.status == "active",
            NewsItem.display_time >= start - timedelta(hours=8),
            NewsItem.display_time < end - timedelta(hours=8),
        )
        .order_by(NewsItem.display_time.desc(), NewsItem.id.desc())
    ).all()
    for title, symbols in rows:
        for instrument_id in {keys[s] for s in symbols or [] if s in keys}:
            bucket = titles.setdefault(instrument_id, [])
            if len(bucket) < NEWS_PER_MEMBER and title not in bucket:
                bucket.append(title)
    return titles


def _industries(db: Session, day: date, ids: list[int]) -> dict[int, str]:
    rows = db.execute(
        select(
            GroupMembership.instrument_id,
            ThemeGroup.display_name_zh,
            ThemeGroup.name,
        )
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(
            ThemeGroup.group_type == "official_industry",
            GroupMembership.instrument_id.in_(ids),
            GroupMembership.valid_from <= day,
            (GroupMembership.valid_to.is_(None)) | (GroupMembership.valid_to >= day),
        )
        .order_by(GroupMembership.instrument_id, ThemeGroup.id)
    ).all()
    found: dict[int, str] = {}
    for instrument_id, display, name in rows:
        found.setdefault(instrument_id, display or name)
    return found


def _existing_theme_names(db: Session) -> list[str]:
    return sorted(
        {
            display or name
            for display, name in db.execute(
                select(ThemeGroup.display_name_zh, ThemeGroup.name).where(
                    ThemeGroup.group_type.in_(
                        (THEME_GROUP_TYPE, THEME_CANDIDATE_GROUP_TYPE)
                    )
                )
            ).all()
        }
    )


def main_business(pages: PageStore, symbol: str) -> tuple[str | None, str | None]:
    """The normalised 主要經營業務 cell of a stock's MOPS page, or an error."""

    try:
        text = pages.text(mops_profile_url(symbol))
    except EvidenceFetchError as error:
        return None, str(error)
    cell = _mops_main_business(text)
    if cell is None:
        return None, "no main business on page"
    return cell[:MAIN_BUSINESS_MAX_CHARS], None


def cluster_input(
    db: Session,
    day: date,
    item: Cluster,
    pages: PageStore,
    existing: list[str],
) -> tuple[dict[str, Any], dict[str, Instrument], list[dict[str, Any]]]:
    members = sorted(
        item.members, key=lambda member: (-member.member_mean_corr, member.instrument_id)
    )[:MAX_MEMBERS]
    ids = [member.instrument_id for member in members]
    instruments = {
        row.id: row
        for row in db.scalars(select(Instrument).where(Instrument.id.in_(ids))).all()
    }
    industries = _industries(db, day, ids)
    news = _news_titles(db, day, instruments)
    by_symbol: dict[str, Instrument] = {}
    fetch_errors: list[dict[str, Any]] = []
    entries = []
    for member in members:
        instrument = instruments[member.instrument_id]
        key = f"{instrument.exchange}:{instrument.symbol}"
        by_symbol[key] = instrument
        business, error = main_business(pages, instrument.symbol)
        if error is not None:
            fetch_errors.append({"symbol": key, "error": error})
        entries.append(
            {
                "symbol": key,
                "name": instrument.name,
                "industry": industries.get(member.instrument_id),
                "excess_return_20d": round(member.excess_return_20d, 4),
                "main_business": business,
                "news_titles": news.get(member.instrument_id, []),
            }
        )
    payload = {
        "trading_date": day.isoformat(),
        "cluster_no": item.cluster_no,
        "mean_corr": round(item.mean_corr, 4),
        "members": entries,
        "existing_themes": existing,
    }
    return payload, by_symbol, fetch_errors


def build_prompt(template: str, payload: dict[str, Any]) -> str:
    # Escape angle brackets so stored text cannot close or forge the block.
    data = (
        json.dumps(payload, ensure_ascii=False, indent=1)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return f"{template.rstrip()}\n\n<cluster>\n{data}\n</cluster>\n"


# --- output -------------------------------------------------------------------


def validate_output(structured: Any, symbols: Sequence[str]) -> dict[str, Any]:
    """Validate the whole answer; any problem rejects the proposal."""

    raw = _object(structured, _FIELDS, "structured_output")
    if not isinstance(raw["is_theme"], bool):
        raise LlmBatchError("schema_mismatch", "is_theme must be a boolean")
    reason = _string(raw["reason"], "reason", REASON_MAX_CHARS)
    if not raw["is_theme"]:
        return {"is_theme": False, "reason": reason}
    candidate_id = _string(raw["id"], "id", ID_MAX_CHARS)
    if not _ID.match(candidate_id):
        raise LlmBatchError("schema_mismatch", "id must be lowercase kebab-case")
    name = _string(raw["name"], "name", NAME_MAX_CHARS)
    if not name or "etf" in name.casefold():
        raise LlmBatchError("schema_mismatch", "name empty or contains ETF")
    description = _string(raw["description"], "description", DESCRIPTION_MAX_CHARS)
    keywords = raw["keywords"]
    if not isinstance(keywords, list) or not 1 <= len(keywords) <= MAX_KEYWORDS:
        raise LlmBatchError("schema_mismatch", "keywords must list 1-8 words")
    words = [_string(word, "keyword", KEYWORD_MAX_CHARS) for word in keywords]
    if not all(words):
        raise LlmBatchError("schema_mismatch", "empty keyword")
    if not isinstance(raw["members"], list):
        raise LlmBatchError("schema_mismatch", "members must be a list")
    allowed = set(symbols)
    members = []
    seen: set[str] = set()
    for value in raw["members"]:
        member = _object(value, _MEMBER_FIELDS, "member")
        symbol = _string(member["symbol"], "member symbol")
        if symbol not in allowed:
            raise LlmBatchError("schema_mismatch", f"{symbol} is not in the cluster")
        if symbol in seen:
            raise LlmBatchError("schema_mismatch", f"duplicate member {symbol}")
        seen.add(symbol)
        if member["relation"] not in RELATIONS:
            raise LlmBatchError("schema_mismatch", f"{symbol} relation invalid")
        if member["relevance"] not in RELEVANCE_LEVELS:
            raise LlmBatchError("schema_mismatch", f"{symbol} relevance invalid")
        quote = _string(member["quote"], f"{symbol} quote", QUOTE_MAX_CHARS)
        if not quote:
            raise LlmBatchError("schema_mismatch", f"{symbol} quote empty")
        members.append(
            {
                "symbol": symbol,
                "relation": member["relation"],
                "relevance": member["relevance"],
                "quote": quote,
            }
        )
    return {
        "is_theme": True,
        "reason": reason,
        "id": candidate_id,
        "name": name,
        "description": description,
        "keywords": words,
        "members": members,
    }


def verify_proposal(
    proposal: dict[str, Any],
    by_symbol: dict[str, Instrument],
    pages: PageStore,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The members that pass ``check_member`` and the failures with errors."""

    theme = {"keywords": proposal["keywords"]}
    types = {
        (instrument.exchange, instrument.symbol): instrument.instrument_type
        for instrument in by_symbol.values()
    }
    passed, failed = [], []
    for member in proposal["members"]:
        instrument = by_symbol[member["symbol"]]
        url = mops_profile_url(instrument.symbol)
        evidence = {"url": url, "title": MOPS_PROFILE_TITLE, "quote": member["quote"]}
        errors = check_member(
            theme,
            {"instrument": member["symbol"], "evidence": [evidence]},
            pages,
            types,
        )
        if instrument.instrument_type not in THEME_MEMBER_TYPES:
            errors = errors or [f"instrument_type={instrument.instrument_type}"]
        if errors:
            failed.append({"symbol": member["symbol"], "errors": errors})
        else:
            passed.append(
                {
                    "instrument_id": instrument.id,
                    "symbol": member["symbol"],
                    "relation": member["relation"],
                    "relevance": member["relevance"],
                    "url": url,
                    "quote": member["quote"],
                }
            )
    return passed, failed


def _duplicate_of_existing(db: Session, proposal: dict[str, Any]) -> str | None:
    """An existing theme with the proposal's id or name (case-insensitive)."""

    name = proposal["name"].casefold()
    for group_id, group_name, display in db.execute(
        select(ThemeGroup.id, ThemeGroup.name, ThemeGroup.display_name_zh).where(
            ThemeGroup.group_type == THEME_GROUP_TYPE
        )
    ).all():
        if group_id == f"theme-{proposal['id']}" or name in {
            (group_name or "").casefold(),
            (display or "").casefold(),
        }:
            return group_id
    return None


# --- run ----------------------------------------------------------------------


def _calls_today(db: Session, run_date: date) -> int:
    runs = db.scalars(
        select(IngestionRun).where(
            IngestionRun.run_type == RUN_TYPE, IngestionRun.run_date == run_date
        )
    ).all()
    return sum(int((run.metadata_json or {}).get("calls", 0)) for run in runs)


def _usage_total(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        key: sum(int(item.get("usage", {}).get(key, 0)) for item in results)
        for key in _USAGE_KEYS
    }


def _cluster_summary(
    db: Session, run: ThemeClusterRun, clusters: list[Cluster]
) -> list[dict[str, Any]]:
    ids = [member.instrument_id for item in clusters for member in item.members]
    instruments = {
        row.id: f"{row.exchange}:{row.symbol} {row.name}"
        for row in db.scalars(select(Instrument).where(Instrument.id.in_(ids))).all()
    }
    return [
        {
            "cluster_no": item.cluster_no,
            "size": len(item.members),
            "mean_corr": round(item.mean_corr, 4),
            "members": [instruments.get(i, str(i)) for i in item.instrument_ids],
        }
        for item in clusters
    ]


def _propose(
    db: Session,
    run: IngestionRun,
    cluster_run: ThemeClusterRun,
    item: Cluster,
    pages: PageStore,
    template: str,
    command: list[str],
    runner: Runner,
    existing: list[str],
) -> dict[str, Any]:
    day = cluster_run.trading_date
    payload, by_symbol, fetch_errors = cluster_input(db, day, item, pages, existing)
    outcome: dict[str, Any] = {
        "cluster_no": item.cluster_no,
        "fetch_errors": fetch_errors,
    }
    prompt = build_prompt(template, payload)
    argv = [*command, *cli_arguments(MODEL, OUTPUT_SCHEMA)]
    started = time.monotonic()
    result = runner(prompt, argv)
    outcome["duration_ms"] = int((time.monotonic() - started) * 1000)
    run_at = utcnow()
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
            "duration_ms": outcome["duration_ms"],
        },
        run_at.isoformat(),
        collected_at=run_at,
    )
    outcome["raw_payload_id"] = _upsert_raw_payload(db, run, raw).id
    envelope: dict[str, Any] | None = None
    try:
        envelope = parse_envelope(result)
        proposal = validate_output(envelope.get("structured_output"), list(by_symbol))
    except LlmBatchError as exc:
        if envelope is not None:
            outcome["model"], outcome["usage"] = _usage(envelope)
        outcome.update(status="failed", reason=exc.reason, error=str(exc)[:500])
        return outcome
    model, usage = _usage(envelope)
    outcome.update(model=model, usage=usage, proposal=proposal)
    if not proposal["is_theme"]:
        outcome.update(status="not_theme")
        return outcome
    duplicate = _duplicate_of_existing(db, proposal)
    if duplicate is not None:
        outcome.update(status="rejected", reason="existing_theme", group_id=duplicate)
        return outcome
    passed, failed = verify_proposal(proposal, by_symbol, pages)
    outcome.update(verified=[m["symbol"] for m in passed], failed_members=failed)
    if len(passed) < MIN_VERIFIED_MEMBERS:
        outcome.update(status="rejected", reason="too_few_verified_members")
        return outcome
    provenance = {
        "model": model or MODEL,
        "prompt_version": PROMPT_VERSION,
        "cluster_version": THEME_CLUSTER_VERSION,
        "cluster_run_id": cluster_run.id,
        "cluster_no": item.cluster_no,
        "ingestion_run_id": run.id,
    }
    try:
        written = write_theme_candidate(
            db,
            candidate_id=proposal["id"],
            name=proposal["name"],
            description=proposal["description"],
            keywords=proposal["keywords"],
            members=passed,
            valid_from=day,
            provenance=provenance,
        )
    except ThemeTableError as exc:
        db.rollback()
        outcome.update(status="rejected", reason="write_refused", error=str(exc))
        return outcome
    outcome.update(status="written", **written)
    return outcome


def _ai_step(
    db: Session,
    cluster_run: ThemeClusterRun,
    clusters: list[Cluster],
    decisions: list[dict[str, Any]],
    *,
    runner: Runner | None,
    pages: PageStore | None,
    run_date: date,
    call_limit: int,
) -> dict[str, Any]:
    selected = [
        item
        for item, decision in zip(clusters, decisions)
        if decision["selected"]
    ]
    if not selected:
        return {"status": "success", "calls": 0, "proposals": []}
    command, problem = preflight()
    if problem is not None:
        now = utcnow()
        failed = IngestionRun(
            run_type=RUN_TYPE,
            source="claude-cli",
            run_date=run_date,
            status="failed",
            records=0,
            error=problem,
            started_at=now,
            finished_at=now,
            data_as_of=now.isoformat(),
            metadata_json={"prompt_version": PROMPT_VERSION, "calls": 0},
        )
        db.add(failed)
        db.commit()
        return {"status": "failed", "reason": problem, "calls": 0, "run_id": failed.id}
    assert command is not None
    allowed = max(call_limit - _calls_today(db, run_date), 0)
    template = prompt_text()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="claude-cli",
        run_date=run_date,
        status="running",
        records=0,
        started_at=utcnow(),
        metadata_json={},
    )
    db.add(run)
    db.commit()
    store = pages or PageStore()
    active = runner or run_claude_cli
    existing = _existing_theme_names(db)
    calls = 0
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def metadata() -> dict[str, Any]:
        return {
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": prompt_sha256(template),
            "model": MODEL,
            "trading_date": cluster_run.trading_date.isoformat(),
            "theme_cluster_run_id": cluster_run.id,
            "calls": calls,
            "daily_call_limit": call_limit,
            "skipped_clusters": skipped,
            "usage_total": _usage_total(results),
            "proposals": results,
        }

    for item in selected:
        if calls >= allowed:
            skipped.append({"cluster_no": item.cluster_no, "reason": "daily_call_limit"})
            continue
        calls += 1
        try:
            outcome = _propose(
                db, run, cluster_run, item, store, template, command, active, existing
            )
        except Exception as exc:  # noqa: BLE001 - one cluster must not stop the rest
            db.rollback()
            outcome = {
                "cluster_no": item.cluster_no,
                "status": "failed",
                "reason": "cluster_error",
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        results.append(outcome)
        run.metadata_json = metadata()
        db.commit()
    written = [item for item in results if item.get("status") == "written"]
    failures = [item for item in results if item.get("status") == "failed"]
    run.status = "failed" if failures and not written else "success"
    if failures and written:
        run.status = "partial"
    run.records = sum(len(item.get("added", [])) for item in written)
    run.error = (
        "; ".join(
            f"cluster {item['cluster_no']}: {item.get('error') or item.get('reason')}"
            for item in failures
        )
        or None
    )
    run.data_as_of = utcnow().isoformat()
    run.finished_at = utcnow()
    run.metadata_json = metadata()
    db.commit()
    return {
        "status": run.status,
        "run_id": run.id,
        "calls": calls,
        "records": run.records,
        "error": run.error,
        "proposals": [
            {
                key: item.get(key)
                for key in (
                    "cluster_no",
                    "status",
                    "reason",
                    "group_id",
                    "added",
                    "verified",
                    "failed_members",
                )
                if item.get(key) is not None
            }
            for item in results
        ],
        "skipped_clusters": skipped,
        "usage_total": _usage_total(results),
    }


def discover(
    db: Session,
    target: date,
    *,
    ai: bool = True,
    runner: Runner | None = None,
    pages: PageStore | None = None,
    config: ClusterConfig = DEFAULT_CONFIG,
    run_date: date | None = None,
    call_limit: int = DAILY_CALL_LIMIT,
) -> dict[str, Any]:
    cluster_run = store_clusters(db, target, config)
    clusters = stored_clusters(db, cluster_run)
    decisions = select_clusters(db, target, clusters, config)
    result: dict[str, Any] = {
        "status": "success",
        "date": target.isoformat(),
        "version": THEME_CLUSTER_VERSION,
        "theme_cluster_run_id": cluster_run.id,
        "screened": cluster_run.screened_count,
        "records": cluster_run.cluster_count,
        "clusters": _cluster_summary(db, cluster_run, clusters),
        "selection": decisions,
    }
    if not ai:
        result["ai"] = {"status": "skipped", "reason": "ai_disabled", "calls": 0}
        return result
    result["ai"] = _ai_step(
        db,
        cluster_run,
        clusters,
        decisions,
        runner=runner,
        pages=pages,
        run_date=run_date or datetime.now(TAIPEI).date(),
        call_limit=call_limit,
    )
    if result["ai"]["status"] == "failed":
        # The clusters are stored; the step reports the AI failure.
        result.update(status="partial", error=result["ai"].get("reason"))
    return result


def run_theme_discovery(
    target: date,
    *,
    ai: bool = True,
    runner: Runner | None = None,
    pages: PageStore | None = None,
) -> dict[str, Any]:
    """The daily step: cluster ``target`` and propose candidates; never raises."""

    try:
        # pipeline.SessionLocal, like the other daily steps (and their test patches).
        with pipeline.SessionLocal() as db:
            return discover(db, target, ai=ai, runner=runner, pages=pages)
    except Exception as exc:  # noqa: BLE001 - a warning, the daily goes on
        error = f"{type(exc).__name__}: {exc}"
        print(
            f"warning: {RUN_TYPE} {target.isoformat()} failed: {error}",
            file=sys.stderr,
            flush=True,
        )
        return {
            "status": "failed",
            "date": target.isoformat(),
            "version": THEME_CLUSTER_VERSION,
            "error": error,
        }

