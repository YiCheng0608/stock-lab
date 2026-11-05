import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import type { NewsItem } from '../types'
import { aiResult, internationalItem, naiveTimeItem, newsItem, newsPage, officialItem, productTime } from './news.fixtures'
import { AiInferencePanel, HomeNewsRow, NewsCard, NewsDetailView, NewsListView, StockNewsTimeline } from './NewsViews'
import {
  NEWS_PAGE_SIZE,
  STOCK_NEWS_LIMIT,
  cardAiCandidates,
  directionView,
  formatTaipeiInstant,
  matchesInstrument,
  newsListParams,
  newsPageSearch,
  newsTime,
  parseNewsTab,
  ruleVersion,
  sourceLink,
  stockNewsParams,
  summaryPreview,
  usableAi,
} from './newsView'

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
const fs = require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string }

// Standalone regression module (no browser, no server, no network) for Issue 164: /news tabs and cards, /news/:id facts vs
// AI inference, and the stock news timeline.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<StaticRouter location="/">{element}</StaticRouter>)
const noop = () => undefined
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const loaded = <T,>(data: T) => ({ data, loading: false, error: null })
const listView = (tab: 'domestic' | 'international' | 'official', items: NewsItem[], page = 1) => render(
  <NewsListView filters={{ tab, q: '', symbol: '' }} onFiltersChange={noop} query={loaded(newsPage(items))} page={page} onNext={noop} onPrevious={noop} onReset={noop} />,
)
const hasTone = (markup: string) => /tone-(up|down)/.test(markup)

// ---- request parameters: each tab asks for its own slice; filters are trimmed ----
check(JSON.stringify(newsListParams({ tab: 'domestic', q: '', symbol: '' })) === JSON.stringify({ category: 'domestic', limit: NEWS_PAGE_SIZE }), 'domestic tab filters category=domestic')
check(newsListParams({ tab: 'international', q: '', symbol: '' }).category === 'international', 'international tab filters category=international')
const officialParams = newsListParams({ tab: 'official', q: ' 董事會 ', symbol: ' 3666 ' }, 'cursor-2')
check(officialParams.source_kind === 'official_disclosure' && officialParams.category === undefined && officialParams.q === '董事會' && officialParams.symbol === '3666' && officialParams.cursor === 'cursor-2', 'official tab filters source_kind; q, symbol and cursor pass through')
check(parseNewsTab(null) === 'domestic' && parseNewsTab('international') === 'international' && parseNewsTab('company') === 'domestic', 'domestic is the default tab')
check(JSON.stringify(newsPageSearch({ tab: 'domestic', q: '', symbol: '2330' })) === JSON.stringify({ symbol: '2330' }), 'default tab and empty filters stay out of the URL')
check(JSON.stringify(stockNewsParams('2330')) === JSON.stringify({ symbol: '2330', limit: 50 }) && STOCK_NEWS_LIMIT === 50, 'stock timeline asks for the latest 50')

// ---- AC-1 domestic／international tabs ----
const domestic = listView('domestic', [newsItem()])
check(domestic.includes('id="news-tab-domestic" aria-selected="true"') && domestic.includes('id="news-tab-international" aria-selected="false"') && domestic.includes('id="news-panel-domestic"'), 'domestic tab selected with its panel')
check(count(domestic, 'data-testid="news-card"') === 1 && domestic.includes('href="/news/174"'), 'domestic card links to the detail page')
const international = listView('international', [internationalItem()])
check(international.includes('id="news-tab-international" aria-selected="true"') && international.includes('id="news-panel-international"'), 'international tab selected')
check(international.includes('國際 · 官方機構') && international.includes('Federal Reserve'), 'international card shows category, source kind and source')

