import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import ReactEChartsModule from 'echarts-for-react'

import { Term } from '../components/Term'
import { Badge, Card, CardList, DataTable, DateBadge, EmptyState, ScoreBar, Skeleton, Stat, StrengthChip, Tabs, cx, tabId, tabPanelId, type Column } from '../components/ui'
import { newsSourceName, newsTime } from '../news/newsView'
import { officialEventDisplayTitle } from '../presentation'
import { isFiniteNumber, readChartTheme, type ChartTheme } from '../stock/stockBars'
import { formatFixed, formatTableNumber } from '../units'
import type {
  CandidatesResponse,
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
  THEME_BOARDS,
  boardDates,
  boardLabel,
  boardPagePath,
  buildTrendChartOption,
  candidateCountsByGroup,
  componentExtremes,
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

// A group's 1／5／20 日 relative return as a strength block (#654, DESIGN_SYSTEM §5 強弱色塊); the value is a fraction.
function GroupReturn({ window, value }: { window: { label: string }; value: number | null | undefined }) {
  return <StrengthChip label={`${window.label}相對加權指數`} percent={isFiniteNumber(value) ? value * 100 : null} />
}

// A same-board percentile (0–1) as a 0–100 score bar (#654); no data stays 「—」.
function ComponentBar({ label, value }: { label: string; value: number | null | undefined }) {
  return <ScoreBar label={label} value={isFiniteNumber(value) ? value * 100 : null} />
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

// ---- /themes: one board as one list of two-line rows (Issue 522, DESIGN_SYSTEM §5 族群榜, UI_COPY_SPEC §8.5 族群頁) ----

// The 說明 fold: what the page ranks, the units and blanks, and what the row's short forms mean.
function BoardHelp() {
  return (
    <details className="details board-help">
      <summary>說明</summary>
      <div className="board-help-body">
        <p>產業與題材各自成榜，依相對報酬、廣度、量能、法人與催化劑五分項計分；只有五分項完整的族群稱為熱門族群，熱門族群不另標，其他族群在名稱後標出資料完整度。</p>
        <p><Term id="heat_rank">分數</Term> 0–100，依分數<Term id="heat_rank">排名</Term>；五分項為<Term id="percentile">同榜百分位</Term>（0–100）；1／5／20 日為相對加權指數的報酬（%）；成員為有效／總數（檔）；「—」表示該項無資料。</p>
        <p>名稱後的兩個分項是五分項中最高與最低的一項。</p>
        <p>今日名單 N 檔是當日今日名單中屬於這個族群的檔數，沒有時不顯示。</p>
      </div>
    </details>
  )
}

function ComponentExtremes({ item }: { item: ThemeBoardItem }) {
  const extremes = componentExtremes(item.components)
  if (extremes.length === 0) return <span className="board-row-extremes">五分項無資料</span>
  const title = extremes.length === 2 ? `五分項最高：${extremes[0].label} ${formatComponent(extremes[0].value)}；最低：${extremes[1].label} ${formatComponent(extremes[1].value)}` : `五分項只有${extremes[0].label}有值`
  return (
    <span className="board-row-extremes" title={title}>
      {extremes.map((entry, index) => <span key={entry.key}>{index > 0 && '・'}{entry.label} <b>{formatComponent(entry.value)}</b></span>)}
    </span>
  )
}

// One group (Issue 522): rank, name, quality (only when it is not 熱門族群) and the highest and lowest components, then the
// three relative returns and 今日名單 N 檔; the score at the right, then the 五分項 button. The five components are a
// <details> under the row the button opens, so every row's components stay in the DOM (the screenshot tool opens them).
function BoardRow({ item, picks, open, onOpen }: { item: ThemeBoardItem; picks: number | null; open: boolean; onOpen: (open: boolean) => void }) {
  const detailId = `board-detail-${item.theme_id}`
  return (
    <li className={cx('board-row', open && 'board-row-open')} data-theme-id={item.theme_id}>
      <div className="board-row-main">
        <span className="board-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>
        <p className="board-row-title">
          <Link className="board-row-name" to={themeDetailPath(item.theme_id)}>{item.display_name}</Link>
          {item.quality !== 'complete' && <QualityBadge quality={item.quality} compact explain />}
          <ComponentExtremes item={item} />
        </p>
        <p className="board-row-meta">
          {RETURN_WINDOWS.map((window) => <span key={window.key}>{window.label} <GroupReturn window={window} value={item.relative_returns[window.key]} /></span>)}
          {picks !== null && picks > 0 && <Badge tone="primary" className="badge-compact board-row-picks">今日名單 {picks} 檔</Badge>}
        </p>
        <span className="board-row-score"><span>分數</span> <b>{formatScore(item.score)}</b></span>
        <button type="button" className="btn btn-ghost board-row-toggle" aria-expanded={open} aria-controls={detailId} onClick={() => onOpen(!open)}>五分項 {open ? '▾' : '▸'}</button>
      </div>
      <details className="board-row-detail" id={detailId} open={open} onToggle={(event) => onOpen(event.currentTarget.open)}>
        <summary>{item.display_name} 五分項</summary>
        <div className="board-row-detail-body">
          <dl className="board-components">
            {BOARD_COMPONENTS.map((component) => <div key={component.key}><dt>{component.label}</dt><dd><ComponentBar label={component.label} value={item.components[component.key]} /></dd></div>)}
            <div><dt>成員（檔）</dt><dd>{formatMembers(item.eligible_members, item.member_count)}</dd></div>
          </dl>
          <Link className="text-link" to={themeDetailPath(item.theme_id)}>族群詳情 →</Link>
        </div>
      </details>
    </li>
  )
}

function BoardList({ items, picks }: { items: readonly ThemeBoardItem[]; picks: ReadonlyMap<string, number> | null }) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set())
  const setTheme = (id: string, value: boolean) => setOpen((current) => {
    if (current.has(id) === value) return current
    const next = new Set(current)
    if (value) next.add(id)
    else next.delete(id)
    return next
  })
  return (
    <ol className="board-list">
      {items.map((item) => <BoardRow key={item.theme_id} item={item} picks={picks ? picks.get(item.theme_id) ?? 0 : null} open={open.has(item.theme_id)} onOpen={(value) => setTheme(item.theme_id, value)} />)}
    </ol>
  )
}

