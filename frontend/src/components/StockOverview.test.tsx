import { renderToStaticMarkup } from 'react-dom/server'
import { formatCanonicalShareLots } from '../units'
import { createPriceMemoryFixture, priceFixtureInstrument } from '../stockPriceMemoryRead.test'
import { PRICE_BODY_SHA, PRICE_SCOPE_POLICY_VERSION } from '../stockPriceMemoryRead'
import { InstitutionalDaily, InstitutionalWindows, formatWindowShares, StockOverview, overviewReason, OfficialEvents } from './StockOverview'
import type { InstitutionalDailyData, InstitutionalWindowsData, StockOverviewData, OfficialEventsData } from '../types'
import type { ReactElement } from 'react'

export function runPriceMemoryOverviewSSRTests(render: (element: ReactElement) => string): number {
  let count = 0
  const check = (value: boolean, message: string) => { count++; if (!value) throw new Error(message) }
  const third = createUnitLotsFixture()
  third.as_of = '2026-10-06'; third.price_memory = createPriceMemoryFixture('5347', '2026-10-06', PRICE_SCOPE_POLICY_VERSION)
  const thirdHtml = render(<StockOverview data={third} instrument={priceFixtureInstrument('5347')} explicitCutoff="2026-10-06" onNews={() => {}} onCapturePrice={() => {}} />)
  check(thirdHtml.includes('34,637.793') && thirdHtml.includes('6,615,109,776') && thirdHtml.includes('>191<'), 'third ordinary stock exact lots/TWD and per-share close')
  check(thirdHtml.includes('金融數值僅核 3105、5347、6488') && thirdHtml.includes('資料列序 532'), 'third policy scope and original row visible')
  const thirdConflict = render(<StockOverview data={third} instrument={priceFixtureInstrument('5347')} explicitCutoff="2026-10-05" onNews={() => {}} />)
  check(!thirdConflict.includes('34,637.793') && !thirdConflict.includes('查看官方價格原列、來源版本與 SHA'), 'third cutoff conflict rejects raw projection')
  for (const scope of [undefined, null, {}, { ...third.price_memory!.supported_scope, symbols: 'bad' },
    { ...third.price_memory!.supported_scope, symbols: ['3105', '9999', '6488'] }]) {
    const malformed = structuredClone(third)
    malformed.price_memory!.supported_scope = scope as unknown as NonNullable<StockOverviewData['price_memory']>['supported_scope']
    const html = render(<StockOverview data={malformed} instrument={priceFixtureInstrument('5347')} explicitCutoff="2026-10-06" onNews={() => {}} />)
    check(html.includes('支持範圍待核實') && !html.includes('本次政策支持的上櫃普通股：') && !html.includes('金融數值僅核') && !html.includes('34,637.793'), 'missing/malformed/unknown scope renders a gap without approved scope or values')
  }
  const unknownTuple = structuredClone(third)
  unknownTuple.price_memory!.provenance!.policy_version = 'unknown'
  const unknownTupleHtml = render(<StockOverview data={unknownTuple} instrument={priceFixtureInstrument('5347')} explicitCutoff="2026-10-06" onNews={() => {}} />)
  check(unknownTupleHtml.includes('支持範圍待核實') && !unknownTupleHtml.includes('本次政策支持的上櫃普通股：'), 'unknown policy cannot advertise an approved scope')
  for (const symbol of ['3105', '6488']) {
    const fixture = createUnitLotsFixture()
    fixture.as_of = '2026-10-05'
    fixture.price_memory = createPriceMemoryFixture(symbol)
    const instrument = priceFixtureInstrument(symbol)
    const html = render(<StockOverview data={fixture} instrument={instrument} explicitCutoff="2026-10-05" onNews={() => {}} onCapturePrice={() => {}} />)
    const primary = html.split('<summary>查看官方價格原列、來源版本與 SHA</summary>')[0]
    check(primary.includes(symbol === '3105' ? '48,127.911' : '18,982.607'), 'daily primary exact lots')
    check(primary.includes(symbol === '3105' ? '29,694,939,981' : '22,887,612,060'), 'amount exact TWD')
    check(primary.includes('收盤（元／股）') && primary.includes(symbol === '3105' ? '>615<' : '>1,180<'), 'price stays per share')
    check(!html.includes('既有價格與實際視窗'), 'memory valid hides old primary price panel')
    check(html.includes('成交股數') && html.includes(symbol === '3105' ? '48127911' : '18982607'), 'raw shares remain labelled source audit')
    check(html.includes('原件 SHA-256') && html.includes(PRICE_BODY_SHA), 'source pin visible in details')
    check(html.includes('政府資料開放授權條款 OGL 1.0') && html.includes('櫃買中心 · 上櫃股票行情（11370）'), 'source attribution actual TPEx')
    check(html.includes('本次暫存，重啟後需重新載入') && html.includes('此資料只含一天，趨勢與研究條件仍待補'), 'user limitations plain text')
    const conflict = render(<StockOverview data={fixture} instrument={instrument} explicitCutoff="2026-10-02" onNews={() => {}} onCapturePrice={() => {}} />)
    check(!conflict.includes('查看官方價格原列、來源版本與 SHA') && !conflict.includes(symbol === '3105' ? '48,127.911' : '18,982.607'), 'URL/response cutoff conflict never admits memory')
    const reversed = structuredClone(fixture)
    reversed.as_of = '2026-10-02'
    const reversedHTML = render(<StockOverview data={reversed} instrument={instrument} explicitCutoff="2026-10-05" onNews={() => {}} onCapturePrice={() => {}} />)
    check(!reversedHTML.includes('查看官方價格原列、來源版本與 SHA') && !reversedHTML.includes(symbol === '3105' ? '48,127.911' : '18,982.607'), 'URL10/5 and memory10/5 cannot override overview10/2')
    const twse = render(<StockOverview data={fixture} instrument={{ ...instrument, exchange: 'TWSE' }} explicitCutoff="2026-10-05" onNews={() => {}} />)
    check(!twse.includes('櫃買官方單日行情'), 'outside-market panel absent')
    const unknown = render(<StockOverview data={fixture} instrument={{ ...instrument, symbol: '9999' }} explicitCutoff="2026-10-05" onNews={() => {}} />)
    check(!unknown.includes('櫃買官方單日行情'), 'outside-symbol panel absent')
    const malformed = render(<StockOverview data={fixture} instrument={{ ...instrument, name: 'unknown' }} explicitCutoff="2026-10-05" onNews={() => {}} onCapturePrice={() => {}} />)
    check(malformed.includes('記憶體行情契約待核實') && malformed.includes('disabled=""'), 'bad catalogue identity disabled')
  }
  return count
}


