import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from '../App'
import type { ActionNearness, ActionNearnessItem, ActionSummary, ActionTierSummary, ActionsResponse, Dashboard, Position } from '../types'
import { action } from '../today/today.fixtures'
import { parseStockTab, stockTabSearch } from '../stock/stockTabs'
import { ActionFilters, ActionTierList, ActionTierSectionView } from './ActionViews'
import { ACTION_TIER_PREVIEW, CONDITIONS_PENDING_TEXT, EMPTY_TEXT, NEAR_RESEARCH_LINK, SEARCH_NOTE, hiddenSentence, nearCopy, previewTiers, tierSections } from './actionTiers'

// Action centre tiers (#278, UI_COPY_SPEC §5, DESIGN_SYSTEM §5 行動列表／篩選膠囊／庫存一行), the tier 3 接近成立 cards
// and the tier 2／4 lines (#277-B, UI_COPY_SPEC §6, DESIGN_SYSTEM §7), and the today page's holding line reading every
// holding (#297 review L1). Every check runs and the failures are listed together.
const failures: string[] = []
let checks = 0
const check = (condition: boolean, message: string) => { checks++; if (!condition) failures.push(message) }
type Props = Record<string, unknown>
const appComponent = (name: string) =>
  ((AppModule as Record<string, unknown>)[name] ?? (() => { throw new Error(`App does not export ${name}`) })) as (props: Props) => ReactElement | null
const render = (name: string, element: () => ReactElement, cache: Array<[unknown[], unknown]> = [], location = '/'): string => {
  try {
    const client = new QueryClient()
    for (const [key, value] of cache) client.setQueryData(key, value)
    return renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location={location}>{element()}</StaticRouter></QueryClientProvider>)
  } catch (error) {
    checks++
    failures.push(`${name}: render failed (${error instanceof Error ? error.message.split('\n')[0] : String(error)})`)
    return ''
  }
}
const text = (markup: string) => markup.replace(/<[^>]+>/g, '')
const count = (markup: string, needle: string) => markup.split(needle).length - 1

const row = (symbol: string, tier: 0 | 1 | 2 | 3 | 4 | 5, state: string, extra: Partial<ActionSummary> = {}) =>
  action(symbol, `名稱${symbol}`, state, { tier, data_cutoff: '2026-10-22', current_price: 21.1, price_change: 0.5, price_change_pct: 0.0243, ...extra })

function summary(extra: Partial<ActionTierSummary> = {}): ActionTierSummary {
  return {
    total: 4, held: 0, held_unknown: 0, scope: 'filtered_results', tier_version: 'action_tier_v1', view: 'focus', include_etf: false,
    tiers: [
      { tier: 0, key: 'holding_risk', label: '持倉風險', stock: 0, etf: 0, shown: 0 },
      { tier: 1, key: 'candidate', label: '今日候選', stock: 2, etf: 0, shown: 2 },
      { tier: 2, key: 'conditional', label: '其他成立條件', stock: 50, etf: 8, shown: 50 },
      { tier: 3, key: 'near', label: '接近成立', stock: 0, etf: 0, shown: 0 },
      { tier: 4, key: 'observation', label: '其他觀察', stock: 1310, etf: 140, shown: 2 },
      { tier: 5, key: 'data_insufficient', label: '資料待補', stock: 129, etf: 8, shown: 0 },
    ],
    hidden: { etf: 186, observation: 1308, data_insufficient: 129 },
    views: { focus: 54, with_observation: 1362, all: 1491 },
    etf: 8,
    ...extra,
  }
}

const candidate = (symbol: string, rank: number) => row(symbol, 1, 'conditional_entry', {
  candidate: { rank, total_score: 80 - rank }, trigger_price: 21.5, invalid_price: 20.1, target_1: 23.8, trigger_kind: 'breakout',
})
const page = (items: ActionSummary[], extra: Partial<ActionTierSummary> = {}): ActionsResponse => ({
  items,
  meta: { limit: 20, next_cursor: null, has_more: false, sort: 'action_tier_v1', data_as_of: '2026-10-22', total: items.length },
  summary: summary(extra),
})
const firstPage = () => page([candidate('1712', 1), candidate('6416', 2), row('2010', 2, 'conditional_entry', { trigger_price: 30, invalid_price: 28, target_1: 33 }), row('1234', 4, 'no_condition', { watchlisted: true, primary_reason: { label: '突破條件差 3 項', scope: 'x' } })])

