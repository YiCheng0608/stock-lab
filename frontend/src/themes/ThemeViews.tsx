import { useMemo } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import ReactEChartsModule from 'echarts-for-react'

import { Term } from '../components/Term'
import { Badge, Card, CardList, DataTable, DateBadge, EmptyState, Skeleton, Stat, Tabs, tabId, tabPanelId, type Column } from '../components/ui'
import { newsSourceName, newsTime } from '../news/newsView'
import { officialEventDisplayTitle } from '../presentation'
import { isFiniteNumber, readChartTheme, type ChartTheme } from '../stock/stockBars'
import { formatFixed, formatTableNumber } from '../units'
import type {
  NewsItem,
  ThemeBoard,
  ThemeBoardItem,
  ThemeBoardMeta,
  ThemeBoardResponse,
  ThemeDetail,
  ThemeEvidence,
  ThemeInlineMember,
  ThemeMemberRow,
  ThemeMemberSort,
  ThemeMembersResponse,
  ThemeTrendPoint,
} from '../types'
import {
  BOARD_COMPONENTS,
  DEFAULT_MEMBER_SORT,
  MEMBER_SORTS,
  RETURN_WINDOWS,
  TODAY_BOARD_LIMIT,
  THEME_BOARDS,
  boardDates,
  boardLabel,
  boardPagePath,
  buildTrendChartOption,
  evidenceUrl,
  filterBoardItems,
  formatComponent,
  formatDate,
  formatMembers,
  formatRank,
  formatScore,
  memberStaleDate,
  memberTableNote,
  memberTableRows,
  qualityLabel,
  qualityTone,
  relationLabel,
  relativeReturn,
  relevanceLabel,
  themeDefinitionVersion,
  themeDetailPath,
  trendHasEnoughPoints,
} from './themeBoards'

// Vite resolves the ESM default export; under plain Node (scripts/ci-test.cjs) the CJS build arrives as its module object.
const ReactECharts = (ReactEChartsModule as unknown as { default?: typeof ReactEChartsModule }).default ?? ReactEChartsModule

function documentTheme(): ChartTheme {
  const style = typeof document === 'undefined' ? null : getComputedStyle(document.documentElement)
  return readChartTheme((token) => style?.getPropertyValue(token) ?? '')
}

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後重新整理'
}

// `explain` makes 「事件資料待補」 a glossary term; leave it off inside a link (UI_COPY_SPEC §7).
export function QualityBadge({ quality, compact = false, explain = false }: { quality: string | null | undefined; compact?: boolean; explain?: boolean }) {
  const label = qualityLabel(quality)
  const pending = '事件資料待補'
  const at = explain ? label.indexOf(pending) : -1
  return (
    <Badge tone={qualityTone(quality)} className={compact ? 'badge-compact' : undefined}>
      {/* One inline span: the badge is a flex box, and bare children would each become a separate item. */}
      {at < 0 ? label : <span>{label.slice(0, at)}<Term id="event_data_pending">{pending}</Term>{label.slice(at + pending.length)}</span>}
    </Badge>
  )
}

function ReturnValue({ value, unit = '' }: { value: number | null | undefined; unit?: string }) {
  const { text, tone } = relativeReturn(value, unit)
  return <span className={`tone-${tone}`}>{text}</span>
}

export function BoardDateBadges({ meta }: { meta: Pick<ThemeBoardMeta, 'trading_date' | 'data_as_of'> }) {
  const { trading, dataAsOf } = boardDates(meta)
  return (
    <span className="board-dates">
      <DateBadge date={trading} />
      {dataAsOf && <Badge className="date-badge" title={`官方資料日期 ${dataAsOf}`}>官方資料 {dataAsOf}</Badge>}
    </span>
  )
}

// ---- /themes: one board as a desktop table and phone cards ----

