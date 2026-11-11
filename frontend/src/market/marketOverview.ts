import { formatDay } from '../dates'
import type { IndexRow, MarketOverview, MarketOverviewExchange, StockBarsResponse, TaiexMa60 } from '../types'
import { formatFixed } from '../units'
import { isFiniteNumber } from '../stock/stockBars'

// Pure helpers for the market page (/market, Issue 549) and the 今日名單 one-line summary.
// Copy and units follow UI_COPY_SPEC §11; layout DESIGN_SYSTEM §4/§5.

export const EXCHANGES = [
  { exchange: 'TWSE', label: '上市', index: '加權指數', short: '加權' },
  { exchange: 'TPEx', label: '上櫃', index: '櫃買指數', short: '櫃買' },
] as const
export type ExchangeSpec = (typeof EXCHANGES)[number]

export const MARKET_PATH = '/market'
export const MARKET_PAGE_LEAD = '上市、上櫃的收盤概況，以及加權、櫃買、台指期與美股共 7 檔指數的總表；點一列看它的日 K。'

// ---- 指數總表與共用 K 線圖, Issue 564 ---------------------------------------------------------------
// The seven rows of market_overview.indexes, in table order; the shared chart below is the stock page's StockBarsChart
// on /api/stocks/<exchange>/<symbol>/bars for the selected row (TAIEX by default, kept in ?index=).

export type IndexSpec = {
  key: string
  group: 'tw' | 'us'
  exchange: string
  symbol: string
  name: string
  instrumentType: 'index' | 'futures'
  // Price decimals of the row and the chart (DESIGN_SYSTEM §3: indexes two, TX whole points).
  digits: number
}
export const INDEX_SPECS: readonly IndexSpec[] = [
  { key: 'taiex', group: 'tw', exchange: 'TWSE', symbol: 'TAIEX', name: '加權指數', instrumentType: 'index', digits: 2 },
  { key: 'tpex', group: 'tw', exchange: 'TPEx', symbol: 'TPEX', name: '櫃買指數', instrumentType: 'index', digits: 2 },
  { key: 'tx', group: 'tw', exchange: 'TAIFEX', symbol: 'TX', name: '台指期近月', instrumentType: 'futures', digits: 0 },
  { key: 'spx', group: 'us', exchange: 'US', symbol: 'SPX', name: 'S&P 500', instrumentType: 'index', digits: 2 },
  { key: 'ixic', group: 'us', exchange: 'US', symbol: 'IXIC', name: 'NASDAQ 綜合指數', instrumentType: 'index', digits: 2 },
  { key: 'dji', group: 'us', exchange: 'US', symbol: 'DJI', name: '道瓊工業指數', instrumentType: 'index', digits: 2 },
  { key: 'sox', group: 'us', exchange: 'US', symbol: 'SOX', name: '費城半導體指數', instrumentType: 'index', digits: 2 },
]
export const TAIEX = INDEX_SPECS[0]
export const INDEX_PARAM = 'index'
export const INDEX_TABLE_TITLE = '指數總表'
export const INDEX_CHART_ID = 'market-index-chart'
export const INDEX_CHART_TITLE_ID = 'market-chart-title'
export const INDEX_SELECT_HINT = '點一列，下方圖表切換為該指數的日 K'
export const TW_GROUP_TITLE = '台股'
export const US_GROUP_TITLE = '美股'

// The selected row from ?index= (unknown or missing → 加權指數), and the search that selects another one.
export function selectedIndex(search: URLSearchParams): IndexSpec {
  const key = search.get(INDEX_PARAM)
  return INDEX_SPECS.find((spec) => spec.key === key) ?? TAIEX
}
export function indexSearch(search: URLSearchParams, key: string): URLSearchParams {
  const next = new URLSearchParams(search)
  if (key === TAIEX.key) next.delete(INDEX_PARAM)
  else next.set(INDEX_PARAM, key)
  return next
}

export const chartTitle = (spec: IndexSpec) => `${spec.name}日線`

export function indexRow(overview: MarketOverview | undefined, key: string): IndexRow | null {
  return overview?.indexes?.find((row) => row.key === key) ?? null
}

const monthText = (month: string | null | undefined) => month && /^\d{6}$/.test(month) ? `${month.slice(0, 4)}/${month.slice(4)}` : month ?? null

// The TX row's second line under its name: 「合約 2026/11」.
export function contractText(row: IndexRow | null): string | null {
  const month = row?.status === 'available' ? monthText(row.contract_month) : null
  return month ? `合約 ${month}` : null
}

export const ROLL_LABEL = '換月'
// Under the table on a TX roll day: why the row has no change (bars are not adjusted across a roll).
export function rollNote(row: IndexRow | null): string | null {
  if (row?.change_status !== 'contract_roll') return null
  const months = [monthText(row.previous_contract_month), monthText(row.contract_month)].filter(Boolean).join(' → ')
  return `台指期近月 ${day(row.trading_date)} 換月${months ? `（${months}）` : ''}，與前一筆是不同合約，不計漲跌`
}

// 「無資料：尚未收集」, 「無資料：尚無已驗證的資料日」 or 「無資料：最近一次擷取失敗（YYYY/MM/DD）」 for a row without data.
export function indexMissingText(row: IndexRow | null): string {
  if (row?.reason === 'no_verified_session') return '無資料：尚無已驗證的資料日'
  if (row?.reason === 'fetch_failed') {
    const attempt = row.last_attempt_date ? formatDay(row.last_attempt_date) ?? row.last_attempt_date : null
    return `無資料：最近一次擷取失敗${attempt ? `（${attempt}）` : ''}`
  }
  return '無資料：尚未收集'
}

