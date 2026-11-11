import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { Badge, Card, EmptyState, Skeleton, Tabs, tabId, tabPanelId } from '../components/ui'
import { cx } from '../components/ui/cx'
import { officialEventDisplayTitle } from '../presentation'
import type { CursorPage, NewsAi, NewsItem } from '../types'
import {
  NEWS_RELATION_FILTERS,
  NEWS_TABS,
  NO_SUMMARY_TEXT,
  STOCK_NEWS_LIMIT,
  aiDirection,
  candidateCheckLabel,
  candidateCheckNote,
  candidateCheckSummary,
  candidateConfidenceLabel,
  candidateHref,
  candidateLabel,
  cardAiCandidates,
  cleanNewsLead,
  directionView,
  sourceDirectionView,
  formatTaipeiInstant,
  impactScopeLabel,
  matchesInstrument,
  namedAiCandidates,
  newsCategoryLabel,
  newsPageSearch,
  newsSourceName,
  newsTime,
  normalizeText,
  productTimeText,
  ruleVersion,
  sourceKindLabel,
  sourceLink,
  summaryPreview,
  usableAi,
  userFacingNewsThemes,
  verifiedInstruments,
  type CardAiCandidate,
  type DirectionView,
  type NewsFilters,
  type NewsTab,
} from './newsView'

export type QueryView<T> = { data: T | undefined; loading: boolean; error: unknown }

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後重新整理'
}

// The shown title (#523): the official event names, then the leading marks and byline cleared (NEWS_SPEC §6); the
// source title stays in the API and on /news/:id 技術資訊.
function newsTitle(item: Pick<NewsItem, 'title'>): string {
  return cleanNewsLead(officialEventDisplayTitle(item.title)) ?? '標題未提供'
}

function DirectionText({ view }: { view: DirectionView }) {
  return (
    <span className="news-direction">
      {view.tone && <i className={`direction-dot tone-${view.tone}`} aria-hidden="true" />}
      {view.label}
    </span>
  )
}

export function AiBadge() {
  return <Badge tone="accent" dot className="badge-compact">AI 推論</Badge>
}

function SourceLinkLine({ item }: { item: NewsItem }) {
  const link = sourceLink(item)
  return (
    <div className="news-source">
      {link.href
        ? <a href={link.href} target="_blank" rel="noopener noreferrer">{link.label}</a>
        : <span>{link.label}</span>}
      {link.note && <span className="small-note">{link.note}</span>}
    </div>
  )
}

// UI_COPY_SPEC §4 (#523): the relation filters' empty states name the filter; the watchlist one also says where to add.
function emptyReason(filters: NewsFilters): string {
  if (filters.watchlist) return '目前沒有與自選股相關的新聞。自選清單是空的時不會有結果；個股頁勾選「我的自選」可查看目前的自選股。'
  if (filters.verified) return '目前沒有符合條件、且有已核實標的的新聞。'
  return TAB_EMPTY[filters.tab]
}

function RelationFilterChips({ filters, onChange }: { filters: NewsFilters; onChange: (filters: NewsFilters) => void }) {
  return (
    <div className="filter-chips news-relation-filters" role="group" aria-label="新聞關聯篩選">
      {NEWS_RELATION_FILTERS.map(({ key, label }) => {
        const pressed = Boolean(filters[key])
        return <button key={key} type="button" className={cx('badge filter-chip', pressed && 'filter-chip-selected')} aria-pressed={pressed} onClick={() => onChange({ ...filters, [key]: !pressed })}>{label}</button>
      })}
    </div>
  )
}

function RelationChips({ item, hideEmpty = false }: { item: NewsItem; hideEmpty?: boolean }) {
  const instruments = verifiedInstruments(item)
  const themes = userFacingNewsThemes(item)
  if (!instruments.length && !themes.length) return hideEmpty ? null : <span className="small-note">未有已核實的標的或族群</span>
  const version = ruleVersion(item)
  return (
    <div className="news-chips">
      {version && <span className="small-note news-relation-source">規則核實 · {version}</span>}
      {instruments.map((instrument) => instrument.href
        ? <Link className="tag symbol-tag" key={instrument.key} to={instrument.href}>{instrument.label}</Link>
        : <span className="tag" key={instrument.key}>{instrument.label}</span>)}
      {themes.map((theme) => <Link className="tag" key={theme.theme_id} to={'/themes/' + encodeURIComponent(theme.theme_id)}>{theme.display_name}</Link>)}
    </div>
  )
}

