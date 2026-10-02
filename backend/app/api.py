from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StrictInt, model_validator
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from .config import API_PREFIX, DEFAULT_CORS_ORIGINS, MAX_GROUP_CANDIDATES, OFFICIAL_MAX_BACKFILL_DAYS
from .coverage import has_backfill_manifest
from .db import SessionLocal
from .domain import ETF_CATEGORIES, signal_confidence_semantics
from .level_semantics import build_level_semantics, canonical_evidence
from .models import (
    ChipSnapshot,
    CorporateAction,
    DataQuality,
    Event,
    FundamentalSnapshot,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    PortfolioPosition,
    RawPayload,
    Signal,
    SignalEvaluation,
    SignalSettlement,
    StrategyVersion,
    TechnicalFeature,
    ThemeGroup,
)
from worker.pipeline import summarize_backtest
from worker.backfill import (
    BACKFILL_SCOPES,
    backfill_run_dict,
    coverage_report,
    get_backfill_run,
    resolve_backfill_scope,
)
from .decision import (
    ACTION_LABELS,
    build_action_summaries,
    build_decision_summary,
    latest_official_as_of,
    prioritized_instrument_ids,
)
from .glossary import GLOSSARY_VERSION, glossary_terms
from .news import (
    _is_verified_theme_for_instrument,
    _theme_ids_for_event,
    is_verified_theme,
    sync_news_from_events,
)
from .product_time import (
    build_news_product_time,
    build_signal_product_time,
)
from .units import share_quantity_dict, shares_from_position_quantity
from .stock_overview import build_stock_overview, resolve_stock_cutoff


router = APIRouter(prefix=API_PREFIX)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def _effective_page_size(page_size: int, limit: int | None) -> int:
    """Keep the old limit query parameter usable while standardising paging."""

    return limit if limit is not None else page_size


def _paginate_query(
    db: Session,
    query: Any,
    *,
    page: int,
    page_size: int,
    order_by: tuple[Any, ...],
) -> tuple[list[Any], int]:
    total = db.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    ) or 0
    rows = db.scalars(
        query.order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return rows, int(total)


def _page_response(items: list[dict[str, Any]], *, page: int, page_size: int, total: int) -> dict[str, Any]:
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
        },
    }


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def as_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def as_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def instrument_dict(item: Instrument | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "id": item.id,
        "market": item.market,
        "exchange": item.exchange,
        "symbol": item.symbol,
        "name": item.name,
        "industry": item.industry,
        "instrument_type": item.instrument_type,
        "etf_category": item.etf_category,
        "listing_date": as_date(item.listing_date),
        "is_watchlisted": item.is_watchlisted,
        "status": item.status,
    }


def bar_dict(item: MarketBar | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "date": as_date(item.trading_date),
        "open": item.open,
        "high": item.high,
        "low": item.low,
        "close": item.close,
        "adj_close": item.adj_close,
        "volume": item.volume,
        "turnover": item.turnover,
        "turnover_status": item.turnover_status,
        "turnover_reason": item.turnover_reason,
        "source": item.source,
        "data_as_of": as_datetime(item.data_as_of),
        "collected_at": as_datetime(item.collected_at),
        "is_suspended": bool(item.is_suspended),
    }


def chip_dict(item: ChipSnapshot) -> dict[str, Any]:
    return {
        "date": as_date(item.trading_date),
        "foreign_buy": item.foreign_buy,
        "trust_buy": item.trust_buy,
        "dealer_buy": item.dealer_buy,
        "margin_balance": item.margin_balance,
        "margin_change": item.margin_change,
        "short_balance": item.short_balance,
        "borrowed_sell": item.borrowed_sell,
        "day_trade_ratio": item.day_trade_ratio,
        "source": item.source,
        "data_as_of": as_datetime(item.data_as_of),
        "collected_at": as_datetime(item.collected_at),
    }


def quality_dict(item: DataQuality) -> dict[str, Any]:
    return {
        "entity_type": item.entity_type,
        "entity_key": item.entity_key,
        "as_of_date": as_date(item.as_of_date),
        "status": item.status,
        "missing_fields": item.missing_fields_json or [],
        "checks": item.checks_json or {},
        "source": item.source,
        "checked_at": as_datetime(item.checked_at),
    }


def raw_payload_dict(item: RawPayload) -> dict[str, Any]:
    return {
        "id": item.id,
        "ingestion_run_id": item.ingestion_run_id,
        "source": item.source,
        "endpoint": item.endpoint,
        "sha256": item.sha256,
        "data_as_of": item.data_as_of,
        "collected_at": as_datetime(item.collected_at),
    }


def event_dict(db: Session, item: Event) -> dict[str, Any]:
    instrument = db.get(Instrument, item.instrument_id) if item.instrument_id else None
    return {
        "id": item.id,
        "date": as_date(item.event_date),
        "type": item.event_type,
        "title": item.title,
        "description": item.description,
        "instrument": instrument_dict(instrument),
        "source": item.source,
        "endpoint": item.endpoint,
        "raw_payload_id": item.raw_payload_id,
        "data_as_of": item.data_as_of,
        "collected_at": as_datetime(item.collected_at),
    }


def settlement_dict(item: SignalSettlement) -> dict[str, Any]:
    return {
        "id": item.id,
        "horizon": item.horizon,
        "settlement_date": as_date(item.settlement_date),
        "final_status": item.final_status,
        "first_trigger": item.first_trigger,
        "return_or_risk": item.return_or_risk,
        "incomparable_reason": item.incomparable_reason,
        "source": item.source,
        "data_time": item.data_time,
        "execution_date": as_date(item.execution_date),
        "execution_price": item.execution_price,
        "comparable": item.comparable,
        "data_quality": item.data_quality,
    }


def evaluation_dict(item: SignalEvaluation) -> dict[str, Any]:
    return {
        "id": item.id,
        "session_date": as_date(item.session_date),
        "session_no": item.session_no,
        "ohlc": item.ohlc_json,
        "adjusted_ohlc": item.adjusted_ohlc_json,
        "volume": item.volume,
        "volume_ratio_20d": item.volume_ratio_20d,
        "pullback_price_trigger": item.pullback_price_trigger,
        "breakout_price_trigger": item.breakout_price_trigger,
        "target_price_trigger": item.target_price_trigger,
        "invalid_price_trigger": item.invalid_price_trigger,
        "institutional_confirmation": item.institutional_confirmation,
        "leverage_confirmation": item.leverage_confirmation,
        "subgroup_confirmation": item.subgroup_confirmation,
        "full_confirmation": item.full_confirmation,
        "status": item.status,
        "reason": item.reason,
        "source": item.source,
        "data_time": item.data_time,
        "execution_date": as_date(item.execution_date),
        "execution_price": item.execution_price,
        "corporate_action_applied": item.corporate_action_applied,
        "suspended": item.suspended,
        "comparable": item.comparable,
        "trigger_order": item.trigger_order,
        "data_quality": item.data_quality,
    }


def latest_run(db: Session) -> IngestionRun | None:
    return db.scalar(
        select(IngestionRun).where(
            IngestionRun.run_type == "collect",
            IngestionRun.source == "official",
        )
        .order_by(desc(IngestionRun.updated_at), desc(IngestionRun.started_at), desc(IngestionRun.id))
        .limit(1)
    )


def latest_scores(db: Session) -> dict[str, GroupDailyScore]:
    rows = db.scalars(
        select(GroupDailyScore).order_by(
            desc(GroupDailyScore.trading_date),
            desc(GroupDailyScore.id),
        )
    ).all()
    result: dict[str, GroupDailyScore] = {}
    for row in rows:
        result.setdefault(row.group_id, row)
    return result


def scores_as_of(db: Session, as_of: date | None) -> dict[str, GroupDailyScore]:
    if as_of is None:
        # Product ranking is official-snapshot scoped.  Do not let an
        # unscoped legacy score look like a current market ranking.
        return {}
    query = select(GroupDailyScore)
    query = query.where(GroupDailyScore.trading_date <= as_of)
    rows = db.scalars(
        query.order_by(desc(GroupDailyScore.trading_date), desc(GroupDailyScore.id))
    ).all()
    result: dict[str, GroupDailyScore] = {}
    for row in rows:
        result.setdefault(row.group_id, row)
    return result


def _score_details(score: GroupDailyScore | None) -> dict[str, Any]:
    return score.details_json if score and isinstance(score.details_json, dict) else {}


def _candidate_symbols(score: GroupDailyScore | None) -> list[str]:
    symbols = _score_details(score).get("candidate_symbols")
    # Retain ordered display text, including repeated symbols across markets.
    # Malformed JSON is not coerced into a new symbol or a renderable object.
    return [symbol for symbol in symbols if type(symbol) is str and symbol.strip()] if isinstance(symbols, list) else []


def _public_candidate_identity(db: Session | None, group: ThemeGroup, score: GroupDailyScore | None) -> dict[str, Any]:
    """Verify the whole source-day envelope; never infer legacy identities.

    This is a historical display projection, not current action eligibility.
    Status/type/category are current metadata; only membership dates have
    historical bounds. IDs are strings on the public JSON/JavaScript boundary.
    """
    empty = {"public_candidate_identity_version": "instrument-id-string-v1", "candidate_instruments": []}
    details = _score_details(score)
    symbols, candidates = details.get("candidate_symbols"), details.get("candidate_instruments")
    if (db is None or not score or score.group_id != group.id or not score.trading_date
            or details.get("candidate_identity_version") != "instrument-id-v1"
            or not isinstance(symbols, list) or not isinstance(candidates, list)
            or len(candidates) > MAX_GROUP_CANDIDATES or len(symbols) != len(candidates)
            or any(type(symbol) is not str or not symbol.strip() for symbol in symbols)):
        return empty
    ids, pairs = set(), set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return empty
        item_id, exchange, symbol = (candidate.get(key) for key in ("instrument_id", "exchange", "symbol"))
        if (type(item_id) is not int or not 0 < item_id <= 9223372036854775807
                or type(exchange) is not str or not exchange.strip()
                or type(symbol) is not str or not symbol.strip()
                or item_id in ids or (exchange, symbol) in pairs):
            return empty
        ids.add(item_id)
        pairs.add((exchange, symbol))
    if [candidate["symbol"] for candidate in candidates] != symbols or not candidates:
        return empty
    rows = db.execute(
        select(Instrument.id, Instrument.exchange, Instrument.symbol,
               Instrument.instrument_type, Instrument.etf_category)
        .join(GroupMembership, GroupMembership.instrument_id == Instrument.id)
        .where(Instrument.id.in_(ids), GroupMembership.group_id == group.id,
               GroupMembership.valid_from <= score.trading_date,
               (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= score.trading_date)))
    ).all()
    etf_group = group.group_type in {"etf", "instrument_theme"} or "etf" in group.name.lower()
    source_members = {
        item_id: (exchange, symbol) for item_id, exchange, symbol, kind, category in rows
        if ((kind == "etf" and category in ETF_CATEGORIES) if etf_group else kind in {"stock", "ipo"})
    }
    if any(source_members.get(candidate["instrument_id"]) != (candidate["exchange"], candidate["symbol"])
           for candidate in candidates):
        return empty
    return {**empty, "candidate_instruments": [
        {"instrument_id": str(candidate["instrument_id"]), "exchange": candidate["exchange"], "symbol": candidate["symbol"]}
        for candidate in candidates
    ]}


