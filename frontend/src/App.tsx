import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, NavLink, Route, Routes, useParams, useSearchParams } from 'react-router-dom'

import {
  captureOfficialEvents,
  captureInstitutionalWindows,
  captureStockPriceMemory,
  capturePriceLotFocus,
  captureOfficialEventFocus,
  deletePortfolio,
  getAction,
  getActions,
  getBackfillRuns,
  getBacktestSummary,
  getCoverage,
  getDashboard,
  getOfficialEventFocus,
  getPriceLotFocus,
  getDataQuality,
  getGlossary,
  getGroup,
  getGroups,
  getIngestionRuns,
  getNews,
  getNewsDetail,
  getRawPayloads,
  getStock,
  getStocks,
  getStrategies,
  getTheme,
  getThemeMembers,
  getThemes,
  getTracking,
  getPortfolio,
  upsertPortfolio,
} from './api'
import type {
  ActionSummary,
  BacktestSummary,
  CursorMeta,
  Dashboard,
  DataQualityRow,
  GlossaryTerm,
  GroupDetail,
  GroupMember,
  InstrumentDetail,
  OfficialEventFocusData,
  NewsItem,
  Pagination,
  Position,
  PositionInput,
  RawPayload,
  SignalEvaluation,
  SignalSettlement,
  StockDirectoryRow,
  ThemeDirectoryRow,
  TrackingResponse,
  ProductTime,
} from './types'
import { commitSearchOnEnter } from './search'
import { GLOSSARY } from './glossary'
import { legacyRouteTarget } from './routes'
import { formatPortfolioValue, formatPositionValuation, formatLocalPositionValuation, formatPortfolioClose, formatQuoteRecord, portfolioValueFromText } from './portfolioValues'
import { formatTableNumber, formatTableVolume, formatTableChip, formatShareLots, formatSignedShareLots, formatSourceAwareShareLots, formatShareQuantity, formatPositionShares, positionQuantityFromText, isVerifiedChipFlowSource, isVerifiedMarginSource, isVerifiedShareSource, type ShareUnit } from './units'
import { groupDisplayName, categoryLabel, formatProductTimeRole, levelFieldLabel, levelObservationZoneLabel, levelSemanticsLabel, productActionReasonLabel, productQualityLabel, productResearchDescription, productTimeRoleDateTime, signalConfidenceLabel, stockDirectoryActionLabel, stockDirectoryQualityLabel, stopPriceFieldLabel, type ProductQualityKind } from './presentation'
import { StockPriceChart } from './StockPriceChart'
import { isValidBar } from './stockChart'
import { StockResearchPanel, stockResearchAction, validStockResearchRead } from './StockResearchPanel'
import { stockIndependentView } from './stockIndependentReads'
import { StockOverview } from './components/StockOverview'
import { memoryPriceChartBars, PRICE_SYMBOL_NAMES, priceSourcePins, validStockPriceMemoryRead } from './stockPriceMemoryRead'
import { approximateRangePct, exactTurnoverText, minLotsShares, minRangeMilliPct, minTurnoverValue, priceFocusDayMoveLabels, priceFocusReturnPath, validFocusDate, validPriceFocusDayMove, validPriceFocusParams, validPriceLotFocus } from './priceFocus'
import { formatCanonicalShareLots, formatCanonicalShares } from './units'
import { isTemporaryIndustryGroupName, isTemporaryIndustryTheme, TEMPORARY_INDUSTRY_GROUP_NOTICE } from './stockResearch'

function formatNumber(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('zh-TW', { maximumFractionDigits: digits })
    : '未提供'
}

function formatPercent(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? (value * 100).toFixed(digits)
    : '未提供'
}

function formatSignedNumber(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未提供'
  const formatted = formatNumber(Math.abs(value), digits)
  return value > 0 ? `+${formatted}` : value < 0 ? `-${formatted}` : formatted
}

function formatSignedPercent(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未提供'
  const formatted = formatPercent(Math.abs(value), digits)
  return value > 0 ? `+${formatted}` : value < 0 ? `-${formatted}` : formatted
}

function compactText(value: string | null | undefined, maxLength = 120): string | null {
  if (!value) return null
  const cleaned = String(value).replace(/\s+/g, ' ').trim()
  if (!cleaned) return null
  return cleaned.length <= maxLength ? cleaned : cleaned.slice(0, maxLength - 1).trimEnd() + '…'
}

function formatTaiwanDateTime(value: string | null | undefined, dateOnly = false): string {
  if (!value) return '未提供'
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z'
  const parsed = new Date(normalized)
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10)
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(dateOnly ? {} : { hour: '2-digit', minute: '2-digit' }),
  }).format(parsed)
}

const statusNames: Record<string, string> = {
  complete: '完整',
  partial: '部分完整',
  missing: '缺資料',
  data_incomplete: '資料不足',
  insufficient_members: '成員不足',
  insufficient_data: '資料不足',
  insufficient_sample: '樣本不足',
  technical_only: '僅技術驗證',
  conditional: '條件成立',
  observation: '觀察',
  invalid_levels: '價位無效',
  active: '追蹤中',
  success: '成功',
  failed: '失敗',
  running: '執行中',
  incomparable: '不可比',
  invalidated: '已失效',
  target_1_hit: '達到第一目標',
  target_2_hit: '達到第二目標',
  manual_review: '需人工判讀',
  no_data: '尚無資料',
  official: '官方資料',
  official_snapshot: '官方快照',
  unknown: '未知',
}

const actionNames: Record<string, string> = {
  conditional_entry: '條件進場',
  wait_breakout: '等待突破',
  wait_pullback: '等待回踩',
  hold_observe: '持有觀察',
  reduce_exit: '庫存風險：減碼／退場條件',
  data_insufficient: '策略判斷資料待補',
  no_condition: '暫無研究條件',
  manual_review: '需人工判讀',
}

function statusLabel(status: string | null | undefined): string {
  return statusNames[status ?? 'unknown'] ?? '待確認'
}

function uiStatusLabel(status: string | null | undefined): string {
  return statusNames[status ?? 'unknown'] ?? '待確認'
}

function actionLabel(state: string): string {
  return actionNames[state] ?? '待判定'
}

function sourceLabel(source: string | null | undefined | readonly string[]): string {
  if (Array.isArray(source)) {
    const sources = [...new Set((source as readonly unknown[]).map((value) => typeof value === 'string' ? value.trim() : '').filter(Boolean))]
    if (sources.length === 0) return '來源未提供'
    if (sources.some((value) => value.toLowerCase() === 'unknown')) return '來源未完整提供'
    return sources.map((value) => sourceLabel(value)).join('／')
  }
  if (typeof source !== 'string' || !source) return '來源未提供'
  const normalized = source.trim().toLowerCase()
  if (!normalized || normalized === 'unknown') return '來源未提供'
  const names: Record<string, string> = {
    official: '官方資料',
    twse: '臺灣證券交易所',
    tpex: '證券櫃檯買賣中心',
    mops: '公開資訊觀測站',
    'twse/tpex official feeds': 'TWSE／TPEx 官方資料',
    'no configured official collection': '尚無已驗證的官方資料',
    'official-fixture': '官方資料',
  }
  return names[normalized] ?? (/^[\x00-\x7F]*$/.test(source) ? '來源待核實' : source)
}

function newsSourceLabel(source: string | null | undefined): string {
  if (!source) return '官方公告資料'
  const value = source.trim()
  const normalized = value.toLowerCase()
  if (normalized === 'mops' || normalized.startsWith('mops_')) return '公開資訊觀測站公告'
  if (normalized.startsWith('tpex')) return '櫃買中心官方資料'
  if (normalized.startsWith('twse')) return '證交所官方資料'
  return value.includes('官方') ? value : '官方公告資料'
}

function userFacingNewsThemes(item: NewsItem): NewsItem['themes'] {
  return item.themes.filter((theme) => {
    const name = theme.display_name.trim()
    if (!name || name === '族群待確認') return false
    // The API only emits verified active memberships.  Keep this small
    // compatibility guard for an older server response that may still carry
    // a legacy English group label until the backend is restarted.
    return !/^(industry|etf|new listings)\b/i.test(name)
  })
}

function instrumentTypeLabel(type: string): string {
  return ({ stock: '股票', equity: '股票', etf: 'ETF', ipo: '新上市', index: '指數' }[type.toLowerCase()] ?? '其他標的')
}

function marketDisplayLabel(value: string | null | undefined): string {
  if (value === 'TWSE') return '上市'
  if (value === 'TPEx') return '上櫃'
  return '市場待核實'
}

function officialEventDisplayTitle(title: string | null | undefined, type: string | null | undefined = null): string {
  if (title === 'TPEx resumption' || type === 'TPEx resumption') return '上櫃股票恢復交易'
  if (title === 'TPEx suspension interval' || type === 'TPEx suspension interval') return '上櫃股票暫停交易期間'
  return title || type || '官方事件'
}

function strategyLabel(strategy: string | null | undefined): string {
  return ({
    breakout_v1: '突破條件',
    pullback_v1: '回踩條件',
    breakout: '突破條件',
    pullback: '回踩條件',
  }[strategy ?? ''] ?? '策略條件')
}

const themeMetricLabels: Record<string, string> = {
  relative_return_1d: '1 日相對大盤',
  relative_return_5d: '5 日相對大盤',
  relative_return_20d: '20 日相對 加權指數',
  breadth: '成員廣度',
  volume_strength: '量能強度',
  institutional_flow: '法人籌碼',
}

function themeMetricLabel(key: string): string | null {
  return themeMetricLabels[key] ?? null
}

function priceChangeTone(value: number | null | undefined): 'positive' | 'negative' | '' {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return ''
  return value > 0 ? 'positive' : 'negative'
}

function chipSourceHasShareUnit(source: string | null | undefined): boolean {
  return isVerifiedChipFlowSource(source)
}

function formatChipFlow(value: number | null, source: string | null | undefined): string {
  if (value == null) return '未提供'
  return chipSourceHasShareUnit(source) ? formatSignedShareLots(value) : `${formatSignedNumber(value)}（單位待提供）`
}

function formatChipMarginChange(value: number | null, source: string | null | undefined): string {
  if (value == null) return '未提供'
  return isVerifiedMarginSource(source) ? `${formatSignedNumber(value)} 張` : `${formatSignedNumber(value)}（單位待提供）`
}

const fieldNames: Record<string, string> = {
  data_as_of: '資料截至日',
  market_bar: '日行情',
  bars_20d: '20 日行情',
  bars_60d: '60 日行情',
  benchmark: '加權指數 基準',
  theme_membership: '族群成員',
  qualified_theme: '完整熱門族群',
  institutional_flow_5d: '5 日法人籌碼',
  foreign_buy: '外資淨買賣超',
  trust_buy: '投信淨買賣超',
  dealer_buy: '自營商淨買賣超',
  margin_balance: '融資餘額',
  margin_change: '融資變化',
  risk_reward: '風險報酬比',
  trigger_price: '觸發價',
  entry_low: '回踩區下緣',
  entry_high: '回踩區上緣',
  invalid_price: '失效價／停損',
  target_1: '第一目標價',
  prior_20_highs: '20 日前期高點',
  prior_20_volumes: '20 日前期成交量',
  bar_count_60d: '60 日有效行情日數',
  ma20: 'MA20',
  ma60: 'MA60',
  group_excess_return_20d: '族群相對 加權指數 的 20 日超額報酬',
  institutional_flow_to_turnover_ratio_5d: '5 日法人流向／20 日日均成交額',
  margin_balance_change_ratio_5d: '5 日融資餘額變化率',
  signal_data_quality: '訊號資料品質',
  signal: '策略訊號',
}

const fieldAliases: Record<string, string> = {
  'taiex excess return 20d': '族群相對 加權指數 的 20 日超額報酬',
  'institutional flow 5d': '5 日法人籌碼',
  'margin change 5d': '5 日融資餘額變化率',
  'prior 20 highs': '20 日前期高點',
  'prior 20 volumes': '20 日前期成交量',
  'bar count 60d': '60 日有效行情日數',
  'average daily turnover 20d': '20 日日均成交額',
}

function fieldLabel(field: string): string {
  const value = field.trim()
  const normalized = value.toLowerCase()
  return fieldNames[value] ?? fieldNames[normalized] ?? fieldAliases[normalized] ?? (/[\u3400-\u9fff]/.test(value) ? value : '待補資料')
}

function researchSourceLabel(source: string | null | undefined): string {
  if (!source) return '系統固定研究規則'
  const value = source.trim()
  const normalized = value.toLowerCase()
  if (value.includes('固定研究規則') || normalized === 'canonical' || normalized.includes('strategy rule')) return '系統固定研究規則'
  return sourceLabel(value)
}

function QualityBadge({ status, kind = 'technical' }: { status: string | null | undefined; kind?: 'technical' | ProductQualityKind }) {
  const value = status ?? 'unknown'
  const label = kind === 'technical' ? uiStatusLabel(value) : productQualityLabel(value, kind)
  return <span className={'pill ' + value.replace(/[^a-zA-Z0-9]+/g, '_')}>{label}</span>
}

function Loading() {
  return <div className="loading">資料載入中…</div>
}

function ErrorBox({ error }: { error: unknown }) {
  const detail = error instanceof Error ? error.message : '未知錯誤'
  return <div className="error-box"><div>資料暫時無法載入，請稍後重新整理。</div><details className="technical-details"><summary>錯誤詳細資訊</summary><div>{detail}</div></details></div>
}

function QueryState({ loading, error, children }: { loading: boolean; error: unknown; children: ReactNode }) {
  if (loading) return <Loading />
  if (error) return <ErrorBox error={error} />
  return <>{children}</>
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">台股研究專案</div>
          <Link to="/" className="brand">市場研究台</Link>
        </div>
        <nav aria-label="主要導覽">
          <NavLink to="/" end>今日</NavLink>
          <NavLink to="/news">新聞</NavLink>
          <NavLink to="/themes">族群</NavLink>
          <NavLink to="/stocks">個股</NavLink>
          <NavLink to="/actions">行動</NavLink>
        </nav>
      </header>
      <main>{children}</main>
      <footer>
        <span>T 日收盤訊號 · 最早 T+1 執行 · T+5／T+20 追蹤</span>
        <span>僅使用官方資料 · 詳細來源見各頁資料說明</span>
        <nav className="secondary-nav" aria-label="次要工具">
          <Link to="/research/backtest">技術回測</Link>
          <Link to="/research/coverage">資料覆蓋度</Link>
          <Link to="/research/strategies">策略版本</Link>
          <Link to="/system/data-quality">資料品質</Link>
          <Link to="/glossary">用語表</Link>
        </nav>
      </footer>
    </div>
  )
}

function PageTitle({ eyebrow, title, description, children }: { eyebrow: string; title: string; description?: string; children?: ReactNode }) {
  return (
    <section className="page-title">
      <div className="eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      {description && <p>{description}</p>}
      {children}
    </section>
  )
}

function SearchBox({
  draft,
  query,
  placeholder,
  onDraftChange,
  onSubmit,
  onClear,
}: {
  draft: string
  query: string
  placeholder: string
  onDraftChange: (value: string) => void
  onSubmit: (value?: string) => void
  onClear: () => void
}) {
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const committed = commitSearchOnEnter(event.currentTarget.value, event.key)
    if (committed !== null) {
      event.preventDefault()
      onSubmit(committed)
    }
  }
  return (
    <div className="search-controls">
      <input
        className="search-input"
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label="搜尋"
      />
      <button type="button" className="secondary-button" onClick={() => onSubmit()}>搜尋</button>
      {(draft || query) && <button type="button" className="secondary-button" onClick={onClear}>清除</button>}
    </div>
  )
}

function PagePagination({ pagination, onPageChange }: { pagination: Pagination; onPageChange: (page: number) => void }) {
  if (!pagination.total) return <div className="empty">沒有符合條件的資料。</div>
  return (
    <div className="pagination-controls">
      <span>第 {pagination.page}／{pagination.total_pages} 頁 · 共 {pagination.total.toLocaleString()} 筆</span>
      <div>
        <button type="button" className="secondary-button" disabled={!pagination.has_previous} onClick={() => onPageChange(pagination.page - 1)}>上一頁</button>
        <button type="button" className="secondary-button" disabled={!pagination.has_next} onClick={() => onPageChange(pagination.page + 1)}>下一頁</button>
      </div>
    </div>
  )
}

function DirectoryPagination({ meta, onPageChange }: { meta: Record<string, unknown>; onPageChange: (page: number) => void }) {
  const page = Number(meta.page ?? 1)
  const totalPages = Number(meta.total_pages ?? 0)
  const total = Number(meta.total ?? 0)
  if (!total) return <div className="empty">沒有符合條件的資料。</div>
  return (
    <div className="pagination-controls">
      <span>第 {page}／{totalPages} 頁 · 共 {total.toLocaleString()} 筆</span>
      <div>
        <button type="button" className="secondary-button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一頁</button>
        <button type="button" className="secondary-button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>下一頁</button>
      </div>
    </div>
  )
}

