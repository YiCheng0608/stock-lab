import { Link } from 'react-router-dom'

import { Term } from '../components/Term'
import { Card, DataTable } from '../components/ui'
import type { Column } from '../components/ui'
import { STRATEGY_NAME, STRATEGY_TERM_ID } from './strategyName'
import { CONFIRMATIONS, SCORE_COMPONENTS } from './trendChips'
import type { ConfirmationRow, ScoreRow } from './trendChips'

// 策略說明 (/strategy, #493, #577; PRODUCT_SPEC §2, UI_COPY_SPEC §13): the rules behind the 今日名單 list, by name: the two
// entry rules, the confirmation thresholds and the score weights. Issue 729 (decision 6881593041, plan 甲): the page holds
// the rules only; how to read the list, research findings and what the product does not do stay in the Issues. Static
// copy; the numbers are in ./trendChips.ts, the formulas in docs/spec/breakout_pullback.md and docs/spec/candidate_score.md,
// the terms in the glossary. A strategy is one <section data-strategy> titled by its name, so another strategy is another
// section beside it, not a change to this one.

const TYPES: ReadonlyArray<{ id: 'breakout' | 'pullback'; title: string; rule: string }> = [
  {
    id: 'breakout', title: '突破型',
    rule: '收盤站上前 20 個交易日的最高價，而且當天成交量至少是前 20 日均量的 1.2 倍。',
  },
  {
    id: 'pullback', title: '回踩型',
    rule: '中期趨勢向上（20 日均線在 60 日均線之上，收盤在 60 日均線以上），股價拉回到 20 日均線附近（約 −3%～+2%），而且量縮（前 20 日均量的 0.6～1.2 倍）。',
  },
]

// The two tables use `action-table` on the table (cell padding for wrapped text, row lines kept) and the default
// `table-wrap` around it. Not `strategy-table-wrap`: styles.css hides that wrap on phones, where the strategy board has cards.
const CONFIRMATION_COLUMNS: ReadonlyArray<Column<ConfirmationRow>> = [
  { key: 'name', header: '確認條件', cell: (row) => <b>{row.name}</b> },
  { key: 'threshold', header: '門檻', wrap: true, cell: (row) => row.threshold },
  { key: 'meaning', header: '白話', wrap: true, cell: (row) => row.meaning },
]

const SCORE_COLUMNS: ReadonlyArray<Column<ScoreRow>> = [
  { key: 'name', header: '分項', cell: (row) => <b>{row.name}{row.inference && '（推論）'}</b> },
  { key: 'weight', header: '權重', num: true, cell: (row) => `${row.weight}%` },
  { key: 'looks', header: '看什麼', wrap: true, cell: (row) => row.looks },
]

export function StrategyPage() {
  return (
    <div className="page strategy-page">
      <section className="page-title">
        <div className="eyebrow">目前策略：{STRATEGY_NAME}</div>
        <h1>策略說明</h1>
      </section>

      <section className="strategy-section" data-strategy={STRATEGY_TERM_ID} aria-labelledby="strategy-current-title">
        <h2 id="strategy-current-title"><Term id={STRATEGY_TERM_ID}>{STRATEGY_NAME}</Term></h2>

        <h3>兩條成立規則：突破型與回踩型</h3>
        <div className="strategy-grid strategy-grid-2">
          {TYPES.map((type) => (
            <Card key={type.id} as="article" title={<Term id={type.id}>{type.title}</Term>}>
              <dl className="strategy-facts">
                <div><dt>成立條件</dt><dd>{type.rule}</dd></div>
              </dl>
            </Card>
          ))}
        </div>

        <h3>三個確認條件：兩條規則都要通過</h3>
        <p>突破型與回踩型都要同時通過下面三個條件；任何一項資料不足就不列入，不會拿 0 補。</p>
        <DataTable columns={CONFIRMATION_COLUMNS} rows={CONFIRMATIONS} rowKey={(row) => row.key} className="action-table" />

        <h3>依評分排序：四個分項與權重</h3>
        <p>入選的股票依下面四個分項的加權總分（0–100）由高到低排；總分只決定先後。</p>
        <DataTable columns={SCORE_COLUMNS} rows={SCORE_COMPONENTS} rowKey={(row) => row.key} className="action-table" />
        <p className="small-note">沒有資料的分項不以 0 計，改用有資料的分項重新加權；技術分項必須有資料，有資料的分項權重合計要達 65%，否則不列入。各子項怎麼換成 0–100 見 <Term id="candidate_score">候選總分</Term>與<Term id="percentile">百分位</Term>；每檔的完整條件在個股頁「研究條件」分頁。</p>
      </section>

      <p className="small-note">規則版本與設定快照見 <Link className="text-link" to="/research/strategies">策略版本</Link>，用語見 <Link className="text-link" to="/glossary">用語表</Link>。</p>
    </div>
  )
}
