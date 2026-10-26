"""``dashboard.market_overview``: stored market summaries of the dashboard date.

Only reads ``market_summaries`` written by collect and ``worker.cli
market-summary`` (Issue #275).  Each exchange is shown for ``dashboard.as_of``
alone; a row of another date is never shown in its place.
"""

from __future__ import annotations

from datetime import date, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .models import MarketSummary

EXCHANGES = ("TWSE", "TPEx")
INDEX_LABELS = {"TWSE": "加權指數", "TPEx": "櫃買指數"}
SOURCE_LABELS = {
    "twse_mi_index": "臺灣證券交易所 MI_INDEX",
    "tpex_mainborad_highlight": "櫃買中心 tpex_mainborad_highlight",
}
TURNOVER_SCOPE_LABELS = {
    "twse_all_securities": "集中市場總計（含 ETF、權證等）",
    "tpex_stocks": "上櫃股票",
}


def _collected_at(row: MarketSummary) -> str | None:
    value = row.collected_at
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _available(row: MarketSummary) -> dict[str, Any]:
    return {
        "exchange": row.exchange,
        "status": "available",
        "index": {
            "name": INDEX_LABELS.get(row.exchange, row.index_name),
            "close": row.index_close,
            "change": row.index_change,
            "change_pct": row.index_change_pct,
            "change_pct_method": row.change_pct_method,
        },
        "turnover": {
            "value": row.turnover,
            "scope": row.turnover_scope,
            "scope_label": TURNOVER_SCOPE_LABELS.get(row.turnover_scope),
        },
        "breadth": {
            "advancers": row.advancers,
            "decliners": row.decliners,
            "unchanged": row.unchanged,
            "limit_up": row.limit_up,
            "limit_down": row.limit_down,
            "unmatched": row.unmatched,
            "not_comparable": row.not_comparable,
            "scope": row.breadth_scope,
        },
        "source": {
            "label": SOURCE_LABELS.get(row.source, row.source),
            "collected_at": _collected_at(row),
            "data_as_of": row.data_as_of,
            "raw_payload_id": row.raw_payload_id,
        },
    }


def market_overview(db: Session, as_of: str | None) -> dict[str, Any]:
    """Both exchanges for ``as_of`` (``dashboard.as_of``), each on its own.

    ``unavailable`` reasons: ``no_verified_session`` (the dashboard has no
    date), ``row_date_mismatch`` (the exchange's newest row is of another
    date, given as ``latest_trading_date``) and ``not_collected`` (no row).
    """

    session = date.fromisoformat(as_of) if as_of else None
    exchanges: list[dict[str, Any]] = []
    for exchange in EXCHANGES:
        if session is None:
            exchanges.append(
                {
                    "exchange": exchange,
                    "status": "unavailable",
                    "reason": "no_verified_session",
                }
            )
            continue
        row = db.scalar(
            select(MarketSummary).where(
                MarketSummary.exchange == exchange,
                MarketSummary.trading_date == session,
            )
        )
        if row is not None:
            exchanges.append(_available(row))
            continue
        latest = db.scalar(
            select(MarketSummary.trading_date)
            .where(MarketSummary.exchange == exchange)
            .order_by(desc(MarketSummary.trading_date))
            .limit(1)
        )
        exchanges.append(
            {
                "exchange": exchange,
                "status": "unavailable",
                "reason": "row_date_mismatch" if latest else "not_collected",
                "latest_trading_date": latest.isoformat() if latest else None,
            }
        )
    return {"trading_date": as_of, "exchanges": exchanges}
