import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { SERIES_API, SERIES_INVESTORS, SERIES_NAMES, SERIES_SYMBOLS, seriesControls, seriesGeometry, seriesPath, validSeriesControls, validateSeries } from './chipsSeries'
import type { SeriesControls, SeriesInvestor, SeriesPoint, SeriesRead, SeriesWindow } from './chipsSeries'
import './ChipsSeriesPage.css'

type Held = { read: SeriesRead | null; busy: boolean; firstUsed: boolean; status: string; mask: () => void; action: (capture: boolean, c: SeriesControls) => Promise<void> }
const SeriesContext = createContext<Held | null>(null)
export function ChipsSeriesProvider({ children }: { children: ReactNode }) {
  const [read, setRead] = useState<SeriesRead | null>(null)
  const [busy, setBusy] = useState(false)
  const [firstUsed, setFirstUsed] = useState(false)
  const [status, setStatus] = useState('尚未取得來源。七股每日淨超與累計均未驗證。')
  const pending = useRef(false), firstLatch = useRef(false)
  function mask() { setRead(null); setStatus('原始條件未准入，資料不可用。請套用有效條件後明確讀取已持有來源。') }
  async function action(capture: boolean, c: SeriesControls) {
    if (pending.current || !validSeriesControls(c) || capture && firstLatch.current) return
    pending.current = true
    setBusy(true)
    setRead(null)
    if (capture) { firstLatch.current = true; setFirstUsed(true) }
    try {
      const response = await fetch(SERIES_API + (capture ? '/capture' : '') + '?' + new URLSearchParams({ as_of: c.as_of }), capture ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' } : { method: 'GET' })
      if (!response.ok) throw new Error('HTTP ' + response.status)
      const checked = await validateSeries(await response.json())
      if (!checked) throw new Error('來源缺漏或驗證未通過')
      setRead(checked)
      setStatus('七股、42 個窗口總和與全部累計前綴已完整驗證。')
    } catch (error) {
      setRead(null)
      setStatus('資料不可用：' + (error instanceof Error ? error.message : '讀取失敗') + '。請明確重新讀取；切換條件或返回不會恢復舊值。')
    } finally { pending.current = false; setBusy(false) }
  }
  return <SeriesContext.Provider value={{ read, busy, firstUsed, status, mask, action }}>{children}</SeriesContext.Provider>
}
const investorLabels: Record<SeriesInvestor, string> = { foreign: '外資及陸資（不含外資自營商）', trust: '投信', dealer: '自營商' }
const signed = (value: string) => value !== '0' && !value.startsWith('-') ? '+' + value : value

export function SeriesChart({ window, cumulative, onPoint }: { window: SeriesWindow; cumulative?: boolean; onPoint: (point: SeriesPoint) => void }) {
  const geometry = seriesGeometry(window.points, cumulative)
  const title = cumulative ? '窗口累計淨超' : '每日淨超'
  const activate = (event: KeyboardEvent<SVGGElement>, point: SeriesPoint) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onPoint(point) }
  }
  return <figure className="series-chart">
    <figcaption>{title}（股）<span>＋買超　−賣超　虛線為 0</span></figcaption>
    <svg viewBox="0 0 700 190" role="img" aria-label={title + '，圖形為近似比例；精確值見日期表與可操作資料點'}>
      <line x1="15" x2="685" y1={geometry.zero} y2={geometry.zero} className="series-zero-line" />
      <text x="2" y="76" className="series-axis">0</text>
      {cumulative && <polyline points={geometry.values.map((p) => p.x + ',' + p.y).join(' ')} className="series-line" />}
      {window.points.map((point, i) => {
        const { x, y } = geometry.values[i]
        const exact = cumulative ? point.cumulative_shares : point.net_shares
        return <g key={point.date} role="button" tabIndex={0} aria-label={point.date + ' ' + title + ' ' + signed(exact) + ' 股，查看原始列'} onClick={() => onPoint(point)} onKeyDown={(event) => activate(event, point)} className={BigInt(exact) < 0n ? 'series-negative' : 'series-positive'}>
          {!cumulative && <rect x={x - (window.points.length === 5 ? 18 : 9)} y={Math.min(y, 80)} width={window.points.length === 5 ? 36 : 18} height={Math.max(2, Math.abs(80 - y))} />}
          <circle cx={x} cy={y} r={cumulative ? 5 : 4} />
          <title>{point.date + ': ' + signed(exact) + ' 股'}</title>
          <text x={x} y="178" textAnchor="middle" className="series-axis" fontSize={window.points.length === 20 ? 9 : 12}>{point.date.slice(5).replace('-', '/')}</text>
        </g>
      })}
    </svg>
    <p>累計在每個窗口首日前歸零。圖形只作近似定位；點選或用鍵盤開啟精確股數、張數及原始列。</p>
  </figure>
}

