import { renderToStaticMarkup } from 'react-dom/server'
import { InstitutionalDaily, StockOverview, overviewReason } from './StockOverview'
import type { InstitutionalDailyData, StockOverviewData } from '../types'

function expect(condition: boolean, message: string): void {
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
  events: { status: 'unavailable', reasons: ['event_capture_consumer_not_verified', 'event_source_time_not_verified'] }, limitations: [],
}
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
const dailyHtml = renderToStaticMarkup(<StockOverview data={{ ...data, as_of: '2026-10-03', institutional_daily: daily }} onNews={() => {}} />)
expect(dailyHtml.includes('單日法人原件') && dailyHtml.includes('穩懋（3105）') && dailyHtml.includes('單位：股'), 'selected original has its own named block, company and exact share unit')
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
console.log('StockOverview price/daily display checks passed')
