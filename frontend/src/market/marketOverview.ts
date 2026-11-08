import type { MarketOverview, MarketOverviewExchange } from '../types'
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
// The TWSE capitalization-weighted index, drawn by the stock page's StockBarsChart from the same bars API (Issue 549;
// close-only twse_index rows follow its synthetic-bar rules until Issue 552 stores real daily K bars).
export const TAIEX = { exchange: 'TWSE', symbol: 'TAIEX' } as const
export const TAIEX_CHART_TITLE = '加權指數日線'

export const UP_DOWN_NOTE = '紅色為上漲、綠色為下跌（台股慣例）'
export const DERIVED_NOTE = '櫃買指數漲跌幅依前一日收市指數計算'
export const TPEX_NO_BARS_TEXT = '無資料：目前只收櫃買指數的當日數值，歷史日 K 尚未收集'

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