export function SeriesEvidence({ point, read }: { point: SeriesPoint; read: SeriesRead }) {
  const receipt = read.receipts.find((r) => r.sha256 === point.receipt_sha256)
  return <section className="series-evidence" aria-label="原始列追溯">
    <h2>{point.date} 原始列 #{point.row_ordinal}</h2>
    <p>每日 {signed(point.net_shares)} 股／{signed(point.net_lots)} 張；窗口累計 {signed(point.cumulative_shares)} 股／{signed(point.cumulative_lots)} 張。{point.net_shares === '0' && '已驗證當日淨超為零。'}</p>
    <dl><dt>原始 receipt SHA256</dt><dd>{point.receipt_sha256}</dd><dt>body SHA256</dt><dd>{point.body_sha256}</dd><dt>來源 URL</dt><dd>{String(receipt?.original.url ?? '')}</dd></dl>
    <div className="series-table-wrap"><table><thead><tr><th>原欄位</th><th>原始字串</th></tr></thead><tbody>{read.policy.sources.daily.header.map((label, i) => <tr key={label}><th>{label}</th><td><code>{point.source_values[i]}</code></td></tr>)}</tbody></table></div>
    <details><summary>原始 canonical receipt</summary><pre>{receipt?.canonical}</pre></details>
  </section>
}