const BOARD_TABLE_NOTE = <>分數 0–100；五分項為<Term id="percentile">同榜百分位</Term>（0–100）；1／5／20 日為相對加權指數的報酬（%）；成員為有效／總數（檔）；「—」表示該項無資料。</>

const BOARD_COLUMNS: ReadonlyArray<Column<ThemeBoardItem>> = [
  { key: 'rank', header: <Term id="heat_rank">排名</Term>, num: true, cell: (item) => item.rank },
  {
    key: 'name', header: '族群', cellClassName: 'board-name-cell', cell: (item) => <>
      <Link className="symbol-link" to={themeDetailPath(item.theme_id)}>{item.display_name}</Link>
      <QualityBadge quality={item.quality} compact explain />
    </>,
  },
  { key: 'score', header: <Term id="heat_rank">分數</Term>, num: true, cellClassName: 'board-score', cell: (item) => formatScore(item.score) },
  ...BOARD_COMPONENTS.map((component): Column<ThemeBoardItem> => ({ key: component.key, header: component.label, num: true, cell: (item) => formatComponent(item.components[component.key]) })),
  ...RETURN_WINDOWS.map((window): Column<ThemeBoardItem> => ({ key: window.key, header: window.label, num: true, cell: (item) => <ReturnValue value={item.relative_returns[window.key]} /> })),
  { key: 'members', header: '成員', num: true, cell: (item) => formatMembers(item.eligible_members, item.member_count) },
]

function BoardTable({ items }: { items: readonly ThemeBoardItem[] }) {
  return <DataTable wrapClassName="board-table-wrap" className="board-table" note={BOARD_TABLE_NOTE} columns={BOARD_COLUMNS} rows={items} rowKey={(item) => item.theme_id} rowProps={(item) => ({ 'data-theme-id': item.theme_id })} />
}

// 640px and below: one card per group, the first ten open (DESIGN_SYSTEM §5.1).
function BoardCards({ items }: { items: readonly ThemeBoardItem[] }) {
  return (
    <CardList className="board-cards" items={items} itemKey={(item) => item.theme_id} restLabel={(count) => `顯示其餘 ${count} 個族群`} renderCard={(item) => (
        <Link className="board-card" to={themeDetailPath(item.theme_id)}>
          <div className="board-card-head">
            <span className="rank">#{item.rank}</span>
            <strong>{item.display_name}</strong>
            <span className="board-card-score">{formatScore(item.score)}</span>
          </div>
          <QualityBadge quality={item.quality} compact />
          <dl className="board-card-grid">
            {BOARD_COMPONENTS.map((component) => <div key={component.key}><dt>{component.label}</dt><dd>{formatComponent(item.components[component.key])}</dd></div>)}
            {RETURN_WINDOWS.map((window) => <div key={window.key}><dt>{window.label}</dt><dd><ReturnValue value={item.relative_returns[window.key]} unit="%" /></dd></div>)}
            <div><dt>成員</dt><dd>{formatMembers(item.eligible_members, item.member_count)}</dd></div>
          </dl>
        </Link>
    )} />
  )
}

export function ThemeBoardPanel({ board, data, search }: { board: ThemeBoard; data: ThemeBoardResponse; search: string }) {
  const filtered = filterBoardItems(data.items, search)
  return (
    <>
      <div className="board-toolbar">
        <span className="small-note">{boardLabel(board)}榜 · 共 {data.meta.total} 個族群{search.trim() ? ` · 符合搜尋 ${filtered.length} 個` : ''}</span>
        <BoardDateBadges meta={data.meta} />
      </div>
      {data.items.length === 0
        ? <Card><EmptyState reason={data.meta.empty_message ?? '此榜目前沒有族群'} /></Card>
        : filtered.length === 0
          ? <Card><EmptyState title="沒有符合的族群" reason="換個名稱關鍵字再試" /></Card>
          : <><BoardTable items={filtered} /><BoardCards items={filtered} /></>}
    </>
  )
}

