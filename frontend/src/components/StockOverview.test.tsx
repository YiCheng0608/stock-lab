import { renderToStaticMarkup } from 'react-dom/server'
import { StockOverview, overviewReason } from './StockOverview'
import type { StockOverviewData } from '../types'

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
console.log('StockOverview display checks passed')
