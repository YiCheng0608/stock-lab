export type Pagination = {
  page: number
  page_size: number
  total: number
  total_pages: number
  has_previous: boolean
  has_next: boolean
}

export type Paginated<T> = {
  items: T[]
  pagination: Pagination
}

export type Instrument = {
  id: number
  market: string
  exchange: string
  symbol: string
  name: string
  industry?: string | null
  instrument_type: string
  etf_category?: string | null
  listing_date?: string | null
  is_watchlisted: boolean
  status: string
}

export type GroupMetrics = Record<string, number | null>

export type PublicCandidateInstrument = {
  // Decimal string: SQLite IDs may exceed JavaScript's safe integer range.
  instrument_id: string
  exchange: string
  symbol: string
}

export type PublicCandidateIdentity = {
  public_candidate_identity_version?: 'instrument-id-string-v1'
  candidate_instruments?: PublicCandidateInstrument[]
}

export type GroupRow = PublicCandidateIdentity & {
  group_id: string
  name: string
  group_type: string
  score: number | null
  rank: number | null
  trading_date: string | null
  data_quality: string
  eligible_members: number
  metrics: GroupMetrics
  candidates: string[]
  benchmark: string | null
  benchmark_returns: Record<string, number | null>
  leaderboard: string | null
  methodology: Record<string, unknown>
}

export type SignalConfidenceSemantics = {
  version: string
  kind: string
  is_calibrated: boolean
  is_probability: boolean
  display_label_zh: string
}

export type LevelFieldSemantics = {
  role: string
  label_zh: string
  source_field: string
  reason?: string
}

export type LevelSemantics = {
  version: string
  kind: 'rule_reference' | 'unknown' | string
  reason: string
  strategy: { name: string | null; version: string | null }
  formula: {
    version: string | null
    source: string | null
    reason: string | null
    expression?: string
    rounding?: string
  }
  fields: Record<string, LevelFieldSemantics>
  price_basis: { value: string | null; reason: string }
  cost_included: { value: boolean | null; reason: string }
  decision_at: { value: string | null; reason: string }
  generated_at: { value: string | null; reason: string }
  response_generated_at?: string
}

export type ProductTimeRole = {
  role: string
  status: 'known' | 'unknown' | string
  precision: 'date' | 'instant' | 'none' | string
  value: string | null
  utc?: string | null
  date?: string | null
  source?: string | null
  evidence?: unknown
  ref?: string | null
  reason?: string | null
  timezone_policy?: string
}

export type ProductTime = {
  version: string
  scope: string
  availability_truth: 'not_asserted' | string
  timezone_policy: {
    display_timezone: string
    known_instant: string
    date_only: string
    naive_or_missing: string
  }
  roles: Record<string, ProductTimeRole>
  response_generated_at: string
  legacy: Record<string, unknown>
  limitations: string[]
}

export type StopPriceSemantics = {
  kind: 'user_position_risk_input' | 'rule_reference' | 'unknown' | string
  label: string
  origin: string | null
  source_field: string | null
  is_rule_reference: boolean
  reason: string | null
}

export type Signal = {
  id: number
  signal_key: string
  signal_date: string
  instrument: Instrument | null
  status: string
  entry_type: string
  reference_entry: number | null
  pullback_low: number | null
  pullback_high: number | null
  breakout_price: number | null
  invalid_price: number | null
  target_1: number | null
  target_2: number | null
  confidence: number | null
  confidence_semantics?: SignalConfidenceSemantics
  level_semantics?: LevelSemantics
  product_time?: ProductTime
  response_generated_at?: string
  rationale: string | null
  data_cutoff: string | null
  source_report: string | null
  earliest_execution_date: string | null
  execution_date: string | null
  execution_price: number | null
  data_quality: string
  rule_evidence: Record<string, unknown>
  strategy: {
    name: string
    version: string
    kind: string
    canonical_config_snapshot: Record<string, unknown>
  } | null
}

export type Dashboard = {
  as_of: string | null
  mode: string
  scan_scope: string
  market: {
    instruments: number
    bars: number
    groups: number
    source: string
    source_label?: string
  }
  scan_scope_label?: string
  data_quality: {
    latest_run: string
    latest_run_source: string | null
    latest_run_date: string | null
    latest_run_records: number
    data_as_of: string | null
    error: string | null
    updated_at: string | null
  }
  groups: GroupRow[]
  signals: Signal[]
  signal_status_counts: Record<string, number>
  news?: NewsItem[]
  themes?: ThemeDirectoryRow[]
  candidates?: ActionSummary[]
  actions?: ActionSummary[]
  action_counts?: { total: number; actionable: number; data_insufficient: number; held: number }
  empty_states?: Record<string, string | null>
}

