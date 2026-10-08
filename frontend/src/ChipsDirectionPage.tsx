import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { DIRECTION_API, DIRECTION_CATEGORIES, DIRECTION_INVESTORS, DIRECTION_NAMES, DIRECTION_SYMBOLS, directionControls, directionPath, validDirectionControls, validateDirection } from './chipsDirection'
import type { DirectionCategory, DirectionControls, DirectionInvestor, DirectionPoint, DirectionRead, DirectionSign, DirectionStats, DirectionWindow } from './chipsDirection'
import './ChipsSeriesPage.css'

type Held = { read: DirectionRead | null; busy: boolean; firstUsed: boolean; status: string; mask: () => void; action: (capture: boolean, controls: DirectionControls) => Promise<void> }
const DirectionContext = createContext<Held | null>(null)
export function ChipsDirectionProvider({ children }: { children: ReactNode }) {
  const [read, setRead] = useState<DirectionRead | null>(null), [busy, setBusy] = useState(false), [firstUsed, setFirstUsed] = useState(false)
  const [status, setStatus] = useState('尚未取得來源。方向、正負零計數與連續區段均未驗證。')
  const pending = useRef(false), firstLatch = useRef(false), epoch = useRef(0)
  function mask() { epoch.current++; setRead(null); setStatus('原始條件未准入，所有資料不可用。套用有效條件後，請明確讀取已持有來源。') }
  async function action(capture: boolean, controls: DirectionControls) {
    if (pending.current || !validDirectionControls(controls) || capture && firstLatch.current) return
    pending.current = true
    const token = ++epoch.current
    setBusy(true); setRead(null)
    if (capture) { firstLatch.current = true; setFirstUsed(true) }
    try {
      const response = await fetch(DIRECTION_API + (capture ? '/capture' : '') + '?' + new URLSearchParams({ as_of: controls.as_of }), capture ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' } : { method: 'GET' })
      if (!response.ok) throw new Error('HTTP ' + response.status)
      const checked = await validateDirection(await response.json())
      if (!checked) throw new Error('完整來源或方向證據未通過驗證')
      if (token !== epoch.current) return
      setRead(checked); setStatus('七股每日三法人方向與所有 5／20 日正負零計數、連續區段已完整驗證。')
    } catch (error) {
      if (token !== epoch.current) return
      setRead(null); setStatus('資料不可用：' + (error instanceof Error ? error.message : '讀取失敗') + '。套用條件或返回不會恢復舊值；請明確重新讀取。')
    } finally { pending.current = false; setBusy(false) }
  }
  return <DirectionContext.Provider value={{ read, busy, firstUsed, status, mask, action }}>{children}</DirectionContext.Provider>
}
export const directionInvestorLabels: Record<DirectionInvestor, string> = { foreign: '外資及陸資（不含外資自營商）', trust: '投信', dealer: '自營商' }
export const directionSignLabels: Record<DirectionSign, string> = { positive: '正淨超', negative: '負淨超', zero: '零淨超' }
export const directionCategoryLabels: Record<DirectionCategory, string> = { all_positive: '三法人全正', all_negative: '三法人全負', opposite: '正負分歧（可含零）', single_direction_with_zero: '單向含零', all_zero: '三法人全零' }
const signed = (s: string) => s !== '0' && !s.startsWith('-') ? '+' + s : s
const attribution = "財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；方向與區段為本地衍生結果。"

export function DirectionSummary({ stats }: { stats: DirectionStats }) {
  const latest = stats.latest_run
  return <div data-direction-counts>
    <p>正淨超 <strong data-direction-count="positive">{stats.counts.positive}</strong> 日 · 負淨超 <strong data-direction-count="negative">{stats.counts.negative}</strong> 日 · 零淨超 <strong data-direction-count="zero">{stats.counts.zero}</strong> 日</p>
    <p>窗口內最新區段：{directionSignLabels[latest.sign]} {latest.length} 日，{latest.start_date} 至 {latest.end_date}。{latest.earlier_unknown ? '區段從窗口起點截斷，之前是否延續未知。' : '區段起點位於此窗口內。'}{latest.sign === 'zero' && ' 零淨超已中斷正／負連續區段。'}</p>
    <p>所有長度只計所選窗口內的已驗證交易日，不代表完整歷史持續時間。</p>
  </div>
}

export function DirectionSegments({ window, investor, onPoint }: { window: DirectionWindow; investor: DirectionInvestor; onPoint: (point: DirectionPoint) => void }) {
  const [expanded, setExpanded] = useState<number | null>(null)
  useEffect(() => setExpanded(null), [window, investor])
  const stats = window.investors[investor]
  const expandedSegment = expanded === null ? null : stats.segments[expanded]
  return <section aria-label="完整連續區段" data-direction-investor={investor} data-direction-horizon={window.horizon}>
    <h2>連續區段</h2><p>相鄰同方向合為一段；零獨立成段，打斷正／負區段。點選區段，再選日期查看原始列。</p>
    <div className="series-table-wrap"><table aria-label="連續區段日期與長度"><thead><tr><th>方向</th><th>起日</th><th>末日</th><th>窗口內日數</th><th>起點限制與操作</th></tr></thead><tbody>{stats.segments.map((segment, index) => <tr key={segment.start_date} data-direction-segment={index}>
      <td>{directionSignLabels[segment.sign]}</td><td>{segment.start_date}</td><td>{segment.end_date}</td><td>{segment.length}</td><td>{segment.earlier_unknown && <span>窗口起點截斷；之前未知。 </span>}<button type="button" data-direction-segment-button={index} aria-expanded={expanded === index} aria-label={segment.start_date + ' 至 ' + segment.end_date + ' 展開區段日期'} onClick={() => setExpanded(expanded === index ? null : index)}>展開區段日期</button></td>
    </tr>)}</tbody></table></div>
    {expandedSegment && <div className="series-actions" aria-label="所選區段日期">{window.points.slice(expandedSegment.start_index, expandedSegment.end_index + 1).map((point) => <button type="button" key={point.date} data-direction-segment-date={point.date} aria-label={point.date + ' 查看三法人原始列'} onClick={() => onPoint(point)}>{point.date} · 查看原始列 #{point.row_ordinal}</button>)}</div>}
  </section>
}

export function DirectionEvidence({ point, read }: { point: DirectionPoint; read: DirectionRead }) {
  const receipt = read.receipts.find((r) => r.sha256 === point.receipt_sha256)
  return <section className="series-evidence" aria-label="三法人原始列追溯" data-direction-evidence-date={point.date}>
    <h2>{point.date} 原始列 #{point.row_ordinal}</h2><p>{directionCategoryLabels[point.category]}。每個符號取自該日原始淨超，不以缺列或未知補零。</p>
    {DIRECTION_INVESTORS.map((investor) => <p key={investor} data-direction-net={investor}>{directionInvestorLabels[investor]}：{signed(point.net_shares[investor])} 股／{signed(point.net_lots[investor])} 張；{directionSignLabels[point.signs[investor]]}。{point.signs[investor] === 'zero' && '已驗證原始淨超為零。'}</p>)}
    <dl><dt>原始 receipt SHA256</dt><dd data-direction-receipt-sha>{point.receipt_sha256}</dd><dt>body SHA256</dt><dd data-direction-body-sha>{point.body_sha256}</dd><dt>來源 URL</dt><dd>{String(receipt?.original.url ?? '')}</dd></dl>
    <div className="series-table-wrap"><table aria-label="完整25原欄字串"><thead><tr><th>原欄位</th><th>原始字串</th></tr></thead><tbody>{read.policy.sources.daily.header.map((label, index) => <tr key={label} data-direction-raw-field={index}><th>{label}</th><td><code>{point.source_values[index]}</code></td></tr>)}</tbody></table></div>
    <details><summary>原始 canonical receipt</summary><pre data-direction-canonical-receipt>{receipt?.canonical}</pre></details>
  </section>
}

export default function ChipsDirectionPage() {
  const state = useContext(DirectionContext)
  if (!state) throw new Error('direction provider required')
  const [params, setParams] = useSearchParams(), controls = directionControls(params), rawKey = params.toString()
  const [draft, setDraft] = useState<DirectionControls>(controls), [selected, setSelected] = useState<DirectionPoint | null>(null)
  const { symbol } = useParams()
  useEffect(() => {
    const raw = directionControls(new URLSearchParams(rawKey))
    setDraft(raw); setSelected(null)
    if (!validDirectionControls(raw) || symbol && !DIRECTION_NAMES[symbol]) state.mask()
    if (!rawKey) setParams(new URLSearchParams(raw), { replace: true })
  }, [rawKey, symbol])
  const valid = validDirectionControls(controls) && (!symbol || Boolean(DIRECTION_NAMES[symbol]))
  const read = valid ? state.read : null, stock = read?.stocks.find((s) => s.symbol === symbol), window = stock?.windows[controls.horizon]
  const investor = controls.investor as DirectionInvestor
  const selectedCurrent = window?.points.find((p) => p.date === selected?.date) ?? null
  useEffect(() => setSelected(null), [read])
  function apply(event: FormEvent) { event.preventDefault(); setSelected(null); setParams(new URLSearchParams(draft)) }
  return <main className="chips-series-page">
    <header><p className="series-eyebrow">TPEx · 七股 · 2026/10/06</p><h1>三法人方向與連續區段</h1><p>每日三個原始淨超的方向、所選法人正負零日數與窗口內連續區段。外資不含外資自營商；不推論行情、報酬或交易訊號。</p></header>
    <form className="series-controls" onSubmit={apply} key={rawKey}>
      <label>截止日期<input type="text" aria-label="截止日期" value={draft.as_of} onChange={(e) => setDraft({ ...draft, as_of: e.target.value })} /></label>
      <label>法人<select aria-label="法人" value={draft.investor} onChange={(e) => setDraft({ ...draft, investor: e.target.value })}>{DIRECTION_INVESTORS.map((i) => <option key={i} value={i}>{directionInvestorLabels[i]}</option>)}</select></label>
      <label>窗口<select aria-label="窗口" value={draft.horizon} onChange={(e) => setDraft({ ...draft, horizon: e.target.value })}><option value="5">最近 5 個交易日</option><option value="20">最近 20 個交易日</option></select></label>
      <button type="submit" disabled={state.busy}>套用條件</button>
    </form>
    <p className="series-current">目前原始條件：as_of={controls.as_of} · investor={controls.investor} · horizon={controls.horizon}</p>
    <div className="series-actions"><button type="button" data-direction-first disabled={state.busy || state.firstUsed || !valid} onClick={() => void state.action(true, controls)}>首次取得來源（僅一次）</button><button type="button" data-direction-read disabled={state.busy || !valid} onClick={() => void state.action(false, controls)}>明確讀取已持有來源</button>{symbol && <Link to={directionPath(controls)}>返回七股（保留原始條件）</Link>}</div>
    <p role="status" className="series-status">{state.busy ? '正在驗證完整來源，所有方向、計數與區段暫不顯示。' : state.status}</p>
    {!valid && <p className="series-unavailable">此原始條件不在已准入日期／法人／窗口範圍，所有數值不可用。</p>}
    {!symbol ? <section className="series-cards" aria-label="七股"><p className="series-count">已驗證股數：{read ? '7' : '未知'}</p>{DIRECTION_SYMBOLS.map((s) => {
      const item = read?.stocks.find((x) => x.symbol === s), summary = item?.windows[controls.horizon].investors[investor]
      return <article key={s}><h2>{s} {DIRECTION_NAMES[s]}</h2>{summary ? <><DirectionSummary stats={summary} /><Link to={directionPath(controls, s)}>查看每日方向與連續區段</Link></> : <><p>方向／正負零計數／區段不可用</p><button type="button" disabled>完整七股來源驗證後開啟</button></>}</article>
    })}</section> : !window || !read ? <section className="series-unavailable"><h2>{symbol} {DIRECTION_NAMES[symbol] ?? ''}</h2><p>{!DIRECTION_NAMES[symbol] ? '此標的不在核定七股範圍。' : '來源不可用。'}方向、計數、區段、原列與日曆均不顯示。</p></section> : <section className="series-detail" aria-label="三法人方向明細">
      <h2>{stock?.symbol} {stock?.name} · {directionInvestorLabels[investor]} · {controls.horizon} 日</h2>
      <p>{window.points[0].date} 至 {window.points.at(-1)?.date}，完整 {window.horizon} 個已驗證交易日。</p>
      <DirectionSummary stats={window.investors[investor]} />
      <p>每日三法人方向：{DIRECTION_CATEGORIES.map((category) => <span key={category} data-direction-category-count={category}>{directionCategoryLabels[category]} {window.direction_counts[category]} 日； </span>)}</p>
      <DirectionSegments key={stock?.symbol + '/' + investor + '/' + controls.horizon} window={window} investor={investor} onPoint={setSelected} />
      <div className="series-table-wrap"><table aria-label="每日三法人原始淨超與方向"><thead><tr><th>日期</th>{DIRECTION_INVESTORS.map((i) => <th key={i}>{directionInvestorLabels[i]}（股／張）</th>)}<th>三法人方向</th><th>原列</th></tr></thead><tbody>{window.points.map((point) => <tr key={point.date} data-direction-daily-date={point.date}><th>{point.date}</th>{DIRECTION_INVESTORS.map((i) => <td key={i}>{signed(point.net_shares[i])}<br />{signed(point.net_lots[i])}<br />{directionSignLabels[point.signs[i]]}</td>)}<td>{directionCategoryLabels[point.category]}</td><td><button type="button" data-direction-date={point.date} aria-label={point.date + ' 查看三法人原始列'} onClick={() => setSelected(point)}>查看原始列 #{point.row_ordinal}</button></td></tr>)}</tbody></table></div>
      {selectedCurrent && <DirectionEvidence point={selectedCurrent} read={read} />}
      <details className="series-calendar"><summary>完整觀測日曆與來源說明</summary>
        <p>完整返回 {read.calendar.rows.length} 日，採用 {read.calendar.adopted_dates.length} 日；窗口取最後 {controls.horizon} 日。所有截止後原列經驗證後保留追溯、排除計算。此為指數觀測日曆。</p>
        <p>日曆版本：{read.calendar.version}；日曆 schema：{read.calendar.schema}。</p><p>發布／首次可得／修訂時間未知；不支援歷史 PIT。</p>
        <p>來源版本：{read.policy.sources.index.source_version}；{read.policy.sources.daily.source_version}。</p>
        <div className="series-table-wrap"><table aria-label="完整日曆六原欄"><thead><tr><th>原觀測日期</th><th>採入</th><th>原列與六欄原字串</th></tr></thead><tbody>{read.calendar.rows.map((row) => <tr key={row.date} data-direction-calendar-date={row.date}><th>{row.date}</th><td>{row.date <= controls.as_of ? '是' : '截止後排除'}</td><td><details><summary>#{row.row_ordinal} 查看日曆原列</summary><dl>{['資料日期', '開市', '最高價', '最低價', '收市', '漲跌'].map((label, index) => <div key={label} data-direction-calendar-field={index}><dt>{label}</dt><dd><code>{row.source_values[index]}</code></dd></div>)}<dt>body SHA256</dt><dd>{row.body_sha256}</dd><dt>原始 receipt SHA256</dt><dd>{row.receipt_sha256}</dd></dl><pre>{read.receipts.find((r) => r.sha256 === row.receipt_sha256)?.canonical}</pre></details></td></tr>)}</tbody></table></div>
      </details>
    </section>}
    <footer className="series-calendar"><p>{attribution}</p><p>觀測日：2026/10/08；發布、首次可得及修訂時間未知；不支援歷史 PIT。原成交統計尚未反映券商帳號更正。</p><a href="https://data.gov.tw/license">政府資料開放授權條款第1版</a></footer>
  </main>
}