// ---- AC-1 no data ----
const empty = listView('international', [])
check(empty.includes('無資料') && empty.includes('目前沒有符合條件的國際新聞。') && !empty.includes('data-testid="news-card"') && !empty.includes('pagination-controls'), 'empty tab shows the empty state, no pager')
const errored = render(<NewsListView filters={{ tab: 'domestic', q: '', symbol: '' }} onFiltersChange={noop} query={{ data: undefined, loading: false, error: new Error('API 503') }} page={1} onNext={noop} onPrevious={noop} onReset={noop} />)
check(errored.includes('新聞暫時無法載入') && errored.includes('API 503'), 'API error is shown, not an empty list')
const paged = render(<NewsListView filters={{ tab: 'domestic', q: '', symbol: '' }} onFiltersChange={noop} query={loaded(newsPage([newsItem()], { next_cursor: 'abc', has_more: true, total: 63 }))} page={2} onNext={noop} onPrevious={noop} onReset={noop} />)
check(paged.includes('第 2 頁') && paged.includes('共 63 則') && paged.includes('class="secondary-button">下一頁</button>') && !paged.includes('disabled="">上一頁'), 'cursor pager: previous and next enabled on page 2')

// ---- #300 search bars (DESIGN_SYSTEM §5 搜尋列): one row, buttons as tall as the inputs, never alone on a line ----
// The news bar is the same form on every tab: the two inputs, 搜尋, and 清除 once a filter is set, with no wrapper between.
const formControls = (markup: string) => {
  const form = /<form class="news-filters"[^>]*>([\s\S]*?)<\/form>/.exec(markup)?.[1] ?? ''
  const controls = form.match(/<input[^>]*>|<button[^>]*>[^<]*<\/button>/g) ?? []
  return { leftover: controls.reduce((rest, control) => rest.replace(control, ''), form), labels: controls.map((control) => /aria-label="([^"]*)"/.exec(control)?.[1] ?? />([^<]*)<\/button>/.exec(control)?.[1] ?? '?') }
}
for (const tab of ['domestic', 'international', 'official'] as const) {
  const bar = formControls(listView(tab, [newsItem()]))
  check(bar.leftover === '' && bar.labels.join('|') === '搜尋新聞|依股票代號篩選|搜尋', `${tab} search bar: inputs and 搜尋 are the form's only children, got ${bar.labels.join('|')} + 「${bar.leftover}」`)
}
const filteredBar = formControls(render(<NewsListView filters={{ tab: 'official', q: '董事會', symbol: '' }} onFiltersChange={noop} query={loaded(newsPage([officialItem()]))} page={1} onNext={noop} onPrevious={noop} onReset={noop} />))
check(filteredBar.labels.join('|') === '搜尋新聞|依股票代號篩選|搜尋|清除', `official search bar with a filter adds 清除 last, got ${filteredBar.labels.join('|')}`)
// The layout lives in styles.css; this reads its rules (outside and inside the 640px block) instead of a browser.
const css = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
const phoneStart = css.indexOf('@media (max-width: 640px) {')
const phoneCss = css.slice(phoneStart, css.indexOf('\n}', phoneStart))
const wideCss = css.replace(/@media[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}/g, '')
const declarations = (sheet: string, selector: string) => [...sheet.matchAll(/(?:^|\n)\s*([^{}\n][^{}]*)\{([^}]*)\}/g)]
  .filter((match) => match[1].split(',').some((part) => part.trim() === selector)).map((match) => match[2]).join(';')
const has = (sheet: string, selector: string, declaration: RegExp) => check(declaration.test(declarations(sheet, selector)), `${selector} needs ${declaration.source}, got 「${declarations(sheet, selector).trim()}」`)
for (const bar of ['.news-filters', '.search-controls']) {
  has(wideCss, bar, /display:\s*flex/)
  has(wideCss, bar, /flex-wrap:\s*nowrap/)
  has(wideCss, bar, /align-items:\s*stretch/)
  has(wideCss, `${bar} button`, /flex:\s*none/)
  has(wideCss, `${bar} .search-input`, /min-width:\s*0/)
}
has(wideCss, '.search-controls .search-input', /flex:\s*1 1 auto/)
check(!/flex-wrap:\s*wrap/.test(declarations(phoneCss, '.search-controls')), 'the stock and action search box keeps its buttons on the input row at 640px')
has(phoneCss, '.news-filters', /flex-wrap:\s*wrap/)
has(phoneCss, '.news-filters .search-input', /flex:\s*1 1 100%/)
has(phoneCss, '.news-filters .news-symbol-input', /flex:\s*1 1 0/)

