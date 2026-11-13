import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { ActionDetailPanel, ResearchGapLine } from '../App'
import { actionNote, actionStateLabel, hiddenSentence } from '../actions/actionTiers'
import { GLOSSARY } from '../glossary'
import { productActionReasonLabel, productQualityLabel } from '../presentation'
import { action } from '../today/today.fixtures'
import type { ActionTierSummary, GapReason, StrategyBoardRow } from '../types'
import { board, incompleteRow, notApplicableRow } from './strategyBoard.fixtures'
import { StockSummaryCard } from './StockSummaryCard'
import { unmetText } from './strategyBoard'

// Issue 524 (UI_COPY_SPEC §5, §6.1, §9, §10.1): a data_insufficient stock is worded by what is short. Only a gap we did
// not collect and can backfill says 「待回補」; an official table without the stock says so, an excluded ETF category is
// 「不適用」, anything else is 「資料不足」. Every check runs and the failures are listed together.
const failures: string[] = []
const check = (condition: boolean, message: string) => { if (!condition) failures.push(message) }
const text = (markup: string) => markup.replace(/<[^>]+>/g, '')

const INSTITUTIONAL = { code: 'institutional_not_listed', label: '近 5 個交易日有 1 天官方三大法人表未列此股（官方只列當天有法人買賣的股票）' }
const NO_TRADE = { code: 'official_no_trade', label: '近 60 個交易日有 3 天官方行情無成交' }
const ETF = { code: 'etf_not_general_action_eligible', label: '債券、槓桿或反向 ETF 不適用一般突破／回踩研究條件' }

const insufficient = (gap_reasons?: GapReason[], extra = {}) => action('1240', '茂生農經', 'data_insufficient', {
  tier: 5, display_action: '策略判斷資料待補', data_gap: '60 日基準還缺 3 個有效交易日，尚不能計算進場、失效與目標價。',
  primary_reason: gap_reasons?.length ? { label: gap_reasons[0].label, scope: 'research' } : undefined, gap_reasons, ...extra,
})

// A1／A6: the state name, by the summary's causes.
check(actionStateLabel(insufficient([NO_TRADE, INSTITUTIONAL])) === '資料不足，無法判斷', 'A1 list badge: ' + actionStateLabel(insufficient([NO_TRADE])))
check(actionStateLabel(insufficient(undefined)) === '資料不足，無法判斷', 'A1 list badge without causes')
check(actionStateLabel(insufficient([ETF])) === '不適用一般研究條件', 'A6 list badge of an excluded ETF: ' + actionStateLabel(insufficient([ETF])))
check(actionStateLabel(insufficient([ETF, NO_TRADE])) === '資料不足，無法判斷', 'A6 only when the ETF category is the one cause')

// A2: the research quality badge pairs with 策略判斷資料完整.
check(productQualityLabel('partial', 'research') === '策略判斷資料不足', 'A2 research badge: ' + productQualityLabel('partial', 'research'))
check(productQualityLabel('complete', 'research') === '策略判斷資料完整', 'A2 complete badge unchanged')

// A4: the hidden-rows line.
const summary = { view: 'focus', include_etf: false, hidden: { etf: 2, observation: 0, data_insufficient: 3 } } as unknown as ActionTierSummary
check(hiddenSentence(summary) === '預設隱藏：ETF 2 檔、資料不足 3 檔', 'A4 hidden line (its note moved to 說明, Issue 649): ' + hiddenSentence(summary))

// B1: the list's note is the primary reason when the summary has causes, else the data-gap sentence.
check(actionNote(insufficient([NO_TRADE, INSTITUTIONAL])) === NO_TRADE.label, 'B1 note is the primary reason: ' + actionNote(insufficient([NO_TRADE])))
check(actionNote(insufficient(undefined)) === '60 日基準還缺 3 個有效交易日，尚不能計算進場、失效與目標價。', 'B1 note without causes keeps data_gap')

// The stock page's research action card: title and badge.
const panel = text(renderToStaticMarkup(<ActionDetailPanel action={insufficient([NO_TRADE, INSTITUTIONAL], { data_quality: 'partial' })} gap={{ reasons: [NO_TRADE, INSTITUTIONAL], missingFields: ['bars_60d'] }} />))
check(panel.includes('資料不足，無法判斷') && !panel.includes('待補'), 'A1 research card: ' + panel)
check(panel.includes('策略判斷資料不足'), 'A2 research card badge: ' + panel)
const etfPanel = text(renderToStaticMarkup(<ActionDetailPanel action={insufficient([ETF], { data_quality: 'partial' })} gap={{ reasons: [ETF], missingFields: [] }} />))
check(etfPanel.includes('不適用一般研究條件') && etfPanel.includes('策略判斷不適用') && !etfPanel.includes('待補'), 'A6 research card: ' + etfPanel)

