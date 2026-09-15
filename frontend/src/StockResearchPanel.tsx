import { Link } from 'react-router-dom'
import { groupDisplayName, researchRequirementLabel } from './presentation'
import { formatTableChip } from './units'
import type { ActionSummary, EventRow, InstrumentDetail, NewsItem } from './types'
import { eventTimeLabels, formatResearchDate, formatResearchDateTime, isTemporaryIndustryGroupName, newsTimeLabels, recentByDate, summarizeStockResearch } from './stockResearch'

type StockDetailData = InstrumentDetail & { news: NewsItem[]; decision_summary?: ActionSummary | null }

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
      {inventory.unknownTimes > 0 && <div className="chart-warning research-time-warning" role="status">部分證據時間格式或時區未確認；畫面保留「待核實」，不將其升格為確定時間。</div>}
    </section>
  )
}
