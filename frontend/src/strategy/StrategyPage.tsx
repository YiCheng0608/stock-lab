import { Link } from 'react-router-dom'

import { Term } from '../components/Term'
import { Card, DataTable } from '../components/ui'
import type { Column } from '../components/ui'
import { STRATEGY_NAME, STRATEGY_TERM_ID } from './strategyName'
import { COMPOSITION, CONFIRMATIONS, SCORE_COMPONENTS } from './trendChips'
import type { ConfirmationRow, ScoreRow } from './trendChips'

// 策略說明 (/strategy, #493, #577; PRODUCT_SPEC §2, UI_COPY_SPEC §13): the strategy behind the 今日可買 list, by name, with the
// thresholds and score weights it uses, then how to follow a row, what 觀察中 does and what the product does not do. Static
// copy; the numbers are in ./trendChips.ts, the formulas in docs/spec/breakout_pullback.md and docs/spec/candidate_score.md,
// the terms in the glossary. A strategy is one <section data-strategy> titled by its name, so another strategy is another
// section beside it, not a change to this one.

const STEPS: ReadonlyArray<{ title: string; text: string }> = [
  { title: '1. 收盤後掃描全市場', text: '每個交易日收盤後，系統對全部上市、上櫃普通股跑兩種固定規則：突破型與回踩型。' },
  { title: '2. 條件全部成立才入選', text: '價格、量能、族群、法人與融資的條件都要成立；任何一項資料不足，就不列入，不會拿 0 補。另外 20 日平均成交量至少 1,000 張；成交量太少，或均量資料不足的股票不列入。ETF 不列入。' },
  { title: '3. 依評分排序', text: '入選的股票依技術、籌碼、族群、新聞情緒四項評分的加權總分排序（權重見下方「依評分排序」），最多列 20 檔。評分只決定先後，不代表勝率或預期報酬。' },
]

const TYPES: ReadonlyArray<{ id: 'breakout' | 'pullback'; title: string; rule: string; fits: string; risk: string }> = [
  {
    id: 'breakout', title: '突破型',
    rule: '收盤站上前 20 個交易日的最高價，而且當天成交量至少是前 20 日均量的 1.2 倍。',
    fits: '追強勢：股價剛創近期新高、買盤放量時。',
    risk: '假突破：突破後很快跌回原本的區間。',
  },
  {
    id: 'pullback', title: '回踩型',
    rule: '中期趨勢向上（20 日均線在 60 日均線之上，收盤在 60 日均線以上），股價拉回到 20 日均線附近（約 −3%～+2%），而且量縮（前 20 日均量的 0.6～1.2 倍）。',
    fits: '等拉回：趨勢向上的股票回到支撐區、賣壓變小時。',
    risk: '趨勢轉弱：拉回沒有止住，一路跌破支撐。',
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
        <p>「今日可買」不是推薦，而是固定規則篩出來、條件已經成立的研究名單；照著做之前，先看懂它怎麼選、什麼時候算失效。</p>
      </section>

      <section className="strategy-section" data-strategy={STRATEGY_TERM_ID} aria-labelledby="strategy-current-title">
        <h2 id="strategy-current-title"><Term id={STRATEGY_TERM_ID}>{STRATEGY_NAME}</Term></h2>
        <p>目前「今日可買」用的是{STRATEGY_NAME}：只做多頭趨勢的股票，除了價量條件成立，還要所屬族群比大盤強、三大法人沒有明顯賣超、融資沒有過熱；大盤好壞目前不影響判斷。它由兩條規則——突破型（<code>{COMPOSITION.breakout}</code>）與回踩型（<code>{COMPOSITION.pullback}</code>）——和一個評分——<Term id="candidate_score">候選總分</Term>（<code>{COMPOSITION.score}</code>）組成。</p>

        <h3>今日可買怎麼來</h3>
        <div className="strategy-grid strategy-grid-3">
          {STEPS.map((step) => <Card key={step.title} as="article" title={step.title}><p>{step.text}</p></Card>)}
        </div>

        <h3>兩條成立規則：突破型與回踩型</h3>
        <div className="strategy-grid strategy-grid-2">
          {TYPES.map((type) => (
            <Card key={type.id} as="article" title={<Term id={type.id}>{type.title}</Term>}>
              <dl className="strategy-facts">
                <div><dt>成立條件</dt><dd>{type.rule}</dd></div>
                <div><dt>適合</dt><dd>{type.fits}</dd></div>
                <div><dt>主要風險</dt><dd>{type.risk}</dd></div>
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

      <section className="strategy-section" aria-labelledby="strategy-follow-title">
        <h2 id="strategy-follow-title">怎麼照著做</h2>
        <Card as="article">
          <ol className="strategy-steps">
            <li><b><Term id="t_plus_1">T+1</Term> 才進場</b>：名單是收盤後算出來的，最早下一個交易日才能照著做。</li>
            <li><b><Term id="entry_zone">進場區</Term></b>：突破型是一個價位（在它附近進場），回踩型是一段區間（在區間內進場）；開盤就跳過目標或跌破停損時，這筆不進場。</li>
            <li><b><Term id="support">停損</Term></b>：跌破就代表條件失效，出場，不要攤平。</li>
            <li><b><Term id="target">目標</Term></b>：目標一較近，是主要的獲利出場價；目標二較遠，是延伸參考。</li>
            <li><b><Term id="rr">RR</Term></b>：可能賺的空間是可能賠的幾倍（目標一減進場價，除以進場價減停損；回踩型的進場價取進場區中點）；規則要求至少 1.5 倍才列入。</li>
          </ol>
        </Card>
      </section>

      <section className="strategy-section" aria-labelledby="strategy-watch-title">
        <h2 id="strategy-watch-title">觀察中在做什麼</h2>
        <Card as="article">
          <p>在「今日可買」或個股頁按「加入追蹤」，系統會從下一個交易日起、每天收盤後依日線模擬這筆的進場與出場（最多 20 個交易日），結果放在 <Link className="text-link" to="/watch">觀察中</Link> 的「追蹤計畫」與「追蹤回看」。模擬已扣固定的手續費與滑價假設，不是實際成交，也不寫進你的庫存。</p>
          <p>「觀察中」也會提醒你庫存的風險，並列出差一點就成立的股票。</p>
        </Card>
      </section>

      <section className="strategy-section" aria-labelledby="strategy-limits-title">
        <h2 id="strategy-limits-title">不做的事</h2>
        <Card as="article">
          <ul className="strategy-steps">
            <li>不自動下單，也不提供盤中即時價格；所有判斷都是盤後、以日線計算。</li>
            <li>不顯示勝率或成立機率：目前沒有經過驗證的統計可以支持這種數字。</li>
            <li>AI 只寫說明文字，畫面上都標「AI 推論」；價位一律以規則算出的數字為準。</li>
          </ul>
          <p className="small-note">規則版本與設定快照見 <Link className="text-link" to="/research/strategies">策略版本</Link>，用語見 <Link className="text-link" to="/glossary">用語表</Link>。</p>
        </Card>
      </section>
    </div>
  )
}
