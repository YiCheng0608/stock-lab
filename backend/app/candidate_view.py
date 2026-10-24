"""Read model of stored daily candidates (``/api/candidates`` and stock detail).

Only reads ``candidate_runs`` / ``daily_candidates`` written by
``worker.candidates`` and the ``candidate_llm_notes`` written by
``worker.candidate_notes``; nothing is scored or generated at request time.
"""

from __future__ import annotations

from datetime import date, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .domain import CANDIDATE_NOTE_PROMPT_VERSION, CANDIDATE_SCORE_VERSION
from .models import (
    CandidateLlmNote,
    CandidateRun,
    ChipSnapshot,
    DailyCandidate,
    Instrument,
    MarketBar,
    Signal,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 20

COMPONENT_LABELS = {
    "technical": "技術",
    "chips": "籌碼",
    "group": "族群",
    "news_sentiment": "新聞情緒",
}
NULL_EXPLANATIONS = {
    "signal_evidence_missing": "訊號依據缺少前 20 日高點、量或均線，無法計算",
    "technical_inputs_missing": "技術子項皆無資料",
    "chip_or_volume_sessions_incomplete": "近 20 個交易日的籌碼或成交量不完整，或當日無交易",
    "chip_inputs_missing": "籌碼子項皆無資料",
    "news_collection_missing": "近 3 日沒有成功的新聞收集，新聞分項無資料",
    "instrument_not_in_universe": "標的不在當日普通股母體內",
    "no_qualified_group": "當日沒有已排名且資料完整的所屬產業或題材",
}
ZERO_REASONS = {
    "no_actionable_signals": "當日沒有成立（條件成立）的策略訊號",
    "all_excluded": "成立的訊號都因 ETF、價位不合法或評分資料不足被排除",
}


def _explained(node: dict[str, Any]) -> dict[str, Any]:
    reason = node.get("null_reason")
    return {
        **node,
        "null_explanation": NULL_EXPLANATIONS.get(reason, reason) if reason else None,
    }


def _components(stored: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, label in COMPONENT_LABELS.items():
        component = dict(stored.get(key) or {})
        component.pop("raw", None)
        component["label"] = label
        component["items"] = {
            name: _explained(item)
            for name, item in (component.get("items") or {}).items()
        }
        result[key] = _explained(component)
    return result


def _levels(signal: Signal) -> dict[str, Any]:
    if signal.entry_type == "breakout":
        entry = signal.breakout_price
        zone = {"low": signal.breakout_price, "high": signal.breakout_price}
    else:
        entry = signal.reference_entry
        zone = {"low": signal.pullback_low, "high": signal.pullback_high}
    risk_reward = None
    if (
        entry is not None
        and signal.invalid_price is not None
        and signal.target_1 is not None
        and entry > signal.invalid_price
    ):
        risk_reward = round(
            (signal.target_1 - entry) / (entry - signal.invalid_price), 4
        )
    return {
        "entry_type": signal.entry_type,
        "entry": entry,
        "entry_zone": zone,
        "invalid_price": signal.invalid_price,
        "target_1": signal.target_1,
        "target_2": signal.target_2,
        "risk_reward": risk_reward,
        "earliest_execution_date": signal.earliest_execution_date.isoformat()
        if signal.earliest_execution_date
        else None,
    }


def _note(db: Session, row: DailyCandidate) -> dict[str, Any] | None:
    """The candidate's LLM note (inference), or None when none was attempted.

    A done note of the current prompt version comes first, then the latest
    done note of another version; a pending one has no text.
    """

    notes = db.scalars(
        select(CandidateLlmNote).where(CandidateLlmNote.daily_candidate_id == row.id)
    ).all()
    if not notes:
        return None
    note = max(
        notes,
        key=lambda item: (
            item.llm_status == "done",
            item.prompt_version == CANDIDATE_NOTE_PROMPT_VERSION,
            item.llm_run_at,
        ),
    )
    done = note.llm_status == "done"
    return {
        "status": "done" if done else "pending",
        "inference": True,
        "selection": note.ai_selection if done else None,
        "levels": note.ai_levels if done else None,
        "risks": note.ai_risks if done else None,
        "model": note.llm_model,
        "prompt_version": note.prompt_version,
        # llm_run_at is UTC-naive; the instant carries its offset.
        "generated_at": note.llm_run_at.replace(tzinfo=timezone.utc).isoformat()
        if note.llm_run_at
        else None,
        "input_hash": note.llm_input_hash,
    }


def candidate_item(
    db: Session, row: DailyCandidate, run: CandidateRun
) -> dict[str, Any]:
    instrument = db.get(Instrument, row.instrument_id)
    signal = db.get(Signal, row.signal_id)
    bar = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == row.instrument_id,
            MarketBar.trading_date == row.trading_date,
        )
    )
    chip = db.scalar(
        select(ChipSnapshot).where(
            ChipSnapshot.instrument_id == row.instrument_id,
            ChipSnapshot.trading_date == row.trading_date,
        )
    )
    news_config = (
        (run.config_json or {}).get("components", {}).get("news_sentiment", {})
    )
    return {
        "rank": row.rank,
        "trading_date": row.trading_date.isoformat(),
        "score_version": row.score_version,
        "instrument": {
            "id": instrument.id,
            "exchange": instrument.exchange,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "instrument_type": instrument.instrument_type,
        },
        "strategy": row.strategy,
        "signal_id": row.signal_id,
        "signal_status": signal.status,
        "levels": _levels(signal),
        "total_score": row.total_score,
        "weight_coverage": row.weight_coverage,
        "partial_components": row.weight_coverage < 1.0 - 1e-9,
        "components": _components(row.components_json or {}),
        "alternatives": (row.components_json or {}).get("alternatives", []),
        "reasons": row.reasons_json or [],
        "groups": row.groups_json or [],
        "data_as_of": row.data_as_of.isoformat(),
        "llm_note": _note(db, row),
        "sources": {
            "signal": f"analysis:{row.strategy}",
            "market_bar": bar.source if bar else None,
            "chips": chip.source if chip else None,
            "groups": "hot_group_v1",
            "news": f"news_items+news_llm_results:{news_config.get('llm_prompt_version')}",
        },
    }


