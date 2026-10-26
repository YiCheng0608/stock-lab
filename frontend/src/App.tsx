import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, Route, Routes, useParams, useSearchParams } from 'react-router-dom'

import {
  deletePortfolio,
  getAction,
  getActions,
  getCandidates,
  getBackfillRuns,
  getBacktestSummary,
  getCoverage,
  getDashboard,
  getDataQuality,
  getGlossary,
  getGroup,
  getGroups,
  getIngestionRuns,
  getNews,
  getNewsDetail,
  getRawPayloads,
  getStock,
  getStockBars,
  getStocks,
  getStrategies,
  getTheme,
  getThemeMembers,
  getThemeBoard,
  getThemeSuggestion,
  getThemeSuggestions,
  getTracking,
  getPortfolio,
  upsertPortfolio,
} from './api'
import type {
  ActionSummary,
  BackfillRun,
  BacktestSummary,
  CursorMeta,
  Dashboard,
  DataQualityRow,
  GlossaryTerm,
  GroupDetail,
  GroupMember,
  IngestionRun,
  InstrumentDetail,
  Pagination,
  Position,
  PositionInput,
  RawPayload,
  SignalEvaluation,
  SignalSettlement,
  StockDirectoryRow,
  StockBarsInterval,
  StockBarsResponse,
  ThemeBoard,
  TrackingResponse,
  ProductTime,
} from './types'
import { commitSearchOnEnter } from './search'
import { GLOSSARY } from './glossary'
import { formatDay, formatTaipeiDay, formatTaipeiMinute } from './dates'
import { formatPortfolioValue, formatPositionValuation, formatLocalPositionValuation, formatPortfolioClose, formatQuoteRecord, portfolioValueFromText } from './portfolioValues'
import { formatFixed, formatTableNumber, formatTableVolume, formatTableVolumeShares, formatTableChip,formatShareQuantity, formatPositionShares, positionQuantityFromText, isVerifiedChipFlowSource, isVerifiedMarginSource, isVerifiedShareSource, type ShareUnit } from './units'
import { officialEventDisplayTitle, formatProductTimeRole, levelFieldLabel, levelObservationZoneLabel, levelSemanticsLabel, productActionReasonLabel, productQualityLabel, productResearchDescription, productTimeRoleDateTime, signalConfidenceLabel, staleCloseDateLabel, stockDirectoryActionLabel, stockDirectoryQualityLabel, stockGroupLabel, stopPriceFieldLabel, type ProductQualityKind } from './presentation'
import { Shell } from './components/Shell'
import { Term } from './components/Term'
import { Card, DataTable, EmptyState, Skeleton, Tabs, cx, tabId, tabPanelId, type Column } from './components/ui'
import { StockBarsChart } from './stock/StockBarsChart'
import { priceDigits } from './stock/stockBars'
import { StockHeader } from './stock/StockHeader'
import { StrategyVersionList, backtestGroupKey } from './components/StrategyVersionCard'
import { HotGroupsSection, ThemeDetailView, ThemesBoardView } from './themes/ThemeViews'
import { ThemeSuggestionsSection, type SuggestionNewsState } from './themes/ThemeSuggestionViews'
import { THEME_SUGGESTION_LIMIT } from './themes/themeSuggestions'
import { CandidatesSection, StockCandidatePanel } from './candidates/CandidateViews'
import { MEMBER_PAGE_SIZE, THEME_BOARD_LIMIT, THEME_NEWS_LIMIT, TODAY_BOARD_LIMIT, parseBoard } from './themes/themeBoards'
import { NewsCard, NewsDetailView, NewsListView, StockNewsTimeline } from './news/NewsViews'
import { HoldingAlert, MarketOverviewView, TodayHeader } from './today/TodayViews'
import { newsListParams, newsPageSearch, parseNewsTab, stockNewsParams, type NewsFilters } from './news/newsView'

// Fixed decimals (DESIGN_SYSTEM §3): rule levels and ratios 2, counts 0, a stock's own price by its tick.
function formatNumber(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? formatFixed(value, digits) : '未提供'
}

function formatSignedNumber(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? formatFixed(value, digits, true) : '未提供'
}

function formatSignedPercent(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) && Number.isFinite(value * 100) ? `${formatFixed(value * 100, digits, true)}%` : '未提供'
}

function compactText(value: string | null | undefined, maxLength = 120): string | null {
  if (!value) return null
  const cleaned = String(value).replace(/\s+/g, ' ').trim()
  if (!cleaned) return null
  return cleaned.length <= maxLength ? cleaned : cleaned.slice(0, maxLength - 1).trimEnd() + '…'
}