// ---- AC-1 card order and copy (UI_COPY §4) ----
const card = render(<NewsCard item={newsItem()} />)
const order = ['news-source-badge', 'class="news-card-title"', 'class="news-card-summary"', 'class="news-card-time"', 'class="news-card-impact"', 'class="news-chips"', 'class="news-source"']
check(order.every((name, index) => index === 0 || card.indexOf(name) > card.indexOf(order[index - 1])), `card order follows UI_COPY §4: ${card}`)
check(card.includes('Yahoo奇摩股市') && card.includes('國內 · 媒體報導') && !card.includes('交易所公告'), 'media news is labelled by source_kind, never as an exchange announcement')
check(card.includes('台積電宣布臺南再蓋新廠 南市府：積極協助行政程序'), 'title whitespace and newlines are collapsed')
check(card.includes('href="/stocks/TWSE/2330"') && card.includes('2330 台積電'), 'verified instrument chip links to the stock')
const longSummary = '字'.repeat(130)
check(summaryPreview({ summary_preview: longSummary, summary: null }) === '字'.repeat(119) + '…' && summaryPreview({ summary_preview: null, summary: null, description: null }) === null, 'preview is cut at 120 characters')
check(render(<NewsCard item={internationalItem()} />).includes('來源未提供摘要'), 'missing summary says so')
// Today page row (Issue 510, UI_COPY_SPEC §4): two lines, the title then source · time and the direction; the tags,
// category, summary, AI candidates and source link stay on the cards.
const homeRow = render(<HomeNewsRow item={newsItem()} />)
const homeOrder = ['class="home-news-title"', 'class="home-news-source"', '<time', 'class="home-news-impact"']
check(homeOrder.every((name, index) => homeRow.includes(name) && (index === 0 || homeRow.indexOf(name) > homeRow.indexOf(homeOrder[index - 1]))), `home row order: ${homeRow}`)
check(!/news-card-summary|class="news-source"|news-chips|news-card-meta|規則核實|news-ai-candidates/.test(homeRow), 'the home row drops the summary, source link, tags, category and AI candidates')
check(homeRow.includes('title="台積電宣布臺南再蓋新廠 南市府：積極協助行政程序"'), 'the full title is the link title (the line is cut with an ellipsis)')
const aiRow = render(<HomeNewsRow item={newsItem({ ai: aiResult({ impact_direction: 'positive' }) })} />)
check(aiRow.includes('class="news-direction"') && aiRow.includes('可能正向') && aiRow.indexOf('news-direction') < aiRow.indexOf('>AI 推論<'), 'an AI direction is followed by 「AI 推論」 (page_checks T6 reads the line before it)')
check(!render(<HomeNewsRow item={newsItem({ ai: undefined })} />).includes('>AI 推論<'), 'a rule direction has no 「AI 推論」')
// Issue 512: the home row names no stock, so an emerging, delisted or hidden candidate never reaches it as a bare code;
// its link goes to /news/:id, which reads 「7808 訊聯智藥（興櫃）」.
const homeEmerging = render(<HomeNewsRow item={newsItem({ ai: aiResult({ symbol_candidates: [{ exchange: 'TWSE', symbol: '7808', name: '訊聯智藥', listing: 'emerging', reason: null, confidence: 'low', verified: false, source_check: 'mentioned' }, { exchange: 'TWSE', symbol: '2888', name: '新光金', listing: 'delisted', reason: null, confidence: 'low', verified: false, source_check: 'mentioned' }] }) })} />)
check(!/7808|2888|4152|代號未對應/.test(homeEmerging) && homeEmerging.includes('href="/news/'), `the home row shows no candidate code and links to the detail: ${homeEmerging}`)
check(render(<NewsCard item={officialItem()} />).includes('<span class="tag">3666</span>'), 'bare official code is a plain chip')
// Issue 451 (NEWS_SPEC §2): verified relations name their source and the rule version from impact.method.
check(card.includes('<span class="small-note news-relation-source">規則核實 · v2</span>') && card.indexOf('規則核實 · v2') < card.indexOf('2330 台積電'), 'rule relations are labelled 規則核實 with the rule version before the chips')
const v1Item = newsItem({ impact: { ...newsItem().impact, method: 'rule:exact-name-code/v1' } })
check(render(<NewsCard item={v1Item} />).includes('規則核實 · v1') && ruleVersion(v1Item) === 'v1', 'an item kept on the old rule shows v1')
check(!render(<NewsCard item={officialItem()} />).includes('規則核實') && ruleVersion(officialItem()) === null, 'official projections have no rule label')
check(!render(<NewsCard item={newsItem({ symbols: [], instruments: [] })} />).includes('規則核實'), 'no verified relation, no rule label')

