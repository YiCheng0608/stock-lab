import type { ChartTheme } from '../stock/stockBars'
import type {
  ThemeBoard,
  ThemeBoardComponent,
  ThemeBoardItem,
  ThemeBoardMeta,
  ThemeDetail,
  ThemeEvidence,
  ThemeInlineMember,
  ThemeMemberRow,
  ThemeTrendPoint,
} from '../types'

// Group boards (docs/V1_SPEC.md hot_group_v1): industries and themes are ranked separately, one request per board.
// The board page takes the whole board (MAX_PAGE_SIZE) and filters names locally; the today page shows the Top 10.
export const THEME_BOARD_LIMIT = 100
export const TODAY_BOARD_LIMIT = 10
export const MEMBER_PAGE_SIZE = 30
export const THEME_NEWS_LIMIT = 10

export const THEME_BOARDS: ReadonlyArray<{ id: ThemeBoard; label: string }> = [
  { id: 'industry', label: '產業' },
  { id: 'theme', label: '題材' },
]

export function themeBoardPath(board: ThemeBoard, limit = THEME_BOARD_LIMIT): string {
  const query = new URLSearchParams({ board, limit: String(limit) })
  return `/themes?${query.toString()}`
}

// ?board= on /themes; anything but "theme" falls back to the default industry board.
export function parseBoard(value: string | null | undefined): ThemeBoard {
  return value === 'theme' ? 'theme' : 'industry'
}

export function boardPagePath(board: ThemeBoard): string {
  return board === 'industry' ? '/themes' : `/themes?board=${board}`
}

export function themeDetailPath(themeId: string): string {
  return '/themes/' + encodeURIComponent(themeId)
}

export function boardLabel(board: string | null | undefined): string {
  return board === 'industry' ? '產業' : board === 'theme' ? '題材' : '其他'
}

// UI_COPY_SPEC §3: only a complete five-component score is called a hot group.
export function qualityLabel(quality: string | null | undefined): string {
  if (quality === 'complete') return '熱門族群'
  if (quality === 'partial') return '技術與籌碼觀察（事件資料待補）'
  return '資料完整度待核實'
}

export function qualityTone(quality: string | null | undefined): 'success' | 'warning' | 'default' {
  return quality === 'complete' ? 'success' : quality === 'partial' ? 'warning' : 'default'
}

export const BOARD_COMPONENTS: ReadonlyArray<{ key: ThemeBoardComponent; label: string }> = [
  { key: 'relative_return', label: '相對報酬' },
  { key: 'breadth', label: '廣度' },
  { key: 'volume_strength', label: '量能' },
  { key: 'institutional_flow', label: '法人' },
  { key: 'catalyst', label: '催化劑' },
]

export const RETURN_WINDOWS: ReadonlyArray<{ key: '1d' | '5d' | '20d'; label: string }> = [
  { key: '1d', label: '1 日' },
  { key: '5d', label: '5 日' },
  { key: '20d', label: '20 日' },
]

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// Components are same-board percentiles 0–1, shown on a 0–100 scale; no data is 「—」, never 0.
export function formatComponent(value: number | null | undefined): string {
  return isFiniteNumber(value) ? (value * 100).toFixed(0) : '—'
}

export function formatScore(value: number | null | undefined): string {
  return isFiniteNumber(value) ? value.toFixed(2) : '—'
}

export function formatRank(rank: number | null | undefined): string {
  return isFiniteNumber(rank) ? `#${rank}` : '—'
}

export type ReturnTone = 'up' | 'down' | 'flat'

// Relative return vs TAIEX as a fraction; percent with two decimals and an explicit sign (red up, green down).
export function relativeReturn(value: number | null | undefined, unit = ''): { text: string; tone: ReturnTone } {
  if (!isFiniteNumber(value)) return { text: '—', tone: 'flat' }
  const percent = (Math.abs(value) * 100).toFixed(2)
  if (percent === '0.00') return { text: `0.00${unit}`, tone: 'flat' }
  return value > 0 ? { text: `+${percent}${unit}`, tone: 'up' } : { text: `-${percent}${unit}`, tone: 'down' }
}

export function formatMembers(eligible: number | null | undefined, total: number | null | undefined): string {
  return `${isFiniteNumber(eligible) ? eligible : '—'}／${isFiniteNumber(total) ? total : '—'}`
}

// UI_COPY_SPEC §1: dates read YYYY/MM/DD.
export function formatDate(value: string | null | undefined): string | null {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null
  return match ? `${match[1]}/${match[2]}/${match[3]}` : null
}

// Score date of the board, plus the official data date only when it differs.
export function boardDates(meta: Pick<ThemeBoardMeta, 'trading_date' | 'data_as_of'>): { trading: string | null; dataAsOf: string | null } {
  const trading = formatDate(meta.trading_date)
  const dataAsOf = formatDate(meta.data_as_of)
  return { trading, dataAsOf: dataAsOf && dataAsOf !== trading ? dataAsOf : null }
}