// The 資料日 cell: 「YYYY/MM/DD」 plus 非最新, or 「YYYY/MM/DD 美股休市」 when the expected US day is a recorded US holiday.
export function indexDateText(row: IndexRow & { trading_date: string }): { date: string; flag: string | null } {
  const date = day(row.trading_date)
  if (row.freshness === 'stale') return { date, flag: STALE_LABEL }
  if (row.freshness === 'us_market_closed') return { date, flag: `${day(row.expected_date)} 美股休市` }
  return { date, flag: null }
}

export const indexAvailable = (row: IndexRow | null): row is IndexRow & { trading_date: string } =>
  row?.status === 'available' && typeof row.trading_date === 'string'

export const INDEX_MA60_POSITION: Record<string, string> = { above: '之上', below: '之下', equal: '持平' }

// The 相對季線 cell: a position and the MA60 value, 「資料不足（{n}／60 日）」, or 「無資料：…」.
export type IndexMa60Cell = { kind: 'position'; position: string; ma60: string } | { kind: 'text'; text: string }
export function indexMa60Cell(row: IndexRow | null, digits: number): IndexMa60Cell {
  const item = indexAvailable(row) ? row.ma60 : null
  if (!item) return { kind: 'text', text: '—' }
  if (item.status === 'available' && isFiniteNumber(item.ma60) && item.position && INDEX_MA60_POSITION[item.position]) {
    return { kind: 'position', position: INDEX_MA60_POSITION[item.position], ma60: `季線 ${dash(item.ma60, digits)}` }
  }
  if (item.status === 'insufficient') {
    const count = isFiniteNumber(item.close_count) ? formatFixed(item.close_count, 0) : '—'
    return { kind: 'text', text: `資料不足（${count}／${item.required_closes} 日）` }
  }
  const reasons: Record<string, string> = {
    not_collected: '日線未收集',
    row_date_mismatch: `日線最新為 ${day(item.latest_trading_date)}`,
    indicator_not_computed: '季線尚未計算',
  }
  const reason = item.reason ? reasons[item.reason] : undefined
  return { kind: 'text', text: reason ? `無資料：${reason}` : '無資料' }
}

// 「美股（前一交易日）」 only when every US row with data is the US session before the Taiwan data date (#547's
// freshness: latest or us_market_closed, and dated before market_overview.trading_date); otherwise 「美股」.
export function usGroupTitle(overview: MarketOverview | undefined): string {
  const rows = (overview?.indexes ?? []).filter((row) => row.group === 'us').filter(indexAvailable)
  const twDate = overview?.trading_date ?? null
  const previous = rows.length > 0 && rows.every((row) =>
    (row.freshness === 'latest' || row.freshness === 'us_market_closed') && (twDate === null || row.trading_date < twDate))
  return previous ? US_SECTION_TITLE : US_GROUP_TITLE
}

// 「來源：…」 under the table at every width (the 來源 column is hidden at 640px and below, DESIGN_SYSTEM §5.1).
export const INDEX_SOURCE_NOTE = '來源：加權指數 臺灣證券交易所；櫃買指數 證券櫃檯買賣中心；台指期近月 臺灣期貨交易所；美股 FinMind'
export const INDEX_CHANGE_NOTE = '漲跌：加權、櫃買為交易所公布的收盤概況（同大盤概況）；台指期近月與美股依前一筆收盤計算，台指期換月日不計漲跌'
export const INDEX_STALE_NOTE = '「非最新」：資料日不是預期的資料日（台股為台股資料日，美股為台股資料日的前一個平日）'
export const INDEX_MA60_NOTE = '季線：各指數最近 60 個交易日收盤的平均（indicators/v1），以該列資料日的收盤判定，高於季線為「之上」、等於季線不算高於；不足 60 個交易日寫「資料不足」'

// 資料說明 of the index table: sources and their notices (the index owners' copyright notices kept), how dates,
// changes and the MA60 position are read.
export function indexTableNotes(overview: MarketOverview | undefined): string[] {
  const rows = (overview?.indexes ?? []).filter(indexAvailable)
  const copyrights = [...new Set(rows.flatMap((row) => row.group === 'us' && row.source?.copyright ? [row.source.copyright] : []))]
  return [
    INDEX_SOURCE_NOTE,
    TAIFEX_ATTRIBUTION,
    US_ATTRIBUTION,
    ...copyrights,
    INDEX_STALE_NOTE,
    US_EXPECTED_NOTE,
    INDEX_CHANGE_NOTE,
    ...(isDerived(overview) ? [DERIVED_NOTE] : []),
    UP_DOWN_NOTE,
    INDEX_MA60_NOTE,
    MA60_BACKGROUND_NOTE,
  ]
}

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

// 今日名單 summary (UI_COPY_SPEC §11): one item per exchange, 「加權 24,012.35 -0.49%」 or 「加權 未取得」.
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
export const MA60_BACKGROUND_NOTE = '季線位置只是背景資訊，不是買賣建議，也不影響今日名單'
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

// ---- 美股, Issue 547 --------------------------------------------------------------------------------
// Daily bars of four US indexes from FinMind (Issue 568; market_overview.foreign_indices, the index table's US rows,
// Issue 564). FRED's close-only rows (Issue 547), where a database has them, still chart as a close line.

export const US_SECTION_TITLE = '美股（前一交易日）'
export const US_ATTRIBUTION = '資料來源：FinMind（個人非商業使用）'
export const US_EXPECTED_NOTE = '預期資料日為台股資料日的前一個平日（週一為上週五）'
export const STALE_LABEL = '非最新'