export function ThemeBoardPanel({ board, data, search, candidates }: { board: ThemeBoard; data: ThemeBoardResponse; search: string; candidates?: CandidatesResponse }) {
  const filtered = filterBoardItems(data.items, search)
  const picks = candidateCountsByGroup(candidates, data.meta.trading_date)
  return (
    <>
      <div className="board-toolbar">
        <span className="small-note">{boardLabel(board)}榜 · 共 {data.meta.total} 個族群{search.trim() ? ` · 符合搜尋 ${filtered.length} 個` : ''}</span>
        <BoardDateBadges meta={data.meta} />
        <BoardHelp />
      </div>
      {data.items.length === 0
        ? <Card><EmptyState reason={data.meta.empty_message ?? '此榜目前沒有族群'} /></Card>
        : filtered.length === 0
          ? <Card><EmptyState title="沒有符合的族群" reason="換個名稱關鍵字再試" /></Card>
          : <BoardList items={filtered} picks={picks} />}
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
  candidates,
}: {
  board: ThemeBoard
  onBoardChange: (board: ThemeBoard) => void
  search: string
  onSearchChange: (value: string) => void
  data: ThemeBoardResponse | undefined
  loading: boolean
  error: unknown
  // The latest 今日名單 list, counted per group on the rows (Issue 522); missing or of another day, the rows say nothing.
  candidates?: CandidatesResponse
}) {
  // The page explanation moved into the board's 說明 fold (Issue 522), so the title is only the eyebrow and the heading.
  return (
    <div className="page themes-page">
      <section className="page-title">
        <div className="eyebrow">族群排行</div>
        <h1>族群</h1>
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
            : data && <ThemeBoardPanel board={board} data={data} search={search} candidates={candidates} />}
      </div>
    </div>
  )
}

// ---- today: Top 5 per board ----