// C: 差哪個條件 of an incomplete row takes the summary's sentence of the same topic.
const institutionalRow: StrategyBoardRow = { ...incompleteRow(), missing: ['institutional_flow_to_turnover_ratio_5d_missing_or_non_finite'], missing_labels: ['近 5 日法人籌碼資料待補'] }
check(unmetText(institutionalRow, [NO_TRADE, INSTITUTIONAL]) === `無法判斷：${INSTITUTIONAL.label}`, 'C institutional: ' + unmetText(institutionalRow, [NO_TRADE, INSTITUTIONAL]))
const margin = { code: 'margin_zero_base', label: '5 個交易日前融資餘額為 0，無法計算融資變化率' }
check(unmetText(incompleteRow(), [NO_TRADE, margin]) === `無法判斷：${margin.label}`, 'C margin: ' + unmetText(incompleteRow(), [NO_TRADE, margin]))
const barsRow: StrategyBoardRow = { ...incompleteRow(), missing: ['history_under_60_bars', 'ma60_missing_or_non_finite'], missing_labels: ['近 60 個交易日行情不足', '60 日均線資料待補'] }
check(unmetText(barsRow, [NO_TRADE, INSTITUTIONAL]) === `無法判斷：${NO_TRADE.label}`, 'C bars, each sentence once: ' + unmetText(barsRow, [NO_TRADE, INSTITUTIONAL]))
const group = { code: 'group_return_unavailable', label: '未歸屬任何有效族群，無法計算族群相對加權指數的 20 日報酬' }
const groupRow: StrategyBoardRow = { ...incompleteRow(), missing: ['group_excess_return_20d_missing_or_non_finite'], missing_labels: ['近 20 日相對大盤資料待補'] }
check(unmetText(groupRow, [group]) === `無法判斷：${group.label}`, 'C group: ' + unmetText(groupRow, [group]))
const listed = { code: 'listed_under_threshold', label: '上市（櫃）後只有 12 個交易日，未滿 60 個交易日' }
check(unmetText(institutionalRow, [listed]) === `無法判斷：${listed.label}`, 'C a short listing explains the chip inputs: ' + unmetText(institutionalRow, [listed]))
const uncollected = { code: 'institutional_not_collected', label: '近 5 個交易日有 1 天法人資料尚未收錄（待回補）' }
check(unmetText(institutionalRow, [uncollected]) === `無法判斷：${uncollected.label}`, 'C not collected: ' + unmetText(institutionalRow, [uncollected]))
// No sentence of the topic (an older response or another date): the code's own label, never 待補.
const fallback = unmetText({ ...institutionalRow, missing_labels: ['近 5 日法人籌碼資料不足'] }, undefined)
check(fallback === '無法判斷：近 5 日法人籌碼資料不足', 'C fallback: ' + fallback)
const unlabeled = unmetText({ ...institutionalRow, missing_labels: [] }, [NO_TRADE])
check(unlabeled.startsWith('無法判斷：') && !unlabeled.includes('待補') && !unlabeled.includes(NO_TRADE.label), 'C fallback without labels: ' + unlabeled)
check(unmetText(notApplicableRow(), [ETF]) === ETF.label, 'C not applicable row unchanged: ' + unmetText(notApplicableRow(), [ETF]))


// The summary card's closest strategy: an incomplete row's line already says why, with no 差： in front.
const card = text(renderToStaticMarkup(<StaticRouter location="/stocks/TPEx/1240"><StockSummaryCard board={board([institutionalRow])} action={insufficient([NO_TRADE, INSTITUTIONAL])} researchHref="?tab=research" /></StaticRouter>))
check(card.includes(`無法判斷：${INSTITUTIONAL.label}`) && !card.includes('差：無法判斷'), 'C summary card: ' + card)
// D: no reason label says 待補.
const codes = ['data_incomplete', 'prior_20_highs_missing_or_invalid', 'prior_20_volumes_missing_or_invalid', 'close_missing_or_non_finite',
  'volume_missing_or_non_finite', 'ma20_missing_or_non_finite', 'ma60_missing_or_non_finite', 'group=missing',
  'missing=institutional_flow_5d', 'breakout=data_incomplete:ma60_missing_or_non_finite']
for (const code of codes) check(!productActionReasonLabel(code).includes('待補'), `D ${code}: ${productActionReasonLabel(code)}`)
check(productActionReasonLabel('data_incomplete') === '此研究條件資料不足', 'D1: ' + productActionReasonLabel('data_incomplete'))
check(productActionReasonLabel('missing=institutional_flow_5d') === '缺少資料：缺少 5 日法人籌碼', 'D3 missing=: ' + productActionReasonLabel('missing=institutional_flow_5d'))
const older = text(renderToStaticMarkup(<ResearchGapLine reasons={undefined} missingFields={['bars_60d', 'no_such_field']} />))
check(older.includes('研究資料不足：60 日行情、其他研究資料。'), 'D3 older response: ' + older)

// E: the group event gap keeps its name (our own collection gap) and says why.
const pending = GLOSSARY.find((term) => term.term_id === 'event_data_pending')
check(pending?.name === '事件資料待補', 'E keeps 事件資料待補')
check(Boolean(pending?.limitations.includes('回補')), 'E says it can be backfilled: ' + pending?.limitations)

if (failures.length) throw new Error(`gap wording: ${failures.length} failures\n- ${failures.join('\n- ')}`)
