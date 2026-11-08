import { formatDay } from '../dates'
import type { ForeignIndex, MarketOverview, MarketOverviewExchange, StockBarsResponse, TaiexMa60 } from '../types'
import { formatFixed } from '../units'
import { isFiniteNumber } from '../stock/stockBars'

// Pure helpers for the market page (/market, Issue 549) and the 今日可買 one-line summary.
// Copy and units follow UI_COPY_SPEC §11; layout DESIGN_SYSTEM §4/§5.

export const EXCHANGES = [
  { exchange: 'TWSE', label: '上市', index: '加權指數', short: '加權' },
  { exchange: 'TPEx', label: '上櫃', index: '櫃買指數', short: '櫃買' },
] as const
export type ExchangeSpec = (typeof EXCHANGES)[number]

export const MARKET_PATH = '/market'
export const MARKET_PAGE_LEAD = '上市、上櫃的收盤概況，加權、櫃買指數與台指期的日 K，以及前一個交易日的美股指數。'
// The three daily K charts of the market page, each the stock page's StockBarsChart on the same bars API (Issue 549,
// 552): the TWSE capitalization-weighted index, the TPEx index and the TX near month (TAIFEX open data).
export type MarketChartSpec = {
  // 'us-spx' … for the US index charts (Issue 547).
  key: string
  exchange: string
  symbol: string
  title: string
  titleId: string
  instrumentType: 'index' | 'futures'
}
export const MARKET_CHARTS: readonly MarketChartSpec[] = [
  { key: 'taiex', exchange: 'TWSE', symbol: 'TAIEX', title: '加權指數日線', titleId: 'market-chart-title', instrumentType: 'index' },
  { key: 'tpex', exchange: 'TPEx', symbol: 'TPEX', title: '櫃買指數日線', titleId: 'market-tpex-chart-title', instrumentType: 'index' },
  { key: 'tx', exchange: 'TAIFEX', symbol: 'TX', title: '台指期近月日線', titleId: 'market-tx-chart-title', instrumentType: 'futures' },
]
export const TAIEX = MARKET_CHARTS[0]

export const UP_DOWN_NOTE = '紅色為上漲、綠色為下跌（台股慣例）'
export const DERIVED_NOTE = '櫃買指數漲跌幅依前一日收市指數計算'
// 政府資料開放授權條款第1版 第三條 attribution, on the TX chart (coordinator decision 6715831640).
export const TAIFEX_ATTRIBUTION = '資料來源：臺灣期貨交易所（政府資料開放平臺，政府資料開放授權條款第1版）'
export const TX_ROLL_NOTE = '近月合約：每月第三個週三（到期日）起改用次月，換月不做價差調整；只含一般交易時段'

// The TX history starts at the first collect (open data has the latest session only): said when the daily series is
// shorter than the request, so the first bar is the first collected session.
export function collectedSinceText(data: StockBarsResponse | undefined): string | null {
  if (!data || data.interval !== 'day' || !data.bars.length || data.count >= data.limit) return null
  const first = data.bars[0].date
  return `自 ${formatDay(first) ?? first} 起收集，無更早歷史`
}

// 「合約 2026/11 · 未平倉 125,793 口 · 結算價 39,652」 for the latest daily bar with a contract month.
export function futuresLatestText(data: StockBarsResponse | undefined): string | null {
  const latest = data?.interval === 'day' ? [...data.bars].reverse().find((bar) => bar.contract_month) : undefined
  if (!latest?.contract_month) return null
  const month = /^\d{6}$/.test(latest.contract_month) ? `${latest.contract_month.slice(0, 4)}/${latest.contract_month.slice(4)}` : latest.contract_month
  const interest = isFiniteNumber(latest.open_interest) ? `${formatFixed(latest.open_interest, 0)} 口` : '—'
  const settlement = isFiniteNumber(latest.settlement_price) ? formatFixed(latest.settlement_price, 0) : '—'
  return `${formatDay(latest.date) ?? latest.date} 合約 ${month} · 未平倉 ${interest} · 結算價 ${settlement}`
}

export const SCOPE_LABELS: Record<string, string> = {
  twse_all_securities: '集中市場總計（含 ETF、權證等）',
  tpex_stocks: '上櫃股票',
}
// Shown next to each turnover amount, so the scope is on screen without opening 資料說明 (UI_COPY_SPEC §11).
export const SHORT_SCOPE_LABELS: Record<string, string> = {
  twse_all_securities: '集中市場總計',
  tpex_stocks: '上櫃股票',
}

export function available(overview: MarketOverview | undefined, exchange: string): MarketOverviewExchange | null {
  const row = overview?.exchanges.find((item) => item.exchange === exchange)
  return row?.status === 'available' ? row : null
}

export const missingText = (spec: ExchangeSpec) => `${spec.label}大盤資料未取得`

export function changeTone(value: number | null | undefined): 'tone-up' | 'tone-down' | null {
  if (!isFiniteNumber(value) || Number(value.toFixed(2)) === 0) return null
  return value > 0 ? 'tone-up' : 'tone-down'
}

