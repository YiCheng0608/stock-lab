import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { DEALER_COMPONENTS, DEALER_COMPONENTS_API, DEALER_COMPONENTS_ATTRIBUTION, DEALER_COMPONENTS_NAMES, DEALER_COMPONENTS_SYMBOLS, DEALER_METRICS, dealerControls, dealerPath, validDealerControls, validDealerParams, validateDealerComponents } from './chipsDealerComponents'
import type { DealerComponent, DealerControls, DealerRead, DealerStock } from './chipsDealerComponents'
import './ChipsSeriesPage.css'

type Held = { read: DealerRead | null; busy: boolean; firstUsed: boolean; status: string; mask: () => void; action: (capture: boolean, controls: DealerControls, event: Event) => Promise<void> }
const DealerContext = createContext<Held | null>(null)
export function isDealerTrustedAction(event: Event): boolean { return event instanceof Event && event.isTrusted }
export function installDealerPageLifecycle(target: EventTarget, mask: () => void): () => void {
  const hide = () => flushSync(mask)
  const show = (event: Event) => { if ((event as PageTransitionEvent).persisted) flushSync(mask) }
  target.addEventListener('pagehide', hide)
  target.addEventListener('pageshow', show)
  target.addEventListener('popstate', hide)
  return () => { target.removeEventListener('pagehide', hide); target.removeEventListener('pageshow', show); target.removeEventListener('popstate', hide) }
}
export function ChipsDealerComponentsProvider({ children }: { children: ReactNode }) {
  const [read, setRead] = useState<DealerRead | null>(null), [busy, setBusy] = useState(false), [firstUsed, setFirstUsed] = useState(false)
  const [status, setStatus] = useState('尚未取得來源。自行買賣、避險及總額的每日與五日數值、原列及日曆均未驗證。')
  const pending = useRef(false), firstLatch = useRef(false), epoch = useRef(0)
  function mask() { epoch.current++; setRead(null); setStatus('資料已遮罩，全部每日、五日總額、對帳、原列及日曆不可用。套用或返回不會恢復舊值；請明確讀取已持有來源。') }
  async function action(capture: boolean, controls: DealerControls, event: Event) {
    if (!isDealerTrustedAction(event) || pending.current || !validDealerControls(controls) || capture && firstLatch.current) return
    pending.current = true
    const token = ++epoch.current
    setBusy(true); setRead(null)
    if (capture) { firstLatch.current = true; setFirstUsed(true) }
    try {
      const response = await fetch(DEALER_COMPONENTS_API + (capture ? '/capture' : '') + '?' + new URLSearchParams({ as_of: controls.as_of }), capture ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' } : { method: 'GET' })
      if (!response.ok) throw new Error('HTTP ' + response.status)
      const checked = await validateDealerComponents(await response.json())
      if (!checked) throw new Error('完整來源或三組對帳未通過驗證')
      if (token !== epoch.current) return
      setRead(checked); setStatus('完整七股五日原列與三組買進／賣出／淨超已驗證，每日及五日自行買賣＋避險＝總額。')
    } catch (error) {
      if (token !== epoch.current) return
      setRead(null); setStatus('資料不可用：' + (error instanceof Error ? error.message : '讀取失敗') + '。全部每日、總額、對帳、原件及日曆已清空；請明確重新讀取。')
    } finally { pending.current = false; setBusy(false) }
  }
  return <DealerContext.Provider value={{ read, busy, firstUsed, status, mask, action }}>{children}</DealerContext.Provider>
}
const names: Record<DealerComponent, string> = { self: '自行買賣', hedge: '避險', total: '自營商總額' }
const metrics = { buy: '買進', sell: '賣出', net: '淨超' }
const signed = (s: string) => s !== '0' && !s.startsWith('-') ? '+' + s : s
export function DealerSummary({ stock }: { stock: DealerStock }) {
  const window = stock.window
  return <section aria-label="五日三組買賣淨超總額" data-dealer-summary={stock.symbol}>
    <h3>最近5個已驗證交易日 · {window.points[0].date} 至 {window.points[4].date}</h3>
    <div className="series-table-wrap"><table aria-label="自行買賣避險總額五日精確對帳"><thead><tr><th>五日總和（股／張）</th>{DEALER_COMPONENTS.map((c) => <th key={c}>{names[c]}</th>)}</tr></thead><tbody>
      {DEALER_METRICS.map((metric) => <tr key={metric}><th>{metrics[metric]}</th>{DEALER_COMPONENTS.map((c) => { const a = window.totals[c]; return <td key={c} data-dealer-total={c + '/' + metric} data-dealer-component={c} data-dealer-metric={metric} data-dealer-shares={a[metric + '_shares' as 'buy_shares']} data-dealer-lots={a[metric + '_lots' as 'buy_lots']}>{signed(a[metric + '_shares' as 'buy_shares'])} 股<br />{signed(a[metric + '_lots' as 'buy_lots'])} 張{a['verified_' + metric + '_zero' as 'verified_buy_zero'] && <p>已驗證五日總和為零</p>}</td> })}</tr>)}
    </tbody></table></div>
    <p data-dealer-window-check={String(window.component_check)}>五日買進、賣出、淨超各自完成「自行買賣＋避險＝自營商總額」對帳；三組各自買進−賣出＝淨超。</p>
    <p>五日總和為零與單日原值為零分開驗證；缺資料不顯示為零。</p>
  </section>
}
export function DealerDaily({ stock, onPoint }: { stock: DealerStock; onPoint: (index: number) => void }) {
  return <section aria-label="五日三組每日買賣淨超"><h3>每日自行買賣、避險及總額</h3>
    <div className="series-table-wrap"><table aria-label="三組每日精確買進賣出淨超"><thead><tr><th rowSpan={2}>交易日</th>{DEALER_COMPONENTS.map((c) => <th colSpan={3} key={c}>{names[c]}</th>)}<th rowSpan={2}>對帳／原列</th></tr><tr>{DEALER_COMPONENTS.flatMap((c) => DEALER_METRICS.map((m) => <th key={c + m}>{metrics[m]}（股／張）</th>))}</tr></thead><tbody>
      {stock.window.points.map((p, index) => <tr key={p.date} data-dealer-row-date={p.date}><th>{p.date}</th>{DEALER_COMPONENTS.flatMap((c) => DEALER_METRICS.map((m) => { const a = p.components[c]; return <td key={c + m} data-dealer-daily-date={p.date} data-dealer-component={c} data-dealer-metric={m} data-dealer-shares={a[m + '_shares' as 'buy_shares']} data-dealer-lots={a[m + '_lots' as 'buy_lots']}>{signed(a[m + '_shares' as 'buy_shares'])} 股<br />{signed(a[m + '_lots' as 'buy_lots'])} 張{a['verified_' + m + '_zero' as 'verified_buy_zero'] && <p>已驗證原值為零</p>}</td> }))}<td><p data-dealer-daily-check={p.date}>三組買−賣＝淨；自行＋避險＝總額</p><button type="button" data-dealer-point-button={p.date} onClick={() => onPoint(index)}>查看完整原始列</button></td></tr>)}
    </tbody></table></div>
  </section>
}
export function DealerEvidence({ stock, index, read }: { stock: DealerStock; index: number; read: DealerRead }) {
  const p = stock.window.points[index], receipt = read.receipts.find((r) => r.sha256 === p.receipt_sha256)
  return <section className="series-evidence" aria-label="完整每日原始列追溯" data-dealer-evidence-date={p.date}>
    <h3>{p.date} · 原始列 <span data-dealer-row-ordinal>{p.row_ordinal}</span></h3>
    {DEALER_COMPONENTS.map((c) => <p key={c} data-dealer-original-component={c}>{names[c]}：{DEALER_METRICS.map((m) => <span key={m} data-dealer-original-metric={c + '/' + m}>{metrics[m]} {signed(p.components[c][m + '_shares' as 'buy_shares'])} 股／{signed(p.components[c][m + '_lots' as 'buy_lots'])} 張；</span>)}</p>)}
    <dl><dt>ORIGINAL receipt SHA256</dt><dd data-dealer-receipt-sha>{p.receipt_sha256}</dd><dt>body SHA256</dt><dd data-dealer-body-sha>{p.body_sha256}</dd><dt>來源 URL</dt><dd data-dealer-source-url>{String(receipt?.original.url ?? '')}</dd></dl>
    <div className="series-table-wrap"><table aria-label="完整25原欄字串"><thead><tr><th>原欄位</th><th>原始字串</th></tr></thead><tbody>{read.policy.sources.daily.header.map((label, field) => <tr key={label} data-dealer-raw-field={field}><th>{label}</th><td><code>{p.source_values[field]}</code></td></tr>)}</tbody></table></div>
    <details><summary>未增補的原始 canonical receipt</summary><pre data-dealer-canonical-receipt>{receipt?.canonical}</pre></details>
  </section>
}
export function DealerCalendar({ read }: { read: DealerRead }) {
  return <details className="series-calendar" data-dealer-calendar><summary>完整觀測日曆與來源說明</summary>
    <p>完整返回 {read.calendar.rows.length} 日，採入 {read.calendar.adopted_dates.length} 日；全部先驗後才取最近5日。截止後原列保留追溯但排除計算，此日曆不代表個股收盤價。</p>
    <p>日曆 schema：{read.calendar.schema}；版本：{read.calendar.version}。</p><p>來源版本：{read.policy.sources.index.source_version}；{read.policy.sources.daily.source_version}。</p>
    <div className="series-table-wrap"><table aria-label="完整日曆六原欄"><thead><tr><th>日期</th><th>採入</th><th>原列／六欄／receipt</th></tr></thead><tbody>{read.calendar.rows.map((row) => <tr key={row.date} data-dealer-calendar-date={row.date}><th>{row.date}</th><td>{row.date <= read.as_of ? '是' : '截止後排除'}</td><td><details><summary>#{row.row_ordinal} 查看日曆原列</summary><dl>{read.policy.sources.index.header.map((label, field) => <div key={label} data-dealer-calendar-field={field}><dt>{label}</dt><dd><code>{row.source_values[field]}</code></dd></div>)}<dt>body SHA256</dt><dd data-dealer-calendar-body-sha>{row.body_sha256}</dd><dt>ORIGINAL receipt SHA256</dt><dd data-dealer-calendar-receipt-sha>{row.receipt_sha256}</dd></dl><pre data-dealer-calendar-canonical>{read.receipts.find((r) => r.sha256 === row.receipt_sha256)?.canonical}</pre></details></td></tr>)}</tbody></table></div>
  </details>
}
export default function ChipsDealerComponentsPage() {
  const state = useContext(DealerContext)
  if (!state) throw new Error('dealer components provider required')
  const [params, setParams] = useSearchParams(), controls = dealerControls(params), rawKey = params.toString()
  const [draft, setDraft] = useState<DealerControls>(controls), [selected, setSelected] = useState<number | null>(null)
  const { symbol } = useParams()
  useEffect(() => installDealerPageLifecycle(window, () => { state.mask(); setSelected(null) }), [])
  useEffect(() => {
    const query = new URLSearchParams(rawKey), raw = dealerControls(query)
    setDraft(raw); setSelected(null)
    if (!validDealerParams(query) || !validDealerControls(raw) || symbol && !DEALER_COMPONENTS_NAMES[symbol]) state.mask()
    if (!rawKey) setParams(new URLSearchParams(raw), { replace: true })
  }, [rawKey, symbol])
  const valid = validDealerParams(params) && validDealerControls(controls) && (!symbol || Boolean(DEALER_COMPONENTS_NAMES[symbol]))
  const read = valid ? state.read : null, stock = read?.stocks.find((s) => s.symbol === symbol)
  useEffect(() => setSelected(null), [read])
  const apply = (event: FormEvent) => { event.preventDefault(); state.mask(); setSelected(null); setParams(new URLSearchParams(draft)) }
  return <main className="chips-series-page">
    <header><p className="series-eyebrow">TPEx · 七股 · 2026/10/06</p><h1>自營商自行買賣與避險對帳</h1><p>同一截止最近5個交易日，自行買賣、避險及自營商總額的買進／賣出／淨超始終並列，保留完整原欄追溯。</p></header>
    <form className="series-controls" onSubmit={apply} key={rawKey}><label>截止日期<input type="text" aria-label="截止日期" value={draft.as_of} onChange={(e) => setDraft({ ...draft, as_of: e.target.value })} /></label><label>法人<select aria-label="法人" value={draft.investor} onChange={(e) => setDraft({ ...draft, investor: e.target.value })}><option value="dealer">自營商（自行買賣＋避險）</option></select></label><label>窗口<select aria-label="窗口" value={draft.horizon} onChange={(e) => setDraft({ ...draft, horizon: e.target.value })}><option value="5">最近5個交易日</option></select></label><button type="submit" disabled={state.busy}>套用條件</button></form>
    <p className="series-current">目前原始條件：as_of={controls.as_of} · investor={controls.investor} · horizon={controls.horizon}</p>
    <div className="series-actions"><button type="button" data-dealer-first disabled={state.busy || state.firstUsed || !valid} onClick={(e) => void state.action(true, controls, e.nativeEvent)}>首次取得來源（僅一次）</button><button type="button" data-dealer-read disabled={state.busy || !valid} onClick={(e) => void state.action(false, controls, e.nativeEvent)}>明確讀取已持有來源</button>{symbol && <Link to={dealerPath(controls)} onClick={() => { state.mask(); setSelected(null) }}>返回七股（保留原始條件）</Link>}</div>
    <p role="status" className="series-status">{state.busy ? '正在驗證完整來源，全部數值、對帳、原件及日曆暫不顯示。' : state.status}</p>
    {!valid && <p className="series-unavailable">原始條件未准入，或有缺少／重複／未知參數；所有每日、五日總額、對帳與追溯不可用。</p>}
    {!symbol ? <section className="series-cards" aria-label="七股"><p className="series-count">已驗證股數：{read ? '7' : '未知'}</p>{DEALER_COMPONENTS_SYMBOLS.map((s) => { const item = read?.stocks.find((x) => x.symbol === s); return <article key={s}><h2>{s} {DEALER_COMPONENTS_NAMES[s]}</h2>{item ? <><DealerSummary stock={item} /><Link to={dealerPath(controls, s)}>查看五日三組每日對帳及原列</Link></> : <><p>三組每日、五日總額、對帳與原件不可用</p><button type="button" disabled>完整七股來源驗證後開啟</button></>}</article> })}</section> : !stock || !read ? <section className="series-unavailable"><h2>{symbol} {DEALER_COMPONENTS_NAMES[symbol] ?? ''}</h2><p>{!DEALER_COMPONENTS_NAMES[symbol] ? '此標的不在核定七股範圍。' : '來源不可用。'}全部每日、五日總額、對帳、原件及日曆不顯示。</p></section> : <section className="series-detail" aria-label="自營商三組五日明細"><h2>{stock.symbol} {stock.name}</h2><DealerSummary stock={stock} /><DealerDaily stock={stock} onPoint={setSelected} />{selected !== null && <DealerEvidence stock={stock} index={selected} read={read} />}<DealerCalendar read={read} /></section>}
    <footer className="series-calendar"><p>{DEALER_COMPONENTS_ATTRIBUTION}</p><p>觀測日2026/10/08，截止日2026/10/06；發布、首次可得、修訂時間未知，不支援歷史PIT。原成交統計尚未反映券商帳號更正。</p><a href="https://data.gov.tw/license">政府資料開放授權條款第1版</a></footer>
  </main>
}