const windowOnly = ['unit-lots-only', 'w3-only', 'w4-only', 'w5-only', 'w6-only', 'w7-only', 'w8-only'].includes((globalThis as typeof globalThis & { __institutionalWindowSSRSelection?: string }).__institutionalWindowSSRSelection ?? '')
let originalAssertionCount = 0
function expect(condition: boolean, message: string): void {
  originalAssertionCount += 1
  if (!condition) throw new Error(message)
}

const latest = {
  date: '2026-10-01', open: 26.3, high: 26.4, low: 25.45, close: 25.55, volume: 0,
  turnover: 0, turnover_status: 'available', turnover_reason: null, source: 'twse',
  data_as_of: '2026-10-01T00:00:00', collected_at: '2026-10-02T20:49:16',
  provenance: { raw_payload_id: 1, ingestion_run_id: 1, source_id: 'twse_stock_day_all', source_version: '1.0',
    endpoint: 'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', body_sha256: 'b'.repeat(64), receipt_sha256: 'c'.repeat(64),
    registry_version: 'pinned', manifest_digest: 'sha256:' + 'd'.repeat(64), captured_at: '2026-10-02T20:49:15+00:00',
    raw_collected_at: '2026-10-02T20:49:15', verification: 'local_evidence_consistent', license: {}, summarize_decision: {} },
} satisfies NonNullable<StockOverviewData['price']['latest']>
const data: StockOverviewData = {
  version: 'stock-overview/p1-v1', as_of: '2026-10-02', cutoff_basis: 'data_date_inclusive', historical_pit: 'unsupported', scope: 'M1-P1',
  price: { status: 'available', basis: 'original_api_ohlcv', window_limit: 120, candidate_count: 2, valid_count: 1,
    from: latest.date, to: latest.date, latest, bars: [latest], rejected: [{ date: '2026-10-02', reason: 'price_raw_evidence_missing' }],
    reasons: ['price_latest_before_cutoff', 'price_raw_evidence_missing'] },
  institutional: { status: 'unavailable', horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], values: null,
    reasons: ['institutional_sources_not_admitted', 'trading_session_source_not_admitted'] },
  conditions: [{ strategy: 'breakout_v1', label: '突破條件', version: '1.0.0', signal_date: '2026-09-30', status: 'data_insufficient',
    reasons: ['strategy_input_sources_not_admitted', 'strategy_time_evidence_not_verified', 'industry_membership_not_verified'] }],
  events: { version: 'official-events/p3b-v1', status: 'unavailable', reasons: ['event_capture_not_enabled'],
    as_of: '2026-10-02', observed_date: null, cutoff_basis: 'observed_taipei_date_inclusive', capture_enabled: false, can_capture: false, cache_present: false,
    capture_action: 'not_attempted', storage: 'memory_only', durable_capture: false, historical_pit: 'unsupported', source_url_kind: 'feed',
    published_time: 'unknown', first_availability: 'unknown', revision_history: 'unknown', rows: [], provenance: null, attribution: null, limitations: [] }, limitations: [],
}
if (!windowOnly) {
const html = renderToStaticMarkup(<StockOverview data={data} onNews={() => {}} />)
expect(html.includes('2026/10/02') && html.includes('2026/10/01'), 'cutoff and latest usable date remain visibly separate')
expect(html.includes('25.55') && html.includes('成交額（來源計價單位）：0'), 'price and explicit zero amount are retained')
expect(html.includes('成交量（張）') && html.includes('<strong>0</strong>'), 'explicit zero volume stays visible')
expect(html.includes('最新可用行情早於研究截止日期') && html.includes('缺少已核對的交易日基準'), 'real independent source/date blockers are visible')
expect(html.includes('不代表歷史當時可得') && html.includes('不代表完整交易日窗口'), 'date cutoff does not claim PIT or complete trading sessions')
expect(html.includes('查看新聞與公告') && html.includes('既有族群關聯待重新核實'), 'news entry and existing classification warning remain usable')
expect(html.includes('<summary>查看策略版本</summary>breakout_v1'), 'technical strategy identity stays in details')
expect(overviewReason('body_changed').includes('不穩定'), 'changed local evidence has understandable copy')

const missing = { ...latest, turnover: null, turnover_status: 'unavailable' as const, turnover_reason: 'missing' }
const missingHtml = renderToStaticMarkup(<StockOverview data={{ ...data, price: { ...data.price, latest: missing, bars: [missing] } }} onNews={() => {}} />)
expect(missingHtml.includes('未提供') && missingHtml.includes('未補零') && !missingHtml.includes('成交額（來源計價單位）：0'), 'missing amount never renders as explicit zero')

const unavailableHtml = renderToStaticMarkup(<StockOverview data={{ ...data, price: { ...data.price, status: 'unavailable', latest: null, bars: [], valid_count: 0, from: null, to: null } }} onNews={() => {}} />)
expect(unavailableHtml.includes('尚無來源與數值已核對的價格') && unavailableHtml.includes('查看新聞與公告'), 'unavailable price does not hide independent entry points')

for (const [volume_exact, lots, shares] of [
  ['0', '0', '0'],
  ['9007199254740993', '9,007,199,254,740.993', '9,007,199,254,740,993'],
  ['9223372036854775807', '9,223,372,036,854,775.807', '9,223,372,036,854,775,807'],
]) {
  const bar = { ...latest, volume: Number(volume_exact), volume_exact }
  const exactHtml = renderToStaticMarkup(<StockOverview data={{ ...data, price: { ...data.price, latest: bar, bars: [bar] } }} onNews={() => {}} />)
  expect(exactHtml.includes(`<strong>${lots}</strong>`) && exactHtml.includes(`<td>${shares}</td>`), 'overview latest lots and original shares both preserve canonical digits')
}
for (const bar of [
  { ...latest, volume: Number('9007199254740993') },
  { ...latest, volume: 1000, volume_exact: null },
  { ...latest, volume: 1000, volume_exact: '01' },
  { ...latest, volume: 1000, volume_exact: '9223372036854775808' },
]) {
  const invalidHtml = renderToStaticMarkup(<StockOverview data={{ ...data, price: { ...data.price, latest: bar, bars: [bar] } }} onNews={() => {}} />)
  expect(invalidHtml.includes('數值或單位待核實') && !invalidHtml.includes('<strong>1</strong>') && !invalidHtml.includes('<td>1,000</td>'), 'overview rejects malformed exact text and unsafe legacy numbers without fallback')
}
}
const investor = (label: string, buy: string, sell: string, net: string) => ({ label, buy, sell, net, source_fields: { buy: 'buy', sell: 'sell', net: 'net' } })
const daily: InstitutionalDailyData = {
  version: 'institutional-daily/p2b-v1', status: 'available', as_of: '2026-10-03', date: '2026-10-02',
  selection_basis: 'explicit_configured_single_day', unit: 'shares', quantity_encoding: 'canonical_integer_string', historical_pit: 'unsupported',
  reasons: ['daily_configured_date_before_cutoff'], limitations: [],
  session_windows: { status: 'unavailable', horizons: [5, 20], reasons: ['multi_session_institutional_evidence_missing'] },
  row: { symbol: '3105', company_name: '穩懋', date: '2026-10-02', source_date: '1151002', exchange: 'TPEx', unit: 'shares', row_ordinal: 175,
    investors: { foreign: investor('外資及陸資（不含外資自營商）', '10547941', '3264551', '7283390'), trust: investor('投信', '0', '27000', '-27000'), dealer: investor('自營商', '1070812', '86707', '984105') }, total_net: '8240495' },
  provenance: { source_id: 'tpex_3insti_daily_trading', source_version: 'pinned-source', endpoint: 'https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading',
    registry_version: 'pinned-registry', manifest_digest: 'sha256:' + 'd'.repeat(64), body_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), captured_at: '2026-10-02T21:33:02+00:00', verification: 'local_evidence_consistent' },
  attribution: { owner: { name: 'Taipei Exchange', data_provider: '金融監督管理委員會證券期貨局', dataset_name: '上櫃股票三大法人買賣明細資訊', license_url: 'https://data.gov.tw/license', attribution_year: 2026 },
    dataset_id: 'data-gov-11856', source_id: 'tpex_3insti_daily_trading', source_url: 'https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading', terms: {}, evidence: [], purpose_evidence: {} },
}
if (!windowOnly) {
const dailyHtml = renderToStaticMarkup(<StockOverview data={{ ...data, as_of: '2026-10-03', institutional_daily: daily }} onNews={() => {}} />)
expect(dailyHtml.includes('單日法人原件') && dailyHtml.includes('穩懋（3105）') && dailyHtml.includes('單位：張') && dailyHtml.includes('來源稽核原值（股）'), 'selected original has a lots main value and labelled original shares')
for (const quantity of ['10,547,941', '3,264,551', '7,283,390', '-27,000', '1,070,812', '86,707', '984,105', '8,240,495']) expect(dailyHtml.includes(quantity), 'separate investor quantities and total retained: ' + quantity)
expect(dailyHtml.includes('原始資料日 1151002') && dailyHtml.includes('原件列序 175') && dailyHtml.includes('a'.repeat(64)) && dailyHtml.includes('b'.repeat(64)), 'source date, ordinal and both hashes retained')
expect(dailyHtml.includes('尚未確認截至日前最新資料') && dailyHtml.includes('最近 5／20 交易日淨買賣超與趨勢尚不可用'), 'a configured date before cutoff never claims latest or completes windows')
expect(dailyHtml.includes('金融監督管理委員會證券期貨局') && dailyHtml.includes('https://data.gov.tw/license'), 'attribution and license link visible')

const large = { ...daily, row: { ...daily.row!, total_net: '-9223372036854775807', investors: { ...daily.row!.investors, foreign: investor('外資', '9223372036854775807', '0', '-9223372036854775807') } } }
const largeHtml = renderToStaticMarkup(<InstitutionalDaily data={large} />)
expect(largeHtml.includes('9,223,372,036,854,775,807') && largeHtml.includes('-9,223,372,036,854,775,807'), 'int64 canonical text is never rounded through Number')
const zeroHtml = renderToStaticMarkup(<InstitutionalDaily data={{ ...daily, row: { ...daily.row!, total_net: '0' } }} />)
expect(zeroHtml.includes('<td>0</td>'), 'verified exact zero remains a visible zero')
const rejectedHtml = renderToStaticMarkup(<InstitutionalDaily data={{ ...daily, status: 'unavailable', row: null, provenance: null, reasons: ['daily_after_cutoff'] }} />)
expect(rejectedHtml.includes('本次不採用') && rejectedHtml.includes('尚無可核對的單日法人原件') && !rejectedHtml.includes('10,547,941'), 'future original is hidden without legacy fallback')
console.log('StockOverview original price/daily', originalAssertionCount, 'checks passed')
}