export function ThemesBoardView({
  board,
  onBoardChange,
  search,
  onSearchChange,
  data,
  loading,
  error,
  suggestions,
}: {
  board: ThemeBoard
  onBoardChange: (board: ThemeBoard) => void
  search: string
  onSearchChange: (value: string) => void
  data: ThemeBoardResponse | undefined
  loading: boolean
  error: unknown
  // News theme suggestions (#216), kept outside the ranked boards.
  suggestions?: ReactNode
}) {
  return (
    <div className="page">
      <section className="page-title">
        <div className="eyebrow">族群排行</div>
        <h1>族群</h1>
        <p>產業與題材各自成榜，依相對報酬、廣度、量能、法人與催化劑五分項計分；只有五分項完整的族群稱為熱門族群。</p>
      </section>
      <div className="board-controls">
        <Tabs items={THEME_BOARDS} value={board} onChange={onBoardChange} label="族群榜別" idPrefix="board" />
        <input
          className="search-input board-search"
          type="search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="以名稱篩選本榜"
          aria-label="以名稱篩選本榜"
        />
      </div>
      <div id={tabPanelId('board', board)} role="tabpanel" aria-labelledby={tabId('board', board)} className="board-panel">
        {loading
          ? <Skeleton lines={6} label="族群榜載入中…" />
          : error
            ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
            : data && <ThemeBoardPanel board={board} data={data} search={search} />}
      </div>
      {suggestions}
    </div>
  )
}

// ---- today: Top 5 per board ----

// Today page compact row (#276, UI_COPY_SPEC §8.5): rank, name, quality, score, relative returns and date on one row.
function HotGroupRow({ item }: { item: ThemeBoardItem }) {
  return (
    <Link className="hot-group-row" to={themeDetailPath(item.theme_id)} data-theme-id={item.theme_id}>
      <span className="rank hot-group-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>
      <h3>{item.display_name}</h3>
      <QualityBadge quality={item.quality} compact />
      <div className="hot-group-score"><span>分數</span><b>{formatScore(item.score)}</b></div>
      <dl className="hot-group-returns">
        {RETURN_WINDOWS.map((window) => <div key={window.key}><dt>{window.label}</dt><dd><ReturnValue value={item.relative_returns[window.key]} unit="%" /></dd></div>)}
      </dl>
      <div className="small-note">資料 {formatDate(item.trading_date) ?? '日期待核實'} · 相對加權指數</div>
    </Link>
  )
}

export function HotGroupsSection({
  title = '熱門族群',
  board,
  onBoardChange,
  data,
  loading,
  error,
}: {
  title?: ReactNode
  board: ThemeBoard
  onBoardChange: (board: ThemeBoard) => void
  data: ThemeBoardResponse | undefined
  loading: boolean
  error: unknown
}) {
  return (
    <section className="hot-groups" aria-labelledby="hot-groups-title">
      <div className="section-head">
        <div><div className="eyebrow">族群發現 · 各榜前 {TODAY_BOARD_LIMIT} 名</div><h2 id="hot-groups-title">{title}</h2></div>
        <Link to={boardPagePath(board)} className="text-link">查看完整排行</Link>
      </div>
      <div className="board-controls">
        <Tabs items={THEME_BOARDS} value={board} onChange={onBoardChange} label="熱門族群榜別" idPrefix="today-board" />
        {data && <BoardDateBadges meta={data.meta} />}
      </div>
      <div id={tabPanelId('today-board', board)} role="tabpanel" aria-labelledby={tabId('today-board', board)}>
        {loading
          ? <Skeleton lines={4} label="熱門族群載入中…" />
          : error
            ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
            : !data
              ? null
              : data.items.length === 0
                ? <Card><EmptyState reason={data.meta.empty_message ?? '此榜目前沒有族群'} /></Card>
                : <div className="hot-group-list">{data.items.map((item) => <HotGroupRow key={item.theme_id} item={item} />)}</div>}
      </div>
    </section>
  )
}

// ---- /themes/:id ----