function CursorControls({ meta, page, itemCount, onNext, onPrevious, onReset }: { meta: CursorMeta; page: number; itemCount: number; onNext: (cursor: string) => void; onPrevious: () => void; onReset: () => void }) {
  if (!meta.total && !meta.has_more && !meta.next_cursor && page === 1) return <div className="empty">沒有符合條件的資料。</div>
  return (
    <div className="pagination-controls">
      <span>第 {page} 頁 · 本頁 {itemCount} 筆{meta.total == null ? '' : ` · 共 ${meta.total.toLocaleString()} 筆`}</span>
      <div>
        <button type="button" className="secondary-button" disabled={page <= 1} onClick={onPrevious}>上一頁</button>
        <button type="button" className="secondary-button" disabled={!meta.next_cursor} onClick={() => meta.next_cursor && onNext(meta.next_cursor)}>下一頁</button>
        <button type="button" className="secondary-button" disabled={page <= 1} onClick={onReset}>回到第一頁</button>
      </div>
    </div>
  )
}

function Term({ id, children }: { id: string; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const term = GLOSSARY.find((item) => item.term_id === id)
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])
  if (!term) return <span>{children ?? id}</span>
  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="term-button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        {children ?? term.name}
      </button>
      {open && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setOpen(false)}>
          <section className="glossary-modal" role="dialog" aria-modal="true" aria-label={term.name} onMouseDown={(event) => event.stopPropagation()}>
            <div className="position-head"><strong>{term.name}</strong><button type="button" className="secondary-button" onClick={() => { setOpen(false); buttonRef.current?.focus() }}>關閉</button></div>
            <p><b>白話定義：</b>{term.plain_definition.replaceAll('外陸資', '外資')}</p>
            <p><b>用途：</b>{term.use}</p>
            <p><b>如何解讀：</b>{term.how_to_read}</p>
            <p><b>限制：</b>{term.limitations}</p>
          </section>
        </div>
        )}
    </>
  )
}

function actionPath(action: ActionSummary): string {
  return '/actions/' + encodeURIComponent(action.instrument.exchange) + '/' + encodeURIComponent(action.instrument.symbol)
}

function importantActionLevel(action: ActionSummary): string | null {
  if (['data_insufficient', 'data_incomplete', 'insufficient_data', 'no_condition', 'manual_review'].includes(action.action_state)) return null
  if (action.action_state === 'conditional_entry') {
    const levels = [
      action.trigger_price == null ? null : levelFieldLabel('trigger_price', action.level_semantics) + ' ' + formatNumber(action.trigger_price),
      action.invalid_price == null ? null : levelFieldLabel('invalid_price', action.level_semantics) + ' ' + formatNumber(action.invalid_price),
    ].filter(Boolean)
    return levels.length ? levels.join('／') : null
  }
  if (action.action_state === 'wait_breakout' && action.trigger_price != null) return levelFieldLabel('trigger_price', action.level_semantics) + ' ' + formatNumber(action.trigger_price)
  if (action.action_state === 'wait_pullback' && (action.entry_low != null || action.entry_high != null)) {
    return levelObservationZoneLabel(action.level_semantics) + ' ' + formatNumber(action.entry_low) + '～' + formatNumber(action.entry_high)
  }
  if (['hold_observe', 'reduce_exit'].includes(action.action_state) && action.stop_price != null) return stopPriceFieldLabel(action.stop_price_semantics) + ' ' + formatNumber(action.stop_price)
  return null
}

function ProductTimeSummary({
  time,
  news = false,
  compact = false,
  fallbackDate,
  fallbackEarliestDate,
}: {
  time?: ProductTime
  news?: boolean
  compact?: boolean
  fallbackDate?: string | null
  fallbackEarliestDate?: string | null
}) {
  const eventAt = news ? productTimeRoleDateTime(time, 'event_at') : undefined
  const dateRole = news && eventAt ? 'event_at' : news ? 'event_date' : 'market_date'
  const dateLabel = news ? (eventAt ? '事件時間' : '事件日期') : '資料日期'
  const dateTime = productTimeRoleDateTime(time, dateRole)
  const published = formatProductTimeRole(time, 'published_at')
  const publishedLabel = time?.roles?.published_at?.precision === 'date' ? '發布日期' : '發布時間'
  const decision = formatProductTimeRole(time, 'decision_at')
  const earliest = formatProductTimeRole(time, 'earliest_execution_date', fallbackEarliestDate ?? null)
  const dateValue = formatProductTimeRole(time, dateRole, fallbackDate ?? null)
  return (
    <div className="small-note product-time-summary" data-testid="product-time-summary">
      <div>
        <span>{dateLabel}：{dateValue}</span>
        {news && <span> · {publishedLabel}：{published}</span>}
        {!news && <span> · 決策時間：{decision}</span>}
        {!news && <span> · 規則最早執行日：{earliest}</span>}
      </div>
      {dateTime && <time dateTime={dateTime} hidden />}
      {!compact && <div>時間以台灣時間顯示；未確認的時間保留待核實。</div>}
    </div>
  )
}

export function CompactActionCard({ action }: { action: ActionSummary }) {
  const instrument = action.instrument
  const read = action.market_read
  const explicitRead = read !== undefined
  const validRead = !explicitRead || (read != null && !Array.isArray(read) && read.status === 'known'
    && Array.isArray(read.invalid_fields) && read.invalid_fields.length === 0
    && typeof action.current_price === 'number' && Number.isFinite(action.current_price) && action.current_price > 0)
  const price = validRead && typeof action.current_price === 'number' && Number.isFinite(action.current_price) ? action.current_price : null
  const incomplete = (explicitRead && !validRead) || ['data_insufficient', 'data_incomplete', 'insufficient_data'].includes(action.action_state)
  const title = incomplete ? '策略判斷資料待補' : action.display_action || actionLabel(action.action_state)
  const validChange = validRead && price !== null && typeof action.price_change === 'number' && Number.isFinite(action.price_change)
    && typeof action.price_change_pct === 'number' && Number.isFinite(action.price_change_pct) && Number.isFinite(action.price_change_pct * 100)
  const change = validChange
    ? `漲跌（元／%） ${formatSignedNumber(action.price_change)}（${formatSignedPercent(action.price_change_pct)}）`
    : '漲跌待核實'
  return (
    <Link className="panel compact-action-card" to={actionPath(action)} aria-label={`${instrument.symbol} ${title}`}>
      <div className="position-head"><span className="symbol-link"><strong>{instrument.symbol}</strong> {instrument.name}</span><span className="pill action-status-pill">{title}</span></div>
      <div className="small-note">{marketDisplayLabel(instrument.exchange)} · {instrumentTypeLabel(instrument.instrument_type)}</div>
      {action.position_quantity_status === 'unknown' && <span className="pill ambiguous">庫存數量待核實</span>}
      <div className="compact-price" style={{ minWidth: 0, flexWrap: 'wrap' }}><div style={{ minWidth: 0, flex: '1 1 140px', overflowWrap: 'anywhere' }}><span className="compact-label">最近收盤（報價幣別元）</span><strong>{price !== null ? formatNumber(price) : '待核實'}</strong></div><span style={{ minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }} className={priceChangeTone(validChange ? action.price_change : null)}>{change}</span></div>
      {explicitRead && !validRead && read?.status !== 'missing' && <div className="small-note">行情讀值無效，先核對原記錄。</div>}
      {read?.status === 'missing' && <div className="small-note">尚無行情記錄。</div>}
      <div className="small-note">資料日 {formatTaiwanDateTime(action.data_cutoff ?? action.price_as_of, true)}</div>
      <span className="compact-detail-link">查看個股詳情 →</span>
    </Link>
  )
}

function ProductActionCard({ action }: { action: ActionSummary }) {
  const instrument = action.instrument
  const incomplete = ['data_insufficient', 'data_incomplete', 'insufficient_data'].includes(action.action_state)
  const actionTitle = incomplete ? '策略判斷資料待補' : action.display_action || actionLabel(action.action_state)
  const visibleMissing = action.missing_data_priority.slice(0, 4)
  const remainingMissing = action.missing_data_priority.slice(4)
  const showLevels = ['conditional_entry', 'wait_breakout', 'wait_pullback', 'hold_observe', 'reduce_exit'].includes(action.action_state)
  const primaryConfidenceSemantics = action.strategies.find((strategy) => strategy.strategy === action.primary_strategy)?.confidence_semantics ?? action.strategies[0]?.confidence_semantics
  return (
    <article className="panel action-card">
      <div className="position-head">
        <Link to={'/stocks/' + encodeURIComponent(instrument.exchange) + '/' + encodeURIComponent(instrument.symbol)} className="symbol-link">
          <strong>{instrument.symbol}</strong> {instrument.name}
        </Link>
        <span className="pill action-status-pill">{actionTitle}</span>
      </div>
      {incomplete && <div className="action-state">目前無法產生研究動作</div>}
      {action.action_state === 'conditional_entry' && action.primary_strategy && <div className="action-state">今日{strategyLabel(action.primary_strategy)}成立</div>}
      <div className="small-note">{instrument.exchange} · {instrumentTypeLabel(instrument.instrument_type)}</div>
      {action.position_quantity_status === 'unknown' && <div className="small-note"><span className="pill ambiguous">庫存數量待核實</span> 庫存數量待核實，先核對原記錄。</div>}
      <ProductTimeSummary time={action.product_time} fallbackDate={action.data_cutoff} fallbackEarliestDate={action.earliest_execution_date} />
      {action.primary_strategy && <div className="small-note">主條件：{strategyLabel(action.primary_strategy)}{action.alternative_strategies.length ? ' · 替代：' + action.alternative_strategies.map(strategyLabel).join('、') : ''}</div>}
      <div className="action-instruction">{action.display_instruction ?? action.action_instruction ?? (incomplete ? '現在：先不行動' : actionLabel(action.action_state))}</div>
      {action.current_price != null && <div className="metric-row"><span>最近收盤／漲跌幅（報價幣別元／%，{formatTaiwanDateTime(action.price_as_of, true)}）</span><b>{formatNumber(action.current_price)}{action.price_change_pct != null ? ' · ' + formatSignedPercent(action.price_change_pct) : ' · 漲跌幅待核實'}</b></div>}
      {incomplete ? (
        <div className="data-gap">{productActionReasonLabel(action.data_gap ?? '研究資料尚未完整，尚不能計算進場、失效與目標價。')}</div>
      ) : showLevels ? (
        <><p className="small-note">價位單位：各標的報價幣別的元；風險報酬比為倍。</p><div className="level-grid">
          {['conditional_entry', 'wait_breakout'].includes(action.action_state) && action.trigger_price != null && <div><span>{levelFieldLabel('trigger_price', action.level_semantics)}</span><b>{formatNumber(action.trigger_price)}</b></div>}
          {action.action_state === 'conditional_entry' && action.primary_strategy === 'pullback_v1' && (action.entry_low != null || action.entry_high != null) && <div><span>{levelObservationZoneLabel(action.level_semantics)}</span><b>{formatNumber(action.entry_low)}～{formatNumber(action.entry_high)}</b></div>}
          {action.action_state === 'wait_pullback' && action.entry_low != null && <div><span>{levelFieldLabel('entry_low', action.level_semantics)}</span><b>{formatNumber(action.entry_low)}</b></div>}
          {action.action_state === 'wait_pullback' && action.entry_high != null && <div><span>{levelFieldLabel('entry_high', action.level_semantics)}</span><b>{formatNumber(action.entry_high)}</b></div>}
          {action.action_state === 'conditional_entry' && action.invalid_price != null && <div><span>{levelFieldLabel('invalid_price', action.level_semantics)}</span><b>{formatNumber(action.invalid_price)}</b></div>}
          {action.action_state === 'conditional_entry' && action.target_1 != null && <div><span>{levelFieldLabel('target_1', action.level_semantics)}</span><b>{formatNumber(action.target_1)}</b></div>}
          {action.action_state === 'conditional_entry' && action.risk_reward != null && <div><span><Term id="rr">風險報酬比</Term></span><b>{formatNumber(action.risk_reward, 2)}</b></div>}
           {['hold_observe', 'reduce_exit'].includes(action.action_state) && action.stop_price != null && <div><span>{stopPriceFieldLabel(action.stop_price_semantics)}</span><b>{formatNumber(action.stop_price)}</b></div>}
         </div></>
       ) : null}
      {(action.display_reasons ?? action.reasons).length > 0 && <ul className="reason-list">{(action.display_reasons ?? action.reasons).map((reason) => <li key={reason}>{action.display_reasons ? reason : productActionReasonLabel(reason)}</li>)}</ul>}
      {action.conflicts.length > 0 && <div className="warning-box">{action.conflicts.join('；')}</div>}
      {visibleMissing.length > 0 && (
        <div className="missing-list">
          <div className="small-note">缺少資料與補齊優先級</div>
          {visibleMissing.map((item) => <div key={item.field}><span>{fieldLabel(item.field)}</span><span className="pill priority-pill">{item.priority_label}</span></div>)}
          {remainingMissing.length > 0 && <details className="technical-details"><summary>查看完整缺口（{remainingMissing.length} 項）</summary>{remainingMissing.map((item) => <div key={item.field}><span>{fieldLabel(item.field)}</span><span>{item.priority_label}</span></div>)}</details>}
        </div>
      )}
      <details className="technical-details"><summary>技術資訊</summary><div>策略判斷資料：{productQualityLabel(action.data_quality, 'research')}</div><div>資料日：{formatTaiwanDateTime(action.data_cutoff, true)}</div><div>價位語意：{levelSemanticsLabel(action.level_semantics)}</div>{action.strategies.length > 0 && <div>訊號信心欄位：{signalConfidenceLabel(primaryConfidenceSemantics)}</div>}{action.stop_price_semantics?.kind === 'user_position_risk_input' && <div>風險價來源：庫存設定，不是規則失效參考價。</div>}<div>策略結果與官方行情、籌碼來源已保留供稽核。</div></details>
    </article>
  )
}

