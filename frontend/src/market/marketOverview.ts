import type { MarketOverview, MarketOverviewExchange, StockBarRow, StockBarsInterval, StockBarsResponse } from '../types'
import { formatDay } from '../dates'
import { formatFixed } from '../units'
import { isFiniteNumber, type ChartTheme, type ChartZoom } from '../stock/stockBars'

// Pure helpers for the market page (/market, Issue 549) and the 今日可買 one-line summary.
// Copy and units follow UI_COPY_SPEC §11; layout DESIGN_SYSTEM §4/§5/§6.

export const EXCHANGES = [
  { exchange: 'TWSE', label: '上市', index: '加權指數', short: '加權' },
  { exchange: 'TPEx', label: '上櫃', index: '櫃買指數', short: '櫃買' },
] as const
export type ExchangeSpec = (typeof EXCHANGES)[number]

export const MARKET_PATH = '/market'
// The TWSE capitalization-weighted index: an index instrument whose daily close comes from MI_INDEX (source twse_index).
export const TAIEX = { exchange: 'TWSE', symbol: 'TAIEX' } as const
// Same window as the stock page K-line (STOCK_BARS_LIMIT; the first view shows its last DEFAULT_VISIBLE_BARS).
export const TAIEX_BARS_LIMIT = 250
export const TABLE_ROWS = 30

export const MARKET_INTERVALS: ReadonlyArray<{ id: StockBarsInterval; label: string }> = [
  { id: 'day', label: '日線' },
  { id: 'week', label: '週線' },
]

export const UP_DOWN_NOTE = '紅色為上漲、綠色為下跌（台股慣例）'
export const DERIVED_NOTE = '櫃買指數漲跌幅依前一日收市指數計算'
export const TPEX_NO_BARS_TEXT = '無資料：櫃買中心大盤資料的來源只提供當日數值，沒有歷史日線'
export const INDEX_CLOSE_ONLY = '指數只有收盤價，只畫收盤線，不畫 K 線與成交量'

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

// ---- 加權指數日線 ----

// Bars whose close the chart can draw: a traded day with a finite positive close.
export function closeOf(bar: StockBarRow): number | null {
  return bar.is_suspended !== true && isFiniteNumber(bar.close) && bar.close > 0 ? bar.close : null
}

// 「來源 臺灣證券交易所」 only when every bar is the official MI_INDEX close (twse_index); otherwise say it is unverified.
export function indexSourceText(sources: readonly string[]): string {
  if (!sources.length) return '來源未提供'
  return sources.every((source) => source === 'twse_index') ? '來源 臺灣證券交易所' : '來源待核實'
}

export function chartMeta(response: StockBarsResponse): string[] {
  const unit = response.interval === 'week' ? '週線' : '日線'
  return [
    indexSourceText(response.sources),
    `最近 ${response.count} 根${unit}；缺日不補${response.interval === 'week' ? '；週線依日線聚合' : ''}`,
    INDEX_CLOSE_ONLY,
  ]
}

export type IndexChartLayout = { height: number; main: number; sliderTop: number; left: number; right: number }

export function indexChartLayout(mainHeight: number): IndexChartLayout {
  return { height: mainHeight + 64, main: mainHeight, sliderTop: mainHeight + 36, left: 64, right: 16 }
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function indexTooltip(bar: StockBarRow | undefined): string {
  if (!bar) return ''
  const close = closeOf(bar)
  return `<strong>${escapeHtml(formatDay(bar.date) ?? bar.date)}</strong><br/>收盤 ${close == null ? '—' : formatFixed(close, 2)} 點`
}

// DESIGN_SYSTEM §6 single line: primary 2px over a primary fill fading to nothing; the y axis is not pinned at 0.
export function buildIndexChartOption(response: StockBarsResponse, theme: ChartTheme, layout: IndexChartLayout, zoom: ChartZoom) {
  const axisLabel = { color: theme.muted, fontFamily: theme.fontMono, fontSize: 12 }
  const bars = response.bars
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: layout.left, right: layout.right, top: 16, height: layout.main },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: bars.map((bar) => formatDay(bar.date) ?? bar.date),
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false },
      axisLabel,
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: theme.grid } },
      axisLabel: { ...axisLabel, formatter: (value: number) => formatFixed(value, 0) },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.subtle } },
      backgroundColor: theme.cardBg,
      borderColor: theme.border,
      borderWidth: 1,
      textStyle: { color: theme.text, fontFamily: theme.fontMono, fontSize: 12 },
      extraCssText: 'border-radius: 8px;',
      formatter: (params: unknown) => {
        const entries = Array.isArray(params) ? params : [params]
        const first = entries.find((entry) => entry && typeof entry === 'object' && isFiniteNumber((entry as { dataIndex?: unknown }).dataIndex)) as { dataIndex: number } | undefined
        return first ? indexTooltip(bars[first.dataIndex]) : ''
      },
    },
    dataZoom: [
      { type: 'inside', start: zoom.start, end: zoom.end },
      {
        type: 'slider', start: zoom.start, end: zoom.end, top: layout.sliderTop, height: 20, left: layout.left, right: layout.right,
        borderColor: theme.border, textStyle: { color: theme.muted, fontFamily: theme.fontMono },
        dataBackground: { lineStyle: { color: theme.subtle }, areaStyle: { color: theme.grid } },
      },
    ],
    series: [{
      name: '加權指數收盤',
      type: 'line',
      data: bars.map((bar) => closeOf(bar) ?? '-'),
      connectNulls: false,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: false,
      lineStyle: { color: theme.primary, width: 2 },
      itemStyle: { color: theme.primary },
      areaStyle: {
        opacity: 0.25,
        color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: theme.primary }, { offset: 1, color: 'transparent' }] },
      },
    }],
  }
}