const TREND_COLUMNS: ReadonlyArray<Column<ThemeTrendPoint>> = [
  { key: 'date', header: '日期', cell: (point) => formatDate(point.trading_date) ?? point.trading_date },
  { key: 'score', header: '分數', num: true, cell: (point) => formatScore(point.score) },
  { key: 'rank', header: '排名', num: true, cell: (point) => formatRank(point.rank) },
  { key: 'quality', header: '品質', cell: (point) => qualityLabel(point.quality) },
  { key: 'members', header: '有效成員', num: true, cell: (point) => point.eligible_members ?? '—' },
]

function TrendCard({ trend, dataDate }: { trend: readonly ThemeTrendPoint[]; dataDate: string | null }) {
  const theme = useMemo(documentTheme, [])
  const enough = trendHasEnoughPoints(trend)
  const option = useMemo(() => enough ? buildTrendChartOption(trend, theme) : null, [enough, trend, theme])
  return (
    <Card className="trend-card" eyebrow="近 20 個交易日" title="熱度走勢" titleId="theme-trend-title" aria-labelledby="theme-trend-title" aside={<DateBadge date={dataDate} />}>
      {option ? (
        <>
          <div className="trend-stage">
            <ReactECharts option={option} notMerge lazyUpdate autoResize opts={{ renderer: 'canvas' }} style={{ width: '100%', height: 240 }} role="img" aria-label="族群熱度分數走勢圖；數值見下方資料表" />
          </div>
          <details className="details chart-data-table">
            <summary>查看走勢資料表</summary>
            <DataTable note="分數 0–100；「—」表示當日無分數或未排名。" columns={TREND_COLUMNS} rows={[...trend].reverse()} rowKey={(point) => point.trading_date} />
          </details>
        </>
      ) : <EmptyState reason="走勢資料不足（需至少 2 個交易日的分數）" />}
    </Card>
  )
}

function ComponentsCard({ detail, item }: { detail: ThemeDetail; item: ThemeBoardItem | null }) {
  const metrics = detail.theme.metrics ?? {}
  const returns = item?.relative_returns ?? { '1d': metrics.relative_return_1d ?? null, '5d': metrics.relative_return_5d ?? null, '20d': metrics.relative_return_20d ?? null }
  return (
    <Card className="components-card" eyebrow={<><Term id="percentile">同榜百分位</Term> 0–100</>} title={<Term id="group_components">五分項</Term>} aside={<DateBadge date={formatDate(item?.trading_date ?? detail.theme.trading_date)} />}>
      {!item && <p className="small-note">此族群不在本日{boardLabel(detail.board)}榜（有效成員未達 3 檔或資料不足以計分），五分項沒有同榜百分位。</p>}
      <div className="metric-list">
        {BOARD_COMPONENTS.map((component) => <div className="metric-row" key={component.key}><span>{component.label}</span><b>{formatComponent(item?.components[component.key])}</b></div>)}
      </div>
      <div className="metric-list components-returns">
        {RETURN_WINDOWS.map((window) => <div className="metric-row" key={window.key}><span>{window.label}相對加權指數</span><b><ReturnValue value={returns[window.key]} unit="%" /></b></div>)}
      </div>
    </Card>
  )
}

function EvidenceCell({ evidence }: { evidence: ThemeEvidence | null | undefined }) {
  if (!evidence) return <span className="muted">證據待核實</span>
  const url = evidenceUrl(evidence)
  return (
    <span className="evidence-cell">
      <span>{relationLabel(evidence.relation)} · 關聯度{relevanceLabel(evidence.relevance)}</span>
      {url ? <a className="text-link" href={url} target="_blank" rel="noopener noreferrer">證據來源</a> : <span className="muted">來源連結未提供</span>}
    </span>
  )
}

function marketLabel(exchange: string): string {
  return exchange === 'TWSE' ? '上市' : exchange === 'TPEx' ? '上櫃' : '市場待核實'
}