function ThemeCard({ theme }: { theme: ThemeDirectoryRow }) {
  const metrics = Object.entries(theme.metrics)
    .filter(([key, value]) => themeMetricLabel(key) && value != null)
    .slice(0, 2)
  const needsTemporaryVerification = isTemporaryIndustryTheme(theme)
  return (
    <article className="group-card">
      <Link to={'/themes/' + encodeURIComponent(theme.theme_id)} className="group-card-link">
        <div className="group-card-head">{theme.rank != null && <span className="rank">#{theme.rank}</span>}{needsTemporaryVerification ? <span className="pill ambiguous">關聯待核實</span> : theme.qualified ? <span className="pill complete">族群評分資料完整</span> : <QualityBadge kind="theme" status={theme.data_quality} />}</div>
        <h3>{needsTemporaryVerification ? '產業名稱待核實（既有分類）' : groupDisplayName(theme.display_name)}</h3>
        <div className="small-note">{categoryLabel(theme.category)} · {theme.eligible_members} 檔既有成員</div>
        {metrics.length ? <div className="theme-metric-list">{metrics.map(([key, value]) => <div className="metric-row" key={key}><span>{themeMetricLabel(key)}（%）</span><b>{key.startsWith('relative_return_') ? formatSignedPercent(value) : key === 'breadth' ? formatPercent(value, 0) : formatPercent(value)}</b></div>)}</div> : <div className="small-note">資料待核實。</div>}
        <span className="compact-detail-link">查看族群詳情 →</span>
      </Link>
      {needsTemporaryVerification && <div className="data-gap theme-verification-warning">{TEMPORARY_INDUSTRY_GROUP_NOTICE}</div>}
      {needsTemporaryVerification && <details className="technical-details"><summary>既有資料</summary><div>既有名稱：{theme.display_name}</div><div>既有識別碼：{theme.theme_id}</div><div>既有成員數：{theme.eligible_members}</div></details>}
    </article>
  )
}

function newsCategoryLabel(item: NewsItem): string {
  return item.category === 'company' ? '公司公告' : '交易所公告'
}

function newsEventDate(item: NewsItem): string | null {
  return item.event_date ?? (item.event_at ? item.event_at.slice(0, 10) : null)
}

function ProductNewsCard({ item, detail = false }: { item: NewsItem; detail?: boolean }) {
  const relatedInstruments = item.instruments ?? []
  const visibleThemes = userFacingNewsThemes(item)
  const impactLabel = item.impact_direction === 'positive' ? '可能正向' : item.impact_direction === 'negative' ? '可能負向' : '影響尚未判定'
  const confidenceLabel = item.confidence === 'high' ? '高可信度' : '可信度待確認'
  const eventDate = newsEventDate(item)
  const displayTitle = officialEventDisplayTitle(item.title)

  if (!detail) {
    return (
      <article className="news-list-item" data-testid="news-list-item">
        <div className="news-list-time">{eventDate ? `事件日 ${formatTaiwanDateTime(eventDate, true)}` : item.published_at ? `發布日 ${formatTaiwanDateTime(item.published_at, true)}` : '日期待核實'}</div>
        <div className="news-list-main">
          <div className="news-list-meta"><span>{newsCategoryLabel(item)}</span><span>{newsSourceLabel(item.source_name)}</span></div>
          <h3><Link to={'/news/' + encodeURIComponent(item.id)}>{displayTitle}</Link></h3>
        </div>
        <div className="news-list-related">
          {relatedInstruments.length > 0
            ? relatedInstruments.map((instrument) => <Link className="symbol-link" key={instrument.exchange + instrument.symbol} to={'/stocks/' + encodeURIComponent(instrument.exchange) + '/' + encodeURIComponent(instrument.symbol)}>{instrument.symbol} {instrument.name}</Link>)
            : item.symbols.length > 0
              ? item.symbols.map((symbol) => <span className="symbol-link" key={symbol}>{symbol}</span>)
              : <span className="small-note">未指定標的</span>}
        </div>
      </article>
    )
  }

  return (
    <article className="panel news-card news-detail-card" data-testid="news-detail-card">
      <div className="news-meta"><span>{newsCategoryLabel(item)}</span><span>{newsSourceLabel(item.source_name)}</span><span>{confidenceLabel}</span></div>
      <ProductTimeSummary time={item.product_time} news fallbackDate={eventDate} />
      <div className="news-detail-meta"><span>影響：{impactLabel}</span></div>
      <div className="news-detail-body"><p>{item.summary ?? '官方資料未提供公告內容。'}</p></div>
      {item.time_consistency === 'conflict' && <div className="warning-box">資料集事件日期與公告內容提及日期不一致，時間待人工核實。</div>}
      {relatedInstruments.length > 0 ? (
        <div className="tag-list">{relatedInstruments.map((instrument) => <Link className="tag symbol-tag" key={instrument.exchange + instrument.symbol} to={'/stocks/' + encodeURIComponent(instrument.exchange) + '/' + encodeURIComponent(instrument.symbol)}>{instrument.symbol} {instrument.name}</Link>)}</div>
      ) : item.symbols.length > 0 ? <div className="tag-list">{item.symbols.map((symbol) => <span className="tag" key={symbol}>{symbol}</span>)}</div> : null}
      {visibleThemes.length > 0 && <div className="tag-list">{visibleThemes.map((theme) => <span className="tag" key={theme.theme_id}>{groupDisplayName(theme.display_name)}</span>)}</div>}
      <div className="news-source">
        {item.source.url && item.source.url_kind === 'feed'
          ? <a href={item.source.url} target="_blank" rel="noreferrer">查看官方公告資料集</a>
          : '官方公告資料集連結未提供'}
      </div>
       <details className="technical-details"><summary>技術資訊</summary><div>來源類型：官方公告／資料集</div><div>收錄時間：{formatProductTimeRole(item.product_time, 'collected_at')}</div><div>資料日：{formatTaiwanDateTime(item.provenance.data_as_of, true)}</div>{displayTitle !== item.title && <div>原始標題：{item.title}</div>}<div>原始資料識別碼：{item.provenance.raw_payload_id ?? '—'} · 事件識別碼：{item.provenance.event_id ?? '—'}</div><div>來源位置：{item.provenance.endpoint ?? '—'}</div></details>
    </article>
  )
}

function NewsDetailPage() {
  const { newsId = '' } = useParams()
  const query = useQuery({ queryKey: ['news-detail', newsId], queryFn: () => getNewsDetail(newsId), enabled: Boolean(newsId) })
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page"><Link to="/news" className="back-link">← 回到新聞</Link><PageTitle eyebrow="官方公告詳情" title={officialEventDisplayTitle(query.data.title)} description="此頁顯示官方事件的完整摘要與可稽核來源；國際與媒體新聞尚未接入。" /><ProductNewsCard item={query.data} detail /></div>}</QueryState>
}

function taipeiObservationDate(): string {
  const parts = new Intl.DateTimeFormat('en', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const part = (type: string) => parts.find((value) => value.type === type)?.value ?? ''
  return `${part('year')}-${part('month')}-${part('day')}`
}

function focusUnavailableMessage(data: OfficialEventFocusData): string {
  if (data.reasons.includes('event_memory_capture_missing')) return data.can_capture ? '尚未取得本次官方原件。可按「首次取得官方原件」進行一次觀測。' : '此截止日期尚無可用原件；過往日期不能以今日取得的資料補成歷史觀測。'
  if (data.reasons.includes('event_observation_after_cutoff')) return '已取得原件的觀測日晚於截止日期，本清單排除該次觀測。'
  if (data.reasons.includes('event_cutoff_before_current_observation')) return '過往截止日期且無可用原件，未執行取得。'
  if (data.reasons.some((reason) => reason === 'event_capture_not_enabled' || reason === 'event_capture_configuration_invalid')) return '官方事件原件取得尚未啟用。'
  if (data.reasons.includes('event_capture_in_progress')) return '官方原件正在取得，完成後可讀取已取得原件。'
  return '本次官方原件未通過來源或內容驗證，關注清單暫不可用。'
}

export function trimOfficialEventSearch(value: string): string {
  // Fixed Python str.strip whitespace set, shared with the API's q contract.
  return value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu, '')
}

export function officialEventFocusReturnPath(params: URLSearchParams): string | null {
  if (params.get('from') !== 'official-events') return null
  const asOf = params.get('focus_as_of') ?? ''
  const q = params.get('focus_q') ?? ''
  if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf) || asOf.startsWith('0000-') || Array.from(q).length > 100) return null
  const instant = new Date(`${asOf}T00:00:00Z`)
  if (!Number.isFinite(instant.getTime()) || instant.toISOString().slice(0, 10) !== asOf) return null
  const query = new URLSearchParams({ as_of: asOf, q: trimOfficialEventSearch(q) })
  return `/?${query.toString()}#official-event-focus-title`
}

export function OfficialEventFocusPanel() {
  const [searchParams, setSearchParams] = useSearchParams()
  const asOf = searchParams.get('as_of') || taipeiObservationDate()
  const q = searchParams.get('q') ?? ''
  const [draft, setDraft] = useState(asOf)
  const [searchDraft, setSearchDraft] = useState(q)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [capturing, setCapturing] = useState(false)
  const [captureError, setCaptureError] = useState<{ key: string; message: string } | null>(null)
  const queryClient = useQueryClient()
  const queryKey = ['official-event-focus', asOf, q]
  const requestKey = JSON.stringify(queryKey)
  const query = useQuery({ queryKey, queryFn: () => getOfficialEventFocus(asOf, q), retry: false, refetchOnWindowFocus: false, placeholderData: undefined })
  useEffect(() => { setDraft(asOf); setSearchDraft(q); setSearchError(null); setCaptureError(null) }, [asOf, q])
  const applySearch = (value: string) => {
    if (Array.from(value).length > 100) { setSearchError('搜尋最多 100 個字元。'); return }
    setSearchError(null)
    const next = new URLSearchParams(searchParams)
    next.set('as_of', asOf)
    const normalized = trimOfficialEventSearch(value)
    if (normalized) next.set('q', normalized); else next.delete('q')
    setSearchDraft(normalized)
    setSearchParams(next)
  }
  const capture = async () => {
    setCapturing(true); setCaptureError(null)
    try { queryClient.setQueryData(queryKey, await captureOfficialEventFocus(asOf, q)) }
    catch (error) { setCaptureError({ key: requestKey, message: error instanceof Error ? error.message : '取得失敗' }) }
    finally { setCapturing(false) }
  }
  const captureMessage = captureError?.key === requestKey ? captureError.message : null
  const data = query.data
  const licenseEvidence = data?.attribution?.evidence.find((item) => item.url === 'https://data.gov.tw/license')
  return <section className="panel official-event-focus" aria-labelledby="official-event-focus-title">
    <div className="section-head overview-head"><div><div className="eyebrow">本次觀測 · 臺灣證券交易所</div><h2 id="official-event-focus-title">官方事件關注</h2></div><span className="small-note">依代碼排序</span></div>
    <p className="small-note">本次已觀測的除權息事件供查閱；未來生效日期保留。研究條件待補，事件不表示價格影響或買賣建議。</p>
    <form className="overview-cutoff-control" onSubmit={(event) => { event.preventDefault(); if (!draft) return; const next = new URLSearchParams(searchParams); next.set('as_of', draft); setSearchParams(next) }}>
      <label htmlFor="focus-observation-cutoff">觀測截止日期</label><input id="focus-observation-cutoff" type="date" required value={draft} onInput={(event) => setDraft(event.currentTarget.value)} onChange={(event) => setDraft(event.currentTarget.value)} />
      <button type="submit" className="secondary-button" disabled={capturing}>套用截止</button>
      <button type="button" className="secondary-button" disabled={capturing || query.isFetching} onClick={() => void query.refetch()}>讀取已取得原件</button>
      <button type="button" className="secondary-button" disabled={capturing || query.isFetching || !data?.can_capture || data.cache_present} onClick={() => void capture()}>{capturing ? '取得中…' : '首次取得官方原件'}</button>
    </form>
    <form className="overview-cutoff-control focus-search-control" onSubmit={(event) => { event.preventDefault(); applySearch(searchDraft) }}>
      <label htmlFor="focus-search">搜尋原件代碼或名稱</label><input id="focus-search" type="search" value={searchDraft} placeholder="輸入代碼或名稱片段" aria-describedby="focus-search-help" aria-invalid={Boolean(searchError)} onChange={(event) => setSearchDraft(event.currentTarget.value)} />
      <button type="submit" className="secondary-button">搜尋</button><button type="button" className="secondary-button" onClick={() => applySearch('')}>清除搜尋</button>
    </form>
    <p id="focus-search-help" className="small-note">搜尋本次官方原件的代碼與名稱，不分大小寫；最多 100 個字元，僅比對連續文字。</p>
    {searchError && <div className="warning-box" role="status">{searchError}</div>}
    <div className="small-note focus-observation-note">截止 {asOf}（台北觀測日含當日）{data?.observed_date ? ` · 原件觀測日 ${data.observed_date}` : ''} · 原件只在本次服務執行期間保留；服務重啟後須重新取得，不自動更新。</div>
    {query.isLoading && <div className="empty">讀取關注清單…</div>}
    {(query.error || captureMessage) && <div className="warning-box" role="status">讀取或取得失敗：{captureMessage || (query.error instanceof Error ? query.error.message : '請稍後再試')}</div>}
    {data?.status === 'unavailable' && <div className="empty focus-unavailable" role="status">{focusUnavailableMessage(data)}</div>}
    {data?.status === 'available' && <>
      <div className="small-note focus-count">本次原件 {data.candidate_count ?? 0} 筆事件 · {data.total} 檔標的；{data.search_query ? `搜尋「${data.search_query}」` : '全部原件標的'}符合 {data.matched} 檔，顯示 {data.displayed} 檔{data.truncated ? `（已截斷，最多 ${data.limit} 檔）` : ''}。此順序僅供閱讀。</div>
      {data.items.length === 0 ? <div className="empty focus-empty" role="status">{data.total === 0 ? '本次官方原件為零筆。這不表示市場沒有事件，也不代表完整市場範圍。' : '本次原件沒有符合搜尋的標的；可清除搜尋查看本次清單。這不表示市場沒有事件。'}</div> : <div className="focus-grid">{data.items.map((item) => <article className="focus-card" key={`${item.exchange}:${item.symbol}`}>
        <div className="position-head"><strong>{item.symbol} {item.company_name}</strong><span>{item.exchange}</span></div>
        <div className="table-wrap focus-event-table"><table><caption>本次觀測事件</caption><thead><tr><th>生效日期</th><th>官方事件類型</th></tr></thead><tbody>{item.events.map((event) => <tr key={`${event.event_date}:${event.kind}:${event.row_ordinal}`}><td>{event.event_date}</td><td>{event.label}</td></tr>)}</tbody></table></div>
        <div className="small-note">研究條件：待補</div>
        {item.stock_page_available && item.detail_url ? <Link className="text-link focus-stock-link" to={item.detail_url}>查看個股總覽（相同截止日期）</Link> : <div className="small-note focus-catalogue-missing">個股頁尚無此標的</div>}
        <details className="technical-details"><summary>事件原件值</summary>{item.events.map((event) => <div key={event.row_ordinal}>原件列 {event.row_ordinal}：Date {event.source_date} · Exdividend {event.source_classification} · Name {event.company_name}</div>)}</details>
      </article>)}</div>}
    </>}
    {data && <details className="technical-details overview-provenance focus-source-details"><summary>來源、授權與驗證範圍</summary>
      <div>來源資料集：TWSE TWT48U。發布時間、首次可得時間、修訂歷史：未知；歷史時點資料與完整市場範圍尚未驗證。</div>
      {data.provenance && <><div>來源：{data.provenance.source_id} · 版本 {data.provenance.source_version}</div><div>觀測時間：{formatTaiwanDateTime(data.provenance.captured_at)} · 請求開始 {formatTaiwanDateTime(data.provenance.request_started_at)}</div><div>原件來源：<a href={data.provenance.endpoint} target="_blank" rel="noreferrer">臺灣證券交易所原始資料</a></div><div>Body SHA-256：{data.provenance.body_sha256}</div><div>Receipt SHA-256：{data.provenance.receipt_sha256}</div><div>Registry：{data.provenance.registry_version} · {data.provenance.manifest_digest}</div></>}
      {data.attribution && <><div>資料提供者：{data.attribution.owner.name}</div><div>使用條款：{licenseEvidence ? <a href={licenseEvidence.url} target="_blank" rel="noreferrer">{data.attribution.terms.value}</a> : data.attribution.terms.value}</div><details><summary>來源與用途證據</summary><pre>{JSON.stringify({ evidence: data.attribution.evidence, purpose_evidence: data.attribution.purpose_evidence, summarize_decision: data.summarize_decision, runtime_conditions: data.runtime_condition_receipts, summary_conditions: data.summary_condition_receipts }, null, 2)}</pre></details></>}
      {data.reasons.length > 0 && <div>驗證狀態：{data.reasons.join('、')}</div>}
    </details>}
  </section>
}

