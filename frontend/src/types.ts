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

// dashboard.market_overview (#275): each exchange for dashboard.as_of only, never another day's row.
export type MarketOverviewExchange = {
  exchange: 'TWSE' | 'TPEx' | string
  status: 'available' | 'unavailable' | string
  reason?: string
  latest_trading_date?: string | null
  index?: { name: string; close: number | null; change: number | null; change_pct: number | null; change_pct_method: 'official' | 'derived' | string | null }
  turnover?: { value: number | null; scope: 'twse_all_securities' | 'tpex_stocks' | string | null; scope_label: string | null }
  breadth?: {
    advancers: number | null
    decliners: number | null
    unchanged: number | null
    limit_up: number | null
    limit_down: number | null
    unmatched: number | null
    not_comparable?: number | null
    scope: string | null
  }
  source?: { label: string | null; collected_at: string | null; data_as_of?: string | null; raw_payload_id?: number | null }
}

export type MarketOverview = {
  trading_date: string | null
  exchanges: MarketOverviewExchange[]
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
  candidates?: ActionSummary[]
  actions?: ActionSummary[]
  action_counts?: { total: number; actionable: number; data_insufficient: number; held: number; held_unknown?: number; scope?: string }
  empty_states?: Record<string, string | null>
  market_overview?: MarketOverview
}

export type Bar = {
  date: string
  open: number
  high: number
  low: number
  close: number
  adj_close: number
  volume: number
  /** Canonical nonnegative int64 shares; absent only on older API responses. */
  volume_exact?: string | null
  turnover: number
  turnover_status: 'available' | 'unavailable' | 'unknown'
  turnover_reason: string | null
  source: string
  data_as_of: string | null
  collected_at: string | null
  is_suspended: boolean
}

