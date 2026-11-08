import { formatDay } from '../dates'
import type { ForeignIndex, MarketOverview, MarketOverviewExchange, StockBarsResponse } from '../types'
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
  ]
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