export type Bar = {
  date: string
  open: number
  high: number
  low: number
  close: number
  adj_close: number
  volume: number
  turnover: number
  source: string
  data_as_of: string | null
  collected_at: string | null
  is_suspended: boolean
}

export type ChipSnapshot = {
  date: string
  foreign_buy: number | null
  trust_buy: number | null
  dealer_buy: number | null
  margin_balance: number | null
  margin_change: number | null
  short_balance: number | null
  borrowed_sell: number | null
  day_trade_ratio: number | null
  source: string
  data_as_of: string | null
  collected_at: string | null
}

export type CorporateAction = {
  date: string
  type: string
  cash_dividend: number | null
  stock_dividend_ratio: number | null
  split_ratio: number | null
  reference_price: number | null
  source: string
  data_as_of: string | null
}

export type FundamentalSnapshot = {
  period_end: string
  fiscal_period: string
  announcement_date: string | null
  revenue: number | null
  eps: number | null
  roe: number | null
  source: string
  data_as_of: string | null
}

export type EventRow = {
  date: string
  type: string
  title: string
  description: string | null
  source: string
  data_as_of: string | null
}

export type EventListRow = EventRow & {
  id: number
  instrument: Instrument | null
  endpoint: string | null
  raw_payload_id: number | null
  collected_at: string | null
}

export type DataQualityRow = {
  entity_type: string
  entity_key: string
  as_of_date: string
  status: string
  missing_fields: string[]
  checks: Record<string, unknown>
  source: string | null
  checked_at: string | null
}

export type RawPayload = {
  id: number
  ingestion_run_id: number | null
  source: string
  endpoint: string
  sha256: string | null
  data_as_of: string | null
  collected_at: string | null
}

export type InstrumentDetail = {
  instrument: Instrument
  bars: Bar[]
  features: Record<string, number | string | null>
  groups: Array<{ id: string; name: string; valid_from: string; valid_to: string | null }>
  chips: ChipSnapshot[]
  corporate_actions: CorporateAction[]
  fundamentals: FundamentalSnapshot[]
  events: EventRow[]
  data_quality: DataQualityRow[]
  coverage?: InstrumentCoverage | null
  quality_summary?: {
    market: { status: string; label: string; as_of: string | null; missing_fields: string[]; source: string | null }
    research: { status: string; label: string; as_of: string | null; missing_fields: string[]; action_state: string | null }
    instrument: string
  }
  product_time?: ProductTime
  response_generated_at?: string
  strategy_conditions: Record<string, { label?: string; requires: string[]; source: string; technical?: Record<string, string> }>
  signals: Signal[]
}

export type InstrumentCoverage = {
  coverage_status?: 'unknown' | 'verified' | string
  exchange: string
  symbol: string
  instrument_type: string
  etf_category: string | null
  listing_date: string | null
  verified_taiex_sessions: number | null
  bars_total: number
  chips_total: number
  effective_bar_sessions: number | null
  effective_chip_sessions: number | null
  eligible_sessions: number | null
  latest_bar: string | null
  latest_chip: string | null
  missing_bars_to_20: number | null
  missing_bars_to_60: number | null
  missing_chips_to_20: number | null
  missing_chips_to_60: number | null
  missing_bar_dates_to_20: string[]
  missing_bar_dates_to_60: string[]
  missing_chip_dates_to_20: string[]
  missing_chip_dates_to_60: string[]
  coverage_reasons: string[]
  ipo_stage: string | null
  windows: Record<string, Record<string, unknown>>
}

export type GroupMember = Instrument & {
  role: string
  confidence: number
  valid_from: string
  valid_to: string | null
  latest_bar: Bar | null
  features: Record<string, number | string | null>
}

export type GroupDetail = {
  group: GroupRow
  members: GroupMember[]
  methodology: Record<string, unknown>
}

export type SignalEvaluation = {
  id: number
  session_date: string
  session_no: number | null
  ohlc: Record<string, number> | null
  adjusted_ohlc: Record<string, number> | null
  volume: number | null
  volume_ratio_20d: number | null
  pullback_price_trigger: boolean | null
  breakout_price_trigger: boolean | null
  target_price_trigger: boolean | null
  invalid_price_trigger: boolean | null
  institutional_confirmation: string | null
  leverage_confirmation: string | null
  subgroup_confirmation: string | null
  full_confirmation: boolean | null
  status: string
  reason: string | null
  source: string | null
  data_time: string | null
  execution_date: string | null
  execution_price: number | null
  corporate_action_applied: boolean | null
  suspended: boolean | null
  comparable: boolean | null
  trigger_order: string | null
  data_quality: string
}

export type SignalSettlement = {
  id: number
  horizon: number
  settlement_date: string
  final_status: string | null
  first_trigger: string | null
  return_or_risk: number | null
  incomparable_reason: string | null
  source: string | null
  data_time: string | null
  execution_date: string | null
  execution_price: number | null
  comparable: boolean | null
  data_quality: string
  signal_key?: string | null
}

