import { renderToStaticMarkup } from 'react-dom/server'

import { ResearchGapLine, stockCoverageReasonLabels } from '../App'

// Standalone regression module (no browser, no server, no network): the stock page's research tab says why the
// strategy judgement is short of data (Issue 511, UI_COPY_SPEC §6.1), and no field code falls back to 「待補資料」.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }

// Every code build_decision_summary can put in blocking_reasons (backend/app/decision.py).
const BLOCKING_CODES = [
  'data_as_of', 'market_bar', 'market_bar_read_invalid', 'taiex_session_baseline', 'bars_20d', 'bars_60d', 'signal',
  'institutional_flow_5d', 'foreign_buy', 'trust_buy', 'dealer_buy', 'margin_balance', 'margin_change',
  'theme_membership', 'qualified_theme', 'benchmark', 'signal_data_quality', 'data_incomplete', 'invalid_levels',
  'trigger_price', 'entry_low', 'entry_high', 'invalid_price', 'target_1', 'target_2', 'risk_reward', 'data_cutoff',
  'group_excess_return_20d', 'institutional_flow_to_turnover_ratio_5d', 'margin_balance_change_ratio_5d', 'ohlcv',
]

const reasons = [
  { code: 'official_no_trade', label: '近 60 個交易日有 3 天官方行情無成交' },
  { code: 'institutional_not_listed', label: '近 5 個交易日有 1 天官方三大法人表未列此股（官方只列當天有法人買賣的股票）' },
]
const html = renderToStaticMarkup(<ResearchGapLine reasons={reasons} missingFields={['bars_60d', 'data_incomplete']} />)
check(html.includes('目前不能判斷的原因：近 60 個交易日有 3 天官方行情無成交；近 5 個交易日有 1 天官方三大法人表未列此股（官方只列當天有法人買賣的股票）。'), 'the causes are the line, joined by 「；」')
check(html.includes('<summary>查看缺少的欄位</summary><div>60 日行情、策略訊號資料不完整</div>'), 'the exact fields stay one click away')
check(!html.includes('研究資料待補'), 'a line with causes does not say 研究資料待補')

// An older response (no gap_reasons) keeps the field list.
const older = renderToStaticMarkup(<ResearchGapLine reasons={undefined} missingFields={['bars_60d']} />)
check(older.includes('研究資料待補：60 日行情。'), 'no causes: the field list as before')

// No blocking code is unknown to the field table.
const every = renderToStaticMarkup(<ResearchGapLine reasons={undefined} missingFields={BLOCKING_CODES} />)
check(!every.includes('待補資料'), 'every blocking code has a field label: ' + every)

// The stock page's coverage panel counts a no-trade day as one of the 60 sessions still missing, so its label must
// not call the day 「不算缺資料」 (review of PR 514); the market coverage page keeps its own label.
check(!stockCoverageReasonLabels.official_no_trade.includes('不算缺資料'), 'stock coverage: a no-trade day is still a missing session')
check(stockCoverageReasonLabels.bar_invalid === '已收到行情但數值不完整', 'stock coverage: an unusable stored bar has its own label')
check(stockCoverageReasonLabels.quote_not_listed === '官方行情表當日未列此股', 'stock coverage keeps the shared labels')