function formatTaiwanDateTime(value: string | null | undefined, dateOnly = false): string {
  if (!value) return '未提供'
  // A plain trading date is a calendar day, not an instant.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDay(value) ?? value
  return (dateOnly ? formatTaipeiDay(value) : formatTaipeiMinute(value)) ?? formatDay(value) ?? value
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

function instrumentTypeLabel(type: string): string {
  return ({ stock: '股票', equity: '股票', etf: 'ETF', ipo: '新上市', index: '指數' }[type.toLowerCase()] ?? '其他標的')
}

function marketDisplayLabel(value: string | null | undefined): string {
  if (value === 'TWSE') return '上市'
  if (value === 'TPEx') return '上櫃'
  return '市場待核實'
}

function strategyLabel(strategy: string | null | undefined): string {
  return ({
    breakout_v1: '突破條件',
    pullback_v1: '回踩條件',
    breakout: '突破條件',
    pullback: '回踩條件',
  }[strategy ?? ''] ?? '策略條件')
}

function priceChangeTone(value: number | null | undefined): 'positive' | 'negative' | '' {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return ''
  return value > 0 ? 'positive' : 'negative'
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
  institutional_flow_to_turnover_ratio_5d: '5 日法人流向／20 日日均成交量',
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
  'average daily volume 20d': '20 日日均成交量',
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
  return <div className="page"><Skeleton lines={4} /></div>
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
  compact = false,
  fallbackDate,
  fallbackEarliestDate,
}: {
  time?: ProductTime
  compact?: boolean
  fallbackDate?: string | null
  fallbackEarliestDate?: string | null
}) {
  const dateRole = 'market_date'
  const dateTime = productTimeRoleDateTime(time, dateRole)
  const decision = formatProductTimeRole(time, 'decision_at')
  const earliest = formatProductTimeRole(time, 'earliest_execution_date', fallbackEarliestDate ?? null)
  const dateValue = formatProductTimeRole(time, dateRole, fallbackDate ?? null)
  return (
    <div className="small-note product-time-summary" data-testid="product-time-summary">
      <div>
        <span>資料日期：{dateValue}</span>
        <span> · 決策時間：{decision}</span>
        <span> · 規則最早執行日：{earliest}</span>
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
  // Change keeps the close's tick decimals (DESIGN_SYSTEM §3).
  const digits = priceDigits(price, instrument.instrument_type)
  const change = validChange
    ? `漲跌（元） ${formatSignedNumber(action.price_change, digits)}（${formatSignedPercent(action.price_change_pct)}）`
    : '漲跌待核實'
  return (
    <Link className="panel compact-action-card" to={actionPath(action)} aria-label={`${instrument.symbol} ${title}`}>
      <div className="position-head"><span className="symbol-link"><strong>{instrument.symbol}</strong> {instrument.name}</span><span className="pill action-status-pill">{title}</span></div>
      <div className="small-note">{marketDisplayLabel(instrument.exchange)} · {instrumentTypeLabel(instrument.instrument_type)}</div>
      {action.position_quantity_status === 'unknown' && <span className="pill ambiguous">庫存數量待核實</span>}
      <div className="compact-price" style={{ minWidth: 0, flexWrap: 'wrap' }}><div style={{ minWidth: 0, flex: '1 1 140px', overflowWrap: 'anywhere' }}><span className="compact-label">最近收盤（報價幣別元）</span><strong>{price !== null ? formatNumber(price, digits) : '待核實'}</strong></div><span style={{ minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }} className={cx('compact-change', priceChangeTone(validChange ? action.price_change : null))}>{change}</span></div>
      {explicitRead && !validRead && read?.status !== 'missing' && <div className="small-note">行情讀值無效，先核對原記錄。</div>}
      {read?.status === 'missing' && <div className="small-note">尚無行情記錄。</div>}
      <div className="small-note">資料日 {formatTaiwanDateTime(action.data_cutoff ?? action.price_as_of, true)}</div>
      <span className="compact-detail-link">查看個股詳情 →</span>
    </Link>
  )
}

export function ProductActionCard({ action }: { action: ActionSummary }) {
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
      {action.current_price != null && <div className="metric-row"><span>最近收盤／漲跌幅（報價幣別元／%，{formatTaiwanDateTime(action.price_as_of, true)}）</span><b>{formatNumber(action.current_price, priceDigits(action.current_price, instrument.instrument_type))}{action.price_change_pct != null ? ' · ' + formatSignedPercent(action.price_change_pct) : ' · 漲跌幅待核實'}</b></div>}
      {incomplete ? (
        <div className="data-gap">{productActionReasonLabel(action.data_gap ?? '研究資料尚未完整，尚不能計算進場、失效與目標價。')}</div>
      ) : showLevels ? (
        <><p className="small-note">價位單位：各標的報價幣別的元；風險報酬比為倍。</p><div className="level-grid">
          {['conditional_entry', 'wait_breakout'].includes(action.action_state) && action.trigger_price != null && <div><span>{levelFieldLabel('trigger_price', action.level_semantics)}</span><b className="level-entry">{formatNumber(action.trigger_price)}</b></div>}
          {action.action_state === 'conditional_entry' && action.primary_strategy === 'pullback_v1' && (action.entry_low != null || action.entry_high != null) && <div><span>{levelObservationZoneLabel(action.level_semantics)}</span><b className="level-entry">{formatNumber(action.entry_low)}～{formatNumber(action.entry_high)}</b></div>}
          {action.action_state === 'wait_pullback' && action.entry_low != null && <div><span>{levelFieldLabel('entry_low', action.level_semantics)}</span><b className="level-entry">{formatNumber(action.entry_low)}</b></div>}
          {action.action_state === 'wait_pullback' && action.entry_high != null && <div><span>{levelFieldLabel('entry_high', action.level_semantics)}</span><b className="level-entry">{formatNumber(action.entry_high)}</b></div>}
          {action.action_state === 'conditional_entry' && action.invalid_price != null && <div><span>{levelFieldLabel('invalid_price', action.level_semantics)}</span><b className="level-stop">{formatNumber(action.invalid_price)}</b></div>}
          {action.action_state === 'conditional_entry' && action.target_1 != null && <div><span>{levelFieldLabel('target_1', action.level_semantics)}</span><b className="level-target">{formatNumber(action.target_1)}</b></div>}
          {action.action_state === 'conditional_entry' && action.risk_reward != null && <div><span><Term id="rr">風險報酬比</Term></span><b>{formatNumber(action.risk_reward, 2)}</b></div>}
           {['hold_observe', 'reduce_exit'].includes(action.action_state) && action.stop_price != null && <div><span>{stopPriceFieldLabel(action.stop_price_semantics)}</span><b className="level-stop">{formatNumber(action.stop_price)}</b></div>}
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

function NewsDetailPage() {
  const { newsId = '' } = useParams()
  const query = useQuery({ queryKey: ['news-detail', newsId], queryFn: () => getNewsDetail(newsId), enabled: Boolean(newsId) })
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <NewsDetailView item={query.data} />}</QueryState>
}

export function TodayPage() {
  const query = useQuery<Dashboard>({ queryKey: ['dashboard'], queryFn: getDashboard })
  const [board, setBoard] = useState<ThemeBoard>('industry')
  const hotGroups = useQuery({ queryKey: ['theme-board', board, TODAY_BOARD_LIMIT], queryFn: () => getThemeBoard(board, TODAY_BOARD_LIMIT) })
  const candidates = useQuery({ queryKey: ['candidates', 'latest'], queryFn: () => getCandidates() })
  const data = query.data
  const homeActions = Array.from(new Map(
    [...(data?.actions ?? []), ...(data?.candidates ?? [])]
      .filter((action) => action.action_state !== 'data_insufficient' || action.held === true || action.position_quantity_status === 'unknown')
      .map((action) => [`${action.instrument.exchange}:${action.instrument.symbol}:${action.as_of ?? ''}`, action] as const),
  ).values())
  const modeLabel = data?.mode === 'official' ? '官方單日快照' : data?.mode === 'official_partial' ? '官方單日快照（資料仍待補）' : '尚無官方快照'
  // PRODUCT_SPEC §2: header line → market overview → holding-risk alert → candidates → groups and news → watched stocks.
  return (
    <div className="page home-page">
      <TodayHeader
        loading={query.isLoading}
        asOf={data?.as_of}
        sourceLabel={data ? data.market.source_label ?? sourceLabel(data.market.source) : ''}
        modeLabel={modeLabel}
        badge={data && <QualityBadge kind="market" status={data.data_quality.latest_run} />}
        scopeText={data && `${data.scan_scope_label ?? '官方標的範圍；只有研究資料足夠的項目可進入行動摘要'} · ${data.market.instruments.toLocaleString()} 檔標的 · ${data.market.bars.toLocaleString()} 筆日行情 · ${homeActions.length.toLocaleString()} 筆行動摘要`}
        overview={data?.market_overview}
      />
    <QueryState loading={query.isLoading} error={query.error}>
      {data && (
        <>
          <MarketOverviewView overview={data.market_overview} />
          <HoldingAlert actions={data.actions ?? []} />
          <CandidatesSection data={candidates.data} loading={candidates.isLoading} error={candidates.error} />
          <div className="home-columns">
            <HotGroupsSection title={<Term id="hot_group">熱門族群</Term>} board={board} onBoardChange={setBoard} data={hotGroups.data} loading={hotGroups.isLoading} error={hotGroups.error} />
            <section className="home-news" aria-labelledby="home-news-title">
              <div className="section-head"><div><div className="eyebrow">市場基礎層 · 重大事件</div><h2 id="home-news-title">重點新聞</h2></div><Link to="/news" className="text-link">查看全部新聞</Link></div>
              {data.news?.length ? <div className="news-list-compact">{data.news.slice(0, 3).map((item) => <NewsCard key={item.id} item={item} compact />)}</div> : <div className="empty panel">市場新聞區尚無可顯示內容。</div>}
            </section>
          </div>
          <section className="section-head"><div><div className="eyebrow">使用者行動</div><h2>關注標的</h2></div><Link to="/actions" className="text-link">查看行動中心</Link></section>
          {homeActions.length ? <div className="action-grid">{homeActions.slice(0, 6).map((action) => <CompactActionCard key={action.instrument.exchange + action.instrument.symbol + (action.as_of ?? '')} action={action} />)}</div> : <div className="empty panel">{data.empty_states?.actions ?? '目前沒有可顯示的行動摘要。'}</div>}
          {data.data_quality.error && <div className="warning-box">官方擷取警告：{data.data_quality.error}</div>}
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
  const [searchParams, setSearchParams] = useSearchParams()
  const filters: NewsFilters = { tab: parseNewsTab(searchParams.get('tab')), q: searchParams.get('q') ?? '', symbol: searchParams.get('symbol') ?? '' }
  const [page, setPage] = useState(1)
  const [pageCursors, setPageCursors] = useState<Array<string | undefined>>([undefined])
  const cursor = pageCursors[page - 1]
  const params = newsListParams(filters, cursor)
  const query = useQuery({ queryKey: ['news', params], queryFn: () => getNews(params) })
  const resetPage = () => { setPage(1); setPageCursors([undefined]) }
  const changeFilters = (next: NewsFilters) => { setSearchParams(newsPageSearch(next), { replace: true }); resetPage() }
  const nextPage = (nextCursor: string) => { setPageCursors((current) => [...current.slice(0, page), nextCursor]); setPage(page + 1) }
  const previousPage = () => { if (page > 1) setPage(page - 1) }
  return <NewsListView filters={filters} onFiltersChange={changeFilters} query={{ data: query.data, loading: query.isLoading, error: query.error }} page={page} onNext={nextPage} onPrevious={previousPage} onReset={resetPage} />
}

function ThemesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const board = parseBoard(searchParams.get('board'))
  const [search, setSearch] = useState('')
  const query = useQuery({ queryKey: ['theme-board', board, THEME_BOARD_LIMIT], queryFn: () => getThemeBoard(board) })
  const changeBoard = (next: ThemeBoard) => setSearchParams(next === 'industry' ? {} : { board: next }, { replace: true })
  const suggestions = useQuery({ queryKey: ['theme-suggestions', THEME_SUGGESTION_LIMIT], queryFn: () => getThemeSuggestions(THEME_SUGGESTION_LIMIT) })
  const [expanded, setExpanded] = useState<number[]>([])
  const fullNews = useQueries({ queries: expanded.map((id) => ({ queryKey: ['theme-suggestion', id], queryFn: () => getThemeSuggestion(id) })) })
  const full: Record<number, SuggestionNewsState> = Object.fromEntries(expanded.map((id, index) => [id, { data: fullNews[index].data, loading: fullNews[index].isLoading, error: fullNews[index].error }]))
  const loadAll = (id: number) => setExpanded((current) => current.includes(id) ? current : [...current, id])
  return <ThemesBoardView board={board} onBoardChange={changeBoard} search={search} onSearchChange={setSearch} data={query.data} loading={query.isLoading} error={query.error}
    suggestions={<ThemeSuggestionsSection data={suggestions.data} loading={suggestions.isLoading} error={suggestions.error} full={full} onLoadAll={loadAll} />} />
}

function ThemePage() {
  const { themeId = '' } = useParams()
  const [memberPage, setMemberPage] = useState(1)
  useEffect(() => setMemberPage(1), [themeId])
  const detail = useQuery({ queryKey: ['theme', themeId], queryFn: () => getTheme(themeId), enabled: Boolean(themeId) })
  const detailBoard = detail.data?.board
  const board: ThemeBoard | null = detailBoard === 'industry' || detailBoard === 'theme' ? detailBoard : null
  // Rank, quality and the same-board percentiles come from the board itself (shared cache with /themes).
  const boardQuery = useQuery({ queryKey: ['theme-board', board, THEME_BOARD_LIMIT], queryFn: () => getThemeBoard(board as ThemeBoard), enabled: board !== null })
  const members = useQuery({ queryKey: ['theme-members', themeId, memberPage], queryFn: () => getThemeMembers(themeId, { page: memberPage, page_size: MEMBER_PAGE_SIZE, sort: 'price' }), enabled: Boolean(themeId) })
  const news = useQuery({ queryKey: ['theme-news', themeId], queryFn: () => getNews({ theme_id: themeId, limit: THEME_NEWS_LIMIT }), enabled: Boolean(themeId) })
  if (detail.isLoading) return <Loading />
  if (detail.error) return <ErrorBox error={detail.error} />
  if (!detail.data) return null
  return <ThemeDetailView
    detail={detail.data}
    board={{ data: boardQuery.data, loading: boardQuery.isLoading && board !== null, error: boardQuery.error }}
    members={{ data: members.data, loading: members.isLoading, error: members.error }}
    onMemberPageChange={setMemberPage}
    news={{ data: news.data, loading: news.isLoading, error: news.error }}
  />
}

function stockDirectoryColumns(dataAsOf: string | null): ReadonlyArray<Column<StockDirectoryRow>> {
  const instrumentOf = (row: StockDirectoryRow) => row.instrument ?? row
  return [
    { key: 'symbol', header: '代號', cell: (row) => { const instrument = instrumentOf(row); return <Link className="symbol-link" to={'/stocks/' + encodeURIComponent(instrument.exchange) + '/' + encodeURIComponent(instrument.symbol)}>{instrument.symbol}</Link> } },
    { key: 'name', header: '名稱', cell: (row) => instrumentOf(row).name },
    { key: 'exchange', header: '交易所', wideOnly: true, cell: (row) => marketDisplayLabel(instrumentOf(row).exchange) },
    { key: 'type', header: '類型', wideOnly: true, cell: (row) => instrumentTypeLabel(instrumentOf(row).instrument_type) },
    {
      // A column across stocks keeps two decimals (DESIGN_SYSTEM §3).
      key: 'close', header: '最近收盤', num: true, cell: (row) => {
        const closeDate = row.latest_price != null ? staleCloseDateLabel(row.price_as_of, dataAsOf) : null
        return <>{formatTableNumber(row.latest_price ?? row.latest_bar?.close, 2)}{closeDate && <div className="small-note">{closeDate}</div>}</>
      },
    },
    { key: 'action', header: '目前研究動作', cell: (row) => stockDirectoryActionLabel(row.action_state, row.action_label_zh) },
    { key: 'quality', header: '策略判斷資料', cell: (row) => <span className="pill">{stockDirectoryQualityLabel(row.data_quality)}</span> },
  ]
}

export function StockTable({ rows, dataAsOf }: { rows: StockDirectoryRow[]; dataAsOf: string | null }) {
  if (!rows.length) return <div className="empty panel">沒有符合條件的股票。</div>
  return <DataTable
    note="單位：價格為各標的報價幣別的元，指數為點。空白表示未提供資料或數值待核實；最近收盤早於最新交易日時，下方括號標出它的日期。"
    columns={stockDirectoryColumns(dataAsOf)}
    rows={rows}
    rowKey={(row) => (row.instrument ?? row).exchange + (row.instrument ?? row).symbol}
  />
}

function StocksPage() {
  // The navbar search lands here as /stocks?q=...
  const [searchParams] = useSearchParams()
  const navQuery = searchParams.get('q') ?? ''
  const [draft, setDraft] = useState(navQuery)
  const [search, setSearch] = useState(navQuery)
  const [page, setPage] = useState(1)
  useEffect(() => { setDraft(navQuery); setSearch(navQuery); setPage(1) }, [navQuery])
  const [type, setType] = useState('')
  const [watchlist, setWatchlist] = useState(false)
  const query = useQuery({ queryKey: ['stocks', { search, page, type, watchlist }], queryFn: () => getStocks({ q: search || undefined, page, page_size: 30, instrument_type: type || undefined, watchlist_only: watchlist || undefined }) })
  const submit = (value = draft.trim()) => { setSearch(value); setPage(1) }
  const clear = () => { setDraft(''); setSearch(''); setPage(1) }
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page">
    <PageTitle eyebrow="市場標的目錄" title="個股" description="股票、ETF 與新上市標的分開標示；行動與缺資料優先級只來自已驗證官方快照。">
      <div className="filter-row"><SearchBox draft={draft} query={search} placeholder="搜尋代號或名稱" onDraftChange={setDraft} onSubmit={submit} onClear={clear} /><select className="filter-select" value={type} onChange={(event) => { setType(event.target.value); setPage(1) }}><option value="">全部類型</option><option value="stock">股票</option><option value="etf">ETF</option><option value="ipo">新上市</option></select><label className="check-label"><input type="checkbox" checked={watchlist} onChange={(event) => { setWatchlist(event.target.checked); setPage(1) }} /> 我的自選</label></div>
    </PageTitle>
    {query.data.items.length ? <StockTable rows={query.data.items} dataAsOf={typeof query.data.meta.data_as_of === 'string' ? query.data.meta.data_as_of : null} /> : <div className="empty panel">沒有符合條件的標的。</div>}
    <DirectoryPagination meta={query.data.meta} onPageChange={setPage} />
  </div>}</QueryState>
}

function StockPage() {
  const { exchange = '', symbol = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const asOf = searchParams.get('as_of') ?? ''
  const [cutoffDraft, setCutoffDraft] = useState(asOf)
  const enabled = Boolean(exchange && symbol)
  const query = useQuery({ queryKey: ['stock', exchange, symbol, asOf], queryFn: () => getStock(exchange, symbol, asOf || undefined), enabled })
  const [barsInterval, setBarsInterval] = useState<StockBarsInterval>('day')
  // The header always reads the daily series; the chart reads the selected interval (same cache entry for 'day').
  const dayBars = useQuery({ queryKey: ['stock-bars', exchange, symbol, 'day'], queryFn: () => getStockBars(exchange, symbol, 'day'), enabled })
  const chartBars = useQuery({ queryKey: ['stock-bars', exchange, symbol, barsInterval], queryFn: () => getStockBars(exchange, symbol, barsInterval), enabled })
  useEffect(() => setCutoffDraft(asOf), [asOf])
  const [tab, setTab] = useState<StockTab>('chart')
  const stockNews = useQuery({ queryKey: ['stock-news', exchange, symbol], queryFn: () => getNews(stockNewsParams(symbol)), enabled: enabled && tab === 'news' })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorBox error={query.error} />
  if (!query.data) return null
  const data = query.data
  const candidate = data.bars[data.bars.length - 1]
  const latestBar = candidate && typeof candidate.close === 'number' && Number.isFinite(candidate.close) && candidate.close > 0 && typeof candidate.date === 'string' ? candidate : undefined
  const fallbackMarketComplete = Boolean(latestBar && typeof latestBar.source === 'string' && !latestBar.source.toLowerCase().includes('fixture'))
  const fallbackResearchStatus = data.decision_summary?.data_quality ?? 'missing'
  const fallbackResearchIncomplete = data.decision_summary?.action_state === 'data_insufficient' || fallbackResearchStatus !== 'complete'
  const qualitySummary = data.quality_summary ?? {
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
  const tabs: Array<{ id: StockTab; label: string }> = [
    { id: 'chart', label: '圖表與指標' },
    { id: 'chips', label: '法人籌碼' },
    { id: 'news', label: '新聞與公告' },
    { id: 'research', label: '研究條件' },
    { id: 'data', label: '資料說明' },
  ]
  return <div className="page stock-page">
    <Link to="/stocks" className="back-link">← 回到個股</Link>
    <StockHeader symbol={data.instrument.symbol} name={data.instrument.name} exchange={data.instrument.exchange} typeLabel={instrumentTypeLabel(data.instrument.instrument_type)} instrumentType={data.instrument.instrument_type} dailyBars={dayBars.data?.bars} loading={dayBars.isLoading}>
      <form className="overview-cutoff-control" onSubmit={(event) => { event.preventDefault(); const submitted = String(new FormData(event.currentTarget).get('as_of') ?? ''); const next = new URLSearchParams(searchParams); if (submitted) next.set('as_of', submitted); else next.delete('as_of'); setSearchParams(next) }}><label htmlFor="stock-cutoff">研究截止日期</label><input id="stock-cutoff" name="as_of" type="date" className="input" value={cutoffDraft} onInput={(event) => setCutoffDraft(event.currentTarget.value)} onChange={(event) => setCutoffDraft(event.target.value)} /><button type="submit" className="btn btn-secondary btn-sm">套用截止</button><button type="button" className="btn btn-ghost btn-sm" onClick={() => { const next = new URLSearchParams(searchParams); next.delete('as_of'); setSearchParams(next); setCutoffDraft('') }}>最新資料</button><span className="small-note">空白日期會使用最新資料日期；截止日期不影響頁首收盤、K 線與新聞時間線。</span></form>
    </StockHeader>
    <Tabs items={tabs} value={tab} onChange={setTab} label="個股詳情分頁" idPrefix="stock" className="stock-tabs" />
    <div className="stock-tab-content" id={tabPanelId('stock', tab)} role="tabpanel" aria-labelledby={tabId('stock', tab)}>
      {tab === 'chart' && <StockBarsChart interval={barsInterval} onIntervalChange={setBarsInterval} data={chartBars.data} loading={chartBars.isLoading} error={chartBars.error} instrumentType={data.instrument.instrument_type} />}
      {tab === 'chips' && <Card eyebrow="籌碼資料" title="法人與融資">{data.chips.length ? <ChipTable rows={data.chips.slice(-30).reverse()} /> : <EmptyState reason="尚無可核實的籌碼資料。" />}<BrokerBranchEntry exchange={data.instrument.exchange} /></Card>}
      {tab === 'news' && <><StockNewsTimeline exchange={data.instrument.exchange} symbol={data.instrument.symbol} query={{ data: stockNews.data, loading: stockNews.isLoading, error: stockNews.error }} /><StockEventList events={data.events} /></>}
      {tab === 'research' && <>{fallbackResearchIncomplete && <div className="data-gap stock-data-gap">研究資料待補：{qualitySummary.research.missing_fields.map(fieldLabel).join('、') || '尚不能形成完整策略判斷'}。</div>}<StockCandidatePanel candidate={data.candidate} /><ActionDetailPanel action={data.decision_summary ?? null} /><Card eyebrow="研究條件 · 只讀快照" title="族群與策略條件"><GroupList groups={data.groups} /><ConditionList conditions={data.strategy_conditions} /></Card></>}
      {tab === 'data' && <><CoveragePanel coverage={data.coverage} /><QualityPanel summary={qualitySummary} rows={data.data_quality} /><Card className="stock-source-panel" eyebrow="資料說明" title="原始時間、來源與技術指標"><div className="metric-row"><span>行情來源</span><b>{sourceLabel([...new Set(data.bars.map((bar) => bar.source).filter((source): source is string => typeof source === 'string'))])}</b></div><div className="metric-row"><span>回應產生時間</span><b>{formatTaiwanDateTime(data.response_generated_at)}</b></div><IndicatorMetaRows bars={dayBars.data} /><details className="technical-details"><summary>查看原始行情表</summary><BarTable rows={data.bars.slice(-30).reverse()} instrumentType={data.instrument.instrument_type} /></details></Card></>}
    </div>
    <p className="disclaimer">此為研究工具與資料摘要，不構成投資建議、報酬保證或自動下單指令。</p>
  </div>
}

// Indicator provenance from the daily bars API (docs/V1_SPEC.md 技術指標): version, price basis and batch time.
export function IndicatorMetaRows({ bars }: { bars: StockBarsResponse | undefined }) {
  if (!bars) return <div className="metric-row"><span>技術指標</span><b>待核實</b></div>
  const meta = bars.indicators
  return <>
    <div className="metric-row"><span>技術指標版本</span><b>{meta.formula_version}</b></div>
    <div className="metric-row"><span>價格基準</span><b>{meta.price_basis === 'as_of_date_raw_basis' ? '資料日原始價（前期依除權息換算）' : '待核實'}</b></div>
    <div className="metric-row"><span>日線指標計算時間</span><b>{meta.computed_at ? formatTaiwanDateTime(meta.computed_at) : '尚未計算'}</b></div>
    <div className="metric-row"><span>K 線資料日期</span><b>{formatDay(bars.data_as_of) ?? '待核實'}</b></div>
  </>
}

function GroupList({ groups }: { groups: InstrumentDetail['groups'] }) {
  if (!groups.length) return <div className="empty">尚無可顯示的族群歸屬。</div>
  return <div className="research-list">{groups.map((group) => <div className="research-list-item" key={group.id + '-' + group.valid_from}>
    <strong>{stockGroupLabel(group)}</strong>
    <span className="small-note">有效期間：{formatTaiwanDateTime(group.valid_from, true)}～{group.valid_to ? formatTaiwanDateTime(group.valid_to, true) : '截止日未提供'}</span>
  </div>)}</div>
}

function BrokerBranchEntry({ exchange }: { exchange: string }) {
  const url = exchange === 'TWSE' ? 'https://bsr.twse.com.tw/bshtm/bsMenu.aspx' : exchange === 'TPEx' ? 'https://www.tpex.org.tw/web/stock/aftertrading/broker_trading/brokerBS.php' : null
  return <section className="broker-branch-entry" aria-labelledby="broker-branch-title">
    <h3 id="broker-branch-title">券商／分點</h3>
    <p>尚未提供整合的券商分點買賣資料。</p>
    <p className="small-note">券商分點是交易通道，不能據此認定特定主力；與外資、投信、自營商的三大法人分類不同。</p>
    {url ? <><a className="text-link" href={url} target="_blank" rel="noreferrer">前往{exchange === 'TWSE' ? '證交所' : '櫃買中心'}官方券商買賣查詢</a><p className="small-note">官方查詢需人工輸入驗證碼。{exchange === 'TPEx' ? '櫃買中心僅提供當日資料。' : ''}請在官方頁面輸入股票代號並完成驗證。</p></> : <p className="small-note">市場尚未核實，暫無對應官方查詢入口。</p>}
  </section>
}

// One stock's prices share its latest close's tick decimals; lots are whole, the exact shares sit beside them.
export function BarTable({ rows, instrumentType }: { rows: InstrumentDetail['bars']; instrumentType: string }) {
  const digits = priceDigits(rows.find((row) => typeof row.close === 'number' && Number.isFinite(row.close))?.close, instrumentType)
  const columns: ReadonlyArray<Column<InstrumentDetail['bars'][number]>> = [
    { key: 'date', header: '日期', cell: (row) => formatTaiwanDateTime(row.date, true) },
    { key: 'close', header: '收盤', num: true, cell: (row) => formatTableNumber(row.close, digits) },
    { key: 'high', header: '最高', num: true, cell: (row) => formatTableNumber(row.high, digits) },
    { key: 'low', header: '最低', num: true, cell: (row) => formatTableNumber(row.low, digits) },
    { key: 'volume', header: '成交量', num: true, cell: (row) => formatTableVolume(row.volume, row.source, row.volume_exact) },
    { key: 'shares', header: '成交股數', num: true, cell: (row) => formatTableVolumeShares(row.volume, row.source, row.volume_exact) },
  ]
  return <DataTable
    wrapClassName="compact-table"
    note="單位：股價為各標的報價幣別的元，指數為點；成交量為張（股數 ÷ 1,000 四捨五入），成交股數為來源原值（股）。空白表示未提供資料、數值無效或成交量來源單位待核實。"
    columns={columns}
    rows={rows}
    rowKey={(row, index) => row.id ?? row.date ?? index}
  />
}

function formatRawChipValue(value: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-TW', { maximumFractionDigits: 3 }) : '未提供'
}

const CHIP_COLUMNS: ReadonlyArray<Column<InstrumentDetail['chips'][number]>> = [
  { key: 'date', header: '日期', cell: (row) => formatTaiwanDateTime(row.date, true) },
  { key: 'foreign', header: <Term id="foreign_flow">外資買賣超</Term>, num: true, cell: (row) => formatTableChip(row.foreign_buy, row.source) },
  { key: 'trust', header: <Term id="trust_flow">投信</Term>, num: true, cell: (row) => formatTableChip(row.trust_buy, row.source) },
  { key: 'dealer', header: <Term id="dealer_flow">自營商</Term>, num: true, cell: (row) => formatTableChip(row.dealer_buy, row.source) },
  { key: 'margin', header: <Term id="margin">融資增減</Term>, num: true, cell: (row) => formatTableChip(row.margin_change, row.source, true) },
]

export function ChipTable({ rows }: { rows: InstrumentDetail['chips'] }) {
  return <>
    <div className="small-note chip-unit-note">單位：張（三大法人為股數 ÷ 1,000 四捨五入，不足 500 股為 0）。三大法人為外資、投信、自營商；正值為買超，負值為賣超。融資正值為餘額增加，負值為減少。空白表示未提供資料、數值無效或來源單位待核實；原始股數與來源見下方說明。</div>
    <DataTable wrapClassName="compact-table" columns={CHIP_COLUMNS} rows={rows} rowKey={(row, index) => row.id ?? row.date ?? index} />
    <details className="technical-details chip-source-details"><summary>資料來源與原始值</summary><div className="chip-source-list">{rows.map((row) => <div className="chip-source-row" key={`${row.date}-${row.source}`}><strong>{formatTaiwanDateTime(row.date, true)}</strong><span>來源：{sourceLabel(row.source)}（{row.source || '來源未提供'}） · 資料截至：{formatTaiwanDateTime(row.data_as_of, true)} · 收集：{formatTaiwanDateTime(row.collected_at)}</span><span>來源稽核原值：外資（{isVerifiedChipFlowSource(row.source) ? '股' : '單位待核實'}） {formatRawChipValue(row.foreign_buy)} · 投信（{isVerifiedChipFlowSource(row.source) ? '股' : '單位待核實'}） {formatRawChipValue(row.trust_buy)} · 自營商（{isVerifiedChipFlowSource(row.source) ? '股' : '單位待核實'}） {formatRawChipValue(row.dealer_buy)} · 融資（{isVerifiedMarginSource(row.source) ? '張' : '單位待核實'}） {formatRawChipValue(row.margin_change)}</span></div>)}</div></details>
  </>
}

function ConditionList({ conditions }: { conditions: InstrumentDetail['strategy_conditions'] }) {
  return <div className="condition-list">{Object.entries(conditions).map(([name, condition]) => <div className="condition" key={name}><div className="condition-head"><strong><Term id={name === 'breakout' ? 'breakout' : 'pullback'}>{condition.label ?? strategyLabel(name)}</Term></strong><span className="muted">{researchSourceLabel(condition.source)}</span></div><div className="tag-list">{condition.requires.map((field) => <span className="tag" key={field}>{fieldLabel(field)}</span>)}</div>{condition.technical && <details className="technical-details"><summary>技術資訊</summary>{Object.values(condition.technical).map((value) => <div key={value}>{value}</div>)}</details>}</div>)}</div>
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

type StockTab = 'chart' | 'chips' | 'news' | 'research' | 'data'

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
        {action.trigger_price != null && <div><span>{levelFieldLabel('trigger_price', action.level_semantics)}</span><b className="level-entry">{formatNumber(action.trigger_price)}</b></div>}
        {action.entry_low != null && <div><span>{levelFieldLabel('entry_low', action.level_semantics)}</span><b className="level-entry">{formatNumber(action.entry_low)}</b></div>}
        {action.entry_high != null && <div><span>{levelFieldLabel('entry_high', action.level_semantics)}</span><b className="level-entry">{formatNumber(action.entry_high)}</b></div>}
        {action.invalid_price != null && <div><span><Term id="support">{levelFieldLabel('invalid_price', action.level_semantics)}</Term></span><b className="level-stop">{formatNumber(action.invalid_price)}</b></div>}
        {action.target_1 != null && <div><span><Term id="target">{levelFieldLabel('target_1', action.level_semantics)}</Term></span><b className="level-target">{formatNumber(action.target_1)}</b></div>}
        {action.risk_reward != null && <div><span><Term id="rr">風險報酬比</Term></span><b>{formatNumber(action.risk_reward)}</b></div>}
      </div>}
      {detailReasons.length > 0 && <ul className="reason-list">{detailReasons.map((reason) => <li key={reason}>{action.display_reasons ? reason : productActionReasonLabel(reason)}</li>)}</ul>}
      {action.conflicts.length > 0 && <div className="warning-box">{action.conflicts.join('；')}</div>}
      <div className="small-note">資料日：{formatTaiwanDateTime(action.data_cutoff, true)} · 價位語意：{levelSemanticsLabel(action.level_semantics)} · 規則與官方資料詳見資料說明。</div>
    </details>
  </section>
}

function StockEventList({ events }: { events: InstrumentDetail['events'] }) {
  return <>
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
  return <section className="panel portfolio-subsection"><div className="section-head"><div><div className="eyebrow">行動優先級</div><h2>我的庫存</h2></div><span className="small-note">庫存風險會優先於一般市場標的</span></div><p className="small-note">未核實行情的本地記錄與試算，可展開每筆庫存核對。</p><details className="portfolio-editor"><summary>新增庫存</summary><p className="small-note">每張為 1,000 股，可輸入整數張或零股股數。</p><form className="inline-form" onSubmit={save}><input aria-label="庫存代號" placeholder="代號" value={draft.symbol} onChange={(event) => setDraft({ ...draft, symbol: event.target.value })} /><select aria-label="交易所" className="filter-select" value={draft.exchange} onChange={(event) => setDraft({ ...draft, exchange: event.target.value })}><option value="">交易所</option><option value="TWSE">上市（TWSE）</option><option value="TPEx">上櫃（TPEx）</option></select><select aria-label="交易單位" className="filter-select" value={draft.unit} onChange={(event) => setDraft({ ...draft, unit: event.target.value as ShareUnit })}><option value="lot">單位：張</option><option value="odd_lot">單位：零股</option></select><input aria-label={draft.unit === 'lot' ? '張數' : '股數'} type="text" inputMode="numeric" placeholder={draft.unit === 'lot' ? '張數' : '股數'} value={draft.quantity} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })} /><input aria-label="平均成本／每股" type="text" inputMode="decimal" placeholder="平均成本／每股" value={draft.average_cost} onChange={(event) => setDraft({ ...draft, average_cost: event.target.value })} /><input aria-label="停損價" type="text" inputMode="decimal" placeholder="停損價" value={draft.stop_price} onChange={(event) => setDraft({ ...draft, stop_price: event.target.value })} /><button type="submit" className="secondary-button" disabled={busy !== null}>{busy === 'save' ? '儲存中…' : '儲存'}</button></form></details>{message && <div className="small-note">{message}</div>}{query.data?.items.length ? <div className="position-list">{query.data.items.map((position) => <div className="position-card" key={position.id}><div className="position-head"><Link className="symbol-link" to={'/stocks/' + encodeURIComponent(position.instrument?.exchange ?? '') + '/' + encodeURIComponent(position.instrument?.symbol ?? '')}>{position.instrument?.symbol ?? '—'} {position.instrument?.name ?? ''}</Link><button type="button" className="delete-button" disabled={busy !== null} onClick={() => remove(position.id)}>{busy === position.id ? '刪除中…' : '刪除'}</button></div><div className="position-quantity"><div>持有 {formatShareQuantity(position.shares, position.shares_exact)}</div></div><div className="small-note">平均成本（報價幣別元／股） {formatPortfolioValue(position.average_cost, position.portfolio_value_status, 'average_cost')} · 停損價（報價幣別元／股） {formatPortfolioValue(position.stop_price, position.portfolio_value_status, 'stop_price')} · 收盤狀態 {formatPortfolioClose(position.portfolio_quote)} · 市值（報價幣別元） {formatPositionValuation(position.market_value, position.valuation_status, 'market_value')} · 未實現損益（報價幣別元） {formatPositionValuation(position.unrealized_pnl, position.valuation_status, 'unrealized_pnl')}</div>
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

function ResearchBacktestPage() {
  const query = useQuery<BacktestSummary>({ queryKey: ['backtest-summary'], queryFn: () => getBacktestSummary() })
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page"><PageTitle eyebrow="研究詳細" title="技術回測" description="此頁只呈現固定規則的技術驗證；樣本不足時不輸出勝率或採用結論。" />{query.data.run ? <><div className="source-banner"><strong>{statusLabel(query.data.run.status)}</strong><span>資料截至 {formatTaiwanDateTime(query.data.run.data_as_of, true)}</span><QualityBadge status={query.data.run.assessment} /><span>可行動樣本 {query.data.run.zero_actionable_count}</span></div><BacktestTable groups={query.data.groups} /></> : <div className="empty panel">尚無回測紀錄。</div>}</div>}</QueryState>
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
  return <div className="page"><PageTitle eyebrow="研究詳細" title="官方資料回補與覆蓋度" description="此頁只讀取回補稽核紀錄與目前資料覆蓋度，不提供直接啟動正式回補的操作。"><Link className="text-link" to="/system/data-quality">前往系統資料品質</Link></PageTitle><section className="panel"><div className="section-head"><div><h2>最近一次回補</h2><div className="small-note">回補由受控工作流程執行，日期與來源均保留稽核紀錄。</div></div>{latest && <QualityBadge status={latest.status} />}</div>{latest ? <div className="metric-grid"><div className="metric-card"><span>日期範圍</span><b>{latest.metadata.start_date as string}～{latest.metadata.end_date as string}</b></div><div className="metric-card"><span>原定日曆日期</span><b>{requested} 日</b></div><div className="metric-card"><span>已驗證交易日</span><b>{verified}／{target} 日</b></div><div className="metric-card"><span>延伸補抓</span><b>{extensions} 日</b></div><div className="metric-card"><span>明確休市／無資料</span><b>{skipped} 日</b></div><div className="metric-card"><span>覆蓋目標</span><b>{manifest.target_met === true ? '已達成' : '尚未達成'}</b></div></div> : <div className="empty">尚無官方回補稽核紀錄。</div>}{latest?.error && <div className="data-gap">最近一次狀態說明：{latest.error}</div>}</section><section className="panel"><div className="section-head"><div><h2>目前市場資料覆蓋度</h2><div className="small-note">{summary?.baseline_message ?? coverage.data?.baseline?.message ?? '尚無可核實的官方交易日基準。'}</div></div>{summary && <QualityBadge kind="generic" status={coverageBadge} />}</div>{summary?.coverage_status === 'unknown' ? <div className="empty">尚未建立回補涵蓋基準；因此不計算全市場缺口原因。請先由受控流程產生回補稽核紀錄。</div> : summary ? <><div className="metric-grid"><div className="metric-card"><span>加權指數 已核實交易日</span><b>{summary.verified_taiex_sessions} 日{coverageStatus === 'snapshot' ? '（官方快照）' : ''}</b></div><div className="metric-card"><span>行情未滿 20 日</span><b>{summary.incomplete_to_20} 個標的</b></div><div className="metric-card"><span>行情未滿 60 日</span><b>{summary.incomplete_to_60} 個標的</b></div><div className="metric-card"><span>籌碼未滿 20 日</span><b>{summary.incomplete_chips_to_20} 個標的</b></div></div>{Object.keys(summary.coverage_reason_counts).length > 0 && <div className="tag-list">{Object.entries(summary.coverage_reason_counts).map(([reason, count]) => <span className="tag" key={reason}>{coverageReasonLabels[reason] ?? '其他資料缺口'}：{count}</span>)}</div>}<div className="small-note">回補目標：{summary.target_met === null ? '尚無回補稽核基準' : summary.target_met ? '已達成' : '尚未達成'}；事件資料：{summary.verified_event_sessions} 個已核實查詢日。</div></> : <div className="empty">尚無覆蓋度摘要。</div>}</section><section className="panel"><h2>回補紀錄</h2>{runs.data?.items.length ? <BackfillRunTable runs={runs.data.items} /> :<div className="empty">尚無回補紀錄。</div>}</section></div>
}

function SystemDataPage() {
  const quality = useQuery({ queryKey: ['quality'], queryFn: () => getDataQuality({ page: 1, page_size: 30 }) })
  const raw = useQuery({ queryKey: ['raw'], queryFn: () => getRawPayloads({ page: 1, page_size: 30 }) })
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => getIngestionRuns({ page: 1, page_size: 20 }) })
  const strategies = useQuery({ queryKey: ['strategies'], queryFn: () => getStrategies({ page: 1, page_size: 20 }) })
  const error = quality.error ?? raw.error ?? runs.error ?? strategies.error
  if (quality.isLoading || raw.isLoading || runs.isLoading || strategies.isLoading) return <Loading />
  if (error) return <ErrorBox error={error} />
  return <div className="page"><PageTitle eyebrow="系統頁" title="資料品質" description="管理型檢視：原始資料、擷取工作、資料品質與固定規則設定快照。"><div className="source-banner"><strong>官方資料</strong><span>此頁不在主導航，供稽核使用。</span></div><Link className="text-link" to="/research/coverage">查看官方資料回補與覆蓋度</Link></PageTitle><section className="panel"><h2>擷取狀態</h2><IngestionRunTable rows={runs.data?.items ?? []} /></section><section className="panel"><h2>原始來源</h2><RawTable rows={raw.data?.items ?? []} /></section><section className="panel"><h2>資料品質</h2><QualityTable rows={quality.data?.items ?? []} /></section><section className="panel"><h2>策略版本</h2><StrategyVersionList items={strategies.data?.items ?? []} variant="condition" labelFor={strategyLabel} badgeFor={(item) => <QualityBadge status={item.active ? 'complete' : 'inactive'} />} /></section></div>
}

const RAW_COLUMNS: ReadonlyArray<Column<RawPayload>> = [
  { key: 'collected', header: '擷取時間', cell: (row) => row.collected_at ?? '—' },
  { key: 'run', header: '資料批次', num: true, cell: (row) => formatTableNumber(row.ingestion_run_id, 0) },
  { key: 'source', header: '來源', cell: (row) => sourceLabel(row.source) },
  { key: 'date', header: '資料日', cell: (row) => row.data_as_of ?? '—' },
  { key: 'endpoint', header: '來源位置', cell: (row) => row.endpoint },
  { key: 'sha', header: '內容校驗碼', cellClassName: 'hash-cell', cell: (row) => row.sha256 ?? '—' },
]

export function RawTable({ rows }: { rows: RawPayload[] }) {
  if (!rows.length) return <div className="empty">尚無原始來源資料。</div>
  return <DataTable columns={RAW_COLUMNS} rows={rows} rowKey={(row) => row.id} />
}

type BacktestGroup = BacktestSummary['groups'][number]
const BACKTEST_COLUMNS: ReadonlyArray<Column<BacktestGroup>> = [
  { key: 'strategy', header: '策略', cell: (row) => `${strategyLabel(row.strategy)} · 規則版本 ${row.version}` },
  { key: 'type', header: '類型', cell: (row) => instrumentTypeLabel(row.instrument_type) },
  { key: 'horizon', header: '期限', num: true, cell: (row) => formatTableNumber(row.horizon, 0) },
  { key: 'sample', header: '樣本', num: true, cell: (row) => formatTableNumber(row.sample, 0) },
  { key: 'comparable', header: '可比', num: true, cell: (row) => formatTableNumber(row.comparable, 0) },
  { key: 'incomparable', header: '不可比', num: true, cell: (row) => formatTableNumber(row.incomparable, 0) },
  { key: 'assessment', header: '評估', cell: (row) => <QualityBadge status={row.assessment} /> },
]

export function BacktestTable({ groups }: { groups: BacktestGroup[] }) {
  return <DataTable note="期限為訊號日之後的交易日數；樣本、可比與不可比的單位為筆。空白表示未提供資料或數值待核實。" columns={BACKTEST_COLUMNS} rows={groups} rowKey={backtestGroupKey} />
}

const BACKFILL_COLUMNS: ReadonlyArray<Column<BackfillRun>> = [
  { key: 'updated', header: '更新時間', cell: (run) => formatTaiwanDateTime(run.updated_at) },
  { key: 'range', header: '資料範圍', cell: (run) => `${run.metadata.start_date as string}～${run.metadata.end_date as string}` },
  { key: 'status', header: '狀態', cell: (run) => <QualityBadge status={run.status} /> },
  { key: 'records', header: '筆數', num: true, cell: (run) => formatTableNumber(run.records, 0) },
  { key: 'error', header: '錯誤', cell: (run) => run.error ?? '—' },
]

export function BackfillRunTable({ runs }: { runs: BackfillRun[] }) {
  return <DataTable note="資料量單位：筆。空白表示未提供資料或數值待核實。" columns={BACKFILL_COLUMNS} rows={runs} rowKey={(run) => run.id} />
}

const INGESTION_COLUMNS: ReadonlyArray<Column<IngestionRun>> = [
  { key: 'updated', header: '更新', cell: (run) => formatTaiwanDateTime(run.updated_at) },
  { key: 'source', header: '來源', cell: (run) => sourceLabel(run.source) },
  { key: 'date', header: '資料日', cell: (run) => run.run_date },
  { key: 'status', header: '狀態', cell: (run) => <QualityBadge status={run.status} /> },
  { key: 'records', header: '筆數', num: true, cell: (run) => formatTableNumber(run.records, 0) },
  { key: 'asOf', header: '資料截至', cell: (run) => formatTaiwanDateTime(run.data_as_of, true) },
  { key: 'error', header: '錯誤', cell: (run) => run.error ?? '—' },
]

export function IngestionRunTable({ rows }: { rows: IngestionRun[] }) {
  return <DataTable note="資料量單位：筆。空白表示未提供資料或數值待核實。" columns={INGESTION_COLUMNS} rows={rows} rowKey={(run) => run.id} />
}

function QualityTable({ rows }: { rows: DataQualityRow[] }) {
  if (!rows.length) return <div className="empty">尚無資料品質紀錄。</div>
  return <div className="quality-list">{rows.map((row) => <div className="quality-line" key={row.entity_key + row.as_of_date}><span>{row.as_of_date} · {row.entity_key}</span><QualityBadge status={row.status} /><span>{row.missing_fields.map(fieldLabel).join('、') || '完整'}</span></div>)}</div>
}

function ResearchStrategiesPage() {
  const query = useQuery({ queryKey: ['strategies'], queryFn: () => getStrategies({ page: 1, page_size: 50 }) })
  return <QueryState loading={query.isLoading} error={query.error}>{query.data && <div className="page"><PageTitle eyebrow="研究詳細" title="策略版本" description="固定規則設定快照是稽核證據；產品行動摘要不改寫研究規則。" /><StrategyVersionList items={query.data.items} variant="panel" labelFor={strategyLabel} /></div>}</QueryState>
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
    <Route path="/system/data-quality" element={<SystemDataPage />} />
    <Route path="/research/backtest" element={<ResearchBacktestPage />} />
    <Route path="/research/coverage" element={<BackfillCoveragePage />} />
    <Route path="/research/strategies" element={<ResearchStrategiesPage />} />
    <Route path="/glossary" element={<GlossaryPage />} />
    <Route path="*" element={<NotFound />} />
  </Routes></Shell>
}
