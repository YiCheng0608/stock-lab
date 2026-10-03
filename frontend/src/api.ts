import type {
  BacktestSummary,
  BackfillRun,
  CoverageReport,
  Dashboard,
  ActionSummary,
  CursorPage,
  DataQualityRow,
  EventListRow,
  GroupDetail,
  GroupRow,
  IngestionRun,
  Instrument,
  InstrumentDetail,
  OfficialEventsData,
  OfficialEventFocusData,
  NewsItem,
  GlossaryTerm,
  StockDirectoryRow,
  ThemeDirectoryRow,
  ThemeDetail,
  Paginated,
  Position,
  PositionInput,
  RawPayload,
  Signal,
  StrategyRow,
  TrackingResponse,
} from './types'

import { assertPortfolioValue } from './portfolioValues'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(API_BASE + path)
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

async function post<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

async function del<T>(path: string): Promise<T> {
  const response = await fetch(API_BASE + path, { method: 'DELETE' })
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

type PageParams = { q?: string; page?: number; page_size?: number }

function queryString(params: Record<string, string | number | boolean | undefined>): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value))
  })
  const encoded = query.toString()
  return encoded ? `?${encoded}` : ''
}

export const getDashboard = () => get<Dashboard>('/dashboard')
export const getOfficialEventFocus = (asOf: string, q = '') =>
  get<OfficialEventFocusData>(`/focus/official-events${queryString({ as_of: asOf, q })}`)
export const captureOfficialEventFocus = (asOf: string, q = '') =>
  post<OfficialEventFocusData>(`/focus/official-events/capture${queryString({ as_of: asOf, q })}`, {})
export const getGroups = (params: PageParams = {}) =>
  get<Paginated<GroupRow>>(`/groups${queryString(params)}`)
export const getGroup = (id: string) => get<GroupDetail>(`/groups/${encodeURIComponent(id)}`)
export const getInstruments = (params: PageParams = {}) =>
  get<Paginated<Instrument>>(`/instruments${queryString(params)}`)
export const getInstrument = (symbol: string, exchange?: string) =>
  get<InstrumentDetail>(
    `/instruments/${encodeURIComponent(symbol)}${exchange ? `?exchange=${encodeURIComponent(exchange)}` : ''}`,
  )
export const getSignals = (
  params: PageParams & { status?: string; instrument_symbol?: string } = {},
) => get<Paginated<Signal>>(
  `/signals${queryString({
    q: params.q,
    page: params.page,
    page_size: params.page_size,
    status: params.status,
    instrument_symbol: params.instrument_symbol,
  })}`,
)
export const getEvents = (params: PageParams & { event_type?: string; exchange?: string } = {}) =>
  get<Paginated<EventListRow>>(
    `/events${queryString({
      q: params.q,
      page: params.page,
      page_size: params.page_size,
      event_type: params.event_type,
      exchange: params.exchange,
    })}`,
  )
export const getTracking = () => get<TrackingResponse>('/tracking')
export const getTrackingSignal = (signalKey: string) =>
  get<{ signal: Signal; evaluations: TrackingResponse['rows']; settlements: TrackingResponse['settlements'] }>(
    `/tracking/${encodeURIComponent(signalKey)}`,
  )
export const getPortfolio = (params: PageParams = {}) =>
  get<Paginated<Position>>(`/portfolio${queryString(params)}`)
export const upsertPortfolio = (payload: PositionInput) => {
  assertPortfolioValue(payload.average_cost, '平均成本')
  assertPortfolioValue(payload.stop_price, '停損價')
  assertPortfolioValue(payload.risk_budget, '風險額度')
  return post<Position>('/portfolio', payload)
}
export const deletePortfolio = (positionId: number) =>
  del<{ status: string; id: number }>(`/portfolio/${positionId}`)
export const getDataQuality = (params: PageParams & { entity_type?: string; status?: string } = {}) =>
  get<Paginated<DataQualityRow>>(
    `/data-quality${queryString({
      q: params.q,
      page: params.page,
      page_size: params.page_size,
      entity_type: params.entity_type,
      status: params.status,
    })}`,
  )