export function PriceLotFocusPanel() {
  const [params, setParams] = useSearchParams()
  const asOf = params.get('as_of') ?? '', minLots = params.get('min_lots') ?? ''
  const direction = params.get('day_move') ?? 'all', dayMove = validPriceFocusDayMove(direction) ? direction : 'all'
  const minTurnover = params.get('min_turnover') ?? '0'
  const minRangePct = params.get('min_range_pct') ?? '0'
  const [dateDraft, setDateDraft] = useState(asOf), [lotsDraft, setLotsDraft] = useState(minLots)
  const [moveDraft, setMoveDraft] = useState(direction)
  const [turnoverDraft, setTurnoverDraft] = useState(minTurnover)
  const [rangeDraft, setRangeDraft] = useState(minRangePct)
  const [formError, setFormError] = useState<string | null>(null), [busy, setBusy] = useState(false)
  const [captureError, setCaptureError] = useState<{ key: string; message: string } | null>(null)
  const pending = useRef(false), currentKey = useRef('')
  const key = JSON.stringify([asOf, minLots, direction, minTurnover, minRangePct]); currentKey.current = key
  const draftsValid = validFocusDate(dateDraft) && minLotsShares(lotsDraft) !== null && validPriceFocusDayMove(moveDraft) && minTurnoverValue(turnoverDraft) !== null && minRangeMilliPct(rangeDraft) !== null
  const enabled = validPriceFocusParams(params) && draftsValid
  const queryKey = ['price-lot-focus', asOf, minLots, direction, minTurnover, minRangePct]
  const client = useQueryClient()
  const query = useQuery({ queryKey, queryFn: () => getPriceLotFocus(asOf, minLots, dayMove, minTurnover, minRangePct), enabled, retry: false, refetchOnWindowFocus: false, placeholderData: undefined })
  useEffect(() => { setDateDraft(asOf); setLotsDraft(minLots); setMoveDraft(direction); setTurnoverDraft(minTurnover); setRangeDraft(minRangePct); setFormError(null); setCaptureError(null) }, [asOf, minLots, direction, minTurnover, minRangePct])
  const apply = (event: FormEvent) => {
    event.preventDefault()
    if (!validFocusDate(dateDraft) || minLotsShares(lotsDraft) === null || !validPriceFocusDayMove(moveDraft)) { setFormError('請選擇有效日期與單日方向，並輸入非負成交張數；最多三位小數，上限 9,223,372,036,854,775.807 張。'); return }
    if (minTurnoverValue(turnoverDraft) === null) { setFormError('最小成交金額須為非負整數元，上限 9,223,372,036,854,775,807 元；請勿使用逗號、小數或前導零。'); return }
    if (minRangeMilliPct(rangeDraft) === null) { setFormError('最小本日振幅須為非負百分比，最多三位小數，上限 9,223,372,036,854,775.807%；請勿使用前導零、符號或逗號。'); return }
    const next = new URLSearchParams(params); next.set('as_of', dateDraft); next.set('min_lots', lotsDraft); next.set('day_move', moveDraft); next.set('min_turnover', turnoverDraft); next.set('min_range_pct', rangeDraft)
    setFormError(null); setParams(next)
  }
  const capture = async () => {
    if (pending.current || !enabled) return
    pending.current = true; setBusy(true); setCaptureError(null)
    try {
      const data = await capturePriceLotFocus(asOf, minLots, dayMove, minTurnover, minRangePct)
      client.setQueryData(queryKey, data)
    } catch (error) {
      if (currentKey.current === key) setCaptureError({ key, message: error instanceof Error ? error.message : '取得失敗' })
    } finally { pending.current = false; setBusy(false) }
  }
  const accepted = enabled && validPriceLotFocus(query.data, asOf, minLots, dayMove, minTurnover, minRangePct)
  const data = accepted ? query.data : undefined
  return <section className="panel official-event-focus" aria-labelledby="price-lot-focus-title">
    <div className="section-head overview-head"><div><div className="eyebrow">指定來源日 · 上櫃普通股</div><h2 id="price-lot-focus-title">成交張數關注</h2></div><span className="small-note">依代碼排序</span></div>
    <p className="small-note">明選來源日、最小成交張數、成交金額、單日方向與本日振幅，查看同時符合條件的標的。10/5 已核 3105 穩懋、6488 環球晶；2026-10-06 本次政策支持 3105 穩懋、3293 鈊象、5274 信驊、5347 世界、6488 環球晶、6510 精測、8069 元太七股，既有六股、五股、四股、三股及兩股政策仍可讀取。每次服務只取得一份指定日期原件，依本次已核範圍篩選。此順序供閱讀，不是排名或買賣建議。單日方向以當日開盤比較，不表示相對前一日的漲跌。本日振幅（%）＝100×(最高−最低)/開盤，以原件十進位值精確比較門檻。</p>
    <form className="overview-cutoff-control" onSubmit={apply}>
      <label htmlFor="price-focus-date">來源日期</label><input id="price-focus-date" type="date" required value={dateDraft} onChange={(event) => setDateDraft(event.currentTarget.value)} />
      <label htmlFor="price-focus-min-lots">最小成交張數</label><input id="price-focus-min-lots" type="text" inputMode="decimal" required value={lotsDraft} placeholder="例如 20000，最多三位小數" onChange={(event) => setLotsDraft(event.currentTarget.value)} />
      <label htmlFor="price-focus-min-turnover">最小成交金額（元）</label><input id="price-focus-min-turnover" type="text" inputMode="numeric" required value={turnoverDraft} placeholder="例如 25000000000，整數元" onChange={(event) => setTurnoverDraft(event.currentTarget.value)} />
      <label htmlFor="price-focus-day-move">單日方向（收盤相對開盤）</label><select id="price-focus-day-move" value={moveDraft} onChange={(event) => setMoveDraft(event.currentTarget.value)}>{Object.entries(priceFocusDayMoveLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <label htmlFor="price-focus-min-range">最小本日振幅（%）</label><input id="price-focus-min-range" type="text" inputMode="decimal" required value={rangeDraft} placeholder="例如 6.000，最多三位小數" onChange={(event) => setRangeDraft(event.currentTarget.value)} />
      <button type="submit" className="secondary-button" disabled={busy || !draftsValid}>套用條件</button>
      <button type="button" className="secondary-button" disabled={!enabled || busy || query.isFetching} onClick={() => void query.refetch()}>讀取已取得原件</button>
      <button type="button" className="secondary-button" disabled={!data?.can_capture || busy || query.isFetching} onClick={() => void capture()}>{busy ? '取得中…' : '首次載入官方單日行情'}</button>
    </form>
    {formError && <div className="warning-box" role="status">{formError}</div>}
    {!enabled && <div className="empty" role="status">請設定有效且不重複的來源日期、成交張數、成交金額、單日方向與本日振幅條件；尚未查詢候選。</div>}
    {enabled && query.isLoading && <div className="empty">讀取成交張數關注…</div>}
    {(query.error || captureError?.key === key) && <div className="warning-box" role="status">{captureError?.key === key ? captureError.message : '關注清單讀取失敗。'}</div>}
    {enabled && query.data && !accepted && <div className="warning-box" role="status">來源、日期或條件回應未通過核對，關注清單暫不可用。</div>}
    {data?.status === 'unavailable' && <div className="empty focus-unavailable" role="status">{data.reasons.includes('price_memory_capture_missing') ? '尚未取得指定日期原件，候選數未知；可首次載入官方單日行情。' : '此日期或來源資料不足，候選數未知。'}這與符合條件的零候選不同。</div>}
    {data?.status === 'available' && <>
      <div className="small-note focus-count">來源日期 {data.as_of} · 最小 {minLots} 張 · 金額 ≥ {exactTurnoverText(minTurnover)} 元 · 方向 {priceFocusDayMoveLabels[dayMove]} · 振幅 ≥ {minRangePct}% · 已核 {data.reads.length} 股，符合 {data.count} 檔。</div>
      {data.count === 0 ? <div className="empty focus-empty" role="status">已核 {data.reads.length} 股原件，沒有同時符合最小 {minLots} 張、成交金額 {exactTurnoverText(minTurnover)} 元、方向「{priceFocusDayMoveLabels[dayMove]}」與本日振幅 {minRangePct}% 的標的；這是此範圍的零候選。</div> : <div className="focus-grid">{data.items.map((item) => {
        const memory = data.reads.find((read) => read.instrument.symbol === item.symbol)!.price_memory!
        return <article className="focus-card" key={`${item.exchange}:${item.symbol}`}>
          <div className="position-head"><strong>{item.symbol} {item.name}</strong><span>{item.exchange}</span></div>
          <p>成交 {formatCanonicalShareLots(item.volume_exact, 1, true)} 張 ≥ 門檻 {minLots} 張</p>
          <p>成交金額 {exactTurnoverText(item.turnover_exact)} 元 ≥ 門檻 {exactTurnoverText(minTurnover)} 元</p>
          <p>{priceFocusDayMoveLabels[item.day_move]}：開盤 {item.open_exact} 元／股 · 收盤 {item.close_exact} 元／股</p>
          <p>本日振幅 約 {approximateRangePct(item.open_exact, item.high_exact, item.low_exact)}% ≥ 門檻 {item.min_range_pct}%：100×(最高 {item.high_exact} − 最低 {item.low_exact})/開盤 {item.open_exact}；價格單位元／股，門檻以精確值核對。</p>
          <div className="small-note">來源日 {item.source_date} · 版本 {item.source_version}</div>
          <Link className="text-link focus-stock-link" to={item.detail_url}>查看個股總覽（相同截止日期）</Link>
          <details className="technical-details" style={{ overflowWrap: 'anywhere' }}><summary>原股、來源與驗證範圍</summary>
            <div>原件成交股數：{formatCanonicalShares(item.volume_exact, 1, true)} 股 · 原件列 {memory.latest!.row_ordinal}</div>
            <div>門檻：{data.min_shares} 股 · 取得時間：{formatTaiwanDateTime(memory.provenance!.captured_at)}</div>
            <a href={memory.provenance!.endpoint} target="_blank" rel="noreferrer">櫃買中心原始資料</a>
            <div>Body SHA-256：{memory.provenance!.body_sha256}</div><div>Receipt SHA-256：{memory.provenance!.receipt_sha256}</div>
            <div>{memory.attribution!.owners.join('、')} · {memory.attribution!.dataset_name} · <a href={memory.attribution!.license_url} target="_blank" rel="noreferrer">{memory.attribution!.license}</a></div>
            <div>發布、首次可得及修訂時間未知；取得時間不代表發布時間。僅單日、非歷史時點資料；原件只保留在本次服務記憶體，重啟後需重新取得。</div>
          </details>
        </article>
      })}</div>}
    </>}
    <p className="small-note">所選日期是原件的來源日期，不表示今日即時資料；未驗全市場、研究條件、Signal、Plan 或保存。</p>
  </section>
}

export function TodayPage() {
  const query = useQuery<Dashboard>({ queryKey: ['dashboard'], queryFn: getDashboard })
  const homeActions = Array.from(new Map(
    [...(query.data?.actions ?? []), ...(query.data?.candidates ?? [])]
      .filter((action) => action.action_state !== 'data_insufficient' || action.held === true || action.position_quantity_status === 'unknown')
      .map((action) => [`${action.instrument.exchange}:${action.instrument.symbol}:${action.as_of ?? ''}`, action] as const),
  ).values())
  return (
    <div className="page">
          <section className="hero home-header">
            <div>
              <div className="eyebrow">今日市場</div>
              <h1>今日市場總覽</h1>
              <p>掌握公告、熱門族群與關注標的。</p>
            </div>
            <div className="hero-note"><span>資料截至</span><strong>{formatTaiwanDateTime(query.data?.as_of, true)}</strong><small>{query.data?.market.source_label ?? sourceLabel(query.data?.market.source)}</small></div>
          </section>
          <PriceLotFocusPanel />
          <OfficialEventFocusPanel />
    <QueryState loading={query.isLoading} error={query.error}>
      {query.data && (
        <>
          <div className={'source-banner ' + query.data.mode}>
            <strong>{query.data.mode === 'official' ? '官方單日快照' : query.data.mode === 'official_partial' ? '官方單日快照（資料仍待補）' : '尚無官方快照'}</strong>
            <QualityBadge kind="market" status={query.data.data_quality.latest_run} /><details className="data-explanation"><summary>資料說明</summary><span>{query.data.scan_scope_label ?? '官方標的範圍；只有研究資料足夠的項目可進入行動摘要'} · {query.data.market.instruments.toLocaleString()} 檔標的 · {query.data.market.bars.toLocaleString()} 筆日行情 · {(query.data.themes ?? []).filter((theme) => theme.qualified).length.toLocaleString()} 個族群摘要 · {homeActions.length.toLocaleString()} 筆行動摘要</span></details>
          </div>
          <section className="section-head"><div><div className="eyebrow">市場基礎層 · 重大事件</div><h2>今日市場／重大事件</h2></div><Link to="/news" className="text-link">查看全部新聞</Link></section>
          {query.data.news?.length ? <div className="news-list">{query.data.news.slice(0, 3).map((item) => <ProductNewsCard key={item.id} item={item} />)}</div> : <div className="empty panel">市場新聞區尚無可顯示內容；官方除權息事件請見上方「官方事件關注」。</div>}
          <section className="section-head"><div><div className="eyebrow">族群發現</div><h2><Term id="hot_group">熱門族群</Term></h2></div><Link to="/themes" className="text-link">查看完整排行</Link></section>
          {query.data.themes?.some((theme) => theme.qualified) ? <div className="group-grid">{query.data.themes.filter((theme) => theme.qualified).slice(0, 5).map((theme) => <ThemeCard key={theme.theme_id} theme={theme} />)}</div> : <div className="empty panel">{query.data.empty_states?.themes ?? '目前沒有足以成立的熱門族群。'}</div>}
          <section className="section-head"><div><div className="eyebrow">熱門候選／使用者行動</div><h2>關注標的</h2></div><Link to="/actions" className="text-link">查看行動中心</Link></section>
          {homeActions.length ? <div className="action-grid">{homeActions.slice(0, 6).map((action) => <CompactActionCard key={action.instrument.exchange + action.instrument.symbol + (action.as_of ?? '')} action={action} />)}</div> : <div className="empty panel">{query.data.empty_states?.actions ?? '目前沒有可顯示的行動摘要。'}</div>}
          {query.data.data_quality.error && <div className="warning-box">官方擷取警告：{query.data.data_quality.error}</div>}
        </>
      )}
    </QueryState>
    </div>
  )
}

function StatCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="stat-card"><div className="muted">{label}</div><div className="stat-value">{value}</div><div className="stat-detail">{detail}</div></div>
}

function NewsPage() {
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageCursors, setPageCursors] = useState<Array<string | undefined>>([undefined])
  const [category, setCategory] = useState('')
  const [sourceKind, setSourceKind] = useState('')
  const [timeConsistency, setTimeConsistency] = useState('')
  const cursor = pageCursors[page - 1]
  const query = useQuery({
    queryKey: ['news', { search, cursor, category, sourceKind, timeConsistency }],
    queryFn: () => getNews({ q: search || undefined, cursor, limit: 20, category: category || undefined, source_kind: sourceKind || undefined, time_consistency: timeConsistency || undefined }),
  })
  const resetPage = () => { setPage(1); setPageCursors([undefined]) }
  const submit = (value = draft.trim()) => { setSearch(value); resetPage() }
  const clear = () => { setDraft(''); setSearch(''); resetPage() }
  const changeFilter = (setter: (value: string) => void, value: string) => { setter(value); resetPage() }
  const nextPage = (nextCursor: string) => { setPageCursors((current) => [...current.slice(0, page), nextCursor]); setPage(page + 1) }
  const previousPage = () => { if (page > 1) setPage(page - 1) }
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page">
     <PageTitle eyebrow="最新官方公告" title="新聞" description="目前為官方公告列表；列表只顯示事件日或發布日，完整時間與衝突說明請進入詳情。">
      <div className="filter-row"><SearchBox draft={draft} query={search} placeholder="搜尋標題、摘要、來源或代號" onDraftChange={setDraft} onSubmit={submit} onClear={clear} /><select className="filter-select" value={category} onChange={(event) => changeFilter(setCategory, event.target.value)}><option value="">全部類別</option><option value="company">公司事件</option><option value="taiwan">台灣官方事件</option></select><select className="filter-select" value={sourceKind} onChange={(event) => changeFilter(setSourceKind, event.target.value)}><option value="">一般公告</option><option value="official_disclosure">官方公告／資料</option></select><select className="filter-select" value={timeConsistency} onChange={(event) => changeFilter(setTimeConsistency, event.target.value)}><option value="">全部日期狀態</option><option value="conflict">日期待確認</option></select></div>
    </PageTitle>
     {query.data.items.length ? <div className="news-list">{query.data.items.map((item) => <ProductNewsCard key={item.id} item={item} />)}</div> : <div className="empty panel">沒有符合條件的官方事件。</div>}
     <CursorControls meta={query.data.meta} page={page} itemCount={query.data.items.length} onNext={nextPage} onPrevious={previousPage} onReset={resetPage} />
  </div>}</QueryState>
}

function ThemesPage() {
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const query = useQuery({ queryKey: ['themes', { search, page }], queryFn: () => getThemes({ q: search || undefined, page, page_size: 20, only_qualified: true }) })
  const submit = (value = draft.trim()) => { setSearch(value); setPage(1) }
  const clear = () => { setDraft(''); setSearch(''); setPage(1) }
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page">
    <PageTitle eyebrow="族群發現" title="熱門族群" description="只有資料完整、有效成員至少 3 檔且使用 加權指數 基準的族群會進入排行；ETF 獨立分榜。"><SearchBox draft={draft} query={search} placeholder="搜尋族群名稱" onDraftChange={setDraft} onSubmit={submit} onClear={clear} /></PageTitle>
    {query.data.items.length ? <div className="group-grid">{query.data.items.map((theme) => <ThemeCard key={theme.theme_id} theme={theme} />)}</div> : <div className="empty panel">目前沒有成立的熱門族群。研究資料尚未齊備、成員少於 3 檔或缺少 加權指數 基準的族群不會排名。</div>}
    <DirectoryPagination meta={query.data.meta} onPageChange={setPage} />
  </div>}</QueryState>
}

function ThemeCandidateTags({ theme }: { theme: ThemeDirectoryRow }) {
  const rawSymbols = theme.candidate_symbols
  const symbols = Array.isArray(rawSymbols) ? rawSymbols.filter((symbol) => typeof symbol === 'string' && symbol.trim()) : []
  const candidates = theme.candidate_instruments
  const ids = new Set<string>()
  const pairs = new Set<string>()
  const verified = theme.public_candidate_identity_version === 'instrument-id-string-v1'
    && Array.isArray(rawSymbols) && symbols.length === rawSymbols.length
    && Array.isArray(candidates) && candidates.length <= 4 && candidates.length === symbols.length
    && candidates.every((candidate, index) => {
      if (!candidate || typeof candidate !== 'object') return false
      const { instrument_id: id, exchange, symbol } = candidate
      if (typeof id !== 'string' || !/^[1-9][0-9]*$/.test(id)
        || id.length > 19 || (id.length === 19 && id > '9223372036854775807')
        || typeof exchange !== 'string' || !exchange.trim()
        || typeof symbol !== 'string' || symbol !== symbols[index]) return false
      const pair = JSON.stringify([exchange, symbol])
      if (ids.has(id) || pairs.has(pair)) return false
      ids.add(id)
      pairs.add(pair)
      return true
    })
  if (!symbols.length) return <div className="empty">沒有足以顯示的候選股票。</div>
  return <div className="tag-list">{symbols.map((symbol, index) => {
    const candidate = verified ? candidates[index] : null
    return candidate
      ? <Link className="tag symbol-tag" key={`${candidate.instrument_id}:${index}`} to={'/stocks/' + encodeURIComponent(candidate.exchange) + '/' + encodeURIComponent(candidate.symbol)}>{candidate.exchange} {symbol}</Link>
      : <span className="tag" key={`legacy:${index}`}>{symbol}</span>
  })}</div>
}