export default function ChipsSeriesPage() {
  const state = useContext(SeriesContext)
  if (!state) throw new Error('series provider required')
  const [params, setParams] = useSearchParams()
  const controls = seriesControls(params)
  const [draft, setDraft] = useState<SeriesControls>(controls)
  const [selected, setSelected] = useState<SeriesPoint | null>(null)
  const rawKey = params.toString()
  useEffect(() => {
    const raw = seriesControls(new URLSearchParams(rawKey))
    setDraft(raw); setSelected(null)
    if (!validSeriesControls(raw)) state.mask()
    if (!rawKey) setParams(new URLSearchParams(raw), { replace: true })
  }, [rawKey])
  const { symbol } = useParams()
  const valid = validSeriesControls(controls)
  const read = valid ? state.read : null
  const stock = read?.stocks.find((s) => s.symbol === symbol)
  const window = stock?.series[controls.investor as SeriesInvestor][controls.horizon]
  const selectedCurrent = window?.points.find((p) => p.date === selected?.date) ?? null
  function apply(event: FormEvent) {
    event.preventDefault()
    setSelected(null)
    setParams(new URLSearchParams(draft))
  }
  return <main className="chips-series-page">
    <header><p className="series-eyebrow">TPEx · 七股 · 2026/10/06</p><h1>每日法人淨超與窗口累計</h1><p>外資不含外資自營商。資料日期截止固定；每日淨超、累計與原始來源一同驗證。</p></header>
    <form className="series-controls" onSubmit={apply} key={params.toString()}>
      <label>截止日期<input type="text" aria-label="截止日期" value={draft.as_of} onChange={(e) => setDraft({ ...draft, as_of: e.target.value })} /></label>
      <label>法人<select aria-label="法人" value={draft.investor} onChange={(e) => setDraft({ ...draft, investor: e.target.value })}>{SERIES_INVESTORS.map((i) => <option key={i} value={i}>{investorLabels[i]}</option>)}</select></label>
      <label>窗口<select aria-label="窗口" value={draft.horizon} onChange={(e) => setDraft({ ...draft, horizon: e.target.value })}><option value="5">最近 5 個交易日</option><option value="20">最近 20 個交易日</option></select></label>
      <button type="submit" disabled={state.busy}>套用條件</button>
    </form>
    <p className="series-current">目前原始條件：as_of={controls.as_of} · investor={controls.investor} · horizon={controls.horizon}</p>
    <div className="series-actions"><button type="button" disabled={state.busy || state.firstUsed || !valid} onClick={() => void state.action(true, controls)}>首次取得來源（僅一次）</button><button type="button" disabled={state.busy || !valid} onClick={() => void state.action(false, controls)}>明確讀取已持有來源</button>{symbol && <Link to={seriesPath(controls)}>返回七股（保留原始條件）</Link>}</div>
    <p role="status" className="series-status">{state.busy ? '正在驗證完整來源，所有數值暫不顯示。' : state.status}</p>
    {!valid && <p className="series-unavailable">此原始條件不在已准入日期／法人／窗口範圍，數值不可用。</p>}
    {!symbol ? <section className="series-cards" aria-label="七股"><p className="series-count">已驗證股數：{read ? '7' : '未知'}</p>{SERIES_SYMBOLS.map((s) => {
      const item = read?.stocks.find((x) => x.symbol === s)
      const summary = item?.series[controls.investor as SeriesInvestor][controls.horizon]
      return <article key={s}><h2>{s} {SERIES_NAMES[s]}</h2>{summary ? <><p>窗口淨超 <strong>{signed(summary.total_shares)} 股</strong></p><p>{signed(summary.total_lots)} 張 {summary.verified_zero ? '· 已驗證淨超為零' : ''}</p><Link to={seriesPath(controls, s)}>查看每日圖與精確日期表</Link></> : <><p>每日淨超／累計不可用</p><button type="button" disabled>完整七股來源驗證後開啟</button></>}</article>
    })}</section> : !window || !read ? <section className="series-unavailable"><h2>{symbol} {SERIES_NAMES[symbol] ?? ''}</h2><p>來源不可用，圖表、精確日期表、原列與日曆均不顯示。</p></section> : <section className="series-detail" aria-label="每日淨超明細">
      <h2>{stock?.symbol} {stock?.name} · {investorLabels[controls.investor as SeriesInvestor]} · {controls.horizon} 日</h2>
      <p>窗口淨超 <strong>{signed(window.total_shares)} 股／{signed(window.total_lots)} 張</strong>；{window.verified_zero ? '已驗證淨超為零' : '已驗證可用'}。累計起點：0 股；{window.points[0].date} 至 {window.points.at(-1)?.date}。</p>
      <SeriesChart window={window} onPoint={setSelected} /><SeriesChart window={window} cumulative onPoint={setSelected} />
      <div className="series-table-wrap"><table aria-label="精確日期淨超與累計"><thead><tr><th>日期</th><th>每日股數</th><th>每日張數</th><th>累計股數</th><th>累計張數</th><th>原列</th></tr></thead><tbody>{window.points.map((p) => <tr key={p.date}><th>{p.date}</th><td>{signed(p.net_shares)}{p.net_shares === '0' && <span> · 已驗證當日淨超為零</span>}</td><td>{signed(p.net_lots)}</td><td>{signed(p.cumulative_shares)}</td><td>{signed(p.cumulative_lots)}</td><td><button type="button" onClick={() => setSelected(p)} aria-label={p.date + ' 查看原始列'}>#{p.row_ordinal}</button></td></tr>)}</tbody></table></div>
      {selectedCurrent && <SeriesEvidence point={selectedCurrent} read={read} />}
      <details className="series-calendar"><summary>完整觀測日曆與來源說明</summary><p>採用 24 日；窗口取最後 {controls.horizon} 日。原觀測 2026/10/07 保留追溯，超過截止而排除；不是個股收盤歷史。</p><p>發布／首次可得／修訂時間未知；不支援歷史 PIT。</p><p>policy：{read.policy_version}</p><p>policy digest：{read.policy_digest}</p><div className="series-table-wrap"><table><thead><tr><th>原觀測日期</th><th>採入</th><th>原列與六欄原字串</th></tr></thead><tbody>{read.calendar.rows.map((r) => <tr key={r.date}><th>{r.date}</th><td>{r.date <= controls.as_of ? '是' : '截止後排除'}</td><td><details><summary>#{r.row_ordinal} 查看日曆原列</summary><dl>{['資料日期', '開市', '最高價', '最低價', '收市', '漲跌'].map((label, i) => <div key={label}><dt>{label}</dt><dd><code>{r.source_values[i]}</code></dd></div>)}<dt>body SHA256</dt><dd>{r.body_sha256}</dd><dt>原始 receipt SHA256</dt><dd>{r.receipt_sha256}</dd></dl><pre>{read.receipts.find((receipt) => receipt.sha256 === r.receipt_sha256)?.canonical}</pre></details></td></tr>)}</tbody></table></div><p>資料提供者：櫃買中心，政府資料開放授權條款第 1 版；原成交統計，尚未反映券商帳號更正。</p></details>
    </section>}
  </main>
}