export const dash = (value: number | null | undefined, digits = 0) => isFiniteNumber(value) ? formatFixed(value, digits) : '—'

// A ratio (-0.0049) as a signed percent with two decimals (-0.49%), or — when the source gave none.
export function signedPercent(ratio: number | null | undefined): string {
  return isFiniteNumber(ratio) ? `${formatFixed(ratio * 100, 2, true)}%` : '—'
}

// 今日可買 summary (UI_COPY_SPEC §11): one item per exchange, 「加權 24,012.35 -0.49%」 or 「加權 未取得」.
export type SummaryItem = { spec: ExchangeSpec; close: string | null; pct: string; tone: 'tone-up' | 'tone-down' | null }

export function summaryItems(overview: MarketOverview | undefined): SummaryItem[] {
  return EXCHANGES.map((spec) => {
    const index = available(overview, spec.exchange)?.index
    if (!index || !isFiniteNumber(index.close)) return { spec, close: null, pct: '—', tone: null }
    // The tone reads the shown percent (-0.49), not the ratio (-0.0049) that rounds to 0.00 at two decimals.
    const percent = isFiniteNumber(index.change_pct) ? index.change_pct * 100 : null
    return { spec, close: formatFixed(index.close, 2), pct: signedPercent(index.change_pct), tone: changeTone(percent) }
  })
}

// 資料說明 of the market page: sources, turnover scopes (only exchanges shown), how a derived change is computed.
export function marketOverviewNotes(overview: MarketOverview | undefined): string[] {
  const shown = EXCHANGES.flatMap((spec) => {
    const row = available(overview, spec.exchange)
    return row ? [{ spec, row }] : []
  })
  const sources = shown.flatMap(({ spec, row }) => row.source?.label ? [`${spec.label}為${row.source.label}`] : [])
  const scopes = shown.flatMap(({ spec, row }) => {
    const label = row.turnover?.scope_label ?? (row.turnover?.scope ? SCOPE_LABELS[row.turnover.scope] : undefined)
    return label ? [`${spec.label}為${label}`] : []
  })
  return [
    ...(sources.length ? [`來源：${sources.join('；')}`] : []),
    ...(scopes.length ? [`成交金額範圍：${scopes.join('；')}`] : []),
    ...(isDerived(overview) ? [DERIVED_NOTE] : []),
    UP_DOWN_NOTE,
    // The MA60 definition only when the MA60 line has a position or a count to explain (Issue 561).
    ...(['available', 'insufficient'].includes(overview?.taiex_ma60?.status ?? '') ? [MA60_NOTE, MA60_BACKGROUND_NOTE] : []),
  ]
}

// ---- 加權指數與季線, Issue 561 ------------------------------------------------------------------------
// market_overview.taiex_ma60: one neutral line under the four widgets (no red/green: it is background, not a signal).

export const MA60_LABEL = '加權指數與季線（MA60）'
export const MA60_NOTE = '季線：臺灣證券交易所加權指數最近 60 個交易日收盤的平均（indicators/v1）；位置以當日收盤是否高於季線判定，等於季線不算高於'
export const MA60_BACKGROUND_NOTE = '季線位置只是背景資訊，不是買賣建議，也不影響今日可買名單'
export const MA60_POSITION: Record<string, string> = { above: '在季線之上', below: '在季線之下', equal: '與季線持平' }

const day = (value: string | null | undefined) => formatDay(value) ?? value ?? '—'

// 「季線無資料：…」 or 「季線資料不足：…」 when there is no position to show (UI_COPY_SPEC §11); null when there is.
export function ma60MissingText(item: TaiexMa60 | undefined): string | null {
  if (item?.status === 'available' && isFiniteNumber(item.close) && isFiniteNumber(item.ma60) && item.position && MA60_POSITION[item.position]) return null
  if (item?.status === 'insufficient') {
    const count = isFiniteNumber(item.close_count) ? `只有 ${formatFixed(item.close_count, 0)} 個交易日收盤` : '收盤不足'
    return `季線資料不足：加權指數到 ${day(item.trading_date)} ${count}，季線需要 ${item.required_closes} 個`
  }
  const reasons: Record<string, string> = {
    no_verified_session: '尚無已驗證的資料日',
    not_collected: '加權指數日線未收集',
    row_date_mismatch: `加權指數日線最新為 ${day(item?.latest_trading_date)}，不是資料日`,
    indicator_not_computed: '季線尚未計算',
  }
  return `季線無資料：${(item?.reason && reasons[item.reason]) ?? (item ? '當日收盤無法計算季線' : '尚未提供')}`
}

// 「加權指數 27,123.45（2026/11/06）」 + 「在季線之上」 + 「（季線 25,890.12）」.
export function ma60PositionParts(item: TaiexMa60): { lead: string; position: string; ma60: string } | null {
  if (ma60MissingText(item) !== null) return null
  return {
    lead: `加權指數 ${dash(item.close, 2)}（${day(item.trading_date)}）`,
    position: MA60_POSITION[item.position as string],
    ma60: `（季線 ${dash(item.ma60, 2)}）`,
  }
}