export const getRawPayloads = (params: PageParams & { ingestion_run_id?: number; source?: string } = {}) =>
  get<Paginated<RawPayload>>(
    `/raw-payloads${queryString({
      q: params.q,
      page: params.page,
      page_size: params.page_size,
      ingestion_run_id: params.ingestion_run_id,
      source: params.source,
    })}`,
  )
export const getIngestionRuns = (params: PageParams = {}) =>
  get<Paginated<IngestionRun>>(`/ingestion-runs${queryString(params)}`)
export const getStrategies = (params: PageParams = {}) =>
  get<Paginated<StrategyRow>>(`/strategies${queryString(params)}`)
export const getBacktestSummary = (runId?: number) =>
  get<BacktestSummary>(`/backtest/summary${runId ? `?run_id=${runId}` : ''}`)
export const getBackfillRuns = (params: PageParams & { status?: string } = {}) =>
  get<Paginated<BackfillRun>>(`/backfill-runs${queryString({
    q: params.q,
    page: params.page,
    page_size: params.page_size,
    status: params.status,
  })}`)
export const getBackfillRun = (runId: number) => get<BackfillRun>(`/backfill-runs/${runId}`)
export const getCoverage = (params: {
  start_date?: string
  end_date?: string
  scope?: string
  exchange?: string
  symbol?: string
} = {}) => get<CoverageReport>(`/coverage${queryString(params)}`)

export type CursorParams = {
  cursor?: string
  limit?: number
  q?: string
  category?: string
  symbol?: string
  theme_id?: string
  source_kind?: string
  impact_direction?: string
  time_consistency?: string
  state?: string
  held_only?: boolean
  watchlist_only?: boolean
}

export const getNews = (params: CursorParams = {}) =>
  get<CursorPage<NewsItem>>(`/news${queryString(params)}`)
export const getNewsDetail = (newsId: string) =>
  get<NewsItem>(`/news/${encodeURIComponent(newsId)}`)

export const getThemes = (params: PageParams & { leaderboard?: string; only_qualified?: boolean } = {}) =>
  get<{ items: ThemeDirectoryRow[]; meta: Record<string, unknown> }>(
    `/themes${queryString(params)}`,
  )

export const getTheme = (id: string) => get<ThemeDetail>(`/themes/${encodeURIComponent(id)}`)
export const getThemeMembers = (id: string, params: PageParams & { sort?: string } = {}) =>
  get<ThemeDetail & { items: StockDirectoryRow[] }>(
    `/themes/${encodeURIComponent(id)}/members${queryString(params)}`,
  )

export const getStocks = (params: PageParams & { exchange?: string; instrument_type?: string; theme_id?: string; watchlist_only?: boolean } = {}) =>
  get<{ items: StockDirectoryRow[]; meta: Record<string, unknown> }>(`/stocks${queryString(params)}`)

export const getStock = (exchange: string, symbol: string, asOf?: string) =>
  get<InstrumentDetail & { decision_summary: ActionSummary | null; news: NewsItem[] }>(
    `/stocks/${encodeURIComponent(exchange)}/${encodeURIComponent(symbol)}${queryString({ as_of: asOf })}`,
  )

export const captureOfficialEvents = (exchange: string, symbol: string, asOf?: string) =>
  post<OfficialEventsData>(
    `/stocks/${encodeURIComponent(exchange)}/${encodeURIComponent(symbol)}/official-events/capture${queryString({ as_of: asOf })}`,
    {},
  )

export const getActions = (params: CursorParams = {}) =>
  get<CursorPage<ActionSummary> & { taxonomy?: Record<string, string>; summary?: { total: number; actionable: number; data_insufficient: number; held: number } }>(`/actions${queryString(params)}`)

export const getAction = (exchange: string, symbol: string) =>
  get<{ decision_summary: ActionSummary }>(
    `/actions/${encodeURIComponent(exchange)}/${encodeURIComponent(symbol)}`,
  )

export const getGlossary = (params: { q?: string; category?: string } = {}) =>
  get<{ items: GlossaryTerm[]; meta: { version: string; total: number } }>(`/glossary${queryString(params)}`)
