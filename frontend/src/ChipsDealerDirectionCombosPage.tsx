import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { COMBOS_API, COMBOS_COMPONENTS, COMBOS_DATASET, COMBOS_KEYS, COMBOS_NAMES, COMBOS_PROVIDER, COMBOS_SYMBOLS, COMBOS_WINDOW_DATES, comboActionAllowed, comboControls, comboLots, comboPath, comboRequestInit, comboReturnPath, resolveComboResponse, validComboControls, validComboParams } from './chipsDealerDirectionCombos'
import type { ComboAmounts, ComboComponent, ComboControls, ComboKey, ComboPhase, ComboRead, ComboSegment, ComboStock } from './chipsDealerDirectionCombos'
import './ChipsSeriesPage.css'

type Held = { read: ComboRead | null; busy: boolean; firstUsed: boolean; phase: ComboPhase; status: string; mask: () => void; action: (capture: boolean, controls: ComboControls, event: Event) => Promise<void> }
const ComboContext = createContext<Held | null>(null)
const INITIAL_STATUS = '尚未取得來源。自行買賣與避險的每日方向、九種組合、連續區段與原列均未驗證。'
const MASKED_STATUS = '資料已遮罩，全部每日淨額、方向、組合、區段、原列及日曆不可用。套用或返回不會恢復舊值；請明確讀取已持有來源。'
export function isComboTrustedAction(event: Event): boolean { return event instanceof Event && event.isTrusted }
export function installComboPageLifecycle(target: EventTarget, mask: () => void): () => void {
  const hide = () => flushSync(mask)
  const show = (event: Event) => { if ((event as PageTransitionEvent).persisted) flushSync(mask) }
  target.addEventListener('pagehide', hide)
  target.addEventListener('pageshow', show)
  target.addEventListener('popstate', hide)
  return () => { target.removeEventListener('pagehide', hide); target.removeEventListener('pageshow', show); target.removeEventListener('popstate', hide) }
}
export function ChipsDealerDirectionCombosProvider({ children }: { children: ReactNode }) {
  const [read, setRead] = useState<ComboRead | null>(null), [busy, setBusy] = useState(false), [firstUsed, setFirstUsed] = useState(false)
  const [phase, setPhase] = useState<ComboPhase>('unacquired'), [status, setStatus] = useState(INITIAL_STATUS)
  const pending = useRef(false), firstLatch = useRef(false), epoch = useRef(0), generation = useRef<string | null>(null)
  function mask() { epoch.current++; setRead(null); setPhase('masked'); setStatus(MASKED_STATUS) }
  async function action(capture: boolean, controls: ComboControls, event: Event) {
    if (!comboActionAllowed({ trusted: isComboTrustedAction(event), pending: pending.current, valid: validComboControls(controls), capture, firstLatched: firstLatch.current })) return
    pending.current = true
    const token = ++epoch.current
    setBusy(true); setRead(null)
    if (capture) { firstLatch.current = true; setFirstUsed(true) }
    try {
      const response = await fetch(COMBOS_API + (capture ? '/capture' : '') + '?' + new URLSearchParams({ as_of: controls.as_of }), comboRequestInit(capture))
      let body: unknown = null
      try { body = await response.json() } catch { body = null }
      if (token !== epoch.current) return
      const outcome = await resolveComboResponse({ capture, status: response.status, ok: response.ok, body, heldGeneration: generation.current })
      if (token !== epoch.current) return
      generation.current = outcome.generation
      if (outcome.lockFirst) { firstLatch.current = true; setFirstUsed(true) }
      setRead(outcome.read); setPhase(outcome.phase); setStatus(outcome.text)
    } catch (error) {
      if (token !== epoch.current) return
      setRead(null); setPhase('error'); setStatus('資料不可用：' + (error instanceof Error ? error.message : '讀取失敗') + '。全部每日淨額、方向、組合、區段、原列及日曆已清空；請明確重新讀取。')
    } finally { pending.current = false; setBusy(false) }
  }
  return <ComboContext.Provider value={{ read, busy, firstUsed, phase, status, mask, action }}>{children}</ComboContext.Provider>
}
const componentNames: Record<ComboComponent, string> = { self: '自行買賣', hedge: '避險' }
const signNames = { positive: '正', negative: '負', zero: '零' } as const
const signed = (s: string) => s !== '0' && !s.startsWith('-') ? '+' + s : s
export function comboLabel(key: ComboKey): string {
  const [own, hedge] = key.split('_') as ['positive' | 'negative' | 'zero', 'positive' | 'negative' | 'zero']
  return '自行買賣' + signNames[own] + '／避險' + signNames[hedge]
}
function segmentText(s: ComboSegment): string { return signNames[s.sign] + ' · ' + s.start_date + ' 至 ' + s.end_date + ' · ' + s.length + ' 日' + (s.earlier_unknown ? ' · 窗口前延續未知' : '') }
function Amount({ a, date, component }: { a: ComboAmounts; date: string; component: ComboComponent }) {
  return <td data-combos-daily-date={date} data-combos-component={component} data-combos-shares={a.net_shares} data-combos-lots={a.net_lots} data-combos-sign={a.sign}>{signed(a.net_shares)} 股<br />{signed(a.net_lots)} 張 · {signNames[a.sign]}{a.net_shares === '0' && <p>已驗證淨額為零</p>}</td>
}
export function ComboSummary({ stock }: { stock: ComboStock }) {
  const w = stock.window
  return <section aria-label="自行買賣與避險方向計數與最新區段" data-combos-summary={stock.symbol}>
    <h3>最近5個已驗證交易日 · {w.points[0].date} 至 {w.points[4].date}</h3>
    <div className="series-table-wrap"><table aria-label="自行買賣與避險並列方向計數"><thead><tr><th>五日方向（日數）</th><th>正</th><th>負</th><th>零</th><th>窗口內最新區段</th></tr></thead><tbody>
      {COMBOS_COMPONENTS.map((c) => <tr key={c}><th>{componentNames[c]}</th>{(['positive', 'negative', 'zero'] as const).map((s) => <td key={s} data-combos-count={c + '/' + s}>{w.counts[c][s]}</td>)}<td data-combos-latest={c}>{segmentText(w.latest[c])}</td></tr>)}
    </tbody></table></div>
    <p data-combos-opposite-count={w.opposite.count}>相反方向日數：{w.opposite.count}（自行買賣與避險同日一正一負）</p>
    <p>只計所選五日窗口；首段之前延續未知，不推歷史完整持續性或市場含義。真零中斷正負連續區段；缺資料不當作零。</p>
  </section>
}
export function ComboDaily({ stock, onPoint }: { stock: ComboStock; onPoint: (index: number) => void }) {
  return <section aria-label="五日自行買賣與避險每日淨額"><h3>每日自行買賣與避險淨額（買進−賣出，本地衍生）</h3>
    <div className="series-table-wrap"><table aria-label="每日精確淨額與方向組合"><thead><tr><th>交易日</th><th>自行買賣淨額（股／張）</th><th>避險淨額（股／張）</th><th>當日組合</th><th>相反方向</th><th>原列</th></tr></thead><tbody>
      {stock.window.points.map((p, index) => <tr key={p.date} data-combos-row-date={p.date}><th>{p.date}</th><Amount a={p.self} date={p.date} component="self" /><Amount a={p.hedge} date={p.date} component="hedge" /><td data-combos-daily-combination={p.date + '/' + p.combination}>{comboLabel(p.combination)}</td><td data-combos-daily-opposite={p.date + '/' + String(p.opposite)}>{p.opposite ? '是' : '否'}</td><td><button type="button" data-combos-point-button={p.date} onClick={() => onPoint(index)}>查看該日全部原列</button></td></tr>)}
    </tbody></table></div>
  </section>
}
export function ComboSegments({ stock, onPoint }: { stock: ComboStock; onPoint: (index: number) => void }) {
  return <section aria-label="全部最大連續區段"><h3>全部最大連續區段</h3>
    {COMBOS_COMPONENTS.map((c) => <div className="series-table-wrap" key={c}><table aria-label={componentNames[c] + '最大連續區段'}><thead><tr><th>{componentNames[c]}區段</th><th>方向</th><th>起訖</th><th>日數</th><th>窗口前延續</th><th>日期（點開原列）</th></tr></thead><tbody>
      {stock.window.segments[c].map((s, i) => <tr key={i} data-combos-segment={c + '/' + i}><th>#{i + 1}{i === stock.window.segments[c].length - 1 ? '（最新）' : ''}</th><td>{signNames[s.sign]}</td><td>{s.start_date} 至 {s.end_date}</td><td>{s.length}</td><td>{s.earlier_unknown ? '未知' : '否'}</td><td>{COMBOS_WINDOW_DATES.slice(s.start_index, s.end_index + 1).map((d, k) => <button type="button" key={d} data-combos-segment-date={c + '/' + i + '/' + d} onClick={() => onPoint(s.start_index + k)}>{d}</button>)}</td></tr>)}
    </tbody></table></div>)}
    <p>零自成一段並中斷正負連續區段；首段的「窗口前延續」只表示窗口之前未知。</p>
  </section>
}
export function ComboCombinations({ stock, onPoint }: { stock: ComboStock; onPoint: (index: number) => void }) {
  const w = stock.window
  return <section aria-label="九種每日組合與相反方向"><h3>九種每日組合（自行買賣／避險）</h3>
    <div className="series-table-wrap"><table aria-label="九種組合日數與日期"><thead><tr><th>組合</th><th>日數</th><th>日期（點開原列）</th></tr></thead><tbody>
      {COMBOS_KEYS.map((k) => <tr key={k} data-combos-combo={k}><th>{comboLabel(k)}</th><td data-combos-combo-count={k + '/' + w.combination_counts[k]}>{w.combination_counts[k]}</td><td>{w.combination_dates[k].length ? w.combination_dates[k].map((d) => <button type="button" key={d} data-combos-combo-date={k + '/' + d} onClick={() => onPoint(COMBOS_WINDOW_DATES.indexOf(d))}>{d}</button>) : '無'}</td></tr>)}
    </tbody></table></div>
    <p data-combos-opposite-total={w.opposite.count}>相反方向日數 {w.opposite.count}（僅「自行買賣正／避險負」與「自行買賣負／避險正」）：{w.opposite.dates.length ? w.opposite.dates.map((d) => <button type="button" key={d} data-combos-opposite-date={d} onClick={() => onPoint(COMBOS_WINDOW_DATES.indexOf(d))}>{d}</button>) : '無'}</p>
  </section>
}
export function ComboEvidence({ stock, index, read }: { stock: ComboStock; index: number; read: ComboRead }) {
  const p = stock.window.points[index], receipt = read.receipts[p.request_index]
  return <section className="series-evidence" aria-label="該股該日 FinMind 全部 name 原列追溯" data-combos-evidence-date={p.date}>
    <h3>{stock.symbol} {stock.name} · {p.date} · 原始回應共 5 個 name 列</h3>
    <p>自行買賣淨額 {signed(p.self.net_shares)} 股（{signNames[p.self.sign]}）；避險淨額 {signed(p.hedge.net_shares)} 股（{signNames[p.hedge.sign]}）；組合：{comboLabel(p.combination)}；相反方向：{p.opposite ? '是' : '否'}。淨額＝買進−賣出，FinMind 無淨額欄。</p>
    <div className="series-table-wrap"><table aria-label="該日全部 name 原列"><thead><tr><th>回應列序（0 起）</th><th>name</th><th>買進（股／張）</th><th>賣出（股／張）</th><th>原鍵序</th></tr></thead><tbody>
      {p.rows.map((r) => <tr key={r.name} data-combos-raw-row={r.name} data-combos-raw-index={r.row_index}><td>{r.row_index}</td><th>{r.name}</th><td data-combos-raw-buy={r.buy_shares}>{r.buy_shares} 股 / {comboLots(BigInt(r.buy_shares))} 張{r.buy_shares === '0' && <p>已驗證原值為零</p>}</td><td data-combos-raw-sell={r.sell_shares}>{r.sell_shares} 股 / {comboLots(BigInt(r.sell_shares))} 張{r.sell_shares === '0' && <p>已驗證原值為零</p>}</td><td><code data-combos-key-order>{r.key_order.join(',')}</code></td></tr>)}
    </tbody></table></div>
    <dl><dt>receipt SHA256（canonical）</dt><dd data-combos-receipt-sha>{p.receipt_sha256}</dd><dt>body SHA256</dt><dd data-combos-body-sha>{p.body_sha256}</dd><dt>來源 URL</dt><dd data-combos-source-url>{p.url}</dd><dt>日曆參照</dt><dd data-combos-calendar-reference>{read.calendar.reference}（固定交易日，不取日曆；{p.date} 為窗口內第 {index + 1} 日）</dd></dl>
    <details><summary>未增補的 canonical receipt</summary><pre data-combos-canonical-receipt>{receipt.canonical}</pre></details>
  </section>
}
export function ComboCalendar({ read }: { read: ComboRead }) {
  const c = read.calendar
  return <details className="series-calendar" data-combos-calendar><summary>固定日曆參照與來源說明</summary>
    <p>{c.reference}：窗口五日 {c.window_dates.join('、')}；{c.anchor_only_dates.join('、')} 只供五日淨額 anchor 核對，不進入方向計算；休市日 {c.closed_dates.join('、')}。日曆 GET {c.calendar_gets} 次。</p>
    <p>{c.meaning}</p>
    <p>五日淨額 anchor 核對：{read.provenance.anchors_checked} 個值全數相等後才可用。零值形狀比對（僅記錄，不拒用）：{read.provenance.record_only_comparison.matches ? '與前身紀錄一致' : '與前身紀錄不同（不判為來源錯誤；後補計可能使買進與賣出等額增加）'}。</p>
  </details>
}
export default function ChipsDealerDirectionCombosPage() {
  const state = useContext(ComboContext)
  if (!state) throw new Error('dealer direction combos provider required')
  const [params, setParams] = useSearchParams(), controls = comboControls(params), rawKey = params.toString(), { search } = useLocation()
  const [draft, setDraft] = useState<ComboControls>(controls), [selected, setSelected] = useState<number | null>(null)
  const { symbol } = useParams()
  useEffect(() => installComboPageLifecycle(window, () => { state.mask(); setSelected(null) }), [])
  useEffect(() => {
    const query = new URLSearchParams(rawKey), raw = comboControls(query)
    setDraft(raw); setSelected(null)
    if (!validComboParams(query) || !validComboControls(raw) || symbol && !COMBOS_NAMES[symbol]) state.mask()
    if (!rawKey) setParams(new URLSearchParams(raw), { replace: true })
  }, [rawKey, symbol])
  const valid = validComboParams(params) && validComboControls(controls) && (!symbol || Boolean(COMBOS_NAMES[symbol]))
  const read = valid ? state.read : null, stock = read?.stocks.find((s) => s.symbol === symbol)
  useEffect(() => setSelected(null), [read])
  const apply = (event: FormEvent) => { event.preventDefault(); state.mask(); setSelected(null); setParams(new URLSearchParams(draft)) }
  return <main className="chips-series-page">
    <header><p className="series-eyebrow">TPEx · 七股 · 2026/10/06</p><h1>自營商自行買賣與避險：五日方向組合</h1><p>同一截止最近5個交易日，自行買賣與避險的每日淨額方向、九種每日組合、相反方向日數、最大連續區段與窗口內最新區段始終並列，並可追溯到該股該日 FinMind 的全部原列。</p></header>
    <form className="series-controls" onSubmit={apply} key={rawKey}><label>截止日期<input type="text" aria-label="截止日期" value={draft.as_of} onChange={(e) => setDraft({ ...draft, as_of: e.target.value })} /></label><label>法人<select aria-label="法人" value={draft.investor} onChange={(e) => setDraft({ ...draft, investor: e.target.value })}><option value="dealer">自營商（自行買賣＋避險）</option></select></label><label>窗口<select aria-label="窗口" value={draft.horizon} onChange={(e) => setDraft({ ...draft, horizon: e.target.value })}><option value="5">最近5個交易日</option></select></label><button type="submit" disabled={state.busy}>套用條件</button></form>
    <p className="series-current">目前原始條件：as_of={controls.as_of} · investor={controls.investor} · horizon={controls.horizon}</p>
    <div className="series-actions"><button type="button" data-combos-first disabled={state.busy || state.firstUsed || !valid} onClick={(e) => void state.action(true, controls, e.nativeEvent)}>首次取得來源（僅一次）</button><button type="button" data-combos-read disabled={state.busy || !valid} onClick={(e) => void state.action(false, controls, e.nativeEvent)}>明確讀取已持有來源</button>{symbol && <Link to={comboReturnPath(search)} data-combos-return onClick={() => { state.mask(); setSelected(null) }}>返回七股（保留原始條件）</Link>}</div>
    <p role="status" className="series-status" data-combos-phase={state.busy ? 'busy' : state.phase}>{state.busy ? '正在驗證完整來源，全部數值、方向、組合、區段、原列及日曆暫不顯示。' : state.status}</p>
    {!valid && <p className="series-unavailable">原始條件未准入，或有缺少／重複／未知參數；所有每日淨額、方向、組合、區段與追溯不可用。</p>}
    {!symbol ? <section className="series-cards" aria-label="七股"><p className="series-count">已驗證股數：{read ? '7' : '未知'}</p>{COMBOS_SYMBOLS.map((s) => { const item = read?.stocks.find((x) => x.symbol === s); return <article key={s}><h2>{s} {COMBOS_NAMES[s]}</h2>{item ? <><ComboSummary stock={item} /><Link to={comboPath(controls, s)}>查看五日每日方向、組合、區段及原列</Link></> : <><p>自行買賣與避險的方向、組合、區段與原列不可用</p><button type="button" disabled>完整七股來源驗證後開啟</button></>}</article> })}</section> : !stock || !read ? <section className="series-unavailable"><h2>{symbol} {COMBOS_NAMES[symbol] ?? ''}</h2><p>{!COMBOS_NAMES[symbol] ? '此標的不在核定七股範圍。' : '來源不可用。'}全部每日淨額、方向、組合、區段、原列及日曆不顯示。</p></section> : <section className="series-detail" aria-label="自行買賣與避險五日明細"><h2>{stock.symbol} {stock.name}</h2><ComboSummary stock={stock} /><ComboDaily stock={stock} onPoint={setSelected} /><ComboSegments stock={stock} onPoint={setSelected} /><ComboCombinations stock={stock} onPoint={setSelected} />{selected !== null && <ComboEvidence stock={stock} index={selected} read={read} />}<ComboCalendar read={read} /></section>}
    <footer className="series-calendar"><p>提供者：{COMBOS_PROVIDER}（服務提供者，非官方直接來源）；資料集：{COMBOS_DATASET}（個股三大法人買賣）。</p><p>{read ? read.provenance.rights : '用途限本地、個人、非商用的 RAM 研究；不再散布、不鏡像、不落盤。'}</p><p>{read ? read.provenance.value_label : '取得值為「API 當下值」（非 PIT）；買進與賣出可能事後等額補計，淨額不受影響。'}</p><p>每日淨額＝買進−賣出，為本地衍生值（FinMind 無淨額欄）；發布、首次可得、修訂時間未知，不支援歷史 PIT。</p></footer>
  </main>
}