function check(condition: boolean, label: string): void {
  if (!condition) throw new Error(label)
}

export function runOfficialEventsSSRTests(render: (element: ReactElement) => string): number {
  const data: OfficialEventsData = {
    version: 'official-events/p3b-v1', status: 'available', reasons: [], as_of: '2026-10-03', observed_date: '2026-10-03',
    cutoff_basis: 'observed_taipei_date_inclusive', capture_enabled: true, can_capture: true, cache_present: true,
    capture_action: 'cached', storage: 'memory_only', durable_capture: false, historical_pit: 'unsupported', source_url_kind: 'feed',
    published_time: 'unknown', first_availability: 'unknown', revision_history: 'unknown', limitations: [],
    rows: [{ exchange: 'TWSE', symbol: '0056', company_name: '元大高股息', event_date: '2026-10-22', source_date: '1151022',
      source_classification: '息', event_date_role: 'effective_date', event_date_precision: 'date', kind: 'ex_dividend', label: '除息',
      row_ordinal: 5, published_at: null, first_available_at: null, revision_available_at: null, availability: 'unknown' },
    { exchange: 'TWSE', symbol: '0056', company_name: '元大高股息', event_date: '2026-11-22', source_date: '1151122',
      source_classification: '權息', event_date_role: 'effective_date', event_date_precision: 'date', kind: 'ex_right_and_dividend', label: '除權息',
      row_ordinal: 6, published_at: null, first_available_at: null, revision_available_at: null, availability: 'unknown' }],
    provenance: { source_id: 'twse_twt48u_all', source_version: 'twse-twt48u-all-d011-2026-09-12',
      endpoint: 'https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL', registry_version: 'r1-a1-c009-2026-09-12.1',
      manifest_digest: 'sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b',
      body_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), captured_at: '2026-10-02T16:00:01+00:00',
      request_started_at: '2026-10-02T16:00:00+00:00', storage: 'memory_only', verification: 'local_evidence_consistent' },
    attribution: { owner: { name: 'Taiwan Stock Exchange (TWSE)', type: 'official_exchange' },
      dataset_id: 'data-gov-89748', source_id: 'twse_twt48u_all', source_url: 'https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL',
      terms: { status: 'known', value: 'OGL 1.0', reason: 'Dataset and data.gov license pages provide the reuse terms.' },
      evidence: [
        { url: 'https://openapi.twse.com.tw/v1/swagger.json', checked_at: '2026-09-12 Asia/Taipei', claim: 'Swagger documents the exact GET path and no parameters.' },
        { url: 'https://data.gov.tw/dataset/89748', checked_at: '2026-09-12 Asia/Taipei', claim: 'Dataset 89748 identifies irregular update, free access, and OGL 1.0.' },
        { url: 'https://data.gov.tw/license', checked_at: '2026-09-12 Asia/Taipei', claim: 'The OGL 1.0 terms require attribution and preserve source-integrity conditions.' },
      ], purpose_evidence: {} },
  }
  const html = render(<OfficialEvents data={data} onCapture={() => undefined} />)
  check(html.includes('2026/10/22') && html.includes('2026/11/22') && html.includes('元大高股息'), 'future multi-event identity/date')
  check(html.includes('原件列序 5') && html.includes('1151022') && html.includes('原始分類 息')
    && html.includes('a'.repeat(64)) && html.includes('b'.repeat(64)) && html.includes(data.provenance!.captured_at), 'exact provenance')
  check(html.includes('查看官方公告資料集') && html.includes('未提供單則原文') && html.includes('發布、首次可得與修訂時間均未知')
    && html.includes('記憶體') && html.includes('不推論價格影響') && html.includes('讀取本次官方除權息預告'), 'scope and cache copy')
  check(html.includes('資料提供：Taiwan Stock Exchange (TWSE)') && html.includes('授權 OGL 1.0')
    && html.includes('href="https://data.gov.tw/license"') && !html.includes('資料提供： ·'), 'actual TWSE attribution shape and pinned license href')
  const before = render(<OfficialEvents data={{ ...data, status: 'unavailable', rows: [], provenance: null,
    reasons: ['event_observation_after_cutoff'], as_of: '2026-10-02' }} onCapture={() => undefined} />)
  check(before.includes('本次觀測日晚於研究截止') && before.includes('2026/10/03') && before.includes('請將研究截止日期設為此日')
    && !before.includes('元大高股息') && !before.includes('2026/10/22'), 'cutoff rejection without event leakage')
  const missing = render(<OfficialEvents data={{ ...data, status: 'unavailable', rows: [], provenance: null, observed_date: null,
    reasons: ['event_memory_capture_missing'], cache_present: false }} onCapture={() => undefined} requestFailure="selected_symbol_missing:0056" />)
  check(missing.includes('取得本次官方除權息預告') && missing.includes('無法據此宣稱沒有事件') && missing.includes('role="alert"'), 'explicit capture and failed POST copy')
  const disabled = render(<OfficialEvents data={{ ...data, status: 'unavailable', rows: [], provenance: null, observed_date: null,
    reasons: ['event_capture_not_enabled'], capture_enabled: false, can_capture: false, cache_present: false }} onCapture={() => undefined} />)
  check(disabled.includes('伺服器尚未明示啟用') && !disabled.includes('<button') && !disabled.includes('元大高股息'), 'disabled operation hidden')
  const busy = render(<OfficialEvents data={data} onCapture={() => undefined} busy requestFailure="receipt_mismatch:body_sha256" />)
  check(busy.includes('disabled=""') && busy.includes('正在取得官方預告') && busy.includes('擷取紀錄與原件') && !busy.includes('法人原件'), 'busy and neutral evidence failure')
  return 8
}

