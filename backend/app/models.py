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
    # official_industry | etf | instrument_theme (legacy ETF theme) |
    # daily_hot_group (new listings) | theme (theme table) |
    # theme_candidate (inactive suggestion awaiting review; never scored).
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
    # pending (name not mapped) | official / verified / approved (displayable,
    # see app.news.is_verified_theme) | pending_verification (theme candidate).
    name_status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "instrument_id", "valid_from", name="uq_group_membership_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("theme_groups.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    # member | candidate (member of a theme_candidate group, unverified).
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


class TechnicalIndicator(Base):
    """One row of scalar daily indicators per instrument, date and formula version.

    Formulas live in app.indicators; a null field has its reason in null_reasons.
    """

    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trading_date", "formula_version", name="uq_technical_indicator_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    formula_version: Mapped[str] = mapped_column(String(40))
    price_basis: Mapped[str] = mapped_column(String(40))
    bar_count: Mapped[int] = mapped_column(Integer)
    ma5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma10: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma60: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma120: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_dif: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi6: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi12: Mapped[float | None] = mapped_column(Float, nullable=True)
    kd_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    kd_d: Mapped[float | None] = mapped_column(Float, nullable=True)
    boll_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    boll_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    boll_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol_ma5: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol_ma20: Mapped[float | None] = mapped_column(Float, nullable=True)
    null_reasons: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(120), default="derived:market_bars")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class GroupDailyScoreArchive(Base):
    """A ``group_daily_scores`` row as it was before a newer hot_group version overwrote it.

    The score table keeps one row per (group, date), so the old version's
    result is copied here verbatim in the same transaction; it is never read
    by the API.  ``hot_group_version`` is the version that wrote the copy.
    """

    __tablename__ = "group_daily_score_archive"
    __table_args__ = (
        UniqueConstraint("group_id", "trading_date", "hot_group_version", name="uq_group_score_archive_day_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_id: Mapped[int] = mapped_column(Integer, index=True)
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
    eligible_members: Mapped[int] = mapped_column(Integer)
    data_quality: Mapped[str] = mapped_column(String(30))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    hot_group_version: Mapped[str] = mapped_column(String(30))
    archive_reason: Mapped[str] = mapped_column(String(80))
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    # A formula sub-version keeps ``version`` unchanged (V1_SPEC), so it is part
    # of the identity: signals written before a formula change keep pointing at
    # their untouched row and snapshot.  ``unclassified/<reason>`` rows are never
    # reused by the worker; the default marks a row nobody classified.
    __table_args__ = (UniqueConstraint("name", "version", "formula_version", name="uq_strategy_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(30))
    formula_version: Mapped[str] = mapped_column(String(80), server_default="unclassified/unspecified")
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
    """Auditable product news: official-event projections and feed items.

    Official events are projected by app.news; registered media and overseas
    official feeds are written by worker.news_batch (title, summary, time and
    item link only, never article bodies).  ``symbols_json`` and
    ``theme_ids_json`` are compact read-side relations; the originating Event
    or raw payload remains linked for auditability.
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


class ScheduleRun(Base):
    """One invocation of a scheduled job such as ``worker.cli daily``.

    Every invocation writes a row, including reruns that find the target date
    already complete; data idempotency is owned by the steps themselves.
    """

    __tablename__ = "schedule_runs"
    __table_args__ = (Index("ix_schedule_run_job_date", "job", "target_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(40), default="daily")
    target_date: Mapped[date] = mapped_column(Date, index=True)
    trigger: Mapped[str] = mapped_column(String(30), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    records: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # The process that owns a running row, so a later trigger on the same
    # host can tell a live run from one whose process was killed.
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ScheduleRunStep(Base):
    __tablename__ = "schedule_run_steps"
    __table_args__ = (UniqueConstraint("schedule_run_id", "step", name="uq_schedule_run_step"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_run_id: Mapped[int] = mapped_column(ForeignKey("schedule_runs.id"), index=True)
    step: Mapped[str] = mapped_column(String(40))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="running")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    records: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class NewsLlmResult(Base):
    """LLM inference for one news item under one prompt version (worker.news_llm).

    Kept apart from NewsItem so rule relations (``symbols_json``) and the
    source summary are never overwritten; a new prompt version adds rows and
    older rows stay.  ``llm_status`` is ``done`` or ``pending`` (retried later).
    """

    __tablename__ = "news_llm_results"
    __table_args__ = (
        UniqueConstraint("news_item_id", "prompt_version", name="uq_news_llm_item_prompt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_item_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), index=True)
    prompt_version: Mapped[str] = mapped_column(String(40))
    llm_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    llm_input_hash: Mapped[str] = mapped_column(String(64))
    llm_run_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    llm_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    llm_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_symbol_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ai_theme_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ai_impact_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_impact_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_impact_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_unsupported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=True)
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True)


class CandidateRun(Base):
    """One computed daily candidate list per trading date and score version.

    A day with zero candidates still has a row so the reason is queryable.
    Rows are written once; a rerun of the same date and version reuses them.
    """

    __tablename__ = "candidate_runs"
    __table_args__ = (UniqueConstraint("trading_date", "score_version", name="uq_candidate_run_day_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    score_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="success")
    evaluated_signals: Mapped[int] = mapped_column(Integer, default=0)
    pool_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    zero_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    exclusions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DailyCandidate(Base):
    """A ranked candidate of one candidate run (V1_SPEC candidate_score_v1)."""

    __tablename__ = "daily_candidates"
    __table_args__ = (
        UniqueConstraint("trading_date", "instrument_id", "score_version", name="uq_daily_candidate_day_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_run_id: Mapped[int] = mapped_column(ForeignKey("candidate_runs.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"))
    strategy: Mapped[str] = mapped_column(String(60))
    score_version: Mapped[str] = mapped_column(String(40))
    total_score: Mapped[float] = mapped_column(Float)
    weight_coverage: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    components_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasons_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    groups_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    data_as_of: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CandidateLlmNote(Base):
    """LLM explanation of one daily candidate under one prompt version (worker.candidate_notes).

    Inference kept apart from the rule-based row: it never changes the score,
    rank or selection.  ``llm_status`` is ``done`` or ``pending`` (retried by
    a later run); a done row is never rewritten for the same prompt version.
    """

    __tablename__ = "candidate_llm_notes"
    __table_args__ = (
        UniqueConstraint("daily_candidate_id", "prompt_version", name="uq_candidate_llm_note_prompt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_candidate_id: Mapped[int] = mapped_column(ForeignKey("daily_candidates.id"), index=True)
    candidate_run_id: Mapped[int] = mapped_column(ForeignKey("candidate_runs.id"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    prompt_version: Mapped[str] = mapped_column(String(40))
    llm_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    llm_input_hash: Mapped[str] = mapped_column(String(64))
    llm_run_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    llm_status: Mapped[str] = mapped_column(String(20), default="pending")
    llm_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_selection: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_levels: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_risks: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=True)
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"), nullable=True)


class ThemeSuggestion(Base):
    """A news theme suggestion awaiting human review (worker.theme_suggestions).

    Aggregated from the ``theme_candidates`` of done news_llm_results, one row
    per prompt version and normalized theme name.  Never scored or ranked and
    never written to theme_groups; ``status`` stays ``pending_verification``.
    ``matched_group_id`` names an existing theme or official industry with the
    same normalized name (then it is not a new theme).
    """

    __tablename__ = "theme_suggestions"
    __table_args__ = (
        UniqueConstraint("prompt_version", "theme_key", name="uq_theme_suggestion_prompt_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_key: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    aggregation_version: Mapped[str] = mapped_column(String(40))
    llm_models_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    news_count: Mapped[int] = mapped_column(Integer)
    first_news_date: Mapped[date] = mapped_column(Date)
    last_news_date: Mapped[date] = mapped_column(Date, index=True)
    matched_group_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_verification")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ThemeSuggestionNews(Base):
    """One news item behind a theme suggestion, with the LLM's own wording."""

    __tablename__ = "theme_suggestion_news"
    __table_args__ = (
        UniqueConstraint("suggestion_id", "news_item_id", name="uq_theme_suggestion_news_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("theme_suggestions.id"), index=True)
    news_item_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), index=True)
    news_llm_result_id: Mapped[int] = mapped_column(ForeignKey("news_llm_results.id"))
    theme_text: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    news_date: Mapped[date] = mapped_column(Date)
