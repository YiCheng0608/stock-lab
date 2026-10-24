// #245 AC-3 temporary single-page change, reverted next
import { Link } from 'react-router-dom'

import { Badge, Card, EmptyState, Skeleton } from '../components/ui'
import { AiBadge } from '../news/NewsViews'
import type { ThemeSuggestion, ThemeSuggestionNews, ThemeSuggestionsResponse } from '../types'
import { formatDate } from './themeBoards'
import {
  SUGGESTION_EMPTY_REASON,
  SUGGESTION_EMPTY_TEXT,
  SUGGESTION_NOTE,
  hiddenNewsCount,
  suggestionConfidenceLabel,
  suggestionDates,
  suggestionVersionLine,
  suggestionUpdatedText,
} from './themeSuggestions'

export type SuggestionNewsState = { data: ThemeSuggestion | undefined; loading: boolean; error: unknown }

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後再試'
}

function SuggestionNewsList({ news }: { news: readonly ThemeSuggestionNews[] }) {
  return (
    <ul className="ai-candidates suggestion-news">
      {news.map((item) => (
        <li key={item.news_id}>
          <Link to={`/news/${item.news_id}`}>{item.title}</Link>
          <span className="small-note">{item.source_name} · 新聞日 {formatDate(item.news_date) ?? '待核實'} · 判讀題材「{item.theme_text}」</span>
          {item.reason && <span className="small-note">理由：{item.reason}</span>}
        </li>
      ))}
    </ul>
  )
}

function SuggestionCard({
  item,
  full,
  onLoadAll,
}: {
  item: ThemeSuggestion
  full: SuggestionNewsState | undefined
  onLoadAll: (id: number) => void
}) {
  const hidden = hiddenNewsCount(item)
  const news = full?.data?.news ?? item.news
  return (
    <article className="ai-inference theme-suggestion" data-suggestion-id={item.id}>
      <div className="ai-inference-head">
        <h3>{item.display_name}</h3>
        <span className="theme-suggestion-badges">
          <Badge tone="warning" className="badge-compact">待核實</Badge>
          <AiBadge />
        </span>
      </div>
      <p className="theme-suggestion-stats"><b>{item.news_count}</b> 則新聞 · {suggestionDates(item)} · {suggestionConfidenceLabel(item.confidence)}</p>
      <details className="theme-suggestion-news">
        <summary>關聯新聞（{item.news_count} 則）</summary>
        <SuggestionNewsList news={news} />
        {hidden > 0 && !full?.data && (
          full?.loading
            ? <p className="small-note">載入其餘新聞中…</p>
            : <button type="button" className="btn-ghost" onClick={() => onLoadAll(item.id)}>顯示其餘 {hidden} 則</button>
        )}
        {Boolean(full?.error) && <p className="small-note">其餘新聞暫時無法載入：{errorReason(full?.error)}</p>}
      </details>
      <p className="small-note ai-meta">{suggestionVersionLine(item)}</p>
    </article>
  )
}

export function ThemeSuggestionsSection({
  data,
  loading,
  error,
  full = {},
  onLoadAll,
}: {
  data: ThemeSuggestionsResponse | undefined
  loading: boolean
  error: unknown
  full?: Record<number, SuggestionNewsState>
  onLoadAll: (id: number) => void
}) {
  const updated = suggestionUpdatedText(data?.meta.updated_at)
  return (
    <section className="theme-suggestions" aria-labelledby="theme-suggestions-title">
      <div className="section-head">
        <div><div className="eyebrow">新聞聚合 · 待核實</div><h2 id="theme-suggestions-title">新聞題材建議</h2></div>
        {data && data.meta.total > 0 && <span className="small-note">{data.meta.total} 個建議{updated ? ` · ${updated}` : ''}</span>}
      </div>
      <p className="small-note">{SUGGESTION_NOTE}</p>
      {loading
        ? <Skeleton lines={3} label="新聞題材建議載入中…" />
        : error
          ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
          : !data
            ? null
            : data.items.length === 0
              ? <Card><EmptyState title={SUGGESTION_EMPTY_TEXT} reason={SUGGESTION_EMPTY_REASON} /></Card>
              : <div className="theme-suggestion-grid">
                {data.items.map((item) => <SuggestionCard key={item.id} item={item} full={full[item.id]} onLoadAll={onLoadAll} />)}
              </div>}
      {data && data.meta.matched_total > 0 && (
        <p className="small-note">另有 {data.meta.matched_total} 個建議與既有產業或題材同名，不另列出。</p>
      )}
      {data && data.meta.total > data.items.length && (
        <p className="small-note">依關聯新聞則數顯示前 {data.items.length} 個，共 {data.meta.total} 個。</p>
      )}
    </section>
  )
}
