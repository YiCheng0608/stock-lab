import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { captureInstitutionalWindows, getSavedPriceChipsFocus } from './api'
import { JOINT_KEYS, jointParams, validJointConditions, validJointFocus, focusTransition, type JointConditions, type JointFocusData, type FocusGeneration } from './savedPriceChipsFocus'
import { validChips1006Read } from './components/StockOverview'
import { formatCanonicalShareLots } from './units'
import { exactTurnoverText, priceFocusDayMoveLabels } from './priceFocus'

function unavailableScopeReason(data: JointFocusData): string | null {
  if (data.status !== 'unavailable') return null
  if (data.reasons.includes('joint_focus_cutoff_not_supported')) return `來源日期 ${data.as_of} 不在本次範圍；只支持 2026-10-06 的 3105、6488。候選數未知。`
  if (data.reasons.some((reason) => reason.includes('not_enabled') || reason.includes('not_admitted') || /_pins?_/.test(reason))) return '此來源使用尚未核定或來源版本不符；本次候選數未知。'
  return null
}

export function SavedPriceChipsFocusResults({ data }: { data: JointFocusData }) {
  const values = Object.fromEntries(JOINT_KEYS.map((key) => [key, data[key]])) as JointConditions
  if (!validJointFocus(data, values)) return <div role="alert">共同來源或條件未通過核對，候選數未知。</div>
  if (data.status === 'unavailable') return <div className="empty" role="status">{unavailableScopeReason(data) ?? `${data.price_ready ? '七股保存來源已核對，尚未取得完整兩股法人來源。' : '共同來源尚未完整核對。'}候選數未知。`}<details><summary>查看讀取原因</summary>{data.reasons.join('、')}</details></div>
  return <><p className="small-note">來源日 {data.as_of} · 已核七股行情與兩股法人，篩選範圍為 3105、6488；符合 {data.count} 檔。其餘五股不在本次法人範圍。</p>
    {data.count === 0 ? <div className="empty" role="status">兩股完整來源已核對，沒有同時符合價格與法人條件的標的；這是此範圍的零候選。</div> : <div className="focus-grid">{data.items.map((item) => <article className="focus-card" key={item.symbol}>
      <strong>{item.symbol} {item.name}</strong><p>成交 {formatCanonicalShareLots(item.volume_exact, 1, true)} 張 ≥ {item.min_lots} 張</p>
      <p>成交金額 {exactTurnoverText(item.turnover_exact)} 元 ≥ {exactTurnoverText(item.min_turnover)} 元</p>
      <p>{priceFocusDayMoveLabels[item.day_move]}：開盤 {item.open_exact}／收盤 {item.close_exact} 元；本日振幅門檻 ≥ {item.min_range_pct}%</p>
      <p>{({ foreign: '外資及陸資（不含外資自營商）', trust: '投信', dealer: '自營商' } as Record<string, string>)[item.investor]} {item.horizon} 交易日淨買賣超 {formatCanonicalShareLots(item.net_shares, 1, true)} 張 ≥ {item.min_net_lots} 張</p>
      <Link className="text-link focus-stock-link" to={item.detail_url}>查看同截止個股與來源</Link>
      <details className="technical-details"><summary>精確數值與來源版本</summary><div>窗口淨超 {item.net_shares} 股 · 門檻 {item.min_net_shares} 股 · 含等號</div><div>{data.policy_version}</div><div>價格保存 UTC {data.price!.reads[0].price_saved.storage_provenance!.saved_at}；法人是本次新取得，發布、首次可得與修訂時間未知。</div></details>
    </article>)}</div>}</>
}