// Today page row (#510, UI_COPY_SPEC §8.5): two lines, rank, name, quality (only when it is not 熱門族群) and score,
// then the three relative returns; the date and 「相對加權指數」 are said once under the card head.
function HotGroupRow({ item }: { item: ThemeBoardItem }) {
  return (
    <Link className="hot-group-row" to={themeDetailPath(item.theme_id)} data-theme-id={item.theme_id}>
      <span className="hot-group-line">
        <span className="rank hot-group-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>
        <h3>{item.display_name}</h3>
        {item.quality !== 'complete' && <QualityBadge quality={item.quality} compact />}
        <span className="hot-group-score"><span>分數</span> <b>{formatScore(item.score)}</b></span>
      </span>
      <span className="hot-group-returns">
        {RETURN_WINDOWS.map((window) => <span key={window.key}>{window.label} <GroupReturn window={window} value={item.relative_returns[window.key]} /></span>)}
      </span>
    </Link>
  )
}

export const HOT_GROUP_RETURNS_NOTE = '1／5／20 日為相對加權指數的報酬'

export function HotGroupsSection({
  title = '熱門族群',
  board,
  onBoardChange,
  data,
  loading,
  error,
  className,
}: {
  title?: ReactNode
  board: ThemeBoard
  onBoardChange: (board: ThemeBoard) => void
  data: ThemeBoardResponse | undefined
  loading: boolean
  error: unknown
  className?: string
}) {
  // One head line (#510): title, the board tabs and 完整排行; the date and what the returns are relative to under it.
  return (
    <section className={cx('hot-groups', className)} aria-labelledby="hot-groups-title">
      <div className="panel-head">
        <h2 id="hot-groups-title">{title}</h2>
        <Tabs items={THEME_BOARDS} value={board} onChange={onBoardChange} label="熱門族群榜別" idPrefix="today-board" className="tabs-compact" />
        <Link to={boardPagePath(board)} className="text-link">完整排行 →</Link>
      </div>
      {data && <div className="hot-groups-dates"><BoardDateBadges meta={data.meta} /><span className="small-note">{HOT_GROUP_RETURNS_NOTE}</span></div>}
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
  { key: 'score', header: '分數（0–100）', num: true, cell: (point) => formatScore(point.score) },
  { key: 'rank', header: '排名', num: true, cell: (point) => formatRank(point.rank) },
  { key: 'quality', header: '品質', cell: (point) => qualityLabel(point.quality) },
  { key: 'members', header: '有效成員（檔）', num: true, cell: (point) => point.eligible_members ?? '—' },
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

// Rank, quality and the same-board percentiles come from the board request, so the page tells its four states apart:
// still loading and failed are never 「不在本日榜」 (UI_COPY_SPEC §8.5 族群詳情的名次與五分項, #463).
type BoardState = 'loading' | 'error' | 'off' | 'on'

function boardStateOf(board: QueryView<ThemeBoardResponse>, item: ThemeBoardItem | null): BoardState {
  if (item) return 'on'
  if (board.loading) return 'loading'
  return board.error ? 'error' : 'off'
}

function ComponentsCard({ detail, item, state, error }: { detail: ThemeDetail; item: ThemeBoardItem | null; state: BoardState; error: unknown }) {
  const metrics = detail.theme.metrics ?? {}
  const returns = item?.relative_returns ?? { '1d': metrics.relative_return_1d ?? null, '5d': metrics.relative_return_5d ?? null, '20d': metrics.relative_return_20d ?? null }
  return (
    <Card className="components-card" eyebrow={<><Term id="percentile">同榜百分位</Term> 0–100</>} title={<Term id="group_components">五分項</Term>} aside={<DateBadge date={formatDate(item?.trading_date ?? detail.theme.trading_date)} />}>
      {state === 'off' && <p className="small-note">此族群不在本日{boardLabel(detail.board)}榜（有效成員未達 3 檔或資料不足以計分），五分項沒有同榜百分位。</p>}
      {state === 'error' && <p className="small-note">榜單暫時無法載入：{errorReason(error)}</p>}
      {state === 'loading'
        ? <Skeleton lines={BOARD_COMPONENTS.length} className="inline-skeleton" label="五分項載入中…" />
        : <div className="metric-list">
          {BOARD_COMPONENTS.map((component) => <div className="metric-row" key={component.key}><span>{component.label}</span><ComponentBar label={component.label} value={item?.components[component.key]} /></div>)}
        </div>}
      <div className="metric-list components-returns">
        {RETURN_WINDOWS.map((window) => <div className="metric-row" key={window.key}><span>{window.label}相對加權指數</span><GroupReturn window={window} value={returns[window.key]} /></div>)}
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

// 候選 #N before 條件成立 (a candidate is always conditional) before 接近成立 (#277-B); the theme board adds 領先成員
// (UI_COPY_SPEC §8.5).
function MemberBadges({ row, withRole }: { row: MemberRow; withRole: boolean }) {
  const { candidate_rank: rank, conditional, near } = values(row)
  return <>
    {isFiniteNumber(rank)
      ? <Badge tone="primary" className="badge-compact">候選 #{rank}</Badge>
      : conditional ? <Badge className="badge-compact">條件成立</Badge> : near && <Badge tone="primary" className="badge-compact">接近成立</Badge>}
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

// The day's turnover (成交金額) in 億元, only when the source stated it (turnover_status available).
const turnoverText = (row: MemberRow) => {
  const { turnover, turnover_status: status } = values(row)
  return status === 'available' && isFiniteNumber(turnover) ? formatFixed(turnover / 1e8, 2) : ''
}

function memberColumns(withEvidence: boolean, membersAsOf: string | null): ReadonlyArray<Column<MemberRow>> {
  return [
    { key: 'symbol', header: '代號', cell: (row) => <Link className="symbol-link" to={memberPath(row)}>{row.symbol}</Link> },
    { key: 'name', header: '名稱', wrap: true, cellClassName: 'member-name-cell', cell: (row) => <><Link className="symbol-link" to={memberPath(row)}>{row.name}</Link> <MemberBadges row={row} withRole={withEvidence} /></> },
    { key: 'market', header: '市場', wideOnly: true, cell: (row) => marketLabel(row.exchange) },
    { key: 'close', header: '收盤（元）', num: true, cell: (row) => <MemberClose row={row} membersAsOf={membersAsOf} /> },
    { key: 'change', header: '漲跌幅（%）', num: true, cell: (row) => <MemberPercent value={values(row).change_status === 'known' ? values(row).change_pct : null} /> },
    { key: 'turnover', header: '成交金額（億元）', num: true, cell: turnoverText },
    { key: 'return5', header: '5 日相對（%）', num: true, cell: (row) => <MemberPercent value={values(row).excess_return_5d} /> },
    { key: 'return20', header: '20 日相對（%）', num: true, cell: (row) => <MemberPercent value={values(row).excess_return_20d} /> },
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
            <div><dt>成交金額（億元）</dt><dd>{turnoverText(row)}</dd></div>
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
  const state = boardStateOf(board, item)
  const rankDetail = {
    on: `${boardLabel(detail.board)}榜共 ${board.data?.meta.total ?? '—'} 個族群`,
    loading: '榜單載入中',
    error: '榜單暫時無法載入',
    off: '未列入本日榜單',
  }[state]
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
          <Stat label={<Term id="heat_rank">排名</Term>} value={state === 'loading' ? <Skeleton lines={1} className="inline-skeleton" label="排名載入中…" /> : formatRank(item?.rank)} detail={rankDetail} />
          <Stat label={<><Term id="heat_rank">分數</Term>（0–100）</>} value={formatScore(item?.score ?? detail.theme.score)} />
          <Stat label="有效成員／成員" value={formatMembers(item?.eligible_members ?? detail.theme.eligible_members, item?.member_count ?? detail.members_total)} detail="檔" />
        </div>
        {version && <div className="small-note">題材表版本 {version}</div>}
      </section>
      <div className="theme-detail-grid">
        <TrendCard trend={detail.trend} dataDate={formatDate(detail.trend.at(-1)?.trading_date ?? detail.data_as_of)} />
        <ComponentsCard detail={detail} item={item} state={state} error={board.error} />
      </div>
      <section className="section-head">
        <div><div className="eyebrow">成員資料截至 {formatDate(detail.members_as_of) ?? '日期未提供'}</div><h2>族群成員</h2></div>
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
