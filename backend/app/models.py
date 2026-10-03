from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Instrument(Base):
    __tablename__ = "instruments"
    # A ticker is only unique within an exchange.  TWSE and TPEx can publish
    # the same symbol, so using the broader market as the key would merge two
    # independent instruments during an official refresh.
    __table_args__ = (UniqueConstraint("exchange", "symbol", name="uq_instrument_exchange_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String(20), default="TW")
    exchange: Mapped[str] = mapped_column(String(20), default="TWSE", server_default="TWSE", index=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(120))
    instrument_type: Mapped[str] = mapped_column(String(20), default="stock", index=True)
    etf_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    listing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_watchlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ThemeGroup(Base):
    __tablename__ = "theme_groups"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    group_type: Mapped[str] = mapped_column(String(30), default="official_industry")
    definition_version: Mapped[str] = mapped_column(String(30), default="v1")
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Product-facing labels are deliberately separate from the source-defined
    # ``name``.  Unknown source codes remain explicit instead of being given a
    # guessed theme name, while the exchange provenance stays on memberships.
    display_name_zh: Mapped[str | None] = mapped_column(String(120), nullable=True)
    display_description_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    name_source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    name_status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "instrument_id", "valid_from", name="uq_group_membership_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("theme_groups.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trading_date", name="uq_market_bar_day"),
        Index("ix_market_bar_instrument_date", "instrument_id", "trading_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    turnover: Mapped[float] = mapped_column(Float, default=0)
    turnover_status: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    turnover_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(120), default="unknown")
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True, index=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class ChipSnapshot(Base):
    __tablename__ = "chip_snapshots"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trading_date", name="uq_chip_snapshot_day"),
        Index("ix_chip_snapshot_instrument_date", "instrument_id", "trading_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    foreign_buy: Mapped[float | None] = mapped_column(Float, nullable=True)
    trust_buy: Mapped[float | None] = mapped_column(Float, nullable=True)
    dealer_buy: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    short_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    borrowed_sell: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_trade_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(120), default="unknown")
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True, index=True)


class TechnicalFeature(Base):
    __tablename__ = "technical_features"
    __table_args__ = (UniqueConstraint("instrument_id", "trading_date", name="uq_technical_feature_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(120), default="derived")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupDailyScore(Base):
    __tablename__ = "group_daily_scores"
    __table_args__ = (UniqueConstraint("group_id", "trading_date", name="uq_group_score_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("theme_groups.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    relative_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_return_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_return_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_return_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    breadth: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    institutional_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    catalyst: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eligible_members: Mapped[int] = mapped_column(Integer, default=0)
    data_quality: Mapped[str] = mapped_column(String(30), default="complete")
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_strategy_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(30))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    canonical_config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    signal_date: Mapped[date] = mapped_column(Date, index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    strategy_version_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="observation", index=True)
    entry_type: Mapped[str] = mapped_column(String(30), default="conditional")
    reference_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    pullback_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    pullback_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    breakout_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    invalid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_cutoff: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_report: Mapped[str | None] = mapped_column(String(500), nullable=True)
    earliest_execution_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    execution_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_quality: Mapped[str] = mapped_column(String(30), default="complete", server_default="complete")
    rule_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SignalEvaluation(Base):
    __tablename__ = "signal_evaluations"
    __table_args__ = (UniqueConstraint("signal_id", "session_date", name="uq_signal_evaluation_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)
    session_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ohlc_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_ratio_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    pullback_price_trigger: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    breakout_price_trigger: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    target_price_trigger: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    invalid_price_trigger: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    institutional_confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)
    leverage_confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)
    subgroup_confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_confirmation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="未觸發")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_time: Mapped[str | None] = mapped_column(String(80), nullable=True)
    execution_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjusted_ohlc_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    corporate_action_applied: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    suspended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comparable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trigger_order: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data_quality: Mapped[str] = mapped_column(String(30), default="complete", server_default="complete")


class SignalSettlement(Base):
    __tablename__ = "signal_settlements"
    __table_args__ = (
        UniqueConstraint("signal_id", "horizon", name="uq_signal_settlement_horizon"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    horizon: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    settlement_date: Mapped[date] = mapped_column(Date, index=True)
    final_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    first_trigger: Mapped[str | None] = mapped_column(String(120), nullable=True)
    return_or_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    incomparable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_time: Mapped[str | None] = mapped_column(String(80), nullable=True)
    execution_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    data_quality: Mapped[str] = mapped_column(String(30), default="complete", server_default="complete")


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), unique=True)
    shares: Mapped[float] = mapped_column(Float, default=0)
    shares_integer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_type: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(120))
    run_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    records: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_key: Mapped[str | None] = mapped_column(String(180), nullable=True, unique=True, index=True)
    data_as_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RawPayload(Base):
    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(String(500))
    payload_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_as_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("instrument_id", "action_date", "action_type", name="uq_corporate_action_day_type"),
        Index("ix_corporate_action_instrument_date", "instrument_id", "action_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    action_date: Mapped[date] = mapped_column(Date, index=True)
    action_type: Mapped[str] = mapped_column(String(40))
    cash_dividend: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock_dividend_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    split_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(120), default="unknown")
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True, index=True)
    data_as_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    __table_args__ = (
        UniqueConstraint("instrument_id", "period_end", "fiscal_period", name="uq_fundamental_period"),
        Index("ix_fundamental_instrument_period", "instrument_id", "period_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    fiscal_period: Mapped[str] = mapped_column(String(30), default="unknown")
    announcement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(120), default="unknown")
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True, index=True)
    data_as_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("instrument_id", "event_date", "event_type", "title", name="uq_event_identity"),
        Index("ix_event_instrument_date", "instrument_id", "event_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), nullable=True, index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(120), default="unknown")
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True, index=True)
    data_as_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NewsItem(Base):
    """Auditable product projection of official events.

    The project intentionally does not ingest unapproved media or fabricate
    article metadata.  ``symbols_json`` and ``theme_ids_json`` are compact
    read-side relations; the originating Event and raw payload remain linked
    for auditability.
    """

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_news_canonical_key"),
        Index("ix_news_collected_id", "collected_at", "id"),
        Index("ix_news_published", "published_at"),
        Index("ix_news_display_id", "display_time", "id"),
        Index("ix_news_category", "category"),
        Index("ix_news_source_kind", "source_kind"),
        Index("ix_news_event", "event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(300), nullable=False)
    dedupe_cluster_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    category: Mapped[str] = mapped_column(String(30), default="taiwan", server_default="taiwan")
    source_kind: Mapped[str] = mapped_column(String(40), default="official_disclosure", server_default="official_disclosure")
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    source_url_kind: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    source_item_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="zh-Hant", server_default="zh-Hant")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # ``event_date`` is deliberately separate from an event timestamp.  A
    # source that only publishes a date must not be presented as if it supplied
    # an exact publication time.
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    time_basis: Mapped[str] = mapped_column(String(20), default="unverified", server_default="unverified")
    time_precision: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    time_consistency: Mapped[str] = mapped_column(String(20), default="verified", server_default="verified", index=True)
    display_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    symbols_json: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    theme_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    impact_scope: Mapped[str] = mapped_column(String(30), default="instrument", server_default="instrument")
    impact_direction: Mapped[str] = mapped_column(String(30), default="unknown", server_default="unknown")
    impact_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_method: Mapped[str] = mapped_column(String(120), default="default_unknown", server_default="default_unknown")
    confidence: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active", index=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("news_items.id"), nullable=True)


class DataQuality(Base):
    __tablename__ = "data_quality"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_key", "as_of_date", name="uq_data_quality_entity_day"),
        Index("ix_data_quality_entity", "entity_type", "entity_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_key: Mapped[str] = mapped_column(String(160), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(30), default="complete")
    missing_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    checks_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