// Listed candidates link to the stock page; emerging and delisted ones are plain text (#512, UI_COPY_SPEC §4).
function CandidateName({ candidate }: { candidate: Pick<CardAiCandidate, 'exchange' | 'symbol' | 'name' | 'listing'> }) {
  const href = candidateHref(candidate)
  const label = candidateLabel(candidate)
  return href ? <Link to={href}>{label}</Link> : <span>{label}</span>
}

// UI_COPY_SPEC §4 AI 候選行 / DESIGN_SYSTEM §5: inference kept apart from the verified chips, collapsed by default.
function AiCandidateRow({ item }: { item: NewsItem }) {
  const ai = usableAi(item)
  const candidates = cardAiCandidates(item)
  if (!ai || !candidates.length) return null
  return (
    <details className="news-ai-candidates" data-testid="news-ai-candidates">
      <summary>{candidateCheckSummary(candidates)}</summary>
      <ul>{candidates.map((candidate) => (
        <li key={candidate.key}>
          <CandidateName candidate={candidate} />
          <span className="news-ai-confidence">{` · ${candidateCheckLabel(candidate.source_check)} · ${candidateConfidenceLabel(candidate.confidence)}`}</span>
        </li>
      ))}</ul>
      <p className="small-note">{`模型 ${ai.model ?? '未記錄'} · 提示版本 ${ai.prompt_version ?? '未記錄'} · ${candidateCheckNote(ai)}`}</p>
    </details>
  )
}

// One card for /news and the stock timeline (DESIGN_SYSTEM §5 card, UI_COPY §4 order):
// category and source → title → summary preview → source time → impact → verified relations → AI candidates → source link.
export function NewsCard({ item }: { item: NewsItem }) {
  const time = newsTime(item)
  const ai = usableAi(item)
  const preview = summaryPreview(item)
  return (
    <article className="card news-card" data-testid="news-card" data-news-id={item.id}>
      <div className="news-card-meta">
        <Badge className="badge-compact news-source-badge">{newsSourceName(item)}</Badge>
        <span>{newsCategoryLabel(item.category)} · {sourceKindLabel(item.source_kind)}</span>
      </div>
      <h3 className="news-card-title"><Link to={'/news/' + encodeURIComponent(item.id)}>{newsTitle(item)}</Link></h3>
      <p className={preview ? 'news-card-summary' : 'news-card-summary muted'}>{preview ?? NO_SUMMARY_TEXT}</p>
      <div className="news-card-time">{time.dateTime ? <time dateTime={time.dateTime}>{time.text}</time> : time.text}</div>
      <div className="news-card-impact">
        {ai ? <><DirectionText view={aiDirection(ai)} /><AiBadge /></> : <DirectionText view={directionView(item.impact_direction)} />}
      </div>
      <RelationChips item={item} />
      <AiCandidateRow item={item} />
      <SourceLinkLine item={item} />
    </article>
  )
}

function ImpactText({ item }: { item: NewsItem }) {
  const ai = usableAi(item)
  return ai ? <><DirectionText view={aiDirection(ai)} /><AiBadge /></> : <DirectionText view={directionView(item.impact_direction)} />
}

function InstrumentTag({ instrument }: { instrument: ReturnType<typeof verifiedInstruments>[number] }) {
  return instrument.href
    ? <Link className="tag symbol-tag" to={instrument.href}>{instrument.label}</Link>
    : <span className="tag">{instrument.label}</span>
}

// What the /news row keeps collapsed (#523, UI_COPY_SPEC §4): category and source kind, the summary preview, the verified
// relations (with the rule version), the AI candidates and the source link; no line for a missing relation.
function NewsRowDetail({ item }: { item: NewsItem }) {
  const preview = summaryPreview(item)
  return (
    <div className="news-row-detail-body">
      <div className="news-row-kind">{newsCategoryLabel(item.category)} · {sourceKindLabel(item.source_kind)}</div>
      <p className={preview ? 'news-row-summary' : 'news-row-summary muted'}>{preview ?? NO_SUMMARY_TEXT}</p>
      <RelationChips item={item} hideEmpty />
      <AiCandidateRow item={item} />
      <div className="news-row-links">
        <SourceLinkLine item={item} />
        <Link className="text-link" to={'/news/' + encodeURIComponent(item.id)}>詳情 →</Link>
      </div>
    </div>
  )
}

