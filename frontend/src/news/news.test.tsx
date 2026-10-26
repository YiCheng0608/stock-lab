import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import type { NewsItem } from '../types'
import { aiResult, internationalItem, naiveTimeItem, newsItem, newsPage, officialItem, productTime } from './news.fixtures'
import { AiInferencePanel, NewsCard, NewsDetailView, NewsListView, StockNewsTimeline } from './NewsViews'
import {
  NEWS_PAGE_SIZE,
  STOCK_NEWS_LIMIT,
  directionView,
  formatTaipeiInstant,
  matchesInstrument,
  newsListParams,
  newsPageSearch,
  newsTime,
  parseNewsTab,
  sourceLink,
  stockNewsParams,
  summaryPreview,
  usableAi,
} from './newsView'

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
// Today page compact row (#276, UI_COPY_SPEC §4): no summary and no source link; the rest keeps its order.
const compact = render(<NewsCard item={newsItem()} compact />)
const compactOrder = ['news-source-badge', 'class="news-card-title"', 'class="news-card-time"', 'class="news-card-impact"', 'class="news-chips"']
check(compactOrder.every((name, index) => compact.includes(name) && (index === 0 || compact.indexOf(name) > compact.indexOf(compactOrder[index - 1]))), `compact card order: ${compact}`)
check(!compact.includes('news-card-summary') && !compact.includes('class="news-source"') && compact.includes('news-card-compact'), 'compact card drops the summary and source link')
check(render(<NewsCard item={officialItem()} />).includes('<span class="tag">3666</span>'), 'bare official code is a plain chip')

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
check(!facts.includes('AI') && !facts.includes('3奈米廠，預計2028') && !facts.includes('6751'), 'facts carry no AI content')
check(facts.includes('來源未標示影響') && !facts.includes('影響尚未判定') && !hasTone(facts), 'source impact unknown in facts reads 來源未標示影響, no color')
check(detail.includes('<section class="ai-inference" aria-labelledby="ai-inference-title" data-testid="ai-inference">') && inference.includes('AI 推論') && inference.includes('badge badge-accent'), 'AI block has the accent bar class and AI 推論 badge')
check(inference.includes('台積電宣布臺南增建3奈米廠') && inference.includes('可能正向') && inference.includes('新廠預計2028年上半年量產'), 'AI summary, direction and rationale')
check(inference.includes('候選標的') && count(inference, '待核實') >= 2 && inference.includes('模型把握高') && inference.includes('半導體'), 'candidates are marked 待核實 with model confidence')
check(inference.includes('href="/stocks/TWSE/2330"') && inference.includes('6751 （代號未對應到已知標的）') && !inference.includes('/stocks/TWSE/6751'), 'unknown candidate code is not linked')
check(inference.includes('模型 claude-haiku-5-5') && inference.includes('提示版本 news_v1') && inference.includes('產生時間 2026/10/17 23:04'), 'model, prompt version and generation time')
const noAi = render(<NewsDetailView item={newsItem()} />)
check(noAi.includes('此則尚未產生 AI 摘要與判讀') && noAi.includes('class="ai-inference"'), 'without AI the block still stands apart and says so')
const unsupportedDetail = render(<AiInferencePanel ai={aiResult({ unsupported: true, symbol_candidates: [], theme_candidates: [] })} />)
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