// ---- AC-1 unknown direction never gets up／down colors ----
check(card.includes('影響尚未判定') && !hasTone(card) && !card.includes('AI 推論'), 'no AI: rule direction unknown, no red／green, no AI badge')
for (const direction of ['unknown', null, 'sideways']) check(directionView(direction).tone === null, `${direction} has no tone`)
check(directionView('positive').tone === 'up' && directionView('negative').tone === 'down' && directionView('mixed').tone === 'flat', 'known directions: up red, down green, mixed flat')
const aiCard = render(<NewsCard item={newsItem({ ai: aiResult() })} />)
check(aiCard.includes('direction-dot tone-up') && aiCard.includes('可能正向') && aiCard.includes('AI 推論'), 'AI direction on the card is a colored dot plus text, marked AI 推論')
const unsupported = render(<NewsCard item={newsItem({ ai: aiResult({ unsupported: true, impact_direction: 'positive' }) })} />)
check(unsupported.includes('影響尚未判定') && !hasTone(unsupported), 'unsupported AI result stays unknown without color')
const unknownAi = render(<NewsCard item={newsItem({ ai: aiResult({ impact_direction: 'unknown' }) })} />)
check(unknownAi.includes('影響尚未判定') && !hasTone(unknownAi), 'AI unknown direction has no red／green')
check(usableAi(newsItem({ ai: aiResult({ status: 'pending' }) })) === null && usableAi(newsItem({ ai: undefined })) === null, 'only a done result is shown')

