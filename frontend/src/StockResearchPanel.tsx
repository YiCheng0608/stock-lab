import { Link } from 'react-router-dom'
import { groupDisplayName, researchRequirementLabel } from './presentation'
import { formatTableChip } from './units'
import type { ActionSummary, EventRow, InstrumentDetail, NewsItem } from './types'
import { eventTimeLabels, formatResearchDate, formatResearchDateTime, isTemporaryIndustryGroupName, newsTimeLabels, recentByDate, summarizeStockResearch } from './stockResearch'

type StockDetailData = InstrumentDetail & { news: NewsItem[]; decision_summary?: ActionSummary | null }

const canonicalStrategies = ['breakout_v1', 'pullback_v1'] as const
const readStates = ['known', 'missing', 'invalid']
const object = (value: unknown): value is Record<string, unknown> => value != null && typeof value === 'object' && !Array.isArray(value)
const identity = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const dateOnly = (value: unknown): value is string => typeof value === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)
  && Number(value.slice(0, 4)) > 0 && !Number.isNaN(new Date(value + 'T00:00:00Z').getTime()) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string') && new Set(value).size === value.length
const displayStrings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string')
const positive = (value: unknown) => value === null || (typeof value === 'number' && Number.isFinite(value) && value > 0)
const essentialReadFields = ['id', 'instrument_id', 'signal_key', 'signal_date', 'strategy_version_id', 'status', 'data_quality', 'strategy.id', 'strategy.name', 'strategy.version']
const metadataSchema = [...essentialReadFields, 'entry_type', 'reference_entry', 'pullback_low', 'pullback_high', 'breakout_price', 'invalid_price', 'target_1', 'target_2', 'execution_price', 'confidence', 'rationale', 'data_cutoff', 'source_report', 'earliest_execution_date', 'execution_date', 'created_at', 'rule_evidence', 'strategy.kind', 'strategy.config_json', 'strategy.canonical_config_snapshot', 'strategy.active', 'strategy.created_at']

function validRead(value: unknown, emptySlot = false): boolean {
  if (!object(value) || typeof value.status !== 'string' || !readStates.includes(value.status) || !strings(value.invalid_fields) || !strings(value.missing_fields) || !object(value.metadata_fields)
    || !Object.values(value.metadata_fields).every((state) => typeof state === 'string' && readStates.includes(state))) return false
  if (!emptySlot && (!metadataSchema.every((key) => readStates.includes(String((value.metadata_fields as Record<string, unknown>)[key])))
    || !value.invalid_fields.every((key) => (value.metadata_fields as Record<string, unknown>)[key] === 'invalid')
    || !value.missing_fields.every((key) => (value.metadata_fields as Record<string, unknown>)[key] === 'missing')
    || (value.status === 'known' && !essentialReadFields.every((key) => (value.metadata_fields as Record<string, unknown>)[key] === 'known')))) return false
  return value.status === 'known' ? value.invalid_fields.length === 0 && value.missing_fields.length === 0
    : value.status === 'invalid' ? value.invalid_fields.length > 0 : value.invalid_fields.length === 0 && value.missing_fields.length > 0
}

function finiteJson(value: unknown, nodeLimit = 16384, depthLimit = 32, generatedRootKey?: string): boolean {
  const pending: Array<[unknown, number]> = [[value, 0]]
  let nodes = 0
  while (pending.length) {
    const [item, depth] = pending.pop()!
    if (++nodes > nodeLimit || depth > depthLimit) return false
    if (typeof item === 'number' && !Number.isFinite(item)) return false
    if (Array.isArray(item)) {
      if (item.length > nodeLimit - nodes - pending.length) return false
      for (const child of item) pending.push([child, depth + 1])
    } else if (object(item)) {
      const keys = Object.keys(item).filter((key) => depth !== 0 || key !== generatedRootKey)
      if (keys.length * 2 > nodeLimit - nodes - pending.length) return false
      for (const key of keys) { pending.push([key, depth + 1]); pending.push([item[key], depth + 1]) }
    }
    else if (item !== null && !['string', 'number', 'boolean'].includes(typeof item)) return false
  }
  return true
}

function finiteEvidence(value: unknown, semantics: unknown): boolean {
  if (!object(value) || !object(value.level_semantics) || !object(semantics)
    || !finiteJson(value.level_semantics, 512, 8) || !finiteJson(semantics, 512, 8)) return false
  // The API attaches this bounded sibling after the raw field's own limits.
  return JSON.stringify(value.level_semantics) === JSON.stringify(semantics)
    && finiteJson(value, 16384, 32, 'level_semantics')
}