// ---- counts and the hidden line come from summary (UI_COPY_SPEC §5) ----
const filters = render('ActionFilters', () => <ActionFilters summary={summary()} view="focus" includeEtf={false} searching={false} onViewChange={() => {}} onIncludeEtfChange={() => {}} />)
for (const label of ['重點 54', '含其他觀察 1,362', '全部 1,491', '含 ETF（8）']) check(text(filters).includes(label), `篩選膠囊: shows 「${label}」 from summary, got ${text(filters)}`)
check(count(filters, 'aria-pressed="true"') === 1 && /aria-pressed="true"[^>]*>重點 54/.test(filters), '篩選膠囊: only 重點 is selected by default')
check(filters.includes('filter-chip-selected') && count(filters, 'class="badge filter-chip') === 3, '篩選膠囊: three badge chips, the selected variant on one')
const sentence = '預設隱藏：ETF 186 檔、其他觀察 1,308 檔、策略判斷資料待補 129 檔；自選標的一律顯示。隱藏不刪資料，切換上方篩選即可看到。'
check(text(filters).includes(sentence), `預設隱藏句: from summary.hidden, got ${text(filters)}`)
check(hiddenSentence(summary({ hidden: { etf: 0, observation: 3, data_insufficient: 0 }, view: 'all' })) === '目前隱藏：其他觀察 3 檔；自選標的一律顯示。隱藏不刪資料，切換上方篩選即可看到。', '隱藏句: a zero part is left out and a non-default filter says 目前隱藏')
check(hiddenSentence(summary({ hidden: { etf: 0, observation: 0, data_insufficient: 0 }, view: 'all', include_etf: true })) === null, '隱藏句: nothing hidden, no line')
const searching = render('ActionFilters search', () => <ActionFilters summary={summary()} view="focus" includeEtf={false} searching onViewChange={() => {}} onIncludeEtfChange={() => {}} />)
check(text(searching).includes(SEARCH_NOTE) && !text(searching).includes('預設隱藏'), '搜尋: the line says the search ignores the filters')

// ---- one section per tier with rows; 顯示 k／N 檔 and 顯示更多 page the tier ----
const sections = tierSections(firstPage())
check(sections.map((section) => `${section.tier}:${section.items.length}/${section.shown}`).join(' ') === '1:2/2 2:1/50 4:1/2', `區塊: tiers with shown rows only, got ${sections.map((section) => `${section.tier}:${section.items.length}/${section.shown}`).join(' ')}`)
const more = tierSections(firstPage(), { 2: [page([row('2010', 2, 'conditional_entry'), row('2038', 2, 'conditional_entry')])] })
check(more[1].items.map((item) => item.instrument.symbol).join(',') === '2010,2038', '顯示更多: a tier page appends its rows after the first page, without repeating one')
const list = render('ActionTierList', () => <ActionTierList sections={sections} loadingTiers={new Set()} canLoadMore={() => true} onMore={() => {}} />)
for (const line of ['今日候選', '顯示 2／2 檔', '其他成立條件', '顯示 1／50 檔', '顯示更多（還有 49 檔）', '其他觀察', '顯示 1／2 檔', '顯示更多（還有 1 檔）']) check(text(list).includes(line), `區塊: shows 「${line}」`)
check(count(list, '顯示更多') === 2, '顯示更多: only where the tier has rows not loaded')
check(count(list, 'data-action-row=') === 4 && count(list, 'data-action-card=') === 4, '區塊: one table row and one phone card per loaded row')
check(/<td><span class="candidate-rank"[^>]*>#1<\/span><\/td>/.test(list), '今日候選: the first cell is the rank')
check(count(list, 'href="/stocks/TWSE/1712?tab=research"') >= 2, '每列: links to the stock research tab')
check(count(list, '>2026/10/22</td>') === 4, '每列: a 資料日 cell YYYY/MM/DD')
check(text(list).includes('突破條件差 3 項'), '其他觀察: the 說明 column has the main reason')
check(render('ActionTierList empty', () => <ActionTierList sections={[]} loadingTiers={new Set()} canLoadMore={() => true} onMore={() => {}} />).includes(EMPTY_TEXT), '區塊: no rows, the empty line')
const loadedAll = render('ActionTierSectionView loaded', () => <ActionTierSectionView section={{ ...sections[1], shown: 1 }} canLoadMore onMore={() => {}} />)
check(!loadedAll.includes('顯示更多'), '顯示更多: none once every row is loaded')

// ---- the page: no state dropdown, sections from the cached first page ----
const ActionsPage = appComponent('ActionsPage')
const actionsPage = render('ActionsPage', () => <ActionsPage />, [[['actions', { view: 'focus' }], firstPage()], [['portfolio-subsection'], { items: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 0, has_next: false, has_previous: false } }]])
check(!actionsPage.includes('value="conditional_entry"') && !text(actionsPage).includes('全部行動狀態'), '行動頁: the state dropdown is gone')
check(text(actionsPage).includes('重點 54') && text(actionsPage).includes(sentence), '行動頁: chips and the hidden line render from the first page')
check(text(actionsPage).includes('顯示 2／2 檔') && actionsPage.indexOf('今日候選') < actionsPage.indexOf('其他成立條件'), '行動頁: tier sections in tier order')