// ---- #452 AC-1 card AI candidates row (UI_COPY_SPEC §4 AI 候選行, DESIGN_SYSTEM §5) ----
const candidateRow = (markup: string) => /<details class="news-ai-candidates"[^>]*>[\s\S]*?<\/details>/.exec(markup)?.[0] ?? ''
const candidate = (exchange: string, symbol: string, name: string | null, confidence: string | null = 'medium', source_check: string | null = 'not_mentioned', listing: string | undefined = 'listed') => ({ exchange, symbol, name, listing, reason: '理由只在詳情頁', confidence, verified: false as const, source_check })
// With candidates: 2330 is rule-verified on this item and drops out; 3105 links, 7808 is an emerging stock (Issue 512) in plain text.
const withCandidates = newsItem({ ai: aiResult({ symbol_candidates: [candidate('TWSE', '2330', '台積電', 'high'), candidate('TPEx', '3105', '穩懋', 'high', 'mentioned'), candidate('TWSE', '7808', '訊聯智藥', 'low', 'not_mentioned', 'emerging')] }) })
const candidatesCard = render(<NewsCard item={withCandidates} />)
const row = candidateRow(candidatesCard)
check(row !== '' && count(candidatesCard, 'data-testid="news-ai-candidates"') === 1, `card with candidates shows one AI candidates row: ${candidatesCard}`)
check(candidatesCard.indexOf('class="news-chips"') < candidatesCard.indexOf('news-ai-candidates') && candidatesCard.indexOf('news-ai-candidates') < candidatesCard.indexOf('class="news-source"'), 'AI candidates row sits after the verified chips and before the source link')
check(row.includes('href="/stocks/TPEx/3105"') && row.includes('3105 穩懋') && row.includes('模型把握高'), 'named candidate links to the stock with the model confidence')
// #465: each candidate says whether the rule check found it in the sent text; none reads 待核實.
check(/3105 穩懋<\/a><span class="news-ai-confidence"> · 規則核實：原文提及 · 模型把握高/.test(row), `mentioned candidate reads 規則核實：原文提及: ${row}`)
check(/7808 訊聯智藥（興櫃）<\/span><span class="news-ai-confidence"> · 推論 · 模型把握低/.test(row), `not mentioned candidate reads 推論: ${row}`)
check(!candidatesCard.includes('待核實'), 'the card has no 待核實')
check(row.includes('7808 訊聯智藥（興櫃）') && !row.includes('/stocks/TWSE/7808') && !row.includes('代號未對應'), 'an emerging candidate is named and marked 興櫃, without a stock link (Issue 512)')
// #512: a delisted stock is marked 已下市 and not linked; a nameless one (an older server) is not listed at all.
const delistedRow = candidateRow(render(<NewsCard item={newsItem({ ai: aiResult({ symbol_candidates: [candidate('TWSE', '2888', '新光金', 'high', 'mentioned', 'delisted'), candidate('TWSE', '6751', null, 'low', 'not_mentioned', undefined), candidate('TWSE', '2454', '聯發科', 'low', 'not_mentioned', undefined)] }) })} />))
check(delistedRow.includes('<span>2888 新光金（已下市）</span>') && !delistedRow.includes('/stocks/TWSE/2888'), `a delisted candidate reads 已下市 and is plain text: ${delistedRow}`)
check(!delistedRow.includes('6751') && !delistedRow.includes('代號未對應') && delistedRow.includes('<summary>AI 候選 · 2 檔（規則核實 1、推論 1）</summary>'), `a nameless candidate is left out of the row and its count: ${delistedRow}`)
check(delistedRow.includes('href="/stocks/TWSE/2454"') && delistedRow.includes('2454 聯發科</a>'), 'without listing (an older server) a named candidate still links')
check(!row.includes('2330') && !row.includes('理由只在詳情頁'), 'rule-verified 2330 is not repeated; reasons stay on the detail page')
check(!row.includes('class="tag'), 'candidates are not tag chips, so they never read as verified relations')
// 收合與展開: closed <details> by default; the summary is the only line until opened, the list and meta follow it inside.
check(/^<details class="news-ai-candidates" data-testid="news-ai-candidates">/.test(row) && !/<details[^>]*\sopen/.test(row), 'AI candidates row is collapsed by default')
const summaryEnd = row.indexOf('</summary>')
check(row.indexOf('<summary>') > 0 && summaryEnd > 0 && row.indexOf('<ul>') > summaryEnd && row.indexOf('模型 ') > summaryEnd, 'summary first; candidates and model line only show when expanded')
// 「推論」 label and versions.
const summaryText = row.slice(row.indexOf('<summary>'), summaryEnd).replace(/<[^>]+>/g, '')
// The text carries 「推論」; no second AI 推論 badge, so the card keeps one (verify N4 counts whole 「AI 推論」 lines).
check(summaryText === 'AI 候選 · 2 檔（規則核實 1、推論 1）' && !row.includes('AI 推論'), `summary reads 「AI 候選 · 2 檔（規則核實 1、推論 1）」 without a badge, got 「${summaryText}」`)
const allInferred = candidateRow(render(<NewsCard item={newsItem({ ai: aiResult({ symbol_candidates: [candidate('TWSE', '6751', '甲'), { ...candidate('TWSE', '6752', '乙'), source_check: undefined }] }) })} />))
check(allInferred.includes('<summary>AI 候選 · 2 檔（推論 2）</summary>'), `a candidate without a check result is 推論: ${allInferred}`)
check(count(candidatesCard, 'AI 推論') === 1, 'a card with AI candidates still has one AI 推論 badge, after the AI direction')
check(row.includes('模型 claude-haiku-5-5 · 提示版本 news_v1 · 核對規則 ai-candidate-source/v1。規則核實：名稱或代號出現在標題或摘要；推論：原文沒有寫出，由模型推得。候選不計入已核實關聯。'), `expanded row carries the model, prompt version and check rule: ${row}`)
const unrecorded = candidateRow(render(<NewsCard item={newsItem({ ai: aiResult({ model: null, prompt_version: null }) })} />))
check(unrecorded.includes('模型 未記錄 · 提示版本 未記錄'), 'missing model／prompt version reads 未記錄')
// No candidates: no AI, an empty list, a pending result, or only rule-verified codes → no row and no 「無」.
const noRows: Array<[string, NewsItem]> = [
  ['no AI', newsItem()],
  ['empty candidates', newsItem({ ai: aiResult({ symbol_candidates: [] }) })],
  ['pending result', newsItem({ ai: aiResult({ status: 'pending' }) })],
  ['only the verified 2330', newsItem({ ai: aiResult({ symbol_candidates: [candidate('TWSE', '2330', '台積電')] }) })],
  ['bare official code 3666', newsItem({ ...officialItem(), ai: aiResult({ symbol_candidates: [candidate('TWSE', '3666', '光耀')] }) })],
]
for (const [label, item] of noRows) {
  const markup = render(<NewsCard item={item} />)
  check(!markup.includes('news-ai-candidates') && !markup.includes('AI 候選'), `${label}: no AI candidates row`)
  check(cardAiCandidates(item).length === 0, `${label}: no card candidates`)
}
// Duplicates compare the code only (listed and OTC codes never repeat, PR #458 review): verified via symbols 「EX:SYM」
// without instruments drops the candidate on either exchange; the same code twice (even on two exchanges) is listed once.
const viaSymbols = newsItem({ instruments: [], symbols: ['TPEx:3105'], ai: aiResult({ symbol_candidates: [candidate('TPEx', '3105', '穩懋'), candidate('TWSE', '3105', '穩懋'), candidate('TWSE', '2454', '聯發科'), candidate('TPEx', '2454', '聯發科')] }) })
check(cardAiCandidates(viaSymbols).map((item) => item.key).join('|') === 'TWSE:2454', `symbols EX:SYM drops the code on both exchanges; repeats listed once, got ${cardAiCandidates(viaSymbols).map((item) => item.key).join('|')}`)
// instruments alone (symbols empty), so this path is checked apart from the symbols one above.
const otherExchange = newsItem({ symbols: [], ai: aiResult({ symbol_candidates: [candidate('TPEx', '2330', '台積電')] }) })
check(cardAiCandidates(otherExchange).length === 0 && !render(<NewsCard item={otherExchange} />).includes('news-ai-candidates'), 'a candidate on the other exchange than the verified instrument is not shown twice')