function ThemePage() {
  const { themeId = '' } = useParams()
  const [memberPage, setMemberPage] = useState(1)
  const theme = useQuery({ queryKey: ['theme', themeId], queryFn: () => getTheme(themeId), enabled: Boolean(themeId) })
  const members = useQuery({ queryKey: ['theme-members', themeId, memberPage], queryFn: () => getThemeMembers(themeId, { page: memberPage, page_size: 30, sort: 'price' }), enabled: Boolean(themeId) })
  if (theme.isLoading || members.isLoading) return <Loading />
  if (theme.error) return <ErrorBox error={theme.error} />
  if (members.error) return <ErrorBox error={members.error} />
  if (!theme.data || !members.data) return null
  const item = theme.data.theme
  const metricEntries = Object.entries(item.metrics).filter(([key, value]) => themeMetricLabel(key) && value != null)
  const memberDataAsOf = typeof members.data.meta?.data_as_of === 'string' ? members.data.meta.data_as_of : theme.data.data_as_of
  const needsTemporaryVerification = isTemporaryIndustryTheme(item)
  return <div className="page">
    <Link to="/themes" className="back-link">← 回到族群</Link>
    <PageTitle eyebrow={categoryLabel(item.category)} title={needsTemporaryVerification ? '產業名稱待核實（既有分類）' : groupDisplayName(item.display_name)} description={needsTemporaryVerification ? TEMPORARY_INDUSTRY_GROUP_NOTICE : item.description} />
     <div className="source-banner"><strong>{needsTemporaryVerification ? '關聯待核實' : item.qualified ? '可排名' : '不排名'}</strong><span>{needsTemporaryVerification ? TEMPORARY_INDUSTRY_GROUP_NOTICE : item.qualified ? item.why_hot.join(' · ') : item.missing_reasons.join('；')}</span>{needsTemporaryVerification ? <span className="pill ambiguous">僅供查閱</span> : item.qualified ? <span className="pill complete">族群評分資料完整</span> : <QualityBadge kind="theme" status={item.data_quality} />}</div>
     {needsTemporaryVerification && <details className="technical-details"><summary>既有資料</summary><div>既有名稱：{item.display_name}</div><div>既有識別碼：{item.theme_id}</div><div>既有成員數：{item.eligible_members}</div></details>}
     <div className="detail-grid two-panels">
       <div className="panel"><h2>市場指標</h2>{item.qualified && metricEntries.length ? <div className="metric-list">{metricEntries.map(([key, value]) => <div className="metric-row" key={key}><span>{themeMetricLabel(key)}（%）</span><b>{key.startsWith('relative_return_') ? formatSignedPercent(value) : key === 'breadth' ? formatPercent(value, 0) : formatPercent(value)}</b></div>)}</div> : <div className="empty">{item.qualified ? '尚無已命名且可核實的市場指標。' : item.data_quality === 'insufficient_data' ? '資料不足，尚未完成評估。' : '尚未評估；不代表條件不成立。'}</div>}</div>
       <div className="panel"><h2>候選股票</h2><ThemeCandidateTags theme={item} /><div className="small-note">評分日期 {formatTaiwanDateTime(item.trading_date, true)} · 基準：<Term id="taiex">加權指數</Term></div></div>
    </div>
    <section className="section-head"><div><div className="eyebrow">{needsTemporaryVerification ? '既有成員 · 待重新核實' : '有效成員'}</div><h2>{needsTemporaryVerification ? '既有族群成員' : '族群成員'}</h2></div></section>
     <div className="small-note">成員資料截至 {formatTaiwanDateTime(memberDataAsOf, true)}</div>
     {members.data.items.length ? <ThemeMemberTable rows={members.data.items} /> : <div className="empty panel">此日期沒有有效成員。</div>}
     {members.data.meta && <DirectoryPagination meta={members.data.meta} onPageChange={setMemberPage} />}
  </div>
}

function StockTable({ rows }: { rows: StockDirectoryRow[] }) {
  if (!rows.length) return <div className="empty panel">沒有符合條件的股票。</div>
  return <div className="table-wrap"><p className="small-note">單位：價格為各標的報價幣別的元，指數為點。空白表示未提供資料或數值待核實。</p><table><thead><tr><th>代號</th><th>名稱</th><th>交易所</th><th>類型</th><th>最近收盤</th><th>目前研究動作</th><th>策略判斷資料</th></tr></thead><tbody>{rows.map((row) => {
    const instrument = row.instrument ?? row
    return <tr key={instrument.exchange + instrument.symbol}><td><Link className="symbol-link" to={'/stocks/' + encodeURIComponent(instrument.exchange) + '/' + encodeURIComponent(instrument.symbol)}>{instrument.symbol}</Link></td><td>{instrument.name}</td><td>{marketDisplayLabel(instrument.exchange)}</td><td>{instrumentTypeLabel(instrument.instrument_type)}</td><td className="numeric-cell">{formatTableNumber(row.latest_price ?? row.latest_bar?.close, 2)}</td><td>{stockDirectoryActionLabel(row.action_state, row.action_label_zh)}</td><td><span className="pill">{stockDirectoryQualityLabel(row.data_quality)}</span></td></tr>
  })}</tbody></table></div>
}

function ThemeMemberTable({ rows }: { rows: StockDirectoryRow[] }) {
  if (!rows.length) return <div className="empty panel">沒有符合條件的族群成員。</div>
  return <div className="table-wrap"><p className="small-note">單位：價格為各標的報價幣別的元，指數為點。空白表示未提供資料或數值待核實。</p><table><thead><tr><th>代號</th><th>名稱</th><th>市場</th><th>角色</th><th>收盤</th><th>資料日期</th></tr></thead><tbody>{rows.map((row) => {
    const instrument = row.instrument ?? row
    const stockPath = '/stocks/' + encodeURIComponent(instrument.exchange) + '/' + encodeURIComponent(instrument.symbol)
    return <tr key={instrument.exchange + instrument.symbol}><td><Link className="symbol-link" to={stockPath}>{instrument.symbol}</Link></td><td><Link className="symbol-link" to={stockPath}>{instrument.name}</Link></td><td>{marketDisplayLabel(instrument.exchange)}</td><td>{row.role === 'leader' ? '領先成員' : row.role === 'member' ? '成員' : '角色待核實'}</td><td className="numeric-cell">{formatTableNumber(row.latest_bar?.close ?? row.latest_price, 2)}</td><td>{formatTaiwanDateTime(row.latest_bar?.date ?? row.price_as_of, true)}</td></tr>
  })}</tbody></table></div>
}

function StocksPage() {
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [type, setType] = useState('')
  const [watchlist, setWatchlist] = useState(false)
  const query = useQuery({ queryKey: ['stocks', { search, page, type, watchlist }], queryFn: () => getStocks({ q: search || undefined, page, page_size: 30, instrument_type: type || undefined, watchlist_only: watchlist || undefined }) })
  const submit = (value = draft.trim()) => { setSearch(value); setPage(1) }
  const clear = () => { setDraft(''); setSearch(''); setPage(1) }
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page">
    <PageTitle eyebrow="市場標的目錄" title="個股" description="股票、ETF 與新上市標的分開標示；行動與缺資料優先級只來自已驗證官方快照。">
      <div className="filter-row"><SearchBox draft={draft} query={search} placeholder="搜尋代號或名稱" onDraftChange={setDraft} onSubmit={submit} onClear={clear} /><select className="filter-select" value={type} onChange={(event) => { setType(event.target.value); setPage(1) }}><option value="">全部類型</option><option value="stock">股票</option><option value="etf">ETF</option><option value="ipo">新上市</option></select><label className="check-label"><input type="checkbox" checked={watchlist} onChange={(event) => { setWatchlist(event.target.checked); setPage(1) }} /> 我的自選</label></div>
    </PageTitle>
    {query.data.items.length ? <StockTable rows={query.data.items} /> : <div className="empty panel">沒有符合條件的標的。</div>}
    <DirectoryPagination meta={query.data.meta} onPageChange={setPage} />
  </div>}</QueryState>
}