// ---- a tier with no row on the first page shows its first rows on load (#301 review M2) ----
const candidatesOnly = () => page([candidate('1712', 1), candidate('6416', 2)])
check(previewTiers(candidatesOnly()).join(',') === '2,4', `首屏: tiers 2 and 4 have rows but none on the first page, got ${previewTiers(candidatesOnly()).join(',')}`)
check(previewTiers(firstPage()).length === 0, '首屏: every listed tier already has rows on the first page')
const tier2Rows = Array.from({ length: ACTION_TIER_PREVIEW }, (_, index) => row(String(2010 + index), 2, 'conditional_entry'))
const previewPage = render('ActionsPage preview', () => <ActionsPage />, [
  [['actions', { view: 'focus' }], candidatesOnly()],
  [['actions', { view: 'focus' }, 'tier', 2, 'preview'], { ...page(tier2Rows), meta: { ...page(tier2Rows).meta, next_cursor: 'tier-2-after-5', has_more: true } }],
  [['actions', { view: 'focus' }, 'tier', 4, 'preview'], page([row('1234', 4, 'no_condition', { watchlisted: true })])],
  [['portfolio-subsection'], { items: [], pagination: {} }],
])
check(text(previewPage).includes('顯示 5／50 檔') && text(previewPage).includes('顯示更多（還有 45 檔）'), `首屏: 其他成立條件 shows its first five rows, got ${text(previewPage).slice(text(previewPage).indexOf('第 2 級'), text(previewPage).indexOf('第 2 級') + 160)}`)
check(count(previewPage, 'data-action-row=') === 2 + ACTION_TIER_PREVIEW + 1, '首屏: candidate rows, five tier-2 rows and the tier-4 row')
check(!text(previewPage).includes('顯示 0／'), '首屏: no listed tier shows 0 rows')
const loadingTier = render('ActionTierSectionView loading', () => <ActionTierSectionView section={{ tier: 2, key: 'conditional', label: '其他成立條件', shown: 50, items: [], candidateListSize: 20 }} loading canLoadMore={false} onMore={() => {}} />)
check(loadingTier.includes('aria-busy="true"') && loadingTier.includes('class="card skeleton'), '首屏: a tier whose first rows are loading shows a skeleton, so screenshots wait for it')