def score_dict(group: ThemeGroup, score: GroupDailyScore | None, db: Session | None = None) -> dict[str, Any]:
    if not score:
        return {
            "group_id": group.id,
            "name": group.name,
            "group_type": group.group_type,
            "score": None,
            "rank": None,
            "trading_date": None,
            "data_quality": "missing",
            "eligible_members": 0,
            "metrics": {},
            "candidates": [],
            **_public_candidate_identity(db, group, None),
            "benchmark": None,
            "leaderboard": None,
        }
    details = _score_details(score)
    return {
        "group_id": group.id,
        "name": group.name,
        "group_type": group.group_type,
        "score": score.score,
        "rank": score.rank,
        "trading_date": as_date(score.trading_date),
        "data_quality": score.data_quality,
        "eligible_members": score.eligible_members,
        "metrics": {
            "relative_return": score.relative_return,
            "relative_return_1d": score.relative_return_1d,
            "relative_return_5d": score.relative_return_5d,
            "relative_return_20d": score.relative_return_20d,
            "breadth": score.breadth,
            "volume_strength": score.volume_strength,
            "institutional_flow": score.institutional_flow,
            "catalyst": score.catalyst,
        },
        "candidates": _candidate_symbols(score),
        **_public_candidate_identity(db, group, score),
        "benchmark": details.get("benchmark"),
        "benchmark_returns": details.get("benchmark_returns", {}),
        "leaderboard": details.get("leaderboard"),
        "methodology": details.get("methodology", {}),
    }


def _group_display_name(group: ThemeGroup) -> str:
    if is_verified_theme(group):
        return group.display_name_zh.strip()
    return "族群待確認"


def _group_display_description(group: ThemeGroup, score: GroupDailyScore | None) -> str:
    if group.display_description_zh:
        return group.display_description_zh
    if group.group_type == "etf":
        return "依官方 ETF 分類獨立排行，不與公司股票族群混排。"
    if group.group_type == "daily_hot_group":
        return "依官方資料與有效成員日期建立的新上市觀察族群。"
    if score and score.eligible_members is not None:
        return "依官方共同產業分類與有效成員日期計算的市場族群。"
    return "官方分類名稱尚待對照；資料不足時不列入熱門排行。"


def _theme_qualified(group: ThemeGroup, score: GroupDailyScore | None) -> bool:
    if not score or not is_verified_theme(group):
        return False
    details = _score_details(score)
    return bool(
        score.data_quality == "complete"
        and (score.eligible_members or 0) >= 3
        and score.rank is not None
        and details.get("benchmark") == "TAIEX"
    )


def _product_group_taxonomy_statuses(db: Session, as_of: date | None) -> dict[str, bool]:
    """Batch-compute official group validity for one product cutoff."""

    key = as_of.isoformat() if as_of else "none"
    cache = db.info.setdefault("_product_group_taxonomy", {})
    if key in cache:
        return cache[key]
    effective_date = as_of or date.today()
    official_groups = db.scalars(
        select(ThemeGroup).where(
            ThemeGroup.active.is_(True),
            ThemeGroup.source.like("%official OpenAPI%"),
        )
    ).all()
    statuses = {
        group.id: bool(is_verified_theme(group))
        for group in official_groups
    }
    if official_groups:
        group_ids = list(statuses)
        rows = db.execute(
            select(GroupMembership, Instrument, ThemeGroup)
            .join(Instrument, Instrument.id == GroupMembership.instrument_id)
            .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
            .where(
                GroupMembership.group_id.in_(group_ids),
                GroupMembership.valid_from <= effective_date,
                (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= effective_date)),
                Instrument.status == "active",
            )
        ).all()
        seen_members: dict[str, int] = {group_id: 0 for group_id in group_ids}
        for membership, instrument, group in rows:
            if "official OpenAPI" not in str(membership.source or ""):
                continue
            seen_members[group.id] += 1
            statuses[group.id] = statuses[group.id] and _is_verified_theme_for_instrument(
                group,
                membership,
                instrument,
            )
        for group_id, count in seen_members.items():
            statuses[group_id] = statuses[group_id] and count > 0
    cache[key] = statuses
    return statuses


def _product_group_taxonomy_verified(
    db: Session,
    group: ThemeGroup,
    as_of: date | None,
) -> bool:
    """Keep stale cross-exchange group memberships out of product pages.

    Official collectors write the exchange on every membership.  A legacy
    group can still look official by name while containing a TPEx numeric code
    interpreted with the TWSE namespace (or vice versa).  Product ranking is
    therefore fail-closed until every current official membership agrees with
    the exchange-aware canonical group.  Small fixture/legacy groups that do
    not claim the official OpenAPI provenance retain the existing product
    behaviour for backwards-compatible tests and audit views.
    """

    if "official OpenAPI" not in str(group.source or ""):
        # Non-official rows remain visible to the existing audit/fixture
        # surface; ``theme_product_dict`` still marks them unqualified.
        return True
    return _product_group_taxonomy_statuses(db, as_of).get(group.id, False)


def _theme_missing_reasons(group: ThemeGroup, score: GroupDailyScore | None) -> list[str]:
    if not group.active:
        return ["此族群已停用"]
    if not score:
        return ["尚無族群分數"]
    missing: list[str] = []
    if score.data_quality != "complete":
        missing.append("族群資料尚未完整")
    if (score.eligible_members or 0) < 3:
        missing.append(f"有效成員僅 {score.eligible_members or 0} 檔，至少需要 3 檔")
    if score.rank is None:
        missing.append("尚未完成排行")
    if _score_details(score).get("benchmark") != "TAIEX":
        missing.append("缺少 TAIEX 基準")
    return missing


def _theme_why_hot(score: GroupDailyScore | None) -> list[str]:
    if not score:
        return []
    values = (
        ("relative_return_20d", "20 日相對 TAIEX"),
        ("breadth", "成員廣度"),
        ("volume_strength", "量能強度"),
        ("institutional_flow", "法人籌碼"),
    )
    reasons: list[str] = []
    for field, label in values:
        value = getattr(score, field, None)
        if value is not None:
            if field == "breadth":
                reasons.append(f"{label} {value:.0%}")
            else:
                reasons.append(f"{label} {value:.2%}")
    return reasons[:3]


def _safe_group_description(group: ThemeGroup, score: GroupDailyScore | None) -> str:
    if not is_verified_theme(group):
        return "官方族群名稱尚待核實，暫不納入產品解讀。"
    if group.display_description_zh:
        return group.display_description_zh
    if group.group_type == "etf":
        return "依官方 ETF 分類獨立排行，不與公司族群混合。"
    if group.group_type == "daily_hot_group":
        return "依上市日期建立的短期觀察族群。"
    if score and score.eligible_members is not None:
        return "依官方共同產業分類建立的市場族群。"
    return "官方族群資料尚未完整。"


def _safe_theme_missing_reasons(group: ThemeGroup, score: GroupDailyScore | None) -> list[str]:
    if not group.active:
        return ["此族群目前未啟用"]
    if not is_verified_theme(group):
        return ["官方族群名稱尚待核實"]
    if not score:
        return ["尚無已驗證的族群資料"]
    missing: list[str] = []
    if score.data_quality != "complete":
        missing.append("族群資料尚未完整")
    if (score.eligible_members or 0) < 3:
        missing.append(f"目前只有 {score.eligible_members or 0} 檔有效成員，至少需要 3 檔")
    if score.rank is None:
        missing.append("尚未取得有效排行")
    if _score_details(score).get("benchmark") != "TAIEX":
        missing.append("缺少 TAIEX 基準")
    return missing


def _safe_theme_why_hot(score: GroupDailyScore | None) -> list[str]:
    if not score:
        return []
    values = (
        ("relative_return_20d", "20 日相對 TAIEX"),
        ("breadth", "成員上漲廣度"),
        ("volume_strength", "成交量強度"),
        ("institutional_flow", "法人籌碼確認"),
    )
    reasons: list[str] = []
    for field, label in values:
        value = getattr(score, field, None)
        if value is not None:
            reasons.append(f"{label} {value:.0%}" if field == "breadth" else f"{label} {value:.2%}")
    return reasons[:3]


def theme_product_dict(group: ThemeGroup, score: GroupDailyScore | None, db: Session | None = None) -> dict[str, Any]:
    details = _score_details(score)
    qualified = _theme_qualified(group, score)
    metrics = {
        "relative_return_1d": score.relative_return_1d if score else None,
        "relative_return_5d": score.relative_return_5d if score else None,
        "relative_return_20d": score.relative_return_20d if score else None,
        "breadth": score.breadth if score else None,
        "volume_strength": score.volume_strength if score else None,
        "institutional_flow": score.institutional_flow if score else None,
    }
    return {
        "theme_id": group.id,
        "display_name": _group_display_name(group),
        "description": _safe_group_description(group, score),
        "category": group.display_category or ("ETF" if group.group_type == "etf" else "股票族群"),
        "name_status": group.name_status,
        "qualified": qualified,
        "score": score.score if score else None,
        "rank": score.rank if score and qualified else None,
        "trading_date": as_date(score.trading_date) if score else None,
        "data_quality": score.data_quality if score else "missing",
        "eligible_members": score.eligible_members if score else 0,
        "minimum_members": 3,
        "metrics": metrics,
        "why_hot": _safe_theme_why_hot(score) if qualified else [],
        "missing_reasons": [] if qualified else _safe_theme_missing_reasons(group, score),
        "candidate_symbols": _candidate_symbols(score) if qualified else [],
        **_public_candidate_identity(db, group, score if qualified else None),
        "benchmark": details.get("benchmark") if score else None,
        "benchmark_returns": details.get("benchmark_returns", {}) if score else {},
        "leaderboard": details.get("leaderboard") if score else None,
        "methodology": details.get("methodology", {}) if score else {},
    }


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": max(0, int(offset))}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error):
        raise HTTPException(status_code=400, detail="invalid cursor")