// ---- AC-1 time display (NEWS_SPEC §4, UI_COPY §4) ----
check(newsTime(newsItem()).text === '發布於 2026/10/18 00:05' && card.includes('dateTime="2026-10-17T16:05:00+00:00"'), 'known published instant in Taipei time')
const official = render(<NewsCard item={officialItem()} />)
check(newsTime(officialItem()).text === '事件日 2026/09/08' && official.includes('事件日 2026/09/08') && !official.includes('00:00'), 'date-only event shows no hours or minutes')
check(newsTime(naiveTimeItem()).text === '來源時間待核實', 'naive feed time stays 待核實 (product_time only, Issue 186)')
check(newsTime(newsItem({ published_at: null, display_time: null, product_time: productTime() })).text === '來源時間未提供', 'no source time at all')
check(newsTime(newsItem({ time_consistency: 'conflict' })).text === '來源時間待核實', 'conflict is never shown as a verified time')
check(newsTime(newsItem({ product_time: undefined, published_at: '2026-10-17T16:00:00' })).text === '來源時間待核實' && newsTime(newsItem({ product_time: undefined, published_at: null, event_date: '2026-09-08' })).text === '事件日 2026/09/08', 'without product_time only legal values are formatted')
check(formatTaipeiInstant('2026-10-17T23:30:00Z') === '2026/10/18 07:30' && formatTaipeiInstant('2026-10-17T23:30:00') === null, '24-hour Taipei format; naive is rejected')