export function validStockResearchRead(data: StockDetailData): boolean {
  const state = data.research_read
  if (state === undefined) return true
  if (!object(state) || state.version !== 'stock-research-read/v1' || state.verification !== 'stored_value_syntax_only'
    || !readStates.includes(state.status) || state.window_limit !== 20 || !count(state.candidate_count) || state.candidate_count > 20
    || !count(state.scanned_count) || !count(state.future_count) || state.future_count > state.scanned_count
    || !count(state.unlocated_count) || !count(state.identity_unlocated_count)
    || state.unlocated_count > state.scanned_count || state.identity_unlocated_count > state.scanned_count
    || !Array.isArray(data.signals) || state.candidate_count !== data.signals.length
    || state.candidate_count > state.scanned_count - state.future_count || !Array.isArray(state.candidate_order)
    || state.candidate_order.length !== data.signals.length || !object(state.latest)
    || Object.keys(state.latest).length !== 2 || !strings(state.blocked_strategies)
    || !state.blocked_strategies.every((name) => canonicalStrategies.includes(name as typeof canonicalStrategies[number]))) return false
  for (const [amount, id] of [[state.unlocated_count, state.unlocated_signal_id], [state.identity_unlocated_count, state.identity_unlocated_signal_id]]) {
    if (amount === 0 ? id !== null : !identity(id)) return false
  }
  const ids = new Set<number>()
  let previous: InstrumentDetail['signals'][number] | undefined
  for (const [index, row] of data.signals.entries()) {
    if (!object(row) || !identity(row.id) || ids.has(row.id) || state.candidate_order[index] !== row.id || row.instrument_id !== data.instrument.id
      || !validRead(row.signal_read) || !object(row.strategy) || (row.signal_date !== null && !dateOnly(row.signal_date))) return false
    ids.add(row.id)
    const fields = row.signal_read.metadata_fields
    if (!['id', 'instrument_id', 'signal_key', 'signal_date', 'strategy_version_id', 'status', 'data_quality', 'strategy.id', 'strategy.name', 'strategy.version', 'rule_evidence', 'data_cutoff', 'earliest_execution_date'].every((key) => readStates.includes(fields[key]))) return false
    if ((fields.signal_date === 'known') !== (row.signal_date !== null) || (row.strategy_version_id !== null && !identity(row.strategy_version_id))) return false
    for (const key of ['signal_key', 'status', 'data_quality', 'entry_type', 'rationale', 'data_cutoff', 'source_report'] as const) {
      if (row[key] !== null && typeof row[key] !== 'string') return false
      if ((fields[key] === 'known') !== (row[key] !== null)) return false
    }
    for (const key of ['reference_entry', 'pullback_low', 'pullback_high', 'breakout_price', 'invalid_price', 'target_1', 'target_2', 'execution_price'] as const) {
      if (!positive(row[key]) || (fields[key] === 'known') !== (row[key] !== null)) return false
    }
    for (const key of ['name', 'version', 'kind'] as const) if (row.strategy[key] !== null && typeof row.strategy[key] !== 'string') return false
    if (row.confidence !== null && (typeof row.confidence !== 'number' || !Number.isFinite(row.confidence))) return false
    if (row.earliest_execution_date !== null && !dateOnly(row.earliest_execution_date)) return false
    if (row.execution_date !== null && !dateOnly(row.execution_date)) return false
    if (row.rule_evidence !== null && !finiteEvidence(row.rule_evidence, row.level_semantics)) return false
    if ((fields.rule_evidence === 'known') !== (row.rule_evidence !== null)) return false
    if (row.strategy.canonical_config_snapshot !== null && (!object(row.strategy.canonical_config_snapshot) || !finiteJson(row.strategy.canonical_config_snapshot))) return false
    if (previous?.signal_date && row.signal_date && (row.signal_date > previous.signal_date || (row.signal_date === previous.signal_date && row.id > previous.id))) return false
    if (row.signal_date) previous = row
  }
  const blocked: string[] = []
  for (const name of canonicalStrategies) {
    const slot = state.latest[name]
    if (!object(slot) || !validRead(slot.read, slot.signal_id === null) || (slot.signal_date !== null && !dateOnly(slot.signal_date))) return false
    if (slot.signal_id === null) {
      if (slot.signal_date !== null || slot.strategy_version_id !== null || slot.read.status !== 'missing' || slot.read.missing_fields.join() !== 'signal' || Object.keys(slot.read.metadata_fields).length) return false
    } else {
      if (!identity(slot.signal_id) || (slot.strategy_version_id !== null && !identity(slot.strategy_version_id))) return false
      if ((slot.read.metadata_fields.signal_date === 'known') !== (slot.signal_date !== null)
        || (slot.read.metadata_fields.strategy_version_id === 'known') !== (slot.strategy_version_id !== null)) return false
      const visible = data.signals.find((row) => row.strategy.name === name)
      if (visible && (visible.id !== slot.signal_id || visible.signal_date !== slot.signal_date || visible.strategy_version_id !== slot.strategy_version_id
        || JSON.stringify(visible.signal_read) !== JSON.stringify(slot.read))) return false
      if (slot.read.status !== 'known') blocked.push(name)
    }
  }
  const instrumentBlocked = state.unlocated_count > 0 || state.identity_unlocated_count > 0
  const invalid = instrumentBlocked || data.signals.some((row) => row.signal_read.status !== 'known')
  return state.status === (invalid ? 'invalid' : data.signals.length ? 'known' : 'missing')
    && state.decision_block_scope === (instrumentBlocked ? 'instrument' : blocked.length ? 'slots' : 'none')
    && state.blocked_strategies.join() === blocked.join()
}

