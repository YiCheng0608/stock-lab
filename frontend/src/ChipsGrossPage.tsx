import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { GROSS_API, GROSS_INVESTORS, GROSS_NAMES, GROSS_SYMBOLS, grossControls, grossGeometry, grossPath, validGrossControls, validateGross } from './chipsGross'
import type { GrossControls, GrossInvestor, GrossPoint, GrossRead, GrossWindow } from './chipsGross'
import './ChipsSeriesPage.css'

type Held = { read: GrossRead | null; busy: boolean; firstUsed: boolean; status: string; mask: () => void; action: (capture: boolean, c: GrossControls) => Promise<void> }
const GrossContext = createContext<Held | null>(null)
export function ChipsGrossProvider({ children }: { children: ReactNode }) {
  const [read, setRead] = useState<GrossRead | null>(null)
  const [busy, setBusy] = useState(false)
  const [firstUsed, setFirstUsed] = useState(false)
  const [status, setStatus] = useState('尚未取得來源。七股每日買進、賣出與淨超均未驗證。')
  const pending = useRef(false), firstLatch = useRef(false), epoch = useRef(0)
  function mask() { epoch.current++; setRead(null); setStatus('原始條件未准入，資料不可用。請套用有效條件後明確讀取已持有來源。') }
  async function action(capture: boolean, c: GrossControls) {
    if (pending.current || !validGrossControls(c) || capture && firstLatch.current) return
    pending.current = true
    const token = ++epoch.current
    setBusy(true)
    setRead(null)
    if (capture) { firstLatch.current = true; setFirstUsed(true) }
    try {
      const response = await fetch(GROSS_API + (capture ? '/capture' : '') + '?' + new URLSearchParams({ as_of: c.as_of }), capture ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' } : { method: 'GET' })
      if (!response.ok) throw new Error('HTTP ' + response.status)
      const checked = await validateGross(await response.json())
      if (!checked) throw new Error('來源缺漏或驗證未通過')
      if (token !== epoch.current) return
      setRead(checked)
      setStatus('七股買進、賣出與淨超，以及每個窗口累計均已完整驗證。')
    } catch (error) {
      setRead(null)
      setStatus('資料不可用：' + (error instanceof Error ? error.message : '讀取失敗') + '。請明確重新讀取；切換條件或返回不會恢復舊值。')
    } finally { pending.current = false; setBusy(false) }
  }
  return <GrossContext.Provider value={{ read, busy, firstUsed, status, mask, action }}>{children}</GrossContext.Provider>
}
const investorLabels: Record<GrossInvestor, string> = { foreign: '外資及陸資（不含外資自營商）', trust: '投信', dealer: '自營商' }
const signed = (value: string) => value !== '0' && !value.startsWith('-') ? '+' + value : value

export function GrossChart({ window, cumulative, onPoint }: { window: GrossWindow; cumulative?: boolean; onPoint: (point: GrossPoint) => void }) {
  const bound = Math.max(1, ...window.points.flatMap((p) => [Number(cumulative ? p.cumulative_buy_shares : p.buy_shares), Number(cumulative ? p.cumulative_sell_shares : p.sell_shares)]))
  const buy = grossGeometry(window.points, cumulative, 'buy', bound), sell = grossGeometry(window.points, cumulative, 'sell', bound)
  const title = cumulative ? '窗口累計買進與賣出' : '每日買進與賣出'
  const activate = (event: KeyboardEvent<SVGGElement>, point: GrossPoint) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onPoint(point) }
  }
  return <figure className="series-chart">
    <figcaption>{title}（股）<span style={{ color: '#167c72' }}>買進（綠）</span><span style={{ color: '#b14c52' }}>賣出（紅）</span></figcaption>
    <svg viewBox="0 0 700 190" role="img" aria-label={title + '，圖形為近似比例；精確值見日期表與可操作資料點'}>
      <line x1="15" x2="685" y1={buy.zero} y2={buy.zero} className="series-zero-line" />
      <text x="2" y="146" className="series-axis">0</text>
      {cumulative && <><polyline points={buy.values.map((p) => p.x + ',' + p.y).join(' ')} fill="none" stroke="#167c72" strokeWidth="2" /><polyline points={sell.values.map((p) => p.x + ',' + p.y).join(' ')} fill="none" stroke="#b14c52" strokeWidth="2" strokeDasharray="5 3" /></>}
      {window.points.map((point, i) => {
        const { x, y } = buy.values[i], sellY = sell.values[i].y, width = window.points.length === 5 ? 14 : 6
        const buyExact = cumulative ? point.cumulative_buy_shares : point.buy_shares, sellExact = cumulative ? point.cumulative_sell_shares : point.sell_shares
        return <g key={point.date} role="button" tabIndex={0} aria-label={point.date + ' ' + title + ' 買進 ' + buyExact + ' 股，賣出 ' + sellExact + ' 股，查看原始列'} onClick={() => onPoint(point)} onKeyDown={(event) => activate(event, point)}>
          {!cumulative && <><rect x={x - width - 1} y={y} width={width} height={Math.max(2, buy.zero - y)} fill="#167c72" /><rect x={x + 1} y={sellY} width={width} height={Math.max(2, sell.zero - sellY)} fill="#b14c52" /></>}
          <circle cx={x - (cumulative ? 0 : width / 2)} cy={y} r="4" fill="#167c72" /><circle cx={x + (cumulative ? 0 : width / 2)} cy={sellY} r="4" fill="#b14c52" />
          <title>{point.date + ': 買進 ' + buyExact + ' 股，賣出 ' + sellExact + ' 股'}</title>
          <text x={x} y="178" textAnchor="middle" className="series-axis" fontSize={window.points.length === 20 ? 9 : 12}>{point.date.slice(5).replace('-', '/')}</text>
        </g>
      })}
    </svg>
    <p>累計在每個窗口首日前歸零。圖形只作近似定位；點選或用鍵盤開啟精確股數、張數及原始列。</p>
  </figure>
}