// ---- AC-1 source link kinds (UI_COPY §4) ----
const itemLink = sourceLink(newsItem())
check(itemLink.href === 'https://tw.news.yahoo.com/tsmc-tainan-160000675.html' && itemLink.label === '查看原文' && itemLink.note === null, 'item → 查看原文')
check(sourceLink({ ...officialItem(), source: { name: 'MOPS', url: 'https://mops.example/1', url_kind: 'item' } }).label === '查看原始公告', 'official item → 查看原始公告')
const feedLink = sourceLink(officialItem())
check(feedLink.label === '查看官方公告資料集' && feedLink.note === '資料集連結未必定位到本則公告', 'feed → dataset with a note')
check(sourceLink(internationalItem()).href === null && sourceLink(internationalItem()).label === '來源連結未提供', 'none → plain text')
check(sourceLink(newsItem({ source: { name: 'x', url: 'javascript:alert(1)', url_kind: 'item' } })).href === null, 'non-http url is never linked')
check(card.includes('href="https://tw.news.yahoo.com/tsmc-tainan-160000675.html" target="_blank" rel="noopener noreferrer">查看原文</a>'), 'item link opens a new tab')
check(official.includes('>查看官方公告資料集</a>') && official.includes('資料集連結未必定位到本則公告'), 'feed link rendered with its note')
const noLink = render(<NewsCard item={internationalItem()} />)
check(noLink.includes('<span>來源連結未提供</span>') && !noLink.slice(noLink.indexOf('class="news-source"')).includes('<a '), 'none renders no dead link')