export function filterBoardItems(items: readonly ThemeBoardItem[], query: string): ThemeBoardItem[] {
  const needle = query.trim().toLocaleLowerCase()
  return needle ? items.filter((item) => item.display_name.toLocaleLowerCase().includes(needle)) : [...items]
}

export function findBoardItem(items: readonly ThemeBoardItem[] | undefined, themeId: string): ThemeBoardItem | null {
  return items?.find((item) => item.theme_id === themeId) ?? null
}

// ---- detail: evidence, members, version ----

const RELATION_LABELS: Record<string, string> = {
  core_business: '主要業務',
  product_line: '產品線',
  supply_chain: '供應鏈',
}
const RELEVANCE_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' }

export function relationLabel(value: string | null | undefined): string {
  return (value && RELATION_LABELS[value]) || '關係待核實'
}

export function relevanceLabel(value: string | null | undefined): string {
  return (value && RELEVANCE_LABELS[value]) || '待核實'
}

// Evidence links open in a new tab; only http(s) URLs become links.
export function evidenceUrl(evidence: ThemeEvidence | null | undefined): string | null {
  const url = evidence?.url?.trim()
  return url && /^https?:\/\//i.test(url) ? url : null
}

export function themeDefinitionVersion(detail: ThemeDetail, rows: ReadonlyArray<{ theme_evidence?: ThemeEvidence | null }> = []): string | null {
  if (detail.theme.definition_version) return detail.theme.definition_version
  const fromEvidence = [...detail.members, ...rows].map((member) => member.theme_evidence?.theme_version).find((value) => value)
  return fromEvidence ?? null
}

// The member table reads the paginated endpoint (it carries the latest close). Until a page arrives the inline list
// stands in, unless the detail says it is truncated: then only the paginated endpoint is used.
export function memberTableRows(detail: ThemeDetail, page: { items: ThemeMemberRow[] } | undefined): Array<ThemeMemberRow | ThemeInlineMember> | null {
  if (page) return page.items
  if (detail.members_truncated) return null
  return detail.members.slice(0, MEMBER_PAGE_SIZE)
}

// ---- trend chart (DESIGN_SYSTEM §6 single-line chart) ----

export function trendHasEnoughPoints(trend: readonly ThemeTrendPoint[]): boolean {
  return trend.filter((point) => isFiniteNumber(point.score)).length >= 2
}

function escapeHtml(value: unknown): string {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

export function formatTrendTooltip(point: ThemeTrendPoint | undefined): string {
  if (!point) return ''
  const lines = [
    `<strong>${escapeHtml(formatDate(point.trading_date) ?? point.trading_date)}</strong>`,
    `分數 ${escapeHtml(formatScore(point.score))}`,
    `排名 ${escapeHtml(formatRank(point.rank))}`,
    `品質 ${escapeHtml(qualityLabel(point.quality))}`,
    `有效成員 ${escapeHtml(isFiniteNumber(point.eligible_members) ? `${point.eligible_members} 檔` : '—')}`,
  ]
  // Only these fixed tags are emitted; every dynamic value above is escaped.
  return lines.join('<br/>')
}

export function buildTrendChartOption(trend: readonly ThemeTrendPoint[], theme: ChartTheme) {
  const axisLabel = { color: theme.muted, fontFamily: theme.fontMono, fontSize: 12 }
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: trend.map((point) => formatDate(point.trading_date)?.slice(5) ?? point.trading_date),
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false },
      axisLabel,
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { lineStyle: { color: theme.grid } },
      axisLabel,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: theme.subtle }, crossStyle: { color: theme.subtle }, label: { backgroundColor: theme.cardBg, color: theme.text, fontFamily: theme.fontMono } },
      backgroundColor: theme.cardBg,
      borderColor: theme.border,
      borderWidth: 1,
      textStyle: { color: theme.text, fontFamily: theme.fontMono, fontSize: 12 },
      extraCssText: 'border-radius: 8px;',
      formatter: (params: unknown) => {
        const entries = Array.isArray(params) ? params : [params]
        const first = entries.find((entry) => entry && typeof entry === 'object' && isFiniteNumber((entry as { dataIndex?: unknown }).dataIndex)) as { dataIndex: number } | undefined
        return first ? formatTrendTooltip(trend[first.dataIndex]) : ''
      },
    },
    series: [{
      name: '熱度分數',
      type: 'line',
      data: trend.map((point) => isFiniteNumber(point.score) ? point.score : '-'),
      connectNulls: false,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: false,
      lineStyle: { color: theme.primary, width: 2 },
      itemStyle: { color: theme.primary },
      // Primary fill from 25% at the line to nothing at the axis.
      areaStyle: {
        opacity: 0.25,
        color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: theme.primary }, { offset: 1, color: 'transparent' }] },
      },
    }],
  }
}