// 「近 250 個交易日在季線之上：2026/09/01–2026/11/06（48 日，持續中）；…」, newest first.
export function ma60SegmentsText(item: TaiexMa60): string | null {
  const window = item.segment_window
  if (ma60MissingText(item) !== null || !window) return null
  const scope = `近 ${formatFixed(window.sessions, 0)} 個交易日`
  const segments = item.segments ?? []
  if (!segments.length) return `${scope}沒有在季線之上的日子`
  const runs = segments.map((run) => {
    const start = `${day(run.start)}${run.starts_before_window ? '（或更早）' : ''}`
    const span = run.start === run.end ? start : `${start}–${day(run.end)}`
    return `${span}（${formatFixed(run.sessions, 0)} 日${run.ongoing ? '，持續中' : ''}）`
  })
  return `${scope}在季線之上：${runs.join('；')}`
}

export const isDerived = (overview: MarketOverview | undefined) => available(overview, 'TPEx')?.index?.change_pct_method === 'derived'

// ---- 美股（前一交易日）, Issue 547 ------------------------------------------------------------------
// FRED closes of four US indexes (market_overview.foreign_indices), in this order; each also has a daily K chart the
// user can open (the stock page's StockBarsChart on /api/stocks/US/<symbol>/bars, close line only).

export type UsIndexSpec = { symbol: string; name: string; titleId: string }
export const US_INDEXES: readonly UsIndexSpec[] = [
  { symbol: 'SPX', name: 'S&P 500', titleId: 'market-us-spx-chart-title' },
  { symbol: 'IXIC', name: 'NASDAQ 綜合指數', titleId: 'market-us-ixic-chart-title' },
  { symbol: 'DJI', name: '道瓊工業指數', titleId: 'market-us-dji-chart-title' },
  { symbol: 'SOX', name: '費城半導體指數', titleId: 'market-us-sox-chart-title' },
]
export const US_SECTION_TITLE = '美股（前一交易日）'
export const FRED_ATTRIBUTION = '資料來源：FRED，Federal Reserve Bank of St. Louis（個人非商業使用）'
export const US_CHANGE_NOTE = '漲跌依前一筆收盤計算；紅色為上漲、綠色為下跌（台股慣例）'
export const US_EXPECTED_NOTE = '預期資料日為台股資料日的前一個平日（週一為上週五）；S&P 500 在 FRED 約晚一天更新'
export const STALE_LABEL = '非最新'

export function usChartSpec(spec: UsIndexSpec): MarketChartSpec {
  return { key: `us-${spec.symbol.toLowerCase()}`, exchange: 'US', symbol: spec.symbol, title: `${spec.name}日線`, titleId: spec.titleId, instrumentType: 'index' }
}

export function foreignIndex(overview: MarketOverview | undefined, symbol: string): ForeignIndex | null {
  return overview?.foreign_indices?.find((item) => item.symbol === symbol) ?? null
}

export const foreignAvailable = (item: ForeignIndex | null): item is ForeignIndex & { trading_date: string } =>
  item?.status === 'available' && typeof item.trading_date === 'string'

// 「無資料：尚未收集」 or 「無資料：最近一次擷取失敗（YYYY/MM/DD）」 (UI_COPY_SPEC §11).
export function foreignMissingText(item: ForeignIndex | null): string {
  if (item?.reason === 'fetch_failed') {
    const day = item.last_attempt_date ? formatDay(item.last_attempt_date) ?? item.last_attempt_date : null
    return `無資料：最近一次擷取失敗${day ? `（${day}）` : ''}`
  }
  return '無資料：尚未收集'
}

// The line under each available index: 「資料 YYYY/MM/DD」 plus 非最新, or 美股休市 when the expected day was a FRED blank.
export function foreignDateText(item: ForeignIndex & { trading_date: string }): { date: string; flag: string | null } {
  const date = `資料 ${formatDay(item.trading_date) ?? item.trading_date}`
  if (item.freshness === 'stale') return { date, flag: STALE_LABEL }
  if (item.freshness === 'us_market_closed') return { date, flag: `${formatDay(item.expected_date) ?? item.expected_date} 美股休市` }
  return { date, flag: null }
}

// The section badge: the newest data date among the indexes shown.
export function foreignLatestDate(overview: MarketOverview | undefined): string | null {
  const dates = (overview?.foreign_indices ?? []).filter(foreignAvailable).map((item) => item.trading_date).sort()
  return dates.length ? dates[dates.length - 1] : null
}

// 資料說明 of the US section, and the per-series copyright notices of the indexes shown (FRED terms).
export function foreignNotes(overview: MarketOverview | undefined): string[] {
  const copyrights = [...new Set((overview?.foreign_indices ?? []).filter(foreignAvailable).flatMap((item) => item.source?.copyright ? [item.source.copyright] : []))]
  return [FRED_ATTRIBUTION, ...copyrights, US_EXPECTED_NOTE, US_CHANGE_NOTE]
}