export function stockResearchAction(data: StockDetailData): ActionSummary | null {
  if (!validStockResearchRead(data)) return null
  const action = data.decision_summary
  if (!action || !object(action) || !['conditional_entry', 'wait_breakout', 'wait_pullback', 'hold_observe', 'reduce_exit', 'data_insufficient', 'manual_review', 'no_condition'].includes(action.action_state)
    || !['complete', 'partial', 'missing'].includes(action.data_quality)
    || !Array.isArray(action.strategies) || !Array.isArray(action.missing_data_priority) || !displayStrings(action.reasons) || !displayStrings(action.conflicts)
    || (action.display_reasons !== undefined && !displayStrings(action.display_reasons))) return null
  for (const key of ['trigger_price', 'entry_low', 'entry_high', 'invalid_price', 'stop_price', 'target_1', 'target_2'] as const) if (!positive(action[key])) return null
  if (action.risk_reward !== null && (typeof action.risk_reward !== 'number' || !Number.isFinite(action.risk_reward))) return null
  if (data.research_read === undefined) return action
  const state = data.research_read
  if (JSON.stringify(action.research_read) !== JSON.stringify(state)) return null
  if (state.decision_block_scope === 'instrument' && action.action_state !== 'data_insufficient') return null
  const seen = new Set<string>()
  for (const result of action.strategies) {
    if (!object(result) || !canonicalStrategies.includes(result.strategy as typeof canonicalStrategies[number]) || seen.has(result.strategy) || !validRead(result.signal_read)) return null
    seen.add(result.strategy)
    const slot = state.latest[result.strategy as typeof canonicalStrategies[number]]
    if (result.signal_id !== slot.signal_id || result.signal_date !== slot.signal_date || JSON.stringify(result.signal_read) !== JSON.stringify(slot.read)) return null
  }
  if (['conditional_entry', 'wait_breakout', 'wait_pullback', 'hold_observe', 'reduce_exit'].includes(action.action_state)) {
    const primary = action.strategies.find((result) => result.strategy === action.primary_strategy)
    if (!primary && action.action_state === 'hold_observe' && action.primary_strategy === null
      && ['trigger_price', 'entry_low', 'entry_high', 'invalid_price', 'stop_price', 'target_1', 'target_2'].every((key) => action[key as keyof ActionSummary] === null)
      && action.strategies.some((result) => result.status === 'observation' && result.data_quality === 'complete' && result.signal_read?.status === 'known' && strings(result.missing) && !result.missing.length)) return action
    if (!primary || primary.signal_read?.status !== 'known' || state.blocked_strategies.includes(primary.strategy) || !strings(primary.missing) || primary.missing.length) return null
    if (!object(primary.levels) || !Object.values(primary.levels).every(positive)) return null
  }
  return action
}

