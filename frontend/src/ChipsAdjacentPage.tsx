import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ADJACENT_API, ADJACENT_INVESTORS, ADJACENT_NAMES, ADJACENT_SIGNS, ADJACENT_SYMBOLS, ADJACENT_WINDOWS, adjacentControls, adjacentPath, validAdjacentControls, validAdjacentParams, validateAdjacent } from './chipsAdjacent'
import type { AdjacentControls, AdjacentInvestor, AdjacentPoint, AdjacentRead, AdjacentSign, AdjacentStock, AdjacentWindowName } from './chipsAdjacent'
import './ChipsSeriesPage.css'

type Held = { read: AdjacentRead | null; busy: boolean; firstUsed: boolean; status: string; mask: () => void; action: (capture: boolean, controls: AdjacentControls) => Promise<void> }
const AdjacentContext = createContext<Held | null>(null)
export function installAdjacentPageLifecycle(target: EventTarget, mask: () => void): () => void {
  // Clear the departing document before it can become a live BFCache snapshot.
  const hide = () => flushSync(mask)
  const show = (event: Event) => { if ((event as PageTransitionEvent).persisted) flushSync(mask) }
  target.addEventListener('pagehide', hide)
  target.addEventListener('pageshow', show)
  return () => {
    target.removeEventListener('pagehide', hide)
    target.removeEventListener('pageshow', show)
  }
}
export function ChipsAdjacentProvider({ children }: { children: ReactNode }) {
  const [read, setRead] = useState<AdjacentRead | null>(null), [busy, setBusy] = useState(false), [firstUsed, setFirstUsed] = useState(false)
  const [status, setStatus] = useState('尚未取得來源。前5與近5的計數、淨超、差異與原列均未驗證。')
  const pending = useRef(false), firstLatch = useRef(false), epoch = useRef(0)
  function mask() { epoch.current++; setRead(null); setStatus('資料已遮罩，所有比較、原件與日曆不可用。套用有效條件或返回不會恢復舊值；請明確讀取已持有來源。') }
  async function action(capture: boolean, controls: AdjacentControls) {
    if (pending.current || !validAdjacentControls(controls) || capture && firstLatch.current) return
    pending.current = true
    const token = ++epoch.current
    setBusy(true); setRead(null)
    if (capture) { firstLatch.current = true; setFirstUsed(true) }
    try {
      const response = await fetch(ADJACENT_API + (capture ? '/capture' : '') + '?' + new URLSearchParams({ as_of: controls.as_of }), capture ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' } : { method: 'GET' })
      if (!response.ok) throw new Error('HTTP ' + response.status)
      const checked = await validateAdjacent(await response.json())
      if (!checked) throw new Error('完整來源或相鄰窗口證據未通過驗證')
      if (token !== epoch.current) return
      setRead(checked); setStatus('七股前5與近5、三法人計數／淨超／差異及35組日期配對已完整驗證。')
    } catch (error) {
      if (token !== epoch.current) return
      setRead(null); setStatus('資料不可用：' + (error instanceof Error ? error.message : '讀取失敗') + '。套用條件或返回不會恢復舊值；請明確重新讀取。')
    } finally { pending.current = false; setBusy(false) }
  }
  return <AdjacentContext.Provider value={{ read, busy, firstUsed, status, mask, action }}>{children}</AdjacentContext.Provider>
}
export const adjacentInvestorLabels: Record<AdjacentInvestor, string> = { foreign: '外資及陸資（不含外資自營商）', trust: '投信', dealer: '自營商' }
const signLabels: Record<AdjacentSign, string> = { positive: '正淨超', negative: '負淨超', zero: '零淨超' }
const windowLabels: Record<AdjacentWindowName, string> = { previous: '前5個交易日', recent: '最近5個交易日' }
const signed = (s: string | number) => String(s) !== '0' && !String(s).startsWith('-') ? '+' + s : String(s)
const attribution = "財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；相鄰窗口比較為本地衍生結果。"

export function AdjacentSummary({ stock, investor }: { stock: AdjacentStock; investor: AdjacentInvestor }) {
  const previous = stock.windows.previous, recent = stock.windows.recent, comparison = stock.comparisons[investor]
  return <section aria-label="前5與近5精確比較" data-adjacent-summary={investor}>
    <div className="series-table-wrap"><table aria-label="兩窗口計數淨超與差異"><thead><tr><th>統計</th><th>前5<br />{previous.points[0].date} 至 {previous.points[4].date}</th><th>近5<br />{recent.points[0].date} 至 {recent.points[4].date}</th><th>差異（近5−前5）</th></tr></thead><tbody>
      {ADJACENT_SIGNS.map((sign) => <tr key={sign}><th>{signLabels[sign]}日數</th>{ADJACENT_WINDOWS.map((name) => <td key={name} data-adjacent-count={name + '/' + sign}>{stock.windows[name].investors[investor].counts[sign]} 日</td>)}<td data-adjacent-count-delta={sign}>{signed(comparison.count_deltas[sign])} 日</td></tr>)}
      <tr><th>淨超總和（股／張）</th>{ADJACENT_WINDOWS.map((name) => { const stats = stock.windows[name].investors[investor]; return <td key={name} data-adjacent-total={name}>{signed(stats.total_shares)} 股<br />{signed(stats.total_lots)} 張{stats.verified_zero && <p>完整5日淨超總和為零。</p>}</td> })}<td data-adjacent-net-delta>{signed(comparison.net_delta_shares)} 股<br />{signed(comparison.net_delta_lots)} 張{comparison.verified_delta_zero && <p>兩窗口總和相同，差異為零。</p>}</td></tr>
    </tbody></table></div>
    <p>差異只表示最近5減前5；總和或差異為零，不代表每天的原始淨超都是零。兩窗口各恰好5個已驗證交易日。</p>
    {ADJACENT_WINDOWS.map((name) => { const stats = stock.windows[name].investors[investor], latest = stats.latest_run; return <div key={name} data-adjacent-run={name}>
      <p>{windowLabels[name]}窗口內最新區段：{signLabels[latest.sign]} {latest.length} 日，{latest.start_date} 至 {latest.end_date}。{latest.earlier_unknown ? '區段從窗口起點截斷，之前是否延續未知。' : '區段起點位於此窗口內。'}{latest.sign === 'zero' && ' 零淨超已中斷正／負連續區段。'}</p>
      <details><summary>{windowLabels[name]}全部窗口內區段</summary><div className="series-table-wrap"><table aria-label={windowLabels[name] + '區段日期與長度'}><thead><tr><th>方向</th><th>起日</th><th>末日</th><th>窗口內日數</th><th>起點限制</th></tr></thead><tbody>{stats.segments.map((segment) => <tr key={segment.start_date} data-adjacent-segment={name + '/' + segment.start_index}><td>{signLabels[segment.sign]}</td><td>{segment.start_date}</td><td>{segment.end_date}</td><td>{segment.length}</td><td>{segment.earlier_unknown ? '窗口起點截斷；之前未知' : '窗口內'}</td></tr>)}</tbody></table></div></details>
    </div> })}
    <p>區段長度只計各自5日窗口內，不能延伸為完整歷史持續時間。</p>
  </section>
}

export function AdjacentPairs({ stock, investor, onPair }: { stock: AdjacentStock; investor: AdjacentInvestor; onPair: (position: number) => void }) {
  return <section aria-label="兩窗口逐日位置配對"><h2>逐日配對與原件</h2><p>依兩窗口內第1至第5個交易日配對；每對是兩個不同日期，沒有將不同日期視為同一天。</p>
    <div className="series-table-wrap"><table aria-label="前5近5位置配對與淨超差異"><thead><tr><th>位置</th><th>前5日期／淨超</th><th>近5日期／淨超</th><th>近5−前5（股／張）</th><th>雙原列</th></tr></thead><tbody>{stock.pairs.map((pair, index) => <tr key={pair.position} data-adjacent-pair={pair.position}>
      <th>第{pair.position}個交易日</th>{ADJACENT_WINDOWS.map((name) => { const p = stock.windows[name].points[index]; return <td key={name} data-adjacent-pair-side={name}>{p.date}<br />{signed(p.net_shares[investor])} 股／{signed(p.net_lots[investor])} 張<br />{signLabels[p.signs[investor]]}</td> })}<td data-adjacent-pair-delta={pair.position}>{signed(pair.net_delta_shares[investor])} 股／{signed(pair.net_delta_lots[investor])} 張</td><td><button type="button" data-adjacent-pair-button={pair.position} aria-label={'第' + pair.position + '對 ' + pair.previous_date + ' 與 ' + pair.recent_date + ' 查看兩份原始列'} onClick={() => onPair(pair.position)}>查看兩份原始列</button></td>
    </tr>)}</tbody></table></div>
    <p>5個配對差異的總和，已與兩窗口淨超總和差異精確對帳。</p>
  </section>
}

function OriginalEvidence({ point, read, name }: { point: AdjacentPoint; read: AdjacentRead; name: AdjacentWindowName }) {
  const receipt = read.receipts.find((r) => r.sha256 === point.receipt_sha256)
  return <section className="series-evidence" aria-label={windowLabels[name] + '原始列追溯'} data-adjacent-evidence-side={name} data-adjacent-evidence-date={point.date}>
    <h3>{windowLabels[name]} · {point.date} 原始列 #{point.row_ordinal}</h3>
    {ADJACENT_INVESTORS.map((investor) => <p key={investor} data-adjacent-original-net={investor}>{adjacentInvestorLabels[investor]}：{signed(point.net_shares[investor])} 股／{signed(point.net_lots[investor])} 張；{signLabels[point.signs[investor]]}。{point.signs[investor] === 'zero' && '已驗證此日原始淨超為零。'}</p>)}
    <dl><dt>原始 receipt SHA256</dt><dd data-adjacent-receipt-sha>{point.receipt_sha256}</dd><dt>body SHA256</dt><dd data-adjacent-body-sha>{point.body_sha256}</dd><dt>來源 URL</dt><dd>{String(receipt?.original.url ?? '')}</dd></dl>
    <div className="series-table-wrap"><table aria-label={windowLabels[name] + '完整25原欄字串'}><thead><tr><th>原欄位</th><th>原始字串</th></tr></thead><tbody>{read.policy.sources.daily.header.map((label, index) => <tr key={label} data-adjacent-raw-field={index}><th>{label}</th><td><code>{point.source_values[index]}</code></td></tr>)}</tbody></table></div>
    <details><summary>{windowLabels[name]}原始 canonical receipt</summary><pre data-adjacent-canonical-receipt>{receipt?.canonical}</pre></details>
  </section>
}
export function AdjacentEvidence({ stock, position, read }: { stock: AdjacentStock; position: number; read: AdjacentRead }) {
  return <section aria-label="配對兩份原始列" data-adjacent-evidence-pair={position}><h2>第{position}對：兩個日期的原始列</h2>{ADJACENT_WINDOWS.map((name) => <OriginalEvidence key={name} point={stock.windows[name].points[position - 1]} read={read} name={name} />)}</section>
}

export default function ChipsAdjacentPage() {
  const state = useContext(AdjacentContext)
  if (!state) throw new Error('adjacent provider required')
  const [params, setParams] = useSearchParams(), controls = adjacentControls(params), rawKey = params.toString()
  const [draft, setDraft] = useState<AdjacentControls>(controls), [selected, setSelected] = useState<number | null>(null)
  const { symbol } = useParams()
  useEffect(() => installAdjacentPageLifecycle(window, () => { state.mask(); setSelected(null) }), [])
  useEffect(() => {
    const query = new URLSearchParams(rawKey), raw = adjacentControls(query)
    setDraft(raw); setSelected(null)
    if (!validAdjacentParams(query) || !validAdjacentControls(raw) || symbol && !ADJACENT_NAMES[symbol]) state.mask()
    if (!rawKey) setParams(new URLSearchParams(raw), { replace: true })
  }, [rawKey, symbol])
  const valid = validAdjacentParams(params) && validAdjacentControls(controls) && (!symbol || Boolean(ADJACENT_NAMES[symbol]))
  const read = valid ? state.read : null, stock = read?.stocks.find((s) => s.symbol === symbol), investor = controls.investor as AdjacentInvestor
  useEffect(() => setSelected(null), [read])
  function apply(event: FormEvent) { event.preventDefault(); setSelected(null); setParams(new URLSearchParams(draft)) }
  return <main className="chips-series-page">
    <header><p className="series-eyebrow">TPEx · 七股 · 2026/10/06</p><h1>前5與近5法人淨超比較</h1><p>比較相鄰兩個5交易日窗口的三法人淨超、正負零日數、差異與原始列。外資不含外資自營商，不推論行情、報酬或交易訊號。</p></header>
    <form className="series-controls" onSubmit={apply} key={rawKey}><label>截止日期<input type="text" aria-label="截止日期" value={draft.as_of} onChange={(e) => setDraft({ ...draft, as_of: e.target.value })} /></label><label>法人<select aria-label="法人" value={draft.investor} onChange={(e) => setDraft({ ...draft, investor: e.target.value })}>{ADJACENT_INVESTORS.map((i) => <option key={i} value={i}>{adjacentInvestorLabels[i]}</option>)}</select></label><label>窗口<select aria-label="窗口" value={draft.horizon} onChange={(e) => setDraft({ ...draft, horizon: e.target.value })}><option value="5">相鄰兩個5交易日窗口</option></select></label><button type="submit" disabled={state.busy}>套用條件</button></form>
    <p className="series-current">目前原始條件：as_of={controls.as_of} · investor={controls.investor} · horizon={controls.horizon}</p>
    <div className="series-actions"><button type="button" data-adjacent-first disabled={state.busy || state.firstUsed || !valid} onClick={() => void state.action(true, controls)}>首次取得來源（僅一次）</button><button type="button" data-adjacent-read disabled={state.busy || !valid} onClick={() => void state.action(false, controls)}>明確讀取已持有來源</button>{symbol && <Link to={adjacentPath(controls)}>返回七股（保留原始條件）</Link>}</div>
    <p role="status" className="series-status">{state.busy ? '正在驗證完整來源，所有比較、原件與日曆暫不顯示。' : state.status}</p>
    {!valid && <p className="series-unavailable">此原始條件不在已准入日期／法人／5日窗口範圍，或有重複／未知參數，所有數值不可用。</p>}
    {!symbol ? <section className="series-cards" aria-label="七股"><p className="series-count">已驗證股數：{read ? '7' : '未知'}</p>{ADJACENT_SYMBOLS.map((s) => { const item = read?.stocks.find((x) => x.symbol === s); return <article key={s}><h2>{s} {ADJACENT_NAMES[s]}</h2>{item ? <><AdjacentSummary stock={item} investor={investor} /><Link to={adjacentPath(controls, s)}>查看兩窗口逐日配對與原列</Link></> : <><p>前5／近5計數、淨超、差異與原件不可用</p><button type="button" disabled>完整七股來源驗證後開啟</button></>}</article> })}</section> : !stock || !read ? <section className="series-unavailable"><h2>{symbol} {ADJACENT_NAMES[symbol] ?? ''}</h2><p>{!ADJACENT_NAMES[symbol] ? '此標的不在核定七股範圍。' : '來源不可用。'}計數、淨超、差異、配對、區段、原件與日曆均不顯示。</p></section> : <section className="series-detail" aria-label="相鄰兩窗口比較明細"><h2>{stock.symbol} {stock.name} · {adjacentInvestorLabels[investor]}</h2>
      <AdjacentSummary stock={stock} investor={investor} /><AdjacentPairs stock={stock} investor={investor} onPair={setSelected} />
      {selected !== null && <AdjacentEvidence stock={stock} position={selected} read={read} />}
      <details className="series-calendar"><summary>完整觀測日曆與來源說明</summary><p>完整返回 {read.calendar.rows.length} 日，採用 {read.calendar.adopted_dates.length} 日；全部先驗後才取最後10日，前5與近5各恰5日。截止後原列保留追溯但排除計算。此為指數觀測日曆，不代表個股收盤價。</p><p>日曆版本：{read.calendar.version}；日曆 schema：{read.calendar.schema}。</p><p>來源版本：{read.policy.sources.index.source_version}；{read.policy.sources.daily.source_version}。發布／首次可得／修訂時間未知；不支援歷史 PIT。</p>
        <div className="series-table-wrap"><table aria-label="完整日曆六原欄"><thead><tr><th>日期</th><th>採入</th><th>原列與六欄原字串</th></tr></thead><tbody>{read.calendar.rows.map((row) => <tr key={row.date} data-adjacent-calendar-date={row.date}><th>{row.date}</th><td>{row.date <= controls.as_of ? '是' : '截止後排除'}</td><td><details><summary>#{row.row_ordinal} 查看日曆原列</summary><dl>{read.policy.sources.index.header.map((label, index) => <div key={label} data-adjacent-calendar-field={index}><dt>{label}</dt><dd><code>{row.source_values[index]}</code></dd></div>)}<dt>body SHA256</dt><dd>{row.body_sha256}</dd><dt>原始 receipt SHA256</dt><dd>{row.receipt_sha256}</dd></dl><pre>{read.receipts.find((r) => r.sha256 === row.receipt_sha256)?.canonical}</pre></details></td></tr>)}</tbody></table></div>
      </details>
    </section>}
    <footer className="series-calendar"><p>{attribution}</p><p>觀測日：2026/10/08；發布、首次可得及修訂時間未知；不支援歷史 PIT。原成交統計尚未反映券商帳號更正。</p><a href="https://data.gov.tw/license">政府資料開放授權條款第1版</a></footer>
  </main>
}