def _run_for(
    db: Session, trading_date: date | None, *, on_or_before: bool = False
) -> CandidateRun | None:
    query = select(CandidateRun).where(
        CandidateRun.score_version == CANDIDATE_SCORE_VERSION
    )
    if trading_date is not None:
        query = query.where(
            CandidateRun.trading_date <= trading_date
            if on_or_before
            else CandidateRun.trading_date == trading_date
        )
    return db.scalar(query.order_by(desc(CandidateRun.trading_date)).limit(1))


def _methodology(run: CandidateRun | None) -> dict[str, Any]:
    config = (run.config_json if run is not None else None) or {}
    return {
        "score_version": CANDIDATE_SCORE_VERSION,
        "purpose": "評分只用於排序，不代表勝率或預期報酬，不改變策略判定",
        "weights": config.get("weights"),
        "minimum_weight_coverage": config.get("minimum_weight_coverage"),
        "components": {
            key: {
                "label": label,
                "weight": (config.get("weights") or {}).get(key),
                "inference": bool(
                    (config.get("components") or {})
                    .get(key, {})
                    .get("inference", False)
                ),
            }
            for key, label in COMPONENT_LABELS.items()
        },
        "null_explanations": NULL_EXPLANATIONS,
    }


def candidate_list(
    db: Session, trading_date: date | None, limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    run = _run_for(db, trading_date)
    if run is None:
        return {
            "status": "not_computed",
            "trading_date": trading_date.isoformat() if trading_date else None,
            "score_version": CANDIDATE_SCORE_VERSION,
            "candidate_count": 0,
            "zero_reason": None,
            "zero_reason_text": None,
            "methodology": _methodology(None),
            "items": [],
        }
    rows = db.scalars(
        select(DailyCandidate)
        .where(DailyCandidate.candidate_run_id == run.id)
        .order_by(DailyCandidate.rank)
        .limit(limit)
    ).all()
    return {
        "status": run.status,
        "trading_date": run.trading_date.isoformat(),
        "score_version": run.score_version,
        # computed_at is UTC-naive; the instant carries its offset.
        "computed_at": run.computed_at.replace(tzinfo=timezone.utc).isoformat()
        if run.computed_at
        else None,
        "evaluated_signals": run.evaluated_signals,
        "pool_count": run.pool_count,
        "candidate_count": run.candidate_count,
        "zero_reason": run.zero_reason,
        "zero_reason_text": ZERO_REASONS.get(run.zero_reason)
        if run.zero_reason
        else None,
        "exclusions": run.exclusions_json or {},
        "data_as_of": run.trading_date.isoformat(),
        "news_coverage": (run.summary_json or {}).get("news"),
        "methodology": _methodology(run),
        "items": [candidate_item(db, row, run) for row in rows],
    }


def candidate_for_instrument(
    db: Session, instrument_id: int, as_of: date | None
) -> dict[str, Any] | None:
    """The stock's row in the latest candidate run on or before ``as_of``."""

    run = _run_for(db, as_of, on_or_before=True)
    if run is None:
        return None
    row = db.scalar(
        select(DailyCandidate).where(
            DailyCandidate.candidate_run_id == run.id,
            DailyCandidate.instrument_id == instrument_id,
        )
    )
    return candidate_item(db, row, run) if row is not None else None