/** Stored bar columns are nullable; a null core value never becomes a chart point. */
export type StockDetailBar = Omit<Bar, 'date' | 'open' | 'high' | 'low' | 'close' | 'adj_close' | 'volume' | 'turnover' | 'turnover_status' | 'source' | 'is_suspended'> & {
  id?: number
  date: string | null
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  adj_close: number | null
  volume: number | null
  turnover: number | null
  turnover_status: Bar['turnover_status'] | null
  source: string | null
  is_suspended: boolean | null
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

export type StockDetailChip = Omit<ChipSnapshot, 'date' | 'source'> & {
  date: string | null
  source: string | null
  id?: number | null
}

export type StockFeatureSnapshot = {
  trading_date: string | null
  source: string | null
  created_at: string | null
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
  bars: StockDetailBar[]
  features: Record<string, unknown>
  feature_snapshot?: StockFeatureSnapshot | null
  groups: Array<{ id: string; name: string | null; display_name: string | null; verified: boolean; valid_from: string; valid_to: string | null }>
  chips: StockDetailChip[]
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
  news_cutoff?: { as_of: string | null; filter: string; limit: number }
  strategy_conditions: Record<string, { label?: string; requires: string[]; source: string; technical?: Record<string, string> }>
  signals: Signal[]
  // The stock's row in the latest candidate run on or before the cutoff; null when it is not a candidate.
  candidate?: CandidateItem | null
  // One row per registered strategy on the latest signal date (#274).
  strategy_board?: StrategyBoard | null
}

export type StrategyBoardStatus = 'conditional' | 'observation' | 'data_incomplete' | 'not_applicable'

export type StrategyCondition = {
  code: string
  kind: string
  satisfied: boolean | null
  actual: number | null
  threshold: number | null
  threshold_high: number | null
  operator: string | null
  reasons: string[]
  next_session: Record<string, number | string | null> | null
}

// Levels never mix: actionable reads the signal, observation reads strategy_levels.
export type StrategyActionableLevels = {
  kind: 'actionable'
  entry_type: string
  trigger_price: number | null
  reference_entry: number | null
  entry_low: number | null
  entry_high: number | null
  invalid_price: number | null
  target_1: number | null
  target_2: number | null
  risk_reward: number | null
}

export type StrategyObservationLevels = {
  kind: 'observation'
  display_label: string
  availability: 'levels' | 'trend_unreachable' | 'data_incomplete' | 'not_applicable' | 'suspended' | string
  next_session_date: string | null
  trigger_price: number | null
  zone_low: number | null
  zone_high: number | null
  min_volume: number | null
  max_volume: number | null
  reference_entry: number | null
  entry_low: number | null
  entry_high: number | null
  invalid_price: number | null
  target_1: number | null
  target_2: number | null
  risk_reward: number | null
  reachable_next_session: boolean | null
  price_basis: string
  missing_inputs: string[]
  missing_labels: string[]
}

export type StrategyBoardRow = {
  strategy: string
  label: string
  version: string
  entry_type: string
  status: StrategyBoardStatus
  signal_id: number | null
  signal_date: string | null
  earliest_execution_date: string | null
  levels: StrategyActionableLevels | StrategyObservationLevels | null
  levels_missing: boolean
  unmet: string[]
  missing: string[]
  missing_labels: string[]
  conditions: StrategyCondition[]
}

export type StrategyBoard = {
  as_of: string | null
  levels_version: string
  candidate: { rank: number; total_score: number; score_version: string; strategy: string; llm_note?: CandidateLlmNote | null } | null
  strategies: StrategyBoardRow[]
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

/** Local stored inputs for portfolio inspection, not a certified full Bar. */
export type ProjectedPortfolioBar = {
  date: string | null
  close: number | null
  source: string | null
  data_as_of: string | null
  collected_at: string | null
}
export type PortfolioQuote = {
  close: number | null
  close_status: 'known' | 'missing' | 'invalid'
  recorded: Omit<ProjectedPortfolioBar, 'close'>
  record_status: Record<'date' | 'source' | 'data_as_of' | 'collected_at', 'known' | 'missing' | 'invalid'>
  source_verification: 'unverified'
  date_verification: 'unverified'
}

export type Position = {
  id: number
  instrument: Instrument | null
  shares: number | null
  shares_exact?: string | null
  position_quantity_status?: 'known' | 'unknown' | 'absent'
  quantity?: {
    total_shares: number
    total_shares_exact?: string
    quantity_lots: number
    quantity_lots_exact?: string
    odd_lot_shares: number
    unit: 'lot' | 'odd_lot' | 'mixed'
    display: string
  } | null
  average_cost: number | null
  stop_price: number | null
  risk_budget: number | null
  portfolio_value_status?: {
    average_cost: 'known' | 'missing' | 'invalid'
    stop_price: 'known' | 'missing' | 'invalid'
    risk_budget: 'known' | 'missing' | 'invalid'
  }
  note: string | null
  updated_at: string | null
  latest_bar: ProjectedPortfolioBar | null
  portfolio_quote?: PortfolioQuote
  market_value: number | null
  unrealized_pnl: number | null
  valuation_status?: {
    market_value: 'known' | 'local_estimate' | 'missing' | 'invalid' | 'quantity_unknown' | 'precision_unsupported'
    unrealized_pnl: 'known' | 'local_estimate' | 'missing' | 'invalid' | 'quantity_unknown' | 'precision_unsupported'
  }
}

export type PositionInput = {
  symbol: string
  exchange?: string
  shares?: number | string
  unit?: 'lot' | 'odd_lot'
  quantity?: number | string
  quantity_lots?: number | string
  odd_lot_shares?: number | string
  average_cost?: number | null
  stop_price?: number | null
  risk_budget?: number | null
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
  id: number
  name: string
  version: string
  formula_version: string
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
  // Latest done LLM result (worker.news_llm, NEWS_SPEC §5); null until one exists. Absent on older servers.
  ai?: NewsAi | null
}

// LLM inference kept apart from source facts: candidates are never verified relations.
export type NewsAi = {
  inference: true
  status: 'done' | string
  summary: string | null
  symbol_candidates: Array<{
    exchange: string
    symbol: string
    name: string | null
    reason: string | null
    confidence: 'high' | 'medium' | 'low' | string | null
    verified: false
  }>
  theme_candidates: Array<{ theme: string; reason: string | null }>
  impact_direction: 'positive' | 'negative' | 'mixed' | 'unknown' | string | null
  impact_scope: 'instrument' | 'theme' | 'market' | string | null
  impact_rationale: string | null
  unsupported: boolean | null
  model: string | null
  prompt_version: string | null
  input_hash: string | null
  generated_at: string | null
}

// Group boards (docs/V1_SPEC.md hot_group_v1): GET /api/themes?board=industry|theme&limit=N.
export type ThemeBoard = 'industry' | 'theme'
export type ThemeBoardComponent = 'relative_return' | 'breadth' | 'volume_strength' | 'institutional_flow' | 'catalyst'

export type ThemeBoardItem = {
  theme_id: string
  display_name: string
  description: string
  board: string | null
  rank: number
  score: number
  quality: 'complete' | 'partial' | string
  // Same-board percentile 0–1; null when the component has no data.
  components: Record<ThemeBoardComponent, number | null>
  relative_returns: { '1d': number | null; '5d': number | null; '20d': number | null }
  eligible_members: number | null
  member_count: number | null
  trading_date: string | null
}

export type ThemeBoardEmptyReason = 'no_official_run' | 'no_board_scores' | 'no_scores_for_date' | 'no_ranked_groups'

export type ThemeBoardMeta = {
  board: ThemeBoard
  requested_date: string | null
  trading_date: string | null
  data_as_of: string | null
  limit: number
  total: number
  sort: string
  empty_reason: ThemeBoardEmptyReason | null
  empty_message: string | null
}

export type ThemeBoardResponse = { items: ThemeBoardItem[]; meta: ThemeBoardMeta }

// News theme suggestions awaiting review (/api/theme-suggestions, #216): LLM inference, never scored or ranked.
export type ThemeSuggestionNews = {
  news_id: number
  title: string
  source_name: string
  news_date: string
  theme_text: string
  reason: string | null
}

export type ThemeSuggestion = {
  id: number
  theme_key: string
  display_name: string
  status: string
  inference: true
  news_count: number
  first_news_date: string
  last_news_date: string
  // news_v1 theme candidates carry no confidence.
  confidence: 'not_provided' | string
  matched_group: { group_id: string; name: string; group_type: string } | null
  prompt_version: string
  aggregation_version: string
  llm_models: string[]
  computed_at: string | null
  news: ThemeSuggestionNews[]
}

export type ThemeSuggestionsResponse = {
  items: ThemeSuggestion[]
  meta: {
    total: number
    limit: number
    include_matched: boolean
    matched_total: number
    news_per_suggestion: number
    aggregation_version: string
    updated_at: string | null
    sort: string
  }
}

// Membership source of a theme-table member (docs/INDUSTRY_CLASSIFICATION.md §7); null for other groups.
export type ThemeEvidence = {
  kind?: string | null
  url: string | null
  relation: 'core_business' | 'product_line' | 'supply_chain' | string | null
  relevance: 'high' | 'medium' | 'low' | string | null
  theme_version: string | null
}

// GET /api/themes/{id} `theme`: the group with its latest score (rank is null unless the group is fully qualified).
export type ThemeSummary = {
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
  metrics: Record<string, number | null>
  definition_version?: string | null
}

export type ThemeTrendPoint = {
  trading_date: string
  score: number | null
  rank: number | null
  quality: string | null
  eligible_members: number | null
}

export type ThemeInlineMember = {
  exchange: string
  symbol: string
  name: string
  instrument_type: string
  role: string
  valid_from: string | null
  valid_to: string | null
  theme_evidence: ThemeEvidence | null
}

export type ThemeDetail = {
  theme: ThemeSummary
  board: string | null
  methodology?: Record<string, unknown>
  data_as_of: string | null
  trend: ThemeTrendPoint[]
  members_total: number
  members_truncated: boolean
  members_endpoint: string
  members_as_of: string | null
  // At most one page; the full list is members_endpoint.
  members: ThemeInlineMember[]
}

// GET /themes/{id}/members sorts (#280); the API also keeps price and name.
export type ThemeMemberSort = 'turnover' | 'change_pct' | 'return_5d' | 'return_20d' | 'symbol'

export type ThemeMemberRow = StockDirectoryRow & {
  theme_evidence?: ThemeEvidence | null
  // Change against the previous session, same rule as the candidate market (#280, UI_COPY_SPEC §8.5).
  change?: number | null
  change_pct?: number | null
  change_status?: 'known' | 'unverified' | 'missing' | string
  // Only on members_as_of; missing when the member has no bar that day.
  turnover?: number | null
  turnover_status?: 'available' | 'unavailable' | 'unknown' | 'missing' | string
  excess_return_5d?: number | null
  excess_return_20d?: number | null
  candidate_rank?: number | null
  conditional?: boolean
}

export type ThemeMembersResponse = {
  theme: ThemeSummary
  members_as_of?: string | null
  items: ThemeMemberRow[]
  meta: Record<string, unknown>
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
  signal_key: string | null
  signal_date: string | null
  status: string | null
  data_quality: string | null
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
  wait_missing?: string[]
  evidence: Record<string, unknown> | null
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
  held: boolean | null
  position_quantity_status?: 'known' | 'unknown' | 'absent'
  watchlisted: boolean
  current_price: number | null
  market_read?: { status: 'known' | 'missing' | 'invalid'; invalid_fields: string[] }
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

// GET /api/stocks/{exchange}/{symbol}/bars (docs/V1_SPEC.md 技術指標, indicators/v1).
export type StockBarsInterval = 'day' | 'week'

export type IndicatorField =
  | 'ma5' | 'ma10' | 'ma20' | 'ma60' | 'ma120'
  | 'macd_dif' | 'macd_signal' | 'macd_hist'
  | 'rsi6' | 'rsi12'
  | 'kd_k' | 'kd_d'
  | 'boll_mid' | 'boll_upper' | 'boll_lower'
  | 'vol_ma5' | 'vol_ma20'

export type StockBarRow = {
  date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  // Daily rows carry `source` and `is_suspended`; weekly rows carry `sources`, `week_start`, `week_end`, `trading_days`.
  source?: string | null
  sources?: string[]
  is_suspended?: boolean
  week_start?: string
  week_end?: string
  trading_days?: number
  bar_count: number | null
  // Only null fields are listed: insufficient_bars, suspended, invalid_bar, no_price_change or not_computed.
  reasons: Partial<Record<IndicatorField, string>>
} & Partial<Record<IndicatorField, number | null>>

export type StockBarsResponse = {
  instrument: { id: number; exchange: string; symbol: string; name: string; instrument_type: string }
  interval: StockBarsInterval
  limit: number
  count: number
  data_as_of: string | null
  sources: string[]
  indicators: {
    formula_version: string
    price_basis: string
    parameters: Record<string, unknown>
    required_bars: Partial<Record<IndicatorField, number>>
    fields: string[]
    source: string
    computed_at: string | null
  }
  bars: StockBarRow[]
}

// ---- candidate_score_v1 (GET /api/candidates; InstrumentDetail.candidate) ----
// Shapes follow backend/app/candidate_view.py; scores are 0–1 and null means 無資料 (never 0).

export type CandidateComponentKey = 'technical' | 'chips' | 'news_sentiment' | 'group'

export type CandidateSubItem = {
  value: number | null
  percentile: number | null
  weight: number
  better: 'higher' | 'lower' | string
  null_reason: string | null
  null_explanation: string | null
}

export type CandidateComponent = {
  label: string
  score: number | null
  weight: number
  inference: boolean
  item_coverage: number
  null_reason: string | null
  null_explanation: string | null
  items: Record<string, CandidateSubItem>
  // group only: the qualified group the score came from.
  source?: { group_id: string; name: string; board: string; rank: number; board_size: number } | null
}

export type CandidateReason = {
  code: string
  component: CandidateComponentKey | string
  text: string
  params?: Record<string, string>
  inference: boolean
}

export type CandidateGroup = {
  group_id: string
  name: string
  board: 'industry' | 'theme' | string
  qualified: boolean
  rank: number | null
  board_size: number | null
  board_percentile: number | null
  score: number | null
  data_quality: string | null
  score_date: string | null
}

export type CandidateLevels = {
  entry_type: 'breakout' | 'pullback' | string
  entry: number | null
  entry_zone: { low: number | null; high: number | null }
  invalid_price: number | null
  target_1: number | null
  target_2: number | null
  risk_reward: number | null
  earliest_execution_date: string | null
}

// LLM explanation of a candidate (inference, #220); text only when status is done.
export type CandidateLlmNote = {
  status: 'done' | 'pending' | string
  inference: boolean
  selection: string | null
  levels: string | null
  risks: string | null
  model: string | null
  prompt_version: string
  generated_at: string | null
  input_hash: string
}

export type CandidateItem = {
  rank: number
  trading_date: string
  score_version: string
  instrument: { id: number; exchange: string; symbol: string; name: string; instrument_type: string }
  strategy: string
  signal_id: number
  signal_status: string
  levels: CandidateLevels
  total_score: number
  weight_coverage: number
  partial_components: boolean
  components: Record<CandidateComponentKey, CandidateComponent>
  alternatives: Array<{ strategy: string; signal_id: number; total_score: number }>
  reasons: CandidateReason[]
  groups: CandidateGroup[]
  data_as_of: string
  // Missing on responses from before #220; null when no note was attempted.
  llm_note?: CandidateLlmNote | null
  sources: { signal: string; market_bar: string | null; chips: string | null; groups: string; news: string }
  // Close of trading_date and its change (#276); missing on responses from before #276.
  market?: CandidateMarket
}

// known: against the previous verified session from the same source; unverified: change not shown; missing: no traded bar.
export type CandidateMarket = {
  trading_date: string
  close: number | null
  change: number | null
  change_pct: number | null
  change_status: 'known' | 'unverified' | 'missing' | string
  source: string | null
}

export type CandidateZeroReason = 'no_actionable_signals' | 'all_excluded'

export type CandidatesResponse = {
  status: 'not_computed' | 'success' | string
  trading_date: string | null
  score_version: string
  computed_at?: string | null
  evaluated_signals?: number
  pool_count?: number
  candidate_count: number
  zero_reason: CandidateZeroReason | string | null
  zero_reason_text: string | null
  exclusions?: Record<string, number>
  data_as_of?: string
  news_coverage?: Record<string, unknown> | null
  methodology: {
    score_version: string
    purpose: string
    weights: Record<CandidateComponentKey, number> | null
    minimum_weight_coverage: number | null
    components: Record<CandidateComponentKey, { label: string; weight: number | null; inference: boolean }>
    null_explanations: Record<string, string>
  }
  items: CandidateItem[]
}