def _cursor_response(
    items: list[dict[str, Any]],
    *,
    offset: int,
    limit: int,
    total: int,
    data_as_of: str | None,
    sort: str,
) -> dict[str, Any]:
    has_more = offset + len(items) < total
    return {
        "items": items,
        "meta": {
            "limit": limit,
            "next_cursor": _encode_cursor(offset + len(items)) if has_more else None,
            "has_more": has_more,
            "sort": sort,
            "data_as_of": data_as_of,
            "total": total,
        },
    }


def _directory_response(
    items: list[dict[str, Any]],
    *,
    page: int,
    page_size: int,
    total: int,
    q: str | None,
    data_as_of: str | None,
    sort: str,
) -> dict[str, Any]:
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": items,
        "meta": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "q": q or "",
            "sort": sort,
            "data_as_of": data_as_of,
        },
    }


def _summary_preview(value: str | None, max_length: int = 120) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 1].rstrip() + "…"


def _news_order_by() -> tuple[Any, ...]:
    """Database-side preordering for the canonical product-news keyset.

    The final key is also applied in Python because legacy rows can require an
    Event-derived fallback while they are being reconciled.  Keeping the
    persisted display time first makes the common path indexable without
    changing the immutable cursor contract.
    """

    return (
        desc(NewsItem.display_time).nullslast(),
        desc(NewsItem.canonical_key),
        desc(NewsItem.id),
    )


_NEWS_TIME_BASIS_RANK = {"published": 4, "event": 3, "event_date": 2, "collected": 1, "unverified": 0}
_NEWS_TIME_PRECISION_RANK = {"datetime": 2, "date": 1, "none": 0}


def _news_time_view(db: Session, item: NewsItem) -> tuple[datetime | None, str, str]:
    """Return the persisted immutable display-time fields.

    Rows written before the temporal migration may not have the derived
    columns.  Those rows use the same conservative fallback until the
    idempotent Event projection reconciles them.
    """

    persisted_time = getattr(item, "display_time", None)
    persisted_basis = getattr(item, "time_basis", None)
    persisted_precision = getattr(item, "time_precision", None)
    if (
        persisted_time is not None
        and persisted_basis in _NEWS_TIME_BASIS_RANK
        and persisted_precision in _NEWS_TIME_PRECISION_RANK
    ):
        if persisted_time.tzinfo is not None:
            persisted_time = persisted_time.replace(tzinfo=None)
        return persisted_time, persisted_basis, persisted_precision

    published_at = getattr(item, "published_at", None)
    if published_at is not None:
        return published_at, "published", "datetime"
    event_at = getattr(item, "event_at", None)
    if event_at is not None:
        return event_at, "event", "datetime"
    event_date = getattr(item, "event_date", None)
    if event_date is None and item.event_id:
        event = db.get(Event, item.event_id)
        event_date = event.event_date if event else None
    if event_date is not None:
        return datetime.combine(event_date, datetime.min.time()), "event_date", "date"
    collected_at = getattr(item, "collected_at", None)
    if collected_at is not None:
        return collected_at, "collected", "datetime"
    return None, "unverified", "none"


def _news_sort_key(db: Session, item: NewsItem) -> tuple[Any, ...]:
    display_time, time_basis, time_precision = _news_time_view(db, item)
    return (
        display_time or datetime.min,
        _NEWS_TIME_BASIS_RANK.get(time_basis, 0),
        _NEWS_TIME_PRECISION_RANK.get(time_precision, 0),
        item.canonical_key or "",
        item.id,
    )