export type TrackingRow = {
  signal: Signal
  instrument: Instrument | null
  evaluation: SignalEvaluation
}

export type TrackingResponse = {
  rows: TrackingRow[]
  settlements: SignalSettlement[]
  summary: { evaluation_rows: number; settlement_rows: number; horizons: number[] }
  response_generated_at?: string
}

export type Position = {
  id: number
  instrument: Instrument | null
  shares: number
  quantity?: {
    total_shares: number
    quantity_lots: number
    odd_lot_shares: number
    unit: 'lot' | 'odd_lot' | 'mixed'
    display: string
  }
  average_cost: number | null
  stop_price: number | null
  risk_budget: number | null
  note: string | null
  updated_at: string | null
  latest_bar: Bar | null
  market_value: number | null
  unrealized_pnl: number | null
}

export type PositionInput = {
  symbol: string
  exchange?: string
  shares?: number
  unit?: 'lot' | 'odd_lot'
  quantity?: number
  quantity_lots?: number
  odd_lot_shares?: number
  average_cost?: number
  stop_price?: number
  risk_budget?: number
  note?: string
}

export type IngestionRun = {
  id: number
  run_type: string
  source: string
  run_date: string
  status: string
  records: number
  error: string | null
  request_key: string | null
  data_as_of: string | null
  metadata?: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  updated_at: string | null
}

export type BackfillRun = IngestionRun & {
  metadata: Record<string, unknown>
}

export type CoverageReport = {
  scope?: string
  start_date: string
  end_date: string
  session_basis: string
  baseline?: {
    status: 'unknown' | 'snapshot' | 'manifest' | string
    kind: string
    source: string
    message: string
    has_backfill_manifest: boolean
  }
  session_count: number
  sessions: string[]
  requested_calendar_dates: string[]
  expected_dates: string[]
  date_coverage: Array<Record<string, unknown>>
  instrument_coverage: InstrumentCoverage[]
  event_coverage: {
    status: string
    denominator: string
    target_sessions: number
    verified_sessions: number
    verified_empty_sessions: number
    partial_sessions: number
    unsupported_sessions: number
    unqueried_sessions: number
    observed_event_dates: number
    observed_event_rows: number
    reason?: string
  }
  summary: {
    session_basis: string
    coverage_status?: 'unknown' | 'snapshot' | 'manifest' | string
    baseline_kind?: string
    baseline_source?: string
    baseline_message?: string
    has_backfill_manifest?: boolean
    session_count: number
    date_count: number
    instrument_count: number
    bar_rows: number
    chip_rows: number
    incomplete_to_20: number
    incomplete_to_60: number
    incomplete_chips_to_20: number
    incomplete_chips_to_60: number
    coverage_reason_counts: Record<string, number>
    requested_calendar_sessions: number
    verified_trading_sessions: number
    verified_ohlcv_sessions: number
    verified_taiex_sessions: number
    verified_chip_sessions: number
    verified_event_sessions: number
    target_ohlcv_taiex_sessions: number
    target_chip_event_sessions: number
    target_met: boolean | null
    latest_observed: string | null
    data_cutoff: string | null
  }
}

export type BacktestGroup = {
  strategy: string
  version: string
  instrument_type: string
  horizon: number
  sample: number
  comparable: number
  incomparable: number
  assessment: string
  interpretation: string
}

export type BacktestSummary = {
  run: {
    id: number
    status: string
    run_type: string
    request_key: string | null
    run_date: string | null
    data_as_of: string | null
    metadata: Record<string, unknown>
    assessment: string
    zero_actionable_count: number
  } | null
  groups: BacktestGroup[]
  assessment: string
  zero_actionable_count: number
  idempotent_reuse?: boolean
}

export type StrategyRow = {
  name: string
  version: string
  kind: string
  active: boolean
  config: Record<string, unknown>
  canonical_config_snapshot: Record<string, unknown>
  created_at: string | null
}

export type CursorMeta = {
  limit: number
  next_cursor: string | null
  has_more: boolean
  sort: string
  data_as_of: string | null
  total?: number
}

export type CursorPage<T> = {
  items: T[]
  meta: CursorMeta
}