// ---- AC-1 detail: source facts and AI inference are separate ----
const detail = render(<NewsDetailView item={newsItem({ ai: aiResult() })} />)
const factsStart = detail.indexOf('data-testid="news-facts"')
const aiStart = detail.indexOf('data-testid="ai-inference"')
check(factsStart > 0 && aiStart > factsStart, 'facts card first, AI block after it')
const facts = detail.slice(factsStart, aiStart)
const inference = detail.slice(aiStart)
check(facts.includes('來源事實') && facts.includes('台積電十五日召開法說會') && facts.includes('發布於 2026/10/18 00:05') && facts.includes('已核實關聯') && facts.includes('href="/stocks/TWSE/2330"'), 'facts: source summary, time and verified relations')
check(facts.includes('規則核實 · v2') && facts.includes('關聯方法：規則比對（名稱／簡稱／代號） · 規則版本 v2'), 'detail: relation source and rule version')
check(!facts.includes('AI') && !facts.includes('3奈米廠，預計2028') && !facts.includes('7808'), 'facts carry no AI content')
check(facts.includes('來源未標示影響') && !facts.includes('影響尚未判定') && !hasTone(facts), 'source impact unknown in facts reads 來源未標示影響, no color')
check(detail.includes('<section class="ai-inference" aria-labelledby="ai-inference-title" data-testid="ai-inference">') && inference.includes('AI 推論') && inference.includes('badge badge-accent'), 'AI block has the accent bar class and AI 推論 badge')
check(inference.includes('台積電宣布臺南增建3奈米廠') && inference.includes('可能正向') && inference.includes('新廠預計2028年上半年量產'), 'AI summary, direction and rationale')
check(inference.includes('候選標的') && !inference.includes('待核實') && inference.includes('規則核實：原文提及 · 模型把握高') && inference.includes('推論 · 模型把握低') && inference.includes('半導體'), `Issue 465: candidates carry their check result and model confidence, no 待核實: ${inference}`)
check(/候選題材 <span class="badge badge-success badge-compact">已通過題材核對<\/span>/.test(inference), 'theme candidates passed the rule theme check (Issue 413) and say so')
check(inference.includes('href="/stocks/TWSE/2330"') && inference.includes('<span>7808 訊聯智藥（興櫃）</span>') && !inference.includes('/stocks/TWSE/7808'), 'an emerging candidate is marked 興櫃 and not linked (Issue 512)')
check(!inference.includes('4152') && !inference.includes('代號未對應'), 'a hidden code (code_unknown) never shows on the detail page')
const allHidden = render(<AiInferencePanel ai={aiResult({ symbol_candidates: [], hidden_symbol_candidates: [{ exchange: 'TPEx', symbol: '4152', reason: 'code_unknown' }] })} />)
check(allHidden.includes('模型提出的候選代號都查無對應標的，不列出。') && !allHidden.includes('4152'), `only hidden codes: says so without the codes: ${allHidden}`)
const delistedDetail = render(<AiInferencePanel ai={aiResult({ symbol_candidates: [candidate('TWSE', '2888', '新光金', 'high', 'mentioned', 'delisted')] })} />)
check(delistedDetail.includes('<span>2888 新光金（已下市）</span>') && !delistedDetail.includes('/stocks/TWSE/2888'), 'detail: a delisted candidate reads 已下市 and is not linked')
check(inference.includes('模型 claude-haiku-5-5') && inference.includes('提示版本 news_v1') && inference.includes('產生時間 2026/10/17 23:04') && inference.includes('核對規則 ai-candidate-source/v1'), 'model, prompt version, generation time and check rule')
const noAi = render(<NewsDetailView item={newsItem()} />)
check(noAi.includes('此則尚未產生 AI 摘要與判讀') && noAi.includes('class="ai-inference"'), 'without AI the block still stands apart and says so')
const unsupportedDetail = render(<AiInferencePanel ai={aiResult({ unsupported: true, symbol_candidates: [], hidden_symbol_candidates: [], theme_candidates: [] })} />)
check(unsupportedDetail.includes('沒有直接關聯') && !hasTone(unsupportedDetail) && unsupportedDetail.includes('模型未提出候選標的'), 'unsupported AI result: notice, no direction color')
const officialDetail = render(<NewsDetailView item={officialItem()} />)
check(officialDetail.includes('個股公告 · 官方公告資料') && officialDetail.includes('公開資訊觀測站公告') && officialDetail.includes('展開公告內容') && officialDetail.includes('事件日 2026/09/08'), 'official detail: source label, collapsed full text, date-only')
const conflict = render(<NewsDetailView item={{ ...officialItem(), time_consistency: 'conflict' }} />)
check(conflict.includes('資料集事件日期與公告內容提及日期不一致'), 'conflict warning on the detail page')

// ---- stock timeline: exact exchange + symbol, same card ----
check(matchesInstrument(newsItem(), 'TWSE', '2330') && !matchesInstrument(newsItem(), 'TPEx', '2330'), 'instrument match needs the exchange')
check(matchesInstrument({ instruments: [], symbols: ['2330'] }, 'TWSE', '2330') && !matchesInstrument({ instruments: [], symbols: ['TWSE:23301'] }, 'TWSE', '2330'), 'bare official code matches; substrings do not')
const timeline = render(<StockNewsTimeline exchange="TWSE" symbol="2330" query={loaded(newsPage([newsItem({ ai: aiResult() }), newsItem({ id: '900', symbols: ['TWSE:23301'], instruments: [] }), newsItem({ id: '901', symbols: ['2330'], instruments: [], category: 'company', source_kind: 'official_disclosure' })]))} />)
check(timeline.includes('最近 50 則') && timeline.includes('class="news-cards news-timeline"') && count(timeline, 'data-testid="news-card"') === 2 && !timeline.includes('data-news-id="900"'), 'timeline keeps exact matches with the shared card')
check(timeline.includes('href="/news?symbol=2330"'), 'timeline links to the filtered news page')
const emptyTimeline = render(<StockNewsTimeline exchange="TWSE" symbol="2330" query={loaded(newsPage([]))} />)
check(emptyTimeline.includes('尚無與此股已核實關聯的新聞或公告。'), 'empty timeline')