if (!windowOnly) console.log('OfficialEvents new SSR', runOfficialEventsSSRTests(renderToStaticMarkup), 'checks passed')

export function runInstitutionalWindowSSRTests(render: (element: ReactElement) => string): number {
  const dates = ['2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02']
  const base: InstitutionalWindowsData = {
    version: 'institutional-windows/w3-v1', status: 'available', as_of: '2026-10-02', horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], values: null, reasons: [],
    unit: 'shares', quantity_encoding: 'canonical_integer_string', historical_pit: 'unsupported',
    supported_scope: { exchange: 'TPEx', symbols: ['3105', '6488'], supported_cutoffs: ['2026-09-30', '2026-10-01', '2026-10-02'], calendar_from: '2026-09-01', calendar_to: '2026-10-02' },
    capture_state: { enabled: true, attempted: true, busy: false, can_capture: true, cache_present: true, action: 'cached', request_count: 24 },
    calendar: { version: 'bounded-test', status: 'available', expected_dates: dates, valid_dates: dates, missing_dates: [],
      basis: { weekday_rule: 'https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html', closed_notice: 'https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html', closed_dates: ['2026-09-25', '2026-09-28'] }, evidence: [] },
    windows: { '5': { horizon: 5, status: 'available', values: { foreign: '46116860184273879035', trust: '-9007199254740993', dealer: '0' }, from: dates[0], to: dates[4], required_dates: dates, valid_dates: dates, missing_dates: [], invalid_dates: [], reasons: [] },
      '20': { horizon: 20, status: 'unavailable', values: null, from: '2026-09-03', to: dates[4], required_dates: ['2026-09-03', ...dates], valid_dates: dates, missing_dates: ['2026-09-03'], invalid_dates: [], reasons: ['institutional_window_expected_dates_missing'] } },
    policy: { version: 'test-version', digest: 'sha256:' + 'a'.repeat(64), profile: 'free_public_local' }, calculation_version: 'test-calc',
  }
  const html = render(<InstitutionalWindows data={base} onCapture={() => undefined} />)
  check(html.includes('46,116,860,184,273,879.035') && html.includes('-9,007,199,254,740.993') && html.includes('>0</td>'), 'large signed/zero lots preserve every share')
  check(html.includes('所需 5／已驗 5／缺 0 日') && html.includes('所需 6／已驗 5／缺 1 日') && html.includes('2026/09/24') && html.includes('2026/10/02'), 'independent partial window ranges and counts')
  check(html.includes('讀取本次法人窗口') && html.includes('OGL 1.0') && html.includes('https://data.gov.tw/dataset/11856') && html.includes('https://data.gov.tw/dataset/11391'), 'read same memory and attributed dataset links')
  check(html.includes('<details') && html.includes('2026-09-25、2026-09-28') && html.includes('發布、首次可得與修訂時間均未知') && html.includes('PIT 未支援'), 'explicit calendar and unknown time scope in source details')
  const initial = render(<InstitutionalWindows data={{ ...base, windows: {}, capture_state: { ...base.capture_state!, attempted: false, cache_present: false } }} onCapture={() => undefined} />)
  check(initial.includes('載入5／20日法人窗口') && !initial.includes('184,467'), 'explicit first load without cached values')
  const busy = render(<InstitutionalWindows data={base} busy onCapture={() => undefined} requestFailure="window_capture_failed" />)
  check(busy.includes('disabled=""') && busy.includes('正在載入法人窗口') && busy.includes('role="alert"'), 'busy and defined request error')
  for (const value of ['01', '-0', '1e3', 1000, null]) {
    check(formatWindowShares(value) === null, 'malformed quantity is rejected')
    const invalid = render(<InstitutionalWindows data={{ ...base, windows: { ...base.windows, '5': { ...base.windows!['5'], values: { ...base.windows!['5'].values!, foreign: value as string } } } }} />)
    check(invalid.includes('數值或窗口條件待核對') && !invalid.includes('-9,007,199,254,740,993'), 'invalid horizon does not partially display numerical values')
  }
  const unsupported = render(<InstitutionalWindows data={{ ...base, as_of: '2026-10-03', windows: {}, reasons: ['window_cutoff_not_supported'], capture_state: { ...base.capture_state!, can_capture: false } }} onCapture={() => undefined} />)
  check(unsupported.includes('不沿用其他截止的數值') && !unsupported.includes('184,467') && !unsupported.includes('<button'), 'unsupported cutoff cannot display or capture another cutoff')
  const whole = render(<StockOverview data={{ ...data, institutional: base, institutional_daily: daily }} onNews={() => undefined} />)
  check(!whole.includes('窗口仍不可用') && whole.includes('5／20 日窗口請見上方') && whole.includes('其他範圍與研究條件尚未完成'), 'single-day and footer copy agrees with independent windows')
  return 18
}