export function SavedPriceChipsFocusPage() {
  const [params, setParams] = useSearchParams()
  const current = jointParams(params), key = params.toString()
  const [draft, setDraft] = useState<JointConditions>(() => Object.fromEntries(JOINT_KEYS.map((field) => [field, params.get(field) ?? ''])) as JointConditions)
  useEffect(() => setDraft(Object.fromEntries(JOINT_KEYS.map((field) => [field, params.get(field) ?? ''])) as JointConditions), [key])
  const route = useRef({ key, generation: 0 })
  if (route.current.key !== key) route.current = { key, generation: route.current.generation + 1 }
  const token = `${route.current.generation}:${key}`
  const generation = useRef<FocusGeneration>({ token, epoch: 0, failure: null, price: false, chips: false })
  if (generation.current.token !== token) generation.current = { token, epoch: 0, failure: null, price: false, chips: false }
  const [read, setRead] = useState<{ token: string; data: JointFocusData } | null>(null)
  const [notice, setNotice] = useState<{ token: string; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null), pending = useRef(false)
  const clean = current !== null && JOINT_KEYS.every((field) => current[field] === draft[field])
  const enabled = clean && validJointConditions(draft)
  const present = enabled && read?.token === token && !generation.current.failure ? read.data : undefined
  const changeDraft = (field: keyof JointConditions, value: string) => {
    generation.current = { token, epoch: generation.current.epoch + 1, failure: null, price: false, chips: false }
    setRead(null); setNotice(null); setDraft((previous) => ({ ...previous, [field]: value }))
  }
  const fail = () => { generation.current = focusTransition(generation.current, token, generation.current.epoch, 'failure'); setRead(null); setNotice({ token, text: '共同來源讀取或核對失敗，候選數未知。請明示重新讀取兩來源；失敗的來源取得不重試。' }) }
  const reopen = async () => {
    if (!enabled || !current || pending.current) return
    const epoch = generation.current.epoch
    pending.current = true; setBusy(token); setRead(null); setNotice(null)
    try {
      const data = await getSavedPriceChipsFocus(current)
      if (generation.current.token !== token || generation.current.epoch !== epoch) return
      if (!validJointFocus(data, current)) { fail(); return }
      if (data.status === 'available') generation.current = focusTransition(generation.current, token, epoch, 'joint')
      else if (data.price_ready && data.can_capture) generation.current = focusTransition(generation.current, token, epoch, 'price')
      else if (unavailableScopeReason(data)) generation.current = { token, epoch, failure: null, price: false, chips: false }
      else { fail(); return }
      setRead({ token, data })
    } catch { if (generation.current.token === token && generation.current.epoch === epoch) fail() }
    finally { pending.current = false; setBusy((value) => value === token ? null : value) }
  }
  const capture = async () => {
    if (!enabled || !current || !present?.can_capture || pending.current) return
    const epoch = generation.current.epoch
    pending.current = true; setBusy(token); setRead(null); setNotice(null)
    try {
      const result = await captureInstitutionalWindows('TPEx', '3105', current.as_of)
      if (generation.current.token !== token || generation.current.epoch !== epoch) return
      if (result.status !== 'available' || !validChips1006Read(result, 'TPEx', '3105', current.as_of)) { fail(); return }
      generation.current = focusTransition(generation.current, token, epoch, 'chips')
      setNotice({ token, text: '本次法人來源已取得。請按「讀取保存來源並篩選」，明示核對新快照與已取得法人；尚未列候選。' })
    } catch { if (generation.current.token === token && generation.current.epoch === epoch) fail() }
    finally { pending.current = false; setBusy((value) => value === token ? null : value) }
  }
  const input = (field: keyof JointConditions, label: string, type = 'text') => <label>{label}<input name={field} type={type} required value={draft[field]} onChange={(event) => changeDraft(field, event.currentTarget.value)} /></label>
  return <div className="page"><Link className="back-link" to="/">← 回到市場總覽</Link><section className="panel official-event-focus"><h1>保存行情與法人條件關注</h1>
    <p>2026-10-06 3105 穩懋／6488 環球晶。四價格條件與選定法人窗口淨超門檻同時成立才列入，門檻含等號；依代碼排序，不是排名或買賣建議。</p>
    <form className="overview-cutoff-control" onSubmit={(event) => { event.preventDefault(); if (!validJointConditions(draft) || pending.current) return; setRead(null); setNotice(null); setParams(new URLSearchParams(draft)) }}>
      {input('as_of', '來源日期', 'date')}{input('min_lots', '最小成交張數')}{input('min_turnover', '最小成交金額（元）')}{input('min_range_pct', '最小本日振幅（%）')}
      <label>單日方向<select name="day_move" value={draft.day_move} onChange={(e) => changeDraft('day_move', e.currentTarget.value)}><option value="">請選擇</option>{Object.entries(priceFocusDayMoveLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>法人<select name="investor" value={draft.investor} onChange={(e) => changeDraft('investor', e.currentTarget.value)}><option value="">請選擇</option><option value="foreign">外資及陸資（不含外資自營商）</option><option value="trust">投信</option><option value="dealer">自營商</option></select></label>
      <label>交易日窗口<select name="horizon" value={draft.horizon} onChange={(e) => changeDraft('horizon', e.currentTarget.value)}><option value="">請選擇</option><option value="5">5 交易日</option><option value="20">20 交易日</option></select></label>{input('min_net_lots', '最小淨買賣超（張，可負值）')}
      <button type="submit" className="secondary-button" disabled={!validJointConditions(draft) || busy === token}>套用條件</button>
      <button type="button" className="secondary-button" disabled={!enabled || busy === token} onClick={() => void reopen()}>讀取保存來源並篩選</button>
      <button type="button" className="secondary-button" disabled={!enabled || !present?.can_capture || busy === token} onClick={() => void capture()}>首次取得法人來源</button>
    </form>
    {!validJointConditions(draft) && <p role="status">請填完整八條件；淨超張數可負、最多三位小數，不接受正號、逗號、前導零、負零或空白。</p>}
    {busy === token ? <p role="status">核對來源中…</p> : notice?.token === token ? <div className="warning-box" role="alert">{notice.text}</div> : present ? <SavedPriceChipsFocusResults data={present} /> : <div className="empty" role="status">目前條件尚未完整明示讀取，候選數未知。套用、切股與返回都不自動讀取來源。</div>}
    <p className="small-note">發布、首次可得與修訂時間未知；不支持 PIT、趨勢、策略或交易計畫。</p>
  </section></div>
}