// Member rows: the paginated endpoint's rows, or the detail's inline rows (no values) until a page arrives.
type MemberRow = ThemeMemberRow | ThemeInlineMember
const memberPath = (row: MemberRow) => '/stocks/' + encodeURIComponent(row.exchange) + '/' + encodeURIComponent(row.symbol)
const values = (row: MemberRow): Partial<ThemeMemberRow> => ('latest_bar' in row ? row : {})

// 候選 #N before 條件成立 (a candidate is always conditional); the theme board adds 領先成員 (UI_COPY_SPEC §8.5).
function MemberBadges({ row, withRole }: { row: MemberRow; withRole: boolean }) {
  const { candidate_rank: rank, conditional } = values(row)
  return <>
    {isFiniteNumber(rank) ? <Badge tone="primary" className="badge-compact">候選 #{rank}</Badge> : conditional && <Badge className="badge-compact">條件成立</Badge>}
    {withRole && row.role === 'leader' && <Badge className="badge-compact">領先成員</Badge>}
  </>
}

// A column across stocks keeps two decimals (DESIGN_SYSTEM §3); an older bar carries its date on the next line.
function MemberClose({ row, membersAsOf }: { row: MemberRow; membersAsOf: string | null }) {
  const stale = memberStaleDate(values(row), membersAsOf)
  return <>{formatTableNumber(values(row).latest_bar?.close, 2)}{stale && <span className="member-bar-date">資料 {stale}</span>}</>
}

// Percent of the change or a relative return; a blank cell instead of 「—」 in this table (UI_COPY_SPEC §8.4).
function MemberPercent({ value, unit = '' }: { value: number | null | undefined; unit?: string }) {
  if (!isFiniteNumber(value)) return null
  return <ReturnValue value={value} unit={unit} />
}

// Turnover in 億元, only when the source stated it (turnover_status available).
const turnoverText = (row: MemberRow) => {
  const { turnover, turnover_status: status } = values(row)
  return status === 'available' && isFiniteNumber(turnover) ? formatFixed(turnover / 1e8, 2) : ''
}

function memberColumns(withEvidence: boolean, membersAsOf: string | null): ReadonlyArray<Column<MemberRow>> {
  return [
    { key: 'symbol', header: '代號', cell: (row) => <Link className="symbol-link" to={memberPath(row)}>{row.symbol}</Link> },
    { key: 'name', header: '名稱', wrap: true, cellClassName: 'member-name-cell', cell: (row) => <><Link className="symbol-link" to={memberPath(row)}>{row.name}</Link> <MemberBadges row={row} withRole={withEvidence} /></> },
    { key: 'market', header: '市場', wideOnly: true, cell: (row) => marketLabel(row.exchange) },
    { key: 'close', header: '收盤', num: true, cell: (row) => <MemberClose row={row} membersAsOf={membersAsOf} /> },
    { key: 'change', header: '漲跌幅', num: true, cell: (row) => <MemberPercent value={values(row).change_status === 'known' ? values(row).change_pct : null} /> },
    { key: 'turnover', header: '成交值', num: true, cell: turnoverText },
    { key: 'return5', header: '5 日相對', num: true, cell: (row) => <MemberPercent value={values(row).excess_return_5d} /> },
    { key: 'return20', header: '20 日相對', num: true, cell: (row) => <MemberPercent value={values(row).excess_return_20d} /> },
    ...(withEvidence ? [{ key: 'evidence', header: '證據', cell: (row: MemberRow) => <EvidenceCell evidence={row.theme_evidence} /> }] : []),
  ]
}

export function ThemeMemberTable({ rows, withEvidence, membersAsOf = null }: { rows: ReadonlyArray<MemberRow>; withEvidence: boolean; membersAsOf?: string | null }) {
  return <DataTable
    wrapClassName="member-table-wrap"
    columns={memberColumns(withEvidence, membersAsOf)}
    rows={rows}
    rowKey={(row) => row.exchange + row.symbol}
  />
}

// 640px and below: one card per member, title row with close and change, then turnover and the two returns; the first ten open (DESIGN_SYSTEM §5, §5.1).
function ThemeMemberCards({ rows, withEvidence, membersAsOf }: { rows: ReadonlyArray<MemberRow>; withEvidence: boolean; membersAsOf: string | null }) {
  return (
    <CardList className="member-cards" items={rows} itemKey={(row) => row.exchange + row.symbol} renderCard={(row) => (
        <div className="member-card">
          <div className="member-card-head">
            <div className="member-card-name"><Link className="symbol-link" to={memberPath(row)}>{row.symbol} {row.name}</Link> <MemberBadges row={row} withRole={withEvidence} /></div>
            <div className="member-card-price">
              <MemberClose row={row} membersAsOf={membersAsOf} />
              <MemberPercent value={values(row).change_status === 'known' ? values(row).change_pct : null} unit="%" />
            </div>
          </div>
          <dl className="board-card-grid">
            <div><dt>成交值</dt><dd>{turnoverText(row)}</dd></div>
            <div><dt>5 日相對</dt><dd><MemberPercent value={values(row).excess_return_5d} unit="%" /></dd></div>
            <div><dt>20 日相對</dt><dd><MemberPercent value={values(row).excess_return_20d} unit="%" /></dd></div>
          </dl>
          {withEvidence && <div className="member-card-evidence"><EvidenceCell evidence={row.theme_evidence} /></div>}
        </div>
    )} />
  )
}

function MemberSortSelect({ value, onChange }: { value: ThemeMemberSort; onChange: (sort: ThemeMemberSort) => void }) {
  return (
    <label className="member-sort">
      <span>排序</span>
      <select className="filter-select" aria-label="成員排序" value={value} onChange={(event) => onChange(event.target.value as ThemeMemberSort)}>
        {MEMBER_SORTS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
      </select>
    </label>
  )
}

function MemberPager({ meta, onPageChange }: { meta: Record<string, unknown>; onPageChange: (page: number) => void }) {
  const page = Number(meta.page ?? 1)
  const totalPages = Number(meta.total_pages ?? 0)
  const total = Number(meta.total ?? 0)
  if (totalPages <= 1) return <div className="pagination-controls"><span>共 {total.toLocaleString()} 檔</span></div>
  return (
    <div className="pagination-controls">
      <span>第 {page}／{totalPages} 頁 · 共 {total.toLocaleString()} 檔</span>
      <div>
        <button type="button" className="secondary-button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一頁</button>
        <button type="button" className="secondary-button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>下一頁</button>
      </div>
    </div>
  )
}

// Same product_time reading as the news page (NEWS_SPEC §6): Taipei time for a known instant, the calendar day for date-only.
function NewsTime({ item }: { item: NewsItem }) {
  const time = newsTime(item)
  return <span className="news-list-time">{time.dateTime ? <time dateTime={time.dateTime}>{time.text}</time> : time.text}</span>
}

export function ThemeNewsList({ items }: { items: readonly NewsItem[] }) {
  if (!items.length) return <Card><EmptyState reason="此族群尚無已核實關聯的新聞" /></Card>
  return (
    <ul className="theme-news-list">
      {items.map((item) => (
        <li key={item.id}>
          <NewsTime item={item} />
          <Link className="theme-news-title" to={'/news/' + encodeURIComponent(item.id)}>{officialEventDisplayTitle(item.title)}</Link>
          <span className="small-note">{newsSourceName(item)}</span>
        </li>
      ))}
    </ul>
  )
}

export type QueryView<T> = { data: T | undefined; loading: boolean; error: unknown }

export function ThemeDetailView({
  detail,
  board,
  members,
  memberSort = DEFAULT_MEMBER_SORT,
  onMemberSortChange = () => undefined,
  onMemberPageChange,
  news,
}: {
  detail: ThemeDetail
  board: QueryView<ThemeBoardResponse>
  members: QueryView<ThemeMembersResponse>
  // The page owns the sort with the page number; a new sort starts at page 1 (#280).
  memberSort?: ThemeMemberSort
  onMemberSortChange?: (sort: ThemeMemberSort) => void
  onMemberPageChange: (page: number) => void
  news: QueryView<{ items: NewsItem[] }>
}) {
  const item = board.data?.items.find((row) => row.theme_id === detail.theme.theme_id) ?? null
  const isTheme = detail.board === 'theme'
  const rows = memberTableRows(detail, members.data)
  const membersAsOf = members.data?.members_as_of ?? detail.members_as_of
  const version = isTheme ? themeDefinitionVersion(detail, members.data?.items) : null
  const scoreDate = formatDate(item?.trading_date ?? detail.theme.trading_date)
  const backBoard: ThemeBoard = isTheme ? 'theme' : 'industry'
  return (
    <div className="page">
      <Link to={boardPagePath(backBoard)} className="back-link">← 回到{boardLabel(backBoard)}榜</Link>
      <section className="theme-header">
        <div className="theme-header-badges">
          <Badge tone="primary">{boardLabel(detail.board)}</Badge>
          <QualityBadge quality={item?.quality ?? detail.theme.data_quality} explain />
          <DateBadge date={scoreDate} />
        </div>
        <h1>{detail.theme.display_name}</h1>
        <p>{detail.theme.description}</p>
        <div className="theme-stats">
          <Stat label={<Term id="heat_rank">排名</Term>} value={formatRank(item?.rank)} detail={item ? `${boardLabel(detail.board)}榜共 ${board.data?.meta.total ?? '—'} 個族群` : board.loading ? '榜單載入中' : '未列入本日榜單'} />
          <Stat label={<><Term id="heat_rank">分數</Term>（0–100）</>} value={formatScore(item?.score ?? detail.theme.score)} />
          <Stat label="有效成員／成員" value={formatMembers(item?.eligible_members ?? detail.theme.eligible_members, item?.member_count ?? detail.members_total)} detail="檔" />
        </div>
        {version && <div className="small-note">題材表版本 {version}</div>}
      </section>
      <div className="theme-detail-grid">
        <TrendCard trend={detail.trend} dataDate={formatDate(detail.trend.at(-1)?.trading_date ?? detail.data_as_of)} />
        <ComponentsCard detail={detail} item={item} />
      </div>
      <section className="section-head">
        <div><div className="eyebrow">成員資料截至 {formatDate(detail.members_as_of) ?? '日期待核實'}</div><h2>族群成員</h2></div>
        <MemberSortSelect value={memberSort} onChange={onMemberSortChange} />
      </section>
      {members.error
        ? <Card><EmptyState title="成員資料暫時無法載入" reason={errorReason(members.error)} /></Card>
        : rows === null
          ? <Skeleton lines={5} label="成員載入中…" />
          : rows.length === 0
            ? <Card><EmptyState reason="此日期沒有有效成員" /></Card>
            : <>
              <p className="table-note member-note">{memberTableNote(rows.map(values), membersAsOf)}</p>
              <ThemeMemberTable rows={rows} withEvidence={isTheme} membersAsOf={membersAsOf} />
              <ThemeMemberCards rows={rows} withEvidence={isTheme} membersAsOf={membersAsOf} />
            </>}
      {members.data && <MemberPager meta={members.data.meta} onPageChange={onMemberPageChange} />}
      <section className="section-head"><div><div className="eyebrow">最多 10 則</div><h2>相關新聞</h2></div></section>
      {news.loading
        ? <Skeleton lines={3} label="新聞載入中…" />
        : news.error
          ? <Card><EmptyState title="新聞暫時無法載入" reason={errorReason(news.error)} /></Card>
          : <ThemeNewsList items={news.data?.items ?? []} />}
    </div>
  )
}