export function runInstitutionalWindowCutoffSSRTests(render: (element: ReactElement) => string, earlier = false, fifth = false, sixth = false, seventh = false, eighth = false): number {
  let checks = 0
  const verify = (condition: boolean, message: string) => { checks++; if (!condition) throw new Error(message) }
  const sessions = [...(eighth ? ['2026-08-25'] : []), ...(seventh ? ['2026-08-26'] : []), ...(sixth ? ['2026-08-27'] : []), ...(fifth ? ['2026-08-28'] : []), ...(earlier ? ['2026-08-31'] : []), '2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08',
    '2026-09-09', '2026-09-10', '2026-09-11', '2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18',
    '2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02']
  const cutoffs = [...(eighth ? ['2026-09-21'] : []), ...(seventh ? ['2026-09-22'] : []), ...(sixth ? ['2026-09-23'] : []), ...(fifth ? ['2026-09-24'] : []), ...(earlier ? ['2026-09-29'] : []), '2026-09-30', '2026-10-01', '2026-10-02']
  for (const [offset, cutoff] of cutoffs.entries()) {
    const dates = sessions.slice(offset, offset + 20)
    const windows = Object.fromEntries([5, 20].map((horizon) => {
      const selected = dates.slice(-horizon)
      return [String(horizon), { horizon, status: 'available', values: { foreign: horizon === 5 ? '46116860184273879035' : '184467440737095516140', trust: '-9007199254740993', dealer: '0' },
        from: selected[0], to: cutoff, required_dates: selected, valid_dates: selected, missing_dates: [], invalid_dates: [], reasons: [],
        daily_evidence: selected.map((day) => ({ row: { symbol: '3105', company_name: `TRACE-${day}`, date: day, source_date: day.replace(/-/g, ''), row_ordinal: 1,
          investors: { foreign: investor('外資', '100', '0', '100'), trust: investor('投信', '0', '0', '0'), dealer: investor('自營商', '0', '0', '0') }, total_net: '100' },
          provenance: { source_id: 'synthetic', source_version: 'v2', requested_date: day, url: 'https://data.gov.tw/dataset/11856', method: 'GET',
            body_sha256: 'a'.repeat(64), body_bytes: 100, captured_at: '2026-10-04T00:00:01+00:00', request_started_at: '2026-10-04T00:00:00+00:00',
            policy_version: 'test', policy_digest: 'test', profile: 'free_public_local', historical_pit: 'unsupported' } })) }]
    })) as NonNullable<InstitutionalWindowsData['windows']>
    const base: InstitutionalWindowsData = {
      version: eighth ? 'institutional-windows/w8-v1' : seventh ? 'institutional-windows/w7-v1' : sixth ? 'institutional-windows/w6-v1' : fifth ? 'institutional-windows/w5-v1' : earlier ? 'institutional-windows/w4-v1' : 'institutional-windows/w3-v1', status: 'available', as_of: cutoff, horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], values: null, reasons: [],
      unit: 'shares', quantity_encoding: 'canonical_integer_string', historical_pit: 'unsupported', windows,
      supported_scope: { exchange: 'TPEx', symbols: ['3105', '6488'], supported_cutoffs: cutoffs, calendar_from: sessions[0], calendar_to: sessions[sessions.length - 1] },
      calendar: { version: 'bounded', status: 'available', expected_dates: sessions, valid_dates: sessions, missing_dates: [],
        evidence: earlier ? [{ ...windows['20'].daily_evidence![0].provenance, source_id: 'synthetic-index', requested_date: '2026-08-01',
          candidate_count: 21, adopted_count: eighth ? 5 : seventh ? 4 : sixth ? 3 : fifth ? 2 : 1, pre_calendar_row_count: eighth ? 16 : seventh ? 17 : sixth ? 18 : fifth ? 19 : 20, validation_scope: 'all_returned_month_rows' }] : [] },
      capture_state: { enabled: true, attempted: true, busy: false, can_capture: true, cache_present: true, action: 'cached', request_count: eighth ? 30 : seventh ? 29 : sixth ? 28 : fifth ? 27 : earlier ? 26 : 24 },
    }
    const html = render(<InstitutionalWindows data={base} onCapture={() => undefined} />)
    const primary = html.split('<details')[0]
    verify(primary.includes('184,467,440,737,095,516.14') && primary.includes('46,116,860,184,273,879.035')
      && primary.includes('-9,007,199,254,740.993') && primary.includes('>0</td>')
      && html.includes('窗口來源稽核原值（股）') && html.includes('184,467,440,737,095,516,140'), 'supported cutoff main lots and labelled audit share strings are independently exact')
    verify(html.includes('所需 20／已驗 20／缺 0 日') && html.includes('所需 5／已驗 5／缺 0 日'), 'two complete fixed horizons')
    verify(html.includes(`TRACE-${dates[0]}`) && html.includes(`TRACE-${cutoff}`) && html.includes(cutoff.replace(/-/g, '/')), 'same cutoff source expansion')
    verify(html.includes(cutoffs.map((day) => day.replace(/-/g, '/')).join('、')) && html.includes('各窗口只採用截至所選日期的原件'), 'supported cutoffs and batch/adoption scope')
    if (earlier) {
      verify(html.includes(`${eighth ? '2026/08/25' : seventh ? '2026/08/26' : sixth ? '2026/08/27' : fifth ? '2026/08/28' : '2026/08/31'} — 2026/10/02`) && !html.includes('只支持 2026/09/01'), 'earlier calendar scope is displayed')
      verify(html.includes(`完整月原件已驗 21 列／本範圍採用 ${eighth ? 5 : seventh ? 4 : sixth ? 3 : fifth ? 2 : 1} 列／界線前已驗但未採用 ${eighth ? 16 : seventh ? 17 : sixth ? 18 : fifth ? 19 : 20} 列`), 'full-month validation differs from adopted dates')
    }
    const noScope = render(<InstitutionalWindows data={earlier ? { ...base, as_of: '2026-09-28' } : { ...base, supported_scope: { ...base.supported_scope!, supported_cutoffs: [] } }} onCapture={() => undefined} />)
    verify(!noScope.includes('184,467') && !noScope.includes('<button') && !noScope.includes('TRACE-'), 'unsupported scope hides values/action/source rows')
    const wrongEnd = render(<InstitutionalWindows data={{ ...base, windows: { '20': { ...windows['20'], to: '2026-10-03' } } }} />)
    verify(!wrongEnd.includes('184,467') && wrongEnd.includes('數值或窗口條件待核對'), 'another cutoff cannot supply a displayed net')
    const partial = render(<InstitutionalWindows data={{ ...base, windows: { ...windows, '20': { ...windows['20'], status: 'unavailable', values: null,
      valid_dates: dates.slice(1), missing_dates: [dates[0]], reasons: ['institutional_window_expected_dates_missing'] } } }} />)
    verify(partial.includes('所需 20／已驗 19／缺 1 日') && partial.includes(`缺日：${dates[0]}`) && partial.includes('46,116'), 'partial twenty keeps five and exact missing date')
    const futureRow = { ...windows['20'].daily_evidence![0], row: { ...windows['20'].daily_evidence![0].row, date: '2026-10-03', company_name: 'FUTURE-SENTINEL' } }
    const future = render(<InstitutionalWindows data={{ ...base, windows: { ...windows, '20': { ...windows['20'], daily_evidence: [...windows['20'].daily_evidence!, futureRow] } } }} />)
    verify(!future.includes('FUTURE-SENTINEL'), 'batch future records never appear as adopted source rows')
    if (fifth) {
      const unsupported = render(<InstitutionalWindows data={{ ...base, as_of: '2026-09-28', reasons: ['window_cutoff_not_supported'] }} onCapture={() => undefined} />)
      verify(unsupported.includes(cutoffs.map((day) => day.replace(/-/g, '/')).join('、')) && unsupported.includes('不沿用其他截止的數值'), 'unsupported cutoff uses the current scope')
      const overviewVersion = eighth ? 'stock-overview/w8-v1' : seventh ? 'stock-overview/w7-v1' : sixth ? 'stock-overview/w6-v1' : 'stock-overview/w5-v1'
      const whole = render(<StockOverview data={{ ...data, version: overviewVersion, as_of: cutoff, institutional: base }} onNews={() => undefined} />)
      verify(whole.includes(`總覽版本 ${overviewVersion}`) && !whole.includes('與 2026/09/30、2026/10/01、2026/10/02 截止'), 'overview scope does not retain a stale static list')
      if (eighth && cutoff === '2026-09-21') {
        verify(dates.length === 20 && windows['20'].from === '2026-08-25' && windows['5'].from === '2026-09-15', 'eighth cutoff has the independent twenty/five-day starts')
        verify(html.includes('TRACE-2026-08-25') && !html.includes('TRACE-2026-09-22') && partial.includes('缺日：2026-08-25'), 'new August source and missing day do not adopt later cutoff rows')
      }
      if (seventh && cutoff === '2026-09-22') {
        verify(dates.length === 20 && windows['20'].from === '2026-08-26' && windows['5'].from === '2026-09-16', 'seventh cutoff has the independent twenty/five-day starts')
        verify(html.includes('TRACE-2026-08-26') && !html.includes('TRACE-2026-09-23') && partial.includes('缺日：2026-08-26'), 'new August source and missing day do not adopt later cutoff rows')
      }
      if (sixth && cutoff === '2026-09-23') {
        verify(windows['20'].from === '2026-08-27' && windows['5'].from === '2026-09-17', 'sixth cutoff has exactly twenty sessions and the positive five-day start')
        verify(html.includes('TRACE-2026-08-27') && !html.includes('TRACE-2026-09-24') && partial.includes('缺日：2026-08-27'), 'new August source and local missing date do not adopt later cutoffs')
      }
      if (cutoff === '2026-09-24') {
        verify(windows['20'].from === '2026-08-28' && windows['5'].from === '2026-09-18', 'new cutoff has exactly twenty sessions and the positive five-day start')
        verify(html.includes('TRACE-2026-08-28') && !html.includes('TRACE-2026-09-29') && partial.includes('缺日：2026-08-28'), 'new August source and missing day are traceable without adopting later cutoffs')
      }
    }
  }
  return checks
}

