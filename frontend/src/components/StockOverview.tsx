import type { StockOverviewData } from '../types'
import { formatResearchDate, formatResearchDateTime } from '../stockResearch'

const REASONS: Record<string, string> = {
  price_source_not_admitted: '這筆行情來源與用途尚待核對',
  price_ingestion_provenance_missing: '缺少合格的收集紀錄關聯',
  price_raw_evidence_missing: '缺少可回指的原始資料與擷取證據',
  price_registry_pin_mismatch: '來源清單版本或雜湊不一致',
  price_body_hash_mismatch: '原始資料雜湊不一致',
  price_receipt_invalid: '擷取紀錄格式無效',
  price_receipt_mismatch: '擷取紀錄與來源、版本或原始資料不一致',
  price_receipt_http_invalid: '擷取紀錄未確認成功回應',
  price_attribution_mismatch: '缺少一致的來源與授權註記',
  price_conditions_mismatch: '擷取限制執行證據不一致',
  price_capture_time_mismatch: '擷取時間與原始資料紀錄不一致',
  price_raw_date_mismatch: '原始資料日期不一致',
  price_evidence_changed: '驗證期間來源檔案發生變更',
  price_purpose_not_admitted: '來源的研究使用條件尚待核對',
  price_identity_date_mismatch: '標的或行情日期與原件不一致',
  price_suspended: '這筆行情標示為停牌',
  price_invalid_ohlc: '開高低收數值或範圍無效',
  price_invalid_volume: '成交量缺失或不是有效非負整數',
  price_selected_row_invalid: '原件中的選中標的缺失或數值無效',
  price_selected_value_mismatch: '行情數值與選中原件不一致',
  price_turnover_state_mismatch: '成交額或可得狀態與原件不一致',
  price_data_date_mismatch: '行情資料日與選中原件不一致',
  price_duplicate_date: '重複日期的行情全部拒用',
  price_evidence_invalid: '來源證據無法完整驗證',
  price_no_rows_before_cutoff: '截止日期以前沒有行情資料',
  price_latest_before_cutoff: '最新可用行情早於研究截止日期',
  institutional_sources_not_admitted: '法人資料的來源與完整性尚待核對',
  trading_session_source_not_admitted: '缺少已核對的交易日基準',
  strategy_input_sources_not_admitted: '策略所需法人、成交額與族群資料尚待核對',
  strategy_time_evidence_not_verified: '策略輸入與結果的時間證據尚未驗收',
  industry_membership_not_verified: '既有族群關聯待重新核實',
  strategy_result_missing: '截止日期以前沒有這個版本的策略結果',
  strategy_result_before_cutoff: '既有策略結果早於本次截止日期',
  event_capture_consumer_not_verified: '官方事件原件與讀取結果尚待核對',
  event_source_time_not_verified: '事件來源與發布／事件時間尚未完整驗證',
}

export function overviewReason(reason: string): string {
  if (reason.startsWith('body_')) return '原始資料檔案不可讀、不穩定或不符合檔案驗證條件'
  if (reason.startsWith('receipt_')) return '擷取紀錄檔案不可讀、不穩定或不符合檔案驗證條件'
  return REASONS[reason] ?? '來源證據尚待核對'
}

function number(value: number | null, digits = 2): string {
  return value != null && Number.isFinite(value) ? value.toLocaleString('zh-TW', { maximumFractionDigits: digits }) : '未提供'
}

function Reasons({ reasons }: { reasons: string[] }) {
  return reasons.length ? <ul className="overview-reasons">{reasons.map((reason) => <li key={reason}>{overviewReason(reason)}</li>)}</ul> : null
}

