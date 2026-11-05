import { Link } from 'react-router-dom'

import { Term } from '../components/Term'
import { Card } from '../components/ui'

// 策略說明 (/strategy, #493; PRODUCT_SPEC §2, UI_COPY_SPEC §13): how the 今日可買 list is made, the two strategy types,
// how to follow a row, what 觀察中 does and what the product does not do. Static copy; the formulas live in
// docs/spec/breakout_pullback.md and docs/spec/candidate_score.md, the terms in the glossary.

const STEPS: ReadonlyArray<{ title: string; text: string }> = [
  { title: '1. 收盤後掃描全市場', text: '每個交易日收盤後，系統對全部上市、上櫃普通股跑兩種固定規則：突破型與回踩型。' },
  { title: '2. 條件全部成立才入選', text: '價格、量能、族群、法人與融資的條件都要成立；任何一項資料不足，就不列入，不會拿 0 補。ETF 不列入。' },
  { title: '3. 依評分排序', text: '入選的股票依技術、籌碼、族群、新聞情緒四項評分排序，最多列 20 檔。評分只決定先後，不代表勝率或預期報酬。' },
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
    rule: '中期趨勢向上（20 日均線在 60 日均線之上），股價拉回到 20 日均線附近（約 −3%～+2%），而且量縮（前 20 日均量的 0.6～1.2 倍）。',
    fits: '等拉回：趨勢向上的股票回到支撐區、賣壓變小時。',
    risk: '趨勢轉弱：拉回沒有止住，一路跌破支撐。',
  },
]

export function StrategyPage() {
  return (
    <div className="page strategy-page">
      <section className="page-title">
        <div className="eyebrow">名單怎麼來、怎麼用</div>
        <h1>策略說明</h1>
        <p>「今日可買」不是推薦，而是固定規則篩出來、條件已經成立的研究名單；照著做之前，先看懂它怎麼選、什麼時候算失效。</p>
      </section>

      <section className="strategy-section" aria-labelledby="strategy-list-title">
        <h2 id="strategy-list-title">今日可買怎麼來</h2>
        <div className="strategy-grid strategy-grid-3">
          {STEPS.map((step) => <Card key={step.title} as="article" title={step.title}><p>{step.text}</p></Card>)}
        </div>
        <p className="small-note">評分的四個分項與權重見 <Term id="candidate_score">候選總分</Term>；每檔的完整條件在個股頁「研究條件」分頁。</p>
      </section>

      <section className="strategy-section" aria-labelledby="strategy-types-title">
        <h2 id="strategy-types-title">突破型與回踩型</h2>
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
        <p className="small-note">兩種都另外要求：所屬族群近 20 日跑贏加權指數、三大法人 5 日沒有明顯賣超、融資 5 日增加不超過 5%。</p>
      </section>

      <section className="strategy-section" aria-labelledby="strategy-follow-title">
        <h2 id="strategy-follow-title">怎麼照著做</h2>
        <Card as="article">
          <ol className="strategy-steps">
            <li><b><Term id="t_plus_1">T+1</Term> 才進場</b>：名單是收盤後算出來的，最早下一個交易日才能照著做。</li>
            <li><b><Term id="entry_zone">進場區</Term></b>：突破型是一個價位（在它附近進場），回踩型是一段區間（在區間內進場）；開盤就跳過目標或跌破停損時，這筆不進場。</li>
            <li><b><Term id="support">停損</Term></b>：跌破就代表條件失效，出場，不要攤平。</li>
            <li><b><Term id="target">目標</Term></b>：目標一較近，是主要的獲利出場價；目標二較遠，是延伸參考。</li>
            <li><b><Term id="rr">RR</Term></b>：可能賺的空間是可能賠的幾倍；規則要求至少 1.5 倍才列入。</li>
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