// ---- tier 3 接近成立: the badge, 「差：」 lines and met short names, no level (#277-B) ----
const unmet = (item: Partial<ActionNearnessItem> & { code: string; kind: string }): ActionNearnessItem => ({
  short_label: null, gap: null, position: null, actual: null, threshold: null, threshold_high: null, operator: null, ...item,
})
const nearness = (extra: Partial<ActionNearness>): ActionNearness => ({
  strategy: 'breakout_v1', label: '突破條件', near: true, unmet_count: 1, price_gap: 0, unmet: [], met_short_labels: ['族群', '法人', '融資'], ...extra,
})
const breakoutNear = nearness({
  unmet_count: 2, price_gap: 0.021,
  unmet: [
    unmet({ code: 'breakout_price', kind: 'price', short_label: '價格', gap: 0.021, position: 'below' }),
    unmet({ code: 'breakout_volume', kind: 'volume', short_label: '量能', actual: 0.8, threshold: 1.2, operator: 'gte' }),
  ],
})
const pullbackNear = nearness({
  strategy: 'pullback_v1', label: '回踩條件', price_gap: 0.012, met_short_labels: ['趨勢', '族群', '法人', '融資'],
  unmet: [unmet({ code: 'pullback_support_zone', kind: 'price', short_label: '支撐區', gap: 0.012, position: 'above' })],
})
const volumeNear = nearness({
  strategy: 'pullback_v1', label: '回踩條件', met_short_labels: ['趨勢', '族群', '法人', '融資'],
  unmet: [unmet({ code: 'pullback_volume', kind: 'volume', short_label: '量能', actual: 1.3245, threshold: 0.6, threshold_high: 1.2, operator: 'between' })],
})
check(JSON.stringify(nearCopy(breakoutNear)) === JSON.stringify({ title: '接近突破條件', lines: ['差：收盤站上前 20 日高點（還差 2.10%）', '差：量能 ≥ 1.20 倍（今日 0.80 倍）'], met: '族群、法人、融資已達成' }), `接近突破: ${JSON.stringify(nearCopy(breakoutNear))}`)
check(JSON.stringify(nearCopy(pullbackNear)?.lines) === JSON.stringify(['差：收盤回到 20 日均線支撐區（高於上緣 1.20%）']), `接近回踩: ${JSON.stringify(nearCopy(pullbackNear))}`)
check(nearCopy({ ...pullbackNear, unmet: [{ ...pullbackNear.unmet[0], position: 'below', gap: 0.005 }] })?.lines[0] === '差：收盤回到 20 日均線支撐區（低於下緣 0.50%）', '接近回踩: below the zone says 低於下緣')
check(JSON.stringify(nearCopy(volumeNear)) === JSON.stringify({ title: '接近回踩條件', lines: ['差：量能 0.60～1.20 倍（今日 1.32 倍）'], met: '趨勢、族群、法人、融資已達成' }), `接近回踩量能: ${JSON.stringify(nearCopy(volumeNear))}`)
check(nearCopy(nearness({ near: false })) === null && nearCopy(null) === null, '接近: a tier 4 nearness or none is not a near card')
check(nearCopy(nearness({ unmet: [unmet({ code: 'margin_financing', kind: 'confirmation' })] }))?.lines[0] === '差：融資增加超過上限', '接近: a condition without a near sentence uses its unmet phrase')

const nearPage = page([
  row('2010', 2, 'conditional_entry', { trigger_price: 30, invalid_price: 28, target_1: 33 }),
  row('0050', 2, 'conditional_entry', { trigger_price: 30, invalid_price: 28, target_1: 33, instrument: { ...action('0050', 'ETF', 'x').instrument, instrument_type: 'etf' } }),
  // The summary's own levels are present on purpose: a near row must still not show them.
  row('1295', 3, 'no_condition', { nearness: volumeNear, trigger_price: 45.55, invalid_price: 44.12, target_1: 49.99 }),
  row('2330', 3, 'no_condition', { nearness: breakoutNear }),
  row('1234', 4, 'no_condition', { nearness: nearness({ near: false }), primary_reason: { label: '突破條件差 3 項：價格、量能、法人', scope: 'breakout' } }),
  row('5678', 4, 'no_condition', { nearness: null, primary_reason: { label: '回踩條件差 1 項：趨勢', scope: 'pullback' } }),
], {
  candidate_list_size: 20,
  tiers: summary().tiers.map((tier) => ({ ...tier, shown: tier.tier === 2 ? 2 : tier.tier === 3 ? 2 : tier.tier === 4 ? 2 : 0 })),
})
const nearList = render('ActionTierList near', () => <ActionTierList sections={tierSections(nearPage)} loadingTiers={new Set()} canLoadMore={() => true} onMore={() => {}} />)
const tierMarkup = (tier: number) => nearList.slice(nearList.indexOf(`data-tier="${tier}"`), nearList.indexOf('</section>', nearList.indexOf(`data-tier="${tier}"`)))
const near = tierMarkup(3)
check(count(near, 'data-action-row=') === 2 && count(near, 'data-action-card=') === 2, '接近成立: one row and one card per near stock')
for (const line of ['接近回踩條件', '差：量能 0.60～1.20 倍（今日 1.32 倍）', '趨勢、族群、法人、融資已達成', '接近突破條件', '差：收盤站上前 20 日高點（還差 2.10%）', '族群、法人、融資已達成', '差哪個條件']) check(text(near).includes(line), `接近成立: shows 「${line}」`)
check(count(near, '>差：') === 6, `接近成立: every 「差：」 line in the table and the card, got ${count(near, '>差：')}`)
check(count(near, NEAR_RESEARCH_LINK) === 4 && !near.includes('>策略總表 →<'), '接近成立: the link says 價位見策略總表 →')
check(!/level-(entry|stop|target)/.test(near) && !near.includes('candidate-mini-levels'), '接近成立: no level cell or level box')
check(!/45\.55|44\.12|49\.99/.test(near) && !near.includes('單位：價格'), '接近成立: none of the row levels, no level unit note')
check(near.includes('class="badge badge-primary badge-compact">接近回踩條件'), `接近成立: a primary badge, got ${near.slice(near.indexOf('接近回踩') - 80, near.indexOf('接近回踩'))}`)
const conditional = tierMarkup(2)
check(text(conditional).includes('條件成立，未進今日候選前 20') && text(conditional).includes('條件成立，ETF 不列入候選評分'), `其他成立條件: why it is not a candidate, got ${text(conditional).slice(0, 300)}`)
const observation = tierMarkup(4)
check(text(observation).includes('突破條件差 3 項：價格、量能、法人') && text(observation).includes('回踩條件差 1 項：趨勢'), '其他觀察: the 差 N 項 line')
check(count(observation, CONDITIONS_PENDING_TEXT) === 2, `其他觀察: 條件明細尚未產生 only without a strategy_levels row (table and card), got ${count(observation, CONDITIONS_PENDING_TEXT)}`)