// One /news item (#523, DESIGN_SYSTEM §5 新聞清單): the title on line 1; source · time · direction (「AI 推論」 after an AI
// direction) and the verified instrument tags on line 2; 「展開」 opens the rest in a <details> under the row, so the
// screenshot tool can open them all. Every part is a grid or flex item, so each is its own line of page text (page_checks
// N2–N4). Line two is one element (`display: contents` on wide screens) so phones can lay it out as one unwrapped flex line,
// with the direction moved up beside the title as on the today page.
export function NewsListRow({ item, open, onOpen }: { item: NewsItem; open: boolean; onOpen: (open: boolean) => void }) {
  const time = newsTime(item)
  const title = newsTitle(item)
  const instruments = verifiedInstruments(item)
  const detailId = `news-row-detail-${item.id}`
  return (
    <li className={cx('news-row', open && 'news-row-open')} data-testid="news-card" data-news-id={item.id}>
      <div className="news-row-main">
        <h3 className="news-row-title"><Link to={'/news/' + encodeURIComponent(item.id)} title={title}>{title}</Link></h3>
        <span className="news-row-impact"><ImpactText item={item} /></span>
        <div className="news-row-line2">
          <span className="news-row-source">{newsSourceName(item)}</span>
          <span className="news-row-sep" aria-hidden="true">·</span>
          {time.dateTime ? <time className="news-row-time" dateTime={time.dateTime}>{time.text}</time> : <span className="news-row-time">{time.text}</span>}
          {instruments.length > 0 && <span className="news-row-tags">{instruments.map((instrument) => <InstrumentTag key={instrument.key} instrument={instrument} />)}</span>}
          <button type="button" className="btn btn-ghost news-row-toggle" aria-expanded={open} aria-controls={detailId} onClick={() => onOpen(!open)}>{open ? '收合' : '展開'}</button>
        </div>
      </div>
      <details className="news-row-detail" id={detailId} open={open} onToggle={(event) => onOpen(event.currentTarget.open)}>
        <summary>{title}</summary>
        <NewsRowDetail item={item} />
      </details>
    </li>
  )
}

export function NewsList({ items, emptyReason }: { items: readonly NewsItem[]; emptyReason: string }) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set())
  if (!items.length) return <Card><EmptyState reason={emptyReason} /></Card>
  const toggle = (id: string, next: boolean) => setOpen((current) => {
    if (current.has(id) === next) return current
    const copy = new Set(current)
    if (next) copy.add(id)
    else copy.delete(id)
    return copy
  })
  return <ol className="news-row-list">{items.map((item) => <NewsListRow key={item.id} item={item} open={open.has(item.id)} onOpen={(next) => toggle(item.id, next)} />)}</ol>
}

export function NewsCardList({ items, emptyReason, timeline = false }: { items: readonly NewsItem[]; emptyReason: string; timeline?: boolean }) {
  if (!items.length) return <Card><EmptyState reason={emptyReason} /></Card>
  return <div className={timeline ? 'news-cards news-timeline' : 'news-cards'}>{items.map((item) => <NewsCard key={item.id} item={item} />)}</div>
}

const TAB_EMPTY: Record<NewsTab, string> = {
  domestic: '目前沒有符合條件的國內新聞。',
  international: '目前沒有符合條件的國際新聞。',
  official: '目前沒有符合條件的官方公告。',
}

function NewsFilterForm({ filters, onSubmit }: { filters: NewsFilters; onSubmit: (filters: NewsFilters) => void }) {
  // Keyed on the applied values, so a URL change resets the drafts.
  const [q, setQ] = useState(filters.q)
  const [symbol, setSymbol] = useState(filters.symbol)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit({ ...filters, q: q.trim(), symbol: symbol.trim() })
  }
  const clear = () => { setQ(''); setSymbol(''); onSubmit({ ...filters, q: '', symbol: '' }) }
  return (
    <form className="news-filters" onSubmit={submit} role="search">
      <input className="search-input" type="search" value={q} onChange={(event) => setQ(event.target.value)} placeholder="搜尋標題、摘要或來源" aria-label="搜尋新聞" />
      <input className="search-input news-symbol-input" type="search" value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="股票代號" aria-label="依股票代號篩選" inputMode="numeric" />
      <button type="submit" className="secondary-button">搜尋</button>
      {(filters.q || filters.symbol || q || symbol) && <button type="button" className="secondary-button" onClick={clear}>清除</button>}
    </form>
  )
}