export type NewsItem = {
  id: string
  canonical_key: string
  dedupe_cluster_id: string | null
  category: string
  source_kind: string
  source_name: string
  source: { name: string; url: string | null; url_kind: string }
  source_item_id: string | null
  title: string
  summary: string | null
  description?: string | null
  summary_preview?: string | null
  language: string
  published_at: string | null
  event_at: string | null
  event_date?: string | null
  display_time?: string | null
  time_basis?: 'published' | 'event' | 'event_date' | 'collected' | 'unverified' | string
  time_precision?: 'datetime' | 'date' | 'none' | string
  time_consistency?: 'verified' | 'conflict' | 'unverified' | string
  product_time?: ProductTime
  response_generated_at?: string
  collected_at: string | null
  symbols: string[]
  instruments?: Array<{ exchange: string; symbol: string; name: string }>
  themes: Array<{ theme_id: string; display_name: string }>
  theme_ids: string[]
  impact: {
    scope: string
    direction: string
    rationale: string | null
    method: string
    confidence: string
  }
  impact_scope: string
  impact_direction: string
  confidence: string
  status: string
  content_hash: string | null
  provenance: {
    event_id: number | null
    raw_payload_id: number | null
    endpoint: string | null
    data_as_of: string | null
  }
  detail_url?: string
}

export type ThemeDirectoryRow = PublicCandidateIdentity & {
  theme_id: string
  display_name: string
  description: string
  category: string
  name_status: string
  qualified: boolean
  score: number | null
  rank: number | null
  trading_date: string | null
  data_quality: string
  eligible_members: number
  minimum_members: number
  metrics: Record<string, number | null>
  why_hot: string[]
  missing_reasons: string[]
  candidate_symbols: string[]
  benchmark: string | null
  benchmark_returns: Record<string, number | null>
  leaderboard: string | null
  methodology: Record<string, unknown>
}

export type ThemeDetail = {
  theme: ThemeDirectoryRow
  methodology?: Record<string, unknown>
  data_as_of?: string | null
  members?: StockDirectoryRow[]
  meta?: Record<string, unknown>
}

export type StockDirectoryRow = {
  instrument?: Instrument
  id?: number
  market?: string
  exchange: string
  symbol: string
  name: string
  industry?: string | null
  instrument_type: string
  etf_category?: string | null
  listing_date?: string | null
  is_watchlisted: boolean
  status: string
  role?: string
  confidence?: number
  valid_from?: string
  valid_to?: string | null
  latest_bar?: Bar | null
  latest_price?: number | null
  price_as_of?: string | null
  action_state?: string
  action_label_zh?: string
  data_quality?: string
  missing_data_priority?: MissingDataPriority[]
  product_time?: ProductTime
  response_generated_at?: string
}

export type MissingDataPriority = {
  field: string
  priority: string
  priority_label: string
  reason: string
}

export type StrategyDecision = {
  strategy: string
  signal_id: number
  signal_key: string
  signal_date: string
  status: string
  data_quality: string
  rationale: string | null
  levels: {
    trigger_price: number | null
    entry_low: number | null
    entry_high: number | null
    invalid_price: number | null
    target_1: number | null
    target_2: number | null
  }
  risk_reward: number | null
  confidence_semantics?: SignalConfidenceSemantics
  level_semantics?: LevelSemantics
  product_time?: ProductTime
  response_generated_at?: string
  earliest_execution_date: string | null
  missing: string[]
  evidence: Record<string, unknown>
}

export type ActionSummary = {
  instrument: {
    id: number
    exchange: string
    symbol: string
    name: string
    instrument_type: string
    etf_category: string | null
  }
  as_of: string | null
  generated_at: string
  product_time?: ProductTime
  response_generated_at?: string
  level_semantics?: LevelSemantics
  stop_price_semantics?: StopPriceSemantics
  action_state: string
  action_label_zh: string
  display_action?: string
  action_instruction?: string
  display_instruction?: string
  display_reasons?: string[]
  primary_reason?: { label: string; scope: string }
  primary_levels?: Record<string, unknown>
  data_status?: { source: string; market: string; strategy: string }
  context_badges?: string[]
  detail_url?: string
  data_gap?: string | null
  priority: number
  held: boolean
  watchlisted: boolean
  current_price: number | null
  price_as_of: string | null
  previous_close?: number | null
  price_change?: number | null
  price_change_pct?: number | null
  trigger_kind: string | null
  trigger_price: number | null
  entry_low: number | null
  entry_high: number | null
  invalid_price: number | null
  stop_price: number | null
  target_1: number | null
  target_2: number | null
  risk_reward: number | null
  earliest_execution_date: string | null
  primary_strategy: string | null
  alternative_strategies: string[]
  strategies: StrategyDecision[]
  reasons: string[]
  conflicts: string[]
  evidence_refs: string[]
  data_quality: string
  blocking_reasons: string[]
  missing_data_priority: MissingDataPriority[]
  theme_ids: string[]
  event_ids: number[]
  data_cutoff: string | null
}

export type GlossaryTerm = {
  term_id: string
  name: string
  aliases: string[]
  category: string
  plain_definition: string
  use: string
  how_to_read: string
  limitations: string
  related: string[]
  version: string
}