export function StockOverview({ data, onNews }: { data: StockOverviewData; onNews: () => void }) {
  const price = data.price
  const latest = price.latest
  return <section className="stock-overview" aria-labelledby="stock-overview-title">
    <div className="section-head overview-head"><div><div className="eyebrow">研究總覽</div><h2 id="stock-overview-title">資料截止 {formatResearchDate(data.as_of)}</h2></div><span className="badge">{latest ? '價格來源已核對／部分資料待補' : '研究資料待補'}</span></div>
    <p className="overview-cutoff-note">依資料日期截至的事後研究；不代表歷史當時可得。價格保留原始口徑，尚未提供完整還原鏈。</p>
    <div className="overview-grid">
      <section className="panel overview-price"><h3>價格與實際視窗</h3>
        <p className="small-note">本次最多 {price.window_limit} 筆，收到 {price.candidate_count} 筆、通過 {price.valid_count} 筆；不代表完整交易日窗口。</p>
        {latest ? <>
          <div className="overview-range">可用區間 {formatResearchDate(price.from)} — {formatResearchDate(price.to)}</div>
          <div className="stock-quote-grid"><div><span>最新可用收盤（報價幣別元）</span><strong>{number(latest.close)}</strong></div><div><span>成交量（張）</span><strong>{number(latest.volume / 1000, 3)}</strong></div><div><span>資料日</span><strong>{formatResearchDate(latest.date)}</strong></div></div>
          <div className="overview-ohlc"><span>開 {number(latest.open)}</span><span>高 {number(latest.high)}</span><span>低 {number(latest.low)}</span><span>收 {number(latest.close)}</span></div>
          <p className="small-note">成交額（來源計價單位）：{number(latest.turnover, 0)}{latest.turnover_status !== 'available' && `；原件${latest.turnover_reason === 'missing' ? '缺少成交額' : '成交額無效'}，未補零。`}</p>
          <p className="small-note">來源 <a href={latest.provenance.endpoint} target="_blank" rel="noreferrer">臺灣證券交易所 · STOCK_DAY_ALL</a>；擷取 {formatResearchDateTime(latest.provenance.captured_at)}。本地原件與數值一致，不代表來源真偽或歷史可得性已驗證。</p>
          <details className="technical-details"><summary>查看價格視窗與來源版本</summary>
            <div>總覽版本 {data.version} · 來源版本 {latest.provenance.source_version} · registry {latest.provenance.registry_version}</div>
            <div className="table-wrap"><table><caption>原始價格（各標的報價幣別的元）與成交量（股）；成交額為來源計價單位，空白表示不可用。</caption><thead><tr><th>日期</th><th>開</th><th>高</th><th>低</th><th>收</th><th>成交量</th><th>成交額</th></tr></thead><tbody>{price.bars.map((bar) => <tr key={bar.date}><td>{formatResearchDate(bar.date)}</td><td>{number(bar.open)}</td><td>{number(bar.high)}</td><td>{number(bar.low)}</td><td>{number(bar.close)}</td><td>{number(bar.volume, 0)}</td><td>{bar.turnover == null ? '' : number(bar.turnover, 0)}</td></tr>)}</tbody></table></div>
            {price.bars.map((bar) => <div className="overview-provenance" key={bar.date}>{bar.date} · raw {bar.provenance.raw_payload_id} · 原件 SHA-256 {bar.provenance.body_sha256} · 擷取紀錄 SHA-256 {bar.provenance.receipt_sha256} · 資料時間原值 {bar.data_as_of} · 收集時間原值 {bar.collected_at ?? '未提供'}</div>)}
          </details>
        </> : <div className="data-gap">尚無來源與數值已核對的價格。其餘研究入口可繼續使用。</div>}
        <Reasons reasons={price.reasons} />
        {price.rejected.length > 0 && <details className="technical-details"><summary>未採用 {price.rejected.length} 筆行情的日期與原因</summary>{price.rejected.map((row, index) => <div key={`${row.date}-${index}`}>{formatResearchDate(row.date)}：{overviewReason(row.reason)}（{row.reason}）</div>)}</details>}
      </section>
      <section className="panel"><h3>外資／投信／自營商</h3><div className="badge">資料不足</div><p>最近 5／20 交易日淨買賣超與趨勢尚不可用。</p><Reasons reasons={data.institutional.reasons} /><p className="small-note">各法人獨立計算的來源與交易日條件尚未滿足；缺值不作 0，融資不併入三大法人。</p></section>
      <section className="panel overview-conditions"><h3>研究條件</h3>{data.conditions.map((condition) => <div className="overview-condition" key={condition.strategy}><div className="position-head"><strong>{condition.label}</strong><span className="badge">{condition.status === 'met' ? '成立' : condition.status === 'not_met' ? '未成立' : '資料不足'}</span></div><p className="small-note">既有結果日期 {formatResearchDate(condition.signal_date)}</p><Reasons reasons={condition.reasons} /><details className="technical-details"><summary>查看策略版本</summary>{condition.strategy} · 版本 {condition.version ?? '尚無可核對結果'}</details></div>)}<p className="small-note">沿用既有固定規則；輸入需求不等於條件成立，仍需補齊資料後才能形成完整交易計畫。</p></section>
      <section className="panel"><h3>新聞與官方事件入口</h3><p>保留既有來源連結、發布與事件時間；尚不能把入口中的資料當作已驗收事件或推論價格影響。</p><Reasons reasons={data.events.reasons} /><button type="button" className="secondary-button" onClick={onNews}>查看新聞與公告</button><p className="small-note">新聞採已核對的發布／事件時間截至；未知時間或超過截止的項目不混入本次清單。</p></section>
    </div>
    <details className="technical-details"><summary>研究範圍與總覽版本</summary>總覽版本 {data.version}。M1-P1 僅包含資料日期截止與可追溯的原始價格視窗；完整 M1 的法人窗口、事件與研究條件尚未完成。歷史當時可得（PIT）未支援。</details>
  </section>
}