export function NewsListView({
  filters,
  onFiltersChange,
  query,
  page,
  onNext,
  onPrevious,
  onReset,
}: {
  filters: NewsFilters
  onFiltersChange: (filters: NewsFilters) => void
  query: QueryView<CursorPage<NewsItem>>
  page: number
  onNext: (cursor: string) => void
  onPrevious: () => void
  onReset: () => void
}) {
  const data = query.data
  return (
    <div className="page news-page">
      <section className="page-title news-page-title">
        <h1>新聞</h1>
        <p>國內、國際財經新聞與官方公告；每則標示來源與時間，AI 摘要與判讀另標「AI 推論」。</p>
      </section>
      <div className="news-controls">
        <Tabs items={NEWS_TABS} value={filters.tab} onChange={(tab) => onFiltersChange({ ...filters, tab })} label="新聞分類" idPrefix="news" />
        <NewsFilterForm key={JSON.stringify(newsPageSearch(filters))} filters={filters} onSubmit={onFiltersChange} />
      </div>
      <RelationFilterChips filters={filters} onChange={onFiltersChange} />
      <div id={tabPanelId('news', filters.tab)} role="tabpanel" aria-labelledby={tabId('news', filters.tab)} className="news-panel">
        {query.loading
          ? <Skeleton lines={6} label="新聞載入中…" />
          : query.error
            ? <Card><EmptyState title="新聞暫時無法載入" reason={errorReason(query.error)} /></Card>
            : data && <>
              <NewsList key={JSON.stringify(newsPageSearch(filters))} items={data.items} emptyReason={emptyReason(filters)} />
              {(data.items.length > 0 || page > 1) && (
                <div className="pagination-controls">
                  <span>第 {page} 頁 · 本頁 {data.items.length} 則{data.meta.total == null ? '' : ` · 共 ${data.meta.total.toLocaleString()} 則`}</span>
                  <div>
                    <button type="button" className="secondary-button" disabled={page <= 1} onClick={onPrevious}>上一頁</button>
                    <button type="button" className="secondary-button" disabled={!data.meta.next_cursor} onClick={() => data.meta.next_cursor && onNext(data.meta.next_cursor)}>下一頁</button>
                    <button type="button" className="secondary-button" disabled={page <= 1} onClick={onReset}>回到第一頁</button>
                  </div>
                </div>
              )}
            </>}
      </div>
    </div>
  )
}

// NEWS_SPEC §5 / DESIGN_SYSTEM §7: LLM output sits in its own block with the accent bar and the 「AI 推論」 badge.
export function AiInferencePanel({ ai }: { ai: NewsAi | null }) {
  if (!ai) {
    return (
      <section className="ai-inference" aria-labelledby="ai-inference-title">
        <div className="ai-inference-head"><h2 id="ai-inference-title">AI 摘要與判讀</h2><AiBadge /></div>
        <p className="muted">此則尚未產生 AI 摘要與判讀。</p>
      </section>
    )
  }
  const named = namedAiCandidates(ai.symbol_candidates)
  const proposedAny = ai.symbol_candidates.length > 0 || (ai.hidden_symbol_candidates?.length ?? 0) > 0
  const generated = formatTaipeiInstant(ai.generated_at)
  return (
    <section className="ai-inference" aria-labelledby="ai-inference-title" data-testid="ai-inference">
      <div className="ai-inference-head"><h2 id="ai-inference-title">AI 摘要與判讀</h2><AiBadge /></div>
      {ai.unsupported && <p className="data-gap">模型判斷此則與台股標的或市場沒有直接關聯，不給方向。</p>}
      <dl className="ai-fields">
        <div><dt>AI 摘要</dt><dd>{normalizeText(ai.summary) ?? '模型未產生摘要'}</dd></div>
        <div><dt>方向</dt><dd><DirectionText view={aiDirection(ai)} /> · 範圍：{impactScopeLabel(ai.impact_scope)}</dd></div>
        <div><dt>理由</dt><dd>{normalizeText(ai.impact_rationale) ?? '模型未提供理由'}</dd></div>
      </dl>
      <h3 className="ai-subtitle">候選標的</h3>
      {named.length
        ? <ul className="ai-candidates">{named.map((candidate) => (
          <li key={`${candidate.exchange}:${candidate.symbol}`}>
            <CandidateName candidate={candidate} />
            <span className="small-note">{`${candidateCheckLabel(candidate.source_check)} · ${candidateConfidenceLabel(candidate.confidence)}${normalizeText(candidate.reason) ? ` · ${normalizeText(candidate.reason)}` : ''}`}</span>
          </li>
        ))}</ul>
        : <p className="small-note">{proposedAny ? '模型提出的候選代號都查無對應標的，不列出。' : '模型未提出候選標的。'}</p>}
      {ai.theme_candidates.length > 0 && <>
        <h3 className="ai-subtitle">候選題材 <Badge tone="success" className="badge-compact">已通過題材核對</Badge></h3>
        <ul className="ai-candidates">{ai.theme_candidates.map((candidate) => (
          <li key={candidate.theme}><span>{candidate.theme}</span>{normalizeText(candidate.reason) && <span className="small-note">{normalizeText(candidate.reason)}</span>}</li>
        ))}</ul>
      </>}
      <p className="small-note ai-meta">模型 {ai.model ?? '未記錄'} · 提示版本 {ai.prompt_version ?? '未記錄'} · 產生時間 {generated ?? '待核實'} · {candidateCheckNote(ai)}候選標的與題材都不作為交易理由。</p>
    </section>
  )
}