function StockPage() {
  const { exchange = '', symbol = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const asOf = searchParams.get('as_of') ?? ''
  const lotFocusReturnPath = priceFocusReturnPath(searchParams)
  const focusReturnPath = lotFocusReturnPath ?? officialEventFocusReturnPath(searchParams)
  const [cutoffDraft, setCutoffDraft] = useState(asOf)
  const query = useQuery({ queryKey: ['stock', exchange, symbol, asOf], queryFn: () => getStock(exchange, symbol, asOf || undefined), enabled: Boolean(exchange && symbol) })
  useEffect(() => setCutoffDraft(asOf || query.data?.overview?.as_of || ''), [asOf, query.data?.overview?.as_of])
  const [tab, setTab] = useState<StockTab>('technical')
  const [capturingEvents, setCapturingEvents] = useState(false)
  const [eventRequestFailure, setEventRequestFailure] = useState<{ key: string; reason: string } | null>(null)
  const eventRequestKey = `${exchange}:${symbol}:${asOf}`
  const windowRequestKey = `${exchange}:${symbol}:${asOf}`
  const currentWindowKey = useRef(windowRequestKey)
  currentWindowKey.current = windowRequestKey
  const windowPending = useRef(false)
  const [windowBusyKey, setWindowBusyKey] = useState<string | null>(null)
  const [windowRequestFailure, setWindowRequestFailure] = useState<{ key: string; reason: string } | null>(null)
  const acquireWindows = async () => {
    if (windowPending.current) return
    const requestKey = windowRequestKey
    windowPending.current = true
    setWindowBusyKey(requestKey)
    setWindowRequestFailure(null)
    try {
      const result = await captureInstitutionalWindows(exchange, symbol, asOf || undefined)
      if (currentWindowKey.current !== requestKey) return
      if (result.status === 'unavailable') setWindowRequestFailure({ key: requestKey, reason: result.reasons[0] ?? 'window_capture_failed' })
      await query.refetch()
    } catch {
      if (currentWindowKey.current === requestKey) setWindowRequestFailure({ key: requestKey, reason: 'window_capture_request_failed' })
    } finally {
      windowPending.current = false
      setWindowBusyKey((key) => key === requestKey ? null : key)
    }
  }
  const priceRequestKey = `${exchange}:${symbol}:${asOf}`
  const currentPriceKey = useRef(priceRequestKey)
  currentPriceKey.current = priceRequestKey
  const pricePending = useRef(false)
  const [priceBusyKey, setPriceBusyKey] = useState<string | null>(null)
  const [priceRequestFailure, setPriceRequestFailure] = useState<{ key: string; reason: string } | null>(null)
  const acquirePrice = async () => {
    if (pricePending.current || !priceSourcePins(asOf)) return
    const requestKey = priceRequestKey
    pricePending.current = true
    setPriceBusyKey(requestKey)
    setPriceRequestFailure(null)
    try {
      const result = await captureStockPriceMemory(exchange, symbol, asOf)
      if (currentPriceKey.current !== requestKey) return
      if (result.status !== 'available') setPriceRequestFailure({ key: requestKey, reason: result.reasons[0] ?? 'price_capture_failed' })
      await query.refetch()
    } catch {
      if (currentPriceKey.current === requestKey) setPriceRequestFailure({ key: requestKey, reason: 'price_capture_request_failed' })
    } finally {
      pricePending.current = false
      setPriceBusyKey((key) => key === requestKey ? null : key)
    }
  }
  const acquireEvents = async () => {
    if (capturingEvents) return
    setCapturingEvents(true)
    setEventRequestFailure(null)
    try {
      const result = await captureOfficialEvents(exchange, symbol, asOf || undefined)
      if (result.status === 'unavailable') {
        setEventRequestFailure({ key: eventRequestKey, reason: result.reasons[0] ?? 'event_capture_failed' })
      }
      await query.refetch()
    } catch {
      setEventRequestFailure({ key: eventRequestKey, reason: 'event_capture_request_failed' })
    } finally {
      setCapturingEvents(false)
    }
  }
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorBox error={query.error} />
  if (!query.data) return null
  const data = query.data
  const priceMemory = data.overview?.price_memory
  const priceCutoff = asOf || data.overview?.as_of || null
  const memoryKnown = (!asOf || asOf === data.overview?.as_of) && validStockPriceMemoryRead(priceMemory, data.instrument, priceCutoff)
  const memoryRejected = priceMemory?.status === 'available' && !memoryKnown
  const independent = stockIndependentView(data)
  const finitePrice = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0
  const researchShapeValid = validStockResearchRead(data)
  const researchAction = stockResearchAction(data)
  const finiteValue = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
  const read = data.market_read
  const readShapeValid = read != null && ['known', 'missing', 'invalid'].includes(read.status)
    && Array.isArray(read.invalid_fields) && read.invalid_fields.every((field) => typeof field === 'string')
    && Array.isArray(read.missing_fields) && read.missing_fields.every((field) => typeof field === 'string')
    && read.metadata_fields != null && typeof read.metadata_fields === 'object' && !Array.isArray(read.metadata_fields)
    && Object.values(read.metadata_fields).every((state) => ['known', 'missing', 'invalid'].includes(state))
    && ((read.status === 'missing' && read.candidate_count === 0) || ['adj_close', 'turnover', 'turnover_status', 'turnover_reason', 'data_as_of', 'collected_at', 'raw_payload_id'].every((key) => ['known', 'missing', 'invalid'].includes(read.metadata_fields[key])))
    && Number.isInteger(read.candidate_count) && read.candidate_count! >= 0 && read.candidate_count! <= 120
    && read.window_limit === 120 && Number.isInteger(read.unlocated_count) && read.unlocated_count! >= 0
    && read.verification === 'stored_value_syntax_only'
  const readKnown = read === undefined || (readShapeValid && read.status === 'known'
    && read.candidate_count! >= 1 && read.invalid_fields.length === 0 && read.missing_fields.length === 0 && read.unlocated_count === 0)
  const candidate = data.overview ? data.overview.price.status === 'available' ? data.overview.price.latest : null : data.bars[data.bars.length - 1]
  const candidateRow = data.bars[data.bars.length - 1]
  const candidateRead = candidateRow?.market_read
  const candidateCoreKnown = read === undefined || (candidateRead?.status === 'known' && isValidBar(candidateRow))
  const candidateConflict = read !== undefined && data.overview?.price.status === 'available'
    && (!candidate || candidateRow?.date !== candidate.date || candidateRow?.close !== candidate.close)
  const candidateKnown = candidateCoreKnown && !candidateConflict
  const latestBar = memoryKnown ? priceMemory.latest : !memoryRejected && readKnown && candidateKnown && candidate && finitePrice(candidate.close) ? candidate : undefined
  const previousBar = data.bars.length > 1 ? data.bars[data.bars.length - 2] : undefined
  const legacyPrice = data.decision_summary?.current_price
  const priceConflict = read !== undefined && !data.overview && legacyPrice != null && (!finitePrice(legacyPrice) || legacyPrice !== latestBar?.close)
  const currentPrice = memoryKnown ? priceMemory.latest.close : memoryRejected || !readKnown || priceConflict ? null : data.overview || read !== undefined ? latestBar?.close ?? null : finitePrice(legacyPrice) ? legacyPrice : latestBar?.close ?? null
  const legacyChange = data.decision_summary?.price_change
  const previousKnown = read === undefined || (previousBar?.market_read?.status === 'known' && isValidBar(previousBar) && previousBar.date < candidateRow.date!)
  const calculatedChange = previousKnown && latestBar && finitePrice(latestBar.close) && finitePrice(previousBar?.close) ? latestBar.close - previousBar.close : null
  const changeConflict = read !== undefined && legacyChange != null && (!finiteValue(legacyChange) || legacyChange !== calculatedChange)
  const change = read === undefined ? finiteValue(legacyChange) ? legacyChange : calculatedChange : !changeConflict ? calculatedChange : null
  const priceChange = memoryKnown || data.overview || !readKnown || !candidateKnown || priceConflict ? null : finiteValue(change) ? change : null
  const legacyPercent = data.decision_summary?.price_change_pct
  const calculatedPercent = priceChange != null && finitePrice(previousBar?.close) ? priceChange / previousBar.close : null
  const percentConflict = read !== undefined && legacyPercent != null && (!finiteValue(legacyPercent) || legacyPercent !== calculatedPercent)
  const percent = read === undefined ? finiteValue(legacyPercent) ? legacyPercent : calculatedPercent : !percentConflict ? calculatedPercent : null
  const priceChangePct = !memoryKnown && !data.overview && readKnown && candidateKnown && !priceConflict && finiteValue(percent) && Number.isFinite(percent * 100) ? percent : null
  const fallbackMarketComplete = Boolean(latestBar && typeof latestBar.source === 'string' && !latestBar.source.toLowerCase().includes('fixture'))
  const fallbackResearchStatus = data.decision_summary?.data_quality ?? 'missing'
  const fallbackResearchIncomplete = data.decision_summary?.action_state === 'data_insufficient' || fallbackResearchStatus !== 'complete'
  const hasTemporaryIndustryGroup = data.groups.some((group) => isTemporaryIndustryGroupName(group.name))
  const storedQualitySummary = data.quality_summary ?? {
    market: {
      status: fallbackMarketComplete ? 'complete' : latestBar ? 'partial' : 'missing',
      label: fallbackMarketComplete ? '當日行情來源完整' : '當日行情來源尚未完整',
      as_of: latestBar?.date ?? null,
      missing_fields: latestBar ? [] : ['market_bar'],
      source: latestBar?.source ?? null,
    },
    research: {
      status: fallbackResearchStatus,
      label: fallbackResearchIncomplete ? '策略判斷資料待補' : '策略判斷資料完整',
      as_of: data.decision_summary?.data_cutoff ?? null,
      missing_fields: data.decision_summary?.blocking_reasons ?? [],
      action_state: data.decision_summary?.action_state ?? null,
    },
    instrument: data.instrument.exchange + ':' + data.instrument.symbol,
  }
  const qualitySummary = memoryKnown ? { ...storedQualitySummary, market: {
    status: 'complete', label: `${priceMemory.latest.date} 單日官方行情已核對`, as_of: priceMemory.latest.date,
    missing_fields: [], source: 'tpex',
  } } : storedQualitySummary
  const tabs: Array<{ id: StockTab; label: string }> = [
    { id: 'technical', label: '技術走勢' },
    { id: 'chips', label: '法人籌碼' },
    { id: 'news', label: '新聞與公告' },
    { id: 'research', label: '研究條件' },
    { id: 'data', label: '資料說明' },
  ]
  return <div className="page">
    <Link to={focusReturnPath ?? '/stocks'} className="back-link">{lotFocusReturnPath ? '← 回到成交張數關注（原條件）' : focusReturnPath ? '← 回到官方事件關注（原搜尋與截止日期）' : '← 回到個股'}</Link>
    <PageTitle eyebrow={marketDisplayLabel(data.instrument.exchange) + ' · ' + instrumentTypeLabel(data.instrument.instrument_type)} title={data.instrument.symbol + ' ' + data.instrument.name}>
      <div className="stock-quote-grid">
        <div><span>最近收盤（報價幣別元）</span><strong>{currentPrice == null ? '待核實' : formatNumber(currentPrice)}</strong></div>
        <div><span>漲跌（元／%）</span><strong className={priceChangeTone(priceChange)}>{priceChange == null ? '待核實' : `${formatSignedNumber(priceChange)}${priceChangePct == null ? '' : `（${formatSignedPercent(priceChangePct)}）`}`}</strong></div>
        <div><span>成交量（張）</span><strong>{formatTableVolume(latestBar?.volume, latestBar?.source, latestBar?.volume_exact) || (latestBar?.volume == null ? '未提供' : '數值或單位待核實')}</strong></div>
      </div>
      <div className="small-note stock-header-meta">價格資料日期 {formatTaiwanDateTime(latestBar?.date, true)} · 來源 {latestBar ? sourceLabel(latestBar.source) : '尚無已核對的價格來源'}</div>
      <form className="overview-cutoff-control" onSubmit={(event) => { event.preventDefault(); const submitted = String(new FormData(event.currentTarget).get('as_of') ?? ''); const next = new URLSearchParams(searchParams); if (submitted) next.set('as_of', submitted); else next.delete('as_of'); setSearchParams(next) }}><label htmlFor="stock-cutoff">研究截止日期</label><input id="stock-cutoff" name="as_of" type="date" value={cutoffDraft} onInput={(event) => setCutoffDraft(event.currentTarget.value)} onChange={(event) => setCutoffDraft(event.target.value)} /><button type="submit" className="secondary-button">套用截止</button><button type="button" className="secondary-button" onClick={() => { const next = new URLSearchParams(searchParams); next.delete('as_of'); setSearchParams(next); setCutoffDraft('') }}>最新資料</button><span className="small-note">空白日期會使用最新資料日期。</span></form>
      {priceSourcePins(asOf) && exchange === 'TPEx' && <div className="small-note">同截止切換：{(memoryKnown ? priceSourcePins(asOf, data.overview!.price_memory!.provenance!.policy_version)! : priceSourcePins(asOf)!).symbols.map((symbol, index) => <span key={symbol}>{index > 0 && ' · '}<Link to={`/stocks/TPEx/${symbol}?as_of=${asOf}`}>{symbol} {PRICE_SYMBOL_NAMES[symbol]}</Link></span>)}</div>}
    </PageTitle>
    {!memoryKnown && (!readKnown || !candidateKnown || priceConflict) && <div className="data-gap stock-market-read-gap" role="status">{readShapeValid && read?.status === 'missing' ? '尚無行情記錄。' : '行情讀值無效，先核對原記錄。'} 最近收盤與漲跌待核實；已知日期的合法歷史行情仍可查看。</div>}
    {data.overview && <StockOverview data={data.overview} instrument={data.instrument} explicitCutoff={asOf} onCapturePrice={acquirePrice} capturingPrice={priceBusyKey === priceRequestKey} priceRequestFailure={priceRequestFailure?.key === priceRequestKey ? priceRequestFailure.reason : undefined} onNews={() => setTab('news')} onCaptureEvents={acquireEvents} capturingEvents={capturingEvents} eventRequestFailure={eventRequestFailure?.key === eventRequestKey ? eventRequestFailure.reason : undefined} onCaptureWindows={acquireWindows} capturingWindows={windowBusyKey === windowRequestKey} windowRequestFailure={windowRequestFailure?.key === windowRequestKey ? windowRequestFailure.reason : undefined} />}
    {(!researchShapeValid || data.research_read?.status === 'invalid') && <div className="data-gap stock-research-read-gap" role="status">研究候選讀值無效或格式待核實，先核對原記錄；行情與其他獨立區塊仍可查看。{researchShapeValid && data.research_read?.decision_block_scope === 'slots' ? '各策略分別核對，不以較早候選代替。' : ''}</div>}
    {fallbackResearchIncomplete && <div className="data-gap stock-data-gap">研究資料待補：{qualitySummary.research.missing_fields.map(fieldLabel).join('、') || '尚不能形成完整策略判斷'}。可在「研究條件」查看限制。</div>}
    <div className="stock-tabs" role="tablist" aria-label="個股詳情分頁">{tabs.map((item) => <button type="button" role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'stock-tab active' : 'stock-tab'} key={item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}</div>
    <div className="stock-tab-content">
      {tab === 'technical' && <section className="stock-tab-panel">{memoryKnown && <p className="small-note">{priceMemory.latest!.date === '2026-10-05' ? '10/5' : '10/6'} 官方單日行情；此原件沒有歷史價格視窗，MA20／MA60 待補。既有資料的日期與原列可在資料說明查看。</p>}<StockPriceChart bars={memoryKnown ? memoryPriceChartBars(priceMemory, data.instrument, priceCutoff) : memoryRejected ? [] : data.bars} unlocatedDateRows={memoryKnown ? 0 : read?.unlocated_count ?? 0} knownGapDates={memoryKnown ? [] : [...new Set([...(data.coverage?.missing_bar_dates_to_20 ?? []), ...(data.coverage?.missing_bar_dates_to_60 ?? [])])]} /></section>}
      {tab === 'chips' && <section className="stock-tab-panel panel"><div className="section-head"><div><div className="eyebrow">籌碼資料</div><h2>法人與融資</h2></div></div>{independent.chipStatus !== 'known' && <div className="data-gap stock-chip-read-gap" role="status">籌碼讀值缺失或無效，先核對原記錄；未提供與無效數值保留空白，其他獨立區塊仍可查看。</div>}{independent.chips.length ? <ChipTable rows={independent.chips.slice(-30).reverse()} /> : <div className="empty">尚無可核實的籌碼資料。</div>}<BrokerBranchEntry exchange={data.instrument.exchange} /></section>}
      {tab === 'news' && <section className="stock-tab-panel"><StockEventList news={data.news} events={data.events} /></section>}
      {tab === 'research' && <section className="stock-tab-panel">{hasTemporaryIndustryGroup && <div className="data-gap research-group-warning">{TEMPORARY_INDUSTRY_GROUP_NOTICE}</div>}<ActionDetailPanel action={researchAction} /><StockResearchPanel data={data} /></section>}
      {tab === 'data' && <section className="stock-tab-panel"><CoveragePanel coverage={data.coverage} /><QualityPanel summary={qualitySummary} rows={data.data_quality} /><section className="panel stock-source-panel"><div className="section-head"><div><div className="eyebrow">資料說明</div><h2>原始時間、來源與技術欄位</h2></div></div><div className="metric-row"><span>行情來源</span><b>{sourceLabel([...new Set(data.bars.map((bar) => bar.source).filter((source): source is string => typeof source === 'string'))])}</b></div><div className="metric-row"><span>回應產生時間</span><b>{formatTaiwanDateTime(data.response_generated_at)}</b></div>{independent.featureStatus !== 'known' && <div className="data-gap stock-feature-read-gap" role="status">後端特徵讀值缺失或無效，先核對原記錄；不以較早快照替代，行情與研究條件仍可查看。</div>}<div className="metric-row"><span><Term id="ma20">MA20</Term>／<Term id="ma60">MA60</Term>（後端特徵快照）</span><b>{formatNumber(independent.features.ma20)} ／ {formatNumber(independent.features.ma60)}</b></div>{independent.featureValid && data.feature_snapshot && <div className="small-note">快照資料日 {formatTaiwanDateTime(data.feature_snapshot.trading_date, true)} · 來源 {sourceLabel(data.feature_snapshot.source)} · 建立 {formatTaiwanDateTime(data.feature_snapshot.created_at)}；讀值語法不證明來源或當時可用性。</div>}<details className="technical-details"><summary>查看原始行情表</summary><BarTable rows={data.bars.slice(-30).reverse()} /></details></section></section>}
    </div>
  </div>
}

function BrokerBranchEntry({ exchange }: { exchange: string }) {
  const url = exchange === 'TWSE' ? 'https://bsr.twse.com.tw/bshtm/bsMenu.aspx' : exchange === 'TPEx' ? 'https://www.tpex.org.tw/web/stock/aftertrading/broker_trading/brokerBS.php' : null
  return <section className="panel broker-branch-entry" aria-labelledby="broker-branch-title">
    <h3 id="broker-branch-title">券商／分點</h3>
    <p>尚未提供整合的券商分點買賣資料。</p>
    <p className="small-note">券商分點是交易通道，不能據此認定特定主力；與外資、投信、自營商的三大法人分類不同。</p>
    {url ? <><a className="text-link" href={url} target="_blank" rel="noreferrer">前往{exchange === 'TWSE' ? '證交所' : '櫃買中心'}官方券商買賣查詢</a><p className="small-note">官方查詢需人工輸入驗證碼。{exchange === 'TPEx' ? '櫃買中心僅提供當日資料。' : ''}請在官方頁面輸入股票代號並完成驗證。</p></> : <p className="small-note">市場尚未核實，暫無對應官方查詢入口。</p>}
  </section>
}

function BarTable({ rows }: { rows: InstrumentDetail['bars'] }) {
  return <div className="table-wrap compact-table"><p className="small-note">單位：股價為各標的報價幣別的元，指數為點；成交量為張。空白表示未提供資料、數值無效或成交量來源單位待核實。</p><table><thead><tr><th>日期</th><th>收盤</th><th>最高</th><th>最低</th><th>成交量</th></tr></thead><tbody>{rows.map((row, index) => <tr key={row.id ?? row.date ?? index}><td>{formatTaiwanDateTime(row.date, true)}</td><td className="numeric-cell">{formatTableNumber(row.close, 2)}</td><td className="numeric-cell">{formatTableNumber(row.high, 2)}</td><td className="numeric-cell">{formatTableNumber(row.low, 2)}</td><td className="numeric-cell">{formatTableVolume(row.volume, row.source, row.volume_exact)}</td></tr>)}</tbody></table></div>
}

function formatRawChipValue(value: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-TW', { maximumFractionDigits: 3 }) : '未提供'
}

export function ChipTable({ rows }: { rows: InstrumentDetail['chips'] }) {
  return <>
    <div className="small-note chip-unit-note">單位：張。三大法人為外資、投信、自營商；正值為買超，負值為賣超。融資正值為餘額增加，負值為減少。空白表示未提供資料、數值無效或來源單位待核實；原始值與來源見下方說明。</div>
    <div className="table-wrap compact-table">
      <table>
        <thead><tr><th>日期</th><th><Term id="foreign_flow">外資買賣超</Term></th><th><Term id="trust_flow">投信</Term></th><th><Term id="dealer_flow">自營商</Term></th><th><Term id="margin">融資增減</Term></th></tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.id ?? row.date ?? index}>
          <td>{formatTaiwanDateTime(row.date, true)}</td>
          <td className="numeric-cell">{formatTableChip(row.foreign_buy, row.source)}</td>
          <td className="numeric-cell">{formatTableChip(row.trust_buy, row.source)}</td>
          <td className="numeric-cell">{formatTableChip(row.dealer_buy, row.source)}</td>
          <td className="numeric-cell">{formatTableChip(row.margin_change, row.source, true)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <details className="technical-details chip-source-details"><summary>資料來源與原始值</summary><div className="chip-source-list">{rows.map((row) => <div className="chip-source-row" key={`${row.date}-${row.source}`}><strong>{formatTaiwanDateTime(row.date, true)}</strong><span>來源：{sourceLabel(row.source)}（{row.source || '來源未提供'}） · 資料截至：{formatTaiwanDateTime(row.data_as_of, true)} · 收集：{formatTaiwanDateTime(row.collected_at)}</span><span>來源稽核原值：外資（{isVerifiedChipFlowSource(row.source) ? '股' : '單位待核實'}） {formatRawChipValue(row.foreign_buy)} · 投信（{isVerifiedChipFlowSource(row.source) ? '股' : '單位待核實'}） {formatRawChipValue(row.trust_buy)} · 自營商（{isVerifiedChipFlowSource(row.source) ? '股' : '單位待核實'}） {formatRawChipValue(row.dealer_buy)} · 融資（{isVerifiedMarginSource(row.source) ? '張' : '單位待核實'}） {formatRawChipValue(row.margin_change)}</span></div>)}</div></details>
  </>
}

function ConditionList({ conditions }: { conditions: InstrumentDetail['strategy_conditions'] }) {
  return <div className="condition-list">{Object.entries(conditions).map(([name, condition]) => <div className="condition" key={name}><div className="condition-head"><strong><Term id={name === 'breakout' ? 'breakout' : 'pullback'}>{condition.label ?? strategyLabel(name)}</Term></strong><span className="muted">{researchSourceLabel(condition.source)}</span></div><div className="tag-list">{condition.requires.map((field) => <span className="tag" key={field}>{fieldLabel(field)}</span>)}</div>{condition.technical && <details className="technical-details"><summary>技術資訊</summary>{Object.values(condition.technical).map((value) => <div key={value}>{value}</div>)}</details>}</div>)}</div>
}

function EventPanel({ rows }: { rows: NewsItem[] }) {
  return <div className="panel"><h2>官方事件</h2>{rows.length ? rows.map((item) => <ProductNewsCard key={item.id} item={item} />) : <div className="empty">尚無個股官方事件。</div>}</div>
}

function QualityPanel({ summary, rows }: { summary: InstrumentDetail['quality_summary']; rows: DataQualityRow[] }) {
  if (!summary) return <div className="panel"><h2>資料品質</h2><div className="empty">尚無依用途分開的資料品質摘要。</div></div>
  const researchDescription = productResearchDescription(summary.research.status, summary.research.missing_fields.map(fieldLabel))
  return <div className="panel"><h2><Term id="data_quality">資料品質</Term>（依用途）</h2><div className="quality-line"><strong>當日行情來源</strong><QualityBadge kind="market" status={summary.market.status} /><span>{productQualityLabel(summary.market.status, 'market')} · 資料日 {formatTaiwanDateTime(summary.market.as_of, true)}</span></div><div className="quality-line"><strong>策略判斷資料</strong><QualityBadge kind="research" status={summary.research.status} /><span>{researchDescription}</span></div>{rows.length > 0 && <details className="technical-details"><summary>查看來源檢查紀錄</summary>{rows.slice(0, 5).map((row) => <div className="quality-line" key={row.entity_key + row.as_of_date}><span>{formatTaiwanDateTime(row.as_of_date, true)}</span><QualityBadge kind="generic" status={row.status} /><span>{row.missing_fields.map(fieldLabel).join('、') || '檢查完成'}</span></div>)}</details>}</div>
}

const coverageReasonLabels: Record<string, string> = {
  listed_under_threshold: '上市／掛牌後有效交易日尚不足',
  missing_bar_dates: '部分有效交易日缺少行情',
  suspended_or_no_trade: '停牌或當日無交易',
  missing_taiex: '缺少 加權指數 交易日基準',
  missing_chips: '部分有效交易日缺少籌碼',
  etf_not_general_action_eligible: '此 ETF 類型不套用一般股票進出場判斷',
}

function CoveragePanel({ coverage }: { coverage: InstrumentDetail['coverage'] }) {
  if (!coverage) return <section className="panel"><h2>有效資料日數</h2><div className="empty">尚無可核實的交易日基準。</div></section>
  const labels = coverage.coverage_reasons.map((reason) => coverageReasonLabels[reason] ?? '資料覆蓋仍待核實')
  const baselineLabel = coverage.verified_taiex_sessions == null ? '尚無可核實基準' : `${formatNumber(coverage.verified_taiex_sessions, 0)} 日`
  const barCountLabel = coverage.effective_bar_sessions == null ? '尚無可核實基準' : `${formatNumber(coverage.effective_bar_sessions, 0)} 日`
  const missing20Label = coverage.missing_bars_to_20 == null ? '尚無可核實基準' : coverage.missing_bars_to_20 > 0 ? `還缺 ${coverage.missing_bars_to_20} 日` : '已達成'
  const missing60Label = coverage.missing_bars_to_60 == null ? '尚無可核實基準' : coverage.missing_bars_to_60 > 0 ? `還缺 ${coverage.missing_bars_to_60} 日` : '已達成'
  const missingChipLabel = coverage.missing_chips_to_20 == null ? '尚無可核實基準' : coverage.missing_chips_to_20 > 0 ? `20 日還缺 ${coverage.missing_chips_to_20} 日` : '20 日已達成'
  return <section className="panel coverage-panel"><div className="section-head"><div><div className="eyebrow">研究資料覆蓋</div><h2>距離策略判斷還缺幾個有效交易日</h2></div><span className="small-note">基準 {baselineLabel}</span></div><div className="metric-row"><span>有效行情交易日</span><b>{barCountLabel}</b></div><div className="metric-row"><span>距離 20 日條件</span><b>{missing20Label}</b></div><div className="metric-row"><span>距離 60 日條件</span><b>{missing60Label}</b></div><div className="metric-row"><span>籌碼資料</span><b>{missingChipLabel}</b></div>{labels.length ? <div className="data-gap">目前原因：{labels.join('、')}</div> : <div className="small-note">目前沒有已知資料覆蓋缺口。</div>}<details className="technical-details"><summary>查看缺口日期與資料明細</summary><div className="small-note">20 日行情缺口：{coverage.missing_bar_dates_to_20.length ? coverage.missing_bar_dates_to_20.join('、') : '無'}</div><div className="small-note">60 日行情缺口：{coverage.missing_bar_dates_to_60.length ? coverage.missing_bar_dates_to_60.join('、') : '無'}</div><div className="small-note">20 日籌碼缺口：{coverage.missing_chip_dates_to_20.length ? coverage.missing_chip_dates_to_20.join('、') : '無'}</div></details></section>
}

type StockTab = 'technical' | 'chips' | 'news' | 'research' | 'data'

export function ActionDetailPanel({ action }: { action: ActionSummary | null }) {
  if (!action) return <section className="panel stock-action-detail"><h2>研究條件</h2><div className="empty">尚無行動摘要。</div></section>
  const incomplete = ['data_insufficient', 'data_incomplete', 'insufficient_data'].includes(action.action_state)
  const actionTitle = incomplete ? '策略判斷資料待補' : action.display_action ?? actionLabel(action.action_state)
  const detailReasons = action.display_reasons ?? action.reasons
  const showLevels = ['conditional_entry', 'wait_breakout', 'wait_pullback', 'hold_observe', 'reduce_exit'].includes(action.action_state)
  return <section className="panel stock-action-detail">
    <div className="section-head"><div><div className="eyebrow">研究動作</div><h2>{actionTitle}</h2></div><QualityBadge kind="research" status={action.data_quality} /></div>
    <div className="action-detail-summary"><strong>{action.display_instruction ?? action.action_instruction ?? actionLabel(action.action_state)}</strong>{action.primary_reason?.label && <span>{action.primary_reason.label}</span>}</div>
    {action.position_quantity_status === 'unknown' && <div className="small-note"><span className="pill ambiguous">庫存數量待核實</span> 請先核對原記錄，再確認持倉狀態。</div>}
    {incomplete && <div className="data-gap">{productActionReasonLabel(action.data_gap ?? '研究資料尚未完整，尚不能計算進場、失效與目標價。')}</div>}
    <details className="technical-details"><summary>查看風險提醒、時間與價位</summary>
      <ProductTimeSummary time={action.product_time} fallbackDate={action.data_cutoff} fallbackEarliestDate={action.earliest_execution_date} />
      {showLevels && <div className="level-grid stock-detail-levels">
        {action.trigger_price != null && <div><span>{levelFieldLabel('trigger_price', action.level_semantics)}</span><b>{formatNumber(action.trigger_price)}</b></div>}
        {action.entry_low != null && <div><span>{levelFieldLabel('entry_low', action.level_semantics)}</span><b>{formatNumber(action.entry_low)}</b></div>}
        {action.entry_high != null && <div><span>{levelFieldLabel('entry_high', action.level_semantics)}</span><b>{formatNumber(action.entry_high)}</b></div>}
        {action.invalid_price != null && <div><span>{levelFieldLabel('invalid_price', action.level_semantics)}</span><b>{formatNumber(action.invalid_price)}</b></div>}
        {action.target_1 != null && <div><span>{levelFieldLabel('target_1', action.level_semantics)}</span><b>{formatNumber(action.target_1)}</b></div>}
        {action.risk_reward != null && <div><span><Term id="rr">風險報酬比</Term></span><b>{formatNumber(action.risk_reward)}</b></div>}
      </div>}
      {detailReasons.length > 0 && <ul className="reason-list">{detailReasons.map((reason) => <li key={reason}>{action.display_reasons ? reason : productActionReasonLabel(reason)}</li>)}</ul>}
      {action.conflicts.length > 0 && <div className="warning-box">{action.conflicts.join('；')}</div>}
      <div className="small-note">資料日：{formatTaiwanDateTime(action.data_cutoff, true)} · 價位語意：{levelSemanticsLabel(action.level_semantics)} · 規則與官方資料詳見資料說明。</div>
    </details>
  </section>
}

function StockEventList({ news, events }: { news: NewsItem[]; events: InstrumentDetail['events'] }) {
  if (!news.length && !events.length) return <div className="empty panel">尚無個股新聞或官方事件。</div>
  return <>
    {news.length > 0 && <div className="news-list">{news.map((item) => <ProductNewsCard key={item.id} item={item} />)}</div>}
    {events.length > 0 && <section className="panel stock-event-list"><h2>官方事件紀錄</h2><div className="event-list">{events.map((item, index) => { const displayTitle = officialEventDisplayTitle(item.title, item.type); return <article className="event-item" key={`${item.date}-${item.type}-${index}`}><div className="small-note">事件日 {formatTaiwanDateTime(item.date, true)} · 來源 {sourceLabel(item.source)}</div><strong>{displayTitle}</strong>{item.description && <p>{item.description}</p>}{displayTitle !== (item.title || item.type || '官方事件') && <details className="technical-details"><summary>資料來源</summary><div>原始標題：{item.title || '—'} · 原始類型：{item.type || '—'}</div><div>資料截至：{formatTaiwanDateTime(item.data_as_of, true)}</div></details>}</article> })}</div></section>}
  </>
}

export function ActionsPage() {
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageCursors, setPageCursors] = useState<Array<string | undefined>>([undefined])
  const [state, setState] = useState('')
  const cursor = pageCursors[page - 1]
  const query = useQuery({ queryKey: ['actions', { search, cursor, state }], queryFn: () => getActions({ q: search || undefined, cursor, limit: 20, state: state || undefined }) })
  const resetPage = () => { setPage(1); setPageCursors([undefined]) }
  const submit = (value = draft.trim()) => { setSearch(value); resetPage() }
  const clear = () => { setDraft(''); setSearch(''); resetPage() }
  const nextPage = (nextCursor: string) => { setPageCursors((current) => [...current.slice(0, page), nextCursor]); setPage(page + 1) }
  const previousPage = () => { if (page > 1) setPage(page - 1) }
  return <div className="page">
    <PageTitle eyebrow="行動判斷" title="行動中心" description="每個標的與資料日最多一張摘要；先看庫存風險，再看可執行條件與官方事件。">
       <div className="filter-row"><SearchBox draft={draft} query={search} placeholder="搜尋代號或名稱" onDraftChange={setDraft} onSubmit={submit} onClear={clear} /><select className="filter-select" value={state} onChange={(event) => { setState(event.target.value); resetPage() }}><option value="">全部行動狀態</option>{Object.entries(actionNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
    </PageTitle>
    <PortfolioSubsection />
    <QueryState loading={query.isLoading} error={query.error}>{query.data && (() => {
      const executableStates = new Set(['conditional_entry', 'wait_breakout', 'wait_pullback', 'hold_observe', 'reduce_exit', 'manual_review'])
      const priorityItems = query.data.items.filter((item) => item.held === true || item.position_quantity_status === 'unknown' || executableStates.has(item.action_state))
      const eventOrWatchlistWaiting = query.data.items.filter((item) => item.held === false && item.action_state === 'data_insufficient' && (item.watchlisted || (item.event_ids ?? []).length > 0))
      const ordinaryWaiting = query.data.items.filter((item) => item.held === false && item.action_state === 'data_insufficient' && !item.watchlisted && (item.event_ids ?? []).length === 0)
      const otherSummaries = query.data.items.filter((item) => item.held === false && item.action_state === 'no_condition')
      return <>
        {query.data.summary?.held_unknown !== undefined && <p className="small-note">本次篩選庫存數量待核實 {query.data.summary.held_unknown.toLocaleString()} 筆；這些記錄尚未計入已核實持倉。</p>}
        {priorityItems.length > 0 ? <section><div className="section-head"><div><div className="eyebrow">優先處理</div><h2>庫存風險／可執行條件</h2></div><span className="small-note">{priorityItems.length} 筆</span></div><div className="action-grid">{priorityItems.map((item) => <CompactActionCard key={item.instrument.exchange + item.instrument.symbol + (item.as_of ?? '')} action={item} />)}</div></section> : (eventOrWatchlistWaiting.length === 0 && <div className="empty panel">目前沒有庫存風險或可執行條件。</div>)}
        {eventOrWatchlistWaiting.length > 0 && <section className="deferred-section"><div className="section-head"><div><div className="eyebrow">事件／自選</div><h2>優先補齊資料</h2></div><span className="small-note">{eventOrWatchlistWaiting.length} 筆</span></div><p className="small-note">有官方事件或自選標的的研究資料尚未齊備，優先於一般市場標的處理。</p><details className="deferred-list"><summary>展開待補標的</summary><div className="action-grid">{eventOrWatchlistWaiting.map((item) => <CompactActionCard key={item.instrument.exchange + item.instrument.symbol + (item.as_of ?? '')} action={item} />)}</div></details></section>}
        {ordinaryWaiting.length > 0 && <section className="deferred-section"><div className="section-head"><div><div className="eyebrow">資料補齊</div><h2>一般標的待補資料</h2></div><span className="small-note">本批 {ordinaryWaiting.length} 筆／共 {query.data.summary?.data_insufficient ?? ordinaryWaiting.length} 筆</span></div><p className="small-note">一般標的一日研究資料尚未齊備集中在這裡，不會淹沒庫存與可執行條件。</p><details className="deferred-list"><summary>展開待補標的</summary><div className="action-grid">{ordinaryWaiting.map((item) => <CompactActionCard key={item.instrument.exchange + item.instrument.symbol + (item.as_of ?? '')} action={item} />)}</div></details></section>}
        {otherSummaries.length > 0 && <section className="deferred-section"><div className="section-head"><div><div className="eyebrow">其他摘要</div><h2>目前沒有成立條件</h2></div><span className="small-note">{otherSummaries.length} 筆</span></div><div className="action-grid">{otherSummaries.map((item) => <CompactActionCard key={item.instrument.exchange + item.instrument.symbol + (item.as_of ?? '')} action={item} />)}</div></section>}
         <CursorControls meta={query.data.meta} page={page} itemCount={query.data.items.length} onNext={nextPage} onPrevious={previousPage} onReset={resetPage} />
      </>
    })()}</QueryState>
  </div>
}

type PortfolioDraft = { symbol: string; exchange: string; unit: ShareUnit; quantity: string; average_cost: string; stop_price: string }

const emptyPortfolioDraft: PortfolioDraft = { symbol: '', exchange: '', unit: 'lot', quantity: '', average_cost: '', stop_price: '' }

export function PortfolioSubsection() {
  const query = useQuery({ queryKey: ['portfolio-subsection'], queryFn: () => getPortfolio({ page: 1, page_size: 20 }) })
  const [draft, setDraft] = useState<PortfolioDraft>(emptyPortfolioDraft)
  const [busy, setBusy] = useState<number | 'save' | null>(null)
  const [message, setMessage] = useState('')
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!draft.symbol.trim() || !draft.quantity) { setMessage('請輸入代號與數量。'); return }
    let payload: PositionInput
    try {
      payload = { symbol: draft.symbol.trim(), exchange: draft.exchange || undefined, unit: draft.unit,
        quantity: positionQuantityFromText(draft.unit, draft.quantity),
        average_cost: portfolioValueFromText(draft.average_cost, '平均成本'),
        stop_price: portfolioValueFromText(draft.stop_price, '停損價') }
    } catch (error) { setMessage(error instanceof Error ? error.message : '請核對庫存輸入。'); return }
    setBusy('save'); setMessage('')
    try { await upsertPortfolio(payload); await query.refetch(); setDraft(emptyPortfolioDraft); setMessage('庫存已保存。') } catch (error) { setMessage(error instanceof Error ? error.message : '保存失敗。') } finally { setBusy(null) }
  }
  const remove = async (id: number) => {
    if (busy !== null) return
    setBusy(id); setMessage('')
    try { await deletePortfolio(id); await query.refetch(); setMessage('庫存已刪除。') } catch (error) { setMessage(error instanceof Error ? error.message : '刪除失敗。') } finally { setBusy(null) }
  }
  return <section className="panel portfolio-subsection"><div className="section-head"><div><div className="eyebrow">行動優先級</div><h2>我的庫存</h2></div><span className="small-note">庫存風險會優先於一般市場標的</span></div><p className="small-note">未核實行情的本地記錄與試算，可展開每筆庫存核對。</p><details className="portfolio-editor"><summary>新增庫存</summary><p className="small-note">每張為 1,000 股；可保存的總股數為 1 至 9,223,372,036,854,775,807 股。</p><form className="inline-form" onSubmit={save}><input aria-label="庫存代號" placeholder="代號" value={draft.symbol} onChange={(event) => setDraft({ ...draft, symbol: event.target.value })} /><select aria-label="交易所" className="filter-select" value={draft.exchange} onChange={(event) => setDraft({ ...draft, exchange: event.target.value })}><option value="">交易所</option><option value="TWSE">上市（TWSE）</option><option value="TPEx">上櫃（TPEx）</option></select><select aria-label="交易單位" className="filter-select" value={draft.unit} onChange={(event) => setDraft({ ...draft, unit: event.target.value as ShareUnit })}><option value="lot">單位：張</option><option value="odd_lot">單位：零股</option></select><input aria-label={draft.unit === 'lot' ? '張數' : '股數'} type="text" inputMode="numeric" placeholder={draft.unit === 'lot' ? '張數' : '股數'} value={draft.quantity} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })} /><input aria-label="平均成本／每股" type="text" inputMode="decimal" placeholder="平均成本／每股" value={draft.average_cost} onChange={(event) => setDraft({ ...draft, average_cost: event.target.value })} /><input aria-label="停損價" type="text" inputMode="decimal" placeholder="停損價" value={draft.stop_price} onChange={(event) => setDraft({ ...draft, stop_price: event.target.value })} /><button type="submit" className="secondary-button" disabled={busy !== null}>{busy === 'save' ? '儲存中…' : '儲存'}</button></form></details>{message && <div className="small-note">{message}</div>}{query.data?.items.length ? <div className="position-list">{query.data.items.map((position) => <div className="position-card" key={position.id}><div className="position-head"><Link className="symbol-link" to={'/stocks/' + encodeURIComponent(position.instrument?.exchange ?? '') + '/' + encodeURIComponent(position.instrument?.symbol ?? '')}>{position.instrument?.symbol ?? '—'} {position.instrument?.name ?? ''}</Link><button type="button" className="delete-button" disabled={busy !== null} onClick={() => remove(position.id)}>{busy === position.id ? '刪除中…' : '刪除'}</button></div><div className="position-quantity"><div>持有 {formatShareQuantity(position.shares, position.shares_exact)}</div></div><div className="small-note">平均成本（報價幣別元／股） {formatPortfolioValue(position.average_cost, position.portfolio_value_status, 'average_cost')} · 停損價（報價幣別元／股） {formatPortfolioValue(position.stop_price, position.portfolio_value_status, 'stop_price')} · 收盤狀態 {formatPortfolioClose(position.portfolio_quote)} · 市值（報價幣別元） {formatPositionValuation(position.market_value, position.valuation_status, 'market_value')} · 未實現損益（報價幣別元） {formatPositionValuation(position.unrealized_pnl, position.valuation_status, 'unrealized_pnl')}</div>
        <details className="portfolio-quote-review" style={{ overflowWrap: 'anywhere' }}><summary>核對庫存原股數、本地行情與試算</summary>
          <div className="small-note">來源稽核原股數 {formatPositionShares(position.shares, position.shares_exact)}</div>
          <p className="small-note">本地記錄；來源／日期待核實。記錄日期不表示交易日或原件證據已核實。</p>
          <div className="small-note">本地收盤讀值（報價幣別元／股） {formatPortfolioClose(position.portfolio_quote, true)}</div>
          <div className="small-note">記錄來源 {formatQuoteRecord(position.portfolio_quote, 'source')} · 記錄日期 {formatQuoteRecord(position.portfolio_quote, 'date')}</div>
          <div className="small-note">記錄資料時間 {formatQuoteRecord(position.portfolio_quote, 'data_as_of')} · 記錄收集時間 {formatQuoteRecord(position.portfolio_quote, 'collected_at')}</div>
          <p className="small-note">本地試算，行情來源／日期尚未核實。停牌、行情整體一致性與可交易用途尚未核對。</p>
          <div className="small-note">市值本地試算（股數 × 本地收盤，報價幣別元） {formatLocalPositionValuation(position.market_value, position.valuation_status, 'market_value')}</div>
          <div className="small-note">未實現損益本地試算（市值 − 平均成本 × 股數，報價幣別元） {formatLocalPositionValuation(position.unrealized_pnl, position.valuation_status, 'unrealized_pnl')}</div>
        </details></div>)}</div> : <div className="empty">尚未建立庫存。</div>}</section>
}