function ResearchCandidates({ data }: { data: StockDetailData }) {
  if (!validStockResearchRead(data)) return <div className="data-gap" role="status">研究候選讀回格式待核實，先核對原記錄。</div>
  if (data.research_read === undefined) return <div className="small-note">舊版回應未提供研究候選讀回狀態。</div>
  const state = data.research_read
  return <section className="panel research-block"><h3>研究候選 · 只讀記錄</h3>
    <p className="small-note">本窗 {state.candidate_count} 筆，最多 20 筆；固定要求仍為兩種策略。讀值語法不證來源、可得時間或成立條件。</p>
    {state.unlocated_count > 0 && <div className="data-gap">全標的有 {state.unlocated_count} 筆候選日期無法定位（記錄 #{state.unlocated_signal_id}）；研究結論待核實。</div>}
    {state.identity_unlocated_count > 0 && <div className="data-gap">全標的有 {state.identity_unlocated_count} 筆策略身分無法定位（記錄 #{state.identity_unlocated_signal_id}）；研究結論待核實。</div>}
    {data.signals.length ? <div className="research-list">{data.signals.map((row) => <div className="research-list-item" key={row.id}>
      <strong>記錄 #{row.id} · {row.strategy.name === 'breakout_v1' ? '突破條件' : row.strategy.name === 'pullback_v1' ? '回踩條件' : row.strategy.name ?? '策略身分待核實'}</strong>
      <span className="small-note">日期 {formatResearchDate(row.signal_date)} · 版本 {row.strategy.version ?? '待核實'} · 原狀態 {row.status ?? '待核實'}</span>
      <span>{row.signal_read.status === 'invalid' ? '候選讀值無效，先核對原記錄。' : row.signal_read.status === 'missing' ? '必要讀值未提供。' : '儲存讀值語法已分類，尚不代表研究條件成立。'}</span>
      {Object.values(row.signal_read.metadata_fields).includes('invalid') && <span className="small-note">部分欄位待核實；可選顯示欄位不單獨否定其他完整策略。</span>}
    </div>)}</div> : <div className="empty">本截止範圍尚無研究候選。</div>}
  </section>
}

function numberLabel(value: number | null | undefined, digits = 0): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('zh-TW', { maximumFractionDigits: digits })
    : '待核實'
}

function sourceLabel(value: string | null | undefined): string {
  const source = value?.trim() ?? ''
  return source === 'canonical' ? '固定研究規則' : source === 'twse' ? '臺灣證券交易所' : source === 'tpex' ? '證券櫃檯買賣中心' : /[\u3400-\u9fff]/.test(source) ? source : '來源待核實'
}

function sourceKindLabel(value: string | null | undefined): string {
  const kind = value?.trim() ?? ''
  const normalized = kind.toLowerCase()
  if (['official', 'government', 'regulator', 'exchange', 'official_notice', 'official_dataset'].includes(normalized)) return '官方資料'
  if (['media', 'news', 'press', 'media_article'].includes(normalized)) return '媒體來源'
  return /[\u3400-\u9fff]/.test(kind) ? kind : '來源類型待核實'
}

function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value?.trim()) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

function ChipEvidence({ rows }: { rows: InstrumentDetail['chips'] }) {
  const recent = recentByDate(rows, 20)
  if (!recent.length) return <div className="empty">尚無官方籌碼資料；策略判斷資料待補。</div>
  return (
    <div className="table-wrap compact-table research-table">
      <table>
        <thead><tr><th>資料日</th><th>外資淨買賣超</th><th>投信淨買賣超</th><th>自營商淨買賣超</th><th>融資餘額變化</th><th>來源</th><th>資料截至</th></tr></thead>
        <tbody>{recent.map((row, index) => <tr key={`${row.date}-${index}`}>
          <td>{formatResearchDate(row.date)}</td>
          <td className="numeric-cell">{formatTableChip(row.foreign_buy, row.source)}</td>
          <td className="numeric-cell">{formatTableChip(row.trust_buy, row.source)}</td>
          <td className="numeric-cell">{formatTableChip(row.dealer_buy, row.source)}</td>
          <td className="numeric-cell">{formatTableChip(row.margin_change, row.source, true)}</td>
          <td>{sourceLabel(row.source)}</td>
          <td>{formatResearchDateTime(row.data_as_of)}</td>
        </tr>)}</tbody>
      </table>
      <div className="small-note">單位：張。法人正值為買超、負值為賣超；融資正值為餘額增加、負值為減少。空白表示未提供資料、數值無效或來源單位待核實。</div>
    </div>
  )
}