export function NewsDetailView({ item }: { item: NewsItem }) {
  const time = newsTime(item)
  const summary = normalizeText(item.summary)
  const description = normalizeText(item.description)
  const title = newsTitle(item)
  return (
    <div className="page news-detail-page">
      <Link to="/news" className="back-link">← 回到新聞</Link>
      <section className="page-title">
        <div className="eyebrow">{newsCategoryLabel(item.category)} · {sourceKindLabel(item.source_kind)}</div>
        <h1 className="news-detail-title">{title}</h1>
      </section>
      <div className="news-detail-grid">
        <Card as="article" className="news-facts" eyebrow="來源事實" title={newsSourceName(item)} data-testid="news-facts">
          <div className="news-card-time">{time.dateTime ? <time dateTime={time.dateTime}>{time.text}</time> : time.text}</div>
          {item.time_consistency === 'conflict' && <div className="warning-box">資料集事件日期與公告內容提及日期不一致，時間待人工核實。</div>}
          <p className={summary ? 'news-detail-body' : 'news-detail-body muted'}>{summary ?? NO_SUMMARY_TEXT}</p>
          {description && description !== summary && (
            <details className="news-full">
              <summary>展開公告內容</summary>
              <p className="news-detail-body">{description}</p>
            </details>
          )}
          <div className="news-detail-section"><span className="news-detail-label">影響</span><DirectionText view={sourceDirectionView(item.impact_direction)} /></div>
          <div className="news-detail-section"><span className="news-detail-label">已核實關聯</span><RelationChips item={item} /></div>
          <SourceLinkLine item={item} />
          <details className="technical-details">
            <summary>技術資訊</summary>
            <div>來源類型：{sourceKindLabel(item.source_kind)}</div>
            <div>系統收錄時間：{productTimeText(item.product_time, 'collected_at')}</div>
            {item.impact?.method && <div>關聯方法：{item.impact.method.startsWith('rule:') ? `規則比對（名稱／簡稱／代號）${ruleVersion(item) ? ` · 規則版本 ${ruleVersion(item)}` : ''}` : '來源標示'}</div>}
            {item.title && title !== normalizeText(item.title) && <div>原始標題：{item.title}</div>}
            <div>原始資料識別碼：{item.provenance?.raw_payload_id ?? '—'} · 事件識別碼：{item.provenance?.event_id ?? '—'}</div>
            <div>來源位置：{item.provenance?.endpoint ?? '—'}</div>
          </details>
        </Card>
        <AiInferencePanel ai={usableAi(item)} />
      </div>
    </div>
  )
}

// Stock page 「新聞與公告」 tab: the latest STOCK_NEWS_LIMIT items of /api/news?symbol=, exact exchange + symbol only.
export function StockNewsTimeline({ exchange, symbol, query }: { exchange: string; symbol: string; query: QueryView<CursorPage<NewsItem>> }) {
  const head = (
    <div className="section-head news-timeline-head">
      <div><div className="eyebrow">新聞時間線 · 最近 {STOCK_NEWS_LIMIT} 則</div><h2>{symbol} 相關新聞</h2></div>
      <Link className="text-link" to={`/news?symbol=${encodeURIComponent(symbol)}`}>在新聞頁搜尋</Link>
    </div>
  )
  if (query.loading) return <>{head}<Skeleton lines={4} label="新聞載入中…" /></>
  if (query.error) return <>{head}<Card><EmptyState title="新聞暫時無法載入" reason={errorReason(query.error)} /></Card></>
  const items = (query.data?.items ?? []).filter((item) => matchesInstrument(item, exchange, symbol))
  return <>{head}<NewsCardList items={items} emptyReason="尚無與此股已核實關聯的新聞或公告。" timeline /></>
}