function LegacyInstrumentRedirect() {
  const { symbol = '' } = useParams()
  const [searchParams] = useSearchParams()
  const exchange = searchParams.get('exchange')
  const target = legacyRouteTarget('/instruments/' + symbol, exchange ? '?exchange=' + encodeURIComponent(exchange) : '') ?? '/stocks'
  return <Navigate replace to={target} />
}

function LegacyGroupRedirect() {
  const { groupId = '' } = useParams()
  return <Navigate replace to={'/themes/' + encodeURIComponent(groupId)} />
}

function ResearchBacktestPage() {
  const query = useQuery<BacktestSummary>({ queryKey: ['backtest-summary'], queryFn: () => getBacktestSummary() })
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page"><PageTitle eyebrow="研究詳細" title="技術回測" description="此頁只呈現固定規則的技術驗證；樣本不足時不輸出勝率或採用結論。" />{query.data.run ? <><div className="source-banner"><strong>{statusLabel(query.data.run.status)}</strong><span>資料截至 {formatTaiwanDateTime(query.data.run.data_as_of, true)}</span><QualityBadge status={query.data.run.assessment} /><span>可行動樣本 {query.data.run.zero_actionable_count}</span></div><div className="table-wrap"><p className="small-note">期限為訊號日之後的交易日數；樣本、可比與不可比的單位為筆。空白表示未提供資料或數值待核實。</p><table><thead><tr><th>策略</th><th>類型</th><th>期限</th><th>樣本</th><th>可比</th><th>不可比</th><th>評估</th></tr></thead><tbody>{query.data.groups.map((row) => <tr key={row.strategy + row.instrument_type + row.horizon}><td>{strategyLabel(row.strategy)} · 規則版本 {row.version}</td><td>{instrumentTypeLabel(row.instrument_type)}</td><td className="numeric-cell">{formatTableNumber(row.horizon, 0)}</td><td className="numeric-cell">{formatTableNumber(row.sample, 0)}</td><td className="numeric-cell">{formatTableNumber(row.comparable, 0)}</td><td className="numeric-cell">{formatTableNumber(row.incomparable, 0)}</td><td><QualityBadge status={row.assessment} /></td></tr>)}</tbody></table></div></> : <div className="empty panel">尚無回測紀錄。</div>}</div>}</QueryState>
}

function readMetadataRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function readMetadataList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function BackfillCoveragePage() {
  const runs = useQuery({ queryKey: ['backfill-runs'], queryFn: () => getBackfillRuns({ page: 1, page_size: 10 }) })
  const coverage = useQuery({ queryKey: ['coverage'], queryFn: () => getCoverage() })
  const error = runs.error ?? coverage.error
  if (runs.isLoading || coverage.isLoading) return <Loading />
  if (error) return <ErrorBox error={error} />
  const latest = runs.data?.items[0]
  const metadata = latest?.metadata ?? {}
  const manifest = readMetadataRecord(metadata.coverage_manifest_summary)
  const targets = readMetadataRecord(metadata.coverage_targets)
  const requested = readMetadataList(metadata.requested_calendar_dates).length
  const verified = readMetadataList(metadata.verified_trading_sessions).length
  const extensions = readMetadataList(metadata.extension_dates).length
  const skipped = readMetadataList(metadata.skipped_non_trading).length
  const target = typeof targets.ohlcv_taiex_sessions === 'number' ? targets.ohlcv_taiex_sessions : 65
  const summary = coverage.data?.summary
  const coverageStatus = summary?.coverage_status ?? coverage.data?.baseline?.status ?? 'unknown'
  const coverageBadge = coverageStatus === 'manifest' ? 'complete' : coverageStatus === 'snapshot' ? 'official_snapshot' : 'unknown'
  return <div className="page"><PageTitle eyebrow="研究詳細" title="官方資料回補與覆蓋度" description="此頁只讀取回補稽核紀錄與目前資料覆蓋度，不提供直接啟動正式回補的操作。"><Link className="text-link" to="/system/data-quality">前往系統資料品質</Link></PageTitle><section className="panel"><div className="section-head"><div><h2>最近一次回補</h2><div className="small-note">回補由受控工作流程執行，日期與來源均保留稽核紀錄。</div></div>{latest && <QualityBadge status={latest.status} />}</div>{latest ? <div className="metric-grid"><div className="metric-card"><span>日期範圍</span><b>{latest.metadata.start_date as string}～{latest.metadata.end_date as string}</b></div><div className="metric-card"><span>原定日曆日期</span><b>{requested} 日</b></div><div className="metric-card"><span>已驗證交易日</span><b>{verified}／{target} 日</b></div><div className="metric-card"><span>延伸補抓</span><b>{extensions} 日</b></div><div className="metric-card"><span>明確休市／無資料</span><b>{skipped} 日</b></div><div className="metric-card"><span>覆蓋目標</span><b>{manifest.target_met === true ? '已達成' : '尚未達成'}</b></div></div> : <div className="empty">尚無官方回補稽核紀錄。</div>}{latest?.error && <div className="data-gap">最近一次狀態說明：{latest.error}</div>}</section><section className="panel"><div className="section-head"><div><h2>目前市場資料覆蓋度</h2><div className="small-note">{summary?.baseline_message ?? coverage.data?.baseline?.message ?? '尚無可核實的官方交易日基準。'}</div></div>{summary && <QualityBadge kind="generic" status={coverageBadge} />}</div>{summary?.coverage_status === 'unknown' ? <div className="empty">尚未建立回補涵蓋基準；因此不計算全市場缺口原因。請先由受控流程產生回補稽核紀錄。</div> : summary ? <><div className="metric-grid"><div className="metric-card"><span>加權指數 已核實交易日</span><b>{summary.verified_taiex_sessions} 日{coverageStatus === 'snapshot' ? '（官方快照）' : ''}</b></div><div className="metric-card"><span>行情未滿 20 日</span><b>{summary.incomplete_to_20} 個標的</b></div><div className="metric-card"><span>行情未滿 60 日</span><b>{summary.incomplete_to_60} 個標的</b></div><div className="metric-card"><span>籌碼未滿 20 日</span><b>{summary.incomplete_chips_to_20} 個標的</b></div></div>{Object.keys(summary.coverage_reason_counts).length > 0 && <div className="tag-list">{Object.entries(summary.coverage_reason_counts).map(([reason, count]) => <span className="tag" key={reason}>{coverageReasonLabels[reason] ?? '其他資料缺口'}：{count}</span>)}</div>}<div className="small-note">回補目標：{summary.target_met === null ? '尚無回補稽核基準' : summary.target_met ? '已達成' : '尚未達成'}；事件資料：{summary.verified_event_sessions} 個已核實查詢日。</div></> : <div className="empty">尚無覆蓋度摘要。</div>}</section><section className="panel"><h2>回補紀錄</h2>{runs.data?.items.length ? <div className="table-wrap"><p className="small-note">資料量單位：筆。空白表示未提供資料或數值待核實。</p><table><thead><tr><th>更新時間</th><th>資料範圍</th><th>狀態</th><th>筆數</th><th>錯誤</th></tr></thead><tbody>{runs.data.items.map((run) => <tr key={run.id}><td>{formatTaiwanDateTime(run.updated_at)}</td><td>{run.metadata.start_date as string}～{run.metadata.end_date as string}</td><td><QualityBadge status={run.status} /></td><td className="numeric-cell">{formatTableNumber(run.records, 0)}</td><td>{run.error ?? '—'}</td></tr>)}</tbody></table></div> : <div className="empty">尚無回補紀錄。</div>}</section></div>
}

function SystemDataPage() {
  const quality = useQuery({ queryKey: ['quality'], queryFn: () => getDataQuality({ page: 1, page_size: 30 }) })
  const raw = useQuery({ queryKey: ['raw'], queryFn: () => getRawPayloads({ page: 1, page_size: 30 }) })
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => getIngestionRuns({ page: 1, page_size: 20 }) })
  const strategies = useQuery({ queryKey: ['strategies'], queryFn: () => getStrategies({ page: 1, page_size: 20 }) })
  const error = quality.error ?? raw.error ?? runs.error ?? strategies.error
  if (quality.isLoading || raw.isLoading || runs.isLoading || strategies.isLoading) return <Loading />
  if (error) return <ErrorBox error={error} />
  return <div className="page"><PageTitle eyebrow="系統頁" title="資料品質" description="管理型檢視：原始資料、擷取工作、資料品質與固定規則設定快照。"><div className="source-banner"><strong>官方資料</strong><span>此頁不在主導航，供稽核使用。</span></div><Link className="text-link" to="/research/coverage">查看官方資料回補與覆蓋度</Link></PageTitle><section className="panel"><h2>擷取狀態</h2><div className="table-wrap"><p className="small-note">資料量單位：筆。空白表示未提供資料或數值待核實。</p><table><thead><tr><th>更新</th><th>來源</th><th>資料日</th><th>狀態</th><th>筆數</th><th>資料截至</th><th>錯誤</th></tr></thead><tbody>{runs.data?.items.map((run) => <tr key={run.id}><td>{formatTaiwanDateTime(run.updated_at)}</td><td>{sourceLabel(run.source)}</td><td>{run.run_date}</td><td><QualityBadge status={run.status} /></td><td className="numeric-cell">{formatTableNumber(run.records, 0)}</td><td>{formatTaiwanDateTime(run.data_as_of, true)}</td><td>{run.error ?? '—'}</td></tr>)}</tbody></table></div></section><section className="panel"><h2>原始來源</h2><RawTable rows={raw.data?.items ?? []} /></section><section className="panel"><h2>資料品質</h2><QualityTable rows={quality.data?.items ?? []} /></section><section className="panel"><h2>策略版本</h2>{strategies.data?.items.map((item) => <div className="condition" key={item.name + item.version}><div className="condition-head"><strong>{strategyLabel(item.name)} · 規則版本 {item.version}</strong><QualityBadge status={item.active ? 'complete' : 'inactive'} /></div><details className="technical-details"><summary>查看規則設定</summary><pre>{JSON.stringify(item.canonical_config_snapshot, null, 2)}</pre></details></div>)}</section></div>
}

function RawTable({ rows }: { rows: RawPayload[] }) {
  if (!rows.length) return <div className="empty">尚無原始來源資料。</div>
  return <div className="table-wrap"><table><thead><tr><th>擷取時間</th><th>資料批次</th><th>來源</th><th>資料日</th><th>來源位置</th><th>內容校驗碼</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td>{row.collected_at ?? '—'}</td><td className="numeric-cell">{formatTableNumber(row.ingestion_run_id, 0)}</td><td>{sourceLabel(row.source)}</td><td>{row.data_as_of ?? '—'}</td><td>{row.endpoint}</td><td className="hash-cell">{row.sha256 ?? '—'}</td></tr>)}</tbody></table></div>
}

function QualityTable({ rows }: { rows: DataQualityRow[] }) {
  if (!rows.length) return <div className="empty">尚無資料品質紀錄。</div>
  return <div className="quality-list">{rows.map((row) => <div className="quality-line" key={row.entity_key + row.as_of_date}><span>{row.as_of_date} · {row.entity_key}</span><QualityBadge status={row.status} /><span>{row.missing_fields.map(fieldLabel).join('、') || '完整'}</span></div>)}</div>
}

function ResearchStrategiesPage() {
  const query = useQuery({ queryKey: ['strategies'], queryFn: () => getStrategies({ page: 1, page_size: 50 }) })
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page"><PageTitle eyebrow="研究詳細" title="策略版本" description="固定規則設定快照是稽核證據；產品行動摘要不改寫研究規則。" />{query.data.items.map((item) => <article className="panel" key={item.name + item.version}><div className="position-head"><strong>{strategyLabel(item.name)}</strong><span>規則版本 {item.version}</span></div><details className="technical-details"><summary>查看規則設定</summary><pre>{JSON.stringify(item.canonical_config_snapshot, null, 2)}</pre></details></article>)}</div>}</QueryState>
}

function GlossaryPage() {
  const query = useQuery<{ items: GlossaryTerm[] }>({ queryKey: ['glossary'], queryFn: () => getGlossary() })
  const terms = query.data?.items.length ? query.data.items : GLOSSARY
  return <QueryState loading={query.isLoading} error={query.error}><div className="page"><PageTitle eyebrow="用語" title="用語表" description="按 Enter／Space 或點擊任一詞彙開啟完整定義、用途、解讀方式與限制。" /><div className="glossary-grid">{terms.map((term) => <article className="panel" key={term.term_id}><h2><Term id={term.term_id}>{term.name.replaceAll('外陸資', '外資')}</Term></h2><p>{term.plain_definition.replaceAll('外陸資', '外資')}</p><div className="small-note">用途：{term.use}</div></article>)}</div></div></QueryState>
}

function NotFound() {
  return <div className="page"><div className="empty panel">找不到此頁。<Link className="text-link" to="/">回到今日</Link></div></div>
}

export default function App() {
  return <Shell><Routes>
    <Route path="/" element={<TodayPage />} />
    <Route path="/news/:newsId" element={<NewsDetailPage />} />
    <Route path="/news" element={<NewsPage />} />
    <Route path="/themes" element={<ThemesPage />} />
    <Route path="/themes/:themeId" element={<ThemePage />} />
    <Route path="/stocks" element={<StocksPage />} />
    <Route path="/stocks/:exchange/:symbol" element={<StockPage />} />
    <Route path="/actions" element={<ActionsPage />} />
    <Route path="/actions/:exchange/:symbol" element={<StockPage />} />
    <Route path="/groups" element={<Navigate replace to="/themes" />} />
    <Route path="/groups/:groupId" element={<LegacyGroupRedirect />} />
    <Route path="/instruments" element={<Navigate replace to="/stocks" />} />
    <Route path="/instruments/:symbol" element={<LegacyInstrumentRedirect />} />
    <Route path="/signals" element={<Navigate replace to="/actions" />} />
    <Route path="/tracking" element={<Navigate replace to="/actions" />} />
    <Route path="/portfolio" element={<Navigate replace to="/actions" />} />
    <Route path="/data-quality" element={<Navigate replace to="/system/data-quality" />} />
    <Route path="/backtest" element={<Navigate replace to="/research/backtest" />} />
    <Route path="/system/data-quality" element={<SystemDataPage />} />
    <Route path="/research/backtest" element={<ResearchBacktestPage />} />
    <Route path="/research/coverage" element={<BackfillCoveragePage />} />
    <Route path="/research/strategies" element={<ResearchStrategiesPage />} />
    <Route path="/glossary" element={<GlossaryPage />} />
    <Route path="*" element={<NotFound />} />
  </Routes></Shell>
}