def _encode_news_cursor(db: Session, item: NewsItem) -> str:
    display_time, time_basis, time_precision = _news_time_view(db, item)
    payload = {
        "display_time": display_time.isoformat() if display_time else None,
        "time_basis": time_basis,
        "time_precision": time_precision,
        "canonical_key": item.canonical_key,
        "id": item.id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_news_cursor(cursor: str | None) -> tuple[Any, ...] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if not isinstance(payload, dict):
            raise ValueError
        display_time = payload.get("display_time")
        parsed_time = datetime.fromisoformat(display_time) if display_time else datetime.min
        if parsed_time.tzinfo is not None:
            parsed_time = parsed_time.replace(tzinfo=None)
        time_basis = str(payload["time_basis"])
        time_precision = str(payload["time_precision"])
        canonical_key = payload["canonical_key"]
        if not isinstance(canonical_key, str):
            raise ValueError
        item_id = int(payload["id"])
        if time_basis not in _NEWS_TIME_BASIS_RANK or time_precision not in _NEWS_TIME_PRECISION_RANK or item_id < 1:
            raise ValueError
        return (
            parsed_time,
            _NEWS_TIME_BASIS_RANK[time_basis],
            _NEWS_TIME_PRECISION_RANK[time_precision],
            canonical_key,
            item_id,
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid cursor")


def _news_theme_ids(db: Session, item: NewsItem, event: Event | None = None) -> list[str]:
    """Recompute safe themes from current membership, never legacy JSON alone."""

    if getattr(item, "time_consistency", None) == "conflict":
        return []
    event = event or (db.get(Event, item.event_id) if item.event_id else None)
    if event is not None:
        return _theme_ids_for_event(db, event)
    return [
        theme_id
        for theme_id in (item.theme_ids_json or [])
        if is_verified_theme(db.get(ThemeGroup, theme_id))
    ]


def news_dict(db: Session, item: NewsItem) -> dict[str, Any]:
    event = db.get(Event, item.event_id) if item.event_id else None
    display_time, time_basis, time_precision = _news_time_view(db, item)
    time_consistency = getattr(item, "time_consistency", None) or "unverified"
    product_time = build_news_product_time(item, event=event)
    themes = []
    verified_theme_ids = _news_theme_ids(db, item, event)
    for theme_id in verified_theme_ids:
        group = db.get(ThemeGroup, theme_id)
        if is_verified_theme(group):
            themes.append({"theme_id": group.id, "display_name": _group_display_name(group)})
    related_instruments: list[dict[str, str]] = []
    if event and event.instrument_id and time_consistency != "conflict":
        instrument = db.get(Instrument, event.instrument_id)
        if instrument and instrument.symbol in (item.symbols_json or []):
            related_instruments.append(
                {
                    "exchange": instrument.exchange,
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                }
            )
    return {
        "id": str(item.id),
        "canonical_key": item.canonical_key,
        "dedupe_cluster_id": item.dedupe_cluster_id,
        "category": item.category,
        "source_kind": item.source_kind,
        "source_name": item.source_name,
        "source": {
            "name": item.source_name,
            "url": item.source_url,
            "url_kind": item.source_url_kind,
        },
        "source_item_id": item.source_item_id,
        "title": item.title,
        "summary": item.summary,
        "description": event.description if event else item.summary,
        "summary_preview": _summary_preview(item.summary),
        "language": item.language,
        "published_at": as_datetime(item.published_at),
        "event_at": as_datetime(item.event_at),
        "event_date": as_date(getattr(item, "event_date", None) or (event.event_date if event else None)),
        "display_time": as_datetime(display_time),
        "time_basis": time_basis,
        "time_precision": time_precision,
        "time_consistency": time_consistency,
        "product_time": product_time,
        "response_generated_at": product_time["response_generated_at"],
        "collected_at": as_datetime(item.collected_at),
        "symbols": item.symbols_json or [],
        "instruments": related_instruments,
        "themes": themes,
        "theme_ids": verified_theme_ids,
        "impact": {
            "scope": item.impact_scope,
            "direction": item.impact_direction,
            "rationale": item.impact_rationale,
            "method": item.impact_method,
            "confidence": item.confidence,
        },
        "impact_scope": item.impact_scope,
        "impact_direction": item.impact_direction,
        "confidence": item.confidence,
        "status": item.status,
        "content_hash": item.content_hash,
        "detail_url": f"/news/{item.id}",
        "provenance": {
            "event_id": item.event_id,
            "raw_payload_id": item.raw_payload_id,
            "endpoint": event.endpoint if event else None,
            "data_as_of": event.data_as_of if event else None,
        },
    }


_NEWS_SORT_DESCRIPTION = "display_time_desc,time_basis_desc,time_precision_desc,canonical_key_desc,id_desc"


def signal_dict(db: Session, item: Signal, *, include_evidence: bool = True) -> dict[str, Any]:
    instrument = db.get(Instrument, item.instrument_id)
    strategy = db.get(StrategyVersion, item.strategy_version_id) if item.strategy_version_id else None
    evidence = item.rule_evidence_json or {}
    level_semantics = build_level_semantics(
        strategy_name=strategy.name if strategy else None,
        strategy_version=strategy.version if strategy else None,
    )
    product_time = build_signal_product_time(item)
    payload = {
        "id": item.id,
        "signal_key": item.signal_key,
        "signal_date": as_date(item.signal_date),
        "instrument": instrument_dict(instrument),
        "status": item.status,
        "entry_type": item.entry_type,
        "reference_entry": item.reference_entry,
        "pullback_low": item.pullback_low,
        "pullback_high": item.pullback_high,
        "breakout_price": item.breakout_price,
        "invalid_price": item.invalid_price,
        "target_1": item.target_1,
        "target_2": item.target_2,
        "confidence": item.confidence,
        # Keep this compatibility field in compact responses too; consumers
        # must not need the audit-heavy evidence payload to avoid probability
        # language around the legacy numeric column.
        "confidence_semantics": signal_confidence_semantics(
            item.confidence,
            evidence,
            strategy_name=strategy.name if strategy else None,
            strategy_version=strategy.version if strategy else None,
        ),
        "level_semantics": level_semantics,
        "product_time": product_time,
        "response_generated_at": product_time["response_generated_at"],
        "rationale": item.rationale,
        "data_cutoff": item.data_cutoff,
        "source_report": item.source_report,
        "earliest_execution_date": as_date(item.earliest_execution_date),
        "execution_date": as_date(item.execution_date),
        "execution_price": item.execution_price,
        "data_quality": item.data_quality,
        "rule_evidence": canonical_evidence(evidence, level_semantics),
        "strategy": {
            "name": strategy.name,
            "version": strategy.version,
            "kind": strategy.kind,
            "canonical_config_snapshot": strategy.canonical_config_snapshot or {},
        }
        if strategy
        else None,
    }
    if not include_evidence:
        payload.pop("rule_evidence", None)
        if payload.get("strategy"):
            payload["strategy"].pop("canonical_config_snapshot", None)
    return payload


_ACTION_LIST_FIELDS = (
    "instrument",
    "as_of",
    "generated_at",
    "product_time",
    "response_generated_at",
    "level_semantics",
    "stop_price_semantics",
    "action_state",
    "action_label_zh",
    "display_action",
    "action_instruction",
    "display_instruction",
    "display_reasons",
    "primary_reason",
    "primary_levels",
    "data_status",
    "context_badges",
    "detail_url",
    "data_gap",
    "priority",
    "held",
    "watchlisted",
    "current_price",
    "price_as_of",
    "previous_close",
    "price_change",
    "price_change_pct",
    "trigger_kind",
    "trigger_price",
    "entry_low",
    "entry_high",
    "invalid_price",
    "stop_price",
    "target_1",
    "target_2",
    "risk_reward",
    "earliest_execution_date",
    "primary_strategy",
    "alternative_strategies",
    "reasons",
    "conflicts",
    "data_quality",
    "blocking_reasons",
    "missing_data_priority",
    "theme_ids",
    "event_ids",
    "data_cutoff",
)


def compact_action_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Strip audit-heavy fields from list/dashboard action projections."""

    payload = {key: item.get(key) for key in _ACTION_LIST_FIELDS if key in item}
    payload["reasons"] = list(payload.get("reasons") or [])[:3]
    payload["display_reasons"] = list(payload.get("display_reasons") or [])[:3]
    payload["missing_data_priority"] = list(payload.get("missing_data_priority") or [])[:4]
    return payload


def compact_group_summary(group: ThemeGroup, score: GroupDailyScore | None, db: Session | None = None) -> dict[str, Any]:
    """Keep the compatibility dashboard group field lightweight."""

    payload = score_dict(group, score, db)
    payload.pop("methodology", None)
    payload["candidates"] = list(payload.get("candidates") or [])[:4]
    payload["candidate_instruments"] = payload["candidate_instruments"][:4]
    return payload


def compact_theme_summary(group: ThemeGroup, score: GroupDailyScore | None, db: Session | None = None) -> dict[str, Any]:
    """Return the dashboard theme card without research-detail methodology."""

    payload = theme_product_dict(group, score, db)
    payload.pop("methodology", None)
    payload["candidate_symbols"] = list(payload.get("candidate_symbols") or [])[:4]
    payload["candidate_instruments"] = payload["candidate_instruments"][:4]
    return payload


def compact_news_dict(db: Session, item: NewsItem) -> dict[str, Any]:
    """Return the small dashboard/news-list projection.

    The detail endpoint remains the only product surface that needs full
    summary/provenance payloads; list rows carry only the event metadata and
    linked instruments.
    """

    payload = news_dict(db, item)
    return {
        key: payload[key]
        for key in (
            "id",
            "category",
            "source_kind",
            "source_name",
            "source",
            "title",
            "summary_preview",
            "published_at",
            "event_at",
            "event_date",
            "display_time",
            "time_basis",
            "time_precision",
            "time_consistency",
            "product_time",
            "response_generated_at",
            "collected_at",
            "symbols",
            "instruments",
            "themes",
            "theme_ids",
            "impact_direction",
            "confidence",
            "status",
            "detail_url",
        )
    }


def action_candidate_ids(
    db: Session,
    as_of: date | None,
    *,
    q: str | None = None,
    held_only: bool = False,
    watchlist_only: bool = False,
    theme_id: str | None = None,
) -> tuple[list[int], set[int]]:
    """Filter the cheap action candidate projection before decision building."""

    ordered_ids = prioritized_instrument_ids(db, as_of)
    if not ordered_ids:
        return [], set()
    instruments = db.scalars(
        select(Instrument).where(Instrument.id.in_(ordered_ids), Instrument.status == "active")
    ).all()
    by_id = {item.id: item for item in instruments}
    held_ids = set(
        db.scalars(
            select(PortfolioPosition.instrument_id).where(PortfolioPosition.instrument_id.in_(ordered_ids))
        ).all()
    )
    theme_ids: set[int] | None = None
    if theme_id:
        effective_date = as_of or date.today()
        theme_ids = set(
            db.scalars(
                select(GroupMembership.instrument_id).where(
                    GroupMembership.group_id == theme_id,
                    GroupMembership.instrument_id.in_(ordered_ids),
                    GroupMembership.valid_from <= effective_date,
                    (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= effective_date)),
                )
            ).all()
        )
    needle = q.strip().casefold() if q and q.strip() else None
    filtered: list[int] = []
    for instrument_id in ordered_ids:
        instrument = by_id.get(instrument_id)
        if not instrument:
            continue
        if held_only and instrument_id not in held_ids:
            continue
        if watchlist_only and not instrument.is_watchlisted:
            continue
        if theme_ids is not None and instrument_id not in theme_ids:
            continue
        if needle and needle not in f"{instrument.symbol} {instrument.name}".casefold():
            continue
        filtered.append(instrument_id)
    return filtered, held_ids


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "taiwan-stock-research"}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    # Keep the read model current for existing official Events.  This is an
    # idempotent projection only; it does not introduce any non-official feed.
    if sync_news_from_events(db):
        db.commit()
    groups = db.scalars(select(ThemeGroup).where(ThemeGroup.active.is_(True))).all()
    scores = latest_scores(db)
    group_rows = [compact_group_summary(group, scores.get(group.id), db) for group in groups]
    group_rows.sort(key=lambda item: (item["rank"] is None, item["rank"] or 999, item["name"]))

    instruments_count = db.scalar(
        select(func.count(Instrument.id)).where(Instrument.instrument_type != "index")
    ) or 0
    bars_count = db.scalar(select(func.count(MarketBar.id))) or 0
    signal_rows = db.scalars(
        select(Signal).order_by(desc(Signal.signal_date), desc(Signal.id)).limit(8)
    ).all()
    status_rows = db.execute(select(Signal.status, func.count(Signal.id)).group_by(Signal.status)).all()
    run = latest_run(db)
    if run:
        mode = "official" if run.status == "success" else "official_partial"
        source_label = "TWSE/TPEx official feeds"
        scan_scope = "official universe; only rows with complete source data are actionable"
        source_label_zh = "TWSE／TPEx 官方資料"
        scan_scope_label = "官方標的範圍；只有資料完整的項目可進入行動摘要"
    else:
        mode = "no_data"
        source_label = "no configured official collection"
        scan_scope = "no market scan has completed"
        source_label_zh = "尚無已驗證的官方資料"
        scan_scope_label = "尚無已完成的官方市場資料擷取"

    if run and run.data_as_of:
        verified_as_of = run.data_as_of[:10]
    else:
        # A failed official run has no verified market date.  Do not surface
        # an older bar as though it belonged to this run.
        verified_as_of = None

    run, official_as_of = latest_official_as_of(db)
    product_scores = scores_as_of(db, official_as_of) if run and run.status == "success" else {}
    product_themes = [
        compact_theme_summary(group, product_scores.get(group.id), db)
        for group in groups
        if _product_group_taxonomy_verified(db, group, official_as_of)
    ]
    product_themes.sort(key=lambda item: (not item["qualified"], item["rank"] is None, item["rank"] or 999, item["display_name"]))
    product_themes = product_themes[:8]
    # Build only the compact first page for the home dashboard.  Full
    # strategies/evidence/coverage are reserved for stock/action detail.
    action_candidate_ids = prioritized_instrument_ids(db, official_as_of)
    action_rows = build_action_summaries(db, official_as_of, instrument_ids=action_candidate_ids[:8])
    product_news = db.scalars(
        select(NewsItem)
        .outerjoin(Event, NewsItem.event_id == Event.id)
        .where(
            NewsItem.status == "active",
            or_(NewsItem.time_consistency.is_(None), NewsItem.time_consistency != "conflict"),
        )
        .order_by(*_news_order_by())
        .limit(6)
    ).all()
    actionable = [item for item in action_rows if item["action_state"] not in {"data_insufficient", "no_condition"}]
    display_actions = [
        item
        for item in action_rows
        if item["action_state"] != "data_insufficient" or item.get("held")
    ]
    return {
        # An older row with a newer date must not make an official run
        # appear current.  Prefer the run's verified data_as_of when present.
        "as_of": verified_as_of,
        "mode": mode,
        "scan_scope": scan_scope,
        "scan_scope_label": scan_scope_label,
        "market": {
            "instruments": instruments_count,
            "bars": bars_count,
            "groups": len(groups),
            "source": source_label,
            "source_label": source_label_zh,
        },
        "data_quality": {
            "latest_run": run.status if run else "not_started",
            "latest_run_source": run.source if run else None,
            "latest_run_date": as_date(run.run_date) if run else None,
            "latest_run_records": run.records if run else 0,
            "data_as_of": run.data_as_of if run else None,
            "error": run.error if run else None,
            "updated_at": as_datetime(run.updated_at) if run else None,
        },
        "groups": group_rows,
        "signals": [signal_dict(db, item, include_evidence=False) for item in signal_rows],
        "signal_status_counts": {status: count for status, count in status_rows},
        # Product IA read model.  Legacy fields above remain for compatibility
        # with the Phase 1 research surface.
        "news": [compact_news_dict(db, item) for item in product_news],
        "themes": product_themes,
        "candidates": [compact_action_summary(item) for item in actionable[:8]],
        "actions": [compact_action_summary(item) for item in display_actions[:8]],
        "action_counts": {
            "total": len(action_candidate_ids),
            "actionable": len(actionable),
            "data_insufficient": sum(item["action_state"] == "data_insufficient" for item in action_rows),
            "held": sum(bool(item.get("held")) for item in action_rows),
            "scope": "compact_first_page",
        },
        "empty_states": {
            "news": "尚未接入核准的國際／媒體新聞" if not product_news else None,
            "themes": "目前沒有同時達到完整資料與至少 3 檔成員的熱門族群" if not any(item["qualified"] for item in product_themes) else None,
            "actions": "目前沒有資料完整的可執行條件；請查看缺少資料與補齊優先級" if not actionable else None,
        },
    }


@router.get("/news")
def news(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    q: str | None = Query(default=None),
    category: str | None = None,
    symbol: str | None = None,
    theme_id: str | None = None,
    source_kind: str | None = None,
    impact_direction: str | None = None,
    time_consistency: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Existing official Events may predate the product projection.  Refreshing
    # this read model is idempotent and keeps the API useful after migration.
    if sync_news_from_events(db):
        db.commit()
    if time_consistency == "conflict":
        # Quarantined chronology is intentionally opt-in.  It remains
        # addressable for audit, but never enters the default product feed.
        query = select(NewsItem).where(NewsItem.time_consistency == "conflict")
    else:
        query = select(NewsItem).where(NewsItem.status == "active")
        query = query.where(
            or_(NewsItem.time_consistency.is_(None), NewsItem.time_consistency != "conflict")
        )
        if time_consistency:
            query = query.where(NewsItem.time_consistency == time_consistency)
    if category:
        query = query.where(NewsItem.category == category)
    if source_kind:
        query = query.where(NewsItem.source_kind == source_kind)
    if impact_direction:
        query = query.where(NewsItem.impact_direction == impact_direction)
    rows = db.scalars(
        query.outerjoin(Event, NewsItem.event_id == Event.id)
        .order_by(*_news_order_by())
    ).all()
    needle = q.strip().casefold() if q and q.strip() else None
    symbol_needle = symbol.strip().casefold() if symbol and symbol.strip() else None
    filtered: list[NewsItem] = []
    seen_keys: set[str] = set()
    for item in rows:
        identity_keys = {
            value
            for value in (item.canonical_key, item.dedupe_cluster_id, item.content_hash)
            if value
        }
        if identity_keys & seen_keys:
            continue
        if needle:
            haystack = " ".join(
                [
                    item.title or "",
                    item.summary or "",
                    item.source_name or "",
                    " ".join(item.symbols_json or []),
                ]
            ).casefold()
            if needle not in haystack:
                continue
        if symbol_needle and not any(symbol_needle in str(value).casefold() for value in (item.symbols_json or [])):
            continue
        if theme_id and theme_id not in _news_theme_ids(db, item):
            continue
        seen_keys.update(identity_keys)
        filtered.append(item)
    # Use the persisted/derived immutable key for both ordering and paging.
    # This is deliberately a keyset comparison; an offset cursor would shift
    # when a newly collected event arrives ahead of the current page.
    filtered.sort(key=lambda item: _news_sort_key(db, item), reverse=True)
    cursor_key = _decode_news_cursor(cursor)
    if cursor_key is None:
        after_cursor = filtered
    else:
        after_cursor = [item for item in filtered if _news_sort_key(db, item) < cursor_key]
    page = after_cursor[:limit]
    has_more = len(after_cursor) > len(page)
    run, _as_of = latest_official_as_of(db)
    return {
        "items": [news_dict(db, item) for item in page],
        "meta": {
            "limit": limit,
            "next_cursor": _encode_news_cursor(db, page[-1]) if has_more and page else None,
            "has_more": has_more,
            "sort": _NEWS_SORT_DESCRIPTION,
            "data_as_of": run.data_as_of if run else None,
            "total": len(filtered),
        },
    }


@router.get("/news/{news_id}")
def news_detail(news_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return one active projected official event with full audit context."""

    if sync_news_from_events(db):
        db.commit()
    item = db.get(NewsItem, news_id)
    if not item or (item.status != "active" and item.time_consistency != "conflict"):
        raise HTTPException(status_code=404, detail="news item not found")
    return news_dict(db, item)


@router.get("/themes")
def themes(
    q: str | None = Query(default=None),
    leaderboard: str | None = None,
    only_qualified: bool = True,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run, as_of = latest_official_as_of(db)
    score_rows = scores_as_of(db, as_of) if run and run.status == "success" else {}
    rows: list[dict[str, Any]] = []
    for group in db.scalars(select(ThemeGroup).where(ThemeGroup.active.is_(True))).all():
        if not _product_group_taxonomy_verified(db, group, as_of):
            continue
        score = score_rows.get(group.id)
        item = theme_product_dict(group, score, db)
        if only_qualified and not item["qualified"]:
            continue
        if leaderboard and item.get("leaderboard") != leaderboard:
            continue
        if q and q.strip():
            needle = q.strip().casefold()
            haystack = " ".join(
                str(item.get(field) or "")
                for field in ("theme_id", "display_name", "description", "category", "leaderboard")
            ).casefold()
            if needle not in haystack:
                continue
        rows.append(item)
    rows.sort(
        key=lambda item: (
            not item["qualified"],
            item["rank"] is None,
            item["rank"] or 999,
            item["display_name"],
        )
    )
    total = len(rows)
    start = (page - 1) * page_size
    return _directory_response(
        rows[start : start + page_size],
        page=page,
        page_size=page_size,
        total=total,
        q=q,
        data_as_of=run.data_as_of if run else (as_of.isoformat() if as_of else None),
        sort="qualified desc, rank asc, display_name asc",
    )


@router.get("/themes/{theme_id}")
def theme_detail(theme_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    group = db.get(ThemeGroup, theme_id)
    if not group:
        raise HTTPException(status_code=404, detail="theme not found")
    run, as_of = latest_official_as_of(db)
    score = scores_as_of(db, as_of).get(theme_id) if run and run.status == "success" else None
    return {
        "theme": theme_product_dict(group, score, db),
        "methodology": _score_details(score).get("methodology", {}),
        "data_as_of": run.data_as_of if run else (as_of.isoformat() if as_of else None),
    }


@router.get("/themes/{theme_id}/members")
def theme_members(
    theme_id: str,
    q: str | None = Query(default=None),
    sort: str = Query(default="symbol"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    group = db.get(ThemeGroup, theme_id)
    if not group:
        raise HTTPException(status_code=404, detail="theme not found")
    run, as_of = latest_official_as_of(db)
    effective_date = as_of or date.today()
    memberships = db.execute(
        select(GroupMembership, Instrument)
        .join(Instrument, Instrument.id == GroupMembership.instrument_id)
        .where(
            GroupMembership.group_id == theme_id,
            GroupMembership.valid_from <= effective_date,
            (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= effective_date)),
            Instrument.status == "active",
        )
    ).all()
    members: list[dict[str, Any]] = []
    for membership, instrument in memberships:
        if q and q.strip() and q.strip().casefold() not in f"{instrument.symbol} {instrument.name}".casefold():
            continue
        latest_bar = db.scalar(
            select(MarketBar)
            .where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date <= effective_date,
            )
            .order_by(desc(MarketBar.trading_date), desc(MarketBar.id))
            .limit(1)
        )
        members.append(
            {
                **(instrument_dict(instrument) or {}),
                "role": membership.role,
                "confidence": membership.confidence,
                "valid_from": as_date(membership.valid_from),
                "valid_to": as_date(membership.valid_to),
                "latest_bar": bar_dict(latest_bar),
            }
        )
    if sort == "price":
        members.sort(key=lambda item: (item["latest_bar"] is None, -(item["latest_bar"]["close"] if item["latest_bar"] else 0), item["symbol"]))
    elif sort == "name":
        members.sort(key=lambda item: (item["name"], item["symbol"]))
    else:
        members.sort(key=lambda item: (item["exchange"], item["symbol"]))
    total = len(members)
    start = (page - 1) * page_size
    return {
        "theme": theme_product_dict(group, scores_as_of(db, as_of).get(theme_id) if run and run.status == "success" else None, db),
        **_directory_response(
            members[start : start + page_size],
            page=page,
            page_size=page_size,
            total=total,
            q=q,
            data_as_of=run.data_as_of if run else (as_of.isoformat() if as_of else None),
            sort=sort,
        ),
    }


@router.get("/stocks")
def stocks(
    q: str | None = Query(default=None),
    exchange: str | None = None,
    instrument_type: str | None = None,
    theme_id: str | None = None,
    watchlist_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run, as_of = latest_official_as_of(db)
    query = select(Instrument).where(Instrument.status == "active", Instrument.instrument_type != "index")
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(or_(Instrument.symbol.ilike(needle), Instrument.name.ilike(needle)))
    if exchange:
        query = query.where(Instrument.exchange == exchange)
    if instrument_type:
        query = query.where(Instrument.instrument_type == instrument_type)
    if watchlist_only:
        query = query.where(Instrument.is_watchlisted.is_(True))
    if theme_id:
        effective_date = as_of or date.today()
        query = query.join(GroupMembership, GroupMembership.instrument_id == Instrument.id).where(
            GroupMembership.group_id == theme_id,
            GroupMembership.valid_from <= effective_date,
            (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= effective_date)),
        ).distinct()
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(Instrument.exchange, Instrument.symbol, Instrument.id),
    )
    items = []
    for instrument in rows:
        summary = build_decision_summary(db, instrument, as_of)
        items.append(
            {
                "instrument": instrument_dict(instrument),
                "latest_price": summary.get("current_price"),
                "price_as_of": summary.get("price_as_of"),
                "action_state": summary.get("action_state"),
                "action_label_zh": summary.get("action_label_zh"),
                "data_quality": summary.get("data_quality"),
                "missing_data_priority": summary.get("missing_data_priority", []),
                "product_time": summary.get("product_time"),
                "response_generated_at": summary.get("response_generated_at"),
            }
        )
    return _directory_response(
        items,
        page=page,
        page_size=page_size,
        total=total,
        q=q,
        data_as_of=run.data_as_of if run else (as_of.isoformat() if as_of else None),
        sort="exchange asc, symbol asc",
    )


@router.get("/stocks/{exchange}/{symbol}")
def stock_detail(exchange: str, symbol: str, db: Session = Depends(get_db), as_of: date | None = None) -> dict[str, Any]:
    instrument_row = _find_instrument(db, symbol, exchange)
    if not instrument_row:
        raise HTTPException(status_code=404, detail="instrument not found")
    cutoff = resolve_stock_cutoff(db, instrument_row, as_of)
    # No dated records means no shared cutoff can be established. Keep this
    # explicit; date.min prevents current feature/decision fallback from leaking in.
    payload = instrument_detail(symbol, exchange, db, cutoff or date.min)
    instrument = payload["instrument"]
    instrument_row = db.get(Instrument, instrument["id"])
    payload["decision_summary"] = build_decision_summary(db, instrument_row, cutoff) if instrument_row and cutoff and cutoff >= date(1, 1, 8) else None
    payload["overview"] = build_stock_overview(db, instrument_row, cutoff)
    if payload["decision_summary"]:
        payload["product_time"] = payload["decision_summary"].get("product_time")
        payload["response_generated_at"] = payload["decision_summary"].get("response_generated_at")
    payload["coverage"] = (
        payload["decision_summary"].get("coverage")
        if payload.get("decision_summary")
        else None
    )
    # News remains a sub-section of the stock detail; the main product feed is
    # still /news and its cursor contract.
    if instrument_row:
        news_rows = db.scalars(
            select(NewsItem)
            .where(
                NewsItem.status == "active",
                or_(NewsItem.time_consistency.is_(None), NewsItem.time_consistency != "conflict"),
                NewsItem.symbols_json.contains([instrument_row.symbol]),
                _stock_news_cutoff_filter(cutoff),
            )
            .outerjoin(Event, NewsItem.event_id == Event.id)
            .order_by(*_news_order_by())
            .limit(20)
        ).all()
        payload["news"] = [news_dict(db, item) for item in news_rows]
        payload["news_cutoff"] = {"as_of": cutoff.isoformat() if cutoff else None,
                                  "filter": "verified_publication_or_event", "limit": 20}
    else:
        payload["news"] = []
    return payload


def _stock_news_cutoff_filter(cutoff: date | None):
    """Apply original-time cutoff in SQL before the existing 20-row limit.

    app.news persists publication/event instants as UTC-naive DateTime. Date-only
    event roles stay dates; collection timestamps never qualify this section.
    """
    if cutoff is None:
        return False
    last_utc_instant = datetime.combine(cutoff, datetime.max.time()) - timedelta(hours=8)
    persisted = and_(NewsItem.display_time.is_not(None), NewsItem.time_basis.in_(_NEWS_TIME_BASIS_RANK),
                     NewsItem.time_precision.in_(_NEWS_TIME_PRECISION_RANK))
    event_day = func.coalesce(NewsItem.event_date, Event.event_date)
    original_fallback = or_(
        and_(NewsItem.published_at.is_not(None), NewsItem.published_at <= last_utc_instant),
        and_(NewsItem.published_at.is_(None), NewsItem.event_at.is_not(None), NewsItem.event_at <= last_utc_instant),
        and_(NewsItem.published_at.is_(None), NewsItem.event_at.is_(None), event_day <= cutoff),
    )
    return and_(NewsItem.time_consistency == "verified", or_(
        and_(persisted, NewsItem.time_basis.in_({"published", "event"}), NewsItem.time_precision == "datetime",
             NewsItem.display_time <= last_utc_instant),
        and_(persisted, NewsItem.time_basis == "event_date", NewsItem.time_precision == "date", event_day <= cutoff),
        and_(~func.coalesce(persisted, False), original_fallback),
    ))


@router.get("/stocks/{exchange}/{symbol}/overview")
def stock_overview(exchange: str, symbol: str, db: Session = Depends(get_db), as_of: date | None = None) -> dict[str, Any]:
    instrument = _find_instrument(db, symbol, exchange)
    if not instrument:
        raise HTTPException(status_code=404, detail="instrument not found")
    return build_stock_overview(db, instrument, as_of)


@router.get("/actions")
def actions(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    q: str | None = Query(default=None),
    state: str | None = None,
    held_only: bool = False,
    watchlist_only: bool = False,
    theme_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run, as_of = latest_official_as_of(db)
    filtered_ids, held_ids = action_candidate_ids(
        db,
        as_of,
        q=q,
        held_only=held_only,
        watchlist_only=watchlist_only,
        theme_id=theme_id,
    )
    offset = _decode_cursor(cursor)
    # A state filter depends on the composed decision and therefore cannot be
    # answered from the cheap identity projection alone.  It is an explicit
    # narrow query, so preserve its exact old semantics; the default list path
    # below only builds the requested page.
    if state:
        state_rows = build_action_summaries(db, as_of, instrument_ids=filtered_ids)
        state_rows = [item for item in state_rows if item.get("action_state") == state]
        state_rows.sort(key=lambda item: filtered_ids.index(item["instrument"]["id"]) if item.get("instrument", {}).get("id") in filtered_ids else len(filtered_ids))
        total = len(state_rows)
        page = state_rows[offset : offset + limit]
        held_count = sum(bool(item.get("held")) for item in state_rows)
        actionable_count = sum(item.get("action_state") in {"conditional_entry", "wait_breakout", "wait_pullback", "hold_observe", "reduce_exit", "manual_review"} for item in state_rows)
        data_insufficient_count = sum(item.get("action_state") == "data_insufficient" for item in state_rows)
    else:
        page_ids = filtered_ids[offset : offset + limit]
        page = build_action_summaries(db, as_of, instrument_ids=page_ids)
        by_id = {item.get("instrument", {}).get("id"): item for item in page}
        page = [by_id[item_id] for item_id in page_ids if item_id in by_id]
        total = len(filtered_ids)
        held_count = sum(item_id in held_ids for item_id in filtered_ids)
        actionable_count = sum(item.get("action_state") in {"conditional_entry", "wait_breakout", "wait_pullback", "hold_observe", "reduce_exit", "manual_review"} for item in page)
        data_insufficient_count = sum(item.get("action_state") == "data_insufficient" for item in page)
    return _cursor_response(
        [compact_action_summary(item) for item in page],
        offset=offset,
        limit=limit,
        total=total,
        data_as_of=run.data_as_of if run else (as_of.isoformat() if as_of else None),
        sort="priority asc, held desc, watchlisted desc, exchange asc, symbol asc",
    ) | {
        "taxonomy": ACTION_LABELS,
        "summary": {
            "total": total,
            "actionable": actionable_count,
            "data_insufficient": data_insufficient_count,
            "held": held_count,
            "scope": "filtered_results" if state else "page_for_actionable_and_data_insufficient_counts",
        },
    }


@router.get("/actions/{exchange}/{symbol}")
def action_detail(exchange: str, symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    instrument = _find_instrument(db, symbol, exchange)
    if not instrument:
        raise HTTPException(status_code=404, detail="instrument not found")
    decision = build_decision_summary(db, instrument)
    return {
        "decision_summary": decision,
        "product_time": decision.get("product_time"),
        "response_generated_at": decision.get("response_generated_at"),
    }


@router.get("/system/data-quality")
def system_data_quality(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    q: str | None = Query(default=None),
    entity_type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(DataQuality)
    if entity_type:
        query = query.where(DataQuality.entity_type == entity_type)
    if status:
        query = query.where(DataQuality.status == status)
    rows = db.scalars(query.order_by(desc(DataQuality.as_of_date), desc(DataQuality.id))).all()
    needle = q.strip().casefold() if q and q.strip() else None
    if needle:
        rows = [
            row
            for row in rows
            if needle in f"{row.entity_type} {row.entity_key} {row.status} {row.source or ''}".casefold()
        ]
    offset = _decode_cursor(cursor)
    page = rows[offset : offset + limit]
    return _cursor_response(
        [quality_dict(item) for item in page],
        offset=offset,
        limit=limit,
        total=len(rows),
        data_as_of=None,
        sort="as_of_date desc, id desc",
    )


@router.get("/glossary")
def glossary(q: str | None = Query(default=None), category: str | None = None) -> dict[str, Any]:
    items = glossary_terms(q=q, category=category)
    return {"items": items, "meta": {"version": GLOSSARY_VERSION, "total": len(items)}}


@router.get("/groups")
def groups(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    scores = latest_scores(db)
    rows = [
        score_dict(group, scores.get(group.id), db)
        for group in db.scalars(select(ThemeGroup).where(ThemeGroup.active.is_(True))).all()
    ]
    if q and q.strip():
        needle = q.strip().casefold()
        rows = [
            row
            for row in rows
            if any(
                needle in str(row.get(field) or "").casefold()
                for field in ("group_id", "name", "group_type", "leaderboard")
            )
        ]
    rows = sorted(rows, key=lambda item: (item["rank"] is None, item["rank"] or 999, item["name"]))
    total = len(rows)
    start = (page - 1) * page_size
    return _page_response(rows[start : start + page_size], page=page, page_size=page_size, total=total)


@router.get("/groups/{group_id}")
def group_detail(group_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    group = db.get(ThemeGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    score = latest_scores(db).get(group_id)
    memberships = db.scalars(
        select(GroupMembership)
        .where(GroupMembership.group_id == group_id)
        .order_by(GroupMembership.valid_from, GroupMembership.id)
    ).all()
    members: list[dict[str, Any]] = []
    for membership in memberships:
        instrument = db.get(Instrument, membership.instrument_id)
        if not instrument:
            continue
        latest_bar = db.scalar(
            select(MarketBar)
            .where(MarketBar.instrument_id == instrument.id)
            .order_by(desc(MarketBar.trading_date))
            .limit(1)
        )
        latest_feature = db.scalar(
            select(TechnicalFeature)
            .where(TechnicalFeature.instrument_id == instrument.id)
            .order_by(desc(TechnicalFeature.trading_date))
            .limit(1)
        )
        members.append(
            {
                **(instrument_dict(instrument) or {}),
                "role": membership.role,
                "confidence": membership.confidence,
                "valid_from": as_date(membership.valid_from),
                "valid_to": as_date(membership.valid_to),
                "latest_bar": bar_dict(latest_bar),
                "features": latest_feature.features_json if latest_feature else {},
            }
        )
    members.sort(key=lambda item: (item["latest_bar"] is None, -(item["latest_bar"]["close"] if item["latest_bar"] else 0)))
    return {
        "group": score_dict(group, score, db),
        "members": members,
        "methodology": _score_details(score).get("methodology", {}),
    }


@router.get("/instruments")
def instruments(
    q: str | None = Query(default=None),
    instrument_type: str | None = None,
    exchange: str | None = None,
    watchlist_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(Instrument).where(Instrument.status == "active")
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(or_(Instrument.symbol.ilike(needle), Instrument.name.ilike(needle)))
    if instrument_type:
        query = query.where(Instrument.instrument_type == instrument_type)
    if exchange:
        query = query.where(Instrument.exchange == exchange)
    if watchlist_only:
        query = query.where(Instrument.is_watchlisted.is_(True))
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(Instrument.exchange, Instrument.symbol, Instrument.id),
    )
    return _page_response(
        [instrument_dict(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


def _find_instrument(db: Session, symbol: str, exchange: str | None = None) -> Instrument | None:
    query = select(Instrument).where(Instrument.symbol == symbol)
    if exchange:
        query = query.where(Instrument.exchange == exchange)
    return db.scalar(query.order_by(Instrument.id).limit(1))


def _instrument_quality_summary(
    db: Session,
    instrument: Instrument,
    bars: list[MarketBar],
    decision: dict[str, Any],
) -> dict[str, Any]:
    run, as_of = latest_official_as_of(db)
    latest_bar = bars[0] if bars else None
    market_missing: list[str] = []
    if not run or run.status != "success" or not as_of:
        market_missing.append("official_run")
    if not latest_bar:
        market_missing.append("market_bar")
    elif as_of and latest_bar.trading_date != as_of:
        market_missing.append("latest_market_date")
    elif (latest_bar.source or "").casefold().endswith("fixture"):
        market_missing.append("official_market_source")
    market_status = "complete" if not market_missing else ("partial" if latest_bar else "missing")
    research_status = decision.get("data_quality") or "missing"
    if research_status == "complete":
        research_label = "策略判斷資料完整"
    else:
        # Product pages must not expose the raw/ambiguous distinction between
        # partial and insufficient.  The missing_fields list below carries the
        # exact reason; this label only states the research purpose.
        research_label = "策略判斷資料待補"
    return {
        "market": {
            "status": market_status,
            "label": "當日行情來源完整" if market_status == "complete" else "當日行情來源尚未完整",
            "as_of": as_of.isoformat() if as_of else None,
            "missing_fields": market_missing,
            "source": run.source if run else None,
        },
        "research": {
            "status": research_status,
            "label": research_label,
            "as_of": decision.get("as_of"),
            "missing_fields": decision.get("blocking_reasons") or [],
            "action_state": decision.get("action_state"),
        },
        "instrument": f"{instrument.exchange}:{instrument.symbol}",
    }


def _source_action_classification(item: CorporateAction, instrument: Instrument) -> dict[str, Any]:
    """Project local source-field consistency, not event identity or authenticity."""
    details = item.details_json
    raw = details.get("Exdividend") if isinstance(details, Mapping) else None
    result = {"kind": "unknown", "label": "未知",
              "raw": {"field": "Exdividend", "value": raw if isinstance(raw, str) else None},
              "reason": "unsupported_source"}
    if item.source != "twse" or instrument.exchange != "TWSE":
        return result
    if not isinstance(details, Mapping) or not details:
        return dict(result, reason="invalid_details")
    fields = [details.get(key) for key in ("Code", "Date", "Exdividend")]
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        return dict(result, reason="missing_official_field")
    code, day, kind = (value.strip() for value in fields)

    def roc_date(value: str) -> date | None:
        if len(value) != 7 or not value.isascii() or not value.isdigit():
            return None
        try:
            return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:]))
        except ValueError:
            return None

    parsed_day = roc_date(day)
    kinds = {"息": ("ex_dividend", "除息"), "權": ("ex_right", "除權"),
             "權息": ("ex_right_and_dividend", "除權息")}
    for alias in ("股票代號", "證券代號", "除權息日期", "除權息"):
        value = details.get(alias)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            return dict(result, reason="alias_conflict")
        value = value.strip()
        if alias == "除權息日期":
            matches = parsed_day is not None and roc_date(value) == parsed_day
        elif alias == "除權息":
            matches = value in kinds and value == kind
        else:
            matches = value == code
        if not matches:
            return dict(result, reason="alias_conflict")
    if code != instrument.symbol or parsed_day is None or parsed_day != item.action_date:
        return dict(result, reason="identity_mismatch")
    if kind not in kinds:
        return dict(result, reason="unknown_raw_value")
    return dict(result, kind=kinds[kind][0], label=kinds[kind][1], reason="trusted_twse_exact_fields")


@router.get("/instruments/{symbol}")
def instrument_detail(symbol: str, exchange: str | None = None, db: Session = Depends(get_db), as_of: date | None = None) -> dict[str, Any]:
    instrument = _find_instrument(db, symbol, exchange)
    if not instrument:
        raise HTTPException(status_code=404, detail="instrument not found")
    bars = db.scalars(
        select(MarketBar)
        .where(MarketBar.instrument_id == instrument.id, MarketBar.trading_date <= (as_of or date.max))
        .order_by(desc(MarketBar.trading_date))
        .limit(120)
    ).all()
    feature = db.scalar(
        select(TechnicalFeature)
        .where(TechnicalFeature.instrument_id == instrument.id, TechnicalFeature.trading_date <= (as_of or date.max))
        .order_by(desc(TechnicalFeature.trading_date))
        .limit(1)
    )
    memberships = db.scalars(
        select(GroupMembership)
        .where(GroupMembership.instrument_id == instrument.id,
               GroupMembership.valid_from <= (as_of or date.max),
               or_(GroupMembership.valid_to.is_(None), GroupMembership.valid_to >= as_of) if as_of else True)
        .order_by(GroupMembership.valid_from)
    ).all()
    signals = db.scalars(
        select(Signal)
        .where(Signal.instrument_id == instrument.id, Signal.signal_date <= (as_of or date.max))
        .order_by(desc(Signal.signal_date), desc(Signal.id))
        .limit(20)
    ).all()
    chips = db.scalars(
        select(ChipSnapshot)
        .where(ChipSnapshot.instrument_id == instrument.id, ChipSnapshot.trading_date <= (as_of or date.max))
        .order_by(desc(ChipSnapshot.trading_date))
        .limit(120)
    ).all()
    actions = db.scalars(
        select(CorporateAction)
        .where(CorporateAction.instrument_id == instrument.id, CorporateAction.action_date <= (as_of or date.max))
        .order_by(desc(CorporateAction.action_date))
        .limit(50)
    ).all()
    fundamentals = db.scalars(
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.instrument_id == instrument.id, FundamentalSnapshot.period_end <= (as_of or date.max),
               FundamentalSnapshot.announcement_date <= as_of if as_of else True)
        .order_by(desc(FundamentalSnapshot.period_end))
        .limit(20)
    ).all()
    events = db.scalars(
        select(Event)
        .where(Event.instrument_id == instrument.id, Event.event_date <= (as_of or date.max))
        .order_by(desc(Event.event_date), desc(Event.id))
        .limit(50)
    ).all()
    quality = db.scalars(
        select(DataQuality)
        .where(
            DataQuality.entity_type == "instrument",
            DataQuality.entity_key == f"{instrument.exchange}:{instrument.symbol}",
            DataQuality.as_of_date <= (as_of or date.max),
        )
        .order_by(desc(DataQuality.as_of_date), desc(DataQuality.id))
        .limit(10)
    ).all()
    decision = build_decision_summary(db, instrument, as_of) if as_of is None or as_of >= date(1, 1, 8) else {}
    return {
        "instrument": instrument_dict(instrument),
        "bars": [bar_dict(item) for item in reversed(bars)],
        "features": feature.features_json if feature else {},
        "groups": [
            {
                "id": membership.group_id,
                "name": db.get(ThemeGroup, membership.group_id).name if db.get(ThemeGroup, membership.group_id) else membership.group_id,
                "valid_from": as_date(membership.valid_from),
                "valid_to": as_date(membership.valid_to),
            }
            for membership in memberships
        ],
        "chips": [chip_dict(item) for item in reversed(chips)],
        "corporate_actions": [
            {
                "date": as_date(item.action_date),
                "type": item.action_type,
                "source_action_classification": _source_action_classification(item, instrument),
                "cash_dividend": item.cash_dividend,
                "stock_dividend_ratio": item.stock_dividend_ratio,
                "split_ratio": item.split_ratio,
                "reference_price": item.reference_price,
                "source": item.source,
                "data_as_of": item.data_as_of,
            }
            for item in actions
        ],
        "fundamentals": [
            {
                "period_end": as_date(item.period_end),
                "fiscal_period": item.fiscal_period,
                "announcement_date": as_date(item.announcement_date),
                "revenue": item.revenue,
                "eps": item.eps,
                "roe": item.roe,
                "source": item.source,
                "data_as_of": item.data_as_of,
            }
            for item in fundamentals
        ],
        "events": [
            {
                "date": as_date(item.event_date),
                "type": item.event_type,
                "title": item.title,
                "description": item.description,
                "source": item.source,
                "data_as_of": item.data_as_of,
            }
            for item in events
        ],
        "data_quality": [quality_dict(item) for item in quality],
        "product_time": decision.get("product_time"),
        "response_generated_at": decision.get("response_generated_at"),
        "quality_summary": _instrument_quality_summary(db, instrument, bars, decision),
        "strategy_conditions": {
            "breakout": {
                "label": "突破條件",
                "requires": ["20 日前期高點", "20 日前期成交量", "族群相對 TAIEX 的 20 日超額報酬", "5 日法人流向", "5 日融資餘額變化率"],
                "source": "系統固定研究規則",
                "technical": {"rule_label": "突破條件固定版本", "basis_label": "只使用資料日以前的已驗證資料"},
            },
            "pullback": {
                "label": "回踩條件",
                "requires": ["60 日有效行情日數", "MA20", "MA60", "20 日前期成交量", "族群相對 TAIEX 的 20 日超額報酬", "5 日法人流向", "5 日融資餘額變化率"],
                "source": "系統固定研究規則",
                "technical": {"rule_label": "回踩條件固定版本", "basis_label": "只使用資料日以前的已驗證資料"},
            },
        },
        "signals": [signal_dict(db, item) for item in signals],
    }


@router.get("/signals")
def signals(
    status: str | None = None,
    instrument_symbol: str | None = None,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(Signal).join(Instrument, Instrument.id == Signal.instrument_id)
    if status:
        query = query.where(Signal.status == status)
    if instrument_symbol:
        query = query.where(Instrument.symbol == instrument_symbol)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                Signal.signal_key.ilike(needle),
                Instrument.symbol.ilike(needle),
                Instrument.name.ilike(needle),
            )
        )
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(desc(Signal.signal_date), desc(Signal.id)),
    )
    return _page_response(
        [signal_dict(db, item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/signals/{signal_id}")
def signal_detail(signal_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    signal = db.get(Signal, signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="signal not found")
    evaluations = db.scalars(
        select(SignalEvaluation)
        .where(SignalEvaluation.signal_id == signal.id)
        .order_by(SignalEvaluation.session_no, SignalEvaluation.session_date)
    ).all()
    settlements = db.scalars(
        select(SignalSettlement)
        .where(SignalSettlement.signal_id == signal.id)
        .order_by(SignalSettlement.horizon)
    ).all()
    return {
        "signal": signal_dict(db, signal),
        "evaluations": [evaluation_dict(item) for item in evaluations],
        "settlements": [settlement_dict(item) for item in settlements],
    }


@router.get("/events")
def events(
    q: str | None = Query(default=None),
    event_type: str | None = None,
    exchange: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(Event).outerjoin(Instrument, Instrument.id == Event.instrument_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if exchange:
        query = query.where(Instrument.exchange == exchange)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                Event.title.ilike(needle),
                Event.description.ilike(needle),
                Event.event_type.ilike(needle),
                Event.source.ilike(needle),
                Instrument.symbol.ilike(needle),
                Instrument.name.ilike(needle),
            )
        )
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(desc(Event.event_date), desc(Event.id)),
    )
    return _page_response(
        [event_dict(db, item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


def _tracking_rows(db: Session, signal_key: str | None = None) -> list[dict[str, Any]]:
    query = select(SignalEvaluation).order_by(desc(SignalEvaluation.session_date), desc(SignalEvaluation.id)).limit(1000)
    evaluations = db.scalars(query).all()
    rows: list[dict[str, Any]] = []
    for evaluation in evaluations:
        signal = db.get(Signal, evaluation.signal_id)
        if not signal or (signal_key and signal.signal_key != signal_key):
            continue
        instrument = db.get(Instrument, signal.instrument_id)
        rows.append(
            {
                "signal": signal_dict(db, signal),
                "instrument": instrument_dict(instrument),
                "evaluation": evaluation_dict(evaluation),
            }
        )
    return rows


@router.get("/tracking")
def tracking(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = _tracking_rows(db)
    settlements = db.scalars(
        select(SignalSettlement).order_by(desc(SignalSettlement.settlement_date), desc(SignalSettlement.id)).limit(1000)
    ).all()
    return {
        "rows": rows,
        "settlements": [
            {
                **settlement_dict(item),
                "signal_key": db.get(Signal, item.signal_id).signal_key if db.get(Signal, item.signal_id) else None,
            }
            for item in settlements
        ],
        "summary": {
            "evaluation_rows": len(rows),
            "settlement_rows": len(settlements),
            "horizons": [5, 20],
        },
    }


@router.get("/tracking/{signal_key}")
def tracking_signal(signal_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    signal = db.scalar(select(Signal).where(Signal.signal_key == signal_key))
    if not signal:
        raise HTTPException(status_code=404, detail="signal not found")
    settlements = db.scalars(
        select(SignalSettlement).where(SignalSettlement.signal_id == signal.id).order_by(SignalSettlement.horizon)
    ).all()
    return {
        "signal": signal_dict(db, signal),
        "evaluations": _tracking_rows(db, signal_key),
        "settlements": [settlement_dict(item) for item in settlements],
    }


class PositionInput(BaseModel):
    symbol: str
    exchange: str | None = None
    shares: StrictInt | None = Field(default=None, gt=0)
    unit: str | None = None
    quantity: StrictInt | None = Field(default=None, gt=0)
    quantity_lots: StrictInt | None = Field(default=None, gt=0)
    odd_lot_shares: StrictInt | None = Field(default=None, gt=0)
    average_cost: float | None = Field(default=None, ge=0)
    stop_price: float | None = Field(default=None, ge=0)
    risk_budget: float | None = Field(default=None, ge=0)
    note: str | None = None

    @model_validator(mode="after")
    def normalize_quantity(self) -> "PositionInput":
        self.shares = shares_from_position_quantity(
            shares=self.shares,
            unit=self.unit,
            quantity=self.quantity,
            quantity_lots=self.quantity_lots,
            odd_lot_shares=self.odd_lot_shares,
        )
        return self


def position_dict(db: Session, position: PortfolioPosition) -> dict[str, Any]:
    instrument = db.get(Instrument, position.instrument_id)
    latest_bar = db.scalar(
        select(MarketBar)
        .where(MarketBar.instrument_id == position.instrument_id)
        .order_by(desc(MarketBar.trading_date))
        .limit(1)
    )
    market_value = latest_bar.close * position.shares if latest_bar else None
    cost_value = position.average_cost * position.shares if position.average_cost is not None else None
    return {
        "id": position.id,
        "instrument": instrument_dict(instrument),
        "shares": position.shares,
        "quantity": share_quantity_dict(position.shares),
        "average_cost": position.average_cost,
        "stop_price": position.stop_price,
        "risk_budget": position.risk_budget,
        "note": position.note,
        "updated_at": as_datetime(position.updated_at),
        "latest_bar": bar_dict(latest_bar),
        "market_value": market_value,
        "unrealized_pnl": market_value - cost_value if market_value is not None and cost_value is not None else None,
    }


@router.get("/portfolio")
def portfolio(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(PortfolioPosition).join(Instrument, Instrument.id == PortfolioPosition.instrument_id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(or_(Instrument.symbol.ilike(needle), Instrument.name.ilike(needle)))
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(PortfolioPosition.id,),
    )
    return _page_response(
        [position_dict(db, position) for position in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/portfolio")
def upsert_portfolio(position_input: PositionInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    instrument = _find_instrument(db, position_input.symbol.strip(), position_input.exchange)
    if not instrument:
        raise HTTPException(status_code=404, detail="instrument not found")
    position = db.scalar(select(PortfolioPosition).where(PortfolioPosition.instrument_id == instrument.id))
    if not position:
        position = PortfolioPosition(instrument_id=instrument.id)
        db.add(position)
    position.shares = position_input.shares
    position.average_cost = position_input.average_cost
    position.stop_price = position_input.stop_price
    position.risk_budget = position_input.risk_budget
    position.note = position_input.note
    position.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(position)
    return position_dict(db, position)


@router.delete("/portfolio/{position_id}")
def delete_portfolio(position_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    position = db.get(PortfolioPosition, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="portfolio position not found")
    db.delete(position)
    db.commit()
    return {"status": "deleted", "id": position_id}


@router.get("/data-quality")
def data_quality(
    entity_type: str | None = None,
    status: str | None = None,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(DataQuality)
    if entity_type:
        query = query.where(DataQuality.entity_type == entity_type)
    if status:
        query = query.where(DataQuality.status == status)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                DataQuality.entity_type.ilike(needle),
                DataQuality.entity_key.ilike(needle),
                DataQuality.status.ilike(needle),
                DataQuality.source.ilike(needle),
            )
        )
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(desc(DataQuality.as_of_date), desc(DataQuality.id)),
    )
    return _page_response(
        [quality_dict(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/raw-payloads")
def raw_payloads(
    ingestion_run_id: int | None = None,
    source: str | None = None,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(RawPayload)
    if ingestion_run_id is not None:
        query = query.where(RawPayload.ingestion_run_id == ingestion_run_id)
    if source:
        query = query.where(RawPayload.source == source)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                RawPayload.source.ilike(needle),
                RawPayload.endpoint.ilike(needle),
                RawPayload.payload_path.ilike(needle),
                RawPayload.sha256.ilike(needle),
                RawPayload.data_as_of.ilike(needle),
            )
        )
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(desc(RawPayload.collected_at), desc(RawPayload.id)),
    )
    return _page_response(
        [raw_payload_dict(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/ingestion-runs")
def ingestion_runs(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(IngestionRun)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                IngestionRun.run_type.ilike(needle),
                IngestionRun.source.ilike(needle),
                IngestionRun.status.ilike(needle),
                IngestionRun.request_key.ilike(needle),
                IngestionRun.error.ilike(needle),
                IngestionRun.data_as_of.ilike(needle),
            )
        )
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(desc(IngestionRun.updated_at), desc(IngestionRun.id)),
    )
    items = [
        {
            "id": run.id,
            "run_type": run.run_type,
            "source": run.source,
            "run_date": as_date(run.run_date),
            "status": run.status,
            "records": run.records,
            "error": run.error,
            "request_key": run.request_key,
            "data_as_of": run.data_as_of,
            "metadata": run.metadata_json or {},
            "started_at": as_datetime(run.started_at),
            "finished_at": as_datetime(run.finished_at),
            "updated_at": as_datetime(run.updated_at),
        }
        for run in rows
    ]
    return _page_response(items, page=page, page_size=page_size, total=total)


@router.get("/backtest/summary")
def backtest_summary(run_id: int | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Expose technical backtest counts, explicitly separated by universe type."""

    return summarize_backtest(db, run_id)


@router.get("/backfill-runs")
def backfill_runs(
    q: str | None = Query(default=None),
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(IngestionRun).where(IngestionRun.run_type == "backfill")
    if status:
        query = query.where(IngestionRun.status == status)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                IngestionRun.source.ilike(needle),
                IngestionRun.status.ilike(needle),
                IngestionRun.request_key.ilike(needle),
                IngestionRun.error.ilike(needle),
            )
        )
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(desc(IngestionRun.updated_at), desc(IngestionRun.id)),
    )
    return _page_response(
        [backfill_run_dict(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/backfill-runs/{run_id}")
def backfill_run_detail(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = get_backfill_run(db, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="backfill run not found")
    return result


@router.get("/coverage")
def coverage(
    start_date: date | None = None,
    end_date: date | None = None,
    scope: str | None = Query(default=None),
    exchange: str | None = None,
    symbol: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    has_manifest = has_backfill_manifest(db)
    explicit_range = start_date is not None or end_date is not None
    latest = db.scalar(select(func.max(MarketBar.trading_date)))
    resolved_end = end_date or latest or date.today()
    if start_date is not None:
        resolved_start = start_date
    elif not has_manifest and not explicit_range:
        # A no-run snapshot has no bounded calendar to report.  Keep the
        # default response compact and tied to the observed cutoff.
        resolved_start = resolved_end
    else:
        resolved_start = resolved_end - timedelta(days=OFFICIAL_MAX_BACKFILL_DAYS)
    if resolved_start > resolved_end:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")

    target_keys: set[tuple[str, str]] | None = None
    scope_info: dict[str, Any] | None = None
    if scope:
        if scope.strip().lower() not in BACKFILL_SCOPES:
            raise HTTPException(status_code=422, detail="unsupported coverage scope")
        scope_info = resolve_backfill_scope(db, scope, resolved_start, resolved_end)
        target_keys = None if scope_info["scope"] in {"market", "all"} else set(scope_info["target_keys"])
    elif exchange or symbol:
        query = select(Instrument).where(Instrument.status == "active")
        if exchange:
            query = query.where(Instrument.exchange == exchange)
        if symbol:
            query = query.where(Instrument.symbol == symbol)
        target_keys = {
            (item.exchange, item.symbol)
            for item in db.scalars(query).all()
            if item.instrument_type in {"stock", "etf", "ipo"}
        }

    report = coverage_report(
        db,
        resolved_start,
        resolved_end,
        target_keys=target_keys,
        require_provenance=not has_manifest,
        include_calendar_dates=has_manifest or explicit_range,
    )
    report["scope"] = scope_info["scope"] if scope_info else ("instrument_filter" if target_keys is not None else "market")
    return report


@router.get("/strategies")
def strategies(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page_size = _effective_page_size(page_size, limit)
    query = select(StrategyVersion)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                StrategyVersion.name.ilike(needle),
                StrategyVersion.version.ilike(needle),
                StrategyVersion.kind.ilike(needle),
            )
        )
    rows, total = _paginate_query(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(StrategyVersion.name, StrategyVersion.version, StrategyVersion.id),
    )
    items = [
        {
            "name": row.name,
            "version": row.version,
            "kind": row.kind,
            "active": row.active,
            "config": row.config_json or {},
            "canonical_config_snapshot": row.canonical_config_snapshot or {},
            "created_at": as_datetime(row.created_at),
        }
        for row in rows
    ]
    return _page_response(items, page=page, page_size=page_size, total=total)


def configure_cors(app) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEFAULT_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