function GroupEvidence({ rows }: { rows: InstrumentDetail['groups'] }) {
  if (!rows.length) return <div className="empty">尚無可顯示的族群歸屬。</div>
  return <div className="research-list">{rows.map((group) => {
    const needsTemporaryVerification = isTemporaryIndustryGroupName(group.name)
    return <div className="research-list-item" key={`${group.id}-${group.valid_from}`}>
    <strong>{needsTemporaryVerification ? '既有產業族群關聯（待核實）' : groupDisplayName(group.name)}</strong>
    <span className="small-note">有效期間：{formatResearchDate(group.valid_from)}～{group.valid_to ? formatResearchDate(group.valid_to) : '截止日未提供'}</span>
    {needsTemporaryVerification && <details className="technical-details"><summary>既有資料</summary><div>既有名稱：{group.name}</div><div>既有識別碼：{group.id}</div><div>既有成員有效期間：{formatResearchDate(group.valid_from)}～{group.valid_to ? formatResearchDate(group.valid_to) : '截止日未提供'}</div></details>}
  </div>})}</div>
}

function NewsEvidence({ rows }: { rows: NewsItem[] }) {
  if (!rows.length) return <div className="empty">尚無個股相關新聞。</div>
  return <div className="research-list">{rows.map((item) => {
    const times = newsTimeLabels(item)
    const sourceUrl = safeExternalUrl(item.source?.url)
    return <article className="research-news-item" key={item.id}>
      <div className="small-note">事件時間：{times.event} · 發布時間：{times.published}</div>
      <strong>{item.title}</strong>
      <p>{item.summary ?? item.description ?? '來源未提供新聞內容。'}</p>
      <div className="small-note">來源類型：{sourceKindLabel(item.source_kind)} · 來源：{sourceLabel(item.source_name || item.source?.name)} · 資料截至：{times.dataAsOf} · 蒐集：{times.collected}</div>
      <div className="research-links">
        <Link className="text-link" to={`/news/${encodeURIComponent(item.id)}`}>查看新聞詳情</Link>
        {sourceUrl ? <a className="text-link" href={sourceUrl} target="_blank" rel="noreferrer">查看來源</a> : <span className="small-note">來源連結未提供</span>}
      </div>
    </article>
  })}</div>
}

function EventEvidence({ rows }: { rows: EventRow[] }) {
  if (!rows.length) return <div className="empty">尚無個股事件紀錄。</div>
  return <div className="research-list">{rows.map((item, index) => {
    const times = eventTimeLabels(item)
    return <div className="research-list-item" key={`${item.date}-${item.type}-${index}`}>
      <div className="small-note">事件日：{times.eventDate} · 資料截至：{times.dataAsOf}</div>
      <strong>{item.title}</strong>
      <span className="small-note">類型：{item.type || '未提供'} · 來源：{sourceLabel(item.source)}</span>
      {item.description && <p>{item.description}</p>}
    </div>
  })}</div>
}

function StrategyEvidence({ conditions }: { conditions: InstrumentDetail['strategy_conditions'] }) {
  const entries = Object.entries(conditions)
  if (!entries.length) return <div className="empty">尚無策略條件快照。</div>
  return <div className="research-list">{entries.map(([name, condition]) => <div className="research-list-item research-condition" key={name}>
    <div className="position-head"><strong>{name === 'breakout' ? '突破條件' : name === 'pullback' ? '回踩條件' : '策略條件待核實'}</strong><span className="small-note">來源：{sourceLabel(condition.source)}</span></div>
    <div className="small-note">必要條件（僅列出要求，不代表已通過）</div>
    <div className="tag-list">{condition.requires.map((field) => <span className="tag" key={field}>{researchRequirementLabel(field)}</span>)}</div>
    {condition.technical && <details className="technical-details"><summary>查看技術資訊</summary>{Object.entries(condition.technical).map(([key, value]) => <div key={key}>{key}：{value}</div>)}</details>}
  </div>)}</div>
}

export function StockResearchPanel({ data }: { data: StockDetailData }) {
  const inventory = summarizeStockResearch(data)
  return (
    <section className="stock-research-panel" aria-labelledby="stock-research-title">
      <div className="section-head">
        <div>
          <div className="eyebrow">研究條件 · 只讀快照</div>
          <h2 id="stock-research-title">族群與策略條件</h2>
        </div>
        <span className="small-note">族群 {inventory.groups} · 策略 {inventory.strategies}</span>
      </div>
      <div className="research-evidence-grid">
        <section className="panel research-block"><h3>族群歸屬</h3><GroupEvidence rows={data.groups} /></section>
        <section className="panel research-block"><h3>策略條件快照</h3><StrategyEvidence conditions={data.strategy_conditions} /></section>
      </div>
      <ResearchCandidates data={data} />
      {inventory.unknownTimes > 0 && <div className="chart-warning research-time-warning" role="status">部分證據時間格式或時區未確認；畫面保留「待核實」，不將其升格為確定時間。</div>}
    </section>
  )
}