export function runInstitutionalWindowEarlierCutoffSSRTests(render: (element: ReactElement) => string): number {
  return runInstitutionalWindowCutoffSSRTests(render, true)
}

export function runInstitutionalWindowFifthCutoffSSRTests(render: (element: ReactElement) => string): number {
  return runInstitutionalWindowCutoffSSRTests(render, true, true)
}

export function runInstitutionalWindowSixthCutoffSSRTests(render: (element: ReactElement) => string): number {
  return runInstitutionalWindowCutoffSSRTests(render, true, true, true)
}

export function runInstitutionalWindowSeventhCutoffSSRTests(render: (element: ReactElement) => string): number {
  return runInstitutionalWindowCutoffSSRTests(render, true, true, true, true)
}

export function runInstitutionalWindowEighthCutoffSSRTests(render: (element: ReactElement) => string): number {
  return runInstitutionalWindowCutoffSSRTests(render, true, true, true, true, true)
}

/** Rebuildable presentation fixtures; synthetic provenance is not source acceptance. */
export function createUnitLotsFixture(): StockOverviewData {
  const dates = ['2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11',
    '2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-21', '2026-09-22', '2026-09-23',
    '2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02']
  const windows = Object.fromEntries(([5, 20] as const).map((horizon) => {
    const selected = dates.slice(-horizon)
    return [String(horizon), { horizon, status: 'available', values: { foreign: horizon === 5 ? '1001' : '184467440737095516140', trust: '-1', dealer: '0' },
      from: selected[0], to: '2026-10-02', required_dates: selected, valid_dates: selected, missing_dates: [], invalid_dates: [], reasons: [],
      daily_evidence: [{ row: daily.row!, provenance: { source_id: 'synthetic-presentation-fixture', source_version: 'unit-lots-1', requested_date: '2026-10-02',
        url: 'https://data.gov.tw/dataset/11856', method: 'GET', body_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), body_bytes: 0,
        captured_at: '2026-10-05T00:00:00+00:00', request_started_at: '2026-10-05T00:00:00+00:00', policy_version: 'fixture', policy_digest: 'fixture', profile: 'free_public_local', historical_pit: 'unsupported' } }],
    }]
  })) as NonNullable<InstitutionalWindowsData['windows']>
  const price = { ...latest, date: '2026-10-02', volume: 9007199254740992, volume_exact: '9007199254740993' }
  return { ...data, version: 'unit-lots-1-presentation-fixture', as_of: '2026-10-02',
    price: { ...data.price, latest: price, bars: [price], from: price.date, to: price.date, candidate_count: 1, valid_count: 1, rejected: [], reasons: [] },
    institutional_daily: { ...daily, as_of: '2026-10-02', reasons: [], provenance: { ...daily.provenance!, source_version: 'synthetic-presentation-fixture' } },
    institutional: { version: 'unit-lots-1-fixture', status: 'available', as_of: '2026-10-02', horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], values: null, reasons: [],
      unit: 'shares', quantity_encoding: 'canonical_integer_string', historical_pit: 'unsupported', windows,
      supported_scope: { exchange: 'TPEx', symbols: ['3105'], supported_cutoffs: ['2026-10-02'], calendar_from: dates[0], calendar_to: dates[19] },
      calendar: { version: 'synthetic-presentation-fixture', status: 'available', expected_dates: dates, valid_dates: dates, missing_dates: [], evidence: [] },
      capture_state: { enabled: false, attempted: true, busy: false, can_capture: false, cache_present: true, action: 'cached', request_count: 0 },
    },
  }
}