export function GrossEvidence({ point, read }: { point: GrossPoint; read: GrossRead }) {
  const receipt = read.receipts.find((r) => r.sha256 === point.receipt_sha256)
  return <section className="series-evidence" aria-label="原始列追溯">
    <h2>{point.date} 原始列 #{point.row_ordinal}</h2>
    <p>每日買進 {point.buy_shares} 股／{point.buy_lots} 張 − 賣出 {point.sell_shares} 股／{point.sell_lots} 張 = 淨超 {signed(point.net_shares)} 股／{signed(point.net_lots)} 張。</p>
    <p>窗口累計買進 {point.cumulative_buy_shares} 股／{point.cumulative_buy_lots} 張 − 賣出 {point.cumulative_sell_shares} 股／{point.cumulative_sell_lots} 張 = 淨超 {signed(point.cumulative_net_shares)} 股／{signed(point.cumulative_net_lots)} 張。</p>
    {(point.buy_shares === '0' || point.sell_shares === '0') && <p>已驗證當日{point.buy_shares === '0' ? '買進' : ''}{point.buy_shares === '0' && point.sell_shares === '0' ? '及' : ''}{point.sell_shares === '0' ? '賣出' : ''}為零。</p>}
    <dl><dt>原始 receipt SHA256</dt><dd>{point.receipt_sha256}</dd><dt>body SHA256</dt><dd>{point.body_sha256}</dd><dt>來源 URL</dt><dd>{String(receipt?.original.url ?? '')}</dd></dl>
    <div className="series-table-wrap"><table><thead><tr><th>原欄位</th><th>原始字串</th></tr></thead><tbody>{read.policy.sources.daily.header.map((label, i) => <tr key={label}><th>{label}</th><td><code>{point.source_values[i]}</code></td></tr>)}</tbody></table></div>
    <details><summary>原始 canonical receipt</summary><pre>{receipt?.canonical}</pre></details>
  </section>
}