// ---- 我的庫存: one line without holdings, the full section with them ----
const PortfolioSubsection = appComponent('PortfolioSubsection')
const emptyPortfolio = render('PortfolioSubsection empty', () => <PortfolioSubsection />, [[['portfolio-subsection'], { items: [], pagination: {} }]])
check(emptyPortfolio.includes('class="card portfolio-line"') && text(emptyPortfolio).includes('尚未建立庫存。') && text(emptyPortfolio).includes('有持倉風險時列在最上方。'), '庫存一行: no holdings, one line')
check(!emptyPortfolio.includes('portfolio-subsection') && emptyPortfolio.includes('新增庫存'), '庫存一行: not the full panel, the form still opens')
const position = { id: 1, instrument: { exchange: 'TWSE', symbol: '2330', name: '台積電' }, shares: 1000, shares_exact: true, average_cost: 900, stop_price: 850, portfolio_value_status: {}, portfolio_quote: null, market_value: null, unrealized_pnl: null, valuation_status: 'unavailable' } as unknown as Position
const fullPortfolio = render('PortfolioSubsection held', () => <PortfolioSubsection />, [[['portfolio-subsection'], { items: [position], pagination: {} }]])
check(fullPortfolio.includes('class="panel portfolio-subsection"') && fullPortfolio.includes('position-card') && !fullPortfolio.includes('portfolio-line'), '庫存: holdings show the full section')

// ---- /actions/:exchange/:symbol is the research tab; the stock page tab follows ?tab= ----
const redirect = (AppModule as unknown as { actionDetailRedirectPath: (exchange: string, symbol: string) => string }).actionDetailRedirectPath
check(redirect('TWSE', '2330') === '/stocks/TWSE/2330?tab=research', `轉址: /actions/TWSE/2330 → ${redirect('TWSE', '2330')}`)
check(parseStockTab('research') === 'research' && parseStockTab(null) === 'chart' && parseStockTab('nope') === 'chart', '個股分頁: ?tab= opens that tab, else 圖表')
check(stockTabSearch(new URLSearchParams('as_of=2026-10-21'), 'news').toString() === 'as_of=2026-10-21&tab=news', '個股分頁: switching writes ?tab= and keeps as_of')
check(stockTabSearch(new URLSearchParams('tab=news'), 'chart').toString() === '', '個股分頁: the default tab is not written')

// ---- today: the holding line counts every holding, not the first 8 actions (#297 review L1) ----
const quiet = Array.from({ length: 8 }, (_, index) => action(String(1101 + index), `持倉${index}`, 'hold_observe', { held: true }))
const ninth = action('9999', '第九檔', 'reduce_exit', { held: true })
const dashboard = { as_of: '2026-10-22', mode: 'official', scan_scope: '', market: { instruments: 1, bars: 1, groups: 0, source: 'official' }, data_quality: { latest_run: 'success', latest_run_source: null, latest_run_date: null, latest_run_records: 0, data_as_of: null, error: null, updated_at: null }, groups: [], signals: [], signal_status_counts: {}, actions: quiet, holding_actions: [ninth, ...quiet], candidates: [] } as unknown as Dashboard
const TodayPage = appComponent('TodayPage')
const today = render('TodayPage', () => <TodayPage />, [[['dashboard'], dashboard]])
check(text(today).includes('持倉風險 1 檔：9999 第九檔：減碼／退場條件'), `今日持倉提示列: reads holding_actions, got ${text(today).slice(0, 400)}`)

if (failures.length) throw new Error(`${failures.length} of ${checks} action-tier checks failed:\n- ${failures.join('\n- ')}`)