export function runUnitLotsSSRTests(render: (element: ReactElement) => string): number {
  let checks = 0
  const verify = (condition: boolean, message: string) => { checks++; if (!condition) throw new Error(message) }
  const fixture = createUnitLotsFixture()
  const dailyData = fixture.institutional_daily!
  const windowData = fixture.institutional
  const main = (html: string) => html.split('<details')[0]
  const dailyHtml = render(<InstitutionalDaily data={dailyData} windowsPresent />)
  verify(main(dailyHtml).includes('單位：張') && main(dailyHtml).includes('法人買進、賣出與淨買賣超（張）'), 'daily primary unit/caption is lots')
  for (const value of ['10,547.941', '3,264.551', '7,283.39', '-27', '1,070.812', '86.707', '984.105', '8,240.495']) {
    verify(main(dailyHtml).includes(`>${value}</td>`), 'daily buy/sell/net/total retains exact fractional lots')
  }
  verify(dailyHtml.includes('來源稽核原值（股）') && dailyHtml.indexOf('>10,547,941</td>') > dailyHtml.indexOf('<details'), 'original daily shares are labelled and inside details')
  const zero = render(<InstitutionalDaily data={{ ...dailyData, row: { ...dailyData.row!, total_net: '0' } }} />)
  verify(main(zero).includes('>0</td>'), 'canonical zero remains a main numerical zero')
  for (const value of [null, '01', '-0', '+1', '1\n', '1.5', '1e3', '9223372036854775808']) {
    const html = render(<InstitutionalDaily data={{ ...dailyData, row: { ...dailyData.row!, total_net: value as string } }} />)
    verify(main(html).includes('待核對') && !main(html).includes('>8,240.495</td>'), 'invalid daily text never falls back')
  }
  const negativeGross = render(<InstitutionalDaily data={{ ...dailyData, row: { ...dailyData.row!, investors: { ...dailyData.row!.investors, foreign: investor('外資', '-22222', '0', '0') } } }} />)
  verify(main(negativeGross).includes('待核對') && !main(negativeGross).includes('-22.222'), 'negative gross is invalid')
  for (const changed of [
    { ...dailyData, unit: 'unknown' }, { ...dailyData, quantity_encoding: 'number' },
    { ...dailyData, row: { ...dailyData.row!, unit: 'mixed' } },
  ]) {
    const html = render(<InstitutionalDaily data={changed as InstitutionalDailyData} />)
    verify(!main(html).includes('10,547.941') && html.includes('單位待核實') && !html.includes('來源稽核原值（股）'), 'daily unknown unit/encoding cannot claim shares or lots')
  }
  const windowHtml = render(<InstitutionalWindows data={windowData} />)
  verify(main(windowHtml).includes('淨買賣超（張）') && main(windowHtml).includes('>1.001</td>') && main(windowHtml).includes('>-0.001</td>') && main(windowHtml).includes('>0</td>'), '5-day lots preserve positive/negative one-share remainder and zero')
  verify(main(windowHtml).includes('>184,467,440,737,095,516.14</td>'), '20-day boundary exceeds int64 and stays exact')
  verify(windowHtml.includes('窗口來源稽核原值（股）') && windowHtml.indexOf('>184,467,440,737,095,516,140</td>') > windowHtml.indexOf('<details'), 'original window shares stay in details')
  for (const [horizon, value, expected] of [[5, '46116860184273879035', '46,116,860,184,273,879.035'], [20, '-184467440737095516140', '-184,467,440,737,095,516.14']] as const) {
    const changed = { ...windowData, windows: { ...windowData.windows, [horizon]: { ...windowData.windows![horizon], values: { foreign: value, trust: '-1', dealer: '0' } } } }
    verify(main(render(<InstitutionalWindows data={changed} />)).includes(`>${expected}</td>`), 'each signed window uses its own maximum')
  }
  for (const value of [null, '01', '-0', '+1', '1\n', '184467440737095516141']) {
    const changed = { ...windowData, windows: { ...windowData.windows, '20': { ...windowData.windows!['20'], values: { foreign: value as string, trust: '-1', dealer: '0' } } } }
    const html = render(<InstitutionalWindows data={changed} />)
    verify(main(html).includes('數值或窗口條件待核對') && !main(html).includes('184,467,440,737,095,516.14'), 'invalid window hides that full horizon without fallback')
  }
  const twenty = windowData.windows!['20']
  for (const changed of [
    { ...windowData, unit: 'mixed' }, { ...windowData, quantity_encoding: 'number' },
    { ...windowData, horizons: [5] }, { ...windowData, as_of: '2026-10-03' },
    { ...windowData, windows: { ...windowData.windows, '20': { ...twenty, horizon: 5 } } },
    { ...windowData, windows: { ...windowData.windows, '20': { ...twenty, valid_dates: twenty.valid_dates.slice(1), missing_dates: [twenty.from!] } } },
    { ...windowData, windows: { ...windowData.windows, '20': { ...twenty, to: '2026-10-03' } } },
  ]) verify(!main(render(<InstitutionalWindows data={changed} />)).includes('184,467,440,737,095,516.14'), 'unit, horizon, completeness and cutoff gates remain required')
  const priceHtml = render(<StockOverview data={fixture} onNews={() => undefined} />)
  verify(priceHtml.includes('<strong>9,007,199,254,740.993</strong>') && priceHtml.includes('<td>9,007,199,254,740,993</td>') && priceHtml.includes('25.55'), 'volume main lots, original shares and original price stay separate')
  verify(formatWindowShares('184467440737095516140') === null && formatWindowShares('184467440737095516140', 20) !== null && formatCanonicalShareLots('1') === '0.001', 'audit formatter is bounded by its named horizon')
  return checks
}