export default function ChipsGrossPage() {
  const state = useContext(GrossContext)
  if (!state) throw new Error('series provider required')
  const [params, setParams] = useSearchParams()
  const controls = grossControls(params)
  const [draft, setDraft] = useState<GrossControls>(controls)
  const [selected, setSelected] = useState<GrossPoint | null>(null)
  const rawKey = params.toString()
  const { symbol } = useParams()
  useEffect(() => {
    const raw = grossControls(new URLSearchParams(rawKey))
    setDraft(raw); setSelected(null)
    if (!validGrossControls(raw) || symbol && !GROSS_NAMES[symbol]) state.mask()
    if (!rawKey) setParams(new URLSearchParams(raw), { replace: true })
  }, [rawKey, symbol])
  const valid = validGrossControls(controls) && (!symbol || Boolean(GROSS_NAMES[symbol]))
  const read = valid ? state.read : null
  const stock = read?.stocks.find((s) => s.symbol === symbol)
  const window = stock?.series[controls.investor as GrossInvestor][controls.horizon]
  const selectedCurrent = window?.points.find((p) => p.date === selected?.date) ?? null
  function apply(event: FormEvent) {
    event.preventDefault()
    setSelected(null)
    setParams(new URLSearchParams(draft))
  }
  return <main className="chips-series-page">
    <header><p className="series-eyebrow">TPEx · 七股 · 2026/10/06</p><h1>法人買進、賣出與窗口累計</h1><p>外資不含外資自營商。買進 − 賣出 = 淨超；每日值、窗口累計與原始來源一同驗證。</p></header>
    <form className="series-controls" onSubmit={apply} key={params.toString()}>
      <label>截止日期<input type="text" aria-label="截止日期" value={draft.as_of} onChange={(e) => setDraft({ ...draft, as_of: e.target.value })} /></label>
      <label>法人<select aria-label="法人" value={draft.investor} onChange={(e) => setDraft({ ...draft, investor: e.target.value })}>{GROSS_INVESTORS.map((i) => <option key={i} value={i}>{investorLabels[i]}</option>)}</select></label>
      <label>窗口<select aria-label="窗口" value={draft.horizon} onChange={(e) => setDraft({ ...draft, horizon: e.target.value })}><option value="5">最近 5 個交易日</option><option value="20">最近 20 個交易日</option></select></label>
      <button type="submit" disabled={state.busy}>套用條件</button>
    </form>
    <p className="series-current">目前原始條件：as_of={controls.as_of} · investor={controls.investor} · horizon={controls.horizon}</p>
    <div className="series-actions"><button type="button" disabled={state.busy || state.firstUsed || !valid} onClick={() => void state.action(true, controls)}>首次取得來源（僅一次）</button><button type="button" disabled={state.busy || !valid} onClick={() => void state.action(false, controls)}>明確讀取已持有來源</button>{symbol && <Link to={grossPath(controls)}>返回七股（保留原始條件）</Link>}</div>
    <p role="status" className="series-status">{state.busy ? '正在驗證完整來源，所有數值暫不顯示。' : state.status}</p>
    {!valid && <p className="series-unavailable">此原始條件不在已准入日期／法人／窗口範圍，數值不可用。</p>}
    {!symbol ? <section className="series-cards" aria-label="七股"><p className="series-count">已驗證股數：{read ? '7' : '未知'}</p>{GROSS_SYMBOLS.map((s) => {
      const item = read?.stocks.find((x) => x.symbol === s)
      const summary = item?.series[controls.investor as GrossInvestor][controls.horizon]
      return <article key={s}><h2>{s} {GROSS_NAMES[s]}</h2>{summary ? <><p>窗口買進 <strong>{summary.total_buy_shares} 股／{summary.total_buy_lots} 張</strong></p><p>窗口賣出 <strong>{summary.total_sell_shares} 股／{summary.total_sell_lots} 張</strong></p><p>淨超 {signed(summary.total_net_shares)} 股／{signed(summary.total_net_lots)} 張</p><Link to={grossPath(controls, s)}>查看每日買賣圖與精確日期表</Link></> : <><p>每日買進／賣出／累計不可用</p><button type="button" disabled>完整七股來源驗證後開啟</button></>}</article>
    })}</section> : !window || !read ? <section className="series-unavailable"><h2>{symbol} {GROSS_NAMES[symbol] ?? ''}</h2><p>{!GROSS_NAMES[symbol] ? '此標的不在核定七股範圍。' : '來源不可用。'}圖表、精確日期表、原列與日曆均不顯示。</p></section> : <section className="series-detail" aria-label="每日買進賣出明細">
      <h2>{stock?.symbol} {stock?.name} · {investorLabels[controls.investor as GrossInvestor]} · {controls.horizon} 日</h2>
      <p>窗口買進 <strong>{window.total_buy_shares} 股／{window.total_buy_lots} 張</strong> − 賣出 <strong>{window.total_sell_shares} 股／{window.total_sell_lots} 張</strong> = 淨超 <strong>{signed(window.total_net_shares)} 股／{signed(window.total_net_lots)} 張</strong>。累計起點：買進、賣出、淨超各 0 股；{window.points[0].date} 至 {window.points.at(-1)?.date}。</p>
      <GrossChart window={window} onPoint={setSelected} /><GrossChart window={window} cumulative onPoint={setSelected} />
      <div className="series-table-wrap"><table aria-label="精確日期買進賣出淨超與累計"><thead><tr><th>日期</th>{['買進', '賣出', '淨超', '累計買進', '累計賣出', '累計淨超'].map((label) => <th key={label}>{label}（股／張）</th>)}<th>原列</th></tr></thead><tbody>{window.points.map((p) => <tr key={p.date}><th>{p.date}</th>{(['buy', 'sell', 'net', 'cumulative_buy', 'cumulative_sell', 'cumulative_net'] as const).map((component) => <td key={component}>{signed(p[`${component}_shares`])}<br />{signed(p[`${component}_lots`])}{(component === 'buy' || component === 'sell') && p[`${component}_shares`] === '0' && <span> · 已驗證零</span>}</td>)}<td><button type="button" onClick={() => setSelected(p)} aria-label={p.date + ' 查看原始列'}>#{p.row_ordinal}</button></td></tr>)}</tbody></table></div>
      {selectedCurrent && <GrossEvidence point={selectedCurrent} read={read} />}
      <details className="series-calendar"><summary>完整觀測日曆與來源說明</summary><p>完整返回 {read.calendar.rows.length} 日，採用 {read.calendar.adopted_dates.length} 日；窗口取最後 {controls.horizon} 日。截止後原列全部保留追溯、排除計算。此為指數觀測日曆。</p><p>發布／首次可得／修訂時間未知；不支援歷史 PIT。</p><p>來源版本：{read.policy.sources.index.source_version}；{read.policy.sources.daily.source_version}</p><div className="series-table-wrap"><table><thead><tr><th>原觀測日期</th><th>採入</th><th>原列與六欄原字串</th></tr></thead><tbody>{read.calendar.rows.map((r) => <tr key={r.date}><th>{r.date}</th><td>{r.date <= controls.as_of ? '是' : '截止後排除'}</td><td><details><summary>#{r.row_ordinal} 查看日曆原列</summary><dl>{['資料日期', '開市', '最高價', '最低價', '收市', '漲跌'].map((label, i) => <div key={label}><dt>{label}</dt><dd><code>{r.source_values[i]}</code></dd></div>)}<dt>body SHA256</dt><dd>{r.body_sha256}</dd><dt>原始 receipt SHA256</dt><dd>{r.receipt_sha256}</dd></dl><pre>{read.receipts.find((receipt) => receipt.sha256 === r.receipt_sha256)?.canonical}</pre></details></td></tr>)}</tbody></table></div></details>
    </section>}
    <footer className="series-calendar"><p>資料提供者：櫃買中心（Taipei Exchange, TPEx），2026。資料集 11391「Index historical data」及 11856「Information on the trading details of OTC stocks three major institutional investors」。依<a href="https://data.gov.tw/license">政府資料開放授權條款第 1 版</a>使用；原列完整性及來源追溯保留。觀測日：2026/10/08；發布、首次可得及修訂時間未知，不支援歷史 PIT。原成交統計尚未反映券商帳號更正。</p></footer>
  </main>
}
