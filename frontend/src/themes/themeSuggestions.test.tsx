import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { industryBoard } from './themeBoards.fixtures'
import { ThemesBoardView } from './ThemeViews'
import { ThemeSuggestionsSection } from './ThemeSuggestionViews'
import {
  SUGGESTION_EMPTY_TEXT,
  SUGGESTION_NOTE,
  THEME_SUGGESTION_LIMIT,
  hiddenNewsCount,
  suggestionConfidenceLabel,
  suggestionDates,
  suggestionUpdatedText,
  suggestionVersionLine,
  themeSuggestionsPath,
} from './themeSuggestions'
import { suggestion, suggestions } from './themeSuggestions.fixtures'

// Standalone regression module for the news theme suggestions (#216) on /themes: pending verification, AI inference,
// related news, versions, and kept apart from the ranked boards.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<StaticRouter location="/themes">{element}</StaticRouter>)
const noop = () => undefined
const count = (markup: string, needle: string) => markup.split(needle).length - 1

// ---- helpers ----
check(themeSuggestionsPath() === '/theme-suggestions' && themeSuggestionsPath(THEME_SUGGESTION_LIMIT) === '/theme-suggestions?limit=20', 'request path and default limit')
check(suggestionConfidenceLabel('not_provided') === '模型未提供把握' && suggestionConfidenceLabel(null) === '模型未提供把握', 'news_v1 themes carry no confidence')
check(suggestionConfidenceLabel('high') === '模型把握高', 'a future confidence keeps the news copy')
check(suggestionDates(suggestion()) === '首次 2026/10/11 · 最近 2026/10/17', 'first and last news dates')
check(suggestionDates(suggestion({ first_news_date: '2026-10-17' })) === '新聞日 2026/10/17', 'one day is shown once')
check(suggestionVersionLine(suggestion()) === '模型 claude-haiku-5-5 · 提示版本 news_v1 · 彙整規則 theme_suggestions_v1', 'model, prompt and aggregation versions')
check(suggestionVersionLine(suggestion({ llm_models: [] })).startsWith('模型 未記錄'), 'missing model is stated')
check(suggestionUpdatedText('2026-10-18T01:00:00+00:00') === '最近更新 2026/10/18 09:00', 'update time in Taipei')
check(suggestionUpdatedText('2026-10-18T01:00:00') === null && suggestionUpdatedText(null) === null, 'an instant without offset is not guessed')
check(hiddenNewsCount(suggestion()) === 2 && hiddenNewsCount(suggestion({ news_count: 5 })) === 0, 'news beyond the inline five')

// ---- section markup ----
const markup = render(<ThemeSuggestionsSection data={suggestions()} loading={false} error={null} onLoadAll={noop} />)
check(markup.includes('新聞題材建議') && markup.includes('新聞聚合 · 待核實'), 'section title and eyebrow')
check(markup.includes(SUGGESTION_NOTE), 'not ranked, not verified, not a trading reason')
check(count(markup, '>待核實</span>') === 2 && count(markup, 'AI 推論') === 2, 'every suggestion is marked pending verification and AI inference')
check(count(markup, 'class="ai-inference theme-suggestion"') === 2, 'each suggestion sits in the accent-bar inference block')
check(markup.includes('<b>7</b> 則新聞 · 首次 2026/10/11 · 最近 2026/10/17 · 模型未提供把握'), 'count, dates and confidence')
check(markup.includes('關聯新聞（7 則）') && markup.includes('href="/news/117"') && markup.includes('無人機訂單新聞 17'), 'related news link to the news detail')
check(markup.includes('鉅亨網 · 新聞日 2026/10/17 · 判讀題材「無人機」') && markup.includes('理由：國防無人機採購'), 'source, date, wording and reason')
check(count(markup, '理由：') === 5, 'a news item without a reason shows none')
check(markup.includes('顯示其餘 2 則') && count(markup, '顯示其餘') === 1, 'only a suggestion with hidden news offers the rest')
check(markup.includes('模型 claude-haiku-5-5 · 提示版本 news_v1 · 彙整規則 theme_suggestions_v1'), 'versions on each suggestion')
check(markup.includes('3 個建議 · 最近更新 2026/10/18 09:00'), 'total and update time')
check(markup.includes('另有 4 個建議與既有產業或題材同名，不另列出。'), 'matched names are counted, not listed')
check(markup.includes('依關聯新聞則數顯示前 2 個，共 3 個。'), 'truncated list says so')
for (const banned of ['排名', '分數', '#1', 'pending_verification', 'not_provided', 'theme_key']) {
  check(!markup.includes(banned), `no rank, score or internal value: ${banned}`)
}

// ---- the rest of the news ----
const full = suggestion({ news: [...suggestion().news, ...[12, 11].map((day) => ({ news_id: 100 + day, title: `無人機訂單新聞 ${day}`, source_name: '鉅亨網', news_date: `2026-10-${day}`, theme_text: '無人機', reason: null }))] })
const expanded = render(<ThemeSuggestionsSection data={suggestions()} loading={false} error={null} full={{ 11: { data: full, loading: false, error: null } }} onLoadAll={noop} />)
check(expanded.includes('href="/news/111"') && !expanded.includes('顯示其餘'), 'loaded detail replaces the inline five')
const loadingRest = render(<ThemeSuggestionsSection data={suggestions()} loading={false} error={null} full={{ 11: { data: undefined, loading: true, error: null } }} onLoadAll={noop} />)
check(loadingRest.includes('載入其餘新聞中…'), 'loading the rest')
const failedRest = render(<ThemeSuggestionsSection data={suggestions()} loading={false} error={null} full={{ 11: { data: undefined, loading: false, error: new Error('API 500') } }} onLoadAll={noop} />)
check(failedRest.includes('其餘新聞暫時無法載入：API 500') && failedRest.includes('顯示其餘 2 則'), 'failed load can be retried')

// ---- states ----
const empty = render(<ThemeSuggestionsSection data={{ items: [], meta: { ...suggestions().meta, total: 0, matched_total: 0, updated_at: null } }} loading={false} error={null} onLoadAll={noop} />)
check(empty.includes(SUGGESTION_EMPTY_TEXT) && empty.includes('新聞 AI 判讀尚未提出與既有族群不同名的題材') && !empty.includes('最近更新'), 'empty state with reason')
check(render(<ThemeSuggestionsSection data={undefined} loading error={null} onLoadAll={noop} />).includes('新聞題材建議載入中…'), 'loading skeleton')
check(render(<ThemeSuggestionsSection data={undefined} loading={false} error={new Error('API 503')} onLoadAll={noop} />).includes('API 503'), 'error state')

// ---- kept apart from the ranked boards ----
const page = render(<ThemesBoardView board="industry" onBoardChange={noop} search="" onSearchChange={noop} data={industryBoard()} loading={false} error={null}
  suggestions={<ThemeSuggestionsSection data={suggestions()} loading={false} error={null} onLoadAll={noop} />} />)
const boardEnd = page.indexOf('</table>')
check(boardEnd > 0 && page.indexOf('新聞題材建議') > boardEnd, 'suggestions follow the board, outside its table')
check(!page.slice(0, page.indexOf('theme-suggestions')).includes('無人機'), 'no suggestion inside the board')
